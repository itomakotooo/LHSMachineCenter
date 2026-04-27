"""For each RED machine identified by scan_payid_attribution_gap.py,
sample one chunk and dump 1-2 example rounds per culprit SpinType
so we can categorize the per-machine fix pattern.

Output: human-readable per-machine block listing:
  - Total rounds, by-SpinType count + win sum
  - Sample rounds (winning, with empty PayoutIdToWinAmount) per ST
  - Whether `WinCredits / BetAmount` is integer multiplier
  - Whether trigger ReMarks 'Trigger' present (selector hint)
  - 'move' / 'WheelSpin' / similar ReMarks (mechanic hint)
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAWDATA = REPO / "rawdata"

# Pulled from scan_payid_attribution_gap.py top RED rows
TARGETS = [
    ("M250", "mode_5"),
    ("M268", "mode_5"),
    ("M260", "mode_5"),
    ("M214", "mode_1"),
    ("M24", "mode_5"),
    ("M264", "mode_5"),
    ("M100", "mode_5"),
    ("M279", "mode_1"),  # known wheel
    ("M132$TopDollarSelector$2$40", "mode_7"),  # known multi-settlement
]


def inspect(machine: str, mode_dir: str):
    cf = RAWDATA / machine / mode_dir / "chunk_0001.json"
    if not cf.exists():
        print(f"### {machine} {mode_dir}: NO CHUNK")
        return
    with open(cf, "r", encoding="utf-8") as f:
        env = json.load(f)
    bet = int(env.get("_bet", 1000))
    resp = env["response"]

    by_st = defaultdict(lambda: {
        "n": 0, "n_win": 0, "win_sum": 0.0, "empty_pid_with_win": 0,
        "samples_with_win_no_pid": [], "remarks": Counter(),
        "win_over_bet_int_count": 0, "win_over_bet_frac_count": 0,
    })
    for robot in resp:
        if not isinstance(robot, dict):
            continue
        rr = robot.get("roundResult")
        if isinstance(rr, str):
            rounds = json.loads(rr)
        elif isinstance(rr, list):
            rounds = rr
        else:
            continue
        for r in rounds:
            if not isinstance(r, dict):
                continue
            st = r.get("SpinType")
            wc = float(r.get("WinCredits", 0) or 0)
            pid = r.get("PayoutIdToWinAmount")
            rmk = r.get("ReMarks", "")
            s = by_st[st]
            s["n"] += 1
            if wc > 0:
                s["n_win"] += 1
                s["win_sum"] += wc
                pid_empty = (pid is None) or (isinstance(pid, dict) and not pid)
                if pid_empty:
                    s["empty_pid_with_win"] += 1
                    if len(s["samples_with_win_no_pid"]) < 2:
                        # Compact sample
                        s["samples_with_win_no_pid"].append({
                            "ST": st, "win": wc,
                            "BetAmount": r.get("BetAmount"),
                            "CostCredits": r.get("CostCredits"),
                            "remarks": rmk[:60],
                            "win_over_bet": wc / bet if bet > 0 else None,
                            "stop_symbols": r.get("StopSymbolsByCol"),
                        })
                # Multiplier classification
                ratio = wc / bet
                if abs(ratio - round(ratio)) < 0.01:
                    s["win_over_bet_int_count"] += 1
                else:
                    s["win_over_bet_frac_count"] += 1
            if rmk:
                s["remarks"][rmk[:30]] += 1

    print(f"### {machine} {mode_dir}  bet={bet}")
    for st, s in sorted(by_st.items(), key=lambda kv: -kv[1]["empty_pid_with_win"]):
        if s["empty_pid_with_win"] == 0 and s["n_win"] == 0:
            continue
        marker = " <-- CULPRIT" if s["empty_pid_with_win"] > 0 else ""
        print(f"  ST={st}: n={s['n']}, win_n={s['n_win']}, win_sum={s['win_sum']:.0f}, "
              f"empty_pid_with_win={s['empty_pid_with_win']} "
              f"(int_x={s['win_over_bet_int_count']}, frac_x={s['win_over_bet_frac_count']}){marker}")
        if s["remarks"]:
            top_remarks = ", ".join(f"{rmk!r}({c})" for rmk, c in s["remarks"].most_common(3))
            print(f"    remarks: {top_remarks}")
        for sample in s["samples_with_win_no_pid"]:
            print(f"    sample: {sample}")
    print()


def main():
    for m, mode in TARGETS:
        inspect(m, mode)


if __name__ == "__main__":
    main()
