"""Probe which RTP modes are supported per machine.

Sends a tiny request (1 robot × 10 spins) to each machine for each mode
and records success/failure. Writes results to configs/machine_modes.json.

Usage:
    python scripts/probe_modes.py --concurrency 10
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fresh_slotlab.analyzer.core.base_pipeline import make_payload, post_json  # noqa: E402

MACHINES_CONFIG = ROOT / "configs" / "machines.json"
OUTPUT = ROOT / "configs" / "machine_modes.json"
MODES = [1, 2, 5, 7]


def probe_mode(machine: str, mode: int, timeout: float = 30.0) -> bool:
    """Return True if the machine supports this mode."""
    payload = make_payload(
        machine=machine, rtp_mode=mode, bet=1000,
        spin_times=10, robot_count=1,
        init_credits=10**14, reset_each_spin=True,
        continue_after_bankrupt=True,
    )
    try:
        resp = post_json(payload, timeout)
        return isinstance(resp, list) and len(resp) > 0
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    with open(MACHINES_CONFIG, "r", encoding="utf-8") as f:
        machines = json.load(f).get("machines", [])

    available = [m for m in machines if m.get("available", True)]
    print(f"Probing {len(available)} machines × {len(MODES)} modes = {len(available) * len(MODES)} requests")
    print(f"Concurrency: {args.concurrency}")

    results: dict[str, list[int]] = {}
    t0 = time.time()

    tasks = [(m["machine"], mode) for m in available for mode in MODES]

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        future_map = {
            pool.submit(probe_mode, machine, mode, args.timeout): (machine, mode)
            for machine, mode in tasks
        }
        done = 0
        for future in concurrent.futures.as_completed(future_map):
            machine, mode = future_map[future]
            ok = future.result()
            if machine not in results:
                results[machine] = []
            if ok:
                results[machine].append(mode)
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(tasks)} done...")

    # Sort modes
    for k in results:
        results[k] = sorted(results[k])

    elapsed = time.time() - t0
    all_modes = sum(len(v) for v in results.values())
    zero_modes = sum(1 for v in results.values() if not v)

    print(f"\nDone in {elapsed:.1f}s")
    print(f"Total supported modes: {all_modes}")
    print(f"Machines with 0 modes: {zero_modes}")

    # Show distribution
    from collections import Counter
    mode_counts = Counter(len(v) for v in results.values())
    for n, cnt in sorted(mode_counts.items()):
        print(f"  {n} modes: {cnt} machines")

    OUTPUT.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nWritten to {OUTPUT}")


if __name__ == "__main__":
    main()
