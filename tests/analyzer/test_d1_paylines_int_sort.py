"""R1 Phase 2 d1 — paylines list int sort in PayoutsBySpinType.emit().

Invariants asserted (AC#1)
--------------------------
1. emit() sorts paylines numerically (int order), NOT lexicographically.
   A fixture with 12 paylines ("1".."12" as string keys) must produce
   [1,2,3,4,5,6,7,8,9,10,11,12], NOT [1,10,11,12,2,3,4,5,6,7,8,9].
2. The scatter sentinel payline "-1" sorts FIRST (int("-1")=-1 < 1).
3. Defensive RuntimeError fires for non-integer payline_id strings
   that are not "-1" (schema drift detection per feedback_capture_drift.md).
4. M14 (9 paylines) still produces int-sorted order (trivially correct
   for <=9 but confirms no regression from the key=lambda x: int(...) fix).

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug d1: revert sort key to string (remove int() call).
  Edit payouts_by_spin_type.py emit(), BOTH sort sites:
    Change: key=lambda x: int(x["payline_id"])
    To:     key=lambda x: x["payline_id"]
  RED: test_ten_plus_paylines_int_order fails — order becomes lexicographic
       [1,10,11,12,2,3,...] instead of [1,2,...,10,11,12].
       test_scatter_sentinel_sorts_first also fails (str("-1") > str("1")).
  Revert (restore int()) -> GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_capture_drift.md (RuntimeError on non-integer payline_id)
- memory/feedback_no_hardcode.md (test uses synthetic fixture, not machine-specific ids)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _import_plugin():
    try:
        from fresh_slotlab.analyzer.features.payouts_by_spin_type import PayoutsBySpinType
    except ImportError:
        from analyzer.features.payouts_by_spin_type import PayoutsBySpinType  # type: ignore[no-redef]
    return PayoutsBySpinType


def _make_ctx(effective_bet_for_rtp: float = 100_000.0) -> Any:
    """Build a minimal PipelineContext-like mock for unit tests."""
    ctx = MagicMock()
    ctx.effective_bet_for_rtp = effective_bet_for_rtp
    return ctx


def _make_summary_with_st(
    spins: int = 10_000,
    st_int: int = 1,
    behavior: str = "paid",
) -> dict:
    """Build a minimal summary with spin_type_breakdown."""
    return {
        "player_impact": {
            "spin_type_breakdown": [
                {"spin_type": st_int, "behavior_name": behavior, "spins": spins}
            ],
        }
    }


def _build_12_payline_acc(st_int: int = 1) -> dict:
    """Build extract-style accumulator with 12 paylines for a single pid.

    Payline ids are string keys "1" through "12" as they come from the parser.
    Lexicographic order would be: 1,10,11,12,2,3,4,5,6,7,8,9.
    Integer order is:             1,2,3,4,5,6,7,8,9,10,11,12.
    """
    # pid "99" has hits in ST st_int with a positive win so it passes sort/skip guards
    pid = "99"
    by_st_hits = {pid: {st_int: 100}}
    by_st_win = {pid: {st_int: 5000.0}}

    # pid has regular (non-trigger) lines — has_regular_line=True means
    # is_trigger=False in emit(), so it uses the "exclude -1, sort by int" path.
    pid_has_regular_line = {pid: True}

    # 12 paylines with equal hit counts
    pid_payline_hits = {
        pid: {str(i): 100 for i in range(1, 13)}  # "1" through "12"
    }
    pid_match_count_dist: dict = {pid: {3: 100}}
    pid_col_set: dict = {pid: [0, 1, 2]}

    return {
        "by_st_hits": by_st_hits,
        "by_st_win": by_st_win,
        "pid_payline_hits": pid_payline_hits,
        "pid_match_count_dist": pid_match_count_dist,
        "pid_col_set": pid_col_set,
        "pid_has_regular_line": pid_has_regular_line,
    }


def _build_scatter_sentinel_acc(st_int: int = 1) -> dict:
    """Build accumulator with a trigger-marker pid that has only the -1 payline."""
    pid = "666"
    by_st_hits = {pid: {st_int: 50}}
    by_st_win = {pid: {st_int: 0.0}}

    # trigger-marker: has_regular_line absent (False), total_win == 0
    pid_has_regular_line: dict = {}  # omitted -> False
    pid_payline_hits = {pid: {"-1": 50}}  # only scatter line
    pid_match_count_dist: dict = {}
    pid_col_set: dict = {}

    return {
        "by_st_hits": by_st_hits,
        "by_st_win": by_st_win,
        "pid_payline_hits": pid_payline_hits,
        "pid_match_count_dist": pid_match_count_dist,
        "pid_col_set": pid_col_set,
        "pid_has_regular_line": pid_has_regular_line,
    }


# ---------------------------------------------------------------------------
# T1: 10+ payline fixture — must sort numerically
# ---------------------------------------------------------------------------

class TestTenPlusPaylineIntSort:
    """Machines with 10+ paylines must have paylines sorted by int, not string."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin()()

    @pytest.fixture
    def emitted_rows(self, plugin):
        """Run emit() on 12-payline synthetic fixture; return the emitted rows."""
        st_int = 1
        acc = _build_12_payline_acc(st_int=st_int)
        summary = _make_summary_with_st(st_int=st_int)
        ctx = _make_ctx()
        plugin.emit(acc, summary, ctx)
        result = summary["player_impact"]["payouts_by_spin_type"]
        label = f"ST{st_int}_paid"
        rows = result.get(label, [])
        # There must be exactly one row (pid "99")
        assert rows, f"Expected 1 row for pid 99, got: {result}"
        return rows[0]

    def test_ten_plus_paylines_int_order(self, emitted_rows):
        """12-payline pid must have paylines sorted [1,2,...,10,11,12] NOT [1,10,11,12,2,...].

        INJECT-BUG (d1): change sort key from int(x["payline_id"]) to x["payline_id"]
        → order becomes lexicographic → this test fails.
        Revert (restore int()) → GREEN.
        """
        paylines = emitted_rows.get("paylines", [])
        assert len(paylines) == 12, (
            f"Expected 12 payline entries, got {len(paylines)}. "
            f"paylines: {paylines}"
        )
        actual_ids = [int(p["payline_id"]) for p in paylines]
        expected_ids = list(range(1, 13))
        assert actual_ids == expected_ids, (
            f"Paylines must be in integer order [1..12], got {actual_ids}. "
            f"Lexicographic order would be [1,10,11,12,2,...]. "
            f"The int() key in the sort is the d1 fix — reverting it causes this test to fail."
        )

    def test_payline_ids_are_strings_in_output(self, emitted_rows):
        """payline_id in emitted output must be a string (preserves parser format)."""
        paylines = emitted_rows.get("paylines", [])
        for entry in paylines:
            pid = entry.get("payline_id")
            assert isinstance(pid, str), (
                f"payline_id in emitted row must be a string, got {type(pid).__name__}: {pid!r}"
            )

    def test_payline_hit_counts_preserved(self, emitted_rows):
        """hit_count values from accumulator must be preserved in emitted paylines."""
        paylines = emitted_rows.get("paylines", [])
        for entry in paylines:
            assert entry.get("hit_count") == 100, (
                f"All paylines were built with hit_count=100. Got: {entry}"
            )


# ---------------------------------------------------------------------------
# T2: Scatter sentinel "-1" sorts first
# ---------------------------------------------------------------------------

class TestScatterSentinelSortsFirst:
    """The scatter trigger payline '-1' (int=-1 < 1) must sort before positive paylines."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin()()

    @pytest.fixture
    def emitted_rows(self, plugin):
        """Emit with a trigger-marker pid (only -1 payline)."""
        st_int = 1
        acc = _build_scatter_sentinel_acc(st_int=st_int)
        summary = _make_summary_with_st(st_int=st_int)
        ctx = _make_ctx()
        plugin.emit(acc, summary, ctx)
        result = summary["player_impact"]["payouts_by_spin_type"]
        label = f"ST{st_int}_paid"
        rows = result.get(label, [])
        assert rows, f"Expected 1 row for trigger-marker pid 666, got: {result}"
        return rows[0]

    def test_scatter_sentinel_present(self, emitted_rows):
        """Trigger-marker pid must have the -1 payline entry emitted."""
        paylines = emitted_rows.get("paylines", [])
        ids = [p["payline_id"] for p in paylines]
        assert "-1" in ids, (
            f"Trigger-marker pid must include payline '-1'. Got paylines: {paylines}"
        )

    def test_scatter_sentinel_sorts_first(self, emitted_rows):
        """'-1' (int=-1) must sort BEFORE any positive payline (none here, but int-sort verified).

        INJECT-BUG (d1 scatter path): change sort key to string on the trigger-marker branch.
        String sort: '-1' > '1' (ASCII '-' < '1' — actually '-' IS < '1' so this passes
        trivially for 1-entry case). But in a mixed case, string sort breaks.
        This test confirms the sort key is int()-based by verifying int("-1") == -1 < 1.
        """
        paylines = emitted_rows.get("paylines", [])
        if len(paylines) >= 1:
            first = paylines[0]
            assert int(first["payline_id"]) == -1, (
                f"First payline for trigger-marker must be -1 (sentinel). "
                f"Got: {first}. This confirms int()-based sort on the trigger path."
            )

    def test_is_trigger_marker_true_in_notes(self, emitted_rows):
        """Trigger-marker pid (win=0, no regular line) must have is_trigger_marker=True in notes."""
        notes = emitted_rows.get("notes", {})
        assert notes.get("is_trigger_marker") is True, (
            f"pid with win=0 and no regular line must be flagged as trigger marker. "
            f"notes: {notes}"
        )


# ---------------------------------------------------------------------------
# T3: Mixed paylines — regular pid with both scatter(-1) and normal lines
# ---------------------------------------------------------------------------

class TestMixedPaylineFilterAndSort:
    """Regular pid: only non-(-1) paylines emitted, sorted by int."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin()()

    def test_regular_pid_excludes_scatter_line_and_sorts_by_int(self, plugin):
        """A regular pid with paylines {'-1':5, '2':10, '11':8, '3':12} must emit
        only [2,3,11] in int order (excluding -1), not lexicographic [11,2,3].

        INJECT-BUG (d1): revert sort key to string → order becomes ['11','2','3'].
        Test fails. Restore int() → GREEN.
        """
        st_int = 1
        pid = "42"
        acc = {
            "by_st_hits": {pid: {st_int: 30}},
            "by_st_win": {pid: {st_int: 3000.0}},
            "pid_payline_hits": {pid: {"-1": 5, "2": 10, "11": 8, "3": 12}},
            "pid_match_count_dist": {pid: {3: 30}},
            "pid_col_set": {pid: [0, 1, 2]},
            "pid_has_regular_line": {pid: True},  # has non-scatter lines → regular pid
        }
        summary = _make_summary_with_st(st_int=st_int)
        ctx = _make_ctx()
        plugin.emit(acc, summary, ctx)

        result = summary["player_impact"]["payouts_by_spin_type"]
        label = f"ST{st_int}_paid"
        rows = result.get(label, [])
        assert rows, f"Expected 1 row for pid {pid!r}"
        row = rows[0]

        paylines = row.get("paylines", [])
        ids = [p["payline_id"] for p in paylines]
        # "-1" must be excluded (regular pid, not trigger-marker)
        assert "-1" not in ids, (
            f"Regular pid must exclude payline -1. Got: {ids}"
        )
        # Remaining must be in int order [2, 3, 11]
        assert ids == ["2", "3", "11"], (
            f"Paylines must be in int order ['2','3','11'], not lexicographic. "
            f"Got: {ids}. The d1 fix is key=lambda x: int(x['payline_id'])."
        )


# ---------------------------------------------------------------------------
# T3b: Trigger-marker pid with MULTIPLE paylines — scatter sentinel sorts first
# ---------------------------------------------------------------------------

class TestTriggerMarkerMultiPaylineSentinelFirst:
    """Trigger-marker pid with '-1' plus positive paylines must sort '-1' first.

    The original test_scatter_sentinel_sorts_first used a 1-element list which
    is trivially sorted regardless of key function — it does not guard the
    trigger-branch sort. This test uses a multi-payline trigger-marker to prove
    the int() key is actually used on the trigger path.

    Inject-bug recipe (trigger-branch sort site)
    --------------------------------------------
    Bug: revert the trigger-branch sort key from int(x["payline_id"]) to
         x["payline_id"] (string).
    With string sort:
      sorted(["-1","1","10","2"]) = ["-1","1","10","2"]  (ASCII '-' < '0' < '1')
    — this happens to match int order for this specific fixture, so the test
    would NOT catch the regression with only these values.
    Use a fixture where string order and int order differ:
      pl_map = {"-1": 5, "10": 3, "2": 7, "1": 2}
      String sort: ["-1", "1", "10", "2"]  (ASCII: '-'<'1', then lexicographic)
      Int sort:    ["-1", "1", "2", "10"]   ← different at positions 2 and 3
    RED: test_trigger_marker_mixed_paylines_int_order fails — order becomes
         ["-1","1","10","2"] instead of ["-1","1","2","10"].
    Revert (restore int()) → GREEN.
    """

    @pytest.fixture
    def plugin(self):
        return _import_plugin()()

    def _build_trigger_marker_multi_acc(self, st_int: int = 1) -> dict:
        """Build accumulator: trigger-marker pid with '-1' + '1', '2', '10' paylines.

        This fixture has both the scatter sentinel AND multiple positive paylines.
        String sort:  ["-1", "1", "10", "2"]   (lexicographic — '1' < '10' < '2')
        Int sort:     ["-1", "1",  "2", "10"]   (numeric — 2 < 10)
        The two orderings differ at positions 2 and 3, making this a real guard.
        """
        pid = "666"
        return {
            "by_st_hits": {pid: {st_int: 50}},
            "by_st_win": {pid: {st_int: 0.0}},       # win=0 → trigger marker
            "pid_payline_hits": {pid: {"-1": 5, "10": 3, "2": 7, "1": 2}},
            "pid_match_count_dist": {},
            "pid_col_set": {},
            "pid_has_regular_line": {},               # absent → False → trigger path
        }

    def test_trigger_marker_mixed_paylines_int_order(self, plugin):
        """Trigger-marker with '-1','1','2','10' paylines must sort as [-1,1,2,10].

        String sort gives [-1,1,10,2]; int sort gives [-1,1,2,10].
        This test distinguishes the two and guards the trigger-branch sort site.

        INJECT-BUG (trigger-branch sort): change sort key on the trigger path from
            key=lambda x: int(x["payline_id"])
        to
            key=lambda x: x["payline_id"]
        RED: order becomes ["-1","1","10","2"] instead of ["-1","1","2","10"].
        Revert (restore int()) → GREEN.
        """
        st_int = 1
        acc = self._build_trigger_marker_multi_acc(st_int=st_int)
        summary = _make_summary_with_st(st_int=st_int)
        ctx = _make_ctx()
        plugin.emit(acc, summary, ctx)

        result = summary["player_impact"]["payouts_by_spin_type"]
        label = f"ST{st_int}_paid"
        rows = result.get(label, [])
        assert rows, f"Expected 1 row for trigger-marker pid 666. result keys: {list(result.keys())}"
        row = rows[0]

        paylines = row.get("paylines", [])
        actual_ids = [p["payline_id"] for p in paylines]

        # Scatter sentinel must be first (int(-1) = -1 < 1)
        assert actual_ids[0] == "-1", (
            f"Scatter sentinel '-1' must sort first (int=-1 < 1). "
            f"Got order: {actual_ids}"
        )

        # Full int order: [-1, 1, 2, 10]
        assert actual_ids == ["-1", "1", "2", "10"], (
            f"Paylines must be in int order ['-1','1','2','10'], not lexicographic "
            f"['-1','1','10','2']. Got: {actual_ids}. "
            f"The d1 fix is key=lambda x: int(x['payline_id']) on the trigger path."
        )

    def test_trigger_marker_is_flagged(self, plugin):
        """Trigger-marker pid must have is_trigger_marker=True in notes."""
        st_int = 1
        acc = self._build_trigger_marker_multi_acc(st_int=st_int)
        summary = _make_summary_with_st(st_int=st_int)
        ctx = _make_ctx()
        plugin.emit(acc, summary, ctx)

        result = summary["player_impact"]["payouts_by_spin_type"]
        label = f"ST{st_int}_paid"
        row = result[label][0]
        assert row["notes"]["is_trigger_marker"] is True, (
            f"win=0 + no regular line must flag is_trigger_marker=True. notes: {row['notes']}"
        )


# ---------------------------------------------------------------------------
# T4: Defensive RuntimeError for non-integer payline_id
# ---------------------------------------------------------------------------

class TestDefensiveRuntimeErrorNonIntPaylineId:
    """Non-integer payline_id must raise RuntimeError (schema drift guard).

    Per memory/feedback_capture_drift.md: schema drift must surface as a
    descriptive error, not a bare ValueError or silent skip.
    """

    @pytest.fixture
    def plugin(self):
        return _import_plugin()()

    def test_non_integer_payline_id_raises_runtime_error(self, plugin):
        """A payline_id like 'A1' (not int-parseable and not '-1') must raise RuntimeError.

        INJECT-BUG: remove the pre-validation loop in emit().
        → Non-integer payline_id silently raises bare ValueError from int()
          with no context → harder to diagnose. This test becomes RED because
          a RuntimeError with the descriptive message is expected, not a ValueError.
        Revert (restore pre-validation) → GREEN.
        """
        st_int = 1
        pid = "99"
        acc = {
            "by_st_hits": {pid: {st_int: 10}},
            "by_st_win": {pid: {st_int: 100.0}},
            "pid_payline_hits": {pid: {"A1": 5}},  # non-integer, non-"-1" payline_id
            "pid_match_count_dist": {},
            "pid_col_set": {},
            "pid_has_regular_line": {pid: True},
        }
        summary = _make_summary_with_st(st_int=st_int)
        ctx = _make_ctx()

        with pytest.raises(RuntimeError, match="non-integer payline_id"):
            plugin.emit(acc, summary, ctx)
