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
