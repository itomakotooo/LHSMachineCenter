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
    # pay_id 8 deliberately deferred (LOW confidence rule per 01c §3 ambiguity)
    assert pay_ids == [2, 3, 4, 5, 6, 7, 9]
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
