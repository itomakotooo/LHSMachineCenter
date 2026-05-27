"""AnalyzerFeature: collect_mechanic — Pattern B from start.

Phase C5 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §7.2
and session_artifacts/_impl/phase_c5/brief.md §2.1 + §2.3.

Replaces the PIA inline ``collect_mechanic`` top-level block
(lines ~4631-4755 in player_impact_analyzer.py).  Pre-C5 fields are
preserved byte-identical; gap #6 adds a new ``chunk_spin_times_recommendation``
sub-dict to the ``clamp_warning`` section.

Mechanism
---------
The collect mechanic (BCM / BuffCollectionMap) is the machine feature where
robots accumulate credits across paid spins until a threshold (cycle_length) is
reached, then fire a bonus event.  This plugin surfaces:
  - Basic collect statistics (applicable, robots_with_data, total_collects, etc.)
  - Clamp warning: signals when chunk_spin_times cuts mid-cycle (chunk too short
    for the robot to complete its BCM cycle before the run ends).
  - Chunk_spin_times recommendation (gap #6): how large chunk_spin_times should
    be to ensure at least one complete cycle per robot.
  - BCM cycle-bonus RTP correction: estimated lost RTP from mid-cycle truncation.
  - Feature-match: pairs the BCM cycle with its bonus feature.
  - Cycle observation: distinguishes "no BCM" from "BCM but no reset seen".

The ``collect_mechanic`` key is TOP-LEVEL in the summary (not under
``player_impact``), consistent with the pre-C5 schema.

Data sources (stash pattern — same as BankruptcySimulation in C1)
-----------------------------------------------------------------
The PIA inline block uses many local variables (collect_robots_seen_total,
all_cycle_peaks, all_final_cc_values, upstream_feature_tally, etc.) that are
not available post-emit via chunk_dict.  Like BankruptcySimulation, this plugin
uses a pre-emit stash key: the inline block writes the pre-computed
``collect_mechanic`` dict (WITHOUT chunk_spin_times_recommendation) into
``summary["_collect_mechanic_data"]``, and emit() reads it, adds the gap #6
field, removes the stash, and writes ``summary["collect_mechanic"]``.

Gap #6: chunk_spin_times recommendation
---------------------------------------
Added to ``clamp_warning`` sub-dict per user decision (07_decision.md §6 D2):

  recommended_min    = detected_cycle_length * avg_spins_per_collect
  recommended_safety = recommended_min * 1.5
  current            = summary["sampling"]["chunk_spin_times"]
  rationale          = descriptive string

For M275 example: cycle_length=1000, avg_spins_per_collect=5.568 →
  recommended_min    ≈ 5568
  recommended_safety ≈ 8352
  current            = 5000 (too short)

The ``chunk_spin_times_recommendation`` field is present iff:
  - clamp_warning.applicable is True
  - detected_cycle_length is not None
  - avg_paid_spins_per_collect is not None

If any condition is unmet, the sub-dict is absent (no silent default — per
feedback_invariant_with_fallback_hides_drift.md, absent means "no BCM cycle
detected" not "0 spins needed").

Schema (SCHEMA_VERSION = 2)
---------------------------
summary["collect_mechanic"]:
  applicable                    — bool
  robots_with_data              — int
  total_collects                — int
  max_acc_credits_observed      — int | None
  avg_spins_between_collects    — float | None
  clamp_warning:
    applicable                  — bool
    pending_robots              — int
    total_pending_paid_spins    — int
    pending_share_of_paid_spins — float | None
    avg_paid_spins_per_collect  — float | None
    note                        — str | None
    chunk_spin_times_recommendation:  ← NEW in C5 (gap #6)
      current                   — int | None
      recommended_min           — int | None
      recommended_safety        — int | None
      rationale                 — str
  bonus_cycle_correction:
    applicable                  — bool
    bonus_feature               — str | None
    bonus_feature_source        — str
    detected_cycle_length       — int | None
    completed_cycles_total      — int
    robots_with_pending_cycle   — int
    avg_bonus_payout            — float | None
    estimated_correction_pp     — float
  feature_match:
    applicable                  — bool
    known_features              — list[str]
    bonus_feature               — str | None
    bonus_feature_source        — str
    warning                     — str | None
  cycle_observation:
    mechanic_detected           — bool
    reset_observed              — bool
    cycle_len_lower_bound       — int | None
    warning                     — str | None
  newfreespin_correction        — backward-compat alias for bonus_cycle_correction

SCHEMA_VERSION history
----------------------
v1 — pre-C5 inline block (no chunk_spin_times_recommendation field)
v2 — C5 plugin (adds chunk_spin_times_recommendation to clamp_warning)

REGISTERED_FALLBACK_RULES[1] — old v1 summaries on disk have no
  chunk_spin_times_recommendation; frontend renders it as None per fallback.

Per-machine isolation
---------------------
This plugin file is NOT in fresh_slotlab/analyzer/core/ so its addition does
NOT change compute_base_analyzer_version().  Only machines that declare
"collect_mechanic" in their manifest's analyzer_features list will include this
plugin's hash in their effective_analyzer_version.

REQUIRES = () — stash key pre-exists before emit loop.

Memory feedback honored
-----------------------
- feedback_subprocess_import_suicide_and_module_globals.md:
    register() is a pure list-append — no I/O at import time.
- feedback_no_silent_swallow.md:
    If _collect_mechanic_data stash key is missing, emit() raises a diagnostic
    RuntimeError (not silently skipped).
- feedback_invariant_with_fallback_hides_drift.md:
    chunk_spin_times_recommendation is absent (not zero) when clamp_warning
    is not applicable — explicit "no cycle data" signal.
    _payout_groups_status is an explicit named status, not a catch-all bucket.
- feedback_prefer_complex_better.md:
    Stash pattern reused from BankruptcySimulation; no ad-hoc workaround.
- feedback_no_hardcode.md:
    No machine-specific semantics hardcoded; cycle_length and avg_spins come
    from measured data.
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

# Stash key written by PIA inline block (Phase C5 carve).
# Analogous to _bankruptcy_rows used by BankruptcySimulation (C1).
_STASH_KEY = "_collect_mechanic_data"

# Safety multiplier for chunk_spin_times recommendation (gap #6).
_CHUNK_SAFETY_FACTOR: float = 1.5


class CollectMechanic(AnalyzerFeature):
    """Pattern B plugin: BCM collect-mechanic summary panel.

    extract() is a no-op (data flows via pre-emit stash key).
    emit() reads the stash, adds gap #6 chunk_spin_times_recommendation,
    removes the stash, and writes the final summary["collect_mechanic"] key.

    The collect_mechanic key is TOP-LEVEL in the summary (not under
    player_impact), consistent with the pre-C5 schema.

    Accumulator structure
    ---------------------
    No accumulator — this plugin uses the stash pattern.
    extract() returns {} always.
    reduce() returns {} always.
    """

    FEATURE_ID: ClassVar[str] = "collect_mechanic"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("collect_mechanic",)
    SCHEMA_VERSION: ClassVar[int] = 2  # C5: adds chunk_spin_times_recommendation
    RTP_CONTRIBUTION: ClassVar[bool] = False  # display only
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    REQUIRES: ClassVar[tuple[str, ...]] = ()  # stash key pre-exists before emit loop

    # v1 summaries (pre-C5 inline block) have no chunk_spin_times_recommendation.
    # Frontend renders it as None when loading a v1 summary.
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {
        # C5 FIX per critic: chunk_spin_times_recommendation lives at
        # collect_mechanic.clamp_warning.chunk_spin_times_recommendation
        # (nested), NOT at the top of collect_mechanic. Use dotted path so any
        # future fallback engine knows the actual schema location.
        1: {
            "clamp_warning.chunk_spin_times_recommendation": None,
        }
    }

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """No-op — collect_mechanic uses the pre-emit stash pattern."""
        return {}

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """No-op — no per-chunk accumulator."""
        return {}

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Read stash, add gap #6 recommendation, write summary["collect_mechanic"].

        Steps:
          1. Read the stash key (written by the PIA inline block).
          2. Add chunk_spin_times_recommendation to clamp_warning (gap #6).
          3. Remove the stash key.
          4. Write summary["collect_mechanic"].
          5. Write backward-compat alias (newfreespin_correction).

        Gap #6 chunk_spin_times_recommendation
        ----------------------------------------
        formula:
          recommended_min    = detected_cycle_length * avg_spins_per_collect
          recommended_safety = recommended_min * 1.5 (safety factor)
          current            = summary["sampling"]["chunk_spin_times"]

        Present iff: clamp_warning.applicable AND detected_cycle_length is not
        None AND avg_paid_spins_per_collect is not None.

        Backward-compat alias
        ---------------------
        The ``newfreespin_correction`` key in the top-level summary dict is
        preserved (same as the pre-C5 inline backward-compat patch at line ~4825).

        Raises RuntimeError (surfaced as feature_error) if the stash key is
        absent.  Per feedback_no_silent_swallow.md: never silently skip.
        """
        if _STASH_KEY not in summary:
            raise RuntimeError(
                f"collect_mechanic plugin: stash key '{_STASH_KEY}' "
                f"not found in summary. PIA inline carve may be incomplete. "
                f"Expected the inline block to write this key before the emit loop."
            )

        cm: dict[str, Any] = summary.pop(_STASH_KEY)

        # ── Gap #6: add chunk_spin_times_recommendation to clamp_warning ──
        clamp = cm.get("clamp_warning") or {}
        bcc = cm.get("bonus_cycle_correction") or {}

        clamp_applicable = bool(clamp.get("applicable", False))
        detected_cycle_length: int | None = bcc.get("detected_cycle_length")
        avg_spins: float | None = clamp.get("avg_paid_spins_per_collect")

        if (
            clamp_applicable
            and detected_cycle_length is not None
            and avg_spins is not None
            and avg_spins > 0
        ):
            recommended_min = detected_cycle_length * avg_spins
            recommended_safety = recommended_min * _CHUNK_SAFETY_FACTOR

            # Read current chunk_spin_times from the pre-written sampling block.
            # summary["sampling"] is written in the PIA F1 section before emit
            # loop (guaranteed present).
            current_cst: int | None = (
                int(summary.get("sampling", {}).get("chunk_spin_times", 0)) or None
            )

            rationale = (
                f"BCM cycle length {detected_cycle_length} "
                f"* avg {avg_spins:.2f} spins/collect "
                f"= {recommended_min:.0f} spins/cycle; "
            )
            if current_cst is not None and current_cst < recommended_min:
                rationale += (
                    f"current chunk_spin_times {current_cst} is too short "
                    f"for complete cycles — widen to at least "
                    f"{int(recommended_safety)} (safety x{_CHUNK_SAFETY_FACTOR})"
                )
            elif current_cst is not None and current_cst < recommended_safety:
                # C5 FIX per critic: previous text said "covers at least
                # recommended_safety" which is false for M275 (current=5000=
                # recommended_min<7500=safety). Split into borderline case.
                rationale += (
                    f"current chunk_spin_times {current_cst} meets recommended "
                    f"minimum {int(recommended_min)} but is below safety "
                    f"margin {int(recommended_safety)} (x{_CHUNK_SAFETY_FACTOR}) "
                    f"— consider widening for more reliable cycle completion"
                )
            elif current_cst is not None:
                # current >= recommended_safety: fully adequate
                rationale += (
                    f"current chunk_spin_times {current_cst} >= safety margin "
                    f"{int(recommended_safety)} — adequate for cycle completion"
                )
            else:
                rationale += (
                    f"recommended minimum {int(recommended_min)}, "
                    f"safety margin {int(recommended_safety)}"
                )

            clamp["chunk_spin_times_recommendation"] = {
                "current": current_cst,
                "recommended_min": int(recommended_min),
                "recommended_safety": int(recommended_safety),
                "rationale": rationale,
            }
            cm["clamp_warning"] = clamp

        # ── Write top-level collect_mechanic ──
        summary["collect_mechanic"] = cm

        # ── Backward-compat alias: newfreespin_correction ──
        # Same logic as the pre-C5 inline patch at PIA line ~4825.
        # Keep newfreespin_correction pointing at the same dict as
        # bonus_cycle_correction so report-readers expecting the legacy key
        # keep working.  New code should read bonus_cycle_correction directly.
        if "bonus_cycle_correction" in cm and "newfreespin_correction" not in cm:
            cm["newfreespin_correction"] = cm["bonus_cycle_correction"]


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# ---------------------------------------------------------------------------
register(CollectMechanic())
