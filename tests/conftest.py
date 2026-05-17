"""Top-level conftest: ensure repo root is on sys.path so tests can import
``src.web_console.backend.app`` without installing the package.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def pytest_configure(config: pytest.Config) -> None:
    """Register custom marks so pytest does not warn about unknown marks."""
    config.addinivalue_line(
        "markers",
        "integration: slow end-to-end tests that spawn real subprocesses "
        "or make real HTTP calls. Gate with: pytest -m 'not integration'.",
    )
