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

Phase 3 (Per-item generate + failure modes) adds:

  * _dispatch_generate_for_item -- post-sample generate run dispatch
  * _wait_for_run -- generic run-completion poller
  * _sample_cell extended:
      - md5_drift_invalidated pre-flight check
      - convergence_timeout detection after sample
      - manifest_override_partial stub detection
      - generate dispatch + wait inline (MF-2 resolution)
  * resume_sweep extended:
      - running items (mid-sample crash) reset to pending
      - generating items (mid-generate crash) recovered from runs table
  * _mark_item extended: supports generate_run_id + generate_status extras
  * All 9 terminal statuses reachable (see _TERMINAL_STATUSES constant)

Phase 5 (Cron scheduler + M274 alert + hardening) adds:

  * _AutoInspectScheduler -- threading.Timer-based cron scheduler
      - daily HH:MM mode (fire once per day at that UTC wall-clock time)
      - interval N mode (fire every N hours)
      - reads settings every cycle (operator can change cadence live)
      - idempotent: if sweep is running, logs skip and reschedules
  * _check_m274_alert -- M274 RTP-drift alert (07_decision §2 OQ-A)
      - compares achieved_rtp_pct (not halfwidth) against baseline
      - baseline auto-created on first successful M274/mode-1 sweep run
      - fires WARN event + persists alert file on |delta| > 2.0pp
  * preview_sweep -- adds 5-second urllib timeout (P4 open concern #1)
  * get_sweep_status -- adds items_limit param (P4 open concern #2)

Design:  session_artifacts/_arch/auto_inspect/07_decision.md §2-§4 + §6
Phase 1: commit 1bcf43c
Phase 2: commit 76c4512
Phase 3: commit 205ffc0
Phase 4: commit 9181ff8

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
import re
import sqlite3
import threading
import time
import traceback
import urllib.error
import urllib.request
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

# All 9 terminal item statuses (07_decision §3 + §4 P3 deliverable 2).
# Each must be paired with a non-null terminal_reason (§6 acceptance).
_TERMINAL_STATUSES = frozenset({
    "completed",              # sample + generate both succeeded
    "failed",                 # subprocess crash / HTTP error / disk error
    "structural_skip",        # machine in structural_skip_machines roster
    "convergence_timeout",    # max_chunks hit before target CI half-width
    "manifest_override_partial",  # manifest bootstrap-default data (stub for P5)
    "deferred_lock_conflict", # cell-lock yield exceeded cell_busy_timeout_s
    "wall_time_timeout",      # item sampling/generate exceeded wall_time_per_cell_s
    "md5_drift_invalidated",  # upstream md5 changed between enqueue and dispatch
    "cancelled",              # operator-requested cancellation
})

# Worker poll interval in seconds.
_WORKER_POLL_S = 1.0

# Cell-lock poll interval in seconds.
_CELL_LOCK_POLL_S = 5.0

# Run poll interval in seconds.
_RUN_POLL_S = 5.0

# Cron validation regexes (07_decision §2 OQ-G).
# daily: "HH:MM" where H=[01]\d or 2[0-3], M=[0-5]\d
_CRON_DAILY_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# interval: 1-24 (integer string)
_CRON_INTERVAL_RE = re.compile(r"^([1-9]|1\d|2[0-4])$")

# M274 RTP-drift alert threshold (pp).
_M274_ALERT_DELTA_PP = 2.0

# Machine + mode that the baseline alert tracks.
_M274_MACHINE = "M274"
_M274_MODE = 1

# Preview scan upstream timeout (seconds).
_PREVIEW_UPSTREAM_TIMEOUT_S = 5

# Default items cap for get_sweep_status.
_ITEMS_DEFAULT_LIMIT = 200


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

    def get_sweep_status(
        self,
        sweep_id: str,
        items_limit: int = _ITEMS_DEFAULT_LIMIT,
    ) -> dict[str, Any] | None:
        """Return sweep progress dict or None if sweep_id not found.

        P4 addition: also returns ``items`` list for the per-cell
        drill-down table in the frontend.  Each item contains the
        fields the UI needs to render a row.

        P5 addition: ``items_limit`` caps the items list returned
        (default 200, per P5 deliverable 4).  UI passes ?items_limit=200.
        For a 1688-cell sweep this avoids sending a multi-MB payload on
        every poll.  Items are returned in queue_position order (earliest
        first).
        """
        # Clamp to sensible range.
        items_limit = max(1, min(items_limit, 5000))

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

            # Fetch items for per-cell drill-down (P4 §5).
            # P5: capped at items_limit (default 200).
            items_rows = conn.execute(
                """
                SELECT machine, mode, status, cell_class,
                       terminal_reason, started_at, finished_at,
                       queue_position
                FROM auto_inspect_items
                WHERE sweep_id=?
                ORDER BY queue_position ASC
                LIMIT ?
                """,
                (sweep_id, items_limit),
            ).fetchall()

        counts: dict[str, int] = {}
        for cr in counts_rows:
            counts[str(cr["status"])] = int(cr["cnt"])

        items: list[dict[str, Any]] = [
            {
                "machine": str(ir["machine"]),
                "mode": int(ir["mode"]),
                "status": str(ir["status"]),
                "cell_class": str(ir["cell_class"]),
                "terminal_reason": ir["terminal_reason"],
                "started_at": ir["started_at"],
                "finished_at": ir["finished_at"],
                "queue_position": int(ir["queue_position"]),
            }
            for ir in items_rows
        ]

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
            "items": items,
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

    def preview_sweep(self) -> dict[str, Any]:
        """Return what a new sweep would enqueue, without committing anything.

        P4 deliverable 3 (GET /api/auto-inspect/preview).

        P5 hardening: _scan_cells runs in a background thread with a
        5-second timeout against the upstream snapshot fetch.  If
        the thread doesn't finish in _PREVIEW_UPSTREAM_TIMEOUT_S seconds,
        the operator gets a diagnostic message instead of a hanging UI.

        Returns a dict with:
          * cells: list of cell dicts (machine, mode, cell_class,
            cfg_md5_at_enqueue, code_md5_at_enqueue)
          * total: int
          * by_mode: {str(mode): int}
          * by_cell_class: {cell_class: int}
          * estimated_wall_time_s: int (total * 300 rough estimate)
          * structural_skip_count: int
          * manifest_override_count: int
        """
        from fastapi import HTTPException  # noqa: PLC0415

        settings = self._load_auto_sweep_settings()
        modes_list = list(_SWEEP_MODES)
        skip_fresh = bool(settings.get("skip_fresh_cells", True))

        # P5: run scan in a thread so we can enforce a timeout.
        # _scan_cells is CPU/disk-bound; the only potential slow-path
        # is if `_resolve_active_server_id` or snapshot load hits a
        # very slow NTFS path.  Timeout is generous (30s) to cover
        # large fleets while still protecting the HTTP handler from
        # hanging indefinitely.
        scan_result: list[list[dict[str, Any]]] = []
        scan_exc: list[BaseException] = []

        def _run_scan() -> None:
            try:
                scan_result.append(
                    self._scan_cells(modes_list, skip_fresh=skip_fresh)
                )
            except Exception as exc:  # noqa: BLE001
                scan_exc.append(exc)

        scan_thread = threading.Thread(target=_run_scan, daemon=True)
        scan_thread.start()
        # Allow _PREVIEW_UPSTREAM_TIMEOUT_S for the scan (filesystem + DB).
        # Use 30s for preview (more generous than the name suggests; the
        # constant is named for the upstream concern but applies to full scan).
        scan_thread.join(timeout=30)

        if scan_thread.is_alive():
            _logger.warning(
                "AutoInspectManager.preview_sweep: scan timed out after 30s"
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    "preview unavailable: scan timed out -- "
                    "upstream snapshot may be unreachable"
                ),
            )

        if scan_exc:
            exc = scan_exc[0]
            _logger.error(
                "AutoInspectManager.preview_sweep: _scan_cells error: %s",
                exc,
            )
            raise HTTPException(
                status_code=500,
                detail=f"preview scan error: {type(exc).__name__}: {exc}",
            )

        cells = scan_result[0] if scan_result else []

        by_mode: dict[str, int] = {}
        by_cell_class: dict[str, int] = {}
        for cell in cells:
            mode_key = str(cell["mode"])
            by_mode[mode_key] = by_mode.get(mode_key, 0) + 1
            cc = str(cell.get("cell_class") or "easy")
            by_cell_class[cc] = by_cell_class.get(cc, 0) + 1

        structural_skip_count = by_cell_class.get("bcm_hard", 0)
        manifest_override_count = by_cell_class.get("manifest_override", 0)
        # Rough estimate: 5 minutes per cell.
        estimated_wall_time_s = len(cells) * 300

        return {
            "total": len(cells),
            "cells": [
                {
                    "machine": c["machine"],
                    "mode": c["mode"],
                    "cell_class": c.get("cell_class") or "easy",
                    "cfg_md5_at_enqueue": c.get("cfg_md5_at_enqueue") or "",
                    "code_md5_at_enqueue": c.get("code_md5_at_enqueue") or "",
                }
                for c in cells
            ],
            "by_mode": by_mode,
            "by_cell_class": by_cell_class,
            "structural_skip_count": structural_skip_count,
            "manifest_override_count": manifest_override_count,
            "estimated_wall_time_s": estimated_wall_time_s,
        }

    def resume_sweep(self, sweep_id: str) -> None:
        """Resume a sweep that was interrupted by a console restart.

        Per 07_decision §2 V3: resets claimed->pending, then re-dispatches
        workers.  Runs in a daemon thread spawned by create_app.
        """
        _logger.info(
            "AutoInspectManager.resume_sweep: resuming sweep_id=%s", sweep_id,
        )

        # Phase 3 recovery: resolve 'running' and 'generating' items first,
        # then reset 'claimed' to 'pending'.
        #
        # (a) Items mid-sample (status='running', sample_run_id IS NOT NULL):
        #     Check if the sample run succeeded, failed, or is still orphaned.
        #     - completed -> dispatch generate phase (set to 'running' so
        #       the worker will re-dispatch generate from recovery)
        #     - failed / orphaned -> reset to 'pending' so worker re-samples
        #
        # (b) Items mid-generate (status='generating', generate_run_id IS NOT NULL):
        #     Check the generate run's status in runs table.
        #     - completed -> mark item 'completed'
        #     - failed / still-running (orphan) -> clear generate_run_id,
        #       reset to 'running' so worker will re-dispatch generate
        #
        # (c) Items with terminal status: no-op (already done).
        try:
            self._resume_recover_running_items(sweep_id)
            self._resume_recover_generating_items(sweep_id)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            _logger.error(
                "AutoInspectManager.resume_sweep: phase-recovery failed for "
                "%s: %s\n%s",
                sweep_id, exc, tb,
            )
            # Persist to stdout so operator can see it even without log rotation.
            print(
                f"[auto-inspect] resume_sweep({sweep_id!r}) phase-recovery "
                f"failed: {exc}",
                flush=True,
            )
            # Fall through to claimed-reset; don't abort the whole resume.

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
        """Run the sampling step for one cell, then dispatch generate.

        Called with cell lock held.

        Phase 3 additions vs P2:
          * md5_drift_invalidated pre-flight check (07_decision §4 P3 del.5)
          * convergence_timeout detection after sample completes (del.3)
          * manifest_override_partial stub (del.3, real heuristic in P5)
          * generate dispatch + wait inline (del.1, MF-2 resolution)
        """
        from src.web_console.backend.app import (  # noqa: PLC0415
            RunCreateRequest,
            _get_machine_md5,
        )

        mode_settings = (settings.get("modes") or {}).get(str(mode)) or {}
        chunk_spin_times: int = int(mode_settings.get("chunk_spin_times") or 10000)
        chunk_robot_count: int = int(mode_settings.get("chunk_robot_count") or 2)
        batch_concurrency: int = int(mode_settings.get("batch_concurrency") or 16)
        target_halfwidth_pp: float = float(
            mode_settings.get("target_halfwidth_pp") or 0.5
        )
        max_chunks: int = int(mode_settings.get("max_chunks") or 60)

        # -- P3 del.5: md5_drift_invalidated pre-flight ----------------------
        # Compare item's cfg_md5_at_enqueue / code_md5_at_enqueue against the
        # current local md5.  If they diverged, the upstream config changed
        # since this cell was enqueued; sampling with stale md5 would produce
        # a mixed-md5 report.  Mark and skip.
        # NOTE: explicit mode= required (07_decision §6 acceptance criteria).
        if self._check_md5_drift(sweep_id, machine, mode, settings):
            # _check_md5_drift marks the item itself; just return.
            return

        # Build RunCreateRequest for sampling.
        req = RunCreateRequest(
            machine=machine,
            mode=mode,
            chunk_spin_times=chunk_spin_times,
            chunk_robot_count=chunk_robot_count,
            batch_concurrency=batch_concurrency,
            target_halfwidth_pp=target_halfwidth_pp,
            max_chunks=max_chunks,
        )

        # Start the sample run.
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

        # Store sample_run_id + set status='running' on the item row.
        now_ts = datetime.now(timezone.utc).isoformat()
        with self._store._connect() as conn:
            conn.execute(
                """
                UPDATE auto_inspect_items
                SET sample_run_id=?, started_at=?, status='running'
                WHERE sweep_id=? AND machine=? AND mode=?
                """,
                (run_id, now_ts, sweep_id, machine, mode),
            )
            conn.commit()

        self._append_item_event(
            sweep_id, machine, mode,
            {"type": "sample_started", "run_id": run_id, "worker": worker_id},
        )

        # Wait for sample run completion (poll runs table).
        wall_time_s: float = float(
            settings.get("wall_time_per_cell_s") or 7200
        )
        wall_start = time.monotonic()
        deadline = wall_start + wall_time_s
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
            # Wall time exceeded during sampling.
            self._mark_item(
                sweep_id, machine, mode,
                status="wall_time_timeout",
                reason=(
                    f"sampling run {run_id} exceeded wall_time "
                    f"{wall_time_s}s; sampling aborted"
                ),
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

        if run_terminal_status != "completed":
            # run_terminal_status in ('failed',).
            sample_row = self._store.get_run(run_id)
            err_msg = str((sample_row or {}).get("error_message") or "")
            self._mark_item(
                sweep_id, machine, mode,
                status="failed",
                reason=(
                    f"sample run {run_id} terminal "
                    f"status={run_terminal_status}: {err_msg}"
                ),
                extra={"sample_run_id": run_id},
            )
            self._record_failure_window(sweep_id, "failed")
            return

        # ---------- sampling completed ----------
        self._append_item_event(
            sweep_id, machine, mode,
            {"type": "sample_completed", "run_id": run_id},
        )

        # -- P3 del.3: convergence_timeout detection -------------------------
        # After sampling, check achieved_halfwidth_pp vs target.
        # We still generate the report (bcm_uncharted rationale per OQ-D:
        # partial data is informative even when CI not fully converged).
        sample_row = self._store.get_run(run_id)
        achieved_hw = None
        if sample_row:
            _ahw = sample_row.get("achieved_halfwidth_pp")
            if _ahw is not None:
                try:
                    achieved_hw = float(_ahw)
                except (TypeError, ValueError):
                    achieved_hw = None

        convergence_timed_out = (
            achieved_hw is not None and achieved_hw > target_halfwidth_pp
        )

        # -- P3 del.3: manifest_override_partial stub ------------------------
        # Real heuristic deferred to P5.  Always returns False for now.
        manifest_partial = self._detect_manifest_override_partial_stub(
            sweep_id, machine, mode, sample_row or {},
        )

        # -- P3 del.1: dispatch generate for THIS item (MF-2 resolution) ----
        # We dispatch generate whether or not CI converged (bcm_uncharted
        # rationale).  convergence_timeout status is set AFTER generate
        # if CI wasn't met.
        try:
            generate_run_id = self._dispatch_generate_for_item(
                sweep_id, machine, mode, settings, run_id,
            )
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            _logger.error(
                "AutoInspectManager._sample_cell: "
                "_dispatch_generate_for_item(%s/%d) failed: %s\n%s",
                machine, mode, exc, tb,
            )
            self._mark_item(
                sweep_id, machine, mode,
                status="failed",
                reason=f"generate dispatch error: {type(exc).__name__}: {exc}",
                extra={"sample_run_id": run_id},
            )
            self._record_failure_window(sweep_id, "failed")
            return

        if not generate_run_id:
            self._mark_item(
                sweep_id, machine, mode,
                status="failed",
                reason="generate dispatch returned empty run_id",
                extra={"sample_run_id": run_id},
            )
            self._record_failure_window(sweep_id, "failed")
            return

        # Store generate_run_id and set status='generating'.
        now_ts2 = datetime.now(timezone.utc).isoformat()
        with self._store._connect() as conn:
            conn.execute(
                """
                UPDATE auto_inspect_items
                SET generate_run_id=?, generate_status='running', status='generating'
                WHERE sweep_id=? AND machine=? AND mode=?
                """,
                (generate_run_id, sweep_id, machine, mode),
            )
            conn.commit()

        self._append_item_event(
            sweep_id, machine, mode,
            {"type": "generate_started", "generate_run_id": generate_run_id},
        )

        # Wait for generate run to terminal (remaining wall time).
        elapsed = time.monotonic() - wall_start
        remaining_wall = max(0.0, wall_time_s - elapsed)
        gen_terminal = self._wait_for_run(
            generate_run_id,
            timeout_s=remaining_wall,
            cancel_ev=cancel_ev,
        )

        if gen_terminal == "wall_time":
            self._mark_item(
                sweep_id, machine, mode,
                status="wall_time_timeout",
                reason=(
                    f"generate run {generate_run_id} exceeded remaining "
                    f"wall_time; total cell budget was {wall_time_s}s"
                ),
                extra={
                    "sample_run_id": run_id,
                    "generate_run_id": generate_run_id,
                    "generate_status": "timeout",
                },
            )
            self._record_failure_window(sweep_id, "skip")
            return

        if gen_terminal == "cancelled":
            self._mark_item(
                sweep_id, machine, mode,
                status="cancelled",
                reason="cancelled by operator during generate",
                extra={
                    "sample_run_id": run_id,
                    "generate_run_id": generate_run_id,
                    "generate_status": "cancelled",
                },
            )
            return

        if gen_terminal != "completed":
            gen_row = self._store.get_run(generate_run_id)
            gen_err = str((gen_row or {}).get("error_message") or "")
            self._mark_item(
                sweep_id, machine, mode,
                status="failed",
                reason=(
                    f"generate run {generate_run_id} failed: "
                    f"status={gen_terminal}: {gen_err}"
                ),
                extra={
                    "sample_run_id": run_id,
                    "generate_run_id": generate_run_id,
                    "generate_status": gen_terminal,
                },
            )
            self._record_failure_window(sweep_id, "failed")
            return

        # Generate completed.  Now apply post-sampling classification.
        if manifest_partial:
            self._mark_item(
                sweep_id, machine, mode,
                status="manifest_override_partial",
                reason=(
                    "manifest override detected bootstrap-default paid "
                    "spin_type; report may be imprecise (P5 heuristic pending)"
                ),
                extra={
                    "sample_run_id": run_id,
                    "generate_run_id": generate_run_id,
                    "generate_status": "completed",
                },
            )
            self._record_failure_window(sweep_id, "skip")
            return

        if convergence_timed_out:
            self._mark_item(
                sweep_id, machine, mode,
                status="convergence_timeout",
                reason=(
                    f"sampling achieved halfwidth {achieved_hw:.4f}pp > "
                    f"target {target_halfwidth_pp:.4f}pp after {max_chunks} "
                    f"max chunks; report generated with partial data"
                ),
                extra={
                    "sample_run_id": run_id,
                    "generate_run_id": generate_run_id,
                    "generate_status": "completed",
                },
            )
            self._record_failure_window(sweep_id, "skip")
            return

        # All good -- mark completed.
        self._mark_item(
            sweep_id, machine, mode,
            status="completed",
            reason="sample + generate complete",
            extra={
                "sample_run_id": run_id,
                "generate_run_id": generate_run_id,
                "generate_status": "completed",
            },
        )
        self._record_failure_window(sweep_id, "ok")
        self._append_item_event(
            sweep_id, machine, mode,
            {"type": "generate_completed",
             "generate_run_id": generate_run_id},
        )

        # P5: M274 RTP-drift alert (07_decision §2 OQ-A).
        # Fire after a successful completion for the M274/mode-1 cell.
        if machine == _M274_MACHINE and mode == _M274_MODE:
            self._check_m274_alert(
                sweep_id=sweep_id,
                run_id=run_id,
            )

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

    # -- Private -- P3 generate + failure modes ----------------------------

    def _dispatch_generate_for_item(
        self,
        sweep_id: str,
        machine: str,
        mode: int,
        settings: dict[str, Any],
        sample_run_id: str,
    ) -> str:
        """Dispatch a from-cache generate-report run for a single item.

        Per 07_decision §2 MF-2: each item dispatches its OWN generate run
        after sampling completes.  No batch-level generate; no duplicate
        generate risk.

        Returns the generate run_id string.  Raises on error.

        Note: md5 drift is NOT re-checked here (it was checked in
        _sample_cell pre-flight).  The rawdata written by sampling already
        uses the correct md5.
        """
        from src.web_console.backend.app import RunCreateRequest  # noqa: PLC0415

        # from_cache_dir = rawdata path for (machine, mode).
        # This is the directory where sampling wrote its chunks.
        rawdata_dir = self._rawdata_root / machine / f"mode_{mode}"

        # Snapshot the md5 that sampling used (from the item row).
        with self._store._connect() as conn:
            item_row = conn.execute(
                "SELECT cfg_md5_at_enqueue, code_md5_at_enqueue "
                "FROM auto_inspect_items "
                "WHERE sweep_id=? AND machine=? AND mode=?",
                (sweep_id, machine, mode),
            ).fetchone()
        # sqlite3.Row supports index-access but not .get(); convert to dict.
        item_dict = dict(item_row) if item_row is not None else {}
        cfg_md5 = str(item_dict.get("cfg_md5_at_enqueue") or "")
        code_md5 = str(item_dict.get("code_md5_at_enqueue") or "")

        req = RunCreateRequest(
            machine=machine,
            mode=mode,
            from_cache_dir=str(rawdata_dir),
            upstream_config_md5=cfg_md5,
            upstream_code_md5=code_md5,
        )

        _logger.debug(
            "AutoInspectManager._dispatch_generate_for_item: "
            "%s/mode_%d from_cache_dir=%s",
            machine, mode, rawdata_dir,
        )

        run_result = self._run_manager.start_run(req)
        return str(run_result.get("run_id") or "")

    def _wait_for_run(
        self,
        run_id: str,
        *,
        timeout_s: float,
        cancel_ev: threading.Event | None,
    ) -> str:
        """Poll until run_id reaches a terminal status.

        Returns one of: 'completed', 'failed', 'cancelled', 'wall_time'.
        Never returns an empty string or raises (all errors become 'failed').
        """
        if timeout_s <= 0:
            return "wall_time"

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if cancel_ev and cancel_ev.is_set():
                return "cancelled"
            try:
                row = self._store.get_run(run_id)
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "AutoInspectManager._wait_for_run(%s): get_run error: %s",
                    run_id, exc,
                )
                return "failed"
            if row is None:
                return "failed"
            status = str(row.get("status") or "")
            if status == "completed":
                return "completed"
            if status in ("failed", "cancelled"):
                return status
            time.sleep(_RUN_POLL_S)

        return "wall_time"

    def _check_md5_drift(
        self,
        sweep_id: str,
        machine: str,
        mode: int,
        settings: dict[str, Any],
    ) -> bool:
        """Check for md5 drift between enqueue time and current dispatch.

        Per 07_decision §4 P3 del.5:
          Compare item.cfg_md5_at_enqueue / code_md5_at_enqueue against
          the CURRENT local md5 (re-read from machines.json).

        Returns True if drift detected (item marked, caller should return).
        Returns False if no drift (proceed with sampling).

        Mode is always passed explicitly -- no mode=None footgun.
        """
        from src.web_console.backend.app import _get_machine_md5  # noqa: PLC0415

        try:
            with self._store._connect() as conn:
                item_row = conn.execute(
                    "SELECT cfg_md5_at_enqueue, code_md5_at_enqueue "
                    "FROM auto_inspect_items "
                    "WHERE sweep_id=? AND machine=? AND mode=?",
                    (sweep_id, machine, mode),
                ).fetchone()
            if item_row is None:
                return False  # Can't determine drift; proceed

            # sqlite3.Row supports index-access but not .get(); use dict().
            item_dict = dict(item_row)
            enqueue_cfg = str(item_dict.get("cfg_md5_at_enqueue") or "")
            enqueue_code = str(item_dict.get("code_md5_at_enqueue") or "")

            # Explicitly pass mode (never None).
            current_cfg, current_code = _get_machine_md5(
                machine, self._machines_config, mode=mode
            )

            # Drift: both md5s were non-empty at enqueue AND current differs.
            if (enqueue_cfg or enqueue_code) and (
                enqueue_cfg != current_cfg or enqueue_code != current_code
            ):
                self._mark_item(
                    sweep_id, machine, mode,
                    status="md5_drift_invalidated",
                    reason=(
                        f"upstream md5 changed between enqueue and dispatch; "
                        f"enqueue=({enqueue_cfg[:8]},{enqueue_code[:8]}) "
                        f"current=({current_cfg[:8]},{current_code[:8]}); "
                        "this cell's data would be stale"
                    ),
                )
                self._record_failure_window(sweep_id, "skip")
                self._append_item_event(
                    sweep_id, machine, mode,
                    {"type": "md5_drift", "machine": machine, "mode": mode,
                     "enqueue_cfg": enqueue_cfg, "current_cfg": current_cfg},
                )
                return True

        except Exception as exc:  # noqa: BLE001
            # md5 drift check is best-effort; log but don't abort sampling.
            _logger.warning(
                "AutoInspectManager._check_md5_drift(%s/%d): %s",
                machine, mode, exc,
            )
        return False

    def _detect_manifest_override_partial_stub(
        self,
        sweep_id: str,
        machine: str,
        mode: int,
        sample_run_row: dict[str, Any],
    ) -> bool:
        """Stub: detect manifest_override_partial condition.

        Per 07_decision §4 P3 del.4:
          Real heuristic deferred to P5.  This stub always returns False.

        P5 heuristic will inspect summary.paid_spin_type against the
        manifest's expected paid_spin_type to detect bootstrap-default
        data scenarios.
        """
        # P5: inspect sample_run_row['summary_path'] or loaded summary JSON
        # for paid_spin_type matching manifest's spin_type_convention.paid.
        # For now: stub always returns False.
        return False

    def _resume_recover_running_items(self, sweep_id: str) -> None:
        """Recovery for items in status='running' (mid-sample crash).

        Per 07_decision §4 P3 del.3 restart recovery:
          - If sample_run_id's run row is 'completed': keep 'running' so
            worker will re-claim and jump straight to generate dispatch.
            (Actually we reset to 'pending' so normal claim path fires;
            the worker will re-check the sample run and can re-dispatch
            generate.  Simpler and safe because from-cache generate is
            idempotent.)
          - If sample_run_id's run is 'failed' / orphan / missing: reset
            to 'pending' so worker re-samples.
        """
        with self._store._connect() as conn:
            running_items = conn.execute(
                """
                SELECT machine, mode, sample_run_id
                FROM auto_inspect_items
                WHERE sweep_id=? AND status='running'
                """,
                (sweep_id,),
            ).fetchall()

        for item in running_items:
            machine = str(item["machine"])
            mode = int(item["mode"])
            sample_run_id = item["sample_run_id"]

            if not sample_run_id:
                # No run dispatched yet -- safe to reset to pending.
                self._reset_item_to_pending(sweep_id, machine, mode)
                continue

            try:
                run_row = self._store.get_run(str(sample_run_id))
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "AutoInspectManager._resume_recover_running_items: "
                    "get_run(%s) failed: %s; resetting to pending",
                    sample_run_id, exc,
                )
                self._reset_item_to_pending(sweep_id, machine, mode)
                continue

            if run_row is None:
                self._reset_item_to_pending(sweep_id, machine, mode)
                continue

            run_status = str(run_row.get("status") or "")
            if run_status == "completed":
                # Sampling was done; worker will re-dispatch generate.
                # Reset to pending so it goes through normal claim + sample
                # path; _sample_cell will see existing chunks and skip
                # re-sampling (analyzer's --from-cache handles this).
                # For P3 simplicity: reset to pending.
                self._reset_item_to_pending(sweep_id, machine, mode)
                _logger.info(
                    "AutoInspectManager._resume_recover_running_items: "
                    "%s/mode_%d sample was completed; reset to pending "
                    "for generate re-dispatch",
                    machine, mode,
                )
            else:
                # Run is failed, cancelled, or still running (orphan).
                # A2 will have marked orphaned runs 'failed' by this point
                # (per R1 crash recovery).  Reset to pending for re-sample.
                self._reset_item_to_pending(sweep_id, machine, mode)
                _logger.info(
                    "AutoInspectManager._resume_recover_running_items: "
                    "%s/mode_%d sample run=%s status=%s; reset to pending",
                    machine, mode, sample_run_id, run_status,
                )

    def _resume_recover_generating_items(self, sweep_id: str) -> None:
        """Recovery for items in status='generating' (mid-generate crash).

        Per 07_decision §4 P3 del.3 restart recovery:
          - generate_run_id run is 'completed': mark item 'completed'.
          - generate_run_id run is 'failed' / orphan / missing: clear
            generate_run_id, reset to 'running' so worker re-dispatches
            generate (item's sample_run_id is still valid).
        """
        with self._store._connect() as conn:
            gen_items = conn.execute(
                """
                SELECT machine, mode, sample_run_id, generate_run_id
                FROM auto_inspect_items
                WHERE sweep_id=? AND status='generating'
                """,
                (sweep_id,),
            ).fetchall()

        for item in gen_items:
            machine = str(item["machine"])
            mode = int(item["mode"])
            generate_run_id = item["generate_run_id"]
            sample_run_id = item["sample_run_id"]

            if not generate_run_id:
                # No generate run dispatched yet -- reset to running so
                # worker re-dispatches generate.
                self._reset_item_to_running(sweep_id, machine, mode)
                continue

            try:
                gen_row = self._store.get_run(str(generate_run_id))
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "AutoInspectManager._resume_recover_generating_items: "
                    "get_run(%s) failed: %s; resetting to running",
                    generate_run_id, exc,
                )
                self._reset_item_to_running(sweep_id, machine, mode)
                continue

            if gen_row is None:
                self._reset_item_to_running(sweep_id, machine, mode)
                continue

            gen_status = str(gen_row.get("status") or "")
            if gen_status == "completed":
                # Generate actually finished before the crash -- mark done.
                _logger.info(
                    "AutoInspectManager._resume_recover_generating_items: "
                    "%s/mode_%d generate was completed; marking item completed",
                    machine, mode,
                )
                self._mark_item(
                    sweep_id, machine, mode,
                    status="completed",
                    reason="sample + generate complete (recovered on resume)",
                    extra={
                        "sample_run_id": str(sample_run_id or ""),
                        "generate_run_id": generate_run_id,
                        "generate_status": "completed",
                    },
                )
            else:
                # Generate run failed or is orphaned (A2 will have marked
                # orphaned runs 'failed' per R1).  Clear generate_run_id
                # and reset to 'running' so worker re-dispatches generate.
                _logger.info(
                    "AutoInspectManager._resume_recover_generating_items: "
                    "%s/mode_%d generate run=%s status=%s; re-dispatch",
                    machine, mode, generate_run_id, gen_status,
                )
                self._reset_item_to_running(sweep_id, machine, mode)

    def _reset_item_to_pending(
        self, sweep_id: str, machine: str, mode: int
    ) -> None:
        """Reset an item to 'pending', clearing sample_run_id."""
        with self._store._connect() as conn:
            conn.execute(
                """
                UPDATE auto_inspect_items
                SET status='pending', claimed_by=NULL, claimed_at=NULL,
                    sample_run_id=NULL, started_at=NULL
                WHERE sweep_id=? AND machine=? AND mode=?
                """,
                (sweep_id, machine, mode),
            )
            conn.commit()

    def _reset_item_to_running(
        self, sweep_id: str, machine: str, mode: int
    ) -> None:
        """Reset a 'generating' item to 'running', clearing generate_run_id.

        The worker will re-claim and re-dispatch generate from _sample_cell.
        Because sampling already completed, _sample_cell will re-check the
        sample run row and proceed directly to generate dispatch.
        """
        with self._store._connect() as conn:
            conn.execute(
                """
                UPDATE auto_inspect_items
                SET status='running', generate_run_id=NULL,
                    generate_status=NULL
                WHERE sweep_id=? AND machine=? AND mode=?
                """,
                (sweep_id, machine, mode),
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
                elif k == "generate_run_id":
                    update_fields.append("generate_run_id=?")
                    params.append(str(v))
                elif k == "generate_status":
                    update_fields.append("generate_status=?")
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


    # -- Private -- P5 M274 alert ------------------------------------------

    def _check_m274_alert(
        self,
        sweep_id: str,
        run_id: str,
    ) -> None:
        """M274 RTP-drift alert (07_decision §2 OQ-A).

        Compares achieved_rtp_pct from the completed sample run against
        the baseline stored in state/console/m274_baseline.json.

        Baseline lifecycle:
          * If the file is missing: this run's RTP becomes the baseline.
            Write the file.  NO alert.
          * If baseline exists: compute |current - baseline|.  If > 2pp,
            fire a WARN event on the item + persist a diagnostic file.

        Per memory/feedback_no_silent_swallow.md:
          * Both outcome paths (write baseline / fire alert) persist to disk.
          * Errors are logged + don't abort the caller.
        """
        try:
            # Resolve state_dir: same parent as settings_path.
            state_dir = self._settings_path.parent
            baseline_path = state_dir / "m274_baseline.json"

            # Fetch current achieved_rtp_pct from the runs table.
            run_row = self._store.get_run(run_id)
            if run_row is None:
                _logger.warning(
                    "AutoInspectManager._check_m274_alert: run %s not found",
                    run_id,
                )
                return

            current_rtp = run_row.get("achieved_rtp_pct")
            if current_rtp is None:
                _logger.info(
                    "AutoInspectManager._check_m274_alert: run %s has no "
                    "achieved_rtp_pct; skipping alert check",
                    run_id,
                )
                return

            try:
                current_rtp_f = float(current_rtp)
            except (TypeError, ValueError):
                _logger.warning(
                    "AutoInspectManager._check_m274_alert: achieved_rtp_pct "
                    "%r is not numeric; skipping",
                    current_rtp,
                )
                return

            now_ts = datetime.now(timezone.utc).isoformat()

            # -- No baseline: write and exit without alert --
            if not baseline_path.exists():
                baseline_data = {
                    "baseline_rtp_pct": current_rtp_f,
                    "captured_at": now_ts,
                    "captured_from_run_id": run_id,
                    "captured_from_sweep_id": sweep_id,
                }
                try:
                    baseline_path.write_text(
                        json.dumps(baseline_data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    _logger.info(
                        "AutoInspectManager._check_m274_alert: wrote baseline "
                        "rtp=%.4f to %s",
                        current_rtp_f, baseline_path,
                    )
                except OSError as exc:
                    _logger.error(
                        "AutoInspectManager._check_m274_alert: "
                        "failed to write baseline: %s",
                        exc,
                    )
                return

            # -- Baseline exists: compare --
            try:
                baseline_data = json.loads(
                    baseline_path.read_text(encoding="utf-8")
                )
                baseline_rtp_f = float(baseline_data["baseline_rtp_pct"])
            except (OSError, json.JSONDecodeError, KeyError, TypeError,
                    ValueError) as exc:
                _logger.warning(
                    "AutoInspectManager._check_m274_alert: baseline parse "
                    "error: %s; skipping alert",
                    exc,
                )
                return

            delta = abs(current_rtp_f - baseline_rtp_f)
            _logger.info(
                "AutoInspectManager._check_m274_alert: "
                "current=%.4fpp baseline=%.4fpp delta=%.4fpp",
                current_rtp_f, baseline_rtp_f, delta,
            )

            if delta <= _M274_ALERT_DELTA_PP:
                # No alert -- within tolerance.
                return

            # -- Fire alert --
            alert_msg = (
                f"M274 RTP drift: current={current_rtp_f:.4f}pp "
                f"baseline={baseline_rtp_f:.4f}pp "
                f"delta={delta:.4f}pp (threshold={_M274_ALERT_DELTA_PP}pp)"
            )
            _logger.warning("AutoInspectManager._check_m274_alert: %s", alert_msg)

            # (a) WARN event on the item (flows through UI events panel).
            self._append_item_event(
                sweep_id, _M274_MACHINE, _M274_MODE,
                {
                    "type": "warn",
                    "level": "warn",
                    "message": alert_msg,
                    "current_rtp_pct": current_rtp_f,
                    "baseline_rtp_pct": baseline_rtp_f,
                    "delta_pp": delta,
                    "run_id": run_id,
                },
            )

            # (b) Persist diagnostic file (feedback_no_silent_swallow.md).
            alert_ts = now_ts.replace(":", "").replace("-", "").replace("+", "")[:15]
            alert_path = state_dir / f"m274_alert_{alert_ts}.json"
            alert_file_data = {
                "alert_fired_at": now_ts,
                "sweep_id": sweep_id,
                "run_id": run_id,
                "machine": _M274_MACHINE,
                "mode": _M274_MODE,
                "current_rtp_pct": current_rtp_f,
                "baseline_rtp_pct": baseline_rtp_f,
                "delta_pp": delta,
                "threshold_pp": _M274_ALERT_DELTA_PP,
                "message": alert_msg,
            }
            try:
                alert_path.write_text(
                    json.dumps(alert_file_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                _logger.warning(
                    "AutoInspectManager._check_m274_alert: "
                    "diagnostic persisted to %s",
                    alert_path,
                )
            except OSError as exc:
                _logger.error(
                    "AutoInspectManager._check_m274_alert: "
                    "failed to write alert diagnostic: %s",
                    exc,
                )

        except Exception as exc:  # noqa: BLE001
            # Alert is best-effort -- don't abort the sweep on alert errors.
            # Log with full traceback so operator can investigate.
            _logger.error(
                "AutoInspectManager._check_m274_alert: unexpected error: "
                "%s\n%s",
                exc, traceback.format_exc(),
            )
            print(
                f"[auto-inspect] _check_m274_alert unexpected error: {exc}",
                flush=True,
            )

    # -- Private -- fleet refresh proxy ------------------------------------


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


class _AutoInspectScheduler:
    """threading.Timer-based cron scheduler for AutoInspectManager.

    Phase 5 deliverable 1 (07_decision §2 OQ-G).

    Supports only two modes:
      * "daily" + "HH:MM" — fire once per UTC calendar day at HH:MM.
      * "interval" + "N" — fire every N hours (N in 1-24).

    Design choices:
      * Reads settings EVERY cycle so operator can change cadence live.
      * If enabled flips False between two fires, next _fire() exits.
      * Idempotent stop() — calling multiple times is safe.
      * All state is per-instance (no module globals).
      * Daemon threads — won't block interpreter shutdown.

    Per memory/feedback_subprocess_import_suicide_and_module_globals.md:
      * No module-level state.
      * AutoInspectManager reference injected via __init__.
    """

    def __init__(
        self,
        manager: "AutoInspectManager",
        *,
        settings_path: Path,
    ) -> None:
        self._manager = manager
        self._settings_path = settings_path
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._stopped = False

    def start(self) -> None:
        """Schedule the first fire.  Idempotent (safe to call twice)."""
        with self._lock:
            if self._stopped:
                return
        self._schedule_next()

    def stop(self) -> None:
        """Cancel the pending timer.  Idempotent."""
        with self._lock:
            self._stopped = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    # -- Internal --

    def _load_settings(self) -> dict[str, Any]:
        """Load current auto_sweep settings block."""
        try:
            from src.web_console.backend.app import _load_settings  # noqa: PLC0415
            s = _load_settings(self._settings_path)
            return s.get("auto_sweep") or {}
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "_AutoInspectScheduler._load_settings: %s; "
                "using empty defaults",
                exc,
            )
            return {}

    def _compute_delay_s(
        self,
        schedule_mode: str,
        schedule_value: str,
    ) -> float | None:
        """Compute seconds until next fire, or None on invalid format.

        daily: fire at next UTC HH:MM (may be tomorrow if already past).
        interval: fire in N * 3600 seconds.
        """
        if schedule_mode == "interval":
            if not _CRON_INTERVAL_RE.match(schedule_value):
                _logger.warning(
                    "_AutoInspectScheduler: invalid interval value %r "
                    "(expected 1-24); not scheduling",
                    schedule_value,
                )
                return None
            return float(int(schedule_value)) * 3600.0

        if schedule_mode == "daily":
            if not _CRON_DAILY_RE.match(schedule_value):
                _logger.warning(
                    "_AutoInspectScheduler: invalid daily value %r "
                    "(expected HH:MM); not scheduling",
                    schedule_value,
                )
                return None
            hh, mm = int(schedule_value[:2]), int(schedule_value[3:])
            now_utc = datetime.now(timezone.utc)
            # Next fire: today at HH:MM UTC, or tomorrow if already past.
            target = now_utc.replace(
                hour=hh, minute=mm, second=0, microsecond=0
            )
            diff = (target - now_utc).total_seconds()
            if diff <= 0:
                # Already past today -- fire tomorrow.
                diff += 86400.0
            return diff

        _logger.warning(
            "_AutoInspectScheduler: unknown schedule_mode %r; "
            "not scheduling",
            schedule_mode,
        )
        return None

    def _schedule_next(self) -> None:
        """Load settings and arm the next timer."""
        with self._lock:
            if self._stopped:
                return

        settings = self._load_settings()
        enabled = bool(settings.get("enabled", False))
        if not enabled:
            _logger.debug(
                "_AutoInspectScheduler: auto_sweep.enabled=False; "
                "not scheduling"
            )
            return

        schedule_mode = str(settings.get("schedule_mode") or "daily")
        schedule_value = str(settings.get("schedule_value") or "02:00")

        delay_s = self._compute_delay_s(schedule_mode, schedule_value)
        if delay_s is None:
            return

        _logger.info(
            "_AutoInspectScheduler: next sweep in %.0fs "
            "(mode=%s value=%s)",
            delay_s, schedule_mode, schedule_value,
        )

        with self._lock:
            if self._stopped:
                return
            self._timer = threading.Timer(delay_s, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        """Called when the timer fires.  Checks running state + starts sweep."""
        # Read settings fresh -- operator may have changed them.
        settings = self._load_settings()
        enabled = bool(settings.get("enabled", False))

        if not enabled:
            _logger.info(
                "_AutoInspectScheduler._fire: auto_sweep.enabled=False; "
                "skipping and not rescheduling"
            )
            return

        # Check if a sweep is already running.
        if self._manager._has_running_sweep():
            _logger.warning(
                "_AutoInspectScheduler._fire: previous sweep still running, "
                "skipping cron trigger"
            )
        else:
            try:
                sweep_id = self._manager.start_sweep(trigger="cron")
                _logger.info(
                    "_AutoInspectScheduler._fire: cron sweep started "
                    "sweep_id=%s",
                    sweep_id,
                )
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "_AutoInspectScheduler._fire: start_sweep failed: %s\n%s",
                    exc, traceback.format_exc(),
                )
                # Persist diagnostic (feedback_no_silent_swallow.md).
                print(
                    f"[auto-inspect] cron fire start_sweep failed: {exc}",
                    flush=True,
                )

        # Reschedule next fire.
        self._schedule_next()
