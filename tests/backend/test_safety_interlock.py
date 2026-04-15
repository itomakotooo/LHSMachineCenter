"""Tests for the operation mutex + active-run blocking on the three write
endpoints (POST /api/runs, POST /api/autotune, POST /api/cache/cleanup).

These freeze the safety contract in code so future endpoint refactors can't
silently drop a 409 path.
"""
from __future__ import annotations


def _run_payload(**overrides):
    base = {
        "machine": "M14",
        "mode": 1,
        "target_halfwidth_pp": 0.5,
        "chunk_spin_times": 5000,
        "chunk_robot_count": 20,
        "batch_concurrency": 2,
        "max_chunks": 120,
        "timeout": 300.0,
        "bankruptcy_session_spins": 500,
        "bankruptcy_bankroll_multipliers": "100,200,500",
        "model_id": "gpt-5.4-mini",
    }
    base.update(overrides)
    return base


def _autotune_payload():
    return {
        "machine": "M14",
        "mode": 1,
        "spin_times": 120,
        "robot_candidates": [8, 12],
        "concurrency_candidates": [1, 2],
        "rounds": 1,
        "timeout": 5.0,
        "bet": 1000,
    }


# ---------------------------- active-run blocking


def test_runs_blocked_by_active_run(client):
    c, _app = client
    first = c.post("/api/runs", json=_run_payload())
    assert first.status_code == 200
    second = c.post("/api/runs", json=_run_payload())
    assert second.status_code == 409
    assert second.json()["detail"].startswith("run already active: ")


def test_autotune_blocked_by_active_run(client):
    c, _app = client
    started = c.post("/api/runs", json=_run_payload())
    assert started.status_code == 200
    resp = c.post("/api/autotune", json=_autotune_payload())
    assert resp.status_code == 409
    assert resp.json()["detail"] == "auto tune is blocked while runs are active"


def test_cache_cleanup_soft_blocked_by_active_run(client):
    """Cache cleanup is the special case: when a run is active it returns 200
    with a {message} payload, NOT 409 (so the UI doesn't surface a scary
    error for the very common 'try to clean while running' click)."""
    c, _app = client
    started = c.post("/api/runs", json=_run_payload())
    assert started.status_code == 200
    resp = c.post("/api/cache/cleanup", json={"max_delete_bytes": 0})
    assert resp.status_code == 200
    assert resp.json() == {
        "deleted_files": 0,
        "deleted_bytes": 0,
        "message": "cleanup blocked while runs are active",
    }


# ---------------------------- mutex blocking


def test_autotune_blocks_runs_via_mutex(client):
    c, app = client
    assert app.state.ops.acquire("auto_tune")
    try:
        resp = c.post("/api/runs", json=_run_payload())
        assert resp.status_code == 409
        assert resp.json()["detail"] == "system busy: auto_tune"
    finally:
        app.state.ops.release()


def test_runs_blocks_autotune_via_mutex(client):
    c, app = client
    assert app.state.ops.acquire("start_run")
    try:
        resp = c.post("/api/autotune", json=_autotune_payload())
        # When a run is "active" via the mutex but no actual running row exists
        # the autotune endpoint reaches the mutex check.
        assert resp.status_code == 409
        assert resp.json()["detail"] == "system busy: start_run"
    finally:
        app.state.ops.release()


# ---------------------------- mutex release


def test_mutex_released_after_success(client, app_factory, wait_until_fixture):
    c, app = client
    started = c.post("/api/runs", json=_run_payload())
    assert started.status_code == 200
    # The /api/runs handler released the mutex synchronously after start_run
    # returned, so it should already be False even before _watch_run finishes.
    assert app.state.ops.snapshot()["busy"] is False
    # Letting the watcher finish should not change that.
    app_factory.stub_popen.processes[0].finish(0)
    wait_until_fixture(
        lambda: not app.state.ops.snapshot()["busy"],
        timeout=5.0,
        msg="ops mutex unexpectedly busy after run completion",
    )
