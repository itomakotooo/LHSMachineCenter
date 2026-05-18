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
- Writers (`update_entry`) do read-modify-write + os.replace, protected
  by both an in-process `threading.Lock` AND an OS-level cross-process
  exclusive file lock (`msvcrt.locking` on Windows / `fcntl.flock` on
  POSIX). The cross-process lock is critical: this index is touched
  by both the main backend process AND `ProcessPoolExecutor` workers
  (`BatchGenerateManager`) running in separate processes; without a
  cross-process lock, near-simultaneous writes from 4 workers race and
  lose entries. Phase 1 deploy refactor (2026-05-15) added the
  cross-process lock; before that, only the per-process os.replace
  atomicity was relied on. NTFS mtime resolution is 100ns — too coarse
  for the v1-designer-proposed mtime-retry to detect concurrent
  writers, so we went straight to an OS lock instead.
- Readers validate `entry.chunks` against the actual glob count; a
  mismatch triggers rescan + rewrite. This self-heals drift from
  failed writes, external deletion, or concurrent writers racing.
- On any decode error / missing file, fall back to "empty index" and
  let the next call rebuild.

Cross-refs:
- session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.2 R3
- memory/reference_chunk_index_inverted_md5.md (analogous within-process
  pattern for the per-cell sidecar; that one is single-process so
  threading.Lock alone is sufficient)
"""

from __future__ import annotations

import json
import os
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

INDEX_FILENAME = "_index.json"
INDEX_VERSION = 1

# In-process lock — serializes threads within the same Python process.
# Cross-process locking via msvcrt.locking / fcntl.flock is layered on
# top inside _cross_process_index_lock. Both layers are needed: the
# OS lock alone doesn't help when one process holds the OS lock and
# multiple threads in the SAME process try to acquire it (msvcrt.locking
# returns the lock to the same fd; concurrent threads in the same
# process would still race on the underlying read+modify+write).
_INDEX_LOCK = threading.Lock()


def _persist_lock_degraded(rawdata_root: Path, reason: str, exc: BaseException) -> None:
    """One-shot diagnostic when the OS-level lock degrades to in-process-only.

    Per memory/feedback_no_silent_swallow.md: silent fall-through to a weaker
    locking mode must be observable by operators so they can investigate
    (AV/EDR interference, network share, permission issue, etc.).

    One-shot: if the diagnostic file already exists we skip the write to avoid
    log spam on persistent degradation conditions. Manual delete of the file
    re-arms the diagnostic.

    Last-resort fallback: if the disk write itself fails, print to stderr — we
    don't swallow the diagnostic-write failure per feedback_no_silent_swallow.md.
    """
    diag_path = rawdata_root / f"{INDEX_FILENAME}.lock_degraded.json"
    if diag_path.exists():
        return  # one-shot; already flagged — operator must manually delete to re-arm
    try:
        diag_path.parent.mkdir(parents=True, exist_ok=True)
        diag_path.write_text(
            json.dumps({
                "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "platform": sys.platform,
                "reason": reason,
                "error": f"{exc.__class__.__name__}: {exc}",
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as inner_exc:
        # Last-resort stderr — don't silently swallow per feedback_no_silent_swallow.md.
        print(
            f"[rawdata-index] FAILED to persist lock-degraded diagnostic: "
            f"{inner_exc.__class__.__name__}: {inner_exc}",
            file=sys.stderr,
        )


@contextmanager
def _cross_process_index_lock(rawdata_root: Path) -> Iterator[None]:
    """Hold an exclusive OS-level lock on `_index.json.lock` for the
    duration of an index read-modify-write.

    Within-process: ``threading.Lock`` serializes Python threads.
    Cross-process: ``msvcrt.locking`` (Windows) / ``fcntl.flock`` (POSIX)
    serializes separate Python processes (e.g. ``ProcessPoolExecutor``
    workers spawned by ``BatchGenerateManager``).

    Degrades to within-process-only locking if the OS lock API is
    unavailable (rare; both Windows ``msvcrt`` and POSIX ``fcntl`` are
    in the stdlib). The within-process lock is always honored so a
    single-process test environment stays safe.

    Lock byte region: a single byte at offset 0 of the lockfile.
    msvcrt.locking and fcntl.flock both operate at this granularity
    by default; using a 1-byte region keeps the lock fast and
    consistent across the two backends.
    """
    rawdata_root.mkdir(parents=True, exist_ok=True)
    lockfile = rawdata_root / f"{INDEX_FILENAME}.lock"

    # Acquire within-process lock first. If a thread in this process
    # already holds the OS-level lock via this function, we must NOT
    # re-enter; threading.Lock blocks (not re-entrant), which is the
    # right semantics — the caller should not call this nested.
    _INDEX_LOCK.acquire()
    f = None
    os_lock_acquired = False
    try:
        try:
            # r+b creates the file via touch if it doesn't exist; we
            # don't write any meaningful content into the lockfile.
            lockfile.touch(exist_ok=True)
            f = open(lockfile, "r+b")
        except OSError as _open_exc:
            # Can't even open the lockfile — degrade to within-
            # process-only and continue. The caller's read-modify-write
            # is still atomic per-process via os.replace, so single-
            # process correctness is preserved.
            # Phase 1 fix: one-shot diagnostic per feedback_no_silent_swallow.md
            # so operators see when OS-level locking has silently degraded.
            _persist_lock_degraded(rawdata_root, "lockfile_open_failed", _open_exc)
            yield
            return

        if sys.platform == "win32":
            try:
                import msvcrt
                # LK_LOCK is blocking with retry: tries once per second
                # for up to ~10 seconds, then raises OSError. For our
                # workload (chunk-write completing in <1s typically),
                # this is plenty.
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                os_lock_acquired = True
            except (OSError, ImportError) as _msvcrt_exc:
                # Module missing or lock contention timeout. Continue
                # with within-process lock only; the os.replace below
                # is still per-process-atomic.
                # Phase 1 fix: one-shot diagnostic per feedback_no_silent_swallow.md.
                _persist_lock_degraded(rawdata_root, "msvcrt_locking_failed", _msvcrt_exc)
        else:
            try:
                import fcntl
                # fcntl.flock with LOCK_EX blocks indefinitely on
                # contention; this is fine because critical sections
                # are sub-second.
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                os_lock_acquired = True
            except (OSError, ImportError) as _fcntl_exc:
                # Phase 1 fix: one-shot diagnostic per feedback_no_silent_swallow.md.
                _persist_lock_degraded(rawdata_root, "fcntl_flock_failed", _fcntl_exc)

        yield
    finally:
        if os_lock_acquired and f is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                # POSIX: closing the fd releases flock automatically.
            except (OSError, ImportError):
                pass
        if f is not None:
            try:
                f.close()
            except OSError:
                pass
        _INDEX_LOCK.release()


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

    Phase 1 deploy: read-modify-write is protected by both a
    `threading.Lock` and an OS-level cross-process file lock so
    near-simultaneous writes from `ProcessPoolExecutor` workers can't
    silently lose entries. See `_cross_process_index_lock` for details.
    """
    try:
        # Scan is done BEFORE acquiring the lock so we don't hold the
        # cross-process lock during I/O-heavy chunk-dir iteration. The
        # scan reads only sidecar metadata so it can't be corrupted by
        # concurrent writers to _index.json (which is what the lock
        # protects). If chunks change between scan and write, that's
        # fine — the next update_entry call will pick up the new state.
        entry = _scan_mode_dir(chunk_dir)
        with _cross_process_index_lock(rawdata_root):
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
    """Drop the entry for a (machine, mode) — e.g. after rawdata delete.

    Phase 1 deploy: cross-process lock layered for the same reason as
    `update_entry` — concurrent delete + sample-completion writes from
    different processes must not collide.
    """
    try:
        with _cross_process_index_lock(rawdata_root):
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

    Phase 1 deploy: cross-process lock held for the entire scan + save
    so a concurrent `update_entry` from another process can't slip in
    between the rebuild's read and write. This blocks the rebuild
    longer than ideal, but rebuild is a rare admin operation so the
    trade-off is fine.
    """
    if not rawdata_root.is_dir():
        return _empty_index()
    with _cross_process_index_lock(rawdata_root):
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
