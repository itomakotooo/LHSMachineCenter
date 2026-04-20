"""Verify simulator end-to-end by running it through the existing analyzer.

Flow:
  1. ``simulate.py`` writes rawdata-format chunks to ``out/<tag>/cache/``
  2. ``player_impact_analyzer.py --from-cache`` reads those chunks and
     produces the same summary / report artefacts as real runs
  3. This script diffs sim summary against a reference summary (defaults
     to the ``reports/<machine>/mode_<N>/latest.json`` target file)

Interpretation:
  - If diff is small → engine correct AND user's weights ≈ production weights
  - If RTP / bucket distribution / per-pay_id fires diverge → engine may be
    correct but user's weights don't match whatever produced the rawdata.
    That's expected when the provided weight table is a "reference" not
    the current production reel strip.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def run_simulate(
    spec: Path,
    weights: Path,
    cache_dir: Path,
    *,
    chunks: int,
    robots: int,
    spins_per_robot: int,
    seed: int,
) -> None:
    cmd = [
        sys.executable, "-m", "slot_designer.scripts.simulate",
        "--spec", str(spec),
        "--weights", str(weights),
        "--out-dir", str(cache_dir),
        "--chunks", str(chunks),
        "--robots", str(robots),
        "--spins-per-robot", str(spins_per_robot),
        "--seed", str(seed),
    ]
    result = subprocess.run(cmd, cwd=_ROOT, check=True, capture_output=True, text=True)
    print(result.stdout)


def run_analyzer(
    cache_dir: Path,
    report_dir: Path,
    machine: str,
    mode: int,
) -> None:
    analyzer = _ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
    report_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(analyzer),
        "--machine", machine,
        "--rtp-mode", str(mode),
        "--from-cache", str(cache_dir),
        "--output-dir", str(report_dir),
        "--target-halfwidth-pp", "0.001",  # don't CI-stop; process all chunks
        "--max-chunks", "9999",
    ]
    result = subprocess.run(cmd, cwd=_ROOT, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print("--- analyzer stdout ---")
        print(result.stdout[-3000:])
        print("--- analyzer stderr ---")
        print(result.stderr[-3000:])
        raise SystemExit(f"analyzer exited {result.returncode}")
    # Show the last chunk lines so the operator sees completion
    tail = result.stdout.strip().splitlines()[-10:]
    print("analyzer tail:")
    for line in tail:
        print(f"  {line}")


def _gather(summary: dict) -> dict:
    pi = summary["player_impact"]
    vol = pi["volatility"]
    hit = pi["hit_and_payout"]
    streaks = pi.get("streaks", {})
    derived = summary.get("guideline_assessment", {}).get("derived_metrics", {})
    return {
        "rtp_pct": summary["rtp"]["point_pct"],
        "total_spins": summary["sampling"]["total_spins"],
        "bucket": vol["return_bucket_rate"],
        "std_return_x": vol["std_return_x"],
        "max_return_x": vol["max_observed_return_x"],
        "hit_rate": hit["win_hit_rate"],
        "zero_rate": hit["zero_win_rate"],
        "big10": hit.get("big_win_x10_rate", 0),
        "loss_p95": streaks.get("loss_streak_p95", 0),
        "loss_max": streaks.get("loss_streak_max", 0),
        "tail10": derived.get("tail_dependency_ge10x", 0),
        "tail100": derived.get("tail_dependency_ge100x", 0),
        "pay_hits": {r["payout_id"]: r["hit_rate"] for r in pi.get("payout_ids_top20", [])},
    }


def compare(sim_sum: dict, ref_sum: dict, ref_label: str) -> None:
    s = _gather(sim_sum)
    r = _gather(ref_sum)

    def row(label, sv, rv, width=28):
        diff = sv - rv
        print(f"  {label:<{width}} sim={sv:>10.4f}   ref={rv:>10.4f}   Δ={diff:+8.4f}")

    print(f"\n=== sim vs {ref_label} ===")
    print(f"  sim  spins: {s['total_spins']:>8}  ref spins: {r['total_spins']:>8}\n")

    row("RTP (%)", s["rtp_pct"], r["rtp_pct"])
    row("hit_rate (%)", s["hit_rate"] * 100, r["hit_rate"] * 100)
    row("zero_win_rate (%)", s["zero_rate"] * 100, r["zero_rate"] * 100)
    row("big_win_x10_rate (%)", s["big10"] * 100, r["big10"] * 100)
    row("std_return_x", s["std_return_x"], r["std_return_x"])
    row("tail_dep_ge10x", s["tail10"], r["tail10"])
    row("tail_dep_ge100x", s["tail100"], r["tail100"])
    row("loss_streak_p95", s["loss_p95"], r["loss_p95"])
    row("loss_streak_max", s["loss_max"], r["loss_max"])

    print("\n  Multiplier bucket spin_rate (%):")
    bucket_keys = [
        "ge1_lt5", "ge5_lt10", "ge10_lt20", "ge20_lt50",
        "ge50_lt100", "ge100_lt200", "ge200_lt500",
        "ge500_lt1000", "ge1000_lt5000", "ge5000",
    ]
    for k in bucket_keys:
        sv = s["bucket"].get(k, 0) * 100
        rv = r["bucket"].get(k, 0) * 100
        print(f"    {k:<18s} sim={sv:>7.4f}   ref={rv:>7.4f}   Δ={sv - rv:+7.4f}")

    print("\n  Per-pay_id hit rate (%):")
    all_pids = sorted(set(s["pay_hits"]) | set(r["pay_hits"]),
                      key=lambda x: int(x) if x.isdigit() else -1)
    for pid in all_pids:
        sv = s["pay_hits"].get(pid, 0)
        rv = r["pay_hits"].get(pid, 0)
        marker = "  " if abs(sv - rv) < 0.5 else " *"
        print(f"    pay_id {pid:>4}: sim={sv:>8.4f}   ref={rv:>8.4f}   Δ={sv - rv:+7.4f}{marker}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--machine", default="M1")
    p.add_argument("--mode", type=int, default=1)
    p.add_argument("--spec", type=Path)
    p.add_argument("--weights", type=Path)
    p.add_argument("--chunks", type=int, default=11)
    p.add_argument("--robots", type=int, default=10)
    p.add_argument("--spins-per-robot", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--ref-summary", type=Path,
                   help="override reference summary path (defaults to the latest.json target for machine/mode)")
    p.add_argument("--keep-out", action="store_true")
    args = p.parse_args()

    spec = args.spec or (_ROOT / "slot_designer" / "specs" / f"{args.machine}.spec.json")
    weights = args.weights or (
        _ROOT / "slot_designer" / "weights" / f"{args.machine}_mode{args.mode}.current.json"
    )
    if not spec.exists():
        raise SystemExit(f"spec not found: {spec}")
    if not weights.exists():
        raise SystemExit(f"weights not found: {weights}")

    tag = f"{args.machine}_mode{args.mode}_verify"
    out_root = _ROOT / "slot_designer" / "out" / tag
    cache_dir = out_root / "cache"
    report_dir = out_root / "analyzer_report"
    if out_root.exists() and not args.keep_out:
        shutil.rmtree(out_root)

    print(f"[1/3] simulate → {cache_dir}")
    run_simulate(spec, weights, cache_dir,
                 chunks=args.chunks, robots=args.robots,
                 spins_per_robot=args.spins_per_robot, seed=args.seed)

    print(f"\n[2/3] analyzer --from-cache → {report_dir}")
    run_analyzer(cache_dir, report_dir, args.machine, args.mode)

    sim_sum_path = report_dir / "player_impact_summary.json"
    if not sim_sum_path.exists():
        raise SystemExit(f"analyzer did not produce summary at {sim_sum_path}")
    sim_summary = json.loads(sim_sum_path.read_text(encoding="utf-8"))

    # Load reference summary
    if args.ref_summary:
        ref_path = args.ref_summary
        ref_label = str(ref_path)
    else:
        latest_path = _ROOT / "reports" / args.machine / f"mode_{args.mode}" / "latest.json"
        if not latest_path.exists():
            raise SystemExit(f"no reference latest.json at {latest_path}; pass --ref-summary")
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        ref_path = Path(latest["summary_file"])
        ref_label = f"{args.machine} mode {args.mode} real report"
    ref_summary = json.loads(ref_path.read_text(encoding="utf-8"))

    print(f"\n[3/3] diff")
    compare(sim_summary, ref_summary, ref_label)

    # Stand-alone sim profile (useful when tuning without a ref)
    sim = _gather(sim_summary)
    print(f"\n=== sim stand-alone ===")
    print(f"  RTP       : {sim['rtp_pct']:.3f}%")
    print(f"  hit_rate  : {sim['hit_rate']*100:.3f}%")
    print(f"  std ret_x : {sim['std_return_x']:.3f}")
    print(f"  tail_ge10 : {sim['tail10']:.3f}")


if __name__ == "__main__":
    main()
