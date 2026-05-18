"""ConcurrencyLimiter — Semaphore-based cap on concurrent analyzer subprocesses.

Phase 2 of the deploy migration (2026-05-17).  Replaces the v1 token-bucket
approach (W3 critic CI-2: token bucket governs launch *rate*, not steady-state
*concurrency*; the wrong mechanism for the H4 gap).

Design source: session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.5
Decision:      session_artifacts/_arch/deploy/07_deploy_decision.md §3.1 INV-10

Defaults: n_slots=5, foreground_reserve=2.
  * 5 × 8 concurrent upstream connections = 40 max per LAN client.
  * 2 foreground-reserved slots mean ad-hoc fetch always get priority
    over background full-fleet-refresh workers.

Per memory/feedback_subprocess_import_suicide_and_module_globals.md:
  * No import-time side effects.
  * ConcurrencyLimiter() is constructed inside create_app() — one per app
    instance.
"""

from __future__ import annotations

import threading
from typing import Callable


class ConcurrencyLimiter:
    """Semaphore-based concurrency cap with foreground/background priority.

    Foreground callers (priority="foreground") can consume any slot up to
    ``n_slots``.  Background callers (priority="background") can consume a
    slot only when ``active_count < n_slots - foreground_reserve``, so the
    last ``foreground_reserve`` slots are always available for foreground
    requests.

    Example with defaults (n_slots=5, foreground_reserve=2):
      * active_count=0..2  — both foreground and background can acquire.
      * active_count=3     — background is blocked (would leave only 2 =
                             foreground_reserve slots free); foreground can
                             still acquire.
      * active_count=4..5  — only foreground can acquire.

    Thread-safety: all mutations are serialised through ``_lock``.
    The semaphore provides the actual blocking primitive; ``_active_count``
    and the threshold check are guarded by ``_lock``.
    """

    def __init__(
        self,
        n_slots: int = 5,
        foreground_reserve: int = 2,
    ) -> None:
        if n_slots < 1:
            raise ValueError(f"n_slots must be >= 1, got {n_slots}")
        if foreground_reserve < 0 or foreground_reserve >= n_slots:
            raise ValueError(
                f"foreground_reserve must be in [0, n_slots), "
                f"got {foreground_reserve} (n_slots={n_slots})"
            )
        self._n_slots: int = n_slots
        self._foreground_reserve: int = foreground_reserve
        self._semaphore: threading.Semaphore = threading.Semaphore(n_slots)
        self._lock: threading.Lock = threading.Lock()
        self._active_count: int = 0

    @property
    def active_count(self) -> int:
        """Current number of acquired slots (thread-safe snapshot)."""
        with self._lock:
            return self._active_count

    def acquire(
        self,
        priority: str = "foreground",
        timeout: float | None = 30.0,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> bool:
        """Attempt to acquire one slot.

        ``priority="foreground"``:
          * Blocks up to ``timeout`` seconds (default 30 s) waiting for a
            free slot.  Returns False on timeout.
          * ``cancel_flag`` is ignored for foreground (no fleet-cancellation
            concept).

        ``priority="background"``:
          * Blocks until ``active_count < n_slots - foreground_reserve``
            AND a semaphore slot is available.
          * ``cancel_flag()`` is polled in a loop; returns False immediately
            when it fires.
          * ``timeout`` is ignored for background (cancel-driven exit only).
          * Uses a 1-second poll interval — precise enough for fleet-refresh
            cancellation UX without hammering the lock.

        Returns True on success (slot acquired; caller MUST call release()).
        Returns False if timed out (foreground) or cancelled (background).
        """
        if priority == "foreground":
            # Try to acquire the semaphore with a timeout.
            timeout_val = timeout if timeout is not None else 30.0
            acquired = self._semaphore.acquire(blocking=True, timeout=timeout_val)
            if not acquired:
                return False
            with self._lock:
                self._active_count += 1
            return True

        else:
            # Background: poll until below threshold and a slot is free.
            bg_threshold = self._n_slots - self._foreground_reserve
            while True:
                # Check cancel flag first.
                if cancel_flag is not None and cancel_flag():
                    return False
                # Check if we're below the background threshold.
                with self._lock:
                    below_threshold = self._active_count < bg_threshold
                if below_threshold:
                    # Try a non-blocking semaphore acquire.
                    acquired = self._semaphore.acquire(blocking=False)
                    if acquired:
                        # Re-check threshold under lock to avoid TOCTOU.
                        with self._lock:
                            if self._active_count < bg_threshold:
                                self._active_count += 1
                                return True
                            # Another thread snuck in; release and retry.
                        self._semaphore.release()
                # Wait a short interval before retrying.
                import time  # local import; no top-level side effect
                time.sleep(1.0)

    def release(self) -> None:
        """Release one previously acquired slot.

        Defensive: if called more times than acquire succeeded, the
        semaphore is incremented but _active_count floor-clamped to 0
        to avoid negative counts.
        """
        self._semaphore.release()
        with self._lock:
            if self._active_count > 0:
                self._active_count -= 1
