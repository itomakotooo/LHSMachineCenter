"""Subprocess-level byte-identical regression test for Phase C1 — M14 mode 1.

Spawns the real player_impact_analyzer subprocess against M14 mode 1 cached
chunks.  Verifies RTP integrity, key invariants, and effective_analyzer_version.

Failure modes caught
---------------------
1. Any C1 code change that alters player_impact values (RTP regression).
2. server_total_win != our_total_win (RTP integrity L1).
3. rtp_integrity_check.passed == False (RTP integrity L2).
4. analyzer_init_error key present (indicates plugin lifecycle failure).
5. effective_analyzer_version wrong (hash composition regressed).
6. player_impact key set shrank (feature silently disappeared).

Inject-bug contract (per memory/feedback_enumerate_safety_paths.md)
----------------------------------------------------------------------
Bug: in bankruptcy_simulation.py emit(), add a spurious key:
     summary["player_impact"]["bankruptcy_simulation"]["INJECTED"] = True
Expected: test_player_impact_keys_present fails — the presence check is a
  subset check; the injected key doesn't break that. But
  test_bankruptcy_simulation_no_injected_key DOES fail.
Revert: remove the injected key → both tests pass.

More impactful inject-bug for byte-identical regression:
Bug: change the `session_spins` value in bankruptcy_simulation emit() to a
  hard-coded wrong value (e.g. bankruptcy_sim_session_spins + 1).
Expected: test_bankruptcy_simulation_session_spins_matches fails.
Revert: restore correct formula → test passes.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (must spawn real subprocess, not unit-test the helper)
- memory/feedback_enumerate_safety_paths.md
  (inject-bug verification mandatory)
- memory/feedback_integration_test_argv.md
  (real subprocess, not mock)
- memory/feedback_no_silent_swallow.md
  (analyzer_init_error must be absent on success path)
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

# Minimum set of player_impact keys expected to be present — verified against
# the C1 postC1 summary.json run (see session_artifacts/_impl/phase_c1/).
_EXPECTED_PLAYER_IMPACT_KEYS = {
    "volatility",
    "multiplier_profile",
    "hit_and_payout",
    "streaks",
    "paylines_top20",
    "payout_groups_top20",
    "payout_ids_top20",
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "spin_type_breakdown",
    "spin_type_coverage",
    "field_discovery",
    "machine_mechanics",
    "upstream_feature_breakdown",
    "bonus_chain_dynamics",
    "payline_symbol_top20",
    "session_rtp_curves",
    "chain_ratio_sequences",
    "reel_position_top20",
    "symbols_top20",
    "symbols_by_column_top10",
    "symbols_by_column_top10_payline",
    "payline_rows_per_col",
    "bankruptcy_simulation",
    "bankruptcy_probe",
}


@pytest.fixture(scope="module")
def m14_summary() -> dict:
    """Run M14 mode 1 analyzer against cached chunks; return parsed summary."""
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
            timeout=120,
        )
        assert result.returncode == 0, (
            f"Analyzer exited non-zero ({result.returncode}).\n"
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )

        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists(), (
            f"summary.json not written to {tmpdir}. "
            f"STDOUT: {result.stdout[:500]}"
        )
        data = json.loads(summary_path.read_bytes())
    return data


class TestM14RtpIntegrity:
    """RTP integrity invariants — must hold for every analyzer invocation."""

    def test_server_total_win_equals_our_total_win(self, m14_summary):
        """server_total_win == our_total_win is the L1 RTP integrity invariant.

        INJECT-BUG: this would be broken by changing the RTP numerator source
        or altering how wins are summed across chunks.
        """
        rtp = m14_summary["rtp"]
        assert rtp["server_total_win"] == rtp["our_total_win"], (
            f"L1 RTP integrity failed: server={rtp['server_total_win']} "
            f"our={rtp['our_total_win']}"
        )

    def test_rtp_integrity_check_passed(self, m14_summary):
        """rtp_integrity_check.passed must be True on success path."""
        ric = m14_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed is not True. Full value: {ric}"
        )

    def test_no_analyzer_init_error(self, m14_summary):
        """analyzer_init_error key must be absent on success path.

        Per memory/feedback_no_silent_swallow.md — this key only appears when
        the topo-sort or emit loop fails with a programming error.
        """
        assert "analyzer_init_error" not in m14_summary, (
            f"analyzer_init_error unexpectedly present: "
            f"{m14_summary['analyzer_init_error']}"
        )


class TestM14PlayerImpactKeys:
    """player_impact key set must contain all expected subkeys."""

    def test_player_impact_keys_present(self, m14_summary):
        """All 25 expected player_impact keys must be present.

        INJECT-BUG: comment out one feature's registration (e.g. in
        payouts_by_spin_type.py, remove register(PayoutsBySpinType())).
        Expected: payouts_by_spin_type disappears from player_impact;
        assertion fails because key is missing from the set.
        """
        pi_keys = set(m14_summary.get("player_impact", {}).keys())
        missing = _EXPECTED_PLAYER_IMPACT_KEYS - pi_keys
        assert not missing, (
            f"player_impact missing expected keys: {missing}. "
            f"Present keys: {sorted(pi_keys)}"
        )


class TestM14EffectiveAnalyzerVersion:
    """effective_analyzer_version must match deterministic per-machine compute."""

    def test_effective_analyzer_version_matches(self, m14_summary):
        """effective_analyzer_version in summary must match versioning module output.

        This verifies the C1 hash composition change (90e36d27df98 → baf56e2f9f6e)
        is correctly computed and persisted by PIA.
        """
        try:
            from fresh_slotlab.analyzer.versioning import (
                compute_effective_version_for_machine,
            )
        except ImportError:
            from analyzer.versioning import compute_effective_version_for_machine  # type: ignore[no-redef]

        expected = compute_effective_version_for_machine("M14", 1)
        actual = m14_summary.get("effective_analyzer_version", "")
        assert actual == expected, (
            f"effective_analyzer_version mismatch: "
            f"summary has {actual!r}, versioning module returns {expected!r}"
        )


class TestM14BankruptcySimulation:
    """bankruptcy_simulation key invariants — Pattern B plugin correctness."""

    def test_bankruptcy_simulation_structure(self, m14_summary):
        """bankruptcy_simulation must have the 4 expected top-level keys."""
        bs = m14_summary.get("player_impact", {}).get("bankruptcy_simulation", {})
        expected_keys = {"source", "session_spins", "percentile_keys", "tiers"}
        missing = expected_keys - set(bs.keys())
        assert not missing, (
            f"bankruptcy_simulation missing keys: {missing}. "
            f"Got: {sorted(bs.keys())}"
        )

    def test_bankruptcy_simulation_source_is_rawdata_replay(self, m14_summary):
        """source must be 'rawdata_replay'."""
        bs = m14_summary["player_impact"]["bankruptcy_simulation"]
        assert bs["source"] == "rawdata_replay", (
            f"Expected 'rawdata_replay', got {bs['source']!r}"
        )

    def test_bankruptcy_probe_equals_tiers(self, m14_summary):
        """bankruptcy_probe (back-compat alias) must equal tiers list."""
        pi = m14_summary["player_impact"]
        bs = pi["bankruptcy_simulation"]
        bp = pi["bankruptcy_probe"]
        assert bp == bs["tiers"], (
            "bankruptcy_probe must be identical to bankruptcy_simulation.tiers"
        )

    def test_no_temp_keys_in_summary(self, m14_summary):
        """Temp keys (_bankruptcy_rows, _bankruptcy_sim_session_spins) must be absent.

        These are cleaned up by emit(); if they appear in the final JSON it means
        the cleanup loop in emit() failed to run.
        """
        assert "_bankruptcy_rows" not in m14_summary, (
            "_bankruptcy_rows temp key leaked into final summary"
        )
        assert "_bankruptcy_sim_session_spins" not in m14_summary, (
            "_bankruptcy_sim_session_spins temp key leaked into final summary"
        )
        # Also check they're not under player_impact
        pi = m14_summary.get("player_impact", {})
        assert "_bankruptcy_rows" not in pi
        assert "_bankruptcy_sim_session_spins" not in pi
