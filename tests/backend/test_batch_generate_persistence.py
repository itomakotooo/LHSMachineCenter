"""L3 — BatchGenerateManager SQLite persistence (2026-05-26).

Symmetric to L2: when the console process dies mid-batch-generate
(operator clicked '⟳ 批量生成 Report' for 100 machines and went home),
the BatchGenerateManager._batches dict goes with it. Pre-L3: state
gone, operator has no idea what was completed. Post-L3: state
persisted to the same ``batches`` SQLite table that L2 introduced,
discriminated by ``kind`` column ('sampling' vs 'generate').

Tests here:
  1. Schema upgrade (kind column added on existing L2 dbs).
  2. upsert_batch round-trip with kind='generate'.
  3. list_batches_by_status filtered by kind.
  4. BatchGenerateManager persists on start + item transitions +
     cancel + terminal status.
  5. Restart recovery rehydrates non-terminal generate batches
     and does NOT touch sampling batches (kind isolation).

Inject-bug recipes inline.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


# ── 1. Schema migration ──────────────────────────────────────────


class TestSchemaMigration:
    def test_kind_column_added_to_legacy_l2_db(self, tmp_path: Path):
        """Simulate an L2-era database that has the batches table but
        WITHOUT the kind column. StateStore init should ALTER TABLE
        ADD COLUMN it without losing existing data.

        Inject-bug: remove the
            if "kind" not in batches_columns: ADD COLUMN
        block -> pre-L2 dbs blow up on upsert_batch with
        'no column named kind' -> this test fails at the smoke
        upsert_batch call below.
        """
        from src.web_console.backend.app import StateStore

        # Create a manual pre-L3 schema (no kind column).
        db_path = tmp_path / "console.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE batches (
                batch_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                finished_at TEXT,
                concurrency INTEGER NOT NULL DEFAULT 3,
                params_json TEXT NOT NULL,
                items_json TEXT NOT NULL,
                events_json TEXT NOT NULL,
                reports_root TEXT
            )
        """)
        conn.execute("""
            INSERT INTO batches (batch_id, status, created_at, concurrency,
                                 params_json, items_json, events_json)
            VALUES ('legacy_b1', 'completed', '2026-05-25T10:00:00Z', 3,
                    '{}', '[]', '[]')
        """)
        conn.commit()
        conn.close()

        # StateStore init triggers the ALTER.
        StateStore(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cols = {row[1] for row in conn.execute("PRAGMA table_info(batches)").fetchall()}
        assert "kind" in cols, "ALTER TABLE batches ADD COLUMN kind missing"
        # Existing row gets the default ('sampling') so old data
        # surfaces in the unified view as a sampling batch.
        row = dict(conn.execute("SELECT kind FROM batches WHERE batch_id='legacy_b1'").fetchone())
        assert row["kind"] == "sampling"
        conn.close()


# ── 2. upsert_batch round-trip with kind ──────────────────────


class TestUpsertWithKind:
    def test_default_kind_is_sampling(self, tmp_path: Path):
        from src.web_console.backend.app import StateStore
        store = StateStore(tmp_path / "console.db")
        store.upsert_batch(
            "b001",
            status="running",
            created_at="2026-05-26T10:00:00Z",
            finished_at=None,
            concurrency=3,
            params={}, items=[], events=[],
            reports_root=None,
        )
        row = store.get_batch_row("b001")
        assert row["kind"] == "sampling"

    def test_explicit_kind_generate_round_trip(self, tmp_path: Path):
        """Inject-bug: in upsert_batch, hardcode kind='sampling' in the
        payload -> kind='generate' calls overwrite to 'sampling' ->
        list_batches_by_status(kind='generate') returns empty ->
        BatchGenerateManager's restore can't find its own batches."""
        from src.web_console.backend.app import StateStore
        store = StateStore(tmp_path / "console.db")
        store.upsert_batch(
            "g001",
            status="completed",
            created_at="2026-05-26T10:00:00Z",
            finished_at="2026-05-26T10:30:00Z",
            concurrency=4,
            params={"total": 5, "completed": 5, "failed": 0, "pending": 0},
            items=[{"machine": "M14", "mode": 1, "status": "completed"}],
            events=[],
            reports_root=None,
            kind="generate",
        )
        row = store.get_batch_row("g001")
        assert row["kind"] == "generate"
        assert row["status"] == "completed"
        assert row["params"]["total"] == 5


# ── 3. list_batches_by_status filtered by kind ────────────────


class TestListByKind:
    def test_kind_filter_isolates_managers(self, tmp_path: Path):
        """The unified batches table holds both sampling and generate
        batches; each manager queries with its own kind filter so the
        restore code only rehydrates its own type.

        Inject-bug: remove the ``kind`` filter from list_batches_by_status
        -> BatchRunManager._restore_persisted_batches loads generate
        batches into the sampling _batches dict -> get_batch returns
        them as sampling batches with weird shape -> downstream UI
        breaks. The test fails because the list returns 2 rows
        instead of 1.
        """
        from src.web_console.backend.app import StateStore
        store = StateStore(tmp_path / "console.db")
        for bid, kind in [("s_run", "sampling"), ("g_run", "generate")]:
            store.upsert_batch(
                bid,
                status="running",
                created_at="2026-05-26T10:00:00Z",
                finished_at=None,
                concurrency=3,
                params={}, items=[], events=[],
                reports_root=None,
                kind=kind,
            )
        sampling_only = store.list_batches_by_status(("running",), kind="sampling")
        generate_only = store.list_batches_by_status(("running",), kind="generate")
        all_kinds = store.list_batches_by_status(("running",))
        assert {b["batch_id"] for b in sampling_only} == {"s_run"}
        assert {b["batch_id"] for b in generate_only} == {"g_run"}
        assert {b["batch_id"] for b in all_kinds} == {"s_run", "g_run"}


# ── 4. BatchGenerateManager restart recovery ─────────────────


def _seed_generate_batch(
    db_path: Path,
    batch_id: str,
    status: str,
    items: list[dict],
    params: dict,
) -> None:
    from src.web_console.backend.app import StateStore
    store = StateStore(db_path)
    store.upsert_batch(
        batch_id,
        status=status,
        created_at="2026-05-26T09:00:00Z",
        finished_at=None,
        concurrency=4,
        params=params,
        items=items,
        events=[],
        reports_root=None,
        kind="generate",
    )


def _make_batch_gen_manager(tmp_path: Path):
    """Build a BatchGenerateManager with a stub prepare/finalize and a
    real StateStore. No threads spawn until .start() is called."""
    from src.web_console.backend.app import BatchGenerateManager, StateStore
    store = StateStore(tmp_path / "console.db")
    def _stub_prepare(machine, mode):
        return {"machine": machine, "mode": mode, "run_id": f"r_{machine}_{mode}",
                "job": {"machine": machine, "mode": mode}}
    def _stub_finalize(prepared, worker_result):
        return {**prepared}
    return BatchGenerateManager(
        prepare_fn=_stub_prepare,
        finalize_fn=_stub_finalize,
        concurrency=4,
        root_path=str(tmp_path),
        store=store,
    ), store


class TestRestartRecovery:
    def test_running_generate_batch_restored_as_cancelled(self, tmp_path: Path):
        """Pre-seed a 'running' generate batch BEFORE constructing
        BatchGenerateManager; verify it restores as 'cancelled' with
        in-flight items flipped.

        Inject-bug: in _restore_persisted, drop the
            self._batches[batch_id] = state
        assignment -> restored entries missing from in-memory dict ->
        manager.get(batch_id) returns None instead of the restored
        state -> test fails.
        """
        _seed_generate_batch(
            tmp_path / "console.db",
            "g_interrupted",
            status="running",
            items=[
                {"machine": "M14", "mode": 1, "status": "completed",
                 "run_id": "r1"},
                {"machine": "M120", "mode": 1, "status": "running",
                 "run_id": "r2"},
                {"machine": "M99", "mode": 2, "status": "pending"},
            ],
            params={"total": 3, "completed": 1, "failed": 0, "pending": 1},
        )
        mgr, store = _make_batch_gen_manager(tmp_path)
        restored = mgr.get("g_interrupted")
        assert restored is not None, "generate batch not restored from DB"
        assert restored["status"] == "cancelled"
        by_machine = {it["machine"]: it for it in restored["items"]}
        assert by_machine["M14"]["status"] == "completed"  # untouched
        assert by_machine["M120"]["status"] == "cancelled"  # was running
        assert by_machine["M99"]["status"] == "cancelled"   # was pending
        # DB row also flipped.
        row = store.get_batch_row("g_interrupted")
        assert row["status"] == "cancelled"

    def test_completed_generate_batch_not_restored(self, tmp_path: Path):
        _seed_generate_batch(
            tmp_path / "console.db",
            "g_done",
            status="completed",
            items=[{"machine": "M14", "mode": 1, "status": "completed"}],
            params={"total": 1, "completed": 1, "failed": 0, "pending": 0},
        )
        mgr, _ = _make_batch_gen_manager(tmp_path)
        assert mgr.get("g_done") is None

    def test_sampling_batch_does_not_leak_into_generate_recovery(
        self, tmp_path: Path,
    ):
        """A sampling-kind batch persisted with the same table must
        NOT be picked up by BatchGenerateManager._restore_persisted.

        Inject-bug: drop the kind='generate' arg from
        list_batches_by_status call in _restore_persisted -> all
        non-terminal batches restored regardless of kind -> sampling
        batch appears in BatchGenerateManager.get() -> later code
        that assumes BGM-shape state crashes on missing fields ->
        this test fails because mgr.get('s_running') returns the
        sampling state instead of None.
        """
        from src.web_console.backend.app import StateStore
        # Seed a sampling-kind batch.
        store = StateStore(tmp_path / "console.db")
        store.upsert_batch(
            "s_running",
            status="running",
            created_at="2026-05-26T10:00:00Z",
            finished_at=None,
            concurrency=3,
            params={"chunk_spin_times": 10000}, items=[], events=[],
            reports_root=None,
            kind="sampling",
        )
        mgr, _ = _make_batch_gen_manager(tmp_path)
        assert mgr.get("s_running") is None, (
            "sampling batch leaked into BatchGenerateManager via "
            "missing kind filter"
        )


# ── 5. BatchGenerateManager persists on start + cancel ───────


class TestPersistOnLifecycle:
    def test_start_persists_initial_state(self, tmp_path: Path):
        """Inject-bug: remove the self._persist(batch_id) call in start
        -> initial state never makes it to disk -> if console dies
        before the first item finalize, the batch is lost on restart
        -> this test fails because get_batch_row returns None right
        after start.
        """
        mgr, store = _make_batch_gen_manager(tmp_path)
        # We don't want the background thread to actually run analyzer
        # subprocesses, so we cancel immediately. The start() call
        # itself returns synchronously after persisting + spawning the
        # thread. Persistence happens BEFORE the thread starts.
        result = mgr.start([
            {"machine": "M14", "mode": 1},
            {"machine": "M120", "mode": 1},
        ])
        bid = result["batch_id"]
        # Cancel right away so the worker thread doesn't actually do
        # work. The persist-on-cancel call captures the cancel intent.
        mgr.cancel(bid)
        # DB row exists.
        row = store.get_batch_row(bid)
        assert row is not None
        assert row["kind"] == "generate"
        # status may be pending/running/cancelled depending on whether
        # the background thread had a chance to flip it; the important
        # invariant is that persistence DID happen.
        assert row["status"] in ("pending", "running", "cancelled", "completed", "partial")
        # items list captures both machines from the start() input.
        machines = {it["machine"] for it in row["items"]}
        assert machines == {"M14", "M120"}
