"""Batch light-sampling for development: pull 10k spins per machine-mode.

Usage:
    python -m fresh_slotlab.batch_dev_sampler M1 M2 M3 --mode 2
    python -m fresh_slotlab.batch_dev_sampler M1-M10 --mode 2
    python -m fresh_slotlab.batch_dev_sampler M1-M10 --mode 2 --concurrency 5

Output is saved under  dev_rawdata/{machine}/mode_{mode}/chunk_0001.json
using the same envelope format as the chunk cache (compatible with
offline rebuild and future analyzer work).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import socket
import sys
import time
import urllib.error
from pathlib import Path
from typing import Any

# Reuse the core helpers from the existing analyzer
from fresh_slotlab.player_impact_analyzer import (
    CHUNK_CACHE_VERSION,
    make_payload,
    post_json,
    post_json_with_retry,
    utc_now,
    _compute_upstream_schema_fingerprint,
    _lookup_machine_md5,
    _payload_sha256,
)

DEV_RAWDATA_DIR = Path(__file__).resolve().parent.parent / "dev_rawdata"

# post_json_with_retry has moved to player_impact_analyzer so the live
# sampling loop and this dev sampler share one retry policy. The local
# `_post_json_with_retry` alias is preserved below for tests that
# monkey-patch it at the sampler module (they only import this module
# so patching the analyzer symbol wouldn't reach them).
_post_json_with_retry = post_json_with_retry


def _atomic_write_envelope(out_path: Path, envelope: dict[str, Any]) -> None:
    """Write the chunk envelope atomically (.tmp + os.replace).

    Mirrors _save_chunk_cache's v3 atomicity. Without this, a crash or
    disk-full mid-write leaves a half-JSON chunk that the analyzer's
    load_chunk_envelope will reject on the next read.
    """
    tmp = out_path.with_name(out_path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, out_path)
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise

# ── CLI ─────────────────────────────────────────────────────────────


def _expand_machine_range(token: str) -> list[str]:
    """Expand 'M1-M10' into ['M1','M2',...,'M10']. Pass through plain names."""
    m = re.fullmatch(r"[Mm](\d+)-[Mm](\d+)", token)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return [f"M{i}" for i in range(lo, hi + 1)]
    return [token]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("machines", nargs="+",
                   help="Machine names or ranges, e.g. M1 M2 M3 or M1-M10")
    p.add_argument("--mode", type=int, default=2, help="RTP mode (default: 2)")
    p.add_argument("--spins", type=int, default=10_000,
                   help="Total spins per machine-mode (default: 10000)")
    p.add_argument("--robot-count", type=int, default=10,
                   help="Robots per API call (default: 10, spins split evenly)")
    p.add_argument("--bet", type=int, default=1000, help="Bet amount (default: 1000)")
    p.add_argument("--concurrency", type=int, default=3,
                   help="Max machines sampled in parallel (default: 3)")
    p.add_argument("--timeout", type=float, default=300,
                   help="API timeout in seconds (default: 300)")
    p.add_argument("--out-dir", type=str, default=None,
                   help=f"Output root (default: {DEV_RAWDATA_DIR})")
    return p.parse_args(argv)


# ── Single machine fetch ────────────────────────────────────────────


def fetch_machine(
    machine: str,
    mode: int,
    spins: int,
    robot_count: int,
    bet: int,
    timeout: float,
    out_dir: Path,
) -> dict[str, Any]:
    """Fetch one machine-mode and save to disk. Returns status dict."""
    spin_per_robot = spins // robot_count
    actual_spins = spin_per_robot * robot_count

    dest = out_dir / machine / f"mode_{mode}"
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / "chunk_0001.json"

    # Skip if already fetched
    if out_path.exists():
        size_mb = out_path.stat().st_size / (1024 * 1024)
        return {
            "machine": machine,
            "mode": mode,
            "ok": True,
            "skipped": True,
            "size_mb": round(size_mb, 2),
        }

    payload = make_payload(
        machine=machine,
        rtp_mode=mode,
        bet=bet,
        spin_times=spin_per_robot,
        robot_count=robot_count,
        init_credits=10**14,
        reset_each_spin=True,
        continue_after_bankrupt=True,
    )

    t0 = time.time()
    try:
        resp = _post_json_with_retry(payload, timeout)
    except Exception as exc:  # noqa: BLE001
        return {
            "machine": machine,
            "mode": mode,
            "ok": False,
            "error": f"{exc.__class__.__name__}: {exc}",
            "elapsed_s": round(time.time() - t0, 1),
        }
    elapsed = time.time() - t0

    # Save in chunk-cache envelope format (v3 — atomic + sha256) for
    # parity with _save_chunk_cache. See player_impact_analyzer.py.
    config_md5, code_md5 = _lookup_machine_md5(machine)
    envelope = {
        "_cache_version": CHUNK_CACHE_VERSION,
        "_machine": machine,
        "_mode": mode,
        "_bet": bet,
        "_spin_times": spin_per_robot,
        "_robot_count": robot_count,
        "_chunk_index": 1,
        "_saved_at": utc_now(),
        "_config_md5": config_md5,
        "_code_md5": code_md5,
        "_upstream_schema_fingerprint": _compute_upstream_schema_fingerprint(resp),
        "_payload_sha256": _payload_sha256(resp),
        "_dev_sample": True,
        "response": resp,
    }
    _atomic_write_envelope(out_path, envelope)
    size_mb = out_path.stat().st_size / (1024 * 1024)

    return {
        "machine": machine,
        "mode": mode,
        "ok": True,
        "skipped": False,
        "spins": actual_spins,
        "elapsed_s": round(elapsed, 1),
        "size_mb": round(size_mb, 2),
    }


# ── Main ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    # Expand ranges
    machines: list[str] = []
    for token in args.machines:
        machines.extend(_expand_machine_range(token))
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for m in machines:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    machines = unique

    out_dir = Path(args.out_dir) if args.out_dir else DEV_RAWDATA_DIR

    print(f"=== Batch Dev Sampler ===")
    print(f"Machines:    {', '.join(machines)} ({len(machines)} total)")
    print(f"Mode:        {args.mode}")
    print(f"Spins:       {args.spins:,} per machine ({args.robot_count} robots x "
          f"{args.spins // args.robot_count:,} spins)")
    print(f"Concurrency: {args.concurrency}")
    print(f"Output:      {out_dir}")
    print()

    results: list[dict[str, Any]] = []
    t_start = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        future_to_machine = {
            pool.submit(
                fetch_machine,
                machine=m,
                mode=args.mode,
                spins=args.spins,
                robot_count=args.robot_count,
                bet=args.bet,
                timeout=args.timeout,
                out_dir=out_dir,
            ): m
            for m in machines
        }

        for future in concurrent.futures.as_completed(future_to_machine):
            machine = future_to_machine[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                result = {"machine": machine, "mode": args.mode, "ok": False,
                          "error": str(exc)}

            results.append(result)
            # Live progress
            status = "SKIP" if result.get("skipped") else ("OK" if result["ok"] else "FAIL")
            detail = ""
            if result["ok"]:
                detail = f" ({result['size_mb']} MB"
                if not result.get("skipped"):
                    detail += f", {result['elapsed_s']}s"
                detail += ")"
            else:
                detail = f" — {result.get('error', '?')}"
            print(f"  [{status}] {machine} mode {args.mode}{detail}")

    total_time = time.time() - t_start
    ok_count = sum(1 for r in results if r["ok"])
    fail_count = len(results) - ok_count
    total_mb = sum(r.get("size_mb", 0) for r in results if r["ok"])

    print()
    print(f"Done in {total_time:.1f}s — {ok_count} OK, {fail_count} failed, "
          f"{total_mb:.1f} MB total")

    if fail_count:
        print("\nFailed machines:")
        for r in results:
            if not r["ok"]:
                print(f"  {r['machine']}: {r.get('error', '?')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
