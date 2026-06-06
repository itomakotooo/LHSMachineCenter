"""Tests for fresh_slotlab/analyzer/pipeline_context.py — Phase C1, updated 5C.

Phase 5C: MechanismRegistry removed. PipelineContext now has 7 fields.
The mechanism_registry field is gone. MechanismRegistry class is deleted.

Failure modes caught by these tests
-------------------------------------
1. PipelineContext missing a required field (TypeError on construction).
2. PipelineContext mutability — a plugin accidentally mutates shared pipeline
   state.  frozen=True raises dataclasses.FrozenInstanceError on any attempt.

Inject-bug contracts (per memory/feedback_enumerate_safety_paths.md)
----------------------------------------------------------------------
Test: test_frozen_raises_on_mutation
  Bug: remove frozen=True from @dataclass(frozen=True) in pipeline_context.py
  Expected: FrozenInstanceError is NOT raised → test fails because ctx.total_spins = 99
             assignment succeeds silently instead of raising.
  Revert: restore frozen=True → test passes again.

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

from fresh_slotlab.analyzer.pipeline_context import PipelineContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(**overrides) -> PipelineContext:
    """Build a minimal valid PipelineContext for tests (7 fields, no mechanism_registry)."""
    defaults = dict(
        effective_bet_for_rtp=1_000_000.0,
        total_spins=10_000,
        total_paid_sessions=500,
        total_paid_spins=10_000,
        clamp_pending_robots_total=0,
        robots_with_pending_cycle=0,
        manifest={},
    )
    defaults.update(overrides)
    return PipelineContext(**defaults)


# ---------------------------------------------------------------------------
# Test 1: all 7 fields can be set without TypeError
# ---------------------------------------------------------------------------

class TestPipelineContextConstruction:
    """PipelineContext(all 7 fields) must succeed with correct types.

    Phase 5C: mechanism_registry field removed; 7 fields (was 8).
    """

    def test_all_fields_construct_no_error(self):
        """Construction with all 7 required fields must not raise."""
        ctx = PipelineContext(
            effective_bet_for_rtp=500.0,
            total_spins=230_000,
            total_paid_sessions=800,
            total_paid_spins=10_000,
            clamp_pending_robots_total=3,
            robots_with_pending_cycle=1,
            manifest={"modes": {"1": {}}},
        )
        assert ctx.effective_bet_for_rtp == 500.0
        assert ctx.total_spins == 230_000
        assert ctx.total_paid_sessions == 800
        assert ctx.total_paid_spins == 10_000
        assert ctx.clamp_pending_robots_total == 3
        assert ctx.robots_with_pending_cycle == 1
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
                manifest={},
            )

    def test_all_fields_attribute_access(self):
        """All 7 fields accessible as attributes (no mechanism_registry)."""
        ctx = _make_ctx()
        assert isinstance(ctx.effective_bet_for_rtp, float)
        assert isinstance(ctx.total_spins, int)
        assert isinstance(ctx.total_paid_sessions, int)
        assert isinstance(ctx.total_paid_spins, int)
        assert isinstance(ctx.clamp_pending_robots_total, int)
        assert isinstance(ctx.robots_with_pending_cycle, int)
        assert isinstance(ctx.manifest, dict)

    def test_mechanism_registry_field_absent(self):
        """PipelineContext must NOT have a mechanism_registry field (5C removed it)."""
        ctx = _make_ctx()
        assert not hasattr(ctx, "mechanism_registry"), (
            "mechanism_registry field must not exist in PipelineContext after 5C. "
            "The field was removed when MechanismRegistry was deleted."
        )

    def test_no_mechanism_registry_in_dataclass_fields(self):
        """mechanism_registry must not appear in dataclasses.fields(PipelineContext)."""
        field_names = {f.name for f in dataclasses.fields(PipelineContext)}
        assert "mechanism_registry" not in field_names, (
            f"mechanism_registry must not be a dataclass field after 5C. "
            f"Got fields: {sorted(field_names)}"
        )

    def test_exactly_seven_fields(self):
        """PipelineContext must have exactly 7 dataclass fields after 5C removal."""
        field_names = {f.name for f in dataclasses.fields(PipelineContext)}
        expected = {
            "effective_bet_for_rtp",
            "total_spins",
            "total_paid_sessions",
            "total_paid_spins",
            "clamp_pending_robots_total",
            "robots_with_pending_cycle",
            "manifest",
            "machine_spec_manifest",  # optional, has default
        }
        # 7 required + 1 optional with default = 8 names; but machine_spec_manifest
        # is optional (default_factory=dict), so it's still a field.
        assert field_names == expected, (
            f"PipelineContext must have fields: {sorted(expected)}\n"
            f"Got: {sorted(field_names)}"
        )

    def test_with_machine_spec_manifest(self):
        """machine_spec_manifest optional field accepted."""
        ctx = PipelineContext(
            effective_bet_for_rtp=1000.0,
            total_spins=10000,
            total_paid_sessions=500,
            total_paid_spins=500,
            clamp_pending_robots_total=0,
            robots_with_pending_cycle=0,
            manifest={},
            machine_spec_manifest={"spin_types": {"1": {"role": "paid_spin", "play": "Normal"}}},
        )
        assert ctx.machine_spec_manifest is not None
        assert "spin_types" in ctx.machine_spec_manifest


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

    def test_frozen_manifest_field(self):
        """Replacing manifest on a frozen ctx must raise."""
        ctx = _make_ctx()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            ctx.manifest = {}  # type: ignore[misc]
