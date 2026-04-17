"""One-off scan: check all machines' mode_N rawdata for collect-cycle
vs feature-name mismatches.

Surfaces machines where the analyzer detects a BuffCollectionMap
cycle (CollectCount resets across rounds) but "NewFreespin" isn't
among the upstream FeatureWin keys — meaning the hardcoded
newfreespin_correction silently returns 0pp and the true RTP is
under-reported.

Faster than full analyzer.main() (which takes ~50s/machine with
collect-cycle math + all summary blocks): we call
``parse_chunk_response`` directly on just the first cached chunk per
machine, pull ``cycle_peaks`` (>0 means cycle observed) and
``upstream_feature_tally`` keys, then classify via
``collect_feature_match_warning``. ~0.5s/machine → ~2min for all 250.

Usage:
    python scripts/scan_collect_feature_match.py
    python scripts/scan_collect_feature_match.py --mode 2
    python scripts/scan_collect_feature_match.py --machines M1-M50
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV_RAWDATA = ROOT / "dev_rawdata"

_parser = None
_warn_fn = None


def _worker_init() -> None:
    """Pre-import parser so each job doesn't re-import analyzer."""
    global _parser, _warn_fn
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from fresh_slotlab.player_impact_analyzer import (
        parse_chunk_response,
        collect_feature_match_warning,
    )
    _parser = parse_chunk_response
    _warn_fn = collect_feature_match_warning


def _scan_one(job: dict) -> dict:
    """Parse first chunk, return full FeatureWin tally per machine.

    Only machines whose upstream_feature_tally contains
    "BuffCollectionMap" run the collect-mechanic cycle. The feature
    that PAIRS with BuffCollectionMap (the bonus that fires at cycle
    completion) varies per machine — NewFreespin on some, possibly
    others. This scan doesn't assume the pairing; it just surfaces
    every FeatureWin entry + win totals so the operator can eyeball
    which feature is carrying the cycle bonus on each machine.
    """
    machine = job["machine"]
    chunk_path = Path(job["chunk_path"])
    bet = job["bet"]
    t0 = time.time()
    try:
        env = json.loads(chunk_path.read_text(encoding="utf-8"))
        resp = env.get("response", [])
        rec = _parser(resp, chunk_index=1, bet=bet)
        if not rec.get("ok"):
            return {"machine": machine, "ok": False,
                    "error": f"parse_failed: {rec.get('error')}"}
        feature_tally = rec.get("upstream_feature_tally") or {}
        # Flatten each feature's win/times across all payout IDs.
        feat_summary = {}
        for feat, payouts in feature_tally.items():
            if not isinstance(payouts, dict):
                continue
            total_win = sum(float((e or {}).get("win", 0.0) or 0.0)
                            for e in payouts.values())
            total_times = sum(int((e or {}).get("times", 0) or 0)
                              for e in payouts.values())
            feat_summary[feat] = {"win": total_win, "times": total_times}
        has_bcm = "BuffCollectionMap" in feat_summary
        cycle_peaks = rec.get("cycle_peaks") or []
        total_win = float(rec.get("win", 0.0) or 0.0)
        return {
            "machine": machine,
            "ok": True,
            "has_buffcollectionmap": has_bcm,
            "feature_summary": feat_summary,
            "total_win": total_win,
            "cycle_observed": len(cycle_peaks) > 0,
            "cycle_peaks_count": len(cycle_peaks),
            "completed_cycles": int(rec.get("completed_cycles") or 0),
            "elapsed_s": round(time.time() - t0, 2),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "machine": machine, "ok": False,
            "error": f"{type(exc).__name__}: {str(exc)[:150]}",
            "elapsed_s": round(time.time() - t0, 2),
        }


def _expand_range(token: str) -> list[str]:
    m = re.fullmatch(r"[Mm](\d+)-[Mm](\d+)", token)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return [f"M{i}" for i in range(lo, hi + 1)]
    return [token]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--rawdata-dir", type=Path, default=DEV_RAWDATA)
    parser.add_argument("--machines", nargs="*", default=None)
    args = parser.parse_args()

    allowed = None
    if args.machines:
        allowed = set()
        for tok in args.machines:
            allowed.update(_expand_range(tok))

    jobs = []
    for md in sorted(args.rawdata_dir.iterdir(),
                     key=lambda d: int(d.name[1:]) if d.name[1:].isdigit() else 0):
        if not md.is_dir() or not md.name.startswith("M"):
            continue
        if allowed is not None and md.name not in allowed:
            continue
        chunk_dir = md / f"mode_{args.mode}"
        if not chunk_dir.is_dir():
            continue
        chunks = sorted(chunk_dir.glob("chunk_*.json"))
        if not chunks:
            continue
        try:
            env = json.loads(chunks[0].read_text(encoding="utf-8"))
            bet = int(env.get("_bet", 1000) or 1000)
        except Exception:  # noqa: BLE001
            bet = 1000
        jobs.append({
            "machine": md.name,
            "chunk_path": str(chunks[0]),
            "bet": bet,
        })

    print(f"=== Collect-feature-match scan (mode={args.mode}) ===")
    print(f"Machines: {len(jobs)}")
    print(f"Concurrency: {args.concurrency}")
    print()

    results = []
    t0 = time.time()
    with mp.Pool(processes=args.concurrency, initializer=_worker_init) as pool:
        for i, r in enumerate(pool.imap_unordered(_scan_one, jobs), 1):
            results.append(r)
            if i % 50 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} (t+{time.time()-t0:.0f}s)")

    bcm_machines = [r for r in results if r.get("ok") and r.get("has_buffcollectionmap")]
    no_bcm = [r for r in results if r.get("ok") and not r.get("has_buffcollectionmap")]
    failed = [r for r in results if not r.get("ok")]

    def _mkey(r):
        try:
            return int(r["machine"][1:])
        except Exception:
            return 999999

    print()
    print("=" * 78)
    print(f"RESULTS  mode {args.mode} | {len(results)} machines | "
          f"{time.time()-t0:.0f}s total")
    print("=" * 78)
    print(f"  BuffCollectionMap machines (collect-mechanic) .. {len(bcm_machines)}")
    print(f"  no BuffCollectionMap (normal machines) ......... {len(no_bcm)}")
    print(f"  parse failed ................................... {len(failed)}")
    print()

    if bcm_machines:
        print("=" * 78)
        print("BuffCollectionMap machines — FeatureWin breakdown (sorted by M#)")
        print("=" * 78)
        print(
            f"{'machine':<8} {'cycle':>7} {'completed':>10}  "
            f"feature breakdown (name: win / times)"
        )
        print("-" * 78)
        for r in sorted(bcm_machines, key=_mkey):
            cyc = "yes" if r.get("cycle_observed") else "no"
            fs = r.get("feature_summary") or {}
            # Sort features by win desc so the operator sees which one
            # dominates (candidate cycle-bonus feature) at a glance.
            feat_rows = sorted(
                fs.items(), key=lambda kv: -(kv[1].get("win", 0) or 0)
            )
            feat_str = " | ".join(
                f"{name}={int(data['win']):,}w/{int(data['times'])}x"
                for name, data in feat_rows[:6]
            )
            if len(feat_rows) > 6:
                feat_str += f" | +{len(feat_rows) - 6} more"
            print(
                f"  {r['machine']:<6} {cyc:>7} "
                f"{r.get('completed_cycles', 0):>10}  {feat_str}"
            )
        print()

    if failed:
        print("-" * 78)
        print(f"PARSE FAILED — {len(failed)} machines")
        print("-" * 78)
        for r in sorted(failed, key=_mkey):
            print(f"  {r['machine']:<6} {r.get('error', '?')}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
