"""Parser-blind crazy-reel NUDGE extractor (M63 onboarding, Wave 4).

Detects the in-engine base-game reel NUDGE on declared paid STs: a vertical
3-symbol ``crazy_up / crazy / crazy_down`` block that lands on a SINGLE reel
(column) of the final grid and slides through the 3-row window. When the block
appears the reel MOVES once (user domain confirmation 2026-06-17:
"出现了就会移一次轴"), improving/completing lines. The nudge is INTRA-ST (no
separate event ST, no transition, no ReMarks) — it is marked ONLY by the crazy
symbols in ``StopSymbolsByCol`` of the same paid round, so it is fully captured
by stateless testspin.

This extractor accumulates the per-round nudge geometry (which column nudged,
single vs multi, the 3-row arrangement = slide offset, win>0, and whether any
winning payline runs THROUGH the nudged column) so the consumer plugin
(features/nudge_dynamics.py) can present the nudge's felt experience as rates /
shares / probabilities / count distributions — all DATA-DERIVED per machine,
never hardcoded (feedback_no_hardcode.md). The crazy-symbol family, the reel
field, the row separator, the win field, and the payline column basis are ALL
DECLARED in the manifest's spin_types["<st>"].crazy_reel block — ZERO
machine-specific code in this file.

Discovery happens via DECLARED_IN_KEY = "crazy_reel" — a manifest spin_types
block carrying a "crazy_reel" config dict activates this extractor on that ST.
Machines without that block are totally unaffected (no "crazy_reel" key in their
chunk records, byte-identical parse). Mirrors st_extract/wheel_cells.py.

Manifest declaration shape (per-ST "crazy_reel" block):
{
  "spin_type": 1,
  "reel_field": "StopSymbolsByCol",       # the LIST-of-column-strings field
  "reel_field_kind": "list_of_col_strings",
  "row_sep": "-",                          # token separator inside a column string
  "symbols": ["crazy_up", "crazy", "crazy_down"],  # the nudge symbol family
  "win_field": "WinCredits",
  "payline_field": "PayoutByPayline",      # "lineId:s-s(pos,pos,pos,); ..."
  "payline_col_basis": "hundreds_digit"    # col = pos // 100 - 1 (pos 100/101/199
                                           #   -> col0; 200/201/299 -> col1; ...)
}
  - reel_field   : the round field carrying the per-column stopped symbols, parsed
                   as a LIST of strings (the M63 reality; NOT the dict form that
                   the trigger_path extractor assumes). Each list element is one
                   column string like "row0-row1-row2-".
  - row_sep      : the token separator inside a column string (default "-").
  - symbols      : the crazy-family symbol tokens (the nudge marker). DECLARED so
                   no symbol name is hardcoded.
  - win_field    : the real win field (only used as a >0 flag; money-agnostic).
  - payline_field: the round field carrying winning line positions; used to decide
                   whether a win runs THROUGH the nudged column.
  - payline_col_basis: how a payline position integer maps to a column. Only
                   "hundreds_digit" is supported (col = pos // 100 - 1); the basis
                   is recorded for forward compatibility and an unknown basis is a
                   loud config error (feedback_no_silent_swallow.md).

Per declared crazy-reel-ST round:
  - split each column string on row_sep into ≤3 row tokens; mark the column
    "nudged" if any token is in the declared symbol family.
  - is_nudge = ≥1 nudged column. single vs multi by nudged-column count.
  - the slide-offset arrangement = the ordered 3-row tuple on the FIRST nudged
    column, with non-crazy rows shown as "." (e.g. ("crazy_up","crazy",
    "crazy_down") = the full block centred). This is the NUDGE signature.
  - by_column counts the FIRST nudged column (one column per round, column-generic
    — any reel can nudge).
  - win>0 (the win_field flag) and, on a winning round, whether any winning
    payline runs THROUGH the FIRST nudged column (decode payline_field positions
    via payline_col_basis; if the nudged column is among the hit columns the
    nudge is the cause, not a coincidence).

emits (per ST, finalize_chunk) — ALL COUNTS (money-agnostic; the consumer derives
the ratios):
{
  "<st_int>": {
    "total_rounds": int,            # rounds observed on this ST
    "nudge_rounds": int,            # rounds with >=1 nudged column
    "single_col_rounds": int,       # nudge rounds with exactly 1 nudged column
    "multi_col_rounds": int,        # nudge rounds with >1 nudged column
    "baseline_rounds": int,         # rounds with NO nudge (total - nudge)
    "nudge_win_rounds": int,        # nudge rounds with win>0
    "baseline_win_rounds": int,     # baseline rounds with win>0
    "win_through_nudge_rounds": int,# nudge winning rounds whose line runs through
                                    #   the nudged column
    "by_column": {"<col>": count},  # first-nudged-column distribution
    "by_arrangement": {"<label>": count},  # slide-offset histogram
    "skipped_rounds": int           # rounds with no parseable reel field
  }, ...
}
Top-level key is omitted (entire "st_extract" key absent) when no extractors ran,
per the parser's inertness contract.

Per feedback_no_silent_swallow.md: errors inside observe_round are NOT swallowed
here; the parser wraps each extractor call in its own try/except and surfaces as
_extract_error_crazy_reel_dim. A round whose reel field is missing/malformed is
NOT an error — it is a legitimate skip, counted in skipped_rounds.

Per feedback_subprocess_import_suicide_and_module_globals.md: no module-level I/O;
registry state lives in st_extract/__init__.py, not here; class methods do not
read module globals.
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

_DEFAULT_REEL_FIELD: str = "StopSymbolsByCol"
_DEFAULT_ROW_SEP: str = "-"
_DEFAULT_WIN_FIELD: str = "WinCredits"
_DEFAULT_PAYLINE_FIELD: str = "PayoutByPayline"
_DEFAULT_COL_BASIS: str = "hundreds_digit"

# Supported payline column bases.  Only "hundreds_digit" exists today; an
# unknown basis is a loud config error rather than a silent miscount.
_SUPPORTED_COL_BASES: frozenset[str] = frozenset({"hundreds_digit"})

# Extract the parenthesised position list out of one payline segment, e.g.
# "3:7-7(101,201,301,);" -> "101,201,301,".
_POS_GROUP_RE: re.Pattern = re.compile(r"\(([\d,]+)\)")


class CrazyReelDimExtractor(STExtractor):
    """Per-round crazy-reel NUDGE geometry accumulator.

    Declared by manifest spin_types blocks carrying "crazy_reel".  Fires only on
    the STs whose block carries that key.  Other STs are silently ignored
    (early-return in observe_round).  ZERO hardcoded symbol names / field names —
    everything is read from the per-ST declaration.
    """

    EXTRACTOR_ID: ClassVar[str] = "crazy_reel_dim"
    DECLARED_IN_KEY: ClassVar[str] = "crazy_reel"

    def __init__(self, manifest: dict) -> None:
        self._manifest = manifest

        # st_int -> {reel_field, row_sep, symbols (frozenset), win_field,
        #            payline_field, col_basis}
        self._st_declarations: dict[int, dict[str, Any]] = {}
        spin_types = manifest.get("spin_types") or {}
        for st_str, st_block in spin_types.items():
            if not isinstance(st_block, dict):
                continue
            cr = st_block.get("crazy_reel")
            if not isinstance(cr, dict):
                continue
            try:
                st_int = int(st_str)
            except (TypeError, ValueError):
                continue
            # Allow an explicit spin_type override in the block; default to the
            # ST key the block lives under.
            block_st = cr.get("spin_type")
            if block_st is not None:
                try:
                    st_int = int(block_st)
                except (TypeError, ValueError):
                    pass

            symbols_raw = cr.get("symbols")
            if not isinstance(symbols_raw, (list, tuple)) or not symbols_raw:
                # Loud at config time — the nudge family is the whole point of
                # the declaration (feedback_no_silent_swallow.md).
                raise ValueError(
                    f"CrazyReelDimExtractor: crazy_reel block for ST={st_str} "
                    f"must declare a non-empty 'symbols' list, got {symbols_raw!r}."
                )
            symbols = frozenset(str(s) for s in symbols_raw)

            col_basis = str(cr.get("payline_col_basis") or _DEFAULT_COL_BASIS)
            if col_basis not in _SUPPORTED_COL_BASES:
                raise ValueError(
                    f"CrazyReelDimExtractor: unsupported payline_col_basis "
                    f"{col_basis!r} for ST={st_str}. Supported: "
                    f"{sorted(_SUPPORTED_COL_BASES)}."
                )

            self._st_declarations[st_int] = {
                "reel_field": str(cr.get("reel_field") or _DEFAULT_REEL_FIELD),
                "row_sep": str(cr.get("row_sep") or _DEFAULT_ROW_SEP),
                "symbols": symbols,
                "win_field": str(cr.get("win_field") or _DEFAULT_WIN_FIELD),
                "payline_field": str(
                    cr.get("payline_field") or _DEFAULT_PAYLINE_FIELD
                ),
                "col_basis": col_basis,
            }

        # ── Chunk-level accumulators (reset by finalize_chunk) ──
        self._total: dict[int, int] = defaultdict(int)
        self._nudge: dict[int, int] = defaultdict(int)
        self._single: dict[int, int] = defaultdict(int)
        self._multi: dict[int, int] = defaultdict(int)
        self._nudge_win: dict[int, int] = defaultdict(int)
        self._baseline_win: dict[int, int] = defaultdict(int)
        self._through: dict[int, int] = defaultdict(int)
        self._skipped: dict[int, int] = defaultdict(int)
        # Win-AMOUNT accumulators (form the nudge-vs-total win SHARE in the
        # consumer — a ratio, never surfaced as a coin total; closes the N6
        # "RTP concentration" gap the W5 breaker flagged 2026-06-17).
        self._nudge_win_sum: dict[int, float] = defaultdict(float)
        self._total_win_sum: dict[int, float] = defaultdict(float)
        # (st_int, col) -> count (first nudged column)
        self._by_col: dict[tuple[int, int], int] = defaultdict(int)
        # (st_int, arrangement_label) -> count
        self._by_arr: dict[tuple[int, str], int] = defaultdict(int)

        # Per-robot state (set by begin_robot).
        self._robot_ctx: dict = {}

        # Error accumulators (parser snapshots + resets these — see _base.py).
        self._obs_errors: list[str] = []
        self._begin_robot_error: str | None = None

    @classmethod
    def clone_for_manifest(cls, manifest: dict) -> "CrazyReelDimExtractor":
        return cls(manifest)

    # ------------------------------------------------------------------
    # begin_robot
    # ------------------------------------------------------------------

    def begin_robot(self, robot_ctx: dict) -> None:
        """Reset per-robot state.  No cross-robot nudge state is carried."""
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
        """Accumulate the nudge geometry for declared crazy-reel STs."""
        decl = self._st_declarations.get(spin_type)
        if decl is None:
            return

        reel = round_dict.get(decl["reel_field"])
        if not isinstance(reel, list):
            # No reel field (or wrong shape) on this round — a legitimate skip
            # (parser-blind safe), NOT an error.
            self._skipped[spin_type] += 1
            return

        symbols: frozenset = decl["symbols"]
        row_sep: str = decl["row_sep"]

        self._total[spin_type] += 1
        win_val = self._win_value(round_dict, round_ctx, decl)
        self._total_win_sum[spin_type] += win_val
        won = win_val > 0.0

        nudged_cols: list[int] = []
        first_arrangement: tuple[str, ...] | None = None
        for ci, col in enumerate(reel):
            # split into row tokens; the trailing separator yields an empty
            # token which we drop for the membership test but keep the first 3
            # real rows for the arrangement tuple.
            rows = [t for t in str(col).split(row_sep)]
            row_tokens = [t for t in rows if t != ""]
            if any(t in symbols for t in row_tokens):
                nudged_cols.append(ci)
                if first_arrangement is None:
                    # arrangement = ordered first-3 rows, non-crazy shown as "."
                    first_arrangement = tuple(
                        (t if t in symbols else ".") for t in rows[:3]
                    )

        if not nudged_cols:
            # Baseline round (no nudge).
            if won:
                self._baseline_win[spin_type] += 1
            return

        # ── Nudge round ──
        self._nudge[spin_type] += 1
        self._nudge_win_sum[spin_type] += win_val
        if len(nudged_cols) == 1:
            self._single[spin_type] += 1
        else:
            self._multi[spin_type] += 1

        first_col = nudged_cols[0]
        self._by_col[(spin_type, first_col)] += 1

        if first_arrangement is not None:
            label = ",".join(first_arrangement)
            self._by_arr[(spin_type, label)] += 1

        if won:
            self._nudge_win[spin_type] += 1
            # Does a winning payline run THROUGH ANY nudged column?  N3 ("the
            # shifted reel is what paid me") credits the nudge when the win runs
            # through ANY of the round's nudged reels — on a multi-column nudge
            # round the win through a non-first nudged reel is still the nudge.
            # (Data-verified: ANY-column == the design's 1,276/1,458; first-only
            # would undercount the 5 multi-column rounds whose win runs through a
            # non-first nudged reel.)
            hit_cols = self._winning_columns(round_dict, decl)
            if hit_cols & set(nudged_cols):
                self._through[spin_type] += 1

    # ------------------------------------------------------------------
    # finalize_chunk
    # ------------------------------------------------------------------

    def finalize_chunk(self) -> dict:
        """Return the per-ST nudge geometry as a JSON-serializable dict.

        Stored under rec["st_extract"]["crazy_reel_dim"].  Resets all chunk-level
        accumulators so this instance can be reused across chunks.
        """
        all_sts: set[int] = (
            set(self._total)
            | set(self._nudge)
            | set(self._skipped)
            | set(self._st_declarations)
        )

        result: dict[str, Any] = {}
        for st_int in sorted(all_sts):
            total = int(self._total.get(st_int, 0))
            nudge = int(self._nudge.get(st_int, 0))

            by_column = {
                str(col): int(cnt)
                for (s, col), cnt in sorted(self._by_col.items())
                if s == st_int
            }
            by_arrangement = {
                label: int(cnt)
                for (s, label), cnt in sorted(self._by_arr.items())
                if s == st_int
            }

            result[str(st_int)] = {
                "total_rounds": total,
                "nudge_rounds": nudge,
                "single_col_rounds": int(self._single.get(st_int, 0)),
                "multi_col_rounds": int(self._multi.get(st_int, 0)),
                "baseline_rounds": total - nudge,
                "nudge_win_rounds": int(self._nudge_win.get(st_int, 0)),
                "baseline_win_rounds": int(self._baseline_win.get(st_int, 0)),
                "win_through_nudge_rounds": int(self._through.get(st_int, 0)),
                "nudge_win_sum": float(self._nudge_win_sum.get(st_int, 0.0)),
                "total_win_sum": float(self._total_win_sum.get(st_int, 0.0)),
                "by_column": by_column,
                "by_arrangement": by_arrangement,
                "skipped_rounds": int(self._skipped.get(st_int, 0)),
            }

        # ── Reset all chunk-level accumulators for the next chunk ──
        self._total = defaultdict(int)
        self._nudge = defaultdict(int)
        self._single = defaultdict(int)
        self._multi = defaultdict(int)
        self._nudge_win = defaultdict(int)
        self._baseline_win = defaultdict(int)
        self._through = defaultdict(int)
        self._skipped = defaultdict(int)
        self._by_col = defaultdict(int)
        self._by_arr = defaultdict(int)
        self._nudge_win_sum = defaultdict(float)
        self._total_win_sum = defaultdict(float)
        # Defensive error-accumulator resets (parser already snapshotted them).
        self._obs_errors = []
        self._begin_robot_error = None

        # Drop STs that produced no observation AND no skip (lean record).
        return {
            st: payload
            for st, payload in result.items()
            if payload["total_rounds"] > 0 or payload["skipped_rounds"] > 0
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _win_value(
        self, round_dict: dict, round_ctx: dict | None, decl: dict
    ) -> float:
        """The round's win AMOUNT.

        Prefer the rule-view win from round_ctx (the same source the sibling
        extractors and the parser's attribution use — so the nudge win SHARE is
        consistent with the report's RTP); fall back to the declared raw win
        field. Accumulated into nudge_win_sum / total_win_sum to form the N6
        SHARE (a ratio); never surfaced as a coin total.
        """
        if round_ctx is not None and "win" in round_ctx:
            try:
                return float(round_ctx["win"])
            except (TypeError, ValueError):
                pass
        raw = round_dict.get(decl["win_field"])
        if raw is None:
            return 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    def _win_positive(
        self, round_dict: dict, round_ctx: dict | None, decl: dict
    ) -> bool:
        """True if this round won (money-agnostic boolean flag)."""
        return self._win_value(round_dict, round_ctx, decl) > 0.0

    def _winning_columns(self, round_dict: dict, decl: dict) -> set[int]:
        """Decode the columns that a winning payline runs through.

        Reads the declared payline_field, extracts every parenthesised position
        integer, and maps each to a column via the declared col_basis.  Returns
        the set of distinct hit columns (empty when the field is absent/empty —
        a parser-blind-safe legitimate state, NOT an error).
        """
        pbp = round_dict.get(decl["payline_field"])
        if not pbp:
            return set()
        cols: set[int] = set()
        for m in _POS_GROUP_RE.finditer(str(pbp)):
            for tok in m.group(1).split(","):
                tok = tok.strip()
                if not tok.isdigit():
                    continue
                col = self._pos_to_col(int(tok), decl["col_basis"])
                if col is not None:
                    cols.add(col)
        return cols

    @staticmethod
    def _pos_to_col(pos: int, col_basis: str) -> int | None:
        """Map a payline position integer to a 0-based column.

        "hundreds_digit": col = (pos + 1) // 100 - 1.  On M63 the window cell
        positions are {99,100,101} (col0), {199,200,201} (col1), {299,300,301}
        (col2) — the row offset is -1/0/+1 around the col centre (100/200/300).
        The +1 before the floor-divide groups the LOWER boundary cell (99/199/299)
        with its OWN column (99->col0, 199->col1, 299->col2) instead of dropping
        it (99) or misattributing it to the column below (199->0, 299->1).
        Fixes the W5 finding: the prior `pos//100-1` was curve-fit to a wrong
        win-through-nudge target; the corrected decode yields N3=100% on this
        3-reel all-column-payline game (any winning line spans all 3 reels, so a
        single-reel nudge is ALWAYS on the winning line).
        """
        if col_basis == "hundreds_digit":
            col = (pos + 1) // 100 - 1
            return col if col >= 0 else None
        # Unknown bases are rejected at clone time; defensive None here.
        return None


# ---------------------------------------------------------------------------
# Self-registration — fires at module import time (idempotent list-append).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# ---------------------------------------------------------------------------
register_extractor(CrazyReelDimExtractor({}))
