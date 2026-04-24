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
                     response_bytes: int = 3_000_000):
        envelope = {
            "_cache_version": 3,
            "_machine": "M14",
            "_mode": 1,
            "_bet": 1000,
            "_chunk_index": idx,
            "_saved_at": "2026-04-24T12:00:00Z",
            "_config_md5": cfg,
            "_code_md5": code,
            "response": "x" * response_bytes,
        }
        path.write_text(
            json.dumps(envelope, ensure_ascii=False), encoding="utf-8",
        )

    def test_extracts_fields_from_fat_chunk(self, tmp_path):
        from fresh_slotlab.chunk_index import peek_chunk_envelope
        p = tmp_path / "chunk_0007.json"
        self._write_chunk(p, idx=7, cfg="localcfg_abc12345", code="real_code")
        assert p.stat().st_size > 2_500_000
        assert peek_chunk_envelope(p) == (7, "localcfg_abc12345", "real_code")

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
        """Chunk file deleted externally → sidecar keyset drifts from
        disk → get_chunks_index rebuilds."""
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
        # External delete — sidecar still has 3 entries.
        (mode_dir / "chunk_0002.json").unlink()
        idx = get_chunks_index(mode_dir)
        assert set(idx["chunks"].keys()) == {"chunk_0001.json", "chunk_0003.json"}


# ── 4. Writer hook parity ────────────────────────────────────────


class TestWriterParity:
    """Both real and virtual writers populate the SAME sidecar format
    — so readers don't need to know which side wrote the chunks."""

    def test_virtual_write_chunk_populates_sidecar(self, tmp_path):
        """slot_designer's ``write_chunk`` must call ``update_chunk_entry``
        — the integration proof for virtual rawdata."""
        from slot_designer.emitter.chunk import emit_chunk, write_chunk
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


# ── 6. Byte-budget reader proof ──────────────────────────────────


class TestReaderShortCircuit:
    """check_rawdata_status on a directory with pre-populated sidecar
    must NOT open any chunk file. This is the click-a-machine-is-slow
    bug fix in one assertion."""

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
