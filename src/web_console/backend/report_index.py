"""Unified report index builder and locked writer for per-mode index.json.

Defect being fixed (2026-06-12): four producers wrote four different
index-entry shapes, three of them missing rawdata md5 / analyzer-version
fields, and /api/reports/import wrote no index at all.  Additionally all
writers did read-list-append-write with no lock, so concurrent batch
finalizes silently dropped entries (M14/mode_1: 16 dirs, 4 entries).

Design:
  - ``build_index_entry`` is the single canonical entry constructor.
    All four producers route through it so the shape is always full.
  - ``append_index_entry`` guards the read-modify-write with a
    cross-process file lock on ``<mode_dir>/index.json.lock``,
    mirroring the ``rawdata_index._cross_process_index_lock`` pattern
    used by the ``BatchGenerateManager`` worker pool.
  - ``rewrite_latest`` recomputes latest.json from the in-memory index
    (newest entry by ``created_at``) under the same lock.

Lock behaviour mirrors ``fresh_slotlab.rawdata_index``:
  - Within-process: ``threading.Lock`` serializes Python threads.
  - Cross-process: ``msvcrt.locking`` (Windows) / ``fcntl.flock`` with
    LOCK_NB + bounded retry (POSIX) serializes worker processes.
  - Degrades gracefully to within-process-only when the OS lock is
    unavailable; diagnostic persisted to a sidecar file on disk
    (feedback_no_silent_swallow) + stderr.

report_file key:
  - present in the entry ONLY when the .md file actually exists on disk.
    The new report_engine never writes a .md; legacy paths that did
    keep getting the key.  Reconcile drops stale report_file keys.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

LOCK_FILENAME = "index.json.lock"
LOCK_DEGRADED_FILENAME = "index.json.lock_degraded.json"

# POSIX bounded-retry constants (mirrors rawdata_index pattern).
_POSIX_RETRY_COUNT = 20
_POSIX_RETRY_SLEEP = 0.5  # seconds per attempt; total max ~10s

# Within-process lock registry, keyed by resolved mode_dir path.
_INDEX_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
# One-shot "OS lock degraded" diagnostic per mode_dir (avoid flood).
_LOCK_DEGRADED: set[str] = set()


def _lock_for(mode_dir: Path) -> threading.Lock:
    try:
        key = str(mode_dir.resolve())
    except (OSError, RuntimeError):
        key = str(mode_dir)
    with _LOCKS_GUARD:
        lk = _INDEX_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _INDEX_LOCKS[key] = lk
        return lk


def _persist_lock_degraded(mode_dir: Path, reason: str) -> None:
    """Write a sidecar file recording the OS-lock degradation event.

    Mirrors ``rawdata_index._persist_lock_degraded``.  Fires only once per
    mode_dir per process lifetime (guarded by ``_LOCK_DEGRADED`` set).
    Also prints to stderr for immediate visibility in server logs.
    """
    key = str(mode_dir)
    if key in _LOCK_DEGRADED:
        return
    _LOCK_DEGRADED.add(key)
    print(
        f"[report_index] OS lock degraded for {mode_dir}: {reason}",
        file=sys.stderr,
    )
    try:
        sidecar = mode_dir / LOCK_DEGRADED_FILENAME
        payload = {
            "mode_dir": str(mode_dir),
            "reason": reason,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        fd, tmp = tempfile.mkstemp(prefix=".ldeg.", suffix=".json.tmp",
                                   dir=str(mode_dir))
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, sidecar)
    except Exception:  # noqa: BLE001
        pass  # sidecar write is best-effort; stderr message already sent


@contextmanager
def _report_index_lock(mode_dir: Path) -> Iterator[None]:
    """Exclusive lock for read-modify-write on mode_dir/index.json.

    Layers within-process threading.Lock with OS-level file lock so
    ProcessPoolExecutor workers (batch generate) cannot race each other.

    Platform behaviour:
      Windows: ``msvcrt.LK_LOCK`` with 10-second retry (built into LK_LOCK).
      POSIX:   ``fcntl.LOCK_EX | LOCK_NB`` with bounded retry (20 × 0.5s)
               so stale locks (e.g. crashed process) don't block forever.

    On OS-lock failure the function degrades to within-process-only and
    persists a sidecar ``index.json.lock_degraded.json`` in mode_dir
    (feedback_no_silent_swallow).
    """
    mode_dir.mkdir(parents=True, exist_ok=True)
    lockfile = mode_dir / LOCK_FILENAME
    in_proc_lock = _lock_for(mode_dir)
    in_proc_lock.acquire()
    f = None
    os_acquired = False
    try:
        try:
            lockfile.touch(exist_ok=True)
            f = open(lockfile, "r+b")  # noqa: SIM115
        except OSError as _open_exc:
            _persist_lock_degraded(
                mode_dir,
                f"open failed: {type(_open_exc).__name__}: {_open_exc}",
            )
            yield
            return

        if sys.platform == "win32":
            try:
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                os_acquired = True
            except (OSError, ImportError) as _exc:
                _persist_lock_degraded(
                    mode_dir,
                    f"msvcrt.locking failed: {type(_exc).__name__}: {_exc}",
                )
        else:
            # POSIX: LOCK_NB + bounded retry so a stale lock doesn't block forever.
            try:
                import fcntl
                _acquired = False
                for _attempt in range(_POSIX_RETRY_COUNT):
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        _acquired = True
                        break
                    except BlockingIOError:
                        time.sleep(_POSIX_RETRY_SLEEP)
                if _acquired:
                    os_acquired = True
                else:
                    _persist_lock_degraded(
                        mode_dir,
                        f"fcntl.flock timed out after "
                        f"{_POSIX_RETRY_COUNT * _POSIX_RETRY_SLEEP:.1f}s",
                    )
            except (OSError, ImportError) as _exc:
                _persist_lock_degraded(
                    mode_dir,
                    f"fcntl unavailable: {type(_exc).__name__}: {_exc}",
                )

        yield
    finally:
        if f is not None:
            if os_acquired:
                try:
                    if sys.platform == "win32":
                        import msvcrt
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except (OSError, ImportError):
                    pass
            try:
                f.close()
            except OSError:
                pass
        in_proc_lock.release()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, payload: Any) -> None:
    """tmp + os.replace atomic write.  Same pattern as chunk_index and
    rawdata_index; keeps readers safe against partial-write crashes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".idx.", suffix=".json.tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                os.replace(tmp_name, path)
                last_exc = None
                break
            except PermissionError as exc:
                import time
                last_exc = exc
                time.sleep(0.05 * (attempt + 1))
        if last_exc is not None:
            raise last_exc
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_index_entry(
    reports_root: Path,
    machine: str,
    mode: int,
    report_version: str,
    run_id: str,
    *,
    summary: dict[str, Any],
    summary_path: Path,
) -> dict[str, Any]:
    """Construct the canonical full-shape index entry.

    All four producers (generate, batch-generate, import, retention
    rebuild) route through this builder so the resulting entry always
    carries the complete field set.

    Fields:
      report_version, run_id, created_at,
      summary_file (canonical absolute path under reports_root),
      report_file (ONLY when the .md actually exists — key absent
        when the new report_engine is used, present for legacy paths),
      rtp_point_pct, achieved_rtp_pct, achieved_halfwidth_pp,
      total_spins, quality_label,
      rawdata_config_md5, rawdata_code_md5,
      analyzer_version, effective_analyzer_version.

    ``summary`` must be the already-read summary dict (caller owns the
    I/O; the builder is pure).  ``summary_path`` is the canonical disk
    path (absolute, under reports_root); the builder resolves it to a
    canonical string for storage.
    """
    rtp = (summary.get("rtp") or {}).get("point_pct")
    hw = (summary.get("sampling") or {}).get("achieved_halfwidth_pp")
    ql = (
        (summary.get("guideline_assessment") or {})
        .get("data_quality", {})
        .get("quality_label")
        or (summary.get("guideline_assessment") or {}).get("quality_label")
        or summary.get("quality_label")
    )
    total_spins = (summary.get("sampling") or {}).get("total_spins")
    config_md5 = summary.get("config_md5") or ""
    code_md5 = summary.get("code_md5") or ""
    analyzer_version = summary.get("analyzer_version") or ""
    effective_analyzer_version = summary.get("effective_analyzer_version") or ""

    entry: dict[str, Any] = {
        "report_version": report_version,
        "run_id": run_id,
        "created_at": _now_iso(),
        "summary_file": str(summary_path),
        "rtp_point_pct": rtp,
        "achieved_rtp_pct": rtp,
        "achieved_halfwidth_pp": hw,
        "total_spins": total_spins,
        "quality_label": ql,
        "rawdata_config_md5": config_md5,
        "rawdata_code_md5": code_md5,
        "analyzer_version": analyzer_version,
        "effective_analyzer_version": effective_analyzer_version,
    }

    # report_file: include only when the .md actually exists.
    report_md_path = summary_path.parent / "player_impact_report.md"
    if report_md_path.exists():
        entry["report_file"] = str(report_md_path)

    return entry


def append_index_entry(mode_dir: Path, entry: dict[str, Any]) -> None:
    """Append ``entry`` to ``<mode_dir>/index.json`` under a cross-process
    exclusive lock.  Creates index.json when absent.

    After appending, callers should call ``rewrite_latest(mode_dir)``
    separately — or use ``append_and_rewrite_latest`` for the common
    single-entry finalize path.

    The lock is held for the entire read-modify-write cycle so concurrent
    batch-worker finalizes (ProcessPoolExecutor) see a consistent index.
    """
    index_path = mode_dir / "index.json"
    with _report_index_lock(mode_dir):
        index_payload: list[dict[str, Any]] = []
        if index_path.exists():
            try:
                raw = json.loads(index_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    index_payload = raw
            except (OSError, json.JSONDecodeError):
                index_payload = []
        index_payload.append(entry)
        _atomic_write_json(index_path, index_payload)


def rewrite_latest(mode_dir: Path) -> None:
    """Recompute ``<mode_dir>/latest.json`` from the current index.

    Latest = the entry with the newest sort key.  Primary: ``created_at``
    (ISO string, lexicographic = chronological).  Secondary: ``report_version``
    (rv_YYYYMMDDTHHMMSSZ… prefix, also lexicographic = chronological).
    When both are equal the last element in the list wins (most recently
    appended = most recently written run).

    Deletes latest.json when the index is empty.

    The lock is held so the read of index.json and the write of
    latest.json are atomic (no concurrent writer can interleave).
    """
    index_path = mode_dir / "index.json"
    latest_path = mode_dir / "latest.json"
    with _report_index_lock(mode_dir):
        index_payload: list[dict[str, Any]] = []
        if index_path.exists():
            try:
                raw = json.loads(index_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    index_payload = [e for e in raw if isinstance(e, dict)]
            except (OSError, json.JSONDecodeError):
                index_payload = []
        if not index_payload:
            try:
                latest_path.unlink(missing_ok=True)
            except OSError:
                pass
            return
        latest = max(
            enumerate(index_payload),
            key=lambda ie: (
                str(ie[1].get("created_at") or ""),
                str(ie[1].get("report_version") or ""),
                ie[0],  # position as final tiebreaker
            ),
        )[1]
        _atomic_write_json(latest_path, latest)


def append_and_rewrite_latest(mode_dir: Path, entry: dict[str, Any]) -> None:
    """Append entry + rewrite latest in one double-locked operation.

    Equivalent to ``append_index_entry`` then ``rewrite_latest`` but
    acquires the lock only once (the full read-modify-write cycle is
    one critical section).

    This is the method all four finalizers should use; it replaces the
    old pair of ``atomic_json_write(index_path, …) + atomic_json_write
    (latest_path, item)`` calls.

    latest.json is recomputed as the maximum entry over the full index
    (same algorithm as ``rewrite_latest``), not a blind copy of the
    just-appended entry.  This is safe for both the normal finalize flow
    (sequential chronological appends) and for reconcile / migration
    callers that may append historically older entries out of order.
    """
    index_path = mode_dir / "index.json"
    latest_path = mode_dir / "latest.json"
    with _report_index_lock(mode_dir):
        # Read existing index.
        index_payload: list[dict[str, Any]] = []
        if index_path.exists():
            try:
                raw = json.loads(index_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    index_payload = [e for e in raw if isinstance(e, dict)]
            except (OSError, json.JSONDecodeError):
                index_payload = []
        # Append.
        index_payload.append(entry)
        _atomic_write_json(index_path, index_payload)
        # Recompute latest = max over the full index (NOT blind copy of
        # the just-appended entry).  Consistent with rewrite_latest.
        # Tiebreaker: position (last element wins when created_at and
        # report_version are identical) preserves the chronological
        # invariant for normal sequential finalizes.
        latest = max(
            enumerate(index_payload),
            key=lambda ie: (
                str(ie[1].get("created_at") or ""),
                str(ie[1].get("report_version") or ""),
                ie[0],
            ),
        )[1]
        _atomic_write_json(latest_path, latest)
