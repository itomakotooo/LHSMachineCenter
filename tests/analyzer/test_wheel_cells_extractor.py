"""wheel_cells STExtractor — ISOLATION unit tests (VALUE-AGNOSTIC).

Charter: the unit is the SpinType (EVENT); we test STRUCTURE / determinism /
honesty INVARIANTS of the extractor, never an RTP value. This file exercises the
extractor in ISOLATION (no report engine, no real rawdata) so the determinism
alarm and the honesty contracts are proven on tiny synthetic inputs whose ground
truth is unambiguous.

What wheel_cells delivers (fresh_slotlab/analyzer/st_extract/wheel_cells.py):
  - per declared-wheel-ST round it regexes the cell index out of ReMarks
    ("WheelSpin CellIndex <n>; ...") and records prize_mult = win/bet;
  - each cell is meant to be DETERMINISTIC (exactly one prize). A cell that ever
    pays >1 distinct prize is a DATA ALARM in `nondeterministic_cells` and its
    `prize_multiplier` is emitted as null (NEVER a silently-picked one);
  - an unobserved declared cell -> null prize, hit_count 0 (never fabricated);
  - a ReMarks string WITHOUT a CellIndex -> a counted skip, never a crash;
  - DECLARED_IN_KEY = "wheel_cells" — only a manifest spin_types block carrying a
    "wheel_cells" dict selects this extractor (machines without it are unaffected).

Inject-bug -> RED -> revert -> GREEN (TestInjectBugProof):
  Each safety claim is paired with a recipe that, applied to wheel_cells.py, makes
  exactly one test go RED — proving the test is NOT vacuous. The recipes are
  documented inline; this file's tests verify the LIVE (correct) behavior, and a
  red-test partner runs the inject manually on a copied module (the determinism
  alarm one is also proven dynamically below by feeding a nondeterministic cell —
  if the alarm logic were deleted the test fixture itself would catch a silent
  pick).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WHEEL_CELLS_SRC = (
    _REPO_ROOT / "fresh_slotlab" / "analyzer" / "st_extract" / "wheel_cells.py"
)


# ---------------------------------------------------------------------------
# Helpers — drive the extractor directly (begin_robot / observe_round /
# finalize_chunk), no parser, no report engine.
# ---------------------------------------------------------------------------

def _wheel_cells_cls():
    from fresh_slotlab.analyzer.st_extract.wheel_cells import WheelCellsExtractor
    return WheelCellsExtractor


def _manifest(
    st: int = 2,
    *,
    cell_count: int | None = 12,
    remarks_field: str = "ReMarks",
    cell_pattern: str | None = None,
    include_block: bool = True,
) -> dict:
    """A minimal SpinType-native manifest declaring (or not) a wheel_cells block."""
    block: dict = {}
    if cell_pattern is not None:
        block["cell_pattern"] = cell_pattern
    if remarks_field != "ReMarks":
        block["remarks_field"] = remarks_field
    if cell_count is not None:
        block["cell_count"] = cell_count
    block.setdefault("spin_type", st)
    st_spec: dict = {"role": "settlement", "play": "Wheel"}
    if include_block:
        st_spec["wheel_cells"] = block
    return {
        "machine_id": "M_synthetic_wheel",
        "spin_types": {str(st): st_spec},
    }


def _round(cell: int | None, *, win: float, remarks_field: str = "ReMarks",
           remarks: str | None = None) -> dict:
    """A synthetic wheel round. cell=None -> ReMarks with NO CellIndex."""
    if remarks is None:
        remarks = (
            f"WheelSpin CellIndex {cell}; WheelId 1;" if cell is not None
            else "WheelSpin WheelId 1;"  # no CellIndex token
        )
    return {"SpinType": 2, remarks_field: remarks, "WinCredits": win}


def _run(extractor, rounds: list[dict], *, bet: int = 1000, st: int = 2) -> dict:
    """Drive one robot of rounds through the extractor and finalize the chunk.

    round_ctx mirrors the parser's contract: it exposes a rule-view "win" (here
    we use the round's raw win — on the wheel STs raw == rule-view) and "bet".
    """
    extractor.begin_robot({"robot_idx": 0})
    for i, r in enumerate(rounds):
        win = float(r.get("WinCredits") or 0.0)
        extractor.observe_round(
            r, st, {"robot_idx": 0, "round_idx": i, "bet": bet, "win": win},
        )
    return extractor.finalize_chunk()


# ---------------------------------------------------------------------------
# 1. Determinism ALARM — the headline value-agnostic guard (NOT vacuous).
# ---------------------------------------------------------------------------

class TestDeterminismAlarm:
    def test_clean_cells_no_alarm(self):
        """Every cell pays exactly one prize -> nondeterministic_cells EMPTY,
        each cell's prize_multiplier is the singleton."""
        cls = _wheel_cells_cls()
        ext = cls.clone_for_manifest(_manifest(cell_count=4))
        rounds = [
            _round(1, win=5000), _round(1, win=5000),   # cell 1 -> 5x always
            _round(2, win=20000), _round(2, win=20000),  # cell 2 -> 20x always
        ]
        out = _run(ext, rounds)["2"]
        assert out["nondeterministic_cells"] == {}, (
            f"clean cells must have NO determinism alarm; got {out['nondeterministic_cells']}"
        )
        assert out["cell_map"]["1"]["prize_multiplier"] == 5
        assert out["cell_map"]["2"]["prize_multiplier"] == 20

    def test_nondeterministic_cell_fires_alarm_and_nulls_prize(self):
        """RED-TEST (not vacuous): a cell observed paying TWO distinct prizes
        (20x and 30x) must be recorded in nondeterministic_cells AND its
        prize_multiplier emitted as NULL — never a silently-picked one.

        INJECT-BUG recipe (wheel_cells.py finalize_chunk, ~line 289): replace
            if len(prizes) == 1:
                prize_multiplier = self._coerce_mult(next(iter(prizes)))
            else:
                prize_multiplier = None
                nondeterministic[str(cell)] = sorted(...)
        with `prize_multiplier = self._coerce_mult(next(iter(prizes)))` for ALL
        cardinalities (silently pick one, drop the alarm) -> this test goes RED
        (nondeterministic_cells empty + prize not null). Revert -> GREEN.
        """
        cls = _wheel_cells_cls()
        ext = cls.clone_for_manifest(_manifest(cell_count=4))
        rounds = [
            _round(3, win=20000),  # cell 3 -> 20x
            _round(3, win=30000),  # cell 3 -> 30x  (CONTRADICTION -> ALARM)
        ]
        out = _run(ext, rounds)["2"]
        assert "3" in out["nondeterministic_cells"], (
            "a cell paying >1 distinct prize MUST be flagged in "
            f"nondeterministic_cells; got {out['nondeterministic_cells']}"
        )
        assert sorted(out["nondeterministic_cells"]["3"]) == [20, 30], (
            f"the alarm must record BOTH observed prizes; got "
            f"{out['nondeterministic_cells']['3']}"
        )
        assert out["cell_map"]["3"]["prize_multiplier"] is None, (
            "a nondeterministic cell's prize_multiplier must be NULL "
            "(NOT silently resolved to one of the two values)"
        )
        # The nondeterministic cell must NOT pollute the jackpot derivation.
        assert 3 not in (out["jackpot"]["cells"] or []), (
            "a nondeterministic cell cannot be a jackpot cell (its prize is unknown)"
        )


# ---------------------------------------------------------------------------
# 2. Unobserved cell -> honest null (never fabricated).
# ---------------------------------------------------------------------------

class TestUnobservedCellHonesty:
    def test_unobserved_declared_cell_is_null_not_fabricated(self):
        """A declared cell never seen in the sample -> prize null, hit_count 0,
        present in unobserved_cells. NEVER interpolated / phantom-counted."""
        cls = _wheel_cells_cls()
        # Declare 4 cells; only observe cells 1 and 2.
        ext = cls.clone_for_manifest(_manifest(cell_count=4))
        out = _run(ext, [_round(1, win=5000), _round(2, win=20000)])["2"]
        assert set(out["unobserved_cells"]) == {3, 4}, (
            f"cells 3 & 4 are declared-but-unobserved; got {out['unobserved_cells']}"
        )
        for c in ("3", "4"):
            assert out["cell_map"][c]["prize_multiplier"] is None, (
                f"unobserved cell {c} must have null prize (never fabricated)"
            )
            assert out["cell_map"][c]["hit_count"] == 0
        # The unobserved cells must NOT leak into distinct_prizes.
        assert out["distinct_prizes"] == [5, 20], (
            f"distinct_prizes must contain ONLY observed prizes; got {out['distinct_prizes']}"
        )


# ---------------------------------------------------------------------------
# 3. ReMarks without CellIndex -> counted skip, never a crash.
# ---------------------------------------------------------------------------

class TestSkipNotCrash:
    def test_remarks_without_cellindex_is_skipped_and_counted(self):
        """A ReMarks string carrying no CellIndex token -> skipped_rounds += 1,
        no crash, no phantom cell."""
        cls = _wheel_cells_cls()
        ext = cls.clone_for_manifest(_manifest(cell_count=4))
        rounds = [
            _round(1, win=5000),
            _round(None, win=0),      # ReMarks present, NO CellIndex -> skip
            _round(2, win=20000),
        ]
        out = _run(ext, rounds)["2"]
        assert out["skipped_rounds"] == 1, (
            f"the no-CellIndex round must be a counted skip; got "
            f"skipped_rounds={out['skipped_rounds']}"
        )
        assert out["total_wheel_spins"] == 2, (
            "only the 2 parseable rounds count as wheel spins"
        )
        assert set(out["observed_cells"]) == {1, 2}

    def test_missing_remarks_field_is_skipped(self):
        """A round with the remarks field entirely absent -> counted skip,
        parser-blind-safe (only read fields the round carries; never crash)."""
        cls = _wheel_cells_cls()
        ext = cls.clone_for_manifest(_manifest(cell_count=4))
        ext.begin_robot({"robot_idx": 0})
        # Round with NO ReMarks key at all.
        ext.observe_round(
            {"SpinType": 2, "WinCredits": 0}, 2,
            {"robot_idx": 0, "round_idx": 0, "bet": 1000, "win": 0.0},
        )
        ext.observe_round(
            _round(1, win=5000), 2,
            {"robot_idx": 0, "round_idx": 1, "bet": 1000, "win": 5000.0},
        )
        out = ext.finalize_chunk()["2"]
        assert out["skipped_rounds"] == 1, (
            "a round with no ReMarks field must be a counted skip, never a crash"
        )
        assert out["observed_cells"] == [1]


# ---------------------------------------------------------------------------
# 4. DECLARED_IN_KEY gating — only "wheel_cells" blocks select this extractor.
# ---------------------------------------------------------------------------

class TestDeclaredInKeyGating:
    def test_declared_in_key_is_wheel_cells(self):
        cls = _wheel_cells_cls()
        assert cls.DECLARED_IN_KEY == "wheel_cells", (
            "the extractor must self-declare DECLARED_IN_KEY='wheel_cells'"
        )
        assert cls.EXTRACTOR_ID == "wheel_cells"

    def test_manifest_with_wheel_cells_selects_extractor(self):
        """A manifest declaring a wheel_cells block selects exactly one
        WheelCellsExtractor via get_extractors_for_manifest."""
        from fresh_slotlab.analyzer.st_extract import (
            discover_extractors, get_extractors_for_manifest,
        )
        discover_extractors()
        cls = _wheel_cells_cls()
        result = get_extractors_for_manifest(_manifest())
        wc = [e for e in result if isinstance(e, cls)]
        assert len(wc) == 1, (
            f"a wheel_cells manifest must select exactly ONE WheelCellsExtractor; "
            f"got {[type(e).__name__ for e in result]}"
        )

    def test_manifest_without_wheel_cells_does_not_select_extractor(self):
        """A manifest with NO wheel_cells block must NOT select the extractor
        (the unique-key gating — no cross-fire onto other machines)."""
        from fresh_slotlab.analyzer.st_extract import (
            discover_extractors, get_extractors_for_manifest,
        )
        discover_extractors()
        cls = _wheel_cells_cls()
        result = get_extractors_for_manifest(_manifest(include_block=False))
        wc = [e for e in result if isinstance(e, cls)]
        assert wc == [], (
            "a manifest without a wheel_cells block must NOT select the "
            f"WheelCellsExtractor; got {[type(e).__name__ for e in result]}"
        )

    def test_extractor_id_is_unique_in_registry(self):
        """wheel_cells shares DECLARED_IN_KEY with nothing else; assert its id is
        unique after discovery (Phase-3 extractor-count regression guard)."""
        from fresh_slotlab.analyzer.st_extract import discover_extractors, ALL_EXTRACTORS
        discover_extractors()
        ids = [e.EXTRACTOR_ID for e in ALL_EXTRACTORS]
        assert ids.count("wheel_cells") == 1, (
            f"wheel_cells must be registered exactly once; got ids {ids}"
        )


# ---------------------------------------------------------------------------
# 5. Jackpot derivation — value-agnostic (max of observed prizes).
# ---------------------------------------------------------------------------

class TestJackpotDerivation:
    def test_jackpot_is_max_observed_prize(self):
        """jackpot.prize_multiplier == max(observed distinct prizes); jackpot.cells
        == the cell(s) paying it. VALUE-AGNOSTIC: derived from data, NOT a literal."""
        cls = _wheel_cells_cls()
        ext = cls.clone_for_manifest(_manifest(cell_count=4))
        rounds = [
            _round(1, win=5000),    # 5x
            _round(2, win=50000),   # 50x  <- the max
            _round(3, win=20000),   # 20x
        ]
        out = _run(ext, rounds)["2"]
        observed_prizes = out["distinct_prizes"]
        assert out["jackpot"]["prize_multiplier"] == max(observed_prizes), (
            "jackpot multiplier must equal max(observed prizes), data-derived"
        )
        assert out["jackpot"]["cells"] == [2], (
            "jackpot cells must be the cell(s) paying the max prize"
        )

    def test_jackpot_ties_collect_all_max_cells(self):
        """Two cells share the max prize -> jackpot.cells lists BOTH (M279's
        cells 8 & 10 = 100x archetype), data-derived, value-agnostic."""
        cls = _wheel_cells_cls()
        ext = cls.clone_for_manifest(_manifest(cell_count=4))
        rounds = [
            _round(1, win=100000),  # 100x
            _round(3, win=100000),  # 100x (tie)
            _round(2, win=20000),   # 20x
        ]
        out = _run(ext, rounds)["2"]
        assert out["jackpot"]["prize_multiplier"] == max(out["distinct_prizes"])
        assert sorted(out["jackpot"]["cells"]) == [1, 3], (
            "both cells paying the max prize must be jackpot cells"
        )


# ---------------------------------------------------------------------------
# Carve isolation — the extractor is base-EXCLUDED (editing it never flips
# the fleet base_hash). The structural guarantee behind onboarding isolation.
# ---------------------------------------------------------------------------

class TestCarveIsolation:
    _WHEEL_CELLS_REL = "fresh_slotlab/analyzer/st_extract/wheel_cells.py"

    def test_wheel_cells_not_in_base_closure(self):
        from fresh_slotlab.analyzer.versioning import _CLOSURE_FILES
        assert self._WHEEL_CELLS_REL not in _CLOSURE_FILES, (
            f"{self._WHEEL_CELLS_REL} must NOT be in _CLOSURE_FILES — it is an "
            "intentional carve so editing it only re-flags wheel machines."
        )

    def test_editing_wheel_cells_does_not_flip_base_hash(self):
        """Simulate an edit (append bytes) inside the hash computation: because
        wheel_cells.py is base-excluded, base_hash is unchanged.

        INJECT-BUG: add wheel_cells.py to _CLOSURE_FILES -> this goes RED."""
        import hashlib
        from fresh_slotlab.analyzer.versioning import (
            _CLOSURE_FILES, _REPO_ROOT, compute_base_analyzer_version,
        )
        baseline = compute_base_analyzer_version()
        h = hashlib.sha256()
        for rel in sorted(_CLOSURE_FILES):
            raw = (_REPO_ROOT / rel).read_bytes().replace(b"\r\n", b"\n")
            if rel == self._WHEEL_CELLS_REL:
                raw = raw + b"\n# simulate editing the wheel_cells extractor\n"
            h.update(raw)
        after = h.hexdigest()[:12]
        assert after == baseline, (
            "editing wheel_cells.py changed base_hash — the extractor leaked into "
            "the closure (carve regression)."
        )


# ---------------------------------------------------------------------------
# INJECT-BUG PROOF — break the determinism alarm in a COPY of the module and
# assert the alarm stops firing (RED), proving the live alarm is load-bearing.
# ---------------------------------------------------------------------------

class TestInjectBugProof:
    def _load_module_from_source(self, source: str, name: str):
        """Import a patched copy of wheel_cells.py under a throwaway module name
        so the live module is untouched (auto-revert by not mutating the real one).
        """
        import sys
        import types
        spec = importlib.util.spec_from_loader(name, loader=None)
        mod = types.ModuleType(name)
        mod.__file__ = str(_WHEEL_CELLS_SRC)
        # The module self-registers on import (register_extractor at the bottom);
        # patch that line out so the throwaway copy does not pollute the registry.
        patched = source.replace(
            "register_extractor(WheelCellsExtractor({}))",
            "# register suppressed in test copy",
        )
        sys.modules[name] = mod
        try:
            exec(compile(patched, str(_WHEEL_CELLS_SRC), "exec"), mod.__dict__)
        finally:
            sys.modules.pop(name, None)
        return mod

    def test_inject_silent_pick_breaks_determinism_alarm(self):
        """INJECT (determinism): replace the alarm branch with a silent-pick of
        the first prize. Assert that on a nondeterministic cell the patched copy
        produces NO alarm + a non-null prize (RED), while the LIVE module fires
        the alarm + nulls the prize (GREEN). The contrast proves the test is not
        vacuous and the alarm is load-bearing.
        """
        source = _WHEEL_CELLS_SRC.read_text(encoding="utf-8")

        # The exact live alarm block (must match the source verbatim).
        live_block = (
            "                if len(prizes) == 1:\n"
            "                    prize_multiplier = self._coerce_mult(next(iter(prizes)))\n"
            "                    distinct_prizes.add(prize_multiplier)\n"
            "                else:\n"
            "                    # DATA ALARM: a deterministic cell paid >1 distinct prize.\n"
            "                    # Do NOT silently pick one — emit null and record the alarm.\n"
            "                    prize_multiplier = None\n"
            "                    nondeterministic[str(cell)] = sorted(\n"
            "                        self._coerce_mult(p) for p in prizes\n"
            "                    )"
        )
        assert live_block in source, (
            "the determinism-alarm block changed shape — update the inject-bug "
            "recipe in test_wheel_cells_extractor.py to match the new source."
        )
        # BUG: silently pick the first prize for ALL cardinalities, drop the alarm.
        bug_block = (
            "                prize_multiplier = self._coerce_mult(next(iter(prizes)))\n"
            "                distinct_prizes.add(prize_multiplier)"
        )
        buggy_source = source.replace(live_block, bug_block)
        assert buggy_source != source, "inject-bug substitution did not apply"

        buggy_mod = self._load_module_from_source(
            buggy_source, "_wheel_cells_buggy_copy"
        )
        BuggyCls = buggy_mod.WheelCellsExtractor
        ext = BuggyCls.clone_for_manifest(_manifest(cell_count=4))
        rounds = [_round(3, win=20000), _round(3, win=30000)]
        out = _run(ext, rounds)["2"]

        # RED on the buggy copy: alarm gone, prize silently picked.
        assert out["nondeterministic_cells"] == {}, (
            "inject-bug: the silent-pick variant must NOT fire the determinism "
            f"alarm (proving the live alarm is load-bearing); got "
            f"{out['nondeterministic_cells']}"
        )
        assert out["cell_map"]["3"]["prize_multiplier"] is not None, (
            "inject-bug: the silent-pick variant resolves the prize to a value "
            "(the bug); the live module nulls it"
        )

        # GREEN on the LIVE module (un-patched): alarm fires, prize nulled.
        cls = _wheel_cells_cls()
        live_ext = cls.clone_for_manifest(_manifest(cell_count=4))
        live_out = _run(live_ext, [_round(3, win=20000), _round(3, win=30000)])["2"]
        assert "3" in live_out["nondeterministic_cells"]
        assert live_out["cell_map"]["3"]["prize_multiplier"] is None
