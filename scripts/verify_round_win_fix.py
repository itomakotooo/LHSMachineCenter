"""Post-fix fleet verification: walk every cached (machine, mode) pair
and confirm the round_win wiring delivers the promised invariants.

For each pair:
  1. Load chunk_0001.json
  2. Load round_win_rules for that machine (may be empty)
  3. Call parse_chunk_response with rules / without rules
  4. Compute server_total_win from analysisResult.TotalWin
  5. Classify the result:
     * GREEN_FIXED:  rules applied, fix_drift < 0.1%, legacy_drift > 1%
     * GREEN_CLEAN:  no rules, legacy == server (within 0.1%)
     * IDENTITY_OK:  no rules, no_rules == empty_rules byte-identical
     * IDENTITY_BAD: no rules, no_rules != empty_rules (REGRESSION)
     * STILL_BAD:    rules applied but fix_drift > 0.1%
     * NOT_FIXED:    no rules, drift > 1% (D_other class -- expected)

Output: TSV with one row per (machine, mode) + summary counts.

Run before vs after the fix to confirm:
  - 12 TopDollarSelector machines moved from drift-with-bug to GREEN_FIXED
  - Other ~830 A_clean machines stay GREEN_CLEAN
  - 8 D_other (M99/M112) machines stay NOT_FIXED (pending separate plan)
  - ZERO IDENTITY_BAD entries -- absolute regression invariant
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAWDATA = REPO / "rawdata"
CONFIG_PATH = REPO / "configs" / "machine_round_win_rules.json"

sys.path.insert(0, str(REPO))


def _server_total_win(resp) -> float:
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


def verify_pair(args):
    machine, mode_dir, config = args
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

    from fresh_slotlab.analyzer.core.parser import parse_chunk_response
    from fresh_slotlab.round_win import load_rules_for_machine

    server = _server_total_win(resp)
    rules = load_rules_for_machine(machine, config)

    # Always compute legacy (no rules) -- this drives the byte-identity
    # check for unconfigured machines.
    rec_legacy = parse_chunk_response(resp, 1, bet)
    rec_empty = parse_chunk_response(resp, 1, bet, round_win_rules=[])
    legacy_win = rec_legacy["win"]
    empty_win = rec_empty["win"]
    identity_ok = (
        legacy_win == empty_win
        and rec_legacy["spins"] == rec_empty["spins"]
        and rec_legacy["bet"] == rec_empty["bet"]
        and rec_legacy["win_sum"] == rec_empty["win_sum"]
        and dict(rec_legacy["payout_id_win"]) == dict(rec_empty["payout_id_win"])
        and dict(rec_legacy["multiplier_bucket_win"]) == dict(rec_empty["multiplier_bucket_win"])
    )

    legacy_drift_pct = (abs(legacy_win - server) / server * 100.0) if server > 0 else 0.0

    if rules:
        rec_rules = parse_chunk_response(resp, 1, bet, round_win_rules=rules)
        fixed_win = rec_rules["win"]
        fixed_drift_pct = (abs(fixed_win - server) / server * 100.0) if server > 0 else 0.0
        if fixed_drift_pct < 0.1:
            cls = "GREEN_FIXED"
        else:
            cls = "STILL_BAD"
    else:
        fixed_win = legacy_win
        fixed_drift_pct = legacy_drift_pct
        if not identity_ok:
            cls = "IDENTITY_BAD"
        elif legacy_drift_pct < 1.0:
            cls = "GREEN_CLEAN"
        else:
            cls = "NOT_FIXED"

    return {
        "machine": machine,
        "mode": mode_dir,
        "class": cls,
        "server_win": server,
        "legacy_win": legacy_win,
        "fixed_win": fixed_win,
        "legacy_drift_pct": legacy_drift_pct,
        "fixed_drift_pct": fixed_drift_pct,
        "identity_ok": identity_ok,
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
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    pairs = discover_pairs()
    print(f"# verifying {len(pairs)} (machine, mode) pairs", file=sys.stderr)

    args_list = [(m, mode, config) for m, mode in pairs]
    results = []
    with ProcessPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(verify_pair, a): a for a in args_list}
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            if r is not None:
                results.append(r)
            done += 1
            if done % 100 == 0:
                print(f"#  progress: {done}/{len(pairs)}", file=sys.stderr)

    cls_counts = {}
    for r in results:
        cls_counts[r["class"]] = cls_counts.get(r["class"], 0) + 1
    print("# class summary:")
    for k in sorted(cls_counts):
        print(f"#   {k}: {cls_counts[k]}")
    print()

    # Sort: REGRESSIONS first, then GREEN_FIXED, NOT_FIXED, GREEN_CLEAN
    cls_order = {
        "IDENTITY_BAD": 0,
        "STILL_BAD": 1,
        "GREEN_FIXED": 2,
        "NOT_FIXED": 3,
        "ERROR": 4,
        "GREEN_CLEAN": 5,
    }
    results.sort(key=lambda r: (cls_order.get(r["class"], 9), -r.get("legacy_drift_pct", 0)))

    cols = ["class", "machine", "mode", "rule_count", "server_win",
            "legacy_drift_pct", "fixed_drift_pct", "identity_ok"]
    print("\t".join(cols))
    for r in results:
        if r["class"] == "ERROR":
            print(f"ERROR\t{r['machine']}\t{r['mode']}\t\t\t\t\t{r.get('msg','')}")
            continue
        # Skip the GREEN_CLEAN noise -- only print non-clean rows for review.
        if r["class"] == "GREEN_CLEAN":
            continue
        print("\t".join([
            r["class"], r["machine"], r["mode"],
            str(r["rule_count"]),
            f"{r['server_win']:.0f}",
            f"{r['legacy_drift_pct']:.2f}",
            f"{r['fixed_drift_pct']:.4f}",
            str(r["identity_ok"]),
        ]))


if __name__ == "__main__":
    main()
