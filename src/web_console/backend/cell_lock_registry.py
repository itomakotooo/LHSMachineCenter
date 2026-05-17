"""CellLockRegistry — unified per-cell concurrency primitive.

Phase 2 of the deploy migration (2026-05-17).  Replaces four independent
in-memory primitives:

  * ``_IN_USE_MODES`` global set  (app.py:2180)
  * ``BatchRunManager._busy_keys`` instance set  (app.py:3238)
  * ``OperationCoordinator`` single-flag mutex  (app.py:4040)
  * per-path ``_sidecar_lock_for`` dict  (chunk_index.py:91)

Design source: session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.1
Decision:      session_artifacts/_arch/deploy/07_deploy_decision.md §3.1

Per memory/feedback_subprocess_import_suicide_and_module_globals.md:
  * No import-time side effects.  Importing this module builds no state.
  * Callers construct CellLockRegistry() inside create_app() so each app
    instance (prod or test-isolated) has its own registry.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Any


class CellOperation(Enum):
    """Operations that can be active on a ``(machine, mode)`` cell.

    Invariants (enforced by CellLockRegistry.try_acquire_cell):
      INV-1: SAMPLING and DELETING are mutually exclusive per cell.
      INV-2: GENERATING and DELETING are mutually exclusive per cell.
      INV-3: SAMPLING + GENERATING on the same cell are ALLOWED.
              (Generator snapshots chunks at start; new chunks written by
               concurrent SAMPLING after that point are not included —
               benign per 04_v2 §4.1 OQ-1 resolution.)
      INV-4: At most ONE SAMPLING per cell.
      INV-5: At most ONE GENERATING per cell.
    """

    SAMPLING = "sampling"    # BatchRunManager: analyzer subprocess writing chunks
    GENERATING = "generating"  # RunManager / BatchGenerateManager: reading chunks
    DELETING = "deleting"    # delete_rawdata paths: unlinking chunks + updating index


class CellLockRegistry:
    """Thread-safe registry of active operations across ``(machine, mode)`` cells.

    Usage::

        registry = CellLockRegistry()

        # Attempt to acquire SAMPLING on (M14, 1):
        if registry.try_acquire_cell("M14", 1, CellOperation.SAMPLING,
                                     info={"run_id": rid, ...}):
            try:
                ...do sampling...
            finally:
                registry.release_cell("M14", 1, CellOperation.SAMPLING)
        else:
            ...handle conflict...

        # Global ops (disk_cleanup, prune_versions, etc.):
        if registry.try_acquire_global("disk_cleanup"):
            try:
                ...
            finally:
                registry.release_global("disk_cleanup")
    """

    def __init__(self) -> None:
        # Guards ALL mutations below — one lock for the whole registry.
        self._lock: threading.Lock = threading.Lock()

        # Active operations per cell: (machine, mode) → set of CellOperation.
        self._registry: dict[tuple[str, int], set[CellOperation]] = {}

        # Per-active-SAMPLING metadata, used by attach-response logic (R9).
        # Present only while SAMPLING is active on that cell.
        # Keys: {"run_id": str, "config_id": str, "upstream_md5": str}
        self._sampling_info: dict[tuple[str, int], dict[str, Any]] = {}

        # Global one-at-a-time ops (disk_cleanup, prune_versions, etc.)
        # INV-6: at most ONE holder per named global op.
        self._global_ops: dict[str, bool] = {}

    # ── Cell-level API ────────────────────────────────────────────────

    def try_acquire_cell(
        self,
        machine: str,
        mode: int,
        op: CellOperation,
        info: dict[str, Any] | None = None,
    ) -> bool:
        """Attempt to acquire ``op`` on ``(machine, mode)``.

        Returns True and records the op if the invariants permit it.
        Returns False without mutating state if any invariant would be
        violated.

        ``info`` is stored verbatim per-cell when ``op == SAMPLING``.
        Callers should pass at minimum::

            {"run_id": str, "config_id": str, "upstream_md5": str}

        for attach-response lookup (R9 / D12).
        """
        key = (str(machine), int(mode))
        with self._lock:
            active = self._registry.get(key) or set()

            if op is CellOperation.SAMPLING:
                # INV-1: SAMPLING ↔ DELETING mutually exclusive
                if CellOperation.DELETING in active:
                    return False
                # INV-4: at most one SAMPLING
                if CellOperation.SAMPLING in active:
                    return False

            elif op is CellOperation.GENERATING:
                # INV-2: GENERATING ↔ DELETING mutually exclusive
                if CellOperation.DELETING in active:
                    return False
                # INV-5: at most one GENERATING
                if CellOperation.GENERATING in active:
                    return False

            elif op is CellOperation.DELETING:
                # INV-1 + INV-2: DELETING ↔ SAMPLING and GENERATING both exclusive
                if CellOperation.SAMPLING in active or CellOperation.GENERATING in active:
                    return False
                # At most one DELETING per cell
                if CellOperation.DELETING in active:
                    return False

            # All invariants satisfied — record the operation.
            if key not in self._registry:
                self._registry[key] = set()
            self._registry[key].add(op)

            # Store SAMPLING metadata for attach-response lookup.
            if op is CellOperation.SAMPLING and info is not None:
                self._sampling_info[key] = dict(info)

            return True

    def release_cell(
        self,
        machine: str,
        mode: int,
        op: CellOperation,
    ) -> None:
        """Release ``op`` from ``(machine, mode)``.

        Defensive: releasing an op that was never acquired is a no-op
        (does not raise).  This mirrors the original ``_IN_USE_MODES.discard``
        semantics.
        """
        key = (str(machine), int(mode))
        with self._lock:
            active = self._registry.get(key)
            if active is None:
                return
            active.discard(op)
            if not active:
                del self._registry[key]
            # Clear SAMPLING metadata when SAMPLING is released.
            if op is CellOperation.SAMPLING:
                self._sampling_info.pop(key, None)

    def get_active_cells(
        self,
        op: CellOperation | None = None,
    ) -> set[tuple[str, int]]:
        """Return the set of cells that have at least one active operation.

        If ``op`` is given, return only cells with that specific operation
        active.  Used by disk-cleanup to skip cells in use, and by
        D10/_auto_cleanup_for_space.
        """
        with self._lock:
            if op is None:
                return set(self._registry.keys())
            return {
                key
                for key, active in self._registry.items()
                if op in active
            }

    def get_active_sampling_info(
        self,
        machine: str,
        mode: int,
    ) -> dict[str, Any] | None:
        """Return stored SAMPLING info for ``(machine, mode)``, or None.

        Used by the R9 attach-response logic in BatchRunManager._run_one:
        if acquire returns False, the caller checks whether the existing
        SAMPLING has the same ``(config_id, upstream_md5)`` to decide
        between attach vs reject.
        """
        key = (str(machine), int(mode))
        with self._lock:
            info = self._sampling_info.get(key)
            if info is None:
                return None
            return dict(info)  # defensive copy

    def update_sampling_run_id(self, machine: str, mode: int, run_id: str) -> bool:
        """Update the run_id field of an active SAMPLING entry's stored info.

        Returns True if updated, False if no active SAMPLING for (machine, mode).

        Used by D12 attach semantics: BatchRunManager._run_one calls this after
        RunManager.start_run() returns the real run_id, so subsequent attach
        lookups see the live run_id (not the empty placeholder stored at
        try_acquire_cell time).

        Per 04_v2 §4.1 R9: the registry stores a COPY of info at acquire time.
        Mutating the caller's local dict after acquire does NOT update the
        registry — this method must be called explicitly.
        """
        key = (str(machine), int(mode))
        with self._lock:
            info = self._sampling_info.get(key)
            if info is None:
                return False
            info["run_id"] = run_id
            return True

    # ── Global op API ─────────────────────────────────────────────────

    def try_acquire_global(self, name: str) -> bool:
        """Attempt to acquire a named global op slot.

        INV-6: at most ONE holder per name at a time.
        Returns True on success, False if already held.
        """
        with self._lock:
            if self._global_ops.get(name):
                return False
            self._global_ops[name] = True
            return True

    def release_global(self, name: str) -> None:
        """Release a named global op.  Defensive: no-op if not held."""
        with self._lock:
            self._global_ops.pop(name, None)

    # ── Snapshot ─────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of the registry state.

        Used by ``GET /api/system-state`` (D13) and by impl-verifier /
        impl-critic for sanity checks.

        Structure::

            {
              "cells": {
                "<machine>|<mode>": ["sampling", "generating", ...],
                ...
              },
              "global_ops": ["disk_cleanup", ...],
              "active_cell_count": int,
              "active_global_count": int,
            }
        """
        with self._lock:
            cells: dict[str, list[str]] = {}
            for (machine, mode), active in self._registry.items():
                cells[f"{machine}|{mode}"] = sorted(op.value for op in active)

            global_ops = sorted(
                name for name, held in self._global_ops.items() if held
            )

            # Include SAMPLING info so operators can see which runs are
            # actively sampling when inspecting system-state.
            sampling_details: dict[str, dict[str, Any]] = {}
            for (machine, mode), info in self._sampling_info.items():
                sampling_details[f"{machine}|{mode}"] = dict(info)

            return {
                "cells": cells,
                "global_ops": global_ops,
                "active_cell_count": len(self._registry),
                "active_global_count": len(global_ops),
                "sampling_details": sampling_details,
            }
