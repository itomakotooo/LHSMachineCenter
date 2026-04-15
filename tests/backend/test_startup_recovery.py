"""Tests for RunManager._recover_orphan_running_runs and the recovery snapshot
exposed on /api/health and /api/system-state.

The general pattern: seed a stale ``running`` row directly via SQL (bypassing
the production code path) BEFORE the app is built, then build the app and
assert the recovery happened.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.backend._seed import insert_run_row


def test_stale_running_marked_failed(app_factory):
    insert_run_row(
        app_factory.db_path,
        run_id="stale001",
        status="running",
        process_pid=42424,
    )
    app = app_factory()
    with TestClient(app) as c:
        resp = c.get("/api/runs/stale001")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed"
        assert body["error_message"].startswith("run interrupted by console restart")
        assert body["finished_at"] is not None


def test_recovery_snapshot_in_health(app_factory):
    insert_run_row(
        app_factory.db_path,
        run_id="stale001",
        status="running",
        process_pid=42424,
    )
    app = app_factory()
    with TestClient(app) as c:
        body = c.get("/api/health").json()
        assert body["startup_recovery_count"] == 1
        # _terminate_pid_if_running is monkeypatched to True in app_factory,
        # so the pid is recorded as terminated.
        assert body["startup_terminated_pid_count"] == 1


def test_recovery_snapshot_in_system_state(app_factory):
    insert_run_row(
        app_factory.db_path,
        run_id="stale001",
        status="running",
        process_pid=42424,
    )
    app = app_factory()
    with TestClient(app) as c:
        body = c.get("/api/system-state").json()
        sr = body["startup_recovery"]
        assert sr["recovered_count"] == 1
        assert sr["run_ids"] == ["stale001"]
        assert sr["terminated_pids"] == [42424]
        assert sr["failed_to_terminate_pids"] == []


def test_recovery_handles_pid_termination_failure(
    app_factory, monkeypatch: pytest.MonkeyPatch
):
    # Override the always-True monkeypatch from app_factory with one that
    # always reports failure, simulating a pid we couldn't kill.
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: False,
    )
    insert_run_row(
        app_factory.db_path,
        run_id="stale002",
        status="running",
        process_pid=99999,
    )
    app = app_factory()
    with TestClient(app) as c:
        sr = c.get("/api/system-state").json()["startup_recovery"]
        assert sr["recovered_count"] == 1
        assert sr["run_ids"] == ["stale002"]
        assert sr["terminated_pids"] == []
        assert sr["failed_to_terminate_pids"] == [99999]
        body = c.get("/api/runs/stale002").json()
        assert body["status"] == "failed"
        assert "stale worker process may still exist" in body["error_message"]
