"""Regression: virtual console's data isolation invariants.

Locks the 2026-04-21 incident (upstream auto-refresh-md5 on page load
pulled 253 real-fleet machines into machines_virtual.json, breaking
virtual/real separation).

Checks:
  1. Default create_app (no override) → real-style upstream fetch path;
     virtual app must NOT accidentally expose it.
  2. create_app with md5_refresh_override → _do_refresh_machines_md5
     delegates to the callable, no upstream bytes fetched.
  3. Virtual app's local refresh preserves registry size (doesn't
     ever grow entries from outside sources).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient

from slot_designer.core.backend.virtual_app import (
    VIRTUAL_MACHINES_CONFIG,
    _local_md5_refresh,
    build_virtual_app,
)


def test_local_md5_refresh_returns_virtual_server_id():
    """The local override must return server_id='virtual' so any log /
    UI surface can distinguish it from real upstream fetches."""
    result = _local_md5_refresh()
    assert result.get("server_id") == "virtual"
    assert result.get("_virtual_refresh") is True, (
        "response must carry _virtual_refresh=True marker so UI + tests "
        "can detect the override path fired (and not the upstream one)"
    )


def test_refresh_preserves_registry_size():
    """The critical invariant: virtual refresh never ADDS new machines.
    Only recomputes md5 on existing ones."""
    before = json.loads(VIRTUAL_MACHINES_CONFIG.read_text(encoding="utf-8"))
    before_names = sorted(m["machine"] for m in before.get("machines", []))
    _local_md5_refresh()
    after = json.loads(VIRTUAL_MACHINES_CONFIG.read_text(encoding="utf-8"))
    after_names = sorted(m["machine"] for m in after.get("machines", []))
    assert before_names == after_names, (
        f"virtual refresh changed machine set!\n"
        f"before: {before_names}\nafter:  {after_names}\n"
        f"(size change probably means isolation broken — upstream fetch "
        f"somehow leaked in)"
    )


def test_refresh_only_contains_virtual_machines():
    """Further invariant: the registry after refresh must not contain
    real-fleet machine names like M1, M14, M272 — those are real console's
    concern. Virtual machines should have a 'sim' suffix (convention) or
    some other marker that they're declared in slot_designer/."""
    after = json.loads(VIRTUAL_MACHINES_CONFIG.read_text(encoding="utf-8"))
    real_fleet_leak = [
        m["machine"] for m in after.get("machines", [])
        if m["machine"] in ("M1", "M14", "M272", "M273", "M247", "M112")
        # These are canonical real-fleet names. If any appear here,
        # isolation definitely broken.
    ]
    assert not real_fleet_leak, (
        f"real-fleet machine names leaked into virtual registry: "
        f"{real_fleet_leak}. This is the 2026-04-21 incident pattern."
    )


def test_api_refresh_md5_goes_through_override():
    """End-to-end: POST /api/machines/refresh-md5 on the virtual app
    returns the override's response shape (server_id='virtual'), NOT
    the upstream handler's shape (server_id='dev' + machines_fetched
    from upstream HTTP)."""
    app = build_virtual_app()
    client = TestClient(app)

    before = json.loads(VIRTUAL_MACHINES_CONFIG.read_text(encoding="utf-8"))
    before_size = len(before.get("machines", []))

    r = client.post("/api/machines/refresh-md5", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("server_id") == "virtual", (
        f"refresh-md5 response not from override path: {body}"
    )
    assert body.get("_virtual_refresh") is True

    after = json.loads(VIRTUAL_MACHINES_CONFIG.read_text(encoding="utf-8"))
    assert len(after.get("machines", [])) == before_size, (
        "refresh-md5 modified registry size — isolation broken"
    )


if __name__ == "__main__":
    import inspect

    mod = sys.modules[__name__]
    tests = [obj for name, obj in inspect.getmembers(mod)
             if name.startswith("test_") and callable(obj)]
    passed, failures = 0, []
    for t in tests:
        try:
            t()
            print(f"ok  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failures.append((t.__name__, e))
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if not failures else 1)
