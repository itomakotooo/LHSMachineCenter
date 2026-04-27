"""Fleet-wide payid attribution gap scan.

Complements scan_round_win_drift.py (chunk-level WinCredits sum vs
server). This one checks the SECOND invariant the user cares about:
  sum of payout_id_win[pid] across all pay_ids ≈ chunk_win

When that invariant breaks, the per-payid drilldown shows less RTP
than the headline (M279 case: 93.79 vs 97.76 = 3.96pp gap because
Wheel rounds have WinCredits but empty PayoutIdToWinAmount).

For each cached chunk_0001:
  total_win   = sum WinCredits across rounds (extract_round_win-style)
  pid_round   = sum PayoutIdToWinAmount values, scaled M209-style
  pid_session = sum trigger-session session_wins (compute_trigger_sessions)
  pid_total   = pid_round + pid_session
  gap         = total_win - pid_total
  gap_pct     = gap / total_win * 100

Classifies:
  GREEN_OK:        |gap_pct| < 0.5
  YELLOW_SMALL:    0.5 <= |gap_pct| < 5
  RED_LARGE:       |gap_pct| >= 5
  ALSO logs which SpinTypes contribute to unattributed wins
  (round.WinCredits > 0 with empty PayoutIdToWinAmount that's also
  not picked up by trigger_sessions)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAWDATA = REPO / "rawdata"
sys.path.insert(0, str(REPO))


def to_float(v, default=0.0):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def scan_pair(args):
    machine, mode_dir = args
    cf = RAWDATA / machine / mode_dir / "chunk_0001.json"
    if not cf.exists():
        return None
    try:
        with open(cf, "r", encoding="utf-8") as f:
            envelope = json.load(f)
    except Exception as e:
        return {"machine": machine, "mode": mode_dir, "error": str(e)}
    resp = envelope.get("response")
    if not isinstance(resp, list) or not resp:
        return {"machine": machine, "mode": mode_dir, "error": "no response"}
    bet = int(envelope.get("_bet", 1000))

    # Load round_win rules + trigger session helper.
    from fresh_slotlab.round_win import (
        extract_round_payouts,
        extract_round_win,
        load_rules_for_machine,
    )
    from fresh_slotlab.trigger_sessions import (
        _round_has_credited_win,
        compute_trigger_sessions,
    )
    config_path = REPO / "configs" / "machine_round_win_rules.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = None
    rules = load_rules_for_machine(machine, cfg)

    total_win = 0.0
    pid_round = 0.0
    pid_session = 0.0
    # Track unattributed-win rounds by SpinType to identify culprits.
    unattributed_by_st: dict = defaultdict(lambda: {"win": 0.0, "rounds": 0})

    for robot in resp:
        if not isinstance(robot, dict):
            continue
        rr = robot.get("roundResult")
        if isinstance(rr, str):
            try:
                rounds = json.loads(rr)
            except Exception:
                continue
        elif isinstance(rr, list):
            rounds = rr
        else:
            continue

        # Round-level win + Payout aggregation (mirrors parse_chunk_response).
        # Uses rule-aware extract_round_payouts so machines configured
        # with synthesize_pay_id rules see the synthetic 'st<N>' labels
        # contribute to pid_round.
        for r in rounds:
            if not isinstance(r, dict):
                continue
            win = extract_round_win(r, rules=rules)
            total_win += win
            pid_to_win = extract_round_payouts(r, rules=rules, ctx={"bet": bet})
            if pid_to_win:
                pay_sum = sum(to_float(v, 0.0) for v in pid_to_win.values())
                scale = 1.0
                if pay_sum > 0 and 0 < win < pay_sum:
                    scale = win / pay_sum
                for amt in pid_to_win.values():
                    pid_round += to_float(amt, 0.0) * scale
            else:
                # Empty / None payouts (rule explicitly suppressed via
                # {} OR no rule + raw round.PayoutIdToWinAmount empty)
                # AND win > 0 -> unattributed at the round level.
                # trigger_sessions may pick it up via session_win below.
                if win > 0:
                    st = r.get("SpinType")
                    unattributed_by_st[st]["win"] += win
                    unattributed_by_st[st]["rounds"] += 1

        # Trigger-session attribution: session_win goes onto trigger pay_ids.
        sessions = compute_trigger_sessions(rounds, round_win_rules=rules)
        for s in sessions:
            sw = float(s.get("session_win", 0.0) or 0.0)
            if sw == 0.0:
                continue
            pid_session += sw

    pid_total = pid_round + pid_session
    gap = total_win - pid_total
    gap_pct = (gap / total_win * 100.0) if total_win > 0 else 0.0

    if abs(gap_pct) < 0.5:
        cls = "GREEN_OK"
    elif abs(gap_pct) < 5.0:
        cls = "YELLOW_SMALL"
    else:
        cls = "RED_LARGE"

    # Sort culprit STs by win desc.
    culprits = sorted(
        ((st, v["rounds"], v["win"]) for st, v in unattributed_by_st.items()),
        key=lambda x: -x[2],
    )[:5]
    culprit_str = " | ".join(
        f"ST{st}:n={n},w={int(w)}" for st, n, w in culprits if w > 0
    )

    return {
        "machine": machine,
        "mode": mode_dir,
        "class": cls,
        "total_win": total_win,
        "pid_round": pid_round,
        "pid_session": pid_session,
        "pid_total": pid_total,
        "gap": gap,
        "gap_pct": gap_pct,
        "rule_count": len(rules),
        "culprits": culprit_str,
    }


def discover_pairs():
    pairs = []
    for mdir in RAWDATA.iterdir():
        if not mdir.is_dir():
            continue
        for modedir in mdir.iterdir():
            if not modedir.is_dir() or not modedir.name.startswith("mode_"):
                continue
            if (modedir / "chunk_0001.json").exists():
                pairs.append((mdir.name, modedir.name))
    return pairs


def main():
    pairs = discover_pairs()
    print(f"# scanning {len(pairs)} (machine, mode) pairs", file=sys.stderr)
    results = []
    with ProcessPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(scan_pair, p): p for p in pairs}
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            if r is not None:
                results.append(r)
            done += 1
            if done % 100 == 0:
                print(f"#  progress: {done}/{len(pairs)}", file=sys.stderr)

    cls_counts = defaultdict(int)
    for r in results:
        if r.get("error"):
            cls_counts["ERROR"] += 1
        else:
            cls_counts[r["class"]] += 1
    print("# class summary:")
    for k in sorted(cls_counts):
        print(f"#   {k}: {cls_counts[k]}")
    print()

    cls_order = {"RED_LARGE": 0, "YELLOW_SMALL": 1, "ERROR": 2, "GREEN_OK": 3}
    results.sort(key=lambda r: (
        cls_order.get(r.get("class", "ERROR"), 9),
        -abs(r.get("gap_pct", 0))
    ))

    cols = ["class", "machine", "mode", "rule_count", "gap_pct",
            "total_win", "pid_total", "gap", "culprits"]
    print("\t".join(cols))
    for r in results:
        if r.get("error"):
            print(f"ERROR\t{r['machine']}\t{r['mode']}\t\t\t\t\t\t{r['error']}")
            continue
        # Skip GREEN_OK rows -- noise.
        if r["class"] == "GREEN_OK":
            continue
        print("\t".join([
            r["class"], r["machine"], r["mode"],
            str(r["rule_count"]),
            f"{r['gap_pct']:.2f}",
            f"{r['total_win']:.0f}",
            f"{r['pid_total']:.0f}",
            f"{r['gap']:.0f}",
            r["culprits"],
        ]))


if __name__ == "__main__":
    main()
