"""Playwright smoke tests for the local Slot Console.

Covers the UX contracts that pure-function tests can't verify:
- bilingual tooltip rendering when the language selector flips
- cache-cleanup risk-tier dialog flow (low: one confirm; high: confirm + DELETE token)
- start / autotune buttons disable themselves when an active run row exists
"""
from __future__ import annotations

import sqlite3

import pytest

from tests.backend._seed import insert_run_row


# Marks tests that pinned the pre-2026-04-17 UI: sidebar with startBtn /
# autotuneBtn / ciSelect / modeSelect / runMeta / progressBar, etc.
# The UI was restructured to fold sampling exclusively into the
# 机台管理 tab's 采样选中机台 panel; the 调试机台 tab is display-only
# now. Those old DOM nodes are gone, so these tests can never pass in
# their current form. Kept as skips (not deletes) so the history of
# what they pinned is still discoverable in code.
_obsolete_post_restructure = pytest.mark.skip(
    reason="obsolete after 2026-04-17 UI restructure: sidebar and its "
           "ciSelect/modeSelect/startBtn/runMeta are gone; sampling now "
           "runs from the manage-tab 采样选中机台 panel (sampleMode / "
           "sampleCi / sampleStartBtn). Rewrite pending."
)


def _wait_for_pure_loaded(page) -> None:
    page.wait_for_function(
        "() => typeof window.PURE === 'object' "
        "&& document.querySelector('[data-help-key=helpCiTarget]') != null",
        timeout=5000,
    )


def _wait_for_tooltip(page, ref_lang: str) -> None:
    """Wait for applyFieldHelpHints to populate the title attribute for a
    well-known help-dot, comparing against the expected value computed via
    PURE.fmt in the page context.
    """
    page.wait_for_function(
        f"""() => {{
            const el = document.querySelector('[data-help-key=helpCiTarget]');
            if (!el || !window.PURE) return false;
            const expected = window.PURE.fmt('{ref_lang}', 'helpCiTarget');
            return el.getAttribute('title') === expected;
        }}""",
        timeout=5000,
    )


def test_boot_and_language_switch(console_page):
    page = console_page
    _wait_for_pure_loaded(page)

    # Default language is zh -- tooltip should be Chinese.
    _wait_for_tooltip(page, "zh")
    title_zh = page.locator("[data-help-key=helpCiTarget]").get_attribute("title")
    assert title_zh and "目标 CI 半宽" in title_zh

    # Switch to English.
    page.select_option("#langSelect", "en")
    _wait_for_tooltip(page, "en")
    title_en = page.locator("[data-help-key=helpCiTarget]").get_attribute("title")
    assert title_en and "Target CI half-width" in title_en

    # Switch back to Chinese.
    page.select_option("#langSelect", "zh")
    _wait_for_tooltip(page, "zh")
    title_back = page.locator("[data-help-key=helpCiTarget]").get_attribute("title")
    assert title_back and "目标 CI 半宽" in title_back


def _write_rawdata_chunk(mode_dir: Path, idx: int, pad_bytes: int) -> Path:
    """Write an envelope-shaped chunk padded to approximately pad_bytes
    total so e2e risk-tier checks hit the intended threshold. Retention
    is reset to 0 by the caller so every chunk is deletable."""
    import json
    mode_dir.mkdir(parents=True, exist_ok=True)
    padding = "x" * max(0, pad_bytes - 300)  # rough envelope overhead
    p = mode_dir / f"chunk_{idx:04d}.json"
    p.write_text(json.dumps({
        "_cache_version": 3, "_machine": "M14", "_mode": 1, "_bet": 1000,
        "_spin_times": 1000, "_robot_count": 1, "_chunk_index": idx,
        "_saved_at": "2026-04-01T00:00:00Z",
        "_config_md5": "", "_code_md5": "",
        "_padding": padding, "response": [],
    }), encoding="utf-8")
    return p


def test_rawdata_banner_cleanup_flow(console_page, clean_cache, clean_runs,
                                      live_server):
    """Replaces the old tiered cache-cleanup tests (2026-04-19 master/detail
    refactor removed the Chunk 缓存 panel + its risk-tier + DELETE-token
    prompts). The rawdata banner's 一键清理 is now a single-confirm flow
    that hits POST /api/cache/cleanup end-to-end."""
    import httpx
    page = console_page
    _wait_for_pure_loaded(page)

    page.click("#tabBtnManage")

    # Retention 0 → every chunk we drop is immediately reclaimable.
    r = httpx.put(
        f"{live_server.base_url}/api/settings",
        json={"min_retention_spins": 0}, timeout=5,
    )
    assert r.status_code == 200

    chunk = _write_rawdata_chunk(
        live_server.rawdata_dir / "M14" / "mode_1", 1, pad_bytes=1024,
    )

    # Force a banner refresh so it sees the new chunk + shows the cleanup btn.
    page.evaluate("refreshRawdataOverview()")
    page.wait_for_function(
        "() => { const b = document.getElementById('rawdataBannerCleanupBtn'); "
        "return b && !b.disabled; }",
        timeout=5000,
    )

    dialogs: list[dict] = []

    def _on_dialog(dialog):
        dialogs.append({"type": dialog.type, "message": dialog.message})
        dialog.accept()

    page.on("dialog", _on_dialog)
    page.click("#rawdataBannerCleanupBtn")

    page.wait_for_function(
        "async () => { const r = await fetch('/api/rawdata/M14').then(r => r.json()); "
        "const m1 = r.modes && r.modes['1']; "
        "if (!m1) return true; "
        "const c = m1.classified || {}; "
        "return (c.kept_chunks + c.deletable_chunks + c.stale_chunks) === 0; }",
        timeout=5000,
    )

    # New banner flow: single confirm, no DELETE token prompt.
    assert any(d["type"] == "confirm" for d in dialogs)


@_obsolete_post_restructure
def test_mode_2_forces_fuzzy_option(console_page, clean_runs):
    """Switching to mode 2 must auto-select the fuzzy ciSelect option ("0")
    and disable every other tier, since the backend rejects mode 2/5 with
    a non-zero target_halfwidth_pp (Commit 3)."""
    page = console_page
    _wait_for_pure_loaded(page)
    # Default mode is 1; sanity-check all options enabled.
    state_before = page.evaluate(
        "() => { const s = document.getElementById('ciSelect'); "
        "return {value: s.value, disabled: Array.from(s.options).map(o => o.disabled)}; }"
    )
    assert state_before["value"] == "0.5"
    assert state_before["disabled"] == [False, False, False, False, False]

    page.select_option("#modeSelect", "2")
    page.wait_for_function(
        "() => document.getElementById('ciSelect').value === '0'",
        timeout=2000,
    )
    state_after = page.evaluate(
        "() => { const s = document.getElementById('ciSelect'); "
        "return {value: s.value, disabled: Array.from(s.options).map(o => o.disabled)}; }"
    )
    assert state_after["value"] == "0"
    # First four (0.5 / 1 / 2 / 5) disabled; fuzzy (index 4, value "0") enabled.
    assert state_after["disabled"] == [True, True, True, True, False]

    # Switching back to mode 7 must re-enable everything and snap to 0.5.
    page.select_option("#modeSelect", "7")
    page.wait_for_function(
        "() => document.getElementById('ciSelect').value === '0.5'",
        timeout=2000,
    )
    restored = page.evaluate(
        "() => Array.from(document.getElementById('ciSelect').options).map(o => o.disabled)"
    )
    assert restored == [False, False, False, False, False]


@_obsolete_post_restructure
def test_start_enabled_with_preset_concurrency(console_page, clean_runs):
    """Fresh page load: Start button must be ENABLED because robotInput /
    concInput carry preset defaults (validated on M272 mode 1 via Auto Tune).
    Clearing either input re-locks Start until it's repopulated."""
    page = console_page
    _wait_for_pure_loaded(page)

    # Presets are in place on first load -> Start enabled.
    page.wait_for_function(
        "() => document.getElementById('startBtn').disabled === false",
        timeout=3000,
    )
    # Sanity: the preset values came through.
    robot_val = page.evaluate("() => document.getElementById('robotInput').value")
    conc_val = page.evaluate("() => document.getElementById('concInput').value")
    assert int(robot_val) > 0, f"robot preset missing: {robot_val!r}"
    assert int(conc_val) > 0, f"conc preset missing: {conc_val!r}"

    # Clear both inputs -> Start should re-disable with a validation tip.
    page.evaluate(
        "() => { "
        "  document.getElementById('robotInput').value = ''; "
        "  document.getElementById('concInput').value = ''; "
        "  document.getElementById('ciSelect').dispatchEvent(new Event('change')); "
        "}"
    )
    page.wait_for_function(
        "() => document.getElementById('startBtn').disabled === true",
        timeout=2000,
    )
    tip = page.locator("#startBtn").get_attribute("title") or ""
    assert "Auto Tune" in tip or "压测" in tip, f"unexpected start tooltip: {tip}"

    # Repopulate -> Start re-enables.
    page.evaluate(
        "() => { "
        "  document.getElementById('robotInput').value = '16'; "
        "  document.getElementById('concInput').value = '2'; "
        "  document.getElementById('ciSelect').dispatchEvent(new Event('change')); "
        "}"
    )
    page.wait_for_function(
        "() => document.getElementById('startBtn').disabled === false",
        timeout=2000,
    )
    assert page.locator("#startBtn").is_disabled() is False


@_obsolete_post_restructure
def test_start_inserts_submitted_placeholder_in_run_meta(console_page, clean_runs):
    """After clicking Start, runMeta must show the localized
    'submitted, waiting for analyzer to spawn...' placeholder before any
    progress event arrives. Without this the user has no signal at all."""
    page = console_page
    _wait_for_pure_loaded(page)
    # Simulate Auto Tune filling robot/conc so Start is enabled.
    page.evaluate(
        "() => { "
        "  document.getElementById('robotInput').value = '8'; "
        "  document.getElementById('concInput').value = '1'; "
        "  document.getElementById('ciSelect').dispatchEvent(new Event('change')); "
        "}"
    )
    page.wait_for_function(
        "() => document.getElementById('startBtn').disabled === false",
        timeout=2000,
    )
    # We don't care if the POST succeeds against the real test API; we only
    # care that the placeholder lands in the DOM synchronously after click.
    page.click("#startBtn")
    page.wait_for_function(
        "() => /提交|submitted/.test(document.getElementById('runMeta').textContent)",
        timeout=2000,
    )


@_obsolete_post_restructure
def test_autotune_click_lights_up_progress_panel(console_page, clean_runs):
    """Clicking Auto Tune should immediately replace the autotuneMeta
    body with at least the 'starting...' line written by startAutotunePolling."""
    page = console_page
    _wait_for_pure_loaded(page)
    page.click("#autotuneBtn")
    # Either "压测启动中..." (zh) or "autotune starting..." (en) depending on
    # localStorage state; matching either keeps this test locale-independent.
    page.wait_for_function(
        "() => /启动中|starting/.test(document.getElementById('autotuneMeta').textContent)",
        timeout=3000,
    )


@_obsolete_post_restructure
def test_dashboard_shell_renders_sidebar_with_run_actions(console_page):
    """Layout-refactor smoke: the .dashboard shell exists, .dash-sidebar
    holds the migrated run-config / model-config / run-actions panels,
    and the four primary control buttons live inside the sidebar (not
    in the main grid)."""
    page = console_page
    _wait_for_pure_loaded(page)

    assert page.locator(".dashboard").count() == 1
    assert page.locator(".dash-sidebar").count() == 1
    assert page.locator(".dash-main").count() == 1

    # Migrated panels live under .dash-sidebar (not under .dash-main).
    assert page.locator(".dash-sidebar .panel.run-config").count() == 1
    assert page.locator(".dash-sidebar .panel.model-config").count() == 1
    assert page.locator(".dash-sidebar .panel.run-actions").count() == 1

    # Run-control buttons relocated to the sidebar (commit 2 of the
    # dashboard refactor); their IDs are unchanged so other e2e tests
    # that target #startBtn / #autotuneBtn keep working.
    for btn_id in ("startBtn", "autotuneBtn", "stopBtn", "refreshBtn"):
        assert page.locator(f".dash-sidebar #{btn_id}").count() == 1, btn_id


@_obsolete_post_restructure
def test_live_status_strip_shows_idle_brief(console_page, clean_runs):
    """When no run is active the topbar live-status strip degrades to a
    "machine . mode . status" brief (renderLiveStatusStrip's idle path).
    The bootstrap fills the machine selector, so the brief should be
    non-empty within a couple of seconds of page load."""
    page = console_page
    _wait_for_pure_loaded(page)

    # Wait for bootstrap to fill machineSelect so the idle brief renders.
    page.wait_for_function(
        "() => { const m = document.getElementById('machineSelect');"
        "  return m && m.value && document.getElementById('liveStatusStrip').textContent.length > 0; }",
        timeout=5000,
    )
    text = (page.locator("#liveStatusStrip").text_content() or "").strip()
    # Brief is "machine . mode N" so at minimum the chosen machine name
    # (e.g. M14) appears in the strip.
    machine = page.evaluate("() => document.getElementById('machineSelect').value")
    assert machine and machine in text, f"expected '{machine}' in strip, got: {text!r}"


@_obsolete_post_restructure
def test_mid_panels_stacked(console_page):
    """User feedback after the first dashboard pass: assessment /
    interpretation / events should be stacked panels (not tabs).
    Verify all three render as independent .panel sections in the
    main area."""
    page = console_page
    _wait_for_pure_loaded(page)

    # All three panels exist and are visible (stacked layout, not tabbed).
    assert page.locator(".dash-main .panel.interpretation").count() == 1
    assert page.locator(".dash-main .panel.report").count() == 1
    assert page.locator(".dash-main .panel.logs").count() == 1
    # Headline IDs still wired:
    assert page.locator("#interpretBtn").is_visible()
    assert page.locator("#assessment").count() == 1
    assert page.locator("#eventsText").count() == 1


@_obsolete_post_restructure
def test_drilldown_panels_stacked(console_page):
    """Drilldown panels (paylines / payout-groups / symbols) are
    independent stacked panels too -- tab switching was more friction
    than scroll for these tables per user feedback."""
    page = console_page
    _wait_for_pure_loaded(page)

    assert page.locator(".dash-main .panel.paylines").count() == 1
    assert page.locator(".dash-main .panel.payout-groups").count() == 1
    assert page.locator(".dash-main .panel.symbols").count() == 1
    # Drilldown table IDs preserved.
    assert page.locator("#paylineTable").count() == 1
    assert page.locator("#payoutGroupTable").count() == 1
    assert page.locator("#symbolOverallTable").count() == 1
    assert page.locator("#symbolByColMatrix").count() == 1


@_obsolete_post_restructure
def test_sidebar_run_actions_first(console_page):
    """Run-control panel sits at the top of the sidebar so the
    Start/Auto buttons are immediately visible on page load."""
    page = console_page
    _wait_for_pure_loaded(page)

    # First .panel inside .dash-sidebar must be the run-actions block.
    first_panel_classes = page.evaluate(
        "() => document.querySelector('.dash-sidebar > .panel').className"
    )
    assert "run-actions" in first_panel_classes, (
        f"sidebar's first panel should be run-actions; got: {first_panel_classes!r}"
    )


@_obsolete_post_restructure
def test_start_button_disabled_when_run_active(live_server, page, clean_runs, clean_cache):
    # Seed AFTER the server has booted: startup recovery already ran and won't
    # touch this row. The frontend's polling (~4.5s) will then notice it.
    insert_run_row(
        live_server.db_path,
        run_id="e2e_active_run",
        status="running",
        process_pid=11111,
    )
    try:
        page.goto(f"{live_server.base_url}/console/", wait_until="domcontentloaded")
        page.wait_for_selector("#langSelect")
        # Wait up to ~10s for the polling cycle to pick up the active run.
        page.wait_for_function(
            "() => document.getElementById('startBtn').disabled === true",
            timeout=10000,
        )
        assert page.locator("#startBtn").is_disabled()
        assert page.locator("#autotuneBtn").is_disabled()
    finally:
        # Clean up so other tests in this session start from a fresh runs table.
        conn = sqlite3.connect(str(live_server.db_path))
        try:
            conn.execute("DELETE FROM runs WHERE run_id = ?", ("e2e_active_run",))
            conn.commit()
        finally:
            conn.close()
