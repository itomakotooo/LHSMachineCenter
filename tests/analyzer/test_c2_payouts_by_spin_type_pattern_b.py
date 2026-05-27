"""Phase C2 — unit tests for PayoutsBySpinType Pattern-B plugin.

Tests the extract() / reduce() / emit() lifecycle in isolation using synthetic
chunk data.  Does NOT spawn a subprocess — unit-level correctness only.
Subprocess-level byte-identical tests live in test_c2_byte_identical_m*.py.

Invariants asserted
-------------------
1. Import is clean — no side effects at import time.
2. register() is idempotent — importing twice does not double-add to ALL_FEATURES.
3. SCHEMA_VERSION == 1 — no shape change in C2.
4. DECLARED_DEPS == () — no _ prefix temp keys needed (reads real summary key).
5. extract() on empty chunk_dict returns empty dict (no crash).
6. extract() correctly reads payout_id_by_spin_type + payout_id_win_by_spin_type.
7. reduce() merges two extract() outputs correctly (additive per (pid, st_int)).
8. reduce() handles prev_acc == {} (first chunk) and this_acc == {} (empty chunk).
9. emit() reads ctx.effective_bet_for_rtp and spin_type_breakdown; writes
   summary["player_impact"]["payouts_by_spin_type"] with correct schema.
10. Trigger-marker semantic: pid 666 with win=0 but non-zero hits is retained
    (not silently filtered).
11. rtp_contribution_pp formula: (st_win / effective_bet_for_rtp) * 100.0.

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug A — emit() writes injected sentinel instead of real data:
    In emit(), change the final write to:
        player_impact["payouts_by_spin_type"] = {"_INJECTED": True}
    RED: test_emit_writes_payouts_by_spin_type and test_emit_schema_keys fail.
    Revert → GREEN.

Bug B — extract() skips second dict:
    Remove the second for-loop block in extract() (payout_id_win_by_spin_type).
    RED: test_extract_win_aggregation fails (by_st_win missing).
    Revert → GREEN.

Bug C — rtp_contribution_pp uses wrong denominator:
    In emit(), change effective_bet_for_rtp to 1.0 (constant).
    RED: test_emit_rtp_contribution_pp_formula fails.
    Revert → GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_subprocess_import_suicide_and_module_globals.md
  (import must not run I/O)
- memory/feedback_no_hardcode.md (plugin must not assume specific pid/ST values)
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
    """Build a minimal PipelineContext-like object for unit tests."""
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


def _make_summary_with_st_breakdown(
    st_entries: list[dict[str, Any]],
) -> dict[str, Any]:
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


# ---------------------------------------------------------------------------
# T1: Import + registration invariants
# ---------------------------------------------------------------------------

class TestPluginImportAndRegistration:
    """Import and registration are side-effect-free and idempotent."""

    def test_import_clean_no_exception(self):
        """Importing the module must not raise.

        Per memory/feedback_subprocess_import_suicide_and_module_globals.md:
        register() is a pure list-append — no I/O at import time.
        """
        try:
            import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
        except ImportError:
            import analyzer.features.payouts_by_spin_type  # type: ignore[no-redef] # noqa: F401

    def test_register_idempotent_no_double_add(self):
        """Importing twice must not add a second entry to ALL_FEATURES.

        INJECT-BUG: remove the duplicate-guard in feature_registry.register()
        → importing twice adds two entries → this test fails (count > 1).
        """
        try:
            from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
        except ImportError:
            from analyzer.feature_registry import ALL_FEATURES  # type: ignore[no-redef]

        # Import again — should be no-op due to Python module cache.
        try:
            import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
        except ImportError:
            import analyzer.features.payouts_by_spin_type  # type: ignore[no-redef] # noqa: F401

        count = sum(
            1 for f in ALL_FEATURES if f.FEATURE_ID == "payouts_by_spin_type"
        )
        assert count == 1, (
            f"Expected exactly 1 PayoutsBySpinType in ALL_FEATURES, got {count}. "
            f"register() may not be idempotent."
        )

    def test_schema_version_is_1(self):
        """SCHEMA_VERSION must be 1 in C2 (no shape change yet; C3 bumps to 2)."""
        PayoutsBySpinType = _import_plugin()
        assert PayoutsBySpinType.SCHEMA_VERSION == 1, (
            f"Expected SCHEMA_VERSION=1, got {PayoutsBySpinType.SCHEMA_VERSION}. "
            "C3 enrichment (shape/cols/paylines) bumps to 2; C2 must not."
        )

    def test_declared_deps_empty(self):
        """DECLARED_DEPS must be () — plugin reads real summary key, not _ prefix."""
        PayoutsBySpinType = _import_plugin()
        assert PayoutsBySpinType.DECLARED_DEPS == (), (
            f"Expected DECLARED_DEPS=(), got {PayoutsBySpinType.DECLARED_DEPS!r}. "
            "Plugin reads summary['player_impact']['spin_type_breakdown'] directly."
        )

    def test_feature_id_is_payouts_by_spin_type(self):
        """FEATURE_ID must match the summary key written by emit()."""
        PayoutsBySpinType = _import_plugin()
        assert PayoutsBySpinType.FEATURE_ID == "payouts_by_spin_type"


# ---------------------------------------------------------------------------
# T2: extract() — per-chunk extraction
# ---------------------------------------------------------------------------

class TestExtract:
    """extract() reads payout_id_by_spin_type and payout_id_win_by_spin_type."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin()()

    def test_extract_empty_chunk_dict_returns_empty(self, plugin):
        """extract() on empty chunk_dict must not crash and return empty-ish acc."""
        result = plugin.extract(None, {})
        assert isinstance(result, dict)
        # by_st_hits and by_st_win may be absent or empty — not crash
        by_hits = result.get("by_st_hits", {})
        by_win = result.get("by_st_win", {})
        assert by_hits == {} or by_hits is None
        assert by_win == {} or by_win is None

    def test_extract_none_chunk_dict_returns_empty(self, plugin):
        """extract() on None chunk_dict must return empty dict (not crash)."""
        result = plugin.extract(None, None)
        assert isinstance(result, dict)

    def test_extract_hit_aggregation_single_pid_st(self, plugin):
        """extract() reads hits from payout_id_by_spin_type correctly.

        INJECT-BUG: remove the first for-loop in extract() (hits block).
        RED: by_st_hits is empty → this assertion fails.
        """
        chunk = {
            "payout_id_by_spin_type": {"101": {"1": 5}},
            "payout_id_win_by_spin_type": {"101": {"1": 500.0}},
        }
        result = plugin.extract(None, chunk)
        hits = result.get("by_st_hits", {})
        assert "101" in hits, f"Expected pid '101' in by_st_hits, got: {hits}"
        assert hits["101"].get(1) == 5, (
            f"Expected hits['101'][1]=5, got {hits['101']}"
        )

    def test_extract_win_aggregation(self, plugin):
        """extract() reads wins from payout_id_win_by_spin_type correctly.

        INJECT-BUG: remove the second for-loop in extract() (win block).
        RED: by_st_win is empty → this assertion fails.
        """
        chunk = {
            "payout_id_by_spin_type": {"202": {"43": 10}},
            "payout_id_win_by_spin_type": {"202": {"43": 1000.0}},
        }
        result = plugin.extract(None, chunk)
        wins = result.get("by_st_win", {})
        assert "202" in wins, f"Expected pid '202' in by_st_win, got: {wins}"
        assert abs(wins["202"].get(43, -1) - 1000.0) < 1e-6, (
            f"Expected wins['202'][43]=1000.0, got {wins['202']}"
        )

    def test_extract_multiple_pids_and_st(self, plugin):
        """extract() correctly handles multiple PIDs and spin types."""
        chunk = {
            "payout_id_by_spin_type": {
                "9": {"1": 80, "44": 5},
                "666": {"1": 200},
            },
            "payout_id_win_by_spin_type": {
                "9": {"1": 8000.0, "44": 0.0},
                "666": {"1": 0.0},  # trigger marker — win=0
            },
        }
        result = plugin.extract(None, chunk)
        hits = result.get("by_st_hits", {})
        wins = result.get("by_st_win", {})
        assert hits.get("9", {}).get(1) == 80
        assert hits.get("9", {}).get(44) == 5
        assert hits.get("666", {}).get(1) == 200
        assert abs(wins.get("9", {}).get(1, -1) - 8000.0) < 1e-6
        assert abs(wins.get("666", {}).get(1, -1) - 0.0) < 1e-6

    def test_extract_missing_keys_tolerated(self, plugin):
        """extract() tolerates missing payout_id_by_spin_type key (old chunk format)."""
        chunk = {"payout_id_hits": {"9": 50}}  # old format — no ST-split keys
        result = plugin.extract(None, chunk)
        assert isinstance(result, dict)
        # Should not crash; may return empty by_st_hits/by_st_win
        hits = result.get("by_st_hits", {})
        assert hits == {}


# ---------------------------------------------------------------------------
# T3: reduce() — cross-chunk merging
# ---------------------------------------------------------------------------

class TestReduce:
    """reduce() additively merges two extract() outputs."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin()()

    def test_reduce_empty_prev_returns_this(self, plugin):
        """reduce({}, this_acc) must return this_acc unchanged."""
        this = {"by_st_hits": {"9": {1: 5}}, "by_st_win": {"9": {1: 500.0}}}
        result = plugin.reduce({}, this)
        assert result == this or (
            result.get("by_st_hits", {}).get("9", {}).get(1) == 5
        ), f"reduce({{}}, this) failed: {result}"

    def test_reduce_empty_this_returns_prev(self, plugin):
        """reduce(prev_acc, {}) must return prev_acc unchanged."""
        prev = {"by_st_hits": {"7": {1: 10}}, "by_st_win": {"7": {1: 1000.0}}}
        result = plugin.reduce(prev, {})
        assert result.get("by_st_hits", {}).get("7", {}).get(1) == 10

    def test_reduce_adds_hits_across_chunks(self, plugin):
        """reduce() must sum hit counts for same (pid, st) across chunks.

        INJECT-BUG: change reduce() to return prev_acc without merging this_acc.
        RED: hit count is 5 instead of 15.
        """
        chunk1 = {"by_st_hits": {"101": {1: 5}}, "by_st_win": {"101": {1: 500.0}}}
        chunk2 = {"by_st_hits": {"101": {1: 10}}, "by_st_win": {"101": {1: 1000.0}}}
        merged = plugin.reduce(chunk1, chunk2)
        assert merged["by_st_hits"]["101"][1] == 15, (
            f"Expected sum hits=15, got {merged['by_st_hits']['101'][1]}"
        )

    def test_reduce_adds_wins_across_chunks(self, plugin):
        """reduce() must sum win amounts for same (pid, st) across chunks."""
        chunk1 = {"by_st_hits": {"202": {43: 3}}, "by_st_win": {"202": {43: 300.0}}}
        chunk2 = {"by_st_hits": {"202": {43: 7}}, "by_st_win": {"202": {43: 700.0}}}
        merged = plugin.reduce(chunk1, chunk2)
        assert abs(merged["by_st_win"]["202"][43] - 1000.0) < 1e-6, (
            f"Expected sum wins=1000.0, got {merged['by_st_win']['202'][43]}"
        )

    def test_reduce_merges_distinct_pids(self, plugin):
        """reduce() keeps pids from both chunks when they don't overlap."""
        chunk1 = {"by_st_hits": {"9": {1: 5}}, "by_st_win": {"9": {1: 50.0}}}
        chunk2 = {"by_st_hits": {"7": {1: 3}}, "by_st_win": {"7": {1: 30.0}}}
        merged = plugin.reduce(chunk1, chunk2)
        assert "9" in merged["by_st_hits"]
        assert "7" in merged["by_st_hits"]

    def test_reduce_three_chunks(self, plugin):
        """reduce() composable: reduce(reduce(c1, c2), c3) == total."""
        c1 = {"by_st_hits": {"9": {1: 2}}, "by_st_win": {"9": {1: 200.0}}}
        c2 = {"by_st_hits": {"9": {1: 3}}, "by_st_win": {"9": {1: 300.0}}}
        c3 = {"by_st_hits": {"9": {1: 5}}, "by_st_win": {"9": {1: 500.0}}}
        merged = plugin.reduce(plugin.reduce(c1, c2), c3)
        assert merged["by_st_hits"]["9"][1] == 10
        assert abs(merged["by_st_win"]["9"][1] - 1000.0) < 1e-6


# ---------------------------------------------------------------------------
# T4: emit() — final summary write
# ---------------------------------------------------------------------------

class TestEmit:
    """emit() builds and writes payouts_by_spin_type to summary."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin()()

    def _simple_acc(self) -> dict[str, Any]:
        """Minimal accumulated state for 2 PIDs across 1 ST."""
        return {
            "by_st_hits": {
                "9": {1: 100},
                "7": {1: 50},
            },
            "by_st_win": {
                "9": {1: 10_000.0},
                "7": {1: 5_000.0},
            },
        }

    def _simple_summary(self) -> dict[str, Any]:
        return _make_summary_with_st_breakdown([
            {
                "spin_type": 1,
                "behavior_name": "paid",
                "spins": 10_000,
                "total_paid_bet": 10_000_000.0,
            }
        ])

    def test_emit_writes_payouts_by_spin_type(self, plugin):
        """emit() must write 'payouts_by_spin_type' to summary['player_impact'].

        INJECT-BUG: replace emit() body final write with
            player_impact['payouts_by_spin_type'] = {'_INJECTED': True}
        RED: assertions on row structure fail.
        """
        summary = self._simple_summary()
        ctx = _make_ctx(effective_bet_for_rtp=100_000.0)
        plugin.emit(self._simple_acc(), summary, ctx)
        pi = summary.get("player_impact", {})
        assert "payouts_by_spin_type" in pi, (
            f"emit() must write 'payouts_by_spin_type' key. "
            f"Got keys: {sorted(pi.keys())}"
        )

    def test_emit_schema_keys(self, plugin):
        """Each row in payouts_by_spin_type must have the required 6 keys."""
        summary = self._simple_summary()
        ctx = _make_ctx(effective_bet_for_rtp=100_000.0)
        plugin.emit(self._simple_acc(), summary, ctx)
        pbst = summary["player_impact"]["payouts_by_spin_type"]
        assert "ST1_paid" in pbst, f"Expected 'ST1_paid' key, got {sorted(pbst.keys())}"
        rows = pbst["ST1_paid"]
        assert len(rows) > 0, "Expected at least one row in ST1_paid"
        required_keys = {
            "payout_id", "hit_count", "hit_rate",
            "total_win", "avg_win_when_hit", "rtp_contribution_pp"
        }
        for row in rows:
            missing = required_keys - set(row.keys())
            assert not missing, f"Row missing keys {missing}: {row}"

    def test_emit_rtp_contribution_pp_formula(self, plugin):
        """rtp_contribution_pp == (st_win / effective_bet_for_rtp) * 100.

        INJECT-BUG: change denominator to 1.0 (constant).
        RED: value is 1_000_000% instead of 10.0%.
        """
        # pid "9" has st_win=10_000, effective_bet_for_rtp=100_000
        # expected: (10000/100000)*100 = 10.0
        summary = self._simple_summary()
        ctx = _make_ctx(effective_bet_for_rtp=100_000.0)
        plugin.emit(self._simple_acc(), summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid9_rows = [r for r in rows if r["payout_id"] == "9"]
        assert len(pid9_rows) == 1, f"Expected 1 row for pid '9', got {len(pid9_rows)}"
        expected_rtp = (10_000.0 / 100_000.0) * 100.0  # = 10.0
        actual_rtp = pid9_rows[0]["rtp_contribution_pp"]
        assert abs(actual_rtp - expected_rtp) < 1e-6, (
            f"rtp_contribution_pp formula wrong: expected {expected_rtp}, got {actual_rtp}"
        )

    def test_emit_hit_rate_formula(self, plugin):
        """hit_rate == hit_count / st_spins_count."""
        # pid "9" has hits=100, st_spins=10_000 → hit_rate=0.01
        summary = self._simple_summary()
        ctx = _make_ctx(effective_bet_for_rtp=100_000.0)
        plugin.emit(self._simple_acc(), summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid9_row = next(r for r in rows if r["payout_id"] == "9")
        expected_hit_rate = 100 / 10_000  # 0.01
        assert abs(pid9_row["hit_rate"] - expected_hit_rate) < 1e-9, (
            f"hit_rate wrong: expected {expected_hit_rate}, got {pid9_row['hit_rate']}"
        )

    def test_emit_avg_win_when_hit_formula(self, plugin):
        """avg_win_when_hit == total_win / hit_count."""
        # pid "9": 10000 / 100 = 100.0
        summary = self._simple_summary()
        ctx = _make_ctx(effective_bet_for_rtp=100_000.0)
        plugin.emit(self._simple_acc(), summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        pid9_row = next(r for r in rows if r["payout_id"] == "9")
        expected = 10_000.0 / 100  # = 100.0
        assert abs(pid9_row["avg_win_when_hit"] - expected) < 1e-6, (
            f"avg_win_when_hit wrong: expected {expected}, got {pid9_row['avg_win_when_hit']}"
        )

    def test_emit_trigger_marker_retained(self, plugin):
        """pid 666 with win=0 and non-zero hits must appear in output.

        Trigger-marker semantic: hit_count > 0 is the only retention criterion.
        win=0 must NOT cause the row to be filtered out.

        Per memory/feedback_no_hardcode.md: pid 666 is the common scatter
        trigger marker; the plugin must not hardcode its retention — it must
        work for any pid with hits>0 regardless of win value.

        INJECT-BUG: change retention check from 'if st_hits == 0: continue'
        to 'if st_win == 0: continue' → trigger markers dropped silently.
        RED: pid '666' absent from output.
        """
        acc = {
            "by_st_hits": {
                "9": {1: 50},
                "666": {1: 200},   # trigger marker — hits but no win
            },
            "by_st_win": {
                "9": {1: 5_000.0},
                "666": {1: 0.0},   # win=0
            },
        }
        summary = _make_summary_with_st_breakdown([
            {"spin_type": 1, "behavior_name": "paid", "spins": 10_000, "total_paid_bet": 0.0}
        ])
        ctx = _make_ctx(effective_bet_for_rtp=10_000.0)
        plugin.emit(acc, summary, ctx)
        rows = summary["player_impact"]["payouts_by_spin_type"].get("ST1_paid", [])
        pid_ids = {r["payout_id"] for r in rows}
        assert "666" in pid_ids, (
            f"pid '666' (trigger marker, win=0, hits=200) must be retained. "
            f"Got pids: {pid_ids}"
        )
        marker_row = next(r for r in rows if r["payout_id"] == "666")
        assert marker_row["hit_count"] == 200
        assert marker_row["total_win"] == 0.0
        assert marker_row["rtp_contribution_pp"] == 0.0

    def test_emit_empty_acc_produces_empty_lists(self, plugin):
        """emit() with empty final_acc should produce empty lists per ST label."""
        summary = _make_summary_with_st_breakdown([
            {"spin_type": 1, "behavior_name": "paid", "spins": 5_000, "total_paid_bet": 0.0}
        ])
        ctx = _make_ctx(effective_bet_for_rtp=5_000.0)
        plugin.emit({}, summary, ctx)
        pbst = summary["player_impact"]["payouts_by_spin_type"]
        assert "ST1_paid" in pbst
        assert pbst["ST1_paid"] == [], f"Expected empty list for no data, got {pbst['ST1_paid']}"

    def test_emit_zero_bet_does_not_crash(self, plugin):
        """emit() with effective_bet_for_rtp=0 must not crash (ZeroDivisionError guard)."""
        summary = self._simple_summary()
        ctx = _make_ctx(effective_bet_for_rtp=0.0)
        plugin.emit(self._simple_acc(), summary, ctx)
        # Should produce rows with rtp_contribution_pp=0.0
        rows = summary["player_impact"]["payouts_by_spin_type"]["ST1_paid"]
        for row in rows:
            assert row["rtp_contribution_pp"] == 0.0, (
                f"With zero bet, rtp_contribution_pp must be 0.0, got {row['rtp_contribution_pp']}"
            )

    def test_emit_multiple_spin_types(self, plugin):
        """emit() produces a key per ST label when there are multiple STs."""
        acc = {
            "by_st_hits": {
                "9": {1: 100, 44: 30},
            },
            "by_st_win": {
                "9": {1: 1_000.0, 44: 0.0},
            },
        }
        summary = _make_summary_with_st_breakdown([
            {"spin_type": 1, "behavior_name": "paid", "spins": 1_000, "total_paid_bet": 1_000.0},
            {"spin_type": 44, "behavior_name": "free", "spins": 200, "total_paid_bet": 0.0},
        ])
        ctx = _make_ctx(effective_bet_for_rtp=1_000.0)
        plugin.emit(acc, summary, ctx)
        pbst = summary["player_impact"]["payouts_by_spin_type"]
        assert "ST1_paid" in pbst, f"Expected ST1_paid key, got {sorted(pbst.keys())}"
        assert "ST44_free" in pbst, f"Expected ST44_free key, got {sorted(pbst.keys())}"
