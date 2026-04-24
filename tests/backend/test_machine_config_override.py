"""Tests for the per-focused-machine MachineConfig override feature.

Operators maintain local ``machineconfig/<underlying>Cfg.txt`` files
(gitignored) for machines they're currently A/B testing. The
focused-machine detail panel auto-reveals a "use local cfg" checkbox
when the backend finds a matching file; checking the box opts the
next sampling run into passing that file's content as the upstream
``MachineConfig`` field.

Variants of the same underlying share ONE cfg file — ``M273`` and
``M273$WheelSelector$1$1-2-3`` both resolve to ``M273Cfg.txt`` via
the variants_map (no ``$``-splitting shortcut).

Backend contract tested here:
  1. GET /api/machines/{m}/cfg-availability reports file metadata
  2. BatchRunItem.use_local_machine_config=True reads the file and
     sets machine_config server-side; analyzer cmd carries
     --machine-config-file
  3. use_local + missing file → 400 (fail loud, not silent global cfg)
  4. Explicit machine_config string still works (legacy path)
  5. Variants resolve to underlying cfg file

The make_payload / analyzer-side field injection is tested separately;
this file exercises the backend filesystem + endpoint glue.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _run_payload(**overrides):
    base = {
        "machine": "M14",
        "mode": 1,
        "target_halfwidth_pp": 0.5,
        "chunk_spin_times": 5000,
        "chunk_robot_count": 8,
        "batch_concurrency": 8,
        "max_chunks": 120,
        "timeout": 300.0,
        "bankruptcy_session_spins": 500,
        "bankruptcy_bankroll_multipliers": "100,200,500",
        "model_id": "gpt-5.4-mini",
    }
    base.update(overrides)
    return base


@pytest.fixture
def fake_machineconfig_dir(tmp_path, monkeypatch):
    """Redirect MACHINECONFIG_DIR to a tmp dir so tests can stage
    cfg files without polluting the repo-root machineconfig/."""
    import src.web_console.backend.app as app_mod
    d = tmp_path / "machineconfig"
    d.mkdir()
    monkeypatch.setattr(app_mod, "MACHINECONFIG_DIR", d)
    return d


class TestCfgAvailabilityEndpoint:
    def test_no_file_returns_available_false(self, client, fake_machineconfig_dir):
        c, _app = client
        r = c.get("/api/machines/M14/cfg-availability")
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is False
        assert body["machine"] == "M14"
        assert body["underlying"] == "M14"
        assert body["filename"] == "M14Cfg.txt"

    def test_file_present_returns_metadata(
        self, client, fake_machineconfig_dir,
    ):
        (fake_machineconfig_dir / "M14Cfg.txt").write_text(
            '{"marker":"v1"}', encoding="utf-8",
        )
        c, _app = client
        r = c.get("/api/machines/M14/cfg-availability")
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        assert body["underlying"] == "M14"
        assert body["filename"] == "M14Cfg.txt"
        assert body["bytes"] == len('{"marker":"v1"}')
        assert body["mtime_iso"] is not None


class TestUseLocalMachineConfigFlag:
    def test_flag_reads_file_and_sets_machine_config(
        self, client, fake_machineconfig_dir, app_factory,
    ):
        """use_local_machine_config=True + file on disk → analyzer
        subprocess cmd carries --machine-config-file whose target
        contains the file's content."""
        cfg_content = '{"weights": {"r1": [1, 2, 3]}, "marker": "local_v1"}'
        (fake_machineconfig_dir / "M14Cfg.txt").write_text(
            cfg_content, encoding="utf-8",
        )
        c, _app = client
        resp = c.post(
            "/api/batch-run",
            json={
                "items": [
                    {
                        "machine": "M14",
                        "mode": 1,
                        "chunk_spin_times": 1000,
                        "use_local_machine_config": True,
                    }
                ],
                "chunk_robot_count": 8,
                "batch_concurrency": 8,
                "concurrency": 1,
                "max_chunks": 5,
                "timeout": 60.0,
                "target_halfwidth_pp": 0.5,
            },
        )
        assert resp.status_code == 200, resp.text

        import time
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if app_factory.stub_popen.cmds:
                break
            time.sleep(0.05)

        cmds = app_factory.stub_popen.cmds
        assert cmds, "batch worker should have spawned analyzer subprocess"
        cmd = cmds[-1]
        assert "--machine-config-file" in cmd
        idx = cmd.index("--machine-config-file")
        written = Path(cmd[idx + 1]).read_text(encoding="utf-8")
        assert written == cfg_content

    def test_flag_without_file_returns_400(
        self, client, fake_machineconfig_dir,
    ):
        """use_local=True but no file → 400 up front. Better than
        silently sampling against global cfg while UI claims override
        is active."""
        c, _app = client
        resp = c.post(
            "/api/batch-run",
            json={
                "items": [
                    {
                        "machine": "M14",
                        "mode": 1,
                        "chunk_spin_times": 1000,
                        "use_local_machine_config": True,
                    }
                ],
                "chunk_robot_count": 8,
                "batch_concurrency": 8,
                "concurrency": 1,
                "max_chunks": 5,
                "timeout": 60.0,
                "target_halfwidth_pp": 0.5,
            },
        )
        assert resp.status_code == 400
        assert "M14Cfg.txt" in resp.json()["detail"]

    def test_flag_false_omits_file(
        self, client, fake_machineconfig_dir, app_factory,
    ):
        """Default (flag False) + file present → cfg NOT used.
        Only explicit opt-in by the operator activates the override."""
        (fake_machineconfig_dir / "M14Cfg.txt").write_text(
            '{"x":1}', encoding="utf-8",
        )
        c, _app = client
        resp = c.post(
            "/api/batch-run",
            json={
                "items": [{"machine": "M14", "mode": 1, "chunk_spin_times": 1000}],
                "chunk_robot_count": 8, "batch_concurrency": 8,
                "concurrency": 1, "max_chunks": 5, "timeout": 60.0,
                "target_halfwidth_pp": 0.5,
            },
        )
        assert resp.status_code == 200, resp.text

        import time
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if app_factory.stub_popen.cmds:
                break
            time.sleep(0.05)

        assert app_factory.stub_popen.cmds
        cmd = app_factory.stub_popen.cmds[-1]
        assert "--machine-config-file" not in cmd

    def test_explicit_machine_config_wins_over_flag(
        self, client, fake_machineconfig_dir, app_factory,
    ):
        """When machine_config string is explicitly set, it wins even
        if use_local_machine_config=True. Explicit beats inferred —
        rare path, mostly defensive."""
        (fake_machineconfig_dir / "M14Cfg.txt").write_text(
            '{"source":"file"}', encoding="utf-8",
        )
        explicit = '{"source":"explicit"}'
        c, _app = client
        resp = c.post(
            "/api/batch-run",
            json={
                "items": [
                    {
                        "machine": "M14",
                        "mode": 1,
                        "chunk_spin_times": 1000,
                        "machine_config": explicit,
                        "use_local_machine_config": True,
                    }
                ],
                "chunk_robot_count": 8, "batch_concurrency": 8,
                "concurrency": 1, "max_chunks": 5, "timeout": 60.0,
                "target_halfwidth_pp": 0.5,
            },
        )
        assert resp.status_code == 200, resp.text

        import time
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if app_factory.stub_popen.cmds:
                break
            time.sleep(0.05)

        cmd = app_factory.stub_popen.cmds[-1]
        idx = cmd.index("--machine-config-file")
        written = Path(cmd[idx + 1]).read_text(encoding="utf-8")
        assert written == explicit, "explicit string should beat file read"


class TestUnderlyingResolution:
    """Pure helper tests — make_payload + resolve_underlying_for_display
    without spinning up the FastAPI app."""

    def test_non_variant_returns_self(self):
        from src.web_console.backend.machine_variants import (
            resolve_underlying_for_display,
        )
        rows = [
            {"machine": "M14", "upstream_key": "M14"},
            {"machine": "M15", "upstream_key": "M15"},
        ]
        assert resolve_underlying_for_display("M14", rows, {}) == "M14"
        assert resolve_underlying_for_display("M15", rows, {}) == "M15"

    def test_variant_resolves_through_variants_map(self):
        """Display name 'M273$WheelSelector$1$1-2-3' has
        upstream_key 'M273$1$1-2-3'; variants_map maps that upstream
        key to the underlying 'M273'. No $ splitting involved."""
        from src.web_console.backend.machine_variants import (
            resolve_underlying_for_display,
        )
        rows = [
            {
                "machine": "M273$WheelSelector$1$1-2-3",
                "upstream_key": "M273$1$1-2-3",
            },
        ]
        variants_map = {"M273$1$1-2-3": "M273"}
        assert (
            resolve_underlying_for_display(
                "M273$WheelSelector$1$1-2-3", rows, variants_map,
            )
            == "M273"
        )

    def test_unknown_display_falls_through(self):
        """Row not found → display name returned as-is. This keeps
        the availability endpoint predictable (it'll just report no
        file exists for that name) rather than 500'ing."""
        from src.web_console.backend.machine_variants import (
            resolve_underlying_for_display,
        )
        assert resolve_underlying_for_display("M999", [], {}) == "M999"

    def test_variant_shares_cfg_file_with_siblings(
        self, client, fake_machineconfig_dir, tmp_path, monkeypatch,
    ):
        """Two variants of M273 both see M273Cfg.txt as available."""
        import src.web_console.backend.app as app_mod
        # Stage machines.json with two M273 variants.
        fake_machines = tmp_path / "machines.json"
        fake_machines.write_text(json.dumps({
            "machines": [
                {"machine": "M14", "upstream_key": "M14"},
                {
                    "machine": "M273$WheelSelector$1$1-2-3",
                    "upstream_key": "M273$1$1-2-3",
                },
                {
                    "machine": "M273$WheelSelector$1$1-4-5",
                    "upstream_key": "M273$1$1-4-5",
                },
            ],
        }), encoding="utf-8")
        fake_halls = tmp_path / "machine_halls.json"
        fake_halls.write_text(json.dumps({
            "variants_map": {
                "M273$1$1-2-3": "M273",
                "M273$1$1-4-5": "M273",
            },
        }), encoding="utf-8")
        monkeypatch.setattr(app_mod, "MACHINES_CONFIG", fake_machines)
        # The helper reads halls_path via argument default, but
        # load_variants_map is loaded with a default = ROOT/..., so we
        # have to patch the ROOT-based default via the helper's path
        # argument. Easiest is to call _resolve_local_cfg_for_machine
        # directly with both paths.
        (fake_machineconfig_dir / "M273Cfg.txt").write_text(
            '{"marker":"m273"}', encoding="utf-8",
        )
        for display in (
            "M273$WheelSelector$1$1-2-3",
            "M273$WheelSelector$1$1-4-5",
        ):
            underlying, path = app_mod._resolve_local_cfg_for_machine(
                display,
                machines_config_path=fake_machines,
                halls_path=fake_halls,
            )
            assert underlying == "M273"
            assert path is not None
            assert path.name == "M273Cfg.txt"


class TestMakePayloadInjectsMachineConfigField:
    """Wire-level check — the analyzer's make_payload adds
    `MachineConfig` iff a non-empty string is passed. This is what
    proves the override actually reaches upstream."""

    def test_non_empty_machine_config_adds_field(self):
        from fresh_slotlab.player_impact_analyzer import make_payload
        p = make_payload(
            machine="M14", rtp_mode=1, bet=1000, spin_times=100,
            robot_count=1, init_credits=10**14,
            reset_each_spin=True, continue_after_bankrupt=True,
            machine_config='{"x":1}',
        )
        assert p.get("MachineConfig") == '{"x":1}'

    def test_none_machine_config_omits_field(self):
        from fresh_slotlab.player_impact_analyzer import make_payload
        for empty in (None, ""):
            p = make_payload(
                machine="M14", rtp_mode=1, bet=1000, spin_times=100,
                robot_count=1, init_credits=10**14,
                reset_each_spin=True, continue_after_bankrupt=True,
                machine_config=empty,
            )
            assert "MachineConfig" not in p
