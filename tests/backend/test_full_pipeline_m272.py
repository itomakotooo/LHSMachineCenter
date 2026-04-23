"""Full-pipeline regression test against the M272 mode 1 fixture.

This test runs the COMPLETE analyzer main() — from chunk sampling
through aggregation through summary build — against a saved raw API
response fixture. The HTTP call is monkey-patched so no network access
is needed.

Baseline values were pre-computed from the same fixture on 2026-04-16
and hardcoded here. If any analyzer refactor silently changes the
output (e.g. the RTP-denominator bug from the eq0 drop), this test
fails with an immediately diagnostic message.

Unlike test_fixture_m272.py (which only exercises a single chunk
through run_sampling_chunk), this test locks the end-to-end contract:
raw API response → full main() → summary.json → metrics match.

If you change the fixture, re-run the baseline computation script
at the bottom of this file to update BASELINE.
"""
from __future__ import annotations

import json
import sys
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "m272_mode1_r8_s50.json"

# Pre-computed from the same fixture via the full pipeline on 2026-04-16.
# Update these if you intentionally change summary semantics.
BASELINE = {
    "rtp_point_pct": 83.3125,
    "paid_spins": 400,
    "bonus_spins": 46,
    "total_spins": 446,
    "upstream_matches": True,
    "upstream_delta": 0.0,
    "tail_dep_ge10x": 0.6667066766691673,
    "tail_dep_ge50x": 0.5701425356339085,
    "volatility_class": "Very High",
    "experience_archetype": "Grindy",
    "spin_type_count": 2,
    "has_feature_breakdown": True,
    "has_bonus_chain": True,
    "eq0_in_buckets": False,
    "bucket_count": 11,
    "bucket_rtp_sum": 83.3125,
}


@pytest.fixture()
def run_full_pipeline(monkeypatch):
    """Run the full analyzer main() against the fixture and return
    the parsed summary dict."""
    fixture_data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))

    monkeypatch.setattr(
        "fresh_slotlab.player_impact_analyzer.post_json",
        lambda payload, timeout: fixture_data,
    )
    # Prevent os._exit from killing the test runner.
    monkeypatch.setattr("os._exit", lambda rc: None)

    with tempfile.TemporaryDirectory() as tmpdir:
        outdir = Path(tmpdir) / "output"
        outdir.mkdir()
        progress = Path(tmpdir) / "progress.jsonl"

        test_argv = [
            "analyzer",
            "--machine", "M272",
            "--rtp-mode", "1",
            "--bet", "1000",
            "--chunk-spin-times", "50",
            "--chunk-robot-count", "8",
            "--batch-concurrency", "1",
            "--max-chunks", "1",
            "--target-halfwidth-pp", "999",
            "--timeout", "30",
            "--output-dir", str(outdir),
            "--progress-file", str(progress),
            "--run-id", "regression_test",
            "--bankruptcy-session-spins", "100",
            "--bankruptcy-bankroll-multipliers", "100,200,500",
        ]

        monkeypatch.setattr(sys, "argv", test_argv)
        captured = StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        from fresh_slotlab.player_impact_analyzer import main
        rc = main()
        assert rc == 0, f"main() returned {rc}"

        summary_path = outdir / "player_impact_summary.json"
        assert summary_path.exists(), "summary.json was not written"
        return json.loads(summary_path.read_text(encoding="utf-8"))


# ---------- RTP correctness ----------

def test_rtp_matches_baseline(run_full_pipeline):
    """RTP must match baseline exactly (same input data = deterministic
    output). Any drift means the aggregation or denominator changed."""
    s = run_full_pipeline
    actual = s["rtp"]["point_pct"]
    expected = BASELINE["rtp_point_pct"]
    assert abs(actual - expected) < 0.001, (
        f"RTP drift: got {actual:.4f}%, baseline {expected:.4f}%"
    )


def test_bucket_rtp_sum_equals_rtp(run_full_pipeline):
    """Sum of per-bucket rtp_contribution_pp must equal rtp.point_pct.
    This is the invariant the eq0-denominator bug violated (sum was 5x
    the real RTP because zero-win session bets were excluded)."""
    s = run_full_pipeline
    buckets = s["player_impact"]["multiplier_profile"]["buckets"]
    bucket_sum = sum(b["rtp_contribution_pp"] for b in buckets)
    rtp = s["rtp"]["point_pct"]
    assert abs(bucket_sum - rtp) < 0.01, (
        f"bucket_rtp_sum={bucket_sum:.4f} != rtp={rtp:.4f}"
    )


def test_payout_ids_top20_rtp_sum_equals_summary_rtp(run_full_pipeline):
    """Iter 3 denominator unification (2026-04-23) on a bonus-heavy
    machine. M272 has both paid (SpinType 140) and bonus (SpinType
    126) rounds — denominator choice matters here. Before iter 3,
    payout rows used total_bet = (paid + bonus) × bet; summary.rtp
    uses paid-only. The sum(rtp_pp) lagged summary.rtp by the
    ratio paid / total. Now both use effective_bet_for_rtp and
    the sum converges exactly.

    This is the test the M14 fixture couldn't catch (M14 has
    bonus_spins=0, so total_bet == effective_bet_for_rtp, hiding
    the bug). M272's bonus-heavy fixture exercises the diff."""
    s = run_full_pipeline
    rows = s["player_impact"]["payout_ids_top20"]
    pay_sum_pp = sum(r.get("rtp_contribution_pp", 0.0) for r in rows)
    rtp = s["rtp"]["point_pct"]
    assert abs(pay_sum_pp - rtp) < 0.01, (
        f"payout_ids_top20 rtp_pp sum {pay_sum_pp:.4f} diverges "
        f"from summary.rtp {rtp:.4f} — denominator regression? "
        f"delta={rtp - pay_sum_pp:.4f}pp"
    )


# ---------- sampling / upstream ----------

def test_paid_bonus_spins_exact(run_full_pipeline):
    s = run_full_pipeline
    assert s["sampling"]["paid_spins"] == BASELINE["paid_spins"]
    assert s["sampling"]["bonus_spins"] == BASELINE["bonus_spins"]
    assert s["sampling"]["total_spins"] == BASELINE["total_spins"]


def test_upstream_cross_check(run_full_pipeline):
    s = run_full_pipeline
    ua = s["upstream_analysis"]
    assert ua["matches"] is True
    assert abs(ua["delta"]) < 1.0


# ---------- classification ----------

def test_volatility_and_archetype(run_full_pipeline):
    s = run_full_pipeline
    cls = s["guideline_assessment"]["classification"]
    assert cls["volatility_class"] == BASELINE["volatility_class"]
    assert cls["experience_archetype"] == BASELINE["experience_archetype"]


# ---------- tail dependency ----------

def test_tail_dependency_multi_threshold(run_full_pipeline):
    s = run_full_pipeline
    dm = s["guideline_assessment"]["derived_metrics"]
    assert abs(dm["tail_dependency_ge10x"] - BASELINE["tail_dep_ge10x"]) < 0.001
    assert abs(dm["tail_dependency_ge50x"] - BASELINE["tail_dep_ge50x"]) < 0.001
    # ge10x >= ge50x always (bigger threshold = less tail mass)
    assert dm["tail_dependency_ge10x"] >= dm["tail_dependency_ge50x"]
    assert dm["tail_dependency_ge50x"] >= dm["tail_dependency_ge100x"]


# ---------- output shape ----------

def test_eq0_not_in_output_buckets(run_full_pipeline):
    s = run_full_pipeline
    labels = [b["bucket"] for b in s["player_impact"]["multiplier_profile"]["buckets"]]
    assert "eq0" not in labels
    assert len(labels) == BASELINE["bucket_count"]


def test_spin_type_breakdown_shape(run_full_pipeline):
    s = run_full_pipeline
    st = s["player_impact"]["spin_type_breakdown"]
    assert len(st) == BASELINE["spin_type_count"]
    # First row = main (paid), second = bonus (free)
    if len(st) >= 2:
        assert st[0]["behavior_name"] == "paid"
        assert st[1]["behavior_name"] == "free"
        assert st[1]["rtp_pct"] is None, "free-spin type rtp_pct must be null"


def test_feature_breakdown_and_bonus_chain(run_full_pipeline):
    s = run_full_pipeline
    fb = s["player_impact"]["upstream_feature_breakdown"]
    bc = s["player_impact"]["bonus_chain_dynamics"]
    assert fb["applicable"] == BASELINE["has_feature_breakdown"]
    assert bc["applicable"] == BASELINE["has_bonus_chain"]
    if bc["applicable"]:
        assert bc["chain_count"] > 0
        assert bc["avg_chain_length"] > 1.0


def test_feature_breakdown_rows_have_chain_fields(run_full_pipeline):
    """Every feature row must carry the enriched fields that support
    trigger-only detection + chain-parent display on the UI, even for
    plain paying features (where trigger_only=False and parent=None).
    """
    fb = run_full_pipeline["player_impact"]["upstream_feature_breakdown"]
    required_keys = {
        "feature_name",
        "total_win",
        "total_times",
        "fires_spins",
        "fire_rate",
        "direct_win_credits",
        "trigger_only",
        "resolved_spin_type",
        "spin_type_binding_ambiguous",
        "chain_parent_feature",
        "chain_parent_confidence",
        "chain_parent_share",
        "chain_parent_next_fires",
        "rtp_contribution_pp",
        "share_of_total_win",
        "payouts",
    }
    for feat in fb["features"]:
        missing = required_keys - set(feat.keys())
        assert not missing, (
            f"feature {feat.get('feature_name')!r} missing: {missing}"
        )
        # Paying features (direct_win_credits > 0) must NOT be
        # flagged trigger_only; inverse for zero-win features.
        if feat["direct_win_credits"] > 0:
            assert feat["trigger_only"] is False
        # fires_spins mirrors total_times exactly (legacy alias).
        assert feat["fires_spins"] == feat["total_times"]
        # fire_rate = fires / total_spins, bounded [0, 1].
        assert 0.0 <= feat["fire_rate"] <= 1.0


def test_feature_breakdown_m272_paying_features_resolved(run_full_pipeline):
    """M272 fixture has 2 features, both paying (no trigger-only on
    this machine). Both should map to their SpinType via exact count
    match and trigger_only should be False for each."""
    fb = run_full_pipeline["player_impact"]["upstream_feature_breakdown"]
    by_name = {f["feature_name"]: f for f in fb["features"]}
    assert {"NormalCollectionSpin", "NewFreespin"}.issubset(set(by_name.keys()))
    for name in ("NormalCollectionSpin", "NewFreespin"):
        feat = by_name[name]
        assert feat["trigger_only"] is False
        # Both paying features bind to a SpinType on M272.
        assert feat["resolved_spin_type"] is not None
        assert feat["spin_type_binding_ambiguous"] is False


def test_collect_feature_match_block_present_no_warning(run_full_pipeline):
    """feature_match must always be in the collect_mechanic summary so
    the UI can check it; warning=None on M272 (cycle-bonus feature
    resolvable). The block now reports the RESOLVED feature + source
    (config/heuristic/none) instead of a hardcoded NewFreespin check.
    """
    fm = run_full_pipeline["collect_mechanic"].get("feature_match")
    assert fm is not None, "feature_match block must be present in summary"
    for k in ("applicable", "known_features", "bonus_feature",
              "bonus_feature_source", "warning"):
        assert k in fm, f"feature_match missing key: {k}"
    assert fm["warning"] is None, (
        f"M272 fixture must not trigger warning; got: {fm.get('warning')!r}"
    )


def test_collect_bonus_cycle_correction_block_shape(run_full_pipeline):
    """The RTP-correction block used to be `newfreespin_correction` with
    a hardcoded feature name. It's now `bonus_cycle_correction` with
    an explicit resolved feature + source (config / heuristic / none).
    The old key is kept as an alias for backward compat."""
    cm = run_full_pipeline["collect_mechanic"]
    assert "bonus_cycle_correction" in cm
    bcc = cm["bonus_cycle_correction"]
    for k in ("applicable", "bonus_feature", "bonus_feature_source",
              "detected_cycle_length", "completed_cycles_total",
              "avg_bonus_payout", "estimated_correction_pp"):
        assert k in bcc, f"bonus_cycle_correction missing key: {k}"
    # Legacy alias still carries the same payload (JSON round-trip
    # loses object identity, so compare by value, not by `is`).
    assert cm.get("newfreespin_correction") == bcc, (
        "newfreespin_correction must alias to bonus_cycle_correction for "
        "backward compat"
    )


def test_cycle_observation_block_present(run_full_pipeline):
    """New Phase 3D block: distinguishes 'no collect mechanic' from
    'collect mechanic but cache too short to see a reset'. On M272
    fixture (50 spin times × 8 robots = 400 rounds, cycle_len ~1000)
    the mechanic is detected but no reset fires — so the warning
    surfaces with a cycle_len_lower_bound hint."""
    co = run_full_pipeline["collect_mechanic"].get("cycle_observation")
    assert co is not None, "cycle_observation block must be in summary"
    assert co["mechanic_detected"] is True, (
        "M272 must report mechanic_detected=True (has CollectCount)"
    )
    # On the fixture, sample ends at cycle boundary without a reset.
    # If that ever changes (larger fixture), the test can be loosened.
    if co["reset_observed"] is False:
        assert co["warning"] is not None
        assert co["cycle_len_lower_bound"] is not None
