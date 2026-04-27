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
from fresh_slotlab.round_win import SettlementWinAmountRule


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
    def test_m15_filter_preserves_selector_offer_attribution(self):
        """Iter 3 regression: the Iter 3 double-count filter
        ``_round_has_credited_win`` must NOT fire on M15 selector
        offer rounds (PayoutIdToWinAmount=None) — they don't
        actually carry any pay_id credit, so their WinCredits
        (the offer values) IS the only path for the trigger pay_id
        to recover its bonus win. This test locks Iter 1's
        105,665,000 verified total survives the Iter 3 filter."""
        rounds = [
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0,
             "PayoutIdToWinAmount": {"666": 0}, "ReMarks": "Trigger"},
            # Selector offer rounds — no Payout dict at all.
            {"SpinType": 14, "CostCredits": None, "WinCredits": 15000,
             "PayoutIdToWinAmount": None, "ReMarks": ""},
            {"SpinType": 14, "CostCredits": None, "WinCredits": 20000,
             "PayoutIdToWinAmount": None, "ReMarks": ""},
            {"SpinType": 14, "CostCredits": None, "WinCredits": 40000,
             "PayoutIdToWinAmount": None, "ReMarks": ""},
            # Settlement round — Win=None, Payout=None.
            {"SpinType": 15, "CostCredits": None, "WinCredits": None,
             "PayoutIdToWinAmount": None, "ReMarks": ""},
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0},
        ]
        s = compute_trigger_sessions(rounds)[0]
        assert s["win_rule"] == "last_non_none"
        # 40000 is the accepted offer. Filter doesn't apply — all
        # selector rounds have PayoutIdToWinAmount=None (not dict).
        assert s["session_win"] == 40000

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


# ---------------------------------------------------------------------
# Type 2 — paid round without "Trigger" ReMarks but with win=0 pay_id
# (WheelSelector M273 / CommonSelector M201/M257). Rule: sum_all.
# ---------------------------------------------------------------------


class TestType2WheelSelector:
    """M273 WheelSelector shape (probed live): paid round SpinType=140
    with ``PayoutIdToWinAmount={'5801': 0}`` and empty ReMarks;
    then non-paid rounds move through SpinType 139 → 136 → 137 → 117
    (freespins). Rule: sum all freespin WinCredits."""

    def test_m273_freespin_rounds_with_pay_id_attribution_dont_double_count(self):
        """Iter 3 correction: the probed M273 freespin rounds
        carry non-empty PayoutIdToWinAmount (e.g. {'6': 7000,
        '101': 2000}). Those amounts are already credited to
        pay_id 6 / 101 by the round-level aggregator — folding
        the same WinCredits into the trigger pay_id's session_win
        would double-count. The filter
        ``_round_has_credited_win`` excludes them. Session_win
        drops to 0 (trigger pay_id 5801 correctly captures zero
        bonus-feature win; all bonus credit flows through the
        freespin pay_ids at round level)."""
        rounds = [
            {"SpinType": 140, "CostCredits": 1000, "WinCredits": 0,
             "PayoutIdToWinAmount": {"5801": 0}, "ReMarks": ""},
            {"SpinType": 139, "CostCredits": 0, "WinCredits": 0,
             "PayoutIdToWinAmount": {},
             "ReMarks": "Minigame CellIndexes: 2,2,2,1,"},
            {"SpinType": 136, "CostCredits": None, "WinCredits": None,
             "PayoutIdToWinAmount": None, "ReMarks": "WheelSelector"},
            {"SpinType": 137, "CostCredits": None, "WinCredits": 0,
             "PayoutIdToWinAmount": None,
             "ReMarks": "PreWheel ReqCommonParam 3-5-9 "},
            {"SpinType": 117, "CostCredits": 0, "WinCredits": 0,
             "PayoutIdToWinAmount": {}, "ReMarks": " Freespin 1 of 7"},
            # Real freespin wins: each has its own Payout attribution,
            # so round aggregator owns them.
            {"SpinType": 117, "CostCredits": 0, "WinCredits": 9000,
             "PayoutIdToWinAmount": {"6": 7000, "101": 2000},
             "ReMarks": " Freespin 2 of 7"},
            {"SpinType": 117, "CostCredits": 0, "WinCredits": 5000,
             "PayoutIdToWinAmount": {"101": 5000},
             "ReMarks": " Freespin 3 of 7"},
            {"SpinType": 117, "CostCredits": 0, "WinCredits": 500,
             "PayoutIdToWinAmount": {"9": 500, "2600": 0},
             "ReMarks": " Freespin 4 of 7"},
            {"SpinType": 117, "CostCredits": 0, "WinCredits": 0,
             "PayoutIdToWinAmount": {}, "ReMarks": " Freespin 5 of 7"},
            {"SpinType": 140, "CostCredits": 1000, "WinCredits": 500,
             "PayoutIdToWinAmount": {"9": 500}, "ReMarks": ""},
        ]
        sessions = compute_trigger_sessions(rounds)
        assert len(sessions) == 1
        s = sessions[0]
        assert s["trigger_pay_ids"] == ["5801"]
        assert s["win_rule"] == "sum_all"
        # Every bonus round with a nonzero-win Payout is filtered;
        # the Payout-empty rounds contribute Win=0. Net session_win = 0.
        assert s["session_win"] == 0

    def test_m273_bonus_round_without_pay_attribution_is_counted(self):
        """Regression guard: if a M273-style session had bonus rounds
        without any Payout attribution (e.g. a pure selector-offer-
        style sub-flow), those WinCredits WOULD accrue to the trigger
        pay_id — the filter only excludes rounds that already had
        credit at pay_id level."""
        rounds = [
            {"SpinType": 140, "CostCredits": 1000, "WinCredits": 0,
             "PayoutIdToWinAmount": {"X": 0}, "ReMarks": ""},
            # No Payout attribution → counts toward session.
            {"SpinType": 117, "CostCredits": 0, "WinCredits": 10000,
             "PayoutIdToWinAmount": None, "ReMarks": ""},
            # Payout attribution → filtered out of sum.
            {"SpinType": 117, "CostCredits": 0, "WinCredits": 50000,
             "PayoutIdToWinAmount": {"1": 50000}, "ReMarks": ""},
            {"SpinType": 140, "CostCredits": 1000, "WinCredits": 0},
        ]
        s = compute_trigger_sessions(rounds)[0]
        assert s["win_rule"] == "sum_all"
        assert s["session_win"] == 10000  # first round only; second filtered


class TestType2CommonSelector:
    """M201 CommonSelector sample (probed live). Sessions have 2
    kinds: LockReSpin (pay_id 7777 → 1-3 bonus rounds) and
    NewFreespin (pay_id 6666 → many freespin rounds). Both use
    sum_all rule."""

    def test_m201_lockrespin_session_filters_credited_round(self):
        """Iter 3 correction: the M201 bonus round
        ``{'20102': 11660}`` is credited to pay_id 20102 at round
        level; session must not double-credit pay_id 7777 with the
        same 11660. session_win collapses to 0."""
        rounds = [
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0,
             "PayoutIdToWinAmount": {"7777": 0}, "ReMarks": ""},
            {"SpinType": 13, "CostCredits": 0, "WinCredits": 0,
             "PayoutIdToWinAmount": {}, "ReMarks": ""},
            {"SpinType": 149, "CostCredits": None, "WinCredits": None,
             "PayoutIdToWinAmount": None, "ReMarks": "Selector"},
            {"SpinType": 13, "CostCredits": 0, "WinCredits": 11660,
             "PayoutIdToWinAmount": {"20102": 11660}, "ReMarks": ""},
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0},
        ]
        s = compute_trigger_sessions(rounds)[0]
        assert s["trigger_pay_ids"] == ["7777"]
        assert s["win_rule"] == "sum_all"
        assert s["session_win"] == 0

    def test_m257_freespin_all_rounds_already_attributed(self):
        """Iter 3 correction: every M257 freespin round carries its
        own Payout entry (pay_id 1 / 7 etc). All are filtered.
        session_win = 0 on trigger pay_id 666; the freespin-round
        pay_ids absorb the feature's RTP contribution at round level."""
        rounds = [
            {"SpinType": 140, "CostCredits": 1000, "WinCredits": 0,
             "PayoutIdToWinAmount": {"666": 0}, "ReMarks": ""},
            {"SpinType": 149, "CostCredits": None, "WinCredits": None,
             "PayoutIdToWinAmount": None, "ReMarks": "Selector14"},
            {"SpinType": 126, "CostCredits": 0, "WinCredits": 22200,
             "PayoutIdToWinAmount": {"4": 22200},
             "ReMarks": "Freespin 1; "},
            {"SpinType": 126, "CostCredits": 0, "WinCredits": 5550,
             "PayoutIdToWinAmount": {"7": 5550},
             "ReMarks": "Freespin 2; "},
            {"SpinType": 126, "CostCredits": 0, "WinCredits": 0,
             "PayoutIdToWinAmount": {}, "ReMarks": "Freespin 3; "},
            {"SpinType": 126, "CostCredits": 0, "WinCredits": 28860,
             "PayoutIdToWinAmount": {"7": 1110, "1": 27750},
             "ReMarks": "Freespin 4; "},
            {"SpinType": 140, "CostCredits": 1000, "WinCredits": 0},
        ]
        s = compute_trigger_sessions(rounds)[0]
        assert s["win_rule"] == "sum_all"
        assert s["session_win"] == 0


class TestTriggerAnchorRequired:
    """Paid round without any win==0 pay_id is NOT a trigger session
    even if followed by non-paid rounds. Covers M209 gap case: paid
    rounds carry ``PayoutIdToWinAmount={}`` (no anchor) but still
    enter a bonus sequence via SpinType transition alone — these
    sessions can't be attributed to a pay_id so the helper skips."""

    def test_empty_payout_on_paid_round_skipped(self):
        rounds = [
            {"SpinType": 140, "CostCredits": 1000, "WinCredits": 0,
             "PayoutIdToWinAmount": {}, "ReMarks": ""},
            {"SpinType": 149, "CostCredits": None, "WinCredits": None,
             "ReMarks": "Selector"},
            {"SpinType": 36, "CostCredits": 0, "WinCredits": 10000,
             "ReMarks": "move"},
            {"SpinType": 140, "CostCredits": 1000, "WinCredits": 0},
        ]
        assert compute_trigger_sessions(rounds) == []

    def test_paid_round_with_only_paying_pay_ids_skipped(self):
        """Paid round with pay_ids but all have nonzero win (normal
        payline hit) — not a trigger. Regression guard."""
        rounds = [
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 500,
             "PayoutIdToWinAmount": {"9": 500}, "ReMarks": ""},
            # No non-paid rounds following — regular paid spin.
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0},
        ]
        assert compute_trigger_sessions(rounds) == []

    def test_non_paid_successor_required(self):
        """Paid round with win=0 pay_id but NO following non-paid
        rounds → ordinary paid spin (the pay_id is payline metadata,
        not a trigger signal). Important: don't treat every win=0
        pay_id as a trigger — M273 has pay_id 2600 and 5801 that
        can appear on non-trigger rounds too."""
        rounds = [
            {"SpinType": 140, "CostCredits": 1000, "WinCredits": 0,
             "PayoutIdToWinAmount": {"5801": 0}, "ReMarks": ""},
            # Back to paid — no bonus sequence.
            {"SpinType": 140, "CostCredits": 1000, "WinCredits": 500,
             "PayoutIdToWinAmount": {"9": 500}},
        ]
        assert compute_trigger_sessions(rounds) == []


class TestPaidRoundClassifier:
    """CostCredits>0 classifier — shared between Type 1 and Type 2
    session boundary logic. Regression tests guard the rule."""

    def test_cost_positive_is_paid(self):
        from fresh_slotlab.trigger_sessions import _is_paid_round
        assert _is_paid_round({"CostCredits": 1000}) is True

    def test_cost_zero_is_not_paid(self):
        from fresh_slotlab.trigger_sessions import _is_paid_round
        assert _is_paid_round({"CostCredits": 0}) is False

    def test_cost_none_is_not_paid(self):
        """Bonus/settlement rounds consistently have CostCredits=None
        across every probed machine (M15 selector, M273 freespin,
        M201 selector, M209 move, M257 freespin)."""
        from fresh_slotlab.trigger_sessions import _is_paid_round
        assert _is_paid_round({"CostCredits": None}) is False

    def test_missing_cost_field_is_not_paid(self):
        from fresh_slotlab.trigger_sessions import _is_paid_round
        assert _is_paid_round({}) is False

    def test_non_dict_is_not_paid(self):
        from fresh_slotlab.trigger_sessions import _is_paid_round
        assert _is_paid_round(None) is False
        assert _is_paid_round("not a dict") is False

    def test_malformed_cost_is_not_paid(self):
        from fresh_slotlab.trigger_sessions import _is_paid_round
        assert _is_paid_round({"CostCredits": "bad"}) is False


# ---------------------------------------------------------------------
# Rule-driven path (2026-04-27): when round_win_rules is provided,
# bonus rounds' WinCredits is read via extract_round_win so phantom-
# offer rounds (M12 ST=14) contribute 0 and settlement rounds (M12
# ST=15 carrying WinAmount) contribute their WinAmount.
# ---------------------------------------------------------------------


class TestRoundWinRulesIntegration:
    """Default-mode (no rules) byte-identity is locked by the existing
    M15 / M6 / M116 / M123 / M273 / M201 / M257 tests above. These new
    tests lock the rule-driven path against realistic M12 rawdata
    where ST=15 settlement carries WinAmount but no WinCredits field.
    """

    def _topdollar_rule(self) -> SettlementWinAmountRule:
        return SettlementWinAmountRule(
            phantom_spin_types=[14],
            settlement_spin_types=[15],
        )

    def test_m12_settlement_winamount_is_authoritative_session_win(self):
        """Realistic M12 fixture: ST=14 carries OfferValue*bet as
        phantom WinCredits, ST=15 carries the actual payout in a
        WinAmount field with no WinCredits at all. Default path picks
        the last ST=14 offer (30000) -- wrong; rule-driven path picks
        ST=15 WinAmount (60000) -- correct."""
        rounds = [
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0,
             "PayoutIdToWinAmount": {"666": 0}, "ReMarks": "Trigger"},
            # 4 selector offer rounds. WinCredits = OfferValue*bet.
            {"SpinType": 14, "CostCredits": 0, "WinCredits": 17000,
             "PayoutIdToWinAmount": None},
            {"SpinType": 14, "CostCredits": 0, "WinCredits": 25000,
             "PayoutIdToWinAmount": None},
            {"SpinType": 14, "CostCredits": 0, "WinCredits": 15000,
             "PayoutIdToWinAmount": None},
            {"SpinType": 14, "CostCredits": 0, "WinCredits": 30000,
             "PayoutIdToWinAmount": None},
            # Settlement: NO WinCredits field at all, only WinAmount
            # (twice the last offer in this real-rawdata example).
            {"SpinType": 15, "CostCredits": 0, "WinAmount": 60000,
             "PayoutIdToWinAmount": None},
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0},
        ]
        # Default (legacy): last_non_none picks last ST=14 = 30000.
        s_default = compute_trigger_sessions(rounds)[0]
        assert s_default["session_win"] == 30000

        # Rule-driven: phantom -> 0, settlement -> WinAmount = 60000.
        s_rules = compute_trigger_sessions(
            rounds, round_win_rules=[self._topdollar_rule()],
        )[0]
        assert s_rules["session_win"] == 60000

    def test_m12_variant1_single_pick_settlement(self):
        """Variant 1 single-pick: 1 ST=14 + 1 ST=15. The legacy path
        uses last ST=14 WinCredits which happens to equal the WinAmount
        when no multiplier fires (drift scan A_clean coincidence).
        Rule-driven path is semantically correct: read ST=15 WinAmount."""
        rounds = [
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0,
             "PayoutIdToWinAmount": {"666": 0}, "ReMarks": "Trigger"},
            {"SpinType": 14, "CostCredits": 0, "WinCredits": 20000,
             "PayoutIdToWinAmount": None},
            {"SpinType": 15, "CostCredits": 0, "WinAmount": 20000,
             "PayoutIdToWinAmount": None},
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0},
        ]
        s_default = compute_trigger_sessions(rounds)[0]
        assert s_default["session_win"] == 20000  # last ST=14 = 20000

        s_rules = compute_trigger_sessions(
            rounds, round_win_rules=[self._topdollar_rule()],
        )[0]
        assert s_rules["session_win"] == 20000  # ST=15 WinAmount = 20000

    def test_m12_variant1_with_multiplier_settlement_doubles(self):
        """Real-rawdata variant 1 occasionally has a 2x multiplier
        applied at settlement (132/612 pairs in fleet scan): ST=14
        WinCredits=30000, ST=15 WinAmount=60000. Default reads 30000
        (wrong); rule path reads WinAmount (correct)."""
        rounds = [
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0,
             "PayoutIdToWinAmount": {"666": 0}, "ReMarks": "Trigger"},
            {"SpinType": 14, "CostCredits": 0, "WinCredits": 30000,
             "PayoutIdToWinAmount": None},
            {"SpinType": 15, "CostCredits": 0, "WinAmount": 60000,
             "PayoutIdToWinAmount": None},
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0},
        ]
        s_default = compute_trigger_sessions(rounds)[0]
        assert s_default["session_win"] == 30000  # legacy = wrong here

        s_rules = compute_trigger_sessions(
            rounds, round_win_rules=[self._topdollar_rule()],
        )[0]
        assert s_rules["session_win"] == 60000  # corrected

    def test_unconfigured_machine_default_byte_identical(self):
        """Sanity: if rules list is empty the legacy session_win must
        match exactly. Locks the no-config path for the 380+ A_clean
        machines."""
        rounds = [
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0,
             "PayoutIdToWinAmount": {"666": 0}, "ReMarks": "Trigger"},
            {"SpinType": 14, "CostCredits": 0, "WinCredits": 15000,
             "PayoutIdToWinAmount": None},
            {"SpinType": 14, "CostCredits": 0, "WinCredits": 40000,
             "PayoutIdToWinAmount": None},
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0},
        ]
        s_none = compute_trigger_sessions(rounds, round_win_rules=None)
        s_empty = compute_trigger_sessions(rounds, round_win_rules=[])
        s_omitted = compute_trigger_sessions(rounds)
        assert s_none[0]["session_win"] == 40000
        assert s_empty[0]["session_win"] == 40000
        assert s_omitted[0]["session_win"] == 40000

    def test_m273_freespin_rule_not_active_no_change(self):
        """Type 2 freespin (M273) WITHOUT a topdollar rule applied to
        it must produce the same session_win as legacy -- 0, because
        round-level pay_id credits the freespin pay_ids directly."""
        rounds = [
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0,
             "PayoutIdToWinAmount": {"5801": 0}, "ReMarks": ""},
            {"SpinType": 137, "CostCredits": 0, "WinCredits": 9000,
             "PayoutIdToWinAmount": {"6": 7000, "101": 2000}},
            {"SpinType": 1, "CostCredits": 1000, "WinCredits": 0},
        ]
        # Even with a TopDollar rule active, M273 ST=137 isn't in the
        # phantom_spin_types list -> rule returns None -> legacy path.
        # _round_has_credited_win filter still excludes the freespin
        # round so session_win = 0 regardless of rules.
        s = compute_trigger_sessions(
            rounds, round_win_rules=[self._topdollar_rule()],
        )[0]
        assert s["session_win"] == 0
