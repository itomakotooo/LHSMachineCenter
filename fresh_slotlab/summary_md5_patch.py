"""Shared helper for patching empty md5 fields in a written summary (Ticket P1-B2).

Two callsites in the codebase perform the same operation — "fill
``config_md5`` / ``code_md5`` in ``player_impact_summary.json`` when the
real analyzer left them blank" — with cross-referencing comments but
no shared code:

  α) ``src/web_console/backend/app.py:_run_generate_report`` (post-``pia.main()``)
  β) ``slot_designer/core/backend/virtual_analyzer.py:_patch_summary_md5_tags``
     (post-delegate subprocess)

This module provides ``patch_summary_md5`` as the single implementation.
Both callsites are thin wrappers that inject the appropriate
``md5_lookup_fn`` for their context:

  α injects: lambda wrapping ``_get_machine_md5(machine, mc, mode=mode)``
  β injects: lambda wrapping ``_compute_md5s(entry, mode=args.rtp_mode)``

Contract
--------
C1 — Injectable lookup:
    ``md5_lookup_fn()`` takes no arguments (caller binds machine/mode in
    the lambda) and returns ``(config_md5: str, code_md5: str)``.

C3 — Per-mode granularity:
    The helper does NOT compute md5s itself — it delegates entirely to the
    caller-supplied ``md5_lookup_fn``. Per-mode correctness is the
    caller's responsibility.

C4 — Empty-md5 detection:
    Only fills fields that are falsy (empty string, ``None``, or missing key).
    Non-empty values are NOT overwritten — the patcher is a harmless no-op
    if the real analyzer ever learns about the registry.

C5 — Failure logging (per memory ``feedback_no_silent_swallow.md``):
    If ``md5_lookup_fn()`` raises, or writing the patched JSON fails, the
    failure is logged to stderr with machine/mode/error context. The caller's
    primary artefacts (report + stats) remain valid — this is best-effort
    metadata tagging.

No side effects on import
-------------------------
Per memory ``feedback_subprocess_import_suicide_and_module_globals.md``:
this module has NO import-time side effects. No app construction, no
subprocess spawn, no global-state mutation.

Citing ``session_artifacts/_arch/01_pipeline_map.md §4`` row "md5 patch into
summary", ``session_artifacts/_arch/03_coupling_audit.md §4.5`` (duplicate
primitives), and ``session_artifacts/_arch/08_handoff.md §4 Phase 1``
(summary patcher × 2).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, Tuple


def patch_summary_md5(
    summary_path: Path,
    md5_lookup_fn: Callable[[], Tuple[str, str]],
    *,
    machine: str = "<unknown>",
    mode: object = "<unknown>",
) -> None:
    """Patch empty ``config_md5`` / ``code_md5`` in *summary_path*.

    Parameters
    ----------
    summary_path:
        Absolute path to ``player_impact_summary.json``.
    md5_lookup_fn:
        Zero-argument callable returning ``(config_md5, code_md5)`` for
        the machine + mode in question.  The caller binds machine/mode
        in a lambda; this helper does not assume a registry schema.
    machine:
        Machine identifier — used ONLY in error log messages (C5).
    mode:
        Mode identifier — used ONLY in error log messages (C5).

    Returns
    -------
    None
        Best-effort.  Primary report artefacts are never at risk.

    Side effects
    ------------
    Writes the patched JSON back to *summary_path* when any field was
    updated.  Logs failures to ``sys.stderr`` with machine/mode context.
    """
    if not summary_path.exists():
        return

    # --- Step 1: resolve md5 values from the injected lookup function ---
    try:
        config_md5, code_md5 = md5_lookup_fn()
    except Exception as exc:  # noqa: BLE001
        # C5: log failure with full context — do NOT silently swallow.
        print(
            f"patch_summary_md5: md5 lookup failed for machine={machine!r} "
            f"mode={mode!r}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return

    if not (config_md5 or code_md5):
        # Nothing to patch — both lookup results are falsy.
        return

    # --- Step 2: read existing summary ---
    try:
        payload: dict = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # C5: log read failure.
        print(
            f"patch_summary_md5: could not read summary for machine={machine!r} "
            f"mode={mode!r}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return

    # --- Step 3: apply only the empty fields (C4 — never overwrite) ---
    # Design choice (P1-B2 R2): "fill if empty, never re-stamp stale".
    # Skip non-empty existing values even if they could be from a different
    # cache version. Safe today because the real analyzer always emits ""
    # for virtual machines (the only callers that need patching post-hoc);
    # if a future caller writes a non-empty-but-stale md5 deliberately,
    # this helper will NOT correct it. Re-stamping logic belongs in a
    # separate explicit re-stamp helper, not the post-hoc filler.
    dirty = False
    if config_md5 and not payload.get("config_md5"):
        payload["config_md5"] = config_md5
        dirty = True
    if code_md5 and not payload.get("code_md5"):
        payload["code_md5"] = code_md5
        dirty = True

    if not dirty:
        return

    # --- Step 4: write back ---
    try:
        summary_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        # C5: log write failure.  Report is still valid without this tag.
        print(
            f"patch_summary_md5: could not write patched summary for "
            f"machine={machine!r} mode={mode!r}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
