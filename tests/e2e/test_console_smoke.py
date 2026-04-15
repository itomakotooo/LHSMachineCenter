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


def test_cache_cleanup_low_risk_flow(console_page, clean_cache, clean_runs):
    page = console_page
    _wait_for_pure_loaded(page)

    # Cache panel lives on the "manage" tab; debug tab is default.
    page.click("#tabBtnManage")
    page.wait_for_selector("#cacheRefreshBtn", state="visible")

    # Write 1 KB so it sits below the e2e medium threshold (2048).
    cache_dir = clean_cache
    (cache_dir / "low.bin").write_bytes(b"x" * 1024)

    # Refresh cache panel and wait for the meta to mention 'low'.
    page.click("#cacheRefreshBtn")
    page.wait_for_function(
        "() => /low|低/.test(document.getElementById('cacheRiskMeta').textContent)",
        timeout=5000,
    )

    dialogs: list[dict] = []

    def _on_dialog(dialog):
        dialogs.append({"type": dialog.type, "message": dialog.message})
        dialog.accept()

    page.on("dialog", _on_dialog)
    page.click("#cacheCleanupBtn")

    # File deletion happens inside an async POST; poll until gone.
    page.wait_for_function(
        "async () => { const r = await fetch('/api/cache/status').then(r => r.json()); "
        "return r.file_count === 0; }",
        timeout=5000,
    )

    # Low risk should produce exactly one confirm dialog (no DELETE token prompt).
    assert len(dialogs) == 1
    assert dialogs[0]["type"] == "confirm"
    assert not (cache_dir / "low.bin").exists()


def test_cache_cleanup_high_risk_requires_token(console_page, clean_cache, clean_runs):
    page = console_page
    _wait_for_pure_loaded(page)

    page.click("#tabBtnManage")
    page.wait_for_selector("#cacheRefreshBtn", state="visible")

    cache_dir = clean_cache
    # 10 KB > the e2e high threshold (8192).
    (cache_dir / "big.bin").write_bytes(b"y" * 10_000)

    page.click("#cacheRefreshBtn")
    page.wait_for_function(
        "() => /high|高/.test(document.getElementById('cacheRiskMeta').textContent)",
        timeout=5000,
    )

    # First attempt: enter the wrong DELETE token -> nothing should be deleted.
    dialogs_wrong: list[dict] = []

    def _wrong(dialog):
        dialogs_wrong.append({"type": dialog.type})
        if dialog.type == "confirm":
            dialog.accept()
        elif dialog.type == "prompt":
            dialog.accept("WRONG")
        else:
            dialog.accept()

    page.on("dialog", _wrong)
    page.click("#cacheCleanupBtn")
    # Give the JS a beat to finish handling dialogs + alert; we don't poll a
    # network condition because nothing should change.
    page.wait_for_timeout(500)
    page.remove_listener("dialog", _wrong)

    assert any(d["type"] == "confirm" for d in dialogs_wrong)
    assert any(d["type"] == "prompt" for d in dialogs_wrong)
    assert (cache_dir / "big.bin").exists(), "wrong token must NOT delete the file"

    # Second attempt: correct DELETE token -> file removed.
    dialogs_right: list[dict] = []

    def _right(dialog):
        dialogs_right.append({"type": dialog.type})
        if dialog.type == "confirm":
            dialog.accept()
        elif dialog.type == "prompt":
            dialog.accept("DELETE")
        else:
            dialog.accept()

    page.on("dialog", _right)
    page.click("#cacheCleanupBtn")
    page.wait_for_function(
        "async () => { const r = await fetch('/api/cache/status').then(r => r.json()); "
        "return r.file_count === 0; }",
        timeout=5000,
    )
    page.remove_listener("dialog", _right)

    assert any(d["type"] == "confirm" for d in dialogs_right)
    assert any(d["type"] == "prompt" for d in dialogs_right)
    assert not (cache_dir / "big.bin").exists()


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
