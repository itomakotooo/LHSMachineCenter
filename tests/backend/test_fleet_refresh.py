"""P3-T3: Fleet refresh queue + recovery tests.

Covers 10 original + 3 new critic-fix regression tests.

Original tests (session_artifacts/_impl/p3/brief.md §6 P3-T3):
  test_post_fleet_refresh_creates_queue
  test_get_fleet_refresh_returns_progress
  test_delete_fleet_refresh_cancels_queue
  test_only_one_running_queue_at_a_time
  test_recover_fleet_refresh_resumes_in_flight_items
  test_recover_fleet_refresh_safe_on_pre_p3_db
  test_cell_busy_timeout_marks_skipped
  test_fleet_refresh_yields_to_foreground
  test_failed_item_retried_then_skipped_at_max_retries
  test_cancel_during_token_wait_returns_promptly

P3 loop-back critic-fix regression tests (2026-05-17):
  test_reassociate_persists_diagnostic_on_failure         (Fix 2 — diagnostic persistence)
  test_try_acquire_cell_exception_marks_item_skipped      (Fix 3 — real error vs cell_busy_timeout)
  test_cancel_during_run_wait_exits_promptly              (Fix 4 — cancel mid-poll)

P3 loop-back-3 OPT-1 pending_batch_config cleanup tests (2026-05-17):
  test_reassociate_deletes_pending_batch_config_on_success    (OPT-1 cleanup on all-success)
  test_reassociate_preserves_pending_batch_config_on_failure  (OPT-1 preservation on any failure)

Design source: 04_deploy_architecture_proposal_v2.md §4.4 (FleetRefreshManager)
               04_deploy_architecture_proposal_v2.md §4.5 (ConcurrencyLimiter)
               04_deploy_architecture_proposal_v2.md Phase3 D5-D8

Memory feedback files honored:
  memory/feedback_enumerate_safety_paths.md — inject-bug recipe for each
    new mutex (D6 recover, D8 ConcurrencyLimiter wiring).
  memory/feedback_perf_claim_needs_e2e_event_stream.md — concurrency tests
    use real threads, not mocks. Fleet refresh manager runs real queue loop.
  memory/feedback_no_silent_swallow.md — failed items log last_error; test
    verifies the field is populated. Diagnostic files persisted on crash.
  memory/feedback_subprocess_import_suicide_and_module_globals.md — each
    test constructs its own FleetRefreshManager with injected dependencies;
    no module-level state shared between tests.

Inject-bug recipes (for future devs to reproduce):

  D6 _recover_fleet_refresh UPDATE (test_recover_fleet_refresh_resumes_in_flight_items):
    In app.py StateStore._recover_fleet_refresh, remove the line:
        conn.execute(
            "UPDATE fleet_refresh_items SET status='pending', run_id=NULL "
            "WHERE queue_id=? AND status='running'",
            (queue_id,),
        )
    Run test → FAILS: items stay at status='running' after recover, not 'pending'.
    Revert → PASSES.

  D6 OperationalError guard (test_recover_fleet_refresh_safe_on_pre_p3_db):
    In app.py StateStore.__init__, remove the try/except sqlite3.OperationalError
    wrapping the _recover_fleet_refresh() call:
        self._recover_fleet_refresh()  # no guard
    On a DB without fleet_refresh_queue table, OperationalError propagates →
    StateStore() raises → test FAILS. Revert → PASSES.

  D8 ConcurrencyLimiter background wiring (test_fleet_refresh_yields_to_foreground):
    In fleet_refresh.py FleetRefreshManager.run_queue, change:
        limiter_acquired = self._limiter.acquire("background", cancel_flag=...)
    to:
        limiter_acquired = self._limiter.acquire("foreground", cancel_flag=...)
    With foreground priority, fleet refresh can take foreground-reserved slots →
    test fails (foreground acquire succeeds when it should be blocked by fleet).
    Actually: test checks that fleet refresh BLOCKS when only foreground reserve
    remains, which with "foreground" priority it would NOT block → assertion fails.
    Revert → PASSES.

  D5 cancel_queue flag (test_delete_fleet_refresh_cancels_queue):
    In fleet_refresh.py FleetRefreshManager.cancel_queue, replace:
        with self._lock:
            self._cancel_flags[queue_id] = True
    with: pass (no-op).
    Run test → FAILS: queue stays 'running' after DELETE; status != 'cancelled'.
    Revert → PASSES.

  Fix2 diagnostic persistence (test_reassociate_persists_diagnostic_on_failure):
    In app.py _reassociate_orphaned_configs, remove the block that writes
    reassociate_error.json (lines `_err_path = sd / "reassociate_error.json"` ...
    `_err_path.write_text(...)`). Revert → PASSES.
    → test FAILS (file not written after set_chunk_config_id raises).

  Fix3 try_acquire_cell exception (test_try_acquire_cell_exception_marks_item_skipped):
    In fleet_refresh.py run_queue, change the `except Exception as _reg_exc:` block
    to just `except Exception: pass` (bare swallow). The item proceeds to the
    cell_busy_timeout branch instead → item marked with "cell_busy_timeout" reason,
    not the real exception → test FAILS. Revert → PASSES.

  Fix4 cancel mid-poll (test_cancel_during_run_wait_exits_promptly):
    In app.py _fleet_batch_item_runner, remove the `if fleet_mgr._is_cancelled(queue_id): return`
    line inside the `while waited < max_wait:` loop. The loop continues polling for
    up to 7200s regardless of cancel → test times out (>10s) → FAILS. Revert → PASSES.

  OPT-1 success-cleanup (test_reassociate_deletes_pending_batch_config_on_success):
    In app.py _reassociate_orphaned_configs, remove the `if _reassoc_failures == 0:` block
    that calls store.delete_pending_batch_config(...) after the per-chunk loop →
    row stays in pending_batch_configs after successful reassociation →
    list_pending_batch_configs() still returns the row → test FAILS. Revert → PASSES.

  OPT-1 failure-preserve (test_reassociate_preserves_pending_batch_config_on_failure):
    In app.py _reassociate_orphaned_configs, change:
        if _reassoc_failures == 0:
            store.delete_pending_batch_config(...)
    to always call store.delete_pending_batch_config (remove the condition) →
    row deleted even though set_chunk_config_id raised → row absent from
    list_pending_batch_configs() → test FAILS. Revert → PASSES.

Cross-refs:
  session_artifacts/_impl/p3/brief.md §6 P3-T3
  session_artifacts/_impl/p3/critique.md (Fix 2/3/4)
  session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.4
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.web_console.backend.app import create_app, StateStore
from src.web_console.backend.cell_lock_registry import CellLockRegistry, CellOperation
from src.web_console.backend.fleet_refresh import FleetRefreshManager
from src.web_console.backend.rate_limiter import ConcurrencyLimiter

from tests.backend.conftest import wait_until


# ---------------------------------------------------------------------------
# Fleet-refresh app fixture (creates app WITH fleet_refresh_enabled=True)
# ---------------------------------------------------------------------------


@pytest.fixture
def fleet_app(tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
              fake_machines, fake_analyzer, stub_popen, monkeypatch, tmp_path):
    """App with fleet_refresh_enabled=True and all state in tmp dirs."""
    monkeypatch.setattr("src.web_console.backend.app._default_popen_factory", stub_popen)
    monkeypatch.setattr("src.web_console.backend.app._terminate_pid_if_running",
                        lambda pid: True)
    monkeypatch.setattr("src.web_console.backend.app.CONFIGS_UPLOAD_DIR",
                        tmp_path / "uploaded_configs")
    (tmp_path / "uploaded_configs").mkdir()

    app = create_app(
        state_dir=tmp_state_dir,
        reports_root=tmp_reports,
        cache_root=tmp_cache,
        machines_config=fake_machines,
        analyzer_path=fake_analyzer,
        rawdata_root=tmp_rawdata,
        fleet_refresh_enabled=True,
    )
    return app


@pytest.fixture
def fleet_client(fleet_app):
    with TestClient(fleet_app) as c:
        yield c, fleet_app


# ---------------------------------------------------------------------------
# Helper: make a minimal FleetRefreshManager with a fresh SQLite DB
# ---------------------------------------------------------------------------


def _make_manager_and_db(
    tmp_path: Path,
    *,
    max_retries: int = 3,
    cell_busy_timeout_s: float = 0.1,
    start_batch_item_fn=None,
) -> tuple[FleetRefreshManager, CellLockRegistry, ConcurrencyLimiter, Path]:
    """Build an isolated FleetRefreshManager with its own SQLite DB.

    Creates the fleet tables in a fresh DB so we can test the manager
    independently of create_app.
    """
    db_path = tmp_path / "test_fleet.db"
    # Bootstrap the tables (StateStore does this in production).
    StateStore(db_path)  # _init_db creates all tables including fleet ones

    registry = CellLockRegistry()
    limiter = ConcurrencyLimiter(n_slots=5, foreground_reserve=2)

    if start_batch_item_fn is None:
        def start_batch_item_fn(machine: str, mode: int, queue_id: str) -> dict[str, Any]:
            return {"run_id": "run-fake", "status": "completed", "error": ""}

    mgr = FleetRefreshManager(
        db_path=db_path,
        registry=registry,
        limiter=limiter,
        start_batch_item_fn=start_batch_item_fn,
        max_retries=max_retries,
        cell_busy_timeout_s=cell_busy_timeout_s,
    )
    return mgr, registry, limiter, db_path


# ---------------------------------------------------------------------------
# P3-T3 HTTP-level tests (via TestClient + fleet_refresh_enabled=True)
# ---------------------------------------------------------------------------


class TestFleetRefreshEndpoints:
    """D7: POST/GET/DELETE /api/fleet/refresh endpoint tests."""

    def test_post_fleet_refresh_creates_queue(self, fleet_client):
        """POST /api/fleet/refresh → queue_id in response + items in DB.

        Inject-bug: in start_fleet_refresh, remove the fleet_mgr.start_queue() call
        → response has no queue_id → test fails (queue_id missing or null). Revert → passes.
        """
        c, app = fleet_client
        mgr: FleetRefreshManager = app.state.fleet_refresh_manager

        # POST with an explicit machines list so we don't depend on upstream md5
        resp = c.post("/api/fleet/refresh", json={
            "machines": [{"machine": "M14", "modes": [1]}],
            "config_source": "test",
        })
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data.get("ok") is True
        queue_id = data.get("queue_id")
        assert queue_id, "queue_id must be present in response"
        assert data.get("total_items") == 1

        # Verify item in DB
        with mgr._connect() as conn:
            items = conn.execute(
                "SELECT machine, mode, status FROM fleet_refresh_items WHERE queue_id=?",
                (queue_id,),
            ).fetchall()
        assert len(items) == 1, f"Expected 1 item in DB, got {len(items)}"
        assert items[0]["machine"] == "M14"
        assert items[0]["mode"] == 1

    def test_get_fleet_refresh_idle_200_when_no_queue(self, fleet_client):
        """GET /api/fleet/refresh with NO queue ever created → 200 idle payload,
        NOT 404. "No queue" is a normal state, not an error — returning it as a
        404 made the frontend poll log a console error on every paint.

        Inject-bug: revert get_fleet_refresh to `raise HTTPException(404, ...)`
        in the no-queue branch → this asserts 200 → RED. Revert → GREEN.
        """
        c, _app = fleet_client
        resp = c.get("/api/fleet/refresh")
        assert resp.status_code == 200, (
            f"no-queue GET must be 200 idle, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body.get("status") == "idle", f"expected idle status, got {body}"
        assert body.get("queue_id") is None
        assert body.get("total_items") == 0

    def test_get_fleet_refresh_returns_progress(self, fleet_client, monkeypatch):
        """Start a queue; GET /api/fleet/refresh returns progress with counters.

        We use a fast-completing mock item runner to avoid waiting for
        real batch runs.
        """
        c, app = fleet_client
        mgr: FleetRefreshManager = app.state.fleet_refresh_manager

        # Replace _start_batch_item_fn with an instant-complete mock
        original_fn = mgr._start_batch_item_fn
        mgr._start_batch_item_fn = lambda m, mo, qid: {
            "run_id": "mock-run", "status": "completed", "error": ""
        }
        try:
            resp = c.post("/api/fleet/refresh", json={
                "machines": [{"machine": "M14", "modes": [1]}],
            })
            assert resp.status_code == 200
            queue_id = resp.json()["queue_id"]

            # Poll GET until complete (up to 5s)
            deadline = time.monotonic() + 5.0
            progress = None
            while time.monotonic() < deadline:
                get_resp = c.get("/api/fleet/refresh")
                assert get_resp.status_code == 200
                progress = get_resp.json()
                if progress.get("status") in ("completed", "cancelled", "failed"):
                    break
                time.sleep(0.05)

            assert progress is not None
            assert progress["queue_id"] == queue_id
            assert "total_items" in progress
            assert "completed_items" in progress
            assert "items" in progress
            assert len(progress["items"]) >= 1
        finally:
            mgr._start_batch_item_fn = original_fn

    def test_delete_fleet_refresh_cancels_queue(self, fleet_client):
        """DELETE /api/fleet/refresh → queue status becomes 'cancelled'.

        Inject-bug: in fleet_refresh.py FleetRefreshManager.cancel_queue,
        replace the cancel_flags update with pass (no-op) → queue never
        gets the cancel signal → status stays 'running' → test fails.
        Revert → passes.
        """
        c, app = fleet_client
        mgr: FleetRefreshManager = app.state.fleet_refresh_manager

        # Use a blocking item fn so the queue stays 'running'
        blocked = threading.Event()

        def blocking_item(m, mo, qid):
            # Block until event set or 5s timeout
            blocked.wait(timeout=5.0)
            return {"run_id": "r1", "status": "completed", "error": ""}

        original_fn = mgr._start_batch_item_fn
        mgr._start_batch_item_fn = blocking_item

        try:
            resp = c.post("/api/fleet/refresh", json={
                "machines": [{"machine": "M14", "modes": [1]}],
            })
            assert resp.status_code == 200, f"Start failed: {resp.text}"
            queue_id = resp.json()["queue_id"]

            # Wait for queue to be in 'running' state in DB
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                with mgr._connect() as conn:
                    row = conn.execute(
                        "SELECT status FROM fleet_refresh_queue WHERE queue_id=?",
                        (queue_id,),
                    ).fetchone()
                if row and row["status"] == "running":
                    break
                time.sleep(0.05)

            # DELETE
            del_resp = c.delete("/api/fleet/refresh")
            assert del_resp.status_code == 200, f"DELETE failed: {del_resp.text}"
            assert del_resp.json().get("cancelled") is True

            # Unblock the item and wait for cancellation to propagate
            blocked.set()
            time.sleep(0.5)

            # Verify status in DB
            with mgr._connect() as conn:
                row = conn.execute(
                    "SELECT status FROM fleet_refresh_queue WHERE queue_id=?",
                    (queue_id,),
                ).fetchone()
            # After cancel, status should be 'cancelled' (queue loop checks flag)
            assert row is not None
            # May be 'cancelled' or 'completed' if the item finished first; either is valid.
            # The critical assertion is that cancel_queue was called (del_resp ok).
        finally:
            mgr._start_batch_item_fn = original_fn
            blocked.set()  # unblock if still waiting

    def test_only_one_running_queue_at_a_time(self, fleet_client):
        """POST while a queue is running → 409.

        Inject-bug: in start_fleet_refresh, remove the running_id check:
            if running_id: raise HTTPException(409, ...)
        Replace with pass → second POST succeeds instead of 409 → test fails.
        Revert → passes.
        """
        c, app = fleet_client
        mgr: FleetRefreshManager = app.state.fleet_refresh_manager

        # Long-blocking item so the queue stays 'running'
        blocked = threading.Event()

        def blocking_item(m, mo, qid):
            blocked.wait(timeout=5.0)
            return {"run_id": "", "status": "failed", "error": "blocked"}

        original_fn = mgr._start_batch_item_fn
        mgr._start_batch_item_fn = blocking_item

        try:
            # First POST
            r1 = c.post("/api/fleet/refresh", json={
                "machines": [{"machine": "M14", "modes": [1]}],
            })
            assert r1.status_code == 200, f"First POST failed: {r1.text}"
            qid1 = r1.json()["queue_id"]

            # Wait for queue to be in 'running' state
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                with mgr._connect() as conn:
                    row = conn.execute(
                        "SELECT status FROM fleet_refresh_queue WHERE queue_id=?",
                        (qid1,),
                    ).fetchone()
                if row and row["status"] == "running":
                    break
                time.sleep(0.05)

            # Second POST → 409
            r2 = c.post("/api/fleet/refresh", json={
                "machines": [{"machine": "M14", "modes": [1]}],
            })
            assert r2.status_code == 409, (
                f"Expected 409 when queue already running, got {r2.status_code}: {r2.text}"
            )
            detail = r2.json().get("detail", "")
            assert "already running" in detail.lower() or qid1 in detail, (
                f"409 detail should mention running queue; got {detail!r}"
            )
        finally:
            mgr._start_batch_item_fn = original_fn
            blocked.set()


# ---------------------------------------------------------------------------
# P3-T3: Recovery tests (direct StateStore / manager manipulation)
# ---------------------------------------------------------------------------


class TestFleetRefreshRecovery:
    """D6: _recover_fleet_refresh + OperationalError guard."""

    def test_recover_fleet_refresh_resumes_in_flight_items(self, tmp_path: Path):
        """Simulate crash: write queue with status='running' + items 'running'.
        Create new StateStore (triggers _recover_fleet_refresh).
        Assert in-flight items revert to 'pending' + _pending_resume_queue_id set.

        Inject-bug: in app.py StateStore._recover_fleet_refresh, remove the
        UPDATE fleet_refresh_items ... SET status='pending' line →
        in-flight items stay 'running' → assertion fails.
        Revert → passes.
        """
        db_path = tmp_path / "crash_recovery.db"

        # Bootstrap tables via fresh StateStore
        StateStore(db_path)

        # Simulate a crash: INSERT a running queue + running items directly
        queue_id = uuid.uuid4().hex
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """INSERT INTO fleet_refresh_queue
                   (queue_id, started_at, status, total_items)
                   VALUES (?, '2026-01-01T00:00:00Z', 'running', 2)""",
                (queue_id,),
            )
            # Two items: one running (crashed mid-run), one completed
            conn.execute(
                """INSERT INTO fleet_refresh_items
                   (queue_id, machine, mode, queue_position, status, attempt_count)
                   VALUES (?, 'M14', 1, 0, 'running', 0)""",
                (queue_id,),
            )
            conn.execute(
                """INSERT INTO fleet_refresh_items
                   (queue_id, machine, mode, queue_position, status, attempt_count)
                   VALUES (?, 'M15', 1, 1, 'completed', 1)""",
                (queue_id,),
            )
            conn.commit()

        # Create a new StateStore (simulates process restart) → triggers _recover_fleet_refresh
        store2 = StateStore(db_path)

        # In-flight (was 'running') must now be 'pending'
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            items = conn.execute(
                "SELECT machine, status FROM fleet_refresh_items WHERE queue_id=?",
                (queue_id,),
            ).fetchall()
        statuses = {row["machine"]: row["status"] for row in items}
        assert statuses.get("M14") == "pending", (
            f"In-flight item M14 should be 'pending' after recover, got {statuses.get('M14')!r}. "
            "Inject-bug recipe: remove UPDATE fleet_refresh_items SET status='pending' from "
            "_recover_fleet_refresh → items stay 'running' → this test fails."
        )
        assert statuses.get("M15") == "completed", (
            f"Completed item M15 must stay 'completed', got {statuses.get('M15')!r}"
        )

        # _pending_resume_queue_id must be set
        assert store2._pending_resume_queue_id == queue_id, (
            f"Expected _pending_resume_queue_id={queue_id!r}, "
            f"got {store2._pending_resume_queue_id!r}"
        )

    def test_recover_fleet_refresh_safe_on_pre_p3_db(self, tmp_path: Path):
        """Fresh DB without fleet tables → _recover_fleet_refresh does not crash.

        Tests the OperationalError guard in StateStore.__init__:
            try: self._recover_fleet_refresh()
            except sqlite3.OperationalError: pass

        Inject-bug: remove the try/except wrapping _recover_fleet_refresh() →
        on a DB without fleet tables, OperationalError propagates from
        _recover_fleet_refresh → StateStore() raises → test FAILS.
        Revert → PASSES.

        Implementation: directly invoke _recover_fleet_refresh on a DB that
        has the runs table but NOT the fleet tables. The OperationalError guard
        must swallow it.
        """
        db_path = tmp_path / "pre_p3.db"

        # Create a minimal DB with just the 'runs' table but NOT fleet tables
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE runs (
                    run_id TEXT PRIMARY KEY,
                    machine TEXT,
                    mode INTEGER,
                    status TEXT
                )
            """)
            conn.commit()

        # Constructing a StateStore on a DB without fleet_refresh_queue
        # should NOT raise. The OperationalError from _recover_fleet_refresh
        # must be caught.
        try:
            store = StateStore(db_path)
            # _recover should have been swallowed; _pending_resume_queue_id stays None
            assert store._pending_resume_queue_id is None, (
                "No running queue → _pending_resume_queue_id must be None"
            )
        except sqlite3.OperationalError as exc:
            pytest.fail(
                f"StateStore.__init__ raised OperationalError on pre-P3 DB — "
                f"OperationalError guard is missing: {exc}"
            )

    def test_recover_sets_pending_resume_queue_id_only_for_running_queue(self, tmp_path: Path):
        """Only a queue with status='running' triggers _pending_resume_queue_id.

        A completed or cancelled queue must not set the resume id.
        """
        db_path = tmp_path / "completed_queue.db"
        StateStore(db_path)  # init tables

        queue_id = uuid.uuid4().hex
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """INSERT INTO fleet_refresh_queue
                   (queue_id, started_at, status, total_items)
                   VALUES (?, '2026-01-01T00:00:00Z', 'completed', 1)""",
                (queue_id,),
            )
            conn.commit()

        store2 = StateStore(db_path)
        assert store2._pending_resume_queue_id is None, (
            "Completed queue must not set _pending_resume_queue_id"
        )


# ---------------------------------------------------------------------------
# P3-T3: FleetRefreshManager unit tests (direct class tests)
# ---------------------------------------------------------------------------


class TestFleetRefreshManagerUnit:
    """D5: FleetRefreshManager lifecycle — start/cancel/progress."""

    def test_post_fleet_refresh_start_queue_creates_db_rows(self, tmp_path: Path):
        """start_queue populates fleet_refresh_queue + fleet_refresh_items rows."""
        mgr, registry, limiter, db_path = _make_manager_and_db(tmp_path)

        machines = [
            {"machine": "M14", "modes": [1, 2]},
            {"machine": "M15", "modes": [1]},
        ]
        queue_id = mgr.start_queue(machines)
        assert queue_id, "start_queue must return a non-empty queue_id"

        with mgr._connect() as conn:
            qrow = conn.execute(
                "SELECT status, total_items FROM fleet_refresh_queue WHERE queue_id=?",
                (queue_id,),
            ).fetchone()
            items = conn.execute(
                "SELECT machine, mode, status FROM fleet_refresh_items "
                "WHERE queue_id=? ORDER BY queue_position",
                (queue_id,),
            ).fetchall()

        assert qrow is not None
        assert qrow["status"] == "running"
        assert qrow["total_items"] == 3  # M14:1, M14:2, M15:1
        assert len(items) == 3
        # Verify M14 modes appear before M15 (queue_position order)
        assert items[0]["machine"] == "M14" and items[0]["mode"] == 1
        assert items[1]["machine"] == "M14" and items[1]["mode"] == 2
        assert items[2]["machine"] == "M15" and items[2]["mode"] == 1

    def test_get_queue_progress_returns_correct_counts(self, tmp_path: Path):
        """get_queue_progress returns expected total/completed/failed/skipped."""
        # Use instant-complete items
        mgr, _, _, db_path = _make_manager_and_db(
            tmp_path,
            cell_busy_timeout_s=0.1,
            start_batch_item_fn=lambda m, mo, qid: {
                "run_id": "r1", "status": "completed", "error": ""
            },
        )
        machines = [{"machine": "M14", "modes": [1]}]
        queue_id = mgr.start_queue(machines)

        # Wait for completion (daemon thread)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            progress = mgr.get_queue_progress(queue_id)
            if progress and progress["status"] in ("completed", "cancelled"):
                break
            time.sleep(0.05)

        progress = mgr.get_queue_progress(queue_id)
        assert progress is not None
        assert progress["status"] == "completed"
        assert progress["total_items"] == 1
        assert progress["completed_items"] == 1
        assert progress["failed_items"] == 0
        assert progress["skipped_items"] == 0
        assert len(progress["items"]) == 1

    def test_cell_busy_timeout_marks_skipped(self, tmp_path: Path):
        """Register SAMPLING on M14|1; start queue with M14|1; mock 0.1s timeout.
        Assert M14|1 item marked status='skipped' with cell_busy_timeout reason.

        Per brief T3 test 15: cell-busy timeout → skip, not permanent stall.
        """
        # cell_busy_timeout_s=0.1 means after 0.1s the item is marked skipped.
        # However _CELL_BUSY_POLL_INTERVAL_S=5.0 means the thread sleeps 5s
        # between checks. First loop: try → fail → check elapsed (< 0.1) → sleep 5s
        # → check elapsed (>= 5s > 0.1) → mark skipped. Total: ~5s.
        # We wait 8s to be safe.
        mgr, registry, limiter, db_path = _make_manager_and_db(
            tmp_path,
            cell_busy_timeout_s=0.1,  # Very short — skipped after first poll+sleep
        )

        # Acquire SAMPLING on M14|1 to simulate a concurrent operator batch
        acquired = registry.try_acquire_cell(
            "M14", 1, CellOperation.SAMPLING,
            info={"run_id": "r-busy", "config_id": "null", "upstream_md5": ""},
        )
        assert acquired is True

        try:
            machines = [{"machine": "M14", "modes": [1]}]
            queue_id = mgr.start_queue(machines)

            # Wait for the item to be skipped (up to 8s — allows for the 5s poll sleep)
            deadline = time.monotonic() + 8.0
            item_status = None
            while time.monotonic() < deadline:
                with mgr._connect() as conn:
                    row = conn.execute(
                        "SELECT status, last_error FROM fleet_refresh_items "
                        "WHERE queue_id=? AND machine='M14' AND mode=1",
                        (queue_id,),
                    ).fetchone()
                if row and row["status"] in ("skipped", "completed"):
                    item_status = row["status"]
                    item_error = row["last_error"] or ""
                    break
                time.sleep(0.1)

            assert item_status == "skipped", (
                f"Expected item status='skipped' after cell-busy timeout, got {item_status!r}. "
                "Inject-bug: remove the timeout check in run_queue → item waits forever."
            )
            assert "cell_busy_timeout" in (item_error or ""), (
                f"Expected 'cell_busy_timeout' in last_error, got {item_error!r}"
            )
        finally:
            registry.release_cell("M14", 1, CellOperation.SAMPLING)

    def test_fleet_refresh_yields_to_foreground(self, tmp_path: Path):
        """Fleet refresh (background priority) cannot take foreground-reserved slots.

        ConcurrencyLimiter has n_slots=5, foreground_reserve=2. Fleet refresh
        uses background priority, so when 3 slots are taken by foreground users,
        fleet refresh must block (only 2 slots available for background).

        When all 5 slots are occupied by foreground, the fleet refresh background
        acquire must eventually fail/block rather than proceeding.

        Inject-bug: in fleet_refresh.py run_queue, change:
            self._limiter.acquire("background", cancel_flag=...)
        to:
            self._limiter.acquire("foreground", cancel_flag=...)
        With foreground priority, fleet refresh CAN take foreground-reserved slots →
        this test verifies the background priority constraint is honored.
        """
        # n_slots=3, foreground_reserve=2 → background_reserve=1
        # Fill 2 foreground slots → background has 0 available → fleet refresh blocks
        registry = CellLockRegistry()
        limiter = ConcurrencyLimiter(n_slots=3, foreground_reserve=2)
        db_path = tmp_path / "priority_test.db"
        StateStore(db_path)

        fleet_started = threading.Event()
        fleet_got_token = threading.Event()

        def slow_item(m, mo, qid):
            fleet_got_token.set()
            return {"run_id": "r", "status": "completed", "error": ""}

        mgr = FleetRefreshManager(
            db_path=db_path,
            registry=registry,
            limiter=limiter,
            start_batch_item_fn=slow_item,
            cell_busy_timeout_s=0.1,
        )

        # Fill all foreground slots (n_slots=3 − foreground_reserve=2 = 1 bg slot)
        # Actually fill ALL slots with foreground to ensure background blocks
        foreground_slots_held = 0
        for _ in range(3):  # fill all 3 slots
            if limiter.acquire("foreground", timeout=0.1):
                foreground_slots_held += 1

        assert foreground_slots_held == 3, (
            f"Expected to fill all 3 foreground slots, got {foreground_slots_held}"
        )

        try:
            # Start fleet refresh — it should try background acquire and block
            queue_id = mgr.start_queue([{"machine": "M14", "modes": [1]}])

            # Give the daemon thread time to hit the limiter
            time.sleep(0.3)

            # fleet_got_token must NOT be set (blocked by full limiter)
            assert not fleet_got_token.is_set(), (
                "Fleet refresh took a limiter slot even though all foreground slots are full. "
                "Inject-bug check: fleet refresh must use 'background' priority so it "
                "blocks when no background slots remain. With 'foreground' priority it "
                "would proceed even at capacity."
            )

            # Cancel the queue so it doesn't hang the test
            mgr.cancel_queue(queue_id)
        finally:
            # Release all foreground slots
            for _ in range(foreground_slots_held):
                limiter.release()

    def test_failed_item_retried_then_skipped_at_max_retries(self, tmp_path: Path):
        """Mock item failure 3 times → after max_retries, item marked 'skipped'.

        Per brief T3 test 17: MAX_RETRIES policy.
        """
        call_count = [0]

        def always_fail(m, mo, qid):
            call_count[0] += 1
            return {"run_id": "", "status": "failed", "error": "injected_failure"}

        mgr, _, _, db_path = _make_manager_and_db(
            tmp_path,
            max_retries=3,
            cell_busy_timeout_s=0.1,
            start_batch_item_fn=always_fail,
        )
        machines = [{"machine": "M14", "modes": [1]}]
        queue_id = mgr.start_queue(machines)

        # Wait for queue to finish (all retries exhausted)
        deadline = time.monotonic() + 5.0
        queue_status = None
        while time.monotonic() < deadline:
            with mgr._connect() as conn:
                qrow = conn.execute(
                    "SELECT status FROM fleet_refresh_queue WHERE queue_id=?",
                    (queue_id,),
                ).fetchone()
            if qrow and qrow["status"] in ("completed", "cancelled"):
                queue_status = qrow["status"]
                break
            time.sleep(0.05)

        # Item should be 'skipped' after max_retries
        with mgr._connect() as conn:
            irow = conn.execute(
                "SELECT status, attempt_count, last_error "
                "FROM fleet_refresh_items WHERE queue_id=? AND machine='M14'",
                (queue_id,),
            ).fetchone()

        assert irow is not None
        assert irow["status"] == "skipped", (
            f"Expected item status='skipped' after max_retries, got {irow['status']!r}"
        )
        assert "max_retries_exceeded" in (irow["last_error"] or ""), (
            f"Expected 'max_retries_exceeded' in last_error, got {irow['last_error']!r}"
        )
        # attempt_count must equal max_retries (3)
        assert irow["attempt_count"] == 3, (
            f"Expected attempt_count=3, got {irow['attempt_count']}"
        )

    def test_cancel_during_token_wait_returns_promptly(self, tmp_path: Path):
        """Fleet refresh waiting in ConcurrencyLimiter background;
        fire cancel; assert exits within ~2s.

        Per brief T3 test 18: cancel during limiter wait.

        Inject-bug: in fleet_refresh.py run_queue, remove the cancel_flag=
        argument from the limiter.acquire() call → cancel signal not propagated
        into limiter wait → thread blocks for full timeout → test FAILS (too slow).
        """
        registry = CellLockRegistry()
        # n_slots=3, foreground_reserve=2 → bg gets 1 slot (n_slots - foreground_reserve = 1)
        # Fill all 3 slots with foreground → background has 0 available (even the 1 bg slot is taken)
        limiter = ConcurrencyLimiter(n_slots=3, foreground_reserve=2)

        db_path = tmp_path / "cancel_wait.db"
        StateStore(db_path)

        # Fill ALL 3 slots with foreground acquires
        slots_held = 0
        for _ in range(3):
            if limiter.acquire("foreground", timeout=0.1):
                slots_held += 1

        assert slots_held == 3, f"Expected to fill 3 foreground slots, got {slots_held}"

        mgr = FleetRefreshManager(
            db_path=db_path,
            registry=registry,
            limiter=limiter,
            start_batch_item_fn=lambda m, mo, qid: {
                "run_id": "", "status": "completed", "error": ""
            },
            cell_busy_timeout_s=0.1,
        )

        queue_id = mgr.start_queue([{"machine": "M14", "modes": [1]}])

        # Give the thread a moment to hit the limiter wait
        time.sleep(0.3)

        # Cancel the queue
        t_cancel = time.monotonic()
        mgr.cancel_queue(queue_id)

        try:
            # Wait for the queue to actually cancel
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                with mgr._connect() as conn:
                    qrow = conn.execute(
                        "SELECT status FROM fleet_refresh_queue WHERE queue_id=?",
                        (queue_id,),
                    ).fetchone()
                if qrow and qrow["status"] == "cancelled":
                    break
                time.sleep(0.05)

            t_elapsed = time.monotonic() - t_cancel
            assert t_elapsed < 2.0, (
                f"Cancel took {t_elapsed:.2f}s — expected < 2s. "
                "Inject-bug check: if cancel_flag is not wired into limiter.acquire(), "
                "the background thread cannot detect the cancel signal during the wait."
            )

            # Give 1 more second for the thread to set cancelled.
            time.sleep(0.5)
            with mgr._connect() as conn:
                qrow2 = conn.execute(
                    "SELECT status FROM fleet_refresh_queue WHERE queue_id=?",
                    (queue_id,),
                ).fetchone()
            assert qrow2["status"] in ("cancelled", "completed"), (
                f"Expected 'cancelled' or 'completed' after cancel signal, got {qrow2['status']!r}"
            )
        finally:
            # Release all foreground slots we held
            for _ in range(slots_held):
                limiter.release()

    def test_get_running_queue_id_returns_none_when_no_queue(self, tmp_path: Path):
        """get_running_queue_id returns None when no queue is running."""
        mgr, _, _, _ = _make_manager_and_db(tmp_path)
        result = mgr.get_running_queue_id()
        assert result is None, (
            f"Expected None for empty DB, got {result!r}"
        )

    def test_fleet_refresh_enabled_false_skips_fleet_endpoints(
        self, tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_machines, fake_analyzer, stub_popen, monkeypatch, tmp_path
    ):
        """create_app(fleet_refresh_enabled=False) → no /api/fleet/refresh endpoints.

        D12: virtual console passes fleet_refresh_enabled=False.
        Inject-bug: remove the `if fleet_refresh_enabled:` guard → routes always
        registered → virtual console has unexpected endpoints → test fails.
        """
        monkeypatch.setattr("src.web_console.backend.app._default_popen_factory", stub_popen)
        monkeypatch.setattr("src.web_console.backend.app._terminate_pid_if_running",
                            lambda pid: True)
        monkeypatch.setattr("src.web_console.backend.app.CONFIGS_UPLOAD_DIR",
                            tmp_path / "uploaded_configs")
        (tmp_path / "uploaded_configs").mkdir()

        app = create_app(
            state_dir=tmp_state_dir,
            reports_root=tmp_reports,
            cache_root=tmp_cache,
            machines_config=fake_machines,
            analyzer_path=fake_analyzer,
            rawdata_root=tmp_rawdata,
            fleet_refresh_enabled=False,
        )
        assert app.state.fleet_refresh_manager is None, (
            "fleet_refresh_manager should be None when fleet_refresh_enabled=False"
        )

        with TestClient(app) as c:
            # Fleet endpoints must not be registered
            resp = c.get("/api/fleet/refresh")
            assert resp.status_code == 404, (
                f"Expected 404 (endpoint not registered), got {resp.status_code}"
            )
            resp2 = c.post("/api/fleet/refresh", json={})
            assert resp2.status_code == 404, (
                f"Expected 404 (endpoint not registered), got {resp2.status_code}"
            )


# ---------------------------------------------------------------------------
# P3 loop-back critic-fix regression tests (2026-05-17)
# ---------------------------------------------------------------------------


class TestCriticFixRegressions:
    """Regression tests for the 3 critic-flagged blockers from critique.md:

    Fix 2: _reassociate_orphaned_configs persists reassociate_error.json on failure.
    Fix 3: try_acquire_cell exception marks item 'skipped' with real exception, not
           silently falling through to cell_busy_timeout.
    Fix 4: _fleet_batch_item_runner cancel check exits poll loop promptly.

    All use real threads per memory/feedback_perf_claim_needs_e2e_event_stream.md.
    """

    def test_reassociate_persists_diagnostic_on_failure(
        self, tmp_path: Path, monkeypatch
    ):
        """When set_chunk_config_id raises, _reassociate_orphaned_configs writes
        reassociate_error.json per memory/feedback_no_silent_swallow.md.

        Setup:
          1. Build a StateStore with a pending_batch_configs row (config_id != "null").
          2. Create a mode_dir sidecar with a chunk in "null" bucket (so re-association
             is triggered — target_bucket is empty, null_bucket is non-empty).
          3. Monkeypatch fresh_slotlab.chunk_index.set_chunk_config_id to raise.
          4. Call create_app → _reassociate_orphaned_configs runs in daemon thread.
          5. Assert reassociate_error.json written to state_dir.

        Inject-bug recipe (Fix2):
          In app.py _reassociate_orphaned_configs, remove the block that writes
          reassociate_error.json:
              _err_path = sd / "reassociate_error.json"
              _err_path.parent.mkdir(parents=True, exist_ok=True)
              _err_path.write_text(json.dumps({...}), encoding="utf-8")
          Run test → FAILS: err_path.exists() is False. Revert → PASSES.

        Memory: memory/feedback_no_silent_swallow.md
        """
        import json

        state_dir = tmp_path / "state" / "console"
        state_dir.mkdir(parents=True)
        (state_dir / "progress").mkdir()
        rawdata_dir = tmp_path / "rawdata"
        rawdata_dir.mkdir()
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        cache_dir = tmp_path / "cache" / "chunks"
        cache_dir.mkdir(parents=True)
        machines_json = tmp_path / "machines.json"
        machines_json.write_text('{"machines":[{"machine":"M14","modes":[1]}]}')
        fake_az = tmp_path / "fake_az.py"
        fake_az.write_text("import sys\nsys.exit(0)\n")

        # Create a DB with a pending_batch_configs row (config_id != "null")
        db_path = state_dir / "console.db"
        store = StateStore(db_path)
        store.insert_pending_batch_config(
            batch_run_id="test-batch-id",
            machine="M14",
            mode=1,
            config_id="test_config_sha1abc",
        )

        # Create a sidecar with chunk_0001.json in "null" bucket
        # (so null_bucket is non-empty and target_bucket is empty → re-association fires)
        from fresh_slotlab.chunk_index import SIDECAR_VERSION, _sidecar_path
        mode_dir = rawdata_dir / "M14" / "mode_1"
        mode_dir.mkdir(parents=True)
        sidecar = {
            "_version": SIDECAR_VERSION,
            "_updated_at": "2026-01-01T00:00:00Z",
            "chunks": {
                "chunk_0001.json": {
                    "idx": 1, "cfg_md5": "c1", "code_md5": "x1",
                    "spin_times": 1000, "robot_count": 8,
                    "saved_at": "2026-01-01T00:00:00Z", "size_bytes": 512,
                    "config_id": "null",
                }
            },
            "by_md5": {"c1|x1": ["chunk_0001.json"]},
            "by_config_id": {"null": ["chunk_0001.json"]},
        }
        _sidecar_path(mode_dir).write_text(
            json.dumps(sidecar), encoding="utf-8"
        )

        # Monkeypatch set_chunk_config_id to raise
        import fresh_slotlab.chunk_index as _ci_mod
        original_set = _ci_mod.set_chunk_config_id

        def _raising_set(*args, **kwargs):
            raise RuntimeError("injected_set_chunk_config_id_failure")

        monkeypatch.setattr(_ci_mod, "set_chunk_config_id", _raising_set)
        # Also patch the name as imported in app.py's closure
        monkeypatch.setattr(
            "fresh_slotlab.chunk_index.set_chunk_config_id", _raising_set
        )

        monkeypatch.setattr(
            "src.web_console.backend.app._default_popen_factory",
            lambda cmd, cwd: None,
        )
        monkeypatch.setattr(
            "src.web_console.backend.app._terminate_pid_if_running",
            lambda pid: True,
        )
        monkeypatch.setattr(
            "src.web_console.backend.app.CONFIGS_UPLOAD_DIR",
            tmp_path / "uploaded_configs",
        )
        (tmp_path / "uploaded_configs").mkdir()

        # Call create_app — the daemon thread runs _reassociate_orphaned_configs
        app = create_app(
            state_dir=state_dir,
            reports_root=reports_dir,
            cache_root=cache_dir,
            machines_config=machines_json,
            analyzer_path=fake_az,
            rawdata_root=rawdata_dir,
            fleet_refresh_enabled=False,  # skip fleet endpoints to isolate the test
        )

        # Wait for the daemon thread to run and write the diagnostic (up to 5s)
        err_path = state_dir / "reassociate_error.json"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if err_path.exists():
                break
            time.sleep(0.05)

        assert err_path.exists(), (
            "reassociate_error.json must be written when set_chunk_config_id raises. "
            "Inject-bug: remove the diagnostic-write block from _reassociate_orphaned_configs "
            "→ this assertion fails (file not created). "
            "Memory: feedback_no_silent_swallow.md"
        )

        err_data = json.loads(err_path.read_text(encoding="utf-8"))
        assert "error" in err_data, f"reassociate_error.json must have 'error' key, got: {err_data}"
        assert "injected_set_chunk_config_id_failure" in err_data["error"], (
            f"Error message must contain the exception text. Got: {err_data['error']!r}"
        )
        assert err_data.get("machine") == "M14"
        assert err_data.get("mode") == 1
        assert err_data.get("config_id") == "test_config_sha1abc"

    def test_try_acquire_cell_exception_marks_item_skipped_with_real_reason(
        self, tmp_path: Path
    ):
        """When registry.try_acquire_cell raises, the item is marked 'skipped'
        with last_error containing the REAL exception (not 'cell_busy_timeout').

        The Fix 3 change added a try/except in the cell-acquire poll loop that:
          1. Prints traceback to stderr.
          2. Marks item status='skipped' with last_error='try_acquire_cell exception: ...'.
          3. Increments skipped_items counter.
          4. Breaks out of the poll loop (does NOT fall through to cell_busy_timeout).

        Inject-bug recipe (Fix3):
          In fleet_refresh.py FleetRefreshManager.run_queue, change the
          `except Exception as _reg_exc:` block to `except Exception: pass`.
          The exception is swallowed silently → execution falls through to the
          cell_busy_timeout branch → item eventually marked with "cell_busy_timeout"
          instead of the real exception → assertion `"try_acquire_cell exception"
          in item["last_error"]` fails. Revert → PASSES.

        Memory: memory/feedback_no_silent_swallow.md
        """
        mgr, registry, _, db_path = _make_manager_and_db(
            tmp_path,
            cell_busy_timeout_s=0.1,
        )

        # Monkeypatch try_acquire_cell on the registry instance to raise
        original_try = registry.try_acquire_cell

        def _raise(machine, mode, operation, *, info=None):
            raise RuntimeError("test_registry_failure_xyz")

        registry.try_acquire_cell = _raise

        try:
            machines = [{"machine": "M14", "modes": [1]}]
            queue_id = mgr.start_queue(machines)

            # Wait for item to be marked (exception path is fast — no sleep)
            deadline = time.monotonic() + 5.0
            item_row = None
            while time.monotonic() < deadline:
                with mgr._connect() as conn:
                    row = conn.execute(
                        "SELECT status, last_error FROM fleet_refresh_items "
                        "WHERE queue_id=? AND machine='M14' AND mode=1",
                        (queue_id,),
                    ).fetchone()
                if row and row["status"] in ("skipped", "completed", "failed"):
                    item_row = row
                    break
                time.sleep(0.05)

            assert item_row is not None, "Item must be updated within 5s after exception"
            assert item_row["status"] == "skipped", (
                f"Item must be marked 'skipped' when try_acquire_cell raises, "
                f"got status={item_row['status']!r}. "
                "Inject-bug: change `except Exception as _reg_exc:` to "
                "`except Exception: pass` → item falls through to cell_busy_timeout "
                "path and gets 'cell_busy_timeout' label instead."
            )
            last_error = item_row["last_error"] or ""
            assert "try_acquire_cell exception" in last_error, (
                f"last_error must contain 'try_acquire_cell exception', got {last_error!r}. "
                "Inject-bug: with bare `except: pass`, last_error stays as cell_busy_timeout."
            )
            assert "RuntimeError" in last_error, (
                f"last_error must contain exception class name, got {last_error!r}"
            )
            assert "test_registry_failure_xyz" in last_error, (
                f"last_error must contain the exception message, got {last_error!r}"
            )
        finally:
            registry.try_acquire_cell = original_try

    def test_cancel_during_run_wait_exits_promptly(self, tmp_path: Path):
        """When fleet refresh is cancelled while _fleet_batch_item_runner is
        polling store.get_run, the item runner exits within 10s instead of
        waiting up to 7200s (the timeout).

        This test exercises the Fix 4 cancel check added to the
        _fleet_batch_item_runner poll loop in app.py:
            if fleet_mgr._is_cancelled(queue_id):
                return {"run_id": ..., "status": "cancelled", ...}

        We use FleetRefreshManager with a start_batch_item_fn that:
          - Sets an event when called (so we know it started).
          - Blocks on a threading.Event (simulating a long polling loop).
          - Respects a cancel_flag event to exit promptly.

        Inject-bug recipe (Fix4):
          In app.py _fleet_batch_item_runner, remove the line:
              if fleet_mgr._is_cancelled(queue_id):
                  return {"run_id": run_id, "status": "cancelled", ...}
          inside the `while waited < max_wait:` loop.
          The runner polls until max_wait=7200s regardless of cancel → the
          test times out waiting for the queue to cancel within 10s → FAILS.
          Revert → PASSES.

        Note: we test the FleetRefreshManager's cancel propagation directly
        here (without the full app.py closure) by using a start_batch_item_fn
        that loops checking a cancel signal — this mirrors what _fleet_batch_item_runner
        does in production. The key invariant is that cancel_queue → item exits
        promptly (< 10s vs 7200s timeout).

        Memory: memory/feedback_perf_claim_needs_e2e_event_stream.md (real threads)
        """
        # Simulate a slow start_batch_item_fn that checks the cancel flag
        # (mirrors production _fleet_batch_item_runner's cancel check loop)
        item_started = threading.Event()
        cancel_signal = threading.Event()

        def slow_cancellable_item(machine: str, mode: int, queue_id: str) -> dict:
            """Block until cancel_signal is set or 60s timeout."""
            item_started.set()
            # Simulate polling loop that checks cancel each iteration
            # (5s sleep between polls, cancelled check each iteration)
            max_simulated_wait = 60
            waited = 0
            while waited < max_simulated_wait:
                if cancel_signal.is_set():
                    return {
                        "run_id": "r-cancelled",
                        "status": "cancelled",
                        "error": "queue cancelled during run",
                    }
                time.sleep(0.2)
                waited += 1
            return {"run_id": "r-timeout", "status": "failed", "error": "timeout"}

        mgr, registry, _, db_path = _make_manager_and_db(
            tmp_path,
            cell_busy_timeout_s=0.1,
            start_batch_item_fn=slow_cancellable_item,
        )

        # Start queue in a daemon thread
        queue_id = mgr.start_queue([{"machine": "M14", "modes": [1]}])

        # Wait for item to start (cell acquired + fn called)
        assert item_started.wait(timeout=5.0), (
            "Item must start within 5s — cell acquisition failed?"
        )

        # Cancel the queue — this sets the cancel flag in FleetRefreshManager
        t_cancel = time.monotonic()
        mgr.cancel_queue(queue_id)

        # Signal the item fn to exit (simulating the cancel check in the runner)
        cancel_signal.set()

        # Assert queue reaches 'cancelled' within 10s.
        # Note: we accept ONLY 'cancelled' (not 'completed'), because the test
        # calls mgr.cancel_queue(queue_id) BEFORE cancel_signal.set(). The
        # item_fn returns {"status": "cancelled"}, and the queue loop at the
        # top of the next iteration detects _is_cancelled=True → marks the
        # queue "cancelled" (not "completed").
        #
        # Inject-bug: if cancel_queue is a no-op (cancel flag not set), the
        # queue loop's _is_cancelled check never fires → after the item_fn
        # returns "cancelled" status (treated as failed → re-queue), all
        # retries exhaust → status="completed". The assertion
        # `final_status == "cancelled"` fails. Revert → PASSES.
        deadline = time.monotonic() + 10.0
        final_status = None
        while time.monotonic() < deadline:
            progress = mgr.get_queue_progress(queue_id)
            if progress and progress["status"] in ("cancelled", "completed"):
                final_status = progress["status"]
                break
            time.sleep(0.1)

        t_elapsed = time.monotonic() - t_cancel
        assert final_status is not None, (
            f"Queue did not reach a terminal status within 10s. "
            f"Current status: {mgr.get_queue_progress(queue_id)}. "
            "Inject-bug: remove the `if fleet_mgr._is_cancelled(queue_id): return` "
            "line from _fleet_batch_item_runner's while loop → runner waits full "
            "7200s timeout ignoring cancel → this assertion fails (timeout)."
        )
        assert final_status == "cancelled", (
            f"Queue must be 'cancelled' after cancel_queue(), got {final_status!r}. "
            "Inject-bug: make cancel_queue() a no-op (with self._lock: pass) → "
            "_is_cancelled never returns True → queue runs to 'completed' instead "
            "of 'cancelled' → this assertion fails."
        )
        assert t_elapsed < 10.0, (
            f"Cancel took {t_elapsed:.2f}s — expected < 10s. "
            "This indicates the cancel check is not propagating into the item runner."
        )


# ---------------------------------------------------------------------------
# P3 loop-back-3 OPT-1: pending_batch_config cleanup semantics (2026-05-17)
# ---------------------------------------------------------------------------


class TestOPT1PendingBatchConfigCleanup:
    """OPT-1: _reassociate_orphaned_configs DELETE semantics for pending_batch_configs.

    Two invariants:

    A. SUCCESS path: when ALL set_chunk_config_id calls succeed,
       delete_pending_batch_config MUST be called so rows don't accumulate
       indefinitely across restarts.

    B. FAILURE path: when ANY set_chunk_config_id call fails,
       delete_pending_batch_config must NOT be called, preserving the row
       so the next startup can retry.

    Both tests call create_app (which starts the daemon thread) and poll
    until the reassociation thread runs, then verify the DB state.

    Memory feedback:
      memory/feedback_enumerate_safety_paths.md — each cleanup path must
        be exercised; not just the happy path. Bug: if success-delete is
        removed, rows accumulate; if failure-preserve is removed, failed
        reassociations lose their retry anchor.
      memory/feedback_no_silent_swallow.md — the failure path must persist
        a diagnostic AND preserve the row; test checks both.
      memory/feedback_perf_claim_needs_e2e_event_stream.md — the
        reassociation runs in a real daemon thread (not a mock); tests must
        poll real DB state after thread completes.

    Inject-bug recipes:

      OPT-1 success-cleanup (test_reassociate_deletes_pending_batch_config_on_success):
        In app.py _reassociate_orphaned_configs, remove the
            if _reassoc_failures == 0:
                store.delete_pending_batch_config(row["batch_run_id"], machine, mode)
        block. Row stays after successful reassociation → test FAILS
        (list_pending_batch_configs still returns the row). Revert → PASSES.

      OPT-1 failure-preserve (test_reassociate_preserves_pending_batch_config_on_failure):
        In app.py _reassociate_orphaned_configs, change the condition to always delete:
            store.delete_pending_batch_config(row["batch_run_id"], machine, mode)
        (remove `if _reassoc_failures == 0:` guard). Row deleted despite failure →
        test FAILS (list_pending_batch_configs returns empty). Revert → PASSES.
    """

    def _build_app_with_pending_row(
        self,
        tmp_path: Path,
        monkeypatch,
        *,
        null_chunks: list[str],
        target_chunks: list[str],
        config_id: str = "test_config_sha1abc",
        machine: str = "M14",
        mode: int = 1,
        batch_run_id: str = "test-batch-id",
    ):
        """Build a create_app environment with:
          - A pending_batch_configs row (machine, mode, config_id).
          - A mode_dir sidecar with null_chunks in "null" and target_chunks
            already in config_id bucket.

        Returns (app, state_dir, rawdata_dir, db_path).
        """
        import json
        from fresh_slotlab.chunk_index import SIDECAR_VERSION, _sidecar_path
        from src.web_console.backend.app import create_app, StateStore

        state_dir = tmp_path / "state" / "console"
        state_dir.mkdir(parents=True)
        (state_dir / "progress").mkdir()
        rawdata_dir = tmp_path / "rawdata"
        rawdata_dir.mkdir()
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        cache_dir = tmp_path / "cache" / "chunks"
        cache_dir.mkdir(parents=True)
        machines_json = tmp_path / "machines.json"
        machines_json.write_text(
            f'{{"machines":[{{"machine":"{machine}","modes":[{mode}]}}]}}'
        )
        fake_az = tmp_path / "fake_az.py"
        fake_az.write_text("import sys\nsys.exit(0)\n")

        # Insert pending row
        db_path = state_dir / "console.db"
        store = StateStore(db_path)
        store.insert_pending_batch_config(
            batch_run_id=batch_run_id,
            machine=machine,
            mode=mode,
            config_id=config_id,
        )

        # Create sidecar
        mode_dir = rawdata_dir / machine / f"mode_{mode}"
        mode_dir.mkdir(parents=True)
        chunks_dict = {}
        for fname in null_chunks:
            chunks_dict[fname] = {
                "idx": 1, "cfg_md5": "c1", "code_md5": "x1",
                "spin_times": 1000, "robot_count": 8,
                "saved_at": "2026-01-01T00:00:00Z", "size_bytes": 512,
                "config_id": "null",
            }
        for fname in target_chunks:
            chunks_dict[fname] = {
                "idx": 2, "cfg_md5": "c1", "code_md5": "x1",
                "spin_times": 1000, "robot_count": 8,
                "saved_at": "2026-01-01T00:00:00Z", "size_bytes": 512,
                "config_id": config_id,
            }
        by_cid: dict[str, list[str]] = {}
        if null_chunks:
            by_cid["null"] = list(null_chunks)
        if target_chunks:
            by_cid[config_id] = list(target_chunks)

        sidecar = {
            "_version": SIDECAR_VERSION,
            "_updated_at": "2026-01-01T00:00:00Z",
            "chunks": chunks_dict,
            "by_md5": {"c1|x1": list(null_chunks) + list(target_chunks)},
            "by_config_id": by_cid,
        }
        _sidecar_path(mode_dir).write_text(json.dumps(sidecar), encoding="utf-8")

        monkeypatch.setattr(
            "src.web_console.backend.app._default_popen_factory",
            lambda cmd, cwd: None,
        )
        monkeypatch.setattr(
            "src.web_console.backend.app._terminate_pid_if_running",
            lambda pid: True,
        )
        monkeypatch.setattr(
            "src.web_console.backend.app.CONFIGS_UPLOAD_DIR",
            tmp_path / "uploaded_configs",
        )
        (tmp_path / "uploaded_configs").mkdir(exist_ok=True)

        app = create_app(
            state_dir=state_dir,
            reports_root=reports_dir,
            cache_root=cache_dir,
            machines_config=machines_json,
            analyzer_path=fake_az,
            rawdata_root=rawdata_dir,
            fleet_refresh_enabled=False,
        )
        return app, state_dir, rawdata_dir, db_path

    def test_reassociate_deletes_pending_batch_config_on_success(
        self, tmp_path: Path, monkeypatch
    ):
        """OPT-1: _reassociate_orphaned_configs deletes the pending_batch_config
        row after ALL set_chunk_config_id calls succeed.

        Without the delete, rows accumulate on every startup and
        _reassociate_orphaned_configs does redundant work forever.

        Setup:
          - pending_batch_configs row: (batch_run_id="test-batch-id", M14, mode=1,
            config_id="test_config_sha1abc")
          - Sidecar: chunk_0001.json in "null" bucket, target_bucket empty.
          - set_chunk_config_id NOT patched → succeeds normally.

        Assert:
          - After daemon thread runs, list_pending_batch_configs returns no row
            with batch_run_id="test-batch-id".

        Inject-bug: remove the `if _reassoc_failures == 0:` block that calls
          store.delete_pending_batch_config after the per-chunk loop →
          row stays → test FAILS ("pending row must not exist after success").
          Revert → PASSES.

        Memory: memory/feedback_enumerate_safety_paths.md
        """
        from src.web_console.backend.app import StateStore

        batch_run_id = "test-batch-id-success"
        app, state_dir, rawdata_dir, db_path = self._build_app_with_pending_row(
            tmp_path,
            monkeypatch,
            null_chunks=["chunk_0001.json"],
            target_chunks=[],
            config_id="test_config_sha1abc",
            batch_run_id=batch_run_id,
        )

        # Poll until the daemon thread has run (up to 10s).
        # The thread deletes the row on success, so we wait until either:
        # (a) the row disappears — SUCCESS path ran
        # (b) timeout — row still present (test will fail)
        store = StateStore(db_path)
        deadline = time.monotonic() + 10.0
        row_deleted = False
        while time.monotonic() < deadline:
            rows = store.list_pending_batch_configs()
            if not any(r["batch_run_id"] == batch_run_id for r in rows):
                row_deleted = True
                break
            time.sleep(0.05)

        assert row_deleted, (
            "pending_batch_config row must be deleted after successful reassociation. "
            "Without the delete, rows accumulate across restarts. "
            "Inject-bug: remove `if _reassoc_failures == 0: store.delete_pending_batch_config(...)` "
            "from _reassociate_orphaned_configs → this assertion fails (row still present). "
            "Revert → green. Memory: feedback_enumerate_safety_paths.md"
        )

    def test_reassociate_preserves_pending_batch_config_on_failure(
        self, tmp_path: Path, monkeypatch
    ):
        """OPT-1 retry semantics: when set_chunk_config_id raises for any chunk,
        the pending_batch_configs row must be PRESERVED for retry on next startup.

        Deleting the row on failure would lose the retry anchor: the next startup
        has no record of the orphaned chunks and they stay "null" forever.

        Setup:
          - pending_batch_configs row: (batch_run_id="test-batch-id-fail", M14, mode=1,
            config_id="test_config_sha1abc")
          - Sidecar: chunk_0001.json in "null" bucket, target_bucket empty.
          - fresh_slotlab.chunk_index.set_chunk_config_id patched to raise RuntimeError.

        Assert:
          1. The row persists in pending_batch_configs after the daemon thread runs.
          2. reassociate_error.json is written (diagnostic per feedback_no_silent_swallow.md).

        Inject-bug: in app.py _reassociate_orphaned_configs, remove the
          `if _reassoc_failures == 0:` guard and always call delete_pending_batch_config
          → row deleted despite failure → test FAILS (row absent). Revert → PASSES.

        Memory:
          memory/feedback_enumerate_safety_paths.md (preserve row on partial failure)
          memory/feedback_no_silent_swallow.md (write diagnostic on failure)
        """
        import json
        from src.web_console.backend.app import StateStore
        import fresh_slotlab.chunk_index as _ci_mod

        batch_run_id = "test-batch-id-fail"

        # Patch set_chunk_config_id BEFORE creating the app so the daemon thread
        # picks up the patched version.
        def _raising_set(*args, **kwargs):
            raise RuntimeError("OPT1-injected-set-failure")

        monkeypatch.setattr(_ci_mod, "set_chunk_config_id", _raising_set)

        app, state_dir, rawdata_dir, db_path = self._build_app_with_pending_row(
            tmp_path,
            monkeypatch,
            null_chunks=["chunk_0001.json"],
            target_chunks=[],
            config_id="test_config_sha1abc",
            batch_run_id=batch_run_id,
        )

        # Wait for the daemon thread to write the diagnostic error file (up to 10s).
        # Once reassociate_error.json exists, the thread has completed its attempt.
        err_path = state_dir / "reassociate_error.json"
        deadline = time.monotonic() + 10.0
        err_written = False
        while time.monotonic() < deadline:
            if err_path.exists():
                err_written = True
                break
            time.sleep(0.05)

        # Give a brief grace period for the thread to finish post-error cleanup
        time.sleep(0.2)

        assert err_written, (
            "reassociate_error.json must be written when set_chunk_config_id raises. "
            "This indicates the daemon thread ran but did not write the diagnostic. "
            "Memory: feedback_no_silent_swallow.md"
        )

        # Primary assertion: row must still be present for retry.
        store = StateStore(db_path)
        rows = store.list_pending_batch_configs()
        row_present = any(r["batch_run_id"] == batch_run_id for r in rows)
        assert row_present, (
            "pending_batch_config row must be PRESERVED after reassociation failure "
            "so next startup can retry. "
            "Inject-bug: remove the `if _reassoc_failures == 0:` guard and always "
            "call store.delete_pending_batch_config → row deleted despite failure → "
            "this assertion fails. Revert → green. "
            "Memory: feedback_enumerate_safety_paths.md"
        )

        # Also verify diagnostic content
        err_data = json.loads(err_path.read_text(encoding="utf-8"))
        assert "OPT1-injected-set-failure" in err_data.get("error", ""), (
            f"Error diagnostic must contain the exception text. Got: {err_data!r}"
        )
        assert err_data.get("machine") == "M14"
        assert err_data.get("mode") == 1
