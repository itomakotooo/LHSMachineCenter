"""Parser-blind wheel cell-index extractor.

Accumulates the per-round wheel landing cell (from ReMarks
"WheelSpin CellIndex <n>; WheelId <w>;") and the prize multiplier each cell
pays (WinCredits / bet) for declared wheel STs, so the consumer plugin
(features/wheel_dynamics.py) can present the EXACT 12-cell wheel face,
the cell->prize identity, the jackpot cell(s), and the un-merged distinct
prize distribution — all DATA-DERIVED per machine, never hardcoded
(feedback_no_hardcode.md).

ZERO machine-specific code in this file.  Discovery happens via
DECLARED_IN_KEY = "wheel_cells" — a manifest spin_types block carrying a
"wheel_cells" config dict activates this extractor on that ST.  Machines
without that block are totally unaffected (no "wheel_cells" key in their
chunk records, byte-identical parse).

Manifest declaration shape (per-ST "wheel_cells" block):
{
  "spin_type": 2,
  "remarks_field": "ReMarks",
  "cell_pattern": "CellIndex\\s+(\\d+)",
  "cell_count": 12,
  "prize_basis": "win_over_bet"
}
  - remarks_field : the round field carrying the "WheelSpin CellIndex <n>;"
                    string (default "ReMarks").
  - cell_pattern  : a regex with ONE capture group = the cell index integer
                    (default r"CellIndex\\s+(\\d+)").
  - cell_count    : the declared number of physical cells (so an unobserved
                    TOP cell is detectable; falls back to max observed if absent).
  - prize_basis   : "win_over_bet" — prize multiplier = WinCredits / bet (the
                    only basis supported; recorded for forward compatibility).

Per declared-wheel-ST round:
  - regex the cell index out of the remarks field; skip + count _skipped when
    the field is missing or carries no CellIndex (parser-blind-safe: only read
    fields the round carries; never crash on a malformed ReMarks).
  - prize_mult = round_ctx["win"] / bet when round_ctx exposes the rule-view
    win (same source the sibling extractors prefer — keeps the extractor
    consistent with parser attribution; on the wheel STs raw WinCredits ==
    rule-view win so the value is identical), else raw WinCredits / bet.
  - accumulate per cell: hit_count, win_sum, and the SET of distinct
    prize_mults seen.

DETERMINISM CHECK (feedback_invariant_with_fallback_hides_drift.md): each cell
is deterministic = exactly one prize.  A cell observed paying >1 distinct
prize_mult is a DATA ALARM — it is recorded in `nondeterministic_cells`
(cell -> sorted distinct mults), and that cell's `prize_multiplier` is emitted
as null (NOT a silently-picked one).  We never crash and never fabricate.

finalize_chunk output shape (stored under rec["st_extract"]["wheel_cells"]):
{
  "<st_int>": {
    "cell_map": {
      "<cell>": {
        "prize_multiplier": <float|null>,   # the singleton; null if unobserved
                                            #   or nondeterministic
        "hit_count": int,
        "hit_prob": <float|null>            # hit_count / total_wheel_spins
      }, ...
    },
    "observed_cells": [<cell>, ...],        # sorted ints
    "cell_count": int,                      # declared (or max observed)
    "unobserved_cells": [<cell>, ...],      # 1..cell_count minus observed
    "distinct_prizes": [<mult>, ...],       # sorted distinct singleton prizes
    "jackpot": {"prize_multiplier": <max>, "cells": [<cell>, ...]},
    "total_wheel_spins": int,
    "nondeterministic_cells": {"<cell>": [<mult>, ...], ...},  # data alarm
    "skipped_rounds": int                   # rounds with no parseable CellIndex
  }, ...
}
Top-level key is omitted (entire "st_extract" key absent) when no extractors
ran, per the parser's inertness contract.

Per feedback_no_silent_swallow.md: errors inside observe_round are NOT
swallowed here; the parser wraps each extractor call in its own try/except and
surfaces as _extract_error_wheel_cells.  A round with no parseable CellIndex
is NOT an error — it is a legitimate skip, counted in skipped_rounds.

Per feedback_subprocess_import_suicide_and_module_globals.md: no module-level
I/O; registry state lives in st_extract/__init__.py, not here; class methods
do not read module globals.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, ClassVar

try:
    from fresh_slotlab.analyzer.st_extract._base import STExtractor
    from fresh_slotlab.analyzer.st_extract import register_extractor
except ImportError:
    from analyzer.st_extract._base import STExtractor  # type: ignore[no-redef]
    from analyzer.st_extract import register_extractor  # type: ignore[no-redef]

# Default cell-index pattern when a declaration omits cell_pattern.  One capture
# group = the integer cell index.  Matches "WheelSpin CellIndex 8; WheelId 1;".
_DEFAULT_CELL_PATTERN: str = r"CellIndex\s+(\d+)"
_DEFAULT_REMARKS_FIELD: str = "ReMarks"


class WheelCellsExtractor(STExtractor):
    """Per-round wheel cell-index + cell->prize-multiplier accumulator.

    Declared by manifest spin_types blocks carrying "wheel_cells".  Fires only
    on the STs whose block carries that key.  Other STs are silently ignored
    (early-return in observe_round).

    The cell->prize correspondence is a fixed deterministic structural fact
    (each CellIndex always pays the same WinCredits on these machines); this
    extractor surfaces it from data and ALARMS (never crashes) if it ever sees
    a cell pay >1 distinct prize.
    """

    EXTRACTOR_ID: ClassVar[str] = "wheel_cells"
    DECLARED_IN_KEY: ClassVar[str] = "wheel_cells"

    def __init__(self, manifest: dict) -> None:
        self._manifest = manifest

        # Pre-parse the per-ST wheel_cells declarations once.  Compile the
        # regex per ST so a malformed pattern is caught at clone time, not in
        # the hot loop.
        # st_int -> {"remarks_field": str, "cell_re": compiled, "cell_count": int|None}
        self._st_declarations: dict[int, dict[str, Any]] = {}
        spin_types = manifest.get("spin_types") or {}
        for st_str, st_block in spin_types.items():
            if not isinstance(st_block, dict):
                continue
            wc = st_block.get("wheel_cells")
            if not isinstance(wc, dict):
                continue
            try:
                st_int = int(st_str)
            except (TypeError, ValueError):
                continue
            # Allow an explicit spin_type override in the block; default to the
            # ST key the block lives under.
            block_st = wc.get("spin_type")
            if block_st is not None:
                try:
                    st_int = int(block_st)
                except (TypeError, ValueError):
                    pass
            remarks_field = str(wc.get("remarks_field") or _DEFAULT_REMARKS_FIELD)
            pattern = str(wc.get("cell_pattern") or _DEFAULT_CELL_PATTERN)
            try:
                cell_re = re.compile(pattern)
            except re.error as exc:
                # Loud, at config time — never silently swallow a bad pattern
                # (feedback_no_silent_swallow.md).
                raise ValueError(
                    f"WheelCellsExtractor: invalid cell_pattern {pattern!r} "
                    f"for ST={st_str}: {exc}"
                ) from exc
            cell_count_raw = wc.get("cell_count")
            cell_count: int | None
            try:
                cell_count = int(cell_count_raw) if cell_count_raw is not None else None
            except (TypeError, ValueError):
                cell_count = None
            self._st_declarations[st_int] = {
                "remarks_field": remarks_field,
                "cell_re": cell_re,
                "cell_count": cell_count,
            }

        # ── Chunk-level accumulators (reset by finalize_chunk) ──
        # (st_int, cell) -> hit_count
        self._cell_hits: dict[tuple[int, int], int] = defaultdict(int)
        # (st_int, cell) -> win_sum (prize_mult sum, for diagnostics)
        self._cell_win: dict[tuple[int, int], float] = defaultdict(float)
        # (st_int, cell) -> set of distinct prize_mults seen
        self._cell_prizes: dict[tuple[int, int], set] = defaultdict(set)
        # st_int -> total wheel spins observed (with a parseable CellIndex)
        self._total_spins: dict[int, int] = defaultdict(int)
        # st_int -> rounds skipped (no parseable CellIndex)
        self._skipped: dict[int, int] = defaultdict(int)

        # Per-robot state (set by begin_robot).
        self._robot_ctx: dict = {}

        # Error accumulators (parser snapshots + resets these — see _base.py).
        self._obs_errors: list[str] = []
        self._begin_robot_error: str | None = None

    @classmethod
    def clone_for_manifest(cls, manifest: dict) -> "WheelCellsExtractor":
        return cls(manifest)

    # ------------------------------------------------------------------
    # begin_robot
    # ------------------------------------------------------------------

    def begin_robot(self, robot_ctx: dict) -> None:
        """Reset per-robot state.  No cross-robot wheel state is carried."""
        self._robot_ctx = robot_ctx

    # ------------------------------------------------------------------
    # observe_round
    # ------------------------------------------------------------------

    def observe_round(
        self,
        round_dict: dict,
        spin_type: int,
        round_ctx: dict,
    ) -> None:
        """Accumulate the cell index + prize multiplier for declared wheel STs."""
        decl = self._st_declarations.get(spin_type)
        if decl is None:
            return

        remarks_field: str = decl["remarks_field"]
        cell_re: re.Pattern = decl["cell_re"]

        remarks = round_dict.get(remarks_field)
        if remarks is None:
            # No remarks field on this round — a legitimate skip (parser-blind
            # safe), NOT an error.
            self._skipped[spin_type] += 1
            return
        m = cell_re.search(str(remarks))
        if m is None:
            # ReMarks present but carries no CellIndex — skip + count.
            self._skipped[spin_type] += 1
            return
        try:
            cell = int(m.group(1))
        except (TypeError, ValueError, IndexError):
            self._skipped[spin_type] += 1
            return

        # prize_mult = win / bet.  Prefer the rule-view win from round_ctx (same
        # source the sibling extractors prefer) so the extractor stays
        # consistent with parser attribution; fall back to raw WinCredits.
        bet = round_ctx.get("bet", 1)
        effective_bet = float(bet) if bet and bet > 0 else 1.0
        win_amt = self._get_win(round_dict, round_ctx)
        prize_mult = win_amt / effective_bet if effective_bet > 0 else 0.0

        key = (spin_type, cell)
        self._cell_hits[key] += 1
        self._cell_win[key] += prize_mult
        self._cell_prizes[key].add(prize_mult)
        self._total_spins[spin_type] += 1

    # ------------------------------------------------------------------
    # finalize_chunk
    # ------------------------------------------------------------------

    def finalize_chunk(self) -> dict:
        """Return the per-ST wheel cell map as a JSON-serializable dict.

        Stored under rec["st_extract"]["wheel_cells"].  Resets all chunk-level
        accumulators so this instance can be reused across chunks.
        """
        # Collect all STs that produced any signal (observed or skipped).
        all_sts: set[int] = (
            {st for (st, _c) in self._cell_hits}
            | set(self._total_spins)
            | set(self._skipped)
            | set(self._st_declarations)
        )

        result: dict[str, Any] = {}
        for st_int in sorted(all_sts):
            decl = self._st_declarations.get(st_int) or {}
            total = int(self._total_spins.get(st_int, 0))
            skipped = int(self._skipped.get(st_int, 0))

            # Build the per-cell map + detect nondeterministic cells.
            cell_map: dict[str, Any] = {}
            observed_cells: list[int] = []
            distinct_prizes: set = set()
            nondeterministic: dict[str, list] = {}

            cells_for_st = sorted(
                c for (s, c) in self._cell_hits if s == st_int
            )
            for cell in cells_for_st:
                key = (st_int, cell)
                hits = int(self._cell_hits.get(key, 0))
                prizes = self._cell_prizes.get(key) or set()
                observed_cells.append(cell)

                prize_multiplier: Any
                if len(prizes) == 1:
                    prize_multiplier = self._coerce_mult(next(iter(prizes)))
                    distinct_prizes.add(prize_multiplier)
                else:
                    # DATA ALARM: a deterministic cell paid >1 distinct prize.
                    # Do NOT silently pick one — emit null and record the alarm.
                    prize_multiplier = None
                    nondeterministic[str(cell)] = sorted(
                        self._coerce_mult(p) for p in prizes
                    )

                cell_map[str(cell)] = {
                    "prize_multiplier": prize_multiplier,
                    "hit_count": hits,
                    "hit_prob": (hits / total) if total > 0 else None,
                }

            # cell_count: declared (or fall back to max observed).
            declared_count = decl.get("cell_count")
            if declared_count is not None:
                cell_count = int(declared_count)
            elif observed_cells:
                cell_count = max(observed_cells)
            else:
                cell_count = 0

            # unobserved_cells: declared range 1..cell_count minus observed.
            observed_set = set(observed_cells)
            unobserved_cells = [
                c for c in range(1, cell_count + 1) if c not in observed_set
            ]
            # Add cell_map entries for unobserved cells (honest: null prize).
            for c in unobserved_cells:
                cell_map[str(c)] = {
                    "prize_multiplier": None,
                    "hit_count": 0,
                    "hit_prob": (0.0 if total > 0 else None),
                }

            # jackpot: max distinct prize + the cell(s) that pay it.
            if distinct_prizes:
                jackpot_mult = max(distinct_prizes)
                jackpot_cells = sorted(
                    cell for (s, cell) in self._cell_hits
                    if s == st_int
                    and len(self._cell_prizes.get((s, cell)) or set()) == 1
                    and self._coerce_mult(
                        next(iter(self._cell_prizes[(s, cell)]))
                    ) == jackpot_mult
                )
                jackpot = {
                    "prize_multiplier": jackpot_mult,
                    "cells": jackpot_cells,
                }
            else:
                jackpot = {"prize_multiplier": None, "cells": []}

            result[str(st_int)] = {
                "cell_map": cell_map,
                "observed_cells": observed_cells,
                "cell_count": cell_count,
                "unobserved_cells": unobserved_cells,
                "distinct_prizes": sorted(distinct_prizes),
                "jackpot": jackpot,
                "total_wheel_spins": total,
                "nondeterministic_cells": nondeterministic,
                "skipped_rounds": skipped,
            }

        # ── Reset all chunk-level accumulators for the next chunk ──
        self._cell_hits = defaultdict(int)
        self._cell_win = defaultdict(float)
        self._cell_prizes = defaultdict(set)
        self._total_spins = defaultdict(int)
        self._skipped = defaultdict(int)
        # Defensive error-accumulator resets (parser already snapshotted them —
        # see _base.py snapshot/reset contract).
        self._obs_errors = []
        self._begin_robot_error = None

        # Omit STs that produced no observation AND no skip AND no declaration
        # signal is impossible here (we seeded from declarations) — but drop an
        # ST whose entire map is empty to keep the record lean.
        return {
            st: payload
            for st, payload in result.items()
            if payload["total_wheel_spins"] > 0
            or payload["skipped_rounds"] > 0
            or payload["cell_map"]
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_mult(v: float) -> float | int:
        """Normalise a prize multiplier: integer-valued floats become ints so
        the emitted dict keys/values are stable (50.0 -> 50)."""
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return v
        if fv == int(fv):
            return int(fv)
        return fv

    def _get_win(self, round_dict: dict, round_ctx: dict | None = None) -> float:
        """Extract win amount, preferring the rule-view win from round_ctx.

        Mirrors the sibling extractors (trigger_path / freespin_progression):
        the parser already ran extract_round_win with the full rule set and
        passes the result via round_ctx["win"].  On the wheel STs raw
        WinCredits == rule-view win, so the value is identical either way.
        """
        if round_ctx is not None and "win" in round_ctx:
            v = round_ctx["win"]
            try:
                fv = float(v)
                return fv if fv > 0.0 else 0.0
            except (TypeError, ValueError):
                pass
        raw = round_dict.get("WinCredits")
        if raw is None:
            raw = round_dict.get("WinAmount")
        if raw is None:
            return 0.0
        try:
            v = float(raw)
            return v if v > 0.0 else 0.0
        except (TypeError, ValueError):
            return 0.0


# ---------------------------------------------------------------------------
# Self-registration — fires at module import time (idempotent list-append).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# ---------------------------------------------------------------------------
register_extractor(WheelCellsExtractor({}))
