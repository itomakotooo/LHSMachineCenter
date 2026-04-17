"""Tests for _terminate_process_tree (Windows taskkill + POSIX psutil).

Cancel paths in cancel_batch / /api/runs/{id}/cancel used to call bare
`Popen.terminate()` which kills only the root pid. The analyzer spawns
its own ThreadPoolExecutor workers + urllib threads; bare terminate
leaves those as orphans on POSIX. This helper walks the process tree
and terminates everything, with a psutil→taskkill dispatch.

Covers:
- Windows path: delegates to `_terminate_pid_if_running` (taskkill /T /F)
- POSIX with psutil available: walks children + waits + kills stragglers
- POSIX without psutil: falls back to single-pid SIGTERM with a warning
- Invalid pid (<=0 or NoSuchProcess) returns False cleanly
- Accepts either Popen-like object (reads .pid) or int pid
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

import src.web_console.backend.app as app_mod


# ── Windows path ─────────────────────────────────────────────────────


class TestTerminateProcessTreeWindows:
    def test_delegates_to_taskkill(self, monkeypatch):
        monkeypatch.setattr(app_mod.os, "name", "nt")
        captured = {}

        def fake_terminate(pid: int) -> bool:
            captured["pid"] = pid
            return True

        monkeypatch.setattr(app_mod, "_terminate_pid_if_running", fake_terminate)
        assert app_mod._terminate_process_tree(12345) is True
        assert captured["pid"] == 12345

    def test_accepts_process_like_object(self, monkeypatch):
        monkeypatch.setattr(app_mod.os, "name", "nt")
        monkeypatch.setattr(app_mod, "_terminate_pid_if_running", lambda pid: True)
        proc = MagicMock()
        proc.pid = 777
        assert app_mod._terminate_process_tree(proc) is True


# ── POSIX with psutil ────────────────────────────────────────────────


def _install_fake_psutil(monkeypatch, fake_module):
    """Shim sys.modules so `import psutil` inside _terminate_process_tree
    picks up our mock. Required because psutil isn't a hard dep and the
    module uses a local import to soft-depend on it."""
    monkeypatch.setitem(sys.modules, "psutil", fake_module)


class TestTerminateProcessTreePosixPsutil:
    def test_walks_tree_terminates_each_waits_kills_stragglers(
        self, monkeypatch
    ):
        monkeypatch.setattr(app_mod.os, "name", "posix")
        # Build a fake psutil module with just enough surface.
        fake_psutil = types.ModuleType("psutil")

        class FakeNoSuchProcess(Exception):
            pass
        fake_psutil.NoSuchProcess = FakeNoSuchProcess

        events: list[str] = []

        class FakeProc:
            def __init__(self, pid):
                self.pid = pid
                self.terminate_called = False
                self.kill_called = False

            def children(self, recursive):
                assert recursive is True
                return [FakeProc(101), FakeProc(102)]

            def terminate(self):
                events.append(f"term:{self.pid}")
                self.terminate_called = True

            def kill(self):
                events.append(f"kill:{self.pid}")
                self.kill_called = True

        def fake_process(pid):
            return FakeProc(pid)

        # wait_procs returns (finished, alive). Put pid 102 into alive
        # so we can verify the straggler-kill path fires.
        def fake_wait_procs(procs, timeout):
            alive = [p for p in procs if p.pid == 102]
            finished = [p for p in procs if p.pid != 102]
            return finished, alive

        fake_psutil.Process = fake_process
        fake_psutil.wait_procs = fake_wait_procs
        _install_fake_psutil(monkeypatch, fake_psutil)

        assert app_mod._terminate_process_tree(100) is True
        # Order: children terminated first (101, 102), then root (100),
        # then kill() on stragglers (102).
        assert "term:101" in events
        assert "term:102" in events
        assert "term:100" in events
        assert "kill:102" in events
        assert "kill:100" not in events  # root was not alive → no kill

    def test_nosuchprocess_on_root_returns_false(self, monkeypatch):
        monkeypatch.setattr(app_mod.os, "name", "posix")
        fake_psutil = types.ModuleType("psutil")

        class FakeNoSuchProcess(Exception):
            pass
        fake_psutil.NoSuchProcess = FakeNoSuchProcess

        def raising_process(pid):
            raise FakeNoSuchProcess(f"no {pid}")

        fake_psutil.Process = raising_process
        fake_psutil.wait_procs = lambda procs, timeout: ([], [])
        _install_fake_psutil(monkeypatch, fake_psutil)

        assert app_mod._terminate_process_tree(9999) is False

    def test_child_nosuchprocess_swallowed(self, monkeypatch):
        # A child vanishing between .children() and .terminate() is
        # expected (race) — don't let it bubble.
        monkeypatch.setattr(app_mod.os, "name", "posix")
        fake_psutil = types.ModuleType("psutil")

        class FakeNoSuchProcess(Exception):
            pass
        fake_psutil.NoSuchProcess = FakeNoSuchProcess

        class FakeChild:
            pid = 101
            def terminate(self):
                raise FakeNoSuchProcess("gone")
            def kill(self):
                raise FakeNoSuchProcess("gone")

        class FakeRoot:
            pid = 100
            def children(self, recursive): return [FakeChild()]
            def terminate(self): pass
            def kill(self): pass

        fake_psutil.Process = lambda pid: FakeRoot()
        fake_psutil.wait_procs = lambda procs, timeout: (procs, [])
        _install_fake_psutil(monkeypatch, fake_psutil)

        assert app_mod._terminate_process_tree(100) is True


# ── POSIX without psutil ─────────────────────────────────────────────


class TestTerminateProcessTreePosixFallback:
    def test_no_psutil_falls_back_to_single_pid(self, monkeypatch, capsys):
        monkeypatch.setattr(app_mod.os, "name", "posix")
        # Ensure `import psutil` raises ImportError inside the helper.
        # Use a sentinel that isn't a module so the import fails.
        monkeypatch.setitem(sys.modules, "psutil", None)
        captured = {}

        def fake_terminate(pid: int) -> bool:
            captured["pid"] = pid
            return True

        monkeypatch.setattr(app_mod, "_terminate_pid_if_running", fake_terminate)
        assert app_mod._terminate_process_tree(555) is True
        assert captured["pid"] == 555
        # Warning was printed.
        out = capsys.readouterr().out
        assert "psutil not installed" in out


# ── Input validation ─────────────────────────────────────────────────


class TestTerminateProcessTreeInput:
    def test_zero_pid_returns_false(self, monkeypatch):
        # Independent of platform — pid<=0 is rejected upfront.
        assert app_mod._terminate_process_tree(0) is False

    def test_negative_pid_returns_false(self, monkeypatch):
        assert app_mod._terminate_process_tree(-1) is False

    def test_popen_with_zero_pid_returns_false(self, monkeypatch):
        proc = MagicMock()
        proc.pid = 0
        assert app_mod._terminate_process_tree(proc) is False
