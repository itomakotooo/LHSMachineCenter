"""Fleet-wide investigation of 3 bugs reported by user on M279:

  1. PayoutByPayline symbol_id != PayoutIdToWinAmount key
     (inference uses symbol_id as pay_id; jackpot pattern breaks it)

  2. BCM chain inference picks wrong downstream feature
     (cc-reset timing off-by-one + heuristic max(feature_win))

  3. Wild auto-nudge mechanic treated as independent feature
     (ST=36 MoveSpin is paid-spin continuation, not new feature)

For each bug, identify which machines are affected and how badly.
This drives the refactor decision: if bugs are localized to a small
family, per-machine config; if widespread, structural change.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAWDATA = REPO / "rawdata"
BCM_PAIRINGS_PATH = REPO / "configs" / "bcm_pairings.json"

PAYLINE_RE = re.compile(r"(-?\d+):(-?\d+)-(-?\d+)\(([^)]*)\)")


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
    except Exception:
        return None
    resp = envelope.get("response")
    if not isinstance(resp, list) or not resp:
        return None
    bet = int(envelope.get("_bet", 1000))

    # Bug 1 metrics: count rounds where any line in PayoutByPayline has
    # a symbol_id that's NOT a key in PayoutIdToWinAmount (mismatched
    # namespace -- inference would synthesize a wrong pay_id).
    bug1_total_rounds = 0
    bug1_lines_total = 0
    bug1_lines_mismatch = 0
    bug1_mismatch_examples: list = []  # (line_id, sym_id, pid_keys) tuples

    # Bug 2 metrics: BCM cycle behavior.
    # - Does this (machine, mode) have CollectCount mechanic?
    # - At cc-peak (cycle complete), what SpinType fires next?
    # - Compare with what bcm_pairings.json + heuristic picks
    cc_observed = False
    cc_peak_value: int = 0  # max cc observed across the chunk (cycle length)
    cc_peak_count: int = 0
    next_st_at_peak: Counter = Counter()
    next_st_at_normal_paid: Counter = Counter()  # cc 1..peak-1 -> next ST

    # First pass: find the cycle peak (max cc value) across all robots.
    for robot in resp:
        if not isinstance(robot, dict):
            continue
        rr = robot.get("roundResult")
        if isinstance(rr, str):
            try:
                rounds_pre = json.loads(rr)
            except Exception:
                continue
        elif isinstance(rr, list):
            rounds_pre = rr
        else:
            continue
        for r in rounds_pre:
            if not isinstance(r, dict):
                continue
            cc = r.get("CollectCount")
            if cc is None:
                continue
            try:
                cc_int = int(cc)
            except (TypeError, ValueError):
                continue
            if cc_int > cc_peak_value:
                cc_peak_value = cc_int
                cc_observed = True

    # Track FeatureWin totals -- used to verify max-win heuristic choice
    feature_win_totals: dict = defaultdict(float)

    # Bug 3 metrics: wild-nudge / move-spin mechanic.
    # Detect by ReMarks containing 'move' / 'Move' / 'nudge' / 'Nudge'
    # AND CostCredits=0 (i.e., free continuation of paid spin).
    nudge_observed = False
    nudge_remarks: Counter = Counter()
    nudge_st_distribution: Counter = Counter()
    nudge_total_win = 0.0

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

        # FeatureWin parse
        ar = robot.get("analysisResult")
        if isinstance(ar, str):
            try:
                analysis = json.loads(ar)
            except Exception:
                analysis = None
        else:
            analysis = ar
        if isinstance(analysis, dict):
            fw = analysis.get("FeatureWin")
            if isinstance(fw, str):
                try:
                    fw = json.loads(fw)
                except Exception:
                    fw = None
            if isinstance(fw, dict):
                for feat_name, payouts in fw.items():
                    if not isinstance(payouts, dict):
                        continue
                    feat_win = sum(
                        to_float(v.get("WinCredits"), 0.0)
                        for v in payouts.values() if isinstance(v, dict)
                    )
                    feature_win_totals[feat_name] += feat_win

        # Per-round walk
        for i, r in enumerate(rounds):
            if not isinstance(r, dict):
                continue
            bug1_total_rounds += 1

            # Bug 1: PayoutByPayline vs PayoutIdToWinAmount
            pbp = r.get("PayoutByPayline") or ""
            pid = r.get("PayoutIdToWinAmount") or {}
            pid_keys: set = set()
            if isinstance(pid, dict):
                pid_keys = {str(k) for k in pid.keys()}
            if pbp and pid_keys:
                for rec in pbp.split(";"):
                    m = PAYLINE_RE.match(rec.strip())
                    if not m:
                        continue
                    bug1_lines_total += 1
                    sym_id = m[2]
                    if sym_id not in pid_keys:
                        bug1_lines_mismatch += 1
                        if len(bug1_mismatch_examples) < 3:
                            bug1_mismatch_examples.append({
                                "line_id": m[1], "sym_id": sym_id,
                                "pid_keys": sorted(pid_keys)[:5],
                            })

            # Bug 2: BCM cycle behavior. cycle_peak is fixed (e.g.,
            # 1000 for M279); a paid round with cc == cycle_peak is
            # the cycle-complete signal. We compare what fires next
            # against the heuristic / config pick.
            cc = r.get("CollectCount")
            cost = r.get("CostCredits")
            if cc is not None and cc_peak_value >= 50:
                try:
                    cc_int = int(cc)
                except (TypeError, ValueError):
                    cc_int = 0
                is_paid_round = (
                    cost is not None and to_float(cost, 0.0) > 0
                )
                if is_paid_round and cc_int > 0:
                    is_at_peak = (cc_int == cc_peak_value)
                    if is_at_peak:
                        # Find next non-paid round
                        for j in range(i + 1, min(i + 5, len(rounds))):
                            nr = rounds[j]
                            if not isinstance(nr, dict):
                                continue
                            ncost = nr.get("CostCredits")
                            if ncost is None or to_float(ncost) == 0:
                                next_st_at_peak[nr.get("SpinType")] += 1
                                cc_peak_count += 1
                                break
                            else:
                                next_st_at_peak["NEXT_PAID"] += 1
                                cc_peak_count += 1
                                break
                    elif cc_int < cc_peak_value - 10:
                        # Mid-cycle paid round
                        for j in range(i + 1, min(i + 3, len(rounds))):
                            nr = rounds[j]
                            if not isinstance(nr, dict):
                                continue
                            ncost = nr.get("CostCredits")
                            if ncost is None or to_float(ncost) == 0:
                                next_st_at_normal_paid[nr.get("SpinType")] += 1
                                break
                            else:
                                next_st_at_normal_paid["NEXT_PAID"] += 1
                                break

            # Bug 3: wild-nudge / move-spin detection
            rmk = r.get("ReMarks") or ""
            if isinstance(rmk, str):
                rmk_lower = rmk.lower()
                if (
                    ("move" in rmk_lower or "nudge" in rmk_lower)
                    and to_float(cost, 0.0) == 0.0
                ):
                    nudge_observed = True
                    nudge_remarks[rmk[:30]] += 1
                    nudge_st_distribution[r.get("SpinType")] += 1
                    nudge_total_win += to_float(r.get("WinCredits"), 0.0)

    # bcm_pairings.json heuristic / observed ground-truth comparison
    bcm_config_target: str | None = None
    bcm_config_confidence: str | None = None
    if BCM_PAIRINGS_PATH.exists():
        try:
            with open(BCM_PAIRINGS_PATH, encoding="utf-8") as f:
                cfg_p = json.load(f)
            machines_cfg = (cfg_p or {}).get("machines") or {}
            entry = machines_cfg.get(machine)
            if isinstance(entry, dict):
                modes = entry.get("modes") or {}
                mode_num = mode_dir.replace("mode_", "")
                m_cfg = modes.get(mode_num) or {}
                bcm_config_target = m_cfg.get("bonus_feature")
                bcm_config_confidence = m_cfg.get("confidence")
        except Exception:
            pass

    # Heuristic max-feature (mimics _resolve_bonus_feature).
    PAID_NORMAL = {"Normal", "NormalCollectionSpin", "NewFreespin", "FreeSpin"}
    heuristic_pick: str | None = None
    heuristic_pick_win: float = -1.0
    for feat_name, win in feature_win_totals.items():
        if feat_name in PAID_NORMAL or feat_name == "BuffCollectionMap":
            continue
        if win > heuristic_pick_win:
            heuristic_pick_win = win
            heuristic_pick = feat_name

    return {
        "machine": machine,
        "mode": mode_dir,
        "bet": bet,
        "rounds_total": bug1_total_rounds,
        # Bug 1
        "bug1_lines_total": bug1_lines_total,
        "bug1_lines_mismatch": bug1_lines_mismatch,
        "bug1_mismatch_pct": (
            bug1_lines_mismatch / bug1_lines_total * 100.0
            if bug1_lines_total > 0 else 0.0
        ),
        "bug1_examples": bug1_mismatch_examples,
        # Bug 2
        "cc_observed": cc_observed,
        "cc_peak_value": cc_peak_value,
        "cc_peak_paid_rounds": cc_peak_count,
        "next_st_at_peak": dict(next_st_at_peak),
        "next_st_at_normal_paid": dict(next_st_at_normal_paid),
        "bcm_config_target": bcm_config_target,
        "bcm_config_confidence": bcm_config_confidence,
        "bcm_heuristic_pick": heuristic_pick,
        "bcm_heuristic_pick_win": heuristic_pick_win,
        # Bug 3
        "nudge_observed": nudge_observed,
        "nudge_remarks": dict(nudge_remarks),
        "nudge_st_distribution": dict(nudge_st_distribution),
        "nudge_total_win": nudge_total_win,
        # Feature totals -- ground truth for heuristic tuning
        "feature_win_totals": dict(feature_win_totals),
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
    print(f"# investigating {len(pairs)} (machine, mode) pairs", file=sys.stderr)
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

    # Aggregate
    bug1_affected = []  # machines with > 0.1% line mismatch rate
    bug2_affected = []  # machines with cc mechanic + (config or heuristic) != observed-true
    bug3_affected = []  # machines with nudge / move observed

    for r in results:
        if r["bug1_lines_mismatch"] > 0:
            bug1_affected.append(r)
        # Bug 2: machine has cc mechanic, heuristic / config target known,
        # observed at-peak target known
        if r["cc_observed"] and r["cc_peak_paid_rounds"] > 0:
            obs = r["next_st_at_peak"]
            if obs:
                # Top observed at-peak ST
                top_obs_st = max(obs.items(), key=lambda kv: kv[1])[0]
                # Compare with config / heuristic
                bug2_affected.append({
                    "machine": r["machine"],
                    "mode": r["mode"],
                    "cc_peak_value": r["cc_peak_value"],
                    "cc_peak_paid_rounds": r["cc_peak_paid_rounds"],
                    "obs_at_peak": obs,
                    "top_obs_st": top_obs_st,
                    "config_target": r["bcm_config_target"],
                    "config_confidence": r["bcm_config_confidence"],
                    "heuristic_pick": r["bcm_heuristic_pick"],
                    "feature_totals": r["feature_win_totals"],
                })
        if r["nudge_observed"]:
            bug3_affected.append(r)

    print()
    print(f"## Bug 1 (PayoutByPayline symbol_id mismatch)")
    print(f"  Affected (machine, mode) pairs: {len(bug1_affected)}")
    bug1_high = [r for r in bug1_affected if r["bug1_mismatch_pct"] > 1.0]
    print(f"  High-impact (>1% line mismatch): {len(bug1_high)}")
    print()
    print("  Top 15 affected (by mismatch %):")
    for r in sorted(bug1_affected, key=lambda x: -x["bug1_mismatch_pct"])[:15]:
        print(f"    {r['machine']:35s} {r['mode']:8s}  "
              f"mismatch={r['bug1_lines_mismatch']:5d}/{r['bug1_lines_total']:7d} "
              f"({r['bug1_mismatch_pct']:5.2f}%) "
              f"ex={r['bug1_examples'][:1]}")

    print()
    print(f"## Bug 2 (BCM chain inference)")
    print(f"  Machines with cc/BCM mechanic: {len(bug2_affected)}")
    # How many have config/heuristic mismatch with observed-at-peak?
    bug2_mismatched = []
    for r in bug2_affected:
        # The config target is a feature NAME (e.g., 'MoveSpin'); the
        # observed-at-peak is a SpinType (e.g., 2 for Wheel). Different
        # namespaces -- can't directly compare. But we can detect "wheel"
        # in observed (if ST=2 dominates, expect feature like 'Wheel').
        # Print all and let operator review.
        bug2_mismatched.append(r)
    print(f"  Showing all {len(bug2_mismatched)}:")
    for r in sorted(bug2_mismatched, key=lambda x: x["machine"]):
        print(f"    {r['machine']:35s} {r['mode']:8s} "
              f"peak={r['cc_peak_value']:4d} "
              f"obs_at_peak={r['obs_at_peak']} "
              f"cfg={r['config_target']!r}/{r['config_confidence']} "
              f"heur={r['heuristic_pick']!r}")

    print()
    print(f"## Bug 3 (wild-nudge / move-spin)")
    print(f"  Affected (machine, mode) pairs: {len(bug3_affected)}")
    print()
    print("  Top 15 affected (by nudge_total_win):")
    for r in sorted(bug3_affected, key=lambda x: -x["nudge_total_win"])[:15]:
        sample_remarks = list(r["nudge_remarks"].items())[:3]
        print(f"    {r['machine']:35s} {r['mode']:8s} "
              f"nudge_st={r['nudge_st_distribution']} "
              f"win={r['nudge_total_win']:11.0f} "
              f"sample_remarks={sample_remarks}")


if __name__ == "__main__":
    main()
