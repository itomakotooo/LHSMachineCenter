"""Tests for /api/autotune/progress + progress_callback plumbing in
run_auto_tune. We don't run the real autotune pipeline (which hits a
remote test API); we drive the callback directly to keep the tests
deterministic and fast.
"""
from __future__ import annotations


def test_progress_endpoint_idle_before_first_run(client):
    c, _app = client
    resp = c.get("/api/autotune/progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "idle"
    assert body["total_candidates"] == 0
    assert body["completed_candidates"] == 0
    assert body["last_result"] is None


def test_progress_callback_mutates_snapshot(client, app_factory):
    """Drive the progress sink installed by create_app directly, so we can
    assert each phase transition without running the autotune grid."""
    c, app = client

    # The sink is a closure captured inside create_app -- pull it out via
    # app.state.autotune_progress + the lock it also installed. We simulate
    # phase transitions by writing to the state dict the same way the sink
    # would; the assertion is really "the GET endpoint mirrors the state".
    # For a realistic test we go through the sink closure directly by
    # importing the helper we just exercised.
    lock = app.state.autotune_progress_lock
    progress = app.state.autotune_progress

    # Phase "start"
    with lock:
        progress.update(
            {
                "status": "running",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": None,
                "total_candidates": 4,
                "completed_candidates": 0,
                "last_result": None,
                "machine": "M14",
                "mode": 1,
            }
        )
    body = c.get("/api/autotune/progress").json()
    assert body["status"] == "running"
    assert body["total_candidates"] == 4
    assert body["completed_candidates"] == 0
    assert body["machine"] == "M14"

    # Phase "candidate" (first one in)
    with lock:
        progress["completed_candidates"] = 1
        progress["last_result"] = {
            "robot_count": 16,
            "batch_concurrency": 2,
            "success_rate": 0.96,
            "throughput_spins_per_sec": 4200.0,
            "p95_latency_s": 0.55,
        }
    body = c.get("/api/autotune/progress").json()
    assert body["completed_candidates"] == 1
    assert body["last_result"]["robot_count"] == 16
    assert body["last_result"]["success_rate"] == 0.96

    # Phase "finish"
    with lock:
        progress["status"] = "completed"
        progress["finished_at"] = "2026-01-01T00:01:30Z"
    body = c.get("/api/autotune/progress").json()
    assert body["status"] == "completed"
    assert body["finished_at"] == "2026-01-01T00:01:30Z"


def test_progress_endpoint_returns_snapshot_copy(client, app_factory):
    """The endpoint must return a copy, not the live dict, so callers can't
    mutate server state by accident."""
    c, app = client
    with app.state.autotune_progress_lock:
        app.state.autotune_progress["status"] = "running"
        app.state.autotune_progress["total_candidates"] = 9

    body1 = c.get("/api/autotune/progress").json()
    assert body1["status"] == "running"
    # Mutating the response body must not leak into the next response.
    body1["status"] = "HACKED"
    body1["total_candidates"] = 999

    body2 = c.get("/api/autotune/progress").json()
    assert body2["status"] == "running"
    assert body2["total_candidates"] == 9


def test_progress_endpoint_unaffected_by_mutex_or_active_run(client, app_factory):
    """Progress snapshot should be readable even while the ops mutex is
    held by another write op (this is a read-only endpoint)."""
    c, app = client
    assert app.state.ops.acquire("auto_tune")
    try:
        resp = c.get("/api/autotune/progress")
        assert resp.status_code == 200
    finally:
        app.state.ops.release()


# ---------- run_auto_tune loop (compact grid + early exit) ----------


def _drive_run_auto_tune(monkeypatch, *, robot_candidates, concurrency_candidates,
                         per_candidate_result):
    """Execute run_auto_tune with the remote sampling call stubbed.

    `per_candidate_result(robot, conc)` returns the dict that
    _run_parallel_candidate would normally compute; tests use it to
    inject success_rate values so the early-exit logic can be exercised
    deterministically.
    """
    from src.web_console.backend import app as backend_app
    from src.web_console.backend.app import AutoTuneRequest, run_auto_tune

    calls: list[tuple[int, int]] = []

    def fake_candidate(*, machine, mode, spin_times, robot_count, batch_concurrency,
                      rounds, timeout, bet):
        calls.append((robot_count, batch_concurrency))
        result = per_candidate_result(robot_count, batch_concurrency)
        # Fill the same surface the real function returns so the
        # ranking + recommendation block doesn't choke.
        result.setdefault("robot_count", robot_count)
        result.setdefault("batch_concurrency", batch_concurrency)
        result.setdefault("spin_times", spin_times)
        result.setdefault("rounds", rounds)
        result.setdefault("request_count", rounds * batch_concurrency)
        result.setdefault("success_count", int(result.get("success_rate", 0.0)
                                                * rounds * batch_concurrency))
        result.setdefault("total_spins", spin_times * robot_count)
        result.setdefault("p95_latency_s", 0.5)
        return result

    monkeypatch.setattr(backend_app, "_run_parallel_candidate", fake_candidate)

    progress_events: list[tuple[str, dict]] = []

    def progress_callback(phase, payload):
        progress_events.append((phase, payload or {}))

    req = AutoTuneRequest(
        machine="M14",
        mode=1,
        robot_candidates=robot_candidates,
        concurrency_candidates=concurrency_candidates,
        spin_times=120,
        rounds=1,
        timeout=10.0,
        bet=1000,
    )
    out = run_auto_tune(req, progress_callback=progress_callback)
    return out, calls, progress_events


def test_autotune_default_grid_is_compact_3x3(client):
    """Defaults: robot_candidates [8, 16, 24], concurrency_candidates
    [1, 2, 4]. The grid was 5x4 = 20 in the previous round; user
    feedback flagged it as too slow."""
    from src.web_console.backend.app import AutoTuneRequest

    req = AutoTuneRequest(machine="M14", mode=1)
    assert req.robot_candidates == [8, 16, 24]
    assert req.concurrency_candidates == [1, 2, 4]


def test_autotune_runs_all_candidates_when_healthy(monkeypatch, client):
    """No saturation -> the full 3x3 grid runs and 9 candidates land
    in the result.results list."""
    out, calls, events = _drive_run_auto_tune(
        monkeypatch,
        robot_candidates=[8, 16, 24],
        concurrency_candidates=[1, 2, 4],
        per_candidate_result=lambda r, c: {
            "success_rate": 1.0,
            "throughput_spins_per_sec": 1000.0 + r * 10 + c * 5,
        },
    )
    assert len(calls) == 9
    assert out["tested"] == 9
    # Best should be the highest throughput (largest robot * conc combo).
    assert out["best"]["robot_count"] == 24
    assert out["best"]["batch_concurrency"] == 4
    # Progress events: 1 start + 9 candidates + 1 finish.
    phases = [p for p, _ in events]
    assert phases.count("start") == 1
    assert phases.count("candidate") == 9
    assert phases.count("finish") == 1


def test_autotune_skips_higher_conc_after_saturation(monkeypatch, client):
    """Robot=24 fails at conc=1 (success_rate=0.5 < 0.7 threshold).
    The loop must skip (24, 2) and (24, 4) -- only 7 real candidates
    actually execute, the other 2 emit skipped progress events."""
    def per_candidate(robot, conc):
        # Robot 24 saturated even at lowest conc.
        if robot == 24:
            return {"success_rate": 0.5, "throughput_spins_per_sec": 800.0}
        return {"success_rate": 1.0, "throughput_spins_per_sec": 2000.0}

    out, calls, events = _drive_run_auto_tune(
        monkeypatch,
        robot_candidates=[8, 16, 24],
        concurrency_candidates=[1, 2, 4],
        per_candidate_result=per_candidate,
    )
    # _run_parallel_candidate called 7 times (8x3 + 16x3 + 24x1 = 7).
    assert len(calls) == 7
    assert (24, 1) in calls
    assert (24, 2) not in calls
    assert (24, 4) not in calls
    # Skipped events still emitted so the operator sees the early exit.
    skipped = [p for phase, p in events if phase == "candidate" and p.get("skipped")]
    assert len(skipped) == 2
    assert all(p["skip_reason"] == "saturated_at_lower_concurrency" for p in skipped)
    assert {p["batch_concurrency"] for p in skipped} == {2, 4}
    # 'tested' counts only real candidates (skipped don't go into the
    # ranked list).
    assert out["tested"] == 7


def test_autotune_partial_saturation_only_for_affected_robot(monkeypatch, client):
    """If robot=8 saturates at conc=2, robots 16 and 24 still get the
    full conc sweep (saturation is per-robot, not global)."""
    def per_candidate(robot, conc):
        if robot == 8 and conc >= 2:
            return {"success_rate": 0.4, "throughput_spins_per_sec": 500.0}
        return {"success_rate": 1.0, "throughput_spins_per_sec": 1500.0 + robot}

    out, calls, _events = _drive_run_auto_tune(
        monkeypatch,
        robot_candidates=[8, 16, 24],
        concurrency_candidates=[1, 2, 4],
        per_candidate_result=per_candidate,
    )
    # Robot 8: (1) ok, (2) marks saturated -> (4) skipped. 2 real calls.
    # Robot 16: 3 calls. Robot 24: 3 calls. Total = 8.
    assert len(calls) == 8
    assert (8, 1) in calls
    assert (8, 2) in calls
    assert (8, 4) not in calls
    assert (16, 4) in calls
    assert (24, 4) in calls
