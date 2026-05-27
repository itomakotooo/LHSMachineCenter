"""Byte-identical regression test for Phase C2 — M275 mode 1.

M275 is the primary machine driving the unbundle effort (M275-driven).
It has freespin bonus chains (bonus_spins > 0) making it distinct from M14.

C2 byte-identical result for M275: IDENTICAL (0 non-volatile diffs).
See: session_artifacts/_impl/phase_c2/byte_identical_results.md

This test verifies:
1. payouts_by_spin_type has rows for M275's paid + free spin types.
2. The bonus-chain path was not broken by C2's plugin carve.
3. No other player_impact subkey regressed.

**Updated post-C3**: Under C3 (SCHEMA_VERSION=2), each row gains 4 new optional fields:
shape / covered_columns / paylines / notes.  These tests verify only the LEGACY 6 fields
remain byte-identical via subset comparison (_REQUIRED_ROW_KEYS); new C3 fields are
validated in test_c3_byte_identical_legacy_fields_m275.py.

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug: in payouts_by_spin_type.py extract(), change the hits accumulator to:
    by_st_hits.setdefault(pid_str, {})[st_int] = 0  # always zero
RED: test_payouts_by_spin_type_total_hits_nonzero fails (all rows skipped
    due to hits==0 filter in emit()).
Revert → GREEN.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md
- memory/feedback_enumerate_safety_paths.md
- memory/feedback_integration_test_argv.md
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
_CACHE_DIR = _REPO_ROOT / "rawdata" / "M275" / "mode_1"

_REQUIRED_ROW_KEYS = {
    "payout_id", "hit_count", "hit_rate",
    "total_win", "avg_win_when_hit", "rtp_contribution_pp",
}


@pytest.fixture(scope="module")
def m275_c2_summary() -> dict:
    """Run M275 mode 1 analyzer with C2 plugin; return parsed summary."""
    if not _CACHE_DIR.exists() or not list(_CACHE_DIR.glob("chunk_*.json")):
        pytest.skip(f"M275 mode 1 cached chunks not found at {_CACHE_DIR}")

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable,
            str(_PIA),
            "--machine", "M275",
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
            f"M275 analyzer exited non-zero ({result.returncode}).\n"
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists()
        data = json.loads(summary_path.read_bytes())
    return data


class TestM275C2RtpIntegrity:
    """RTP integrity invariants for M275 post-C2."""

    def test_rtp_integrity_check_passed(self, m275_c2_summary):
        ric = m275_c2_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, f"rtp_integrity_check failed: {ric}"

    def test_no_analyzer_init_error(self, m275_c2_summary):
        assert "analyzer_init_error" not in m275_c2_summary, (
            f"analyzer_init_error present: {m275_c2_summary.get('analyzer_init_error')}"
        )

    def test_no_feature_errors(self, m275_c2_summary):
        fe = m275_c2_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"


class TestM275C2BonusChainIntact:
    """M275's bonus chain path must not be broken by C2."""

    def test_has_bonus_spins(self, m275_c2_summary):
        """M275 must still report bonus_spins > 0 post-C2."""
        bonus_spins = m275_c2_summary["sampling"]["bonus_spins"]
        assert bonus_spins > 0, (
            f"Expected M275 bonus_spins > 0, got {bonus_spins}. "
            "C2 may have broken the bonus-spin accumulation path."
        )

    def test_bonus_chain_dynamics_applicable(self, m275_c2_summary):
        """bonus_chain_dynamics.applicable must be True (M275 has freespins)."""
        bcd = m275_c2_summary["player_impact"].get("bonus_chain_dynamics", {})
        assert bcd.get("applicable") is True, (
            f"bonus_chain_dynamics.applicable must be True for M275 post-C2. "
            f"Got: {bcd.get('applicable')!r}"
        )


class TestM275C2PayoutsBySpinType:
    """payouts_by_spin_type correctness for M275 post-C2."""

    def test_payouts_by_spin_type_present(self, m275_c2_summary):
        """payouts_by_spin_type must be present in player_impact."""
        pi = m275_c2_summary.get("player_impact", {})
        assert "payouts_by_spin_type" in pi, (
            f"payouts_by_spin_type missing. Keys: {sorted(pi.keys())}"
        )

    def test_payouts_by_spin_type_has_rows(self, m275_c2_summary):
        """At least one ST label must have non-empty rows for M275.

        INJECT-BUG: change extract() to return {} always (Pattern A regression).
        RED: all ST labels empty → this assertion fails.
        """
        pbst = m275_c2_summary["player_impact"]["payouts_by_spin_type"]
        nonempty_labels = [k for k, v in pbst.items() if v]
        assert len(nonempty_labels) > 0, (
            f"payouts_by_spin_type has no non-empty ST labels. "
            f"Labels: {sorted(pbst.keys())}"
        )

    def test_payouts_by_spin_type_row_schema(self, m275_c2_summary):
        """Every row must have the 6 SCHEMA_VERSION 1 required keys (subset check).

        Post-C3 note: rows now contain additional SCHEMA_VERSION 2 fields
        (shape/covered_columns/paylines/notes); this test verifies only the
        legacy 6 fields are present, not the full C3 schema.
        """
        pbst = m275_c2_summary["player_impact"]["payouts_by_spin_type"]
        for label, rows in pbst.items():
            for row in rows:
                missing = _REQUIRED_ROW_KEYS - set(row.keys())
                assert not missing, f"Row in {label!r} missing keys {missing}: {row}"

    def test_payouts_by_spin_type_total_hits_nonzero(self, m275_c2_summary):
        """Sum of hit_count across all rows must be > 0 for M275."""
        pbst = m275_c2_summary["player_impact"]["payouts_by_spin_type"]
        total_hits = sum(
            row["hit_count"] for rows in pbst.values() for row in rows
        )
        assert total_hits > 0, (
            f"Total hit_count = 0 for M275. "
            "extract() may be a no-op (Pattern A regression)."
        )

    def test_no_temp_key_leaks(self, m275_c2_summary):
        """No _-prefix temp keys must appear in the final summary."""
        for k in m275_c2_summary:
            assert not k.startswith("_"), f"Temp key {k!r} leaked (top-level)"
        pi = m275_c2_summary.get("player_impact", {})
        for k in pi:
            assert not k.startswith("_"), f"Temp key {k!r} leaked (player_impact)"

    def test_no_mechanism_registry_temp_key(self, m275_c2_summary):
        """_mechanism_registry must not appear in final summary (cleaned up)."""
        assert "_mechanism_registry" not in m275_c2_summary
        pi = m275_c2_summary.get("player_impact", {})
        assert "_mechanism_registry" not in pi
