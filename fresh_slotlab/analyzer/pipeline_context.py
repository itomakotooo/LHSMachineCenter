"""PipelineContext.

Phase C1 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §4.1–§4.3.
Phase 5C: MechanismRegistry removed entirely; the mechanism_registry field is gone.
The dataclass now has 7 fields (down from 8).

PipelineContext
---------------
Frozen dataclass passed as the 3rd argument to every ``AnalyzerFeature.emit()``
call.  Carries the raw accumulator scalars that live as local variables inside
``player_impact_analyzer.main()`` after the merge loop completes.  Plugins that
compute ``rtp_contribution_pp`` or other RTP-denominated metrics need
``effective_bet_for_rtp``; BCM-specific plugins need the BCM scalars.

Frozen so plugins cannot accidentally mutate shared pipeline state.

No import-time I/O per memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# PipelineContext — frozen dataclass, 7 fields (mechanism_registry removed 5C)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PipelineContext:
    """Immutable context bag passed as 3rd argument to every emit() call.

    All fields are required.  The builder (report_engine finalization block)
    populates all fields from local accumulator variables before the emit loop.

    Per 04_v3 §4.1 and §4.3 (manifest field is the v3 Fix 2 addition).

    Fields
    ------
    effective_bet_for_rtp : float
        RTP denominator: total credited bet across all paid spins.
        Source: ``effective_bet_for_rtp`` local var in report_engine post-merge.

    total_spins : int
        Total spins (paid + bonus) across all chunks.
        Source: ``total_spins`` local var in report_engine post-merge.

    total_paid_sessions : int
        Total paid-round sessions (session-centric semantics).
        Source: ``total_paid_sessions`` local var in report_engine post-merge.

    total_paid_spins : int
        Total paid spins (rounds where CostCredits > 0).
        Source: sum(spin_type_paid_rounds.values()) in report_engine post-merge.

    clamp_pending_robots_total : int
        BCM-specific: robots with pending paid spins at analysis cutoff.
        Source: ``clamp_pending_robots_total`` local var in report_engine.
        Used by collect_mechanic plugin for the correction formula.

    robots_with_pending_cycle : int
        BCM-specific: robots that have an incomplete cycle at analysis cutoff.
        Source: computed inline in report_engine finalization block from
        ``all_final_cc_values`` and ``all_cycle_peaks``.
        Used by collect_mechanic plugin for the correction formula.

    manifest : dict[str, Any]
        Resolved (inheritance + per-mode) manifest for this (machine, mode).
        Source: resolved by report_engine before the chunk loop.
        Plugins that need manifest fields at emit() time read from here
        rather than re-loading from disk or stashing via extract().
        Example: ctx.manifest.get("modes", {}).get(str(mode), {}).get("grid", {})

    machine_spec_manifest : dict[str, Any]
        SpinType-native manifest for this machine (phase 3 de-couple).
        Carries the ``spin_types`` role/play declarations and the ``trigger``
        block.  Plugins that derive mechanism flags (freespin_applicable,
        jackpot_applicable, scatter_trigger_pids) read from here via
        ``machine_spec.derive_mechanism_flags(ctx.machine_spec_manifest)``
        (phase 3/5C mandate — mechanism_registry removed).
        Empty dict ({}) when no SpinType-native manifest exists for this machine.
    """

    effective_bet_for_rtp: float
    total_spins: int
    total_paid_sessions: int
    total_paid_spins: int
    clamp_pending_robots_total: int
    robots_with_pending_cycle: int
    manifest: dict[str, Any]
    machine_spec_manifest: dict[str, Any] = field(default_factory=dict)
