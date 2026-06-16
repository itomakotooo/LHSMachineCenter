"""Top-level conftest: ensure repo root is on sys.path so tests can import
``src.web_console.backend.app`` without installing the package.
"""
from __future__ import annotations

import os
import pathlib
import shutil
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


# ─────────────────────────────────────────────────────────────────────────
# Real-rawdata destruction guard (test isolation)
# ─────────────────────────────────────────────────────────────────────────
# 2026-06-16: M43/mode_7's cached chunks were silently erased during a test
# run — a destructive op (unlink / rmtree) fired against the REAL repo
# rawdata/ tree instead of a tmp dir, and we lost the data with no signal
# (sidecar quietly rebuilt empty). This guard makes that class of bug
# IMPOSSIBLE to do silently: it wraps the deletion primitives so any attempt
# to remove a `chunk_*.json` data file under the real rawdata/ tree — or to
# rmtree any directory inside it — raises immediately, pinpointing the
# offending test + call site, rather than eating cached data.
#
# Tests that exercise the real delete endpoints (cache cleanup, delete_rawdata,
# version purge) MUST point their rawdata_root at a tmp dir (tmp_rawdata /
# tmp_path) — those resolve OUTSIDE repo rawdata/ and are unaffected. Sidecar
# (_chunks.json) and *.tmp upkeep is also allowed (only chunk_*.json data files
# are protected). See memory/feedback_enumerate_safety_paths.md.

_REAL_RAWDATA = (_ROOT / "rawdata").resolve()

_GUARD_MSG = (
    "RAWDATA-GUARD BLOCKED {op}: a test tried to delete {what}.\n"
    "  This would destroy REAL cached rawdata. Tests must operate on a tmp "
    "rawdata root (tmp_rawdata / tmp_path fixture), never the repo's rawdata/.\n"
    "  If you genuinely meant a tmp path, check that rawdata_root / RAWDATA_ROOT "
    "is monkeypatched to the tmp dir for this code path."
)


def _resolve(target) -> Path | None:
    try:
        return Path(os.fspath(target)).resolve()
    except (TypeError, ValueError, OSError):
        return None


def _under_real_rawdata(p: Path | None) -> bool:
    return p is not None and (p == _REAL_RAWDATA or _REAL_RAWDATA in p.parents)


def _protected_chunk_file(target) -> str | None:
    """Reason string if `target` is a real rawdata chunk DATA file (chunk_*.json
    under rawdata/), else None. Sidecars / *.tmp / non-rawdata paths → None."""
    p = _resolve(target)
    if not _under_real_rawdata(p):
        return None
    name = p.name
    if name.startswith("chunk_") and name.endswith(".json"):
        return f"real rawdata chunk file {p}"
    return None


@pytest.fixture(scope="session", autouse=True)
def _protect_real_rawdata():
    """Wrap Path.unlink / os.unlink / os.remove / shutil.rmtree so no test can
    silently delete real rawdata chunk data. Restores the originals on teardown.

    INJECT-BUG (proof the guard is live, per feedback_enumerate_safety_paths):
    comment out the four assignments below → tests/test_rawdata_isolation_guard.py
    goes RED (the delete is no longer blocked). Restore → GREEN.
    """
    orig_path_unlink = pathlib.Path.unlink
    orig_os_unlink = os.unlink
    orig_os_remove = os.remove
    orig_rmtree = shutil.rmtree

    def guard_path_unlink(self, *a, **k):
        reason = _protected_chunk_file(self)
        if reason:
            raise RuntimeError(_GUARD_MSG.format(op="Path.unlink", what=reason))
        return orig_path_unlink(self, *a, **k)

    def guard_os_unlink(path, *a, **k):
        reason = _protected_chunk_file(path)
        if reason:
            raise RuntimeError(_GUARD_MSG.format(op="os.unlink", what=reason))
        return orig_os_unlink(path, *a, **k)

    def guard_os_remove(path, *a, **k):
        reason = _protected_chunk_file(path)
        if reason:
            raise RuntimeError(_GUARD_MSG.format(op="os.remove", what=reason))
        return orig_os_remove(path, *a, **k)

    def guard_rmtree(path, *a, **k):
        p = _resolve(path)
        if _under_real_rawdata(p):
            raise RuntimeError(
                _GUARD_MSG.format(op="shutil.rmtree", what=f"real rawdata dir {p}")
            )
        return orig_rmtree(path, *a, **k)

    pathlib.Path.unlink = guard_path_unlink
    os.unlink = guard_os_unlink
    os.remove = guard_os_remove
    shutil.rmtree = guard_rmtree
    try:
        yield
    finally:
        pathlib.Path.unlink = orig_path_unlink
        os.unlink = orig_os_unlink
        os.remove = orig_os_remove
        shutil.rmtree = orig_rmtree
