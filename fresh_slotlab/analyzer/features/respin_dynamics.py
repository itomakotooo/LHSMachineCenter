"""AnalyzerFeature: respin_dynamics — the WinRespin (st50) MECHANIC view.

M43 onboarding (Wave 4). The reel/payid/outcome DIMENSIONS of st50 are already
covered by the strict-reused PER_SPINTYPE plugins (payouts_by_spin_type /
reel_marginal_by_spin_type / spin_type_outcomes / spin_type_rtp_buckets). This
feature quantifies the RESPIN MECHANIC itself — the felt experience that makes
st50 a distinct event — as rates / multipliers / probabilities / distributions
(money-agnostic; NO coin totals).

What the player feels (design 03_design.md §1): a win on a paid spin sometimes
"locks in" and the reels spin again for free on a premium (skin-6) board; if that
respin also wins it can keep going. The metrics below quantify reward-continuation
/ escalation.

Mechanic metrics (design M1–M5)
-------------------------------
- M1 grant-rate: how often a win turns into a free respin. Two felt denominators:
    per winning paid spin (≈1 in 10), per all paid spins (≈1 per 75).
    Signal: ST1->ST50 opener transitions / winning-st1 and / all-st1.
- M2 hit-rate uplift: the respin board feels more generous than the base game.
    Signal: st50 hit_rate vs st1 hit_rate (ratio) + the two overlaid multiplier
    distributions (per-ST return-bucket histograms).
- M3 skin-6 premium-reel effect: WHY the respin pays more. The symbol→multiplier
    paytable is SHARED with st1, so the uplift is a shifted symbol/win-frequency
    MIX on skin 6. Signal: st50 payid share vs st1 payid share (per-pid hit/win).
- M4 continuity: a respin that wins gives ANOTHER respin (escalation). The
    CONTINUATION PROBABILITY P(st50 -> st50) is derivable from transition counts.
    NOTE (parser_blind): the exact burst-length histogram (len1/2/3) and the
    win-gating proof (len>=2 bursts are 100% win-bursts) need per-round run-length
    accumulation that lives only in the parser (a base-closure file) — see the
    `parser_blind` output field.
- M5 RTP-concentration: how much payback the respin mechanic adds, and its tier
    shape (mostly small/zero, occasionally a fat-tail pop). Signal: st50
    rtp_contribution_pp / total + the per-ST return-bucket tail share.

Data path (all base-EXCLUDED — no parser/closure dependency)
------------------------------------------------------------
extract() reads two PER-CHUNK accumulators the parser already emits in the chunk
dict (rec) — we accumulate them OURSELVES (no dependency on the consumed
_upstream_feature_breakdown_data stash, no ordering fragility):

  chunk_dict["spin_type_next_counts"]
      {str(from_st): {str(to_st): count}} — the per-robot ST transition tally.
      Gives ST1->ST50 openers (M1), ST50->ST50 continuations (M4), ST50 exits.
  chunk_dict["spin_type_bucket_spins" | "spin_type_bucket_bet" | "spin_type_bucket_win"]
      {str(st): {return_bucket_label: value}} — per-ST win/bet multiplier-band
      histogram over ALL rounds (free included). For st50 the bet defaults to the
      run bet (BetAmount=1000), so the bands are meaningful multipliers (M2/M5).
      return_bucket() bands are in RETURN_BUCKET_ORDER; "eq0" (zero-win) is the
      loss band and is NOT in that order (counted in the denominator, not shown).

emit() additionally reads two already-built summary sections (byte-stable, from
the strict-reused plugins; guaranteed present before the emit loop / via our
REQUIRES on payouts_by_spin_type):

  summary["player_impact"]["spin_type_breakdown"]
      per-ST round-level stats (spins, win_rounds, hit_rate, total_win,
      rtp_contribution_pp, behavior_name). M2 hit-rate, M5 RTP-share.
  summary["player_impact"]["payouts_by_spin_type"]
      per-ST payid rows (payout_id, hit_count, total_win, symbol_combo). M3 mix.

RTP_CONTRIBUTION = False
  This feature re-presents wins already attributed to st50 by the PER_SPINTYPE
  plugins. It adds NOTHING to the RTP sum; sum(pay_id.rtp_pp)==summary.rtp is
  unaffected (feedback_aggregator_parity_invariant.md).

Per-machine isolation
---------------------
This file is NOT in fresh_slotlab/analyzer/core/ and NOT in versioning._CLOSURE_FILES
— it is base-EXCLUDED (R-4). Auto-discovered via feature_registry.discover_features()
(globs features/*.py). Editing it re-flags ONLY machines that declare
"respin_dynamics" (via the `respin` role in machine_spec.ROLE_ANALYSES).

Memory feedback honored
-----------------------
- feedback_no_hardcode.md: no M43-specific ids. The respin/base/settlement STs are
  resolved from the manifest's spin_types (role/play), passed via
  ctx.machine_spec_manifest — NOT hardcoded "50"/"1".
- feedback_no_silent_swallow.md: a missing REQUIRES section (payouts_by_spin_type)
  RAISES (recorded in feature_errors). The parser_blind sub-metrics are surfaced
  EXPLICITLY in a `parser_blind` field rather than emitted as fabricated zeros.
- feedback_aggregator_parity_invariant.md: RTP_CONTRIBUTION = False.
- feedback_invariant_with_fallback_hides_drift.md: no catch-all bucket; rates with
  a zero denominator are emitted as null (not a "0.0 with 0 denominator" lie).
- feedback_no_parallel_panel_impl.md: mirrors spin_type_outcomes /
  spin_type_rtp_buckets / topdollar_choice pattern (extract/reduce/emit, ClassVar
  layout, try/except dual-path import, register()); reuses RETURN_BUCKET_ORDER.
- feedback_subprocess_import_suicide_and_module_globals.md: register() is a pure
  list-append; no I/O at import time.
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


# Multiplier-band tail thresholds (felt "fat-tail" cut). A band qualifies as
# tail if its lower bound is >= the threshold. Used for the M5 fat-tail share.
# Tail = >= 20x bands (the "occasional 20-300x pop" of the respin).
_TAIL_GE20_BANDS: frozenset[str] = frozenset({
    "ge20_lt50", "ge50_lt100", "ge100_lt200", "ge200_lt500",
    "ge500_lt1000", "ge1000_lt5000", "ge5000",
})


def _merge_nested_counts(
    prev: dict[str, dict[str, float]],
    this: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Additively merge two {outer: {inner: number}} dicts (used for both the
    transition tally and the per-ST bucket tallies)."""
    out: dict[str, dict[str, float]] = {}
    for okey, imap in prev.items():
        out[okey] = dict(imap)
    for okey, imap in this.items():
        dest = out.setdefault(okey, {})
        for ikey, val in imap.items():
            dest[ikey] = dest.get(ikey, 0) + val
    return out


def _resolve_st_by_role_or_play(
    manifest: dict[str, Any] | None,
    *,
    role: str | None = None,
    play: str | None = None,
) -> int | None:
    """Return the first SpinType int whose spec matches the given role or play.

    Reads ctx.machine_spec_manifest (the SpinType-native manifest). Returns None
    if no manifest or no match — callers degrade gracefully (no hardcoded ids,
    per feedback_no_hardcode.md).
    """
    if not isinstance(manifest, dict):
        return None
    for st_key, spec in (manifest.get("spin_types") or {}).items():
        if not isinstance(spec, dict):
            continue
        if role is not None and str(spec.get("role", "")) == role:
            try:
                return int(st_key)
            except (TypeError, ValueError):
                continue
        if play is not None and str(spec.get("play", "")) == play:
            try:
                return int(st_key)
            except (TypeError, ValueError):
                continue
    return None


class RespinDynamics(AnalyzerFeature):
    """Pattern-B plugin: accumulate transition + per-ST bucket data per chunk;
    compute the respin-mechanic metrics in emit() (reading the byte-stable
    spin_type_breakdown / payouts_by_spin_type sections too).

    Accumulator structure
    ---------------------
      next_counts: dict[str, dict[str, int]]
          ST transition tally (from spin_type_next_counts), merged across chunks.
      bucket_spins / bucket_win: dict[str, dict[str, number]]
          per-ST return-bucket histograms (from spin_type_bucket_{spins,win}).
    """

    FEATURE_ID: ClassVar[str] = "respin_dynamics"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("respin_dynamics",)
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False  # re-presents already-attributed wins
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    # We read summary["player_impact"]["payouts_by_spin_type"] +
    # ["spin_type_breakdown"] in emit(); REQUIRES payouts_by_spin_type guarantees
    # both are present (payouts_by_spin_type itself requires spin_type_breakdown,
    # written by the inline F1 block before the emit loop).
    REQUIRES: ClassVar[tuple[str, ...]] = ("payouts_by_spin_type",)
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Lift the per-chunk transition tally + per-ST bucket histograms.

        Returns {next_counts, bucket_spins, bucket_win}. Empty dicts when the
        keys are absent (old cached chunks / non-applicable machine) — a valid
        state, not an error (feedback_no_silent_swallow.md: absence of OPTIONAL
        per-chunk accumulators is legitimate; only a malformed shape would raise,
        but these are simple dict reads with defensive coercion).
        """
        if not chunk_dict or not isinstance(chunk_dict, dict):
            return {"next_counts": {}, "bucket_spins": {}, "bucket_win": {}}

        def _coerce_nested(raw: Any, *, as_int: bool) -> dict[str, dict[str, float]]:
            out: dict[str, dict[str, float]] = {}
            if not isinstance(raw, dict):
                return out
            for okey, imap in raw.items():
                if not isinstance(imap, dict):
                    continue
                inner: dict[str, float] = {}
                for ikey, val in imap.items():
                    try:
                        inner[str(ikey)] = int(val or 0) if as_int else float(val or 0.0)
                    except (TypeError, ValueError):
                        continue
                if inner:
                    out[str(okey)] = inner
            return out

        return {
            "next_counts": _coerce_nested(
                chunk_dict.get("spin_type_next_counts"), as_int=True
            ),
            "bucket_spins": _coerce_nested(
                chunk_dict.get("spin_type_bucket_spins"), as_int=True
            ),
            "bucket_win": _coerce_nested(
                chunk_dict.get("spin_type_bucket_win"), as_int=False
            ),
        }

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Additively merge transition + bucket tallies across chunks."""
        if not prev_acc:
            return this_acc if this_acc else {
                "next_counts": {}, "bucket_spins": {}, "bucket_win": {}
            }
        if not this_acc:
            return prev_acc
        return {
            "next_counts": _merge_nested_counts(
                prev_acc.get("next_counts") or {}, this_acc.get("next_counts") or {}
            ),
            "bucket_spins": _merge_nested_counts(
                prev_acc.get("bucket_spins") or {}, this_acc.get("bucket_spins") or {}
            ),
            "bucket_win": _merge_nested_counts(
                prev_acc.get("bucket_win") or {}, this_acc.get("bucket_win") or {}
            ),
        }

    @staticmethod
    def _bucket_distribution(
        bucket_spins: dict[str, int],
        bucket_win: dict[str, float],
    ) -> dict[str, Any]:
        """Build a money-agnostic multiplier-band distribution for one ST.

        Returns {bands:[{band, spin_count, prob, win_share}], total_spins,
        win_rounds, tail_ge20x_win_share, tail_ge20x_spin_rate}. The denominator
        is ALL of this ST's rounds (incl. the eq0 loss band) so prob sums to 1.0.
        Win shares are over this ST's total win.
        """
        # eq0 (zero-win) rounds are in bucket_spins but NOT in RETURN_BUCKET_ORDER.
        total_spins = sum(int(v) for v in bucket_spins.values())
        total_win = sum(float(v) for v in bucket_win.values())
        win_rounds = sum(
            int(c) for b, c in bucket_spins.items() if b != "eq0"
        )
        bands: list[dict[str, Any]] = []
        tail_win = 0.0
        tail_spins = 0
        for band in RETURN_BUCKET_ORDER:
            sc = int(bucket_spins.get(band, 0))
            bw = float(bucket_win.get(band, 0.0))
            if sc == 0 and bw == 0.0:
                continue
            bands.append({
                "band": band,
                "spin_count": sc,
                "prob": (sc / total_spins) if total_spins > 0 else None,
                "win_share": (bw / total_win) if total_win > 0 else None,
            })
            if band in _TAIL_GE20_BANDS:
                tail_win += bw
                tail_spins += sc
        return {
            "total_spins": total_spins,
            "win_rounds": win_rounds,
            "bands": bands,
            "tail_ge20x_win_share": (tail_win / total_win) if total_win > 0 else None,
            "tail_ge20x_spin_rate": (
                (tail_spins / total_spins) if total_spins > 0 else None
            ),
        }

    @staticmethod
    def _payid_share(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
        """Per-pid hit-share + win-share for one ST (real pids only — exclude
        "_"-prefixed synthetic buckets). Used for the M3 base-vs-respin mix."""
        real = [
            r for r in (rows or [])
            if not str(r.get("payout_id") or "").startswith("_")
        ]
        total_hits = sum(int(r.get("hit_count") or 0) for r in real)
        total_win = sum(float(r.get("total_win") or 0.0) for r in real)
        out: dict[str, dict[str, float]] = {}
        for r in real:
            pid = str(r.get("payout_id") or "")
            hits = int(r.get("hit_count") or 0)
            win = float(r.get("total_win") or 0.0)
            out[pid] = {
                "hit_count": hits,
                "hit_share": (hits / total_hits) if total_hits > 0 else 0.0,
                "win_share": (win / total_win) if total_win > 0 else 0.0,
            }
        return out

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Compute and write summary["player_impact"]["respin_dynamics"].

        Resolves the respin ST (role=="respin") and base ST (role=="paid_spin")
        from ctx.machine_spec_manifest (no hardcoded ids). If no respin ST is
        declared, writes {applicable: False} and returns.
        """
        player_impact = summary.setdefault("player_impact", {})

        # Hard dependency check (feedback_no_silent_swallow.md): payouts_by_spin_type
        # ALWAYS writes its section when it runs; an ABSENT key means it crashed
        # upstream — surface loudly (the emit loop records it in feature_errors).
        if "payouts_by_spin_type" not in player_impact:
            raise RuntimeError(
                "respin_dynamics requires player_impact['payouts_by_spin_type'] "
                "(REQUIRES dependency) but it is absent at emit time — "
                "PayoutsBySpinType did not run or failed upstream."
            )

        manifest = getattr(ctx, "machine_spec_manifest", None)
        respin_st = _resolve_st_by_role_or_play(manifest, role="respin")
        base_st = _resolve_st_by_role_or_play(manifest, role="paid_spin")

        if respin_st is None:
            # No respin SpinType declared for this machine — nothing to analyze.
            player_impact["respin_dynamics"] = {
                "applicable": False,
                "reason": "no SpinType with role 'respin' in manifest",
            }
            return

        next_counts: dict[str, dict[str, int]] = (final_acc or {}).get("next_counts") or {}
        bucket_spins: dict[str, dict[str, int]] = (final_acc or {}).get("bucket_spins") or {}
        bucket_win: dict[str, dict[str, float]] = (final_acc or {}).get("bucket_win") or {}

        # --- round-level stats from spin_type_breakdown (byte-stable) ---
        stb_rows: list[dict[str, Any]] = player_impact.get("spin_type_breakdown") or []
        stb_by_st: dict[int, dict[str, Any]] = {}
        for row in stb_rows:
            try:
                stb_by_st[int(row.get("spin_type"))] = row
            except (TypeError, ValueError):
                continue
        respin_row = stb_by_st.get(respin_st) or {}
        base_row = stb_by_st.get(base_st) if base_st is not None else {}
        base_row = base_row or {}

        respin_st_s = str(respin_st)
        base_st_s = str(base_st) if base_st is not None else None

        # ── M1 — grant-rate (opener transitions) ──
        # Openers = transitions INTO the respin from ANY source ST except the
        # respin itself (the exclusion drops respin->respin continuations).
        # Topology-aware: a DIRECT base-opener machine (M43 ST1->ST50, M279
        # ST140->ST36) has only the paid base ST transitioning into the respin,
        # so this is BYTE-IDENTICAL to the prior base_st-only count; a
        # BONUS-INTERNAL respin (M182 ST126->ST50, opened from inside the
        # freespin) recovers the true opener count instead of a false 0.
        # Denominators stay the paid base spins (per_paid_spin = respins/paid).
        openers = sum(
            int(row.get(respin_st_s, 0))
            for src_st, row in next_counts.items()
            if src_st != respin_st_s
        )
        base_win_rounds = int(base_row.get("win_rounds") or 0)
        base_spins = int(base_row.get("spins") or 0)
        grant_rate = {
            "openers": openers,
            "per_winning_paid_spin": (
                openers / base_win_rounds if base_win_rounds > 0 else None
            ),
            "per_paid_spin": (
                openers / base_spins if base_spins > 0 else None
            ),
            "one_per_n_paid_spins": (
                base_spins / openers if openers > 0 else None
            ),
        }

        # ── M2 — hit-rate uplift + overlaid multiplier distributions ──
        respin_hit = respin_row.get("hit_rate")
        base_hit = base_row.get("hit_rate")
        hit_rate_uplift = {
            "respin_hit_rate": respin_hit,
            "base_hit_rate": base_hit,
            "uplift_ratio": (
                (float(respin_hit) / float(base_hit))
                if (respin_hit is not None and base_hit not in (None, 0, 0.0))
                else None
            ),
        }
        respin_dist = self._bucket_distribution(
            bucket_spins.get(respin_st_s) or {}, bucket_win.get(respin_st_s) or {}
        )
        base_dist = (
            self._bucket_distribution(
                bucket_spins.get(base_st_s) or {}, bucket_win.get(base_st_s) or {}
            )
            if base_st_s is not None else None
        )

        # ── M3 — skin-premium symbol/payid mix (base vs respin) ──
        pbst: dict[str, list[dict[str, Any]]] = player_impact.get("payouts_by_spin_type") or {}
        # Resolve the per-ST labels (e.g. "ST50_free") used by payouts_by_spin_type.
        respin_label = self._label_for_st(pbst, respin_st)
        base_label = self._label_for_st(pbst, base_st) if base_st is not None else None
        payid_mix = {
            "respin_payid_share": self._payid_share(pbst.get(respin_label) or [])
            if respin_label else {},
            "base_payid_share": self._payid_share(pbst.get(base_label) or [])
            if base_label else {},
            "note": (
                "symbol->multiplier paytable is SHARED with the base game; the "
                "uplift is a shifted symbol/win-frequency MIX on the premium skin, "
                "not a richer paytable. Compare the two payid shares above."
            ),
        }

        # ── M4 — continuity / continuation probability ──
        # P(respin continues) = P(respin_st -> respin_st). Exits go to base/settle.
        respin_out = next_counts.get(respin_st_s) or {}
        respin_out_total = sum(int(v) for v in respin_out.values())
        respin_self = int(respin_out.get(respin_st_s, 0))
        continuity = {
            "continuation_prob": (
                respin_self / respin_out_total if respin_out_total > 0 else None
            ),
            "respin_to_respin_transitions": respin_self,
            "respin_exit_transitions": respin_out_total,
            "exit_breakdown": {str(k): int(v) for k, v in respin_out.items()},
            "parser_blind": [
                "burst_length_histogram (len1/len2/len3 run-length distribution)",
                "win_gating_proof (len>=2 bursts are 100% win-bursts; avg "
                "multiplier per burst-length)",
            ],
            "parser_blind_reason": (
                "consecutive-respin run-length + per-run win outcome require "
                "per-round run-length accumulation in parser.py (a base-closure "
                "file). Only the aggregate respin->respin transition COUNT is "
                "exposed base-excluded, which gives the continuation probability "
                "but not the burst-length shape. Escalated to the framework team."
            ),
        }

        # ── M5 — RTP-concentration / share + fat-tail shape ──
        rtp_share = {
            "respin_rtp_contribution_pp": respin_row.get("rtp_contribution_pp"),
            "share_of_all_win": (
                self._share_of_total_win(respin_row, stb_rows)
            ),
            "fat_tail_ge20x_win_share": respin_dist.get("tail_ge20x_win_share"),
            "loss_rate": (
                self._loss_rate(bucket_spins.get(respin_st_s) or {})
            ),
            "note": (
                "the respin is a small-frequency, fat-tailed bonus — mostly small "
                "or zero, occasionally a 20-300x pop (see fat_tail_ge20x_win_share)."
            ),
        }

        player_impact["respin_dynamics"] = {
            "applicable": True,
            "respin_spin_type": respin_st,
            "base_spin_type": base_st,
            "grant_rate": grant_rate,
            "hit_rate_uplift": hit_rate_uplift,
            "respin_multiplier_distribution": respin_dist,
            "base_multiplier_distribution": base_dist,
            "payid_mix": payid_mix,
            "continuity": continuity,
            "rtp_concentration": rtp_share,
        }

    @staticmethod
    def _label_for_st(
        pbst: dict[str, list[dict[str, Any]]], st_int: int | None
    ) -> str | None:
        """Find the payouts_by_spin_type label (e.g. "ST50_free") for an ST int."""
        if st_int is None:
            return None
        prefix = f"ST{st_int}_"
        for label in pbst:
            if label.startswith(prefix):
                return label
        return None

    @staticmethod
    def _share_of_total_win(
        st_row: dict[str, Any], stb_rows: list[dict[str, Any]]
    ) -> float | None:
        """This ST's total_win as a share of all STs' total_win."""
        st_win = float(st_row.get("total_win") or 0.0)
        all_win = sum(float(r.get("total_win") or 0.0) for r in stb_rows)
        return (st_win / all_win) if all_win > 0 else None

    @staticmethod
    def _loss_rate(bucket_spins: dict[str, int]) -> float | None:
        """Share of this ST's rounds that won nothing (the eq0 band)."""
        total = sum(int(v) for v in bucket_spins.values())
        zero = int(bucket_spins.get("eq0", 0))
        return (zero / total) if total > 0 else None


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# Auto-discovered by feature_registry.discover_features() (globs features/*.py).
# ---------------------------------------------------------------------------
register(RespinDynamics())
