"""Phase C4 — subprocess test: M14 must have no false positives.

Spawns the real player_impact_analyzer against M14 mode 1 cached chunks.
Verifies that the Mechanism Registry does NOT produce false-positive applicable
flags for a vanilla machine (M14 has no jackpot, no freespin, no lock mechanics).

Background
----------
M14 is the standard validation machine per user_testing_machine.md.
It has no jackpot PIDs >= 10000, no JackpotIds events, no bonus chains,
no lock lines/symbols/reels, and no dollar pick mechanics.

The C4 Mechanism Registry must:
1. Not fire Tier 3 jackpot detection (no PIDs >= 10000)
2. Not fire Tier 2 freespin detection (bonus_chain_lengths = [])
3. Leave all applicable flags = False

Coordinator-verified values (M14 mode 1, 2026-05-27):
  machine_mechanics.jackpot.applicable = False
  machine_mechanics.free_spin.applicable = False
  All 6 sections: applicable = False

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug: Add a false-positive in MechanismRegistry.build() — change threshold to 0:
    In mechanism_registry.py, change:
        if pid_int >= 10000 and pid_s not in scatter_marker_pids:
    to:
        if pid_int >= 0 and pid_s not in scatter_marker_pids:
    RED: M14 has regular paid PIDs (e.g., pid=1, 2, 3...) which are >= 0,
         so jackpot_applicable becomes True for M14 (false positive).
         test_m14_jackpot_applicable_false fails.
    Revert (restore >= 10000) → GREEN.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test required — false-positive prevention needs real machine data)
- memory/feedback_integration_test_argv.md
  (real subprocess against real M14 data)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/user_testing_machine.md (M14 mode 1 is the standard validation machine)
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


@pytest.fixture(scope="module")
def m14_c4_summary() -> dict:
    """Run M14 mode 1 analyzer from cache; return parsed summary."""
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
            timeout=300,
        )
        assert result.returncode == 0, (
            f"M14 analyzer exited non-zero ({result.returncode}).\n"
            f"STDOUT: {result.stdout[:3000]}\n"
            f"STDERR: {result.stderr[:3000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists(), (
            f"summary.json not written. STDOUT: {result.stdout[:500]}"
        )
        return json.loads(summary_path.read_bytes())


# ---------------------------------------------------------------------------
# T1: Analyzer health
# ---------------------------------------------------------------------------

class TestM14C4Health:
    """Sanity: no errors, machine_mechanics key present."""

    def test_no_analyzer_init_error(self, m14_c4_summary):
        """analyzer_init_error must be absent."""
        assert "analyzer_init_error" not in m14_c4_summary, (
            f"analyzer_init_error present: {m14_c4_summary.get('analyzer_init_error')}"
        )

    def test_no_feature_errors(self, m14_c4_summary):
        """feature_errors must be absent or empty."""
        fe = m14_c4_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"

    def test_machine_mechanics_key_present(self, m14_c4_summary):
        """machine_mechanics must be in player_impact (M14 declares it in manifest)."""
        pi = m14_c4_summary.get("player_impact", {})
        assert "machine_mechanics" in pi, (
            f"'machine_mechanics' missing from player_impact for M14. "
            f"M14 manifest declares machine_mechanics in analyzer_features. "
            f"Got keys: {sorted(pi.keys())}"
        )


# ---------------------------------------------------------------------------
# T2: No false positives — all mechanics.applicable = False
# ---------------------------------------------------------------------------

class TestM14NoFalsePositives:
    """ALL 6 mechanics.applicable must be False for M14 (vanilla machine)."""

    def _get_mm(self, summary: dict) -> dict:
        return summary["player_impact"]["machine_mechanics"]

    def test_m14_jackpot_applicable_false(self, m14_c4_summary):
        """jackpot.applicable must be False for M14 (no jackpot PIDs >= 10000).

        M14 does not have PIDs >= 10000 in payout_id_win, and has no JackpotIds
        raw field events. The Mechanism Registry must correctly return False.

        INJECT-BUG: lower PID threshold to >= 0 in mechanism_registry.py.
        RED: all M14's paid PIDs become jackpot candidates → false positive.
        Revert → GREEN.
        """
        mm = self._get_mm(m14_c4_summary)
        assert mm["jackpot"]["applicable"] is False, (
            f"jackpot.applicable must be False for M14 (no jackpot PIDs). "
            f"Got: {mm['jackpot']['applicable']!r}. "
            f"jackpot_ids: {mm['jackpot'].get('jackpot_ids')}"
        )

    def test_m14_freespin_applicable_false(self, m14_c4_summary):
        """free_spin.applicable must be False for M14 (no bonus chains).

        M14 has no freespin chains → bonus_chain_lengths = [] → Tier 2 gives False.
        """
        mm = self._get_mm(m14_c4_summary)
        assert mm["free_spin"]["applicable"] is False, (
            f"free_spin.applicable must be False for M14 (no bonus chains). "
            f"Got: {mm['free_spin']['applicable']!r}"
        )

    def test_m14_lock_lines_applicable_false(self, m14_c4_summary):
        """lock_lines.applicable must be False for M14 (no lock lines mechanics)."""
        mm = self._get_mm(m14_c4_summary)
        assert mm["lock_lines"]["applicable"] is False, (
            f"lock_lines.applicable must be False for M14. "
            f"Got: {mm['lock_lines']['applicable']!r}"
        )

    def test_m14_lock_symbols_applicable_false(self, m14_c4_summary):
        """lock_symbols.applicable must be False for M14."""
        mm = self._get_mm(m14_c4_summary)
        assert mm["lock_symbols"]["applicable"] is False, (
            f"lock_symbols.applicable must be False for M14. "
            f"Got: {mm['lock_symbols']['applicable']!r}"
        )

    def test_m14_lock_reels_applicable_false(self, m14_c4_summary):
        """lock_reels.applicable must be False for M14."""
        mm = self._get_mm(m14_c4_summary)
        assert mm["lock_reels"]["applicable"] is False, (
            f"lock_reels.applicable must be False for M14. "
            f"Got: {mm['lock_reels']['applicable']!r}"
        )

    def test_m14_dollar_pick_applicable_false(self, m14_c4_summary):
        """dollar_pick.applicable must be False for M14."""
        mm = self._get_mm(m14_c4_summary)
        assert mm["dollar_pick"]["applicable"] is False, (
            f"dollar_pick.applicable must be False for M14. "
            f"Got: {mm['dollar_pick']['applicable']!r}"
        )

    def test_m14_no_tier1_manifest_override_detection(self, m14_c4_summary):
        """M14 manifest has no mechanism_overrides — _detection_source must NOT say tier1_manifest.

        If any _detection_source says 'tier1_manifest' for M14, it means the
        manifest erroneously has overrides (or there's a detection logic bug).
        """
        mm = self._get_mm(m14_c4_summary)
        for section_name in ["jackpot", "free_spin"]:
            src = mm[section_name].get("_detection_source", "")
            assert src != "tier1_manifest", (
                f"{section_name}._detection_source is 'tier1_manifest' for M14, "
                f"but M14 has no mechanism_overrides in its manifest. Got: {src!r}"
            )

    def test_m14_jackpot_ids_empty(self, m14_c4_summary):
        """jackpot_ids must be empty for M14 (no jackpot events)."""
        mm = self._get_mm(m14_c4_summary)
        jackpot_ids = mm["jackpot"].get("jackpot_ids", [])
        assert jackpot_ids == [], (
            f"jackpot_ids must be [] for M14. Got: {jackpot_ids}"
        )

    def test_m14_freespin_chain_spins_zero(self, m14_c4_summary):
        """chain_spins must be 0 for M14 (no freespin chains)."""
        mm = self._get_mm(m14_c4_summary)
        chain_spins = mm["free_spin"].get("chain_spins", -1)
        assert chain_spins == 0, (
            f"chain_spins must be 0 for M14. Got: {chain_spins}"
        )
