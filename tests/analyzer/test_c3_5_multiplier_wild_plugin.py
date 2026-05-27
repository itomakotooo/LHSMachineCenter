"""Phase C3.5 — unit tests for multiplier_wild plugin.

Tests extract() / reduce() / emit() behaviour using synthetic chunk_dict data.
Does NOT spawn subprocesses — unit-level correctness only.
Subprocess-level tests live in test_c3_5_m275_e2e.py and
test_c3_5_m14_no_multiplier_wild.py.

Invariants asserted
-------------------
1. Plugin imports clean (import has no I/O side effects).
2. FEATURE_ID == "multiplier_wild".
3. SCHEMA_VERSION == 1.
4. RTP_CONTRIBUTION == True.
5. DECLARED_DEPS == ().
6. register() is idempotent — duplicate import does not grow ALL_FEATURES.
7. extract() with wildNx symbols parses multiplier values via regex.
8. extract() with NO wildNx symbols returns empty accumulators (applicable=False path).
9. extract() with None / non-dict chunk_dict returns empty accumulators (robustness).
10. reduce() merges by_col additively across chunks (same symbol + same col → summed).
11. reduce() merges by_st additively across chunks (same symbol + same ST → summed).
12. reduce() handles new symbol appearing only in second chunk.
13. reduce() handles empty prev_acc (first chunk).
14. emit() reads ctx.total_spins for hit_rate denominator.
15. emit() writes summary["player_impact"]["multiplier_wild"] with correct schema.
16. emit() applicable=True when wildNx symbols observed.
17. emit() applicable=False when no wildNx symbols observed.
18. emit() variants sorted by multiplier_value ascending (wild2x first, wild10x last).
19. emit() estimated_rtp_contribution_pp is null.
20. emit() estimated_rtp_method == "deferred_v2".
21. emit() by_column entries sorted by col index numerically.
22. emit() by_spin_type uses _ST_BEHAVIOR dict for known STs (1=paid, 140=paid, 126=free).
23. emit() by_spin_type uses "other" label for unknown ST.
24. emit() total_hits = sum of col_data values for each variant.
25. emit() total_multiplier_wild_hits = sum across all variants.

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug A — regex never matches (no variants extracted):
    In multiplier_wild.py, change:
        _WILD_NX_RE = re.compile(r"^wild(\\d+)x$")
    to:
        _WILD_NX_RE = re.compile(r"^NOMATCH(\\d+)x$")
    RED: test_extract_parses_wild2x_variant + test_extract_multiple_variants fail.
    Revert (restore original regex) → GREEN.

Bug B — emit() always emits empty variants list:
    In multiplier_wild.py MultiplierWild.emit(), change:
        variants: list[dict[str, Any]] = []
        for sym in sorted(all_syms):
            ...
            variants.append({...})
    to:
        variants: list[dict[str, Any]] = []
        # bug: skip loop
    RED: test_emit_variants_populated fails (variants == []).
    Revert → GREEN.

Bug C — reduce() uses assignment instead of addition (not additive):
    In _merge() inside reduce(), change:
        dest[k] = dest.get(k, 0) + v
    to:
        dest[k] = v
    RED: test_reduce_by_col_additive fails (count is 200 not 300 when same col present).
    Revert → GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_subprocess_import_suicide_and_module_globals.md
  (register() must be pure list-append — no I/O at import time)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (applicable=False is an explicit signal, NOT a catch-all bucket)
- memory/feedback_no_hardcode.md
  (regex-based: generic, not hardcoded to 2/5/10 only)
- memory/feedback_prefer_complex_better.md
  (generic regex over hardcoded symbol list)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_plugin_class():
    try:
        from fresh_slotlab.analyzer.features.multiplier_wild import MultiplierWild
    except ImportError:
        from analyzer.features.multiplier_wild import MultiplierWild  # type: ignore[no-redef]
    return MultiplierWild


def _make_ctx(total_spins: int = 10_000) -> Any:
    """Build a minimal PipelineContext-like object."""
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext, MechanismRegistry
    except ImportError:
        from analyzer.pipeline_context import PipelineContext, MechanismRegistry  # type: ignore[no-redef]
    return PipelineContext(
        effective_bet_for_rtp=10_000_000.0,
        total_spins=total_spins,
        total_paid_sessions=total_spins,
        total_paid_spins=total_spins,
        clamp_pending_robots_total=0,
        robots_with_pending_cycle=0,
        mechanism_registry=MechanismRegistry(),
        manifest={},
    )


def _chunk_with_wilds(
    by_col: dict[str, dict[str, int]],
    by_st: dict[str, dict[str, dict[str, int]]] | None = None,
) -> dict:
    """Build a synthetic chunk_dict with symbol_counts_by_col[_by_spin_type]."""
    chunk = {"symbol_counts_by_col": by_col}
    if by_st is not None:
        chunk["symbol_counts_by_col_by_spin_type"] = by_st
    return chunk


# ---------------------------------------------------------------------------
# T1: Plugin class-level invariants
# ---------------------------------------------------------------------------

class TestMultiplierWildClassInvariants:
    """Plugin class-level invariants: FEATURE_ID / SCHEMA_VERSION / RTP_CONTRIBUTION."""

    def test_feature_id(self):
        """FEATURE_ID must be 'multiplier_wild'.

        INJECT-BUG: change FEATURE_ID to 'multiplier_wild_v2'.
        RED: this assertion fires.
        Revert → GREEN.
        """
        mw = _import_plugin_class()
        assert mw.FEATURE_ID == "multiplier_wild", (
            f"FEATURE_ID must be 'multiplier_wild', got {mw.FEATURE_ID!r}"
        )

    def test_schema_version_is_1(self):
        """SCHEMA_VERSION must be 1 (C3.5 ships v1 of this plugin schema).

        INJECT-BUG: set SCHEMA_VERSION = 2 in plugin file.
        RED: this assertion fires.
        Revert → GREEN.
        """
        mw = _import_plugin_class()
        assert mw.SCHEMA_VERSION == 1, (
            f"SCHEMA_VERSION must be 1, got {mw.SCHEMA_VERSION}"
        )

    def test_rtp_contribution_is_true(self):
        """RTP_CONTRIBUTION must be True (plugin declares it contributes to RTP).

        INJECT-BUG: set RTP_CONTRIBUTION = False.
        RED: this assertion fires.
        Revert → GREEN.
        """
        mw = _import_plugin_class()
        assert mw.RTP_CONTRIBUTION is True, (
            f"RTP_CONTRIBUTION must be True, got {mw.RTP_CONTRIBUTION!r}"
        )

    def test_declared_deps_is_empty_tuple(self):
        """DECLARED_DEPS must be () — plugin has no upstream summary temp-key deps."""
        mw = _import_plugin_class()
        assert mw.DECLARED_DEPS == (), (
            f"DECLARED_DEPS must be (), got {mw.DECLARED_DEPS!r}"
        )

    def test_registered_fallback_rules_is_empty(self):
        """REGISTERED_FALLBACK_RULES must be {} (no backward-compat rules in v1)."""
        mw = _import_plugin_class()
        assert mw.REGISTERED_FALLBACK_RULES == {}, (
            f"REGISTERED_FALLBACK_RULES must be {{}}, got {mw.REGISTERED_FALLBACK_RULES!r}"
        )

    def test_schema_keys_contains_multiplier_wild(self):
        """SCHEMA_KEYS must contain 'multiplier_wild'."""
        mw = _import_plugin_class()
        assert "multiplier_wild" in mw.SCHEMA_KEYS, (
            f"SCHEMA_KEYS must contain 'multiplier_wild', got {mw.SCHEMA_KEYS!r}"
        )


# ---------------------------------------------------------------------------
# T2: Import safety + registration idempotency
# ---------------------------------------------------------------------------

class TestMultiplierWildImportSafety:
    """Import must be side-effect free; register() must be idempotent."""

    def test_import_clean(self):
        """Importing multiplier_wild must not raise or produce stderr.

        Per feedback_subprocess_import_suicide_and_module_globals.md:
        module import must not trigger I/O or process manipulation.
        """
        import importlib
        # Should import cleanly (no I/O, no error)
        try:
            mod = importlib.import_module("fresh_slotlab.analyzer.features.multiplier_wild")
        except ImportError:
            mod = importlib.import_module("analyzer.features.multiplier_wild")
        assert hasattr(mod, "MultiplierWild"), "MultiplierWild class not found after import"

    def test_register_idempotent(self):
        """Calling register() twice on MultiplierWild must not grow ALL_FEATURES.

        Per feature_registry design: register() is idempotent — same FEATURE_ID
        results in silent no-op on second call.
        """
        try:
            from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES, register
        except ImportError:
            from analyzer.feature_registry import ALL_FEATURES, register  # type: ignore[no-redef]

        MultiplierWild = _import_plugin_class()
        before_count = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "multiplier_wild")

        # Try to register again
        register(MultiplierWild())

        after_count = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "multiplier_wild")
        assert after_count == before_count, (
            f"register() is not idempotent: multiplier_wild count grew from "
            f"{before_count} to {after_count}. Expected no-op on duplicate."
        )

    def test_multiplier_wild_in_all_features_after_import(self):
        """After importing the plugin module, ALL_FEATURES must contain multiplier_wild.

        This is the C3.5 registration invariant: the plugin registers itself at
        module import time via register(MultiplierWild()).
        """
        try:
            import fresh_slotlab.analyzer.features.multiplier_wild  # noqa: F401
            from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
        except ImportError:
            import analyzer.features.multiplier_wild  # type: ignore[no-redef]  # noqa: F401
            from analyzer.feature_registry import ALL_FEATURES  # type: ignore[no-redef]

        fids = [f.FEATURE_ID for f in ALL_FEATURES]
        assert "multiplier_wild" in fids, (
            f"'multiplier_wild' not in ALL_FEATURES after import. "
            f"Got: {fids}"
        )


# ---------------------------------------------------------------------------
# T3: extract() correctness
# ---------------------------------------------------------------------------

class TestMultiplierWildExtract:
    """extract() reads symbol_counts_by_col + symbol_counts_by_col_by_spin_type."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_extract_parses_wild2x_variant(self, plugin):
        """extract() detects 'wild2x' symbol and accumulates col counts.

        INJECT-BUG (Bug A): change regex to ^NOMATCH(\\d+)x$.
        RED: by_col is empty (no match) → test fails.
        Revert → GREEN.
        """
        chunk = _chunk_with_wilds(
            by_col={"1": {"wild2x": 500, "bar": 200}},
        )
        acc = plugin.extract(None, chunk)
        by_col = acc.get("by_col", {})
        assert "wild2x" in by_col, (
            f"'wild2x' must be detected by extract(). Got by_col keys: {list(by_col.keys())}"
        )
        assert by_col["wild2x"].get("1") == 500, (
            f"wild2x col '1' count must be 500, got {by_col['wild2x'].get('1')}"
        )

    def test_extract_ignores_non_wildnx_symbols(self, plugin):
        """extract() must NOT include regular 'wild' or 'bar' symbols."""
        chunk = _chunk_with_wilds(
            by_col={"1": {"wild": 300, "bar": 200, "seven": 100, "wild2x": 50}},
        )
        acc = plugin.extract(None, chunk)
        by_col = acc.get("by_col", {})
        assert "wild" not in by_col, f"'wild' (no multiplier) must not appear in by_col: {by_col}"
        assert "bar" not in by_col, f"'bar' must not appear in by_col: {by_col}"
        assert "wild2x" in by_col, f"'wild2x' must be in by_col: {by_col}"

    def test_extract_multiple_variants(self, plugin):
        """extract() detects wild2x, wild5x, wild10x simultaneously.

        INJECT-BUG (Bug A): change regex to ^NOMATCH(\\d+)x$.
        RED: by_col is empty → test fails.
        Revert → GREEN.
        """
        chunk = _chunk_with_wilds(
            by_col={
                "1": {"wild2x": 100, "wild5x": 200, "wild10x": 50, "other": 999},
            },
        )
        acc = plugin.extract(None, chunk)
        by_col = acc.get("by_col", {})
        assert set(by_col.keys()) == {"wild2x", "wild5x", "wild10x"}, (
            f"Expected exactly wild2x/wild5x/wild10x in by_col, got {set(by_col.keys())}"
        )

    def test_extract_no_wildnx_symbols_returns_empty(self, plugin):
        """extract() with NO wildNx symbols returns empty accumulators.

        This is the 'vanilla machine' path — applicable=False in emit().
        Per feedback_invariant_with_fallback_hides_drift.md: empty by_col/by_st
        is the explicit 'no data' signal, not a catch-all bucket.
        """
        chunk = _chunk_with_wilds(
            by_col={"1": {"wild": 300, "bar": 200}, "2": {"seven": 100}},
        )
        acc = plugin.extract(None, chunk)
        assert acc["by_col"] == {}, (
            f"by_col must be empty when no wildNx symbols: {acc['by_col']}"
        )
        assert acc["by_st"] == {}, (
            f"by_st must be empty when no wildNx symbols: {acc['by_st']}"
        )

    def test_extract_none_chunk_returns_empty(self, plugin):
        """extract() with None chunk_dict returns empty accumulators safely."""
        acc = plugin.extract(None, None)
        assert acc == {"by_col": {}, "by_st": {}}, (
            f"Expected {{'by_col': {{}}, 'by_st': {{}}}} for None chunk, got {acc}"
        )

    def test_extract_non_dict_chunk_returns_empty(self, plugin):
        """extract() with non-dict chunk_dict returns empty accumulators safely."""
        acc = plugin.extract(None, "not_a_dict")
        assert acc == {"by_col": {}, "by_st": {}}, (
            f"Expected empty acc for non-dict chunk, got {acc}"
        )

    def test_extract_by_st_from_symbol_counts_by_col_by_spin_type(self, plugin):
        """extract() aggregates by_st across all cols from symbol_counts_by_col_by_spin_type."""
        chunk = _chunk_with_wilds(
            by_col={"1": {"wild2x": 100}},
            by_st={
                "140": {"1": {"wild2x": 80}},
                "126": {"1": {"wild2x": 20}},
            },
        )
        acc = plugin.extract(None, chunk)
        by_st = acc.get("by_st", {})
        assert "wild2x" in by_st, f"'wild2x' missing from by_st: {by_st}"
        assert by_st["wild2x"].get("140") == 80, (
            f"wild2x ST=140 count must be 80, got {by_st['wild2x'].get('140')}"
        )
        assert by_st["wild2x"].get("126") == 20, (
            f"wild2x ST=126 count must be 20, got {by_st['wild2x'].get('126')}"
        )

    def test_extract_by_st_aggregates_across_columns(self, plugin):
        """extract() sums by_st counts across all columns for a given ST."""
        # Same symbol in both col 1 and col 2 for the same ST
        chunk = _chunk_with_wilds(
            by_col={"1": {"wild2x": 50}, "2": {"wild2x": 30}},
            by_st={
                "1": {
                    "1": {"wild2x": 50},
                    "2": {"wild2x": 30},
                },
            },
        )
        acc = plugin.extract(None, chunk)
        by_st = acc.get("by_st", {})
        # ST=1 should have 50+30 = 80 total for wild2x
        assert by_st.get("wild2x", {}).get("1") == 80, (
            f"wild2x ST=1 should be 80 (50+30 across cols), "
            f"got {by_st.get('wild2x', {}).get('1')}"
        )

    def test_extract_missing_by_st_key_falls_back_to_empty(self, plugin):
        """extract() tolerates missing symbol_counts_by_col_by_spin_type."""
        chunk = _chunk_with_wilds(
            by_col={"1": {"wild2x": 100}},
            # No by_st key in chunk_dict
        )
        acc = plugin.extract(None, chunk)
        # by_st should be empty (no ST breakdown available)
        assert acc["by_st"] == {}, (
            f"by_st should be empty when symbol_counts_by_col_by_spin_type absent: {acc['by_st']}"
        )

    def test_extract_multiple_cols_same_symbol(self, plugin):
        """extract() accumulates same symbol across multiple columns in by_col."""
        chunk = _chunk_with_wilds(
            by_col={
                "0": {"wild2x": 10},
                "1": {"wild2x": 100},
                "2": {"wild2x": 5},
            },
        )
        acc = plugin.extract(None, chunk)
        by_col = acc["by_col"]
        assert by_col["wild2x"]["0"] == 10
        assert by_col["wild2x"]["1"] == 100
        assert by_col["wild2x"]["2"] == 5


# ---------------------------------------------------------------------------
# T4: reduce() correctness
# ---------------------------------------------------------------------------

class TestMultiplierWildReduce:
    """reduce() merges by_col + by_st additively across chunks."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_reduce_by_col_additive(self, plugin):
        """by_col merges additively: same (symbol, col) sums counts.

        INJECT-BUG (Bug C): change `dest[k] = dest.get(k, 0) + v` to `dest[k] = v`.
        RED: wild2x col '1' = 200 instead of 300.
        Revert → GREEN.
        """
        acc1 = {"by_col": {"wild2x": {"1": 100}}, "by_st": {}}
        acc2 = {"by_col": {"wild2x": {"1": 200}}, "by_st": {}}
        merged = plugin.reduce(acc1, acc2)
        assert merged["by_col"]["wild2x"]["1"] == 300, (
            f"by_col reduce must sum additively: expected 300, got "
            f"{merged['by_col']['wild2x']['1']}"
        )

    def test_reduce_by_st_additive(self, plugin):
        """by_st merges additively across chunks.

        INJECT-BUG (Bug C): assignment instead of addition.
        RED: wild5x ST '140' = 2000 instead of 3000.
        Revert → GREEN.
        """
        acc1 = {"by_col": {}, "by_st": {"wild5x": {"140": 1000}}}
        acc2 = {"by_col": {}, "by_st": {"wild5x": {"140": 2000}}}
        merged = plugin.reduce(acc1, acc2)
        assert merged["by_st"]["wild5x"]["140"] == 3000, (
            f"by_st reduce must sum additively: expected 3000, got "
            f"{merged['by_st']['wild5x']['140']}"
        )

    def test_reduce_new_symbol_in_second_chunk(self, plugin):
        """reduce() keeps symbols that appear in only one chunk."""
        acc1 = {"by_col": {"wild2x": {"1": 100}}, "by_st": {"wild2x": {"1": 80}}}
        acc2 = {"by_col": {"wild5x": {"1": 200}}, "by_st": {"wild5x": {"1": 150}}}
        merged = plugin.reduce(acc1, acc2)
        assert "wild2x" in merged["by_col"], "wild2x from chunk1 missing in merged"
        assert "wild5x" in merged["by_col"], "wild5x from chunk2 missing in merged"
        assert merged["by_col"]["wild2x"]["1"] == 100
        assert merged["by_col"]["wild5x"]["1"] == 200

    def test_reduce_empty_prev_returns_this(self, plugin):
        """reduce({}, this_acc) returns this_acc (first chunk base case)."""
        this = {"by_col": {"wild2x": {"1": 100}}, "by_st": {"wild2x": {"140": 80}}}
        merged = plugin.reduce({}, this)
        assert merged["by_col"]["wild2x"]["1"] == 100, (
            f"reduce({{}}, this) must return this. Got: {merged}"
        )

    def test_reduce_empty_this_returns_prev(self, plugin):
        """reduce(prev, {}) returns prev (empty chunk — robustness)."""
        prev = {"by_col": {"wild2x": {"1": 100}}, "by_st": {}}
        merged = plugin.reduce(prev, {})
        assert merged["by_col"]["wild2x"]["1"] == 100, (
            f"reduce(prev, {{}}) must return prev. Got: {merged}"
        )

    def test_reduce_new_col_in_second_chunk(self, plugin):
        """reduce() merges cols not present in first chunk."""
        acc1 = {"by_col": {"wild2x": {"1": 100}}, "by_st": {}}
        acc2 = {"by_col": {"wild2x": {"2": 50}}, "by_st": {}}
        merged = plugin.reduce(acc1, acc2)
        assert merged["by_col"]["wild2x"]["1"] == 100
        assert merged["by_col"]["wild2x"]["2"] == 50


# ---------------------------------------------------------------------------
# T5: emit() correctness
# ---------------------------------------------------------------------------

class TestMultiplierWildEmit:
    """emit() builds summary["player_impact"]["multiplier_wild"] correctly."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_emit_applicable_true_when_wilds_observed(self, plugin):
        """emit() sets applicable=True when by_col has wildNx symbols.

        INJECT-BUG (Bug B): skip the variant loop so all_syms is always empty.
        RED: applicable is False instead of True.
        Revert → GREEN.
        """
        acc = {
            "by_col": {"wild2x": {"1": 100}},
            "by_st": {"wild2x": {"140": 80, "126": 20}},
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        mw = summary["player_impact"]["multiplier_wild"]
        assert mw["applicable"] is True, (
            f"applicable must be True when wildNx symbols observed. Got: {mw['applicable']!r}"
        )

    def test_emit_applicable_false_when_no_wilds(self, plugin):
        """emit() sets applicable=False and empty variants when no wildNx symbols.

        Per feedback_invariant_with_fallback_hides_drift.md: explicit signal.
        """
        acc = {"by_col": {}, "by_st": {}}
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        mw = summary["player_impact"]["multiplier_wild"]
        assert mw["applicable"] is False, (
            f"applicable must be False when no wildNx symbols. Got: {mw['applicable']!r}"
        )
        assert mw["variants"] == [], (
            f"variants must be [] when applicable=False. Got: {mw['variants']}"
        )

    def test_emit_variants_sorted_by_multiplier_value_ascending(self, plugin):
        """emit() sorts variants by multiplier_value ascending (wild2x first).

        INJECT-BUG (Bug B): reverse sort.
        RED: variants[0]['symbol'] = 'wild10x' not 'wild2x'.
        Revert → GREEN.
        """
        acc = {
            "by_col": {
                "wild10x": {"1": 50},
                "wild5x": {"1": 200},
                "wild2x": {"1": 100},
            },
            "by_st": {},
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        variants = summary["player_impact"]["multiplier_wild"]["variants"]
        symbols_in_order = [v["symbol"] for v in variants]
        assert symbols_in_order == ["wild2x", "wild5x", "wild10x"], (
            f"Variants must be sorted by multiplier_value ascending. "
            f"Got: {symbols_in_order}"
        )

    def test_emit_multiplier_value_extracted_from_symbol_name(self, plugin):
        """emit() extracts multiplier_value from symbol name via regex."""
        acc = {
            "by_col": {"wild7x": {"1": 100}},
            "by_st": {"wild7x": {"1": 100}},
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        variants = summary["player_impact"]["multiplier_wild"]["variants"]
        assert len(variants) == 1
        assert variants[0]["multiplier_value"] == 7, (
            f"multiplier_value for wild7x must be 7, got {variants[0]['multiplier_value']}"
        )

    def test_emit_total_hits_is_sum_of_col_counts(self, plugin):
        """total_hits per variant = sum of all col counts in by_col for that symbol."""
        acc = {
            "by_col": {"wild2x": {"1": 100, "2": 50, "3": 25}},
            "by_st": {},
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        variants = summary["player_impact"]["multiplier_wild"]["variants"]
        assert variants[0]["total_hits"] == 175, (
            f"total_hits must be 100+50+25=175, got {variants[0]['total_hits']}"
        )

    def test_emit_hit_rate_uses_ctx_total_spins(self, plugin):
        """emit() uses ctx.total_spins as hit_rate denominator.

        hit_rate = hits / total_spins. If total_spins changes, hit_rate changes.
        This verifies the denominator source.
        """
        acc = {"by_col": {"wild2x": {"1": 100}}, "by_st": {}}
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(total_spins=5_000))
        variants = summary["player_impact"]["multiplier_wild"]["variants"]
        hit_rate = variants[0]["by_column"][0]["hit_rate"]
        expected = round(100 / 5_000, 6)
        assert abs(hit_rate - expected) < 1e-9, (
            f"hit_rate must be 100/5000={expected}, got {hit_rate}"
        )

    def test_emit_by_column_sorted_numerically(self, plugin):
        """emit() by_column entries sorted by col index numerically."""
        acc = {
            "by_col": {"wild2x": {"3": 10, "1": 50, "10": 5}},
            "by_st": {},
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        variants = summary["player_impact"]["multiplier_wild"]["variants"]
        cols = [entry["col"] for entry in variants[0]["by_column"]]
        assert cols == [1, 3, 10], (
            f"by_column must be sorted numerically, got {cols}"
        )

    def test_emit_by_spin_type_known_st_labels(self, plugin):
        """emit() uses _ST_BEHAVIOR dict for known STs: 1=paid, 140=paid, 126=free."""
        acc = {
            "by_col": {"wild2x": {"1": 150}},
            "by_st": {
                "wild2x": {"1": 50, "140": 80, "126": 20},
            },
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        variants = summary["player_impact"]["multiplier_wild"]["variants"]
        st_map = {e["spin_type"]: e["behavior"] for e in variants[0]["by_spin_type"]}
        assert st_map.get(1) == "paid", f"ST=1 must be 'paid', got {st_map.get(1)!r}"
        assert st_map.get(140) == "paid", f"ST=140 must be 'paid', got {st_map.get(140)!r}"
        assert st_map.get(126) == "free", f"ST=126 must be 'free', got {st_map.get(126)!r}"

    def test_emit_by_spin_type_unknown_st_is_other(self, plugin):
        """emit() uses 'other' label for STs not in _ST_BEHAVIOR dict."""
        acc = {
            "by_col": {"wild2x": {"1": 100}},
            "by_st": {"wild2x": {"999": 100}},
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        variants = summary["player_impact"]["multiplier_wild"]["variants"]
        st_map = {e["spin_type"]: e["behavior"] for e in variants[0]["by_spin_type"]}
        assert st_map.get(999) == "other", (
            f"Unknown ST=999 must map to 'other', got {st_map.get(999)!r}"
        )

    def test_emit_estimated_rtp_contribution_pp_is_null(self, plugin):
        """estimated_rtp_contribution_pp must be null (deferred to v2).

        Per brief §2.2: actual RTP uplift requires combining with line-win data.
        """
        acc = {"by_col": {"wild2x": {"1": 100}}, "by_st": {}}
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        mw = summary["player_impact"]["multiplier_wild"]
        assert mw["estimated_rtp_contribution_pp"] is None, (
            f"estimated_rtp_contribution_pp must be null (None in Python), "
            f"got {mw['estimated_rtp_contribution_pp']!r}"
        )

    def test_emit_estimated_rtp_method_is_deferred_v2(self, plugin):
        """estimated_rtp_method must be 'deferred_v2'."""
        acc = {"by_col": {"wild2x": {"1": 100}}, "by_st": {}}
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        mw = summary["player_impact"]["multiplier_wild"]
        assert mw["estimated_rtp_method"] == "deferred_v2", (
            f"estimated_rtp_method must be 'deferred_v2', "
            f"got {mw['estimated_rtp_method']!r}"
        )

    def test_emit_total_multiplier_wild_hits_is_sum_across_variants(self, plugin):
        """total_multiplier_wild_hits = sum of total_hits across all variants."""
        acc = {
            "by_col": {
                "wild2x": {"1": 100},
                "wild5x": {"1": 200},
                "wild10x": {"1": 50},
            },
            "by_st": {},
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        mw = summary["player_impact"]["multiplier_wild"]
        assert mw["total_multiplier_wild_hits"] == 350, (
            f"total_multiplier_wild_hits must be 100+200+50=350, "
            f"got {mw['total_multiplier_wild_hits']}"
        )

    def test_emit_variants_schema_keys(self, plugin):
        """Each variant dict must have: symbol, multiplier_value, total_hits,
        by_column, by_spin_type."""
        acc = {
            "by_col": {"wild5x": {"1": 200}},
            "by_st": {"wild5x": {"140": 200}},
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        variants = summary["player_impact"]["multiplier_wild"]["variants"]
        required_keys = {"symbol", "multiplier_value", "total_hits", "by_column", "by_spin_type"}
        for v in variants:
            missing = required_keys - set(v.keys())
            assert not missing, (
                f"Variant dict missing required keys {missing}. Got: {sorted(v.keys())}"
            )

    def test_emit_by_column_entry_schema(self, plugin):
        """Each by_column entry must have: col (int), hits (int), hit_rate (float)."""
        acc = {"by_col": {"wild2x": {"1": 100}}, "by_st": {}}
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        col_entry = summary["player_impact"]["multiplier_wild"]["variants"][0]["by_column"][0]
        assert isinstance(col_entry["col"], int), f"col must be int, got {type(col_entry['col'])}"
        assert col_entry["col"] == 1
        assert col_entry["hits"] == 100
        assert isinstance(col_entry["hit_rate"], float), (
            f"hit_rate must be float, got {type(col_entry['hit_rate'])}"
        )

    def test_emit_by_spin_type_entry_schema(self, plugin):
        """Each by_spin_type entry must have: spin_type (int), behavior (str), hits (int)."""
        acc = {
            "by_col": {"wild2x": {"1": 100}},
            "by_st": {"wild2x": {"140": 80}},
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        st_entry = summary["player_impact"]["multiplier_wild"]["variants"][0]["by_spin_type"][0]
        assert isinstance(st_entry["spin_type"], int), (
            f"spin_type must be int, got {type(st_entry['spin_type'])}"
        )
        assert isinstance(st_entry["behavior"], str), (
            f"behavior must be str, got {type(st_entry['behavior'])}"
        )
        assert isinstance(st_entry["hits"], int), (
            f"hits must be int, got {type(st_entry['hits'])}"
        )

    def test_emit_top_level_schema_keys(self, plugin):
        """multiplier_wild dict must have all 5 required top-level keys."""
        acc = {"by_col": {"wild2x": {"1": 100}}, "by_st": {}}
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(10_000))
        mw = summary["player_impact"]["multiplier_wild"]
        required = {
            "applicable", "variants", "total_multiplier_wild_hits",
            "estimated_rtp_contribution_pp", "estimated_rtp_method",
        }
        missing = required - set(mw.keys())
        assert not missing, (
            f"multiplier_wild missing required top-level keys: {missing}. "
            f"Got: {sorted(mw.keys())}"
        )

    def test_emit_zero_total_spins_hit_rate_is_zero(self, plugin):
        """emit() with ctx.total_spins=0 produces hit_rate=0.0 (no division error)."""
        acc = {"by_col": {"wild2x": {"1": 100}}, "by_st": {}}
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx(total_spins=0))
        col_entry = summary["player_impact"]["multiplier_wild"]["variants"][0]["by_column"][0]
        assert col_entry["hit_rate"] == 0.0, (
            f"hit_rate must be 0.0 when total_spins=0, got {col_entry['hit_rate']}"
        )
