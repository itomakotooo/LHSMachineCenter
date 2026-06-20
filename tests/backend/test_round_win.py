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
    BCMCycleAnchorRule,
    RoundWinRule,
    SettlementWinAmountRule,
    SynthesizePayIdRule,
    WinResidualRule,
    extract_round_payouts,
    extract_round_trigger_anchor,
    extract_round_win,
    extract_trigger_pay_ids_default,
    is_paid_round,
    load_rules_for_machine,
    round_has_credited_win,
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
# WinResidualRule -- collect-coin attribution (keep payline pids, add
# residual WinCredits - sum(payid) to a collect pid). Real-rawdata
# anchors: M24 ST46 (PigCredits), M262 ST140, M125 ST138, M254 ST154.
# ---------------------------------------------------------------------


class TestWinResidualRule:
    def _rule(self) -> WinResidualRule:
        return WinResidualRule(spin_types=[46])

    def test_keeps_payline_pids_and_adds_residual(self):
        """M24 ST46 residual round: paylines {30:10000,...} sum=10650,
        WinCredits=15650 -> keep paylines, add st46_collect:5000."""
        rule = self._rule()
        r = {"SpinType": 46, "CostCredits": 0, "WinCredits": 15650,
             "PayoutIdToWinAmount": {"30": 10000, "32": 100, "31": 500, "36": 50}}
        result = rule.extract_payouts(r)
        assert result == {"30": 10000.0, "32": 100.0, "31": 500.0,
                          "36": 50.0, "st46_collect": 5000.0}
        # Total credited == WinCredits (closes sum(payid)==chunk_win).
        assert abs(sum(result.values()) - 15650.0) < 1e-9

    def test_bare_win_round_whole_win_is_residual(self):
        """Bare-win ST46 (pid empty) -> the whole WinCredits is the
        collect residual: {st46_collect: WinCredits}. Subsumes the
        SynthesizePayIdRule spin_type bare case."""
        rule = self._rule()
        r = {"SpinType": 46, "CostCredits": 0, "WinCredits": 63000,
             "PayoutIdToWinAmount": {}}
        assert rule.extract_payouts(r) == {"st46_collect": 63000.0}

    def test_pure_payline_round_passes_through(self):
        """WinCredits == sum(payline pids) -> residual <= tol -> None
        (caller uses the round's own pids, no synthetic collect row)."""
        rule = self._rule()
        r = {"SpinType": 46, "CostCredits": 0, "WinCredits": 10650,
             "PayoutIdToWinAmount": {"30": 10000, "32": 100, "31": 500, "36": 50}}
        assert rule.extract_payouts(r) is None

    def test_trigger_token_pid_preserved_residual_is_full_win(self):
        """A value-0 trigger token contributes 0 to the payline sum, so
        residual == full WinCredits; the token is preserved."""
        rule = self._rule()
        r = {"SpinType": 46, "CostCredits": 0, "WinCredits": 10500,
             "PayoutIdToWinAmount": {"666": 0}}
        result = rule.extract_payouts(r)
        assert result == {"666": 0.0, "st46_collect": 10500.0}

    def test_zero_win_no_attribution(self):
        rule = self._rule()
        r = {"SpinType": 46, "CostCredits": 0, "WinCredits": 0,
             "PayoutIdToWinAmount": {}}
        assert rule.extract_payouts(r) is None

    def test_unconfigured_spin_type_no_opinion(self):
        rule = self._rule()
        r = {"SpinType": 45, "CostCredits": 1000, "WinCredits": 12000,
             "PayoutIdToWinAmount": {"6": 5000}}
        assert rule.extract_payouts(r) is None

    def test_over_attributed_round_passes_through(self):
        """If sum(pid) > WinCredits (residual negative) -> None, never
        a negative collect row."""
        rule = self._rule()
        r = {"SpinType": 46, "CostCredits": 0, "WinCredits": 5000,
             "PayoutIdToWinAmount": {"6": 8000}}
        assert rule.extract_payouts(r) is None

    def test_spin_type_label_format(self):
        rule = WinResidualRule(spin_types=[46], label_format="spin_type")
        r = {"SpinType": 46, "CostCredits": 0, "WinCredits": 63000,
             "PayoutIdToWinAmount": {}}
        assert rule.extract_payouts(r) == {"st46": 63000.0}

    def test_extract_win_is_passthrough(self):
        """Residual rule only re-attributes pids -- chunk_win stays
        WinCredits (RTP unchanged)."""
        rule = self._rule()
        r = {"SpinType": 46, "WinCredits": 15650}
        assert rule.extract_win(r) is None

    def test_string_spin_type_coerced(self):
        rule = self._rule()
        r = {"SpinType": "46", "WinCredits": 10500, "PayoutIdToWinAmount": {}}
        assert rule.extract_payouts(r) == {"st46_collect": 10500.0}

    def test_non_dict_input_no_opinion(self):
        rule = self._rule()
        assert rule.extract_payouts(None) is None
        assert rule.extract_payouts(42) is None

    def test_invalid_label_format_raises(self):
        with pytest.raises(ValueError, match="label_format"):
            WinResidualRule(spin_types=[46], label_format="multiplier")

    def test_collect_label_is_not_a_fallback_bucket(self):
        """The minted label must NOT start with a reserved fallback
        prefix (_unattributed_/_other/_default/_misc) or the
        rtp-integrity Layer-2 gate would flag it."""
        rule = self._rule()
        r = {"SpinType": 46, "WinCredits": 10500, "PayoutIdToWinAmount": {}}
        (label,) = rule.extract_payouts(r).keys()
        assert not label.startswith(("_unattributed_", "_other", "_default", "_misc"))


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
    assert "win_residual" in RULE_REGISTRY
    assert "bcm_cycle_anchor" in RULE_REGISTRY
    assert RULE_REGISTRY["settlement_winamount"] is SettlementWinAmountRule
    assert RULE_REGISTRY["synthesize_pay_id"] is SynthesizePayIdRule
    assert RULE_REGISTRY["win_residual"] is WinResidualRule
    assert RULE_REGISTRY["bcm_cycle_anchor"] is BCMCycleAnchorRule


def test_load_win_residual_rule_from_config():
    config = {
        "rules": {
            "m24_freespin_collect": {
                "type": "win_residual",
                "params": {"spin_types": [46], "label_format": "spin_type_collect"},
                "applies_to": ["M24"],
            }
        }
    }
    rules = load_rules_for_machine("M24", config)
    assert len(rules) == 1
    assert isinstance(rules[0], WinResidualRule)
    # Not applied to a machine outside applies_to.
    assert load_rules_for_machine("M99", config) == []


# ---------------------------------------------------------------------
# is_paid_round predicate
# ---------------------------------------------------------------------


class TestIsPaidRound:
    def test_positive_cost_is_paid(self):
        assert is_paid_round({"CostCredits": 1000}) is True

    def test_zero_cost_not_paid(self):
        assert is_paid_round({"CostCredits": 0}) is False

    def test_none_cost_not_paid(self):
        assert is_paid_round({"CostCredits": None}) is False
        assert is_paid_round({}) is False

    def test_non_numeric_cost_not_paid(self):
        assert is_paid_round({"CostCredits": "abc"}) is False

    def test_non_dict_input_not_paid(self):
        assert is_paid_round(None) is False
        assert is_paid_round([]) is False
        assert is_paid_round("paid") is False


# ---------------------------------------------------------------------
# extract_trigger_pay_ids_default
# ---------------------------------------------------------------------


class TestExtractTriggerPayIdsDefault:
    def test_returns_win_zero_keys_sorted(self):
        # M15-style trigger: pid 9 (cherry, real win) + pid 666 (trigger token)
        pid = {"9": 1000, "666": 0}
        assert extract_trigger_pay_ids_default(pid) == ["666"]

    def test_multiple_zero_keys_sorted(self):
        pid = {"5801": 0, "666": 0, "9": 1000}
        assert extract_trigger_pay_ids_default(pid) == ["5801", "666"]

    def test_empty_dict_returns_empty(self):
        assert extract_trigger_pay_ids_default({}) == []

    def test_non_dict_returns_empty(self):
        assert extract_trigger_pay_ids_default(None) == []
        assert extract_trigger_pay_ids_default("x") == []

    def test_none_values_treated_as_zero(self):
        assert extract_trigger_pay_ids_default({"5801": None}) == ["5801"]


# ---------------------------------------------------------------------
# extract_round_trigger_anchor dispatcher
# ---------------------------------------------------------------------


class TestExtractRoundTriggerAnchor:
    def test_no_rules_matches_default(self):
        r = {"CostCredits": 1000, "PayoutIdToWinAmount": {"5801": 0, "1": 5000}}
        assert extract_round_trigger_anchor(r) == ["5801"]

    def test_rule_augments_default(self):
        r = {"CostCredits": 1000, "CollectCount": 1000,
             "PayoutIdToWinAmount": {"5801": 0}}
        rule = BCMCycleAnchorRule()
        # Default extracts '5801'; rule contributes '_bcm_cycle'; merged
        result = extract_round_trigger_anchor(r, rules=[rule],
                                              ctx={"cycle_peak": 1000})
        assert result == sorted(["5801", "_bcm_cycle"])

    def test_rule_only_when_default_empty(self):
        r = {"CostCredits": 1000, "CollectCount": 1000,
             "PayoutIdToWinAmount": {}}
        rule = BCMCycleAnchorRule()
        result = extract_round_trigger_anchor(r, rules=[rule],
                                              ctx={"cycle_peak": 1000})
        assert result == ["_bcm_cycle"]

    def test_no_dupes_when_rule_returns_existing_anchor(self):
        r = {"CostCredits": 1000, "CollectCount": 1000,
             "PayoutIdToWinAmount": {"_bcm_cycle": 0}}

        class _Echo(RoundWinRule):
            def extract_trigger_anchor(self, rd, ctx=None):
                return ["_bcm_cycle"]

        result = extract_round_trigger_anchor(r, rules=[_Echo()])
        assert result == ["_bcm_cycle"]  # de-duped

    def test_non_dict_returns_empty(self):
        assert extract_round_trigger_anchor(None) == []


# ---------------------------------------------------------------------
# round_has_credited_win predicate
# ---------------------------------------------------------------------


class TestRoundHasCreditedWin:
    def test_nonzero_pid_value_counts(self):
        assert round_has_credited_win({"PayoutIdToWinAmount": {"1": 5000}}) is True

    def test_all_zero_pid_values_not_credited(self):
        assert round_has_credited_win({"PayoutIdToWinAmount": {"666": 0}}) is False

    def test_empty_dict_not_credited(self):
        assert round_has_credited_win({"PayoutIdToWinAmount": {}}) is False

    def test_none_payout_not_credited(self):
        # M15 selector offer carries Payout=None; session_win should
        # still own the offer attribution -- this is "not credited".
        assert round_has_credited_win({"PayoutIdToWinAmount": None}) is False

    def test_rule_supplied_payouts_counted(self):
        """A rule synthesizing {'st2': 60000} means the round-level
        aggregator credits 'st2' -- ``round_has_credited_win`` must
        observe this and report True so trigger_sessions excludes the
        round from session_win accumulation."""
        r = {"CostCredits": 0, "WinCredits": 60000, "SpinType": 2,
             "BetAmount": 1000, "PayoutIdToWinAmount": {}}

        class _Synth(RoundWinRule):
            def extract_payouts(self, rd, ctx=None):
                return {"st2": 60000}

        assert round_has_credited_win(r, rules=[_Synth()]) is True

    def test_settlement_rule_empty_dict_not_credited(self):
        """SettlementWinAmountRule returns {} on phantom/settlement
        rounds -- this is explicit "no round-level credit, delegate
        to session_win". Must NOT count as credited."""
        r = {"CostCredits": 0, "WinCredits": 0, "SpinType": 15,
             "WinAmount": 80000, "PayoutIdToWinAmount": None}

        class _Empty(RoundWinRule):
            def extract_payouts(self, rd, ctx=None):
                return {}

        assert round_has_credited_win(r, rules=[_Empty()]) is False


# ---------------------------------------------------------------------
# BCMCycleAnchorRule
# ---------------------------------------------------------------------


class TestBCMCycleAnchorRule:
    def test_fires_at_cycle_peak(self):
        rule = BCMCycleAnchorRule()
        r = {"CostCredits": 1000, "CollectCount": 1000,
             "PayoutIdToWinAmount": {}}
        assert rule.extract_trigger_anchor(r, {"cycle_peak": 1000}) == ["_bcm_cycle"]

    def test_does_not_fire_below_peak(self):
        rule = BCMCycleAnchorRule()
        r = {"CostCredits": 1000, "CollectCount": 999,
             "PayoutIdToWinAmount": {}}
        assert rule.extract_trigger_anchor(r, {"cycle_peak": 1000}) is None

    def test_does_not_fire_on_bonus_round(self):
        """Bonus rounds (cost=0) never carry CollectCount and should
        never be classified as trigger anchors. Defensive check."""
        rule = BCMCycleAnchorRule()
        r = {"CostCredits": 0, "CollectCount": 1000,
             "PayoutIdToWinAmount": {}}
        assert rule.extract_trigger_anchor(r, {"cycle_peak": 1000}) is None

    def test_no_ctx_no_fire(self):
        rule = BCMCycleAnchorRule()
        r = {"CostCredits": 1000, "CollectCount": 1000}
        assert rule.extract_trigger_anchor(r, None) is None
        assert rule.extract_trigger_anchor(r, {}) is None

    def test_none_peak_no_fire(self):
        """``detect_cycle_peak`` returns None when the chunk is too
        short to observe a reset; rule must pass through silently."""
        rule = BCMCycleAnchorRule()
        r = {"CostCredits": 1000, "CollectCount": 1000}
        assert rule.extract_trigger_anchor(r, {"cycle_peak": None}) is None

    def test_non_numeric_cycle_field_no_fire(self):
        rule = BCMCycleAnchorRule()
        r = {"CostCredits": 1000, "CollectCount": "bogus"}
        assert rule.extract_trigger_anchor(r, {"cycle_peak": 1000}) is None

    def test_custom_anchor_pid(self):
        rule = BCMCycleAnchorRule(anchor_pid="mycycle")
        r = {"CostCredits": 1000, "CollectCount": 500}
        assert rule.extract_trigger_anchor(r, {"cycle_peak": 500}) == ["mycycle"]

    def test_custom_cycle_field(self):
        rule = BCMCycleAnchorRule(cycle_field="MyCounter")
        r = {"CostCredits": 1000, "MyCounter": 50}
        assert rule.extract_trigger_anchor(r, {"cycle_peak": 50}) == ["_bcm_cycle"]

    def test_extract_win_payouts_passthrough(self):
        """Rule only contributes trigger anchors -- it must NOT
        override extract_win or extract_payouts (those keep their
        default behaviour)."""
        rule = BCMCycleAnchorRule()
        r = {"CostCredits": 1000, "CollectCount": 1000, "WinCredits": 0,
             "PayoutIdToWinAmount": {"5": 1234}}
        assert rule.extract_win(r) is None
        assert rule.extract_payouts(r) is None

    def test_invalid_peak_no_fire(self):
        rule = BCMCycleAnchorRule()
        r = {"CostCredits": 1000, "CollectCount": 1000}
        assert rule.extract_trigger_anchor(r, {"cycle_peak": -1}) is None
        assert rule.extract_trigger_anchor(r, {"cycle_peak": "bogus"}) is None

    def test_non_dict_round_no_fire(self):
        rule = BCMCycleAnchorRule()
        assert rule.extract_trigger_anchor(None, {"cycle_peak": 1000}) is None
        assert rule.extract_trigger_anchor([], {"cycle_peak": 1000}) is None

    def test_load_from_config(self):
        cfg = {"rules": {"bcm_m274": {
            "type": "bcm_cycle_anchor",
            "params": {"anchor_pid": "_bcm_cycle", "cycle_field": "CollectCount"},
            "applies_to": ["M274"],
        }}}
        rules = load_rules_for_machine("M274", cfg)
        assert len(rules) == 1
        assert isinstance(rules[0], BCMCycleAnchorRule)
        assert rules[0].anchor_pid == "_bcm_cycle"
        assert rules[0].cycle_field == "CollectCount"

    def test_other_machine_no_rule(self):
        cfg = {"rules": {"bcm_m274": {
            "type": "bcm_cycle_anchor",
            "params": {},
            "applies_to": ["M274"],
        }}}
        assert load_rules_for_machine("M275", cfg) == []
