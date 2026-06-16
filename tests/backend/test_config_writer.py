"""Tests for the Phase 1 deploy atomic JSON writers.

Covers:
- ``atomic_json_write`` — basic atomic semantics + no .tmp leftover
- ``atomic_json_read_modify_write`` — basic; missing file → default;
  corrupt file → default; returns persisted data
- Concurrent serialization — N threads writing same path produce a
  consistent final state (one writer wins; readers never see partial
  data because of os.replace atomicity)
- Concurrent read-modify-write — N threads each appending to a list
  produce all N items in the final file (the lock prevents the
  lost-update race that motivated Critical C1 / Scenario 16)

Inject-bug verification protocol (per
``memory/feedback_enumerate_safety_paths.md``):
- The concurrent-rmw test is the "would-have-caught-Scenario-16"
  regression. Manual inject-bug: remove the ``with lock`` from
  ``atomic_json_read_modify_write`` in ``config_writer.py`` and rerun
  this test → ``test_concurrent_rmw_no_lost_updates`` must fail with
  fewer than 50 items in the final file. Restore the lock → green.
  This proves the test catches the actual hazard, not just an
  abstract invariant.

Cross-refs:
- ``session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md`` §4.2
- ``memory/feedback_enumerate_safety_paths.md`` — inject-bug verification
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from src.web_console.backend.config_writer import (
    atomic_json_read_modify_write,
    atomic_json_write,
)
from src.web_console.backend import config_writer as _cw


class TestAtomicReplaceRetry:
    """os.replace transiently fails with PermissionError on Windows when the
    target is open by a concurrent reader; the write must retry, not 500."""

    def test_retries_permission_error_then_succeeds(self, tmp_path: Path, monkeypatch):
        p = tmp_path / "machines.json"
        atomic_json_write(p, {"v": 0})  # seed
        calls = {"n": 0}
        real_replace = os.replace

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] <= 3:  # fail the first 3, succeed on the 4th
                raise PermissionError(13, "target open by reader")
            return real_replace(src, dst)

        monkeypatch.setattr(_cw.os, "replace", flaky_replace)
        monkeypatch.setattr(_cw, "_REPLACE_BACKOFF_S", 0.0)  # no sleep in test
        atomic_json_write(p, {"v": 1})  # must NOT raise
        assert json.loads(p.read_text()) == {"v": 1}
        assert calls["n"] == 4  # 3 retries + 1 success

    def test_reraises_after_exhausting_retries(self, tmp_path: Path, monkeypatch):
        p = tmp_path / "machines.json"
        atomic_json_write(p, {"v": 0})

        def always_fail(src, dst):
            raise PermissionError(13, "perpetually locked")

        monkeypatch.setattr(_cw.os, "replace", always_fail)
        monkeypatch.setattr(_cw, "_REPLACE_BACKOFF_S", 0.0)
        with pytest.raises(PermissionError):  # surfaced, never swallowed
            atomic_json_write(p, {"v": 1})


class TestAtomicJsonWrite:
    def test_writes_dict(self, tmp_path: Path):
        p = tmp_path / "test.json"
        atomic_json_write(p, {"a": 1, "b": "x"})
        assert json.loads(p.read_text()) == {"a": 1, "b": "x"}

    def test_writes_list(self, tmp_path: Path):
        p = tmp_path / "test.json"
        atomic_json_write(p, [1, 2, 3])
        assert json.loads(p.read_text()) == [1, 2, 3]

    def test_creates_parent_dir(self, tmp_path: Path):
        p = tmp_path / "subdir" / "nested" / "test.json"
        atomic_json_write(p, {})
        assert p.is_file()

    def test_no_tmp_leftover(self, tmp_path: Path):
        p = tmp_path / "test.json"
        atomic_json_write(p, {"x": 1})
        # The tmp file is os.replace'd into target; no leftover.
        assert not (tmp_path / "test.json.tmp").exists()

    def test_overwrites_existing(self, tmp_path: Path):
        p = tmp_path / "test.json"
        atomic_json_write(p, {"v": 1})
        atomic_json_write(p, {"v": 2})
        assert json.loads(p.read_text()) == {"v": 2}

    def test_trailing_newline_added(self, tmp_path: Path):
        p = tmp_path / "test.json"
        atomic_json_write(p, {"a": 1}, trailing_newline=True)
        content = p.read_text()
        assert content.endswith("\n")
        assert json.loads(content) == {"a": 1}

    def test_trailing_newline_default_off(self, tmp_path: Path):
        p = tmp_path / "test.json"
        atomic_json_write(p, {"a": 1})
        content = p.read_text()
        # json.dumps doesn't add trailing newline; default off preserves that
        assert not content.endswith("\n")

    def test_unicode_preserved(self, tmp_path: Path):
        p = tmp_path / "test.json"
        atomic_json_write(p, {"name": "策划"})
        # Round-trip preserves Chinese (ensure_ascii=False in writer)
        assert json.loads(p.read_text(encoding="utf-8"))["name"] == "策划"


class TestAtomicJsonReadModifyWrite:
    def test_basic_rmw(self, tmp_path: Path):
        p = tmp_path / "test.json"
        atomic_json_write(p, {"count": 1})
        result = atomic_json_read_modify_write(
            p, lambda cur: {"count": cur["count"] + 1}
        )
        assert result == {"count": 2}
        assert json.loads(p.read_text()) == {"count": 2}

    def test_missing_file_passes_default(self, tmp_path: Path):
        p = tmp_path / "missing.json"
        result = atomic_json_read_modify_write(
            p,
            lambda cur: {"items": (cur or {}).get("items", []) + ["x"]},
            default={"items": []},
        )
        assert result == {"items": ["x"]}

    def test_corrupt_file_passes_default(self, tmp_path: Path):
        p = tmp_path / "corrupt.json"
        p.write_text("not valid json {{{", encoding="utf-8")
        result = atomic_json_read_modify_write(
            p, lambda cur: {"recovered": True}, default={"empty": True}
        )
        assert result == {"recovered": True}
        # File is now valid JSON
        assert json.loads(p.read_text()) == {"recovered": True}

    def test_returns_persisted_data(self, tmp_path: Path):
        p = tmp_path / "test.json"
        result = atomic_json_read_modify_write(
            p, lambda cur: {"new": 42}, default={}
        )
        # Returned value matches what's on disk
        assert result == json.loads(p.read_text())

    def test_no_tmp_leftover(self, tmp_path: Path):
        p = tmp_path / "test.json"
        atomic_json_read_modify_write(
            p, lambda cur: {"v": 1}, default={}
        )
        assert not (tmp_path / "test.json.tmp").exists()


class TestConcurrentSerialization:
    """Phase 1 critical regression: Scenario 16 / Critical C1.

    Without per-file locks, two concurrent callers reading the same
    baseline + each appending their delta + each writing back results
    in the second writer overwriting the first writer's update. The
    lock makes them serialize so all updates persist.
    """

    def test_concurrent_writes_no_partial_files(self, tmp_path: Path):
        """Even without rmw, concurrent atomic_json_write must never
        leave the file in a partial state (atomic rename guarantees
        this; the test confirms os.replace works as expected)."""
        p = tmp_path / "shared.json"
        N = 30

        def writer(i: int) -> None:
            atomic_json_write(p, {"writer": i, "payload": list(range(i, i + 100))})

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Final state is one of the writers' values; never a partial JSON.
        final = json.loads(p.read_text())
        assert "writer" in final
        assert 0 <= final["writer"] < N
        assert len(final["payload"]) == 100

    def test_concurrent_rmw_no_lost_updates(self, tmp_path: Path):
        """The regression test that would have caught Scenario 16.

        N threads each append a unique integer to a list inside a JSON
        file via atomic_json_read_modify_write. The per-file lock must
        ensure all N integers are present in the final file (one
        writer's update is never overwritten by a stale-baseline write).

        Inject-bug check: remove the `with lock` from
        atomic_json_read_modify_write → this test fails with len < N.
        """
        p = tmp_path / "counter.json"
        atomic_json_write(p, {"items": []})

        N = 50

        def append_one(i: int) -> None:
            atomic_json_read_modify_write(
                p,
                lambda cur: {
                    "items": (cur if isinstance(cur, dict) else {}).get("items", []) + [i]
                },
                default={"items": []},
            )

        threads = [threading.Thread(target=append_one, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = json.loads(p.read_text())
        # All N items must be present; sorted to ignore order
        assert sorted(final["items"]) == list(range(N)), (
            f"Expected all {N} items present; got {len(final['items'])}: "
            f"{sorted(final['items'])[-5:]} (tail). "
            f"This is the Scenario 16 lost-update race."
        )

    def test_different_paths_dont_block_each_other(self, tmp_path: Path):
        """Per-file locks are per-PATH, not global. Two threads writing
        different files must run in parallel (this is mostly a smoke
        test — failing means we accidentally introduced a global lock)."""
        p1 = tmp_path / "a.json"
        p2 = tmp_path / "b.json"

        results = []

        def write_a():
            atomic_json_write(p1, {"a": 1})
            results.append("a")

        def write_b():
            atomic_json_write(p2, {"b": 2})
            results.append("b")

        t1 = threading.Thread(target=write_a)
        t2 = threading.Thread(target=write_b)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both files exist with their own content
        assert json.loads(p1.read_text()) == {"a": 1}
        assert json.loads(p2.read_text()) == {"b": 2}
        assert sorted(results) == ["a", "b"]


class TestEdgeCases:
    def test_rmw_modifier_returning_none_persists_null(self, tmp_path: Path):
        """The modifier contract: whatever it returns is persisted.
        Returning None → file contains 'null'. Caller's responsibility
        if that's not what they wanted."""
        p = tmp_path / "test.json"
        result = atomic_json_read_modify_write(p, lambda cur: None, default={})
        assert result is None
        assert json.loads(p.read_text()) is None

    def test_rmw_modifier_exception_propagates(self, tmp_path: Path):
        """If modifier raises, the file must NOT be touched (lock release
        without write). Otherwise we'd corrupt config on transient bugs."""
        p = tmp_path / "test.json"
        atomic_json_write(p, {"v": 1})

        def boom(cur):
            raise ValueError("modifier failed")

        with pytest.raises(ValueError, match="modifier failed"):
            atomic_json_read_modify_write(p, boom, default={})

        # Pre-existing content unchanged
        assert json.loads(p.read_text()) == {"v": 1}
        # No .tmp leftover
        assert not (tmp_path / "test.json.tmp").exists()
