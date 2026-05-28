"""R2 Phase 2 CR-1 regression: _bonus_chain_dynamics_data stash still populated.

After C-1 removes the F6 inline write of summary["player_impact"]["bonus_chain_dynamics"],
the stash builder must still produce summary["_bonus_chain_dynamics_data"] by reading
the LOCAL variable `bonus_chain_dynamics` (in scope from ~pia:4011).

This test locks that invariant: run PIA against M275 cached chunks and assert that
the stash key is present in the output JSON (bonus_chain_dynamics section non-empty).
Also asserts that machine_mechanics.freespin.fs_chain_spins > 0 for M275, which
proves the full dependency path bonus_chain_dynamics → machine_mechanics still works.

Inject-bug recipe (per feedback_enumerate_safety_paths.md)
----------------------------------------------------------
In player_impact_analyzer.py, revert the stash builder to read the summary key:
    "bonus_chain_dynamics": summary["player_impact"]["bonus_chain_dynamics"],
While keeping the inline write removed.  This produces:
    KeyError: 'bonus_chain_dynamics'  (since the summary key no longer exists)
which cascades to a Region 2 SystemExit(1) and BCD absent from the output.
The test turns RED (summary_path does not exist or has analyzer_init_error).
Revert (restore local-var read) -> GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md — inject-bug mandatory
- memory/feedback_perf_claim_needs_e2e_event_stream.md — real subprocess / real
  cached chunks to verify the actual runtime path (not just unit mocks)
- memory/feedback_no_proactive_fetch.md — only M275/M14 cached chunks used
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA_PATH = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_M275_CACHE = _REPO_ROOT / "rawdata" / "M275" / "mode_1"
_M14_CACHE = _REPO_ROOT / "rawdata" / "M14" / "mode_1"


def _m275_cache_available() -> bool:
    return _M275_CACHE.exists() and bool(list(_M275_CACHE.glob("chunk_*.json")))


def _m14_cache_available() -> bool:
    return _M14_CACHE.exists() and bool(list(_M14_CACHE.glob("chunk_*.json")))


_SKIP_NO_M275 = pytest.mark.skipif(
    not _m275_cache_available(),
    reason=f"M275 mode_1 cached chunks not found at {_M275_CACHE}",
)
_SKIP_NO_M14 = pytest.mark.skipif(
    not _m14_cache_available(),
    reason=f"M14 mode_1 cached chunks not found at {_M14_CACHE}",
)


def _pia_argv(machine: str, cache_dir: Path, output_dir: str) -> list[str]:
    return [
        str(_PIA_PATH),
        "--machine", machine,
        "--rtp-mode", "1",
        "--from-cache", str(cache_dir),
        "--output-dir", output_dir,
        "--bet", "1000",
    ]


# ---------------------------------------------------------------------------
# Test 1 — CR-1: stash key present + bonus_chain_dynamics non-empty (M275)
# ---------------------------------------------------------------------------

@_SKIP_NO_M275
class TestCR1StashStillPopulatedM275:
    """After C-1 inline-write removal, _bonus_chain_dynamics_data stash built from local var.

    M275 is the canonical machine that exercises the full bonus_chain_dynamics
    path (bonus_chain_count > 0, chain_count > 0, freespin applicable).

    Assertions:
        1. PIA exits 0 (no SystemExit / KeyError cascade).
        2. player_impact_summary.json exists in output_dir.
        3. "bonus_chain_dynamics" key is present in summary["player_impact"].
        4. bonus_chain_dynamics["applicable"] is True (M275 has chains).
        5. bonus_chain_dynamics["chain_count"] > 0.
        6. summary["player_impact"]["machine_mechanics"]["free_spin"]["chain_spins"] > 0
           (the dependency path bonus_chain_dynamics → machine_mechanics still works).
        7. "analyzer_init_error" is NOT in the summary (no Region 2 cascade).
    """

    def test_cr1_stash_still_populated_m275(self, monkeypatch):
        """C-1 stash uses local var — bonus_chain_dynamics still populated for M275."""
        import fresh_slotlab.player_impact_analyzer as _pia_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(sys, "argv", _pia_argv("M275", _M275_CACHE, tmpdir))

            # Must NOT raise SystemExit (no Region 2 cascade from missing stash)
            _pia_mod.main()

            summary_path = Path(tmpdir) / "player_impact_summary.json"

            # Assertion 2: JSON exists
            assert summary_path.exists(), (
                f"player_impact_summary.json NOT FOUND at {summary_path}. "
                "C-1 stash fix broken — likely KeyError cascade from stash builder "
                "trying to read the removed summary key."
            )

            summary = json.loads(summary_path.read_bytes())

            # Assertion 7: no Region 2 cascade
            assert "analyzer_init_error" not in summary, (
                f"analyzer_init_error present — CR-1 cascade occurred: "
                f"{summary.get('analyzer_init_error')}"
            )

            pi = summary.get("player_impact", {})

            # Assertion 3: bonus_chain_dynamics key present
            assert "bonus_chain_dynamics" in pi, (
                f"player_impact.bonus_chain_dynamics MISSING from output. "
                f"Keys: {sorted(pi.keys())}"
            )

            bcd = pi["bonus_chain_dynamics"]

            # Assertion 4: applicable=True for M275
            assert bcd.get("applicable") is True, (
                f"bonus_chain_dynamics.applicable must be True for M275, "
                f"got {bcd.get('applicable')!r}"
            )

            # Assertion 5: chain_count > 0
            assert bcd.get("chain_count", 0) > 0, (
                f"bonus_chain_dynamics.chain_count must be > 0 for M275, "
                f"got {bcd.get('chain_count')!r}"
            )

            # Assertion 6: machine_mechanics.free_spin.chain_spins > 0
            mm = pi.get("machine_mechanics", {})
            fs = mm.get("free_spin", {})
            fs_chain_spins = fs.get("chain_spins", 0)
            assert fs_chain_spins > 0, (
                f"machine_mechanics.free_spin.chain_spins must be > 0 for M275 "
                f"(bonus_chain_dynamics → machine_mechanics REQUIRES path). "
                f"Got chain_spins={fs_chain_spins!r}. "
                f"free_spin block: {fs}"
            )


# ---------------------------------------------------------------------------
# Test 2 — CR-1: M14 clean run — no analyzer_init_error, no feature_errors
# ---------------------------------------------------------------------------

@_SKIP_NO_M14
class TestCR1M14CleanRun:
    """M14 has no bonus chains — bonus_chain_dynamics.applicable=False, no errors.

    Assertions:
        1. PIA exits 0.
        2. player_impact_summary.json exists.
        3. bonus_chain_dynamics present (written by plugin), applicable=False.
        4. No "analyzer_init_error" in summary.
        5. No mechanism_registry_unknown_override_* in feature_errors (no overrides).
    """

    def test_cr1_m14_clean_run(self, monkeypatch):
        """M14 clean run — no errors, bonus_chain_dynamics present but applicable=False."""
        import fresh_slotlab.player_impact_analyzer as _pia_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(sys, "argv", _pia_argv("M14", _M14_CACHE, tmpdir))
            _pia_mod.main()

            summary_path = Path(tmpdir) / "player_impact_summary.json"
            assert summary_path.exists(), (
                f"player_impact_summary.json NOT FOUND for M14 at {summary_path}."
            )

            summary = json.loads(summary_path.read_bytes())

            assert "analyzer_init_error" not in summary, (
                f"analyzer_init_error present for M14 clean run: "
                f"{summary.get('analyzer_init_error')}"
            )

            pi = summary.get("player_impact", {})
            assert "bonus_chain_dynamics" in pi, (
                f"bonus_chain_dynamics MISSING from M14 player_impact. "
                f"Keys: {sorted(pi.keys())}"
            )

            bcd = pi["bonus_chain_dynamics"]
            # M14 has no ReMarks-based freespin chains
            assert bcd.get("applicable") is False, (
                f"M14 bonus_chain_dynamics.applicable must be False, "
                f"got {bcd.get('applicable')!r}"
            )

            # No unknown override keys — M14 has no mechanism_overrides
            feature_errors = summary.get("feature_errors", {})
            unknown_keys = [
                k for k in feature_errors
                if k.startswith("mechanism_registry_unknown_override_")
            ]
            assert not unknown_keys, (
                f"Unexpected mechanism_registry_unknown_override_* entries for M14: "
                f"{unknown_keys}"
            )
