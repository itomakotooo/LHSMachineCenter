"""POST /api/batch-run/{id}/resume — 2026-05-22 task A1.

Re-submit a finished-but-incomplete batch (status in
{cancelled, failed, partial}) with the original batch's params, but
only the items that did NOT reach `completed` / `attached`. The
backend's per-item resume_from_cache picks up existing rawdata
chunks for each cell, so already-partial cells continue from their
last chunk index.

Tests here cover:
  - happy path: cancelled batch with mixed completed / cancelled items
    -> new batch_id, only incomplete items, params copied verbatim
  - 404 when batch_id is unknown
  - 409 when batch is still running (resume of an in-flight batch
    would create a phantom second batch hitting the same cells)
  - 409 when all items already completed (nothing to resume)
  - completed items + attached items both skipped on resume

Inject-bug recipes inline. Endpoint code lives in app.py around
`@app.post("/api/batch-run/{batch_id}/resume")`.
"""
from __future__ import annotations

from typing import Any


def _seed_finished_batch(
    app,
    *,
    status: str,
    items: list[dict[str, Any]],
    params_override: dict[str, Any] | None = None,
) -> str:
    """Stuff a synthetic finished batch into the in-memory
    BatchRunManager so we don't have to actually run samples.

    The resume endpoint reads from get_batch which surfaces the
    in-memory _batches dict; that's enough to test the request
    construction without spawning analyzer subprocesses.
    """
    from src.web_console.backend.app import BatchRunManager

    # Reach into the app's BatchRunManager via the closure-captured
    # variable used by the FastAPI handlers.
    batch_mgr = None
    for r in app.routes:
        ep = getattr(r, "endpoint", None)
        if ep is None:
            continue
        closure = getattr(ep, "__closure__", None) or ()
        for cell in closure:
            try:
                v = cell.cell_contents
            except ValueError:
                continue
            if isinstance(v, BatchRunManager):
                batch_mgr = v
                break
        if batch_mgr is not None:
            break
    assert batch_mgr is not None, (
        "could not locate BatchRunManager closure on app routes"
    )

    import uuid
    batch_id = uuid.uuid4().hex[:12]
    params = {
        "chunk_spin_times": 10000,
        "chunk_robot_count": 8,
        "batch_concurrency": 8,
        "max_chunks": 60,
        "timeout": 60.0,
        "target_halfwidth_pp": 0.5,
        "auto_cleanup_cache": True,
        "server_id": "intranet",
    }
    if params_override:
        params.update(params_override)
    state = {
        "batch_id": batch_id,
        "status": status,
        "items": items,
        "events": [],
        "concurrency": 3,
        "params": params,
        "reports_root": None,
        "created_at": "2026-05-22T00:00:00Z",
        "cancel_requested": True,
    }
    with batch_mgr._lock:
        batch_mgr._batches[batch_id] = state
    return batch_id


# ── happy paths ──────────────────────────────────────────────────


class TestResumeHappyPath:
    def test_cancelled_batch_resumes_only_incomplete_items(self, client):
        """Cancelled batch with 4 items (1 completed, 1 attached, 2
        cancelled) → new batch has only the 2 cancelled items.

        Inject-bug recipe: in the resume endpoint replace
        ``incomplete_statuses = {"failed", "cancelled", "pending",
        "running"}`` with ``{"failed", "cancelled", "pending",
        "running", "completed"}`` → completed item gets re-submitted →
        assertion fails (`resumed_items != 2`).
        """
        c, app = client
        bid = _seed_finished_batch(
            app,
            status="cancelled",
            items=[
                {"machine": "M14", "mode": 1, "status": "completed",
                 "chunk_spin_times": 10000, "run_id": "r_done"},
                {"machine": "M272", "mode": 1, "status": "attached",
                 "chunk_spin_times": 10000, "run_id": "r_att"},
                {"machine": "M120", "mode": 1, "status": "cancelled",
                 "chunk_spin_times": 10000, "run_id": None,
                 "error": "cancelled by user"},
                {"machine": "M99", "mode": 2, "status": "cancelled",
                 "chunk_spin_times": 10000, "run_id": None,
                 "error": "cancelled by user"},
            ],
        )
        resp = c.post(f"/api/batch-run/{bid}/resume")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["batch_id"] != bid
        assert body["resumed_from_batch_id"] == bid
        assert body["resumed_items"] == 2
        assert body["skipped_completed_items"] == 2
        assert body["status"] == "running"
        assert body["total"] == 2

    def test_failed_batch_re_runs_failed_items(self, client):
        """Failed batch (status=failed) with 1 completed + 1 failed item
        → resume includes the failed one only.

        Inject-bug: change endpoint guard from
        ``status not in ("cancelled", "failed", "partial")`` to
        ``status != "cancelled"`` → failed batches get rejected with
        409 → this test fails with assertion `200 == 409`.
        """
        c, app = client
        bid = _seed_finished_batch(
            app,
            status="failed",
            items=[
                {"machine": "M14", "mode": 1, "status": "completed",
                 "chunk_spin_times": 10000, "run_id": "r_done"},
                {"machine": "M120", "mode": 1, "status": "failed",
                 "chunk_spin_times": 10000, "run_id": "r_failed",
                 "error": "upstream_unstable"},
            ],
        )
        resp = c.post(f"/api/batch-run/{bid}/resume")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["resumed_items"] == 1
        assert body["skipped_completed_items"] == 1

    def test_partial_batch_resumes(self, client):
        """Partial = some items completed but didn't hit CI target.
        Partial is a terminal state on the batch level but the items
        themselves are 'completed' with ci_target_met=False; they should
        NOT be resumed (the run already succeeded, just didn't tighten
        the CI). Only pending / cancelled / failed siblings get re-queued.
        """
        c, app = client
        bid = _seed_finished_batch(
            app,
            status="partial",
            items=[
                {"machine": "M14", "mode": 1, "status": "completed",
                 "chunk_spin_times": 10000, "run_id": "r_done",
                 "ci_target_met": False},
                {"machine": "M120", "mode": 1, "status": "pending",
                 "chunk_spin_times": 10000, "run_id": None},
            ],
        )
        resp = c.post(f"/api/batch-run/{bid}/resume")
        assert resp.status_code == 200
        assert resp.json()["resumed_items"] == 1

    def test_params_preserved_from_original_batch(self, client):
        """The new batch must inherit the original's params (server_id,
        chunk_robot_count, batch_concurrency, max_chunks, timeout,
        target_halfwidth_pp, chunk_spin_times) so the resume is a true
        continuation and not a fresh sweep with defaults.

        Inject-bug: in the endpoint, change
        ``timeout=float(params.get("timeout") or 60.0)`` to
        ``timeout=60.0`` (hardcoded) → custom timeouts dropped on
        resume → this test's check on the new batch's params fails
        because timeout=120.0 from the original gets clobbered to 60.0.
        """
        c, app = client
        bid = _seed_finished_batch(
            app,
            status="cancelled",
            items=[
                {"machine": "M14", "mode": 1, "status": "cancelled",
                 "chunk_spin_times": 8000, "run_id": None},
            ],
            params_override={
                "chunk_spin_times": 12000,
                "chunk_robot_count": 4,
                "batch_concurrency": 12,
                "max_chunks": 50,
                "timeout": 120.0,
                "target_halfwidth_pp": 0.25,
                "auto_cleanup_cache": False,
                "server_id": "prod",
            },
        )
        resp = c.post(f"/api/batch-run/{bid}/resume")
        assert resp.status_code == 200
        new_bid = resp.json()["batch_id"]

        # GET /api/batch-run/{id} doesn't surface internal params to
        # the UI (only item-level state); reach into the manager's
        # in-memory _batches dict to verify the params copy is intact.
        from src.web_console.backend.app import BatchRunManager
        batch_mgr = None
        for r in app.routes:
            ep = getattr(r, "endpoint", None)
            if ep is None:
                continue
            for cell in getattr(ep, "__closure__", None) or ():
                try:
                    v = cell.cell_contents
                except ValueError:
                    continue
                if isinstance(v, BatchRunManager):
                    batch_mgr = v
                    break
            if batch_mgr is not None:
                break
        assert batch_mgr is not None
        with batch_mgr._lock:
            new_state = dict(batch_mgr._batches[new_bid])
            new_params = dict(new_state.get("params") or {})
            new_items = [dict(it) for it in new_state.get("items") or []]

        assert new_params.get("chunk_robot_count") == 4
        assert new_params.get("batch_concurrency") == 12
        assert new_params.get("max_chunks") == 50
        assert new_params.get("timeout") == 120.0
        assert new_params.get("target_halfwidth_pp") == 0.25
        assert new_params.get("auto_cleanup_cache") is False
        assert new_params.get("server_id") == "prod"
        # Per-item chunk_spin_times preserved (this drives analyzer's
        # per-chunk request size; mixing values per-item is supported).
        assert new_items[0]["chunk_spin_times"] == 8000


# ── rejection paths ──────────────────────────────────────────────


class TestResumeRejections:
    def test_404_when_batch_id_unknown(self, client):
        c, _app = client
        resp = c.post("/api/batch-run/does_not_exist/resume")
        assert resp.status_code == 404

    def test_409_when_batch_still_running(self, client):
        """Resuming a running batch would create a parallel batch that
        races the original on the same cells. CellLockRegistry would
        catch the SAMPLING attempt (and return 'attached'), but the
        cleaner contract is to reject at submit time.

        Inject-bug: remove the
        ``if state["status"] not in ("cancelled", "failed", "partial"):``
        guard → running batches accept resume → this test sees 200
        instead of 409.
        """
        c, app = client
        bid = _seed_finished_batch(
            app,
            status="running",
            items=[
                {"machine": "M14", "mode": 1, "status": "running",
                 "chunk_spin_times": 10000, "run_id": "r_live"},
            ],
        )
        resp = c.post(f"/api/batch-run/{bid}/resume")
        assert resp.status_code == 409
        assert "running" in resp.json()["detail"]

    def test_409_when_already_completed(self, client):
        """A fully-completed batch has nothing left to resume; the
        operator clicking the button would just re-submit completed
        items as no-ops (since resume_from_cache sees the work done).
        Reject explicitly to make it clear there's nothing to do."""
        c, app = client
        bid = _seed_finished_batch(
            app,
            status="completed",
            items=[
                {"machine": "M14", "mode": 1, "status": "completed",
                 "chunk_spin_times": 10000, "run_id": "r_done"},
            ],
        )
        resp = c.post(f"/api/batch-run/{bid}/resume")
        assert resp.status_code == 409

    def test_409_when_cancelled_but_all_items_completed(self, client):
        """Edge case: batch was cancelled but every item happened to
        finish before the cancellation hit. Body says nothing-to-resume."""
        c, app = client
        bid = _seed_finished_batch(
            app,
            status="cancelled",
            items=[
                {"machine": "M14", "mode": 1, "status": "completed",
                 "chunk_spin_times": 10000, "run_id": "r_done"},
                {"machine": "M272", "mode": 1, "status": "attached",
                 "chunk_spin_times": 10000, "run_id": "r_att"},
            ],
        )
        resp = c.post(f"/api/batch-run/{bid}/resume")
        assert resp.status_code == 409
        assert "nothing" in resp.json()["detail"].lower()
