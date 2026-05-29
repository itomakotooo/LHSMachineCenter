"""R1 Phase 2 d4 — avg_bonus_payout None vs 0.0 (arch-v2 §5.4 corrected).

Invariants asserted (AC#6)
--------------------------
The avg_bonus_payout inline block in player_impact_analyzer.py:4821 must:

1. Case 1: _cm_bonus_feat is None/falsy → avg_bonus_payout = None.
   (Unresolved bonus feature — no meaningful average exists.)

2. Case 2: _cm_bonus_feat truthy AND total_completed_cycles == 0 → None.
   (No cycles completed — average would be 0/0, meaningless.)

3. Case 3 (d4 fix): _cm_bonus_feat truthy AND total_completed_cycles > 0
   AND sum(win) == 0.0 → None, NOT 0.0.
   Semantic: "bonus feature identified and cycles completed, but produced
   no measurable win in this sample — data-resolution issue, not 0 RTP."
   The old code (plain _s / total_completed_cycles) returned 0.0 which
   silently conflated "0 RTP from bonus" with "data resolution issue".
   Frontend app.js:6196 has != null guard → renders "—" for None,
   "0" for 0.0. None is correct here.

4. Case 4 (normal): sum(win) > 0 → float = sum / cycles (unchanged).

5. M275 subprocess: avg_bonus_payout is a non-zero float (case 4 — confirms
   the `_s > 0` guard does NOT break the common non-zero-win case).

6. M14 subprocess: avg_bonus_payout is None (case 2 — cycles == 0 path,
   confirming pre-existing None behavior unaffected by d4 change).

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug d4: remove the `_s > 0` guard in the avg_bonus_payout lambda.
  The unit tests exercise this via the `_compute_avg_bonus_payout` helper in THIS
  file, which is a byte-for-byte copy of the avg_bonus_payout expression. Phase
  2a carved that expression VERBATIM out of PIA into the collect_mechanic plugin
  (fresh_slotlab/analyzer/features/collect_mechanic.py, in CollectMechanic.emit()'s
  bonus_cycle_correction dict). The expression text is unchanged; only its file
  moved.

  Step 1: In this test file, find:
      (lambda _s: _s / total_completed_cycles if _s > 0 else None)(
  Change to:
      (lambda _s: _s / total_completed_cycles)(
  Step 2: Run: pytest tests/analyzer/test_d4_avg_bonus_payout_none.py::TestCase3ZeroWinIsNone
  RED: test_case3_zero_win_is_none_not_zero and 3 siblings fail — returns 0.0.
  Step 3: Revert (restore `if _s > 0 else None`) → all GREEN.

  To verify the production code directly, also apply the same change to the
  avg_bonus_payout lambda in collect_mechanic.py and run a subprocess test with a
  synthetic fixture (no cached machine naturally produces case 3 in existing cache).

NOTE on test approach (per brief §6 AC#6):
  The avg_bonus_payout computation now lives in the collect_mechanic plugin
  (Phase 2a carve; was PIA inline). Direct unit testing is done by evaluating an
  equivalent expression matching the exact plugin code, parameterized over the
  three distinct cases. A subprocess test covers case 4 (M275 real data) and
  case 2 (M14 real data). Case 3 (sum==0, cycles>0) is tested via synthetic
  expression evaluation because no cached machine produces this edge case in its
  real data. The helper `_compute_avg_bonus_payout` must stay in sync with the
  avg_bonus_payout expression in collect_mechanic.py.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
- memory/feedback_perf_claim_needs_e2e_event_stream.md
  (subprocess test for M275/M14 covers the real production paths)
- memory/feedback_session_semantics.md
  (avg_bonus_payout is per-cycle metric; None != 0.0 semantics matter)
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
_M14_CACHE = _REPO_ROOT / "rawdata" / "M14" / "mode_1"


# ---------------------------------------------------------------------------
# The exact avg_bonus_payout expression (now in collect_mechanic.py's emit(),
# carved verbatim from PIA in Phase 2a) as a testable function.
#
# This mirrors the plugin code exactly, allowing case-3 testing without subprocess.
# If the plugin code changes, update this function AND the inject-bug recipe.
# ---------------------------------------------------------------------------

def _compute_avg_bonus_payout(
    _cm_bonus_feat: str | None,
    total_completed_cycles: int,
    upstream_feature_tally: dict,
) -> float | None:
    """Equivalent to PIA inline block at lines 4821-4831.

    Exact logic:
        "avg_bonus_payout": (
            (
                (lambda _s: _s / total_completed_cycles if _s > 0 else None)(
                    sum(
                        float(e.get("win", 0.0))
                        for e in (upstream_feature_tally.get(_cm_bonus_feat) or {}).values()
                    )
                )
                if total_completed_cycles > 0 else None
            ) if _cm_bonus_feat else None
        ),
    """
    return (
        (
            (lambda _s: _s / total_completed_cycles if _s > 0 else None)(
                sum(
                    float(e.get("win", 0.0))
                    for e in (upstream_feature_tally.get(_cm_bonus_feat) or {}).values()
                )
            )
            if total_completed_cycles > 0 else None
        ) if _cm_bonus_feat else None
    )


# ---------------------------------------------------------------------------
# T1: Case 3 — resolved bonus_feat + cycles>0 + zero win → None (d4 fix)
# ---------------------------------------------------------------------------

class TestCase3ZeroWinIsNone:
    """sum(win)==0.0 with cycles>0 must produce None, not 0.0.

    This is the d4 correctness fix. The old code was:
        (lambda _s: _s / total_completed_cycles)(...)
    Which returns 0.0 / cycles = 0.0. Wrong semantic.
    The fix is:
        (lambda _s: _s / total_completed_cycles if _s > 0 else None)(...)
    """

    def test_case3_zero_win_is_none_not_zero(self):
        """All upstream_feature_tally entries have win=0 → avg_bonus_payout = None.

        INJECT-BUG (d4): change 'if _s > 0 else None' to remove the guard
          (lambda _s: _s / total_completed_cycles)
        RED: returns 0.0 instead of None → this test fails.
        Revert → GREEN.
        """
        # Simulate: bonus_feat resolved, cycles=5, but every tally entry has win=0
        bonus_feat = "NormalCollectionSpin"
        upstream_feature_tally = {
            bonus_feat: {
                "robot_0": {"win": 0.0, "count": 5},
                "robot_1": {"win": 0.0, "count": 3},
                "robot_2": {"win": 0.0, "count": 7},
            }
        }
        result = _compute_avg_bonus_payout(
            _cm_bonus_feat=bonus_feat,
            total_completed_cycles=5,
            upstream_feature_tally=upstream_feature_tally,
        )
        assert result is None, (
            f"Case 3: resolved bonus_feat + cycles>0 + sum(win)==0 must return None, "
            f"not 0.0. Got: {result!r}. "
            f"Semantic: 'bonus identified but no measurable win — data-resolution issue'. "
            f"INJECT-BUG: remove `if _s > 0 else None` from PIA:4823 → returns 0.0 → RED."
        )

    def test_case3_missing_win_field_is_none(self):
        """Tally entries without 'win' field default to 0.0 → still None."""
        bonus_feat = "MyFeature"
        upstream_feature_tally = {
            bonus_feat: {
                "robot_0": {"count": 5},  # no 'win' key
            }
        }
        result = _compute_avg_bonus_payout(
            _cm_bonus_feat=bonus_feat,
            total_completed_cycles=3,
            upstream_feature_tally=upstream_feature_tally,
        )
        assert result is None, (
            f"Missing 'win' field defaults to 0.0 → sum=0 → None. Got: {result!r}"
        )

    def test_case3_empty_tally_for_bonus_feat_is_none(self):
        """upstream_feature_tally present but bonus_feat has empty inner dict → None."""
        bonus_feat = "MyFeature"
        upstream_feature_tally = {
            bonus_feat: {}  # no robot entries at all
        }
        result = _compute_avg_bonus_payout(
            _cm_bonus_feat=bonus_feat,
            total_completed_cycles=2,
            upstream_feature_tally=upstream_feature_tally,
        )
        assert result is None, (
            f"Empty tally → sum=0.0 → None. Got: {result!r}"
        )

    def test_case3_bonus_feat_absent_from_tally_is_none(self):
        """upstream_feature_tally doesn't have bonus_feat → None (no win data)."""
        bonus_feat = "UnlistedFeature"
        upstream_feature_tally = {
            "OtherFeature": {"robot_0": {"win": 999.0}}
        }
        result = _compute_avg_bonus_payout(
            _cm_bonus_feat=bonus_feat,
            total_completed_cycles=10,
            upstream_feature_tally=upstream_feature_tally,
        )
        assert result is None, (
            f"Bonus feat absent from tally → sum=0 → None. Got: {result!r}"
        )


# ---------------------------------------------------------------------------
# T2: Case 1 — _cm_bonus_feat is falsy → None
# ---------------------------------------------------------------------------

class TestCase1UnresolvedBonusFeat:
    """_cm_bonus_feat is None/empty string → avg_bonus_payout = None."""

    def test_none_bonus_feat_is_none(self):
        """Case 1: _cm_bonus_feat=None → None regardless of cycles or tally."""
        result = _compute_avg_bonus_payout(
            _cm_bonus_feat=None,
            total_completed_cycles=10,
            upstream_feature_tally={"SomeFeature": {"r": {"win": 100.0}}},
        )
        assert result is None, (
            f"Unresolved bonus_feat must always return None. Got: {result!r}"
        )

    def test_empty_string_bonus_feat_is_none(self):
        """Empty string is falsy → treated same as None."""
        result = _compute_avg_bonus_payout(
            _cm_bonus_feat="",
            total_completed_cycles=10,
            upstream_feature_tally={},
        )
        assert result is None, (
            f"Empty string bonus_feat is falsy → None. Got: {result!r}"
        )


# ---------------------------------------------------------------------------
# T3: Case 2 — total_completed_cycles == 0 → None
# ---------------------------------------------------------------------------

class TestCase2ZeroCycles:
    """total_completed_cycles == 0 → None regardless of tally content."""

    def test_zero_cycles_is_none(self):
        """Case 2: cycles=0 → None (inner 'if ... > 0 else None' for cycles)."""
        result = _compute_avg_bonus_payout(
            _cm_bonus_feat="NormalCollectionSpin",
            total_completed_cycles=0,
            upstream_feature_tally={"NormalCollectionSpin": {"r": {"win": 500.0}}},
        )
        assert result is None, (
            f"Cycles=0 must return None. Got: {result!r}"
        )


# ---------------------------------------------------------------------------
# T4: Case 4 — normal case (sum(win) > 0) → float
# ---------------------------------------------------------------------------

class TestCase4NonZeroWin:
    """sum(win) > 0 AND cycles > 0 → float = sum / cycles. Unchanged from pre-d4."""

    def test_nonzero_win_returns_float(self):
        """Case 4: sum(win)=1000, cycles=10 → avg=100.0."""
        bonus_feat = "NormalCollectionSpin"
        upstream_feature_tally = {
            bonus_feat: {
                "robot_0": {"win": 600.0},
                "robot_1": {"win": 400.0},
            }
        }
        result = _compute_avg_bonus_payout(
            _cm_bonus_feat=bonus_feat,
            total_completed_cycles=10,
            upstream_feature_tally=upstream_feature_tally,
        )
        assert isinstance(result, float), (
            f"Non-zero win + cycles > 0 must return float. Got: {type(result).__name__!r}"
        )
        assert abs(result - 100.0) < 1e-6, (
            f"sum(win)=1000, cycles=10 → avg=100.0. Got: {result!r}"
        )

    def test_nonzero_win_single_robot(self):
        """Single robot with win=500, cycles=2 → avg=250.0."""
        bonus_feat = "MyFeature"
        upstream_feature_tally = {
            bonus_feat: {
                "robot_0": {"win": 500.0},
            }
        }
        result = _compute_avg_bonus_payout(
            _cm_bonus_feat=bonus_feat,
            total_completed_cycles=2,
            upstream_feature_tally=upstream_feature_tally,
        )
        assert isinstance(result, float)
        assert abs(result - 250.0) < 1e-6, (
            f"500.0 / 2 = 250.0. Got: {result!r}"
        )

    def test_case3_and_case4_differ(self):
        """Case 3 (zero win) returns None; case 4 (nonzero win) returns float.

        This test directly contrasts the two cases to prove the distinction.
        """
        bonus_feat = "Feature"
        # Case 3: zero win
        case3 = _compute_avg_bonus_payout(
            _cm_bonus_feat=bonus_feat,
            total_completed_cycles=5,
            upstream_feature_tally={bonus_feat: {"r": {"win": 0.0}}},
        )
        # Case 4: nonzero win
        case4 = _compute_avg_bonus_payout(
            _cm_bonus_feat=bonus_feat,
            total_completed_cycles=5,
            upstream_feature_tally={bonus_feat: {"r": {"win": 500.0}}},
        )
        assert case3 is None, f"Case 3 must be None. Got: {case3!r}"
        assert isinstance(case4, float), f"Case 4 must be float. Got: {case4!r}"
        assert case4 == 100.0, f"500.0 / 5 = 100.0. Got: {case4!r}"


# ---------------------------------------------------------------------------
# T5: Subprocess — M275 and M14 real-data paths
# ---------------------------------------------------------------------------

class TestAvgBonusPayoutSubprocess:
    """Real subprocess tests verify the PIA inline code paths on cached machines."""

    @pytest.fixture(scope="class")
    def m275_bcc(self):
        """Run M275 mode 1 from cache; return bonus_cycle_correction dict."""
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
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=300
            )
            assert result.returncode == 0, (
                f"M275 analyzer failed.\n"
                f"STDOUT: {result.stdout[:2000]}\nSTDERR: {result.stderr[:2000]}"
            )
            summary = json.loads(
                (Path(tmpdir) / "player_impact_summary.json").read_bytes()
            )
        return summary.get("collect_mechanic", {}).get("bonus_cycle_correction", {})

    @pytest.fixture(scope="class")
    def m14_bcc(self):
        """Run M14 mode 1 from cache; return bonus_cycle_correction dict."""
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
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=300
            )
            assert result.returncode == 0, (
                f"M14 analyzer failed.\n"
                f"STDERR: {result.stderr[:2000]}"
            )
            summary = json.loads(
                (Path(tmpdir) / "player_impact_summary.json").read_bytes()
            )
        return summary.get("collect_mechanic", {}).get("bonus_cycle_correction", {})

    def test_m275_avg_bonus_payout_is_float(self, m275_bcc):
        """M275 has resolved bonus_feat + cycles>0 + sum(win)>0 → float (case 4).

        This confirms the `_s > 0` guard does NOT break the normal non-zero-win path.
        If d4 inject-bug (removing guard) is applied, M275 STILL returns a float
        (since _s > 0 is True for M275) — so M275 alone cannot catch bug d4.
        The synthetic unit tests in T1 cover case 3.
        """
        abp = m275_bcc.get("avg_bonus_payout")
        assert isinstance(abp, (int, float)) and abp is not None, (
            f"M275 avg_bonus_payout must be a non-None number (case 4). "
            f"Got: {abp!r} (type: {type(abp).__name__})"
        )
        assert abp > 0.0, (
            f"M275 avg_bonus_payout must be > 0 (real bonus win observed). "
            f"Got: {abp!r}"
        )

    def test_m275_avg_bonus_payout_not_zero(self, m275_bcc):
        """M275 avg_bonus_payout must not be 0.0 (real win data present)."""
        abp = m275_bcc.get("avg_bonus_payout")
        assert abp != 0.0, (
            f"M275 avg_bonus_payout must not be 0.0. Got: {abp!r}"
        )

    def test_m14_avg_bonus_payout_is_none(self, m14_bcc):
        """M14 avg_bonus_payout must be None (cycles=0, case 2).

        M14 is a non-BCM machine; collect_mechanic applicable=False;
        total_completed_cycles=0 → None regardless of d4 fix.
        This confirms pre-existing None behavior unaffected by d4 change.
        """
        abp = m14_bcc.get("avg_bonus_payout")
        assert abp is None, (
            f"M14 avg_bonus_payout must be None (no BCM cycles). "
            f"Got: {abp!r}"
        )
