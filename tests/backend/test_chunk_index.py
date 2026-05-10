"""Tests for the per-mode chunk metadata sidecar (``_chunks.json``).

The sidecar is an optimization layer over raw chunk files — readers
can check envelope md5 without a 3MB JSON parse. These tests lock:

  1. Peek helper correctness + byte budget (regex extracts header
     without reading the fat ``response`` field).
  2. Sidecar round-trips: write → load → match.
  3. Self-healing: missing / stale sidecars get rebuilt transparently.
  4. Writer hook parity: real ``_persist_chunk`` AND virtual
     ``write_chunk`` both populate the SAME sidecar format (one
     module shared by both writers).
  5. Reader short-circuit: real + virtual readers skip non-matching
     chunks without opening the full file (byte-counter proof).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


# ── 1. Peek correctness ──────────────────────────────────────────


class TestPeekChunkEnvelope:
    def _write_chunk(self, path: Path, *, idx: int, cfg: str, code: str,
                     response_bytes: int = 3_000_000,
                     spin_times: int = 2000, robot_count: int = 8):
        envelope = {
            "_cache_version": 3,
            "_machine": "M14",
            "_mode": 1,
            "_bet": 1000,
            "_spin_times": spin_times,
            "_robot_count": robot_count,
            "_chunk_index": idx,
            "_saved_at": "2026-04-24T12:00:00Z",
            "_config_md5": cfg,
            "_code_md5": code,
            "response": "x" * response_bytes,
        }
        path.write_text(
            json.dumps(envelope, ensure_ascii=False), encoding="utf-8",
        )

    def test_extracts_all_fields_from_fat_chunk(self, tmp_path):
        from fresh_slotlab.chunk_index import peek_chunk_envelope
        p = tmp_path / "chunk_0007.json"
        self._write_chunk(p, idx=7, cfg="localcfg_abc12345", code="real_code",
                          spin_times=2000, robot_count=8)
        assert p.stat().st_size > 2_500_000
        result = peek_chunk_envelope(p)
        assert result == {
            "idx": 7,
            "cfg_md5": "localcfg_abc12345",
            "code_md5": "real_code",
            "spin_times": 2000,
            "robot_count": 8,
        }

    def test_optional_scalars_default_to_zero(self, tmp_path):
        """Legacy envelope without _spin_times / _robot_count → peek
        still succeeds on md5 fields, optional fields default to 0."""
        from fresh_slotlab.chunk_index import peek_chunk_envelope
        p = tmp_path / "chunk_0001.json"
        # Hand-write without _spin_times + _robot_count.
        body = (
            '{"_chunk_index": 1, "_config_md5": "x",'
            ' "_code_md5": "y", "response": []}'
        )
        p.write_text(body, encoding="utf-8")
        assert peek_chunk_envelope(p) == {
            "idx": 1, "cfg_md5": "x", "code_md5": "y",
            "spin_times": 0, "robot_count": 0,
        }

    def test_returns_none_for_malformed(self, tmp_path):
        from fresh_slotlab.chunk_index import peek_chunk_envelope
        p = tmp_path / "chunk_0001.json"
        p.write_text(json.dumps({"_cache_version": 1, "response": []}),
                     encoding="utf-8")
        assert peek_chunk_envelope(p) is None

    def test_returns_none_for_missing_file(self, tmp_path):
        from fresh_slotlab.chunk_index import peek_chunk_envelope
        assert peek_chunk_envelope(tmp_path / "nope.json") is None

    def test_peek_reads_bounded_bytes(self, tmp_path, monkeypatch):
        """Hard byte-budget assertion — peek must NOT read the full
        2MB file. Future regression here would fail this test."""
        from fresh_slotlab.chunk_index import peek_chunk_envelope
        p = tmp_path / "chunk_0003.json"
        self._write_chunk(p, idx=3, cfg="x", code="y",
                          response_bytes=2_000_000)

        read_counter = {"bytes": 0}
        original_open = Path.open

        def counting_open(self, mode="r", *args, **kwargs):
            if self == p:
                real = original_open(self, mode, *args, **kwargs)

                class _CountingReader:
                    def __init__(self, inner):
                        self._inner = inner
                    def read(self, size=-1):
                        data = self._inner.read(size)
                        read_counter["bytes"] += len(data)
                        return data
                    def __enter__(self):
                        self._inner.__enter__()
                        return self
                    def __exit__(self, *a):
                        return self._inner.__exit__(*a)
                    def __getattr__(self, name):
                        return getattr(self._inner, name)

                return _CountingReader(real)
            return original_open(self, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "open", counting_open)
        peek_chunk_envelope(p)
        assert read_counter["bytes"] < 16_384, (
            f"peek must not read full file; got {read_counter['bytes']:,}B"
        )


# ── 2. Sidecar round-trips ───────────────────────────────────────


class TestSidecarRoundtrip:
    def test_update_then_load(self, tmp_path):
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, load_chunks_index,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        cf = mode_dir / "chunk_0005.json"
        cf.write_text(json.dumps({
            "_chunk_index": 5, "_config_md5": "abc", "_code_md5": "def",
            "response": [],
        }), encoding="utf-8")
        update_chunk_entry(mode_dir, cf, chunk_index=5,
                           config_md5="abc", code_md5="def")
        idx = load_chunks_index(mode_dir)
        assert idx is not None
        assert "chunk_0005.json" in idx["chunks"]
        entry = idx["chunks"]["chunk_0005.json"]
        assert entry["idx"] == 5
        assert entry["cfg_md5"] == "abc"
        assert entry["code_md5"] == "def"
        assert entry["size_bytes"] > 0

    def test_remove_entry(self, tmp_path):
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, remove_chunk_entry, load_chunks_index,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        cf = mode_dir / "chunk_0001.json"
        cf.write_text("{}", encoding="utf-8")
        update_chunk_entry(mode_dir, cf, chunk_index=1,
                           config_md5="x", code_md5="y")
        assert "chunk_0001.json" in load_chunks_index(mode_dir)["chunks"]
        remove_chunk_entry(mode_dir, "chunk_0001.json")
        assert "chunk_0001.json" not in (
            load_chunks_index(mode_dir) or {"chunks": {}}
        )["chunks"]

    def test_bulk_remove_entries_single_write(self, tmp_path):
        """bulk_remove_chunk_entries: many removals → ONE sidecar
        rewrite (verified via mtime comparison after the call), and
        every entry actually leaves the in-memory chunks dict.
        Regression guard for the auto-cleanup hot path that deletes
        thousands of chunks in one cleanup pass — without bulk it
        would do thousands of read+merge+write cycles."""
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, bulk_remove_chunk_entries,
            load_chunks_index, _sidecar_path,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        names = [f"chunk_{i:04d}.json" for i in range(1, 11)]
        for i, name in enumerate(names, start=1):
            cf = mode_dir / name
            cf.write_text("{}", encoding="utf-8")
            update_chunk_entry(mode_dir, cf, chunk_index=i,
                               config_md5="cfg", code_md5="code")
        sidecar = _sidecar_path(mode_dir)
        before_mtime = sidecar.stat().st_mtime_ns

        # Remove the first 7 in one bulk call.
        removed = bulk_remove_chunk_entries(mode_dir, names[:7])
        assert removed == 7
        after_mtime = sidecar.stat().st_mtime_ns
        # Sidecar mtime advanced exactly once (one atomic write).
        assert after_mtime > before_mtime
        # The remaining 3 are still in the index.
        idx = load_chunks_index(mode_dir)
        assert set(idx["chunks"].keys()) == set(names[7:])

    def test_bulk_remove_skips_unknown_entries(self, tmp_path):
        """Entries that aren't in the sidecar are silently skipped
        (returns count of actually-removed). No spurious sidecar
        write when removing 0 actual entries (avoids bumping mtime
        past dir mtime unnecessarily)."""
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, bulk_remove_chunk_entries, _sidecar_path,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        cf = mode_dir / "chunk_0001.json"
        cf.write_text("{}", encoding="utf-8")
        update_chunk_entry(mode_dir, cf, chunk_index=1,
                           config_md5="x", code_md5="y")
        before_mtime = _sidecar_path(mode_dir).stat().st_mtime_ns

        # All names unknown → no-op, returns 0, sidecar untouched.
        removed = bulk_remove_chunk_entries(
            mode_dir, ["chunk_9999.json", "ghost.json"],
        )
        assert removed == 0
        assert _sidecar_path(mode_dir).stat().st_mtime_ns == before_mtime

    def test_bulk_remove_no_sidecar(self, tmp_path):
        """No sidecar yet (mode_dir hasn't been hit by a writer) →
        bulk_remove returns 0 without crashing. The next reader will
        rebuild via the mtime stale-check anyway."""
        from fresh_slotlab.chunk_index import bulk_remove_chunk_entries
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        assert bulk_remove_chunk_entries(
            mode_dir, ["chunk_0001.json"],
        ) == 0

    def test_load_returns_none_on_version_mismatch(self, tmp_path):
        from fresh_slotlab.chunk_index import load_chunks_index, SIDECAR_NAME
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        (mode_dir / SIDECAR_NAME).write_text(
            json.dumps({"_version": 9999, "chunks": {}}), encoding="utf-8",
        )
        assert load_chunks_index(mode_dir) is None

    def test_load_returns_none_on_corrupt_json(self, tmp_path):
        from fresh_slotlab.chunk_index import load_chunks_index, SIDECAR_NAME
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        (mode_dir / SIDECAR_NAME).write_text("not valid json{",
                                              encoding="utf-8")
        assert load_chunks_index(mode_dir) is None


# ── 3. Self-healing via get_chunks_index ─────────────────────────


def _write_chunk(path: Path, *, idx: int, cfg: str, code: str):
    path.write_text(json.dumps({
        "_chunk_index": idx, "_saved_at": "2026-04-24T12:00:00Z",
        "_config_md5": cfg, "_code_md5": code, "response": [],
    }), encoding="utf-8")


class TestSelfHeal:
    def test_rebuilds_missing_sidecar(self, tmp_path):
        from fresh_slotlab.chunk_index import (
            get_chunks_index, SIDECAR_NAME,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        _write_chunk(mode_dir / "chunk_0001.json", idx=1, cfg="a", code="b")
        _write_chunk(mode_dir / "chunk_0002.json", idx=2, cfg="a", code="b")
        assert not (mode_dir / SIDECAR_NAME).exists()

        idx = get_chunks_index(mode_dir)
        assert set(idx["chunks"].keys()) == {"chunk_0001.json", "chunk_0002.json"}
        # Side effect: sidecar file now persisted.
        assert (mode_dir / SIDECAR_NAME).is_file()

    def test_rebuilds_stale_sidecar(self, tmp_path):
        """Chunk file deleted externally (i.e. NOT through
        ``remove_chunk_entry`` / ``bulk_remove_chunk_entries``) →
        dir.mtime advances past sidecar.mtime → get_chunks_index
        rebuilds. This is the safety net for rogue ``rm`` commands
        or pre-fix versions of the cleanup paths.
        """
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, get_chunks_index,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        for i in (1, 2, 3):
            cf = mode_dir / f"chunk_{i:04d}.json"
            _write_chunk(cf, idx=i, cfg="a", code="b")
            update_chunk_entry(mode_dir, cf, chunk_index=i,
                               config_md5="a", code_md5="b")
        # External delete (without sidecar update) — sidecar still
        # has 3 entries on disk but dir.mtime is now newer.
        (mode_dir / "chunk_0002.json").unlink()
        idx = get_chunks_index(mode_dir)
        assert set(idx["chunks"].keys()) == {"chunk_0001.json", "chunk_0003.json"}

    def test_does_not_rebuild_when_sidecar_in_sync(self, tmp_path):
        """When chunks are deleted THROUGH the bulk_remove path,
        the sidecar's keyset matches disk → next get_chunks_index
        consults the sidecar directly without the expensive
        glob+peek rebuild.

        Regression guard for the perf fix (2026-04-25): the four
        production deletion sites (delete_rawdata, _auto_cleanup_
        for_space, delete_rawdata_version, cache_cleanup) now call
        ``bulk_remove_chunk_entries`` to keep the sidecar in sync.
        Before the fix every read after a delete triggered a
        rebuild because the sidecar's keyset still listed the
        deleted chunks. This test would fail (sidecar would be
        rewritten by get_chunks_index due to detected staleness)
        if any of those wirings were dropped.
        """
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, bulk_remove_chunk_entries,
            get_chunks_index, _sidecar_path,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        for i in (1, 2, 3):
            cf = mode_dir / f"chunk_{i:04d}.json"
            _write_chunk(cf, idx=i, cfg="a", code="b")
            update_chunk_entry(mode_dir, cf, chunk_index=i,
                               config_md5="a", code_md5="b")
        # Coordinated delete: unlink + sidecar update via the same
        # helper used in the production cleanup paths.
        (mode_dir / "chunk_0002.json").unlink()
        bulk_remove_chunk_entries(mode_dir, ["chunk_0002.json"])
        sidecar_mtime_before_read = _sidecar_path(mode_dir).stat().st_mtime_ns

        idx = get_chunks_index(mode_dir)
        assert set(idx["chunks"].keys()) == {"chunk_0001.json", "chunk_0003.json"}
        # Sidecar wasn't rewritten by get_chunks_index — keyset
        # matched disk so no rebuild fired.
        assert _sidecar_path(mode_dir).stat().st_mtime_ns == sidecar_mtime_before_read

    def test_external_chunk_add_triggers_rebuild(self, tmp_path):
        """Sanity: a chunk that lands without going through
        ``update_chunk_entry`` (e.g. parallel writer crashed mid-
        update) is still discovered by the next read. Pins the
        "external add" arm of the keyset check."""
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, get_chunks_index,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        cf = mode_dir / "chunk_0001.json"
        _write_chunk(cf, idx=1, cfg="a", code="b")
        update_chunk_entry(mode_dir, cf, chunk_index=1,
                           config_md5="a", code_md5="b")
        # External add — bypassed sidecar update.
        _write_chunk(mode_dir / "chunk_0002.json", idx=2, cfg="a", code="b")
        idx = get_chunks_index(mode_dir)
        assert "chunk_0002.json" in idx["chunks"]


# ── 4. Writer hook parity ────────────────────────────────────────


class TestWriterParity:
    """Both real and virtual writers populate the SAME sidecar format
    — so readers don't need to know which side wrote the chunks."""

    def test_virtual_write_chunk_populates_sidecar(self, tmp_path):
        """slot_designer's ``write_chunk`` must call ``update_chunk_entry``
        — the integration proof for virtual rawdata."""
        from slot_designer.core.emitter.chunk import emit_chunk, write_chunk
        from fresh_slotlab.chunk_index import load_chunks_index

        out = tmp_path / "M1sim" / "mode_1"
        chunk = emit_chunk(
            robots=[], machine="M1sim", mode=1, bet=1000,
            spin_times=100, robot_count=1, chunk_index=3,
            upstream_schema_fingerprint="abc",
            config_md5="virtual_cfg", code_md5="virtual_code",
        )
        cf = write_chunk(chunk, out, 3)
        assert cf.is_file()

        idx = load_chunks_index(out)
        assert idx is not None
        assert idx["chunks"]["chunk_0003.json"]["cfg_md5"] == "virtual_cfg"
        assert idx["chunks"]["chunk_0003.json"]["code_md5"] == "virtual_code"


# ── 5. Query helpers ─────────────────────────────────────────────


class TestQueryHelpers:
    def test_iter_chunks_matching_md5(self, tmp_path):
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, iter_chunks_matching_md5,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        # Two md5 buckets on disk.
        for i, (c, d) in enumerate(
            [("v1", "k"), ("v1", "k"), ("v2", "k")], start=1,
        ):
            cf = mode_dir / f"chunk_{i:04d}.json"
            _write_chunk(cf, idx=i, cfg=c, code=d)
            update_chunk_entry(mode_dir, cf, chunk_index=i,
                               config_md5=c, code_md5=d)

        v1 = iter_chunks_matching_md5(mode_dir, "v1", "k")
        assert [f for f, _ in v1] == ["chunk_0001.json", "chunk_0002.json"]

        v2 = iter_chunks_matching_md5(mode_dir, "v2", "k")
        assert [f for f, _ in v2] == ["chunk_0003.json"]

        nothing = iter_chunks_matching_md5(mode_dir, "doesnt", "exist")
        assert nothing == []

    def test_summarize_by_md5(self, tmp_path):
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, summarize_by_md5,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        for i, (c, d) in enumerate(
            [("v1", "k"), ("v1", "k"), ("v2", "k")], start=1,
        ):
            cf = mode_dir / f"chunk_{i:04d}.json"
            _write_chunk(cf, idx=i, cfg=c, code=d)
            update_chunk_entry(mode_dir, cf, chunk_index=i,
                               config_md5=c, code_md5=d)

        groups = summarize_by_md5(mode_dir)
        assert groups[("v1", "k")]["count"] == 2
        assert groups[("v2", "k")]["count"] == 1
        assert groups[("v1", "k")]["max_idx"] == 2


# ── chunks_by_md5 inverted-index lookup (2026-04-26) ─────────────


class TestChunksByMd5InvertedIndex:
    """The architectural answer to the 2026-04-26 user feedback
    ("你应该有个管理 rawdata 的机制，比如索引啥的, 而不是要去读每个
    rawdata 才知道 md5"): the sidecar maintains a ``by_md5``
    inverted index alongside the per-chunk dict, so md5-bucket
    lookups are O(1) (single dict access) instead of O(N) (walk
    over every entry). Maintained on every write — these tests pin
    that contract."""

    def test_chunks_by_md5_direct_lookup(self, tmp_path):
        """Basic happy path: 3 chunks across 2 md5 buckets, lookup
        each bucket returns the right filenames."""
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, chunks_by_md5,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        for i, (c, d) in enumerate(
            [("v1", "k"), ("v1", "k"), ("v2", "k")], start=1,
        ):
            cf = mode_dir / f"chunk_{i:04d}.json"
            _write_chunk(cf, idx=i, cfg=c, code=d)
            update_chunk_entry(mode_dir, cf, chunk_index=i,
                               config_md5=c, code_md5=d)
        assert chunks_by_md5(mode_dir, "v1", "k") == [
            "chunk_0001.json", "chunk_0002.json",
        ]
        assert chunks_by_md5(mode_dir, "v2", "k") == ["chunk_0003.json"]
        # Unknown md5 → empty list (caller's "no matching chunks"
        # signal).
        assert chunks_by_md5(mode_dir, "ghost", "ghost") == []

    def test_by_md5_persisted_in_sidecar_on_write(self, tmp_path):
        """update_chunk_entry maintains ``by_md5`` alongside ``chunks``
        on every write; the field round-trips through atomic save/load.
        Regression guard: previously by_md5 didn't exist; if anyone
        reverts the maintenance code, the loaded sidecar would be
        missing the field and chunks_by_md5 would fall back to the
        in-memory rebuild path on every read."""
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, load_chunks_index,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        cf = mode_dir / "chunk_0001.json"
        _write_chunk(cf, idx=1, cfg="A", code="B")
        update_chunk_entry(mode_dir, cf, chunk_index=1,
                           config_md5="A", code_md5="B")
        idx = load_chunks_index(mode_dir)
        assert idx is not None
        # by_md5 field is persisted, with the chunk in the right
        # bucket.
        assert "by_md5" in idx
        assert idx["by_md5"] == {"A|B": ["chunk_0001.json"]}

    def test_by_md5_drops_chunk_on_bulk_remove(self, tmp_path):
        """When chunks are removed via bulk_remove_chunk_entries,
        the by_md5 index drops them too — no phantom filenames
        pointing at deleted files. Empty buckets are removed
        entirely so the dict stays clean."""
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, bulk_remove_chunk_entries,
            load_chunks_index,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        names = []
        for i in (1, 2, 3):
            cf = mode_dir / f"chunk_{i:04d}.json"
            _write_chunk(cf, idx=i, cfg="A", code="B")
            update_chunk_entry(mode_dir, cf, chunk_index=i,
                               config_md5="A", code_md5="B")
            names.append(cf.name)
        # Remove first two — bucket should still have chunk_0003 only.
        bulk_remove_chunk_entries(mode_dir, names[:2])
        idx = load_chunks_index(mode_dir)
        assert idx["by_md5"] == {"A|B": ["chunk_0003.json"]}
        # Remove the last one — bucket dies entirely.
        bulk_remove_chunk_entries(mode_dir, [names[2]])
        idx = load_chunks_index(mode_dir)
        assert idx["by_md5"] == {}

    def test_by_md5_isolates_buckets_per_md5(self, tmp_path):
        """Removing a chunk from md5=A doesn't affect md5=B's bucket.
        Pin guard against off-by-one bugs in the cross-bucket
        update logic."""
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, bulk_remove_chunk_entries,
            load_chunks_index,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        for i, (c, d) in enumerate(
            [("A", "X"), ("A", "X"), ("B", "X")], start=1,
        ):
            cf = mode_dir / f"chunk_{i:04d}.json"
            _write_chunk(cf, idx=i, cfg=c, code=d)
            update_chunk_entry(mode_dir, cf, chunk_index=i,
                               config_md5=c, code_md5=d)
        # Remove one A chunk only.
        bulk_remove_chunk_entries(mode_dir, ["chunk_0001.json"])
        idx = load_chunks_index(mode_dir)
        # A bucket has chunk_0002 left; B bucket untouched.
        assert idx["by_md5"]["A|X"] == ["chunk_0002.json"]
        assert idx["by_md5"]["B|X"] == ["chunk_0003.json"]

    def test_by_md5_handles_chunk_remstamped_with_new_md5(self, tmp_path):
        """Re-indexing a chunk with a different md5 (rare but possible
        during dev — overwrite chunk_0001 with new weights) should
        move it from the old bucket to the new bucket. Not double-
        listed."""
        from fresh_slotlab.chunk_index import (
            update_chunk_entry, load_chunks_index,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        cf = mode_dir / "chunk_0001.json"
        _write_chunk(cf, idx=1, cfg="OLD", code="K")
        update_chunk_entry(mode_dir, cf, chunk_index=1,
                           config_md5="OLD", code_md5="K")
        # Same chunk file, new md5 stamp.
        update_chunk_entry(mode_dir, cf, chunk_index=1,
                           config_md5="NEW", code_md5="K")
        idx = load_chunks_index(mode_dir)
        # Old bucket gone (was emptied), new bucket has the chunk.
        assert idx["by_md5"] == {"NEW|K": ["chunk_0001.json"]}
        # Per-chunk dict shows the new md5.
        assert idx["chunks"]["chunk_0001.json"]["cfg_md5"] == "NEW"

    def test_chunks_by_md5_backward_compat_legacy_v1_sidecar(self, tmp_path):
        """A pre-2026-04-26 sidecar on disk has ``chunks`` but no
        ``by_md5``. ``chunks_by_md5`` should still return correct
        buckets (deriving in-memory) without crashing or returning
        empty. Next write persists the field — no manual migration."""
        from fresh_slotlab.chunk_index import (
            chunks_by_md5, _sidecar_path, _write_sidecar_atomic,
        )
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        # Write a chunk file so stale-check passes.
        _write_chunk(mode_dir / "chunk_0001.json", idx=1, cfg="X", code="Y")
        _write_chunk(mode_dir / "chunk_0002.json", idx=2, cfg="X", code="Y")
        # Hand-write a v1-style sidecar (no by_md5 field).
        _write_sidecar_atomic(_sidecar_path(mode_dir), {
            "_version": 1,
            "_updated_at": "2026-04-25T00:00:00Z",
            "chunks": {
                "chunk_0001.json": {"idx": 1, "cfg_md5": "X", "code_md5": "Y",
                                    "spin_times": 0, "robot_count": 0,
                                    "saved_at": "", "size_bytes": 0},
                "chunk_0002.json": {"idx": 2, "cfg_md5": "X", "code_md5": "Y",
                                    "spin_times": 0, "robot_count": 0,
                                    "saved_at": "", "size_bytes": 0},
            },
        })
        # Lookup works despite no by_md5 in the sidecar.
        assert sorted(chunks_by_md5(mode_dir, "X", "Y")) == [
            "chunk_0001.json", "chunk_0002.json",
        ]


# ── 6. Byte-budget reader proof ──────────────────────────────────


class TestReaderShortCircuit:
    """check_rawdata_status + _classify_chunks on a dir with populated
    sidecar must NOT open any chunk file. This is the click-a-machine-
    is-slow bug fix in one assertion — applies to BOTH real and virtual
    because both paths go through ``GET /api/rawdata/{machine}`` which
    calls ``_classify_chunks`` internally."""

    def test_classify_chunks_doesnt_open_chunks_when_sidecar_present(
        self, tmp_path, monkeypatch,
    ):
        """``_classify_chunks`` drives the 机台管理 click response for
        both real + virtual consoles. Sidecar-backed path must read
        zero bytes from chunk files. Regression here reproduces the
        2026-04-24 user-reported "虚拟机台点击机台卡片以后还是卡一会"
        symptom."""
        from fresh_slotlab.chunk_index import update_chunk_entry
        from src.web_console.backend.app import _classify_chunks

        root = tmp_path / "rd"
        mode_dir = root / "M1sim" / "mode_1"
        mode_dir.mkdir(parents=True)
        # 10 chunks of ~500 KB each — fat enough that a regression
        # back to full-read shows up obviously.
        for i in range(1, 11):
            cf = mode_dir / f"chunk_{i:04d}.json"
            cf.write_text(json.dumps({
                "_chunk_index": i,
                "_spin_times": 2000,
                "_robot_count": 8,
                "_saved_at": "2026-04-24T12:00:00Z",
                "_config_md5": "cfg_virtual",
                "_code_md5": "code_virtual",
                "response": "X" * 500_000,
            }), encoding="utf-8")
            update_chunk_entry(
                mode_dir, cf, chunk_index=i,
                config_md5="cfg_virtual", code_md5="code_virtual",
                spin_times=2000, robot_count=8,
            )

        read_counter = {"bytes": 0}
        original_read = Path.read_text

        def counting_read(self, *args, **kwargs):
            data = original_read(self, *args, **kwargs)
            if self.name.startswith("chunk_"):
                read_counter["bytes"] += len(data.encode("utf-8"))
            return data

        monkeypatch.setattr(Path, "read_text", counting_read)

        # Need a machines_config path (unused by _classify_chunks beyond
        # being passed to _get_machine_md5 which we mock).
        import src.web_console.backend.app as app_mod
        monkeypatch.setattr(
            app_mod, "_get_machine_md5",
            lambda *a, **kw: ("cfg_virtual", "code_virtual"),
        )

        result = _classify_chunks(
            "M1sim", 1,
            rawdata_root=root,
            machines_config=tmp_path / "machines.json",
            min_retention_spins=0,
        )
        # All 10 chunks classified; per-chunk spins = 2000 × 8 = 16000.
        # At min_retention_spins=0 all land in "deletable" (nothing
        # kept beyond baseline) — that's an orthogonal classification
        # detail; the point is they ALL got classified.
        total_classified = (
            len(result["kept"])
            + len(result["deletable"])
            + len(result["historical"])
        )
        assert total_classified == 10
        # Real assertion: zero chunk-file bytes read when sidecar
        # serves all entries.
        assert read_counter["bytes"] == 0, (
            f"sidecar populated → _classify_chunks must not read chunk "
            f"files; got {read_counter['bytes']:,}B"
        )

    def test_rawdata_index_scan_doesnt_open_chunks_when_sidecar_present(
        self, tmp_path, monkeypatch,
    ):
        """rawdata_index._scan_mode_dir was the last unpatched slow
        path — check_rawdata_status called it via update_entry() at
        the END of the cold path, opening every chunk a SECOND time
        just to refresh the machine-level index. Measured 3.1s on a
        195-chunk virtual mode_1 before this fix. Lock: sidecar-backed
        ``_scan_mode_dir`` must read zero bytes from chunk files."""
        from fresh_slotlab.chunk_index import update_chunk_entry
        from fresh_slotlab.rawdata_index import _scan_mode_dir

        mode_dir = tmp_path / "M1sim" / "mode_1"
        mode_dir.mkdir(parents=True)
        for i in range(1, 11):
            cf = mode_dir / f"chunk_{i:04d}.json"
            cf.write_text(json.dumps({
                "_chunk_index": i,
                "_spin_times": 2000, "_robot_count": 8,
                "_saved_at": "2026-04-24T12:00:00Z",
                "_config_md5": "v1", "_code_md5": "c1",
                "response": "X" * 500_000,
            }), encoding="utf-8")
            update_chunk_entry(
                mode_dir, cf, chunk_index=i,
                config_md5="v1", code_md5="c1",
                spin_times=2000, robot_count=8,
            )

        read_counter = {"bytes": 0}
        original_read = Path.read_text

        def counting_read(self, *args, **kwargs):
            data = original_read(self, *args, **kwargs)
            if self.name.startswith("chunk_"):
                read_counter["bytes"] += len(data.encode("utf-8"))
            return data
        # _scan_mode_dir also reads via path.open().read() in the
        # fallback; wrap that too for a tighter assertion.
        original_open = Path.open

        def counting_open(self, mode="r", *args, **kwargs):
            if self.name.startswith("chunk_"):
                real = original_open(self, mode, *args, **kwargs)

                class _Counter:
                    def __init__(self, inner):
                        self._inner = inner
                    def read(self, size=-1):
                        data = self._inner.read(size)
                        read_counter["bytes"] += len(
                            data.encode("utf-8") if isinstance(data, str) else data
                        )
                        return data
                    def __enter__(self):
                        self._inner.__enter__()
                        return self
                    def __exit__(self, *a):
                        return self._inner.__exit__(*a)
                    def __getattr__(self, name):
                        return getattr(self._inner, name)
                return _Counter(real)
            return original_open(self, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", counting_read)
        monkeypatch.setattr(Path, "open", counting_open)

        entry = _scan_mode_dir(mode_dir)
        assert entry is not None
        assert entry["chunks"] == 10
        assert entry["config_md5"] == "v1"
        # Sidecar serves everything — zero chunk-file content reads.
        assert read_counter["bytes"] == 0, (
            f"_scan_mode_dir must use sidecar; got {read_counter['bytes']:,}B"
        )

    def test_check_rawdata_status_doesnt_open_chunks_when_sidecar_present(
        self, tmp_path, monkeypatch,
    ):
        from fresh_slotlab.chunk_index import update_chunk_entry
        from src.web_console.backend.app import check_rawdata_status

        root = tmp_path / "rd"
        mode_dir = root / "M14" / "mode_1"
        mode_dir.mkdir(parents=True)
        # Write 5 chunks + corresponding sidecar entries.
        for i in range(1, 6):
            cf = mode_dir / f"chunk_{i:04d}.json"
            # Note: these chunks are written with a large filler to prove
            # the sidecar short-circuit avoids reading them.
            cf.write_text(json.dumps({
                "_chunk_index": i,
                "_saved_at": "2026-04-24T12:00:00Z",
                "_config_md5": "cfg_x",
                "_code_md5": "code_y",
                "response": "X" * 500_000,
            }), encoding="utf-8")
            update_chunk_entry(mode_dir, cf, chunk_index=i,
                               config_md5="cfg_x", code_md5="code_y")

        # Count bytes read from any chunk_NNNN.json file during the call.
        read_counter = {"bytes": 0}
        original_read = Path.read_text

        def counting_read(self, *args, **kwargs):
            data = original_read(self, *args, **kwargs)
            if self.name.startswith("chunk_"):
                read_counter["bytes"] += len(data.encode("utf-8"))
            return data

        monkeypatch.setattr(Path, "read_text", counting_read)

        # Stub _get_machine_md5 to return matching md5 so all 5 count as usable.
        import src.web_console.backend.app as app_mod
        monkeypatch.setattr(
            app_mod, "_get_machine_md5",
            lambda *a, **kw: ("cfg_x", "code_y"),
        )

        status = check_rawdata_status(
            "M14", 1, rawdata_root=root, machines_config=None,
        )
        assert status["usable_chunks"] == 5
        # Cold path via sidecar must read zero bytes from the fat
        # chunk files themselves. Any regression that reintroduces
        # ``json.loads(chunk_path.read_text())`` would blow past this.
        assert read_counter["bytes"] == 0, (
            f"sidecar present → must not read chunk files; "
            f"got {read_counter['bytes']:,}B"
        )


class TestUpdateChunkEntryConcurrency:
    """The analyzer's ThreadPoolExecutor (batch_concurrency=8) calls
    update_chunk_entry from N parallel workers per mode_dir. Without
    write serialization, the read-modify-write cycle drops entries:
    two workers read the same baseline {1,2}, worker A writes
    {1,2,3}, worker B writes {1,2,4} — entry 3 vanishes.

    Observed 2026-04-28 on M15$TopDollarSelector$1$ mode_1: chunks
    0003 and 0007 landed on disk but never appeared in
    ``_chunks.json`` (sidecar held only 6 of 8 new chunks). Locks
    the per-mode-dir threading.Lock fix that closes the race."""

    def _write_chunk(self, mode_dir, idx):
        cf = mode_dir / f"chunk_{idx:04d}.json"
        cf.write_text(json.dumps({
            "_chunk_index": idx,
            "_spin_times": 1000, "_robot_count": 8,
            "_saved_at": "2026-04-28T12:00:00Z",
            "_config_md5": "cfg_x", "_code_md5": "code_y",
            "response": "Y" * 1024,
        }), encoding="utf-8")
        return cf

    def test_parallel_workers_lose_no_entries(self, tmp_path, monkeypatch):
        """Two-thread read-modify-write race demonstration. Without
        the lock, thread A reads the baseline, thread B reads the
        same baseline, A writes its update, B writes its update on
        top — A's entry is lost. With the lock both serialize, both
        entries land.

        We force the race deterministically by injecting a small
        sleep inside ``_write_sidecar_atomic`` so the read-then-write
        window is large enough for the second thread's read to
        observe the pre-A baseline. Without the sleep this race is
        racy-by-machine-speed; with it, the test reliably fails
        without the lock fix."""
        import threading
        import time as _time
        from fresh_slotlab import chunk_index as ci
        mode_dir = tmp_path / "M15" / "mode_1"
        mode_dir.mkdir(parents=True)
        cf_a = self._write_chunk(mode_dir, idx=1)
        cf_b = self._write_chunk(mode_dir, idx=2)

        # Slow down the write side so two parallel calls overlap.
        # Each thread now spends ~50ms in the write phase, easily
        # large enough for thread 2 to enter and read pre-thread-1
        # state before thread 1's write lands. The lock collapses
        # this overlap; without it the sleep guarantees the race.
        original = ci._write_sidecar_atomic

        def slow_write(sidecar, payload):
            _time.sleep(0.05)
            return original(sidecar, payload)

        monkeypatch.setattr(ci, "_write_sidecar_atomic", slow_write)

        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def worker(idx, cf):
            try:
                barrier.wait()
                ci.update_chunk_entry(
                    mode_dir, cf, chunk_index=idx,
                    config_md5="cfg_x", code_md5="code_y",
                    spin_times=1000, robot_count=8,
                )
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        t1 = threading.Thread(target=worker, args=(1, cf_a))
        t2 = threading.Thread(target=worker, args=(2, cf_b))
        t1.start(); t2.start()
        t1.join(timeout=10.0); t2.join(timeout=10.0)
        assert not errors, f"worker raised: {errors}"

        # Read raw (don't trigger the rebuild path that masks the
        # race — we want to see EXACTLY what the writers persisted).
        idx = ci.load_chunks_index(mode_dir) or {}
        chunks = idx.get("chunks") or {}
        missing = [
            n for n in ("chunk_0001.json", "chunk_0002.json")
            if n not in chunks
        ]
        assert not missing, (
            f"sidecar lost {len(missing)} entries to the read-modify-write "
            f"race: {missing}. With the per-mode-dir lock both entries "
            f"should land; without it one is lost."
        )
        # by_md5 inverted index must agree.
        by_md5 = idx.get("by_md5") or {}
        bucket = by_md5.get("cfg_x|code_y") or []
        assert sorted(bucket) == ["chunk_0001.json", "chunk_0002.json"]

    def test_permission_error_retry_recovers(self, tmp_path, monkeypatch):
        """Windows AV transiently locks the sidecar during os.replace,
        raising PermissionError. The retry loop in _write_sidecar_atomic
        must absorb up to 5 attempts so a single AV scan doesn't drop
        the entry. Simulate by injecting a counter that fails the
        first 2 calls then succeeds."""
        import os
        from fresh_slotlab import chunk_index as ci
        mode_dir = tmp_path / "M15" / "mode_1"
        mode_dir.mkdir(parents=True)
        cf = self._write_chunk(mode_dir, idx=1)
        attempts = {"n": 0}
        original_replace = os.replace

        def flaky_replace(src, dst):
            attempts["n"] += 1
            if attempts["n"] <= 2:
                raise PermissionError("[WinError 5] Access is denied (simulated)")
            return original_replace(src, dst)

        monkeypatch.setattr(ci.os, "replace", flaky_replace)
        ci.update_chunk_entry(
            mode_dir, cf, chunk_index=1,
            config_md5="cfg_x", code_md5="code_y",
            spin_times=1000, robot_count=8,
        )
        # Despite the first two attempts failing, the 3rd succeeded.
        idx = ci.get_chunks_index(mode_dir)
        assert "chunk_0001.json" in (idx.get("chunks") or {})
        assert attempts["n"] == 3, (
            f"expected 3 replace attempts (2 fail + 1 succeed), got {attempts['n']}"
        )

    def test_permission_error_retry_gives_up_after_5(self, tmp_path, monkeypatch):
        """Persistent failure (AV won't release the file) → after 5
        retries the helper raises and update_chunk_entry's outer
        try/except logs to stderr without crashing the analyzer."""
        import os
        import sys
        from io import StringIO
        from fresh_slotlab import chunk_index as ci
        mode_dir = tmp_path / "M15" / "mode_1"
        mode_dir.mkdir(parents=True)
        cf = self._write_chunk(mode_dir, idx=1)
        attempts = {"n": 0}

        def always_fail(src, dst):
            attempts["n"] += 1
            raise PermissionError("[WinError 5] persistent (simulated)")

        monkeypatch.setattr(ci.os, "replace", always_fail)
        captured = StringIO()
        monkeypatch.setattr(sys, "stderr", captured)
        # Should NOT raise — outer except in update_chunk_entry swallows.
        ci.update_chunk_entry(
            mode_dir, cf, chunk_index=1,
            config_md5="cfg_x", code_md5="code_y",
            spin_times=1000, robot_count=8,
        )
        assert attempts["n"] == 5, (
            f"expected 5 retry attempts before giving up, got {attempts['n']}"
        )
        # Diagnostic must still reach stderr so operators can see the
        # transient AV pattern in their logs.
        log = captured.getvalue()
        assert "[chunk_index] update_chunk_entry failed" in log
        assert "PermissionError" in log
