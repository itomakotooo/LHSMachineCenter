"""Thread-safe atomic JSON writes with per-file locks.

Phase 1 deploy refactor (2026-05-15): replaces ad-hoc ``write_text``
patterns across config writers that raced under multi-user concurrency.
The Critical C1 fix (``machines.json`` wipe race — coupling-auditor
Scenario 16 in ``session_artifacts/_arch/deploy/03_deploy_concurrency_blast_radius.md``)
lives here.

Pattern:

- ``atomic_json_write(path, data)`` — one-shot atomic write
- ``atomic_json_read_modify_write(path, modifier, default=...)`` —
  read+modify+write under a single per-file lock, preventing
  lost-update races (two concurrent callers both reading the same
  baseline and one overwriting the other's update).

Implementation:

- Per-file ``threading.Lock`` registry keyed by the absolute path
- Registry access guarded by a master lock so concurrent first-access
  for a new path can't create duplicate locks
- Write goes through ``<path>.tmp`` + ``os.replace`` for atomicity
  within a filesystem (POSIX ``rename`` / Windows ``MoveFileEx``)

**In-process only**: writers in different processes do NOT see each
other's threading locks. For cross-process safety (e.g.
``ProcessPoolExecutor`` workers writing the same file) use OS-level
file locks at the call site — see ``fresh_slotlab.rawdata_index._cross_process_index_lock``
for the pattern using ``msvcrt.locking`` (Windows) / ``fcntl.flock`` (POSIX).

Cross-refs:

- ``session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md`` §4.2
- ``memory/feedback_md5_is_a_tag_not_a_destruction_signal.md`` — cache
  delete is a first-class op; this module's atomicity guarantees readers
  never see a half-written config that could trigger downstream
  wrong-path delete.
- ``memory/feedback_no_silent_swallow.md`` — failure modes are surfaced
  by raising; callers decide whether to persist a diagnostic.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable

# Per-file lock registry. Keyed by absolute path so different relative
# Path references to the same file share a single lock.
_FILE_LOCKS: dict[str, threading.Lock] = {}

# Master lock guards the registry itself (get-or-create of per-file
# locks). Concurrent first-access to two different paths in different
# threads must not produce two lock instances for the same key.
_REGISTRY_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    """Return the ``threading.Lock`` for ``path``, creating it on first
    access. Resolved absolute path is the key so different relative
    references to the same file share one lock instance.
    """
    key = str(Path(path).absolute())
    with _REGISTRY_GUARD:
        lock = _FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[key] = lock
        return lock


def atomic_json_write(
    path: Path,
    data: Any,
    *,
    trailing_newline: bool = False,
) -> None:
    """Atomic JSON write with per-file ``threading.Lock``.

    Concurrent in-process callers serialize per-path; different paths
    write in parallel. Readers never see a partial file — they see
    either the old version or the new (no mid-write truncation).

    Args:
        path: target file path
        data: any JSON-serializable value
        trailing_newline: append ``"\\n"`` after the JSON body (matches
            some pre-existing call sites that did so explicitly;
            default False to match ``json.dumps`` output exactly)
    """
    path = Path(path)
    lock = _lock_for(path)
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        if trailing_newline:
            payload += "\n"
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)


def atomic_json_read_modify_write(
    path: Path,
    modifier: Callable[[Any], Any],
    default: Any = None,
    *,
    trailing_newline: bool = False,
) -> Any:
    """Atomic read-modify-write with per-file ``threading.Lock``.

    The lock is held across the entire read → modify → write cycle so
    two concurrent callers serialize at this path. Without this, two
    callers could each read the same baseline, each apply their delta,
    and the second writer overwrites the first writer's update (the
    "lost update" race documented in Scenario 16 / Critical C1).

    ``modifier`` receives the current parsed JSON (or ``default`` if the
    file is missing or unparseable) and returns the new data to persist.
    Returns the persisted data so the caller can use it directly
    without re-reading.

    Args:
        path: target file path
        modifier: pure function ``current -> new_data``. Should not
            mutate ``current`` in place if ``default`` is a shared
            structure; treat its input as read-only.
        default: value passed to ``modifier`` when file is missing or
            corrupt. ``None`` is fine for most callers but watch out
            for downstream code that expects a dict — pass
            ``default={"key": []}`` shape explicitly when needed.
        trailing_newline: same semantics as ``atomic_json_write``
    """
    path = Path(path)
    lock = _lock_for(path)
    with lock:
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                current = default
        else:
            current = default
        new_data = modifier(current)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(new_data, ensure_ascii=False, indent=2)
        if trailing_newline:
            payload += "\n"
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
        return new_data
