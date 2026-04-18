"""End-to-end test entrypoint.

Reads SLOT_E2E_STATE_DIR / SLOT_E2E_REPORTS / SLOT_E2E_CACHE /
SLOT_E2E_RAWDATA from the environment and constructs an isolated
FastAPI app via create_app. This keeps the env-var coupling out of
production app.py and main.py while still letting Playwright fixtures
spawn ``python -m uvicorn`` against tmp paths.

Missing or empty env vars raise RuntimeError with a clear message rather
than KeyError, so a misconfigured fixture surfaces as an immediate test
failure instead of a cryptic 500.
"""
from __future__ import annotations

import os
from pathlib import Path

from src.web_console.backend.app import create_app


_REQUIRED = ("SLOT_E2E_STATE_DIR", "SLOT_E2E_REPORTS", "SLOT_E2E_CACHE",
             "SLOT_E2E_RAWDATA")


def _required_env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(
            f"e2e_launch: missing required env var {key} "
            f"(needs all of: {', '.join(_REQUIRED)})"
        )
    return val


app = create_app(
    state_dir=Path(_required_env("SLOT_E2E_STATE_DIR")),
    reports_root=Path(_required_env("SLOT_E2E_REPORTS")),
    cache_root=Path(_required_env("SLOT_E2E_CACHE")),
    rawdata_root=Path(_required_env("SLOT_E2E_RAWDATA")),
)
