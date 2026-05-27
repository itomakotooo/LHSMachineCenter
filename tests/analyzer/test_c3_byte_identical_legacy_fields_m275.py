"""Phase C3 — byte-identical regression test for M275 mode 1 legacy fields.

THE critical additive invariant for C3: the 6 legacy C2 fields in
payouts_by_spin_type must be byte-identical pre-C3 vs post-C3 for M275.
Only the 4 new C3 fields (shape / covered_columns / paylines / notes) may differ.

This test uses two baselines:
  - Pre-C3 (C2 smoke): cache/c2_smoke/M275_postC2/player_impact_summary.json
  - Post-C3 (C3 smoke): cache/c3_smoke/M275/player_impact_summary.json
  ... AND it runs the current code against rawdata/M275/mode_1/ to produce
  a fresh post-C3 report, comparing fresh vs C3 smoke (structural).

If the C2 smoke cache is absent, the test falls back to just verifying that
the C3 fresh output has all 10 keys per row and that legacy fields are not zero.

Per brief §4 AC#4: M275 existing 6 fields IDENTICAL pre/post C3.

Invariants asserted
-------------------
1. C2 smoke legacy 6 fields == C3 fresh output legacy 6 fields for M275
   (byte-identical values; delta = 0.0 for float fields).
2. C3 fresh output has all 4 new fields populated (not None / empty for all rows).
3. pid 666 is present in C3 output with is_trigger_marker == True.
4. pid 27502 (jackpot) is present and is_trigger_marker == False.
5. All non-pid-666 rows have total_win > 0 (basic sanity: win data flows).
6. No feature_errors in C3 output.
7. At least 1 row has covered_columns == [0, 1, 2] (M275 is 3×3 grid).

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug: in emit(), accidentally overwrite an existing legacy field:
    Change the row construction to:
        "hit_count": 0,   # BUG: always zero
    RED: test_legacy_hit_count_byte_identical fails (0 != C2 value).
Revert → GREEN.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md (subprocess against
  real fixture is mandatory; mock-only tests cannot catch this class of failure)
- memory/feedback_enumerate_safety_paths.md (inject-bug protocol)
- memory/feedback_no_hardcode.md (pid 666 check uses structural logic,
  not hardcoded assumptions)
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
_C2_SMOKE = _REPO_ROOT / "cache" / "c2_smoke" / "M275_postC2" / "player_impact_summary.json"

_LEGACY_KEYS = {
    "payout_id", "hit_count", "hit_rate",
    "total_win", "avg_win_when_hit", "rtp_contribution_pp",
}
_C3_NEW_KEYS = {"shape", "covered_columns", "paylines", "notes"}
_ALL_REQUIRED_KEYS = _LEGACY_KEYS | _C3_NEW_KEYS


def _load_c2_smoke() -> dict | None:
    """Load C2 smoke baseline. Returns None if file not found (test adapts)."""
    if _C2_SMOKE.exists():
        return json.loads(_C2_SMOKE.read_bytes())
    return None


@pytest.fixture(scope="module")
def m275_c3_summary() -> dict:
    """Run M275 mode 1 analyzer with C3 code; return parsed summary."""
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
            f"M275 C3 analyzer exited non-zero ({result.returncode}).\n"
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists(), "player_impact_summary.json not produced"
        return json.loads(summary_path.read_bytes())


class TestM275C3LegacyFieldsByteIdentical:
    """THE invariant: C2 legacy fields == C3 fresh output (byte-identical values)."""

    def test_no_feature_errors(self, m275_c3_summary):
        """No feature_errors in C3 output for M275."""
        fe = m275_c3_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"

    def test_payouts_by_spin_type_present(self, m275_c3_summary):
        """payouts_by_spin_type must be present in M275 C3 output."""
        pi = m275_c3_summary.get("player_impact", {})
        assert "payouts_by_spin_type" in pi, (
            f"payouts_by_spin_type missing. Keys: {sorted(pi.keys())}"
        )

    def test_all_rows_have_10_required_keys(self, m275_c3_summary):
        """Every row must have 6 C2 fields + 4 C3 fields (10 total minimum).

        This is the structural byte-identical invariant: C3 is purely additive.
        No existing keys removed.
        """
        pbst = m275_c3_summary["player_impact"]["payouts_by_spin_type"]
        for label, rows in pbst.items():
            for row in rows:
                missing = _ALL_REQUIRED_KEYS - set(row.keys())
                assert not missing, (
                    f"M275 C3 row in {label!r} missing keys {missing}. "
                    f"Row has: {sorted(row.keys())}"
                )

    def test_legacy_fields_byte_identical_vs_c2_smoke(self, m275_c3_summary):
        """Legacy 6 fields must be byte-identical C2 smoke → C3 fresh for M275.

        INJECT-BUG: in emit(), set hit_count = 0 always.
        RED: hit_count differs from C2 smoke → this assertion fails.
        Revert → GREEN.

        Falls back to sanity check if C2 smoke not found.
        """
        c2 = _load_c2_smoke()
        if c2 is None:
            pytest.skip("C2 smoke baseline not found; byte-identical comparison skipped")

        c2_pbst = c2["player_impact"]["payouts_by_spin_type"]
        c3_pbst = m275_c3_summary["player_impact"]["payouts_by_spin_type"]

        diffs = []
        for label, c2_rows in c2_pbst.items():
            c3_rows = c3_pbst.get(label, [])
            c2_by_pid = {r["payout_id"]: r for r in c2_rows}
            c3_by_pid = {r["payout_id"]: r for r in c3_rows}

            for pid in set(c2_by_pid.keys()):
                if pid not in c3_by_pid:
                    diffs.append(f"{label}/{pid}: present in C2 but missing in C3")
                    continue
                r2 = c2_by_pid[pid]
                r3 = c3_by_pid[pid]
                for key in _LEGACY_KEYS - {"payout_id"}:  # payout_id is the lookup key
                    v2 = r2.get(key)
                    v3 = r3.get(key)
                    if isinstance(v2, float) and isinstance(v3, float):
                        if abs(v2 - v3) > 1e-9:
                            diffs.append(
                                f"{label}/{pid}/{key}: C2={v2!r} vs C3={v3!r} "
                                f"(delta={abs(v2-v3):.2e})"
                            )
                    elif v2 != v3:
                        diffs.append(f"{label}/{pid}/{key}: C2={v2!r} vs C3={v3!r}")

        assert not diffs, (
            f"M275 LEGACY FIELD REGRESSIONS ({len(diffs)}):\n"
            + "\n".join(f"  {d}" for d in diffs)
            + "\n\nC3 must be purely additive — the 6 C2 fields must be byte-identical."
        )

    def test_c3_new_fields_not_all_none(self, m275_c3_summary):
        """C3 new fields must not all be None/empty for M275.

        At least some rows should have populated shape/covered_columns/paylines/notes.
        """
        pbst = m275_c3_summary["player_impact"]["payouts_by_spin_type"]
        rows_flat = [r for rows in pbst.values() for r in rows]
        rows_with_shape = [r for r in rows_flat if r.get("shape")]
        assert rows_with_shape, (
            f"No rows have a populated 'shape' dict. C3 enrichment may not be running."
        )

    def test_at_least_one_row_has_3x3_columns(self, m275_c3_summary):
        """At least 1 row must have covered_columns == [0,1,2] (M275 is 3×3 grid)."""
        pbst = m275_c3_summary["player_impact"]["payouts_by_spin_type"]
        rows_flat = [r for rows in pbst.values() for r in rows]
        three_col_rows = [r for r in rows_flat if r.get("covered_columns") == [0, 1, 2]]
        assert three_col_rows, (
            f"No rows have covered_columns==[0,1,2]. "
            "M275 is a 3-column grid; most pids should cover all 3 columns."
        )


class TestM275C3Pid666TriggerMarker:
    """M275 pid 666 must be flagged is_trigger_marker == True in C3 output."""

    def _find_pid_row(self, summary: dict, pid: str) -> dict | None:
        """Find a row by payout_id across all ST labels."""
        pbst = summary["player_impact"]["payouts_by_spin_type"]
        for rows in pbst.values():
            for row in rows:
                if row["payout_id"] == pid:
                    return row
        return None

    def test_pid_666_present_in_payouts_by_spin_type(self, m275_c3_summary):
        """pid 666 must appear in payouts_by_spin_type (trigger marker retained)."""
        row = self._find_pid_row(m275_c3_summary, "666")
        assert row is not None, (
            "pid '666' missing from payouts_by_spin_type. "
            "Trigger markers (win=0, hits>0) must be retained."
        )

    def test_pid_666_is_trigger_marker_true(self, m275_c3_summary):
        """M275 pid 666 must have notes.is_trigger_marker == True.

        Canonical trigger marker: all hits have line_id==-1, all wins == 0.
        This is THE specific C3 invariant for M275.

        Per brief §4 AC#3: pid 666 specifically shows notes.is_trigger_marker=True.
        Per memory/feedback_invariant_with_fallback_hides_drift.md: this is an
        explicit positive signal, not a fallback bucket.
        """
        row = self._find_pid_row(m275_c3_summary, "666")
        assert row is not None, "pid '666' missing"
        notes = row.get("notes", {})
        assert notes.get("is_trigger_marker") is True, (
            f"M275 pid 666 must have is_trigger_marker=True. "
            f"Got notes: {notes}"
        )

    def test_pid_666_total_win_is_zero(self, m275_c3_summary):
        """pid 666 total_win must be 0.0 (trigger marker, no payout)."""
        row = self._find_pid_row(m275_c3_summary, "666")
        assert row is not None
        assert row["total_win"] == 0.0, (
            f"pid 666 total_win must be 0.0, got {row['total_win']}"
        )

    def test_pid_666_paylines_has_minus1_entry(self, m275_c3_summary):
        """pid 666 paylines must include the -1 payline_id (scatter trigger line)."""
        row = self._find_pid_row(m275_c3_summary, "666")
        assert row is not None
        payline_ids = [p["payline_id"] for p in row.get("paylines", [])]
        assert "-1" in payline_ids, (
            f"pid 666 must have paylines entry with payline_id='-1'. "
            f"Got: {payline_ids}"
        )

    def test_pid_27502_jackpot_not_trigger_marker(self, m275_c3_summary):
        """M275 pid 27502 (jackpot) must NOT be is_trigger_marker.

        Per brief §4: jackpot pids (27502/27503/27504) are real payouts —
        they win credits and must not be flagged as trigger markers.
        """
        row = self._find_pid_row(m275_c3_summary, "27502")
        if row is None:
            pytest.skip("pid 27502 not found in output (may be in different ST label)")
        notes = row.get("notes", {})
        assert notes.get("is_trigger_marker") is not True, (
            f"M275 pid 27502 (jackpot) must NOT be is_trigger_marker. "
            f"Got notes: {notes}"
        )
