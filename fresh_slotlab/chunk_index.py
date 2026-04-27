"""Per-mode chunk metadata sidecar — ``_chunks.json``.

The rawdata management layer for chunk-md5 segregation. Replaces the
"open every file to know its md5" anti-pattern that user feedback
2026-04-26 finally pinned down ("你应该有个管理 rawdata 的机制，比如
索引啥的，而不是要去读每个 rawdata 才知道 md5"). Three hot paths
benefit:

1. Resume-replay with md5 filter (operator swaps local cfg → most
   chunks belong to a historical md5): pre-fix iterated every chunk,
   post-fix consults the inverted ``by_md5`` index for an O(1) bucket
   lookup. ~14 s → ~10 ms wall time on M1sim's 1443-chunk dir.

2. CI pre-check (virtual_analyzer's _load_existing_session_stats):
   same anti-pattern, same fix.

3. 机台管理 click on a machine with large rawdata
   (check_rawdata_status cold-path): same.

Sidecar shape (one file per ``<rawdata_root>/<machine>/mode_<N>/``):

  {
    "_version": 1,
    "_updated_at": "ISO ts",
    "chunks": {                            # per-chunk lookup (existing)
      "chunk_0001.json": {
        "idx": 1, "cfg_md5": "...", "code_md5": "...",
        "spin_times": 1000, "robot_count": 8,
        "saved_at": "...", "size_bytes": N
      },
      ...
    },
    "by_md5": {                            # md5 → [filenames] (2026-04-26)
      "cfg_a|code_x": ["chunk_0001.json", ...],
      "cfg_b|code_x": ["chunk_0010.json", ...]
    }
  }

Reads pick the right index for the question:
  - "what does THIS chunk look like?"   → chunks[name]
  - "give me the chunks for THIS md5"   → by_md5[cfg|code]
  - "how many md5 versions exist?"      → keys of by_md5

Writes maintain BOTH indexes atomically. ``update_chunk_entry`` and
``bulk_remove_chunk_entries`` are the only mutators — every chunk
add/remove path in the codebase routes through one of them.

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
- Backward compat: pre-2026-04-26 sidecars on disk lack the
  ``by_md5`` field. Helpers derive it in-memory on first read; the
  next write through update/bulk_remove persists the v2 layout.
  No version bump, no migration script.
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
_PEEK_RE_CORE = re.compile(
    r'"_chunk_index"\s*:\s*(\d+).*?'
    r'"_config_md5"\s*:\s*"([^"]*)".*?'
    r'"_code_md5"\s*:\s*"([^"]*)"',
    re.DOTALL,
)
# Optional scalars — peeked in the same 4KB pass. When absent (old
# envelope / partial write) the sidecar entry records 0 and the
# caller's fallback logic handles it.
_PEEK_RE_SPIN_TIMES = re.compile(r'"_spin_times"\s*:\s*(\d+)')
_PEEK_RE_ROBOT_COUNT = re.compile(r'"_robot_count"\s*:\s*(\d+)')


class ChunkIndexError(Exception):
    """Raised when the sidecar is structurally invalid. Callers should
    delete + rebuild rather than propagate (the chunk files themselves
    remain authoritative)."""


# ── Peek helpers ────────────────────────────────────────────────────


def peek_chunk_envelope(path: Path) -> dict[str, Any] | None:
    """Read just the envelope header and return a dict with
    ``{idx, cfg_md5, code_md5, spin_times, robot_count}``.

    The three required fields (idx + both md5s) come from one combined
    regex that enforces encounter order — any reordered envelope fails
    the match, and the caller falls back to full ``load_chunk_envelope``.
    The two optional fields (spin_times, robot_count) are grabbed
    independently and default to 0 when absent so callers can still
    use the sidecar for md5 classification on legacy envelopes.

    Returns ``None`` when the required fields don't appear in the
    first ~4 KB of the file. Never raises for IO / decode errors."""
    try:
        with path.open("rb") as f:
            head = f.read(_PEEK_BYTES)
    except OSError:
        return None
    try:
        text = head.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return None
    m = _PEEK_RE_CORE.search(text)
    if not m:
        return None
    try:
        idx = int(m.group(1))
    except (ValueError, IndexError):
        return None
    spin_m = _PEEK_RE_SPIN_TIMES.search(text)
    robot_m = _PEEK_RE_ROBOT_COUNT.search(text)
    return {
        "idx": idx,
        "cfg_md5": m.group(2),
        "code_md5": m.group(3),
        "spin_times": int(spin_m.group(1)) if spin_m else 0,
        "robot_count": int(robot_m.group(1)) if robot_m else 0,
    }


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


def _md5_key(cfg_md5: str, code_md5: str) -> str:
    """Stable string key for the by_md5 inverted index. Pipe is fine
    as a separator since md5 hex digests never contain pipes."""
    return f"{cfg_md5 or ''}|{code_md5 or ''}"


def _rebuild_by_md5(chunks_dict: dict[str, Any]) -> dict[str, list[str]]:
    """Derive the (cfg_md5|code_md5) → [filenames] inverted index from
    the per-chunk dict. Used at build time AND as a fallback when an
    older sidecar (no ``by_md5`` field) is loaded — that case auto-
    upgrades on the next write."""
    by_md5: dict[str, list[str]] = {}
    for fname, entry in chunks_dict.items():
        if not isinstance(entry, dict):
            continue
        key = _md5_key(
            str(entry.get("cfg_md5", "") or ""),
            str(entry.get("code_md5", "") or ""),
        )
        by_md5.setdefault(key, []).append(str(fname))
    # Sort each bucket by chunk_index (extracted from filename) for
    # deterministic iteration. Filename "chunk_0001.json" → 1.
    for names in by_md5.values():
        names.sort(key=lambda n: int(n.split("_", 1)[1].split(".", 1)[0])
                   if "_" in n and "." in n else 0)
    return by_md5


def build_chunks_index(mode_dir: Path) -> dict[str, Any]:
    """Scan ``mode_dir/chunk_*.json`` via peek, produce a fresh
    sidecar payload, and persist it.

    Slow only on the very first call after a directory gains chunks
    (peek × N = 4 KB × N IO, ~5 ms/chunk). Subsequent reads hit the
    sidecar directly.

    Output payload carries TWO indexes:

      * ``chunks``: per-chunk dict (filename → metadata) — used for
        per-chunk lookups (e.g. "what was chunk_0042's saved_at?").

      * ``by_md5``: inverted index (cfg|code → [filenames]) — used
        for the "give me the chunks for THIS md5" hot path that
        the real + virtual analyzers' replay loops hit. O(1) dict
        lookup instead of O(N) walk over ``chunks``. Added
        2026-04-26 after the user observed: "你应该有个管理 rawdata
        的机制，比如索引啥的，而不是要去读每个 rawdata 才知道 md5".
    """
    entries: dict[str, dict[str, Any]] = {}
    for cf in sorted(mode_dir.glob("chunk_*.json")):
        peek = peek_chunk_envelope(cf)
        if peek is None:
            # Envelope didn't match the regex — skip. A follow-up
            # full ``load_chunk_envelope`` caller handles it; we
            # just don't index it in the sidecar.
            continue
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
            "idx": peek["idx"],
            "cfg_md5": peek["cfg_md5"],
            "code_md5": peek["code_md5"],
            "spin_times": peek["spin_times"],
            "robot_count": peek["robot_count"],
            "saved_at": saved_at,
            "size_bytes": size_bytes,
        }
    payload = {
        "_version": SIDECAR_VERSION,
        "_updated_at": _now_iso(),
        "chunks": entries,
        "by_md5": _rebuild_by_md5(entries),
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
    corrupt/partial writes of the sidecar.

    2026-04-25: switched from ``Path.glob("chunk_*.json")`` to
    ``os.scandir`` with prefix/suffix string checks. ~1.7x faster
    on a 700-chunk dir (0.6ms vs 1.0ms) and avoids per-entry Path
    object allocation. Same correctness guarantee — file/Path
    iteration is the underlying mechanism in both APIs.

    Why we still need this check at all (given delete-path hooks
    now update the sidecar): defensive backstop for any future
    code path that adds/removes chunks without going through
    ``update_chunk_entry`` / ``bulk_remove_chunk_entries``. The
    cost when sidecar IS in sync is dominated by one syscall +
    700 short string comparisons — sub-millisecond. The cost when
    sidecar IS stale is one syscall + N peeks at 4KB each — but
    that case only fires once until the rebuilt sidecar persists.
    Windows mtime resolution (15.625 ms tick) makes the cheaper
    ``stat`` mtime-based variant unreliable, so we keep the
    keyset comparison.
    """
    indexed = idx.get("chunks") or {}
    indexed_names = set(indexed.keys()) if isinstance(indexed, dict) else set()
    indexed_count = len(indexed_names)
    on_disk_count = 0
    try:
        with os.scandir(mode_dir) as it:
            for entry in it:
                name = entry.name
                if not name.startswith("chunk_") or not name.endswith(".json"):
                    continue
                # Avoid stat-ing entry.is_file() in the hot path:
                # `chunk_*.json` files are always regular files in
                # this codebase (writers use mkstemp + os.replace),
                # so a name match is sufficient. If symlinks ever
                # appeared the scandir would still iterate them; the
                # rebuild path's peek_chunk_envelope would handle.
                on_disk_count += 1
                if name not in indexed_names:
                    return True  # New chunk that bypassed our hooks.
    except OSError:
        return True
    return on_disk_count != indexed_count


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
    spin_times: int = 0,
    robot_count: int = 0,
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
            "by_md5": {},
        }
        if idx.get("_version") != SIDECAR_VERSION:
            # Can't merge into foreign schema; rebuild from scratch.
            idx = {
                "_version": SIDECAR_VERSION,
                "_updated_at": _now_iso(),
                "chunks": {},
                "by_md5": {},
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
        # Maintain the by_md5 inverted index alongside the per-chunk
        # dict. If this filename is being re-indexed (chunk rewritten
        # with a different md5 — rare but possible during dev), drop
        # it from its OLD bucket first.
        new_cfg = str(config_md5 or "")
        new_code = str(code_md5 or "")
        new_key = _md5_key(new_cfg, new_code)
        existing_entry = idx["chunks"].get(chunk_file.name)
        by_md5 = idx.setdefault("by_md5", _rebuild_by_md5(idx["chunks"]))
        if isinstance(existing_entry, dict):
            old_key = _md5_key(
                str(existing_entry.get("cfg_md5", "") or ""),
                str(existing_entry.get("code_md5", "") or ""),
            )
            if old_key != new_key and old_key in by_md5:
                try:
                    by_md5[old_key].remove(chunk_file.name)
                    if not by_md5[old_key]:
                        del by_md5[old_key]
                except ValueError:
                    pass
        # Add to new bucket (idempotent — set semantics via "in" check
        # so re-indexing the same chunk twice doesn't duplicate).
        bucket = by_md5.setdefault(new_key, [])
        if chunk_file.name not in bucket:
            bucket.append(chunk_file.name)
            # Keep bucket order deterministic by chunk_index for
            # downstream consumers that expect sorted iteration.
            bucket.sort(key=lambda n: int(n.split("_", 1)[1].split(".", 1)[0])
                        if "_" in n and "." in n else 0)
        idx["chunks"][chunk_file.name] = {
            "idx": int(chunk_index),
            "cfg_md5": new_cfg,
            "code_md5": new_code,
            "spin_times": int(spin_times or 0),
            "robot_count": int(robot_count or 0),
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
    missing entry is a no-op.

    For batch deletion (auto-cleanup loop, version-purge endpoint
    that nukes many chunks at once), prefer
    :func:`bulk_remove_chunk_entries` — it does ONE sidecar
    read+merge+write instead of N.
    """
    bulk_remove_chunk_entries(mode_dir, [chunk_file_name])


def bulk_remove_chunk_entries(
    mode_dir: Path,
    chunk_file_names: list[str] | tuple[str, ...] | set[str],
) -> int:
    """Drop multiple entries in a single sidecar read+write cycle.

    Used by paths that delete many chunks at once (auto disk-space
    cleanup, version purge, rawdata purge) so we don't rewrite the
    sidecar N times when one rewrite would do.

    Returns the number of entries actually removed (entries that
    weren't in the sidecar are silently skipped — the caller may
    have unlinked files from outside this module's purview).

    Best-effort: a sidecar IO failure is logged + swallowed so
    the chunk deletes (which are authoritative) aren't undone.
    Next reader call rebuilds via the mtime stale-check.
    """
    if not chunk_file_names:
        return 0
    name_set = set(chunk_file_names)
    idx = load_chunks_index(mode_dir)
    if idx is None:
        # Nothing to update — sidecar will be rebuilt on next read.
        # The dir's mtime already moved past sidecar.mtime when the
        # files were unlinked, so the next get_chunks_index will
        # detect stale and rebuild from scratch.
        return 0
    chunks = idx.get("chunks") or {}
    by_md5 = idx.setdefault("by_md5", _rebuild_by_md5(chunks))
    removed = 0
    for name in name_set:
        entry = chunks.pop(name, None)
        if entry is None:
            continue
        removed += 1
        # Drop from the inverted index too — keep both views in sync
        # so chunks_by_md5() lookups don't return phantom filenames
        # pointing at deleted files.
        if isinstance(entry, dict):
            key = _md5_key(
                str(entry.get("cfg_md5", "") or ""),
                str(entry.get("code_md5", "") or ""),
            )
            bucket = by_md5.get(key)
            if isinstance(bucket, list):
                try:
                    bucket.remove(name)
                except ValueError:
                    pass
                if not bucket:
                    del by_md5[key]
    if removed == 0:
        # No entries actually removed; skip the sidecar write so
        # we don't bump its mtime past dir.mtime unnecessarily.
        return 0
    idx["chunks"] = chunks
    idx["by_md5"] = by_md5
    idx["_updated_at"] = _now_iso()
    try:
        _write_sidecar_atomic(_sidecar_path(mode_dir), idx)
    except OSError as exc:
        import sys
        print(
            f"[chunk_index] bulk_remove_chunk_entries failed for "
            f"{mode_dir}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return removed


def remove_sidecar(mode_dir: Path) -> None:
    """Delete the sidecar file. Use when the entire mode_dir is
    being torn down (e.g. force-purge a whole machine/mode) — the
    next read against the dir (if it still exists) will rebuild
    from scratch."""
    sidecar = _sidecar_path(mode_dir)
    try:
        sidecar.unlink()
    except OSError:
        pass


# ── Query helpers (reader convenience) ──────────────────────────────


def chunks_by_md5(
    mode_dir: Path, cfg_md5: str, code_md5: str,
) -> list[str]:
    """Direct O(1) lookup: filenames of chunks stamped with the given
    md5 pair. Hits the sidecar's ``by_md5`` inverted index so callers
    don't iterate the per-chunk dict.

    Returns ``[]`` for unknown md5 (sidecar bucket missing). Sidecar
    auto-rebuilds via ``get_chunks_index`` if the keyset has drifted
    from disk; the returned list is sorted by chunk index ascending.

    Use this from analyzer pre-filters / replay loops where you know
    you only want one md5 bucket — avoids the O(N) walk over every
    sidecar entry that the older ``iter_chunks_matching_md5`` (kept
    for back-compat) does.

    Backward compat: when an older sidecar (no ``by_md5`` field) is
    loaded, the field is derived in-memory on the fly. The next
    write (update_chunk_entry / bulk_remove_chunk_entries / build_
    chunks_index) persists it, so the next call hits the fast path.
    """
    idx = get_chunks_index(mode_dir)
    by_md5 = idx.get("by_md5")
    if not isinstance(by_md5, dict):
        # Older sidecar without the inverted index — derive once
        # in-memory. Costs O(N) for THIS call only; next write
        # persists the field and subsequent calls are O(1).
        by_md5 = _rebuild_by_md5(idx.get("chunks") or {})
    return list(by_md5.get(_md5_key(cfg_md5, code_md5), []))


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
