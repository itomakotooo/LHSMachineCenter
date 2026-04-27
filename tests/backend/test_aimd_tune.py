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
        # Generic shape: with N consecutive successes already, the
        # next success makes (N+1). If (N+1) < SUCCESS_STREAK_FOR_GROW,
        # the function bumps the streak counter but doesn't grow.
        # Parametric on SUCCESS_STREAK_FOR_GROW so the test stays
        # valid through tuning changes (was 3 before 2026-04-26;
        # dropped to 1 to recover faster on internal-network default
        # — at threshold=1 every clean batch grows, so this scenario
        # is degenerate. Skip explicitly when threshold=1).
        if SUCCESS_STREAK_FOR_GROW <= 1:
            import pytest
            pytest.skip(
                f"SUCCESS_STREAK_FOR_GROW={SUCCESS_STREAK_FOR_GROW}; "
                f"every clean batch grows at threshold=1"
            )
        prior = SUCCESS_STREAK_FOR_GROW - 2  # need one more before grow
        conc, spins, streak, pause = aimd_tune(
            current_concurrency=2,
            current_chunk_spins=2500,
            max_concurrency=4,
            max_chunk_spins=5000,
            batch_fully_failed=False,
            consecutive_successful=prior,
        )
        assert conc == 2, "no change before streak"
        assert spins == 2500
        assert streak == prior + 1
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
        #
        # 2026-04-26: parametric on SUCCESS_STREAK_FOR_GROW. At
        # threshold=1 every clean batch grows, so the "doesn't grow
        # yet" assertion is degenerate; skip explicitly.
        if SUCCESS_STREAK_FOR_GROW <= 1:
            import pytest
            pytest.skip(
                f"SUCCESS_STREAK_FOR_GROW={SUCCESS_STREAK_FOR_GROW}; "
                f"every clean batch grows at threshold=1"
            )
        conc, spins, streak, pause = aimd_tune(2, 2500, 4, 5000, False, 0)
        # Increments streak by 1, doesn't grow yet.
        assert (conc, spins, streak) == (2, 2500, 1)
        assert pause is False


# NOTE: collect_feature_match_warning coverage moved to
# test_bcm_resolver.py when the signature was reworked to take the
# resolved feature + source from _resolve_bonus_feature. The older
# tests here (which tested a hardcoded NewFreespin check) are
# superseded — the newer logic is strictly more robust.
