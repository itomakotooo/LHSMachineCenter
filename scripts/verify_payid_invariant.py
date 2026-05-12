"""End-to-end fleet verification of the payid attribution invariant.

For each cached chunk, runs parse_chunk_response (rule-aware path)
and checks two invariants:

  1. **Total accounting**: |chunk_win - sum(payout_id_win.values())|
     / chunk_win < 0.5% (gap_pct -- closes when the fallback
     synthesizer absorbs whatever the named-pid path left over).
  2. **Attribution quality**: fallback_pct = sum_of_synthetic_pids /
     chunk_win < 2.0% (the synthetic ``_unattributed_st<N>`` /
     ``_unattributed_residual`` catch-alls should be near-empty when
     per-machine rules cover every trigger path).

Invariant 1 alone hides systematic mis-attribution -- a machine where
EVERY bonus win lands in ``_unattributed_st<N>`` still scores
gap_pct=0 because the fallback adds back exactly what the named pids
missed. Invariant 2 was added 2026-05-12 after the M274 BCM cycle
trigger investigation surfaced 55 of 117 cached BCM (machine, mode)
pairs hiding 0.5--100% fallback shares behind GREEN_OK.

Output: TSV. Classes (sorted highest-severity first in the report):
  RED_GAP        -- gap_pct >= 5 (real arithmetic gap)
  RED_FALLBACK   -- gap_pct < 5 but fallback_pct >= 5
                    (structural mis-attribution masked by synthesizer)
  YELLOW_SMALL   -- 0.5 <= gap_pct < 5
  YELLOW_FALLBACK-- gap_pct < 0.5 but fallback_pct >= 2
                    (low-grade leakage worth investigating)
  GREEN_OK       -- gap_pct < 0.5 AND fallback_pct < 2
  ERROR          -- chunk parse failed

Run before vs after a change to confirm:
  - All previously RED machines move to GREEN_OK / YELLOW_*
  - Zero machines regress from GREEN to RED/YELLOW
  - Reducing fallback_pct on a machine never widens its gap_pct
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAWDATA = REPO / "rawdata"
CONFIG_PATH = REPO / "configs" / "machine_round_win_rules.json"
sys.path.insert(0, str(REPO))


def verify_pair(args):
    machine, mode_dir = args
    cf = RAWDATA / machine / mode_dir / "chunk_0001.json"
    if not cf.exists():
        return None
    try:
        with open(cf, "r", encoding="utf-8") as f:
            envelope = json.load(f)
    except Exception as e:
        return {"machine": machine, "mode": mode_dir, "class": "ERROR", "msg": str(e)}
    resp = envelope.get("response")
    if not isinstance(resp, list) or not resp:
        return {"machine": machine, "mode": mode_dir, "class": "ERROR", "msg": "no response"}
    bet = int(envelope.get("_bet", 1000))

    from fresh_slotlab.player_impact_analyzer import parse_chunk_response
    from fresh_slotlab.round_win import load_rules_for_machine
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = None
    rules = load_rules_for_machine(machine, cfg)

    rec = parse_chunk_response(resp, 1, bet, round_win_rules=rules)
    if not rec.get("ok"):
        return {"machine": machine, "mode": mode_dir, "class": "ERROR",
                "msg": rec.get("error", "parse_failed")}

    chunk_win = float(rec["win"])
    pid_win = rec.get("payout_id_win") or {}
    pid_sum = sum(pid_win.values())
    # Fallback pids are the synthetic catch-alls emitted when the
    # primary pid attribution path leaves a round-level or
    # session-level residual: ``_unattributed_st<N>`` (per-SpinType
    # synthesis in the round loop) and ``_unattributed_residual``
    # (chunk-level residual). They close the gap_pct invariant but
    # hide mis-attribution; track them separately.
    fallback_pids = {
        k: v for k, v in pid_win.items()
        if str(k).startswith("_unattributed_")
    }
    fallback_sum = sum(fallback_pids.values())
    real_pid_sum = pid_sum - fallback_sum

    gap = chunk_win - pid_sum
    gap_pct = (abs(gap) / chunk_win * 100.0) if chunk_win > 0 else 0.0
    fallback_pct = (fallback_sum / chunk_win * 100.0) if chunk_win > 0 else 0.0

    if gap_pct >= 5.0:
        cls = "RED_GAP"
    elif fallback_pct >= 5.0:
        cls = "RED_FALLBACK"
    elif gap_pct >= 0.5:
        cls = "YELLOW_SMALL"
    elif fallback_pct >= 2.0:
        cls = "YELLOW_FALLBACK"
    else:
        cls = "GREEN_OK"

    return {
        "machine": machine, "mode": mode_dir, "class": cls,
        "chunk_win": chunk_win,
        "pid_sum": pid_sum,
        "real_pid_sum": real_pid_sum,
        "fallback_sum": fallback_sum,
        "fallback_pid_count": len(fallback_pids),
        "fallback_pct": fallback_pct,
        "gap_pct": gap_pct,
        "rule_count": len(rules),
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
    print(f"# verifying {len(pairs)} (machine, mode) pairs", file=sys.stderr)
    results = []
    with ProcessPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(verify_pair, p): p for p in pairs}
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
        cls_counts[r["class"]] += 1
    print("# class summary:")
    for k in sorted(cls_counts):
        print(f"#   {k}: {cls_counts[k]}")
    print()

    cls_order = {
        "RED_GAP": 0, "RED_FALLBACK": 1,
        "YELLOW_SMALL": 2, "YELLOW_FALLBACK": 3,
        "ERROR": 4, "GREEN_OK": 9,
    }
    results.sort(key=lambda r: (
        cls_order.get(r.get("class"), 9),
        -max(abs(r.get("gap_pct", 0)), abs(r.get("fallback_pct", 0))),
    ))

    cols = ["class", "machine", "mode", "rule_count", "gap_pct", "fallback_pct",
            "chunk_win", "pid_sum", "real_pid_sum", "fallback_sum", "fallback_count"]
    print("\t".join(cols))
    for r in results:
        if r.get("class") == "ERROR":
            print(f"ERROR\t{r['machine']}\t{r['mode']}\t\t\t\t\t\t\t\t\t{r.get('msg','')}")
            continue
        if r["class"] == "GREEN_OK":
            continue  # only print rows that warrant attention
        print("\t".join([
            r["class"], r["machine"], r["mode"],
            str(r["rule_count"]),
            f"{r['gap_pct']:.4f}",
            f"{r['fallback_pct']:.4f}",
            f"{r['chunk_win']:.0f}",
            f"{r['pid_sum']:.0f}",
            f"{r['real_pid_sum']:.0f}",
            f"{r['fallback_sum']:.0f}",
            str(r["fallback_pid_count"]),
        ]))


if __name__ == "__main__":
    main()
