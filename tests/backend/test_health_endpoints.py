"""Smoke tests for /api/health, /api/system-state, /api/machines, /api/models,
and /api/cache/status. These freeze the response shape so future changes
that drop a field surface as test failures.
"""
from __future__ import annotations


def test_health_ok_shape(client):
    c, _app = client
    resp = c.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["ts"], str)
    assert body["ts"].endswith("Z")
    assert isinstance(body["app_started_at"], str)
    assert body["operation_busy"] is False
    assert body["running_runs_count"] == 0
    assert body["startup_recovery_count"] == 0
    assert body["startup_terminated_pid_count"] == 0


def test_system_state_shape(client):
    c, _app = client
    resp = c.get("/api/system-state")
    assert resp.status_code == 200
    body = resp.json()
    # Top-level keys
    for key in (
        "ts",
        "app_started_at",
        "operation_busy",
        "operation_name",
        "operation_since",
        "running_runs_count",
        "running_run_ids",
        "in_memory_running_count",
        "startup_recovery",
    ):
        assert key in body, f"missing top-level key: {key}"
    # startup_recovery sub-keys
    sr = body["startup_recovery"]
    for key in (
        "recovered_count",
        "run_ids",
        "terminated_pids",
        "failed_to_terminate_pids",
    ):
        assert key in sr, f"missing startup_recovery.{key}"
    assert sr["recovered_count"] == 0
    assert sr["run_ids"] == []
    assert sr["terminated_pids"] == []
    assert sr["failed_to_terminate_pids"] == []


def test_machines_endpoint(client):
    c, _app = client
    resp = c.get("/api/machines")
    assert resp.status_code == 200
    data = resp.json()
    assert "machines" in data
    m0 = data["machines"][0]
    assert m0["machine"] == "M14"
    assert m0["modes"] == [1]
    # Enrichment fields added by load_machines.
    assert "category" in m0
    assert "report_count" in m0
    assert isinstance(m0["report_count"], int)


def test_models_endpoint_default_provider(client):
    c, _app = client
    resp = c.get("/api/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_provider"] == "gemini"
    assert body["provider_options"] == ["gemini", "gpt", "claude"]
    assert body["has_api_key"] is False
    # First warning should mention the empty provider key.
    assert any("GEMINI API key is empty" in w for w in body["warnings"])


def test_cache_status_includes_thresholds(client):
    """cache/status must expose risk_thresholds so the frontend tier wrapper
    has a server-controlled value (covers Commit 4)."""
    c, _app = client
    resp = c.get("/api/cache/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_bytes"] == 0
    assert body["file_count"] == 0
    assert body["running_runs"] == 0
    assert body["reclaimable_bytes_estimate"] == 0
    rt = body.get("risk_thresholds")
    assert rt is not None, "risk_thresholds missing"
    assert isinstance(rt["medium_bytes"], int)
    assert isinstance(rt["high_bytes"], int)
    assert rt["medium_bytes"] > 0
    assert rt["high_bytes"] >= rt["medium_bytes"]
