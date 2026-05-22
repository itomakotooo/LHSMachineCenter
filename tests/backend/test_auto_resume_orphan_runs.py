"""A2 — Auto-resume orphan runs on console startup (2026-05-22).

When the console process dies mid-sample, the runs table has rows with
status='running' that no longer have a live subprocess. Pre-A2 behavior:
mark them failed, operator manually retriggers. A2: when the
``auto_resume_orphan_runs`` setting is True, ``RunManager`` re-submits
each orphan via ``--resume-from-cache`` so the analyzer picks up
where it left off.

Test surface here is the unit-level recovery method
(``RunManager._recover_orphan_running_runs``). The end-to-end "kill
process → restart console → run continues" cycle requires real
subprocess infra and is not in scope for CI; the unit test seeds the
runs table with synthetic orphan rows and verifies the recovery path
produces the right state transitions + spawn calls.

Inject-bug recipes are inline in each test docstring.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def _make_runmanager(
    *,
    tmp_path: Path,
    stub_popen,
    auto_resume: bool,
    pre_insert: list[dict[str, Any]] | None = None,
):
    """Build a RunManager pointed at a fresh tmp state dir + stub popen.

    Pre-insert orphan rows BEFORE RunManager.__init__ so the recovery
    method picks them up. Returns (manager, store, rawdata_root,
    reports_root) so tests can poke disk + DB state.
    """
    from src.web_console.backend.app import (
        RunManager, StateStore, ANALYZER, REPORTS_ROOT, PROGRESS_DIR,
        MACHINES_CONFIG,
    )

    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "console.db"
    rawdata_root = tmp_path / "rawdata"
    rawdata_root.mkdir(parents=True, exist_ok=True)
    reports_root = tmp_path / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    progress_dir = state_dir / "progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    cache_root = tmp_path / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)

    # Fake an analyzer file so RunManager.__init__ doesn't reject — the
    # stub popen takes over before any real execution would happen.
    fake_analyzer = tmp_path / "fake_analyzer.py"
    fake_analyzer.write_text("# stub\n", encoding="utf-8")

    # Fake a machines config so _resolve_upstream_machine_name doesn't
    # error on lookup.
    fake_machines = tmp_path / "machines.json"
    fake_machines.write_text(
        json.dumps({"machines": [
            {"machine": "M14", "mode_list": [1, 2], "upstream_key": "M14"},
            {"machine": "M120", "mode_list": [1, 2], "upstream_key": "M120"},
        ]}),
        encoding="utf-8",
    )

    store = StateStore(db_path)

    # Pre-insert orphans via raw SQL so the rows exist when RunManager
    # __init__ fires. Using create_run() would require the full
    # request flow — bypass for test ergonomics.
    if pre_insert:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        try:
            for r in pre_insert:
                fields = sorted(r.keys())
                placeholders = ",".join(":" + f for f in fields)
                conn.execute(
                    f"INSERT INTO runs ({','.join(fields)}) VALUES ({placeholders})",
                    r,
                )
            conn.commit()
        finally:
            conn.close()

    mgr = RunManager(
        store,
        analyzer=fake_analyzer,
        reports_root=reports_root,
        progress_dir=progress_dir,
        cache_root=cache_root,
        machines_config=fake_machines,
        rawdata_root=rawdata_root,
        popen_factory=stub_popen,
        auto_resume_orphan_runs=auto_resume,
    )
    return mgr, store, rawdata_root, reports_root


def _orphan_row(run_id: str, machine: str = "M14", mode: int = 1) -> dict[str, Any]:
    """Build a minimal runs-table row for an orphan run."""
    return {
        "run_id": run_id,
        "machine": machine,
        "mode": mode,
        "status": "running",
        "model_id": "gpt-5.4-mini",
        "created_at": "2026-05-22T08:00:00Z",
        "started_at": "2026-05-22T08:00:00Z",
        "finished_at": None,
        "target_halfwidth_pp": 0.25,
        "chunk_spin_times": 12000,
        "chunk_robot_count": 4,
        "batch_concurrency": 12,
        "max_chunks": 60,
        "timeout": 90.0,
        "bankruptcy_session_spins": 10000,
        "bankruptcy_bankroll_multipliers": "10,100,200,500",
        "report_version": f"rv_old_{run_id}",
        "output_dir": f"reports/{machine}/mode_{mode}/versions/rv_old_{run_id}",
        "progress_file": f"state/progress/{run_id}.jsonl",
        "summary_file": None,
        "report_file": None,
        "error_message": None,
        "process_pid": None,
        "rawdata_config_md5": "abc123",
        "rawdata_code_md5": "def456",
    }


# ── A2 default behavior (auto_resume=True) ────────────────────────


class TestAutoResumeOn:
    def test_orphan_marked_failed_and_resumed(self, tmp_path, stub_popen):
        """Orphan row → failed (with auto-resumed link) + new running row.

        Inject-bug recipe: in _recover_orphan_running_runs, change
        ``if self._auto_resume_orphan_runs:`` to
        ``if False:`` → resume branch never fires → only the old row
        gets updated (failed), no new row → assertion
        `len(running_after) == 1` fails (becomes 0).
        """
        mgr, store, rawdata_root, _ = _make_runmanager(
            tmp_path=tmp_path,
            stub_popen=stub_popen,
            auto_resume=True,
            pre_insert=[_orphan_row("orph1", "M14", 1)],
        )
        snapshot = mgr.startup_recovery_snapshot()
        # 1. Original recovery happened: orphan marked failed.
        old_row = store.get_run("orph1")
        assert old_row is not None
        assert old_row["status"] == "failed"
        # error_message should reference the new run_id
        assert "auto-resumed as " in (old_row.get("error_message") or "")
        # 2. Snapshot reports the mapping.
        assert "orph1" in snapshot["auto_resumed"]
        new_run_id = snapshot["auto_resumed"]["orph1"]
        # 3. A new run exists, status running.
        new_row = store.get_run(new_run_id)
        assert new_row is not None
        assert new_row["status"] == "running"
        # 4. Recovery list still reports it (book-keeping).
        assert "orph1" in snapshot["run_ids"]

    def test_resumed_run_has_resume_from_cache_arg(self, tmp_path, stub_popen):
        """The spawned subprocess should carry --resume-from-cache
        pointing at the rawdata dir for the orphan's (machine, mode).

        Inject-bug: in _spawn_resume_for_orphan, drop
        ``resume_from_cache_dir=str(rawdata_dir)`` from the
        RunCreateRequest → spawned cmd lacks --resume-from-cache →
        assertion fails (substring not in argv).
        """
        mgr, _, rawdata_root, _ = _make_runmanager(
            tmp_path=tmp_path,
            stub_popen=stub_popen,
            auto_resume=True,
            pre_insert=[_orphan_row("orph2", "M120", 2)],
        )
        # stub_popen captures every spawn cmd; the first should be the
        # resume for orph2.
        assert stub_popen.cmds, "no subprocess spawn captured"
        cmd = stub_popen.cmds[-1]
        assert "--resume-from-cache" in cmd
        idx = cmd.index("--resume-from-cache")
        resume_path = cmd[idx + 1]
        # The path is what we'd write chunks to for this cell.
        expected = rawdata_root / "M120" / "mode_2"
        assert Path(resume_path) == expected

    def test_resumed_run_preserves_params(self, tmp_path, stub_popen):
        """Custom params on the orphan row (timeout=90, target=0.25,
        chunk_spin_times=12000, robot=4, conc=12) must flow into the
        new spawned cmd args.

        Inject-bug: change int() / float() coercion in
        _spawn_resume_for_orphan to a literal default (e.g.
        chunk_spin_times=int(row.get("chunk_spin_times") or 10000)
        → chunk_spin_times=10000) → spawned cmd has wrong value →
        assertion fails.
        """
        mgr, _, _, _ = _make_runmanager(
            tmp_path=tmp_path,
            stub_popen=stub_popen,
            auto_resume=True,
            pre_insert=[_orphan_row("orph3")],
        )
        cmd = stub_popen.cmds[-1]
        # Walk pairs to find each CLI arg's value.
        def _arg(name: str) -> str:
            i = cmd.index(name)
            return cmd[i + 1]
        assert _arg("--chunk-spin-times") == "12000"
        assert _arg("--chunk-robot-count") == "4"
        assert _arg("--batch-concurrency") == "12"
        assert _arg("--target-halfwidth-pp") == "0.25"
        assert _arg("--timeout") == "90.0"
        # max-chunks survives too
        assert _arg("--max-chunks") == "60"


# ── auto_resume=False (pre-A2 behavior) ──────────────────────────


class TestAutoResumeOff:
    def test_orphan_marked_failed_no_new_run(self, tmp_path, stub_popen):
        """When auto-resume is disabled, the orphan is marked failed
        with a "please rerun" hint and NO new run is spawned.

        Inject-bug: invert the boolean — pass auto_resume=False but
        have _recover_orphan_running_runs always try to resume → new
        run appears → assertion `auto_resumed == {}` fails.
        """
        mgr, store, _, _ = _make_runmanager(
            tmp_path=tmp_path,
            stub_popen=stub_popen,
            auto_resume=False,
            pre_insert=[_orphan_row("orph_off", "M14", 1)],
        )
        snapshot = mgr.startup_recovery_snapshot()
        # 1. No auto-resume entries.
        assert snapshot.get("auto_resumed") == {}
        # 2. No subprocess spawned (stub_popen captured nothing).
        assert stub_popen.cmds == []
        # 3. Old row marked failed with a "please rerun" hint.
        old_row = store.get_run("orph_off")
        assert old_row is not None
        assert old_row["status"] == "failed"
        assert "please rerun" in (old_row.get("error_message") or "")
        assert "auto-resumed as " not in (old_row.get("error_message") or "")


# ── Edge cases ──────────────────────────────────────────────────


class TestRecoveryEdgeCases:
    def test_no_orphans_returns_zero_snapshot(self, tmp_path, stub_popen):
        mgr, _, _, _ = _make_runmanager(
            tmp_path=tmp_path,
            stub_popen=stub_popen,
            auto_resume=True,
            pre_insert=None,
        )
        snap = mgr.startup_recovery_snapshot()
        assert snap["recovered_count"] == 0
        assert snap["run_ids"] == []
        assert snap["auto_resumed"] == {}
        assert stub_popen.cmds == []

    def test_multiple_orphans_each_resumed(self, tmp_path, stub_popen):
        """Two orphans on different (machine, mode) cells — both should
        resume in parallel without colliding on the SAMPLING lock."""
        mgr, store, _, _ = _make_runmanager(
            tmp_path=tmp_path,
            stub_popen=stub_popen,
            auto_resume=True,
            pre_insert=[
                _orphan_row("orph_a", "M14", 1),
                _orphan_row("orph_b", "M120", 2),
            ],
        )
        snap = mgr.startup_recovery_snapshot()
        assert len(snap["auto_resumed"]) == 2
        assert set(snap["auto_resumed"].keys()) == {"orph_a", "orph_b"}
        # Two subprocess spawns captured (one per cell).
        assert len(stub_popen.cmds) == 2
