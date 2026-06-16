"""AnalyzerFeature: wheel_dynamics — the Wheel (st2) collect-settlement MECHANIC view.

M279 onboarding (Wave 4), generalized M283 + wheel_cells extractor (Wave 3+). st2
has no reels/cost and no round-level PayoutId; its whole win is attributed to a
single real pid `st2` by the config-only SynthesizePayIdRule
(configs/machine_round_win_rules.json: m279_wheel_settlement / m283_wheel_settlement)
so the RTP-integrity gate passes (_unattributed_st2 -> 0). This feature quantifies
the WHEEL MECHANIC's felt experience as rates / multipliers / probabilities /
shares (money-agnostic; NO coin totals).

What the player feels (design 03_design.md §ST2 "What the player FEELS at the
wheel"): every 1000th paid spin a guaranteed prize wheel fires and ALWAYS pays —
a scheduled lottery that resolves into a certain pop, possibly the jackpot cell.
Three distinct feelings, each made a number:

  1. A guaranteed, scheduled payout (hit-rate 1.0 + deterministic cadence).
  2. A prize-tier lottery (the discrete-prize probability / win-share shape).
  3. The jackpot-cell chance (the 12-cell landing map; M279 cells 8 & 10 = 100x,
     M283 cell 10 = 200x).

Mechanic metrics (design W1-W4)
-------------------------------
- W1 guaranteed-payout / cadence: hit_rate (1.0, from spin_type_breakdown — the
    server Wheel has NO -1/loss tier), one_per_n_paid_spins (= base_spins /
    wheel_events ~ 1000, the metronome period), events.
- W2 discrete prize-tier distribution (the lottery): the wheel's OWN prize
    taxonomy as {prize_multiplier, prob, hit_count, win_share}. EXACT, DATA-DERIVED
    per machine from the wheel_cells extractor's per-round CellIndex->WinCredits
    accumulation — NOT a hardcoded ladder (feedback_no_hardcode.md) and NO LONGER
    a coarse RETURN_BUCKET banding that merged the 20x/30x prizes. For M279 this
    RESTORES the 6 distinct prizes (incl. 30x @ cell 5) as a REAL data-derived
    value; for M283 it gives 6 distinct prizes incl. the 200x jackpot tier and
    correctly omits a fabricated 30x.
- W3 wheel cell map + jackpot (the jackpot chance): the EXACT 12-cell landing
    distribution {cell: {prize_multiplier, hit_count, hit_prob}}, the jackpot
    cell(s) IDENTITY and prize multiplier, all DATA-DERIVED from the wheel_cells
    extractor. An UNOBSERVED cell (M283 cell 7, n=0) is reported honestly with
    prize_multiplier null + observed:false, NEVER fabricated
    (feedback_invariant_with_fallback_hides_drift.md). A cell ever seen paying
    >1 distinct prize is surfaced as a DATA ALARM (nondeterministic_cells), never
    silently resolved.
- W4 RTP-concentration: the felt "a rare guaranteed event carrying a few % of
    payback." wheel_rtp_contribution_pp, share_of_all_win, event_rate. Signal:
    spin_type_breakdown.

Data path (all base-EXCLUDED — no parser/closure dependency)
------------------------------------------------------------
extract() reads per-chunk accumulators the parser already emits in the chunk
dict (rec) — accumulated OURSELVES (no stash-ordering dependency):

  chunk_dict["st_extract"]["wheel_cells"]
      {str(st): {cell_map, observed_cells, cell_count, unobserved_cells,
      distinct_prizes, jackpot, total_wheel_spins, nondeterministic_cells,
      skipped_rounds}} — the per-ST extraction layer's wheel cell-index
      extractor output (st_extract/wheel_cells.py, declared by the manifest's
      spin_types["<st>"].wheel_cells block). The EXACT cell map + distinct-prize
      distribution (W2 + W3). Key is absent on chunks parsed without extractors
      or on machines without the wheel_cells block — a legitimate state (the
      feature then degrades gracefully, reporting source unavailable, never
      fabricating).
  chunk_dict["st_extract"]["_extract_error_wheel_cells"]
      surfaced extractor errors — collected and re-surfaced (never dropped,
      feedback_no_silent_swallow.md).

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
on M15's TopDollar settlement or M43's WinMiniGame settlement). The wheel_cells
extractor it consumes is likewise base-excluded (st_extract/wheel_cells.py).

Memory feedback honored
-----------------------
- feedback_no_hardcode.md: the wheel ST is resolved from the manifest's spin_types
  (play "Wheel"), NOT hardcoded "2". The cell->prize map / band labels / jackpot
  are DATA-DERIVED from the wheel_cells extractor, NOT hardcoded constants (the
  prior interim _BAND_TO_PRIZE_MULT / merged_avg_multiplier de-hardcode is now
  fully removed in favor of the exact extractor map).
- feedback_no_silent_swallow.md: a missing spin_type_breakdown section RAISES.
  The cell map degrades gracefully when the extractor is absent (available:false
  with a reason), and surfaces extractor errors + nondeterministic-cell alarms.
- feedback_invariant_with_fallback_hides_drift.md: no catch-all bucket; an
  unobserved cell is null+observed:false (not a fabricated value); rates with a
  zero denominator are null, not a "0.0 with 0 denominator" lie.
- feedback_no_parallel_panel_impl.md: mirrors freespin_dynamics' consumption of
  the st_extract layer (reads rec["st_extract"][<EXTRACTOR_ID>], merges across
  chunks, surfaces errors), and minigame_dynamics' emit shape.
- feedback_subprocess_import_suicide_and_module_globals.md: register() is a pure
  list-append; no I/O at import time.
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


# The extractor id whose chunk output W2/W3 consume (st_extract/wheel_cells.py).
_WHEEL_CELLS_EXTRACTOR_ID: str = "wheel_cells"


def _merge_cell_maps(prev: dict[str, Any], this: dict[str, Any]) -> dict[str, Any]:
    """Merge two wheel_cells extractor outputs across chunks.

    Shape: {st_str: {cell_map, observed_cells, cell_count, unobserved_cells,
    distinct_prizes, jackpot, total_wheel_spins, nondeterministic_cells,
    skipped_rounds}}.

    Per-cell hit_count / total_wheel_spins / skipped_rounds are additive.
    The cell->prize_multiplier is a DETERMINISTIC structural fact (the same in
    every chunk); we keep the singleton but ESCALATE to a nondeterministic-cell
    ALARM if two chunks ever disagree on a cell's prize
    (feedback_invariant_with_fallback_hides_drift.md — drift must be a signal,
    never silently merged). hit_prob is recomputed at emit() from the merged
    totals, so it is NOT merged here.
    """
    out: dict[str, Any] = {}
    all_sts = set(prev) | set(this)
    for st in all_sts:
        pa = prev.get(st) or {}
        pb = this.get(st) or {}

        # Merge per-cell hit_count + reconcile prize_multiplier.
        cm_a: dict[str, Any] = pa.get("cell_map") or {}
        cm_b: dict[str, Any] = pb.get("cell_map") or {}
        nd: dict[str, Any] = {}
        for k, v in (pa.get("nondeterministic_cells") or {}).items():
            nd[str(k)] = list(v)
        for k, v in (pb.get("nondeterministic_cells") or {}).items():
            nd[str(k)] = sorted(set(nd.get(str(k), [])) | set(v))

        merged_cm: dict[str, Any] = {}
        all_cells = set(cm_a) | set(cm_b)
        for cell in all_cells:
            ea = cm_a.get(cell) or {}
            eb = cm_b.get(cell) or {}
            hits = int(ea.get("hit_count", 0)) + int(eb.get("hit_count", 0))
            pa_mult = ea.get("prize_multiplier")
            pb_mult = eb.get("prize_multiplier")
            # Reconcile the singleton prize. None means "unobserved/alarmed in
            # that chunk"; a real value from either chunk wins. Two DIFFERENT
            # real values is a drift ALARM.
            observed_mults = {m for m in (pa_mult, pb_mult) if m is not None}
            if len(observed_mults) == 0:
                prize = None
            elif len(observed_mults) == 1:
                prize = next(iter(observed_mults))
            else:
                prize = None
                nd[str(cell)] = sorted(set(nd.get(str(cell), [])) | observed_mults)
            merged_cm[str(cell)] = {
                "prize_multiplier": prize,
                "hit_count": hits,
                # hit_prob recomputed at emit() from merged totals.
                "hit_prob": None,
            }

        total = int(pa.get("total_wheel_spins", 0)) + int(pb.get("total_wheel_spins", 0))
        skipped = int(pa.get("skipped_rounds", 0)) + int(pb.get("skipped_rounds", 0))
        # cell_count: declared, identical across chunks; take the max (defensive).
        cell_count = max(int(pa.get("cell_count", 0)), int(pb.get("cell_count", 0)))

        out[str(st)] = {
            "cell_map": merged_cm,
            "cell_count": cell_count,
            "total_wheel_spins": total,
            "skipped_rounds": skipped,
            "nondeterministic_cells": nd,
        }
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
    """Pattern-B plugin: accumulate the per-ST wheel_cells extractor output per
    chunk; compute the wheel-mechanic metrics in emit() (reading the byte-stable
    spin_type_breakdown section too).

    Accumulator structure
    ---------------------
      cell_data: dict[str, Any]
          {st: {cell_map, cell_count, total_wheel_spins, skipped_rounds,
          nondeterministic_cells}} from rec["st_extract"]["wheel_cells"],
          merged across chunks.
      cell_errors: list[str]
          surfaced _extract_error_wheel_cells entries (never dropped).
      chunks_with_extract / chunks_total: int
          coverage counters — reports honestly when some chunks were parsed
          without the extractor (e.g. a caller bypassing the extractor wiring).
    """

    FEATURE_ID: ClassVar[str] = "wheel_dynamics"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("wheel_dynamics",)
    SCHEMA_VERSION: ClassVar[int] = 2
    RTP_CONTRIBUTION: ClassVar[bool] = False  # win already attributed via synth rule
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    # We read spin_type_breakdown in emit(); payouts_by_spin_type guarantees it is
    # present (it requires spin_type_breakdown, written by the inline F1 block).
    REQUIRES: ClassVar[tuple[str, ...]] = ("payouts_by_spin_type",)
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Lift the per-chunk wheel_cells extractor output.

        Absence of the OPTIONAL extractor (old cached records / machine without
        a wheel_cells block) is a legitimate state, not an error — coverage is
        tracked and reported (feedback_no_silent_swallow.md: extractor ERRORS,
        by contrast, are collected and re-surfaced).
        """
        empty = {
            "cell_data": {}, "cell_errors": [],
            "chunks_with_extract": 0, "chunks_total": 0,
        }
        if not chunk_dict or not isinstance(chunk_dict, dict):
            return empty

        st_extract = chunk_dict.get("st_extract")
        cell_data: dict[str, Any] = {}
        cell_errors: list[str] = []
        chunks_with_extract = 0

        if isinstance(st_extract, dict):
            wc_raw = st_extract.get(_WHEEL_CELLS_EXTRACTOR_ID)
            if isinstance(wc_raw, dict):
                chunks_with_extract = 1
                for st_key, payload in wc_raw.items():
                    if not str(st_key).isdigit():
                        continue
                    if not isinstance(payload, dict):
                        continue
                    cm_in = payload.get("cell_map") or {}
                    cm_out: dict[str, Any] = {}
                    for cell, entry in cm_in.items():
                        if not isinstance(entry, dict):
                            continue
                        cm_out[str(cell)] = {
                            "prize_multiplier": entry.get("prize_multiplier"),
                            "hit_count": int(entry.get("hit_count") or 0),
                            "hit_prob": None,  # recomputed at emit()
                        }
                    cell_data[str(st_key)] = {
                        "cell_map": cm_out,
                        "cell_count": int(payload.get("cell_count") or 0),
                        "total_wheel_spins": int(payload.get("total_wheel_spins") or 0),
                        "skipped_rounds": int(payload.get("skipped_rounds") or 0),
                        "nondeterministic_cells": {
                            str(k): list(v)
                            for k, v in (payload.get("nondeterministic_cells") or {}).items()
                        },
                    }
            err = st_extract.get(f"_extract_error_{_WHEEL_CELLS_EXTRACTOR_ID}")
            if err:
                cell_errors.append(str(err))

        return {
            "cell_data": cell_data,
            "cell_errors": cell_errors,
            "chunks_with_extract": chunks_with_extract,
            "chunks_total": 1,
        }

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Additively merge wheel_cells data across chunks."""
        empty = {
            "cell_data": {}, "cell_errors": [],
            "chunks_with_extract": 0, "chunks_total": 0,
        }
        if not prev_acc:
            return this_acc if this_acc else empty
        if not this_acc:
            return prev_acc
        return {
            "cell_data": _merge_cell_maps(
                prev_acc.get("cell_data") or {}, this_acc.get("cell_data") or {}
            ),
            "cell_errors": (
                list(prev_acc.get("cell_errors") or [])
                + list(this_acc.get("cell_errors") or [])
            ),
            "chunks_with_extract": (
                int(prev_acc.get("chunks_with_extract") or 0)
                + int(this_acc.get("chunks_with_extract") or 0)
            ),
            "chunks_total": (
                int(prev_acc.get("chunks_total") or 0)
                + int(this_acc.get("chunks_total") or 0)
            ),
        }

    @staticmethod
    def _build_cell_map(
        st_payload: dict[str, Any],
        errors: list[str],
        chunks_with_extract: int,
        chunks_total: int,
    ) -> dict[str, Any]:
        """Build the EXACT 12-cell wheel map from the merged wheel_cells data.

        Money-agnostic: per cell {prize_multiplier, observed, hit_count,
        hit_prob}. Unobserved cells -> {prize_multiplier: null, observed: false}
        (HONEST, never fabricated). hit_prob recomputed from the merged
        total_wheel_spins. nondeterministic cells surfaced as a DATA ALARM.

        Returns available:false (with a reason) when no extractor data is present
        — the feature degrades gracefully, it does not fabricate the wheel face.
        """
        if not st_payload:
            return {
                "available": False,
                "reason": (
                    "no st_extract.wheel_cells data in the parsed chunks "
                    f"({chunks_with_extract}/{chunks_total} chunks carried the "
                    "extractor output). The manifest declares wheel_cells on the "
                    "wheel ST; the per-ST extraction layer resolves it at parse "
                    "time — a caller that bypasses report_engine's extractor "
                    "wiring, or a machine without the wheel_cells block, produces "
                    "records without it."
                ),
                "extraction_errors": errors,
            }

        cm_raw: dict[str, Any] = st_payload.get("cell_map") or {}
        total = int(st_payload.get("total_wheel_spins") or 0)
        cell_count = int(st_payload.get("cell_count") or 0)
        if cell_count <= 0 and cm_raw:
            cell_count = max(int(c) for c in cm_raw)
        nondeterministic = st_payload.get("nondeterministic_cells") or {}

        cells_out: list[dict[str, Any]] = []
        observed_cells: list[int] = []
        unobserved_cells: list[int] = []
        distinct_prizes_set: set = set()
        for cell in range(1, cell_count + 1):
            entry = cm_raw.get(str(cell)) or {}
            hits = int(entry.get("hit_count") or 0)
            prize = entry.get("prize_multiplier")
            observed = hits > 0
            if observed:
                observed_cells.append(cell)
            else:
                unobserved_cells.append(cell)
            if observed and prize is not None:
                distinct_prizes_set.add(prize)
            cells_out.append({
                "cell": cell,
                "prize_multiplier": prize if observed else None,
                "observed": observed,
                "hit_count": hits,
                "hit_prob": (hits / total) if total > 0 else None,
                **({"nondeterministic": True} if str(cell) in nondeterministic else {}),
            })

        # jackpot: max distinct prize + the observed cells that pay it.
        if distinct_prizes_set:
            jackpot_mult = max(distinct_prizes_set)
            jackpot_cells = [
                c["cell"] for c in cells_out
                if c["observed"] and c["prize_multiplier"] == jackpot_mult
            ]
            jackpot = {"prize_multiplier": jackpot_mult, "cells": jackpot_cells}
        else:
            jackpot = {"prize_multiplier": None, "cells": []}

        section: dict[str, Any] = {
            "available": True,
            "source": (
                "st_extract.wheel_cells (per-ST extraction layer; per-round "
                "ReMarks CellIndex -> WinCredits/bet). The cell->prize map is a "
                "deterministic structural fact derived from data, not hardcoded."
            ),
            "wheel_cell_count": cell_count,
            "cells": cells_out,
            "observed_cells": observed_cells,
            "unobserved_cells": unobserved_cells,
            "distinct_prizes": sorted(distinct_prizes_set),
            "jackpot": jackpot,
            # Backward-friendly flat aliases (mirror the old cell_map keys so the
            # frontend KPI block can read them directly).
            "jackpot_cells": jackpot["cells"],
            "jackpot_prize_multiplier": jackpot["prize_multiplier"],
            "total_wheel_spins": total,
            "skipped_rounds": int(st_payload.get("skipped_rounds") or 0),
            "extraction_coverage": {
                "chunks_with_extract": chunks_with_extract,
                "chunks_total": chunks_total,
            },
        }
        if unobserved_cells:
            section["unobserved_note"] = (
                "cells with hit_count 0 in this sample have prize_multiplier null "
                "and observed:false — the prize is NOT fabricated (more wheel "
                "spins would pin it). feedback_invariant_with_fallback_hides_drift."
            )
        if nondeterministic:
            section["nondeterministic_cells"] = nondeterministic
            section["nondeterministic_alarm"] = (
                "one or more cells paid >1 distinct prize multiplier — a DATA "
                "ALARM (each wheel cell is meant to be deterministic). The cell's "
                "prize_multiplier is null (NOT silently resolved). Investigate "
                "before trusting the cell map."
            )
        if errors:
            section["extraction_errors"] = errors
        return section

    @staticmethod
    def _build_prize_distribution(cell_section: dict[str, Any]) -> dict[str, Any]:
        """Money-agnostic discrete-prize distribution as DISTINCT prizes
        (un-merged — derived from the exact cell map, NOT coarse RETURN_BUCKET
        bands). For M279 this RESTORES the 6 distinct prizes incl. 30x as a REAL
        data-derived value; for M283 it gives 6 distinct prizes incl. 200x and no
        fabricated 30x.

        Each prize: {prize_multiplier, prob, hit_count, win_share}.
          prob       = hit_count / total_wheel_spins (the prize-tier probability)
          win_share  = (prize_multiplier * hit_count) / sum(prize*hit) over prizes
        Returns available:false when the cell section is unavailable.
        """
        if not cell_section.get("available"):
            return {
                "available": False,
                "reason": cell_section.get("reason", "wheel_cells data unavailable"),
            }

        total = int(cell_section.get("total_wheel_spins") or 0)
        # Aggregate hit_count per distinct prize across all observed cells.
        prize_hits: dict[Any, int] = {}
        for c in cell_section.get("cells") or []:
            if not c.get("observed"):
                continue
            pm = c.get("prize_multiplier")
            if pm is None:
                continue
            prize_hits[pm] = prize_hits.get(pm, 0) + int(c.get("hit_count") or 0)

        total_win = sum(float(pm) * cnt for pm, cnt in prize_hits.items())
        prizes: list[dict[str, Any]] = []
        modal_prize: Any = None
        modal_count = -1
        for pm in sorted(prize_hits):
            cnt = prize_hits[pm]
            win = float(pm) * cnt
            prizes.append({
                "prize_multiplier": pm,
                "prob": (cnt / total) if total > 0 else None,
                "hit_count": cnt,
                "win_share": (win / total_win) if total_win > 0 else None,
            })
            if cnt > modal_count:
                modal_count = cnt
                modal_prize = pm

        jackpot = cell_section.get("jackpot") or {}
        return {
            "available": True,
            "source": (
                "st_extract.wheel_cells — each DISTINCT prize multiplier the wheel "
                "pays (un-merged from the exact cell->prize map). prob = "
                "hit_count/total wheel spins; win_share = prize*hit over all "
                "prize*hit. NO hardcoded ladder, NO RETURN_BUCKET merge."
            ),
            "total_events": total,
            "prizes": prizes,
            "distinct_prize_count": len(prizes),
            "modal_prize_multiplier": modal_prize,
            "dominant_prize_share": (
                (modal_count / total) if (total > 0 and modal_count > 0) else None
            ),
            "jackpot_prize_multiplier": jackpot.get("prize_multiplier"),
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

        final_acc = final_acc or {}
        cell_data: dict[str, Any] = final_acc.get("cell_data") or {}
        cell_errors: list[str] = list(final_acc.get("cell_errors") or [])
        chunks_with_extract = int(final_acc.get("chunks_with_extract") or 0)
        chunks_total = int(final_acc.get("chunks_total") or 0)

        wheel_st_s = str(wheel_st)
        st_payload = cell_data.get(wheel_st_s) or {}

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

        # ── W3 — EXACT 12-cell landing map + jackpot cell IDENTITY (data-derived) ──
        cell_map = self._build_cell_map(
            st_payload, cell_errors, chunks_with_extract, chunks_total
        )

        # ── W2 — discrete prize-tier distribution (the lottery) ──
        # DISTINCT prizes, un-merged, derived from the exact cell map (no
        # hardcoded ladder, no RETURN_BUCKET merge).
        prize_distribution = self._build_prize_distribution(cell_map)

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
