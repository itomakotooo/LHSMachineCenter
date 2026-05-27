"""Phase C4 — subprocess test: M275 gap #1 closed (jackpot.applicable=True).

Spawns the real player_impact_analyzer against M275 mode 1 cached chunks.
Verifies that gap #1 (jackpot.applicable=false despite jackpot PIDs present)
is CLOSED by the C4 Mechanism Registry implementation.

Background
----------
Before C4, the PIA inline machine_mechanics block used:
  jackpot_applicable = (jackpot_spins > 0)
For M275, jackpot PIDs 27502/27503/27504 appear in payout_id_win (not in the
raw JackpotIds field) so jackpot_spins == 0 → jackpot.applicable=False (BUG).

After C4, the MechanismRegistry uses Tier 3 Path A:
  any PID >= 10000 in payout_id_win → jackpot_applicable=True
This correctly identifies 27502/27503/27504 and sets applicable=True.

Coordinator-verified values (M275 mode 1, 2026-05-27):
  jackpot.applicable = True
  jackpot_ids = ["27502", "27503", "27504"]
  detection_source = "tier3_pid_ge_10000"
  rtp_contribution_pp ≈ 5.49 (range [5.0, 6.0])

Per memory/feedback_perf_claim_needs_e2e_event_stream.md:
  Unit tests of MechanismRegistry.build() alone cannot catch:
  - PIA wiring (5-site registration)
  - Registry passed through PipelineContext
  - payout_id_win accumulator correctly built from parser output
  This subprocess test catches all three.

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md) — Bug C
--------------------------------------------------------------------------
Bug C — skip the PID >= 10000 jackpot detection branch in MechanismRegistry:
    In fresh_slotlab/analyzer/mechanism_registry.py, in MechanismRegistry.build(),
    change the Path A detection block:
        for pid_s in payout_id_win:
            try:
                pid_int = int(pid_s)
            except ValueError:
                continue
            if pid_int >= 10000 and pid_s not in scatter_marker_pids:
                _path_a.add(pid_s)
    to:
        # BUG: skip Path A detection entirely
        pass

    RED: M275 jackpot.applicable=False (PIDs 27502/27503/27504 no longer detected via
         Path A, and they don't appear in JackpotIds raw field so Path B is also empty).
         test_m275_jackpot_applicable_true fails.
    Revert (restore Path A loop) → GREEN.

    This test documents that Path A detection is the critical guard for gap #1 closure.
    Without it, 26 machines with jackpot PIDs >= 10000 would silently regress to
    jackpot.applicable=False.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test required — unit tests alone don't catch PIA wiring bugs)
- memory/feedback_integration_test_argv.md
  (real subprocess invocation, not mocked; real parser output, real accumulation)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (_detection_source must say which tier fired — not a silent bucket)
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

# Coordinator-verified jackpot PIDs for M275 mode 1.
_EXPECTED_JACKPOT_IDS = {"27502", "27503", "27504"}

# rtp_contribution_pp range verified by coordinator (5.4875% from brief)
_RTP_CONTRIBUTION_LO = 5.0
_RTP_CONTRIBUTION_HI = 6.0


@pytest.fixture(scope="module")
def m275_gap1_summary() -> dict:
    """Run M275 mode 1 analyzer from cache; return parsed summary."""
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
            timeout=300,
        )
        assert result.returncode == 0, (
            f"M275 analyzer exited non-zero ({result.returncode}).\n"
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

class TestM275Gap1Health:
    """Sanity: no errors, rtp_integrity passes."""

    def test_no_analyzer_init_error(self, m275_gap1_summary):
        """analyzer_init_error must be absent."""
        assert "analyzer_init_error" not in m275_gap1_summary, (
            f"analyzer_init_error present: {m275_gap1_summary.get('analyzer_init_error')}"
        )

    def test_no_feature_errors(self, m275_gap1_summary):
        """feature_errors must be absent or empty."""
        fe = m275_gap1_summary.get("feature_errors", {})
        assert not fe, f"feature_errors populated: {fe}"

    def test_machine_mechanics_key_present(self, m275_gap1_summary):
        """machine_mechanics must be in player_impact (5-site registration check)."""
        pi = m275_gap1_summary.get("player_impact", {})
        assert "machine_mechanics" in pi, (
            f"'machine_mechanics' missing from player_impact. Keys: {sorted(pi.keys())}. "
            f"Check all 5 plugin registration sites in PIA."
        )


# ---------------------------------------------------------------------------
# T2: Gap #1 closure — jackpot.applicable=True for M275
# ---------------------------------------------------------------------------

class TestM275Gap1JackpotApplicable:
    """jackpot.applicable must be True — gap #1 closed."""

    def test_m275_jackpot_applicable_true(self, m275_gap1_summary):
        """jackpot.applicable must be True for M275.

        INJECT-BUG (Bug C): remove the Path A PID >= 10000 detection loop from
        mechanism_registry.py MechanismRegistry.build().
        RED: jackpot.applicable=False because:
          - PIDs 27502/27503/27504 no longer detected via Path A
          - No JackpotIds raw field events on M275 so Path B is also empty
          - jackpot_pid_set = empty → jackpot_applicable = False
        Revert (restore Path A loop) → GREEN.

        This is the canonical test for gap #1 closure.
        """
        jp = m275_gap1_summary["player_impact"]["machine_mechanics"]["jackpot"]
        assert jp["applicable"] is True, (
            f"jackpot.applicable must be True for M275 (gap #1 closure). "
            f"Got: {jp['applicable']!r}. "
            f"Full jackpot block: {json.dumps(jp, indent=2)}"
        )

    def test_m275_jackpot_ids_correct(self, m275_gap1_summary):
        """jackpot_ids must include 27502, 27503, 27504 (coordinator-verified)."""
        jp = m275_gap1_summary["player_impact"]["machine_mechanics"]["jackpot"]
        jackpot_ids_actual = set(jp.get("jackpot_ids", []))
        assert _EXPECTED_JACKPOT_IDS.issubset(jackpot_ids_actual), (
            f"jackpot_ids must contain {_EXPECTED_JACKPOT_IDS}. "
            f"Got: {jackpot_ids_actual}"
        )

    def test_m275_jackpot_id_count(self, m275_gap1_summary):
        """jackpot_id_count must be >= 3 (at least the 3 coordinator-verified PIDs)."""
        jp = m275_gap1_summary["player_impact"]["machine_mechanics"]["jackpot"]
        count = jp.get("jackpot_id_count", 0)
        assert count >= 3, (
            f"jackpot_id_count must be >= 3. Got: {count}. "
            f"jackpot_ids: {jp.get('jackpot_ids')}"
        )

    def test_m275_jackpot_detection_source_tier3(self, m275_gap1_summary):
        """_detection_source must be 'tier3_pid_ge_10000' (coordinator-verified)."""
        jp = m275_gap1_summary["player_impact"]["machine_mechanics"]["jackpot"]
        src = jp.get("_detection_source", "")
        assert "tier3" in str(src), (
            f"_detection_source must contain 'tier3' for M275 (PID >= 10000 path). "
            f"Got: {src!r}"
        )

    def test_m275_jackpot_rtp_contribution_in_range(self, m275_gap1_summary):
        """rtp_contribution_pp must be in [5.0, 6.0] (coordinator says ~5.49)."""
        jp = m275_gap1_summary["player_impact"]["machine_mechanics"]["jackpot"]
        rtp = jp.get("rtp_contribution_pp", 0.0)
        assert _RTP_CONTRIBUTION_LO <= rtp <= _RTP_CONTRIBUTION_HI, (
            f"jackpot.rtp_contribution_pp must be in [{_RTP_CONTRIBUTION_LO}, "
            f"{_RTP_CONTRIBUTION_HI}]. Got: {rtp:.4f}. "
            f"Coordinator verified value is ~5.49."
        )

    def test_m275_jackpot_trigger_spins_positive(self, m275_gap1_summary):
        """trigger_spins must be > 0 (jackpot events observed in M275 data)."""
        jp = m275_gap1_summary["player_impact"]["machine_mechanics"]["jackpot"]
        trigger_spins = jp.get("trigger_spins", 0)
        assert trigger_spins > 0, (
            f"trigger_spins must be > 0 for M275 (jackpot events exist). "
            f"Got: {trigger_spins}"
        )
