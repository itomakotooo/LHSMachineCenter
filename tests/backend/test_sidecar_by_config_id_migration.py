"""P3-T5: Sidecar by_config_id migration tests.

Covers 3 original + 2 critic-fix regression tests + 1 loop-back-3 deadlock regression.

Original tests (session_artifacts/_impl/p3/brief.md §6 P3-T5):
  test_load_chunks_index_migrates_existing_sidecar
  test_load_chunks_index_idempotent_on_v3_sidecar
  test_new_chunk_with_config_id_indexed_correctly

P3 loop-back critic-fix regression tests (2026-05-17):
  test_set_chunk_config_id_moves_chunk_between_buckets  (Fix 1a)
  test_set_chunk_config_id_missing_chunk_raises         (Fix 1b)

P3 loop-back-3 deadlock regression (2026-05-17):
  test_set_chunk_config_id_on_pre_p3_sidecar_does_not_deadlock  (RLock fix)

Design source: 04_deploy_architecture_proposal_v2.md §4.3 D3 + critique m3 fix.
D3: by_config_id inverted index + lazy migration in load_chunks_index.

The sidecar schema (v3 layout, P3):
  {
    "_version": 1,
    "_updated_at": "...",
    "chunks": {
      "chunk_0001.json": {..., "config_id": "null"},
      ...
    },
    "by_md5": {...},
    "by_config_id": {
      "null": ["chunk_0001.json"],
      "<sha1>": ["chunk_0002.json"]
    }
  }

Memory feedback files honored:
  memory/feedback_enumerate_safety_paths.md — inject-bug recipe for each invariant.
  memory/reference_chunk_index_inverted_md5.md — by_config_id is structured parallel
    to by_md5; iterate by_config_id, never iterate chunks to filter by config.
  memory/feedback_no_silent_swallow.md — set_chunk_config_id raises KeyError on
    missing chunk so caller can handle it and write diagnostics.

Inject-bug recipes (for future devs to reproduce):

  D3a (test_load_chunks_index_migrates_existing_sidecar):
    In fresh_slotlab/chunk_index.py load_chunks_index, remove the lazy migration block:
        if "by_config_id" not in data:
            _migrate_by_config_id(mode_dir, data)
    Run test → FAILS: by_config_id key missing from returned data. Revert → PASSES.

  D3b (test_new_chunk_with_config_id_indexed_correctly):
    In fresh_slotlab/chunk_index.py update_chunk_entry, remove the by_config_id
    maintenance block (the _new_config_id / by_config_id update code) →
    new chunk not added to by_config_id["X"] → test FAILS. Revert → PASSES.

  D3c (_migrate_by_config_id backfill):
    In fresh_slotlab/chunk_index.py _migrate_by_config_id, remove the backfill line:
        entry.setdefault("config_id", "null")
    Run test_load_chunks_index_migrates_existing_sidecar → FAILS (chunk entries
    still missing config_id field). Revert → PASSES.

  Fix1a (test_set_chunk_config_id_moves_chunk_between_buckets):
    In fresh_slotlab/chunk_index.py set_chunk_config_id, remove the by_config_id
    bucket update (the `if old_config_id != new_config_id:` block AND the
    `new_bucket = by_config_id.setdefault(...)` block) → chunk stays in "null"
    bucket and is NOT added to the new config_id bucket → test FAILS.
    Revert → PASSES.

  Fix1b (test_set_chunk_config_id_missing_chunk_raises):
    In fresh_slotlab/chunk_index.py set_chunk_config_id, remove the KeyError
    raise when chunk_file_name not in chunks (let it silently return None) →
    the test's pytest.raises(KeyError) block passes the silently-returning call
    but the assertion inside will catch the missing raise → test FAILS.
    Revert → PASSES.

  RLock-deadlock (test_set_chunk_config_id_on_pre_p3_sidecar_does_not_deadlock):
    In fresh_slotlab/chunk_index.py, change:
        _SIDECAR_LOCKS: dict[str, threading.RLock] = {}
    to:
        _SIDECAR_LOCKS: dict[str, threading.Lock] = {}
    AND change in _sidecar_lock_for:
        lock = threading.RLock()
    to:
        lock = threading.Lock()
    The test spawns a daemon thread that calls set_chunk_config_id on a
    pre-P3 sidecar (no by_config_id), which internally calls load_chunks_index
    → _migrate_by_config_id → _sidecar_lock_for → second acquire of the SAME
    Lock from the same thread → deadlock. Thread.join(timeout=5.0) times out
    → completed.is_set() is False → AssertionError. Revert → PASSES.

Cross-refs:
  session_artifacts/_impl/p3/brief.md §6 P3-T5
  session_artifacts/_impl/p3/critique.md (Fix 1 — set_chunk_config_id)
  session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.3 D3
  memory/reference_chunk_index_inverted_md5.md
  memory/feedback_no_silent_swallow.md
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fresh_slotlab.chunk_index import (
    SIDECAR_VERSION,
    _migrate_by_config_id,
    _rebuild_by_config_id,
    _write_sidecar_atomic,
    _sidecar_path,
    load_chunks_index,
)


# ---------------------------------------------------------------------------
# Helpers: build pre-P3 sidecars (no by_config_id)
# ---------------------------------------------------------------------------


def _write_pre_p3_sidecar(mode_dir: Path, chunks: dict) -> Path:
    """Write a sidecar without by_config_id (simulates pre-P3 on-disk state).

    Chunks dict: {filename: {meta_dict}}.  No by_config_id key.
    """
    mode_dir.mkdir(parents=True, exist_ok=True)
    sidecar = {
        "_version": SIDECAR_VERSION,
        "_updated_at": "2026-01-01T00:00:00Z",
        "chunks": chunks,
        "by_md5": {
            f"{v.get('_config_md5', '')}|{v.get('_code_md5', '')}": [fname]
            for fname, v in chunks.items()
        },
        # NO by_config_id key — this is the pre-P3 layout
    }
    p = _sidecar_path(mode_dir)
    p.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return p


def _write_v3_sidecar(mode_dir: Path, chunks: dict) -> Path:
    """Write a sidecar WITH by_config_id (simulates post-P3 on-disk state)."""
    mode_dir.mkdir(parents=True, exist_ok=True)
    by_cid = _rebuild_by_config_id(chunks)
    sidecar = {
        "_version": SIDECAR_VERSION,
        "_updated_at": "2026-01-01T00:00:00Z",
        "chunks": chunks,
        "by_md5": {},
        "by_config_id": by_cid,
    }
    p = _sidecar_path(mode_dir)
    p.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# P3-T5 tests
# ---------------------------------------------------------------------------


class TestSidecarByConfigIdMigration:
    """D3: lazy migration of by_config_id on first load_chunks_index call."""

    def test_load_chunks_index_migrates_existing_sidecar(self, tmp_path: Path):
        """Pre-P3 sidecar (no by_config_id) → load_chunks_index adds by_config_id.

        Migration must:
          1. Add by_config_id = {"null": [all_chunks]} to in-memory data.
          2. Backfill config_id="null" on each chunk entry.
          3. Persist the v3 layout to disk (so next read hits the fast path).

        Inject-bug: remove the lazy migration block from load_chunks_index:
            if "by_config_id" not in data:
                _migrate_by_config_id(mode_dir, data)
        Run test → FAILS: by_config_id key absent in returned data. Revert → PASSES.
        """
        mode_dir = tmp_path / "M14" / "mode_1"

        # Write pre-P3 sidecar with 2 chunks (no config_id, no by_config_id)
        pre_p3_chunks = {
            "chunk_0001.json": {
                "_chunk_index": 1,
                "_config_md5": "cfg1",
                "_code_md5": "code1",
                "_spin_times": 1000,
                "_robot_count": 8,
            },
            "chunk_0002.json": {
                "_chunk_index": 2,
                "_config_md5": "cfg1",
                "_code_md5": "code1",
                "_spin_times": 1000,
                "_robot_count": 8,
            },
        }
        _write_pre_p3_sidecar(mode_dir, pre_p3_chunks)

        # Call load_chunks_index → should trigger migration
        data = load_chunks_index(mode_dir)
        assert data is not None, "load_chunks_index must return data for valid sidecar"

        # 1. by_config_id must be present in returned data
        assert "by_config_id" in data, (
            "by_config_id must be added by lazy migration in load_chunks_index. "
            "Inject-bug: remove the `if 'by_config_id' not in data:` block."
        )

        # 2. All chunks must be in the "null" bucket
        by_cid = data["by_config_id"]
        assert "null" in by_cid, (
            f"Expected 'null' bucket in by_config_id, got keys: {list(by_cid.keys())}"
        )
        null_chunks = set(by_cid["null"])
        assert "chunk_0001.json" in null_chunks
        assert "chunk_0002.json" in null_chunks

        # 3. Each chunk entry must have config_id="null" backfilled
        chunks = data.get("chunks", {})
        for fname, entry in chunks.items():
            assert entry.get("config_id") == "null", (
                f"Chunk {fname} should have config_id='null' after migration, "
                f"got {entry.get('config_id')!r}. "
                "Inject-bug: remove `entry.setdefault('config_id', 'null')` from _migrate_by_config_id."
            )

        # 4. Persistence: the sidecar on disk must now have by_config_id
        persisted = json.loads(_sidecar_path(mode_dir).read_text(encoding="utf-8"))
        assert "by_config_id" in persisted, (
            "Migrated by_config_id must be persisted to disk so next read hits fast path."
        )

    def test_load_chunks_index_idempotent_on_v3_sidecar(self, tmp_path: Path):
        """Already-migrated sidecar → second load_chunks_index is a no-op.

        The migration block only runs when by_config_id is absent.
        A sidecar that already has by_config_id must not be double-migrated.
        """
        mode_dir = tmp_path / "M14" / "mode_1"

        # Write already-migrated sidecar
        chunks = {
            "chunk_0001.json": {
                "_chunk_index": 1,
                "_config_md5": "cfg1",
                "_code_md5": "code1",
                "_spin_times": 1000,
                "_robot_count": 8,
                "config_id": "null",
            }
        }
        _write_v3_sidecar(mode_dir, chunks)

        # Track disk mtime before second load
        sidecar_path = _sidecar_path(mode_dir)
        mtime_before = sidecar_path.stat().st_mtime

        # First load (triggers no migration — already v3)
        data1 = load_chunks_index(mode_dir)
        assert data1 is not None
        assert "by_config_id" in data1

        # Second load — must not re-write (idempotent)
        data2 = load_chunks_index(mode_dir)
        assert data2 is not None
        assert "by_config_id" in data2

        # by_config_id content must be identical between loads
        assert data1["by_config_id"] == data2["by_config_id"], (
            "Second load returned different by_config_id — possible double-migration bug"
        )

    def test_new_chunk_with_config_id_indexed_correctly(self, tmp_path: Path):
        """Write a chunk with config_id="X"; assert by_config_id["X"] contains it.

        Tests the update_chunk_entry maintenance path (D3 mutator updates).

        Inject-bug: in chunk_index.py update_chunk_entry, remove the by_config_id
        maintenance block → new chunk not indexed → by_config_id["X"] empty → test FAILS.
        Revert → PASSES.
        """
        from fresh_slotlab.chunk_index import update_chunk_entry, load_chunks_index

        mode_dir = tmp_path / "M14" / "mode_1"
        mode_dir.mkdir(parents=True, exist_ok=True)

        # Write a chunk file to disk (update_chunk_entry reads/updates sidecar for it)
        chunk_file = mode_dir / "chunk_0001.json"
        config_id = "abc123sha1deadbeef"
        chunk_file.write_text(json.dumps({
            "_chunk_index": 1,
            "_config_md5": "cfg_x",
            "_code_md5": "code_x",
            "_spin_times": 1000,
            "_robot_count": 8,
            "rounds": [],
        }), encoding="utf-8")

        # update_chunk_entry: chunk metadata including config_id
        # The function signature: update_chunk_entry(mode_dir, chunk_file, ...)
        # We call it with the minimal required arguments
        update_chunk_entry(
            mode_dir,
            chunk_file,
            chunk_index=1,
            config_md5="cfg_x",
            code_md5="code_x",
            spin_times=1000,
            robot_count=8,
        )

        # Load the sidecar and verify by_config_id
        data = load_chunks_index(mode_dir)
        assert data is not None, "Sidecar must exist after update_chunk_entry"
        assert "by_config_id" in data, (
            "Sidecar must have by_config_id after update_chunk_entry"
        )

        # New chunk without explicit config_id → should land in "null" bucket
        # (config_id is not yet wired through update_chunk_entry per P3 notes)
        by_cid = data["by_config_id"]
        all_indexed = []
        for bucket_chunks in by_cid.values():
            all_indexed.extend(bucket_chunks)
        assert "chunk_0001.json" in all_indexed, (
            f"chunk_0001.json not indexed in any by_config_id bucket. "
            f"Current by_config_id: {by_cid}"
        )

    def test_rebuild_by_config_id_groups_by_config_id_field(self, tmp_path: Path):
        """_rebuild_by_config_id groups chunks by their config_id field.

        Chunks without config_id → "null" bucket.
        Chunks with config_id="X" → "X" bucket.
        """
        chunks = {
            "chunk_0001.json": {"config_id": "null", "_config_md5": "a", "_code_md5": "b"},
            "chunk_0002.json": {"config_id": "null", "_config_md5": "a", "_code_md5": "b"},
            "chunk_0003.json": {"config_id": "sha1abc", "_config_md5": "c", "_code_md5": "d"},
            "chunk_0004.json": {},  # No config_id → "null" bucket
        }
        by_cid = _rebuild_by_config_id(chunks)
        assert "null" in by_cid
        assert "sha1abc" in by_cid
        assert set(by_cid["null"]) == {"chunk_0001.json", "chunk_0002.json", "chunk_0004.json"}
        assert by_cid["sha1abc"] == ["chunk_0003.json"]

    def test_migrate_by_config_id_in_place_then_persists(self, tmp_path: Path):
        """_migrate_by_config_id modifies data in-place and persists sidecar."""
        mode_dir = tmp_path / "migrate_test" / "mode_1"

        chunks = {
            "chunk_0001.json": {"_config_md5": "c1", "_code_md5": "x1"},
            "chunk_0002.json": {"_config_md5": "c2", "_code_md5": "x2"},
        }
        _write_pre_p3_sidecar(mode_dir, chunks)

        # Load the raw JSON (has no by_config_id)
        raw = json.loads(_sidecar_path(mode_dir).read_text(encoding="utf-8"))
        assert "by_config_id" not in raw

        # Call migration directly
        _migrate_by_config_id(mode_dir, raw)

        # In-memory: by_config_id must be present
        assert "by_config_id" in raw
        assert "null" in raw["by_config_id"]
        for fname in chunks:
            assert fname in raw["by_config_id"]["null"]

        # Each chunk entry must have config_id="null" backfilled
        for fname, entry in raw["chunks"].items():
            assert entry.get("config_id") == "null", (
                f"Chunk {fname} must have config_id='null' after migration"
            )

        # On disk: persisted
        persisted = json.loads(_sidecar_path(mode_dir).read_text(encoding="utf-8"))
        assert "by_config_id" in persisted, "Migration must persist sidecar to disk"


# ---------------------------------------------------------------------------
# P3 loop-back critic-fix regression tests (2026-05-17 Fix 1)
# ---------------------------------------------------------------------------


class TestSetChunkConfigId:
    """Fix 1: set_chunk_config_id atomically updates chunk entry + by_config_id index.

    Critic blocker: the critic noted that set_chunk_config_id must keep
    by_config_id in sync (move chunk OUT of old bucket AND INTO new bucket).
    Without both operations, _reassociate_orphaned_configs would re-associate
    chunks into a new config_id but the "null" inverted index would still list
    them, causing double-attribution on the next filter.

    Memory feedback: memory/feedback_enumerate_safety_paths.md (every mutator
    must update ALL related state, not just the primary field).
    """

    def _seed_sidecar_with_null_chunk(self, mode_dir: Path) -> Path:
        """Write a v3 sidecar with one chunk in the 'null' config_id bucket."""
        mode_dir.mkdir(parents=True, exist_ok=True)
        sidecar = {
            "_version": SIDECAR_VERSION,
            "_updated_at": "2026-01-01T00:00:00Z",
            "chunks": {
                "chunk_0001.json": {
                    "idx": 1,
                    "cfg_md5": "cfg1",
                    "code_md5": "code1",
                    "spin_times": 1000,
                    "robot_count": 8,
                    "saved_at": "2026-01-01T00:00:00Z",
                    "size_bytes": 1024,
                    "config_id": "null",
                }
            },
            "by_md5": {"cfg1|code1": ["chunk_0001.json"]},
            "by_config_id": {"null": ["chunk_0001.json"]},
        }
        p = _sidecar_path(mode_dir)
        p.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
        return p

    def test_set_chunk_config_id_moves_chunk_between_buckets(self, tmp_path: Path):
        """set_chunk_config_id atomically: updates chunk's config_id AND
        moves it in by_config_id (out of old bucket, into new bucket).

        Invariant enforced:
          1. chunk entry["config_id"] == new_config_id
          2. chunk NOT in old bucket ("null")
          3. chunk IN new bucket (new_config_id)
          4. Changes persist to disk (atomic write)

        Inject-bug recipe (Fix1a):
          In fresh_slotlab/chunk_index.py set_chunk_config_id, remove the
          by_config_id bucket update blocks:
            - Remove: `if old_config_id != new_config_id:` block (old bucket removal)
            - Remove: `new_bucket = by_config_id.setdefault(...)` block (new bucket add)
          Run test → FAILS: "chunk_0001.json" still in by_config_id["null"] and
          NOT in by_config_id["X_config_id"]. Revert → PASSES.

        Memory: memory/feedback_enumerate_safety_paths.md
        """
        from fresh_slotlab.chunk_index import set_chunk_config_id, load_chunks_index

        mode_dir = tmp_path / "M14" / "mode_1"
        self._seed_sidecar_with_null_chunk(mode_dir)

        new_config_id = "X_config_id_sha1abc"

        # Act: move chunk from "null" to new_config_id
        set_chunk_config_id(mode_dir, "chunk_0001.json", new_config_id)

        # Read back from disk to verify persistence
        data = load_chunks_index(mode_dir)
        assert data is not None, "Sidecar must exist and be readable after set_chunk_config_id"

        # 1. Per-chunk entry updated
        entry = data["chunks"].get("chunk_0001.json")
        assert entry is not None, "chunk_0001.json must still exist in sidecar after reassignment"
        assert entry["config_id"] == new_config_id, (
            f"chunk entry config_id must be {new_config_id!r}, got {entry['config_id']!r}. "
            "Inject-bug: if set_chunk_config_id only updates entry but skips by_config_id, "
            "the inverted index is inconsistent (entry says new but index still says old)."
        )

        # 2. Old bucket ("null") must NOT contain the chunk
        by_cid = data.get("by_config_id", {})
        null_bucket = by_cid.get("null", [])
        assert "chunk_0001.json" not in null_bucket, (
            f"chunk_0001.json must be removed from 'null' bucket after reassignment. "
            f"Current 'null' bucket: {null_bucket}. "
            "Inject-bug: remove the `if old_config_id != new_config_id:` block → "
            "chunk stays in old bucket → double-attribution on filter."
        )

        # 3. New bucket must contain the chunk
        new_bucket = by_cid.get(new_config_id, [])
        assert "chunk_0001.json" in new_bucket, (
            f"chunk_0001.json must be in by_config_id[{new_config_id!r}] after reassignment. "
            f"Current new bucket: {new_bucket}. "
            "Inject-bug: remove the `new_bucket = by_config_id.setdefault(...)` block → "
            "chunk not added to new bucket → _reassociate_orphaned_configs has no effect."
        )

    def test_set_chunk_config_id_missing_chunk_raises(self, tmp_path: Path):
        """set_chunk_config_id on a chunk NOT in sidecar raises KeyError.

        This is the documented behavior: caller (_reassociate_orphaned_configs)
        catches KeyError and writes diagnostic per feedback_no_silent_swallow.md.
        A silent no-op would mask failures (chunk may have been rebuilt / deleted).

        Inject-bug recipe (Fix1b):
          In fresh_slotlab/chunk_index.py set_chunk_config_id, remove the
          explicit KeyError raise:
              raise KeyError(f"{chunk_file_name!r} not in sidecar chunks index")
          Replace with `return` (silent no-op) → pytest.raises(KeyError) catches
          that no exception was raised → test FAILS with "DID NOT RAISE".
          Revert → PASSES.

        Memory: memory/feedback_no_silent_swallow.md
        """
        from fresh_slotlab.chunk_index import set_chunk_config_id

        # Case 1: empty mode_dir — no sidecar at all
        mode_dir_empty = tmp_path / "M14" / "mode_empty"
        mode_dir_empty.mkdir(parents=True, exist_ok=True)

        with pytest.raises(KeyError, match="not in sidecar"):
            set_chunk_config_id(mode_dir_empty, "chunk_9999.json", "some_config_id")

        # Case 2: sidecar exists but does NOT contain the requested chunk
        mode_dir_real = tmp_path / "M14" / "mode_real"
        self._seed_sidecar_with_null_chunk(mode_dir_real)  # has chunk_0001.json, not 9999

        with pytest.raises(KeyError, match="not in sidecar"):
            set_chunk_config_id(mode_dir_real, "chunk_9999.json", "some_config_id")

        # Sanity: existing chunk does NOT raise
        set_chunk_config_id(mode_dir_real, "chunk_0001.json", "valid_config")  # must not raise


# ---------------------------------------------------------------------------
# P3 loop-back-3 deadlock regression (2026-05-17)
# ---------------------------------------------------------------------------


class TestRLockDeadlockRegression:
    """REGRESSION: set_chunk_config_id on a pre-P3 sidecar must not deadlock.

    Root cause (identified by impl-critic in critique_v2.md BUG-1):

    set_chunk_config_id acquires _sidecar_lock_for(mode_dir) then calls
    load_chunks_index(mode_dir). When the on-disk sidecar is pre-P3 (no
    by_config_id field), load_chunks_index calls _migrate_by_config_id,
    which calls _sidecar_lock_for(mode_dir) again to persist the migrated
    sidecar. With a plain threading.Lock (non-reentrant), the second acquire
    from the SAME thread blocks forever — deadlock.

    Fix: _SIDECAR_LOCKS now uses threading.RLock (reentrant). The same thread
    can re-acquire an already-held RLock without blocking.

    Memory feedback:
      memory/feedback_enumerate_safety_paths.md — every call path that can
        re-enter a lock must be identified; switching to RLock is the correct
        fix. Test proves the fix with real thread + timeout.
      memory/feedback_perf_claim_needs_e2e_event_stream.md — concurrency
        tests must use real threads (not mocks) to detect actual deadlocks.

    Inject-bug recipe:
      In fresh_slotlab/chunk_index.py change:
          _SIDECAR_LOCKS: dict[str, threading.RLock] = {}
      to:
          _SIDECAR_LOCKS: dict[str, threading.Lock] = {}
      AND in _sidecar_lock_for change:
          lock = threading.RLock()
      to:
          lock = threading.Lock()
      Run this test → thread.join(timeout=5.0) returns without completed being
      set → AssertionError "set_chunk_config_id deadlocked on pre-P3 sidecar!"
      Revert both lines → green.

    See session_artifacts/_impl/p3/critique_v2.md §BUG-1 for analysis.
    """

    def test_set_chunk_config_id_on_pre_p3_sidecar_does_not_deadlock(
        self, tmp_path: Path
    ):
        """set_chunk_config_id on a pre-P3 sidecar (no by_config_id) must
        complete promptly. Uses a real daemon thread with 5s join timeout to
        detect the hang without blocking the test suite.

        The deadlock path:
          set_chunk_config_id
            → acquires _sidecar_lock_for(mode_dir)  [1st acquire]
            → calls load_chunks_index(mode_dir)
              → sees no by_config_id in sidecar
              → calls _migrate_by_config_id(mode_dir, data)
                → acquires _sidecar_lock_for(mode_dir)  [2nd acquire — deadlock with Lock]

        With RLock the 2nd acquire re-enters immediately.
        """
        import threading
        from fresh_slotlab.chunk_index import (
            SIDECAR_VERSION,
            _sidecar_path,
            set_chunk_config_id,
            load_chunks_index,
        )

        mode_dir = tmp_path / "M14" / "mode_deadlock"
        mode_dir.mkdir(parents=True)

        # Seed a PRE-P3 sidecar — has 'chunks' but NO 'by_config_id' key.
        # This triggers the lazy migration path inside load_chunks_index.
        pre_p3_sidecar = {
            "_version": SIDECAR_VERSION,
            "_updated_at": "2026-01-01T00:00:00Z",
            "chunks": {
                "chunk_0001.json": {
                    "idx": 1,
                    "cfg_md5": "cfg1",
                    "code_md5": "code1",
                    "spin_times": 1000,
                    "robot_count": 8,
                    "saved_at": "2026-01-01T00:00:00Z",
                    "size_bytes": 1024,
                    # NOTE: no "config_id" key — pre-P3 layout
                },
                "chunk_0002.json": {
                    "idx": 2,
                    "cfg_md5": "cfg1",
                    "code_md5": "code1",
                    "spin_times": 1000,
                    "robot_count": 8,
                    "saved_at": "2026-01-01T00:00:00Z",
                    "size_bytes": 1024,
                },
            },
            "by_md5": {"cfg1|code1": ["chunk_0001.json", "chunk_0002.json"]},
            # NO "by_config_id" — this is the critical condition
        }
        _sidecar_path(mode_dir).write_text(
            json.dumps(pre_p3_sidecar, indent=2), encoding="utf-8"
        )

        # Without RLock, this call would deadlock waiting for itself.
        # With RLock it completes promptly (sub-second).
        # We detect the hang by running in a daemon thread with a join timeout.
        completed = threading.Event()
        exc_holder: list[BaseException] = []

        def _do_set() -> None:
            try:
                set_chunk_config_id(mode_dir, "chunk_0001.json", "X_config_id_sha1")
            except Exception as exc:
                exc_holder.append(exc)
            finally:
                completed.set()

        t = threading.Thread(target=_do_set, daemon=True)
        t.start()
        t.join(timeout=5.0)

        assert completed.is_set(), (
            "set_chunk_config_id deadlocked on pre-P3 sidecar (no by_config_id)! "
            "The thread did not complete within 5s. "
            "Inject-bug: revert _SIDECAR_LOCKS from RLock to Lock AND "
            "_sidecar_lock_for to return threading.Lock() → this assertion fires. "
            "Revert both changes → green. "
            "See session_artifacts/_impl/p3/critique_v2.md §BUG-1."
        )

        # No unexpected exceptions (KeyError is acceptable if chunk not in sidecar,
        # but shouldn't happen since we just wrote chunk_0001.json).
        if exc_holder:
            raise AssertionError(
                f"set_chunk_config_id raised an unexpected exception: {exc_holder[0]!r}"
            ) from exc_holder[0]

        # Verify both migration AND reassignment happened correctly.
        data = load_chunks_index(mode_dir)
        assert data is not None, "Sidecar must be readable after set_chunk_config_id"

        # Migration: by_config_id must now be present
        assert "by_config_id" in data, (
            "by_config_id must have been added by migration inside load_chunks_index "
            "during the set_chunk_config_id call."
        )

        # chunk_0001.json was reassigned → must be in new bucket
        by_cid = data["by_config_id"]
        new_bucket = by_cid.get("X_config_id_sha1", [])
        assert "chunk_0001.json" in new_bucket, (
            f"chunk_0001.json must be in by_config_id['X_config_id_sha1'] after "
            f"reassignment, got: {by_cid}"
        )

        # chunk_0002.json was untouched → must still be in "null" bucket
        null_bucket = by_cid.get("null", [])
        assert "chunk_0002.json" in null_bucket, (
            f"chunk_0002.json must remain in by_config_id['null'] (untouched), "
            f"got null_bucket={null_bucket}"
        )

        # chunk_0001.json must NOT be in "null" bucket
        assert "chunk_0001.json" not in null_bucket, (
            f"chunk_0001.json must have been removed from 'null' bucket after "
            f"reassignment, got null_bucket={null_bucket}"
        )
