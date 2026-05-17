"""Shared helper for triggering offline inference scripts after a successful
analyzer run (Ticket P1-B5).

Two callsites independently trigger the same pair of scripts:

  α) ``src/web_console/backend/app.py:_run_post_analyzer_inference``
     (in-process generate-report path; fires from daemon thread)
  β) ``slot_designer/core/backend/virtual_analyzer.py:_run_inference_scripts``
     (virtual-analyzer subprocess; fires after delegate returns)

Both fire ``scripts/infer_paytable.py`` and ``scripts/verify_machine_labels.py``
for a given (machine, mode). This module provides the single canonical
implementation; both callsites become thin wrappers that inject their
context (script paths, rawdata root, output dirs).

Contract
--------
C1 — Single helper with explicit path args:
    ``run_post_analyzer_inference(summary_path, paytables_dir, classify_dir,
    opts) -> InferenceResult``. Both callers pass paths explicitly.

C2 — Both callsites use helper:
    app.py and virtual_analyzer.py become thin invocations.

C3 — Failure diagnostic on disk:
    If either subprocess returns rc != 0 (or cannot be started), the helper
    writes ``<summary_dir>/_post_inference_failure.json`` containing:
    ``script_name``, ``rc``, ``stderr_tail`` (last 50 lines), ``argv``,
    ``cwd``, ``wall_time_seconds``. Then logs to stderr. Does NOT raise.
    Does NOT silently swallow. (memory ``feedback_no_silent_swallow.md``)

C4 — Worker resource snapshot:
    When invoked from a worker pool context, callers MUST pass an explicit
    ``env`` dict (snapshotted by the worker initializer) via ``opts``.
    The helper never reads ``os.environ`` live if ``opts["env"]`` is given.

No side effects on import
-------------------------
Per memory ``feedback_subprocess_import_suicide_and_module_globals.md``:
this module has NO import-time side effects. No app construction, no
subprocess spawn, no global-state mutation.

Citing:
- ``session_artifacts/_arch/01_pipeline_map.md §4`` row 5 (inference scripts
  trigger)
- ``session_artifacts/_arch/03_coupling_audit.md §4.5`` (duplicate primitives)
- ``session_artifacts/_arch/08_handoff.md §4 Phase 1`` (inference-trigger × 2)
- memory ``feedback_no_silent_swallow.md``
- memory ``feedback_perf_claim_needs_e2e_event_stream.md``
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ScriptResult:
    """Outcome of running one inference script subprocess."""

    name: str
    ok: bool
    rc: int | None = None
    argv: list[str] = field(default_factory=list)
    cwd: str = ""
    stderr_tail: str = ""
    error: str | None = None
    wall_time_seconds: float = 0.0


@dataclass
class InferenceResult:
    """Aggregated outcome for one (machine, mode) inference pass."""

    machine: str = "<unknown>"
    mode: int = 0
    skipped: str | None = None          # non-None → neither script was run
    failed: bool = False                 # True when any script rc != 0
    scripts: list[ScriptResult] = field(default_factory=list)


def run_post_analyzer_inference(
    summary_path: Path | str,
    paytables_dir: Path | str | None,
    classify_dir: Path | str | None,
    opts: dict[str, Any],
) -> InferenceResult:
    """Run infer_paytable + verify_machine_labels for one (machine, mode).

    This is the canonical shared implementation — both the real-console
    in-process path and the virtual-analyzer subprocess path delegate here.

    Parameters
    ----------
    summary_path:
        Path to ``player_impact_summary.json`` written by the analyzer.
        Used (a) to derive the summary directory for failure-diagnostic
        persistence (C3) and (b) to read ``machine`` / ``mode`` from the
        summary JSON when those keys are absent from ``opts``.
    paytables_dir:
        ``--output-dir`` forwarded to ``infer_paytable.py``.
        ``None`` → script uses its built-in default (``configs/paytables``).
    classify_dir:
        ``--output-dir`` forwarded to ``verify_machine_labels.py``.
        ``None`` → script uses its built-in default (``dev_reports/_classify``).
    opts:
        Configuration dictionary.  Recognised keys (all optional):

        ``machine`` (str):
            Machine identifier, e.g. ``"M1"``. Defaults to reading from
            summary JSON, then ``"<unknown>"``.
        ``mode`` (int):
            RTP mode integer. Defaults to reading from summary JSON, then 0.
        ``infer_paytable_script`` (str | Path):
            Explicit path to ``infer_paytable.py``.  Takes priority over
            ``scripts_dir``. When absent, derived from ``scripts_dir`` or
            auto-resolved relative to this module's repo root.
        ``verify_labels_script`` (str | Path):
            Explicit path to ``verify_machine_labels.py``.  Same logic.
        ``scripts_dir`` (Path | str):
            Directory containing both scripts.  Used when the explicit
            per-script keys are absent.
        ``rawdata_root`` (Path | str | None):
            When set, forwarded as ``SLOT_RAWDATA_ROOT`` env var so scripts
            scan the correct rawdata tree. ``None`` → inherit parent env.
        ``env`` (dict[str, str] | None):
            Full environment dict for subprocesses. When set (worker pool
            path, test path), used verbatim so no live ``os.environ`` read
            happens in the worker (C4). When ``None``, falls back to
            ``os.environ`` copy at call time.
        ``timeout_sec`` (float, default 300.0):
            Per-script subprocess timeout in seconds.
        ``log_to_dir`` (Path | str | None):
            When set, writes the full result dict to
            ``<log_to_dir>/_post_hook.json`` (same contract as the
            batch-gen worker). Disabled by default — callers that want
            a separate hook log opt in explicitly.
        ``skip_env_var`` (str, default ``"SLOT_SKIP_AUTO_INFER"``):
            Env var name that, when set to ``"1"``, short-circuits both
            scripts and records a skip marker.
        ``sys_executable`` (str):
            Python executable used to launch subprocesses. Defaults to
            ``sys.executable`` at call time.
        ``worker_snapshot`` (dict):
            Worker-context resource snapshot (sys_path_0, cwd, env_extras).
            Accepted and stored on the result for diagnostics; the helper
            never reads live sys.path at job time (C4).

    Returns
    -------
    InferenceResult
        Always returns (never raises). ``InferenceResult.failed`` is True
        when any script returned non-zero; ``InferenceResult.skipped`` is
        non-None when no scripts ran.

    Side effects
    ------------
    * Writes ``<summary_dir>/_post_inference_failure.json`` when any script
      fails (rc != 0 or unlaunchable) — C3.
    * Writes ``<log_to_dir>/_post_hook.json`` when ``log_to_dir`` is given.
    * Logs failures to ``sys.stderr`` — C3, never silently swallows.
    * Creates ``paytables_dir`` / ``classify_dir`` when non-None and they
      don't exist yet.
    """
    summary_path = Path(summary_path)
    summary_dir = summary_path.parent

    # --- Resolve machine / mode -------------------------------------------
    machine: str = str(opts.get("machine", ""))
    mode_raw = opts.get("mode", None)
    if not machine or mode_raw is None:
        # Try to read from the summary JSON.
        _summary_meta = _read_summary_meta(summary_path)
        if not machine:
            machine = str(_summary_meta.get("machine", "<unknown>"))
        if mode_raw is None:
            mode_raw = _summary_meta.get("mode", 0)
    mode: int = int(mode_raw if mode_raw is not None else 0)

    # --- Resolve script paths ---------------------------------------------
    scripts_dir_raw = opts.get("scripts_dir")
    if scripts_dir_raw is not None:
        _scripts_dir = Path(scripts_dir_raw)
    else:
        # Auto-resolve: this module is at fresh_slotlab/post_inference.py,
        # scripts/ is at repo_root/scripts/.
        _scripts_dir = Path(__file__).resolve().parent.parent / "scripts"

    paytable_script = Path(
        opts.get("infer_paytable_script") or (_scripts_dir / "infer_paytable.py")
    )
    classify_script = Path(
        opts.get("verify_labels_script") or (_scripts_dir / "verify_machine_labels.py")
    )

    timeout_sec: float = float(opts.get("timeout_sec", 300.0))
    log_to_dir = opts.get("log_to_dir")
    skip_env_var: str = opts.get("skip_env_var", "SLOT_SKIP_AUTO_INFER")
    exe: str = opts.get("sys_executable") or sys.executable
    rawdata_root = opts.get("rawdata_root")

    # Use caller-supplied env snapshot when available (C4 — worker pool).
    # Otherwise snapshot os.environ at call time (NOT at module import time).
    if opts.get("env") is not None:
        env: dict[str, str] = dict(opts["env"])
    else:
        env = dict(os.environ)

    # Forward rawdata_root into env if explicitly supplied.
    if rawdata_root is not None:
        env["SLOT_RAWDATA_ROOT"] = str(rawdata_root)

    # Capture cwd for diagnostics (C3 requires it in the diagnostic file).
    _cwd = str(opts.get("worker_snapshot", {}).get("cwd") or os.getcwd())

    result = InferenceResult(machine=machine, mode=mode)

    # ------------------------------------------------------------------ #
    # Guard 1: env-var skip (used by tests to avoid real subprocess cost) #
    # ------------------------------------------------------------------ #
    if env.get(skip_env_var) == "1":
        result.skipped = f"env_{skip_env_var}"
        _maybe_write_log(result, log_to_dir)
        return result

    # ------------------------------------------------------------------ #
    # Guard 2: rawdata absence check                                       #
    # Avoids subprocess start cost when there is nothing to scan.         #
    # Safe no-op: the UI shows "not_run" until the next real pass.        #
    # ------------------------------------------------------------------ #
    if rawdata_root is not None:
        per_mode_dir = Path(rawdata_root) / machine / f"mode_{int(mode)}"
        if not per_mode_dir.is_dir():
            result.skipped = "no_rawdata_for_pair"
            _maybe_write_log(result, log_to_dir)
            return result

    # ------------------------------------------------------------------ #
    # Ensure output directories exist.                                     #
    # ------------------------------------------------------------------ #
    if paytables_dir is not None:
        Path(paytables_dir).mkdir(parents=True, exist_ok=True)
    if classify_dir is not None:
        Path(classify_dir).mkdir(parents=True, exist_ok=True)

    paytable_argv: list[str] = ["--machine", machine, "--mode", str(int(mode))]
    if paytables_dir is not None:
        paytable_argv += ["--output-dir", str(paytables_dir)]

    classify_argv: list[str] = ["--machines", machine, "--mode", str(int(mode))]
    if classify_dir is not None:
        classify_argv += ["--output-dir", str(classify_dir)]

    jobs = [
        ("paytable_shape", paytable_script, paytable_argv),
        ("classifier", classify_script, classify_argv),
    ]

    for name, script, argv in jobs:
        if not script.exists():
            sr = ScriptResult(
                name=name,
                ok=False,
                error="script_missing",
                argv=[str(script), *argv],
                cwd=_cwd,
            )
            result.scripts.append(sr)
            result.failed = True
            # C3: log non-silently so operator knows the hook is broken.
            print(
                f"post_inference: script missing for {name!r}: {script}",
                file=sys.stderr,
            )
            _write_failure_diagnostic(summary_dir, sr)
            continue

        full_argv = [exe, str(script), *argv]
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                full_argv,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
                env=env,
            )
            wall = round(time.monotonic() - t0, 3)
            stderr_tail = "\n".join(
                (proc.stderr or "").splitlines()[-50:]
            )
            sr = ScriptResult(
                name=name,
                ok=proc.returncode == 0,
                rc=proc.returncode,
                argv=full_argv,
                cwd=_cwd,
                stderr_tail=stderr_tail,
                wall_time_seconds=wall,
            )
            if proc.returncode != 0:
                result.failed = True
                # C3: log non-silently.
                print(
                    f"post_inference: {name!r} rc={proc.returncode}; "
                    f"stderr tail:\n{stderr_tail}",
                    file=sys.stderr,
                )
                _write_failure_diagnostic(summary_dir, sr)
        except subprocess.TimeoutExpired:
            wall = round(time.monotonic() - t0, 3)
            sr = ScriptResult(
                name=name,
                ok=False,
                error=f"timeout_after_{timeout_sec}s",
                argv=full_argv,
                cwd=_cwd,
                wall_time_seconds=wall,
            )
            result.failed = True
            print(
                f"post_inference: {name!r} timed out after {timeout_sec}s",
                file=sys.stderr,
            )
            _write_failure_diagnostic(summary_dir, sr)
        except Exception as exc:  # noqa: BLE001
            wall = round(time.monotonic() - t0, 3)
            sr = ScriptResult(
                name=name,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                argv=full_argv,
                cwd=_cwd,
                wall_time_seconds=wall,
            )
            result.failed = True
            print(
                f"post_inference: {name!r} launch error: {exc}",
                file=sys.stderr,
            )
            _write_failure_diagnostic(summary_dir, sr)

        result.scripts.append(sr)

    _maybe_write_log(result, log_to_dir)
    return result


# --------------------------------------------------------------------------- #
# Internal helpers                                                              #
# --------------------------------------------------------------------------- #

def _read_summary_meta(summary_path: Path) -> dict[str, Any]:
    """Read machine/mode from summary JSON; returns empty dict on any failure."""
    if not summary_path.exists():
        return {}
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_failure_diagnostic(summary_dir: Path, sr: ScriptResult) -> None:
    """Write / append a failure entry to ``<summary_dir>/_post_inference_failure.json``.

    C3 per ticket §3: persists ``script_name``, ``rc``, ``stderr_tail``
    (last 50 lines already sliced by caller), ``argv``, ``cwd``,
    ``wall_time_seconds``.
    """
    diag_path = summary_dir / "_post_inference_failure.json"
    entry: dict[str, Any] = {
        "script_name": sr.name,
        "rc": sr.rc,
        "stderr_tail": sr.stderr_tail,
        "argv": sr.argv,
        "cwd": sr.cwd,
        "error": sr.error,
        "wall_time_seconds": sr.wall_time_seconds,
    }
    # Accumulate entries (multiple scripts may fail in one pass).
    existing: list[dict[str, Any]] = []
    if diag_path.exists():
        try:
            existing = json.loads(diag_path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = [existing]
        except (OSError, json.JSONDecodeError):
            existing = []
    existing.append(entry)
    try:
        summary_dir.mkdir(parents=True, exist_ok=True)
        diag_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        # Cannot let a log-write failure mask the original script failure.
        print(
            f"post_inference: could not write failure diagnostic "
            f"to {diag_path}: {exc}",
            file=sys.stderr,
        )


def _maybe_write_log(result: InferenceResult, log_to_dir: Any) -> None:
    """Write full result to ``<log_to_dir>/_post_hook.json`` if requested.

    Same contract as the batch-gen worker's ``_post_hook.json`` persistence
    (memory ``feedback_no_silent_swallow.md``): the daemon thread in the
    real-console path drops its return value — this file is the only
    persistence for that path's outcome.
    """
    if log_to_dir is None:
        return
    log_path = Path(log_to_dir) / "_post_hook.json"
    payload: dict[str, Any] = {
        "machine": result.machine,
        "mode": result.mode,
        "skipped": result.skipped,
        "failed": result.failed,
        "scripts": [
            {
                "name": s.name,
                "ok": s.ok,
                "rc": s.rc,
                "argv": s.argv,
                "cwd": s.cwd,
                "stderr_tail": s.stderr_tail,
                "error": s.error,
                "wall_time_seconds": s.wall_time_seconds,
            }
            for s in result.scripts
        ],
    }
    try:
        Path(log_to_dir).mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        # Don't let a log-write failure change the hook's effective outcome,
        # but DO surface it to stderr per memory feedback_no_silent_swallow.md
        # (P1-B5 R1 fix: was silent `pass`, now logs context for ops trace).
        print(
            f"post_inference: could not write hook log to {log_path}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
