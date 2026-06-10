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

P1-D1 parity additions (ticket §3 C1-C4):
  C2 — forward --upstream-config-md5 / --upstream-code-md5 from job dict
  C3 — call patch_summary_md5 after analyzer returns (shared canonical)
  C4 — call run_post_analyzer_inference after patch (shared canonical)
"""
from __future__ import annotations

import contextlib
import io
import sys
import time
from pathlib import Path

# Populated lazily in _pool_worker_init(); cached across jobs within
# the same worker process so we only pay the analyzer-import cost once.
# Phase 2b: _analyzer_mod is retained for signature compat but is no
# longer used; generation goes through _report_engine_mod instead.
_analyzer_mod = None
_report_engine_mod = None  # fresh_slotlab.analyzer.report_engine (phase 2b)
# Captured here (rather than read from sys.path[0] at job-time) because
# third-party imports or analyzer.main() can reorder sys.path — the
# post-analyzer hook needs a stable anchor to locate scripts/.
_project_root: str | None = None

# C3/C4 canonical helpers — pre-imported at initializer time per memory
# feedback_subprocess_import_suicide_and_module_globals.md (worker pool
# initializer pattern). These are set to the real module objects by
# _pool_worker_init; tests may substitute fakes.
_patch_summary_md5_fn = None   # fresh_slotlab.summary_md5_patch.patch_summary_md5
_run_post_inference_fn = None  # fresh_slotlab.post_inference.run_post_analyzer_inference
_lookup_machine_md5_fn = None  # fresh_slotlab.machine_md5.lookup_machine_md5
_extract_base_machine_name_fn = None  # machine_variants.extract_base_machine_name (variant→base)


def _pool_worker_init(root_path: str) -> None:
    """Pool initializer: pre-import analyzer module into this worker.

    Called once per worker process by ProcessPoolExecutor's
    ``initializer`` hook. Subsequent calls to run_analyzer_job reuse
    the cached module reference — saves ~800ms per job vs. repeated
    subprocess + import.

    Also pre-imports the P1-D1 canonical helpers (C3/C4) so they are
    available at job time without live module reads (per memory
    feedback_subprocess_import_suicide_and_module_globals.md §C6).

    Phase 2b: imports report_engine (the new SpinType-native orchestrator)
    instead of the deleted player_impact_analyzer. _analyzer_mod is kept
    None (no longer used for generation) so existing callers that test
    ``_analyzer_mod is None`` stay compatible.
    """
    global _analyzer_mod, _report_engine_mod, _project_root
    global _patch_summary_md5_fn, _run_post_inference_fn, _lookup_machine_md5_fn
    global _extract_base_machine_name_fn
    _project_root = root_path
    if root_path not in sys.path:
        sys.path.insert(0, root_path)
    # _analyzer_mod: kept None — the deleted player_impact_analyzer is gone.
    _analyzer_mod = None
    # Phase 2b: pre-import the new report engine.
    try:
        import fresh_slotlab.analyzer.report_engine as _rem
        _report_engine_mod = _rem
    except Exception as _exc:
        import sys as _sys
        print(
            f"batch_gen_worker: could not import report_engine: {_exc}",
            file=_sys.stderr,
        )
        _report_engine_mod = None
    # C3 — canonical summary md5 patcher (P1-B2)
    from fresh_slotlab.summary_md5_patch import patch_summary_md5 as _psm
    _patch_summary_md5_fn = _psm
    # C4 — canonical inference trigger (P1-B5)
    from fresh_slotlab.post_inference import run_post_analyzer_inference as _rpi
    _run_post_inference_fn = _rpi
    # C3 — canonical real-machine md5 lookup (P1-B1)
    from fresh_slotlab.machine_md5 import lookup_machine_md5 as _lmm
    _lookup_machine_md5_fn = _lmm
    # Variant→base resolver, pre-imported per C6 (no live module read at job time).
    # Graceful: if it cannot import, leave None → run_analyzer_job treats machine as
    # its own base (non-variant behaviour, the pre-fix status quo).
    try:
        from src.web_console.backend.machine_variants import extract_base_machine_name as _ebm
        _extract_base_machine_name_fn = _ebm
    except Exception as _exc:  # noqa: BLE001
        import sys as _sys
        print(
            f"batch_gen_worker: could not import extract_base_machine_name "
            f"(variant resolution disabled for batch): {_exc}",
            file=_sys.stderr,
        )
        _extract_base_machine_name_fn = None


def run_analyzer_job(job: dict) -> dict:
    """Run report generation for one (machine, mode). Writes outputs to
    job['output_dir']. Returns a terse status dict; parent reads the
    actual summary.json from disk for final metrics + DB update.

    Phase 2b: uses report_engine.generate_report_from_chunks for
    registered machines (configs/machine_manifests/<M>.json exists).
    Non-registered machines return a clear per-item "not registered" status.

    Expected job keys:
      machine (str), mode (int), chunk_dir (str), output_dir (str),
      run_id (str), progress_file (str), max_chunks (int),
      chunk_spin_times (int), chunk_robot_count (int), bet (int),
      upstream_config_md5 (str), upstream_code_md5 (str)  [P1-D1 C1/C2]
      machines_config (str)                               [P1-D1 C3]
    """
    machine = job.get("machine") or ""
    mode_raw = job.get("mode")
    if not machine or mode_raw is None:
        return {
            "machine": machine,
            "mode": mode_raw,
            "ok": False,
            "error": "job missing required 'machine' or 'mode' key",
            "elapsed_s": 0.0,
        }
    mode = int(mode_raw)
    output_dir = Path(job["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    # Phase 2b: use the new report engine for registered machines.
    _rem = _report_engine_mod
    if _rem is None:
        # Engine not available — try lazy import (e.g. unit-test callers
        # that bypass _pool_worker_init).
        try:
            import fresh_slotlab.analyzer.report_engine as _rem  # noqa: PLC0415
        except Exception as _exc:
            return {
                "machine": machine, "mode": mode, "ok": False,
                "error": f"report_engine not available: {_exc}",
                "elapsed_s": 0.0,
            }

    # Registered check: configs/machine_manifests/<machine>.json must exist.
    # Resolve the manifests root relative to this worker's project root or
    # fall back to repo-relative default from the engine module.
    _root = Path(_project_root) if _project_root else Path(_rem.__file__).resolve().parent.parent.parent
    _manifests_root = _root / "configs" / "machine_manifests"
    # Variant resolution — MIRROR of app.py._run_generate_report: a variant
    # (machine_id with a "$" selector suffix) shares the underlying base's parsing
    # and has no manifest of its own. Resolve the base, register against it, and pass
    # manifest_machine_id so the engine uses the base's manifest while keeping the
    # variant's identity. Uses the resolver pre-imported in _pool_worker_init (C6 — no
    # live module read at job time); if unavailable, machine is its own base (non-variant).
    _base_machine = (
        _extract_base_machine_name_fn(machine) if _extract_base_machine_name_fn else machine
    )
    if not (_manifests_root / f"{_base_machine}.json").exists():
        return {
            "machine": machine, "mode": mode, "ok": False,
            "error": (
                f"machine {machine} is not registered for the SpinType-native engine "
                f"(no configs/machine_manifests/{_base_machine}.json); "
                "see docs/ANALYZER_ARCHITECTURE.md"
            ),
            "elapsed_s": 0.0,
        }

    chunk_dir = Path(job["chunk_dir"])
    run_id = str(job["run_id"])
    t0 = time.time()
    try:
        _rem.generate_report_from_chunks(
            machine, mode,
            chunk_dir=chunk_dir,
            output_dir=output_dir,
            run_id=run_id,
            manifest_machine_id=_base_machine,
        )
        elapsed = round(time.time() - t0, 2)
        summary_file = output_dir / "player_impact_summary.json"
        if not summary_file.exists():
            return {
                "machine": machine, "mode": mode, "ok": False,
                "error": "no summary generated",
                "elapsed_s": elapsed,
            }

        # C3 (P1-D1 §3 C3): patch empty md5 tags in the written summary
        # via the canonical shared helper (P1-B2 dedup). Virtual machines
        # leave config_md5 / code_md5 empty in the summary because the
        # real analyzer only reads configs/machines.json (real-machine
        # registry). Without this patch the rwtree cell shows
        # md5_status=untagged even though the report IS current.
        # Mirrors the patch in _run_generate_report (app.py lines 7221-7229).
        # Best-effort: failure is logged to stderr but does NOT fail the item.
        #
        # Use pre-imported module globals (set by _pool_worker_init) when
        # available (C6 — no live module reads at job time for pool workers).
        # Fall back to lazy import for callers that didn't go through
        # _pool_worker_init (unit tests, alternate call paths) — the lazy
        # import is safe here because this module has no import-time side
        # effects per fresh_slotlab.summary_md5_patch contract.
        try:
            _psm = _patch_summary_md5_fn
            _lmm = _lookup_machine_md5_fn
            if _psm is None:
                from fresh_slotlab.summary_md5_patch import patch_summary_md5 as _psm  # noqa: PLC0415
            # P1-D1 round-2 critic SQ2 fix (CRITICAL):
            # original used lookup_machine_md5() which is the FLAT-SCHEMA
            # reader from fresh_slotlab.machine_md5 — does NOT interpret
            # modesMd5. For virtual machines (M1sim etc.) whose top-level
            # configSummaryMd5 is "" with per-mode values in modesMd5
            # blocks, the flat reader returns ("","") → patch_summary_md5
            # skips per its line 107 guard → virtual batch reports remained
            # md5_status=untagged. Silent no-op for the most important
            # case (the very gap P1-B2 was supposed to close).
            # Fix: use the per-mode md5 values already resolved by
            # _prepare_batch_gen_item via _get_machine_md5(machine, mc,
            # mode=mode) and threaded into the job dict (C1 keys). These
            # values handle both flat (real) and modesMd5 (virtual)
            # schemas correctly via app.py:_get_machine_md5.
            _upstream_cfg = job.get("upstream_config_md5", "") or ""
            _upstream_code = job.get("upstream_code_md5", "") or ""
            def _md5_lookup(
                _cfg=_upstream_cfg, _code=_upstream_code,
            ) -> tuple[str, str]:
                return _cfg, _code
            _psm(
                summary_file,
                _md5_lookup,
                machine=machine,
                mode=mode,
            )
        except Exception as exc:  # noqa: BLE001
            # Non-fatal: log and continue — analyzer output is valid.
            print(
                f"batch_gen_worker: patch_summary_md5 failed for "
                f"machine={machine!r} mode={mode!r}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

        # C4 (P1-D1 §3 C4): trigger offline inference scripts via the
        # canonical shared helper (P1-B5 dedup). Replaces the legacy
        # inline subprocess block that required script_root resolution
        # and ran scripts individually. The canonical helper handles
        # SLOT_SKIP_AUTO_INFER, failure diagnostics on disk, and
        # _post_inference_failure.json persistence per memory
        # feedback_no_silent_swallow.md.
        #
        # Use pre-imported module global (set by _pool_worker_init) when
        # available (C6). Fall back to lazy import for callers that didn't
        # go through _pool_worker_init (unit tests, alternate call paths).
        hook_results: list[dict] = []
        try:
            _rpi = _run_post_inference_fn
            if _rpi is None:
                from fresh_slotlab.post_inference import run_post_analyzer_inference as _rpi  # noqa: PLC0415
            import os as _os
            _chunk_dir_for_infer = chunk_dir
            rawdata_root = _chunk_dir_for_infer.parent.parent if _chunk_dir_for_infer.is_dir() else None
            env = dict(_os.environ)
            if rawdata_root is not None:
                env.setdefault("SLOT_RAWDATA_ROOT", str(rawdata_root))
            infer_result = _rpi(
                summary_path=summary_file,
                paytables_dir=job.get("paytables_dir") or None,
                classify_dir=job.get("classify_dir") or None,
                opts={
                    "machine": machine,
                    "mode": mode,
                    "scripts_dir": (
                        Path(_project_root) / "scripts"
                        if _project_root else None
                    ),
                    "rawdata_root": rawdata_root,
                    # C4/C6: pass pre-snapshotted env so no live
                    # os.environ read happens in the worker (per
                    # memory feedback_subprocess_import_suicide_and_
                    # module_globals.md).
                    "env": env,
                    "sys_executable": sys.executable,
                    "worker_snapshot": {
                        "project_root": _project_root,
                        "sys_path_0": sys.path[0] if sys.path else None,
                        "sys_executable": sys.executable,
                    },
                },
            )
            # Serialise InferenceResult into the hook_results list so
            # _finalize_batch_gen_item can persist it to _post_hook.json.
            hook_entry: dict = {
                "canonical_post_inference": True,
                "machine": infer_result.machine,
                "mode": infer_result.mode,
            }
            if infer_result.skipped:
                # Use "skip" key for backward compat with test_batch_worker_post_hook.py
                # and the C4 test assertions (both check `"skip" in entry`).
                hook_entry["skip"] = infer_result.skipped
            if infer_result.failed:
                hook_entry["failed"] = True
            for s in infer_result.scripts:
                hook_entry[s.name] = {
                    "ok": s.ok,
                    "rc": s.rc,
                    "stderr_tail": s.stderr_tail,
                    "error": s.error,
                    "wall_time_seconds": s.wall_time_seconds,
                }
            hook_results.append(hook_entry)
        except Exception as exc:  # noqa: BLE001
            hook_results.append({
                "canonical_post_inference": True,
                "outer_err": f"{type(exc).__name__}: {exc}",
            })

        return {
            "machine": machine, "mode": mode, "ok": True,
            "elapsed_s": elapsed,
            "post_hook": hook_results,
        }
    except SystemExit as exc:
        # report_engine raises SystemExit on hard errors (topo-sort failure, etc.)
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
