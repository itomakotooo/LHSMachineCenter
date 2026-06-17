"""AnalyzerFeature: nudge_dynamics — the crazy-reel NUDGE mechanic view (M63).

M63 onboarding (Wave 4). M63 mode_1 is a single paid-base-game SpinType (ST=1).
The ONE felt mechanic the strict-reused PER_SPINTYPE + CROSS_CUTTING stack does
NOT surface is the in-engine base-game reel NUDGE: on ~10% of paid spins a
vertical 3-symbol crazy_up/crazy/crazy_down block lands on a SINGLE reel and the
reel MOVES once (user domain confirmation 2026-06-17), sliding the block through
the 3-row window and improving/completing lines. It roughly DOUBLES the win-rate
of those rounds and 87.5% of its wins run THROUGH the nudged reel. This is the
"the reel just shifted and gave me a line" feeling — wholly INTRA-ST1, captured
by stateless testspin (it lives in StopSymbolsByCol), so the data RTP is COMPLETE
and the mechanic is NOT out-of-engine.

This feature quantifies the NUDGE's felt experience as rates / shares /
probabilities / count distributions (money-agnostic; NO coin totals). The metric
set N1-N6 (design 03_design.md §2):

  N1 nudge cadence — "how often does a reel shift?": hit_rate (nudge rounds / all
     paid spins) + single_col_share (the clean one-reel event).
  N2 win-rate uplift — "a shift makes me twice as likely to win": nudge win-rate
     vs baseline win-rate, and the ratio.
  N3 win-through-nudge — "the shifted reel is what paid me": wins running through
     the nudged column / nudge wins.
  N4 slide-offset distribution — "the block can land anywhere": the 5-arrangement
     histogram (the nudge stop position) with prob.
  N5 per-column distribution — "any reel can shift": the first-nudged-column
     count distribution (column-generic).
  N6 RTP concentration — "shifts carry a big chunk of payback": nudge-round win
     share of all win, the nudge RTP contribution pp, and the event rate.

Data path (all base-EXCLUDED — no parser/closure dependency)
------------------------------------------------------------
extract() reads the per-chunk crazy_reel_dim extractor output the parser emits in
the chunk dict (rec) — accumulated OURSELVES (no stash-ordering dependency), the
respin_dynamics / wheel_dynamics pattern:

  chunk_dict["st_extract"]["crazy_reel_dim"]
      {str(st): {total_rounds, nudge_rounds, single_col_rounds, multi_col_rounds,
      baseline_rounds, nudge_win_rounds, baseline_win_rounds,
      win_through_nudge_rounds, by_column, by_arrangement, skipped_rounds}} — the
      per-ST extraction layer's crazy-reel NUDGE extractor output
      (st_extract/crazy_reel_dim.py, declared by the manifest's
      spin_types["<st>"].crazy_reel block). Key is absent on chunks parsed
      without extractors or on machines without the crazy_reel block — a
      legitimate state (the feature then reports applicable:false, never
      fabricating).
  chunk_dict["st_extract"]["_extract_error_crazy_reel_dim"]
      surfaced extractor errors — collected and re-surfaced (never dropped,
      feedback_no_silent_swallow.md).

emit() additionally reads the byte-stable
summary["player_impact"]["spin_type_breakdown"] (per-ST round-level stats) for N6
(total_win, rtp_contribution_pp) — the same source wheel_dynamics uses.

RTP_CONTRIBUTION = False
  The nudge's wins are already attributed to ST1's real PayoutIds by the
  PER_SPINTYPE plugins (crazy* never itself carries a pid). This feature
  re-presents that win; it adds NOTHING to the RTP sum; sum(pay_id.rtp_pp) ==
  summary.rtp is unaffected (feedback_aggregator_parity_invariant.md).

Per-machine isolation
---------------------
NOT in fresh_slotlab/analyzer/core/ and NOT in versioning._CLOSURE_FILES — base-
EXCLUDED. Auto-discovered via feature_registry.discover_features(). It attaches
ONLY to a machine whose ST declares the "crazy_reel" dimension (via
machine_spec.DIMENSION_ANALYSES — NOT the shared `paid_spin` role nor the shared
`Normal` play, which would cross-fire onto every base game / every Normal base).
The crazy_reel_dim extractor it consumes is likewise base-excluded.

Memory feedback honored
-----------------------
- feedback_no_hardcode.md: the nudge ST is resolved from the manifest's
  spin_types (the ST carrying the "crazy_reel" block), NOT hardcoded "1".
- feedback_no_silent_swallow.md: a missing spin_type_breakdown section RAISES.
  The nudge degrades gracefully when the extractor is absent (applicable:false
  with a reason), and surfaces extractor errors.
- feedback_invariant_with_fallback_hides_drift.md: no catch-all bucket; rates
  with a zero denominator are null, not a "0.0 with 0 denominator" lie;
  applicable:false is an explicit no-data signal, not a fallback bucket.
- feedback_no_parallel_panel_impl.md: mirrors wheel_dynamics' consumption of the
  st_extract layer (reads rec["st_extract"][<EXTRACTOR_ID>], merges across
  chunks, surfaces errors) and its emit shape.
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


# The extractor id whose chunk output this plugin consumes.
_CRAZY_REEL_EXTRACTOR_ID: str = "crazy_reel_dim"

# The manifest spin_types sub-key that declares the nudge dimension.  Resolving
# the nudge ST from this key (not a hardcoded number) honors feedback_no_hardcode.
_CRAZY_REEL_DECL_KEY: str = "crazy_reel"

# Additive count keys merged across chunks.
_COUNT_KEYS: tuple[str, ...] = (
    "total_rounds",
    "nudge_rounds",
    "single_col_rounds",
    "multi_col_rounds",
    "baseline_rounds",
    "nudge_win_rounds",
    "baseline_win_rounds",
    "win_through_nudge_rounds",
    "skipped_rounds",
)

# Additive win-AMOUNT sums (float) — feed the N6 nudge win SHARE (a ratio), never
# surfaced as a coin total. Kept separate from _COUNT_KEYS so the int-cast does not
# apply (win is integer credits today, but the sum path stays float-safe).
_SUM_KEYS: tuple[str, ...] = ("nudge_win_sum", "total_win_sum")


def _merge_dim(prev: dict[str, Any], this: dict[str, Any]) -> dict[str, Any]:
    """Additively merge two crazy_reel_dim extractor outputs across chunks.

    Shape: {st_str: {<count keys>, by_column, by_arrangement}}.  All count keys
    and the by_column / by_arrangement histograms are additive.
    """
    out: dict[str, Any] = {}
    all_sts = set(prev) | set(this)
    for st in all_sts:
        pa = prev.get(st) or {}
        pb = this.get(st) or {}
        merged: dict[str, Any] = {}
        for k in _COUNT_KEYS:
            merged[k] = int(pa.get(k, 0)) + int(pb.get(k, 0))
        for k in _SUM_KEYS:
            merged[k] = float(pa.get(k, 0.0)) + float(pb.get(k, 0.0))
        # by_column (str col -> count) additive
        bc: dict[str, int] = {}
        for src in (pa.get("by_column") or {}, pb.get("by_column") or {}):
            for col, cnt in src.items():
                bc[str(col)] = bc.get(str(col), 0) + int(cnt)
        merged["by_column"] = bc
        # by_arrangement (label -> count) additive
        ba: dict[str, int] = {}
        for src in (pa.get("by_arrangement") or {}, pb.get("by_arrangement") or {}):
            for label, cnt in src.items():
                ba[str(label)] = ba.get(str(label), 0) + int(cnt)
        merged["by_arrangement"] = ba
        out[str(st)] = merged
    return out


def _resolve_nudge_st(manifest: dict[str, Any] | None) -> int | None:
    """Return the first SpinType int whose spec carries the crazy_reel block.

    No hardcoded ids (feedback_no_hardcode.md): the nudge ST is the ST declaring
    the dimension, read from ctx.machine_spec_manifest.
    """
    if not isinstance(manifest, dict):
        return None
    for st_key, spec in (manifest.get("spin_types") or {}).items():
        if isinstance(spec, dict) and isinstance(spec.get(_CRAZY_REEL_DECL_KEY), dict):
            # Honor an explicit spin_type override inside the block.
            block_st = spec[_CRAZY_REEL_DECL_KEY].get("spin_type")
            if block_st is not None:
                try:
                    return int(block_st)
                except (TypeError, ValueError):
                    pass
            try:
                return int(st_key)
            except (TypeError, ValueError):
                continue
    return None


def _safe_div(num: float, den: float) -> float | None:
    """num/den, or None when den<=0 (no "0.0 with 0 denominator" lie)."""
    return (num / den) if den and den > 0 else None


class NudgeDynamics(AnalyzerFeature):
    """Pattern-B plugin: accumulate the per-ST crazy_reel_dim extractor output per
    chunk; compute the nudge-mechanic metrics N1-N6 in emit() (reading the
    byte-stable spin_type_breakdown section too).

    Accumulator structure
    ---------------------
      dim_data: dict[str, Any]
          {st: {<count keys>, by_column, by_arrangement}} from
          rec["st_extract"]["crazy_reel_dim"], merged across chunks.
      dim_errors: list[str]
          surfaced _extract_error_crazy_reel_dim entries (never dropped).
      chunks_with_extract / chunks_total: int
          coverage counters — reports honestly when some chunks were parsed
          without the extractor.
    """

    FEATURE_ID: ClassVar[str] = "nudge_dynamics"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("nudge_dynamics",)
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False  # win already attributed to ST1 pids
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    # We read spin_type_breakdown in emit(); payouts_by_spin_type guarantees it is
    # present (it requires spin_type_breakdown, written by the inline F1 block).
    REQUIRES: ClassVar[tuple[str, ...]] = ("payouts_by_spin_type",)
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Lift the per-chunk crazy_reel_dim extractor output.

        Absence of the OPTIONAL extractor (old cached records / machine without a
        crazy_reel block) is a legitimate state, not an error — coverage is
        tracked and reported (feedback_no_silent_swallow.md: extractor ERRORS, by
        contrast, are collected and re-surfaced).
        """
        empty = {
            "dim_data": {}, "dim_errors": [],
            "chunks_with_extract": 0, "chunks_total": 0,
        }
        if not chunk_dict or not isinstance(chunk_dict, dict):
            return empty

        st_extract = chunk_dict.get("st_extract")
        dim_data: dict[str, Any] = {}
        dim_errors: list[str] = []
        chunks_with_extract = 0

        if isinstance(st_extract, dict):
            raw = st_extract.get(_CRAZY_REEL_EXTRACTOR_ID)
            if isinstance(raw, dict):
                chunks_with_extract = 1
                for st_key, payload in raw.items():
                    if not str(st_key).isdigit():
                        continue
                    if not isinstance(payload, dict):
                        continue
                    rec: dict[str, Any] = {}
                    for k in _COUNT_KEYS:
                        rec[k] = int(payload.get(k) or 0)
                    for k in _SUM_KEYS:
                        rec[k] = float(payload.get(k) or 0.0)
                    rec["by_column"] = {
                        str(c): int(v)
                        for c, v in (payload.get("by_column") or {}).items()
                    }
                    rec["by_arrangement"] = {
                        str(label): int(v)
                        for label, v in (payload.get("by_arrangement") or {}).items()
                    }
                    dim_data[str(st_key)] = rec
            err = st_extract.get(f"_extract_error_{_CRAZY_REEL_EXTRACTOR_ID}")
            if err:
                dim_errors.append(str(err))

        return {
            "dim_data": dim_data,
            "dim_errors": dim_errors,
            "chunks_with_extract": chunks_with_extract,
            "chunks_total": 1,
        }

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Additively merge crazy_reel_dim data across chunks."""
        empty = {
            "dim_data": {}, "dim_errors": [],
            "chunks_with_extract": 0, "chunks_total": 0,
        }
        if not prev_acc:
            return this_acc if this_acc else empty
        if not this_acc:
            return prev_acc
        return {
            "dim_data": _merge_dim(
                prev_acc.get("dim_data") or {}, this_acc.get("dim_data") or {}
            ),
            "dim_errors": (
                list(prev_acc.get("dim_errors") or [])
                + list(this_acc.get("dim_errors") or [])
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
    def _slide_distribution(by_arrangement: dict[str, int], nudge_rounds: int) -> list[dict[str, Any]]:
        """N4 — the slide-offset histogram, sorted by descending count, each with
        a prob over nudge rounds.  Money-agnostic (counts + probabilities)."""
        rows: list[dict[str, Any]] = []
        for label, cnt in sorted(
            by_arrangement.items(), key=lambda kv: (-int(kv[1]), str(kv[0]))
        ):
            rows.append({
                "offset_label": label,
                "count": int(cnt),
                "prob": _safe_div(int(cnt), nudge_rounds),
            })
        return rows

    @staticmethod
    def _column_distribution(by_column: dict[str, int], nudge_rounds: int) -> list[dict[str, Any]]:
        """N5 — the per-column (first nudged column) distribution, sorted by
        column index, each with a share over nudge rounds (column-generic)."""
        rows: list[dict[str, Any]] = []

        def _col_key(c: str) -> int:
            try:
                return int(c)
            except (TypeError, ValueError):
                return 1_000_000

        for col, cnt in sorted(by_column.items(), key=lambda kv: _col_key(kv[0])):
            rows.append({
                "col": int(col) if str(col).lstrip("-").isdigit() else col,
                "count": int(cnt),
                "share": _safe_div(int(cnt), nudge_rounds),
            })
        return rows

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Compute and write summary["player_impact"]["nudge_dynamics"]."""
        player_impact = summary.setdefault("player_impact", {})

        # Hard dependency check (feedback_no_silent_swallow.md).
        if "spin_type_breakdown" not in player_impact:
            raise RuntimeError(
                "nudge_dynamics requires player_impact['spin_type_breakdown'] "
                "but it is absent at emit time — the inline F1 block / "
                "PayoutsBySpinType did not run or failed upstream."
            )

        manifest = getattr(ctx, "machine_spec_manifest", None)
        nudge_st = _resolve_nudge_st(manifest)

        if nudge_st is None:
            player_impact["nudge_dynamics"] = {
                "applicable": False,
                "reason": "no SpinType declares the 'crazy_reel' dimension in manifest",
            }
            return

        final_acc = final_acc or {}
        dim_data: dict[str, Any] = final_acc.get("dim_data") or {}
        dim_errors: list[str] = list(final_acc.get("dim_errors") or [])
        chunks_with_extract = int(final_acc.get("chunks_with_extract") or 0)
        chunks_total = int(final_acc.get("chunks_total") or 0)

        payload = dim_data.get(str(nudge_st)) or {}
        total_rounds = int(payload.get("total_rounds") or 0)
        nudge_rounds = int(payload.get("nudge_rounds") or 0)

        # No crazy rounds observed -> explicit no-data signal (NOT a fabricated
        # zero-filled panel, NOT a fallback bucket).
        if not payload or nudge_rounds <= 0:
            reason = (
                "no crazy-reel nudge rounds observed"
                if payload
                else (
                    "no st_extract.crazy_reel_dim data in the parsed chunks "
                    f"({chunks_with_extract}/{chunks_total} chunks carried the "
                    "extractor output). The manifest declares crazy_reel on the "
                    "nudge ST; the per-ST extraction layer resolves it at parse "
                    "time — a caller that bypasses report_engine's extractor "
                    "wiring, or a machine without the crazy_reel block, produces "
                    "records without it."
                )
            )
            section: dict[str, Any] = {
                "applicable": False,
                "nudge_spin_type": nudge_st,
                "reason": reason,
                "extraction_coverage": {
                    "chunks_with_extract": chunks_with_extract,
                    "chunks_total": chunks_total,
                },
            }
            if dim_errors:
                section["extraction_errors"] = dim_errors
            player_impact["nudge_dynamics"] = section
            return

        single_col = int(payload.get("single_col_rounds") or 0)
        multi_col = int(payload.get("multi_col_rounds") or 0)
        baseline_rounds = int(payload.get("baseline_rounds") or 0)
        nudge_win = int(payload.get("nudge_win_rounds") or 0)
        baseline_win = int(payload.get("baseline_win_rounds") or 0)
        through = int(payload.get("win_through_nudge_rounds") or 0)

        # ── N1 cadence — "how often does a reel shift?" ──
        hit_rate = _safe_div(nudge_rounds, total_rounds)
        single_col_share = _safe_div(single_col, nudge_rounds)
        one_per_n = _safe_div(total_rounds, nudge_rounds)

        # ── N2 win-rate uplift — "a shift ~doubles my win chance" ──
        nudge_win_rate = _safe_div(nudge_win, nudge_rounds)
        baseline_win_rate = _safe_div(baseline_win, baseline_rounds)
        uplift_ratio = (
            (nudge_win_rate / baseline_win_rate)
            if (nudge_win_rate is not None and baseline_win_rate)
            else None
        )
        win_rate_uplift = {
            "nudge": nudge_win_rate,
            "baseline": baseline_win_rate,
            "ratio": uplift_ratio,
        }

        # ── N3 win-through-nudge — "the shifted reel is what paid me" ──
        win_through_nudge_share = _safe_div(through, nudge_win)

        # ── N4 slide-offset distribution — "the block can land anywhere" ──
        slide_distribution = self._slide_distribution(
            payload.get("by_arrangement") or {}, nudge_rounds
        )

        # ── N5 per-column distribution — "any reel can shift" ──
        by_column = self._column_distribution(
            payload.get("by_column") or {}, nudge_rounds
        )

        # ── N6 RTP concentration — "shifts carry a big chunk of payback" ──
        # Money is used ONLY to form a SHARE / contribution-pp (the framework's
        # standard win/bet ratio), never a coin total surfaced to the player.
        stb_rows: list[dict[str, Any]] = player_impact.get("spin_type_breakdown") or []
        nudge_row: dict[str, Any] = {}
        for row in stb_rows:
            try:
                if int(row.get("spin_type")) == nudge_st:
                    nudge_row = row
                    break
            except (TypeError, ValueError):
                continue
        st_total_win = float(nudge_row.get("total_win") or 0.0)
        st_rtp_pp = nudge_row.get("rtp_contribution_pp")
        all_win = sum(float(r.get("total_win") or 0.0) for r in stb_rows)
        all_spins = sum(int(r.get("spins") or 0) for r in stb_rows)
        # N6 RTP concentration — the nudge-round win share, now DATA-DERIVED.
        # The extractor accumulates per-round win into nudge_win_sum/total_win_sum
        # (counts→ratio is the framework's standard win/bet surface; never a coin
        # total). share_of_st_win = nudge-round win ÷ this ST's win; the nudge's
        # RTP contribution (pp) = that share × the ST's rtp_pp.
        nudge_win_sum = float(payload.get("nudge_win_sum") or 0.0)
        total_win_sum = float(payload.get("total_win_sum") or 0.0)
        share_of_st_win = _safe_div(nudge_win_sum, total_win_sum)
        nudge_rtp_pp = (
            (share_of_st_win * float(st_rtp_pp))
            if (share_of_st_win is not None and st_rtp_pp is not None)
            else None
        )
        rtp_concentration = {
            # share of ALL machine win (== share_of_st_win on a single-ST machine)
            "share_of_all_win": _safe_div(nudge_win_sum, all_win),
            "share_of_st_win": share_of_st_win,
            "nudge_rtp_contribution_pp": nudge_rtp_pp,
            "event_rate": _safe_div(nudge_rounds, all_spins),
            "hit_rate": hit_rate,
            "note": (
                "the nudge fires on ~{:.1f}% of paid spins and carries "
                "~{:.1f}% of this ST's payback (DATA-DERIVED from per-round "
                "nudge_win_sum/total_win_sum)."
            ).format(100.0 * (hit_rate or 0.0), 100.0 * (share_of_st_win or 0.0)),
        }

        section = {
            "applicable": True,
            "nudge_spin_type": nudge_st,
            "cadence": {
                "hit_rate": hit_rate,
                "nudge_rounds": nudge_rounds,
                "total_rounds": total_rounds,
                "single_col_rounds": single_col,
                "multi_col_rounds": multi_col,
                "single_col_share": single_col_share,
                "one_per_n_paid_spins": one_per_n,
            },
            "hit_rate": hit_rate,
            "single_col_share": single_col_share,
            "win_rate_uplift": win_rate_uplift,
            "win_through_nudge_share": win_through_nudge_share,
            "win_through_nudge_rounds": through,
            "nudge_win_rounds": nudge_win,
            "slide_distribution": slide_distribution,
            "by_column": by_column,
            "rtp_concentration": rtp_concentration,
            "extraction_coverage": {
                "chunks_with_extract": chunks_with_extract,
                "chunks_total": chunks_total,
            },
        }
        if int(payload.get("skipped_rounds") or 0):
            section["skipped_rounds"] = int(payload.get("skipped_rounds") or 0)
        if dim_errors:
            section["extraction_errors"] = dim_errors

        player_impact["nudge_dynamics"] = section


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# Auto-discovered by feature_registry.discover_features() (globs features/*.py).
# ---------------------------------------------------------------------------
register(NudgeDynamics())
