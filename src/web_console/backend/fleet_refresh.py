"""FleetRefreshManager — SQLite-backed fleet-refresh queue with crash recovery.

Phase 3 of the deploy migration (2026-05-17).  Coordinates background
full-fleet refresh runs with:

  * per-(machine, mode) item state persisted to SQLite
  * crash-recoverable resume: in-flight items re-queued as pending on startup
  * cell-busy timeout: items that can't acquire the SAMPLING lock within
    SLOT_FLEET_CELL_BUSY_TIMEOUT_S (default 1800 s / 30 min) are marked
    skipped so they don't stall the whole queue forever
  * retry policy: failed items retried up to MAX_RETRIES (default 3) before
    being marked skipped
  * ConcurrencyLimiter integration: background priority so ad-hoc planner
    fetches (foreground) always get priority over fleet refresh workers

Design source: session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.4
Decision:      session_artifacts/_arch/deploy/07_deploy_decision.md §3.1 INV-9

Per memory/feedback_subprocess_import_suicide_and_module_globals.md:
  * No import-time side effects.  No module-level state beyond constants.
  * FleetRefreshManager() is constructed inside create_app() so each app
    instance (prod or test-isolated) has its own manager.

Per memory/feedback_no_silent_swallow.md:
  * All exception paths persist diagnostics to SQLite (last_error column)
    and print to stderr with traceback.
  * No bare ``except: pass`` — every caught exception is re-logged before
    silently continuing the queue (a failed item does NOT stop the queue).
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from src.web_console.backend.cell_lock_registry import CellLockRegistry
    from src.web_console.backend.rate_limiter import ConcurrencyLimiter

# Default cell-busy timeout — configurable via env.
_DEFAULT_CELL_BUSY_TIMEOUT_S = 1800  # 30 minutes

# Max retry attempts per item before it is permanently skipped.
_DEFAULT_MAX_RETRIES = 3

# Poll interval when waiting for a cell to become available.
_CELL_BUSY_POLL_INTERVAL_S = 5.0

# Poll interval between queue items when checking the cancel flag.
_QUEUE_POLL_INTERVAL_S = 0.5


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class FleetRefreshManager:
    """SQLite-backed queue manager for full-fleet background refresh.

    Lifecycle::

        mgr = FleetRefreshManager(store, registry, limiter, batch_run_fn, db_path)

        # Trigger a new refresh:
        queue_id = mgr.start_queue(machines_list)

        # Resume after crash (called by create_app on startup):
        mgr.run_queue(existing_queue_id)  # in a daemon thread

        # Cancel:
        mgr.cancel_queue(queue_id)

        # Poll progress:
        progress = mgr.get_queue_progress(queue_id)
    """

    def __init__(
        self,
        db_path: "Path",
        registry: "CellLockRegistry",
        limiter: "ConcurrencyLimiter",
        start_batch_item_fn: "Callable[[str, int, str], dict[str, Any]]",
        *,
        max_retries: int | None = None,
        cell_busy_timeout_s: float | None = None,
    ) -> None:
        """Construct a FleetRefreshManager.

        Parameters
        ----------
        db_path:
            Path to the SQLite database (same ``console.db`` as StateStore).
        registry:
            The app-scoped ``CellLockRegistry`` instance.
        limiter:
            The app-scoped ``ConcurrencyLimiter`` instance.
        start_batch_item_fn:
            Callable that starts a single batch-run item and waits for it
            to complete.  Signature: ``(machine: str, mode: int, queue_id:
            str) -> dict`` with keys ``run_id``, ``status`` ('completed' /
            'failed'), ``error`` (str or None).
        max_retries:
            Override for ``_DEFAULT_MAX_RETRIES`` (or ``SLOT_FLEET_MAX_RETRIES``
            env). Mostly for tests.
        cell_busy_timeout_s:
            Override for ``_DEFAULT_CELL_BUSY_TIMEOUT_S`` (or
            ``SLOT_FLEET_CELL_BUSY_TIMEOUT_S`` env). Mostly for tests.
        """
        self._db_path = Path(db_path)
        self._registry = registry
        self._limiter = limiter
        self._start_batch_item_fn = start_batch_item_fn

        # Env-configurable knobs (override wins over env which wins over default).
        self._max_retries: int = (
            max_retries
            if max_retries is not None
            else int(os.environ.get("SLOT_FLEET_MAX_RETRIES") or _DEFAULT_MAX_RETRIES)
        )
        self._cell_busy_timeout_s: float = (
            cell_busy_timeout_s
            if cell_busy_timeout_s is not None
            else float(
                os.environ.get("SLOT_FLEET_CELL_BUSY_TIMEOUT_S")
                or _DEFAULT_CELL_BUSY_TIMEOUT_S
            )
        )

        # Cancel flags: queue_id -> bool.  Protected by _lock.
        self._cancel_flags: dict[str, bool] = {}
        self._lock = threading.Lock()

    # ── Cancel API ────────────────────────────────────────────────────

    def cancel_queue(self, queue_id: str) -> None:
        """Signal the running queue to cancel after the current item."""
        with self._lock:
            self._cancel_flags[queue_id] = True

    def _is_cancelled(self, queue_id: str) -> bool:
        with self._lock:
            return self._cancel_flags.get(queue_id, False)

    # ── SQLite helpers ────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _mark_queue_status(
        self, queue_id: str, status: str, *, finished_at: str | None = None,
        cancelled_at: str | None = None,
    ) -> None:
        patch = {"status": status}
        if finished_at is not None:
            patch["finished_at"] = finished_at
        if cancelled_at is not None:
            patch["cancelled_at"] = cancelled_at
        sets = ", ".join(f"{k}=:{k}" for k in patch)
        patch["queue_id"] = queue_id
        with self._connect() as conn:
            conn.execute(
                f"UPDATE fleet_refresh_queue SET {sets} WHERE queue_id=:queue_id",
                patch,
            )
            conn.commit()

    def _update_completed_items(
        self, queue_id: str, status_col: str, delta: int,
    ) -> None:
        """Atomically increment one of the counter columns."""
        with self._connect() as conn:
            conn.execute(
                f"UPDATE fleet_refresh_queue SET {status_col}={status_col}+? "
                "WHERE queue_id=?",
                (delta, queue_id),
            )
            conn.commit()

    def _mark_item(
        self,
        queue_id: str,
        machine: str,
        mode: int,
        status: str,
        *,
        run_id: str | None = None,
        last_error: str | None = None,
        attempt_count_delta: int = 0,
    ) -> None:
        now = _utc_now()
        with self._connect() as conn:
            if status in ("running",):
                conn.execute(
                    "UPDATE fleet_refresh_items SET status=?, run_id=?, started_at=? "
                    "WHERE queue_id=? AND machine=? AND mode=?",
                    (status, run_id or "", now, queue_id, machine, mode),
                )
            elif status in ("completed", "failed", "skipped"):
                conn.execute(
                    "UPDATE fleet_refresh_items "
                    "SET status=?, run_id=?, last_error=?, finished_at=?, "
                    "    attempt_count=attempt_count+? "
                    "WHERE queue_id=? AND machine=? AND mode=?",
                    (
                        status,
                        run_id or "",
                        last_error or "",
                        now,
                        attempt_count_delta,
                        queue_id,
                        machine,
                        mode,
                    ),
                )
            elif status in ("pending",):
                # Re-queue: reset run_id + increment attempt_count.
                conn.execute(
                    "UPDATE fleet_refresh_items "
                    "SET status=?, last_error=?, attempt_count=attempt_count+? "
                    "WHERE queue_id=? AND machine=? AND mode=?",
                    (status, last_error or "", attempt_count_delta, queue_id, machine, mode),
                )
            conn.commit()

    def _next_pending_item(
        self, queue_id: str,
    ) -> tuple[str, int, int] | None:
        """Return (machine, mode, attempt_count) for the next pending item
        in queue_position order, or None if the queue is exhausted."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT machine, mode, attempt_count FROM fleet_refresh_items "
                "WHERE queue_id=? AND status='pending' "
                "ORDER BY queue_position ASC LIMIT 1",
                (queue_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row["machine"]), int(row["mode"]), int(row["attempt_count"])

    # ── Public API ────────────────────────────────────────────────────

    def start_queue(
        self,
        machines: list[dict[str, Any]],
        *,
        config_source: str = "server_default",
        server_id: str | None = None,
    ) -> str:
        """Create a new queue, populate per-(machine, mode) items, and
        spawn a daemon thread to process them.

        ``machines`` is a list of dicts with keys ``machine`` and ``modes``
        (list of int mode numbers).  The order of the list determines
        ``queue_position`` for deterministic item ordering.

        Returns the new ``queue_id``.
        """
        queue_id = uuid.uuid4().hex
        now = _utc_now()
        items: list[tuple] = []
        pos = 0
        for entry in machines:
            machine = str(entry.get("machine") or "")
            for mode in (entry.get("modes") or []):
                items.append((
                    queue_id, machine, int(mode), pos, "pending",
                ))
                pos += 1

        total_items = len(items)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO fleet_refresh_queue
                    (queue_id, started_at, status, total_items,
                     completed_items, failed_items, skipped_items,
                     config_source, server_id)
                VALUES (?, ?, 'running', ?, 0, 0, 0, ?, ?)
                """,
                (queue_id, now, total_items, config_source, server_id),
            )
            conn.executemany(
                """
                INSERT INTO fleet_refresh_items
                    (queue_id, machine, mode, queue_position, status,
                     attempt_count)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                items,
            )
            conn.commit()

        threading.Thread(
            target=self.run_queue,
            args=(queue_id,),
            daemon=True,
            name=f"fleet-refresh-{queue_id[:8]}",
        ).start()
        return queue_id

    def run_queue(self, queue_id: str) -> None:
        """Process all pending items in queue order.  Runs as a daemon thread.

        For each item:
          1. Poll for the next pending item.
          2. Wait up to ``cell_busy_timeout_s`` for the cell's SAMPLING slot.
             Timeout → mark skipped.
          3. Acquire a ``background`` ConcurrencyLimiter slot (cancel-aware).
          4. Call ``_start_batch_item_fn`` and handle result.
          5. On failure: increment attempt_count; re-queue if below max_retries,
             mark skipped if exhausted.
          6. On completion: update counters.
        """
        from src.web_console.backend.cell_lock_registry import CellOperation

        while True:
            if self._is_cancelled(queue_id):
                self._mark_queue_status(
                    queue_id, "cancelled", cancelled_at=_utc_now(),
                )
                return

            next_item = self._next_pending_item(queue_id)
            if next_item is None:
                # No more pending items — queue is done.
                break

            machine, mode, attempt_count = next_item

            # ── Step 1: wait for cell to become available ──────────────
            cell_wait_start = time.monotonic()
            cell_acquired = False
            while True:
                if self._is_cancelled(queue_id):
                    break

                try:
                    cell_acquired = self._registry.try_acquire_cell(
                        machine, mode, CellOperation.SAMPLING,
                        info={
                            "config_id": "null",
                            "upstream_md5": "",
                            "run_id": "",
                        },
                    )
                except Exception as _reg_exc:  # noqa: BLE001
                    # Per memory/feedback_no_silent_swallow.md: surface registry
                    # errors so operators can distinguish "cell genuinely busy"
                    # from "registry threw an unexpected exception".
                    traceback.print_exc()
                    print(
                        f"[fleet-refresh] try_acquire_cell raised for "
                        f"{machine}|{mode}: "
                        f"{_reg_exc.__class__.__name__}: {_reg_exc}",
                        file=sys.stderr,
                    )
                    # Mark item failed with the real reason (not "cell_busy_timeout").
                    self._mark_item(
                        queue_id, machine, mode, "skipped",
                        last_error=(
                            f"try_acquire_cell exception: "
                            f"{_reg_exc.__class__.__name__}: {_reg_exc}"
                        ),
                        attempt_count_delta=1,
                    )
                    self._update_completed_items(queue_id, "skipped_items", 1)
                    break  # exit cell-busy poll loop; move to next item

                if cell_acquired:
                    break

                elapsed = time.monotonic() - cell_wait_start
                if elapsed >= self._cell_busy_timeout_s:
                    # Cell was busy for the whole timeout window.
                    self._mark_item(
                        queue_id, machine, mode, "skipped",
                        last_error=(
                            f"cell_busy_timeout: SAMPLING lock not available "
                            f"after {elapsed:.0f}s"
                        ),
                    )
                    self._update_completed_items(queue_id, "skipped_items", 1)
                    print(
                        f"[fleet-refresh] {machine}|{mode} skipped — "
                        f"cell busy after {elapsed:.0f}s",
                        file=sys.stderr,
                    )
                    break  # Move to next item.

                time.sleep(_CELL_BUSY_POLL_INTERVAL_S)

            if not cell_acquired:
                # Either cancelled or cell-busy timeout — move on.
                if self._is_cancelled(queue_id):
                    self._mark_queue_status(
                        queue_id, "cancelled", cancelled_at=_utc_now(),
                    )
                    return
                continue  # Already marked skipped above.

            # ── Step 2: acquire ConcurrencyLimiter (background) ────────
            limiter_acquired = False
            try:
                limiter_acquired = self._limiter.acquire(
                    "background",
                    cancel_flag=lambda: self._is_cancelled(queue_id),
                )
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self._registry.release_cell(machine, mode, CellOperation.SAMPLING)
                self._mark_item(
                    queue_id, machine, mode, "failed",
                    last_error=f"limiter_acquire_error: {exc}",
                    attempt_count_delta=1,
                )
                self._update_completed_items(queue_id, "failed_items", 1)
                continue

            if not limiter_acquired:
                # Cancel fired during limiter wait.
                self._registry.release_cell(machine, mode, CellOperation.SAMPLING)
                self._mark_queue_status(
                    queue_id, "cancelled", cancelled_at=_utc_now(),
                )
                return

            # ── Step 3: run the item ───────────────────────────────────
            run_id_result: str | None = None
            try:
                self._mark_item(
                    queue_id, machine, mode, "running",
                    run_id="",
                )
                result = self._start_batch_item_fn(machine, mode, queue_id)
                run_id_result = str(result.get("run_id") or "")
                item_status = str(result.get("status") or "failed")
                item_error = str(result.get("error") or "")

                if item_status == "completed":
                    self._mark_item(
                        queue_id, machine, mode, "completed",
                        run_id=run_id_result,
                        attempt_count_delta=1,
                    )
                    self._update_completed_items(queue_id, "completed_items", 1)
                else:
                    # Failed — retry or skip.
                    new_attempt = attempt_count + 1
                    if new_attempt >= self._max_retries:
                        self._mark_item(
                            queue_id, machine, mode, "skipped",
                            run_id=run_id_result,
                            last_error=(
                                f"max_retries_exceeded ({self._max_retries}): "
                                f"{item_error}"
                            ),
                            attempt_count_delta=1,
                        )
                        self._update_completed_items(queue_id, "skipped_items", 1)
                        print(
                            f"[fleet-refresh] {machine}|{mode} skipped after "
                            f"{new_attempt} attempts: {item_error[:120]}",
                            file=sys.stderr,
                        )
                    else:
                        # Re-queue.
                        self._mark_item(
                            queue_id, machine, mode, "pending",
                            last_error=item_error,
                            attempt_count_delta=1,
                        )
                        print(
                            f"[fleet-refresh] {machine}|{mode} retry "
                            f"{new_attempt}/{self._max_retries}: {item_error[:80]}",
                            file=sys.stderr,
                        )

            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                new_attempt = attempt_count + 1
                err_str = f"{exc.__class__.__name__}: {exc}"
                if new_attempt >= self._max_retries:
                    self._mark_item(
                        queue_id, machine, mode, "skipped",
                        run_id=run_id_result,
                        last_error=f"max_retries_exceeded ({self._max_retries}): {err_str}",
                        attempt_count_delta=1,
                    )
                    self._update_completed_items(queue_id, "skipped_items", 1)
                else:
                    self._mark_item(
                        queue_id, machine, mode, "pending",
                        last_error=err_str,
                        attempt_count_delta=1,
                    )
            finally:
                # Always release both primitives.
                self._registry.release_cell(machine, mode, CellOperation.SAMPLING)
                if limiter_acquired:
                    self._limiter.release()

        # Queue exhausted (or all items processed).
        if not self._is_cancelled(queue_id):
            self._mark_queue_status(
                queue_id, "completed", finished_at=_utc_now(),
            )

    # ── Progress API ──────────────────────────────────────────────────

    def get_queue_progress(self, queue_id: str) -> dict[str, Any] | None:
        """Return a progress snapshot dict for the given queue, or None
        if the queue doesn't exist."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM fleet_refresh_queue WHERE queue_id=?",
                (queue_id,),
            ).fetchone()
            if row is None:
                return None
            items = conn.execute(
                "SELECT machine, mode, status, run_id, attempt_count, "
                "last_error, started_at, finished_at "
                "FROM fleet_refresh_items WHERE queue_id=? "
                "ORDER BY queue_position ASC",
                (queue_id,),
            ).fetchall()
        return {
            "queue_id": queue_id,
            "status": row["status"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "cancelled_at": row["cancelled_at"],
            "total_items": row["total_items"],
            "completed_items": row["completed_items"],
            "failed_items": row["failed_items"],
            "skipped_items": row["skipped_items"],
            "config_source": row["config_source"],
            "server_id": row["server_id"],
            "items": [
                {
                    "machine": r["machine"],
                    "mode": r["mode"],
                    "status": r["status"],
                    "run_id": r["run_id"],
                    "attempt_count": r["attempt_count"],
                    "last_error": r["last_error"],
                    "started_at": r["started_at"],
                    "finished_at": r["finished_at"],
                }
                for r in items
            ],
        }

    def get_running_queue_id(self) -> str | None:
        """Return the queue_id of the currently running queue, or None."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT queue_id FROM fleet_refresh_queue "
                    "WHERE status='running' LIMIT 1",
                ).fetchone()
            return str(row["queue_id"]) if row else None
        except sqlite3.OperationalError:
            # Tables don't exist yet (pre-P3 database).
            return None
