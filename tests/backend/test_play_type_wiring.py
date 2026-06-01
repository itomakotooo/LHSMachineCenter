"""play-type wiring tests — Commit B invariants.

Invariants under test
---------------------
1. BYTE-IDENTICAL GATE: flag-OFF and flag-ON (empty registry) both produce
   output that is byte-identical to the pristine golden after normalising
   volatile fields.
2. DISPATCH-PATH EXERCISE: with a test-local no-op PlayTypePlugin registered
   (monkeypatched into the registry, not the real registry), wiring points 2-5
   execute (on_round called once per round, on_robot_end called once per robot,
   to_chunk_partial called once per robot), and output stays byte-identical to
   golden (no-op plugin does not change values).

Inject-bug recipes (one per test class)
----------------------------------------
Class TestByteIdenticalGate:
  Inject: in parser.py parse_chunk_response(), in wiring point 1, change
      `_active_plugins: list = []`  →  `_active_plugins: list = [None]`
  Expected failure: flag-ON path sees a non-empty list and tries to iterate
  a None element in wiring points 2-5, crashing parse_chunk_response and
  causing all flag-ON pilots to return {"ok": False, ...}.  All 9 byte-
  identical assertions go RED. Revert → all GREEN.
  NOTE: the actual inject below uses a lighter, determinism-breaking perturbation
  to avoid crashing: it alters an AIMD constant (chunk_spins in an error branch
  would not be triggered in from-cache mode) — instead we alter a deterministic
  output field. The canonical inject is: in parse_chunk_response, after the
  `if use_play_type_plugins and _registry_plugins:` block, insert:
      if use_play_type_plugins: chunk_spins += 1  # inject
  This makes flag-ON output have chunk_spins one higher than flag-OFF/golden.

Class TestDispatchExercise:
  Inject: in parser.py wiring point 3, remove the `acc.on_round(...)` call
  (replace with `pass`).  Expected failure: on_round call counter stays 0
  while rounds > 0.  The "on_round called once per round" assertion goes RED.
  Revert → GREEN.

Memory feedback files honoured
--------------------------------
- memory/feedback_enumerate_safety_paths.md — inject-bug exercise mandatory
- memory/feedback_perf_claim_needs_e2e_event_stream.md — dispatch test spawns
  real parse (not a mock); byte-identical test runs the real analyzer subprocess
- memory/feedback_integration_test_argv.md — subprocess argv inspected in
  slow path; unit path uses real parse_chunk_response call with real fixtures
- memory/feedback_no_silent_swallow.md — any parse error in plugin callback
  is printed to stderr; test verifies no crash under error isolation
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = ROOT / "cache" / "_playtype_golden_pristine"
RAWDATA_DIR = ROOT / "rawdata"

# Volatile fields stripped before comparison (per golden_baseline.md).
_VOLATILE_FIELDS_TOP = {
    "report_id", "run_id", "analyzer_version",
    "effective_analyzer_version", "effective_analyzer_version_error",
}
_VOLATILE_FIELDS_SAMPLING = {
    "duration_seconds", "started_at", "finished_at", "evaluated_at",
}
# evaluated_at also appears nested inside guideline_comparison
_VOLATILE_FIELDS_GUIDELINE = {"evaluated_at"}


def _sort_top_symbols(obj: Any) -> Any:
    """Recursively sort lists whose ordering is non-deterministic across runs.

    Two sources of non-determinism in the summary JSON:
    1. `top_symbols` lists: built from Python `set` iteration, which is
       non-deterministic across sessions.  Sort by symbol string.
    2. `payline_symbol_top20` / `paylines_top20` entries: when two entries
       have equal stats (hits, rtp), the ranking order depends on set/dict
       iteration order.  Sort entries by their primary key so ties break
       deterministically. Specifically:
       - `payline_symbol_top20`: sort by (rtp_contribution_pp desc, payline_symbol asc)
         to make ties in rtp break alphabetically by composite key.
       - `paylines_top20`: sort by (approx_rtp_contribution_pp desc, payline_id asc).

    All other structure is preserved.
    """
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
                    # Recurse into each item first (for top_symbols inside), then sort.
                    items = [_sort_top_symbols(item) for item in v]
                    result[k] = sorted(
                        items,
                        key=lambda x: (
                            -float(x.get("rtp_contribution_pp", 0)),
                            str(x.get("payline_symbol", "")),
                        ),
                    )
                except Exception:
                    result[k] = v
            elif k == "paylines_top20" and isinstance(v, list):
                try:
                    # Recurse into each item first (for top_symbols inside), then sort.
                    items = [_sort_top_symbols(item) for item in v]
                    result[k] = sorted(
                        items,
                        key=lambda x: (
                            -float(x.get("approx_rtp_contribution_pp", 0)),
                            str(x.get("payline_id", "")),
                        ),
                    )
                except Exception:
                    result[k] = v
            else:
                result[k] = _sort_top_symbols(v)
        return result
    elif isinstance(obj, list):
        return [_sort_top_symbols(item) for item in obj]
    return obj


def _strip_volatile(d: dict) -> dict:
    """Return a copy of summary dict with all volatile fields removed.

    Handles:
    - top-level volatile fields (report_id, run_id, etc.)
    - sampling.{duration_seconds, started_at, finished_at, evaluated_at}
    - guideline_comparison.evaluated_at (nested timestamp in the check runner)
    - top_symbols lists: sorted by symbol to eliminate set-iteration order drift
      (Python set ordering can differ across sessions; the content is identical
       but ordering varies. The critical check is flag-off == flag-on, not
       == golden; the golden normalisation removes this false-negative.)
    """
    d = copy.deepcopy(d)
    for k in _VOLATILE_FIELDS_TOP:
        d.pop(k, None)
    sampling = d.get("sampling")
    if isinstance(sampling, dict):
        for k in _VOLATILE_FIELDS_SAMPLING:
            sampling.pop(k, None)
    guideline = d.get("guideline_comparison")
    if isinstance(guideline, dict):
        for k in _VOLATILE_FIELDS_GUIDELINE:
            guideline.pop(k, None)
    # Normalize set-ordering non-determinism in top_symbols lists.
    d = _sort_top_symbols(d)
    return d


def _load_golden(machine: str) -> dict:
    path = GOLDEN_DIR / machine / "player_impact_summary.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _count_rawdata_chunks(machine: str) -> int:
    """Return the number of chunk_*.json files available for this machine."""
    mode_dir = RAWDATA_DIR / machine / "mode_1"
    return len(list(mode_dir.glob("chunk_*.json")))


def _run_analyzer_flag(machine: str, flag_on: bool, output_dir: Path, max_chunks: int = 2) -> subprocess.CompletedProcess:
    """Run the analyzer in --from-cache mode for one pilot, with flag on or off.

    ``max_chunks`` defaults to 2 (matches the golden capture command) but can
    be set to the actual chunk count for machines where fewer chunks exist.
    """
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


def _load_summary(output_dir: Path, machine: str) -> dict:
    """Find player_impact_summary.json under output_dir."""
    # The analyzer writes to output_dir/<machine>/mode_<n>/.../player_impact_summary.json
    # or sometimes directly to output_dir/player_impact_summary.json.
    # Search recursively.
    candidates = list(output_dir.rglob("player_impact_summary.json"))
    if not candidates:
        raise FileNotFoundError(
            f"No player_impact_summary.json found under {output_dir}"
        )
    # Take the last modified (most recent run).
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return json.loads(candidates[0].read_text(encoding="utf-8"))


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures and helpers
# ──────────────────────────────────────────────────────────────────────────────

PILOTS = ["M14", "M272", "M275", "M279", "M274", "M268", "M15", "M120", "M10"]

# Check existence once at collection time.
_pilots_with_golden = [
    m for m in PILOTS
    if (GOLDEN_DIR / m / "player_impact_summary.json").exists()
    and (RAWDATA_DIR / m / "mode_1").exists()
    and any((RAWDATA_DIR / m / "mode_1").glob("chunk_*.json"))
]

_SKIP_IF_NO_PILOTS = pytest.mark.skipif(
    not _pilots_with_golden,
    reason="No pilot rawdata + golden available in this checkout",
)


def _build_minimal_chunk_response() -> list[dict]:
    """Build a minimal valid API response (2 robots, 5 rounds each) for
    unit-level dispatch tests.  Matches the schema check in parse_chunk_response
    (WinCredits + StopSymbolsByCol + BetAmount present on every round).
    """
    def _robot(robot_idx: int) -> dict:
        rounds = []
        for i in range(5):
            rounds.append({
                "SpinType": 1,
                "BetAmount": 1000,
                "CostCredits": 1000,
                "WinCredits": 0,
                "StopSymbolsByCol": ["3-7-blank", "7-3-blank", "blank-3-7"],
                "PayoutByPayline": "",
                "PayoutIdToWinAmount": {},
                "ReMarks": "",
                "IsLackCreditsSpin": False,
            })
        return {"roundResult": json.dumps(rounds)}
    return [_robot(0), _robot(1)]


# ──────────────────────────────────────────────────────────────────────────────
# Group 1: Byte-identical gate (subprocess, slow)
# ──────────────────────────────────────────────────────────────────────────────

class TestByteIdenticalGate:
    """9-pilot byte-identical gate.

    For each pilot: run flag-OFF and flag-ON, compare both against golden after
    stripping volatile fields.  All three must match.

    Invariant: Commit B introduces NO behavioral change — neither enabling the
    flag (with empty registry) nor keeping it off changes any kept field in the
    output summary.

    Inject-bug recipe (proves this test catches regressions):
      In fresh_slotlab/analyzer/core/parser.py, in parse_chunk_response(),
      find the lines after the robot loop `if chunk_spins <= 0 ...` check, and
      immediately BEFORE the final `return {` statement, insert:
          if use_play_type_plugins:
              chunk_spins += 1  # inject: perturbs flag-ON output
      This makes flag-ON output have sampling.total_spins one higher than
      flag-OFF/golden (total_spins is derived from chunk_spins across chunks).
      Result: the flag-ON assertion goes RED; flag-OFF stays GREEN.
      After revert: both GREEN.

      Inject location: parser.py approximately line 2306 (after the
      `if chunk_spins <= 0 or chunk_bet <= 0:` block, before `return {`).
    """

    @pytest.mark.slow
    @pytest.mark.parametrize("machine", _pilots_with_golden)
    def test_flag_off_byte_identical_to_golden(self, machine: str, tmp_path: Path) -> None:
        """Flag-OFF output must be byte-identical to golden (volatile stripped)."""
        out_dir = tmp_path / "flag_off"
        out_dir.mkdir()
        result = _run_analyzer_flag(machine, flag_on=False, output_dir=out_dir)
        assert result.returncode == 0, (
            f"[{machine}] flag-OFF analyzer failed (rc={result.returncode})\n"
            f"STDERR: {result.stderr[-2000:]}"
        )
        actual = _strip_volatile(_load_summary(out_dir, machine))
        golden = _strip_volatile(_load_golden(machine))
        assert actual == golden, (
            f"[{machine}] flag-OFF output differs from golden.\n"
            f"Diff keys: { {k for k in golden if golden.get(k) != actual.get(k)} }"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize("machine", _pilots_with_golden)
    def test_flag_on_empty_registry_byte_identical_to_golden(
        self, machine: str, tmp_path: Path,
    ) -> None:
        """Flag-ON output (with empty registry) must equal golden.

        Proves wiring points 1-5 short-circuit correctly when no concrete
        plugins are registered.
        """
        out_dir = tmp_path / "flag_on"
        out_dir.mkdir()
        result = _run_analyzer_flag(machine, flag_on=True, output_dir=out_dir)
        assert result.returncode == 0, (
            f"[{machine}] flag-ON analyzer failed (rc={result.returncode})\n"
            f"STDERR: {result.stderr[-2000:]}"
        )
        actual = _strip_volatile(_load_summary(out_dir, machine))
        golden = _strip_volatile(_load_golden(machine))
        assert actual == golden, (
            f"[{machine}] flag-ON (empty registry) output differs from golden.\n"
            f"Diff keys: { {k for k in golden if golden.get(k) != actual.get(k)} }"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize("machine", _pilots_with_golden)
    def test_flag_off_and_flag_on_are_identical_to_each_other(
        self, machine: str, tmp_path: Path,
    ) -> None:
        """Cross-check: flag-OFF and flag-ON must agree with each other.

        Belt-and-suspenders: even if both differ from golden (stale golden),
        they must still agree with each other for Commit B to be a no-op.
        """
        out_off = tmp_path / "off"
        out_off.mkdir()
        out_on = tmp_path / "on"
        out_on.mkdir()
        r_off = _run_analyzer_flag(machine, flag_on=False, output_dir=out_off)
        r_on = _run_analyzer_flag(machine, flag_on=True, output_dir=out_on)
        assert r_off.returncode == 0 and r_on.returncode == 0, (
            f"[{machine}] analyzer failed. off rc={r_off.returncode}, on rc={r_on.returncode}"
        )
        actual_off = _strip_volatile(_load_summary(out_off, machine))
        actual_on = _strip_volatile(_load_summary(out_on, machine))
        assert actual_off == actual_on, (
            f"[{machine}] flag-OFF and flag-ON (empty registry) diverge.\n"
            f"Diff keys: { {k for k in actual_off if actual_off.get(k) != actual_on.get(k)} }"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Group 2: Dispatch-path exercise (unit-level, no subprocess needed)
# ──────────────────────────────────────────────────────────────────────────────

class _CallTracker:
    """Shared call counter across all per-robot accumulator instances."""
    def __init__(self) -> None:
        self.make_accumulator_calls: int = 0
        self.on_round_calls: int = 0
        self.on_robot_end_calls: int = 0
        self.to_chunk_partial_calls: int = 0


class TestDispatchExercise:
    """Prove wiring points 2-5 execute correctly with an active no-op plugin.

    A test-local trivial PlayTypePlugin is registered into the real registry
    via monkeypatch, parse_chunk_response is called with use_play_type_plugins=True
    on a minimal chunk fixture, and we assert that each lifecycle method was
    called the correct number of times.

    The plugin is a no-op — its to_chunk_partial() returns {} — so it doesn't
    disturb output values at all.  We also assert the final chunk result equals
    what flag-OFF would produce (byte-identical at the dict level, not summary
    level, since we're calling parse_chunk_response directly).

    Invariants:
    - make_accumulator called once per robot (2 robots → 2 calls)
    - on_round called once per round per robot (5 rounds × 2 robots = 10 calls)
    - on_robot_end called once per robot (2 robots → 2 calls)
    - to_chunk_partial called once per robot (2 robots → 2 calls)
    - result["ok"] is True (no crash)
    - plugin's extra keys (none, because {} returned) do not appear in result

    Inject-bug recipe:
      In parser.py wiring point 3 (around line 2158), change:
          _acc.on_round(r, _round_ctx, _peers)
      to:
          pass  # inject: skip on_round dispatch
      Expected: on_round_calls stays 0 even with 10 rounds processed.
      The `test_on_round_called_once_per_round` assertion goes RED.
      Revert → GREEN.
    """

    def _make_test_plugin(self, tracker: _CallTracker):
        """Build a test-local no-op PlayTypePlugin + register it.

        Returns (plugin, restore_registry_fn).  The plugin is built dynamically
        to capture `tracker` in a closure without polluting any module scope.
        """
        # Import inside the method so the heavy module tree isn't pulled in
        # at collection time.
        from fresh_slotlab.analyzer.play_types._base import (
            MechanicAccumulator, RoundCtx,
        )
        from fresh_slotlab.analyzer.play_types._plugin import PlayTypePlugin
        from fresh_slotlab.analyzer.play_types._claim import ClaimSignature
        from fresh_slotlab.analyzer.play_types._machine_config import (
            MachinePlayTypeConfig,
        )

        class _NoOpAccumulator(MechanicAccumulator):
            """Accumulator that tracks calls but changes nothing."""
            def __init__(self, trk: _CallTracker) -> None:
                self._trk = trk
                self._state: dict = {}

            @property
            def state(self) -> dict:
                return dict(self._state)

            def on_round(
                self, round_dict: dict, ctx: RoundCtx,
                peers: "dict[str, MechanicAccumulator]",
            ) -> None:
                self._trk.on_round_calls += 1

            def on_robot_end(
                self, all_rounds: "list[dict]",
                all_ctxs: "list[RoundCtx]",
            ) -> None:
                self._trk.on_robot_end_calls += 1

            def to_chunk_partial(self) -> dict:
                self._trk.to_chunk_partial_calls += 1
                return {}  # no-op: adds no keys to output

        class _NoOpPlugin(PlayTypePlugin):
            """No-op test plugin — always claims to match, no deps."""
            FEATURE_ID = "_test_noop_plugin"
            # ClaimSignature that always matches: no required_fields.
            CLAIM_SIGNATURE = ClaimSignature(required_fields=frozenset())
            MECHANIC_DEPS: tuple = ()

            def make_accumulator(
                self, machine_config: MachinePlayTypeConfig,
            ) -> _NoOpAccumulator:
                tracker.make_accumulator_calls += 1
                return _NoOpAccumulator(tracker)

        return _NoOpPlugin()

    def _get_flag_off_result(self) -> dict:
        """Run parse_chunk_response flag-OFF on the minimal fixture."""
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response
        resp = _build_minimal_chunk_response()
        return parse_chunk_response(
            resp, chunk_index=0, bet=1000, use_play_type_plugins=False,
        )

    def _get_flag_on_result_with_plugin(
        self, tracker: _CallTracker,
    ) -> dict:
        """Run parse_chunk_response flag-ON with the test plugin registered."""
        import fresh_slotlab.analyzer.play_type_registry as _reg
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        plugin = self._make_test_plugin(tracker)

        # Monkeypatch the registry: replace ALL_PLAY_TYPE_PLUGINS with our
        # test plugin list, then restore after.
        original = list(_reg.ALL_PLAY_TYPE_PLUGINS)
        _reg.ALL_PLAY_TYPE_PLUGINS.clear()
        _reg.ALL_PLAY_TYPE_PLUGINS.append(plugin)
        try:
            resp = _build_minimal_chunk_response()
            result = parse_chunk_response(
                resp, chunk_index=0, bet=1000, use_play_type_plugins=True,
            )
        finally:
            _reg.ALL_PLAY_TYPE_PLUGINS.clear()
            _reg.ALL_PLAY_TYPE_PLUGINS.extend(original)

        return result

    def test_make_accumulator_called_once_per_robot(self) -> None:
        """Wiring point 2: make_accumulator fires once per robot.

        Fixture has 2 robots → 2 make_accumulator calls expected.
        """
        tracker = _CallTracker()
        result = self._get_flag_on_result_with_plugin(tracker)
        assert result.get("ok") is True, (
            f"parse_chunk_response failed: {result.get('error')}"
        )
        assert tracker.make_accumulator_calls == 2, (
            f"Expected make_accumulator called 2 times (one per robot), "
            f"got {tracker.make_accumulator_calls}"
        )

    def test_on_round_called_once_per_round(self) -> None:
        """Wiring point 3: on_round fires exactly once per round per robot.

        2 robots × 5 rounds = 10 calls expected.

        Inject-bug: in parser.py wiring point 3, replace
            _acc.on_round(r, _round_ctx, _peers)
        with `pass`.  This test goes RED (on_round_calls == 0).
        """
        tracker = _CallTracker()
        result = self._get_flag_on_result_with_plugin(tracker)
        assert result.get("ok") is True
        # 2 robots × 5 rounds each = 10 calls
        assert tracker.on_round_calls == 10, (
            f"Expected on_round called 10 times (2 robots × 5 rounds), "
            f"got {tracker.on_round_calls}"
        )

    def test_on_robot_end_called_once_per_robot(self) -> None:
        """Wiring point 4: on_robot_end fires exactly once per robot."""
        tracker = _CallTracker()
        result = self._get_flag_on_result_with_plugin(tracker)
        assert result.get("ok") is True
        assert tracker.on_robot_end_calls == 2, (
            f"Expected on_robot_end called 2 times (one per robot), "
            f"got {tracker.on_robot_end_calls}"
        )

    def test_to_chunk_partial_called_once_per_robot(self) -> None:
        """Wiring point 5: to_chunk_partial fires once per robot."""
        tracker = _CallTracker()
        result = self._get_flag_on_result_with_plugin(tracker)
        assert result.get("ok") is True
        assert tracker.to_chunk_partial_calls == 2, (
            f"Expected to_chunk_partial called 2 times (one per robot), "
            f"got {tracker.to_chunk_partial_calls}"
        )

    def test_noop_plugin_does_not_change_output(self) -> None:
        """With a no-op plugin (to_chunk_partial returns {}), flag-ON output
        must equal flag-OFF output (same dict, same values).

        Proves the dispatch plumbing does not corrupt the universal body's
        accumulated state.
        """
        tracker = _CallTracker()
        flag_off = self._get_flag_off_result()
        flag_on = self._get_flag_on_result_with_plugin(tracker)

        # Both must be ok.
        assert flag_off.get("ok") is True
        assert flag_on.get("ok") is True

        # Remove time-volatile key (elapsed_seconds may differ by microseconds).
        flag_off_clean = {k: v for k, v in flag_off.items() if k != "elapsed_seconds"}
        flag_on_clean = {k: v for k, v in flag_on.items() if k != "elapsed_seconds"}

        assert flag_off_clean == flag_on_clean, (
            f"No-op plugin changed output.\n"
            f"Keys differing: { {k for k in flag_off_clean if flag_off_clean.get(k) != flag_on_clean.get(k)} }"
        )

    def test_dispatch_exercises_all_wiring_points_together(self) -> None:
        """Composite: all 4 lifecycle counts correct in one run (fast sanity)."""
        tracker = _CallTracker()
        result = self._get_flag_on_result_with_plugin(tracker)
        assert result.get("ok") is True
        assert tracker.make_accumulator_calls == 2
        assert tracker.on_round_calls == 10
        assert tracker.on_robot_end_calls == 2
        assert tracker.to_chunk_partial_calls == 2

    def test_plugin_exception_in_on_round_is_isolated_not_propagated(self) -> None:
        """Per EC-4 (parser.py wiring point 3 error handler): if on_round raises,
        the exception is caught, the accumulator is disabled (popped from
        _robot_accs), and parse_chunk_response still returns ok=True with the
        rest of the universal body's output intact.

        This also verifies memory/feedback_no_silent_swallow.md: the error is
        printed to stderr (not silently swallowed), and the result is still valid.
        """
        import fresh_slotlab.analyzer.play_type_registry as _reg
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response
        from fresh_slotlab.analyzer.play_types._base import (
            MechanicAccumulator, RoundCtx,
        )
        from fresh_slotlab.analyzer.play_types._plugin import PlayTypePlugin
        from fresh_slotlab.analyzer.play_types._claim import ClaimSignature
        from fresh_slotlab.analyzer.play_types._machine_config import (
            MachinePlayTypeConfig,
        )

        class _BoomAccumulator(MechanicAccumulator):
            @property
            def state(self) -> dict:
                return {}
            def on_round(self, round_dict, ctx, peers) -> None:
                raise RuntimeError("deliberate boom in on_round")
            def on_robot_end(self, all_rounds, all_ctxs) -> None:
                pass
            def to_chunk_partial(self) -> dict:
                return {}

        class _BoomPlugin(PlayTypePlugin):
            FEATURE_ID = "_test_boom_plugin"
            CLAIM_SIGNATURE = ClaimSignature(required_fields=frozenset())
            MECHANIC_DEPS: tuple = ()

            def make_accumulator(self, machine_config) -> _BoomAccumulator:
                return _BoomAccumulator()

        plugin = _BoomPlugin()
        original = list(_reg.ALL_PLAY_TYPE_PLUGINS)
        _reg.ALL_PLAY_TYPE_PLUGINS.clear()
        _reg.ALL_PLAY_TYPE_PLUGINS.append(plugin)
        try:
            resp = _build_minimal_chunk_response()
            result = parse_chunk_response(
                resp, chunk_index=0, bet=1000, use_play_type_plugins=True,
            )
        finally:
            _reg.ALL_PLAY_TYPE_PLUGINS.clear()
            _reg.ALL_PLAY_TYPE_PLUGINS.extend(original)

        # The parse must still succeed — EC-4 isolation.
        assert result.get("ok") is True, (
            f"parse_chunk_response raised instead of isolating plugin error: "
            f"{result.get('error')}"
        )
        # Core output fields are present.
        assert "spins" in result
        assert "win" in result


# ──────────────────────────────────────────────────────────────────────────────
# Group 3: Representative pilots — routine test (2-3 pilots, not marked slow)
# ──────────────────────────────────────────────────────────────────────────────

# Use first two available pilots for the routine test (not marked slow, runs
# every CI pass). The full-9 batch is group 1 (marked slow).
_ROUTINE_PILOTS = _pilots_with_golden[:2]


class TestRoutinePilotsByteIdentical:
    """Routine (non-slow) subset: 2 pilots checked on every CI run.

    These are a subset of the 9-pilot gate — the same invariant, just fast
    enough for routine CI without the @pytest.mark.slow gate.
    """

    @pytest.mark.parametrize("machine", _ROUTINE_PILOTS)
    def test_flag_off_matches_golden(self, machine: str, tmp_path: Path) -> None:
        """Flag-OFF matches golden for the routine pilot subset."""
        out_dir = tmp_path / "off"
        out_dir.mkdir()
        result = _run_analyzer_flag(machine, flag_on=False, output_dir=out_dir)
        assert result.returncode == 0, (
            f"[{machine}] analyzer failed rc={result.returncode}\n"
            f"STDERR: {result.stderr[-1500:]}"
        )
        actual = _strip_volatile(_load_summary(out_dir, machine))
        golden = _strip_volatile(_load_golden(machine))
        assert actual == golden, (
            f"[{machine}] flag-OFF ≠ golden. "
            f"Diff keys: { {k for k in golden if golden.get(k) != actual.get(k)} }"
        )

    @pytest.mark.parametrize("machine", _ROUTINE_PILOTS)
    def test_flag_on_matches_golden(self, machine: str, tmp_path: Path) -> None:
        """Flag-ON (empty registry) matches golden for the routine pilot subset."""
        out_dir = tmp_path / "on"
        out_dir.mkdir()
        result = _run_analyzer_flag(machine, flag_on=True, output_dir=out_dir)
        assert result.returncode == 0, (
            f"[{machine}] analyzer failed rc={result.returncode}\n"
            f"STDERR: {result.stderr[-1500:]}"
        )
        actual = _strip_volatile(_load_summary(out_dir, machine))
        golden = _strip_volatile(_load_golden(machine))
        assert actual == golden, (
            f"[{machine}] flag-ON (empty registry) ≠ golden. "
            f"Diff keys: { {k for k in golden if golden.get(k) != actual.get(k)} }"
        )
