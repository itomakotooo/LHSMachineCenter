"""Fleet-wide drift scan: our_total_win vs server_total_win per (machine, mode).

For each cached machine×mode, opens chunk_0001.json and computes:
  our_total_win  = sum of round.WinCredits across ALL rounds
  server_total_win = sum of analysisResult.TotalWin[*].WinCredits
  paid_win = sum of WinCredits on rounds with CostCredits>0
  winamount_total = sum of round.WinAmount on ALL rounds (settlement-style)
  paid_cost = sum of CostCredits on paid rounds

Per-SpinType breakdown lists (count, win_credits_sum, winamount_sum, has_payout_id_credit_count)
so we can classify each machine into:
  A) clean: |our - server| / server <= 0.01
  B) over-count phantom (our > server, paid + winamount == server)
  C) under-count missing (our < server, paid + winamount == server)
  D) other (M112-style sub-round duplication, etc.)

Output: TSV to stdout, sorted by drift_abs desc.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

RAWDATA = Path("rawdata")


def to_float(v, default=0.0):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def scan_pair(machine_mode: tuple[str, str]) -> dict:
    machine, mode = machine_mode
    chunk_dir = RAWDATA / machine / mode
    cf = chunk_dir / "chunk_0001.json"
    if not cf.exists():
        return {"machine": machine, "mode": mode, "error": "no_chunk_0001"}
    try:
        with open(cf, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"machine": machine, "mode": mode, "error": f"load_fail:{e}"}

    response = data.get("response")
    if not isinstance(response, list):
        return {"machine": machine, "mode": mode, "error": "no_response_list"}

    our_win = 0.0
    server_win = 0.0
    paid_win = 0.0
    paid_cost = 0.0
    winamount_total = 0.0
    total_rounds = 0
    paid_rounds_count = 0

    # Per-SpinType: (count, sum_wincredits, sum_winamount, with_pid_credit_count, with_pid_empty_count)
    st_stats: dict = defaultdict(lambda: {"count": 0, "wc_sum": 0.0, "wa_sum": 0.0, "pid_credit": 0, "pid_empty_or_none": 0, "is_paid_count": 0})

    for robot in response:
        if not isinstance(robot, dict):
            continue
        # Round-level
        rr = robot.get("roundResult")
        if isinstance(rr, str):
            try:
                rounds = json.loads(rr)
            except Exception:
                rounds = []
        elif isinstance(rr, list):
            rounds = rr
        else:
            rounds = []

        for r in rounds:
            if not isinstance(r, dict):
                continue
            total_rounds += 1
            st = r.get("SpinType")
            wc = to_float(r.get("WinCredits"), 0.0)
            wa = to_float(r.get("WinAmount"), 0.0)
            cost = to_float(r.get("CostCredits"), 0.0)
            our_win += wc
            winamount_total += wa
            is_paid = cost > 0
            if is_paid:
                paid_rounds_count += 1
                paid_win += wc
                paid_cost += cost
            pid = r.get("PayoutIdToWinAmount")
            has_pid_credit = isinstance(pid, dict) and any(to_float(v) > 0 for v in pid.values())
            pid_empty_or_none = (pid is None) or (isinstance(pid, dict) and not pid)

            s = st_stats[st]
            s["count"] += 1
            s["wc_sum"] += wc
            s["wa_sum"] += wa
            if is_paid:
                s["is_paid_count"] += 1
            if has_pid_credit:
                s["pid_credit"] += 1
            elif pid_empty_or_none:
                s["pid_empty_or_none"] += 1

        # analysisResult.TotalWin
        ar = robot.get("analysisResult")
        if isinstance(ar, str):
            try:
                analysis = json.loads(ar)
            except Exception:
                analysis = None
        elif isinstance(ar, dict):
            analysis = ar
        else:
            analysis = None

        if isinstance(analysis, dict):
            tw = analysis.get("TotalWin")
            if isinstance(tw, str):
                try:
                    tw = json.loads(tw)
                except Exception:
                    tw = None
            if isinstance(tw, dict):
                for v in tw.values():
                    if isinstance(v, dict):
                        server_win += to_float(v.get("WinCredits"), 0.0)

    drift = our_win - server_win
    drift_pct = (drift / server_win * 100.0) if server_win > 0 else 0.0
    paid_plus_wa = paid_win + winamount_total
    paid_plus_wa_drift = paid_plus_wa - server_win
    paid_plus_wa_drift_pct = (paid_plus_wa_drift / server_win * 100.0) if server_win > 0 else 0.0

    # Classify
    if abs(drift_pct) <= 1.0:
        cls = "A_clean"
    elif abs(paid_plus_wa_drift_pct) <= 1.0:
        cls = "B_overcount" if drift > 0 else "C_undercount"
    else:
        cls = "D_other"

    # Compact ST summary string
    st_summary_parts = []
    for st, s in sorted(st_stats.items(), key=lambda kv: (-kv[1]["count"], str(kv[0]))):
        tag = []
        if s["is_paid_count"] > 0 and s["is_paid_count"] == s["count"]:
            tag.append("paid")
        elif s["is_paid_count"] > 0:
            tag.append(f"paid={s['is_paid_count']}/{s['count']}")
        if s["wa_sum"] > 0:
            tag.append(f"WA={s['wa_sum']:.0f}")
        if s["wc_sum"] > 0 and s["pid_empty_or_none"] == s["count"]:
            tag.append("phantom_offer")
        elif s["wc_sum"] > 0 and s["pid_credit"] > 0:
            tag.append("pid_credited")
        st_summary_parts.append(f"ST{st}:n={s['count']},wc={s['wc_sum']:.0f}{(',' + ','.join(tag)) if tag else ''}")
    st_summary = " | ".join(st_summary_parts[:8])

    return {
        "machine": machine,
        "mode": mode,
        "total_rounds": total_rounds,
        "paid_rounds": paid_rounds_count,
        "our_win": our_win,
        "server_win": server_win,
        "paid_win": paid_win,
        "winamount_total": winamount_total,
        "paid_plus_wa": paid_plus_wa,
        "drift_pct": drift_pct,
        "paid_plus_wa_drift_pct": paid_plus_wa_drift_pct,
        "class": cls,
        "st_summary": st_summary,
    }


def discover_pairs() -> list[tuple[str, str]]:
    pairs = []
    for machine_dir in RAWDATA.iterdir():
        if not machine_dir.is_dir():
            continue
        for mode_dir in machine_dir.iterdir():
            if not mode_dir.is_dir() or not mode_dir.name.startswith("mode_"):
                continue
            if (mode_dir / "chunk_0001.json").exists():
                pairs.append((machine_dir.name, mode_dir.name))
    return pairs


def main():
    pairs = discover_pairs()
    print(f"# scanning {len(pairs)} (machine, mode) pairs", file=sys.stderr)
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(scan_pair, p): p for p in pairs}
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            if done % 100 == 0:
                print(f"#   progress: {done}/{len(pairs)}", file=sys.stderr)

    # Sort by abs drift desc, errors first
    results.sort(key=lambda r: (0 if r.get("error") else 1, -abs(r.get("drift_pct", 0.0))))

    # Emit summary first
    cls_counts = defaultdict(int)
    for r in results:
        if r.get("error"):
            cls_counts["E_error"] += 1
        else:
            cls_counts[r["class"]] += 1
    print("# class summary:")
    for k, v in sorted(cls_counts.items()):
        print(f"#   {k}: {v}")
    print()
    # TSV header
    cols = ["class", "machine", "mode", "drift_pct", "paid_plus_wa_drift_pct",
            "total_rounds", "our_win", "server_win", "paid_win", "winamount_total",
            "st_summary"]
    print("\t".join(cols))
    for r in results:
        if r.get("error"):
            print(f"E_error\t{r['machine']}\t{r['mode']}\t\t\t\t\t\t\t\t{r['error']}")
            continue
        row = [
            r["class"], r["machine"], r["mode"],
            f"{r['drift_pct']:.2f}",
            f"{r['paid_plus_wa_drift_pct']:.2f}",
            str(r["total_rounds"]),
            f"{r['our_win']:.0f}",
            f"{r['server_win']:.0f}",
            f"{r['paid_win']:.0f}",
            f"{r['winamount_total']:.0f}",
            r["st_summary"],
        ]
        print("\t".join(row))


if __name__ == "__main__":
    main()
