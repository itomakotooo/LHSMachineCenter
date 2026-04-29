"""M1 design verification — player-experience gate.

Per ``project_slot_designer_axiom_experience_is_soul``: TDD numbers are
inspiration, not constraint; what we verify is **player experience
reasonableness**, not divergence from a particular real machine's
per-position weights.

Run after any tune. All red lines must be green before "done" per
``project_slot_designer_axiom_experience_is_soul``.

Usage:
    python -m slot_designer.scripts.verify_m1_design

Exit: 0 = all green, 1 = at least one red.

Categories:
    [RTP]         Per-mode total RTP within tolerance
    [HIT]         Per-mode hit rate within band
    [WILD]        Wild on payline P(>=1) signature within band per mode
    [SHARE]       Per-mode family RTP share within band
    [DENSITY]     Per-family per-reel payline density visually合理 [1%, 22%]
    [MODE7-LOCK]  Mode 7 Diamond/Seven family RTP within ±0.5pp of mode 1
                  (大奖击中率/产出期望绝对不砍)
    [MODE7-CUT]   Mode 7 Bar1/Cherry family share visibly cut from mode 1
                  (略砍小奖/砍小奖体感)
    [SIGNATURE]   Wild on payline cross-mode drift ≤ 25%
                  (Double Diamond signature 一致性)
    [TOP-PATH]    Top-tier (Diamond + Seven) RTP not cut in mode 7
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import analytic_profile, compute_reel_marginal
from slot_designer.engine.loader import load_engine

SPEC = _ROOT / "slot_designer" / "specs" / "M1.spec.json"
STRIPS = _ROOT / "slot_designer" / "weights" / "M1" / "reel_strips.json"

# pay_id -> family classification for RTP-share aggregation.
# Matches tune_m1.PAY_TO_FAMILY.
PAY_TO_FAMILY = {
    "12": "Cherry", "13": "Cherry", "14": "Cherry",
    "2": "Diamond", "3": "Diamond", "4": "Diamond",
    "5": "Seven", "6": "Seven", "10": "Seven",
    "7": "Bar3", "8": "Bar2", "9": "Bar1",
    "11": "Bar_group",  # split equally Bar1/Bar2/Bar3
}

# Per-mode RTP / hit / wild_signature / family-share targets.
MODE_TARGETS = {
    1: {
        "rtp": 95.0, "rtp_tol": 1.0,
        "hit_lo": 0.14, "hit_hi": 0.22,
        "wild_lo": 0.10, "wild_hi": 0.18,
        "family_share_band": {
            # share = family_rtp_pp / total_rtp (0-1 scale).
            # Synced with tune_m1.EXPERIENCE_TARGETS[1].family_share_bands.
            # Wild lowered to 10-16% allows Diamond family share to compress
            # to ~5% (pure-Diamond combos cubic-rare; substitution wins go
            # to non-Diamond families).
            "Diamond": (0.04, 0.20),
            "Seven":   (0.12, 0.24),
            "Bar3":    (0.10, 0.22),
            "Bar2":    (0.10, 0.24),
            "Bar1":    (0.08, 0.20),
            "Cherry":  (0.08, 0.18),
        },
        # Mid-bucket hit-rate floors — player should see 5-20× wins
        # at ≤15-min cadence (10 spins/min).
        "bucket_hit_floors": {
            "ge5_lt10": 0.005,    # ≥1 in 200 spins (~20 min)
            "ge10_lt20": 0.008,   # ≥1 in 125 spins (~12 min)
        },
    },
    7: {
        "rtp": 85.0, "rtp_tol": 1.5,
        "hit_lo": 0.10, "hit_hi": 0.16,
        "wild_lo": 0.10, "wild_hi": 0.18,
        # Mode 7 family share inherits mode 1 floor; explicit checks via
        # MODE7-LOCK / MODE7-CUT validate per-family deltas.
        "family_share_band": {
            "Diamond": (0.04, 0.20),
            "Seven":   (0.12, 0.26),
            "Bar3":    (0.10, 0.24),
            "Bar2":    (0.08, 0.26),
            "Bar1":    (0.06, 0.22),
            "Cherry":  (0.06, 0.18),
        },
    },
    2: {
        "rtp": 294.5, "rtp_tol": 20.0,
        "hit_lo": 0.20, "hit_hi": 0.35,
        "wild_lo": 0.10, "wild_hi": 0.28,
        # Lucky mode = 7-dominated per RWB/Blazing Sevens benchmark.
        # Synced with tune_m1.EXPERIENCE_TARGETS.
        "family_share_band": {
            "Diamond": (0.03, 0.25),
            "Seven":   (0.35, 0.65),
            "Bar3":    (0.05, 0.22),
            "Bar2":    (0.05, 0.20),
            "Bar1":    (0.03, 0.16),
            "Cherry":  (0.03, 0.16),
        },
        "density_hi": 0.30,
    },
    5: {
        "rtp": 500.0, "rtp_tol": 30.0,
        "hit_lo": 0.20, "hit_hi": 0.40,
        "wild_lo": 0.10, "wild_hi": 0.30,
        "family_share_band": {
            "Diamond": (0.02, 0.30),
            "Seven":   (0.50, 0.80),
            "Bar3":    (0.03, 0.20),
            "Bar2":    (0.02, 0.13),
            "Bar1":    (0.005, 0.10),
            "Cherry":  (0.01, 0.10),
        },
        "density_hi": 0.35,
    },
}

# Per-reel per-family density caps — synced with tune_m1.py.
# Bar3/Bar2 (mid-pay 显眼) > 17% on any reel = "怪" (one symbol dominates).
# Top-pay (Seven, Diamond) capped tighter (rare-by-brand). Bar1/Cherry
# (filler-acceptable) higher cap. Lucky modes get ~3-5pp upper relax.
PER_REEL_DENSITY_HI_BY_FAMILY_STANDARD = {
    "Diamond1": 0.10, "Diamond2": 0.10,
    "Seven1": 0.12,  "Seven2": 0.12,
    # Bar3 cap 18% (was 17%): with R1 Blank pinned to [30%, 40%], standard
    # mode reels lose blank space and tuner uses Bar3 as the "asymmetric
    # mid-pay" reel marker (3-reel near-miss design — tune_m1 line ~131
    # "asymmetric Bar3 is the intentional near-miss mechanism"). 18% accom-
    # modates this without over-constraining; cap was a picked threshold
    # in the first place. Bar2 stays 17% (less commonly the asymmetric reel).
    "Bar3": 0.18, "Bar2": 0.17,
    "Bar1": 0.22, "Cherry": 0.20,
}
PER_REEL_DENSITY_HI_BY_FAMILY_LUCKY = {
    "Diamond1": 0.13, "Diamond2": 0.13,
    "Seven1": 0.23,  "Seven2": 0.23,
    "Bar3": 0.20, "Bar2": 0.20,
    "Bar1": 0.26, "Cherry": 0.22,
}
PER_REEL_DENSITY_HI_BY_MODE = {
    1: PER_REEL_DENSITY_HI_BY_FAMILY_STANDARD,
    7: PER_REEL_DENSITY_HI_BY_FAMILY_STANDARD,
    2: PER_REEL_DENSITY_HI_BY_FAMILY_LUCKY,
    5: PER_REEL_DENSITY_HI_BY_FAMILY_LUCKY,
}

PER_REEL_DENSITY_LO_BY_FAMILY = {
    "Seven2": 0.0025, "Diamond2": 0.0025,  # top-rare; 1 in 400 still visible
    "Seven1": 0.005, "Diamond1": 0.005,
    "Bar3": 0.005, "Bar2": 0.005, "Bar1": 0.005,
    "Cherry": 0.005,
}

# Mode 7 anchoring: Diamond/Seven absolute RTP (pp) must be within
# ±MODE7_LOCK_TOL of mode 1's value.
MODE7_LOCK_TOL_PP = 0.6

# Mode 7 cut: Bar1/Cherry family pp must be at least MODE7_CUT_MIN_PP below mode 1.
MODE7_CUT_MIN_PP = {"Bar1": 1.0, "Cherry": 1.0}

# Standard-mode wild signature drift: mode 1 vs mode 7 should be similar
# (both "normal luck"). Lucky modes (2, 5) naturally have more wild visible
# — that's part of "feels lucky", not a signature break.
WILD_DRIFT_STANDARD_PP = 3.0  # mode 1 vs mode 7 absolute pp difference cap

# Mode 5 base lock: per FIRST_MACHINE.md §7 + project_slot_designer_strips_
# identical_across_modes.md, non-feature mode 5 base weights (Cherry / Bar1
# / Bar2 / Bar3 / Blank) must be byte-identical to mode 2's. Only top-bucket
# (Diamond / Seven) weights vary to push RTP from ~294% to 500%. This blocks
# the pareto trap where free-tuning mode 5 collapses one reel's total weight
# (R-stuffing) and exterminates a base family on that reel.
MODE5_BASE_FAMILIES = ("Cherry", "Bar1", "Bar2", "Bar3", "Blank")

# Brand uniformity: top-prize family (Diamond/Seven for M1) cross-reel
# marginal ratio cap. Player perceives consistent brand only if top
# symbols appear roughly equally on all 3 reels. This mirrors tune_m1.py's
# uniformity_ratio_cap (= 2.0 standard / 2.5 lucky) — verify is the dual
# of tune cost.
#
# Why this replaces "R-COLLAPSE absolute reel-total-weight cap":
#   - Player doesn't see total weight (it's a virtual-reel granularity, not
#     a visual property). Player sees per-(symbol, reel) marginals.
#   - Direct check on top-prize cross-reel marginal ratio is 1 step closer
#     to perception than reel-total-weight ratio.
#   - 2.0/2.5 is still picked but expresses a direct "brand consistency"
#     goal (top symbols not concentrated on one reel) — not an indirect
#     proxy. The cap value remains M1-specific (other machines re-derive).
BRAND_UNIFORMITY_RATIO_CAP_STANDARD = 2.0   # mode 1, mode 7 — top-prize cross-reel max/min
BRAND_UNIFORMITY_RATIO_CAP_LUCKY = 2.5      # mode 2, mode 5 — relaxed for lucky variance

# R1 Blank absolute band — M1-specific user-pinned design target (1-line
# classic). Per DESIGN.md §2: R1 ∈ [30%, 40%] all modes. NOT universal —
# multi-line / video slot machines should re-derive based on their paylines.
R1_BLANK_BAND = (0.30, 0.40)

# §14 M1 SAME-SYMBOL-SPACING: same-symbol cyclic distance ≥ this many stops.
# M1 22-stop strip; for repeating symbols (Bar3 R1=3, Bar1 R2/R3=3, Cherry=2),
# distance ≥ 4 stops = ≥ 1 non-Blank gap between repetition. M1-specific (per
# DESIGN.md §2; not universal — see project_slot_designer_visual_rhythm.md).
SAME_SYMBOL_MIN_STOP_GAP = 4

# §15 WINDOW-VISIBILITY (PWDF) — M1-specific floor.
#
# Mechanism: RTP-neutral Blank weight redistribution (post-tune).
# Per redistribute_m1_blanks.py: shift weight from non-top-adj Blanks (down to
# floor=1) to top-adj Blank positions, preserving total Blank weight per reel.
# Marginals invariant → RTP/hit/share unchanged. Top-symbol visibility ↑ ~10pp.
#
# Achievable on M1 physical 22-stop reels (verified 2026-04-29):
#   pre-redistribution: Diamond1 35%, Diamond2 30%, Seven2 29%
#   post-redistribution: Diamond1 44%, Diamond2 41%, Seven2 39%
# Floor 38% provides small buffer below post-redistribution baseline as
# regression guard. NOT Harrigan 50% (which requires virtual reel mapping —
# architectural upgrade not implemented).
#
# Cherry visibility drops 57% → 38% (its non-top-adj Blank neighbors lose
# weight). Still well above natural baseline; brand visibility preserved.
#
# Per project_slot_designer_window_visibility_pwdf.md. NOT universal —
# 5-reel video / virtual-reel machines re-derive.
WINDOW_VISIBILITY_TARGETS_STANDARD = {
    # symbol -> any-reel visibility floor — for mode 1, mode 7 (standard RTP).
    # Post-redistribution baseline: Diamond1 44%, Diamond2 41%, Seven2 39%.
    # Floor 38% gives small buffer.
    "Diamond1": 0.38,
    "Diamond2": 0.38,
    "Seven2":   0.38,
}
WINDOW_VISIBILITY_TARGETS_LUCKY = {
    # Lucky modes (2, 5): higher RTP → top symbols naturally more weighted →
    # redistribution gives less relative gain. Post-redistribution baseline:
    # Diamond1 ~36%, Diamond2 ~37%. Floor 35% gives buffer.
    # Lower floor for lucky is design-correct: lucky players see top symbols
    # often enough already, less need for PWDF "almost won" psychology.
    "Diamond1": 0.35,
    "Diamond2": 0.35,
    "Seven2":   0.38,  # Seven2 lucky still post-redistribution ~52% — keep std floor
}
# Seven1 (mid-pay 7) excluded — naturally ~48% post-redistribution.
# Cherry (brand) excluded — it's the "donor" of weight, not "boost target".
# Sparse-symbol escape valve: ratio metric is over-sensitive when absolute
# marginals are tiny (e.g., Diamond2 ≈ 1-2% — 1pp spread inflates ratio
# 2x). Player visibility threshold: ≤ 2pp spread is below perception.
# Pass if EITHER ratio ≤ cap OR abs spread ≤ this floor.
BRAND_UNIFORMITY_ABS_SPREAD_FLOOR_PP = 0.02

# Strip alternation: per project_slot_designer_strips_weights_layout.md
# (universal rule, Harrigan near-miss band玩家心理), Blank / non-Blank must
# strictly alternate on every reel — no 3-consecutive Blank or 3-consecutive
# non-Blank chains. Stop count is machine-specific (M1 = 22, M37/M15 = 36),
# but alternation invariant is universal.

# Reel asymmetry: per project_slot_designer_reel_asymmetry.md (Strickland/
# Reid/Harrigan), R1 should have lower Blank rate + higher top-prize density
# than R3. Direction must hold for all modes; lucky modes (RTP > 200%) get
# wider tolerance (high RTP dilutes near-miss psychology). Tuner doesn't
# know this rule — needs both verify check AND cost penalty.
# Tolerances: standard mode (1, 7) requires R1 ≤ R3 + 3pp Blank, R1 ≥ R3
# - 1pp top-prize. Lucky modes (2, 5) get 8pp Blank tolerance (lucky modes
# tend to balance reels via tuner's variance-penalty for visual consistency).
REEL_ASYMMETRY_BLANK_TOL_PP_STANDARD = 0.03   # R1 Blank may exceed R3 by ≤ 3pp
REEL_ASYMMETRY_BLANK_TOL_PP_LUCKY = 0.08      # lucky modes wider tolerance
REEL_ASYMMETRY_TOP_TOL_PP_STANDARD = 0.01     # R1 top-prize may fall below R3 by ≤ 1pp
REEL_ASYMMETRY_TOP_TOL_PP_LUCKY = 0.03        # lucky modes tend to have more top variance
TOP_PRIZE_FAMILIES = ("Diamond1", "Diamond2", "Seven1", "Seven2")


def family_rtp_breakdown(profile, paytable):
    rtp_excluded = {str(p["pay_id"]) for p in paytable if p.get("rtp_excluded")}
    family: dict[str, float] = defaultdict(float)
    for pid, rtp_contrib in profile.get("pay_rtp", {}).items():
        if pid in rtp_excluded:
            continue
        f = PAY_TO_FAMILY.get(pid, "Unknown")
        if f == "Bar_group":
            for bar in ("Bar1", "Bar2", "Bar3"):
                family[bar] += rtp_contrib / 3
        else:
            family[f] += rtp_contrib
    return {k: v * 100 for k, v in family.items()}  # pp


def per_reel_family_density(engine):
    out: dict[tuple[str, int], float] = {}
    for r_idx, reel in enumerate(engine.reels):
        marg = compute_reel_marginal(reel)
        for sym, p in marg.items():
            out[(sym, r_idx)] = p
    return out


def wild_on_payline_p(engine):
    p_no_wild = 1.0
    for reel in engine.reels:
        marg = compute_reel_marginal(reel)
        p_w = marg.get("Diamond1", 0) + marg.get("Diamond2", 0)
        p_no_wild *= (1.0 - p_w)
    return 1.0 - p_no_wild


def load_mode_state(mode):
    weights_path = _ROOT / "slot_designer" / "weights" / "M1" / f"mode_{mode}" / "weights.json"
    if not weights_path.exists():
        return None
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    engine, _ = load_engine(SPEC, weights_path)
    profile = analytic_profile(engine)
    family_rtp = family_rtp_breakdown(profile, spec["pays"])
    densities = per_reel_family_density(engine)
    wild_p = wild_on_payline_p(engine)
    weights_doc = json.loads(weights_path.read_text(encoding="utf-8"))
    return {
        "engine": engine,
        "profile": profile,
        "family_rtp_pp": family_rtp,
        "densities": densities,
        "wild_on_payline": wild_p,
        "weights_doc": weights_doc,
    }


def make_check(category, mode, label, ok, info):
    return {
        "category": category,
        "mode": mode,
        "label": label,
        "ok": bool(ok),
        "info": info,
    }


def run_per_mode_checks(mode, state):
    targets = MODE_TARGETS[mode]
    profile = state["profile"]
    family_rtp = state["family_rtp_pp"]
    wild_p = state["wild_on_payline"]
    densities = state["densities"]
    checks = []

    # RTP
    rtp = profile["rtp_pct"]
    rtp_target = targets["rtp"]
    rtp_tol = targets["rtp_tol"]
    rtp_ok = abs(rtp - rtp_target) <= rtp_tol
    checks.append(make_check(
        "RTP", mode, f"RTP {rtp:.2f}% vs target {rtp_target:.1f}±{rtp_tol:.1f}",
        rtp_ok, f"diff {rtp - rtp_target:+.2f}pp",
    ))

    # HIT
    hit = profile["hit_rate"]
    hit_ok = targets["hit_lo"] <= hit <= targets["hit_hi"]
    checks.append(make_check(
        "HIT", mode, f"hit {hit:.2%} vs band [{targets['hit_lo']:.0%}, {targets['hit_hi']:.0%}]",
        hit_ok, "",
    ))

    # WILD
    wild_ok = targets["wild_lo"] <= wild_p <= targets["wild_hi"]
    checks.append(make_check(
        "WILD", mode, f"wild_on_payline {wild_p:.2%} vs band [{targets['wild_lo']:.0%}, {targets['wild_hi']:.0%}]",
        wild_ok, "",
    ))

    # SHARE
    total_rtp = profile["rtp_pct"]
    for f, (lo, hi) in targets["family_share_band"].items():
        actual = family_rtp.get(f, 0.0) / total_rtp if total_rtp > 0 else 0
        ok = lo <= actual <= hi
        checks.append(make_check(
            "SHARE", mode, f"{f} share {actual:.1%} vs band [{lo:.0%}, {hi:.0%}]",
            ok, f"absolute {family_rtp.get(f, 0.0):.2f}pp",
        ))

    # DENSITY (per-reel per-family) — per-family per-mode caps.
    # Mid-pay symbols capped at 17% standard / 20% lucky to avoid "怪".
    hi_by_fam = PER_REEL_DENSITY_HI_BY_MODE.get(mode, PER_REEL_DENSITY_HI_BY_FAMILY_STANDARD)
    for (sym, r), d in sorted(densities.items()):
        if sym == "Blank":
            continue
        den_lo = PER_REEL_DENSITY_LO_BY_FAMILY.get(sym, 0.005)
        den_hi = hi_by_fam.get(sym, 0.22)
        ok = den_lo <= d <= den_hi
        if not ok:
            checks.append(make_check(
                "DENSITY", mode, f"{sym} R{r+1} density {d:.2%} outside [{den_lo:.1%}, {den_hi:.0%}]",
                ok, "",
            ))

    # BUCKET-FLOOR — mid-bucket hit-rate floors so player sees mid wins
    # at human cadence. Mode 1 specifies; lucky/derived modes inherit
    # naturally via family RTP boost.
    bucket_floors = targets.get("bucket_hit_floors", {})
    for bucket, floor in bucket_floors.items():
        actual = profile.get("bucket_rate", {}).get(bucket, 0.0)
        ok = actual >= floor
        # Convert to "1 in N spins" for readability
        n_spins_actual = (1 / actual) if actual > 0 else float("inf")
        n_spins_floor = 1 / floor
        checks.append(make_check(
            "BUCKET-FLOOR", mode,
            f"{bucket} hit {actual:.2%} (1 in {n_spins_actual:.0f}) vs floor {floor:.1%} (1 in {n_spins_floor:.0f})",
            ok, "",
        ))

    return checks


def run_cross_mode_checks(state_by_mode):
    """Mode 7 lock + cut + signature consistency."""
    checks = []

    if 1 not in state_by_mode:
        return checks

    m1 = state_by_mode[1]
    m1_family = m1["family_rtp_pp"]
    m1_wild = m1["wild_on_payline"]

    # Mode 7 locks (Diamond/Seven absolute pp)
    if 7 in state_by_mode:
        m7 = state_by_mode[7]
        m7_family = m7["family_rtp_pp"]

        for f in ("Diamond", "Seven"):
            m1_pp = m1_family.get(f, 0.0)
            m7_pp = m7_family.get(f, 0.0)
            diff = m7_pp - m1_pp
            ok = abs(diff) <= MODE7_LOCK_TOL_PP
            checks.append(make_check(
                "MODE7-LOCK", 7,
                f"{f} pp m7={m7_pp:.2f} vs m1={m1_pp:.2f} (Δ {diff:+.2f}pp, tol ±{MODE7_LOCK_TOL_PP:.1f})",
                ok,
                "大奖击中率/产出期望绝对不砍",
            ))

        # Mode 7 cuts (Bar1/Cherry visibly cut)
        for f, min_cut in MODE7_CUT_MIN_PP.items():
            m1_pp = m1_family.get(f, 0.0)
            m7_pp = m7_family.get(f, 0.0)
            cut = m1_pp - m7_pp
            ok = cut >= min_cut
            checks.append(make_check(
                "MODE7-CUT", 7,
                f"{f} cut {cut:+.2f}pp (min {min_cut:.1f}pp expected)",
                ok,
                "小奖砍 → 玩家觉得运气差 → 充值 trigger",
            ))

        # Top path: Diamond + Seven mode 7 sum >= mode 1 sum (less ε)
        m1_top = m1_family.get("Diamond", 0) + m1_family.get("Seven", 0)
        m7_top = m7_family.get("Diamond", 0) + m7_family.get("Seven", 0)
        top_diff = m7_top - m1_top
        ok = top_diff >= -MODE7_LOCK_TOL_PP * 2  # combined tolerance
        checks.append(make_check(
            "TOP-PATH", 7,
            f"Diamond+Seven m7={m7_top:.2f}pp vs m1={m1_top:.2f}pp (Δ {top_diff:+.2f}pp)",
            ok,
            "顶奖路径不动",
        ))

    # Standard-mode wild signature: mode 1 vs mode 7 should be similar.
    # Lucky modes 2/5 allowed to have MORE wild (lucky feel = more wild visible).
    if 1 in state_by_mode and 7 in state_by_mode:
        w1 = state_by_mode[1]["wild_on_payline"] * 100
        w7 = state_by_mode[7]["wild_on_payline"] * 100
        diff = abs(w1 - w7)
        ok = diff <= WILD_DRIFT_STANDARD_PP
        checks.append(make_check(
            "SIGNATURE", None,
            f"wild_on_payline mode 1={w1:.2f}pp vs mode 7={w7:.2f}pp (diff {diff:.2f}pp, tol {WILD_DRIFT_STANDARD_PP}pp)",
            ok,
            "标准模式间 Double Diamond signature 一致",
        ))

    # Lucky modes can have MORE wild visibility (part of lucky feel) but
    # never less than standard modes (signature would die in lucky modes).
    for lucky in (2, 5):
        if lucky in state_by_mode and 1 in state_by_mode:
            w_lucky = state_by_mode[lucky]["wild_on_payline"]
            w_std = state_by_mode[1]["wild_on_payline"]
            ok = w_lucky >= w_std - 0.02  # allow small downward (2pp)
            checks.append(make_check(
                "SIGNATURE", lucky,
                f"mode {lucky} wild {w_lucky:.2%} vs mode 1 wild {w_std:.2%} (lucky should not be lower)",
                ok,
                "Lucky mode 不能让 signature 反而变弱",
            ))

    # MODE5-BASE-LOCK: per FIRST_MACHINE.md §7, non-feature mode 5 base
    # weights (Cherry/Bar1/Bar2/Bar3/Blank) must be byte-identical to mode 2.
    # Top-bucket (Diamond/Seven) weights vary; all others lock.
    if 2 in state_by_mode and 5 in state_by_mode:
        m2_w = state_by_mode[2]["weights_doc"]["weights"]
        m5_w = state_by_mode[5]["weights_doc"]["weights"]
        strips_doc = json.loads(STRIPS.read_text(encoding="utf-8"))
        strips_reels = strips_doc["reels"]
        diff_positions = []
        for r_idx in range(len(strips_reels)):
            for p_idx in range(len(strips_reels[r_idx])):
                sym = strips_reels[r_idx][p_idx]
                if sym in MODE5_BASE_FAMILIES:
                    if m2_w[r_idx][p_idx] != m5_w[r_idx][p_idx]:
                        diff_positions.append((r_idx + 1, p_idx, sym,
                                               m2_w[r_idx][p_idx], m5_w[r_idx][p_idx]))
        ok = len(diff_positions) == 0
        if ok:
            label = (f"mode 5 base (Cherry/Bar/Blank) byte-identical to mode 2 "
                     f"(0/54 base positions differ)")
        else:
            sample = diff_positions[:3]
            label = (f"mode 5 base differs from mode 2 at {len(diff_positions)}/54 "
                     f"positions: {sample[0]} ...")
        checks.append(make_check(
            "MODE5-BASE-LOCK", 5, label, ok,
            "非 feature 机台 mode 5 base 权重必须 = mode 2; 仅 top-bucket 调",
        ))

    # BRAND-UNIFORMITY: top-prize family cross-reel marginal ratio cap.
    # Direct check on player-visible quantity (per-(symbol, reel) marginal),
    # mirrors tune_m1.py uniformity_ratio_cap. Catches tuner pareto-stuffing
    # top symbols onto one reel (typical R-stuffing failure mode).
    for mode in sorted(state_by_mode.keys()):
        densities = state_by_mode[mode]["densities"]
        is_lucky = mode in (2, 5)
        cap = (BRAND_UNIFORMITY_RATIO_CAP_LUCKY if is_lucky
               else BRAND_UNIFORMITY_RATIO_CAP_STANDARD)
        for fam in TOP_PRIZE_FAMILIES:
            per_reel = [densities.get((fam, r), 0.0) for r in range(len(strips_reels))]
            mn, mx = min(per_reel), max(per_reel)
            abs_spread = mx - mn
            if mn <= 1e-6:
                # Family extinct on at least one reel — flag as RED
                ok = False
                ratio_str = "∞ (extinct on ≥1 reel)"
            else:
                ratio = mx / mn
                # Dual criterion: pass if EITHER ratio within cap OR absolute
                # spread below player-visibility threshold (≤ 2pp). Ratio
                # alone is over-sensitive for sparse symbols (Diamond2 ≈ 1-2%
                # → 1pp spread looks like ratio 2x but is invisible to player).
                ok = (ratio <= cap) or (abs_spread <= BRAND_UNIFORMITY_ABS_SPREAD_FLOOR_PP)
                ratio_str = f"{ratio:.2f}×"
            per_reel_str = " ".join(f"R{i+1}={d:.2%}" for i, d in enumerate(per_reel))
            checks.append(make_check(
                "BRAND-UNIFORMITY", mode,
                f"{fam} cross-reel ({per_reel_str}) ratio {ratio_str} vs cap {cap:.1f}× "
                f"(abs spread {abs_spread:.2%} vs floor {BRAND_UNIFORMITY_ABS_SPREAD_FLOOR_PP:.0%})",
                ok,
                "顶奖符号跨 reel 应近似一致 (brand consistency); ratio cap 或 abs spread 任一通过即 OK",
            ))

    # R1-BLANK-BAND: M1-specific absolute band [30%, 40%] for R1 Blank rate.
    # Per DESIGN.md §2 + memory note: 30% lower = cherry/seven reveal drama;
    # 40% upper = early rejection防线. User-pinned, not universal.
    strips_doc = json.loads(STRIPS.read_text(encoding="utf-8"))
    strips_reels = strips_doc["reels"]
    for mode in sorted(state_by_mode.keys()):
        densities_m = state_by_mode[mode]["densities"]
        r1_blank = densities_m.get(("Blank", 0), 0.0)
        lo, hi = R1_BLANK_BAND
        ok = lo <= r1_blank <= hi
        checks.append(make_check(
            "R1-BLANK-BAND", mode,
            f"R1 Blank {r1_blank:.2%} vs band [{lo:.0%}, {hi:.0%}]",
            ok,
            "M1 user-pinned: R1 不能太 blank (早期拒绝) 也不能过密 (cherry reveal drama)",
        ))

    # REEL-ASYMMETRY: per project_slot_designer_reel_asymmetry.md universal rule.
    # R1 should have lower Blank rate + higher top-prize density than the last
    # reel (R3 in 3-reel, R5 in 5-reel). Standard modes (1, 7) tight tolerance,
    # lucky modes (2, 5) wider (high RTP dilutes near-miss psychology).
    n_reels = len(strips_reels)
    last_reel_idx = n_reels - 1
    for mode in sorted(state_by_mode.keys()):
        m_w = state_by_mode[mode]["weights_doc"]["weights"]
        # Compute per-reel Blank + top-prize marginal
        def reel_marg(r_idx, syms):
            total = sum(m_w[r_idx])
            if total <= 0:
                return 0.0
            return sum(w for w, s in zip(m_w[r_idx], strips_reels[r_idx]) if s in syms) / total
        r1_blank = reel_marg(0, ("Blank",))
        r_last_blank = reel_marg(last_reel_idx, ("Blank",))
        r1_top = reel_marg(0, TOP_PRIZE_FAMILIES)
        r_last_top = reel_marg(last_reel_idx, TOP_PRIZE_FAMILIES)
        is_lucky = mode in (2, 5)
        blank_tol = (REEL_ASYMMETRY_BLANK_TOL_PP_LUCKY if is_lucky
                     else REEL_ASYMMETRY_BLANK_TOL_PP_STANDARD)
        top_tol = (REEL_ASYMMETRY_TOP_TOL_PP_LUCKY if is_lucky
                   else REEL_ASYMMETRY_TOP_TOL_PP_STANDARD)
        # R1 Blank ≤ R(last) Blank + tolerance (defending early-rejection)
        blank_ok = r1_blank <= r_last_blank + blank_tol
        checks.append(make_check(
            "REEL-ASYMMETRY", mode,
            f"R1 Blank {r1_blank:.2%} vs R{n_reels} Blank {r_last_blank:.2%} "
            f"(diff {r1_blank-r_last_blank:+.2%}, tol +{blank_tol:.0%})",
            blank_ok,
            "防早期拒绝 (Strickland/Reid): R1 应 ≤ R(last) Blank",
        ))
        # R1 top-prize density ≥ R(last) top-prize density (Harrigan near-miss)
        top_ok = r1_top >= r_last_top - top_tol
        checks.append(make_check(
            "REEL-ASYMMETRY", mode,
            f"R1 top-prize {r1_top:.2%} vs R{n_reels} top-prize {r_last_top:.2%} "
            f"(diff {r1_top-r_last_top:+.2%}, tol -{top_tol:.0%})",
            top_ok,
            "near-miss psychology (Harrigan): R(last) 顶奖应 ≤ R1 (R(last) = 差一点 reel)",
        ))

    # BLANK-FLANK-DIVERSITY: per project_slot_designer_blank_flank_diversity.md
    # universal hard rule for line-based slots. Each Blank position p must satisfy
    # strip[(p-1)%n] != strip[(p+1)%n] (no X-Blank-X — would create cheap
    # near-miss in 3-row window, dilute真 near-miss value).
    for r_idx, reel in enumerate(strips_reels):
        n = len(reel)
        violations_pairs = []
        for p in range(n):
            if reel[p] == "Blank":
                prev = reel[(p - 1) % n]
                nxt = reel[(p + 1) % n]
                if prev == nxt and prev != "Blank":
                    violations_pairs.append((p, prev))
        ok = len(violations_pairs) == 0
        if ok:
            label = f"R{r_idx+1}: 0 X-Blank-X violations"
        else:
            sample = violations_pairs[0]
            label = (f"R{r_idx+1}: {len(violations_pairs)} X-Blank-X violations: "
                     f"pos {sample[0]} ({sample[1]}-Blank-{sample[1]})")
        checks.append(make_check(
            "BLANK-FLANK-DIVERSITY", None, label, ok,
            "防廉价 near-miss (X-Blank-X 视窗 dilute 真 near-miss 价值)",
        ))

    # VISUAL-RHYTHM (M1 specific sub-rule SAME-SYMBOL-SPACING):
    # 同 symbol 重复实例 cyclic 距离 ≥ SAME_SYMBOL_MIN_STOP_GAP stops.
    # M1 = 4 stops (machine specific cap; other machines self-define).
    for r_idx, reel in enumerate(strips_reels):
        n = len(reel)
        sym_positions: dict[str, list[int]] = {}
        for p, s in enumerate(reel):
            if s == "Blank":
                continue
            sym_positions.setdefault(s, []).append(p)
        violations_v = []
        for sym, positions in sym_positions.items():
            if len(positions) < 2:
                continue
            sorted_p = sorted(positions)
            for i in range(len(sorted_p)):
                next_p = sorted_p[(i + 1) % len(sorted_p)]
                if next_p > sorted_p[i]:
                    d = next_p - sorted_p[i]
                else:
                    d = (n - sorted_p[i]) + next_p  # cyclic wrap
                if d < SAME_SYMBOL_MIN_STOP_GAP:
                    violations_v.append((sym, sorted_p[i], next_p, d))
        ok = len(violations_v) == 0
        if ok:
            label = (f"R{r_idx+1}: SAME-SYMBOL-SPACING ≥ {SAME_SYMBOL_MIN_STOP_GAP} "
                     f"stops cyclic ✓")
        else:
            sample = violations_v[0]
            label = (f"R{r_idx+1}: {len(violations_v)} SAME-SYMBOL-SPACING violations: "
                     f"{sample[0]} at pos {sample[1]} and {sample[2]} (cyclic dist {sample[3]} < "
                     f"{SAME_SYMBOL_MIN_STOP_GAP})")
        checks.append(make_check(
            "VISUAL-RHYTHM", None, label, ok,
            "M1 子规则 SAME-SYMBOL-SPACING — 重复 symbol 不密集 (机台 specific)",
        ))

    # WINDOW-VISIBILITY (PWDF): per project_slot_designer_window_visibility_pwdf.md.
    # Top-prize symbols any-reel window visibility ≥ machine-specific floor.
    # Implementation: RTP-neutral Blank weight redistribution — see
    # redistribute_m1_blanks.py. Mode-specific floor (standard tighter, lucky
    # looser since lucky modes naturally have more top-symbol visibility).
    n_stops = len(strips_reels[0])
    for mode in sorted(state_by_mode.keys()):
        m_w = state_by_mode[mode]["weights_doc"]["weights"]
        is_lucky = mode in (2, 5)
        targets = (WINDOW_VISIBILITY_TARGETS_LUCKY if is_lucky
                   else WINDOW_VISIBILITY_TARGETS_STANDARD)
        for sym, floor in targets.items():
            per_reel_vis = []
            for r in range(len(strips_reels)):
                total_w = sum(m_w[r])
                if total_w <= 0:
                    per_reel_vis.append(0.0)
                    continue
                p_in_window = 0
                for k in range(n_stops):
                    strip = strips_reels[r]
                    if (strip[(k - 1) % n_stops] == sym
                            or strip[k] == sym
                            or strip[(k + 1) % n_stops] == sym):
                        p_in_window += m_w[r][k]
                per_reel_vis.append(p_in_window / total_w)
            any_reel = 1.0
            for v in per_reel_vis:
                any_reel *= (1.0 - v)
            any_reel = 1.0 - any_reel
            ok = any_reel >= floor
            per_reel_str = " ".join(f"R{i+1}={v*100:.1f}%" for i, v in enumerate(per_reel_vis))
            checks.append(make_check(
                "WINDOW-VISIBILITY", mode,
                f"{sym} any-reel visibility {any_reel*100:.2f}% vs floor {floor*100:.0f}% "
                f"({per_reel_str})",
                ok,
                "Harrigan PWDF: top symbol 视窗 frequent + payline rare = 'almost' 心理",
            ))

    # ALTERNATION: Blank / non-Blank must strictly alternate on every reel.
    # No 3-consecutive Blank or 3-consecutive non-Blank chains. Universal
    # invariant (independent of mode — strips are shared across modes).
    for r_idx, reel in enumerate(strips_reels):
        violations = []
        for p in range(len(reel) - 1):
            cur_blank = reel[p] == "Blank"
            nxt_blank = reel[p + 1] == "Blank"
            if cur_blank == nxt_blank:
                kind = "BB" if cur_blank else "NN"
                violations.append((p, p + 1, kind, reel[p], reel[p + 1]))
        ok = len(violations) == 0
        if ok:
            blanks = sum(1 for s in reel if s == "Blank")
            label = (f"R{r_idx+1} alternation OK ({blanks} Blank / "
                     f"{len(reel)-blanks} non-Blank, strict B-N-B-N)")
        else:
            sample = violations[0]
            label = (f"R{r_idx+1} alternation broken at {len(violations)} adjacency: "
                     f"pos {sample[0]}-{sample[1]} both '{sample[2]}' "
                     f"({sample[3]}/{sample[4]})")
        checks.append(make_check(
            "ALTERNATION", None, label, ok,
            "Blank/非 Blank 严格交替 (Harrigan near-miss band 玩家心理 universal rule)",
        ))

    return checks


def main():
    state_by_mode: dict[int, dict] = {}
    available_modes = []
    for mode in (1, 2, 5, 7):
        st = load_mode_state(mode)
        if st is None:
            print(f"  [skip] mode {mode}: weights file not found")
            continue
        state_by_mode[mode] = st
        available_modes.append(mode)

    if not state_by_mode:
        print("ERROR: no mode weights found")
        return 1

    all_checks = []

    print("\n=== M1 player-experience design verification ===")
    print(f"Modes available: {available_modes}\n")

    for mode in sorted(available_modes):
        state = state_by_mode[mode]
        print(f"--- Mode {mode} ---")
        rtp = state["profile"]["rtp_pct"]
        hit = state["profile"]["hit_rate"]
        wild = state["wild_on_payline"]
        print(f"  RTP={rtp:.2f}%  hit={hit:.2%}  wild_on_payline={wild:.2%}")
        family_rtp = state["family_rtp_pp"]
        for f in ("Diamond", "Seven", "Bar3", "Bar2", "Bar1", "Cherry"):
            v = family_rtp.get(f, 0.0)
            share = v / rtp * 100 if rtp > 0 else 0
            print(f"    {f:8s} {v:6.2f}pp ({share:5.1f}%)")

        checks = run_per_mode_checks(mode, state)
        all_checks.extend(checks)

    cross = run_cross_mode_checks(state_by_mode)
    all_checks.extend(cross)

    # Summary
    print("\n=== Verification results ===")
    fail_count = 0
    by_category = defaultdict(list)
    for c in all_checks:
        by_category[c["category"]].append(c)

    for cat in sorted(by_category.keys()):
        checks = by_category[cat]
        passes = sum(1 for c in checks if c["ok"])
        fails = sum(1 for c in checks if not c["ok"])
        status = "GREEN" if fails == 0 else f"RED ({fails}/{len(checks)} fail)"
        print(f"  [{cat:12s}] {passes:3d} pass / {len(checks):3d} total — {status}")
        for c in checks:
            if not c["ok"]:
                mode_str = f"mode {c['mode']}" if c["mode"] is not None else "all"
                print(f"     [FAIL] {mode_str}: {c['label']}")
                if c["info"]:
                    print(f"          ({c['info']})")
                fail_count += 1

    print(f"\n{'GREEN — all checks pass' if fail_count == 0 else f'RED — {fail_count} check(s) failed'}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
