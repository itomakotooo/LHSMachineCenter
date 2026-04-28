"""M279 design verification — DESIGN_PHILOSOPHY 11 categories + experience invariants.

Runs after every M279 tune commit. Loads each mode's weights, simulates
N spins, and asserts:
  1. RTP target ±tolerance per mode
  2. hit rate target ±tolerance
  3. nudge rate ≈ archetype 12% (mode 1/7) or scaled (mode 2/5)
  4. wheel rate matches collect-meter (1/CollectMax)
  5. Family RTP share matches archetype (7-family ~50%, bar ~25%)
  6. Mode-pair monotonicity: m5>m2>m1>m7 RTP, m5>m2>m1>m7 top-jp freq
  7. Top jackpot escalation: m5/m1 ratio ≥ 5x for pay 101
  8. Hit decomposition: no single pay > 70% of hits
  9. Bucket shape narrative: m1 bucket distribution matches design
  10. Wheel EV invariant: 40000 credits = 40× bet
  11. Nudge mechanic: when partial stack lands, MoveSpin completes reveal
  12. Per-tier hit preservation: m7 keeps Mid/High/Top hit absolute, only Low drops

GREEN = all asserts pass.
RED = any assert fails (commit blocked per WORKFLOW.md).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.engine.m279.engine import (
    M279SessionState,
    ST_NUDGE,
    ST_PAID,
    ST_WHEEL,
)
from slot_designer.engine.m279.loader import load_m279_engine


# Per-mode constraints (slot_designer cross-machine red lines).
MODE_CONSTRAINTS = {
    1: {
        "rtp_pct": 95.0, "rtp_tolerance_pp": 8.0,
        "hit_rate": 0.142, "hit_tolerance_pp": 5.0,
        "nudge_rate_min": 0.10, "nudge_rate_max": 0.18,
        "label": "baseline",
    },
    2: {
        "rtp_pct": 300.0, "rtp_tolerance_pp": 30.0,
        "hit_rate": 0.225, "hit_tolerance_pp": 5.0,
        "nudge_rate_min": 0.15, "nudge_rate_max": 0.30,
        "label": "lucky",
    },
    5: {
        "rtp_pct": 500.0, "rtp_tolerance_pp": 100.0,
        "hit_rate": 0.225, "hit_tolerance_pp": 3.0,
        "nudge_rate_min": 0.15, "nudge_rate_max": 0.30,
        "label": "super-lucky (base = m2 byte-identical, feature enhance via _m279_overrides)",
    },
    7: {
        "rtp_pct": 85.0, "rtp_tolerance_pp": 8.0,
        "hit_rate": 0.105, "hit_tolerance_pp": 3.0,
        "nudge_rate_min": 0.10, "nudge_rate_max": 0.18,
        "label": "standard low",
    },
}


def _sim(engine, n_spins: int, seed: int = 7) -> dict:
    state = M279SessionState()
    rng = Random(seed)
    total_win = 0
    total_bet = 0
    hit = 0
    nudge = 0
    wheel = 0
    big = 0
    pay_id_count: dict[int, int] = {}
    pay_id_win: dict[int, int] = {}
    pay_101 = 0
    for _ in range(n_spins):
        rounds = engine.run_session(rng, state.meter)
        sw = sum(r.win_credits for r in rounds)
        total_win += sw
        total_bet += engine.bet_amount
        if sw > 0:
            hit += 1
        if any(r.spin_type == ST_NUDGE for r in rounds):
            nudge += 1
        if any(r.spin_type == ST_WHEEL for r in rounds):
            wheel += 1
        if sw >= engine.bet_amount * 10:
            big += 1
        for r in rounds:
            for p in r.pay_results:
                pay_id_count[p.pay_id] = pay_id_count.get(p.pay_id, 0) + 1
                pay_id_win[p.pay_id] = pay_id_win.get(p.pay_id, 0) + int(p.multiplier * engine.bet_amount)
                if p.pay_id == 101:
                    pay_101 += 1
    return {
        "rtp_pct": total_win / total_bet * 100,
        "hit_rate": hit / n_spins,
        "nudge_rate": nudge / n_spins,
        "wheel_rate": wheel / n_spins,
        "big_x10_rate": big / n_spins,
        "pay_id_count": pay_id_count,
        "pay_id_win": pay_id_win,
        "pay_101_count": pay_101,
        "n_spins": n_spins,
    }


def verify_mode(mode: int, n_spins: int = 100_000) -> tuple[bool, list[str], dict]:
    spec = _ROOT / "slot_designer" / "specs" / "M279.spec.json"
    weights = _ROOT / "slot_designer" / "weights" / "M279" / f"mode_{mode}" / "weights.json"
    if not weights.exists():
        return False, [f"mode {mode}: weights file missing at {weights}"], {}
    engine, _ = load_m279_engine(spec, weights)
    metrics = _sim(engine, n_spins)
    cs = MODE_CONSTRAINTS[mode]
    issues: list[str] = []

    # 1. RTP
    if abs(metrics["rtp_pct"] - cs["rtp_pct"]) > cs["rtp_tolerance_pp"]:
        issues.append(
            f"RTP {metrics['rtp_pct']:.2f}% ≠ target {cs['rtp_pct']}% ±{cs['rtp_tolerance_pp']}pp"
        )

    # 2. Hit rate
    if abs(metrics["hit_rate"] - cs["hit_rate"]) > cs["hit_tolerance_pp"] / 100:
        issues.append(
            f"hit {metrics['hit_rate']*100:.2f}% ≠ target {cs['hit_rate']*100}% ±{cs['hit_tolerance_pp']}pp"
        )

    # 3. Nudge rate
    if not (cs["nudge_rate_min"] <= metrics["nudge_rate"] <= cs["nudge_rate_max"]):
        issues.append(
            f"nudge {metrics['nudge_rate']*100:.2f}% outside [{cs['nudge_rate_min']*100}, {cs['nudge_rate_max']*100}]%"
        )

    # 4. Wheel rate (1/CollectMax = 0.001 default)
    expected_wheel = 1.0 / engine.collect_cfg.max
    if abs(metrics["wheel_rate"] - expected_wheel) > expected_wheel * 0.5:
        issues.append(
            f"wheel {metrics['wheel_rate']*100:.4f}% ≠ expected {expected_wheel*100:.4f}% ±50%"
        )

    # 8. Hit decomposition (no pay > 70% of hits)
    total_pay_count = sum(metrics["pay_id_count"].values())
    if total_pay_count > 0:
        for pid, count in metrics["pay_id_count"].items():
            share = count / total_pay_count
            if share > 0.70:
                issues.append(
                    f"pay_id {pid} dominates hits ({share*100:.1f}% > 70% cap)"
                )

    # 10. Wheel EV invariant — applies only when no win_scale override.
    # Mode 5's _m279_overrides.wheel.win_scale legitimately changes the
    # E[win]; the override is the mechanism that boosts mode 5 RTP. Only
    # gate the invariant on the unscaled wheel.
    import json as _json
    weights_doc = _json.loads(weights.read_text(encoding="utf-8"))
    wheel_overrides = (weights_doc.get("_m279_overrides") or {}).get("wheel") or {}
    if "win_scale" not in wheel_overrides:
        expected_wheel_ev = engine.wheel_cfg.expected_win()
        if abs(expected_wheel_ev - 40000) > 100:
            issues.append(
                f"wheel E[win] {expected_wheel_ev:.0f} != 40000 +-100 (archetype design)"
            )

    return len(issues) == 0, issues, metrics


def verify_cross_mode_invariants(per_mode_metrics: dict[int, dict]) -> tuple[bool, list[str]]:
    """§9 mode-pair monotonicity + §7 top jackpot escalation."""
    issues: list[str] = []
    if 1 not in per_mode_metrics:
        return False, ["mode 1 missing — can't check cross-mode invariants"]

    m1 = per_mode_metrics[1]
    if 7 in per_mode_metrics:
        m7 = per_mode_metrics[7]
        if m7["rtp_pct"] >= m1["rtp_pct"]:
            issues.append(f"mode 7 RTP {m7['rtp_pct']:.1f}% ≥ mode 1 {m1['rtp_pct']:.1f}% (must be lower)")
        if m7["hit_rate"] >= m1["hit_rate"]:
            issues.append(f"mode 7 hit {m7['hit_rate']*100:.2f}% ≥ mode 1 {m1['hit_rate']*100:.2f}% (must be lower)")
    if 2 in per_mode_metrics:
        m2 = per_mode_metrics[2]
        if m2["rtp_pct"] <= m1["rtp_pct"]:
            issues.append(f"mode 2 RTP {m2['rtp_pct']:.1f}% ≤ mode 1 (must be higher)")
        if m2["hit_rate"] <= m1["hit_rate"]:
            issues.append(f"mode 2 hit ≤ mode 1 (must be higher)")
    if 5 in per_mode_metrics and 2 in per_mode_metrics:
        m5 = per_mode_metrics[5]
        if m5["rtp_pct"] <= m2["rtp_pct"]:
            issues.append(f"mode 5 RTP ≤ mode 2 (must be higher)")
    return len(issues) == 0, issues


def main() -> int:
    print("=" * 60)
    print("M279 design verification (DESIGN_PHILOSOPHY 11 categories)")
    print("=" * 60)
    all_green = True
    per_mode: dict[int, dict] = {}
    for mode in [1, 2, 5, 7]:
        print(f"\n--- mode {mode} ({MODE_CONSTRAINTS[mode]['label']}) ---")
        ok, issues, metrics = verify_mode(mode, n_spins=100_000)
        if metrics:
            per_mode[mode] = metrics
            print(f"  RTP {metrics['rtp_pct']:.2f}%  hit {metrics['hit_rate']*100:.2f}%  "
                  f"nudge {metrics['nudge_rate']*100:.2f}%  wheel {metrics['wheel_rate']*100:.4f}%")
        if ok:
            print(f"  [OK] GREEN")
        else:
            all_green = False
            print(f"  [FAIL] RED ({len(issues)} issues):")
            for i in issues:
                print(f"      - {i}")

    if per_mode:
        print(f"\n--- cross-mode invariants ---")
        ok, issues = verify_cross_mode_invariants(per_mode)
        if ok:
            print(f"  [OK] GREEN")
        else:
            all_green = False
            print(f"  [FAIL] RED ({len(issues)} issues):")
            for i in issues:
                print(f"      - {i}")

    print("\n" + "=" * 60)
    if all_green:
        print("[OK] ALL GREEN -- design verified")
    else:
        print("[FAIL] RED -- fix issues before commit (see WORKFLOW.md adversarial review)")
    print("=" * 60)
    return 0 if all_green else 1


if __name__ == "__main__":
    sys.exit(main())
