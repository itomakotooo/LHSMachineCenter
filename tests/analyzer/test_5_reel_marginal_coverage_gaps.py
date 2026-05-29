"""Phase 5 — synthetic-input units for the carved branches the M275/M14 goldens MISS.

COVERAGE-GAP CLOSER (the 2b ``_quantiles``-index lesson / the 3
chain-confidence-ladder lesson / the 4 zero-spin-divisor lesson; see
session_artifacts/_impl/phase_extract_4_multiplier_profile/inject_bug_evidence.md
§Coverage-gap).

The byte-identity goldens (M275 + M14 in
test_5_byte_identical_reel_marginal_carve.py) lock the carved dict-build
leaf-by-leaf, but the two sample machines exercise ONLY the fully-populated path:

  - M275: 2 SpinType labels (ST126_free, ST140_paid), each with 3 reel columns,
    every column non-empty (col_total > 0).
  - M14:  1 SpinType label (ST1_paid), 3 columns, every column non-empty.

So several arms of the moved build are NEVER exercised by either golden.  A
regression in any of them would leave BOTH byte-identity deep-diffs GREEN.  This
file pins each with a synthetic stash + breakdown.

Branch enumeration of the moved build (deliverable #3 "hunt for any OTHER
unexercised branch") — reel_marginal_by_spin_type.py emit(), the
``for st_int, label in sorted(_st_label.items())`` loop:

  (1) ``_st_label`` EMPTY  ->  whole dict is ``{}``                  [golden-missed]
        Driver: spin_type_breakdown == []  (no labels at all).
        Real machines always have >= 1 SpinType, so the goldens never hit this.

  (2) ``reel_marginal_by_spin_type[label] = {}``  (label kept, NO surviving cols)
        Two sub-causes, BOTH golden-missed:
        (2a) ``st_col_map = ...get(st_int) or {}`` -> the ``or {}`` arm
             (the label exists in _st_label but NOT in the accumulator).
        (2b) the accumulator HAS the st_int but every column has col_total == 0
             (the ``if col_total == 0: continue`` skips them all).
        Either way the label still gets an (empty) entry — matching the pre-carve
        dict (the markdown consumer then skips empty col_rows; see PIA ~5069).

  (3) ``if col_total == 0: continue``  with SOME surviving columns          [golden-missed]
        A mix of zero-total and non-zero-total columns under one label: the zero
        ones are dropped, the non-zero ones survive. Real machines have no
        all-zero surviving column, so the goldens never drive a partial skip.

  (4) count-descending sort with a TIE
        ``sorted(sym_map.items(), key=lambda kv: kv[1], reverse=True)`` — pinned so
        a flipped ``reverse`` or a wrong sort key is caught locally (the goldens
        cover sorting only via their specific real distributions).

  The leaves inside a surviving row (``symbol`` / ``int(count)`` / ``prob_pct =
  (cnt/col_total)*100``) are unconditional and covered byte-identically by the
  goldens; pinned here too as fast-localized regression signals.

Inject-bug recipes (per feedback_enumerate_safety_paths.md) — verified 2026-05-30
(RED->revert->GREEN while the byte-identity goldens stay GREEN; evidence in
inject_bug_evidence.md §Coverage-gap):

  empty-label-map arm (branch 1):
    -  reel_marginal_by_spin_type[label] = col_rows   (loop body never runs)
    -> change ``for st_int, label in sorted(_st_label.items())`` to iterate a
       hard-coded ``[(0, "X")]`` (BUG): test_empty_breakdown_yields_empty_dict RED
       (produces {"X": {}} instead of {}). Goldens stay GREEN.

  col_total==0 skip removal (branches 2b/3):
    -  if col_total == 0:
    -      continue
    +  pass  # BUG (no skip)
    -> test_zero_total_column_is_skipped RED (an empty/degenerate column survives
       with a ZeroDivisionError or an empty row list). Goldens stay GREEN (no
       all-zero surviving column on either machine).

  sort-direction flip (branch 4):
    -  sorted(sym_map.items(), key=lambda kv: kv[1], reverse=True)
    +  sorted(sym_map.items(), key=lambda kv: kv[1])                     # BUG
    -> test_rows_sorted_count_descending RED (ascending order). Goldens ALSO go
       RED on real data (they lock the order), but this localizes it instantly.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md
    each branch of the moved compute needs its own inject-bug-provable test; the
    empty-label / empty-col / col-skip arms are golden-missed safety paths.
- memory/feedback_perf_claim_needs_e2e_event_stream.md
    the 2b _quantiles-index gap: the 2 sample machines' data can leave whole
    branches uncovered; synthetic inputs spanning those branches are required.
- memory/feedback_invariant_with_fallback_hides_drift.md
    a label silently dropped (vs kept-with-empty-dict) is exactly the
    absent-vs-present drift the structural goldens miss but a typed assertion
    catches; the empty-col_rows entry must be PRESENT (the markdown consumer skips
    it, but the JSON contract keeps it).
"""
from __future__ import annotations

from typing import Any

import pytest


def _import_plugin_class():
    try:
        from fresh_slotlab.analyzer.features.reel_marginal_by_spin_type import (
            ReelMarginalBySpinType,
        )
    except ImportError:  # running as standalone script
        from analyzer.features.reel_marginal_by_spin_type import (  # type: ignore[no-redef]
            ReelMarginalBySpinType,
        )
    return ReelMarginalBySpinType


def _emit(accumulator: dict[int, dict[int, dict[str, int]]],
          breakdown: list[dict[str, Any]]) -> dict:
    """Run the plugin emit() with a synthetic accumulator + spin_type_breakdown.

    ``accumulator`` is the raw symbol_counts_by_col_by_spin_type_total
    ({st_int: {col_int: {symbol: count}}}); ``breakdown`` is the
    spin_type_breakdown rows the plugin re-derives _st_label from.
    Returns the built reel_marginal_by_spin_type dict.
    """
    plugin = _import_plugin_class()()
    summary: dict[str, Any] = {
        "_reel_marginal_by_spin_type_data": {
            "symbol_counts_by_col_by_spin_type_total": accumulator,
        },
        "player_impact": {"spin_type_breakdown": breakdown},
    }
    plugin.emit({}, summary, None)
    return summary["player_impact"]["reel_marginal_by_spin_type"]


# ---------------------------------------------------------------------------
# Branch 1: empty spin_type_breakdown -> empty _st_label -> empty dict
# ---------------------------------------------------------------------------

class TestEmptyBreakdownEmptyDict:
    """An empty spin_type_breakdown must yield an empty reel_marginal dict.

    Neither golden machine has zero SpinTypes, so the empty-label-map arm
    (the outer loop never runs) is uncovered by the byte-identity tests.
    """

    def test_empty_breakdown_yields_empty_dict(self):
        """spin_type_breakdown == [] -> reel_marginal_by_spin_type == {}.

        INJECT-BUG: make the outer loop iterate a hard-coded non-empty list (so a
        label leaks in despite the empty breakdown). RED here; goldens GREEN.
        """
        rm = _emit(accumulator={1: {0: {"A": 5}}}, breakdown=[])
        assert rm == {}, (
            f"empty spin_type_breakdown must produce an empty dict (the _st_label "
            f"map is empty -> the outer loop never runs). Got {rm!r}"
        )

    def test_empty_breakdown_is_a_plain_dict(self):
        """The empty result must be a dict (not None / not a list)."""
        rm = _emit(accumulator={}, breakdown=[])
        assert isinstance(rm, dict) and rm == {}


# ---------------------------------------------------------------------------
# Branch 2a: label present in _st_label but absent from the accumulator
#            -> `...get(st_int) or {}` arm -> reel_marginal[label] = {}
# ---------------------------------------------------------------------------

class TestLabelAbsentFromAccumulator:
    """A label with no accumulator entry must still get an EMPTY col_rows dict.

    The pre-carve build always assigned ``reel_marginal_by_spin_type[label] =
    col_rows`` (even when col_rows is empty), so the label is PRESENT with ``{}``.
    A regression that dropped such labels (e.g. ``if col_rows:`` before the
    assignment) would diverge from the pre-carve dict — but the goldens never hit
    this (every M275/M14 label is in the accumulator).
    """

    def test_label_without_accumulator_entry_is_present_empty(self):
        """st in breakdown but NOT in accumulator -> {label: {}} (present, empty).

        Exercises the ``st_col_map = ...get(st_int) or {}`` fallback arm.
        """
        rm = _emit(
            accumulator={},  # accumulator has NO entry for st=1
            breakdown=[{"spin_type": 1, "behavior_name": "paid"}],
        )
        assert "ST1_paid" in rm, (
            f"a label absent from the accumulator must still be PRESENT with an "
            f"empty col_rows (matches the pre-carve dict). Got {rm!r}"
        )
        assert rm["ST1_paid"] == {}, (
            f"the label's col_rows must be the empty dict, not dropped/None. "
            f"Got {rm['ST1_paid']!r}"
        )

    def test_mixed_present_and_absent_labels(self):
        """Two labels: one in the accumulator (populated), one absent (empty).

        Confirms a populated label and an empty label co-exist in one build —
        the empty one is kept with {} (not dropped, not crashing the populated one).
        """
        rm = _emit(
            accumulator={2: {0: {"A": 3, "B": 1}}},  # only st=2 populated
            breakdown=[
                {"spin_type": 1, "behavior_name": "free"},  # absent -> {}
                {"spin_type": 2, "behavior_name": "paid"},  # present
            ],
        )
        assert rm["ST1_free"] == {}
        assert rm["ST2_paid"] == {"0": [
            {"symbol": "A", "count": 3, "prob_pct": (3 / 4) * 100.0},
            {"symbol": "B", "count": 1, "prob_pct": (1 / 4) * 100.0},
        ]}
        # Outer order = sorted by spin_type int (1 before 2).
        assert list(rm.keys()) == ["ST1_free", "ST2_paid"]


# ---------------------------------------------------------------------------
# Branch 2b/3: col_total == 0 skip
# ---------------------------------------------------------------------------

class TestZeroTotalColumnSkip:
    """Columns whose symbol counts sum to 0 must be SKIPPED (the ``continue`` arm).

    No golden machine has an all-zero surviving column, so the skip arm is
    uncovered by the byte-identity tests. A regression removing the guard would
    either keep an empty column or raise ZeroDivisionError on the prob_pct divide.
    """

    def test_zero_total_column_is_skipped(self):
        """A column whose counts sum to 0 must NOT appear in col_rows.

        INJECT-BUG: replace ``if col_total == 0: continue`` with ``pass``. RED:
        the zero column survives (empty row list or ZeroDivisionError). Goldens
        GREEN (no all-zero surviving column on either machine).
        """
        rm = _emit(
            accumulator={1: {
                0: {"A": 5, "B": 3},  # col_total = 8 -> survives
                1: {"A": 0, "B": 0},  # col_total = 0 -> skipped
            }},
            breakdown=[{"spin_type": 1, "behavior_name": "paid"}],
        )
        assert list(rm["ST1_paid"].keys()) == ["0"], (
            f"col 1 (all-zero) must be skipped; only col 0 survives. "
            f"Got cols {list(rm['ST1_paid'].keys())}"
        )

    def test_all_columns_zero_yields_empty_col_rows(self):
        """If EVERY column under a label sums to 0, col_rows is {} (label kept).

        Combines branch 2b (label present in accumulator) with the col-skip: all
        columns dropped -> empty col_rows -> ``reel_marginal[label] = {}`` (still
        present, matching the pre-carve dict).
        """
        rm = _emit(
            accumulator={1: {0: {"A": 0}, 1: {"B": 0}}},
            breakdown=[{"spin_type": 1, "behavior_name": "paid"}],
        )
        assert "ST1_paid" in rm
        assert rm["ST1_paid"] == {}, (
            f"all-zero columns -> empty col_rows (label kept). Got {rm['ST1_paid']!r}"
        )

    def test_zero_total_column_does_not_divide_by_zero(self):
        """The col_total == 0 skip is a safety path (no ZeroDivisionError).

        The prob_pct divide ``cnt / col_total`` would raise on a zero total; the
        ``continue`` guard short-circuits before the divide. A regression removing
        the guard surfaces as a feature error / crash — the goldens cannot catch it
        (no all-zero surviving column).
        """
        # Must not raise; the zero column is simply absent.
        rm = _emit(
            accumulator={1: {0: {"X": 0, "Y": 0}}},
            breakdown=[{"spin_type": 1, "behavior_name": "paid"}],
        )
        assert rm["ST1_paid"] == {}


# ---------------------------------------------------------------------------
# Branch 4: count-descending sort + the unconditional row leaves
# ---------------------------------------------------------------------------

class TestRowSortAndLeaves:
    """Symbol rows within a column must be count-descending; leaves verbatim."""

    def test_rows_sorted_count_descending(self):
        """Rows must be ordered by count DESC (reverse=True).

        INJECT-BUG: drop ``reverse=True`` from the sort. RED here (ascending);
        goldens ALSO RED on real data, but this localizes it.
        """
        rm = _emit(
            accumulator={1: {0: {"low": 1, "high": 100, "mid": 50}}},
            breakdown=[{"spin_type": 1, "behavior_name": "paid"}],
        )
        rows = rm["ST1_paid"]["0"]
        assert [r["symbol"] for r in rows] == ["high", "mid", "low"], rows
        assert [r["count"] for r in rows] == [100, 50, 1], rows

    def test_count_is_int_and_prob_pct_is_float(self):
        """count must be int(cnt); prob_pct must be the float (cnt/col_total)*100.

        Pins the None-vs-0.0 / int-vs-float forms the byte-identity contract
        preserves. A regression dropping the int() or rewriting the prob_pct form
        is caught here directly.
        """
        rm = _emit(
            accumulator={1: {0: {"A": 30, "B": 10}}},  # col_total = 40
            breakdown=[{"spin_type": 1, "behavior_name": "paid"}],
        )
        rows = rm["ST1_paid"]["0"]
        a = next(r for r in rows if r["symbol"] == "A")
        assert isinstance(a["count"], int) and a["count"] == 30
        assert isinstance(a["prob_pct"], float)
        assert a["prob_pct"] == (30 / 40) * 100.0
        b = next(r for r in rows if r["symbol"] == "B")
        assert b["prob_pct"] == (10 / 40) * 100.0

    def test_prob_pct_sums_to_100_per_column(self):
        """prob_pct must sum to ~100 per (label, column) — the documented invariant.

        (The markdown header asserts "prob_pct sums to 100 per (SpinType, reel)".)
        """
        rm = _emit(
            accumulator={1: {0: {"A": 1, "B": 2, "C": 3, "D": 4}}},  # total 10
            breakdown=[{"spin_type": 1, "behavior_name": "paid"}],
        )
        rows = rm["ST1_paid"]["0"]
        assert abs(sum(r["prob_pct"] for r in rows) - 100.0) < 1e-9

    def test_columns_sorted_by_int_key(self):
        """Columns must be emitted in ascending INT order (sorted(st_col_map)).

        The column key in the output is ``str(ci)`` but the sort is on the INT ci.
        A regression sorting on the str key would mis-order cols >= 10 (e.g. "10"
        before "2"). Pins the int-sort with a 2-vs-10 column pair.
        """
        rm = _emit(
            accumulator={1: {
                10: {"A": 1},
                2: {"B": 1},
            }},
            breakdown=[{"spin_type": 1, "behavior_name": "paid"}],
        )
        # int sort: 2 before 10 (string sort would give "10" before "2").
        assert list(rm["ST1_paid"].keys()) == ["2", "10"], rm["ST1_paid"]


# ---------------------------------------------------------------------------
# Branch: outer label order = sorted by spin_type INT (not behavior string)
# ---------------------------------------------------------------------------

class TestLabelOrderBySpinTypeInt:
    """Labels must be emitted in ascending spin_type-INT order (sorted(_st_label)).

    ``sorted(_st_label.items())`` sorts by the dict KEY = spin_type int. The
    goldens cover this only for their specific ST sets (M275: 126<140); this pins
    it with an order that would differ under a string sort of the labels.
    """

    def test_labels_ordered_by_spin_type_int(self):
        """st=2 ("ST2_*") must come before st=10 ("ST10_*") — int order, not string.

        String-sorting the LABELS would put "ST10_..." before "ST2_..." (because
        "1" < "2"); the correct int-key sort puts ST2 first. A regression sorting
        on the label string instead of the int key is caught here.
        """
        rm = _emit(
            accumulator={2: {0: {"A": 1}}, 10: {0: {"B": 1}}},
            breakdown=[
                {"spin_type": 10, "behavior_name": "free"},
                {"spin_type": 2, "behavior_name": "paid"},
            ],
        )
        assert list(rm.keys()) == ["ST2_paid", "ST10_free"], (
            f"labels must be ordered by spin_type INT (2 before 10), not by the "
            f"label string ('ST10' would sort before 'ST2'). Got {list(rm.keys())}"
        )
