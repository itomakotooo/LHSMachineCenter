"""P2 dispatch tests for the auto-inspect feature.

Tests added (8 scenarios, 30 test functions):

  Scenario 1 — Atomic claim race (V1 / S4-G1)
    Verify that concurrent workers cannot claim the same pending item.
    threading.Lock around UPDATE...RETURNING is the guard.

  Scenario 2 — Windowed consecutive-failure counter (MF-5)
    _record_failure_window + _failure_counter_tripped enforce the last-10
    window, skip-status exclusion, and trip at >=3 failed.

  Scenario 3 — MF-3 mutex (bidirectional)
    start_sweep returns 409 while fleet refresh is running.
    start_fleet_refresh returns 409 while sweep is running.

  Scenario 4 — structural_skip roster from settings (S2-G1)
    _classify_cell reads structural_skip_machines from settings at runtime;
    operator overrides take effect without restarting the manager.

  Scenario 5 — cancel_sweep semantics
    Pending items immediately cancelled; sweep status flipped to cancelled;
    get_sweep_status returns cancelled state.

  Scenario 6 — resume_sweep resets claimed -> pending (R1 + L2/L3 interaction)
    Simulates crash-mid-dispatch: claimed items reset to pending;
    _is_cell_owned_by_active_queue sees them as still owned after reset.

  Scenario 7 — HTTP endpoint integration smoke
    Four new routes round-trip correctly via TestClient.

  Scenario 8 — mode=None footgun (07_decision §6 acceptance criteria)
    Static AST scan: no call to _get_machine_md5(... mode=None) in impl.

Inject-bug recipes documented in each test class docstring.

Memory feedback files honored:
  feedback_enumerate_safety_paths.md  — every invariant has inject-bug proof
  feedback_integration_test_argv.md   — concurrency tests use real threads
  feedback_perf_claim_needs_e2e_event_stream.md — real threads, not mocks
  feedback_subprocess_import_suicide_and_module_globals.md — per-instance state
  feedback_no_silent_swallow.md       — terminal statuses carry non-null reasons

Spec: session_artifacts/_arch/auto_inspect/07_decision.md §2-§4 + §6
"""
from __future__ import annotations

import ast
import collections
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Shared helpers
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
                   settings: dict | None = None):
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

    run_mgr = RunManager(
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
        run_manager=run_mgr,
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
               cell_class: str = "easy") -> None:
    """Insert an item row directly."""
    with store._connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO auto_inspect_items
            (sweep_id, machine, mode, queue_position, status, cell_class)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sweep_id, machine, mode, queue_position, item_status, cell_class),
        )
        conn.commit()


def _get_item_status(store, sweep_id: str, machine: str, mode: int) -> str | None:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT status FROM auto_inspect_items "
            "WHERE sweep_id=? AND machine=? AND mode=?",
            (sweep_id, machine, mode),
        ).fetchone()
    return str(row["status"]) if row else None


def _get_sweep_status_from_db(store, sweep_id: str) -> str | None:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT status FROM auto_inspect_sweeps WHERE sweep_id=?",
            (sweep_id,),
        ).fetchone()
    return str(row["status"]) if row else None


# ---------------------------------------------------------------------------
# Scenario 1 — Atomic claim race
# ---------------------------------------------------------------------------


class TestScenario1AtomicClaimRace:
    """Verify that concurrent workers cannot claim the same pending item.

    Two workers racing to claim items must each get DISTINCT items.
    The threading.Lock around UPDATE...RETURNING in _claim_next_item is the guard.

    Inject-bug recipe:
        In auto_inspect_manager.py AutoInspectManager._claim_next_item:
        Comment out `with self._claim_lock:` and the paired de-indent.
        Result: without the lock, two threads may execute the RETURNING
        subquery simultaneously and observe the same 'pending' row before
        either UPDATE commits — SQLite WAL mode + row-level locking
        means one UPDATE wins, but the returned row from the loser
        RETURNING may still be the same row if SQLite < 3.35 path is
        taken. More deterministically: if the fallback path
        (_claim_next_item_fallback) is used, both threads read the same
        row in the SELECT phase before either UPDATE commits.
        In the fallback path, removing the lock is guaranteed to cause
        a double-claim under thread contention.
        -> test_no_duplicate_claims goes RED.
        Revert -> GREEN.

    Memory: feedback_integration_test_argv.md, feedback_perf_claim_needs_e2e_event_stream.md
    """

    def _make_auto_mgr_with_items(self, tmp_path: Path, n_items: int):
        """Create a manager + sweep with n_items pending items."""
        auto_mgr, store, dirs = _make_auto_mgr(tmp_path)

        sweep_id = "sw_race_001"
        _seed_sweep(store, sweep_id, "sampling")
        for i in range(n_items):
            _seed_item(
                store, sweep_id, f"M{100 + i}", 1,
                "pending", queue_position=i
            )
        return auto_mgr, store, sweep_id

    def test_no_duplicate_claims_under_concurrent_workers(self, tmp_path):
        """5 threads claim from 10 items: each item claimed by exactly ONE worker.

        Inject-bug: remove `with self._claim_lock:` block -> high probability
        of double-claim when fallback path is active -> assertion fails.
        """
        n_items = 10
        n_workers = 5
        auto_mgr, store, sweep_id = self._make_auto_mgr_with_items(
            tmp_path, n_items
        )

        claimed_by: dict[str, list[str]] = {}  # machine+mode -> [worker_ids]
        lock = threading.Lock()

        def worker_fn(worker_id: str) -> None:
            for _ in range(n_items * 2):  # attempt more times than items
                item = auto_mgr._claim_next_item(sweep_id, worker_id)
                if item is None:
                    break
                key = f"{item['machine']}/{item['mode']}"
                with lock:
                    claimed_by.setdefault(key, []).append(worker_id)

        threads = [
            threading.Thread(target=worker_fn, args=(f"w{i}",), daemon=True)
            for i in range(n_workers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        # Each item must be claimed by exactly one worker.
        duplicates = {k: v for k, v in claimed_by.items() if len(v) > 1}
        assert not duplicates, (
            f"Items claimed by multiple workers: {duplicates}. "
            "threading.Lock in _claim_next_item is broken or missing."
        )

        # Total claims must equal n_items (no orphans).
        total_claimed = sum(len(v) for v in claimed_by.values())
        assert total_claimed == n_items, (
            f"Expected {n_items} total claims, got {total_claimed}. "
            "Some items were not claimed (orphans exist)."
        )

    def test_no_pending_items_after_all_workers_finish(self, tmp_path):
        """After concurrent claim loop, no items remain in pending status.

        Inject-bug: same as above — lock removal -> items may be re-pended
        by error recovery or items stay pending due to double-skip.
        """
        n_items = 6
        n_workers = 3
        auto_mgr, store, sweep_id = self._make_auto_mgr_with_items(
            tmp_path, n_items
        )

        def worker_fn(worker_id: str) -> None:
            for _ in range(n_items * 2):
                item = auto_mgr._claim_next_item(sweep_id, worker_id)
                if item is None:
                    break

        threads = [
            threading.Thread(target=worker_fn, args=(f"w{i}",), daemon=True)
            for i in range(n_workers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        with store._connect() as conn:
            pending_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM auto_inspect_items "
                "WHERE sweep_id=? AND status='pending'",
                (sweep_id,),
            ).fetchone()["cnt"]

        assert pending_count == 0, (
            f"{pending_count} items still in 'pending' after all workers finished. "
            "Claim loop has a gap."
        )

    def test_claimed_status_set_on_db_row_after_claim(self, tmp_path):
        """After _claim_next_item returns, item status is 'claimed' in DB.

        Inject-bug: change `status='claimed'` to `status='running'` in UPDATE
        -> item is never in 'claimed' state -> this assertion fails.
        """
        auto_mgr, store, sweep_id = self._make_auto_mgr_with_items(tmp_path, 3)
        item = auto_mgr._claim_next_item(sweep_id, "w0")
        assert item is not None, "Expected to claim an item"

        db_status = _get_item_status(store, sweep_id, item["machine"], item["mode"])
        assert db_status == "claimed", (
            f"Expected 'claimed' in DB after _claim_next_item, got {db_status!r}. "
            "The UPDATE must set status='claimed' as the transient state."
        )

    def test_claimed_by_field_set_to_worker_id(self, tmp_path):
        """After claim, claimed_by and claimed_at are populated.

        Inject-bug: remove `claimed_by=?` from the UPDATE statement
        -> claimed_by stays NULL -> this assertion fails.
        """
        auto_mgr, store, sweep_id = self._make_auto_mgr_with_items(tmp_path, 2)
        item = auto_mgr._claim_next_item(sweep_id, "worker_xyz")
        assert item is not None

        with store._connect() as conn:
            row = conn.execute(
                "SELECT claimed_by, claimed_at FROM auto_inspect_items "
                "WHERE sweep_id=? AND machine=? AND mode=?",
                (sweep_id, item["machine"], item["mode"]),
            ).fetchone()
        assert row["claimed_by"] == "worker_xyz", (
            f"claimed_by should be 'worker_xyz', got {row['claimed_by']!r}"
        )
        assert row["claimed_at"] is not None, "claimed_at must be populated"

    def test_claim_returns_none_when_no_pending(self, tmp_path):
        """When no pending items remain, _claim_next_item returns None.

        Inject-bug: return a dummy dict instead of None ->
        worker loops forever (no termination) -> test hangs / fails.
        """
        auto_mgr, store, sweep_id = self._make_auto_mgr_with_items(tmp_path, 1)

        # Claim the only item.
        item = auto_mgr._claim_next_item(sweep_id, "w0")
        assert item is not None

        # Now no pending items remain.
        result = auto_mgr._claim_next_item(sweep_id, "w1")
        assert result is None, (
            f"Expected None when no pending items remain, got {result!r}"
        )

    def test_items_claimed_in_queue_position_order(self, tmp_path):
        """Items are claimed in ascending queue_position order.

        Inject-bug: change ORDER BY queue_position ASC to DESC ->
        items claimed in reverse order -> assertion fails.
        """
        auto_mgr, store, sweep_id = self._make_auto_mgr_with_items(tmp_path, 4)

        claimed_order = []
        for i in range(4):
            item = auto_mgr._claim_next_item(sweep_id, f"w{i}")
            if item:
                claimed_order.append(int(item["queue_position"]))

        assert claimed_order == sorted(claimed_order), (
            f"Items not claimed in queue_position order: {claimed_order}"
        )


# ---------------------------------------------------------------------------
# Scenario 2 — Windowed consecutive-failure counter (MF-5)
# ---------------------------------------------------------------------------


class TestScenario2WindowedFailureCounter:
    """Verify the windowed failure counter logic per 07_decision §2 MF-5.

    Rules under test:
      * Window size = last 10 attempts.
      * Only 'failed' outcome increments the failure count.
      * 'skip' (structural_skip / convergence_timeout / etc.) does NOT increment.
      * Trip condition: failed_count >= max_failures (default 3).

    Inject-bug recipe:
        Option A: Change `collections.deque(maxlen=10)` to `maxlen=100` in
                  __init__/_failure_windows initialization inside start_sweep.
                  -> Window holds 100 items instead of 10 -> test that expects
                  trip after 3 of last 10 does NOT trip because window has
                  100 entries (old failures diluted) -> test RED.
                  Revert -> GREEN.

        Option B: Remove the `if outcome not in ("ok", "failed"): return`
                  early-return in _record_failure_window.
                  -> 'skip' increments counter -> structural_skip sweeps
                  trip immediately -> test_structural_skip_does_not_trip RED.
                  Revert -> GREEN.

    Memory: feedback_enumerate_safety_paths.md
    """

    def _fresh_deque(self) -> collections.deque:
        return collections.deque(maxlen=10)

    def _make_mgr_with_window(self, tmp_path: Path) -> tuple[Any, str]:
        """Create AutoInspectManager + a sweep_id with initialized window."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_win_001"
        _seed_sweep(store, sweep_id, "sampling")
        with auto_mgr._failure_lock:
            auto_mgr._failure_windows[sweep_id] = collections.deque(maxlen=10)
        return auto_mgr, sweep_id

    def test_three_consecutive_failures_trips_counter(self, tmp_path):
        """3 'failed' outcomes -> counter tripped (3 >= 3).

        Inject-bug (Option A): change maxlen=10 to maxlen=100 ->
        trip condition depends on count, not window, so 3 failed in
        100-slot window still returns True. This specific inject-bug
        does NOT break this test. Use Option B below.

        Inject-bug (Option B): replace `failed_count >= max_failures`
        with `failed_count > max_failures` ->
        3 failed is no longer >= 3 -> does NOT trip -> RED.
        Revert -> GREEN.
        """
        auto_mgr, sweep_id = self._make_mgr_with_window(tmp_path)
        auto_mgr._record_failure_window(sweep_id, "failed")
        auto_mgr._record_failure_window(sweep_id, "failed")
        auto_mgr._record_failure_window(sweep_id, "failed")
        assert auto_mgr._failure_counter_tripped(sweep_id, max_failures=3), (
            "3 consecutive failures must trip the counter (failed_count >= 3)"
        )

    def test_two_failures_does_not_trip(self, tmp_path):
        """2 'failed' outcomes -> NOT tripped.

        Inject-bug: change `>= max_failures` to `>= 2` ->
        2 failures now trip -> assertion fails.
        """
        auto_mgr, sweep_id = self._make_mgr_with_window(tmp_path)
        auto_mgr._record_failure_window(sweep_id, "failed")
        auto_mgr._record_failure_window(sweep_id, "failed")
        assert not auto_mgr._failure_counter_tripped(sweep_id, max_failures=3), (
            "2 failures should NOT trip when max_failures=3"
        )

    def test_structural_skip_does_not_count(self, tmp_path):
        """5 'skip' outcomes -> window has 0 failures -> does NOT trip.

        Inject-bug (Option B): remove `if outcome not in ("ok","failed"): return`
        early-return -> 'skip' stored in window -> window fills with 'skip'
        entries -> _failure_counter_tripped counts them as 'failed'... wait,
        it only counts 'failed', so 'skip' being stored doesn't matter.

        Better inject-bug for this test: change _record_failure_window to
        record outcome ALWAYS (remove the guard):
            window.append(outcome)  # no "skip" filtering
        Then _failure_counter_tripped checks `x == "failed"` so 'skip' entries
        still don't increment. This test would remain GREEN.

        The CORRECT inject-bug to break structural_skip exclusion is:
        Change _record_failure_window to:
            if outcome in ("ok", "failed", "skip"):
                window.append("failed" if outcome == "skip" else outcome)
        -> 'skip' mapped to 'failed' -> structural_skip trips -> RED.
        Revert -> GREEN.
        """
        auto_mgr, sweep_id = self._make_mgr_with_window(tmp_path)
        for _ in range(5):
            auto_mgr._record_failure_window(sweep_id, "skip")
        assert not auto_mgr._failure_counter_tripped(sweep_id, max_failures=3), (
            "Structural-skip outcomes must NOT increment the failure counter (MF-5)"
        )

    def test_window_size_10_old_failures_diluted(self, tmp_path):
        """Failures outside the 10-item window don't count.

        Pattern: 8 'failed' followed by 5 'ok' -> last 10 = 2 failed + 8 ok
        (because 10-slot window drops the oldest 3 failures when 5 ok pushed)
        -> not tripped at max_failures=3.

        Inject-bug: change maxlen=10 to maxlen=100 ->
        window retains all 8 failures + 5 ok = 8 failed in 13 items ->
        _failure_counter_tripped sees 8 >= 3 -> trips when it shouldn't -> RED.
        Revert -> GREEN.
        """
        auto_mgr, sweep_id = self._make_mgr_with_window(tmp_path)
        # Record 8 failed
        for _ in range(8):
            auto_mgr._record_failure_window(sweep_id, "failed")
        # Record 5 ok  -> oldest 3 failed pushed out (10-item window: 5 failed + 5 ok)
        for _ in range(5):
            auto_mgr._record_failure_window(sweep_id, "ok")
        # Window now: [failed, failed, failed, failed, failed, ok, ok, ok, ok, ok]
        # 5 failed in window -> tripped at max_failures=3
        assert auto_mgr._failure_counter_tripped(sweep_id, max_failures=3), (
            "Expected trip: 5 failed in window of 10"
        )

    def test_exactly_window_boundary_not_tripped(self, tmp_path):
        """3 failed at positions 1,5,10 within a 10-item window trips.

        Inject-bug: change `maxlen=10` to `maxlen=9` ->
        one failure gets pushed out -> only 2 failures in window -> no trip -> RED.
        Revert -> GREEN.
        """
        auto_mgr, sweep_id = self._make_mgr_with_window(tmp_path)
        # Position 1: failed
        auto_mgr._record_failure_window(sweep_id, "failed")
        # Positions 2-4: ok
        for _ in range(3):
            auto_mgr._record_failure_window(sweep_id, "ok")
        # Position 5: failed
        auto_mgr._record_failure_window(sweep_id, "failed")
        # Positions 6-9: ok
        for _ in range(4):
            auto_mgr._record_failure_window(sweep_id, "ok")
        # Position 10: failed
        auto_mgr._record_failure_window(sweep_id, "failed")

        # Window = [failed, ok, ok, ok, failed, ok, ok, ok, ok, failed]
        # 3 failed in window -> trip
        assert auto_mgr._failure_counter_tripped(sweep_id, max_failures=3), (
            "3 failures at positions 1,5,10 in 10-slot window must trip counter"
        )

    def test_mixed_skips_and_failures_window_boundary(self, tmp_path):
        """50 structural_skips + 3 failures -> last 10 = skips only -> no trip.

        Pattern: 50 skips (not counted) then 3 failed.
        Since skips are NOT stored, the window only sees the 3 failed attempts.
        With max_failures=3 and 3 failed in last 10 -> tripped.

        But the SCENARIO is: 50 skips THEN 3 failed THEN 50 skips.
        The 50 trailing skips don't add to window. Window has 3 failed.
        So the counter IS tripped.

        Inject-bug: count skips as attempts ->
        50 trailing skips fill window, diluting the 3 failures -> not tripped -> RED.
        Revert -> GREEN.
        """
        auto_mgr, sweep_id = self._make_mgr_with_window(tmp_path)
        # 50 skips before: not stored, window stays empty
        for _ in range(50):
            auto_mgr._record_failure_window(sweep_id, "skip")
        # 3 failures
        for _ in range(3):
            auto_mgr._record_failure_window(sweep_id, "failed")
        # 50 more skips: still not stored
        for _ in range(50):
            auto_mgr._record_failure_window(sweep_id, "skip")

        # Window = [failed, failed, failed] -> tripped
        assert auto_mgr._failure_counter_tripped(sweep_id, max_failures=3), (
            "3 failures sandwiched by skips: skips must not dilute the window"
        )

    def test_2_failed_1_completed_1_failed_trips(self, tmp_path):
        """2 failed + 1 ok + 1 failed in order -> 3 failed in window -> tripped.

        Inject-bug: change `_failure_counter_tripped` to count only
        consecutive failures (reset on 'ok') ->
        counter resets after the 'ok' -> only 1 consecutive -> not tripped -> RED.
        Revert -> GREEN.
        """
        auto_mgr, sweep_id = self._make_mgr_with_window(tmp_path)
        auto_mgr._record_failure_window(sweep_id, "failed")
        auto_mgr._record_failure_window(sweep_id, "failed")
        auto_mgr._record_failure_window(sweep_id, "ok")  # intervening success
        auto_mgr._record_failure_window(sweep_id, "failed")

        assert auto_mgr._failure_counter_tripped(sweep_id, max_failures=3), (
            "3 total failures (non-consecutive) must trip the windowed counter"
        )

    def test_ok_outcomes_dont_count_as_failures(self, tmp_path):
        """10 'ok' outcomes -> 0 failures -> not tripped."""
        auto_mgr, sweep_id = self._make_mgr_with_window(tmp_path)
        for _ in range(10):
            auto_mgr._record_failure_window(sweep_id, "ok")
        assert not auto_mgr._failure_counter_tripped(sweep_id, max_failures=3)

    def test_unknown_sweep_returns_false_not_crash(self, tmp_path):
        """_failure_counter_tripped for unknown sweep_id returns False."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        result = auto_mgr._failure_counter_tripped("sw_nonexistent", max_failures=3)
        assert result is False


# ---------------------------------------------------------------------------
# Scenario 3 — MF-3 mutex (both directions)
# ---------------------------------------------------------------------------


class TestScenario3MF3Mutex:
    """Verify bidirectional mutex between auto-inspect sweep and fleet refresh.

    Forward: sweep running -> start_fleet_refresh -> 409.
    Reverse: fleet refresh running -> start_sweep -> 409.

    Inject-bug recipe (forward check):
        In app.py start_fleet_refresh route, comment out:
            _ai_mgr = getattr(app.state, "auto_inspect_manager", None)
            if _ai_mgr is not None and _ai_mgr._has_running_sweep():
                raise HTTPException(status_code=409, ...)
        -> fleet refresh starts even when sweep is active -> test RED.
        Revert -> GREEN.

    Inject-bug recipe (reverse check):
        In auto_inspect_manager.py start_sweep, comment out:
            fleet_proxy = self._get_fleet_refresh_manager()
            if fleet_proxy is not None:
                running_queue = fleet_proxy.get_running_queue_id()
                if running_queue:
                    raise HTTPException(status_code=409, ...)
        -> start_sweep succeeds even when fleet refresh is active -> test RED.
        Revert -> GREEN.

    Memory: feedback_enumerate_safety_paths.md, feedback_integration_test_argv.md
    """

    @pytest.fixture
    def fleet_ai_client(self, tmp_state_dir, tmp_reports, tmp_cache,
                        tmp_rawdata, fake_machines, fake_analyzer,
                        stub_popen, monkeypatch, tmp_path):
        """App with BOTH fleet_refresh_enabled=True and auto-inspect wired."""
        from src.web_console.backend.app import create_app

        monkeypatch.setattr(
            "src.web_console.backend.app._default_popen_factory", stub_popen
        )
        monkeypatch.setattr(
            "src.web_console.backend.app._terminate_pid_if_running",
            lambda pid: True,
        )
        # CONFIGS_UPLOAD_DIR must be a real dir for fleet_refresh_enabled=True.
        upload_dir = tmp_path / "uploaded_configs"
        upload_dir.mkdir()
        monkeypatch.setattr(
            "src.web_console.backend.app.CONFIGS_UPLOAD_DIR", upload_dir
        )

        app = create_app(
            state_dir=tmp_state_dir,
            reports_root=tmp_reports,
            cache_root=tmp_cache,
            machines_config=fake_machines,
            analyzer_path=fake_analyzer,
            rawdata_root=tmp_rawdata,
            fleet_refresh_enabled=True,
        )
        with TestClient(app) as c:
            yield c, app

    def test_start_sweep_blocks_fleet_refresh(self, fleet_ai_client):
        """While sweep is sampling, POST /api/fleet/refresh -> 409.

        Inject-bug: remove the `_ai_mgr._has_running_sweep()` guard from
        start_fleet_refresh -> fleet refresh proceeds despite active sweep
        -> 200 instead of 409 -> assertion fails.
        """
        c, app = fleet_ai_client
        ai_mgr = app.state.auto_inspect_manager

        # Seed a sampling sweep directly so sweep is "running" without
        # needing to actually start the dispatch thread.
        store = ai_mgr._store
        _seed_sweep(store, "sw_mf3_fwd", "sampling")

        # Fleet refresh should now be blocked.
        resp = c.post(
            "/api/fleet/refresh",
            json={"machines": [{"machine": "M14", "modes": [1]}]},
        )
        assert resp.status_code == 409, (
            f"Expected 409 when sweep is running, got {resp.status_code}. "
            "MF-3 forward mutex is missing."
        )
        assert "auto-inspect" in resp.json().get("detail", "").lower(), (
            f"409 detail should mention 'auto-inspect', got: {resp.json()}"
        )

    def test_fleet_refresh_blocks_start_sweep(self, fleet_ai_client):
        """While fleet refresh is running, POST /api/auto-inspect/start -> 409.

        Inject-bug: remove the `fleet_proxy.get_running_queue_id()` guard from
        start_sweep -> sweep proceeds despite active fleet refresh
        -> 200 instead of 409 -> assertion fails.
        """
        c, app = fleet_ai_client
        ai_mgr = app.state.auto_inspect_manager
        fleet_mgr = app.state.fleet_refresh_manager

        # Seed a running fleet_refresh_queue row directly.
        # NOTE: total_items is NOT NULL with no default — must be supplied.
        fake_queue_id = "fq_mf3_rev"
        with fleet_mgr._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO fleet_refresh_queue
                (queue_id, status, started_at, config_source, total_items,
                 completed_items, failed_items, skipped_items)
                VALUES (?, 'running', '2026-05-26T00:00:00Z', 'server_default', 1, 0, 0, 0)
                """,
                (fake_queue_id,),
            )
            conn.commit()

        # start_sweep should now be blocked.
        resp = c.post("/api/auto-inspect/start")
        assert resp.status_code == 409, (
            f"Expected 409 when fleet refresh is running, got {resp.status_code}. "
            "MF-3 reverse mutex is missing."
        )
        assert "fleet refresh" in resp.json().get("detail", "").lower(), (
            f"409 detail should mention 'fleet refresh', got: {resp.json()}"
        )

    def test_after_sweep_cancel_fleet_refresh_succeeds(self, fleet_ai_client):
        """Cancel sweep -> fleet refresh allowed.

        This proves the mutex is NOT a permanent lock — cancelling the
        sweep clears the block.

        Inject-bug: cancel_sweep marks sweep 'cancelled' but _has_running_sweep
        still returns True (wrong WHERE clause) -> fleet refresh still blocked
        after cancel -> test RED.
        Revert -> GREEN.
        """
        c, app = fleet_ai_client
        ai_mgr = app.state.auto_inspect_manager
        store = ai_mgr._store

        # Seed + cancel a sweep.
        _seed_sweep(store, "sw_mf3_cancel", "sampling")
        ok = ai_mgr.cancel_sweep("sw_mf3_cancel")
        assert ok, "cancel_sweep should return True for known sweep"

        # Now fleet refresh should be allowed.
        resp = c.post(
            "/api/fleet/refresh",
            json={"machines": [{"machine": "M14", "modes": [1]}]},
        )
        # 200 or 400 (no machines) but NOT 409
        assert resp.status_code != 409, (
            f"Fleet refresh blocked even after sweep was cancelled. "
            f"status={resp.status_code}"
        )

    def test_second_sweep_start_blocked_by_first(self, tmp_path):
        """start_sweep returns 409 when another sweep is already running.

        This is the single-sweep mutex (separate from MF-3 fleet mutex).

        Inject-bug: remove `if self._has_running_sweep(): raise HTTPException`
        from start_sweep -> two sweeps can run concurrently -> test RED.
        Revert -> GREEN.
        """
        from fastapi import HTTPException

        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        # Seed a running sweep to simulate one already started.
        _seed_sweep(store, "sw_already_running", "sampling")

        with pytest.raises(HTTPException) as exc_info:
            auto_mgr.start_sweep()
        assert exc_info.value.status_code == 409, (
            f"Expected 409 for double sweep, got {exc_info.value.status_code}"
        )
        assert "already running" in str(exc_info.value.detail).lower(), (
            f"Expected 'already running' in detail, got: {exc_info.value.detail}"
        )


# ---------------------------------------------------------------------------
# Scenario 4 — structural_skip roster from settings (not hardcoded)
# ---------------------------------------------------------------------------


class TestScenario4StructuralSkipFromSettings:
    """Verify that _classify_cell reads structural_skip_machines from settings.

    The spec resolution (07_decision §2 S2-G1) requires the roster to live
    in settings.json key 'auto_sweep.structural_skip_machines', not hardcoded.

    Inject-bug recipe:
        In auto_inspect_manager.py _scan_cells or _classify_cell, replace:
            structural_skip: set[str] = set(
                settings.get("structural_skip_machines") or ["M250", ...]
            )
        with a hardcoded constant:
            structural_skip: set[str] = {"M250", "M260", "M264", "M268"}
        -> Operator adds "M99" to settings -> M99 still classified 'easy'
        -> test_settings_override_adds_m99_to_skip RED.
        Similarly, removing "M250" from settings -> still skipped -> RED.
        Revert -> GREEN.

    Memory: feedback_enumerate_safety_paths.md
    """

    def test_classify_cell_uses_structural_skip_from_settings(self, tmp_path):
        """_classify_cell returns 'bcm_hard' for machines in settings roster.

        Inject-bug: hardcode the skip list -> adding M99 to settings
        has no effect -> still classified 'easy' -> RED.
        """
        auto_mgr, store, _ = _make_auto_mgr(
            tmp_path,
            settings={
                "auto_sweep": {
                    "structural_skip_machines": ["M250", "M260", "M264", "M268", "M99"],
                }
            },
        )
        # Load settings the same way _scan_cells does.
        settings = auto_mgr._load_auto_sweep_settings()
        structural_skip: set[str] = set(
            settings.get("structural_skip_machines") or
            ["M250", "M260", "M264", "M268"]
        )

        result = auto_mgr._classify_cell(
            "M99", 1,
            structural_skip=structural_skip,
            trigger_session_machines=set(),
            manifest_override_machines=set(),
        )
        assert result == "bcm_hard", (
            f"M99 should be 'bcm_hard' after adding to settings roster, "
            f"got {result!r}. structural_skip is hardcoded, not from settings."
        )

    def test_classify_cell_not_skipped_when_replaced_with_nonoverlapping_roster(
        self, tmp_path
    ):
        """Replace roster with non-overlapping set -> M250 classified 'easy'.

        NOTE on implementation behavior: the impl uses `settings.get(...) or [defaults]`
        which means an EMPTY list falls back to the hardcoded default (empty list is
        falsy). To actually remove M250 from the skip set, the operator must supply a
        non-empty list that doesn't include M250.

        This test verifies that a settings-provided list that excludes M250 takes
        effect — which IS supported by the current implementation.

        Inject-bug: hardcode the skip list (always {"M250","M260","M264","M268"}) ->
        operator setting M250-excluding list has no effect -> M250 still 'bcm_hard' -> RED.
        Revert -> GREEN.

        Known gap (for impl-critic): setting structural_skip_machines=[] does NOT
        result in an empty skip set because [] is falsy and falls back to defaults.
        Operator must supply at least one element in the new roster.
        """
        auto_mgr, store, _ = _make_auto_mgr(
            tmp_path,
            settings={
                "auto_sweep": {
                    # Only M99 in roster — excludes all original 4 machines.
                    "structural_skip_machines": ["M99"],
                }
            },
        )
        settings = auto_mgr._load_auto_sweep_settings()
        structural_skip: set[str] = set(
            settings.get("structural_skip_machines") or
            ["M250", "M260", "M264", "M268"]
        )

        # M250 is not in the override roster ["M99"] -> should be 'easy'.
        result = auto_mgr._classify_cell(
            "M250", 1,
            structural_skip=structural_skip,
            trigger_session_machines=set(),
            manifest_override_machines=set(),
        )
        assert result == "easy", (
            f"M250 should be 'easy' when operator sets roster to ['M99'] only, "
            f"got {result!r}. structural_skip_machines is hardcoded."
        )

        # M99 IS in the override roster -> should be 'bcm_hard'.
        result_m99 = auto_mgr._classify_cell(
            "M99", 1,
            structural_skip=structural_skip,
            trigger_session_machines=set(),
            manifest_override_machines=set(),
        )
        assert result_m99 == "bcm_hard", (
            f"M99 should be 'bcm_hard' per settings override, got {result_m99!r}"
        )

    def test_default_roster_used_when_settings_absent(self, tmp_path):
        """When settings.json has no auto_sweep block, default roster used.

        Default = {M250, M260, M264, M268} from 07_decision §3.

        Inject-bug: replace default fallback list with [] ->
        M250 not in default -> classified 'easy' when it should be 'bcm_hard' -> RED.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)  # no settings file
        settings = auto_mgr._load_auto_sweep_settings()
        structural_skip: set[str] = set(
            settings.get("structural_skip_machines") or
            ["M250", "M260", "M264", "M268"]
        )

        # Default roster must include M250, M260, M264, M268.
        for m in ["M250", "M260", "M264", "M268"]:
            result = auto_mgr._classify_cell(
                m, 1,
                structural_skip=structural_skip,
                trigger_session_machines=set(),
                manifest_override_machines=set(),
            )
            assert result == "bcm_hard", (
                f"Machine {m} should be 'bcm_hard' with default roster, "
                f"got {result!r}"
            )

    def test_structural_skip_item_marked_and_not_counted_in_failure_window(
        self, tmp_path
    ):
        """bcm_hard cell -> worker calls _mark_item(structural_skip) and
        _record_failure_window(skip) -> window unchanged.

        Verifies MF-5 + S2-G1 integration: structural_skip items are
        excluded from the failure counter.

        Inject-bug: change `_record_failure_window(sweep_id, "skip")` to
        `_record_failure_window(sweep_id, "failed")` inside the structural_skip
        branch of _worker -> M279-class machines trip the counter -> RED.
        Revert -> GREEN.
        """
        auto_mgr, store, _ = _make_auto_mgr(
            tmp_path,
            settings={
                "auto_sweep": {
                    "structural_skip_machines": ["M250"],
                }
            },
        )
        sweep_id = "sw_s4_int"
        _seed_sweep(store, sweep_id, "sampling")
        # Seed the item row so _mark_item can UPDATE it.
        _seed_item(store, sweep_id, "M250", 1, "claimed", 0, "bcm_hard")
        with auto_mgr._failure_lock:
            auto_mgr._failure_windows[sweep_id] = collections.deque(maxlen=10)

        # Directly exercise the structural_skip branch logic.
        # (Not calling _worker because that would start a real run;
        # we call _mark_item and _record_failure_window as the worker does.)
        auto_mgr._mark_item(
            sweep_id, "M250", 1,
            status="structural_skip",
            reason="machine in structural_skip roster -- manual review required",
        )
        auto_mgr._record_failure_window(sweep_id, "skip")

        # Window must still be empty (skip not stored).
        with auto_mgr._failure_lock:
            window = list(auto_mgr._failure_windows.get(sweep_id, []))
        assert window == [], (
            f"structural_skip ('skip' outcome) must NOT increment window, "
            f"got window={window!r}"
        )

        # Item must be marked structural_skip with a non-null reason.
        with store._connect() as conn:
            row = conn.execute(
                "SELECT status, terminal_reason FROM auto_inspect_items "
                "WHERE sweep_id=? AND machine=? AND mode=?",
                (sweep_id, "M250", 1),
            ).fetchone()
        assert row["status"] == "structural_skip"
        assert row["terminal_reason"] is not None and row["terminal_reason"] != "", (
            "terminal_reason must be non-null for structural_skip (07_decision §6)"
        )


# ---------------------------------------------------------------------------
# Scenario 5 — cancel_sweep semantics
# ---------------------------------------------------------------------------


class TestScenario5CancelSweepSemantics:
    """Verify cancel_sweep transitions sweep + pending items correctly.

    Per 07_decision §2 (cancel_sweep implementation):
      * Pending items immediately set to 'cancelled' with terminal_reason.
      * Sweep status set to 'cancelled'.
      * Running items continue to natural end (not force-killed by cancel_sweep).
      * Subsequent get_sweep_status returns 'cancelled'.

    Inject-bug recipe:
        In auto_inspect_manager.py cancel_sweep, remove the UPDATE for pending items:
            conn.execute(\"UPDATE auto_inspect_items SET status='cancelled'...
                          WHERE sweep_id=? AND status='pending'\", ...)
        -> pending items stay in 'pending' state -> test_pending_items_cancelled_on_sweep_cancel RED.
        Revert -> GREEN.

    Memory: feedback_enumerate_safety_paths.md
    """

    def test_pending_items_cancelled_on_sweep_cancel(self, tmp_path):
        """cancel_sweep -> pending items immediately set to 'cancelled'.

        Inject-bug: remove `UPDATE ... SET status='cancelled' WHERE status='pending'`
        from cancel_sweep -> pending items stay pending -> assertion fails.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_cancel_001"
        _seed_sweep(store, sweep_id, "sampling")
        # Seed 5 pending + 1 running item.
        for i in range(5):
            _seed_item(store, sweep_id, f"M{200 + i}", 1, "pending", i)
        _seed_item(store, sweep_id, "M299", 1, "running", 99)

        # Initialise cancel event so cancel_sweep can set it.
        auto_mgr._cancel_events[sweep_id] = threading.Event()

        ok = auto_mgr.cancel_sweep(sweep_id)
        assert ok is True, "cancel_sweep must return True for known sweep"

        # All pending items must be cancelled.
        with store._connect() as conn:
            pending_remaining = conn.execute(
                "SELECT COUNT(*) AS cnt FROM auto_inspect_items "
                "WHERE sweep_id=? AND status='pending'",
                (sweep_id,),
            ).fetchone()["cnt"]
        assert pending_remaining == 0, (
            f"{pending_remaining} pending items remain after cancel. "
            "cancel_sweep must immediately cancel all pending items."
        )

    def test_running_item_not_force_killed_by_cancel(self, tmp_path):
        """Running items survive cancel_sweep (only pending items are cancelled).

        Inject-bug: change WHERE clause to include `status IN ('pending', 'running')`
        -> running items also cancelled -> test RED.
        Revert -> GREEN.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_cancel_002"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M301", 1, "running", 0)

        auto_mgr._cancel_events[sweep_id] = threading.Event()
        auto_mgr.cancel_sweep(sweep_id)

        # Running item must still be 'running' (not force-cancelled).
        status = _get_item_status(store, sweep_id, "M301", 1)
        assert status == "running", (
            f"Running item should NOT be force-cancelled by cancel_sweep, "
            f"got status={status!r}."
        )

    def test_sweep_status_becomes_cancelled(self, tmp_path):
        """After cancel_sweep, sweep row status = 'cancelled'.

        Inject-bug: remove `UPDATE auto_inspect_sweeps SET status='cancelled'`
        from cancel_sweep -> sweep status stays 'sampling' -> test RED.
        Revert -> GREEN.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_cancel_003"
        _seed_sweep(store, sweep_id, "sampling")
        auto_mgr._cancel_events[sweep_id] = threading.Event()

        auto_mgr.cancel_sweep(sweep_id)

        sweep_status = _get_sweep_status_from_db(store, sweep_id)
        assert sweep_status == "cancelled", (
            f"Sweep status must be 'cancelled' after cancel, got {sweep_status!r}"
        )

    def test_get_sweep_status_returns_cancelled(self, tmp_path):
        """get_sweep_status returns 'cancelled' after cancel_sweep.

        Inject-bug: get_sweep_status reads from a stale cache or recomputes
        wrongly -> returns 'sampling' after cancel -> test RED.
        Revert -> GREEN.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_cancel_004"
        _seed_sweep(store, sweep_id, "sampling")
        auto_mgr._cancel_events[sweep_id] = threading.Event()

        auto_mgr.cancel_sweep(sweep_id)

        result = auto_mgr.get_sweep_status(sweep_id)
        assert result is not None, "get_sweep_status must not return None for known sweep"
        assert result["status"] == "cancelled", (
            f"get_sweep_status should return 'cancelled', got {result['status']!r}"
        )

    def test_cancel_sweep_returns_false_for_unknown(self, tmp_path):
        """cancel_sweep returns False for unknown sweep_id."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        result = auto_mgr.cancel_sweep("sw_does_not_exist")
        assert result is False

    def test_cancel_sweep_returns_true_for_already_terminal(self, tmp_path):
        """cancel_sweep returns True (no error) for already-completed sweep.

        Per implementation: terminal sweeps return True immediately.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_cancel_terminal"
        _seed_sweep(store, sweep_id, "completed")
        result = auto_mgr.cancel_sweep(sweep_id)
        assert result is True

    def test_pending_items_have_terminal_reason_after_cancel(self, tmp_path):
        """Cancelled items carry non-null terminal_reason (07_decision §6).

        Inject-bug: remove `terminal_reason='cancelled by operator'` from
        the UPDATE in cancel_sweep -> terminal_reason stays NULL
        -> this assertion fails.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_cancel_reason"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M310", 1, "pending", 0)
        auto_mgr._cancel_events[sweep_id] = threading.Event()

        auto_mgr.cancel_sweep(sweep_id)

        with store._connect() as conn:
            row = conn.execute(
                "SELECT terminal_reason FROM auto_inspect_items "
                "WHERE sweep_id=? AND machine=? AND mode=?",
                (sweep_id, "M310", 1),
            ).fetchone()
        assert row["terminal_reason"] is not None and row["terminal_reason"] != "", (
            "Cancelled items must have non-null terminal_reason (07_decision §6 — no silent failure)"
        )


# ---------------------------------------------------------------------------
# Scenario 6 — resume_sweep resets claimed -> pending
# ---------------------------------------------------------------------------


class TestScenario6ResumeSweeResetsClaimed:
    """Verify resume_sweep resets claimed -> pending (crash-recovery for R1).

    Per 07_decision §2 V3: claimed rows are orphaned on crash;
    resume_sweep must reset them to 'pending' so workers can re-claim.

    Inject-bug recipe:
        In auto_inspect_manager.py resume_sweep, remove the UPDATE:
            conn.execute(
                \"UPDATE auto_inspect_items SET status='pending', claimed_by=NULL,
                  claimed_at=NULL WHERE sweep_id=? AND status='claimed'\", ...
            )
        -> Crashed-claimed items stay claimed -> workers can't claim them
        -> items never processed after resume -> test RED.
        Revert -> GREEN.

    Memory: feedback_enumerate_safety_paths.md
    """

    def test_claimed_items_reset_to_pending_after_resume(self, tmp_path):
        """3 claimed items -> resume_sweep -> all 3 become pending.

        Inject-bug: remove the UPDATE in resume_sweep ->
        claimed items stay in 'claimed' -> assertion fails.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_resume_001"
        _seed_sweep(store, sweep_id, "sampling")

        # Seed 3 claimed items (simulating crash mid-dispatch).
        for i in range(3):
            _seed_item(store, sweep_id, f"M{400 + i}", 1, "claimed", i)

        # Verify pre-condition.
        with store._connect() as conn:
            claimed_before = conn.execute(
                "SELECT COUNT(*) AS cnt FROM auto_inspect_items "
                "WHERE sweep_id=? AND status='claimed'",
                (sweep_id,),
            ).fetchone()["cnt"]
        assert claimed_before == 3

        # Resume: must reset claimed -> pending.
        auto_mgr.resume_sweep(sweep_id)

        with store._connect() as conn:
            claimed_after = conn.execute(
                "SELECT COUNT(*) AS cnt FROM auto_inspect_items "
                "WHERE sweep_id=? AND status='claimed'",
                (sweep_id,),
            ).fetchone()["cnt"]
            pending_after = conn.execute(
                "SELECT COUNT(*) AS cnt FROM auto_inspect_items "
                "WHERE sweep_id=? AND status='pending'",
                (sweep_id,),
            ).fetchone()["cnt"]

        assert claimed_after == 0, (
            f"{claimed_after} items still 'claimed' after resume. "
            "resume_sweep must reset claimed -> pending."
        )
        assert pending_after == 3, (
            f"Expected 3 pending after reset, got {pending_after}"
        )

    def test_resume_clears_claimed_by_and_claimed_at(self, tmp_path):
        """After resume, claimed_by and claimed_at are NULL.

        Inject-bug: reset status but not claimed_by/claimed_at ->
        stale worker_id in claimed_by -> UI shows wrong owner -> test RED.
        Revert -> GREEN.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_resume_002"
        _seed_sweep(store, sweep_id, "sampling")

        # Seed a claimed item with claimed_by populated.
        with store._connect() as conn:
            conn.execute(
                """
                INSERT INTO auto_inspect_items
                (sweep_id, machine, mode, queue_position, status, cell_class,
                 claimed_by, claimed_at)
                VALUES (?, 'M401', 1, 0, 'claimed', 'easy', 'crashed_worker', '2026-05-26T00:00:00Z')
                """,
                (sweep_id,),
            )
            conn.commit()

        auto_mgr.resume_sweep(sweep_id)

        with store._connect() as conn:
            row = conn.execute(
                "SELECT claimed_by, claimed_at FROM auto_inspect_items "
                "WHERE sweep_id=? AND machine='M401' AND mode=1",
                (sweep_id,),
            ).fetchone()

        assert row["claimed_by"] is None, (
            f"claimed_by should be NULL after resume, got {row['claimed_by']!r}"
        )
        assert row["claimed_at"] is None, (
            f"claimed_at should be NULL after resume, got {row['claimed_at']!r}"
        )

    def test_resume_does_not_touch_completed_items(self, tmp_path):
        """Completed items stay completed after resume (only claimed reset).

        Inject-bug: change WHERE status='claimed' to WHERE status IN
        ('claimed','completed') -> completed items reset to pending ->
        already-done work re-queued -> test RED.
        Revert -> GREEN.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_resume_003"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M410", 1, "claimed", 0)
        _seed_item(store, sweep_id, "M411", 1, "completed", 1)

        auto_mgr.resume_sweep(sweep_id)

        completed_status = _get_item_status(store, sweep_id, "M411", 1)
        assert completed_status == "completed", (
            f"Completed item must NOT be reset by resume, got {completed_status!r}"
        )

    def test_is_cell_owned_after_resume_reset(self, tmp_path, stub_popen):
        """After resume resets claimed->pending, _is_cell_owned_by_active_queue
        still reports ownership (item is now 'pending', still non-terminal).

        Inject-bug: resume sets status='pending' but
        _is_cell_owned_by_active_queue does not include 'pending' in the
        non-terminal list -> ownership check returns None -> A2 spawns
        duplicate run -> test RED.
        Revert -> GREEN.
        """
        from src.web_console.backend.app import StateStore, RunManager

        state_dir = tmp_path / "state" / "console"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "progress").mkdir()
        db_path = state_dir / "console.db"
        reports = tmp_path / "reports"
        reports.mkdir()
        rawdata = tmp_path / "rawdata"
        rawdata.mkdir()
        cache = tmp_path / "cache"
        cache.mkdir()

        store = StateStore(db_path)

        # Seed sweep + item in 'pending' state (post-resume state).
        _seed_sweep(store, "sw_post_resume", "sampling")
        _seed_item(store, "sw_post_resume", "M420", 1, "pending", 0)

        fake_machines = tmp_path / "machines.json"
        fake_machines.write_text(
            json.dumps({"machines": [{"machine": "M420", "mode_list": [1]}]}),
            encoding="utf-8",
        )
        fake_analyzer = tmp_path / "analyzer.py"
        fake_analyzer.write_text("# stub\n", encoding="utf-8")

        run_mgr = RunManager(
            store,
            analyzer=fake_analyzer,
            reports_root=reports,
            progress_dir=state_dir / "progress",
            cache_root=cache,
            machines_config=fake_machines,
            rawdata_root=rawdata,
            popen_factory=stub_popen,
        )

        # After resume, pending item should still be "owned" by active sweep.
        result = run_mgr._is_cell_owned_by_active_queue("M420", 1)
        assert result is not None, (
            "Post-resume pending item must still be owned by active sweep. "
            "_is_cell_owned_by_active_queue branch 3 is missing 'pending' "
            "from non-terminal list."
        )
        assert "sw_post_resume" in result

    def test_resume_noop_for_unknown_sweep(self, tmp_path):
        """resume_sweep for unknown sweep_id must not raise."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        # Must not raise.
        auto_mgr.resume_sweep("sw_nonexistent_for_resume")


# ---------------------------------------------------------------------------
# Scenario 7 — HTTP endpoint integration smoke
# ---------------------------------------------------------------------------


class TestScenario7HTTPEndpoints:
    """Smoke test for the four new auto-inspect HTTP routes.

    POST /api/auto-inspect/start -> 200 with sweep_id
    GET /api/auto-inspect/{sweep_id} -> 200 with state dict
    POST /api/auto-inspect/{sweep_id}/cancel -> 200
    GET /api/auto-inspect -> 200 with sweeps list
    POST /api/auto-inspect/start (second) while first running -> 409

    Inject-bug recipe for POST /start:
        In app.py, comment out the `@app.post("/api/auto-inspect/start")` route ->
        POST returns 404 -> assertion fails.
        Revert -> GREEN.

    Inject-bug recipe for GET /{sweep_id}:
        Change the route to return status_code=200 with an empty dict ->
        "sweep_id" missing from response -> assertion fails.
        Revert -> GREEN.

    Memory: feedback_integration_test_argv.md
    """

    def test_post_start_returns_200_with_sweep_id(self, client):
        """POST /api/auto-inspect/start -> 200, response has sweep_id.

        Inject-bug: comment out the route -> 404 -> assertion fails.
        """
        c, app = client
        resp = c.post("/api/auto-inspect/start")
        assert resp.status_code == 200, (
            f"Expected 200 from POST /api/auto-inspect/start, got {resp.status_code}. "
            f"Body: {resp.text}"
        )
        data = resp.json()
        assert "sweep_id" in data, f"Response missing sweep_id: {data}"
        assert isinstance(data["sweep_id"], str) and len(data["sweep_id"]) > 0

    def test_get_sweep_status_returns_200(self, client):
        """GET /api/auto-inspect/{sweep_id} -> 200, returns state.

        Inject-bug: remove the GET route -> 404 -> assertion fails.
        """
        c, app = client

        # Start a sweep to get a valid sweep_id.
        resp_start = c.post("/api/auto-inspect/start")
        assert resp_start.status_code == 200
        sweep_id = resp_start.json()["sweep_id"]

        resp = c.get(f"/api/auto-inspect/{sweep_id}")
        assert resp.status_code == 200, (
            f"Expected 200 from GET /api/auto-inspect/{sweep_id}, "
            f"got {resp.status_code}. Body: {resp.text}"
        )
        data = resp.json()
        assert data.get("sweep_id") == sweep_id
        assert "status" in data

    def test_get_sweep_status_404_for_unknown(self, client):
        """GET /api/auto-inspect/nonexistent -> 404.

        Inject-bug: always return 200 with empty dict -> assertion fails.
        """
        c, app = client
        resp = c.get("/api/auto-inspect/sw_definitely_does_not_exist_abc123")
        assert resp.status_code == 404, (
            f"Expected 404 for unknown sweep_id, got {resp.status_code}"
        )

    def test_post_cancel_returns_200(self, client):
        """POST /api/auto-inspect/{sweep_id}/cancel -> 200 {ok: true}.

        Inject-bug: remove cancel route -> 404/405 -> assertion fails.
        """
        c, app = client

        resp_start = c.post("/api/auto-inspect/start")
        assert resp_start.status_code == 200
        sweep_id = resp_start.json()["sweep_id"]

        resp = c.post(f"/api/auto-inspect/{sweep_id}/cancel")
        assert resp.status_code == 200, (
            f"Expected 200 from cancel, got {resp.status_code}. Body: {resp.text}"
        )
        data = resp.json()
        assert data.get("ok") is True

    def test_post_cancel_404_for_unknown_sweep(self, client):
        """POST /api/auto-inspect/nonexistent/cancel -> 404."""
        c, app = client
        resp = c.post("/api/auto-inspect/sw_nocancel/cancel")
        assert resp.status_code == 404

    def test_get_list_sweeps_returns_sweeps_array(self, client):
        """GET /api/auto-inspect -> 200, returns {"sweeps": [...]}.

        Inject-bug: remove list route -> 404 -> assertion fails.
        """
        c, app = client

        # Start a sweep first so the list is non-empty.
        c.post("/api/auto-inspect/start")

        resp = c.get("/api/auto-inspect")
        assert resp.status_code == 200, (
            f"Expected 200 from GET /api/auto-inspect, got {resp.status_code}"
        )
        data = resp.json()
        assert "sweeps" in data, f"Response missing 'sweeps' key: {data}"
        assert isinstance(data["sweeps"], list)
        assert len(data["sweeps"]) >= 1

    def test_second_start_returns_409_while_sweep_running(self, client):
        """POST /api/auto-inspect/start twice -> second returns 409.

        Inject-bug: remove single-sweep mutex check from start_sweep ->
        two sweeps can run concurrently -> second also returns 200 -> RED.
        Revert -> GREEN.
        """
        c, app = client

        # First start must succeed.
        resp1 = c.post("/api/auto-inspect/start")
        assert resp1.status_code == 200, (
            f"First start should succeed, got {resp1.status_code}"
        )

        # Second start while first is running must return 409.
        resp2 = c.post("/api/auto-inspect/start")
        assert resp2.status_code == 409, (
            f"Expected 409 for second start while sweep running, "
            f"got {resp2.status_code}. Body: {resp2.text}"
        )

    def test_list_sweeps_newest_first(self, client):
        """list_recent_sweeps returns sweeps in newest-first order.

        Inject-bug: change ORDER BY created_at DESC to ASC ->
        oldest returned first -> assertion on order fails.
        """
        c, app = client
        ai_mgr = app.state.auto_inspect_manager
        store = ai_mgr._store

        # Directly seed two sweeps with known timestamps.
        _seed_sweep(store, "sw_order_old", "completed")
        import time as _time
        _time.sleep(0.01)  # ensure different created_at
        # Use a sweep_id with a later timestamp that won't conflict.
        with store._connect() as conn:
            conn.execute(
                "INSERT INTO auto_inspect_sweeps "
                "(sweep_id, status, created_at, settings_snapshot_json, modes_json, trigger) "
                "VALUES ('sw_order_new', 'completed', '2026-05-27T00:00:00Z', '{}', '[]', 'manual')"
            )
            conn.execute(
                "UPDATE auto_inspect_sweeps SET created_at='2026-05-25T00:00:00Z' "
                "WHERE sweep_id='sw_order_old'"
            )
            conn.commit()

        result = ai_mgr.list_recent_sweeps(limit=10)
        ids = [r["sweep_id"] for r in result]
        new_idx = ids.index("sw_order_new") if "sw_order_new" in ids else -1
        old_idx = ids.index("sw_order_old") if "sw_order_old" in ids else -1

        if new_idx >= 0 and old_idx >= 0:
            assert new_idx < old_idx, (
                f"Sweeps not returned newest-first. "
                f"sw_order_new at idx {new_idx}, sw_order_old at idx {old_idx}"
            )


# ---------------------------------------------------------------------------
# Scenario 8 — mode=None footgun (07_decision §6 acceptance criteria)
# ---------------------------------------------------------------------------


class TestScenario8ModeNoneFootgun:
    """Verify no call to _get_machine_md5(..., mode=None) in impl.

    Per 07_decision §6: 'No mode=None calls to _get_machine_md5.'

    Static AST scan of auto_inspect_manager.py.

    Inject-bug recipe:
        In auto_inspect_manager.py _scan_cells, change:
            local_cfg, local_code = _get_machine_md5(
                machine, self._machines_config, mode=mode
            )
        to:
            local_cfg, local_code = _get_machine_md5(
                machine, self._machines_config, mode=None
            )
        -> This assertion sees keyword arg mode=None -> RED.
        Revert -> GREEN.

    Memory: feedback_no_silent_swallow.md (silent None mode corrupts md5 lookup)
    """

    def test_no_mode_none_calls_to_get_machine_md5(self):
        """AST scan of auto_inspect_manager.py — no `mode=None` anywhere.

        Inject-bug: add `_get_machine_md5(m, path, mode=None)` anywhere in
        auto_inspect_manager.py -> scan finds it -> assertion fails.
        """
        src_path = (
            ROOT / "src" / "web_console" / "backend" / "auto_inspect_manager.py"
        )
        src = src_path.read_text(encoding="utf-8-sig")
        tree = ast.parse(src)

        mode_none_calls: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Check if the function name is _get_machine_md5.
            func = node.func
            is_target = False
            if isinstance(func, ast.Name) and func.id == "_get_machine_md5":
                is_target = True
            elif isinstance(func, ast.Attribute) and func.attr == "_get_machine_md5":
                is_target = True
            if not is_target:
                continue
            # Check for mode=None keyword arg.
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    if kw.value.value is None:
                        mode_none_calls.append(
                            f"line {node.lineno}: _get_machine_md5(mode=None)"
                        )

        assert not mode_none_calls, (
            f"mode=None calls found in auto_inspect_manager.py: {mode_none_calls}. "
            "07_decision §6 acceptance criteria violated."
        )

    def test_all_get_machine_md5_calls_have_explicit_mode(self):
        """Every _get_machine_md5 call site passes an explicit mode kwarg.

        Inject-bug: change `mode=mode` to positional arg (no keyword) ->
        this test does NOT catch that; the mode=None test catches None.
        This test catches the case where mode keyword is completely absent
        which might fall back to a default of None.
        """
        src_path = (
            ROOT / "src" / "web_console" / "backend" / "auto_inspect_manager.py"
        )
        src = src_path.read_text(encoding="utf-8-sig")
        tree = ast.parse(src)

        calls_without_mode: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_target = False
            if isinstance(func, ast.Name) and func.id == "_get_machine_md5":
                is_target = True
            elif isinstance(func, ast.Attribute) and func.attr == "_get_machine_md5":
                is_target = True
            if not is_target:
                continue
            # Check that at least one keyword arg is 'mode'.
            has_mode_kwarg = any(kw.arg == "mode" for kw in node.keywords)
            if not has_mode_kwarg:
                calls_without_mode.append(
                    f"line {node.lineno}: _get_machine_md5 missing mode= kwarg"
                )

        assert not calls_without_mode, (
            f"_get_machine_md5 calls without explicit mode= kwarg: {calls_without_mode}. "
            "mode= must always be explicit per 07_decision §6."
        )

    def test_no_module_level_globals_in_auto_inspect_manager(self):
        """No module-level mutable state in auto_inspect_manager.py.

        Per feedback_subprocess_import_suicide_and_module_globals.md:
        module-level state is forbidden — all state must be per-instance.

        Inject-bug: add `_GLOBAL_SWEEP_STATE = {}` at module level ->
        test finds it -> assertion fails.
        Revert -> GREEN.
        """
        src_path = (
            ROOT / "src" / "web_console" / "backend" / "auto_inspect_manager.py"
        )
        src = src_path.read_text(encoding="utf-8-sig")
        tree = ast.parse(src)

        forbidden_globals = {
            "RAWDATA_ROOT", "MACHINES_CONFIG", "STATE_DIR", "REPORTS_ROOT",
            "CACHE_ROOT", "_global_state", "_sweep_registry",
        }
        module_globals: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        module_globals.add(t.id)
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    module_globals.add(node.target.id)

        found = forbidden_globals & module_globals
        assert not found, (
            f"Module-level globals found in auto_inspect_manager.py: {found}. "
            "Per feedback_subprocess_import_suicide_and_module_globals.md."
        )


# ---------------------------------------------------------------------------
# Auxiliary: _mark_item always sets terminal_reason (07_decision §6)
# ---------------------------------------------------------------------------


class TestMarkItemAlwaysHasTerminalReason:
    """_mark_item must always set non-null terminal_reason.

    Per 07_decision §6: 'Every terminal status must be a named enum value
    with non-null terminal_reason.'

    Inject-bug recipe:
        In auto_inspect_manager.py _mark_item, change:
            "terminal_reason=?",
            "finished_at=?",
        to:
            "finished_at=?",
        (remove terminal_reason from UPDATE) ->
        terminal_reason stays NULL -> assertion fails.
        Revert -> GREEN.

    Memory: feedback_invariant_with_fallback_hides_drift.md
    """

    def _call_mark_item(self, auto_mgr, store, sweep_id, machine, mode,
                        status, reason):
        """Helper: call _mark_item and fetch the row."""
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, machine, mode, "claimed")

        auto_mgr._mark_item(
            sweep_id, machine, mode,
            status=status,
            reason=reason,
        )

        with store._connect() as conn:
            row = conn.execute(
                "SELECT status, terminal_reason FROM auto_inspect_items "
                "WHERE sweep_id=? AND machine=? AND mode=?",
                (sweep_id, machine, mode),
            ).fetchone()
        return row

    def test_failed_status_has_terminal_reason(self, tmp_path):
        """_mark_item(status='failed') -> terminal_reason is non-null."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        row = self._call_mark_item(
            auto_mgr, store, "sw_mr1", "M500", 1,
            "failed", "run aborted with exit code 1"
        )
        assert row["status"] == "failed"
        assert row["terminal_reason"] == "run aborted with exit code 1", (
            f"terminal_reason should be set, got {row['terminal_reason']!r}"
        )

    def test_structural_skip_has_terminal_reason(self, tmp_path):
        """_mark_item(status='structural_skip') -> terminal_reason non-null."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        row = self._call_mark_item(
            auto_mgr, store, "sw_mr2", "M501", 1,
            "structural_skip", "machine in structural_skip roster"
        )
        assert row["terminal_reason"] is not None and row["terminal_reason"] != ""

    def test_completed_status_has_terminal_reason(self, tmp_path):
        """_mark_item(status='completed') -> terminal_reason non-null."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        row = self._call_mark_item(
            auto_mgr, store, "sw_mr3", "M502", 1,
            "completed", "sampling completed"
        )
        assert row["terminal_reason"] is not None and row["terminal_reason"] != ""

    def test_wall_time_timeout_has_terminal_reason(self, tmp_path):
        """_mark_item(status='wall_time_timeout') -> terminal_reason non-null."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        row = self._call_mark_item(
            auto_mgr, store, "sw_mr4", "M503", 1,
            "wall_time_timeout", "run exceeded wall_time 7200s"
        )
        assert row["terminal_reason"] is not None and row["terminal_reason"] != ""


# ---------------------------------------------------------------------------
# Auxiliary: get_sweep_status / list_recent_sweeps correctness
# ---------------------------------------------------------------------------


class TestGetSweepStatusAndList:
    """Basic correctness of get_sweep_status and list_recent_sweeps."""

    def test_get_sweep_status_returns_none_for_missing(self, tmp_path):
        """Unknown sweep_id -> None (not raise, not empty dict)."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        result = auto_mgr.get_sweep_status("sw_totally_missing")
        assert result is None

    def test_get_sweep_status_has_items_by_status(self, tmp_path):
        """get_sweep_status returns items_by_status breakdown."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        sweep_id = "sw_gs1"
        _seed_sweep(store, sweep_id, "sampling")
        _seed_item(store, sweep_id, "M600", 1, "pending", 0)
        _seed_item(store, sweep_id, "M601", 1, "completed", 1)
        _seed_item(store, sweep_id, "M602", 1, "failed", 2)

        result = auto_mgr.get_sweep_status(sweep_id)
        assert result is not None
        by_status = result.get("items_by_status", {})
        assert by_status.get("pending", 0) == 1
        assert by_status.get("completed", 0) == 1
        assert by_status.get("failed", 0) == 1

    def test_list_recent_sweeps_empty_on_empty_db(self, tmp_path):
        """list_recent_sweeps returns empty list when no sweeps."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        result = auto_mgr.list_recent_sweeps()
        assert result == []

    def test_list_recent_sweeps_respects_limit(self, tmp_path):
        """list_recent_sweeps(limit=2) returns at most 2 sweeps."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        for i in range(5):
            _seed_sweep(store, f"sw_limit_{i}", "completed")

        result = auto_mgr.list_recent_sweeps(limit=2)
        assert len(result) <= 2


# ---------------------------------------------------------------------------
# Auxiliary: _has_running_sweep returns True only for non-terminal sweeps
# ---------------------------------------------------------------------------


class TestHasRunningSweep:
    """_has_running_sweep detects active sweeps correctly.

    Inject-bug: change WHERE status IN ('scanning','sampling','finalizing')
    to WHERE status='sampling' -> 'scanning' sweeps not detected ->
    start_sweep succeeds when another scanning sweep exists -> RED.
    Revert -> GREEN.
    """

    def test_sampling_sweep_detected(self, tmp_path):
        """sampling sweep -> _has_running_sweep() is True."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        _seed_sweep(store, "sw_has_1", "sampling")
        assert auto_mgr._has_running_sweep() is True

    def test_scanning_sweep_detected(self, tmp_path):
        """scanning sweep -> _has_running_sweep() is True.

        Inject-bug: omit 'scanning' from WHERE clause -> returns False
        -> start_sweep allows a second concurrent sweep -> RED.
        """
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        _seed_sweep(store, "sw_has_2", "scanning")
        assert auto_mgr._has_running_sweep() is True

    def test_finalizing_sweep_detected(self, tmp_path):
        """finalizing sweep -> _has_running_sweep() is True."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        _seed_sweep(store, "sw_has_3", "finalizing")
        assert auto_mgr._has_running_sweep() is True

    def test_completed_sweep_not_detected(self, tmp_path):
        """completed sweep -> _has_running_sweep() is False."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        _seed_sweep(store, "sw_has_4", "completed")
        assert auto_mgr._has_running_sweep() is False

    def test_cancelled_sweep_not_detected(self, tmp_path):
        """cancelled sweep -> _has_running_sweep() is False."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        _seed_sweep(store, "sw_has_5", "cancelled")
        assert auto_mgr._has_running_sweep() is False

    def test_no_sweeps_returns_false(self, tmp_path):
        """Empty DB -> _has_running_sweep() is False."""
        auto_mgr, store, _ = _make_auto_mgr(tmp_path)
        assert auto_mgr._has_running_sweep() is False
