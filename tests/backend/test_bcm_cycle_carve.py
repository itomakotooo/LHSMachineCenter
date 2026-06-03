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

=== Salvaged contract tests (Phase D) ===
Phase D deleted ``tests/backend/test_bcm_base.py`` (the deleted play-type plugin
framework test file). That file's ``TestComputeRobotCyclePeaks`` class (12 unit
tests) tested ``compute_robot_cycle_peaks`` — a KEPT function that now lives only in
this module. Those tests are salvaged here, re-pointed to the bcm_cycle import (not
the deleted bcm_base). Framework-specific tests (TestBCMBaseClaim / T3 flag-ON
subprocess / T4 engagement via BCMBaseAccumulator / T5 accumulator lifecycle) are
intentionally omitted — they tested the deleted plugin, not the kept function.

detect_cycle_peak / at_cycle_peak_indices / infer_bcm_target_spin_type already have
full coverage in test_round_classification.py (which imports from bcm_cycle).
Only compute_robot_cycle_peaks had its coverage in the deleted file.

Inject-bug recipe (for CI/future dev):
  In fresh_slotlab/analyzer/play_types/bcm_cycle.py, change:
      if cc_int < prev and prev > 10:
  to the OLD buggy rule:
      if cc_int < prev - 1 and prev >= 5:
  Then:
    - test_small_peak_not_recorded → RED (old rule WOULD record peak=8 reset)
    - test_single_step_drop_recorded → RED (old rule would NOT record 50→49)
  Revert → both GREEN.

Memory feedback honoured:
  - memory/feedback_enumerate_safety_paths.md — inject-bug recipe documents
    exact regression path for each assertion (see inject-bug section above).
  - memory/feedback_perf_claim_needs_e2e_event_stream.md — real M272 rawdata test
    (test_m272_real_rounds_produces_peaks) exercises the real data path.
  - memory/feedback_integration_test_argv.md — the byte-identical gate is run as a
    coordinator stash→run→diff workflow (pre/post reports under cache/), not a pytest
    function; this file pins base_hash isolation + the compute_robot_cycle_peaks contract.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fresh_slotlab.analyzer.versioning import (
    _CLOSURE_FILES,
    _REPO_ROOT,
    compute_base_analyzer_version,
)
from fresh_slotlab.analyzer.play_types import bcm_cycle
from fresh_slotlab.analyzer.play_types.bcm_cycle import compute_robot_cycle_peaks

_BCM_CYCLE_REL = "fresh_slotlab/analyzer/play_types/bcm_cycle.py"
_ROUND_CLASS_REL = "fresh_slotlab/round_classification.py"
_BCM_FNS = [
    "get_collect_count",
    "detect_cycle_peak",
    "compute_robot_cycle_peaks",
    "at_cycle_peak_indices",
    "infer_bcm_target_spin_type",
]

_ROOT = Path(__file__).resolve().parents[2]
_RAWDATA_DIR = _ROOT / "rawdata"
_M272_AVAILABLE = (
    (_RAWDATA_DIR / "M272" / "mode_1").is_dir()
    and any((_RAWDATA_DIR / "M272" / "mode_1").glob("chunk_*.json"))
)
_SKIP_NO_M272 = pytest.mark.skipif(
    not _M272_AVAILABLE, reason="M272 rawdata not available"
)


def _make_synthetic_bcm_rounds(cc_sequence: list[int]) -> list[dict]:
    """Build a minimal paid-round list with the given CollectCount sequence.

    Each round: CostCredits=1000, CollectCount=cc. Mirrors the helper from
    the deleted test_bcm_base.py (salvaged: same semantics, no framework deps).
    """
    rounds = []
    for cc in cc_sequence:
        rounds.append({
            "SpinType": 140,
            "BetAmount": 1000,
            "CostCredits": 1000,
            "WinCredits": 0,
            "CollectCount": cc,
            "AccCredits": 0,
            "CreditsSymbols": "",
            "SymbolIndexToRewards": {},
            "StopSymbolsByCol": ["1-2-3"],
            "PayoutByPayline": "",
            "PayoutIdToWinAmount": {},
            "ReMarks": "",
        })
    return rounds


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


# ---------------------------------------------------------------------------
# Carve isolation gate (unchanged from before Phase D)
# ---------------------------------------------------------------------------

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
    """Sanity only; full behavior coverage is in test_round_classification.py
    (detect_cycle_peak / at_cycle_peak_indices / infer_bcm_target_spin_type)
    and TestComputeRobotCyclePeaks below (compute_robot_cycle_peaks contract)."""

    def test_get_collect_count(self) -> None:
        assert bcm_cycle.get_collect_count({"CollectCount": 500}) == 500
        assert bcm_cycle.get_collect_count({}) is None

    def test_compute_robot_cycle_peaks_empty(self) -> None:
        assert bcm_cycle.compute_robot_cycle_peaks([]) == []


# ---------------------------------------------------------------------------
# Salvaged contract tests — compute_robot_cycle_peaks
# (from deleted tests/backend/test_bcm_base.py::TestComputeRobotCyclePeaks)
#
# These tests prove the CORRECT rule (cc < prev AND prev > 10) is used,
# NOT the old buggy rule (cc < prev - 1 AND prev >= 5).
#
# Inject-bug B recipe (see module docstring) targets these tests.
# ---------------------------------------------------------------------------

class TestComputeRobotCyclePeaks:
    """Unit contract for compute_robot_cycle_peaks — salvaged from deleted
    test_bcm_base.py::TestComputeRobotCyclePeaks (Phase D cleanup).

    Each case isolates a single behavioral property of the CORRECT rule
    (cc_int < prev AND prev > 10). The two discriminating cases at the bottom
    are the inject-bug B proof: if the condition is reverted to the old rule
    (cc < prev-1 AND prev >= 5) these two tests flip RED.
    """

    def test_empty_rounds_returns_empty(self) -> None:
        assert compute_robot_cycle_peaks([]) == []

    def test_non_dict_rounds_skipped(self) -> None:
        """Non-dict entries (None, str, int) are skipped without error."""
        assert compute_robot_cycle_peaks([None, "bad", 42]) == []

    def test_bonus_rounds_not_paid_skipped(self) -> None:
        """Bonus rounds (CostCredits=0 or None) do not contribute to peaks."""
        rounds = [
            {"SpinType": 2, "CostCredits": 0, "CollectCount": 1000},
            {"SpinType": 2, "CostCredits": None, "CollectCount": 500},
        ]
        assert compute_robot_cycle_peaks(rounds) == []

    def test_cc_zero_on_paid_round_skipped(self) -> None:
        """Paid rounds with CollectCount=0 are skipped (M274 cc=0 machine)."""
        rounds = _make_synthetic_bcm_rounds([0, 0, 0])
        assert compute_robot_cycle_peaks(rounds) == []

    def test_monotonic_increase_no_peaks(self) -> None:
        """CC walking monotonically up (no reset) → no peaks detected."""
        rounds = _make_synthetic_bcm_rounds(list(range(1, 101)))
        assert compute_robot_cycle_peaks(rounds) == []

    def test_single_complete_cycle_records_peak(self) -> None:
        """One complete cycle (cc=1..100 then reset to cc=1) records one peak.

        The peak value recorded is prev (100) at the moment of reset.
        Reset condition: cc_int(1) < prev(100) AND prev(100) > 10 → True.
        """
        cc_seq = list(range(1, 101)) + [1, 2, 3]  # reset at cc=1 after 100
        rounds = _make_synthetic_bcm_rounds(cc_seq)
        peaks = compute_robot_cycle_peaks(rounds)
        assert peaks == [100], f"Expected [100], got {peaks}"

    def test_multiple_cycles_records_all_peaks(self) -> None:
        """Multiple cycles → multiple peak entries."""
        # Two cycles: 1..50 → reset, then 1..50 → reset.
        cc_seq = list(range(1, 51)) + list(range(1, 51)) + [1]
        rounds = _make_synthetic_bcm_rounds(cc_seq)
        peaks = compute_robot_cycle_peaks(rounds)
        assert peaks == [50, 50], f"Expected [50, 50], got {peaks}"

    def test_small_peak_not_recorded(self) -> None:
        """Peak in [5,10] range NOT recorded: floor is prev > 10, not >= 5.

        Setup: cc goes 1..8 (peak=8) then drops to 1.
        Correct rule: cc(1) < prev(8) → True, BUT prev(8) > 10 → False → NOT recorded.
        Old buggy rule: cc(1) < prev(8)-1=7 → True, prev(8) >= 5 → True → WOULD record.

        Inject-bug B: change to old rule → this test goes RED (would get [8]).
        """
        cc_seq = list(range(1, 9)) + [1, 2, 3]  # cc=1..8, then reset to 1
        rounds = _make_synthetic_bcm_rounds(cc_seq)
        peaks = compute_robot_cycle_peaks(rounds)
        assert peaks == [], (
            f"Expected [] (peak=8 ≤ 10, should NOT be recorded), got {peaks}.\n"
            "Likely cause: using old buggy rule (prev >= 5) instead of (prev > 10).\n"
            "Inject-bug B: flip condition to 'cc < prev-1 and prev >= 5' → RED here."
        )

    def test_single_step_drop_recorded(self) -> None:
        """A single-step drop IS recorded: ANY drop < prev, not < prev-1.

        Setup: cc goes 1..50, then cc=49 (one step down).
        Correct rule: cc(49) < prev(50) → True, prev(50) > 10 → True → RECORDS peak 50.
        Old buggy rule: cc(49) < prev(50)-1=49 → False (49 < 49 is False) → MISSES it.

        Inject-bug B: change to old rule → this test goes RED (would get []).
        """
        cc_seq = list(range(1, 51)) + [49, 50, 49]  # 50→49 is a single-step drop
        rounds = _make_synthetic_bcm_rounds(cc_seq)
        peaks = compute_robot_cycle_peaks(rounds)
        assert 50 in peaks, (
            f"Expected 50 in peaks (single-step drop from 50→49 MUST be recorded), "
            f"got {peaks}.\n"
            "Likely cause: using old buggy rule (cc < prev-1) instead of (cc < prev).\n"
            "Inject-bug B: flip condition to 'cc < prev-1 and prev >= 5' → RED here."
        )

    def test_initial_prev_zero_means_no_false_peak_at_start(self) -> None:
        """First paid round cc > 0: prev=0, so cc < prev = cc < 0 → False.

        No spurious peak at the very start of the robot.
        """
        rounds = _make_synthetic_bcm_rounds([500, 501, 502])
        peaks = compute_robot_cycle_peaks(rounds)
        assert peaks == [], f"Expected [], got {peaks}"

    def test_m274_cc_zero_machine_no_peaks(self) -> None:
        """M274 (cc=0 machine): CollectCount=0 on all paid rounds → no peaks."""
        rounds = [
            {
                "SpinType": 140, "CostCredits": 1000, "WinCredits": 0,
                "BetAmount": 1000, "CollectCount": 0,
                "AccCredits": 0, "CreditsSymbols": "", "SymbolIndexToRewards": {},
            }
            for _ in range(50)
        ]
        assert compute_robot_cycle_peaks(rounds) == []

    @_SKIP_NO_M272
    def test_m272_real_rounds_produces_peaks(self) -> None:
        """M272 real rawdata (chunk 0002): cycle peaks recorded across robots.

        M272 mode 1 has 1000-paid-spin cycles. Chunk 0002 robots span MORE than
        one cycle, so resets are observable. Verifies the function fires on real data
        with the exact expected peak value of 1000.
        """
        d = _RAWDATA_DIR / "M272" / "mode_1"
        chunks = sorted(d.glob("chunk_*.json"))
        if len(chunks) < 2:
            pytest.skip("M272 has only 1 chunk; need 2 for reset-visible data")

        chunk2 = json.loads(chunks[1].read_text(encoding="utf-8"))
        resp = chunk2["response"]

        all_peaks: list[int] = []
        for robot in resp:
            raw = robot.get("roundResult")
            rounds = json.loads(raw) if isinstance(raw, str) else (raw or [])
            all_peaks.extend(compute_robot_cycle_peaks(rounds))

        assert len(all_peaks) >= 1, (
            f"Expected at least 1 cycle peak across all robots in M272 chunk 0002, "
            f"got 0. compute_robot_cycle_peaks is not firing on real M272 data."
        )
        for p in all_peaks:
            assert p == 1000, (
                f"Peak {p} unexpected for M272 mode 1 (expected exactly 1000).\n"
                "If the rule condition is wrong, this would show a different value."
            )

    def test_both_old_and_new_rule_agree_on_large_drop(self) -> None:
        """For large real-pilot cycles, both rules agree — explains why inject-bug
        was latent on real pilots (M272 cycle=1000: drop of 999 >> 1 step).

        cc=1..1000 → reset to 1: both rules record peak=1000.
        - Correct (cc < prev): 1 < 1000 → True; 1000 > 10 → True → records.
        - Old buggy (cc < prev-1): 1 < 999 → True; 1000 >= 5 → True → also records.
        """
        cc_seq = list(range(1, 1001)) + [1]
        rounds = _make_synthetic_bcm_rounds(cc_seq)
        peaks = compute_robot_cycle_peaks(rounds)
        assert 1000 in peaks, f"Expected 1000 in peaks for large cycle, got {peaks}"
