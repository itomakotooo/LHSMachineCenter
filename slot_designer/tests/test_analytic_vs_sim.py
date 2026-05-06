"""Analytic should converge to what the simulator produces.

For given weights, `analytic_profile` computes RTP / bucket / per-pay_id
directly from reel marginals × paytable rules. The simulator produces
stochastic samples that converge to the same values. At 110k spins, the
CI is tight enough that the analytic prediction should land inside.

We use this as a correctness test for BOTH pipelines — if analytic and
sim disagree beyond CI, one of them has a bug (typically the evaluator
or a probability edge case).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import analytic_profile
from slot_designer.engine.loader import load_engine


SPEC = _ROOT / "slot_designer" / "specs" / "M1.spec.json"
WEIGHTS = _ROOT / "slot_designer" / "weights" / "M1" / "mode_1" / "weights.json"


def _simulate_rtp(engine, n: int, seed: int = 42) -> tuple[float, float]:
    """Run N spins and return (rtp_fraction, hit_rate). No analyzer, just raw tally."""
    rng = Random(seed)
    total_win = 0
    total_bet = 0
    hit_count = 0
    for _ in range(n):
        out = engine.spin(rng)
        total_bet += out.bet_amount
        if out.pay is not None:
            win = out.pay.multiplier * out.bet_amount
            total_win += win
            hit_count += 1
    return total_win / total_bet if total_bet else 0.0, hit_count / n


def test_analytic_probabilities_sum_to_one():
    engine, _ = load_engine(SPEC, WEIGHTS)
    prof = analytic_profile(engine)
    assert abs(prof["total_prob"] - 1.0) < 1e-9, prof["total_prob"]


def test_analytic_matches_simulator_rtp():
    """Multi-seed averaging: 5 × 100k spins, stderr of mean ≈ 1pp for M1
    (σ_return ≈ 7.4, stderr_single = 2.34pp, /√5 ≈ 1.05pp). Threshold 1.5pp
    gives ~1.4σ headroom so the test is reliable across reasonable luck."""
    engine, _ = load_engine(SPEC, WEIGHTS)
    prof = analytic_profile(engine)
    analytic_rtp = prof["rtp_pct"] / 100
    rtps = [_simulate_rtp(engine, n=100_000, seed=s)[0] for s in range(5)]
    mean_sim = sum(rtps) / len(rtps)
    diff_pp = abs(mean_sim - analytic_rtp) * 100
    assert diff_pp < 1.5, (
        f"5-seed mean sim RTP {mean_sim*100:.3f}% vs analytic {analytic_rtp*100:.3f}%, "
        f"Δ={diff_pp:.3f}pp > 1.5pp (seeds: {[f'{r*100:.2f}' for r in rtps]})"
    )


def test_analytic_matches_simulator_hit_rate():
    engine, _ = load_engine(SPEC, WEIGHTS)
    prof = analytic_profile(engine)
    _, sim_hit = _simulate_rtp(engine, n=200_000, seed=42)
    # hit_rate 2σ ≈ 2√(p(1-p)/n). For p≈0.18, n=200k: 2σ ≈ 0.17pp.
    # Allow 0.5pp — tight but robust.
    diff_pp = abs(sim_hit - prof["hit_rate"]) * 100
    assert diff_pp < 0.5, (
        f"sim hit {sim_hit*100:.3f}% vs analytic {prof['hit_rate']*100:.3f}%, Δ={diff_pp:.3f}pp"
    )


def test_analytic_bucket_rates_are_non_negative():
    engine, _ = load_engine(SPEC, WEIGHTS)
    prof = analytic_profile(engine)
    for k, v in prof["bucket_rate"].items():
        assert v >= 0, f"{k} has negative probability {v}"


def test_m1_cannot_reach_sub_one_bucket():
    """M1 paytable has no pay with multiplier < 1; gt0_lt1 bucket must be
    structurally empty regardless of weights."""
    engine, _ = load_engine(SPEC, WEIGHTS)
    prof = analytic_profile(engine)
    assert prof["bucket_rate"].get("gt0_lt1", 0) == 0, (
        f"gt0_lt1 should be 0 for M1, got {prof['bucket_rate'].get('gt0_lt1')}"
    )


# =============================================================================
# M37 reroll-block regression — analytic must model `(wild,grand,wild)` reroll
# =============================================================================
# Without reroll modeling, mode 5 analytic over-reports by ~2.4pp (combo
# probability 0.024% × payout 100× = 2.4pp lost when the engine rerolls these
# spins). Bug 2026-05-06: caught when mode 5 sim consistently landed -3pp
# below analytic across 5 seeds. Fix: analytic_profile detects reroll_blocks
# from evaluator.rules and renormalizes (drop blocked combos + scale by
# 1/(1-P_blocked)). This test pins the post-reroll alignment.

_M37_SPEC = _ROOT / "slot_designer" / "specs" / "M37.spec.json"
_M37_STRIPS = _ROOT / "slot_designer" / "weights" / "M37" / "reel_strips.json"
_M37_M5_WEIGHTS = _ROOT / "slot_designer" / "weights" / "M37" / "mode_5" / "weights.json"


def test_m37_mode5_analytic_includes_reroll_correction():
    """Mode 5 has the largest reroll impact in the fleet (P=0.024%, payout
    100× → 2.4pp). Analytic post-reroll should match engine sim within
    sampling noise across 5 seeds at 1M each (CV~6.7, stderr√5 ≈ 1.3pp).

    Three guards layered (each catches a different regression mode):
      1. p_reroll_blocked > 0 — reroll detection working
      2. total_prob == 1.0 — renormalization applied (without it,
         total_prob = 1 - P_blocked < 1.0, catching the 'detect but don't
         renormalize' bug that slips through pure RTP comparison since
         blocked contribution drop happens to cancel ~half the renorm gap)
      3. analytic ≈ sim within 2pp — end-to-end empirical alignment
    """
    engine, _ = load_engine(_M37_SPEC, _M37_M5_WEIGHTS, strips_path=_M37_STRIPS)
    prof = analytic_profile(engine)

    # Guard 1: reroll detection must trigger
    p_blocked = prof.get("p_reroll_blocked", 0)
    assert p_blocked > 0.0001, (
        f"M37 mode 5 should have non-trivial reroll P (expected ≥ 0.01%, got {p_blocked*100:.4f}%); "
        "if this drops to 0, analytic is no longer applying reroll correction"
    )

    # Guard 2: post-renormalization total_prob must sum to 1.0 (without
    # renormalization, total_prob = 1 - P_blocked ≈ 0.99976)
    assert abs(prof["total_prob"] - 1.0) < 1e-9, (
        f"M37 mode 5 total_prob = {prof['total_prob']:.6f}, expected 1.0 "
        f"(if this is ~0.99976, reroll renormalization is missing — analytic "
        f"detected blocked combos but didn't renormalize the surviving ones)"
    )

    # Guard 3: end-to-end analytic ≈ sim
    analytic_rtp = prof["rtp_pct"] / 100
    rtps = [_simulate_rtp(engine, n=1_000_000, seed=s)[0] for s in range(5)]
    mean_sim = sum(rtps) / len(rtps)
    diff_pp = abs(mean_sim - analytic_rtp) * 100
    assert diff_pp < 2.0, (
        f"5-seed mean sim RTP {mean_sim*100:.3f}% vs reroll-aware analytic "
        f"{analytic_rtp*100:.3f}%, Δ={diff_pp:.3f}pp > 2.0pp "
        f"(seeds: {[f'{r*100:.2f}' for r in rtps]})"
    )


def test_m37_mode1_no_reroll_impact():
    """Mode 1 has the same reroll_blocks rule but the (wild,grand,wild)
    probability is tiny (P~3.5e-7) → reroll correction must be near-zero
    so it doesn't artificially inflate mode 1 metrics."""
    M1_W = _ROOT / "slot_designer" / "weights" / "M37" / "mode_1" / "weights.json"
    engine, _ = load_engine(_M37_SPEC, M1_W, strips_path=_M37_STRIPS)
    prof = analytic_profile(engine)
    p_blocked = prof.get("p_reroll_blocked", 0)
    assert p_blocked < 1e-5, (
        f"M37 mode 1 P_blocked should be tiny (<0.001%), got {p_blocked*100:.6f}%"
    )


if __name__ == "__main__":
    import inspect

    mod = sys.modules[__name__]
    tests = [obj for name, obj in inspect.getmembers(mod)
             if name.startswith("test_") and callable(obj)]
    passed = 0
    failures: list[tuple[str, BaseException]] = []
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
