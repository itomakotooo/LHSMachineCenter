"""Tests for the per-focused-machine MachineConfig override feature.

Focused-machine sampling flow lets operators upload a local JSON file
that is passed to every upstream request as the `MachineConfig`
payload field — designer A/B testing without a server deploy.

The backend's side of that contract:
  1. /api/runs accepts `machine_config` as JSON string.
  2. RunManager persists the string to a file under the run's output
     dir and passes ``--machine-config-file <path>`` to the analyzer
     subprocess.
  3. BatchRunItem accepts a per-item `machine_config` that flows
     through BatchRunManager → RunCreateRequest the same way.

The analyzer's side (reading the file + injecting into every payload)
is unit-tested via make_payload tests; here we only assert the
backend-subprocess glue since that's the new surface.
"""
from __future__ import annotations

from pathlib import Path


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


class TestMachineConfigOverrideOnSingleRun:
    def test_non_empty_machine_config_writes_file_and_passes_cli_arg(
        self, client, app_factory
    ):
        """machine_config='{...}' → analyzer cmd carries
        ``--machine-config-file <path>`` and the file on disk matches
        the string the caller sent."""
        c, _app = client
        cfg_json = '{"reel_weights": {"reel1": [1, 2, 3]}, "_probe_marker": "override_v1"}'

        resp = c.post(
            "/api/runs",
            json=_run_payload(machine_config=cfg_json),
        )
        assert resp.status_code == 200, resp.text

        cmds = app_factory.stub_popen.cmds
        assert cmds, "expected RunManager to spawn at least one stub process"
        cmd = cmds[-1]

        assert "--machine-config-file" in cmd, (
            f"machine_config set → analyzer cmd must carry --machine-config-file; "
            f"got {cmd}"
        )
        idx = cmd.index("--machine-config-file")
        cfg_path = Path(cmd[idx + 1])
        assert cfg_path.is_file(), f"expected config file at {cfg_path}"
        content = cfg_path.read_text(encoding="utf-8")
        assert content == cfg_json, (
            f"file on disk must match POSTed JSON string verbatim; "
            f"got {content!r}"
        )

    def test_empty_machine_config_omits_cli_arg(self, client, app_factory):
        """Default / empty machine_config → no --machine-config-file
        flag, so analyzer falls back to server's global cfg.json
        (which is the intended default behavior)."""
        c, _app = client
        resp = c.post(
            "/api/runs",
            json=_run_payload(),  # machine_config defaults to ""
        )
        assert resp.status_code == 200, resp.text

        cmds = app_factory.stub_popen.cmds
        cmd = cmds[-1]
        assert "--machine-config-file" not in cmd, (
            f"empty machine_config → no --machine-config-file arg; got {cmd}"
        )

    def test_omitted_machine_config_field_omits_cli_arg(
        self, client, app_factory
    ):
        """A caller that doesn't even send the `machine_config` field
        (older client, curl script) still works — pydantic default
        kicks in and we emit no flag."""
        c, _app = client
        payload = _run_payload()
        payload.pop("machine_config", None)  # ensure field absent, not just empty
        resp = c.post("/api/runs", json=payload)
        assert resp.status_code == 200, resp.text

        cmd = app_factory.stub_popen.cmds[-1]
        assert "--machine-config-file" not in cmd


class TestMachineConfigOverrideOnBatchRun:
    def test_batch_item_machine_config_flows_to_analyzer_cmd(
        self, client, app_factory
    ):
        """BatchRunItem.machine_config on a single-item batch ends up
        as --machine-config-file on the per-item analyzer subprocess.
        Mirrors the focused-machine frontend flow (items.length === 1,
        staged cfg → item.machine_config)."""
        c, _app = client
        cfg_json = '{"marker": "batch_override_v1"}'

        resp = c.post(
            "/api/batch-run",
            json={
                "items": [
                    {
                        "machine": "M14",
                        "mode": 1,
                        "chunk_spin_times": 1000,
                        "machine_config": cfg_json,
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

        # Wait for the batch worker thread to actually spawn the run
        # subprocess (it happens async in a separate thread).
        import time
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if app_factory.stub_popen.cmds:
                break
            time.sleep(0.05)

        cmds = app_factory.stub_popen.cmds
        assert cmds, "batch should have spawned at least one analyzer subprocess"
        cmd = cmds[-1]
        assert "--machine-config-file" in cmd, (
            f"batch-item machine_config must reach analyzer cmd; got {cmd}"
        )
        idx = cmd.index("--machine-config-file")
        assert Path(cmd[idx + 1]).read_text(encoding="utf-8") == cfg_json

    def test_batch_item_without_machine_config_omits_arg(
        self, client, app_factory
    ):
        """Multi-machine batches (or single item without override) must
        NOT carry the flag — cross-machine cfg reuse is almost always
        wrong, and the absent flag tells the analyzer to use global cfg."""
        c, _app = client
        resp = c.post(
            "/api/batch-run",
            json={
                "items": [
                    {"machine": "M14", "mode": 1, "chunk_spin_times": 1000}
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

        assert app_factory.stub_popen.cmds, "batch should have spawned subprocess"
        cmd = app_factory.stub_popen.cmds[-1]
        assert "--machine-config-file" not in cmd


class TestMakePayloadInjectsMachineConfigField:
    def test_non_empty_machine_config_adds_field(self):
        """make_payload in the analyzer adds ``MachineConfig`` to the
        outgoing upstream payload iff a non-empty string is passed.
        This is the actual wire-level assertion — everything else is
        plumbing to get the string here."""
        from fresh_slotlab.player_impact_analyzer import make_payload

        p = make_payload(
            machine="M14",
            rtp_mode=1,
            bet=1000,
            spin_times=100,
            robot_count=1,
            init_credits=10**14,
            reset_each_spin=True,
            continue_after_bankrupt=True,
            machine_config='{"x": 1}',
        )
        assert p.get("MachineConfig") == '{"x": 1}'

    def test_none_machine_config_omits_field(self):
        """Absent or empty string → the field must NOT appear on the
        payload at all (its presence alone is the server's "override
        this request" signal)."""
        from fresh_slotlab.player_impact_analyzer import make_payload

        for empty in (None, ""):
            p = make_payload(
                machine="M14",
                rtp_mode=1,
                bet=1000,
                spin_times=100,
                robot_count=1,
                init_credits=10**14,
                reset_each_spin=True,
                continue_after_bankrupt=True,
                machine_config=empty,
            )
            assert "MachineConfig" not in p, (
                f"empty/None machine_config must NOT add the field; "
                f"got {p!r} for empty={empty!r}"
            )
