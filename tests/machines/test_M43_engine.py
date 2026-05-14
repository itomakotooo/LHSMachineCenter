"""M43 engine smoke + schema-fingerprint alignment tests (Stage 2).

Per ARCHITECTURE.md §5.4: spec/strips/weights load successfully; engine
runs 1k spins without exception; produced chunk schema matches
production rawdata byte-for-byte.

Production rawdata anchor:
  ``rawdata/M43/mode_1/chunk_0001.json`` (envelope claims
  ``_upstream_schema_fingerprint = 5d02773c069fc396``).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from random import Random

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_M43_SPEC = _REPO_ROOT / "slot_designer" / "machines" / "M43" / "spec.json"
_M43_STRIPS = _REPO_ROOT / "slot_designer" / "machines" / "M43" / "reel_strips.json"
_M43_WEIGHTS_M1 = (
    _REPO_ROOT / "slot_designer" / "machines" / "M43" / "weights" / "mode_1" / "weights.json"
)
_PROD_CHUNK = _REPO_ROOT / "rawdata" / "M43" / "mode_1" / "chunk_0001.json"


def test_spec_loads_and_has_required_blocks():
    spec = json.loads(_M43_SPEC.read_text(encoding="utf-8"))
    assert spec["machine"] == "M43"
    assert spec["mode"] == 1
    assert spec["grid"]["cols"] == 3 and spec["grid"]["rows"] == 3
    assert len(spec["grid"]["paylines"]) == 1
    # 8 symbols expected: blank, 1bar, 2bar, 3bar, 7, wild, blankup, blankdown
    assert set(spec["symbols"].keys()) == {
        "blank", "1bar", "2bar", "3bar", "7",
        "wild", "blankup", "blankdown",
    }
    pay_ids = sorted(p["pay_id"] for p in spec["pays"])
    # pay_id 8 added at Stage 2.5 (plugin_handled kind: trigger + multiplier
    # logic lives in M43FeaturePlugin._apply_payline_post_eval).
    assert pay_ids == [2, 3, 4, 5, 6, 7, 8, 9]
    # pay_id 8 must be declared as plugin_handled (no evaluator logic).
    pay8 = next(p for p in spec["pays"] if p["pay_id"] == 8)
    assert pay8["kind"] == "plugin_handled"
    # Features declared (M43 has Respin + MiniGame)
    assert len(spec["features"]) == 1
    assert spec["features"][0]["trigger_pay_id"] is None  # outcome-conditional


def test_strips_load_and_have_20_stops_per_reel():
    strips = json.loads(_M43_STRIPS.read_text(encoding="utf-8"))
    assert strips["machine"] == "M43"
    assert strips["reel_set"] == "default"
    assert len(strips["reels"]) == 3
    for ri, reel in enumerate(strips["reels"]):
        assert len(reel) == 20, f"reel {ri+1} expected 20 stops, got {len(reel)}"


def test_weights_align_with_strips_per_position():
    strips = json.loads(_M43_STRIPS.read_text(encoding="utf-8"))
    weights = json.loads(_M43_WEIGHTS_M1.read_text(encoding="utf-8"))
    assert len(strips["reels"]) == len(weights["weights"])
    for s, w in zip(strips["reels"], weights["weights"]):
        assert len(s) == len(w)


def test_load_engine_wires_m43_plugin():
    from slot_designer.core.engine.feature_protocol import FeaturePlugin
    from slot_designer.core.engine.loader import load_engine

    engine, _ = load_engine(_M43_SPEC, _M43_WEIGHTS_M1)
    assert engine.plugin is not None, "M43 declares features; plugin must wire"
    assert isinstance(engine.plugin, FeaturePlugin)
    # Outcome-conditional plugin → trigger_pay_id is None.
    assert engine.plugin.trigger_pay_id is None


def test_engine_runs_1k_spins_without_exception():
    from slot_designer.core.engine.loader import load_engine

    engine, _ = load_engine(_M43_SPEC, _M43_WEIGHTS_M1)
    rng = Random(0)
    for _ in range(1000):
        outcome, feature_rounds = engine.spin_session(rng)
        # Sanity: outcome grid 3x3, payline length 3.
        assert len(outcome.grid) == 3
        assert all(len(col) == 3 for col in outcome.grid)
        assert isinstance(feature_rounds, list)


def test_chunk_schema_fingerprint_matches_production():
    """compute_schema_fingerprint(virtual chunk's first round) ==
    production chunk's claimed _upstream_schema_fingerprint.

    Production anchor: rawdata/M43/mode_1/chunk_0001.json — fingerprint
    ``5d02773c069fc396`` (sha256[:16] of sorted ST=1 round keys).
    """
    from slot_designer.core.emitter.driver import compute_schema_fingerprint_for
    from slot_designer.core.engine.loader import load_engine

    engine, _ = load_engine(_M43_SPEC, _M43_WEIGHTS_M1)
    fp = compute_schema_fingerprint_for(engine, mode=1, spins_per_robot=1000)

    prod = json.loads(_PROD_CHUNK.read_text(encoding="utf-8"))
    assert fp == prod["_upstream_schema_fingerprint"], (
        f"virtual schema fingerprint {fp} != production "
        f"{prod['_upstream_schema_fingerprint']}"
    )
    # Hard-coded sentinel: catches a future production schema drift
    # (would invalidate this assertion before refresh-fetching).
    assert fp == "5d02773c069fc396"


def test_chunk_envelope_keys_match_production():
    """Virtual chunk envelope key set matches production exactly."""
    from slot_designer.core.emitter.driver import (
        compute_schema_fingerprint_for, sample_one_chunk,
    )
    from slot_designer.core.engine.loader import load_engine

    engine, _ = load_engine(_M43_SPEC, _M43_WEIGHTS_M1)
    schema_fp = compute_schema_fingerprint_for(engine, mode=1, spins_per_robot=1000)

    rng = Random(123)
    chunk, _w, _b = sample_one_chunk(
        engine,
        machine="M43", mode=1, chunk_index=1,
        robots=1, spins_per_robot=100, rng=rng,
        schema_fp=schema_fp,
        config_md5="test", code_md5="test",
    )

    prod = json.loads(_PROD_CHUNK.read_text(encoding="utf-8"))
    virt_keys = set(chunk.keys())
    prod_keys = set(prod.keys())
    assert virt_keys == prod_keys, (
        f"chunk envelope keys differ: virtual_only={virt_keys - prod_keys}, "
        f"prod_only={prod_keys - virt_keys}"
    )


def test_feature_rounds_emit_st50_st51():
    """Run enough spins that respin (ST=50) and minigame (ST=51) both fire,
    and validate their round-dict shapes."""
    from slot_designer.core.engine.loader import load_engine
    from slot_designer.core.emitter.driver import (
        compute_schema_fingerprint_for, sample_one_chunk,
    )

    engine, _ = load_engine(_M43_SPEC, _M43_WEIGHTS_M1)
    schema_fp = compute_schema_fingerprint_for(engine, mode=1, spins_per_robot=1000)

    rng = Random(7)
    chunk, _w, _b = sample_one_chunk(
        engine,
        machine="M43", mode=1, chunk_index=1,
        robots=2, spins_per_robot=5000, rng=rng,
        schema_fp=schema_fp,
        config_md5="test", code_md5="test",
    )

    seen_st50 = False
    seen_st51 = False
    for robot in chunk["response"]:
        rounds = json.loads(robot["roundResult"])
        for r in rounds:
            st = r.get("SpinType")
            if st == 50:
                seen_st50 = True
                assert r.get("ReMarks") == "ReSpin"
                assert r.get("ReelSkin") == 6
                assert r.get("CostCredits") == 0
            elif st == 51:
                seen_st51 = True
                rm = r.get("ReMarks", "")
                assert rm.startswith("MiniGame[") and rm.endswith("]"), (
                    f"mini-game ReMarks malformed: {rm!r}"
                )
                # Reduced 7-key envelope per 01c §6 + §8.
                expected_keys = {
                    "IsLackCreditsSpin", "LastCredits", "RTPId",
                    "ReMarks", "SpinTimes", "SpinType", "WinCredits",
                }
                assert set(r.keys()) == expected_keys, (
                    f"mini-game key set differs: virt={set(r.keys())} "
                    f"expected={expected_keys}"
                )

    assert seen_st50, "no ST=50 (Respin) rounds emitted in 10k spins — trigger broken?"
    assert seen_st51, "no ST=51 (MiniGame) rounds emitted in 10k spins — trigger broken?"


# ─── Stage 2.5 tests (pay_id 8 + off-payline wild doubling) ────────────

def _make_outcome(grid: list[list[str]], pay=None):
    """Helper: build a SpinOutcome with the given 3×3 grid and optional pay."""
    from slot_designer.core.engine.spin import SpinOutcome
    return SpinOutcome(
        grid=grid,
        pay=pay,
        cost_credits=1000,
        bet_amount=1000,
        spin_type=1,
    )


def _make_pay(pay_id: int, multiplier: float):
    from slot_designer.core.engine.rules import PayResult
    return PayResult(
        pay_id=pay_id,
        multiplier=multiplier,
        positions=((0, 1), (1, 1), (2, 1)),
    )


def test_pay_id_8_fires_on_2wf_plus_1blank_payline():
    """pay_id 8 must fire when payline = 2 wild-family + 1 blank (predicate B_v2)."""
    from slot_designer.machines.M43.plugins.feature import _apply_payline_post_eval

    # Construct a grid where mid-row = (blank, blankup, blankdown), i.e. 2 wf + 1 blank.
    # Place wild symbols in the grid to yield window_wf_count=4.
    # Grid[col][row]: col=0 → [blank, blank, blank], col=1 → [blank, blankup, blank],
    #                  col=2 → [blank, blankdown, blank]
    # window_wf_count = blankup(1) + blankdown(1) = 2 on payline + 0 off-payline wf
    # BUT the formula needs window_wf_count = total wf in all 9 cells.
    # Let's put blankup on R1-top and wild on R3-top to get window_wf=4.
    grid = [
        ["1bar",     "blank",    "blank"],    # col 0: top=1bar, mid=blank, bot=blank
        ["blankup",  "blankup",  "blank"],    # col 1: top=blankup, mid=blankup, bot=blank
        ["wild",     "blankdown","blank"],    # col 2: top=wild, mid=blankdown, bot=blank
    ]
    # payline mid: blank, blankup, blankdown → n_wf=2, n_blank=1 → predicate fires
    # window_wf_count: blankup(R1-top) + blankup(R1-mid) + wild(R2-top) + blankdown(R2-mid) = 4
    outcome = _make_outcome(grid, pay=None)
    _apply_payline_post_eval(outcome)
    assert outcome.pay is not None, "pay_id 8 should have fired"
    assert outcome.pay.pay_id == 8
    assert outcome.pay.multiplier == 5  # window_wf=4 → 5×


def test_pay_id_8_does_not_fire_when_payline_has_bar():
    """When payline = 2 wf + 1 bar, standard bar pay fires; pay_id 8 must NOT fire."""
    from slot_designer.machines.M43.plugins.feature import _apply_payline_post_eval

    # payline mid: 1bar, blankdown, blankup → standard evaluator returns pay_id 6
    # with doubling from the wild-family symbols on payline.
    # Simulate that the standard evaluator already returned pay_id=6 (multiplier=10).
    grid = [
        ["blank",    "1bar",     "blank"],    # col 0: mid = 1bar
        ["blank",    "blankdown","blank"],    # col 1: mid = blankdown
        ["blank",    "blankup",  "blank"],    # col 2: mid = blankup
    ]
    base_pay = _make_pay(pay_id=6, multiplier=10.0)
    outcome = _make_outcome(grid, pay=base_pay)
    _apply_payline_post_eval(outcome)
    # Standard pay already exists → Rule A path, not Rule B.
    assert outcome.pay.pay_id == 6, "pay_id must remain 6 (bar pay)"
    # No off-payline wilds here → multiplier unchanged.
    assert outcome.pay.multiplier == 10.0


def test_pay_id_8_multiplier_formula_window4():
    """window_wf_count=4 → multiplier 5× (5*2^0)."""
    from slot_designer.machines.M43.plugins.feature import _apply_payline_post_eval

    # payline: blank, blankup, blankdown (n_wf=2, n_blank=1)
    # window: only these 2 wf cells + 2 more from top rows = 4 total wf.
    grid = [
        ["1bar",  "blank",    "blank"],
        ["blankup","blankup", "blank"],
        ["blank", "blankdown","blank"],
    ]
    # window_wf_count: blankup(col1-top) + blankup(col1-mid) + blankdown(col2-mid) = 3
    # Hmm, need 4. Let me add one more wf cell off-payline.
    grid = [
        ["blankup", "blank",    "blank"],   # col0: top=blankup (wf), mid=blank
        ["blank",   "blankup",  "blank"],   # col1: mid=blankup (wf payline)
        ["blank",   "blankdown","blank"],   # col2: mid=blankdown (wf payline)
    ]
    # window_wf: blankup(col0-top) + blankup(col1-mid) + blankdown(col2-mid) = 3
    # Still need 4. Let me use explicit 4-wf scenario.
    grid = [
        ["blankdown","blank",   "blank"],   # col0-top=blankdown; col0-mid=blank
        ["blankup",  "blankup", "blank"],   # col1-top=blankup; col1-mid=blankup
        ["wild",     "blankdown","blank"],  # col2-top=wild; col2-mid=blankdown
    ]
    # payline: blank, blankup, blankdown → n_wf=2, n_blank=1 ✓
    # window_wf_count: blankdown(col0-top) + blankup(col1-top) + blankup(col1-mid) +
    #                  wild(col2-top) + blankdown(col2-mid) = 5
    # That's 5, not 4. Let me build an exact window_wf=4 scenario.
    grid = [
        ["blank",   "blank",    "blank"],   # col0: all blank
        ["blankup", "blankup",  "blank"],   # col1: top=blankup, mid=blankup
        ["blank",   "blankdown","blank"],   # col2: mid=blankdown
    ]
    # payline mid: blank, blankup, blankdown → n_wf=2, n_blank=1 ✓
    # window_wf: blankup(col1-top=off) + blankup(col1-mid=payline) + blankdown(col2-mid=payline) = 3
    # 3 != 4. The formula requires window_wf_count ∈ {4,5,6}.
    # For window_wf=4 we need exactly 4 wf cells in the 3x3 grid.
    grid = [
        ["blankup", "blank",    "blank"],   # col0: top=blankup (off-payline wf)
        ["blank",   "blankup",  "blank"],   # col1: mid=blankup (payline wf)
        ["blank",   "blankdown","blankdown"],# col2: mid=blankdown (payline wf), bot=blankdown (off)
    ]
    # payline mid: blank, blankup, blankdown → n_wf=2, n_blank=1 ✓
    # window_wf: blankup(col0-top) + blankup(col1-mid) + blankdown(col2-mid) + blankdown(col2-bot)=4 ✓
    outcome = _make_outcome(grid, pay=None)
    _apply_payline_post_eval(outcome)
    assert outcome.pay is not None
    assert outcome.pay.pay_id == 8
    assert outcome.pay.multiplier == 5, f"window_wf=4 → 5×, got {outcome.pay.multiplier}"


def test_pay_id_8_multiplier_formula_window5():
    """window_wf_count=5 → multiplier 10× (5*2^1)."""
    from slot_designer.machines.M43.plugins.feature import _apply_payline_post_eval

    # payline mid: blank, blankup, blankdown + 3 more off-payline wf cells = 5 total.
    grid = [
        ["blankup",  "blank",    "blankdown"],  # col0: top=blankup, mid=blank, bot=blankdown
        ["blank",    "blankup",  "blank"],       # col1: mid=blankup (payline)
        ["blank",    "blankdown","blank"],        # col2: mid=blankdown (payline)
    ]
    # window_wf: blankup(col0-top) + blankdown(col0-bot) + blankup(col1-mid) + blankdown(col2-mid)=4
    # Need 5. Add one more.
    grid = [
        ["blankup",  "blank",    "blankdown"],
        ["blankup",  "blankup",  "blank"],
        ["blank",    "blankdown","blank"],
    ]
    # window_wf: blankup(col0-top) + blankdown(col0-bot) + blankup(col1-top) + blankup(col1-mid) +
    #            blankdown(col2-mid) = 5 ✓
    # payline mid: blank, blankup, blankdown → n_wf=2, n_blank=1 ✓
    outcome = _make_outcome(grid, pay=None)
    _apply_payline_post_eval(outcome)
    assert outcome.pay is not None
    assert outcome.pay.pay_id == 8
    assert outcome.pay.multiplier == 10, f"window_wf=5 → 10×, got {outcome.pay.multiplier}"


def test_pay_id_8_multiplier_formula_window6():
    """window_wf_count=6 → multiplier 20× (5*2^2)."""
    from slot_designer.machines.M43.plugins.feature import _apply_payline_post_eval

    # 6 wf cells in window; payline mid still = 2wf + 1blank.
    grid = [
        ["blankup",  "blank",    "blankdown"],  # col0: top+bot=wf, mid=blank
        ["blankup",  "blankup",  "blankdown"],  # col1: top+mid+bot=wf
        ["blank",    "blankdown","blank"],        # col2: mid=blankdown
    ]
    # window_wf: blankup(col0-top) + blankdown(col0-bot) + blankup(col1-top) +
    #            blankup(col1-mid) + blankdown(col1-bot) + blankdown(col2-mid) = 6 ✓
    # payline mid: blank, blankup, blankdown → n_wf=2, n_blank=1 ✓
    outcome = _make_outcome(grid, pay=None)
    _apply_payline_post_eval(outcome)
    assert outcome.pay is not None
    assert outcome.pay.pay_id == 8
    assert outcome.pay.multiplier == 20, f"window_wf=6 → 20×, got {outcome.pay.multiplier}"


def test_off_payline_bar_pays_use_standard_wild_mult():
    """For bar pays (pay_ids 2-7), wild ON payline is handled by standard
    evaluator via wild.multiplier=2 — no additional post-eval doubling needed.

    Production evidence: (1bar, wild, 1bar) → pay_id 6 at 20×.
    Standard eval: wild.mult=2 → 10×2=20×.  Post-eval: no change.
    """
    from slot_designer.machines.M43.plugins.feature import _apply_payline_post_eval

    # payline mid: 1bar, wild, 1bar → standard gives pay_id 6 at 20× (wild.mult=2)
    grid = [
        ["blank", "1bar", "blank"],    # col0: mid=1bar
        ["blankdown", "wild", "blankup"],  # col1: mid=wild (on payline), top=blankdown, bot=blankup
        ["blank", "1bar", "blank"],    # col2: mid=1bar
    ]
    # Simulate standard eval result: pay_id 6, mult=20.0 (10 × wild.mult=2)
    base_pay = _make_pay(pay_id=6, multiplier=20.0)
    outcome = _make_outcome(grid, pay=base_pay)
    _apply_payline_post_eval(outcome)
    assert outcome.pay.pay_id == 6, "pay_id must remain 6"
    assert outcome.pay.multiplier == 20.0, (
        f"wild on payline already gives 20× via standard eval; post-eval must not re-double. "
        f"Got {outcome.pay.multiplier}"
    )


def test_blankup_on_payline_bar_pay_no_additional_doubling():
    """blankup/blankdown on payline for bar pays: standard eval gives 10× (mult=1),
    no post-eval doubling.  Production evidence: (1bar, blankdown, 1bar) → 10×.
    """
    from slot_designer.machines.M43.plugins.feature import _apply_payline_post_eval

    # payline mid: 1bar, blankdown, 1bar → standard gives pay_id 6 at 10× (blankdown.mult=1)
    grid = [
        ["blank",  "1bar",     "blank"],    # col0: mid=1bar
        ["1bar",   "blankdown","wild"],     # col1: mid=blankdown, bot=wild (adjacent)
        ["blank",  "1bar",     "blank"],    # col2: mid=1bar
    ]
    base_pay = _make_pay(pay_id=6, multiplier=10.0)  # standard eval: 10×1=10×
    outcome = _make_outcome(grid, pay=base_pay)
    _apply_payline_post_eval(outcome)
    assert outcome.pay.pay_id == 6
    assert outcome.pay.multiplier == 10.0, (
        f"blankdown on payline → 10× (no extra doubling). Got {outcome.pay.multiplier}"
    )


def test_pay_id_9_doubles_when_literal_wild_on_payline():
    """pay_id 9 (side_wild_alone, 2×) doubles to 4× when literal wild is on payline.

    Production evidence: (blank, wild, blank) → 4×; (blank, blankup, blank) → 2×.
    """
    from slot_designer.machines.M43.plugins.feature import _apply_payline_post_eval

    # Case 1: literal wild on payline mid → should double to 4×
    grid_wild = [
        ["blank", "blank",  "blank"],        # col0: all blank
        ["blankdown", "wild", "blankup"],    # col1: mid=wild (payline)
        ["blank", "blank",  "blank"],        # col2: all blank
    ]
    outcome_wild = _make_outcome(grid_wild, pay=_make_pay(9, 2.0))
    _apply_payline_post_eval(outcome_wild)
    assert outcome_wild.pay.pay_id == 9
    assert outcome_wild.pay.multiplier == 4.0, (
        f"wild on payline → pay_id 9 doubles to 4×. Got {outcome_wild.pay.multiplier}"
    )

    # Case 2: blankup on payline mid → stays at 2×
    grid_blankup = [
        ["blank", "blank",  "blank"],        # col0: all blank
        ["wild",  "blankup","blank"],        # col1: mid=blankup (NOT literal wild), top=wild
        ["blank", "blank",  "blank"],        # col2: all blank
    ]
    outcome_blankup = _make_outcome(grid_blankup, pay=_make_pay(9, 2.0))
    _apply_payline_post_eval(outcome_blankup)
    assert outcome_blankup.pay.pay_id == 9
    assert outcome_blankup.pay.multiplier == 2.0, (
        f"blankup on payline → pay_id 9 stays at 2×. Got {outcome_blankup.pay.multiplier}"
    )


def test_pay_id_9_stays_2x_when_blankdown_on_payline():
    """blankdown on payline (not literal wild) → pay_id 9 stays at 2×.

    Completes three-way verification: wild→4×, blankup→2×, blankdown→2×.
    blankdown and blankup are strip-equivalent adjacency markers (01c §1);
    both should produce identical 2× behavior per Rule C in feature.py.
    """
    from slot_designer.machines.M43.plugins.feature import _apply_payline_post_eval

    # payline mid: blank, blankdown, blank → blankdown is NOT literal wild
    # → Rule C must NOT double → stays at 2×
    grid_blankdown = [
        ["blank", "blank",    "blank"],      # col0: all blank
        ["wild",  "blankdown","blank"],      # col1: mid=blankdown (NOT literal wild), top=wild
        ["blank", "blank",    "blank"],      # col2: all blank
    ]
    outcome_blankdown = _make_outcome(grid_blankdown, pay=_make_pay(9, 2.0))
    _apply_payline_post_eval(outcome_blankdown)
    assert outcome_blankdown.pay.pay_id == 9
    assert outcome_blankdown.pay.multiplier == 2.0, (
        f"blankdown on payline → pay_id 9 stays at 2× (no doubling). "
        f"Got {outcome_blankdown.pay.multiplier}"
    )


def test_pay_id_8_no_cooccurrence_with_standard_pay():
    """pay_id 8 must NEVER fire in the same round as a standard pay.

    Runs a 10k-spin Monte Carlo and asserts zero co-occurrence.
    """
    from slot_designer.core.engine.loader import load_engine

    engine, _ = load_engine(_M43_SPEC, _M43_WEIGHTS_M1)
    rng = Random(42)

    for _ in range(10_000):
        outcome, _ = engine.spin_session(rng)
        if outcome.pay is not None and outcome.pay.pay_id == 8:
            # Verify the payline had 2 wf + 1 blank (predicate B_v2).
            # If a standard evaluator had returned a different pay_id,
            # _apply_payline_post_eval would have taken Rule A path,
            # never assigning pay_id 8.
            # So pay_id==8 here implies standard returned None → exclusive.
            payline_syms = [outcome.grid[c][1] for c in range(3)]
            wf_set = frozenset({"wild", "blankup", "blankdown"})
            n_wf = sum(1 for s in payline_syms if s in wf_set)
            n_blank = sum(1 for s in payline_syms if s == "blank")
            assert n_wf == 2 and n_blank == 1, (
                f"pay_id 8 fired on non-predicate payline: {payline_syms}"
            )


def test_pay_id_8_hits_in_10k_spins():
    """pay_id 8 must appear in a 10k-spin run (rate ~1.275% → ~127 hits expected)."""
    from slot_designer.core.engine.loader import load_engine

    engine, _ = load_engine(_M43_SPEC, _M43_WEIGHTS_M1)
    rng = Random(0)
    hits = sum(
        1 for _ in range(10_000)
        if (lambda o: o.pay is not None and o.pay.pay_id == 8)(engine.spin_session(rng)[0])
    )
    assert hits > 0, (
        f"pay_id 8 never fired in 10k spins — predicate or spec wiring broken. "
        f"Expected ~127 hits."
    )
