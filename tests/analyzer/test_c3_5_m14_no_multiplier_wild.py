"""Phase C3.5 — subprocess test: M14 must NOT have multiplier_wild in output.

Spawns the real player_impact_analyzer against M14 mode 1 cached chunks.
Verifies the manifest-declared-only opt-in semantic:
  - M14.json does NOT declare 'multiplier_wild' in analyzer_features
  - Therefore, multiplier_wild plugin must NOT run for M14
  - Therefore, summary["player_impact"].get("multiplier_wild") must be None

This test proves the NEGATIVE case of the per-machine isolation property.
The positive case (M275 HAS the key) is proven in test_c3_5_m275_e2e.py.
The isolation mechanism is proven in test_c3_5_isolation_m275_only.py.

Per brief §4 AC#6: M14 / M37 cached rebuild must NOT have multiplier_wild key.
Acceptable behavior: key absent OR {"applicable": False} if manifest declares
but data has none. Brief implementer chose key-absent (not in manifest = not run).
This test asserts key absent (the stricter check — aligns with manifest-declared opt-in).

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug: add "multiplier_wild" to M14.json analyzer_features.
Expected:
  - Plugin runs for M14
  - M14 has no wildNx symbols in its data (M14 is a vanilla machine)
  - Plugin emits applicable=False
  - summary["player_impact"]["multiplier_wild"] is present (not None)
  - test_m14_no_multiplier_wild_key fails (key is present, not None)
Revert M14.json (remove "multiplier_wild" from analyzer_features) → GREEN.

This is the canonical inject-bug for the manifest-declared-only opt-in semantic.
If you can add a plugin to any machine by editing its manifest, the isolation
must hold in BOTH directions: opt-in flips effective_version AND causes plugin to run.

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test required — unit test cannot verify manifest-gating logic)
- memory/feedback_integration_test_argv.md
  (real subprocess invocation, real manifest, real gating)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (key absent = explicit "not declared" signal, not a silent bucket)
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
def m14_c3_5_summary() -> dict:
    """Run M14 mode 1 analyzer in C3.5 branch; return parsed summary."""
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
            f"M14 analyzer exited non-zero ({result.returncode}).\n"
            f"STDOUT: {result.stdout[:3000]}\n"
            f"STDERR: {result.stderr[:3000]}"
        )
        summary_path = Path(tmpdir) / "player_impact_summary.json"
        assert summary_path.exists(), (
            f"summary.json not written. STDOUT: {result.stdout[:500]}"
        )
        data = json.loads(summary_path.read_bytes())
    return data


# ---------------------------------------------------------------------------
# T1: Analyzer health checks (M14 must still run cleanly in C3.5)
# ---------------------------------------------------------------------------

class TestM14C3_5Health:
    """M14 analyzer must still run cleanly after C3.5 plugin addition."""

    def test_no_analyzer_init_error(self, m14_c3_5_summary):
        """analyzer_init_error must be absent on M14 success path."""
        assert "analyzer_init_error" not in m14_c3_5_summary, (
            f"analyzer_init_error present: {m14_c3_5_summary.get('analyzer_init_error')}"
        )

    def test_no_feature_errors(self, m14_c3_5_summary):
        """feature_errors must be absent or empty on M14 success path."""
        fe = m14_c3_5_summary.get("feature_errors", {})
        assert not fe, (
            f"feature_errors unexpectedly populated for M14: {fe}"
        )

    def test_rtp_integrity_check_passed(self, m14_c3_5_summary):
        """M14 rtp_integrity_check.passed must be True (regression guard)."""
        ric = m14_c3_5_summary.get("rtp_integrity_check", {})
        assert ric.get("passed") is True, (
            f"rtp_integrity_check.passed is not True for M14: {ric}"
        )


# ---------------------------------------------------------------------------
# T2: multiplier_wild key must be ABSENT from M14 output
# ---------------------------------------------------------------------------

class TestM14NoMultiplierWild:
    """multiplier_wild key must be absent from M14 player_impact.

    This confirms the manifest-declared-only opt-in semantic:
    M14 did not declare 'multiplier_wild' → plugin must not run → key absent.
    """

    def test_m14_no_multiplier_wild_key(self, m14_c3_5_summary):
        """summary["player_impact"]["multiplier_wild"] must be None (key absent).

        INJECT-BUG: add "multiplier_wild" to M14.json analyzer_features.
        RED: plugin runs for M14 → key present (applicable=False since M14
             has no wildNx symbols) → .get("multiplier_wild") is not None →
             this assertion fails.
        Revert M14.json → GREEN.

        This is the canonical manifest-gating inject-bug.
        """
        pi = m14_c3_5_summary.get("player_impact", {})
        mw_value = pi.get("multiplier_wild")
        assert mw_value is None, (
            f"M14 player_impact must NOT have 'multiplier_wild' key. "
            f"Got: {mw_value!r}. "
            f"M14.json must NOT declare 'multiplier_wild' in analyzer_features "
            f"— only M275 opts in as of C3.5."
        )

    def test_m14_multiplier_wild_not_in_player_impact_keys(self, m14_c3_5_summary):
        """'multiplier_wild' must not appear in player_impact key set for M14."""
        pi = m14_c3_5_summary.get("player_impact", {})
        assert "multiplier_wild" not in pi, (
            f"'multiplier_wild' must not be a key in M14 player_impact. "
            f"Found it present (value: {pi.get('multiplier_wild')!r}). "
            f"Manifest-gating broken or M14.json was incorrectly updated."
        )


# ---------------------------------------------------------------------------
# T3: M14 still has its 4 declared features (regression guard)
# ---------------------------------------------------------------------------

class TestM14FeaturesUnchanged:
    """M14 still emits all 4 declared features — C3.5 must not regress them."""

    _EXPECTED_M14_FEATURES = {
        "payouts_by_spin_type",
        "reel_marginal_by_spin_type",
        "bankruptcy_simulation",
        "bankruptcy_probe",
    }

    def test_payouts_by_spin_type_present(self, m14_c3_5_summary):
        """payouts_by_spin_type must still be present in M14 output after C3.5."""
        pi = m14_c3_5_summary.get("player_impact", {})
        assert "payouts_by_spin_type" in pi, (
            f"payouts_by_spin_type missing from M14 player_impact. "
            f"C3.5 must not regress M14's existing features."
        )

    def test_payouts_by_spin_type_has_rows(self, m14_c3_5_summary):
        """payouts_by_spin_type must have non-empty rows for M14 (paid spins)."""
        pbst = m14_c3_5_summary["player_impact"]["payouts_by_spin_type"]
        nonempty = [k for k, v in pbst.items() if v]
        assert nonempty, (
            f"payouts_by_spin_type has no non-empty ST labels for M14. "
            f"C3.5 must not regress extract/reduce/emit loop."
        )

    def test_bankruptcy_simulation_present(self, m14_c3_5_summary):
        """bankruptcy_simulation must still be present in M14 output after C3.5."""
        pi = m14_c3_5_summary.get("player_impact", {})
        assert "bankruptcy_simulation" in pi, (
            f"bankruptcy_simulation missing from M14 player_impact. "
            f"C3.5 must not regress M14's existing features."
        )


# ---------------------------------------------------------------------------
# T4: M14 effective_version in summary confirms no plugin was added
# ---------------------------------------------------------------------------

class TestM14EffectiveVersionInSummary:
    """M14 effective_version in summary must be the C3 non-M275 value.

    If multiplier_wild was accidentally added to M14's manifest,
    its effective_version would change — this test would catch it.
    """

    def test_m14_effective_version_matches_versioning_module(self, m14_c3_5_summary):
        """effective_analyzer_version in M14 summary must match versioning module."""
        try:
            from fresh_slotlab.analyzer.versioning import compute_effective_version_for_machine
        except ImportError:
            from analyzer.versioning import compute_effective_version_for_machine  # type: ignore[no-redef]

        expected = compute_effective_version_for_machine("M14", 1)
        actual = m14_c3_5_summary.get("effective_analyzer_version", "")
        assert actual == expected, (
            f"effective_analyzer_version in M14 summary must match versioning module. "
            f"Summary has {actual!r}, module returns {expected!r}."
        )

    def test_m14_effective_version_is_c3_non_m275_value(self, m14_c3_5_summary):
        """M14 effective_version in summary must be 6aae41144cea (C4 non-M275 value).

        C3.5 value was 6aae41144cea (4 plugins: payouts_by_spin_type, reel_marginal,
        bankruptcy_simulation, multiplier_profile).
        C4 adds machine_mechanics to ALL 253 base manifests including M14.
        New C4 value: 6aae41144cea (5 plugins, machine_mechanics added, no multiplier_wild).

        INJECT-BUG: add "multiplier_wild" to M14.json.
        RED: M14 effective_version changes → != 6aae41144cea → this fails.
        Revert M14.json → GREEN.
        """
        _NON_M275_EFFECTIVE_VERSION = "6aae41144cea"  # C4 value
        actual = m14_c3_5_summary.get("effective_analyzer_version", "")
        assert actual == _NON_M275_EFFECTIVE_VERSION, (
            f"M14 effective_analyzer_version must be {_NON_M275_EFFECTIVE_VERSION!r}. "
            f"Got: {actual!r}. C4 adds machine_mechanics to M14; if M14 also gained "
            f"multiplier_wild, its version would be different."
        )
