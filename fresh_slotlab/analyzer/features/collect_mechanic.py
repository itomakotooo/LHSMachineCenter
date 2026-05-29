"""AnalyzerFeature: collect_mechanic — OWNS the collect-mechanic compute.

Phase C5 of analyzer unbundle (M275-driven) introduced this plugin per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §7.2
and session_artifacts/_impl/phase_c5/brief.md §2.1 + §2.3.

Phase 2a (analyzer honesty/isolation; see
session_artifacts/_arch_honesty_isolation/07_decision.md §5 Phase 2 + R-11 and
session_artifacts/_impl/phase_extract_2a_collect_mechanic/brief.md) carved the
dict-building compute OUT of player_impact_analyzer.py (PIA) and INTO this
plugin's ``emit()``.  Before 2a the plugin was a Pattern-B stash *shell*: PIA
built the fully-formed ``collect_mechanic`` dict inline (PIA:4770-4858) and
this plugin only added gap #6 + the alias.  After 2a:

  - PIA's stash ``summary["_collect_mechanic_data"]`` carries only the RAW
    accumulator inputs (collect_robots_seen_total, all_cycle_peaks, the
    upstream_feature_tally, the resolved bonus-feature strings, etc. — no
    compute).
  - ``emit()`` re-sources those raw inputs, builds the ``collect_mechanic`` dict
    VERBATIM (key order / float / None / lambda forms preserved — output is
    byte-identical to the pre-carve report), then adds gap #6
    (``chunk_spin_times_recommendation``) + the ``newfreespin_correction`` alias.

Why the carve: editing this feature's logic must flip ONLY collect_mechanic's
feature_hash, not ``compute_base_analyzer_version()`` (the fleet-wide base).
PIA shed the dict-builder + the two private helpers (collect_feature_match_warning,
build_cycle_observation), so base shrinks one-time and this feature's compute
now lives with its own hash.

The shared bonus-feature resolution (``_resolve_bonus_feature``) stays in PIA
(it has a second consumer on the bonus-chain path); PIA pre-resolves the
(feature, source) strings and hands them to this plugin via the stash.  The
shared RTP-correction math (``_compute_bonus_correction``) lives in
``analyzer.core.parser`` and is imported here (core never imports PIA — no
circular import).

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
The collect-mechanic compute needs many PIA merge-loop accumulators
(collect_robots_seen_total, all_cycle_peaks, all_final_cc_values,
upstream_feature_tally, etc.) that are not available post-emit via chunk_dict.
Like BankruptcySimulation, this plugin uses a pre-emit stash key: PIA writes the
RAW accumulator inputs into ``summary["_collect_mechanic_data"]`` (Phase 2a — no
compute in PIA), and emit() reads those raw inputs, builds the
``collect_mechanic`` dict, adds the gap #6 field, removes the stash, and writes
``summary["collect_mechanic"]``.

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
      Note (R1 d4 decision): avg_bonus_payout is None when bonus_feature is
      unresolved OR when sum(win) == 0.0 with cycles > 0 (data-resolution issue).
      The 0.0 case returns None rather than 0.0 to preserve "unknown" semantics.
      Frontend consumer at app.js:6196 has !=(null) guard already — renders "—".
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
    # Phase 2a carve: the BCM RTP-correction math lives in core (it is SHARED —
    # core never imports PIA, so this is not a circular import). The plugin now
    # OWNS the collect_mechanic compute and invokes this in emit().
    from fresh_slotlab.analyzer.core.parser import _compute_bonus_correction
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    from analyzer.feature_registry import register  # type: ignore[no-redef]
    from analyzer.core.parser import _compute_bonus_correction  # type: ignore[no-redef]

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


# ---------------------------------------------------------------------------
# Private helpers — moved VERBATIM from player_impact_analyzer.py (Phase 2a
# carve, was PIA:744 / PIA:786). They are PRIVATE to this feature: on the
# report-production path only this plugin's compute calls them. External
# callers (tests/backend/test_bcm_resolver.py, scripts/scan_collect_feature_match.py)
# now import them from this module. Moving them here removes their bytes from
# base_hash so editing this feature's logic flips only collect_mechanic's
# feature_hash, not base.
# ---------------------------------------------------------------------------
def collect_feature_match_warning(
    cycle_peaks: list[int],
    upstream_feature_tally: dict,
    resolved_feature: str | None,
    resolved_source: str,
) -> dict:
    """Summary block reporting the BCM-bonus-feature resolution.

    ``warning`` is non-None only when a cycle was observed AND neither
    the config nor the heuristic could identify a bonus feature. In
    that case RTP correction falls through to 0pp and the operator
    needs to either add a config entry or investigate the machine.

    Happy paths (warning is None):
      * cycle_peaks empty → no cycle observed in sample (separate
        ``cycle_observation`` block surfaces the "need more data"
        case; this block stays silent).
      * cycle_peaks non-empty AND resolved_feature is not None →
        pairing known, correction computable.
    """
    has_cycles = len(cycle_peaks) > 0
    features = sorted((upstream_feature_tally or {}).keys())
    warn = None
    if has_cycles and resolved_feature is None:
        warn = (
            "collect cycle detected (from BuffCollectionMap CC resets) "
            "but no bonus feature could be resolved for this machine. "
            "RTP correction will report 0pp which likely under-reports "
            "true RTP. Fix by either: (a) adding this machine to "
            "configs/bcm_pairings.json with the correct bonus_feature, "
            "or (b) resampling so the heuristic has non-zero win data "
            f"for the bonus channel. Features seen: {features!r}"
        )
    return {
        "applicable": has_cycles,
        "known_features": features,
        "bonus_feature": resolved_feature,
        "bonus_feature_source": resolved_source,
        "warning": warn,
    }


def build_cycle_observation(
    collect_robots_seen: int,
    cycle_peaks: list[int],
    final_cc_values: list[int],
) -> dict:
    """Surface the "collect mechanic present but cache too short to
    capture a cycle reset" case (M272-style: one chunk, all 10 robots
    ended exactly at CC=1000 without resetting).

    Without this block, the analyzer silently conflates "mechanic not
    present" with "mechanic present but under-sampled" — both come out
    as `cycle_peaks == []` and RTP correction gives 0pp. The warning
    here distinguishes the two so the operator knows to resume-sample
    rather than treat the current RTP as final.

    Fields:
      * mechanic_detected — ``collect_robots_seen > 0`` (robot's
        rounds carried CollectCount)
      * reset_observed — ``len(cycle_peaks) > 0`` (at least one CC
        reset event observed)
      * cycle_len_lower_bound — ``max(final_cc_values)`` when no reset;
        the cycle length is AT LEAST this (robots can't exceed it if
        they never reset, so the max-final-CC is a lower bound)
      * warning — non-None iff mechanic_detected AND NOT reset_observed
    """
    mechanic = collect_robots_seen > 0
    reset = len(cycle_peaks) > 0
    lower_bound = max(final_cc_values) if final_cc_values else None
    warn = None
    if mechanic and not reset:
        target = lower_bound * 2 if lower_bound else None
        warn = (
            f"collect mechanic detected (CollectCount field present on "
            f"{collect_robots_seen} robots) but no cycle reset observed "
            f"in this sample. Cycle length is at least {lower_bound} "
            f"(max final CC). RTP correction unavailable until resample "
            f"/ resume with ≥ {target} SpinTimes so at least one full "
            f"cycle completes + resets."
        )
    return {
        "mechanic_detected": mechanic,
        "reset_observed": reset,
        "cycle_len_lower_bound": lower_bound,
        "warning": warn,
    }


class CollectMechanic(AnalyzerFeature):
    """Pattern-B stash plugin that OWNS the BCM collect-mechanic compute.

    extract() / reduce() are no-ops (data flows via the pre-emit stash key).
    emit() re-sources the raw accumulators from the stash, builds the
    ``collect_mechanic`` dict (verbatim from the former PIA inline block — see
    module docstring / Phase 2a), adds gap #6 chunk_spin_times_recommendation,
    removes the stash, and writes the final summary["collect_mechanic"] key plus
    the newfreespin_correction alias.

    The collect_mechanic key is TOP-LEVEL in the summary (not under
    player_impact), consistent with the pre-C5 schema.

    Accumulator structure
    ---------------------
    No per-chunk accumulator — this plugin uses the stash pattern.
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
        """Build the collect_mechanic dict, add gap #6, write summary["collect_mechanic"].

        Steps:
          1. Read + validate the stash key's raw inputs (written by PIA).
          2. Build the collect_mechanic dict verbatim (Phase 2a carve).
          3. Add chunk_spin_times_recommendation to clamp_warning (gap #6).
          4. Remove the stash key.
          5. Write summary["collect_mechanic"].
          6. Write backward-compat alias (newfreespin_correction).

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
        preserved (same as the pre-C5 inline backward-compat patch, now owned
        by this plugin after the Phase 2a carve).

        Raises RuntimeError (surfaced as feature_error) if the stash key is
        absent.  Per feedback_no_silent_swallow.md: never silently skip.
        """
        if _STASH_KEY not in summary:
            raise RuntimeError(
                f"collect_mechanic plugin: stash key '{_STASH_KEY}' "
                f"not found in summary. PIA inline carve may be incomplete. "
                f"Expected the inline block to write this key before the emit loop."
            )

        # ── Read the RAW accumulator inputs (Phase 2a carve) ──
        # The PIA stash now carries raw inputs only; this plugin OWNS the
        # dict-build (moved verbatim from PIA:4770-4858). Per
        # feedback_no_silent_swallow.md: each expected raw key is read by
        # explicit indexing so a missing key raises a diagnostic KeyError
        # (never a silent default that would corrupt the report numbers).
        _raw: dict[str, Any] = summary.pop(_STASH_KEY)
        _expected_keys = (
            "collect_robots_seen_total", "collect_count_total",
            "acc_credits_max_global", "total_spins",
            "clamp_pending_robots_total", "clamp_pending_paid_spins_total",
            "total_paid_sessions", "all_cycle_peaks", "all_final_cc_values",
            "total_completed_cycles", "upstream_feature_tally",
            "effective_bet_for_rtp", "bonus_feature", "bonus_feature_source",
        )
        _missing = [k for k in _expected_keys if k not in _raw]
        if _missing:
            raise RuntimeError(
                f"collect_mechanic plugin: stash '{_STASH_KEY}' is missing "
                f"expected raw input key(s) {_missing!r}. The PIA Phase 2a carve "
                f"stash builder must populate every raw accumulator before the "
                f"emit loop. Refusing to silently default (would corrupt report "
                f"numbers) — see feedback_no_silent_swallow.md."
            )

        collect_robots_seen_total = _raw["collect_robots_seen_total"]
        collect_count_total = _raw["collect_count_total"]
        acc_credits_max_global = _raw["acc_credits_max_global"]
        total_spins = _raw["total_spins"]
        clamp_pending_robots_total = _raw["clamp_pending_robots_total"]
        clamp_pending_paid_spins_total = _raw["clamp_pending_paid_spins_total"]
        total_paid_sessions = _raw["total_paid_sessions"]
        all_cycle_peaks = _raw["all_cycle_peaks"]
        all_final_cc_values = _raw["all_final_cc_values"]
        total_completed_cycles = _raw["total_completed_cycles"]
        upstream_feature_tally = _raw["upstream_feature_tally"]
        effective_bet_for_rtp = _raw["effective_bet_for_rtp"]
        _cm_bonus_feat = _raw["bonus_feature"]
        _cm_bonus_src = _raw["bonus_feature_source"]

        # ── Build the collect_mechanic dict — moved VERBATIM from PIA:4770-4858.
        # Key insertion order, float/None/lambda forms preserved exactly (the
        # byte-identity contract depends on this being a verbatim move, not a
        # rewrite). _resolve_bonus_feature stays in PIA (shared); its resolved
        # strings arrive via the stash as _cm_bonus_feat / _cm_bonus_src.
        _cm_cycle_peaks_sorted = sorted(all_cycle_peaks) if all_cycle_peaks else []
        _cm_cycle_median = (
            _cm_cycle_peaks_sorted[len(_cm_cycle_peaks_sorted) // 2]
            if _cm_cycle_peaks_sorted else None
        )
        cm: dict[str, Any] = {
            "applicable": collect_robots_seen_total > 0,
            "robots_with_data": collect_robots_seen_total,
            "total_collects": collect_count_total,
            "max_acc_credits_observed": acc_credits_max_global,
            "avg_spins_between_collects": (
                (total_spins / collect_count_total)
                if collect_count_total > 0
                else None
            ),
            "clamp_warning": {
                "applicable": (
                    collect_robots_seen_total > 0
                    and clamp_pending_robots_total > 0
                ),
                "pending_robots": clamp_pending_robots_total,
                "total_pending_paid_spins": clamp_pending_paid_spins_total,
                "pending_share_of_paid_spins": (
                    (clamp_pending_paid_spins_total / total_paid_sessions)
                    if total_paid_sessions > 0
                    else None
                ),
                "avg_paid_spins_per_collect": (
                    (total_paid_sessions / collect_count_total)
                    if collect_count_total > 0
                    else None
                ),
                "note": (
                    "Pending paid spins were accumulating toward the next collect "
                    "trigger when chunk_spin_times ran out; the bonus those spins "
                    "would have triggered isn't in the sample. If this is a large "
                    "fraction of total paid spins, widen chunk_spin_times and "
                    "rerun to get a tighter RTP estimate."
                ) if (
                    collect_robots_seen_total > 0 and clamp_pending_robots_total > 0
                ) else None,
            },
            "bonus_cycle_correction": {
                "applicable": len(all_cycle_peaks) > 0,
                "bonus_feature": _cm_bonus_feat,
                "bonus_feature_source": _cm_bonus_src,
                "detected_cycle_length": (
                    int(_cm_cycle_median)
                    if _cm_cycle_median is not None else None
                ),
                "completed_cycles_total": total_completed_cycles,
                "robots_with_pending_cycle": sum(
                    1 for fcc in all_final_cc_values
                    if _cm_cycle_median is not None and fcc < _cm_cycle_median
                ),
                # R1 Phase 2 d4: None when bonus_feat unresolved OR cycles==0 OR
                # sum(win)==0 (data-resolution issue — "identified but no measurable win"
                # is semantically distinct from "0 RTP from bonus").  The 0.0/cycles=0.0
                # case from pre-fix is wrong; frontend app.js:6196 has != null guard.
                # d4 regression test: the case-3 (sum==0, cycles>0) edge case cannot
                # occur in any cached fixture machine, so it is tested via the mirror
                # helper `_compute_avg_bonus_payout` in test_d4_avg_bonus_payout_none.py.
                # If you refactor this expression, update that helper too or the test
                # goes stale-green without catching a regression in this line.
                "avg_bonus_payout": (
                    (
                        (lambda _s: _s / total_completed_cycles if _s > 0 else None)(
                            sum(
                                float(e.get("win", 0.0))
                                for e in (upstream_feature_tally.get(_cm_bonus_feat) or {}).values()
                            )
                        )
                        if total_completed_cycles > 0 else None
                    ) if _cm_bonus_feat else None
                ),
                "estimated_correction_pp": _compute_bonus_correction(
                    _cm_bonus_feat,
                    all_cycle_peaks, all_final_cc_values,
                    upstream_feature_tally, total_completed_cycles,
                    effective_bet_for_rtp,
                ),
            },
            "feature_match": collect_feature_match_warning(
                all_cycle_peaks,
                upstream_feature_tally,
                _cm_bonus_feat,
                _cm_bonus_src,
            ),
            "cycle_observation": build_cycle_observation(
                collect_robots_seen_total,
                all_cycle_peaks,
                all_final_cc_values,
            ),
        }

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
        # Same logic as the pre-C5 inline patch (now owned by this plugin).
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
