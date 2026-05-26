"""Tests for fresh_slotlab/analyzer/pipeline_context.py — Phase C1.

Failure modes caught by these tests
-------------------------------------
1. PipelineContext missing a required field (TypeError on construction).
2. PipelineContext mutability — a plugin accidentally mutates shared pipeline
   state.  frozen=True raises dataclasses.FrozenInstanceError on any attempt.
3. MechanismRegistry missing to_summary_dict() or returning wrong keys.
4. MechanismRegistry initial state is not all-falsy (would mean C1 ships
   live detection logic that was explicitly deferred to C4).

Inject-bug contracts (per memory/feedback_enumerate_safety_paths.md)
----------------------------------------------------------------------
Test: test_frozen_raises_on_mutation
  Bug: remove frozen=True from @dataclass(frozen=True) in pipeline_context.py
  Expected: FrozenInstanceError is NOT raised → test fails because ctx.total_spins = 99
             assignment succeeds silently instead of raising.
  Revert: restore frozen=True → test passes again.

Test: test_mechanism_registry_all_falsy_initial_state
  Bug: set self.jackpot_applicable = True in MechanismRegistry.__init__
  Expected: assertion `mr.jackpot_applicable == False` fails.
  Revert: restore False → test passes again.

Test: test_mechanism_registry_to_summary_dict_keys
  Bug: remove "jackpot_applicable" key from to_summary_dict() return dict
  Expected: assertion about key presence fails.
  Revert: restore the key → test passes.

Memory files cited
------------------
- memory/feedback_subprocess_import_suicide_and_module_globals.md
  (import-time I/O check — covered by import-level module load)
- memory/feedback_enumerate_safety_paths.md
  (inject-bug recipes above)
- memory/feedback_no_silent_swallow.md
  (frozen dataclass ensures mutation attempt is never silent)
"""

from __future__ import annotations

import dataclasses

import pytest

from fresh_slotlab.analyzer.pipeline_context import MechanismRegistry, PipelineContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(**overrides) -> PipelineContext:
    """Build a minimal valid PipelineContext for tests."""
    defaults = dict(
        effective_bet_for_rtp=1_000_000.0,
        total_spins=10_000,
        total_paid_sessions=500,
        total_paid_spins=10_000,
        clamp_pending_robots_total=0,
        robots_with_pending_cycle=0,
        mechanism_registry=MechanismRegistry(),
        manifest={},
    )
    defaults.update(overrides)
    return PipelineContext(**defaults)


# ---------------------------------------------------------------------------
# Test 1: all 8 fields can be set without TypeError
# ---------------------------------------------------------------------------

class TestPipelineContextConstruction:
    """PipelineContext(all 8 fields) must succeed with correct types."""

    def test_all_fields_construct_no_error(self):
        """Construction with all 8 required fields must not raise."""
        mr = MechanismRegistry()
        ctx = PipelineContext(
            effective_bet_for_rtp=500.0,
            total_spins=230_000,
            total_paid_sessions=800,
            total_paid_spins=10_000,
            clamp_pending_robots_total=3,
            robots_with_pending_cycle=1,
            mechanism_registry=mr,
            manifest={"modes": {"1": {}}},
        )
        assert ctx.effective_bet_for_rtp == 500.0
        assert ctx.total_spins == 230_000
        assert ctx.total_paid_sessions == 800
        assert ctx.total_paid_spins == 10_000
        assert ctx.clamp_pending_robots_total == 3
        assert ctx.robots_with_pending_cycle == 1
        assert ctx.mechanism_registry is mr
        assert ctx.manifest == {"modes": {"1": {}}}

    def test_missing_field_raises_type_error(self):
        """Omitting any required field must raise TypeError."""
        with pytest.raises(TypeError):
            PipelineContext(  # type: ignore[call-arg]
                effective_bet_for_rtp=500.0,
                # total_spins intentionally missing
                total_paid_sessions=800,
                total_paid_spins=10_000,
                clamp_pending_robots_total=0,
                robots_with_pending_cycle=0,
                mechanism_registry=MechanismRegistry(),
                manifest={},
            )

    def test_all_fields_attribute_access(self):
        """All 8 fields accessible as attributes."""
        ctx = _make_ctx()
        # Verify all 8 attributes are accessible and return the right type
        assert isinstance(ctx.effective_bet_for_rtp, float)
        assert isinstance(ctx.total_spins, int)
        assert isinstance(ctx.total_paid_sessions, int)
        assert isinstance(ctx.total_paid_spins, int)
        assert isinstance(ctx.clamp_pending_robots_total, int)
        assert isinstance(ctx.robots_with_pending_cycle, int)
        assert isinstance(ctx.mechanism_registry, MechanismRegistry)
        assert isinstance(ctx.manifest, dict)


# ---------------------------------------------------------------------------
# Test 2: frozen dataclass — mutation raises FrozenInstanceError
# ---------------------------------------------------------------------------

class TestPipelineContextIsFrozen:
    """PipelineContext must be a frozen dataclass — mutation raises FrozenInstanceError.

    INJECT-BUG: remove frozen=True from @dataclass(frozen=True) in pipeline_context.py.
    After injection the mutation ctx.total_spins = 99 silently succeeds.
    pytest.raises(FrozenInstanceError) catches nothing → context manager exits
    without seeing the exception → raises pytest.fail internally → test is RED.

    Revert frozen=True → FrozenInstanceError raised → test is GREEN.
    """

    def test_frozen_raises_on_mutation(self):
        """Attempt to set any field after construction must raise FrozenInstanceError."""
        ctx = _make_ctx()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            ctx.total_spins = 99  # type: ignore[misc]

    def test_frozen_raises_on_new_attr(self):
        """Attempt to set a non-existent attribute must also raise."""
        ctx = _make_ctx()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            ctx.new_field = "should_fail"  # type: ignore[attr-defined]

    def test_frozen_mechanism_registry_field(self):
        """Replacing mechanism_registry on a frozen ctx must raise."""
        ctx = _make_ctx()
        new_mr = MechanismRegistry()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            ctx.mechanism_registry = new_mr  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 3: MechanismRegistry construction and to_summary_dict()
# ---------------------------------------------------------------------------

class TestMechanismRegistry:
    """MechanismRegistry placeholder must instantiate and return expected keys."""

    EXPECTED_SUMMARY_KEYS = {
        "jackpot_applicable",
        "jackpot_pid_set",
        "freespin_applicable",
        "scatter_marker_pids",
        "payout_groups_applicable",
        "_detection_source",
        "_phase",
    }

    def test_instantiates_no_error(self):
        """MechanismRegistry() must not raise."""
        mr = MechanismRegistry()
        assert mr is not None

    def test_to_summary_dict_returns_dict(self):
        """to_summary_dict() must return a dict."""
        mr = MechanismRegistry()
        result = mr.to_summary_dict()
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_to_summary_dict_keys_present(self):
        """to_summary_dict() must contain all expected keys.

        INJECT-BUG: remove any key (e.g. 'jackpot_applicable') from the return
        dict in to_summary_dict().
        Expected: assertion fails because key missing from result.
        Revert: restore the key → test passes.
        """
        mr = MechanismRegistry()
        result = mr.to_summary_dict()
        missing = self.EXPECTED_SUMMARY_KEYS - set(result.keys())
        assert not missing, (
            f"to_summary_dict() missing expected keys: {missing}. "
            f"Got: {sorted(result.keys())}"
        )

    def test_c1_phase_marker(self):
        """_phase key must be 'C1_placeholder' — confirms C4 logic not yet shipped."""
        mr = MechanismRegistry()
        result = mr.to_summary_dict()
        assert result["_phase"] == "C1_placeholder", (
            f"Expected C1_placeholder, got {result['_phase']!r}"
        )


# ---------------------------------------------------------------------------
# Test 4: MechanismRegistry initial state all-falsy (C1 is a no-op)
# ---------------------------------------------------------------------------

class TestMechanismRegistryInitialState:
    """C1 ships placeholder — all detection fields must be falsy.

    INJECT-BUG: set self.jackpot_applicable = True in MechanismRegistry.__init__.
    Expected: assertion mr.jackpot_applicable == False fails.
    Revert: restore False → test passes.
    """

    def test_all_applicable_flags_false(self):
        """All *_applicable booleans must be False in the C1 placeholder."""
        mr = MechanismRegistry()
        assert mr.jackpot_applicable is False, (
            "jackpot_applicable must be False in C1 placeholder"
        )
        assert mr.freespin_applicable is False, (
            "freespin_applicable must be False in C1 placeholder"
        )
        assert mr.payout_groups_applicable is False, (
            "payout_groups_applicable must be False in C1 placeholder"
        )

    def test_all_pid_sets_empty(self):
        """All frozenset fields must be empty in the C1 placeholder."""
        mr = MechanismRegistry()
        assert len(mr.jackpot_pid_set) == 0, (
            f"jackpot_pid_set must be empty, got {mr.jackpot_pid_set}"
        )
        assert len(mr.scatter_marker_pids) == 0, (
            f"scatter_marker_pids must be empty, got {mr.scatter_marker_pids}"
        )

    def test_detection_source_empty(self):
        """_detection_source dict must be empty in the C1 placeholder."""
        mr = MechanismRegistry()
        assert mr._detection_source == {}, (
            f"_detection_source must be empty, got {mr._detection_source}"
        )

    def test_summary_dict_falsy_applicable_values(self):
        """to_summary_dict() must reflect the falsy state in all applicable flags."""
        mr = MechanismRegistry()
        d = mr.to_summary_dict()
        assert d["jackpot_applicable"] is False
        assert d["freespin_applicable"] is False
        assert d["payout_groups_applicable"] is False
        assert d["jackpot_pid_set"] == []
        assert d["scatter_marker_pids"] == []
