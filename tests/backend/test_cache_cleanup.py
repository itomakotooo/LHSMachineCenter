"""Tests for /api/cache/cleanup behavior beyond the 'soft block' case (which
lives in test_safety_interlock.py): actual file deletion, max_delete_bytes
budget enforcement, and the mutex-blocked 409 path.
"""
from __future__ import annotations

import os


def test_cleanup_idle_deletes_all_files(client, app_factory):
    c, _app = client
    cache_dir = app_factory.cache_dir
    for i in range(3):
        (cache_dir / f"f{i}.bin").write_bytes(b"x" * 1000)
    resp = c.post("/api/cache/cleanup", json={"max_delete_bytes": 0})
    assert resp.status_code == 200
    assert resp.json() == {"deleted_files": 3, "deleted_bytes": 3000}
    assert list(cache_dir.iterdir()) == []


def test_cleanup_respects_max_delete_bytes(client, app_factory):
    """With three 1000-byte files and a 1500-byte budget, only the oldest
    file should be deleted (adding the second one would exceed 1500)."""
    c, _app = client
    cache_dir = app_factory.cache_dir
    files = []
    for i in range(3):
        f = cache_dir / f"f{i}.bin"
        f.write_bytes(b"y" * 1000)
        files.append(f)
    # Force ascending mtime so deletion order is deterministic.
    base_mtime = 1_700_000_000
    for idx, f in enumerate(files):
        os.utime(f, (base_mtime + idx, base_mtime + idx))

    resp = c.post("/api/cache/cleanup", json={"max_delete_bytes": 1500})
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted_files"] == 1
    assert body["deleted_bytes"] == 1000
    # The first file (oldest mtime) should be the one deleted.
    assert not files[0].exists()
    assert files[1].exists()
    assert files[2].exists()


def test_cleanup_blocked_by_mutex_returns_409(client, app_factory):
    c, app = client
    (app_factory.cache_dir / "junk.bin").write_bytes(b"z" * 100)
    assert app.state.ops.acquire("auto_tune")
    try:
        resp = c.post("/api/cache/cleanup", json={"max_delete_bytes": 0})
        assert resp.status_code == 409
        assert resp.json()["detail"] == "system busy: auto_tune"
    finally:
        app.state.ops.release()
    # File still there; mutex-blocked cleanup must not delete anything.
    assert (app_factory.cache_dir / "junk.bin").exists()
