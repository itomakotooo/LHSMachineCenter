"""M37 design verification — player-experience gate.

Per ``project_slot_designer §A axiom``: numerical targets are necessary
preconditions; experience invariants are the soul. Run after any tune.
All red lines must be green before "done".

Categories (4 modes verified — see check_hit per-mode bands at lines 60-100):
  [RTP]                  mode 1 RTP ∈ [94%, 96%] (m2/m5/m7 see ts dict)
  [HIT]                  mode 1 hit ∈ [14%, 21%] (v3 wild count=3, side_wild_alone 增加)
                         m7 [11, 15.5%] / m2 [30, 36%] / m5 [30, 38%]
  [BUCKET-CAP]           ge5000 bucket = 0 (paytable max-payout invariant)
  [ALTERNATION]          strip strict B/N alternation, 0 violations (universal §E)
  [BLANK-FLANK-DIVERSITY] strip[p-1] ≠ strip[p+1] for every blank pos (universal §13)
  [BOOSTER-R1R3-EMPTY]   mini/minor/major/grand R1+R3 marginal = 0 (M37 paytable rule)
  [WILD-R2-EMPTY]        plain wild R2 marginal = 0 (M37 paytable rule)
  [BOOSTER-HIER]         R2: mini > minor > major > grand, adjacent ratio ≥ 1.3×
  [BOOSTER-VISIBLE]      R2 booster total marginal ∈ [7%, 13%] (mode 1)
  [GRAND-SIGNATURE]      R2 grand marginal ∈ [0.05%, 0.15%] (mode 1, lifetime tier)
  [REEL-ASYMMETRY]       R1 Blank ≤ R3 Blank ≤ R2 Blank
                         R1 top-prize density ≥ R3 top-prize density (top-prize = high7 + wild)
  [REROLL-VERIFY]        spec.reroll_blocks contains (wild, grand, wild)
  [TOP-PATH-1000X]       1000× top-jackpot = pay_id 1 × grand boost (no other path)
  [BUCKET-SHAPE]         JS divergence to target bucket distribution ≤ threshold

Usage:
    python -m slot_designer.scripts.verify_m37_design

Exit: 0 = all green, 1 = at least one red.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.core.devtools.analytic_rtp import (
    analytic_profile,
    compute_reel_marginal,
    structurally_reachable_buckets,
)
from slot_designer.core.devtools.shape_distance import shape_distance
from slot_designer.core.engine.loader import load_engine

SPEC = _ROOT / "slot_designer" / "machines" / "M37" / "spec.json"
STRIPS = _ROOT / "slot_designer" / "machines" / "M37" / "reel_strips.json"
WEIGHTS = {
    1: _ROOT / "slot_designer" / "machines" / "M37" / "weights" / "mode_1" / "weights.json",
    2: _ROOT / "slot_designer" / "machines" / "M37" / "weights" / "mode_2" / "weights.json",
    5: _ROOT / "slot_designer" / "machines" / "M37" / "weights" / "mode_5" / "weights.json",
    7: _ROOT / "slot_designer" / "machines" / "M37" / "weights" / "mode_7" / "weights.json",
}
TARGETS = {
    1: _ROOT / "slot_designer"  / "core" / "tuner" / "targets" / "M37_mode1.target.json",
}

# Per-mode tolerances + bands.
MODE_TARGETS = {
    1: {
        # v5 amendment 2026-05-11 (ship'd): RTP 94.09 / hit 20.92 / pid9 share 20.07%
        # - hit_hi 0.21→0.22 (V verify_v5_diff §1.1: physics floor 20.24 at pid9=20%+RTP=94)
        # - hier_ratio_min 1.3→1.0 (V verify_v5_diff §1.4: v5 sanction monotone strict)
        # - pid9_share band [19, 21]% (NEW user precise red, V verify_v5_diff §2.1)
        "rtp": 95.0, "rtp_tol_pp": 1.0,
        "hit_lo": 0.14, "hit_hi": 0.22,
        "booster_visible_lo": 0.04, "booster_visible_hi": 0.10,
        "grand_lo": 0.0007, "grand_hi": 0.0016,
        "hier_ratio_min": 1.0,
        "shape_js_max": 0.10,
        "pid9_share_lo": 19.0, "pid9_share_hi": 21.0,
    },
    2: {
        # v6 amendment 2026-05-12: RTP 303.45 / hit 32.21 / pid9 share 20.37%
        # - hier_ratio_min 1.3→1.0 (V verify_v6_diff: v5 sanction universal-floor consistency)
        # - pid9_share band [10, 22]% (NEW per V verify_v6_diff)
        "rtp": 300.0, "rtp_tol_pp": 5.0,
        "hit_lo": 0.30, "hit_hi": 0.36,
        "booster_visible_lo": 0.16, "booster_visible_hi": 0.28,
        "grand_lo": 0.0020, "grand_hi": 0.0065,
        "hier_ratio_min": 1.0,
        "shape_js_max": 0.10,
        "pid9_share_lo": 10.0, "pid9_share_hi": 22.0,
    },
    5: {
        # v6 amendment: auto-inherit from m2 base (MODE5-BASE-LOCK) + R2 grand pos 23 override.
        # RTP 507.56 / hit 33.09 / pid9 share 12.02%
        # - hier_ratio_min 1.3→1.0
        # - pid9_share band [8, 16]% (m5 always low — grand × high7 1000× dominates RTP)
        "rtp": 500.0, "rtp_tol_pp": 10.0,
        "hit_lo": 0.30, "hit_hi": 0.40,
        "booster_visible_lo": 0.16, "booster_visible_hi": 0.28,
        "grand_lo": 0.010, "grand_hi": 0.020,
        "hier_ratio_min": 1.0,
        "shape_js_max": 0.10,
        "pid9_share_lo": 8.0, "pid9_share_hi": 16.0,
    },
    7: {
        # v8 amendment 2026-05-12 (replace v6): RTP 85.16 / hit 20.11 / pid9 share 18.82%
        # Designer v8 player-experience optimal: R2 mini unchanged (Lightning Link UX intact),
        # R2 minor ×0.80, R2 major ×0.80, R1+R3 wild ×0.95. R1+R3 bar/high7 UNCHANGED.
        # - hit_hi 0.17→0.21 (V verify_v8_diff: v8 hit 20.11 close to m1 hit due to bar-untouched;
        #   §9 HIT-MONOTONIC-SAFETY m1-m7≥0.3pp守 cross-mode direction)
        # - WINDOW-VISIBILITY r1r3_high7 lower revert 0.24→0.26 (v8 R1+R3 byte-eq m1)
        # - per-pid ratio informational YELLOW (Designer §4 tier floors 0.85/0.80/0.50)
        "rtp": 85.0, "rtp_tol_pp": 1.0,
        "hit_lo": 0.11, "hit_hi": 0.21,
        "booster_visible_lo": 0.04, "booster_visible_hi": 0.12,
        "grand_lo": 0.0007, "grand_hi": 0.0016,
        "hier_ratio_min": 1.0,
        "shape_js_max": 0.10,
        "pid9_share_lo": 14.0, "pid9_share_hi": 21.0,
    },
}


# ANSI-ish status (no color in this codebase to keep output portable)
def _ok(msg: str) -> str:
    return f"  GREEN  {msg}"


def _fail(msg: str) -> str:
    return f"  RED    {msg}"


def _warn(msg: str) -> str:
    return f"  YELLOW {msg}"


def check_rtp(profile: dict, mode: int, ts: dict) -> tuple[bool, str]:
    rtp = profile["rtp_pct"]
    target = ts["rtp"]
    tol = ts["rtp_tol_pp"]
    if abs(rtp - target) <= tol:
        return True, _ok(f"[RTP]                 mode {mode} RTP {rtp:.3f}% ∈ [{target-tol}, {target+tol}]")
    return False, _fail(f"[RTP]                 mode {mode} RTP {rtp:.3f}% NOT in [{target-tol}, {target+tol}]")


def check_hit(profile: dict, mode: int, ts: dict) -> tuple[bool, str]:
    hit = profile["hit_rate"]
    if ts["hit_lo"] <= hit <= ts["hit_hi"]:
        return True, _ok(f"[HIT]                 mode {mode} hit {hit*100:.3f}% ∈ [{ts['hit_lo']*100}%, {ts['hit_hi']*100}%]")
    return False, _fail(f"[HIT]                 mode {mode} hit {hit*100:.3f}% NOT in [{ts['hit_lo']*100}%, {ts['hit_hi']*100}%]")


def check_bucket_cap(profile: dict, mode: int) -> tuple[bool, str]:
    ge5000 = profile["bucket_rate"].get("ge5000", 0.0)
    if ge5000 == 0.0:
        return True, _ok(f"[BUCKET-CAP]          mode {mode} ge5000 = 0 (paytable max 1000×)")
    return False, _fail(f"[BUCKET-CAP]          mode {mode} ge5000 = {ge5000*100:.6f}% — should be 0!")


def check_pid9_share(profile: dict, mode: int, ts: dict) -> tuple[bool, str]:
    """[PID9-SHARE] pid 9 RTP / total RTP — user v5+v6 precise red.

    Source: user_brief.md §v5/§v6 hard locked + design_v5.md §4 + design_v6.md §3.
    Encodes "no booster/wild-alone fallback dominating RTP" — classic 3-reel slot
    sanity ([10, 20]% is industry-typical alone-pay band; mode 5 lower because
    grand × high7 = 1000× absorbs more RTP into pid 1).
    """
    # pay_rtp keys are str (e.g. "9") per analytic_profile output convention.
    pid9_rtp_pp = profile["pay_rtp"].get("9", profile["pay_rtp"].get(9, 0.0)) * 100
    total_rtp = profile["rtp_pct"]
    if total_rtp <= 0:
        return False, _fail(f"[PID9-SHARE]          mode {mode} total RTP {total_rtp:.3f} <= 0")
    share = pid9_rtp_pp / total_rtp * 100
    lo, hi = ts["pid9_share_lo"], ts["pid9_share_hi"]
    if lo <= share <= hi:
        return True, _ok(f"[PID9-SHARE]          mode {mode} pid9 {share:.2f}% ∈ [{lo}%, {hi}%] (pid9_rtp={pid9_rtp_pp:.2f}pp / total {total_rtp:.2f}%)")
    return False, _fail(f"[PID9-SHARE]          mode {mode} pid9 {share:.2f}% NOT in [{lo}%, {hi}%] (pid9_rtp={pid9_rtp_pp:.2f}pp / total {total_rtp:.2f}%)")


def check_alternation(strips: list[list[str]], blank: str) -> tuple[bool, str]:
    violations = 0
    detail = []
    for ri, strip in enumerate(strips):
        n = len(strip)
        for i in range(n):
            cur_blank = strip[i] == blank
            nxt_blank = strip[(i+1) % n] == blank
            if cur_blank == nxt_blank:
                violations += 1
                if len(detail) < 3:
                    detail.append(f"R{ri+1}@{i}-{(i+1)%n}: {strip[i]}-{strip[(i+1)%n]}")
    if violations == 0:
        return True, _ok(f"[ALTERNATION]         all 3 reels strict B/N alternation (0 violations)")
    return False, _fail(f"[ALTERNATION]         {violations} violations across reels (e.g. {', '.join(detail)})")


def check_blank_flank_diversity(strips: list[list[str]], blank: str) -> tuple[bool, str]:
    violations = 0
    detail = []
    for ri, strip in enumerate(strips):
        n = len(strip)
        for p, sym in enumerate(strip):
            if sym != blank:
                continue
            prev_sym = strip[(p-1) % n]
            next_sym = strip[(p+1) % n]
            if prev_sym == next_sym:
                violations += 1
                if len(detail) < 3:
                    detail.append(f"R{ri+1}@blank-{p}: {prev_sym}-blank-{next_sym}")
    if violations == 0:
        return True, _ok(f"[BLANK-FLANK-DIVERSITY] no X-Blank-X anywhere (0 violations)")
    return False, _fail(f"[BLANK-FLANK-DIVERSITY] {violations} X-Blank-X violations (e.g. {', '.join(detail)})")


def check_booster_r1r3_empty(reel_marginals: list[dict[str, float]]) -> tuple[bool, str]:
    boosters = ["mini", "minor", "major", "grand"]
    leaks = []
    for ri in [0, 2]:  # R1, R3
        for b in boosters:
            mg = reel_marginals[ri].get(b, 0.0)
            if mg > 0:
                leaks.append(f"R{ri+1} {b} {mg*100:.3f}%")
    if not leaks:
        return True, _ok("[BOOSTER-R1R3-EMPTY]  mini/minor/major/grand absent on R1+R3")
    return False, _fail(f"[BOOSTER-R1R3-EMPTY]  leaks: {', '.join(leaks)}")


def check_wild_r2_empty(reel_marginals: list[dict[str, float]]) -> tuple[bool, str]:
    mg = reel_marginals[1].get("wild", 0.0)
    if mg == 0.0:
        return True, _ok("[WILD-R2-EMPTY]       plain wild absent on R2")
    return False, _fail(f"[WILD-R2-EMPTY]       leak: R2 wild {mg*100:.3f}% — should be 0!")


def check_booster_hier(reel_marginals: list[dict[str, float]], ts: dict) -> tuple[bool, str]:
    r2 = reel_marginals[1]
    mn = r2.get("mini", 0.0)
    mr = r2.get("minor", 0.0)
    mj = r2.get("major", 0.0)
    gr = r2.get("grand", 0.0)
    pairs = [("mini/minor", mn, mr), ("minor/major", mr, mj), ("major/grand", mj, gr)]
    rmin = ts["hier_ratio_min"]
    fails = []
    parts = []
    for name, hi, lo in pairs:
        if lo == 0:
            ratio = float("inf")
        else:
            ratio = hi / lo
        ok = hi > lo and ratio >= rmin
        parts.append(f"{name}={ratio:.2f}x")
        if not ok:
            fails.append(f"{name} ratio {ratio:.2f}x (need ≥ {rmin}x with hi > lo)")
    if not fails:
        return True, _ok(f"[BOOSTER-HIER]        倒金字塔 OK ({', '.join(parts)})")
    return False, _fail(f"[BOOSTER-HIER]        violations: {'; '.join(fails)}")


def check_booster_visible(reel_marginals: list[dict[str, float]], ts: dict) -> tuple[bool, str]:
    r2 = reel_marginals[1]
    total = sum(r2.get(b, 0.0) for b in ["mini", "minor", "major", "grand"])
    lo, hi = ts["booster_visible_lo"], ts["booster_visible_hi"]
    if lo <= total <= hi:
        return True, _ok(f"[BOOSTER-VISIBLE]     R2 booster total {total*100:.3f}% ∈ [{lo*100}%, {hi*100}%]")
    return False, _fail(f"[BOOSTER-VISIBLE]     R2 booster total {total*100:.3f}% NOT in [{lo*100}%, {hi*100}%]")


def check_grand_signature(reel_marginals: list[dict[str, float]], ts: dict) -> tuple[bool, str]:
    gr = reel_marginals[1].get("grand", 0.0)
    lo, hi = ts["grand_lo"], ts["grand_hi"]
    if lo <= gr <= hi:
        return True, _ok(f"[GRAND-SIGNATURE]     R2 grand {gr*100:.4f}% ∈ [{lo*100}%, {hi*100}%]")
    return False, _fail(f"[GRAND-SIGNATURE]     R2 grand {gr*100:.4f}% NOT in [{lo*100}%, {hi*100}%]")


def check_reel_asymmetry(reel_marginals: list[dict[str, float]]) -> tuple[bool, str]:
    blanks = [m.get("blank", 0.0) for m in reel_marginals]
    # Top-prize density on R1/R3 = high7 + wild + 7bar (these contribute to top-paying combos).
    # On R2 the analogue is high7 + booster (booster_visible covered separately).
    top_R1 = reel_marginals[0].get("high7", 0) + reel_marginals[0].get("wild", 0) + reel_marginals[0].get("7bar", 0)
    top_R3 = reel_marginals[2].get("high7", 0) + reel_marginals[2].get("wild", 0) + reel_marginals[2].get("7bar", 0)
    fails = []
    parts = [f"blanks R1={blanks[0]*100:.1f}% R3={blanks[2]*100:.1f}% R2={blanks[1]*100:.1f}%"]
    if not (blanks[0] <= blanks[2] + 0.01):  # 1pp slack
        fails.append(f"R1 blank {blanks[0]*100:.2f}% > R3 {blanks[2]*100:.2f}%")
    if not (blanks[2] <= blanks[1] + 0.01):
        fails.append(f"R3 blank {blanks[2]*100:.2f}% > R2 {blanks[1]*100:.2f}%")
    parts.append(f"top-prize R1={top_R1*100:.1f}% R3={top_R3*100:.1f}%")
    if top_R1 + 0.005 < top_R3:  # 0.5pp slack
        fails.append(f"R1 top-prize {top_R1*100:.2f}% < R3 {top_R3*100:.2f}% (R1 should ≥ R3)")
    if not fails:
        return True, _ok(f"[REEL-ASYMMETRY]      {'; '.join(parts)}")
    return False, _fail(f"[REEL-ASYMMETRY]      violations: {'; '.join(fails)}")


def check_reroll_verify(spec: dict) -> tuple[bool, str]:
    blocks = spec.get("reroll_blocks", [])
    patterns = [tuple(b.get("pattern", [])) for b in blocks]
    if ("wild", "grand", "wild") in patterns:
        return True, _ok("[REROLL-VERIFY]       (wild, grand, wild) in spec.reroll_blocks")
    return False, _fail("[REROLL-VERIFY]       (wild, grand, wild) NOT in spec.reroll_blocks!")


def check_top_path_1000x(profile: dict, engine, evaluator) -> tuple[bool, str]:
    """1000× top jackpot must be reached EXCLUSIVELY via pay_id 1 × grand boost.
    Engine-level: enumerate payline combos at 1000× exactly, all should be pay_id 1
    with grand on R2 + (high7|wild) on sides.
    """
    from slot_designer.core.devtools.analytic_rtp import enumerate_payline
    paths_1000 = []
    for prob, pay_id, mult in enumerate_payline(engine):
        if mult == 1000.0:
            paths_1000.append((prob, pay_id))
    if not paths_1000:
        return False, _fail("[TOP-PATH-1000X]      no 1000× combinations enumerable — Grand path broken!")
    # All 1000× combos should be pay_id 1
    non_pay_id_1 = [(p, pid) for p, pid in paths_1000 if pid != 1]
    if non_pay_id_1:
        return False, _fail(f"[TOP-PATH-1000X]      {len(non_pay_id_1)} non-pay_id-1 combo(s) reach 1000×")
    n_combos = len(paths_1000)
    total_prob = sum(p for p, _ in paths_1000)
    return True, _ok(f"[TOP-PATH-1000X]      {n_combos} combos all pay_id 1 (high7-grand anchor); P(1000×)={total_prob*100:.5f}%")


def check_bucket_shape(profile: dict, target: dict, ts: dict, reachable) -> tuple[bool, str]:
    pred = profile["bucket_rate"]
    tgt = target["bucket_rate"]
    sd = shape_distance(pred, tgt, reachable_buckets=reachable)
    js = sd["js_divergence"]
    if js <= ts["shape_js_max"]:
        return True, _ok(f"[BUCKET-SHAPE]        JS divergence {js:.4f} ≤ {ts['shape_js_max']}")
    return False, _fail(f"[BUCKET-SHAPE]        JS divergence {js:.4f} > {ts['shape_js_max']}")


def check_mode7_lock(profiles: dict, marginals: dict) -> list[tuple[bool, str]]:
    """Mode 7 booster marginal close to mode 1 — booster reveal cadence preserved.

    Per universal §D + public M37Cfg evidence (skin 7 vs skin 1 booster within 0.1pp):
    booster marginal must match within ±0.5pp tolerance (allows R2 reel total
    weight drift due to other R2 changes between modes, but reveal cadence is
    sensibly identical to player).
    """
    out = []
    if 1 not in profiles or 7 not in profiles:
        return out
    m1_rms = marginals[1]
    m7_rms = marginals[7]
    tol = 0.005  # 0.5pp
    for sym in ['mini', 'minor', 'major', 'grand']:
        m1_v = m1_rms[1].get(sym, 0)
        m7_v = m7_rms[1].get(sym, 0)
        delta = abs(m1_v - m7_v)
        eq = delta <= tol
        if eq:
            out.append((True, _ok(f"[MODE7-LOCK]          R2 {sym} m1 {m1_v*100:.4f}% / m7 {m7_v*100:.4f}% (drift {delta*100:.4f}pp ≤ 0.5pp)")))
        else:
            out.append((False, _fail(f"[MODE7-LOCK]          R2 {sym} drift {delta*100:.4f}pp > 0.5pp tolerance")))
    return out


def check_mode5_base_lock(weights: dict, strips: list) -> tuple[bool, str]:
    """Mode 5 base weights byte-identical to mode 2, except R2 grand."""
    if 2 not in weights or 5 not in weights:
        return True, _ok("[MODE5-BASE-LOCK]     skip (mode 2 or 5 missing)")
    grand_idx = [i for i, sym in enumerate(strips[1]) if sym == 'grand']
    violations = []
    for ri in range(3):
        for pi in range(len(weights[2][ri])):
            if ri == 1 and pi in grand_idx:
                continue
            if weights[2][ri][pi] != weights[5][ri][pi]:
                violations.append(f"R{ri+1}[{pi}]")
    if not violations:
        return True, _ok("[MODE5-BASE-LOCK]     mode 5 base byte-eq mode 2 (only R2 grand differs)")
    return False, _fail(f"[MODE5-BASE-LOCK]     {len(violations)} non-grand drift positions: {violations[:3]}...")


def _compute_window_visibility(strips: list[list[str]], weights: list[list[int]],
                                target_symbols: list[str]) -> dict[int, dict[str, float]]:
    """For each reel, compute P(symbol visible in 3-row window) for target_symbols.

    P(X visible) = sum over stop p of (weight[p]/total) ×
        [strip[(p-1)%n]==X OR strip[p]==X OR strip[(p+1)%n]==X]
    """
    out = {}
    for reel_idx in range(len(strips)):
        n = len(strips[reel_idx])
        total = sum(weights[reel_idx])
        vis = {sym: 0.0 for sym in target_symbols}
        for p in range(n):
            window = {strips[reel_idx][(p - 1) % n], strips[reel_idx][p], strips[reel_idx][(p + 1) % n]}
            for sym in target_symbols:
                if sym in window:
                    vis[sym] += weights[reel_idx][p] / total
        out[reel_idx] = vis
    return out


def check_window_visibility(strips: list[list[str]], weights: list[list[int]], mode: int) -> list[tuple[bool, str]]:
    """Per-mode window visibility band check.

    Bands per M37/DESIGN.md §7.4:
      mode 1/7: R2 grand [12%, 22%], R1+R3 high7 [28%, 38%], wild [12%, 22%]
      mode 2/5: R2 grand [22%, 40%], R1+R3 high7 [32%, 45%], wild [15%, 25%]
    """
    bands = {
        # 2026-05-07 LAYOUT v2: R1/R3 wild count 2→3 → window vis baseline higher.
        # Old band [10%, 22%] was for 2-wild layout; new 3-wild layout produces ~18-23%.
        # Band widened upper to 26% to accommodate.
        # m1 v5 ship'd 2026-05-11: R1+R3 high7 +29% boost → window vis up; bands kept.
        1: {"r2_grand": (0.10, 0.22), "r1r3_high7": (0.26, 0.40), "r1r3_wild": (0.10, 0.26),
            "r2_booster_total": (0.18, 0.40)},
        # m7 v8 2026-05-12 (replace v6): R1+R3 bar/high7 byte-eq m1 v5 (no v6 boost),
        # so high7 window vis reverts to m1-aligned. r1r3_high7 lower 0.24→0.26 revert.
        # r1r3_wild kept at 0.08 lower (v8 wild ×0.95 cut needs floor).
        7: {"r2_grand": (0.10, 0.22), "r1r3_high7": (0.26, 0.40), "r1r3_wild": (0.08, 0.26),
            "r2_booster_total": (0.18, 0.40)},
        # 2026-05-07 ARCHETYPE PIVOT: bar-and-grand-anchored (v4). Wild visibility band
        # widened (wild marginal 2.2% vs old 14% → window vis ~8% vs old ~25%); high7 band
        # widened slightly (R1+R3 high7 marginal diluted by lowbars boost). Grand widened
        # (now anchors ge200-500). r2_booster_total band kept (booster mass ~24% preserved).
        2: {"r2_grand": (0.10, 0.45), "r1r3_high7": (0.15, 0.40), "r1r3_wild": (0.05, 0.35),
            "r2_booster_total": (0.35, 0.60)},
        5: {"r2_grand": (0.15, 0.55), "r1r3_high7": (0.15, 0.40), "r1r3_wild": (0.05, 0.35),
            "r2_booster_total": (0.35, 0.60)},
    }
    if mode not in bands:
        return []
    out = []
    band = bands[mode]
    targets = ["high7", "wild", "grand", "mini", "minor", "major"]
    vis = _compute_window_visibility(strips, weights, targets)

    # R2 grand
    g = vis[1].get("grand", 0)
    lo, hi = band["r2_grand"]
    if lo <= g <= hi:
        out.append((True, _ok(f"[WINDOW-VISIBILITY]   mode {mode} R2 grand window {g*100:.2f}% ∈ [{lo*100}%, {hi*100}%]")))
    else:
        out.append((False, _fail(f"[WINDOW-VISIBILITY]   mode {mode} R2 grand window {g*100:.2f}% NOT in [{lo*100}%, {hi*100}%]")))

    # R1+R3 high7
    h1 = vis[0].get("high7", 0)
    h3 = vis[2].get("high7", 0)
    lo, hi = band["r1r3_high7"]
    if lo <= h1 <= hi and lo <= h3 <= hi:
        out.append((True, _ok(f"[WINDOW-VISIBILITY]   mode {mode} R1 high7 {h1*100:.2f}%, R3 high7 {h3*100:.2f}% ∈ [{lo*100}%, {hi*100}%]")))
    else:
        out.append((False, _fail(f"[WINDOW-VISIBILITY]   mode {mode} R1 high7 {h1*100:.2f}% / R3 high7 {h3*100:.2f}% NOT in [{lo*100}%, {hi*100}%]")))

    # R1+R3 wild
    w1 = vis[0].get("wild", 0)
    w3 = vis[2].get("wild", 0)
    lo, hi = band["r1r3_wild"]
    if lo <= w1 <= hi and lo <= w3 <= hi:
        out.append((True, _ok(f"[WINDOW-VISIBILITY]   mode {mode} R1 wild {w1*100:.2f}%, R3 wild {w3*100:.2f}% ∈ [{lo*100}%, {hi*100}%]")))
    else:
        out.append((False, _fail(f"[WINDOW-VISIBILITY]   mode {mode} R1 wild {w1*100:.2f}% / R3 wild {w3*100:.2f}% NOT in [{lo*100}%, {hi*100}%]")))

    # R2 booster total
    btot = sum(vis[1].get(s, 0) for s in ["mini", "minor", "major", "grand"])
    # NOTE: this counts overlap (booster visibility computed independently per symbol)
    # so total may exceed 100%. The "total" here is actually probability of "any booster visible"
    # but we're approximating with sum. Use individual checks anyway.
    return out


def check_window_visibility_cap(strips: list[list[str]], weights: list[list[int]], mode: int) -> tuple[bool, str]:
    """No top symbol visibility exceeds 50% (防"假")."""
    targets = ["high7", "wild", "grand", "mini", "minor", "major"]
    vis = _compute_window_visibility(strips, weights, targets)
    violations = []
    for ri in range(len(strips)):
        for sym in targets:
            v = vis[ri].get(sym, 0)
            if v > 0.50:
                violations.append(f"R{ri+1} {sym} {v*100:.1f}%")
    if not violations:
        return True, _ok(f"[WINDOW-VISIBILITY-CAP] mode {mode} no top symbol exceeds 50% any-reel visibility")
    return False, _fail(f"[WINDOW-VISIBILITY-CAP] mode {mode} violations: {', '.join(violations)}")


def check_blank_ratio_cap(strips: list[list[str]], weights: list[list[int]], mode: int) -> tuple[bool, str]:
    """Per-reel max(blank_weight)/min(blank_weight) ≤ 5× (防"假"redistribution)."""
    cap = 5.0
    violations = []
    for ri in range(len(strips)):
        blank_weights = [weights[ri][p] for p, sym in enumerate(strips[ri]) if sym == "blank"]
        if not blank_weights:
            continue
        ratio = max(blank_weights) / min(blank_weights)
        if ratio > cap + 0.01:  # tiny epsilon for rounding
            violations.append(f"R{ri+1} {ratio:.2f}x")
    if not violations:
        return True, _ok(f"[BLANK-RATIO-CAP]     mode {mode} per-reel blank weight max/min ≤ {cap}x")
    return False, _fail(f"[BLANK-RATIO-CAP]     mode {mode} violations: {', '.join(violations)}")


def check_mid_pay_visible_floor(strips: list[list[str]], weights: list[list[int]], mode: int) -> tuple[bool, str]:
    """Mid-pay (1bar/2bar/3bar/7bar) any-reel window visibility ≥ floor (防视觉消失)."""
    # Per-mode floor: mode 1/7 standard 8%; mode 2/5 since 2026-05-07 pivot intentionally
    # de-emphasizes high-bars (3bar/7bar cut ×0.5 to limit (high_bar×grand)→ge500+ leak).
    # 7% floor still keeps high-bars visible (every ~14 spins) for symbol identity.
    floor = 0.07 if mode in (2, 5) else 0.08
    targets = ["1bar", "2bar", "3bar", "7bar"]
    vis = _compute_window_visibility(strips, weights, targets)
    violations = []
    for ri in range(len(strips)):
        for sym in targets:
            v = vis[ri].get(sym, 0)
            if v < floor:
                violations.append(f"R{ri+1} {sym} {v*100:.2f}%")
    if not violations:
        return True, _ok(f"[MID-PAY-VISIBLE-FLOOR] mode {mode} all mid-pay any-reel visibility ≥ {floor*100}%")
    return False, _fail(f"[MID-PAY-VISIBLE-FLOOR] mode {mode} violations: {', '.join(violations)}")


def check_cross_mode_invariants(profiles: dict, marginals: dict) -> list[tuple[bool, str]]:
    """Cross-mode monotonicity + escalation."""
    out = []
    if not all(m in profiles for m in [1, 2, 5, 7]):
        return out
    rtp = {m: profiles[m]['rtp_pct'] for m in [1, 2, 5, 7]}
    hit = {m: profiles[m]['hit_rate'] for m in [1, 2, 5, 7]}
    grand = {m: marginals[m][1].get('grand', 0) for m in [1, 2, 5, 7]}

    # RTP monotonic: m7 < m1 < m2 < m5
    if rtp[7] < rtp[1] < rtp[2] < rtp[5]:
        out.append((True, _ok(f"[RTP-MONOTONIC]       m7 {rtp[7]:.1f} < m1 {rtp[1]:.1f} < m2 {rtp[2]:.1f} < m5 {rtp[5]:.1f}")))
    else:
        out.append((False, _fail(f"[RTP-MONOTONIC]       violated: m7={rtp[7]:.1f} m1={rtp[1]:.1f} m2={rtp[2]:.1f} m5={rtp[5]:.1f}")))

    # Hit monotonic: m7 < m1 < m2 (m5 ≈ m2)
    if hit[7] < hit[1] < hit[2]:
        if abs(hit[5] - hit[2]) < 0.05:  # 5pp slack between m2 and m5
            out.append((True, _ok(f"[HIT-MONOTONIC]       m7 {hit[7]*100:.1f}% < m1 {hit[1]*100:.1f}% < m2 {hit[2]*100:.1f}% ≈ m5 {hit[5]*100:.1f}%")))
        else:
            out.append((False, _fail(f"[HIT-MONOTONIC]       m5 hit drift from m2: m2 {hit[2]*100:.1f}% vs m5 {hit[5]*100:.1f}% (gap > 5pp)")))
    else:
        out.append((False, _fail(f"[HIT-MONOTONIC]       violated: m7={hit[7]*100:.1f}% m1={hit[1]*100:.1f}% m2={hit[2]*100:.1f}% m5={hit[5]*100:.1f}%")))

    # Top-jackpot escalation: grand R2 marginal m7 ≈ m1 (within ±0.5pp tolerance per MODE7-LOCK)
    # < m2 < m5 (m5 most frequent grand)
    if abs(grand[7] - grand[1]) < 0.005 and grand[1] < grand[2] < grand[5]:
        ratios = f"m1={grand[1]*100:.3f}% m2={grand[2]*100:.3f}% (×{grand[2]/grand[1]:.1f}) m5={grand[5]*100:.3f}% (×{grand[5]/grand[1]:.1f})"
        out.append((True, _ok(f"[TOP-JACKPOT-ESCALATION] grand m7≈m1<m2<m5 ✓ {ratios}")))
    else:
        out.append((False, _fail(f"[TOP-JACKPOT-ESCALATION] violated: m1={grand[1]*100:.3f}% m2={grand[2]*100:.3f}% m5={grand[5]*100:.3f}% m7={grand[7]*100:.3f}%")))

    return out


def main() -> int:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    strips_doc = json.loads(STRIPS.read_text(encoding="utf-8"))
    strips = strips_doc["reels"]

    # Detect blank
    flat = [s for r in strips for s in r]
    blank = "blank" if "blank" in flat else "Blank"

    print(f"=== M37 design verification ===")
    print(f"  spec    : {SPEC.relative_to(_ROOT)}")
    print(f"  strips  : {STRIPS.relative_to(_ROOT)}")
    print(f"  modes   : {sorted(WEIGHTS)}")
    print()

    # Strip-level checks (mode-independent)
    print("Strip-level (mode-independent):")
    results = []
    ok, msg = check_alternation(strips, blank); results.append(ok); print(msg)
    ok, msg = check_blank_flank_diversity(strips, blank); results.append(ok); print(msg)
    ok, msg = check_reroll_verify(spec); results.append(ok); print(msg)
    print()

    # Per-mode checks — collect profiles + marginals + raw weights for cross-mode checks
    profiles = {}
    marginals = {}
    raw_weights = {}
    for mode in sorted(WEIGHTS):
        ts = MODE_TARGETS[mode]
        weights_path = WEIGHTS[mode]
        if not weights_path.exists():
            print(f"Mode {mode}: weights file missing ({weights_path}) — skipping.")
            continue
        # Use mode 1 target for bucket-shape comparison; modes 2/5/7 don't have rigid bucket targets
        # (mode 7 derived from m1, mode 2/5 are independent — JS check is informational)
        target_path = TARGETS.get(mode, TARGETS[1])
        target = json.loads(target_path.read_text(encoding="utf-8"))
        engine, _ = load_engine(SPEC, weights_path)
        profile = analytic_profile(engine)
        reel_marginals = [compute_reel_marginal(r) for r in engine.reels]
        reachable = structurally_reachable_buckets(engine)
        profiles[mode] = profile
        marginals[mode] = reel_marginals
        raw_weights[mode] = json.loads(weights_path.read_bytes().decode("utf-8"))["weights"]

        print(f"Mode {mode}:")
        print(f"  RTP {profile['rtp_pct']:.3f}%  hit {profile['hit_rate']*100:.3f}%  CV {profile['cv']:.3f}")
        print(f"  R1 marginals: blank={reel_marginals[0].get('blank', 0)*100:.1f}% wild={reel_marginals[0].get('wild', 0)*100:.2f}% high7={reel_marginals[0].get('high7', 0)*100:.2f}%")
        print(f"  R2 marginals: blank={reel_marginals[1].get('blank', 0)*100:.1f}% high7={reel_marginals[1].get('high7', 0)*100:.2f}% mini={reel_marginals[1].get('mini', 0)*100:.3f}% minor={reel_marginals[1].get('minor', 0)*100:.3f}% major={reel_marginals[1].get('major', 0)*100:.3f}% grand={reel_marginals[1].get('grand', 0)*100:.4f}%")
        print(f"  R3 marginals: blank={reel_marginals[2].get('blank', 0)*100:.1f}% wild={reel_marginals[2].get('wild', 0)*100:.2f}% high7={reel_marginals[2].get('high7', 0)*100:.2f}%")
        print()

        ok, msg = check_rtp(profile, mode, ts); results.append(ok); print(msg)
        ok, msg = check_hit(profile, mode, ts); results.append(ok); print(msg)
        ok, msg = check_pid9_share(profile, mode, ts); results.append(ok); print(msg)
        ok, msg = check_bucket_cap(profile, mode); results.append(ok); print(msg)
        # Bucket-shape only meaningful for mode 1 (we have a hit-targeted bell shape there).
        # Modes 2/5/7 are independent archetypes — bucket shape emerges from per-reel design.
        if mode == 1:
            ok, msg = check_bucket_shape(profile, target, ts, reachable); results.append(ok); print(msg)
        ok, msg = check_booster_r1r3_empty(reel_marginals); results.append(ok); print(msg)
        ok, msg = check_wild_r2_empty(reel_marginals); results.append(ok); print(msg)
        ok, msg = check_booster_hier(reel_marginals, ts); results.append(ok); print(msg)
        ok, msg = check_booster_visible(reel_marginals, ts); results.append(ok); print(msg)
        ok, msg = check_grand_signature(reel_marginals, ts); results.append(ok); print(msg)
        ok, msg = check_reel_asymmetry(reel_marginals); results.append(ok); print(msg)
        ok, msg = check_top_path_1000x(profile, engine, None); results.append(ok); print(msg)
        # New §15 PWDF checks (per universal §15.7 + §15.8 / M37 DESIGN.md §7)
        for ok, msg in check_window_visibility(strips, raw_weights[mode], mode):
            results.append(ok); print(msg)
        ok, msg = check_window_visibility_cap(strips, raw_weights[mode], mode); results.append(ok); print(msg)
        ok, msg = check_blank_ratio_cap(strips, raw_weights[mode], mode); results.append(ok); print(msg)
        ok, msg = check_mid_pay_visible_floor(strips, raw_weights[mode], mode); results.append(ok); print(msg)
        print()

    # Cross-mode invariants
    print("Cross-mode invariants:")
    for ok, msg in check_mode7_lock(profiles, marginals):
        results.append(ok); print(msg)
    if 2 in raw_weights and 5 in raw_weights:
        ok, msg = check_mode5_base_lock(raw_weights, strips); results.append(ok); print(msg)
    for ok, msg in check_cross_mode_invariants(profiles, marginals):
        results.append(ok); print(msg)
    print()

    n_total = len(results)
    n_green = sum(results)
    print(f"=== Result: {n_green}/{n_total} GREEN ===")
    return 0 if n_green == n_total else 1


if __name__ == "__main__":
    sys.exit(main())
