"""Tests for /api/cache/cleanup — tiered deletion over RAWDATA_ROOT.

Cleanup now operates on the rawdata root (where actual chunks live)
instead of the old transient cache/chunks/ tree. The retention quota
(default 100k spins per (machine, mode)) protects baseline chunks from
both manual delete and auto-cleanup; everything above that — plus
stale-md5 chunks — is candidate for reclamation, sorted oldest-mtime
first.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _write_chunk(
    dir_: Path,
    idx: int,
    *,
    config_md5: str,
    code_md5: str,
    spin_times: int = 5_000,
    mtime: float | None = None,
) -> Path:
    """Write a minimal envelope-shaped chunk that _classify_chunks can
    parse. Real chunks have more fields but the classifier only reads
    ``_config_md5`` / ``_code_md5`` / ``_spin_times``."""
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / f"chunk_{idx:04d}.json"
    p.write_text(json.dumps({
        "_cache_version": 3,
        "_machine": "M14",
        "_mode": 1,
        "_bet": 1000,
        "_spin_times": spin_times,
        "_robot_count": 1,
        "_chunk_index": idx,
        "_saved_at": "2026-04-01T00:00:00Z",
        "_config_md5": config_md5,
        "_code_md5": code_md5,
        "response": [],
    }), encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


# fake_machines (the conftest fixture) writes M14 without md5 fields;
# _get_machine_md5 returns ("", "") → unverifiable=True → all chunks
# treated as valid. That's fine for most cleanup tests since the tier
# logic only relies on the spin-quota split in the unverifiable case.
# Tests that exercise "stale md5" bypass the default fixture.


def test_cleanup_keeps_baseline_deletes_excess(client, app_factory):
    """Write 15 chunks × 10k spins = 150k total. Default retention
    is 100k → first 10 chunks are kept (100k exactly), last 5 are
    deletable. Cleanup should remove exactly those 5."""
    c, _app = client
    mode_dir = app_factory.rawdata_dir / "M14" / "mode_1"
    base_mtime = 1_700_000_000
    for i in range(1, 16):
        _write_chunk(
            mode_dir, i, config_md5="cfg1", code_md5="code1",
            spin_times=10_000, mtime=base_mtime + i,
        )
    assert len(list(mode_dir.glob("chunk_*.json"))) == 15

    resp = c.post("/api/cache/cleanup", json={"max_delete_bytes": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted_files"] == 5

    remaining = sorted(mode_dir.glob("chunk_*.json"))
    assert len(remaining) == 10
    # Kept chunks are the first 10 by chunk_index
    names = {p.name for p in remaining}
    assert names == {f"chunk_{i:04d}.json" for i in range(1, 11)}


def test_cleanup_never_exceeds_retention_quota(client, app_factory):
    """With only 5 chunks × 10k spins = 50k total, quota not reached
    → nothing is deletable. Cleanup is a no-op."""
    c, _app = client
    mode_dir = app_factory.rawdata_dir / "M14" / "mode_1"
    for i in range(1, 6):
        _write_chunk(
            mode_dir, i, config_md5="cfg1", code_md5="code1",
            spin_times=10_000,
        )
    resp = c.post("/api/cache/cleanup", json={"max_delete_bytes": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted_files"] == 0
    assert len(list(mode_dir.glob("chunk_*.json"))) == 5


def test_cleanup_respects_max_delete_bytes(client, app_factory):
    """20 chunks × 10k spins = 200k total, 10 deletable. With a budget
    capping us at 2 chunks' worth of bytes, only 2 should be deleted —
    the two oldest of the deletable group."""
    c, _app = client
    mode_dir = app_factory.rawdata_dir / "M14" / "mode_1"
    base_mtime = 1_700_000_000
    # Determinstic chunk sizes via fixed _response_padding
    written = []
    for i in range(1, 21):
        p = _write_chunk(
            mode_dir, i, config_md5="cfg1", code_md5="code1",
            spin_times=10_000, mtime=base_mtime + i,
        )
        written.append(p)
    # Use the actual on-disk size of a chunk so the budget is tight.
    chunk_size = written[0].stat().st_size
    budget = chunk_size * 2 + 10  # fits exactly 2 chunks

    resp = c.post("/api/cache/cleanup", json={"max_delete_bytes": budget})
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted_files"] == 2

    remaining = sorted(mode_dir.glob("chunk_*.json"))
    remaining_names = {p.name for p in remaining}
    # First 10 are kept (baseline), chunks 11-12 should be gone (oldest
    # of the deletable), chunks 13-20 still there.
    assert "chunk_0011.json" not in remaining_names
    assert "chunk_0012.json" not in remaining_names
    assert "chunk_0013.json" in remaining_names
    assert "chunk_0001.json" in remaining_names  # kept


def test_cleanup_blocked_by_mutex_returns_409(client, app_factory):
    c, app = client
    mode_dir = app_factory.rawdata_dir / "M14" / "mode_1"
    for i in range(1, 16):
        _write_chunk(
            mode_dir, i, config_md5="cfg1", code_md5="code1",
            spin_times=10_000,
        )
    assert app.state.ops.acquire("auto_tune")
    try:
        resp = c.post("/api/cache/cleanup", json={"max_delete_bytes": 0})
        assert resp.status_code == 409
        assert resp.json()["detail"] == "system busy: auto_tune"
    finally:
        app.state.ops.release()
    # All chunks still there; mutex-blocked cleanup must not delete.
    assert len(list(mode_dir.glob("chunk_*.json"))) == 15


def test_cleanup_reclaims_stale_md5_chunks_first(
    tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata, fake_analyzer,
    tmp_path, monkeypatch,
):
    """Stale-md5 chunks come first in the deletable queue regardless
    of mtime, because they carry no analytical value."""
    monkeypatch.setattr(
        "src.web_console.backend.app._default_popen_factory",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )
    # machines.json with explicit md5 so stale chunks are actually stale
    mc = tmp_path / "machines.json"
    mc.write_text(json.dumps({
        "machines": [{
            "machine": "M14", "modes": [1],
            "configSummaryMd5": "CUR_CFG",
            "codeSummaryMd5": "CUR_CODE",
        }],
    }), encoding="utf-8")

    mode_dir = tmp_rawdata / "M14" / "mode_1"
    base_mtime = 1_700_000_000
    # 10 baseline chunks with current md5 (all kept)
    for i in range(1, 11):
        _write_chunk(
            mode_dir, i, config_md5="CUR_CFG", code_md5="CUR_CODE",
            spin_times=10_000, mtime=base_mtime + 1000 + i,
        )
    # 2 stale chunks with OLD md5 — should be reclaimed regardless
    # that their mtime is ancient (older than the kept chunks')
    stale_paths = []
    for i in range(100, 102):
        stale_paths.append(_write_chunk(
            mode_dir, i, config_md5="OLD_CFG", code_md5="OLD_CODE",
            spin_times=10_000, mtime=base_mtime - 1000,  # older
        ))

    from src.web_console.backend.app import create_app
    from fastapi.testclient import TestClient
    app = create_app(
        state_dir=tmp_state_dir, reports_root=tmp_reports, cache_root=tmp_cache,
        machines_config=mc, analyzer_path=fake_analyzer, rawdata_root=tmp_rawdata,
    )
    with TestClient(app) as c:
        resp = c.post("/api/cache/cleanup", json={"max_delete_bytes": 0})
        assert resp.status_code == 200
        # Exactly the 2 stale chunks should be gone. The 10 kept chunks
        # are baseline (md5 current + within retention).
        assert resp.json()["deleted_files"] == 2
        for p in stale_paths:
            assert not p.exists()
        assert sum(1 for _ in mode_dir.glob("chunk_*.json")) == 10
