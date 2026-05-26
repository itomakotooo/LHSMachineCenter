"""Unit tests for topo-sort exception surfacing — Phase C1.

Verifies that PluginCyclicDependencyError and PluginMissingDependencyError
are raised by topological_sort() with correct structured attributes.

Per brief §4 acceptance criterion 5: "inject test that registers a cyclic
plugin pair; assert PluginCyclicDependencyError is raised with cycle attr".

Design note on subprocess-level surfacing:
  The brief notes that subprocess-level surfacing (summary["analyzer_init_error"]
  + stderr + rc != 0) is harder to test as a unit test because it requires
  injecting a cyclic plugin into the real feature registry, running the full
  PIA subprocess, then restoring the registry — a multi-step stateful mutation.
  We test the unit-level contract here (topological_sort raises) which is the
  critical invariant. The subprocess-level path is covered indirectly by the
  byte-identical tests (which verify no analyzer_init_error on success path).
  A full subprocess-level inject test is left as TODO for Phase C2 when a
  stable test fixture for plugin registration exists.

Failure modes caught
---------------------
1. PluginCyclicDependencyError not raised on A→B→A cycle.
2. PluginCyclicDependencyError.cycle attribute missing or wrong type.
3. PluginCyclicDependencyError raised before PluginMissingDependencyError
   (ordering matters — missing dep is checked first).
4. PluginMissingDependencyError not raised on missing dep.
5. PluginMissingDependencyError.plugin / .missing_dep attributes wrong.
6. Three-node cycle (A→B→C→A) not detected.

Inject-bug contract (per memory/feedback_enumerate_safety_paths.md)
----------------------------------------------------------------------
Test: test_cycle_a_b_raises_PluginCyclicDependencyError
  Bug: in topo_sort.py, remove the cycle detection block (the
       `if len(result) < len(features)` check and the raise).
       Replace with `return result` (silently returns partial result).
  Expected: pytest.raises(PluginCyclicDependencyError) exits without the
    exception being raised → test is RED.
  Revert: restore the cycle detection block → test is GREEN.

Test: test_missing_dep_raises_before_cycle_check
  Bug: in topo_sort.py, remove the pre-validation loop (the
       `for feat in features: for dep_id in feat.REQUIRES: if dep_id not in...`
       block). Only Kahn's algorithm runs.
  Expected: missing dep is silently treated as if it doesn't exist;
    Kahn's terminates early and raises PluginCyclicDependencyError instead of
    PluginMissingDependencyError → test_missing_dep_raises_before_cycle_check
    assertion `isinstance(exc, PluginMissingDependencyError)` fails.
  Revert: restore pre-validation loop → PluginMissingDependencyError raised first.

Memory files cited
------------------
- memory/feedback_no_silent_swallow.md
  (plugin errors must raise loudly, not silently return partial result)
- memory/feedback_enumerate_safety_paths.md
  (inject-bug protocol mandatory for each test)
- memory/feedback_subprocess_import_suicide_and_module_globals.md
  (no import-time I/O in topo_sort.py — verified by the import in this file)
"""

from __future__ import annotations

import pytest

from fresh_slotlab.analyzer.topo_sort import (
    PluginCyclicDependencyError,
    PluginMissingDependencyError,
    topological_sort,
)


# ---------------------------------------------------------------------------
# Minimal stub feature — no ABC overhead, matches what topo_sort expects
# ---------------------------------------------------------------------------

class _MockFeature:
    """Minimal mock AnalyzerFeature for injection testing.

    Only FEATURE_ID and REQUIRES are needed by topological_sort.
    """

    def __init__(self, fid: str, requires: tuple[str, ...] = ()) -> None:
        self.FEATURE_ID = fid
        self.REQUIRES = requires
        self.DECLARED_DEPS: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Test group 1: cyclic dependency detection
# ---------------------------------------------------------------------------

class TestPluginCyclicDependencyError:
    """topological_sort must raise PluginCyclicDependencyError on any cycle."""

    def test_cycle_a_b_raises(self):
        """A→B, B→A: direct two-node cycle must raise.

        INJECT-BUG: remove the cycle detection block (len(result) < len(features)
        check + raise PluginCyclicDependencyError) in topo_sort.py.
        After injection: returns partial list silently → pytest.raises context
        exits cleanly without exception → test RED.
        Revert: restore cycle detection → raises correctly → test GREEN.
        """
        a = _MockFeature("cycle_test_a", requires=("cycle_test_b",))
        b = _MockFeature("cycle_test_b", requires=("cycle_test_a",))

        with pytest.raises(PluginCyclicDependencyError) as exc_info:
            topological_sort([a, b])

        exc = exc_info.value
        # .cycle must be a list containing at least one of the involved nodes
        assert isinstance(exc.cycle, list), (
            f"PluginCyclicDependencyError.cycle must be list, got {type(exc.cycle)}"
        )
        assert len(exc.cycle) >= 1, (
            "PluginCyclicDependencyError.cycle must name at least one node"
        )
        # Both a and b are in the cycle; at least one must appear
        assert "cycle_test_a" in exc.cycle or "cycle_test_b" in exc.cycle, (
            f"Neither 'cycle_test_a' nor 'cycle_test_b' in exc.cycle: {exc.cycle}"
        )

    def test_cycle_error_message_is_informative(self):
        """Error message string must mention 'cycle' for human readability."""
        a = _MockFeature("alpha", requires=("beta",))
        b = _MockFeature("beta", requires=("alpha",))

        with pytest.raises(PluginCyclicDependencyError) as exc_info:
            topological_sort([a, b])

        msg = str(exc_info.value).lower()
        assert "cycle" in msg, (
            f"Error message does not mention 'cycle': {str(exc_info.value)!r}"
        )

    def test_three_node_cycle_raises(self):
        """A→B→C→A: three-node cycle must raise PluginCyclicDependencyError."""
        a = _MockFeature("node_a", requires=("node_c",))
        b = _MockFeature("node_b", requires=("node_a",))
        c = _MockFeature("node_c", requires=("node_b",))

        with pytest.raises(PluginCyclicDependencyError) as exc_info:
            topological_sort([a, b, c])

        exc = exc_info.value
        assert isinstance(exc.cycle, list)
        # All 3 nodes involved — at least 2 should be reported
        involved = set(exc.cycle) & {"node_a", "node_b", "node_c"}
        assert len(involved) >= 1, (
            f"Expected at least one of {{node_a, node_b, node_c}} in cycle, "
            f"got: {exc.cycle}"
        )

    def test_cycle_with_valid_prefix_node_raises(self):
        """A valid no-dep node plus a cyclic pair — cycle still detected."""
        # "ok_node" has no deps, so it would complete successfully.
        # But "bad_a"↔"bad_b" form a cycle; cycle detection must still fire.
        ok = _MockFeature("ok_node")
        bad_a = _MockFeature("bad_a", requires=("bad_b",))
        bad_b = _MockFeature("bad_b", requires=("bad_a",))

        with pytest.raises(PluginCyclicDependencyError):
            topological_sort([ok, bad_a, bad_b])


# ---------------------------------------------------------------------------
# Test group 2: missing dependency detection
# ---------------------------------------------------------------------------

class TestPluginMissingDependencyError:
    """topological_sort must raise PluginMissingDependencyError for missing deps."""

    def test_single_missing_dep_raises(self):
        """Plugin declaring REQUIRES for a non-existent feature must raise.

        INJECT-BUG: remove the pre-validation loop in topo_sort.py
        (the `for feat in features: for dep_id in feat.REQUIRES:` block).
        After injection: missing dep not detected → Kahn's stalls → raises
        PluginCyclicDependencyError instead → isinstance check fails → RED.
        Revert: restore pre-validation → PluginMissingDependencyError raised → GREEN.
        """
        a = _MockFeature("feature_a", requires=("nonexistent_feature",))

        with pytest.raises(PluginMissingDependencyError) as exc_info:
            topological_sort([a])

        exc = exc_info.value
        assert exc.plugin == "feature_a", (
            f"Expected exc.plugin == 'feature_a', got {exc.plugin!r}"
        )
        assert exc.missing_dep == "nonexistent_feature", (
            f"Expected exc.missing_dep == 'nonexistent_feature', got {exc.missing_dep!r}"
        )

    def test_missing_dep_raises_before_cycle_check(self):
        """Missing dep must be detected BEFORE cycle check runs.

        If a feature declares a missing dep, the error must be
        PluginMissingDependencyError, not PluginCyclicDependencyError.
        """
        # Feature that has BOTH a missing dep AND would form a cycle if the
        # missing dep were present. Missing dep must win.
        a = _MockFeature("feature_x", requires=("missing_dep", "feature_y"))
        b = _MockFeature("feature_y", requires=("feature_x",))

        exc = None
        try:
            topological_sort([a, b])
        except PluginMissingDependencyError as e:
            exc = e
        except PluginCyclicDependencyError as e:
            pytest.fail(
                f"Expected PluginMissingDependencyError (missing dep check runs first), "
                f"but got PluginCyclicDependencyError: {e}"
            )

        assert exc is not None, "Expected PluginMissingDependencyError to be raised"
        assert exc.missing_dep == "missing_dep"

    def test_missing_dep_error_message_is_informative(self):
        """Error message must identify plugin and missing dep for debugging."""
        a = _MockFeature("my_plugin", requires=("the_missing_dep",))

        with pytest.raises(PluginMissingDependencyError) as exc_info:
            topological_sort([a])

        msg = str(exc_info.value)
        assert "my_plugin" in msg, (
            f"Plugin name 'my_plugin' not in error message: {msg!r}"
        )
        assert "the_missing_dep" in msg, (
            f"Missing dep 'the_missing_dep' not in error message: {msg!r}"
        )

    def test_second_dep_missing_correctly_identified(self):
        """When multiple deps are declared, the missing one is correctly identified."""
        present = _MockFeature("present_feature")
        consumer = _MockFeature(
            "consumer",
            requires=("present_feature", "absent_feature"),
        )

        with pytest.raises(PluginMissingDependencyError) as exc_info:
            topological_sort([present, consumer])

        exc = exc_info.value
        assert exc.plugin == "consumer"
        assert exc.missing_dep == "absent_feature"


# ---------------------------------------------------------------------------
# Test group 3: error attributes are correctly structured
# ---------------------------------------------------------------------------

class TestErrorAttributes:
    """Exception attribute correctness — used by PIA to build analyzer_init_error."""

    def test_cyclic_error_has_cycle_attr(self):
        """PluginCyclicDependencyError must expose .cycle as a list."""
        a = _MockFeature("a", requires=("b",))
        b = _MockFeature("b", requires=("a",))

        try:
            topological_sort([a, b])
        except PluginCyclicDependencyError as e:
            assert hasattr(e, "cycle"), "PluginCyclicDependencyError must have .cycle"
            assert isinstance(e.cycle, list), ".cycle must be a list"
        else:
            pytest.fail("PluginCyclicDependencyError not raised")

    def test_missing_dep_error_has_plugin_and_missing_dep_attrs(self):
        """PluginMissingDependencyError must expose .plugin and .missing_dep."""
        a = _MockFeature("my_feat", requires=("no_such_feat",))

        try:
            topological_sort([a])
        except PluginMissingDependencyError as e:
            assert hasattr(e, "plugin"), "Must have .plugin attr"
            assert hasattr(e, "missing_dep"), "Must have .missing_dep attr"
            assert isinstance(e.plugin, str), ".plugin must be str"
            assert isinstance(e.missing_dep, str), ".missing_dep must be str"
        else:
            pytest.fail("PluginMissingDependencyError not raised")

    def test_cyclic_error_is_exception_subclass(self):
        """Both error classes must be Exception subclasses (catchable by PIA)."""
        a = _MockFeature("a", requires=("b",))
        b = _MockFeature("b", requires=("a",))

        with pytest.raises(Exception):  # noqa: B017  (catches any Exception)
            topological_sort([a, b])

    def test_missing_dep_error_is_exception_subclass(self):
        """PluginMissingDependencyError must be catchable as Exception."""
        a = _MockFeature("a", requires=("missing",))

        with pytest.raises(Exception):  # noqa: B017
            topological_sort([a])


# ---------------------------------------------------------------------------
# Test group 4: no-error cases are not affected by error path changes
# ---------------------------------------------------------------------------

class TestNoFalsePositives:
    """Verify error cases don't fire on valid inputs."""

    def test_two_valid_nodes_no_error(self):
        """A valid A→B dependency graph must not raise any error."""
        a = _MockFeature("provider_a")
        b = _MockFeature("consumer_b", requires=("provider_a",))

        result = topological_sort([a, b])
        assert len(result) == 2
        fids = [f.FEATURE_ID for f in result]
        assert fids.index("provider_a") < fids.index("consumer_b")

    def test_empty_input_no_error(self):
        """Empty feature list must return empty list without raising."""
        result = topological_sort([])
        assert result == []

    def test_single_feature_no_deps_no_error(self):
        """Single feature with no deps must not raise."""
        a = _MockFeature("solo_feature")
        result = topological_sort([a])
        assert len(result) == 1
        assert result[0].FEATURE_ID == "solo_feature"
