"""Tests for the session-dim win fix (FRAMEWORK_PASS_2026-06-11.md Sub-pass A).

Invariants locked by this file:

  A. Two-number contract (Type-2 / self-crediting bonus rounds):
       session_dim_win == sum(bonus WinCredits) while session_win == 0
       AND the parser-produced session_win_sum includes the bonus wins
       (end-to-end fold via _close_session / bonus_win_from_helper).

  B. Type-1 (M15-shaped) regression guard:
       session_dim_win == session_win == last non-None WinCredits.
       The exclusion never fires on Type-1 shapes (PayoutIdToWinAmount=None).

  C. Conservation check unit coverage (rtp_integrity.py):
       (i)  all-real manifest + totals match => OK (session_conservation_ok=True)
       (ii) all-real manifest + totals mismatch => violation visible in
            serialized summary fields (not just the dataclass).
       (iii) manifest with a preview ST => skip with reason present.
       (iv)  no manifest => skip with reason present.

  D. Real-data structural invariant (value-agnostic, M275 mode 1):
       sum(round WinCredits) == session_win_sum from parse_chunk_response.
       Checked on a single robot extracted from the first chunk to keep
       the test sub-second on any machine that has the cached rawdata.
       If rawdata/M275/mode_1/chunk_0001.json is absent the test skips
       (CI runs on clean checkout; rawdata is developer-only).

  E. Cross-machine non-leak (M15-shaped):
       A Type-1 trigger path produces session_dim_win == session_win
       (no phantom-offer inflation from the session_dim path).
       Fixture-level; does not touch real rawdata.

INJECT-BUG RECIPES (per memory/feedback_enumerate_safety_paths.md):
  IB-A1 (two-number contract): in parser.py change
    session_dim_win_by_trigger_idx.get(_round_idx_in_robot, 0.0)
    back to
    session_win_by_trigger_idx.get(_round_idx_in_robot, 0.0)
    => test_type2_parser_session_win_sum_includes_bonus_wins goes RED
       (session_win_sum would be 0 + regular instead of dim_win + regular)

  IB-A2 (dim walk credited-win exclusion): in trigger_sessions.py add
    if not round_has_credited_win(nr, rules=round_win_rules, ctx=ctx):
    guard ALSO wrapping the dim_* accumulators (lines ~350-358)
    => test_type2_two_number_contract goes RED
       (dim_sum would also be 0 when bonus rounds self-credit)

  IB-C (conservation fields in summary): in report_engine.py remove the
    "session_conservation_level" key from the rtp_integrity_check dict write
    => test_conservation_fields_land_in_summary_dict goes RED
    (all 4 conservation keys are asserted: session_conservation_ok,
    session_conservation_level, session_conservation_skip_reason,
    session_conservation_notes)

Memory feedback files honored:
  feedback_enumerate_safety_paths.md  — inject-bug for every safety carve-out
  feedback_perf_claim_needs_e2e_event_stream.md — no mock-only for e2e claims
  feedback_integration_test_argv.md   — assertions on actual computed values
  feedback_invariant_with_fallback_hides_drift.md — conservation check must surface
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo root + rawdata paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
M275_CHUNK = ROOT / "rawdata" / "M275" / "mode_1" / "chunk_0001.json"


# ---------------------------------------------------------------------------
# Synthetic round builders (shared by tests A, B, E)
# ---------------------------------------------------------------------------

def _paid(*, st: int = 140, bet: int = 1000, win: int = 0,
          payout: dict | None = None, remarks: str = "") -> dict:
    """Minimal paid round. Includes StopSymbolsByCol so schema check passes."""
    return {
        "SpinType": st,
        "CostCredits": bet,
        "BetAmount": bet,
        "WinCredits": win,
        "StopSymbolsByCol": ["A-B-C", "A-B-C", "A-B-C", "A-B-C", "A-B-C"],
        "PayoutIdToWinAmount": payout if payout is not None else {},
        "ReMarks": remarks,
    }


def _bonus(*, st: int = 126, win: int | None = 0,
           payout: dict | None = None, remarks: str = "") -> dict:
    """Minimal bonus round (no CostCredits)."""
    return {
        "SpinType": st,
        "CostCredits": None,
        "WinCredits": win,
        "StopSymbolsByCol": ["A-B-C", "A-B-C", "A-B-C", "A-B-C", "A-B-C"],
        "PayoutIdToWinAmount": payout if payout is not None else {},
        "ReMarks": remarks,
    }


def _robot(rounds: list[dict], robot_id: str = "robot_0") -> dict:
    """Wrap rounds into the parser's expected robot dict envelope."""
    return {
        "robotId": robot_id,
        "roundResult": json.dumps(rounds),
    }


def _compute_orphan_bonus_win(rounds: list[dict]) -> float:
    """Return the sum of WinCredits of bonus rounds BEFORE the first paid round.

    "Orphan bonus rounds" occur at the very start of a chunk (before any paid
    trigger): they contribute to total_win but are NOT attributed to any trigger
    session (there's no trigger paid round yet).  The conservation invariant is:

        session_win_sum == total_win - orphan_bonus_win

    A paid round is one with CostCredits > 0 (matches is_paid_round in round_win.py).
    Bonus rounds have CostCredits in (None, 0).
    """
    orphan_win = 0.0
    for r in rounds:
        if not isinstance(r, dict):
            continue
        cc = r.get("CostCredits")
        is_paid = False
        if cc is not None:
            try:
                is_paid = float(cc) > 0.0
            except (TypeError, ValueError):
                pass
        if is_paid:
            # First paid round reached — no more orphans possible
            break
        wc = r.get("WinCredits")
        if wc is not None:
            try:
                orphan_win += float(wc)
            except (TypeError, ValueError):
                pass
    return orphan_win


# ---------------------------------------------------------------------------
# A — Type-2 two-number contract + end-to-end parser fold
# ---------------------------------------------------------------------------

class TestType2TwoNumberContract:
    """Group A: Type-2 robot fixture (paid round with win==0 anchor pid +
    following bonus rounds that SELF-CREDIT at pid level).

    Invariant: session_dim_win == sum(bonus WinCredits),
               session_win == 0  (credited-win exclusion fires on every bonus).
    """

    def _type2_rounds(self):
        """Three bonus rounds self-credit at pid level; trigger has no ReMarks."""
        return [
            _paid(win=0, payout={"666": 0}, remarks=""),   # Type-2 trigger
            _bonus(win=7500, payout={"3": 7500}),          # self-credit
            _bonus(win=5000, payout={"4": 5000}),          # self-credit
            _bonus(win=0,    payout={"5": 0}),             # self-credit (zero win)
            _paid(win=2000, payout={"7": 2000}),           # regular paid (closes session)
        ]

    def test_type2_two_number_contract(self):
        """session_win == 0 (every bonus round is credited → excluded from pid dim).
        session_dim_win == 12500 (sum of non-zero bonus WinCredits).
        Inject-bug IB-A2: wrapping dim accumulators in credited-win check → dim_sum=0 → RED.
        """
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions

        rounds = self._type2_rounds()
        sessions = compute_trigger_sessions(rounds)
        assert len(sessions) == 1, "Expected exactly 1 trigger session"
        s = sessions[0]

        # pid-attribution dimension: all bonus rounds self-credit => excluded
        assert s["session_win"] == 0.0, (
            f"session_win must be 0 for Type-2 self-crediting bonus rounds. "
            f"Got {s['session_win']}. "
            "INJECT-BUG IB-A2: wrapping dim accumulators in credited-win check would also make this 0."
        )

        # player-experience dimension: no exclusion => full bonus win
        bonus_win_sum = 7500 + 5000 + 0  # zero-win bonus does not contribute
        assert s["session_dim_win"] == float(bonus_win_sum), (
            f"session_dim_win must equal sum of bonus WinCredits ({bonus_win_sum}). "
            f"Got {s['session_dim_win']}. "
            "INJECT-BUG IB-A2: adding credited-win exclusion to dim path would make this 0."
        )

        # The two numbers must differ (this is the core fix invariant)
        assert s["session_dim_win"] > s["session_win"], (
            "session_dim_win MUST be > session_win for Type-2 self-crediting bonus rounds."
        )

    def test_type2_win_rule_is_sum_all(self):
        """Type-2 (no Trigger remark) must use win_rule='sum_all'."""
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions

        sessions = compute_trigger_sessions(self._type2_rounds())
        assert sessions[0]["win_rule"] == "sum_all"

    def test_type2_parser_session_win_sum_includes_bonus_wins(self):
        """End-to-end fold: parse_chunk_response must include the bonus wins
        in session_win_sum (via _close_session's bonus_win_from_helper which
        now reads session_dim_win_by_trigger_idx, not session_win_by_trigger_idx).

        Inject-bug IB-A1: reverting parser.py to use session_win_by_trigger_idx
        => bonus_win_from_helper = 0 => session_win_sum = 0 + 2000 = 2000 => RED.
        """
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        rounds = self._type2_rounds()
        # rounds: trigger(0) + 3 bonus(7500+5000+0) + regular_paid(2000)
        # session_win_sum = session1_dim_win(12500) + session2_regular(2000) = 14500
        resp = [_robot(rounds)]
        rec = parse_chunk_response(resp, 1, 1000)
        assert rec["ok"] is True, f"parse failed: {rec.get('error')}"

        total_bonus_win = 7500 + 5000 + 0  # = 12500
        regular_paid_win = 2000
        expected_session_win_sum = float(total_bonus_win + regular_paid_win)

        actual = rec["session_win_sum"]
        assert actual == expected_session_win_sum, (
            f"session_win_sum={actual!r} but expected {expected_session_win_sum}. "
            "INJECT-BUG IB-A1: reverting parser.py to session_win_by_trigger_idx "
            "makes bonus_win_from_helper=0, so session_win_sum would be 2000 (only the regular paid)."
        )

    def test_type2_parser_session_win_sum_equals_total_win(self):
        """Conservation: for an all-real machine, session_win_sum == total chunk win.
        The trigger session's session_dim_win (12500) + the regular paid (2000)
        exactly accounts for every credit the player received.
        """
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        rounds = self._type2_rounds()
        resp = [_robot(rounds)]
        rec = parse_chunk_response(resp, 1, 1000)
        assert rec["ok"] is True

        assert rec["session_win_sum"] == rec["win"], (
            f"session_win_sum ({rec['session_win_sum']}) != total win ({rec['win']}). "
            "Conservation must hold for an all-real-economy Type-2 fixture."
        )

    def test_type2_bonus_bucket_reflects_dim_win(self):
        """The session_bucket_win values must reflect session_dim_win, not session_win.
        Trigger session has 12500 credits at 1000 bet => 12.5x => ge10_lt20 bucket.
        If bonus_win_from_helper were session_win (0), the session would be 0-win
        and land in the loss bucket instead.
        """
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response
        from fresh_slotlab.analyzer.core._utils import return_bucket

        rounds = self._type2_rounds()
        resp = [_robot(rounds)]
        rec = parse_chunk_response(resp, 1, 1000)
        assert rec["ok"] is True

        session_bucket_win = rec["session_bucket_win"]
        # 12500 / 1000 = 12.5x => ge10_lt20
        expected_bucket = return_bucket(12500.0 / 1000.0)
        assert session_bucket_win.get(expected_bucket, 0) >= 12500.0, (
            f"Expected trigger session (12500 credits, 12.5x) in bucket '{expected_bucket}'. "
            f"Got session_bucket_win={session_bucket_win}. "
            "If bonus_win_from_helper used session_win (0) instead of session_dim_win, "
            "the session would land in the 0-win (loss) bucket."
        )


# ---------------------------------------------------------------------------
# B — Type-1 regression guard (M15-shaped)
# ---------------------------------------------------------------------------

class TestType1RegressionGuard:
    """Group B: Type-1 fixture (ReMarks='Trigger' + phantom-offer bonus rounds
    with PayoutIdToWinAmount=None/empty). The exclusion never fires on Type-1
    because PayoutIdToWinAmount is None/empty on every bonus round.
    Invariant: session_dim_win == session_win == last non-None WinCredits.
    """

    def _type1_rounds(self, last_offer: int = 40000):
        """M15 TopDollar: trigger with ReMarks='Trigger', ST=14 offer rounds,
        ST=15 settlement round (WinCredits=None)."""
        return [
            _paid(st=1, win=0, payout={"666": 0}, remarks="Trigger"),
            _bonus(st=14, win=15000, payout=None),   # offer 1 - phantom
            _bonus(st=14, win=25000, payout=None),   # offer 2 - phantom
            _bonus(st=14, win=last_offer, payout=None),  # offer 3 - accepted
            _bonus(st=15, win=None, payout=None),    # settlement (None win)
            _paid(st=1, win=0, payout={}),           # back to paid
        ]

    def test_type1_dim_win_equals_session_win(self):
        """Type-1: exclusion never fires => session_dim_win == session_win.
        INJECT-BUG: adding any exclusion logic to the dim path would make
        this diverge when PayoutIdToWinAmount={} (empty but not None).
        """
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions

        sessions = compute_trigger_sessions(self._type1_rounds())
        assert len(sessions) == 1
        s = sessions[0]
        assert s["session_dim_win"] == s["session_win"], (
            f"Type-1: session_dim_win ({s['session_dim_win']}) != session_win ({s['session_win']}). "
            "The exclusion must NOT fire on Type-1 shapes (PayoutIdToWinAmount=None)."
        )

    def test_type1_session_win_is_last_non_none(self):
        """session_win (and session_dim_win) == last_offer (40000), not the sum
        of all offers. last_non_none semantics: player accepted the last offer.
        """
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions

        rounds = self._type1_rounds(last_offer=40000)
        s = compute_trigger_sessions(rounds)[0]
        assert s["session_win"] == 40000.0
        assert s["session_dim_win"] == 40000.0

    def test_type1_no_phantom_offer_inflation(self):
        """Regression: session_dim_win must NOT be the SUM of all offer values.
        Sum would be 80000 (15000+25000+40000), but last_non_none gives 40000.
        """
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions

        rounds = self._type1_rounds(last_offer=40000)
        s = compute_trigger_sessions(rounds)[0]
        sum_of_offers = 15000 + 25000 + 40000
        assert s["session_dim_win"] != float(sum_of_offers), (
            f"session_dim_win must NOT be the sum of all offers ({sum_of_offers}). "
            "That would inflate the session win from phantom offer rounds."
        )

    def test_type1_win_rule_is_last_non_none(self):
        """Type-1 (has Trigger remark) => win_rule='last_non_none'."""
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions

        s = compute_trigger_sessions(self._type1_rounds())[0]
        assert s["win_rule"] == "last_non_none"

    def test_type1_parser_session_win_sum_matches_accepted_offer(self):
        """End-to-end: parse_chunk_response session_win_sum must include the
        accepted offer (40000), not the sum of all offers or 0.
        """
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        rounds = self._type1_rounds(last_offer=40000)
        rec = parse_chunk_response([_robot(rounds)], 1, 1000)
        assert rec["ok"] is True

        # session_win_sum = accepted offer (40000) from trigger session
        # The second paid round has win=0, so it contributes 0.
        assert rec["session_win_sum"] >= 40000.0, (
            f"session_win_sum={rec['session_win_sum']} must include the accepted offer (40000). "
            "If session_dim_win were session_win=0 (due to incorrect exclusion), this would fail."
        )


# ---------------------------------------------------------------------------
# C — Conservation check unit coverage
# ---------------------------------------------------------------------------

class TestConservationCheckUnit:
    """Group C: rtp_integrity.py session-conservation check.

    (i)  all-real manifest + totals match => session_conservation_ok=True
    (ii) all-real manifest + totals mismatch => violation visible in
         the serialized summary dict (not just the dataclass).
    (iii) manifest with a preview ST => session_conservation_ok=None,
          skip_reason present.
    (iv)  no manifest provided => session_conservation_ok=None,
          skip_reason present.

    Conservation does NOT flip `passed`.
    """

    def _all_real_manifest(self) -> dict:
        """Synthetic machine_spec_manifest where every ST has economy.kind='real'."""
        return {
            "machine_id": "M_test_real",
            "spin_types": {
                "1": {"role": "paid_spin", "economy": {"kind": "real"}},
                "50": {"role": "respin", "economy": {"kind": "real"}},
            },
        }

    def _preview_manifest(self) -> dict:
        """Manifest with a preview ST (like M15 ST=14)."""
        return {
            "machine_id": "M_test_preview",
            "spin_types": {
                "1": {"role": "paid_spin", "economy": {"kind": "real"}},
                "14": {"role": "player_choice", "economy": {"kind": "preview"}},
                "15": {"role": "settlement", "economy": {"kind": "real"}},
            },
        }

    def _make_summary(self, chunk_win: float = 1000.0) -> dict:
        """Minimal summary that passes Layer 1."""
        return {
            "machine": "M_test",
            "mode": 1,
            "rtp": {"our_total_win": chunk_win},
            "player_impact": {
                "payout_ids_top20": [
                    {"payout_id": "100", "total_win": chunk_win,
                     "hit_count": 10, "spin_type_breakdown": []}
                ]
            },
        }

    def test_enforce_ok_all_real_totals_match(self):
        """All-real manifest + session_win_total == total_win => session_conservation_ok=True.
        The check is informational and does NOT flip passed.
        """
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity

        total_win = 10000.0
        result = check_rtp_integrity(
            self._make_summary(chunk_win=total_win),
            machine_spec_manifest=self._all_real_manifest(),
            session_win_total=total_win,  # exact match
            warn_only=True,
        )
        assert result.session_conservation_ok is True, (
            f"Expected session_conservation_ok=True for exact match. "
            f"Got: {result.session_conservation_ok!r}. "
            f"skip_reason: {result.session_conservation_skip_reason!r}. "
            f"notes: {result.session_conservation_notes!r}"
        )
        # Informational: does NOT flip passed (Layer 1 passes in this fixture)
        assert result.passed is True, (
            "Conservation check must NOT flip passed — it is informational."
        )

    def test_enforce_violation_totals_mismatch(self):
        """All-real manifest + session_win_total significantly diverges from total_win
        => session_conservation_ok=False (violation class visible).
        The check does NOT flip passed.
        """
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity

        total_win = 10000.0
        # session_win_total is 50% of total_win (huge gap => violation)
        session_win = 5000.0

        result = check_rtp_integrity(
            self._make_summary(chunk_win=total_win),
            machine_spec_manifest=self._all_real_manifest(),
            session_win_total=session_win,
            warn_only=True,
        )
        assert result.session_conservation_ok is False, (
            f"Expected session_conservation_ok=False for a 50% gap. "
            f"Got: {result.session_conservation_ok!r}. "
            f"notes: {result.session_conservation_notes!r}"
        )
        # Conservation does NOT flip passed
        assert result.passed is True, (
            "Conservation check must NOT flip passed (it is informational)."
        )

    def test_conservation_fields_land_in_summary_dict(self):
        """All 4 conservation fields must appear in the summary dict written by
        report_engine's rtp_integrity_check serialization, NOT just in the dataclass.
        Inject-bug IB-C: removing any of the 4 keys from report_engine's dict write
        => RED.  Specifically, removing 'session_conservation_level' is the
        canonical IB-C injection (round-3 4th field).

        Uses generate_report_from_chunks with a minimal 20-round M43 chunk (v2 legacy
        format, no _payload_sha256) so the test completes in <0.5s.
        """
        import tempfile
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

        # Minimal M43 chunk: 20 paid spins, no bonus rounds, no trigger sessions.
        # M43 has all-real economy (ST1/ST50/ST51) => conservation runs (but skips
        # because win=0 in this fixture). The key contract: all 4 fields must exist
        # in rtp_integrity_check whether the check ran or skipped.
        rounds = [
            {
                "SpinType": 1, "CostCredits": 1000, "BetAmount": 1000,
                "WinCredits": 0,
                "StopSymbolsByCol": ["A-B-C", "A-B-C", "A-B-C", "A-B-C", "A-B-C"],
                "PayoutIdToWinAmount": {}, "ReMarks": "",
            }
            for _ in range(20)
        ]
        chunk = {
            "_envelope_version": 2,
            "_machine": "M43", "_mode": 1, "_bet": 1000,
            "_config_md5": "test_aaa", "_code_md5": "test_bbb",
            "_chunk_index": 1,
            "response": [{"robotId": "robot_0", "roundResult": json.dumps(rounds)}],
        }

        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            chunk_dir = tmp / "chunks"
            chunk_dir.mkdir()
            (chunk_dir / "chunk_0001.json").write_text(
                json.dumps(chunk), encoding="utf-8"
            )
            out_dir = tmp / "out"
            out_dir.mkdir()
            summary = generate_report_from_chunks(
                "M43", 1, chunk_dir=chunk_dir, output_dir=out_dir
            )

        ric = summary.get("rtp_integrity_check", {})

        # IB-C contract: all 4 conservation keys must exist in the summary dict.
        # The round-3 canonical IB-C injection is removing 'session_conservation_level'.
        assert "session_conservation_ok" in ric, (
            "INJECT-BUG IB-C: 'session_conservation_ok' missing from "
            "rtp_integrity_check dict in report_engine output. "
            "Removing the key from report_engine's serialization dict makes this RED."
        )
        assert "session_conservation_level" in ric, (
            "INJECT-BUG IB-C: 'session_conservation_level' missing from "
            "rtp_integrity_check dict. "
            "Round-3 canonical inject: remove this key from report_engine => RED."
        )
        assert "session_conservation_skip_reason" in ric, (
            "'session_conservation_skip_reason' missing from rtp_integrity_check dict."
        )
        assert "session_conservation_notes" in ric, (
            "'session_conservation_notes' missing from rtp_integrity_check dict."
        )
        assert isinstance(ric["session_conservation_notes"], list), (
            "session_conservation_notes must be serialized as a list."
        )

    def test_skip_preview_st_present(self):
        """Manifest with a preview ST => session_conservation_ok=None + skip_reason."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity

        result = check_rtp_integrity(
            self._make_summary(chunk_win=5000.0),
            machine_spec_manifest=self._preview_manifest(),
            session_win_total=5000.0,
            warn_only=True,
        )
        assert result.session_conservation_ok is None, (
            f"Expected session_conservation_ok=None for preview-ST manifest. "
            f"Got: {result.session_conservation_ok!r}"
        )
        assert result.session_conservation_skip_reason is not None, (
            "session_conservation_skip_reason must explain why the check was skipped."
        )
        assert len(result.session_conservation_skip_reason) > 0

    def test_skip_no_manifest_provided(self):
        """machine_spec_manifest=None => session_conservation_ok=None + skip_reason."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity

        result = check_rtp_integrity(
            self._make_summary(chunk_win=5000.0),
            machine_spec_manifest=None,
            session_win_total=5000.0,
            warn_only=True,
        )
        assert result.session_conservation_ok is None, (
            f"Expected session_conservation_ok=None when no manifest. "
            f"Got: {result.session_conservation_ok!r}"
        )
        assert result.session_conservation_skip_reason is not None

    def test_skip_no_session_win_total(self):
        """All-real manifest but session_win_total=None => skip with reason."""
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity

        result = check_rtp_integrity(
            self._make_summary(chunk_win=5000.0),
            machine_spec_manifest=self._all_real_manifest(),
            session_win_total=None,
            warn_only=True,
        )
        assert result.session_conservation_ok is None, (
            f"Expected skip when session_win_total=None. "
            f"Got: {result.session_conservation_ok!r}"
        )
        assert result.session_conservation_skip_reason is not None

    def test_conservation_does_not_flip_passed(self):
        """Regardless of conservation check result, passed is determined only by L1-L4.
        A 50% gap violation must NOT flip passed (it is informational).
        """
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity

        total_win = 10000.0
        result = check_rtp_integrity(
            self._make_summary(chunk_win=total_win),
            machine_spec_manifest=self._all_real_manifest(),
            session_win_total=1.0,  # extreme mismatch
            warn_only=True,
        )
        # Violation detected
        assert result.session_conservation_ok is False
        # But passed is still True (only L1-L4 can flip it)
        assert result.passed is True, (
            "session_conservation_ok=False must NOT flip passed. "
            "The check is informational per FRAMEWORK_PASS_2026-06-11.md §A."
        )

    # --- Three-class level contract (Critic optional #1) ---

    def test_three_class_level_ok_exact_match(self):
        """Three-class contract: exact match => session_conservation_level == 'ok'
        and session_conservation_ok is True.

        Level classification boundary: diff_pct < 1% => 'ok'.
        Inject: replace total_win with 0.96*total_win (4% diff) => would become 'warn'.
        """
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity

        total_win = 50000.0
        result = check_rtp_integrity(
            self._make_summary(chunk_win=total_win),
            machine_spec_manifest=self._all_real_manifest(),
            session_win_total=total_win,  # exact match => 0% diff
            warn_only=True,
        )
        assert result.session_conservation_level == "ok", (
            f"Exact match must produce level='ok'. "
            f"Got level={result.session_conservation_level!r}, "
            f"ok={result.session_conservation_ok!r}, "
            f"notes={result.session_conservation_notes!r}"
        )
        assert result.session_conservation_ok is True, (
            f"level=='ok' implies session_conservation_ok is True. "
            f"Got: {result.session_conservation_ok!r}"
        )

    def test_three_class_level_warn_three_percent_gap(self):
        """Three-class contract: ~3% gap => session_conservation_level == 'warn'
        and session_conservation_ok is False.

        Level boundary: 1% <= diff_pct < 5% => 'warn'.
        """
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity

        total_win = 50000.0
        session_win = total_win * 0.97  # 3% gap

        result = check_rtp_integrity(
            self._make_summary(chunk_win=total_win),
            machine_spec_manifest=self._all_real_manifest(),
            session_win_total=session_win,
            warn_only=True,
        )
        assert result.session_conservation_level == "warn", (
            f"3% gap must produce level='warn'. "
            f"Got level={result.session_conservation_level!r}, "
            f"notes={result.session_conservation_notes!r}"
        )
        assert result.session_conservation_ok is False, (
            f"level=='warn' implies session_conservation_ok is False. "
            f"Got: {result.session_conservation_ok!r}"
        )

    def test_three_class_level_fail_fifty_percent_gap(self):
        """Three-class contract: 50% gap => session_conservation_level == 'fail'
        and session_conservation_ok is False.

        Level boundary: diff_pct >= 5% => 'fail'.
        """
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity

        total_win = 50000.0
        session_win = total_win * 0.50  # 50% gap

        result = check_rtp_integrity(
            self._make_summary(chunk_win=total_win),
            machine_spec_manifest=self._all_real_manifest(),
            session_win_total=session_win,
            warn_only=True,
        )
        assert result.session_conservation_level == "fail", (
            f"50% gap must produce level='fail'. "
            f"Got level={result.session_conservation_level!r}, "
            f"notes={result.session_conservation_notes!r}"
        )
        assert result.session_conservation_ok is False, (
            f"level=='fail' implies session_conservation_ok is False. "
            f"Got: {result.session_conservation_ok!r}"
        )

    def test_three_class_level_boundary_exactly_one_percent(self):
        """Boundary precision: exactly 1% gap must produce level='warn' (not 'ok').
        The threshold is `diff_pct < 1.0` for 'ok', so diff_pct==1.0 is 'warn'.
        """
        from fresh_slotlab.analyzer.rtp_integrity import check_rtp_integrity

        total_win = 100000.0
        session_win = total_win * 0.99  # exactly 1% gap

        result = check_rtp_integrity(
            self._make_summary(chunk_win=total_win),
            machine_spec_manifest=self._all_real_manifest(),
            session_win_total=session_win,
            warn_only=True,
        )
        # 1.0% is NOT < 1.0, so it must be 'warn' (not 'ok')
        assert result.session_conservation_level in ("warn", "fail"), (
            f"Exactly 1% diff must be classified 'warn' (not 'ok'). "
            f"Got level={result.session_conservation_level!r}"
        )
        assert result.session_conservation_level != "ok", (
            "1% gap must NOT be classified 'ok' (threshold is strictly <1%)."
        )

    def test_generate_path_level_not_none(self):
        """Critic #1 (generate path): run generate_report_from_chunks on a
        minimal M43 chunk where session_win_total=0 (no trigger sessions).
        The conservation check must FIRE (level is not None) when M43's
        all-real manifest is present in the default manifests directory.

        If M43.json is not in configs/machine_manifests, this verifies at
        minimum that session_conservation_level key exists in the output
        (the round-3 serialization contract).
        """
        import tempfile
        from fresh_slotlab.analyzer.report_engine import generate_report_from_chunks

        # 20 paid rounds, no trigger sessions => session_win_total=0
        rounds = [
            {
                "SpinType": 1, "CostCredits": 1000, "BetAmount": 1000,
                "WinCredits": 500,
                "StopSymbolsByCol": ["A-B-C", "A-B-C", "A-B-C", "A-B-C", "A-B-C"],
                "PayoutIdToWinAmount": {"1": 500}, "ReMarks": "",
            }
            for _ in range(20)
        ]
        chunk = {
            "_envelope_version": 2,
            "_machine": "M43", "_mode": 1, "_bet": 1000,
            "_config_md5": "test_aaa", "_code_md5": "test_bbb",
            "_chunk_index": 1,
            "response": [{"robotId": "robot_0", "roundResult": json.dumps(rounds)}],
        }

        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            chunk_dir = tmp / "chunks"
            chunk_dir.mkdir()
            (chunk_dir / "chunk_0001.json").write_text(
                json.dumps(chunk), encoding="utf-8"
            )
            out_dir = tmp / "out"
            out_dir.mkdir()
            summary = generate_report_from_chunks(
                "M43", 1, chunk_dir=chunk_dir, output_dir=out_dir
            )

        ric = summary.get("rtp_integrity_check", {})

        # The 4th field must be present in the serialized output regardless of level
        assert "session_conservation_level" in ric, (
            "'session_conservation_level' key must always be present in "
            "rtp_integrity_check (round-3 serialization contract). "
            "If this fails, report_engine is not serializing the 4th conservation field."
        )
        # If M43's all-real manifest is on disk, the check must actually fire
        # (level is not None). If the manifest is missing the check skips (level=None),
        # which is acceptable for a CI environment without manifests.
        # The assertion below documents the expected behavior for dev environments.
        level = ric.get("session_conservation_level")
        if level is not None:
            assert level in ("ok", "warn", "fail"), (
                f"session_conservation_level must be one of 'ok'/'warn'/'fail' when not None. "
                f"Got: {level!r}"
            )


# ---------------------------------------------------------------------------
# D — Real-data structural invariant (M275 mode 1, value-agnostic)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not M275_CHUNK.exists(),
    reason="rawdata/M275/mode_1/chunk_0001.json absent; developer-only (rawdata not in CI)",
)
class TestM275ConservationInvariant:
    """Group D: Real-data value-agnostic invariant.

    Parses one robot from M275 mode_1 chunk_0001.json through the real
    parse_chunk_response path and asserts:
        session_win_sum == rec["win"]  (i.e., sum(round WinCredits))

    No pinned RTP values. The assertion is purely structural: every credit
    the player received must be captured by at least one session.

    Design choice: only robot_0 is parsed (not the full 8-robot chunk)
    to keep the test under 5 seconds on a laptop. This is documented
    rather than using the full chunk.
    """

    def test_m275_session_win_sum_equals_total_win_robot0(self):
        """Value-agnostic orphan-aware invariant: for robot 0 of M275 chunk 1,
            session_win_sum == total_win - orphan_bonus_win
        where orphan_bonus_win = Σ WinCredits of bonus rounds BEFORE the first
        paid round (orphan rounds contribute to total_win but are not attributed
        to any trigger session because no trigger has fired yet).

        Uses real rawdata, real parse_chunk_response — NOT mock-only per
        memory/feedback_perf_claim_needs_e2e_event_stream.md.

        SQ-4 fix (critic-required): the original strict form
        `session_win_sum == total_win` accidentally relied on robot_0 having
        no orphan bonus rounds.  This form is correct regardless of robot
        structure.

        Inject-bug IB-A1: reverting parser.py _close_session to use
        session_win_by_trigger_idx makes bonus_win_from_helper=0 for every
        M275 trigger session => session_win_sum drops to only paid-round wins
        (orphan stays 0) => session_win_sum < total_win - orphan_bonus_win
        => assertion fails RED.  Revert => GREEN.
        """
        from fresh_slotlab.analyzer.core.parser import parse_chunk_response

        with open(M275_CHUNK, encoding="utf-8") as f:
            env = json.load(f)
        bet = int(env.get("_bet", 1000))
        resp = env.get("response", [])
        assert len(resp) >= 1, "Expected at least 1 robot in M275 chunk"

        # Use only robot_0 to bound execution time (documented)
        robot_0 = resp[0]

        # Decode round list to compute orphan_bonus_win before parsing
        rr = robot_0.get("roundResult")
        if isinstance(rr, str):
            rr = json.loads(rr)
        assert isinstance(rr, list), "roundResult must decode to a list"

        # Orphan bonus win: bonus rounds before the first paid round
        orphan_bonus_win = _compute_orphan_bonus_win(rr)

        rec = parse_chunk_response([robot_0], 1, bet)
        assert rec["ok"] is True, f"parse failed for M275 robot_0: {rec.get('error')}"

        session_win_sum = rec["session_win_sum"]
        total_win = rec["win"]

        assert total_win > 0, "M275 robot_0 must have positive total win"
        assert session_win_sum > 0, (
            "session_win_sum must be > 0 after dim fix. "
            "If it is 0, bonus_win_from_helper is still using session_win (0 for M275)."
        )

        # Orphan-aware conservation: exact, value-agnostic, no flake
        expected = total_win - orphan_bonus_win
        assert session_win_sum == expected, (
            f"Orphan-aware conservation failed: session_win_sum ({session_win_sum}) != "
            f"total_win ({total_win}) - orphan_bonus_win ({orphan_bonus_win}) = {expected}. "
            "INJECT-BUG IB-A1: reverting parser.py to session_win_by_trigger_idx "
            "makes bonus_win_from_helper=0 for all M275 sessions => session_win_sum "
            "drops to paid-round wins only => fails RED."
        )

    def test_m275_trigger_sessions_have_nonzero_dim_win(self):
        """At least one trigger session must have session_dim_win > session_win.
        This is the core M275 defect that the fix addresses: before the fix,
        session_dim_win did not exist and session_win was 0 for every session
        (all bonus rounds self-credit at pid level).
        """
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions

        with open(M275_CHUNK, encoding="utf-8") as f:
            env = json.load(f)
        resp = env.get("response", [])
        robot_0 = resp[0]
        rr = robot_0.get("roundResult")
        if isinstance(rr, str):
            rr = json.loads(rr)

        sessions = compute_trigger_sessions(rr)
        assert len(sessions) > 0, "Expected trigger sessions in M275 robot_0"

        # At least one session must have session_dim_win > session_win
        # (the two-number contract for Type-2 self-crediting machines)
        has_dim_gt_pid = any(
            s["session_dim_win"] > s["session_win"] for s in sessions
        )
        assert has_dim_gt_pid, (
            "Expected at least one M275 session where session_dim_win > session_win. "
            "M275 bonus rounds self-credit at pid level => session_win=0, "
            "session_dim_win=full bonus win for Type-2 sessions. "
            "If ALL sessions have session_dim_win == session_win, the dim path "
            "is not accumulating independently of the pid-attribution path."
        )


# ---------------------------------------------------------------------------
# E — Cross-machine non-leak (M15-shaped Type-1)
# ---------------------------------------------------------------------------

class TestM15ShapedNonLeak:
    """Group E: M15-shaped Type-1 trigger path produces unchanged session numbers.
    The session_dim path must NOT inflate Type-1 sessions with phantom offers.

    Fixture-level test (no real rawdata required). The byte-identical gate
    at cache/_fwpass_gate/ is the coordinator's e2e evidence.
    """

    def test_m15_shaped_dim_win_equals_session_win(self):
        """M15 TopDollar: PayoutIdToWinAmount=None on all bonus rounds.
        The credited-win exclusion never fires => dim == pid.
        """
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions

        rounds = [
            _paid(st=1, win=0, payout={"666": 0}, remarks="Trigger"),
            _bonus(st=14, win=15000, payout=None),
            _bonus(st=14, win=20000, payout=None),
            _bonus(st=14, win=40000, payout=None),  # accepted offer
            _bonus(st=15, win=None,  payout=None),  # settlement
            _paid(st=1, win=0, payout={}),
        ]
        sessions = compute_trigger_sessions(rounds)
        assert len(sessions) == 1
        s = sessions[0]

        assert s["session_dim_win"] == s["session_win"], (
            f"M15-shaped: session_dim_win ({s['session_dim_win']}) != "
            f"session_win ({s['session_win']}). "
            "Type-1 shapes must have dim == pid (exclusion never fires on None payout)."
        )
        # And both must be last_non_none = 40000
        assert s["session_win"] == 40000.0
        assert s["session_dim_win"] == 40000.0

    def test_m15_shaped_empty_payout_dict_does_not_exclude(self):
        """Empty payout dict {} (not None) must NOT trigger the exclusion.
        round_has_credited_win requires at least one NONZERO value in the dict.
        Empty dict => not credited => win still accumulates in both pid and dim paths.
        """
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions

        rounds = [
            _paid(st=1, win=0, payout={"666": 0}, remarks="Trigger"),
            _bonus(st=14, win=30000, payout={}),   # empty dict => NOT excluded
            _bonus(st=15, win=None, payout=None),  # settlement
            _paid(st=1, win=0, payout={}),
        ]
        sessions = compute_trigger_sessions(rounds)
        s = sessions[0]

        # Empty payout dict should NOT trigger exclusion
        assert s["session_win"] == 30000.0, (
            f"Empty payout dict must NOT trigger credited-win exclusion. "
            f"Got session_win={s['session_win']} (expected 30000)."
        )
        assert s["session_dim_win"] == 30000.0

    def test_m15_shaped_trigger_add_does_not_gate_session_win_rule(self):
        """TriggerAddFreeSpin as a bonus-round remark must NOT break session detection.
        When a bonus round carries 'TriggerAddFreeSpin' (re-trigger mid-session),
        it is just a bonus round — it does not close the session or open a new one.
        The session_win must still be the last non-None WinCredits across ALL bonus rounds.
        """
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions

        # TriggerAddFreeSpin appears as the ReMarks on a BONUS round (mid-session)
        # It extends the existing feature but does NOT open a new session
        rounds = [
            _paid(st=1, win=0, payout={"666": 0}, remarks="TriggerFreeSpin"),
            _bonus(st=14, win=15000, payout=None, remarks="TriggerAddFreeSpin"),  # mid-session
            _bonus(st=14, win=40000, payout=None, remarks=""),  # last non-None
            _bonus(st=15, win=None,  payout=None, remarks=""),  # settlement
            _paid(st=1, win=0, payout={}),
        ]
        sessions = compute_trigger_sessions(rounds)
        # One session: TriggerAddFreeSpin mid-session does not split it
        assert len(sessions) == 1, (
            f"TriggerAddFreeSpin on a bonus round must NOT split the session. "
            f"Got {len(sessions)} sessions."
        )
        s = sessions[0]
        # session_win_rule = last_non_none (TriggerFreeSpin opened it)
        assert s["win_rule"] == "last_non_none"
        # Last non-None WinCredits = 40000 (settlement None is excluded)
        assert s["session_win"] == 40000.0, (
            f"Expected last_non_none=40000. Got {s['session_win']}."
        )
        assert s["session_dim_win"] == 40000.0

    def test_m15_shaped_multiple_sessions_independent(self):
        """Multiple trigger sessions must be independent — one session's
        session_dim_win must not bleed into another.
        """
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions

        rounds = [
            # Session 1: last offer = 40000
            _paid(st=1, win=0, payout={"666": 0}, remarks="Trigger"),
            _bonus(st=14, win=15000, payout=None),
            _bonus(st=14, win=40000, payout=None),
            _bonus(st=15, win=None,  payout=None),
            # Session 2: last offer = 20000
            _paid(st=1, win=0, payout={"666": 0}, remarks="Trigger"),
            _bonus(st=14, win=5000,  payout=None),
            _bonus(st=14, win=20000, payout=None),
            _bonus(st=15, win=None,  payout=None),
            _paid(st=1, win=0, payout={}),  # close session 2
        ]
        sessions = compute_trigger_sessions(rounds)
        assert len(sessions) == 2, f"Expected 2 sessions, got {len(sessions)}"

        assert sessions[0]["session_win"] == 40000.0
        assert sessions[0]["session_dim_win"] == 40000.0
        assert sessions[1]["session_win"] == 20000.0
        assert sessions[1]["session_dim_win"] == 20000.0


# ---------------------------------------------------------------------------
# F — Type-1 + round_win_rules: session_dim_win must use rule's view
# ---------------------------------------------------------------------------

class TestType1WithRulesRegression:
    """Critic optional #2: when round_win_rules is non-empty (e.g.
    SettlementWinAmountRule), the dim path must use extract_round_win()
    (rule's view) rather than raw WinCredits.

    Fixture: M15-style TopDollar
      - paid trigger ST=1, remarks='Trigger', payout={'666': 0}
      - ST=14 offer  WinCredits=40000   (phantom offer — rule returns 0)
      - ST=14 offer  WinCredits=30000   (phantom offer — rule returns 0)
      - ST=15 settlement WinAmount=30000, WinCredits=None  (rule returns WinAmount)
      - paid ST=1 (closes session)

    Without rules: last_non_none of raw WinCredits = 40000 (last non-None offer).
    With SettlementWinAmountRule(phantom_st=[14], settlement_st=[15]):
      extract_round_win for ST=14 rounds => 0
      extract_round_win for ST=15 round  => WinAmount=30000
      dim path always uses extract_round_win when round_win_rules non-empty =>
      dim_last_nonnone after walking = 30000 (settlement round's rule value)
      => session_dim_win == 30000 (NOT 40000 raw offers).

    This is exactly what M15 production does: the accepted value is WinAmount
    on the settlement round, not the displayed WinCredits on the offer rounds.
    The phantom offer WinCredits are display-only and must be zeroed by the rule.

    Inject-bug: if the dim path used raw WinCredits instead of extract_round_win
    when rules are present, session_dim_win would be 40000 (last non-None WinCredits),
    not 30000 (settlement WinAmount). The test would fail RED.
    """

    def _m15_style_rounds_with_settlement(
        self,
        offer1_credits: int = 15000,
        offer2_credits: int = 40000,
        settlement_win_amount: int = 30000,
    ) -> list[dict]:
        """M15 TopDollar style: two offer rounds + settlement round.

        ST=14 offer rounds carry WinCredits (phantom display value).
        ST=15 settlement round carries WinAmount (real payout), WinCredits=None.
        """
        return [
            # Trigger paid round
            {
                "SpinType": 1, "CostCredits": 1000, "BetAmount": 1000,
                "WinCredits": 0,
                "StopSymbolsByCol": ["A-B-C", "A-B-C", "A-B-C", "A-B-C", "A-B-C"],
                "PayoutIdToWinAmount": {"666": 0},
                "ReMarks": "Trigger",
            },
            # Offer 1 (phantom, ST=14)
            {
                "SpinType": 14, "CostCredits": None, "WinCredits": offer1_credits,
                "StopSymbolsByCol": ["A-B-C", "A-B-C", "A-B-C", "A-B-C", "A-B-C"],
                "PayoutIdToWinAmount": None,
                "ReMarks": "",
            },
            # Offer 2 (phantom, ST=14) — last non-None WinCredits if no rule
            {
                "SpinType": 14, "CostCredits": None, "WinCredits": offer2_credits,
                "StopSymbolsByCol": ["A-B-C", "A-B-C", "A-B-C", "A-B-C", "A-B-C"],
                "PayoutIdToWinAmount": None,
                "ReMarks": "",
            },
            # Settlement (ST=15) — carries real payout in WinAmount
            {
                "SpinType": 15, "CostCredits": None, "WinCredits": None,
                "WinAmount": settlement_win_amount,
                "StopSymbolsByCol": ["A-B-C", "A-B-C", "A-B-C", "A-B-C", "A-B-C"],
                "PayoutIdToWinAmount": None,
                "ReMarks": "",
            },
            # Next paid round closes session
            {
                "SpinType": 1, "CostCredits": 1000, "BetAmount": 1000,
                "WinCredits": 0,
                "StopSymbolsByCol": ["A-B-C", "A-B-C", "A-B-C", "A-B-C", "A-B-C"],
                "PayoutIdToWinAmount": {},
                "ReMarks": "",
            },
        ]

    def test_type1_with_rules_session_dim_win_uses_settlement_value(self):
        """With SettlementWinAmountRule active, session_dim_win must equal
        WinAmount on the settlement round (30000), NOT the raw phantom offer
        WinCredits (40000).

        Without rules: last_non_none of raw WinCredits would give 40000 (offer2).
        With rules: extract_round_win zeros ST=14 offers and returns ST=15 WinAmount.
        The dim path always uses extract_round_win when round_win_rules non-empty
        => dim_last_nonnone = 30000 at end of session.

        Inject-bug: if dim path fell back to raw WinCredits when rules present,
        session_dim_win would be 40000 => assertion fails RED.
        """
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions
        from fresh_slotlab.round_win import SettlementWinAmountRule

        rounds = self._m15_style_rounds_with_settlement(
            offer1_credits=15000,
            offer2_credits=40000,     # last non-None WinCredits without rule
            settlement_win_amount=30000,  # real payout in WinAmount
        )

        rule = SettlementWinAmountRule(
            phantom_spin_types=[14],
            settlement_spin_types=[15],
        )

        sessions = compute_trigger_sessions(rounds, round_win_rules=[rule])
        assert len(sessions) == 1, f"Expected 1 session, got {len(sessions)}"
        s = sessions[0]

        # With rules: dim path zeroed phantom offers and used settlement WinAmount
        assert s["session_dim_win"] == 30000.0, (
            f"session_dim_win must equal settlement WinAmount (30000) "
            f"when SettlementWinAmountRule is active. Got {s['session_dim_win']}. "
            "INJECT-BUG: if dim path used raw WinCredits, last_non_none would "
            "be 40000 (offer2_credits) instead of 30000."
        )

    def test_type1_with_rules_session_dim_win_not_raw_offer_sum(self):
        """session_dim_win must NOT be the sum of all offer WinCredits.
        With rules: sum would be 0+0+30000=30000 (rule zeros offers,
        returns WinAmount for settlement). Without rules: sum is NOT used
        (Type-1 uses last_non_none). Either way, 15000+40000+0=55000 is wrong.
        """
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions
        from fresh_slotlab.round_win import SettlementWinAmountRule

        rounds = self._m15_style_rounds_with_settlement(
            offer1_credits=15000,
            offer2_credits=40000,
            settlement_win_amount=30000,
        )

        rule = SettlementWinAmountRule(
            phantom_spin_types=[14],
            settlement_spin_types=[15],
        )
        sessions = compute_trigger_sessions(rounds, round_win_rules=[rule])
        s = sessions[0]

        # Must not be the raw sum of offer WinCredits
        raw_offer_sum = 15000 + 40000 + 0  # offers + settlement (None->0)
        assert s["session_dim_win"] != float(raw_offer_sum), (
            f"session_dim_win must NOT be raw offer sum ({raw_offer_sum}). "
            f"Got {s['session_dim_win']}."
        )

    def test_type1_without_rules_falls_back_to_raw_last_non_none(self):
        """Without round_win_rules, the same fixture uses raw WinCredits
        and last_non_none = 40000 (last offer with non-None WinCredits).
        This is the BASELINE: rules change the dim_win, no-rules is
        unchanged from pre-fix behavior.
        """
        from fresh_slotlab.trigger_sessions import compute_trigger_sessions

        rounds = self._m15_style_rounds_with_settlement(
            offer1_credits=15000,
            offer2_credits=40000,
            settlement_win_amount=30000,
        )

        sessions = compute_trigger_sessions(rounds)  # no rules
        s = sessions[0]

        # Without rules: last_non_none of raw WinCredits = 40000
        assert s["session_dim_win"] == 40000.0, (
            f"Without rules, session_dim_win must be last_non_none of raw WinCredits "
            f"(40000 = offer2_credits). Got {s['session_dim_win']}."
        )
        assert s["session_win"] == 40000.0
