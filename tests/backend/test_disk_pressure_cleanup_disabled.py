"""Regression: the disk-monitor daemon must not leak in backend tests.

Root cause of the flaky full-suite runs (2026-06-16): create_app() starts a
``disk-monitor`` DAEMON thread that, every SLOT_DISK_MONITOR_INTERVAL_S seconds,
calls ``_auto_cleanup_for_space`` when free disk < SLOT_DISK_LOW_WATER_GB
(default 5 GB), EVICTING deletable chunks across the app's rawdata_root. The
threads are ``daemon=True`` and never joined, so EVERY create_app() in the suite
leaks one. On a dev box hovering near 5 GB free they fire nondeterministically;
a monitor leaked by an early test then:
  * evicts chunks a LATER test is mid-generate on -> FileNotFoundError /
    report-md5 drift, OR
  * lands a cleanup call inside an unrelated test's _auto_cleanup_for_space spy
    (e.g. test_rawdata_root_split_path) -> wrong-rawdata_root assertion failure.
This is the same _auto_cleanup_for_space family as the M43/mode_7 data loss.

Fix: ``_disk_monitor_loop`` returns immediately when its interval is <= 0
(guard in app.py), and tests/backend/conftest.py::_no_disk_monitor_thread sets
SLOT_DISK_MONITOR_INTERVAL_S=0 for ALL backend tests, so create_app spawns no
looping monitor. This does NOT disable the BATCH generate path's own inline
disk-pressure loop (BatchRunManager._run_one, gated on SLOT_DISK_LOW_WATER_GB),
which tests such as test_rawdata_root_split_path drive directly — those stay
green. Production leaves the interval unset (default 60 s) so the monitor runs.
"""
from __future__ import annotations

import os
import threading
import time

from fastapi.testclient import TestClient


class TestDiskMonitorDisabledInTests:
    def test_autouse_sets_monitor_interval_zero(self) -> None:
        """Contract: the backend autouse fixture disables the disk-monitor
        suite-wide. INJECT-BUG: delete the setenv in
        conftest._no_disk_monitor_thread -> this assertion goes RED.
        """
        assert os.environ.get("SLOT_DISK_MONITOR_INTERVAL_S") == "0", (
            "backend tests must run with SLOT_DISK_MONITOR_INTERVAL_S=0 so "
            "create_app spawns no leaked disk-monitor daemon thread"
        )

    def test_create_app_leaves_no_live_disk_monitor_at_interval_zero(
        self, app_factory
    ) -> None:
        """With SLOT_DISK_MONITOR_INTERVAL_S=0 (autouse), create_app must NOT
        leave a live, looping ``disk-monitor`` thread.

        INJECT-BUG: remove ``if interval <= 0: return`` from
        ``_disk_monitor_loop`` in app.py -> at interval=0 the loop busy-spins
        and a live 'disk-monitor' thread persists -> this test RED. Revert ->
        GREEN. (Proves the guard is what keeps the monitor from leaking.)
        """
        app = app_factory()
        with TestClient(app):
            # Give the (guarded) thread a beat to start and return.
            time.sleep(0.3)
            alive = [
                t for t in threading.enumerate()
                if t.name == "disk-monitor" and t.is_alive()
            ]
        assert not alive, (
            f"create_app left {len(alive)} live disk-monitor thread(s) at "
            "interval=0 — the guard must make _disk_monitor_loop exit "
            "immediately so no cleanup-firing daemon leaks into later tests"
        )
