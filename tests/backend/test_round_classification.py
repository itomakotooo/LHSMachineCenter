"""Unit tests for fresh_slotlab.round_classification.

Coverage:
  * is_paid_round / get_collect_count (existing semantics)
  * is_wild_nudge_round (Bug 3 detection)
  * extract_authoritative_pay_ids
  * parse_payline_records
  * attribute_lines_to_pay_ids (Bug 1 -- direct, suffix, single-remaining)
  * detect_cycle_peak / infer_bcm_target_spin_type (Bug 2)
"""
from __future__ import annotations

from fresh_slotlab.round_classification import (
    PAYLINE_RE,
    at_cycle_peak_indices,
    attribute_lines_to_pay_ids,
    detect_cycle_peak,
    extract_authoritative_pay_ids,
    get_collect_count,
    infer_bcm_target_spin_type,
    is_paid_round,
    is_wild_nudge_round,
    parse_payline_records,
)


# ---------------------------------------------------------------------
# is_paid_round / get_collect_count
# ---------------------------------------------------------------------


class TestIsPaidRound:
    def test_cost_positive(self):
        assert is_paid_round({"CostCredits": 1000}) is True

    def test_cost_zero(self):
        assert is_paid_round({"CostCredits": 0}) is False

    def test_cost_none(self):
        assert is_paid_round({"CostCredits": None}) is False

    def test_missing(self):
        assert is_paid_round({}) is False

    def test_non_dict(self):
        assert is_paid_round(None) is False
        assert is_paid_round("nope") is False

    def test_string_cost(self):
        assert is_paid_round({"CostCredits": "1000"}) is True
        assert is_paid_round({"CostCredits": "bad"}) is False


class TestGetCollectCount:
    def test_normal(self):
        assert get_collect_count({"CollectCount": 500}) == 500

    def test_string(self):
        assert get_collect_count({"CollectCount": "750"}) == 750

    def test_zero(self):
        assert get_collect_count({"CollectCount": 0}) == 0

    def test_missing(self):
        assert get_collect_count({}) is None

    def test_none(self):
        assert get_collect_count({"CollectCount": None}) is None

    def test_bad(self):
        assert get_collect_count({"CollectCount": "abc"}) is None

    def test_non_dict(self):
        assert get_collect_count(None) is None


# ---------------------------------------------------------------------
# is_wild_nudge_round
# ---------------------------------------------------------------------


class TestIsWildNudgeRound:
    def test_m279_canonical_move(self):
        """M279 ST=36 wild nudge: cost=0, ReMarks='move'."""
        r = {"SpinType": 36, "CostCredits": 0, "WinCredits": 2220,
             "ReMarks": "move"}
        assert is_wild_nudge_round(r) is True

    def test_uppercase_move(self):
        r = {"CostCredits": 0, "ReMarks": "Move"}
        assert is_wild_nudge_round(r) is True

    def test_nudge_word(self):
        # Word boundary required -- 'nudge' as standalone token.
        r = {"CostCredits": 0, "ReMarks": "nudge"}
        assert is_wild_nudge_round(r) is True

    def test_compound_word_not_matched(self):
        """Defensive: 'WildNudge' (no whitespace boundary inside) does
        NOT match -- avoids false-positive on machine names that
        happen to contain the keyword as a fragment. Real data uses
        the standalone 'move' / 'nudge' tokens (verified across
        M279/M226/M149/M140/M26/M51/M256 in fleet investigation)."""
        r = {"CostCredits": 0, "ReMarks": "WildNudge"}
        assert is_wild_nudge_round(r) is False

    def test_paid_round_with_move_remark_not_nudge(self):
        """Defensive: even if ReMarks somehow contains 'move' on a
        paid round (CostCredits>0), it's NOT a wild-nudge -- nudge
        is by definition cost-free."""
        r = {"CostCredits": 1000, "ReMarks": "move"}
        assert is_wild_nudge_round(r) is False

    def test_cost_none_treated_as_no_cost(self):
        r = {"CostCredits": None, "ReMarks": "move"}
        assert is_wild_nudge_round(r) is True

    def test_remark_without_keyword(self):
        r = {"CostCredits": 0, "ReMarks": "FreeSpin"}
        assert is_wild_nudge_round(r) is False

    def test_empty_remark(self):
        r = {"CostCredits": 0, "ReMarks": ""}
        assert is_wild_nudge_round(r) is False

    def test_no_remark_field(self):
        r = {"CostCredits": 0}
        assert is_wild_nudge_round(r) is False

    def test_word_boundary_required(self):
        """'movement' shouldn't match -- only standalone 'move' word."""
        r = {"CostCredits": 0, "ReMarks": "movement_classifier"}
        assert is_wild_nudge_round(r) is False

    def test_non_dict(self):
        assert is_wild_nudge_round(None) is False
        assert is_wild_nudge_round("move") is False


# ---------------------------------------------------------------------
# extract_authoritative_pay_ids
# ---------------------------------------------------------------------


class TestExtractAuthoritativePayIds:
    def test_normal(self):
        r = {"PayoutIdToWinAmount": {"6": 1110}}
        assert extract_authoritative_pay_ids(r) == {"6": 1110.0}

    def test_multi_pay_id(self):
        r = {"PayoutIdToWinAmount": {"104": 15000, "3": 19980, "5": 3330}}
        assert extract_authoritative_pay_ids(r) == {
            "104": 15000.0, "3": 19980.0, "5": 3330.0,
        }

    def test_int_keys_coerced_to_str(self):
        r = {"PayoutIdToWinAmount": {6: 1110}}
        assert extract_authoritative_pay_ids(r) == {"6": 1110.0}

    def test_missing(self):
        assert extract_authoritative_pay_ids({}) == {}

    def test_none(self):
        assert extract_authoritative_pay_ids({"PayoutIdToWinAmount": None}) == {}

    def test_non_dict_payout(self):
        assert extract_authoritative_pay_ids({"PayoutIdToWinAmount": "weird"}) == {}

    def test_non_dict_input(self):
        assert extract_authoritative_pay_ids(None) == {}


# ---------------------------------------------------------------------
# parse_payline_records
# ---------------------------------------------------------------------


class TestParsePaylineRecords:
    def test_single_line(self):
        out = parse_payline_records("3:6-6(100,199,300,)")
        assert out == [{
            "line_id": 3, "symbol_id": "6", "match_count": 3,
            "positions": [100, 199, 300],
        }]

    def test_multi_line(self):
        out = parse_payline_records(
            "2:5-5(99,199,299,);  5:27905-27905(101,200,299,);"
        )
        assert len(out) == 2
        assert out[0]["line_id"] == 2
        assert out[0]["symbol_id"] == "5"
        assert out[1]["line_id"] == 5
        assert out[1]["symbol_id"] == "27905"

    def test_negative_line_id(self):
        # M121 uses line_id=-1 for scatter pays.
        out = parse_payline_records("-1:12107-12107(99,)")
        assert out[0]["line_id"] == -1
        assert out[0]["symbol_id"] == "12107"

    def test_empty(self):
        assert parse_payline_records("") == []
        assert parse_payline_records(None) == []

    def test_garbage_skipped(self):
        out = parse_payline_records("garbage; 3:6-6(100,)")
        assert len(out) == 1
        assert out[0]["line_id"] == 3


# ---------------------------------------------------------------------
# attribute_lines_to_pay_ids
# ---------------------------------------------------------------------


class TestAttributeLinesToPayIds:
    def test_m14_direct_match(self):
        """M14 simple: symbol_id == pay_id ('8' direct)."""
        r = {
            "PayoutByPayline": "2:8-8(199,)",
            "PayoutIdToWinAmount": {"8": 400},
        }
        result = attribute_lines_to_pay_ids(r)
        assert len(result) == 1
        assert result[0]["pay_id"] == "8"
        assert result[0]["symbol_id"] == "8"
        assert result[0]["line_id"] == 2

    def test_m120_suffix_match(self):
        """M120: symbol '109' suffix matches pay_id '9'."""
        r = {
            "PayoutByPayline": "3:109-109(100,200,300,)",
            "PayoutIdToWinAmount": {"9": 1110},
        }
        result = attribute_lines_to_pay_ids(r)
        assert result[0]["pay_id"] == "9"
        assert result[0]["symbol_id"] == "109"

    def test_m139_suffix_match(self):
        """M139: symbol '55' suffix matches pay_id '5'."""
        r = {
            "PayoutByPayline": "5:55-55(100,200,300,)",
            "PayoutIdToWinAmount": {"5": 500},
        }
        result = attribute_lines_to_pay_ids(r)
        assert result[0]["pay_id"] == "5"

    def test_m279_jackpot_single_remaining(self):
        """M279 jackpot symbol '27905' doesn't match by direct or
        suffix on '104'. But '104' is the only unaccounted pay_id
        once direct matches consume '5', '3' -> single-remaining
        rule attributes line 5 to pay_id '104'."""
        r = {
            "PayoutByPayline": (
                "2:5-5(99,199,299,);  3:3-3(101,201,301,);  "
                "5:27905-27905(101,200,299,);  8:3-3(101,200,301,);  "
                "9:5-5(99,200,299,);"
            ),
            "PayoutIdToWinAmount": {"104": 15000, "3": 19980, "5": 3330},
        }
        result = attribute_lines_to_pay_ids(r)
        # Lines 2 & 9 (symbol 5) -> pay_id 5
        # Lines 3 & 8 (symbol 3) -> pay_id 3
        # Line 5 (symbol 27905) -> pay_id 104 (single remaining)
        line_to_pid = {L["line_id"]: L["pay_id"] for L in result}
        assert line_to_pid == {2: "5", 9: "5", 3: "3", 8: "3", 5: "104"}

    def test_mixed_direct_and_single_remaining(self):
        r = {
            "PayoutByPayline": "1:8-8(99,);  2:99-99(199,)",
            "PayoutIdToWinAmount": {"8": 100, "9": 200},
        }
        result = attribute_lines_to_pay_ids(r)
        line_to_pid = {L["line_id"]: L["pay_id"] for L in result}
        # '8' direct, '99' suffix matches '9'.
        assert line_to_pid == {1: "8", 2: "9"}

    def test_no_pay_ids_no_attribution(self):
        r = {
            "PayoutByPayline": "3:6-6(100,)",
            "PayoutIdToWinAmount": {},
        }
        result = attribute_lines_to_pay_ids(r)
        assert result[0]["pay_id"] is None

    def test_empty_payline(self):
        r = {"PayoutByPayline": "", "PayoutIdToWinAmount": {"5": 100}}
        assert attribute_lines_to_pay_ids(r) == []

    def test_long_pay_id_not_shadowed_by_short(self):
        """If pay_ids are '4' and '104', symbol '27904' should match
        '4' (longest suffix match). Wait actually '27904' ends with
        '4' AND not with '104'. So pay_id '4' wins. But if symbol is
        '274104', it ends with both '4' and '104' -- '104' should win
        (longer suffix preferred)."""
        r = {
            "PayoutByPayline": "1:274104-274104(99,200,300,)",
            "PayoutIdToWinAmount": {"4": 100, "104": 15000},
        }
        result = attribute_lines_to_pay_ids(r)
        # '104' is longer suffix -- should win.
        assert result[0]["pay_id"] == "104"

    def test_unmatched_when_multiple_unaccounted(self):
        """If after direct + suffix passes, multiple lines remain
        with multiple unaccounted pay_ids, leave them None rather
        than guess."""
        r = {
            "PayoutByPayline": "1:abc-abc(99,);  2:xyz-xyz(199,)",
            "PayoutIdToWinAmount": {"5": 100, "9": 200},
        }
        result = attribute_lines_to_pay_ids(r)
        assert all(L["pay_id"] is None for L in result)

    def test_non_dict_input(self):
        assert attribute_lines_to_pay_ids(None) == []


# ---------------------------------------------------------------------
# BCM cycle peak / target inference
# ---------------------------------------------------------------------


class TestDetectCyclePeak:
    def test_full_cycle_reset_observed(self):
        """Cycle 1->1000 then reset to 1 -> peak detected as 1000."""
        rounds = [
            {"CollectCount": 1}, {"CollectCount": 500},
            {"CollectCount": 1000}, {"CollectCount": 1},
        ]
        assert detect_cycle_peak(rounds) == 1000

    def test_no_reset_returns_none(self):
        """2026-04-27 fix: cc walks 1->1000 monotonically without
        resetting (chunk too short to see a full cycle) -> peak is
        unknown, return None. Pre-fix max(cc)=1000 lied as peak,
        misfiring BCM target inference on M250/M256."""
        rounds = [
            {"CollectCount": 1}, {"CollectCount": 500},
            {"CollectCount": 1000},  # ends here, no reset back to small
        ]
        assert detect_cycle_peak(rounds) is None

    def test_no_cc_mechanic(self):
        rounds = [{"WinCredits": 100}, {"WinCredits": 0}]
        assert detect_cycle_peak(rounds) is None

    def test_partial_data_with_reset(self):
        # CC field appears intermittently; reset still detected.
        rounds = [
            {"CollectCount": 100},
            {"WinCredits": 50},
            {"CollectCount": 250},
            {"CollectCount": 1},  # reset 250 -> 1
        ]
        assert detect_cycle_peak(rounds) == 250

    def test_partial_data_no_reset_returns_none(self):
        rounds = [
            {"CollectCount": 100},
            {"WinCredits": 50},
            {"CollectCount": 250},
        ]
        assert detect_cycle_peak(rounds) is None

    def test_min_resets_threshold(self):
        """Caller can require >=N resets for stricter inference."""
        rounds = [
            {"CollectCount": 100}, {"CollectCount": 1},  # 1 reset
        ]
        assert detect_cycle_peak(rounds, min_resets=1) == 100
        assert detect_cycle_peak(rounds, min_resets=2) is None

    def test_multiple_resets_at_same_peak(self):
        """Real M279 pattern: cc cycles 1->1000->1->1000->1, peak=1000."""
        rounds = [
            {"CollectCount": 999}, {"CollectCount": 1000},
            {"CollectCount": 1},   # reset
            {"CollectCount": 999}, {"CollectCount": 1000},
            {"CollectCount": 1},   # reset
        ]
        assert detect_cycle_peak(rounds, min_resets=2) == 1000

    def test_noisy_drops_filtered(self):
        """A 1-step drop (cc=10 -> cc=9) shouldn't count as a reset."""
        rounds = [
            {"CollectCount": 9}, {"CollectCount": 10}, {"CollectCount": 9},
        ]
        assert detect_cycle_peak(rounds) is None

    def test_zero_only_returns_none(self):
        """All-zero CC means no real cycle activity."""
        rounds = [{"CollectCount": 0}, {"CollectCount": 0}]
        assert detect_cycle_peak(rounds) is None


class TestAtCyclePeakIndices:
    def test_finds_peak_paid_rounds(self):
        rounds = [
            {"CostCredits": 1000, "CollectCount": 500},
            {"CostCredits": 1000, "CollectCount": 1000},  # peak
            {"CostCredits": 0, "CollectCount": None},      # bonus
            {"CostCredits": 1000, "CollectCount": 1},
            {"CostCredits": 1000, "CollectCount": 1000},  # peak
        ]
        assert at_cycle_peak_indices(rounds, 1000) == [1, 4]

    def test_skips_non_paid_at_peak(self):
        # CC=1000 on a non-paid round shouldn't count -- it's already
        # a bonus round.
        rounds = [
            {"CostCredits": 0, "CollectCount": 1000},  # not paid
            {"CostCredits": 1000, "CollectCount": 1000},  # paid at peak
        ]
        assert at_cycle_peak_indices(rounds, 1000) == [1]


class TestInferBcmTargetSpinType:
    def test_m250_no_cycle_returns_none(self):
        """M250/M256 pattern: cc walks 1 -> 1000 monotonically without
        ever resetting in the sampled chunk window. Pre-2026-04-27 logic
        used max(cc) and observed "what fires after cc=1000" -- the
        few NewFreespin events at cc=1000 (1.3% trigger rate) were
        noise, not a deterministic cycle target. Now: detect_cycle_peak
        returns None when no reset is observed -> infer_bcm_target_spin_type
        returns (None, 0) and BCM inference falls through to legacy
        max-feature heuristic with low confidence."""
        rounds = []
        for cc_val in range(1, 1001):
            rounds.append({
                "CostCredits": 1000, "WinCredits": 100,
                "CollectCount": cc_val, "SpinType": 140,
            })
        # No reset back to small cc -> no cycle inferable.
        st, count = infer_bcm_target_spin_type(rounds)
        assert st is None
        assert count == 0

    def test_m279_wheel(self):
        """M279: paid round at cc=1000 followed by ST=2 wheel
        (deterministic: 100% of cycle completions trigger Wheel)."""
        rounds = [
            {"CostCredits": 1000, "CollectCount": 999, "SpinType": 140},
            {"CostCredits": 1000, "CollectCount": 1000, "SpinType": 140},
            {"CostCredits": None, "CollectCount": None, "SpinType": 2,
             "ReMarks": "WheelSpin CellIndex 3"},
            {"CostCredits": 1000, "CollectCount": 1, "SpinType": 140},
            {"CostCredits": 1000, "CollectCount": 1000, "SpinType": 140},
            {"CostCredits": None, "CollectCount": None, "SpinType": 2,
             "ReMarks": "WheelSpin CellIndex 1"},
        ]
        st, count = infer_bcm_target_spin_type(rounds, cycle_peak=1000)
        assert st == 2
        assert count == 2

    def test_immediate_next_only(self):
        """When cc=peak paid is followed by multiple non-paid rounds,
        we count ONLY the immediate-next one. Avoids miscounting
        transient nudge -> wheel sequences."""
        rounds = [
            {"CostCredits": 1000, "CollectCount": 1000, "SpinType": 140},
            {"CostCredits": 0, "SpinType": 2, "ReMarks": "WheelSpin"},
            {"CostCredits": 0, "SpinType": 36, "ReMarks": "move"},  # ignored
        ]
        st, count = infer_bcm_target_spin_type(rounds, cycle_peak=1000)
        assert st == 2
        assert count == 1

    def test_no_cycle_peak_no_inference(self):
        rounds = [{"CostCredits": 1000, "WinCredits": 100}]
        st, count = infer_bcm_target_spin_type(rounds)
        assert st is None
        assert count == 0

    def test_wins_over_max_feature_heuristic(self):
        """Counter-example: many MoveSpin nudge rounds (high freq)
        between paid rounds. Cycle-peak inference still picks the
        Wheel that fires AT cc=peak, not the dominant feature."""
        rounds = [
            # Lots of paid + nudge in mid-cycle
            {"CostCredits": 1000, "CollectCount": 100, "SpinType": 140},
            {"CostCredits": 0, "SpinType": 36, "ReMarks": "move"},
            {"CostCredits": 1000, "CollectCount": 200, "SpinType": 140},
            {"CostCredits": 0, "SpinType": 36, "ReMarks": "move"},
            # Peak round
            {"CostCredits": 1000, "CollectCount": 1000, "SpinType": 140},
            {"CostCredits": None, "SpinType": 2, "ReMarks": "WheelSpin"},
        ]
        st, count = infer_bcm_target_spin_type(rounds, cycle_peak=1000)
        assert st == 2  # Wheel, not MoveSpin
        assert count == 1
