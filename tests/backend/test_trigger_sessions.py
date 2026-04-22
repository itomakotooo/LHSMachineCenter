"""Tests for the trigger session detector.

The detector solves the pay_id-666-can't-see-its-win bug: trigger
tokens carry zero win at round level, but the feature they activate
accrues real credits that only surface on the upstream FeatureWin
aggregate. These tests lock the mapping from round sequences to
session win so the analyzer can fold the value back onto the
trigger pay_id's RTP contribution.

The live cross-check (M15 full chunk scan, 2238 sessions totalling
105,665,000 credits = FeatureWin.TopDollar.total_win) is covered
by the analyzer's end-to-end pipeline test; the unit tests below
cover the pure-function contract:

  * Which ReMarks qualify as "new trigger" vs "re-trigger"
  * Which pay_ids in a trigger round count as the trigger anchor
  * Session boundary: start = trigger round, end = next round with
    same SpinType (back to paid), or end of rounds
  * session_win = last non-None WinCredits across the span
  * Malformed input (non-dict rounds / non-string ReMarks / empty
    PayoutIdToWinAmount) handled without raising
"""
from __future__ import annotations

from fresh_slotlab.trigger_sessions import (
    compute_trigger_sessions,
    extract_trigger_pay_ids,
    is_new_trigger_remark,
)


class TestIsNewTriggerRemark:
    def test_bare_trigger_matches(self):
        """M15 TopDollar family: ReMarks == 'Trigger' exactly."""
        assert is_new_trigger_remark("Trigger") is True

    def test_trigger_freespin_matches(self):
        """M6 Fortunes / M86 Hoppy / M39 Dancing: suffix variants."""
        assert is_new_trigger_remark("TriggerFreeSpin") is True

    def test_trigger_gold_bonus_semicolon_matches(self):
        """M116 Christmas: 'Trigger GoldBonus;' (space + semicolon)."""
        assert is_new_trigger_remark("Trigger GoldBonus;") is True

    def test_trigger_selector_matches(self):
        """M123 Valentine: 'Trigger Selector;'."""
        assert is_new_trigger_remark("Trigger Selector;") is True

    def test_trigger_add_freespin_rejected(self):
        """M39 re-trigger: extends existing session, NOT a new one.
        Treating it as new would double-count the feature win."""
        assert is_new_trigger_remark("TriggerAddFreeSpin") is False

    def test_leading_whitespace_tolerated(self):
        """Whitespace-padded ReMarks still trigger (upstream drift
        once shipped rogue trailing spaces)."""
        assert is_new_trigger_remark("  Trigger  ") is True

    def test_empty_string_rejected(self):
        assert is_new_trigger_remark("") is False

    def test_non_trigger_prefix_rejected(self):
        """'Freespin 1; CollectCount:3;' (M272 style) doesn't start
        with Trigger so it's not caught by iteration-1 detector."""
        assert is_new_trigger_remark("Freespin 1; CollectCount:3;") is False

    def test_non_string_rejected(self):
        """Defensive: None / int / list inputs don't raise."""
        assert is_new_trigger_remark(None) is False
        assert is_new_trigger_remark(42) is False  # type: ignore[arg-type]
        assert is_new_trigger_remark(["Trigger"]) is False  # type: ignore[arg-type]

    def test_case_sensitive(self):
        """ReMarks is case-sensitive per upstream; "trigger" (lower)
        isn't a valid signal. Guards against future "normalization"
        that'd break real-data match."""
        assert is_new_trigger_remark("trigger") is False
        assert is_new_trigger_remark("TRIGGER") is False


class TestExtractTriggerPayIds:
    def test_single_zero_win_pay_id(self):
        """M15 most common: {'666': 0}."""
        assert extract_trigger_pay_ids({"666": 0}) == ["666"]

    def test_coexisting_paying_pay_id_excluded(self):
        """M15 observed: trigger round with pay_id 666 (zero) + pay_id
        9 cherry (paying 1000). Only 666 is the trigger anchor."""
        assert extract_trigger_pay_ids({"666": 0, "9": 1000}) == ["666"]

    def test_multiple_zero_win_pay_ids_sorted(self):
        """If multiple pay_ids have zero win, return all sorted for
        deterministic session-win attribution downstream."""
        assert extract_trigger_pay_ids({"200": 0, "100": 0}) == ["100", "200"]

    def test_zero_and_nonzero_separated(self):
        """Mixed payouts — only zero-win ids count as triggers."""
        assert extract_trigger_pay_ids({"1": 500, "666": 0, "5": 100}) == ["666"]

    def test_string_zero_coerced(self):
        """Upstream sometimes returns stringified numbers."""
        assert extract_trigger_pay_ids({"666": "0"}) == ["666"]

    def test_non_numeric_win_defaults_to_zero(self):
        """Defensive: non-numeric win treated as zero, pay_id still
        counts as trigger. Safer than skipping and missing a real
        trigger anchor due to schema drift."""
        assert extract_trigger_pay_ids({"X": None}) == ["X"]

    def test_empty_input_returns_empty(self):
        assert extract_trigger_pay_ids({}) == []
        assert extract_trigger_pay_ids(None) == []  # type: ignore[arg-type]

    def test_non_dict_input_returns_empty(self):
        assert extract_trigger_pay_ids("not a dict") == []  # type: ignore[arg-type]
        assert extract_trigger_pay_ids([1, 2]) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# compute_trigger_sessions — the core session scanner
# ---------------------------------------------------------------------


def _paid_round(win: int = 0, pidwa: dict | None = None, remarks: str = "") -> dict:
    """Minimal paid round fixture. SpinType=1 matches M15/M12/M6
    convention; tests that need a different anchor override it."""
    return {
        "SpinType": 1,
        "CostCredits": 1000,
        "BetAmount": 1000,
        "WinCredits": win,
        "PayoutIdToWinAmount": pidwa if pidwa is not None else {},
        "ReMarks": remarks,
    }


def _bonus_round(spin_type: int, win: int | None = 0, remarks: str = "") -> dict:
    """Minimal bonus-side round fixture. Bonus rounds typically
    have CostCredits=None and sometimes WinCredits=None."""
    return {
        "SpinType": spin_type,
        "CostCredits": None,
        "WinCredits": win,
        "ReMarks": remarks,
    }


class TestComputeTriggerSessionsHappyPath:
    def test_m15_topdollar_session_win_is_last_selector_offer(self):
        """M15 TopDollar: paid (SpinType=1, ReMarks=Trigger, pay_id
        666 with win=0) → 4 selector offer rounds (SpinType=14)
        with ascending offer values → settlement (SpinType=15,
        WinCredits=None). Session win is the LAST non-None win —
        which is the final selector offer (player accepted it)."""
        rounds = [
            _paid_round(win=0, pidwa={"666": 0}, remarks="Trigger"),
            _bonus_round(14, win=15000),
            _bonus_round(14, win=20000),
            _bonus_round(14, win=25000),
            _bonus_round(14, win=40000),
            _bonus_round(15, win=None),
            _paid_round(win=0, pidwa={"9": 100}),  # back to paid
        ]
        sessions = compute_trigger_sessions(rounds)
        assert len(sessions) == 1
        s = sessions[0]
        assert s["trigger_idx"] == 0
        assert s["trigger_pay_ids"] == ["666"]
        assert s["trigger_spin_type"] == 1
        assert s["session_end_idx"] == 6  # index of the next SpinType=1 round
        assert s["session_win"] == 40000
        assert s["bonus_spin_types"] == [14, 14, 14, 14, 15]

    def test_m15_cooccurring_cherry_pay_id_not_trigger(self):
        """M15 real sample: 46 / 689 trigger rounds carry pay_id 9
        (cherry) paying 1000 alongside pay_id 666 trigger token.
        Only 666 should be counted as trigger anchor — the cherry
        win is already recorded as a regular payline hit by the
        analyzer's base aggregation loop (double-counting it as
        feature win would inflate pay_id 9's RTP contribution)."""
        rounds = [
            _paid_round(
                win=1000, pidwa={"666": 0, "9": 1000}, remarks="Trigger",
            ),
            _bonus_round(14, win=50000),
            _paid_round(win=0),
        ]
        sessions = compute_trigger_sessions(rounds)
        assert sessions[0]["trigger_pay_ids"] == ["666"]

    def test_session_ends_at_next_paid_spin_type_not_every_spin_type_change(self):
        """Bonus rounds often mix multiple SpinTypes (M15: 14 →
        14 → 14 → 15 for offer + settlement). The session only
        ends when we return to the TRIGGER round's SpinType —
        intermediate SpinType changes within the bonus sequence
        don't close the session."""
        rounds = [
            _paid_round(win=0, pidwa={"666": 0}, remarks="Trigger"),
            _bonus_round(14, win=10000),
            _bonus_round(15, win=None),
            _bonus_round(14, win=20000),  # ST changed but not to 1
            _paid_round(win=0),             # NOW back to paid — end
        ]
        s = compute_trigger_sessions(rounds)[0]
        assert s["session_end_idx"] == 4
        assert s["session_win"] == 20000
        assert s["bonus_spin_types"] == [14, 15, 14]

    def test_session_runs_to_end_of_rounds_when_no_return(self):
        """Trigger at the end of a robot's sequence without a
        closing paid round (chunk boundary). Session includes all
        subsequent bonus rounds; no error."""
        rounds = [
            _paid_round(win=0, pidwa={"666": 0}, remarks="Trigger"),
            _bonus_round(14, win=35000),
            _bonus_round(15, win=None),
        ]
        s = compute_trigger_sessions(rounds)[0]
        assert s["session_end_idx"] == 3
        assert s["session_win"] == 35000


class TestMultipleSessions:
    def test_back_to_back_sessions_counted_independently(self):
        rounds = [
            _paid_round(win=0, pidwa={"666": 0}, remarks="Trigger"),
            _bonus_round(14, win=15000),
            _paid_round(win=0),
            _paid_round(win=0, pidwa={"666": 0}, remarks="Trigger"),
            _bonus_round(14, win=80000),
            _paid_round(win=0),
        ]
        sessions = compute_trigger_sessions(rounds)
        assert len(sessions) == 2
        assert sessions[0]["session_win"] == 15000
        assert sessions[1]["session_win"] == 80000

    def test_non_trigger_rounds_between_sessions_ignored(self):
        """Normal paid rounds (no trigger) don't create sessions."""
        rounds = [
            _paid_round(win=100, pidwa={"1": 100}),
            _paid_round(win=0, pidwa={"666": 0}, remarks="Trigger"),
            _bonus_round(14, win=50000),
            _paid_round(win=200, pidwa={"5": 200}),
            _paid_round(win=0, pidwa={"666": 0}, remarks="Trigger"),
            _bonus_round(14, win=25000),
        ]
        sessions = compute_trigger_sessions(rounds)
        assert len(sessions) == 2
        assert sessions[0]["trigger_idx"] == 1
        assert sessions[1]["trigger_idx"] == 4


class TestRetriggerDoesNotDoubleCount:
    def test_trigger_add_freespin_mid_session_ignored_as_session_opener(self):
        """M39 DancingDrum: ``TriggerAddFreeSpin`` mid-freespin
        extends free-spin count, doesn't open a new session. The
        outer FreeSpin session continues with its original
        trigger's pay_ids; re-trigger round's win is folded into
        the outer session_win (last non-None rule)."""
        rounds = [
            _paid_round(
                win=0, pidwa={"100": 0}, remarks="TriggerFreeSpin",
            ),
            _bonus_round(67, win=500, remarks="FreeSpin"),
            _bonus_round(67, win=800, remarks="TriggerAddFreeSpin"),
            _bonus_round(67, win=1200, remarks="FreeSpin"),
            _paid_round(win=0),  # back to SpinType=1 — session ends
        ]
        sessions = compute_trigger_sessions(rounds)
        assert len(sessions) == 1
        assert sessions[0]["trigger_pay_ids"] == ["100"]
        # Session win is the last freespin's cumulative-or-per-round
        # WinCredits (last non-None = 1200). Actual upstream feature
        # sum behavior is verified by the analyzer pipeline test;
        # here we just lock the rule — NOT 500 + 800 + 1200 summed,
        # which would be wrong (re-trigger round's win is part of
        # the progression, not additive).
        assert sessions[0]["session_win"] == 1200


class TestFamilyCoverage:
    """Spot-check remarks strings observed in the live probe for
    each Type-1 family to guard against a future edit that breaks
    one specific family's signal."""

    def test_m6_fortunes_triggerfreespin(self):
        rounds = [
            _paid_round(win=0, pidwa={"T": 0}, remarks="TriggerFreeSpin"),
            _bonus_round(7, win=5000),
        ]
        s = compute_trigger_sessions(rounds)
        assert len(s) == 1 and s[0]["session_win"] == 5000

    def test_m116_christmas_gold_bonus(self):
        rounds = [
            _paid_round(
                win=0, pidwa={"T": 0}, remarks="Trigger GoldBonus;",
            ),
            _bonus_round(68, win=8000, remarks="GoldBonus"),
        ]
        s = compute_trigger_sessions(rounds)
        assert len(s) == 1 and s[0]["session_win"] == 8000

    def test_m123_valentine_selector(self):
        rounds = [
            _paid_round(
                win=0, pidwa={"T": 0}, remarks="Trigger Selector;",
            ),
            _bonus_round(111, win=0, remarks="Selector"),
            _bonus_round(126, win=2000, remarks="Freespin 1;"),
            _bonus_round(126, win=3500, remarks="Freespin 2;"),
        ]
        s = compute_trigger_sessions(rounds)
        assert len(s) == 1 and s[0]["session_win"] == 3500


class TestDefensiveInputs:
    def test_non_dict_rounds_skipped(self):
        """A corrupt chunk might have non-dict entries intermixed.
        Don't raise; just skip them."""
        rounds = [
            "not a round",  # type: ignore[list-item]
            _paid_round(win=0, pidwa={"666": 0}, remarks="Trigger"),
            None,  # type: ignore[list-item]
            _bonus_round(14, win=40000),
            _paid_round(win=0),
        ]
        s = compute_trigger_sessions(rounds)
        assert len(s) == 1
        assert s[0]["session_win"] == 40000

    def test_trigger_remark_without_pay_ids_skipped(self):
        """Degenerate trigger: ReMarks=Trigger but PayoutIdToWinAmount
        is empty. Without a pay_id anchor we can't attribute the
        session win, so skip rather than attribute to an empty set."""
        rounds = [
            _paid_round(win=0, pidwa={}, remarks="Trigger"),
            _bonus_round(14, win=40000),
        ]
        assert compute_trigger_sessions(rounds) == []

    def test_empty_rounds_returns_empty(self):
        assert compute_trigger_sessions([]) == []

    def test_no_trigger_rounds_returns_empty(self):
        rounds = [_paid_round() for _ in range(5)]
        assert compute_trigger_sessions(rounds) == []

    def test_bonus_round_missing_wincredits_fields_survives(self):
        """Bonus round dict without a ``WinCredits`` key at all
        (not just None value). last_nonnone_win stays at 0.
        Analyzer shouldn't attribute any win to this session."""
        rounds = [
            _paid_round(win=0, pidwa={"T": 0}, remarks="Trigger"),
            {"SpinType": 14, "CostCredits": None},  # no WinCredits field
            _paid_round(win=0),
        ]
        s = compute_trigger_sessions(rounds)
        assert s[0]["session_win"] == 0
