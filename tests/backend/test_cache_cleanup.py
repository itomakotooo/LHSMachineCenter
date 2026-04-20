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


def test_lock_survives_md5_drift_in_check_rawdata_status(
    tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata, fake_analyzer,
    tmp_path, monkeypatch,
):
    """REGRESSION: User reported M1|1 losing millions of spins of
    locked chunks across a full batch (2026-04-20). Root cause:
    ``start_batch`` calls ``check_rawdata_status(auto_delete_mismatched
    =True)`` for every item, and that code path
    unlinked any chunk whose envelope md5 didn't match current upstream
    — without consulting the lock registry. A machine whose config md5
    had drifted historically (old chunks carrying OLD md5, newer chunks
    carrying CUR md5) saw ALL the old ones wiped the first time a
    full-fleet batch ran, even if the operator had locked that
    (machine, mode).

    This test locks M1|1, seeds a mix of stale + current chunks (the
    exact pattern that bit M1 in production), and asserts that
    ``check_rawdata_status(auto_delete_mismatched=True)`` leaves
    every chunk on disk. The fix is the ``is_locked`` guard added
    inside the function; without it, this test fails with the old
    chunks gone."""
    monkeypatch.setattr(
        "src.web_console.backend.app._default_popen_factory",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )
    mc = tmp_path / "machines.json"
    mc.write_text(json.dumps({
        "machines": [{
            "machine": "M1", "modes": [1],
            "configSummaryMd5": "CUR_CFG",
            "codeSummaryMd5": "CUR_CODE",
        }],
    }), encoding="utf-8")

    mode_dir = tmp_rawdata / "M1" / "mode_1"
    # Historical old-md5 chunks (the "几百万 spins" the user lost)
    stale_paths = []
    for i in range(1, 6):
        stale_paths.append(_write_chunk(
            mode_dir, i, config_md5="OLD_CFG", code_md5="OLD_CODE",
            spin_times=10_000,
        ))
    # Recent chunks with current md5 (these survived in prod too
    # — it's the OLD-md5 chunks that got wiped).
    current_paths = []
    for i in range(6, 9):
        current_paths.append(_write_chunk(
            mode_dir, i, config_md5="CUR_CFG", code_md5="CUR_CODE",
            spin_times=10_000,
        ))

    # Write the lock registry BEFORE the batch-like call. Production
    # bug: lock file was consulted by _auto_cleanup_for_space but NOT
    # by check_rawdata_status, so auto_delete_mismatched bulldozed the
    # stale chunks regardless.
    locks_path = mc.parent / "rawdata_locks.json"
    locks_path.write_text(json.dumps({
        "locked": ["M1|1"], "updated_at": "2026-04-20T05:19:41Z",
    }), encoding="utf-8")

    # Invalidate the module-level lock cache so our freshly-written
    # file is picked up. The cache keys on mtime_ns; a same-second
    # write with a cold module can return an empty set otherwise.
    import src.web_console.backend.app as app_mod
    app_mod._LOCK_CACHE["mtime"] = 0
    app_mod._LOCK_CACHE["data"] = None

    from src.web_console.backend.app import check_rawdata_status
    result = check_rawdata_status(
        "M1", 1,
        rawdata_root=tmp_rawdata, machines_config=mc,
        auto_delete_mismatched=True,
    )

    # All 5 OLD chunks are still on disk — lock held the line.
    for p in stale_paths:
        assert p.exists(), f"LOCKED OLD-md5 chunk was deleted: {p.name}"
    for p in current_paths:
        assert p.exists(), f"current chunk vanished somehow: {p.name}"
    # Status still reports the stale chunks as mismatched so the UI
    # can flag "已锁 + stale" and nudge the operator to decide.
    assert result["mismatch_chunks"] == 5
    assert result["usable_chunks"] == 3
    # deleted_paths should be empty — nothing was removed.
    assert result["deleted_paths"] == []


def test_delete_rawdata_respects_lock_without_force(
    tmp_rawdata, tmp_path, monkeypatch,
):
    """The /api/rawdata/{m} DELETE endpoint (default, non-force) goes
    through delete_rawdata(force=False) which runs the classifier.
    Locked (machine, mode) should be preserved; force=True overrides.

    Paired with the above test — together they ensure both the
    auto-delete path (check_rawdata_status) and the manual
    classifier-delete path (delete_rawdata) honor the lock uniformly.
    """
    mc = tmp_path / "machines.json"
    mc.write_text(json.dumps({
        "machines": [{
            "machine": "M1", "modes": [1],
            "configSummaryMd5": "CUR_CFG",
            "codeSummaryMd5": "CUR_CODE",
        }],
    }), encoding="utf-8")
    mode_dir = tmp_rawdata / "M1" / "mode_1"
    # 15 chunks × 10k spins = 150k, default retention 100k → 10 kept,
    # 5 deletable. Without a lock, delete_rawdata(force=False) would
    # remove the 5 deletable ones.
    base_mtime = 1_700_000_000
    paths = []
    for i in range(1, 16):
        paths.append(_write_chunk(
            mode_dir, i, config_md5="CUR_CFG", code_md5="CUR_CODE",
            spin_times=10_000, mtime=base_mtime + i,
        ))
    # Lock M1|1
    locks_path = mc.parent / "rawdata_locks.json"
    locks_path.write_text(json.dumps({
        "locked": ["M1|1"], "updated_at": "2026-04-20T05:19:41Z",
    }), encoding="utf-8")

    import src.web_console.backend.app as app_mod
    app_mod._LOCK_CACHE["mtime"] = 0
    app_mod._LOCK_CACHE["data"] = None

    from src.web_console.backend.app import delete_rawdata
    # force=False: lock MUST hold → nothing deleted
    result = delete_rawdata(
        "M1", 1, rawdata_root=tmp_rawdata, machines_config=mc, force=False,
    )
    assert result["ok"] is True
    assert result["deleted_chunks"] == 0
    assert result["kept_chunks"] == 15  # all survive under the lock
    assert 1 in result["skipped_locked_modes"]
    for p in paths:
        assert p.exists()

    # force=True: user explicitly overrides → chunks removed. The
    # "完全删除" button is the escape hatch; lock doesn't block it.
    result2 = delete_rawdata(
        "M1", 1, rawdata_root=tmp_rawdata, machines_config=mc, force=True,
    )
    assert result2["ok"] is True
    assert result2["forced"] is True
    assert not mode_dir.exists()


def test_unlocked_md5_drift_still_deletes(
    tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata, fake_analyzer,
    tmp_path, monkeypatch,
):
    """Inverse of the above: without a lock, the original
    auto_delete_mismatched semantics still hold — stale chunks are
    reclaimed. This prevents the fix from accidentally turning into
    "never auto-delete mismatched chunks anywhere"."""
    monkeypatch.setattr(
        "src.web_console.backend.app._default_popen_factory",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )
    mc = tmp_path / "machines.json"
    mc.write_text(json.dumps({
        "machines": [{
            "machine": "M1", "modes": [1],
            "configSummaryMd5": "CUR_CFG",
            "codeSummaryMd5": "CUR_CODE",
        }],
    }), encoding="utf-8")
    mode_dir = tmp_rawdata / "M1" / "mode_1"
    stale_paths = [
        _write_chunk(mode_dir, i, config_md5="OLD", code_md5="OLD", spin_times=10_000)
        for i in range(1, 4)
    ]

    # No lock file written — pure "drifted chunks, no operator carve-out".
    import src.web_console.backend.app as app_mod
    app_mod._LOCK_CACHE["mtime"] = 0
    app_mod._LOCK_CACHE["data"] = None

    from src.web_console.backend.app import check_rawdata_status
    result = check_rawdata_status(
        "M1", 1,
        rawdata_root=tmp_rawdata, machines_config=mc,
        auto_delete_mismatched=True,
    )
    for p in stale_paths:
        assert not p.exists(), f"unlocked stale chunk survived: {p.name}"
    assert len(result["deleted_paths"]) == 3
