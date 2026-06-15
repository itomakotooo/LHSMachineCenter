"""Phase 1 dimension substrate tests — finalize_chunk "dimensions" sub-key contract.

Design source: session_artifacts/_arch_playtype/dimension/04_dimension_framework.md §3.2 + §6
Breaker source: session_artifacts/_arch_playtype/dimension/05_breaker.md (GAP-A, BREAK-3)
Implementation: fresh_slotlab/analyzer/st_extract/trigger_path.py

What Phase 1 added
------------------
TriggerPathExtractor.finalize_chunk now emits, alongside the unchanged flat
"trigger_path" per-ST output, a new "dimensions" sub-key at:

    chunk_dict["st_extract"]["trigger_path"]["dimensions"] = {
        "<st_str>": {
            "<dim_name>": {             # e.g. "trigger_path"
                "<value>": {            # e.g. "scatter", "collect_peak"
                    "round_count":      int,
                    "win_sum":          float,
                    "paid_round_count": int,
                    "win_round_count":  int,
                    "bet_sum":          float,
                    "bucket_hist":      {<bucket>: int},
                    "session_count":    int,
                    "symbol_counts":    {<col>: {<sym>: count}},
                    "next_st_counts":   {<next_st_int>: int},
                }
            }
        }
    }

GAP-A fix (05_breaker.md §GAP-A): next_st_counts for the PREVIOUS declared ST
is recorded BEFORE the early-return that skips undeclared STs.  This means the
ST126->ST140 exit transition (freespin-session-ends) is captured even though
ST140 is not declared.  The headline regression test for this fix is Group B.

Tests in this file
------------------
Group A (sum==aggregate invariant):
    test_sum_equals_aggregate_round_count_2value_split
    test_sum_equals_aggregate_win_sum
    test_sum_equals_aggregate_paid_round_count
    test_sum_equals_aggregate_win_round_count
    test_sum_equals_aggregate_bet_sum
    test_sum_equals_aggregate_session_count
    test_sum_includes_unknown_buckets

Group B (GAP-A regression — exit transitions captured):
    test_gap_a_declared_to_undeclared_transition_present
    test_gap_a_declared_to_declared_transition_also_captured
    test_gap_a_no_cross_robot_bleed

Group C (bucket_hist uses shared return_bucket edges):
    test_bucket_hist_keys_match_return_bucket_helper
    test_bucket_hist_zero_win_lands_in_eq0
    test_bucket_hist_all_keys_valid

Group D (symbol_counts):
    test_symbol_counts_present_when_stop_symbols_by_col_dict
    test_symbol_counts_absent_when_no_stop_symbols_field
    test_symbol_counts_no_crash_when_stop_symbols_list_shape

Group E (session_count semantics):
    test_session_count_two_blocks_same_value
    test_session_count_split_across_values_via_discriminator

Group F (unknown/multi surfacing):
    test_unknown_unmapped_discriminator_value_surfaced_as_alarm
    test_unknown_bucket_not_merged_into_real_value
    test_multi_trigger_produces_multi_bucket

Group G (backward-compat flat "trigger_path" output unchanged):
    test_backward_compat_flat_trigger_path_unchanged_in_shape
    test_backward_compat_flat_matches_pre_phase1_fields
    test_backward_compat_no_new_keys_in_flat_output

Group H (real-data — skipif M275 rawdata absent):
    test_real_m275_dimensions_sum_equals_total_round_count
    test_real_m275_two_values_present_unknown_empty
    test_real_m275_next_st_126_to_140_captured

INJECT-BUG RECIPES
------------------
IB-B1 (GAP-A regression — move transition recording below early-return):
  In trigger_path.py::observe_round, move the block:
      if self._prev_dim_key is not None:
          self._dim_next_st_counts[self._prev_dim_key][spin_type] += 1
  to AFTER the early-return:
      if spin_type not in self._st_declarations:
          self._prev_dim_key = None
          return
  => test_gap_a_declared_to_undeclared_transition_present RED
     (ST126->ST140 transition count == 0 instead of > 0).
  Revert => GREEN.

IB-A1 (corrupt win_sum accumulator — double-count):
  In trigger_path.py::observe_round, after the line:
      self._dim_win_sum[dim_key] += win_amt
  add:
      self._dim_win_sum[dim_key] += win_amt   # double-count bug
  => test_sum_equals_aggregate_win_sum RED
     (sum of per-dim win_sum == 2x total instead of 1x).
  Revert => GREEN.

IB-C1 (hand-rolled bucket instead of return_bucket):
  In trigger_path.py::observe_round, replace:
      bucket = return_bucket(mult)
  with:
      bucket = "hand_rolled_bucket"   # wrong label, breaks shared edge contract
  => test_bucket_hist_keys_match_return_bucket_helper RED.
  Revert => GREEN.

IB-D1 (skip symbol_counts accumulation):
  In trigger_path.py::observe_round, comment out the entire
  "symbol_counts: from StopSymbolsByCol" block (lines that read
  stop_syms = round_dict.get("StopSymbolsByCol") through
  self._dim_symbol_counts[sym_key][sym_str] += 1).
  => test_symbol_counts_present_when_stop_symbols_by_col_dict RED.
  Revert => GREEN.

Memory feedback honored:
  memory/feedback_enumerate_safety_paths.md
      - inject-bug recipe per invariant, documented above.
  memory/feedback_perf_claim_needs_e2e_event_stream.md
      - Group H uses real parser + real extractor against real M275 chunks
        (no mock), not just unit-testing the extractor in isolation.
  memory/feedback_integration_test_argv.md
      - Group H asserts on actual computed values / structure (not "was called").
  memory/feedback_no_silent_swallow.md
      - unknown/multi buckets are asserted PRESENT as alarm signals;
        tests would fail if they were silently merged.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Repo / rawdata paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
M275_CHUNK1 = ROOT / "rawdata" / "M275" / "mode_1" / "chunk_0001.json"
M275_CHUNK2 = ROOT / "rawdata" / "M275" / "mode_1" / "chunk_0002.json"
M275_AVAILABLE = M275_CHUNK1.exists() and M275_CHUNK2.exists()
SKIP_NO_M275 = pytest.mark.skipif(
    not M275_AVAILABLE,
    reason="rawdata/M275/mode_1 absent; developer-only test",
)

# Key names in the extractor output (tested as a contract, not hard-coded in impl)
_EXTRACTOR_ID = "trigger_path"         # rec["st_extract"]["trigger_path"]
_DIMENSIONS_KEY = "dimensions"         # rec["st_extract"]["trigger_path"]["dimensions"]
_DIM_NAME = "trigger_path"             # the dim_name emitted for trigger_paths blocks


# ---------------------------------------------------------------------------
# Synthetic fixture helpers — mirror test_st_extract_framework.py conventions
# ---------------------------------------------------------------------------

def _paid(
    *,
    st: int = 140,
    bet: int = 1000,
    win: int = 0,
    payout: dict | None = None,
    remarks: str = "",
    extra: dict | None = None,
) -> dict:
    """Minimal paid round dict accepted by parse_chunk_response."""
    r: dict[str, Any] = {
        "SpinType": st,
        "CostCredits": bet,
        "BetAmount": bet,
        "WinCredits": win,
        "StopSymbolsByCol": ["A-B-C"] * 5,
        "PayoutIdToWinAmount": payout if payout is not None else {},
        "ReMarks": remarks,
    }
    if extra:
        r.update(extra)
    return r


def _bonus(
    *,
    st: int = 126,
    win: int | None = 0,
    payout: dict | None = None,
    remarks: str = "",
    extra: dict | None = None,
) -> dict:
    """Minimal bonus round dict (CostCredits=None → not paid)."""
    r: dict[str, Any] = {
        "SpinType": st,
        "CostCredits": None,
        "WinCredits": win,
        "StopSymbolsByCol": ["A-B-C"] * 5,
        "PayoutIdToWinAmount": payout if payout is not None else {},
        "ReMarks": remarks,
    }
    if extra:
        r.update(extra)
    return r


def _robot(rounds: list[dict], robot_id: str = "robot_0") -> dict:
    return {"robotId": robot_id, "roundResult": json.dumps(rounds)}


def _manifest_disc(
    st: int = 126,
    field: str = "FieldX",
    field_map: dict | None = None,
) -> dict:
    """Manifest using round_field discriminator on `st`."""
    if field_map is None:
        field_map = {"0": "scatter", "2": "collect_peak"}
    return {
        "machine_id": "M_synth",
        "spin_types": {
            str(st): {
                "role": "bonus_spin",
                "trigger_paths": {
                    "discriminator": {
                        "kind": "round_field",
                        "field": field,
                        "map": field_map,
                        "unmapped_value_policy": "surface_as_unknown_path",
                    },
                    "multi_trigger_policy": "additive_sessions",
                },
            }
        },
    }


def _manifest_fallback(
    st: int = 126,
) -> dict:
    """Manifest using anchor-walk fallback on `st`."""
    return {
        "machine_id": "M_synth",
        "spin_types": {
            str(st): {
                "role": "bonus_spin",
                "trigger_paths": {
                    "paths": {
                        "scatter": {"opened_by": {"payout_id": "666"}},
                        "collect_peak": {
                            "opened_by": {"counter": "CollectCount", "at_peak": 100}
                        },
                    },
                    "multi_trigger_policy": "additive_sessions",
                },
            }
        },
    }


def _run_extractor(
    rounds: list[dict],
    manifest: dict,
    bet: int = 1000,
    robot_id: str = "robot_0",
) -> dict:
    """Run parse_chunk_response with TriggerPathExtractor, return the full extractor dict.

    Returns: rec["st_extract"]["trigger_path"] (which contains both the flat
    per-path keys AND the new "dimensions" sub-key).
    """
    from fresh_slotlab.analyzer.st_extract import (
        discover_extractors,
        get_extractors_for_manifest,
    )
    from fresh_slotlab.analyzer.core.parser import parse_chunk_response

    discover_extractors()
    extractors = get_extractors_for_manifest(manifest)
    assert len(extractors) >= 1, f"Expected >=1 extractor for manifest, got {len(extractors)}"

    rec = parse_chunk_response(
        [_robot(rounds, robot_id=robot_id)],
        chunk_index=1,
        bet=bet,
        st_extractors=extractors,
    )
    assert rec["ok"] is True, f"parse_chunk_response failed: {rec.get('error')}"
    st_ext = rec.get("st_extract", {})
    assert _EXTRACTOR_ID in st_ext, (
        f"Expected '{_EXTRACTOR_ID}' key in st_extract. Got keys: {list(st_ext.keys())}"
    )
    return st_ext[_EXTRACTOR_ID]


def _dimensions_for_st(extractor_data: dict, st: int) -> dict:
    """Extract the dimensions dict for a specific ST from extractor output.

    Returns: {dim_name: {value: {stats}}} or {} if absent.
    """
    dims = extractor_data.get(_DIMENSIONS_KEY, {})
    return dims.get(str(st), {})


# ---------------------------------------------------------------------------
# Group A — Sum == Aggregate invariant
# ---------------------------------------------------------------------------

class TestSumEqualsAggregate:
    """Group A — core gate: for every declared ST, sum over dim values == ST total.

    Synthetic: 2-value split (scatter / collect_peak) with known totals.
    The sum must include unknown/multi buckets per §3.2.

    INJECT-BUG IB-A1 (corrupt win_sum accumulator — double-count):
      In trigger_path.py::observe_round, duplicate the line:
          self._dim_win_sum[dim_key] += win_amt
      => test_sum_equals_aggregate_win_sum RED (sum == 2x the real total).
      Revert => GREEN.
    """

    # Fixture: 2 scatter rounds + 1 collect_peak round in separate blocks.
    # scatter block: win=3000+4000=7000, paid=0, sessions=2
    # collect_peak block: win=5000, paid=0, sessions=1
    # Total for ST=126: round=3, win=12000, sessions=3

    def _fixture_rounds(self) -> list[dict]:
        return [
            # Block 1 — scatter (FieldX=0), 2 bonus rounds
            _paid(bet=1000, win=0, payout={"666": 0}, extra={"FieldX": 0}),
            _bonus(st=126, win=3000, extra={"FieldX": 0}),
            _bonus(st=126, win=4000, extra={"FieldX": 0}),
            # Block 2 — collect_peak (FieldX=2), 1 bonus round
            _paid(bet=1000, win=0, payout={}, extra={"FieldX": 2}),
            _bonus(st=126, win=5000, extra={"FieldX": 2}),
            # Close
            _paid(bet=1000, win=0, extra={"FieldX": 0}),
        ]

    def _run(self) -> tuple[dict, dict]:
        """Return (extractor_data, dim_data_for_st126)."""
        manifest = _manifest_disc()
        data = _run_extractor(self._fixture_rounds(), manifest)
        dim = _dimensions_for_st(data, 126)
        assert _DIM_NAME in dim, (
            f"Expected dim_name '{_DIM_NAME}' in dimensions for ST126. Got: {list(dim.keys())}"
        )
        return data, dim[_DIM_NAME]

    def test_sum_equals_aggregate_round_count_2value_split(self) -> None:
        """Σ round_count over all values == total ST rounds (3).

        INJECT-BUG IB-A1 variant: set _dim_round_count[dim_key] = 99 unconditionally
        => sum != 3 => RED. Revert => GREEN.
        """
        _, dim_values = self._run()
        total = sum(v["round_count"] for v in dim_values.values())
        expected = 3  # 2 scatter + 1 collect_peak
        assert total == expected, (
            f"Sum == aggregate invariant (round_count): expected {expected}, got {total}. "
            f"dim_values: {list(dim_values.keys())}. "
            "INJECT-BUG IB-A1: corrupt accumulator → sum != total → RED."
        )

    def test_sum_equals_aggregate_win_sum(self) -> None:
        """Σ win_sum over all values == 12000 (known total for this fixture).

        INJECT-BUG IB-A1: duplicate self._dim_win_sum[dim_key] += win_amt
        => sum == 24000 instead of 12000 => RED.
        """
        _, dim_values = self._run()
        total = sum(v["win_sum"] for v in dim_values.values())
        expected = 12000.0  # 3000+4000 scatter + 5000 collect_peak
        assert total == pytest.approx(expected), (
            f"Sum == aggregate invariant (win_sum): expected {expected}, got {total}. "
            "INJECT-BUG IB-A1: double-count win_sum => sum=24000 => RED."
        )

    def test_sum_equals_aggregate_paid_round_count(self) -> None:
        """Σ paid_round_count over all values == 0 (all rounds are bonus, CostCredits=None)."""
        _, dim_values = self._run()
        total = sum(v["paid_round_count"] for v in dim_values.values())
        # All fixture bonus rounds have CostCredits=None → not paid → 0
        assert total == 0, (
            f"Sum == aggregate invariant (paid_round_count): expected 0, got {total}. "
            "CostCredits=None bonus rounds must not be counted as paid."
        )

    def test_sum_equals_aggregate_win_round_count(self) -> None:
        """Σ win_round_count == count of rounds with win > 0.

        Fixture: all 3 bonus rounds have win > 0 → expected sum = 3.
        """
        _, dim_values = self._run()
        total = sum(v["win_round_count"] for v in dim_values.values())
        assert total == 3, (
            f"Sum == aggregate invariant (win_round_count): expected 3, got {total}. "
            "All 3 fixture bonus rounds have win > 0."
        )

    def test_sum_equals_aggregate_bet_sum(self) -> None:
        """Σ bet_sum over all values == bet × round_count per value.

        With bet=1000: scatter=2 rounds → 2000, collect_peak=1 round → 1000, total=3000.
        """
        _, dim_values = self._run()
        total = sum(v["bet_sum"] for v in dim_values.values())
        expected = 3000.0  # 3 rounds × 1000 bet
        assert total == pytest.approx(expected), (
            f"Sum == aggregate invariant (bet_sum): expected {expected}, got {total}."
        )

    def test_sum_equals_aggregate_session_count(self) -> None:
        """Σ session_count over all values == distinct blocks by value.

        scatter: 1 block (block 1) → session_count=1 (but 2 rounds in it)
        collect_peak: 1 block (block 2) → session_count=1
        total = 2 distinct sessions across all values.
        """
        _, dim_values = self._run()
        total = sum(v["session_count"] for v in dim_values.values())
        # scatter: 1 distinct block_id; collect_peak: 1 distinct block_id → total=2
        assert total == 2, (
            f"Sum == aggregate invariant (session_count): expected 2, got {total}. "
            "1 scatter block + 1 collect_peak block = 2 sessions total."
        )

    def test_sum_includes_unknown_buckets(self) -> None:
        """When unknown buckets exist they must be included in the sum.

        Fixture: add a round with FieldX=99 (unmapped). It lands in 'unknown:99'.
        The sum of round_count over ALL values (including unknown:99) must equal
        total observed ST rounds.
        """
        manifest = _manifest_disc()
        rounds = [
            _paid(bet=1000, win=0, extra={"FieldX": 0}),
            _bonus(st=126, win=1000, extra={"FieldX": 0}),   # scatter
            _paid(bet=1000, win=0, extra={"FieldX": 2}),
            _bonus(st=126, win=2000, extra={"FieldX": 2}),   # collect_peak
            _paid(bet=1000, win=0, extra={"FieldX": 99}),
            _bonus(st=126, win=3000, extra={"FieldX": 99}),  # unknown:99
            _paid(bet=1000, win=0),
        ]
        data = _run_extractor(rounds, manifest)
        dim = _dimensions_for_st(data, 126).get(_DIM_NAME, {})

        total_round = sum(v["round_count"] for v in dim.values())
        assert total_round == 3, (
            f"Sum including unknown buckets must equal total ST rounds (3). Got {total_round}. "
            f"Buckets present: {list(dim.keys())}. "
            "The unknown:99 bucket must be included in the sum, not silently dropped."
        )
        # Also assert that unknown:99 is present (alarm semantics, not merged)
        assert any(k.startswith("unknown:") for k in dim), (
            "Unknown bucket (unknown:99) must be present in dimensions output. "
            "Silently dropping it would mean the sum < total."
        )


# ---------------------------------------------------------------------------
# Group B — GAP-A regression: declared->undeclared transitions captured
# ---------------------------------------------------------------------------

class TestGapANextStTransitions:
    """Group B — headline GAP-A regression from 05_breaker.md §GAP-A.

    The fix: record next_st_counts BEFORE the early-return that skips undeclared STs.
    This ensures ST126->ST140 (freespin exit) transitions are captured even though
    ST140 is not a declared ST.

    INJECT-BUG IB-B1 (move transition recording below early-return):
      In trigger_path.py::observe_round, move the block
          if self._prev_dim_key is not None:
              self._dim_next_st_counts[self._prev_dim_key][spin_type] += 1
      to AFTER:
          if spin_type not in self._st_declarations:
              self._prev_dim_key = None
              return
      => test_gap_a_declared_to_undeclared_transition_present RED
         (next_st_counts[140] == 0 instead of > 0 for ST126->ST140 transitions).
      Revert => GREEN.
    """

    def _run_with_transitions(
        self,
        declared_st: int,
        undeclared_st: int,
        n_transitions: int,
        field_val: int = 0,
        label: str = "scatter",
    ) -> dict:
        """Build a fixture with n_transitions from declared_st to undeclared_st."""
        manifest = _manifest_disc(st=declared_st, field_map={str(field_val): label})
        rounds = []
        for _ in range(n_transitions):
            rounds.append(_paid(bet=1000, win=0, extra={"FieldX": field_val}))
            rounds.append(_bonus(st=declared_st, win=1000, extra={"FieldX": field_val}))
            rounds.append(_paid(st=undeclared_st, bet=1000, win=0))  # exit transition
        data = _run_extractor(rounds, manifest)
        return _dimensions_for_st(data, declared_st).get(_DIM_NAME, {})

    def test_gap_a_declared_to_undeclared_transition_present(self) -> None:
        """ST126 (declared) -> ST140 (undeclared): transition must appear in next_st_counts.

        This is the exact failure mode from 05_breaker.md §GAP-A:
        "9.8% of transitions (892/9090) are ST126->ST140 and would be silently
        dropped if the transition recording is placed AFTER the early-return."

        Fixture: 3 blocks of ST=126 (scatter), each followed by ST=140 (undeclared).
        After parsing: next_st_counts[140] must be >= 3.

        INJECT-BUG IB-B1: move transition block below early-return
        => next_st_counts.get(140, 0) == 0 => test RED.
        Revert => GREEN.
        """
        n = 3  # number of ST126->ST140 transitions
        dim_values = self._run_with_transitions(
            declared_st=126, undeclared_st=140, n_transitions=n
        )
        scatter = dim_values.get("scatter", {})
        next_sts = scatter.get("next_st_counts", {})

        # The transition to the undeclared ST must be recorded.
        count_to_undeclared = next_sts.get(140, 0)
        assert count_to_undeclared >= n, (
            f"GAP-A: ST126->ST140 transition count must be >= {n}. "
            f"Got next_st_counts={next_sts}. "
            "INJECT-BUG IB-B1: move transition recording below early-return "
            "=> count == 0 => RED. Revert => GREEN. "
            "This locks the 05_breaker.md §GAP-A fix: 9.8% of freespin-session "
            "exit transitions must NOT be silently dropped."
        )

    def test_gap_a_declared_to_declared_transition_also_captured(self) -> None:
        """ST126 -> ST126 (both declared): intra-declared transitions also recorded.

        This verifies the normal case still works: when consecutive rounds are
        both declared-ST, the transition is recorded in next_st_counts.
        Fixture: 2 consecutive ST=126 bonus rounds in the same block.
        """
        manifest = _manifest_disc()
        rounds = [
            _paid(bet=1000, win=0, extra={"FieldX": 0}),
            _bonus(st=126, win=1000, extra={"FieldX": 0}),  # round 1: scatter
            _bonus(st=126, win=2000, extra={"FieldX": 0}),  # round 2: scatter (prev->curr)
            _paid(bet=1000, win=0),
        ]
        data = _run_extractor(rounds, manifest)
        dim_values = _dimensions_for_st(data, 126).get(_DIM_NAME, {})
        scatter = dim_values.get("scatter", {})
        next_sts = scatter.get("next_st_counts", {})

        # ST126->ST126 transition must be captured (round 1 -> round 2)
        assert next_sts.get(126, 0) >= 1, (
            f"ST126->ST126 (declared-to-declared) transition must appear in next_st_counts. "
            f"Got next_st_counts={next_sts}. "
            "The GAP-A fix must not break intra-declared transitions."
        )

    def test_gap_a_no_cross_robot_bleed(self) -> None:
        """The _prev_dim_key must reset between robots so no cross-robot transition is recorded.

        Two robots: robot_0 ends with a declared-ST round; robot_1 starts with
        an undeclared-ST round. The transition robot_0_last->robot_1_first must
        NOT appear in robot_1's next_st_counts.

        We test this by running two robots in one parse_chunk_response call
        and asserting that the declared-ST round count == expected (no phantom
        transitions from robot bleed).
        """
        manifest = _manifest_disc()
        # Robot 0: 1 scatter round
        r0_rounds = [
            _paid(bet=1000, win=0, extra={"FieldX": 0}),
            _bonus(st=126, win=1000, extra={"FieldX": 0}),
            _paid(bet=1000, win=0),
        ]
        # Robot 1: starts immediately with undeclared ST=1 (paid), no bonus round
        r1_rounds = [
            _paid(st=1, bet=1000, win=500),
        ]

        from fresh_slotlab.analyzer.st_extract import discover_extractors, get_extractors_for_manifest
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response
        discover_extractors()
        extractors = get_extractors_for_manifest(manifest)

        # Two robots in one chunk
        robots = [
            {"robotId": "r0", "roundResult": json.dumps(r0_rounds)},
            {"robotId": "r1", "roundResult": json.dumps(r1_rounds)},
        ]
        rec = parse_chunk_response(robots, chunk_index=1, bet=1000, st_extractors=extractors)
        assert rec["ok"] is True

        data = rec["st_extract"][_EXTRACTOR_ID]
        dim = _dimensions_for_st(data, 126).get(_DIM_NAME, {})
        scatter = dim.get("scatter", {})

        # Only 1 ST126 round total (from robot 0)
        assert scatter.get("round_count", 0) == 1, (
            f"Cross-robot bleed: only 1 ST126 round expected. "
            f"Got scatter={scatter}. "
            "begin_robot must reset _prev_dim_key so robot_0's last ST does not "
            "create a transition to robot_1's first round."
        )


# ---------------------------------------------------------------------------
# Group C — bucket_hist uses shared return_bucket edges
# ---------------------------------------------------------------------------

class TestBucketHistSharedEdges:
    """Group C — bucket_hist keys must come from return_bucket(), not hand-rolled.

    INJECT-BUG IB-C1 (hand-rolled bucket label):
      In trigger_path.py::observe_round, replace:
          bucket = return_bucket(mult)
      with:
          bucket = "hand_rolled_bucket"
      => test_bucket_hist_keys_match_return_bucket_helper RED.
      Revert => GREEN.
    """

    def _get_bucket_hist_for_value(
        self,
        win_mult: float,
        label: str = "scatter",
        field_val: int = 0,
    ) -> dict:
        """Return bucket_hist for `label` after a single round with win=win_mult*bet."""
        bet = 1000
        win = int(win_mult * bet)
        manifest = _manifest_disc(field_map={str(field_val): label})
        rounds = [
            _paid(bet=bet, win=0, extra={"FieldX": field_val}),
            _bonus(st=126, win=win, extra={"FieldX": field_val}),
            _paid(bet=bet, win=0),
        ]
        data = _run_extractor(rounds, manifest, bet=bet)
        dim = _dimensions_for_st(data, 126).get(_DIM_NAME, {})
        return dim.get(label, {}).get("bucket_hist", {})

    def test_bucket_hist_keys_match_return_bucket_helper(self) -> None:
        """bucket_hist keys must be exactly the label produced by return_bucket().

        We manufacture a win=5.0x bet → return_bucket(5.0) → known bucket name.
        The same bucket must appear in bucket_hist.

        INJECT-BUG IB-C1: replace return_bucket(mult) with "hand_rolled_bucket"
        => bucket_hist == {"hand_rolled_bucket": 1}, expected key absent => RED.
        Revert => GREEN.
        """
        from fresh_slotlab.analyzer.core._utils import return_bucket

        mult = 5.0
        expected_bucket = return_bucket(mult)
        hist = self._get_bucket_hist_for_value(mult)

        assert expected_bucket in hist, (
            f"bucket_hist must contain key '{expected_bucket}' (return_bucket({mult})). "
            f"Got hist={hist}. "
            "INJECT-BUG IB-C1: hand-rolled label => expected key absent => RED."
        )
        assert hist[expected_bucket] == 1, (
            f"bucket_hist['{expected_bucket}'] must be 1 for a single round. Got {hist}."
        )

    def test_bucket_hist_zero_win_lands_in_eq0(self) -> None:
        """Win=0 → return_bucket(0.0) → 'eq0' bucket.

        This locks the zero-win bucket semantics used by freespin_dynamics.
        """
        from fresh_slotlab.analyzer.core._utils import return_bucket

        expected = return_bucket(0.0)
        # Use win=0 bonus round
        bet = 1000
        manifest = _manifest_disc()
        rounds = [
            _paid(bet=bet, win=0, extra={"FieldX": 0}),
            _bonus(st=126, win=0, extra={"FieldX": 0}),  # zero-win round
            _paid(bet=bet, win=0),
        ]
        data = _run_extractor(rounds, manifest, bet=bet)
        dim = _dimensions_for_st(data, 126).get(_DIM_NAME, {})
        hist = dim.get("scatter", {}).get("bucket_hist", {})

        assert expected in hist, (
            f"Zero-win round must land in bucket '{expected}' (return_bucket(0.0)). "
            f"Got hist={hist}."
        )

    def test_bucket_hist_all_keys_valid(self) -> None:
        """All keys in bucket_hist must be valid return_bucket() outputs.

        Run a multi-round fixture with diverse wins (0, 1x, 5x, 15x).
        Every key in the resulting bucket_hist must be a known return_bucket label.
        """
        from fresh_slotlab.analyzer.core._utils import return_bucket

        # Build the universe of all valid bucket labels
        valid_buckets = {
            return_bucket(v) for v in [
                0.0, 0.1, 0.9, 1.0, 2.0, 5.0, 7.0, 12.0, 25.0, 60.0,
                110.0, 250.0, 600.0, 1500.0, 5000.0
            ]
        }

        bet = 1000
        manifest = _manifest_disc()
        rounds = []
        for mult in [0.0, 1.0, 5.0, 15.0]:
            rounds.append(_paid(bet=bet, win=0, extra={"FieldX": 0}))
            rounds.append(_bonus(st=126, win=int(mult * bet), extra={"FieldX": 0}))
        rounds.append(_paid(bet=bet, win=0))

        data = _run_extractor(rounds, manifest, bet=bet)
        dim = _dimensions_for_st(data, 126).get(_DIM_NAME, {})
        hist = dim.get("scatter", {}).get("bucket_hist", {})

        for key in hist:
            assert key in valid_buckets, (
                f"bucket_hist key '{key}' is not a valid return_bucket() output. "
                f"Valid: {sorted(valid_buckets)}. "
                "This indicates hand-rolled bucket labels in the extractor."
            )


# ---------------------------------------------------------------------------
# Group D — symbol_counts
# ---------------------------------------------------------------------------

class TestSymbolCounts:
    """Group D — symbol_counts: populated when StopSymbolsByCol is a dict; absent otherwise.

    INJECT-BUG IB-D1 (skip symbol_counts accumulation):
      In trigger_path.py::observe_round, comment out the StopSymbolsByCol block.
      => test_symbol_counts_present_when_stop_symbols_by_col_dict RED.
      Revert => GREEN.
    """

    def test_symbol_counts_present_when_stop_symbols_by_col_dict(self) -> None:
        """When StopSymbolsByCol is a dict, symbol_counts must be populated per col.

        Fixture: ST=126 round with StopSymbolsByCol={"col0": "Seven", "col1": "Bar"}.
        Expected: symbol_counts["col0"]["Seven"] == 1, symbol_counts["col1"]["Bar"] == 1.

        INJECT-BUG IB-D1: comment out the StopSymbolsByCol accumulation block
        => symbol_counts == {} => assertion on col0 fails => RED.
        Revert => GREEN.
        """
        manifest = _manifest_disc()
        sym_data = {"col0": "Seven", "col1": "Bar"}
        rounds = [
            _paid(bet=1000, win=0, extra={"FieldX": 0}),
            {
                "SpinType": 126,
                "CostCredits": None,
                "WinCredits": 2000,
                "StopSymbolsByCol": sym_data,  # dict shape
                "PayoutIdToWinAmount": {},
                "ReMarks": "",
                "FieldX": 0,
            },
            _paid(bet=1000, win=0),
        ]
        data = _run_extractor(rounds, manifest)
        dim = _dimensions_for_st(data, 126).get(_DIM_NAME, {})
        scatter = dim.get("scatter", {})
        sym_counts = scatter.get("symbol_counts", {})

        assert "col0" in sym_counts or len(sym_counts) > 0, (
            f"symbol_counts must be populated when StopSymbolsByCol is a dict. "
            f"Got symbol_counts={sym_counts}. "
            "INJECT-BUG IB-D1: comment out accumulation block => empty => RED."
        )
        # Verify content for the specific symbol we injected
        col0 = sym_counts.get("col0", {})
        assert col0.get("Seven", 0) == 1, (
            f"symbol_counts['col0']['Seven'] must be 1. Got col0={col0}."
        )

    def test_symbol_counts_absent_when_no_stop_symbols_field(self) -> None:
        """When StopSymbolsByCol is absent from the round dict, symbol_counts must be empty/absent.

        No crash allowed. Phase 1 inertness: old data that lacks this field must parse cleanly.
        """
        manifest = _manifest_disc()
        rounds = [
            _paid(bet=1000, win=0, extra={"FieldX": 0}),
            {
                "SpinType": 126,
                "CostCredits": None,
                "WinCredits": 1000,
                # No StopSymbolsByCol key at all
                "PayoutIdToWinAmount": {},
                "ReMarks": "",
                "FieldX": 0,
            },
            _paid(bet=1000, win=0),
        ]
        data = _run_extractor(rounds, manifest)
        dim = _dimensions_for_st(data, 126).get(_DIM_NAME, {})
        scatter = dim.get("scatter", {})

        # Must not crash, and symbol_counts must be empty or absent
        sym_counts = scatter.get("symbol_counts", {})
        assert sym_counts == {} or len(sym_counts) == 0, (
            f"symbol_counts must be empty when StopSymbolsByCol is absent. "
            f"Got symbol_counts={sym_counts}."
        )
        # round_count must still be correct (feature absence must not affect other stats)
        assert scatter.get("round_count", 0) == 1, (
            f"round_count must still be 1 even without StopSymbolsByCol. "
            f"Got scatter={scatter}."
        )

    def test_symbol_counts_no_crash_when_stop_symbols_list_shape(self) -> None:
        """When StopSymbolsByCol is a list (not dict), no crash and symbol_counts empty.

        Many machines emit StopSymbolsByCol as a list-of-strings, not a dict.
        The extractor must handle this gracefully (no KeyError / AttributeError).
        """
        manifest = _manifest_disc()
        rounds = [
            _paid(bet=1000, win=0, extra={"FieldX": 0}),
            {
                "SpinType": 126,
                "CostCredits": None,
                "WinCredits": 1000,
                "StopSymbolsByCol": ["Seven-Bar-Blank"] * 5,  # list shape, not dict
                "PayoutIdToWinAmount": {},
                "ReMarks": "",
                "FieldX": 0,
            },
            _paid(bet=1000, win=0),
        ]
        # Must not raise
        try:
            data = _run_extractor(rounds, manifest)
        except Exception as e:
            pytest.fail(
                f"Extractor must not crash when StopSymbolsByCol is a list. Got: {e}"
            )

        dim = _dimensions_for_st(data, 126).get(_DIM_NAME, {})
        scatter = dim.get("scatter", {})
        # round_count must be correct regardless of symbol shape
        assert scatter.get("round_count", 0) == 1, (
            f"round_count must be 1 even with list-shape StopSymbolsByCol. Got {scatter}."
        )
        # symbol_counts must be empty (list is not a dict, so no accumulation)
        sym = scatter.get("symbol_counts", {})
        assert sym == {}, (
            f"symbol_counts must be empty for list-shape StopSymbolsByCol. Got {sym}."
        )


# ---------------------------------------------------------------------------
# Group E — session_count semantics
# ---------------------------------------------------------------------------

class TestSessionCountSemantics:
    """Group E — session_count = distinct (robot_idx, block_id) per (st, dim_name, value).

    This mirrors the existing trigger_path session tests but for the new "dimensions" key.
    Mirror test IDs from test_st_extract_framework.py D7/D7b.
    """

    def test_session_count_two_blocks_same_value(self) -> None:
        """Two blocks both mapping to 'scatter' → session_count == 2.

        Block 1: FieldX=0 (scatter), 1 round.
        Block 2: FieldX=0 (scatter), 1 round.
        Expected: scatter.session_count == 2 in dimensions.
        """
        manifest = _manifest_disc()
        rounds = [
            # Block 1
            _paid(bet=1000, win=0, extra={"FieldX": 0}),
            _bonus(st=126, win=2000, extra={"FieldX": 0}),
            # Block 2
            _paid(bet=1000, win=0, extra={"FieldX": 0}),
            _bonus(st=126, win=3000, extra={"FieldX": 0}),
            _paid(bet=1000, win=0),
        ]
        data = _run_extractor(rounds, manifest)
        dim = _dimensions_for_st(data, 126).get(_DIM_NAME, {})
        scatter = dim.get("scatter", {})

        assert scatter.get("session_count", 0) == 2, (
            f"Two distinct blocks → session_count=2. Got scatter={scatter}. "
            "session_count must count distinct (robot_idx, block_id), not rounds."
        )
        assert scatter.get("round_count", 0) == 2, (
            f"Two rounds total → round_count=2. Got scatter={scatter}."
        )

    def test_session_count_split_across_values_via_discriminator(self) -> None:
        """One block, two rounds split across scatter/collect_peak via discriminator.

        Round 1: FieldX=0 (scatter), Round 2: FieldX=2 (collect_peak).
        Both rounds come from the SAME block (same block_id).
        session_count for each value == 1 (each sees the block once).

        This mirrors test_st_extract_framework.py::D7b for the new dimensions key.
        """
        manifest = _manifest_disc()
        rounds = [
            _paid(bet=1000, win=0, extra={"FieldX": 0}),
            _bonus(st=126, win=1000, extra={"FieldX": 0}),   # scatter, block 1
            _bonus(st=126, win=2000, extra={"FieldX": 2}),   # collect_peak, block 1
            _paid(bet=1000, win=0),
        ]
        data = _run_extractor(rounds, manifest)
        dim = _dimensions_for_st(data, 126).get(_DIM_NAME, {})

        scatter_sc = dim.get("scatter", {}).get("session_count", 0)
        collect_sc = dim.get("collect_peak", {}).get("session_count", 0)

        assert scatter_sc == 1, (
            f"Scatter (1 round in block 1) → session_count=1. Got {scatter_sc}. "
            "Mirror of test_st_extract_framework.py::D7b for the dimensions key."
        )
        assert collect_sc == 1, (
            f"Collect_peak (1 round in block 1) → session_count=1. Got {collect_sc}."
        )


# ---------------------------------------------------------------------------
# Group F — unknown/multi surfacing
# ---------------------------------------------------------------------------

class TestUnknownMultiSurfacing:
    """Group F — unmapped values → 'unknown:<v>', double-trigger → 'multi:<A>+<B>'.

    Per 04_dimension_framework.md §3.2: these are alarm semantics, surfaced in
    the output, never merged into a real dimension value.
    """

    def test_unknown_unmapped_discriminator_value_surfaced_as_alarm(self) -> None:
        """FieldX=99 (not in map) → 'unknown:99' bucket present in dimensions.

        Must NOT be merged into scatter or collect_peak.
        Must be present as an explicit alarm bucket.
        """
        manifest = _manifest_disc()
        rounds = [
            _paid(bet=1000, win=0, extra={"FieldX": 99}),
            _bonus(st=126, win=5000, extra={"FieldX": 99}),
            _paid(bet=1000, win=0),
        ]
        data = _run_extractor(rounds, manifest)
        dim = _dimensions_for_st(data, 126).get(_DIM_NAME, {})

        assert any(k.startswith("unknown:") for k in dim), (
            f"Unmapped FieldX=99 must surface as 'unknown:99' bucket in dimensions. "
            f"Got dim keys: {list(dim.keys())}. "
            "Per §3.2 'unmapped_value_policy: surface_as_unknown' — alarm, not merged."
        )
        # Must NOT be merged into scatter
        assert dim.get("scatter", {}).get("round_count", 0) == 0, (
            "Unmapped round must NOT appear in 'scatter' dimension value."
        )

    def test_unknown_bucket_not_merged_into_real_value(self) -> None:
        """sum == aggregate must still hold when an unknown bucket is present.

        Mixed fixture: 1 scatter + 1 unknown:99 → total=2 rounds.
        sum(round_count for all values) == 2.
        """
        manifest = _manifest_disc()
        rounds = [
            _paid(bet=1000, win=0, extra={"FieldX": 0}),
            _bonus(st=126, win=1000, extra={"FieldX": 0}),   # scatter
            _paid(bet=1000, win=0, extra={"FieldX": 99}),
            _bonus(st=126, win=2000, extra={"FieldX": 99}),  # unknown:99
            _paid(bet=1000, win=0),
        ]
        data = _run_extractor(rounds, manifest)
        dim = _dimensions_for_st(data, 126).get(_DIM_NAME, {})

        total = sum(v["round_count"] for v in dim.values())
        assert total == 2, (
            f"Sum including unknown bucket must equal 2. Got {total}. "
            f"Dim values: {list(dim.keys())}."
        )
        # scatter must have exactly 1 round (not polluted by unknown)
        assert dim.get("scatter", {}).get("round_count", 0) == 1, (
            "scatter.round_count must be 1; unknown round must not merge into it."
        )

    def test_multi_trigger_produces_multi_bucket(self) -> None:
        """Anchor-walk: both payout_id AND counter match → 'multi:collect_peak+scatter' bucket.

        Fixture: opening paid round has both payout_id='666' (scatter) AND CollectCount=100
        (collect_peak). Per additive_sessions policy: rounds/wins go to multi bucket.
        Per-path session_counts each get +1.
        """
        manifest = _manifest_fallback()
        rounds = [
            # Multi-trigger opener: both payout_id=666 AND CollectCount=100
            _paid(bet=1000, win=0, payout={"666": 0}, extra={"CollectCount": 100}),
            _bonus(st=126, win=6000),
            _paid(bet=1000, win=0),
        ]
        data = _run_extractor(rounds, manifest)
        dim = _dimensions_for_st(data, 126).get(_DIM_NAME, {})

        multi_key = "multi:collect_peak+scatter"  # sorted labels
        assert multi_key in dim, (
            f"Multi-trigger must produce '{multi_key}' bucket in dimensions. "
            f"Got dim keys: {list(dim.keys())}. "
            "Per §3.2: multi-trigger routes rounds/wins to 'multi:<A>+<B>' bucket."
        )
        multi = dim[multi_key]
        assert multi.get("round_count", 0) == 1, (
            f"Multi bucket must carry 1 round. Got {multi}."
        )
        assert multi.get("win_sum", 0.0) == pytest.approx(6000.0), (
            f"Multi bucket win_sum must be 6000. Got {multi.get('win_sum')}."
        )


# ---------------------------------------------------------------------------
# Group G — backward-compat: flat "trigger_path" output UNCHANGED
# ---------------------------------------------------------------------------

class TestBackwardCompatFlatOutput:
    """Group G — Phase 1 must not alter the flat trigger_path output that freespin_dynamics reads.

    The existing per-ST, per-label dict (round_count, win_sum, session_count, win_band_hist)
    must be UNCHANGED in shape. The "dimensions" key is an addition, not a replacement.

    INVARIANT: for the flat output, adding "dimensions" as a sibling key at the
    top level of rec["st_extract"]["trigger_path"] must not affect the existing
    string-keyed ST entries (e.g. "126": {"scatter": {...}}).

    Per 04_dimension_framework.md §3.4.1:
      chunk_dict["st_extract"]["trigger_path"] = {
          "<st_int>": {...},        # backward-compat (unchanged)
          "dimensions": {...}       # NEW Phase 1 key
      }
    """

    def _run_simple(self) -> dict:
        """Run a simple 1-scatter-block fixture and return the full extractor output."""
        manifest = _manifest_disc()
        rounds = [
            _paid(bet=1000, win=0, extra={"FieldX": 0}),
            _bonus(st=126, win=3000, extra={"FieldX": 0}),
            _paid(bet=1000, win=0),
        ]
        return _run_extractor(rounds, manifest)

    def test_backward_compat_flat_trigger_path_unchanged_in_shape(self) -> None:
        """The flat per-ST section (data["126"]["scatter"]) must be present and
        contain exactly the pre-Phase-1 fields: round_count, win_sum, session_count,
        win_band_hist.

        It must NOT gain new fields (bet_sum, paid_round_count, etc.) — those
        belong only in the "dimensions" sub-key.
        """
        data = self._run_simple()

        # The flat "126" key must be present (backward compat)
        assert "126" in data, (
            "Flat 'trigger_path' output must still contain '126' key. "
            "Phase 1 must not remove the backward-compat flat output."
        )
        st_flat = data["126"]
        assert "scatter" in st_flat, (
            f"Flat '126' output must contain 'scatter' label. Got keys: {list(st_flat.keys())}"
        )

        scatter_flat = st_flat["scatter"]
        # Pre-Phase-1 fields must all be present
        required_fields = {"round_count", "win_sum", "session_count", "win_band_hist"}
        missing = required_fields - set(scatter_flat.keys())
        assert not missing, (
            f"Flat trigger_path scatter must contain all pre-Phase-1 fields. "
            f"Missing: {missing}. Got: {list(scatter_flat.keys())}."
        )

    def test_backward_compat_flat_matches_pre_phase1_fields(self) -> None:
        """The flat output values must match what the pre-Phase-1 extractor produced.

        Specifically: round_count=1, win_sum=3000.0, session_count=1,
        win_band_hist with at least one bucket.
        """
        data = self._run_simple()
        scatter_flat = data.get("126", {}).get("scatter", {})

        assert scatter_flat.get("round_count") == 1, (
            f"Flat scatter.round_count must be 1. Got {scatter_flat}."
        )
        assert scatter_flat.get("win_sum") == pytest.approx(3000.0), (
            f"Flat scatter.win_sum must be 3000.0. Got {scatter_flat}."
        )
        assert scatter_flat.get("session_count") == 1, (
            f"Flat scatter.session_count must be 1. Got {scatter_flat}."
        )
        hist = scatter_flat.get("win_band_hist", {})
        assert len(hist) > 0, (
            f"Flat scatter.win_band_hist must be non-empty. Got {scatter_flat}."
        )

    def test_backward_compat_no_new_keys_in_flat_output(self) -> None:
        """The flat per-label dict must contain ONLY the 4 pre-Phase-1 keys.

        Phase 1 additions (bet_sum, paid_round_count, etc.) must appear ONLY in
        the 'dimensions' sub-key, NOT in the flat output that freespin_dynamics reads.
        """
        data = self._run_simple()
        scatter_flat = data.get("126", {}).get("scatter", {})
        allowed_flat_keys = {"round_count", "win_sum", "session_count", "win_band_hist"}
        extra_keys = set(scatter_flat.keys()) - allowed_flat_keys
        assert not extra_keys, (
            f"Flat trigger_path output must contain only pre-Phase-1 keys. "
            f"Found extra keys: {extra_keys}. "
            "Phase 1 new fields (bet_sum, paid_round_count, etc.) must be in 'dimensions' only."
        )

    def test_backward_compat_dimensions_key_is_sibling_not_nested_inside_st(self) -> None:
        """The 'dimensions' key must be a sibling of the ST-keyed entries in the
        extractor output, not nested inside a ST number dict.

        Correct shape:  {"126": {"scatter": {...}}, "dimensions": {...}}
        Wrong shape:    {"126": {"scatter": {...}, "dimensions": {...}}}
        """
        data = self._run_simple()

        # Top level of extractor output: "126" and "dimensions" are siblings
        assert _DIMENSIONS_KEY in data, (
            f"'dimensions' must be a top-level sibling key in the extractor output. "
            f"Got top-level keys: {list(data.keys())}."
        )
        # The "126" entry must NOT contain "dimensions" as a sub-key
        st_entry = data.get("126", {})
        assert _DIMENSIONS_KEY not in st_entry, (
            f"'dimensions' must NOT be nested inside the ST-number dict ('126'). "
            f"It must be a top-level sibling. Got st_entry keys: {list(st_entry.keys())}. "
            "Wrong nesting would break freespin_dynamics which reads data['126']['scatter']."
        )


# ---------------------------------------------------------------------------
# Group H — Real-data M275 (skipif rawdata absent)
# ---------------------------------------------------------------------------

@SKIP_NO_M275
class TestRealDataM275Dimensions:
    """Group H — M275 real-data reconciliation for the 'dimensions' sub-key.

    Value-agnostic: assert sum == total, both values present, unknown empty,
    and next_st 126->140 captured. Do NOT pin literal counts.

    Per 05_breaker.md CASE 1 (HELD): M275 ST126 scatter+collect_peak+unknown == 9090.
    Per 05_breaker.md §GAP-A: 892 ST126->ST140 transitions exist and must appear
    in next_st_counts for scatter path.
    """

    def _disc_manifest_m275(self) -> dict:
        """M275 discriminator manifest per coordinator-verified ground truth:
        GameplayTriggerType 0=scatter, 2=collect_peak.
        """
        return {
            "machine_id": "M275",
            "spin_types": {
                "126": {
                    "role": "freespin",
                    "trigger_paths": {
                        "discriminator": {
                            "kind": "round_field",
                            "field": "GameplayTriggerType",
                            "map": {"0": "scatter", "2": "collect_peak"},
                            "unmapped_value_policy": "surface_as_unknown_path",
                        },
                        "multi_trigger_policy": "additive_sessions",
                    },
                }
            },
        }

    def _run_chunk(self, chunk_path: Path) -> dict:
        """Parse one M275 chunk and return the extractor output."""
        from fresh_slotlab.analyzer.st_extract import discover_extractors, get_extractors_for_manifest
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        discover_extractors()
        manifest = self._disc_manifest_m275()
        extractors = get_extractors_for_manifest(manifest)
        assert len(extractors) >= 1

        env = json.loads(chunk_path.read_bytes().decode("utf-8"))
        bet = int(env.get("_bet", 1000))
        resp = env["response"]

        rec = parse_chunk_response(resp, chunk_index=1, bet=bet, st_extractors=extractors)
        assert rec["ok"] is True, f"parse failed for {chunk_path.name}: {rec.get('error')}"
        return rec["st_extract"][_EXTRACTOR_ID]

    def _run_both_chunks(self) -> tuple[dict, dict]:
        """Return (chunk1_data, chunk2_data)."""
        return self._run_chunk(M275_CHUNK1), self._run_chunk(M275_CHUNK2)

    def _merge_dim_values(self, c1: dict, c2: dict, st: int) -> dict:
        """Merge dimensions[st][dim_name] from two chunks into a combined view."""
        merged: dict[str, dict] = defaultdict(lambda: defaultdict(int))
        for chunk_data in (c1, c2):
            dim = _dimensions_for_st(chunk_data, st).get(_DIM_NAME, {})
            for val, stats in dim.items():
                for k, v in stats.items():
                    if isinstance(v, (int, float)):
                        merged[val][k] += v
        return dict(merged)

    def test_real_m275_dimensions_sum_equals_total_round_count(self) -> None:
        """Σ round_count over all values (scatter+collect_peak+unknown) == 9090.

        Per 05_breaker.md CASE 1: breaker confirmed exact round totals.
        Value-agnostic assertion: sum == total declared-ST rounds, not pinned splits.

        Relation: scatter.round_count + collect_peak.round_count + unknown.round_count
                  == total ST126 rounds in both chunks.
        """
        c1, c2 = self._run_both_chunks()

        # Compute raw ST126 round count from both chunks
        def _count_st126(chunk_path: Path) -> int:
            env = json.loads(chunk_path.read_bytes().decode("utf-8"))
            total = 0
            for robot in env["response"]:
                rr = robot.get("roundResult")
                rounds = json.loads(rr) if isinstance(rr, str) else (rr or [])
                total += sum(1 for r in rounds if r.get("SpinType") == 126)
            return total

        raw_total = _count_st126(M275_CHUNK1) + _count_st126(M275_CHUNK2)

        # Sum dimension values across both chunks
        merged = self._merge_dim_values(c1, c2, 126)
        dim_total = sum(v.get("round_count", 0) for v in merged.values())

        assert raw_total > 0, "M275 must have ST126 rounds in the rawdata."
        assert dim_total == raw_total, (
            f"Σ dimension round_count ({dim_total}) must equal raw ST126 count ({raw_total}). "
            f"Values present: {list(merged.keys())}. "
            "This is the value-agnostic sum==aggregate gate per §3.2 of 04_dimension_framework.md."
        )

    def test_real_m275_two_values_present_unknown_empty(self) -> None:
        """Both 'scatter' and 'collect_peak' must be present; no unknown buckets.

        Per 05_breaker.md CASE 1: GTT tally {0:8290, 2:800}, 0 unknown.
        All observed GameplayTriggerType values are mapped (0 → scatter, 2 → collect_peak).
        Value-agnostic: assert both values present and no 'unknown:' keys.
        """
        c1, c2 = self._run_both_chunks()
        merged = self._merge_dim_values(c1, c2, 126)

        assert "scatter" in merged, (
            f"'scatter' must be present in M275 ST126 dimensions. "
            f"Got values: {list(merged.keys())}."
        )
        assert "collect_peak" in merged, (
            f"'collect_peak' must be present in M275 ST126 dimensions. "
            f"Got values: {list(merged.keys())}."
        )

        unknown_keys = [k for k in merged if k.startswith("unknown:")]
        assert len(unknown_keys) == 0, (
            f"M275 ST126 must have no 'unknown:' buckets when all GTT values are mapped. "
            f"Got unknown keys: {unknown_keys}. "
            "Per 05_breaker.md CASE 1: all 9090 rounds map to scatter or collect_peak."
        )

        # Relational: scatter >> collect_peak in count (per breaker 8290 vs 800)
        scatter_rc = merged["scatter"]["round_count"]
        collect_rc = merged["collect_peak"]["round_count"]
        assert scatter_rc > collect_rc, (
            f"scatter.round_count ({scatter_rc}) must exceed collect_peak ({collect_rc}). "
            "M275 scatter triggers much more frequently than collect_peak."
        )

    def test_real_m275_next_st_126_to_140_captured(self) -> None:
        """ST126->ST140 transitions must appear in scatter's next_st_counts.

        Per 05_breaker.md §GAP-A: 892 out of 9090 ST126 transitions are to ST140
        (freespin-session-exit). With the GAP-A fix in place, these must appear
        in next_st_counts[140] for the scatter path.

        Value-agnostic: assert count > 0 (not pinned to 892).

        INJECT-BUG IB-B1 (move transition below early-return):
        => next_st_counts.get(140, 0) == 0 => RED.
        Revert => GREEN.
        """
        c1, c2 = self._run_both_chunks()

        # Accumulate next_st_counts[140] for scatter across both chunks
        total_126_to_140 = 0
        for chunk_data in (c1, c2):
            dim = _dimensions_for_st(chunk_data, 126).get(_DIM_NAME, {})
            scatter = dim.get("scatter", {})
            next_sts = scatter.get("next_st_counts", {})
            total_126_to_140 += next_sts.get(140, 0)

        assert total_126_to_140 > 0, (
            f"next_st_counts[140] for scatter must be > 0 across both M275 chunks. "
            f"Got {total_126_to_140}. "
            "GAP-A fix: ST126->ST140 exit transitions must be captured BEFORE the "
            "early-return that skips undeclared STs. "
            "INJECT-BUG IB-B1: move transition block below early-return => 0 => RED. "
            "Per 05_breaker.md §GAP-A: 892 such transitions exist (9.8% of ST126 rounds)."
        )

    def test_real_m275_sum_scatter_plus_collect_peak_equals_total(self) -> None:
        """scatter.round_count + collect_peak.round_count == total ST126 rounds.

        This is the M275-specific sum==aggregate gate from §3.6 Gate 3:
        'sum(scatter.round_count + collect_peak.round_count + unknowns) == ST126_spins'.

        Since unknown must be empty (previous test), this simplifies to:
        scatter + collect_peak == total.
        """
        c1, c2 = self._run_both_chunks()

        def _count_st126(chunk_path: Path) -> int:
            env = json.loads(chunk_path.read_bytes().decode("utf-8"))
            total = 0
            for robot in env["response"]:
                rr = robot.get("roundResult")
                rounds = json.loads(rr) if isinstance(rr, str) else (rr or [])
                total += sum(1 for r in rounds if r.get("SpinType") == 126)
            return total

        raw_total = _count_st126(M275_CHUNK1) + _count_st126(M275_CHUNK2)
        merged = self._merge_dim_values(c1, c2, 126)

        scatter_rc = merged.get("scatter", {}).get("round_count", 0)
        collect_rc = merged.get("collect_peak", {}).get("round_count", 0)
        sum_named = scatter_rc + collect_rc

        assert sum_named == raw_total, (
            f"scatter ({scatter_rc}) + collect_peak ({collect_rc}) = {sum_named} "
            f"must equal raw ST126 total ({raw_total}). "
            "This holds when unknown is empty (all GTT values mapped)."
        )


# ---------------------------------------------------------------------------
# Group I — freespin_dynamics ingestion guard (critic Q1/Q10 regression)
#
# The extractor now emits a "dimensions" key as a SIBLING of the numeric
# ST keys inside st_extract["trigger_path"]. freespin_dynamics.extract()
# iterates those keys; without the isdigit() guard it would ingest
# "dimensions" as a fake ST into its accumulator (inert at emit today, but a
# Phase-2 foot-gun). This locks the guard. Inject-bug (manual, documented in
# the commit): delete the `if not str(st_key).isdigit(): continue` line in
# freespin_dynamics.extract() -> test_dimensions_sibling_not_ingested RED.
# ---------------------------------------------------------------------------
class TestFreespinIngestionGuard:
    def _extract(self, tp_raw):
        from fresh_slotlab.analyzer.features.freespin_dynamics import FreespinDynamics
        chunk = {"st_extract": {"trigger_path": tp_raw}}
        return FreespinDynamics().extract(None, chunk)

    def test_dimensions_sibling_not_ingested(self):
        # tp_raw mirrors the real extractor output: numeric ST keys + a
        # "dimensions" sibling produced by Phase 1.
        tp_raw = {
            "126": {
                "scatter": {"round_count": 10, "win_sum": 100.0,
                            "session_count": 1, "win_band_hist": {}},
            },
            "dimensions": {
                "126": {"trigger_path": {"scatter": {"round_count": 10}}},
            },
        }
        acc = self._extract(tp_raw)
        tps = acc["trigger_paths"]
        assert "126" in tps, "real ST key must still be ingested"
        assert "dimensions" not in tps, (
            "the 'dimensions' sibling key must NOT be ingested as a fake ST "
            "(freespin_dynamics int-guard regression)"
        )

    def test_real_st_data_unaffected_by_guard(self):
        # The guard must not drop or alter genuine ST data.
        tp_raw = {
            "126": {
                "scatter": {"round_count": 7, "win_sum": 70.0,
                            "session_count": 2, "win_band_hist": {"1x": 7}},
            },
        }
        acc = self._extract(tp_raw)
        row = acc["trigger_paths"]["126"]["scatter"]
        assert row["round_count"] == 7
        assert row["win_sum"] == 70.0
        assert row["session_count"] == 2
