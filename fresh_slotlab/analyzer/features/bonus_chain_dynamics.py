"""AnalyzerFeature: bonus_chain_dynamics — Pattern B stash pattern.

Phase C6 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §7.2
and session_artifacts/_impl/phase_c6/brief.md §2.

Replaces the PIA inline F6 block that builds
``summary["player_impact"]["bonus_chain_dynamics"]`` (lines ~3975-4063 in
player_impact_analyzer.py).  Pre-C6 fields are preserved byte-identical;
C6 additionally closes gap #3 by augmenting each ``payout_ids_top20`` row with
a ``notes`` block that identifies scatter-trigger marker pids.

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

Stash pattern
-------------
The PIA inline F6 block continues to write the pre-built ``bonus_chain_dynamics``
dict into ``summary["player_impact"]["bonus_chain_dynamics"]`` (so the C4 invariant
assert and machine_mechanics.emit() ordering contract remain satisfied).

The PIA block additionally writes ``summary["_bonus_chain_dynamics_data"]``
(stash key) carrying:
  - ``bonus_chain_dynamics``: the already-built public dict (passthrough)
  - ``scatter_feature_names``: sorted list of feature names from
    ``all_chains_by_feature`` keys that have non-empty ``lengths`` data
    (same filter as the by_feature construction — omits empty features)

emit() reads the stash, removes it, overwrites
``summary["player_impact"]["bonus_chain_dynamics"]`` (byte-identical), and
augments each row in ``summary["player_impact"]["payout_ids_top20"]`` with
``notes``.

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
DECLARED_DEPS = () — stash key is the delivery mechanism.

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

# Stash key written by PIA inline F6 block (Phase C6 carve).
# Analogous to _collect_mechanic_data used by CollectMechanic (C5).
_STASH_KEY = "_bonus_chain_dynamics_data"


class BonusChainDynamics(AnalyzerFeature):
    """Pattern B plugin: bonus chain dynamics summary panel + gap #3 trigger marker.

    extract() is a no-op (data flows via pre-emit stash key).
    emit() reads the stash, overwrites summary["player_impact"]["bonus_chain_dynamics"]
    (byte-identical to pre-C6 inline), and augments each payout_ids_top20 row
    with ``notes`` containing is_trigger_marker + trigger_target (gap #3).

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
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
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
        """Read stash, overwrite bonus_chain_dynamics, augment payout_ids_top20.

        Steps
        -----
        1. Read and remove the stash key written by PIA inline F6.
        2. Overwrite summary["player_impact"]["bonus_chain_dynamics"] with the
           pre-built dict (byte-identical to pre-C6; pure carve step).
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
          - scatter_feature_chain_counts missing from stash when len >= 2
            (per feedback_capture_drift.md + feedback_no_silent_swallow.md)

        CR-2: when confidence == "fallback_no_chain_data", a companion warning
        is written to summary["feature_errors"] so operators scanning that panel
        see the degradation (per feedback_invariant_with_fallback_hides_drift.md).
        """
        if _STASH_KEY not in summary:
            raise RuntimeError(
                f"bonus_chain_dynamics plugin: stash key '{_STASH_KEY}' "
                f"not found in summary. PIA inline F6 carve may be incomplete. "
                f"Expected the inline block to write this key before the emit loop."
            )

        stash: dict[str, Any] = summary.pop(_STASH_KEY)
        bcd: dict[str, Any] = stash["bonus_chain_dynamics"]
        scatter_feature_names: list[str] = stash.get("scatter_feature_names") or []

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
