"""Batch-generate reports from dev_rawdata using --from-cache.

For each machine with a chunk file in dev_rawdata/, runs the full
analyzer pipeline offline and writes a report to reports/{machine}/mode_{mode}/.

Usage:
    python scripts/batch_generate_reports.py
    python scripts/batch_generate_reports.py --concurrency 4
    python scripts/batch_generate_reports.py --machines M1-M10
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANALYZER = ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
DEV_RAWDATA = ROOT / "dev_rawdata"
REPORTS_ROOT = ROOT / "reports"


def _expand_machine_range(token: str) -> list[str]:
    m = re.fullmatch(r"[Mm](\d+)-[Mm](\d+)", token)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return [f"M{i}" for i in range(lo, hi + 1)]
    return [token]


def find_machine_chunks(rawdata_dir: Path) -> list[tuple[str, int, Path]]:
    """Find all (machine, mode, chunk_dir) tuples."""
    results = []
    for machine_dir in sorted(
        rawdata_dir.iterdir(),
        key=lambda d: int(d.name[1:]) if d.name[1:].isdigit() else 0,
    ):
        if not machine_dir.is_dir():
            continue
        for mode_dir in sorted(machine_dir.iterdir()):
            if not mode_dir.is_dir():
                continue
            chunk_files = list(mode_dir.glob("chunk_*.json"))
            if not chunk_files:
                continue
            # Extract mode number from dir name "mode_2"
            mode_match = re.search(r"mode_(\d+)", mode_dir.name)
            mode = int(mode_match.group(1)) if mode_match else 1
            results.append((machine_dir.name, mode, mode_dir))
    return results


def run_report(
    machine: str,
    mode: int,
    chunk_dir: Path,
    reports_root: Path,
    force: bool = False,
) -> dict:
    """Run analyzer --from-cache for one machine-mode."""
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Read chunk to get a run-id-like hash
    chunk_file = next(chunk_dir.glob("chunk_*.json"), None)
    if not chunk_file:
        return {"machine": machine, "mode": mode, "ok": False, "error": "no_chunk"}

    raw = json.loads(chunk_file.read_text(encoding="utf-8"))
    bet = int(raw.get("_bet", 1000) or 1000)

    report_version = f"rv_{ts}_devcache"
    output_dir = reports_root / machine / f"mode_{mode}" / "versions" / report_version

    # Skip if a report already exists for this machine-mode (unless --force).
    if not force:
        existing_versions = reports_root / machine / f"mode_{mode}" / "versions"
        if existing_versions.is_dir():
            existing = [d for d in existing_versions.iterdir() if d.is_dir() and (d / "player_impact_summary.json").exists()]
            if existing:
                return {"machine": machine, "mode": mode, "ok": True, "skipped": True}

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(ANALYZER),
        "--machine", machine,
        "--rtp-mode", str(mode),
        "--bet", str(bet),
        "--from-cache", str(chunk_dir),
        "--output-dir", str(output_dir),
        "--max-chunks", "999",
    ]

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        elapsed = time.time() - t0
        if result.returncode != 0:
            # Clean up empty dir on failure
            try:
                output_dir.rmdir()
            except OSError:
                pass
            return {
                "machine": machine,
                "mode": mode,
                "ok": False,
                "error": result.stderr[:200] if result.stderr else f"exit_{result.returncode}",
                "elapsed_s": round(elapsed, 1),
            }
        # Verify summary file was created
        summary_file = output_dir / "player_impact_summary.json"
        if not summary_file.exists():
            return {
                "machine": machine,
                "mode": mode,
                "ok": False,
                "error": "no_summary_generated",
                "elapsed_s": round(elapsed, 1),
            }
        return {
            "machine": machine,
            "mode": mode,
            "ok": True,
            "skipped": False,
            "elapsed_s": round(elapsed, 1),
        }
    except subprocess.TimeoutExpired:
        return {"machine": machine, "mode": mode, "ok": False, "error": "timeout"}
    except Exception as exc:
        return {"machine": machine, "mode": mode, "ok": False, "error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--machines", nargs="*", default=None,
                        help="Machine names or ranges (default: all in dev_rawdata)")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if reports already exist")
    parser.add_argument("--rawdata-dir", type=Path, default=DEV_RAWDATA)
    parser.add_argument("--reports-root", type=Path, default=REPORTS_ROOT)
    args = parser.parse_args()

    all_chunks = find_machine_chunks(args.rawdata_dir)

    # Filter by --machines if specified
    if args.machines:
        allowed = set()
        for token in args.machines:
            allowed.update(_expand_machine_range(token))
        all_chunks = [(m, mode, d) for m, mode, d in all_chunks if m in allowed]

    if not all_chunks:
        print("No machine chunks found.")
        return

    print(f"=== Batch Report Generator ===")
    print(f"Machines: {len(all_chunks)} machine-modes")
    print(f"Concurrency: {args.concurrency}")
    print()

    results = []
    t_start = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        future_map = {
            pool.submit(run_report, m, mode, d, args.reports_root, args.force): (m, mode)
            for m, mode, d in all_chunks
        }
        for future in concurrent.futures.as_completed(future_map):
            m, mode = future_map[future]
            try:
                r = future.result()
            except Exception as exc:
                r = {"machine": m, "mode": mode, "ok": False, "error": str(exc)}
            results.append(r)

            status = "SKIP" if r.get("skipped") else ("OK" if r["ok"] else "FAIL")
            detail = f" ({r['elapsed_s']}s)" if "elapsed_s" in r else ""
            if not r["ok"]:
                detail = f" — {r.get('error', '?')}"
            print(f"  [{status}] {m} mode {mode}{detail}")

    total_time = time.time() - t_start
    ok = sum(1 for r in results if r["ok"])
    skip = sum(1 for r in results if r.get("skipped"))
    fail = sum(1 for r in results if not r["ok"])
    print(f"\nDone in {total_time:.1f}s — {ok} OK ({skip} skipped), {fail} failed")

    if fail:
        print("\nFailed:")
        for r in results:
            if not r["ok"]:
                print(f"  {r['machine']} mode {r['mode']}: {r.get('error')}")


if __name__ == "__main__":
    main()
