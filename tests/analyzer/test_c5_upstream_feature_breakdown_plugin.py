"""Phase C5 — unit + subprocess tests for upstream_feature_breakdown plugin.

Invariants asserted
-------------------
1. Plugin imports clean — no I/O side-effects at import time.
2. FEATURE_ID == "upstream_feature_breakdown".
3. SCHEMA_VERSION == 1 (C5 initial; byte-identical to pre-C5 inline block).
4. REQUIRES == () (stash pattern; no emit-loop ordering dependency).
5. REGISTERED_FALLBACK_RULES == {} (no version migration needed — brand-new plugin).
6. RTP_CONTRIBUTION == False (display-only panel).
7. "upstream_feature_breakdown" present in ALL_FEATURES after import.
8. register() is idempotent — duplicate import does not grow ALL_FEATURES.
9. extract() is a no-op — always returns {}.
10. reduce() is a no-op — always returns {}.
11. emit() raises RuntimeError when stash key absent (no silent swallow).
12. emit() reads stash key, removes it, writes summary["player_impact"]["upstream_feature_breakdown"].
13. emit() leaves no _upstream_feature_breakdown_data key in summary after completion.
14. M275 subprocess: applicable=True with exactly 4 feature entries.
15. M275 subprocess: feature names include NormalCollectionSpin, NewFreespin [via NewFreespin],
    NewFreespin [via BCM cycle], BuffCollectionMap.
16. M14 subprocess: applicable=False (only "Normal" feature; single-feature machine).
17. No feature_errors in M275 or M14 subprocess output.

Phase 3 carve note
------------------
The plugin now OWNS the ~400-line row-build (moved VERBATIM out of PIA per
session_artifacts/_impl/phase_extract_3_upstream_feature/brief.md §2). The stash
carries RAW inputs (upstream_feature_tally, the resolved feature→SpinType maps,
the transition/bucket/chain accumulators, etc.); emit() re-sources them and BUILDS
the {applicable, source, features} dict. The assertions below are unchanged; only
the _make_stash_data() fixture body changed to feed the new raw-input contract.
A full deep-diff byte-identity regression (REAL subprocess vs frozen goldens) lives
in test_3_byte_identical_upstream_feature_carve.py.

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug A — emit() writes an empty/forced breakdown instead of building from the stash:
    In upstream_feature_breakdown.py UpstreamFeatureBreakdown.emit(), replace the
    final write block:
        player_impact = summary.setdefault("player_impact", {})
        player_impact["upstream_feature_breakdown"] = {
            "applicable": upstream_feature_applicable,
            "source": "analysisResult.FeatureWin",
            "features": upstream_feature_rows,
        }
    with (forcing the wrong value):
        summary.pop(_STASH_KEY, None)  # already popped above; harmless
        player_impact = summary.setdefault("player_impact", {})
        player_impact["upstream_feature_breakdown"] = {"applicable": False, "features": []}
    RED: test_emit_reads_stash_and_writes_player_impact fails (applicable/features wrong).
         test_m275_applicable_true fails (subprocess level).
    Revert (restore the build-from-stash write) -> GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_subprocess_import_suicide_and_module_globals.md
  (register() must be pure list-append; no I/O at import time)
- memory/feedback_no_silent_swallow.md
  (emit() must raise RuntimeError on missing stash, not silently skip)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (applicable=False is explicit signal "single-feature machine", not a catch-all)
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test required for PIA wiring verification)
- memory/feedback_integration_test_argv.md
  (real subprocess against real cached chunks)
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

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
        from fresh_slotlab.analyzer.features.upstream_feature_breakdown import UpstreamFeatureBreakdown
    except ImportError:
        from analyzer.features.upstream_feature_breakdown import UpstreamFeatureBreakdown  # type: ignore[no-redef]
    return UpstreamFeatureBreakdown


# ---------------------------------------------------------------------------
# Subprocess fixtures (module-scoped — run once per file)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m275_ufb_summary() -> dict:
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
        assert summary_path.exists(), f"summary.json not written. STDOUT: {result.stdout[:500]}"
        return json.loads(summary_path.read_bytes())


@pytest.fixture(scope="module")
def m14_ufb_summary() -> dict:
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

class TestUpstreamFeatureBreakdownClassInvariants:
    """Class-level constants must match design contract."""

    def test_feature_id(self):
        """FEATURE_ID must be 'upstream_feature_breakdown'."""
        cls = _import_plugin_class()
        assert cls.FEATURE_ID == "upstream_feature_breakdown", (
            f"FEATURE_ID must be 'upstream_feature_breakdown', got {cls.FEATURE_ID!r}"
        )

    def test_schema_version_is_1(self):
        """SCHEMA_VERSION must be 1 (C5 initial; byte-identical to pre-C5 inline block)."""
        cls = _import_plugin_class()
        assert cls.SCHEMA_VERSION == 1, (
            f"SCHEMA_VERSION must be 1, got {cls.SCHEMA_VERSION}"
        )

    def test_requires_is_empty_tuple(self):
        """REQUIRES must be () — stash pattern; no emit-loop ordering dep."""
        cls = _import_plugin_class()
        assert cls.REQUIRES == (), (
            f"REQUIRES must be (), got {cls.REQUIRES!r}"
        )

    def test_registered_fallback_rules_is_empty(self):
        """REGISTERED_FALLBACK_RULES must be {} — brand-new plugin, no version migration."""
        cls = _import_plugin_class()
        rules = cls.REGISTERED_FALLBACK_RULES
        assert rules == {}, (
            f"REGISTERED_FALLBACK_RULES must be {{}}, got {rules!r}"
        )

    def test_rtp_contribution_is_false(self):
        """RTP_CONTRIBUTION must be False — display-only panel."""
        cls = _import_plugin_class()
        assert cls.RTP_CONTRIBUTION is False, (
            f"RTP_CONTRIBUTION must be False, got {cls.RTP_CONTRIBUTION!r}"
        )

    def test_schema_keys_contains_upstream_feature_breakdown(self):
        """SCHEMA_KEYS must contain 'upstream_feature_breakdown'."""
        cls = _import_plugin_class()
        assert "upstream_feature_breakdown" in cls.SCHEMA_KEYS, (
            f"SCHEMA_KEYS must contain 'upstream_feature_breakdown', got {cls.SCHEMA_KEYS!r}"
        )

    def test_declared_deps_is_empty_tuple(self):
        """DECLARED_DEPS must be ()."""
        cls = _import_plugin_class()
        assert cls.DECLARED_DEPS == (), (
            f"DECLARED_DEPS must be (), got {cls.DECLARED_DEPS!r}"
        )


# ---------------------------------------------------------------------------
# T2: Import safety + registration idempotency
# ---------------------------------------------------------------------------

class TestUpstreamFeatureBreakdownImportSafety:
    """Import must be side-effect free; register() must be idempotent."""

    def test_import_clean(self):
        """Importing the module must not raise or produce side effects.

        Per feedback_subprocess_import_suicide_and_module_globals.md.
        """
        mod = importlib.import_module("fresh_slotlab.analyzer.features.upstream_feature_breakdown")
        assert hasattr(mod, "UpstreamFeatureBreakdown"), (
            "UpstreamFeatureBreakdown class not found after import"
        )

    def test_in_all_features_after_import(self):
        """After importing, ALL_FEATURES must contain 'upstream_feature_breakdown'."""
        import fresh_slotlab.analyzer.features.upstream_feature_breakdown  # noqa: F401
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
        fids = [f.FEATURE_ID for f in ALL_FEATURES]
        assert "upstream_feature_breakdown" in fids, (
            f"'upstream_feature_breakdown' not in ALL_FEATURES. Got: {fids}"
        )

    def test_register_idempotent(self):
        """Calling register() twice must not grow ALL_FEATURES."""
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES, register
        cls = _import_plugin_class()
        before = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "upstream_feature_breakdown")
        register(cls())
        after = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "upstream_feature_breakdown")
        assert after == before, (
            f"register() not idempotent: count grew from {before} to {after}"
        )


# ---------------------------------------------------------------------------
# T3: extract() and reduce() no-ops
# ---------------------------------------------------------------------------

class TestUpstreamFeatureBreakdownExtractReduce:
    """extract() and reduce() must be no-ops (stash pattern)."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def test_extract_returns_empty_dict(self, plugin):
        """extract() must return {} regardless of inputs."""
        assert plugin.extract(None, None) == {}, "extract(None, None) must be {}"
        assert plugin.extract(None, {"some": "data"}) == {}, "extract with data must be {}"
        assert plugin.extract(None, 12345) == {}, "extract with int must be {}"

    def test_reduce_returns_empty_dict(self, plugin):
        """reduce() must return {} regardless of inputs."""
        assert plugin.reduce({}, {}) == {}, "reduce({}, {}) must be {}"
        assert plugin.reduce({"a": 1}, {"b": 2}) == {}, "reduce with data must be {}"


# ---------------------------------------------------------------------------
# T4: emit() correctness
# ---------------------------------------------------------------------------

class TestUpstreamFeatureBreakdownEmit:
    """emit() stash-pattern contract enforcement."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def _make_stash_data(self, applicable=True, features=None):
        """Build a minimal _upstream_feature_breakdown_data stash (Phase 3 RAW inputs).

        Phase 3 carve: the stash now carries the RAW row-build inputs instead of
        the pre-built {applicable, source, features} dict. emit() re-sources these
        raw inputs and BUILDS the dict verbatim (the ~400-line row-build moved out
        of PIA). The assertions in this suite stay identical; only this fixture body
        changes to match the new stash contract.

        Raw input design (drives the assertions byte-for-byte):
          - applicable=True  → upstream_feature_tally has a single bonus-named
            feature "NormalCollectionSpin" (non-"Normal" → has_bonus_named_feature
            → applicable=True), one pid with win>0 + times>0 (NOT trigger_only →
            single aggregate row). feature_to_spin_type={} so resolved_spin_type is
            None → no bucket/transition lookups needed; one clean aggregate row
            named "NormalCollectionSpin" is emitted (len(features)==1).
          - applicable=False → single "Normal" feature only (has_multiple_features
            False + has_bonus_named_feature False → applicable=False).
          - source is the constant "analysisResult.FeatureWin" baked into the build.
          - the ``features`` kwarg (legacy passthrough param) is accepted for
            signature compat but ignored — the plugin now BUILDS features from the
            tally (it no longer accepts a pre-built features list).

        All transition/bucket/chain accumulators are empty (resolved_spin_type is
        None for these synthetic features, so the build never indexes them). The
        full raw-input key set is present so the plugin's fail-loud guard passes.
        """
        if applicable:
            _tally = {
                "NormalCollectionSpin": {
                    "1": {"win": 500.0, "times": 100},
                },
            }
        else:
            _tally = {
                "Normal": {
                    "1": {"win": 500.0, "times": 100},
                },
            }
        return {
            # Resolved helper RESULTS (empty → resolved_spin_type None for both).
            "feature_to_spin_type": {},
            "spin_type_to_feature": {},
            "ambiguous_mapped": set(),
            "bcm_bonus_feature": None,
            "bcm_bonus_source": "none",
            # The per-feature per-pid {win, times} tally the row headers read.
            "upstream_feature_tally": _tally,
            # SpinType transition table (empty — no successor/predecessor edges).
            "spin_type_next_counts": {},
            # Chain post-processing accumulators (empty — no per-path sub_streams).
            "chain_chunk_summaries": {},
            "chain_bucket_spins": {},
            "chain_bucket_bet": {},
            "chain_bucket_win": {},
            # Round-level multiplier-bucket accumulators + settlement-ST fallbacks.
            "spin_type_bucket_spins": {},
            "spin_type_bucket_bet": {},
            "spin_type_bucket_win": {},
            "session_bucket_spins_by_settlement_st": {},
            "session_bucket_bet_by_settlement_st": {},
            "session_bucket_win_by_settlement_st": {},
            # Wild-nudge tagging inputs.
            "spin_type_spins": {},
            "spin_type_nudge_round_count": {},
            # Scalars.
            "total_spins": 1000,
            "effective_bet_for_rtp": 1000.0,
            "upstream_total_win": 500.0,
        }

    def test_emit_raises_when_stash_absent(self, plugin):
        """emit() must raise RuntimeError when stash key missing.

        Per feedback_no_silent_swallow.md: never silently skip.
        """
        summary: dict = {}  # no _upstream_feature_breakdown_data key
        with pytest.raises(RuntimeError, match="_upstream_feature_breakdown_data"):
            plugin.emit({}, summary, None)

    def test_emit_reads_stash_and_writes_player_impact(self, plugin):
        """emit() reads stash, removes it, writes player_impact key.

        INJECT-BUG (Bug A): change emit() to write empty features list instead
        of reading from stash. RED: applicable/features values are wrong.
        Revert -> GREEN.
        """
        feature_data = self._make_stash_data(
            applicable=True,
            features=[{"feature_name": "NormalCollectionSpin", "rtp_contribution_pp": 44.8}],
        )
        summary = {"_upstream_feature_breakdown_data": feature_data}
        plugin.emit({}, summary, None)

        # Check final schema key written
        pi = summary.get("player_impact", {})
        ufb = pi.get("upstream_feature_breakdown")
        assert ufb is not None, (
            "emit() must write summary['player_impact']['upstream_feature_breakdown']"
        )
        assert ufb["applicable"] is True, f"applicable must be True, got {ufb['applicable']!r}"
        assert len(ufb["features"]) == 1, f"features must have 1 entry, got {len(ufb['features'])}"
        assert ufb["features"][0]["feature_name"] == "NormalCollectionSpin"

    def test_emit_removes_stash_key(self, plugin):
        """emit() must remove _upstream_feature_breakdown_data from summary (cleanup)."""
        stash = {"_upstream_feature_breakdown_data": self._make_stash_data()}
        plugin.emit({}, stash, None)
        assert "_upstream_feature_breakdown_data" not in stash, (
            "emit() must remove the stash key after reading it. "
            "Key still present: '_upstream_feature_breakdown_data' found in summary."
        )

    def test_emit_preserves_source_field(self, plugin):
        """source must be 'analysisResult.FeatureWin' from the stash."""
        stash = {"_upstream_feature_breakdown_data": self._make_stash_data()}
        plugin.emit({}, stash, None)
        ufb = stash["player_impact"]["upstream_feature_breakdown"]
        assert ufb["source"] == "analysisResult.FeatureWin", (
            f"source must be 'analysisResult.FeatureWin', got {ufb.get('source')!r}"
        )

    def test_emit_applicable_false_propagated(self, plugin):
        """emit() must propagate applicable=False from stash (single-feature machine)."""
        stash = {"_upstream_feature_breakdown_data": self._make_stash_data(applicable=False)}
        plugin.emit({}, stash, None)
        ufb = stash["player_impact"]["upstream_feature_breakdown"]
        assert ufb["applicable"] is False, (
            f"applicable must be False when stash says False, got {ufb['applicable']!r}"
        )

    def test_emit_creates_player_impact_if_absent(self, plugin):
        """emit() creates player_impact dict if not already present in summary."""
        stash = {"_upstream_feature_breakdown_data": self._make_stash_data()}
        # No player_impact key initially
        plugin.emit({}, stash, None)
        assert "player_impact" in stash, "emit() must create summary['player_impact'] if absent"


# ---------------------------------------------------------------------------
# T5: M275 subprocess — applicable=True + 4 features
# ---------------------------------------------------------------------------

class TestM275UpstreamFeatureBreakdown:
    """M275 must produce applicable=True with 4 feature entries."""

    def test_no_feature_errors(self, m275_ufb_summary):
        """feature_errors must be absent or empty for M275."""
        fe = m275_ufb_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"

    def test_upstream_feature_breakdown_key_present(self, m275_ufb_summary):
        """upstream_feature_breakdown must be in player_impact."""
        pi = m275_ufb_summary.get("player_impact", {})
        assert "upstream_feature_breakdown" in pi, (
            f"'upstream_feature_breakdown' missing from player_impact. Got keys: {sorted(pi.keys())}"
        )

    def test_m275_applicable_true(self, m275_ufb_summary):
        """M275 upstream_feature_breakdown.applicable must be True.

        INJECT-BUG (Bug A): change emit() to return empty features list.
        RED: applicable=False instead of True.
        Revert -> GREEN.
        """
        ufb = m275_ufb_summary["player_impact"]["upstream_feature_breakdown"]
        assert ufb["applicable"] is True, (
            f"M275 upstream_feature_breakdown.applicable must be True (multi-feature machine). "
            f"Got: {ufb['applicable']!r}"
        )

    def test_m275_exactly_4_features(self, m275_ufb_summary):
        """M275 must have exactly 4 feature entries."""
        ufb = m275_ufb_summary["player_impact"]["upstream_feature_breakdown"]
        features = ufb["features"]
        assert len(features) == 4, (
            f"M275 must have 4 feature entries, got {len(features)}. "
            f"Names: {[f.get('feature_name') for f in features]}"
        )

    def test_m275_has_normal_collection_spin(self, m275_ufb_summary):
        """M275 must have NormalCollectionSpin feature."""
        ufb = m275_ufb_summary["player_impact"]["upstream_feature_breakdown"]
        names = [f["feature_name"] for f in ufb["features"]]
        assert "NormalCollectionSpin" in names, (
            f"NormalCollectionSpin not found in feature names: {names}"
        )

    def test_m275_has_newfreespin_via_newfreespin(self, m275_ufb_summary):
        """M275 must have 'NewFreespin [via NewFreespin]' feature (re-trigger stream)."""
        ufb = m275_ufb_summary["player_impact"]["upstream_feature_breakdown"]
        names = [f["feature_name"] for f in ufb["features"]]
        assert "NewFreespin [via NewFreespin]" in names, (
            f"'NewFreespin [via NewFreespin]' not found in feature names: {names}"
        )

    def test_m275_has_newfreespin_via_bcm_cycle(self, m275_ufb_summary):
        """M275 must have 'NewFreespin [via BCM cycle]' feature (BCM-triggered bonus)."""
        ufb = m275_ufb_summary["player_impact"]["upstream_feature_breakdown"]
        names = [f["feature_name"] for f in ufb["features"]]
        assert "NewFreespin [via BCM cycle]" in names, (
            f"'NewFreespin [via BCM cycle]' not found in feature names: {names}"
        )

    def test_m275_has_buff_collection_map(self, m275_ufb_summary):
        """M275 must have BuffCollectionMap feature."""
        ufb = m275_ufb_summary["player_impact"]["upstream_feature_breakdown"]
        names = [f["feature_name"] for f in ufb["features"]]
        assert "BuffCollectionMap" in names, (
            f"BuffCollectionMap not found in feature names: {names}"
        )

    def test_m275_source_field(self, m275_ufb_summary):
        """source must be 'analysisResult.FeatureWin'."""
        ufb = m275_ufb_summary["player_impact"]["upstream_feature_breakdown"]
        assert ufb["source"] == "analysisResult.FeatureWin", (
            f"source must be 'analysisResult.FeatureWin', got {ufb.get('source')!r}"
        )

    def test_m275_no_stash_key_in_final_summary(self, m275_ufb_summary):
        """Stash key _upstream_feature_breakdown_data must not appear in final summary."""
        assert "_upstream_feature_breakdown_data" not in m275_ufb_summary, (
            "Stash key '_upstream_feature_breakdown_data' leaked into final summary."
        )


# ---------------------------------------------------------------------------
# T6: M14 subprocess — applicable=False
# ---------------------------------------------------------------------------

class TestM14UpstreamFeatureBreakdown:
    """M14 must produce applicable=False (single-feature vanilla machine)."""

    def test_no_feature_errors(self, m14_ufb_summary):
        """feature_errors must be absent or empty for M14."""
        fe = m14_ufb_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"

    def test_m14_upstream_feature_breakdown_present(self, m14_ufb_summary):
        """upstream_feature_breakdown must be in M14 player_impact."""
        pi = m14_ufb_summary.get("player_impact", {})
        assert "upstream_feature_breakdown" in pi, (
            f"'upstream_feature_breakdown' missing from M14 player_impact. "
            f"Got keys: {sorted(pi.keys())}"
        )

    def test_m14_applicable_false(self, m14_ufb_summary):
        """M14 upstream_feature_breakdown.applicable must be False (single-feature machine).

        M14 has only the 'Normal' feature in FeatureWin.
        No NormalCollectionSpin, no NewFreespin, no BuffCollectionMap.
        """
        ufb = m14_ufb_summary["player_impact"]["upstream_feature_breakdown"]
        assert ufb["applicable"] is False, (
            f"M14 upstream_feature_breakdown.applicable must be False "
            f"(single 'Normal' feature only). Got: {ufb['applicable']!r}"
        )
