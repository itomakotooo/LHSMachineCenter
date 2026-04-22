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
