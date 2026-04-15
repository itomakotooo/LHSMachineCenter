"""Top-level conftest: ensure repo root is on sys.path so tests can import
``src.web_console.backend.app`` without installing the package.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
