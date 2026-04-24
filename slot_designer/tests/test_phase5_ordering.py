"""Phase 5 ordering optimizer tests.

Key invariant to verify: permutation PRESERVES per-symbol counts (and
therefore marginals, and therefore RTP / bucket shape / CV). If this
invariant breaks, Phase 5 is silently regressing Phase 4's achievement.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import analytic_profile
from slot_designer.devtools.player_experience import (
    experience_metrics,
    near_miss_rate_2_of_3,
    pwdf_ratio,
    reel_blank_adjacency_score,
    symbol_mid_probability,
    symbol_window_probability,
)
from slot_designer.engine.loader import load_engine
from slot_designer.tuner.layout import base_counts
from slot_designer.tuner.ordering import (
    ExperienceCostWeights,
    SAConfig,
    evaluate_experience_cost,
    random_swap_mutation,
    run_simulated_annealing,
    swap_two_stops,
)


SPEC = _ROOT / "slot_designer" / "specs" / "M37.spec.json"
STRIPS = _ROOT / "slot_designer" / "weights" / "M37" / "reel_strips.json"
WEIGHTS = _ROOT / "slot_designer" / "weights" / "M37" / "mode_1" / "weights.json"


def _load_weights() -> dict:
    """Return the assembled weights envelope (legacy shape) built from
    the new strips + weights.json pair. Tests use the old-style
    ``reel_sets.default.reels`` path to reach the per-stop list of
    ``{symbol, weight}`` dicts.
    """
    from slot_designer.engine.loader import load_reels_for_tuner
    reels = load_reels_for_tuner(STRIPS, WEIGHTS)
    return {"reel_sets": {"default": {"reels": reels}}}


def test_swap_preserves_counts():
    w = _load_weights()
    reel0 = w["reel_sets"]["default"]["reels"][0]
    before = sorted([(s["symbol"], s["weight"]) for s in reel0])
    swapped = swap_two_stops(reel0, 0, 5)
    after = sorted([(s["symbol"], s["weight"]) for s in swapped])
    assert before == after, "swap_two_stops changed symbol set!"


def test_random_swap_preserves_symbol_totals():
    w = _load_weights()
    reels = w["reel_sets"]["default"]["reels"]
    base_totals = base_counts(w)
    rng = Random(42)
    mutated = random_swap_mutation(reels, rng)
    mutated_totals = base_counts({"reel_sets": {"default": {"reels": mutated}}})
    assert base_totals == mutated_totals, (
        f"random_swap altered per-(symbol,reel) totals: "
        f"before={base_totals} after={mutated_totals}"
    )


def test_sa_preserves_rtp(tmp_path):
    """After Phase 5, analytic RTP must be unchanged from the input weights
    (ordering is marginal-preserving; RTP depends only on marginals).

    Writes a roundtrip strips.json + weights.json pair in tmp_path so
    load_engine can re-open them via its strips+weights schema.
    """
    engine, _ = load_engine(SPEC, WEIGHTS)
    rtp_before = analytic_profile(engine)["rtp_pct"]

    weights = _load_weights()
    reels = weights["reel_sets"]["default"]["reels"]

    # M37 uses lowercase 'blank'
    def cost_fn(r):
        b = evaluate_experience_cost(r, blank_symbol="blank")
        return b.total, b

    result = run_simulated_annealing(
        reels, cost_fn,
        config=SAConfig(max_steps=500),
        rng=Random(7),
        blank_symbol="blank",
    )
    # Serialize best reels as strips + weights in tmp_path so the
    # loader (which expects the two-file layout) can round-trip them.
    machine_dir = tmp_path / "M37sim"
    mode_dir = machine_dir / "mode_1"
    mode_dir.mkdir(parents=True)
    strips_doc = {
        "machine": "M37",
        "reel_set": "default",
        "reels": [[s["symbol"] for s in reel] for reel in result.best_reels],
    }
    weights_doc = {
        "machine": "M37",
        "mode": 1,
        "reel_set": "default",
        "weights": [[int(s["weight"]) for s in reel] for reel in result.best_reels],
    }
    (machine_dir / "reel_strips.json").write_text(
        json.dumps(strips_doc, ensure_ascii=False), encoding="utf-8")
    (mode_dir / "weights.json").write_text(
        json.dumps(weights_doc, ensure_ascii=False), encoding="utf-8")
    engine2, _ = load_engine(SPEC, mode_dir / "weights.json")
    rtp_after = analytic_profile(engine2)["rtp_pct"]
    assert abs(rtp_after - rtp_before) < 1e-9, (
        f"Phase 5 changed RTP: before={rtp_before}, after={rtp_after}"
    )


def test_blank_adjacency_max_when_surrounded():
    """Synthetic reel with every high-value stop surrounded by blanks →
    blank_adjacency = 1.0."""
    # Blank, HV, Blank, Blank, HV, Blank
    strip = [
        {"symbol": "Blank", "weight": 10},
        {"symbol": "Seven1", "weight": 5},
        {"symbol": "Blank", "weight": 10},
        {"symbol": "Blank", "weight": 10},
        {"symbol": "Seven1", "weight": 5},
        {"symbol": "Blank", "weight": 10},
    ]
    score = reel_blank_adjacency_score(strip, ["Seven1"])
    assert score == 1.0, f"expected 1.0, got {score}"


def test_blank_adjacency_zero_when_clustered():
    """HV stops touching each other → no blank adjacency."""
    strip = [
        {"symbol": "Seven1", "weight": 5},
        {"symbol": "Seven1", "weight": 5},
        {"symbol": "Bar1", "weight": 3},
    ]
    score = reel_blank_adjacency_score(strip, ["Seven1"])
    # Each Seven1 has one Seven1 neighbor (not blank) and one Bar/Seven — 0 blanks
    assert score == 0.0, f"expected 0.0, got {score}"


def test_pwdf_sensible_range():
    """For the baseline M37 reels, PWDF should be meaningful (>1) for
    high-value symbols that cluster with blanks. M37 uses 'high7' as
    its top-tier family equivalent to Seven1 on M1."""
    w = _load_weights()
    reels = w["reel_sets"]["default"]["reels"]
    # Check reel 0: high7 clustered with blanks (alternation)
    ratio = pwdf_ratio(reels[0], "high7")
    assert ratio > 1.5, f"high7 PWDF on reel 0 should reflect clustering, got {ratio}"
    mid_p = symbol_mid_probability(reels[0], "high7")
    win_p = symbol_window_probability(reels[0], "high7")
    assert win_p > mid_p, f"window prob should exceed mid prob: win={win_p}, mid={mid_p}"


def test_near_miss_rate_returns_finite():
    w = _load_weights()
    reels = w["reel_sets"]["default"]["reels"]
    nm = near_miss_rate_2_of_3(reels, "high7")
    assert 0 <= nm < 1, f"near-miss rate out of range: {nm}"


def test_experience_cost_band_respects_initial():
    """Cost should NOT heavily penalize an already well-clustered initial
    design. For M37's base reel (perfect alternation), total cost should be
    dominated by the blank_adj bonus (negative), not large penalties.
    M37 uses lowercase 'blank' and has different high-value symbols
    (high7, grand, major) than M1's Seven1/Diamond1/etc."""
    w = _load_weights()
    reels = w["reel_sets"]["default"]["reels"]
    # M37 high-value family: high7 (top-tier regular) + grand/major (boosters).
    b = evaluate_experience_cost(
        reels,
        high_value=("high7", "grand", "major", "minor"),
        blank_symbol="blank",
    )
    # blank_adj_bonus is negative, nm/pwdf should be small or zero
    assert b.blank_adj_bonus < 0, (
        f"expected blank_adj_bonus to be negative (reward); got "
        f"{b.blank_adj_bonus}. Breakdown: {b}"
    )
    # Total may be dominated by nm-below-min penalty if counts are sparse,
    # but the optimizer design ensures it doesn't blow up on reasonable inputs.
    assert b.total < 100, f"cost unexpectedly high for good initial: {b.total}"


if __name__ == "__main__":
    import inspect

    mod = sys.modules[__name__]
    tests = [obj for name, obj in inspect.getmembers(mod)
             if name.startswith("test_") and callable(obj)]
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
