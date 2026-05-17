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
# Captured here (rather than read from sys.path[0] at job-time) because
# third-party imports or analyzer.main() can reorder sys.path — the
# post-analyzer hook needs a stable anchor to locate scripts/.
_project_root: str | None = None


def _pool_worker_init(root_path: str) -> None:
    """Pool initializer: pre-import analyzer module into this worker.

    Called once per worker process by ProcessPoolExecutor's
    ``initializer`` hook. Subsequent calls to run_analyzer_job reuse
    the cached module reference — saves ~800ms per job vs. repeated
    subprocess + import.
    """
    global _analyzer_mod, _project_root
    _project_root = root_path
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
        # 2026-04-22: disable Tier-2 non-convergence abort. With
        # target=0.001pp the abort's (ci/target)² projection always
        # overflows the chunks-budget ceiling and bails at the 20-
        # chunk floor. Batch generate-report is exhaustive replay,
        # never targeting a real CI — abort is user-facing sampling
        # logic only. Mirrors the fix in in-process _run_generate_report.
        "--disable-non-convergence-abort",
        "--timeout", "30",
        "--run-id", str(job["run_id"]),
        "--progress-file", str(job["progress_file"]),
        "--bankruptcy-session-spins", "10000",
        "--bankruptcy-bankroll-multipliers", "10,100,200,500",
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
        # KNOWN GAP (P1-B2 R1 + P1-A4 R1) — see PHASE_1_TICKETS.md
        # "Known follow-ups" section. This worker is missing TWO post-
        # analyzer steps that _run_generate_report applies (app.py:7083):
        #   1. patch_summary_md5(summary_file, lookup_fn=...) so virtual
        #      machines do not land in rwtree with md5_status=untagged
        #   2. forwarding --upstream-config-md5 / --upstream-code-md5
        #      CLI args to the analyzer subprocess so historical-md5
        #      chunks are filtered out of the current-md5 baseline
        # Both gaps stem from the same architectural shortcut: this
        # worker is a leaner driver than _run_generate_report. A unified
        # follow-up ticket should bring this worker to parity. Until
        # then, virtual-machine batch reports may have empty md5 fields
        # AND batch reports may unknowingly include historical chunks.
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
        hook_results: list[dict] = []
        try:
            import os as _os
            if _os.environ.get("SLOT_SKIP_AUTO_INFER") == "1":
                hook_results.append({"skip": "env_SLOT_SKIP_AUTO_INFER"})
            else:
                import subprocess
                chunk_dir = Path(job["chunk_dir"])
                if not chunk_dir.is_dir():
                    hook_results.append({
                        "skip": "chunk_dir_missing",
                        "chunk_dir": str(chunk_dir),
                    })
                else:
                    rawdata_root = chunk_dir.parent.parent
                    env = dict(_os.environ)
                    env.setdefault("SLOT_RAWDATA_ROOT", str(rawdata_root))
                    # Use the root captured in the pool initializer —
                    # reading sys.path[0] at job-time is fragile because
                    # analyzer.main() / third-party imports can reorder
                    # sys.path. Fall back to CWD only if init somehow
                    # didn't run (shouldn't happen in the pool path).
                    script_root = (
                        Path(_project_root) if _project_root else Path(".")
                    )
                    # Record the resolution context once per item so
                    # operators can distinguish "script_root pointed at
                    # the wrong dir" from "subprocess hit a real error."
                    hook_results.append({
                        "context": {
                            "script_root": str(script_root),
                            "project_root": _project_root,
                            "sys_executable": sys.executable,
                            "sys_path_0": sys.path[0] if sys.path else None,
                            "rawdata_root": str(rawdata_root),
                        },
                    })
                    # Forward parent-app's paytables_dir / classify_dir
                    # to the scripts' --output-dir args so hook artefacts
                    # land in the right tree for alternate-universe callers
                    # (tests, virtual console). Missing keys → scripts use
                    # their built-in defaults (configs/paytables + dev_reports/
                    # _classify) — unchanged behaviour for real console.
                    pt_argv = [
                        str(script_root / "scripts" / "infer_paytable.py"),
                        "--machine", str(machine), "--mode", str(mode),
                    ]
                    if job.get("paytables_dir"):
                        pt_argv += ["--output-dir", str(job["paytables_dir"])]
                    cls_argv = [
                        str(script_root / "scripts" / "verify_machine_labels.py"),
                        "--machines", str(machine), "--mode", str(mode),
                    ]
                    if job.get("classify_dir"):
                        cls_argv += ["--output-dir", str(job["classify_dir"])]
                    for name, argv_ext in (
                        ("paytable_shape", pt_argv),
                        ("classifier", cls_argv),
                    ):
                        if not Path(argv_ext[0]).exists():
                            hook_results.append({
                                "hook": name,
                                "skip": "script_missing",
                                "path": argv_ext[0],
                            })
                            continue
                        try:
                            proc = subprocess.run(
                                [sys.executable, *argv_ext],
                                capture_output=True, text=True,
                                # 300s covers the M1-size outlier
                                # (~70s for composition-breakdown on
                                # 384 chunks); small machines <30s.
                                timeout=300, check=False, env=env,
                            )
                            hook_results.append({
                                "hook": name,
                                "rc": proc.returncode,
                                "stderr_tail": (proc.stderr or "")[-200:],
                            })
                        except subprocess.TimeoutExpired:
                            hook_results.append({"hook": name, "timeout": True})
                        except Exception as exc:  # noqa: BLE001
                            hook_results.append({
                                "hook": name,
                                "err": f"{type(exc).__name__}: {exc}",
                            })
        except Exception as exc:  # noqa: BLE001
            hook_results.append({"outer_err": f"{type(exc).__name__}: {exc}"})
        return {
            "machine": machine, "mode": mode, "ok": True,
            "elapsed_s": elapsed,
            "post_hook": hook_results,
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
