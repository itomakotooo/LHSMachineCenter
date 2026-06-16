"""AnalyzerFeature: freespin_dynamics — the granted-freespin-session MECHANIC view.

M275 onboarding (Wave 4). The reel/payid/outcome DIMENSIONS of the freespin ST
are already covered by the strict-reused PER_SPINTYPE plugins
(payouts_by_spin_type / reel_marginal_by_spin_type / spin_type_outcomes;
spin_type_rtp_buckets omits free STs BY DESIGN — paid-bet denominator). This
feature quantifies the FREESPIN MECHANIC itself — the felt experience that makes
a granted multi-spin free session a distinct event — as rates / multipliers /
probabilities / distributions (money-agnostic; NO coin totals).

Role hook: ROLE_ANALYSES["freespin"] (machine_spec.py). The `freespin` role =
a granted multi-spin FREE session opened by a trigger event (scatter pid and/or
a counter peak) — structurally DIFFERENT from `respin` (a win-driven extension
of the same paid spin with variable, win-gated burst length). respin_dynamics'
metric semantics would mis-describe a scatter freespin (grant-per-winning-spin
is meaningless for a win-independent trigger; "continuation_prob" reads as a
win-gated chain when it is just the arithmetic of a fixed block) — see
session_artifacts/_onboard/M275/03_design.md §3. Attach by ROLE because the
analysis applies to ANY freespin-role ST generically (session cadence / uplift /
trigger paths are feature-agnostic across the freespin family).

What the player feels (design 03_design.md §2.1), each feeling -> a number:
  F1 The grant — "I got a block of free spins" (rare; mostly by luck, sometimes
     earned by the pity meter). Session cadence: openers / per-paid-spin rate /
     one-per-N / average block length.
  F2 The hot board — free spins hit much more often than the base game
     (uplift ratio) + the overlaid multiplier band distributions + payid mix.
  F6 Two doors into the same room ⭐⭐ (the central design): the session opens by
     LUCK (scatter pid) or by RIGHT (counter peak). The per-path side-by-side
     table REPORTS the paths and lets identity/difference EMERGE from the data
     (never assumed) — reusable across the freespin family where per-path
     configs may genuinely differ.
  F3a/F4/F5 (server-tier sessions / ER ladder / FS arc) are parser_blind —
     flagged explicitly, NEVER fabricated (see `parser_blind` output field).

Data path (all base-EXCLUDED — no parser/closure dependency)
------------------------------------------------------------
extract() reads per-chunk accumulators the parser already emits in the chunk
dict (rec) — accumulated OURSELVES (no stash-ordering dependency):

  chunk_dict["spin_type_next_counts"]
      {str(from_st): {str(to_st): count}} — ST transition tally. Gives
      base->freespin openers (F1) and freespin->freespin internal transitions.
  chunk_dict["spin_type_bucket_spins" | "spin_type_bucket_win"]
      {str(st): {return_bucket_label: value}} — per-ST win/bet multiplier-band
      histograms over ALL rounds (free included). The F2 band overlays.
  chunk_dict["st_extract"]["trigger_path"]
      {str(st): {path_label: {round_count, win_sum, session_count,
      win_band_hist}}} — the per-ST extraction layer's generic trigger-path
      extractor output (st_extract/trigger_path.py, declared by the manifest's
      spin_types["<st>"].trigger_paths block). The F6 per-path split. Key is
      absent on chunks parsed without extractors — a legitimate state (the F6
      section then reports source unavailable, never fabricates).
  chunk_dict["st_extract"]["_extract_error_trigger_path"]
      surfaced extractor errors — collected and re-surfaced in the output
      (feedback_no_silent_swallow.md: never dropped).

emit() additionally reads two already-built summary sections (byte-stable;
ordering guaranteed via REQUIRES):

  summary["player_impact"]["spin_type_breakdown"]   (hit rates, RTP pp, wins)
  summary["player_impact"]["payouts_by_spin_type"]  (payid mix)
  summary["player_impact"]["bonus_chain_dynamics"]  (chain STRUCTURE
      corroboration ONLY: chain_count / avg_chain_length / retrigger. Its
      ExtraRatio surfaces are ReMarks-regex-sourced and DEFAULT-FILLED flat-100
      on field-borne-ER machines like M275 — they MUST NOT be cited as ER
      coverage; see the corroboration `source` note.)

RTP_CONTRIBUTION = False
  This feature re-presents wins already attributed to the freespin ST's own
  pids by the PER_SPINTYPE plugins. It adds NOTHING to the RTP sum;
  sum(pay_id.rtp_pp)==summary.rtp is unaffected
  (feedback_aggregator_parity_invariant.md).

Per-machine isolation
---------------------
NOT in fresh_slotlab/analyzer/core/ and NOT in versioning._CLOSURE_FILES —
base-EXCLUDED (R-4). Auto-discovered via feature_registry.discover_features().
Editing it re-flags ONLY machines declaring "freespin_dynamics" (via the
`freespin` role in machine_spec.ROLE_ANALYSES).

Memory feedback honored
-----------------------
- feedback_no_hardcode.md: no M275-specific ids. The freespin/base STs are
  resolved from the manifest's spin_types (role), path labels from the
  manifest's trigger_paths declaration — NOT hardcoded "126"/"140"/"666".
- feedback_no_silent_swallow.md: a missing REQUIRES section RAISES; extractor
  errors are re-surfaced; parser_blind sub-metrics are EXPLICIT, never
  fabricated zeros.
- feedback_invariant_with_fallback_hides_drift.md: unknown:* / multi:* path
  buckets are surfaced as ALARM-semantics rows (signal, never a silent
  residual); zero-denominator rates emit null, not a "0.0" lie.
- feedback_no_parallel_panel_impl.md: mirrors respin_dynamics / wheel_dynamics
  (extract/reduce/emit, ClassVar layout, dual-path import, register());
  reuses RETURN_BUCKET_ORDER.
- feedback_subprocess_import_suicide_and_module_globals.md: register() is a
  pure list-append; no I/O at import time.
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

# Phase 3: freespin_progression extractor id.
_FREESPIN_PROGRESSION_EXTRACTOR_ID: str = "freespin_progression"

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
    except ImportError:
        from analyzer.pipeline_context import PipelineContext  # type: ignore[assignment]


# Multiplier-band tail thresholds (felt "fat-tail" cut) — same bands the sibling
# respin_dynamics uses, so tail shares are comparable across mechanic views.
_TAIL_GE20_BANDS: frozenset[str] = frozenset({
    "ge20_lt50", "ge50_lt100", "ge100_lt200", "ge200_lt500",
    "ge500_lt1000", "ge1000_lt5000", "ge5000",
})

# The extractor id whose chunk output F6 consumes (st_extract/trigger_path.py).
_TRIGGER_PATH_EXTRACTOR_ID: str = "trigger_path"


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


def _merge_trigger_paths(
    prev: dict[str, dict[str, dict[str, Any]]],
    this: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Merge two {st: {path: {round_count, win_sum, session_count,
    win_band_hist}}} trees across chunks.

    session_count is summed: the extractor keys sessions by (robot_idx,
    block_id) WITHIN a chunk, and robots are distinct across chunks, so
    per-chunk distinct-session counts are additive.
    """
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for st, paths in prev.items():
        out[st] = {p: {
            "round_count": int(v.get("round_count", 0)),
            "win_sum": float(v.get("win_sum", 0.0)),
            "session_count": int(v.get("session_count", 0)),
            "win_band_hist": dict(v.get("win_band_hist") or {}),
        } for p, v in paths.items()}
    for st, paths in this.items():
        dest_st = out.setdefault(st, {})
        for p, v in paths.items():
            dest = dest_st.setdefault(p, {
                "round_count": 0, "win_sum": 0.0, "session_count": 0,
                "win_band_hist": {},
            })
            dest["round_count"] += int(v.get("round_count", 0))
            dest["win_sum"] += float(v.get("win_sum", 0.0))
            dest["session_count"] += int(v.get("session_count", 0))
            for band, cnt in (v.get("win_band_hist") or {}).items():
                dest["win_band_hist"][band] = (
                    dest["win_band_hist"].get(band, 0) + int(cnt)
                )
    return out


def _merge_progression(
    prev: dict[str, Any],
    this: dict[str, Any],
) -> dict[str, Any]:
    """Merge two freespin_progression outputs across chunks.

    Shape: {st_str: {dim_name: {path_label: {er_ladder, fs_arc, session_tier_hist}}}}

    Per-FS-index counts/sums are additive. session_tier_hist bucket counts
    are additive. er_distribution counts are additive.
    """
    out: dict[str, Any] = {}

    def _merge_er_ladder(
        a: dict[str, Any], b: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge two {fs_idx: {er_distribution, er_sum, round_count}} dicts."""
        result: dict[str, Any] = {}
        all_idxs = set(a) | set(b)
        for fi in all_idxs:
            ea = a.get(fi) or {}
            eb = b.get(fi) or {}
            merged_dist: dict[str, int] = {}
            all_er_vals = set(ea.get("er_distribution") or {}) | set(eb.get("er_distribution") or {})
            for er_val in all_er_vals:
                merged_dist[er_val] = (
                    int((ea.get("er_distribution") or {}).get(er_val, 0))
                    + int((eb.get("er_distribution") or {}).get(er_val, 0))
                )
            result[fi] = {
                "er_distribution": merged_dist,
                "er_sum": float(ea.get("er_sum", 0.0)) + float(eb.get("er_sum", 0.0)),
                "round_count": int(ea.get("round_count", 0)) + int(eb.get("round_count", 0)),
            }
        return result

    def _merge_fs_arc(
        a: dict[str, Any], b: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge two {fs_idx: {round_count, win_round_count, win_sum}} dicts."""
        result: dict[str, Any] = {}
        all_idxs = set(a) | set(b)
        for fi in all_idxs:
            ea = a.get(fi) or {}
            eb = b.get(fi) or {}
            result[fi] = {
                "round_count": int(ea.get("round_count", 0)) + int(eb.get("round_count", 0)),
                "win_round_count": int(ea.get("win_round_count", 0)) + int(eb.get("win_round_count", 0)),
                "win_sum": float(ea.get("win_sum", 0.0)) + float(eb.get("win_sum", 0.0)),
            }
        return result

    def _merge_hist(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
        result: dict[str, int] = dict(a)
        for k, v in b.items():
            result[k] = result.get(k, 0) + int(v)
        return result

    all_sts = set(prev) | set(this)
    for st_str in all_sts:
        pa = prev.get(st_str) or {}
        pb = this.get(st_str) or {}
        out[st_str] = {}
        all_dims = set(pa) | set(pb)
        for dim_name in all_dims:
            da = pa.get(dim_name) or {}
            db = pb.get(dim_name) or {}
            out[st_str][dim_name] = {}
            all_paths = set(da) | set(db)
            for path_label in all_paths:
                va = da.get(path_label) or {}
                vb = db.get(path_label) or {}
                out[st_str][dim_name][path_label] = {
                    "er_ladder": _merge_er_ladder(
                        va.get("er_ladder") or {}, vb.get("er_ladder") or {}
                    ),
                    "fs_arc": _merge_fs_arc(
                        va.get("fs_arc") or {}, vb.get("fs_arc") or {}
                    ),
                    "session_tier_hist": _merge_hist(
                        va.get("session_tier_hist") or {},
                        vb.get("session_tier_hist") or {},
                    ),
                    "_alarm": va.get("_alarm") or vb.get("_alarm"),
                }
    return out


def _resolve_st_by_role(manifest: dict[str, Any] | None, role: str) -> int | None:
    """Return the first SpinType int whose spec.role == role. None if no match.

    No hardcoded ids (feedback_no_hardcode.md): the freespin/base STs are
    identified by their manifest role declarations.
    """
    if not isinstance(manifest, dict):
        return None
    for st_key, spec in (manifest.get("spin_types") or {}).items():
        if isinstance(spec, dict) and str(spec.get("role", "")) == role:
            try:
                return int(st_key)
            except (TypeError, ValueError):
                continue
    return None


class FreespinDynamics(AnalyzerFeature):
    """Pattern-B plugin: accumulate transition + per-ST bucket + trigger-path
    data per chunk; compute the freespin-mechanic metrics in emit() (reading
    the byte-stable spin_type_breakdown / payouts_by_spin_type /
    bonus_chain_dynamics sections too).

    Accumulator structure
    ---------------------
      next_counts: dict[str, dict[str, int]]
          ST transition tally (spin_type_next_counts), merged across chunks.
      bucket_spins / bucket_win: dict[str, dict[str, number]]
          per-ST return-bucket histograms (spin_type_bucket_{spins,win}).
      trigger_paths: dict[str, dict[str, dict]]
          {st: {path: {round_count, win_sum, session_count, win_band_hist}}}
          from rec["st_extract"]["trigger_path"], merged across chunks.
      trigger_path_errors: list[str]
          surfaced _extract_error_trigger_path entries (never dropped).
      chunks_with_extract / chunks_total: int
          coverage counters — F6 reports honestly when some chunks were
          parsed without the extractor (e.g. stale caller).
    """

    FEATURE_ID: ClassVar[str] = "freespin_dynamics"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("freespin_dynamics",)
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False  # re-presents already-attributed wins
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    # spin_type_breakdown + payouts_by_spin_type are guaranteed by
    # payouts_by_spin_type (it requires spin_type_breakdown, written by the
    # inline F1 block). bonus_chain_dynamics is in REQUIRES so the chain
    # STRUCTURE corroboration reads a section that has already been emitted
    # (it is CROSS_CUTTING — present in every machine's analysis set).
    REQUIRES: ClassVar[tuple[str, ...]] = (
        "payouts_by_spin_type",
        "bonus_chain_dynamics",
    )
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """Lift the per-chunk transition tally, per-ST bucket histograms, and
        the trigger_path extraction output.

        Absence of the OPTIONAL accumulators (old cached records / machine
        without extraction) is a legitimate state, not an error — coverage is
        tracked and reported (feedback_no_silent_swallow.md: extractor ERRORS,
        by contrast, are collected and re-surfaced).
        """
        empty = {
            "next_counts": {}, "bucket_spins": {}, "bucket_win": {},
            "trigger_paths": {}, "trigger_path_errors": [],
            "chunks_with_extract": 0, "chunks_total": 0,
            # Phase 3: freespin_progression extractor data.
            "progression": {},  # {st_str: {dim_name: {path_label: {er_ladder, fs_arc, session_tier_hist}}}}
            "progression_errors": [],
        }
        if not chunk_dict or not isinstance(chunk_dict, dict):
            return empty

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

        st_extract = chunk_dict.get("st_extract")
        trigger_paths: dict[str, dict[str, dict[str, Any]]] = {}
        trigger_path_errors: list[str] = []
        chunks_with_extract = 0

        if isinstance(st_extract, dict):
            tp_raw = st_extract.get(_TRIGGER_PATH_EXTRACTOR_ID)
            if isinstance(tp_raw, dict):
                chunks_with_extract = 1
                for st_key, paths in tp_raw.items():
                    if not str(st_key).isdigit(): continue  # skip "dimensions" and any future non-ST sibling keys
                    if not isinstance(paths, dict):
                        continue
                    dest = trigger_paths.setdefault(str(st_key), {})
                    for label, stats in paths.items():
                        if not isinstance(stats, dict):
                            continue
                        dest[str(label)] = {
                            "round_count": int(stats.get("round_count") or 0),
                            "win_sum": float(stats.get("win_sum") or 0.0),
                            "session_count": int(stats.get("session_count") or 0),
                            "win_band_hist": {
                                str(b): int(c)
                                for b, c in (stats.get("win_band_hist") or {}).items()
                            },
                        }

            err = st_extract.get(f"_extract_error_{_TRIGGER_PATH_EXTRACTOR_ID}")
            if err:
                trigger_path_errors.append(str(err))

        # Phase 3: lift freespin_progression extractor output.
        progression: dict[str, Any] = {}
        progression_errors: list[str] = []
        if isinstance(st_extract, dict):
            prog_raw = st_extract.get(_FREESPIN_PROGRESSION_EXTRACTOR_ID)
            if isinstance(prog_raw, dict):
                # Copy the full structure (st_str -> dim_name -> path_label -> {er_ladder, fs_arc, session_tier_hist}).
                for st_key, dim_data in prog_raw.items():
                    if not isinstance(dim_data, dict):
                        continue
                    dest_dims: dict[str, Any] = {}
                    for dim_name, path_data in dim_data.items():
                        if not isinstance(path_data, dict):
                            continue
                        dest_paths: dict[str, Any] = {}
                        for path_label, stats in path_data.items():
                            if not isinstance(stats, dict):
                                continue
                            dest_paths[str(path_label)] = {
                                "er_ladder": dict(stats.get("er_ladder") or {}),
                                "fs_arc": dict(stats.get("fs_arc") or {}),
                                "session_tier_hist": dict(stats.get("session_tier_hist") or {}),
                                "_alarm": stats.get("_alarm"),
                            }
                        if dest_paths:
                            dest_dims[str(dim_name)] = dest_paths
                    if dest_dims:
                        progression[str(st_key)] = dest_dims
            err_prog = st_extract.get(f"_extract_error_{_FREESPIN_PROGRESSION_EXTRACTOR_ID}")
            if err_prog:
                progression_errors.append(str(err_prog))

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
            "trigger_paths": trigger_paths,
            "trigger_path_errors": trigger_path_errors,
            "chunks_with_extract": chunks_with_extract,
            "chunks_total": 1,
            "progression": progression,
            "progression_errors": progression_errors,
        }

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Additively merge all accumulators across chunks."""
        _empty = {
            "next_counts": {}, "bucket_spins": {}, "bucket_win": {},
            "trigger_paths": {}, "trigger_path_errors": [],
            "chunks_with_extract": 0, "chunks_total": 0,
            "progression": {}, "progression_errors": [],
        }
        if not prev_acc:
            return this_acc if this_acc else _empty
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
            "trigger_paths": _merge_trigger_paths(
                prev_acc.get("trigger_paths") or {},
                this_acc.get("trigger_paths") or {},
            ),
            "trigger_path_errors": (
                list(prev_acc.get("trigger_path_errors") or [])
                + list(this_acc.get("trigger_path_errors") or [])
            ),
            "chunks_with_extract": (
                int(prev_acc.get("chunks_with_extract") or 0)
                + int(this_acc.get("chunks_with_extract") or 0)
            ),
            "chunks_total": (
                int(prev_acc.get("chunks_total") or 0)
                + int(this_acc.get("chunks_total") or 0)
            ),
            # Phase 3: merge progression data.
            "progression": _merge_progression(
                prev_acc.get("progression") or {},
                this_acc.get("progression") or {},
            ),
            "progression_errors": (
                list(prev_acc.get("progression_errors") or [])
                + list(this_acc.get("progression_errors") or [])
            ),
        }

    @staticmethod
    def _bucket_distribution(
        bucket_spins: dict[str, int],
        bucket_win: dict[str, float],
    ) -> dict[str, Any]:
        """Money-agnostic multiplier-band distribution for one ST (the same
        shape respin_dynamics emits, so band overlays read identically in the
        console). Denominator = ALL of this ST's rounds (incl. eq0)."""
        total_spins = sum(int(v) for v in bucket_spins.values())
        total_win = sum(float(v) for v in bucket_win.values())
        win_rounds = sum(int(c) for b, c in bucket_spins.items() if b != "eq0")
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
        """Per-pid hit-share + win-share for one ST (real pids only)."""
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

    @staticmethod
    def _label_for_st(
        pbst: dict[str, list[dict[str, Any]]], st_int: int | None
    ) -> str | None:
        """Find the payouts_by_spin_type label (e.g. "ST126_free") for an ST int."""
        if st_int is None:
            return None
        prefix = f"ST{st_int}_"
        for label in pbst:
            if label.startswith(prefix):
                return label
        return None

    @staticmethod
    def _band_rows_from_hist(hist: dict[str, int]) -> list[dict[str, Any]]:
        """Order a {band: count} histogram into RETURN_BUCKET_ORDER rows
        (eq0 = zero-win band appended last when present)."""
        total = sum(int(v) for v in hist.values())
        rows: list[dict[str, Any]] = []
        ordered = list(RETURN_BUCKET_ORDER) + (["eq0"] if "eq0" in hist else [])
        for band in ordered:
            cnt = int(hist.get(band, 0))
            if cnt == 0:
                continue
            rows.append({
                "band": band,
                "round_count": cnt,
                "prob": (cnt / total) if total > 0 else None,
            })
        # Surface any band outside the canonical order (signal, not residual).
        for band, cnt in hist.items():
            if band not in ordered and int(cnt) > 0:
                rows.append({
                    "band": str(band),
                    "round_count": int(cnt),
                    "prob": (int(cnt) / total) if total > 0 else None,
                    "unexpected_band": True,
                })
        return rows

    @staticmethod
    def _build_er_ladder_section(
        prog_by_path: dict[str, Any],
        errors: list[str],
    ) -> dict[str, Any]:
        """Phase 3 — F4 ER ladder per FS-index, with by_dim breakdown.

        Computes: aggregate (all-path) + per-path when multiple real paths exist.
        Money-agnostic: hit_rate + mean_er + er_distribution per FS position.

        Real paths = those whose label does NOT start with 'unknown:' or 'multi:'.
        """
        if not prog_by_path:
            return {
                "available": False,
                "reason": "freespin_progression extractor output absent",
                "extraction_errors": errors,
            }

        real_paths = {
            label: data
            for label, data in prog_by_path.items()
            if not label.startswith("unknown:") and not label.startswith("multi:")
        }
        if not real_paths:
            return {
                "available": False,
                "reason": "no real path data in freespin_progression output",
                "extraction_errors": errors,
            }

        def _build_per_path_er(path_data: dict[str, Any]) -> dict[str, Any]:
            """Build er_ladder rows for one path."""
            er_ladder_raw: dict[str, Any] = path_data.get("er_ladder") or {}
            fs_rows: dict[str, Any] = {}
            for fs_idx_str in sorted(er_ladder_raw, key=lambda x: int(x)):
                entry = er_ladder_raw[fs_idx_str]
                rcount = int(entry.get("round_count", 0))
                er_sum = float(entry.get("er_sum", 0.0))
                er_dist = {str(k): int(v) for k, v in (entry.get("er_distribution") or {}).items()}
                mean_er = er_sum / rcount if rcount > 0 else None
                fs_rows[fs_idx_str] = {
                    "round_count": rcount,
                    "er_distribution": er_dist,
                    "er_sum": er_sum,
                    "mean_er": mean_er,
                }
            return fs_rows

        # Aggregate across all real paths.
        agg_ladder: dict[str, Any] = {}
        all_fs_idxs: set[str] = set()
        for path_data in real_paths.values():
            all_fs_idxs.update((path_data.get("er_ladder") or {}).keys())
        for fi in sorted(all_fs_idxs, key=lambda x: int(x)):
            rcount = 0
            er_sum = 0.0
            er_dist_agg: dict[str, int] = {}
            for path_data in real_paths.values():
                entry = (path_data.get("er_ladder") or {}).get(fi) or {}
                rcount += int(entry.get("round_count", 0))
                er_sum += float(entry.get("er_sum", 0.0))
                for er_val, cnt in (entry.get("er_distribution") or {}).items():
                    er_dist_agg[str(er_val)] = er_dist_agg.get(str(er_val), 0) + int(cnt)
            agg_ladder[fi] = {
                "round_count": rcount,
                "er_distribution": er_dist_agg,
                "er_sum": er_sum,
                "mean_er": er_sum / rcount if rcount > 0 else None,
            }

        section: dict[str, Any] = {
            "available": True,
            "source": "freespin_progression extractor (ExtraRatio field per round)",
            "aggregate": agg_ladder,
        }

        # Per-path breakdown when multiple real paths exist.
        if len(real_paths) >= 2:
            by_dim: dict[str, Any] = {}
            for path_label, path_data in real_paths.items():
                by_dim[path_label] = _build_per_path_er(path_data)
            section["by_dim"] = {"trigger_path": by_dim}

        # Surface alarm buckets.
        alarm_keys = [
            label for label in prog_by_path
            if label.startswith("unknown:") or label.startswith("multi:")
        ]
        if alarm_keys:
            section["alarm_buckets"] = alarm_keys

        if errors:
            section["extraction_errors"] = errors

        return section

    @staticmethod
    def _build_fs_arc_section(
        prog_by_path: dict[str, Any],
        errors: list[str],
    ) -> dict[str, Any]:
        """Phase 3 — F5 FS-index arc (hit rate cliff) per FS position, with by_dim.

        Computes hit_rate + mean_win per FS position for aggregate and per-path.
        The 41%→4.7% cliff is the signature of M275's skin-change mechanic.
        Money-agnostic in structure; reports raw win_sum/round_count.
        """
        if not prog_by_path:
            return {
                "available": False,
                "reason": "freespin_progression extractor output absent",
                "extraction_errors": errors,
            }

        real_paths = {
            label: data
            for label, data in prog_by_path.items()
            if not label.startswith("unknown:") and not label.startswith("multi:")
        }
        if not real_paths:
            return {
                "available": False,
                "reason": "no real path data in freespin_progression output",
                "extraction_errors": errors,
            }

        def _build_per_path_arc(path_data: dict[str, Any]) -> dict[str, Any]:
            """Build fs_arc rows for one path."""
            fs_arc_raw: dict[str, Any] = path_data.get("fs_arc") or {}
            rows: dict[str, Any] = {}
            for fs_idx_str in sorted(fs_arc_raw, key=lambda x: int(x)):
                entry = fs_arc_raw[fs_idx_str]
                rcount = int(entry.get("round_count", 0))
                wcount = int(entry.get("win_round_count", 0))
                wsum = float(entry.get("win_sum", 0.0))
                hit_rate = wcount / rcount if rcount > 0 else None
                mean_win = wsum / wcount if wcount > 0 else None
                rows[fs_idx_str] = {
                    "round_count": rcount,
                    "win_round_count": wcount,
                    "win_sum": wsum,
                    "hit_rate": hit_rate,
                    "mean_win_when_hit": mean_win,
                }
            return rows

        # Aggregate across all real paths.
        all_fs_idxs: set[str] = set()
        for path_data in real_paths.values():
            all_fs_idxs.update((path_data.get("fs_arc") or {}).keys())
        agg_arc: dict[str, Any] = {}
        for fi in sorted(all_fs_idxs, key=lambda x: int(x)):
            rcount = 0
            wcount = 0
            wsum = 0.0
            for path_data in real_paths.values():
                entry = (path_data.get("fs_arc") or {}).get(fi) or {}
                rcount += int(entry.get("round_count", 0))
                wcount += int(entry.get("win_round_count", 0))
                wsum += float(entry.get("win_sum", 0.0))
            agg_arc[fi] = {
                "round_count": rcount,
                "win_round_count": wcount,
                "win_sum": wsum,
                "hit_rate": wcount / rcount if rcount > 0 else None,
                "mean_win_when_hit": wsum / wcount if wcount > 0 else None,
            }

        section: dict[str, Any] = {
            "available": True,
            "source": "freespin_progression extractor (ReMarks Freespin N index per round)",
            "note": (
                "Hit rate declines as FS index increases (skin-change mechanic: "
                "FS 1-3 skin 11 ~41% / FS 4-7 skin 21 ~28% / FS 8-10 skin 31 ~4.7%) "
                "while ExtraRatio climbs monotonically — rare-but-large tail design."
            ),
            "aggregate": agg_arc,
        }

        if len(real_paths) >= 2:
            by_dim: dict[str, Any] = {}
            for path_label, path_data in real_paths.items():
                by_dim[path_label] = _build_per_path_arc(path_data)
            section["by_dim"] = {"trigger_path": by_dim}

        alarm_keys = [
            label for label in prog_by_path
            if label.startswith("unknown:") or label.startswith("multi:")
        ]
        if alarm_keys:
            section["alarm_buckets"] = alarm_keys

        if errors:
            section["extraction_errors"] = errors

        return section

    @staticmethod
    def _build_session_tier_section(
        prog_by_path: dict[str, Any],
        errors: list[str],
    ) -> dict[str, Any]:
        """Phase 3 — session-tier distribution (return_bucket histogram per session win).

        Merges per-path session_tier_hist dicts (additive across paths for aggregate).
        Emits by_dim when multiple real paths exist.
        """
        if not prog_by_path:
            return {
                "available": False,
                "reason": "freespin_progression extractor output absent",
                "extraction_errors": errors,
            }

        real_paths = {
            label: data
            for label, data in prog_by_path.items()
            if not label.startswith("unknown:") and not label.startswith("multi:")
        }
        if not real_paths:
            return {
                "available": False,
                "reason": "no real path data in freespin_progression output",
                "extraction_errors": errors,
            }

        # Aggregate histogram.
        agg_hist: dict[str, int] = {}
        for path_data in real_paths.values():
            for bucket, cnt in (path_data.get("session_tier_hist") or {}).items():
                agg_hist[str(bucket)] = agg_hist.get(str(bucket), 0) + int(cnt)

        agg_total = sum(agg_hist.values())

        def _hist_rows(hist: dict[str, int]) -> list[dict[str, Any]]:
            """Order histogram into RETURN_BUCKET_ORDER rows."""
            total = sum(hist.values())
            rows: list[dict[str, Any]] = []
            ordered = list(RETURN_BUCKET_ORDER) + (["eq0"] if "eq0" in hist else [])
            for band in ordered:
                cnt = int(hist.get(band, 0))
                if cnt == 0:
                    continue
                rows.append({
                    "band": band,
                    "session_count": cnt,
                    "prob": cnt / total if total > 0 else None,
                })
            # Surface any unexpected bucket.
            for band, cnt in hist.items():
                if band not in ordered and int(cnt) > 0:
                    rows.append({
                        "band": str(band),
                        "session_count": int(cnt),
                        "prob": int(cnt) / total if total > 0 else None,
                        "unexpected_band": True,
                    })
            return rows

        section: dict[str, Any] = {
            "available": True,
            "source": (
                "freespin_progression extractor (per-session win_sum → "
                "return_bucket proxy; unit = session win / bet)"
            ),
            "total_sessions": agg_total,
            # Honesty caveat (mirrors _trigger_path_section): under the
            # additive_sessions policy a double-trigger block is credited to
            # EACH matched path, so the per-path session histograms (and thus
            # this aggregate total, built by merging them) count such a block
            # once per path — total_sessions may exceed the distinct block count.
            "total_sessions_note": (
                "additive_sessions: a multi-trigger block counts once per matched "
                "path, so this total may exceed the distinct freespin-block count"
            ),
            "aggregate": _hist_rows(agg_hist),
        }

        if len(real_paths) >= 2:
            by_dim: dict[str, Any] = {}
            for path_label, path_data in real_paths.items():
                hist = {
                    str(k): int(v)
                    for k, v in (path_data.get("session_tier_hist") or {}).items()
                }
                path_total = sum(hist.values())
                by_dim[path_label] = {
                    "total_sessions": path_total,
                    "rows": _hist_rows(hist),
                }
            section["by_dim"] = {"trigger_path": by_dim}

        alarm_keys = [
            label for label in prog_by_path
            if label.startswith("unknown:") or label.startswith("multi:")
        ]
        if alarm_keys:
            section["alarm_buckets"] = alarm_keys

        if errors:
            section["extraction_errors"] = errors

        return section

    def _trigger_path_section(
        self,
        final_acc: dict,
        fs_st: int,
        manifest: dict[str, Any] | None,
        fs_row: dict[str, Any],
        base_spins: int,
        effective_bet_for_rtp: float,
    ) -> dict[str, Any]:
        """F6 — the per-path side-by-side table.

        Paths are labeled from the manifest's trigger_paths declaration; the
        numbers come from the st_extract.trigger_path accumulator. unknown:* /
        multi:* buckets are SURFACED (alarm semantics) per
        feedback_invariant_with_fallback_hides_drift.md.

        rtp_contribution_pp_split is money-agnostic: path win_sum over the
        report's PAID-bet RTP denominator (ctx.effective_bet_for_rtp = bet x
        total paid rounds) x 100 — the parity denominator (sum(pid pp) ==
        summary RTP). NOTE: spin_type_breakdown's per-ST rtp_contribution_pp
        uses a GLOBAL-bet denominator that also counts cost-0 STs' BetAmount
        rows, so on machines whose free rows carry BetAmount the two differ
        (M275: paths sum to 44.414pp paid-bet vs 39.883pp global-bet). The
        invariant this block guarantees is: sum(per-path pp) ==
        share_of_all_win x summary RTP.
        """
        declared: dict[str, Any] = {}
        if isinstance(manifest, dict):
            st_block = (manifest.get("spin_types") or {}).get(str(fs_st))
            if isinstance(st_block, dict):
                tp = st_block.get("trigger_paths")
                if isinstance(tp, dict):
                    declared = tp

        declared_paths: dict[str, str] = {}
        for label, spec in (declared.get("paths") or {}).items():
            display = spec.get("label") if isinstance(spec, dict) else None
            declared_paths[str(label)] = str(display or label)

        acc_paths: dict[str, dict[str, Any]] = (
            (final_acc.get("trigger_paths") or {}).get(str(fs_st)) or {}
        )
        chunks_total = int(final_acc.get("chunks_total") or 0)
        chunks_with_extract = int(final_acc.get("chunks_with_extract") or 0)
        errors = list(final_acc.get("trigger_path_errors") or [])

        if not acc_paths:
            return {
                "available": False,
                "reason": (
                    "no st_extract.trigger_path data in the parsed chunks "
                    f"({chunks_with_extract}/{chunks_total} chunks carried the "
                    "extractor output). The manifest declares trigger_paths; "
                    "the per-ST extraction layer resolves it at parse time — "
                    "a caller that bypasses report_engine's extractor wiring "
                    "produces records without it."
                ),
                "declared_paths": declared_paths,
                "extraction_errors": errors,
            }

        # Split real (declared) paths from surfaced unknown:* / multi:* buckets.
        real_paths: dict[str, dict[str, Any]] = {}
        unknown_paths: dict[str, dict[str, Any]] = {}
        multi_paths: dict[str, dict[str, Any]] = {}
        for label, stats in acc_paths.items():
            if label.startswith("unknown:"):
                unknown_paths[label] = stats
            elif label.startswith("multi:"):
                multi_paths[label] = stats
            else:
                real_paths[label] = stats

        total_sessions = sum(
            int(v.get("session_count") or 0) for v in real_paths.values()
        )
        total_win = sum(float(v.get("win_sum") or 0.0) for v in acc_paths.values())
        fs_total_win = float(fs_row.get("total_win") or 0.0)

        def _path_row(label: str, stats: dict[str, Any]) -> dict[str, Any]:
            sessions = int(stats.get("session_count") or 0)
            rounds = int(stats.get("round_count") or 0)
            win_sum = float(stats.get("win_sum") or 0.0)
            return {
                "path": label,
                "label": declared_paths.get(label, label),
                "session_count": sessions,
                "session_share": (
                    sessions / total_sessions if total_sessions > 0 else None
                ),
                "trigger_rate_per_paid_spin": (
                    sessions / base_spins if base_spins > 0 else None
                ),
                "one_per_n_paid_spins": (
                    base_spins / sessions if sessions > 0 else None
                ),
                "round_count": rounds,
                "win_share": (win_sum / total_win) if total_win > 0 else None,
                "rtp_contribution_pp_split": (
                    win_sum / effective_bet_for_rtp * 100.0
                    if effective_bet_for_rtp > 0 else None
                ),
                "win_band_hist": self._band_rows_from_hist(
                    stats.get("win_band_hist") or {}
                ),
            }

        # Declared paths first (manifest order), then any undeclared real label.
        ordered_labels = [p for p in declared_paths if p in real_paths]
        ordered_labels += [p for p in sorted(real_paths) if p not in ordered_labels]
        path_rows = [_path_row(p, real_paths[p]) for p in ordered_labels]

        section: dict[str, Any] = {
            "available": True,
            "source": (
                "st_extract.trigger_path (per-ST extraction layer; "
                "manifest-declared round_field discriminator). session_count = "
                "distinct opened blocks per path; under the declared "
                "additive_sessions policy a multi-trigger block counts once per "
                "matched path, so path session counts may sum to more than the "
                "distinct block count."
            ),
            "discriminator": declared.get("discriminator"),
            "multi_trigger_policy": declared.get("multi_trigger_policy"),
            "total_sessions": total_sessions,
            "freespin_total_win_share_covered": (
                (total_win / fs_total_win) if fs_total_win > 0 else None
            ),
            "paths": path_rows,
            "extraction_coverage": {
                "chunks_with_extract": chunks_with_extract,
                "chunks_total": chunks_total,
            },
        }
        # ALARM-semantics buckets: surfaced, never merged, never hidden
        # (feedback_invariant_with_fallback_hides_drift.md).
        if unknown_paths:
            section["unknown_paths"] = [
                _path_row(p, unknown_paths[p]) for p in sorted(unknown_paths)
            ]
            section["unknown_paths_alarm"] = (
                "unknown:* buckets carry discriminator values OUTSIDE the "
                "manifest map — a SIGNAL (new trigger vocabulary / drift), "
                "never a residual. Investigate before trusting the path split."
            )
        if multi_paths:
            section["multi_buckets"] = [
                _path_row(p, multi_paths[p]) for p in sorted(multi_paths)
            ]
            section["multi_buckets_note"] = (
                "multi:* buckets appear only in fallback (anchor-walk) mode "
                "for multi-trigger blocks under additive_sessions."
            )
        if errors:
            section["extraction_errors"] = errors
        return section

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Compute and write summary["player_impact"]["freespin_dynamics"].

        Resolves the freespin ST (role=="freespin") and base ST
        (role=="paid_spin") from ctx.machine_spec_manifest (no hardcoded ids).
        If no freespin ST is declared, writes {applicable: False} and returns.
        """
        player_impact = summary.setdefault("player_impact", {})

        # Hard dependency check (feedback_no_silent_swallow.md).
        if "payouts_by_spin_type" not in player_impact:
            raise RuntimeError(
                "freespin_dynamics requires player_impact['payouts_by_spin_type'] "
                "(REQUIRES dependency) but it is absent at emit time — "
                "PayoutsBySpinType did not run or failed upstream."
            )

        manifest = getattr(ctx, "machine_spec_manifest", None)
        fs_st = _resolve_st_by_role(manifest, "freespin")
        base_st = _resolve_st_by_role(manifest, "paid_spin")

        if fs_st is None:
            player_impact["freespin_dynamics"] = {
                "applicable": False,
                "reason": "no SpinType with role 'freespin' in manifest",
            }
            return

        final_acc = final_acc or {}
        next_counts: dict[str, dict[str, int]] = final_acc.get("next_counts") or {}
        bucket_spins: dict[str, dict[str, int]] = final_acc.get("bucket_spins") or {}
        bucket_win: dict[str, dict[str, float]] = final_acc.get("bucket_win") or {}

        # --- round-level stats from spin_type_breakdown (byte-stable) ---
        stb_rows: list[dict[str, Any]] = player_impact.get("spin_type_breakdown") or []
        stb_by_st: dict[int, dict[str, Any]] = {}
        for row in stb_rows:
            try:
                stb_by_st[int(row.get("spin_type"))] = row
            except (TypeError, ValueError):
                continue
        fs_row = stb_by_st.get(fs_st) or {}
        base_row = (stb_by_st.get(base_st) if base_st is not None else {}) or {}

        fs_st_s = str(fs_st)
        base_st_s = str(base_st) if base_st is not None else None

        # ── F1 — session cadence (the grant) ──
        openers = 0
        if base_st_s is not None:
            openers = int((next_counts.get(base_st_s) or {}).get(fs_st_s, 0))
        base_spins = int(base_row.get("spins") or 0)
        fs_spins = int(fs_row.get("spins") or 0)
        fs_out = next_counts.get(fs_st_s) or {}
        fs_out_total = sum(int(v) for v in fs_out.values())
        fs_self = int(fs_out.get(fs_st_s, 0))
        # Chain STRUCTURE corroboration from the reused CROSS_CUTTING plugin.
        # STRUCTURE ONLY: its ExtraRatio surfaces are ReMarks-regex-sourced and
        # default-fill flat-100 on field-borne-ER machines — NEVER cite them.
        bcd = player_impact.get("bonus_chain_dynamics") or {}
        chain_corroboration = {
            "chain_count": bcd.get("chain_count"),
            "avg_chain_length": bcd.get("avg_chain_length"),
            "avg_retriggers_per_chain": bcd.get("avg_retriggers_per_chain"),
            "source": (
                "bonus_chain_dynamics — chain STRUCTURE only. Its ExtraRatio "
                "surfaces (extra_ratio_histogram / max-ratio quantiles / depth "
                "curve) are ReMarks-regex-sourced and DEFAULT-FILLED on "
                "field-borne-ExtraRatio machines; they MUST NOT be cited as "
                "ER coverage (see parser_blind)."
            ),
        }
        session_cadence = {
            "openers": openers,
            "per_paid_spin": (openers / base_spins) if base_spins > 0 else None,
            "one_per_n_paid_spins": (base_spins / openers) if openers > 0 else None,
            "avg_block_length_rounds": (fs_spins / openers) if openers > 0 else None,
            "block_length_note": (
                "avg over CONTIGUOUS freespin blocks (openers = base->freespin "
                "transitions). Back-to-back grants merge into one contiguous "
                "block — the same merge the server's own SummaryWin applies."
            ),
            "continuation": {
                "freespin_to_freespin_transitions": fs_self,
                "exit_transitions": fs_out_total,
                "continuation_prob": (
                    fs_self / fs_out_total if fs_out_total > 0 else None
                ),
                "exit_breakdown": {str(k): int(v) for k, v in fs_out.items()},
                "note": (
                    "for a FIXED-LENGTH granted session this probability is the "
                    "arithmetic of the block length, NOT a win-gated chain — "
                    "do not read it as an escalation mechanic."
                ),
            },
            "chain_structure_corroboration": chain_corroboration,
        }

        # ── F2 — hot-board uplift + band overlays + payid mix ──
        fs_hit = fs_row.get("hit_rate")
        base_hit = base_row.get("hit_rate")
        hot_board_uplift = {
            "freespin_hit_rate": fs_hit,
            "base_hit_rate": base_hit,
            "uplift_ratio": (
                (float(fs_hit) / float(base_hit))
                if (fs_hit is not None and base_hit not in (None, 0, 0.0))
                else None
            ),
        }
        fs_dist = self._bucket_distribution(
            bucket_spins.get(fs_st_s) or {}, bucket_win.get(fs_st_s) or {}
        )
        base_dist = (
            self._bucket_distribution(
                bucket_spins.get(base_st_s) or {}, bucket_win.get(base_st_s) or {}
            )
            if base_st_s is not None else None
        )
        pbst: dict[str, list[dict[str, Any]]] = (
            player_impact.get("payouts_by_spin_type") or {}
        )
        fs_label = self._label_for_st(pbst, fs_st)
        base_label = self._label_for_st(pbst, base_st) if base_st is not None else None
        payid_mix = {
            "freespin_payid_share": self._payid_share(pbst.get(fs_label) or [])
            if fs_label else {},
            "base_payid_share": self._payid_share(pbst.get(base_label) or [])
            if base_label else {},
            "note": (
                "symbol->multiplier paytable is SHARED with the base game; the "
                "freespin board is a hotter symbol/win-frequency MIX (plus a "
                "session multiplier the per-round ExtraRatio field applies — "
                "see parser_blind for the ladder itself)."
            ),
        }

        # ── F2/F5-share — RTP concentration ──
        all_win = sum(float(r.get("total_win") or 0.0) for r in stb_rows)
        fs_total_win = float(fs_row.get("total_win") or 0.0)
        rtp_concentration = {
            "freespin_rtp_contribution_pp": fs_row.get("rtp_contribution_pp"),
            "share_of_all_win": (fs_total_win / all_win) if all_win > 0 else None,
            "fat_tail_ge20x_win_share": fs_dist.get("tail_ge20x_win_share"),
            "zero_win_round_rate": (
                (int((bucket_spins.get(fs_st_s) or {}).get("eq0", 0))
                 / fs_dist["total_spins"])
                if fs_dist.get("total_spins") else None
            ),
            "note": (
                "a rare grant carrying a large share of all payback — compare "
                "session cadence (one per N paid spins) to share_of_all_win "
                "for the concentration ratio."
            ),
        }

        # ── F6 — the trigger-path dimension (two doors into the same room) ──
        effective_bet = float(getattr(ctx, "effective_bet_for_rtp", 0.0) or 0.0)
        trigger_paths_section = self._trigger_path_section(
            final_acc, fs_st, manifest, fs_row, base_spins, effective_bet,
        )

        # ── Phase 3 — ER ladder / FS arc / session-tier from freespin_progression ──
        progression: dict[str, Any] = final_acc.get("progression") or {}
        progression_errors: list[str] = list(final_acc.get("progression_errors") or [])
        fs_st_s_for_prog = str(fs_st)
        prog_for_st: dict[str, Any] = progression.get(fs_st_s_for_prog) or {}
        # The dimension name is "trigger_path" (produced by the extractor).
        prog_dim_name = "trigger_path"
        prog_by_path: dict[str, Any] = prog_for_st.get(prog_dim_name) or {}

        # ── ER Ladder section ──
        er_ladder_section = self._build_er_ladder_section(prog_by_path, progression_errors)

        # ── FS Arc section ──
        fs_arc_section = self._build_fs_arc_section(prog_by_path, progression_errors)

        # ── Session-tier distribution section ──
        session_tier_section = self._build_session_tier_section(prog_by_path, progression_errors)

        # ── F3a / F4 / F5 — parser_blind (updated: F4/F5 now delivered) ──
        parser_blind_remaining: list[str] = []
        if not prog_by_path:
            # No progression data: all items remain parser-blind.
            parser_blind_remaining = [
                "F3a server SummaryWin session-tier taxonomy (the machine's OWN "
                "session multiplier distribution; parser accumulates "
                "TotalWin+FeatureWin only)",
                "F4 one-way ExtraRatio ladder (ExtraRatio FIELD not available in "
                "freespin_progression extractor output for this run)",
                "F5 rise-then-cliff arc (FS-index arc not available in "
                "freespin_progression extractor output for this run)",
                "per-path session-tier distributions / per-path ER & FS arcs "
                "(freespin_progression extractor output absent for this run — "
                "see trigger_paths for per-path round/win/session COUNTS)",
            ]
        else:
            # F4 + F5 + session-tier are now delivered.
            parser_blind_remaining = [
                "F3a server SummaryWin session-tier taxonomy (the machine's OWN "
                "session multiplier distribution; parser accumulates "
                "TotalWin+FeatureWin only — the session_tier_distribution section "
                "above uses return_bucket on our per-session win totals as a proxy)",
                "FS-index x ReelSkin cross-dimension not accumulated (per-skin "
                "hit rates are in the static M275 understanding doc; the FS arc "
                "above is aggregated across all skin phases)",
            ]

        player_impact["freespin_dynamics"] = {
            "applicable": True,
            "freespin_spin_type": fs_st,
            "base_spin_type": base_st,
            "session_cadence": session_cadence,
            "hot_board_uplift": hot_board_uplift,
            "freespin_multiplier_distribution": fs_dist,
            "base_multiplier_distribution": base_dist,
            "payid_mix": payid_mix,
            "rtp_concentration": rtp_concentration,
            "trigger_paths": trigger_paths_section,
            # Phase 3 new sections.
            "er_ladder": er_ladder_section,
            "fs_index_arc": fs_arc_section,
            "session_tier_distribution": session_tier_section,
            "parser_blind": parser_blind_remaining,
            "parser_blind_reason": (
                "F3a SummaryWin tiers need the server's own TierByWin taxonomy "
                "(parser accumulates TotalWin+FeatureWin only). "
                "F4 ER ladder + F5 FS arc are now delivered from the "
                "freespin_progression extractor (Phase 3, 04_dimension_framework.md §6). "
                "When the extractor is absent (old cached chunks without the "
                "extractor wired in), all items revert to parser-blind."
            ),
        }


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# Auto-discovered by feature_registry.discover_features() (globs features/*.py).
# ---------------------------------------------------------------------------
register(FreespinDynamics())
