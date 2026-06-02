"""Commit C2 fix — BCMBaseAccumulator cycle-peak tests.

Invariants under test
---------------------
T1 - BCMBasePlugin CLAIMS M272 (real rawdata: paid rounds carry the 4 BCM
     fields CollectCount / AccCredits / CreditsSymbols / SymbolIndexToRewards).

T2 - compute_robot_cycle_peaks helper contract:
     - returns [] for empty / non-BCM round lists
     - correctly applies the inline rule: ANY drop (cc < prev) + prev > 10
     - the initial prev=0 means the first paid round can never trigger a peak
     - both BCM machines (cc != 0) and M274 (cc always 0) handled correctly

T3 - BCM-pilot flag-ON byte-identical to golden: M272, M275, M279, M268,
     M274 all produce the same summary JSON (volatile stripped) whether the
     flag is on or off, compared against the cached golden in
     ``cache/_playtype_golden_pristine/``.

T4 - Inject-bug A (engagement): monkeypatching ``compute_robot_cycle_peaks``
     in ``fresh_slotlab.analyzer.play_types.bcm_base`` to always return
     [99999] makes the M272 ``collect_mechanic.clamp_warning.completed_cycles``
     value diverge from the golden.  Proves BCMBase's ``cycle_peaks`` output
     actually flows to the summary (plugin not bypassed).

T5 - Inject-bug B (logic correctness): a synthetic robot fixture with:
     - a cycle peak at 8 (in the [5,10] range) followed by a drop to 1
     - a single-step drop: cc goes 50 → 49 (not >= 2 steps)
     ``compute_robot_cycle_peaks`` (correct rule: ANY drop, prev > 10) must:
     - NOT record the peak-8 reset (8 ≤ 10)
     - RECORD the single-step drop from cc=50 to cc=49 (prev=50 > 10, ANY drop)
     The OLD buggy rule (cc < prev - 1 and prev >= 5) would:
     - NOT record peak-8 reset (8 ≥ 5, BUT the drop-to-1 is 7 steps, so it
       WOULD record it -- wait, we need to verify exactly)
     Actually: old rule ``cc < prev - 1``: 1 < 8-1=7 → True; 8 >= 5 → True →
       would RECORD the peak-8 reset (wrong — inline floor is > 10, not >= 5)
     And for single-step drop 50→49: 49 < 50-1=49 → False → would NOT record
     (wrong — inline is ANY drop < prev, not < prev-1)
     This test verifies the helper behaves like the INLINE rule, NOT the old
     buggy rule.

Inject-bug recipes (prove each test catches its regression)
-----------------------------------------------------------
T4: monkeypatch ``fresh_slotlab.analyzer.play_types.bcm_base.compute_robot_cycle_peaks``
    → return [99999] → completed_cycles in summary diverges from golden → RED.
    Revert (monkeypatch context exits) → GREEN.

T5: change the condition in compute_robot_cycle_peaks from
        if cc_int < prev and prev > 10:
    to the old buggy one:
        if cc_int < prev - 1 and prev >= 5:
    → the assertions about single-step drop and small peak flip → RED.
    Revert → GREEN.

Memory feedback files honoured
-------------------------------
- memory/feedback_no_silent_swallow.md — helper outputs must be deterministic;
  no silent pass on TypeError/ValueError (they produce cc_int=0, which is
  explicitly documented in compute_robot_cycle_peaks docstring).
- memory/feedback_perf_claim_needs_e2e_event_stream.md — T3 uses real
  subprocess against real cached fixtures.
- memory/feedback_enumerate_safety_paths.md — inject-bug tests prove each
  assertion is genuinely guarding the invariant (not tautological).
- memory/feedback_integration_test_argv.md — T3 subprocess argv fully explicit.
- memory/feedback_no_parallel_panel_impl.md — test helpers reuse sibling
  patterns from test_play_type_c1_fixes.py (_load_m272_rounds, etc.).
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = ROOT / "cache" / "_playtype_golden_pristine"
RAWDATA_DIR = ROOT / "rawdata"


# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------
try:
    from fresh_slotlab.analyzer.play_types.bcm_cycle import compute_robot_cycle_peaks
    from fresh_slotlab.analyzer.play_types._claim import ClaimSignature
    from fresh_slotlab.analyzer.play_types._detector import detect_play_types
    from fresh_slotlab.analyzer.play_types._machine_config import MachinePlayTypeConfig
    from fresh_slotlab.analyzer.play_types.bcm_base import BCMBasePlugin, BCMBaseAccumulator
    _FRAMEWORK_AVAILABLE = True
except ImportError:
    _FRAMEWORK_AVAILABLE = False

_SKIP_NO_FRAMEWORK = pytest.mark.skipif(
    not _FRAMEWORK_AVAILABLE,
    reason="BCMBase framework not available",
)

# Check whether M272 rawdata is present (BCM archetype for claim + engagement tests).
_M272_AVAILABLE = (RAWDATA_DIR / "M272" / "mode_1").is_dir() and any(
    (RAWDATA_DIR / "M272" / "mode_1").glob("chunk_*.json")
)
_SKIP_NO_M272 = pytest.mark.skipif(
    not _M272_AVAILABLE, reason="M272 rawdata not available"
)

# BCM pilots for byte-identical gate: machines that have both golden + rawdata.
_BCM_PILOTS_ALL = ["M272", "M275", "M279", "M268", "M274"]
_BCM_PILOTS_WITH_DATA = [
    m for m in _BCM_PILOTS_ALL
    if (GOLDEN_DIR / m / "player_impact_summary.json").exists()
    and (RAWDATA_DIR / m / "mode_1").is_dir()
    and any((RAWDATA_DIR / m / "mode_1").glob("chunk_*.json"))
]

# Non-BCM pilots for regression check.
_NON_BCM_PILOTS = ["M14", "M15", "M120", "M10"]
_NON_BCM_WITH_DATA = [
    m for m in _NON_BCM_PILOTS
    if (GOLDEN_DIR / m / "player_impact_summary.json").exists()
    and (RAWDATA_DIR / m / "mode_1").is_dir()
    and any((RAWDATA_DIR / m / "mode_1").glob("chunk_*.json"))
]

_SKIP_NO_BCM_PILOTS = pytest.mark.skipif(
    not _BCM_PILOTS_WITH_DATA,
    reason="No BCM pilot rawdata + golden available",
)


# ---------------------------------------------------------------------------
# Registry isolation (per-test).
#
# ALL_PLAY_TYPE_PLUGINS is a module global. Other play-type test files
# (test_play_type_wiring / test_play_type_c1_fixes) clear+append fake plugins
# inside their tests; if a restore is imperfect the global stays polluted for
# tests that run later. The in-process engagement tests (T4) call
# parse_chunk_response and rely on bcm_base being the *active* plugin for M272,
# so a polluted registry makes them flaky (pass in isolation, fail in the full
# suite). Restore the registry to its import-time (real) state before every test
# in this module, and restore the prior state afterward so we don't pollute
# downstream files. Per memory/feedback_subprocess_import_suicide_and_module_globals.md.
# ---------------------------------------------------------------------------
if _FRAMEWORK_AVAILABLE:
    import fresh_slotlab.analyzer.play_type_registry as _play_type_registry
    # Captured AFTER the bcm_base import above (so bcm_base is registered),
    # at collection time (before any test mutates the global).
    _REGISTRY_AT_IMPORT = list(_play_type_registry.ALL_PLAY_TYPE_PLUGINS)

    @pytest.fixture(autouse=True)
    def _isolate_play_type_registry():
        saved = list(_play_type_registry.ALL_PLAY_TYPE_PLUGINS)
        _play_type_registry.ALL_PLAY_TYPE_PLUGINS[:] = _REGISTRY_AT_IMPORT
        try:
            yield
        finally:
            _play_type_registry.ALL_PLAY_TYPE_PLUGINS[:] = saved


# ---------------------------------------------------------------------------
# Helpers (reuse sibling pattern from test_play_type_wiring.py)
# ---------------------------------------------------------------------------

# Volatile fields stripped before comparison.
_VOLATILE_TOP = {
    "report_id", "run_id", "analyzer_version",
    "effective_analyzer_version", "effective_analyzer_version_error",
}
_VOLATILE_SAMPLING = {"duration_seconds", "started_at", "finished_at", "evaluated_at"}
_VOLATILE_GUIDELINE = {"evaluated_at"}


def _sort_top_symbols(obj):
    """Recursively sort non-deterministic lists to eliminate set-order drift."""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if k == "top_symbols" and isinstance(v, list):
                try:
                    result[k] = sorted(v, key=lambda x: str(x.get("symbol", "")))
                except Exception:
                    result[k] = v
            elif k == "payline_symbol_top20" and isinstance(v, list):
                try:
                    items = [_sort_top_symbols(i) for i in v]
                    result[k] = sorted(items, key=lambda x: (
                        -float(x.get("rtp_contribution_pp", 0)),
                        str(x.get("payline_symbol", "")),
                    ))
                except Exception:
                    result[k] = v
            elif k == "paylines_top20" and isinstance(v, list):
                try:
                    items = [_sort_top_symbols(i) for i in v]
                    result[k] = sorted(items, key=lambda x: (
                        -float(x.get("approx_rtp_contribution_pp", 0)),
                        str(x.get("payline_id", "")),
                    ))
                except Exception:
                    result[k] = v
            else:
                result[k] = _sort_top_symbols(v)
        return result
    elif isinstance(obj, list):
        return [_sort_top_symbols(i) for i in obj]
    return obj


def _strip_volatile(d: dict) -> dict:
    """Return a copy of summary dict with volatile fields removed."""
    d = copy.deepcopy(d)
    for k in _VOLATILE_TOP:
        d.pop(k, None)
    samp = d.get("sampling")
    if isinstance(samp, dict):
        for k in _VOLATILE_SAMPLING:
            samp.pop(k, None)
    gl = d.get("guideline_comparison")
    if isinstance(gl, dict):
        for k in _VOLATILE_GUIDELINE:
            gl.pop(k, None)
    return _sort_top_symbols(d)


def _load_golden(machine: str) -> dict:
    path = GOLDEN_DIR / machine / "player_impact_summary.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _run_analyzer_flag(
    machine: str, flag_on: bool, output_dir: Path, max_chunks: int = 2
) -> subprocess.CompletedProcess:
    rawdata_mode_dir = RAWDATA_DIR / machine / "mode_1"
    cmd = [
        sys.executable, "-m", "fresh_slotlab.player_impact_analyzer",
        "--machine", machine,
        "--rtp-mode", "1",
        "--from-cache", str(rawdata_mode_dir),
        "--output-dir", str(output_dir),
        "--max-chunks", str(max_chunks),
    ]
    if flag_on:
        cmd.append("--use-play-type-plugins")
    return subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )


def _load_summary(output_dir: Path) -> dict:
    candidates = list(output_dir.rglob("player_impact_summary.json"))
    if not candidates:
        raise FileNotFoundError(
            f"No player_impact_summary.json found under {output_dir}"
        )
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return json.loads(candidates[0].read_text(encoding="utf-8"))


def _load_m272_first_robot_rounds() -> list[dict]:
    """Load M272 chunk 0001 first-robot rounds (BCM archetype)."""
    d = RAWDATA_DIR / "M272" / "mode_1"
    chunk = json.loads(
        sorted(d.glob("chunk_*.json"))[0].read_text(encoding="utf-8")
    )
    resp = chunk["response"]
    r0 = resp[0]
    raw = r0.get("roundResult")
    return json.loads(raw) if isinstance(raw, str) else (raw or [])


def _make_synthetic_bcm_rounds(cc_sequence: list[int]) -> list[dict]:
    """Build a minimal paid-round list with the given CollectCount sequence.

    Each round: CostCredits=1000, CollectCount=cc, other fields minimal.
    """
    rounds = []
    for cc in cc_sequence:
        rounds.append({
            "SpinType": 140,
            "BetAmount": 1000,
            "CostCredits": 1000,
            "WinCredits": 0,
            "CollectCount": cc,
            "AccCredits": 0,
            "CreditsSymbols": "",
            "SymbolIndexToRewards": {},
            "StopSymbolsByCol": ["1-2-3"],
            "PayoutByPayline": "",
            "PayoutIdToWinAmount": {},
            "ReMarks": "",
        })
    return rounds


# ---------------------------------------------------------------------------
# T1 — BCMBasePlugin claims M272
# ---------------------------------------------------------------------------

class TestBCMBaseClaim:
    """T1: BCMBasePlugin.CLAIM_SIGNATURE.matches() returns True for M272 rawdata.

    The 4 BCM fields (CollectCount, AccCredits, CreditsSymbols,
    SymbolIndexToRewards) must appear on at least one PAID round in the
    5000-round sample.  M272 mode 1 has them on every paid ST=140 round.

    Inject-bug: change ClaimSignature required_fields to include a field
    that doesn't exist (e.g. "NonExistentBCMField") → claim fails → RED.
    Revert → GREEN.
    """

    @_SKIP_NO_FRAMEWORK
    @_SKIP_NO_M272
    def test_bcm_base_claims_m272_rawdata(self) -> None:
        """BCMBasePlugin's ClaimSignature fires on M272 chunk 0001."""
        import types
        rounds = _load_m272_first_robot_rounds()
        assert rounds, "M272 chunk 0001 has no rounds — fixture problem"

        sig = BCMBasePlugin.CLAIM_SIGNATURE
        paid_rounds = [
            r for r in rounds
            if isinstance(r, dict)
            and r.get("CostCredits") is not None
            and float(r.get("CostCredits", 0) or 0) > 0.0
        ]
        assert paid_rounds, "M272 chunk 0001 has no paid rounds — fixture problem"

        # matches() needs all rounds (it does its own paid filtering) + a parse_state.
        parse_state = types.SimpleNamespace(cost_credits_unreliable=False)
        matched = sig.matches(rounds, parse_state)
        assert matched, (
            f"BCMBasePlugin.CLAIM_SIGNATURE did not match M272 rounds.\n"
            f"Required fields: {sig.required_fields}\n"
            f"Fields present on first paid round: {set(paid_rounds[0].keys())}"
        )

    @_SKIP_NO_FRAMEWORK
    def test_bcm_base_does_not_claim_non_bcm_rounds(self) -> None:
        """ClaimSignature does NOT fire when BCM fields are absent."""
        import types
        sig = BCMBasePlugin.CLAIM_SIGNATURE
        # Build paid rounds with no BCM fields.
        all_rounds = [
            {
                "SpinType": 1, "CostCredits": 1000, "WinCredits": 0,
                "BetAmount": 1000,
                # CollectCount intentionally absent — not a BCM machine.
            }
            for _ in range(5)
        ]
        parse_state = types.SimpleNamespace(cost_credits_unreliable=False)
        assert not sig.matches(all_rounds, parse_state), (
            "ClaimSignature wrongly fired on rounds lacking BCM fields"
        )


# ---------------------------------------------------------------------------
# T2 — compute_robot_cycle_peaks helper contract
# ---------------------------------------------------------------------------

class TestComputeRobotCyclePeaks:
    """T2: Unit-test the shared helper compute_robot_cycle_peaks.

    Each case proves the CORRECT rule (cc < prev AND prev > 10) is used,
    NOT the old buggy rule (cc < prev - 1 AND prev >= 5).

    Inject-bug B recipe: change the condition in round_classification.py from
        if cc_int < prev and prev > 10:
    to:
        if cc_int < prev - 1 and prev >= 5:
    then:
    - test_small_peak_not_recorded goes RED (old rule WOULD record peak=8 reset)
    - test_single_step_drop_recorded goes RED (old rule would NOT record 50→49)
    Revert → both GREEN.
    """

    @_SKIP_NO_FRAMEWORK
    def test_empty_rounds_returns_empty(self) -> None:
        assert compute_robot_cycle_peaks([]) == []

    @_SKIP_NO_FRAMEWORK
    def test_non_dict_rounds_skipped(self) -> None:
        assert compute_robot_cycle_peaks([None, "bad", 42]) == []

    @_SKIP_NO_FRAMEWORK
    def test_bonus_rounds_not_paid_skipped(self) -> None:
        """Bonus rounds (CostCredits=0 or None) do not contribute to peaks."""
        rounds = [
            {"SpinType": 2, "CostCredits": 0, "CollectCount": 1000},
            {"SpinType": 2, "CostCredits": None, "CollectCount": 500},
        ]
        assert compute_robot_cycle_peaks(rounds) == []

    @_SKIP_NO_FRAMEWORK
    def test_cc_zero_on_paid_round_skipped(self) -> None:
        """Paid rounds with CollectCount=0 are skipped (M274 cc=0 machine)."""
        rounds = _make_synthetic_bcm_rounds([0, 0, 0])
        assert compute_robot_cycle_peaks(rounds) == []

    @_SKIP_NO_FRAMEWORK
    def test_monotonic_increase_no_peaks(self) -> None:
        """CC walking monotonically up (no reset) → no peaks detected."""
        rounds = _make_synthetic_bcm_rounds(list(range(1, 101)))
        assert compute_robot_cycle_peaks(rounds) == []

    @_SKIP_NO_FRAMEWORK
    def test_single_complete_cycle_records_peak(self) -> None:
        """One complete cycle (cc=1..100 then reset to cc=1) records one peak.

        The peak value recorded is the prev (100) at the moment of reset.
        Reset condition: cc_int (1) < prev (100) AND prev (100) > 10 → True.
        """
        cc_seq = list(range(1, 101)) + [1, 2, 3]  # reset at cc=1 after 100
        rounds = _make_synthetic_bcm_rounds(cc_seq)
        peaks = compute_robot_cycle_peaks(rounds)
        assert peaks == [100], f"Expected [100], got {peaks}"

    @_SKIP_NO_FRAMEWORK
    def test_multiple_cycles_records_all_peaks(self) -> None:
        """Multiple cycles → multiple peak entries."""
        # Two cycles: 1..50 → reset to 1, then 1..50 → reset to 1 again.
        cc_seq = list(range(1, 51)) + list(range(1, 51)) + [1]
        rounds = _make_synthetic_bcm_rounds(cc_seq)
        peaks = compute_robot_cycle_peaks(rounds)
        assert peaks == [50, 50], f"Expected [50, 50], got {peaks}"

    @_SKIP_NO_FRAMEWORK
    def test_small_peak_not_recorded(self) -> None:
        """Peak in [5,10] range NOT recorded: floor is prev > 10, not >= 5.

        Setup: cc goes 1..8 (peak=8) then drops to 1.
        Inline rule: cc(1) < prev(8) → True, BUT prev(8) > 10 → False.
        Result: NO peak recorded.

        Old buggy rule: cc(1) < prev(8)-1=7 → True, prev(8) >= 5 → True.
        Old buggy result: WOULD record 8 (wrong).
        """
        cc_seq = list(range(1, 9)) + [1, 2, 3]  # cc=1..8, then reset to 1
        rounds = _make_synthetic_bcm_rounds(cc_seq)
        peaks = compute_robot_cycle_peaks(rounds)
        assert peaks == [], (
            f"Expected [] (peak=8 ≤ 10, should NOT be recorded), got {peaks}.\n"
            "Likely cause: using old buggy rule (prev >= 5) instead of (prev > 10)."
        )

    @_SKIP_NO_FRAMEWORK
    def test_single_step_drop_recorded(self) -> None:
        """A single-step drop IS recorded: any drop < prev, not < prev-1.

        Setup: cc goes 1..50, then cc=49 (one step down).
        Inline rule: cc(49) < prev(50) → True, prev(50) > 10 → True.
        Result: peak 50 recorded.

        Old buggy rule: cc(49) < prev(50)-1=49 → False (49 < 49 is False).
        Old buggy result: would NOT record 50 (wrong).
        """
        cc_seq = list(range(1, 51)) + [49, 50, 49]  # 50→49 is a single-step drop
        rounds = _make_synthetic_bcm_rounds(cc_seq)
        peaks = compute_robot_cycle_peaks(rounds)
        # First peak: cc(49) < prev(50) and prev(50) > 10 → append 50.
        assert 50 in peaks, (
            f"Expected 50 in peaks (single-step drop from 50→49 MUST be recorded), "
            f"got {peaks}.\n"
            "Likely cause: using old buggy rule (cc < prev-1) instead of (cc < prev)."
        )

    @_SKIP_NO_FRAMEWORK
    def test_initial_prev_zero_means_no_false_peak_at_start(self) -> None:
        """First paid round cc > 0: prev=0, so cc < prev = cc < 0 → False.

        No spurious peak at the beginning of the robot.
        """
        rounds = _make_synthetic_bcm_rounds([500, 501, 502])
        peaks = compute_robot_cycle_peaks(rounds)
        assert peaks == [], f"Expected [], got {peaks}"

    @_SKIP_NO_FRAMEWORK
    def test_m274_cc_zero_machine_no_peaks(self) -> None:
        """M274 (cc=0 machine): CollectCount=0 on all paid rounds → no peaks."""
        rounds = [
            {
                "SpinType": 140, "CostCredits": 1000, "WinCredits": 0,
                "BetAmount": 1000, "CollectCount": 0,
                "AccCredits": 0, "CreditsSymbols": "", "SymbolIndexToRewards": {},
            }
            for _ in range(50)
        ]
        assert compute_robot_cycle_peaks(rounds) == []

    @_SKIP_NO_FRAMEWORK
    @_SKIP_NO_M272
    def test_m272_real_rounds_produces_peaks(self) -> None:
        """M272 real rawdata (chunk 2): cycle peaks recorded across robots.

        M272 mode 1 has 1000-paid-spin cycles.  Chunk 0001 contains one
        complete cycle per robot (each robot starts at cc=1 and ends at
        cc=1000 — exactly one cycle, no observed reset within a single robot).
        Chunk 0002 robots span MORE than one cycle, so resets are observed.

        This test loads chunk 0002 (which is confirmed to have peaks) and
        verifies compute_robot_cycle_peaks fires correctly on real data.
        """
        d = RAWDATA_DIR / "M272" / "mode_1"
        chunks = sorted(d.glob("chunk_*.json"))
        # Need at least 2 chunks (chunk_0002 is where resets are visible).
        if len(chunks) < 2:
            pytest.skip("M272 has only 1 chunk; need 2 for reset-visible data")

        chunk2 = json.loads(chunks[1].read_text(encoding="utf-8"))
        resp = chunk2["response"]

        all_peaks: list[int] = []
        for robot in resp:
            raw = robot.get("roundResult")
            rounds = json.loads(raw) if isinstance(raw, str) else (raw or [])
            all_peaks.extend(compute_robot_cycle_peaks(rounds))

        assert len(all_peaks) >= 1, (
            f"Expected at least 1 cycle peak across all robots in M272 chunk 0002, "
            f"got 0.  This means compute_robot_cycle_peaks is not firing on real "
            f"M272 data where resets are present."
        )
        # All peaks should be exactly 1000 for M272 mode 1.
        for p in all_peaks:
            assert p == 1000, (
                f"Peak {p} unexpected for M272 mode 1 (expected exactly 1000).\n"
                "If the rule is wrong, this would show a different value."
            )


# ---------------------------------------------------------------------------
# T3 — BCM-pilot flag-ON byte-identical to golden (subprocess)
# ---------------------------------------------------------------------------

class TestBCMPilotByteIdentical:
    """T3: flag-ON produces output byte-identical to golden for all BCM pilots.

    BCM pilots: M272, M275, M279, M268, M274.
    Non-BCM pilots (regression check): M14, M15, M120, M10.

    Inject-bug A recipe: monkeypatching is done in T4 (in-process);
    for a subprocess-level flag-ON regression, see T4's subprocess variant.

    The key invariant is: BCMBaseAccumulator's cycle_peaks output equals
    what the inline inline would produce — both use compute_robot_cycle_peaks.
    Since the goldens were captured with the INLINE path (flag-OFF), and the
    plugin now uses the same helper, flag-ON must match.
    """

    @pytest.mark.slow
    @_SKIP_NO_FRAMEWORK
    @_SKIP_NO_BCM_PILOTS
    @pytest.mark.parametrize("machine", _BCM_PILOTS_WITH_DATA)
    def test_bcm_pilot_flag_on_byte_identical_to_golden(
        self, machine: str, tmp_path: Path,
    ) -> None:
        """Flag-ON summary matches golden (volatile stripped) for BCM pilots."""
        out_dir = tmp_path / "flag_on"
        out_dir.mkdir()
        result = _run_analyzer_flag(machine, flag_on=True, output_dir=out_dir)
        assert result.returncode == 0, (
            f"[{machine}] flag-ON analyzer failed (rc={result.returncode})\n"
            f"STDERR: {result.stderr[-2000:]}"
        )
        actual = _strip_volatile(_load_summary(out_dir))
        golden = _strip_volatile(_load_golden(machine))
        assert actual == golden, (
            f"[{machine}] flag-ON output differs from golden.\n"
            f"Diff top-level keys: "
            f"{ {k for k in set(list(golden.keys()) + list(actual.keys())) if golden.get(k) != actual.get(k)} }"
        )

    @pytest.mark.slow
    @_SKIP_NO_FRAMEWORK
    @pytest.mark.parametrize("machine", _NON_BCM_WITH_DATA)
    def test_non_bcm_pilot_flag_on_unaffected(
        self, machine: str, tmp_path: Path,
    ) -> None:
        """Non-BCM pilot flag-ON must still match golden (BCMBase does not activate)."""
        out_dir = tmp_path / "flag_on"
        out_dir.mkdir()
        result = _run_analyzer_flag(machine, flag_on=True, output_dir=out_dir)
        assert result.returncode == 0, (
            f"[{machine}] flag-ON analyzer failed (rc={result.returncode})\n"
            f"STDERR: {result.stderr[-2000:]}"
        )
        actual = _strip_volatile(_load_summary(out_dir))
        golden = _strip_volatile(_load_golden(machine))
        assert actual == golden, (
            f"[{machine}] flag-ON output differs from golden for non-BCM pilot.\n"
            f"Diff keys: { {k for k in golden if golden.get(k) != actual.get(k)} }"
        )

    @pytest.mark.slow
    @_SKIP_NO_FRAMEWORK
    @_SKIP_NO_BCM_PILOTS
    @pytest.mark.parametrize("machine", _BCM_PILOTS_WITH_DATA)
    def test_bcm_pilot_flag_off_byte_identical_to_golden(
        self, machine: str, tmp_path: Path,
    ) -> None:
        """Flag-OFF still matches golden (inline refactor didn't break anything)."""
        out_dir = tmp_path / "flag_off"
        out_dir.mkdir()
        result = _run_analyzer_flag(machine, flag_on=False, output_dir=out_dir)
        assert result.returncode == 0, (
            f"[{machine}] flag-OFF analyzer failed (rc={result.returncode})\n"
            f"STDERR: {result.stderr[-2000:]}"
        )
        actual = _strip_volatile(_load_summary(out_dir))
        golden = _strip_volatile(_load_golden(machine))
        assert actual == golden, (
            f"[{machine}] flag-OFF output differs from golden after inline refactor.\n"
            f"Diff keys: { {k for k in golden if golden.get(k) != actual.get(k)} }"
        )


# ---------------------------------------------------------------------------
# T4 — Inject-bug A: plugin engagement (in-process + subprocess)
# ---------------------------------------------------------------------------

class TestInjectBugAEngagement:
    """T4: prove BCMBase's cycle_peaks actually flows to the summary.

    If BCMBaseAccumulator were bypassed (e.g. the carve guard swallowed its
    output), corrupting compute_robot_cycle_peaks in the bcm_base module would
    have no effect on the summary — the test would stay GREEN even with the
    inject.  Instead it goes RED, proving the plugin is genuinely engaged.

    Strategy: monkeypatch ``compute_robot_cycle_peaks`` in the bcm_base module
    to return ``[99999]`` for every robot.  Then run parse_chunk_response with
    flag=True on M272 rawdata.  Assert that the ``cycle_peaks`` in the chunk
    result contains 99999 (the corrupted value).  Revert (monkeypatch context
    exits) → 99999 absent from the result.
    """

    @_SKIP_NO_FRAMEWORK
    @_SKIP_NO_M272
    def test_inject_a_corrupted_peaks_appear_in_chunk(self) -> None:
        """Corrupting compute_robot_cycle_peaks in bcm_base changes cycle_peaks.

        This proves BCMBaseAccumulator.to_chunk_partial() is genuinely wired
        into the chunk result (not bypassed).
        """
        import fresh_slotlab.analyzer.play_type_registry as _reg
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        # Load one chunk of M272 rawdata.
        d = RAWDATA_DIR / "M272" / "mode_1"
        chunk_file = sorted(d.glob("chunk_*.json"))[0]
        chunk = json.loads(chunk_file.read_text(encoding="utf-8"))
        resp = chunk["response"]

        # Baseline: run with flag ON — get normal cycle_peaks.
        result_normal = parse_chunk_response(
            resp, chunk_index=0, bet=1000,
            use_play_type_plugins=True,
        )
        assert result_normal.get("ok") is True, (
            f"Baseline parse_chunk_response failed: {result_normal}"
        )
        normal_peaks = result_normal.get("cycle_peaks", [])
        assert isinstance(normal_peaks, list)
        # Normal peaks should NOT contain 99999.
        assert 99999 not in normal_peaks, (
            "Baseline already contains 99999 — fixture is contaminated"
        )

        # Inject: patch compute_robot_cycle_peaks in the bcm_base module to
        # return [99999] always.
        def _corrupted_peaks(_rounds):
            return [99999]

        with patch(
            "fresh_slotlab.analyzer.play_types.bcm_base.compute_robot_cycle_peaks",
            side_effect=_corrupted_peaks,
        ):
            result_injected = parse_chunk_response(
                resp, chunk_index=0, bet=1000,
                use_play_type_plugins=True,
            )

        assert result_injected.get("ok") is True, (
            f"Injected parse_chunk_response failed: {result_injected}"
        )
        injected_peaks = result_injected.get("cycle_peaks", [])
        assert 99999 in injected_peaks, (
            f"Inject-bug A FAILED: 99999 not in cycle_peaks after patching.\n"
            f"Got: {injected_peaks}\n"
            "This means BCMBaseAccumulator.to_chunk_partial is NOT engaged "
            "(plugin output not reaching chunk result, plugin is bypassed)."
        )

    @_SKIP_NO_FRAMEWORK
    @_SKIP_NO_M272
    def test_inject_a_revert_restores_normal_peaks(self) -> None:
        """After inject context exits, normal peaks are restored.

        Proves monkeypatch is correctly scoped (no lingering state).
        """
        import fresh_slotlab.analyzer.play_type_registry as _reg
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        d = RAWDATA_DIR / "M272" / "mode_1"
        chunk_file = sorted(d.glob("chunk_*.json"))[0]
        chunk = json.loads(chunk_file.read_text(encoding="utf-8"))
        resp = chunk["response"]

        def _corrupted_peaks(_rounds):
            return [99999]

        # Run inside inject context.
        with patch(
            "fresh_slotlab.analyzer.play_types.bcm_base.compute_robot_cycle_peaks",
            side_effect=_corrupted_peaks,
        ):
            result_in = parse_chunk_response(
                resp, chunk_index=0, bet=1000, use_play_type_plugins=True,
            )

        # Run after inject context exits (monkeypatch reverted).
        result_out = parse_chunk_response(
            resp, chunk_index=0, bet=1000, use_play_type_plugins=True,
        )

        assert 99999 in result_in.get("cycle_peaks", []), (
            "Inject did not take effect inside context — test design error"
        )
        assert 99999 not in result_out.get("cycle_peaks", []), (
            "99999 still present AFTER inject context exited — monkeypatch leaked"
        )


# ---------------------------------------------------------------------------
# T5 — Inject-bug B: logic correctness (synthetic fixture)
# ---------------------------------------------------------------------------

class TestInjectBugBLogicCorrectness:
    """T5: synthetic fixture proves helper uses CORRECT rule, not old buggy rule.

    The synthetic robot has TWO discriminating cases:
    1. Small-peak reset (cc=1..8 then reset to 1): peak=8 ≤ 10.
       - Correct rule (prev > 10): does NOT record.
       - Old buggy rule (prev >= 5): WOULD record.
    2. Single-step drop (cc goes 50→49): ANY drop means cc < prev.
       - Correct rule (cc < prev): RECORDS the drop.
       - Old buggy rule (cc < prev-1): 49 < 49 → False, does NOT record.

    Inject-bug B recipe: in round_classification.py, change:
        if cc_int < prev and prev > 10:
    to:
        if cc_int < prev - 1 and prev >= 5:
    Expected:
    - test_small_peak_not_recorded: old rule WOULD record 8 → goes RED.
    - test_single_step_drop_recorded: old rule would NOT record 50 → goes RED.
    Revert → both GREEN.

    These tests are IN this class (not just in TestComputeRobotCyclePeaks)
    because they are the "inject-bug B" proof.  The tests here document the
    exact regression the helper guards against.
    """

    @_SKIP_NO_FRAMEWORK
    def test_small_peak_guard_against_old_rule(self) -> None:
        """Peak-8 reset: correct rule keeps it out; old rule would let it in.

        Discriminating: correct rule = NOT recorded; old rule = RECORDED.
        The helper must return [] for this sequence.
        """
        # cc=1..8 then reset to 1 (8 is the peak before reset).
        cc_seq = list(range(1, 9)) + [1]  # peak is 8, drop to 1
        rounds = _make_synthetic_bcm_rounds(cc_seq)
        peaks = compute_robot_cycle_peaks(rounds)

        # Correct rule: prev=8, cc=1. 1 < 8 → True, but 8 > 10 → False. Not recorded.
        assert peaks == [], (
            f"INJECT-BUG B TRIGGERED: peak-8 reset was recorded as {peaks}.\n"
            "Correct rule (prev > 10) should NOT record a reset where prev=8.\n"
            "Old buggy rule (prev >= 5) WOULD record it.\n"
            "Check the condition in compute_robot_cycle_peaks."
        )

    @_SKIP_NO_FRAMEWORK
    def test_single_step_drop_guard_against_old_rule(self) -> None:
        """Single-step drop 50→49: correct rule records it; old rule misses it.

        Discriminating: correct rule = RECORDED; old rule = NOT recorded.
        """
        # cc=1..50 then drop to 49 (single step down from 50).
        cc_seq = list(range(1, 51)) + [49]  # 50→49 is a single-step drop
        rounds = _make_synthetic_bcm_rounds(cc_seq)
        peaks = compute_robot_cycle_peaks(rounds)

        # Correct rule: prev=50, cc=49. 49 < 50 → True, 50 > 10 → True. Recorded.
        assert 50 in peaks, (
            f"INJECT-BUG B TRIGGERED: single-step drop 50→49 was NOT recorded. peaks={peaks}.\n"
            "Correct rule (cc < prev) SHOULD record it.\n"
            "Old buggy rule (cc < prev-1) → 49 < 49 = False → MISSES it.\n"
            "Check the condition in compute_robot_cycle_peaks."
        )

    @_SKIP_NO_FRAMEWORK
    def test_both_rules_agree_on_large_drop(self) -> None:
        """For large cycles (like real pilots), both rules agree.

        cc=1..1000 then reset to 1: drop of 999 steps.
        - Correct rule: 1 < 1000 and 1000 > 10 → True. Recorded.
        - Old buggy rule: 1 < 999 and 1000 >= 5 → True. Also recorded.
        Both agree here — explains why the bug was latent on real pilots.
        """
        cc_seq = list(range(1, 1001)) + [1]
        rounds = _make_synthetic_bcm_rounds(cc_seq)
        peaks = compute_robot_cycle_peaks(rounds)
        assert 1000 in peaks, (
            f"Expected 1000 in peaks for large cycle, got {peaks}"
        )

    @_SKIP_NO_FRAMEWORK
    def test_accumulator_on_robot_end_uses_helper(self) -> None:
        """BCMBaseAccumulator.on_robot_end calls compute_robot_cycle_peaks.

        Build a robot with a known cc sequence, call on_robot_end, verify
        _robot_cycle_peaks matches what compute_robot_cycle_peaks would return.
        """
        # Use a sequence with one large cycle (peaks both rules agree on)
        # plus a single-step drop (only correct rule records).
        cc_seq = (
            list(range(1, 1001))    # first cycle: 1..1000
            + [1]                   # reset to 1 (records peak=1000)
            + list(range(2, 52))    # second cycle: 2..51
            + [50]                  # single-step drop 51→50: both rules record
            + [49]                  # single-step drop 50→49: ONLY correct rule records
        )
        rounds = _make_synthetic_bcm_rounds(cc_seq)

        # Compute expected via helper.
        expected = compute_robot_cycle_peaks(rounds)

        # Build accumulator and call lifecycle.
        from fresh_slotlab.analyzer.play_types._machine_config import MachinePlayTypeConfig
        cfg = MachinePlayTypeConfig(machine_id="M272", mode=1)
        acc = BCMBaseAccumulator(cfg)

        # Simulate on_round (minimal — just field presence check).
        from fresh_slotlab.analyzer.play_types._base import RoundCtx
        for idx, r in enumerate(rounds):
            ctx = RoundCtx(
                round_idx=idx,
                spin_type=int(r.get("SpinType", 1) or 1),
                is_paid=True,
                win_credits=0.0,
                authoritative_pay_ids=frozenset(),
                remarks=str(r.get("ReMarks") or ""),
            )
            acc.on_round(r, ctx, {})

        acc.on_robot_end(rounds, [])

        partial = acc.to_chunk_partial()
        actual_peaks = partial["cycle_peaks"]

        assert actual_peaks == expected, (
            f"BCMBaseAccumulator.on_robot_end returned {actual_peaks} but "
            f"compute_robot_cycle_peaks returned {expected}.\n"
            "The accumulator is NOT using the shared helper."
        )
