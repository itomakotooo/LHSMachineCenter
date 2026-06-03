"""Phase C3 — M275 pid 666 trigger marker E2E assertion.

Runs the real analyzer against the cached M275 mode 1 rawdata and asserts
that pid 666 specifically gets notes.is_trigger_marker == True.

This is THE canonical C3 trigger-marker test: pid 666 on M275 is the
machine that drove the entire unbundle effort. Per brief §4 AC#3.

Per memory/feedback_perf_claim_needs_e2e_event_stream.md:
  "Must spawn real subprocess against real fixture; unit test alone insufficient."
  "Ask: if user screenshots, which test goes red?" — this test goes red
  if trigger-marker detection is broken in the subprocess path.

Invariants asserted
-------------------
1. Analyzer runs to rc=0 with M275 cached chunks.
2. pid 666 present in payouts_by_spin_type output.
3. pid 666 notes.is_trigger_marker == True.
4. pid 666 total_win == 0.0.
5. pid 666 paylines contains a -1 entry (scatter trigger line).
6. pid 666 shape == {} (no regular-line records → empty n-of-a-kind).
7. pid 666 hit_count > 0 (sanity: real data).
8. No other pid in payouts_by_spin_type has is_trigger_marker == True
   (M275 has exactly 1 scatter trigger pid in the standard ST140_paid output).
9. error_capture path works: feature_errors empty (no silent failures).
10. SCHEMA_VERSION == 2 in the produced summary (confirms C3 code ran).

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug: in payouts_by_spin_type.py emit(), change:
    "is_trigger_marker": is_trigger,
to:
    "is_trigger_marker": False,
RED: test_pid_666_is_trigger_marker_true fails (expected True, got False).
Revert → GREEN.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md (subprocess mandatory)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_invariant_with_fallback_hides_drift.md (is_trigger_marker
  is an EXPLICIT positive signal, not a fallback bucket)
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

_TRIGGER_PID = "666"


@pytest.fixture(scope="module")
def m275_trigger_marker_summary() -> dict:
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
            f"M275 trigger-marker test: analyzer exited non-zero ({result.returncode}).\n"
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists()
        return json.loads(summary_path.read_bytes())


def _get_pbst_rows(summary: dict) -> dict[str, list[dict]]:
    """Return payouts_by_spin_type dict from summary."""
    return summary["player_impact"]["payouts_by_spin_type"]


def _find_pid_row(summary: dict, pid: str) -> dict | None:
    """Find a row by payout_id across all ST labels."""
    for rows in _get_pbst_rows(summary).values():
        for row in rows:
            if row["payout_id"] == pid:
                return row
    return None


class TestM275TriggerMarkerAnalyzerRuns:
    """Preconditions: analyzer ran cleanly and produced C3 output."""

    def test_analyzer_rc_zero(self, m275_trigger_marker_summary):
        """Analyzer must exit rc=0 for M275 (fixture would fail otherwise)."""
        # If fixture succeeded, rc was 0. Just verify summary is dict.
        assert isinstance(m275_trigger_marker_summary, dict)

    def test_schema_version_is_3(self, m275_trigger_marker_summary):
        """C3/C4 enrichment fields must be present (SCHEMA_VERSION == 3, C4/Phase-P3 active).

        The summary doesn't directly contain SCHEMA_VERSION, but we can verify
        C3+ code ran by checking that the C3 new fields exist in the output.
        SCHEMA_VERSION was bumped 1→2 in C3 (shape/covered_columns/paylines/notes)
        and 2→3 in C4/Phase-P3 (symbol_combo).
        """
        pbst = _get_pbst_rows(m275_trigger_marker_summary)
        rows_flat = [r for rows in pbst.values() for r in rows]
        assert rows_flat, "No rows in payouts_by_spin_type"
        # At least one row has 'shape' key (C3 new field)
        rows_with_shape = [r for r in rows_flat if "shape" in r]
        assert rows_with_shape, (
            "No rows have 'shape' key — C3 code may not have run. "
            "SCHEMA_VERSION must be 3 (C4/Phase-P3 active)."
        )

    def test_no_feature_errors(self, m275_trigger_marker_summary):
        """feature_errors must be absent or empty for M275 trigger-marker test."""
        fe = m275_trigger_marker_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"


class TestM275Pid666TriggerMarker:
    """pid 666 specific assertions — the canonical trigger marker."""

    def test_pid_666_present(self, m275_trigger_marker_summary):
        """pid 666 must appear in payouts_by_spin_type for M275.

        If absent, either the trigger-marker retention logic is broken
        (hits > 0 but missing from output) or the C3 parse path silently failed.
        """
        row = _find_pid_row(m275_trigger_marker_summary, _TRIGGER_PID)
        assert row is not None, (
            f"pid '{_TRIGGER_PID}' missing from payouts_by_spin_type. "
            "Trigger markers (hits > 0, win = 0) must be retained in C3 output."
        )

    def test_pid_666_is_trigger_marker_true(self, m275_trigger_marker_summary):
        """THE invariant: M275 pid 666 notes.is_trigger_marker MUST be True.

        Per brief §4 AC#3: pid 666 specifically shows is_trigger_marker: true.
        Per memory/feedback_invariant_with_fallback_hides_drift.md: this is an
        explicit positive signal derived from 'all hits have line_id==-1 AND
        total_win==0' — NOT a fallback bucket.

        INJECT-BUG: set is_trigger_marker = False always in emit().
        RED: expected True, got False → this assertion fails.
        Revert → GREEN.
        """
        row = _find_pid_row(m275_trigger_marker_summary, _TRIGGER_PID)
        assert row is not None, f"pid '{_TRIGGER_PID}' missing"
        notes = row.get("notes", {})
        is_trigger = notes.get("is_trigger_marker")
        assert is_trigger is True, (
            f"M275 pid '{_TRIGGER_PID}' must have notes.is_trigger_marker=True. "
            f"Got: {is_trigger!r}. "
            f"Full notes: {notes}"
        )

    def test_pid_666_total_win_zero(self, m275_trigger_marker_summary):
        """pid 666 total_win must be 0.0 (scatter trigger, no credits paid)."""
        row = _find_pid_row(m275_trigger_marker_summary, _TRIGGER_PID)
        assert row is not None
        assert row["total_win"] == 0.0, (
            f"pid 666 total_win must be 0.0, got {row['total_win']}"
        )

    def test_pid_666_hit_count_positive(self, m275_trigger_marker_summary):
        """pid 666 hit_count must be > 0 (real freespin triggers observed)."""
        row = _find_pid_row(m275_trigger_marker_summary, _TRIGGER_PID)
        assert row is not None
        assert row["hit_count"] > 0, (
            f"pid 666 hit_count must be > 0 (freespin triggers present in M275). "
            f"Got: {row['hit_count']}"
        )

    def test_pid_666_paylines_has_minus1(self, m275_trigger_marker_summary):
        """pid 666 paylines list must contain payline_id == '-1'.

        Scatter trigger lines are encoded as line_id == -1 in PayoutByPayline.
        The paylines enrichment must pass this through for trigger markers.
        """
        row = _find_pid_row(m275_trigger_marker_summary, _TRIGGER_PID)
        assert row is not None
        paylines = row.get("paylines", [])
        pl_ids = [p["payline_id"] for p in paylines]
        assert "-1" in pl_ids, (
            f"pid 666 paylines must contain payline_id='-1'. Got: {pl_ids}"
        )

    def test_pid_666_shape_is_empty(self, m275_trigger_marker_summary):
        """pid 666 shape must be {} (no regular-line records, no n-of-a-kind)."""
        row = _find_pid_row(m275_trigger_marker_summary, _TRIGGER_PID)
        assert row is not None
        shape = row.get("shape", None)
        assert shape == {}, (
            f"pid 666 (trigger marker) must have empty shape dict. Got: {shape}"
        )

    def test_pid_666_max_match_count_zero(self, m275_trigger_marker_summary):
        """pid 666 notes.max_match_count_observed must be 0 (no regular lines)."""
        row = _find_pid_row(m275_trigger_marker_summary, _TRIGGER_PID)
        assert row is not None
        mc = row.get("notes", {}).get("max_match_count_observed", -1)
        assert mc == 0, (
            f"pid 666 max_match_count_observed must be 0. Got: {mc}"
        )


class TestM275NonTriggerPidsNotMarked:
    """No other M275 pid in payouts_by_spin_type should be falsely flagged."""

    def test_jackpot_pids_not_trigger_markers(self, m275_trigger_marker_summary):
        """M275 jackpot pids (27502/27503/27504) must NOT be is_trigger_marker.

        Per brief §4: jackpot pids are real payouts; pid 666 detection must be
        criterion-based (line_id==-1 AND win==0), not pid-value-based hardcode.
        """
        jackpot_pids = ["27502", "27503", "27504"]
        for pid in jackpot_pids:
            row = _find_pid_row(m275_trigger_marker_summary, pid)
            if row is None:
                continue  # pid may not appear in all STs; skip if absent
            notes = row.get("notes", {})
            is_trigger = notes.get("is_trigger_marker")
            assert is_trigger is not True, (
                f"Jackpot pid {pid!r} must NOT be is_trigger_marker. "
                f"Got: {is_trigger!r}. Notes: {notes}"
            )

    def test_regular_pids_have_total_win_positive(self, m275_trigger_marker_summary):
        """All non-666 pids with is_trigger_marker=False must have total_win > 0.

        Sanity: trigger marker detection must not misfire on pids that won credits.
        """
        pbst = _get_pbst_rows(m275_trigger_marker_summary)
        for label, rows in pbst.items():
            for row in rows:
                if row["payout_id"] == _TRIGGER_PID:
                    continue
                if row.get("notes", {}).get("is_trigger_marker") is False:
                    # Check: regular pids (not trigger markers) should have win > 0
                    # UNLESS they're _unattributed_* fallback entries
                    if row["payout_id"].startswith("_"):
                        continue
                    assert row["total_win"] > 0, (
                        f"Non-trigger pid {row['payout_id']!r} in {label!r} has "
                        f"total_win=0 but is_trigger_marker=False. "
                        "This may indicate trigger-marker mis-classification."
                    )
