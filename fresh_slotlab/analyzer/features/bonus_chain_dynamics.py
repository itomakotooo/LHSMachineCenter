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
  - ``trigger_target_confidence``: "data_inferred" when trigger_target is set
    from chain-dynamics data; "unknown" when null.

Trigger_target inference (Option B per brief §2.4)
---------------------------------------------------
payout_ids_top20 is a per-pid aggregate; shape/cols/paylines are per-(pid,ST)
and already live in payouts_by_spin_type (C3).  Only ``notes`` is added here.

Inference algorithm:
  1. If pid NOT in scatter_marker_pids → trigger_target = None, confidence = n/a
  2. If pid IN scatter_marker_pids AND ``by_feature`` has exactly one feature
     with chain data → trigger_target = that feature name, confidence = "data_inferred"
  3. If pid IN scatter_marker_pids AND ``by_feature`` has multiple features →
     trigger_target = first feature alphabetically, confidence = "data_inferred"
     (conservative — most machines have a single scatter-triggered bonus feature)
  4. If pid IN scatter_marker_pids AND ``by_feature`` is empty →
     trigger_target = None, confidence = "unknown"

For M275: by_feature has "NormalCollectionSpin" → trigger_target = "NormalCollectionSpin".
For M14: scatter_marker_pids is empty → all rows get is_trigger_marker=False.

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
- feedback_invariant_with_fallback_hides_drift.md:
    is_trigger_marker is an explicit positive signal, not a catch-all fallback.
    trigger_target_confidence is absent for non-trigger rows (explicit "no data"
    versus silent null).
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
        3. Infer trigger_target from scatter_feature_names in stash.
        4. For each row in summary["player_impact"]["payout_ids_top20"], add
           ``notes`` block:
             - is_trigger_marker: True iff pid in mechanism_registry.scatter_marker_pids
             - trigger_target: feature name or None (gap #3)
             - trigger_target_confidence: "data_inferred" | "unknown" (only present
               when is_trigger_marker is True)

        Raises RuntimeError (surfaced as feature_error) if the stash key is
        absent.  Per feedback_no_silent_swallow.md: never silently skip.
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

        # ── Step 3: infer trigger_target for scatter pids ──
        # scatter_feature_names are feature names from all_chains_by_feature keys
        # that have non-empty lengths (same filter as by_feature in F6 inline).
        # A scatter-marker pid triggers the bonus feature(s) tracked in by_feature.
        # If there are multiple features, pick the first alphabetically (conservative).
        scatter_marker_pids: frozenset[str] = ctx.mechanism_registry.scatter_marker_pids

        trigger_target: str | None = None
        if scatter_marker_pids and scatter_feature_names:
            # Sort for deterministic pick when multiple features present.
            trigger_target = sorted(scatter_feature_names)[0]
            trigger_target_confidence = "data_inferred"
        elif scatter_marker_pids:
            # Scatter markers exist but no by_feature chain data (empty machine).
            trigger_target = None
            trigger_target_confidence = "unknown"
        else:
            # No scatter markers — trigger_target is not applicable.
            trigger_target = None
            trigger_target_confidence = None  # absent for non-trigger machines

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
