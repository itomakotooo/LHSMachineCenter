"""L2 — Batch state SQLite persistence + restart recovery (2026-05-22).

When the console process dies mid-batch, the BatchRunManager._batches
dict goes with it. Pre-L2: the operator could not see the batch in
sampling_status anymore, and the A1 resume button was unusable because
its handler reads from _batches. Post-L2: a SQLite ``batches`` table
persists every batch lifecycle milestone, and ``_restore_persisted_batches``
in BatchRunManager.__init__ rehydrates non-terminal batches as
cancelled-by-restart so the A1 button can immediately re-queue the
incomplete items.

Tests here cover:

  1. StateStore.upsert_batch round-trip:
     - INSERT new row
     - UPDATE existing row (status + finished_at + json columns)
     - list_batches_by_status filtering

  2. BatchRunManager restart recovery:
     - Persisted 'running' batch -> on new manager construction,
       restored as 'cancelled', items 'running'/'pending' flipped
       to 'cancelled', warn event appended.
     - Already-terminal batches NOT restored (status='completed'
       stays completed and out of the in-memory dict).
     - Resume endpoint can find restored batches.

Inject-bug recipes inline.
"""
from __future__ import annotations

import json
from pathlib import Path


# ── 1. StateStore upsert_batch / get_batch_row round-trip ──


class TestUpsertBatchRoundTrip:
    def test_insert_and_read_back(self, tmp_path: Path):
        """Inject-bug: in upsert_batch, drop the items_json column from
        the INSERT VALUES clause -> SQLite raises NOT NULL violation
        -> round-trip test fails at the upsert call."""
        from src.web_console.backend.app import StateStore
        store = StateStore(tmp_path / "console.db")
        store.upsert_batch(
            "b001",
            status="running",
            created_at="2026-05-22T10:00:00Z",
            finished_at=None,
            concurrency=3,
            params={"chunk_spin_times": 10000, "server_id": "intranet"},
            items=[
                {"machine": "M14", "mode": 1, "status": "running",
                 "run_id": "r_live"},
                {"machine": "M120", "mode": 1, "status": "pending"},
            ],
            events=[{"ts": "2026-05-22T10:00:01Z", "level": "info",
                     "text": "batch started"}],
            reports_root="/reports",
        )
        row = store.get_batch_row("b001")
        assert row is not None
        assert row["batch_id"] == "b001"
        assert row["status"] == "running"
        assert row["concurrency"] == 3
        assert row["params"]["chunk_spin_times"] == 10000
        assert row["params"]["server_id"] == "intranet"
        assert len(row["items"]) == 2
        assert row["items"][0]["machine"] == "M14"
        assert row["events"][0]["text"] == "batch started"

    def test_update_existing_batch(self, tmp_path: Path):
        """Inject-bug: in the ON CONFLICT clause, replace
        ``status=:status`` with ``status='running'`` (literal) ->
        every UPDATE overwrites status to 'running' regardless of
        the new value -> test fails because final read returns
        'running' instead of 'completed'."""
        from src.web_console.backend.app import StateStore
        store = StateStore(tmp_path / "console.db")
        # Initial insert.
        store.upsert_batch(
            "b002",
            status="running",
            created_at="2026-05-22T10:00:00Z",
            finished_at=None,
            concurrency=3,
            params={"timeout": 60.0},
            items=[{"machine": "M14", "mode": 1, "status": "running"}],
            events=[],
            reports_root=None,
        )
        # Same batch_id, status flipped to completed + finished_at set.
        store.upsert_batch(
            "b002",
            status="completed",
            created_at="2026-05-22T10:00:00Z",
            finished_at="2026-05-22T10:05:00Z",
            concurrency=3,
            params={"timeout": 60.0},
            items=[{"machine": "M14", "mode": 1, "status": "completed",
                    "run_id": "r_done"}],
            events=[{"ts": "2026-05-22T10:05:00Z", "level": "ok",
                     "text": "batch done"}],
            reports_root=None,
        )
        row = store.get_batch_row("b002")
        assert row["status"] == "completed"
        assert row["finished_at"] == "2026-05-22T10:05:00Z"
        assert row["items"][0]["status"] == "completed"
        assert row["items"][0]["run_id"] == "r_done"
        assert row["events"][0]["text"] == "batch done"

    def test_list_batches_by_status_filters(self, tmp_path: Path):
        """list_batches_by_status returns ONLY rows matching the
        provided statuses tuple. Used by _restore_persisted_batches
        with ('pending', 'running') to find non-terminal batches.

        Inject-bug: drop the WHERE filter from the SQL -> all batches
        returned regardless of status -> test fails because completed
        batch leaks into the result."""
        from src.web_console.backend.app import StateStore
        store = StateStore(tmp_path / "console.db")
        for bid, status in [
            ("b_run", "running"),
            ("b_pend", "pending"),
            ("b_done", "completed"),
            ("b_cancel", "cancelled"),
        ]:
            store.upsert_batch(
                bid,
                status=status,
                created_at="2026-05-22T10:00:00Z",
                finished_at=None,
                concurrency=3,
                params={},
                items=[],
                events=[],
                reports_root=None,
            )
        non_terminal = store.list_batches_by_status(("pending", "running"))
        ids = {r["batch_id"] for r in non_terminal}
        assert ids == {"b_run", "b_pend"}, (
            f"expected only running+pending, got {ids}"
        )


# ── 2. BatchRunManager restart recovery ────────────────────────


class TestRestartRecovery:
    def _make_manager(self, tmp_path: Path):
        """Build a BatchRunManager pointed at a fresh tmp DB without
        spawning anything. Used as a fixture for the recovery tests
        below."""
        from src.web_console.backend.app import (
            BatchRunManager, RunManager, StateStore,
        )
        db_path = tmp_path / "console.db"
        store = StateStore(db_path)
        # Stub RunManager — BatchRunManager only touches it for cancel,
        # which the recovery tests don't exercise.
        class _StubRM:
            _lock = __import__("threading").Lock()
            _running: dict = {}
        return BatchRunManager(
            store,
            _StubRM(),
            tmp_path / "cache",
            state_dir=tmp_path,
            rawdata_root=tmp_path / "rawdata",
        ), store

    def test_running_batch_restored_as_cancelled(self, tmp_path: Path):
        """Pre-seed a 'running' batch in the DB BEFORE constructing
        BatchRunManager; verify it restores as 'cancelled' with items
        flipped to cancelled.

        Inject-bug: in _restore_persisted_batches, remove the
        ``self._batches[batch_id] = {...}`` assignment -> batch
        not restored to in-memory dict -> get_batch returns None ->
        test fails at the items check."""
        from src.web_console.backend.app import StateStore
        # Pre-seed BEFORE constructing the manager.
        db_path = tmp_path / "console.db"
        prep_store = StateStore(db_path)
        prep_store.upsert_batch(
            "b_interrupted",
            status="running",
            created_at="2026-05-22T10:00:00Z",
            finished_at=None,
            concurrency=2,
            params={"chunk_spin_times": 10000, "server_id": "intranet",
                    "timeout": 60.0, "chunk_robot_count": 2,
                    "batch_concurrency": 16, "max_chunks": 30,
                    "target_halfwidth_pp": 0.5,
                    "auto_cleanup_cache": True},
            items=[
                {"machine": "M14", "mode": 1, "status": "completed",
                 "chunk_spin_times": 10000, "run_id": "r_done"},
                {"machine": "M120", "mode": 1, "status": "running",
                 "chunk_spin_times": 10000, "run_id": "r_live"},
                {"machine": "M99", "mode": 2, "status": "pending",
                 "chunk_spin_times": 10000},
            ],
            events=[],
            reports_root=None,
        )

        mgr, store = self._make_manager(tmp_path)
        # 1. Restored into in-memory dict.
        restored = mgr.get_batch("b_interrupted")
        assert restored is not None, "batch not restored from DB"
        # 2. status = cancelled, finished_at set.
        # Note: get_batch projects items_out / etc.; for status we
        # read directly from _batches.
        with mgr._lock:
            raw = mgr._batches["b_interrupted"]
            assert raw["status"] == "cancelled"
            assert raw["finished_at"] is not None
            # 3. completed item stays completed; running + pending
            #    flipped to cancelled.
            items_by_machine = {it["machine"]: it for it in raw["items"]}
            assert items_by_machine["M14"]["status"] == "completed"
            assert items_by_machine["M120"]["status"] == "cancelled"
            assert items_by_machine["M99"]["status"] == "cancelled"
            # 4. Restart marker event appended to events.
            assert any(
                "console 重启" in (e.get("text") or "")
                for e in raw["events"]
            )
        # 5. DB row also flipped to cancelled (persist back on restore).
        db_row = store.get_batch_row("b_interrupted")
        assert db_row["status"] == "cancelled"

    def test_completed_batch_not_restored(self, tmp_path: Path):
        """Already-terminal batches stay in the DB but should not
        appear in the in-memory dict (otherwise they'd clutter
        sampling_status as if they were active).

        Inject-bug: in list_batches_by_status caller, change the
        statuses tuple to include 'completed' -> completed batch
        gets restored -> test fails because get_batch returns
        the row instead of None.
        """
        from src.web_console.backend.app import StateStore
        db_path = tmp_path / "console.db"
        prep_store = StateStore(db_path)
        prep_store.upsert_batch(
            "b_old_done",
            status="completed",
            created_at="2026-05-22T09:00:00Z",
            finished_at="2026-05-22T09:10:00Z",
            concurrency=3,
            params={},
            items=[{"machine": "M14", "mode": 1, "status": "completed"}],
            events=[],
            reports_root=None,
        )
        mgr, _ = self._make_manager(tmp_path)
        assert mgr.get_batch("b_old_done") is None, (
            "completed batches should not be loaded back into the in-memory dict"
        )

    def test_resume_endpoint_works_after_restart(self, client, app_factory):
        """End-to-end: seed an interrupted batch row, construct the
        FastAPI app (which restores it), call POST resume — the new
        batch should pick up the previously-running and previously-
        pending items.

        Inject-bug: drop _restore_persisted_batches call from
        __init__ -> restored batch absent from _batches -> POST resume
        returns 404 instead of 200 -> test fails.
        """
        # The client fixture already constructed the app; we need a
        # fresh app where the seed happened BEFORE construction. Use
        # app_factory directly.
        from fastapi.testclient import TestClient
        from src.web_console.backend.app import StateStore

        db_path = app_factory.db_path
        # Build the store + seed the DB BEFORE app construction.
        store = StateStore(db_path)
        store.upsert_batch(
            "b_persisted",
            status="running",
            created_at="2026-05-22T10:00:00Z",
            finished_at=None,
            concurrency=2,
            params={"chunk_spin_times": 10000, "server_id": "intranet",
                    "timeout": 60.0, "chunk_robot_count": 2,
                    "batch_concurrency": 16, "max_chunks": 30,
                    "target_halfwidth_pp": 0.5,
                    "auto_cleanup_cache": True},
            items=[
                {"machine": "M14", "mode": 1, "status": "completed",
                 "chunk_spin_times": 10000, "run_id": "r_done"},
                {"machine": "M120", "mode": 1, "status": "running",
                 "chunk_spin_times": 10000, "run_id": "r_live"},
            ],
            events=[],
            reports_root=None,
        )
        # Now build the app — restore should pick up b_persisted.
        app = app_factory()
        with TestClient(app) as c:
            resp = c.post("/api/batch-run/b_persisted/resume")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["resumed_from_batch_id"] == "b_persisted"
            # 1 incomplete item (M120 running -> cancelled at restore).
            # M14 completed is skipped.
            assert body["resumed_items"] == 1
            assert body["skipped_completed_items"] == 1
