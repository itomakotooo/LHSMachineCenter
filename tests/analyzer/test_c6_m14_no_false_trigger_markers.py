"""Phase C6 — M14 no false trigger markers regression guard.

Invariants asserted
-------------------
1.  M14 payout_ids_top20 rows all have 'notes' block.
2.  M14 has 0 rows with is_trigger_marker == True.
3.  M14 payout_ids_top20 is non-empty (so tests aren't vacuously true).
4.  All M14 payout_ids_top20 notes blocks have 'is_trigger_marker' key.
5.  No M14 payout_ids_top20 row has trigger_target set (should be absent or None).

Rationale
---------
M14 is a vanilla slot machine with no scatter-trigger bonus. The mechanism_registry
for M14 produces scatter_marker_pids = frozenset() because all pids have either
non-zero win or have regular payline records (line_id != -1). The bonus_chain_dynamics
plugin's emit() must therefore produce is_trigger_marker=False for ALL M14 pid rows.

This test guards against the regression where adding trigger-marker detection
accidentally classifies some M14 pid as a trigger when it should not be.

Inject-bug recipe (not a separate inject cycle — covered by test_c6_gap_3 Bug B):
    If Bug B (from test_c6_gap_3_pid_666_trigger_marker.py) were inverted — i.e.
    if emit() set is_trigger_marker=True for all pids — this test would fire.
    We rely on test_c6_gap_3 Bug B to cover the bidirectional correctness; this
    file is the M14-specific false-positive guard.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_no_hardcode.md
  (no machine-specific pid values; inference from mechanism_registry which is
   machine-agnostic)
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess required — unit tests alone cannot verify per-machine isolation)
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


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m14_no_false_summary() -> dict:
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


@pytest.fixture(scope="module")
def m14_pid_rows(m14_no_false_summary) -> list:
    """Extract payout_ids_top20 rows from M14 summary."""
    pi = m14_no_false_summary.get("player_impact", {})
    rows = pi.get("payout_ids_top20") or []
    return rows


# ---------------------------------------------------------------------------
# T1: payout_ids_top20 non-empty
# ---------------------------------------------------------------------------

class TestM14PidRowsPresent:
    """payout_ids_top20 must be non-empty so false-positive checks are not vacuous."""

    def test_payout_ids_top20_nonempty(self, m14_pid_rows):
        """M14 must have at least 1 payout_id row to make the false-positive check meaningful."""
        assert len(m14_pid_rows) > 0, (
            "M14 payout_ids_top20 is empty — cannot test false-positive guard. "
            "M14 has real payout IDs; this suggests a parsing or filtering issue."
        )


# ---------------------------------------------------------------------------
# T2: All rows have notes block
# ---------------------------------------------------------------------------

class TestM14AllRowsHaveNotes:
    """C6 emit() must add notes to all M14 rows, not just M275."""

    def test_all_rows_have_notes_key(self, m14_pid_rows):
        """Every row in M14 payout_ids_top20 must have 'notes' key."""
        missing = [
            str(row.get("payout_id")) for row in m14_pid_rows if "notes" not in row
        ]
        assert not missing, (
            f"M14 rows missing 'notes' key: pids {missing}. "
            f"emit() must add notes to all rows including M14."
        )

    def test_all_rows_have_is_trigger_marker_key(self, m14_pid_rows):
        """Every notes block must have 'is_trigger_marker' key."""
        missing = [
            str(row.get("payout_id"))
            for row in m14_pid_rows
            if "is_trigger_marker" not in row.get("notes", {})
        ]
        assert not missing, (
            f"M14 rows with notes missing 'is_trigger_marker': pids {missing}. "
            f"notes block must always include is_trigger_marker."
        )


# ---------------------------------------------------------------------------
# T3: Zero trigger markers (critical false-positive guard)
# ---------------------------------------------------------------------------

class TestM14ZeroTriggerMarkers:
    """M14 must have 0 rows with is_trigger_marker=True."""

    def test_trigger_marker_count_is_zero(self, m14_pid_rows):
        """Count of is_trigger_marker=True rows must be exactly 0 for M14.

        M14 is a vanilla machine. mechanism_registry will produce
        scatter_marker_pids = frozenset() for M14 because all pids have
        non-zero wins or have regular payline records.

        If this test fires, either:
          (a) M14 has an unexpectedly high-win=0 pid with no paylines (data change), OR
          (b) The detection logic has a false positive (regression).

        In either case this test correctly signals investigation.
        """
        trigger_rows = [
            row for row in m14_pid_rows
            if row.get("notes", {}).get("is_trigger_marker") is True
        ]
        assert len(trigger_rows) == 0, (
            f"M14 must have 0 trigger markers. Found {len(trigger_rows)} rows "
            f"with is_trigger_marker=True. Pids: "
            f"{[r.get('payout_id') for r in trigger_rows]}. "
            f"M14 is a vanilla machine with no scatter triggers."
        )

    def test_no_trigger_target_set_for_any_row(self, m14_pid_rows):
        """No M14 row should have trigger_target set to a non-None value.

        Per plugin design: trigger_target is absent or null for non-trigger machines.
        """
        rows_with_target = [
            row for row in m14_pid_rows
            if row.get("notes", {}).get("trigger_target") is not None
        ]
        assert len(rows_with_target) == 0, (
            f"M14 must have 0 rows with non-None trigger_target. "
            f"Found {len(rows_with_target)}: "
            f"{[(r.get('payout_id'), r.get('notes', {}).get('trigger_target')) for r in rows_with_target]}"
        )

    def test_no_trigger_target_confidence_for_any_row(self, m14_pid_rows):
        """No M14 row should have trigger_target_confidence in notes.

        Per memory/feedback_invariant_with_fallback_hides_drift.md: absence
        is explicit 'not applicable', not a silent null. Non-trigger rows must
        omit trigger_target_confidence entirely.
        """
        rows_with_confidence = [
            row for row in m14_pid_rows
            if "trigger_target_confidence" in row.get("notes", {})
        ]
        assert len(rows_with_confidence) == 0, (
            f"M14 must have 0 rows with trigger_target_confidence key in notes. "
            f"Found {len(rows_with_confidence)}: "
            f"{[r.get('payout_id') for r in rows_with_confidence]}. "
            f"trigger_target_confidence must be absent for non-trigger rows."
        )
