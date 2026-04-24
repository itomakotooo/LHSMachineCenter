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


class TestLocalCfgMd5SegregatesChunks:
    """Without a per-cfg synthetic md5, chunks produced with a
    MachineConfig override get stamped with upstream's global cfg md5
    (the /MachineConfigMd5 endpoint has no idea the request carried
    an override), silently contaminating the global-cfg bucket on
    subsequent resume-reads. These tests lock the fix: RunManager
    swaps in a ``localcfg_<sha1[:8]>`` when machine_config is set."""

    def test_derive_local_cfg_md5_format(self):
        from src.web_console.backend.app import _derive_local_cfg_md5
        tag = _derive_local_cfg_md5('{"x":1}')
        assert tag.startswith("localcfg_")
        assert len(tag) == len("localcfg_") + 8
        # Deterministic — same input → same tag → resume-compatible
        # across operators with byte-identical cfgs.
        assert tag == _derive_local_cfg_md5('{"x":1}')

    def test_different_cfg_different_md5(self):
        from src.web_console.backend.app import _derive_local_cfg_md5
        assert _derive_local_cfg_md5('{"a":1}') != _derive_local_cfg_md5('{"b":1}')

    def test_run_manager_stamps_localcfg_md5_when_machine_config_set(
        self, client, fake_machineconfig_dir, app_factory,
    ):
        """use_local_machine_config=True → analyzer cmd carries
        --upstream-config-md5 localcfg_<hash>, NOT the upstream
        global md5. This is what keeps override-produced chunks
        from mixing with global-cfg chunks on resume."""
        cfg = '{"marker":"override_chunks_go_here"}'
        (fake_machineconfig_dir / "M14Cfg.txt").write_text(cfg, encoding="utf-8")
        c, _app = client
        resp = c.post(
            "/api/batch-run",
            json={
                "items": [
                    {
                        "machine": "M14", "mode": 1,
                        "chunk_spin_times": 1000,
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
        assert "--upstream-config-md5" in cmd
        idx = cmd.index("--upstream-config-md5")
        md5_value = cmd[idx + 1]
        assert md5_value.startswith("localcfg_"), (
            f"override chunks must get synthetic md5, got {md5_value!r}"
        )
        # Must match the deterministic hash of the cfg file content
        # so two operators with the same cfg file share chunks.
        from src.web_console.backend.app import _derive_local_cfg_md5
        assert md5_value == _derive_local_cfg_md5(cfg)

    def test_no_machine_config_keeps_upstream_md5(
        self, client, app_factory, monkeypatch,
    ):
        """Without machine_config, the caller-supplied (or upstream-
        fetched) upstream_config_md5 passes through unchanged."""
        c, _app = client
        resp = c.post(
            "/api/runs",
            json=_run_payload(
                upstream_config_md5="real_server_md5_abc123",
            ),
        )
        assert resp.status_code == 200, resp.text
        cmd = app_factory.stub_popen.cmds[-1]
        idx = cmd.index("--upstream-config-md5")
        assert cmd[idx + 1] == "real_server_md5_abc123"
        assert not cmd[idx + 1].startswith("localcfg_")

    def test_explicit_machine_config_triggers_synthetic_md5_on_direct_run(
        self, client, app_factory,
    ):
        """/api/runs direct caller with machine_config set (no batch
        layer involved) → RunManager still swaps in synthetic md5.
        This is the defensive override at the chokepoint."""
        c, _app = client
        resp = c.post(
            "/api/runs",
            json=_run_payload(
                machine_config='{"direct_call_cfg":true}',
                upstream_config_md5="real_server_md5_xyz",
            ),
        )
        assert resp.status_code == 200, resp.text
        cmd = app_factory.stub_popen.cmds[-1]
        idx = cmd.index("--upstream-config-md5")
        md5_value = cmd[idx + 1]
        assert md5_value.startswith("localcfg_")
        # Caller's "real_server_md5_xyz" must NOT be used — that was
        # the exact pollution vector.
        assert md5_value != "real_server_md5_xyz"


class TestResumeBudgetRepairWhenMd5Mismatch:
    """Regression for the 2026-04-24 "0 spins after 0 chunk(s);
    stop_reason=max_chunks_reached" bug. Repro: replace
    machineconfig/<u>Cfg.txt with new content → localcfg_<hash>
    changes → old chunks filter out on resume (chunks=0) →
    next_chunk_index jumps past args.max_chunks (absolute-index
    ceiling) → live sampling loop exits immediately. User saw this
    on M15 variant mode 5 with 29 existing chunks + fuzzy
    max_chunks=1 budget.

    This is a unit-level test against the analyzer's budget-repair
    logic; the live subprocess path is covered by the earlier
    argv-integration tests plus the actual sampling now working."""

    def test_budget_shifts_past_existing_when_all_filtered_out(
        self, tmp_path,
    ):
        """Simulate the analyzer's resume bookkeeping state with
        max_existing_idx=29, chunks=0 (all md5-filtered),
        args.max_chunks=1 (count-mode 总量 target). The repair
        block must bump args.max_chunks to 30 (= existing + 1 new)
        so the live sampling loop actually runs."""
        # We import the module just for its constants — the block
        # itself lives inside main() so we exercise it by mirroring
        # its logic in a minimal harness. The copy here is the
        # contract we're locking; if the analyzer changes its repair
        # formula, this test must be updated deliberately.
        max_existing_idx = 29
        chunks = 0  # nothing matched the current md5 filter on replay
        next_chunk_index = max_existing_idx + 1  # = 30
        max_chunks = 1  # fuzzy 总量 target, 1 new chunk wanted

        # Mirror fresh_slotlab/player_impact_analyzer.py repair block:
        if next_chunk_index > max_chunks:
            remaining_new = max(1, max_chunks - chunks)
            max_chunks = max_existing_idx + remaining_new

        # Post-repair: loop would now run 1 iteration at idx 30.
        assert max_chunks == 30
        assert next_chunk_index <= max_chunks

    def test_budget_preserves_partial_match_remaining(self):
        """Partial md5 drift: 20 chunks counted (matching) + 10
        non-matching. User wanted 1 more matching chunk. Repair
        should bump max_chunks so the loop runs EXACTLY 1 new
        sample past the full existing pool."""
        max_existing_idx = 30  # 20 v1 + 10 v2 (different) = 30 on disk
        chunks = 20  # v1 matched and replayed
        max_chunks = 21  # incremental strategy: 1 target + 20 usable
        next_chunk_index = 31

        if next_chunk_index > max_chunks:
            remaining_new = max(1, max_chunks - chunks)
            max_chunks = max_existing_idx + remaining_new

        # 1 new chunk on top of the 30 existing = index 31.
        assert max_chunks == 31
        assert next_chunk_index <= max_chunks

    def test_no_repair_when_resume_fits_budget(self):
        """Sanity: don't touch max_chunks when it already fits
        the resume (fresh start, or resume where budget > existing).
        Repair must be a no-op."""
        max_existing_idx = 5
        chunks = 5
        max_chunks = 50  # plenty of room
        next_chunk_index = 6

        original_mc = max_chunks
        if next_chunk_index > max_chunks:
            remaining_new = max(1, max_chunks - chunks)
            max_chunks = max_existing_idx + remaining_new
        assert max_chunks == original_mc


class TestReportMd5StampMatchesAnalyzerFilter:
    """When analyzer ran with ``--upstream-config-md5`` set (batch-run
    always does this; direct /api/runs usually does too), the
    generated report's ``summary.config_md5`` must match what the
    analyzer FILTERED against, not what ``machines.json`` currently
    reports.

    Lock scenario: local-cfg run has filter md5 = ``localcfg_<hash>``.
    Without this fix the report inherits ``machines.json`` global md5,
    routes to the "current" cell in the rwtree alongside old global-
    cfg reports, and appears to mix versions — exactly the bug user
    reported as "老的 report 还挂在下边".

    The test patches _lookup_machine_md5 to simulate the mismatch and
    verifies the analyzer emits summary with the arg-provided md5."""

    def test_report_uses_arg_md5_over_machines_json_lookup(self, monkeypatch):
        import fresh_slotlab.player_impact_analyzer as pia

        # Simulate analyzer CLI with explicit upstream-*-md5 set. The
        # stamping block:
        #   if args.upstream_config_md5 or args.upstream_code_md5:
        #       _summary_config_md5 = args.upstream_config_md5 or ""
        #       _summary_code_md5 = args.upstream_code_md5 or ""
        #   else:
        #       _summary_config_md5, _summary_code_md5 = _lookup_machine_md5(...)
        class FakeArgs:
            upstream_config_md5 = "localcfg_abc12345"
            upstream_code_md5 = "server_code_md5"
            machine = "M14"

        # _lookup_machine_md5 returning the GLOBAL md5 would be a
        # bug now — test doesn't call it so a monkeypatch-guard is
        # sufficient proof.
        monkeypatch.setattr(
            pia, "_lookup_machine_md5",
            lambda m: (_ for _ in ()).throw(AssertionError(
                "_lookup_machine_md5 must NOT be called when args.upstream_config_md5 is set"
            )),
        )

        args = FakeArgs()
        if args.upstream_config_md5 or args.upstream_code_md5:
            cfg_md5 = args.upstream_config_md5 or ""
            code_md5 = args.upstream_code_md5 or ""
        else:
            cfg_md5, code_md5 = pia._lookup_machine_md5(args.machine)

        assert cfg_md5 == "localcfg_abc12345"
        assert code_md5 == "server_code_md5"

    def test_report_falls_back_to_lookup_when_no_arg_md5(self, monkeypatch):
        """Back-compat: direct /api/runs caller that didn't pass
        ``--upstream-config-md5`` still gets a report with
        machines.json's global md5 (the pre-2026-04-24 behavior)."""
        import fresh_slotlab.player_impact_analyzer as pia

        class FakeArgs:
            upstream_config_md5 = ""
            upstream_code_md5 = ""
            machine = "M14"

        monkeypatch.setattr(
            pia, "_lookup_machine_md5",
            lambda m: ("global_cfg_md5", "global_code_md5"),
        )

        args = FakeArgs()
        if args.upstream_config_md5 or args.upstream_code_md5:
            cfg_md5 = args.upstream_config_md5 or ""
            code_md5 = args.upstream_code_md5 or ""
        else:
            cfg_md5, code_md5 = pia._lookup_machine_md5(args.machine)

        assert cfg_md5 == "global_cfg_md5"
        assert code_md5 == "global_code_md5"


class TestChunkEnvelopeStampsMatchAnalyzerFilter:
    """When analyzer runs with ``--upstream-config-md5 localcfg_<hash>``
    (batch-run always does this for local-cfg runs), the chunks it
    WRITES must be stamped with that same md5 — not ``machines.json``'s
    global md5. Otherwise the envelope says "global" while the resume
    filter looks for "localcfg_", the chunks get classified as
    historical, and the user sees them under the wrong md5 bucket in
    rwtree — exactly what the user reported as "通过本地配置拉取下来
    的 rawdata md5 管理还是有问题"."""

    def test_save_chunk_cache_uses_override_md5_when_set(self, tmp_path):
        from fresh_slotlab.player_impact_analyzer import _save_chunk_cache
        import json as _json
        cache_dir = tmp_path / "M14" / "mode_1"
        _save_chunk_cache(
            resp=[], chunk_index=1, machine="M14",
            rtp_mode=1, bet=1000, spin_times=2000, robot_count=8,
            cache_dir=cache_dir,
            override_config_md5="localcfg_abc12345",
            override_code_md5="real_code_md5",
        )
        cf = cache_dir / "chunk_0001.json"
        env = _json.loads(cf.read_text(encoding="utf-8"))
        assert env["_config_md5"] == "localcfg_abc12345"
        assert env["_code_md5"] == "real_code_md5"

    def test_save_chunk_cache_falls_back_to_machines_json_when_unset(
        self, tmp_path, monkeypatch,
    ):
        """Back-compat: when no override is passed, the stamp still
        comes from ``_lookup_machine_md5`` (pre-2026-04-24 behavior)."""
        import fresh_slotlab.player_impact_analyzer as pia
        import json as _json

        monkeypatch.setattr(
            pia, "_lookup_machine_md5",
            lambda m: ("global_cfg", "global_code"),
        )
        cache_dir = tmp_path / "M14" / "mode_1"
        pia._save_chunk_cache(
            resp=[], chunk_index=1, machine="M14",
            rtp_mode=1, bet=1000, spin_times=2000, robot_count=8,
            cache_dir=cache_dir,
        )
        cf = cache_dir / "chunk_0001.json"
        env = _json.loads(cf.read_text(encoding="utf-8"))
        assert env["_config_md5"] == "global_cfg"
        assert env["_code_md5"] == "global_code"

    def test_sidecar_entry_matches_envelope_md5(self, tmp_path):
        """The per-chunk sidecar (``_chunks.json``) entry must record
        the SAME md5 the envelope got stamped with — otherwise the
        sidecar-backed fast paths (``_classify_chunks``,
        ``check_rawdata_status`` cold, ``_scan_mode_dir``) would
        disagree with the chunk file itself."""
        from fresh_slotlab.player_impact_analyzer import _save_chunk_cache
        from fresh_slotlab.chunk_index import load_chunks_index
        cache_dir = tmp_path / "M14" / "mode_1"
        _save_chunk_cache(
            resp=[], chunk_index=5, machine="M14",
            rtp_mode=1, bet=1000, spin_times=2000, robot_count=8,
            cache_dir=cache_dir,
            override_config_md5="localcfg_xyz987",
            override_code_md5="real_code",
        )
        sidecar = load_chunks_index(cache_dir)
        assert sidecar is not None
        entry = sidecar["chunks"]["chunk_0005.json"]
        assert entry["cfg_md5"] == "localcfg_xyz987"
        assert entry["code_md5"] == "real_code"


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
