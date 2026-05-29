"""AnalyzerFeature: bonus_chain_dynamics — Pattern B plugin that OWNS the compute.

Phase C6 of analyzer unbundle (M275-driven) introduced this plugin per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §7.2
and session_artifacts/_impl/phase_c6/brief.md §2.

Phase 2b (analyzer honesty/isolation; see
session_artifacts/_arch_honesty_isolation/07_decision.md §5 Phase 2 + R-11 and
session_artifacts/_impl/phase_extract_2b_bonus_chain/brief.md) carved the
``bonus_chain_dynamics`` dict-BUILD OUT of player_impact_analyzer.py (PIA) and
INTO this plugin's ``emit()`` (mirrors the 2a collect_mechanic carve).  Before
2b the plugin was a Pattern-B stash *shell*: PIA built the fully-formed dict
inline (the ``_quantiles`` closure + ``depth_curve`` loop + the dict literal,
PIA:~3900) and stashed it; this plugin only re-wrote it back unchanged
(passthrough), then added gap #3.  After 2b:

  - PIA's stash ``summary["_bonus_chain_dynamics_data"]`` carries only the RAW
    accumulator inputs (bonus_chain_lengths, all_chains_by_feature, the depth
    histograms, etc. — no compute) plus scatter_feature_names /
    scatter_feature_chain_counts (kept in PIA for the trigger-inference below).
  - ``emit()`` re-sources those raw inputs, builds the ``bonus_chain_dynamics``
    dict VERBATIM (key order / float / 0.0-default / by_feature ``if
    afb["lengths"]`` filter preserved — output byte-identical to the pre-carve
    report), writes ``summary["player_impact"]["bonus_chain_dynamics"]``, then
    closes gap #3 by augmenting each ``payout_ids_top20`` row with a ``notes``
    block that identifies scatter-trigger marker pids.

Why the carve: editing this feature's logic must flip ONLY bonus_chain_dynamics'
feature_hash, not ``compute_base_analyzer_version()`` (the fleet-wide base).  PIA
shed the dict-builder (incl. the ``_quantiles`` closure, now a module-level
helper here), so base shrinks one-time and this feature's compute now lives with
its own hash.

Gap #3: scatter_trigger_marker on payout_ids_top20
---------------------------------------------------
M275 pid 666 (hit=829, win=0, line_id=-1) is a scatter trigger that starts a
NormalCollectionSpin bonus chain.  Before C6, it appeared in payout_ids_top20
as ``cat=paid dom_st=140`` with no special annotation, indistinguishable from
regular pay-id rows that happened to win 0 credits.

C6 adds ``notes: {is_trigger_marker, trigger_target, trigger_target_confidence}``
to every row in payout_ids_top20:

  - ``is_trigger_marker``: True iff pid is in mechanism_registry.scatter_marker_pids
    (win==0 AND no regular line_id != -1 records — same signal as C3 computed
    for payouts_by_spin_type rows).
  - ``trigger_target``: the bonus feature name this scatter triggers,
    inferred from ``all_chains_by_feature`` keys carried in the stash.
    Null when not inferable (e.g. machine has no chain data).
  - ``trigger_target_confidence``: confidence level for the trigger_target inference;
    one of "unique" / "data_inferred" / "fallback_no_chain_data" / "unknown".

Trigger_target inference (R1 Phase 2 d2+d3 correctness fix)
------------------------------------------------------------
payout_ids_top20 is a per-pid aggregate; shape/cols/paylines are per-(pid,ST)
and already live in payouts_by_spin_type (C3).  Only ``notes`` is added here.

Inference algorithm (len-first dispatch per coordinator CR-1):
  1. If scatter_feature_names is empty → trigger_target = None, confidence = "unknown"
     (scatter markers exist but no chain data)
  2. If len(scatter_feature_names) == 1 → trigger_target = that feature name,
     confidence = "unique" (deterministic, no chain_counts needed)
  3. If len(scatter_feature_names) >= 2 AND scatter_feature_chain_counts missing
     from stash → raise RuntimeError (schema drift; caught by pia:5083 emit-error
     handler → feature_errors["bonus_chain_dynamics"])
  4. If len >= 2 AND chain_counts present AND max > 0 → trigger_target = majority
     (highest chain count), confidence = "data_inferred"
  5. If len >= 2 AND chain_counts present AND all zero → trigger_target =
     alphabetical-first (sorted list, deterministic), confidence = "fallback_no_chain_data"
     PLUS companion feature_errors warning per feedback_invariant_with_fallback_hides_drift.md

Chain-count majority vote (d2 correctness fix):
  M275 BEFORE: alphabetical-first → "NewFreespin" (67 chains) — WRONG
  M275 AFTER:  majority vote → "NormalCollectionSpin" (841 chains) — CORRECT

For M275: chain_counts NCS=841 >> NF=67 → "NormalCollectionSpin" (d2 fix).
For M14: scatter_marker_pids is empty → all rows get is_trigger_marker=False.
On tie (all counts equal): max() uses sorted list order (deterministic alphabetical).
This is documented behavior, not a bug.

Stash pattern (Phase 2b — raw inputs; plugin OWNS the build)
------------------------------------------------------------
After R2 Phase 2 (C-1), the PIA inline F6 block NO LONGER writes the public
``bonus_chain_dynamics`` dict into ``summary["player_impact"]``. After Phase 2b
the PIA block no longer BUILDS that dict at all — THIS plugin's emit() builds it
from raw inputs and is the sole writer of
``summary["player_impact"]["bonus_chain_dynamics"]``. Ordering for
machine_mechanics.emit() (which reads that key) is guaranteed by
``machine_mechanics.REQUIRES = ("bonus_chain_dynamics",)`` (R2 C-3); the pre-build
ordering invariant is the C-2 assert on the ``_bonus_chain_dynamics_data`` stash.

The PIA block writes ``summary["_bonus_chain_dynamics_data"]`` (stash key)
carrying (Phase 2b — RAW inputs, no compute):
  - the 9 raw accumulators the dict-build reads: ``bonus_chain_lengths``,
    ``bonus_chain_max_ratios``, ``bonus_total_rounds_global``,
    ``bonus_retrigger_rounds_global``, ``bonus_chain_retrigger_events``,
    ``bonus_extra_ratio_counts``, ``bonus_depth_ratio_count``,
    ``bonus_depth_ratio_sum``, ``all_chains_by_feature``.
  - ``scatter_feature_names``: sorted list of feature names from
    ``all_chains_by_feature`` keys that have non-empty ``lengths`` data
    (same filter as the by_feature construction — omits empty features). Kept in
    PIA (cheap; consumed by this plugin's trigger-inference below).
  - ``scatter_feature_chain_counts``: per-feature chain counts (same filter),
    for the len>=2 majority-vote trigger_target heuristic.

emit() reads the stash, removes it, BUILDS the ``bonus_chain_dynamics`` dict
verbatim (byte-identical to the pre-carve report), writes
``summary["player_impact"]["bonus_chain_dynamics"]``, and augments each row in
``summary["player_impact"]["payout_ids_top20"]`` with ``notes``.

Gap #8 scope decision: Option B
--------------------------------
payout_ids_top20 rows get only ``notes`` (is_trigger_marker + trigger_target).
shape / covered_columns / paylines are per-(pid, ST) and already in
payouts_by_spin_type (C3) — adding them to the per-pid aggregate would require
collapsing across STs which introduces semantic ambiguity.  Option B avoids
that ambiguity.

SCHEMA_VERSION = 1 (bonus_chain_dynamics subkey schema unchanged; notes is new
in payout_ids_top20 rows but payout_ids_top20 is not a plugin-owned key so
no plugin-level SCHEMA_VERSION bump needed).

REQUIRES = () — stash key pre-exists before emit loop.
DECLARED_DEPS = ("_bonus_chain_dynamics_data",) — R2 Phase 2 C-4: Region 2
pre-flight check fires PluginDeclaredDepMissingError if stash is absent.

Per-machine isolation
---------------------
This plugin file is NOT in fresh_slotlab/analyzer/core/ so its addition does
NOT change compute_base_analyzer_version().  Only machines that declare
"bonus_chain_dynamics" in their manifest's analyzer_features list will include
this plugin's hash in their effective_analyzer_version.

Memory feedback honored
-----------------------
- feedback_subprocess_import_suicide_and_module_globals.md:
    register() is a pure list-append — no I/O at import time.
- feedback_no_silent_swallow.md:
    If _bonus_chain_dynamics_data stash key is missing, emit() raises a
    diagnostic RuntimeError (not silently skipped).
    If scatter_feature_chain_counts key is missing from stash when len>=2,
    emit() raises RuntimeError (caught by pia:5083 → feature_errors, not silent).
- feedback_invariant_with_fallback_hides_drift.md:
    is_trigger_marker is an explicit positive signal, not a catch-all fallback.
    trigger_target_confidence is absent for non-trigger rows (explicit "no data"
    versus silent null).
    fallback_no_chain_data confidence emits companion feature_errors warning so
    operators monitoring feature_errors see the degradation signal (not just
    the confidence field which requires specific inspection).
- feedback_capture_drift.md:
    RuntimeError on missing scatter_feature_chain_counts identifies schema drift
    (stash extension not deployed) with a descriptive message.
- feedback_no_parallel_panel_impl.md:
    notes shape mirrors payouts_by_spin_type notes shape (C3 sibling).
    is_trigger_marker logic uses mechanism_registry.scatter_marker_pids (C4 signal)
    not a parallel detector.
- feedback_no_hardcode.md:
    No machine-specific pid values hardcoded; inference derives entirely from
    mechanism_registry (built from observed data + manifest overrides).
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

# Stash key written by the PIA stash builder. Carries the RAW dict-build inputs
# (Phase 2b carve — this plugin builds the dict). Analogous to _collect_mechanic_data
# used by CollectMechanic (C5, also a Phase 2a raw-input stash).
_STASH_KEY = "_bonus_chain_dynamics_data"


# ---------------------------------------------------------------------------
# Private helper — moved VERBATIM from player_impact_analyzer.py (Phase 2b
# carve; was a local closure inside the PIA bonus_chain_dynamics build at
# PIA:~3900). It is PRIVATE to this feature: on the report-production path only
# this plugin's compute calls it (grep-confirmed no other Python caller). Moving
# it here removes its bytes from base_hash so editing this feature's logic flips
# only bonus_chain_dynamics' feature_hash, not base.
# ---------------------------------------------------------------------------
def _quantiles(xs: list[int]) -> dict[str, int | float]:
    if not xs:
        return {"p50": 0, "p90": 0, "p95": 0, "max": 0, "avg": 0.0}
    xs_sorted = sorted(xs)
    n = len(xs_sorted)
    def q(p: float) -> int:
        if n == 0:
            return 0
        idx = min(n - 1, max(0, int(round(p * (n - 1)))))
        return int(xs_sorted[idx])
    return {
        "p50": q(0.50),
        "p90": q(0.90),
        "p95": q(0.95),
        "max": int(xs_sorted[-1]),
        "avg": sum(xs_sorted) / n,
    }


class BonusChainDynamics(AnalyzerFeature):
    """Pattern B plugin that OWNS the bonus_chain_dynamics compute + gap #3 marker.

    extract() / reduce() are no-ops (data flows via the pre-emit stash key).
    emit() re-sources the raw accumulators from the stash, BUILDS the
    ``bonus_chain_dynamics`` dict verbatim (Phase 2b carve — byte-identical to
    the pre-carve report), writes summary["player_impact"]["bonus_chain_dynamics"],
    and augments each payout_ids_top20 row with ``notes`` containing
    is_trigger_marker + trigger_target (gap #3).

    Accumulator structure
    ---------------------
    No accumulator — this plugin uses the stash pattern.
    extract() returns {} always.
    reduce() returns {} always.
    """

    FEATURE_ID: ClassVar[str] = "bonus_chain_dynamics"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("player_impact.bonus_chain_dynamics",)
    SCHEMA_VERSION: ClassVar[int] = 1  # C6: pure carve; notes added to sibling key
    RTP_CONTRIBUTION: ClassVar[bool] = False  # display only
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ("_bonus_chain_dynamics_data",)
    # R2 Phase 2 C-4: DECLARED_DEPS now declares the stash key dependency.
    # The PIA emit loop Region 2 check fires PluginDeclaredDepMissingError
    # (structured analyzer_init_error on disk) if the stash key is absent,
    # instead of the previous soft RuntimeError inside emit().
    # This makes a missing stash (e.g. from a CR-1 cascade) a first-class
    # structured error surfaced to disk, not a swallowed runtime exception.
    REQUIRES: ClassVar[tuple[str, ...]] = ()  # stash key pre-exists before emit loop
    # R1 Phase 2 d2+d3: trigger_target confidence levels
    # "unique"               — len(scatter_feature_names) == 1 (deterministic)
    # "data_inferred"        — len >= 2, chain-count majority vote, max > 0
    # "fallback_no_chain_data" — len >= 2, all chain counts are zero; alphabetical-first
    # "unknown"              — scatter markers exist but scatter_feature_names is empty

    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """No-op — bonus_chain_dynamics uses the pre-emit stash pattern."""
        return {}

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """No-op — no per-chunk accumulator."""
        return {}

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Build bonus_chain_dynamics from raw stash, augment payout_ids_top20.

        Steps
        -----
        1. Read and remove the stash key written by the PIA inline block; read the
           9 RAW accumulator inputs by explicit indexing (fail-loud — no silent
           default that would corrupt report numbers).
        2. BUILD summary["player_impact"]["bonus_chain_dynamics"] verbatim from the
           raw inputs (Phase 2b carve — byte-identical to the pre-carve report).
        3. Infer trigger_target from stash using len-first dispatch (R1 d2+d3).
        4. For each row in summary["player_impact"]["payout_ids_top20"], add
           ``notes`` block:
             - is_trigger_marker: True iff pid in mechanism_registry.scatter_marker_pids
             - trigger_target: feature name or None (gap #3)
             - trigger_target_confidence: "unique"|"data_inferred"|
               "fallback_no_chain_data"|"unknown" (only present when
               is_trigger_marker is True)

        Raises RuntimeError (surfaced as feature_error) if:
          - The stash key is absent (per feedback_no_silent_swallow.md)
          - Any of the 9 raw input keys is absent (Phase 2b carve contract;
            per feedback_no_silent_swallow.md — never silently default)
          - scatter_feature_chain_counts missing from stash when len >= 2
            (per feedback_capture_drift.md + feedback_no_silent_swallow.md)

        CR-2: when confidence == "fallback_no_chain_data", a companion warning
        is written to summary["feature_errors"] so operators scanning that panel
        see the degradation (per feedback_invariant_with_fallback_hides_drift.md).
        """
        if _STASH_KEY not in summary:
            raise RuntimeError(
                f"bonus_chain_dynamics plugin: stash key '{_STASH_KEY}' "
                f"not found in summary. PIA stash builder (Phase 2b carve) may be "
                f"incomplete. Expected it to write this key before the emit loop."
            )

        stash: dict[str, Any] = summary.pop(_STASH_KEY)

        # ── Read the RAW accumulator inputs (Phase 2b carve) ──
        # The PIA stash now carries raw inputs only; this plugin OWNS the
        # dict-build (moved verbatim from PIA:~3900). Per
        # feedback_no_silent_swallow.md: each expected raw key is read by
        # explicit indexing so a missing key raises a diagnostic RuntimeError
        # (never a silent default that would corrupt the report numbers).
        _expected_keys = (
            "bonus_chain_lengths", "bonus_chain_max_ratios",
            "bonus_total_rounds_global", "bonus_retrigger_rounds_global",
            "bonus_chain_retrigger_events", "bonus_extra_ratio_counts",
            "bonus_depth_ratio_count", "bonus_depth_ratio_sum",
            "all_chains_by_feature",
        )
        _missing = [k for k in _expected_keys if k not in stash]
        if _missing:
            raise RuntimeError(
                f"bonus_chain_dynamics plugin: stash '{_STASH_KEY}' is missing "
                f"expected raw input key(s) {_missing!r}. The PIA Phase 2b carve "
                f"stash builder must populate every raw accumulator before the "
                f"emit loop. Refusing to silently default (would corrupt report "
                f"numbers) — see feedback_no_silent_swallow.md."
            )

        bonus_chain_lengths = stash["bonus_chain_lengths"]
        bonus_chain_max_ratios = stash["bonus_chain_max_ratios"]
        bonus_total_rounds_global = stash["bonus_total_rounds_global"]
        bonus_retrigger_rounds_global = stash["bonus_retrigger_rounds_global"]
        bonus_chain_retrigger_events = stash["bonus_chain_retrigger_events"]
        bonus_extra_ratio_counts = stash["bonus_extra_ratio_counts"]
        bonus_depth_ratio_count = stash["bonus_depth_ratio_count"]
        bonus_depth_ratio_sum = stash["bonus_depth_ratio_sum"]
        all_chains_by_feature = stash["all_chains_by_feature"]

        scatter_feature_names: list[str] = stash.get("scatter_feature_names") or []

        # ── Build the bonus_chain_dynamics dict — moved VERBATIM from PIA:~3900.
        # Key insertion order, float forms, 0.0-defaults, and the
        # `if afb["lengths"]` by_feature filter preserved exactly (the
        # byte-identity contract depends on this being a verbatim move, not a
        # rewrite). _quantiles is the module-level helper above (was a local
        # closure in PIA — grep-confirmed private to this build).
        depth_curve: list[dict[str, Any]] = []
        for bucket in ("1", "2-5", "6-10", "11-20", "21+"):
            cnt = bonus_depth_ratio_count.get(bucket, 0)
            tot = bonus_depth_ratio_sum.get(bucket, 0.0)
            depth_curve.append(
                {
                    "depth_bucket": bucket,
                    "rounds": int(cnt),
                    "avg_extra_ratio": (tot / cnt) if cnt > 0 else 0.0,
                }
            )
        bonus_chain_count = len(bonus_chain_lengths)
        bcd: dict[str, Any] = {
            "applicable": bonus_chain_count > 0,
            "source": "ReMarks (Freespin annotation)",
            "chain_count": bonus_chain_count,
            "bonus_round_count": bonus_total_rounds_global,
            "avg_chain_length": (
                sum(bonus_chain_lengths) / bonus_chain_count
                if bonus_chain_count > 0 else 0.0
            ),
            "chain_length_quantiles": _quantiles(bonus_chain_lengths),
            "chain_max_ratio_quantiles": _quantiles(bonus_chain_max_ratios),
            "self_retrigger_round_rate": (
                bonus_retrigger_rounds_global / bonus_total_rounds_global
                if bonus_total_rounds_global > 0 else 0.0
            ),
            "avg_retriggers_per_chain": (
                sum(bonus_chain_retrigger_events) / bonus_chain_count
                if bonus_chain_count > 0 else 0.0
            ),
            # Sorted by ratio ascending so the histogram reads naturally
            # left-to-right; counts are per-round (same round may not
            # double-count because each round emits exactly one ratio).
            "extra_ratio_histogram": [
                {"ratio": r, "rounds": bonus_extra_ratio_counts[r]}
                for r in sorted(bonus_extra_ratio_counts.keys())
            ],
            # Energy ramp: average ExtraRatio at each chain depth bucket.
            # Shows how the MapCollection multiplier escalates as the
            # chain extends.
            "extra_ratio_by_chain_depth": depth_curve,
            # Per-feature breakdown: same structure as aggregate but split
            # by trigger type. NormalCollectionSpin = random (PayId 666),
            # NewFreespin = forced at cycle boundary (no PayId). Empty
            # features are omitted.
            "by_feature": {
                feat: {
                    "chain_count": len(afb["lengths"]),
                    "bonus_round_count": afb["total_rounds"],
                    "avg_chain_length": (
                        sum(afb["lengths"]) / len(afb["lengths"])
                        if afb["lengths"] else 0.0
                    ),
                    "chain_length_quantiles": _quantiles(afb["lengths"]),
                    "chain_max_ratio_quantiles": _quantiles(afb["max_ratios"]),
                    "self_retrigger_round_rate": (
                        afb["retrigger_rounds"] / afb["total_rounds"]
                        if afb["total_rounds"] > 0 else 0.0
                    ),
                }
                for feat, afb in all_chains_by_feature.items()
                if afb["lengths"]
            },
        }

        # ── Step 2: overwrite player_impact.bonus_chain_dynamics (byte-identical) ──
        player_impact = summary.setdefault("player_impact", {})
        player_impact["bonus_chain_dynamics"] = bcd

        # ── Step 3: infer trigger_target for scatter pids (R1 d2+d3) ──
        # Len-first dispatch (coordinator CR-1): determine confidence by len
        # first, then consult chain_counts only when needed (len >= 2).
        # This avoids requiring scatter_feature_chain_counts for single-feature
        # machines where the target is deterministic.
        #
        # Confidence table:
        #   "unique"               — exactly 1 feature (deterministic)
        #   "data_inferred"        — 2+ features, majority by chain count (max > 0)
        #   "fallback_no_chain_data" — 2+ features, all counts zero (alphabetical-first)
        #   "unknown"              — scatter pids exist but scatter_feature_names empty
        scatter_marker_pids: frozenset[str] = ctx.mechanism_registry.scatter_marker_pids

        trigger_target: str | None = None
        trigger_target_confidence: str | None = None
        fallback_pid_str: str | None = None  # set when CR-2 warning is needed

        if scatter_marker_pids and scatter_feature_names:
            n = len(scatter_feature_names)
            if n == 1:
                # Branch: unique — deterministic, no chain_counts needed (d3 fix).
                trigger_target = scatter_feature_names[0]
                trigger_target_confidence = "unique"
            else:
                # Branch: 2+ features — need chain_counts (d2 fix).
                if "scatter_feature_chain_counts" not in stash:
                    # Missing stash key is schema drift (stash extension at pia:4862
                    # not deployed with this plugin). Raise to emit-error handler
                    # (pia:5083 → feature_errors["bonus_chain_dynamics"]).
                    # Per feedback_no_silent_swallow.md + feedback_capture_drift.md:
                    # must raise, not silently fall back to alphabetical-first.
                    raise RuntimeError(
                        f"bonus_chain_dynamics: 'scatter_feature_chain_counts' missing "
                        f"from stash for {n} scatter features {scatter_feature_names!r}. "
                        f"The pia:4862 stash extension (R1 d2) may not be deployed. "
                        f"Cannot disambiguate trigger_target without chain count data."
                    )
                _chain_counts: dict[str, int] = stash["scatter_feature_chain_counts"]
                _max_count = max(
                    (_chain_counts.get(f, 0) for f in scatter_feature_names),
                    default=0,
                )
                if _max_count > 0:
                    # Majority vote — the feature with the highest observed chain count
                    # is the primary scatter trigger target (R1 d2 correctness fix).
                    # M275 BEFORE: alphabetical "NewFreespin" (67 chains) — WRONG
                    # M275 AFTER:  majority "NormalCollectionSpin" (841 chains) — CORRECT
                    # On tie (equal counts): max() picks the first in scatter_feature_names
                    # which is already alphabetically sorted (PIA stash extension uses sorted()).
                    trigger_target = max(
                        scatter_feature_names,
                        key=lambda f: _chain_counts.get(f, 0),
                    )
                    trigger_target_confidence = "data_inferred"
                else:
                    # All chain counts are zero — stash key present but data absent.
                    # Fall back to alphabetical-first (sorted list — deterministic).
                    # CR-2: emit companion feature_errors warning per
                    # feedback_invariant_with_fallback_hides_drift.md so operators
                    # scanning feature_errors see the degradation, not just the
                    # confidence field which requires specific BCD panel inspection.
                    #
                    # NOTE: unreachable in current production — PIA's stash builder
                    # (pia:~4862) filters `if afb.get("lengths")`, so every value
                    # in scatter_feature_chain_counts is >= 1 and max_count is
                    # never 0. This branch + its CR-2 companion warning exist as
                    # forward-compat defensive code for future code paths that might
                    # emit zero-count features. Unit-tested via synthetic all-zero
                    # stash in test_d2_fallback_no_chain_data_warning.py.
                    trigger_target = scatter_feature_names[0]  # sorted → alphabetical-first
                    trigger_target_confidence = "fallback_no_chain_data"
                    # fallback_pid_str set below when we know the scatter pid(s)
                    fallback_pid_str = ",".join(sorted(scatter_marker_pids))
        elif scatter_marker_pids:
            # Scatter markers exist but no by_feature chain data (empty machine).
            trigger_target = None
            trigger_target_confidence = "unknown"
        else:
            # No scatter markers — trigger_target is not applicable.
            trigger_target = None
            trigger_target_confidence = None  # absent for non-trigger machines

        # CR-2: companion feature_errors warning for fallback_no_chain_data state.
        # Written here (after trigger_target_confidence is set) so the warning key
        # is always consistent with what we actually emitted.
        # Per feedback_invariant_with_fallback_hides_drift.md: fallback signals must
        # surface in feature_errors, not only in the data field itself.
        if trigger_target_confidence == "fallback_no_chain_data" and fallback_pid_str is not None:
            # Use a pid-tagged key so multiple scatter pids on the same machine
            # each get their own warning entry (though in practice most machines
            # have a single scatter pid).
            warning_key = f"bonus_chain_dynamics_fallback_{fallback_pid_str}"
            summary.setdefault("feature_errors", {})[warning_key] = {
                "type": "alphabetical_fallback",
                "reason": "scatter_feature_chain_counts all-zero; trigger_target is alphabetical-first, not data-driven",
                "pids": fallback_pid_str,
                "chosen_target": trigger_target,
                "candidates": list(scatter_feature_names),
            }

        # ── Step 4: augment payout_ids_top20 rows (gap #3) ──
        # payout_ids_top20 is guaranteed present (C4 invariant assert writes it
        # before the emit loop starts — see PIA finalization block).
        pid_rows: list[dict[str, Any]] = player_impact.get("payout_ids_top20") or []
        for row in pid_rows:
            pid_str = str(row.get("payout_id", ""))
            is_trigger = pid_str in scatter_marker_pids
            if is_trigger:
                notes: dict[str, Any] = {
                    "is_trigger_marker": True,
                    "trigger_target": trigger_target,
                    "trigger_target_confidence": trigger_target_confidence or "unknown",
                }
            else:
                notes = {
                    "is_trigger_marker": False,
                    # trigger_target and trigger_target_confidence absent for
                    # non-trigger rows — per feedback_invariant_with_fallback_hides_drift.md:
                    # explicit "not applicable" is omission, not null fill.
                }
            row["notes"] = notes


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# ---------------------------------------------------------------------------
register(BonusChainDynamics())
