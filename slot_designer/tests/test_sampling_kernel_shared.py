"""Regression: sample_one_chunk is the single kernel both sampling paths use.

Why this matters (2026-04-23):
  Before refactor, emit_simulation_to_dir (used by simulate.py) and
  virtual_analyzer._run_simulator_chunk (used by virtual console's
  POST /api/batch-run) had duplicated per-chunk loops. When ST=14/ST=15
  feature emission landed in emit_session, only the driver.py loop got
  updated — virtual_analyzer kept calling emit_round → console showed
  RTP=43.25% (base only) while direct simulate.py showed 94%.

Post-refactor both paths route through ``sample_one_chunk``. This test
locks in:
  1. sample_one_chunk returns the expected (chunk, win, bet) tuple
     shape with a feature-engine machine (M15sim) that triggers ST=14
     rounds.
  2. Emitted rounds include ST=1 + ST=14 + ST=15 sequences when feature
     fires (no silent regression back to ST=1-only).
  3. _run_simulator_chunk (virtual_analyzer's wrapper) produces
     byte-identical output to sample_one_chunk called directly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.backend.virtual_analyzer import _run_simulator_chunk
from slot_designer.emitter.driver import (
    compute_schema_fingerprint_for,
    sample_one_chunk,
)
from slot_designer.engine.loader import load_engine


_SPEC = _ROOT / "slot_designer" / "specs" / "M15.spec.json"
_WEIGHTS = _ROOT / "slot_designer" / "weights" / "M15" / "mode_1" / "weights.json"


def _build_engine():
    engine, _ = load_engine(_SPEC, _WEIGHTS)
    return engine


def test_sample_one_chunk_emits_feature_st14_st15():
    """M15sim with feature_spec wired: every triggered spin must produce
    ST=1 (ReMarks='Trigger') + ST=14 × N + ST=15 sequence in that order.
    """
    engine = _build_engine()
    assert engine.feature_spec is not None, (
        "M15sim must load a feature_spec; check loader.py wiring"
    )
    assert engine.feature_trigger_pay_id == 666, (
        f"M15sim trigger pay_id should be 666; got {engine.feature_trigger_pay_id}"
    )

    # Many spins so a trigger is near-certain at ~1.14% trigger rate.
    rng = Random(42)
    schema_fp = compute_schema_fingerprint_for(
        engine, mode=1, spins_per_robot=1000
    )
    chunk, win, bet = sample_one_chunk(
        engine,
        machine="M15sim",
        mode=1,
        chunk_index=1,
        robots=5,
        spins_per_robot=1000,
        rng=rng,
        schema_fp=schema_fp,
    )

    # Chunk envelope sanity
    assert chunk["_machine"] == "M15sim"
    assert chunk["_mode"] == 1
    assert chunk["_chunk_index"] == 1
    assert bet == 5 * 1000 * 1000, (
        f"bet should be robots*spins_per_robot*bet_amount = 5M; got {bet}"
    )

    # Parse one robot's roundResult and validate feature-session structure.
    any_trigger_seen = False
    for robot in chunk["response"]:
        rr = json.loads(robot["roundResult"])
        i = 0
        n = len(rr)
        while i < n:
            r = rr[i]
            st = r.get("SpinType")
            if st == 1 and r.get("ReMarks") == "Trigger":
                any_trigger_seen = True
                # Next rounds should be ST=14 × N then ST=15
                j = i + 1
                n_st14 = 0
                while j < n and rr[j].get("SpinType") == 14:
                    assert rr[j].get("WinCredits", -1) > 0, (
                        "ST=14 reveal should carry a non-zero WinCredits "
                        "(the offer value shown to player)"
                    )
                    assert rr[j].get("BetAmount", -1) == 0, (
                        "ST=14 feature sub-rounds charge no bet"
                    )
                    n_st14 += 1
                    j += 1
                assert 1 <= n_st14 <= 4, (
                    f"1..4 ST=14 rounds per trigger; got {n_st14}"
                )
                assert j < n and rr[j].get("SpinType") == 15, (
                    "ST=15 end marker must follow the ST=14 sequence"
                )
                end_marker = rr[j]
                assert "WinCredits" not in end_marker, (
                    "Production ST=15 has no WinCredits field; emitting one "
                    "overrides last_non_none WinCredits and breaks "
                    "TopDollar bucket_distribution (user-visible bug)"
                )
                assert end_marker.get("WinAmount", 0) > 0, (
                    "ST=15 WinAmount carries the accepted session payout"
                )
                i = j + 1
            else:
                i += 1

    assert any_trigger_seen, (
        "5k spins at 1.14% trigger rate should yield multiple triggers; "
        "none seen → feature emission is broken"
    )


def test_virtual_analyzer_chunk_matches_driver_chunk():
    """``_run_simulator_chunk`` (virtual console path) must produce the
    same output as ``sample_one_chunk`` (direct simulate.py path).

    Guarantees the two callers share a single implementation — any
    divergence (e.g. one path regressing to emit_round-only) is caught here.
    """
    engine1 = _build_engine()
    engine2 = _build_engine()

    schema_fp = compute_schema_fingerprint_for(
        engine1, mode=1, spins_per_robot=200
    )

    chunk_driver, win_d, bet_d = sample_one_chunk(
        engine1,
        machine="M15sim",
        mode=1,
        chunk_index=1,
        robots=3,
        spins_per_robot=200,
        rng=Random(12345),
        schema_fp=schema_fp,
        config_md5="",
        code_md5="",
    )

    spec = json.loads(_SPEC.read_text(encoding="utf-8"))

    chunk_va, win_v, bet_v = _run_simulator_chunk(
        engine2,
        spec,
        chunk_index=1,
        robots=3,
        spins_per_robot=200,
        rng=Random(12345),
        schema_fp=schema_fp,
        md5s=("", ""),
        # Pass explicit machine/mode to match what the CLI does
        # (see regression tests below for the bug this prevented).
        machine="M15sim",
        mode=1,
    )

    assert win_v == win_d, (
        f"virtual vs driver chunk win mismatch: {win_v} vs {win_d}"
    )
    assert bet_v == bet_d
    # Envelopes should be byte-identical once both are tagged the same way.
    assert chunk_va["_machine"] == chunk_driver["_machine"] == "M15sim"
    assert chunk_va["_mode"] == chunk_driver["_mode"] == 1
    assert chunk_va["_chunk_index"] == chunk_driver["_chunk_index"]
    assert len(chunk_va["response"]) == len(chunk_driver["response"])
    for r_v, r_d in zip(chunk_va["response"], chunk_driver["response"]):
        assert r_v["roundResult"] == r_d["roundResult"]
        assert r_v["analysisResult"] == r_d["analysisResult"]


def test_virtual_analyzer_chunk_tags_virtual_machine_and_runtime_mode():
    """Regression (2026-04-23): ``_run_simulator_chunk`` must tag chunks
    with the VIRTUAL machine name and the CALLER-requested mode, not
    spec's source machine / default mode.

    The bug: an earlier implementation hard-coded
    ``machine=spec["machine"], mode=int(spec["mode"])``. For M15.spec.json
    (``machine="M15", mode=1``), mode 7 sampling tagged every chunk as
    ``_machine=M15 _mode=1``. The analyzer's second-pass replay then:
      * skipped all 171 chunks because md5 envelope (computed from
        M15sim/mode_7's weights) appeared to mismatch whatever it was
        comparing against (behavior depended on the analyzer's own md5
        filter semantics, but the end result was 0 spins counted)
      * wrote ``total_spins: 0`` into the summary
      * backend promoted the run to failed with "sampling produced 0
        spins after 0 chunk(s); stop_reason=from_cache_complete"

    User-visible symptom: batch log scrolled through "168 chunks ·
    3,360,000 spins · RTP=32.57%" (the live loop was fine), then the
    replay stage immediately reported 0 spins per batch and the run
    failed with the confusing "0 spins after 0 chunk(s)" message.

    Fixed by accepting optional ``machine`` / ``mode`` kwargs and
    having the CLI always pass ``args.machine`` + ``args.rtp_mode``.
    """
    engine = _build_engine()
    spec = json.loads(_SPEC.read_text(encoding="utf-8"))
    schema_fp = compute_schema_fingerprint_for(engine, mode=7, spins_per_robot=50)

    chunk, _, _ = _run_simulator_chunk(
        engine, spec, chunk_index=1, robots=1, spins_per_robot=50,
        rng=Random(1), schema_fp=schema_fp, md5s=("cfg", "code"),
        machine="M15sim", mode=7,
    )
    assert chunk["_machine"] == "M15sim", (
        f"chunk envelope must tag the virtual machine name, got {chunk['_machine']!r}"
    )
    assert chunk["_mode"] == 7, (
        f"chunk envelope must tag the caller-requested mode, got {chunk['_mode']!r}"
    )


def test_virtual_analyzer_chunk_falls_back_to_spec_when_args_omitted():
    """Backwards compatibility: old callers that pass only ``spec`` (no
    explicit machine/mode kwargs) still get the spec's machine + default
    mode. This preserves any legacy test harness; the CLI always passes
    the explicit args so production pipelines never hit this fallback.
    """
    engine = _build_engine()
    spec = json.loads(_SPEC.read_text(encoding="utf-8"))
    schema_fp = compute_schema_fingerprint_for(engine, mode=1, spins_per_robot=50)

    chunk, _, _ = _run_simulator_chunk(
        engine, spec, chunk_index=1, robots=1, spins_per_robot=50,
        rng=Random(1), schema_fp=schema_fp, md5s=("", ""),
    )
    assert chunk["_machine"] == spec["machine"]
    assert chunk["_mode"] == int(spec["mode"])


if __name__ == "__main__":
    test_sample_one_chunk_emits_feature_st14_st15()
    print("ok  test_sample_one_chunk_emits_feature_st14_st15")
    test_virtual_analyzer_chunk_matches_driver_chunk()
    print("ok  test_virtual_analyzer_chunk_matches_driver_chunk")
    print("2/2 passed")
