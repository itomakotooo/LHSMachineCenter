"""M31 reel strip invariants test.

ARCHITECTURE §5.4 required test: test_<M>_strips_invariants.py
Verifies:
  - Strip symbol sets are subsets of spec symbols (no orphan tokens)
  - Both 'base' and 'freespin' reel sets are non-empty
  - FreeSpin reel 2 (index 1) is 100% wild symbols (no blanks, no regulars, no Scatter)
  - No orphan symbols in any strip position
  - X-Blank-X window isolation: Scatter absent from freespin reels
  - Weights arrays align with strip lengths (per reel)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_M31_DIR = _ROOT / "slot_designer" / "machines" / "M31"
_SPEC_PATH = _M31_DIR / "spec.json"
_STRIPS_PATH = _M31_DIR / "reel_strips.json"
_WEIGHTS_PATH = _M31_DIR / "weights" / "mode_1" / "weights.json"


@pytest.fixture(scope="module")
def spec():
    return json.loads(_SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def strips():
    return json.loads(_STRIPS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def weights():
    return json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────
# Base reel set
# ─────────────────────────────────────────────────────────────────────

def test_base_reels_exist(strips):
    """reel_strips.json has 'reels' key (base reel set)."""
    assert "reels" in strips, "'reels' key missing from reel_strips.json"
    assert len(strips["reels"]) == 3, "Expected 3 reels in base reel set"


def test_base_reels_nonempty(strips):
    for reel_idx, reel in enumerate(strips["reels"]):
        assert len(reel) > 0, f"Base reel {reel_idx + 1} is empty"


def test_base_reel_symbols_in_spec(spec, strips):
    """All base reel symbols are in spec['symbols'] (no orphan tokens)."""
    valid_symbols = set(spec["symbols"].keys())
    for reel_idx, reel in enumerate(strips["reels"]):
        for stop_idx, sym in enumerate(reel):
            assert sym in valid_symbols, (
                f"Orphan symbol '{sym}' at base reel {reel_idx + 1}, "
                f"stop {stop_idx} not in spec symbols {valid_symbols}"
            )


def test_base_reels_have_scatter(strips):
    """Base reels include Scatter symbol (trigger mechanism requires it)."""
    for reel_idx, reel in enumerate(strips["reels"]):
        has_scatter = any(sym == "Scatter" for sym in reel)
        assert has_scatter, (
            f"Base reel {reel_idx + 1} has no Scatter symbol — "
            "scatter trigger requires Scatter on all 3 reels."
        )


def test_base_reel_has_regular_symbols(strips):
    """Base reels have at least one regular symbol per reel."""
    regular = {"1bar", "2bar", "3bar", "bell", "High7"}
    for reel_idx, reel in enumerate(strips["reels"]):
        has_reg = any(sym in regular for sym in reel)
        assert has_reg, f"Base reel {reel_idx + 1} has no regular symbols"


def test_base_weights_align_with_strips(strips, weights):
    """weights['weights'] has same length per reel as strips['reels']."""
    base_weights = weights.get("weights")
    assert base_weights is not None, "'weights' key missing from weights.json"
    assert len(base_weights) == 3, "Expected 3 weight arrays (one per reel)"
    for reel_idx, (reel, wts) in enumerate(zip(strips["reels"], base_weights)):
        assert len(reel) == len(wts), (
            f"Base reel {reel_idx + 1}: strip has {len(reel)} stops "
            f"but weights has {len(wts)} — must match"
        )


# ─────────────────────────────────────────────────────────────────────
# FreeSpin reel set
# ─────────────────────────────────────────────────────────────────────

def test_freespin_reels_exist(strips):
    """reel_strips.json has 'freespin_reels' key."""
    assert "freespin_reels" in strips, (
        "'freespin_reels' key missing from reel_strips.json — "
        "required for ST=44 FreeSpin evaluation"
    )


def test_freespin_has_3_reels(strips):
    freespin_reels = strips["freespin_reels"]
    assert len(freespin_reels) == 3, (
        f"Expected 3 FreeSpin reels, got {len(freespin_reels)}"
    )


def test_freespin_reel2_is_all_wilds(strips):
    """FreeSpin reel 2 (index 1) is 100% wild symbols.

    Verified: 01c §7 — 1,470 FreeSpin reel-2 stops, all Wild2x/Wild3x/Wild5x/Wild10x.
    """
    wild_symbols = {"Wild2x", "Wild3x", "Wild5x", "Wild10x"}
    freespin_reels = strips["freespin_reels"]
    reel2 = freespin_reels[1]
    assert len(reel2) > 0, "FreeSpin reel 2 is empty"
    non_wild = [sym for sym in reel2 if sym not in wild_symbols]
    assert len(non_wild) == 0, (
        f"FreeSpin reel 2 has non-wild symbols: {set(non_wild)} — "
        "reel 2 must be 100% wild (Wild2x/Wild3x/Wild5x/Wild10x) per 01c §7."
    )


def test_freespin_reel2_has_all_4_wild_types(strips):
    """FreeSpin reel 2 has all 4 wild symbol types.

    From 01c §7: Wild2x=47.7%, Wild3x=21.2%, Wild5x=14.6%, Wild10x=16.5%.
    Strip should include at least 1 of each.
    """
    reel2 = strips["freespin_reels"][1]
    wild_types_present = {sym for sym in reel2}
    required = {"Wild2x", "Wild3x", "Wild5x", "Wild10x"}
    missing = required - wild_types_present
    assert not missing, (
        f"FreeSpin reel 2 missing wild types: {missing}. "
        "All 4 wild tiers observed in production data (01c §7)."
    )


def test_freespin_reel2_no_scatter(strips):
    """FreeSpin reel 2 has no Scatter symbol.

    01c §7: Scatter appears at 0% in FreeSpin strips — retrigger structurally impossible.
    """
    reel2 = strips["freespin_reels"][1]
    assert "Scatter" not in reel2, (
        "FreeSpin reel 2 must not contain Scatter — retrigger is impossible per 01c §7."
    )


def test_freespin_reels_no_scatter(strips):
    """FreeSpin reels (all 3) have no Scatter symbol.

    Scatter is structurally absent from FreeSpin reel set (01c §7, §6).
    """
    for reel_idx, reel in enumerate(strips["freespin_reels"]):
        assert "Scatter" not in reel, (
            f"FreeSpin reel {reel_idx + 1} contains Scatter — "
            "Scatter must be absent from all FreeSpin reels per 01c §7."
        )


def test_freespin_reel_symbols_in_spec(spec, strips):
    """All FreeSpin reel symbols are in spec['symbols']."""
    valid_symbols = set(spec["symbols"].keys())
    for reel_idx, reel in enumerate(strips["freespin_reels"]):
        for stop_idx, sym in enumerate(reel):
            assert sym in valid_symbols, (
                f"Orphan symbol '{sym}' at freespin reel {reel_idx + 1}, "
                f"stop {stop_idx} not in spec symbols"
            )


def test_freespin_weights_align_with_strips(strips, weights):
    """weights['freespin_weights'] has same length per reel as freespin_reels."""
    freespin_weights = weights.get("freespin_weights")
    assert freespin_weights is not None, (
        "'freespin_weights' key missing from weights.json"
    )
    freespin_reels = strips["freespin_reels"]
    assert len(freespin_weights) == len(freespin_reels), (
        f"freespin_weights has {len(freespin_weights)} arrays but "
        f"freespin_reels has {len(freespin_reels)} reels"
    )
    for reel_idx, (reel, wts) in enumerate(zip(freespin_reels, freespin_weights)):
        assert len(reel) == len(wts), (
            f"FreeSpin reel {reel_idx + 1}: strip has {len(reel)} stops "
            f"but freespin_weights has {len(wts)}"
        )


# ─────────────────────────────────────────────────────────────────────
# Spec + strips consistency
# ─────────────────────────────────────────────────────────────────────

def test_strips_machine_matches_spec(spec, strips):
    """reel_strips.json['machine'] == spec['machine']."""
    assert strips["machine"] == spec["machine"], (
        f"Strip machine '{strips['machine']}' != spec machine '{spec['machine']}'"
    )


def test_all_spec_symbols_accessible_in_strips(spec, strips):
    """All spec symbols (except filler-only ones) appear in at least one reel."""
    # Scatter should appear in base strips only.
    # All 11 spec symbols appear somewhere.
    all_base_syms = {sym for reel in strips["reels"] for sym in reel}
    all_free_syms = {sym for reel in strips["freespin_reels"] for sym in reel}
    all_strip_syms = all_base_syms | all_free_syms

    spec_symbols = set(spec["symbols"].keys())
    # Scatter is in base strips, not freespin strips — that's expected.
    assert spec_symbols <= all_strip_syms, (
        f"Spec symbols not in any strip: {spec_symbols - all_strip_syms}"
    )


def test_reel_set_tag():
    """reel_strips.json has reel_set='base' matching the ST=43 spin_type."""
    strips = json.loads(_STRIPS_PATH.read_text(encoding="utf-8"))
    assert strips.get("reel_set") == "base", (
        f"reel_set should be 'base', got {strips.get('reel_set')!r}"
    )
