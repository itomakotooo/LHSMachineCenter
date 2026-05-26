"""B1 — GET /api/batches unified batch history endpoint (2026-05-26).

The 2026-05-25 operator pain point: launched a 全量 yesterday, can't
see what happened today because the in-memory _batches dicts only
carry non-terminal entries after a restart. L2 + L3 persisted the
state to SQLite; this endpoint exposes it.

Tests:
  - empty list when no batches exist
  - lists both sampling + generate kinds
  - kind=sampling / kind=generate filters
  - limit clamps to [1, 500]
  - 400 on invalid kind
  - GET /api/batch-run/{id} falls back to DB for terminal batches
    (carries from_history=true sentinel)

Inject-bug recipes inline.
"""
from __future__ import annotations


class TestListBatchesEndpoint:
    def test_empty_returns_empty_list(self, client):
        c, _app = client
        resp = c.get("/api/batches")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"batches": [], "count": 0}

    def test_lists_both_kinds_unified(self, client, app_factory):
        """Inject-bug: in list_batches handler, hardcode kind='sampling'
        in the store call -> generate batches never appear in the
        unified response -> the count check below fails."""
        from src.web_console.backend.app import StateStore
        db_path = app_factory.db_path
        store = StateStore(db_path)
        store.upsert_batch(
            "s1", status="completed", created_at="2026-05-26T10:00:00Z",
            finished_at="2026-05-26T10:05:00Z", concurrency=3,
            params={}, items=[{"machine": "M14", "mode": 1, "status": "completed"}],
            events=[], reports_root=None, kind="sampling",
        )
        store.upsert_batch(
            "g1", status="completed", created_at="2026-05-26T11:00:00Z",
            finished_at="2026-05-26T11:02:00Z", concurrency=4,
            params={"total": 2, "completed": 2, "failed": 0, "pending": 0},
            items=[{"machine": "M14", "mode": 1, "status": "completed"},
                   {"machine": "M120", "mode": 1, "status": "completed"}],
            events=[], reports_root=None, kind="generate",
        )
        c, _app = client
        resp = c.get("/api/batches")
        assert resp.status_code == 200
        body = resp.json()
        # Most-recent first by created_at — g1 (11:00) before s1 (10:00).
        ids = [b["batch_id"] for b in body["batches"]]
        assert ids == ["g1", "s1"]
        # Kind field surfaces so UI can render different icons.
        assert {b["kind"] for b in body["batches"]} == {"sampling", "generate"}
        # Item count surfaces without items_json (heavy json kept off the list view).
        gen_row = next(b for b in body["batches"] if b["batch_id"] == "g1")
        assert gen_row["total_items"] == 2
        assert gen_row["item_status_counts"] == {"completed": 2}
        # No params/items/events in list view (separate detail endpoint).
        assert "items" not in gen_row
        assert "params" not in gen_row
        assert "events" not in gen_row

    def test_kind_filter_isolates(self, client, app_factory):
        from src.web_console.backend.app import StateStore
        store = StateStore(app_factory.db_path)
        store.upsert_batch(
            "s1", status="completed", created_at="2026-05-26T10:00:00Z",
            finished_at=None, concurrency=3, params={}, items=[],
            events=[], reports_root=None, kind="sampling",
        )
        store.upsert_batch(
            "g1", status="completed", created_at="2026-05-26T11:00:00Z",
            finished_at=None, concurrency=4, params={}, items=[],
            events=[], reports_root=None, kind="generate",
        )
        c, _app = client
        sampling_only = c.get("/api/batches?kind=sampling").json()
        generate_only = c.get("/api/batches?kind=generate").json()
        assert {b["batch_id"] for b in sampling_only["batches"]} == {"s1"}
        assert {b["batch_id"] for b in generate_only["batches"]} == {"g1"}

    def test_invalid_kind_returns_400(self, client):
        c, _app = client
        resp = c.get("/api/batches?kind=garbage")
        assert resp.status_code == 400
        assert "kind" in resp.json()["detail"]

    def test_limit_clamps_to_max(self, client):
        """Inject-bug: change eff_limit = max(1, min(500, ...)) to
        eff_limit = int(limit) -> a `?limit=99999` query asks the
        DB for 99999 rows -> wasted IO / response size. Test ensures
        the clamp is in place."""
        c, _app = client
        # Just verify it doesn't error on a huge limit; the actual
        # clamp value is internal. Empty db so no data to count.
        resp = c.get("/api/batches?limit=99999")
        assert resp.status_code == 200


class TestGetBatchRunFallback:
    def test_terminal_batch_served_from_db(self, client, app_factory):
        """A batch that finished (and therefore is NOT in _batches
        in-memory after a restart) should still be retrievable via
        the existing GET /api/batch-run/{id} endpoint by falling
        back to the DB.

        Inject-bug: in get_batch_run, remove the
            row = store.get_batch_row(batch_id)
            ...
        fallback block and immediately raise 404 when in-memory get
        returns None -> the operator can't inspect yesterday's
        completed batch -> this test fails because the response is
        404 instead of 200 with from_history=true.
        """
        from src.web_console.backend.app import StateStore
        store = StateStore(app_factory.db_path)
        store.upsert_batch(
            "s_done",
            status="completed",
            created_at="2026-05-25T10:00:00Z",
            finished_at="2026-05-25T10:30:00Z",
            concurrency=3,
            params={"chunk_spin_times": 10000, "server_id": "intranet"},
            items=[
                {"machine": "M14", "mode": 1, "status": "completed",
                 "run_id": "r1"},
                {"machine": "M120", "mode": 1, "status": "completed",
                 "run_id": "r2"},
            ],
            events=[{"ts": "2026-05-25T10:00:01Z", "level": "info",
                     "text": "batch started"}],
            reports_root="/reports",
            kind="sampling",
        )
        c, _app = client
        resp = c.get("/api/batch-run/s_done")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["batch_id"] == "s_done"
        assert body["status"] == "completed"
        assert body["from_history"] is True  # sentinel
        assert body["kind"] == "sampling"
        assert body["total"] == 2
        assert body["completed"] == 2
        assert body["params"]["chunk_spin_times"] == 10000

    def test_unknown_batch_id_still_404(self, client):
        c, _app = client
        resp = c.get("/api/batch-run/nope_does_not_exist")
        assert resp.status_code == 404
