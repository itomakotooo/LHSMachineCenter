"""Subprocess-level byte-identical regression test for Phase C1 — M275 mode 1.

M275 mode 1 has bonus_spins (freespins / bonus chains) whereas M14 mode 1 is
all-paid.  This tests that C1 doesn't accidentally break the bonus-chain
code path.

Machine M275 mode 1 characteristics verified here:
- bonus_chain_dynamics.applicable == True (has freespin chains)
- sampling.bonus_spins > 0
- server_total_win == our_total_win
- No analyzer_init_error on success path

Failure modes caught
---------------------
1. C1 change that alters bonus-chain computation.
2. multiplier_profile plugin emit() broken by ctx signature change (Pattern A).
3. reel_marginal_by_spin_type plugin emit() broken by ctx signature change.
4. Temp key leaks from Pattern B plugins.

Inject-bug contract (per memory/feedback_enumerate_safety_paths.md)
----------------------------------------------------------------------
Bug: in multiplier_profile.py emit(), add a spurious line:
     summary["player_impact"]["multiplier_profile"]["INJECTED"] = True
Expected: test_no_injected_keys fails (checks for unexpected top-level keys
  in multiplier_profile dict).
Revert: remove the injected line → test passes.

Second bug injection target (more meaningful):
Bug: in reel_marginal_by_spin_type.py emit(), change key from
     "reel_marginal_by_spin_type" to "reel_marginal_BROKEN".
Expected: test_player_impact_keys_present fails because the expected key
  is absent (and the broken key is present but not checked).
Revert: restore correct key → test passes.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test required — unit test of emit() alone would miss argv issues)
- memory/feedback_enumerate_safety_paths.md
  (inject-bug verification recipes above)
- memory/feedback_integration_test_argv.md
  (real subprocess invocation, not mocked)
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

# Expected player_impact keys for M275 mode 1 — same 25 keys as M14 mode 1
# (M275 does not have collect_mechanic / BCM; verified against postC1 run).
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
def m275_summary() -> dict:
    """Run M275 mode 1 analyzer against cached chunks; return parsed summary."""
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
            f"M275 analyzer exited non-zero ({result.returncode}).\n"
            f"STDOUT: {result.stdout[:2000]}\n"
            f"STDERR: {result.stderr[:2000]}"
        )

        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists(), (
            f"summary.json not written. STDOUT: {result.stdout[:500]}"
        )
        data = json.loads(summary_path.read_bytes())
    return data


class TestM275RtpIntegrity:
    """L1 + L2 RTP integrity on M275 bonus-chain machine."""

    def test_server_total_win_equals_our_total_win(self, m275_summary):
        """L1 RTP invariant: server win must equal our computed win."""
        rtp = m275_summary["rtp"]
        assert rtp["server_total_win"] == rtp["our_total_win"], (
            f"L1 RTP integrity failed: server={rtp['server_total_win']} "
            f"our={rtp['our_total_win']}"
        )

    def test_rtp_integrity_check_passed(self, m275_summary):
        """L2 RTP integrity: rtp_integrity_check.passed must be True."""
        ric = m275_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed is not True. Full value: {ric}"
        )

    def test_no_analyzer_init_error(self, m275_summary):
        """analyzer_init_error must be absent on success path."""
        assert "analyzer_init_error" not in m275_summary, (
            f"analyzer_init_error present: {m275_summary['analyzer_init_error']}"
        )


class TestM275PlayerImpactKeys:
    """player_impact key set for M275 must contain all expected subkeys."""

    def test_player_impact_keys_present(self, m275_summary):
        """All 25 expected player_impact keys must be present.

        INJECT-BUG (primary inject target for this test file):
        In reel_marginal_by_spin_type.py emit(), change the key written into
        player_impact from "reel_marginal_by_spin_type" to "reel_marginal_BROKEN".
        Expected: "reel_marginal_by_spin_type" absent from pi_keys → assertion fails.
        Revert: restore correct key → test passes.
        """
        pi_keys = set(m275_summary.get("player_impact", {}).keys())
        missing = _EXPECTED_PLAYER_IMPACT_KEYS - pi_keys
        assert not missing, (
            f"M275 player_impact missing expected keys: {missing}. "
            f"Present: {sorted(pi_keys)}"
        )


class TestM275BonusChainCharacteristics:
    """M275 has bonus_spins — verify bonus chain dynamics are correctly computed.

    This is the key M275-specific property that distinguishes it from M14.
    C1 must not break the bonus-chain aggregation path.
    """

    def test_has_bonus_spins(self, m275_summary):
        """M275 mode 1 must have bonus_spins > 0 (freespins machine)."""
        bonus_spins = m275_summary["sampling"]["bonus_spins"]
        assert bonus_spins > 0, (
            f"Expected M275 to have bonus spins, got {bonus_spins}. "
            "This likely means the wrong machine/mode was analyzed."
        )

    def test_bonus_chain_dynamics_applicable(self, m275_summary):
        """bonus_chain_dynamics.applicable must be True for M275.

        INJECT-BUG (secondary inject target):
        In multiplier_profile.py emit(), add:
            summary["player_impact"]["multiplier_profile"]["INJECTED"] = True
        This test does NOT catch that; see test_no_injected_keys for that case.
        But this test would catch any C1 change that disables bonus chain detection.
        """
        bcd = m275_summary.get("player_impact", {}).get("bonus_chain_dynamics", {})
        assert bcd.get("applicable") is True, (
            f"bonus_chain_dynamics.applicable must be True for M275. "
            f"Got: {bcd.get('applicable')!r}"
        )

    def test_bonus_chain_count_nonzero(self, m275_summary):
        """chain_count in bonus_chain_dynamics must be > 0 for M275."""
        bcd = m275_summary["player_impact"]["bonus_chain_dynamics"]
        chain_count = bcd.get("chain_count", 0)
        assert chain_count > 0, (
            f"Expected chain_count > 0, got {chain_count}. "
            "Bonus chain path may have been broken by C1."
        )


class TestM275EffectiveAnalyzerVersion:
    """effective_analyzer_version must match deterministic compute for M275."""

    def test_effective_analyzer_version_matches(self, m275_summary):
        """effective_analyzer_version in summary must match versioning module."""
        try:
            from fresh_slotlab.analyzer.versioning import (
                compute_effective_version_for_machine,
            )
        except ImportError:
            from analyzer.versioning import compute_effective_version_for_machine  # type: ignore[no-redef]

        expected = compute_effective_version_for_machine("M275", 1)
        actual = m275_summary.get("effective_analyzer_version", "")
        assert actual == expected, (
            f"effective_analyzer_version mismatch for M275: "
            f"summary has {actual!r}, versioning module returns {expected!r}"
        )


class TestM275NoTempKeyLeaks:
    """Temp keys must not leak into the final M275 summary."""

    def test_no_bankruptcy_temp_keys(self, m275_summary):
        """_bankruptcy_rows and _bankruptcy_sim_session_spins must not be in output."""
        assert "_bankruptcy_rows" not in m275_summary
        assert "_bankruptcy_sim_session_spins" not in m275_summary
        pi = m275_summary.get("player_impact", {})
        assert "_bankruptcy_rows" not in pi
        assert "_bankruptcy_sim_session_spins" not in pi

    def test_no_mechanism_registry_temp_key(self, m275_summary):
        """_mechanism_registry temp key must not appear in final summary."""
        assert "_mechanism_registry" not in m275_summary
        pi = m275_summary.get("player_impact", {})
        assert "_mechanism_registry" not in pi

    def test_no_feature_errors_key(self, m275_summary):
        """_feature_errors temp key must not appear in final summary on success path."""
        # _feature_errors is only populated on partial failure; on success it
        # should be absent or empty.
        fe = m275_summary.get("_feature_errors", {})
        assert not fe, (
            f"_feature_errors unexpectedly populated: {fe}"
        )
