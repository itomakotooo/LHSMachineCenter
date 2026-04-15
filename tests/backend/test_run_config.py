"""Tests for the run config validation + fuzzy-tier rewrite.

The fuzzy tier is encoded by target_halfwidth_pp == 0 on the API. The
backend (a) forces mode 2 / 5 into this tier with a 400 response and
(b) rewrites the spawned analyzer command so the CI-stop branch never
fires and max_chunks targets ~1M spins.
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


# ---------- fuzzy tier rewrite ----------


def test_fuzzy_mode_recomputes_max_chunks_and_loosens_halfwidth(
    client, app_factory
):
    """With halfwidth=0 and chunk_spin_times * chunk_robot_count = 100_000,
    max_chunks should be rewritten to 10 (ceil(1_000_000 / 100_000))
    and the CI target passed to the analyzer should be 999.0."""
    c, _app = client
    resp = c.post(
        "/api/runs",
        json=_run_payload(
            mode=1,
            target_halfwidth_pp=0,
            chunk_spin_times=5000,
            chunk_robot_count=20,
            max_chunks=120,  # should be ignored in favor of fuzzy-computed value
        ),
    )
    assert resp.status_code == 200, resp.text

    cmds = app_factory.stub_popen.cmds
    assert cmds, "expected RunManager to spawn at least one stub process"
    cmd = cmds[-1]
    halfwidth_idx = cmd.index("--target-halfwidth-pp")
    assert cmd[halfwidth_idx + 1] == "999.0", (
        f"fuzzy mode should pass halfwidth 999.0, got {cmd[halfwidth_idx + 1]}"
    )
    max_chunks_idx = cmd.index("--max-chunks")
    assert cmd[max_chunks_idx + 1] == "10", (
        f"fuzzy mode should derive max_chunks=10 for 5000x20 per chunk, "
        f"got {cmd[max_chunks_idx + 1]}"
    )


def test_non_fuzzy_preserves_user_max_chunks_and_halfwidth(
    client, app_factory
):
    c, _app = client
    resp = c.post(
        "/api/runs",
        json=_run_payload(mode=1, target_halfwidth_pp=2.0, max_chunks=50),
    )
    assert resp.status_code == 200, resp.text

    cmd = app_factory.stub_popen.cmds[-1]
    halfwidth_idx = cmd.index("--target-halfwidth-pp")
    assert cmd[halfwidth_idx + 1] == "2.0"
    max_chunks_idx = cmd.index("--max-chunks")
    assert cmd[max_chunks_idx + 1] == "50"


# ---------- mode 2 / 5 constraint ----------


def test_mode_2_rejects_non_fuzzy(client):
    c, _app = client
    resp = c.post("/api/runs", json=_run_payload(mode=2, target_halfwidth_pp=0.5))
    assert resp.status_code == 400
    assert "fuzzy" in resp.json()["detail"].lower()


def test_mode_5_rejects_non_fuzzy(client):
    c, _app = client
    resp = c.post("/api/runs", json=_run_payload(mode=5, target_halfwidth_pp=1.0))
    assert resp.status_code == 400
    assert "fuzzy" in resp.json()["detail"].lower()


def test_mode_2_accepts_fuzzy(client):
    c, _app = client
    resp = c.post("/api/runs", json=_run_payload(mode=2, target_halfwidth_pp=0))
    assert resp.status_code == 200, resp.text


def test_mode_1_accepts_any_halfwidth(client):
    c, _app = client
    resp = c.post("/api/runs", json=_run_payload(mode=1, target_halfwidth_pp=2.0))
    assert resp.status_code == 200, resp.text


def test_mode_7_accepts_any_halfwidth(client):
    c, _app = client
    resp = c.post("/api/runs", json=_run_payload(mode=7, target_halfwidth_pp=0.5))
    assert resp.status_code == 200, resp.text
