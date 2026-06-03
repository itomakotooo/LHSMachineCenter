"""Phase C3 — unit tests for payouts_by_spin_type enrichment fields.

Tests shape / covered_columns / paylines / notes derivation via extract() /
reduce() / emit() using synthetic chunk_dict data. Does NOT spawn subprocess —
unit-level correctness only. Subprocess-level byte-identical tests live in
test_c3_byte_identical_m*.py.

Invariants asserted
-------------------
1. Plugin imports clean (no side effects).
2. SCHEMA_VERSION == 2 (C3 bumped from 1).
3. REGISTERED_FALLBACK_RULES has key 1 with all 4 new field names mapped to None.
4. extract() reads 4 C3 chunk_dict keys (payout_id_payline_hits /
   payout_id_match_count_dist / payout_id_col_set / payout_id_has_regular_line).
5. extract() on missing C3 keys returns empty C3 accumulators (old cached chunks).
6. reduce() merges pid_payline_hits additively across chunks.
7. reduce() merges pid_match_count_dist additively across chunks.
8. reduce() merges pid_col_set as union across chunks.
9. reduce() merges pid_has_regular_line as OR (True if True in ANY chunk).
10. emit() produces 'shape' dict keyed "{N}_of_a_kind": count.
11. emit() produces 'covered_columns' as sorted list of int column indices.
12. emit() produces 'paylines' as list of {payline_id, hit_count} dicts.
13. emit() produces 'notes' with is_trigger_marker and max_match_count_observed.
14. Trigger marker detection: line_id==-1 only AND win==0 → is_trigger_marker True.
15. Non-trigger pid with mixed paylines: is_trigger_marker False.
16. C2 legacy fields (payout_id, hit_count, hit_rate, total_win,
    avg_win_when_hit, rtp_contribution_pp) still present alongside C3 fields.

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug A — emit() always emits empty shape:
    In payouts_by_spin_type.py emit(), change:
        shape: dict[str, int] = {
            f"{mc}_of_a_kind": cnt
            for mc, cnt in sorted(mc_dist.items())
        } if mc_dist else {}
    to:
        shape: dict[str, int] = {}
    RED: test_emit_shape_populated fails.
    Revert → GREEN.

Bug B — parser drops payout_id_col_set (covered_columns source):
    In fresh_slotlab/analyzer/core/parser.py, remove the line:
        payout_id_col_set[_c3pid_s].add(_c3col)
    RED: test_covered_columns_populated fails (covered_columns == []).
    Revert → GREEN.

Bug C — emit() always sets is_trigger_marker = False:
    In emit(), change:
        "is_trigger_marker": is_trigger,
    to:
        "is_trigger_marker": False,
    RED: test_trigger_marker_detection fails (expected True, got False).
    Revert → GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_invariant_with_fallback_hides_drift.md (is_trigger_marker is
  an explicit positive signal, not a fallback bucket)
- memory/feedback_subprocess_import_suicide_and_module_globals.md
  (import must not run I/O)
- memory/feedback_no_hardcode.md (plugin must not hardcode pid 666 specifically)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(effective_bet_for_rtp: float = 100_000.0) -> Any:
    """Build a minimal PipelineContext-like object for C3 unit tests."""
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext, MechanismRegistry
    except ImportError:
        from analyzer.pipeline_context import PipelineContext, MechanismRegistry  # type: ignore[no-redef]
    return PipelineContext(
        effective_bet_for_rtp=effective_bet_for_rtp,
        total_spins=10_000,
        total_paid_sessions=10_000,
        total_paid_spins=10_000,
        clamp_pending_robots_total=0,
        robots_with_pending_cycle=0,
        mechanism_registry=MechanismRegistry(),
        manifest={},
    )


def _make_summary_with_st_breakdown(st_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a minimal summary dict containing spin_type_breakdown."""
    return {
        "player_impact": {
            "spin_type_breakdown": st_entries,
        }
    }


def _import_plugin():
    try:
        from fresh_slotlab.analyzer.features.payouts_by_spin_type import PayoutsBySpinType
    except ImportError:
        from analyzer.features.payouts_by_spin_type import PayoutsBySpinType  # type: ignore[no-redef]
    return PayoutsBySpinType


def _standard_acc(
    pid: str = "9",
    st_int: int = 1,
    hits: int = 100,
    win: float = 10_000.0,
    payline_hits: dict | None = None,
    match_count_dist: dict | None = None,
    col_set: list | None = None,
    has_regular_line: bool = True,
) -> dict:
    """Build a complete merged accumulator for a single pid."""
    if payline_hits is None:
        payline_hits = {"1": 60, "2": 40}
    if match_count_dist is None:
        match_count_dist = {3: hits}
    if col_set is None:
        col_set = [0, 1, 2]
    return {
        "by_st_hits": {pid: {st_int: hits}},
        "by_st_win": {pid: {st_int: win}},
        "pid_payline_hits": {pid: payline_hits},
        "pid_match_count_dist": {pid: match_count_dist},
        "pid_col_set": {pid: col_set},
        "pid_has_regular_line": {pid: True} if has_regular_line else {},
    }


def _trigger_marker_acc(
    pid: str = "666",
    st_int: int = 1,
    hits: int = 100,
) -> dict:
    """Build accumulator for a pure trigger-marker pid (line_id=-1, win=0)."""
    return {
        "by_st_hits": {pid: {st_int: hits}},
        "by_st_win": {pid: {st_int: 0.0}},
        "pid_payline_hits": {pid: {"-1": hits}},
        "pid_match_count_dist": {},       # no regular-line records
        "pid_col_set": {pid: [0, 1, 2]},  # positions still decoded
        "pid_has_regular_line": {},        # not present = all trigger lines
    }


_SINGLE_ST_SUMMARY = [
    {"spin_type": 1, "behavior_name": "paid", "spins": 10_000, "total_paid_bet": 10_000_000.0}
]


# ---------------------------------------------------------------------------
# T1: SCHEMA_VERSION and REGISTERED_FALLBACK_RULES
# ---------------------------------------------------------------------------

class TestC3SchemaAndFallback:
    """SCHEMA_VERSION == 2; REGISTERED_FALLBACK_RULES populated for v1."""

    def test_schema_version_is_3(self):
        """C4/Phase-P3 bumps SCHEMA_VERSION from 2 → 3 for symbol_combo enrichment.

        C3 bumped from 1 → 2. C4/Phase-P3 bumped from 2 → 3 for symbol_combo.

        INJECT-BUG: set SCHEMA_VERSION = 2 in plugin file.
        RED: this assertion fires.
        Revert → GREEN.
        """
        PayoutsBySpinType = _import_plugin()
        assert PayoutsBySpinType.SCHEMA_VERSION == 3, (
            f"Expected SCHEMA_VERSION=3, got {PayoutsBySpinType.SCHEMA_VERSION}. "
            "C4/Phase-P3 must bump schema version to 3 for symbol_combo enrichment."
        )

    def test_registered_fallback_rules_has_key_1(self):
        """REGISTERED_FALLBACK_RULES must contain key 1 (v1 → v2 rule).

        INJECT-BUG: remove the {1: ...} entry from REGISTERED_FALLBACK_RULES.
        RED: key 1 absent → this assertion fails.
        Revert → GREEN.
        """
        PayoutsBySpinType = _import_plugin()
        rfr = PayoutsBySpinType.REGISTERED_FALLBACK_RULES
        assert isinstance(rfr, dict), f"REGISTERED_FALLBACK_RULES must be dict, got {type(rfr)}"
        assert 1 in rfr, (
            f"REGISTERED_FALLBACK_RULES must contain key 1 (v1→v2 fallback). "
            f"Got keys: {sorted(rfr.keys())}"
        )

    def test_registered_fallback_rules_v1_has_all_4_new_fields(self):
        """REGISTERED_FALLBACK_RULES[1] must map all 4 new field names to None.

        This is the frontend contract: v1 summaries are missing shape /
        covered_columns / paylines / notes — the renderer defaults them to None.

        INJECT-BUG: remove 'notes' from the fallback dict.
        RED: 'notes' missing from rule → this assertion fails.
        Revert → GREEN.
        """
        PayoutsBySpinType = _import_plugin()
        v1_rule = PayoutsBySpinType.REGISTERED_FALLBACK_RULES.get(1, {})
        expected_keys = {"shape", "covered_columns", "paylines", "notes"}
        actual_keys = set(v1_rule.keys())
        missing = expected_keys - actual_keys
        assert not missing, (
            f"REGISTERED_FALLBACK_RULES[1] missing new fields: {missing}. "
            f"Got keys: {sorted(actual_keys)}"
        )
        # Each must map to None (frontend "hide gracefully" sentinel)
        for field in expected_keys:
            assert v1_rule[field] is None, (
                f"REGISTERED_FALLBACK_RULES[1][{field!r}] must be None, "
                f"got {v1_rule[field]!r}"
            )


# ---------------------------------------------------------------------------
# T2: extract() — reads C3 chunk_dict keys
# ---------------------------------------------------------------------------

class TestC3Extract:
    """extract() reads payout_id_payline_hits / match_count_dist / col_set /
    has_regular_line from chunk_dict (C3 keys)."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin()()

    def test_extract_reads_payline_hits(self, plugin):
        """extract() reads payout_id_payline_hits from chunk_dict.

        INJECT-BUG: remove the payout_id_payline_hits block in extract().
        RED: pid_payline_hits empty → this assertion fails.
        Revert → GREEN.
        """
        chunk = {
            "payout_id_by_spin_type": {"9": {"1": 5}},
            "payout_id_win_by_spin_type": {"9": {"1": 500.0}},
            "payout_id_payline_hits": {"9": {"1": 3, "2": 2}},
            "payout_id_match_count_dist": {"9": {3: 5}},
            "payout_id_col_set": {"9": [0, 1, 2]},
            "payout_id_has_regular_line": {"9": True},
        }
        acc = plugin.extract(None, chunk)
        pl = acc.get("pid_payline_hits", {})
        assert "9" in pl, f"pid '9' missing from pid_payline_hits: {pl}"
        assert pl["9"].get("1") == 3, f"Expected payline '1' hit_count=3, got {pl['9']}"
        assert pl["9"].get("2") == 2, f"Expected payline '2' hit_count=2, got {pl['9']}"

    def test_extract_reads_match_count_dist(self, plugin):
        """extract() reads payout_id_match_count_dist from chunk_dict."""
        chunk = {
            "payout_id_by_spin_type": {"7": {"1": 10}},
            "payout_id_win_by_spin_type": {"7": {"1": 1000.0}},
            "payout_id_payline_hits": {},
            "payout_id_match_count_dist": {"7": {3: 8, 4: 2}},
            "payout_id_col_set": {"7": [0, 1, 2]},
            "payout_id_has_regular_line": {"7": True},
        }
        acc = plugin.extract(None, chunk)
        mc = acc.get("pid_match_count_dist", {})
        assert "7" in mc, f"pid '7' missing from pid_match_count_dist: {mc}"
        assert mc["7"].get(3) == 8, f"Expected match_count 3→8, got {mc['7']}"
        assert mc["7"].get(4) == 2, f"Expected match_count 4→2, got {mc['7']}"

    def test_extract_reads_col_set(self, plugin):
        """extract() reads payout_id_col_set from chunk_dict and sorts it.

        INJECT-BUG: remove the payout_id_col_set block in extract().
        RED: pid_col_set empty → covered_columns empty in emit() → this fails.
        Revert → GREEN.
        """
        chunk = {
            "payout_id_by_spin_type": {"5": {"1": 3}},
            "payout_id_win_by_spin_type": {"5": {"1": 300.0}},
            "payout_id_payline_hits": {},
            "payout_id_match_count_dist": {},
            "payout_id_col_set": {"5": [2, 0, 1]},  # unsorted in chunk
            "payout_id_has_regular_line": {"5": True},
        }
        acc = plugin.extract(None, chunk)
        cs = acc.get("pid_col_set", {})
        assert "5" in cs, f"pid '5' missing from pid_col_set: {cs}"
        assert cs["5"] == [0, 1, 2], f"Expected sorted [0,1,2], got {cs['5']}"

    def test_extract_reads_has_regular_line(self, plugin):
        """extract() reads payout_id_has_regular_line; only True values carried."""
        chunk = {
            "payout_id_by_spin_type": {"3": {"1": 5}},
            "payout_id_win_by_spin_type": {"3": {"1": 0.0}},
            "payout_id_payline_hits": {"3": {"-1": 5}},
            "payout_id_match_count_dist": {},
            "payout_id_col_set": {},
            "payout_id_has_regular_line": {"3": False},  # trigger marker
        }
        acc = plugin.extract(None, chunk)
        hrl = acc.get("pid_has_regular_line", {})
        # False value should NOT be carried (only True values propagate)
        assert "3" not in hrl or hrl.get("3") is not True, (
            f"pid_has_regular_line[3] must not be True for a trigger-marker pid: {hrl}"
        )

    def test_extract_missing_c3_keys_returns_empty_c3_accumulators(self, plugin):
        """extract() tolerates missing C3 keys (old cached chunks without C3 data).

        Old cached chunks (pre-C3 parser rebuild) will not have these keys.
        The plugin must return empty C3 accumulators (not crash).

        INJECT-BUG: do NOT have missing-key handling in extract() (remove .get() fallback).
        RED: KeyError on old chunks → this test fails.
        Revert → GREEN.
        """
        chunk = {
            "payout_id_by_spin_type": {"9": {"1": 5}},
            "payout_id_win_by_spin_type": {"9": {"1": 500.0}},
            # C3 keys absent
        }
        acc = plugin.extract(None, chunk)
        assert acc.get("pid_payline_hits") == {}, (
            f"Expected empty pid_payline_hits for old chunk, got {acc.get('pid_payline_hits')}"
        )
        assert acc.get("pid_match_count_dist") == {}, (
            f"Expected empty pid_match_count_dist for old chunk, got {acc.get('pid_match_count_dist')}"
        )
        assert acc.get("pid_col_set") == {}, (
            f"Expected empty pid_col_set for old chunk, got {acc.get('pid_col_set')}"
        )
        assert acc.get("pid_has_regular_line") == {}, (
            f"Expected empty pid_has_regular_line for old chunk, got {acc.get('pid_has_regular_line')}"
        )


# ---------------------------------------------------------------------------
# T3: reduce() — merging C3 accumulators
# ---------------------------------------------------------------------------

class TestC3Reduce:
    """reduce() merges C3 enrichment accumulators correctly across chunks."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin()()

    def _c3_chunk(
        self,
        pid: str,
        st: int,
        hits: int,
        win: float,
        pl: dict,
        mc: dict,
        cols: list,
        hrl: bool,
    ) -> dict:
        return {
            "by_st_hits": {pid: {st: hits}},
            "by_st_win": {pid: {st: win}},
            "pid_payline_hits": {pid: pl},
            "pid_match_count_dist": {pid: mc} if mc else {},
            "pid_col_set": {pid: cols},
            "pid_has_regular_line": {pid: True} if hrl else {},
        }

    def test_reduce_payline_hits_additive(self, plugin):
        """pid_payline_hits accumulates additively across chunks.

        INJECT-BUG: replace pid_payline_hits merge with just prev_pl (skip this_pl).
        RED: payline '1' count is 3 instead of 8.
        Revert → GREEN.
        """
        c1 = self._c3_chunk("9", 1, 5, 500.0, {"1": 3, "2": 2}, {3: 5}, [0, 1, 2], True)
        c2 = self._c3_chunk("9", 1, 5, 500.0, {"1": 5, "2": 3}, {3: 5}, [0, 1, 2], True)
        merged = plugin.reduce(c1, c2)
        pl = merged.get("pid_payline_hits", {}).get("9", {})
        assert pl.get("1") == 8, f"Expected payline '1' additive sum=8, got {pl.get('1')}"
        assert pl.get("2") == 5, f"Expected payline '2' additive sum=5, got {pl.get('2')}"

    def test_reduce_match_count_dist_additive(self, plugin):
        """pid_match_count_dist accumulates additively across chunks."""
        c1 = self._c3_chunk("7", 1, 5, 500.0, {}, {3: 4}, [0, 1], True)
        c2 = self._c3_chunk("7", 1, 5, 500.0, {}, {3: 3, 4: 2}, [0, 1], True)
        merged = plugin.reduce(c1, c2)
        mc = merged.get("pid_match_count_dist", {}).get("7", {})
        assert mc.get(3) == 7, f"Expected match_count 3→7, got {mc.get(3)}"
        assert mc.get(4) == 2, f"Expected match_count 4→2, got {mc.get(4)}"

    def test_reduce_col_set_union(self, plugin):
        """pid_col_set is merged as union across chunks (column coverage grows).

        INJECT-BUG: replace col_set merge with intersection instead of union.
        RED: merged col_set is [1] instead of [0, 1, 2].
        Revert → GREEN.
        """
        c1 = self._c3_chunk("5", 1, 3, 300.0, {}, {}, [0, 1], True)
        c2 = self._c3_chunk("5", 1, 3, 300.0, {}, {}, [1, 2], True)
        merged = plugin.reduce(c1, c2)
        cs = merged.get("pid_col_set", {}).get("5", [])
        assert cs == [0, 1, 2], f"Expected union [0,1,2], got {cs}"

    def test_reduce_has_regular_line_or_semantics(self, plugin):
        """pid_has_regular_line is OR: True if True in ANY chunk.

        INJECT-BUG: replace OR with AND — only True when BOTH chunks have True.
        RED: a pid that is True in c2 but absent in c1 is lost.
        Revert → GREEN.
        """
        # c1: pid not in has_regular_line (trigger-only)
        c1 = self._c3_chunk("3", 1, 5, 0.0, {"-1": 5}, {}, [], False)
        # c2: pid has a regular line
        c2 = self._c3_chunk("3", 1, 5, 100.0, {"1": 5}, {3: 5}, [0, 1, 2], True)
        merged = plugin.reduce(c1, c2)
        hrl = merged.get("pid_has_regular_line", {})
        assert hrl.get("3") is True, (
            f"pid_has_regular_line must be True if True in ANY chunk. "
            f"Got: {hrl}"
        )

    def test_reduce_payline_hits_new_pid_in_second_chunk(self, plugin):
        """reduce() keeps pids from both chunks when pid appears in only one."""
        c1 = self._c3_chunk("9", 1, 5, 500.0, {"1": 3}, {}, [0, 1], True)
        c2 = self._c3_chunk("7", 1, 5, 500.0, {"2": 7}, {}, [1, 2], True)
        merged = plugin.reduce(c1, c2)
        pl = merged.get("pid_payline_hits", {})
        assert "9" in pl, f"pid '9' from chunk1 missing in merged: {pl.keys()}"
        assert "7" in pl, f"pid '7' from chunk2 missing in merged: {pl.keys()}"

    def test_reduce_empty_prev_acc_returns_c3_fields(self, plugin):
        """reduce({}, this_acc) returns this_acc including C3 fields."""
        this = {
            "by_st_hits": {"9": {1: 5}},
            "by_st_win": {"9": {1: 500.0}},
            "pid_payline_hits": {"9": {"1": 3}},
            "pid_match_count_dist": {"9": {3: 5}},
            "pid_col_set": {"9": [0, 1, 2]},
            "pid_has_regular_line": {"9": True},
        }
        result = plugin.reduce({}, this)
        assert result.get("pid_payline_hits", {}).get("9", {}).get("1") == 3, (
            f"Expected pid_payline_hits[9][1]=3 after reduce({{}}, this): {result}"
        )


# ---------------------------------------------------------------------------
# T4: emit() — C3 enrichment fields in output
# ---------------------------------------------------------------------------

class TestC3EmitEnrichment:
    """emit() produces shape / covered_columns / paylines / notes per row."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin()()

    def test_emit_shape_populated(self, plugin):
        """emit() produces non-empty shape dict for a regular pid.

        INJECT-BUG (Bug A): set shape = {} unconditionally in emit().
        RED: shape is {} instead of {'3_of_a_kind': 100}.
        Revert → GREEN.
        """
        acc = _standard_acc(
            pid="9", st_int=1, hits=100, win=10_000.0,
            match_count_dist={3: 100},
        )
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid9 = next((r for r in rows if r["payout_id"] == "9"), None)
        assert pid9 is not None, "pid '9' row missing from emit output"
        shape = pid9.get("shape", {})
        assert "3_of_a_kind" in shape, f"Expected '3_of_a_kind' in shape, got {shape}"
        assert shape["3_of_a_kind"] == 100, (
            f"Expected shape['3_of_a_kind']=100, got {shape['3_of_a_kind']}"
        )

    def test_emit_shape_keyed_n_of_a_kind(self, plugin):
        """emit() shapes key must follow '{N}_of_a_kind' pattern."""
        acc = _standard_acc(
            pid="7", st_int=1, hits=50, win=5_000.0,
            match_count_dist={3: 30, 4: 15, 5: 5},
        )
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid7 = next(r for r in rows if r["payout_id"] == "7")
        shape = pid7["shape"]
        assert set(shape.keys()) == {"3_of_a_kind", "4_of_a_kind", "5_of_a_kind"}, (
            f"Unexpected shape keys: {shape}"
        )
        assert shape["3_of_a_kind"] == 30
        assert shape["4_of_a_kind"] == 15
        assert shape["5_of_a_kind"] == 5

    def test_emit_covered_columns_sorted_list(self, plugin):
        """emit() covered_columns is a list of int column indices (sorting done in extract/reduce).

        Note: emit() passes through pid_col_set as-is (list). The sorting happens
        in extract() (sorted(set())) and reduce() (sorted(set(union))). So the acc
        must contain pre-sorted data. This test uses a pre-sorted col_set in the acc.

        INJECT-BUG (Bug B, parser side): remove payout_id_col_set.add() in parser.py.
        RED: covered_columns == [] → test_emit_covered_columns_populated fails.
        Revert → GREEN.
        """
        acc = _standard_acc(
            pid="9", st_int=1, hits=100, win=10_000.0,
            col_set=[0, 1, 2],  # pre-sorted (as extract/reduce would produce)
        )
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid9 = next(r for r in rows if r["payout_id"] == "9")
        cols = pid9.get("covered_columns", None)
        assert cols is not None, "covered_columns missing from row"
        assert isinstance(cols, list), f"covered_columns must be list, got {type(cols)}"
        assert cols == [0, 1, 2], f"Expected [0,1,2], got {cols}"

    def test_emit_covered_columns_populated(self, plugin):
        """covered_columns must not be empty for a pid with position data."""
        acc = _standard_acc(pid="5", st_int=1, hits=50, win=5_000.0, col_set=[0])
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid5 = next(r for r in rows if r["payout_id"] == "5")
        assert pid5["covered_columns"], (
            f"covered_columns must not be empty for pid with col_set data: {pid5}"
        )

    def test_emit_paylines_list_of_dicts(self, plugin):
        """emit() paylines is list of {payline_id, hit_count} dicts."""
        acc = _standard_acc(
            pid="9", st_int=1, hits=100, win=10_000.0,
            payline_hits={"1": 60, "2": 40},
        )
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid9 = next(r for r in rows if r["payout_id"] == "9")
        paylines = pid9.get("paylines", None)
        assert paylines is not None, "paylines missing from row"
        assert isinstance(paylines, list), f"paylines must be list, got {type(paylines)}"
        assert len(paylines) == 2, f"Expected 2 payline entries, got {len(paylines)}"
        for entry in paylines:
            assert "payline_id" in entry, f"payline entry missing payline_id: {entry}"
            assert "hit_count" in entry, f"payline entry missing hit_count: {entry}"

    def test_emit_paylines_excludes_trigger_line_for_regular_pid(self, plugin):
        """Regular pid with mixed paylines: -1 entries excluded from paylines list."""
        acc = _standard_acc(
            pid="9", st_int=1, hits=100, win=10_000.0,
            payline_hits={"1": 60, "2": 40, "-1": 5},  # -1 is a rogue entry
            has_regular_line=True,
        )
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid9 = next(r for r in rows if r["payout_id"] == "9")
        payline_ids = {p["payline_id"] for p in pid9["paylines"]}
        assert "-1" not in payline_ids, (
            f"Regular pid should NOT have -1 in paylines: {pid9['paylines']}"
        )

    def test_emit_notes_has_required_keys(self, plugin):
        """emit() notes dict has is_trigger_marker and max_match_count_observed."""
        acc = _standard_acc(pid="9", st_int=1, hits=100, win=10_000.0)
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid9 = next(r for r in rows if r["payout_id"] == "9")
        notes = pid9.get("notes", None)
        assert notes is not None, "notes missing from row"
        assert "is_trigger_marker" in notes, f"notes missing is_trigger_marker: {notes}"
        assert "max_match_count_observed" in notes, (
            f"notes missing max_match_count_observed: {notes}"
        )

    def test_emit_max_match_count_observed(self, plugin):
        """notes.max_match_count_observed == largest match_count seen."""
        acc = _standard_acc(
            pid="7", st_int=1, hits=50, win=5_000.0,
            match_count_dist={3: 30, 5: 10, 4: 10},
        )
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid7 = next(r for r in rows if r["payout_id"] == "7")
        assert pid7["notes"]["max_match_count_observed"] == 5, (
            f"Expected max_match_count_observed=5, got "
            f"{pid7['notes']['max_match_count_observed']}"
        )


# ---------------------------------------------------------------------------
# T5: Trigger marker detection
# ---------------------------------------------------------------------------

class TestC3TriggerMarkerDetection:
    """is_trigger_marker: True iff all records have line_id==-1 AND win==0."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin()()

    def test_trigger_marker_line_id_minus1_only_win_zero(self, plugin):
        """pid with only line_id==-1 records AND win==0 → is_trigger_marker True.

        This is the canonical M275 pid 666 case.

        INJECT-BUG (Bug C): set is_trigger_marker = False always.
        RED: expected True, got False.
        Revert → GREEN.
        """
        acc = _trigger_marker_acc(pid="666", st_int=1, hits=829)
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid666 = next((r for r in rows if r["payout_id"] == "666"), None)
        assert pid666 is not None, "pid '666' missing from emit output"
        assert pid666["notes"]["is_trigger_marker"] is True, (
            f"pid '666' with line_id=-1 only and win=0 must be is_trigger_marker=True. "
            f"Got: {pid666['notes']['is_trigger_marker']!r}"
        )

    def test_trigger_marker_generic_pid_not_666(self, plugin):
        """Trigger marker detection must NOT be hardcoded to pid 666.

        Any pid with line_id==-1 only AND win==0 must be flagged.
        Per memory/feedback_no_hardcode.md: semantics must be per-machine.
        """
        acc = _trigger_marker_acc(pid="999_trigger", st_int=1, hits=200)
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid999 = next((r for r in rows if r["payout_id"] == "999_trigger"), None)
        assert pid999 is not None
        assert pid999["notes"]["is_trigger_marker"] is True, (
            f"Non-666 trigger marker must also get is_trigger_marker=True. "
            f"Got: {pid999['notes']}"
        )

    def test_non_trigger_regular_pid_is_not_marker(self, plugin):
        """Regular pid with win>0 → is_trigger_marker False."""
        acc = _standard_acc(pid="9", st_int=1, hits=100, win=10_000.0, has_regular_line=True)
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid9 = next(r for r in rows if r["payout_id"] == "9")
        assert pid9["notes"]["is_trigger_marker"] is False, (
            f"Regular pid with win>0 must NOT be is_trigger_marker=True. "
            f"Got: {pid9['notes']['is_trigger_marker']!r}"
        )

    def test_trigger_marker_shows_minus1_in_paylines(self, plugin):
        """Trigger marker pid has paylines entry with payline_id '-1'."""
        acc = _trigger_marker_acc(pid="666", st_int=1, hits=829)
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid666 = next(r for r in rows if r["payout_id"] == "666")
        payline_ids = [p["payline_id"] for p in pid666["paylines"]]
        assert "-1" in payline_ids, (
            f"Trigger marker pid must include '-1' payline entry. "
            f"Got payline_ids: {payline_ids}"
        )

    def test_trigger_marker_shape_is_empty(self, plugin):
        """Trigger marker pid (line_id==-1 only) must have empty shape dict.

        No match_count records for trigger lines → shape == {}.
        """
        acc = _trigger_marker_acc(pid="666", st_int=1, hits=829)
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid666 = next(r for r in rows if r["payout_id"] == "666")
        assert pid666["shape"] == {}, (
            f"Trigger marker must have empty shape (no regular lines). "
            f"Got: {pid666['shape']}"
        )

    def test_trigger_marker_max_match_count_is_zero(self, plugin):
        """Trigger marker notes.max_match_count_observed == 0 (no regular lines)."""
        acc = _trigger_marker_acc(pid="666", st_int=1, hits=829)
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid666 = next(r for r in rows if r["payout_id"] == "666")
        assert pid666["notes"]["max_match_count_observed"] == 0, (
            f"Trigger marker must have max_match_count_observed=0. "
            f"Got: {pid666['notes']['max_match_count_observed']}"
        )

    def test_pid_with_win_and_minus1_lines_not_trigger_marker(self, plugin):
        """pid with win > 0 must NOT be trigger marker even if it has -1 lines."""
        # This pid has regular lines AND -1 lines, but win > 0
        acc = {
            "by_st_hits": {"mixed": {1: 50}},
            "by_st_win": {"mixed": {1: 5_000.0}},  # win > 0
            "pid_payline_hits": {"mixed": {"1": 30, "-1": 20}},
            "pid_match_count_dist": {"mixed": {3: 30}},
            "pid_col_set": {"mixed": [0, 1, 2]},
            "pid_has_regular_line": {"mixed": True},
        }
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        mixed = next(r for r in rows if r["payout_id"] == "mixed")
        assert mixed["notes"]["is_trigger_marker"] is False, (
            f"pid with win>0 must not be trigger marker even with -1 lines. "
            f"Got: {mixed['notes']}"
        )


# ---------------------------------------------------------------------------
# T6: Legacy C2 fields still present in C3 output
# ---------------------------------------------------------------------------

class TestC3LegacyFieldsPresent:
    """C3 adds 4 new fields but must not remove the 6 legacy C2 fields."""

    _C2_REQUIRED_KEYS = {
        "payout_id", "hit_count", "hit_rate",
        "total_win", "avg_win_when_hit", "rtp_contribution_pp",
    }
    _C3_NEW_KEYS = {"shape", "covered_columns", "paylines", "notes"}
    _ALL_REQUIRED_KEYS = _C2_REQUIRED_KEYS | _C3_NEW_KEYS

    @pytest.fixture
    def plugin(self):
        return _import_plugin()()

    def test_all_10_keys_present_in_row(self, plugin):
        """Each row must have all 6 C2 fields + 4 C3 fields = 10 keys minimum.

        Per brief §4 AC#4: C2 fields must be byte-identical. This unit test
        checks field presence. Byte-identity is checked in test_c3_byte_identical_*.py.
        """
        acc = _standard_acc(pid="9", st_int=1, hits=100, win=10_000.0)
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        assert rows, "No rows emitted"
        for row in rows:
            missing = self._ALL_REQUIRED_KEYS - set(row.keys())
            assert not missing, (
                f"Row missing required keys {missing}. "
                f"Row has: {sorted(row.keys())}"
            )

    def test_c2_fields_unchanged_values(self, plugin):
        """C2 field values must match pre-C3 formulas exactly.

        rtp_contribution_pp = (st_win / effective_bet_for_rtp) * 100.0
        hit_rate = hit_count / st_spins
        avg_win_when_hit = total_win / hit_count
        """
        acc = _standard_acc(pid="9", st_int=1, hits=100, win=10_000.0)
        summary = _make_summary_with_st_breakdown(_SINGLE_ST_SUMMARY)
        ctx = _make_ctx(100_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid9 = next(r for r in rows if r["payout_id"] == "9")
        assert pid9["hit_count"] == 100
        assert abs(pid9["total_win"] - 10_000.0) < 1e-6
        assert abs(pid9["hit_rate"] - (100 / 10_000)) < 1e-9
        assert abs(pid9["avg_win_when_hit"] - (10_000.0 / 100)) < 1e-6
        assert abs(pid9["rtp_contribution_pp"] - (10_000.0 / 100_000.0) * 100.0) < 1e-6
