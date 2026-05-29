"""Phase C5 — M14 must have no false positives for any C5-added output.

Spawns the real player_impact_analyzer against M14 mode 1 cached chunks.
Verifies that the 2 new C5 plugins + gap #5 filter do NOT fire false positives
for M14, which is the standard validation machine (vanilla, no BCM, single feature).

Background (per user_testing_machine.md)
-----------------------------------------
M14 is the standard validation machine for all analyzer changes.
It is a vanilla machine with:
  - Only "Normal" feature (no NormalCollectionSpin, no NewFreespin, no BCM)
  - No collect mechanic (no BCM robots)
  - No real PayoutGroupId grouping (all zeros or absent)

C5 false-positive invariants for M14
-------------------------------------
1. upstream_feature_breakdown.applicable = False (single "Normal" feature — NOT multi-feature)
2. collect_mechanic.applicable = False (no BCM mechanic)
3. collect_mechanic.clamp_warning.chunk_spin_times_recommendation = absent (None)
   (clamp_warning.applicable=False -> recommendation block omitted)
4. payout_groups_top20 = [] (no real group IDs; all_zeros_filtered or absent_field)
5. payout_groups_status != "populated" (no real PayoutGroupId groups for M14)
6. No feature_errors (both new plugins emit successfully; stash keys must be present)
7. No analyzer_init_error
8. upstream_feature_breakdown.features has exactly 1 entry (the "Normal" feature)
   This confirms applicable=False is correctly set for single-feature machines,
   not because features list is empty.

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug: Set a permanent applicable=True regardless of feature count.
     Phase 3 moved this compute OUT of player_impact_analyzer.py INTO the
     plugin fresh_slotlab/analyzer/features/upstream_feature_breakdown.py:
    In upstream_feature_breakdown.py emit(), find where ``applicable`` is
    derived from the feature count and force it True:
        applicable = True  # BUG: always True

    RED: M14 upstream_feature_breakdown.applicable becomes True (false positive).
         test_m14_upstream_feature_breakdown_applicable_false fails.
    Revert -> GREEN.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test required — unit tests alone can't catch PIA wiring false positives)
- memory/feedback_integration_test_argv.md
  (real subprocess against real M14 cached chunks)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/user_testing_machine.md (M14 mode 1 is the standard validation machine)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (applicable=False is an explicit "not this machine" signal, not a catch-all)
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_M14_CACHE = _REPO_ROOT / "rawdata" / "M14" / "mode_1"


@pytest.fixture(scope="module")
def m14_c5_summary() -> dict:
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
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists(), f"summary.json not written. STDOUT: {result.stdout[:500]}"
        return json.loads(summary_path.read_bytes())


# ---------------------------------------------------------------------------
# T1: Analyzer health
# ---------------------------------------------------------------------------

class TestM14C5Health:
    """Sanity: no errors; both new C5 plugin keys are present."""

    def test_no_analyzer_init_error(self, m14_c5_summary):
        """analyzer_init_error must be absent."""
        assert "analyzer_init_error" not in m14_c5_summary, (
            f"analyzer_init_error present: {m14_c5_summary.get('analyzer_init_error')}"
        )

    def test_no_feature_errors(self, m14_c5_summary):
        """feature_errors must be absent or empty.

        Both new C5 plugins (upstream_feature_breakdown + collect_mechanic) must
        succeed for M14 — stash keys must be written by PIA before emit loop.
        If either plugin raises RuntimeError on missing stash, it appears here.
        """
        fe = m14_c5_summary.get("feature_errors", {})
        assert not fe, (
            f"feature_errors populated: {fe}. "
            f"Both C5 plugins must succeed for M14 (stash keys must be written by PIA)."
        )

    def test_upstream_feature_breakdown_present_in_player_impact(self, m14_c5_summary):
        """upstream_feature_breakdown must be in player_impact for M14."""
        pi = m14_c5_summary.get("player_impact", {})
        assert "upstream_feature_breakdown" in pi, (
            f"'upstream_feature_breakdown' missing from M14 player_impact. "
            f"Got keys: {sorted(pi.keys())}"
        )

    def test_collect_mechanic_present_top_level(self, m14_c5_summary):
        """collect_mechanic must be a top-level key in M14 summary."""
        assert "collect_mechanic" in m14_c5_summary, (
            "collect_mechanic must be top-level in M14 summary."
        )


# ---------------------------------------------------------------------------
# T2: upstream_feature_breakdown — no false positive
# ---------------------------------------------------------------------------

class TestM14UpstreamFeatureBreakdownNoFalsePositive:
    """upstream_feature_breakdown.applicable must be False for M14."""

    def test_applicable_false(self, m14_c5_summary):
        """upstream_feature_breakdown.applicable must be False for M14.

        M14 has only the "Normal" feature — it is a single-feature machine.
        The applicable flag must be False to signal "breakdown is redundant
        with payout_ids_top20 for this machine".

        INJECT-BUG: force applicable=True in PIA logic.
        RED: this test fails (False != True).
        Revert -> GREEN.
        """
        pi = m14_c5_summary.get("player_impact", {})
        ufb = pi.get("upstream_feature_breakdown", {})
        assert ufb.get("applicable") is False, (
            f"M14 upstream_feature_breakdown.applicable must be False "
            f"(single-feature vanilla machine). Got: {ufb.get('applicable')!r}"
        )

    def test_features_list_has_one_entry(self, m14_c5_summary):
        """M14 must have exactly 1 feature entry (the 'Normal' feature).

        applicable=False is NOT because features is empty — it's because
        there's only 1 feature (Normal), which is not "multi-feature".
        The features list is still populated; the plugin just marks it as
        non-applicable for operator display purposes.
        """
        pi = m14_c5_summary.get("player_impact", {})
        ufb = pi.get("upstream_feature_breakdown", {})
        features = ufb.get("features", [])
        assert len(features) == 1, (
            f"M14 must have exactly 1 feature entry, got {len(features)}. "
            f"Names: {[f.get('feature_name') for f in features]}"
        )

    def test_m14_only_normal_feature(self, m14_c5_summary):
        """M14's single feature must be named 'Normal'."""
        pi = m14_c5_summary.get("player_impact", {})
        ufb = pi.get("upstream_feature_breakdown", {})
        features = ufb.get("features", [])
        if features:
            name = features[0].get("feature_name")
            assert name == "Normal", (
                f"M14's only feature must be 'Normal', got {name!r}"
            )


# ---------------------------------------------------------------------------
# T3: collect_mechanic — no false positive
# ---------------------------------------------------------------------------

class TestM14CollectMechanicNoFalsePositive:
    """collect_mechanic.applicable must be False for M14."""

    def test_applicable_false(self, m14_c5_summary):
        """collect_mechanic.applicable must be False for M14 (no BCM mechanic)."""
        cm = m14_c5_summary.get("collect_mechanic", {})
        assert cm.get("applicable") is False, (
            f"M14 collect_mechanic.applicable must be False (no BCM). "
            f"Got: {cm.get('applicable')!r}"
        )

    def test_clamp_warning_recommendation_absent(self, m14_c5_summary):
        """chunk_spin_times_recommendation must be absent for M14.

        M14 has no BCM -> clamp_warning.applicable=False ->
        chunk_spin_times_recommendation block is omitted.
        Per feedback_invariant_with_fallback_hides_drift.md: absent is explicit signal.
        """
        cm = m14_c5_summary.get("collect_mechanic", {})
        cw = cm.get("clamp_warning", {})
        rec = cw.get("chunk_spin_times_recommendation")
        assert rec is None, (
            f"M14 chunk_spin_times_recommendation must be absent (None). "
            f"Got: {rec!r}"
        )

    def test_clamp_warning_applicable_false(self, m14_c5_summary):
        """clamp_warning.applicable must be False for M14 (no robots, no collect events)."""
        cm = m14_c5_summary.get("collect_mechanic", {})
        cw = cm.get("clamp_warning", {})
        assert cw.get("applicable") is False, (
            f"M14 clamp_warning.applicable must be False. Got: {cw.get('applicable')!r}"
        )


# ---------------------------------------------------------------------------
# T4: payout_groups — no false "populated" positive
# ---------------------------------------------------------------------------

class TestM14PayoutGroupsNoFalsePositive:
    """M14 payout_groups must NOT be marked 'populated'."""

    def test_payout_groups_top20_empty(self, m14_c5_summary):
        """M14 payout_groups_top20 must be [] — no real group IDs."""
        pi = m14_c5_summary.get("player_impact", {})
        pg20 = pi.get("payout_groups_top20")
        assert pg20 == [], (
            f"M14 payout_groups_top20 must be [] (no real group IDs). Got: {pg20!r}"
        )

    def testpayout_groups_status_not_populated(self, m14_c5_summary):
        """M14 payout_groups_status must NOT be 'populated'."""
        pi = m14_c5_summary.get("player_impact", {})
        status = pi.get("payout_groups_status")
        assert status != "populated", (
            f"M14 payout_groups_status must NOT be 'populated'. Got: {status!r}. "
            f"M14 has no real PayoutGroupId groups — status must be "
            f"'absent_field' or 'all_zeros_filtered'."
        )
        # Verify it's one of the valid non-populated values
        assert status in {"absent_field", "all_zeros_filtered"}, (
            f"M14 payout_groups_status must be 'absent_field' or 'all_zeros_filtered', "
            f"got {status!r}"
        )


# ---------------------------------------------------------------------------
# T5: No stash key leakage for M14
# ---------------------------------------------------------------------------

class TestM14NoStashKeyLeakage:
    """Stash keys must be cleaned up even for M14 (applicable=False paths)."""

    def test_no_upstream_feature_breakdown_stash_in_final_summary(self, m14_c5_summary):
        """_upstream_feature_breakdown_data must not appear in final M14 summary."""
        assert "_upstream_feature_breakdown_data" not in m14_c5_summary, (
            "Stash key '_upstream_feature_breakdown_data' leaked into M14 final summary."
        )

    def test_no_collect_mechanic_stash_in_final_summary(self, m14_c5_summary):
        """_collect_mechanic_data must not appear in final M14 summary."""
        assert "_collect_mechanic_data" not in m14_c5_summary, (
            "Stash key '_collect_mechanic_data' leaked into M14 final summary."
        )
