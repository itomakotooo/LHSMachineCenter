"""Tests for the operation mutex + active-run blocking on the three write
endpoints (POST /api/runs, POST /api/autotune, POST /api/cache/cleanup).

These freeze the safety contract in code so future endpoint refactors can't
silently drop a 409 path.

Phase 2 migration note (2026-05-17):
  The OperationCoordinator (app.state.ops) was deleted in P2 and replaced
  by CellLockRegistry (app.state.registry). The three mutex-blocking tests
  that previously used app.state.ops.acquire / release have been updated
  to use app.state.registry directly:

  - test_autotune_blocks_runs_via_mutex: now injects GENERATING on M14|1
    via registry to verify POST /api/runs returns 409 "cell busy".
  - test_runs_blocks_autotune_via_mutex: now injects global "autotune" op
    via registry to verify POST /api/autotune returns 409.
  - test_mutex_released_after_success: now checks registry.snapshot() has
    no active cells/global ops after start_run completes.
"""
from __future__ import annotations

from src.web_console.backend.cell_lock_registry import CellLockRegistry, CellOperation


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
    """Phase 2: registry.try_acquire_cell(GENERATING) replaces ops.acquire.

    Injecting a GENERATING lock on M14|1 causes POST /api/runs (which also
    acquires GENERATING) to return 409 "cell busy".
    """
    c, app = client
    registry: CellLockRegistry = app.state.registry
    # Inject GENERATING on M14|1 — the same cell that POST /api/runs would try
    assert registry.try_acquire_cell("M14", 1, CellOperation.GENERATING)
    try:
        resp = c.post("/api/runs", json=_run_payload())
        assert resp.status_code == 409
        # P2 message: "cell M14|1 is busy — retry after active operation completes"
        assert "busy" in resp.json()["detail"].lower() or "M14" in resp.json()["detail"]
    finally:
        registry.release_cell("M14", 1, CellOperation.GENERATING)


def test_runs_blocks_autotune_via_mutex(client):
    """Phase 2: registry.try_acquire_global("autotune") replaces ops.

    When POST /api/autotune is called and the global "autotune" op is already
    held, it returns 409 "autotune already in progress".
    """
    c, app = client
    registry: CellLockRegistry = app.state.registry
    # Inject global "autotune" op
    assert registry.try_acquire_global("autotune")
    try:
        resp = c.post("/api/autotune", json=_autotune_payload())
        assert resp.status_code == 409
        assert "autotune" in resp.json()["detail"].lower()
    finally:
        registry.release_global("autotune")


# ---------------------------- mutex release


def test_mutex_released_after_success(client, app_factory, wait_until_fixture):
    """Phase 2: after POST /api/runs completes, registry has no active GENERATING.

    The /api/runs endpoint acquires GENERATING and releases it in a finally
    block, so after start_run returns the lock must be free.
    """
    c, app = client
    registry: CellLockRegistry = app.state.registry

    started = c.post("/api/runs", json=_run_payload())
    assert started.status_code == 200

    # GENERATING must have been released synchronously after start_run returned
    # (the endpoint uses try/finally — released before return).
    snap = registry.snapshot()
    assert snap["active_cell_count"] == 0, (
        f"Expected no active cells after start_run, got: {snap['cells']}"
    )
    # Letting the watcher finish should not change that.
    app_factory.stub_popen.processes[0].finish(0)
    wait_until_fixture(
        lambda: registry.snapshot()["active_cell_count"] == 0,
        timeout=5.0,
        msg="registry unexpectedly busy after run completion",
    )
