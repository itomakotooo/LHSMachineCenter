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

    python -m uvicorn slot_designer.core.backend.virtual_app:app \\
        --host 127.0.0.1 --port 8878

Or use `scripts/start_virtual_console.ps1` for the production launcher.
"""
from __future__ import annotations

import json
from pathlib import Path

from slot_designer.core.backend.machine_version import compute_machine_md5
# Registry primitives live in a dedicated module with zero side-effects
# so subprocess callers (virtual_analyzer.py) don't have to import this
# file and trigger build_virtual_app() at import time (2026-04-21
# suicide bug). We re-export ``refresh_machines_virtual`` + ``VIRTUAL_
# MACHINES_CONFIG`` from here for back-compat with existing callers.
from slot_designer.core.backend.virtual_registry import (  # noqa: F401
    VIRTUAL_MACHINES_CONFIG,
    refresh_machines_virtual,
)
from src.web_console.backend.app import create_app

# slot_designer/ root (this file at slot_designer/core/backend/virtual_app.py)
_SLOT_DESIGNER = Path(__file__).resolve().parent.parent.parent
_REPO_ROOT = _SLOT_DESIGNER.parent

# Virtual-console state / data paths — all under slot_designer/ for
# complete isolation from the real console's rawdata/ / reports/ / state/
VIRTUAL_STATE_DIR = _SLOT_DESIGNER / "state"
VIRTUAL_RAWDATA_ROOT = _SLOT_DESIGNER / "rawdata"
VIRTUAL_REPORTS_ROOT = _SLOT_DESIGNER / "reports"
VIRTUAL_CACHE_ROOT = _SLOT_DESIGNER / "cache_chunks"
VIRTUAL_CLASSIFY_DIR = _SLOT_DESIGNER / "dev_reports" / "_classify"
VIRTUAL_PAYTABLES_DIR = _SLOT_DESIGNER / "configs" / "paytables_virtual"
VIRTUAL_ANALYZER = _SLOT_DESIGNER / "backend" / "virtual_analyzer.py"


def _local_md5_refresh(server_id: str = "virtual") -> dict:
    """Override for ``POST /api/machines/refresh-md5`` + the pre-batch
    auto-refresh. Called by the backend when the virtual console fires
    a refresh. Recomputes md5s locally via ``refresh_machines_virtual``
    (spec + weights + engine source) instead of fetching from upstream.

    **Critical isolation barrier** (2026-04-21 incident): without this
    override, the frontend bootstrap's auto-refresh-md5 POST triggers
    the default handler which pulls upstream MachineConfigMd5 and
    merges 253 real-fleet machines into machines_virtual.json —
    breaking data isolation. Virtual machines have no upstream;
    md5 is authoritatively derived from local files.
    """
    before_count = 0
    after_count = 0
    if VIRTUAL_MACHINES_CONFIG.exists():
        before = json.loads(VIRTUAL_MACHINES_CONFIG.read_text(encoding="utf-8"))
        before_map = {
            m["machine"]: (m.get("configSummaryMd5"), m.get("codeSummaryMd5"))
            for m in before.get("machines", [])
        }
        before_count = len(before_map)
        after = refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)
        after_count = len(after.get("machines", []))
        updated = sum(
            1 for m in after.get("machines", [])
            if before_map.get(m["machine"]) != (m.get("configSummaryMd5"),
                                                m.get("codeSummaryMd5"))
        )
    else:
        updated = 0
    return {
        "ok": True,
        "server_id": "virtual",
        "machines_fetched": after_count,
        "machines_updated": updated,
        "skipped_empty_upstream": 0,
        "_virtual_refresh": True,   # telemetry for UI / test diagnostic
    }


def _load_declared_pays_from_spec(machine: str) -> list[dict]:
    """Read the virtual machine's spec file and return the full
    declared ``pays`` list (one entry per pay_id the paytable allows,
    including ``rtp_excluded`` grand jackpots).

    Returns [] on any error (missing registry entry, missing spec
    file, malformed JSON) — callers treat the endpoint as best-effort:
    absence → frontend falls back to observed-only (legacy behavior).
    """
    try:
        reg = json.loads(VIRTUAL_MACHINES_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entry = next(
        (m for m in reg.get("machines", []) if m.get("machine") == machine),
        None,
    )
    if entry is None:
        return []
    rel_spec = entry.get("_spec_path")
    if not rel_spec:
        return []
    spec_path = _REPO_ROOT / rel_spec
    if not spec_path.exists():
        return []
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    pays = spec.get("pays")
    if not isinstance(pays, list):
        return []
    # Project to a lean schema — just the fields the UI needs to render
    # a zero-hit row (pay_id, kind, multiplier, grand_jackpot,
    # rtp_excluded). Full spec fields (multiset / alternatives / group)
    # stay in the spec file; frontend doesn't need them for the
    # completeness-only purpose.
    out: list[dict] = []
    for p in pays:
        if not isinstance(p, dict) or "pay_id" not in p:
            continue
        out.append({
            "pay_id": int(p["pay_id"]),
            "kind": str(p.get("kind", "")),
            "multiplier": p.get("multiplier"),
            "grand_jackpot": bool(p.get("grand_jackpot", False)),
            "rtp_excluded": bool(p.get("rtp_excluded", False)),
        })
    out.sort(key=lambda r: r["pay_id"])
    return out


def _register_virtual_only_routes(app):
    """Register routes that exist ONLY on the virtual console.

    Architectural contract (2026-04-22): keep virtual-specific HTTP
    endpoints OUT of ``src/web_console/backend/app.py`` so the real
    console's surface stays unchanged. Routes added here are visible
    on port 8878 only; real console on 8877 returns 404.

    Frontend probes these endpoints and falls back gracefully when
    they 404 — real-console UI therefore keeps its existing behavior.
    """
    @app.get("/api/virtual/paytable/{machine}")
    def virtual_paytable_declared(machine: str) -> dict:
        """Full declared paytable for a virtual machine, read from
        its spec file. Used by the rwtree's Pay ID 总览 panel to
        render zero-hit rows for pay_ids that didn't fire in the
        sample (e.g. rtp_excluded grand jackpots at ~1e-6 frequency
        on small chunk counts).
        """
        pays = _load_declared_pays_from_spec(machine)
        return {
            "machine": machine,
            "source": "spec" if pays else "missing",
            "pays": pays,
        }


def build_virtual_app():
    """Construct the virtual-console FastAPI app with isolated paths."""
    for p in (VIRTUAL_STATE_DIR, VIRTUAL_RAWDATA_ROOT, VIRTUAL_REPORTS_ROOT,
              VIRTUAL_CACHE_ROOT, VIRTUAL_CLASSIFY_DIR, VIRTUAL_PAYTABLES_DIR,
              VIRTUAL_MACHINES_CONFIG.parent):
        p.mkdir(parents=True, exist_ok=True)

    if VIRTUAL_MACHINES_CONFIG.exists():
        refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)

    app = create_app(
        state_dir=VIRTUAL_STATE_DIR,
        reports_root=VIRTUAL_REPORTS_ROOT,
        cache_root=VIRTUAL_CACHE_ROOT,
        machines_config=VIRTUAL_MACHINES_CONFIG,
        analyzer_path=VIRTUAL_ANALYZER,
        classify_dir=VIRTUAL_CLASSIFY_DIR,
        rawdata_root=VIRTUAL_RAWDATA_ROOT,
        paytables_dir=VIRTUAL_PAYTABLES_DIR,
        md5_refresh_override=_local_md5_refresh,
        # Phase 3 (D12): virtual console doesn't need fleet refresh.
        # Passing False suppresses the FleetRefreshManager daemon thread
        # and the /api/fleet/refresh endpoints.
        fleet_refresh_enabled=False,
    )
    _register_virtual_only_routes(app)
    return app


app = build_virtual_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "slot_designer.core.backend.virtual_app:app",
        host="127.0.0.1",
        port=8878,
        reload=False,
    )
