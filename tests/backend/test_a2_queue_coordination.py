"""R1 — A2 + queue coordination (2026-05-26).

When the console restarts mid-batch, two recovery paths can both try
to resume the same (machine, mode) cell:

  - A2 (RunManager._recover_orphan_running_runs) sees the SAMPLING
    run row as orphan -> spawns a new resume run.
  - L2 / L3 / fleet refresh restore (BatchRunManager / BatchGenerate
    Manager / FleetRefreshManager __init__) restores the parent
    queue -> operator clicks ↻ resume / queue auto-resumes -> new
    runs spawn for the same cells.

R1 fixes the race by having A2 skip spawn when the cell is owned by
a non-terminal queue. The orphan is still marked failed (preserving
the failure trail for the queue's own recovery to consume), but no
duplicate run is created.

Tests:
  - cell owned by non-terminal sampling batch -> A2 skips spawn
  - cell owned by non-terminal generate batch -> A2 skips spawn
  - cell owned by non-terminal fleet refresh queue -> A2 skips spawn
  - cell NOT owned by any queue -> A2 spawns as usual (regression
    guard against over-eager skip)

Inject-bug recipes inline.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _make_runmanager_for_r1(
    tmp_path: Path,
    stub_popen,
    *,
    orphan_machine: str = "M14",
    orphan_mode: int = 1,
    pre_seed_batches: list[dict] | None = None,
    pre_seed_fleet: list[dict] | None = None,
):
    """Build a RunManager with an orphan run row plus optional
    seeded batches / fleet_refresh_items to simulate the
    queue-ownership scenarios.
    """
    from src.web_console.backend.app import (
        RunManager, StateStore,
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

    fake_analyzer = tmp_path / "fake_analyzer.py"
    fake_analyzer.write_text("# stub\n", encoding="utf-8")
    fake_machines = tmp_path / "machines.json"
    fake_machines.write_text(json.dumps({"machines": [
        {"machine": "M14", "mode_list": [1, 2], "upstream_key": "M14"},
        {"machine": "M120", "mode_list": [1, 2], "upstream_key": "M120"},
    ]}), encoding="utf-8")

    store = StateStore(db_path)

    # Seed batches via store first (closes its conn after each call).
    if pre_seed_batches:
        for b in pre_seed_batches:
            store.upsert_batch(
                b["batch_id"],
                status=b.get("status", "running"),
                created_at=b.get("created_at", "2026-05-26T07:00:00Z"),
                finished_at=None,
                concurrency=3,
                params=b.get("params", {}),
                items=b.get("items", []),
                events=[],
                reports_root=None,
                kind=b.get("kind", "sampling"),
            )

    # Now use raw conn for runs + fleet inserts (no store methods for
    # these tables).
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        orphan = {
            "run_id": "orph_r1",
            "machine": orphan_machine,
            "mode": orphan_mode,
            "status": "running",
            "model_id": "gpt-5.4-mini",
            "created_at": "2026-05-26T08:00:00Z",
            "started_at": "2026-05-26T08:00:00Z",
            "finished_at": None,
            "target_halfwidth_pp": 0.5,
            "chunk_spin_times": 10000,
            "chunk_robot_count": 8,
            "batch_concurrency": 8,
            "max_chunks": 60,
            "timeout": 60.0,
            "bankruptcy_session_spins": 10000,
            "bankruptcy_bankroll_multipliers": "10,100,200,500",
            "report_version": "rv_old",
            "output_dir": f"reports/{orphan_machine}/mode_{orphan_mode}/versions/rv_old",
            "progress_file": "state/progress/orph_r1.jsonl",
            "summary_file": None,
            "report_file": None,
            "error_message": None,
            "process_pid": None,
            "rawdata_config_md5": "",
            "rawdata_code_md5": "",
        }
        fields = sorted(orphan.keys())
        conn.execute(
            f"INSERT INTO runs ({','.join(fields)}) VALUES ({','.join(':'+f for f in fields)})",
            orphan,
        )
        if pre_seed_fleet:
            for q in pre_seed_fleet:
                conn.execute(
                    "INSERT INTO fleet_refresh_queue "
                    "(queue_id, started_at, status, total_items) VALUES (?, ?, ?, ?)",
                    (q["queue_id"], "2026-05-26T07:00:00Z", q.get("status", "running"),
                     len(q.get("items", []))),
                )
                for pos, it in enumerate(q.get("items", [])):
                    conn.execute(
                        "INSERT INTO fleet_refresh_items "
                        "(queue_id, machine, mode, queue_position) VALUES (?, ?, ?, ?)",
                        (q["queue_id"], it["machine"], it["mode"], pos),
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
        auto_resume_orphan_runs=True,
    )
    return mgr, store


def _orphan_failed_msg(store, run_id: str = "orph_r1") -> str:
    row = store.get_run(run_id)
    return (row or {}).get("error_message", "") or ""


class TestSkipWhenSamplingBatchOwnsCell:
    def test_skip_spawn_when_sampling_batch_pending(self, tmp_path, stub_popen):
        """Sampling batch in 'running' state has the cell in its items
        -> A2 skips spawn -> orphan marked failed with "owned by batch
        ... (kind=sampling)" message.

        Inject-bug: in _recover_orphan_running_runs, remove the
            if queue_owner is not None:
                message_parts.append("skip auto-resume: owned by ...")
            else:
                ... spawn ...
        guard and unconditionally call _spawn_resume_for_orphan ->
        new run gets spawned even though the sampling batch will
        also try to spawn on resume -> assertion `auto_resumed == {}`
        fails because A2 spawned anyway.
        """
        mgr, store = _make_runmanager_for_r1(
            tmp_path=tmp_path,
            stub_popen=stub_popen,
            pre_seed_batches=[{
                "batch_id": "b_owner",
                "status": "running",
                "kind": "sampling",
                "items": [
                    {"machine": "M14", "mode": 1, "status": "running",
                     "run_id": "orph_r1", "chunk_spin_times": 10000},
                ],
            }],
        )
        snap = mgr.startup_recovery_snapshot()
        # A2 did not spawn for orph_r1.
        assert "orph_r1" not in snap["auto_resumed"]
        # Error message mentions the queue owner.
        msg = _orphan_failed_msg(store)
        assert "owned by" in msg
        assert "b_owner" in msg
        # No subprocess spawn captured.
        assert stub_popen.cmds == []


class TestSkipWhenGenerateBatchOwnsCell:
    def test_skip_spawn_when_generate_batch_running(self, tmp_path, stub_popen):
        """Generate batch (kind='generate') in 'running' state with
        the cell in items -> A2 skips spawn."""
        mgr, store = _make_runmanager_for_r1(
            tmp_path=tmp_path,
            stub_popen=stub_popen,
            pre_seed_batches=[{
                "batch_id": "g_owner",
                "status": "running",
                "kind": "generate",
                "items": [
                    {"machine": "M14", "mode": 1, "status": "running",
                     "run_id": "orph_r1"},
                ],
            }],
        )
        snap = mgr.startup_recovery_snapshot()
        assert "orph_r1" not in snap["auto_resumed"]
        msg = _orphan_failed_msg(store)
        assert "g_owner" in msg
        assert "generate" in msg
        assert stub_popen.cmds == []


class TestSkipWhenFleetRefreshOwnsCell:
    def test_skip_spawn_when_fleet_queue_running(self, tmp_path, stub_popen):
        """Fleet refresh queue in 'running' with this cell in
        fleet_refresh_items -> A2 skips spawn.

        Inject-bug: in _is_cell_owned_by_active_queue, remove the
        fleet_refresh JOIN query -> orphan slips through ownership
        check -> A2 spawns -> race with fleet manager's own resume
        thread. Test fails because new run shows up in
        auto_resumed dict.
        """
        mgr, store = _make_runmanager_for_r1(
            tmp_path=tmp_path,
            stub_popen=stub_popen,
            pre_seed_fleet=[{
                "queue_id": "q_owner",
                "status": "running",
                "items": [{"machine": "M14", "mode": 1}],
            }],
        )
        snap = mgr.startup_recovery_snapshot()
        assert "orph_r1" not in snap["auto_resumed"]
        msg = _orphan_failed_msg(store)
        assert "fleet_refresh" in msg
        assert "q_owner" in msg
        assert stub_popen.cmds == []


class TestSpawnsWhenNotOwned:
    def test_orphan_with_no_queue_owner_resumes_normally(self, tmp_path, stub_popen):
        """Regression guard: an orphan that is NOT in any queue's
        items list should still trigger A2 spawn (the queue-ownership
        check must NOT over-fire).

        Inject-bug: in _is_cell_owned_by_active_queue, return a
        non-None string unconditionally -> every orphan gets skipped
        -> A2 is effectively disabled -> auto_resumed always empty
        -> this test fails.
        """
        mgr, store = _make_runmanager_for_r1(
            tmp_path=tmp_path,
            stub_popen=stub_popen,
            pre_seed_batches=[{
                "batch_id": "b_other",
                "status": "running",
                "kind": "sampling",
                "items": [
                    # different cell, not the orphan's
                    {"machine": "M120", "mode": 2, "status": "running"},
                ],
            }],
        )
        snap = mgr.startup_recovery_snapshot()
        assert "orph_r1" in snap["auto_resumed"]
        msg = _orphan_failed_msg(store)
        assert "auto-resumed as" in msg
        assert "owned by" not in msg
        # Subprocess WAS spawned.
        assert stub_popen.cmds, "A2 should have spawned for non-owned orphan"

    def test_terminal_batches_do_not_count_as_owners(self, tmp_path, stub_popen):
        """A 'completed' batch that happened to have this cell in its
        items list should NOT block A2 — the batch already finished
        its work for this cell.

        Inject-bug: in _is_cell_owned_by_active_queue, change
        list_batches_by_status(("pending", "running")) to include
        "completed" -> completed batches block A2 forever ->
        operator never gets their resume -> this test fails because
        auto_resumed stays empty.
        """
        mgr, store = _make_runmanager_for_r1(
            tmp_path=tmp_path,
            stub_popen=stub_popen,
            pre_seed_batches=[{
                "batch_id": "b_done",
                "status": "completed",
                "kind": "sampling",
                "items": [
                    {"machine": "M14", "mode": 1, "status": "completed",
                     "run_id": "old_run"},
                ],
            }],
        )
        snap = mgr.startup_recovery_snapshot()
        assert "orph_r1" in snap["auto_resumed"]
        assert stub_popen.cmds
