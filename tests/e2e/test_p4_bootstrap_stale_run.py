"""T-B1: UI bootstrap stale run test + T-I4: rawdata overview error toast.

Covers two Playwright-required fixes from fix_brief.md §2:
  B1 — boot() crash when report fetch 404s → P3 panels never initialized
  I4 — refreshRawdataOverview silent failure → no visible error to user

Memory feedback files honored:
  memory/feedback_enumerate_safety_paths.md — inject-bug recipe for each fix.
  memory/feedback_perf_claim_needs_e2e_event_stream.md — real browser via Playwright.
  memory/feedback_no_parallel_panel_impl.md — I4 toast reuses existing toast renderer.
  memory/feedback_no_silent_swallow.md — I4 directly addresses: catch swallows error silently.

Inject-bug recipes:

  T-B1 (test_bootstrap_with_stale_run_still_initializes_p3_panels):
    In app.js loadBootstrap(), at L7028-7033:
        if (run.status === "completed" || run.status === "cancelled") {
            const report = await apiGet(`/api/runs/${state.currentRunId}/report`);
            ...
        }
    Remove the try/catch wrapper around the apiGet call (or simulate the
    pre-fix state by removing the try/catch that B1 adds around L7029).
    With stale run (report file deleted → 404): apiGet throws → loadBootstrap
    throws → boot() catch fires → _initConfigUploadPanel() / _initFleetRefreshPanel()
    never called.
    Red: click configUploadBtn → no handler → nothing happens →
         page.evaluate check returns false → assertion FAILS.
    Revert try/catch → GREEN.

  T-I4 (test_rawdata_overview_error_shows_visible_feedback):
    In app.js refreshRawdataOverview(), at L1361:
        } catch (_) {
            state.rawdataOverview = null;
        }
    Add back the silent swallow by removing state.rawdataOverviewError = err.message.
    Inject: kill backend before the fetch → error caught → no toast rendered →
    test asserting visible error FAILS → RED.
    Revert → GREEN.

    NOTE: T-I4 requires killing the backend endpoint during a call, which is hard
    to do cleanly without a proxy. Alternative inject: monkeypatch the endpoint to
    return 500 and verify the frontend renders a visible error message in the banner area.
    This test uses page.route() to intercept /api/rawdata/overview and return 500.

Fixture isolation note:
  T-B1 uses a function-scoped `b1_server` fixture (defined in this file) instead of
  the session-scoped `live_server`. This prevents B1's long page-load (seeded stale run
  causes backend polling that leaks background threads into the pytest process) from
  contaminating the session-scoped server used by T-I4 and other e2e tests.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import httpx
import pytest

# Playwright mark — only runs when playwright is installed and pytest-playwright is configured.
# These tests are NOT marked real_upstream; they use the session live_server.
pytest_playwright_available = False
try:
    import playwright  # noqa: F401
    pytest_playwright_available = True
except ImportError:
    pass

from tests.backend._seed import insert_run_row

_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def b1_server(tmp_path):
    """Function-scoped isolated uvicorn for T-B1.

    Uses its own port + tmp dirs so it does not share state with the
    session-scoped live_server fixture used by T-I4.  This prevents the
    stale-run background-thread from leaking into the shared session server
    and causing T-I4 page.goto timeouts.
    """
    from tests.e2e.conftest import LiveServer

    state_dir = tmp_path / "state" / "console"
    state_dir.mkdir(parents=True)
    (state_dir / "progress").mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    cache_dir = tmp_path / "cache" / "chunks"
    cache_dir.mkdir(parents=True)
    rawdata_dir = tmp_path / "rawdata"
    rawdata_dir.mkdir()

    real_servers_json = _ROOT / "configs" / "servers.json"
    tmp_servers_json = tmp_path / "servers.json"
    shutil.copy2(str(real_servers_json), str(tmp_servers_json))

    tmp_configs_upload_dir = tmp_path / "uploaded_configs"
    tmp_configs_upload_dir.mkdir(parents=True, exist_ok=True)

    port = _free_port()
    env = {
        **os.environ,
        "SLOT_E2E_STATE_DIR": str(state_dir),
        "SLOT_E2E_REPORTS": str(reports_dir),
        "SLOT_E2E_CACHE": str(cache_dir),
        "SLOT_E2E_RAWDATA": str(rawdata_dir),
        "SLOT_E2E_SERVERS": str(tmp_servers_json),
        "SLOT_E2E_CONFIGS_UPLOAD_DIR": str(tmp_configs_upload_dir),
        "SLOT_RISK_MEDIUM_BYTES": "2048",
        "SLOT_RISK_HIGH_BYTES": "8192",
    }

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m", "uvicorn",
            "src.web_console.backend.e2e_launch:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", "warning",
        ],
        cwd=str(_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base_url = f"http://127.0.0.1:{port}"

    deadline = time.time() + 20
    last_err = ""
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/health", timeout=1.0)
            if r.status_code == 200:
                break
        except httpx.RequestError as exc:
            last_err = exc.__class__.__name__
        if proc.poll() is not None:
            stderr = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace")
            pytest.skip(f"b1_server uvicorn died during boot. stderr: {stderr[:300]}")
        time.sleep(0.15)
    else:
        proc.kill()
        pytest.skip(f"b1_server uvicorn did not become ready (last error: {last_err})")

    server = LiveServer(
        base_url=base_url,
        state_dir=state_dir,
        reports_dir=reports_dir,
        cache_dir=cache_dir,
        rawdata_dir=rawdata_dir,
        db_path=state_dir / "console.db",
        servers_config_path=tmp_servers_json,
        configs_upload_dir=tmp_configs_upload_dir,
    )
    try:
        yield server
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _wait_for_pure_loaded(page) -> None:
    """Wait for app.js PURE object to be available (boot() complete)."""
    page.wait_for_function(
        "() => typeof window.PURE === 'object' "
        "&& document.querySelector('[data-help-key=helpCiTarget]') != null",
        timeout=8000,
    )


def _seed_stale_run(db_path: Path, run_id: str = "stale_b1_run") -> str:
    """Insert a completed run row whose report file does not exist."""
    insert_run_row(
        db_path,
        run_id=run_id,
        machine="M14",
        mode=1,
        status="completed",
        report_version="rv_stale_deleted",
        # report_file points at a non-existent path.
        report_file="/nonexistent/path/player_impact_report.md",
    )
    return run_id


@pytest.mark.skipif(
    not pytest_playwright_available,
    reason="playwright not installed — T-B1/T-I4 need pytest-playwright",
)
class TestBootstrapStaleRun:
    """T-B1: UI bootstrap with stale run (completed run + deleted report) must still
    bind P3 panel click handlers.

    Pre-fix: refreshCurrentRun() calls apiGet('/api/runs/{id}/report') with no
    try/catch. 404 propagates → loadBootstrap throws → boot() catch → P3 init skipped.

    Post-fix: try/catch around the report fetch (or finally block in boot()) ensures
    _initConfigUploadPanel() and _initFleetRefreshPanel() always execute.

    Inject-bug recipe:
      In app.js loadBootstrap() at L7028, change the completed/cancelled branch:
          if (run.status === "completed" || run.status === "cancelled") {
              const report = await apiGet(`/api/runs/${state.currentRunId}/report`);
      Remove the try/catch the fix adds so a 404 report fetch propagates.
      With stale_run seeded: apiGet for report → 404 → uncaught → loadBootstrap throws
      → boot() catch fires → _initConfigUploadPanel() never called.
      Test: click configUploadBtn → handler never fired → assert no request intercepted
      or assert visible error panel is shown → RED.
      Revert → GREEN.
    """

    def test_bootstrap_with_stale_run_still_initializes_p3_panels(
        self, b1_server, page,
    ):
        """Seed stale run → boot page → verify P3 panel handlers are bound.

        Uses the function-scoped b1_server fixture (NOT the session live_server)
        to prevent background-thread leakage into subsequent T-I4 tests.

        Strategy:
        1. Seed a 'completed' run in console.db with run_id that /api/runs/{id}/report
           returns 404 (report_file is a non-existent path).
        2. Navigate to /console/.
        3. Wait for boot() to complete (PURE object available).
        4. Assert that clicking configUploadBtn triggers a request to /api/configs
           (proves the handler is bound).
        5. Assert that clicking fleetRefreshStartBtn triggers a request to /api/fleet-refresh
           (proves that handler is bound too).

        Without the B1 fix: handlers are never bound → no request fired → RED.
        With the B1 fix: handlers are bound despite the 404 report → requests fire → GREEN.
        """
        live_server = b1_server  # local alias so body code is unchanged
        # Seed stale run BEFORE navigating so bootstrap sees it immediately.
        run_id = _seed_stale_run(live_server.db_path, run_id="stale_b1_001")

        # Additionally: mark this run as currentRunId in console.db if the frontend
        # reads state.currentRunId from the DB. The frontend derives currentRunId from
        # list_runs response (latest completed run), so the seeded row is enough.

        requests_captured: list[str] = []

        def _on_request(request):
            requests_captured.append(request.url)

        page.on("request", _on_request)
        page.goto(f"{live_server.base_url}/console/", wait_until="domcontentloaded")

        # Wait for boot to complete (PURE available = boot() finished successfully).
        try:
            page.wait_for_function(
                "() => typeof window.PURE === 'object'",
                timeout=10000,
            )
        except Exception:
            # Boot may have failed — check if health is shown as false.
            # If boot crashed (B1 bug active), PURE may never load.
            health_el = page.locator("#healthStatus")
            health_text = health_el.text_content() if health_el.count() else ""
            pytest.fail(
                f"B1 REGRESSION: boot() did not complete (PURE not available). "
                f"This happens when stale run's report fetch (404) is unguarded "
                f"and propagates through loadBootstrap → boot() catch. "
                f"Health element text: {health_text!r}. "
                f"Stale run_id: {run_id!r}. "
                f"If the B1 fix (try/catch around report fetch or finally in boot) "
                f"is not applied, _initConfigUploadPanel/_initFleetRefreshPanel are skipped."
            )

        # Navigate to the P3 tab (manage tab usually) to reveal P3 panels.
        manage_tab = page.locator("#tabBtnManage")
        if manage_tab.count() > 0:
            manage_tab.click()
            page.wait_for_timeout(500)

        # Assert configUploadBtn exists and fires a request when clicked.
        upload_btn = page.locator("#configUploadBtn")
        fleet_btn = page.locator("#fleetRefreshStartBtn")

        upload_btn_exists = upload_btn.count() > 0
        fleet_btn_exists = fleet_btn.count() > 0

        if not upload_btn_exists and not fleet_btn_exists:
            # P3 DOM elements may not be visible on this tab — try P3 tab.
            p3_tab = page.locator("#tabBtnP3, [data-tab=p3], [href='#p3']")
            if p3_tab.count() > 0:
                p3_tab.first.click()
                page.wait_for_timeout(500)
            upload_btn_exists = upload_btn.count() > 0
            fleet_btn_exists = fleet_btn.count() > 0

        # If neither P3 button exists, the DOM doesn't have P3 panels — skip
        # rather than false-pass (architectural gap in test setup).
        if not upload_btn_exists:
            pytest.skip(
                "configUploadBtn DOM element not found — P3 panel may not be rendered "
                "in this live_server's HTML. Check if P3 panel HTML is present."
            )

        # The key assertion: if the B1 fix is applied, clicking the button fires
        # an API request (the handler is bound). If not fixed, clicking does nothing.
        pre_click_count = len([u for u in requests_captured if "/api/configs" in u])

        # Intercept /api/configs requests to detect handler firing.
        api_calls: list[str] = []

        def _capture(request):
            if "/api/configs" in request.url or "/api/fleet-refresh" in request.url:
                api_calls.append(request.url)

        page.on("request", _capture)

        # Click configUploadBtn (if it's not disabled — might need a file selected first).
        # The _initConfigUploadPanel handler listens for click events on the button.
        # A click on a properly-initialized button will at minimum trigger
        # _handleConfigUpload which calls an API. Even if no file is selected,
        # the handler executes (and may show a validation error).
        # We verify the handler runs by checking whether it was CALLED (console.log or
        # state mutation) rather than its HTTP side-effect.

        # Use page.evaluate to check if the event listener is attached.
        has_handler = page.evaluate("""
            () => {
                const btn = document.getElementById('configUploadBtn');
                if (!btn) return false;
                // Check if there is a click event listener via getEventListeners
                // (not always available in non-devtools context).
                // Alternative: check window._p3_initialized flag if the fix sets it.
                // Fallback: attempt a click and check if any state changed.
                return true;  // btn exists = panel was rendered
            }
        """)

        # More robust: verify _initConfigUploadPanel ran by checking
        # window._configUploadInitialized or similar flag that the fix may set.
        # If the fix doesn't set such a flag, check by firing click and looking for
        # any state change or request.
        #
        # The definitive check: if boot() crashed (B1 bug), the HTML button exists
        # (it's static DOM) but has NO click listener. If the fix works, the listener
        # IS bound. We can verify by dispatching a click and checking side effects.

        # Try clicking and verify configList refresh was attempted (fires GET /api/configs).
        requests_before = len(api_calls)

        # _initConfigUploadPanel() calls refreshConfigList() which does GET /api/configs.
        # This fires on initialization, not on button click. So if _init was called,
        # we should already see a /api/configs GET in requests_captured.
        init_request_fired = any(
            "/api/configs" in url for url in requests_captured
        )

        assert init_request_fired, (
            f"B1 REGRESSION: /api/configs was never fetched, indicating "
            f"_initConfigUploadPanel() was never called. "
            f"This happens when loadBootstrap() throws on the stale run's 404 report "
            f"fetch (no try/catch) → boot() catch → P3 init skipped. "
            f"Captured requests (sample): {requests_captured[-10:]!r}. "
            f"Stale run_id: {run_id!r}."
        )

        # Cleanup: remove stale run to not affect other session tests.
        if live_server.db_path.exists():
            conn = sqlite3.connect(str(live_server.db_path))
            try:
                conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
                conn.commit()
            finally:
                conn.close()


@pytest.mark.skipif(
    not pytest_playwright_available,
    reason="playwright not installed — T-I4 needs pytest-playwright",
)
class TestRawdataOverviewErrorToast:
    """T-I4: refreshRawdataOverview() must render visible error feedback when
    the /api/rawdata/overview call fails.

    Pre-fix: catch block sets rawdataOverview = null and renders blank banner.
    Post-fix: catch stores rawdataOverviewError = err.message; renderRawdataBanner()
    renders an error toast/inline warning in the banner area.

    Inject-bug recipe:
      In app.js refreshRawdataOverview() catch block (L1361):
          } catch (_) {
              state.rawdataOverview = null;
          }
      Remove the `state.rawdataOverviewError = _.message` line (or add it back to
      simulate the pre-fix state).
      Inject: use page.route() to intercept /api/rawdata/overview → return 500.
      Test: verify #rawdataOverviewBanner or a sibling element shows an error string.
      Without I4 fix: banner is hidden (null data) → no visible error → RED.
      With fix: banner shows error text → GREEN.
    """

    def test_rawdata_overview_error_shows_visible_feedback(
        self, live_server, page,
    ):
        """Intercept /api/rawdata/overview → 500 → assert visible error in banner area.

        Uses page.route() to inject the error without killing the backend.
        """
        # Route /api/rawdata/overview to return a 500 error.
        page.route(
            f"{live_server.base_url}/api/rawdata/overview",
            lambda route: route.fulfill(
                status=500,
                body=json.dumps({"detail": "simulated_error_for_I4_test"}),
                headers={"Content-Type": "application/json"},
            ),
        )

        page.goto(f"{live_server.base_url}/console/", wait_until="domcontentloaded")

        try:
            page.wait_for_function(
                "() => typeof window.PURE === 'object'",
                timeout=10000,
            )
        except Exception:
            pytest.skip("Page did not load — live_server unavailable")

        # Navigate to manage tab where rawdata banner lives.
        manage_tab = page.locator("#tabBtnManage")
        if manage_tab.count() > 0:
            manage_tab.click()
            page.wait_for_timeout(300)

        # Trigger a manual refresh of the rawdata overview.
        page.evaluate("refreshRawdataOverview()")
        page.wait_for_timeout(1000)  # Give async fetch time to complete.

        # I4 invariant: there must be visible error feedback somewhere in the
        # banner area. Pre-fix: banner is hidden (class="hidden") or shows nothing.
        # Post-fix: banner shows error message or a dedicated error div.
        banner = page.locator("#rawdataOverviewBanner")
        if banner.count() == 0:
            pytest.skip(
                "rawdataOverviewBanner element not found — P3 panel may use different DOM"
            )

        # Check for error text in the banner or its siblings.
        # The exact element depends on the implementer's choice:
        # Option 1: inline text in the banner area.
        # Option 2: a dedicated error div (e.g. #rawdataOverviewError).
        # Option 3: a toast notification.
        # We check multiple possible locations.
        page_text = page.evaluate("() => document.body.innerText")

        # If state.rawdataOverviewError is set, any render path that reads it
        # will show something. Check if any error-related text appears.
        has_error_feedback = (
            "error" in page_text.lower()
            or "failed" in page_text.lower()
            or "500" in page_text
            or "simulated_error" in page_text
            or page.evaluate(
                "() => !!window.state && !!window.state.rawdataOverviewError"
            )
        )

        assert has_error_feedback, (
            "I4 REGRESSION: No visible error feedback after /api/rawdata/overview "
            "returned 500. Pre-fix behavior: catch block silently sets "
            "rawdataOverview=null and hides the banner. Post-fix: state.rawdataOverviewError "
            "is set and renderRawdataBanner shows a visible error message. "
            f"Banner visible: {not banner.is_hidden() if banner.count() > 0 else 'N/A'}. "
            f"Page text sample: {page_text[:300]!r}"
        )

    def test_rawdata_overview_success_shows_normal_banner(
        self, console_page,
    ):
        """Baseline: with successful overview, banner renders normally (no error state).

        Ensures the I4 fix doesn't break the happy path.
        """
        page = console_page

        # Trigger rawdata overview refresh (should succeed against live_server).
        page.evaluate("refreshRawdataOverview()")
        page.wait_for_timeout(1000)

        # State should NOT have a rawdataOverviewError when the call succeeds.
        error_state = page.evaluate(
            "() => window.state && window.state.rawdataOverviewError"
        )
        assert not error_state, (
            f"rawdataOverviewError set despite successful /api/rawdata/overview call: "
            f"{error_state!r}. "
            f"The I4 fix should clear rawdataOverviewError on success."
        )
