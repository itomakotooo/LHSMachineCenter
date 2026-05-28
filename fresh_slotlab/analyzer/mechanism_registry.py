"""MechanismRegistry — single source of truth for machine mechanism detection.

Phase C4 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §5.2.

Replaces the C1 placeholder body in pipeline_context.py with real Tier 1/2/3
detection logic.  The class is defined here (outside core/) so changes to
detection logic do NOT flip compute_base_analyzer_version() for the entire
fleet — only machines that declare the machine_mechanics plugin will be
affected via their effective_analyzer_version.

Tier precedence (highest → lowest)
------------------------------------
Tier 1 — manifest["mechanism_overrides"] dict — explicit operator declaration.
Tier 2 — inferred from merge-loop accumulators available post-Phase A:
  freespin  : len(bonus_chain_lengths) > 0
  jackpot   : NOT IMPLEMENTED (intentionally deferred). Tier 3
              (PID >= 10,000 OR JackpotIds field) is correct for all known
              fleet machines as of R2. Add Tier 2 only if a machine has
              jackpot PIDs < 10,000 with no JackpotIds field.
Tier 3 — raw evidence:
  jackpot   : payout_id_win PIDs with int(pid) >= 10000 (Path A)
              UNION jackpot_ids_seen from raw JackpotIds field (Path B)
  freespin  : total_freespin_chain_spins > 0 (only when Tier 2 has no signal)
  scatter   : PIDs with win==0 AND no regular line_id != -1 records
  payout_groups : any gid != 0 with win > 0

Memory feedback honored
-----------------------
- feedback_no_silent_swallow.md:
    _detection_source dict carries audit trail for every field.
    No field is silently set to a fallback without recording which tier fired.
- feedback_invariant_with_fallback_hides_drift.md:
    _detection_source is an explicit required output, not optional.
    The machine_mechanics plugin surfaces it as "_detection_source" per field.
- feedback_subprocess_import_suicide_and_module_globals.md:
    No import-time I/O.  MechanismRegistry.__init__ does only pure computation.
- feedback_no_hardcode.md:
    No machine-specific semantics hardcoded — PID thresholds and field names
    come from the data or manifest, not from machine-id lookups.
"""
from __future__ import annotations

from typing import Any


class MechanismRegistry:
    """Single source of truth for machine mechanism detection.

    Build once per run via ``build()`` class method.  Passed through
    ``PipelineContext.mechanism_registry`` to every ``emit()`` call.

    Attributes
    ----------
    jackpot_applicable : bool
    jackpot_pid_set : frozenset[str]
    freespin_applicable : bool
    scatter_marker_pids : frozenset[str]
    payout_groups_applicable : bool
    _detection_source : dict[str, str]
        Per-field audit trail: which tier fired for each mechanism flag.
        Keys: "jackpot_applicable", "jackpot_pid_set", "freespin_applicable",
              "scatter_marker_pids", "payout_groups_applicable".
        Values: tier labels like "tier1_manifest", "tier2_bonus_chain_lengths",
                "tier3_pid_ge_10000", "tier3_jackpot_ids_seen",
                "tier3_pid_ge_10000_and_jackpot_ids_seen", "tier3_raw".
    """

    def __init__(
        self,
        *,
        jackpot_applicable: bool = False,
        jackpot_pid_set: "frozenset[str]" = frozenset(),
        freespin_applicable: bool = False,
        scatter_marker_pids: "frozenset[str]" = frozenset(),
        payout_groups_applicable: bool = False,
        detection_source: "dict[str, str] | None" = None,
    ) -> None:
        """Create a MechanismRegistry instance.

        All parameters are keyword-only with defaults so ``MechanismRegistry()``
        produces a valid no-op instance (all False / empty).  This preserves
        backward compatibility with the C1 placeholder calling pattern
        ``_mechanism_registry = MechanismRegistry()`` used in tests.

        Production code should use ``MechanismRegistry.build(...)`` to run
        the Tier 1/2/3 detection algorithm.
        """
        self.jackpot_applicable = jackpot_applicable
        self.jackpot_pid_set = jackpot_pid_set
        self.freespin_applicable = freespin_applicable
        self.scatter_marker_pids = scatter_marker_pids
        self.payout_groups_applicable = payout_groups_applicable
        self._detection_source: dict[str, str] = detection_source if detection_source is not None else {}

    @classmethod
    def build(
        cls,
        *,
        manifest: dict[str, Any],
        payout_id_win: dict[str, float],
        payout_id_hits: dict[str, int],
        jackpot_ids_seen: set[str],
        bonus_chain_lengths: list[int],
        total_freespin_chain_spins: int,
        payout_group_win: dict[int, float],
        pid_has_regular_line: dict[str, bool],
    ) -> "MechanismRegistry":
        """Build a registry instance by running Tier 1 → Tier 2 → Tier 3 detection.

        Parameters
        ----------
        manifest:
            Resolved (inheritance + per-mode) manifest for this run.
            May include ``mechanism_overrides`` dict (Tier 1).
        payout_id_win:
            Run-level {pid_str: total_credits_won} from PIA merge loop.
        payout_id_hits:
            Run-level {pid_str: total_hits} from PIA merge loop.
        jackpot_ids_seen:
            Run-level set of jackpot PID strings accumulated from the raw
            ``JackpotIds`` field by the parser (Path B for jackpot detection).
        bonus_chain_lengths:
            Run-level list of freespin chain lengths (from ReMarks annotation).
            Non-empty ↔ freespin chains occurred.  Empty ↔ no freespin chains.
        total_freespin_chain_spins:
            Sum of freespin spins across all chains (Tier 3 fallback signal).
        payout_group_win:
            Run-level {group_id_int: total_win_float} from PIA merge loop.
        pid_has_regular_line:
            {pid_str: True} for PIDs that have at least one PayoutByPayline
            record with line_id != -1.  Absent key means only trigger-lines
            were observed.  Built by payouts_by_spin_type plugin's extract().
        """
        overrides: dict[str, Any] = manifest.get("mechanism_overrides") or {}
        detection_source: dict[str, str] = {}

        # ── Scatter marker detection (runs first, output used by jackpot) ──
        # A PID is a scatter trigger marker if:
        #   - total win == 0  (win field in payout_id_win)
        #   - no regular-line record (pid absent from pid_has_regular_line or
        #     pid_has_regular_line[pid] is falsy)
        # This prevents high-numeric-ID scatter markers from being misclassified
        # as jackpot candidates.
        scatter_marker_pids: frozenset[str]
        if "scatter_marker_pids" in overrides:
            scatter_marker_pids = frozenset(str(p) for p in overrides["scatter_marker_pids"])
            detection_source["scatter_marker_pids"] = "tier1_manifest"
        else:
            _scatter_set: set[str] = set()
            for pid_s, win in payout_id_win.items():
                if win == 0.0 and not pid_has_regular_line.get(pid_s, False):
                    # Win==0 AND no regular line → scatter trigger marker
                    _scatter_set.add(pid_s)
            scatter_marker_pids = frozenset(_scatter_set)
            detection_source["scatter_marker_pids"] = "tier3_raw"

        # ── Jackpot detection ──
        jackpot_applicable: bool
        jackpot_pid_set: frozenset[str]

        if "jackpot_applicable" in overrides:
            jackpot_applicable = bool(overrides["jackpot_applicable"])
            _jpids_override = overrides.get("jackpot_pid_set", [])
            jackpot_pid_set = frozenset(str(p) for p in _jpids_override)
            detection_source["jackpot_applicable"] = "tier1_manifest"
            detection_source["jackpot_pid_set"] = "tier1_manifest"
        else:
            # Tier 3 — Path A: PIDs >= 10000 in payout_id_win (exclude scatter)
            _path_a: set[str] = set()
            for pid_s in payout_id_win:
                try:
                    pid_int = int(pid_s)
                except ValueError:
                    continue
                if pid_int >= 10000 and pid_s not in scatter_marker_pids:
                    _path_a.add(pid_s)

            # Tier 3 — Path B: jackpot_ids_seen from raw JackpotIds field
            _path_b: set[str] = jackpot_ids_seen - scatter_marker_pids

            jackpot_pid_set = frozenset(_path_a | _path_b)
            jackpot_applicable = bool(jackpot_pid_set)

            # Record which path(s) contributed.
            if _path_a and _path_b:
                _src = "tier3_pid_ge_10000_and_jackpot_ids_seen"
            elif _path_a:
                _src = "tier3_pid_ge_10000"
            elif _path_b:
                _src = "tier3_jackpot_ids_seen"
            else:
                _src = "tier3_raw"
            detection_source["jackpot_applicable"] = _src
            detection_source["jackpot_pid_set"] = _src

        # ── Freespin detection ──
        freespin_applicable: bool

        if "freespin_applicable" in overrides:
            freespin_applicable = bool(overrides["freespin_applicable"])
            detection_source["freespin_applicable"] = "tier1_manifest"
        else:
            # Tier 2: bonus_chain_lengths is the authoritative signal.
            # Non-empty → freespin chains occurred.
            # Empty list → explicit False (Tier 3 fallback BLOCKED per 04_v3 §5.2).
            # Note: behavior_name=free MUST NOT be used (causes false-positive
            # on BCM_WHEEL machines like M279 per 04_v3 §5.2 R3-06).
            if bonus_chain_lengths:
                freespin_applicable = True
                detection_source["freespin_applicable"] = "tier2_bonus_chain_lengths"
            else:
                # Tier 2 explicit False: bonus_chain_lengths is empty list.
                # Even if total_freespin_chain_spins > 0, Tier 2 explicit-False
                # blocks Tier 3.  In practice, if bonus_chain_lengths is empty
                # then total_freespin_chain_spins will also be 0.
                #
                # total_freespin_chain_spins is accepted for forward-compatibility
                # but is NOT read in the current detection logic. Tier 2
                # explicit-False (bonus_chain_lengths empty) blocks Tier 3 before
                # this value could be used. Add Tier 3 freespin logic here only if
                # a machine class does not annotate ReMarks but DOES have freespin
                # behavior observable via total_freespin_chain_spins > 0.
                freespin_applicable = False
                detection_source["freespin_applicable"] = "tier2_bonus_chain_lengths_empty"

        # ── Payout groups detection ──
        payout_groups_applicable: bool

        if "payout_groups_applicable" in overrides:
            payout_groups_applicable = bool(overrides["payout_groups_applicable"])
            detection_source["payout_groups_applicable"] = "tier1_manifest"
        else:
            # Tier 3: any group_id != 0 with win > 0 → real grouping present.
            # group_id=0 is the default/no-grouping bucket (e.g. M275 all-zeros).
            payout_groups_applicable = any(
                gid != 0 and win > 0
                for gid, win in payout_group_win.items()
            )
            detection_source["payout_groups_applicable"] = "tier3_raw"

        return cls(
            jackpot_applicable=jackpot_applicable,
            jackpot_pid_set=jackpot_pid_set,
            freespin_applicable=freespin_applicable,
            scatter_marker_pids=scatter_marker_pids,
            payout_groups_applicable=payout_groups_applicable,
            detection_source=detection_source,
        )

    def to_summary_dict(self) -> dict[str, Any]:
        """Serialise registry state for inclusion in the summary JSON."""
        return {
            "jackpot_applicable": self.jackpot_applicable,
            "jackpot_pid_set": sorted(self.jackpot_pid_set),
            "freespin_applicable": self.freespin_applicable,
            "scatter_marker_pids": sorted(self.scatter_marker_pids),
            "payout_groups_applicable": self.payout_groups_applicable,
            "_detection_source": dict(self._detection_source),
        }
