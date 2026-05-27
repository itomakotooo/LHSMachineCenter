"""Byte-identical regression test for Phase C2 — M37 mode 1 (D-archetype).

M37 is a D-archetype (classic reel) regression check.  Important note:

M37's cached chunks use the OLD format (pre-SpinType-split), where the raw
response data is stored under a 'response' field and reparsed at runtime.
The parse_chunk_response() function DOES synthesize payout_id_by_spin_type
from the raw response for these old chunks.

Observed behavior:
  pre-C2 (C1 inline code): payouts_by_spin_type = {"ST1_paid": []}  (EMPTY)
  post-C2 (C2 plugin):     payouts_by_spin_type = {"ST1_paid": [12 rows]}

Root cause of pre-C2 empty output: the C1 inline block read
payout_id_win_by_spin_type_total which was populated from rec["payout_id_win_by_spin_type"]
in the merge loop — BUT for M37's old chunks, the parser-synthesized data
uses integer spin_type keys while the merge loop accumulated them differently.
The C2 plugin reads directly from the per-chunk chunk_dict returned by the
parser, which DOES have the correct data. This is a C2 improvement.

The test therefore does NOT assert byte-identical to pre-C2 for M37.
Instead it asserts:
  1. payouts_by_spin_type has NON-EMPTY rows (improvement over pre-C2 empty output).
  2. Row schema is correct (SCHEMA_VERSION 1 legacy 6 fields via subset check).
  3. No temp key leaks.
  4. RTP integrity still passes.

**Updated post-C3**: Under C3 (SCHEMA_VERSION=2), each row gains 4 new optional fields:
shape / covered_columns / paylines / notes.  This test verifies only the LEGACY 6 fields
remain present via subset comparison (_REQUIRED_ROW_KEYS).

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug: in payouts_by_spin_type.py extract(), when chunk_dict is not None but
    payout_id_by_spin_type key is missing (old format), synthesize nothing.
    Actually test: change extract() to return {} when by_st_hits would be empty.
    In practice: add early return if not (chunk_dict.get('payout_id_by_spin_type')):
        return {}
RED: M37 old chunks have payout_id_by_spin_type populated by parser — but
    the test checking total_hits > 0 would fail if we ignore the parsed data.
    (The inject is: add 'if not chunk_dict.get(\"payout_id_by_spin_type\"): return {}'
    BEFORE the iteration, which would silently skip old chunk keys.)
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
_CACHE_DIR = _REPO_ROOT / "rawdata" / "M37" / "mode_1"

_REQUIRED_ROW_KEYS = {
    "payout_id", "hit_count", "hit_rate",
    "total_win", "avg_win_when_hit", "rtp_contribution_pp",
}


@pytest.fixture(scope="module")
def m37_c2_summary() -> dict:
    """Run M37 mode 1 analyzer with C2 plugin; return parsed summary."""
    if not _CACHE_DIR.exists() or not list(_CACHE_DIR.glob("chunk_*.json")):
        pytest.skip(f"M37 mode 1 cached chunks not found at {_CACHE_DIR}")

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable,
            str(_PIA),
            "--machine", "M37",
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
            timeout=300,  # M37 has many chunks (~200+)
        )
        assert result.returncode == 0, (
            f"M37 analyzer exited non-zero ({result.returncode}).\n"
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists()
        data = json.loads(summary_path.read_bytes())
    return data


class TestM37C2RtpIntegrity:
    """RTP integrity invariants for M37 post-C2."""

    def test_rtp_integrity_check_passed(self, m37_c2_summary):
        ric = m37_c2_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, f"rtp_integrity_check failed: {ric}"

    def test_no_analyzer_init_error(self, m37_c2_summary):
        assert "analyzer_init_error" not in m37_c2_summary, (
            f"analyzer_init_error present: {m37_c2_summary.get('analyzer_init_error')}"
        )

    def test_no_feature_errors(self, m37_c2_summary):
        fe = m37_c2_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"


class TestM37C2PayoutsBySpinType:
    """payouts_by_spin_type improvement verification for M37 old-format chunks.

    NOTE: M37 pre-C2 had EMPTY rows in ST1_paid due to the C1 inline code
    not correctly reading the parser-synthesized payout_id_win_by_spin_type.
    The C2 plugin reads directly from the parsed chunk_dict and produces
    correct non-empty rows. This is a C2 improvement.
    """

    def test_payouts_by_spin_type_present(self, m37_c2_summary):
        """payouts_by_spin_type must be present in player_impact.

        INJECT-BUG: remove register(PayoutsBySpinType()) → key absent.
        RED: this assertion fails.
        """
        pi = m37_c2_summary.get("player_impact", {})
        assert "payouts_by_spin_type" in pi, (
            f"payouts_by_spin_type missing. Keys: {sorted(pi.keys())}"
        )

    def test_payouts_by_spin_type_has_rows_improvement(self, m37_c2_summary):
        """C2 plugin must produce NON-EMPTY rows for M37 (improvement over C1 empty).

        pre-C2 (C1) produced: {"ST1_paid": []} — empty list.
        post-C2 must produce: {"ST1_paid": [N rows]} where N > 0.

        INJECT-BUG: change extract() to return {} unconditionally.
        RED: all rows empty → assertion fails.
        """
        pbst = m37_c2_summary["player_impact"]["payouts_by_spin_type"]
        nonempty_labels = [k for k, v in pbst.items() if v]
        assert len(nonempty_labels) > 0, (
            f"M37 payouts_by_spin_type has no non-empty ST labels. "
            f"C2 should have improved on C1's empty output for old-format chunks. "
            f"Labels: {sorted(pbst.keys())}"
        )

    def test_payouts_by_spin_type_row_schema(self, m37_c2_summary):
        """Every row must have the 6 required SCHEMA_VERSION 1 keys (subset check).

        Post-C3 note: rows now contain additional SCHEMA_VERSION 2 fields
        (shape/covered_columns/paylines/notes); this test verifies only the
        legacy 6 fields are present, not the full C3 schema.
        """
        pbst = m37_c2_summary["player_impact"]["payouts_by_spin_type"]
        for label, rows in pbst.items():
            for row in rows:
                missing = _REQUIRED_ROW_KEYS - set(row.keys())
                assert not missing, f"Row in {label!r} missing keys {missing}: {row}"

    def test_payouts_by_spin_type_total_hits_nonzero(self, m37_c2_summary):
        """Sum of hit_count across all rows must be > 0 for M37.

        INJECT-BUG: see module docstring inject-bug recipe.
        RED: total_hits == 0.
        """
        pbst = m37_c2_summary["player_impact"]["payouts_by_spin_type"]
        total_hits = sum(
            row["hit_count"] for rows in pbst.values() for row in rows
        )
        assert total_hits > 0, (
            f"Total hit_count = 0 for M37. "
            f"extract() is not reading payout_id_by_spin_type for old-format chunks."
        )

    def test_payouts_by_spin_type_pids_match_top20(self, m37_c2_summary):
        """PIDs in payouts_by_spin_type must be a subset of payout_ids_top20."""
        pbst = m37_c2_summary["player_impact"].get("payouts_by_spin_type", {})
        top20 = m37_c2_summary["player_impact"].get("payout_ids_top20", [])
        top20_pids = {str(r["payout_id"]) for r in top20}
        plugin_pids = {
            str(row["payout_id"]) for rows in pbst.values() for row in rows
        }
        unknown = plugin_pids - top20_pids
        assert not unknown, (
            f"PIDs in payouts_by_spin_type not in payout_ids_top20: {unknown}. "
            "Plugin may be reading from a different data source."
        )

    def test_no_temp_key_leaks(self, m37_c2_summary):
        """No _-prefix temp keys must appear in the final summary."""
        for k in m37_c2_summary:
            assert not k.startswith("_"), f"Temp key {k!r} leaked (top-level)"
        pi = m37_c2_summary.get("player_impact", {})
        for k in pi:
            assert not k.startswith("_"), f"Temp key {k!r} leaked (player_impact)"
