"""Tests for fresh_slotlab.rawdata_index (P0.2 session 2026-04).

The index is a derived cache sitting at `<rawdata_root>/_index.json`
that lets `check_rawdata_status` answer UI status queries in O(1) file
opens instead of scanning every chunk envelope.

Covers:
- load_index: missing file, corrupt JSON, version mismatch → empty shell
- update_entry: full scan + atomic persist; empty dir removes entry
- remove_entry: targeted drop
- rebuild_full: walks all machine/mode subdirs
- atomic write leaves no `.tmp` leftovers on success
- `check_rawdata_status` fast-path: uses index when valid, falls back
  to scan when stale, self-heals the entry after cold path
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fresh_slotlab.rawdata_index import (
    INDEX_FILENAME,
    INDEX_VERSION,
    entry_key,
    load_index,
    rebuild_full,
    remove_entry,
    update_entry,
)
from fresh_slotlab.analyzer.core.writer import _save_chunk_cache as _real_save_chunk_cache


def _stub_md5_lookup(_machine: str) -> tuple[str, str]:
    """Stub for the lookup_machine_md5 kwarg required post-P2-B3 carve."""
    return ("", "")


def _save_chunk_cache(*args, **kwargs):
    """Wrapper defaulting lookup_machine_md5 + rawdata_index_update_entry.
    Pre-P2-B3 callsites passed 8 positional args + expected the writer to
    internally call rawdata_index.update_entry; post-P2-B3 both are DI."""
    kwargs.setdefault("lookup_machine_md5", _stub_md5_lookup)
    if "rawdata_index_update_entry" not in kwargs:
        from fresh_slotlab import rawdata_index as _ri
        kwargs["rawdata_index_update_entry"] = _ri.update_entry
    return _real_save_chunk_cache(*args, **kwargs)


from src.web_console.backend.app import check_rawdata_status


def _sample_response() -> list:
    return [
        {
            "roundResult": json.dumps(
                [{"BetAmount": 1000, "CurrentWin": 500, "SpinType": "Normal"}]
            )
        }
    ]


def _seed_chunks(
    rawdata_root: Path, machine: str, mode: int, count: int
) -> Path:
    """Write `count` valid v3 chunks in `<root>/<machine>/mode_<mode>/`."""
    mode_dir = rawdata_root / machine / f"mode_{mode}"
    mode_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        _save_chunk_cache(
            _sample_response(), i, machine, mode, 1000, 1000, 10, mode_dir
        )
    return mode_dir


class TestLoadIndex:
    def test_missing_file_returns_empty_shell(self, tmp_path: Path):
        d = load_index(tmp_path)
        assert d["_version"] == INDEX_VERSION
        assert d["entries"] == {}

    def test_corrupt_json_returns_empty(self, tmp_path: Path):
        (tmp_path / INDEX_FILENAME).write_text(
            "not valid json {{{", encoding="utf-8"
        )
        assert load_index(tmp_path)["entries"] == {}

    def test_version_mismatch_returns_empty(self, tmp_path: Path):
        (tmp_path / INDEX_FILENAME).write_text(
            json.dumps(
                {
                    "_version": 999,
                    "_updated_at": "x",
                    "entries": {"M1|1": {"chunks": 5}},
                }
            ),
            encoding="utf-8",
        )
        assert load_index(tmp_path)["entries"] == {}

    def test_missing_entries_key_returns_empty(self, tmp_path: Path):
        (tmp_path / INDEX_FILENAME).write_text(
            json.dumps({"_version": INDEX_VERSION}), encoding="utf-8"
        )
        assert load_index(tmp_path)["entries"] == {}


class TestUpdateEntry:
    def test_scans_and_persists_entry(self, tmp_path: Path):
        # _save_chunk_cache already calls update_entry internally,
        # so after seeding the index is expected to be populated.
        _seed_chunks(tmp_path, "M1", 1, count=3)
        idx = load_index(tmp_path)
        e = idx["entries"].get(entry_key("M1", 1))
        assert e is not None
        assert e["chunks"] == 3
        assert e["total_size_bytes"] > 0
        assert len(e["chunk_files"]) == 3
        assert e["config_md5"] == "" or isinstance(e["config_md5"], str)
        assert e["mixed_md5"] is False

    def test_explicit_call_overwrites_entry(self, tmp_path: Path):
        mode_dir = _seed_chunks(tmp_path, "M1", 1, count=2)
        # Drop a chunk externally, then call update_entry.
        list(mode_dir.glob("chunk_*.json"))[0].unlink()
        update_entry(tmp_path, "M1", 1, mode_dir)
        assert load_index(tmp_path)["entries"][entry_key("M1", 1)]["chunks"] == 1

    def test_empty_dir_removes_entry(self, tmp_path: Path):
        mode_dir = _seed_chunks(tmp_path, "M1", 1, count=1)
        for f in mode_dir.glob("chunk_*.json"):
            f.unlink()
        update_entry(tmp_path, "M1", 1, mode_dir)
        assert entry_key("M1", 1) not in load_index(tmp_path)["entries"]

    def test_no_tmp_leftover(self, tmp_path: Path):
        _seed_chunks(tmp_path, "M1", 1, count=1)
        assert not (tmp_path / f"{INDEX_FILENAME}.tmp").exists()


class TestRemoveEntry:
    def test_drops_named_entry(self, tmp_path: Path):
        _seed_chunks(tmp_path, "M1", 1, count=1)
        _seed_chunks(tmp_path, "M2", 1, count=1)
        remove_entry(tmp_path, "M1", 1)
        entries = load_index(tmp_path)["entries"]
        assert entry_key("M1", 1) not in entries
        assert entry_key("M2", 1) in entries

    def test_noop_when_entry_absent(self, tmp_path: Path):
        # No index file at all — must not raise.
        remove_entry(tmp_path, "M1", 1)


class TestRebuildFull:
    def test_walks_machine_mode_tree(self, tmp_path: Path):
        _seed_chunks(tmp_path, "M1", 1, count=2)
        _seed_chunks(tmp_path, "M1", 2, count=1)
        _seed_chunks(tmp_path, "M272", 5, count=4)
        # Nuke the index and rebuild from scratch.
        (tmp_path / INDEX_FILENAME).unlink(missing_ok=True)
        data = rebuild_full(tmp_path)
        assert set(data["entries"].keys()) == {
            entry_key("M1", 1),
            entry_key("M1", 2),
            entry_key("M272", 5),
        }
        assert data["entries"][entry_key("M272", 5)]["chunks"] == 4

    def test_skips_underscore_prefixed_dirs(self, tmp_path: Path):
        _seed_chunks(tmp_path, "M1", 1, count=1)
        # Simulate a sidecar dir (e.g. if someone puts _trash/ in rawdata)
        (tmp_path / "_stash").mkdir()
        (tmp_path / "_stash" / "mode_1").mkdir()
        data = rebuild_full(tmp_path)
        assert list(data["entries"].keys()) == [entry_key("M1", 1)]

    def test_empty_root_returns_empty(self, tmp_path: Path):
        data = rebuild_full(tmp_path)
        assert data["entries"] == {}


class TestCheckRawdataStatusIndexIntegration:
    def test_unverifiable_fast_path(self, tmp_path: Path, monkeypatch):
        # No machines.json → unverifiable path. Index should still be
        # consulted and give a usable count without opening chunks.
        _seed_chunks(tmp_path, "M1", 1, count=3)
        # Force _get_machine_md5 to return empty ("unverifiable")
        import src.web_console.backend.app as app
        monkeypatch.setattr(app, "_get_machine_md5", lambda *a, **kw: ("", ""))
        status = check_rawdata_status(
            "M1", 1, rawdata_root=tmp_path, machines_config=None
        )
        assert status["exists"]
        assert status["usable_chunks"] == 3
        assert status["unverifiable"] is True
        assert status["mismatch_chunks"] == 0

    def test_stale_index_falls_back_and_heals(self, tmp_path: Path, monkeypatch):
        # Seed 3 chunks, then delete one externally without updating
        # the index (simulates concurrent delete or crashed writer).
        mode_dir = _seed_chunks(tmp_path, "M1", 1, count=3)
        list(mode_dir.glob("chunk_*.json"))[-1].unlink()
        # Index still says 3. Cold path should detect (actual=2 ≠ idx=3),
        # rescan, AND update the entry so next read is correct.
        import src.web_console.backend.app as app
        monkeypatch.setattr(app, "_get_machine_md5", lambda *a, **kw: ("", ""))
        status = check_rawdata_status(
            "M1", 1, rawdata_root=tmp_path, machines_config=None
        )
        assert status["usable_chunks"] == 2  # authoritative
        # Index was healed — second call sees chunks=2 directly.
        assert load_index(tmp_path)["entries"][entry_key("M1", 1)]["chunks"] == 2

    def test_status_never_mutates_disk(self, tmp_path: Path, monkeypatch):
        # Post 2026-04-21: check_rawdata_status is read-only. Even when
        # called on a dir with md5-mismatched chunks (the old
        # auto_delete_mismatched=True scenario) NOTHING is unlinked.
        # md5 is a tag, not a destruction signal — deletions only
        # happen through cache-management paths.
        _seed_chunks(tmp_path, "M1", 1, count=2)
        import src.web_console.backend.app as app
        monkeypatch.setattr(app, "_get_machine_md5", lambda *a, **kw: ("", ""))
        status = check_rawdata_status(
            "M1", 1, rawdata_root=tmp_path, machines_config=None,
        )
        # Unverifiable upstream → treat as usable; no disk changes.
        assert status["usable_chunks"] == 2
        assert "deleted_paths" not in status
        # Chunks still on disk.
        chunk_files = sorted((tmp_path / "M1" / "mode_1").glob("chunk_*.json"))
        assert len(chunk_files) == 2

    def test_missing_dir_returns_empty_status(self, tmp_path: Path):
        # No machine dir at all — status says exists=False; index is
        # irrelevant since the dir check short-circuits.
        status = check_rawdata_status("Mghost", 1, rawdata_root=tmp_path)
        assert status["exists"] is False
        assert status["usable_chunks"] == 0
