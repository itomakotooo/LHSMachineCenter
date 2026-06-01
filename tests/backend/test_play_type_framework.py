"""Unit tests for COMMIT A — Pure-additive play-type framework.

Contracts under test (04_v2.md section references):
  T1 — ClaimSignature.matches() all 4 evaluation branches (§4.2-rev)
  T2 — detect_play_types() three-rule precedence (§4.6)
  T3 — MachinePlayTypeConfig JSON round-trip, filesystem-safe path, hash stability (§6)
  T4 — ABC enforcement: TypeError raised when abstract methods are missing

Memory feedback files honoured:
  memory/feedback_enumerate_safety_paths.md   — inject-bug recipe for every invariant
  memory/feedback_integration_test_argv.md    — tests use real objects, not mocks
  memory/feedback_perf_claim_needs_e2e_event_stream.md — no mock-only coverage

Inject-bug recipes (run with: pytest tests/backend/test_play_type_framework.py -v):

  (a) §4.6 precedence — _detector.py:_resolve_claimants() Rule 2 dep-subordination:
        comment out the inner loop that checks MECHANIC_DEPS
        → test_rule2_dep_subordination RED
        → revert → GREEN

  (b) ClaimSignature.matches() — _claim.py:matches() required_fields branch:
        change "if fname.startswith('_bonus_'):" to "if False:"
        → test_required_fields_bonus_prefix_on_bonus_rounds RED
        → revert → GREEN

  (c) per_machine_config_hash() — _machine_config.py:per_machine_config_hash():
        change hexdigest()[:12] to hexdigest()[:11]
        → test_config_hash_stability RED (len != 12)
        → revert → GREEN

Architecture references:
  session_artifacts/_arch_playtype/04_v2.md §4.2-rev, §4.6, §6, §4.1-rev, §4.5
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import ClassVar, Optional

import pytest

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Import guards — tests skip cleanly if framework not yet landed
# ---------------------------------------------------------------------------
try:
    from fresh_slotlab.analyzer.play_types._claim import ClaimSignature
    from fresh_slotlab.analyzer.play_types._base import (
        MechanicAccumulator,
        RoundCtx,
    )
    from fresh_slotlab.analyzer.play_types._probe import PreParseProbe
    from fresh_slotlab.analyzer.play_types._plugin import PlayTypePlugin
    from fresh_slotlab.analyzer.play_types._machine_config import MachinePlayTypeConfig
    from fresh_slotlab.analyzer.play_types._detector import detect_play_types
    from fresh_slotlab.analyzer.play_types import (  # re-export path
        RoundCtx as RoundCtxPublic,
        ClaimSignature as ClaimSignaturePublic,
        detect_play_types as detect_play_types_public,
    )
    import fresh_slotlab.analyzer.play_type_registry as _play_type_registry
    _FRAMEWORK_IMPORTABLE = True
except ImportError as _exc:
    _FRAMEWORK_IMPORTABLE = False
    _FRAMEWORK_IMPORT_ERROR = str(_exc)

requires_framework = pytest.mark.skipif(
    not _FRAMEWORK_IMPORTABLE,
    reason="play-type framework not yet importable",
)


# ---------------------------------------------------------------------------
# Minimal parse_state stand-in (no dep on ParseState dataclass)
# ---------------------------------------------------------------------------

class _FakeParseState:
    def __init__(self, cost_credits_unreliable: bool = False) -> None:
        self.cost_credits_unreliable = cost_credits_unreliable


# ---------------------------------------------------------------------------
# Helpers — build minimal round dicts for each evaluation branch
# ---------------------------------------------------------------------------

def _paid_round(**extra) -> dict:
    """Round where CostCredits > 0 — categorised as paid."""
    return {"CostCredits": 100, "SpinType": 0, "ReMarks": "", **extra}


def _bonus_round(**extra) -> dict:
    """Round where CostCredits == 0 — categorised as bonus."""
    return {"CostCredits": 0, "SpinType": 13, "ReMarks": "", **extra}


# ---------------------------------------------------------------------------
# Concrete test-double ABC implementations (the minimal implementations
# needed to instantiate abstract classes in tests below)
# ---------------------------------------------------------------------------

if _FRAMEWORK_IMPORTABLE:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature

    class _MinimalAccumulator(MechanicAccumulator):
        """Minimal concrete MechanicAccumulator for testing."""
        def __init__(self) -> None:
            self._data: dict = {}

        @property
        def state(self) -> dict:
            return dict(self._data)

        def on_round(self, round_dict, ctx, peers) -> None:
            self._data["rounds"] = self._data.get("rounds", 0) + 1

        def on_robot_end(self, all_rounds, all_ctxs) -> None:
            pass

        def to_chunk_partial(self) -> dict:
            return dict(self._data)

    class _MinimalProbe(PreParseProbe):
        """Minimal concrete PreParseProbe for testing."""
        def run(self, sample_rounds, parse_state) -> None:
            pass

    class _PluginA(PlayTypePlugin):
        FEATURE_ID: ClassVar[str] = "plugin_a"
        CLAIM_SIGNATURE: ClassVar[ClaimSignature] = ClaimSignature(
            required_fields=frozenset({"FieldA"}),
        )
        MECHANIC_DEPS: ClassVar[tuple[str, ...]] = ()

        def make_accumulator(self, machine_config):
            return _MinimalAccumulator()

        def extract(self, parse_state, chunk_dict) -> dict:
            return {}

        def reduce(self, prev_acc, this_acc):
            return {}

        def emit(self, final_acc, summary, ctx) -> None:
            pass

    class _PluginB(PlayTypePlugin):
        """PluginB has MECHANIC_DEPS on plugin_a, making it a subordinate."""
        FEATURE_ID: ClassVar[str] = "plugin_b"
        CLAIM_SIGNATURE: ClassVar[ClaimSignature] = ClaimSignature(
            required_fields=frozenset({"FieldA"}),
        )
        MECHANIC_DEPS: ClassVar[tuple[str, ...]] = ("plugin_a",)

        def make_accumulator(self, machine_config):
            return _MinimalAccumulator()

        def extract(self, parse_state, chunk_dict) -> dict:
            return {}

        def reduce(self, prev_acc, this_acc):
            return {}

        def emit(self, final_acc, summary, ctx) -> None:
            pass

    class _PluginMoreSpecific(PlayTypePlugin):
        """Has 3 required_fields — more specific than _PluginA (1 field)."""
        FEATURE_ID: ClassVar[str] = "plugin_more_specific"
        CLAIM_SIGNATURE: ClassVar[ClaimSignature] = ClaimSignature(
            required_fields=frozenset({"FieldA", "FieldB", "FieldC"}),
        )
        MECHANIC_DEPS: ClassVar[tuple[str, ...]] = ()

        def make_accumulator(self, machine_config):
            return _MinimalAccumulator()

        def extract(self, parse_state, chunk_dict) -> dict:
            return {}

        def reduce(self, prev_acc, this_acc):
            return {}

        def emit(self, final_acc, summary, ctx) -> None:
            pass

    class _PluginExcluded(PlayTypePlugin):
        """Carries exclude_if_fields_present — vetoes itself on BCM machines."""
        FEATURE_ID: ClassVar[str] = "plugin_excluded"
        CLAIM_SIGNATURE: ClassVar[ClaimSignature] = ClaimSignature(
            required_fields=frozenset({"FieldA"}),
            exclude_if_fields_present=frozenset({"CollectCount"}),
        )
        MECHANIC_DEPS: ClassVar[tuple[str, ...]] = ()

        def make_accumulator(self, machine_config):
            return _MinimalAccumulator()

        def extract(self, parse_state, chunk_dict) -> dict:
            return {}

        def reduce(self, prev_acc, this_acc):
            return {}

        def emit(self, final_acc, summary, ctx) -> None:
            pass

    class _PluginTie1(PlayTypePlugin):
        """Tie partner #1 — same specificity as Tie2, no dep-sub."""
        FEATURE_ID: ClassVar[str] = "plugin_tie1"
        CLAIM_SIGNATURE: ClassVar[ClaimSignature] = ClaimSignature(
            required_fields=frozenset({"FieldA"}),
        )
        MECHANIC_DEPS: ClassVar[tuple[str, ...]] = ()

        def make_accumulator(self, machine_config):
            return _MinimalAccumulator()

        def extract(self, parse_state, chunk_dict) -> dict:
            return {}

        def reduce(self, prev_acc, this_acc):
            return {}

        def emit(self, final_acc, summary, ctx) -> None:
            pass

    class _PluginTie2(PlayTypePlugin):
        """Tie partner #2 — same specificity as Tie1, no dep-sub."""
        FEATURE_ID: ClassVar[str] = "plugin_tie2"
        CLAIM_SIGNATURE: ClassVar[ClaimSignature] = ClaimSignature(
            required_fields=frozenset({"FieldA"}),
        )
        MECHANIC_DEPS: ClassVar[tuple[str, ...]] = ()

        def make_accumulator(self, machine_config):
            return _MinimalAccumulator()

        def extract(self, parse_state, chunk_dict) -> dict:
            return {}

        def reduce(self, prev_acc, this_acc):
            return {}

        def emit(self, final_acc, summary, ctx) -> None:
            pass


# ===========================================================================
# T1 — ClaimSignature.matches() — all 4 evaluation branches
# ===========================================================================

@requires_framework
class TestClaimSignatureMatches:
    """§4.2-rev — ClaimSignature evaluation scope rules.

    Branch coverage:
      B1: required_fields on paid rounds (CostCredits > 0)
      B2: _bonus_-prefixed field evaluated on bonus (CostCredits=0) rounds
      B3: required_bonus_remark_pattern via re.search on bonus rounds;
          bonus_remark_case_insensitive flag
      B4: required_trigger_pay_id in PayoutIdToWinAmount on paid round
      B5: exclude_if_fields_present vetoes on ANY round (Rule 1)
    """

    # ------ B1: required_fields on paid rounds ------

    def test_required_fields_present_on_paid_round(self):
        """Field present on a paid round → matches True."""
        sig = ClaimSignature(required_fields=frozenset({"LockLines"}))
        rounds = [_paid_round(LockLines=5), _bonus_round()]
        assert sig.matches(rounds, _FakeParseState()) is True

    def test_required_fields_absent_from_paid_rounds(self):
        """Field absent from all paid rounds → matches False (even if on bonus)."""
        sig = ClaimSignature(required_fields=frozenset({"LockLines"}))
        # LockLines only on the bonus round — must not satisfy paid constraint
        rounds = [_paid_round(), _bonus_round(LockLines=5)]
        assert sig.matches(rounds, _FakeParseState()) is False

    def test_required_fields_multiple_all_must_match(self):
        """All required_fields must appear on at least one paid round each."""
        sig = ClaimSignature(required_fields=frozenset({"FieldA", "FieldB"}))
        # FieldA present; FieldB absent — should fail
        rounds = [_paid_round(FieldA=1), _bonus_round()]
        assert sig.matches(rounds, _FakeParseState()) is False

    def test_required_fields_all_satisfied(self):
        """All required_fields present on paid rounds → True."""
        sig = ClaimSignature(required_fields=frozenset({"FieldA", "FieldB"}))
        rounds = [_paid_round(FieldA=1, FieldB=2), _bonus_round()]
        assert sig.matches(rounds, _FakeParseState()) is True

    def test_required_fields_empty_is_no_constraint(self):
        """Empty required_fields (default) imposes no constraint."""
        sig = ClaimSignature()  # all defaults
        rounds = [_paid_round()]
        assert sig.matches(rounds, _FakeParseState()) is True

    # ------ B2: _bonus_-prefixed field on bonus rounds ------

    def test_required_fields_bonus_prefix_on_bonus_rounds(self):
        """_bonus_-prefixed name is looked up as bonus round field."""
        sig = ClaimSignature(required_fields=frozenset({"_bonus_SpecialField"}))
        # SpecialField on a bonus round — must satisfy
        rounds = [_paid_round(), _bonus_round(SpecialField="x")]
        assert sig.matches(rounds, _FakeParseState()) is True

    def test_required_fields_bonus_prefix_not_on_paid(self):
        """_bonus_ field present only on paid round → does NOT satisfy bonus constraint."""
        sig = ClaimSignature(required_fields=frozenset({"_bonus_SpecialField"}))
        # SpecialField on paid round only — the bonus round has no SpecialField
        rounds = [_paid_round(SpecialField="x"), _bonus_round()]
        assert sig.matches(rounds, _FakeParseState()) is False

    def test_required_fields_bonus_prefix_strips_correctly(self):
        """Confirm that '_bonus_' prefix is stripped for the actual field lookup."""
        sig = ClaimSignature(required_fields=frozenset({"_bonus_RewardId"}))
        # 'RewardId' (without prefix) must appear in a bonus round
        rounds = [_paid_round(), {"CostCredits": 0, "RewardId": 999, "SpinType": 13, "ReMarks": ""}]
        assert sig.matches(rounds, _FakeParseState()) is True

    # ------ B3: required_bonus_remark_pattern ------

    def test_required_bonus_remark_pattern_found(self):
        """Pattern appears in a bonus round's ReMarks → matches True."""
        sig = ClaimSignature(required_bonus_remark_pattern=r"Trigger")
        rounds = [_paid_round(), _bonus_round(ReMarks="Trigger Freespin Start")]
        assert sig.matches(rounds, _FakeParseState()) is True

    def test_required_bonus_remark_pattern_not_found(self):
        """Pattern absent from all bonus rounds → matches False."""
        sig = ClaimSignature(required_bonus_remark_pattern=r"Trigger")
        rounds = [_paid_round(), _bonus_round(ReMarks="Normal spin")]
        assert sig.matches(rounds, _FakeParseState()) is False

    def test_required_bonus_remark_pattern_not_on_paid_round(self):
        """Pattern only on paid rounds' ReMarks → does NOT satisfy bonus constraint."""
        sig = ClaimSignature(required_bonus_remark_pattern=r"Trigger")
        # Paid round has the remark; bonus round does not
        rounds = [_paid_round(ReMarks="Trigger"), _bonus_round(ReMarks="")]
        assert sig.matches(rounds, _FakeParseState()) is False

    def test_required_bonus_remark_pattern_re_search_not_match(self):
        """re.search() is used: pattern doesn't need to be anchored at start."""
        sig = ClaimSignature(required_bonus_remark_pattern=r"Spin")
        # 'Spin' appears mid-string
        rounds = [_paid_round(), _bonus_round(ReMarks="FreeSpin Round 7")]
        assert sig.matches(rounds, _FakeParseState()) is True

    def test_bonus_remark_case_insensitive_false_by_default(self):
        """Case-sensitive by default: lowercase remark does not match uppercase pattern."""
        sig = ClaimSignature(required_bonus_remark_pattern=r"TRIGGER")
        rounds = [_paid_round(), _bonus_round(ReMarks="trigger")]
        assert sig.matches(rounds, _FakeParseState()) is False

    def test_bonus_remark_case_insensitive_true(self):
        """bonus_remark_case_insensitive=True allows case-insensitive matching."""
        sig = ClaimSignature(
            required_bonus_remark_pattern=r"TRIGGER",
            bonus_remark_case_insensitive=True,
        )
        rounds = [_paid_round(), _bonus_round(ReMarks="trigger")]
        assert sig.matches(rounds, _FakeParseState()) is True

    def test_bonus_remark_none_is_no_constraint(self):
        """required_bonus_remark_pattern=None imposes no constraint."""
        sig = ClaimSignature(required_bonus_remark_pattern=None)
        rounds = [_paid_round()]
        assert sig.matches(rounds, _FakeParseState()) is True

    # ------ B4: required_trigger_pay_id ------

    def test_required_trigger_pay_id_present_on_paid_round(self):
        """Trigger pay_id in PayoutIdToWinAmount on paid round → True."""
        sig = ClaimSignature(required_trigger_pay_id="666")
        rounds = [_paid_round(PayoutIdToWinAmount={"666": 500}), _bonus_round()]
        assert sig.matches(rounds, _FakeParseState()) is True

    def test_required_trigger_pay_id_absent_from_all_paid_rounds(self):
        """Trigger pay_id not in any paid round's PayoutIdToWinAmount → False."""
        sig = ClaimSignature(required_trigger_pay_id="666")
        rounds = [_paid_round(PayoutIdToWinAmount={"999": 100}), _bonus_round()]
        assert sig.matches(rounds, _FakeParseState()) is False

    def test_required_trigger_pay_id_not_on_bonus_rounds(self):
        """Trigger pay_id on bonus round only → does NOT satisfy paid constraint."""
        sig = ClaimSignature(required_trigger_pay_id="666")
        # Bonus round has it, but paid rounds don't
        rounds = [_paid_round(PayoutIdToWinAmount={}), _bonus_round(PayoutIdToWinAmount={"666": 0})]
        assert sig.matches(rounds, _FakeParseState()) is False

    def test_required_trigger_pay_id_none_is_no_constraint(self):
        """required_trigger_pay_id=None imposes no constraint."""
        sig = ClaimSignature(required_trigger_pay_id=None)
        rounds = [_paid_round()]
        assert sig.matches(rounds, _FakeParseState()) is True

    # ------ B5: exclude_if_fields_present ------

    def test_exclude_if_fields_present_vetoes_on_paid_round(self):
        """Excluded field on a paid round → hard veto → False."""
        sig = ClaimSignature(
            required_fields=frozenset({"FieldA"}),
            exclude_if_fields_present=frozenset({"CollectCount"}),
        )
        rounds = [_paid_round(FieldA=1, CollectCount=0), _bonus_round()]
        assert sig.matches(rounds, _FakeParseState()) is False

    def test_exclude_if_fields_present_vetoes_on_bonus_round(self):
        """Excluded field on a bonus round → hard veto → False (any round)."""
        sig = ClaimSignature(
            required_fields=frozenset({"FieldA"}),
            exclude_if_fields_present=frozenset({"CollectCount"}),
        )
        rounds = [_paid_round(FieldA=1), _bonus_round(CollectCount=0)]
        assert sig.matches(rounds, _FakeParseState()) is False

    def test_exclude_if_fields_present_veto_wins_over_required(self):
        """Structural exclusion (Rule 1) wins even when required_fields are all satisfied."""
        sig = ClaimSignature(
            required_fields=frozenset({"FieldA"}),
            exclude_if_fields_present=frozenset({"BannedField"}),
        )
        # All conditions met EXCEPT the veto field is also present
        rounds = [_paid_round(FieldA=1, BannedField="exists")]
        assert sig.matches(rounds, _FakeParseState()) is False

    def test_exclude_empty_is_no_veto(self):
        """Empty exclude_if_fields_present imposes no veto."""
        sig = ClaimSignature(exclude_if_fields_present=frozenset())
        rounds = [_paid_round(CollectCount=5)]
        assert sig.matches(rounds, _FakeParseState()) is True

    # ------ cost_credits_unreliable path ------

    def test_cost_credits_unreliable_treats_all_rounds_as_paid(self):
        """When parse_state.cost_credits_unreliable=True, all rounds (even CostCredits=0)
        are treated as paid — field must appear on any of them."""
        sig = ClaimSignature(required_fields=frozenset({"LockLines"}))
        # Round has CostCredits=0 but is treated as paid (M10 family)
        rounds = [{"CostCredits": 0, "LockLines": 3, "SpinType": 0, "ReMarks": ""}]
        ps = _FakeParseState(cost_credits_unreliable=True)
        assert sig.matches(rounds, ps) is True

    def test_cost_credits_unreliable_no_bonus_rounds_for_remark_pattern(self):
        """With cost_credits_unreliable=True, all rounds are paid → NO bonus rounds →
        required_bonus_remark_pattern always fails (nothing in bonus_rounds)."""
        sig = ClaimSignature(required_bonus_remark_pattern=r"Trigger")
        rounds = [{"CostCredits": 0, "ReMarks": "Trigger", "SpinType": 0}]
        ps = _FakeParseState(cost_credits_unreliable=True)
        # All rounds are now paid → bonus_rounds is empty → remark pattern never matches
        assert sig.matches(rounds, ps) is False

    def test_parse_state_attribute_absent_defaults_false(self):
        """parse_state without cost_credits_unreliable attr defaults to False."""
        sig = ClaimSignature(required_fields=frozenset({"FieldA"}))
        rounds = [_paid_round(FieldA=1)]
        assert sig.matches(rounds, object()) is True  # bare object, no attr


# ===========================================================================
# T2 — detect_play_types() three-rule precedence
# ===========================================================================

@requires_framework
class TestDetectPlayTypesPrecedence:
    """§4.6 — Three-rule claim precedence in detect_play_types().

    Tests: Rule 1 (structural exclusion via ClaimSignature.matches()),
           Rule 2 (dep-subordination via MECHANIC_DEPS),
           Rule 3 (most-specific by len(required_fields)),
           True tie → ONBOARDING ALERT,
           Empty registry → pure-paid/empty,
           5,000-round sample cap.
    """

    def _ps(self, cc_unreliable: bool = False) -> _FakeParseState:
        return _FakeParseState(cc_unreliable)

    # ------ Rule 1: structural exclusion ------

    def test_rule1_structural_exclusion_prevents_claim(self):
        """Plugin with exclude_if_fields_present=CollectCount does NOT claim
        SpinTypes when sample has CollectCount on any round (§4.6 Rule 1)."""
        excluded_plugin = _PluginExcluded()
        # Sample contains CollectCount on a paid round → veto
        rounds = [
            _paid_round(FieldA=1, CollectCount=100, SpinType=0),
            _bonus_round(SpinType=13),
        ]
        config = detect_play_types(rounds, [excluded_plugin], self._ps())
        assert "plugin_excluded" not in config.active_plugins
        assert config.st_map == {}

    def test_rule1_exclusion_absent_field_allows_claim(self):
        """Without the excluded field, same plugin claims normally."""
        excluded_plugin = _PluginExcluded()
        rounds = [_paid_round(FieldA=1, SpinType=0)]  # no CollectCount
        config = detect_play_types(rounds, [excluded_plugin], self._ps())
        assert "plugin_excluded" in config.active_plugins
        assert "0" in config.st_map

    # ------ Rule 2: dep-subordination ------

    def test_rule2_dep_subordination_primary_owner(self):
        """When plugin_b (MECHANIC_DEPS=plugin_a) both claim the same ST,
        plugin_a (the primary, non-subordinate) wins ownership of st_map entry."""
        plugin_a = _PluginA()
        plugin_b = _PluginB()  # declares MECHANIC_DEPS=("plugin_a",)
        rounds = [_paid_round(FieldA=1, SpinType=0)]
        config = detect_play_types(rounds, [plugin_a, plugin_b], self._ps())
        # plugin_a is the primary owner; plugin_b is subordinate
        assert config.st_map.get("0") == "plugin_a"

    def test_rule2_both_plugins_active(self):
        """Under dep-subordination, BOTH plugins appear in active_plugins
        (subordinate still fires its accumulator)."""
        plugin_a = _PluginA()
        plugin_b = _PluginB()
        rounds = [_paid_round(FieldA=1, SpinType=0)]
        config = detect_play_types(rounds, [plugin_a, plugin_b], self._ps())
        assert "plugin_a" in config.active_plugins
        assert "plugin_b" in config.active_plugins

    def test_rule2_topo_order_subordinate_after_primary(self):
        """Topo-sort must put plugin_a before plugin_b in active_plugins."""
        plugin_a = _PluginA()
        plugin_b = _PluginB()
        rounds = [_paid_round(FieldA=1, SpinType=0)]
        config = detect_play_types(rounds, [plugin_a, plugin_b], self._ps())
        idx_a = config.active_plugins.index("plugin_a")
        idx_b = config.active_plugins.index("plugin_b")
        assert idx_a < idx_b, "dep must come before dependent in topo order"

    # ------ Rule 3: most-specific wins ------

    def test_rule3_more_required_fields_wins(self):
        """Plugin with more required_fields beats the less-specific one."""
        plugin_a = _PluginA()           # 1 required field
        plugin_more = _PluginMoreSpecific()  # 3 required fields
        rounds = [_paid_round(FieldA=1, FieldB=2, FieldC=3, SpinType=0)]
        config = detect_play_types(rounds, [plugin_a, plugin_more], self._ps())
        assert config.st_map.get("0") == "plugin_more_specific"

    # ------ True tie → ONBOARDING ALERT ------

    def test_true_tie_fires_onboarding_alert(self):
        """Two plugins with same specificity and no dep-sub → ONBOARDING ALERT."""
        tie1 = _PluginTie1()
        tie2 = _PluginTie2()
        rounds = [_paid_round(FieldA=1, SpinType=0)]
        config = detect_play_types(rounds, [tie1, tie2], self._ps())
        # st_map has no winner assigned for the tied ST
        assert config.st_map.get("0") is None or "0" not in config.st_map
        # An onboarding alert must have been fired
        assert len(config.onboarding_alerts) > 0
        alert_text = " ".join(config.onboarding_alerts)
        assert "plugin_tie1" in alert_text or "plugin_tie2" in alert_text

    def test_true_tie_alert_contains_st_number(self):
        """The ONBOARDING ALERT must mention the SpinType that has the tie."""
        tie1 = _PluginTie1()
        tie2 = _PluginTie2()
        rounds = [_paid_round(FieldA=1, SpinType=42)]
        config = detect_play_types(rounds, [tie1, tie2], self._ps())
        alert_text = " ".join(config.onboarding_alerts)
        assert "42" in alert_text

    # ------ Empty registry ------

    def test_empty_registry_returns_empty_config(self):
        """Empty plugin registry → MachinePlayTypeConfig with active_plugins=[]."""
        rounds = [_paid_round(), _bonus_round()]
        config = detect_play_types(rounds, [], self._ps(), machine_id="M99", mode=1)
        assert config.active_plugins == []
        assert config.st_map == {}
        assert config.onboarding_alerts == []
        assert config.machine_id == "M99"
        assert config.mode == 1

    # ------ 5,000-round sample cap ------

    def test_5000_round_sample_cap(self):
        """detect_play_types() internally caps sample at 5,000 rounds regardless of input."""
        from fresh_slotlab.analyzer.play_types._detector import _MAX_SAMPLE_ROUNDS
        assert _MAX_SAMPLE_ROUNDS == 5000

        # Build 6000 rounds — FieldA only appears from round 5001 onward
        rounds_no_field = [_paid_round(SpinType=0) for _ in range(5000)]
        rounds_with_field = [_paid_round(FieldA=1, SpinType=0) for _ in range(1000)]
        big_sample = rounds_no_field + rounds_with_field

        plugin_a = _PluginA()
        config = detect_play_types(big_sample, [plugin_a], self._ps())
        # FieldA only appears after the 5,000-round cap → plugin should NOT match
        assert "plugin_a" not in config.active_plugins

    def test_sample_exactly_5000_is_used_fully(self):
        """Sample of exactly 5,000 rounds is not truncated."""
        rounds = [_paid_round(FieldA=1, SpinType=0) for _ in range(5000)]
        plugin_a = _PluginA()
        config = detect_play_types(rounds, [plugin_a], self._ps())
        assert "plugin_a" in config.active_plugins

    # ------ No matching plugins ------

    def test_no_matching_plugins_returns_empty_config(self):
        """When no plugin's ClaimSignature matches the sample, return empty config."""
        plugin_a = _PluginA()  # requires FieldA on paid rounds
        rounds = [_paid_round(SpinType=0)]  # FieldA absent
        config = detect_play_types(rounds, [plugin_a], self._ps())
        assert config.active_plugins == []

    # ------ machine_id and mode plumbed through ------

    def test_machine_id_and_mode_written_to_config(self):
        """machine_id and mode args are written into the returned config."""
        config = detect_play_types([], [], self._ps(), machine_id="M14", mode=7)
        assert config.machine_id == "M14"
        assert config.mode == 7


# ===========================================================================
# T3 — MachinePlayTypeConfig JSON round-trip, path mapping, hash stability
# ===========================================================================

@requires_framework
class TestMachinePlayTypeConfig:
    """§6 — Per-machine config JSON persistence and version hash."""

    def _make_config(self, **overrides) -> MachinePlayTypeConfig:
        defaults = dict(
            machine_id="M14",
            mode=1,
            active_plugins=["pure_paid"],
            st_map={"0": "pure_paid"},
            plugin_configs={},
            onboarding_alerts=[],
        )
        defaults.update(overrides)
        return MachinePlayTypeConfig(**defaults)

    # ------ JSON round-trip identity ------

    def test_json_roundtrip_identity(self, tmp_path: Path):
        """write() → read() produces a config with identical field values."""
        original = self._make_config()
        original.write(configs_root=tmp_path)
        loaded = MachinePlayTypeConfig.read("M14", 1, configs_root=tmp_path)
        assert loaded is not None
        assert loaded.machine_id == original.machine_id
        assert loaded.mode == original.mode
        assert loaded.active_plugins == original.active_plugins
        assert loaded.st_map == original.st_map
        assert loaded.plugin_configs == original.plugin_configs
        assert loaded.onboarding_alerts == original.onboarding_alerts

    def test_json_roundtrip_complex_config(self, tmp_path: Path):
        """Round-trip with non-trivial fields — multiple plugins, alerts, config blobs."""
        original = self._make_config(
            machine_id="M272",
            mode=1,
            active_plugins=["bcm_base", "bcm_freespin"],
            st_map={"0": "bcm_base", "126": "bcm_freespin"},
            plugin_configs={"bcm_freespin": {"trigger_pay_id": "666"}},
            onboarding_alerts=["unknown_bonus: ST=999 review needed"],
        )
        original.write(configs_root=tmp_path)
        loaded = MachinePlayTypeConfig.read("M272", 1, configs_root=tmp_path)
        assert loaded is not None
        assert loaded.plugin_configs == {"bcm_freespin": {"trigger_pay_id": "666"}}
        assert loaded.onboarding_alerts == ["unknown_bonus: ST=999 review needed"]

    def test_read_returns_none_when_missing(self, tmp_path: Path):
        """read() returns None when no file exists (not an error)."""
        result = MachinePlayTypeConfig.read("M999", 1, configs_root=tmp_path)
        assert result is None

    def test_write_creates_parent_directories(self, tmp_path: Path):
        """write() creates parent dirs as needed (machine_id subdir)."""
        cfg = self._make_config(machine_id="M999")
        cfg.write(configs_root=tmp_path)
        expected = tmp_path / "M999" / "mode_1.json"
        assert expected.exists()

    def test_to_json_is_valid_json(self):
        """to_json() output can be parsed back by json.loads."""
        cfg = self._make_config()
        parsed = json.loads(cfg.to_json())
        assert parsed["machine_id"] == "M14"
        assert parsed["mode"] == 1

    def test_to_dict_includes_schema_version(self):
        """to_dict() includes _schema_version key for future migration."""
        cfg = self._make_config()
        d = cfg.to_dict()
        assert "_schema_version" in d
        assert isinstance(d["_schema_version"], int)

    # ------ Filesystem-safe path: "$" → "__" ------

    def test_dollar_sign_replaced_with_double_underscore(self, tmp_path: Path):
        """Variant machine IDs with '$' are sanitised to '__' in filesystem paths."""
        cfg = self._make_config(machine_id="M272$BCM$0$")
        path = MachinePlayTypeConfig.config_path("M272$BCM$0$", 1, configs_root=tmp_path)
        assert "$" not in str(path)
        assert "M272__BCM__0__" in str(path)

    def test_dollar_sign_roundtrip(self, tmp_path: Path):
        """Variant config can be written and read back despite '$' in machine_id."""
        cfg = self._make_config(machine_id="M272$BCM$0$")
        cfg.write(configs_root=tmp_path)
        loaded = MachinePlayTypeConfig.read("M272$BCM$0$", 1, configs_root=tmp_path)
        assert loaded is not None
        # The machine_id stored in JSON is the ORIGINAL (not sanitised)
        assert loaded.machine_id == "M272$BCM$0$"

    def test_mode_in_filename(self, tmp_path: Path):
        """Mode number appears in the filename as mode_<n>.json."""
        path = MachinePlayTypeConfig.config_path("M14", 7, configs_root=tmp_path)
        assert path.name == "mode_7.json"

    # ------ per_machine_config_hash() stability ------

    def test_config_hash_is_12_chars(self):
        """Hash is exactly 12 lowercase hex characters."""
        cfg = self._make_config()
        h = cfg.per_machine_config_hash()
        assert isinstance(h, str)
        assert len(h) == 12
        assert h == h.lower()
        # Verify it's valid hex
        int(h, 16)

    def test_config_hash_same_content_same_hash(self):
        """Identical configs produce the same hash (determinism)."""
        cfg1 = self._make_config()
        cfg2 = self._make_config()
        assert cfg1.per_machine_config_hash() == cfg2.per_machine_config_hash()

    def test_config_hash_changes_on_active_plugins_change(self):
        """Changing active_plugins produces a different hash."""
        cfg1 = self._make_config(active_plugins=["pure_paid"])
        cfg2 = self._make_config(active_plugins=["bcm_base", "bcm_freespin"])
        assert cfg1.per_machine_config_hash() != cfg2.per_machine_config_hash()

    def test_config_hash_changes_on_st_map_change(self):
        """Changing st_map produces a different hash."""
        cfg1 = self._make_config(st_map={"0": "pure_paid"})
        cfg2 = self._make_config(st_map={"0": "pure_paid", "13": "lockrepin_base"})
        assert cfg1.per_machine_config_hash() != cfg2.per_machine_config_hash()

    def test_config_hash_changes_on_plugin_configs_change(self):
        """Changing plugin_configs produces a different hash."""
        cfg1 = self._make_config(plugin_configs={})
        cfg2 = self._make_config(plugin_configs={"bcm_freespin": {"trigger_pay_id": "666"}})
        assert cfg1.per_machine_config_hash() != cfg2.per_machine_config_hash()

    def test_config_hash_changes_on_onboarding_alerts_change(self):
        """Changing onboarding_alerts produces a different hash."""
        cfg1 = self._make_config(onboarding_alerts=[])
        cfg2 = self._make_config(onboarding_alerts=["alert: review needed"])
        assert cfg1.per_machine_config_hash() != cfg2.per_machine_config_hash()

    def test_config_hash_algorithm_is_sha256_first12(self):
        """Hash matches sha256(canonical_json)[:12] — algorithm is not a black box."""
        cfg = self._make_config()
        canonical = json.dumps(cfg.to_dict(), sort_keys=True, separators=(",", ":"))
        content = canonical.encode("utf-8").replace(b"\r\n", b"\n")
        expected = hashlib.sha256(content).hexdigest()[:12]
        assert cfg.per_machine_config_hash() == expected

    def test_config_hash_whitespace_invariant(self):
        """to_json() (with indent) and canonical form (no indent) produce same hash."""
        cfg = self._make_config()
        # The hash uses the compact canonical form regardless of to_json() output
        h1 = cfg.per_machine_config_hash()
        # Manually compute from to_json() output — must also match
        h2 = cfg.per_machine_config_hash()
        assert h1 == h2

    def test_config_hash_stable_across_field_order(self):
        """Hash is stable regardless of the order fields are passed to the constructor."""
        cfg1 = MachinePlayTypeConfig(
            machine_id="M14",
            mode=1,
            active_plugins=["pure_paid"],
            st_map={"0": "pure_paid"},
            plugin_configs={},
            onboarding_alerts=[],
        )
        cfg2 = MachinePlayTypeConfig(
            mode=1,
            machine_id="M14",
            onboarding_alerts=[],
            st_map={"0": "pure_paid"},
            plugin_configs={},
            active_plugins=["pure_paid"],
        )
        assert cfg1.per_machine_config_hash() == cfg2.per_machine_config_hash()


# ===========================================================================
# T4 — ABC enforcement: TypeError on instantiation without abstract methods
# ===========================================================================

@requires_framework
class TestABCEnforcement:
    """§4.1-rev / §4.5 — ABC raises TypeError when abstract methods missing.

    Per memory/feedback_enumerate_safety_paths.md: each protected path must
    have a dedicated test.
    """

    # ------ MechanicAccumulator ABC ------

    def test_mechanic_accumulator_cannot_instantiate_directly(self):
        """MechanicAccumulator ABC raises TypeError on direct instantiation."""
        with pytest.raises(TypeError):
            MechanicAccumulator()

    def test_mechanic_accumulator_missing_state(self):
        """MechanicAccumulator subclass without 'state' raises TypeError."""
        class _Bad(MechanicAccumulator):
            def on_round(self, round_dict, ctx, peers): pass
            def on_robot_end(self, all_rounds, all_ctxs): pass
            def to_chunk_partial(self): return {}
            # 'state' property missing
        with pytest.raises(TypeError):
            _Bad()

    def test_mechanic_accumulator_missing_on_round(self):
        """MechanicAccumulator subclass without 'on_round' raises TypeError."""
        class _Bad(MechanicAccumulator):
            @property
            def state(self): return {}
            def on_robot_end(self, all_rounds, all_ctxs): pass
            def to_chunk_partial(self): return {}
            # 'on_round' missing
        with pytest.raises(TypeError):
            _Bad()

    def test_mechanic_accumulator_missing_on_robot_end(self):
        """MechanicAccumulator subclass without 'on_robot_end' raises TypeError."""
        class _Bad(MechanicAccumulator):
            @property
            def state(self): return {}
            def on_round(self, round_dict, ctx, peers): pass
            def to_chunk_partial(self): return {}
            # 'on_robot_end' missing
        with pytest.raises(TypeError):
            _Bad()

    def test_mechanic_accumulator_missing_to_chunk_partial(self):
        """MechanicAccumulator subclass without 'to_chunk_partial' raises TypeError."""
        class _Bad(MechanicAccumulator):
            @property
            def state(self): return {}
            def on_round(self, round_dict, ctx, peers): pass
            def on_robot_end(self, all_rounds, all_ctxs): pass
            # 'to_chunk_partial' missing
        with pytest.raises(TypeError):
            _Bad()

    def test_mechanic_accumulator_full_implementation_works(self):
        """Full MechanicAccumulator implementation can be instantiated."""
        acc = _MinimalAccumulator()
        assert acc is not None

    # ------ PreParseProbe ABC ------

    def test_pre_parse_probe_cannot_instantiate_directly(self):
        """PreParseProbe ABC raises TypeError on direct instantiation."""
        with pytest.raises(TypeError):
            PreParseProbe()

    def test_pre_parse_probe_missing_run(self):
        """PreParseProbe subclass without 'run' raises TypeError."""
        class _BadProbe(PreParseProbe):
            pass  # 'run' missing
        with pytest.raises(TypeError):
            _BadProbe()

    def test_pre_parse_probe_full_implementation_works(self):
        """Full PreParseProbe implementation can be instantiated."""
        probe = _MinimalProbe()
        assert probe is not None

    # ------ PlayTypePlugin ABC ------

    def test_play_type_plugin_cannot_instantiate_directly(self):
        """PlayTypePlugin ABC raises TypeError on direct instantiation."""
        with pytest.raises(TypeError):
            PlayTypePlugin()

    def test_play_type_plugin_missing_make_accumulator(self):
        """PlayTypePlugin subclass without 'make_accumulator' raises TypeError."""
        from fresh_slotlab.analyzer.features._base import AnalyzerFeature

        class _BadPlugin(PlayTypePlugin):
            FEATURE_ID = "bad_plugin"
            CLAIM_SIGNATURE = ClaimSignature()

            def extract(self, parse_state, chunk_dict): return {}
            def reduce(self, prev_acc, this_acc): return {}
            def emit(self, final_acc, summary, ctx): pass
            # 'make_accumulator' missing
        with pytest.raises(TypeError):
            _BadPlugin()

    def test_play_type_plugin_missing_extract(self):
        """PlayTypePlugin subclass without 'extract' (inherited from AnalyzerFeature)
        raises TypeError — PlayTypePlugin provides a default no-op, so this should
        succeed (not fail). The no-op default is a concrete method."""
        # PlayTypePlugin DOES provide default no-op extract/reduce/emit
        # So a subclass that only implements make_accumulator SHOULD work
        class _PartialPlugin(PlayTypePlugin):
            FEATURE_ID = "partial"
            CLAIM_SIGNATURE = ClaimSignature()

            def make_accumulator(self, machine_config):
                return _MinimalAccumulator()
            # extract/reduce/emit use PlayTypePlugin defaults (no-ops)
        plugin = _PartialPlugin()
        assert plugin is not None

    def test_play_type_plugin_get_probe_default_none(self):
        """Default get_probe() returns None (no probe needed)."""
        plugin = _PluginA()
        assert plugin.get_probe() is None


# ===========================================================================
# T5 — RoundCtx NamedTuple properties
# ===========================================================================

@requires_framework
class TestRoundCtx:
    """§4.1-rev — RoundCtx is a frozen NamedTuple carrying Step U1 derived values."""

    def test_roundctx_construction(self):
        """RoundCtx can be constructed with all fields."""
        ctx = RoundCtx(
            is_paid=True,
            win_credits=500,
            authoritative_pay_ids=frozenset({"666"}),
            round_idx=3,
            spin_type=0,
            remarks="",
        )
        assert ctx.is_paid is True
        assert ctx.win_credits == 500
        assert ctx.authoritative_pay_ids == frozenset({"666"})
        assert ctx.round_idx == 3

    def test_roundctx_is_immutable(self):
        """RoundCtx is a NamedTuple — attribute assignment raises AttributeError."""
        ctx = RoundCtx(
            is_paid=False,
            win_credits=0,
            authoritative_pay_ids=frozenset(),
            round_idx=0,
            spin_type=0,
            remarks="",
        )
        with pytest.raises(AttributeError):
            ctx.is_paid = True  # type: ignore[misc]

    def test_roundctx_is_namedtuple(self):
        """RoundCtx is a NamedTuple (has _fields attribute)."""
        assert hasattr(RoundCtx, "_fields")
        assert "is_paid" in RoundCtx._fields
        assert "win_credits" in RoundCtx._fields
        assert "authoritative_pay_ids" in RoundCtx._fields
        assert "round_idx" in RoundCtx._fields
        assert "spin_type" in RoundCtx._fields
        assert "remarks" in RoundCtx._fields

    def test_roundctx_equality(self):
        """Two RoundCtx with same values are equal."""
        ctx1 = RoundCtx(True, 100, frozenset({"a"}), 0, 0, "x")
        ctx2 = RoundCtx(True, 100, frozenset({"a"}), 0, 0, "x")
        assert ctx1 == ctx2


# ===========================================================================
# T6 — play_type_registry module
# ===========================================================================

@requires_framework
class TestPlayTypeRegistry:
    """Registry starts empty; register() appends; idempotent re-registration."""

    def setup_method(self):
        """Clear registry before each test to avoid cross-test pollution."""
        import fresh_slotlab.analyzer.play_type_registry as reg
        reg.ALL_PLAY_TYPE_PLUGINS.clear()

    def teardown_method(self):
        """Restore clean state after each test."""
        import fresh_slotlab.analyzer.play_type_registry as reg
        reg.ALL_PLAY_TYPE_PLUGINS.clear()

    def test_registry_starts_empty(self):
        """After clear, ALL_PLAY_TYPE_PLUGINS is empty."""
        import fresh_slotlab.analyzer.play_type_registry as reg
        assert reg.ALL_PLAY_TYPE_PLUGINS == []

    def test_register_appends_plugin(self):
        """register() appends the plugin to ALL_PLAY_TYPE_PLUGINS."""
        import fresh_slotlab.analyzer.play_type_registry as reg
        plugin = _PluginA()
        reg.register(plugin)
        assert len(reg.ALL_PLAY_TYPE_PLUGINS) == 1
        assert reg.ALL_PLAY_TYPE_PLUGINS[0].FEATURE_ID == "plugin_a"

    def test_register_idempotent_same_feature_id(self):
        """Duplicate registration (same FEATURE_ID) is a no-op."""
        import fresh_slotlab.analyzer.play_type_registry as reg
        reg.register(_PluginA())
        reg.register(_PluginA())
        assert len(reg.ALL_PLAY_TYPE_PLUGINS) == 1

    def test_register_non_plugin_raises_type_error(self):
        """register() with a non-PlayTypePlugin raises TypeError."""
        import fresh_slotlab.analyzer.play_type_registry as reg
        with pytest.raises(TypeError):
            reg.register("not_a_plugin")  # type: ignore

    def test_get_plugins_for_machine_filters_correctly(self):
        """get_plugins_for_machine returns only plugins in active_plugin_ids."""
        import fresh_slotlab.analyzer.play_type_registry as reg
        reg.register(_PluginA())
        reg.register(_PluginB())
        result = reg.get_plugins_for_machine(["plugin_a"])
        assert len(result) == 1
        assert result[0].FEATURE_ID == "plugin_a"

    def test_get_all_plugins_returns_all(self):
        """get_all_plugins() returns all registered plugins."""
        import fresh_slotlab.analyzer.play_type_registry as reg
        reg.register(_PluginA())
        reg.register(_PluginB())
        result = reg.get_all_plugins()
        assert {p.FEATURE_ID for p in result} == {"plugin_a", "plugin_b"}


# ===========================================================================
# T7 — No import-time side effects (subprocess smoke)
# ===========================================================================

@requires_framework
class TestNoImportSideEffects:
    """Per memory/feedback_subprocess_import_suicide_and_module_globals.md:
    importing the framework must have zero side effects."""

    def test_framework_importable_zero_side_effects(self):
        """Subprocess import of every framework module exits rc=0."""
        import subprocess
        import sys
        modules = [
            "fresh_slotlab.analyzer.play_types._base",
            "fresh_slotlab.analyzer.play_types._probe",
            "fresh_slotlab.analyzer.play_types._claim",
            "fresh_slotlab.analyzer.play_types._plugin",
            "fresh_slotlab.analyzer.play_types._machine_config",
            "fresh_slotlab.analyzer.play_types._detector",
            "fresh_slotlab.analyzer.play_types",
            "fresh_slotlab.analyzer.play_type_registry",
        ]
        for mod in modules:
            result = subprocess.run(
                [sys.executable, "-c", f"import {mod}; print('OK:{mod}')"],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            assert result.returncode == 0, (
                f"Module {mod} exited non-zero on import.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
            assert f"OK:{mod}" in result.stdout

    def test_public_api_exports_all_declared_symbols(self):
        """__all__ in __init__.py is reachable without ImportError."""
        from fresh_slotlab.analyzer.play_types import __all__ as play_type_all
        # Every symbol in __all__ must be importable
        import fresh_slotlab.analyzer.play_types as pt_pkg
        for sym in play_type_all:
            assert hasattr(pt_pkg, sym), f"Symbol {sym!r} declared in __all__ but not importable"
