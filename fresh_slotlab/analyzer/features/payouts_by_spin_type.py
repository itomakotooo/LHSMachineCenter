"""AnalyzerFeature: payouts_by_spin_type — Pattern B (real extraction).

Phase C2 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §7.2.

Pattern B: extract() reads per-chunk payout_id_by_spin_type +
payout_id_win_by_spin_type; reduce() merges across chunks; emit()
writes summary["player_impact"]["payouts_by_spin_type"].

SCHEMA_VERSION = 1 (unchanged from C2; C3 enrichment bumps to 2).
DECLARED_DEPS = () — emit() reads summary["player_impact"]["spin_type_breakdown"]
  directly (written by F1 inline before the plugin emit loop starts, per
  04_v3 §4.2 Phase B ordering contract). No _-prefix temp key needed.

Per memory/feedback_subprocess_import_suicide_and_module_globals.md:
  register() is a pure list-append — no I/O at import time.
Per memory/feedback_no_silent_swallow.md:
  extract() errors are captured by the PIA merge loop, not silently swallowed.
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

    Accumulator structure
    ---------------------
    by_st_hits: dict[pid_str, dict[st_int, int]]
        For each payout_id, for each SpinType int, the number of hits
        in that (pid, ST) pair across all processed chunks.
    by_st_win: dict[pid_str, dict[st_int, float]]
        For each payout_id, for each SpinType int, the total credits won
        in that (pid, ST) pair across all processed chunks.

    The key types are:
    - pid_str: str (payout id as string, e.g. "6", "666", "27502")
    - st_int: int (SpinType integer, e.g. 1, 126, 140)

    emit() reads summary["player_impact"]["spin_type_breakdown"] to derive
    per-ST labels and spins counts. This key is guaranteed present by the
    Phase B ordering contract (F1 inline writes it before the emit loop).
    """

    FEATURE_ID: ClassVar[str] = "payouts_by_spin_type"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("payouts_by_spin_type",)
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False  # display only
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Read per-chunk (pid, ST) hit and win data.

        Reads:
          chunk_dict["payout_id_by_spin_type"]   — dict[pid, dict[st_str, int]]
          chunk_dict["payout_id_win_by_spin_type"] — dict[pid, dict[st_str, float]]

        Returns accumulator:
          {"by_st_hits": {pid_str: {st_int: int}},
           "by_st_win":  {pid_str: {st_int: float}}}

        Handles:
          - None or non-dict chunk_dict: returns empty acc
          - Missing keys: treated as empty dict
          - Non-int st_key: int() conversion, falls back to -1 on failure
        """
        if not chunk_dict or not isinstance(chunk_dict, dict):
            return {"by_st_hits": {}, "by_st_win": {}}

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

        return {"by_st_hits": by_st_hits, "by_st_win": by_st_win}

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Merge two extract() outputs additively across chunks.

        For each (pid, st_int) pair, sums hits and wins from both accs.
        Handles empty dicts (first chunk, empty chunk).
        """
        if not prev_acc:
            return this_acc if this_acc else {"by_st_hits": {}, "by_st_win": {}}
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

        return {"by_st_hits": merged_hits, "by_st_win": merged_wins}

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Build and write summary["player_impact"]["payouts_by_spin_type"].

        Reads:
          ctx.effective_bet_for_rtp — RTP denominator (global paid-session bet)
          summary["player_impact"]["spin_type_breakdown"] — for ST labels +
            spins counts (written by F1 inline; guaranteed present per
            04_v3 §4.2 Phase B ordering contract)
          final_acc — accumulated (pid, ST) hit/win data from extract/reduce

        Writes:
          summary["player_impact"]["payouts_by_spin_type"]:
            {spin_type_label: [{payout_id, hit_count, hit_rate, total_win,
                                avg_win_when_hit, rtp_contribution_pp}]}

        Output is byte-identical to the pre-C2 inline block. Sort order:
          - STs: by spin_type ascending (via _st_label sorted iteration)
          - PIDs within each ST: by total_win descending (same as inline block)
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
                st_pid_rows.append({
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
                })
            payouts_by_spin_type[label] = st_pid_rows

        player_impact["payouts_by_spin_type"] = payouts_by_spin_type


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per ticket P2-C §4 C2: duplicate registration is a silent no-op.
# ---------------------------------------------------------------------------
register(PayoutsBySpinType())
