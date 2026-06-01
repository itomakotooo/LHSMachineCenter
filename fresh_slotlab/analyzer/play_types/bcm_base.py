"""play_types.bcm_base — BCMBasePlugin: the first REAL play-type plugin.

Commit C2.  Per 04_v2.md §9-rev Phase 1 deliverable #10 + the carve design.

BCMBasePlugin
-------------
Detects the BCM (BuffCollectionMap) mechanic: machines where ``CollectCount``,
``AccCredits``, ``CreditsSymbols``, and ``SymbolIndexToRewards`` are present on
paid rounds.  It is the base for all BCM-family machines (M272, M275, M279,
M268, M274, etc.).

Accumulator lifecycle (per §4.1-rev call-ordering model)
---------------------------------------------------------
  on_round()     — records CollectCount from each paid round for later peak
                   detection; tracks whether BCM fields were observed on any
                   round.  Cheap: no computation beyond a field check.

  on_robot_end() — called once after all per-round calls.  Runs
                   ``detect_cycle_peak(all_rounds)`` (the exact same function
                   the inline code calls, ensuring byte-identical output) and
                   ``at_cycle_peak_indices`` on the full robot round list.  Also
                   calls ``infer_bcm_target_spin_type`` to identify the dominant
                   SpinType that fires after each cycle peak (used for the
                   informational ``_bcm_bonus_feature`` auto-detection).

  to_chunk_partial() — returns the chunk-partial dict with the 4 required keys
                   (§9-rev Phase 1 #10 explicit stash contract):

                   ``cycle_peaks``
                       List of detected cycle-peak CC values for this robot.
                       **Same key name as the current inline code** so PIA's
                       merge loop reads it unchanged.  The inline code is gated
                       (see parser.py) when this plugin is active, so the plugin
                       partial is the sole source when the flag is on.

                   ``collect_robots_seen``
                       1 if BCM fields were present on any round of this robot,
                       else 0.  **Same key name as the current inline code** so
                       PIA's merge loop reads it unchanged.

                   ``_bcm_bonus_feature``
                       Auto-detected dominant SpinType (as a string, e.g. "126")
                       that fires after a cycle peak, or None if no cycle peak
                       was observed.  NOTE: this is the SpinType AS STRING, not
                       the upstream feature name string (e.g. "NewFreespin").
                       Stored as a string to avoid the type-aware merge's numeric
                       summation behavior (int/float values are summed across
                       robots; strings get "last robot wins" semantics, which is
                       correct for a per-machine feature identifier).
                       PIA's current ``_resolve_bonus_feature`` call is NOT
                       replaced by this in Commit C2 — the collect_mechanic panel
                       continues to get its bonus_feature from
                       ``_resolve_bonus_feature`` for byte-identical output.
                       This key is written for future wiring (Phase 2 migration)
                       and for the test suite's "verify auto-detect == golden"
                       assertion.

                   ``_bcm_bonus_source``
                       "auto_detected" if a cycle peak was observed, "none"
                       otherwise.  Future wiring point (Phase 2).

CARVE
-----
When ``use_play_type_plugins`` is True AND ``bcm_base`` is active for the
machine, parser.py gates the inline accumulation of ``chunk_cycle_peaks`` and
``chunk_collect_seen`` to avoid double-production:

    # Commit C2 carve (gated when bcm_base plugin is active):
    if not _bcm_base_active:
        if robot_cycle_peaks:
            chunk_cycle_peaks.extend(robot_cycle_peaks)
        if robot_collect_observed:
            chunk_collect_seen += 1

The plugin's ``to_chunk_partial()`` provides ``cycle_peaks`` and
``collect_robots_seen`` instead.  The type-aware merge (wiring point 5 in
parser.py) extends the list across robots and sums the int across robots.
The final chunk dict contains the same values as before the carve.

ClaimSignature
--------------
Requires all four BCM fields on PAID rounds.  M274 has the fields but
``CollectCount`` is always 0 (cc=0 machine) — the signature still fires
because the fields are *present* on paid rounds (even if zero).  BCM
accumulation handles cc=0 gracefully (no cycle peaks, ``collect_robots_seen``
based on field presence not cc > 0).

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional

# Dual-path import pattern (mirrors all other play_types modules).
try:
    from fresh_slotlab.analyzer.play_types._base import MechanicAccumulator, RoundCtx
    from fresh_slotlab.analyzer.play_types._claim import ClaimSignature
    from fresh_slotlab.analyzer.play_types._plugin import PlayTypePlugin
    from fresh_slotlab.round_classification import (
        at_cycle_peak_indices,
        compute_robot_cycle_peaks,
        detect_cycle_peak,
        get_collect_count,
        infer_bcm_target_spin_type,
    )
except ImportError:  # running as standalone script
    from analyzer.play_types._base import MechanicAccumulator, RoundCtx  # type: ignore[no-redef]
    from analyzer.play_types._claim import ClaimSignature  # type: ignore[no-redef]
    from analyzer.play_types._plugin import PlayTypePlugin  # type: ignore[no-redef]
    from round_classification import (  # type: ignore[no-redef]
        at_cycle_peak_indices,
        compute_robot_cycle_peaks,
        detect_cycle_peak,
        get_collect_count,
        infer_bcm_target_spin_type,
    )

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.play_types._machine_config import MachinePlayTypeConfig
    except ImportError:
        from analyzer.play_types._machine_config import MachinePlayTypeConfig  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# BCMBaseAccumulator
# ---------------------------------------------------------------------------

class BCMBaseAccumulator(MechanicAccumulator):
    """Per-robot accumulator for the BCM (BuffCollectionMap) mechanic.

    Tracks CollectCount fields during on_round() to determine whether BCM
    fields were observed.  Builds the cycle-peak list in on_robot_end()
    via ``compute_robot_cycle_peaks(all_rounds)`` — the shared helper that
    is the single source of truth for the per-robot cycle-peak list.
    The inline parser.py also calls this helper, so the two paths are
    byte-identical by construction.

    to_chunk_partial() returns the 4 keys from the explicit stash contract
    in §9-rev Phase 1 #10.  ``cycle_peaks`` and ``collect_robots_seen``
    match the current inline chunk-dict key names so PIA reads them
    unchanged.
    """

    def __init__(self, machine_config: "MachinePlayTypeConfig") -> None:
        self._machine_id: str = machine_config.machine_id
        self._mode: int = machine_config.mode
        # Per-robot tracking state (reset per accumulator instance).
        self._bcm_fields_seen: bool = False   # any round had BCM fields
        # Cycle-peak results from on_robot_end(); None until on_robot_end runs.
        self._robot_cycle_peaks: list[int] = []   # populated by on_robot_end
        self._bcm_target_st: Optional[str] = None  # str(SpinType) after peak, or None

    # ------------------------------------------------------------------
    # MechanicAccumulator contract
    # ------------------------------------------------------------------

    @property
    def state(self) -> dict:
        """Read-only snapshot of current accumulation state.

        Returns a shallow copy to prevent accidental mutation by peers.
        """
        return {
            "bcm_fields_seen": self._bcm_fields_seen,
            "robot_cycle_peaks": list(self._robot_cycle_peaks),
            "bcm_target_st": self._bcm_target_st,
        }

    def on_round(
        self,
        round_dict: dict,
        ctx: RoundCtx,
        peers: "dict[str, MechanicAccumulator]",
    ) -> None:
        """Track BCM field presence per round.

        We only check field presence here (not cycle arithmetic) because
        the full robot round list is required for reliable detect_cycle_peak
        output (the function needs to observe at least one complete reset).
        Cycle arithmetic runs in on_robot_end() after all rounds are seen.

        Contract: round_dict is READ ONLY.
        """
        # BCM fields present on this round?  (All 4 may not appear on
        # bonus rounds — we only need at least one of them to count the
        # robot as "BCM-observed".)
        if not self._bcm_fields_seen:
            if (
                "CollectCount" in round_dict
                or "AccCredits" in round_dict
                or "CreditsSymbols" in round_dict
                or "SymbolIndexToRewards" in round_dict
            ):
                self._bcm_fields_seen = True

    def on_robot_end(
        self,
        all_rounds: "list[dict]",
        all_ctxs: "list[RoundCtx]",
    ) -> None:
        """Build the per-robot cycle-peak list and infer the BCM target ST.

        Calls ``compute_robot_cycle_peaks`` (the SINGLE source of truth) to
        build ``_robot_cycle_peaks`` — byte-identical with the inline parser.py
        accumulation by construction (both call the same helper).

        Also calls ``detect_cycle_peak`` + ``infer_bcm_target_spin_type`` to
        auto-detect which SpinType fires after a cycle peak.  Result stored in
        ``_bcm_target_st`` for reporting / test-suite verification.  The feature
        NAME resolution (SpinType → upstream feature name "NewFreespin" etc.) is
        deferred to PIA via ``_resolve_bonus_feature`` (still in PIA in Commit C2).
        """
        if not all_rounds:
            # EC-1: zero-round robot — no cycle peak possible.
            return

        # Use the shared helper — the SINGLE source of truth for the
        # per-robot cycle-peak list.  This is byte-identical with the
        # inline accumulation in parser.py (which also calls this helper).
        # The previous version of this code had a REIMPLEMENTED walk that
        # used the WRONG condition (``cc < prev_cc - 1 and prev_cc >= 5``
        # from detect_cycle_peak) instead of the inline rule
        # (``cc_int < prev and prev > 10``).  The bug was latent on the
        # 9 pilots (their cycles peak ~1000, where both agree) but produced
        # the wrong list for small cycles (peaks in [5,10]) and single-step
        # drops.  Replaced by a single call to compute_robot_cycle_peaks.
        self._robot_cycle_peaks = compute_robot_cycle_peaks(all_rounds)

        # detect_cycle_peak is still needed to find the dominant peak value
        # for infer_bcm_target_spin_type (which needs the single peak int,
        # not the full list).  It's the inference/averaging function; the
        # counting function is compute_robot_cycle_peaks above.
        cycle_peak = detect_cycle_peak(all_rounds)
        if cycle_peak is None:
            # No full cycle observed in this robot's rounds.
            # _bcm_target_st stays None.
            return

        # Auto-detect the dominant SpinType that fires after cycle peaks.
        # Used for informational purposes and test-suite verification.
        # Does NOT replace _resolve_bonus_feature in Commit C2.
        dom_st, sample_count = infer_bcm_target_spin_type(
            all_rounds, cycle_peak=cycle_peak
        )
        if sample_count > 0 and dom_st is not None:
            # Store as string to prevent the type-aware merge in parser.py
            # from SUMMING the SpinType int across robots.  The merge logic
            # sums int/float values; strings get "last robot wins" semantics
            # (appropriate for a per-machine feature identifier).
            self._bcm_target_st = str(dom_st)

    def to_chunk_partial(self) -> dict:
        """Return this robot's BCM cycle contribution to the chunk dict.

        Key contract (§9-rev Phase 1 #10 explicit stash contract):
        ---------------------------------------------------------------
        ``cycle_peaks``
            List of cycle-peak CC values for this robot.  Matches the
            current inline key name so PIA's merge loop reads unchanged.
            Empty list if no complete cycle was observed (EC-1 / M274 cc=0).

        ``collect_robots_seen``
            1 if BCM fields were observed on any round of this robot, else 0.
            Matches the current inline key name so PIA's merge loop reads
            unchanged (``collect_robots_seen_total += rec.get("collect_robots_seen", 0)``).

        ``_bcm_bonus_feature``
            The auto-detected dominant SpinType (int) that fires after a cycle
            peak, or None if no cycle peak was observed.  This is the SpinType
            INT — NOT the upstream feature name string (e.g. "NewFreespin").
            PIA's ``_resolve_bonus_feature`` still supplies the feature name for
            the collect_mechanic panel in Commit C2.  This key is written for
            future wiring (Phase 2) and for test-suite verification.

        ``_bcm_bonus_source``
            "auto_detected" if _bcm_bonus_feature is not None, else "none".
            Future wiring point (Phase 2).

        EC-1 compliance: returns the same key set with zero/empty/None values
        even when all_rounds was empty or no cycle was detected.
        """
        return {
            "cycle_peaks": list(self._robot_cycle_peaks),
            "collect_robots_seen": 1 if self._bcm_fields_seen else 0,
            "_bcm_bonus_feature": self._bcm_target_st,
            "_bcm_bonus_source": "auto_detected" if self._bcm_target_st is not None else "none",
        }


# ---------------------------------------------------------------------------
# BCMBasePlugin
# ---------------------------------------------------------------------------

class BCMBasePlugin(PlayTypePlugin):
    """Play-type plugin for the BCM (BuffCollectionMap) mechanic.

    Detects machines where CollectCount / AccCredits / CreditsSymbols /
    SymbolIndexToRewards are present on paid rounds — the four BCM-family
    fields (§9-rev Phase 1 #10, coordinator brief §IMPLEMENT).

    ClaimSignature evaluation scope (§4.2-rev):
    --------------------------------------------
    All four fields must be present on at least one PAID round in the
    5,000-round sample.  Bonus rounds (CostCredits=0) are excluded by
    the default ``required_fields`` evaluation scope.

    M274 note: CollectCount is always 0 on M274 mode 1, but the field IS
    present on every paid round.  ``ClaimSignature.matches()`` checks field
    presence, not field value — BCMBasePlugin correctly claims M274.

    Mechanic role only (no display panel in Commit C2):
    ---------------------------------------------------
    ``extract()``, ``reduce()``, ``emit()`` are no-ops inherited from
    ``PlayTypePlugin``.  BCMBasePlugin's contribution to the report is via
    the per-chunk ``cycle_peaks`` / ``collect_robots_seen`` keys produced by
    its accumulator.  The ``collect_mechanic`` display panel is produced by
    the existing ``CollectMechanic`` AnalyzerFeature plugin (which reads the
    ``_collect_mechanic_data`` stash written by PIA's ``main()`` using the
    ``cycle_peaks`` data).
    """

    FEATURE_ID: ClassVar[str] = "bcm_base"

    # Four BCM fields required on paid rounds.
    # Per coordinator brief: "BCM 4-fields on paid rounds — verify against
    # M272 rawdata that these fire on paid ST140".  Verified: all 4 present
    # on every paid ST=140 round in M272 chunk_0001.
    CLAIM_SIGNATURE: ClassVar[ClaimSignature] = ClaimSignature(
        required_fields=frozenset({
            "CollectCount",
            "AccCredits",
            "CreditsSymbols",
            "SymbolIndexToRewards",
        })
    )

    MECHANIC_DEPS: ClassVar[tuple] = ()
    """BCMBase has no play-type mechanic deps — it is the base of the BCM family."""

    REQUIRES_PLAY_TYPES: ClassVar[Optional[frozenset]] = None
    """BCMBase itself is a mechanic plugin; its display impact is via the existing
    collect_mechanic feature (which has REQUIRES_PLAY_TYPES=frozenset({"bcm_base"})).
    This plugin does not produce a display panel of its own."""

    def make_accumulator(
        self, machine_config: "MachinePlayTypeConfig"
    ) -> BCMBaseAccumulator:
        """Return a fresh BCMBaseAccumulator for one robot."""
        return BCMBaseAccumulator(machine_config)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
# Import the registry and register BCMBasePlugin at module import time.
# The registry's duplicate-FEATURE_ID guard makes this idempotent.
# Per memory/feedback_subprocess_import_suicide_and_module_globals.md:
# registration is the only side effect at module scope; it does not run
# IO or start processes.
try:
    from fresh_slotlab.analyzer.play_type_registry import register as _register
except ImportError:
    from analyzer.play_type_registry import register as _register  # type: ignore[no-redef]

_register(BCMBasePlugin())
