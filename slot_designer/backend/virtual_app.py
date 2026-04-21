"""Virtual machine console — reuses `create_app()` with fully isolated paths.

Everything stateful (rawdata / reports / DB / progress / cache / machines
registry / analyzer) lives under ``slot_designer/`` so real-machine console
data is never touched. Same `create_app()` → same UI, same endpoints,
same UX — just a different data universe.

Startup flow:
  1. Regenerate `configs/machines_virtual.json` with fresh MD5s from the
     current spec + engine source. This matches the upstream behavior
     where ``configSummaryMd5`` / ``codeSummaryMd5`` reflects the actual
     config state, so the console's version-tracking (kept vs stale chunks)
     works correctly against my spec/engine edits.
  2. Call `create_app()` with virtual paths injected.
  3. Export `app` for uvicorn.

Run via::

    python -m uvicorn slot_designer.backend.virtual_app:app \\
        --host 127.0.0.1 --port 8878

Or use `scripts/start_virtual_console.ps1` for the production launcher.
"""
from __future__ import annotations

import json
from pathlib import Path

from slot_designer.backend.machine_version import compute_machine_md5
from src.web_console.backend.app import create_app

_SLOT_DESIGNER = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SLOT_DESIGNER.parent

# Virtual-console state / data paths — all under slot_designer/ for
# complete isolation from the real console's rawdata/ / reports/ / state/
VIRTUAL_STATE_DIR = _SLOT_DESIGNER / "state"
VIRTUAL_RAWDATA_ROOT = _SLOT_DESIGNER / "rawdata"
VIRTUAL_REPORTS_ROOT = _SLOT_DESIGNER / "reports"
VIRTUAL_CACHE_ROOT = _SLOT_DESIGNER / "cache_chunks"
VIRTUAL_MACHINES_CONFIG = _SLOT_DESIGNER / "configs" / "machines_virtual.json"
VIRTUAL_CLASSIFY_DIR = _SLOT_DESIGNER / "dev_reports" / "_classify"
VIRTUAL_PAYTABLES_DIR = _SLOT_DESIGNER / "configs" / "paytables_virtual"
VIRTUAL_ANALYZER = _SLOT_DESIGNER / "backend" / "virtual_analyzer.py"


def refresh_machines_virtual(config_path: Path) -> dict:
    """Refresh per-machine MD5s in machines_virtual.json from current
    spec + weights + engine source via the single `compute_machine_md5`
    helper. Registry metadata (_spec_path, _weights_path_template,
    _source_machine, etc.) passes through untouched.

    Called on console boot and at the start of every sampling request
    (so runtime edits to spec/weights take effect immediately for the
    NEXT sampling, not just the next reboot).
    """
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    for entry in raw.get("machines", []):
        if not entry.get("_spec_path"):
            continue
        config_md5, code_md5 = compute_machine_md5(entry)
        entry["configSummaryMd5"] = config_md5
        entry["codeSummaryMd5"] = code_md5
    config_path.write_text(
        json.dumps(raw, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return raw


def build_virtual_app():
    """Construct the virtual-console FastAPI app with isolated paths."""
    for p in (VIRTUAL_STATE_DIR, VIRTUAL_RAWDATA_ROOT, VIRTUAL_REPORTS_ROOT,
              VIRTUAL_CACHE_ROOT, VIRTUAL_CLASSIFY_DIR, VIRTUAL_PAYTABLES_DIR,
              VIRTUAL_MACHINES_CONFIG.parent):
        p.mkdir(parents=True, exist_ok=True)

    if VIRTUAL_MACHINES_CONFIG.exists():
        refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)

    return create_app(
        state_dir=VIRTUAL_STATE_DIR,
        reports_root=VIRTUAL_REPORTS_ROOT,
        cache_root=VIRTUAL_CACHE_ROOT,
        machines_config=VIRTUAL_MACHINES_CONFIG,
        analyzer_path=VIRTUAL_ANALYZER,
        classify_dir=VIRTUAL_CLASSIFY_DIR,
        rawdata_root=VIRTUAL_RAWDATA_ROOT,
        paytables_dir=VIRTUAL_PAYTABLES_DIR,
    )


app = build_virtual_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "slot_designer.backend.virtual_app:app",
        host="127.0.0.1",
        port=8878,
        reload=False,
    )
