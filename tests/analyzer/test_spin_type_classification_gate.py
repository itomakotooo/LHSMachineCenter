"""CODE gate: a machine's declared SpinType `role` must be consistent with the
mechanism DERIVED from its own rawdata. Proves the gate catches mislabel drift
(inject-bug -> red) so a future onboarding cannot silently introduce the
ST13/ST125/ST137 class of error.

Per memory/feedback_integration_test_argv.md: a regression test is only credible if
it is shown to go RED on an injected bug and GREEN on the correct input.
"""
import glob
import json
import os
from collections import Counter, defaultdict

import pytest

from fresh_slotlab.analyzer.spin_type_classification_gate import check_machine
from fresh_slotlab.analyzer.spin_type_deriver import derive_spin_type_profile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_machine_rounds(machine_id):
    """Build rounds_by_st + prev_st_counts + has_paid_base from cached mode_1 rawdata."""
    from fresh_slotlab.analyzer.st_inventory import parse_rounds
    rounds_by_st = defaultdict(list)
    prev_by = defaultdict(Counter)
    has_base = False
    files = sorted(glob.glob(os.path.join(REPO, "rawdata", machine_id, "mode_1", "chunk_*.json")))
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        for robot in (d.get("response") or []):
            prev = None
            for r in parse_rounds(robot):
                st = str(r.get("SpinType"))
                rounds_by_st[st].append(r)
                try:
                    if float(r.get("CostCredits") or 0) > 0:
                        has_base = True
                except (TypeError, ValueError):
                    pass
                if prev is not None:
                    prev_by[st][prev] += 1
                prev = st
    return rounds_by_st, prev_by, has_base


# ── synthetic, deterministic logic checks (no rawdata) ──────────────────────────

def _normal_paid_rounds(n=200):
    return [{"SpinType": 1, "CostCredits": 1000, "BetAmount": 1000, "WinCredits": 500,
             "PayoutIdToWinAmount": {"5": 500}, "StopSymbolsByCol": "x"} for _ in range(n)]


def test_gate_passes_when_role_matches_derived():
    """role=paid_spin on a cost-bearing normal reel -> derived 'normal' is in the
    allowed set -> NO violation."""
    manifest = {"machine_id": "MTEST", "spin_types": {"1": {"role": "paid_spin"}}}
    violations = check_machine(manifest, {"1": _normal_paid_rounds()},
                               machine_has_paid_base=True, prev_st_counts={"1": Counter()})
    assert violations == [], violations


def test_gate_flags_role_mechanism_mismatch_INJECTED_BUG():
    """INJECT-BUG: declare role=state for a SpinType whose rawdata is a paid normal
    reel. The deriver says 'normal'; 'state' does NOT allow 'normal' -> the gate MUST
    flag it. (Revert role to paid_spin -> previous test shows GREEN.)"""
    manifest = {"machine_id": "MTEST", "spin_types": {"1": {"role": "state"}}}
    violations = check_machine(manifest, {"1": _normal_paid_rounds()},
                               machine_has_paid_base=True, prev_st_counts={"1": Counter()})
    assert len(violations) == 1, violations
    v = violations[0]
    assert v["declared_role"] == "state"
    assert v["derived_mechanism"] == "normal"
    assert v["kind"] == "role_mechanism_mismatch"


def test_deriver_distinguishes_hold_respin_by_coin_state():
    """The precise signal that resolved the M245/M268 agent disagreement: hold_respin
    requires PERSISTENT per-position coin JSON; a plain 'Respin N;' is respin."""
    hold = [{"SpinType": 125, "CostCredits": 0, "BetAmount": 1000, "WinCredits": 100,
             "ReMarks": 'Respin %d; {"500":[2804],"800":[2807]}' % i, "StopSymbolsByCol": "x"}
            for i in range(1, 11)]
    plain = [{"SpinType": 125, "CostCredits": 0, "BetAmount": 1000, "WinCredits": 0,
              "ReMarks": "Respin %d; " % i, "StopSymbolsByCol": "x"} for i in range(1, 11)]
    h = derive_spin_type_profile(hold, st="125", machine_has_paid_base=True)
    p = derive_spin_type_profile(plain, st="125", machine_has_paid_base=True)
    assert h["mechanism"] == "hold_respin", h
    assert p["mechanism"] == "respin", p


def test_deriver_accumulating_lock_is_confident_hold():
    """M252 ST125: the held set GROWS across the burst (1,5 -> 1,2,5 -> 1,2,4,5...) = a genuine
    hold-and-respin -> hold_respin at HIGH confidence."""
    rounds = []
    locks = ["1,5,", "1,5,", "1,2,5,", "1,2,4,5,", "1,2,4,5,8,"]
    for i, lk in enumerate(locks):
        rounds.append({"SpinType": 125, "CostCredits": 0, "BetAmount": 1000, "WinCredits": 0,
                       "ReMarks": "Respin %d; " % (i + 1), "StopSymbolsByCol": "x",
                       "LockReels": lk, "SpinTimes": 76})
    prof = derive_spin_type_profile(rounds, st="125", machine_has_paid_base=True)
    assert prof["mechanism"] == "hold_respin" and prof["confidence"] >= 0.8, prof


def test_deriver_constant_lock_is_respin_per_model_decision():
    """MODEL DECISION (owner 2026-06-18): a CONSTANT (non-accumulating) lock is a plain respin,
    NOT hold_respin (which requires an accumulating held set). So M227 ST13 'LockLines=2-' and
    M20 ST22/23 are both respin -- the boundary is now precise + fully data-derivable."""
    rounds = [{"SpinType": 13, "CostCredits": 0, "BetAmount": 1000, "WinCredits": (i % 2) * 200,
               "ReMarks": "", "StopSymbolsByCol": "x", "LockLines": "2-", "SpinTimes": 100 + i // 2}
              for i in range(20)]
    prof = derive_spin_type_profile(rounds, st="13", machine_has_paid_base=False)
    assert prof["mechanism"] == "respin" and prof["confidence"] >= 0.7, prof


def test_deriver_freespin_word_without_counter():
    """ST44: ReMarks 'FreeSpin' (no number) on cost=0 is still a freespin (v1 regex required
    a digit and mislabeled these as respin)."""
    rounds = [{"SpinType": 44, "CostCredits": 0, "BetAmount": 1000, "WinCredits": 300,
               "ReMarks": "FreeSpin", "StopSymbolsByCol": "x"} for _ in range(100)]
    prof = derive_spin_type_profile(rounds, st="44", machine_has_paid_base=True)
    assert prof["mechanism"] == "freespin", prof


def test_deriver_minigame_remark_on_paid_base_is_normal():
    """M124 ST1: a PAID base whose ReMarks say 'Trigger Minigame' is NOT a minigame (the
    minigame rule must require cost=0)."""
    rounds = [{"SpinType": 1, "CostCredits": 1000, "BetAmount": 1000, "WinCredits": 200,
               "PayoutIdToWinAmount": {"3": 200}, "ReMarks": "Trigger Minigame; ",
               "StopSymbolsByCol": "x"} for _ in range(100)]
    prof = derive_spin_type_profile(rounds, st="1", machine_has_paid_base=True)
    assert prof["mechanism"] == "normal", prof


def test_deriver_zero_win_milestone_is_state_not_respin():
    """M257 ST13: never-wins 'null'-ReMarks milestone with no held state -> state, NOT respin
    (a respin sometimes wins; 'null' is not empty so the empty-ReMarks respin path is skipped)."""
    rounds = [{"SpinType": 13, "CostCredits": 0, "BetAmount": 1000, "WinCredits": 0,
               "ReMarks": "null", "StopSymbolsByCol": "x", "LockLines": ""} for _ in range(80)]
    prof = derive_spin_type_profile(rounds, st="13", machine_has_paid_base=True)
    assert prof["mechanism"] == "state", prof


def test_deriver_paid_respin():
    """M148/M163: a COST-bearing reel re-spin marked 'respin' is a respin, not a base reel."""
    rounds = [{"SpinType": 147, "CostCredits": 1000, "BetAmount": 1000, "WinCredits": 300,
               "PayoutIdToWinAmount": {"4": 300}, "ReMarks": "respin", "StopSymbolsByCol": "x"}
              for _ in range(100)]
    prof = derive_spin_type_profile(rounds, st="147", machine_has_paid_base=True)
    assert prof["mechanism"] == "respin", prof


def test_deriver_trigger_marker_is_not_mechanism():
    """A 'TriggerFreespin' ReMarks on a COST-BEARING spin is a trigger marker, not the
    spin's own mechanism -> it stays 'normal', not 'freespin'."""
    rounds = [{"SpinType": 1, "CostCredits": 1000, "BetAmount": 1000, "WinCredits": 200,
               "PayoutIdToWinAmount": {"3": 200}, "ReMarks": "TriggerFreespin",
               "StopSymbolsByCol": "x"} for _ in range(100)]
    prof = derive_spin_type_profile(rounds, st="1", machine_has_paid_base=True)
    assert prof["mechanism"] == "normal", prof
    assert prof["economy"] == "paid", prof


# ── real-rawdata proof (one machine) ────────────────────────────────────────────

@pytest.mark.skipif(not glob.glob(os.path.join(REPO, "rawdata", "M14", "mode_1", "chunk_*.json")),
                    reason="M14 mode_1 rawdata not cached")
def test_gate_on_real_machine_then_injected_drift():
    """Real machine M14: as-declared it is gate-clean; flipping one ST's role to a
    wrong one makes the gate flag it (inject-bug -> red on real data)."""
    manifest = json.load(open(os.path.join(REPO, "configs", "machine_manifests", "M14.json"), encoding="utf-8"))
    rbs, prev_by, has_base = _load_machine_rounds("M14")
    clean = check_machine(manifest, rbs, machine_has_paid_base=has_base, prev_st_counts=prev_by)
    assert clean == [], f"M14 expected gate-clean, got {clean}"

    # INJECT: relabel M14's paid base ST as 'state' (a lie vs its rawdata)
    base_st = next(st for st, b in manifest["spin_types"].items() if b.get("role") == "paid_spin")
    bad = json.loads(json.dumps(manifest))
    bad["spin_types"][base_st]["role"] = "state"
    flagged = check_machine(bad, rbs, machine_has_paid_base=has_base, prev_st_counts=prev_by)
    assert any(v["spin_type"] == base_st for v in flagged), flagged
