"""Gate: the paid-spin count reconciles with the distinct-SpinTimes count.

Analysis-correctness invariant (the value-agnostic companion to the our==server
WIN check, per the owner's framing "there is no wrong RTP, only a wrong analysis
method"):

    parse_chunk_response(chunk).paid_session_count
        == number of distinct SpinTimes in the chunk

A paid base spin == one distinct SpinTimes value (the server's spin index); bonus
rounds (freespin / respin / wheel / settlement) share the triggering spin's
SpinTimes. So the paid-unit count — the RTP denominator — MUST equal the number of
distinct SpinTimes, for EVERY machine, no matter where the upstream logs the cost.

This is exactly the bug that made M93 report RTP 10745% instead of 88.4%: M93
echoes the spin cost onto a feature round (ST82 DiamondManiaFreespin, CostCredits=
1000) while the paid base spin (ST13 LockReSpin) carries CostCredits=0, so the old
"paid ⟺ CostCredits>0" session count collapsed to 329 cost-bearing groups while the
true base-spin count is 40000. The generalized `cost_credits_unreliable` detection
in core/parser.py (flag when cost-bearing SpinTimes ⊊ all SpinTimes) fixes it; this
test LOCKS the invariant so a future cost-echo machine the detection misses fails
loudly instead of silently shipping a 100x-wrong denominator.

Coverage: the 5 machines a fleet sweep found diverging under the old detection
(M93 + the all-zero-CostCredits LockReSpin M10/M23/M131/M133) plus a diverse sample
of normal machines where the invariant has always held.

Inject-bug proof (per memory/feedback_enumerate_safety_paths.md): reverting the
parser detection generalization (restore the old `_all_zero_cost` condition) makes
M93's paid_session_count drop to 329 → this test goes RED for M93; re-applying the
fix → GREEN. (M10/M23/M131/M133 stay GREEN either way — the old all-zero condition
already flagged them.)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fresh_slotlab.analyzer.core.parser import parse_chunk_response

_ROOT = Path(__file__).resolve().parents[2]

# 5 cost-echo machines (the fix's blast radius) + diverse normal controls.
_MACHINES = [
    "M93", "M10", "M23", "M131", "M133",          # cost-echo / all-zero (the fix targets)
    "M15", "M24", "M43", "M104", "M262", "M279",  # normal controls (invariant always held)
]


def _first_chunk(machine: str) -> Path | None:
    chunks = sorted((_ROOT / "rawdata" / machine / "mode_1").glob("chunk_*.json"))
    return chunks[0] if chunks else None


def _distinct_spin_times(resp: list) -> int:
    """Sum, over robots, of the count of distinct SpinTimes values."""
    total = 0
    for robot in resp:
        rr = robot.get("roundResult")
        if isinstance(rr, str):
            rr = json.loads(rr)
        sts = {
            r.get("SpinTimes")
            for r in (rr or [])
            if isinstance(r, dict) and r.get("SpinTimes") is not None
        }
        total += len(sts)
    return total


@pytest.mark.parametrize("machine", _MACHINES)
def test_paid_session_count_equals_distinct_spin_times(machine: str):
    cf = _first_chunk(machine)
    if cf is None:
        pytest.skip(f"{machine}: no cached mode_1 chunk")
    d = json.loads(cf.read_text(encoding="utf-8"))
    rec = parse_chunk_response(d["response"], d["_chunk_index"], d["_bet"])
    paid = int(rec["paid_session_count"])
    distinct = _distinct_spin_times(d["response"])
    assert paid == distinct, (
        f"{machine}: paid_session_count={paid} != distinct SpinTimes={distinct}. "
        f"The paid-unit count diverges from the true base-spin count — a WRONG "
        f"ANALYSIS METHOD (the M93 cost-echo class), which makes the RTP denominator "
        f"wrong. Check the cost_credits_unreliable detection in core/parser.py "
        f"(it must flag machines whose cost-bearing SpinTimes do not cover every "
        f"base spin)."
    )
