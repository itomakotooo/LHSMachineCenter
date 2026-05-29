"""Phase C5 — unit + subprocess tests for collect_mechanic plugin.

Invariants asserted
-------------------
1. Plugin imports clean — no I/O side-effects at import time.
2. FEATURE_ID == "collect_mechanic".
3. SCHEMA_VERSION == 2 (C5 adds chunk_spin_times_recommendation).
4. REQUIRES == () (stash pattern; no emit-loop ordering dependency).
5. REGISTERED_FALLBACK_RULES[1] == {"chunk_spin_times_recommendation": None} (v1 migration rule).
6. RTP_CONTRIBUTION == False (display-only panel).
7. "collect_mechanic" in ALL_FEATURES after import.
8. register() is idempotent — duplicate import does not grow ALL_FEATURES.
9. extract() is a no-op — always returns {}.
10. reduce() is a no-op — always returns {}.
11. emit() raises RuntimeError when stash key absent.
12. emit() reads stash, adds gap #6 recommendation, removes stash, writes summary["collect_mechanic"] (TOP-LEVEL, not under player_impact).
13. emit() computes recommended_min = detected_cycle_length * avg_spins_per_collect.
14. emit() computes recommended_safety = recommended_min * 1.5.
15. emit() does NOT add chunk_spin_times_recommendation when clamp_warning.applicable=False.
16. emit() writes backward-compat alias newfreespin_correction into collect_mechanic dict.
17. M275 subprocess: applicable=True, detected_cycle_length=1000, all expected sub-fields present.
18. M275 subprocess: collect_mechanic is TOP-LEVEL (not under player_impact).
19. M275 subprocess: chunk_spin_times_recommendation present with current=5000.
20. M275 subprocess: recommended_min == 5000 (cycle_length 1000 * avg 5.0 spins/collect).
21. M275 subprocess: recommended_safety == 7500 (recommended_min * 1.5).
22. M14 subprocess: applicable=False.
23. M14 subprocess: collect_mechanic present (top-level key).

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug D — emit() skips reading stash entirely; emits empty dict:
    In collect_mechanic.py CollectMechanic.emit(), replace the main body with:
        summary.pop(_STASH_KEY, None)
        summary["collect_mechanic"] = {}
    RED: test_emit_reads_stash_writes_top_level fails (applicable missing/wrong).
         test_m275_applicable_true fails (subprocess).
    Revert (restore full emit body) -> GREEN.

Bug C (for gap #6 guard — see test_c5_gap_6_chunk_spin_times_recommendation.py):
    In collect_mechanic.py, change recommended_min formula to use constant 1000.
    RED: recommended_min == 1000 instead of computed value.
    Revert -> GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_subprocess_import_suicide_and_module_globals.md
  (register() must be pure list-append; no I/O at import time)
- memory/feedback_no_silent_swallow.md
  (emit() must raise RuntimeError on missing stash)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (chunk_spin_times_recommendation absent when not applicable = explicit signal, not silent 0)
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
        from fresh_slotlab.analyzer.features.collect_mechanic import CollectMechanic
    except ImportError:
        from analyzer.features.collect_mechanic import CollectMechanic  # type: ignore[no-redef]
    return CollectMechanic


# ---------------------------------------------------------------------------
# Subprocess fixtures (module-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m275_cm_summary() -> dict:
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
def m14_cm_summary() -> dict:
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

class TestCollectMechanicClassInvariants:
    """Class-level constants must match design contract."""

    def test_feature_id(self):
        """FEATURE_ID must be 'collect_mechanic'."""
        cls = _import_plugin_class()
        assert cls.FEATURE_ID == "collect_mechanic", (
            f"FEATURE_ID must be 'collect_mechanic', got {cls.FEATURE_ID!r}"
        )

    def test_schema_version_is_2(self):
        """SCHEMA_VERSION must be 2 (C5 adds chunk_spin_times_recommendation)."""
        cls = _import_plugin_class()
        assert cls.SCHEMA_VERSION == 2, (
            f"SCHEMA_VERSION must be 2, got {cls.SCHEMA_VERSION}"
        )

    def test_registered_fallback_rules_v1(self):
        """REGISTERED_FALLBACK_RULES[1] uses dotted path for nested schema.

        v1 summaries (pre-C5 inline block) lack chunk_spin_times_recommendation
        which is nested at collect_mechanic.clamp_warning.chunk_spin_times_recommendation.
        Frontend renders as None per this fallback rule.

        C5 critic FIX-3: was {flat_key: None}; now uses dotted path matching
        actual nested schema location so future fallback engine writes to the
        right place.
        """
        cls = _import_plugin_class()
        rules = cls.REGISTERED_FALLBACK_RULES
        assert 1 in rules, (
            f"REGISTERED_FALLBACK_RULES must have key 1. Got keys: {list(rules.keys())}"
        )
        assert rules[1] == {"clamp_warning.chunk_spin_times_recommendation": None}, (
            f"REGISTERED_FALLBACK_RULES[1] must use dotted path "
            f"{{'clamp_warning.chunk_spin_times_recommendation': None}} per nested schema, "
            f"got {rules[1]!r}"
        )

    def test_requires_is_empty_tuple(self):
        """REQUIRES must be () — stash pattern; no emit-loop ordering dep."""
        cls = _import_plugin_class()
        assert cls.REQUIRES == (), (
            f"REQUIRES must be (), got {cls.REQUIRES!r}"
        )

    def test_rtp_contribution_is_false(self):
        """RTP_CONTRIBUTION must be False — display-only panel."""
        cls = _import_plugin_class()
        assert cls.RTP_CONTRIBUTION is False, (
            f"RTP_CONTRIBUTION must be False, got {cls.RTP_CONTRIBUTION!r}"
        )

    def test_schema_keys_contains_collect_mechanic(self):
        """SCHEMA_KEYS must contain 'collect_mechanic'."""
        cls = _import_plugin_class()
        assert "collect_mechanic" in cls.SCHEMA_KEYS, (
            f"SCHEMA_KEYS must contain 'collect_mechanic', got {cls.SCHEMA_KEYS!r}"
        )


# ---------------------------------------------------------------------------
# T2: Import safety + registration idempotency
# ---------------------------------------------------------------------------

class TestCollectMechanicImportSafety:
    """Import must be side-effect free; register() must be idempotent."""

    def test_import_clean(self):
        """Importing the module must not raise or produce side effects."""
        mod = importlib.import_module("fresh_slotlab.analyzer.features.collect_mechanic")
        assert hasattr(mod, "CollectMechanic"), (
            "CollectMechanic class not found after import"
        )

    def test_in_all_features_after_import(self):
        """After importing, ALL_FEATURES must contain 'collect_mechanic'."""
        import fresh_slotlab.analyzer.features.collect_mechanic  # noqa: F401
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
        fids = [f.FEATURE_ID for f in ALL_FEATURES]
        assert "collect_mechanic" in fids, (
            f"'collect_mechanic' not in ALL_FEATURES. Got: {fids}"
        )

    def test_register_idempotent(self):
        """Calling register() twice must not grow ALL_FEATURES."""
        from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES, register
        cls = _import_plugin_class()
        before = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "collect_mechanic")
        register(cls())
        after = sum(1 for f in ALL_FEATURES if f.FEATURE_ID == "collect_mechanic")
        assert after == before, (
            f"register() not idempotent: count grew from {before} to {after}"
        )


# ---------------------------------------------------------------------------
# T3: extract() and reduce() no-ops
# ---------------------------------------------------------------------------

class TestCollectMechanicExtractReduce:
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

class TestCollectMechanicEmit:
    """emit() stash-pattern contract and gap #6 recommendation formula."""

    @pytest.fixture
    def plugin(self):
        return _import_plugin_class()()

    def _make_stash(self, applicable=True, robots=5, collects=100,
                    clamp_applicable=True, pending_robots=3, avg_spins=5.0,
                    cycle_length=1000):
        """Build a minimal _collect_mechanic_data stash dict.

        Phase 2a contract: the stash carries RAW accumulator inputs (the plugin
        now OWNS the dict-build). These raw values are chosen so the dict the
        plugin rebuilds yields the SAME derived fields the assertions check:
          - applicable          <- collect_robots_seen_total > 0
          - robots_with_data    <- collect_robots_seen_total
          - total_collects      <- collect_count_total
          - detected_cycle_length <- int(median(sorted(all_cycle_peaks)))
          - clamp_warning.applicable <- robots>0 and clamp_pending_robots_total>0
          - avg_paid_spins_per_collect <- total_paid_sessions / collect_count_total
        ``applicable`` (legacy kwarg) toggles robots_seen so callers that passed
        applicable=False still produce a non-applicable summary.
        """
        robots_seen = robots if applicable else 0
        # avg_paid_spins_per_collect = total_paid_sessions / collect_count_total
        total_paid_sessions = int(round(avg_spins * collects))
        return {
            "collect_robots_seen_total": robots_seen,
            "collect_count_total": collects,
            "acc_credits_max_global": 999,
            "total_spins": collects * 5,  # avg_spins_between_collects = 5.0
            "clamp_pending_robots_total": pending_robots if clamp_applicable else 0,
            "clamp_pending_paid_spins_total": 15,
            "total_paid_sessions": total_paid_sessions,
            # Single cycle peak -> median == cycle_length -> detected_cycle_length
            "all_cycle_peaks": [cycle_length],
            "all_final_cc_values": [500, 500, 500],
            "total_completed_cycles": 80,
            "upstream_feature_tally": {
                "NewFreespin": {"1": {"win": 3200000.0, "times": 80}},
            },
            "effective_bet_for_rtp": 1000.0 * collects,
            "bonus_feature": "NewFreespin",
            "bonus_feature_source": "bcm_pairings",
        }

    def test_emit_raises_when_stash_absent(self, plugin):
        """emit() must raise RuntimeError when stash key missing."""
        with pytest.raises(RuntimeError, match="_collect_mechanic_data"):
            plugin.emit({}, {}, None)

    def test_emit_reads_stash_writes_top_level(self, plugin):
        """emit() must write summary['collect_mechanic'] (top-level, not under player_impact).

        INJECT-BUG (Bug D): change emit() to write empty dict.
        RED: applicable missing or wrong.
        Revert -> GREEN.
        """
        stash = self._make_stash()
        summary = {
            "_collect_mechanic_data": stash,
            "sampling": {"chunk_spin_times": 5000},
        }
        plugin.emit({}, summary, None)

        assert "collect_mechanic" in summary, (
            "emit() must write summary['collect_mechanic'] (top-level key)."
        )
        cm = summary["collect_mechanic"]
        assert cm["applicable"] is True, f"applicable must be True, got {cm.get('applicable')!r}"
        assert cm["robots_with_data"] == 5

    def test_emit_not_under_player_impact(self, plugin):
        """collect_mechanic must be a top-level key — NOT under player_impact."""
        stash = self._make_stash()
        summary = {
            "_collect_mechanic_data": stash,
            "sampling": {"chunk_spin_times": 5000},
        }
        plugin.emit({}, summary, None)

        pi = summary.get("player_impact", {})
        assert "collect_mechanic" not in pi, (
            "collect_mechanic must NOT be under player_impact. "
            "It is a top-level key to preserve pre-C5 schema location."
        )

    def test_emit_removes_stash_key(self, plugin):
        """emit() must remove _collect_mechanic_data from summary."""
        stash = self._make_stash()
        summary = {
            "_collect_mechanic_data": stash,
            "sampling": {"chunk_spin_times": 5000},
        }
        plugin.emit({}, summary, None)
        assert "_collect_mechanic_data" not in summary, (
            "emit() must remove stash key '_collect_mechanic_data'."
        )

    def test_emit_adds_chunk_spin_times_recommendation(self, plugin):
        """emit() must add chunk_spin_times_recommendation to clamp_warning.

        recommended_min = detected_cycle_length * avg_spins_per_collect.
        recommended_safety = recommended_min * 1.5.
        Per gap #6 design (brief §2.3).
        """
        stash = self._make_stash(clamp_applicable=True, avg_spins=5.0, cycle_length=1000)
        summary = {
            "_collect_mechanic_data": stash,
            "sampling": {"chunk_spin_times": 5000},
        }
        plugin.emit({}, summary, None)
        cm = summary["collect_mechanic"]
        cw = cm.get("clamp_warning", {})
        rec = cw.get("chunk_spin_times_recommendation")
        assert rec is not None, (
            "chunk_spin_times_recommendation must be present when clamp_warning.applicable=True "
            "and cycle_length + avg_spins are known. Got None."
        )

    def test_emit_recommended_min_formula(self, plugin):
        """recommended_min = detected_cycle_length * avg_paid_spins_per_collect.

        cycle_length=1000, avg_spins=5.0 -> recommended_min=5000.
        """
        stash = self._make_stash(clamp_applicable=True, avg_spins=5.0, cycle_length=1000)
        summary = {
            "_collect_mechanic_data": stash,
            "sampling": {"chunk_spin_times": 5000},
        }
        plugin.emit({}, summary, None)
        cm = summary["collect_mechanic"]
        rec = cm["clamp_warning"]["chunk_spin_times_recommendation"]
        assert rec["recommended_min"] == 5000, (
            f"recommended_min must be 1000 * 5.0 = 5000, got {rec['recommended_min']}"
        )

    def test_emit_recommended_safety_formula(self, plugin):
        """recommended_safety = recommended_min * 1.5.

        recommended_min=5000 -> recommended_safety=7500.
        """
        stash = self._make_stash(clamp_applicable=True, avg_spins=5.0, cycle_length=1000)
        summary = {
            "_collect_mechanic_data": stash,
            "sampling": {"chunk_spin_times": 5000},
        }
        plugin.emit({}, summary, None)
        cm = summary["collect_mechanic"]
        rec = cm["clamp_warning"]["chunk_spin_times_recommendation"]
        assert rec["recommended_safety"] == 7500, (
            f"recommended_safety must be 5000 * 1.5 = 7500, got {rec['recommended_safety']}"
        )

    def test_emit_recommendation_absent_when_clamp_not_applicable(self, plugin):
        """chunk_spin_times_recommendation must NOT be added when clamp_warning.applicable=False.

        Per feedback_invariant_with_fallback_hides_drift.md: absent means
        'no BCM cycle mid-truncation' — not 0 or placeholder.
        """
        # Phase 2a: clamp non-applicability is driven by the raw input
        # clamp_pending_robots_total == 0 (set by clamp_applicable=False), since
        # the plugin now derives clamp_warning.applicable itself.
        stash = self._make_stash(clamp_applicable=False, avg_spins=5.0, cycle_length=1000)
        summary = {
            "_collect_mechanic_data": stash,
            "sampling": {"chunk_spin_times": 5000},
        }
        plugin.emit({}, summary, None)
        cm = summary["collect_mechanic"]
        cw = cm.get("clamp_warning", {})
        rec = cw.get("chunk_spin_times_recommendation")
        assert rec is None, (
            f"chunk_spin_times_recommendation must be absent (not added) when "
            f"clamp_warning.applicable=False. Got: {rec!r}"
        )

    def test_emit_writes_backward_compat_alias(self, plugin):
        """newfreespin_correction must be an alias for bonus_cycle_correction."""
        stash = self._make_stash()
        summary = {
            "_collect_mechanic_data": stash,
            "sampling": {"chunk_spin_times": 5000},
        }
        plugin.emit({}, summary, None)
        cm = summary["collect_mechanic"]
        assert "newfreespin_correction" in cm, (
            "newfreespin_correction alias must be present in collect_mechanic "
            "for backward compatibility."
        )
        assert cm["newfreespin_correction"] is cm["bonus_cycle_correction"], (
            "newfreespin_correction must point to the same dict as bonus_cycle_correction."
        )

    def test_emit_current_chunk_spin_times_from_sampling(self, plugin):
        """chunk_spin_times_recommendation.current reads from summary['sampling']['chunk_spin_times']."""
        stash = self._make_stash(clamp_applicable=True, avg_spins=4.0, cycle_length=500)
        summary = {
            "_collect_mechanic_data": stash,
            "sampling": {"chunk_spin_times": 3000},
        }
        plugin.emit({}, summary, None)
        cm = summary["collect_mechanic"]
        rec = cm["clamp_warning"]["chunk_spin_times_recommendation"]
        assert rec["current"] == 3000, (
            f"current must match sampling.chunk_spin_times=3000, got {rec['current']}"
        )

    def test_emit_rationale_nonempty_string(self, plugin):
        """chunk_spin_times_recommendation.rationale must be a non-empty string."""
        stash = self._make_stash(clamp_applicable=True, avg_spins=5.0, cycle_length=1000)
        summary = {
            "_collect_mechanic_data": stash,
            "sampling": {"chunk_spin_times": 5000},
        }
        plugin.emit({}, summary, None)
        cm = summary["collect_mechanic"]
        rec = cm["clamp_warning"]["chunk_spin_times_recommendation"]
        rationale = rec.get("rationale", "")
        assert isinstance(rationale, str) and len(rationale) > 0, (
            f"rationale must be a non-empty string, got {rationale!r}"
        )


# ---------------------------------------------------------------------------
# T5: M275 subprocess — applicable=True + detailed fields
# ---------------------------------------------------------------------------

class TestM275CollectMechanic:
    """M275 collect_mechanic must be top-level, applicable=True, with cycle data."""

    def test_no_feature_errors(self, m275_cm_summary):
        """feature_errors must be absent or empty for M275."""
        fe = m275_cm_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"

    def test_collect_mechanic_top_level(self, m275_cm_summary):
        """collect_mechanic must be a top-level key (not under player_impact).

        This is the schema location contract from the pre-C5 inline block.
        """
        assert "collect_mechanic" in m275_cm_summary, (
            "collect_mechanic must be top-level in summary. "
            f"Top-level keys: {[k for k in m275_cm_summary if not k.startswith('_')]}"
        )
        pi = m275_cm_summary.get("player_impact", {})
        assert "collect_mechanic" not in pi, (
            "collect_mechanic must NOT be under player_impact — it is top-level."
        )

    def test_m275_applicable_true(self, m275_cm_summary):
        """M275 collect_mechanic.applicable must be True (BCM machine).

        INJECT-BUG (Bug D): emit() writes empty dict.
        RED: applicable missing/False.
        Revert -> GREEN.
        """
        cm = m275_cm_summary["collect_mechanic"]
        assert cm["applicable"] is True, (
            f"collect_mechanic.applicable must be True for M275 (BCM machine). "
            f"Got: {cm.get('applicable')!r}"
        )

    def test_m275_detected_cycle_length_1000(self, m275_cm_summary):
        """bonus_cycle_correction.detected_cycle_length must be 1000 for M275."""
        cm = m275_cm_summary["collect_mechanic"]
        bcc = cm.get("bonus_cycle_correction", {})
        assert bcc.get("detected_cycle_length") == 1000, (
            f"detected_cycle_length must be 1000 for M275, "
            f"got {bcc.get('detected_cycle_length')}"
        )

    def test_m275_clamp_warning_applicable(self, m275_cm_summary):
        """clamp_warning.applicable must be True for M275 (mid-cycle truncation)."""
        cm = m275_cm_summary["collect_mechanic"]
        cw = cm.get("clamp_warning", {})
        assert cw.get("applicable") is True, (
            f"clamp_warning.applicable must be True for M275. "
            f"Got: {cw.get('applicable')!r}"
        )

    def test_m275_chunk_spin_times_recommendation_present(self, m275_cm_summary):
        """chunk_spin_times_recommendation must be present in M275 clamp_warning."""
        cm = m275_cm_summary["collect_mechanic"]
        cw = cm.get("clamp_warning", {})
        rec = cw.get("chunk_spin_times_recommendation")
        assert rec is not None, (
            "chunk_spin_times_recommendation must be present in M275 clamp_warning. "
            "Got None — gap #6 may not be implemented correctly."
        )

    def test_m275_current_chunk_spin_times_5000(self, m275_cm_summary):
        """current must be 5000 (M275 mode 1 chunk_spin_times)."""
        cm = m275_cm_summary["collect_mechanic"]
        rec = cm["clamp_warning"]["chunk_spin_times_recommendation"]
        assert rec["current"] == 5000, (
            f"current must be 5000 (M275 mode 1 chunk_spin_times), got {rec['current']}"
        )

    def test_m275_recommended_min_5000(self, m275_cm_summary):
        """recommended_min must be 5000 (1000 * 5.0 avg_spins_per_collect).

        M275 actual values: detected_cycle_length=1000, avg_paid_spins_per_collect=5.0
        -> recommended_min = 1000 * 5.0 = 5000.

        Note: brief §2.3 used estimated values (5570); this test uses the measured
        actual value from the cached data.
        """
        cm = m275_cm_summary["collect_mechanic"]
        rec = cm["clamp_warning"]["chunk_spin_times_recommendation"]
        assert rec["recommended_min"] == 5000, (
            f"recommended_min must be 5000 (1000 * 5.0 measured avg), "
            f"got {rec['recommended_min']}"
        )

    def test_m275_recommended_safety_7500(self, m275_cm_summary):
        """recommended_safety must be 7500 (5000 * 1.5 safety factor)."""
        cm = m275_cm_summary["collect_mechanic"]
        rec = cm["clamp_warning"]["chunk_spin_times_recommendation"]
        assert rec["recommended_safety"] == 7500, (
            f"recommended_safety must be 7500 (5000 * 1.5), got {rec['recommended_safety']}"
        )

    def test_m275_rationale_nonempty(self, m275_cm_summary):
        """rationale must be a non-empty string."""
        cm = m275_cm_summary["collect_mechanic"]
        rec = cm["clamp_warning"]["chunk_spin_times_recommendation"]
        rationale = rec.get("rationale", "")
        assert isinstance(rationale, str) and len(rationale) > 10, (
            f"rationale must be a non-empty descriptive string, got {rationale!r}"
        )

    def test_m275_no_stash_key_in_final_summary(self, m275_cm_summary):
        """Stash key _collect_mechanic_data must not appear in final summary."""
        assert "_collect_mechanic_data" not in m275_cm_summary, (
            "Stash key '_collect_mechanic_data' leaked into final summary."
        )

    def test_m275_newfreespin_correction_alias_present(self, m275_cm_summary):
        """newfreespin_correction backward-compat alias must be in collect_mechanic."""
        cm = m275_cm_summary["collect_mechanic"]
        assert "newfreespin_correction" in cm, (
            "newfreespin_correction alias missing from M275 collect_mechanic. "
            "Backward-compat alias required for pre-C5 frontend code."
        )


# ---------------------------------------------------------------------------
# T6: M14 subprocess — applicable=False
# ---------------------------------------------------------------------------

class TestM14CollectMechanic:
    """M14 collect_mechanic must be top-level and applicable=False."""

    def test_no_feature_errors(self, m14_cm_summary):
        """feature_errors must be absent or empty for M14."""
        fe = m14_cm_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"

    def test_collect_mechanic_top_level(self, m14_cm_summary):
        """collect_mechanic must be a top-level key in M14 summary."""
        assert "collect_mechanic" in m14_cm_summary, (
            "collect_mechanic must be top-level in M14 summary."
        )

    def test_m14_applicable_false(self, m14_cm_summary):
        """M14 collect_mechanic.applicable must be False (no BCM mechanic)."""
        cm = m14_cm_summary["collect_mechanic"]
        assert cm["applicable"] is False, (
            f"collect_mechanic.applicable must be False for M14 (no BCM). "
            f"Got: {cm.get('applicable')!r}"
        )
