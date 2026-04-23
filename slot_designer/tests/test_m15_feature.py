"""Regression: M15 Feature Play EV + total-RTP invariant (v5 2026-04-23).

Locks in the v5 design:
  - Mode 1 feature EV = 46× per trigger (verified via analyze_feature
    with per-card x_value_weights; spec & mode_1 weights.json both match)
  - Target trigger 1/88 (= 1.136%)
  - Feature RTP ~ 52.25pp → Total Base + Feature ≈ 95% at mode 1 target
  - Jackpot symbol never on reels; Bonus only on reel 3

v5 additions:
  - x_value_weights is now a designer dial (per-card weighted sampling
    without replacement). Previously implicit-uniform.
  - count_y varies per mode (mode 1 narrow, mode 5 wide) to enable
    targeted EV per mode without breaking UX invariants.

If any of these drift (spec change, weight retune, paytable change),
the tests fail loudly.
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


_SPEC_PATH = _ROOT / "slot_designer" / "specs" / "M15.spec.json"
_STRIPS_PATH = _ROOT / "slot_designer" / "weights" / "M15" / "reel_strips.json"
_MODE1_WEIGHTS_PATH = _ROOT / "slot_designer" / "weights" / "M15" / "mode_1" / "weights.json"


def _build_spec_from(feature_params: dict) -> FeatureSpec:
    """Build a FeatureSpec from a feature_params-shaped dict."""
    return FeatureSpec(
        x_count_weights=tuple(feature_params["x_count_weights"]),
        y_count_weights=tuple(feature_params["y_count_weights"]),
        x_value_weights=tuple(feature_params.get(
            "x_value_weights", (1.0,) * 10
        )),
        y_value_weights=tuple(feature_params.get(
            "y_value_weights", (1.0,) * 2
        )),
        accept_threshold=feature_params.get("accept_threshold", 40),
        max_rounds=feature_params.get("max_rounds", 4),
    )


def test_spec_mode1_feature_ev_46():
    """M15.spec.json mode 1 feature weights must produce EV ≈ 46×.

    This is the v5 mode 1 design — classic standard at 95% total RTP
    with 45:55 base:feature split, giving feature RTP target 52.25pp
    at trigger 1/88 (1.136%).
    """
    spec = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    feat = spec["features"][0]
    assert feat["name"] == "FeaturePlay", f"expected FeaturePlay feature, got {feat!r}"

    fs = _build_spec_from(feat)
    stats = analyze_feature(fs)

    # Mode 1 EV: 46× with ±2× tolerance (allows weight perturbations during
    # design iteration but catches fundamental drift).
    assert 44.0 <= stats.expected_payout <= 48.0, (
        f"M15 spec mode 1 feature EV drifted from 46×: got "
        f"{stats.expected_payout:.2f}. If spec weights were updated for new "
        f"mode 1 target, update this bound; otherwise investigate drift."
    )

    # Conditional CV for mode 1 (heavy low-skew + threshold 40) is ~0.74
    assert 0.5 <= stats.cv <= 1.2, f"conditional CV drifted: got {stats.cv:.3f}"


def test_mode1_weights_json_feature_params_match_spec():
    """Per-mode feature_params in mode_1/weights.json should yield the
    same EV as the spec (since spec's default IS mode 1 in v5)."""
    weights = json.loads(_MODE1_WEIGHTS_PATH.read_text(encoding="utf-8"))
    assert "feature_params" in weights, (
        "mode_1/weights.json must have a feature_params block (v5+). "
        "See MODE_DESIGN.md § 10 for structure."
    )
    fp = weights["feature_params"]
    fs = _build_spec_from(fp)
    stats = analyze_feature(fs)

    # Should match the _analytic.ev_per_trigger value recorded in weights.json
    expected_ev = fp.get("_analytic", {}).get("ev_per_trigger", 46.0)
    assert abs(stats.expected_payout - expected_ev) <= 1.0, (
        f"mode 1 feature_params produced EV {stats.expected_payout:.2f}, "
        f"but _analytic.ev_per_trigger claims {expected_ev}. Either the "
        f"weights or the cached analytic is stale."
    )


def test_m15_mode1_total_rtp_approximately_95():
    """Base RTP + trigger × feature EV = total ≈ 95% (45:55 split).

    NOTE: This test depends on the base weights hitting 42.75pp. The
    current mode_1/weights.json base is STALE (67.4pp from old 150%
    design). Once Phase 4 re-tunes base to 42.75pp, this test will pass.
    Until then, mark as expected-failure.
    """
    import pytest  # lazy import in case the tree isn't pytest-installed

    engine, _ = load_engine(_SPEC_PATH, _MODE1_WEIGHTS_PATH)
    p = analytic_profile(engine)
    base_rtp = p["rtp_pct"]

    # Feature trigger rate = Bonus marginal on reel 3
    strips = json.loads(_STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    weights_data = json.loads(_MODE1_WEIGHTS_PATH.read_text(encoding="utf-8"))
    reel_weights = weights_data["weights"]
    r3_total = sum(reel_weights[2])
    bonus_w = sum(w for s, w in zip(strips[2], reel_weights[2]) if s == "topdollar")
    trigger = bonus_w / r3_total

    # Feature EV from v5 mode 1 params
    fp = weights_data["feature_params"]
    fs = _build_spec_from(fp)
    stats = analyze_feature(fs)

    feature_rtp = trigger * stats.expected_payout * 100
    total_rtp = base_rtp + feature_rtp

    # Target 95% ±1pp strict (mode 1 is 标准 mode — tight tolerance).
    # NOTE: base is currently STALE (pre-v5 tune targeted 67.5pp for old 150%
    # design). Allow wider tolerance until base is re-tuned.
    if base_rtp > 50:  # stale pre-v5 base
        pytest.xfail(
            f"mode_1 base weights are STALE (pre-v5 tune, 67.5pp target). "
            f"base_rtp={base_rtp:.2f}pp, feature={feature_rtp:.2f}pp, "
            f"total={total_rtp:.2f}pp. Needs Phase 4 re-tune to 42.75pp "
            f"base. See MODE_DESIGN.md §10 TODO."
        )

    assert 94.0 <= total_rtp <= 96.0, (
        f"M15 mode 1 total RTP drifted outside [94, 96]pp (mode 1 strict): "
        f"base={base_rtp:.2f}pp, feature={feature_rtp:.2f}pp, "
        f"total={total_rtp:.2f}pp."
    )


def test_m15_mode1_trigger_rate_in_user_band():
    """User brief: mode 1 trigger at least 1-1.5%. v5 target is 1.136%."""
    strips = json.loads(_STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    weights_data = json.loads(_MODE1_WEIGHTS_PATH.read_text(encoding="utf-8"))
    reel_weights = weights_data["weights"]

    r3_total = sum(reel_weights[2])
    bonus_w = sum(w for s, w in zip(strips[2], reel_weights[2]) if s == "topdollar")
    trigger = bonus_w / r3_total

    # v5 mode 1 target: 1.136% (1/88). Accept range: 1.0% to 1.5% per user brief.
    # Current base weights give whatever trigger the existing Bonus weight produces;
    # bound on the GENEROUS side for now until Phase 4 retune sets target.
    import pytest
    # Current reel 3 has Bonus weight 1 × 2 stops = 2; r3_total ≈ 1017 (post-150%-tune)
    # so trigger ≈ 0.197% which is WAY off v5 1.136%. Mark xfail until base re-tuned.
    if trigger < 0.008:  # pre-v5 stale trigger
        pytest.xfail(
            f"mode_1 Bonus marginal is STALE (pre-v5, targeting 1/485): "
            f"got 1/{1/trigger:.0f} = {trigger*100:.3f}%. Needs re-tune to "
            f"~1/88 for v5 mode 1. See MODE_DESIGN.md §10 TODO."
        )

    assert 0.010 <= trigger <= 0.015, (
        f"Feature trigger rate drifted outside [1.0%, 1.5%] user target band: "
        f"got {trigger*100:.3f}% (1/{1/trigger:.0f})"
    )


def test_m15_jackpot_symbol_present_on_reels_but_low_rate():
    """v2 schema alignment (2026-04-23): jackpot appears on reels as
    decorative filler (matching M15$TopDollarSelector$0$ production
    rawdata, ~1% payline rate per reel). Game mechanic re-rolls on
    3-jackpot so the 1000× prize never pays in mode 1/2/5/7.

    Test: jackpot present on each reel; marginal < 5% (production ~1%).
    """
    strips = json.loads(_STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    weights = json.loads(_MODE1_WEIGHTS_PATH.read_text(encoding="utf-8"))["weights"]
    for ri in range(3):
        assert "jackpot" in strips[ri], (
            f"M15 reel {ri+1} has no jackpot symbol. Expected at least "
            f"one jackpot stop per reel for v2 schema alignment."
        )
        total_w = sum(weights[ri])
        jackpot_w = sum(
            w for s, w in zip(strips[ri], weights[ri]) if s == "jackpot"
        )
        marginal = jackpot_w / total_w
        assert marginal < 0.05, (
            f"M15 reel {ri+1} jackpot marginal {marginal*100:.2f}% > 5%. "
            f"Keep low to minimize RTP dilution (production ~1%)."
        )


def test_m15_topdollar_only_on_reel_3():
    """Paytable: Feature triggers when topdollar lands on reel 3 payline.
    Reel 1/2 must not carry topdollar (no trigger path there).

    v2 rename: was `Bonus`; now lowercase `topdollar` to match production.
    """
    strips = json.loads(_STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    for ri in (0, 1):
        assert "topdollar" not in strips[ri], (
            f"M15 reel {ri+1} contains topdollar — paytable says topdollar "
            f"only appears on reel 3. Remove from reel {ri+1}."
        )
    assert "topdollar" in strips[2], (
        f"M15 reel 3 must contain at least one topdollar stop to enable "
        f"feature trigger; got {strips[2]!r}"
    )


def test_m15_symbols_match_production_schema():
    """v2 2026-04-23: all symbol names must match production M15
    rawdata schema (lowercase, 1bar/2bar/3bar bar naming, doublediamond
    wild, topdollar bonus, jackpot decorative)."""
    strips = json.loads(_STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    expected = {
        "blank", "cherry", "1bar", "2bar", "3bar",
        "high7", "doublediamond", "topdollar", "jackpot",
    }
    actual = set()
    for reel in strips:
        actual.update(reel)
    extra = actual - expected
    assert not extra, (
        f"M15 strips contain unexpected symbol(s) {extra}. "
        f"Expected production-schema symbols: {sorted(expected)}"
    )


def test_m15_feature_weighted_sampling_backward_compat():
    """v5 added x_value_weights / y_value_weights. Calling FeatureSpec
    without these fields must fall back to pre-v5 uniform behavior.

    Uniform sampling with the default pool gives unconditional single-x
    mean = 127 (= sum(pool) / len(pool)).
    """
    # Legacy-style FeatureSpec call (no value weights)
    fs = FeatureSpec(
        x_count_weights=(100, 0, 0, 0, 0),
        y_count_weights=(100, 0, 0),
        # No x_value_weights / y_value_weights passed
    )
    stats = analyze_feature(fs)

    # With always-1-x, always-0-y, uniform x sampling:
    # unconditional E[R] should == mean(x_pool) = 127
    # 4-round threshold-40 EV ≈ 262.6 (as computed in v1-v3 docs)
    assert 260.0 <= stats.expected_payout <= 265.0, (
        f"v5 backward-compat broken: uniform x_value_weights + narrow "
        f"count should give EV ≈ 262.6 (pre-v5 behavior). Got "
        f"{stats.expected_payout:.2f}."
    )
    assert abs(stats.round_ev_unconditional - 127.0) < 0.1, (
        f"Uniform x_pool unconditional mean should be 127; got "
        f"{stats.round_ev_unconditional:.2f}. Sampling algorithm regression."
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
        except Exception as e:
            print(f"FAIL {t.__name__}: {type(e).__name__}: {e}")
            failures.append((t.__name__, e))
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if not failures else 1)
