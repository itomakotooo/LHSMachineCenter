"""Tests for the SpinType inventory extractor (Phase 0a foundation).

Two layers:
  * Pure unit tests of `signature()` — no rawdata needed (run in CI).
  * Real-data validation on M15 cached chunks — skipped if rawdata absent
    (mirrors the repo's e2e-against-cached-chunks pattern).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fresh_slotlab.analyzer.st_inventory import extract_st_inventory, signature

_REPO = Path(__file__).resolve().parents[2]
_M15_MODE1 = _REPO / "rawdata" / "M15" / "mode_1"


# ── pure unit: signature() ─────────────────────────────────────────────

def test_signature_keeps_only_near_universal_fields():
    entry = {"field_presence": {"A": 1.0, "B": 0.995, "C": 0.5, "D": 0.0}}
    assert signature(entry, min_ratio=0.99) == frozenset({"A", "B"})


def test_signature_empty_when_no_fields():
    assert signature({}, min_ratio=0.99) == frozenset()


def test_signature_threshold_is_inclusive():
    entry = {"field_presence": {"X": 0.99}}
    assert signature(entry, min_ratio=0.99) == frozenset({"X"})


# ── real-data: M15 ground truth (ST1/14/15 + validated field signatures) ─

@pytest.mark.skipif(not _M15_MODE1.exists(), reason="M15 cached rawdata not present")
def test_m15_inventory_matches_validated_event_model():
    inv = extract_st_inventory("M15", 1, _REPO / "rawdata")
    sts = inv["spin_types"]
    # M15 emits exactly ST1 (paid), ST14 (player choice), ST15 (settlement).
    assert {"1", "14", "15"}.issubset(set(sts)), f"got STs {sorted(sts)}"
    # Field signatures match the validated 02_traces spec.
    assert {"DollarCount", "ChosenDollar", "OfferValue"}.issubset(signature(sts["14"]))
    assert "WinAmount" in signature(sts["15"])
    assert {"BetAmount", "PayoutByPayline"}.issubset(signature(sts["1"]))
    # Counts are real (non-trivial).
    assert sts["1"]["count"] > sts["14"]["count"] > 0
    assert inv["rounds_scanned"] > 0
