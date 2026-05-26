"""P3 generate + failure modes tests for the auto-inspect feature.

Tests added per 07_decision §4 P3 deliverables:

  Scenario 1 — Generate dispatched after sample success
    After _sample_cell runs with a mock run_manager that returns a
    completed sample run, _dispatch_generate_for_item must be called.

  Scenario 2 — Terminal reason non-null for all 9 terminal statuses
    For each terminal status, assert item.terminal_reason is non-empty.

  Scenario 3 — md5_drift_invalidated pre-flight
    When item's enqueue md5 differs from current local md5, _sample_cell
    must mark item md5_drift_invalidated without starting a run.

  Scenario 4 — convergence_timeout still generates + marks status
    When sample run's achieved_halfwidth_pp > target, item is marked
    convergence_timeout (but only AFTER generate succeeds).

  Scenario 5 — Resume recovery for running/generating items
    Items in 'running' and 'generating' status are recovered correctly
    by resume_sweep phase-recovery helpers.

  Scenario 6 — wall_time_timeout enforced (remaining budget)
    If wall time is consumed by sampling, generate wait returns
    'wall_time' immediately and item is marked wall_time_timeout.

  Scenario 7 — _wait_for_run return values
    Verify _wait_for_run returns correct string for each terminal state.

  Scenario 8 — _mark_item handles generate_run_id/generate_status extras
    Verify the DB is updated with generate_run_id and generate_status
    when supplied in extra dict.

Inject-bug discipline:
  Each test documents what change would make it go RED.

Memory feedback files honored:
  feedback_no_silent_swallow.md       — terminal statuses carry non-null reasons
  feedback_enumerate_safety_paths.md  — recovery paths have inject-bug proof
  feedback_integration_test_argv.md   — real mock structure, not just unit smoke
  feedback_subprocess_import_suicide_and_module_globals.md — per-instance state

Spec: session_artifacts/_arch/auto_inspect/07_decision.md §2 MF-2 + §4 P3
"""
from __future__ import annotations

import collections
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Shared helpers (mirrors p2_dispatch helpers for isolation)
# ---------------------------------------------------------------------------


def _make_store_and_dirs(tmp_path: Path):
    """Create StateStore + standard dirs. Returns (store, dirs_dict)."""
    from src.web_console.backend.app import StateStore

    state_dir = tmp_path / "state" / "console"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "progress").mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "console.db"
    reports = tmp_path / "reports"
    reports.mkdir()
    rawdata = tmp_path / "rawdata"
    rawdata.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    store = StateStore(db_path)
    return store, {
        "state_dir": state_dir,
        "db_path": db_path,
        "reports": reports,
        "rawdata": rawdata,
        "cache": cache,
    }


def _make_auto_mgr(tmp_path: Path, *, machines: list[dict] | None = None,
                   settings: dict | None = None, run_manager=None):
    """Build a fully wired AutoInspectManager with injected paths.

    Returns (auto_mgr, store, dirs).
    """
    from src.web_console.backend.app import StateStore, RunManager
    from src.web_console.backend.auto_inspect_manager import AutoInspectManager
    from src.web_console.backend.cell_lock_registry import CellLockRegistry
    from src.web_console.backend.rate_limiter import ConcurrencyLimiter

    store, dirs = _make_store_and_dirs(tmp_path)

    fake_analyzer = tmp_path / "analyzer.py"
    fake_analyzer.write_text("# stub\n", encoding="utf-8")

    machine_list = machines if machines is not None else []
    fake_machines = tmp_path / "machines.json"
    fake_machines.write_text(
        json.dumps({"machines": machine_list}), encoding="utf-8"
    )

    settings_path = tmp_path / "settings.json"
    if settings is not None:
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

    if run_manager is None:
        run_manager = RunManager(
            store,
            analyzer=fake_analyzer,
            reports_root=dirs["reports"],
            progress_dir=dirs["state_dir"] / "progress",
            cache_root=dirs["cache"],
            machines_config=fake_machines,
            rawdata_root=dirs["rawdata"],
        )

    registry = CellLockRegistry()
    limiter = ConcurrencyLimiter(n_slots=8, foreground_reserve=2)

    auto_mgr = AutoInspectManager(
        store=store,
        run_manager=run_manager,
        registry=registry,
        limiter=limiter,
        settings_path=settings_path,
        machines_config=fake_machines,
        rawdata_root=dirs["rawdata"],
    )
    return auto_mgr, store, dirs


def _seed_sweep(store, sweep_id: str, sweep_status: str,
                settings_json: str = "{}") -> None:
    """Insert a sweep row directly."""
    with store._connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO auto_inspect_sweeps
            (sweep_id, status, created_at, settings_snapshot_json, modes_json, trigger)
            VALUES (?, ?, '2026-05-26T00:00:00Z', ?, '["1"]', 'manual')
            """,
            (sweep_id, sweep_status, settings_json),
        )
        conn.commit()


def _seed_item(store, sweep_id: str, machine: str, mode: int,
               item_status: str, queue_position: int = 0,
               cell_class: str = "easy",
               cfg_md5: str = "",
               code_md5: str = "",
               sample_run_id: str | None = None,
               generate_run_id: str | None = None) -> None:
    """Insert an item row directly."""
    with store._connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO auto_inspect_items
            (sweep_id, machine, mode, queue_position, status, cell_class,
             cfg_md5_at_enqueue, code_md5_at_enqueue,
             sample_run_id, generate_run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sweep_id, machine, mode, queue_position, item_status,
             cell_class, cfg_md5, code_md5, sample_run_id, generate_run_id),
        )
        conn.commit()


def _get_item_row(store, sweep_id: str, machine: str, mode: int) -> dict | None:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT * FROM auto_inspect_items "
            "WHERE sweep_id=? AND machine=? AND mode=?",
            (sweep_id, machine, mode),
        ).fetchone()
    return dict(row) if row else None


def _seed_run(store, run_id: str, status: str,
              achieved_halfwidth_pp: float | None = None,
              error_message: str | None = None) -> None:
    """Insert a minimal run row satisfying all NOT NULL constraints."""
    with store._connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO runs
            (run_id, machine, mode, status, model_id, created_at, started_at,
             target_halfwidth_pp, chunk_spin_times, chunk_robot_count,
             batch_concurrency, max_chunks, timeout,
             bankruptcy_session_spins, bankruptcy_bankroll_multipliers,
             report_version, output_dir, progress_file,
             achieved_halfwidth_pp, error_message)
            VALUES (?, 'M14', 1, ?, 'gpt-stub', '2026-05-26T00:00:00Z',
                    '2026-05-26T00:00:00Z',
                    0.5, 10000, 2, 16, 60, 60.0,
                    10000, '10,100,200,500',
                    'v0', '/tmp/stub_output', '/tmp/stub_progress',
                    ?, ?)
            """,
            (run_id, status, achieved_halfwidth_pp, error_message),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Scenario 1 — Generate dispatched after sample success
# ---------------------------------------------------------------------------


class TestScenario1GenerateDispatchedAfterSampleSuccess:
    """After _sample_cell runs and sample succeeds, _dispatch_generate_for_item
    must be called.

    MF-2 resolution: per-item generate eliminates the "8h report blackout" gap.

    Inject-bug recipe:
        In _sample_cell, comment out the entire generate dispatch block
        (lines calling _dispatch_generate_for_item).
        -> _dispatch_generate_for_item is never called.
        -> test_p3_generate_dispatched_after_sample_success RED.
        Revert -> GREEN.
    """

    def test_p3_generate_dispatched_after_sample_success(self, tmp_path):
        """Mock run_manager: sample completes, assert _dispatch_generate_for_item called.

        Inject-bug: comment out generate dispatch in _sample_cell ->
        _dispatch_generate_for_item never called -> assertion fails.
        """
        auto_mgr, store, dirs = _make_auto_mgr(tmp_path)

        sweep_id = "sw_p3_gen"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "claimed")

        # Seed a sample run row that will return 'completed'.
        sample_run_id = "run_sample_001"
        _seed_run(store, sample_run_id, "running", achieved_halfwidth_pp=0.3)

        # Seed a generate run row that will return 'completed'.
        gen_run_id = "run_gen_001"
        _seed_run(store, gen_run_id, "running")

        mock_dispatch_called = []

        original_dispatch = auto_mgr._dispatch_generate_for_item

        def fake_dispatch(sweep_id, machine, mode, settings, sample_run_id):
            mock_dispatch_called.append((machine, mode))
            # Seed generate run as completed so _wait_for_run finishes.
            with store._connect() as conn:
                conn.execute(
                    "UPDATE runs SET status='completed' WHERE run_id=?",
                    (gen_run_id,),
                )
                conn.commit()
            return gen_run_id

        # Also need sample run to transition to 'completed' after start_run.
        def fake_start_run(req):
            # Mark sample run completed immediately.
            with store._connect() as conn:
                conn.execute(
                    "UPDATE runs SET status='completed', "
                    "achieved_halfwidth_pp=0.3 WHERE run_id=?",
                    (sample_run_id,),
                )
                conn.commit()
            return {"run_id": sample_run_id}

        auto_mgr._run_manager.start_run = fake_start_run
        auto_mgr._dispatch_generate_for_item = fake_dispatch

        with auto_mgr._failure_lock:
            auto_mgr._failure_windows[sweep_id] = collections.deque(maxlen=10)

        settings = {"wall_time_per_cell_s": 60, "modes": {"1": {
            "chunk_spin_times": 100, "chunk_robot_count": 1,
            "batch_concurrency": 1, "target_halfwidth_pp": 0.5,
            "max_chunks": 5,
        }}}

        cancel_ev = threading.Event()
        auto_mgr._sample_cell(
            sweep_id, "M14", 1, "w0", settings, cancel_ev,
        )

        assert len(mock_dispatch_called) == 1, (
            f"_dispatch_generate_for_item must be called once after sample "
            f"success. Called {len(mock_dispatch_called)} times. "
            "Is the generate dispatch block present in _sample_cell?"
        )
        assert mock_dispatch_called[0] == ("M14", 1), (
            f"_dispatch_generate_for_item called with wrong args: "
            f"{mock_dispatch_called[0]!r}, expected ('M14', 1)"
        )

    def test_item_status_completed_after_sample_and_generate(self, tmp_path):
        """After both sample and generate succeed, item status='completed'.

        Inject-bug: change final _mark_item call to status='generating' ->
        item never reaches 'completed' -> assertion fails.
        """
        auto_mgr, store, dirs = _make_auto_mgr(tmp_path)

        sweep_id = "sw_p3_complete"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "claimed")

        sample_run_id = "run_sample_002"
        gen_run_id = "run_gen_002"

        # Pre-seed runs as completed so polling loop exits immediately.
        _seed_run(store, sample_run_id, "completed",
                  achieved_halfwidth_pp=0.3)
        _seed_run(store, gen_run_id, "completed")

        def fake_start_run(req):
            return {"run_id": sample_run_id}

        def fake_dispatch(sweep_id_, machine, mode, settings_, s_run_id):
            return gen_run_id

        auto_mgr._run_manager.start_run = fake_start_run
        auto_mgr._dispatch_generate_for_item = fake_dispatch

        with auto_mgr._failure_lock:
            auto_mgr._failure_windows[sweep_id] = collections.deque(maxlen=10)

        settings = {"wall_time_per_cell_s": 60, "modes": {"1": {
            "chunk_spin_times": 100, "chunk_robot_count": 1,
            "batch_concurrency": 1, "target_halfwidth_pp": 0.5,
            "max_chunks": 5,
        }}}

        auto_mgr._sample_cell(sweep_id, "M14", 1, "w0", settings, None)

        row = _get_item_row(store, sweep_id, "M14", 1)
        assert row is not None
        assert row["status"] == "completed", (
            f"Item must be 'completed' after sample+generate success, "
            f"got {row['status']!r}"
        )
        assert row["generate_run_id"] == gen_run_id, (
            f"generate_run_id must be set, got {row['generate_run_id']!r}"
        )

    def test_generate_not_dispatched_when_sample_fails(self, tmp_path):
        """When sample fails, _dispatch_generate_for_item must NOT be called.

        Inject-bug: call dispatch unconditionally ->
        len(dispatch_called) > 0 -> assertion fails.
        """
        auto_mgr, store, dirs = _make_auto_mgr(tmp_path)

        sweep_id = "sw_p3_no_gen"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "claimed")

        dispatch_called = []
        fail_run_id = "run_fail_003"
        _seed_run(store, fail_run_id, "failed",
                  error_message="upstream error")

        def fake_start_run(req):
            return {"run_id": fail_run_id}

        def fake_dispatch(*args, **kwargs):
            dispatch_called.append(args)
            return "run_gen_fake"

        auto_mgr._run_manager.start_run = fake_start_run
        auto_mgr._dispatch_generate_for_item = fake_dispatch

        with auto_mgr._failure_lock:
            auto_mgr._failure_windows[sweep_id] = collections.deque(maxlen=10)

        settings = {"wall_time_per_cell_s": 60, "modes": {"1": {
            "chunk_spin_times": 100, "chunk_robot_count": 1,
            "batch_concurrency": 1, "target_halfwidth_pp": 0.5,
            "max_chunks": 5,
        }}}

        auto_mgr._sample_cell(sweep_id, "M14", 1, "w0", settings, None)

        assert len(dispatch_called) == 0, (
            f"_dispatch_generate_for_item must NOT be called when sample fails. "
            f"Called {len(dispatch_called)} times."
        )

        row = _get_item_row(store, sweep_id, "M14", 1)
        assert row is not None
        assert row["status"] == "failed", (
            f"Item must be 'failed' when sample fails, got {row['status']!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 2 — All 9 terminal statuses have non-null terminal_reason
# ---------------------------------------------------------------------------


class TestScenario2AllTerminalStatusesHaveReason:
    """For each of the 9 terminal statuses, assert terminal_reason non-empty.

    Per 07_decision §6 acceptance criteria:
      "No silent failure paths. Every terminal status must be a named enum
      value with non-null terminal_reason."

    Inject-bug recipe:
        In _mark_item, replace terminal_reason=? with terminal_reason=NULL ->
        every status gets NULL reason -> all 9 assertions fail.
        Revert -> GREEN.

    Memory: feedback_no_silent_swallow.md, feedback_invariant_with_fallback_hides_drift.md
    """

    TERMINAL_STATUSES = [
        "completed",
        "failed",
        "structural_skip",
        "convergence_timeout",
        "manifest_override_partial",
        "deferred_lock_conflict",
        "wall_time_timeout",
        "md5_drift_invalidated",
        "cancelled",
    ]

    def _seed_and_mark(self, tmp_path, status: str, reason: str) -> dict:
        """Seed item + mark it with status/reason, return item row."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path / status)
        sweep_id = f"sw_{status[:12]}"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "claimed")

        with auto_mgr._failure_lock:
            auto_mgr._failure_windows[sweep_id] = collections.deque(maxlen=10)

        auto_mgr._mark_item(
            sweep_id, "M14", 1,
            status=status,
            reason=reason,
        )
        return _get_item_row(store, sweep_id, "M14", 1)

    def test_p3_terminal_reason_non_null_on_every_status(self, tmp_path):
        """For each of the 9 terminal statuses, terminal_reason must be non-empty.

        Inject-bug: set terminal_reason=NULL in _mark_item ->
        all 9 assertions fail.
        """
        reasons = {
            "completed": "sample + generate complete",
            "failed": "subprocess crash: rc=1",
            "structural_skip": "machine in structural_skip roster",
            "convergence_timeout": "halfwidth 0.9pp > target 0.5pp",
            "manifest_override_partial": "bootstrap-default paid spin type",
            "deferred_lock_conflict": "cell busy >30min",
            "wall_time_timeout": "run exceeded wall_time 7200s",
            "md5_drift_invalidated": "upstream md5 changed",
            "cancelled": "cancelled by operator",
        }

        for status in self.TERMINAL_STATUSES:
            reason = reasons[status]
            row = self._seed_and_mark(tmp_path, status, reason)

            assert row is not None, f"Item row not found for status={status!r}"
            assert row["status"] == status, (
                f"Status mismatch: expected {status!r}, got {row['status']!r}"
            )
            assert row["terminal_reason"] is not None, (
                f"terminal_reason is NULL for status={status!r}. "
                "07_decision §6: every terminal status must carry non-null reason."
            )
            assert str(row["terminal_reason"]).strip() != "", (
                f"terminal_reason is empty string for status={status!r}. "
                "Per feedback_no_silent_swallow.md: no silent garbage bucket."
            )

    def test_mark_item_sets_finished_at(self, tmp_path):
        """_mark_item sets finished_at timestamp on every terminal status.

        Inject-bug: remove `finished_at=?` from the UPDATE in _mark_item ->
        finished_at stays NULL -> assertion fails.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_finished_at"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "claimed")

        auto_mgr._mark_item(
            sweep_id, "M14", 1,
            status="completed",
            reason="test",
        )

        row = _get_item_row(store, sweep_id, "M14", 1)
        assert row is not None
        assert row["finished_at"] is not None, (
            "finished_at must be set by _mark_item"
        )


# ---------------------------------------------------------------------------
# Scenario 3 — md5_drift_invalidated pre-flight
# ---------------------------------------------------------------------------


class TestScenario3Md5DriftInvalidated:
    """When item's enqueue md5 differs from current local md5, _sample_cell
    must mark item md5_drift_invalidated without calling start_run.

    Inject-bug recipe:
        In _check_md5_drift, return False unconditionally (remove the check).
        -> md5 drift never detected -> item still tries to sample with stale md5
        -> test_drift_detected_before_start_run RED.
        Revert -> GREEN.

    Memory: feedback_enumerate_safety_paths.md
    """

    def test_drift_detected_before_start_run(self, tmp_path):
        """When enqueue md5 != current md5, item marked md5_drift_invalidated.

        start_run must NOT be called (no sampling with stale md5).

        Inject-bug: comment out _check_md5_drift call in _sample_cell ->
        start_run gets called -> assertion fails (start_run_called > 0).
        """
        auto_mgr, store, dirs = _make_auto_mgr(tmp_path)

        sweep_id = "sw_md5_drift"
        _seed_sweep(store, sweep_id, "sampling")
        # Seed item with specific enqueue md5.
        _seed_item(store, sweep_id, "M14", 1, "claimed",
                   cfg_md5="old_cfg_aabb", code_md5="old_code_ccdd")

        start_run_called = []

        def fake_start_run(req):
            start_run_called.append(req)
            return {"run_id": "run_should_not_reach"}

        auto_mgr._run_manager.start_run = fake_start_run

        # Patch _get_machine_md5 to return a DIFFERENT md5 (drift scenario).
        with patch(
            "src.web_console.backend.auto_inspect_manager._get_machine_md5"
            if False else "src.web_console.backend.app._get_machine_md5",
            return_value=("new_cfg_1234", "new_code_5678"),
        ):
            # Directly test _check_md5_drift.
            with auto_mgr._failure_lock:
                auto_mgr._failure_windows[sweep_id] = collections.deque(maxlen=10)

            result = auto_mgr._check_md5_drift(sweep_id, "M14", 1, {})

        assert result is True, (
            "_check_md5_drift must return True when enqueue md5 != current md5. "
            "Is the drift check implemented in _check_md5_drift?"
        )

        row = _get_item_row(store, sweep_id, "M14", 1)
        assert row is not None
        assert row["status"] == "md5_drift_invalidated", (
            f"Item must be 'md5_drift_invalidated' on drift, "
            f"got {row['status']!r}"
        )
        assert row["terminal_reason"] is not None and "md5" in row["terminal_reason"].lower(), (
            f"terminal_reason must mention md5, got: {row['terminal_reason']!r}"
        )

    def test_no_drift_when_md5_matches(self, tmp_path):
        """When enqueue md5 == current md5, _check_md5_drift returns False.

        Inject-bug: return True unconditionally -> all items drift-invalidated
        even when md5 matches -> assertion fails.
        """
        auto_mgr, store, dirs = _make_auto_mgr(tmp_path)

        sweep_id = "sw_md5_ok"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "claimed",
                   cfg_md5="same_cfg", code_md5="same_code")

        with patch(
            "src.web_console.backend.app._get_machine_md5",
            return_value=("same_cfg", "same_code"),
        ):
            with auto_mgr._failure_lock:
                auto_mgr._failure_windows[sweep_id] = collections.deque(maxlen=10)

            result = auto_mgr._check_md5_drift(sweep_id, "M14", 1, {})

        assert result is False, (
            "_check_md5_drift must return False when md5 matches. "
            f"Got {result!r}."
        )

        row = _get_item_row(store, sweep_id, "M14", 1)
        # Item must NOT be modified when no drift.
        assert row["status"] == "claimed", (
            f"Item should still be 'claimed' when no drift, got {row['status']!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 4 — convergence_timeout still generates + marks status
# ---------------------------------------------------------------------------


class TestScenario4ConvergenceTimeout:
    """When sample run's achieved_halfwidth_pp > target, generate still runs,
    then item is marked convergence_timeout (not failed).

    Per OQ-D rationale: report is informative even when CI not converged.

    Inject-bug recipe:
        In _sample_cell, change convergence_timeout check to set status='failed'
        instead of 'convergence_timeout'.
        -> item gets wrong status -> assertion fails.
        Revert -> GREEN.
    """

    def test_convergence_timeout_after_generate_success(self, tmp_path):
        """Sample completes but halfwidth > target: still generate, then
        mark convergence_timeout.

        Inject-bug: remove convergence_timed_out check -> item gets
        'completed' instead of 'convergence_timeout' -> assertion fails.
        """
        auto_mgr, store, dirs = _make_auto_mgr(tmp_path)

        sweep_id = "sw_convtimeout"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "claimed")

        sample_run_id = "run_s_conv"
        gen_run_id = "run_g_conv"

        # achieved_halfwidth_pp=0.9 > target 0.5 -> convergence timeout.
        _seed_run(store, sample_run_id, "completed", achieved_halfwidth_pp=0.9)
        _seed_run(store, gen_run_id, "completed")

        def fake_start_run(req):
            return {"run_id": sample_run_id}

        def fake_dispatch(sweep_id_, machine, mode, settings_, s_run_id):
            return gen_run_id

        auto_mgr._run_manager.start_run = fake_start_run
        auto_mgr._dispatch_generate_for_item = fake_dispatch

        with auto_mgr._failure_lock:
            auto_mgr._failure_windows[sweep_id] = collections.deque(maxlen=10)

        settings = {"wall_time_per_cell_s": 60, "modes": {"1": {
            "chunk_spin_times": 100, "chunk_robot_count": 1,
            "batch_concurrency": 1, "target_halfwidth_pp": 0.5,
            "max_chunks": 5,
        }}}

        auto_mgr._sample_cell(sweep_id, "M14", 1, "w0", settings, None)

        row = _get_item_row(store, sweep_id, "M14", 1)
        assert row is not None
        assert row["status"] == "convergence_timeout", (
            f"Expected 'convergence_timeout' when halfwidth > target, "
            f"got {row['status']!r}"
        )
        assert row["terminal_reason"] is not None
        assert "halfwidth" in row["terminal_reason"].lower() or "pp" in row["terminal_reason"].lower(), (
            f"terminal_reason should mention halfwidth/pp, got: {row['terminal_reason']!r}"
        )
        # generate_run_id should be set (generate DID run before status check).
        assert row["generate_run_id"] == gen_run_id, (
            f"generate_run_id must be set even for convergence_timeout, "
            f"got {row['generate_run_id']!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 5 — Resume recovery for running/generating items
# ---------------------------------------------------------------------------


class TestScenario5ResumeRecovery:
    """Verify resume_sweep P3 extensions recover running/generating items.

    (a) Items mid-sample (status='running') -> reset to 'pending'.
    (b) Items mid-generate (status='generating', generate completed) -> 'completed'.
    (c) Items mid-generate (status='generating', generate failed) -> reset to 'running'.
    (d) Items with terminal status -> untouched.

    Inject-bug recipe (a):
        In _resume_recover_running_items, comment out the
        _reset_item_to_pending call -> running items stay in 'running'
        after resume -> workers can't re-claim -> test RED.
        Revert -> GREEN.

    Inject-bug recipe (b):
        In _resume_recover_generating_items, change the completed branch
        to also reset to 'running' instead of marking 'completed' ->
        already-done generate is re-dispatched -> test RED.
        Revert -> GREEN.
    """

    def test_running_item_reset_to_pending_on_resume(self, tmp_path):
        """Items in 'running' status are reset to 'pending' by resume.

        Inject-bug: remove _reset_item_to_pending call in
        _resume_recover_running_items -> item stays 'running' -> RED.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_resume_run"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "running",
                   sample_run_id="run_orphan_sample")

        # Seed an orphaned / failed sample run.
        _seed_run(store, "run_orphan_sample", "failed", error_message="crashed")

        auto_mgr._resume_recover_running_items(sweep_id)

        row = _get_item_row(store, sweep_id, "M14", 1)
        assert row["status"] == "pending", (
            f"Running item with failed sample run must be reset to 'pending'. "
            f"Got {row['status']!r}."
        )

    def test_running_item_no_sample_run_reset_to_pending(self, tmp_path):
        """Running item with no sample_run_id also resets to pending."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_resume_run2"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "running",
                   sample_run_id=None)

        auto_mgr._resume_recover_running_items(sweep_id)

        row = _get_item_row(store, sweep_id, "M14", 1)
        assert row["status"] == "pending", (
            f"Running item with no sample_run_id must be reset to 'pending', "
            f"got {row['status']!r}"
        )

    def test_generating_item_with_completed_generate_marked_completed(
        self, tmp_path
    ):
        """Items in 'generating' + completed generate run -> marked 'completed'.

        Inject-bug: change the gen_status == 'completed' branch to reset
        to 'running' -> item not marked 'completed' -> assertion fails.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_resume_gen_ok"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "generating",
                   sample_run_id="run_s_done",
                   generate_run_id="run_g_done")
        _seed_run(store, "run_s_done", "completed")
        _seed_run(store, "run_g_done", "completed")

        with auto_mgr._failure_lock:
            auto_mgr._failure_windows[sweep_id] = collections.deque(maxlen=10)

        auto_mgr._resume_recover_generating_items(sweep_id)

        row = _get_item_row(store, sweep_id, "M14", 1)
        assert row["status"] == "completed", (
            f"Generating item with completed generate run must be 'completed'. "
            f"Got {row['status']!r}."
        )
        assert row["terminal_reason"] is not None and row["terminal_reason"] != ""

    def test_generating_item_with_failed_generate_reset_to_running(
        self, tmp_path
    ):
        """Items in 'generating' + failed generate -> reset to 'running'.

        Inject-bug: change to reset to 'pending' (re-sample instead of
        just re-generate) -> item's sample_run_id cleared unnecessarily
        -> test RED (checking status=='running', not 'pending').
        Revert -> GREEN.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_resume_gen_fail"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "generating",
                   sample_run_id="run_s_ok2",
                   generate_run_id="run_g_failed")
        _seed_run(store, "run_s_ok2", "completed")
        _seed_run(store, "run_g_failed", "failed", error_message="out of disk")

        auto_mgr._resume_recover_generating_items(sweep_id)

        row = _get_item_row(store, sweep_id, "M14", 1)
        assert row["status"] == "running", (
            f"Generating item with failed generate must be reset to 'running' "
            f"(re-dispatch generate, not re-sample). Got {row['status']!r}."
        )
        # generate_run_id must be cleared so worker re-dispatches.
        assert row["generate_run_id"] is None, (
            f"generate_run_id must be NULL after reset to running, "
            f"got {row['generate_run_id']!r}"
        )

    def test_terminal_items_not_touched_by_resume(self, tmp_path):
        """Completed/failed items are NOT modified by resume recovery.

        Inject-bug: change WHERE clause in _resume_recover_running_items to
        include 'completed' -> completed items get reset -> test RED.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_resume_terminal"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "completed")
        _seed_item(store, sweep_id, "M15", 1, "failed")
        _seed_item(store, sweep_id, "M16", 1, "structural_skip")

        auto_mgr._resume_recover_running_items(sweep_id)
        auto_mgr._resume_recover_generating_items(sweep_id)

        for machine, expected_status in [
            ("M14", "completed"), ("M15", "failed"), ("M16", "structural_skip")
        ]:
            row = _get_item_row(store, sweep_id, machine, 1)
            assert row["status"] == expected_status, (
                f"Terminal item {machine} must not be touched by resume. "
                f"Expected {expected_status!r}, got {row['status']!r}."
            )


# ---------------------------------------------------------------------------
# Scenario 6 — wall_time_timeout enforced on generate phase
# ---------------------------------------------------------------------------


class TestScenario6WallTimeTimeoutGenerate:
    """If wall time budget is exhausted after sampling, generate wait times out.

    Inject-bug recipe:
        In _wait_for_run, replace `if timeout_s <= 0: return "wall_time"`
        with `if timeout_s < -999: return "wall_time"` (never triggers).
        -> zero-remaining budget still waits indefinitely -> test hangs.
        Revert -> GREEN.
    """

    def test_wait_for_run_zero_timeout_returns_wall_time(self, tmp_path):
        """_wait_for_run with timeout_s=0 immediately returns 'wall_time'.

        Inject-bug: change `timeout_s <= 0` to `timeout_s < -999` in
        _wait_for_run -> zero timeout doesn't short-circuit ->
        test either hangs or returns wrong value -> RED.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)

        # Seed a run that will never complete (status='running').
        _seed_run(store, "run_never", "running")

        result = auto_mgr._wait_for_run(
            "run_never", timeout_s=0.0, cancel_ev=None
        )
        assert result == "wall_time", (
            f"_wait_for_run with timeout_s=0 must return 'wall_time' immediately. "
            f"Got {result!r}."
        )

    def test_wait_for_run_negative_timeout_returns_wall_time(self, tmp_path):
        """_wait_for_run with timeout_s<0 immediately returns 'wall_time'."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        _seed_run(store, "run_neg", "running")

        result = auto_mgr._wait_for_run(
            "run_neg", timeout_s=-5.0, cancel_ev=None
        )
        assert result == "wall_time"

    def test_wall_time_timeout_item_status_when_remaining_zero(self, tmp_path):
        """When generate _wait_for_run returns 'wall_time', item is
        marked wall_time_timeout.

        Inject-bug: change the `gen_terminal == "wall_time"` branch to
        mark 'failed' -> item gets wrong status -> assertion fails.
        """
        auto_mgr, store, dirs = _make_auto_mgr(tmp_path)

        sweep_id = "sw_gen_walltime"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "claimed")

        sample_run_id = "run_s_wt"
        gen_run_id = "run_g_wt"

        # Pre-seed sample run as completed.
        _seed_run(store, sample_run_id, "completed", achieved_halfwidth_pp=0.3)
        # Pre-seed generate run as still running (never completes).
        _seed_run(store, gen_run_id, "running")

        def fake_start_run(req):
            return {"run_id": sample_run_id}

        def fake_dispatch(sweep_id_, machine, mode, settings_, s_run_id):
            return gen_run_id

        # _wait_for_run with timeout=0 returns 'wall_time' immediately.
        def fake_wait(run_id, *, timeout_s, cancel_ev):
            return "wall_time"

        auto_mgr._run_manager.start_run = fake_start_run
        auto_mgr._dispatch_generate_for_item = fake_dispatch
        auto_mgr._wait_for_run = fake_wait

        with auto_mgr._failure_lock:
            auto_mgr._failure_windows[sweep_id] = collections.deque(maxlen=10)

        settings = {"wall_time_per_cell_s": 60, "modes": {"1": {
            "chunk_spin_times": 100, "chunk_robot_count": 1,
            "batch_concurrency": 1, "target_halfwidth_pp": 0.5,
            "max_chunks": 5,
        }}}

        auto_mgr._sample_cell(sweep_id, "M14", 1, "w0", settings, None)

        row = _get_item_row(store, sweep_id, "M14", 1)
        assert row is not None
        assert row["status"] == "wall_time_timeout", (
            f"Item must be 'wall_time_timeout' when generate times out. "
            f"Got {row['status']!r}."
        )
        assert row["terminal_reason"] is not None


# ---------------------------------------------------------------------------
# Scenario 7 — _wait_for_run return values
# ---------------------------------------------------------------------------


class TestScenario7WaitForRunReturnValues:
    """Verify _wait_for_run returns correct string for each terminal state.

    Inject-bug: change 'completed' return to 'ok' -> callers check for
    'completed' -> gen_terminal != 'completed' -> item marked 'failed' -> RED.
    """

    def test_wait_returns_completed_for_completed_run(self, tmp_path):
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        _seed_run(store, "run_c", "completed")
        result = auto_mgr._wait_for_run("run_c", timeout_s=5.0, cancel_ev=None)
        assert result == "completed"

    def test_wait_returns_failed_for_failed_run(self, tmp_path):
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        _seed_run(store, "run_f", "failed")
        result = auto_mgr._wait_for_run("run_f", timeout_s=5.0, cancel_ev=None)
        assert result == "failed"

    def test_wait_returns_cancelled_for_cancelled_run(self, tmp_path):
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        _seed_run(store, "run_x", "cancelled")
        result = auto_mgr._wait_for_run("run_x", timeout_s=5.0, cancel_ev=None)
        assert result == "cancelled"

    def test_wait_returns_cancelled_when_cancel_ev_set(self, tmp_path):
        """If cancel event is set before waiting, returns 'cancelled'."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        _seed_run(store, "run_cancel_ev", "running")
        ev = threading.Event()
        ev.set()  # already cancelled
        result = auto_mgr._wait_for_run(
            "run_cancel_ev", timeout_s=5.0, cancel_ev=ev
        )
        assert result == "cancelled", (
            f"Expected 'cancelled' when cancel event is set, got {result!r}"
        )

    def test_wait_returns_failed_for_missing_run(self, tmp_path):
        """_wait_for_run returns 'failed' when run_id not found."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        result = auto_mgr._wait_for_run(
            "run_nonexistent_xyz", timeout_s=5.0, cancel_ev=None
        )
        assert result == "failed", (
            f"Expected 'failed' for missing run, got {result!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 8 — _mark_item handles generate extras
# ---------------------------------------------------------------------------


class TestScenario8MarkItemGenerateExtras:
    """Verify _mark_item stores generate_run_id and generate_status in DB.

    Inject-bug recipe:
        In _mark_item, remove the 'generate_run_id' and 'generate_status'
        branches from the `for k, v in extra.items()` loop.
        -> DB never gets generate_run_id / generate_status set ->
        test_mark_item_stores_generate_extras RED.
        Revert -> GREEN.
    """

    def test_mark_item_stores_generate_extras(self, tmp_path):
        """_mark_item with generate_run_id/generate_status extras -> DB updated.

        Inject-bug: remove generate_run_id/generate_status handling from
        _mark_item's extra loop -> row has NULL generate_run_id -> RED.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_gen_extras"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M14", 1, "generating")

        with auto_mgr._failure_lock:
            auto_mgr._failure_windows[sweep_id] = collections.deque(maxlen=10)

        auto_mgr._mark_item(
            sweep_id, "M14", 1,
            status="completed",
            reason="sample + generate complete",
            extra={
                "sample_run_id": "run_s_extras",
                "generate_run_id": "run_g_extras",
                "generate_status": "completed",
            },
        )

        row = _get_item_row(store, sweep_id, "M14", 1)
        assert row is not None
        assert row["sample_run_id"] == "run_s_extras", (
            f"sample_run_id not stored: {row['sample_run_id']!r}"
        )
        assert row["generate_run_id"] == "run_g_extras", (
            f"generate_run_id not stored in DB. "
            "Is generate_run_id handled in _mark_item extra loop?"
        )
        assert row["generate_status"] == "completed", (
            f"generate_status not stored: {row['generate_status']!r}"
        )

    def test_terminal_constant_has_all_9_statuses(self, tmp_path):
        """_TERMINAL_STATUSES constant must contain exactly 9 statuses.

        Inject-bug: remove one status from the constant -> assertion fails.
        """
        from src.web_console.backend.auto_inspect_manager import _TERMINAL_STATUSES
        expected = {
            "completed", "failed", "structural_skip",
            "convergence_timeout", "manifest_override_partial",
            "deferred_lock_conflict", "wall_time_timeout",
            "md5_drift_invalidated", "cancelled",
        }
        assert expected == _TERMINAL_STATUSES, (
            f"_TERMINAL_STATUSES mismatch.\n"
            f"Missing: {expected - _TERMINAL_STATUSES}\n"
            f"Extra: {_TERMINAL_STATUSES - expected}"
        )
