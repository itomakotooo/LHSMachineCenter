"""Tests for fresh_slotlab/analyzer/topo_sort.py — Phase C1.

Per brief §4 acceptance criteria:
- 4 plugins no deps → returns alphabetical order
- deps form a chain → returns chain order
- cycle → raises PluginCyclicDependencyError
- missing dep → raises PluginMissingDependencyError

Inject-bug contract (per memory/feedback_enumerate_safety_paths.md):
  Each test is verified by checking that a manually injected bug
  causes the assertion to fail. The inline comments indicate which
  mutation would break each assertion.
"""

from __future__ import annotations

import pytest

from fresh_slotlab.analyzer.topo_sort import (
    PluginCyclicDependencyError,
    PluginMissingDependencyError,
    topological_sort,
)


# ---------------------------------------------------------------------------
# Minimal stub feature for testing — no ABC overhead
# ---------------------------------------------------------------------------

class _Stub:
    """Minimal stub with FEATURE_ID and REQUIRES for topo_sort testing."""

    def __init__(self, fid: str, requires: tuple[str, ...] = ()) -> None:
        self.FEATURE_ID = fid
        self.REQUIRES = requires


# ---------------------------------------------------------------------------
# Test: empty input
# ---------------------------------------------------------------------------

def test_empty_input_returns_empty():
    assert topological_sort([]) == []


# ---------------------------------------------------------------------------
# Test: 4 plugins with no dependencies → alphabetical order
# ---------------------------------------------------------------------------

def test_no_deps_alphabetical_order():
    """4 plugins with no REQUIRES → sorted lexicographically by FEATURE_ID."""
    features = [
        _Stub("reel_marginal_by_spin_type"),
        _Stub("bankruptcy_simulation"),
        _Stub("payouts_by_spin_type"),
        _Stub("multiplier_profile"),
    ]
    result = topological_sort(features)
    fids = [f.FEATURE_ID for f in result]
    # Alphabetical: b < m < p < r
    assert fids == [
        "bankruptcy_simulation",
        "multiplier_profile",
        "payouts_by_spin_type",
        "reel_marginal_by_spin_type",
    ], f"Expected alphabetical order, got {fids}"
    # INJECT-BUG CHECK: if alphabetical tiebreak is removed (e.g. sort by
    # insertion order), this assertion fails because the original order
    # is [reel, bankruptcy, payouts, multiplier] which is not alphabetical.


# ---------------------------------------------------------------------------
# Test: deps form a chain → chain order
# ---------------------------------------------------------------------------

def test_chain_ordering():
    """A -> B -> C chain: A must precede B, B must precede C."""
    a = _Stub("a_feature")
    b = _Stub("b_feature", requires=("a_feature",))
    c = _Stub("c_feature", requires=("b_feature",))

    # Submit in reverse order to verify topo-sort doesn't use input order
    result = topological_sort([c, b, a])
    fids = [f.FEATURE_ID for f in result]
    assert fids.index("a_feature") < fids.index("b_feature"), "a must precede b"
    assert fids.index("b_feature") < fids.index("c_feature"), "b must precede c"
    # INJECT-BUG CHECK: if topological_sort returns input order unchanged
    # (i.e. [c, b, a]), the index assertions above both fail.


def test_chain_with_sibling_alphabetical():
    """Chain + sibling at same initial tier → chain respected + alphabetical tiebreak.

    Initial in-degree 0 nodes: a_provider and c_sibling.
    Alphabetical: a_provider < c_sibling, so a_provider runs first.
    After a_provider runs, b_consumer becomes ready.
    Next ready = {b_consumer, c_sibling}. Alphabetical: b < c.
    So order is: a_provider, b_consumer, c_sibling.
    """
    a = _Stub("a_provider")
    b = _Stub("b_consumer", requires=("a_provider",))
    c = _Stub("c_sibling")  # no deps — same tier as a_provider initially

    result = topological_sort([b, c, a])
    fids = [f.FEATURE_ID for f in result]
    # a_provider runs first (only initially-ready with a < c)
    assert fids[0] == "a_provider", f"Expected a_provider first, got {fids}"
    # a is done → b_consumer becomes ready; ready set is {b_consumer, c_sibling}
    # alphabetical: b < c so b_consumer is next
    assert fids[1] == "b_consumer", f"Expected b_consumer second, got {fids}"
    assert fids[2] == "c_sibling", f"Expected c_sibling last, got {fids}"
    # Dep contract: a_provider before b_consumer
    assert fids.index("a_provider") < fids.index("b_consumer")


# ---------------------------------------------------------------------------
# Test: cycle → raises PluginCyclicDependencyError
# ---------------------------------------------------------------------------

def test_cycle_raises():
    """A→B→A cycle must raise PluginCyclicDependencyError."""
    a = _Stub("a_feature", requires=("b_feature",))
    b = _Stub("b_feature", requires=("a_feature",))

    with pytest.raises(PluginCyclicDependencyError) as exc_info:
        topological_sort([a, b])

    exc = exc_info.value
    assert isinstance(exc.cycle, list), "cycle attribute must be a list"
    assert len(exc.cycle) >= 1, "cycle must name at least one node"
    # Both a and b are in the cycle
    assert "a_feature" in exc.cycle or "b_feature" in exc.cycle
    # INJECT-BUG CHECK: if cycle detection is removed (algorithm always
    # returns partial result), pytest.raises catches nothing and the test fails.


def test_three_node_cycle_raises():
    """A→B→C→A cycle."""
    a = _Stub("a_feat", requires=("c_feat",))
    b = _Stub("b_feat", requires=("a_feat",))
    c = _Stub("c_feat", requires=("b_feat",))

    with pytest.raises(PluginCyclicDependencyError):
        topological_sort([a, b, c])


# ---------------------------------------------------------------------------
# Test: missing dep → raises PluginMissingDependencyError
# ---------------------------------------------------------------------------

def test_missing_dep_raises():
    """Plugin declares REQUIRES for a feature not in the feature set."""
    a = _Stub("a_feature", requires=("nonexistent_feature",))

    with pytest.raises(PluginMissingDependencyError) as exc_info:
        topological_sort([a])

    exc = exc_info.value
    assert exc.plugin == "a_feature"
    assert exc.missing_dep == "nonexistent_feature"
    # INJECT-BUG CHECK: if pre-validation is removed (only Kahn's algorithm
    # runs), a missing dep would manifest as a cycle error or produce wrong
    # ordering instead of raising PluginMissingDependencyError with plugin/dep.


def test_missing_dep_identifies_correct_plugin_and_dep():
    """Error attributes correctly identify which plugin and which dep is missing."""
    b = _Stub("b_feature")  # present
    c = _Stub("c_feature", requires=("b_feature", "missing_x"))  # missing_x absent

    with pytest.raises(PluginMissingDependencyError) as exc_info:
        topological_sort([b, c])

    exc = exc_info.value
    assert exc.plugin == "c_feature", f"Wrong plugin: {exc.plugin}"
    assert exc.missing_dep == "missing_x", f"Wrong missing dep: {exc.missing_dep}"


# ---------------------------------------------------------------------------
# Test: real 4 plugins from the C1 feature set
# ---------------------------------------------------------------------------

def test_real_four_plugins_no_deps_alphabetical():
    """The 4 C1 plugins all have DECLARED_DEPS=() and REQUIRES=() → alphabetical."""
    import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
    import fresh_slotlab.analyzer.features.reel_marginal_by_spin_type  # noqa: F401
    import fresh_slotlab.analyzer.features.bankruptcy_simulation  # noqa: F401
    import fresh_slotlab.analyzer.features.multiplier_profile  # noqa: F401
    from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES

    result = topological_sort(ALL_FEATURES)
    fids = [f.FEATURE_ID for f in result]

    # All 4 should be present
    assert set(fids) == {
        "payouts_by_spin_type",
        "reel_marginal_by_spin_type",
        "bankruptcy_simulation",
        "multiplier_profile",
    }

    # Alphabetical: bankruptcy < multiplier < payouts < reel
    assert fids == sorted(fids), f"Expected alphabetical, got {fids}"
