"""Tests for the AIMD (additive-increase / multiplicative-decrease)
adaptive tuning of batch_concurrency + chunk_spin_times.

Rationale: per-request retry already rides out brief upstream hiccups
(~30s, per the max_attempts=5 + max_backoff_s=30 config). When an
upstream slowdown lasts longer, shrinking the load gives the upstream
breathing room — halving concurrency + chunk size + pausing briefly
before the next submit is the classic TCP-style response. Once
upstream recovers, AIMD grows load back to the user's original setting
over several clean batches.

These tests exercise the pure ``aimd_tune`` helper directly so state
transitions are fast + deterministic.
"""
from __future__ import annotations

import pytest

from fresh_slotlab.player_impact_analyzer import (
    aimd_tune,
    MIN_CHUNK_SPINS,
    SUCCESS_STREAK_FOR_GROW,
    CHUNK_SPINS_GROWTH,
)


class TestAimdHalveOnFailure:
    def test_halves_concurrency_on_fully_failed_batch(self):
        conc, spins, success, pause = aimd_tune(
            current_concurrency=4,
            current_chunk_spins=5000,
            max_concurrency=4,
            max_chunk_spins=5000,
            batch_fully_failed=True,
            consecutive_successful=0,
        )
        assert conc == 2, "4 → 2 on fully-failed batch"
        assert spins == 2500, "5000 → 2500 on fully-failed batch"
        assert success == 0, "streak resets on failure"
        assert pause is True, "caller must pause for circuit breather"

    def test_halves_keeps_floor_of_1_concurrency(self):
        conc, spins, success, pause = aimd_tune(
            current_concurrency=1,
            current_chunk_spins=MIN_CHUNK_SPINS * 2,
            max_concurrency=4,
            max_chunk_spins=5000,
            batch_fully_failed=True,
            consecutive_successful=0,
        )
        assert conc == 1, "concurrency floors at 1"
        assert spins == MIN_CHUNK_SPINS, (
            "chunk_spins floors at MIN_CHUNK_SPINS (going below breaks "
            "collect-cycle correction for cycle_len > chunk_spins machines)"
        )
        assert pause is True

    def test_halves_holds_min_chunk_spins_floor(self):
        conc, spins, _, _ = aimd_tune(
            current_concurrency=2,
            current_chunk_spins=MIN_CHUNK_SPINS,  # already at floor
            max_concurrency=4,
            max_chunk_spins=5000,
            batch_fully_failed=True,
            consecutive_successful=0,
        )
        assert spins == MIN_CHUNK_SPINS, "already at floor — stays"
        assert conc == 1, "concurrency still halves"


class TestAimdGrowOnSuccess:
    def test_no_grow_until_streak_threshold(self):
        # 1 consecutive success — not enough to grow yet.
        conc, spins, streak, pause = aimd_tune(
            current_concurrency=2,
            current_chunk_spins=2500,
            max_concurrency=4,
            max_chunk_spins=5000,
            batch_fully_failed=False,
            consecutive_successful=0,
        )
        assert conc == 2, "no change before streak"
        assert spins == 2500
        assert streak == 1
        assert pause is False

    def test_grows_after_streak_threshold(self):
        # After SUCCESS_STREAK_FOR_GROW-1 prior + 1 new = grow.
        conc, spins, streak, pause = aimd_tune(
            current_concurrency=2,
            current_chunk_spins=2500,
            max_concurrency=4,
            max_chunk_spins=5000,
            batch_fully_failed=False,
            consecutive_successful=SUCCESS_STREAK_FOR_GROW - 1,
        )
        assert conc == 3, "concurrency += 1 after streak"
        expected_spins = int(2500 * CHUNK_SPINS_GROWTH)
        assert spins == expected_spins, f"chunk_spins × {CHUNK_SPINS_GROWTH}"
        assert streak == 0, "streak resets after grow"
        assert pause is False

    def test_grow_capped_at_max_concurrency(self):
        conc, spins, _, _ = aimd_tune(
            current_concurrency=4,
            current_chunk_spins=5000,
            max_concurrency=4,
            max_chunk_spins=5000,
            batch_fully_failed=False,
            consecutive_successful=SUCCESS_STREAK_FOR_GROW - 1,
        )
        assert conc == 4, "already at max — no grow past user setting"
        assert spins == 5000, "chunk_spins capped too"

    def test_grow_capped_at_max_chunk_spins_even_if_under_max_conc(self):
        conc, spins, _, _ = aimd_tune(
            current_concurrency=2,
            current_chunk_spins=5000,
            max_concurrency=4,
            max_chunk_spins=5000,
            batch_fully_failed=False,
            consecutive_successful=SUCCESS_STREAK_FOR_GROW - 1,
        )
        assert conc == 3, "concurrency grows"
        assert spins == 5000, "chunk_spins stays at cap"


class TestAimdRoundTrip:
    """Sanity: halve → grow back to ceiling over enough streak."""

    def test_halve_then_grow_back(self):
        # Start at (4, 5000). One fully-failed batch → (2, 2500).
        conc, spins, streak, _ = aimd_tune(4, 5000, 4, 5000, True, 0)
        assert (conc, spins, streak) == (2, 2500, 0)

        # Now N consecutive successful batches — should grow.
        for _ in range(SUCCESS_STREAK_FOR_GROW):
            conc, spins, streak, pause = aimd_tune(
                conc, spins, 4, 5000, False, streak
            )
            assert pause is False

        # After SUCCESS_STREAK_FOR_GROW successes, conc = 3, spins = int(2500 * 1.25) = 3125.
        assert conc == 3
        assert spins == int(2500 * CHUNK_SPINS_GROWTH)

    def test_no_grow_when_batch_has_any_failure_but_not_fully(self):
        # Partial success (some failed, some succeeded): not "fully
        # failed" so we DON'T pause or halve. But also don't grow since
        # it wasn't a clean batch. Caller should set
        # consecutive_successful=0 externally to reflect this.
        # aimd_tune itself only sees batch_fully_failed=False so it
        # treats as success; caller is responsible for passing
        # consecutive_successful=0 on any failure. This test just locks
        # the function's contract.
        conc, spins, streak, pause = aimd_tune(2, 2500, 4, 5000, False, 0)
        # Increments streak by 1, doesn't grow yet.
        assert (conc, spins, streak) == (2, 2500, 1)
        assert pause is False


# ---------- collect_feature_match_warning ----------

from fresh_slotlab.player_impact_analyzer import collect_feature_match_warning


class TestCollectFeatureMatchWarning:
    """Guards the RTP under-reporting failure mode where the analyzer
    detects collect-mechanic cycles (CC resets from BuffCollectionMap)
    but the cycle bonus on that machine isn't named 'NewFreespin' in
    upstream_feature_tally. Current newfreespin_correction hardcodes
    that feature name; without this warning, another machine's 0pp
    correction would silently under-report true RTP."""

    def test_no_cycles_no_warning(self):
        # M14 baseline: no collect mechanic, no cycles, warning absent.
        out = collect_feature_match_warning(cycle_peaks=[], upstream_feature_tally={})
        assert out["applicable"] is False
        assert out["warning"] is None
        assert out["has_newfreespin"] is False

    def test_cycles_plus_newfreespin_no_warning(self):
        # M272 baseline: collect cycle detected + NewFreespin in tally
        # → correction applies, no warning needed.
        out = collect_feature_match_warning(
            cycle_peaks=[1000, 1000, 1000],
            upstream_feature_tally={"NewFreespin": {"1": {"win": 500, "times": 10}}},
        )
        assert out["applicable"] is True
        assert out["has_newfreespin"] is True
        assert out["warning"] is None

    def test_cycles_but_no_newfreespin_raises_warning(self):
        # Hypothetical machine with a different bonus feature name.
        # Warning must surface so operator can investigate.
        out = collect_feature_match_warning(
            cycle_peaks=[1000, 999, 1001],
            upstream_feature_tally={
                "NormalCollectionSpin": {"1": {"win": 800, "times": 5}},
                "SomethingElse": {"2": {"win": 100, "times": 20}},
            },
        )
        assert out["applicable"] is True
        assert out["has_newfreespin"] is False
        assert out["warning"] is not None, (
            "cycles without NewFreespin must produce a warning"
        )
        assert "NewFreespin" in out["warning"], "warning must name the hardcoded feature"
        assert "NormalCollectionSpin" in out["warning"], (
            "warning must list features actually seen so operator can correlate"
        )
        assert "SomethingElse" in out["warning"]

    def test_tolerates_none_tally(self):
        out = collect_feature_match_warning([1000], None)
        assert out["applicable"] is True
        assert out["warning"] is not None  # cycles seen, no feature data at all
        assert out["known_features"] == []

    def test_known_features_alphabetically_sorted(self):
        out = collect_feature_match_warning(
            cycle_peaks=[],
            upstream_feature_tally={"Zeta": {}, "Alpha": {}, "NewFreespin": {}},
        )
        assert out["known_features"] == ["Alpha", "NewFreespin", "Zeta"]
