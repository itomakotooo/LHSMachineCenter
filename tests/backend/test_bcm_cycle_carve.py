"""Isolation regression test for the BCM-cycle carve (the genuine redo of C2).

Pins the property C2's HOLLOW carve failed to deliver: the BCM cycle logic — the 5
functions get_collect_count / detect_cycle_peak / compute_robot_cycle_peaks /
at_cycle_peak_indices / infer_bcm_target_spin_type — now lives OUTSIDE the base_hash
closure (in play_types/bcm_cycle.py), so editing it does NOT re-flag the fleet.

C2 (commit 6b10942) left these in round_classification.py (a closure file) and had
bcm_base.py merely CALL them, so editing the BCM cycle rule still flipped base_hash.
This carve moved them out. If a future change moves them back into a closure file
(or adds bcm_cycle.py to _CLOSURE_FILES), the isolation test below goes RED.

See CARVE_METHODOLOGY.md for the gate this enforces.
"""
from __future__ import annotations

import hashlib

from fresh_slotlab.analyzer.versioning import (
    _CLOSURE_FILES,
    _REPO_ROOT,
    compute_base_analyzer_version,
)
from fresh_slotlab.analyzer.play_types import bcm_cycle

_BCM_CYCLE_REL = "fresh_slotlab/analyzer/play_types/bcm_cycle.py"
_ROUND_CLASS_REL = "fresh_slotlab/round_classification.py"
_BCM_FNS = [
    "get_collect_count",
    "detect_cycle_peak",
    "compute_robot_cycle_peaks",
    "at_cycle_peak_indices",
    "infer_bcm_target_spin_type",
]


def _base_hash_with_simulated_edit(edit_rel: str, suffix: bytes) -> str:
    """Recompute base_hash, appending *suffix* to *edit_rel* iff it is in the
    closure (mirrors compute_base_analyzer_version exactly)."""
    h = hashlib.sha256()
    for rel in sorted(_CLOSURE_FILES):
        raw = (_REPO_ROOT / rel).read_bytes().replace(b"\r\n", b"\n")
        if rel == edit_rel:
            raw = raw + suffix
        h.update(raw)
    return h.hexdigest()[:12]


class TestBcmCycleLivesOutsideClosure:
    def test_all_five_functions_home_is_bcm_cycle(self) -> None:
        for fn in _BCM_FNS:
            obj = getattr(bcm_cycle, fn)
            assert obj.__module__.endswith("play_types.bcm_cycle"), fn

    def test_bcm_cycle_file_not_in_base_closure(self) -> None:
        assert _BCM_CYCLE_REL not in _CLOSURE_FILES

    def test_round_classification_still_in_base_closure(self) -> None:
        assert _ROUND_CLASS_REL in _CLOSURE_FILES


class TestEditingBcmCycleDoesNotReflagFleet:
    def test_editing_bcm_cycle_logic_leaves_base_hash_unchanged(self) -> None:
        baseline = compute_base_analyzer_version()
        after = _base_hash_with_simulated_edit(
            _BCM_CYCLE_REL, b"\n# simulate editing the BCM cycle rule\n"
        )
        assert after == baseline, (
            "Editing bcm_cycle.py changed base_hash -- the BCM cycle logic leaked "
            "back into the closure (a regression to C2's hollow carve)."
        )

    def test_editing_a_universal_function_still_flips_base_hash(self) -> None:
        baseline = compute_base_analyzer_version()
        after = _base_hash_with_simulated_edit(
            _ROUND_CLASS_REL, b"\n# simulate editing a universal helper\n"
        )
        assert after != baseline, (
            "Editing round_classification.py did NOT change base_hash -- universal "
            "logic is no longer hashed (over-isolation)."
        )


class TestBcmCycleBehaviorPreserved:
    """Sanity only; full behavior coverage is in test_round_classification.py +
    test_bcm_base.py (both now import these from bcm_cycle)."""

    def test_get_collect_count(self) -> None:
        assert bcm_cycle.get_collect_count({"CollectCount": 500}) == 500
        assert bcm_cycle.get_collect_count({}) is None

    def test_compute_robot_cycle_peaks_empty(self) -> None:
        assert bcm_cycle.compute_robot_cycle_peaks([]) == []
