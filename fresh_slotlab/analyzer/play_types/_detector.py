"""play_types._detector — detect_play_types() auto-detection function.

Per 04_v2.md §4.6 (three-rule claim precedence) and §4.2-rev (5,000-round
sample contract).

detect_play_types()
-------------------
Given a 5,000-round sample from chunk_0001 and a registry of PlayTypePlugin
classes, returns a MachinePlayTypeConfig describing which plugins apply to
this (machine, mode) and the SpinType → plugin mapping (st_map).

Three-rule claim precedence (§4.6)
-----------------------------------
Applied in this order when multiple plugins claim the same SpinType:

Rule 1: Structural exclusion wins.
    If a plugin's ClaimSignature.exclude_if_fields_present is non-empty and
    ANY round in the sample contains any of those fields, that plugin does NOT
    claim the ST regardless of other signals.  Hard veto.  This resolves the
    M275 ST=126 BCMFreespin-vs-ScatterFreespin conflict systematically: adding
    exclude_if_fields_present=frozenset({"CollectCount","AccCredits"}) to
    ScatterFreespinPlugin resolves ALL BCM+scatter machines at once.

Rule 2: Dep-subordination.
    If plugin A declares MECHANIC_DEPS containing plugin B's FEATURE_ID, and
    both A and B claim the same ST, B gets primary ownership of that ST in
    st_map, and A is listed as a subordinate observer.  A's accumulator still
    fires for that ST (it can read peer B's state via peers arg in on_round).
    This resolves the M120 ST=138 MultiSymbolCollection-vs-ScatterFreespin
    conflict: MultiSymbolCollectionPlugin has MECHANIC_DEPS=("scatter_freespin",)
    → ST=138 is assigned to scatter_freespin; MultiSymbolCollectionPlugin
    observes those rounds as a subordinate.

Rule 3: Most-specific signature wins.
    If Rules 1 and 2 do not resolve, the plugin with more required_fields in
    its ClaimSignature wins (more fields = more specific signature).  If tied
    (same number of required_fields), an ONBOARDING ALERT fires — this is a
    true ambiguity case requiring human review.

With an EMPTY plugin registry, detect_play_types() returns a config with
active_plugins=[] and an empty st_map.  No concrete plugins exist in Commit A;
this is the expected behaviour.

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

# Dual-path import — mirrors feature_registry.py convention.
try:
    from fresh_slotlab.analyzer.play_types._machine_config import MachinePlayTypeConfig
except ImportError:
    from analyzer.play_types._machine_config import MachinePlayTypeConfig  # type: ignore[no-redef]

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.play_types._plugin import PlayTypePlugin
    except ImportError:
        from analyzer.play_types._plugin import PlayTypePlugin  # type: ignore[assignment]

# Maximum number of sample rounds used for detection (§4.2-rev).
_MAX_SAMPLE_ROUNDS = 5000


def detect_play_types(
    sample_rounds: "list[dict]",
    registered_plugins: "list[PlayTypePlugin]",
    parse_state: object,
    machine_id: str = "",
    mode: int = 1,
) -> MachinePlayTypeConfig:
    """Auto-detect which play-type plugins apply to a machine.

    Evaluates each registered plugin's ClaimSignature against the sample
    rounds, then applies the three-rule precedence to resolve conflicts when
    multiple plugins claim the same SpinType.

    Parameters
    ----------
    sample_rounds:
        Up to 5,000 rounds from chunk_0001 (the caller caps the sample).
        READ ONLY.
    registered_plugins:
        List of PlayTypePlugin instances from play_type_registry.ALL_PLAY_TYPE_PLUGINS.
        May be empty (returns empty config — no plugins detected).
    parse_state:
        ParseState (or any object) with a ``cost_credits_unreliable``
        boolean attribute.  Used by ClaimSignature.matches() for paid/bonus
        round classification.
    machine_id:
        Machine identifier (e.g. "M14").  Written into the returned config.
    mode:
        Integer mode (e.g. 1).  Written into the returned config.

    Returns
    -------
    MachinePlayTypeConfig
        Detected configuration with active_plugins, st_map, and any
        onboarding_alerts for unresolved ambiguities.

    Notes
    -----
    With an empty registered_plugins list, returns a MachinePlayTypeConfig
    with active_plugins=[] and empty st_map.  This is the expected behaviour
    for Commit A (foundation framework only; concrete plugins are Commit B+).

    The caller is responsible for capping sample_rounds at _MAX_SAMPLE_ROUNDS
    before calling this function, or this function will do so internally.
    """
    # Cap sample at 5,000 rounds (§4.2-rev).
    if len(sample_rounds) > _MAX_SAMPLE_ROUNDS:
        sample_rounds = sample_rounds[:_MAX_SAMPLE_ROUNDS]

    if not registered_plugins:
        # No plugins registered — empty config.
        return MachinePlayTypeConfig(
            machine_id=machine_id,
            mode=mode,
            active_plugins=[],
            st_map={},
            plugin_configs={},
            onboarding_alerts=[],
        )

    # ------------------------------------------------------------------
    # Step 1: Evaluate ClaimSignature.matches() for each plugin against
    # the full sample (machine-level match).  Rule 1 (structural exclusion
    # via exclude_if_fields_present) is embedded in matches() — a plugin
    # that fails exclusion returns False here.
    # ------------------------------------------------------------------
    matching_plugins: list = []
    for plugin in registered_plugins:
        if not hasattr(plugin, "CLAIM_SIGNATURE"):
            continue
        if plugin.CLAIM_SIGNATURE.matches(sample_rounds, parse_state):
            matching_plugins.append(plugin)

    if not matching_plugins:
        return MachinePlayTypeConfig(
            machine_id=machine_id,
            mode=mode,
            active_plugins=[],
            st_map={},
            plugin_configs={},
            onboarding_alerts=[],
        )

    # ------------------------------------------------------------------
    # Step 2: Bucket sample rounds by SpinType.
    # Each bucket is the population of rounds for one SpinType value.
    # ------------------------------------------------------------------
    from collections import defaultdict as _defaultdict
    _rounds_by_st: dict = _defaultdict(list)
    for r in sample_rounds:
        st = r.get("SpinType")
        if st is not None:
            _rounds_by_st[str(st)].append(r)

    observed_spin_types: set = set(_rounds_by_st.keys())

    # ------------------------------------------------------------------
    # Step 3: Per-ST ownership — FIX 1 (critique_commitA PREREQ-1).
    #
    # The original code made EVERY machine-matching plugin a claimant for
    # EVERY observed ST.  On multi-play-type machines (e.g. M272:
    # ST=140 paid with CollectCount / ST=126 bonus with "Freespin" remark)
    # this made both BCMBase (paid field signal) and BCMFreespin (bonus
    # remark signal) claim ST=140 AND ST=126 simultaneously, so the
    # precedence resolver picked one winner for ALL STs instead of routing
    # each ST to the plugin whose signal actually fires there.
    #
    # Fix: for each matching plugin, determine which STs it "owns" by re-
    # evaluating its ClaimSignature signals against each ST's per-ST round
    # population instead of the full sample.  Only if a plugin's signal
    # fires within an ST's rounds is that plugin a claimant for that ST.
    # This produces per-ST claimant lists and routes each ST independently.
    #
    # Signal ownership rules (per §4.2-rev):
    #   required_fields (paid signal)       → claims STs whose rounds carry
    #     those fields.  _bonus_-prefixed fields target bonus rounds.
    #   required_bonus_remark_pattern       → claims STs whose rounds match
    #     the remark pattern on bonus rounds.
    #   required_trigger_pay_id             → claims STs whose paid rounds
    #     carry the pay_id in PayoutIdToWinAmount.
    #   No specific signal (empty sig)      → claims ALL observed STs
    #     (universal plugins like PurePaid match by absence of signals).
    #
    # After per-ST claimants are determined, the same three-rule precedence
    # (§4.6) is applied independently per ST over the ACTUAL claimants for
    # that ST, not over all matching plugins.
    # ------------------------------------------------------------------
    _cost_credits_unreliable: bool = getattr(
        parse_state, "cost_credits_unreliable", False
    )

    def _is_paid(r: dict) -> bool:
        if _cost_credits_unreliable:
            return True
        return (r.get("CostCredits") or 0) > 0

    def _plugin_signals_fire_in_st_rounds(
        plugin: object, st_rounds: list
    ) -> bool:
        """Return True if any of plugin's ClaimSignature signals fire within
        st_rounds (the round population for a specific SpinType).

        An EMPTY signature (no required_fields, no remark pattern, no pay_id)
        always fires — it is a universal/fallback plugin.

        This is distinct from ClaimSignature.matches(), which runs on the
        FULL sample and handles exclude_if_fields_present (Rule 1).
        exclude_if_fields_present is a machine-level veto already resolved
        in Step 1; we only check signal fire per ST here.
        """
        import re as _re
        sig = getattr(plugin, "CLAIM_SIGNATURE", None)
        if sig is None:
            return False

        required_fields = getattr(sig, "required_fields", frozenset())
        remark_pattern = getattr(sig, "required_bonus_remark_pattern", None)
        trigger_pay_id = getattr(sig, "required_trigger_pay_id", None)

        # Empty signature = universal plugin; claims every ST.
        has_any_signal = bool(required_fields) or (remark_pattern is not None) or (trigger_pay_id is not None)
        if not has_any_signal:
            return True

        paid_rounds = [r for r in st_rounds if _is_paid(r)]
        bonus_rounds = [r for r in st_rounds if not _is_paid(r)]

        # Check required_fields against the appropriate round population.
        for fname in required_fields:
            if fname.startswith("_bonus_"):
                actual_fname = fname[len("_bonus_"):]
                target = bonus_rounds
            else:
                actual_fname = fname
                target = paid_rounds
            if any(actual_fname in r for r in target):
                return True

        # Check remark pattern against bonus rounds.
        if remark_pattern is not None:
            flags = _re.IGNORECASE if getattr(sig, "bonus_remark_case_insensitive", False) else 0
            pattern = _re.compile(remark_pattern, flags)
            for r in bonus_rounds:
                remarks = r.get("ReMarks") or ""
                if pattern.search(remarks):
                    return True

        # Check trigger pay_id against paid rounds.
        if trigger_pay_id is not None:
            for r in paid_rounds:
                payout_map = r.get("PayoutIdToWinAmount") or {}
                if trigger_pay_id in payout_map:
                    return True

        return False

    # ------------------------------------------------------------------
    # Step 3b: Build per-ST claimant lists and assign winners.
    # ------------------------------------------------------------------
    st_map: dict = {}
    onboarding_alerts: list = []
    active_plugin_ids: set = set()

    # Build a lookup of FEATURE_ID → plugin for dep-subordination checks.
    plugin_by_fid: dict = {p.FEATURE_ID: p for p in matching_plugins}

    for st in sorted(observed_spin_types):
        st_rounds = _rounds_by_st[st]
        # Per-ST claimants: only plugins whose signal fires in this ST's rounds.
        claimants: list = [
            p for p in matching_plugins
            if _plugin_signals_fire_in_st_rounds(p, st_rounds)
        ]

        if not claimants:
            # No plugin claims this ST — leave unowned (inline logic handles it).
            continue

        if len(claimants) == 1:
            winner = claimants[0]
            st_map[st] = winner.FEATURE_ID
            active_plugin_ids.add(winner.FEATURE_ID)
            continue

        # Multiple per-ST claimants — apply Rule 2 and Rule 3.
        winner = _resolve_claimants(claimants, plugin_by_fid, st, onboarding_alerts)
        if winner is not None:
            st_map[st] = winner.FEATURE_ID
            active_plugin_ids.add(winner.FEATURE_ID)

    # Collect all active plugins that claimed at least one ST.
    # Plugins that claimed via dep-subordination (MECHANIC_DEPS) are also
    # included in active_plugins so their accumulators fire.
    # A subordinate plugin: it matched the sample AND declares MECHANIC_DEPS
    # that points to at least one primary winner (active_plugin_ids).
    # We include these so their accumulators observe rounds via on_round()
    # even though they did not win primary ownership of any ST.
    subordinate_ids: set = set()
    for plugin in matching_plugins:
        if plugin.FEATURE_ID in active_plugin_ids:
            continue  # already a primary
        deps = getattr(plugin, "MECHANIC_DEPS", ())
        if any(dep_fid in active_plugin_ids for dep_fid in deps):
            subordinate_ids.add(plugin.FEATURE_ID)

    all_active_ids = active_plugin_ids | subordinate_ids
    active_plugins_ordered = _topo_sort_plugins(
        [p for p in matching_plugins if p.FEATURE_ID in all_active_ids]
    )

    return MachinePlayTypeConfig(
        machine_id=machine_id,
        mode=mode,
        active_plugins=[p.FEATURE_ID for p in active_plugins_ordered],
        st_map=st_map,
        plugin_configs={},
        onboarding_alerts=onboarding_alerts,
    )


def _resolve_claimants(
    claimants: "list",
    plugin_by_fid: "dict[str, PlayTypePlugin]",
    st: str,
    onboarding_alerts: list,
) -> Optional[object]:
    """Apply Rule 2 (dep-subordination) and Rule 3 (most-specific) to pick a winner.

    Rule 1 (structural exclusion) is already applied by ClaimSignature.matches();
    claimants here have all passed the exclusion test.

    Parameters
    ----------
    claimants:
        List of matching plugins for this ST.
    plugin_by_fid:
        All matching plugins by FEATURE_ID.
    st:
        SpinType string being resolved.
    onboarding_alerts:
        Mutable list; alert messages appended here on genuine tie.

    Returns
    -------
    The winning PlayTypePlugin instance, or None on unresolvable tie
    (alert already appended to onboarding_alerts).
    """
    if len(claimants) == 1:
        return claimants[0]

    # Rule 2: dep-subordination.
    # If plugin A declares MECHANIC_DEPS containing plugin B's FEATURE_ID,
    # and B is also in claimants, B is the primary owner (A is subordinate).
    # "A depends on B" means B is upstream/primary; A is the subordinate observer.
    # We want to find the plugin that is NOT a subordinate of any other
    # claimant.
    non_subordinate: list = []
    for candidate in claimants:
        is_subordinate = False
        for other in claimants:
            if candidate is other:
                continue
            # candidate is subordinate if candidate declares other as a dep
            # — i.e., candidate.MECHANIC_DEPS contains other.FEATURE_ID.
            # This means other is the primary (upstream dep) and candidate
            # is the subordinate observer.
            if other.FEATURE_ID in getattr(candidate, "MECHANIC_DEPS", ()):
                is_subordinate = True
                break
        if not is_subordinate:
            non_subordinate.append(candidate)

    if len(non_subordinate) == 1:
        return non_subordinate[0]

    # Remaining candidates after Rule 2 — apply Rule 3: most-specific signature.
    candidates = non_subordinate if non_subordinate else claimants

    def _specificity(plugin: object) -> int:
        sig = getattr(plugin, "CLAIM_SIGNATURE", None)
        if sig is None:
            return 0
        return len(getattr(sig, "required_fields", frozenset()))

    max_spec = max(_specificity(p) for p in candidates)
    most_specific = [p for p in candidates if _specificity(p) == max_spec]

    if len(most_specific) == 1:
        return most_specific[0]

    # Genuine tie — ONBOARDING ALERT.
    tied_ids = sorted(p.FEATURE_ID for p in most_specific)
    onboarding_alerts.append(
        f"claim_tie: ST={st} has {len(most_specific)} equally-specific claimants "
        f"{tied_ids!r} — human review required. "
        f"Add exclude_if_fields_present to one plugin or adjust MECHANIC_DEPS."
    )
    return None


def _topo_sort_plugins(plugins: "list") -> "list":
    """Sort plugins by MECHANIC_DEPS topo-sort order (Kahn's algorithm).

    Ties within the same topo-layer are broken lexicographically by FEATURE_ID,
    matching topo_sort.topological_sort() behaviour.

    Parameters
    ----------
    plugins:
        List of PlayTypePlugin instances to sort.

    Returns
    -------
    list
        Topologically sorted list.  Raises RuntimeError on cycle (programming
        error — MECHANIC_DEPS must be a DAG).
    """
    if not plugins:
        return []

    by_fid: dict = {p.FEATURE_ID: p for p in plugins}
    present_ids: frozenset = frozenset(by_fid)

    # Build adjacency and in-degree for Kahn's algorithm.
    # Edge: dep → consumer.
    from collections import deque
    in_degree: dict = {fid: 0 for fid in present_ids}
    adjacency: dict = {fid: [] for fid in present_ids}

    for plugin in plugins:
        for dep_fid in getattr(plugin, "MECHANIC_DEPS", ()):
            if dep_fid not in present_ids:
                # Dep not in active set — skip (dep plugin not matched on this
                # machine; the subordinate plugin can still fire without its dep).
                continue
            adjacency[dep_fid].append(plugin.FEATURE_ID)
            in_degree[plugin.FEATURE_ID] += 1

    ready: deque = deque(
        sorted(fid for fid, deg in in_degree.items() if deg == 0)
    )
    result: list = []

    while ready:
        current_id = ready.popleft()
        result.append(by_fid[current_id])
        newly_ready: list = []
        for consumer_id in adjacency[current_id]:
            in_degree[consumer_id] -= 1
            if in_degree[consumer_id] == 0:
                newly_ready.append(consumer_id)
        if newly_ready:
            combined = list(ready) + sorted(newly_ready)
            ready = deque(sorted(combined))

    if len(result) < len(plugins):
        # Cycle in MECHANIC_DEPS — programming error.
        cycle_nodes = sorted(fid for fid, deg in in_degree.items() if deg > 0)
        raise RuntimeError(
            f"Cycle in MECHANIC_DEPS detected. "
            f"Involved plugins (may be partial): {cycle_nodes!r}. "
            "Fix MECHANIC_DEPS declarations so the dependency graph is acyclic. "
            "Per memory/feedback_no_silent_swallow.md: this error is not swallowed."
        )

    return result
