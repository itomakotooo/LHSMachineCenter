"""Unit tests for fresh_slotlab.round_win.

Coverage axes:
  * Default fallback (no rules) is byte-identical to legacy WinCredits lookup
  * SettlementWinAmountRule: phantom → 0, settlement → WinAmount, paid passthrough
  * load_rules_for_machine: matches via applies_to, skips unknown types,
    skips bad params, robust to None/empty config
  * extract_round_win: rule order, fallthrough, edge cases (None/missing keys)
"""
from __future__ import annotations

import pytest

from fresh_slotlab.round_win import (
    RULE_REGISTRY,
    RoundWinRule,
    SettlementWinAmountRule,
    extract_round_win,
    load_rules_for_machine,
)


# ---------------------------------------------------------------------
# Default fallback — must match legacy r.get("WinCredits", 0) bit-for-bit
# ---------------------------------------------------------------------


class TestExtractRoundWinDefault:
    def test_no_rules_returns_wincredits(self):
        r = {"WinCredits": 1234, "SpinType": 1, "CostCredits": 1000}
        assert extract_round_win(r) == 1234.0
        assert extract_round_win(r, rules=None) == 1234.0
        assert extract_round_win(r, rules=[]) == 1234.0

    def test_no_rules_missing_wincredits_returns_zero(self):
        r = {"SpinType": 15, "WinAmount": 60000}
        assert extract_round_win(r) == 0.0  # legacy behavior

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


# ---------------------------------------------------------------------
# SettlementWinAmountRule — TopDollar selector machines
# ---------------------------------------------------------------------


class TestSettlementWinAmountRule:
    def _rule(self) -> SettlementWinAmountRule:
        return SettlementWinAmountRule(
            phantom_spin_types=[14],
            settlement_spin_types=[15],
        )

    def test_paid_round_passthrough(self):
        """Paid rounds (CostCredits>0) must return None — rule never
        touches them, even if SpinType matches a configured group."""
        rule = self._rule()
        r = {"SpinType": 1, "CostCredits": 1000, "WinCredits": 400}
        assert rule.extract(r) is None

    def test_paid_round_with_phantom_st_passthrough(self):
        """Defensive: even if a paid round somehow has SpinType=14,
        leave it alone — paid WinCredits is always truth."""
        rule = self._rule()
        r = {"SpinType": 14, "CostCredits": 1000, "WinCredits": 9999}
        assert rule.extract(r) is None

    def test_phantom_offer_returns_zero(self):
        """ST=14 selector offer round: phantom WinCredits → 0."""
        rule = self._rule()
        r = {"SpinType": 14, "CostCredits": 0, "WinCredits": 30000}
        assert rule.extract(r) == 0.0

    def test_phantom_offer_costcredits_none_returns_zero(self):
        rule = self._rule()
        r = {"SpinType": 14, "CostCredits": None, "WinCredits": 30000}
        assert rule.extract(r) == 0.0

    def test_settlement_returns_winamount(self):
        """ST=15 settlement round: WinAmount is the real payout."""
        rule = self._rule()
        r = {"SpinType": 15, "CostCredits": 0, "WinAmount": 60000}
        assert rule.extract(r) == 60000.0

    def test_settlement_missing_winamount_returns_zero(self):
        rule = self._rule()
        r = {"SpinType": 15, "CostCredits": 0}
        assert rule.extract(r) == 0.0

    def test_settlement_none_winamount_returns_zero(self):
        rule = self._rule()
        r = {"SpinType": 15, "CostCredits": 0, "WinAmount": None}
        assert rule.extract(r) == 0.0

    def test_unconfigured_spin_type_returns_none(self):
        """ST=99 not in any list → rule has no opinion → None →
        default fallback to WinCredits at the caller."""
        rule = self._rule()
        r = {"SpinType": 99, "CostCredits": 0, "WinCredits": 100}
        assert rule.extract(r) is None

    def test_missing_spin_type_returns_none(self):
        rule = self._rule()
        r = {"CostCredits": 0, "WinCredits": 100}
        assert rule.extract(r) is None

    def test_string_spin_type_coerced(self):
        """Real rawdata occasionally serializes SpinType as string."""
        rule = self._rule()
        r = {"SpinType": "14", "CostCredits": 0, "WinCredits": 30000}
        assert rule.extract(r) == 0.0

    def test_non_numeric_spin_type_returns_none(self):
        rule = self._rule()
        r = {"SpinType": "weird", "CostCredits": 0, "WinCredits": 100}
        assert rule.extract(r) is None

    def test_non_dict_returns_none(self):
        rule = self._rule()
        assert rule.extract(None) is None
        assert rule.extract("not a dict") is None
        assert rule.extract(42) is None

    def test_multi_phantom_multi_settlement(self):
        """Multi-layer selector: ST=14 + ST=20 both phantom, ST=15
        settlement."""
        rule = SettlementWinAmountRule(
            phantom_spin_types=[14, 20], settlement_spin_types=[15],
        )
        assert rule.extract({"SpinType": 14, "CostCredits": 0, "WinCredits": 1000}) == 0.0
        assert rule.extract({"SpinType": 20, "CostCredits": 0, "WinCredits": 2000}) == 0.0
        assert rule.extract({"SpinType": 15, "CostCredits": 0, "WinAmount": 5000}) == 5000.0
        assert rule.extract({"SpinType": 99, "CostCredits": 0, "WinCredits": 100}) is None


# ---------------------------------------------------------------------
# extract_round_win — integration of rules + default fallthrough
# ---------------------------------------------------------------------


class TestExtractRoundWinWithRules:
    def test_rule_overrides_default(self):
        rule = SettlementWinAmountRule(
            phantom_spin_types=[14], settlement_spin_types=[15],
        )
        r_phantom = {"SpinType": 14, "CostCredits": 0, "WinCredits": 30000}
        r_settle = {"SpinType": 15, "CostCredits": 0, "WinAmount": 60000}
        assert extract_round_win(r_phantom, rules=[rule]) == 0.0
        assert extract_round_win(r_settle, rules=[rule]) == 60000.0

    def test_rule_falls_through_to_default(self):
        """Unconfigured SpinType → rule returns None → default
        WinCredits lookup is used."""
        rule = SettlementWinAmountRule(
            phantom_spin_types=[14], settlement_spin_types=[15],
        )
        r = {"SpinType": 1, "CostCredits": 1000, "WinCredits": 400}
        assert extract_round_win(r, rules=[rule]) == 400.0

    def test_first_matching_rule_wins(self):
        """When two rules match the same round, the first in the list
        takes precedence — operator orders rules in config to control
        layering."""
        class FixedRule(RoundWinRule):
            def __init__(self, value): self.value = value
            def extract(self, r, ctx=None): return self.value

        r = {"WinCredits": 999}
        assert extract_round_win(r, rules=[FixedRule(100), FixedRule(200)]) == 100.0

    def test_first_rule_passes_second_handles(self):
        class NeverRule(RoundWinRule):
            def extract(self, r, ctx=None): return None

        rule = SettlementWinAmountRule(
            phantom_spin_types=[14], settlement_spin_types=[15],
        )
        r = {"SpinType": 14, "CostCredits": 0, "WinCredits": 30000}
        # NeverRule passes → SettlementWinAmountRule fires.
        assert extract_round_win(r, rules=[NeverRule(), rule]) == 0.0


# ---------------------------------------------------------------------
# load_rules_for_machine — config → rule list
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
            },
        }

    def test_machine_in_applies_to_gets_rule(self):
        rules = load_rules_for_machine("M12$TopDollarSelector$0$", self._config())
        assert len(rules) == 1
        assert isinstance(rules[0], SettlementWinAmountRule)
        assert rules[0].phantom_st == frozenset([14])
        assert rules[0].settlement_st == frozenset([15])

    def test_machine_not_in_applies_to_returns_empty(self):
        rules = load_rules_for_machine("M14", self._config())
        assert rules == []

    def test_none_config_returns_empty(self):
        assert load_rules_for_machine("M12$TopDollarSelector$0$", None) == []

    def test_empty_config_returns_empty(self):
        assert load_rules_for_machine("M12$TopDollarSelector$0$", {}) == []

    def test_missing_rules_key_returns_empty(self):
        assert load_rules_for_machine("M12", {"other_key": 1}) == []

    def test_unknown_rule_type_skipped(self):
        cfg = {"rules": {"r1": {
            "type": "totally_unknown_type",
            "params": {},
            "applies_to": ["M12"],
        }}}
        # Doesn't crash; just produces no rules.
        assert load_rules_for_machine("M12", cfg) == []

    def test_bad_params_skipped(self):
        cfg = {"rules": {"r1": {
            "type": "settlement_winamount",
            "params": {"unknown_kwarg": "x"},
            "applies_to": ["M12"],
        }}}
        assert load_rules_for_machine("M12", cfg) == []

    def test_non_dict_spec_skipped(self):
        cfg = {"rules": {"r1": "not a dict"}}
        assert load_rules_for_machine("M12", cfg) == []

    def test_multiple_matching_rules_appended_in_order(self):
        cfg = {"rules": {
            "first": {
                "type": "settlement_winamount",
                "params": {"phantom_spin_types": [14], "settlement_spin_types": [15]},
                "applies_to": ["M12"],
            },
            "second": {
                "type": "settlement_winamount",
                "params": {"phantom_spin_types": [20], "settlement_spin_types": [21]},
                "applies_to": ["M12"],
            },
        }}
        rules = load_rules_for_machine("M12", cfg)
        assert len(rules) == 2
        assert rules[0].phantom_st == frozenset([14])
        assert rules[1].phantom_st == frozenset([20])


# ---------------------------------------------------------------------
# Registry self-check
# ---------------------------------------------------------------------


def test_registry_has_settlement_winamount():
    assert "settlement_winamount" in RULE_REGISTRY
    assert RULE_REGISTRY["settlement_winamount"] is SettlementWinAmountRule
