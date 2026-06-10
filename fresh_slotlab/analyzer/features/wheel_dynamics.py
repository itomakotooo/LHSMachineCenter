"""AnalyzerFeature: wheel_dynamics — the Wheel (st2) collect-settlement MECHANIC view.

M279 onboarding (Wave 4). st2 has no reels/cost and no round-level PayoutId; its
whole win is attributed to a single real pid `st2` by the config-only
SynthesizePayIdRule (configs/machine_round_win_rules.json: m279_wheel_settlement)
so the RTP-integrity gate passes (_unattributed_st2 -> 0). This feature quantifies
the WHEEL MECHANIC's felt experience as rates / multipliers / probabilities /
shares (money-agnostic; NO coin totals).

What the player feels (design 03_design.md §ST2 "What the player FEELS at the
wheel"): every 1000th paid spin a guaranteed prize wheel fires and ALWAYS pays —
a scheduled lottery that resolves into a certain pop, possibly the 100x jackpot
cell. Three distinct feelings, each made a number:

  1. A guaranteed, scheduled payout (hit-rate 1.0 + deterministic cadence).
  2. A prize-tier lottery (the discrete-prize probability / win-share shape).
  3. The 100x jackpot-cell chance (the 12-cell landing map; cells 8 & 10 = 100x).

Mechanic metrics (design W1-W4)
-------------------------------
- W1 guaranteed-payout / cadence ⭐: the felt "certain scheduled reward." hit_rate
    (1.0, from spin_type_breakdown — the server Wheel has NO -1/loss tier),
    one_per_n_paid_spins (= base_spins / wheel_events ~ 1000, the metronome period),
    events. Signal: spin_type_breakdown[ST2] + the base count.
- W2 discrete prize-tier distribution ⭐ (the lottery): the wheel's OWN prize
    taxonomy as {multiplier, prob, win_share}. The 6 raw prizes are 5x/10x/20x/30x/
    50x/100x (W1 CROSS-4). DATA BOUNDARY: the only win-keyed per-ST data the frozen
    parser hands a base-excluded plugin is the COARSE RETURN_BUCKET_ORDER histogram
    (spin_type_bucket_{spins,win}), whose boundaries are .../10/20/50/100/...; the
    20x AND 30x prizes BOTH fall in the single `ge20_lt50` band and are merged
    irrecoverably (verified on the real cached chunks: ge20_lt50 = 20x + 30x, e.g.
    chunk_0001 = 7 + 4 events in one band). So the BAND-level distribution (5 bands)
    is base-derivable here; band -> prize-multiplier labels are exact for every band
    EXCEPT `ge20_lt50` (the 20x/30x collision). The exact 6-prize un-merge needs a
    per-round WinCredits-value tally that lives ONLY in parser.py (a base-closure
    file) — flagged `parser_blind`, never fabricated.
- W3 12-cell map + jackpot-cell probability ⭐ (the jackpot chance): the per-cell
    landing distribution {cell: prob} + P(jackpot cell 8|10) + the fixed cell->prize
    map (cells 8,10 = 100x). NEEDS the per-round ReMarks="WheelSpin CellIndex <n>;
    WheelId 1;" cell index — NOT accumulated by parser.py (it keeps only 3 sample
    ReMarks strings per SpinType, not a CellIndex distribution). Flagged
    `parser_blind` (same boundary M43's minigame node-list G4/G5 declared).
- W4 RTP-concentration: the felt "a rare guaranteed event carrying a few % of
    payback." wheel_rtp_contribution_pp, share_of_all_win (W1 §9: Wheel
    76,780,000 of 1,769,595,050 ~ 4.34%), event_rate (~0.09%). Signal:
    spin_type_breakdown.

Data path (all base-EXCLUDED — no parser/closure dependency)
------------------------------------------------------------
extract() reads one PER-CHUNK accumulator the parser already emits in the chunk
dict (rec) — accumulated OURSELVES (no stash-ordering dependency):

  chunk_dict["spin_type_bucket_spins" | "spin_type_bucket_win"]
      {str(st): {return_bucket_label: value}} — per-ST win/bet multiplier-band
      histogram over ALL rounds. For st2 the bet defaults to the run bet (1000;
      st2 carries NO BetAmount), so the bands are meaningful multipliers (W2).
      "eq0" is the zero-win band (the wheel pays on 100% of rounds, so it is
      empty here — the guaranteed-payout signal).

emit() additionally reads the byte-stable summary["player_impact"]["spin_type_breakdown"]
(per-ST round-level stats) for W1/W4 (spins, win_rounds, hit_rate, total_win,
rtp_contribution_pp).

RTP_CONTRIBUTION = False
  The wheel win is already attributed (to pid `st2`) by the synth rule +
  PER_SPINTYPE plugins. This feature re-presents it; it adds NOTHING to the RTP
  sum; sum(pay_id.rtp_pp)==summary.rtp is unaffected
  (feedback_aggregator_parity_invariant.md).

Per-machine isolation
---------------------
NOT in fresh_slotlab/analyzer/core/ and NOT in versioning._CLOSURE_FILES — base-
EXCLUDED (R-4). Auto-discovered via feature_registry.discover_features(). Editing
it re-flags ONLY machines declaring "wheel_dynamics" (via play "Wheel" in
machine_spec.PLAY_ANALYSES — NOT the shared `settlement` role, so it does NOT fire
on M15's TopDollar settlement or M43's WinMiniGame settlement).

Memory feedback honored
-----------------------
- feedback_no_hardcode.md: the wheel ST is resolved from the manifest's spin_types
  (play "Wheel"), NOT hardcoded "2".
- feedback_no_silent_swallow.md: a missing spin_type_breakdown section RAISES.
  The 6-prize un-merge (20x/30x) and the CellIndex landing map that the frozen
  framework cannot expose are surfaced EXPLICITLY in `parser_blind` — never
  fabricated as zeros or invented splits.
- feedback_invariant_with_fallback_hides_drift.md: no catch-all bucket; rates with
  a zero denominator are null, not a "0.0 with 0 denominator" lie.
- feedback_no_parallel_panel_impl.md: mirrors minigame_dynamics / spin_type_rtp_buckets
  / spin_type_outcomes pattern (extract/reduce/emit, ClassVar layout, dual-path
  import, register()); reuses RETURN_BUCKET_ORDER.
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


# Exact prize-multiplier label for each RETURN_BUCKET band the wheel lands in.
# The wheel pays one of 6 discrete prizes (5/10/20/30/50/100x bet; W1 CROSS-4).
# Mapping each prize onto RETURN_BUCKET_ORDER (boundaries .../10/20/50/100/...):
#   5x   -> ge5_lt10      10x  -> ge10_lt20
#   20x  -> ge20_lt50  ┐  30x  -> ge20_lt50  ┘  ← SAME band (the 20x/30x collision)
#   50x  -> ge50_lt100    100x -> ge100_lt200
# Every band below maps to exactly ONE prize EXCEPT `ge20_lt50`, which merges the
# 20x and 30x prizes (the parser's coarse banding cannot separate them — the exact
# split needs a per-round WinCredits-value tally in parser.py, a base-closure file).
_BAND_TO_PRIZE_MULT: dict[str, int] = {
    "ge5_lt10": 5,
    "ge10_lt20": 10,
    "ge50_lt100": 50,
    "ge100_lt200": 100,
}
# The single band that the frozen banding cannot un-merge.
_MERGED_BAND: str = "ge20_lt50"
_MERGED_BAND_PRIZES: tuple[int, ...] = (20, 30)

# The jackpot prize multiplier (top cell). Cells 8 & 10 land it (W1 CROSS-5).
_JACKPOT_PRIZE_MULT: int = 100
_JACKPOT_CELLS: tuple[int, ...] = (8, 10)
_WHEEL_CELL_COUNT: int = 12


def _merge_nested_counts(
    prev: dict[str, dict[str, float]],
    this: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Additively merge two {outer: {inner: number}} dicts."""
    out: dict[str, dict[str, float]] = {}
    for okey, imap in prev.items():
        out[okey] = dict(imap)
    for okey, imap in this.items():
        dest = out.setdefault(okey, {})
        for ikey, val in imap.items():
            dest[ikey] = dest.get(ikey, 0) + val
    return out


def _resolve_st_by_play(manifest: dict[str, Any] | None, play: str) -> int | None:
    """Return the first SpinType int whose spec.play == play. None if no match.

    No hardcoded ids (feedback_no_hardcode.md): the wheel ST is identified by its
    rawdata feature name (play), read from ctx.machine_spec_manifest.
    """
    if not isinstance(manifest, dict):
        return None
    for st_key, spec in (manifest.get("spin_types") or {}).items():
        if isinstance(spec, dict) and str(spec.get("play", "")) == play:
            try:
                return int(st_key)
            except (TypeError, ValueError):
                continue
    return None


def _resolve_st_by_role(manifest: dict[str, Any] | None, role: str) -> int | None:
    """Return the first SpinType int whose spec.role == role. None if no match."""
    if not isinstance(manifest, dict):
        return None
    for st_key, spec in (manifest.get("spin_types") or {}).items():
        if isinstance(spec, dict) and str(spec.get("role", "")) == role:
            try:
                return int(st_key)
            except (TypeError, ValueError):
                continue
    return None


class WheelDynamics(AnalyzerFeature):
    """Pattern-B plugin: accumulate the per-ST bucket histogram per chunk; compute
    the wheel-mechanic metrics in emit() (reading the byte-stable
    spin_type_breakdown section too).

    Accumulator structure
    ---------------------
      bucket_spins / bucket_win: dict[str, dict[str, number]] — per-ST bands.
    """

    FEATURE_ID: ClassVar[str] = "wheel_dynamics"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("wheel_dynamics",)
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False  # win already attributed via synth rule
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    # We read spin_type_breakdown in emit(); payouts_by_spin_type guarantees it is
    # present (it requires spin_type_breakdown, written by the inline F1 block).
    REQUIRES: ClassVar[tuple[str, ...]] = ("payouts_by_spin_type",)
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Lift the per-chunk per-ST bucket histograms."""
        if not chunk_dict or not isinstance(chunk_dict, dict):
            return {"bucket_spins": {}, "bucket_win": {}}

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
            "bucket_spins": _coerce_nested(
                chunk_dict.get("spin_type_bucket_spins"), as_int=True
            ),
            "bucket_win": _coerce_nested(
                chunk_dict.get("spin_type_bucket_win"), as_int=False
            ),
        }

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Additively merge bucket tallies across chunks."""
        if not prev_acc:
            return this_acc if this_acc else {"bucket_spins": {}, "bucket_win": {}}
        if not this_acc:
            return prev_acc
        return {
            "bucket_spins": _merge_nested_counts(
                prev_acc.get("bucket_spins") or {}, this_acc.get("bucket_spins") or {}
            ),
            "bucket_win": _merge_nested_counts(
                prev_acc.get("bucket_win") or {}, this_acc.get("bucket_win") or {}
            ),
        }

    @staticmethod
    def _prize_distribution(
        bucket_spins: dict[str, int],
        bucket_win: dict[str, float],
    ) -> dict[str, Any]:
        """Money-agnostic discrete-prize distribution for the wheel.

        The wheel's 6 raw prizes (5/10/20/30/50/100x) banded by RETURN_BUCKET_ORDER.
        Every band maps to exactly ONE prize multiplier EXCEPT `ge20_lt50`, which
        merges 20x + 30x (the frozen banding cannot separate them — see the
        `parser_blind` note returned by emit()).

        Returns {bands:[{band, prize_multiplier|prize_multipliers_merged, spin_count,
        prob, win_share}], total_events, modal_band, dominant_band_share,
        band_count, distinct_prize_count, merged_band_present, source}. prob /
        win_share over ALL wheel events.
        """
        total_spins = sum(int(v) for v in bucket_spins.values())
        total_win = sum(float(v) for v in bucket_win.values())
        bands: list[dict[str, Any]] = []
        modal_band: str | None = None
        modal_count = -1
        merged_band_present = False
        for band in RETURN_BUCKET_ORDER:
            sc = int(bucket_spins.get(band, 0))
            bw = float(bucket_win.get(band, 0.0))
            if sc == 0 and bw == 0.0:
                continue
            row: dict[str, Any] = {
                "band": band,
                "spin_count": sc,
                "prob": (sc / total_spins) if total_spins > 0 else None,
                "win_share": (bw / total_win) if total_win > 0 else None,
            }
            if band == _MERGED_BAND:
                merged_band_present = True
                # Honest: this band carries TWO prizes the parser merged.
                row["prize_multipliers_merged"] = list(_MERGED_BAND_PRIZES)
                row["unmerge_blind"] = True
            elif band in _BAND_TO_PRIZE_MULT:
                row["prize_multiplier"] = _BAND_TO_PRIZE_MULT[band]
            else:
                # A band outside the known 6-prize ladder — surface it, do NOT
                # silently relabel (feedback_no_silent_swallow.md). Real data has
                # never produced one (the wheel is a fixed 6-prize ladder), but if
                # it ever appears it is a signal, not a residual.
                row["prize_multiplier"] = None
                row["unexpected_band"] = True
            bands.append(row)
            if sc > modal_count:
                modal_count = sc
                modal_band = band
        # Distinct prizes the BANDS can resolve = one per non-merged band, plus the
        # two prizes hidden inside the merged band (which the bands cannot split).
        distinct_prize_count = sum(
            1 for b in bands if b.get("band") != _MERGED_BAND
        ) + (len(_MERGED_BAND_PRIZES) if merged_band_present else 0)
        return {
            "total_events": total_spins,
            "bands": bands,
            "band_count": len(bands),
            "distinct_prize_count": distinct_prize_count,
            "merged_band_present": merged_band_present,
            "modal_band": modal_band,
            "dominant_band_share": (
                (modal_count / total_spins)
                if (total_spins > 0 and modal_count > 0) else None
            ),
            "source": (
                "our win/bet banding (RETURN_BUCKET_ORDER). The wheel pays one of 6 "
                "discrete prizes (5/10/20/30/50/100x); each RETURN_BUCKET band maps "
                "to exactly one prize EXCEPT ge20_lt50, which MERGES 20x + 30x. The "
                "band-level distribution is exact; the 20x/30x un-merge is "
                "parser_blind (see parser_blind below)."
            ),
        }

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Compute and write summary["player_impact"]["wheel_dynamics"]."""
        player_impact = summary.setdefault("player_impact", {})

        # Hard dependency check (feedback_no_silent_swallow.md).
        if "spin_type_breakdown" not in player_impact:
            raise RuntimeError(
                "wheel_dynamics requires player_impact['spin_type_breakdown'] "
                "but it is absent at emit time — the inline F1 block / "
                "PayoutsBySpinType did not run or failed upstream."
            )

        manifest = getattr(ctx, "machine_spec_manifest", None)
        wheel_st = _resolve_st_by_play(manifest, "Wheel")
        base_st = _resolve_st_by_role(manifest, "paid_spin")

        if wheel_st is None:
            player_impact["wheel_dynamics"] = {
                "applicable": False,
                "reason": "no SpinType with play 'Wheel' in manifest",
            }
            return

        bucket_spins: dict[str, dict[str, int]] = (final_acc or {}).get("bucket_spins") or {}
        bucket_win: dict[str, dict[str, float]] = (final_acc or {}).get("bucket_win") or {}

        stb_rows: list[dict[str, Any]] = player_impact.get("spin_type_breakdown") or []
        stb_by_st: dict[int, dict[str, Any]] = {}
        for row in stb_rows:
            try:
                stb_by_st[int(row.get("spin_type"))] = row
            except (TypeError, ValueError):
                continue
        wheel_row = stb_by_st.get(wheel_st) or {}
        base_row = stb_by_st.get(base_st) if base_st is not None else {}
        base_row = base_row or {}

        wheel_st_s = str(wheel_st)

        # ── W1 — guaranteed-payout / cadence (the certain scheduled reward) ──
        wheel_events = int(wheel_row.get("spins") or 0)
        wheel_win_rounds = int(wheel_row.get("win_rounds") or 0)
        base_spins = int(base_row.get("spins") or 0)
        guaranteed_payout = {
            "hit_rate": wheel_row.get("hit_rate"),
            "win_rounds": wheel_win_rounds,
            "events": wheel_events,
            "guaranteed": (
                (wheel_win_rounds == wheel_events and wheel_events > 0)
            ),
            "one_per_n_paid_spins": (
                base_spins / wheel_events if wheel_events > 0 else None
            ),
            "cadence_note": (
                "the wheel is a deterministic metronome: it fires every ~1000th "
                "paid spin (the CollectCount cycle peak) and ALWAYS pays (the "
                "server Wheel has no loss tier — hit_rate 1.0). This is the one "
                "certain reward, the opposite of the base-game grind."
            ),
        }

        # ── W2 — discrete prize-tier distribution (the lottery) ──
        prize_distribution = self._prize_distribution(
            bucket_spins.get(wheel_st_s) or {}, bucket_win.get(wheel_st_s) or {}
        )
        prize_distribution["parser_blind"] = [
            "exact_6_prize_unmerge (the 20x vs 30x split that RETURN_BUCKET's "
            "ge20_lt50 band MERGES into one band)",
        ]
        prize_distribution["parser_blind_reason"] = (
            "the only win-keyed per-ST data the frozen parser hands a base-excluded "
            "plugin is the COARSE RETURN_BUCKET_ORDER histogram "
            "(spin_type_bucket_{spins,win}), whose boundaries (.../10/20/50/100/...) "
            "place the 20x AND 30x prizes in the SAME ge20_lt50 band (verified on the "
            "real cached chunks). Separating them needs a per-round WinCredits-value "
            "tally in parser.py (a base-closure file). The BAND-level distribution "
            "(5 bands) and the 100% guaranteed hit-rate ARE base-derivable today; the "
            "exact 6-prize un-merge is the honest parser boundary (same boundary M43's "
            "minigame declared). Escalated to the framework team."
        )

        # ── W3 — 12-cell landing map + jackpot-cell probability (parser-blind) ──
        cell_map = {
            "available": False,
            "wheel_cell_count": _WHEEL_CELL_COUNT,
            "jackpot_cells": list(_JACKPOT_CELLS),
            "jackpot_prize_multiplier": _JACKPOT_PRIZE_MULT,
            "parser_blind": [
                "per_cell_landing_distribution ({cell_index: prob} over the 12 cells)",
                "jackpot_cell_probability (P(land cell 8 or 10) = the 100x chance)",
                "cell_to_prize_map (the fixed cell->prize ladder; cells 8 & 10 = 100x)",
            ],
            "parser_blind_reason": (
                "the per-round ReMarks='WheelSpin CellIndex <n>; WheelId 1;' cell "
                "index is NOT accumulated by parser.py (it keeps only 3 sample "
                "ReMarks strings per SpinType, not a CellIndex distribution). "
                "Computing the per-cell landing map / jackpot-cell probability / "
                "cell->prize ladder needs a new per-round ReMarks CellIndex "
                "accumulator in parser.py (a base-closure file). The 12-cell / "
                "cells-8&10-are-100x structure (W1 CROSS-5) is recorded above as the "
                "known fixed shape, but the in-sample landing FREQUENCIES are not "
                "framework-derivable without the parser accumulator. Escalated to the "
                "framework team (same boundary as M43's minigame node-list G4/G5)."
            ),
        }

        # ── W4 — RTP-concentration (a rare guaranteed event, a few % of payback) ──
        all_win = sum(float(r.get("total_win") or 0.0) for r in stb_rows)
        wheel_win = float(wheel_row.get("total_win") or 0.0)
        total_spins_all = sum(int(r.get("spins") or 0) for r in stb_rows)
        rtp_concentration = {
            "wheel_rtp_contribution_pp": wheel_row.get("rtp_contribution_pp"),
            "share_of_all_win": (wheel_win / all_win) if all_win > 0 else None,
            "event_rate": (
                wheel_events / total_spins_all if total_spins_all > 0 else None
            ),
            "hit_rate": wheel_row.get("hit_rate"),
            "note": (
                "the rarest ~0.09% of outcomes (the wheel) carries a few % of all "
                "payback as a GUARANTEED pop — a rare-but-certain event. Compare "
                "event_rate to share_of_all_win for the concentration ratio."
            ),
        }

        player_impact["wheel_dynamics"] = {
            "applicable": True,
            "wheel_spin_type": wheel_st,
            "attributed_pay_id": f"st{wheel_st}",
            "guaranteed_payout": guaranteed_payout,
            "prize_distribution": prize_distribution,
            "cell_map": cell_map,
            "rtp_concentration": rtp_concentration,
        }


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# Auto-discovered by feature_registry.discover_features() (globs features/*.py).
# ---------------------------------------------------------------------------
register(WheelDynamics())
