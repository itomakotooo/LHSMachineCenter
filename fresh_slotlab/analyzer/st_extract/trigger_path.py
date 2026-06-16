"""Generic declarative trigger-path extractor.

Reads the per-ST manifest block "trigger_paths" to split observed rounds
into labelled paths (scatter, collect_peak, etc.) and accumulate per-path
statistics (round_count, win_sum, session_count, win-band histogram).

ZERO machine-specific code in this file.  No "M275", no pid "666", no
field name "GameplayTriggerType" — everything comes from the manifest
declaration.

Manifest declaration shape (from 03_design.md §4.4):
{
  "discriminator": {
    "kind": "round_field",
    "field": "<field_name>",
    "map": {"<raw_value>": "<path_label>", ...},
    "unmapped_value_policy": "surface_as_unknown_path"
  },
  "fallback": {"kind": "trigger_anchor_walk", ...},
  "paths": {
    "<label>": {
      "opened_by": {"payout_id": "<pid>"} |
                   {"counter": "<field>", "at_peak": <int>},
      "label": "<display_label>"
    },
    ...
  },
  "multi_trigger_policy": "additive_sessions"
}

Discriminator logic
-------------------
- kind "round_field": read the named field from the round dict; look up
  the string value in the map; if found → that path label.  If NOT found
  → "unknown:<value>" (surfaced signal bucket, never merged into a real path).
- No usable discriminator (no discriminator key, or kind != "round_field"):
  fall back to trigger_anchor_walk.  Walk paths.opened_by using
  round_ctx.last_paid_round (the most recent paid round dict, which opened
  the current bonus block):
    - opened_by.payout_id P: match if P present in
      last_paid_round["PayoutIdToWinAmount"] with win == 0.
    - opened_by.counter C + at_peak N: match if last_paid_round[C] == N.
  Exactly one match → all rounds in this block get that label.
  Both match (multi-trigger): per multi_trigger_policy "additive_sessions"
    → session_count +1 to EACH matching path;
    → the block's rounds/wins accumulate in "multi:<pathA>+<pathB>" (sorted
       labels, never silently merged into either real path).
  No match → "unknown:no_anchor" (unchanged).
  last_paid_round is None (no paid round yet in this robot): "unknown:no_anchor".

NOTE on payout_id anchor semantics: payout_id matches WIN==0 pids only
(trigger-anchor semantics — a marker pid that opens a bonus block, not a
paying pid).  If a machine's trigger pid carries a non-zero credit award,
it will NOT match this anchor and will land in "unknown:no_anchor".
Document non-zero-win trigger pids explicitly when onboarding new machines.

Opened_by schema constraint: each path spec's opened_by dict MUST use
exactly ONE of the two anchor kinds (payout_id OR counter+at_peak).
Specifying BOTH in a single opened_by raises ValueError at clone time so
ambiguity is caught early, not silently resolved by code order.

Per-path accumulation
---------------------
  round_count    : rounds whose ST matches the declared ST AND label resolved
  win_sum        : sum of round win_amt for those rounds
  session_count  : distinct block_ids that opened via this path.
                   block_id = round_idx of the opening paid round (from
                   round_ctx["block_id"]).  Machine-insensitive: a bonus
                   block == contiguous non-paid rounds after a paid round.
                   For discriminator mode: block_id is still used so that
                   blocks without a trigger-session record (e.g. BCM-opened
                   blocks) are counted correctly.
  win_band_hist  : {bucket_label: count} using return_bucket(win_amt / bet)
                   from fresh_slotlab.analyzer.core._utils (the same helper
                   the chain/bucket accumulators use — not hand-rolled)

Output shape
------------
{
  "<st_int>": {
    "<path_label>": {
      "round_count": int,
      "win_sum": float,
      "session_count": int,
      "win_band_hist": {<bucket>: int, ...}
    },
    ...
  },
  ...
}
Key is omitted (entire "st_extract" key absent) when no extractors ran,
per the parser's inertness contract.

Per memory/feedback_no_silent_swallow.md: errors inside observe_round are
NOT swallowed here; the parser wraps each extractor call in its own
try/except and surfaces as _extract_error_<EXTRACTOR_ID>.

Per memory/feedback_subprocess_import_suicide_and_module_globals.md:
no module-level I/O; registry state is in st_extract/__init__.py not here;
class methods do not read module globals.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, ClassVar

try:
    from fresh_slotlab.analyzer.st_extract._base import STExtractor
    from fresh_slotlab.analyzer.st_extract import register_extractor
    from fresh_slotlab.analyzer.core._utils import return_bucket
except ImportError:
    from analyzer.st_extract._base import STExtractor  # type: ignore[no-redef]
    from analyzer.st_extract import register_extractor  # type: ignore[no-redef]
    from analyzer.core._utils import return_bucket  # type: ignore[no-redef]


class TriggerPathExtractor(STExtractor):
    """Generic per-ST trigger-path splitter.

    Declared by manifest spin_types blocks carrying "trigger_paths".

    Phase 1 — Dimension data substrate (04_dimension_framework.md §6 Phase 1):
    In addition to the existing "trigger_path" output sub-key (read by
    freespin_dynamics, preserved byte-for-byte), finalize_chunk now also emits
    a "dimensions" sub-key with the full per-(ST, dim, value) metric set:
    round_count, win_sum, paid_round_count, win_round_count, bet_sum,
    bucket_hist, session_count, symbol_counts, next_st_counts.

    The "trigger_path" sub-key is UNCHANGED — freespin_dynamics and the M275
    fwpass golden depend on it.

    GAP-A fix (05_breaker.md §GAP-A): next_st_counts for the PREVIOUS declared
    ST is recorded at the TOP of observe_round, BEFORE the early-return that
    skips undeclared STs.  This captures freespin-session-exit transitions
    (e.g. ST126 -> ST140) that would otherwise be silently dropped.
    """

    EXTRACTOR_ID: ClassVar[str] = "trigger_path"
    DECLARED_IN_KEY: ClassVar[str] = "trigger_paths"

    # Dimension name derived from the manifest's "trigger_paths" block.
    # The dimension system (04_dimension_framework.md §3.2) uses "trigger_path"
    # as the dim_name for every ST block declared under "trigger_paths".
    _DIM_NAME: str = "trigger_path"

    def __init__(self, manifest: dict) -> None:
        self._manifest = manifest
        # ------------------------------------------------------------------
        # Existing chunk-level accumulators (produce the "trigger_path" key).
        # Shape: (st_int, path_label) -> value
        # ------------------------------------------------------------------
        self._chunk_round_count: dict[tuple[int, str], int] = defaultdict(int)
        self._chunk_win_sum: dict[tuple[int, str], float] = defaultdict(float)
        self._chunk_win_band: dict[tuple[int, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # session_count: distinct (robot_idx, block_id) pairs per (st, path).
        # block_id = round_idx of the opening paid round — machine-insensitive
        # block boundary signal that works even without a trigger-session record.
        self._chunk_session_keys: dict[tuple[int, str], set[tuple[int, int]]] = defaultdict(set)

        # ------------------------------------------------------------------
        # Phase 1 — new dimension-level accumulators (produce the "dimensions"
        # key).  Shape: (st_int, dim_name, value) -> value, or
        # (st_int, dim_name, value, col) -> {sym: count} for symbol_counts.
        # dim_name is always _DIM_NAME for the trigger_paths case.
        # ------------------------------------------------------------------
        # (st_int, dim_name, label) -> count / sum / set
        self._dim_round_count: dict[tuple[int, str, str], int] = defaultdict(int)
        self._dim_win_sum: dict[tuple[int, str, str], float] = defaultdict(float)
        self._dim_paid_round_count: dict[tuple[int, str, str], int] = defaultdict(int)
        self._dim_win_round_count: dict[tuple[int, str, str], int] = defaultdict(int)
        self._dim_bet_sum: dict[tuple[int, str, str], float] = defaultdict(float)
        self._dim_bucket_hist: dict[tuple[int, str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._dim_session_keys: dict[tuple[int, str, str], set[tuple[int, int]]] = defaultdict(set)
        # (st_int, dim_name, label, col_str) -> {sym: count}
        self._dim_symbol_counts: dict[tuple[int, str, str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # (st_int, dim_name, label) -> {next_st_int: count}
        self._dim_next_st_counts: dict[tuple[int, str, str], dict[int, int]] = defaultdict(lambda: defaultdict(int))

        # Per-robot state (set by begin_robot).
        self._robot_ctx: dict = {}
        # GAP-A fix: (st_int, dim_name, label) of the most recently observed
        # declared-ST round within this robot.  None before the first declared-ST
        # round and after begin_robot resets.  Used to record the outgoing
        # next_st transition AT THE START of the following observe_round call,
        # BEFORE the early-return that skips undeclared STs — so
        # ST126->ST140 (freespin-exit) transitions are captured even though
        # ST140 is not a declared ST.
        self._prev_dim_key: "tuple[int, str, str] | None" = None

        # Pre-parse the ST-level declarations from the manifest once.
        self._st_declarations: dict[int, dict] = {}  # st_int -> trigger_paths block
        spin_types = manifest.get("spin_types") or {}
        for st_str, st_block in spin_types.items():
            if not isinstance(st_block, dict):
                continue
            tp = st_block.get("trigger_paths")
            if isinstance(tp, dict):
                try:
                    st_int = int(st_str)
                except (TypeError, ValueError):
                    continue
                # RISK-3 FIX: validate opened_by ambiguity at config time.
                # A path spec with BOTH payout_id AND counter+at_peak in a
                # single opened_by dict is ambiguous (code order would silently
                # resolve it; both conditions might apply to different machines).
                # Raise loudly here so the operator catches it at manifest load
                # time, not during a parse run.
                paths_decl: dict = tp.get("paths") or {}
                for path_label, path_spec in paths_decl.items():
                    opened_by = (
                        path_spec.get("opened_by")
                        if isinstance(path_spec, dict)
                        else None
                    )
                    if isinstance(opened_by, dict):
                        has_pid = "payout_id" in opened_by
                        has_counter = "counter" in opened_by or "at_peak" in opened_by
                        if has_pid and has_counter:
                            raise ValueError(
                                f"TriggerPathExtractor: path '{path_label}' "
                                f"(ST={st_str}) has BOTH 'payout_id' AND "
                                f"'counter'/'at_peak' in its opened_by — "
                                f"use exactly one anchor kind per path spec."
                            )
                self._st_declarations[st_int] = tp

    @classmethod
    def clone_for_manifest(cls, manifest: dict) -> "TriggerPathExtractor":
        return cls(manifest)

    # ------------------------------------------------------------------
    # begin_robot
    # ------------------------------------------------------------------

    def begin_robot(self, robot_ctx: dict) -> None:
        """Reset per-robot state.

        robot_ctx keys:
          robot_idx    : int
          trig_sessions: dict[int, dict]  — trigger_round_idx -> session record
          cycle_peak   : int | None
        """
        self._robot_ctx = robot_ctx
        # GAP-A fix: reset the previous-declared-ST key so no cross-robot
        # transition is recorded.
        self._prev_dim_key = None

    # ------------------------------------------------------------------
    # observe_round
    # ------------------------------------------------------------------

    def observe_round(
        self,
        round_dict: dict,
        spin_type: int,
        round_ctx: dict,
    ) -> None:
        """Accumulate per-round signal for declared STs.

        GAP-A fix: if the PREVIOUS round was a declared ST, record the
        prev->current transition into dim_next_st_counts BEFORE the
        early-return that skips undeclared STs.  This captures transitions
        from a declared ST to any undeclared ST (e.g. ST126->ST140 = freespin
        session exits, ~9.8% of ST126 transitions).
        """
        # GAP-A FIX: record outgoing transition from the previous declared-ST
        # round regardless of whether the current spin_type is declared.
        if self._prev_dim_key is not None:
            self._dim_next_st_counts[self._prev_dim_key][spin_type] += 1

        if spin_type not in self._st_declarations:
            # Undeclared ST: clear prev_dim_key so we don't chain further.
            self._prev_dim_key = None
            return

        tp_block: dict = self._st_declarations[spin_type]
        round_idx: int = round_ctx.get("round_idx", 0)
        robot_idx: int = round_ctx.get("robot_idx", 0)
        bet: int = round_ctx.get("bet", 1)
        # block_id: round_idx of the opening paid round (None if no paid round yet).
        block_id: int | None = round_ctx.get("block_id")

        # Resolve win_amt: prefer rule-view win from round_ctx when available
        # (RISK-1 FIX) so that extractors stay consistent with parser attribution.
        win_amt = self._get_win(round_dict, round_ctx)

        # Shared bet/multiplier computation used by both old and new paths.
        effective_bet = float(bet) if bet and bet > 0 else 1.0
        mult = win_amt / effective_bet if effective_bet > 0 else 0.0
        bucket = return_bucket(mult)

        # is_paid: CostCredits > 0 (same signal the parser uses).
        cost_raw = round_dict.get("CostCredits")
        try:
            is_paid = float(cost_raw) > 0.0 if cost_raw is not None else False
        except (TypeError, ValueError):
            is_paid = False

        # Resolve path label(s).
        # In normal cases: one label string.
        # In multi-trigger fallback: list of two matched path labels.
        labels = self._resolve_labels(round_dict, spin_type, tp_block, round_ctx)

        # ------------------------------------------------------------------
        # Existing "trigger_path" sub-key accumulation (UNCHANGED).
        # ------------------------------------------------------------------
        if isinstance(labels, list):
            # Multi-trigger block (fallback mode, additive_sessions policy).
            # Rounds/wins go to the combined "multi:<A>+<B>" bucket.
            multi_label = "multi:" + "+".join(sorted(labels))
            key_multi = (spin_type, multi_label)
            self._chunk_round_count[key_multi] += 1
            self._chunk_win_sum[key_multi] += win_amt
            self._chunk_win_band[key_multi][bucket] += 1
            # Session_count +1 to EACH matching individual path.
            if block_id is not None:
                sess_key = (robot_idx, block_id)
                for path_label in labels:
                    key_path = (spin_type, path_label)
                    self._chunk_session_keys[key_path].add(sess_key)
        else:
            label: str = labels
            key = (spin_type, label)
            self._chunk_round_count[key] += 1
            self._chunk_win_sum[key] += win_amt
            self._chunk_win_band[key][bucket] += 1

            # session_count: count once per distinct block_id per (st, path).
            if block_id is not None:
                sess_key = (robot_idx, block_id)
                if sess_key not in self._chunk_session_keys[key]:
                    self._chunk_session_keys[key].add(sess_key)

        # ------------------------------------------------------------------
        # Phase 1 — new "dimensions" sub-key accumulation.
        # The dim_name is _DIM_NAME ("trigger_path") for all trigger_paths
        # declarations.  We accumulate stats for the same resolved label(s).
        # ------------------------------------------------------------------
        dim_name = self._DIM_NAME

        # Determine the single effective label for dimension accumulation.
        # Multi-trigger → "multi:<A>+<B>" bucket (same label as the old path).
        if isinstance(labels, list):
            eff_label: str = "multi:" + "+".join(sorted(labels))
        else:
            eff_label = labels  # type: ignore[assignment]

        dim_key = (spin_type, dim_name, eff_label)

        self._dim_round_count[dim_key] += 1
        self._dim_win_sum[dim_key] += win_amt
        self._dim_bet_sum[dim_key] += effective_bet
        self._dim_bucket_hist[dim_key][bucket] += 1
        if is_paid:
            self._dim_paid_round_count[dim_key] += 1
        if win_amt > 0.0:
            self._dim_win_round_count[dim_key] += 1

        # session_count via (robot_idx, block_id).
        if block_id is not None:
            sess_key = (robot_idx, block_id)
            self._dim_session_keys[dim_key].add(sess_key)
            # For multi-trigger, also +1 to each individual path's session set
            # (mirrors the old trigger_path logic: additive_sessions).
            if isinstance(labels, list):
                for path_label in labels:
                    ind_dim_key = (spin_type, dim_name, path_label)
                    self._dim_session_keys[ind_dim_key].add(sess_key)

        # symbol_counts: from StopSymbolsByCol when present.
        stop_syms = round_dict.get("StopSymbolsByCol")
        if isinstance(stop_syms, dict):
            for col_raw, sym_val in stop_syms.items():
                col_str = str(col_raw)
                sym_str = str(sym_val) if sym_val is not None else "None"
                sym_key = (spin_type, dim_name, eff_label, col_str)
                self._dim_symbol_counts[sym_key][sym_str] += 1

        # Update _prev_dim_key for the NEXT call's GAP-A transition.
        self._prev_dim_key = dim_key

    # ------------------------------------------------------------------
    # finalize_chunk
    # ------------------------------------------------------------------

    def finalize_chunk(self) -> dict:
        """Return per-(st, path) statistics as a JSON-serializable dict.

        The returned dict is stored in rec["st_extract"]["trigger_path"] by
        the parser (EXTRACTOR_ID = "trigger_path").  Its top-level shape is:

          {
            "<st_int>":   { "<path_label>": {4-stat-dict}, ... },  # numeric ST keys
            ...
            "dimensions": { "<st_int>": { "<dim_name>": { "<value>": {9-stat-dict} } } }
          }

        That is: the backward-compat 4-stat path data is at the TOP LEVEL of
        this dict, keyed by numeric ST strings ("126", etc.).  "dimensions" is
        a SIBLING key at that same top level, NOT a wrapper around the ST data.

        A consumer reading st_extract["trigger_path"]["trigger_path"] gets None
        — the flat path data is directly at st_extract["trigger_path"]["126"].

        freespin_dynamics.extract() iterates the top-level keys and uses
        `if not str(st_key).isdigit(): continue` to skip "dimensions".  This
        is an intentional transitional guard: the clean architecture (a
        "dimensions" EXTRACTOR_ID that owns this output entirely) is deferred
        to Phase 2, when freespin_dynamics migrates off the legacy flat key.

        Backward-compat 4-stat shape (per numeric ST key):
          "<st_int>": {
            "<path_label>": {
              "round_count": int,
              "win_sum": float,
              "session_count": int,
              "win_band_hist": {<bucket>: int, ...}
            }, ...
          }

        "dimensions" value shape (Phase 1 data substrate,
        04_dimension_framework.md §6):
          {
            "<st_int>": {
              "<dim_name>": {          # e.g. "trigger_path"
                "<value>": {           # e.g. "scatter", "collect_peak"
                  "round_count": int,
                  "win_sum": float,
                  "paid_round_count": int,
                  "win_round_count": int,
                  "bet_sum": float,
                  "bucket_hist": {<bucket>: int, ...},
                  "session_count": int,
                  "symbol_counts": {<col>: {<sym>: int}, ...},
                  "next_st_counts": {<next_st_int>: int, ...}
                  # PHASE-2 NOTE (a): next_st_counts keys are int in memory
                  # but become str after JSON round-trip from stored reports.
                  # Phase-2 consumers reading from the report JSON must use
                  # str keys (e.g. "126", not 126).
                }, ...
              }
            }, ...
          }

        IMPORTANT: this method also RESETS all chunk-level accumulators so
        the same extractor instance can be reused across chunks by the
        report_engine.  The design pattern is:
          for each chunk:
            for each robot: begin_robot() ... observe_round() ...
            chunk_rec["st_extract"] = extractor.finalize_chunk()  # also resets
        """
        # ------------------------------------------------------------------
        # 1. Build the existing "trigger_path" backward-compat output.
        # Shape is BYTE-FOR-BYTE identical to the pre-Phase-1 output.
        # freespin_dynamics reads this key — it MUST NOT change.
        # ------------------------------------------------------------------
        trigger_path_result: dict[str, dict[str, Any]] = {}
        all_keys = set(self._chunk_round_count) | set(self._chunk_win_sum)
        for (st_int, label) in all_keys:
            st_str = str(st_int)
            if st_str not in trigger_path_result:
                trigger_path_result[st_str] = {}
            trigger_path_result[st_str][label] = {
                "round_count": int(self._chunk_round_count.get((st_int, label), 0)),
                "win_sum": float(self._chunk_win_sum.get((st_int, label), 0.0)),
                "session_count": int(len(self._chunk_session_keys.get((st_int, label), set()))),
                "win_band_hist": dict(self._chunk_win_band.get((st_int, label), {})),
            }

        # ------------------------------------------------------------------
        # 2. Build the new "dimensions" output sub-key.
        # Shape: {st_str: {dim_name: {value: {all_stats}}}}
        # ------------------------------------------------------------------
        dimensions_result: dict[str, dict[str, dict[str, Any]]] = {}

        # Collect all (st_int, dim_name, value) keys from all dimension accumulators.
        all_dim_keys: set[tuple[int, str, str]] = (
            set(self._dim_round_count)
            | set(self._dim_win_sum)
            | set(self._dim_next_st_counts)
        )

        for (st_int, dim_name, value) in all_dim_keys:
            st_str = str(st_int)
            if st_str not in dimensions_result:
                dimensions_result[st_str] = {}
            if dim_name not in dimensions_result[st_str]:
                dimensions_result[st_str][dim_name] = {}

            # Collect symbol_counts for this (st, dim_name, value).
            # PHASE-2 NOTE (b): this loop is O(D×C) where D = number of
            # distinct (st,dim,value) keys and C = number of distinct
            # (st,dim,value,col) keys.  For M275 (2 values, 5 cols) this
            # is negligible.  If a future machine has a high-cardinality
            # discriminator that produces many "unknown:<v>" buckets, D can
            # grow unboundedly and this scan becomes expensive.  Phase 2
            # should restructure symbol_counts into a nested dict keyed by
            # (st,dim,value) → {col→{sym→count}} to eliminate the scan.
            sym_counts: dict[str, dict[str, int]] = {}
            for sym_key, sym_map in self._dim_symbol_counts.items():
                if sym_key[:3] == (st_int, dim_name, value):
                    col_str = sym_key[3]
                    sym_counts[col_str] = dict(sym_map)

            # next_st_counts: {next_st_int: count} → JSON keys as int.
            next_st_raw = dict(self._dim_next_st_counts.get((st_int, dim_name, value), {}))
            next_st_counts_out = {int(k): int(v) for k, v in next_st_raw.items()}

            dimensions_result[st_str][dim_name][value] = {
                "round_count": int(self._dim_round_count.get((st_int, dim_name, value), 0)),
                "win_sum": float(self._dim_win_sum.get((st_int, dim_name, value), 0.0)),
                "paid_round_count": int(self._dim_paid_round_count.get((st_int, dim_name, value), 0)),
                "win_round_count": int(self._dim_win_round_count.get((st_int, dim_name, value), 0)),
                "bet_sum": float(self._dim_bet_sum.get((st_int, dim_name, value), 0.0)),
                "bucket_hist": dict(self._dim_bucket_hist.get((st_int, dim_name, value), {})),
                "session_count": int(len(self._dim_session_keys.get((st_int, dim_name, value), set()))),
                "symbol_counts": sym_counts,
                "next_st_counts": next_st_counts_out,
            }

        # ------------------------------------------------------------------
        # 3. Reset ALL chunk-level accumulators so this instance can be
        # reused across chunks by report_engine.
        # ------------------------------------------------------------------
        # Existing accumulators.
        self._chunk_round_count = defaultdict(int)
        self._chunk_win_sum = defaultdict(float)
        self._chunk_win_band = defaultdict(lambda: defaultdict(int))
        self._chunk_session_keys = defaultdict(set)
        # Phase 1 dimension accumulators.
        self._dim_round_count = defaultdict(int)
        self._dim_win_sum = defaultdict(float)
        self._dim_paid_round_count = defaultdict(int)
        self._dim_win_round_count = defaultdict(int)
        self._dim_bet_sum = defaultdict(float)
        self._dim_bucket_hist = defaultdict(lambda: defaultdict(int))
        self._dim_session_keys = defaultdict(set)
        self._dim_symbol_counts = defaultdict(lambda: defaultdict(int))
        self._dim_next_st_counts = defaultdict(lambda: defaultdict(int))
        # Also reset prev_dim_key — finalize_chunk starts a new chunk context.
        self._prev_dim_key = None
        # BUG-1 / BUG-2 FIX: clear per-chunk error accumulators AFTER the
        # parser has already snapshotted them (parser reads _obs_errors and
        # _begin_robot_error BEFORE calling finalize_chunk — see parser.py
        # finalize block).  Clearing here ensures chunk N's errors do not
        # bleed into chunk N+1.  Extractor-state contract:
        #   parser snapshots _obs_errors + _begin_robot_error
        #   → calls finalize_chunk() (returns result, resets ALL state)
        #   → surfaces snapshots as _extract_error_<ID> if non-empty.
        self._obs_errors: list[str] = []  # type: ignore[attr-defined]
        self._begin_robot_error: str | None = None  # type: ignore[attr-defined]

        # ------------------------------------------------------------------
        # 4. Return the combined result.
        # The parser stores this under rec["st_extract"]["trigger_path"].
        # Consumers of the "trigger_path" sub-key (freespin_dynamics) see
        # trigger_path_result unchanged.  The "dimensions" sub-key is NEW
        # and only present when declared STs were observed.
        # ------------------------------------------------------------------
        out: dict[str, Any] = {}
        if trigger_path_result:
            # Emit backward-compat data at the top-level of this dict (the
            # parser stores the whole dict under rec["st_extract"]["trigger_path"],
            # so freespin_dynamics which does
            #   st_extract.get("trigger_path") → {st: {label: {...}}}
            # must receive the flat {st: {label: {...}}} shape, NOT wrapped
            # under a "trigger_path" sub-key again).
            # THEREFORE: we return trigger_path_result directly as the top-level
            # shape, and add "dimensions" as an ADDITIONAL key at the same level.
            out = dict(trigger_path_result)
        if dimensions_result:
            out["dimensions"] = dimensions_result
        return out

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_win(self, round_dict: dict, round_ctx: dict | None = None) -> float:
        """Extract win amount for a round.

        RISK-1 FIX: prefer the rule-view win from round_ctx["win"] when
        present (the parser already ran extract_round_win with the full
        rule set before calling observe_round, and passes the result via
        round_ctx).  Fall back to raw WinCredits / WinAmount only when
        round_ctx is absent or has no "win" key.

        On M275, raw WinCredits == rule-view win for all bonus rounds, so
        existing M275 numbers are UNCHANGED by this fix.  Future machines
        with SynthesizePayIdRule or chunk-residual attribution will
        automatically use the correct attributed win.
        """
        if round_ctx is not None and "win" in round_ctx:
            v = round_ctx["win"]
            try:
                fv = float(v)
                return fv if fv > 0.0 else 0.0
            except (TypeError, ValueError):
                pass
        # Fallback: raw field from round dict.
        raw = round_dict.get("WinCredits")
        if raw is None:
            raw = round_dict.get("WinAmount")
        if raw is None:
            return 0.0
        try:
            v = float(raw)
            return v if v > 0.0 else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _resolve_labels(
        self,
        round_dict: dict,
        spin_type: int,
        tp_block: dict,
        round_ctx: dict,
    ) -> "str | list[str]":
        """Resolve the path label(s) for this round.

        Returns:
          - str: a single label (normal case, discriminator hit, or unknown).
          - list[str]: exactly 2 labels when multi-trigger in fallback mode.

        Priority:
          1. discriminator.kind == "round_field": field lookup in round_dict.
             Returns a single str always (mapped or "unknown:<value>").
          2. Fallback (trigger_anchor_walk): declaration-driven walk using
             round_ctx.last_paid_round (the opening paid round of the current
             bonus block).
             - Exactly one path matches → str label.
             - Both paths match (multi-trigger) → list of two labels.
             - No match → "unknown:no_anchor".
        """
        discriminator = tp_block.get("discriminator")
        if isinstance(discriminator, dict) and discriminator.get("kind") == "round_field":
            return self._label_from_round_field(round_dict, discriminator)

        # No usable discriminator — fall back to declaration-driven anchor walk.
        return self._label_from_anchor_walk(tp_block, round_ctx)

    def _label_from_round_field(self, round_dict: dict, disc: dict) -> str:
        """Label via field discriminator.

        disc = {"kind": "round_field", "field": "<name>",
                "map": {"<raw_value>": "<label>", ...},
                "unmapped_value_policy": "surface_as_unknown_path"}

        The raw field value is cast to str before map lookup because JSON
        map keys are always strings (the manifest uses "0", "2", etc.) while
        the rawdata field may be int or str.  Per spec, unmapped values →
        "unknown:<value>" (surfaced signal, never merged into a path).
        """
        field_name: str = disc.get("field", "")
        raw_val = round_dict.get(field_name)
        if raw_val is None:
            return "unknown:None"
        # BUG-3 FIX: normalize float-valued integers before str().
        # JSON serialisers may deliver integer-valued fields as floats
        # (e.g. 2.0 instead of 2).  str(2.0) = "2.0" != "2" (the manifest
        # map key), so naive str() silently misclassifies to unknown:2.0.
        # Normalise: a float equal to its int representation becomes that int.
        # Genuine non-integral floats (e.g. 1.5) keep their repr and surface
        # as unknown:<value> as intended.
        if isinstance(raw_val, float) and raw_val == int(raw_val):
            raw_val = int(raw_val)
        val_str = str(raw_val)
        val_map: dict = disc.get("map") or {}
        label = val_map.get(val_str)
        if label is not None:
            return str(label)
        # Unmapped value → surfaced unknown bucket (per spec, NOT merged).
        return f"unknown:{val_str}"

    def _label_from_anchor_walk(
        self,
        tp_block: dict,
        round_ctx: dict,
    ) -> "str | list[str]":
        """Label via declaration-driven anchor walk (fallback mode).

        Uses round_ctx["last_paid_round"] — the opening paid round dict of
        the current bonus block — to check opened_by declarations.

        opened_by.payout_id P:
          Match if P is present as a key in last_paid_round["PayoutIdToWinAmount"]
          with win == 0.  (A bonus-trigger payout typically awards 0 credits
          and just opens the bonus round.)

        opened_by.counter C + at_peak N:
          Match if last_paid_round[C] == N.
          (A BCM counter-milestone trigger: the paid round that completed the
          counter cycle is the opener.)

        Multi-trigger (additive_sessions policy):
          Both paths match → return list of both labels.  Caller routes
          rounds/wins to "multi:<A>+<B>" and +1 session to each path.

        No last_paid_round (paid round hasn't been seen yet in this robot):
          → "unknown:no_anchor"

        No path matches:
          → "unknown:no_anchor"
        """
        last_paid: dict | None = round_ctx.get("last_paid_round")
        if last_paid is None:
            return "unknown:no_anchor"

        paths: dict = tp_block.get("paths") or {}
        matched_labels: list[str] = []

        payout_map: dict = last_paid.get("PayoutIdToWinAmount") or {}
        # Normalise payout_map keys to str for comparison.
        payout_map_str = {str(k): v for k, v in payout_map.items()}

        for path_label, path_spec in paths.items():
            opened_by = path_spec.get("opened_by") if isinstance(path_spec, dict) else None
            if not isinstance(opened_by, dict):
                continue

            # Case A: payout_id anchor.
            # P present in PayoutIdToWinAmount with win == 0.
            if "payout_id" in opened_by:
                pid_str = str(opened_by["payout_id"])
                if pid_str in payout_map_str:
                    win_val = payout_map_str[pid_str]
                    try:
                        win_float = float(win_val) if win_val is not None else 0.0
                    except (TypeError, ValueError):
                        win_float = 0.0
                    if win_float == 0.0:
                        matched_labels.append(path_label)
                        continue

            # Case B: counter + at_peak anchor.
            # last_paid_round[C] == N.
            if "counter" in opened_by and "at_peak" in opened_by:
                counter_field: str = str(opened_by["counter"])
                try:
                    at_peak_val = int(opened_by["at_peak"])
                except (TypeError, ValueError):
                    continue
                raw_counter = last_paid.get(counter_field)
                if raw_counter is not None:
                    try:
                        if int(raw_counter) == at_peak_val:
                            matched_labels.append(path_label)
                    except (TypeError, ValueError):
                        pass

        if len(matched_labels) == 0:
            return "unknown:no_anchor"
        if len(matched_labels) == 1:
            return matched_labels[0]
        # Multi-trigger: return list so caller can handle additive_sessions.
        return matched_labels


# ---------------------------------------------------------------------------
# Self-registration — fires at module import time
# ---------------------------------------------------------------------------
register_extractor(TriggerPathExtractor({}))
