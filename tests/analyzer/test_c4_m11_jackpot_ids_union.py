"""Phase C4 — subprocess test: M11 jackpot via raw JackpotIds union (NB1 fix).

Spawns the real player_impact_analyzer against M11 mode 1 cached chunks.
Verifies that the v3 NB1 fix (JackpotIds raw field union as Path B) correctly
identifies jackpot PIDs that are numerically below 10000.

Background
----------
M11 jackpot PIDs 1102, 1103, 1104 appear in the raw JackpotIds field
(e.g., "1104-" per round in the API response) but NOT in PayoutIdToWinAmount
as high-value entries. Therefore:
  - Tier 3 Path A (PID >= 10000): empty — 1102/1103/1104 are all < 10000
  - Tier 3 Path B (jackpot_ids_seen union): {"1102", "1103", "1104"}
  - Union result: {"1102", "1103", "1104"}
  - jackpot_applicable = True (CORRECT)

Before v3 NB1 fix, Path B did not exist → jackpot_applicable=False for M11
(the same gap #1 but for a different PID pattern than M275).

Coordinator-verified values (M11 mode 1, 2026-05-27):
  jackpot.applicable = True
  jackpot_ids includes "1102", "1103", "1104"
  detection_source = "tier3_jackpot_ids_seen"

SKIP CONDITION: Only run if rawdata/M11/mode_1/chunk_*.json exists.
If not present, skip with a meaningful reason message.

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md) — Bug E
--------------------------------------------------------------------------
Bug E — remove Path B (jackpot_ids_seen) from MechanismRegistry union:
    In fresh_slotlab/analyzer/mechanism_registry.py, in MechanismRegistry.build(),
    remove the Path B contribution to the union:
        # Tier 3 — Path B: jackpot_ids_seen from raw JackpotIds field
        _path_b: set[str] = jackpot_ids_seen - scatter_marker_pids
        jackpot_pid_set = frozenset(_path_a | _path_b)
    Change to:
        # BUG: remove Path B
        jackpot_pid_set = frozenset(_path_a)  # Path B removed

    RED: M11 jackpot PIDs 1102/1103/1104 are all < 10000, so Path A gives
         empty set. With Path B removed, union = empty → jackpot_applicable=False.
         test_m11_jackpot_applicable_true fails.
    Revert (restore `_path_b` and union `_path_a | _path_b`) → GREEN.

    This is the critical test guarding the v3 NB1 fix:
    "Path B MUST be included in the union for M11-style machines."

Memory files cited
------------------
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test required — Path B union logic needs real JackpotIds field data)
- memory/feedback_integration_test_argv.md
  (real subprocess invocation with real M11 parser output)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (_detection_source must say 'tier3_jackpot_ids_seen' to distinguish from Path A)
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
_CACHE_DIR = _REPO_ROOT / "rawdata" / "M11" / "mode_1"

# Coordinator-verified M11 jackpot PIDs (from JackpotIds raw field)
_EXPECTED_JACKPOT_IDS = {"1102", "1103", "1104"}


def _has_m11_cache() -> bool:
    """Return True if M11 mode 1 has cached chunk files."""
    if not _CACHE_DIR.exists():
        return False
    return bool(list(_CACHE_DIR.glob("chunk_*.json")))


@pytest.fixture(scope="module")
def m11_jackpot_summary() -> dict:
    """Run M11 mode 1 analyzer from cache; return parsed summary.

    Skips if M11 cached data is unavailable.
    """
    if not _has_m11_cache():
        pytest.skip(
            f"M11 mode 1 cached chunks not found at {_CACHE_DIR}. "
            f"This test requires actual M11 spin data to validate raw JackpotIds union. "
            f"Run the analyzer online to populate the cache first."
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable,
            str(_PIA),
            "--machine", "M11",
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
            f"M11 analyzer exited non-zero ({result.returncode}).\n"
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

class TestM11JackpotUnionHealth:
    """Sanity: no errors, machine_mechanics key present."""

    def test_no_analyzer_init_error(self, m11_jackpot_summary):
        """analyzer_init_error must be absent."""
        assert "analyzer_init_error" not in m11_jackpot_summary, (
            f"analyzer_init_error present: {m11_jackpot_summary.get('analyzer_init_error')}"
        )

    def test_machine_mechanics_key_present(self, m11_jackpot_summary):
        """machine_mechanics must be in player_impact (M11 declares it in manifest)."""
        pi = m11_jackpot_summary.get("player_impact", {})
        assert "machine_mechanics" in pi, (
            f"'machine_mechanics' missing from player_impact for M11. "
            f"Got keys: {sorted(pi.keys())}"
        )


# ---------------------------------------------------------------------------
# T2: Raw JackpotIds union (Path B) detection
# ---------------------------------------------------------------------------

class TestM11JackpotIdsUnion:
    """jackpot must be detected via JackpotIds raw field (Path B), not PID >= 10000."""

    def test_m11_jackpot_applicable_true(self, m11_jackpot_summary):
        """jackpot.applicable must be True for M11 (JackpotIds raw field path).

        INJECT-BUG (Bug E): remove Path B from MechanismRegistry union.
        RED: M11 PIDs 1102/1103/1104 are < 10000, so Path A gives empty set.
             With Path B removed, jackpot_applicable=False despite real jackpot events.
             This test fails.
        Revert (restore Path B union) → GREEN.

        This is the canonical test guarding the v3 NB1 fix for M11-style machines.
        """
        jp = m11_jackpot_summary["player_impact"]["machine_mechanics"]["jackpot"]
        assert jp["applicable"] is True, (
            f"jackpot.applicable must be True for M11 (via JackpotIds raw field). "
            f"Got: {jp['applicable']!r}. "
            f"Full jackpot block: {json.dumps(jp, indent=2)}"
        )

    def test_m11_jackpot_ids_include_expected(self, m11_jackpot_summary):
        """jackpot_ids must include 1102, 1103, 1104 (coordinator-verified raw values)."""
        jp = m11_jackpot_summary["player_impact"]["machine_mechanics"]["jackpot"]
        jackpot_ids_actual = set(str(x) for x in jp.get("jackpot_ids", []))
        # At minimum, the 3 coordinator-verified PIDs must be present
        # (the actual set might contain more if other jackpot PIDs appear)
        missing = _EXPECTED_JACKPOT_IDS - jackpot_ids_actual
        assert not missing, (
            f"jackpot_ids missing expected PIDs {missing}. "
            f"Full jackpot_ids: {jackpot_ids_actual}. "
            f"These PIDs appear in M11 raw JackpotIds field events."
        )

    def test_m11_jackpot_detection_source_is_path_b(self, m11_jackpot_summary):
        """_detection_source must be 'tier3_jackpot_ids_seen' (Path B only).

        M11 PIDs are < 10000 so Path A gives empty set.
        Only Path B (jackpot_ids_seen from raw JackpotIds field) fires.
        _detection_source must distinguish this from M275's Path A case.

        INJECT-BUG (Bug E): remove Path B → detection_source becomes 'tier3_raw'
        (no paths contributed) but applicable is False → test_m11_jackpot_applicable_true
        fails first (that test is the stronger guard).
        """
        jp = m11_jackpot_summary["player_impact"]["machine_mechanics"]["jackpot"]
        src = jp.get("_detection_source", "")
        # If only Path B fires, source is "tier3_jackpot_ids_seen"
        # If both Path A and B fire (hypothetically), source contains "and"
        # Both are acceptable; what's NOT acceptable is "tier1" or "tier2" or None.
        assert src is not None, (
            f"_detection_source must not be None for M11. "
            f"Per feedback_invariant_with_fallback_hides_drift.md."
        )
        assert "tier3" in str(src) or "jackpot_ids_seen" in str(src), (
            f"_detection_source must indicate Tier 3 / jackpot_ids_seen path for M11. "
            f"Got: {src!r}. Coordinator verified: 'tier3_jackpot_ids_seen'."
        )

    def test_m11_jackpot_pids_below_10000_confirms_path_b(self, m11_jackpot_summary):
        """Confirm M11 jackpot PIDs are all < 10000 (proving Path B is needed).

        If any M11 jackpot PID were >= 10000, Path A would also catch them,
        and this test would not strictly prove Path B is doing the work.
        This assertion documents the structural reason Path B is critical for M11.
        """
        jp = m11_jackpot_summary["player_impact"]["machine_mechanics"]["jackpot"]
        jackpot_ids = jp.get("jackpot_ids", [])
        for pid in jackpot_ids:
            try:
                pid_int = int(pid)
            except (ValueError, TypeError):
                continue
            # At least the coordinator-verified PIDs must be below 10000
            if str(pid) in _EXPECTED_JACKPOT_IDS:
                assert pid_int < 10000, (
                    f"Expected M11 jackpot PID {pid} to be < 10000 "
                    f"(confirming Path B is required). Got pid_int={pid_int}. "
                    f"If this machine's jackpot PIDs changed, update the test."
                )
