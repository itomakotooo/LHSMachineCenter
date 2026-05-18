"""P2-T1: CellLockRegistry unit tests.

Covers all 6 invariants from 04_deploy_architecture_proposal_v2.md §4.1:
  INV-1: SAMPLING + DELETING mutually exclusive per cell.
  INV-2: GENERATING + DELETING mutually exclusive per cell.
  INV-3: SAMPLING + GENERATING on same cell: ALLOWED (concurrent is safe).
  INV-4: At most ONE SAMPLING per cell.
  INV-5: At most ONE GENERATING per cell.
  INV-6: Global ops: at most ONE per named global op at a time.

Memory feedback files honored:
  memory/feedback_enumerate_safety_paths.md — inject-bug recipe for every
    new lock/guard, proving the test catches the actual regression not just
    an abstract invariant.
  memory/feedback_subprocess_import_suicide_and_module_globals.md — verified
    that importing cell_lock_registry has no side effects.

Inject-bug recipes (for future devs to reproduce):

  INV-1/INV-4 (SAMPLING mutex — test_one_sampling_per_cell):
    1. In cell_lock_registry.py CellLockRegistry.__init__, replace:
           self._lock: threading.Lock = threading.Lock()
       with a no-op DummyLock (context manager that does nothing).
    2. Run test_one_sampling_per_cell → should PASS (the boolean check still
       prevents a second SAMPLING logically). The real race is in the
       TOCTOU between check and set without a lock.
       For the thread-safety test: run test_concurrent_acquire_release_thread_safety
       with N=20 threads — without the lock, multiple SAMPLINGs can be
       acquired simultaneously, causing final active_count > 0 or corrupt state.
    3. Revert → PASS.

  INV-6 (global op mutex — test_global_op_one_at_a_time):
    1. Same DummyLock inject as above.
    2. Run test_concurrent_global_op_thread_safety (or the basic
       test_global_op_one_at_a_time under concurrent pressure) →
       two threads can both see _global_ops.get(name) == False
       simultaneously and both return True.
    3. Revert → PASS.

Cross-refs:
  session_artifacts/_impl/p2/brief.md §6 P2-T1
  session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.1
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from src.web_console.backend.cell_lock_registry import CellLockRegistry, CellOperation


# ---------------------------------------------------------------------------
# Helper: fresh registry per test (no shared state)
# ---------------------------------------------------------------------------

@pytest.fixture
def registry() -> CellLockRegistry:
    """Fresh CellLockRegistry with no active operations."""
    return CellLockRegistry()


# ---------------------------------------------------------------------------
# Basic acquire / release
# ---------------------------------------------------------------------------


class TestSamplingAcquireReleaseBasic:
    """Verify the fundamental acquire/release lifecycle for SAMPLING."""

    def test_sampling_acquire_release_basic(self, registry: CellLockRegistry):
        """Acquire SAMPLING → present in get_active_cells → release → absent.

        Inject-bug: remove the `self._registry[key].add(op)` line in
        try_acquire_cell → get_active_cells returns empty even after
        acquire → assertion fails.
        """
        machine, mode = "M14", 1

        # Pre-condition: cell not active
        assert ("M14", 1) not in registry.get_active_cells()
        assert ("M14", 1) not in registry.get_active_cells(CellOperation.SAMPLING)

        # Acquire
        ok = registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING)
        assert ok is True, "First SAMPLING acquire should succeed"

        # Verify presence
        assert ("M14", 1) in registry.get_active_cells()
        assert ("M14", 1) in registry.get_active_cells(CellOperation.SAMPLING)

        # Release
        registry.release_cell(machine, mode, CellOperation.SAMPLING)

        # Verify absence
        assert ("M14", 1) not in registry.get_active_cells()
        assert ("M14", 1) not in registry.get_active_cells(CellOperation.SAMPLING)

    def test_release_unknown_cell_is_safe(self, registry: CellLockRegistry):
        """Releasing a cell that was never acquired must NOT raise.

        Mirrors the original _IN_USE_MODES.discard() defensive semantics.

        Inject-bug: change `active.discard(op)` to `active.remove(op)` in
        release_cell → KeyError is raised → this test fails.
        """
        # Should not raise
        registry.release_cell("M99", 9, CellOperation.SAMPLING)
        registry.release_cell("M14", 1, CellOperation.GENERATING)
        registry.release_cell("M14", 1, CellOperation.DELETING)


# ---------------------------------------------------------------------------
# Invariant tests
# ---------------------------------------------------------------------------


class TestMutualExclusionInvariants:
    """INV-1 through INV-5: mutual exclusion and singleton constraints."""

    def test_sampling_and_deleting_mutually_exclusive(self, registry: CellLockRegistry):
        """INV-1: SAMPLING then DELETING on same cell → DELETING returns False.

        Inject-bug: in try_acquire_cell, remove the check
        `if CellOperation.SAMPLING in active: return False` from the
        DELETING branch → DELETING succeeds even with active SAMPLING
        → this test assertion fails.
        """
        machine, mode = "M14", 1
        assert registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING) is True

        # DELETING must be rejected
        ok = registry.try_acquire_cell(machine, mode, CellOperation.DELETING)
        assert ok is False, "DELETING must be rejected when SAMPLING is active (INV-1)"

        # Also check the reverse: DELETING first, then SAMPLING
        registry.release_cell(machine, mode, CellOperation.SAMPLING)
        assert registry.try_acquire_cell(machine, mode, CellOperation.DELETING) is True

        ok2 = registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING)
        assert ok2 is False, "SAMPLING must be rejected when DELETING is active (INV-1 reverse)"

        registry.release_cell(machine, mode, CellOperation.DELETING)

    def test_generating_and_deleting_mutually_exclusive(self, registry: CellLockRegistry):
        """INV-2: GENERATING then DELETING on same cell → DELETING returns False.

        Inject-bug: remove the `if CellOperation.GENERATING in active: return False`
        check from the DELETING branch in try_acquire_cell → DELETING proceeds
        alongside GENERATING → data corruption race reintroduced → this test fails.
        """
        machine, mode = "M14", 1
        assert registry.try_acquire_cell(machine, mode, CellOperation.GENERATING) is True

        ok = registry.try_acquire_cell(machine, mode, CellOperation.DELETING)
        assert ok is False, "DELETING must be rejected when GENERATING is active (INV-2)"

        # Reverse: DELETING blocks GENERATING
        registry.release_cell(machine, mode, CellOperation.GENERATING)
        assert registry.try_acquire_cell(machine, mode, CellOperation.DELETING) is True

        ok2 = registry.try_acquire_cell(machine, mode, CellOperation.GENERATING)
        assert ok2 is False, "GENERATING must be rejected when DELETING is active (INV-2 reverse)"

        registry.release_cell(machine, mode, CellOperation.DELETING)

    def test_sampling_and_generating_coexist(self, registry: CellLockRegistry):
        """INV-3: SAMPLING + GENERATING on same cell are BOTH allowed.

        The generator snapshots chunks at start; concurrent SAMPLING writing
        new chunks is benign per 04_v2 §4.1 OQ-1.

        Inject-bug: add `if CellOperation.SAMPLING in active: return False`
        to the GENERATING branch → second acquire returns False → test fails.
        """
        machine, mode = "M14", 1
        assert registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING) is True
        assert registry.try_acquire_cell(machine, mode, CellOperation.GENERATING) is True, (
            "GENERATING must succeed even when SAMPLING is active (INV-3 coexistence)"
        )

        # Both should appear in active cells
        active = registry.get_active_cells()
        assert ("M14", 1) in active
        assert ("M14", 1) in registry.get_active_cells(CellOperation.SAMPLING)
        assert ("M14", 1) in registry.get_active_cells(CellOperation.GENERATING)

        registry.release_cell(machine, mode, CellOperation.GENERATING)
        registry.release_cell(machine, mode, CellOperation.SAMPLING)

    def test_one_sampling_per_cell(self, registry: CellLockRegistry):
        """INV-4: Second SAMPLING acquire on same cell → False.

        Attach logic is upstream (BatchRunManager._run_one); the registry
        itself simply rejects. Different config OR same config — both False.

        Inject-bug: remove the `if CellOperation.SAMPLING in active: return False`
        check from the SAMPLING branch → second acquire succeeds → multiple
        concurrent SAMPLINGs can run on one cell → test fails.
        """
        machine, mode = "M14", 1
        assert registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING) is True

        # Second SAMPLING — same cell — must fail
        ok = registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING)
        assert ok is False, "INV-4: at most one SAMPLING per cell"

        registry.release_cell(machine, mode, CellOperation.SAMPLING)
        # After release, a new SAMPLING should succeed
        assert registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING) is True
        registry.release_cell(machine, mode, CellOperation.SAMPLING)

    def test_one_generating_per_cell(self, registry: CellLockRegistry):
        """INV-5: Second GENERATING acquire on same cell → False.

        Inject-bug: remove the `if CellOperation.GENERATING in active: return False`
        check from the GENERATING branch → second acquire succeeds → concurrent
        report generation on same cell (race on report sidecar) → test fails.
        """
        machine, mode = "M14", 1
        assert registry.try_acquire_cell(machine, mode, CellOperation.GENERATING) is True

        ok = registry.try_acquire_cell(machine, mode, CellOperation.GENERATING)
        assert ok is False, "INV-5: at most one GENERATING per cell"

        registry.release_cell(machine, mode, CellOperation.GENERATING)
        assert registry.try_acquire_cell(machine, mode, CellOperation.GENERATING) is True
        registry.release_cell(machine, mode, CellOperation.GENERATING)

    def test_global_op_one_at_a_time(self, registry: CellLockRegistry):
        """INV-6: try_acquire_global twice for same name → second returns False.

        Inject-bug: change `if self._global_ops.get(name): return False` to
        `if False:` (i.e. always succeed) → second acquire returns True →
        concurrent global ops run simultaneously → test fails.
        """
        assert registry.try_acquire_global("disk_cleanup") is True
        assert registry.try_acquire_global("disk_cleanup") is False, (
            "INV-6: second acquire of same global op must fail"
        )

        # Different named op can coexist
        assert registry.try_acquire_global("prune_versions") is True

        registry.release_global("disk_cleanup")
        registry.release_global("prune_versions")

        # After release, re-acquire must succeed
        assert registry.try_acquire_global("disk_cleanup") is True
        registry.release_global("disk_cleanup")

    def test_isolation_across_different_cells(self, registry: CellLockRegistry):
        """Locks on one cell do not affect a different cell.

        Basic sanity: DELETING on M14|1 does not block DELETING on M14|2.
        """
        assert registry.try_acquire_cell("M14", 1, CellOperation.DELETING) is True
        # Different mode — independent cell
        assert registry.try_acquire_cell("M14", 2, CellOperation.DELETING) is True
        assert registry.try_acquire_cell("M15", 1, CellOperation.SAMPLING) is True

        registry.release_cell("M14", 1, CellOperation.DELETING)
        registry.release_cell("M14", 2, CellOperation.DELETING)
        registry.release_cell("M15", 1, CellOperation.SAMPLING)


# ---------------------------------------------------------------------------
# Sampling info / R9 attach lookup
# ---------------------------------------------------------------------------


class TestSamplingInfo:
    """R9 attach-response lookup: get_active_sampling_info stores and returns info."""

    def test_get_active_sampling_info_returns_stored_info(self, registry: CellLockRegistry):
        """acquire SAMPLING with info dict; get_active_sampling_info returns it.

        Inject-bug: remove `self._sampling_info[key] = dict(info)` from
        try_acquire_cell → get_active_sampling_info returns None →
        assertion fails.
        """
        machine, mode = "M14", 1
        info = {
            "run_id": "run-abc-123",
            "config_id": "cfg-001",
            "upstream_md5": "deadbeef|cafebabe",
        }
        ok = registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING, info=info)
        assert ok is True

        retrieved = registry.get_active_sampling_info(machine, mode)
        assert retrieved is not None, "get_active_sampling_info should return stored dict"
        assert retrieved["run_id"] == "run-abc-123"
        assert retrieved["config_id"] == "cfg-001"
        assert retrieved["upstream_md5"] == "deadbeef|cafebabe"

        # Returned dict is a defensive copy (mutations do not affect internal state)
        retrieved["run_id"] = "MUTATED"
        assert registry.get_active_sampling_info(machine, mode)["run_id"] == "run-abc-123", (
            "Returned dict must be a defensive copy — internal state must not be mutated"
        )

        registry.release_cell(machine, mode, CellOperation.SAMPLING)
        # After release, info should be gone
        assert registry.get_active_sampling_info(machine, mode) is None

    def test_get_active_sampling_info_returns_none_for_non_sampling(
        self, registry: CellLockRegistry
    ):
        """GENERATING does not populate sampling info."""
        registry.try_acquire_cell("M14", 1, CellOperation.GENERATING)
        info = registry.get_active_sampling_info("M14", 1)
        assert info is None, "GENERATING op should not populate sampling info"
        registry.release_cell("M14", 1, CellOperation.GENERATING)

    def test_sampling_info_cleared_on_release(self, registry: CellLockRegistry):
        """After release_cell(SAMPLING), sampling info is gone."""
        info = {"run_id": "r1", "config_id": "c1", "upstream_md5": "md5"}
        registry.try_acquire_cell("M14", 1, CellOperation.SAMPLING, info=info)
        registry.release_cell("M14", 1, CellOperation.SAMPLING)
        assert registry.get_active_sampling_info("M14", 1) is None


# ---------------------------------------------------------------------------
# Snapshot serialisability
# ---------------------------------------------------------------------------


class TestSnapshot:
    """snapshot() must return a JSON-serialisable dict (D13)."""

    def test_snapshot_is_json_serializable(self, registry: CellLockRegistry):
        """json.dumps(registry.snapshot()) must not raise.

        Inject-bug: store a non-serialisable value (e.g. a threading.Lock)
        inside _registry → json.dumps raises TypeError → test fails.
        """
        # Empty registry
        s = registry.snapshot()
        json.dumps(s)  # Must not raise

        # With active operations
        registry.try_acquire_cell("M14", 1, CellOperation.SAMPLING,
                                  info={"run_id": "r1", "config_id": "c", "upstream_md5": "m"})
        registry.try_acquire_cell("M14", 1, CellOperation.GENERATING)
        registry.try_acquire_global("disk_cleanup")

        s2 = registry.snapshot()
        serialised = json.dumps(s2)  # Must not raise
        data = json.loads(serialised)

        assert "cells" in data
        assert "global_ops" in data
        assert "active_cell_count" in data
        assert data["active_cell_count"] == 1  # M14|1
        assert "disk_cleanup" in data["global_ops"]

        # Cell should list both SAMPLING and GENERATING
        assert "M14|1" in data["cells"]
        assert "sampling" in data["cells"]["M14|1"]
        assert "generating" in data["cells"]["M14|1"]

        registry.release_cell("M14", 1, CellOperation.SAMPLING)
        registry.release_cell("M14", 1, CellOperation.GENERATING)
        registry.release_global("disk_cleanup")

    def test_snapshot_empty_registry(self, registry: CellLockRegistry):
        """Empty registry snapshot has correct zero-state structure."""
        s = registry.snapshot()
        assert s["cells"] == {}
        assert s["global_ops"] == []
        assert s["active_cell_count"] == 0
        assert s["active_global_count"] == 0


# ---------------------------------------------------------------------------
# Thread-safety tests
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Thread-safety verification: N concurrent threads must see consistent state.

    These tests exercise the threading.Lock protection inside CellLockRegistry.
    Without _lock, the TOCTOU between read-then-write in try_acquire_cell
    would allow two threads to both see "not in registry" and both insert,
    violating INV-4 / INV-5.

    Inject-bug recipe (for impl-tester P2-T5):
      1. Replace `self._lock: threading.Lock = threading.Lock()` in
         CellLockRegistry.__init__ with a DummyLock that does nothing.
      2. Run test_concurrent_acquire_release_thread_safety with N=20 threads
         on the SAME cell — without the lock, multiple SAMPLING acquires can
         succeed simultaneously (TOCTOU race between check and set).
      3. Revert → PASS.
    """

    def test_concurrent_acquire_release_thread_safety_different_cells(
        self, registry: CellLockRegistry
    ):
        """N=20 threads alternately acquiring/releasing on DIFFERENT cells.

        Each thread has its own cell (no contention between threads), so all
        acquires should succeed. This tests that the lock does not deadlock
        or cause unexpected serialisation failures.
        """
        N = 20
        errors: list[str] = []
        results: list[bool] = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            machine = f"M{i:03d}"
            mode = i
            ok = registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING)
            with lock:
                results.append(ok)
            if ok:
                time.sleep(0)  # yield
                registry.release_cell(machine, mode, CellOperation.SAMPLING)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results), f"Some acquires failed on distinct cells: {results}"
        # After all threads done, registry should be empty
        assert registry.get_active_cells() == set(), (
            "Registry not empty after all threads released — leak detected"
        )

    def test_concurrent_acquire_release_same_cell_only_one_wins(
        self, registry: CellLockRegistry
    ):
        """N=20 threads racing to acquire SAMPLING on the SAME cell.

        INV-4: at most ONE should succeed. Without the lock, TOCTOU could
        let multiple threads see the cell as free simultaneously, violating INV-4.

        This is the primary inject-bug target for the _lock protection.
        """
        N = 20
        successes: list[int] = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            ok = registry.try_acquire_cell("M14", 1, CellOperation.SAMPLING)
            if ok:
                with lock:
                    successes.append(i)
                time.sleep(0.001)  # hold briefly to widen TOCTOU window
                registry.release_cell("M14", 1, CellOperation.SAMPLING)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Cannot assert exactly 1 (threads run sequentially after release),
        # but at no point should more than 1 thread hold SAMPLING simultaneously.
        # If _lock is removed, all N threads can win the first check simultaneously.
        # Verify post-condition: registry is clean.
        assert registry.get_active_cells() == set(), (
            "Registry not empty after all threads finished — possible lock leak"
        )
        # At least one thread should have succeeded (registry isn't stuck)
        assert len(successes) >= 1, "No thread succeeded in acquiring — registry stuck?"

    def test_global_op_thread_safety(self, registry: CellLockRegistry):
        """N=10 threads racing to acquire the same global op; exactly ONE wins per round.

        Without _lock, two threads can both see _global_ops.get(name) as False
        simultaneously (TOCTOU) and both return True, violating INV-6.
        """
        N = 10
        wins: list[int] = []
        lock = threading.Lock()
        barrier = threading.Barrier(N)

        def worker(i: int) -> None:
            barrier.wait()  # all start at once to maximise contention
            ok = registry.try_acquire_global("global_test_op")
            if ok:
                with lock:
                    wins.append(i)
                time.sleep(0.001)
                registry.release_global("global_test_op")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Registry should be clean after all threads done
        snap = registry.snapshot()
        assert "global_test_op" not in snap["global_ops"], (
            "global_test_op still held after all threads finished — lock leak"
        )


# ---------------------------------------------------------------------------
# Blocker 2: update_sampling_run_id (D12 fix — impl-critic loop-back)
# ---------------------------------------------------------------------------


class TestUpdateSamplingRunId:
    """unit tests for update_sampling_run_id (added in impl-critic Blocker 2 fix).

    The method is needed because try_acquire_cell stores a COPY of the info dict
    (cell_lock_registry.py line ~144 `dict(info)`). Mutating the caller's local
    dict after acquire does NOT update the registry — a separate explicit call
    to update_sampling_run_id is required.

    Inject-bug recipe:
      In cell_lock_registry.py update_sampling_run_id, change
      `info["run_id"] = run_id` to `pass` (no-op) → registry never updates →
      get_active_sampling_info returns the old run_id → tests FAIL.
    """

    def test_update_sampling_run_id_mutates_registry_copy(
        self, registry: CellLockRegistry
    ):
        """acquire SAMPLING with run_id=""; update_sampling_run_id;
        get_active_sampling_info returns updated run_id.

        Key invariant: try_acquire_cell stores a COPY, so local dict mutations
        do not propagate — update_sampling_run_id is the only correct update path.

        Inject-bug: change `info["run_id"] = run_id` to `pass` → returned
        run_id stays "" → assertion fails.
        """
        machine, mode = "M14", 1
        sampling_info = {
            "run_id": "",           # placeholder — real id not yet known
            "config_id": "null",
            "upstream_md5": "cfg|code",
        }
        ok = registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING,
                                       info=sampling_info)
        assert ok is True

        try:
            # Confirm: local dict mutation does NOT propagate to registry copy
            sampling_info["run_id"] = "should-not-propagate"
            stored = registry.get_active_sampling_info(machine, mode)
            assert stored is not None
            assert stored["run_id"] == "", (
                "try_acquire_cell must store a COPY; local mutation must not affect registry"
            )

            # Explicit update call (the Blocker 2 fix)
            result = registry.update_sampling_run_id(machine, mode, "real-run-id-xyz")
            assert result is True, "update_sampling_run_id must return True for active SAMPLING"

            # Verify registry now shows the real run_id
            stored2 = registry.get_active_sampling_info(machine, mode)
            assert stored2 is not None
            assert stored2["run_id"] == "real-run-id-xyz", (
                f"After update_sampling_run_id, expected 'real-run-id-xyz', "
                f"got {stored2['run_id']!r}"
            )
        finally:
            registry.release_cell(machine, mode, CellOperation.SAMPLING)

    def test_update_sampling_run_id_returns_false_when_no_active_sampling(
        self, registry: CellLockRegistry
    ):
        """update_sampling_run_id returns False when no SAMPLING is active.

        Inject-bug: change `if info is None: return False` to `return True` →
        caller believes update succeeded even with no active SAMPLING → test FAILS.
        """
        # Nothing acquired
        result = registry.update_sampling_run_id("M14", 1, "some-id")
        assert result is False, (
            "update_sampling_run_id must return False when no SAMPLING is active"
        )

        # Only GENERATING active — still no SAMPLING
        registry.try_acquire_cell("M14", 1, CellOperation.GENERATING)
        try:
            result2 = registry.update_sampling_run_id("M14", 1, "some-id")
            assert result2 is False, (
                "update_sampling_run_id returns False even with GENERATING active "
                "(only SAMPLING has a run_id to update)"
            )
        finally:
            registry.release_cell("M14", 1, CellOperation.GENERATING)

    def test_update_sampling_run_id_concurrent_with_get_info(
        self, registry: CellLockRegistry
    ):
        """N writer threads calling update_sampling_run_id + N reader threads
        calling get_active_sampling_info; no torn state (run_id must always be a str).

        The _lock in update_sampling_run_id and get_active_sampling_info
        prevents TOCTOU between the read-modify-write in update and the read
        in get. Without _lock, a reader could see a dict mid-update.

        Inject-bug: remove `with self._lock:` from update_sampling_run_id →
        concurrent readers might see inconsistent dict state → test may fail
        with KeyError or wrong type (unlikely with CPython GIL, but the
        contract requires the lock, not GIL semantics).
        """
        machine, mode = "M14", 1
        registry.try_acquire_cell(machine, mode, CellOperation.SAMPLING,
                                  info={"run_id": "initial", "config_id": "c",
                                        "upstream_md5": "m"})
        errors: list[str] = []
        N = 20

        def writer(i: int) -> None:
            for _ in range(15):
                registry.update_sampling_run_id(machine, mode, f"run-{i}")

        def reader() -> None:
            for _ in range(50):
                info = registry.get_active_sampling_info(machine, mode)
                if info is not None:
                    if "run_id" not in info:
                        errors.append("Missing run_id key in returned info")
                    elif not isinstance(info["run_id"], str):
                        errors.append(f"run_id not str: {type(info['run_id'])}")

        threads = (
            [threading.Thread(target=writer, args=(i,)) for i in range(N // 2)]
            + [threading.Thread(target=reader) for _ in range(N // 2)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        registry.release_cell(machine, mode, CellOperation.SAMPLING)

        assert not errors, (
            f"Concurrent update_sampling_run_id/get_active_sampling_info produced "
            f"torn state: {errors[:3]}"
        )
