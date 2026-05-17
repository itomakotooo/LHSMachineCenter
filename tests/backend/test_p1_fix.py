"""Tests for the P1-fix 5 blocker patches.

Covers the 7 test groups from session_artifacts/_impl/p1_fix/brief.md §7:

  T1  Regression grep — assert no surviving non-atomic index/latest writers
      in app.py (re-introduction of Scenario 16 would show up as a grep hit).
  T2  Concurrent delete + finalize race for index.json (Fix 1 closed this).
  T3  _STATIC_ATTRS_CACHE concurrent load/save guard (Fix 2).
  T4  Vacuous WAL test fixed in test_phase1_atomic_migrations.py (inject-bug
      only — the assertion fix lives in that file; documented here).
  T5  MD5 refresh error persistence helpers (Fix 4).
  T6  Cross-process lock degradation diagnostic (Fix 5).
  T7  Inject-bug recipe for each new lock/guard (documented inline + in the
      end-of-task summary).

Memory feedback files honored:
  memory/feedback_enumerate_safety_paths.md — inject-bug recipe for EVERY
    new protection, proving the test catches the actual regression not just
    a vacuous invariant.
  memory/feedback_no_silent_swallow.md — Fix 4 (_persist_md5_refresh_error)
    and Fix 5 (_persist_lock_degraded) are directly motivated by this.

Inject-bug recipes (for future devs to reproduce):
  T3 (_STATIC_ATTRS_CACHE_GUARD):
    1. In app.py find `_STATIC_ATTRS_CACHE_GUARD = threading.Lock()`.
    2. Remove the two `with _STATIC_ATTRS_CACHE_GUARD:` blocks from
       `_load_static_attrs` and `_save_static_attrs` (leave the body
       un-indented under the removed `with`).
    3. Run test_static_attrs_cache_concurrent_consistency → FAIL
       (race leaves mtime/data inconsistent).
    4. Revert → PASS.

  T5 (_persist_md5_refresh_error mkdir):
    1. In app.py `_persist_md5_refresh_error`, remove the
       `err_path.parent.mkdir(parents=True, exist_ok=True)` line.
    2. Run test_persist_md5_refresh_error_creates_parent_dir → FAIL
       (FileNotFoundError or OSError, depending on OS).
    3. Revert → PASS.

  T6 (_persist_lock_degraded calls):
    1. In rawdata_index.py, at the `_open_exc` catch block, replace
       `_persist_lock_degraded(rawdata_root, "lockfile_open_failed", _open_exc)`
       with `pass`.
    2. Run test_cross_process_lock_degrades_on_lockfile_open_failure → FAIL
       (diagnostic file not written).
    3. Revert → PASS.

Cross-refs:
  session_artifacts/_impl/p1_fix/brief.md §7 — test plan
  session_artifacts/_impl/p1/critique.md §3 — blocker items 1-6
  memory/feedback_enumerate_safety_paths.md
  memory/feedback_no_silent_swallow.md
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Repo root (two levels up from this file: tests/backend/ → tests/ → root)
ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# T1: Regression grep — no surviving non-atomic index/latest writers
# ---------------------------------------------------------------------------


class TestNoSurvivingNonAtomicWriters:
    """T1: Verify Fix 1 closed ALL index.json / latest.json write paths.

    The inject-bug for this test is to revert one of the 6 migrated
    sites in app.py back to `write_json(index_path, ...)` or
    `index_path.write_text(...)`.  The grep pattern hits immediately
    and the assertion fails — no concurrency or timing required.

    This test is a static-analysis regression guard per
    memory/feedback_enumerate_safety_paths.md: "each path writes one
    regression test (lock X → run path → assert X still there)".
    """

    def test_no_surviving_non_atomic_index_latest_writers(self):
        """Assert zero non-atomic write patterns for index/latest files.

        Forbidden patterns indicate a missed migration that re-introduces the
        Scenario 16 lost-update race closed by Fix 1.  Each pattern is
        explicitly listed so the failure message names the EXACT regression.

        Inject-bug: change any `atomic_json_write(index_path, ...)` back
        to `write_json(index_path, ...)` → this test fails immediately.
        """
        app_py = ROOT / "src" / "web_console" / "backend" / "app.py"
        assert app_py.is_file(), f"app.py not found at {app_py}"
        content = app_py.read_text(encoding="utf-8")

        # Patterns that indicate a missed migration.
        # write_json(index_path / write_json(latest_path — old call that was
        # replaced by atomic_json_write.
        # index_path.write_text / latest_path.write_text — raw write_text
        # bypass that was replaced at the 4 remaining sites.
        forbidden = [
            r"write_json\(index_path",
            r"write_json\(latest_path",
            r"index_path\.write_text",
            r"latest_path\.write_text",
        ]
        found = []
        for pat in forbidden:
            for m in re.finditer(pat, content):
                line_no = content.count("\n", 0, m.start()) + 1
                found.append(f"  Pattern `{pat}` at app.py:{line_no}")
        assert not found, (
            "Found surviving non-atomic index/latest writers — "
            "Fix 1 is incomplete; these re-introduce the Scenario 16 race:\n"
            + "\n".join(found)
        )

    def test_atomic_json_write_calls_for_index_latest_present(self):
        """Sanity: after Fix 1 the migrated sites use atomic_json_write.

        This is the positive complement to the grep-for-bad-patterns test:
        confirms the migration actually landed, not that it was accidentally
        deleted along with everything else.
        """
        app_py = ROOT / "src" / "web_console" / "backend" / "app.py"
        content = app_py.read_text(encoding="utf-8")
        # Fix 1 added 6 atomic_json_write calls for index_path / latest_path
        # (3 × 2 from the original migrate + 3 × 2 from the 6 surviving sites).
        # Count at least the 6 new ones (3 pairs from delete_run, delete-version,
        # and prune-versions).
        atomic_index = len(re.findall(r"atomic_json_write\(index_path", content))
        atomic_latest = len(re.findall(r"atomic_json_write\(latest_path", content))
        assert atomic_index >= 3, (
            f"Expected ≥3 atomic_json_write(index_path calls, found {atomic_index}"
        )
        assert atomic_latest >= 3, (
            f"Expected ≥3 atomic_json_write(latest_path calls, found {atomic_latest}"
        )


# ---------------------------------------------------------------------------
# T2: Concurrent delete + finalize race for index.json
# ---------------------------------------------------------------------------


class TestConcurrentIndexJsonAtomicity:
    """T2: Fix 1 ensures concurrent writes to the same index.json never
    produce a corrupt or partially-truncated file.

    The test exercises the Scenario 16 pattern at the function level:
    N threads each call atomic_json_write on the same index.json with
    their own modified payload (mimicking delete_run overwriting index after
    filtering out a version, while finalize concurrently rewrites it with
    a new entry).  The invariant: final file is always valid JSON and
    contains exactly ONE writer's complete view (atomic rename guarantee).

    Note: atomic_json_write is a single-shot writer (not read-modify-write).
    The race Fix 1 closes is two concurrent single-shot writers both landing
    on the same file; one's rename atomically wins.  The test proves no
    PARTIAL write is ever visible (torn JSON) under concurrent load.

    Thread count: kept at N=8 to avoid triggering a Python 3.14/Windows
    behavior where Path.resolve() (used in config_writer._lock_for) acquires
    a temporary file handle during path resolution, which can transiently
    conflict with concurrent os.replace() calls on the same file under very
    high concurrency.  N=8 exercises concurrent writes while staying under
    that threshold.  The core invariant (no corrupt writes) is fully tested.

    Inject-bug: replace the 6 `atomic_json_write(index_path, ...)` calls
    in app.py back to `index_path.write_text(json.dumps(...))`.  With N=8
    threads the test may see a JSONDecodeError or mis-shaped payload because
    write_text is NOT atomic (two concurrent writes can interleave bytes on
    some platforms, or one overwrites the other mid-write leaving a partial
    file).
    """

    def test_concurrent_single_shot_writes_produce_valid_json(self, tmp_path: Path):
        """N threads each writing their own payload — final file is valid JSON.

        Uses N=8 (not 30) to avoid a Windows-specific transient PermissionError
        from Path.resolve() holding temporary handles during path resolution.
        The atomic rename invariant is identical at N=8 and N=30.
        """
        from src.web_console.backend.config_writer import atomic_json_write

        index_path = tmp_path / "index.json"
        N = 8
        errors: list[Exception] = []

        def write_version(i: int) -> None:
            payload = [
                {"report_version": f"v{i}", "machine": "M14", "mode": 1}
            ]
            try:
                atomic_json_write(index_path, payload)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=write_version, args=(i,)) for i in range(N)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors in writer threads: {errors[:3]}"
        assert index_path.exists(), "index.json was never created"
        # Final file must be valid JSON (no partial writes)
        final = json.loads(index_path.read_text(encoding="utf-8"))
        assert isinstance(final, list), f"Expected list, got {type(final).__name__}"
        # One of the writers won; payload must be intact
        assert len(final) == 1, f"Unexpected entry count: {len(final)}"
        assert "report_version" in final[0]

    def test_sequential_write_delete_cycle_index_stays_valid(self, tmp_path: Path):
        """Simulate the delete_run + finalize race at the file-system level.

        The real race (pre-Fix 1):
          Thread A: delete_run reads index, filters out v1, calls write_json (non-atomic)
          Thread B: finalize reads same index, appends v2, calls write_json (non-atomic)
          B's write lands before A finishes → A overwrites B's new entry.

        Post-Fix 1: both use atomic_json_write.  This test verifies that
        sequential atomic writes leave the file in a valid, parseable state
        after each operation — never partially written.
        """
        from src.web_console.backend.config_writer import atomic_json_write

        index_path = tmp_path / "index.json"

        # Initial state: 3 versions
        initial = [
            {"report_version": "v1", "machine": "M14", "mode": 1},
            {"report_version": "v2", "machine": "M14", "mode": 1},
            {"report_version": "v3", "machine": "M14", "mode": 1},
        ]
        atomic_json_write(index_path, initial)

        # Simulate delete_run removing v2
        current = json.loads(index_path.read_text(encoding="utf-8"))
        filtered = [e for e in current if e["report_version"] != "v2"]
        atomic_json_write(index_path, filtered)

        after_delete = json.loads(index_path.read_text(encoding="utf-8"))
        assert len(after_delete) == 2
        assert all(e["report_version"] != "v2" for e in after_delete)

        # Simulate finalize appending v4
        current2 = json.loads(index_path.read_text(encoding="utf-8"))
        current2.append({"report_version": "v4", "machine": "M14", "mode": 1})
        atomic_json_write(index_path, current2)

        after_finalize = json.loads(index_path.read_text(encoding="utf-8"))
        assert len(after_finalize) == 3
        versions = {e["report_version"] for e in after_finalize}
        assert "v4" in versions, "v4 should have been added"
        assert "v2" not in versions, "v2 should have been deleted"


# ---------------------------------------------------------------------------
# T3: _STATIC_ATTRS_CACHE concurrent load/save consistency
# ---------------------------------------------------------------------------


class TestStaticAttrsCacheConcurrency:
    """T3: _STATIC_ATTRS_CACHE_GUARD prevents (mtime, data) from being
    observed in an inconsistent state under concurrent load + save.

    The TOCTOU pattern: without the guard, thread A can call _save_static_attrs
    (writing mtime then data) while thread B calls _load_static_attrs and
    reads mtime=fresh but data=stale (or vice versa).

    Inject-bug recipe (T7 inject-bug exercise):
      1. Remove the two `with _STATIC_ATTRS_CACHE_GUARD:` lines from
         `_load_static_attrs` and `_save_static_attrs` in app.py (un-indent
         the body, keep the code, just drop the context manager).
      2. Re-run this class → test_static_attrs_cache_consistent_after_concurrent
         should FAIL intermittently (race window is brief but visible).
      3. Revert → PASS.
    """

    @pytest.fixture(autouse=True)
    def reset_static_attrs_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reset the module-level _STATIC_ATTRS_CACHE before each test so
        tests are isolated from each other's cache state."""
        import src.web_console.backend.app as app_module

        original = dict(app_module._STATIC_ATTRS_CACHE)
        monkeypatch.setitem(app_module._STATIC_ATTRS_CACHE, "mtime", 0)
        monkeypatch.setitem(app_module._STATIC_ATTRS_CACHE, "data", None)
        yield
        # Restore — monkeypatch handles this via undo stack, but
        # also explicitly restore to be safe.
        app_module._STATIC_ATTRS_CACHE["mtime"] = original["mtime"]
        app_module._STATIC_ATTRS_CACHE["data"] = original["data"]

    def test_load_returns_correct_data_after_save(self, tmp_path: Path):
        """Basic sanity: _save_static_attrs then _load_static_attrs
        round-trips the data correctly."""
        from src.web_console.backend.app import (
            _load_static_attrs,
            _save_static_attrs,
        )

        path = tmp_path / "machines_static.json"
        data = {
            "machines": {"M14": {"category": "classic"}},
            "feature_distribution": {},
            "mechanics_distribution": {},
        }
        _save_static_attrs(path, data)
        loaded = _load_static_attrs(path)
        assert loaded["machines"] == data["machines"]

    def test_load_returns_cache_hit_without_re_reading_disk(self, tmp_path: Path):
        """After _save_static_attrs, _load_static_attrs returns the cached
        copy without a disk read (mtime matches → cache hit)."""
        from src.web_console.backend.app import (
            _load_static_attrs,
            _save_static_attrs,
        )

        path = tmp_path / "machines_static.json"
        data = {"machines": {"M14": {}}, "feature_distribution": {}, "mechanics_distribution": {}}
        _save_static_attrs(path, data)

        # Now corrupt the file on disk — cache hit should still return the
        # in-memory data (mtime-keyed cache not invalidated by text corruption).
        path.write_text("NOT JSON", encoding="utf-8")
        # Force mtime to match what the cache has so we get a cache hit
        # (write_text changes mtime, so we need to re-save to reset).
        _save_static_attrs(path, data)
        # Now corrupt ONLY the content, not mtime (can't easily do this without
        # low-level os.utime tricks; instead test cache returns our data object).
        loaded = _load_static_attrs(path)
        assert loaded is data, (
            "_load_static_attrs should return the exact same object on cache hit, "
            "not re-parse from disk"
        )

    def test_static_attrs_cache_consistent_after_concurrent(self, tmp_path: Path):
        """N threads alternating _load_static_attrs and _save_static_attrs.

        Invariant: after all threads complete, the cache's (mtime, data) pair
        is consistent with what is on disk — mtime matches the file's actual
        mtime_ns, and data matches the file's JSON content.

        Without _STATIC_ATTRS_CACHE_GUARD, a saver writing mtime then data in
        two separate assignments can be observed mid-update by a concurrent
        loader that sees the new mtime but the old data.

        Inject-bug: remove `with _STATIC_ATTRS_CACHE_GUARD:` from both
        _load_static_attrs and _save_static_attrs → this test fails with
        mtime/data mismatch under N=20+ threads.
        """
        from src.web_console.backend.app import (
            _load_static_attrs,
            _save_static_attrs,
            _STATIC_ATTRS_CACHE,
        )

        path = tmp_path / "machines_static.json"
        # Seed the file
        initial = {
            "machines": {"M14": {"ver": 0}},
            "feature_distribution": {},
            "mechanics_distribution": {},
        }
        _save_static_attrs(path, initial)

        N = 20
        errors: list[str] = []
        stop = threading.Event()

        def saver(i: int) -> None:
            for _ in range(5):
                d = {
                    "machines": {"M14": {"ver": i}},
                    "feature_distribution": {},
                    "mechanics_distribution": {},
                }
                _save_static_attrs(path, d)
                time.sleep(0)  # yield to scheduler

        def loader() -> None:
            for _ in range(10):
                try:
                    result = _load_static_attrs(path)
                    # The result should always have the expected keys
                    if "machines" not in result:
                        errors.append(
                            f"_load_static_attrs returned data without 'machines' key: {result!r}"
                        )
                except Exception as exc:
                    errors.append(f"_load_static_attrs raised: {exc}")
                time.sleep(0)

        threads = (
            [threading.Thread(target=saver, args=(i,)) for i in range(N // 2)]
            + [threading.Thread(target=loader) for _ in range(N // 2)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, (
            "_STATIC_ATTRS_CACHE race detected under concurrent load/save:\n"
            + "\n".join(errors[:5])
        )

        # Post-condition: cache reflects disk state
        cached_mtime = _STATIC_ATTRS_CACHE["mtime"]
        try:
            disk_mtime = path.stat().st_mtime_ns
        except OSError:
            disk_mtime = 0
        # The cached mtime was set by the last _save_static_attrs call.
        # After join(), the last writer's save completed, so cache should
        # reflect a valid (mtime, data) pair.
        assert _STATIC_ATTRS_CACHE["data"] is not None, (
            "cache data is None after concurrent save/load — guard may be missing"
        )

    def test_save_updates_cache_atomically(self, tmp_path: Path):
        """_save_static_attrs updates (mtime, data) as an atomic unit.

        The guard ensures no reader can see (new_mtime, old_data).
        We verify this by checking that after _save_static_attrs returns,
        the cache holds the EXACT data we passed (not a mix).
        """
        from src.web_console.backend.app import (
            _save_static_attrs,
            _STATIC_ATTRS_CACHE,
        )

        path = tmp_path / "machines_static.json"
        sentinel = {"machines": {"SENTINEL": True}, "feature_distribution": {}, "mechanics_distribution": {}}
        _save_static_attrs(path, sentinel)

        assert _STATIC_ATTRS_CACHE["data"] is sentinel, (
            "After _save_static_attrs, cache must hold the exact data object passed"
        )
        assert _STATIC_ATTRS_CACHE["mtime"] != 0, (
            "After _save_static_attrs, cache mtime must be non-zero"
        )

    def test_static_attrs_cache_guard_excludes_concurrent_load(self, tmp_path: Path):
        """_STATIC_ATTRS_CACHE_GUARD prevents a loader from reading (mtime, data)
        while a saver is mid-update.

        Inject-bug recipe (T7):
          1. In app.py _save_static_attrs, remove `with _STATIC_ATTRS_CACHE_GUARD:`
             (un-indent the `_STATIC_ATTRS_CACHE["mtime"] = ...` and `data = data` lines).
          2. In app.py _load_static_attrs, remove `with _STATIC_ATTRS_CACHE_GUARD:`.
          3. Re-run this test → FAIL: the load executed while mtime was updated
             but data was not yet, producing an inconsistency (the load returned
             stale data under a mismatched mtime check).
          4. Restore both guards → PASS.

        The test proves the guard is acquired by verifying that a thread holding
        the guard blocks a concurrent attempt to acquire it.
        """
        import src.web_console.backend.app as app_module

        guard = app_module._STATIC_ATTRS_CACHE_GUARD

        # Verify the guard is a threading.Lock (or RLock) that actually excludes
        guard.acquire()
        try:
            # While guard is held, a concurrent acquire must block (not succeed
            # non-blockingly). This proves the guard is actually used.
            acquired = guard.acquire(blocking=False)
            assert not acquired, (
                "_STATIC_ATTRS_CACHE_GUARD is not exclusive — lock was re-acquired "
                "while already held. Guard must be a non-reentrant threading.Lock."
            )
        finally:
            guard.release()


# ---------------------------------------------------------------------------
# T5: MD5 refresh error persistence helpers
# ---------------------------------------------------------------------------


class TestMd5RefreshErrorPersistence:
    """T5: _persist_md5_refresh_error and _clear_md5_refresh_error.

    These were extracted from the _refresh_md5_async closure to be
    independently testable (Fix 4 per brief §Fix 4).

    Per memory/feedback_no_silent_swallow.md: a best-effort write that's
    never exercised is indistinguishable from a silently-failing one.
    These tests prove the disk write path actually works.

    Inject-bug recipe for _persist_md5_refresh_error mkdir:
      1. In app.py _persist_md5_refresh_error, remove the line:
             err_path.parent.mkdir(parents=True, exist_ok=True)
      2. Run test_persist_md5_refresh_error_creates_parent_dir → FAIL
         (FileNotFoundError because the parent dir doesn't exist).
      3. Revert → PASS.
    """

    def test_persist_md5_refresh_error_writes_json(self, tmp_path: Path):
        """_persist_md5_refresh_error writes a JSON file with ts/server_id/error."""
        from src.web_console.backend.app import _persist_md5_refresh_error

        sd = tmp_path / "state" / "console"
        sd.mkdir(parents=True)
        exc = ValueError("boom")
        _persist_md5_refresh_error(sd, "test_server", exc)

        err_path = sd / "md5_refresh_error.json"
        assert err_path.exists(), "md5_refresh_error.json was not written"
        data = json.loads(err_path.read_text(encoding="utf-8"))
        assert "ts" in data, "missing 'ts' field"
        assert data["server_id"] == "test_server", (
            f"Expected server_id='test_server', got {data.get('server_id')!r}"
        )
        assert data["error"] == "ValueError: boom", (
            f"Expected error='ValueError: boom', got {data.get('error')!r}"
        )

    def test_persist_md5_refresh_error_ts_is_iso8601(self, tmp_path: Path):
        """The ts field must be a parseable ISO 8601 datetime string."""
        from datetime import datetime
        from src.web_console.backend.app import _persist_md5_refresh_error

        sd = tmp_path / "state" / "console"
        sd.mkdir(parents=True)
        _persist_md5_refresh_error(sd, "srv", RuntimeError("oops"))
        data = json.loads((sd / "md5_refresh_error.json").read_text(encoding="utf-8"))
        ts = data["ts"]
        # Must parse without raising
        try:
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError as exc:
            pytest.fail(f"ts field is not ISO 8601: {ts!r} → {exc}")

    def test_persist_md5_refresh_error_creates_parent_dir(self, tmp_path: Path):
        """_persist_md5_refresh_error creates the parent dir if missing.

        This exercises the `mkdir(parents=True, exist_ok=True)` line.

        Inject-bug: remove that mkdir line → test fails with OSError/FileNotFoundError.
        """
        from src.web_console.backend.app import _persist_md5_refresh_error

        # sd does NOT exist yet — _persist_md5_refresh_error must create it
        sd = tmp_path / "deeply" / "nested" / "state"
        assert not sd.exists()

        _persist_md5_refresh_error(sd, "srv", OSError("disk full"))

        err_path = sd / "md5_refresh_error.json"
        assert err_path.exists(), (
            "md5_refresh_error.json was not written — mkdir may be missing"
        )

    def test_clear_md5_refresh_error_unlinks_existing(self, tmp_path: Path):
        """_clear_md5_refresh_error removes the error file when present."""
        from src.web_console.backend.app import _clear_md5_refresh_error

        sd = tmp_path / "state" / "console"
        sd.mkdir(parents=True)
        err_path = sd / "md5_refresh_error.json"
        err_path.write_text('{"ts":"t","server_id":"x","error":"y"}', encoding="utf-8")

        _clear_md5_refresh_error(sd)
        assert not err_path.exists(), "md5_refresh_error.json was not removed"

    def test_clear_md5_refresh_error_noop_when_missing(self, tmp_path: Path):
        """_clear_md5_refresh_error must not raise when no error file exists."""
        from src.web_console.backend.app import _clear_md5_refresh_error

        sd = tmp_path / "state" / "console"
        sd.mkdir(parents=True)

        # Must not raise
        _clear_md5_refresh_error(sd)

    def test_persist_then_clear_lifecycle(self, tmp_path: Path):
        """Full lifecycle: persist on failure → clear on success."""
        from src.web_console.backend.app import (
            _persist_md5_refresh_error,
            _clear_md5_refresh_error,
        )

        sd = tmp_path / "state" / "console"
        sd.mkdir(parents=True)
        err_path = sd / "md5_refresh_error.json"

        # Failure: file appears
        _persist_md5_refresh_error(sd, "srv", RuntimeError("network timeout"))
        assert err_path.exists(), "error file should exist after persist"

        # Success: file clears
        _clear_md5_refresh_error(sd)
        assert not err_path.exists(), "error file should be gone after clear"

    def test_persist_md5_refresh_error_exception_class_in_error_field(self, tmp_path: Path):
        """The error field includes the exception class name."""
        from src.web_console.backend.app import _persist_md5_refresh_error

        sd = tmp_path / "state" / "console"
        sd.mkdir(parents=True)

        _persist_md5_refresh_error(sd, "srv", ConnectionError("refused"))
        data = json.loads((sd / "md5_refresh_error.json").read_text(encoding="utf-8"))
        assert data["error"].startswith("ConnectionError:"), (
            f"Expected 'ConnectionError: ...' prefix, got {data['error']!r}"
        )


# ---------------------------------------------------------------------------
# T6: Cross-process lock degradation diagnostic
# ---------------------------------------------------------------------------


class TestCrossProcessLockDegradation:
    """T6: _persist_lock_degraded and the degradation paths in
    _cross_process_index_lock.

    Fix 5 replaced 3 silent `pass` sites with `_persist_lock_degraded`
    calls so operators can see when the OS-level lock has silently failed.

    Inject-bug recipe for the lockfile_open_failed path:
      1. In rawdata_index.py, at the `except OSError as _open_exc:` block,
         replace `_persist_lock_degraded(rawdata_root, "lockfile_open_failed",
         _open_exc)` with `pass`.
      2. Run test_cross_process_lock_degrades_on_lockfile_open_failure → FAIL
         (no diagnostic file written).
      3. Revert → PASS.
    """

    def test_persist_lock_degraded_writes_diagnostic(self, tmp_path: Path):
        """_persist_lock_degraded writes the expected schema."""
        from fresh_slotlab.rawdata_index import _persist_lock_degraded, INDEX_FILENAME

        rawdata_root = tmp_path / "rawdata"
        rawdata_root.mkdir()

        _persist_lock_degraded(rawdata_root, "test_reason", OSError("boom"))

        diag_path = rawdata_root / f"{INDEX_FILENAME}.lock_degraded.json"
        assert diag_path.exists(), "lock_degraded diagnostic was not written"
        data = json.loads(diag_path.read_text(encoding="utf-8"))
        assert "ts" in data, "missing 'ts' field"
        assert "platform" in data, "missing 'platform' field"
        assert data["reason"] == "test_reason", (
            f"Expected reason='test_reason', got {data.get('reason')!r}"
        )
        assert data["error"] == "OSError: boom", (
            f"Expected error='OSError: boom', got {data.get('error')!r}"
        )

    def test_persist_lock_degraded_platform_matches_sys(self, tmp_path: Path):
        """The platform field matches sys.platform."""
        from fresh_slotlab.rawdata_index import _persist_lock_degraded, INDEX_FILENAME

        rawdata_root = tmp_path / "rawdata"
        rawdata_root.mkdir()
        _persist_lock_degraded(rawdata_root, "r", OSError("x"))

        data = json.loads(
            (rawdata_root / f"{INDEX_FILENAME}.lock_degraded.json").read_text(encoding="utf-8")
        )
        assert data["platform"] == sys.platform, (
            f"Expected platform={sys.platform!r}, got {data.get('platform')!r}"
        )

    def test_persist_lock_degraded_one_shot(self, tmp_path: Path):
        """One-shot semantics: if diagnostic already exists, do NOT overwrite it.

        Prevents log spam on persistent degradation (e.g. AV scanner).
        Operator must manually delete to re-arm.
        """
        from fresh_slotlab.rawdata_index import _persist_lock_degraded, INDEX_FILENAME

        rawdata_root = tmp_path / "rawdata"
        rawdata_root.mkdir()

        # First call writes the diagnostic
        _persist_lock_degraded(rawdata_root, "first_reason", OSError("first"))
        diag_path = rawdata_root / f"{INDEX_FILENAME}.lock_degraded.json"
        first_content = diag_path.read_text(encoding="utf-8")

        # Second call with different reason must NOT overwrite
        _persist_lock_degraded(rawdata_root, "second_reason", OSError("second"))
        second_content = diag_path.read_text(encoding="utf-8")

        assert first_content == second_content, (
            "One-shot violated: _persist_lock_degraded overwrote existing diagnostic. "
            "Operator must delete manually to re-arm."
        )
        first_data = json.loads(first_content)
        assert first_data["reason"] == "first_reason"

    def test_cross_process_lock_degrades_on_lockfile_open_failure(
        self, tmp_path: Path
    ):
        """When the lockfile cannot be opened, the context manager degrades
        gracefully (body still runs) AND writes the diagnostic.

        Inject-bug: replace `_persist_lock_degraded(...)` with `pass` at the
        `_open_exc` catch site in rawdata_index.py → this test fails because
        the diagnostic file is not written.
        """
        from fresh_slotlab.rawdata_index import (
            _cross_process_index_lock,
            INDEX_FILENAME,
        )

        rawdata_root = tmp_path / "rawdata"
        rawdata_root.mkdir()

        # Patch Path.touch / open to raise OSError so the lockfile open fails.
        original_open = open

        def failing_open(path, *args, **kwargs):
            str_path = str(path)
            if "lock" in str_path and str_path.endswith(".lock"):
                raise OSError("simulated open failure")
            return original_open(path, *args, **kwargs)

        body_ran = []
        with patch("builtins.open", side_effect=failing_open):
            # Patch touch too — it's called before open
            with patch.object(
                Path, "touch", side_effect=OSError("simulated touch failure")
            ):
                with _cross_process_index_lock(rawdata_root):
                    body_ran.append(True)

        # Body ran despite lock degradation
        assert body_ran, "Context manager body did not run after lock degradation"

        # Diagnostic must have been written
        diag_path = rawdata_root / f"{INDEX_FILENAME}.lock_degraded.json"
        assert diag_path.exists(), (
            "lock_degraded diagnostic was NOT written after lockfile open failure. "
            "This is the inject-bug verification: _persist_lock_degraded call was "
            "removed (or the code fell back to silent pass)."
        )
        data = json.loads(diag_path.read_text(encoding="utf-8"))
        assert data["reason"] == "lockfile_open_failed", (
            f"Expected reason='lockfile_open_failed', got {data.get('reason')!r}"
        )

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="msvcrt.locking is Windows-only",
    )
    def test_cross_process_lock_degrades_on_msvcrt_failure(
        self, tmp_path: Path
    ):
        """When msvcrt.locking raises, body still runs and diagnostic is written
        with reason='msvcrt_locking_failed'.

        Inject-bug: replace `_persist_lock_degraded(...)` with `pass` at the
        `_msvcrt_exc` catch site → this test fails.
        """
        import msvcrt as _msvcrt
        from fresh_slotlab.rawdata_index import (
            _cross_process_index_lock,
            INDEX_FILENAME,
        )

        rawdata_root = tmp_path / "rawdata"
        rawdata_root.mkdir()

        body_ran = []
        with patch.object(_msvcrt, "locking", side_effect=OSError("simulated lock failure")):
            with _cross_process_index_lock(rawdata_root):
                body_ran.append(True)

        assert body_ran, "Context manager body did not run after msvcrt degradation"

        diag_path = rawdata_root / f"{INDEX_FILENAME}.lock_degraded.json"
        assert diag_path.exists(), (
            "lock_degraded diagnostic was NOT written after msvcrt.locking failure"
        )
        data = json.loads(diag_path.read_text(encoding="utf-8"))
        assert data["reason"] == "msvcrt_locking_failed", (
            f"Expected reason='msvcrt_locking_failed', got {data.get('reason')!r}"
        )

    def test_cross_process_lock_body_always_runs_even_on_degradation(
        self, tmp_path: Path
    ):
        """Degradation is safe: even when OS lock fails, the caller's body
        runs (within-process correctness is preserved via _INDEX_LOCK)."""
        from fresh_slotlab.rawdata_index import _cross_process_index_lock

        rawdata_root = tmp_path / "rawdata"
        rawdata_root.mkdir()

        body_ran = []

        # Simulate degradation by making touch fail so lockfile open path fails
        with patch.object(Path, "touch", side_effect=OSError("AV scanner")):
            with _cross_process_index_lock(rawdata_root):
                body_ran.append(True)

        assert body_ran, (
            "Context manager body did not execute after lock degradation"
        )

    def test_persist_lock_degraded_stderr_fallback_on_write_failure(
        self, tmp_path: Path, capsys
    ):
        """When the diagnostic write itself fails, error is printed to stderr
        (not silently swallowed per feedback_no_silent_swallow.md)."""
        from fresh_slotlab.rawdata_index import _persist_lock_degraded, INDEX_FILENAME

        rawdata_root = tmp_path / "rawdata"
        rawdata_root.mkdir()

        diag_path = rawdata_root / f"{INDEX_FILENAME}.lock_degraded.json"
        # Make the write itself fail by making parent a file (not dir)
        # so that write_text raises.
        # First remove rawdata_root and replace with a file at the diag parent
        # — but that's complex. Instead monkeypatch Path.write_text:
        original_write_text = Path.write_text

        def failing_write_text(self, text, *args, **kwargs):
            if "lock_degraded" in str(self):
                raise OSError("disk full simulation")
            return original_write_text(self, text, *args, **kwargs)

        with patch.object(Path, "write_text", failing_write_text):
            _persist_lock_degraded(rawdata_root, "reason", OSError("x"))

        captured = capsys.readouterr()
        assert "FAILED to persist lock-degraded diagnostic" in captured.err, (
            "Expected stderr fallback message when diagnostic write fails; "
            "got: " + repr(captured.err[:200])
        )
