"""Pool worker for ``BatchGenerateManager`` — runs analyzer.main() in a
dedicated subprocess so multiple (machine, mode) items can be processed
in parallel.

The in-process generate-report path (/api/rawdata/{m}/generate-report)
monkey-patches analyzer.post_json at the module level; concurrent calls
would race each other. Running each item in a subprocess gives each
call its own Python interpreter state, so the monkey-patch / sys.argv /
stdout swaps are cleanly isolated.

Worker functions live in a dedicated module (rather than inline in
app.py) because Windows multiprocessing uses ``spawn``, which pickles
the target callable + imports its module fresh in the worker. Keeping
the worker surface small keeps the spawned import tree cheap.

Mirrors the ``scripts/batch_generate_reports.py`` worker pattern; kept
separate so the console's pool doesn't depend on a script being in
sys.path.
"""
from __future__ import annotations

import contextlib
import io
import sys
import time
from pathlib import Path

# Populated lazily in _pool_worker_init(); cached across jobs within
# the same worker process so we only pay the analyzer-import cost once.
_analyzer_mod = None


def _pool_worker_init(root_path: str) -> None:
    """Pool initializer: pre-import analyzer module into this worker.

    Called once per worker process by ProcessPoolExecutor's
    ``initializer`` hook. Subsequent calls to run_analyzer_job reuse
    the cached module reference — saves ~800ms per job vs. repeated
    subprocess + import.
    """
    global _analyzer_mod
    if root_path not in sys.path:
        sys.path.insert(0, root_path)
    import fresh_slotlab.player_impact_analyzer as _mod
    _analyzer_mod = _mod


def run_analyzer_job(job: dict) -> dict:
    """Run analyzer.main() for one (machine, mode). Writes outputs to
    job['output_dir']. Returns a terse status dict; parent reads the
    actual summary.json from disk for final metrics + DB update.

    Expected job keys:
      machine (str), mode (int), chunk_dir (str), output_dir (str),
      run_id (str), progress_file (str), max_chunks (int),
      chunk_spin_times (int), chunk_robot_count (int), bet (int)
    """
    if _analyzer_mod is None:
        return {
            "machine": job.get("machine"),
            "mode": job.get("mode"),
            "ok": False,
            "error": "worker not initialized",
            "elapsed_s": 0.0,
        }
    machine = job["machine"]
    mode = int(job["mode"])
    output_dir = Path(job["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    argv = [
        "analyzer",
        "--machine", str(machine),
        "--rtp-mode", str(mode),
        "--bet", str(job.get("bet", 1000)),
        "--from-cache", str(job["chunk_dir"]),
        "--output-dir", str(output_dir),
        "--max-chunks", str(job["max_chunks"]),
        "--chunk-spin-times", str(job["chunk_spin_times"]),
        "--chunk-robot-count", str(job["chunk_robot_count"]),
        "--batch-concurrency", "1",
        # 0.001 keeps session-CI stop unreachable so max_chunks is
        # the sole termination gate (same rationale as in-process
        # _run_generate_report — see its comment for history).
        "--target-halfwidth-pp", "0.001",
        "--timeout", "30",
        "--run-id", str(job["run_id"]),
        "--progress-file", str(job["progress_file"]),
        "--bankruptcy-session-spins", "10000",
        "--bankruptcy-bankroll-multipliers", "100,200,500",
    ]
    orig_argv = sys.argv
    sys.argv = argv
    t0 = time.time()
    try:
        # analyzer.main() prints its summary JSON to stdout; silence it
        # here — we read the summary from disk instead.
        with contextlib.redirect_stdout(io.StringIO()):
            rc = _analyzer_mod.main()
        elapsed = round(time.time() - t0, 2)
        summary_file = output_dir / "player_impact_summary.json"
        if rc != 0:
            return {
                "machine": machine, "mode": mode, "ok": False,
                "error": f"analyzer rc={rc}",
                "elapsed_s": elapsed,
            }
        if not summary_file.exists():
            return {
                "machine": machine, "mode": mode, "ok": False,
                "error": "no summary generated",
                "elapsed_s": elapsed,
            }
        # Auto-run offline inference scripts so the UI's paytable-shape
        # + classifier panels stay in sync with the just-generated
        # report. Best-effort; a failure here doesn't fail the batch
        # item (analyzer output is already on disk).
        #
        # Rawdata root inheritance: both scripts respect
        # ``SLOT_RAWDATA_ROOT`` env — we derive it from
        # ``job['chunk_dir']`` (``<root>/<machine>/mode_<N>``) so the
        # scripts scan the same rawdata tree analyzer just read from.
        #
        # ``SLOT_SKIP_AUTO_INFER=1`` short-circuits the hook entirely —
        # tests use it to keep the batch-gen tight deadline (~10s).
        # Production leaves it unset so PayID 总览 / classifier panels
        # stay in sync with every fresh report.
        try:
            import os as _os
            if _os.environ.get("SLOT_SKIP_AUTO_INFER") != "1":
                import subprocess
                chunk_dir = Path(job["chunk_dir"])
                if chunk_dir.is_dir():
                    rawdata_root = chunk_dir.parent.parent
                    env = dict(_os.environ)
                    env.setdefault("SLOT_RAWDATA_ROOT", str(rawdata_root))
                    script_root = Path(sys.path[0]) if sys.path else Path(".")
                    for argv_ext in (
                        [str(script_root / "scripts" / "infer_paytable.py"),
                         "--machine", str(machine), "--mode", str(mode)],
                        [str(script_root / "scripts" / "verify_machine_labels.py"),
                         "--machines", str(machine), "--mode", str(mode)],
                    ):
                        if not Path(argv_ext[0]).exists():
                            continue
                        subprocess.run(
                            [sys.executable, *argv_ext],
                            capture_output=True, text=True,
                            # 300s covers the M1-size outlier (~70s
                            # for composition-breakdown on 384 chunks);
                            # small machines still return in <30s.
                            timeout=300, check=False, env=env,
                        )
        except Exception:
            pass  # best-effort post-analyzer hook
        return {
            "machine": machine, "mode": mode, "ok": True,
            "elapsed_s": elapsed,
        }
    except SystemExit as exc:
        # analyzer raises SystemExit on argparse / validation failures —
        # treat as per-item failure, don't kill the worker.
        return {
            "machine": machine, "mode": mode, "ok": False,
            "error": f"SystemExit: {exc}",
            "elapsed_s": round(time.time() - t0, 2),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "machine": machine, "mode": mode, "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_s": round(time.time() - t0, 2),
        }
    finally:
        sys.argv = orig_argv
