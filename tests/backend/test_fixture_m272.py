"""Regression tests against a real M272 mode 1 API response fixture.

The fixture lives at tests/fixtures/m272_mode1_r8_s50.json (8 robots,
50 SpinTimes, ~446 rounds total including bonus). It was captured from
the live MultiRobotTestSpin endpoint and checked into source so these
tests run offline -- no network needed.

Purpose: lock the RTP-denominator invariant (zero-win sessions MUST
contribute their bets to session_bucket_bet so the paid-session RTP
denominator is correct), the upstream cross-check (delta==0), and the
output-bucket filtering (eq0 NOT in output rows, but IS in internal
dicts).

If you change return_bucket / session_bucket_bet / session_bet_sum /
build_multiplier_bucket_rows, this test must still pass. If it breaks,
the operator will see wildly incorrect RTP in the manage-tab history.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# Fixture path relative to repo root.
_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "m272_mode1_r8_s50.json"


@pytest.fixture(autouse=True)
def _patch_post_json(monkeypatch):
    """Replace the live HTTP call with the fixture data."""
    fixture_data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        "fresh_slotlab.analyzer.core.base_pipeline.post_json",
        lambda payload, timeout: fixture_data,
    )


def _run_chunk(**kwargs: Any) -> dict[str, Any]:
    from fresh_slotlab.analyzer.core.base_pipeline import run_sampling_chunk
    defaults = dict(
        chunk_index=1,
        machine="M272",
        rtp_mode=1,
        bet=1000,
        spin_times=50,
        robot_count=8,
        timeout=30,
    )
    defaults.update(kwargs)
    return run_sampling_chunk(**defaults)


# ---------- invariant 1: upstream cross-check ----------

def test_upstream_total_win_delta_zero():
    """Our parsed total_win must exactly match the server-side
    analysisResult.TotalWin sum. Any delta means we're
    miscounting wins somewhere."""
    rec = _run_chunk()
    assert rec["ok"]
    our_win = float(rec["win"])
    upstream = float(rec["upstream_chunk_total_win"])
    assert abs(our_win - upstream) < 1.0, (
        f"upstream drift: ours={our_win} server={upstream} delta={our_win - upstream}"
    )


# ---------- invariant 2: RTP denominator correctness ----------

def test_session_bet_sum_includes_zero_win_sessions():
    """The paid-session RTP denominator (session_bet_sum) must include
    bets from EVERY paid session, including zero-win sessions that go
    to the internal 'eq0' bucket. Missing these bets inflates RTP by
    the reciprocal of hit_rate (~5x on M272 mode 1).

    This is the regression the RTP-denominator bug (fixed 5ef2562)
    would have caught.
    """
    rec = _run_chunk()
    assert rec["ok"]
    paid_sessions = int(rec.get("paid_session_count", 0))
    session_bet_total = sum(float(v) for v in rec["session_bucket_bet"].values())

    # Every paid session bets exactly `bet` (1000), so the total
    # session bet must equal paid_sessions * 1000.
    expected_bet = paid_sessions * 1000.0
    assert abs(session_bet_total - expected_bet) < 1.0, (
        f"session_bet_sum={session_bet_total} != "
        f"paid_sessions({paid_sessions}) * 1000 = {expected_bet}; "
        f"zero-win session bets likely leaking"
    )

    # eq0 key must be in the dict (internal accounting).
    assert "eq0" in rec["session_bucket_bet"], (
        "eq0 missing from session_bucket_bet -- zero-win sessions' bets "
        "are not being accumulated, which would break the RTP denominator"
    )


def test_rtp_within_plausible_range():
    """M272 mode 1's true RTP is ~90-100% at sufficient sample sizes.
    At the fixture's tiny sample (400 paid sessions) we expect high
    variance but NOT the 300-500% that the denominator bug produced."""
    rec = _run_chunk()
    assert rec["ok"]
    total_win = float(rec["win"])
    sess_bet = sum(float(v) for v in rec["session_bucket_bet"].values())
    rtp_pct = (total_win / sess_bet) * 100.0 if sess_bet > 0 else 0.0

    # Wide bounds: 20% to 300% covers even extreme small-sample variance
    # but catches the 470%+ bug.
    assert 20.0 < rtp_pct < 300.0, (
        f"RTP={rtp_pct:.1f}% is out of plausible range for M272 mode 1 "
        f"(even at small sample); investigate session_bet_sum vs total_win"
    )


# ---------- invariant 3: eq0 in internal, not in output ----------

def test_eq0_in_internal_buckets_but_not_in_output_order():
    """eq0 is tracked internally (for correct totals) but excluded from
    RETURN_BUCKET_ORDER so the output rows don't carry a zero-info bar."""
    from fresh_slotlab.analyzer.core.aggregator import RETURN_BUCKET_ORDER

    rec = _run_chunk()
    assert rec["ok"]
    # Internal: present
    assert "eq0" in rec["multiplier_bucket_spins"]
    # Output ordering: absent
    assert "eq0" not in RETURN_BUCKET_ORDER


# ---------- invariant 4: bonus-spin identification ----------

def test_bonus_spins_are_free():
    """Bonus spins (SpinType=126 on M272) must have CostCredits=0.
    spin_type_paid_rounds for 126 must be 0; for 140 must equal its
    total spins. This guards the SpinType RTP denominator fix."""
    rec = _run_chunk()
    assert rec["ok"]
    st_paid = rec.get("spin_type_paid_rounds", {})
    st_spins = rec.get("spin_type_spins", {})
    # SpinType 140 = all-paid
    if "140" in st_spins:
        assert int(st_paid.get("140", 0)) == int(st_spins["140"]), (
            "SpinType 140 should be all-paid"
        )
    # SpinType 126 = all-free
    if "126" in st_spins:
        assert int(st_paid.get("126", 0)) == 0, (
            "SpinType 126 should be all-free (CostCredits=0)"
        )
