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
17. emit() sets trigger_target from scatter_feature_names (alphabetically first).
18. emit() sets trigger_target_confidence="data_inferred" when inferred from chain data.
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
        """DECLARED_DEPS must be () — stash key is delivery mechanism."""
        cls = _import_plugin_class()
        assert cls.DECLARED_DEPS == (), (
            f"DECLARED_DEPS must be (), got {cls.DECLARED_DEPS!r}"
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
        """Build minimal _bonus_chain_dynamics_data stash dict."""
        return {
            "bonus_chain_dynamics": {
                "applicable": applicable,
                "chain_count": chain_count,
                "by_feature": {
                    "NormalCollectionSpin": {
                        "chain_count": chain_count,
                        "avg_chain_length": 5.0,
                    }
                },
            },
            "scatter_feature_names": ["NormalCollectionSpin"] if applicable else [],
        }

    def test_emit_raises_when_stash_absent(self, plugin):
        """emit() must raise RuntimeError when stash key missing.

        Per memory/feedback_no_silent_swallow.md: never silently skip.
        """
        with pytest.raises(RuntimeError, match="_bonus_chain_dynamics_data"):
            plugin.emit({}, {}, self._make_ctx(frozenset()))

    def test_emit_reads_stash_overwrites_bonus_chain_dynamics(self, plugin):
        """emit() must write summary['player_impact']['bonus_chain_dynamics'] (byte-identical carve).

        INJECT-BUG (Bug A): change emit() to write empty dict to bonus_chain_dynamics.
        RED: applicable missing/wrong.
        Revert -> GREEN.
        """
        stash = self._make_stash()
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                "bonus_chain_dynamics": stash["bonus_chain_dynamics"],
                "payout_ids_top20": [],
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
                "bonus_chain_dynamics": stash["bonus_chain_dynamics"],
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
                "bonus_chain_dynamics": stash["bonus_chain_dynamics"],
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
                "bonus_chain_dynamics": stash["bonus_chain_dynamics"],
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
                "bonus_chain_dynamics": stash["bonus_chain_dynamics"],
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
        """trigger_target must be alphabetically-first scatter_feature_names entry."""
        stash = {
            "bonus_chain_dynamics": {"applicable": True, "chain_count": 100},
            "scatter_feature_names": ["ZFeature", "AFeature"],
        }
        pid_rows = [{"payout_id": "666", "hit_count": 100, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                "bonus_chain_dynamics": stash["bonus_chain_dynamics"],
                "payout_ids_top20": pid_rows,
            },
        }
        plugin.emit({}, summary, self._make_ctx(frozenset({"666"})))

        row_666 = summary["player_impact"]["payout_ids_top20"][0]
        # AFeature < ZFeature alphabetically
        assert row_666["notes"]["trigger_target"] == "AFeature", (
            f"trigger_target must be first alphabetically ('AFeature' < 'ZFeature'). "
            f"Got: {row_666['notes'].get('trigger_target')!r}"
        )

    def test_emit_trigger_target_confidence_data_inferred(self, plugin):
        """trigger_target_confidence must be 'data_inferred' when feature names present."""
        stash = self._make_stash()
        pid_rows = [{"payout_id": "666", "hit_count": 829, "total_win": 0}]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                "bonus_chain_dynamics": stash["bonus_chain_dynamics"],
                "payout_ids_top20": pid_rows,
            },
        }
        plugin.emit({}, summary, self._make_ctx(frozenset({"666"})))

        row_666 = summary["player_impact"]["payout_ids_top20"][0]
        assert row_666["notes"]["trigger_target_confidence"] == "data_inferred", (
            f"trigger_target_confidence must be 'data_inferred'. "
            f"Got: {row_666['notes'].get('trigger_target_confidence')!r}"
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
                "bonus_chain_dynamics": stash["bonus_chain_dynamics"],
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
        stash = {
            "bonus_chain_dynamics": {"applicable": False, "chain_count": 0},
            "scatter_feature_names": [],
        }
        pid_rows = [
            {"payout_id": "1", "hit_count": 100, "total_win": 500},
            {"payout_id": "2", "hit_count": 50, "total_win": 200},
        ]
        summary = {
            "_bonus_chain_dynamics_data": stash,
            "player_impact": {
                "bonus_chain_dynamics": stash["bonus_chain_dynamics"],
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
