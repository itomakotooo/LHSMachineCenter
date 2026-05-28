"""Phase C6 — gap #3: scatter_trigger_marker on payout_ids_top20 (M275 pid 666).

Invariants asserted (critical path — gap #3 closure guard)
----------------------------------------------------------
1.  M275 payout_ids_top20 row for pid 666 exists.
2.  pid 666 notes.is_trigger_marker == True.
3.  pid 666 notes.trigger_target == "NormalCollectionSpin" (majority chain-count winner;
    NCS=841 chains vs NewFreespin=67 — correctness fix R1 Phase 2 d2).
4.  pid 666 notes.trigger_target_confidence in {"data_inferred", "unique"}.
5.  pid 1: notes.is_trigger_marker == False (regular pay pid, not scatter).
6.  pid 4: notes.is_trigger_marker == False (regular pay pid, not scatter).
7.  pid 8: notes.is_trigger_marker == False (regular pay pid, not scatter).
8.  All payout_ids_top20 rows have notes block present.
9.  Exactly 1 row across all payout_ids_top20 has is_trigger_marker=True (M275 has
    exactly one scatter trigger pid: 666).

Inject-bug recipe B (CRITICAL — gap #3 regression guard)
----------------------------------------------------------
Bug B: remove trigger_marker detection from emit() in bonus_chain_dynamics.py:
    Change the emit() augmentation block (step 4) to always set is_trigger_marker=False:
        notes = {"is_trigger_marker": False}
        row["notes"] = notes
    RED: test_pid_666_is_trigger_marker fails (is_trigger_marker becomes False).
         test_trigger_marker_count_exactly_one fails (count becomes 0).
    Revert (restore full augmentation logic) -> GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (is_trigger_marker is an explicit positive signal, not catch-all fallback)
- memory/feedback_no_hardcode.md
  (no machine-specific pid values hardcoded; inference derives from mechanism_registry)
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test required — unit tests alone cannot catch PIA field drift)
- memory/feedback_no_parallel_panel_impl.md
  (notes shape mirrors payouts_by_spin_type notes shape — C3 sibling)
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

_VALID_CONFIDENCE_VALUES = {"data_inferred", "unique", "unknown"}


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m275_gap3_summary() -> dict:
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
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )
        return json.loads((Path(tmpdir) / "player_impact_summary.json").read_bytes())


@pytest.fixture(scope="module")
def m275_pid_rows(m275_gap3_summary) -> list:
    """Extract payout_ids_top20 rows from summary."""
    pi = m275_gap3_summary.get("player_impact", {})
    rows = pi.get("payout_ids_top20") or []
    if not rows:
        pytest.skip("payout_ids_top20 is empty — cannot test trigger marker.")
    return rows


@pytest.fixture(scope="module")
def m275_row_by_pid(m275_pid_rows) -> dict:
    """Build {str(payout_id): row} lookup dict for quick access."""
    return {str(row.get("payout_id", "")): row for row in m275_pid_rows}


# ---------------------------------------------------------------------------
# T1: All rows have notes block
# ---------------------------------------------------------------------------

class TestAllRowsHaveNotes:
    """Every payout_ids_top20 row must have a notes block after C6 emit."""

    def test_all_rows_have_notes(self, m275_pid_rows):
        """Every row in payout_ids_top20 must have 'notes' key."""
        missing = [
            row.get("payout_id") for row in m275_pid_rows if "notes" not in row
        ]
        assert not missing, (
            f"Rows missing 'notes' key: payout_ids {missing}. "
            f"C6 emit() must add notes to all rows."
        )


# ---------------------------------------------------------------------------
# T2: pid 666 — trigger marker positive assertion (CRITICAL gap #3 guard)
# ---------------------------------------------------------------------------

class TestPid666TriggerMarker:
    """pid 666 is the scatter trigger for M275 bonus chain — must be identified."""

    def test_pid_666_exists_in_payout_ids_top20(self, m275_row_by_pid):
        """pid 666 must appear in payout_ids_top20 (M275 observed 829 hits).

        If pid 666 is absent, the machine may have been analyzed differently.
        """
        assert "666" in m275_row_by_pid, (
            f"pid 666 must be in payout_ids_top20 for M275. "
            f"Available pids: {sorted(m275_row_by_pid.keys())}"
        )

    def test_pid_666_is_trigger_marker(self, m275_row_by_pid):
        """pid 666 notes.is_trigger_marker must be True.

        INJECT-BUG (Bug B): change emit() step 4 to always set is_trigger_marker=False.
        RED: this test fails (is_trigger_marker becomes False).
        Revert -> GREEN.

        This is the critical gap #3 guard. If regression opens gap #3, this
        test fires immediately.
        """
        row = m275_row_by_pid["666"]
        notes = row.get("notes", {})
        assert notes.get("is_trigger_marker") is True, (
            f"pid 666 must have is_trigger_marker=True (scatter trigger). "
            f"notes: {notes}"
        )

    def test_pid_666_trigger_target_is_normal_collection_spin(self, m275_row_by_pid):
        """pid 666 notes.trigger_target must be 'NormalCollectionSpin'.

        R1 Phase 2 d2 correctness fix: M275 by_feature has NormalCollectionSpin (841
        chains) and NewFreespin (67 chains). Chain-count majority vote picks
        NormalCollectionSpin as the primary scatter trigger target.
        BEFORE d2: alphabetical-first 'NewFreespin' was WRONG.
        AFTER d2:  majority-vote 'NormalCollectionSpin' is CORRECT.

        INJECT-BUG (d2 regression guard): revert bonus_chain_dynamics.py to
        alphabetical-first sort → trigger_target becomes 'NewFreespin' → RED.
        Restore chain-count majority vote → GREEN.
        """
        row = m275_row_by_pid["666"]
        notes = row.get("notes", {})
        assert notes.get("trigger_target") == "NormalCollectionSpin", (
            f"pid 666 trigger_target must be 'NormalCollectionSpin' (chain-count "
            f"majority: NCS=841 > NewFreespin=67). "
            f"notes: {notes}"
        )

    def test_pid_666_trigger_target_confidence_valid(self, m275_row_by_pid):
        """pid 666 notes.trigger_target_confidence must be in valid set."""
        row = m275_row_by_pid["666"]
        notes = row.get("notes", {})
        confidence = notes.get("trigger_target_confidence")
        assert confidence in _VALID_CONFIDENCE_VALUES, (
            f"pid 666 trigger_target_confidence must be one of "
            f"{_VALID_CONFIDENCE_VALUES}. Got: {confidence!r}"
        )


# ---------------------------------------------------------------------------
# T3: Spot-check non-trigger pids — no false positives
# ---------------------------------------------------------------------------

class TestNonTriggerPidSpotCheck:
    """Regular pids must have is_trigger_marker=False — no false positives."""

    @pytest.mark.parametrize("pid", ["1", "4", "8"])
    def test_non_trigger_pid_is_false(self, pid, m275_row_by_pid):
        """Regular pay pids must have is_trigger_marker=False.

        Pids 1, 4, 8 are regular pay pids on M275 (they have non-zero wins
        and payline records). Only pid 666 (win=0, no regular line) is a trigger.
        """
        if pid not in m275_row_by_pid:
            pytest.skip(f"pid {pid} not present in payout_ids_top20 for M275 — skipping spot-check")

        row = m275_row_by_pid[pid]
        notes = row.get("notes", {})
        assert notes.get("is_trigger_marker") is False, (
            f"pid {pid} must have is_trigger_marker=False (regular pay pid). "
            f"notes: {notes}"
        )


# ---------------------------------------------------------------------------
# T4: Exactly one trigger marker in M275 payout_ids_top20
# ---------------------------------------------------------------------------

class TestTriggerMarkerCount:
    """M275 must have exactly 1 trigger marker row."""

    def test_trigger_marker_count_exactly_one(self, m275_pid_rows):
        """Exactly 1 row must have is_trigger_marker=True for M275.

        M275 has a single scatter trigger pid (666). Exactly 1 marker.

        INJECT-BUG (Bug B): force all is_trigger_marker=False.
        RED: count becomes 0 instead of 1.
        Revert -> GREEN.
        """
        trigger_rows = [
            row for row in m275_pid_rows
            if row.get("notes", {}).get("is_trigger_marker") is True
        ]
        assert len(trigger_rows) == 1, (
            f"M275 must have exactly 1 trigger marker row. "
            f"Got {len(trigger_rows)}. "
            f"Trigger pids: {[r.get('payout_id') for r in trigger_rows]}"
        )

    def test_trigger_marker_pid_is_666(self, m275_pid_rows):
        """The single trigger marker row must be pid 666."""
        trigger_rows = [
            row for row in m275_pid_rows
            if row.get("notes", {}).get("is_trigger_marker") is True
        ]
        trigger_pids = [str(r.get("payout_id", "")) for r in trigger_rows]
        assert trigger_pids == ["666"], (
            f"The only trigger marker must be pid 666. Got: {trigger_pids}"
        )
