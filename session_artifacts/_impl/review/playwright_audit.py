"""UI completeness audit via Playwright headless chromium.

Runs against an already-spawned uvicorn at 127.0.0.1:8879.

Captures:
- 3 screenshots (top / middle / bottom viewport scroll positions)
- All console messages (log/info/warn/error)
- All requestfailed network events
- DOM snapshot listing each <section class="panel ..."> and whether
  it's visually rendered (not display:none / not collapsed-to-zero)

Writes JSON results to session_artifacts/_impl/review/audit_result.json
and screenshots to session_artifacts/_impl/review/ui_audit_{top,mid,bot}.png.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, ConsoleMessage, Request


REVIEW_DIR = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8879/console/"


def main() -> int:
    console_msgs: list[dict] = []
    failed_requests: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        page.on("console", lambda m: console_msgs.append({
            "type": m.type,
            "text": m.text,
            "location": str(m.location) if m.location else "",
        }))
        page.on("requestfailed", lambda req: failed_requests.append({
            "url": req.url,
            "method": req.method,
            "failure": req.failure or "",
            "resource_type": req.resource_type,
        }))

        page.goto(URL, wait_until="networkidle", timeout=30000)
        # Give the bootstrap / boot() a moment to wire panels.
        page.wait_for_timeout(2500)

        # ── Inventory ALL panels via DOM ────────────────────────────
        panels = page.evaluate(
            r"""
            () => {
              const out = [];
              const all = document.querySelectorAll('section.panel');
              for (const el of all) {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                const cls = el.className || "";
                const id = el.id || "";
                const h2 = el.querySelector('h2');
                const title = h2 ? (h2.textContent || "").trim() : "";
                out.push({
                  id,
                  className: cls,
                  title,
                  width: Math.round(rect.width),
                  height: Math.round(rect.height),
                  display: style.display,
                  visibility: style.visibility,
                  isHidden: el.classList.contains('hidden'),
                });
              }
              return out;
            }
            """
        )

        # ── Top viewport ─────────────────────────────────────────────
        # Make sure we're scrolled to top first.
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        top_png = REVIEW_DIR / "ui_audit_top.png"
        page.screenshot(path=str(top_png), full_page=False)

        # ── Switch to debug tab too, to capture analyzer panel set
        # (mostly hidden until a run loads, but at least we see the
        # tab body) ──── still on manage tab first.
        # ── Get scroll height ────────────────────────────────────────
        scroll_h = page.evaluate("document.documentElement.scrollHeight")
        viewport_h = page.evaluate("window.innerHeight")

        # ── Middle viewport ──────────────────────────────────────────
        mid_y = max(0, (scroll_h - viewport_h) // 2)
        page.evaluate(f"window.scrollTo(0, {mid_y})")
        page.wait_for_timeout(400)
        mid_png = REVIEW_DIR / "ui_audit_mid.png"
        page.screenshot(path=str(mid_png), full_page=False)

        # ── Bottom viewport (system area: server-mgmt + config-upload + fleet-refresh) ─
        bot_y = max(0, scroll_h - viewport_h)
        page.evaluate(f"window.scrollTo(0, {bot_y})")
        page.wait_for_timeout(500)
        bot_png = REVIEW_DIR / "ui_audit_bot.png"
        page.screenshot(path=str(bot_png), full_page=False)

        # ── Full-page screenshot too for completeness ────────────────
        full_png = REVIEW_DIR / "ui_audit_full.png"
        page.screenshot(path=str(full_png), full_page=True)

        # ── Functional probes: check P3 panel buttons exist + click without crash ─
        functional = {}

        # 1. server-mgmt: click refreshMd5Btn — capture request fired
        functional["refreshMd5"] = _probe_btn(
            page, "#refreshMd5Btn", expected_url_fragment="/api/machines/refresh-md5",
            method="POST", click_and_wait_ms=2000,
        )

        # 2. config-upload: click upload without file → expect status text
        # First clear any error from refresh button
        functional["configUploadNoFile"] = _probe_no_file_upload(page)

        # 3. fleet refresh: get current status (poll endpoint), do NOT start
        functional["fleetRefreshStatus"] = _probe_fleet_status(page)

        # 4. server compare: select dev + prod, click compare
        functional["serverCompare"] = _probe_server_compare(page)

        # ── Check existence of every expected handler-bound element ──
        ids = page.evaluate(
            r"""
            () => {
              const want = [
                'serverTableBody','refreshMd5Btn','addServerBtn','compareServersBtn',
                'compareServerA','compareServerB','serverCompareResult',
                'configUploadPanel','configFileInput','configDisplayNameInput',
                'configUploadBtn','configUploadStatus','configListWrap',
                'fleetRefreshPanel','fleetRefreshStartBtn','fleetRefreshCancelBtn',
                'fleetRefreshStatus','fleetRefreshProgress','fleetRefreshProgressMeta',
                'fleetRefreshProgressInner',
              ];
              const out = {};
              for (const id of want) {
                const el = document.getElementById(id);
                out[id] = el ? {present: true, visible: el.offsetParent !== null} : {present: false};
              }
              return out;
            }
            """
        )

        # ── i18n: verify applied text shows zh, not raw key ───────────
        i18n_check = page.evaluate(
            r"""
            () => {
              const out = {};
              const sample = document.querySelector('[data-i18n="panelServerManagement"]');
              out.panelServerManagement = sample ? sample.textContent : null;
              const cfg = document.querySelector('[data-i18n="panelConfigUpload"]');
              out.panelConfigUpload = cfg ? cfg.textContent : null;
              const fr = document.querySelector('[data-i18n="panelFleetRefresh"]');
              out.panelFleetRefresh = fr ? fr.textContent : null;
              const btn = document.querySelector('[data-i18n="btnFleetRefreshStart"]');
              out.btnFleetRefreshStart = btn ? btn.textContent : null;
              const upload = document.querySelector('[data-i18n="btnConfigUpload"]');
              out.btnConfigUpload = upload ? upload.textContent : null;
              return out;
            }
            """
        )

        browser.close()

    result = {
        "panels": panels,
        "console_msgs": console_msgs,
        "failed_requests": failed_requests,
        "element_presence": ids,
        "i18n_applied": i18n_check,
        "functional_probes": functional,
        "screenshots": {
            "top": str(top_png.relative_to(REVIEW_DIR.parent.parent.parent)),
            "mid": str(mid_png.relative_to(REVIEW_DIR.parent.parent.parent)),
            "bot": str(bot_png.relative_to(REVIEW_DIR.parent.parent.parent)),
            "full": str(full_png.relative_to(REVIEW_DIR.parent.parent.parent)),
        },
    }
    out_path = REVIEW_DIR / "audit_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"panels: {len(panels)}  console_msgs: {len(console_msgs)}  failed_requests: {len(failed_requests)}")
    return 0


def _probe_btn(page, selector, expected_url_fragment, method, click_and_wait_ms):
    """Click a button and verify a network request is fired."""
    requests_seen = []
    handler = lambda req: requests_seen.append({
        "url": req.url, "method": req.method,
    }) if expected_url_fragment in req.url else None
    page.on("request", handler)
    try:
        page.wait_for_selector(selector, state="attached", timeout=3000)
        el = page.query_selector(selector)
        if not el:
            return {"ok": False, "error": "selector not found"}
        # Scroll into view
        el.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        # Suppress alerts so we don't hang
        page.once("dialog", lambda d: d.dismiss())
        el.click(timeout=3000)
        page.wait_for_timeout(click_and_wait_ms)
        matched = [r for r in requests_seen if expected_url_fragment in r["url"]]
        return {
            "ok": len(matched) > 0,
            "matched_requests": matched,
            "all_requests_seen": requests_seen[:10],
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        page.remove_listener("request", handler)


def _probe_no_file_upload(page):
    """Click upload without selecting file → expect status to show 'no file' message."""
    try:
        page.wait_for_selector("#configUploadBtn", state="attached", timeout=3000)
        btn = page.query_selector("#configUploadBtn")
        btn.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        btn.click(timeout=3000)
        page.wait_for_timeout(500)
        status_text = page.evaluate("document.getElementById('configUploadStatus').textContent")
        return {"ok": bool(status_text and status_text.strip()), "status_text": status_text}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _probe_fleet_status(page):
    """Just read the fleet refresh status pane — don't click start."""
    try:
        page.wait_for_selector("#fleetRefreshStatus", state="attached", timeout=3000)
        return page.evaluate(
            r"""
            () => {
              return {
                status: document.getElementById('fleetRefreshStatus').textContent,
                progressVisible: !document.getElementById('fleetRefreshProgress').classList.contains('hidden'),
                startBtnDisabled: document.getElementById('fleetRefreshStartBtn').disabled,
                cancelBtnHidden: document.getElementById('fleetRefreshCancelBtn').classList.contains('hidden'),
              };
            }
            """
        )
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def _probe_server_compare(page):
    """Select two servers, click compare, return resulting state."""
    try:
        # Read available server options first.
        opts_a = page.evaluate(
            "Array.from(document.getElementById('compareServerA').options).map(o => o.value)"
        )
        opts_b = page.evaluate(
            "Array.from(document.getElementById('compareServerB').options).map(o => o.value)"
        )
        if len(opts_a) < 2:
            return {"ok": False, "reason": "fewer than 2 servers available", "options_a": opts_a, "options_b": opts_b}
        # Pick first two distinct.
        a_val = opts_a[0]
        b_val = next((v for v in opts_b if v != a_val), None)
        if not b_val:
            return {"ok": False, "reason": "no distinct second server", "options_a": opts_a, "options_b": opts_b}
        page.select_option("#compareServerA", a_val)
        page.select_option("#compareServerB", b_val)
        page.wait_for_timeout(150)

        requests_seen = []
        handler = lambda req: requests_seen.append({"url": req.url, "method": req.method}) if "/api/servers/compare" in req.url else None
        page.on("request", handler)
        try:
            page.click("#compareServersBtn", timeout=3000)
            page.wait_for_timeout(2500)
            result_text = page.evaluate("document.getElementById('serverCompareResult').innerHTML")
        finally:
            page.remove_listener("request", handler)

        return {
            "ok": True,
            "selected_a": a_val,
            "selected_b": b_val,
            "requests_seen": requests_seen,
            "result_html_len": len(result_text or ""),
            "result_html_excerpt": (result_text or "")[:300],
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    sys.exit(main())
