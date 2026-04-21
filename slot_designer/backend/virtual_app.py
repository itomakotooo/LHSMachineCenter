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

import hashlib
import json
from pathlib import Path

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


def _md5_of_file(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _md5_of_files(paths: list[Path]) -> str:
    h = hashlib.md5()
    for p in sorted(paths):
        h.update(p.read_bytes())
    return h.hexdigest()


def _engine_source_md5() -> str:
    """MD5 of all engine source files. Any change → chunks from old builds
    are flagged stale by the console's classify_chunks.
    """
    engine_dir = _SLOT_DESIGNER / "engine"
    emitter_dir = _SLOT_DESIGNER / "emitter"
    files = sorted(engine_dir.glob("*.py")) + sorted(emitter_dir.glob("*.py"))
    # Exclude __init__.py (empty) to keep the hash stable under minor
    # refactors that don't change actual logic
    files = [f for f in files if f.name != "__init__.py"]
    return _md5_of_files(files)


def refresh_machines_virtual(config_path: Path) -> dict:
    """Read the tracked machines_virtual.json, refresh per-machine MD5s
    from current spec + engine source, write back, return the dict.

    Machines are listed by the curator; this function only refreshes the
    derived MD5 fields. Custom fields (spec_path, weights_path_template,
    source_machine) pass through untouched.
    """
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    engine_md5 = _engine_source_md5()

    for entry in raw.get("machines", []):
        spec_path_rel = entry.get("_spec_path")
        if not spec_path_rel:
            continue
        spec_path = _REPO_ROOT / spec_path_rel
        if not spec_path.exists():
            # Leave existing md5s alone if file missing — avoid silent
            # corruption; analyzer will fail visibly with useful error
            continue
        entry["configSummaryMd5"] = _md5_of_file(spec_path)
        entry["codeSummaryMd5"] = engine_md5

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
