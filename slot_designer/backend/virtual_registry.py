"""Virtual-machine registry primitives with **zero app side-effects**.

Extracted from ``virtual_app.py`` on 2026-04-21 because the subprocess
invocation of ``virtual_analyzer.py`` used to import ``virtual_app``
just to get ``refresh_machines_virtual`` — but importing ``virtual_app``
executes its top-level ``app = build_virtual_app()`` statement, which
calls ``create_app`` → ``RunManager.__init__`` → ``_recover_orphan_
running_runs``. That recovery path lists every run in the StateStore
DB with status="running" and terminates their recorded pids. The
just-started batch subprocess had itself written status="running" to
the DB milliseconds earlier, so it terminated **its own** pid and
exited rc=1 with no stdout/stderr output.

The suicide recipe is specific to virtual-mode subprocess flow (real
analyzer never imports the console app, by design). Keeping registry
helpers in this no-side-effect module lets both the app's boot path
AND the analyzer's subprocess path share the same refresh logic
without the subprocess booting up a second console instance.

Modules that need the constants or the refresh helper should import
from HERE, not from ``virtual_app``. ``virtual_app`` still re-exports
them for back-compat with existing callers (tests, tune.py, etc.).
"""
from __future__ import annotations

import json
from pathlib import Path

from slot_designer.backend.machine_version import (
    compute_machine_md5,
    compute_machine_md5_for_mode,
)


_SLOT_DESIGNER = Path(__file__).resolve().parent.parent

# Canonical path for the virtual-machine registry — the same JSON the
# virtual console reads/writes. Exposed as a constant so callers don't
# have to re-derive it.
VIRTUAL_MACHINES_CONFIG = _SLOT_DESIGNER / "configs" / "machines_virtual.json"


def refresh_machines_virtual(config_path: Path) -> dict:
    """Refresh per-machine MD5s in machines_virtual.json from current
    spec + weights + engine source via the single ``compute_machine_md5``
    helper. Registry metadata (``_spec_path``, ``_weights_path_template``,
    ``_source_machine``, etc.) passes through untouched.

    Called on console boot (by ``virtual_app.build_virtual_app``) and
    at the start of every sampling request (by
    ``virtual_analyzer.py``'s main flow), so runtime edits to spec /
    weights take effect immediately for the NEXT sampling.
    """
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    for entry in raw.get("machines", []):
        if not entry.get("_spec_path"):
            continue
        # Machine-level (aggregate) md5 — for "did anything change?" UI
        # indicator at the machine card header.
        config_md5, code_md5 = compute_machine_md5(entry)
        entry["configSummaryMd5"] = config_md5
        entry["codeSummaryMd5"] = code_md5
        # Per-mode md5 map — the source of truth for chunk stamp /
        # classify comparison. Adding a new mode does NOT flip the
        # per-mode md5 of pre-existing modes (2026-04-22 fix; see
        # compute_machine_md5_for_mode docstring).
        modes_md5: dict[str, dict[str, str]] = {}
        for mode in sorted({int(m) for m in entry.get("modes", [])}):
            m_cfg, m_code = compute_machine_md5_for_mode(entry, mode)
            modes_md5[str(mode)] = {
                "configSummaryMd5": m_cfg,
                "codeSummaryMd5": m_code,
            }
        entry["modesMd5"] = modes_md5
    config_path.write_text(
        json.dumps(raw, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return raw
