"""Full-pipeline regression test against the M14 mode 1 fixture.

M14 is the simplest machine: single SpinType (1, all-paid), no bonus
mechanic, no FeatureWin beyond "Normal", no MapCollection. This
baseline locks the "vanilla classic slot" path so changes designed
for M272's collect-bonus mechanics don't silently break M14.
"""
from __future__ import annotations

import json
import sys
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "m14_mode1_r8_s50.json"

BASELINE = {
    "rtp_point_pct": 53.295,
    "paid_spins": 400,
    "bonus_spins": 0,
    "total_spins": 400,
    "upstream_matches": True,
    "tail_dep_ge10x": 0.3895768833849329,
    "volatility_class": "High",
    "experience_archetype": "Grindy",
    "spin_type_count": 1,
    "has_feature_breakdown": False,
    "has_bonus_chain": False,
    "eq0_in_buckets": False,
    "bucket_count": 11,
    "bucket_rtp_sum": 53.295,
}


@pytest.fixture()
def run_full_pipeline(monkeypatch):
    fixture_data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        "fresh_slotlab.player_impact_analyzer.post_json",
        lambda payload, timeout: fixture_data,
    )
    monkeypatch.setattr("os._exit", lambda rc: None)

    with tempfile.TemporaryDirectory() as tmpdir:
        outdir = Path(tmpdir) / "output"
        outdir.mkdir()
        test_argv = [
            "analyzer",
            "--machine", "M14",
            "--rtp-mode", "1",
            "--bet", "1000",
            "--chunk-spin-times", "50",
            "--chunk-robot-count", "8",
            "--batch-concurrency", "1",
            "--max-chunks", "1",
            "--target-halfwidth-pp", "999",
            "--timeout", "30",
            "--output-dir", str(outdir),
            "--progress-file", str(Path(tmpdir) / "p.jsonl"),
            "--run-id", "m14_regression",
            "--bankruptcy-session-spins", "100",
            "--bankruptcy-bankroll-multipliers", "100,200,500",
        ]
        monkeypatch.setattr(sys, "argv", test_argv)
        monkeypatch.setattr(sys, "stdout", StringIO())
        from fresh_slotlab.player_impact_analyzer import main
        rc = main()
        assert rc == 0
        return json.loads((outdir / "player_impact_summary.json").read_text(encoding="utf-8"))


def test_rtp_matches_baseline(run_full_pipeline):
    assert abs(run_full_pipeline["rtp"]["point_pct"] - BASELINE["rtp_point_pct"]) < 0.001


def test_bucket_rtp_sum_equals_rtp(run_full_pipeline):
    buckets = run_full_pipeline["player_impact"]["multiplier_profile"]["buckets"]
    assert abs(sum(b["rtp_contribution_pp"] for b in buckets) - run_full_pipeline["rtp"]["point_pct"]) < 0.01


def test_payout_ids_top20_rtp_sum_equals_summary_rtp(run_full_pipeline):
    """Iter 3 denominator unification (2026-04-23): payout row
    ``rtp_contribution_pp`` now uses ``effective_bet_for_rtp``
    (paid-spin bet only), same denominator as ``summary.rtp``.
    Before this, payout rows used ``total_bet`` (paid + bonus bet)
    and the sum lagged ``summary.rtp`` by the ratio paid/total
    (M14 had no bonus so the diff was 0; M15/M272-style bonus-
    heavy machines showed ~4% gap). This test locks the parity
    on M14 — sum of all payout row rtp_pp must equal summary.rtp
    exactly (tolerance 0.01 for rounding)."""
    rows = run_full_pipeline["player_impact"]["payout_ids_top20"]
    # -1 is the "no payout" bucket — represents lose spins with
    # total_win = 0 and rtp_pp = 0. Its presence is inert but we
    # guard against flakiness if a future change starts treating
    # it differently. Sum includes it regardless (0 add).
    pay_sum_pp = sum(r.get("rtp_contribution_pp", 0.0) for r in rows)
    rtp_pct = run_full_pipeline["rtp"]["point_pct"]
    assert abs(pay_sum_pp - rtp_pct) < 0.01, (
        f"payout_ids_top20 rtp_pp sum {pay_sum_pp} diverges from "
        f"summary.rtp {rtp_pct} — denominator regression?"
    )


def test_no_bonus_spins(run_full_pipeline):
    assert run_full_pipeline["sampling"]["bonus_spins"] == 0
    assert run_full_pipeline["sampling"]["paid_spins"] == BASELINE["paid_spins"]


def test_upstream_delta_zero(run_full_pipeline):
    assert run_full_pipeline["upstream_analysis"]["matches"] is True


def test_single_spin_type_all_paid(run_full_pipeline):
    st = run_full_pipeline["player_impact"]["spin_type_breakdown"]
    assert len(st) == 1
    assert st[0]["behavior_name"] == "paid"
    assert st[0]["rtp_pct"] is not None  # not null (all-paid has a real RTP)


def test_no_feature_breakdown_no_bonus_chain(run_full_pipeline):
    assert run_full_pipeline["player_impact"]["upstream_feature_breakdown"]["applicable"] is False
    assert run_full_pipeline["player_impact"]["bonus_chain_dynamics"]["applicable"] is False


def test_eq0_not_in_output(run_full_pipeline):
    labels = [b["bucket"] for b in run_full_pipeline["player_impact"]["multiplier_profile"]["buckets"]]
    assert "eq0" not in labels
    assert len(labels) == 11
