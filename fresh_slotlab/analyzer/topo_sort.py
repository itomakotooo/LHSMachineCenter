"""Topological sort for AnalyzerFeature plugin dependency graph.

Phase C1 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §4.2.

Implements Kahn's algorithm (BFS-based) over the REQUIRES DAG declared by
AnalyzerFeature subclasses.  Tie-breaking within the same topological layer
is lexicographic by FEATURE_ID so emit order is deterministic across Python
versions (and across machines that declare the same feature set).

Exceptions
----------
PluginCyclicDependencyError
    Raised when the REQUIRES graph contains a cycle.  This is a programming
    error (plugin misconfiguration); it must surface loudly per
    memory/feedback_no_silent_swallow.md.

PluginMissingDependencyError
    Raised when a plugin's REQUIRES lists a FEATURE_ID that is absent from
    the features-for-this-machine set.  This is also a programming error
    (missing manifest entry or typo in REQUIRES).

PluginDeclaredDepMissingError
    Raised inside the emit loop when a plugin's DECLARED_DEPS names a
    summary-dict key that is absent from ``summary`` at emit time.  This is
    a programming error (ordering bug or typo in DECLARED_DEPS).  Note the
    distinction from PluginMissingDependencyError: REQUIRES carries
    FEATURE_IDs (graph-level); DECLARED_DEPS carries summary-dict keys
    (data-contract level).  Caught by PIA main() Region 2 handler and written
    to ``summary["analyzer_init_error"]`` with region=2 before SystemExit(1).

All three exceptions are caught by PIA main() and written to
``summary["analyzer_init_error"]`` with stderr ERROR log and non-zero rc.

No import-time I/O per memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature


# ---------------------------------------------------------------------------
# Exception types
# ---------------------------------------------------------------------------

class PluginCyclicDependencyError(Exception):
    """REQUIRES graph contains a cycle — emit order is undefined.

    Attributes
    ----------
    cycle : list[str]
        A subset of FEATURE_IDs that form the detected cycle (or at minimum
        the set of nodes with unresolved in-edges when Kahn's algorithm
        terminates early).  May not be the complete cycle; it is the set of
        nodes remaining after the BFS saturates.
    """

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__(
            f"Plugin dependency cycle detected. "
            f"Involved plugins (may be partial): {cycle!r}. "
            "Fix REQUIRES declarations so the dependency graph is acyclic."
        )


class PluginMissingDependencyError(Exception):
    """A plugin declares a REQUIRES dep that is absent from the feature set.

    Attributes
    ----------
    plugin : str
        FEATURE_ID of the plugin that declared the missing dep.
    missing_dep : str
        FEATURE_ID that was declared in REQUIRES but is not registered /
        not present in the features-for-this-machine set.
    """

    def __init__(self, plugin: str, missing_dep: str) -> None:
        self.plugin = plugin
        self.missing_dep = missing_dep
        super().__init__(
            f"Plugin '{plugin}' declares REQUIRES dependency '{missing_dep}' "
            f"which is not present in the feature set for this machine. "
            "Either add the missing plugin to the manifest's analyzer_features "
            "list, or remove the incorrect REQUIRES entry."
        )


class PluginDeclaredDepMissingError(Exception):
    """A plugin's DECLARED_DEPS names a summary-dict key absent at emit time.

    This is a data-contract error, distinct from PluginMissingDependencyError
    which is a graph-level REQUIRES error.  DECLARED_DEPS carries summary-dict
    keys (str keys expected to exist in ``summary`` before emit() is called),
    whereas REQUIRES carries FEATURE_IDs (plugin graph nodes).

    Raised inside the PIA emit loop (Region 2) before emit() is called for the
    offending plugin.  Caught by PIA main() Region 2 handler; written to
    ``summary["analyzer_init_error"]`` with region=2 before SystemExit(1).

    Attributes
    ----------
    plugin : str
        FEATURE_ID of the plugin whose DECLARED_DEPS named the missing key.
    missing_dep_key : str
        The summary-dict key that was absent from ``summary``.
    """

    def __init__(self, plugin: str, missing_dep_key: str) -> None:
        self.plugin = plugin
        self.missing_dep_key = missing_dep_key
        super().__init__(
            f"Plugin '{plugin}' declares DECLARED_DEPS key '{missing_dep_key}' "
            f"which is absent from summary at emit time. "
            "Ordering error or typo in DECLARED_DEPS. "
            "Ensure the plugin that writes this summary key runs before this plugin "
            "in topo order, or remove the incorrect DECLARED_DEPS entry."
        )


# ---------------------------------------------------------------------------
# Kahn's algorithm
# ---------------------------------------------------------------------------

def topological_sort(features: list["AnalyzerFeature"]) -> list["AnalyzerFeature"]:
    """Return *features* sorted by REQUIRES dependency order (Kahn's algorithm).

    Guarantees
    ----------
    - For any feature F that lists feature G in ``F.REQUIRES``, G appears
      before F in the returned list.
    - Within the same topological layer (no ordering constraint between them),
      features are sorted lexicographically by ``FEATURE_ID``.  This makes
      the output deterministic even when the input order varies.

    Parameters
    ----------
    features : list[AnalyzerFeature]
        The (possibly unsorted) list of features to sort.  Typically the
        result of ``get_features_for_machine(manifest)`` filtered to the
        current machine.

    Returns
    -------
    list[AnalyzerFeature]
        Topologically ordered list, same length as *features*.

    Raises
    ------
    PluginMissingDependencyError
        If any feature's ``REQUIRES`` names a FEATURE_ID not present in
        *features*.  Raised before any sorting begins.
    PluginCyclicDependencyError
        If the REQUIRES graph contains a cycle.
    """
    if not features:
        return []

    # Build lookup: FEATURE_ID -> feature instance
    by_id: dict[str, "AnalyzerFeature"] = {f.FEATURE_ID: f for f in features}
    present_ids: frozenset[str] = frozenset(by_id)

    # Pre-validate: check that all REQUIRES deps exist in present_ids
    for feat in features:
        for dep_id in feat.REQUIRES:
            if dep_id not in present_ids:
                raise PluginMissingDependencyError(
                    plugin=feat.FEATURE_ID,
                    missing_dep=dep_id,
                )

    # Build adjacency list and in-degree count for Kahn's algorithm.
    # Edge: dep -> consumer (dep must emit before consumer).
    in_degree: dict[str, int] = {fid: 0 for fid in present_ids}
    # adjacency[dep_id] = list of feature_ids that depend on dep_id
    adjacency: dict[str, list[str]] = {fid: [] for fid in present_ids}

    for feat in features:
        for dep_id in feat.REQUIRES:
            adjacency[dep_id].append(feat.FEATURE_ID)
            in_degree[feat.FEATURE_ID] += 1

    # Kahn's BFS: start from nodes with in_degree == 0
    # Use a sorted initial queue for deterministic tie-breaking.
    ready: deque[str] = deque(
        sorted(fid for fid, deg in in_degree.items() if deg == 0)
    )
    result: list["AnalyzerFeature"] = []

    while ready:
        # Pop the lexicographically smallest ready node (deterministic tie-break)
        current_id = ready.popleft()
        result.append(by_id[current_id])

        # Reduce in-degree for all features that depend on current_id.
        # Collect newly-ready nodes, sort them before appending (tie-break).
        newly_ready: list[str] = []
        for consumer_id in adjacency[current_id]:
            in_degree[consumer_id] -= 1
            if in_degree[consumer_id] == 0:
                newly_ready.append(consumer_id)

        # Insert newly ready nodes in sorted order.  Since ``ready`` may
        # already contain other nodes at the same tier, we merge-sort the
        # combined ready set to maintain strict lexicographic ordering.
        # Simpler approach: extend + re-sort the deque each time.
        # For typical feature counts (< 20) this is negligible.
        if newly_ready:
            combined = list(ready) + sorted(newly_ready)
            ready = deque(sorted(combined))

    # If result length < input length, there's a cycle.
    if len(result) < len(features):
        # The remaining unresolved nodes are those still with in_degree > 0.
        cycle_nodes = sorted(
            fid for fid, deg in in_degree.items() if deg > 0
        )
        raise PluginCyclicDependencyError(cycle=cycle_nodes)

    return result
