"""Per-round field probe — reducer that emits compact KB-scale summaries
instead of raw chunk data.

Usage patterns:
    # What values does RewardType take on M273 mode_1?
    python scripts/probe_round_field.py --machine M273 --mode 1 \
        --field RewardType

    # Cross-tab RewardType against SpinType + sample 3 non-zero rounds.
    python scripts/probe_round_field.py --machine M273 --mode 1 \
        --field RewardType --co SpinType --samples 3 \
        --sample-filter "v != 0"

    # Walk every machine that has a mode_1 cache, show RewardType value
    # distribution in one tall table.
    python scripts/probe_round_field.py --all --mode 1 --field RewardType

Script never pastes raw round content into the operator's terminal
unless --samples N is specified, in which case only N rounds are shown
and only keys overlapping with --field + --co are kept.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAWDATA = ROOT / "rawdata"


def _iter_rounds(chunk_path: Path):
    """Yield each round dict from a chunk envelope."""
    env = json.loads(chunk_path.read_text(encoding="utf-8"))
    resp = env.get("response") or []
    if not isinstance(resp, list):
        return
    for robot in resp:
        if not isinstance(robot, dict):
            continue
        rr = robot.get("roundResult")
        if isinstance(rr, str):
            try:
                rounds = json.loads(rr)
            except json.JSONDecodeError:
                continue
        elif isinstance(rr, list):
            rounds = rr
        else:
            continue
        for r in rounds:
            if isinstance(r, dict):
                yield r


def _value_key(v):
    """Cast value to something Counter-keyable and JSON-safe."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    # Dict / list / nested: bucket by type only (too much fanout
    # otherwise). Callers wanting structure should use --samples.
    return f"<{type(v).__name__}>"


def _probe_one(
    chunk_paths: list[Path],
    field: str,
    co_fields: list[str],
    samples: int,
    sample_filter: str | None,
):
    total_rounds = 0
    present_rounds = 0
    value_counts = Counter()
    co_tables = {c: defaultdict(Counter) for c in co_fields}  # c → {v → Counter(c_v)}
    samples_out = []
    sample_pred = None
    if sample_filter:
        try:
            sample_pred = eval(f"lambda v, r: ({sample_filter})", {"__builtins__": {}}, {})
        except SyntaxError:
            raise SystemExit(f"bad --sample-filter syntax: {sample_filter!r}")

    for cp in chunk_paths:
        for r in _iter_rounds(cp):
            total_rounds += 1
            present = field in r
            if not present:
                continue
            present_rounds += 1
            v = r.get(field)
            vk = _value_key(v)
            value_counts[vk] += 1
            for c in co_fields:
                co_v = _value_key(r.get(c))
                co_tables[c][vk][co_v] += 1
            if samples > len(samples_out):
                if sample_pred is None or sample_pred(v, r):
                    # Keep only field + co-fields + a few common context
                    # keys; no big strings like StopSymbolsByCol.
                    trimmed = {field: v}
                    for c in co_fields:
                        if c in r:
                            trimmed[c] = r[c]
                    for extra in ("BetAmount", "CostCredits", "WinCredits", "CollectCount"):
                        if extra in r and extra not in trimmed:
                            trimmed[extra] = r[extra]
                    samples_out.append(trimmed)

    return {
        "total_rounds": total_rounds,
        "present_rounds": present_rounds,
        "value_counts": value_counts,
        "co_tables": co_tables,
        "samples": samples_out,
    }


def _emit_counts_table(counts: Counter, limit: int = 25) -> list[str]:
    total = sum(counts.values()) or 1
    out = []
    for v, n in counts.most_common(limit):
        pct = 100 * n / total
        out.append(f"    {str(v)!s:<30} {n:>10,}  ({pct:>5.2f}%)")
    if len(counts) > limit:
        out.append(f"    ... {len(counts) - limit} more distinct values")
    return out


def _run_one_machine(machine: str, mode: int, field: str, co: list[str],
                     samples: int, sample_filter: str | None,
                     first_chunk_only: bool) -> None:
    chunk_dir = RAWDATA / machine / f"mode_{mode}"
    if not chunk_dir.is_dir():
        print(f"[{machine} mode_{mode}] no cache dir — skipped")
        return
    chunks = sorted(chunk_dir.glob("chunk_*.json"))
    if not chunks:
        print(f"[{machine} mode_{mode}] no chunks — skipped")
        return
    if first_chunk_only:
        chunks = chunks[:1]
    result = _probe_one(chunks, field, co, samples, sample_filter)
    total = result["total_rounds"]
    present = result["present_rounds"]
    counts = result["value_counts"]
    print()
    print(f"=== {machine} mode_{mode} · field={field} · chunks={len(chunks)} ===")
    print(f"rounds scanned:   {total:,}")
    if total:
        print(f"rounds with field: {present:,}  ({100*present/total:.2f}%)")
    print(f"distinct values:  {len(counts)}")
    print("value_counts:")
    for line in _emit_counts_table(counts):
        print(line)
    for c, tbl in result["co_tables"].items():
        print(f"co-occurrence  {field} × {c}:")
        for v, nested in sorted(tbl.items(), key=lambda kv: -sum(kv[1].values())):
            total_v = sum(nested.values())
            print(f"  {field}={v!s}  (n={total_v:,}):")
            for cv, cn in nested.most_common(10):
                print(f"      {c}={cv!s:<22} {cn:>10,}  ({100*cn/total_v:.2f}%)")
    if result["samples"]:
        print(f"samples (n={len(result['samples'])}):")
        for s in result["samples"]:
            print(f"  {json.dumps(s, ensure_ascii=False, sort_keys=True)}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--machine", help="single machine, e.g. M273")
    p.add_argument("--all", action="store_true",
                   help="scan every machine with mode_N cache")
    p.add_argument("--mode", type=int, default=1)
    p.add_argument("--field", required=True, help="per-round field name")
    p.add_argument("--co", nargs="*", default=[],
                   help="co-occurrence fields (e.g. SpinType PayId)")
    p.add_argument("--samples", type=int, default=0,
                   help="emit up to N raw rounds matching --sample-filter")
    p.add_argument("--sample-filter", default=None,
                   help="Python expr on (v, r) for sampling, e.g. 'v != 0'")
    p.add_argument("--first-chunk", action="store_true",
                   help="only read chunk_0001.json per machine (faster for --all)")
    args = p.parse_args()

    if not args.machine and not args.all:
        p.error("must specify --machine or --all")

    if args.machine:
        _run_one_machine(args.machine, args.mode, args.field, args.co,
                         args.samples, args.sample_filter, args.first_chunk)
        return 0

    # --all: iterate
    machines = sorted(
        (d.name for d in RAWDATA.iterdir()
         if d.is_dir() and d.name.startswith("M")),
        key=lambda n: int(n[1:]) if n[1:].isdigit() else 9999,
    )
    for m in machines:
        _run_one_machine(m, args.mode, args.field, args.co,
                         0, None, True)  # samples/filter off in --all mode
    return 0


if __name__ == "__main__":
    sys.exit(main())
