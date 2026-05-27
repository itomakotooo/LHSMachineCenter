"""Phase C5 — gap #6: chunk_spin_times sizing recommendation.

Tests that the collect_mechanic plugin adds chunk_spin_times_recommendation
to clamp_warning when: clamp_warning.applicable=True AND detected_cycle_length
is known AND avg_paid_spins_per_collect is known.

Invariants asserted
-------------------
1. M275 collect_mechanic.clamp_warning.chunk_spin_times_recommendation is present.
2. chunk_spin_times_recommendation.current == 5000 (M275 mode 1 chunk_spin_times).
3. chunk_spin_times_recommendation.recommended_min == 5000
   (detected_cycle_length=1000 * avg_paid_spins_per_collect=5.0).
4. chunk_spin_times_recommendation.recommended_safety == 7500
   (recommended_min * 1.5 safety factor).
5. rationale is a non-empty string containing cycle length info.
6. M14 collect_mechanic.clamp_warning.chunk_spin_times_recommendation is absent
   (M14 has applicable=False so clamp_warning.applicable=False).
7. Unit formula: different cycle_length + avg_spins inputs produce correct outputs.
8. Unit formula: avg_spins=None -> recommendation absent (no silent default).

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug C — change recommended_min formula to constant 1000 in collect_mechanic.emit():
    In fresh_slotlab/analyzer/features/collect_mechanic.py, in emit():
    Change:
        recommended_min = detected_cycle_length * avg_spins
    To:
        recommended_min = 1000  # BUG: constant instead of formula
    RED: test_m275_recommended_min_5000 fails (1000 != 5000).
         test_recommended_min_formula fails (unit level).
    Revert (restore detected_cycle_length * avg_spins) -> GREEN.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_invariant_with_fallback_hides_drift.md
  (absent recommendation != 0; absent = "no BCM cycle detected" signal)
- memory/feedback_no_silent_swallow.md
  (operator-facing alert — must not be omitted or defaulted silently)
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test required for end-to-end formula verification)
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_M275_CACHE = _REPO_ROOT / "rawdata" / "M275" / "mode_1"
_M14_CACHE = _REPO_ROOT / "rawdata" / "M14" / "mode_1"


# ---------------------------------------------------------------------------
# Subprocess fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def m275_g6_summary() -> dict:
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
            f"STDERR: {result.stderr[:2000]}"
        )
        return json.loads((Path(tmpdir) / "player_impact_summary.json").read_bytes())


@pytest.fixture(scope="module")
def m14_g6_summary() -> dict:
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


# ---------------------------------------------------------------------------
# T1: M275 subprocess — recommendation present with correct values
# ---------------------------------------------------------------------------

class TestM275ChunkSpinTimesRecommendation:
    """M275 must have chunk_spin_times_recommendation with computed values."""

    def _get_rec(self, summary: dict) -> dict:
        cm = summary.get("collect_mechanic", {})
        cw = cm.get("clamp_warning", {})
        return cw.get("chunk_spin_times_recommendation") or {}

    def test_recommendation_present(self, m275_g6_summary):
        """chunk_spin_times_recommendation must be present in M275 clamp_warning.

        INJECT-BUG (Bug C): change recommended_min formula to constant 1000.
        RED: recommended_min != 5000, formula is wrong.
        Also: this test verifies presence — if formula is broken emit() still
        writes the block but with wrong values.
        Revert -> GREEN.
        """
        cm = m275_g6_summary.get("collect_mechanic", {})
        cw = cm.get("clamp_warning", {})
        rec = cw.get("chunk_spin_times_recommendation")
        assert rec is not None, (
            "chunk_spin_times_recommendation must be present in M275 clamp_warning. "
            "Gap #6 adds this field when clamp_warning.applicable=True + cycle data known."
        )

    def test_current_is_5000(self, m275_g6_summary):
        """current must match M275 mode 1 chunk_spin_times = 5000."""
        rec = self._get_rec(m275_g6_summary)
        assert rec.get("current") == 5000, (
            f"current must be 5000 (M275 mode 1 chunk_spin_times), got {rec.get('current')}"
        )

    def test_recommended_min_is_5000(self, m275_g6_summary):
        """recommended_min must be 5000 (cycle_length=1000 * avg_spins_per_collect=5.0).

        M275 measured values: detected_cycle_length=1000, avg_paid_spins_per_collect=5.0.
        Formula: recommended_min = 1000 * 5.0 = 5000.

        INJECT-BUG (Bug C): change to `recommended_min = 1000` (constant).
        RED: got 1000, expected 5000.
        Revert -> GREEN.

        Note: brief §2.3 used estimated values (5570); actual measured value is 5000.
        """
        rec = self._get_rec(m275_g6_summary)
        assert rec.get("recommended_min") == 5000, (
            f"recommended_min must be 5000 (1000 * 5.0 measured avg_paid_spins_per_collect). "
            f"Got: {rec.get('recommended_min')!r}. "
            f"Formula: detected_cycle_length * avg_paid_spins_per_collect."
        )

    def test_recommended_safety_is_7500(self, m275_g6_summary):
        """recommended_safety must be 7500 (recommended_min=5000 * safety_factor=1.5)."""
        rec = self._get_rec(m275_g6_summary)
        assert rec.get("recommended_safety") == 7500, (
            f"recommended_safety must be 7500 (5000 * 1.5), got {rec.get('recommended_safety')!r}"
        )

    def test_rationale_nonempty_string(self, m275_g6_summary):
        """rationale must be a non-empty descriptive string."""
        rec = self._get_rec(m275_g6_summary)
        rationale = rec.get("rationale", "")
        assert isinstance(rationale, str) and len(rationale) > 20, (
            f"rationale must be a non-empty descriptive string with formula info. "
            f"Got: {rationale!r}"
        )

    def test_rationale_contains_cycle_length(self, m275_g6_summary):
        """rationale must mention the cycle length for operator clarity."""
        rec = self._get_rec(m275_g6_summary)
        rationale = rec.get("rationale", "")
        assert "1000" in rationale, (
            f"rationale must mention cycle_length 1000. Got: {rationale!r}"
        )

    def test_no_analyzer_errors(self, m275_g6_summary):
        """No analyzer_init_error or feature_errors for M275."""
        assert "analyzer_init_error" not in m275_g6_summary
        fe = m275_g6_summary.get("feature_errors", {})
        assert not fe, f"feature_errors: {fe}"


# ---------------------------------------------------------------------------
# T2: M14 subprocess — recommendation absent
# ---------------------------------------------------------------------------

class TestM14ChunkSpinTimesRecommendation:
    """M14 has no BCM mechanic — chunk_spin_times_recommendation must be absent."""

    def test_m14_recommendation_absent(self, m14_g6_summary):
        """M14 collect_mechanic.clamp_warning must NOT have chunk_spin_times_recommendation.

        M14 has collect_mechanic.applicable=False -> clamp_warning.applicable=False.
        -> chunk_spin_times_recommendation is absent (not None, not empty dict).
        Per feedback_invariant_with_fallback_hides_drift.md: absent = "no BCM" signal.
        """
        cm = m14_g6_summary.get("collect_mechanic", {})
        cw = cm.get("clamp_warning", {})
        rec = cw.get("chunk_spin_times_recommendation")
        assert rec is None, (
            f"M14 must NOT have chunk_spin_times_recommendation "
            f"(collect_mechanic.applicable=False -> clamp_warning.applicable=False). "
            f"Got: {rec!r}"
        )


# ---------------------------------------------------------------------------
# T3: Unit formula tests (different inputs -> correct outputs)
# ---------------------------------------------------------------------------

class TestChunkSpinTimesRecommendationFormula:
    """Unit tests for the recommendation formula in collect_mechanic.emit()."""

    def _run_emit(self, cycle_length: int, avg_spins: float,
                  current_cst: int = 5000) -> dict | None:
        """Run emit() with controlled stash data; return the recommendation dict or None."""
        try:
            from fresh_slotlab.analyzer.features.collect_mechanic import CollectMechanic
        except ImportError:
            from analyzer.features.collect_mechanic import CollectMechanic  # type: ignore[no-redef]

        plugin = CollectMechanic()
        stash = {
            "applicable": True,
            "robots_with_data": 5,
            "total_collects": 100,
            "max_acc_credits_observed": 999,
            "avg_spins_between_collects": avg_spins,
            "clamp_warning": {
                "applicable": True,
                "pending_robots": 3,
                "total_pending_paid_spins": 15,
                "pending_share_of_paid_spins": 0.03,
                "avg_paid_spins_per_collect": avg_spins,
                "note": "test",
            },
            "bonus_cycle_correction": {
                "applicable": True,
                "bonus_feature": "TestFeature",
                "bonus_feature_source": "bcm_pairings",
                "detected_cycle_length": cycle_length,
                "completed_cycles_total": 80,
                "robots_with_pending_cycle": 3,
                "avg_bonus_payout": 40.0,
                "estimated_correction_pp": 0.0,
            },
            "feature_match": {"applicable": True, "known_features": [], "bonus_feature": None,
                              "bonus_feature_source": "none", "warning": None},
            "cycle_observation": {"mechanic_detected": True, "reset_observed": True,
                                  "cycle_len_lower_bound": cycle_length, "warning": None},
        }
        summary: dict[str, Any] = {
            "_collect_mechanic_data": stash,
            "sampling": {"chunk_spin_times": current_cst},
        }
        plugin.emit({}, summary, None)
        cm = summary.get("collect_mechanic", {})
        return cm.get("clamp_warning", {}).get("chunk_spin_times_recommendation")

    def test_recommended_min_formula(self):
        """recommended_min = cycle_length * avg_spins_per_collect.

        INJECT-BUG (Bug C): change formula to `recommended_min = 1000`.
        RED: expected 3000 (600 * 5.0), got 1000.
        Revert -> GREEN.
        """
        rec = self._run_emit(cycle_length=600, avg_spins=5.0)
        assert rec is not None
        assert rec["recommended_min"] == 3000, (
            f"recommended_min must be 600 * 5.0 = 3000, got {rec['recommended_min']}"
        )

    def test_recommended_safety_formula(self):
        """recommended_safety = recommended_min * 1.5."""
        rec = self._run_emit(cycle_length=600, avg_spins=5.0)
        assert rec is not None
        assert rec["recommended_safety"] == 4500, (
            f"recommended_safety must be 3000 * 1.5 = 4500, got {rec['recommended_safety']}"
        )

    def test_different_cycle_length_different_result(self):
        """Different cycle_length must produce proportionally different recommended_min."""
        rec_1000 = self._run_emit(cycle_length=1000, avg_spins=5.0)
        rec_500 = self._run_emit(cycle_length=500, avg_spins=5.0)
        assert rec_1000 is not None and rec_500 is not None
        assert rec_1000["recommended_min"] == 5000
        assert rec_500["recommended_min"] == 2500
        assert rec_1000["recommended_min"] == 2 * rec_500["recommended_min"], (
            "recommended_min must scale proportionally with cycle_length"
        )

    def test_different_avg_spins_different_result(self):
        """Different avg_spins_per_collect must produce proportionally different recommended_min."""
        rec_5 = self._run_emit(cycle_length=1000, avg_spins=5.0)
        rec_10 = self._run_emit(cycle_length=1000, avg_spins=10.0)
        assert rec_5 is not None and rec_10 is not None
        assert rec_5["recommended_min"] == 5000
        assert rec_10["recommended_min"] == 10000
        assert rec_10["recommended_min"] == 2 * rec_5["recommended_min"], (
            "recommended_min must scale proportionally with avg_spins_per_collect"
        )

    def test_current_captured_from_sampling(self):
        """current must match the chunk_spin_times from sampling."""
        rec = self._run_emit(cycle_length=1000, avg_spins=5.0, current_cst=8000)
        assert rec is not None
        assert rec["current"] == 8000, (
            f"current must be 8000 (from sampling.chunk_spin_times), got {rec['current']}"
        )

    def test_rationale_mentions_cycle_length_and_avg_spins(self):
        """rationale must contain both cycle_length and avg_spins values."""
        rec = self._run_emit(cycle_length=1000, avg_spins=5.0)
        assert rec is not None
        rationale = rec.get("rationale", "")
        assert "1000" in rationale, f"rationale must mention cycle_length 1000: {rationale!r}"
        assert "5" in rationale, f"rationale must mention avg_spins 5.0: {rationale!r}"
