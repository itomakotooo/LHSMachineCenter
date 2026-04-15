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
    import uvicorn

    uvicorn.run(
        "src.web_console.backend.main:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
    )
