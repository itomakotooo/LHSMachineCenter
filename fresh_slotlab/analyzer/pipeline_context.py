"""PipelineContext and MechanismRegistry re-export.

Phase C1 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §4.1–§4.3.
Phase C4: MechanismRegistry moved to mechanism_registry.py; this module
re-exports it for backward compatibility with any caller that imports
from pipeline_context.

PipelineContext
---------------
Frozen dataclass passed as the 3rd argument to every ``AnalyzerFeature.emit()``
call.  Carries the raw accumulator scalars that live as local variables inside
``player_impact_analyzer.main()`` after the merge loop completes.  Plugins that
compute ``rtp_contribution_pp`` or other RTP-denominated metrics need
``effective_bet_for_rtp``; BCM-specific plugins need the BCM scalars.

Frozen so plugins cannot accidentally mutate shared pipeline state.

MechanismRegistry
-----------------
Real Tier 1/2/3 detection logic implemented in Phase C4.
Class definition lives in mechanism_registry.py (outside core/) so changes
to detection logic do NOT flip compute_base_analyzer_version() fleet-wide.
This module re-exports MechanismRegistry for callers that import from here.

No import-time I/O per memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Phase C4: real MechanismRegistry lives in mechanism_registry.py.
# Re-export here for backward compatibility with any existing caller.
try:
    from fresh_slotlab.analyzer.mechanism_registry import MechanismRegistry
except ImportError:  # running as standalone script
    from analyzer.mechanism_registry import MechanismRegistry  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# PipelineContext — frozen dataclass, 8 fields per 04_v3 §4.1 + §4.3
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PipelineContext:
    """Immutable context bag passed as 3rd argument to every emit() call.

    All fields are required.  The builder (PIA finalization block) populates
    all fields from local accumulator variables before the emit loop starts.

    Per 04_v3 §4.1 and §4.3 (manifest field is the v3 Fix 2 addition).

    Fields
    ------
    effective_bet_for_rtp : float
        RTP denominator: total credited bet across all paid spins.
        Source: ``effective_bet_for_rtp`` local var in PIA main() post-merge.

    total_spins : int
        Total spins (paid + bonus) across all chunks.
        Source: ``total_spins`` local var in PIA main() post-merge.

    total_paid_sessions : int
        Total paid-round sessions (session-centric semantics).
        Source: ``total_paid_sessions`` local var in PIA main() post-merge.

    total_paid_spins : int
        Total paid spins (rounds where CostCredits > 0).
        Source: sum(spin_type_paid_rounds.values()) in PIA main() post-merge.

    clamp_pending_robots_total : int
        BCM-specific: robots with pending paid spins at analysis cutoff.
        Source: ``clamp_pending_robots_total`` local var in PIA main().
        Used by collect_mechanic plugin for the correction formula.

    robots_with_pending_cycle : int
        BCM-specific: robots that have an incomplete cycle at analysis cutoff.
        Source: computed inline in PIA finalization block from
        ``all_final_cc_values`` and ``all_cycle_peaks``.
        Used by collect_mechanic plugin for the correction formula.

    mechanism_registry : MechanismRegistry
        Single source of truth for machine mechanism detection.
        Available in emit(); always None during extract().
        Also stashed temporarily in summary["_mechanism_registry"] for
        DECLARED_DEPS-based access patterns.

    manifest : dict[str, Any]
        Resolved (inheritance + per-mode) manifest for this (machine, mode).
        Source: already produced by manifest_loader early in main().
        Plugins that need manifest fields at emit() time read from here
        rather than re-loading from disk or stashing via extract().
        Example: ctx.manifest.get("modes", {}).get(str(mode), {}).get("grid", {})
    """

    effective_bet_for_rtp: float
    total_spins: int
    total_paid_sessions: int
    total_paid_spins: int
    clamp_pending_robots_total: int
    robots_with_pending_cycle: int
    mechanism_registry: MechanismRegistry
    manifest: dict[str, Any]
