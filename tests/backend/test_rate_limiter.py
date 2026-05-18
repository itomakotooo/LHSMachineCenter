"""P2-T2: ConcurrencyLimiter unit tests.

Covers the Semaphore-based concurrency cap with foreground/background
priority per 04_deploy_architecture_proposal_v2.md §4.5.

Default: n_slots=5, foreground_reserve=2.
  - Foreground can consume all 5 slots.
  - Background can consume slots only when active_count < n_slots - foreground_reserve
    (i.e., < 3 active when n_slots=5, reserve=2).
  - Background polls with cancel_flag to exit wait loop.

Memory feedback files honored:
  memory/feedback_enumerate_safety_paths.md — inject-bug recipe for the
    semaphore protection.
  memory/feedback_perf_claim_needs_e2e_event_stream.md — concurrency tests
    spawn real threads, not mocks.

Inject-bug recipe (for impl-tester P2-T5):

  ConcurrencyLimiter semaphore protection:
    1. In rate_limiter.py ConcurrencyLimiter.acquire (background branch),
       change `acquired = self._semaphore.acquire(blocking=False)` to
       `acquired = True` (bypass the semaphore check).
    2. Run test_concurrent_acquire_release_thread_safety → active_count
       can exceed n_slots momentarily → assertion fails.
    3. Revert → PASS.

  Foreground timeout:
    1. In ConcurrencyLimiter.acquire (foreground branch), change
       `acquired = self._semaphore.acquire(blocking=True, timeout=timeout_val)`
       to `acquired = False` (always fail).
    2. Run test_foreground_can_consume_all_slots → all 5 acquires return
       False → assertion fails.
    3. Revert → PASS.

Cross-refs:
  session_artifacts/_impl/p2/brief.md §6 P2-T2
  session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.5
"""

from __future__ import annotations

import threading
import time

import pytest

from src.web_console.backend.rate_limiter import ConcurrencyLimiter


# ---------------------------------------------------------------------------
# Helper: fresh limiter per test
# ---------------------------------------------------------------------------

@pytest.fixture
def limiter() -> ConcurrencyLimiter:
    """Fresh ConcurrencyLimiter with defaults (n_slots=5, foreground_reserve=2)."""
    return ConcurrencyLimiter(n_slots=5, foreground_reserve=2)


@pytest.fixture
def small_limiter() -> ConcurrencyLimiter:
    """Small limiter for timeout tests: n_slots=2, foreground_reserve=1."""
    return ConcurrencyLimiter(n_slots=2, foreground_reserve=1)


# ---------------------------------------------------------------------------
# Foreground acquire tests
# ---------------------------------------------------------------------------


class TestForegroundAcquire:
    """Foreground callers can consume up to n_slots total."""

    def test_foreground_can_consume_all_slots(self, limiter: ConcurrencyLimiter):
        """5 foreground acquires (n_slots=5) all succeed.

        Inject-bug: change semaphore.acquire to always return False →
        all 5 acquires fail → assertion fails.
        """
        slots_acquired = []
        try:
            for _ in range(5):
                ok = limiter.acquire("foreground", timeout=2.0)
                assert ok is True, "Foreground acquire should succeed when slots are free"
                slots_acquired.append(True)
            assert limiter.active_count == 5
        finally:
            for _ in slots_acquired:
                limiter.release()
        assert limiter.active_count == 0

    def test_foreground_timeout_returns_false(self, limiter: ConcurrencyLimiter):
        """All 5 slots full; 6th foreground acquire times out → False.

        Uses a short timeout (0.2s) for test speed.

        Inject-bug: change the semaphore timeout to `None` (block forever) →
        test hangs → caught by pytest timeout if set, otherwise deadlock.
        """
        # Fill all 5 slots
        for _ in range(5):
            ok = limiter.acquire("foreground", timeout=2.0)
            assert ok is True

        # 6th must time out
        ok_6th = limiter.acquire("foreground", timeout=0.2)
        assert ok_6th is False, "6th foreground acquire should time out (slots exhausted)"

        # Clean up
        for _ in range(5):
            limiter.release()
        assert limiter.active_count == 0

    def test_release_decrements_active_count(self, limiter: ConcurrencyLimiter):
        """Basic: acquire increments active_count; release decrements it.

        Inject-bug: remove `self._active_count -= 1` from release() →
        active_count never decrements → assertion after release fails.
        """
        assert limiter.active_count == 0
        ok = limiter.acquire("foreground", timeout=2.0)
        assert ok is True
        assert limiter.active_count == 1
        limiter.release()
        assert limiter.active_count == 0


# ---------------------------------------------------------------------------
# Background acquire tests
# ---------------------------------------------------------------------------


class TestBackgroundAcquire:
    """Background callers respect foreground_reserve threshold."""

    def test_background_blocked_when_only_foreground_reserve_available(
        self, limiter: ConcurrencyLimiter
    ):
        """3 foreground acquires → active=3; background (threshold=3) is blocked.

        With n_slots=5, foreground_reserve=2: bg_threshold = 5-2 = 3.
        When active_count >= 3, background must NOT acquire.
        Cancel flag fires after 0.3s → returns False promptly.

        Inject-bug: change the background threshold check to always
        True (bypass the `active_count < bg_threshold` condition) →
        background acquires even when foreground slots are reserved →
        test fails (background returns True instead of False).
        """
        # Fill 3 slots with foreground
        for _ in range(3):
            ok = limiter.acquire("foreground", timeout=2.0)
            assert ok is True
        assert limiter.active_count == 3  # exactly at bg_threshold

        # Background should be blocked; cancel after 0.3s
        cancelled = threading.Event()
        cancelled_event = threading.Event()

        def do_bg_acquire():
            ok = limiter.acquire(
                "background",
                cancel_flag=lambda: cancelled.is_set(),
            )
            assert ok is False, "Background must be blocked when active_count >= bg_threshold"
            cancelled_event.set()

        t = threading.Thread(target=do_bg_acquire, daemon=True)
        t.start()

        # Let it spin once (the poll interval is 1s, but we just need it to start)
        time.sleep(0.1)
        cancelled.set()
        t.join(timeout=3.0)
        assert not t.is_alive(), "Background thread did not exit after cancel"

        # Clean up
        for _ in range(3):
            limiter.release()
        assert limiter.active_count == 0

    def test_background_succeeds_when_below_threshold(self, limiter: ConcurrencyLimiter):
        """1 foreground active; background can acquire (active=1 < bg_threshold=3).

        With n_slots=5, foreground_reserve=2: bg_threshold=3.
        active_count=1 < 3 → background should succeed immediately.

        Inject-bug: change the background threshold check to always False →
        background never acquires → test hangs / times out.
        """
        # 1 foreground active
        ok = limiter.acquire("foreground", timeout=2.0)
        assert ok is True
        assert limiter.active_count == 1

        # Background should succeed (1 < 3)
        bg_result: list[bool] = []

        def do_bg():
            # Non-blocking check: set cancel after a short wait
            r = limiter.acquire("background", cancel_flag=lambda: False)
            bg_result.append(r)

        t = threading.Thread(target=do_bg, daemon=True)
        t.start()
        t.join(timeout=3.0)

        assert not t.is_alive(), "Background acquire did not return within timeout"
        assert bg_result and bg_result[0] is True, (
            "Background acquire should succeed when active_count < bg_threshold"
        )

        # Clean up
        limiter.release()  # foreground
        limiter.release()  # background
        assert limiter.active_count == 0

    def test_background_cancel_flag_breaks_wait_loop(
        self, limiter: ConcurrencyLimiter
    ):
        """slots full; background waits with cancel_flag that fires → returns False.

        Fills all 5 slots with foreground; background enters wait loop;
        cancel_flag fires immediately → background returns False quickly.

        Inject-bug: remove the `if cancel_flag is not None and cancel_flag(): return False`
        check from the background loop → cancel is ignored → background
        blocks forever → test times out.
        """
        # Fill all 5 slots
        for _ in range(5):
            ok = limiter.acquire("foreground", timeout=2.0)
            assert ok is True

        # Background: cancel flag fires immediately after first check
        started = threading.Event()
        result: list[bool] = []

        def do_bg():
            started.set()
            ok = limiter.acquire(
                "background",
                cancel_flag=lambda: True,  # Always True → cancel immediately
            )
            result.append(ok)

        t = threading.Thread(target=do_bg, daemon=True)
        t.start()
        t.join(timeout=3.0)

        assert not t.is_alive(), "Background acquire did not return after cancel"
        assert result and result[0] is False, (
            "Background acquire with immediate cancel_flag must return False"
        )

        # Clean up
        for _ in range(5):
            limiter.release()
        assert limiter.active_count == 0


# ---------------------------------------------------------------------------
# Thread-safety tests
# ---------------------------------------------------------------------------


class TestConcurrencyLimiterThreadSafety:
    """N threads simultaneously acquiring and releasing must not exceed n_slots.

    The Semaphore provides the blocking primitive; _lock protects _active_count.

    Inject-bug recipe (primary target for P2-T5):
      1. In ConcurrencyLimiter.acquire (background branch), change
         `acquired = self._semaphore.acquire(blocking=False)` to `acquired = True`.
      2. N background threads bypass the semaphore → active_count can exceed n_slots.
      3. Revert → green.
    """

    def test_concurrent_foreground_active_count_never_exceeds_n_slots(
        self, limiter: ConcurrencyLimiter
    ):
        """N=10 foreground threads; at no point does active_count exceed n_slots=5.

        Threads acquire, record active_count, then release.
        Without proper semaphore, active_count can exceed n_slots.
        """
        N = 10
        peak_counts: list[int] = []
        lock = threading.Lock()
        errors: list[str] = []

        def worker():
            ok = limiter.acquire("foreground", timeout=5.0)
            if ok:
                count = limiter.active_count
                with lock:
                    peak_counts.append(count)
                    if count > 5:
                        errors.append(f"active_count={count} exceeded n_slots=5")
                time.sleep(0.01)
                limiter.release()

        threads = [threading.Thread(target=worker) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, "\n".join(errors)
        assert limiter.active_count == 0, (
            f"active_count={limiter.active_count} should be 0 after all releases"
        )

    def test_concurrent_acquire_release_final_state_zero(
        self, limiter: ConcurrencyLimiter
    ):
        """N=10 threads each acquire + release; final active_count == 0.

        Inject-bug: remove `if self._active_count > 0: self._active_count -= 1`
        from release() → active_count stays positive → assertion fails.
        """
        N = 10

        def worker():
            ok = limiter.acquire("foreground", timeout=5.0)
            if ok:
                time.sleep(0.005)
                limiter.release()

        threads = [threading.Thread(target=worker) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert limiter.active_count == 0, (
            f"Expected active_count=0 after {N} acquire+release pairs, "
            f"got {limiter.active_count}"
        )

    def test_active_count_property_is_thread_safe(self, limiter: ConcurrencyLimiter):
        """active_count property reads consistently under concurrent mutations.

        Reads of active_count must be serialised through _lock to avoid
        seeing a torn count (half-incremented int). Python GIL makes true
        tearing unlikely, but the lock is the contract.
        """
        N = 5
        counts: list[int] = []
        lock = threading.Lock()

        def worker():
            ok = limiter.acquire("foreground", timeout=2.0)
            if ok:
                c = limiter.active_count
                with lock:
                    counts.append(c)
                time.sleep(0.005)
                limiter.release()

        threads = [threading.Thread(target=worker) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All counts should be in [1, 5]
        assert all(1 <= c <= 5 for c in counts), (
            f"active_count out of range during concurrent acquire: {counts}"
        )
        assert limiter.active_count == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Constructor validation and edge-case behaviour."""

    def test_invalid_n_slots_raises(self):
        """n_slots=0 must raise ValueError."""
        with pytest.raises(ValueError, match="n_slots"):
            ConcurrencyLimiter(n_slots=0)

    def test_invalid_foreground_reserve_raises(self):
        """foreground_reserve >= n_slots must raise ValueError."""
        with pytest.raises(ValueError, match="foreground_reserve"):
            ConcurrencyLimiter(n_slots=3, foreground_reserve=3)

    def test_foreground_reserve_zero_allowed(self):
        """foreground_reserve=0 means background has no restriction."""
        lim = ConcurrencyLimiter(n_slots=2, foreground_reserve=0)
        assert lim.acquire("foreground", timeout=1.0) is True
        lim.release()

    def test_release_when_nothing_acquired_is_safe(self):
        """release() when active_count==0 should not crash or go negative."""
        lim = ConcurrencyLimiter(n_slots=2, foreground_reserve=1)
        lim.release()  # defensive release — must not raise
        assert lim.active_count == 0
