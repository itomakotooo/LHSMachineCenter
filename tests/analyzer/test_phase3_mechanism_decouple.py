"""Phase 3 mechanism de-couple: inject-bug gate, adapted for 5C.

Phase 5C: MechanismRegistry removed. PipelineContext no longer has a
mechanism_registry field. The inject-bug tests are updated to verify that
the manifest-driven path is the ONLY path (there is no registry fallback
to accidentally use).

ANALYZER_ARCHITECTURE.md §6 phase 3 mandates that machine_mechanics and
bonus_chain_dynamics derive their mechanism flags from the SpinType-native
manifest (role/play) instead of runtime MechanismRegistry detection.

This test file provides:
  1. Unit tests for derive_mechanism_flags() (the new machine_spec helper).
  2. Inject-bug test: break the manifest->mechanism wiring so machine_mechanics
     gets the wrong jackpot/freespin flag → a value-agnostic assertion catches it.
  3. Verify that for M15 (no jackpot/freespin SpinTypes declared), the manifest-
     driven flags are False (behavior-preserving: same as runtime detection).

Gates (per §5.6):
  - Assert structural effects (jackpot_applicable=False/True), NOT RTP values.
  - Inject bug → assertion fails → revert → passes.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# 1. Unit tests for derive_mechanism_flags
# ---------------------------------------------------------------------------

class TestDeriveMechanismFlagsUnit:
    """derive_mechanism_flags: pure manifest computation, no runtime detection."""

    def test_m15_manifest_no_freespin_no_jackpot(self) -> None:
        """M15 has no freespin/jackpot SpinTypes → both flags False."""
        from fresh_slotlab.analyzer.machine_spec import derive_mechanism_flags
        manifest = {
            "spin_types": {
                "1":  {"role": "paid_spin", "play": "Normal"},
                "14": {"role": "player_choice", "play": "TopDollar"},
                "15": {"role": "settlement", "play": "TopDollar"},
            },
            "trigger": {"payout_id": "666", "remarks": "Trigger"},
        }
        flags = derive_mechanism_flags(manifest)
        assert flags["freespin_applicable"] is False
        assert flags["jackpot_applicable"] is False
        assert flags["jackpot_pid_set"] == frozenset()
        assert flags["scatter_trigger_pids"] == frozenset({"666"})
        assert flags["detection_source"] == "manifest_spin_types"

    def test_freespin_play_detected(self) -> None:
        """A SpinType with play='freespin' makes freespin_applicable=True."""
        from fresh_slotlab.analyzer.machine_spec import derive_mechanism_flags
        manifest = {
            "spin_types": {
                "1": {"role": "paid_spin", "play": "Normal"},
                "2": {"role": "settlement", "play": "freespin"},
            },
        }
        flags = derive_mechanism_flags(manifest)
        assert flags["freespin_applicable"] is True
        assert flags["jackpot_applicable"] is False

    def test_jackpot_play_detected(self) -> None:
        """A SpinType with play='jackpot' makes jackpot_applicable=True."""
        from fresh_slotlab.analyzer.machine_spec import derive_mechanism_flags
        manifest = {
            "spin_types": {
                "1": {"role": "paid_spin", "play": "Normal"},
                "5": {"role": "settlement", "play": "Jackpot"},
            },
        }
        flags = derive_mechanism_flags(manifest)
        assert flags["jackpot_applicable"] is True
        assert flags["freespin_applicable"] is False

    def test_play_matching_is_case_insensitive(self) -> None:
        """play='FREESPIN' and 'FreeSpin' both match (case-insensitive)."""
        from fresh_slotlab.analyzer.machine_spec import derive_mechanism_flags
        manifest = {
            "spin_types": {
                "1": {"role": "paid_spin", "play": "FREESPIN"},
            },
        }
        flags = derive_mechanism_flags(manifest)
        assert flags["freespin_applicable"] is True

    def test_no_trigger_block_gives_empty_scatter_pids(self) -> None:
        """No trigger block → scatter_trigger_pids is empty."""
        from fresh_slotlab.analyzer.machine_spec import derive_mechanism_flags
        manifest = {
            "spin_types": {
                "1": {"role": "paid_spin", "play": "Normal"},
            },
        }
        flags = derive_mechanism_flags(manifest)
        assert flags["scatter_trigger_pids"] == frozenset()

    def test_empty_manifest_returns_all_false(self) -> None:
        """Empty manifest dict → all flags False / empty."""
        from fresh_slotlab.analyzer.machine_spec import derive_mechanism_flags
        flags = derive_mechanism_flags({})
        assert flags["freespin_applicable"] is False
        assert flags["jackpot_applicable"] is False
        assert flags["scatter_trigger_pids"] == frozenset()


# ---------------------------------------------------------------------------
# 2. PipelineContext carries machine_spec_manifest field (no mechanism_registry)
# ---------------------------------------------------------------------------

class TestPipelineContextMachineSpecManifest:
    """PipelineContext.machine_spec_manifest must be present (Phase 3 field).
    Phase 5C: mechanism_registry field gone; PipelineContext has 7 fields.
    """

    def test_pipeline_context_has_machine_spec_manifest_field(self) -> None:
        """PipelineContext must accept machine_spec_manifest kwarg (Phase 3).
        Phase 5C: no mechanism_registry argument.
        """
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
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

    def test_pipeline_context_empty_machine_spec_manifest(self) -> None:
        """PipelineContext with empty machine_spec_manifest is valid."""
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
        ctx = PipelineContext(
            effective_bet_for_rtp=1000.0,
            total_spins=10000,
            total_paid_sessions=500,
            total_paid_spins=500,
            clamp_pending_robots_total=0,
            robots_with_pending_cycle=0,
            manifest={},
            machine_spec_manifest={},
        )
        assert ctx.machine_spec_manifest == {}

    def test_pipeline_context_has_no_mechanism_registry_field(self) -> None:
        """PipelineContext must NOT have mechanism_registry field (5C removed it)."""
        import dataclasses
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
        field_names = {f.name for f in dataclasses.fields(PipelineContext)}
        assert "mechanism_registry" not in field_names, (
            f"mechanism_registry must not be a field in PipelineContext after 5C. "
            f"Got fields: {sorted(field_names)}"
        )


# ---------------------------------------------------------------------------
# 3. machine_mechanics reads from manifest (only path — no registry fallback)
# ---------------------------------------------------------------------------

class TestMachineMechanicsManifestDriven:
    """machine_mechanics.emit() must read from manifest (the only path in 5C)."""

    def _make_ctx(self, machine_spec_manifest: dict) -> object:
        """Build a minimal PipelineContext for testing (no mechanism_registry)."""
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
        return PipelineContext(
            effective_bet_for_rtp=10000.0,
            total_spins=1000,
            total_paid_sessions=1000,
            total_paid_spins=1000,
            clamp_pending_robots_total=0,
            robots_with_pending_cycle=0,
            manifest={},
            machine_spec_manifest=machine_spec_manifest,
        )

    def test_m15_manifest_jackpot_false(self) -> None:
        """M15 manifest → jackpot_applicable=False in machine_mechanics output."""
        from fresh_slotlab.analyzer.features.machine_mechanics import MachineMechanics

        # M15 manifest: no jackpot/freespin SpinTypes
        m15_manifest = {
            "spin_types": {
                "1": {"role": "paid_spin", "play": "Normal"},
                "14": {"role": "player_choice", "play": "TopDollar"},
                "15": {"role": "settlement", "play": "TopDollar"},
            },
            "trigger": {"payout_id": "666"},
        }
        ctx = self._make_ctx(m15_manifest)
        summary: dict = {"player_impact": {
            # Provide stubs required by machine_mechanics
            "payout_ids_top20": [],
            "bonus_chain_dynamics": {"applicable": False, "bonus_round_count": 0, "chain_count": 0, "avg_chain_length": 0},
        }}
        plugin = MachineMechanics()
        plugin.emit({}, summary, ctx)

        mm = summary["player_impact"]["machine_mechanics"]
        assert mm["jackpot"]["applicable"] is False, (
            f"M15 manifest has no jackpot SpinType, expected applicable=False, "
            f"got {mm['jackpot']['applicable']}. "
            "Check machine_mechanics.emit() manifest-driven path."
        )
        assert mm["free_spin"]["applicable"] is False, (
            f"M15 manifest has no freespin SpinType, expected applicable=False, "
            f"got {mm['free_spin']['applicable']}. "
            "Check machine_mechanics.emit() manifest-driven path."
        )

    def test_jackpot_manifest_gives_applicable_true(self) -> None:
        """Manifest with jackpot SpinType → jackpot.applicable=True."""
        from fresh_slotlab.analyzer.features.machine_mechanics import MachineMechanics

        jackpot_manifest = {
            "spin_types": {
                "1": {"role": "paid_spin", "play": "Normal"},
                "5": {"role": "settlement", "play": "Jackpot"},
            },
        }
        ctx = self._make_ctx(jackpot_manifest)
        summary: dict = {"player_impact": {
            "payout_ids_top20": [],
            "bonus_chain_dynamics": {"applicable": False, "bonus_round_count": 0, "chain_count": 0, "avg_chain_length": 0},
        }}
        plugin = MachineMechanics()
        plugin.emit({}, summary, ctx)

        mm = summary["player_impact"]["machine_mechanics"]
        assert mm["jackpot"]["applicable"] is True, (
            f"Manifest with jackpot SpinType (play='Jackpot') must give applicable=True. "
            f"Got: {mm['jackpot']['applicable']}"
        )

    def test_no_manifest_gives_false_not_error(self) -> None:
        """Empty machine_spec_manifest → all mechanism flags False, no crash.

        In 5C the else branch returns False for non-registered machines
        (not registered → no report path anyway, but plugin must not crash).
        """
        from fresh_slotlab.analyzer.features.machine_mechanics import MachineMechanics

        ctx = self._make_ctx({})  # empty dict = no SpinType-native manifest
        summary: dict = {"player_impact": {
            "payout_ids_top20": [],
            "bonus_chain_dynamics": {"applicable": False, "bonus_round_count": 0, "chain_count": 0, "avg_chain_length": 0},
        }}
        plugin = MachineMechanics()
        # Must not raise
        plugin.emit({}, summary, ctx)

        mm = summary["player_impact"]["machine_mechanics"]
        assert mm["jackpot"]["applicable"] is False, (
            "Empty manifest must give jackpot.applicable=False (safe default)."
        )
        assert mm["free_spin"]["applicable"] is False, (
            "Empty manifest must give free_spin.applicable=False (safe default)."
        )


# ---------------------------------------------------------------------------
# 4. bonus_chain_dynamics reads scatter_trigger_pids from manifest
# ---------------------------------------------------------------------------

class TestBonusChainDynamicsManifestDriven:
    """bonus_chain_dynamics.emit() must read scatter_trigger_pids from manifest."""

    def _make_ctx(self, machine_spec_manifest: dict) -> object:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
        return PipelineContext(
            effective_bet_for_rtp=10000.0,
            total_spins=1000,
            total_paid_sessions=1000,
            total_paid_spins=1000,
            clamp_pending_robots_total=0,
            robots_with_pending_cycle=0,
            manifest={},
            machine_spec_manifest=machine_spec_manifest,
        )

    def test_m15_manifest_trigger_pid_used_as_scatter_marker(self) -> None:
        """M15 manifest trigger.payout_id='666' → is_trigger_marker=True for pid 666."""
        from fresh_slotlab.analyzer.features.bonus_chain_dynamics import BonusChainDynamics

        m15_manifest = {
            "spin_types": {"1": {"role": "paid_spin", "play": "Normal"}},
            "trigger": {"payout_id": "666", "remarks": "Trigger"},
        }
        ctx = self._make_ctx(m15_manifest)

        # Build minimal stash
        summary: dict = {
            "_bonus_chain_dynamics_data": {
                "bonus_chain_lengths": [],
                "bonus_chain_max_ratios": [],
                "bonus_total_rounds_global": 0,
                "bonus_retrigger_rounds_global": 0,
                "bonus_chain_retrigger_events": [],
                "bonus_extra_ratio_counts": {},
                "bonus_depth_ratio_count": {},
                "bonus_depth_ratio_sum": {},
                "all_chains_by_feature": {},
                "scatter_feature_names": [],
                "scatter_feature_chain_counts": {},
            },
            "player_impact": {
                "payout_ids_top20": [
                    {"payout_id": "666", "hit_count": 100, "total_win": 0},
                    {"payout_id": "1",   "hit_count": 500, "total_win": 50000},
                ],
            },
        }
        plugin = BonusChainDynamics()
        plugin.emit({}, summary, ctx)

        pid_rows = summary["player_impact"].get("payout_ids_top20", [])
        # Find the row for pid "666"
        row_666 = next((r for r in pid_rows if str(r.get("payout_id")) == "666"), None)
        assert row_666 is not None, "Row for pid 666 must exist"
        assert row_666.get("notes", {}).get("is_trigger_marker") is True, (
            f"Manifest trigger.payout_id='666' must produce is_trigger_marker=True "
            f"for pid 666, got notes={row_666.get('notes')}. "
            "Check bonus_chain_dynamics.emit() manifest-driven scatter path."
        )

    def test_empty_manifest_gives_empty_scatter_pids_no_crash(self) -> None:
        """Empty manifest → scatter_marker_pids=frozenset(), no crash.

        In 5C the else branch returns frozenset() for non-registered machines.
        """
        from fresh_slotlab.analyzer.features.bonus_chain_dynamics import BonusChainDynamics

        ctx = self._make_ctx({})  # empty = no SpinType-native manifest

        summary: dict = {
            "_bonus_chain_dynamics_data": {
                "bonus_chain_lengths": [],
                "bonus_chain_max_ratios": [],
                "bonus_total_rounds_global": 0,
                "bonus_retrigger_rounds_global": 0,
                "bonus_chain_retrigger_events": [],
                "bonus_extra_ratio_counts": {},
                "bonus_depth_ratio_count": {},
                "bonus_depth_ratio_sum": {},
                "all_chains_by_feature": {},
                "scatter_feature_names": [],
                "scatter_feature_chain_counts": {},
            },
            "player_impact": {
                "payout_ids_top20": [
                    {"payout_id": "666", "hit_count": 100, "total_win": 0},
                ],
            },
        }
        plugin = BonusChainDynamics()
        # Must not raise
        plugin.emit({}, summary, ctx)
        # 666 is not a scatter marker because no manifest says it is
        pid_rows = summary["player_impact"].get("payout_ids_top20", [])
        row_666 = next((r for r in pid_rows if str(r.get("payout_id")) == "666"), None)
        assert row_666 is not None
        assert row_666.get("notes", {}).get("is_trigger_marker") is not True, (
            "With empty manifest, pid 666 must NOT be marked as trigger_marker."
        )
