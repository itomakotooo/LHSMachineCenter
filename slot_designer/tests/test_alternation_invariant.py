"""Regression: shipped per-mode ``weights.json`` files satisfy
Blank/non-Blank alternation on every reel (strip layout shared across
modes lives in ``<machine>/reel_strips.json``; this test exercises
assembled reels via ``load_reels_for_tuner``).

2026-04-22 user rule: "blank 和非 blank 必须是间隔开的". On a classic
3-reel machine with 36 stops per reel and count(Blank) == count(non-Blank)
(= 18 + 18 for M1), the right layout is strict alternation — never two
Blanks adjacent, never two non-Blanks adjacent, counting the circular
wrap from last → first.

Fix (2026-04-22): ``tuner/ordering.py`` gained
  * ``initialize_alternating(reel)`` — rearranges a reel to strict
    alternation before Phase 5 SA runs
  * ``class_preserving_swap_mutation`` — SA mutation that only swaps
    stops of the same Blank/non-Blank class, preserving alternation
    at every step
  * ``run_simulated_annealing(enforce_alternation=True)`` — default-
    on hard invariant: input must be alternating, and post-SA
    assertion re-verifies.

Tests:
  1. Every shipped per-mode ``weights.json`` (all modes, all reels)
     has zero alternation violations when the shared strips +
     per-mode weights are assembled via ``load_reels_for_tuner``.
  2. ``initialize_alternating`` eliminates violations (inject cluster
     → run init → verify 0). Fails loudly when count(Blank) !=
     count(non-Blank).
  3. ``class_preserving_swap_mutation`` preserves alternation across
     many random mutations.
  4. ``run_simulated_annealing(enforce_alternation=True)`` refuses
     non-alternating input (red-handed regression if someone removes
     the pre-SA init call).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.tuner.ordering import (
    ExperienceCostWeights,
    SAConfig,
    class_preserving_swap_mutation,
    count_alternation_violations,
    evaluate_experience_cost,
    initialize_alternating,
    run_simulated_annealing,
)


def _load_shipped_reels(machine: str, mode: int) -> list[list[dict]]:
    """Assemble the shipped strips + weights into the legacy
    [[{symbol, weight}, ...], ...] shape this test suite compares
    against."""
    from slot_designer.engine.loader import load_reels_for_tuner
    base = _ROOT / "slot_designer" / "weights" / machine
    return load_reels_for_tuner(
        base / "reel_strips.json",
        base / f"mode_{mode}" / "weights.json",
    )


def test_shipped_m37_mode1_has_zero_alternation_violations():
    """2026-04-24: switched from M1 to M37. M1 rebuilt onto IGT Triple
    Double Diamond archetype (22 stops, non-alternating by TDD's actual
    published layout — Hot Roll bonus slot replacement creates 3 consecutive
    Blanks at pos 12-14). M1 is now exempt from alternation invariant; see
    reel_strips.json._archetype and project_slot_designer §F machine archetype.
    M37 (classic 18+18 alternation, no archetype override) remains the
    alternation-invariant representative. Note M37 uses lowercase 'blank'."""
    reels = _load_shipped_reels("M37", 1)
    for ri, reel in enumerate(reels):
        v = count_alternation_violations(reel, blank_symbol="blank")
        assert v == 0, (
            f"M37 mode 1 reel {ri+1} has {v} blank-blank or non-blank-non-blank "
            f"circular adjacency violations. Shipped reels must strictly "
            f"alternate. Re-run Phase 5 with initialize_alternating + "
            f"enforce_alternation=True."
        )


def test_shipped_m37_mode2_has_zero_alternation_violations():
    reels = _load_shipped_reels("M37", 2)
    for ri, reel in enumerate(reels):
        v = count_alternation_violations(reel, blank_symbol="blank")
        assert v == 0, (
            f"M37 mode 2 reel {ri+1} has {v} alternation violations."
        )


def test_initialize_alternating_removes_violations():
    # Synthetic reel with clumped Blanks (3 adjacent) + clumped non-Blanks
    reel = [
        {"symbol": "Blank", "weight": 10},
        {"symbol": "Blank", "weight": 20},
        {"symbol": "Blank", "weight": 30},
        {"symbol": "Bar1",  "weight": 5},
        {"symbol": "Bar2",  "weight": 6},
        {"symbol": "Bar3",  "weight": 7},
    ]
    assert count_alternation_violations(reel) > 0, "seed reel must be clumpy"
    alt = initialize_alternating(reel)
    assert count_alternation_violations(alt) == 0, (
        f"initialize_alternating failed to remove violations; result: {alt!r}"
    )
    # Counts preserved
    def _counts(r):
        out = {}
        for s in r:
            out[s["symbol"]] = out.get(s["symbol"], 0) + s["weight"]
        return out
    assert _counts(alt) == _counts(reel), "init changed per-symbol totals"


def test_initialize_alternating_rejects_imbalanced_reel():
    # 4 Blanks + 2 non-Blanks → strict alternation impossible
    reel = [{"symbol": "Blank", "weight": 1}] * 4 + [
        {"symbol": "Bar1", "weight": 1},
        {"symbol": "Bar2", "weight": 1},
    ]
    try:
        initialize_alternating(reel)
    except ValueError as exc:
        assert "alternation requires count" in str(exc), (
            f"error should explain the imbalance; got {exc!r}"
        )
        return
    raise AssertionError(
        "initialize_alternating must raise on imbalanced reel — silently "
        "returning a non-alternating result would break the post-SA "
        "invariant assertion."
    )


def test_class_preserving_swap_keeps_alternation_across_many_mutations():
    reels = _load_shipped_reels("M37", 1)
    # Confirm starting state is valid (M37 uses lowercase 'blank')
    assert all(count_alternation_violations(r, blank_symbol="blank") == 0 for r in reels)
    rng = Random(123)
    cur = [list(r) for r in reels]
    for _ in range(500):
        cur = class_preserving_swap_mutation(cur, rng, blank_symbol="blank")
        # After every swap, still alternating
        assert all(count_alternation_violations(r, blank_symbol="blank") == 0 for r in cur), (
            "class_preserving_swap_mutation broke alternation — check "
            "that it samples only within one class (all-blank or "
            "all-non-blank index subset)."
        )


def test_run_sa_enforce_alternation_rejects_non_alternating_input():
    # Reel with clustering → SA with enforce=True must refuse
    bad_reels = [[
        {"symbol": "Blank", "weight": 1},
        {"symbol": "Blank", "weight": 1},
        {"symbol": "Bar1",  "weight": 1},
        {"symbol": "Bar2",  "weight": 1},
    ]]

    def cost_fn(rs):
        b = evaluate_experience_cost(rs)
        return b.total, b

    try:
        run_simulated_annealing(
            bad_reels, cost_fn,
            config=SAConfig(max_steps=10),
            rng=Random(0),
            enforce_alternation=True,
        )
    except ValueError as exc:
        assert "adjacency violations" in str(exc), (
            f"error should mention violations; got {exc!r}"
        )
        return
    raise AssertionError(
        "SA with enforce_alternation=True must refuse non-alternating "
        "input. Silently fixing (via init) would hide wiring bugs where "
        "the caller forgot initialize_alternating; loud fail helps catch "
        "them."
    )


def test_run_sa_enforce_alternation_accepts_alternating_input():
    # Pre-alternated reel → SA runs and preserves alternation
    # M37 uses lowercase 'blank'
    reels = _load_shipped_reels("M37", 1)

    def cost_fn(rs):
        b = evaluate_experience_cost(rs, blank_symbol="blank")
        return b.total, b

    result = run_simulated_annealing(
        reels, cost_fn,
        config=SAConfig(max_steps=200),
        rng=Random(0),
        enforce_alternation=True,
        blank_symbol="blank",
    )
    # Post-SA: still zero violations (assertion inside SA also checks this,
    # so if we got here the invariant held)
    for r in result.best_reels:
        assert count_alternation_violations(r, blank_symbol="blank") == 0


if __name__ == "__main__":
    import inspect
    mod = sys.modules[__name__]
    tests = [o for n, o in inspect.getmembers(mod) if n.startswith("test_") and callable(o)]
    passed, failures = 0, []
    for t in tests:
        try:
            t()
            print(f"ok  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failures.append((t.__name__, e))
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if not failures else 1)
