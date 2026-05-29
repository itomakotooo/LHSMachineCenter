"""Phase C6 — unit + subprocess tests for bonus_chain_dynamics plugin.

Invariants asserted
-------------------
1.  Plugin imports clean — no I/O side-effects at import time.
2.  FEATURE_ID == "bonus_chain_dynamics".
3.  SCHEMA_VERSION == 1 (pure carve; notes added to sibling key, not schema change).
4.  REQUIRES == () (stash pattern; no emit-loop ordering dependency).
5.  DECLARED_DEPS == () (stash key is the delivery mechanism).
6.  RTP_CONTRIBUTION == False (display-only panel).
7.  "bonus_chain_dynamics" in ALL_FEATURES after import.
8.  register() is idempotent — duplicate import does not grow ALL_FEATURES.
9.  extract() is a no-op — always returns {}.
10. reduce() is a no-op — always returns {}.
11. emit() raises RuntimeError when stash key absent.
12. emit() reads stash, overwrites summary["player_impact"]["bonus_chain_dynamics"] (byte-identical carve).
13. emit() removes stash key _bonus_chain_dynamics_data from summary.
14. emit() adds notes to every payout_ids_top20 row with is_trigger_marker field.
15. emit() sets is_trigger_marker=True for pids in scatter_marker_pids.
16. emit() sets is_trigger_marker=False for pids NOT in scatter_marker_pids.
17. emit() sets trigger_target via chain-count majority vote (R1 d2 fix).
18. emit() sets trigger_target_confidence="unique" when exactly 1 feature (R1 d3 fix);
    "data_inferred" when 2+ features and chain count majority; "fallback_no_chain_data"
    when all chain counts are zero.
19. M275 subprocess: applicable=True, chain_count=908, by_feature has NormalCollectionSpin.
20. M275 subprocess: bonus_chain_dynamics in player_impact (not top-level).
21. M275 subprocess: stash key absent from final summary.
22. M14 subprocess: applicable=False.
23. M14 subprocess: no false trigger markers in payout_ids_top20.
24. 9 plugins in ALL_FEATURES after all are imported (base 8 + bonus_chain_dynamics).

Inject-bug recipe A (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug A: change emit() to skip stash read and emit empty bonus_chain_dynamics:
    In bonus_chain_dynamics.py BonusChainDynamics.emit(), change the step 2 block to:
        summary.pop(_STASH_KEY, None)
        player_impact = summary.setdefault("player_impact", {})
        player_impact["bonus_chain_dynamics"] = {}
    RED: test_emit_reads_stash_overwrites_bonus_chain_dynamics fails (applicable missing).
         test_m275_applicable_true fails (subprocess).
    Revert (restore full emit body) -> GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_subprocess_import_suicide_and_module_globals.md
  (register() must be pure list-append; no I/O at import time)
- memory/feedback_no_silent_swallow.md
  (emit() must raise RuntimeError on missing stash)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (is_trigger_marker is an explicit signal; trigger_target_confidence absent for non-markers)
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test required for PIA wiring verification)
- memory/feedback_integration_test_argv.md
  (real subprocess against real cached chunks)
- memory/feedback_no_parallel_panel_impl.md
  (notes shape mirrors payouts_by_spin_type notes shape — C3 sibling)
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_M275_CACHE = _REPO_ROOT / "rawdata" / "M275" / "mode_1"
_M14_CACHE = _REPO_ROOT / "rawdata" / "M14" / "mode_1"


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _import_plugin_class():
    try:
        from fresh_slotlab.analyzer.features.bonus_chain_dynamics import BonusChainDynamics
    except ImportError:
        from analyzer.features.bonus_chain_dynamics import BonusChainDynamics  # type: ignore[no-redef]
    return BonusChainDynamics


# ---------------------------------------------------------------------------
# Subprocess fixtures (module-scoped for speed)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m275_bcd_summary() -> dict:
    """Run M275 mode 1 from cache; return parsed summary."""
    if not _M275_CACHE.exists() or not list(_M275_CACHE.glob("chunk_*.json")):
        pytest.skip(f"M275 mode 1 cached chunks not found at {_M275_CACHE}")

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable, str(_PIA),
            "--machine", "M275",
            "--rtp-mode", "1",
            "--from-cache", str(_M275_CACHE),
            "--output-dir", tmpdir,
            "--bet", "1000",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=300)
        assert result.returncode == 0, (
            f"M275 analyzer exited {result.returncode}.\n"
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        return json.loads(summary_path.read_bytes())


@pytest.fixture(scope="module")
def m14_bcd_summary() -> dict:
    """Run M14 mode 1 from cache; return parsed summary."""
    if not _M14_CACHE.exists() or not list(_M14_CACHE.glob("chunk_*.json")):
        pytest.skip(f"M14 mode 1 cached chunks not found at {_M14_CACHE}")

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable, str(_PIA),
            "--machine", "M14",
            "--rtp-mode", "1",
            "--from-cache", str(_M14_CACHE),
            "--output-dir", tmpdir,
            "--bet", "1000",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=300)
        assert result.returncode == 0, (
            f"M14 analyzer exited {result.returncode}.\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        return json.loads(summary_path.read_bytes())


# ---------------------------------------------------------------------------
# T1: Class-level invariants
# ---------------------------------------------------------------------------

class TestBonusChainDynamicsClassInvariants:
    """Class-level constants must match design contract."""

    def test_feature_id(self):
        """FEATURE_ID must be 'bonus_chain_dynamics'."""
        cls = _import_plugin_class()
        assert cls.FEATURE_ID == "bonus_chain_dynamics", (
            f"FEATURE_ID must be 'bonus_chain_dynamics', got {cls.FEATURE_ID!r}"
        )

    def test_schema_version_is_1(self):
        """SCHEMA_VERSION must be 1 (C6 pure carve; no bonus_chain_dynamics schema change)."""
        cls = _import_plugin_class()
        assert cls.SCHEMA_VERSION == 1, (
            f"SCHEMA_VERSION must be 1 (pure carve), got {cls.SCHEMA_VERSION}"
        )

    def test_requires_is_empty_tuple(self):
        """REQUIRES must be () — stash pattern; no emit-loop ordering dep."""
        cls = _import_plugin_class()
        assert cls.REQUIRES == (), (
            f"REQUIRES must be (), got {cls.REQUIRES!r}"
        )

    def test_declared_deps_is_empty_tuple(self):
        """DECLARED_DEPS must be ("_bonus_chain_dynamics_data",) — R2 Phase 2 C-4.

        BonusChainDynamics.emit() requires _bonus_chain_dynamics_data stash key
        to be present in summary before emit() runs.  DECLARED_DEPS makes this
        a Region 2 pre-flight check (PluginDeclaredDepMissingError → structured
        analyzer_init_error on disk) rather than a soft RuntimeError inside emit().

        CR-3: test name preserved for grep compatibility; assertion updated
        per 07_decision.md CR-3.
        """
        cls = _import_plugin_class()
        assert cls.DECLARED_DEPS == ("_bonus_chain_dynamics_data",), (
            f"DECLARED_DEPS must be ('_bonus_chain_dynamics_data',) (R2 C-4), "
            f"got {cls.DECLARED_DEPS!r}"
        )

    def test_rtp_contribution_is_false(self):
        """RTP_CONTRIBUTION must be False — display-only panel."""
        cls = _import_plugin_class()
        assert cls.RTP_CONTRIBUTION is False, (
            f"RTP_CONTRIBUTION must be False, got {cls.RTP_CONTRIBUTION!r}"
        )

    def test_schema_keys_contains_bonus_chain_dynamics(self):
        """SCHEMA_KEYS must reference player_impact.bonus_chain_dynamics."""
        cls = _import_plugin_class()
        assert any("bonus_chain_dynamics" in k for k in cls.SCHEMA_KEYS), (
            f"SCHEMA_KEYS must reference bonus_chain_dynamics. Got {cls.SCHEMA_KEYS!r}"
        )


# ---------------------------------------------------------------------------
# T2: Import safety + registration idempotency
# ---------------------------------------------------------------------------

class TestBonusChainDynamicsImportSafety:
    """Import must be side-effect free; register() must be idempotent."""

    def test_import_clean(self):
        """Importing the module must not raise or produce side effects."""
        mod = importlib.import_module("fresh_slotlab.analyzer.features.bonus_chain_dynamics")
        assert hasattr(mod, "BonusChainDynamics"), (
            "BonusChainDynamics class not found after import"
        )

    def test_in_all_features_after_import(self):
        """After importing, ALL_FEATURES must contain 'bonus_chain_dynamics'."""
        import fresh_slotlab.analyzer.features.bonus_chain_dynamics  # noqa: F401
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
        fids = [f.FEATURE_ID for f in ALL_FEATURES]
        assert "bonus_chain_dynamics" in fids, (
            f"'bonus_chain_dynamics' not in ALL_FEATURES. Got: {fids}"
        )

    def test_register_idempotent(self):
        """Calling register() twice must not grow ALL_FEATURES."""
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES, register
        cls = _import_plugin_class()
        before = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "bonus_chain_dynamics")
        register(cls())
        after = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "bonus_chain_dynamics")
        assert after == before, (
            f"register() not idempotent: count grew from {before} to {after}"
        )

    def test_nine_plugins_in_all_features(self):
        """After all 9 phase plugins imported, ALL_FEATURES has exactly 9 entries.

        9 plugins: payouts_by_spin_type / reel_marginal_by_spin_type /
        bankruptcy_simulation / multiplier_profile / multiplier_wild /
        machine_mechanics / upstream_feature_breakdown / collect_mechanic /
        bonus_chain_dynamics (C6).
        """
        import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
        import fresh_slotlab.analyzer.features.reel_marginal_by_spin_type  # noqa: F401
        import fresh_slotlab.analyzer.features.bankruptcy_simulation  # noqa: F401
        import fresh_slotlab.analyzer.features.multiplier_profile  # noqa: F401
        import fresh_slotlab.analyzer.features.multiplier_wild  # noqa: F401
        import fresh_slotlab.analyzer.features.machine_mechanics  # noqa: F401
        import fresh_slotlab.analyzer.features.upstream_feature_breakdown  # noqa: F401
        import fresh_slotlab.analyzer.features.collect_mechanic  # noqa: F401
        import fresh_slotlab.analyzer.features.bonus_chain_dynamics  # noqa: F401
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
        count = len(ALL_FEATURES)
        assert count == 9, (
            f"Expected exactly 9 plugins in ALL_FEATURES after all phase imports. "
            f"Got {count}: {[f.FEATURE_ID for f in ALL_FEATURES]}"
        )


# ---------------------------------------------------------------------------
# T3: extract() and reduce() no-ops
# ---------------------------------------------------------------------------

class TestBonusChainDynamicsExtractReduce:
    """extract() and reduce() must be no-ops (stash pattern)."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_extract_returns_empty_dict(self, plugin):
        """extract() must return {} regardless of inputs."""
        assert plugin.extract(None, None) == {}
        assert plugin.extract(None, {"some": "data"}) == {}

    def test_reduce_returns_empty_dict(self, plugin):
        """reduce() must return {} regardless of inputs."""
        assert plugin.reduce({}, {}) == {}
        assert plugin.reduce({"a": 1}, {"b": 2}) == {}


# ---------------------------------------------------------------------------
# T4: emit() correctness
# ---------------------------------------------------------------------------

class TestBonusChainDynamicsEmit:
    """emit() stash-pattern contract and gap #3 trigger marker augmentation."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def _make_ctx(self, scatter_marker_pids: frozenset[str]) -> Any:
        """Build a minimal mock PipelineContext with mechanism_registry."""
        ctx = MagicMock()
        ctx.mechanism_registry.scatter_marker_pids = scatter_marker_pids
        return ctx

    def _make_stash(self, applicable: bool = True, chain_count: int = 908) -> dict:
        """Build minimal _bonus_chain_dynamics_data stash dict (Phase 2b RAW inputs).

        Phase 2b carve: the stash now carries the 9 raw accumulator inputs instead
        of the pre-built bonus_chain_dynamics dict. emit() re-sources these raw
        inputs and BUILDS the dict verbatim. The assertions stay identical; only this
        fixture body changes to match the new stash contract.

        Raw input design:
          - bonus_chain_lengths: list of `chain_count` ints (each = 5) so that
            len(lengths) == chain_count and applicable = (chain_count > 0) is correct.
          - bonus_chain_max_ratios: same length list (each ratio = 1) for _quantiles.
          - bonus_total_rounds_global: chain_count * 5 (each chain has 5 rounds).
          - bonus_retrigger_rounds_global: 0 (no retriggering in the test fixture).
          - bonus_chain_retrigger_events: list of 0s, same length as bonus_chain_lengths.
          - bonus_extra_ratio_counts: empty dict (no extra ratio entries).
          - bonus_depth_ratio_count: empty dict (all depth buckets get cnt=0 → 0 rounds).
          - bonus_depth_ratio_sum: empty dict.
          - all_chains_by_feature: for applicable=True, includes NormalCollectionSpin
            with non-empty lengths so the by_feature filter (if afb["lengths"]) passes.

        R1 Phase 2 d2: includes scatter_feature_chain_counts so emit() can run
        the len-first dispatch without raising RuntimeError. The single-feature
        case ("NormalCollectionSpin" only) hits the 'unique' confidence branch
        which does not need chain_counts — but chain_counts is always present
        here to keep the stash schema complete (stash extension added at pia:4862
        unconditionally for all machines with non-empty scatter_feature_names).
        """
        _lengths = [5] * chain_count  # chain_count chains, each of length 5
        _max_ratios = [1] * chain_count
        _retrigger_events = [0] * chain_count
        _total_rounds = chain_count * 5  # 5 rounds per chain
        if applicable and chain_count > 0:
            _all_chains = {
                "NormalCollectionSpin": {
                    "lengths": list(_lengths),
                    "max_ratios": list(_max_ratios),
                    "total_rounds": _total_rounds,
                    "retrigger_rounds": 0,
                },
            }
        else:
            _all_chains = {}
        return {
            # Phase 2b RAW inputs (plugin OWNS the build):
            "bonus_chain_lengths": _lengths,
            "bonus_chain_max_ratios": _max_ratios,
            "bonus_total_rounds_global": _total_rounds,
            "bonus_retrigger_rounds_global": 0,
            "bonus_chain_retrigger_events": _retrigger_events,
            "bonus_extra_ratio_counts": {},
            "bonus_depth_ratio_count": {},
            "bonus_depth_ratio_sum": {},
            "all_chains_by_feature": _all_chains,
            "scatter_feature_names": ["NormalCollectionSpin"] if applicable else [],
            # R1 d2 stash extension: chain counts per feature for majority-vote
            "scatter_feature_chain_counts": (
                {"NormalCollectionSpin": chain_count} if applicable else {}
            ),
        }

    def test_emit_raises_when_stash_absent(self, plugin):
        """emit() must raise RuntimeError when stash key missing.

        Per memory/feedback_no_silent_swallow.md: never silently skip.
        """
        with pytest.raises(RuntimeError, match="_bonus_chain_dynamics_data"):
            plugin.emit({}, {}, self._make_ctx(frozenset()))

    def test_emit_reads_stash_overwrites_bonus_chain_dynamics(self, plugin):
        """emit() must BUILD + write summary['player_impact']['bonus_chain_dynamics'] from raw stash.

        Phase 2b carve: the plugin now OWNS the dict build (moved verbatim from PIA).
        The stash carries RAW inputs; emit() re-sources them and builds the dict.
        Assertions are unchanged: applicable=True (chain_count=908 > 0), chain_count=908.

        INJECT-BUG (Bug A): change emit() to write empty dict to bonus_chain_dynamics.
        RED: applicable missing/wrong.
        Revert -> GREEN.
        """
        stash = self._make_stash()
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                "payout_ids_top20": [],
                # bonus_chain_dynamics is NOT pre-populated — plugin builds it from raw stash
            },
        }
        plugin.emit({}, summary, self._make_ctx(frozenset()))

        bcd = summary["player_impact"]["bonus_chain_dynamics"]
        assert bcd["applicable"] is True, (
            f"applicable must be True after carve. Got: {bcd.get('applicable')!r}"
        )
        assert bcd["chain_count"] == 908, (
            f"chain_count must be 908. Got: {bcd.get('chain_count')!r}"
        )

    def test_emit_removes_stash_key(self, plugin):
        """emit() must remove _bonus_chain_dynamics_data from summary."""
        stash = self._make_stash()
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                "payout_ids_top20": [],
            },
        }
        plugin.emit({}, summary, self._make_ctx(frozenset()))
        assert "_bonus_chain_dynamics_data" not in summary, (
            "emit() must remove stash key '_bonus_chain_dynamics_data'."
        )

    def test_emit_adds_notes_to_all_pid_rows(self, plugin):
        """emit() must add 'notes' block to every payout_ids_top20 row."""
        stash = self._make_stash()
        pid_rows = [
            {"payout_id": "1", "hit_count": 100, "total_win": 500},
            {"payout_id": "4", "hit_count": 50, "total_win": 200},
            {"payout_id": "666", "hit_count": 829, "total_win": 0},
        ]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                "payout_ids_top20": pid_rows,
            },
        }
        plugin.emit({}, summary, self._make_ctx(frozenset({"666"})))

        for row in summary["player_impact"]["payout_ids_top20"]:
            assert "notes" in row, (
                f"Row for pid {row.get('payout_id')!r} is missing 'notes'. "
                f"All rows must have notes block after emit()."
            )

    def test_emit_trigger_marker_true_for_scatter_pid(self, plugin):
        """is_trigger_marker must be True for pid in scatter_marker_pids."""
        stash = self._make_stash()
        pid_rows = [{"payout_id": "666", "hit_count": 829, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                "payout_ids_top20": pid_rows,
            },
        }
        plugin.emit({}, summary, self._make_ctx(frozenset({"666"})))

        row_666 = summary["player_impact"]["payout_ids_top20"][0]
        assert row_666["notes"]["is_trigger_marker"] is True, (
            f"pid 666 (scatter marker) must have is_trigger_marker=True. "
            f"Got: {row_666['notes'].get('is_trigger_marker')!r}"
        )

    def test_emit_trigger_marker_false_for_non_scatter_pid(self, plugin):
        """is_trigger_marker must be False for pid NOT in scatter_marker_pids."""
        stash = self._make_stash()
        pid_rows = [{"payout_id": "1", "hit_count": 100, "total_win": 500}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                "payout_ids_top20": pid_rows,
            },
        }
        plugin.emit({}, summary, self._make_ctx(frozenset({"666"})))

        row_1 = summary["player_impact"]["payout_ids_top20"][0]
        assert row_1["notes"]["is_trigger_marker"] is False, (
            f"pid 1 (regular pid) must have is_trigger_marker=False. "
            f"Got: {row_1['notes'].get('is_trigger_marker')!r}"
        )

    def test_emit_trigger_target_from_scatter_feature_names(self, plugin):
        """trigger_target must use chain-count majority vote when 2+ features present.

        R1 Phase 2 d2 correctness fix: AFeature (100 chains) wins over ZFeature
        (1 chain) by majority vote — not alphabetical order.
        scatter_feature_names sorted alphabetically (["AFeature", "ZFeature"]) per
        PIA stash construction which uses sorted() — matches real production behavior.

        INJECT-BUG (d2 regression): revert to alphabetical-first sort in plugin →
        trigger_target becomes "AFeature" for the wrong reason (alphabetical, not
        chain count). With chain_counts present, this test only catches the case where
        majority-vote correctly picks "AFeature" by count; inject-bug must use a case
        where alphabetical != majority (see test_c6_gap_3_pid_666_trigger_marker.py
        for the real M275 NCS vs NewFreespin case where they differ).
        """
        # Phase 2b: stash carries RAW inputs; plugin builds the bcd dict.
        # 100 chains for AFeature, 1 chain for ZFeature → AFeature wins majority vote.
        # all_chains_by_feature must have non-empty "lengths" for by_feature filter.
        stash = {
            "bonus_chain_lengths": [5] * 101,   # 101 total chains (AFeature:100 + ZFeature:1)
            "bonus_chain_max_ratios": [1] * 101,
            "bonus_total_rounds_global": 101 * 5,
            "bonus_retrigger_rounds_global": 0,
            "bonus_chain_retrigger_events": [0] * 101,
            "bonus_extra_ratio_counts": {},
            "bonus_depth_ratio_count": {},
            "bonus_depth_ratio_sum": {},
            "all_chains_by_feature": {
                "AFeature": {"lengths": [5] * 100, "max_ratios": [1] * 100, "total_rounds": 500, "retrigger_rounds": 0},
                "ZFeature": {"lengths": [5], "max_ratios": [1], "total_rounds": 5, "retrigger_rounds": 0},
            },
            # sorted() alphabetically — matches PIA stash construction behavior
            "scatter_feature_names": ["AFeature", "ZFeature"],
            # R1 d2: chain_counts required when len >= 2; AFeature wins by majority
            "scatter_feature_chain_counts": {"AFeature": 100, "ZFeature": 1},
        }
        pid_rows = [{"payout_id": "666", "hit_count": 100, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                "payout_ids_top20": pid_rows,
            },
        }
        plugin.emit({}, summary, self._make_ctx(frozenset({"666"})))

        row_666 = summary["player_impact"]["payout_ids_top20"][0]
        # AFeature wins by chain count (100 > 1), confidence = "data_inferred"
        assert row_666["notes"]["trigger_target"] == "AFeature", (
            f"trigger_target must be 'AFeature' (chain-count majority: 100 > 1). "
            f"Got: {row_666['notes'].get('trigger_target')!r}"
        )
        assert row_666["notes"]["trigger_target_confidence"] == "data_inferred", (
            f"trigger_target_confidence must be 'data_inferred' for 2-feature majority-vote. "
            f"Got: {row_666['notes'].get('trigger_target_confidence')!r}"
        )

    def test_emit_trigger_target_confidence_unique_for_single_feature(self, plugin):
        """trigger_target_confidence must be 'unique' when exactly 1 scatter feature.

        R1 Phase 2 d3 fix: len-first dispatch sets confidence="unique" for single-
        feature machines (deterministic — no chain_counts needed). _make_stash()
        produces a 1-element scatter_feature_names list, hitting this branch.

        INJECT-BUG (d3 regression): remove the len==1 branch from emit() → single-
        feature case falls into the 2+ branch → hits RuntimeError (missing
        scatter_feature_chain_counts with unsorted name → wrong path) OR emits
        "data_inferred" instead of "unique". Test fails. Restore → GREEN.
        """
        stash = self._make_stash()  # 1 feature: ["NormalCollectionSpin"]
        pid_rows = [{"payout_id": "666", "hit_count": 829, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                "payout_ids_top20": pid_rows,
            },
        }
        plugin.emit({}, summary, self._make_ctx(frozenset({"666"})))

        row_666 = summary["player_impact"]["payout_ids_top20"][0]
        # Single feature → "unique" confidence (d3 fix)
        assert row_666["notes"]["trigger_target_confidence"] == "unique", (
            f"trigger_target_confidence must be 'unique' for single-feature stash. "
            f"Got: {row_666['notes'].get('trigger_target_confidence')!r}"
        )
        assert row_666["notes"]["trigger_target"] == "NormalCollectionSpin", (
            f"trigger_target must be 'NormalCollectionSpin' (only feature). "
            f"Got: {row_666['notes'].get('trigger_target')!r}"
        )

    def test_emit_non_trigger_rows_omit_trigger_target_confidence(self, plugin):
        """Non-trigger rows must NOT have trigger_target_confidence (explicit absence).

        Per memory/feedback_invariant_with_fallback_hides_drift.md: omission is explicit.
        """
        stash = self._make_stash()
        pid_rows = [{"payout_id": "1", "hit_count": 100, "total_win": 500}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                "payout_ids_top20": pid_rows,
            },
        }
        plugin.emit({}, summary, self._make_ctx(frozenset({"666"})))

        row_1 = summary["player_impact"]["payout_ids_top20"][0]
        assert "trigger_target_confidence" not in row_1["notes"], (
            f"trigger_target_confidence must be absent for non-trigger pids. "
            f"Got keys: {list(row_1['notes'].keys())}"
        )

    def test_emit_no_scatter_markers_produces_no_trigger_markers(self, plugin):
        """When scatter_marker_pids is empty, all rows get is_trigger_marker=False."""
        # Phase 2b: stash carries RAW inputs; applicable=False → bonus_chain_lengths=[].
        stash = {
            "bonus_chain_lengths": [],
            "bonus_chain_max_ratios": [],
            "bonus_total_rounds_global": 0,
            "bonus_retrigger_rounds_global": 0,
            "bonus_chain_retrigger_events": [],
            "bonus_extra_ratio_counts": {},
            "bonus_depth_ratio_count": {},
            "bonus_depth_ratio_sum": {},
            "all_chains_by_feature": {},
            "scatter_feature_names": [],
        }
        pid_rows = [
            {"payout_id": "1", "hit_count": 100, "total_win": 500},
            {"payout_id": "2", "hit_count": 50, "total_win": 200},
        ]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                "payout_ids_top20": pid_rows,
            },
        }
        plugin.emit({}, summary, self._make_ctx(frozenset()))  # empty scatter_marker_pids

        for row in summary["player_impact"]["payout_ids_top20"]:
            assert row["notes"]["is_trigger_marker"] is False, (
                f"With no scatter markers, pid {row.get('payout_id')!r} must have "
                f"is_trigger_marker=False. Got: {row['notes'].get('is_trigger_marker')!r}"
            )


# ---------------------------------------------------------------------------
# T5: M275 subprocess — applicable=True + chain_count=908
# ---------------------------------------------------------------------------

class TestM275BonusChainDynamics:
    """M275 bonus_chain_dynamics must be in player_impact, applicable=True."""

    def test_no_feature_errors(self, m275_bcd_summary):
        """feature_errors must be absent or empty for M275."""
        fe = m275_bcd_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"

    def test_bonus_chain_dynamics_in_player_impact(self, m275_bcd_summary):
        """bonus_chain_dynamics must be under player_impact (not top-level).

        This is the schema location contract for F6 block.
        """
        pi = m275_bcd_summary.get("player_impact", {})
        assert "bonus_chain_dynamics" in pi, (
            f"bonus_chain_dynamics must be under player_impact. "
            f"player_impact keys: {[k for k in pi if not k.startswith('_')]}"
        )

    def test_m275_applicable_true(self, m275_bcd_summary):
        """M275 bonus_chain_dynamics.applicable must be True.

        INJECT-BUG (Bug A): emit() writes empty dict.
        RED: applicable missing/False.
        Revert -> GREEN.
        """
        bcd = m275_bcd_summary["player_impact"]["bonus_chain_dynamics"]
        assert bcd["applicable"] is True, (
            f"bonus_chain_dynamics.applicable must be True for M275. "
            f"Got: {bcd.get('applicable')!r}"
        )

    def test_m275_chain_count(self, m275_bcd_summary):
        """M275 chain_count must be >= 1 (real chain data expected)."""
        bcd = m275_bcd_summary["player_impact"]["bonus_chain_dynamics"]
        chain_count = bcd.get("chain_count", 0)
        assert chain_count >= 1, (
            f"chain_count must be >= 1 for M275 (BCM machine). Got: {chain_count}"
        )

    def test_m275_by_feature_has_expected_features(self, m275_bcd_summary):
        """by_feature must contain M275 BCM features: NormalCollectionSpin + NewFreespin.

        M275 has two feature streams: NormalCollectionSpin (BCM) and NewFreespin (bonus).
        Both appear in all_chains_by_feature with non-empty lengths.
        """
        bcd = m275_bcd_summary["player_impact"]["bonus_chain_dynamics"]
        by_feature = bcd.get("by_feature", {})
        # At minimum, NormalCollectionSpin must be present for M275 BCM machine
        assert len(by_feature) >= 1, (
            f"by_feature must have at least 1 entry for M275. Got keys: {list(by_feature.keys())}"
        )
        assert "NormalCollectionSpin" in by_feature or "NewFreespin" in by_feature, (
            f"by_feature must contain at least one of NormalCollectionSpin/NewFreespin. "
            f"Got keys: {list(by_feature.keys())}"
        )

    def test_m275_no_stash_key_in_final_summary(self, m275_bcd_summary):
        """Stash key _bonus_chain_dynamics_data must not appear in final summary."""
        assert "_bonus_chain_dynamics_data" not in m275_bcd_summary, (
            "Stash key '_bonus_chain_dynamics_data' leaked into final summary."
        )

    def test_m275_no_underscore_prefix_keys_at_top_level(self, m275_bcd_summary):
        """No _ prefix keys must appear at top level after cleanup loop."""
        stash_keys = [k for k in m275_bcd_summary if k.startswith("_")]
        assert not stash_keys, (
            f"Unexpected _-prefixed stash keys at top-level: {stash_keys}"
        )


# ---------------------------------------------------------------------------
# T6: M14 subprocess — applicable=False, no false trigger markers
# ---------------------------------------------------------------------------

class TestM14BonusChainDynamics:
    """M14 bonus_chain_dynamics must be applicable=False; no trigger markers."""

    def test_no_feature_errors(self, m14_bcd_summary):
        """feature_errors must be absent or empty for M14."""
        fe = m14_bcd_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"

    def test_bonus_chain_dynamics_in_player_impact(self, m14_bcd_summary):
        """bonus_chain_dynamics must be under player_impact for M14 too."""
        pi = m14_bcd_summary.get("player_impact", {})
        assert "bonus_chain_dynamics" in pi, (
            "bonus_chain_dynamics must be under player_impact even for M14."
        )

    def test_m14_applicable_false(self, m14_bcd_summary):
        """M14 bonus_chain_dynamics.applicable must be False (no BCM mechanic)."""
        bcd = m14_bcd_summary["player_impact"]["bonus_chain_dynamics"]
        assert bcd["applicable"] is False, (
            f"bonus_chain_dynamics.applicable must be False for M14. "
            f"Got: {bcd.get('applicable')!r}"
        )

    def test_m14_no_trigger_markers_in_payout_ids_top20(self, m14_bcd_summary):
        """M14 payout_ids_top20 must have zero rows with is_trigger_marker=True.

        M14 is a vanilla machine with no scatter triggers.
        """
        pi = m14_bcd_summary.get("player_impact", {})
        rows = pi.get("payout_ids_top20") or []
        trigger_count = sum(
            1 for row in rows
            if row.get("notes", {}).get("is_trigger_marker") is True
        )
        assert trigger_count == 0, (
            f"M14 must have 0 trigger markers. Found {trigger_count} rows with "
            f"is_trigger_marker=True. First offending pids: "
            f"{[r.get('payout_id') for r in rows if r.get('notes', {}).get('is_trigger_marker')]}"
        )
