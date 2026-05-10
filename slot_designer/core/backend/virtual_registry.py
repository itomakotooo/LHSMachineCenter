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

from slot_designer.core.backend.machine_version import (
    compute_machine_md5,
    compute_machine_md5_for_mode,
)


# slot_designer/ root (this file at slot_designer/core/backend/virtual_registry.py)
_SLOT_DESIGNER = Path(__file__).resolve().parent.parent.parent

# Canonical path for the virtual-machine registry — the same JSON the
# virtual console reads/writes. Exposed as a constant so callers don't
# have to re-derive it.
VIRTUAL_MACHINES_CONFIG = _SLOT_DESIGNER / "configs" / "machines_virtual.json"


def _discover_modes_on_disk(entry: dict) -> list[int]:
    """Scan the machine's weights directory for ``mode_<N>/weights.json``
    files and return the sorted list of mode numbers present.

    The machine dir is resolved from ``_weights_path_template`` (which
    looks like ``slot_designer/weights/<MACHINE>/mode_{mode}/weights.json``).
    Returns an empty list if the template is missing, the parent dir
    doesn't exist, or no mode subdirs are found — caller falls back to
    the curated ``modes`` list in that case.
    """
    tpl = entry.get("_weights_path_template")
    if not tpl:
        return []
    repo_root = _SLOT_DESIGNER.parent
    # "slot_designer/machines/M15/weights/mode_{mode}/weights.json" →
    # parent "slot_designer/weights/M15/mode_{mode}" →
    # grandparent "slot_designer/weights/M15"
    try:
        sample = repo_root / tpl.format(mode=1)
    except (KeyError, IndexError):
        return []
    machine_dir = sample.parent.parent
    if not machine_dir.is_dir():
        return []
    modes: list[int] = []
    for sub in sorted(machine_dir.glob("mode_*")):
        if not sub.is_dir():
            continue
        name = sub.name  # e.g. "mode_7"
        if not name.startswith("mode_"):
            continue
        try:
            mode_num = int(name.split("_", 1)[1])
        except (ValueError, IndexError):
            continue
        if (sub / "weights.json").exists():
            modes.append(mode_num)
    return modes


def refresh_machines_virtual(config_path: Path) -> dict:
    """Refresh per-machine MD5s in machines_virtual.json from current
    spec + weights + engine source via the single ``compute_machine_md5``
    helper. Registry metadata (``_spec_path``, ``_weights_path_template``,
    ``_source_machine``, etc.) passes through untouched.

    Called on console boot (by ``virtual_app.build_virtual_app``) and
    at the start of every sampling request (by
    ``virtual_analyzer.py``'s main flow), so runtime edits to spec /
    weights take effect immediately for the NEXT sampling.

    Mode auto-discovery (2026-04-23): for virtual entries with
    ``_weights_path_template`` (the slot_designer layout), this scans
    the machine's weights dir for ``mode_<N>/weights.json`` files and
    unions any newly-dropped modes into the entry's ``modes`` list.
    Without this, adding a new mode dir on disk (e.g. via
    ``derive_m15_mode_7.py`` or a Phase 4 tune) leaves the registry
    claiming ``modes: [1]`` → rwtree + batch-run UI can't see the new
    mode. Hand-maintained registries that predate this script stay
    correct too: discovery is additive (never removes a mode even if
    its weights.json temporarily disappears).
    """
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    for entry in raw.get("machines", []):
        if not entry.get("_spec_path"):
            continue
        # Auto-discover modes from disk BEFORE md5 computation so the
        # machine-level aggregate md5 includes every mode's weights
        # (not just the previously-registered subset). Union, don't
        # replace — operator may have hand-curated the list.
        disk_modes = _discover_modes_on_disk(entry)
        if disk_modes:
            existing_modes = {int(m) for m in entry.get("modes", [])}
            union = sorted(existing_modes | set(disk_modes))
            entry["modes"] = union
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
