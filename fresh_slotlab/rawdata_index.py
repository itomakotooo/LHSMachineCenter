"""Cached file-count/md5 index for rawdata directory trees.

Purpose: skip opening N chunk envelopes on every UI status refresh.
`check_rawdata_status` was reading 253 × 4 ≈ 1000+ envelope headers
per full-dashboard load; this module stores pre-aggregated per-
(machine, mode) state in a single file at the rawdata root, so the
common read path becomes one open.

Schema (file at `<rawdata_root>/_index.json`):
    {
      "_version": 1,
      "_updated_at": "2026-04-17T...",
      "entries": {
        "M14|1": {
          "chunks": 4,
          "total_size_bytes": 17_200_000,
          "last_saved_at": "2026-04-17T...",
          "config_md5": "4fcf...",
          "code_md5": "536f...",
          "chunk_files": ["chunk_0001.json", ...]
        },
        ...
      }
    }

Consistency model:
- The index is a *derived cache* — authoritative state is the on-disk
  chunks themselves.
- Writers (`update_entry`) do read-modify-write + os.replace; atomic
  per-process on same filesystem.
- Readers validate `entry.chunks` against the actual glob count; a
  mismatch triggers rescan + rewrite. This self-heals drift from
  failed writes, external deletion, or concurrent writers racing.
- On any decode error / missing file, fall back to "empty index" and
  let the next call rebuild.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INDEX_FILENAME = "_index.json"
INDEX_VERSION = 1


def entry_key(machine: str, mode: int) -> str:
    return f"{machine}|{mode}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _empty_index() -> dict[str, Any]:
    return {"_version": INDEX_VERSION, "_updated_at": _utc_now(), "entries": {}}


def load_index(rawdata_root: Path) -> dict[str, Any]:
    """Load the index file; return an empty shell on any failure.

    Doesn't raise — consumers treat missing/corrupt index as "no cache,
    fall back to filesystem scan" and let the next `update_entry` heal it.
    """
    p = rawdata_root / INDEX_FILENAME
    if not p.exists():
        return _empty_index()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "entries" not in data:
            return _empty_index()
        if data.get("_version") != INDEX_VERSION:
            # Future schema mismatch: treat as empty, will rebuild on
            # next write. Keeps forward-compat simple.
            return _empty_index()
        return data
    except (OSError, json.JSONDecodeError):
        return _empty_index()


def _save_index(rawdata_root: Path, data: dict[str, Any]) -> None:
    """Atomic write of the full index file (.tmp + os.replace)."""
    rawdata_root.mkdir(parents=True, exist_ok=True)
    data["_updated_at"] = _utc_now()
    target = rawdata_root / INDEX_FILENAME
    tmp = rawdata_root / f"{INDEX_FILENAME}.tmp"
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, target)
    except OSError:
        # Best-effort; clean up stray .tmp.
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _scan_mode_dir(chunk_dir: Path) -> dict[str, Any] | None:
    """Build a single entry from the on-disk chunks in a mode directory.

    Returns None when the dir has no chunks (caller should remove any
    stale entry rather than store {"chunks": 0}).

    Reads the per-chunk sidecar (``fresh_slotlab.chunk_index``) to
    avoid opening every chunk file — this is called once per
    ``check_rawdata_status`` call, and on a 195-chunk dir the old
    ``json.loads`` loop was a silent 3s cost behind click-a-machine.
    Sidecar miss for a given file falls through to the old per-file
    open so correctness stays intact on legacy envelopes.
    """
    chunks = sorted(chunk_dir.glob("chunk_*.json"))
    if not chunks:
        return None

    # Pre-load the per-chunk sidecar once. ``get_chunks_index`` auto-
    # rebuilds via 4KB peek per chunk when missing — cheap even on
    # cold starts.
    try:
        from fresh_slotlab.chunk_index import get_chunks_index
        sidecar_entries = get_chunks_index(chunk_dir).get("chunks") or {}
    except Exception:  # noqa: BLE001
        sidecar_entries = {}

    total_size = 0
    saved_ats: list[str] = []
    config_md5 = ""
    code_md5 = ""
    mixed_md5 = False
    names: list[str] = []
    for p in chunks:
        names.append(p.name)
        entry = sidecar_entries.get(p.name)
        if isinstance(entry, dict):
            total_size += int(entry.get("size_bytes", 0) or 0)
            sv = str(entry.get("saved_at", "") or "")
            cfg = str(entry.get("cfg_md5", "") or "")
            code = str(entry.get("code_md5", "") or "")
        else:
            # Sidecar miss — legacy chunk or mid-migration. Fall
            # through to the full file open for this one chunk only;
            # next sidecar rebuild will cover it.
            try:
                st = p.stat()
                total_size += st.st_size
            except OSError:
                continue
            try:
                with p.open("r", encoding="utf-8") as f:
                    data = json.loads(f.read())
            except (OSError, json.JSONDecodeError):
                continue
            sv = str(data.get("_saved_at", ""))
            cfg = str(data.get("_config_md5", ""))
            code = str(data.get("_code_md5", ""))

        if sv:
            saved_ats.append(sv)
        if not config_md5 and cfg:
            config_md5 = cfg
            code_md5 = code
        elif cfg and (cfg != config_md5 or code != code_md5):
            # Mixed md5 across chunks — record the first seen but flag.
            # Reader will fall back to full per-chunk scan in this case.
            mixed_md5 = True
    return {
        "chunks": len(chunks),
        "total_size_bytes": total_size,
        "last_saved_at": max(saved_ats) if saved_ats else "",
        "config_md5": config_md5,
        "code_md5": code_md5,
        "mixed_md5": mixed_md5,
        "chunk_files": names,
    }


def update_entry(
    rawdata_root: Path, machine: str, mode: int, chunk_dir: Path
) -> None:
    """Rescan one (machine, mode) dir and persist its entry atomically.

    Called after a successful chunk write so the index reflects the new
    file; also called by readers when the cached entry is stale. If the
    dir is empty (e.g. after all chunks were deleted), the entry is
    removed from the index.
    """
    try:
        entry = _scan_mode_dir(chunk_dir)
        data = load_index(rawdata_root)
        key = entry_key(machine, mode)
        if entry is None:
            data["entries"].pop(key, None)
        else:
            data["entries"][key] = entry
        _save_index(rawdata_root, data)
    except OSError:
        # Best-effort; stale index self-heals on next read.
        pass


def remove_entry(rawdata_root: Path, machine: str, mode: int) -> None:
    """Drop the entry for a (machine, mode) — e.g. after rawdata delete."""
    try:
        data = load_index(rawdata_root)
        data["entries"].pop(entry_key(machine, mode), None)
        _save_index(rawdata_root, data)
    except OSError:
        pass


def rebuild_full(rawdata_root: Path) -> dict[str, Any]:
    """Full scan: walk every machine/mode subdir and regenerate the index.

    Used by the `rebuild-rawdata-index` CLI / admin endpoint when the
    file got out of sync (batch delete done outside the app, manual
    file copies, etc.).
    """
    if not rawdata_root.is_dir():
        return _empty_index()
    data = _empty_index()
    for machine_dir in sorted(rawdata_root.iterdir()):
        if not machine_dir.is_dir() or machine_dir.name.startswith("_"):
            continue
        for mode_dir in sorted(machine_dir.iterdir()):
            if not mode_dir.is_dir() or not mode_dir.name.startswith("mode_"):
                continue
            try:
                mode_int = int(mode_dir.name.split("_")[1])
            except (IndexError, ValueError):
                continue
            entry = _scan_mode_dir(mode_dir)
            if entry is None:
                continue
            data["entries"][entry_key(machine_dir.name, mode_int)] = entry
    _save_index(rawdata_root, data)
    return data
