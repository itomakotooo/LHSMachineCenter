"""Regression: /api/virtual/paytable/{machine} returns the full
declared pay_id list from the machine's spec file.

2026-04-22 bug report: rwtree's "Pay ID 总览" panel displayed only
the 12 pay_ids that fired in the sample — missing pay_id 4 (the
rtp_excluded grand jackpot at ~1e-6 probability, never observed on
100K-spin samples). User flagged as "解析不完整".

Fix: endpoint returns every pay_id the spec declares (including
rtp_excluded grand jackpots). Frontend merges the list with observed
``payout_ids_top20`` so declared-but-unobserved pays appear as
zero-hit rows (muted styling).

Architectural invariant enforced here: the endpoint is registered
ONLY on the virtual console (via virtual_app._register_virtual_only_
routes). The real console never sees it — real-console tests asserted
separately below.

Tests:
  1. ``/api/virtual/paytable/M1sim`` returns all 13 pay_ids from
     M1.spec.json (including pay_id 4 which is grand_jackpot).
  2. Each declared entry carries ``grand_jackpot`` / ``rtp_excluded``
     booleans so frontend can style them distinctly.
  3. Unknown machine returns 200 with ``source="missing"`` and empty
     pays (frontend falls back to observed-only rendering).
  4. Pay list is sorted by pay_id (deterministic order).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient

from slot_designer.backend.virtual_app import build_virtual_app


def test_virtual_paytable_returns_all_declared_pay_ids():
    """M1.spec.json declares 13 pay_ids (2, 3, 4, 5, 6, 7, 8, 9,
    10, 11, 12, 13, 14). The endpoint must return all 13 — missing
    ANY is the bug that made rwtree show an incomplete list."""
    app = build_virtual_app()
    client = TestClient(app)
    r = client.get("/api/virtual/paytable/M1sim")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["machine"] == "M1sim"
    assert d["source"] == "spec", f"expected source=spec, got {d!r}"

    pay_ids = sorted(p["pay_id"] for p in d["pays"])
    expected = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
    assert pay_ids == expected, (
        f"endpoint must return every declared pay_id in M1.spec.json.\n"
        f"expected: {expected}\n"
        f"got: {pay_ids}\n"
        f"missing: {sorted(set(expected) - set(pay_ids))}\n"
        f"extra: {sorted(set(pay_ids) - set(expected))}"
    )


def test_virtual_paytable_flags_grand_jackpot_and_rtp_excluded():
    """pay_id 4 is M1's grand jackpot (3×Diamond2 = 1000×,
    rtp_excluded=True). Frontend needs both flags to style it
    distinctly (""未命中 · grand jackpot" label)."""
    app = build_virtual_app()
    client = TestClient(app)
    d = client.get("/api/virtual/paytable/M1sim").json()

    pay4 = next(p for p in d["pays"] if p["pay_id"] == 4)
    assert pay4["grand_jackpot"] is True, (
        f"pay_id 4 should carry grand_jackpot=True; got {pay4!r}"
    )
    assert pay4["rtp_excluded"] is True, (
        f"pay_id 4 should carry rtp_excluded=True; got {pay4!r}"
    )
    assert pay4["multiplier"] == 1000

    # Sanity: other pay_ids should NOT be grand_jackpot
    for p in d["pays"]:
        if p["pay_id"] == 4:
            continue
        assert p["grand_jackpot"] is False, (
            f"pay_id {p['pay_id']} should not be grand_jackpot: {p!r}"
        )


def test_virtual_paytable_unknown_machine_returns_empty_gracefully():
    """Frontend falls back to observed-only rendering when the
    endpoint returns empty. Real-console machines (not in
    machines_virtual.json) must NOT break the request — return 200
    with empty pays + source="missing"."""
    app = build_virtual_app()
    client = TestClient(app)
    r = client.get("/api/virtual/paytable/DefinitelyNotAMachine")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["machine"] == "DefinitelyNotAMachine"
    assert d["source"] == "missing"
    assert d["pays"] == []


def test_virtual_paytable_sorted_by_pay_id():
    """Deterministic order so the UI renders rows consistently
    across refreshes and tests assert on index."""
    app = build_virtual_app()
    client = TestClient(app)
    pays = client.get("/api/virtual/paytable/M1sim").json()["pays"]
    pay_ids = [p["pay_id"] for p in pays]
    assert pay_ids == sorted(pay_ids), (
        f"pays must be sorted by pay_id ascending; got {pay_ids}"
    )


def test_real_console_does_not_expose_virtual_endpoint(tmp_path: Path):
    """Architectural contract: the virtual-only endpoint must NOT
    be registered on the real console's app. If a future edit moves
    ``_register_virtual_only_routes`` into ``create_app`` itself,
    this test fails, flagging the main-project pollution before
    shipping.

    Uses a minimal ``create_app()`` (no virtual paths injected) to
    simulate the real-console registration path.
    """
    from src.web_console.backend.app import create_app
    (tmp_path / "state").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "cache").mkdir()
    (tmp_path / "rawdata").mkdir()
    machines_cfg = tmp_path / "machines.json"
    machines_cfg.write_text('{"machines":[]}', encoding="utf-8")
    analyzer = tmp_path / "fake_analyzer.py"
    analyzer.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    app = create_app(
        state_dir=tmp_path / "state",
        reports_root=tmp_path / "reports",
        cache_root=tmp_path / "cache",
        rawdata_root=tmp_path / "rawdata",
        machines_config=machines_cfg,
        analyzer_path=analyzer,
    )
    with TestClient(app) as client:
        r = client.get("/api/virtual/paytable/M1sim")
    assert r.status_code == 404, (
        f"virtual-only endpoint must NOT exist on the real console "
        f"(base create_app without _register_virtual_only_routes). "
        f"Got status {r.status_code}; response: {r.text[:200]!r}"
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
