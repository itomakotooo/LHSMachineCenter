"""Batch-generate reports from rawdata using --from-cache.

For each machine with a chunk file in rawdata/, runs the full
analyzer pipeline offline and writes a report to reports/{machine}/mode_{mode}/.

Usage:
    python scripts/batch_generate_reports.py
    python scripts/batch_generate_reports.py --concurrency 4
    python scripts/batch_generate_reports.py --machines M1-M10
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import multiprocessing as mp
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANALYZER = ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
RAWDATA = ROOT / "rawdata"
# Dev-only tool: default output to dev_reports/ to keep production reports/ clean.
# Use --reports-root reports/ to override (e.g. for baseline generation).
REPORTS_ROOT = ROOT / "dev_reports"

# Populated in each pool worker's init; reused across jobs in that
# worker to avoid the per-job Python-interpreter + analyzer-import cost.
_analyzer_mod = None


def _pool_worker_init() -> None:
    """Pool initializer: pre-import analyzer module once per worker process.

    Cuts per-job overhead ~1s vs. the subprocess.run fallback. On
    Windows Pool uses spawn, so this runs once when the worker is
    first created — not per task.
    """
    global _analyzer_mod
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import fresh_slotlab.player_impact_analyzer as _mod
    _analyzer_mod = _mod


def _run_in_pool_worker(job: dict) -> dict:
    """Invoke analyzer.main() in-process for a single report job.

    Swaps sys.argv so analyzer's argparse works unchanged, silences
    its stdout (it prints a giant JSON summary intended for the
    CLI caller), and resets argv in a finally block.
    """
    assert _analyzer_mod is not None, "worker not initialized"
    machine = job["machine"]
    mode = job["mode"]
    chunk_dir = job["chunk_dir"]
    output_dir = Path(job["output_dir"])
    bet = job["bet"]
    max_chunks = job["max_chunks"]

    output_dir.mkdir(parents=True, exist_ok=True)
    argv = [
        "player_impact_analyzer.py",
        "--machine", machine,
        "--rtp-mode", str(mode),
        "--bet", str(bet),
        "--from-cache", str(chunk_dir),
        "--output-dir", str(output_dir),
        "--max-chunks", str(max_chunks),
    ]
    orig_argv = sys.argv
    sys.argv = argv
    t0 = time.time()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = _analyzer_mod.main()
        elapsed = round(time.time() - t0, 1)
        if rc != 0:
            return {"machine": machine, "mode": mode, "ok": False,
                    "error": f"rc={rc}", "elapsed_s": elapsed}
        if not (output_dir / "player_impact_summary.json").exists():
            return {"machine": machine, "mode": mode, "ok": False,
                    "error": "no_summary_generated", "elapsed_s": elapsed}
        return {"machine": machine, "mode": mode, "ok": True,
                "skipped": False, "elapsed_s": elapsed}
    except SystemExit as exc:
        # analyzer raises SystemExit for validation errors — treat as
        # data-level failure, don't kill the worker.
        return {"machine": machine, "mode": mode, "ok": False,
                "error": f"SystemExit: {exc}",
                "elapsed_s": round(time.time() - t0, 1)}
    except Exception as exc:  # noqa: BLE001
        return {"machine": machine, "mode": mode, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": round(time.time() - t0, 1)}
    finally:
        sys.argv = orig_argv


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


def _peek_chunk_spins(chunk_path: Path) -> tuple[int, int]:
    """Pull (spin_times, robot_count) from the chunk envelope's first
    bytes without loading the full response payload. Chunk envelopes
    start with the small metadata fields before the big ``response``
    array, so a 1 KiB read is enough. Returns (0, 0) on any failure.

    Used by the batch script to pick just enough chunks to hit a
    target spin count — robust to chunks that aren't the standard
    10k (cancelled runs, non-default sampler config, future changes).
    """
    import re
    try:
        with chunk_path.open("rb") as f:
            head = f.read(1024).decode("utf-8", errors="ignore")
    except OSError:
        return 0, 0
    st = re.search(r'"_spin_times"\s*:\s*(\d+)', head)
    rc = re.search(r'"_robot_count"\s*:\s*(\d+)', head)
    return (int(st.group(1)) if st else 0,
            int(rc.group(1)) if rc else 0)


def _build_pool_jobs(
    all_chunks,
    reports_root: Path,
    force: bool,
    target_spins: int,
) -> list[dict]:
    """Pre-compute per-job context and filter out skipped jobs."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    jobs = []
    for machine, mode, chunk_dir in all_chunks:
        chunks_sorted = sorted(chunk_dir.glob("chunk_*.json"))
        if not chunks_sorted:
            jobs.append({"_skip_reason": "no_chunk",
                         "machine": machine, "mode": mode})
            continue
        if not force:
            existing_versions = reports_root / machine / f"mode_{mode}" / "versions"
            if existing_versions.is_dir():
                existing = [d for d in existing_versions.iterdir()
                            if d.is_dir() and (d / "player_impact_summary.json").exists()]
                if existing:
                    jobs.append({"_skip": True, "machine": machine, "mode": mode})
                    continue
        # Accumulate chunks until we reach target_spins (default 10k
        # for dev). Falls through to "use all" when total available
        # is less than target — correct behaviour for machines with a
        # partial / small-chunk cache. ``target_spins <= 0`` disables
        # the cap entirely (prod / baseline regen path).
        bet = 1000
        chunks_needed = 0
        cum_spins = 0
        for cf in chunks_sorted:
            spin_times, robot_count = _peek_chunk_spins(cf)
            chunk_spins = spin_times * robot_count
            chunks_needed += 1
            cum_spins += chunk_spins
            if chunks_needed == 1:
                # Read full envelope for the first chunk only — need
                # _bet for the analyzer invocation. Cheap enough.
                try:
                    raw = json.loads(cf.read_text(encoding="utf-8"))
                    bet = int(raw.get("_bet", 1000) or 1000)
                except Exception:  # noqa: BLE001
                    pass
            if target_spins > 0 and cum_spins >= target_spins:
                break
        output_dir = reports_root / machine / f"mode_{mode}" / "versions" / f"rv_{ts}_devcache"
        jobs.append({
            "machine": machine,
            "mode": mode,
            "chunk_dir": str(chunk_dir),
            "output_dir": str(output_dir),
            "bet": bet,
            "max_chunks": chunks_needed if target_spins > 0 else 9999,
            "target_spins": target_spins,
            "available_spins": cum_spins,
        })
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--machines", nargs="*", default=None,
                        help="Machine names or ranges (default: all in rawdata)")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if reports already exist")
    parser.add_argument("--rawdata-dir", type=Path, default=RAWDATA)
    parser.add_argument("--reports-root", type=Path, default=REPORTS_ROOT)
    parser.add_argument(
        "--target-spins-per-mode", type=int, default=10_000,
        help=(
            "Target sample size per (machine, mode) for dev regen. "
            "Script reads chunk envelopes lightly to pick just enough "
            "chunks to reach this many spins (default 10k ≈ 1 "
            "standard chunk). Machines with less cached total are "
            "processed with whatever's available — reports still "
            "emit but will be noisy (flagged below as LOW_SPINS). "
            "Pass 0 for an uncapped full-cache pass (prod baseline)."
        ),
    )
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
    print(f"Concurrency: {args.concurrency} (pool, in-process)")
    ts_label = f"{args.target_spins_per_mode}" if args.target_spins_per_mode > 0 else "uncapped"
    print(f"Target spins per (machine, mode): {ts_label}")
    print()

    results = []
    t_start = time.time()

    # multiprocessing.Pool with pre-imported analyzer: each worker calls
    # analyzer.main() directly, bypassing subprocess + interpreter +
    # import cost per job.
    jobs = _build_pool_jobs(all_chunks, args.reports_root, args.force, args.target_spins_per_mode)
    # Report skips upfront (no worker cost for these)
    runnable = []
    for j in jobs:
        if j.get("_skip"):
            r = {"machine": j["machine"], "mode": j["mode"], "ok": True, "skipped": True}
            results.append(r)
            print(f"  [SKIP] {j['machine']} mode {j['mode']} — existing report")
        elif j.get("_skip_reason") == "no_chunk":
            # Missing rawdata is legitimately skippable (machine never
            # sampled). Count as skip, not fail.
            r = {"machine": j["machine"], "mode": j["mode"], "ok": True,
                 "skipped": True, "skip_reason": "no_rawdata"}
            results.append(r)
            print(f"  [SKIP] {j['machine']} mode {j['mode']} — no rawdata")
        elif j.get("_skip_reason"):
            r = {"machine": j["machine"], "mode": j["mode"], "ok": False,
                 "error": j["_skip_reason"]}
            results.append(r)
            print(f"  [FAIL] {j['machine']} mode {j['mode']} — {j['_skip_reason']}")
        else:
            # Flag low-sample jobs upfront so operator sees the
            # warning alongside the [OK] line.
            avail = j.get("available_spins", 0)
            target = j.get("target_spins", 0)
            if target > 0 and avail < min(1000, target):
                j["_low_spins"] = avail
            runnable.append(j)

    if runnable:
        # imap_unordered so results stream as they finish (progress
        # feedback) rather than waiting for the whole batch.
        with mp.Pool(processes=args.concurrency, initializer=_pool_worker_init) as pool:
            # Carry the pre-computed low_spins flag forward into
            # results so the output line can include a warning.
            runnable_by_key = {(j["machine"], j["mode"]): j for j in runnable}
            for r in pool.imap_unordered(_run_in_pool_worker, runnable):
                src = runnable_by_key.get((r["machine"], r["mode"]), {})
                low = src.get("_low_spins")
                if low is not None:
                    r["low_spins"] = low
                results.append(r)
                status = "OK" if r["ok"] else "FAIL"
                detail = f" ({r.get('elapsed_s', '?')}s)"
                if not r["ok"]:
                    detail = f" — {r.get('error', '?')}"
                elif low is not None:
                    detail += f"  [WARN only {low} spins available — report noisy]"
                print(f"  [{status}] {r['machine']} mode {r['mode']}{detail}")

    total_time = time.time() - t_start
    ok = sum(1 for r in results if r["ok"])
    skip = sum(1 for r in results if r.get("skipped"))
    no_data = sum(1 for r in results if r.get("skip_reason") == "no_rawdata")
    low = sum(1 for r in results if r.get("low_spins") is not None)
    fail = sum(1 for r in results if not r["ok"])
    print(f"\nDone in {total_time:.1f}s — {ok} OK ({skip} skipped), {fail} failed")
    if no_data:
        print(f"  skipped (no rawdata): {no_data}")
    if low:
        print(f"  low-sample warnings (<1000 spins): {low}")

    if fail:
        print("\nFailed:")
        for r in results:
            if not r["ok"]:
                print(f"  {r['machine']} mode {r['mode']}: {r.get('error')}")
    if low:
        print("\nLow-sample (report noisy, resample for accuracy):")
        for r in results:
            if r.get("low_spins") is not None:
                print(f"  {r['machine']} mode {r['mode']}: {r['low_spins']} spins")


if __name__ == "__main__":
    main()
