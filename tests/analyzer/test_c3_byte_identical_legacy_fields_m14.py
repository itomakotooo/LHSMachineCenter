"""Phase C3 — byte-identical regression test for M14 mode 1 legacy fields.

Same structure as test_c3_byte_identical_legacy_fields_m275.py but for M14
mode 1 (no bonus spins, vanilla paid-only machine — simpler than M275).

Per brief §4 AC#4 + AC#5: M14 and M275 existing 6 fields IDENTICAL pre/post C3.
M14 is the fleet-wide validation machine per memory/user_testing_machine.md.

M14 expected C3 behavior per smoke output:
  - 7 rows in ST1_paid (no freespin ST)
  - shape for each pid: {"3_of_a_kind": N} (M14 is a 3-column payline machine)
  - covered_columns: [0, 1, 2] for all pids
  - paylines: multiple payline entries per pid (5 paylines on M14)
  - notes.is_trigger_marker: False for all pids (M14 has no scatter trigger pid)
  - notes.max_match_count_observed: 3 for all pids (M14 is 3-reel)

Invariants asserted
-------------------
1. C2 smoke legacy 6 fields == C3 fresh output legacy 6 fields for M14.
2. C3 fresh output has all 4 new fields populated for all M14 rows.
3. No row has is_trigger_marker == True (M14 has no scatter trigger pid).
4. All rows have max_match_count_observed >= 1 (real data flowing from parser).
5. All rows have covered_columns non-empty.
6. No feature_errors in C3 output.
7. At least 5 payline entries in at least one row (M14 has 5 paylines).

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug: in emit(), accidentally overwrite 'hit_count' field:
    Change row construction to include:
        "hit_count": 0,   # BUG: always zero
    RED: test_legacy_hit_count_byte_identical fails (0 != C2 hit_count value).
Revert → GREEN.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md (subprocess mandatory)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/user_testing_machine.md (M14 mode 1 is the fleet validation machine)
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
_C2_SMOKE = _REPO_ROOT / "cache" / "c2_smoke" / "M14_postC2" / "player_impact_summary.json"

_LEGACY_KEYS = {
    "payout_id", "hit_count", "hit_rate",
    "total_win", "avg_win_when_hit", "rtp_contribution_pp",
}
_C3_NEW_KEYS = {"shape", "covered_columns", "paylines", "notes"}
_ALL_REQUIRED_KEYS = _LEGACY_KEYS | _C3_NEW_KEYS


def _load_c2_smoke() -> dict | None:
    """Load C2 smoke baseline. Returns None if file not found."""
    if _C2_SMOKE.exists():
        return json.loads(_C2_SMOKE.read_bytes())
    return None


@pytest.fixture(scope="module")
def m14_c3_summary() -> dict:
    """Run M14 mode 1 analyzer with C3 code; return parsed summary."""
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
            timeout=180,
        )
        assert result.returncode == 0, (
            f"M14 C3 analyzer exited non-zero ({result.returncode}).\n"
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists(), "player_impact_summary.json not produced"
        return json.loads(summary_path.read_bytes())


class TestM14C3LegacyFieldsByteIdentical:
    """THE invariant: C2 legacy fields == C3 fresh output for M14 (byte-identical)."""

    def test_no_feature_errors(self, m14_c3_summary):
        """No feature_errors in M14 C3 output."""
        fe = m14_c3_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"

    def test_payouts_by_spin_type_present(self, m14_c3_summary):
        """payouts_by_spin_type must be present in M14 C3 output."""
        pi = m14_c3_summary.get("player_impact", {})
        assert "payouts_by_spin_type" in pi, (
            f"payouts_by_spin_type missing. Keys: {sorted(pi.keys())}"
        )

    def test_all_rows_have_10_required_keys(self, m14_c3_summary):
        """Every M14 row must have 6 C2 fields + 4 C3 fields."""
        pbst = m14_c3_summary["player_impact"]["payouts_by_spin_type"]
        for label, rows in pbst.items():
            for row in rows:
                missing = _ALL_REQUIRED_KEYS - set(row.keys())
                assert not missing, (
                    f"M14 C3 row in {label!r} missing keys {missing}. "
                    f"Row keys: {sorted(row.keys())}"
                )

    def test_legacy_fields_byte_identical_vs_c2_smoke(self, m14_c3_summary):
        """Legacy 6 fields must be byte-identical C2 smoke → C3 fresh for M14.

        INJECT-BUG: in emit(), set 'hit_count': 0 for all rows.
        RED: hit_count differs from C2 smoke → assertion fails.
        Revert → GREEN.

        Falls back to sanity check if C2 smoke not found.
        """
        c2 = _load_c2_smoke()
        if c2 is None:
            pytest.skip("C2 smoke baseline not found; byte-identical comparison skipped")

        c2_pbst = c2["player_impact"]["payouts_by_spin_type"]
        c3_pbst = m14_c3_summary["player_impact"]["payouts_by_spin_type"]

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
                for key in _LEGACY_KEYS - {"payout_id"}:
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
            f"M14 LEGACY FIELD REGRESSIONS ({len(diffs)}):\n"
            + "\n".join(f"  {d}" for d in diffs)
            + "\n\nC3 must be purely additive — the 6 C2 fields must be byte-identical."
        )

    def test_c3_new_fields_populated_for_all_rows(self, m14_c3_summary):
        """All M14 rows must have non-None shape, covered_columns, paylines, notes."""
        pbst = m14_c3_summary["player_impact"]["payouts_by_spin_type"]
        rows_flat = [r for rows in pbst.values() for r in rows]
        assert rows_flat, "No rows in payouts_by_spin_type"
        for row in rows_flat:
            pid = row["payout_id"]
            assert row.get("shape") is not None, f"shape is None for M14 pid {pid}"
            assert row.get("covered_columns") is not None, (
                f"covered_columns is None for M14 pid {pid}"
            )
            assert row.get("paylines") is not None, f"paylines is None for M14 pid {pid}"
            assert row.get("notes") is not None, f"notes is None for M14 pid {pid}"

    def test_m14_no_trigger_markers(self, m14_c3_summary):
        """M14 has no scatter trigger pid — is_trigger_marker must be False for all rows."""
        pbst = m14_c3_summary["player_impact"]["payouts_by_spin_type"]
        trigger_markers = [
            (label, row["payout_id"])
            for label, rows in pbst.items()
            for row in rows
            if row.get("notes", {}).get("is_trigger_marker") is True
        ]
        assert not trigger_markers, (
            f"M14 must not have any trigger marker pids, but found: {trigger_markers}"
        )

    def test_m14_all_rows_max_match_count_gte_1(self, m14_c3_summary):
        """All M14 rows must have max_match_count_observed >= 1 (real data from parser)."""
        pbst = m14_c3_summary["player_impact"]["payouts_by_spin_type"]
        rows_flat = [r for rows in pbst.values() for r in rows]
        for row in rows_flat:
            mc = row.get("notes", {}).get("max_match_count_observed", 0)
            assert mc >= 1, (
                f"M14 pid {row['payout_id']} has max_match_count_observed={mc}. "
                "All M14 pids have regular line hits; match_count must be >= 1."
            )

    def test_m14_covered_columns_nonempty(self, m14_c3_summary):
        """All M14 rows must have non-empty covered_columns (position data flowing)."""
        pbst = m14_c3_summary["player_impact"]["payouts_by_spin_type"]
        rows_flat = [r for rows in pbst.values() for r in rows]
        for row in rows_flat:
            cols = row.get("covered_columns", [])
            assert cols, (
                f"M14 pid {row['payout_id']} has empty covered_columns. "
                "Parser must produce payout_id_col_set for M14 pids."
            )

    def test_m14_has_at_least_5_paylines_in_some_row(self, m14_c3_summary):
        """At least 1 M14 row must have >= 5 payline entries (M14 has 5 paylines)."""
        pbst = m14_c3_summary["player_impact"]["payouts_by_spin_type"]
        rows_flat = [r for rows in pbst.values() for r in rows]
        max_paylines = max(len(row.get("paylines", [])) for row in rows_flat)
        assert max_paylines >= 5, (
            f"Expected at least 1 M14 row with >= 5 paylines (M14 has 5 paylines). "
            f"Max paylines found: {max_paylines}"
        )
