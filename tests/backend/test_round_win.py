"""Unit tests for fresh_slotlab.round_win.

Coverage axes:
  * Default fallback (no rules) is byte-identical to legacy
    WinCredits / PayoutIdToWinAmount lookup
  * SettlementWinAmountRule: phantom -> 0, settlement -> WinAmount,
    extract_payouts returns {} on both, paid passthrough
  * SynthesizePayIdRule: three label_format modes; gracefully
    skips when bet unknown / fractional multiplier under multiplier mode
  * extract_round_win / extract_round_payouts dispatch
  * load_rules_for_machine: matches via applies_to, skips unknown
    types and bad params, robust to None/empty config
"""
from __future__ import annotations

import pytest

from fresh_slotlab.round_win import (
    RULE_REGISTRY,
    RoundWinRule,
    SettlementWinAmountRule,
    SynthesizePayIdRule,
    extract_round_payouts,
    extract_round_win,
    load_rules_for_machine,
)


# ---------------------------------------------------------------------
# Default fallback -- must match legacy r.get("WinCredits", 0) and
# r.get("PayoutIdToWinAmount") bit-for-bit
# ---------------------------------------------------------------------


class TestExtractRoundWinDefault:
    def test_no_rules_returns_wincredits(self):
        r = {"WinCredits": 1234, "SpinType": 1, "CostCredits": 1000}
        assert extract_round_win(r) == 1234.0
        assert extract_round_win(r, rules=None) == 1234.0
        assert extract_round_win(r, rules=[]) == 1234.0

    def test_no_rules_missing_wincredits_returns_zero(self):
        r = {"SpinType": 15, "WinAmount": 60000}
        assert extract_round_win(r) == 0.0

    def test_no_rules_none_wincredits_returns_zero(self):
        r = {"WinCredits": None, "SpinType": 14}
        assert extract_round_win(r) == 0.0

    def test_no_rules_string_wincredits_coerced(self):
        r = {"WinCredits": "5000"}
        assert extract_round_win(r) == 5000.0

    def test_non_dict_input_returns_zero(self):
        assert extract_round_win(None) == 0.0
        assert extract_round_win("not a dict") == 0.0
        assert extract_round_win(42) == 0.0
        assert extract_round_win([1, 2, 3]) == 0.0


class TestExtractRoundPayoutsDefault:
    def test_no_rules_returns_pid_dict(self):
        r = {"PayoutIdToWinAmount": {"6": 1110, "3": 6660}}
        result = extract_round_payouts(r)
        assert result == {"6": 1110.0, "3": 6660.0}

    def test_no_rules_missing_pid_returns_empty(self):
        assert extract_round_payouts({"WinCredits": 100}) == {}

    def test_no_rules_none_pid_returns_empty(self):
        assert extract_round_payouts({"PayoutIdToWinAmount": None}) == {}

    def test_no_rules_empty_dict_pid_returns_empty(self):
        assert extract_round_payouts({"PayoutIdToWinAmount": {}}) == {}

    def test_no_rules_non_dict_pid_returns_empty(self):
        assert extract_round_payouts({"PayoutIdToWinAmount": "weird"}) == {}

    def test_non_dict_input_returns_empty(self):
        assert extract_round_payouts(None) == {}
        assert extract_round_payouts(42) == {}


# ---------------------------------------------------------------------
# SettlementWinAmountRule
# ---------------------------------------------------------------------


class TestSettlementWinAmountRule:
    def _rule(self) -> SettlementWinAmountRule:
        return SettlementWinAmountRule(
            phantom_spin_types=[14],
            settlement_spin_types=[15],
        )

    # extract_win
    def test_paid_round_passthrough(self):
        rule = self._rule()
        r = {"SpinType": 1, "CostCredits": 1000, "WinCredits": 400}
        assert rule.extract_win(r) is None
        assert rule.extract_payouts(r) is None

    def test_paid_round_with_phantom_st_passthrough(self):
        rule = self._rule()
        r = {"SpinType": 14, "CostCredits": 1000, "WinCredits": 9999}
        assert rule.extract_win(r) is None
        assert rule.extract_payouts(r) is None

    def test_phantom_offer_returns_zero(self):
        rule = self._rule()
        r = {"SpinType": 14, "CostCredits": 0, "WinCredits": 30000}
        assert rule.extract_win(r) == 0.0

    def test_phantom_offer_returns_empty_payouts(self):
        rule = self._rule()
        r = {"SpinType": 14, "CostCredits": 0, "WinCredits": 30000}
        assert rule.extract_payouts(r) == {}

    def test_settlement_returns_winamount(self):
        rule = self._rule()
        r = {"SpinType": 15, "CostCredits": 0, "WinAmount": 60000}
        assert rule.extract_win(r) == 60000.0

    def test_settlement_returns_empty_payouts(self):
        """Settlement also suppresses round-level pid credit -- the
        trigger_session helper attributes the win to the trigger
        pay_id (e.g., '666') instead, so round-level must NOT
        also credit anyone or the helper double-counts."""
        rule = self._rule()
        r = {"SpinType": 15, "CostCredits": 0, "WinAmount": 60000}
        assert rule.extract_payouts(r) == {}

    def test_settlement_missing_winamount_returns_zero(self):
        rule = self._rule()
        r = {"SpinType": 15, "CostCredits": 0}
        assert rule.extract_win(r) == 0.0

    def test_unconfigured_spin_type_returns_none(self):
        rule = self._rule()
        r = {"SpinType": 99, "CostCredits": 0, "WinCredits": 100}
        assert rule.extract_win(r) is None
        assert rule.extract_payouts(r) is None

    def test_string_spin_type_coerced(self):
        rule = self._rule()
        r = {"SpinType": "14", "CostCredits": 0, "WinCredits": 30000}
        assert rule.extract_win(r) == 0.0
        assert rule.extract_payouts(r) == {}


# ---------------------------------------------------------------------
# SynthesizePayIdRule
# ---------------------------------------------------------------------


class TestSynthesizePayIdRuleMultiplier:
    def _rule(self) -> SynthesizePayIdRule:
        return SynthesizePayIdRule(spin_types=[2], label_format="multiplier")

    def test_wheel_round_synthesizes_multiplier(self):
        """M279 wheel: ST=2, win=20000, bet=1000 -> pid '20'."""
        rule = self._rule()
        r = {"SpinType": 2, "WinCredits": 20000, "BetAmount": None,
             "CostCredits": None, "PayoutIdToWinAmount": {}}
        result = rule.extract_payouts(r, ctx={"bet": 1000})
        assert result == {"20": 20000.0}

    def test_uses_betamount_when_present(self):
        rule = self._rule()
        r = {"SpinType": 2, "WinCredits": 5000, "BetAmount": 1000,
             "CostCredits": None, "PayoutIdToWinAmount": None}
        result = rule.extract_payouts(r)  # no ctx, BetAmount present
        assert result == {"5": 5000.0}

    def test_falls_through_on_fractional_multiplier(self):
        """M260 wheel sometimes gives win/bet not integer -- multiplier
        format can't synthesize a clean label, returns None to let
        the caller use the default empty pid (so the win remains
        gap'd; reported by the scan)."""
        rule = self._rule()
        r = {"SpinType": 2, "WinCredits": 1500, "PayoutIdToWinAmount": {}}
        result = rule.extract_payouts(r, ctx={"bet": 1000})
        assert result is None

    def test_unconfigured_spin_type_no_synthesis(self):
        rule = self._rule()
        r = {"SpinType": 140, "WinCredits": 5000, "PayoutIdToWinAmount": {}}
        result = rule.extract_payouts(r, ctx={"bet": 1000})
        assert result is None

    def test_zero_win_no_synthesis(self):
        rule = self._rule()
        r = {"SpinType": 2, "WinCredits": 0, "PayoutIdToWinAmount": {}}
        assert rule.extract_payouts(r, ctx={"bet": 1000}) is None

    def test_existing_pid_passthrough_by_default(self):
        """If round has non-empty PayoutIdToWinAmount, don't override
        unless explicitly asked (apply_when_pid_present=True)."""
        rule = self._rule()
        r = {"SpinType": 2, "WinCredits": 20000,
             "PayoutIdToWinAmount": {"100": 20000}}
        result = rule.extract_payouts(r, ctx={"bet": 1000})
        assert result is None

    def test_zero_value_pid_treated_as_empty(self):
        """PayoutIdToWinAmount={'X': 0} (trigger token) is empty for
        synthesis purposes -- it carries no real win credit so the
        rule should still synthesize."""
        rule = self._rule()
        r = {"SpinType": 2, "WinCredits": 50000,
             "PayoutIdToWinAmount": {"trigger_token": 0}}
        result = rule.extract_payouts(r, ctx={"bet": 1000})
        assert result == {"50": 50000.0}

    def test_no_bet_returns_none(self):
        rule = self._rule()
        r = {"SpinType": 2, "WinCredits": 20000, "PayoutIdToWinAmount": {}}
        # No BetAmount on round, no ctx -> can't compute multiplier.
        result = rule.extract_payouts(r, ctx=None)
        assert result is None

    def test_extract_win_is_passthrough(self):
        """Multiplier rule only synthesizes pid -- win extraction
        stays at default (legacy WinCredits)."""
        rule = self._rule()
        r = {"SpinType": 2, "WinCredits": 20000}
        assert rule.extract_win(r) is None


class TestSynthesizePayIdRuleSpinType:
    def _rule(self) -> SynthesizePayIdRule:
        return SynthesizePayIdRule(spin_types=[46], label_format="spin_type")

    def test_freespin_synthesizes_st_label(self):
        """M24 ST=46 freespin: win=12000, bet=1000 -- multiplier
        would be 12 (clean) but spin_type format ignores that and
        produces 'st46' (one bucket per SpinType, simpler drilldown)."""
        rule = self._rule()
        r = {"SpinType": 46, "WinCredits": 12000, "BetAmount": 1000,
             "CostCredits": 0, "PayoutIdToWinAmount": None}
        result = rule.extract_payouts(r, ctx={"bet": 1000})
        assert result == {"st46": 12000.0}

    def test_fractional_win_still_synthesized(self):
        """M268 ST=125 fractional multiplier (1.4x bet) still gets
        a 'st125' label under spin_type format -- unlike multiplier
        format which would refuse."""
        rule = SynthesizePayIdRule(spin_types=[125], label_format="spin_type")
        r = {"SpinType": 125, "WinCredits": 1400, "BetAmount": 1000,
             "PayoutIdToWinAmount": None}
        result = rule.extract_payouts(r)
        assert result == {"st125": 1400.0}


class TestSynthesizePayIdRuleSpinTypeMultiplier:
    def _rule(self) -> SynthesizePayIdRule:
        return SynthesizePayIdRule(spin_types=[2], label_format="spin_type_multiplier")

    def test_integer_multiplier_combined_label(self):
        rule = self._rule()
        r = {"SpinType": 2, "WinCredits": 20000, "BetAmount": 1000,
             "PayoutIdToWinAmount": {}}
        result = rule.extract_payouts(r)
        assert result == {"st2_x20": 20000.0}

    def test_fractional_multiplier_falls_back_to_st_only(self):
        rule = self._rule()
        r = {"SpinType": 2, "WinCredits": 1500, "BetAmount": 1000,
             "PayoutIdToWinAmount": {}}
        result = rule.extract_payouts(r)
        assert result == {"st2": 1500.0}


class TestSynthesizePayIdRuleApplyWhenPidPresent:
    def test_override_existing_pid(self):
        rule = SynthesizePayIdRule(
            spin_types=[2], label_format="multiplier",
            apply_when_pid_present=True,
        )
        r = {"SpinType": 2, "WinCredits": 20000, "BetAmount": 1000,
             "PayoutIdToWinAmount": {"old_pid": 5000}}
        # Even though pid is non-empty, apply_when_pid_present forces synthesis.
        result = rule.extract_payouts(r)
        assert result == {"20": 20000.0}


class TestSynthesizePayIdRuleValidation:
    def test_invalid_label_format_raises(self):
        with pytest.raises(ValueError, match="label_format"):
            SynthesizePayIdRule(spin_types=[2], label_format="bogus_format")


# ---------------------------------------------------------------------
# extract_round_win / extract_round_payouts dispatch
# ---------------------------------------------------------------------


class TestExtractRoundDispatch:
    def test_rule_overrides_default_win(self):
        rule = SettlementWinAmountRule(
            phantom_spin_types=[14], settlement_spin_types=[15],
        )
        r_phantom = {"SpinType": 14, "CostCredits": 0, "WinCredits": 30000}
        r_settle = {"SpinType": 15, "CostCredits": 0, "WinAmount": 60000}
        assert extract_round_win(r_phantom, rules=[rule]) == 0.0
        assert extract_round_win(r_settle, rules=[rule]) == 60000.0

    def test_rule_falls_through_to_default_win(self):
        rule = SettlementWinAmountRule(phantom_spin_types=[14], settlement_spin_types=[15])
        r = {"SpinType": 1, "CostCredits": 1000, "WinCredits": 400}
        assert extract_round_win(r, rules=[rule]) == 400.0

    def test_rule_overrides_default_payouts(self):
        rule = SynthesizePayIdRule(spin_types=[2], label_format="multiplier")
        r = {"SpinType": 2, "WinCredits": 20000, "BetAmount": 1000,
             "PayoutIdToWinAmount": {}}
        result = extract_round_payouts(r, rules=[rule])
        assert result == {"20": 20000.0}

    def test_rule_falls_through_to_default_payouts(self):
        """Rule says no-opinion (None) -> caller gets default
        round.PayoutIdToWinAmount."""
        rule = SynthesizePayIdRule(spin_types=[2], label_format="multiplier")
        r = {"SpinType": 140, "WinCredits": 5000, "PayoutIdToWinAmount": {"6": 5000}}
        result = extract_round_payouts(r, rules=[rule])
        assert result == {"6": 5000.0}

    def test_rule_returning_empty_dict_suppresses_round_pid(self):
        """Empty dict from rule must short-circuit -- caller does
        NOT fall through to round.PayoutIdToWinAmount even if
        non-empty (intentional suppression for selector phantom/settlement)."""
        rule = SettlementWinAmountRule(phantom_spin_types=[14], settlement_spin_types=[15])
        r = {"SpinType": 14, "CostCredits": 0, "WinCredits": 30000,
             "PayoutIdToWinAmount": {"some_id": 999}}  # would credit if rule didn't suppress
        result = extract_round_payouts(r, rules=[rule])
        assert result == {}

    def test_first_matching_rule_wins(self):
        rule_a = SynthesizePayIdRule(spin_types=[2], label_format="spin_type")
        rule_b = SynthesizePayIdRule(spin_types=[2], label_format="multiplier")
        r = {"SpinType": 2, "WinCredits": 20000, "BetAmount": 1000,
             "PayoutIdToWinAmount": {}}
        # rule_a fires first, returns {'st2': 20000}
        result = extract_round_payouts(r, rules=[rule_a, rule_b])
        assert result == {"st2": 20000.0}

    def test_first_rule_passes_second_handles(self):
        rule_a = SynthesizePayIdRule(spin_types=[99], label_format="spin_type")
        rule_b = SynthesizePayIdRule(spin_types=[2], label_format="multiplier")
        r = {"SpinType": 2, "WinCredits": 20000, "BetAmount": 1000,
             "PayoutIdToWinAmount": {}}
        result = extract_round_payouts(r, rules=[rule_a, rule_b])
        assert result == {"20": 20000.0}


# ---------------------------------------------------------------------
# load_rules_for_machine
# ---------------------------------------------------------------------


class TestLoadRulesForMachine:
    def _config(self) -> dict:
        return {
            "rules": {
                "topdollar_selector_settlement": {
                    "type": "settlement_winamount",
                    "params": {
                        "phantom_spin_types": [14],
                        "settlement_spin_types": [15],
                    },
                    "applies_to": [
                        "M12$TopDollarSelector$0$",
                        "M15$TopDollarSelector$0$",
                    ],
                },
                "wheel_bonus_st2_multiplier": {
                    "type": "synthesize_pay_id",
                    "params": {
                        "spin_types": [2],
                        "label_format": "multiplier",
                    },
                    "applies_to": ["M279", "M214"],
                },
            },
        }

    def test_machine_in_applies_to_gets_rule(self):
        rules = load_rules_for_machine("M12$TopDollarSelector$0$", self._config())
        assert len(rules) == 1
        assert isinstance(rules[0], SettlementWinAmountRule)

    def test_wheel_machine_gets_synthesize_rule(self):
        rules = load_rules_for_machine("M279", self._config())
        assert len(rules) == 1
        assert isinstance(rules[0], SynthesizePayIdRule)
        assert rules[0].spin_types == frozenset([2])
        assert rules[0].label_format == "multiplier"

    def test_machine_in_multiple_rules_gets_all(self):
        cfg = self._config()
        # Add M279 to topdollar rule too (artificial, but tests stacking).
        cfg["rules"]["topdollar_selector_settlement"]["applies_to"].append("M279")
        rules = load_rules_for_machine("M279", cfg)
        assert len(rules) == 2

    def test_machine_not_in_applies_to_returns_empty(self):
        rules = load_rules_for_machine("M14", self._config())
        assert rules == []

    def test_none_config_returns_empty(self):
        assert load_rules_for_machine("M12$TopDollarSelector$0$", None) == []

    def test_empty_config_returns_empty(self):
        assert load_rules_for_machine("M12", {}) == []

    def test_unknown_rule_type_skipped(self):
        cfg = {"rules": {"r1": {
            "type": "totally_unknown_type",
            "params": {},
            "applies_to": ["M12"],
        }}}
        assert load_rules_for_machine("M12", cfg) == []

    def test_bad_params_skipped(self):
        cfg = {"rules": {"r1": {
            "type": "settlement_winamount",
            "params": {"unknown_kwarg": "x"},
            "applies_to": ["M12"],
        }}}
        assert load_rules_for_machine("M12", cfg) == []

    def test_invalid_label_format_skipped(self):
        """ValueError from rule constructor (e.g. invalid
        label_format) is caught and the rule is silently skipped."""
        cfg = {"rules": {"r1": {
            "type": "synthesize_pay_id",
            "params": {"spin_types": [2], "label_format": "bogus"},
            "applies_to": ["M279"],
        }}}
        assert load_rules_for_machine("M279", cfg) == []


# ---------------------------------------------------------------------
# Registry self-check
# ---------------------------------------------------------------------


def test_registry_has_known_types():
    assert "settlement_winamount" in RULE_REGISTRY
    assert "synthesize_pay_id" in RULE_REGISTRY
    assert RULE_REGISTRY["settlement_winamount"] is SettlementWinAmountRule
    assert RULE_REGISTRY["synthesize_pay_id"] is SynthesizePayIdRule
