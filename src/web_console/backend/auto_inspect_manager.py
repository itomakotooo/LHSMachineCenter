"""AutoInspectManager — skeleton class for the auto-inspect sweep feature.

Phase 1 (Foundation) — public interface + DB-scan for restart-recovery only.
Phases 2-5 land in subsequent commits per 07_decision.md §4.

Design: session_artifacts/_arch/auto_inspect/07_decision.md §1-§4
Decision rationale: 07_decision.md §2 MF-1..MF-5, V1..V3

Per memory/feedback_subprocess_import_suicide_and_module_globals.md:
  * No import-time side effects.  No module-level state beyond constants.
  * AutoInspectManager() is constructed inside create_app() so each app
    instance (prod or test-isolated) has its own manager instance.
  * All paths (rawdata_root, machines_config, settings_path) are injected
    via __init__ — NEVER read from module-level globals.

Per memory/feedback_no_silent_swallow.md:
  * Every error path either raises, logs to stderr with traceback, or
    persists a diagnostic.  No bare ``except: pass``.

Per 07_decision §6 (acceptance criteria):
  * No mode=None calls to _get_machine_md5 — P1 doesn't call it at all;
    just don't introduce any such call.
  * No module-level globals introduced.
  * MF-1: __init__ must NOT call _do_refresh_machines_md5 synchronously;
    only pure SQLite in __init__.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Avoid circular imports at runtime — types only used for annotation.
    from src.web_console.backend.app import StateStore, RunManager
    from src.web_console.backend.cell_lock_registry import CellLockRegistry
    from src.web_console.backend.rate_limiter import ConcurrencyLimiter

_logger = logging.getLogger(__name__)


class AutoInspectManager:
    """Background sweep manager that discovers stale cells and resamples them.

    Phase 1 only implements:
      * ``__init__``: store refs, scan persisted non-terminal sweeps for
        restart-recovery (pure SQLite — no HTTP, per MF-1).
      * ``_scan_persisted_for_resume``: returns the most-recent non-terminal
        sweep_id (or None).
      * ``resume_sweep``: stub — logs and returns (P3 will fill in full
        restart-recovery logic).
      * ``start_sweep``, ``cancel_sweep``, ``get_sweep_status``,
        ``list_recent_sweeps``: raise NotImplementedError (P2).

    ``create_app`` constructs this manager after building all other managers,
    then spawns a daemon thread targeting ``resume_sweep(sweep_id)`` if
    ``_pending_resume_sweep_id`` is non-None (same pattern as
    FleetRefreshManager restart-recovery at app.py:11599-11607).
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

        All path parameters are injected — never read from module globals.
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
        # Store refs — all per-instance, no module globals.
        self._store = store
        self._run_manager = run_manager
        self._registry = registry
        self._limiter = limiter
        self._settings_path = settings_path
        self._machines_config = machines_config
        self._rawdata_root = rawdata_root

        # Scan persisted non-terminal sweeps for restart-recovery.
        # Pure SQLite — no HTTP, no upstream calls (MF-1 invariant).
        self._pending_resume_sweep_id: str | None = (
            self._scan_persisted_for_resume()
        )

    # ── Public interface (07_decision §1 + V3) ────────────────────────────

    def start_sweep(self, trigger: str = "manual") -> str:
        """Start a new sweep.  Returns sweep_id.

        409 (raise HTTPException) if:
          * A sweep is already active (MF-3 mutex — one sweep at a time).
          * Fleet refresh queue is running (MF-3 — mutually exclusive).

        Phase 1: raises NotImplementedError.  Full impl lands in P2.
        The 409 guards described above are also P2 — noted here so the
        impl-critic can verify the spec intent is captured.
        """
        raise NotImplementedError("P2")

    def cancel_sweep(self, sweep_id: str) -> bool:
        """Cancel a running sweep.  Returns True if successfully cancelled.

        Phase 1: raises NotImplementedError.  Full impl lands in P2.
        """
        raise NotImplementedError("P2")

    def get_sweep_status(self, sweep_id: str) -> dict[str, Any] | None:
        """Return sweep progress dict or None if sweep_id not found.

        Phase 1: raises NotImplementedError.  Full impl lands in P2.
        """
        raise NotImplementedError("P2")

    def list_recent_sweeps(self, limit: int = 30) -> list[dict[str, Any]]:
        """Return the most recent ``limit`` sweeps, newest first.

        Phase 1: raises NotImplementedError.  Full impl lands in P2.
        """
        raise NotImplementedError("P2")

    def resume_sweep(self, sweep_id: str) -> None:
        """Resume a sweep that was interrupted by a console restart.

        Called from create_app's startup daemon thread when
        ``_pending_resume_sweep_id`` is non-None.

        Phase 1: log only — no-op.  Full restart-recovery impl lands in P3.
        """
        _logger.info(
            "AutoInspectManager.resume_sweep: sweep_id=%s detected on startup; "
            "restart-recovery not yet implemented (P3).  Sweep remains in "
            "non-terminal state in DB until P3 lands.",
            sweep_id,
        )
        print(
            f"[auto-inspect] resume_sweep({sweep_id!r}) called — P3 stub, no-op.",
            flush=True,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    def _scan_persisted_for_resume(self) -> str | None:
        """Return the sweep_id of the most-recent non-terminal sweep, or None.

        Non-terminal sweep statuses: 'scanning', 'sampling', 'finalizing'.
        'pending' is also non-terminal but is not used by the sweep state
        machine (sweeps start in 'scanning' directly).

        Pure SQLite read — no HTTP, no upstream calls, safe in __init__.

        Returns None if:
          * No non-terminal sweeps exist.
          * The auto_inspect_sweeps table doesn't exist yet (pre-Phase-4 DB
            — sqlite3.OperationalError is caught and logged, not raised).
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
                        "AutoInspectManager: found non-terminal sweep %s on startup; "
                        "will resume after create_app finishes.",
                        sweep_id,
                    )
                    return sweep_id
                return None
        except sqlite3.OperationalError as exc:
            # Table doesn't exist yet (pre-Phase-4 DB from before this
            # migration ran).  This is normal on first startup after deploy.
            _logger.debug(
                "AutoInspectManager._scan_persisted_for_resume: OperationalError "
                "(likely pre-Phase-4 DB, no auto_inspect_sweeps table yet): %s",
                exc,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            # Unexpected error — log with traceback but don't crash startup.
            import traceback as _tb
            _logger.error(
                "AutoInspectManager._scan_persisted_for_resume: unexpected error: %s\n%s",
                exc,
                _tb.format_exc(),
            )
            print(
                f"[auto-inspect] _scan_persisted_for_resume unexpected error: {exc}",
                flush=True,
            )
            return None
