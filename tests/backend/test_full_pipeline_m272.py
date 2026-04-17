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


def test_collect_feature_match_block_present_no_warning(run_full_pipeline):
    """feature_match must always be in the collect_mechanic summary so
    the UI can check it; warning=None on machines where either no
    cycle was observed (fixture is only 400 spins, cycle_len=1000 so
    no full cycle) OR NewFreespin is properly in the tally. Either
    way, no warning — the only time we warn is cycles-observed AND
    no-NewFreespin, which shouldn't happen on M272."""
    fm = run_full_pipeline["collect_mechanic"].get("feature_match")
    assert fm is not None, "feature_match block must be present in summary"
    assert "warning" in fm, "warning key must always be there (even when None)"
    assert fm["warning"] is None, (
        f"M272 fixture must not trigger warning; got: {fm.get('warning')!r}"
    )
    # Structural keys all present.
    for k in ("applicable", "known_features", "has_newfreespin", "warning"):
        assert k in fm, f"feature_match missing key: {k}"
