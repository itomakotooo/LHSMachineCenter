"""Tests for the structured analyzer-failure message built by _watch_run.

Silent analyzer crashes (no stderr / stdout) used to persist an empty
error_message that the frontend rendered as "unknown error". These tests
lock in the new contract: the message always carries at least the exit
code, and names any missing output artefacts.
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


def test_silent_analyzer_crash_leaves_structured_error_message(
    client, app_factory, wait_until_fixture
):
    """A subprocess that exits non-zero with no stderr/stdout should NOT
    leave error_message empty. It must include exit_code and which output
    files are missing."""
    c, _app = client
    resp = c.post("/api/runs", json=_run_payload())
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]

    # Simulate a silent analyzer crash: exit code 2, empty stderr/stdout,
    # no summary / report written.
    stub = app_factory.stub_popen.processes[-1]
    stub.finish(code=2)

    wait_until_fixture(
        lambda: c.get(f"/api/runs/{run_id}").json().get("status") == "failed",
        timeout=5.0,
        msg="_watch_run never marked the run failed",
    )

    body = c.get(f"/api/runs/{run_id}").json()
    msg = body["error_message"] or ""
    assert msg, "error_message must not be empty for silent failures"
    assert "exit_code=2" in msg, f"message missing exit code: {msg!r}"
    assert "summary missing" in msg, f"message missing summary hint: {msg!r}"
    assert "report missing" in msg, f"message missing report hint: {msg!r}"


def test_analyzer_stderr_is_preserved_in_failure_message(
    client, app_factory, wait_until_fixture
):
    """When stderr IS present, it should appear verbatim at the start of
    the message; the exit_code / missing hints are still appended."""
    c, _app = client
    resp = c.post("/api/runs", json=_run_payload())
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]

    # communicate() returns self._stderr lazily, so injecting it before
    # finish() fires is enough to have it picked up by _watch_run.
    stub = app_factory.stub_popen.processes[-1]
    stub._stderr = "Traceback: analyzer blew up\nKeyError: 'foo'"
    stub.finish(code=1)

    wait_until_fixture(
        lambda: c.get(f"/api/runs/{run_id}").json().get("status") == "failed",
        timeout=5.0,
        msg="_watch_run never marked the run failed",
    )

    msg = c.get(f"/api/runs/{run_id}").json()["error_message"]
    assert "Traceback: analyzer blew up" in msg
    assert "exit_code=1" in msg
    # Missing artefacts still listed (stub didn't write them).
    assert "summary missing" in msg
