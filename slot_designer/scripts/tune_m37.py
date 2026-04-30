"""Tune M37 mode weights — cost function references DESIGN.md derivations.

v7 clean rebuild (2026-04-29). Every numerical parameter traces to a §-numbered
section in ``slot_designer/weights/M37/DESIGN.md``. No picked numbers without
derivation chain. No cross-machine hardcoded thresholds.

Structure:
  - WEIGHT_BOUNDS: physical only [1, 1000] (DESIGN.md §15)
  - Per-mode targets: DESIGN.md §2-§6
  - Cost components: DESIGN.md §15
  - Bucket / hierarchy / asymmetry: DIRECTION-only penalties (DESIGN.md §7/§9/§10)

Mode tune order:
  - Mode 1 (DESIGN.md §13: standalone baseline)
  - Mode 7 (DESIGN.md §13: derived from mode 1 frozen big-win)
  - Mode 2 (DESIGN.md §14: derived from mode 1 floors)
  - Mode 5 (DESIGN.md §14: derived from mode 2 base + grand boost)

Run:
  python -m slot_designer.scripts.tune_m37 --modes 1
  python -m slot_designer.scripts.tune_m37 --modes 1,7
  python -m slot_designer.scripts.tune_m37 --modes 1,2,5,7
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import analytic_profile_from_marginals
from slot_designer.engine.loader import load_engine

SPEC_PATH = _ROOT / "slot_designer" / "specs" / "M37.spec.json"
STRIPS_PATH = _ROOT / "slot_designer" / "weights" / "M37" / "reel_strips.json"
WEIGHTS_DIR = _ROOT / "slot_designer" / "weights" / "M37"


# ═══════════════════════════════════════════════════════════════════
# Spec-level structural facts (NOT picked — engine + paytable physics)
# ═══════════════════════════════════════════════════════════════════

# Symbols on each reel (per reel_strips.json _invariants — wild only on R1+R3,
# booster only on R2)
SYMBOLS_BY_REEL = {
    0: ("blank", "wild", "high7", "7bar", "3bar", "2bar", "1bar"),
    1: ("blank", "high7", "7bar", "3bar", "2bar", "1bar", "mini", "minor", "major", "grand"),
    2: ("blank", "wild", "high7", "7bar", "3bar", "2bar", "1bar"),
}

# Big-win symbols frozen for mode 7 cut (DESIGN.md §13)
BIGWIN_SYMBOLS_R1 = ("wild", "high7")
BIGWIN_SYMBOLS_R2 = ("high7", "mini", "minor", "major", "grand")
BIGWIN_SYMBOLS_R3 = ("wild", "high7")

# Mode 7 bar tier split (DESIGN.md §13: 1bar/2bar/3bar = cut, 7bar = frozen)
SMALL_WIN_BARS = ("1bar", "2bar", "3bar")
MID_WIN_BARS = ("7bar",)

# Pay_id → family classification (per spec paytable, not picked)
PAY_TO_FAMILY = {
    "1":   "high7",          # 3-high7 10×
    "2":   "7bar",           # 3-7bar 6×
    "3":   "bar_tier",       # 3-3bar 5×
    "4":   "bar_tier",       # 3-2bar 4×
    "5":   "bar_tier",       # 3-1bar 3×
    "6":   "high7",          # high7+7bar mixed (2×)
    "7":   "bar_tier",       # bar mixed 1×
    "8":   "booster_alone",  # grand alone 100×
    "9":   "booster_alone",  # mini/minor/major alone OR side-wild alone
    "102": "wild_amplified", # pure-wild + major 100×
    "103": "wild_amplified", # pure-wild + minor 50×
    "104": "wild_amplified", # pure-wild + mini 20×
}

# Tier → bucket key mapping (per analytic_rtp _BUCKETS edges)
TIER_TO_BUCKETS = {
    "low":  ("gt0_lt1", "ge1_lt5", "ge5_lt10"),     # 1-10× pays
    "mid":  ("ge10_lt20", "ge20_lt50"),              # 10-50× pays
    "high": ("ge50_lt100", "ge100_lt200", "ge200_lt500"),  # 50-500×
    "top":  ("ge500_lt1000", "ge1000_lt5000", "ge5000"),   # 500×+
}


# ═══════════════════════════════════════════════════════════════════
# DESIGN.md §15: WEIGHT_BOUNDS — physical only
# ═══════════════════════════════════════════════════════════════════
# Lower bound 1: weight=0 means symbol absent at strip position
#   (engine-level: strip layout has these symbols → must have weight ≥ 1)
# Upper bound 1000: sentinel for SA mutation range. Effectively unbounded —
#   actual optimum weights settle in 1-50 range based on density requirements.
# NO per-family cap variation — that was v1-v6 picked-numbers anti-pattern.
WEIGHT_LO = 1
WEIGHT_HI = 1000


# ═══════════════════════════════════════════════════════════════════
# DESIGN.md §2: Mode RTP targets (USER-SPEC)
# ═══════════════════════════════════════════════════════════════════
RTP_TARGETS = {1: 95.0, 7: 85.0, 2: 300.0, 5: 500.0}
RTP_TOLERANCE_PP = {1: 1.0, 7: 2.0, 2: 20.0, 5: 40.0}


# ═══════════════════════════════════════════════════════════════════
# DESIGN.md §3: Hit rate targets (research-derived)
# ═══════════════════════════════════════════════════════════════════
# Modern multi-tier wild slot range 15-22% (Lightning Link / Dragon Link).
# M37 = LHS modern classic-with-multi-wild → middle of modern range.
HIT_RATE_TARGETS = {
    1: 0.18,   # mid of modern multi-wild range
    7: 0.14,   # m1 - 砍小奖 (Low ↓ ~30%, Mid+ unchanged)
    2: 0.25,   # m1 × 1.4 lucky
    5: 0.30,   # m2 + 顶奖加密
}
HIT_RATE_TOLERANCE = {1: 0.05, 7: 0.03, 2: 0.05, 5: 0.08}


# ═══════════════════════════════════════════════════════════════════
# DESIGN.md §4: Grand alone (pay_id 8) freq targets
# ═══════════════════════════════════════════════════════════════════
# Mode 1 derivation: P(≥1 grand alone in 300-spin session) ≥ 50%
#   → p ≥ 1 - 0.5^(1/300) = 0.00231 → freq ≥ 1/433
#   → choose 1/700 (above floor for comfortable session visibility)
GRAND_ALONE_FREQ_TARGETS = {
    1: 1.0/700,    # session-visibility derivation
    7: 1.0/700,    # = mode 1 (universal §4 cut-mode preserves big-win)
    2: 1.0/200,    # ~3× m1 (lucky tier)
    5: 1.0/40,     # ~5× m2 (super-lucky session moment)
}


# ═══════════════════════════════════════════════════════════════════
# DESIGN.md §5: 3-wild jackpot signature freq targets (mode 1 only)
# ═══════════════════════════════════════════════════════════════════
# Lucky modes (2/5) get natural lift from increased wild + booster density;
# no explicit target there.
THREE_WILD_FREQ_TARGETS_MODE1 = {
    "104": 1.0/8000,    # mini 3-wild = 20× — long-play visibility (v7 revised — see DESIGN.md §5)
    "103": 1.0/15000,   # minor 3-wild = 50× — hierarchy-rarer than mini
    "102": 1.0/30000,   # major 3-wild = 100× — rarest 3-wild
}


# ═══════════════════════════════════════════════════════════════════
# DESIGN.md §6: Top jackpot 1000× freq targets
# ═══════════════════════════════════════════════════════════════════
# Universal §7 (DESIGN_PHILOSOPHY) escalation: m5 > m2 > m1 ≈ m7
# Mid-of-band per universal §7 ranges.
TOP_JACKPOT_FREQ_TARGETS = {
    1: 1.0/80000,    # universal §7 mid (50-100k)
    7: 1.0/80000,    # = m1 (universal §4 cut-mode)
    2: 1.0/20000,    # universal §7 lucky mid (15-30k)
    5: 1.0/5000,     # universal §7 super-lucky mid (3-10k)
}


# ═══════════════════════════════════════════════════════════════════
# Cost component weights — calibrated for component-balance only
# ═══════════════════════════════════════════════════════════════════
# These are NOT goals (no "weight = 200 because that's the right amount").
# They balance cost-function components so RTP isn't trampled by hierarchy
# and vice versa. Each weight is justified by relative magnitude:
#
# Cost form: weight × (relative_deviation × 100)²
#   For RTP: dev = (actual-target)/tolerance ; tol=1pp = 1% → 100/1=100 max-cost
#   For freq: dev = (actual-target)/target ; full-deviation 100% → 100×100=10000 max
#
# Component target: each ~10000 cost when "fully off" so they balance.

W_RTP = 2000.0          # RTP is hardest business constraint (§2 user-spec) — dominant
W_HIT = 5000.0          # hit deviation in pp scale; 5pp-out-of-tol → 5000×25=125K
W_GRAND_FREQ = 500.0    # signature critical (§4 user brief)
W_3WILD_FREQ = 200.0    # signature (§5 user brief — 中轴jackpot 特色玩法)
W_TOP_FREQ = 300.0      # top escalation (universal §7)
W_BUCKET_DIRECTION = 100.0    # direction-only, modest weight
W_HIERARCHY_DIRECTION = 5000.0 # universal §1 hierarchy (strong — slot UX hard rule)
W_ASYMMETRY_DIRECTION = 300.0 # universal §12 (direction-only, moderate)
W_PAY_DOMINANCE = 3000.0      # universal §8: no single pay > 70% of hit count
W_BLANK_DENSITY = 5000.0      # archetype-derived blank ceilings (see _PER_REEL_BLANK_CAP)
W_OUTER_DOMINANCE = 2000.0    # outer-reel single-symbol-dominance (R1/R3 archetype derived)


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _density(weights, strips, reel_idx, sym):
    """P(picked-stop's payline symbol == sym) for one reel."""
    total = sum(weights[reel_idx])
    sym_w = sum(w for w, s in zip(weights[reel_idx], strips[reel_idx]) if s == sym)
    return sym_w / total if total > 0 else 0.0


def _all_densities(weights, strips):
    """{(symbol, reel_idx): density} for all reels + symbols."""
    out = {}
    for r in range(3):
        total = sum(weights[r])
        if total <= 0:
            continue
        for w, s in zip(weights[r], strips[r]):
            out[(s, r)] = out.get((s, r), 0.0) + w / total
    return out


def _build_marginals(weights, strips):
    """[{symbol: density}, ...] per reel — input to analytic_profile."""
    marginals = []
    for r in range(3):
        m = defaultdict(float)
        total = sum(weights[r])
        if total <= 0:
            marginals.append(dict(m))
            continue
        for w, s in zip(weights[r], strips[r]):
            m[s] += w / total
        marginals.append(dict(m))
    return marginals


def _family_rtp_breakdown(pred):
    """{family: total_rtp_pp} from pred.pay_rtp + PAY_TO_FAMILY mapping."""
    out = defaultdict(float)
    for pid, rtp in (pred.get("pay_rtp") or {}).items():
        family = PAY_TO_FAMILY.get(pid, "other")
        out[family] += rtp * 100  # convert prob×mult to pp
    return dict(out)


# ═══════════════════════════════════════════════════════════════════
# Cost function — component-additive, each component traces to DESIGN.md
# ═══════════════════════════════════════════════════════════════════

def predict_cost(weights, strips, evaluator, mode):
    """Compute cost for a candidate weight assignment. See DESIGN.md §15."""
    marginals = _build_marginals(weights, strips)
    pred = analytic_profile_from_marginals(evaluator, marginals)
    densities = _all_densities(weights, strips)

    cost = 0.0

    # ── DESIGN.md §2: RTP target (strict, user-spec)
    rtp_dev_pp = pred["rtp_pct"] - RTP_TARGETS[mode]
    rtp_tol = RTP_TOLERANCE_PP[mode]
    cost += W_RTP * (rtp_dev_pp / rtp_tol) ** 2

    # ── DESIGN.md §3: Hit rate target (broad band, soft)
    hit_dev = pred["hit_rate"] - HIT_RATE_TARGETS[mode]
    hit_tol = HIT_RATE_TOLERANCE[mode]
    if abs(hit_dev) > hit_tol:
        cost += W_HIT * ((abs(hit_dev) - hit_tol) / 0.01) ** 2

    # ── DESIGN.md §4: Grand alone freq (bidirectional pull)
    grand_target = GRAND_ALONE_FREQ_TARGETS[mode]
    grand_actual = pred.get("pay_hits", {}).get("8", 0.0)
    if grand_target > 0:
        rel_dev = (grand_actual - grand_target) / grand_target
        cost += W_GRAND_FREQ * (rel_dev * 100) ** 2

    # ── DESIGN.md §5: 3-wild jackpot freq (mode 1 only)
    if mode == 1:
        for pid, target in THREE_WILD_FREQ_TARGETS_MODE1.items():
            actual = pred.get("pay_hits", {}).get(pid, 0.0)
            if target > 0:
                rel_dev = (actual - target) / target
                cost += W_3WILD_FREQ * (rel_dev * 100) ** 2

    # ── DESIGN.md §6: Top jackpot 1000× freq (analytic from densities)
    p_top = (
        (densities.get(("high7", 0), 0.0) + densities.get(("wild", 0), 0.0))
        * densities.get(("grand", 1), 0.0)
        * (densities.get(("high7", 2), 0.0) + densities.get(("wild", 2), 0.0))
    )
    top_target = TOP_JACKPOT_FREQ_TARGETS[mode]
    if top_target > 0 and p_top > 0:
        rel_dev = (p_top - top_target) / top_target
        cost += W_TOP_FREQ * (rel_dev * 100) ** 2

    # ── DESIGN.md §7: Bucket DIRECTION (Low > Mid > High > Top by hit count)
    # One-sided penalty: only fires when direction violated.
    bucket_rate = pred.get("bucket_rate", {})
    tier_hits = {
        tier: sum(bucket_rate.get(k, 0.0) for k in keys)
        for tier, keys in TIER_TO_BUCKETS.items()
    }
    # Direction: low > mid > high > top
    tier_order = ("low", "mid", "high", "top")
    for i in range(len(tier_order) - 1):
        cur = tier_hits[tier_order[i]]
        nxt = tier_hits[tier_order[i + 1]]
        # Penalize when direction reversed (lower tier should have MORE hits than higher).
        # No `cur > 0` guard — violation real even if cur=0 and nxt>0 (e.g. all hits in Mid).
        if nxt > cur:
            gap = (nxt - cur) * 100  # pp scale
            cost += W_BUCKET_DIRECTION * gap ** 2

    # ── DESIGN.md §9: Hierarchy DIRECTION (universal §1)
    # Bar tier: 1bar > 2bar > 3bar > 7bar by R1+R3 frequency (lower payout = higher freq)
    # Booster tier: mini > minor > major > grand by R2 frequency
    BAR_ORDER = ("1bar", "2bar", "3bar", "7bar")
    for r in (0, 2):  # R1 + R3 only (bars on R1/R3)
        prev_d = None
        for s in BAR_ORDER:
            d = densities.get((s, r), 0.0)
            if d == 0:
                continue
            if prev_d is not None and d > prev_d:
                # Reversal: higher-payout denser than lower-payout
                gap = d - prev_d
                cost += W_HIERARCHY_DIRECTION * (gap * 100) ** 2
            prev_d = d

    BOOSTER_ORDER = ("mini", "minor", "major", "grand")
    prev_d = None
    for s in BOOSTER_ORDER:
        d = densities.get((s, 1), 0.0)
        if d == 0:
            continue
        if prev_d is not None and d > prev_d:
            gap = d - prev_d
            cost += W_HIERARCHY_DIRECTION * (gap * 100) ** 2
        prev_d = d

    # ── DESIGN.md §10: Reel asymmetry direction (universal §12)
    # R1 blank ≤ R3 blank, R1 (high7+wild) ≥ R3 (high7+wild)
    r1_blank = densities.get(("blank", 0), 0.0)
    r3_blank = densities.get(("blank", 2), 0.0)
    if r1_blank > r3_blank:
        gap_pp = (r1_blank - r3_blank) * 100
        cost += W_ASYMMETRY_DIRECTION * gap_pp ** 2

    r1_top = densities.get(("high7", 0), 0.0) + densities.get(("wild", 0), 0.0)
    r3_top = densities.get(("high7", 2), 0.0) + densities.get(("wild", 2), 0.0)
    if r1_top < r3_top:
        gap_pp = (r3_top - r1_top) * 100
        cost += W_ASYMMETRY_DIRECTION * gap_pp ** 2

    # ── Per-reel blank density ceiling (archetype-derived):
    #   R1/R3 (outer reels) ≤ 0.55: classic 1-line RWB/Blazing Sevens baseline
    #     has outer 40-55% blank; M37 archetype = classic → ≤ 55%.
    #   R2 (booster reel) ≤ 0.70: structurally blank-heavier (10 symbols vs 7
    #     outer), but above 70% feels "mostly blank" not "booster reel".
    #   These caps are M37-archetype-specific (DESIGN.md §1 + universal §3
    #   blank-cap headroom). Derivation: classic 1-line natural ratio + buffer.
    PER_REEL_BLANK_CAP = {0: 0.55, 1: 0.70, 2: 0.55}
    for r_idx, cap in PER_REEL_BLANK_CAP.items():
        actual = densities.get(("blank", r_idx), 0.0)
        if actual > cap:
            excess_pp = (actual - cap) * 100
            cost += W_BLANK_DENSITY * excess_pp ** 2

    # ── Outer reel single-symbol dominance (archetype-derived):
    #   No single non-blank symbol on R1 or R3 should exceed 30% density.
    #   Justification: classic 1-line outer reel has 6-7 distinct non-blank
    #   symbols. Uniform density = 8-12%. 30% = 2.5× uniform = "noticeably
    #   dominant but not absurd". Above 30% → reel reads "the X reel" rather
    #   than balanced symbol set (contradicts archetype balance intent).
    OUTER_SINGLE_SYM_CAP = 0.30
    for r_idx in (0, 2):
        for sym in SYMBOLS_BY_REEL[r_idx]:
            if sym == "blank":
                continue
            d = densities.get((sym, r_idx), 0.0)
            if d > OUTER_SINGLE_SYM_CAP:
                excess_pp = (d - OUTER_SINGLE_SYM_CAP) * 100
                cost += W_OUTER_DOMINANCE * excess_pp ** 2

    # ── Universal §8: hit decomposition — no single pay dominates 70% of hits.
    # Without this, optimizer exploits "freq target met" by stuffing pay_id 9
    # (booster_alone family that fires on near-empty payline) to 1/4 freq —
    # dominating hits to 90%+ and producing empty-calorie player feel.
    # Threshold 70% from universal §8 (not picked — DESIGN_PHILOSOPHY direct).
    hit_total = pred.get("hit_rate", 0.0)
    if hit_total > 0:
        for pid, freq in pred.get("pay_hits", {}).items():
            share_of_hits = freq / hit_total
            if share_of_hits > 0.70:
                excess = share_of_hits - 0.70
                cost += W_PAY_DOMINANCE * (excess * 100) ** 2

    return cost, pred


# ═══════════════════════════════════════════════════════════════════
# Simulated annealing — generic; per-mode constraints via frozen/floor/ceiling
# ═══════════════════════════════════════════════════════════════════

def _seed_archetype_weights(strips, frozen=None, floors=None):
    """Fresh weights initialized from M37 archetype (DESIGN.md §1 + reel_strips.json _archetype):

    - Outer reels (R1/R3): classic 1-line distribution
      blank ≈ 50% (per classic baseline)
      wild = 1× of bar tier (rarest non-blank)
      bar tier descending (1bar > 2bar > 3bar > 7bar per universal §1 hierarchy)
      high7 ≈ wild density (paired top-prize on outer)

    - Middle reel (R2): booster reel
      blank ≈ 60% (booster reel structurally blank-heavier per §15.5 redistribution baseline)
      booster tier descending (mini > minor > major > grand per §9 universal §1)
      grand at ~1/2 of major (rarest signature)
      high7 + bars present but minor presence (R2 identity = boosters)

    These ARE numbers, but each derived from archetype + universal §1/§9/§15. Optimizer
    fine-tunes from this sane basin instead of uniform-seed random walk into degenerate corners.
    """
    frozen = frozen or {}
    floors = floors or {}

    # R1/R3 archetype seed (relative weight ratios from classic slot density patterns)
    OUTER_SEED = {
        "blank": 18,  # ≈ 50% (18 blank stops × 18 weight ÷ ~660 total)
        "wild":  3,   # rarest non-blank (top-prize tier)
        "high7": 4,   # paired top-prize
        "7bar":  4,   # mid-payout bar
        "3bar":  6,
        "2bar":  8,
        "1bar":  12,  # most common bar (lowest payout per universal §1)
    }

    # R2 archetype seed (booster reel — boosters define R2 identity)
    R2_SEED = {
        "blank": 30,  # 60%+ blank (booster reel structurally blank-heavy)
        "high7": 4,
        "7bar":  3,
        "3bar":  3,
        "2bar":  3,
        "1bar":  3,
        "mini":  6,   # most common booster
        "minor": 4,
        "major": 3,
        "grand": 1,   # rarest signature (universal §1)
    }

    weights = []
    for r_idx, reel in enumerate(strips):
        sym_to_weight = {}
        seed_dict = R2_SEED if r_idx == 1 else OUTER_SEED
        for sym in set(reel):
            key = (sym, r_idx)
            if key in frozen:
                sym_to_weight[sym] = frozen[key]
            elif key in floors:
                # Use max(seed, floor) so floor not violated
                sym_to_weight[sym] = max(seed_dict.get(sym, 5), floors[key])
            else:
                sym_to_weight[sym] = seed_dict.get(sym, 5)
        weights.append([sym_to_weight[s] for s in reel])
    return weights


# Backwards-compat alias (search_weights uses this name)
_seed_uniform_weights = _seed_archetype_weights


def _mutate_weights(weights, strips, rng, sigma, frozen=None, floors=None,
                    ceilings=None):
    """Per-family-per-reel weight mutation. Applied uniformly to all positions
    of the same (symbol, reel)."""
    frozen = frozen or {}
    floors = floors or {}
    ceilings = ceilings or {}
    new = [list(row) for row in weights]
    for r_idx, reel in enumerate(strips):
        # Pick one (symbol, reel) per mutation step
        symbols = list(set(reel) - {s for s in set(reel) if (s, r_idx) in frozen})
        if not symbols:
            continue
        sym = rng.choice(symbols)
        cur = next(w for w, s in zip(new[r_idx], reel) if s == sym)
        # Multiplicative mutation
        delta = max(1, int(round(cur * sigma * rng.gauss(0, 1))))
        if rng.random() < 0.5:
            new_w = max(WEIGHT_LO, cur - delta)
        else:
            new_w = min(WEIGHT_HI, cur + delta)
        # Apply floor / ceiling
        floor = floors.get((sym, r_idx), WEIGHT_LO)
        ceiling = ceilings.get((sym, r_idx), WEIGHT_HI)
        new_w = max(floor, min(ceiling, new_w))
        # Apply uniformly to all positions of (sym, r_idx)
        for pos, s in enumerate(reel):
            if s == sym:
                new[r_idx][pos] = new_w
    return new


def search_weights(strips, evaluator, mode, *, frozen=None, floors=None,
                   ceilings=None, seed=42, iterations=30000, verbose=True,
                   restarts=3):
    """SA tune for one mode with restarts. Returns (best_weights, best_cost, best_pred).

    Multi-restart SA: each restart starts from new random seed, keeps the best
    across restarts. Cost surface for mode 1 is rugged (many components conflict),
    restarts help escape bad local minima.
    """
    overall_best_weights = None
    overall_best_cost = float("inf")
    overall_best_pred = None

    for restart_idx in range(restarts):
        rng = Random(seed + restart_idx * 1000)
        weights = _seed_uniform_weights(strips, frozen=frozen, floors=floors)
        cur_cost, cur_pred = predict_cost(weights, strips, evaluator, mode)
        best_weights = [list(r) for r in weights]
        best_cost = cur_cost
        best_pred = cur_pred

        # SA params: T calibrated for fine-tune from archetype seed (not random
        # exploration). T_init small so SA stays near seed basin.
        T_init = max(50.0, cur_cost * 0.001)  # 0.1% of seed cost
        T = T_init
        # Decay: T → ~0.0001×T_init by end → strongly greedy at tail
        T_decay = (0.0001) ** (1.0 / iterations)

        # Smaller sigma: fine-tune from archetype, don't drift to extremes
        sigma = 0.2
        sigma_phase_2 = iterations // 3
        sigma_phase_3 = 2 * iterations // 3

        for step in range(iterations):
            if step == sigma_phase_2:
                sigma = 0.15
            elif step == sigma_phase_3:
                sigma = 0.05

            cand = _mutate_weights(weights, strips, rng, sigma,
                                   frozen=frozen, floors=floors, ceilings=ceilings)
            cand_cost, cand_pred = predict_cost(cand, strips, evaluator, mode)

            if cand_cost < cur_cost:
                weights = cand
                cur_cost = cand_cost
                cur_pred = cand_pred
            elif rng.random() < math.exp(-(cand_cost - cur_cost) / max(T, 1e-9)):
                weights = cand
                cur_cost = cand_cost
                cur_pred = cand_pred

            if cur_cost < best_cost:
                best_cost = cur_cost
                best_pred = cur_pred
                best_weights = [list(r) for r in weights]

            T *= T_decay

            if verbose and step % 5000 == 0:
                print(f"    restart {restart_idx} step {step:5d}  cost={cur_cost:>12.3f}  best={best_cost:>12.3f}  T={T:.1f}  sigma={sigma:.3f}")

        if verbose:
            print(f"    restart {restart_idx} final: cost={best_cost:.3f} RTP={best_pred['rtp_pct']:.2f}% hit={best_pred['hit_rate']:.2%}")

        if best_cost < overall_best_cost:
            overall_best_cost = best_cost
            overall_best_weights = best_weights
            overall_best_pred = best_pred

    return overall_best_weights, overall_best_cost, overall_best_pred


# ═══════════════════════════════════════════════════════════════════
# Per-mode tune flow (DESIGN.md §13/§14)
# ═══════════════════════════════════════════════════════════════════

def tune_mode_1(strips, evaluator):
    """Mode 1 = standalone baseline."""
    print("=== Mode 1: standalone baseline (DESIGN.md §13/§14 baseline) ===")
    return search_weights(strips, evaluator, mode=1)


def tune_mode_7(strips, evaluator, mode_1_weights):
    """Mode 7 = mode 1 - 砍小奖派生 (DESIGN.md §13).
    Frozen: high7, wild (R1+R3), 7bar, mini/minor/major/grand (R2).
    Variable: 1bar/2bar/3bar (cut), blank (≥ m1).
    """
    print("=== Mode 7: 砍小奖派生 from mode 1 (DESIGN.md §13) ===")
    frozen = {}
    floors = {}
    # Freeze big-win weights = mode 1
    for r in (0, 2):
        for sym in BIGWIN_SYMBOLS_R1:  # = R3 same set
            w = next((w for w, s in zip(mode_1_weights[r], strips[r]) if s == sym), None)
            if w is not None:
                frozen[(sym, r)] = w
        # Freeze 7bar (mid bar = preserved)
        for sym in MID_WIN_BARS:
            w = next((w for w, s in zip(mode_1_weights[r], strips[r]) if s == sym), None)
            if w is not None:
                frozen[(sym, r)] = w
    # R2 big-win frozen
    for sym in BIGWIN_SYMBOLS_R2:
        w = next((w for w, s in zip(mode_1_weights[1], strips[1]) if s == sym), None)
        if w is not None:
            frozen[(sym, 1)] = w
    # R2 7bar frozen
    for sym in MID_WIN_BARS:
        w = next((w for w, s in zip(mode_1_weights[1], strips[1]) if s == sym), None)
        if w is not None:
            frozen[(sym, 1)] = w
    # Blank floor ≥ mode 1 (anti-density-inflation per §13)
    for r in range(3):
        w = next((w for w, s in zip(mode_1_weights[r], strips[r]) if s == "blank"), None)
        if w is not None:
            floors[("blank", r)] = w
    return search_weights(strips, evaluator, mode=7, frozen=frozen, floors=floors)


def tune_mode_2(strips, evaluator, mode_1_weights):
    """Mode 2 = lucky from mode 1 (DESIGN.md §14).
    All non-blank weights ≥ mode 1; blank weight ≤ mode 1.
    """
    print("=== Mode 2: lucky from mode 1 floors (DESIGN.md §14) ===")
    floors = {}
    ceilings = {}
    for r_idx, reel in enumerate(strips):
        for sym in set(reel):
            w = next((w for w, s in zip(mode_1_weights[r_idx], reel) if s == sym), None)
            if w is None:
                continue
            if sym == "blank":
                ceilings[(sym, r_idx)] = w  # blank ≤ m1
            else:
                floors[(sym, r_idx)] = w   # non-blank ≥ m1
    return search_weights(strips, evaluator, mode=2, floors=floors, ceilings=ceilings)


def tune_mode_5(strips, evaluator, mode_2_weights):
    """Mode 5 = super-lucky from mode 2 base + grand boost (DESIGN.md §14).
    bars + 7bar + high7 + wild + mini + minor frozen = m2;
    major weight ≥ m2; grand weight ≥ m2 × 5; blank ≥ m2.
    """
    print("=== Mode 5: super-lucky from mode 2 + grand boost (DESIGN.md §14) ===")
    frozen = {}
    floors = {}
    for r_idx, reel in enumerate(strips):
        for sym in set(reel):
            w = next((w for w, s in zip(mode_2_weights[r_idx], reel) if s == sym), None)
            if w is None:
                continue
            if sym == "grand":
                # Grand boost: floor = m2 × 5
                floors[(sym, r_idx)] = max(1, w * 5)
            elif sym == "major":
                # Major: floor = m2 (mid-tier multiplier preservation)
                floors[(sym, r_idx)] = w
            elif sym == "blank":
                # Blank: floor = m2 (preserve hit pattern)
                floors[(sym, r_idx)] = w
            else:
                # bars + 7bar + high7 + wild + mini + minor frozen
                frozen[(sym, r_idx)] = w
    return search_weights(strips, evaluator, mode=5, frozen=frozen, floors=floors)


# ═══════════════════════════════════════════════════════════════════
# Output / reporting
# ═══════════════════════════════════════════════════════════════════

def _print_result(mode, pred, weights, strips):
    print(f"\n  Mode {mode} result: cost={pred['rtp_pct']:.3f}% RTP, hit={pred['hit_rate']:.3%}")
    print(f"    CV={pred.get('cv', 0):.2f}")
    densities = _all_densities(weights, strips)
    family_rtp = _family_rtp_breakdown(pred)
    total = pred["rtp_pct"]
    print("    Family RTP shares:")
    for f in ("high7", "7bar", "bar_tier", "booster_alone", "wild_amplified"):
        rtp = family_rtp.get(f, 0)
        share = rtp / total * 100 if total else 0
        print(f"      {f:>16}: {rtp:6.2f}pp ({share:5.1f}%)")
    print("    Per-pay frequencies:")
    for pid in sorted(pred.get("pay_hits", {}).keys(), key=lambda p: int(p)):
        f = pred["pay_hits"][pid]
        rtp = pred.get("pay_rtp", {}).get(pid, 0.0) * 100
        print(f"      pay_id {pid:>4}: 1/{1/f if f else 0:>7.0f}  RTP {rtp:6.2f}pp")
    p_top = (
        (densities.get(("high7", 0), 0) + densities.get(("wild", 0), 0))
        * densities.get(("grand", 1), 0)
        * (densities.get(("high7", 2), 0) + densities.get(("wild", 2), 0))
    )
    print(f"    Top jackpot 1000×: 1/{1/p_top if p_top else 0:.0f} spins")
    print("    Per-reel density:")
    print(f"      {'family':<10} {'R1':>7} {'R2':>7} {'R3':>7}")
    for sym in ("blank", "wild", "high7", "7bar", "3bar", "2bar", "1bar",
                 "mini", "minor", "major", "grand"):
        dr = [densities.get((sym, r), 0) * 100 for r in range(3)]
        if sum(dr) > 0:
            print(f"      {sym:<10} {dr[0]:6.2f}% {dr[1]:6.2f}% {dr[2]:6.2f}%")


def _write_weights(mode, weights, pred):
    out_path = WEIGHTS_DIR / f"mode_{mode}" / "weights.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "machine": "M37",
        "mode": mode,
        "reel_set": "default",
        "_notes": [
            f"M37 mode {mode} v7 (2026-04-29 clean-slate rebuild).",
            f"All cost params trace to DESIGN.md §-numbers (no picked thresholds).",
            f"WEIGHT_BOUNDS: physical only [{WEIGHT_LO}, {WEIGHT_HI}] per DESIGN.md §15.",
            f"RTP target {RTP_TARGETS[mode]}% achieved {pred['rtp_pct']:.2f}%.",
            f"Hit target {HIT_RATE_TARGETS[mode]:.0%} achieved {pred['hit_rate']:.2%}.",
        ],
        "weights": weights,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {out_path.relative_to(_ROOT)}")


def main(modes_to_run=(1,)):
    strips_data = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))
    strips = strips_data["reels"]

    # Reload engine at each mode tune (engine evaluator doesn't depend on weights)
    # Use mode 1 weights as bootstrap for engine init (any valid weights work)
    bootstrap_path = WEIGHTS_DIR / "mode_1" / "weights.json"
    if not bootstrap_path.exists():
        # Write bootstrap stub so engine loader works
        bootstrap_path.parent.mkdir(parents=True, exist_ok=True)
        stub = {
            "machine": "M37", "mode": 1, "reel_set": "default",
            "weights": [[5] * len(reel) for reel in strips],
        }
        bootstrap_path.write_text(json.dumps(stub, indent=2), encoding="utf-8")

    engine, _ = load_engine(SPEC_PATH, bootstrap_path)
    evaluator = engine.evaluator

    mode_weights = {}

    if 1 in modes_to_run:
        w, _, p = tune_mode_1(strips, evaluator)
        _print_result(1, p, w, strips)
        _write_weights(1, w, p)
        mode_weights[1] = w

    if 7 in modes_to_run:
        if 1 not in mode_weights:
            mode_weights[1] = json.loads((WEIGHTS_DIR / "mode_1" / "weights.json").read_text(encoding="utf-8"))["weights"]
        w, _, p = tune_mode_7(strips, evaluator, mode_weights[1])
        _print_result(7, p, w, strips)
        _write_weights(7, w, p)
        mode_weights[7] = w

    if 2 in modes_to_run:
        if 1 not in mode_weights:
            mode_weights[1] = json.loads((WEIGHTS_DIR / "mode_1" / "weights.json").read_text(encoding="utf-8"))["weights"]
        w, _, p = tune_mode_2(strips, evaluator, mode_weights[1])
        _print_result(2, p, w, strips)
        _write_weights(2, w, p)
        mode_weights[2] = w

    if 5 in modes_to_run:
        if 2 not in mode_weights:
            mode_weights[2] = json.loads((WEIGHTS_DIR / "mode_2" / "weights.json").read_text(encoding="utf-8"))["weights"]
        w, _, p = tune_mode_5(strips, evaluator, mode_weights[2])
        _print_result(5, p, w, strips)
        _write_weights(5, w, p)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", type=str, default="1")
    args = parser.parse_args()
    modes = tuple(int(m) for m in args.modes.split(","))
    main(modes_to_run=modes)
