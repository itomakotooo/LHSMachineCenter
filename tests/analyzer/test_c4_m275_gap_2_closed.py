"""Phase C4 — subprocess test: M275 gap #2 closed (free_spin.applicable=True).

Spawns the real player_impact_analyzer against M275 mode 1 cached chunks.
Verifies that gap #2 (free_spin.applicable=false despite freespin rounds present)
is CLOSED by the C4 Mechanism Registry implementation.

Background
----------
Before C4, the PIA inline machine_mechanics block used:
  free_spin_applicable = (freespin_chain_spins > 0)
For M275, freespin chains are tracked via bonus_chain_dynamics (ReMarks-based
annotation), NOT via the CurFreeSpin raw field. This means freespin_chain_spins
== 0 even though M275 has real freespin chains.

After C4, the MechanismRegistry uses Tier 2:
  len(bonus_chain_lengths) > 0 → freespin_applicable=True
M275's bonus_chain_lengths is non-empty (chains of length 10 each).

Coordinator-verified values (M275 mode 1, 2026-05-27):
  free_spin.applicable = True
  chain_spins = 9090 (BCD bonus_round_count)
  detection_source = "tier2_bonus_chain_lengths"
  max_chain_length = 10 (avg_chain_length from BCD, rounded)

Per memory/feedback_perf_claim_needs_e2e_event_stream.md:
  Unit tests of MechanismRegistry.build() alone cannot catch:
  - PIA wiring (5-site registration)
  - bonus_chain_lengths accumulator correctly built in PIA merge loop
  - Registry passed through PipelineContext
  This subprocess test catches all three.

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md) — Bug D
--------------------------------------------------------------------------
Bug D — make Tier 2 freespin detection require an impossibly high threshold:
    In fresh_slotlab/analyzer/mechanism_registry.py, in MechanismRegistry.build(),
    change the Tier 2 freespin detection:
        if bonus_chain_lengths:
            freespin_applicable = True
    to:
        if len(bonus_chain_lengths) > 9999:  # BUG: require 10000+ chains
            freespin_applicable = True

    RED: M275 mode 1 has ~908 chains (len(bonus_chain_lengths) = 908).
         908 > 9999 is False → freespin_applicable=False even though chains exist.
         test_m275_freespin_applicable_true fails.
    Revert (restore original `if bonus_chain_lengths:`) → GREEN.

    M275 has chain_count=908 (coordinator-verified), so the threshold 9999
    is the critical number that pushes it below detection.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test required — unit tests alone don't catch PIA merge loop bugs)
- memory/feedback_integration_test_argv.md
  (real subprocess invocation, not mocked)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (_detection_source must explicitly record tier2 signal)
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

# Coordinator-verified values for M275 mode 1
_EXPECTED_CHAIN_SPINS = 9090  # bonus_round_count from BCD
_EXPECTED_MAX_CHAIN_LENGTH = 10
# Tolerance: ±20% for chain_spins (BCD data may differ slightly across runs)
_CHAIN_SPINS_TOLERANCE = 0.20


@pytest.fixture(scope="module")
def m275_gap2_summary() -> dict:
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

class TestM275Gap2Health:
    """Sanity: no errors, machine_mechanics key present."""

    def test_no_analyzer_init_error(self, m275_gap2_summary):
        """analyzer_init_error must be absent."""
        assert "analyzer_init_error" not in m275_gap2_summary, (
            f"analyzer_init_error present: {m275_gap2_summary.get('analyzer_init_error')}"
        )

    def test_machine_mechanics_key_present(self, m275_gap2_summary):
        """machine_mechanics must be in player_impact."""
        pi = m275_gap2_summary.get("player_impact", {})
        assert "machine_mechanics" in pi, (
            f"'machine_mechanics' missing from player_impact. "
            f"Check all 5 plugin registration sites in PIA."
        )


# ---------------------------------------------------------------------------
# T2: Gap #2 closure — free_spin.applicable=True for M275
# ---------------------------------------------------------------------------

class TestM275Gap2FreespinApplicable:
    """free_spin.applicable must be True — gap #2 closed."""

    def test_m275_freespin_applicable_true(self, m275_gap2_summary):
        """free_spin.applicable must be True for M275.

        INJECT-BUG (Bug D): change Tier 2 freespin detection to:
            if len(bonus_chain_lengths) > 9999:
        RED: M275 has ~908 bonus chains (not > 9999) → freespin_applicable=False.
        Revert (restore `if bonus_chain_lengths:`) → GREEN.

        This is the canonical test for gap #2 closure.
        """
        fs = m275_gap2_summary["player_impact"]["machine_mechanics"]["free_spin"]
        assert fs["applicable"] is True, (
            f"free_spin.applicable must be True for M275 (gap #2 closure). "
            f"Got: {fs['applicable']!r}. "
            f"Full free_spin block: {json.dumps(fs, indent=2)}"
        )

    def test_m275_freespin_detection_source_tier2(self, m275_gap2_summary):
        """_detection_source must contain 'tier2' (bonus_chain_lengths path)."""
        fs = m275_gap2_summary["player_impact"]["machine_mechanics"]["free_spin"]
        src = fs.get("_detection_source", "")
        assert "tier2" in str(src), (
            f"_detection_source must contain 'tier2' for M275 freespin. "
            f"Got: {src!r}. Coordinator verified: 'tier2_bonus_chain_lengths'."
        )

    def test_m275_freespin_chain_spins_in_range(self, m275_gap2_summary):
        """chain_spins must be close to 9090 (coordinator-verified BCD bonus_round_count)."""
        fs = m275_gap2_summary["player_impact"]["machine_mechanics"]["free_spin"]
        chain_spins = fs.get("chain_spins", 0)
        lo = _EXPECTED_CHAIN_SPINS * (1 - _CHAIN_SPINS_TOLERANCE)
        hi = _EXPECTED_CHAIN_SPINS * (1 + _CHAIN_SPINS_TOLERANCE)
        assert lo <= chain_spins <= hi, (
            f"chain_spins must be in [{lo:.0f}, {hi:.0f}] "
            f"(coordinator says {_EXPECTED_CHAIN_SPINS}). "
            f"Got: {chain_spins}"
        )

    def test_m275_freespin_max_chain_length(self, m275_gap2_summary):
        """max_chain_length must be close to 10 (M275 freespin chains are 10 long)."""
        fs = m275_gap2_summary["player_impact"]["machine_mechanics"]["free_spin"]
        max_len = fs.get("max_chain_length", 0)
        # Allow some flex — M275 chains average 10, max may be 10 or slightly above
        assert 8 <= max_len <= 15, (
            f"max_chain_length must be close to 10 for M275. Got: {max_len}. "
            f"Coordinator verified: 10."
        )

    def test_m275_freespin_chain_rate_positive(self, m275_gap2_summary):
        """chain_rate must be > 0 (freespin chains occur at non-zero rate)."""
        fs = m275_gap2_summary["player_impact"]["machine_mechanics"]["free_spin"]
        chain_rate = fs.get("chain_rate", 0.0)
        assert chain_rate > 0.0, (
            f"chain_rate must be > 0 for M275 (has freespin chains). "
            f"Got: {chain_rate}"
        )

    def test_m275_freespin_schema_complete(self, m275_gap2_summary):
        """free_spin block must have all required schema keys."""
        fs = m275_gap2_summary["player_impact"]["machine_mechanics"]["free_spin"]
        required = {
            "applicable", "chain_spins", "chain_rate",
            "retriggers", "max_chain_length", "total_win",
            "rtp_contribution_pp", "_detection_source",
        }
        missing = required - set(fs.keys())
        assert not missing, (
            f"free_spin block missing required keys: {missing}. Got: {sorted(fs.keys())}"
        )
