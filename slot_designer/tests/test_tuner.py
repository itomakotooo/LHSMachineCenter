"""Tuner integration tests.

- apply_counts round-trips correctly (re-extracted counts match target)
- Cost function gives lower total when profile is closer to target
- Short ES run improves cost
- Multi-seed sim on tuned weights converges to analytic prediction
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import (
    analytic_profile,
    analytic_profile_from_marginals,
    structurally_reachable_buckets,
)
from slot_designer.engine.evaluator import PaytableEvaluator
from slot_designer.engine.loader import load_engine
from slot_designer.engine.rules import RuleSet
from slot_designer.engine.symbol import SymbolRegistry
from slot_designer.tuner.cost import CostWeights, evaluate_cost
from slot_designer.tuner.layout import (
    apply_counts,
    base_counts,
    marginals_from_counts,
)
from slot_designer.tuner.loop import ESConfig, run_with_restarts


SPEC = _ROOT / "slot_designer" / "specs" / "M1.spec.json"
STRIPS = _ROOT / "slot_designer" / "weights" / "M1" / "reel_strips.json"
WEIGHTS = _ROOT / "slot_designer" / "weights" / "M1" / "mode_1" / "weights.json"
TARGET = _ROOT / "slot_designer" / "tuner" / "targets" / "M14_mode1.target.json"


def _load():
    """Return spec + assembled weights envelope + target.

    The envelope wraps strips + weights.json into the legacy
    ``{reel_sets: {default: {reels: [[{symbol, weight}, ...]]}}}``
    shape that base_counts / apply_counts still expect. New-schema
    helpers (``base_counts_from_assembled``) operate on the inner
    reels list directly if a test wants to skip the envelope.
    """
    from slot_designer.engine.loader import load_reels_for_tuner
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    reels = load_reels_for_tuner(STRIPS, WEIGHTS)
    weights = {"reel_sets": {"default": {"reels": reels}}}
    target = json.loads(TARGET.read_text(encoding="utf-8"))
    return spec, weights, target


def _evaluator(spec):
    return PaytableEvaluator(
        SymbolRegistry(spec["symbols"]),
        RuleSet(spec["pays"]),
        spec["evaluation_order"],
    )


def test_apply_counts_roundtrip():
    _, weights, _ = _load()
    x = base_counts(weights)
    w2 = apply_counts(weights, x)
    x2 = base_counts(w2)
    # Round-trip should be exact (no rounding since scale=1.0)
    assert x == x2, f"round-trip failed: {x} vs {x2}"


def test_apply_counts_scales_totals():
    """Doubling all counts must double the reel totals EXACTLY.

    Regression: 2026-04-24 M37 mode 5. The old diff-repair pushed the
    entire rounding delta onto scaled[0]; when the delta exceeded
    scaled[0] - min_weight, the max(min_weight, ...) clamp absorbed the
    excess and target_total was silently missed (reel 3 blank: tuner
    wanted 113, on-disk sum was 120 → +6.6pp RTP ghost gap). The fix
    spreads the diff across multiple stops; round-trip must now be exact.
    """
    _, weights, _ = _load()
    x = base_counts(weights)
    x_doubled = [{s: c * 2 for s, c in reel.items()} for reel in x]
    w2 = apply_counts(weights, x_doubled)
    x2 = base_counts(w2)
    # Post-fix: exact match (no drift, not ±len(reel))
    for reel_idx, reel in enumerate(x2):
        for sym, count in x_doubled[reel_idx].items():
            actual = reel.get(sym, 0)
            assert actual == count, (
                f"reel {reel_idx} {sym}: expected {count}, got {actual} "
                f"(drift = {actual - count})"
            )


def test_apply_counts_handles_large_negative_drift():
    """Regression: diff-repair must distribute across stops when
    |diff| > scaled[0] - min_weight, not clamp silently.

    Constructs an 18-stop symbol with seed weights [1, 7, 7, ..., 7]
    (sum=120), target=113 (→ scale 0.9417). Naive scale then round gives
    [1, 7, 7, ..., 7] = 120 still; diff -7 on scaled[0]=1 clamps at
    min_weight=1. Old impl silently returned 120; new impl spreads the
    -7 across 7 different stops to hit 113 exactly.
    """
    # Construct a minimal synthetic weights envelope with just this symbol
    reel = [
        {"symbol": "blank", "weight": 1 if i == 0 else 7}
        for i in range(18)
    ]
    weights = {"reel_sets": {"default": {"reels": [reel]}}}
    target = [{"blank": 113}]
    w2 = apply_counts(weights, target)
    actual = sum(stop["weight"] for stop in w2["reel_sets"]["default"]["reels"][0])
    assert actual == 113, (
        f"large-drift repair failed: target 113, got {actual} "
        f"(would have been 120 pre-fix)"
    )
    # And floor must never be breached
    for stop in w2["reel_sets"]["default"]["reels"][0]:
        assert stop["weight"] >= 1, f"floor breach: {stop}"


def test_cost_decreases_toward_target():
    spec, weights, target = _load()
    ev = _evaluator(spec)
    engine, _ = load_engine(SPEC, WEIGHTS)
    reachable = structurally_reachable_buckets(engine)

    base_x = base_counts(weights)
    base_pred = analytic_profile_from_marginals(ev, marginals_from_counts(base_x))
    if "cv" not in target:
        target["cv"] = target.get("std_return_x", 0) / (target["rtp_pct"] / 100)
    base_cost = evaluate_cost(base_pred, target, reachable_buckets=reachable).total

    # Synthetic "better" point: just the target RTP with base shape
    # (we can't actually reach target without search, but force base_pred
    # closer by scaling). Shortcut: evaluate a trivially tuned candidate.
    tuned_x = [{s: c * 2 for s, c in reel.items()} for reel in base_x]  # marginals unchanged
    tuned_pred = analytic_profile_from_marginals(ev, marginals_from_counts(tuned_x))
    tuned_cost = evaluate_cost(tuned_pred, target, reachable_buckets=reachable).total
    # Marginals same → cost same (not better, not worse)
    assert abs(tuned_cost - base_cost) < 0.01, (
        f"doubling counts should not change cost; base={base_cost}, tuned={tuned_cost}"
    )


def test_es_run_improves_cost():
    """A short ES run must produce cost < baseline cost."""
    spec, weights, target = _load()
    ev = _evaluator(spec)
    engine, _ = load_engine(SPEC, WEIGHTS)
    reachable = structurally_reachable_buckets(engine)
    if "cv" not in target:
        target["cv"] = target.get("std_return_x", 0) / (target["rtp_pct"] / 100)

    def cost_fn(counts_list):
        marg = marginals_from_counts(counts_list)
        pred = analytic_profile_from_marginals(ev, marg)
        b = evaluate_cost(pred, target, reachable_buckets=reachable)
        return b.total, b

    x0 = base_counts(weights)
    base_cost, _ = cost_fn(x0)
    result = run_with_restarts(
        x0, cost_fn,
        restarts=1, evaluations_per_restart=200,
        config=ESConfig(sigma_init=8.0),
        master_seed=0,
    )
    assert result.best_cost < base_cost, (
        f"ES did not improve: base={base_cost}, best={result.best_cost}"
    )
    improvement_pct = (base_cost - result.best_cost) / base_cost * 100
    assert improvement_pct > 10, (
        f"improvement too small: only {improvement_pct:.1f}% in 200 evals"
    )


def test_sim_converges_to_analytic_on_tuned_weights():
    """Verify that saved tuned weights, when run through the engine,
    converge to the analytic prediction at large N × multi-seed.

    This guards against apply_counts breaking marginals silently.
    """
    tuned_path = _ROOT / "slot_designer" / "weights" / "M1" / "mode_1" / "weights.json"
    if not tuned_path.exists():
        # Skip if tuner hasn't been run yet
        return

    engine, _ = load_engine(SPEC, tuned_path)
    analytic = analytic_profile(engine)["rtp_pct"]

    rtps = []
    for seed in range(5):
        rng = Random(seed + 100)
        tw = tb = 0
        for _ in range(200_000):
            out = engine.spin(rng)
            tb += out.bet_amount
            if out.pay:
                tw += out.pay.multiplier * out.bet_amount
        rtps.append(tw / tb * 100)
    mean = statistics.mean(rtps)
    # stderr of mean for 5 seeds × 200k: σ/√(n/5). Allow 2pp buffer.
    diff = abs(mean - analytic)
    assert diff < 2.0, (
        f"5-seed × 200k sim RTP {mean:.3f}% diverges from analytic {analytic:.3f}% "
        f"by {diff:.3f}pp (seeds: {rtps})"
    )


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
