"""AnalyzerFeature: multiplier_wild — Pattern B from start.

Phase C3.5 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/07_decision.md §7 (C3.5 row)
and session_artifacts/_impl/phase_c3_5/brief.md §2.

Closes gap #4 from 00_brief.md §3: multiplier-wild symbols (wild2x / wild5x
/ wild10x / wild_Nx) are present in some machines' reel windows and multiply
the base line win by N when the payline passes through that cell.  This plugin
surfaces per-variant hit counts broken down by column and SpinType.

Mechanism
---------
Symbol-level embedded multiplier: a symbol named ``wildNx`` (matching regex
``^wild(\\d+)x$``) contributes multiplier_value=N to any payline passing
through the cell it occupies.  This is NOT a free-game cumulative multiplier
(ReMarks across M275 freespin rounds carry only "Freespin N;" plain counters,
no multiplier annotation).  Evidence: raw probe session 2026-05-27 —
wild2x/wild5x/wild10x appear only in col 1 (middle reel) for M275 in both
paid (ST=140) and free (ST=126) spin types.

Data sources
------------
Reads from chunk_dict (existing parser output — NO parser change required):
  symbol_counts_by_col         — {str(col): {symbol: count}} overall
  symbol_counts_by_col_by_spin_type — {str(ST): {str(col): {symbol: count}}}

Both keys have been produced by parser.py since 2026-05-14.  Old chunks
without these keys produce empty accumulators (applicable=false).

Output schema v1
----------------
summary["player_impact"]["multiplier_wild"]:
  applicable              — bool; True iff any wild_Nx observed in data
  variants                — list of per-symbol records (sorted by multiplier_value)
    symbol                — str, e.g. "wild2x"
    multiplier_value      — int, e.g. 2
    total_hits            — int
    by_column             — [{col, hits, hit_rate}]  (hit_rate = hits / total_spins)
    by_spin_type          — [{spin_type, behavior, hits}]
  total_multiplier_wild_hits  — int; sum across all variants
  estimated_rtp_contribution_pp — null (deferred to v2)
  estimated_rtp_method    — "deferred_v2"

Per-machine isolation property
-------------------------------
This plugin file is NOT in fresh_slotlab/analyzer/core/ so its addition does
NOT change compute_base_analyzer_version().  Only machines that declare
"multiplier_wild" in their manifest's analyzer_features list will include this
plugin's hash in their effective_analyzer_version.  As of C3.5, only M275.json
declares it.

Memory feedback honored
-----------------------
- feedback_subprocess_import_suicide_and_module_globals.md:
    register() is a pure list-append — no I/O at import time.
- feedback_no_silent_swallow.md:
    extract() errors surface via the existing C2 PIA merge-loop mechanism;
    the per-chunk error dict is returned (not swallowed).
- feedback_invariant_with_fallback_hides_drift.md:
    applicable=False is an explicit signal when no wildNx symbols are
    observed — NOT a catch-all bucket.  The caller can distinguish
    "declared but absent in data" from "not declared".
- feedback_prefer_complex_better.md:
    Generic regex ``^wild(\\d+)x$`` — not hardcoded to 2/5/10 only.
    Any future wildNx symbol is picked up automatically.
- feedback_no_hardcode.md:
    No machine-specific semantics hardcoded — col index, ST values, and
    symbol names are all inferred from the actual data.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar

try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    from fresh_slotlab.analyzer.feature_registry import register
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    from analyzer.feature_registry import register  # type: ignore[no-redef]

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
    except ImportError:
        from analyzer.pipeline_context import PipelineContext  # type: ignore[assignment]

# Regex that matches wildNx symbol names and captures N.
_WILD_NX_RE = re.compile(r"^wild(\d+)x$")

# Behavior label for known SpinType integers.  Machines may use different
# ST integers — we use a generic fallback ("other") for unknown ones.
# M275: ST=1 paid (base spin), ST=140 paid (outer paid), ST=126 free.
# The label is informational only; behavior-critical logic uses ST ints.
_ST_BEHAVIOR: dict[int, str] = {
    1: "paid",
    140: "paid",
    126: "free",
}


class MultiplierWild(AnalyzerFeature):
    """Pattern B plugin: per-chunk extraction of wild_Nx symbol presence.

    Accumulator structure
    ---------------------
    by_col : dict[symbol_str, dict[col_str, int]]
        For each wildNx symbol, for each column (as str key from parser),
        the total number of occurrences across all processed chunks.

    by_st : dict[symbol_str, dict[st_str, int]]
        For each wildNx symbol, for each SpinType (str key from
        symbol_counts_by_col_by_spin_type), the total occurrences.

    Both dicts are empty when no wildNx symbol is observed in the data.
    """

    FEATURE_ID: ClassVar[str] = "multiplier_wild"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("multiplier_wild",)
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = True  # v2 will compute numeric contribution
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    REQUIRES: ClassVar[tuple[str, ...]] = ()
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Read per-chunk wildNx symbol counts from symbol_counts_by_col
        and symbol_counts_by_col_by_spin_type.

        Reads from chunk_dict:
          symbol_counts_by_col
              {str(col): {symbol: count}} — overall (all STs combined).
          symbol_counts_by_col_by_spin_type
              {str(ST): {str(col): {symbol: count}}} — per-ST breakdown.

        Returns accumulator dict with 2 keys:
          by_col  — {symbol_str: {col_str: int}}
          by_st   — {symbol_str: {st_str: int}}

        Handles:
          - None or non-dict chunk_dict: returns empty acc
          - Missing keys: treated as empty dicts (old cached chunks)
          - Symbols not matching ^wild(\\d+)x$: ignored
        """
        if not chunk_dict or not isinstance(chunk_dict, dict):
            return {"by_col": {}, "by_st": {}}

        # --- by_col: from symbol_counts_by_col ---
        by_col: dict[str, dict[str, int]] = {}
        raw_by_col = chunk_dict.get("symbol_counts_by_col") or {}
        for col_str, sym_map in raw_by_col.items():
            if not isinstance(sym_map, dict):
                continue
            for sym, count in sym_map.items():
                if _WILD_NX_RE.match(str(sym)):
                    sym_str = str(sym)
                    col_entry = by_col.setdefault(sym_str, {})
                    col_entry[str(col_str)] = col_entry.get(str(col_str), 0) + int(count or 0)

        # --- by_st: from symbol_counts_by_col_by_spin_type ---
        # Aggregate across all columns to get per-ST total hits per symbol.
        by_st: dict[str, dict[str, int]] = {}
        raw_by_st = chunk_dict.get("symbol_counts_by_col_by_spin_type") or {}
        for st_str, col_map in raw_by_st.items():
            if not isinstance(col_map, dict):
                continue
            for _col_str, sym_map in col_map.items():
                if not isinstance(sym_map, dict):
                    continue
                for sym, count in sym_map.items():
                    if _WILD_NX_RE.match(str(sym)):
                        sym_str = str(sym)
                        st_entry = by_st.setdefault(sym_str, {})
                        st_entry[str(st_str)] = st_entry.get(str(st_str), 0) + int(count or 0)

        return {"by_col": by_col, "by_st": by_st}

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Merge two extract() outputs additively across chunks.

        by_col and by_st are both merged additively: for each
        (symbol, key) pair, sum the counts from both accumulators.
        Handles empty dicts (first chunk, empty chunk).
        """
        if not prev_acc:
            return this_acc if this_acc else {"by_col": {}, "by_st": {}}
        if not this_acc:
            return prev_acc

        def _merge(prev: dict, this: dict) -> dict:
            """Merge two nested dicts of {outer_key: {inner_key: int}} additively."""
            merged: dict[str, dict[str, int]] = {}
            # Start with prev
            for outer, inner in prev.items():
                merged[outer] = dict(inner)
            # Merge this
            for outer, inner in this.items():
                if outer not in merged:
                    merged[outer] = dict(inner)
                else:
                    dest = merged[outer]
                    for k, v in inner.items():
                        dest[k] = dest.get(k, 0) + v
            return merged

        return {
            "by_col": _merge(
                (prev_acc or {}).get("by_col") or {},
                (this_acc or {}).get("by_col") or {},
            ),
            "by_st": _merge(
                (prev_acc or {}).get("by_st") or {},
                (this_acc or {}).get("by_st") or {},
            ),
        }

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Build and write summary["player_impact"]["multiplier_wild"].

        Reads:
          ctx.total_spins — denominator for hit_rate per column
          final_acc       — accumulated by_col + by_st from extract/reduce

        Writes:
          summary["player_impact"]["multiplier_wild"]:
            applicable, variants, total_multiplier_wild_hits,
            estimated_rtp_contribution_pp, estimated_rtp_method

        Behavior label for each ST is inferred from a generic mapping
        (_ST_BEHAVIOR): known STs map to "paid"/"free"; unknown STs
        map to "other".  This is informational only.

        Per feedback_invariant_with_fallback_hides_drift.md:
          applicable=False is an explicit "no data" signal — NOT a
          catch-all bucket.  Machines that don't declare this feature
          won't have the key at all; machines that declare it but have
          no wildNx symbols in their cached data emit applicable=False.
        """
        total_spins = ctx.total_spins
        player_impact = summary.setdefault("player_impact", {})

        acc = final_acc or {}
        by_col: dict[str, dict[str, int]] = acc.get("by_col") or {}
        by_st: dict[str, dict[str, int]] = acc.get("by_st") or {}

        # Collect all wildNx symbols observed.
        all_syms: set[str] = set(by_col.keys()) | set(by_st.keys())

        if not all_syms:
            # No multiplier wilds observed — explicit signal, not silent bucket.
            player_impact["multiplier_wild"] = {
                "applicable": False,
                "variants": [],
                "total_multiplier_wild_hits": 0,
                "estimated_rtp_contribution_pp": None,
                "estimated_rtp_method": "deferred_v2",
            }
            return

        variants: list[dict[str, Any]] = []
        for sym in sorted(all_syms):
            m = _WILD_NX_RE.match(sym)
            mult_val = int(m.group(1)) if m else 0

            # by_column breakdown
            col_data = by_col.get(sym) or {}
            # Sort by col index numerically; col keys are str(int).
            by_column: list[dict[str, Any]] = []
            for col_str in sorted(col_data.keys(), key=lambda c: int(c)):
                hits = int(col_data[col_str])
                hit_rate = (hits / total_spins) if total_spins > 0 else 0.0
                by_column.append({
                    "col": int(col_str),
                    "hits": hits,
                    "hit_rate": round(hit_rate, 6),
                })

            # by_spin_type breakdown
            st_data = by_st.get(sym) or {}
            by_spin_type: list[dict[str, Any]] = []
            for st_str in sorted(st_data.keys(), key=lambda s: int(s)):
                st_int = int(st_str)
                st_hits = int(st_data[st_str])
                behavior = _ST_BEHAVIOR.get(st_int, "other")
                by_spin_type.append({
                    "spin_type": st_int,
                    "behavior": behavior,
                    "hits": st_hits,
                })

            # total_hits: sum across all columns (by_col is the ground truth)
            total_hits = sum(col_data.values())

            variants.append({
                "symbol": sym,
                "multiplier_value": mult_val,
                "total_hits": total_hits,
                "by_column": by_column,
                "by_spin_type": by_spin_type,
            })

        # Sort variants by multiplier_value ascending (wild2x first).
        variants.sort(key=lambda v: v["multiplier_value"])

        total_multiplier_wild_hits = sum(v["total_hits"] for v in variants)

        player_impact["multiplier_wild"] = {
            "applicable": True,
            "variants": variants,
            "total_multiplier_wild_hits": total_multiplier_wild_hits,
            "estimated_rtp_contribution_pp": None,  # v2: requires line-win correlation
            "estimated_rtp_method": "deferred_v2",
        }


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# ---------------------------------------------------------------------------
register(MultiplierWild())
