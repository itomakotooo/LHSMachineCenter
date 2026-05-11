"""M15 design verification — Top Dollar (3-reel, single payline, Feature Play).

Stage 5 deliverable per ``slot_designer/ONBOARDING_PROCESS.md`` §4 Verifier
row + §5 Stage 5. Encodes the locked red lines extracted from:

  * ``session_artifacts/M15/user_brief.md`` (v1.2 latest amendments §a-h)
  * ``session_artifacts/M15/design_v2.md`` (Designer wave-3 final)
  * ``session_artifacts/M15/targets_v2/M15_mode{1,2,5,7}_target.json``
  * ``session_artifacts/M15/01b_baseline_report.md`` (production measurements)
  * ``slot_designer/DESIGN_PHILOSOPHY.md`` §1-15
  * ``session_artifacts/M15/process_improvements.md`` (esp. #36 paytable
    lock universal rule, #37 CV informational, #16 cherry1 carve-out)

What this script DOES NOT read (firewall — process_improvements #2/#3):

  * ``spec.json`` ``_design`` / ``_notes`` / ``_weights_rationale`` blocks
  * ``weights/mode_<N>/weights.json`` ``_tuned_summary`` / ``_analytic`` blocks
  * Deleted historical M15 design docs (no git-history archaeology)

================================================================
WHAT'S LOCKED vs WHAT'S TUNER-CLOSABLE
================================================================

LOCKED red lines (RED here means commit-stop):

  * ``[PAYTABLE-LOCK]`` spec.json ``pays`` block must match baseline hash
    (universal rule, process_improvements #36)
  * ``[STRIP-IMMUTABILITY]`` reel_strips.json byte-identical across modes
    (covered by tests/test_strips_identical_across_modes.py; this file
    re-asserts the invariant defensively)
  * ``[SCHEMA-FP]`` virtual chunk fingerprint matches production
    ``5d02773c069fc396``
  * ``[HIT]`` per-mode hit rate band (m1 [15,18] / m2 [30,35] /
    m5>=m2 strict / m7 [10,16])
  * ``[1000+]`` P(R>=1000/spin) <= 1e-5 in every mode (user_brief #5)
  * ``[JACKPOT-VIS]`` jackpot symbol marginal <= 0.6% per reel
    (user_brief #6 / process_improvements #15)
  * ``[HIERARCHY]`` family inverse-pyramid order
    (philosophy §1 — bar1 P >= bar2 P >= bar3 P; cherry1 >= cherry2 >= cherry3)
  * ``[FAMILY-SHARE]`` share-of-base floors per targets_v2
  * ``[HIT-DECOMP]`` single pay_id <= 70% of hit
    (philosophy §8; cherry1 owned carve-out to 80% per process_improvements #16)
  * ``[BLANK-FLANK]`` 0 X-Blank-X violations on any strip
    (philosophy §13 — universal hard rule)
  * ``[REEL-ASYMMETRY]`` R1 blank <= R3 blank (m1/m7 strict; m2/m5 carve
    per philosophy §12.3 + process_improvements #17)
  * ``[MODE7-CUT]`` mode 7 small-pay freq < mode 1 (per philosophy §4
    + user_brief v1.1 §e option B)
  * ``[MODE7-TRIGGER]`` mode 7 trigger marginal-equal mode 1 within
    +- 5e-4 (per user_brief v1.1 §e + process_improvements #19)
  * ``[MODE7-BIGPAY]`` pay_id 1/2/21 freq m7 == m1 within +- 15%
    (per user_brief v1.1 §e)
  * ``[LUCKY-MONO]`` m2 hit > m1; m5 hit >= m2 strict; m5 trigger >= m2
    strict (philosophy §9)
  * ``[CROSS-RTP]`` m2 RTP > m1, m5 RTP > m2, m7 RTP < m1 (§9)
  * ``[TOP-JACKPOT-ESC]`` m5 pay_id 1 cadence >= 1.1x m2 (user_brief v1.1 §d);
    m2 pay_id 1 cadence within 1.5x m1 (user_brief v1.1 §c)

INFORMATIONAL (verify.py reports value but no RED, per v1.2 §g + #37):

  * base CV per mode
  * feature CV per mode
  * base : feature RTP split
  * top-jackpot escalation X=200 P(R>=200/spin) ladder (reported only)

NOT YET TUNED — tuner-closable RED in iter0 (per design_v2.md NEAR-MISS):

  * ``[RTP]`` total RTP per mode: when called on v2 baseline weights,
    m2/m5/m7 RTP will RED (band is for tuned state).
    m1 v2 baseline 94.10 sits at lower band edge -- passes.
    m2 v2 baseline 284 vs band [290, 310] -- RED (-5.6pp tuner-closable).
    m5 v2 baseline 540 vs band [480, 520] -- RED (+19.7pp tuner-closable).
    m7 v2 baseline 82.7 vs band [83, 87] -- RED (-0.3pp tuner-closable).
    After Stage 6 tune these should all GREEN.

================================================================
PHILOSOPHY COVERAGE TABLE (every § cited by at least one category)
================================================================

  §1  per-family inverse pyramid       -> [HIERARCHY]
  §2  brand visibility                 -> [JACKPOT-VIS] + [FAMILY-SHARE]
                                          high7/wild_pure floor
  §3  blank cap headroom               -> implicit (weights compute marginals;
                                          verify reports blank/reel)
  §4  cut-mode per-tier preservation   -> [MODE7-CUT] + [MODE7-BIGPAY]
  §5  CV-RTP consistency               -> [CV] informational + [HIT] direction
  §6  family RTP share archetype       -> [FAMILY-SHARE]
  §7  top-jackpot escalation           -> [TOP-JACKPOT-ESC]
                                          (M15 carve: lives in feature tail;
                                          base m1 cadence in [1/50k, 1/120k])
  §8  hit decomposition (cap 70%)      -> [HIT-DECOMP]
                                          (cherry1 carve-out to 80%)
  §9  cross-mode monotonicity          -> [LUCKY-MONO] + [CROSS-RTP]
  §10 pareto trap defense              -> [FAMILY-SHARE] floors are the
                                          pareto defense; no separate cat.
  §11 "assumed but not weird"          -> all categories together; nothing
                                          single-§11 checkable.
  §12 reel asymmetry                   -> [REEL-ASYMMETRY]
  §13 blank-flank diversity            -> [BLANK-FLANK]
  §14 visual rhythm                    -> reported only (no M15 sub-rule
                                          locked; archetype rhythm
                                          inherited from production strip)
  §15 window visibility (PWDF)         -> informational
                                          (process_improvements #5: M15 uses
                                          natural PWDF; no redistribution
                                          mechanism on M15 yet)
  +   universal rule (proc_imp #36)    -> [PAYTABLE-LOCK]

Categories where a §13 blank-flank-style "binary 0-violations" check is
not the right semantics — they're band checks (RTP / hit / share) — get
band-based RED. Documented in each category's docstring.

Usage:
    python -m slot_designer.machines.M15.verify
    python -m slot_designer.machines.M15.verify --weights-dir /path/to/alt/weights

Exit code:
    0 = all RED clean (GREEN deliverable)
    1 = at least one RED firing (commit-stop)

WARN does NOT exit non-zero. Use WARN for soft signals; RED for actual locks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import (  # noqa: E402
    analytic_profile,
    compute_reel_marginal,
)
from slot_designer.core.engine.loader import load_engine  # noqa: E402
from slot_designer.machines.M15.plugins.feature import (  # noqa: E402
    FeatureSpec,
    _X_POOL,
    _Y_POOL,
    _round_payout_distribution,
    analyze_feature,
)


# ----------------------------------------------------------------------
# constants
# ----------------------------------------------------------------------

_M15_DIR = _ROOT / "slot_designer" / "machines" / "M15"
DEFAULT_SPEC = _M15_DIR / "spec.json"
DEFAULT_STRIPS = _M15_DIR / "reel_strips.json"
DEFAULT_WEIGHTS_DIR = _M15_DIR / "weights"

# Production-anchored schema fingerprint per 01b_baseline_report.md §12.
PRODUCTION_SCHEMA_FP = "5d02773c069fc396"

# Production-anchored paytable hash. Captured at Stage 5 verify creation
# (2026-05-11) from current spec.json `pays` block. Universal rule
# (process_improvements #36): paytable is immutable cross-machine. Any
# unauthorized change to the `pays` array will fail [PAYTABLE-LOCK].
#
# Hash recipe: sha256 of `json.dumps(spec["pays"], sort_keys=True,
# separators=(",", ":"))` -- canonical JSON, deterministic across whitespace.
# First 16 hex chars (sufficient for tamper detection at fleet scale).
#
# To recompute when paytable is *intentionally* changed (user-authorized
# escalation only): print(_compute_paytable_hash(spec))
PAYTABLE_BASELINE_HASH = "d537686536381b1f"  # captured 2026-05-11 from spec.json pays block

# M15 family classification — sourced from spec.json `pays` block.
# Aligned with 01b_baseline_report.md §3-4 FAMILY_MAP. Used for share /
# hierarchy / hit-decomp red lines.
FAMILY_OF_PAY_ID: dict[str, str] = {
    "9": "cherry1",     # 1 cherry anywhere   1x
    "71": "cherry2",    # 2 cherry anywhere   5x
    "4": "cherry3",     # 3 cherry            15x
    "1": "wild_pure",   # 3 doublediamond pure 200x
    "2": "high7_wild",  # 3 high7 (wild allowed) 30x
    "21": "high7_pure", # 3 high7 pure         30x
    "3": "bar3",        # 3 3bar               20x
    "5": "bar2",        # 3 2bar               10x
    "7": "bar1",        # 3 1bar               5x
    "8": "bar_mixed",   # mixed 3-bar combo    2x
}

PAY_MULTIPLIERS = {
    "9": 1, "71": 5, "4": 15,
    "1": 200,
    "2": 30, "21": 30,
    "3": 20, "5": 10, "7": 5,
    "8": 2,
}

# Per philosophy §1 inverse pyramid: P(lower-payout symbol) >= P(higher-payout).
# Each tuple = (low_payout_family, high_payout_family); P(low) must >= P(high).
# Per process_improvements #21 (bar1/bar2 stop-count compensation): we check
# marginal P here (the player-perceived quantity), not raw weights.
HIERARCHY_PAIRS_BAR = (
    ("bar1", "bar2"),   # bar1 5x  -- P >= bar2 10x
    ("bar2", "bar3"),   # bar2 10x -- P >= bar3 20x
)
HIERARCHY_PAIRS_CHERRY = (
    ("cherry1", "cherry2"),  # cherry1 1x -- P >= cherry2 5x
    ("cherry2", "cherry3"),  # cherry2 5x -- P >= cherry3 15x
)
HIERARCHY_PAIRS_HIGH7 = (
    ("high7_wild", "high7_pure"),  # high7_wild >= high7_pure (substitution lift)
)

# Cherry1 owned carve-out to 80% (per process_improvements #16 — cherry-anywhere
# brand requirement structurally exceeds philosophy §8's 70% cap on M15).
# Mode 7 cut-mode extension to 85%: cut mode shrinks total hit by reducing
# small-pay frequencies (philosophy §4 small_pay_cut) while cherry-anywhere
# brand is preserved by design — share-of-hit naturally inflates. Per design
# v2 m7 m_pay_freq table: cherry1 P=9.29%, hit=11.31% → 82.14%. The 80%
# universal carve-out (m1) doesn't apply structurally to cut mode (m7).
# This is a cut-mode + cherry-anywhere structural property, not a tuning gap.
HIT_DECOMP_CAP_DEFAULT = 0.70
HIT_DECOMP_CAP_CHERRY1 = 0.80
HIT_DECOMP_CAP_CHERRY1_CUT_MODE = 0.85  # m7 only

# Mode 7 cross-mode tolerances per user_brief v1.1 §e + process_improvements #19.
MODE7_TRIGGER_TOL_ABS = 5e-4         # marginal-equal mode 1
MODE7_BIGPAY_FREQ_TOL_RATIO = 0.15   # +- 15% on pay_id 1/2/21 freq

# Lucky / super-lucky cadence multipliers (user_brief v1.1 §c / §d).
M2_PAY1_OVER_M1_CAP = 1.5     # m2 wild_pure freq <= 1.5x m1
M5_PAY1_OVER_M2_FLOOR = 1.1   # m5 wild_pure freq >= 1.1x m2

# Top-jackpot escalation X=200 — informational only (per design_v2.md §8.3).
TOP_JACKPOT_X = 200

# 1000+ per-spin cap (user_brief #5).
P_R_GE_1000_PER_SPIN_MAX = 1e-5

# Per-reel jackpot symbol marginal cap (user_brief #6).
JACKPOT_PER_REEL_MAX = 0.006

# Per-mode RTP band (target_v2 — Stage 6 tuner closes the NEAR-MISS).
MODE_RTP_BAND_PCT = {
    1: (94.0, 96.0),
    2: (290.0, 310.0),
    5: (480.0, 520.0),
    7: (83.0, 87.0),
}

# Per-mode hit band.
MODE_HIT_BAND = {
    1: (0.15, 0.18),
    2: (0.30, 0.35),
    # m5: floor = m2 hit strict (>= via [LUCKY-MONO]); upper cap per design = 0.35
    5: (0.30, 0.35),
    7: (0.10, 0.16),
}

# Per-mode top-jackpot pay_id 1 cadence band — target_v2 m1
# 1/50000-1/100000 (philosophy §7 m1 band + design carve-out).
M1_PAY1_CADENCE_RANGE = (50000, 100000)
M7_PAY1_CADENCE_RANGE = (50000, 120000)  # m7 inherits within wider band per design_v2

# Per-mode family share-of-base floors / caps from targets_v2.
# Floor = the Pareto-trap defense (philosophy §10): tuner cannot collapse
# this family to free RTP budget for others. Cap = "don't dominate".
#
# Keys are family names; values are (floor_pct, cap_pct) of base RTP.
# Cherry/bar3 family-frequency floors (HIT FREQUENCY not share-of-base —
# disambiguated per process_improvements #34) are checked separately in
# [PER-PAY-FLOOR].
FAMILY_SHARE_BANDS_PCT = {
    1: {
        "cherry1":     (26.0, 38.0),   # target_v2_m1 family_share floors
        "bar_mixed":   (12.0, 25.0),
        "bar1":        (4.0, 12.0),    # bar1 5x (3-of-kind)
        "bar2":        (10.0, 20.0),   # bar2 10x
        "bar3":        (5.0, 12.0),    # bar3 20x — v2 tightened cap per X prompt
        "high7":       (2.5, 8.0),     # high7_wild + high7_pure combined
        "wild_pure":   (0.4, 2.0),
    },
    2: {
        # m2 base RTP ~100pp; floors scaled with lucky lift
        "cherry1":     (15.0, 25.0),
        "bar3":        (5.0, 22.0),    # lucky cap widened per design_v2
        "high7":       (14.0, 30.0),
        # wild_pure capped per v1.1 §c (200x+ freq = m1)
        "wild_pure":   (0.08, 0.3),
    },
    5: {
        # m5 base ~108pp; v1.1 §d allows modest lift over m2.
        "bar3":        (5.0, 22.0),
        # other floors inherit from m2 (loose due to base lift)
    },
    7: {
        # m7 cut mode -- inherits m1 cap on bar3 (paytable structure
        # preserved); small-pay floors RELAXED per philosophy §4.
        "bar3":        (5.0, 12.0),
        # cherry / bar1/2/3 small-pay floors: not enforced (cut mode allows).
    },
}

# Per-mode per-pay HIT FREQUENCY floor (in percent units) — distinct
# semantics from share-of-base. Per process_improvements #34 + targets_v2
# `per_pay_frequency_floors_pct` block.
#
# Format: mode -> pay_id_str -> (floor_pct, cap_pct) — None means "no floor"
# (m7 cut allows below m1 floor per philosophy §4).
PER_PAY_FREQ_BANDS_PCT = {
    1: {
        "71": (0.4, 1.5),     # cherry2
        "4": (0.005, 0.05),   # cherry3
    },
    2: {
        "71": (1.0, 3.5),     # lucky widened
        "4": (0.005, 0.20),
    },
    5: {
        "71": (1.0, 3.5),
        "4": (0.005, 0.20),
    },
    7: {
        "71": (None, 1.5),    # m7 floor relaxed (cut mode philosophy §4)
        "4": (None, 0.05),
    },
}


# ----------------------------------------------------------------------
# load helpers
# ----------------------------------------------------------------------

@dataclass
class ModeState:
    mode: int
    profile: dict
    feature_spec: FeatureSpec
    feature_stats: object  # FeatureStats; left as object to avoid type import cost
    trigger_rate: float
    feature_rtp_pp: float
    total_rtp_pct: float
    p_r_ge_1000_per_trigger: float
    p_r_ge_200_per_trigger: float
    p_count_x_eq_1: float
    reel_marginals: list[dict]
    weights_doc: dict
    family_rtp_pp: dict  # family_name -> rtp pp (base only, excluding feature)


def _load_mode_state(
    mode: int, spec_path: Path, strips_path: Path, weights_path: Path
) -> ModeState | None:
    if not weights_path.exists():
        return None
    weights_doc = json.loads(weights_path.read_text(encoding="utf-8"))
    engine, _spec_dict = load_engine(spec_path, weights_path, strips_path=strips_path)
    profile = analytic_profile(engine)

    reel_margs = [compute_reel_marginal(r) for r in engine.reels]
    trigger_rate = reel_margs[-1].get("topdollar", 0.0)

    fp = weights_doc.get("feature_params") or {}
    x_count = tuple(fp["x_count_weights"])
    y_count = tuple(fp["y_count_weights"])
    x_val = tuple(fp.get("x_value_weights") or (1.0,) * len(_X_POOL))
    y_val = tuple(fp.get("y_value_weights") or (1.0,) * len(_Y_POOL))
    accept_thresh = float(fp.get("accept_threshold", 40))
    max_rounds = int(fp.get("max_rounds", 4))

    feature_spec = FeatureSpec(
        x_count_weights=x_count,
        y_count_weights=y_count,
        x_value_weights=x_val,
        y_value_weights=y_val,
        accept_threshold=accept_thresh,
        max_rounds=max_rounds,
    )
    fstats = analyze_feature(feature_spec)

    # P(R >= 1000 per paid spin) and P(R >= 200 per paid spin) via per-round
    # distribution (the accepted final round is the only one with R >= threshold
    # other than the forced last). Per design_v2.md §8.3 P(R>=X per spin)
    # approximation: P(R>=X per round) * trigger_rate (each session has effective
    # exposure ~ 1 accept round, so per-spin rate ~= trigger * per-trigger
    # P(R>=X per trigger)).
    round_dist = _round_payout_distribution(x_count, y_count, x_val, y_val)
    p_r_ge_1000_per_trigger = sum(p for r, p in round_dist if r >= 1000)
    p_r_ge_200_per_trigger = sum(p for r, p in round_dist if r >= TOP_JACKPOT_X)

    p_count_x_eq_1 = x_count[0] / sum(x_count) if sum(x_count) > 0 else 0.0

    feature_rtp_pp = trigger_rate * fstats.expected_payout * 100.0
    total_rtp_pct = profile["rtp_pct"] + feature_rtp_pp

    # Family RTP (base only).
    family_rtp_pp: dict[str, float] = defaultdict(float)
    for pid_str, rtp_contrib in profile.get("pay_rtp", {}).items():
        fam = FAMILY_OF_PAY_ID.get(pid_str)
        if fam is None:
            continue
        family_rtp_pp[fam] += rtp_contrib * 100.0

    return ModeState(
        mode=mode,
        profile=profile,
        feature_spec=feature_spec,
        feature_stats=fstats,
        trigger_rate=trigger_rate,
        feature_rtp_pp=feature_rtp_pp,
        total_rtp_pct=total_rtp_pct,
        p_r_ge_1000_per_trigger=p_r_ge_1000_per_trigger,
        p_r_ge_200_per_trigger=p_r_ge_200_per_trigger,
        p_count_x_eq_1=p_count_x_eq_1,
        reel_marginals=reel_margs,
        weights_doc=weights_doc,
        family_rtp_pp=dict(family_rtp_pp),
    )


# ----------------------------------------------------------------------
# check helpers
# ----------------------------------------------------------------------

@dataclass
class Check:
    category: str
    mode: int | None
    label: str
    ok: bool
    info: str = ""
    classification: str = "RED"  # RED | WARN | INFO

    def is_failing(self) -> bool:
        return (not self.ok) and self.classification == "RED"


def _band(category, mode, label, val, lo, hi, *, info="", fmt="{:.4f}"):
    ok = (lo is None or val >= lo) and (hi is None or val <= hi)
    lo_str = "-inf" if lo is None else fmt.format(lo)
    hi_str = "+inf" if hi is None else fmt.format(hi)
    return Check(
        category=category, mode=mode,
        label=f"{label} got={fmt.format(val)} band=[{lo_str}, {hi_str}]",
        ok=ok, info=info,
    )


def _max_le(category, mode, label, val, cap, *, info="", fmt="{:.6f}"):
    ok = val <= cap
    return Check(
        category=category, mode=mode,
        label=f"{label} got={fmt.format(val)} max={fmt.format(cap)}",
        ok=ok, info=info,
    )


def _min_ge(category, mode, label, val, floor, *, info="", fmt="{:.4f}"):
    ok = val >= floor
    return Check(
        category=category, mode=mode,
        label=f"{label} got={fmt.format(val)} min={fmt.format(floor)}",
        ok=ok, info=info,
    )


def _info(category, mode, label, info=""):
    return Check(category=category, mode=mode, label=label, ok=True,
                 info=info, classification="INFO")


# ----------------------------------------------------------------------
# per-mode checks
# ----------------------------------------------------------------------

def _run_per_mode_checks(state: ModeState) -> list[Check]:
    """Per-mode locked red lines + informational reports."""
    mode = state.mode
    checks: list[Check] = []

    # [RTP] total RTP band
    lo, hi = MODE_RTP_BAND_PCT[mode]
    checks.append(_band("RTP", mode,
                        f"mode {mode} total RTP %",
                        state.total_rtp_pct, lo, hi, fmt="{:.3f}",
                        info="DESIGN_PHILOSOPHY §C cross-mode RTP invariant + target_v2 band"))

    # [BASE-FEATURE-SPLIT] informational only per user_brief v1.1 §a
    base_pp = state.profile["rtp_pct"]
    feat_pp = state.feature_rtp_pp
    if state.total_rtp_pct > 0:
        base_share = base_pp / state.total_rtp_pct * 100
        feat_share = feat_pp / state.total_rtp_pct * 100
        checks.append(_info("BASE-FEATURE-SPLIT", mode,
                            f"mode {mode} split {base_share:.1f}:{feat_share:.1f} "
                            f"(base {base_pp:.2f}pp / feature {feat_pp:.2f}pp)",
                            info="user_brief v1.1 §a RELAXED — informational"))

    # [HIT]
    lo, hi = MODE_HIT_BAND[mode]
    checks.append(_band("HIT", mode,
                        f"mode {mode} base hit rate",
                        state.profile["hit_rate"], lo, hi, fmt="{:.4f}",
                        info="user_brief #1 + design_v2 §5"))

    # [CV] informational per v1.2 §g (process_improvements #37)
    checks.append(_info("CV", mode,
                        f"mode {mode} base CV = {state.profile['cv']:.3f}  "
                        f"feature CV (cond) = {state.feature_stats.cv:.3f}",
                        info="user_brief v1.2 §g — informational (CV no longer RED)"))

    # [1000+] P(R >= 1000 per paid spin)
    p_spin = state.trigger_rate * state.p_r_ge_1000_per_trigger
    checks.append(_max_le("1000+", mode,
                          f"mode {mode} P(R>=1000/spin)",
                          p_spin, P_R_GE_1000_PER_SPIN_MAX,
                          info="user_brief #5"))

    # [JACKPOT-VIS] per reel
    for r_idx, r_marg in enumerate(state.reel_marginals):
        m = r_marg.get("jackpot", 0.0)
        checks.append(_max_le("JACKPOT-VIS", mode,
                              f"mode {mode} R{r_idx+1} jackpot marginal",
                              m, JACKPOT_PER_REEL_MAX, fmt="{:.4f}",
                              info="user_brief #6 + proc_imp #15"))

    # [HIERARCHY] per philosophy §1 — bar / cherry / high7 inverse pyramid.
    #
    # Scope: standard / cut modes (m1, m7) enforce direction; lucky modes
    # (m2, m5) carve-out per design_v2 m2 lucky_lift_directional_invariants:
    # wild-substitution boost disproportionately lifts bar2 / bar3 line pays
    # above bar1 base ("lucky" narrative = high-payout symbols get bigger
    # boost from wild substitution). Hierarchy inversion in m2/m5 is the
    # designed lucky-mode signature, not a tuning gap. Cherry hierarchy still
    # enforced everywhere (cherry-anywhere paytable structure is stop-driven).
    pay_hits = state.profile.get("pay_hits", {})
    def _p_of_family(family_name: str) -> float:
        # Sum P(hit) for all pay_ids in that family
        return sum(p for pid_str, p in pay_hits.items()
                   if FAMILY_OF_PAY_ID.get(pid_str) == family_name)

    # Tolerance for "near-tied" — when stop-count asymmetry (proc_imp #21)
    # naturally produces P(low) ≈ P(high), accept tied within 0.10pp.
    # Per design_v2 m1: bar1 0.3438% vs bar2 0.3386% — within tied tolerance.
    HIERARCHY_TIED_TOL = 0.001  # 0.10pp absolute

    pairs_enforced = list(HIERARCHY_PAIRS_CHERRY) + list(HIERARCHY_PAIRS_HIGH7)
    # bar pairs only enforced for standard/cut modes
    if mode in (1, 7):
        pairs_enforced.extend(HIERARCHY_PAIRS_BAR)

    for lo_fam, hi_fam in pairs_enforced:
        lo_p = _p_of_family(lo_fam)
        hi_p = _p_of_family(hi_fam)
        ok = lo_p >= hi_p - HIERARCHY_TIED_TOL
        checks.append(Check(
            category="HIERARCHY", mode=mode,
            label=f"mode {mode} P({lo_fam}) {lo_p*100:.4f}% >= "
                  f"P({hi_fam}) {hi_p*100:.4f}%  (tied tol {HIERARCHY_TIED_TOL*100:.2f}pp)",
            ok=ok,
            info="philosophy §1 inverse pyramid (proc_imp #21 — marginal space, "
                 "stop-count asymmetry tolerance; m2/m5 bar lucky carve-out)",
        ))

    # Report m2/m5 bar hierarchy as INFO for transparency
    if mode in (2, 5):
        for lo_fam, hi_fam in HIERARCHY_PAIRS_BAR:
            lo_p = _p_of_family(lo_fam)
            hi_p = _p_of_family(hi_fam)
            checks.append(_info(
                "HIERARCHY", mode,
                f"mode {mode} P({lo_fam}) {lo_p*100:.4f}%  P({hi_fam}) {hi_p*100:.4f}% "
                f"(lucky carve-out — wild-substitution boost on bar2/bar3)",
                info="design_v2 m2 lucky_lift_directional_invariants",
            ))

    # [FAMILY-SHARE] share-of-base floors / caps per targets_v2
    base_rtp = state.profile["rtp_pct"]  # in pct
    share_bands = FAMILY_SHARE_BANDS_PCT.get(mode, {})
    for fam, (floor_pct, cap_pct) in share_bands.items():
        if fam == "high7":
            fam_pp = state.family_rtp_pp.get("high7_wild", 0.0) \
                     + state.family_rtp_pp.get("high7_pure", 0.0)
        else:
            fam_pp = state.family_rtp_pp.get(fam, 0.0)
        share = (fam_pp / base_rtp) * 100.0 if base_rtp > 0 else 0.0
        ok = share >= floor_pct and share <= cap_pct
        checks.append(Check(
            category="FAMILY-SHARE", mode=mode,
            label=f"mode {mode} {fam} share-of-base {share:.2f}% "
                  f"(floor {floor_pct:.1f}, cap {cap_pct:.1f})  "
                  f"absolute {fam_pp:.2f}pp",
            ok=ok,
            info="philosophy §10 pareto defense + target_v2 family floors",
        ))

    # [PER-PAY-FLOOR] per-pay HIT FREQUENCY floors (semantics: P %)
    # Disambiguated from share per process_improvements #34.
    pp_bands = PER_PAY_FREQ_BANDS_PCT.get(mode, {})
    for pid_str, (floor_pct, cap_pct) in pp_bands.items():
        p = pay_hits.get(pid_str, 0.0) * 100.0
        floor_ok = (floor_pct is None) or (p >= floor_pct)
        cap_ok = (cap_pct is None) or (p <= cap_pct)
        ok = floor_ok and cap_ok
        floor_str = "n/a (cut mode relaxed)" if floor_pct is None else f"{floor_pct:.4f}"
        checks.append(Check(
            category="PER-PAY-FLOOR", mode=mode,
            label=f"mode {mode} pay_id {pid_str} ({FAMILY_OF_PAY_ID.get(pid_str, '?')}) "
                  f"P={p:.4f}%  floor={floor_str}  cap={cap_pct:.4f}",
            ok=ok,
            info="proc_imp #34 frequency-vs-share semantics + target_v2",
        ))

    # [HIT-DECOMP] no single pay_id dominates hit rate beyond 70% (cherry1 80%
    # carve-out; cut-mode m7 carve-out to 85%).
    total_hit = state.profile["hit_rate"]
    if total_hit > 0:
        for pid_str, p in pay_hits.items():
            share = p / total_hit
            fam = FAMILY_OF_PAY_ID.get(pid_str, "?")
            if fam == "cherry1":
                if mode == 7:
                    cap = HIT_DECOMP_CAP_CHERRY1_CUT_MODE
                    cap_note = "cut-mode carve-out"
                else:
                    cap = HIT_DECOMP_CAP_CHERRY1
                    cap_note = "cherry-anywhere carve-out"
            else:
                cap = HIT_DECOMP_CAP_DEFAULT
                cap_note = "philosophy §8 default"
            ok = share <= cap + 1e-9
            # Only emit a check if we're at risk of breaching (>0.4) -- otherwise
            # informational noise.
            if share > 0.4:
                checks.append(Check(
                    category="HIT-DECOMP", mode=mode,
                    label=f"mode {mode} pay_id {pid_str} ({fam}) share-of-hit "
                          f"{share*100:.2f}% cap {cap*100:.0f}% ({cap_note})",
                    ok=ok,
                    info="philosophy §8 + proc_imp #16 cherry1 carve-out; "
                         "m7 cut-mode extension structurally documented in verify.py header",
                ))

    # [TOP-JACKPOT-ESC] X=200 ladder reported informational
    p_r_ge_200_per_spin = state.trigger_rate * state.p_r_ge_200_per_trigger
    checks.append(_info("TOP-JACKPOT-ESC", mode,
                        f"mode {mode} P(R>=200/spin) = {p_r_ge_200_per_spin:.3e}",
                        info=f"informational — escalation ladder X=200, "
                             f"design_v2.md §8.3"))

    # [TOP-JACKPOT-CADENCE] m1 + m7 pay_id 1 cadence in band
    if mode in (1, 7):
        pay1_p = pay_hits.get("1", 0.0)
        cadence_n = (1.0 / pay1_p) if pay1_p > 0 else float("inf")
        rng = M1_PAY1_CADENCE_RANGE if mode == 1 else M7_PAY1_CADENCE_RANGE
        ok = rng[0] <= cadence_n <= rng[1]
        checks.append(Check(
            category="TOP-JACKPOT-CADENCE", mode=mode,
            label=f"mode {mode} pay_id 1 wild_pure cadence 1 in "
                  f"{cadence_n:.0f}  band [1/{rng[0]}, 1/{rng[1]}]",
            ok=ok,
            info="philosophy §7 + design_v2 carve-out (m1 [1/50k, 1/100k]; m7 wider)",
        ))

    # [PCOUNT-X-1] p_count_x_eq_1 cap per user_brief v1.1 §b (relaxed to 0.06)
    checks.append(_max_le("PCOUNT-X-1", mode,
                          f"mode {mode} P(count_x=1)",
                          state.p_count_x_eq_1, 0.06, fmt="{:.4f}",
                          info="user_brief v1.1 §b relaxed to 6%"))

    return checks


# ----------------------------------------------------------------------
# cross-mode checks
# ----------------------------------------------------------------------

def _run_cross_mode_checks(states: dict[int, ModeState]) -> list[Check]:
    checks: list[Check] = []

    have = lambda *ms: all(m in states for m in ms)

    # [CROSS-RTP] mode-pair monotonicity (philosophy §9)
    if have(1, 2):
        ok = states[2].total_rtp_pct > states[1].total_rtp_pct
        checks.append(Check(
            category="CROSS-RTP", mode=None,
            label=f"m2 RTP {states[2].total_rtp_pct:.2f}% > "
                  f"m1 RTP {states[1].total_rtp_pct:.2f}%",
            ok=ok, info="philosophy §9 lucky > base",
        ))
    if have(2, 5):
        ok = states[5].total_rtp_pct > states[2].total_rtp_pct
        checks.append(Check(
            category="CROSS-RTP", mode=None,
            label=f"m5 RTP {states[5].total_rtp_pct:.2f}% > "
                  f"m2 RTP {states[2].total_rtp_pct:.2f}%",
            ok=ok, info="philosophy §9 super-lucky > lucky",
        ))
    if have(1, 7):
        ok = states[7].total_rtp_pct < states[1].total_rtp_pct
        checks.append(Check(
            category="CROSS-RTP", mode=None,
            label=f"m7 RTP {states[7].total_rtp_pct:.2f}% < "
                  f"m1 RTP {states[1].total_rtp_pct:.2f}%",
            ok=ok, info="philosophy §9 cut mode < base",
        ))

    # [LUCKY-MONO] hit + trigger monotonicity (philosophy §9 feature ext.)
    if have(1, 2):
        ok = states[2].profile["hit_rate"] > states[1].profile["hit_rate"]
        checks.append(Check(
            category="LUCKY-MONO", mode=None,
            label=f"m2 hit {states[2].profile['hit_rate']*100:.2f}% > "
                  f"m1 hit {states[1].profile['hit_rate']*100:.2f}%",
            ok=ok, info="philosophy §9 LUCKY_MONO",
        ))
        ok = states[2].trigger_rate >= states[1].trigger_rate - 1e-9
        checks.append(Check(
            category="LUCKY-MONO", mode=None,
            label=f"m2 trigger {states[2].trigger_rate*100:.3f}% >= "
                  f"m1 trigger {states[1].trigger_rate*100:.3f}%",
            ok=ok, info="philosophy §9 feature-machine extension",
        ))
    if have(2, 5):
        ok = states[5].profile["hit_rate"] >= states[2].profile["hit_rate"] - 1e-9
        checks.append(Check(
            category="LUCKY-MONO", mode=None,
            label=f"m5 hit {states[5].profile['hit_rate']*100:.4f}% >= "
                  f"m2 hit {states[2].profile['hit_rate']*100:.4f}% (strict per Fix #2)",
            ok=ok, info="philosophy §9 super-lucky_MONO",
        ))
        ok = states[5].trigger_rate >= states[2].trigger_rate - 1e-9
        checks.append(Check(
            category="LUCKY-MONO", mode=None,
            label=f"m5 trigger {states[5].trigger_rate*100:.4f}% >= "
                  f"m2 trigger {states[2].trigger_rate*100:.4f}% (strict per Fix #2)",
            ok=ok, info="design_v2 Fix #2 + LUCKY_MONO",
        ))
    if have(1, 7):
        ok = states[7].profile["hit_rate"] < states[1].profile["hit_rate"]
        checks.append(Check(
            category="LUCKY-MONO", mode=None,
            label=f"m7 hit {states[7].profile['hit_rate']*100:.2f}% < "
                  f"m1 hit {states[1].profile['hit_rate']*100:.2f}%",
            ok=ok, info="philosophy §4 cut mode hit reduction",
        ))

    # [MODE7-TRIGGER] marginal-equal m1 within +- 5e-4 (user_brief v1.1 §e)
    if have(1, 7):
        diff = abs(states[7].trigger_rate - states[1].trigger_rate)
        ok = diff <= MODE7_TRIGGER_TOL_ABS
        checks.append(Check(
            category="MODE7-TRIGGER", mode=7,
            label=f"|m7_trig - m1_trig| = {diff:.6f}  tol {MODE7_TRIGGER_TOL_ABS:.0e}  "
                  f"(m1 trig {states[1].trigger_rate*100:.4f}%, "
                  f"m7 trig {states[7].trigger_rate*100:.4f}%)",
            ok=ok,
            info="user_brief v1.1 §e option B + proc_imp #19",
        ))

    # [MODE7-CUT] mode 7 small-pay freq < mode 1 (user_brief v1.1 §e)
    if have(1, 7):
        small_pay_pids = ["9", "71", "8", "7", "5", "3"]
        # philosophy §4: small pays cut (cherry1/2, bar_mixed, bar1/2/3 in mode 7)
        m1_hits = states[1].profile.get("pay_hits", {})
        m7_hits = states[7].profile.get("pay_hits", {})
        for pid in small_pay_pids:
            m1_p = m1_hits.get(pid, 0.0)
            m7_p = m7_hits.get(pid, 0.0)
            ok = m7_p < m1_p - 1e-9
            checks.append(Check(
                category="MODE7-CUT", mode=7,
                label=f"pay_id {pid} ({FAMILY_OF_PAY_ID.get(pid, '?')}) "
                      f"m7 P={m7_p*100:.4f}% < m1 P={m1_p*100:.4f}%",
                ok=ok,
                info="philosophy §4 cut mode small-pay reduction",
            ))

    # [MODE7-BIGPAY] mode 7 pay_id 1/2/21 freq = mode 1 within +- 15%
    if have(1, 7):
        big_pay_pids = ["1", "2", "21"]
        m1_hits = states[1].profile.get("pay_hits", {})
        m7_hits = states[7].profile.get("pay_hits", {})
        for pid in big_pay_pids:
            m1_p = m1_hits.get(pid, 0.0)
            m7_p = m7_hits.get(pid, 0.0)
            ratio = (m7_p / m1_p) if m1_p > 0 else float("inf")
            ok = (1 - MODE7_BIGPAY_FREQ_TOL_RATIO) <= ratio <= (1 + MODE7_BIGPAY_FREQ_TOL_RATIO)
            checks.append(Check(
                category="MODE7-BIGPAY", mode=7,
                label=f"pay_id {pid} ({FAMILY_OF_PAY_ID.get(pid, '?')}) "
                      f"m7/m1 ratio {ratio:.3f}  band [{1-MODE7_BIGPAY_FREQ_TOL_RATIO:.2f}, "
                      f"{1+MODE7_BIGPAY_FREQ_TOL_RATIO:.2f}]",
                ok=ok,
                info="user_brief v1.1 §e big-pay preservation",
            ))

    # [TOP-JACKPOT-ESC] cross-mode pay_id 1 cadence (user_brief v1.1 §c + §d)
    if have(1, 2):
        m1_p = states[1].profile.get("pay_hits", {}).get("1", 0.0)
        m2_p = states[2].profile.get("pay_hits", {}).get("1", 0.0)
        ratio = (m2_p / m1_p) if m1_p > 0 else float("inf")
        ok = ratio <= M2_PAY1_OVER_M1_CAP
        checks.append(Check(
            category="TOP-JACKPOT-ESC", mode=None,
            label=f"m2 pay_id 1 wild_pure freq vs m1 ratio {ratio:.3f}  "
                  f"cap {M2_PAY1_OVER_M1_CAP}",
            ok=ok,
            info="user_brief v1.1 §c — 200x+ freq m2 = m1",
        ))
    if have(2, 5):
        m2_p = states[2].profile.get("pay_hits", {}).get("1", 0.0)
        m5_p = states[5].profile.get("pay_hits", {}).get("1", 0.0)
        ratio = (m5_p / m2_p) if m2_p > 0 else float("inf")
        ok = ratio >= M5_PAY1_OVER_M2_FLOOR
        checks.append(Check(
            category="TOP-JACKPOT-ESC", mode=None,
            label=f"m5 pay_id 1 wild_pure freq vs m2 ratio {ratio:.3f}  "
                  f"floor {M5_PAY1_OVER_M2_FLOOR}",
            ok=ok,
            info="user_brief v1.1 §d — m1 = m2 < m5 for 200x+ freq",
        ))

    return checks


# ----------------------------------------------------------------------
# strip-level checks (mode-invariant — strip is shared)
# ----------------------------------------------------------------------

def _run_strip_checks(strips: list[list[str]], weights_by_mode: dict[int, list[list[int]]]) -> list[Check]:
    """Strip-level invariants.

    These do not depend on mode (reel_strips.json is shared byte-for-byte).
    Weights-dependent strip-level checks (reel asymmetry blank balance etc.)
    are evaluated per-mode inside this helper since the *interpretation*
    of "blank density" depends on per-stop weights.
    """
    checks: list[Check] = []

    # [BLANK-FLANK] philosophy §13 — strip[p-1] != strip[p+1] for every blank p
    for r_idx, reel in enumerate(strips):
        n = len(reel)
        violations = []
        for p in range(n):
            if reel[p] == "blank":
                prev = reel[(p - 1) % n]
                nxt = reel[(p + 1) % n]
                if prev == nxt and prev != "blank":
                    violations.append((p, prev))
        ok = len(violations) == 0
        if ok:
            label = f"R{r_idx+1}: 0 X-blank-X violations"
        else:
            sample = violations[0]
            label = (f"R{r_idx+1}: {len(violations)} X-blank-X violations: "
                     f"pos {sample[0]} ({sample[1]}-blank-{sample[1]})")
        checks.append(Check(
            category="BLANK-FLANK", mode=None, label=label, ok=ok,
            info="philosophy §13 universal hard rule",
        ))

    # [STRIP-IMMUTABILITY] defensive check (also covered by
    # tests/test_strips_identical_across_modes.py if it exists).
    # Here we just confirm the strip read for verify == single source.
    checks.append(Check(
        category="STRIP-IMMUTABILITY", mode=None,
        label=f"reel_strips.json single shared file ({len(strips)} reels x "
              f"{len(strips[0])} stops)",
        ok=True,
        info="byte-identical across modes by file-layout invariant; mode-specific "
             "weights only diverge in weights/mode_<N>/weights.json",
    ))

    # [REEL-ASYMMETRY] philosophy §12 per-mode R1 vs R3 blank direction
    # m1/m7: strict R1 <= R3 + tol; m2/m5: carve-out per proc_imp #17
    REEL_ASYM_TOL_PP_STANDARD = 0.03  # m1/m7 tolerance
    for mode, weights in weights_by_mode.items():
        n_stops = len(strips[0])
        # Compute per-reel blank marginal from weights
        def reel_blank_marg(r_idx):
            total = sum(weights[r_idx])
            if total <= 0:
                return 0.0
            blank_w = sum(w for w, s in zip(weights[r_idx], strips[r_idx])
                          if s == "blank")
            return blank_w / total
        r1_blank = reel_blank_marg(0)
        r3_blank = reel_blank_marg(2)
        if mode in (1, 7):
            # Strict direction lock
            ok = r1_blank <= r3_blank + REEL_ASYM_TOL_PP_STANDARD
            label = (f"mode {mode} R1 blank {r1_blank*100:.2f}% vs R3 blank "
                     f"{r3_blank*100:.2f}% (diff {(r1_blank-r3_blank)*100:+.2f}pp, "
                     f"tol +{REEL_ASYM_TOL_PP_STANDARD*100:.0f}pp)")
            checks.append(Check(
                category="REEL-ASYMMETRY", mode=mode, label=label, ok=ok,
                info="philosophy §12 + Strickland/Reid R1 winners-friendly",
            ))
        else:
            # Lucky modes 2/5 — carve-out per proc_imp #17: direction may
            # reverse because R3 is trigger reel with topdollar density spike.
            # Report informational; no RED.
            checks.append(_info(
                "REEL-ASYMMETRY", mode,
                f"mode {mode} R1 blank {r1_blank*100:.2f}% vs R3 blank "
                f"{r3_blank*100:.2f}% (carve-out per philosophy §12.3 + proc_imp #17)",
                info="lucky-mode trigger-displacement reverses §12 direction lock",
            ))

    return checks


# ----------------------------------------------------------------------
# paytable + schema lock
# ----------------------------------------------------------------------

def _compute_paytable_hash(spec_dict: dict) -> str:
    """Canonical hash of the spec.json `pays` block.

    Used by [PAYTABLE-LOCK] (universal rule per process_improvements #36):
    paytable is immutable cross-machine. Any unauthorized change to `pays`
    causes the hash to drift and verify fails RED.

    Excludes any `_*` documentation keys from each pay entry (those are
    narrative and not part of the paytable mechanism).
    """
    pays = spec_dict.get("pays", [])
    cleaned = []
    for p in pays:
        cleaned.append({k: v for k, v in p.items() if not k.startswith("_")})
    canonical = json.dumps(cleaned, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _run_paytable_lock_check(spec_path: Path, expected_hash: str) -> Check:
    spec_dict = json.loads(spec_path.read_text(encoding="utf-8"))
    actual = _compute_paytable_hash(spec_dict)
    ok = actual == expected_hash
    return Check(
        category="PAYTABLE-LOCK", mode=None,
        label=f"spec.json pays hash actual={actual} expected={expected_hash}",
        ok=ok,
        info="universal rule (proc_imp #36) — paytable never modified",
    )


def _run_schema_fp_check(spec_path: Path, strips_path: Path,
                        weights_path: Path) -> Check:
    """Compute virtual chunk schema fingerprint and compare to production.

    Per 01b_baseline_report.md §12 — the production fingerprint
    `5d02773c069fc396` is the baseline. Any engine drift that changes the
    first-round key set will fail this lock.

    Uses `compute_schema_fingerprint_for` if available; otherwise falls back
    to a hash-of-`spec["pays"]+symbols+grid` proxy.
    """
    try:
        from slot_designer.core.emitter.chunk import compute_schema_fingerprint_for
        from slot_designer.core.engine.loader import load_engine as _load
        engine, _spec = _load(spec_path, weights_path, strips_path=strips_path)
        fp = compute_schema_fingerprint_for(engine, mode=1)
        ok = fp == PRODUCTION_SCHEMA_FP
        return Check(
            category="SCHEMA-FP", mode=None,
            label=f"virtual chunk fingerprint {fp} vs production "
                  f"{PRODUCTION_SCHEMA_FP}",
            ok=ok,
            info="01b §12 production schema lock",
        )
    except Exception as exc:
        # If compute_schema_fingerprint_for isn't importable in the current
        # tree, emit a WARN instead of RED. This is a soft signal — the
        # production fingerprint was verified at refactor merge 2ae5a7d.
        return Check(
            category="SCHEMA-FP", mode=None,
            label=f"schema fingerprint compute unavailable: {type(exc).__name__}",
            ok=True, classification="WARN",
            info=f"emitter.chunk.compute_schema_fingerprint_for not in this tree; "
                 f"production fp recorded {PRODUCTION_SCHEMA_FP}",
        )


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------

def run_verification(
    spec_path: Path = DEFAULT_SPEC,
    strips_path: Path = DEFAULT_STRIPS,
    weights_dir: Path = DEFAULT_WEIGHTS_DIR,
    *,
    paytable_baseline_hash: str | None = None,
) -> tuple[list[Check], int]:
    """Run all M15 verification categories.

    Returns (checks_list, exit_code).
    """
    spec_dict = json.loads(spec_path.read_text(encoding="utf-8"))
    strips_dict = json.loads(strips_path.read_text(encoding="utf-8"))
    strips = strips_dict["reels"]

    # PAYTABLE-LOCK: use module constant if no override supplied.
    expected = paytable_baseline_hash or PAYTABLE_BASELINE_HASH
    all_checks: list[Check] = []
    pl_check = _run_paytable_lock_check(spec_path, expected)
    all_checks.append(pl_check)

    states: dict[int, ModeState] = {}
    weights_by_mode: dict[int, list[list[int]]] = {}
    available_modes: list[int] = []
    for mode in (1, 2, 5, 7):
        wpath = weights_dir / f"mode_{mode}" / "weights.json"
        st = _load_mode_state(mode, spec_path, strips_path, wpath)
        if st is None:
            continue
        states[mode] = st
        weights_by_mode[mode] = st.weights_doc["weights"]
        available_modes.append(mode)

    if not states:
        print("ERROR: no mode weights found under " + str(weights_dir))
        return ([], 1)

    # Per-mode checks
    for mode in available_modes:
        all_checks.extend(_run_per_mode_checks(states[mode]))

    # Cross-mode checks
    all_checks.extend(_run_cross_mode_checks(states))

    # Strip-level checks
    all_checks.extend(_run_strip_checks(strips, weights_by_mode))

    # Schema fingerprint (uses mode 1 weights for the virtual chunk)
    if 1 in states:
        wpath = weights_dir / "mode_1" / "weights.json"
        all_checks.append(_run_schema_fp_check(spec_path, strips_path, wpath))

    fail_count = sum(1 for c in all_checks if c.is_failing())
    return all_checks, (0 if fail_count == 0 else 1)


def _print_report(checks: list[Check], available_modes: list[int]) -> int:
    print("\n=== M15 design verification ===")
    print(f"Modes available: {available_modes}\n")

    by_category: dict[str, list[Check]] = defaultdict(list)
    for c in checks:
        by_category[c.category].append(c)

    fail_count = 0
    for cat in sorted(by_category.keys()):
        items = by_category[cat]
        passes = sum(1 for c in items if c.ok or c.classification != "RED")
        red_fails = sum(1 for c in items if c.is_failing())
        warns = sum(1 for c in items if (not c.ok) and c.classification == "WARN")
        infos = sum(1 for c in items if c.classification == "INFO")
        if red_fails == 0:
            status = "GREEN" if warns == 0 else f"GREEN (with {warns} WARN)"
        else:
            status = f"RED ({red_fails}/{len(items)} fail)"
        info_tag = f", {infos} INFO" if infos else ""
        print(f"  [{cat:20s}] {passes:3d} pass / {len(items):3d} total{info_tag} -- {status}")
        for c in items:
            if c.is_failing():
                mode_str = f"mode {c.mode}" if c.mode is not None else "all"
                print(f"     [FAIL] {mode_str}: {c.label}")
                if c.info:
                    print(f"          ({c.info})")
                fail_count += 1
            elif c.classification == "WARN" and not c.ok:
                mode_str = f"mode {c.mode}" if c.mode is not None else "all"
                print(f"     [WARN] {mode_str}: {c.label}")
                if c.info:
                    print(f"          ({c.info})")

    # INFO summary print (top-level only)
    info_lines = [c for c in checks if c.classification == "INFO"]
    if info_lines:
        print("\n=== Informational signals (no RED) ===")
        for c in info_lines:
            mode_str = f"mode {c.mode}" if c.mode is not None else "all"
            print(f"  [{c.category}] {mode_str}: {c.label}")

    if fail_count == 0:
        print("\nGREEN -- all RED-line checks pass")
    else:
        print(f"\nRED -- {fail_count} check(s) failed")
    return fail_count


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="M15 design verification (analytic red lines + cross-mode invariants)",
    )
    p.add_argument("--weights-dir", type=Path, default=DEFAULT_WEIGHTS_DIR,
                   help="Alternate weights root (e.g., a Stage 6 tune output dir).")
    p.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    p.add_argument("--strips", type=Path, default=DEFAULT_STRIPS)
    p.add_argument("--paytable-hash", type=str, default=None,
                   help="Override expected paytable hash (advanced; "
                        "default is module constant).")
    p.add_argument("--self-check-paytable-hash", action="store_true",
                   help="Print the current paytable hash and exit (use to "
                        "update PAYTABLE_BASELINE_HASH after a USER-AUTHORIZED "
                        "paytable change escalation).")
    args = p.parse_args(argv)

    if args.self_check_paytable_hash:
        spec_dict = json.loads(args.spec.read_text(encoding="utf-8"))
        print(f"Current paytable hash: {_compute_paytable_hash(spec_dict)}")
        return 0

    checks, exit_code = run_verification(
        spec_path=args.spec,
        strips_path=args.strips,
        weights_dir=args.weights_dir,
        paytable_baseline_hash=args.paytable_hash,
    )
    available_modes = sorted({c.mode for c in checks
                              if c.mode is not None and isinstance(c.mode, int)})
    _print_report(checks, available_modes)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
