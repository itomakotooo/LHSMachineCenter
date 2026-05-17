"""Backend production entrypoint.

Importing ``src.web_console.backend.app`` itself has zero side effects (no
disk writes, no SQLite, no FastAPI instance). This module is the one place
where the default app is constructed, so uvicorn can target it via
``src.web_console.backend.main:app``.

Tests should import ``create_app`` from ``app.py`` directly and pass tmp
paths; they should NOT import this module.
"""
from __future__ import annotations

from src.web_console.backend.app import create_app

app = create_app()


if __name__ == "__main__":
    import os
    import uvicorn

    _host = os.environ.get("SLOT_BIND_HOST", "0.0.0.0")
    _port = int(os.environ.get("SLOT_BIND_PORT", "8877"))

    uvicorn.run(
        "src.web_console.backend.main:app",
        host=_host,
        port=_port,
        reload=False,
    )
