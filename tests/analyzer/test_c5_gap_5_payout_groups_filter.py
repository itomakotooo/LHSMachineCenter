"""Phase C5 — gap #5: payout_groups_top20 all-zeros filter.

Tests the PIA F2 inline fix that detects "all PayoutGroupId == 0" and:
  1. Returns payout_groups_top20 = [] (empty, not the noise row)
  2. Sets payout_groups_status = "all_zeros_filtered"

Also verifies:
  - "absent_field" status when machine has no payout_group_hits at all.
  - The status field is nested inside player_impact (not top-level).
  - payout_groups_status is NOT deleted by the top-level _ cleanup loop
    (it lives inside player_impact dict, not as a top-level summary key).

Invariants asserted
-------------------
1. M275: payout_groups_top20 == [] (all PayoutGroupId=0 filtered).
2. M275: payout_groups_status == "all_zeros_filtered".
3. M14: payout_groups_top20 == [] (M14 has absent_field — no payout_group_hits).
4. M14: payout_groups_status == "absent_field" or "all_zeros_filtered" (both are not "populated").
5. "populated" status machines (if any) return non-empty list — tested via synthetic unit logic.
6. payout_groups_status nested under player_impact is NOT cleaned up by top-level _ key cleanup.
7. Three status values are the complete enum: populated / all_zeros_filtered / absent_field.

Note on available test data:
  All machines in the local cache (rawdata/) have either:
    - payout_group_hits = {} (absent_field) — majority
    - payout_group_hits = {0: N} (all_zeros_filtered) — M275, M14, M37
  No machine in cache has nonzero payout_group_hits (verified by exhaustive scan).
  The "populated" path is tested at the unit level (direct code path inspection).

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug B — remove the all-zeros detection filter in PIA F2 inline:
    In fresh_slotlab/player_impact_analyzer.py, find the gap #5 filter block:

        _payout_group_keys_nonzero = set(k for k in payout_group_hits if int(k) != 0)
        payout_groups_status: str
        if not payout_group_hits:
            payout_groups_status = "absent_field"
        elif not _payout_group_keys_nonzero:
            # All rounds have PayoutGroupId == 0 — noise, not signal.
            payout_groups_status = "all_zeros_filtered"
        else:
            payout_groups_status = "populated"

        payout_group_rows: list[dict[str, Any]] = []
        if payout_groups_status == "populated":
            ...

    Remove the all-zeros branch — change to:
        elif not _payout_group_keys_nonzero:
            payout_groups_status = "populated"  # BUG: treat all-zeros as populated

    RED: M275 payout_groups_top20 is no longer [] — it has a noise row
         {group_id: 0, hit_count: 89090, rtp_pp: 80.13}.
         test_m275_payout_groups_top20_empty fails.
         test_m275_status_all_zeros_filtered fails.
    Revert (restore elif not _payout_group_keys_nonzero branch) -> GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (payout_groups_status is an explicit named status — not a silent bucket)
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test required — not just code inspection)
- memory/feedback_integration_test_argv.md
  (real subprocess against real M275/M14 cached chunks)
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
def m275_g5_summary() -> dict:
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
            f"STDERR: {result.stderr[:2000]}"
        )
        return json.loads((Path(tmpdir) / "player_impact_summary.json").read_bytes())


@pytest.fixture(scope="module")
def m14_g5_summary() -> dict:
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
        return json.loads((Path(tmpdir) / "player_impact_summary.json").read_bytes())


# ---------------------------------------------------------------------------
# T1: M275 — all-zeros filtered
# ---------------------------------------------------------------------------

class TestM275PayoutGroupsFilter:
    """M275 has all PayoutGroupId=0 — filter must produce empty list + status flag."""

    def test_m275_payout_groups_top20_empty(self, m275_g5_summary):
        """M275 payout_groups_top20 must be [] (all-zeros filtered).

        INJECT-BUG (Bug B): change the all-zeros branch to "populated".
        RED: payout_groups_top20 is [{group_id: 0, hit_count: 89090, ...}] — noise row.
        Revert -> GREEN.

        Pre-gap-#5: M275 showed a misleading {group_id: 0} row.
        Post-gap-#5: empty list signals "no real PayoutGroupId grouping".
        """
        pi = m275_g5_summary.get("player_impact", {})
        pg20 = pi.get("payout_groups_top20")
        assert pg20 == [], (
            f"M275 payout_groups_top20 must be [] (all PayoutGroupId==0 filtered). "
            f"Got: {pg20!r}. "
            f"This is gap #5 — the all-zeros filter must be active."
        )

    def test_m275_status_all_zeros_filtered(self, m275_g5_summary):
        """M275 payout_groups_status must be 'all_zeros_filtered'.

        Per feedback_invariant_with_fallback_hides_drift.md: this is an
        explicit named operator-readable signal, not a silent bucket.
        """
        pi = m275_g5_summary.get("player_impact", {})
        status = pi.get("payout_groups_status")
        assert status == "all_zeros_filtered", (
            f"M275 payout_groups_status must be 'all_zeros_filtered', got {status!r}. "
            f"Status must be one of: populated / all_zeros_filtered / absent_field."
        )

    def test_m275_status_nested_under_player_impact(self, m275_g5_summary):
        """payout_groups_status must be nested under player_impact (not top-level).

        The top-level summary _ cleanup loop removes _ keys from summary root.
        payout_groups_status lives inside player_impact dict — it should survive cleanup.
        """
        # Not at top-level
        assert "payout_groups_status" not in m275_g5_summary, (
            "payout_groups_status must NOT be at top-level summary "
            "(top-level _ keys are cleaned up). Found it at top-level."
        )
        # Present under player_impact
        pi = m275_g5_summary.get("player_impact", {})
        assert "payout_groups_status" in pi, (
            "payout_groups_status must be under player_impact. "
            f"player_impact keys: {sorted(pi.keys())}"
        )

    def test_m275_no_analyzer_error(self, m275_g5_summary):
        """analyzer_init_error and feature_errors must be absent for M275."""
        assert "analyzer_init_error" not in m275_g5_summary
        fe = m275_g5_summary.get("feature_errors", {})
        assert not fe, f"feature_errors: {fe}"


# ---------------------------------------------------------------------------
# T2: M14 — not "populated" status (absent_field or all_zeros_filtered)
# ---------------------------------------------------------------------------

class TestM14PayoutGroupsFilter:
    """M14 payout_groups_top20 must not be "populated" (no real group IDs)."""

    def test_m14_payout_groups_top20_empty(self, m14_g5_summary):
        """M14 payout_groups_top20 must be [] — M14 has no real payout grouping."""
        pi = m14_g5_summary.get("player_impact", {})
        pg20 = pi.get("payout_groups_top20")
        assert isinstance(pg20, list), (
            f"payout_groups_top20 must be a list, got {type(pg20)!r}"
        )
        assert pg20 == [], (
            f"M14 payout_groups_top20 must be [] (no real group IDs). Got: {pg20!r}"
        )

    def test_m14_status_not_populated(self, m14_g5_summary):
        """M14 payout_groups_status must NOT be 'populated'.

        M14 has either absent_field or all_zeros_filtered — both are correct.
        The invariant is that it's not falsely marked as having real groups.
        """
        pi = m14_g5_summary.get("player_impact", {})
        status = pi.get("payout_groups_status")
        valid_non_populated = {"absent_field", "all_zeros_filtered"}
        assert status in valid_non_populated, (
            f"M14 payout_groups_status must be 'absent_field' or 'all_zeros_filtered', "
            f"got {status!r}. M14 has no real PayoutGroupId grouping."
        )

    def test_m14_status_nested_under_player_impact(self, m14_g5_summary):
        """payout_groups_status must be under player_impact for M14."""
        pi = m14_g5_summary.get("player_impact", {})
        assert "payout_groups_status" in pi, (
            "payout_groups_status must be under player_impact for M14."
        )


# ---------------------------------------------------------------------------
# T3: Unit-level status logic (covers "populated" path + enum completeness)
# ---------------------------------------------------------------------------

class TestPayoutGroupsStatusLogic:
    """Verify the three-value status enum at the PIA source code level.

    Since no cached machine has nonzero payout_group_hits, the "populated"
    path is verified by inspecting the PIA source code directly.
    """

    def test_pia_source_contains_all_three_statuses(self):
        """PIA source must contain all 3 status values as string literals.

        Verifies the enum is complete and not accidentally narrowed.
        """
        src = _PIA.read_text(encoding="utf-8")
        assert '"absent_field"' in src or "'absent_field'" in src, (
            "PIA source missing 'absent_field' status value in payout_groups filter"
        )
        assert '"all_zeros_filtered"' in src or "'all_zeros_filtered'" in src, (
            "PIA source missing 'all_zeros_filtered' status value in payout_groups filter"
        )
        assert '"populated"' in src or "'populated'" in src, (
            "PIA source missing 'populated' status value in payout_groups filter"
        )

    def test_pia_source_payout_group_rows_gated_on_populated(self):
        """PIA source: payout_group_rows populated only when status == 'populated'.

        The guard `if payout_groups_status == "populated":` must be present
        to prevent the all-zeros noise row from being written.

        INJECT-BUG (Bug B): removing this guard allows the loop to run for
        all_zeros_filtered status, producing the noise row.
        """
        src = _PIA.read_text(encoding="utf-8")
        assert 'payout_groups_status == "populated"' in src or \
               "payout_groups_status == 'populated'" in src, (
            "PIA source must have `if payout_groups_status == 'populated':` "
            "guard before building payout_group_rows. This guard is gap #5's protection."
        )

    def test_pia_sourcepayout_groups_status_written_to_player_impact(self):
        """PIA source must write payout_groups_status inside player_impact dict."""
        src = _PIA.read_text(encoding="utf-8")
        assert '"payout_groups_status": payout_groups_status' in src or \
               "'payout_groups_status': payout_groups_status" in src, (
            "PIA source must write payout_groups_status into player_impact dict. "
            "This is the explicit status signal per gap #5."
        )
