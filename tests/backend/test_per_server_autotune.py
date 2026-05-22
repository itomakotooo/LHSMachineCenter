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
    def test_loopback_grid_is_higher_than_wan(self):
        """The whole point of per-endpoint grids: loopback can sustain
        more parallel load than WAN. If the loopback grid ever stops
        being strictly more aggressive than WAN, the feature has
        regressed.

        Inject-bug: make _AUTO_GRIDS["loopback"] equal to ["wan"] entry
        → max(loopback robots) == max(wan robots) → assertion fails.
        """
        from src.web_console.backend.app import _auto_grid_for_endpoint
        loop = _auto_grid_for_endpoint("http://127.0.0.1:15060/x")
        wan = _auto_grid_for_endpoint("http://example.com/x")
        assert max(loop["robot_candidates"]) > max(wan["robot_candidates"])
        assert max(loop["concurrency_candidates"]) > max(wan["concurrency_candidates"])

    def test_lan_grid_is_between_loopback_and_wan(self):
        """Sanity: a LAN endpoint gets a grid that is broader than WAN
        but not as aggressive at the top end as loopback."""
        from src.web_console.backend.app import _auto_grid_for_endpoint
        loop = _auto_grid_for_endpoint("http://127.0.0.1:15060/x")
        lan = _auto_grid_for_endpoint("http://192.168.10.21:15060/x")
        wan = _auto_grid_for_endpoint("http://example.com/x")
        assert max(lan["concurrency_candidates"]) >= max(wan["concurrency_candidates"])
        assert max(lan["robot_candidates"]) <= max(loop["robot_candidates"])


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
