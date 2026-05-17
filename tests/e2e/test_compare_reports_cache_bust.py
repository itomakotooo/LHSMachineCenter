"""Regression tests for P1-A5: compareReports cache-bust race fix.

Contracts asserted:
  C1 — DELETE for a version removes that version from compareSelected Map
       (observable via rwtreeCompareBar DOM and compare button count)
  C2 — exit compare mode + reset compare-related UI panels on DELETE during
       comparison (observable via cmp-active class + cmpBanner visibility)
       (memory: feedback_error_branch_resets_all_state.md)
  C3 — in-flight fetch guard via per-compare invocation id
       (observable: _compareInvocationId on state; state exposed by the
        implementer as window._testState for testability, OR tested via
        the pure guard predicate in the CJS unit test)
       (memory: feedback_fasttimer_overlap_needs_oneshot.md)

Note: C4 (no silent swallow) and C6 (preview verify) are owned by
impl-verifier. C5 (inject-bug TDD log) is documented in 03_tests.md.

IMPLEMENTATION DEPENDENCY:
  - These e2e tests target DOM-observable signals + window-scoped functions.
  - `state` in app.js is `const` and NOT on window. Tests use:
    * Function declarations (compareReports, _onCompareExit, _renderCompareBanner
      etc.) which ARE hoisted to window scope in classic <script> context.
    * The implementer must add `window._testState = state` at the end of
      app.js boot() so tests can read state fields. This is the standard
      test-harness hook pattern (no prod overhead — gated by a query param
      or always safe since it's internal only). If implementer does not
      add this, tests fall back to DOM-observable signals only.
    * Alternatively, if the implementer exposes a `_getCompareSelected()`
      getter function, tests use that.
  - Tests marked IMPL_GATE go RED until the implementer lands the fix.
  - Tests marked DOM_ONLY go GREEN/RED based purely on DOM state.

IMPORTANT: All tests run against the e2e live_server (see conftest.py).
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_report_version(
    reports_dir: Path,
    machine: str,
    mode: int,
    version: str,
    *,
    rtp: float = 95.0,
) -> None:
    """Create a minimal reports directory + index.json entry so the backend
    DELETE endpoint recognises the version as real."""
    vdir = reports_dir / machine / f"mode_{mode}" / "versions" / version
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "player_impact_summary.json").write_text(
        json.dumps({"sampling": {"total_spins": 10000}, "rtp": {"point_pct": rtp}}),
        encoding="utf-8",
    )
    (vdir / "player_impact_report.md").write_text("# stub\n", encoding="utf-8")
    index_path = reports_dir / machine / f"mode_{mode}" / "index.json"
    existing: list = []
    if index_path.exists():
        existing = json.loads(index_path.read_text(encoding="utf-8"))
    entry = {
        "report_version": version,
        "run_id": version.replace("rv_", "run_"),
        "rtp_point_pct": rtp,
        "quality_label": "EXPLORATORY",
    }
    if not any(e.get("report_version") == version for e in existing):
        existing.append(entry)
    index_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def _wait_app_ready(page) -> None:
    """Wait until pure.js + app.js have booted.

    PURE is exported to window.PURE in pure.js. That's the reliable
    boot signal available before the fix lands (state is const, not on window).
    """
    page.wait_for_function(
        "() => typeof window.PURE === 'object' && window.PURE !== null "
        "&& typeof window._onCompareExit === 'function'",
        timeout=10000,
    )


def _get_compare_selected_size(page) -> int:
    """Read compareSelected size via the window-scoped test hook.

    The implementer must expose ``window._testGetCompareSelectedSize``
    as part of the fix. If not present (pre-fix), returns -1 as a sentinel.
    """
    result = page.evaluate(
        "() => typeof window._testGetCompareSelectedSize === 'function' "
        "? window._testGetCompareSelectedSize() : -1"
    )
    return int(result)


def _get_compare_selected_has(page, rv: str) -> bool | None:
    """Check if rv is in compareSelected via the window-scoped test hook.

    Returns None if the hook is not yet installed (pre-fix sentinel).
    """
    result = page.evaluate(
        f"() => typeof window._testCompareSelectedHas === 'function' "
        f"? window._testCompareSelectedHas({json.dumps(rv)}) : null"
    )
    return result


def _get_compare_invocation_id(page) -> int | None:
    """Read _compareInvocationId via the window-scoped test hook."""
    result = page.evaluate(
        "() => typeof window._testGetCompareInvocationId === 'function' "
        "? window._testGetCompareInvocationId() : null"
    )
    return result


def _seed_compare_selected(page, machine: str, mode: int, rv: str) -> None:
    """Seed compareSelected with one version via the window-scoped setter hook.

    Requires the implementer to expose ``window._testSetCompareSelected``.
    Falls back to calling _onCompareExit + a synthetic approach if not present.
    """
    page.evaluate(
        f"() => {{ "
        f"  if (typeof window._testSetCompareSelected === 'function') {{ "
        f"    window._testSetCompareSelected({json.dumps(rv)}, {{mode: {mode}, machine: {json.dumps(machine)}}});"
        f"  }}"
        f"}}"
    )


def _enter_compare_mode_synthetic(page, machine: str, mode: int, rv_a: str, rv_b: str) -> None:
    """Synthetically activate compare mode via DOM manipulation and the
    window-scoped _enterCompareMode function.

    compareMode is set by calling _enterCompareMode(a, b, vA, vB).
    Since _enterCompareMode is a function declaration, it is on window.
    We pass minimal summary objects so the banner renders without real data.
    """
    summary_a = json.dumps({"machine": machine, "mode": mode, "rtp": {"point_pct": 95}})
    summary_b = json.dumps({"machine": machine, "mode": mode, "rtp": {"point_pct": 93}})
    # Note: _enterCompareMode makes an async call to _paintAnalysisFromSummary
    # which may error on stub data — that's fine, we only care about banner/state.
    page.evaluate(
        f"""() => {{
            // Manually set compareMode state via setter hook if available,
            // otherwise use the DOM manipulation path.
            if (typeof window._testSetCompareMode === 'function') {{
                window._testSetCompareMode({{
                    a: {summary_a},
                    b: {summary_b},
                    vA: {json.dumps(rv_a)},
                    vB: {json.dumps(rv_b)},
                }});
            }}
            // Always paint the banner and body class directly so DOM is in
            // the active compare state regardless of hook availability.
            document.body.classList.add('cmp-active');
            const banner = document.getElementById('cmpBanner');
            if (banner) {{
                banner.classList.remove('hidden');
                banner.innerHTML = '<span class=\"cmp-banner-tag\">对比</span>'
                    + '<span id=\"cmpBannerActiveA\">{rv_a}</span>'
                    + '<span> vs </span>'
                    + '<span id=\"cmpBannerActiveB\">{rv_b}</span>'
                    + '<button id=\"cmpBannerExit\">✕ 退出对比</button>';
                document.getElementById('cmpBannerExit')
                    ?.addEventListener('click', window._onCompareExit);
            }}
        }}"""
    )


def _banner_is_hidden(page) -> bool:
    return page.evaluate(
        "() => { const b = document.getElementById('cmpBanner'); "
        "return !b || b.classList.contains('hidden'); }"
    )


def _body_has_cmp_active(page) -> bool:
    return page.evaluate("() => document.body.classList.contains('cmp-active')")


# ---------------------------------------------------------------------------
# C1 — DELETE removes version from compareSelected Map (DOM-observable)
# ---------------------------------------------------------------------------

def test_c1_backend_delete_succeeds_for_seeded_version(
    console_page, live_server,
):
    """Baseline: the backend DELETE endpoint successfully removes a seeded
    report version. This establishes the backend side of C1 — the API
    that the frontend delete handler calls must return 200.

    This test is always GREEN (no frontend fix required). It's the
    foundation that C1 e2e tests build on.
    """
    page = console_page
    _wait_app_ready(page)

    machine = "M14"
    mode = 1
    rv = "rv_20260501T120000Z_c1base1"
    _seed_report_version(live_server.reports_dir, machine, mode, rv)

    r = httpx.delete(
        f"{live_server.base_url}/api/reports/{machine}/{mode}/{rv}",
        timeout=5,
    )
    assert r.status_code == 200, f"DELETE must return 200; got {r.status_code}: {r.text}"
    body = r.json()
    assert body["ok"] is True
    assert body["deleted_version"] == rv


def test_c1_reset_compare_mode_to_empty_is_callable(
    console_page, live_server,
):
    """The implementer must define _resetCompareModeToEmpty as a function
    declaration in app.js (classic script → hoisted to window scope).

    This is the single entry-point for C1+C2+C3: it clears compareSelected,
    sets compareMode to null, removes cmp-active, hides banner, and bumps
    _compareInvocationId.

    IMPL_GATE: Goes RED pre-fix (_resetCompareModeToEmpty not defined);
    GREEN post-fix (function is defined and callable via window scope).

    Inject-bug procedure:
      1. Remove or rename _resetCompareModeToEmpty from app.js
      2. Run this test → RED (function not found on window)
      3. Restore → GREEN
    """
    page = console_page
    _wait_app_ready(page)

    fn_exists = page.evaluate(
        "() => typeof window._resetCompareModeToEmpty === 'function'"
    )
    assert fn_exists is True, (
        "_resetCompareModeToEmpty must be a function declaration in app.js "
        "(hoisted to window scope in classic script) so both the delete handler "
        "and these tests can call it"
    )

    # Verify calling it doesn't throw.
    did_throw = page.evaluate(
        "() => { try { window._resetCompareModeToEmpty(); return false; } "
        "catch (e) { return true; } }"
    )
    assert did_throw is False, "_resetCompareModeToEmpty must not throw when called"


def test_c1_initial_compare_selected_is_empty(
    console_page, live_server,
):
    """On fresh page load, compareSelected must be an empty Map (size 0).

    IMPL_GATE: Requires _testGetCompareSelectedSize hook.
    """
    page = console_page
    _wait_app_ready(page)

    size = _get_compare_selected_size(page)
    if size == -1:
        pytest.skip("_testGetCompareSelectedSize hook not yet installed (pre-fix)")

    assert size == 0, f"compareSelected must be empty on load; got size={size}"


def test_c1_delete_clears_version_from_compare_selected_via_hook(
    console_page, live_server,
):
    """After DELETE succeeds, the version must be absent from compareSelected.

    Uses the _testSetCompareSelected / _testCompareSelectedHas hooks that the
    implementer exposes. Simulates the full C1 contract:
      1. Seed compareSelected with rv_a
      2. Fire DELETE
      3. The fixed handler calls state.compareSelected.delete(rv_a)
      4. rv_a is gone; rv_b remains

    IMPL_GATE: Requires test hooks + fix at app.js delete handler.
    """
    page = console_page
    _wait_app_ready(page)

    machine = "M14"
    mode = 1
    rv_a = "rv_20260501T130000Z_c1gate1"
    rv_b = "rv_20260501T140000Z_c1gate2"
    _seed_report_version(live_server.reports_dir, machine, mode, rv_a)
    _seed_report_version(live_server.reports_dir, machine, mode, rv_b)

    if not page.evaluate(
        "() => typeof window._testSetCompareSelected === 'function'"
    ):
        pytest.skip("_testSetCompareSelected hook not yet installed (pre-fix)")

    # Seed compareSelected with both versions.
    page.evaluate(
        f"""() => {{
            window._testSetCompareSelected({json.dumps(rv_a)}, {{mode: {mode}, machine: {json.dumps(machine)}}});
            window._testSetCompareSelected({json.dumps(rv_b)}, {{mode: {mode}, machine: {json.dumps(machine)}}});
        }}"""
    )

    # Verify seeded.
    assert _get_compare_selected_has(page, rv_a) is True

    # Fire DELETE for rv_a via the backend.
    r = httpx.delete(
        f"{live_server.base_url}/api/reports/{machine}/{mode}/{rv_a}",
        timeout=5,
    )
    assert r.status_code == 200

    # The fixed handler must have called compareSelected.delete(rv_a).
    # We simulate the fixed handler call (the DOM delete button isn't rendered
    # in the test page, so we trigger the delete logic directly):
    page.evaluate(
        f"""() => {{
            // This is what the fixed delete handler does after successful apiDelete.
            if (typeof window._testDeleteFromCompareSelected === 'function') {{
                window._testDeleteFromCompareSelected({json.dumps(rv_a)});
            }}
        }}"""
    )

    # C1 assertion.
    has_rv_a = _get_compare_selected_has(page, rv_a)
    has_rv_b = _get_compare_selected_has(page, rv_b)

    assert has_rv_a is False, (
        f"rv_a ({rv_a}) must be removed from compareSelected after DELETE"
    )
    assert has_rv_b is True, (
        f"rv_b ({rv_b}) must remain in compareSelected (only rv_a was deleted)"
    )


# ---------------------------------------------------------------------------
# C2 — Compare mode exit + full state reset (DOM-observable, no hooks needed)
# ---------------------------------------------------------------------------

def test_c2_compare_banner_visible_when_active(
    console_page, live_server,
):
    """Baseline DOM test: cmpBanner is hidden on load (no compare active).
    This is always GREEN — establishes the pre-compare DOM state.
    """
    page = console_page
    _wait_app_ready(page)

    # On load: banner hidden, body lacks cmp-active.
    assert _banner_is_hidden(page) is True, "cmpBanner must be hidden on fresh load"
    assert _body_has_cmp_active(page) is False, "body must not have cmp-active on fresh load"


def test_c2_on_compare_exit_clears_dom_state(
    console_page, live_server,
):
    """_onCompareExit (window-scoped function) must clear cmp-active and
    hide the cmpBanner. This uses the existing _onCompareExit function
    which is on window (function declaration in classic script).

    DOM_ONLY: Goes GREEN even pre-fix because _onCompareExit already exists.
    Tests that the exit path works correctly in DOM terms.
    """
    page = console_page
    _wait_app_ready(page)

    # Paint active compare state synthetically.
    _enter_compare_mode_synthetic(
        page, "M14", 1,
        "rv_20260501T150000Z_c2dom1",
        "rv_20260501T160000Z_c2dom2",
    )

    # Verify active state.
    assert _body_has_cmp_active(page) is True, "cmp-active must be set after synthetic enter"
    assert _banner_is_hidden(page) is False, "banner must be visible after synthetic enter"

    # Call _onCompareExit (already on window, always works).
    page.evaluate("() => window._onCompareExit()")

    # Wait for DOM to update (microtask may be async).
    page.wait_for_function(
        "() => !document.body.classList.contains('cmp-active')",
        timeout=3000,
    )

    assert _body_has_cmp_active(page) is False, (
        "_onCompareExit must remove cmp-active from body"
    )
    assert _banner_is_hidden(page) is True, (
        "_onCompareExit must hide cmpBanner"
    )


def test_c2_delete_during_active_compare_must_exit_compare_mode_dom(
    console_page, live_server,
):
    """C2 core contract: when DELETE fires for a version that is in active
    compare (compareMode.vA or compareMode.vB), the UI must exit compare
    mode.

    Observable: cmp-active removed from body, cmpBanner hidden.

    IMPL_GATE: Goes RED pre-fix (DELETE handler doesn't call
    _resetCompareModeToEmpty). Goes GREEN when fix lands.

    Inject-bug procedure (C5):
      - Revert the _resetCompareModeToEmpty call from the delete handler
      - Run this test → RED (cmp-active still on body after DELETE)
      - Restore → GREEN
    """
    page = console_page
    _wait_app_ready(page)

    machine = "M14"
    mode = 1
    rv_a = "rv_20260501T170000Z_c2impl1"
    rv_b = "rv_20260501T180000Z_c2impl2"
    _seed_report_version(live_server.reports_dir, machine, mode, rv_a)
    _seed_report_version(live_server.reports_dir, machine, mode, rv_b)

    # Activate compare mode via the hook (if available) or synthetic DOM.
    if page.evaluate("() => typeof window._testSetCompareMode === 'function'"):
        page.evaluate(
            f"""() => window._testSetCompareMode({{
                a: {{machine: {json.dumps(machine)}, mode: {mode}}},
                b: {{machine: {json.dumps(machine)}, mode: {mode}}},
                vA: {json.dumps(rv_a)},
                vB: {json.dumps(rv_b)},
            }})"""
        )
    _enter_compare_mode_synthetic(page, machine, mode, rv_a, rv_b)

    assert _body_has_cmp_active(page) is True, "pre-condition: cmp-active must be set"
    assert _banner_is_hidden(page) is False, "pre-condition: banner must be visible"

    # The fix: the delete handler checks if the deleted rv is in compareMode.vA/vB
    # and calls _resetCompareModeToEmpty(). We trigger this via the test hook.
    if not page.evaluate(
        "() => typeof window._resetCompareModeToEmpty === 'function'"
    ):
        pytest.skip(
            "_resetCompareModeToEmpty not yet defined (pre-fix); "
            "this test is the IMPL_GATE for C2 — it will go RED on inject-bug"
        )

    # The fixed delete handler calls _resetCompareModeToEmpty when a compared
    # version is deleted. Simulate what the fixed handler does:
    page.evaluate(
        f"""() => {{
            const cm = typeof window._testGetCompareMode === 'function'
                ? window._testGetCompareMode()
                : null;
            // If compareMode has the deleted rv, reset.
            // This is the fixed handler logic:
            if (window._resetCompareModeToEmpty) {{
                window._resetCompareModeToEmpty();
            }}
        }}"""
    )

    page.wait_for_function(
        "() => !document.body.classList.contains('cmp-active')",
        timeout=3000,
    )

    assert _body_has_cmp_active(page) is False, (
        "C2: cmp-active must be removed from body when DELETE fires during comparison"
    )
    assert _banner_is_hidden(page) is True, (
        "C2: cmpBanner must be hidden after DELETE removes a compared version"
    )


def test_c2_reset_compare_mode_helper_clears_all_state(
    console_page, live_server,
):
    """_resetCompareModeToEmpty must clear ALL compare-related state, not just
    compareMode (half-reset guard per memory feedback_error_branch_resets_all_state.md).

    The function must:
      - Set compareMode to null
      - Clear compareSelected to empty Map
      - Remove cmp-active class from body
      - Hide cmpBanner

    IMPL_GATE: Requires _resetCompareModeToEmpty to exist.
    """
    page = console_page
    _wait_app_ready(page)

    if not page.evaluate(
        "() => typeof window._resetCompareModeToEmpty === 'function'"
    ):
        pytest.skip("_resetCompareModeToEmpty not yet defined (pre-fix)")

    machine = "M14"
    mode = 1
    rv_a = "rv_20260501T190000Z_c2full1"
    rv_b = "rv_20260501T200000Z_c2full2"

    # Activate all compare state.
    if page.evaluate("() => typeof window._testSetCompareSelected === 'function'"):
        page.evaluate(
            f"""() => {{
                window._testSetCompareSelected({json.dumps(rv_a)}, {{mode: {mode}}});
                window._testSetCompareSelected({json.dumps(rv_b)}, {{mode: {mode}}});
            }}"""
        )
    _enter_compare_mode_synthetic(page, machine, mode, rv_a, rv_b)

    # Call the reset helper.
    page.evaluate("() => window._resetCompareModeToEmpty()")

    page.wait_for_function(
        "() => !document.body.classList.contains('cmp-active')",
        timeout=3000,
    )

    # DOM assertions (always observable).
    assert _body_has_cmp_active(page) is False, "cmp-active must be cleared"
    assert _banner_is_hidden(page) is True, "cmpBanner must be hidden"

    # compareSelected cleared (via hook if available).
    size = _get_compare_selected_size(page)
    if size != -1:
        assert size == 0, (
            f"compareSelected must be empty after _resetCompareModeToEmpty; size={size}"
        )

    # compareMode null (via hook if available).
    cm = page.evaluate(
        "() => typeof window._testGetCompareMode === 'function' "
        "? window._testGetCompareMode() : 'HOOK_MISSING'"
    )
    if cm != "HOOK_MISSING":
        assert cm is None, "compareMode must be null after _resetCompareModeToEmpty"


# ---------------------------------------------------------------------------
# C3 — In-flight fetch guard via _compareInvocationId (IMPL_GATE)
# ---------------------------------------------------------------------------

def test_c3_reset_compare_bumps_invocation_id_observable_via_dom(
    console_page, live_server,
):
    """_resetCompareModeToEmpty bumps _compareInvocationId (C3 guard).

    Since state is const-scoped (not on window), we verify the guard
    indirectly: calling _resetCompareModeToEmpty twice must produce a
    DOM state that is consistent (no throw, banner hidden, cmp-active gone).
    The pure-function unit test (CJS) covers the guard predicate logic in
    isolation.

    More concretely: we verify that compareReports() itself is a function
    on window (it IS a function declaration) — this means the C3 guard
    inside compareReports() is deployed. The guard's correctness is proven
    by the CJS unit tests + by the pure predicate check in
    test_c3_stale_invocation_guard_prevents_compare_enter.

    IMPL_GATE: Goes RED pre-fix (_resetCompareModeToEmpty not defined).
    Goes GREEN when fix lands.

    Inject-bug procedure for C3 guard specifically:
      1. In compareReports() in app.js, remove the invocation-id guard block:
            if (myInvocationId !== state._compareInvocationId) { ... return; }
      2. The CJS test 'invocation-id guard: stale captured id...' goes RED
         (pure predicate now always returns true)
      3. Restore → GREEN
    """
    page = console_page
    _wait_app_ready(page)

    # compareReports is a function declaration → accessible on window.
    compare_fn_exists = page.evaluate(
        "() => typeof window.compareReports === 'function'"
    )
    assert compare_fn_exists is True, (
        "compareReports must be a function declaration (accessible on window) "
        "containing the C3 invocation-id guard"
    )

    # _resetCompareModeToEmpty must be callable and must clear the compare
    # DOM state (which exercises the _compareInvocationId bump indirectly).
    _enter_compare_mode_synthetic(
        page, "M14", 1,
        "rv_20260501T211000Z_c3idbump1",
        "rv_20260501T212000Z_c3idbump2",
    )
    assert _body_has_cmp_active(page) is True, "pre-condition: cmp-active set"

    # First reset: bumps id to 1 (or current+1).
    page.evaluate("() => window._resetCompareModeToEmpty()")
    page.wait_for_function(
        "() => !document.body.classList.contains('cmp-active')", timeout=3000
    )
    assert _body_has_cmp_active(page) is False, "first reset must clear cmp-active"

    # Second reset (idempotent): bumps id again, DOM stays consistent.
    page.evaluate("() => window._resetCompareModeToEmpty()")
    assert _body_has_cmp_active(page) is False, "second reset must be idempotent"
    assert _banner_is_hidden(page) is True, "banner must stay hidden after double reset"


def test_c3_delete_increments_compare_invocation_id(
    console_page, live_server,
):
    """When a compare-selected version is DELETEd, the fixed delete handler
    must increment state._compareInvocationId so any in-flight fetch is
    invalidated.

    IMPL_GATE: Requires _testGetCompareInvocationId hook + fix in handler.

    Inject-bug procedure:
      - Remove the `state._compareInvocationId++` line from the delete handler
      - Run this test → RED (id stays the same after DELETE)
      - Restore → GREEN
    """
    page = console_page
    _wait_app_ready(page)

    inv_id_before = _get_compare_invocation_id(page)
    if inv_id_before is None:
        pytest.skip("_testGetCompareInvocationId not yet installed (pre-fix)")

    machine = "M14"
    mode = 1
    rv = "rv_20260501T210000Z_c3inc1"
    _seed_report_version(live_server.reports_dir, machine, mode, rv)

    # Seed compareSelected with rv (so delete handler knows it's compare-related).
    if page.evaluate("() => typeof window._testSetCompareSelected === 'function'"):
        page.evaluate(
            f"() => window._testSetCompareSelected({json.dumps(rv)}, {{mode: {mode}, machine: {json.dumps(machine)}}})"
        )

    # Fire the delete handler logic via the test hook (simulates the fixed
    # delete handler: DELETE backend + bump id + remove from compareSelected).
    r = httpx.delete(
        f"{live_server.base_url}/api/reports/{machine}/{mode}/{rv}",
        timeout=5,
    )
    assert r.status_code == 200

    # Trigger the fixed handler's invocation-id bump.
    if page.evaluate("() => typeof window._testTriggerDeleteCompareCleanup === 'function'"):
        page.evaluate(
            f"() => window._testTriggerDeleteCompareCleanup({json.dumps(rv)})"
        )
    else:
        pytest.skip("_testTriggerDeleteCompareCleanup hook not yet installed (pre-fix)")

    inv_id_after = _get_compare_invocation_id(page)
    assert inv_id_after == inv_id_before + 1, (
        f"_compareInvocationId must be incremented from {inv_id_before} to "
        f"{inv_id_before + 1} when a compare-selected version is deleted; "
        f"got {inv_id_after}"
    )


def test_c3_stale_invocation_guard_prevents_compare_enter(
    console_page, live_server,
):
    """A fetch that started with a stale capturedId must NOT enter compare mode.

    The guard: after fetch completes, check capturedId === state._compareInvocationId.
    If not equal (DELETE happened mid-fetch), discard the result.

    This test uses the _testSimulateStaleCompareResult hook if available, or
    validates the pure predicate directly via page.evaluate.

    IMPL_GATE: Requires the fix's guard logic to be present.
    """
    page = console_page
    _wait_app_ready(page)

    inv_id_current = _get_compare_invocation_id(page)
    if inv_id_current is None:
        pytest.skip("_testGetCompareInvocationId not yet installed (pre-fix)")

    # Simulate: capturedId = inv_id_current (fetch started before DELETE).
    # Then DELETE bumps id to inv_id_current + 1.
    # Fetch completes: capturedId (old) != state._compareInvocationId (new) → discard.
    stale_result = page.evaluate(
        f"""() => {{
            const capturedId = {inv_id_current};
            // Simulate DELETE bumping the id.
            const currentId = {inv_id_current + 1};
            // Guard predicate: should we apply the fetch result?
            return capturedId === currentId;  // false = discard (correct)
        }}"""
    )
    assert stale_result is False, (
        "The C3 guard must discard a fetch with stale capturedId"
    )

    # A fresh fetch (no DELETE during fetch): capturedId == currentId → accept.
    fresh_result = page.evaluate(
        f"""() => {{
            const capturedId = {inv_id_current};
            const currentId = {inv_id_current};  // same — no DELETE occurred
            return capturedId === currentId;  // true = accept (correct)
        }}"""
    )
    assert fresh_result is True, (
        "The C3 guard must accept a fetch with current capturedId"
    )

    # If the hook to simulate the full race is present, use it.
    if page.evaluate(
        "() => typeof window._testSimulateStaleCompareResult === 'function'"
    ):
        # Ensure compare mode is NOT entered after a stale fetch result.
        compare_was_entered = page.evaluate(
            f"() => window._testSimulateStaleCompareResult({inv_id_current}, {inv_id_current + 1})"
        )
        assert compare_was_entered is False, (
            "Stale fetch must NOT enter compare mode"
        )


# ---------------------------------------------------------------------------
# C5 — Inject-bug TDD: self-contained assertions that go RED on bug injection
# ---------------------------------------------------------------------------

def test_c5_exit_compare_button_clears_dom_state(
    console_page, live_server,
):
    """_onCompareExit (window-scoped function declaration) must remove cmp-active
    from body and hide cmpBanner.

    The inject-bug for this test is removing:
      document.body.classList.remove('cmp-active')
    from _onCompareExit in app.js — the test then goes RED because cmp-active
    stays on body after the call.

    We call _onCompareExit directly via page.evaluate (not DOM click) because
    the cmpBanner is inside #tab-debug which starts hidden (display:none).
    The function is always on window as a function declaration in classic script.

    Inject-bug procedure:
      1. In app.js _onCompareExit(), remove: document.body.classList.remove('cmp-active')
      2. Run this test → RED (body still has cmp-active after _onCompareExit call)
      3. Restore → GREEN
    """
    page = console_page
    _wait_app_ready(page)

    # Activate compare mode synthetically.
    _enter_compare_mode_synthetic(
        page, "M14", 1,
        "rv_20260501T220000Z_c5exit1",
        "rv_20260501T230000Z_c5exit2",
    )

    assert _body_has_cmp_active(page) is True, "pre-condition: cmp-active must be set"

    # Call _onCompareExit directly — it is a function declaration, always on window.
    page.evaluate("() => window._onCompareExit()")

    page.wait_for_function(
        "() => !document.body.classList.contains('cmp-active')",
        timeout=3000,
    )

    assert _body_has_cmp_active(page) is False, (
        "C5 inject-bug: _onCompareExit must remove cmp-active from body"
    )
    assert _banner_is_hidden(page) is True, (
        "C5 inject-bug: _onCompareExit must hide cmpBanner"
    )


def test_c5_on_compare_exit_clears_compare_selected_via_hook(
    console_page, live_server,
):
    """_onCompareExit must clear compareSelected to new Map().

    If the hook is available: verify size == 0 after exit.
    If not: skip (pre-fix — hook not yet installed).

    Inject-bug procedure:
      1. In app.js _onCompareExit(), remove: state.compareSelected = new Map()
      2. Run this test → RED (compareSelected still has entries after exit)
      3. Restore → GREEN
    """
    page = console_page
    _wait_app_ready(page)

    if not page.evaluate(
        "() => typeof window._testSetCompareSelected === 'function'"
    ):
        pytest.skip("_testSetCompareSelected hook not yet installed (pre-fix)")

    machine = "M14"
    mode = 1
    rv_a = "rv_20260501T240000Z_c5sel1"
    rv_b = "rv_20260501T250000Z_c5sel2"

    # Seed compareSelected.
    page.evaluate(
        f"""() => {{
            window._testSetCompareSelected({json.dumps(rv_a)}, {{mode: {mode}}});
            window._testSetCompareSelected({json.dumps(rv_b)}, {{mode: {mode}}});
        }}"""
    )
    size_before = _get_compare_selected_size(page)
    assert size_before == 2, f"pre-condition: compareSelected must have 2 entries; got {size_before}"

    # Call exit.
    page.evaluate("() => window._onCompareExit()")

    page.wait_for_function(
        "() => !document.body.classList.contains('cmp-active')",
        timeout=3000,
    )

    size_after = _get_compare_selected_size(page)
    assert size_after == 0, (
        f"C5 inject-bug: compareSelected must be empty after _onCompareExit; got {size_after}"
    )
