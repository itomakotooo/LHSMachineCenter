"""Per-mode chunk metadata sidecar — ``_chunks.json``.

Solves two hot-path performance issues caused by ``json.loads(whole_file)``
over every historical chunk just to read ~300 bytes of envelope header:

1. Resume-replay with md5 filter (e.g. after operator swaps local cfg):
   ~100 MB / ~15 s wasted reading chunks that will all be filtered out
   anyway.
2. 机台管理 click on a machine with large rawdata: ``check_rawdata_status``
   cold-path rescans every chunk to rebuild md5 / version buckets.

This module maintains a small sidecar (``_chunks.json``, ~100 bytes per
chunk) under each ``<rawdata_root>/<machine>/mode_<N>/`` directory.
Readers consult it first; the chunk files themselves only need full
read when the chunk is actually being merged into stats.

Design notes:
- Pure functions, Path-parameterized — shared verbatim between real
  console (``fresh_slotlab.rawdata``) and virtual console
  (``slot_designer.rawdata``). Caller owns the ``mode_dir`` path.
- Sidecar is an optimization layer; missing / stale / corrupt sidecar
  NEVER blocks correctness. All readers fall back to rebuilding
  (via :func:`peek_chunk_envelope` or full ``load_chunk_envelope``).
- Atomic writes (``tmp + os.replace``) keep readers safe against
  partial-write crashes.
- Self-healing: the ``get_chunks_index`` entry point auto-rebuilds
  + persists when the sidecar is absent or visibly stale (file set
  drifts from index entries). Readers don't need to know which path
  they're on.
- Schema versioning (``_version``) leaves room for future envelope
  fields without breaking old readers.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SIDECAR_NAME = "_chunks.json"
SIDECAR_VERSION = 1

# Envelope header peek — reads only the first few KB of a chunk file
# to regex-extract the header fields without parsing the potentially-
# megabytes-sized ``response`` array. See ``_persist_chunk`` in
# fresh_slotlab.player_impact_analyzer + ``write_chunk`` in
# slot_designer.emitter.chunk: both writers place ``_chunk_index`` /
# ``_config_md5`` / ``_code_md5`` in the envelope dict BEFORE
# ``response``, so the peek regex is a safe fast-path. When the
# ordering invariant ever breaks, the None return funnels callers
# into the full-load fallback — correctness preserved.
_PEEK_BYTES = 4096
_PEEK_RE = re.compile(
    r'"_chunk_index"\s*:\s*(\d+).*?'
    r'"_config_md5"\s*:\s*"([^"]*)".*?'
    r'"_code_md5"\s*:\s*"([^"]*)"',
    re.DOTALL,
)


class ChunkIndexError(Exception):
    """Raised when the sidecar is structurally invalid. Callers should
    delete + rebuild rather than propagate (the chunk files themselves
    remain authoritative)."""


# ── Peek helpers ────────────────────────────────────────────────────


def peek_chunk_envelope(path: Path) -> tuple[int, str, str] | None:
    """Return ``(chunk_index, config_md5, code_md5)`` from the first
    ~4 KB of a chunk file without parsing the whole JSON.

    Returns ``None`` when the regex doesn't match — the caller must
    fall back to full ``load_chunk_envelope``. Never raises for IO
    or decode errors; returns ``None`` so the caller handles the
    missing-file / bad-file path uniformly."""
    try:
        with path.open("rb") as f:
            head = f.read(_PEEK_BYTES)
    except OSError:
        return None
    try:
        text = head.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return None
    m = _PEEK_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1)), m.group(2), m.group(3)
    except (ValueError, IndexError):
        return None


# ── Sidecar I/O ─────────────────────────────────────────────────────


def _sidecar_path(mode_dir: Path) -> Path:
    return mode_dir / SIDECAR_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_sidecar_atomic(sidecar: Path, payload: dict[str, Any]) -> None:
    """Atomic write: tmp-in-same-dir + ``os.replace``. Readers never
    see a torn sidecar. Swallows the parent-exists check since
    ``mode_dir`` existing is the precondition of this module."""
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    # NamedTemporaryFile in the same directory so os.replace is
    # guaranteed same-filesystem (required for atomicity on NTFS + ext4).
    fd, tmp_name = tempfile.mkstemp(
        prefix=".chunks.", suffix=".json.tmp", dir=str(sidecar.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_name, sidecar)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_chunks_index(mode_dir: Path) -> dict[str, Any] | None:
    """Read the sidecar at ``mode_dir/_chunks.json``. Returns ``None``
    for missing / unreadable / version-mismatched sidecars so the
    caller can rebuild. Never raises on bad data — treats it like
    cache invalidation."""
    p = _sidecar_path(mode_dir)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("_version") != SIDECAR_VERSION:
        return None
    chunks = data.get("chunks")
    if not isinstance(chunks, dict):
        return None
    # Normalise: ensure every value is a dict (schema hygiene).
    data["chunks"] = {
        str(k): v for k, v in chunks.items() if isinstance(v, dict)
    }
    return data


def build_chunks_index(mode_dir: Path) -> dict[str, Any]:
    """Scan ``mode_dir/chunk_*.json`` via peek, produce a fresh
    sidecar payload, and persist it.

    Slow only on the very first call after a directory gains chunks
    (peek × N = 4 KB × N IO, ~5 ms/chunk). Subsequent reads hit the
    sidecar directly."""
    entries: dict[str, dict[str, Any]] = {}
    for cf in sorted(mode_dir.glob("chunk_*.json")):
        peek = peek_chunk_envelope(cf)
        if peek is None:
            # Envelope didn't match the regex — skip. A follow-up
            # full ``load_chunk_envelope`` caller handles it; we
            # just don't index it in the sidecar.
            continue
        idx, cfg_md5, code_md5 = peek
        try:
            st = cf.stat()
            size_bytes = int(st.st_size)
            # Use the file's mtime as a best-effort saved_at when the
            # envelope doesn't expose it via peek. Downstream consumers
            # already tolerate either field's absence.
            saved_at = datetime.fromtimestamp(
                st.st_mtime, tz=timezone.utc,
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        except OSError:
            size_bytes = 0
            saved_at = ""
        entries[cf.name] = {
            "idx": idx,
            "cfg_md5": cfg_md5,
            "code_md5": code_md5,
            "saved_at": saved_at,
            "size_bytes": size_bytes,
        }
    payload = {
        "_version": SIDECAR_VERSION,
        "_updated_at": _now_iso(),
        "chunks": entries,
    }
    if mode_dir.is_dir():
        try:
            _write_sidecar_atomic(_sidecar_path(mode_dir), payload)
        except OSError:
            # Persist failure is best-effort — in-memory payload is
            # still returned so caller gets the value.
            pass
    return payload


def _is_index_stale(mode_dir: Path, idx: dict[str, Any]) -> bool:
    """True if the sidecar's keyset doesn't match what's on disk.
    Detects: new chunks landed externally, chunks deleted externally,
    corrupt/partial writes of the sidecar."""
    try:
        on_disk = {p.name for p in mode_dir.glob("chunk_*.json")}
    except OSError:
        return True
    indexed = set(idx.get("chunks", {}).keys())
    return on_disk != indexed


def get_chunks_index(mode_dir: Path) -> dict[str, Any]:
    """Primary read entry point. Returns the sidecar payload,
    auto-rebuilding when missing or stale. Callers get an authoritative
    view without caring which path triggered — load, rebuild, or
    both. Always returns a dict with at least ``{"_version", "chunks"}``
    (``chunks`` may be empty if the dir has no chunk files)."""
    idx = load_chunks_index(mode_dir)
    if idx is None or _is_index_stale(mode_dir, idx):
        idx = build_chunks_index(mode_dir)
    return idx


# ── Write-side update hook ──────────────────────────────────────────


def update_chunk_entry(
    mode_dir: Path,
    chunk_file: Path,
    *,
    chunk_index: int,
    config_md5: str,
    code_md5: str,
    saved_at: str | None = None,
    size_bytes: int | None = None,
) -> None:
    """Record ``chunk_file``'s envelope metadata in the sidecar after
    its successful write. Called from writer hooks in both the real
    analyzer and slot_designer emitter — same signature / same format
    so a sidecar produced by one is readable by the other.

    Implementation: read existing (or empty) → merge → atomic write.
    O(existing-chunk-count) per call which is fine: the sidecar is a
    few KB and reads + writes are cheap. Avoids the "append a JSON
    line per chunk" complexity that would require a custom format.

    Best-effort: any IO failure is logged via ``print`` to stderr and
    swallowed — chunk writes are authoritative, sidecar is a cache.
    Next reader call will rebuild via ``get_chunks_index``."""
    try:
        idx = load_chunks_index(mode_dir) or {
            "_version": SIDECAR_VERSION,
            "_updated_at": _now_iso(),
            "chunks": {},
        }
        if idx.get("_version") != SIDECAR_VERSION:
            # Can't merge into foreign schema; rebuild from scratch.
            idx = {
                "_version": SIDECAR_VERSION,
                "_updated_at": _now_iso(),
                "chunks": {},
            }
        if saved_at is None:
            try:
                saved_at = datetime.fromtimestamp(
                    chunk_file.stat().st_mtime, tz=timezone.utc,
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            except OSError:
                saved_at = _now_iso()
        if size_bytes is None:
            try:
                size_bytes = int(chunk_file.stat().st_size)
            except OSError:
                size_bytes = 0
        idx["chunks"][chunk_file.name] = {
            "idx": int(chunk_index),
            "cfg_md5": str(config_md5 or ""),
            "code_md5": str(code_md5 or ""),
            "saved_at": saved_at,
            "size_bytes": int(size_bytes),
        }
        idx["_updated_at"] = _now_iso()
        _write_sidecar_atomic(_sidecar_path(mode_dir), idx)
    except Exception as exc:  # noqa: BLE001
        # Sidecar is optimization-only; never let its failure block
        # a successful chunk write. Next reader rebuilds.
        import sys
        print(
            f"[chunk_index] update_chunk_entry failed for "
            f"{chunk_file.name}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


def remove_chunk_entry(mode_dir: Path, chunk_file_name: str) -> None:
    """Drop an entry after the chunk file was deleted (e.g. cache
    cleanup, operator-initiated rawdata purge). Missing sidecar or
    missing entry is a no-op."""
    idx = load_chunks_index(mode_dir)
    if idx is None:
        return
    chunks = idx.get("chunks") or {}
    if chunk_file_name not in chunks:
        return
    chunks.pop(chunk_file_name, None)
    idx["chunks"] = chunks
    idx["_updated_at"] = _now_iso()
    try:
        _write_sidecar_atomic(_sidecar_path(mode_dir), idx)
    except OSError:
        pass


# ── Query helpers (reader convenience) ──────────────────────────────


def iter_chunks_matching_md5(
    mode_dir: Path, cfg_md5: str, code_md5: str,
) -> list[tuple[str, dict[str, Any]]]:
    """Return ``[(chunk_filename, entry_dict), ...]`` for chunks whose
    envelope md5s match the given pair. ``(cfg_md5, code_md5) ==
    ("", "")`` matches everything (back-compat with pre-md5
    callers)."""
    idx = get_chunks_index(mode_dir)
    chunks = idx.get("chunks") or {}
    match_any = not cfg_md5 and not code_md5
    out: list[tuple[str, dict[str, Any]]] = []
    for fname, entry in chunks.items():
        if not isinstance(entry, dict):
            continue
        if match_any:
            out.append((fname, entry))
            continue
        if (
            entry.get("cfg_md5") == cfg_md5
            and entry.get("code_md5") == code_md5
        ):
            out.append((fname, entry))
    # Stable sort by index for deterministic replay order.
    out.sort(key=lambda t: int(t[1].get("idx", 0)))
    return out


def summarize_by_md5(mode_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Group chunks by (cfg_md5, code_md5) → {count, total_size_bytes,
    max_idx, earliest_saved_at}. Used by the rawdata version panel
    + check_rawdata_status cold path to avoid opening chunks at all
    once the sidecar is populated."""
    idx = get_chunks_index(mode_dir)
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in (idx.get("chunks") or {}).values():
        if not isinstance(entry, dict):
            continue
        key = (str(entry.get("cfg_md5", "")), str(entry.get("code_md5", "")))
        g = groups.setdefault(key, {
            "count": 0,
            "total_size_bytes": 0,
            "max_idx": 0,
            "earliest_saved_at": "",
        })
        g["count"] += 1
        g["total_size_bytes"] += int(entry.get("size_bytes", 0) or 0)
        g["max_idx"] = max(g["max_idx"], int(entry.get("idx", 0) or 0))
        saved = str(entry.get("saved_at", "") or "")
        if saved and (not g["earliest_saved_at"] or saved < g["earliest_saved_at"]):
            g["earliest_saved_at"] = saved
    return groups
