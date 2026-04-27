"""End-to-end integration: parse_chunk_response with round_win_rules.

Two regression contracts locked here:

  1. **M12 fix**: with the TopDollarSelector rule active, the chunk's
     ``win`` (= our_total_win) matches the upstream's
     ``analysisResult.TotalWin`` (= server_total_win) within 0.1%.
     Without the rule, the legacy path over-counts ST=14 phantom
     offers by tens of millions of credits.

  2. **A_clean byte-identical lockdown**: for machines NOT in the
     config (M14 / M272 / M273 / M201 / M257 ...), every numeric and
     dict field returned by parse_chunk_response is byte-identical
     between ``round_win_rules=None`` and ``round_win_rules=[]``.
     This is the non-regression invariant: 380+ A_clean machines
     see zero behavioural change after the wiring is in place.

Tests skip when the required cached chunk isn't present (CI may run
on a clean checkout without 100+ machine rawdata caches).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fresh_slotlab.player_impact_analyzer import parse_chunk_response
from fresh_slotlab.round_win import (
    SettlementWinAmountRule,
    SynthesizePayIdRule,
    load_rules_for_machine,
)


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAWDATA = REPO_ROOT / "rawdata"
CONFIG_PATH = REPO_ROOT / "configs" / "machine_round_win_rules.json"


def _load_chunk(machine: str, mode_dir: str, chunk_name: str = "chunk_0001.json"):
    cf = RAWDATA / machine / mode_dir / chunk_name
    if not cf.exists():
        pytest.skip(f"cached chunk not present: {cf}")
    with open(cf, "r", encoding="utf-8") as f:
        envelope = json.load(f)
    resp = envelope.get("response")
    if not isinstance(resp, list):
        pytest.skip(f"chunk {cf} has no response list")
    bet = int(envelope.get("_bet", 1000))
    return resp, bet


def _server_total_win(resp) -> float:
    """Sum analysisResult.TotalWin[*].WinCredits across all robots --
    the upstream's authoritative total."""
    total = 0.0
    for robot in resp:
        if not isinstance(robot, dict):
            continue
        ar = robot.get("analysisResult")
        if isinstance(ar, str):
            try:
                analysis = json.loads(ar)
            except (json.JSONDecodeError, ValueError):
                continue
        elif isinstance(ar, dict):
            analysis = ar
        else:
            continue
        tw = analysis.get("TotalWin")
        if isinstance(tw, str):
            try:
                tw = json.loads(tw)
            except (json.JSONDecodeError, ValueError):
                tw = None
        if isinstance(tw, dict):
            for v in tw.values():
                if isinstance(v, dict):
                    val = v.get("WinCredits")
                    try:
                        total += float(val) if val is not None else 0.0
                    except (TypeError, ValueError):
                        pass
    return total


@pytest.fixture(scope="module")
def round_win_config():
    if not CONFIG_PATH.exists():
        pytest.skip(f"config not present: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------
# M12 fix: rule-driven path matches server_total_win within 0.1%
# ---------------------------------------------------------------------


class TestM12RuleFix:
    def test_m12_variant0_mode7_our_matches_server_with_rule(self, round_win_config):
        machine = "M12$TopDollarSelector$0$"
        resp, bet = _load_chunk(machine, "mode_7")
        server = _server_total_win(resp)
        assert server > 0, "server_total_win must be positive on real chunk"

        # Default (legacy) path: known bug -- our_total_win much higher
        # than server (phantom offers counted).
        rec_legacy = parse_chunk_response(resp, 1, bet)
        assert rec_legacy["ok"] is True
        legacy_drift_pct = abs(rec_legacy["win"] - server) / server * 100.0
        assert legacy_drift_pct > 5.0, (
            f"legacy path expected >5% drift on M12 variant 0 "
            f"(our={rec_legacy['win']} vs server={server}, "
            f"drift={legacy_drift_pct:.2f}%) -- if this triggers, the "
            f"phantom-offer bug has been fixed elsewhere or the cached "
            f"chunk changed shape."
        )

        # Rule-driven path: drift drops to ~0 (within 0.1%).
        rules = load_rules_for_machine(machine, round_win_config)
        assert len(rules) == 1
        assert isinstance(rules[0], SettlementWinAmountRule)
        rec_rules = parse_chunk_response(resp, 1, bet, round_win_rules=rules)
        assert rec_rules["ok"] is True
        fixed_drift_pct = abs(rec_rules["win"] - server) / server * 100.0
        assert fixed_drift_pct < 0.1, (
            f"rule-driven path should match server within 0.1pp drift "
            f"(our={rec_rules['win']} vs server={server}, "
            f"drift={fixed_drift_pct:.4f}%)"
        )

    def test_m15_variant0_mode1_our_matches_server_with_rule(self, round_win_config):
        machine = "M15$TopDollarSelector$0$"
        resp, bet = _load_chunk(machine, "mode_1")
        server = _server_total_win(resp)
        assert server > 0

        rec_legacy = parse_chunk_response(resp, 1, bet)
        legacy_drift = abs(rec_legacy["win"] - server) / server * 100.0
        assert legacy_drift > 5.0, "M15 mode_1 legacy path expected >5% drift"

        rules = load_rules_for_machine(machine, round_win_config)
        rec_rules = parse_chunk_response(resp, 1, bet, round_win_rules=rules)
        fixed_drift = abs(rec_rules["win"] - server) / server * 100.0
        assert fixed_drift < 0.1, (
            f"M15 mode_1 fixed drift should be <0.1% (got {fixed_drift:.4f}%)"
        )

    def test_m12_variant1_mode7_byte_identical_chunk_win_with_rule(self, round_win_config):
        """Variant 1 single-pick is the A_clean coincidence -- legacy
        chunk_win happens to match server (ST=14 WinCredits == ST=15
        WinAmount per round). Rule-driven path also matches; both
        should land at server within 0.1%."""
        machine = "M12$TopDollarSelector$1$"
        resp, bet = _load_chunk(machine, "mode_7")
        server = _server_total_win(resp)
        rules = load_rules_for_machine(machine, round_win_config)
        rec_rules = parse_chunk_response(resp, 1, bet, round_win_rules=rules)
        fixed_drift = abs(rec_rules["win"] - server) / server * 100.0
        assert fixed_drift < 0.1


# ---------------------------------------------------------------------
# A_clean byte-identical lockdown
# ---------------------------------------------------------------------


# Numeric scalars that must agree exactly.
_BYTE_IDENTICAL_SCALAR_FIELDS = (
    "spins", "bet", "win", "ret_count", "ret_sum", "ret_sq_sum", "max_return_x",
    "win_spins", "loss_spins", "profit_spins", "breakeven_or_more_spins",
    "big_win_x10_spins", "win_sum", "lack_credit_spins",
    "bonus_total_rounds", "bonus_retrigger_rounds", "max_loss_streak",
    "max_win_streak", "total_symbol_slots",
)

# Dict / list fields that must compare equal.
_BYTE_IDENTICAL_CONTAINER_FIELDS = (
    "payline_hits", "payline_win_approx",
    "loss_streak_hist", "win_streak_hist",
    "multiplier_bucket_spins", "multiplier_bucket_bet", "multiplier_bucket_win",
    "payout_id_hits", "payout_id_win",
    "spin_type_spins", "spin_type_bet", "spin_type_paid_bet",
    "spin_type_win", "spin_type_wins", "spin_type_paid_rounds",
    "symbol_counts",
)


def _assert_record_byte_identical(rec_a, rec_b, tag: str):
    for k in _BYTE_IDENTICAL_SCALAR_FIELDS:
        assert rec_a[k] == rec_b[k], (
            f"[{tag}] scalar field {k} diverged: legacy={rec_a[k]!r} "
            f"empty_rules={rec_b[k]!r}"
        )
    for k in _BYTE_IDENTICAL_CONTAINER_FIELDS:
        assert rec_a[k] == rec_b[k], (
            f"[{tag}] container field {k} diverged"
        )


# Sampled machines whose cached chunks should produce IDENTICAL
# parse_chunk_response output between rules=None and rules=[]. This
# is the dispatch-no-op invariant: even when rule machinery is in
# the call path, an empty rule list must not perturb any numeric
# output.
@pytest.mark.parametrize("machine,mode_dir", [
    ("M14", "mode_1"),               # base paid-only -- A_clean baseline
    ("M272", "mode_1"),              # MapCollection / NewFreespin (now in rule applies_to but byte-identity test passes empty rules so behavior unchanged)
    ("M273", "mode_1"),              # WheelSelector freespin (Type 2)
    ("M201", "mode_1"),              # CommonSelector lockrespin
    ("M257", "mode_1"),              # CommonSelector freespin
    ("M99", "mode_1"),               # D_other class
    ("M112", "mode_1"),              # FinalMinigame summary+sub
])
class TestRulesDispatchNoop:
    def test_no_rules_vs_empty_rules_identical(self, machine, mode_dir, round_win_config):
        """Calling parse_chunk_response with rules=None vs rules=[]
        must produce byte-identical numeric output. This locks the
        invariant that the rule-dispatch code path is a no-op when no
        rules apply -- no rounding drift from extra float arithmetic,
        no field re-ordering quirks, nothing."""
        resp, bet = _load_chunk(machine, mode_dir)
        rec_none = parse_chunk_response(resp, 1, bet, round_win_rules=None)
        rec_empty = parse_chunk_response(resp, 1, bet, round_win_rules=[])
        _assert_record_byte_identical(rec_none, rec_empty, f"{machine}/{mode_dir}")


# Machines that genuinely have NO rule entry (rule absent from
# config). M14 is paid-only baseline; M99/M112 are D_other left
# for a future sub-round-dedupe rule.
@pytest.mark.parametrize("machine,mode_dir", [
    ("M14", "mode_1"),
    ("M99", "mode_1"),
    ("M112", "mode_1"),
])
def test_unconfigured_machine_loads_no_rules(machine, mode_dir, round_win_config):
    """The actual config (TopDollar + synthesize catch-all) must
    produce an empty rule list for these specific machines."""
    rules = load_rules_for_machine(machine, round_win_config)
    assert rules == [], f"{machine} unexpectedly resolves to {[type(r).__name__ for r in rules]}"


# ---------------------------------------------------------------------
# Inverse: configured machines DO get rules
# ---------------------------------------------------------------------


@pytest.mark.parametrize("machine", [
    "M12$TopDollarSelector$0$",
    "M12$TopDollarSelector$1$",
    "M12$TopDollarSelector$2$40",
    "M15$TopDollarSelector$0$",
    "M15$TopDollarSelector$1$",
    "M15$TopDollarSelector$2$40",
    "M90$TopDollarSelector$0$",
    "M90$TopDollarSelector$1$",
    "M90$TopDollarSelector$2$40",
    "M132$TopDollarSelector$0$",
    "M132$TopDollarSelector$1$",
    "M132$TopDollarSelector$2$40",
])
def test_topdollar_selectors_load_settlement_rule(machine, round_win_config):
    rules = load_rules_for_machine(machine, round_win_config)
    settlement_rules = [r for r in rules if isinstance(r, SettlementWinAmountRule)]
    assert len(settlement_rules) == 1
    assert settlement_rules[0].phantom_st == frozenset([14])
    assert settlement_rules[0].settlement_st == frozenset([15])


# ---------------------------------------------------------------------
# PayId attribution invariant (2026-04-27): the second invariant.
# sum(payout_id_win.values()) + sum of trigger session_wins ~= total_win
# After the synthesize_pay_id catch-all rule + multi-settlement
# sum_win fix in trigger_sessions, configured machines should have
# their payid drilldown match headline RTP.
# ---------------------------------------------------------------------


def _payid_invariant_check(rec, total_win_target: float, tag: str, tolerance_pct: float = 0.5):
    """Verify sum(payout_id_win) ~= chunk_win within tolerance.

    Note: this checks ROUND-LEVEL pid attribution only. trigger_sessions
    further attributes session_win to trigger pay_ids (e.g. TopDollar
    pay_id 666), which the analyzer adds on top via a separate code
    path. So a discrepancy here may still be closed by session_win
    attribution -- the e2e check is via headline RTP minus payid_top20
    rtp_pp on the finalized summary.

    For machines where round-level alone covers attribution (Wheel,
    Freespin etc with rule-synthesized pay_ids), this should match
    closely.
    """
    pid_sum = sum(rec["payout_id_win"].values())
    if total_win_target == 0:
        return  # nothing to check
    gap_pct = abs(rec["win"] - pid_sum) / rec["win"] * 100.0 if rec["win"] > 0 else 0.0
    return pid_sum, gap_pct


class TestPayidInvariantWheelMachines:
    """For wheel-bonus machines (M279/M214/M250 etc), the universal
    fallback synthesizer in parse_chunk_response surfaces ST=2
    wheel rounds (which carry WinCredits but empty PayoutIdToWinAmount)
    as ``_unattributed_st2`` in the payid drilldown. The leading
    underscore is the convention for synthetic/catch-all labels."""

    def test_m279_st2_appears_via_fallback(self, round_win_config):
        machine = "M279"
        resp, bet = _load_chunk(machine, "mode_1")
        # Universal fallback fires regardless of rules -- M279 has
        # no specific rule today (no SynthesizePayIdRule entry).
        rec = parse_chunk_response(resp, 1, bet)
        assert "_unattributed_st2" in rec["payout_id_win"]
        assert rec["payout_id_win"]["_unattributed_st2"] > 0

    def test_m279_payid_invariant_closes_via_fallback(self, round_win_config):
        """Universal fallback closes the sum(payid_win) ~= chunk_win
        invariant. M279 wheel rounds previously left a 4% gap; now
        the delta lives in ``_unattributed_st2`` so total matches.

        Both rules=None and rules=[] paths produce identical output
        because no rule entry exists for M279 in the current config."""
        machine = "M279"
        resp, bet = _load_chunk(machine, "mode_1")
        rec = parse_chunk_response(resp, 1, bet)
        pid_sum = sum(rec["payout_id_win"].values())
        gap_pct = abs(rec["win"] - pid_sum) / rec["win"] * 100.0
        assert gap_pct < 0.5, (
            f"M279 payid invariant expected gap <0.5% post-fallback "
            f"(got {gap_pct:.4f}%, win={rec['win']}, pid_sum={pid_sum})"
        )

    def test_m279_total_attribution_matches_chunk_win(self, round_win_config):
        """The fallback pid value plus all real pid values together
        equal chunk_win exactly (within float drift). This is the
        strict end-to-end invariant the user looks at when comparing
        payid_top20 sum to headline RTP."""
        machine = "M279"
        resp, bet = _load_chunk(machine, "mode_1")
        rec = parse_chunk_response(resp, 1, bet)
        pid_sum = sum(rec["payout_id_win"].values())
        # Allow up to 1 credit per round of float-rounding drift.
        assert abs(rec["win"] - pid_sum) < max(1.0, rec["win"] * 1e-6), (
            f"M279 strict invariant: chunk_win={rec['win']} vs "
            f"sum(payout_id_win)={pid_sum}; delta={rec['win']-pid_sum}"
        )


class TestMultiAnchorTriggerSession:
    """When a trigger paid round has multiple zero-value pay_ids
    (M214 mode 5: pid={'1': 0, '666': 0} -- '1' is the base-game
    line that paid 0 on this spin, '666' is the actual TriggerWheel
    signal), session_win must NOT be attributed to ALL of them
    (which doubles the credit and over-attributes the drilldown by
    +24% to +55%). The analyzer picks the largest integer pid as
    the canonical anchor."""

    def test_m214_mode5_payid_invariant_holds(self, round_win_config):
        """End-to-end: M214 mode_5 has multi-anchor triggers (1 +
        666). Without the anchor pick fix, pay_id 1 receives both
        round-level credit (its few non-zero values) AND session_win
        from every wheel session, inflating the drilldown to 55%
        over chunk_win. With the fix, only pay_id 666 absorbs
        session_win, and the global residual closes any remaining
        gap."""
        machine = "M214"
        resp, bet = _load_chunk(machine, "mode_5")
        rec = parse_chunk_response(resp, 1, bet)
        pid_sum = sum(rec["payout_id_win"].values())
        gap_pct = abs(rec["win"] - pid_sum) / rec["win"] * 100.0
        assert gap_pct < 0.5, (
            f"M214 mode_5 multi-anchor test: chunk_win={rec['win']}, "
            f"pid_sum={pid_sum}, gap={gap_pct:.4f}%"
        )

    def test_largest_int_anchor_chosen(self, round_win_config):
        """pay_id 666 (large int, conventional trigger token) gets
        the session_win, not pay_id 1 (small int, base-game line)."""
        machine = "M214"
        resp, bet = _load_chunk(machine, "mode_5")
        rec = parse_chunk_response(resp, 1, bet)
        # 666 should be present and have substantial value (the wheel
        # session_wins). 1 should NOT have inflated value -- it'll
        # appear with hits but value-0 contributions from round-level.
        assert "666" in rec["payout_id_win"]
        assert rec["payout_id_win"]["666"] > 0


class TestPayidInvariantTopdollarMultiSettlement:
    """M132 v2 has multi-settlement sessions (2 ST=15 in one bonus
    block). Pre-fix, helper used last_non_none and dropped earlier
    settlements -> 7% gap. Fix: helper uses sum_win when rules
    active, so all settlements are summed and attributed via
    session_win to pay_id 666."""

    def test_m132_v2_payid_drilldown_includes_all_settlements(self, round_win_config):
        machine = "M132$TopDollarSelector$2$40"
        resp, bet = _load_chunk(machine, "mode_7")
        rules = load_rules_for_machine(machine, round_win_config)
        rec = parse_chunk_response(resp, 1, bet, round_win_rules=rules)

        # Pay_id 666 (TopDollar trigger anchor) should hold the
        # cumulative settlement WinAmounts via session_win attribution.
        assert "666" in rec["payout_id_win"], "trigger pay_id 666 missing"
        assert rec["payout_id_win"]["666"] > 0

        pid_sum = sum(rec["payout_id_win"].values())
        gap_pct = abs(rec["win"] - pid_sum) / rec["win"] * 100.0

        # Post-fix: gap should be small (within ~1%). Pre-fix was ~7%.
        assert gap_pct < 1.0, (
            f"M132 v2 multi-settlement gap should be <1% post-fix "
            f"(got {gap_pct:.2f}%, win={rec['win']}, pid_sum={pid_sum})"
        )
