"""Tune M1 mode weights — player-experience direct objective.

Per ``project_slot_designer_axiom_experience_is_soul``: TDD numbers are
inspiration, not constraint. Cost function targets player experience red
lines (family RTP share, wild signature, per-reel density) directly.

Hard rules:
  - Paytable LOCKED
  - Physical Blank-non-Blank alternation LOCKED (in strip layout)
  - Mode RTP: 1=95%, 7=85% (standard); 2=300%, 5=500% (lucky)
  - Mode 7 = mode 1 - 砍小奖派生：大奖击中率/产出期望绝对不砍
    (Diamond/Seven family RTP contribution = mode 1's, ±0.6pp)

Player experience targets (Double Diamond signature, M1 specific):
  - Wild on payline P(>=1 wild) — see EXPERIENCE_TARGETS
  - Family RTP shares — band per mode
  - Per-reel per-family density — bounded to be视觉 reasonable

Parameterization (27-dim per mode):
  weights[reel r][pos p] = W[(family_at(r, p), r)]
  All positions of same family on same reel share one weight.

Search: random-restart local search with adaptive sigma. Cost combines
RTP/hit/bucket numeric targets with family share / wild signature /
density experience penalties (experience layered ON TOP of numeric).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import (
    analytic_profile_from_marginals,
    structurally_reachable_buckets,
    multiplier_to_bucket,
)
from slot_designer.engine.loader import load_engine
from slot_designer.engine.evaluator import PaytableEvaluator
from slot_designer.engine.rules import RuleSet
from slot_designer.engine.symbol import SymbolRegistry
from slot_designer.tuner.cost import CostWeights, evaluate_cost
from slot_designer.tuner.layout import marginals_from_counts


SPEC_PATH = _ROOT / "slot_designer" / "specs" / "M1.spec.json"
STRIPS_PATH = _ROOT / "slot_designer" / "weights" / "M1" / "reel_strips.json"

SYMBOLS = ("Blank", "Diamond1", "Diamond2", "Seven1", "Seven2",
           "Cherry", "Bar1", "Bar2", "Bar3")

# Per-family per-reel weight bounds. Each is integer >= 1.
# Lower bound floor=1 means "family stays present, never zero out".
# Standard modes (1, 7) use tight bounds to preserve TDD-style classic feel.
# Lucky modes (2, 5) need wider upper bounds — particularly Seven family
# which is the "7-dominated" engine for the lucky/super-lucky feel.
WEIGHT_BOUNDS_STANDARD: dict[str, tuple[int, int]] = {
    "Blank":     (3, 30),
    "Diamond1":  (3, 12),
    "Diamond2":  (3, 12),
    "Seven1":    (1, 20),
    "Seven2":    (1, 20),
    "Cherry":    (1, 30),
    "Bar1":      (1, 30),
    "Bar2":      (1, 30),
    "Bar3":      (1, 30),
}

WEIGHT_BOUNDS_LUCKY: dict[str, tuple[int, int]] = {
    "Blank":     (1, 30),     # less filler, more pay in lucky modes
    "Diamond1":  (3, 18),
    "Diamond2":  (3, 18),
    "Seven1":    (1, 60),     # 7-dominated lucky engine
    "Seven2":    (1, 60),
    "Cherry":    (1, 40),
    "Bar1":      (1, 40),
    "Bar2":      (1, 40),
    "Bar3":      (1, 40),
}

WEIGHT_BOUNDS_BY_MODE = {
    1: WEIGHT_BOUNDS_STANDARD,
    7: WEIGHT_BOUNDS_STANDARD,
    2: WEIGHT_BOUNDS_LUCKY,
    5: WEIGHT_BOUNDS_LUCKY,
}

# Player experience targets — ground truth for "假但不怪".
# Sources: classic 1-line slot benchmarks (RWB/Blazing Sevens published
# data) + Double Diamond brand expectation + IGT TDD WoO data.
EXPERIENCE_TARGETS = {
    1: {
        "wild_on_payline_band": (0.15, 0.22),
        "family_share_bands": {
            "Diamond": (0.18, 0.28),
            "Seven":   (0.15, 0.25),
            "Bar3":    (0.10, 0.18),
            "Bar2":    (0.08, 0.15),
            "Bar1":    (0.05, 0.12),
            "Cherry":  (0.08, 0.15),
        },
        "per_reel_density_band": (0.01, 0.22),
        "top_jackpot_max_spins": 300_000,  # Diamond2×3 期望 spin
    },
    7: {
        # Mode 7 inherits mode 1 experience targets EXCEPT:
        # - Diamond/Seven RTP CONTRIBUTION (in absolute pp) MUST EQUAL mode 1's
        # - Bar3/Bar2 contribution -1 to -2 pp from mode 1
        # - Bar1/Cherry contribution -2 to -3 pp from mode 1
        # These are computed dynamically in mode 7 cost using mode 1 anchor.
        "wild_on_payline_band": (0.15, 0.22),  # signature unchanged
        "per_reel_density_band": (0.01, 0.22),
        "top_jackpot_max_spins": 300_000,
    },
    2: {
        # Lucky mode — 7-dominated per industry research (RWB 50% / Blazing 68%).
        # All families boost relative to mode 1, Seven family BACKBONE.
        # Wild signature must stay close to mode 1 (signature 一致).
        "wild_on_payline_band": (0.15, 0.30),
        "family_share_bands": {
            "Diamond": (0.10, 0.25),
            "Seven":   (0.35, 0.65),  # 7-dominated lucky
            "Bar3":    (0.05, 0.18),
            "Bar2":    (0.03, 0.13),
            "Bar1":    (0.03, 0.13),
            "Cherry":  (0.03, 0.13),
        },
        "per_reel_density_band": (0.01, 0.30),  # higher density allowed in lucky modes
        "top_jackpot_max_spins": 300_000,
    },
    5: {
        # Super-lucky — even more 7-heavy + bigger top tier.
        "wild_on_payline_band": (0.15, 0.30),
        "family_share_bands": {
            "Diamond": (0.08, 0.30),
            "Seven":   (0.50, 0.80),  # super-lucky 7-very-heavy
            "Bar3":    (0.03, 0.15),
            "Bar2":    (0.02, 0.10),
            "Bar1":    (0.01, 0.08),
            "Cherry":  (0.01, 0.08),
        },
        "per_reel_density_band": (0.01, 0.35),
        "top_jackpot_max_spins": 300_000,
    },
}


# Map pay_id -> family for RTP share aggregation.
# Per spec/M1.spec.json:
#   Cherry: pay_id 12, 13, 14 (cherry_count)
#   Diamond/Wild: pay_id 2, 3, 4 (pure_wild + pure_wild_group)
#                  Note: pay_id 4 is rtp_excluded; included in family share
#                  computation only via direct hit, not RTP contribution.
#   Seven: pay_id 5 (Seven2x3), 6 (Seven1x3), 10 (line_3_group seven)
#   Bar3:  pay_id 7
#   Bar2:  pay_id 8
#   Bar1:  pay_id 9
#   Bar_group: pay_id 11 (line_3_group bar) — split evenly across Bar1/2/3 for share
PAY_TO_FAMILY: dict[str, str] = {
    "12": "Cherry", "13": "Cherry", "14": "Cherry",
    "2": "Diamond", "3": "Diamond", "4": "Diamond",
    "5": "Seven", "6": "Seven", "10": "Seven",
    "7": "Bar3",
    "8": "Bar2",
    "9": "Bar1",
    "11": "Bar_group",  # split below
}

PAY_MULTIPLIER: dict[str, float] = {
    "14": 1.0, "13": 2.0, "12": 10.0,
    "2": 500.0, "3": 300.0,  # weighted avg of 240 and 360 — close enough
    "4": 1000.0,
    "5": 50.0, "6": 40.0,
    "7": 20.0, "8": 15.0, "9": 10.0,
    "10": 25.0, "11": 5.0,
}


def family_rtp_breakdown(profile: dict, paytable: list[dict]) -> dict[str, float]:
    """Compute per-family absolute RTP contribution (in % points).

    Uses ``pay_rtp`` from analytic_profile (= prob × actual_multiplier_per_combo,
    which INCLUDES wild substitution boost). So Bar3×3 with one 2x wild
    contributes its full 40× to Bar3 family, not the base 20×.
    """
    rtp_excluded_pids = {str(p["pay_id"]) for p in paytable if p.get("rtp_excluded")}

    family_rtp: dict[str, float] = defaultdict(float)
    for pid, rtp_contrib in profile.get("pay_rtp", {}).items():
        if pid in rtp_excluded_pids:
            continue  # top jackpot doesn't count toward RTP
        family = PAY_TO_FAMILY.get(pid, "Unknown")
        if family == "Bar_group":
            for bar in ("Bar1", "Bar2", "Bar3"):
                family_rtp[bar] += rtp_contrib / 3
        else:
            family_rtp[family] += rtp_contrib

    # rtp_contrib is fractional (0-1 range); convert to RTP pp
    return {f: r * 100 for f, r in family_rtp.items()}


def wild_on_payline_p(reel_marginals: list[dict[str, float]]) -> float:
    """P(>=1 wild on payline). 1 - prod(1 - density of any Diamond per reel)."""
    p_no_wild_all = 1.0
    for marg in reel_marginals:
        p_wild_reel = marg.get("Diamond1", 0) + marg.get("Diamond2", 0)
        p_no_wild_all *= (1.0 - p_wild_reel)
    return 1.0 - p_no_wild_all


def top_jackpot_expected_spins(reel_marginals: list[dict[str, float]]) -> float:
    """Expected spins to hit Diamond2×3."""
    p = 1.0
    for marg in reel_marginals:
        p *= marg.get("Diamond2", 0)
    return float("inf") if p == 0 else 1.0 / p


def per_reel_family_density(weights: list[list[int]],
                            strip: list[list[str]]) -> dict[tuple[str, int], float]:
    """{(family, reel_idx): density}."""
    out: dict[tuple[str, int], float] = {}
    for r_idx, (rw, rs) in enumerate(zip(weights, strip)):
        total = sum(rw)
        family_w: dict[str, int] = defaultdict(int)
        for w, sym in zip(rw, rs):
            family_w[sym] += w
        for f, w in family_w.items():
            out[(f, r_idx)] = w / total if total > 0 else 0
    return out


def build_weights_from_uniform(strip: list[list[str]],
                                fr_weights: dict[tuple[str, int], int]) -> list[list[int]]:
    """fr_weights: {(family, reel_idx): weight}. Apply uniformly to all positions
    of that family on that reel."""
    out = []
    for r_idx, strip_reel in enumerate(strip):
        reel = []
        for sym in strip_reel:
            reel.append(int(fr_weights[(sym, r_idx)]))
        out.append(reel)
    return out


def counts_from_weights(strips, weights):
    counts = []
    for reel_idx, strip in enumerate(strips):
        c: dict[str, int] = defaultdict(int)
        for pos, sym in enumerate(strip):
            c[sym] += weights[reel_idx][pos]
        counts.append(dict(c))
    return counts


def evaluate_candidate(
    fr_weights: dict[tuple[str, int], int],
    strip: list[list[str]],
    evaluator,
    target: dict,
    paytable: list[dict],
    reachable: set,
    cost_weights: CostWeights,
    experience_targets: dict,
    family_rtp_anchor: dict[str, float] | None = None,
    family_rtp_anchor_tol: dict[str, tuple[float, float]] | None = None,
):
    """Return (cost, predicted_profile, family_rtp, wild_p, weights_array).

    family_rtp_anchor: for mode 7, dict of {family: target_rtp_pp} from mode 1.
        Penalty pulls these families toward anchor.
    family_rtp_anchor_tol: {family: (lo_offset, hi_offset)} relative to anchor.
        e.g. for Bar3 略砍: (-2, -1) means mode 7 Bar3 should be 1-2pp below mode 1.
    """
    weights = build_weights_from_uniform(strip, fr_weights)
    counts = counts_from_weights(strip, weights)
    marg = marginals_from_counts(counts)
    pred = analytic_profile_from_marginals(evaluator, marg)

    # Base cost: RTP + bucket shape + CV + hit
    br = evaluate_cost(pred, target, reachable_buckets=reachable, weights=cost_weights)
    cost = br.total

    # Family RTP share penalty
    family_rtp = family_rtp_breakdown(pred, paytable)
    total_rtp = pred["rtp_pct"]

    if family_rtp_anchor is not None:
        # Mode 7 path: lock specific families to mode 1's absolute pp
        for f, anchor_pp in family_rtp_anchor.items():
            actual_pp = family_rtp.get(f, 0.0)
            if family_rtp_anchor_tol and f in family_rtp_anchor_tol:
                lo_off, hi_off = family_rtp_anchor_tol[f]
                lo = anchor_pp + lo_off
                hi = anchor_pp + hi_off
                if actual_pp < lo:
                    cost += 50.0 * (lo - actual_pp) ** 2
                elif actual_pp > hi:
                    cost += 50.0 * (actual_pp - hi) ** 2
            else:
                # Strict equality (Diamond/Seven absolute lock — 大奖 family
                # 击中率/产出期望绝对不砍 per axiom).
                cost += 500.0 * (actual_pp - anchor_pp) ** 2
    else:
        # Mode 1 path: use share band targets
        share_bands = experience_targets.get("family_share_bands", {})
        for f, (lo, hi) in share_bands.items():
            actual = family_rtp.get(f, 0.0) / total_rtp if total_rtp > 0 else 0
            if actual < lo:
                cost += 80.0 * ((lo - actual) * 100) ** 2
            elif actual > hi:
                cost += 80.0 * ((actual - hi) * 100) ** 2

    # Wild on payline signature penalty
    wild_p = wild_on_payline_p(marg)
    wild_lo, wild_hi = experience_targets["wild_on_payline_band"]
    if wild_p < wild_lo:
        cost += 100.0 * ((wild_lo - wild_p) * 100) ** 2
    elif wild_p > wild_hi:
        cost += 100.0 * ((wild_p - wild_hi) * 100) ** 2

    # Per-reel per-family density visual penalty
    densities = per_reel_family_density(weights, strip)
    den_lo, den_hi = experience_targets["per_reel_density_band"]
    for (f, r), d in densities.items():
        if f == "Blank":
            continue  # Blank density not visual-bound (it's the filler)
        if d < den_lo:
            cost += 30.0 * ((den_lo - d) * 100) ** 2
        elif d > den_hi:
            cost += 30.0 * ((d - den_hi) * 100) ** 2

    # Top jackpot reachability
    tj_max = experience_targets.get("top_jackpot_max_spins", 300_000)
    tj_spins = top_jackpot_expected_spins(marg)
    if tj_spins > tj_max:
        cost += 5.0 * ((tj_spins - tj_max) / tj_max) ** 2

    return cost, pred, family_rtp, wild_p, weights


def search_weights(
    target,
    strip,
    evaluator,
    paytable,
    reachable,
    experience_targets,
    cost_weights,
    weight_bounds,
    family_rtp_anchor=None,
    family_rtp_anchor_tol=None,
    seed=0,
    iterations=12000,
    verbose=False,
):
    rng = Random(seed)

    # Initialize: midpoint of bounds
    fr_weights: dict[tuple[str, int], int] = {}
    for sym in SYMBOLS:
        lo, hi = weight_bounds[sym]
        mid = (lo + hi) // 2
        for r in range(3):
            fr_weights[(sym, r)] = mid

    best = dict(fr_weights)
    best_cost, _, _, _, _ = evaluate_candidate(
        best, strip, evaluator, target, paytable, reachable,
        cost_weights, experience_targets, family_rtp_anchor, family_rtp_anchor_tol,
    )

    sigma_pct = 0.4
    success = 0
    window = 80
    win_evals = 0

    for step in range(1, iterations + 1):
        cand = dict(best)
        n_mutate = rng.randint(2, 5)
        keys_to_mutate = rng.sample(list(cand.keys()), n_mutate)
        for key in keys_to_mutate:
            sym, r = key
            lo, hi = weight_bounds[sym]
            cur = cand[key]
            delta = rng.gauss(0, sigma_pct * (hi - lo))
            new = int(round(cur + delta))
            new = max(lo, min(hi, new))
            cand[key] = new

        cost, _, _, _, _ = evaluate_candidate(
            cand, strip, evaluator, target, paytable, reachable,
            cost_weights, experience_targets, family_rtp_anchor, family_rtp_anchor_tol,
        )
        if cost < best_cost:
            best, best_cost = cand, cost
            success += 1
        win_evals += 1
        if win_evals >= window:
            if success / win_evals > 0.2:
                sigma_pct = min(0.4, sigma_pct * 1.1)
            else:
                sigma_pct = max(0.02, sigma_pct * 0.9)
            success = 0
            win_evals = 0
        if verbose and (step <= 5 or step % 1000 == 0):
            print(f"    step {step:>5}  cost={best_cost:.3f}  sigma={sigma_pct:.3f}")

    return best, best_cost


def report_candidate(
    fr_weights,
    strip,
    evaluator,
    paytable,
    reachable,
    experience_targets,
    cost_weights,
    family_rtp_anchor=None,
    family_rtp_anchor_tol=None,
):
    cost, pred, family_rtp, wild_p, weights = evaluate_candidate(
        fr_weights, strip, evaluator, target_dummy_for_repr(),
        paytable, reachable, cost_weights, experience_targets,
        family_rtp_anchor, family_rtp_anchor_tol,
    )
    return cost, pred, family_rtp, wild_p, weights


def target_dummy_for_repr():
    return {"rtp_pct": 95.0, "bucket_rate": {}, "cv": 5.0}


def print_diagnostics(label, fr_weights, strip, evaluator, paytable,
                      reachable, target, experience_targets, cost_weights,
                      family_rtp_anchor=None, family_rtp_anchor_tol=None):
    cost, pred, family_rtp, wild_p, weights = evaluate_candidate(
        fr_weights, strip, evaluator, target, paytable, reachable,
        cost_weights, experience_targets, family_rtp_anchor, family_rtp_anchor_tol,
    )
    print(f"\n  {label}:")
    print(f"    cost={cost:.3f}")
    print(f"    RTP={pred['rtp_pct']:.3f}%  hit={pred['hit_rate']:.3%}  CV={pred['cv']:.2f}")
    print(f"    wild_on_payline={wild_p*100:.2f}% (band {experience_targets['wild_on_payline_band'][0]*100:.0f}-{experience_targets['wild_on_payline_band'][1]*100:.0f}%)")
    print(f"    Top jackpot expected spins: {top_jackpot_expected_spins(marginals_from_counts(counts_from_weights(strip, weights))):,.0f}")
    print(f"    family RTP (pp):")
    total = pred["rtp_pct"]
    for f in ("Diamond", "Seven", "Bar3", "Bar2", "Bar1", "Cherry"):
        v = family_rtp.get(f, 0.0)
        share = v / total * 100 if total > 0 else 0
        print(f"       {f:8s}: {v:6.2f}pp ({share:5.1f}%)")
    print(f"    per-reel per-family density:")
    densities = per_reel_family_density(weights, strip)
    fams_in_order = ("Diamond1", "Diamond2", "Seven1", "Seven2", "Bar3", "Bar2", "Bar1", "Cherry", "Blank")
    print(f"       {'family':10s} R1     R2     R3")
    for f in fams_in_order:
        d1 = densities.get((f, 0), 0) * 100
        d2 = densities.get((f, 1), 0) * 100
        d3 = densities.get((f, 2), 0) * 100
        print(f"       {f:10s} {d1:5.2f}% {d2:5.2f}% {d3:5.2f}%")
    return pred, family_rtp, wild_p, weights


def main(modes_to_run=(1, 7)):
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    strip = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    symbols_reg = SymbolRegistry(spec["symbols"])
    rules = RuleSet(spec["pays"], reroll_blocks=spec.get("reroll_blocks"))
    evaluator = PaytableEvaluator(symbols_reg, rules, spec["evaluation_order"])
    paytable = spec["pays"]

    # reachable buckets — use mode 1 weights file as engine seed
    mode1_weights = _ROOT / "slot_designer" / "weights" / "M1" / "mode_1" / "weights.json"
    engine, _ = load_engine(SPEC_PATH, mode1_weights)
    reachable = structurally_reachable_buckets(engine)

    mode1_anchor: dict[str, float] | None = None

    # If mode 7 is being tuned without mode 1 in same run, load anchor from disk
    if 7 in modes_to_run and 1 not in modes_to_run:
        mode1_path = _ROOT / "slot_designer" / "weights" / "M1" / "mode_1" / "weights.json"
        try:
            mode1_data = json.loads(mode1_path.read_text(encoding="utf-8"))
            saved = mode1_data.get("_tuned_summary", {}).get("family_rtp_pp", {})
            if saved:
                mode1_anchor = {k: float(v) for k, v in saved.items()}
                print(f"[anchor] loaded mode 1 family RTP from disk: {mode1_anchor}")
        except (FileNotFoundError, json.JSONDecodeError):
            print("[anchor] could not load mode 1 anchor from disk; mode 7 will tune independently")

    for mode in modes_to_run:
        target_path = _ROOT / "slot_designer" / "tuner" / "targets" / f"M1_mode{mode}_{ {1: 'classic', 2: 'lucky', 5: 'super_lucky', 7: 'low_rtp'}[mode] }.target.json"
        target = json.loads(target_path.read_text(encoding="utf-8"))
        if "cv" not in target:
            target["cv"] = target.get("std_return_x", 0) / (target["rtp_pct"] / 100)

        # Mode 7 needs stronger RTP pull because family cut bands give
        # the optimizer wiggle room; without strong RTP weight it lands
        # at family-band corner with RTP overshoot.
        rtp_weight = 6.0 if mode == 7 else 2.0
        cost_weights = CostWeights(
            rtp_weight=rtp_weight,
            shape_weight=1.0,
            cv_weight=0.2,
            hit_target=target.get("hit_rate"),
            hit_weight=1.0,
        )

        exp_targets = EXPERIENCE_TARGETS[mode]

        family_anchor = None
        family_anchor_tol = None
        if mode == 7 and mode1_anchor is not None:
            # Mode 7 inherits Diamond/Seven absolute pp from mode 1
            family_anchor = {
                "Diamond": mode1_anchor["Diamond"],
                "Seven": mode1_anchor["Seven"],
            }
            # Bar3/Bar2 略砍 (-2 to -1pp), Bar1/Cherry 砍 (-3 to -2pp)
            family_anchor_tol = {
                # Diamond/Seven omitted -> strict equality penalty
            }
            # Add Bar3/Bar2/Bar1/Cherry as anchored with tolerance windows
            # Mode 7 RTP target = 85, mode 1 = ~94.6, gap = ~9.6pp.
            # Diamond + Seven locked → flex families absorb 9.6pp cut.
            # Distribution honoring user's 略砍 (mid) + 砍 (low):
            #   Bar3:   -1.5pp ± 0.5  (略砍, brand mid-tier)
            #   Bar2:   -1.5pp ± 0.5  (略砍)
            #   Bar1:   -3pp   ± 1    (砍, small)
            #   Cherry: -3.5pp ± 1    (砍, smallest)
            # Sum target ≈ -9.5pp → mode 7 ≈ 85.1pp
            family_anchor["Bar3"] = mode1_anchor["Bar3"]
            family_anchor_tol["Bar3"] = (-2.0, -1.0)
            family_anchor["Bar2"] = mode1_anchor["Bar2"]
            family_anchor_tol["Bar2"] = (-2.0, -1.0)
            family_anchor["Bar1"] = mode1_anchor["Bar1"]
            family_anchor_tol["Bar1"] = (-4.0, -2.0)
            family_anchor["Cherry"] = mode1_anchor["Cherry"]
            family_anchor_tol["Cherry"] = (-4.5, -2.5)

        print(f"\n=== Mode {mode} player-experience tune ===")
        print(f"  target: RTP {target['rtp_pct']}%  hit {target['hit_rate']:.2%}")
        if family_anchor:
            print(f"  family anchor (mode 1):")
            for f, v in family_anchor.items():
                tol_str = ""
                if family_anchor_tol and f in family_anchor_tol:
                    tol_str = f" (cut {family_anchor_tol[f][0]:+.1f} to {family_anchor_tol[f][1]:+.1f}pp)"
                else:
                    tol_str = " (strict)"
                print(f"     {f:8s}: anchor {v:.2f}pp{tol_str}")

        weight_bounds = WEIGHT_BOUNDS_BY_MODE[mode]
        best, best_cost = search_weights(
            target, strip, evaluator, paytable, reachable, exp_targets,
            cost_weights, weight_bounds, family_anchor, family_anchor_tol,
            seed=mode * 7 + 13, iterations=15000, verbose=True,
        )

        pred, family_rtp, wild_p, weights = print_diagnostics(
            f"Mode {mode} result",
            best, strip, evaluator, paytable, reachable, target, exp_targets,
            cost_weights, family_anchor, family_anchor_tol,
        )

        if mode == 1:
            mode1_anchor = dict(family_rtp)

        # Persist
        out_path = _ROOT / "slot_designer" / "weights" / "M1" / f"mode_{mode}" / "weights.json"
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        existing["mode"] = mode
        existing["weights"] = weights
        existing["_family_uniform_weights"] = {
            f"{sym}_R{r}": int(best[(sym, r)]) for sym in SYMBOLS for r in range(3)
        }
        existing["_notes"] = [
            f"M1 mode {mode} — player-experience direct tune.",
            "Per-family per-reel uniform weights (27 dim search), no TDD baseline scaling.",
            "Cost includes: RTP + hit + bucket + family RTP share + wild signature + per-reel density.",
            f"RTP {pred['rtp_pct']:.3f}%, hit {pred['hit_rate']:.3%}, wild_on_payline {wild_p*100:.2f}%",
        ]
        existing["_tuned_summary"] = {
            "rtp_pct": pred["rtp_pct"],
            "hit_rate": pred["hit_rate"],
            "cv": pred["cv"],
            "wild_on_payline": wild_p,
            "family_rtp_pp": {f: round(v, 3) for f, v in family_rtp.items()},
            "method": "player_experience_per_family_per_reel_uniform",
        }
        out_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {out_path.relative_to(_ROOT)}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", type=str, default="1,7")
    args = parser.parse_args()
    modes = tuple(int(m) for m in args.modes.split(","))
    main(modes_to_run=modes)
