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

    Mode 1 is the reference / archetype — strict ±1pp tolerance per
    project_slot_designer_mode_rtp_invariants.md.
    """
    engine, _ = load_engine(_SPEC_PATH, _MODE1_WEIGHTS_PATH)
    p = analytic_profile(engine)
    base_rtp = p["rtp_pct"]

    # Feature trigger rate = topdollar marginal on reel 3
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

    assert 94.0 <= total_rtp <= 96.0, (
        f"M15 mode 1 total RTP drifted outside [94, 96]pp (mode 1 strict): "
        f"base={base_rtp:.2f}pp, feature={feature_rtp:.2f}pp, "
        f"total={total_rtp:.2f}pp."
    )


def test_m15_mode1_trigger_rate_in_user_band():
    """User brief: mode 1 trigger at least 1-1.5%. v5+ target is 1.136% (1/88)."""
    strips = json.loads(_STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    weights_data = json.loads(_MODE1_WEIGHTS_PATH.read_text(encoding="utf-8"))
    reel_weights = weights_data["weights"]

    r3_total = sum(reel_weights[2])
    bonus_w = sum(w for s, w in zip(strips[2], reel_weights[2]) if s == "topdollar")
    trigger = bonus_w / r3_total

    # v5+ mode 1 target: 1.136% (1/88). Accept range: 1.0% to 1.5% per user brief.
    assert 0.010 <= trigger <= 0.015, (
        f"Feature trigger rate drifted outside [1.0%, 1.5%] user target band: "
        f"got {trigger*100:.3f}% (1/{1/trigger:.0f})"
    )


def test_m15_mode1_hit_rate_in_reference_band():
    """Mode 1 is the hit-rate reference for deriving mode 2/5/7 bands
    (see project_slot_designer_hit_rate_deviation.md). Pin mode 1 at
    ~13% so the other modes' derived bands stay anchored.
    """
    engine, _ = load_engine(_SPEC_PATH, _MODE1_WEIGHTS_PATH)
    p = analytic_profile(engine)
    hit_rate = p["hit_rate"]
    assert 0.12 <= hit_rate <= 0.15, (
        f"mode 1 base hit_rate drifted outside reference band [12, 15]%: "
        f"got {hit_rate*100:.2f}%. Other modes derive their hit-rate bands "
        f"from mode 1's anchor; re-tune to restore before shipping."
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


# ─────────────────────────────────────────────────────────────
# v6 2026-04-24: per-mode RTP + hit + trigger regression.
# Before v6 shipped, only mode 1 had a locked numeric test. Modes 2/5/7
# went through retune cycles without numeric guard rails — catching
# design drift required running ad-hoc analytic verification scripts.
# These tests pin the current design targets so any weight / feature_params
# / strip edit that breaks a mode's RTP / hit / trigger contract shows up
# in CI.
# ─────────────────────────────────────────────────────────────


def _mode_metrics(mode: int) -> dict:
    """Compute (base_rtp, hit_rate, trigger_rate, feature_ev, feature_rtp, total)
    for a given M15 mode. Pure analytic — no simulation.
    """
    w_path = _ROOT / "slot_designer" / "weights" / "M15" / f"mode_{mode}" / "weights.json"
    doc = json.loads(w_path.read_text(encoding="utf-8"))
    engine, _ = load_engine(_SPEC_PATH, w_path)
    base = analytic_profile(engine)

    # trigger rate from reel 3 topdollar marginal
    strips = json.loads(_STRIPS_PATH.read_text(encoding="utf-8"))["reels"]
    td = sum(float(w) for s, w in zip(strips[2], doc["weights"][2]) if s == "topdollar")
    tot = sum(float(w) for w in doc["weights"][2])
    trigger = td / tot if tot else 0.0

    fp = doc["feature_params"]
    fs = _build_spec_from(fp)
    fstats = analyze_feature(fs)

    feature_rtp = 100.0 * trigger * fstats.expected_payout
    return {
        "base_rtp": base["rtp_pct"],
        "hit_rate": base["hit_rate"],
        "trigger": trigger,
        "feature_ev": fstats.expected_payout,
        "feature_rtp": feature_rtp,
        "total_rtp": base["rtp_pct"] + feature_rtp,
    }


def test_m15_mode2_rtp_hit_trigger_match_v6_design():
    """Mode 2 v6 shipped targets (MODE_DESIGN.md §5 + §8):
      * Total RTP 300% ±20pp (lucky mode — loose tolerance)
      * Base hit 22.5% ±2.5pp (per project_slot_designer_hit_rate_deviation.md
        user-specified 20-25% band — explicitly NOT ×3.16 from mode 1)
      * Trigger 2.75% ±0.5pp (1/36 — 2.4× mode 1)
      * Feature EV 60× ±3× (1.30× mode 1, within ≤1.5× brief cap)
    """
    m = _mode_metrics(2)
    assert 280.0 <= m["total_rtp"] <= 320.0, (
        f"mode 2 total RTP outside [280, 320]pp: got {m['total_rtp']:.2f}"
    )
    assert 0.20 <= m["hit_rate"] <= 0.25, (
        f"mode 2 base hit_rate outside [20%, 25%] user band: got "
        f"{m['hit_rate']*100:.2f}%. Hit rate is a DESIGN CONSTRAINT, not a "
        f"free variable — see project_slot_designer_hit_rate_deviation.md."
    )
    assert 0.022 <= m["trigger"] <= 0.033, (
        f"mode 2 trigger outside [2.2%, 3.3%]: got {m['trigger']*100:.3f}%"
    )
    assert 57.0 <= m["feature_ev"] <= 63.0, (
        f"mode 2 feature EV drifted from 60×: got {m['feature_ev']:.2f}"
    )


def test_m15_mode7_rtp_hit_trigger_match_v6_design():
    """Mode 7 v6 shipped targets (MODE_DESIGN.md §4 + §8):
      * Total RTP 85% ±1pp (standard-low — STRICT tolerance)
      * Base hit 12.5% ±0.5pp (per hit-rate deviation rule, must stay
        near mode 1's 13% anchor; RTP delta goes into per-hit avg,
        not hit frequency. 12-13% band per user spec.)
      * Trigger 1.136% ±0.1pp (IDENTICAL to mode 1 by design)
      * Feature EV 46× ±2× (feature_params byte-copied from mode 1)

    Catches:
      (a) regression to v5 direct-scale (would hit 7.5% hit, fail hit band)
      (b) feature_params drift from mode 1 (would fail EV band)
      (c) trigger drift from reel 3 rebalance forgetting to pin topdollar
    """
    m = _mode_metrics(7)
    assert 84.0 <= m["total_rtp"] <= 86.0, (
        f"mode 7 total RTP outside STRICT [84, 86]pp: got {m['total_rtp']:.2f}"
    )
    assert 0.120 <= m["hit_rate"] <= 0.130, (
        f"mode 7 base hit_rate outside user-band [12%, 13%]: got "
        f"{m['hit_rate']*100:.2f}%. Direct-scale v5 would hit ~7.5% here; "
        f"if failing with ~7%, you regressed to v5 path — use Phase 4 tune "
        f"with --hit-target 0.125 instead. See MODE_DESIGN.md §4.2 v6."
    )
    assert 0.0108 <= m["trigger"] <= 0.0118, (
        f"mode 7 trigger drifted from mode 1's 1.136%: got "
        f"{m['trigger']*100:.3f}%. Feature RTP depends on this being "
        f"IDENTICAL to mode 1 ('feature 100% same as mode 1' design brief)."
    )
    assert 44.0 <= m["feature_ev"] <= 48.0, (
        f"mode 7 feature EV drifted from 46× (= mode 1 byte-identical): "
        f"got {m['feature_ev']:.2f}. feature_params must be byte-identical "
        f"to mode 1's."
    )


def test_m15_mode5_is_mode2_base_byte_identical():
    """Mode 5 design (MODE_DESIGN.md §6): base weights IDENTICAL to mode 2.
    Differentiation lives entirely in feature_params (EV 132× vs 60×).

    Verifies:
      (a) mode 5 weights array == mode 2 weights array byte-for-byte
      (b) mode 5 trigger rate == mode 2 trigger rate (derived from same reel 3)
      (c) mode 5 base hit == mode 2 base hit (derived from same marginals)
      (d) mode 5 feature EV ≈ 132× (enhanced from mode 2's 60×)
      (e) mode 5 total RTP 500% ±20pp
    """
    m2 = _mode_metrics(2)
    m5 = _mode_metrics(5)

    m2_weights = json.loads(
        (_ROOT / "slot_designer" / "weights" / "M15" / "mode_2" / "weights.json")
        .read_text(encoding="utf-8")
    )["weights"]
    m5_weights = json.loads(
        (_ROOT / "slot_designer" / "weights" / "M15" / "mode_5" / "weights.json")
        .read_text(encoding="utf-8")
    )["weights"]

    assert m2_weights == m5_weights, (
        f"mode 5 base weights must be byte-identical to mode 2 — "
        f"per MODE_DESIGN.md §6 design brief. Differ at reel(s): "
        + ", ".join(
            str(i+1) for i, (r2, r5) in enumerate(zip(m2_weights, m5_weights))
            if r2 != r5
        )
    )
    assert abs(m5["trigger"] - m2["trigger"]) < 1e-9, (
        f"mode 5 trigger must equal mode 2 trigger (same base weights): "
        f"m2={m2['trigger']:.6f} m5={m5['trigger']:.6f}"
    )
    assert abs(m5["hit_rate"] - m2["hit_rate"]) < 1e-9, (
        f"mode 5 hit_rate must equal mode 2 hit_rate (same base weights): "
        f"m2={m2['hit_rate']:.6f} m5={m5['hit_rate']:.6f}"
    )
    assert 125.0 <= m5["feature_ev"] <= 140.0, (
        f"mode 5 feature EV drifted from 132×: got {m5['feature_ev']:.2f}. "
        f"feature_params must give EV ≈2.2× mode 2's 60× per §6."
    )
    assert 480.0 <= m5["total_rtp"] <= 520.0, (
        f"mode 5 total RTP outside [480, 520]pp: got {m5['total_rtp']:.2f}"
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
