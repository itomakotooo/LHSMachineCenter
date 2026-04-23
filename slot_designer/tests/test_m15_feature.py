"""Regression: M15 Feature Play EV + total-RTP invariant.

Locks in the 2026-04-23 design:
  - Feature conditional EV matches spec's declared weights
  - Shipped M15 mode 1 base game + feature combine to ≈150% total RTP
  - Base:Feature split ≈ 45:55
  - Trigger rate ≈ 1/500 (Bonus weight per reel 3 marginal)

If any of these drift (spec change, weight retune, trigger rate shift),
the tests fail loudly so the operator knows the designed invariants
broke.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.engine.feature_m15 import FeatureSpec, analyze_feature
from slot_designer.engine.loader import load_engine
from slot_designer.devtools.analytic_rtp import analytic_profile


def test_feature_ev_matches_spec_weights():
    """Re-run EV calc against the spec-declared weights; expected 400×
    per trigger under (70,25,5,0,0)/(70,25,5) + threshold 40 + 4 rounds."""
    spec_path = _ROOT / "slot_designer" / "specs" / "M15.spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    feat = spec["features"][0]
    assert feat["name"] == "FeaturePlay", f"expected FeaturePlay feature, got {feat!r}"

    fs = FeatureSpec(
        x_count_weights=tuple(feat["x_count_weights"]),
        y_count_weights=tuple(feat["y_count_weights"]),
        accept_threshold=feat["accept_threshold"],
        max_rounds=feat["max_rounds"],
    )
    stats = analyze_feature(fs)

    # Spec-locked EV: 400 ± 5 (rounding + sensitivity to weight changes)
    assert 395.0 <= stats.expected_payout <= 405.0, (
        f"Feature EV drifted from 400× under spec weights: got "
        f"{stats.expected_payout:.2f}. If spec weights changed, update "
        f"this bound; otherwise investigate feature_m15.analyze_feature."
    )
    # Conditional CV ~ 1.67 for these weights
    assert 1.5 <= stats.cv <= 2.0, f"CV drifted: got {stats.cv:.3f}"


def test_m15_mode1_total_rtp_approximately_150():
    """Base RTP + trigger × feature EV = total ≈ 150% (45:55 split)."""
    spec_path = _ROOT / "slot_designer" / "specs" / "M15.spec.json"
    weights_path = _ROOT / "slot_designer" / "weights" / "M15" / "mode_1" / "weights.json"
    strips_path = _ROOT / "slot_designer" / "weights" / "M15" / "reel_strips.json"

    # Base RTP
    engine, _ = load_engine(spec_path, weights_path)
    p = analytic_profile(engine)
    base_rtp = p["rtp_pct"]

    # Feature trigger rate = Bonus marginal on reel 3
    strips = json.loads(strips_path.read_text(encoding="utf-8"))["reels"]
    weights = json.loads(weights_path.read_text(encoding="utf-8"))["weights"]
    r3_total = sum(weights[2])
    bonus_w = sum(w for s, w in zip(strips[2], weights[2]) if s == "Bonus")
    trigger = bonus_w / r3_total

    # Feature EV
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    feat = spec["features"][0]
    fs = FeatureSpec(
        x_count_weights=tuple(feat["x_count_weights"]),
        y_count_weights=tuple(feat["y_count_weights"]),
        accept_threshold=feat["accept_threshold"],
        max_rounds=feat["max_rounds"],
    )
    stats = analyze_feature(fs)

    feature_rtp = trigger * stats.expected_payout * 100  # pp per paid spin
    total_rtp = base_rtp + feature_rtp

    # User brief: total 150% target, 45:55 split. Allow ±5pp for tune
    # drift / rounding.
    assert 145.0 <= total_rtp <= 155.0, (
        f"M15 mode 1 total RTP drifted outside [145, 155]pp target band: "
        f"base={base_rtp:.2f}pp, feature={feature_rtp:.2f}pp, "
        f"total={total_rtp:.2f}pp. Retune base or adjust feature "
        f"trigger rate."
    )

    split_base = base_rtp / total_rtp
    split_feature = feature_rtp / total_rtp
    assert 0.40 <= split_base <= 0.50, (
        f"base share drifted from 45%: got {split_base*100:.1f}% "
        f"(base={base_rtp:.2f}pp, total={total_rtp:.2f}pp)"
    )
    assert 0.50 <= split_feature <= 0.60, (
        f"feature share drifted from 55%: got {split_feature*100:.1f}% "
        f"(feature={feature_rtp:.2f}pp, total={total_rtp:.2f}pp)"
    )


def test_m15_trigger_rate_low_frequency():
    """Bonus on reel 3 must land near 1/500 spins. If this drifts,
    the feature RTP contribution will overshoot (trigger too common)
    or undershoot (trigger too rare)."""
    strips_path = _ROOT / "slot_designer" / "weights" / "M15" / "reel_strips.json"
    weights_path = _ROOT / "slot_designer" / "weights" / "M15" / "mode_1" / "weights.json"
    strips = json.loads(strips_path.read_text(encoding="utf-8"))["reels"]
    weights = json.loads(weights_path.read_text(encoding="utf-8"))["weights"]

    r3_total = sum(weights[2])
    bonus_w = sum(w for s, w in zip(strips[2], weights[2]) if s == "Bonus")
    trigger = bonus_w / r3_total

    # Target 1/485, tolerance 1/350 - 1/650
    assert 1 / 650 <= trigger <= 1 / 350, (
        f"Feature trigger rate drifted outside target band [1/650, 1/350]: "
        f"got 1/{1/trigger:.0f} (Bonus weight {bonus_w} / reel-3 total {r3_total})"
    )


def test_m15_jackpot_symbol_never_on_reels():
    """Paytable: Jackpot 不可随机转出. If any reel picks up Jackpot
    (e.g. operator error or stale weights file), probability of
    3 Jackpot becomes non-zero and rtp_excluded guard silently drops
    it — invisible bug. Better to fail loudly at the reel-layout level."""
    strips_path = _ROOT / "slot_designer" / "weights" / "M15" / "reel_strips.json"
    strips = json.loads(strips_path.read_text(encoding="utf-8"))["reels"]
    for ri, reel in enumerate(strips):
        assert "Jackpot" not in reel, (
            f"M15 reel {ri+1} contains Jackpot — paytable says Jackpot "
            f"is 不可随机转出 (system-forced only). Jackpot must not appear "
            f"on random-spin reels. Remove it from reel_strips.json."
        )


def test_m15_bonus_only_on_reel_3():
    """Paytable: Feature triggers when Bonus shows on reel 3. Reel 1/2
    must not carry Bonus (no trigger path there)."""
    strips_path = _ROOT / "slot_designer" / "weights" / "M15" / "reel_strips.json"
    strips = json.loads(strips_path.read_text(encoding="utf-8"))["reels"]
    for ri in (0, 1):
        assert "Bonus" not in strips[ri], (
            f"M15 reel {ri+1} contains Bonus — paytable says Bonus only "
            f"appears on reel 3 (the feature trigger). Remove Bonus from "
            f"reel {ri+1} in reel_strips.json."
        )
    assert "Bonus" in strips[2], (
        f"M15 reel 3 must contain at least one Bonus stop to enable "
        f"feature trigger; got {strips[2]!r}"
    )


if __name__ == "__main__":
    import inspect
    mod = sys.modules[__name__]
    tests = [o for n, o in inspect.getmembers(mod) if n.startswith("test_") and callable(o)]
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
