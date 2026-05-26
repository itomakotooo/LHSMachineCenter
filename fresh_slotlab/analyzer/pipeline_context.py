"""PipelineContext and MechanismRegistry placeholder.

Phase C1 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §4.1–§4.3.

PipelineContext
---------------
Frozen dataclass passed as the 3rd argument to every ``AnalyzerFeature.emit()``
call.  Carries the raw accumulator scalars that live as local variables inside
``player_impact_analyzer.main()`` after the merge loop completes.  Plugins that
compute ``rtp_contribution_pp`` or other RTP-denominated metrics need
``effective_bet_for_rtp``; BCM-specific plugins need the BCM scalars.

Frozen so plugins cannot accidentally mutate shared pipeline state.

MechanismRegistry (placeholder)
---------------------------------
Empty placeholder class.  The actual detection logic (Tier 1/2/3 per §5.2)
ships in Phase C4 of the carve plan.  C1 ships just the class definition so
PipelineContext can carry a typed ``mechanism_registry`` field without depending
on a future module that does not exist yet.

No import-time I/O per memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# MechanismRegistry — Phase C4 fills this; C1 ships a pure placeholder.
# ---------------------------------------------------------------------------

class MechanismRegistry:
    """Single source of truth for machine mechanism detection.

    Phase C1 placeholder — no detection logic yet.  All attributes return
    empty / falsy values, making mechanism-registry-aware emit() plugins
    degrade gracefully to their current (pre-C4) fallback behaviour.

    Phase C4 will replace this class body with the Tier 1/2/3 detection
    algorithm described in 04_v3 §5.2.

    Instance is built once per run by ``_build_mechanism_registry()`` in the
    PIA finalization block and passed through ``PipelineContext`` to every
    ``emit()`` call.  The same instance is also stashed temporarily in
    ``summary["_mechanism_registry"]`` for the DECLARED_DEPS mechanism
    (and cleaned up after the emit loop like all ``_`` prefixed temp keys).
    """

    def __init__(self) -> None:
        # Tier 1/2/3 fields — all falsy so C1 is a no-op for any plugin
        # that reads the registry.  C4 populates these.
        self.jackpot_applicable: bool = False
        self.jackpot_pid_set: frozenset[str] = frozenset()
        self.freespin_applicable: bool = False
        self.scatter_marker_pids: frozenset[str] = frozenset()
        self.payout_groups_applicable: bool = False
        self._detection_source: dict[str, str] = {}

    def to_summary_dict(self) -> dict[str, Any]:
        """Serialise registry state for inclusion in the summary JSON.

        C1 returns a minimal dict.  C4 will return the full portrait.
        """
        return {
            "jackpot_applicable": self.jackpot_applicable,
            "jackpot_pid_set": sorted(self.jackpot_pid_set),
            "freespin_applicable": self.freespin_applicable,
            "scatter_marker_pids": sorted(self.scatter_marker_pids),
            "payout_groups_applicable": self.payout_groups_applicable,
            "_detection_source": dict(self._detection_source),
            "_phase": "C1_placeholder",
        }


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
