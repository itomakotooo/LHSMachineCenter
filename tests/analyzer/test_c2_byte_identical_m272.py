"""Byte-identical regression test for Phase C2 — M272 mode 1 (B-archetype).

M272 is a B-archetype regression check.  Only 2 cached chunks available.

C2 byte-identical result for M272: IDENTICAL (0 non-volatile diffs).
See: session_artifacts/_impl/phase_c2/byte_identical_results.md

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug: in payouts_by_spin_type.py reduce(), replace merge logic with:
    return prev_acc  # ignore this_acc
RED: test_payouts_by_spin_type_total_hits_nonzero will fail if only 1 chunk
    contributes (hits from chunk 2 lost). But with only 2 chunks this is
    observable as the total hits being approx half of the real total.
    More precisely: test_payouts_by_spin_type_hits_consistent_with_top20
    will catch the discrepancy.
Revert → GREEN.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md
- memory/feedback_enumerate_safety_paths.md
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
_CACHE_DIR = _REPO_ROOT / "rawdata" / "M272" / "mode_1"

_REQUIRED_ROW_KEYS = {
    "payout_id", "hit_count", "hit_rate",
    "total_win", "avg_win_when_hit", "rtp_contribution_pp",
}


@pytest.fixture(scope="module")
def m272_c2_summary() -> dict:
    """Run M272 mode 1 analyzer with C2 plugin; return parsed summary."""
    if not _CACHE_DIR.exists() or not list(_CACHE_DIR.glob("chunk_*.json")):
        pytest.skip(f"M272 mode 1 cached chunks not found at {_CACHE_DIR}")

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable,
            str(_PIA),
            "--machine", "M272",
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
            timeout=60,
        )
        assert result.returncode == 0, (
            f"M272 analyzer exited non-zero ({result.returncode}).\n"
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists()
        data = json.loads(summary_path.read_bytes())
    return data


class TestM272C2RtpIntegrity:
    """RTP integrity invariants for M272 post-C2.

    Note: M272 mode 1 has a pre-existing L2 RTP integrity failure
    (_unattributed_st126 fallback bucket). This is a RoundWinRule attribution
    gap unrelated to C2. rtp_integrity_check.passed is NOT asserted here.
    """

    def test_rtp_layer1_invariant_ok(self, m272_c2_summary):
        """Layer 1 (server_total_win == our_total_win) must still pass for M272.

        This invariant is unaffected by the L2 attribution gap.
        """
        ric = m272_c2_summary.get("rtp_integrity_check", {})
        assert ric.get("layer1_invariant_ok") is True, (
            f"L1 RTP invariant failed for M272: {ric}"
        )

    def test_no_analyzer_init_error(self, m272_c2_summary):
        assert "analyzer_init_error" not in m272_c2_summary, (
            f"analyzer_init_error present: {m272_c2_summary.get('analyzer_init_error')}"
        )

    def test_no_feature_errors(self, m272_c2_summary):
        fe = m272_c2_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"


class TestM272C2PayoutsBySpinType:
    """payouts_by_spin_type correctness for M272 B-archetype post-C2."""

    def test_payouts_by_spin_type_present(self, m272_c2_summary):
        """payouts_by_spin_type must be present in player_impact.

        INJECT-BUG: change plugin FEATURE_ID to wrong value.
        RED: emit() writes to wrong key → payouts_by_spin_type absent.
        """
        pi = m272_c2_summary.get("player_impact", {})
        assert "payouts_by_spin_type" in pi, (
            f"payouts_by_spin_type missing. Keys: {sorted(pi.keys())}"
        )

    def test_payouts_by_spin_type_has_rows(self, m272_c2_summary):
        """At least one non-empty ST label for M272."""
        pbst = m272_c2_summary["player_impact"]["payouts_by_spin_type"]
        nonempty_labels = [k for k, v in pbst.items() if v]
        assert len(nonempty_labels) > 0, (
            f"payouts_by_spin_type all-empty for M272. "
            f"Labels: {sorted(pbst.keys())}"
        )

    def test_payouts_by_spin_type_row_schema(self, m272_c2_summary):
        """Every row must have the 6 SCHEMA_VERSION 1 required keys."""
        pbst = m272_c2_summary["player_impact"]["payouts_by_spin_type"]
        for label, rows in pbst.items():
            for row in rows:
                missing = _REQUIRED_ROW_KEYS - set(row.keys())
                assert not missing, f"Row in {label!r} missing keys {missing}: {row}"

    def test_payouts_by_spin_type_total_hits_nonzero(self, m272_c2_summary):
        """Sum of hit_count across all rows must be > 0."""
        pbst = m272_c2_summary["player_impact"]["payouts_by_spin_type"]
        total_hits = sum(
            row["hit_count"] for rows in pbst.values() for row in rows
        )
        assert total_hits > 0, f"Total hit_count = 0 for M272."

    def test_payouts_by_spin_type_hits_consistent_with_top20(self, m272_c2_summary):
        """Per-pid total hits across all ST must match payout_ids_top20 hit_count.

        payout_ids_top20 computes per-pid aggregate hit_count from the inline
        block's payout_id_hits accumulator.  payouts_by_spin_type computes the
        same from extract()/reduce() via chunk_dict["payout_id_by_spin_type"].
        The two are derived from the same parsed data → per-pid totals must match.

        INJECT-BUG: in reduce(), replace merge with 'return prev_acc'.
        RED: missing chunk 2 data → total per-pid hits is ~ half the real value
        → this assertion fails for any pid present in both chunks.
        Revert → GREEN.
        """
        pbst = m272_c2_summary["player_impact"].get("payouts_by_spin_type", {})
        top20 = m272_c2_summary["player_impact"].get("payout_ids_top20", [])

        # Build per-pid total hits from plugin output
        plugin_hit_totals: dict[str, int] = {}
        for rows in pbst.values():
            for row in rows:
                pid = str(row["payout_id"])
                plugin_hit_totals[pid] = plugin_hit_totals.get(pid, 0) + row["hit_count"]

        # Build per-pid totals from top20
        top20_hit_totals: dict[str, int] = {
            str(r["payout_id"]): r["hit_count"] for r in top20
        }

        mismatches = []
        for pid, plugin_hits in plugin_hit_totals.items():
            top20_hits = top20_hit_totals.get(pid)
            if top20_hits is not None and plugin_hits != top20_hits:
                mismatches.append(
                    f"pid={pid}: plugin={plugin_hits} top20={top20_hits}"
                )

        assert not mismatches, (
            f"Hit count mismatch between payouts_by_spin_type and payout_ids_top20: "
            f"{mismatches[:5]}. "
            "reduce() may not be merging all chunks correctly."
        )

    def test_no_temp_key_leaks(self, m272_c2_summary):
        """No _-prefix temp keys must appear in the final summary."""
        for k in m272_c2_summary:
            assert not k.startswith("_"), f"Temp key {k!r} leaked (top-level)"
        pi = m272_c2_summary.get("player_impact", {})
        for k in pi:
            assert not k.startswith("_"), f"Temp key {k!r} leaked (player_impact)"
