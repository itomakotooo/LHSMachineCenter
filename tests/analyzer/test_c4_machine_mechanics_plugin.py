"""Phase C4 — unit tests for machine_mechanics plugin, adapted for 5C.

Phase 5C: mechanism_registry removed. Tests now drive jackpot/freespin applicable
via machine_spec_manifest (spin_types role/play declarations) instead of
MechanismRegistry. The behavioral invariants remain: jackpot.applicable and
free_spin.applicable come from declared mechanisms, NOT from raw counters.

Tests extract() / reduce() / emit() behaviour using synthetic chunk_dict data.
Does NOT spawn subprocesses — unit-level correctness only.
Subprocess-level tests live in test_c4_m275_gap_1_closed.py and siblings.

Invariants asserted (5C-adapted)
---------------------------------
1. Plugin imports clean (import has no I/O side effects).
2. FEATURE_ID == "machine_mechanics".
3. SCHEMA_VERSION == 2 (C4 adds _detection_source field).
4. REGISTERED_FALLBACK_RULES[1] == {"_detection_source": None}.
5. REQUIRES == ("bonus_chain_dynamics",).
6. RTP_CONTRIBUTION == False (display only, doesn't add to RTP totals).
7. register() is idempotent — duplicate import does not grow ALL_FEATURES.
8. machine_mechanics present in ALL_FEATURES after import.
9. extract() with synthetic chunk_dict reads all 6 mechanic sections.
10. extract() with None / non-dict chunk_dict returns zero accumulator.
11. reduce() accumulates additively for numeric fields.
12. reduce() unions set fields (ls_unique, jp_ids) across chunks.
13. reduce() takes max for fs_max_chain across chunks.
14. reduce() handles empty prev_acc (first chunk) or empty this_acc.
15. emit() composes 6-section dict: lock_lines/lock_symbols/lock_reels/jackpot/free_spin/dollar_pick.
16. emit() jackpot.applicable comes from machine_spec_manifest (declared mechanism), NOT raw counter.
17. emit() free_spin.applicable comes from machine_spec_manifest.
18. emit() jackpot._detection_source populated from derive_mechanism_flags.
19. emit() free_spin._detection_source populated from derive_mechanism_flags.
20. emit() writes to summary["player_impact"]["machine_mechanics"].
21. emit() rtp_contribution_pp = win / ebet * 100 for each section with win > 0.
22. emit() lock_lines.applicable = True only when ll_spins > 0.
23. emit() zero division protected (ebet=0 and total_spins=0 safe).
24. emit() jackpot section includes jackpot_ids from manifest jackpot_pid_set.
25. emit() all 6 sections have correct required schema keys.

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug A — emit() always sets jackpot.applicable = False regardless of manifest:
    In machine_mechanics.py MachineMechanics.emit(), inside the manifest branch,
    change: `_jp_applicable = _mflags["jackpot_applicable"]`
    to: `_jp_applicable = False`
    RED: test_emit_jackpot_applicable_from_manifest fails (False != True).
    Revert (restore original line) → GREEN.

Bug B — REGISTERED_FALLBACK_RULES wrong key:
    Change REGISTERED_FALLBACK_RULES to:
        {1: {"_detection_src": None}}  # wrong key name
    RED: test_registered_fallback_rules_v1 fails.
    Revert → GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_subprocess_import_suicide_and_module_globals.md
  (register() must be pure list-append — no I/O at import time)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (_detection_source is NOT a catch-all bucket — it's an explicit required field)
- memory/feedback_no_hardcode.md
  (no machine-specific PID or threshold hardcoding in plugin)
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
        from fresh_slotlab.analyzer.features.machine_mechanics import MachineMechanics
    except ImportError:
        from analyzer.features.machine_mechanics import MachineMechanics  # type: ignore[no-redef]
    return MachineMechanics


def _make_jackpot_manifest(
    jackpot_applicable: bool = False,
    freespin_applicable: bool = False,
) -> dict:
    """Build a minimal machine_spec_manifest that declares the requested mechanisms.

    Uses the SpinType role/play declarations that derive_mechanism_flags reads.
    jackpot play='Jackpot' → jackpot_applicable=True
    freespin play='freespin' → freespin_applicable=True
    """
    spin_types: dict = {
        "1": {"role": "paid_spin", "play": "Normal"},
    }
    if jackpot_applicable:
        spin_types["5"] = {"role": "settlement", "play": "Jackpot"}
    if freespin_applicable:
        spin_types["2"] = {"role": "settlement", "play": "freespin"}
    return {"spin_types": spin_types}


def _make_ctx(
    total_spins: int = 10_000,
    effective_bet_for_rtp: float = 10_000_000.0,
    jackpot_applicable: bool = False,
    freespin_applicable: bool = False,
    machine_spec_manifest: dict | None = None,
) -> Any:
    """Build a minimal PipelineContext for unit testing via machine_spec_manifest."""
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
    except ImportError:
        from analyzer.pipeline_context import PipelineContext  # type: ignore[no-redef]

    if machine_spec_manifest is None:
        machine_spec_manifest = _make_jackpot_manifest(
            jackpot_applicable=jackpot_applicable,
            freespin_applicable=freespin_applicable,
        )

    return PipelineContext(
        effective_bet_for_rtp=effective_bet_for_rtp,
        total_spins=total_spins,
        total_paid_sessions=total_spins,
        total_paid_spins=total_spins,
        clamp_pending_robots_total=0,
        robots_with_pending_cycle=0,
        manifest={},
        machine_spec_manifest=machine_spec_manifest,
    )


def _make_chunk(
    ll_spins: int = 0, ll_total_lines: int = 0, ll_win: float = 0.0,
    ls_spins: int = 0, ls_unique=None, ls_win: float = 0.0,
    lr_spins: int = 0, lr_win: float = 0.0,
    jp_spins: int = 0, jp_ids_seen=None, jp_win: float = 0.0,
    fs_chain_spins: int = 0, fs_retriggers: int = 0, fs_max_chain: int = 0, fs_win: float = 0.0,
    dp_spins: int = 0, dp_total_dollars: int = 0, dp_win: float = 0.0,
) -> dict:
    """Build a synthetic chunk_dict with the parser-output key names."""
    return {
        "lock_lines_spins": ll_spins,
        "lock_lines_total_lines": ll_total_lines,
        "lock_lines_win": ll_win,
        "lock_symbols_spins": ls_spins,
        "lock_symbols_unique": ls_unique or [],
        "lock_symbols_win": ls_win,
        "lock_reels_spins": lr_spins,
        "lock_reels_win": lr_win,
        "jackpot_spins": jp_spins,
        "jackpot_ids_seen": jp_ids_seen or [],
        "jackpot_win": jp_win,
        "freespin_chain_spins": fs_chain_spins,
        "freespin_retriggers": fs_retriggers,
        "freespin_max_chain": fs_max_chain,
        "freespin_win": fs_win,
        "dollar_pick_spins": dp_spins,
        "dollar_pick_total_dollars": dp_total_dollars,
        "dollar_pick_win": dp_win,
    }


# ---------------------------------------------------------------------------
# T1: Plugin class-level invariants
# ---------------------------------------------------------------------------

class TestMachineMechanicsClassInvariants:
    """Plugin class-level invariants: FEATURE_ID / SCHEMA_VERSION / REQUIRES / etc."""

    def test_feature_id(self):
        """FEATURE_ID must be 'machine_mechanics'."""
        cls = _import_plugin_class()
        assert cls.FEATURE_ID == "machine_mechanics", (
            f"FEATURE_ID must be 'machine_mechanics', got {cls.FEATURE_ID!r}"
        )

    def test_schema_version_is_2(self):
        """SCHEMA_VERSION must be 2 (C4 adds _detection_source field).

        INJECT-BUG: set SCHEMA_VERSION = 1 in plugin file.
        RED: this assertion fires.
        Revert → GREEN.
        """
        cls = _import_plugin_class()
        assert cls.SCHEMA_VERSION == 2, (
            f"SCHEMA_VERSION must be 2 (C4 upgrade), got {cls.SCHEMA_VERSION}"
        )

    def test_registered_fallback_rules_v1(self):
        """REGISTERED_FALLBACK_RULES[1] must be {"_detection_source": None}.

        INJECT-BUG (Bug B): change key to "_detection_src".
        RED: this assertion fires.
        Revert → GREEN.

        This rule ensures v1 summaries (pre-C4 inline block) render
        _detection_source as None instead of being absent.
        Per feedback_invariant_with_fallback_hides_drift.md.
        """
        cls = _import_plugin_class()
        rules = cls.REGISTERED_FALLBACK_RULES
        assert 1 in rules, (
            f"REGISTERED_FALLBACK_RULES must have key 1 (v1→v2 migration rule). "
            f"Got keys: {list(rules.keys())}"
        )
        assert rules[1] == {"_detection_source": None}, (
            f"REGISTERED_FALLBACK_RULES[1] must be {{'_detection_source': None}}, "
            f"got {rules[1]!r}"
        )

    def test_requires_is_empty_tuple(self):
        """REQUIRES must be ("bonus_chain_dynamics",) — R2 Phase 2 C-3.

        machine_mechanics.emit() reads summary["player_impact"]["bonus_chain_dynamics"]
        for the M275 freespin fallback (fs_chain_spins from bonus_round_count).
        After C-1 removes the F6 inline write, that key is written only by the
        BonusChainDynamics plugin.  REQUIRES ensures topo-sort places
        machine_mechanics after bonus_chain_dynamics regardless of alphabetical order.

        CR-3: test name preserved (test_requires_is_empty_tuple) for grep
        compatibility; assertion updated per 07_decision.md CR-3.
        """
        cls = _import_plugin_class()
        assert cls.REQUIRES == ("bonus_chain_dynamics",), (
            f"REQUIRES must be ('bonus_chain_dynamics',) (R2 C-3 explicit ordering), "
            f"got {cls.REQUIRES!r}"
        )

    def test_rtp_contribution_is_false(self):
        """RTP_CONTRIBUTION must be False (display only; doesn't add to RTP).

        Per brief §2.2: machine_mechanics is a display-only panel.
        It does not contribute to the aggregator parity sum.
        Per feedback_aggregator_parity_invariant.md.
        """
        cls = _import_plugin_class()
        assert cls.RTP_CONTRIBUTION is False, (
            f"RTP_CONTRIBUTION must be False, got {cls.RTP_CONTRIBUTION!r}"
        )

    def test_declared_deps_is_empty_tuple(self):
        """DECLARED_DEPS must be () — plugin reads from ctx, not summary temp-keys."""
        cls = _import_plugin_class()
        assert cls.DECLARED_DEPS == (), (
            f"DECLARED_DEPS must be (), got {cls.DECLARED_DEPS!r}"
        )

    def test_schema_keys_contains_machine_mechanics(self):
        """SCHEMA_KEYS must contain 'machine_mechanics'."""
        cls = _import_plugin_class()
        assert "machine_mechanics" in cls.SCHEMA_KEYS, (
            f"SCHEMA_KEYS must contain 'machine_mechanics', got {cls.SCHEMA_KEYS!r}"
        )


# ---------------------------------------------------------------------------
# T2: Import safety + registration idempotency
# ---------------------------------------------------------------------------

class TestMachineMechanicsImportSafety:
    """Import must be side-effect free; register() must be idempotent."""

    def test_import_clean(self):
        """Importing machine_mechanics must not raise or produce side effects.

        Per feedback_subprocess_import_suicide_and_module_globals.md:
        module import must not trigger I/O or process manipulation.
        """
        import importlib
        try:
            mod = importlib.import_module("fresh_slotlab.analyzer.features.machine_mechanics")
        except ImportError:
            mod = importlib.import_module("analyzer.features.machine_mechanics")
        assert hasattr(mod, "MachineMechanics"), (
            "MachineMechanics class not found after import"
        )

    def test_machine_mechanics_in_all_features_after_import(self):
        """After importing the plugin module, ALL_FEATURES must contain machine_mechanics.

        This is the C4 registration invariant: the plugin registers itself at
        module import time via register(MachineMechanics()).
        """
        try:
            import fresh_slotlab.analyzer.features.machine_mechanics  # noqa: F401
            from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
        except ImportError:
            import analyzer.features.machine_mechanics  # type: ignore[no-redef]  # noqa: F401
            from analyzer.feature_registry import ALL_FEATURES  # type: ignore[no-redef]

        fids = [f.FEATURE_ID for f in ALL_FEATURES]
        assert "machine_mechanics" in fids, (
            f"'machine_mechanics' not in ALL_FEATURES after import. Got: {fids}"
        )

    def test_register_idempotent(self):
        """Calling register() twice must not grow ALL_FEATURES.

        Per feature_registry design: register() is idempotent — same FEATURE_ID
        results in silent no-op on second call.
        """
        try:
            from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES, register
        except ImportError:
            from analyzer.feature_registry import ALL_FEATURES, register  # type: ignore[no-redef]

        cls = _import_plugin_class()
        before_count = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "machine_mechanics")

        register(cls())

        after_count = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "machine_mechanics")
        assert after_count == before_count, (
            f"register() is not idempotent: machine_mechanics count grew from "
            f"{before_count} to {after_count}. Expected no-op on duplicate."
        )


# ---------------------------------------------------------------------------
# T3: extract() correctness
# ---------------------------------------------------------------------------

class TestMachineMechanicsExtract:
    """extract() reads all 6 mechanic sections from chunk_dict."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_extract_reads_lock_lines(self, plugin):
        """extract() reads lock_lines_spins, lock_lines_total_lines, lock_lines_win."""
        chunk = _make_chunk(ll_spins=5, ll_total_lines=15, ll_win=1000.0)
        acc = plugin.extract(None, chunk)
        assert acc["ll_spins"] == 5, f"ll_spins must be 5, got {acc.get('ll_spins')}"
        assert acc["ll_total_lines"] == 15, f"ll_total_lines must be 15, got {acc.get('ll_total_lines')}"
        assert acc["ll_win"] == 1000.0, f"ll_win must be 1000.0, got {acc.get('ll_win')}"

    def test_extract_reads_lock_symbols_with_unique_set(self, plugin):
        """extract() reads lock_symbols_unique as a set."""
        chunk = _make_chunk(ls_spins=3, ls_unique=["7", "bar"], ls_win=500.0)
        acc = plugin.extract(None, chunk)
        assert acc["ls_spins"] == 3
        assert isinstance(acc["ls_unique"], set), (
            f"ls_unique must be a set, got {type(acc['ls_unique'])}"
        )
        assert "7" in acc["ls_unique"] and "bar" in acc["ls_unique"], (
            f"ls_unique must contain '7' and 'bar', got {acc['ls_unique']}"
        )

    def test_extract_reads_lock_reels(self, plugin):
        """extract() reads lock_reels_spins and lock_reels_win."""
        chunk = _make_chunk(lr_spins=2, lr_win=800.0)
        acc = plugin.extract(None, chunk)
        assert acc["lr_spins"] == 2
        assert acc["lr_win"] == 800.0

    def test_extract_reads_jackpot_fields(self, plugin):
        """extract() reads jackpot_spins, jackpot_ids_seen (set), jackpot_win."""
        chunk = _make_chunk(jp_spins=1, jp_ids_seen=["1102", "1103"], jp_win=50000.0)
        acc = plugin.extract(None, chunk)
        assert acc["jp_spins"] == 1
        assert isinstance(acc["jp_ids"], set)
        assert "1102" in acc["jp_ids"] and "1103" in acc["jp_ids"]
        assert acc["jp_win"] == 50000.0

    def test_extract_reads_freespin_fields(self, plugin):
        """extract() reads freespin_chain_spins, retriggers, max_chain, win."""
        chunk = _make_chunk(fs_chain_spins=10, fs_retriggers=2, fs_max_chain=8, fs_win=20000.0)
        acc = plugin.extract(None, chunk)
        assert acc["fs_chain_spins"] == 10
        assert acc["fs_retriggers"] == 2
        assert acc["fs_max_chain"] == 8
        assert acc["fs_win"] == 20000.0

    def test_extract_reads_dollar_pick_fields(self, plugin):
        """extract() reads dollar_pick_spins, total_dollars, win."""
        chunk = _make_chunk(dp_spins=4, dp_total_dollars=12, dp_win=3000.0)
        acc = plugin.extract(None, chunk)
        assert acc["dp_spins"] == 4
        assert acc["dp_total_dollars"] == 12
        assert acc["dp_win"] == 3000.0

    def test_extract_none_chunk_returns_zero_acc(self, plugin):
        """extract() with None chunk_dict returns zero accumulator safely."""
        acc = plugin.extract(None, None)
        assert acc["ll_spins"] == 0
        assert acc["jp_spins"] == 0
        assert acc["fs_chain_spins"] == 0
        assert isinstance(acc["jp_ids"], set)
        assert len(acc["jp_ids"]) == 0

    def test_extract_non_dict_chunk_returns_zero_acc(self, plugin):
        """extract() with non-dict chunk_dict returns zero accumulator safely."""
        acc = plugin.extract(None, "not_a_dict")
        assert acc["ll_spins"] == 0
        assert acc["ls_spins"] == 0
        assert isinstance(acc["ls_unique"], set)

    def test_extract_missing_keys_treated_as_zero(self, plugin):
        """extract() with chunk_dict that lacks mechanic keys returns zeros."""
        # Minimal chunk_dict missing all mechanic fields
        acc = plugin.extract(None, {"ok": True, "spins": 1000})
        assert acc["ll_spins"] == 0
        assert acc["jp_spins"] == 0
        assert acc["dp_spins"] == 0

    def test_extract_accumulates_all_19_fields(self, plugin):
        """extract() returns dict with all 19 required accumulator keys."""
        chunk = _make_chunk(ll_spins=1, ls_spins=2, lr_spins=3, jp_spins=4,
                            fs_chain_spins=5, dp_spins=6)
        acc = plugin.extract(None, chunk)
        required_keys = {
            "ll_spins", "ll_total_lines", "ll_win",
            "ls_spins", "ls_unique", "ls_win",
            "lr_spins", "lr_win",
            "jp_spins", "jp_ids", "jp_win",
            "fs_chain_spins", "fs_retriggers", "fs_max_chain", "fs_win",
            "dp_spins", "dp_total_dollars", "dp_win",
        }
        missing = required_keys - set(acc.keys())
        assert not missing, (
            f"extract() missing required accumulator keys: {missing}"
        )


# ---------------------------------------------------------------------------
# T4: reduce() correctness
# ---------------------------------------------------------------------------

class TestMachineMechanicsReduce:
    """reduce() merges accumulators correctly across chunks."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_reduce_numeric_fields_additive(self, plugin):
        """Numeric fields accumulate additively across chunks."""
        acc1 = {
            "ll_spins": 3, "ll_total_lines": 9, "ll_win": 100.0,
            "ls_spins": 2, "ls_unique": set(), "ls_win": 50.0,
            "lr_spins": 1, "lr_win": 200.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 5, "fs_retriggers": 1, "fs_max_chain": 5, "fs_win": 1000.0,
            "dp_spins": 2, "dp_total_dollars": 6, "dp_win": 300.0,
        }
        acc2 = {
            "ll_spins": 4, "ll_total_lines": 12, "ll_win": 200.0,
            "ls_spins": 3, "ls_unique": set(), "ls_win": 75.0,
            "lr_spins": 2, "lr_win": 100.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 7, "fs_retriggers": 2, "fs_max_chain": 8, "fs_win": 2000.0,
            "dp_spins": 1, "dp_total_dollars": 3, "dp_win": 150.0,
        }
        merged = plugin.reduce(acc1, acc2)
        assert merged["ll_spins"] == 7, f"ll_spins should be 3+4=7, got {merged['ll_spins']}"
        assert merged["fs_chain_spins"] == 12, f"fs_chain_spins should be 5+7=12, got {merged['fs_chain_spins']}"
        assert merged["dp_win"] == 450.0, f"dp_win should be 300+150=450, got {merged['dp_win']}"

    def test_reduce_set_fields_unioned(self, plugin):
        """ls_unique and jp_ids must be unioned across chunks."""
        acc1 = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 1, "ls_unique": {"7", "bar"}, "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": {"1102"}, "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        acc2 = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 1, "ls_unique": {"cherry"}, "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": {"1103", "1104"}, "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        merged = plugin.reduce(acc1, acc2)
        assert "7" in merged["ls_unique"] and "bar" in merged["ls_unique"] and "cherry" in merged["ls_unique"], (
            f"ls_unique must be union: got {merged['ls_unique']}"
        )
        assert {"1102", "1103", "1104"} == merged["jp_ids"], (
            f"jp_ids must be union: got {merged['jp_ids']}"
        )

    def test_reduce_fs_max_chain_takes_max(self, plugin):
        """fs_max_chain must be max across chunks, not sum."""
        acc1 = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 10, "fs_retriggers": 0, "fs_max_chain": 7, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        acc2 = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 5, "fs_retriggers": 0, "fs_max_chain": 10, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        merged = plugin.reduce(acc1, acc2)
        assert merged["fs_max_chain"] == 10, (
            f"fs_max_chain must be max(7, 10) = 10, got {merged['fs_max_chain']}"
        )

    def test_reduce_empty_prev_returns_this(self, plugin):
        """reduce({}, this_acc) returns this_acc (first chunk base case)."""
        this = {
            "ll_spins": 5, "ll_total_lines": 15, "ll_win": 100.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        merged = plugin.reduce({}, this)
        assert merged["ll_spins"] == 5, (
            f"reduce({{}}, this) must return this. Got ll_spins={merged.get('ll_spins')}"
        )

    def test_reduce_empty_this_returns_prev(self, plugin):
        """reduce(prev, {}) returns prev (empty chunk — robustness)."""
        prev = {
            "ll_spins": 3, "ll_total_lines": 9, "ll_win": 100.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        merged = plugin.reduce(prev, {})
        assert merged["ll_spins"] == 3, (
            f"reduce(prev, {{}}) must return prev. Got ll_spins={merged.get('ll_spins')}"
        )


# ---------------------------------------------------------------------------
# T5: emit() correctness — manifest-driven mechanism flags
# ---------------------------------------------------------------------------

class TestMachineMechanicsEmit:
    """emit() builds all 6 sections; machine_spec_manifest drives jackpot + free_spin."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_emit_writes_to_player_impact_machine_mechanics(self, plugin):
        """emit() must write to summary["player_impact"]["machine_mechanics"]."""
        acc = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx())
        assert "machine_mechanics" in summary.get("player_impact", {}), (
            f"emit() must write to summary['player_impact']['machine_mechanics']. "
            f"Got player_impact keys: {list(summary.get('player_impact', {}).keys())}"
        )

    def test_emit_six_sections_present(self, plugin):
        """emit() must produce exactly 6 sections."""
        acc = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx())
        mm = summary["player_impact"]["machine_mechanics"]
        expected_sections = {"lock_lines", "lock_symbols", "lock_reels", "jackpot", "free_spin", "dollar_pick"}
        assert set(mm.keys()) == expected_sections, (
            f"emit() must produce exactly 6 sections. "
            f"Got: {set(mm.keys())} | Expected: {expected_sections}"
        )

    def test_emit_jackpot_applicable_from_manifest(self, plugin):
        """jackpot.applicable must come from machine_spec_manifest, not raw counter.

        INJECT-BUG (Bug A): in machine_mechanics.py, inside the manifest branch,
        change `_jp_applicable = _mflags["jackpot_applicable"]` to
        `_jp_applicable = False`.
        RED: this test fails (jp_applicable=False even though manifest declares True).
        Revert (restore original line) → GREEN.

        This is the critical gap #1 closure test:
        - jp_spins = 0 (no JackpotIds raw field events in this chunk)
        - But manifest declares jackpot SpinType (play='Jackpot')
        - emit() must use the manifest, NOT jp_spins > 0
        """
        acc = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0,  # zero raw count — old code would say jp_applicable=False
            "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {}
        ctx = _make_ctx(jackpot_applicable=True)  # manifest declares jackpot
        plugin.emit(acc, summary, ctx)
        mm = summary["player_impact"]["machine_mechanics"]
        assert mm["jackpot"]["applicable"] is True, (
            f"jackpot.applicable must be True (from manifest), "
            f"even when jp_spins=0. Got: {mm['jackpot']['applicable']!r}. "
            f"This is gap #1 — the OLD inline code used `jp_spins > 0` which "
            f"fails for jackpot PIDs that don't appear in JackpotIds field."
        )

    def test_emit_jackpot_detection_source_populated(self, plugin):
        """jackpot._detection_source must be populated from derive_mechanism_flags."""
        acc = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {}
        ctx = _make_ctx(jackpot_applicable=True)
        plugin.emit(acc, summary, ctx)
        mm = summary["player_impact"]["machine_mechanics"]
        ds = mm["jackpot"]["_detection_source"]
        assert ds is not None, (
            f"jackpot._detection_source must not be None. "
            f"Per feedback_invariant_with_fallback_hides_drift.md: "
            f"_detection_source is an explicit required field, not optional."
        )
        assert isinstance(ds, str) and ds, (
            f"_detection_source must be a non-empty string, got {ds!r}"
        )

    def test_emit_freespin_applicable_from_manifest(self, plugin):
        """free_spin.applicable must come from machine_spec_manifest (gap #2 closure).

        Old inline code used fs_chain_spins > 0 which fails for M275-style
        bonus chains tracked via bonus_chain_dynamics, not CurFreeSpin.
        """
        acc = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0,  # zero raw — old code would say fs_applicable=False
            "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {
            "player_impact": {
                "bonus_chain_dynamics": {
                    "chain_count": 908,
                    "bonus_round_count": 9090,
                    "avg_chain_length": 10.0,
                }
            }
        }
        ctx = _make_ctx(freespin_applicable=True)  # manifest declares freespin
        plugin.emit(acc, summary, ctx)
        mm = summary["player_impact"]["machine_mechanics"]
        assert mm["free_spin"]["applicable"] is True, (
            f"free_spin.applicable must be True (from manifest), "
            f"even when fs_chain_spins=0. Got: {mm['free_spin']['applicable']!r}. "
            f"This is gap #2 — M275-style freespin chains tracked via BCD."
        )

    def test_emit_freespin_detection_source_populated(self, plugin):
        """free_spin._detection_source must be populated from derive_mechanism_flags."""
        acc = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {}
        ctx = _make_ctx(freespin_applicable=True)
        plugin.emit(acc, summary, ctx)
        mm = summary["player_impact"]["machine_mechanics"]
        ds = mm["free_spin"]["_detection_source"]
        assert ds is not None, (
            f"free_spin._detection_source must not be None. Got: {ds!r}"
        )

    def test_emit_lock_lines_applicable_when_spins_positive(self, plugin):
        """lock_lines.applicable is True when ll_spins > 0 (counter-driven, not manifest)."""
        acc = {
            "ll_spins": 5, "ll_total_lines": 10, "ll_win": 200.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx())
        mm = summary["player_impact"]["machine_mechanics"]
        assert mm["lock_lines"]["applicable"] is True, (
            f"lock_lines.applicable must be True when ll_spins=5. "
            f"Got: {mm['lock_lines']['applicable']!r}"
        )

    def test_emit_rtp_contribution_pp_computed_correctly(self, plugin):
        """rtp_contribution_pp = (win / ebet * 100) for sections with win > 0."""
        acc = {
            "ll_spins": 1, "ll_total_lines": 3, "ll_win": 100_000.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {}
        # ebet = 10_000_000; win=100_000 → rtp = 100_000 / 10_000_000 * 100 = 1.0%
        ctx = _make_ctx(effective_bet_for_rtp=10_000_000.0)
        plugin.emit(acc, summary, ctx)
        mm = summary["player_impact"]["machine_mechanics"]
        rtp = mm["lock_lines"]["lock_rtp_contribution_pp"]
        assert abs(rtp - 1.0) < 1e-6, (
            f"lock_lines.rtp_contribution_pp must be 1.0, got {rtp}"
        )

    def test_emit_zero_ebet_no_division_error(self, plugin):
        """emit() with effective_bet_for_rtp=0 must not raise ZeroDivisionError."""
        acc = {
            "ll_spins": 5, "ll_total_lines": 10, "ll_win": 200.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {}
        ctx = _make_ctx(effective_bet_for_rtp=0.0)  # zero denominator
        # Must not raise
        plugin.emit(acc, summary, ctx)
        mm = summary["player_impact"]["machine_mechanics"]
        assert mm["lock_lines"]["lock_rtp_contribution_pp"] == 0.0, (
            f"rtp_contribution_pp must be 0.0 when ebet=0, "
            f"got {mm['lock_lines']['lock_rtp_contribution_pp']}"
        )

    def test_emit_zero_total_spins_no_division_error(self, plugin):
        """emit() with total_spins=0 must not raise ZeroDivisionError."""
        acc = {
            "ll_spins": 5, "ll_total_lines": 10, "ll_win": 200.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {}
        ctx = _make_ctx(total_spins=0)
        plugin.emit(acc, summary, ctx)
        mm = summary["player_impact"]["machine_mechanics"]
        assert mm["lock_lines"]["lock_rate"] == 0.0, (
            f"lock_rate must be 0.0 when total_spins=0, "
            f"got {mm['lock_lines']['lock_rate']}"
        )

    def test_emit_jackpot_schema_keys(self, plugin):
        """jackpot section must have all required schema keys including _detection_source."""
        acc = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {}
        ctx = _make_ctx(jackpot_applicable=True)
        plugin.emit(acc, summary, ctx)
        jp = summary["player_impact"]["machine_mechanics"]["jackpot"]
        required = {
            "applicable", "trigger_spins", "trigger_rate",
            "jackpot_ids", "jackpot_id_count", "total_win",
            "rtp_contribution_pp", "_detection_source",
        }
        missing = required - set(jp.keys())
        assert not missing, (
            f"jackpot section missing required schema keys: {missing}. "
            f"Got: {sorted(jp.keys())}"
        )

    def test_emit_free_spin_schema_keys(self, plugin):
        """free_spin section must have all required schema keys including _detection_source."""
        acc = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {}
        plugin.emit(acc, summary, _make_ctx())
        fs = summary["player_impact"]["machine_mechanics"]["free_spin"]
        required = {
            "applicable", "chain_spins", "chain_rate",
            "retriggers", "max_chain_length", "total_win",
            "rtp_contribution_pp", "_detection_source",
        }
        missing = required - set(fs.keys())
        assert not missing, (
            f"free_spin section missing required schema keys: {missing}. "
            f"Got: {sorted(fs.keys())}"
        )

    def test_emit_all_applicable_false_for_zero_acc(self, plugin):
        """With all-zero accumulator and no-mechanism manifest, all applicable must be False."""
        acc = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {}
        ctx = _make_ctx(jackpot_applicable=False, freespin_applicable=False)
        plugin.emit(acc, summary, ctx)
        mm = summary["player_impact"]["machine_mechanics"]
        for section_name in ["lock_lines", "lock_symbols", "lock_reels", "jackpot", "free_spin", "dollar_pick"]:
            assert mm[section_name]["applicable"] is False, (
                f"{section_name}.applicable must be False for zero accumulator + no-mechanism manifest. "
                f"Got: {mm[section_name]['applicable']!r}"
            )

    def test_inject_bug_manifest_beats_raw_counter(self, plugin):
        """INJECT-BUG gate: manifest declares jackpot but jp_spins=0; must still be True.

        This is the primary correctness invariant for the manifest-driven path.
        If code incorrectly fell back to raw counter (jp_spins > 0), this would fail.
        """
        acc = {
            "ll_spins": 0, "ll_total_lines": 0, "ll_win": 0.0,
            "ls_spins": 0, "ls_unique": set(), "ls_win": 0.0,
            "lr_spins": 0, "lr_win": 0.0,
            "jp_spins": 0, "jp_ids": set(), "jp_win": 0.0,
            "fs_chain_spins": 0, "fs_retriggers": 0, "fs_max_chain": 0, "fs_win": 0.0,
            "dp_spins": 0, "dp_total_dollars": 0, "dp_win": 0.0,
        }
        summary: dict = {}
        # Manifest says jackpot=True; if code uses raw counter it would get False
        ctx = _make_ctx(jackpot_applicable=True)
        plugin.emit(acc, summary, ctx)
        mm = summary["player_impact"]["machine_mechanics"]
        assert mm["jackpot"]["applicable"] is True, (
            "INJECT-BUG DETECTION: jackpot.applicable must be True from manifest "
            "even when jp_spins=0. If False, the code is using raw counter not manifest."
        )
