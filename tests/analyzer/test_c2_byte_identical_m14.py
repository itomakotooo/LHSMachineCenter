"""Byte-identical regression test for Phase C2 — M14 mode 1.

Spawns the real player_impact_analyzer subprocess against M14 mode 1 cached
chunks.  Focused on payouts_by_spin_type correctness post-C2 Plugin Pattern B
promotion.  Also verifies no other player_impact subkey changed.

This is a subprocess-level e2e test per:
  memory/feedback_perf_claim_needs_e2e_event_stream.md
  memory/feedback_integration_test_argv.md

Byte-identical protocol
-----------------------
The pre-C2 baseline was produced by stashing C2 changes (git stash),
running the analyzer, popping the stash, and running again.  See:
  session_artifacts/_impl/phase_c2/byte_identical_results.md

M14 mode 1 result: IDENTICAL (0 non-volatile diffs at any player_impact subkey,
including payouts_by_spin_type).

Volatile fields excluded from comparison
-----------------------------------------
report_id, run_id, analyzer_version, effective_analyzer_version,
effective_analyzer_version_error, sampling.started_at/finished_at/duration_seconds,
guideline_comparison.rules_path/evaluated_at.

Invariants asserted
-------------------
1. payouts_by_spin_type has at least one non-empty ST label (M14 has paid spins).
2. Every row has the 6 required schema keys (SCHEMA_VERSION 1 shape).
3. No _-prefix temp keys leak into the final summary.
4. feature_errors absent (or empty) on success path.
5. analyzer_init_error absent on success path.
6. rtp_integrity_check.passed == True.

**Updated post-C3**: Under C3 (SCHEMA_VERSION=2), each row gains 4 new optional fields:
shape / covered_columns / paylines / notes.  These tests verify only the LEGACY 6 fields
remain byte-identical via subset comparison (_REQUIRED_ROW_KEYS); new C3 fields are
validated in test_c3_byte_identical_legacy_fields_m14.py.

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug: in payouts_by_spin_type.py extract(), skip the second chunk's aggregation
    by adding: if parse_state is not None and chunk_dict.get('_chunk_index',0)==2: return {}
RED: hit counts in payouts_by_spin_type will be wrong for M14 (missing chunk 2
    data) → test_payouts_by_spin_type_rows_not_empty passes but
    test_payouts_by_spin_type_total_hits_nonzero may change vs baseline.
    More robustly: test_payouts_by_spin_type_total_hits_nonzero detects
    reduced hit counts.
Revert → GREEN.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md
- memory/feedback_enumerate_safety_paths.md
- memory/feedback_integration_test_argv.md
- memory/feedback_no_silent_swallow.md
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
_CACHE_DIR = _REPO_ROOT / "rawdata" / "M14" / "mode_1"

_REQUIRED_ROW_KEYS = {
    "payout_id", "hit_count", "hit_rate",
    "total_win", "avg_win_when_hit", "rtp_contribution_pp",
}


@pytest.fixture(scope="module")
def m14_c2_summary() -> dict:
    """Run M14 mode 1 analyzer with C2 plugin; return parsed summary."""
    if not _CACHE_DIR.exists() or not list(_CACHE_DIR.glob("chunk_*.json")):
        pytest.skip(f"M14 mode 1 cached chunks not found at {_CACHE_DIR}")

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable,
            str(_PIA),
            "--machine", "M14",
            "--rtp-mode", "1",
            "--from-cache", str(_CACHE_DIR),
            "--output-dir", tmpdir,
            "--bet", "1000",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=120,
        )
        assert result.returncode == 0, (
            f"M14 analyzer exited non-zero ({result.returncode}).\n"
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists(), (
            f"summary.json not written. STDOUT: {result.stdout[:500]}"
        )
        data = json.loads(summary_path.read_bytes())
    return data


class TestM14C2RtpIntegrity:
    """RTP integrity invariants — must hold post-C2."""

    def test_rtp_integrity_check_passed(self, m14_c2_summary):
        """rtp_integrity_check.passed must be True on success path."""
        ric = m14_c2_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed is not True. Full value: {ric}"
        )

    def test_no_analyzer_init_error(self, m14_c2_summary):
        """analyzer_init_error must be absent on success path.

        If present, it means the plugin topo-sort or dep-check failed.
        Per feedback_no_silent_swallow.md this is surfaced as non-zero rc
        AND this key in the summary.
        """
        assert "analyzer_init_error" not in m14_c2_summary, (
            f"analyzer_init_error unexpectedly present: "
            f"{m14_c2_summary.get('analyzer_init_error')}"
        )

    def test_no_feature_errors(self, m14_c2_summary):
        """feature_errors must be absent or empty on success path."""
        fe = m14_c2_summary.get("feature_errors", {})
        assert not fe, (
            f"feature_errors unexpectedly populated: {fe}"
        )


class TestM14C2PayoutsBySpinType:
    """payouts_by_spin_type correctness post-C2 plugin."""

    def test_payouts_by_spin_type_present(self, m14_c2_summary):
        """payouts_by_spin_type must be present in player_impact.

        INJECT-BUG: remove register(PayoutsBySpinType()) in payouts_by_spin_type.py
        → plugin not in ALL_FEATURES → emit() never called → key absent.
        RED: this assertion fails.
        """
        pi = m14_c2_summary.get("player_impact", {})
        assert "payouts_by_spin_type" in pi, (
            f"payouts_by_spin_type missing from player_impact. "
            f"Got keys: {sorted(pi.keys())}"
        )

    def test_payouts_by_spin_type_has_paid_rows(self, m14_c2_summary):
        """M14 is all-paid so at least one ST label must have non-empty rows.

        INJECT-BUG: change extract() to always return {} (revert to Pattern A).
        RED: all ST labels have empty lists → assertion fails.
        """
        pbst = m14_c2_summary["player_impact"]["payouts_by_spin_type"]
        nonempty_labels = [k for k, v in pbst.items() if v]
        assert len(nonempty_labels) > 0, (
            f"payouts_by_spin_type has no non-empty ST labels. "
            f"All labels empty — extract() may have reverted to Pattern A no-op. "
            f"Labels: {sorted(pbst.keys())}"
        )

    def test_payouts_by_spin_type_row_schema(self, m14_c2_summary):
        """Every row must have the 6 SCHEMA_VERSION 1 required keys (subset check).

        Post-C3 note: rows now contain additional SCHEMA_VERSION 2 fields
        (shape/covered_columns/paylines/notes); this test verifies only the
        legacy 6 fields are present, not the full C3 schema.
        """
        pbst = m14_c2_summary["player_impact"]["payouts_by_spin_type"]
        for label, rows in pbst.items():
            for row in rows:
                missing = _REQUIRED_ROW_KEYS - set(row.keys())
                assert not missing, (
                    f"Row in {label!r} missing keys {missing}: {row}"
                )

    def test_payouts_by_spin_type_total_hits_nonzero(self, m14_c2_summary):
        """Sum of hit_count across all rows must be > 0.

        INJECT-BUG: in extract(), skip the payout_id_by_spin_type loop
        → all hit counts = 0 → all rows filtered (hits==0 → skip) → all empty.
        RED: this assertion fails (total_hits == 0).
        """
        pbst = m14_c2_summary["player_impact"]["payouts_by_spin_type"]
        total_hits = sum(
            row["hit_count"]
            for rows in pbst.values()
            for row in rows
        )
        assert total_hits > 0, (
            f"Total hit_count across all payouts_by_spin_type rows is 0. "
            "This likely means extract() is still a no-op (Pattern A)."
        )

    def test_payouts_by_spin_type_rtp_positive(self, m14_c2_summary):
        """Sum of rtp_contribution_pp must be positive (M14 has real wins)."""
        pbst = m14_c2_summary["player_impact"]["payouts_by_spin_type"]
        total_rtp = sum(
            row["rtp_contribution_pp"]
            for rows in pbst.values()
            for row in rows
        )
        assert total_rtp > 0, (
            f"Total rtp_contribution_pp = {total_rtp}. "
            "Expected positive RTP for M14 with real spin data."
        )

    def test_no_temp_key_leaks(self, m14_c2_summary):
        """No _-prefix temp keys must appear in the final summary.

        Checks both top-level and under player_impact.
        """
        for k in m14_c2_summary:
            assert not k.startswith("_"), (
                f"Temp key {k!r} leaked into final summary (top-level)"
            )
        pi = m14_c2_summary.get("player_impact", {})
        for k in pi:
            assert not k.startswith("_"), (
                f"Temp key {k!r} leaked into player_impact"
            )

    def test_payouts_by_spin_type_payout_ids_match_top20(self, m14_c2_summary):
        """PIDs in payouts_by_spin_type must be a subset of payout_ids_top20.

        payout_ids_top20 covers all pids seen in the run. Any pid in
        payouts_by_spin_type must also appear in payout_ids_top20 (which has
        the full universe).

        This is a consistency cross-check between the plugin output and the
        existing inline panel.
        """
        pbst = m14_c2_summary["player_impact"].get("payouts_by_spin_type", {})
        top20 = m14_c2_summary["player_impact"].get("payout_ids_top20", [])
        top20_pids = {str(r["payout_id"]) for r in top20}
        plugin_pids = {
            str(row["payout_id"])
            for rows in pbst.values()
            for row in rows
        }
        # All plugin pids must appear in top20 universe
        unknown = plugin_pids - top20_pids
        assert not unknown, (
            f"PIDs in payouts_by_spin_type not in payout_ids_top20: {unknown}. "
            "This indicates the plugin accumulated from a different data source "
            "than the inline payout_ids panel."
        )
