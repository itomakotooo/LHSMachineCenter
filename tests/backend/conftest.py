"""Backend test fixtures.

Each test gets its own tmp state/reports/cache dirs and a fresh FastAPI app
built via ``create_app(...)``. Subprocess calls are stubbed via the
``popen_factory`` injection on RunManager, and the pid termination helper is
monkeypatched so startup recovery tests don't actually shoot down processes.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from src.web_console.backend.app import create_app

_CONF_REPO_ROOT = Path(__file__).resolve().parents[2]


# Disable the post-generate-report auto-inference subprocess hook for
# ALL backend tests — it spawns infer_paytable + verify_machine_labels
# which adds ~5-10s per item and blows past the 10s batch-gen timeout
# in test_generate_report. Production usage leaves this env unset.
@pytest.fixture(autouse=True)
def _disable_auto_inference_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")


@pytest.fixture
def isolated_rawdata_factory(tmp_path: Path) -> Callable[..., Path]:
    """Factory → an ISOLATED tmp rawdata root holding ONLY the requested
    machine's modes, hardlinked from the real repo ``rawdata/`` (copy fallback).

    Why this exists (2026-06-16 M43/mode_7 loss): generating a report via the
    app calls ``_auto_cleanup_for_space``, which — when the box is low on disk —
    evicts the OLDEST ``deletable``/``historical`` chunks across the ENTIRE
    ``rawdata_root``. A fixture that pointed ``rawdata_root`` at the real repo
    ``rawdata/`` therefore let a single-machine generate silently delete OTHER
    machines' cached chunks fleet-wide (every chunk of a machine absent from the
    fixture's ``machines.json`` is ``historical`` → eviction candidate). Disk
    pressure is nondeterministic, which is why it went un-root-caused.

    Hardlinking just the one machine into a tmp root keeps ``generate`` reading
    real data while bounding cleanup to the tmp tree (which holds only the
    declared, ``kept`` machine → zero eviction candidates). Even if a hardlink
    were unlinked, the real chunk survives (shared inode, separate dentry).
    See ``tests/test_rawdata_isolation_guard.py`` for the belt-and-suspenders
    guard that hard-fails any test that still tries to delete real rawdata.
    """
    def _make(machine: str, modes: list[int], *, root_name: str = "rawdata") -> Path:
        dst_root = tmp_path / root_name
        real = _CONF_REPO_ROOT / "rawdata"
        dst_root.mkdir(parents=True, exist_ok=True)
        for mode in modes:
            src = real / machine / f"mode_{mode}"
            if not src.is_dir():
                continue
            dst = dst_root / machine / f"mode_{mode}"
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                if not f.is_file():
                    continue
                tgt = dst / f.name
                try:
                    os.link(f, tgt)
                except OSError:
                    shutil.copyfile(f, tgt)
        return dst_root
    return _make


# -------------------------------------------------------------------- paths


@pytest.fixture
def tmp_state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state" / "console"
    d.mkdir(parents=True)
    (d / "progress").mkdir()
    return d


@pytest.fixture
def tmp_reports(tmp_path: Path) -> Path:
    d = tmp_path / "reports"
    d.mkdir()
    return d


@pytest.fixture
def tmp_cache(tmp_path: Path) -> Path:
    d = tmp_path / "cache" / "chunks"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def tmp_rawdata(tmp_path: Path) -> Path:
    """Tmp rawdata root — isolates chunk-level tests from the real
    rawdata/ tree. Plumbed through app_factory so create_app sees
    it as RAWDATA_ROOT override."""
    d = tmp_path / "rawdata"
    d.mkdir()
    return d


@pytest.fixture
def fake_machines(tmp_path: Path) -> Path:
    p = tmp_path / "machines.json"
    p.write_text('{"machines":[{"machine":"M14","modes":[1]}]}', encoding="utf-8")
    return p


@pytest.fixture
def fake_analyzer(tmp_path: Path) -> Path:
    p = tmp_path / "fake_analyzer.py"
    p.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    return p


# -------------------------------------------------------------------- subprocess stub


class StubProcess:
    """Test stub for subprocess.Popen.

    ``communicate()`` blocks until ``finish()`` or ``terminate()`` is called,
    with a 10s safety timeout that surfaces a TimeoutError if a test forgets
    to release the stub. The ``stub_popen`` fixture's teardown also calls
    ``terminate()`` on any still-blocking stub so daemon ``_watch_run``
    threads can exit promptly between tests.
    """

    COMMUNICATE_TIMEOUT_S = 10.0

    def __init__(
        self,
        pid: int = 77777,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.pid = pid
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._communicated = False

    def communicate(self) -> tuple[str, str]:
        deadline = time.monotonic() + self.COMMUNICATE_TIMEOUT_S
        while not self._communicated:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "StubProcess.communicate() timeout -- test forgot to call finish()/terminate()"
                )
            time.sleep(0.01)
        return self._stdout, self._stderr

    def terminate(self) -> None:
        self._communicated = True

    def finish(self, code: int = 0) -> None:
        self.returncode = code
        self._communicated = True


@pytest.fixture
def stub_popen():
    processes: list[StubProcess] = []
    cmds: list[list[str]] = []

    def factory(cmd: list[str], cwd: Path) -> StubProcess:
        cmds.append(list(cmd))
        p = StubProcess()
        processes.append(p)
        return p

    factory.processes = processes  # type: ignore[attr-defined]
    factory.cmds = cmds  # type: ignore[attr-defined]
    yield factory
    # Teardown: release any still-blocking stub so the watcher thread can
    # finish quickly. Daemon=True means it won't hang pytest exit even if
    # we miss one, but cleaning up keeps test runs deterministic.
    for p in processes:
        if not p._communicated:
            p.terminate()


# -------------------------------------------------------------------- app factory


@pytest.fixture
def app_factory(
    tmp_state_dir: Path,
    tmp_reports: Path,
    tmp_cache: Path,
    tmp_rawdata: Path,
    fake_machines: Path,
    fake_analyzer: Path,
    stub_popen,
    monkeypatch: pytest.MonkeyPatch,
):
    """Return a builder that constructs an isolated FastAPI app on demand.

    The builder stores convenience handles on itself (cache_dir, db_path,
    stub_popen, state_dir, rawdata_dir) so tests can poke disk state
    directly without re-deriving the paths.
    """
    monkeypatch.setattr(
        "src.web_console.backend.app._default_popen_factory",
        stub_popen,
    )
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )

    def _make():
        return create_app(
            state_dir=tmp_state_dir,
            reports_root=tmp_reports,
            cache_root=tmp_cache,
            machines_config=fake_machines,
            analyzer_path=fake_analyzer,
            rawdata_root=tmp_rawdata,
        )

    _make.cache_dir = tmp_cache         # type: ignore[attr-defined]
    _make.rawdata_dir = tmp_rawdata     # type: ignore[attr-defined]
    _make.db_path = tmp_state_dir / "console.db"   # type: ignore[attr-defined]
    _make.state_dir = tmp_state_dir     # type: ignore[attr-defined]
    _make.reports_dir = tmp_reports     # type: ignore[attr-defined]
    _make.stub_popen = stub_popen       # type: ignore[attr-defined]
    return _make


@pytest.fixture
def client(app_factory):
    """Return (TestClient, app) for an isolated app instance."""
    app = app_factory()
    with TestClient(app) as c:
        yield c, app


# -------------------------------------------------------------------- async helpers


def wait_until(
    predicate: Callable[[], bool],
    timeout: float = 5.0,
    interval: float = 0.05,
    msg: str = "",
) -> None:
    """Poll ``predicate()`` until True, or fail the test after ``timeout``.

    Use this when you need to wait on a daemon thread (e.g. RunManager's
    _watch_run) to publish state. Relying on the stub's internal timeout
    isn't enough -- TimeoutError raised inside a daemon thread is logged
    but doesn't fail the test.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    pytest.fail(f"timeout after {timeout}s: {msg or 'predicate not met'}")


@pytest.fixture
def wait_until_fixture():
    return wait_until
