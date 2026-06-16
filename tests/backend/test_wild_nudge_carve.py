"""Isolation regression test for the wild-nudge carve (PT-7).

Pins the property the play-type refactor exists to deliver: the wild-nudge
mechanic logic (``is_wild_nudge_round``) lives OUTSIDE the ``base_hash`` closure,
so editing it does NOT re-flag the fleet. Contrast: editing a universal function
that is still in ``round_classification.py`` DOES flip ``base_hash``.

This is the objective gate that C2's "carve" failed (the BCM cycle logic stayed
in the closure, so editing it still re-flagged everyone). If a future change
moves ``is_wild_nudge_round`` back into a closure file, or adds ``wild_nudge.py``
to ``_CLOSURE_FILES``, the first test below goes RED — catching a regression to
the hollow-carve mistake.
"""
from __future__ import annotations

import hashlib

from fresh_slotlab.analyzer.versioning import (
    _CLOSURE_FILES,
    _REPO_ROOT,
    compute_base_analyzer_version,
)
from fresh_slotlab.analyzer.play_types.wild_nudge import is_wild_nudge_round

_WILD_NUDGE_REL = "fresh_slotlab/analyzer/play_types/wild_nudge.py"
_ROUND_CLASS_REL = "fresh_slotlab/round_classification.py"


def _base_hash_with_simulated_edit(edit_rel: str, suffix: bytes) -> str:
    """Recompute base_hash, appending *suffix* to *edit_rel* if (and only if)
    it is in the closure. Mirrors ``compute_base_analyzer_version`` exactly
    (sorted order, CRLF->LF, sha256[:12])."""
    h = hashlib.sha256()
    for rel in sorted(_CLOSURE_FILES):
        raw = (_REPO_ROOT / rel).read_bytes().replace(b"\r\n", b"\n")
        if rel == edit_rel:
            raw = raw + suffix
        h.update(raw)
    return h.hexdigest()[:12]


class TestWildNudgeLivesOutsideClosure:
    def test_function_home_is_the_plugin_module(self) -> None:
        # The function's bytes live in wild_nudge.py, not round_classification.
        assert is_wild_nudge_round.__module__.endswith("play_types.wild_nudge")

    def test_wild_nudge_file_not_in_base_closure(self) -> None:
        assert _WILD_NUDGE_REL not in _CLOSURE_FILES

    def test_round_classification_still_in_base_closure(self) -> None:
        # Universal A-class helpers stay in the base; their edits SHOULD re-flag.
        assert _ROUND_CLASS_REL in _CLOSURE_FILES


class TestEditingWildNudgeDoesNotReflagFleet:
    def test_editing_wild_nudge_logic_leaves_base_hash_unchanged(self) -> None:
        baseline = compute_base_analyzer_version()
        # Simulate editing the wild-nudge detection logic. Because wild_nudge.py
        # is NOT in the closure, the edit cannot change base_hash → no machine
        # re-flags. THIS is the isolation C2 failed to achieve.
        after = _base_hash_with_simulated_edit(
            _WILD_NUDGE_REL, b"\n# simulate editing the wild-nudge rule\n"
        )
        assert after == baseline, (
            "Editing wild_nudge.py changed base_hash — the mechanic logic "
            "leaked back into the closure (hollow-carve regression)."
        )

    def test_editing_a_universal_function_still_flips_base_hash(self) -> None:
        baseline = compute_base_analyzer_version()
        # Paired check: a universal function still in the closure MUST re-flag.
        # Guards against faking isolation by yanking round_classification.py out
        # of the closure entirely (which would silence legitimate universal edits).
        after = _base_hash_with_simulated_edit(
            _ROUND_CLASS_REL, b"\n# simulate editing a universal helper\n"
        )
        assert after != baseline, (
            "Editing round_classification.py did NOT change base_hash — "
            "universal logic is no longer hashed (over-isolation)."
        )


class TestWildNudgeBehaviorPreserved:
    """The move must not change behavior — same signals as the original."""

    def test_nudge_round_detected(self) -> None:
        assert is_wild_nudge_round(
            {"CostCredits": 0, "ReMarks": "move", "SpinType": 36}
        ) is True

    def test_nudge_word_boundary_case_insensitive(self) -> None:
        assert is_wild_nudge_round({"CostCredits": None, "ReMarks": "Wild Nudge"}) is True

    def test_paid_round_not_nudge(self) -> None:
        assert is_wild_nudge_round({"CostCredits": 100, "ReMarks": "move"}) is False

    def test_no_remark_not_nudge(self) -> None:
        assert is_wild_nudge_round({"CostCredits": 0}) is False

    def test_substring_not_word_boundary_not_nudge(self) -> None:
        # "MoveSpinTrigger" is a feature name, not a nudge marker.
        assert is_wild_nudge_round({"CostCredits": 0, "ReMarks": "MoveSpinTrigger"}) is False

    def test_non_dict_not_nudge(self) -> None:
        assert is_wild_nudge_round(None) is False
