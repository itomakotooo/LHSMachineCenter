"""Phase C5 — byte-identical unrelated fields + base_hash unchanged.

Verifies that the C5 commit (2 new plugins + gap #5 + gap #6) does NOT
inadvertently change fields that are outside its scope.

Invariants asserted
-------------------
1. base_hash == "d8b8c138874a" (R-1 closure value, post phase-6; registered plugins excluded by R-4).
2. M275 summary: payout_groups_top20 == [] (gap #5 closed).
3. M275 summary: payout_groups_status == "all_zeros_filtered" (gap #5 closed).
4. M275 summary: upstream_feature_breakdown.applicable == True (C5 plugin).
5. M275 summary: collect_mechanic top-level, applicable == True (C5 plugin).
6. M275 summary: collect_mechanic.clamp_warning.chunk_spin_times_recommendation present (gap #6).
7. M14 summary: upstream_feature_breakdown.applicable == False (no false positives).
8. M14 summary: collect_mechanic.applicable == False (no false positives).
9. Stash keys absent from M275 final summary (cleanup loop effective).
10. Stash keys absent from M14 final summary.
11. No _ prefix keys at top-level of M275 or M14 final summary.
12. All C5 new fields are precisely: upstream_feature_breakdown (in player_impact),
    collect_mechanic (top-level), payout_groups_top20 (now [], was noise),
    payout_groups_status (in player_impact), chunk_spin_times_recommendation (in clamp_warning).
13. Preexisting fields not touched by C5 retain expected structure:
    - player_impact.bankruptcy_simulation present
    - player_impact.multiplier_profile present
    - player_impact.payouts_by_spin_type present
    - player_impact.machine_mechanics present
    - player_impact.reel_marginal_by_spin_type present
    - player_impact.multiplier_wild present
    - summary.rtp present
    - summary.sampling present

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess required — unit tests alone cannot catch PIA field drift)
- memory/feedback_aggregator_parity_invariant.md
  (C5 plugins have RTP_CONTRIBUTION=False; they must not alter rtp values)
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
_M275_CACHE = _REPO_ROOT / "rawdata" / "M275" / "mode_1"
_M14_CACHE = _REPO_ROOT / "rawdata" / "M14" / "mode_1"


# ---------------------------------------------------------------------------
# Subprocess fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m275_bi_summary() -> dict:
    """Run M275 mode 1 from cache; return parsed summary."""
    if not _M275_CACHE.exists() or not list(_M275_CACHE.glob("chunk_*.json")):
        pytest.skip(f"M275 mode 1 cached chunks not found at {_M275_CACHE}")
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [sys.executable, str(_PIA), "--machine", "M275", "--rtp-mode", "1",
               "--from-cache", str(_M275_CACHE), "--output-dir", tmpdir, "--bet", "1000"]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=300)
        assert result.returncode == 0, f"M275 exited {result.returncode}.\nSTDERR: {result.stderr[:2000]}"
        return json.loads((Path(tmpdir) / "player_impact_summary.json").read_bytes())


@pytest.fixture(scope="module")
def m14_bi_summary() -> dict:
    """Run M14 mode 1 from cache; return parsed summary."""
    if not _M14_CACHE.exists() or not list(_M14_CACHE.glob("chunk_*.json")):
        pytest.skip(f"M14 mode 1 cached chunks not found at {_M14_CACHE}")
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [sys.executable, str(_PIA), "--machine", "M14", "--rtp-mode", "1",
               "--from-cache", str(_M14_CACHE), "--output-dir", tmpdir, "--bet", "1000"]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=300)
        assert result.returncode == 0, f"M14 exited {result.returncode}.\nSTDERR: {result.stderr[:2000]}"
        return json.loads((Path(tmpdir) / "player_impact_summary.json").read_bytes())


# ---------------------------------------------------------------------------
# T1: base_hash unchanged
# ---------------------------------------------------------------------------

class TestBaseHashUnchanged:
    """base_hash must be the R-1 closure value (honesty-2, 2026-05-29)."""

    def test_base_hash_value(self):
        """compute_base_analyzer_version() must return d8b8c138874a.

        Phase honesty-2 redefined base_hash to the 25-file report-production
        import closure (R-1) → 960e9d18d83d. C5 adds registered plugin files in
        features/ which are EXCLUDED from base_hash by R-4. Phase 2a (the
        collect_mechanic carve) removed the inline dict-builder + 2 private
        helpers from player_impact_analyzer.py (a closure file) → base shrank to
        57fdb323585d. Phase 2b (the bonus_chain_dynamics carve) removed that
        feature's dict-build from PIA → base shrank to 980f488f4bb2. Phase 3 (the
        upstream_feature_breakdown carve) removed that feature's ~400-line row-build
        from PIA → base shrank to c89db791d8a1. Phase 4 (the multiplier_profile
        carve) removed that feature's inline dict-build from PIA → base shrank to
        ce298f055495. Phase 5 (the reel_marginal_by_spin_type carve) removed that
        feature's inline dict-build from PIA → base shrank to ccc1ecce185d. Phase 6
        (the bankruptcy_simulation carve — the LAST carve of the unbundle) removed
        that feature's inline tier ROW-BUILD loop from PIA → base shrank to
        d8b8c138874a
        (one-time fleet re-baseline; report content byte-identical).
        If base_hash changes again, it signals a modification to a production-
        path file in the _CLOSURE_FILES tuple.
        """
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
        actual = compute_base_analyzer_version()
        assert actual == "85666c4c4407", (
            f"base_hash must be '85666c4c4407' (R-1 closure value, post PT-3 BCM-cycle carve). "
            f"Got: {actual!r}. "
            f"Registered plugin additions must NOT change base_hash (R-4 exclusion). "
            f"If a production-path file (in _CLOSURE_FILES) was modified, update this pin."
        )


# ---------------------------------------------------------------------------
# T2: C5 gap closures verified (summary of invariants from other test files)
# ---------------------------------------------------------------------------

class TestC5GapClosures:
    """All C5 gap closures confirmed in one place for easy verifier review."""

    def test_m275_gap_5_payout_groups_empty(self, m275_bi_summary):
        """Gap #5: M275 payout_groups_top20 == [] (all-zeros noise filtered)."""
        pi = m275_bi_summary.get("player_impact", {})
        assert pi.get("payout_groups_top20") == [], (
            f"Gap #5 not closed: payout_groups_top20 is not empty. Got: {pi.get('payout_groups_top20')!r}"
        )

    def test_m275_gap_5_status_all_zeros_filtered(self, m275_bi_summary):
        """Gap #5: payout_groups_status == 'all_zeros_filtered'."""
        pi = m275_bi_summary.get("player_impact", {})
        assert pi.get("payout_groups_status") == "all_zeros_filtered", (
            f"Gap #5 not closed: status is {pi.get('payout_groups_status')!r}"
        )

    def test_m275_gap_6_recommendation_present(self, m275_bi_summary):
        """Gap #6: chunk_spin_times_recommendation present in M275 clamp_warning."""
        cm = m275_bi_summary.get("collect_mechanic", {})
        rec = cm.get("clamp_warning", {}).get("chunk_spin_times_recommendation")
        assert rec is not None, "Gap #6 not closed: chunk_spin_times_recommendation absent for M275."

    def test_m275_c5_plugin_upstream_feature_breakdown(self, m275_bi_summary):
        """C5 plugin: upstream_feature_breakdown present and applicable=True for M275."""
        pi = m275_bi_summary.get("player_impact", {})
        ufb = pi.get("upstream_feature_breakdown", {})
        assert ufb.get("applicable") is True, (
            f"upstream_feature_breakdown.applicable must be True for M275. Got: {ufb.get('applicable')!r}"
        )

    def test_m275_c5_plugin_collect_mechanic(self, m275_bi_summary):
        """C5 plugin: collect_mechanic top-level, applicable=True for M275."""
        cm = m275_bi_summary.get("collect_mechanic", {})
        assert cm.get("applicable") is True, (
            f"collect_mechanic.applicable must be True for M275. Got: {cm.get('applicable')!r}"
        )


# ---------------------------------------------------------------------------
# T3: C5 false-positive guard (M14)
# ---------------------------------------------------------------------------

class TestC5FalsePositiveGuard:
    """C5 plugins must not produce false positives on M14."""

    def test_m14_upstream_feature_breakdown_applicable_false(self, m14_bi_summary):
        """upstream_feature_breakdown.applicable must be False for M14."""
        pi = m14_bi_summary.get("player_impact", {})
        ufb = pi.get("upstream_feature_breakdown", {})
        assert ufb.get("applicable") is False, (
            f"False positive: M14 upstream_feature_breakdown.applicable is not False. "
            f"Got: {ufb.get('applicable')!r}"
        )

    def test_m14_collect_mechanic_applicable_false(self, m14_bi_summary):
        """collect_mechanic.applicable must be False for M14."""
        cm = m14_bi_summary.get("collect_mechanic", {})
        assert cm.get("applicable") is False, (
            f"False positive: M14 collect_mechanic.applicable is not False. "
            f"Got: {cm.get('applicable')!r}"
        )


# ---------------------------------------------------------------------------
# T4: Stash key cleanup — no leakage
# ---------------------------------------------------------------------------

class TestStashKeyCleanup:
    """All C5 stash keys must be absent from both M275 and M14 final summaries."""

    _C5_STASH_KEYS = [
        "_upstream_feature_breakdown_data",
        "_collect_mechanic_data",
    ]

    def test_m275_no_stash_keys_in_top_level(self, m275_bi_summary):
        """No C5 stash keys at M275 top-level summary."""
        for k in self._C5_STASH_KEYS:
            assert k not in m275_bi_summary, (
                f"Stash key '{k}' leaked into M275 final summary top-level."
            )

    def test_m14_no_stash_keys_in_top_level(self, m14_bi_summary):
        """No C5 stash keys at M14 top-level summary."""
        for k in self._C5_STASH_KEYS:
            assert k not in m14_bi_summary, (
                f"Stash key '{k}' leaked into M14 final summary top-level."
            )

    def test_m275_no_underscore_top_level_keys(self, m275_bi_summary):
        """No _ prefix keys at M275 top-level summary (cleanup loop effective)."""
        leaked = [k for k in m275_bi_summary if k.startswith("_")]
        assert not leaked, (
            f"_ prefix keys leaked into M275 top-level summary: {leaked}. "
            f"Cleanup loop must remove all _ keys from summary root."
        )

    def test_m14_no_underscore_top_level_keys(self, m14_bi_summary):
        """No _ prefix keys at M14 top-level summary."""
        leaked = [k for k in m14_bi_summary if k.startswith("_")]
        assert not leaked, (
            f"_ prefix keys leaked into M14 top-level summary: {leaked}."
        )


# ---------------------------------------------------------------------------
# T5: Preexisting fields not disrupted by C5
# ---------------------------------------------------------------------------

class TestPreexistingFieldsPreserved:
    """Fields owned by C1-C4 plugins must still be present in M275 + M14."""

    # Keys present in both M275 and M14 (universal features declared in both manifests).
    _UNIVERSAL_PLAYER_IMPACT_KEYS = [
        "bankruptcy_simulation",
        "multiplier_profile",
        "payouts_by_spin_type",
        "machine_mechanics",
        "reel_marginal_by_spin_type",
    ]

    # multiplier_wild is only declared in M275 manifest, not M14.
    _M275_ONLY_KEYS = [
        "multiplier_wild",
    ]

    def test_m275_c1_c4_player_impact_fields_present(self, m275_bi_summary):
        """All universal + M275-specific C1-C4 player_impact keys must still be present in M275."""
        pi = m275_bi_summary.get("player_impact", {})
        for key in self._UNIVERSAL_PLAYER_IMPACT_KEYS + self._M275_ONLY_KEYS:
            assert key in pi, (
                f"Preexisting player_impact key '{key}' missing from M275 after C5. "
                f"C5 must not disrupt C1-C4 plugin outputs."
            )

    def test_m14_c1_c4_player_impact_fields_present(self, m14_bi_summary):
        """Universal C1-C4 player_impact keys must still be present in M14.

        Note: multiplier_wild is NOT in M14's manifest — M14 does not use
        multiplier wild mechanics. Only universal features are checked for M14.
        """
        pi = m14_bi_summary.get("player_impact", {})
        for key in self._UNIVERSAL_PLAYER_IMPACT_KEYS:
            assert key in pi, (
                f"Preexisting player_impact key '{key}' missing from M14 after C5. "
                f"Got keys: {sorted(pi.keys())}"
            )

    def test_m275_rtp_present(self, m275_bi_summary):
        """M275 summary.rtp must still be present (C5 does not affect RTP computation)."""
        assert "rtp" in m275_bi_summary, "summary.rtp missing from M275 after C5."

    def test_m275_sampling_present(self, m275_bi_summary):
        """M275 summary.sampling must still be present."""
        assert "sampling" in m275_bi_summary, "summary.sampling missing from M275 after C5."

    def test_m14_rtp_present(self, m14_bi_summary):
        """M14 summary.rtp must still be present."""
        assert "rtp" in m14_bi_summary, "summary.rtp missing from M14 after C5."

    def test_m275_no_feature_errors(self, m275_bi_summary):
        """M275 must have no feature_errors (all C1-C4-C5 plugins succeed)."""
        fe = m275_bi_summary.get("feature_errors", {})
        assert not fe, f"feature_errors in M275: {fe}"

    def test_m14_no_feature_errors(self, m14_bi_summary):
        """M14 must have no feature_errors."""
        fe = m14_bi_summary.get("feature_errors", {})
        assert not fe, f"feature_errors in M14: {fe}"


# ---------------------------------------------------------------------------
# T6: payout_groups_status nested-key cleanup behavior
# ---------------------------------------------------------------------------

class TestPayoutGroupsStatusNestedCleanup:
    """Verify payout_groups_status inside player_impact survives top-level cleanup.

    Per brief §2.2: the top-level cleanup loop removes _ keys from summary root.
    payout_groups_status is nested inside player_impact{} — it is NOT a top-level
    summary key, so it must survive the cleanup loop.

    This is the implementer concern #3: nested _ key is safe from cleanup.
    """

    def test_m275payout_groups_status_survives_cleanup(self, m275_bi_summary):
        """payout_groups_status under player_impact must survive the top-level _ cleanup."""
        pi = m275_bi_summary.get("player_impact", {})
        assert "payout_groups_status" in pi, (
            "payout_groups_status was deleted from player_impact by the cleanup loop. "
            "The cleanup loop only removes top-level _ keys — nested _ keys must survive."
        )

    def test_m14payout_groups_status_survives_cleanup(self, m14_bi_summary):
        """payout_groups_status under M14 player_impact must survive cleanup."""
        pi = m14_bi_summary.get("player_impact", {})
        assert "payout_groups_status" in pi, (
            "payout_groups_status was deleted from M14 player_impact by the cleanup loop."
        )
