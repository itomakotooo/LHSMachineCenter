"""Playwright e2e harness.

Spawns ``python -m uvicorn src.web_console.backend.e2e_launch:app`` on a
free port pointed at tmp state/reports/cache directories. Risk thresholds
are lowered to KB scale via env vars so the cleanup-tier tests can trigger
the medium / high tier with tiny files instead of multi-GB writes.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest


_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class LiveServer:
    base_url: str
    state_dir: Path
    reports_dir: Path
    cache_dir: Path
    rawdata_dir: Path
    db_path: Path
    # I5 fix: isolated configs upload dir so /api/configs/upload never
    # touches the real configs/uploaded_configs/ in the worktree.
    configs_upload_dir: Path | None = None


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.mktemp("e2e_runtime")
    state_dir = base / "state" / "console"
    state_dir.mkdir(parents=True)
    (state_dir / "progress").mkdir()
    reports_dir = base / "reports"
    reports_dir.mkdir()
    cache_dir = base / "cache" / "chunks"
    cache_dir.mkdir(parents=True)
    rawdata_dir = base / "rawdata"
    rawdata_dir.mkdir()
    db_path = state_dir / "console.db"
    # I5 fix: isolated configs upload dir.
    configs_upload_dir = base / "configs_upload"
    configs_upload_dir.mkdir(parents=True)

    port = _free_port()
    env = {
        **os.environ,
        "SLOT_E2E_STATE_DIR": str(state_dir),
        "SLOT_E2E_REPORTS": str(reports_dir),
        "SLOT_E2E_CACHE": str(cache_dir),
        "SLOT_E2E_RAWDATA": str(rawdata_dir),
        # I5 fix: pass isolated configs upload dir to e2e_launch.py.
        "SLOT_E2E_CONFIGS_UPLOAD_DIR": str(configs_upload_dir),
        # Shrink risk thresholds so a 1KB file triggers low and a 10KB file
        # triggers high. Defaults (512 MB / 2 GB) are unrealistic for e2e.
        "SLOT_RISK_MEDIUM_BYTES": "2048",
        "SLOT_RISK_HIGH_BYTES": "8192",
    }

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.web_console.backend.e2e_launch:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base_url = f"http://127.0.0.1:{port}"

    deadline = time.time() + 15
    last_err: str = ""
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/health", timeout=1.0)
            if r.status_code == 200:
                break
        except httpx.RequestError as exc:
            last_err = exc.__class__.__name__
        if proc.poll() is not None:
            stderr = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace")
            raise RuntimeError(
                f"uvicorn died during boot (rc={proc.returncode}). stderr:\n{stderr}"
            )
        time.sleep(0.15)
    else:
        proc.kill()
        raise RuntimeError(f"uvicorn did not become ready (last error: {last_err})")

    server = LiveServer(
        base_url=base_url,
        state_dir=state_dir,
        reports_dir=reports_dir,
        cache_dir=cache_dir,
        rawdata_dir=rawdata_dir,
        db_path=db_path,
        configs_upload_dir=configs_upload_dir,
    )
    try:
        yield server
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def console_page(live_server, page):
    """Goto /console/ and wait until the language selector is hydrated."""
    page.goto(f"{live_server.base_url}/console/", wait_until="domcontentloaded")
    page.wait_for_selector("#langSelect")
    return page


@pytest.fixture
def clean_cache(live_server):
    """Delete any leftover files from a prior test in this session.

    Cleans both the legacy cache/chunks root (still exposed for back-
    compat) and the rawdata root (the authoritative chunk location
    that /api/cache/cleanup now operates on).
    """
    import shutil

    def _wipe(d: Path) -> None:
        for entry in list(d.iterdir()):
            try:
                if entry.is_file():
                    entry.unlink()
                else:
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                pass

    _wipe(live_server.cache_dir)
    _wipe(live_server.rawdata_dir)
    yield live_server.cache_dir
    _wipe(live_server.cache_dir)
    _wipe(live_server.rawdata_dir)


@pytest.fixture
def clean_runs(live_server):
    """Drop any runs rows that piled up in earlier session tests so that
    button-disabled assertions start from a clean slate.
    """
    import sqlite3
    if live_server.db_path.exists():
        conn = sqlite3.connect(str(live_server.db_path))
        try:
            conn.execute("DELETE FROM runs")
            conn.commit()
        finally:
            conn.close()
    yield
