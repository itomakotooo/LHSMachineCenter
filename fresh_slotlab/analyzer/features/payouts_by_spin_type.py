"""AnalyzerFeature: payouts_by_spin_type — Pattern B (real extraction).

Phase C2 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §7.2.
Phase C3 adds shape / covered_columns / paylines / notes enrichment per row,
and bumps SCHEMA_VERSION 1 → 2.
Phase C4 (payid symbol enrichment) adds symbol_combo per row (dominant combo
from StopSymbolsByCol decode, cross-machine) and bumps SCHEMA_VERSION 2 → 3.

Pattern B: extract() reads per-chunk payout_id_by_spin_type +
payout_id_win_by_spin_type + C3/C4 enrichment fields; reduce() merges across
chunks; emit() writes summary["player_impact"]["payouts_by_spin_type"].

SCHEMA_VERSION = 3 (bumped in C4; v1/v2 summaries are handled by
REGISTERED_FALLBACK_RULES — frontend renders missing fields as None for
old reports already on disk).

DECLARED_DEPS = () — emit() reads summary["player_impact"]["spin_type_breakdown"]
  directly (written by F1 inline before the plugin emit loop starts, per
  04_v3 §4.2 Phase B ordering contract). No _-prefix temp key needed.

Per memory/feedback_subprocess_import_suicide_and_module_globals.md:
  register() is a pure list-append — no I/O at import time.
Per memory/feedback_no_silent_swallow.md:
  extract() errors are captured by the PIA merge loop, not silently swallowed.
Per memory/feedback_invariant_with_fallback_hides_drift.md:
  notes.is_trigger_marker is an explicit positive signal (line_id==-1 AND
  total_win==0 for ALL hits of that pid) — NOT a catch-all fallback bucket.
"""
from __future__ import annotations

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


class PayoutsBySpinType(AnalyzerFeature):
    """Pattern B plugin: per-chunk extraction of (pid, ST) hit/win data.

    Accumulator structure (C2 fields, unchanged)
    --------------------------------------------
    by_st_hits: dict[pid_str, dict[st_int, int]]
        For each payout_id, for each SpinType int, the number of hits
        in that (pid, ST) pair across all processed chunks.
    by_st_win: dict[pid_str, dict[st_int, float]]
        For each payout_id, for each SpinType int, the total credits won
        in that (pid, ST) pair across all processed chunks.

    C3 enrichment accumulators (merged across chunks)
    --------------------------------------------------
    pid_payline_hits: dict[pid_str, dict[payline_id_str, int]]
        Per-pid per-payline hit counts (all STs combined).
        Payline key "-1" means scatter-trigger line (line_id == -1).
    pid_match_count_dist: dict[pid_str, dict[match_count_int, int]]
        Per-pid n-of-a-kind distribution (only for line_id != -1 records).
    pid_col_set: dict[pid_str, list[int]]
        Per-pid sorted list of column indices covered (from positions).
    pid_has_regular_line: dict[pid_str, bool]
        True if ANY record for this pid had line_id != -1.
        False (absent from dict) means all records are trigger-marker lines.
    pid_symbol_combos: dict[pid_str, dict[combo_str, int]]
        Per-pid symbol combination histogram. combo_str = "|"-joined
        column-ordered symbol names (e.g. "cherry|cherry|35x_wild").
        Only populated when StopSymbolsByCol is available and positions
        decode cleanly. Empty positions (scatter/feature pay) → no entry.

    The key types are:
    - pid_str: str (payout id as string, e.g. "6", "666", "27502")
    - st_int: int (SpinType integer, e.g. 1, 126, 140)
    - payline_id_str: str (payline id as string, e.g. "1", "2", "-1")
    - match_count_int: int (n-of-a-kind count, e.g. 3 for 3-of-a-kind)

    emit() reads summary["player_impact"]["spin_type_breakdown"] to derive
    per-ST labels and spins counts. This key is guaranteed present by the
    Phase B ordering contract (F1 inline writes it before the emit loop).
    """

    FEATURE_ID: ClassVar[str] = "payouts_by_spin_type"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("payouts_by_spin_type",)
    SCHEMA_VERSION: ClassVar[int] = 3  # C4: bumped from 2; adds symbol_combo per-row field
    RTP_CONTRIBUTION: ClassVar[bool] = False  # display only
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()

    # C3: fallback rules for v1 summaries already on disk.
    # C4: v2→v3 fallback for symbol_combo field absent in v2 summaries.
    # Frontend renderer: if row is missing these keys, render as None / hide.
    # Per memory/feedback_md5_is_a_tag_not_a_destruction_signal.md:
    # schema bump invalidates downstream renderers gracefully, does NOT delete.
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {
        1: {
            # v1 → v2: these 4 fields are absent in v1 summaries.
            "shape": None,
            "covered_columns": None,
            "paylines": None,
            "notes": None,
        },
        2: {
            # v2 → v3: symbol_combo field absent in v2 summaries.
            "symbol_combo": None,
        },
    }

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Read per-chunk (pid, ST) hit/win data plus C3 enrichment fields.

        Reads from chunk_dict:
          payout_id_by_spin_type   — dict[pid, dict[st_str, int]]
          payout_id_win_by_spin_type — dict[pid, dict[st_str, float]]
          payout_id_payline_hits   — dict[pid, dict[payline_id_str, int]]  (C3)
          payout_id_match_count_dist — dict[pid, dict[mc_int, int]]         (C3)
          payout_id_col_set        — dict[pid, list[int]]                   (C3)
          payout_id_has_regular_line — dict[pid, bool]                      (C3)
          payout_id_symbol_combos  — dict[pid, dict[combo_str, int]]        (C4)

        Returns accumulator dict with 7 keys:
          by_st_hits, by_st_win  (C2)
          pid_payline_hits, pid_match_count_dist, pid_col_set,
          pid_has_regular_line   (C3)
          pid_symbol_combos      (C4)

        Handles:
          - None or non-dict chunk_dict: returns empty acc (C2 unchanged)
          - Missing C3/C4 keys: treated as empty dicts (old cached chunks)
          - Non-int st_key: int() conversion, falls back to -1 on failure
        """
        if not chunk_dict or not isinstance(chunk_dict, dict):
            return {
                "by_st_hits": {}, "by_st_win": {},
                "pid_payline_hits": {}, "pid_match_count_dist": {},
                "pid_col_set": {}, "pid_has_regular_line": {},
                "pid_symbol_combos": {},
            }

        by_st_hits: dict[str, dict[int, int]] = {}
        by_st_win: dict[str, dict[int, float]] = {}

        pid_by_st = chunk_dict.get("payout_id_by_spin_type") or {}
        for pid, st_map in pid_by_st.items():
            if not isinstance(st_map, dict):
                continue
            pid_str = str(pid)
            hits_for_pid = by_st_hits.setdefault(pid_str, {})
            for st_key, cnt in st_map.items():
                try:
                    st_int = int(st_key)
                except (TypeError, ValueError):
                    st_int = -1
                hits_for_pid[st_int] = hits_for_pid.get(st_int, 0) + int(cnt or 0)

        pid_win_by_st = chunk_dict.get("payout_id_win_by_spin_type") or {}
        for pid, st_map in pid_win_by_st.items():
            if not isinstance(st_map, dict):
                continue
            pid_str = str(pid)
            wins_for_pid = by_st_win.setdefault(pid_str, {})
            for st_key, win_val in st_map.items():
                try:
                    st_int = int(st_key)
                except (TypeError, ValueError):
                    st_int = -1
                wins_for_pid[st_int] = wins_for_pid.get(st_int, 0.0) + float(win_val or 0.0)

        # C3 enrichment accumulators — read from chunk_dict, pass through reduce().
        # Old cached chunks (pre-C3) won't have these keys; default to {}.
        pid_payline_hits: dict[str, dict[str, int]] = {}
        raw_pl = chunk_dict.get("payout_id_payline_hits") or {}
        for pid, pl_map in raw_pl.items():
            if isinstance(pl_map, dict):
                pid_payline_hits[str(pid)] = {str(k): int(v or 0) for k, v in pl_map.items()}

        pid_match_count_dist: dict[str, dict[int, int]] = {}
        raw_mc = chunk_dict.get("payout_id_match_count_dist") or {}
        for pid, mc_map in raw_mc.items():
            if isinstance(mc_map, dict):
                pid_match_count_dist[str(pid)] = {int(k): int(v or 0) for k, v in mc_map.items()}

        pid_col_set: dict[str, list[int]] = {}
        raw_cols = chunk_dict.get("payout_id_col_set") or {}
        for pid, cols in raw_cols.items():
            if isinstance(cols, (list, set, tuple)):
                pid_col_set[str(pid)] = sorted(set(int(c) for c in cols))

        pid_has_regular_line: dict[str, bool] = {}
        raw_hrl = chunk_dict.get("payout_id_has_regular_line") or {}
        for pid, flag in raw_hrl.items():
            if flag:  # only carry True values; False/absent = trigger-only
                pid_has_regular_line[str(pid)] = True

        # C4: symbol combination histogram from chunk_dict.
        # Old cached chunks (pre-C4) won't have this key; default to {}.
        pid_symbol_combos: dict[str, dict[str, int]] = {}
        raw_sc = chunk_dict.get("payout_id_symbol_combos") or {}
        for pid, sc_map in raw_sc.items():
            if isinstance(sc_map, dict):
                pid_symbol_combos[str(pid)] = {
                    str(combo): int(cnt or 0)
                    for combo, cnt in sc_map.items()
                    if cnt
                }

        return {
            "by_st_hits": by_st_hits,
            "by_st_win": by_st_win,
            "pid_payline_hits": pid_payline_hits,
            "pid_match_count_dist": pid_match_count_dist,
            "pid_col_set": pid_col_set,
            "pid_has_regular_line": pid_has_regular_line,
            "pid_symbol_combos": pid_symbol_combos,
        }

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Merge two extract() outputs additively across chunks.

        For each (pid, st_int) pair, sums hits and wins from both accs.
        For C3 enrichment: merges payline_hits and match_count_dist additively;
        col_set is union; has_regular_line is OR across chunks.
        For C4 enrichment: merges symbol_combos additively.
        Handles empty dicts (first chunk, empty chunk).
        """
        if not prev_acc:
            return this_acc if this_acc else {
                "by_st_hits": {}, "by_st_win": {},
                "pid_payline_hits": {}, "pid_match_count_dist": {},
                "pid_col_set": {}, "pid_has_regular_line": {},
                "pid_symbol_combos": {},
            }
        if not this_acc:
            return prev_acc

        prev_hits = prev_acc.get("by_st_hits") or {}
        prev_wins = prev_acc.get("by_st_win") or {}
        this_hits = this_acc.get("by_st_hits") or {}
        this_wins = this_acc.get("by_st_win") or {}

        merged_hits: dict[str, dict[int, int]] = {}
        merged_wins: dict[str, dict[int, float]] = {}

        # Start with prev
        for pid_str, st_map in prev_hits.items():
            merged_hits[pid_str] = dict(st_map)
        for pid_str, st_map in prev_wins.items():
            merged_wins[pid_str] = dict(st_map)

        # Merge this_hits into merged_hits
        for pid_str, st_map in this_hits.items():
            if pid_str not in merged_hits:
                merged_hits[pid_str] = dict(st_map)
            else:
                dest = merged_hits[pid_str]
                for st_int, cnt in st_map.items():
                    dest[st_int] = dest.get(st_int, 0) + cnt

        # Merge this_wins into merged_wins
        for pid_str, st_map in this_wins.items():
            if pid_str not in merged_wins:
                merged_wins[pid_str] = dict(st_map)
            else:
                dest = merged_wins[pid_str]
                for st_int, win_val in st_map.items():
                    dest[st_int] = dest.get(st_int, 0.0) + win_val

        # C3: merge payline_hits (additive)
        prev_pl = prev_acc.get("pid_payline_hits") or {}
        this_pl = this_acc.get("pid_payline_hits") or {}
        merged_pl: dict[str, dict[str, int]] = {}
        for pid_str, pl_map in prev_pl.items():
            merged_pl[pid_str] = dict(pl_map)
        for pid_str, pl_map in this_pl.items():
            if pid_str not in merged_pl:
                merged_pl[pid_str] = dict(pl_map)
            else:
                dest = merged_pl[pid_str]
                for pl_id, cnt in pl_map.items():
                    dest[pl_id] = dest.get(pl_id, 0) + cnt

        # C3: merge match_count_dist (additive)
        prev_mc = prev_acc.get("pid_match_count_dist") or {}
        this_mc = this_acc.get("pid_match_count_dist") or {}
        merged_mc: dict[str, dict[int, int]] = {}
        for pid_str, mc_map in prev_mc.items():
            merged_mc[pid_str] = dict(mc_map)
        for pid_str, mc_map in this_mc.items():
            if pid_str not in merged_mc:
                merged_mc[pid_str] = dict(mc_map)
            else:
                dest = merged_mc[pid_str]
                for mc, cnt in mc_map.items():
                    dest[mc] = dest.get(mc, 0) + cnt

        # C3: merge col_set (union)
        prev_cs = prev_acc.get("pid_col_set") or {}
        this_cs = this_acc.get("pid_col_set") or {}
        merged_cs: dict[str, list[int]] = {}
        all_cs_pids = set(prev_cs.keys()) | set(this_cs.keys())
        for pid_str in all_cs_pids:
            merged_cs[pid_str] = sorted(
                set(prev_cs.get(pid_str) or []) | set(this_cs.get(pid_str) or [])
            )

        # C3: merge has_regular_line (OR — True if True in ANY chunk)
        prev_hrl = prev_acc.get("pid_has_regular_line") or {}
        this_hrl = this_acc.get("pid_has_regular_line") or {}
        merged_hrl: dict[str, bool] = dict(prev_hrl)
        for pid_str, flag in this_hrl.items():
            if flag:
                merged_hrl[pid_str] = True

        # C4: merge symbol_combos (additive — sum counts per combo string)
        prev_sc = prev_acc.get("pid_symbol_combos") or {}
        this_sc = this_acc.get("pid_symbol_combos") or {}
        merged_sc: dict[str, dict[str, int]] = {}
        for pid_str, sc_map in prev_sc.items():
            merged_sc[pid_str] = dict(sc_map)
        for pid_str, sc_map in this_sc.items():
            if pid_str not in merged_sc:
                merged_sc[pid_str] = dict(sc_map)
            else:
                dest = merged_sc[pid_str]
                for combo, cnt in sc_map.items():
                    dest[combo] = dest.get(combo, 0) + cnt

        return {
            "by_st_hits": merged_hits,
            "by_st_win": merged_wins,
            "pid_payline_hits": merged_pl,
            "pid_match_count_dist": merged_mc,
            "pid_col_set": merged_cs,
            "pid_has_regular_line": merged_hrl,
            "pid_symbol_combos": merged_sc,
        }

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Build and write summary["player_impact"]["payouts_by_spin_type"].

        Reads:
          ctx.effective_bet_for_rtp — RTP denominator (global paid-session bet)
          summary["player_impact"]["spin_type_breakdown"] — for ST labels +
            spins counts (written by F1 inline; guaranteed present per
            04_v3 §4.2 Phase B ordering contract)
          final_acc — accumulated (pid, ST) hit/win data from extract/reduce
            plus C3/C4 enrichment fields (pid_payline_hits, pid_match_count_dist,
            pid_col_set, pid_has_regular_line, pid_symbol_combos)

        Writes:
          summary["player_impact"]["payouts_by_spin_type"]:
            {spin_type_label: [{payout_id, hit_count, hit_rate, total_win,
                                avg_win_when_hit, rtp_contribution_pp,
                                shape, covered_columns, paylines, notes,
                                symbol_combo}]}

        C2 fields (payout_id ... rtp_contribution_pp) are byte-identical
        to pre-C3 output. C3 adds 4 new fields per row.

        Shape enrichment:
          shape = {"{N}_of_a_kind": hit_count, ...} keyed over all
          match_count values observed for this pid. Empty dict for
          trigger markers (line_id == -1 only).

        Covered_columns enrichment:
          covered_columns = sorted list of 0-indexed column indices
          seen in this pid's PayoutByPayline records. Empty list if
          no position data available (old cached chunks).

        Paylines enrichment:
          paylines = [{payline_id, hit_count}] sorted by payline_id.
          Only non-trigger paylines (line_id != -1) included for
          regular pids. For trigger markers: includes the "-1" entry.
          hit_count is aggregate across all STs (not per-ST) since
          payline attribution is not broken down by ST in parser.

        Notes enrichment:
          notes = {
            is_trigger_marker: bool  — pid=666 canonical case
            max_match_count_observed: int  — e.g. 3 for 3-of-a-kind
          }
          is_trigger_marker: True iff ALL hit records have line_id==-1
            AND total_win == 0 for this pid (across all STs).
          max_match_count_observed: largest match_count seen for this pid.

        Symbol_combo enrichment (C4):
          symbol_combo = {
            dominant: str | None  — most-frequent combo string (e.g.
                "cherry|cherry|35x_wild"), or None if no decode available.
            distinct_symbols: list[str]  — sorted union of all symbol names
                seen across all combos for this pid (wilds preserved).
          }
          Absent for pids with no StopSymbolsByCol data (old cached chunks,
          scatter-only pids, or STs without PayoutByPayline). The combo is
          aggregate across ALL STs (decode is per-round, not per-ST).

        Sort order (unchanged from C2):
          - STs: by spin_type ascending (via _st_label sorted iteration)
          - PIDs within each ST: by total_win descending
        """
        effective_bet_for_rtp = ctx.effective_bet_for_rtp
        player_impact = summary.setdefault("player_impact", {})

        # Derive _st_label from spin_type_breakdown (F1 already wrote it).
        # Format: "ST{N}_{behavior_name}" e.g. "ST1_paid", "ST126_free".
        spin_type_breakdown = player_impact.get("spin_type_breakdown") or []
        _st_label: dict[int, str] = {
            int(row["spin_type"]): f"ST{int(row['spin_type'])}_{row['behavior_name']}"
            for row in spin_type_breakdown
        }
        # Per-ST spins count for hit_rate denominator.
        _st_spins: dict[int, int] = {
            int(row["spin_type"]): int(row.get("spins", 0))
            for row in spin_type_breakdown
        }

        by_st_hits = (final_acc or {}).get("by_st_hits") or {}
        by_st_win = (final_acc or {}).get("by_st_win") or {}

        # C3/C4 enrichment fields from accumulator.
        pid_payline_hits: dict[str, dict[str, int]] = (final_acc or {}).get("pid_payline_hits") or {}
        pid_match_count_dist: dict[str, dict[int, int]] = (final_acc or {}).get("pid_match_count_dist") or {}
        pid_col_set: dict[str, list[int]] = (final_acc or {}).get("pid_col_set") or {}
        pid_has_regular_line: dict[str, bool] = (final_acc or {}).get("pid_has_regular_line") or {}
        pid_symbol_combos: dict[str, dict[str, int]] = (final_acc or {}).get("pid_symbol_combos") or {}

        # Compute per-pid total win across all STs (for sort order).
        # This must match `payout_id_win` ordering: sum over all STs.
        # For pids only in by_st_hits (win=0 trigger markers), total_win=0.0.
        all_pids: set[str] = set(by_st_hits.keys()) | set(by_st_win.keys())
        pid_total_win: dict[str, float] = {}
        for pid_str in all_pids:
            pid_total_win[pid_str] = sum(
                (by_st_win.get(pid_str) or {}).values()
            )

        payouts_by_spin_type: dict[str, list[dict[str, Any]]] = {}
        for st_int, label in sorted(_st_label.items()):
            st_spins_count = _st_spins.get(st_int, 0)
            st_pid_rows: list[dict[str, Any]] = []

            # Sort pids by total win descending (matches inline block ordering).
            for pid_str, _total_win in sorted(
                pid_total_win.items(),
                key=lambda kv: kv[1],
                reverse=True,
            ):
                st_win_map = by_st_win.get(pid_str) or {}
                st_win = float(st_win_map.get(st_int, 0.0))
                st_hit_map = by_st_hits.get(pid_str) or {}
                st_hits = int(st_hit_map.get(st_int, 0))
                # Skip if pid did not fire in this ST.
                # Trigger-marker pids (e.g. pid 666, win=0) are retained
                # as long as st_hits > 0 — consistent with inline block.
                if st_hits == 0:
                    continue

                # --- C3 enrichment ---
                # shape: n-of-a-kind distribution for this pid (all STs combined).
                # Empty for trigger markers (no regular-line records).
                mc_dist = pid_match_count_dist.get(pid_str) or {}
                shape: dict[str, int] = {
                    f"{mc}_of_a_kind": cnt
                    for mc, cnt in sorted(mc_dist.items())
                } if mc_dist else {}

                # covered_columns: sorted column indices from positions.
                covered_columns: list[int] = list(pid_col_set.get(pid_str) or [])

                # paylines: per-payline hit counts for this pid.
                # Only include non-trigger paylines (line_id != -1) for
                # regular pids; for trigger markers, show the -1 entry.
                pl_map = pid_payline_hits.get(pid_str) or {}
                is_trigger = not pid_has_regular_line.get(pid_str, False) and _total_win == 0.0

                # Defensive pre-validation: payline_id must be accepted by int().
                # Using try/except int() directly mirrors the sort key — anything
                # int() accepts passes (e.g. "-1", "-10", "5", "10"); anything it
                # rejects (e.g. "--1", "1-2", "abc", "") gets the descriptive
                # RuntimeError rather than a bare ValueError at the sort call.
                # Per feedback_capture_drift.md: schema drift must surface as a
                # human-readable error. Caught by pia:5083 emit-error handler →
                # feature_errors["payouts_by_spin_type"] (not a hard crash).
                for pl_id in pl_map:
                    try:
                        int(pl_id)
                    except (ValueError, TypeError):
                        raise RuntimeError(
                            f"payouts_by_spin_type: non-integer payline_id {pl_id!r} "
                            f"encountered for pid {pid_str!r}. Schema drift? All audited "
                            f"machines have int-parseable payline_ids."
                        )

                if is_trigger:
                    # Trigger marker: include all entries (only -1 lines expected).
                    # int("-1") = -1 < 1, so scatter sentinel sorts first naturally.
                    paylines: list[dict[str, Any]] = sorted(
                        [{"payline_id": pl_id, "hit_count": cnt}
                         for pl_id, cnt in pl_map.items()],
                        key=lambda x: int(x["payline_id"]),
                    )
                else:
                    # Regular pid: exclude -1 (trigger-marker line) entries.
                    # Sort by int key — fixes lexicographic "1","10","11","2" for
                    # machines with 10+ paylines (d1 fix, R1 Phase 2).
                    paylines = sorted(
                        [{"payline_id": pl_id, "hit_count": cnt}
                         for pl_id, cnt in pl_map.items()
                         if pl_id != "-1"],
                        key=lambda x: int(x["payline_id"]),
                    )

                # notes: explicit signal fields per pid.
                # max_match_count_observed: largest n-of-a-kind seen.
                max_mc = max(mc_dist.keys()) if mc_dist else 0
                notes: dict[str, Any] = {
                    "is_trigger_marker": is_trigger,
                    "max_match_count_observed": max_mc,
                }

                # --- C4 enrichment: symbol_combo ---
                # Aggregate across ALL STs (decode is per-round, not per-ST).
                # dominant: combo_str with highest cumulative count for this pid.
                # distinct_symbols: sorted union of all symbol names across combos.
                sc_map = pid_symbol_combos.get(pid_str) or {}
                if sc_map:
                    dominant_combo: str | None = max(
                        sc_map.items(), key=lambda kv: kv[1]
                    )[0]
                    # Collect all symbol names from all combos (split by "|")
                    _all_syms: set[str] = set()
                    for _combo_str in sc_map:
                        for _sym in _combo_str.split("|"):
                            if _sym:
                                _all_syms.add(_sym)
                    symbol_combo: dict[str, Any] = {
                        "dominant": dominant_combo,
                        "distinct_symbols": sorted(_all_syms),
                    }
                else:
                    symbol_combo = {"dominant": None, "distinct_symbols": []}
                # --- end C4 enrichment ---

                st_pid_rows.append({
                    # C2 fields (byte-identical to pre-C3)
                    "payout_id": pid_str,
                    "hit_count": st_hits,
                    "hit_rate": (
                        (st_hits / st_spins_count) if st_spins_count > 0 else 0.0
                    ),
                    "total_win": st_win,
                    "avg_win_when_hit": (
                        (st_win / st_hits) if st_hits > 0 else 0.0
                    ),
                    "rtp_contribution_pp": (
                        (st_win / effective_bet_for_rtp) * 100.0
                        if effective_bet_for_rtp > 0 else 0.0
                    ),
                    # C3 new fields
                    "shape": shape,
                    "covered_columns": covered_columns,
                    "paylines": paylines,
                    "notes": notes,
                    # C4 new field
                    "symbol_combo": symbol_combo,
                })
            payouts_by_spin_type[label] = st_pid_rows

        player_impact["payouts_by_spin_type"] = payouts_by_spin_type


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per ticket P2-C §4 C2: duplicate registration is a silent no-op.
# ---------------------------------------------------------------------------
register(PayoutsBySpinType())

# ---------------------------------------------------------------------------
# Auto-import spin_type_outcomes so it self-registers whenever
# payouts_by_spin_type is imported.
#
# This avoids touching player_impact_analyzer.py (a closure file) and
# therefore does NOT flip base_hash (R-4 exclusion: feature plugin files
# are excluded from _CLOSURE_FILES).
#
# spin_type_outcomes.REQUIRES = ("payouts_by_spin_type",) ensures the
# topo-sort places it after us in the emit loop.
#
# Both this file and spin_type_outcomes.py are feature plugin files
# (NOT in _CLOSURE_FILES) so editing either does not flip base_hash.
# ---------------------------------------------------------------------------
# Use find_spec to distinguish "module genuinely absent" (non-fatal — skip)
# from "module present but its import raised" (a real bug — must surface, NOT
# be swallowed, per feedback_no_silent_swallow.md). A bare `except ImportError:
# pass` would hide a broken spin_type_outcomes as silent non-registration,
# which only resurfaces later as a misleading PluginMissingDependencyError.
import importlib as _il
import importlib.util as _ilu

for _sto_name in (
    "fresh_slotlab.analyzer.features.spin_type_outcomes",
    "analyzer.features.spin_type_outcomes",
):
    try:
        _sto_spec = _ilu.find_spec(_sto_name)
    except ModuleNotFoundError:
        _sto_spec = None  # parent package not importable on this path — try next
    if _sto_spec is not None:
        # Found — import WITHOUT swallowing so any error inside the module
        # (broken import, syntax/name error) propagates loudly.
        _il.import_module(_sto_name)
        break
# If neither path resolves a spec, spin_type_outcomes is genuinely absent
# (e.g. a trimmed deployment) — that is a non-fatal skip.
