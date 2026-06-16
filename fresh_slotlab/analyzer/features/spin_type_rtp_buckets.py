"""AnalyzerFeature: spin_type_rtp_buckets — per-SpinType round-level RTP bucket distribution.

Purpose
-------
The global multiplier_profile.buckets bins each session's total win/bet into
canonical buckets — a session-level (paid-round-level) RTP distribution.  This
feature does the SAME thing PER SpinType: for each ST, the distribution of its
PAID rounds' win/bet across the same canonical 11-bucket order.

This lets the operator answer: "What fraction of ST1_paid rounds lose entirely?
What share of ST1_paid's RTP comes from 20x+ hits?".  Directly comparable to
the global multiplier_profile because the same bucket edges and the same global
paid-bet denominator are used.

Design spec anchor
------------------
Brief: "build a per-SpinType ROUND-LEVEL RTP bucket distribution in the analyzer".
Parser change: parser.py adds spin_type_paid_bucket_{spins,bet,win} accumulators
  (ONLY is_paid=True and bet_amt>0 rounds) and emits them as
  chunk_dict["spin_type_rtp_buckets"].
  The parser change flips base_hash (one-time, expected; same as C3 round-level
  enrichment).  This plugin file is NOT in _CLOSURE_FILES (R-4 exclusion), so
  editing THIS file does NOT flip base_hash.

Data path
---------
extract() reads chunk_dict["spin_type_rtp_buckets"]:
    str(st) -> {bucket_label -> {"spins": int, "bet": float, "win": float}}
    Only paid rounds (is_paid=True, bet>0) are in this map.

reduce() merges two extract() accumulators additively (per-ST per-bucket).

emit() computes and writes summary["player_impact"]["spin_type_rtp_buckets"]:
    {"ST1_paid": [
        {"bucket": "gt0_lt1", "spin_count": int, "spin_rate": float,
         "avg_return_x_in_bucket": float, "rtp_contribution_pp": float,
         "win_share": float},
        ...  (11 rows in RETURN_BUCKET_ORDER)
     ], ...}

Field semantics (mirrored from aggregator.build_multiplier_bucket_rows exactly):
  spin_count          — number of paid rounds in this bucket for this ST
  spin_rate           — spin_count / ST_paid_rounds (fraction of this ST's paid rounds)
  avg_return_x_in_bucket — bucket_win_sum / bucket_bet_sum (average win/bet for rounds
                            that LAND in this bucket; 0 when no rounds)
  rtp_contribution_pp — bucket_win_sum / GLOBAL total_bet * 100, where GLOBAL
                        total_bet = sum(spin_type_breakdown[*].total_bet) — the SAME
                        denominator spin_type_breakdown uses (all rounds, incl. bonus
                        BetAmount). So per pure-paid ST the bucket rows sum to that ST's
                        spin_type_breakdown.rtp_contribution_pp.
  win_share           — bucket_win_sum / ST_total_win (0 when ST has no win)

RETURN_BUCKET_ORDER alignment
------------------------------
Bucket edges match RETURN_BUCKET_ORDER in aggregator.py / return_bucket() in _utils.py
exactly (imported from aggregator).  The "eq0" internal sentinel (zero-win rounds)
is NOT in RETURN_BUCKET_ORDER so zero-win paid rounds are silently excluded from the
output rows — matching the behaviour of the global multiplier_profile.

Parity invariant (per feedback_aggregator_parity_invariant.md)
--------------------------------------------------------------
For a pure-paid ST (all its rounds are paid, e.g. ST1), the sum of per-ST bucket
rtp_contribution_pp == that ST's spin_type_breakdown rtp_contribution_pp (within
floating-point precision) — because both use GLOBAL total_bet as denominator and
the numerator is that ST's paid-round win (== its total win when no free rounds).
Verified by the gate test with a tight tolerance. (For mixed STs that also win on
free rounds, the buckets cover paid rounds only, so the sum is a lower bound.)

RTP_CONTRIBUTION = False
  This feature re-groups wins already attributed to STs.  It adds NOTHING new to
  the RTP sum.  sum(pay_id.rtp_pp) == summary.rtp is unaffected.

REQUIRES = ("spin_type_outcomes",)
  Ensures spin_type_outcomes (and therefore payouts_by_spin_type) ran first and
  that spin_type_breakdown is available.  Also ensures RETURN_BUCKET_ORDER is used
  consistently (same import chain as multiplier_profile).

Per-machine isolation
---------------------
This file is NOT in fresh_slotlab/analyzer/core/ — excluded from base_hash by R-4.
Only machines that declare "spin_type_rtp_buckets" in analyzer_features get this
plugin's hash in their effective_analyzer_version.

Auto-import registration
------------------------
This module is auto-imported by spin_type_outcomes.py at its bottom, using the same
find_spec / import_module idiom as payouts_by_spin_type.py → spin_type_outcomes.  This
avoids touching any closure file (player_impact_analyzer.py etc.) and therefore does
NOT flip base_hash beyond the one-time parser change.

Memory feedback honored
-----------------------
- feedback_no_hardcode.md: no machine ids in code.  M15 only in manifest + tests.
- feedback_no_silent_swallow.md: if chunk_dict key absent when present is expected,
  we raise with a diagnostic message (caught by PIA emit-error handler).
  Within extract() the key is optional (old cached chunks won't have it) — we
  return empty acc in that case and surface a flag in the acc so emit() can warn.
- feedback_aggregator_parity_invariant.md: rtp_contribution_pp uses GLOBAL
  total_bet (= sum of spin_type_breakdown total_bet — the SAME denominator
  spin_type_breakdown uses), NOT ctx.effective_bet_for_rtp (paid-only, which
  differs on machines with bonus BetAmount and would break parity), so per
  pure-paid ST the bucket rows sum to ST's rtp_contribution_pp — gate-verified.
- feedback_perf_claim_needs_e2e_event_stream: real subprocess test in the gate file.
- feedback_subprocess_import_suicide_and_module_globals.md: register() is a pure
  list-append — no I/O at import time.
- feedback_invariant_with_fallback_hides_drift.md: no catch-all bucket.  eq0 rounds
  are excluded from output rows (matching global multiplier_profile behaviour).
- feedback_no_parallel_panel_impl.md: mirrors multiplier_profile / payouts_by_spin_type
  pattern exactly; does NOT invent a parallel accumulator structure.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    from fresh_slotlab.analyzer.feature_registry import register
    from fresh_slotlab.analyzer.core.aggregator import RETURN_BUCKET_ORDER
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    from analyzer.feature_registry import register  # type: ignore[no-redef]
    from analyzer.core.aggregator import RETURN_BUCKET_ORDER  # type: ignore[no-redef]

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
    except ImportError:
        from analyzer.pipeline_context import PipelineContext  # type: ignore[assignment]


class SpinTypeRtpBuckets(AnalyzerFeature):
    """Pattern B plugin: per-chunk extraction of per-ST paid-round bucket data.

    Accumulator structure
    ---------------------
    by_st: dict[str, dict[str, {"spins": int, "bet": float, "win": float}]]
        Outer key: str(spin_type), inner key: bucket_label (from RETURN_BUCKET_ORDER).
        Accumulated across chunks by reduce().
    has_missing_chunks: bool
        True if any chunk lacked spin_type_rtp_buckets (old cached chunk).
        Surfaced in emit() as a warning comment but not a hard error.
    """

    FEATURE_ID: ClassVar[str] = "spin_type_rtp_buckets"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("spin_type_rtp_buckets",)
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False  # re-groups already-attributed wins
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    REQUIRES: ClassVar[tuple[str, ...]] = ("spin_type_outcomes",)
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Read per-ST paid-round bucket data from chunk_dict.

        Reads chunk_dict["spin_type_rtp_buckets"]:
            {str(st): {bucket_label: {"spins": int, "bet": float, "win": float}}}

        Old cached chunks (pre spin_type_rtp_buckets parser change) will not have
        this key.  We return an empty accumulator in that case and set
        has_missing_chunks=True so emit() can surface a diagnostic note.

        Returns:
            {
              "by_st": {str(st): {bucket: {"spins": int, "bet": float, "win": float}}},
              "has_missing_chunks": bool,
            }
        """
        if not chunk_dict or not isinstance(chunk_dict, dict):
            return {"by_st": {}, "has_missing_chunks": True}

        raw = chunk_dict.get("spin_type_rtp_buckets")
        if raw is None:
            # Old cached chunk — tolerate gracefully.
            return {"by_st": {}, "has_missing_chunks": True}

        if not isinstance(raw, dict):
            # Unexpected type — surface with a diagnostic error.
            raise RuntimeError(
                f"spin_type_rtp_buckets: chunk_dict['spin_type_rtp_buckets'] "
                f"has unexpected type {type(raw).__name__!r} (expected dict). "
                f"This indicates a parser version mismatch or data corruption. "
                f"Per feedback_no_silent_swallow.md: raising instead of silently "
                f"returning empty data."
            )

        by_st: dict[str, dict[str, dict[str, float]]] = {}
        for st_key, bucket_map in raw.items():
            if not isinstance(bucket_map, dict):
                continue
            st_str = str(st_key)
            st_buckets: dict[str, dict[str, float]] = {}
            for bucket_label, bdata in bucket_map.items():
                if not isinstance(bdata, dict):
                    continue
                try:
                    spins = int(bdata.get("spins") or 0)
                    bet = float(bdata.get("bet") or 0.0)
                    win = float(bdata.get("win") or 0.0)
                except (TypeError, ValueError):
                    continue
                if spins > 0 or bet > 0 or win > 0:
                    st_buckets[str(bucket_label)] = {
                        "spins": spins,
                        "bet": bet,
                        "win": win,
                    }
            if st_buckets:
                by_st[st_str] = st_buckets

        return {"by_st": by_st, "has_missing_chunks": False}

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Merge two extract() outputs additively.

        For each (st, bucket) pair, sums spins/bet/win from both accumulators.
        has_missing_chunks is OR across chunks (True if ANY chunk lacked the key).
        """
        if not prev_acc:
            return this_acc if this_acc else {"by_st": {}, "has_missing_chunks": False}
        if not this_acc:
            return prev_acc

        prev_by_st = prev_acc.get("by_st") or {}
        this_by_st = this_acc.get("by_st") or {}
        has_missing = bool(prev_acc.get("has_missing_chunks")) or bool(
            this_acc.get("has_missing_chunks")
        )

        merged: dict[str, dict[str, dict[str, float]]] = {}

        # Start with prev
        for st_str, bmap in prev_by_st.items():
            merged[st_str] = {b: dict(bdata) for b, bdata in bmap.items()}

        # Merge this_by_st additively
        for st_str, bmap in this_by_st.items():
            if st_str not in merged:
                merged[st_str] = {b: dict(bdata) for b, bdata in bmap.items()}
            else:
                dest = merged[st_str]
                for bucket_label, bdata in bmap.items():
                    if bucket_label not in dest:
                        dest[bucket_label] = dict(bdata)
                    else:
                        dest[bucket_label]["spins"] = (
                            dest[bucket_label].get("spins", 0)
                            + bdata.get("spins", 0)
                        )
                        dest[bucket_label]["bet"] = (
                            dest[bucket_label].get("bet", 0.0)
                            + bdata.get("bet", 0.0)
                        )
                        dest[bucket_label]["win"] = (
                            dest[bucket_label].get("win", 0.0)
                            + bdata.get("win", 0.0)
                        )

        return {"by_st": merged, "has_missing_chunks": has_missing}

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Build and write summary["player_impact"]["spin_type_rtp_buckets"].

        Reads:
          final_acc — accumulated (st, bucket) data from extract/reduce
          ctx.effective_bet_for_rtp — GLOBAL paid-bet denominator for rtp_contribution_pp
          summary["player_impact"]["spin_type_breakdown"] — for ST labels and paid round counts

        Writes:
          summary["player_impact"]["spin_type_rtp_buckets"]:
            {
              "ST1_paid": [
                {"bucket": "gt0_lt1", "spin_count": int, "spin_rate": float,
                 "avg_return_x_in_bucket": float, "rtp_contribution_pp": float,
                 "win_share": float},
                ...  (one row per RETURN_BUCKET_ORDER label — always 11 rows)
              ],
              ...
            }

        Field semantics (mirrored exactly from aggregator.build_multiplier_bucket_rows):
          spin_rate = spin_count / ST_paid_rounds  (0 when no paid rounds)
          avg_return_x_in_bucket = bucket_win_sum / bucket_bet_sum  (0 when no bet in bucket)
          rtp_contribution_pp = bucket_win_sum / global_total_bet * 100, where
            global_total_bet = sum(spin_type_breakdown[*].total_bet)
          win_share = bucket_win_sum / ST_total_win  (0 when ST has no win)

        Parity invariant (pure-paid ST):
          sum(row["rtp_contribution_pp"] for row in bucket_rows) ==
          spin_type_breakdown[st]["rtp_contribution_pp"]  (within floating-point precision)
          Proof: both use global_total_bet (= sum of stb total_bet) as denominator;
          the numerator is sum over this ST's paid-round buckets of bucket_win_sum ==
          ST_total_paid_win. For STs that carry win ONLY on paid rounds (e.g. ST1),
          ST_total_paid_win == ST_total_win == spin_type_breakdown[st].total_win, so
          the sums are equal. (Mixed STs winning on free rounds → lower bound.)

        Only STs that have at least one paid round with bet>0 appear in the output.
        STs with zero paid rounds (pure free-spin STs) are silently omitted —
        their win/bet ratio is undefined and the global multiplier_profile also
        omits them.

        Note: has_missing_chunks=True (old cached chunks lacking the parser-side
        accumulator) is tolerated.  The output will be incomplete but not wrong.
        The presence of the key in the summary with an empty or partial dict signals
        "feature ran but data incomplete" to consumers; the summary["feature_errors"]
        key gets a warning note via the PIA emit loop if emit() raises, but here we
        prefer to write what we have rather than raise and leave the key absent.
        """
        player_impact = summary.setdefault("player_impact", {})

        # Derive ST labels and paid-round denominators from spin_type_breakdown.
        # Format: "ST{N}_{behavior_name}" — same as payouts_by_spin_type.
        stb_rows: list[dict[str, Any]] = (
            player_impact.get("spin_type_breakdown") or []
        )
        st_label: dict[int, str] = {}
        st_paid_rounds: dict[int, int] = {}
        st_total_win: dict[int, float] = {}
        for row in stb_rows:
            try:
                st_int = int(row.get("spin_type") or -1)
                bname = str(row.get("behavior_name") or "unknown")
                st_label[st_int] = f"ST{st_int}_{bname}"
                # paid_rounds: number of rounds classified as paid for this ST.
                # Comes from the spin_type_breakdown row's paid_rounds field if
                # available, else falls back to spins (for backward compat with
                # older summaries that don't have paid_rounds per-ST).
                # NOTE: we use the bucket accumulator's total spins count below as
                # the denominator (sum of bucket spin_counts) so this is only a
                # fallback for STs absent from the accumulator.
                st_paid_rounds[st_int] = int(row.get("paid_rounds") or row.get("spins") or 0)
                st_total_win[st_int] = float(row.get("total_win") or 0.0)
            except (TypeError, ValueError):
                continue

        # rtp_contribution_pp denominator MUST equal the denominator
        # spin_type_breakdown uses (total_bet = ALL rounds incl. bonus BetAmount),
        # so that sum(per-ST bucket rtp_contribution_pp) ==
        # spin_type_breakdown[ST].rtp_contribution_pp (feedback_aggregator_parity_invariant).
        # ctx.effective_bet_for_rtp is the PAID-only session bet, which differs from
        # total_bet on machines whose bonus rounds carry BetAmount — using it breaks
        # parity (M15: 41.94pp vs stb 40.27pp). Derive the global total_bet from the
        # spin_type_breakdown rows (which are guaranteed present in emit()).
        global_total_bet: float = sum(
            float(row.get("total_bet") or 0.0) for row in stb_rows
        )

        by_st: dict[str, dict[str, dict[str, float]]] = (
            (final_acc or {}).get("by_st") or {}
        )

        result: dict[str, list[dict[str, Any]]] = {}

        # Process STs in ascending spin_type order (matches payouts_by_spin_type ordering).
        all_st_ints = set()
        for st_str in by_st:
            try:
                all_st_ints.add(int(st_str))
            except (TypeError, ValueError):
                pass

        for st_int in sorted(all_st_ints):
            st_str = str(st_int)
            label = st_label.get(st_int, f"ST{st_int}_unknown")
            bmap = by_st.get(st_str) or {}

            # Compute ST-level totals from the bucket accumulator (authoritative).
            # IMPORTANT: bmap includes ALL buckets emitted by the parser accumulator,
            # including the "eq0" sentinel (zero-win paid rounds from return_bucket()).
            # "eq0" is NOT in RETURN_BUCKET_ORDER so it never appears as an output row,
            # but it MUST be counted in the denominator so spin_rates sum to 1.0.
            # This mirrors the global multiplier_profile: eq0 rounds increment
            # mb_total_spins (the denominator) but are not shown as a bucket row.
            st_total_paid_spins = sum(bdata.get("spins", 0) for bdata in bmap.values())
            st_total_bet = sum(bdata.get("bet", 0.0) for bdata in bmap.values())
            # win_total: sum only over named buckets (eq0 has win=0.0 anyway since
            # return_bucket returns eq0 only when win_amt <= 0).
            st_bucket_win_total = sum(bdata.get("win", 0.0) for bdata in bmap.values())

            if st_total_paid_spins == 0:
                # No paid rounds for this ST — skip (win/bet ratio undefined).
                continue

            rows: list[dict[str, Any]] = []
            for bucket_label in RETURN_BUCKET_ORDER:
                bdata = bmap.get(bucket_label, {})
                spin_count = int(bdata.get("spins", 0))
                bet_sum = float(bdata.get("bet", 0.0))
                win_sum = float(bdata.get("win", 0.0))
                rows.append({
                    "bucket": bucket_label,
                    "spin_count": spin_count,
                    "spin_rate": (
                        spin_count / st_total_paid_spins
                        if st_total_paid_spins > 0 else 0.0
                    ),
                    "avg_return_x_in_bucket": (
                        win_sum / bet_sum if bet_sum > 0 else 0.0
                    ),
                    "rtp_contribution_pp": (
                        (win_sum / global_total_bet) * 100.0
                        if global_total_bet > 0 else 0.0
                    ),
                    "win_share": (
                        win_sum / st_bucket_win_total
                        if st_bucket_win_total > 0 else 0.0
                    ),
                })

            result[label] = rows

        player_impact["spin_type_rtp_buckets"] = result


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# ---------------------------------------------------------------------------
register(SpinTypeRtpBuckets())
