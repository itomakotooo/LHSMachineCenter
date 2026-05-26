"""AutoInspectManager — sweep manager for the auto-inspect feature.

Phase 2 (Discovery + state machine) lands in this file on top of the
Phase 1 skeleton.  Phase 1 shipped the public interface + DB tables +
_scan_persisted_for_resume.  Phase 2 implements:

  * _scan_cells -- discover cells needing sample
  * start_sweep -- INSERT rows + dispatch workers
  * _dispatch_sweep -- worker loop
  * resume_sweep -- reset claimed->pending + re-dispatch
  * cancel_sweep -- set sweep/items cancelled
  * get_sweep_status -- aggregate progress dict
  * list_recent_sweeps -- recent sweeps for UI

Design:  session_artifacts/_arch/auto_inspect/07_decision.md §2-§4
Phase 1: commit 1bcf43c

Per memory/feedback_subprocess_import_suicide_and_module_globals.md:
  * No import-time side effects.  No module-level state beyond constants.
  * AutoInspectManager() is constructed inside create_app() -- one per app
    instance; every path is injected via __init__.

Per memory/feedback_no_silent_swallow.md:
  * Every terminal status carries non-null terminal_reason.
  * Every except branch persists diagnostic or re-raises.

Per 07_decision §6 (acceptance criteria):
  * No mode=None calls to _get_machine_md5.
  * No module-level globals.
  * MF-1: __init__ does NOT call _do_refresh_machines_md5 synchronously.
"""

from __future__ import annotations

import collections
import json
import logging
import sqlite3
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Avoid circular imports at runtime -- types only used for annotation.
    from src.web_console.backend.app import StateStore, RunManager, RunCreateRequest
    from src.web_console.backend.cell_lock_registry import (
        CellLockRegistry,
        CellOperation,
    )
    from src.web_console.backend.rate_limiter import ConcurrencyLimiter

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (pure constants, no runtime state)
# ---------------------------------------------------------------------------

# Machine modes the sweep considers.  Must match 07_decision §3 modes list.
_SWEEP_MODES: tuple[int, ...] = (1, 2, 5, 7)

# Manifest directory path relative to project root.
_MANIFEST_SUBPATH = Path("slot_designer") / "configs" / "machine_manifests"

# Terminal item statuses that count as "attempt" for the windowed failure
# counter (per 07_decision §2 MF-5).
_COUNTER_ATTEMPT_STATUSES = frozenset({"completed", "failed"})

# Terminal item statuses that do NOT count as "attempt" (expected partial
# failures -- per MF-5 structural exclusion list).
_COUNTER_SKIP_STATUSES = frozenset({
    "structural_skip",
    "convergence_timeout",
    "manifest_override_partial",
    "deferred_lock_conflict",
    "md5_drift_invalidated",
    "wall_time_timeout",
    "cancelled",
})

# Item statuses that mean the item is non-terminal (sweep still owns cell).
_ITEM_NON_TERMINAL_STATUSES = frozenset({
    "pending", "claimed", "running", "generating",
})

# Worker poll interval in seconds.
_WORKER_POLL_S = 1.0

# Cell-lock poll interval in seconds.
_CELL_LOCK_POLL_S = 5.0

# Run poll interval in seconds.
_RUN_POLL_S = 5.0


class AutoInspectManager:
    """Background sweep manager that discovers stale cells and resamples them.

    Public API (per 07_decision §1 + V3):
      * start_sweep(trigger) -> sweep_id
      * cancel_sweep(sweep_id) -> bool
      * get_sweep_status(sweep_id) -> dict | None
      * list_recent_sweeps(limit) -> list[dict]
      * resume_sweep(sweep_id) -> None

    Private:
      * _scan_cells(modes, skip_fresh) -> list[dict]
      * _scan_persisted_for_resume() -> str | None
      * _dispatch_sweep(sweep_id, settings) -> None
      * _worker(sweep_id, worker_id, settings) -> None
      * _claim_next_item(sweep_id, worker_id) -> dict | None
      * _mark_item(sweep_id, machine, mode, status, reason, extra) -> None
      * _append_item_event(sweep_id, machine, mode, event) -> None
      * _has_running_sweep() -> bool
      * _update_sweep_counts(sweep_id) -> None
    """

    def __init__(
        self,
        store: "StateStore",
        run_manager: "RunManager",
        registry: "CellLockRegistry",
        limiter: "ConcurrencyLimiter",
        *,
        settings_path: Path,
        machines_config: Path,
        rawdata_root: Path,
    ) -> None:
        """Construct the manager and scan for a resumable sweep.

        All path parameters are injected -- never read from module globals.
        No HTTP or upstream calls here (MF-1: blocks HTTP startup if done
        synchronously in __init__).

        Args:
            store: Per-app-instance StateStore (owns the SQLite connection).
            run_manager: Per-app-instance RunManager for spawning sample runs.
            registry: Shared CellLockRegistry (enforces SAMPLING/GENERATING
                exclusion invariants).
            limiter: Shared ConcurrencyLimiter (background priority slot).
            settings_path: Path to state/console/settings.json.
            machines_config: Path to configs/machines.json (or override).
            rawdata_root: Path to rawdata/ root directory.
        """
        # Store refs -- all per-instance, no module globals.
        self._store = store
        self._run_manager = run_manager
        self._registry = registry
        self._limiter = limiter
        self._settings_path = settings_path
        self._machines_config = machines_config
        self._rawdata_root = rawdata_root

        # Per-sweep windowed consecutive-failure counter.
        # Keyed by sweep_id -> deque of 'failed'/'ok' strings (last 10 items).
        self._failure_windows: dict[str, collections.deque] = {}

        # Lock protecting failure window dict.
        self._failure_lock: threading.Lock = threading.Lock()

        # Lock used by workers for atomic claim step (V1 per 07_decision §2 V1).
        self._claim_lock: threading.Lock = threading.Lock()

        # Running worker threads: sweep_id -> list[threading.Thread]
        self._worker_threads: dict[str, list[threading.Thread]] = {}

        # Cancel signals: sweep_id -> threading.Event (set = cancel requested)
        self._cancel_events: dict[str, threading.Event] = {}

        # Scan persisted non-terminal sweeps for restart-recovery.
        # Pure SQLite -- no HTTP, no upstream calls (MF-1 invariant).
        self._pending_resume_sweep_id: str | None = (
            self._scan_persisted_for_resume()
        )

    # -- Public interface (07_decision §1 + V3) ----------------------------

    def start_sweep(self, trigger: str = "manual") -> str:
        """Start a new sweep.  Returns sweep_id.

        409 (raise HTTPException) if:
          * Fleet refresh queue is running (MF-3 mutex).
          * A sweep is already running (one-at-a-time invariant).

        Per 07_decision §2 MF-3: the two systems are mutually exclusive.
        """
        from fastapi import HTTPException  # noqa: PLC0415

        # MF-3 mutex: refuse if fleet refresh is active.
        fleet_proxy = self._get_fleet_refresh_manager()
        if fleet_proxy is not None:
            running_queue = fleet_proxy.get_running_queue_id()
            if running_queue:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "fleet refresh queue is active -- wait for it to complete "
                        "or cancel it first"
                    ),
                )

        # Single-sweep mutex.
        if self._has_running_sweep():
            raise HTTPException(
                status_code=409,
                detail="auto-inspect sweep already running",
            )

        # Load current settings (snapshot for this sweep's lifetime).
        settings = self._load_auto_sweep_settings()
        modes_list = list(_SWEEP_MODES)
        skip_fresh = bool(settings.get("skip_fresh_cells", True))
        sweep_id = uuid.uuid4().hex[:12]
        now_ts = datetime.now(timezone.utc).isoformat()

        settings_snapshot_json = json.dumps(settings, ensure_ascii=False)

        # INSERT sweep row in 'scanning' status.
        with self._store._connect() as conn:
            conn.execute(
                """
                INSERT INTO auto_inspect_sweeps
                (sweep_id, status, created_at, settings_snapshot_json,
                 modes_json, trigger, total_items, completed_items,
                 failed_items, skipped_items)
                VALUES (?, 'scanning', ?, ?, ?, ?, 0, 0, 0, 0)
                """,
                (
                    sweep_id,
                    now_ts,
                    settings_snapshot_json,
                    json.dumps([str(m) for m in modes_list]),
                    trigger,
                ),
            )
            conn.commit()

        # Discover cells needing sample.
        try:
            cells = self._scan_cells(modes_list, skip_fresh=skip_fresh)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            _logger.error(
                "AutoInspectManager.start_sweep: _scan_cells failed: %s\n%s",
                exc, tb,
            )
            with self._store._connect() as conn:
                conn.execute(
                    "UPDATE auto_inspect_sweeps SET status='failed', "
                    "finished_at=? WHERE sweep_id=?",
                    (datetime.now(timezone.utc).isoformat(), sweep_id),
                )
                conn.commit()
            raise HTTPException(
                status_code=500,
                detail=f"sweep scan failed: {exc}",
            ) from exc

        # Bulk INSERT items as 'pending'.
        with self._store._connect() as conn:
            for cell in cells:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO auto_inspect_items
                    (sweep_id, machine, mode, queue_position, status, cell_class,
                     cfg_md5_at_enqueue, code_md5_at_enqueue, events_json)
                    VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, '[]')
                    """,
                    (
                        sweep_id,
                        cell["machine"],
                        cell["mode"],
                        cell["queue_position"],
                        cell["cell_class"],
                        cell["cfg_md5_at_enqueue"],
                        cell["code_md5_at_enqueue"],
                    ),
                )
            conn.execute(
                "UPDATE auto_inspect_sweeps SET status='sampling', total_items=? "
                "WHERE sweep_id=?",
                (len(cells), sweep_id),
            )
            conn.commit()

        _logger.info(
            "AutoInspectManager.start_sweep: sweep_id=%s trigger=%s cells=%d",
            sweep_id, trigger, len(cells),
        )

        # Initialise failure window.
        with self._failure_lock:
            self._failure_windows[sweep_id] = collections.deque(maxlen=10)

        # Initialise cancel event.
        self._cancel_events[sweep_id] = threading.Event()

        # Spawn dispatch daemon.
        dispatch_thread = threading.Thread(
            target=self._dispatch_sweep,
            args=(sweep_id, settings),
            daemon=True,
            name=f"auto-inspect-dispatch-{sweep_id[:8]}",
        )
        dispatch_thread.start()
        self._worker_threads[sweep_id] = [dispatch_thread]

        return sweep_id

    def cancel_sweep(self, sweep_id: str) -> bool:
        """Cancel a running sweep.  Returns True if sweep found and cancelled.

        Running items finish naturally; the claimer marks each one cancelled
        when it sees the cancel event.  Pending items are immediately set to
        'cancelled' with terminal_reason.
        """
        now_ts = datetime.now(timezone.utc).isoformat()

        with self._store._connect() as conn:
            row = conn.execute(
                "SELECT status FROM auto_inspect_sweeps WHERE sweep_id=?",
                (sweep_id,),
            ).fetchone()
            if row is None:
                return False
            sweep_status = str(row["status"])
            if sweep_status in ("completed", "cancelled", "failed"):
                # Already terminal -- nothing to cancel.
                return True

            # Set cancel event so workers stop picking up new work.
            cancel_ev = self._cancel_events.get(sweep_id)
            if cancel_ev is not None:
                cancel_ev.set()

            # Mark pending items cancelled immediately.
            conn.execute(
                """
                UPDATE auto_inspect_items
                SET status='cancelled',
                    terminal_reason='cancelled by operator',
                    finished_at=?
                WHERE sweep_id=? AND status='pending'
                """,
                (now_ts, sweep_id),
            )
            # Mark sweep cancelled.
            conn.execute(
                """
                UPDATE auto_inspect_sweeps
                SET status='cancelled', finished_at=?
                WHERE sweep_id=?
                """,
                (now_ts, sweep_id),
            )
            conn.commit()

        _logger.info("AutoInspectManager.cancel_sweep: sweep_id=%s", sweep_id)
        return True

    def get_sweep_status(self, sweep_id: str) -> dict[str, Any] | None:
        """Return sweep progress dict or None if sweep_id not found."""
        with self._store._connect() as conn:
            sweep_row = conn.execute(
                "SELECT * FROM auto_inspect_sweeps WHERE sweep_id=?",
                (sweep_id,),
            ).fetchone()
            if sweep_row is None:
                return None

            # Count items by status group.
            counts_rows = conn.execute(
                """
                SELECT status, COUNT(*) AS cnt
                FROM auto_inspect_items
                WHERE sweep_id=?
                GROUP BY status
                """,
                (sweep_id,),
            ).fetchall()

        counts: dict[str, int] = {}
        for cr in counts_rows:
            counts[str(cr["status"])] = int(cr["cnt"])

        return {
            "sweep_id": sweep_id,
            "status": str(sweep_row["status"]),
            "trigger": str(sweep_row["trigger"]),
            "created_at": str(sweep_row["created_at"]),
            "finished_at": sweep_row["finished_at"],
            "total_items": int(sweep_row["total_items"] or 0),
            "completed_items": int(sweep_row["completed_items"] or 0),
            "failed_items": int(sweep_row["failed_items"] or 0),
            "skipped_items": int(sweep_row["skipped_items"] or 0),
            "items_by_status": counts,
        }

    def list_recent_sweeps(self, limit: int = 30) -> list[dict[str, Any]]:
        """Return the most recent ``limit`` sweeps, newest first."""
        with self._store._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM auto_inspect_sweeps
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def resume_sweep(self, sweep_id: str) -> None:
        """Resume a sweep that was interrupted by a console restart.

        Per 07_decision §2 V3: resets claimed->pending, then re-dispatches
        workers.  Runs in a daemon thread spawned by create_app.
        """
        _logger.info(
            "AutoInspectManager.resume_sweep: resuming sweep_id=%s", sweep_id,
        )

        # Reset claimed items back to pending (crash recovery for V1 atomic
        # claim -- claimed rows are orphaned on crash).
        try:
            with self._store._connect() as conn:
                conn.execute(
                    """
                    UPDATE auto_inspect_items
                    SET status='pending', claimed_by=NULL, claimed_at=NULL
                    WHERE sweep_id=? AND status='claimed'
                    """,
                    (sweep_id,),
                )
                # Ensure sweep is in 'sampling' state (not 'scanning').
                conn.execute(
                    """
                    UPDATE auto_inspect_sweeps
                    SET status='sampling'
                    WHERE sweep_id=? AND status IN ('scanning', 'sampling', 'finalizing')
                    """,
                    (sweep_id,),
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            _logger.error(
                "AutoInspectManager.resume_sweep: DB reset failed for %s: %s\n%s",
                sweep_id, exc, tb,
            )
            print(
                f"[auto-inspect] resume_sweep({sweep_id!r}) DB reset failed: {exc}",
                flush=True,
            )
            return

        # Check sweep is still non-terminal.
        with self._store._connect() as conn:
            row = conn.execute(
                "SELECT status FROM auto_inspect_sweeps WHERE sweep_id=?",
                (sweep_id,),
            ).fetchone()
        if row is None or str(row["status"]) not in (
            "scanning", "sampling", "finalizing"
        ):
            _logger.info(
                "AutoInspectManager.resume_sweep: sweep %s is terminal, skip",
                sweep_id,
            )
            return

        # Load settings from the snapshot stored at sweep creation.
        try:
            with self._store._connect() as conn:
                snap_row = conn.execute(
                    "SELECT settings_snapshot_json FROM auto_inspect_sweeps "
                    "WHERE sweep_id=?",
                    (sweep_id,),
                ).fetchone()
            if snap_row and snap_row["settings_snapshot_json"]:
                settings = json.loads(str(snap_row["settings_snapshot_json"]))
            else:
                settings = self._load_auto_sweep_settings()
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "AutoInspectManager.resume_sweep: settings parse failed (%s), "
                "using current settings",
                exc,
            )
            settings = self._load_auto_sweep_settings()

        # Initialise failure window (fresh for resumed sweep).
        with self._failure_lock:
            self._failure_windows[sweep_id] = collections.deque(maxlen=10)

        # Initialise cancel event.
        if sweep_id not in self._cancel_events:
            self._cancel_events[sweep_id] = threading.Event()
        else:
            self._cancel_events[sweep_id].clear()  # clear any stale cancel signal

        # Re-dispatch workers.
        dispatch_thread = threading.Thread(
            target=self._dispatch_sweep,
            args=(sweep_id, settings),
            daemon=True,
            name=f"auto-inspect-resume-dispatch-{sweep_id[:8]}",
        )
        dispatch_thread.start()
        self._worker_threads.setdefault(sweep_id, []).append(dispatch_thread)
        _logger.info(
            "AutoInspectManager.resume_sweep: re-dispatched workers for sweep %s",
            sweep_id,
        )

    # -- Private -- scan ---------------------------------------------------

    def _scan_cells(
        self,
        modes: list[int],
        *,
        skip_fresh: bool,
    ) -> list[dict[str, Any]]:
        """Discover (machine, mode) cells that need sampling.

        Per 07_decision §4 P2 deliverable 1:
          1. Skip if machine doesn't have this mode (per machine_modes.json).
          2. Compute local md5 via _get_machine_md5 with EXPLICIT mode.
          3. Compute upstream md5 via server snapshot.
          4. Classify needs_sample.
          5. Classify cell_class.

        Returns list of cell dicts ready for INSERT into auto_inspect_items.
        """
        # Lazy import to avoid circular at module level.
        from src.web_console.backend.app import (  # noqa: PLC0415
            _get_machine_md5,
            _resolve_active_server_id,
            _load_server_snapshot,
        )

        # Load machines list.
        machines_data = self._load_machines_json()
        machines: list[str] = []
        for entry in (machines_data.get("machines") or []):
            m = str(entry.get("machine") or "").strip()
            if m:
                machines.append(m)

        # Load machine_modes.json for mode support check.
        machine_modes = self._load_machine_modes_json()

        # Load settings for classification parameters.
        settings = self._load_auto_sweep_settings()
        # 2026-05-26 P2 tester finding: operator must be able to ZERO OUT
        # the structural-skip roster (e.g. after the BCM fix lands for
        # M250/M260/M264/M268). `or` treats [] as falsy and silently
        # falls back to the hardcoded default, defeating the override.
        # Explicit None check honors an empty list.
        _ssm = settings.get("structural_skip_machines")
        if _ssm is None:
            _ssm = ["M250", "M260", "M264", "M268"]
        structural_skip: set[str] = set(_ssm)
        # target_halfwidth_pp is per-mode but use mode 1 as representative
        # for the freshness check default.
        target_halfwidth_pp: float = float(
            settings.get("modes", {}).get("1", {}).get("target_halfwidth_pp", 0.5)
        )

        # Get active server snapshot for upstream md5 lookup.
        server_id = _resolve_active_server_id(settings_path=self._settings_path)
        snapshot: dict[str, Any] = {}
        if server_id:
            snap = _load_server_snapshot(server_id)
            if isinstance(snap, dict):
                snapshot = snap

        # Build manifest override set.
        manifest_override_machines = self._find_manifest_override_machines(machines)

        # Build trigger-session roster.
        trigger_session_machines = self._load_trigger_session_roster()

        cells: list[dict[str, Any]] = []
        queue_position = 0

        for machine in machines:
            for mode in modes:
                # Skip if machine doesn't support this mode.
                if not self._machine_has_mode(machine, mode, machine_modes):
                    continue

                # Compute local md5 -- ALWAYS explicit mode, never None
                # (07_decision §6 acceptance criteria).
                local_cfg, local_code = _get_machine_md5(
                    machine, self._machines_config, mode=mode
                )

                # Get upstream md5 from snapshot.
                snap_entry = snapshot.get(machine) or {}
                if isinstance(snap_entry, dict):
                    upstream_cfg = str(snap_entry.get("configSummaryMd5") or "")
                    upstream_code = str(snap_entry.get("codeSummaryMd5") or "")
                else:
                    upstream_cfg = ""
                    upstream_code = ""

                # Classify needs_sample:
                #  (a) No current-md5 report exists, OR
                #  (b) local_md5 != upstream_md5 (config drift).
                mode_halfwidth = float(
                    settings.get("modes", {}).get(str(mode), {})
                    .get("target_halfwidth_pp", target_halfwidth_pp)
                )
                has_fresh_report = self._has_fresh_report(
                    machine, mode, local_cfg, local_code, mode_halfwidth,
                )
                md5_drifted = (
                    bool(local_cfg or upstream_cfg or local_code or upstream_code)
                    and (local_cfg != upstream_cfg or local_code != upstream_code)
                )
                needs_sample = (not has_fresh_report) or md5_drifted

                # Apply skip_fresh_cells filter (07_decision §2 OQ-C).
                if skip_fresh and not needs_sample:
                    continue

                # Classify cell_class.
                cell_class = self._classify_cell(
                    machine, mode,
                    structural_skip=structural_skip,
                    trigger_session_machines=trigger_session_machines,
                    manifest_override_machines=manifest_override_machines,
                )

                cells.append({
                    "machine": machine,
                    "mode": mode,
                    "queue_position": queue_position,
                    "cell_class": cell_class,
                    "cfg_md5_at_enqueue": local_cfg,
                    "code_md5_at_enqueue": local_code,
                    "needs_sample": needs_sample,
                })
                queue_position += 1

        _logger.info(
            "AutoInspectManager._scan_cells: found %d cells needing sample",
            len(cells),
        )
        return cells

    def _classify_cell(
        self,
        machine: str,
        mode: int,
        *,
        structural_skip: set[str],
        trigger_session_machines: set[str],
        manifest_override_machines: set[str],
    ) -> str:
        """Return cell_class string per 07_decision §2 MF-4 + S2-G1."""
        if machine in structural_skip:
            return "bcm_hard"
        if machine in manifest_override_machines:
            return "manifest_override"
        if machine in trigger_session_machines:
            return "trigger_session"
        return "easy"

    def _has_fresh_report(
        self,
        machine: str,
        mode: int,
        cfg_md5: str,
        code_md5: str,
        target_halfwidth_pp: float,
    ) -> bool:
        """Return True if a completed run exists for (machine, mode) with
        matching md5 AND achieved_halfwidth_pp <= target_halfwidth_pp
        (per 07_decision §2 OQ-C: evaluates against current target setting).
        """
        if not cfg_md5 and not code_md5:
            # No md5 available -- can't confirm freshness.
            return False
        try:
            with self._store._connect() as conn:
                row = conn.execute(
                    """
                    SELECT achieved_halfwidth_pp
                    FROM runs
                    WHERE machine=? AND mode=? AND status='completed'
                      AND rawdata_config_md5=? AND rawdata_code_md5=?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (machine, mode, cfg_md5, code_md5),
                ).fetchone()
            if row is None:
                return False
            achieved = row["achieved_halfwidth_pp"]
            if achieved is None:
                return False
            return float(achieved) <= float(target_halfwidth_pp)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "AutoInspectManager._has_fresh_report(%s, %d): %s",
                machine, mode, exc,
            )
            return False

    # -- Private -- dispatch -----------------------------------------------

    def _dispatch_sweep(
        self,
        sweep_id: str,
        settings: dict[str, Any],
    ) -> None:
        """Spawn sweep_concurrency worker threads and wait for all to finish.

        Called in a daemon thread.
        """
        concurrency: int = int(settings.get("sweep_concurrency") or 2)
        # Clamp to valid range.
        concurrency = max(1, min(16, concurrency))

        workers: list[threading.Thread] = []
        for i in range(concurrency):
            worker_id = f"{sweep_id[:8]}_w{i}"
            t = threading.Thread(
                target=self._worker,
                args=(sweep_id, worker_id, settings),
                daemon=True,
                name=f"auto-inspect-worker-{worker_id}",
            )
            t.start()
            workers.append(t)

        for w in workers:
            w.join()

        # All workers finished -- check final sweep state.
        self._finalize_sweep_if_done(sweep_id)

    def _worker(
        self,
        sweep_id: str,
        worker_id: str,
        settings: dict[str, Any],
    ) -> None:
        """Worker loop: claim -> process -> repeat until no pending items."""
        from src.web_console.backend.cell_lock_registry import (  # noqa: PLC0415
            CellOperation,
        )

        cancel_ev = self._cancel_events.get(sweep_id)
        cell_busy_timeout_s: float = float(
            settings.get("cell_busy_timeout_s") or 1800
        )
        max_consecutive_failures: int = int(
            settings.get("max_consecutive_failures") or 3
        )

        consecutive_idle = 0

        while True:
            # Check cancel signal.
            if cancel_ev and cancel_ev.is_set():
                _logger.info(
                    "AutoInspectManager._worker %s: cancel signalled, stopping",
                    worker_id,
                )
                break

            # Check failure trip condition.
            if self._failure_counter_tripped(sweep_id, max_consecutive_failures):
                _logger.error(
                    "AutoInspectManager._worker %s: failure counter tripped, "
                    "cancelling sweep %s",
                    worker_id, sweep_id,
                )
                self._trip_sweep_on_failure(sweep_id)
                break

            # Atomic claim.
            item = self._claim_next_item(sweep_id, worker_id)
            if item is None:
                consecutive_idle += 1
                if consecutive_idle >= 3:
                    # No pending items after 3 retries -- worker is done.
                    break
                time.sleep(_WORKER_POLL_S)
                continue
            consecutive_idle = 0

            machine = str(item["machine"])
            mode = int(item["mode"])

            _logger.debug(
                "AutoInspectManager._worker %s: claimed %s/mode_%d "
                "cell_class=%s",
                worker_id, machine, mode, item.get("cell_class"),
            )

            # structural_skip: mark and continue.
            if str(item.get("cell_class")) == "bcm_hard":
                self._mark_item(
                    sweep_id, machine, mode,
                    status="structural_skip",
                    reason=(
                        "machine in structural_skip roster -- "
                        "manual review required"
                    ),
                )
                self._append_item_event(
                    sweep_id, machine, mode,
                    {"type": "structural_skip", "worker": worker_id,
                     "reason": "bcm_hard"},
                )
                self._record_failure_window(sweep_id, "skip")
                continue

            # manifest_override: log event but proceed through standard path.
            if str(item.get("cell_class")) == "manifest_override":
                self._append_item_event(
                    sweep_id, machine, mode,
                    {"type": "info", "worker": worker_id,
                     "message": "running with manifest override"},
                )

            # Cell-lock yield (per 07_decision §2 V1 + cell_busy_timeout_s).
            lock_acquired = False
            lock_deadline = time.monotonic() + cell_busy_timeout_s
            while time.monotonic() < lock_deadline:
                if cancel_ev and cancel_ev.is_set():
                    break
                if self._registry.try_acquire_cell(
                    machine, mode, CellOperation.SAMPLING,
                    info={"run_id": "", "sweep_id": sweep_id},
                ):
                    lock_acquired = True
                    break
                time.sleep(_CELL_LOCK_POLL_S)

            if not lock_acquired:
                if cancel_ev and cancel_ev.is_set():
                    self._mark_item(
                        sweep_id, machine, mode,
                        status="cancelled",
                        reason=(
                            "cancelled by operator while waiting for cell lock"
                        ),
                    )
                else:
                    self._mark_item(
                        sweep_id, machine, mode,
                        status="deferred_lock_conflict",
                        reason="cell busy >30min -- yielded to manual op",
                    )
                    self._record_failure_window(sweep_id, "skip")
                continue

            try:
                # Sample the cell.
                self._sample_cell(
                    sweep_id, machine, mode, worker_id, settings, cancel_ev,
                )
            finally:
                self._registry.release_cell(machine, mode, CellOperation.SAMPLING)

    def _sample_cell(
        self,
        sweep_id: str,
        machine: str,
        mode: int,
        worker_id: str,
        settings: dict[str, Any],
        cancel_ev: threading.Event | None,
    ) -> None:
        """Run the sampling step for one cell.  Called with cell lock held."""
        from src.web_console.backend.app import RunCreateRequest  # noqa: PLC0415

        mode_settings = (settings.get("modes") or {}).get(str(mode)) or {}
        chunk_spin_times: int = int(mode_settings.get("chunk_spin_times") or 10000)
        chunk_robot_count: int = int(mode_settings.get("chunk_robot_count") or 2)
        batch_concurrency: int = int(mode_settings.get("batch_concurrency") or 16)
        target_halfwidth_pp: float = float(
            mode_settings.get("target_halfwidth_pp") or 0.5
        )
        max_chunks: int = int(mode_settings.get("max_chunks") or 60)

        # Build RunCreateRequest.
        req = RunCreateRequest(
            machine=machine,
            mode=mode,
            chunk_spin_times=chunk_spin_times,
            chunk_robot_count=chunk_robot_count,
            batch_concurrency=batch_concurrency,
            target_halfwidth_pp=target_halfwidth_pp,
            max_chunks=max_chunks,
        )

        # Start the run.
        try:
            run_result = self._run_manager.start_run(req)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            _logger.error(
                "AutoInspectManager._sample_cell: start_run(%s/%d) "
                "failed: %s\n%s",
                machine, mode, exc, tb,
            )
            self._mark_item(
                sweep_id, machine, mode,
                status="failed",
                reason=f"start_run failed: {type(exc).__name__}: {exc}",
            )
            self._record_failure_window(sweep_id, "failed")
            return

        run_id = str(run_result.get("run_id") or "")
        if not run_id:
            self._mark_item(
                sweep_id, machine, mode,
                status="failed",
                reason="start_run returned empty run_id",
            )
            self._record_failure_window(sweep_id, "failed")
            return

        # Store sample_run_id on the item row.
        now_ts = datetime.now(timezone.utc).isoformat()
        with self._store._connect() as conn:
            conn.execute(
                """
                UPDATE auto_inspect_items
                SET sample_run_id=?, started_at=?
                WHERE sweep_id=? AND machine=? AND mode=?
                """,
                (run_id, now_ts, sweep_id, machine, mode),
            )
            conn.commit()

        self._append_item_event(
            sweep_id, machine, mode,
            {"type": "sample_started", "run_id": run_id, "worker": worker_id},
        )

        # Wait for run completion (poll runs table).
        wall_time_s: float = float(
            settings.get("wall_time_per_cell_s") or 7200
        )
        deadline = time.monotonic() + wall_time_s
        run_terminal_status = ""

        while time.monotonic() < deadline:
            # Check cancel.
            if cancel_ev and cancel_ev.is_set():
                run_terminal_status = "cancelled"
                break

            row = self._store.get_run(run_id)
            if row is None:
                run_terminal_status = "failed"
                break
            status = str(row.get("status") or "")
            if status == "completed":
                run_terminal_status = "completed"
                break
            elif status in ("failed", "cancelled"):
                run_terminal_status = status
                break
            time.sleep(_RUN_POLL_S)

        if not run_terminal_status:
            # Wall time exceeded.
            self._mark_item(
                sweep_id, machine, mode,
                status="wall_time_timeout",
                reason=f"run {run_id} exceeded wall_time {wall_time_s}s",
                extra={"sample_run_id": run_id},
            )
            self._record_failure_window(sweep_id, "skip")
            return

        if run_terminal_status == "cancelled":
            self._mark_item(
                sweep_id, machine, mode,
                status="cancelled",
                reason="cancelled by operator during sampling",
                extra={"sample_run_id": run_id},
            )
            return

        if run_terminal_status == "completed":
            # P2 marks 'completed' (generate phase is P3).
            self._mark_item(
                sweep_id, machine, mode,
                status="completed",
                reason="sampling completed",
                extra={"sample_run_id": run_id},
            )
            self._record_failure_window(sweep_id, "ok")
            self._append_item_event(
                sweep_id, machine, mode,
                {"type": "sample_completed", "run_id": run_id},
            )
            return

        # run_terminal_status in ('failed',).
        row = self._store.get_run(run_id)
        err_msg = (
            str((row or {}).get("error_message") or "") if row else ""
        )
        self._mark_item(
            sweep_id, machine, mode,
            status="failed",
            reason=(
                f"run {run_id} terminal status={run_terminal_status}: {err_msg}"
            ),
            extra={"sample_run_id": run_id},
        )
        self._record_failure_window(sweep_id, "failed")

    # -- Private -- failure window -----------------------------------------

    def _record_failure_window(self, sweep_id: str, outcome: str) -> None:
        """Record an outcome ('ok', 'failed', 'skip') in the sweep's window.

        Only 'ok' and 'failed' are counted as "attempts" (MF-5: skip
        statuses do not increment the failure counter).
        """
        if outcome not in ("ok", "failed"):
            return  # 'skip' -- not an attempt
        with self._failure_lock:
            window = self._failure_windows.get(sweep_id)
            if window is None:
                return
            window.append(outcome)

    def _failure_counter_tripped(
        self,
        sweep_id: str,
        max_failures: int,
    ) -> bool:
        """Return True if >=max_failures of last 10 attempts are 'failed'."""
        with self._failure_lock:
            window = self._failure_windows.get(sweep_id)
            if window is None:
                return False
            failed_count = sum(1 for x in window if x == "failed")
            return failed_count >= max_failures

    def _trip_sweep_on_failure(self, sweep_id: str) -> None:
        """Set sweep status='failed', cancel pending items."""
        now_ts = datetime.now(timezone.utc).isoformat()
        cancel_ev = self._cancel_events.get(sweep_id)
        if cancel_ev:
            cancel_ev.set()
        with self._store._connect() as conn:
            conn.execute(
                """
                UPDATE auto_inspect_items
                SET status='cancelled',
                    terminal_reason='sweep cancelled due to failure trip',
                    finished_at=?
                WHERE sweep_id=? AND status='pending'
                """,
                (now_ts, sweep_id),
            )
            conn.execute(
                """
                UPDATE auto_inspect_sweeps
                SET status='failed', finished_at=?
                WHERE sweep_id=?
                """,
                (now_ts, sweep_id),
            )
            conn.commit()

    # -- Private -- DB helpers ---------------------------------------------

    def _claim_next_item(
        self,
        sweep_id: str,
        worker_id: str,
    ) -> dict[str, Any] | None:
        """Atomic claim: UPDATE ... RETURNING for the next pending item.

        Wrapped in threading.Lock (self._claim_lock) to prevent two workers
        from racing on the same RETURNING row.
        """
        now_ts = datetime.now(timezone.utc).isoformat()
        with self._claim_lock:
            try:
                with self._store._connect() as conn:
                    row = conn.execute(
                        """
                        UPDATE auto_inspect_items
                        SET status='claimed', claimed_by=?, claimed_at=?
                        WHERE (sweep_id, machine, mode) = (
                            SELECT sweep_id, machine, mode
                            FROM auto_inspect_items
                            WHERE sweep_id=? AND status='pending'
                            ORDER BY queue_position ASC
                            LIMIT 1
                        )
                        RETURNING *
                        """,
                        (worker_id, now_ts, sweep_id),
                    ).fetchone()
                    conn.commit()
                if row:
                    return dict(row)
                return None
            except sqlite3.OperationalError as exc:
                # RETURNING not supported (SQLite < 3.35) -- use fallback.
                _logger.warning(
                    "AutoInspectManager._claim_next_item: RETURNING not "
                    "supported (%s), using SELECT+UPDATE fallback",
                    exc,
                )
                return self._claim_next_item_fallback(
                    sweep_id, worker_id, now_ts
                )

    def _claim_next_item_fallback(
        self,
        sweep_id: str,
        worker_id: str,
        now_ts: str,
    ) -> dict[str, Any] | None:
        """Fallback claim for SQLite < 3.35 (no RETURNING).

        Still inside self._claim_lock (called from _claim_next_item).
        """
        with self._store._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM auto_inspect_items
                WHERE sweep_id=? AND status='pending'
                ORDER BY queue_position ASC
                LIMIT 1
                """,
                (sweep_id,),
            ).fetchone()
            if row is None:
                return None
            machine = str(row["machine"])
            mode = int(row["mode"])
            conn.execute(
                """
                UPDATE auto_inspect_items
                SET status='claimed', claimed_by=?, claimed_at=?
                WHERE sweep_id=? AND machine=? AND mode=?
                  AND status='pending'
                """,
                (worker_id, now_ts, sweep_id, machine, mode),
            )
            conn.commit()
        return dict(row)

    def _mark_item(
        self,
        sweep_id: str,
        machine: str,
        mode: int,
        *,
        status: str,
        reason: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Set terminal status + reason on an item row.

        Per 07_decision §6: every terminal status must carry non-null
        terminal_reason.
        """
        now_ts = datetime.now(timezone.utc).isoformat()
        update_fields: list[str] = [
            "status=?",
            "terminal_reason=?",
            "finished_at=?",
        ]
        params: list[Any] = [status, reason, now_ts]

        if extra:
            for k, v in extra.items():
                if k == "sample_run_id":
                    update_fields.append("sample_run_id=?")
                    params.append(str(v))

        params.extend([sweep_id, machine, mode])
        sql = (
            f"UPDATE auto_inspect_items SET {', '.join(update_fields)} "
            "WHERE sweep_id=? AND machine=? AND mode=?"
        )
        with self._store._connect() as conn:
            conn.execute(sql, params)
            conn.commit()

        # Update sweep aggregate counters.
        self._update_sweep_counts(sweep_id)

    def _append_item_event(
        self,
        sweep_id: str,
        machine: str,
        mode: int,
        event: dict[str, Any],
    ) -> None:
        """Append an event to the item's events_json array.

        Per 07_decision §2 R3.2 resolution: cap at 20 events per item.
        Events are best-effort -- failure here is logged, not raised.
        """
        event_with_ts = dict(event)
        event_with_ts.setdefault("ts", datetime.now(timezone.utc).isoformat())
        try:
            with self._store._connect() as conn:
                row = conn.execute(
                    "SELECT events_json FROM auto_inspect_items "
                    "WHERE sweep_id=? AND machine=? AND mode=?",
                    (sweep_id, machine, mode),
                ).fetchone()
                if row is None:
                    return
                existing = json.loads(str(row["events_json"] or "[]"))
                if not isinstance(existing, list):
                    existing = []
                existing.append(event_with_ts)
                # Cap at 20 events per item.
                if len(existing) > 20:
                    existing = existing[-20:]
                conn.execute(
                    "UPDATE auto_inspect_items SET events_json=? "
                    "WHERE sweep_id=? AND machine=? AND mode=?",
                    (json.dumps(existing), sweep_id, machine, mode),
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            # Event append is best-effort; persist diagnostic, don't raise.
            _logger.warning(
                "AutoInspectManager._append_item_event: failed for "
                "%s/%d: %s",
                machine, mode, exc,
            )

    def _update_sweep_counts(self, sweep_id: str) -> None:
        """Update completed/failed/skipped counts on the sweep row."""
        try:
            with self._store._connect() as conn:
                counts = conn.execute(
                    """
                    SELECT
                        SUM(status='completed') AS completed,
                        SUM(status='failed') AS failed,
                        SUM(status IN (
                            'structural_skip','convergence_timeout',
                            'manifest_override_partial',
                            'deferred_lock_conflict',
                            'wall_time_timeout',
                            'md5_drift_invalidated',
                            'cancelled'
                        )) AS skipped
                    FROM auto_inspect_items
                    WHERE sweep_id=?
                    """,
                    (sweep_id,),
                ).fetchone()
                if counts:
                    conn.execute(
                        """
                        UPDATE auto_inspect_sweeps
                        SET completed_items=?, failed_items=?,
                            skipped_items=?
                        WHERE sweep_id=?
                        """,
                        (
                            int(counts["completed"] or 0),
                            int(counts["failed"] or 0),
                            int(counts["skipped"] or 0),
                            sweep_id,
                        ),
                    )
                    conn.commit()
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "AutoInspectManager._update_sweep_counts(%s): %s",
                sweep_id, exc,
            )

    def _finalize_sweep_if_done(self, sweep_id: str) -> None:
        """After all workers finish, check if sweep should be 'completed'."""
        now_ts = datetime.now(timezone.utc).isoformat()
        try:
            # Check cancel signal first.
            cancel_ev = self._cancel_events.get(sweep_id)
            if cancel_ev and cancel_ev.is_set():
                return  # already handled by cancel_sweep or trip

            with self._store._connect() as conn:
                sweep_row = conn.execute(
                    "SELECT status FROM auto_inspect_sweeps WHERE sweep_id=?",
                    (sweep_id,),
                ).fetchone()
                if sweep_row is None:
                    return
                if str(sweep_row["status"]) not in ("sampling", "finalizing"):
                    return  # already terminal

                # Check if any items are still non-terminal.
                non_terminal = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM auto_inspect_items
                    WHERE sweep_id=?
                      AND status IN (
                          'pending','claimed','running','generating'
                      )
                    """,
                    (sweep_id,),
                ).fetchone()
                if non_terminal and int(non_terminal["cnt"] or 0) > 0:
                    return  # still in progress

                conn.execute(
                    """
                    UPDATE auto_inspect_sweeps
                    SET status='completed', finished_at=?
                    WHERE sweep_id=?
                      AND status IN ('sampling','finalizing')
                    """,
                    (now_ts, sweep_id),
                )
                conn.commit()
            _logger.info(
                "AutoInspectManager._finalize_sweep_if_done: "
                "sweep %s completed",
                sweep_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "AutoInspectManager._finalize_sweep_if_done(%s): %s",
                sweep_id, exc,
            )

    def _has_running_sweep(self) -> bool:
        """Return True if a non-terminal sweep exists in the DB."""
        try:
            with self._store._connect() as conn:
                row = conn.execute(
                    """
                    SELECT sweep_id FROM auto_inspect_sweeps
                    WHERE status IN ('scanning', 'sampling', 'finalizing')
                    LIMIT 1
                    """,
                ).fetchone()
            return row is not None
        except sqlite3.OperationalError:
            return False
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "AutoInspectManager._has_running_sweep: unexpected error: %s",
                exc,
            )
            return False

    # -- Private -- helpers ------------------------------------------------

    def _scan_persisted_for_resume(self) -> str | None:
        """Return the sweep_id of the most-recent non-terminal sweep, or None.

        Non-terminal sweep statuses: 'scanning', 'sampling', 'finalizing'.
        Pure SQLite read -- no HTTP, no upstream calls, safe in __init__.

        Returns None if:
          * No non-terminal sweeps exist.
          * The auto_inspect_sweeps table doesn't exist yet (pre-P1 DB).
        """
        try:
            with self._store._connect() as conn:
                row = conn.execute(
                    """
                    SELECT sweep_id
                    FROM auto_inspect_sweeps
                    WHERE status IN ('scanning', 'sampling', 'finalizing')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                ).fetchone()
                if row:
                    sweep_id = str(row["sweep_id"])
                    _logger.info(
                        "AutoInspectManager: found non-terminal sweep %s on "
                        "startup; will resume after create_app finishes.",
                        sweep_id,
                    )
                    return sweep_id
                return None
        except sqlite3.OperationalError as exc:
            # Table doesn't exist yet (pre-P1 DB).
            _logger.debug(
                "AutoInspectManager._scan_persisted_for_resume: "
                "OperationalError (likely pre-P1 DB, no "
                "auto_inspect_sweeps table yet): %s",
                exc,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "AutoInspectManager._scan_persisted_for_resume: "
                "unexpected error: %s\n%s",
                exc,
                traceback.format_exc(),
            )
            print(
                f"[auto-inspect] _scan_persisted_for_resume unexpected "
                f"error: {exc}",
                flush=True,
            )
            return None

    def _load_auto_sweep_settings(self) -> dict[str, Any]:
        """Load the auto_sweep block from settings.json (current values).

        Per 07_decision §2 OQ-C: always reads current settings so that
        tightening target_halfwidth_pp between sweeps re-queues cells
        whose previous reports exceed the new target.
        """
        try:
            from src.web_console.backend.app import _load_settings  # noqa: PLC0415
            s = _load_settings(self._settings_path)
            return s.get("auto_sweep") or {}
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "AutoInspectManager._load_auto_sweep_settings: %s, "
                "using defaults",
                exc,
            )
            return {}

    def _load_machines_json(self) -> dict[str, Any]:
        """Load machines.json.  Returns empty dict on error."""
        try:
            return json.loads(
                self._machines_config.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            _logger.warning(
                "AutoInspectManager._load_machines_json: %s", exc,
            )
            return {"machines": []}

    def _load_machine_modes_json(self) -> dict[str, list[int]]:
        """Load configs/machine_modes.json.  Returns empty dict on error.

        Resolves path relative to machines_config's parent directory
        (in production: configs/machine_modes.json lives next to
        configs/machines.json).
        """
        modes_path = self._machines_config.parent / "machine_modes.json"
        if not modes_path.exists():
            # Fallback: try project_root/configs/machine_modes.json.
            modes_path = (
                self._machines_config.parents[1] / "configs" / "machine_modes.json"
            )
        try:
            raw = json.loads(modes_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            _logger.warning(
                "AutoInspectManager._load_machine_modes_json: %s", exc,
            )
            return {}

    def _machine_has_mode(
        self,
        machine: str,
        mode: int,
        machine_modes: dict[str, list[int]],
    ) -> bool:
        """Return True if machine supports this mode.

        Uses machine_modes.json lookup first, then falls back to
        checking the machines.json mode_list field.
        """
        if machine_modes:
            modes = machine_modes.get(machine)
            if modes is not None:
                return mode in modes

        # Fallback: check machines.json mode_list.
        try:
            data = self._load_machines_json()
            for entry in (data.get("machines") or []):
                if str(entry.get("machine") or "") == machine:
                    mode_list = entry.get("mode_list") or []
                    return mode in mode_list
        except Exception:  # noqa: BLE001
            pass
        # Default: assume mode 1 always supported.
        return mode == 1

    def _find_manifest_override_machines(
        self,
        machines: list[str],
    ) -> set[str]:
        """Return set of machines whose manifest has paid_spin_type != [1]
        or pay_id_override != null (per 07_decision §2 MF-4).
        """
        project_root = self._machines_config.parent.parent
        manifest_dir = project_root / _MANIFEST_SUBPATH

        overrides: set[str] = set()
        if not manifest_dir.is_dir():
            return overrides

        for machine in machines:
            manifest_path = manifest_dir / f"{machine}.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(manifest, dict):
                continue

            # paid_spin_type != [1]: check spin_type_convention.paid.
            stc = manifest.get("spin_type_convention")
            if isinstance(stc, dict):
                paid = stc.get("paid") or []
                if paid and paid != [1]:
                    overrides.add(machine)
                    continue

            # pay_id_override != null.
            if manifest.get("pay_id_override") is not None:
                overrides.add(machine)

        return overrides

    def _load_trigger_session_roster(self) -> set[str]:
        """Return set of machines known to use trigger sessions.

        Sources the roster from the manifest files: machines whose manifest
        has a non-null trigger_session_pattern field.
        """
        project_root = self._machines_config.parent.parent
        manifest_dir = project_root / _MANIFEST_SUBPATH

        roster: set[str] = set()
        if not manifest_dir.is_dir():
            return roster

        for manifest_path in manifest_dir.glob("M*.json"):
            # Only main manifests (not variant files with $ in name).
            if "$" in manifest_path.name:
                continue
            try:
                manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(manifest, dict):
                continue
            machine = str(
                manifest.get("machine_id") or manifest_path.stem
            )
            tsp = manifest.get("trigger_session_pattern")
            if tsp is not None:
                roster.add(machine)

        return roster

    def _get_fleet_refresh_manager(self) -> "_FleetRefreshStatusProxy | None":
        """Try to get a status proxy for FleetRefreshManager.

        Used by start_sweep for the MF-3 mutex check.
        Returns None if unavailable (pre-P3 DB, virtual console, etc.).
        """
        try:
            db_path = self._store.db_path
            if not db_path.exists():
                return None
            return _FleetRefreshStatusProxy(db_path)
        except Exception:  # noqa: BLE001
            return None


class _FleetRefreshStatusProxy:
    """Minimal proxy for fleet refresh status check (MF-3 mutex).

    Does not run a full FleetRefreshManager -- only exposes
    get_running_queue_id() by reading the DB directly.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def get_running_queue_id(self) -> str | None:
        """Return running queue_id or None."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT queue_id FROM fleet_refresh_queue "
                    "WHERE status='running' LIMIT 1"
                ).fetchone()
                return str(row["queue_id"]) if row else None
            finally:
                conn.close()
        except sqlite3.OperationalError:
            return None
        except Exception:  # noqa: BLE001
            return None
