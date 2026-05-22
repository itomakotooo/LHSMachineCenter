"""Per-server autotune persistence + endpoint-aware probe grid (2026-05-22).

Covers four threads of the same feature:

  1. Endpoint classification — loopback / LAN / WAN bucketing for a URL.
  2. Auto-grid preset — which candidate grid each kind picks.
  3. Persistence helpers — _save_server_tuning round-trips through
     _load_settings + _load_server_tuning preserves the recommendation
     and survives an unrelated _save_settings (no clobbering of other
     fields like min_retention_spins / default_server).
  4. GET /api/servers/{id}/tuning — empty when nothing saved; reflects
     the most-recent _save_server_tuning otherwise.

The full HTTP /api/autotune flow that actually runs a probe is NOT
exercised here — that requires a real upstream slot simulator. The
saved-side of that flow is covered via the persistence test directly.

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md) are
inline in each test docstring.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── 1. Endpoint classification ─────────────────────────────────────


class TestClassifyEndpointKind:
    @pytest.mark.parametrize("url, expected", [
        ("http://127.0.0.1:15060/MachineTest/x", "loopback"),
        ("http://localhost:15060/MachineTest/x", "loopback"),
        ("http://[::1]:15060/MachineTest/x", "loopback"),
        ("http://192.168.10.21:15060/MachineTest/x", "lan"),
        ("http://10.0.0.5:80/foo", "lan"),
        ("http://172.16.0.1/foo", "lan"),
        ("http://172.31.255.254/foo", "lan"),
        ("http://172.32.0.1/foo", "wan"),  # 172.32 is OUTSIDE RFC1918
        ("http://172.15.0.1/foo", "wan"),  # 172.15 is OUTSIDE RFC1918
        ("http://116.232.103.19:10288/foo", "wan"),
        ("http://example.com/foo", "wan"),
        ("", "wan"),
        ("not a url at all", "wan"),
    ])
    def test_classify(self, url: str, expected: str):
        """Inject-bug: drop the RFC1918 prefix check → 192.168.x.x gets
        classified 'wan' → autotune for the LAN deploy uses the
        WAN-conservative grid → loopback/LAN throughput goes untapped."""
        from src.web_console.backend.app import _classify_endpoint_kind
        assert _classify_endpoint_kind(url) == expected


# ── 2. Auto-grid preset ──────────────────────────────────────────


class TestAutoGridForEndpoint:
    def test_lan_grid_more_aggressive_than_wan(self):
        """LAN has no rate limit + low latency, so a broader probe grid
        is safe. WAN keeps the conservative grid (matches the 2026-04-25
        external-server benchmark documented in AutoTuneRequest).

        Inject-bug: swap _AUTO_GRIDS["lan"] and ["wan"] entries → LAN
        gets the WAN-conservative grid → assertion fails.
        """
        from src.web_console.backend.app import _auto_grid_for_endpoint
        lan = _auto_grid_for_endpoint("http://192.168.10.21:15060/x")
        wan = _auto_grid_for_endpoint("http://example.com/x")
        assert max(lan["concurrency_candidates"]) >= max(wan["concurrency_candidates"])
        assert max(lan["robot_candidates"]) >= max(wan["robot_candidates"])

    def test_loopback_falls_back_to_lan_grid(self):
        """Loopback no longer has its own probe grid — the autotune
        endpoint short-circuits to _LOOPBACK_HARDCODED_TUNING. But the
        _auto_grid_for_endpoint helper still has to return *something*
        sensible for non-autotune callers (none today). The fallback is
        the LAN preset.

        Inject-bug: remove the `if kind == "loopback": return ...`
        fallback → KeyError on _AUTO_GRIDS["loopback"] → test fails.
        """
        from src.web_console.backend.app import _auto_grid_for_endpoint
        loop = _auto_grid_for_endpoint("http://127.0.0.1:15060/x")
        lan = _auto_grid_for_endpoint("http://192.168.10.21:15060/x")
        assert loop == lan


class TestLoopbackHardcodedTuning:
    """Loopback short-circuit: same-machine deployments (slot simulator
    on 127.0.0.1) use _LOOPBACK_HARDCODED_TUNING instead of a probe.

    Why: 2026-05-22 manual probe sweep on the deployed Windows server
    showed throughput ceiling fixed at ~30k spin/s by simulator CPU,
    invariant across r ∈ {2..32}. Probing wastes 2 minutes for zero
    information.
    """

    def test_autotune_endpoint_short_circuits_for_loopback(
        self, client, app_factory, tmp_path, monkeypatch,
    ):
        """POST /api/autotune with use_auto_grid=true against a loopback
        server skips the probe entirely + returns the hardcoded values
        + persists them under the server_id.

        Inject-bug: remove the
            ``if endpoint_kind == "loopback" and wants_auto:``
        short-circuit block in the auto_tune endpoint → the request
        falls through to run_auto_tune, which calls the real
        _post_slot_spin and tries to actually hit the upstream slot
        simulator. In this test there's no server listening on the
        configured endpoint, so the probe either hangs until timeout
        or returns success_rate=0; either way, the assertion
        `hardcoded == True` fails because the short-circuit synthetic
        response wasn't returned.
        """
        import src.web_console.backend.app as app_mod

        # Point SERVERS_CONFIG at a tmp servers.json with intranet
        # mapped to loopback. Operator settings.json picks intranet as
        # the default so _resolve_active_server_id returns it.
        servers_p = tmp_path / "servers.json"
        servers_p.write_text(json.dumps({
            "servers": [
                {"id": "intranet", "active": True,
                 "endpoint": "http://127.0.0.1:15060"},
            ],
            "default_server": "intranet",
        }), encoding="utf-8")
        monkeypatch.setattr(app_mod, "SERVERS_CONFIG", servers_p)

        # Make sure the operator override agrees so the resolver
        # returns "intranet" deterministically (the app fixture's
        # settings.json may already have a default_server from prior
        # tests; explicit write here resets it).
        settings_path = Path(app_factory.state_dir) / "settings.json"
        from src.web_console.backend.app import _load_settings, _save_settings
        s = _load_settings(settings_path)
        s["default_server"] = "intranet"
        _save_settings(settings_path, s)

        c, _app = client
        resp = c.post("/api/autotune", json={
            "machine": "M14",
            "mode": 1,
            "spin_times": 200,
            "rounds": 2,
            "timeout": 60,
            "bet": 1000,
            "use_auto_grid": True,
            "robot_candidates": [],
            "concurrency_candidates": [],
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 1. Synthetic response shape
        assert body.get("hardcoded") is True
        assert body.get("endpoint_kind") == "loopback"
        assert body.get("tested") == 0
        assert body.get("results") == []
        # 2. Recommendation matches the constant
        assert body["recommendation"]["chunk_robot_count"] == (
            app_mod._LOOPBACK_HARDCODED_TUNING["chunk_robot_count"]
        )
        assert body["recommendation"]["batch_concurrency"] == (
            app_mod._LOOPBACK_HARDCODED_TUNING["batch_concurrency"]
        )
        # 3. Persisted against the server_id — fetch back via
        #    /api/servers/{id}/tuning to prove the save path ran.
        tuning_resp = c.get("/api/servers/intranet/tuning")
        assert tuning_resp.status_code == 200
        saved = tuning_resp.json()
        assert saved["chunk_robot_count"] == (
            app_mod._LOOPBACK_HARDCODED_TUNING["chunk_robot_count"]
        )
        assert saved["batch_concurrency"] == (
            app_mod._LOOPBACK_HARDCODED_TUNING["batch_concurrency"]
        )
        assert saved["endpoint_kind"] == "loopback"
        assert saved["probe"].get("hardcoded") is True

    def test_constant_has_sensible_values(self):
        """Smoke: the hardcoded constant exists with positive ints
        matching what the data justified (small robot count, high
        concurrency — the inverse of the WAN-optimal direction).

        Inject-bug: change _LOOPBACK_HARDCODED_TUNING values to e.g.
        {"chunk_robot_count": 32, "batch_concurrency": 4} (the WAN-
        optimal shape) → assertion fails because robot_count > 8.
        """
        from src.web_console.backend.app import _LOOPBACK_HARDCODED_TUNING
        assert _LOOPBACK_HARDCODED_TUNING["chunk_robot_count"] > 0
        assert _LOOPBACK_HARDCODED_TUNING["batch_concurrency"] > 0
        # Sanity: data showed small-robot wins. If this assertion fires,
        # someone reverted the direction without updating the constant's
        # docstring justification.
        assert _LOOPBACK_HARDCODED_TUNING["chunk_robot_count"] <= 8, (
            "loopback ceiling is set by simulator CPU not network; "
            "high robot count just trades latency for nothing — see "
            "the docstring on _LOOPBACK_HARDCODED_TUNING for the 2026-"
            "05-22 measurement"
        )
        assert _LOOPBACK_HARDCODED_TUNING["batch_concurrency"] >= 8, (
            "loopback rewards concurrency since simulator workers "
            "process in parallel; conc<8 leaves the CPU pool unused"
        )


# ── 3. Persistence round-trip ────────────────────────────────────


class TestServerTuningPersistence:
    def test_round_trip_preserves_recommendation(self, tmp_path: Path):
        """_save_server_tuning → _load_server_tuning preserves the
        recommendation fields with no munging.

        Inject-bug: in _save_server_tuning, swap chunk_robot_count and
        batch_concurrency → round-trip returns wrong values → assertion
        fails because saved 'chunk_robot_count' shows up as 12 (the
        batch_concurrency we passed) instead of 24.
        """
        from src.web_console.backend.app import (
            _load_server_tuning,
            _save_server_tuning,
        )
        sp = tmp_path / "settings.json"
        _save_server_tuning(
            sp, "intranet",
            chunk_robot_count=24, batch_concurrency=12,
            endpoint_kind="loopback",
            probe={"machine": "M14", "mode": 1, "success_rate": 0.95,
                   "throughput_spins_per_sec": 18432.0},
        )
        loaded = _load_server_tuning("intranet", sp)
        assert loaded["chunk_robot_count"] == 24
        assert loaded["batch_concurrency"] == 12
        assert loaded["endpoint_kind"] == "loopback"
        assert loaded["probe"]["machine"] == "M14"

    def test_save_does_not_clobber_other_settings(self, tmp_path: Path):
        """Tuning the intranet server must not corrupt unrelated fields
        like min_retention_spins or default_server.

        Inject-bug: in _save_server_tuning, replace `_load_settings(sp)`
        with `{}` → other fields wiped → assertion fails because
        min_retention_spins reverts to the schema default.
        """
        from src.web_console.backend.app import (
            _load_settings,
            _save_server_tuning,
            _save_settings,
        )
        sp = tmp_path / "settings.json"
        _save_settings(sp, {
            "min_retention_spins": 75000,
            "default_server": "prod",
        })
        _save_server_tuning(
            sp, "intranet",
            chunk_robot_count=24, batch_concurrency=12,
            endpoint_kind="loopback",
        )
        after = _load_settings(sp)
        assert after["min_retention_spins"] == 75000, (
            "min_retention_spins clobbered by autotune save"
        )
        assert after["default_server"] == "prod", (
            "default_server clobbered by autotune save"
        )
        assert "intranet" in (after["server_tuning"] or {})

    def test_save_multiple_servers_each_persisted_separately(self, tmp_path: Path):
        """Tuning intranet must not erase a prior tune for prod."""
        from src.web_console.backend.app import (
            _load_server_tuning,
            _save_server_tuning,
        )
        sp = tmp_path / "settings.json"
        _save_server_tuning(
            sp, "prod",
            chunk_robot_count=8, batch_concurrency=8,
            endpoint_kind="wan",
        )
        _save_server_tuning(
            sp, "intranet",
            chunk_robot_count=24, batch_concurrency=12,
            endpoint_kind="loopback",
        )
        assert _load_server_tuning("prod", sp)["chunk_robot_count"] == 8
        assert _load_server_tuning("intranet", sp)["chunk_robot_count"] == 24

    def test_load_missing_server_returns_empty_dict(self, tmp_path: Path):
        """A server that has never been autotuned returns {} (not None,
        not an exception), so caller-side ``tuning or {default}`` idiom
        works.

        Inject-bug: change return to None → caller's
        `tuning["chunk_robot_count"]` raises KeyError.
        """
        from src.web_console.backend.app import _load_server_tuning
        sp = tmp_path / "settings.json"
        result = _load_server_tuning("nonexistent", sp)
        assert result == {}

    def test_load_drops_corrupt_entries(self, tmp_path: Path):
        """If settings.json has a server_tuning entry with non-positive
        ints, _load_settings drops it on read so caller never sees a
        bogus value. Pure defense-in-depth — autotune never writes
        these — but a hand-edited settings.json would otherwise hit
        the resolver.

        Inject-bug: in _load_settings server_tuning parser, change
        `rc > 0` to `rc >= 0` → 0-valued entries leak through → caller
        gets chunk_robot_count=0 which the gt=0 batch validator rejects
        with a confusing 422.
        """
        from src.web_console.backend.app import _load_server_tuning
        sp = tmp_path / "settings.json"
        sp.write_text(json.dumps({
            "server_tuning": {
                "good": {"chunk_robot_count": 16, "batch_concurrency": 8},
                "bad_zero": {"chunk_robot_count": 0, "batch_concurrency": 8},
                "bad_neg": {"chunk_robot_count": -1, "batch_concurrency": 8},
                "bad_str": {"chunk_robot_count": "x", "batch_concurrency": 8},
                "bad_shape": "not a dict",
            },
        }), encoding="utf-8")
        assert _load_server_tuning("good", sp)["chunk_robot_count"] == 16
        assert _load_server_tuning("bad_zero", sp) == {}
        assert _load_server_tuning("bad_neg", sp) == {}
        assert _load_server_tuning("bad_str", sp) == {}
        assert _load_server_tuning("bad_shape", sp) == {}


# ── 4. HTTP endpoint ─────────────────────────────────────────────


class TestGetServerTuningEndpoint:
    def test_returns_empty_when_never_tuned(self, client):
        c, _app = client
        resp = c.get("/api/servers/intranet/tuning")
        assert resp.status_code == 200
        assert resp.json() == {}

    def test_returns_saved_tuning(self, client, app_factory):
        """After _save_server_tuning lands in the app's settings.json,
        the HTTP endpoint returns the same payload.

        Inject-bug: in the get_server_tuning_endpoint handler, return
        `{}` regardless → assertion fails because chunk_robot_count
        comes back as KeyError / None.
        """
        from src.web_console.backend.app import _save_server_tuning
        c, _app = client
        # Reach the same settings_path that create_app's closure uses
        # by going through app.state (set in create_app for the run).
        # The fixture installs state_dir under tmp_path, so settings.json
        # lives at app.state.state_dir / "settings.json".
        settings_path = Path(app_factory.state_dir) / "settings.json"
        _save_server_tuning(
            settings_path, "intranet",
            chunk_robot_count=24, batch_concurrency=12,
            endpoint_kind="loopback",
            probe={"machine": "M14", "mode": 1, "success_rate": 0.96,
                   "throughput_spins_per_sec": 18000.0},
        )
        resp = c.get("/api/servers/intranet/tuning")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["chunk_robot_count"] == 24
        assert payload["batch_concurrency"] == 12
        assert payload["endpoint_kind"] == "loopback"
        assert payload["probe"]["machine"] == "M14"
