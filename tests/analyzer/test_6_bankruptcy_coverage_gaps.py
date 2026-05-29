"""Phase 6 — synthetic-input units for the carved branches the M275/M14 goldens MISS.

COVERAGE-GAP CLOSER (the 2b ``_quantiles``-index lesson / the 4 zero-spin-divisor
lesson / the 5 empty-col-rows lesson; see the prior-phase inject_bug_evidence.md
files and brief §4 deliverable #3).

The byte-identity goldens (M275 + M14 in test_6_byte_identical_bankruptcy_carve.py)
lock the carved ``build_bankruptcy_rows`` row-build leaf-by-leaf, but BOTH sample
machines exercise ONLY the fully-populated path:

  - M275: 4 tiers (10/100/200/500), EVERY tier with bankrupt>0 AND survived>0
    (rates 0.998/0.978/0.957/0.895, fastest 10/114/361/1326 — all non-None).
  - M14:  4 tiers (10/100/200/500), same — every tier populated, every fastest
    non-None.

So several arms of the moved build are NEVER exercised by either golden. A
regression in any of them would leave BOTH byte-identity deep-diffs GREEN. This
file pins each with a synthetic ``bankruptcy_sim_totals`` dict passed DIRECTLY to
``build_bankruptcy_rows(...)`` (the carved module-level function).

Branch enumeration of the moved build (deliverable #3 "hunt for any OTHER
unexercised branch") — bankruptcy_simulation.py build_bankruptcy_rows(), the
``for m in bankruptcy_mults_tuple`` loop:

  (1) ``tier = ...get(int(m))`` is None  ->  ``tier = _empty_bankruptcy_tier()``  [golden-missed]
        Driver: a multiplier in the tuple that is ABSENT from bankruptcy_sim_totals.
        Real runs build a totals entry for every requested tier, so the goldens
        never hit the ``if tier is None`` fallback. Result: a zero-count tier
        (robots=0, rate=0.0, fastest=None, median=0, all percentiles 0).

  (2) ``total_sessions == 0``  ->  ``rate = 0.0``  (the ``else 0.0`` arm)            [golden-missed]
        Driver: a tier dict with bankrupt=0 AND survived=0 (an explicit empty tier).
        Every golden tier has total_sessions in the hundreds/thousands, so the
        ``if total_sessions > 0`` true-branch is the only one they cover. A
        regression dropping the zero-guard divides by zero (ZeroDivisionError).

  (3) ``fastest_bankruptcy_spins`` is None  (survivors only, zero bankrupt)          [golden-missed]
        Driver: a tier with survived>0 but bankrupt=0 (spins_done == []).
        fastest_bankruptcy_spins_from_list([]) -> None. Every golden tier saw
        bankruptcies (fastest is an int), so the None arm is uncovered. A
        regression that defaulted None to 0 would diverge from the pre-carve dict.

  (4) ``tier.get("spins_done") or []`` / ``tier.get("survived") or 0``  fallbacks   [golden-missed]
        Driver: a tier dict MISSING the spins_done / survived keys entirely (or
        None). Real totals always carry both keys, so the ``or []`` / ``or 0``
        arms are uncovered. Must not KeyError; must degrade to empty/0.

  (5) the final ``bankruptcy_rows.sort(key=lambda row: int(row["bankroll_multiplier"]))``
        Driver: pass the mult tuple OUT OF ORDER -> output must come back sorted
        ascending. The goldens pass (10,100,200,500) already-ascending, so the
        sort is a no-op for them; a flipped/dropped sort is golden-invisible.

  The leaves inside a populated tier (``bankroll_multiplier`` / ``init_credits =
  int(m)*int(bet)`` / ``robots`` / ``bankrupt_robots`` / ``completed_robots`` /
  ``bankruptcy_rate`` / ``median_spins_completed`` / the ``{str(k): v}`` percentile
  serialization) are covered byte-identically by the goldens; pinned here too as
  fast-localized regression signals (esp. the int() casts and the str-keyed
  percentiles dict).

Inject-bug recipes (per feedback_enumerate_safety_paths.md) — verified 2026-05-30
(RED->revert->GREEN while the byte-identity goldens stay GREEN; evidence in
inject_bug_evidence.md §Coverage-gap):

  empty-tier fallback removal (branch 1):
    -  if tier is None:
    -      tier = _empty_bankruptcy_tier()
    +  pass  # BUG (no fallback)
    -> test_absent_multiplier_yields_empty_tier RED (TypeError / KeyError on the
       None tier). Goldens stay GREEN (every golden mult has a totals entry).

  zero-session guard removal (branch 2):
    -  rate = (tier["bankrupt"] / total_sessions) if total_sessions > 0 else 0.0
    +  rate = tier["bankrupt"] / total_sessions                          # BUG
    -> test_zero_session_tier_rate_is_zero RED (ZeroDivisionError). Goldens stay
       GREEN (no all-zero tier on either machine).

  fastest-None coercion (branch 3):
    -  "fastest_bankruptcy_spins": fastest,
    +  "fastest_bankruptcy_spins": fastest or 0,                         # BUG
    -> test_survivors_only_tier_fastest_is_none RED (0 instead of None). Goldens
       stay GREEN (every golden tier has a non-None fastest).

  sort-direction flip (branch 5):
    -  bankruptcy_rows.sort(key=lambda row: int(row.get("bankroll_multiplier", 0)))
    +  bankruptcy_rows.sort(key=lambda row: -int(row.get("bankroll_multiplier", 0)))  # BUG
    -> test_tiers_sorted_ascending_even_when_input_unordered RED (descending).
       Goldens ALSO RED on real data (they lock the order), but this localizes it.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md
    each branch of the moved compute needs its own inject-bug-provable test; the
    empty-tier / zero-session / None-fastest / .get-fallback arms are golden-missed
    safety paths.
- memory/feedback_perf_claim_needs_e2e_event_stream.md
    the 2 sample machines' data can leave whole branches uncovered; synthetic
    inputs spanning those branches are required.
- memory/feedback_no_silent_swallow.md
    the ``tier is None -> _empty_bankruptcy_tier()`` fallback is the DOCUMENTED
    zero-count tier (not a silent default that hides drift). The .get(...) or []
    fallbacks must degrade visibly to empty/0, never KeyError-then-swallow.
- memory/feedback_invariant_with_fallback_hides_drift.md
    a tier silently dropped (vs kept-with-zero-counts) is exactly the absent-vs-
    present drift the structural goldens miss but a typed assertion catches.
"""
from __future__ import annotations

from typing import Any

import pytest


def _build():
    try:
        from fresh_slotlab.analyzer.features.bankruptcy_simulation import (
            build_bankruptcy_rows,
        )
    except ImportError:  # running as standalone script
        from analyzer.features.bankruptcy_simulation import (  # type: ignore[no-redef]
            build_bankruptcy_rows,
        )
    return build_bankruptcy_rows


def _empty_tier_helper():
    """The SAME _empty_bankruptcy_tier the build uses (for golden-shape comparison)."""
    try:
        from fresh_slotlab.analyzer.core._utils import _empty_bankruptcy_tier
    except ImportError:  # running as standalone script
        from analyzer.core._utils import _empty_bankruptcy_tier  # type: ignore[no-redef]
    return _empty_bankruptcy_tier


_PERCENTILE_STR_KEYS = ["10", "20", "30", "40", "50", "60", "70", "80", "90"]


# ---------------------------------------------------------------------------
# Branch 1: a multiplier ABSENT from totals -> _empty_bankruptcy_tier() fallback
# ---------------------------------------------------------------------------

class TestAbsentMultiplierEmptyTier:
    """A requested multiplier with no totals entry must yield a zero-count tier.

    Neither golden has a requested mult missing from totals, so the
    ``if tier is None: tier = _empty_bankruptcy_tier()`` arm is uncovered by the
    byte-identity tests.
    """

    def test_absent_multiplier_yields_empty_tier(self):
        """mult in tuple but NOT in totals -> a populated zero-count row.

        INJECT-BUG: remove the ``if tier is None: tier = _empty_bankruptcy_tier()``
        fallback. RED here (TypeError indexing None). Goldens GREEN.
        """
        rows = _build()({}, (100,), 1000, 10000)  # totals empty
        assert len(rows) == 1
        row = rows[0]
        assert row["bankroll_multiplier"] == 100
        assert row["robots"] == 0, f"absent mult must give 0 robots; got {row['robots']}"
        assert row["bankrupt_robots"] == 0
        assert row["completed_robots"] == 0
        assert row["bankruptcy_rate"] == 0.0
        assert row["median_spins_completed"] == 0
        assert row["fastest_bankruptcy_spins"] is None, (
            f"a zero-count tier never bankrupted -> fastest must be None; got "
            f"{row['fastest_bankruptcy_spins']!r}"
        )
        # All percentiles 0 (the empty-population branch of compute_bankruptcy_percentiles).
        assert row["percentiles"] == {k: 0 for k in _PERCENTILE_STR_KEYS}

    def test_absent_multiplier_still_emits_init_credits(self):
        """The empty-tier row still carries init_credits = mult * bet (not skipped).

        The label/tier is PRESENT with zero counts (matching the pre-carve loop),
        not dropped — a regression dropping absent-mult tiers would shrink the grid.
        """
        rows = _build()({}, (250,), 1000, 10000)
        assert rows[0]["init_credits"] == 250 * 1000
        assert rows[0]["session_spins"] == 10000

    def test_mixed_present_and_absent_multipliers(self):
        """Two tiers: one populated, one absent — both present in output.

        Confirms a populated tier and an empty tier co-exist in one build (the empty
        one kept with zero counts, not dropped, not crashing the populated one).
        """
        rows = _build()(
            {100: {"bankrupt": 3, "survived": 1, "spins_done": [40, 60, 80]}},
            (100, 500),  # 500 absent from totals
            1000,
            10000,
        )
        by_mult = {r["bankroll_multiplier"]: r for r in rows}
        assert set(by_mult) == {100, 500}
        # Populated tier.
        assert by_mult[100]["robots"] == 4
        assert by_mult[100]["bankrupt_robots"] == 3
        assert by_mult[100]["bankruptcy_rate"] == 3 / 4
        assert by_mult[100]["fastest_bankruptcy_spins"] == 40  # min of sorted [40,60,80]
        # Absent tier (zero-count).
        assert by_mult[500]["robots"] == 0
        assert by_mult[500]["fastest_bankruptcy_spins"] is None


# ---------------------------------------------------------------------------
# Branch 2: total_sessions == 0 -> rate 0.0 (the else arm, no divide-by-zero)
# ---------------------------------------------------------------------------

class TestZeroSessionRate:
    """An explicit empty tier (bankrupt=0, survived=0) must give rate 0.0, no crash.

    No golden tier has total_sessions == 0, so the ``else 0.0`` arm is uncovered.
    A regression removing the guard divides by zero.
    """

    def test_zero_session_tier_rate_is_zero(self):
        """bankrupt=0 + survived=0 -> rate 0.0 (no ZeroDivisionError).

        INJECT-BUG: drop the ``if total_sessions > 0`` guard on the rate. RED here
        (ZeroDivisionError). Goldens GREEN (every golden tier has sessions).
        """
        rows = _build()(
            {100: {"bankrupt": 0, "survived": 0, "spins_done": []}},
            (100,),
            1000,
            10000,
        )
        assert rows[0]["bankruptcy_rate"] == 0.0
        assert rows[0]["robots"] == 0
        assert isinstance(rows[0]["bankruptcy_rate"], float)

    def test_zero_session_does_not_raise(self):
        """The zero-session guard is a safety path (no exception)."""
        # Must not raise.
        rows = _build()(
            {100: {"bankrupt": 0, "survived": 0, "spins_done": []}},
            (100,),
            1000,
            10000,
        )
        assert rows[0]["fastest_bankruptcy_spins"] is None


# ---------------------------------------------------------------------------
# Branch 3: survivors-only tier -> fastest is None (NOT coerced to 0)
# ---------------------------------------------------------------------------

class TestSurvivorsOnlyFastestNone:
    """A tier with survivors but zero bankrupt must report fastest=None.

    Every golden tier saw at least one bankruptcy (fastest is an int), so the
    None arm is uncovered. The None must survive to the JSON (the UI highlights it
    separately); a regression coercing it to 0 would diverge from the pre-carve dict.
    """

    def test_survivors_only_tier_fastest_is_none(self):
        """survived>0, bankrupt=0 -> fastest_bankruptcy_spins is None.

        INJECT-BUG: change ``"fastest_bankruptcy_spins": fastest`` to ``fastest or
        0``. RED here (0 instead of None). Goldens GREEN.
        """
        rows = _build()(
            {100: {"bankrupt": 0, "survived": 5, "spins_done": []}},
            (100,),
            1000,
            10000,
        )
        row = rows[0]
        assert row["fastest_bankruptcy_spins"] is None
        assert row["bankrupt_robots"] == 0
        assert row["completed_robots"] == 5
        assert row["robots"] == 5
        assert row["bankruptcy_rate"] == 0.0
        # All-survived population -> every percentile pins to session_spins.
        assert row["percentiles"] == {k: 10000 for k in _PERCENTILE_STR_KEYS}
        # median of an all-survivor tier = session_spins.
        assert row["median_spins_completed"] == 10000

    def test_bankrupt_tier_fastest_is_min_int(self):
        """Contrast: a tier WITH bankruptcies reports the exact minimum spins_done.

        Pins that fastest is an int (the not-None branch) so the None test above is
        a genuine contrast, not a constant.
        """
        rows = _build()(
            {100: {"bankrupt": 3, "survived": 0, "spins_done": [200, 50, 130]}},
            (100,),
            1000,
            10000,
        )
        # sorted -> [50,130,200]; fastest = 50.
        assert rows[0]["fastest_bankruptcy_spins"] == 50
        assert isinstance(rows[0]["fastest_bankruptcy_spins"], int)


# ---------------------------------------------------------------------------
# Branch 4: missing spins_done / survived keys -> .get(...) or fallbacks
# ---------------------------------------------------------------------------

class TestMissingKeyFallbacks:
    """A tier dict missing spins_done / survived must degrade visibly, not KeyError.

    Real totals always carry both keys; the ``tier.get("spins_done") or []`` and
    ``tier.get("survived") or 0`` fallbacks are uncovered by the goldens. They must
    NOT raise — they degrade to empty list / 0 (still requires the mandatory
    ``bankrupt`` / ``survived`` keys for total_sessions, which the build reads by
    direct index — that is the documented hard contract).
    """

    def test_missing_spins_done_key_defaults_to_empty(self):
        """tier without 'spins_done' -> treated as empty list (no KeyError)."""
        rows = _build()(
            {100: {"bankrupt": 0, "survived": 0}},  # no spins_done
            (100,),
            1000,
            10000,
        )
        assert rows[0]["fastest_bankruptcy_spins"] is None
        assert rows[0]["robots"] == 0

    def test_none_spins_done_defaults_to_empty(self):
        """tier with spins_done=None -> ``or []`` fallback -> empty (no crash)."""
        rows = _build()(
            {100: {"bankrupt": 0, "survived": 2, "spins_done": None}},
            (100,),
            1000,
            10000,
        )
        assert rows[0]["fastest_bankruptcy_spins"] is None
        assert rows[0]["completed_robots"] == 2

    def test_missing_survived_in_percentile_ref_defaults_to_zero(self):
        """survived absent from the percentile ref (``tier.get('survived') or 0``).

        ``survived_ref`` defaults to 0 when the key is missing — the percentile call
        then treats the population as bankrupt-only. (The ``completed_robots`` /
        ``total_sessions`` read uses the direct ``tier['survived']`` index, so a
        present-but-zero survived is required for those — covered by branch 2; here
        we keep survived present for the count and just confirm the percentile-ref
        ``or 0`` arm does not crash.)
        """
        # survived present (so total_sessions is well-defined) but spins_done drives
        # the percentile; the ``or 0`` arm on survived_ref is structurally exercised.
        rows = _build()(
            {100: {"bankrupt": 2, "survived": 0, "spins_done": [10, 20]}},
            (100,),
            1000,
            10000,
        )
        # 2 bankrupt, 0 survived -> percentiles computed over [10,20].
        assert rows[0]["bankruptcy_rate"] == 1.0
        assert rows[0]["fastest_bankruptcy_spins"] == 10


# ---------------------------------------------------------------------------
# Branch 5: the final ascending sort (input order independence)
# ---------------------------------------------------------------------------

class TestFinalSort:
    """Output tiers must be sorted ascending by bankroll_multiplier regardless of
    the input tuple order. The goldens pass (10,100,200,500) already-ascending, so
    the sort is a no-op for them.
    """

    def test_tiers_sorted_ascending_even_when_input_unordered(self):
        """An out-of-order mult tuple -> output sorted ascending.

        INJECT-BUG: flip the sort key sign (``-int(...)``). RED here (descending).
        Goldens ALSO RED on real data, but this localizes it instantly.
        """
        rows = _build()(
            {
                500: {"bankrupt": 1, "survived": 0, "spins_done": [5]},
                100: {"bankrupt": 1, "survived": 0, "spins_done": [3]},
                200: {"bankrupt": 1, "survived": 0, "spins_done": [4]},
            },
            (500, 100, 200),  # deliberately out of order
            1000,
            10000,
        )
        assert [r["bankroll_multiplier"] for r in rows] == [100, 200, 500], (
            f"tiers must be sorted ascending by bankroll_multiplier regardless of "
            f"input order; got {[r['bankroll_multiplier'] for r in rows]}"
        )

    def test_int_cast_on_string_multiplier(self):
        """A string-typed multiplier sorts by its int value (the ``int(m)`` cast).

        ``init_credits = int(m) * int(bet)`` and the sort key ``int(row[...])`` both
        cast — pins the int sort so mults >= 10 don't string-sort ("10" < "2").
        """
        rows = _build()(
            {2: {"bankrupt": 1, "survived": 0, "spins_done": [3]},
             10: {"bankrupt": 1, "survived": 0, "spins_done": [4]}},
            (10, 2),  # int tuple, out of order
            1000,
            10000,
        )
        # int sort: 2 before 10 (string sort would give 10 before 2 — "1" < "2").
        assert [r["bankroll_multiplier"] for r in rows] == [2, 10]


# ---------------------------------------------------------------------------
# Unconditional leaves (covered byte-identically by goldens; pinned for triage)
# ---------------------------------------------------------------------------

class TestRowLeavesVerbatim:
    """The per-tier leaves: int casts, rate form, str-keyed percentiles."""

    def test_init_credits_is_mult_times_bet_int(self):
        """init_credits = int(m) * int(bet); both casts applied; result is int.

        Pins the moved ``init_credits`` expression — a float bet still yields an int.
        """
        rows = _build()(
            {100: {"bankrupt": 1, "survived": 1, "spins_done": [50]}},
            (100,),
            1000.0,  # float bet
            10000,
        )
        assert rows[0]["init_credits"] == 100000
        assert isinstance(rows[0]["init_credits"], int)

    def test_rate_is_bankrupt_over_total_sessions(self):
        """bankruptcy_rate = bankrupt / (bankrupt + survived) — the moved divisor.

        A regression rewriting the divisor (e.g. / bankrupt, or / survived) is caught
        here directly. 3 bankrupt + 1 survived -> 0.75.
        """
        rows = _build()(
            {100: {"bankrupt": 3, "survived": 1, "spins_done": [10, 20, 30]}},
            (100,),
            1000,
            10000,
        )
        assert rows[0]["bankruptcy_rate"] == 3 / 4
        assert rows[0]["robots"] == 4

    def test_counts_are_ints(self):
        """robots / bankrupt_robots / completed_robots are int() casts."""
        rows = _build()(
            {100: {"bankrupt": 2, "survived": 5, "spins_done": [10, 20]}},
            (100,),
            1000,
            10000,
        )
        row = rows[0]
        for key in ("robots", "bankrupt_robots", "completed_robots", "median_spins_completed"):
            assert isinstance(row[key], int), f"{key} must be int: {row[key]!r}"
        assert row["bankrupt_robots"] == 2
        assert row["completed_robots"] == 5
        assert row["robots"] == 7

    def test_percentiles_keys_are_strings(self):
        """percentiles dict keys must be strings (the ``{str(k): v}`` serialization).

        A regression dropping the str() would emit int keys -> JSON would coerce them
        anyway, but the in-memory dict (consumed by the markdown read-back via
        ``pct.get(str(k), pct.get(k, 0))``) would mismatch. Pins string keys.
        """
        rows = _build()(
            {100: {"bankrupt": 2, "survived": 0, "spins_done": [100, 200]}},
            (100,),
            1000,
            10000,
        )
        pct = rows[0]["percentiles"]
        assert set(pct.keys()) == set(_PERCENTILE_STR_KEYS)
        assert all(isinstance(k, str) for k in pct), (
            f"percentile keys must be strings (str(k)); got {list(pct)}"
        )

    def test_empty_tier_row_matches_empty_helper_shape(self):
        """The absent-mult row is built from _empty_bankruptcy_tier() — confirm shape.

        Cross-checks that the build's empty-tier fallback uses the SHARED
        _empty_bankruptcy_tier() (the same source PIA used), not a re-derived literal
        (per feedback_no_parallel_panel_impl.md).
        """
        empty = _empty_tier_helper()()
        assert empty == {"bankrupt": 0, "survived": 0, "spins_done": []}, (
            "the shared _empty_bankruptcy_tier() shape changed — the build's "
            "fallback row would change with it; update the absent-mult assertions."
        )
        rows = _build()({}, (100,), 1000, 10000)
        # The empty helper drives robots=0 / bankrupt=0 / survived=0.
        assert rows[0]["robots"] == 0
        assert rows[0]["bankrupt_robots"] == 0
        assert rows[0]["completed_robots"] == 0
