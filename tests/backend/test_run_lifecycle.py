"""Backend run-lifecycle happy-path coverage.

Up until now the backend test suite covered failure paths (silent
crashes, structured error messages, mutex blocking) but never
exercised the happy path end-to-end: POST /api/runs creates a
managed run, the (stubbed) analyzer writes summary + report files,
_watch_run flips the row to 'completed', and the API serves the
report back. Plus the recent zero-spin guard (a 'completed' run with
total_spins=0 must be promoted to 'failed') needs its own contract
test so the next refactor can't accidentally regress it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _run_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "machine": "M14",
        "mode": 1,
        "target_halfwidth_pp": 0.5,
        "chunk_spin_times": 5000,
        "chunk_robot_count": 20,
        "batch_concurrency": 2,
        "max_chunks": 120,
        "timeout": 300.0,
        "bankruptcy_session_spins": 500,
        "bankruptcy_bankroll_multipliers": "100,200,500",
        "model_id": "gpt-5.4-mini",
    }
    base.update(overrides)
    return base


def _good_summary() -> dict[str, Any]:
    """Minimal but realistic summary shape so /api/runs/{id}/report and
    the report-index updater both succeed. Mirrors the player_impact
    JSON the analyzer would normally write."""
    return {
        "machine": "M14",
        "mode": 1,
        "sampling": {
            "target_halfwidth_pp": 0.5,
            "achieved_halfwidth_pp": 0.42,
            "chunk_spin_times": 5000,
            "chunk_robot_count": 20,
            "batch_concurrency": 2,
            "chunks": 12,
            "total_spins": 1_200_000,
            "stop_reason": "ci_target_reached",
            "duration_seconds": 87.5,
            "started_at": "2026-04-15T08:00:00Z",
            "finished_at": "2026-04-15T08:01:27Z",
        },
        "rtp": {"point_pct": 95.43, "ci95_interval_pct": [95.01, 95.85]},
        "player_impact": {
            "volatility": {"classification": "Medium"},
            "hit_and_payout": {
                "zero_win_rate": 0.71,
                "profit_spin_rate": 0.13,
            },
            "streaks": {"loss_streak_p95": 9},
            "multiplier_profile": {
                "tail_dependency": 0.31,
                "buckets": [
                    {"bucket": "gt0_lt1", "spin_count": 190000, "spin_rate": 0.158},
                    {"bucket": "ge1_lt5", "spin_count": 200000, "spin_rate": 0.166},
                ],
            },
            "paylines_top20": [
                {
                    "payline_id": "1",
                    "hit_count": 30000,
                    "hit_rate": 0.025,
                    "approx_rtp_contribution_pp": 9.5,
                    "top_symbols": [{"symbol": "cherry", "count": 18000}],
                }
            ],
            "payout_groups_top20": [
                {"group_id": 0, "hit_count": 850000, "rtp_contribution_pp": 0.0},
                {"group_id": 12, "hit_count": 350000, "rtp_contribution_pp": 80.5},
            ],
            "symbols_top20": [
                {"symbol": "blank", "count": 3500000, "rate": 0.50},
                {"symbol": "cherry", "count": 1100000, "rate": 0.157},
            ],
            "symbols_by_column_top10": {"0": [{"symbol": "blank", "count": 700000}]},
        },
        "guideline_assessment": {"data_quality": {"quality_label": "REPORT_GRADE"}},
        "guideline_comparison": {},
    }


def _zero_spin_summary(stop_reason: str = "request_failed_http_504") -> dict[str, Any]:
    """Realistic shape for the analyzer's 'main loop broke on first
    chunk failure' output: exit_code=0, both files written, but the
    sampling block records 0 spins. This is the case the user hit when
    the upstream test API returned 504s; the new zero-spin guard
    promotes it to 'failed'."""
    return {
        "machine": "M14",
        "mode": 1,
        "sampling": {
            "target_halfwidth_pp": 0.5,
            "achieved_halfwidth_pp": None,
            "chunk_spin_times": 5000,
            "chunk_robot_count": 20,
            "batch_concurrency": 4,
            "chunks": 0,
            "total_spins": 0,
            "stop_reason": stop_reason,
            "duration_seconds": 64.7,
            "started_at": "2026-04-15T07:45:00Z",
            "finished_at": "2026-04-15T07:46:05Z",
        },
        "rtp": {"point_pct": 0.0, "ci95_interval_pct": None},
        "player_impact": {
            "paylines_top20": [],
            "payout_groups_top20": [],
            "symbols_top20": [],
        },
    }


def _spawned_run_paths(app_factory, run_id: str) -> tuple[Path, Path]:
    """Resolve the summary + report paths the just-spawned run will
    look for. ManagedRun derives them from reports_root / machine /
    mode / versions / rv_<ts>_<run_id_prefix>; rather than racing on
    timestamps we read the row the API just inserted to find the
    canonical paths.
    """
    import sqlite3
    conn = sqlite3.connect(str(app_factory.db_path))
    try:
        row = conn.execute(
            "SELECT summary_file, report_file FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"row for run {run_id} not in DB"
    return Path(row[0]), Path(row[1])


# ---------- happy path ----------


def test_run_lifecycle_happy_path_completes_with_report(
    client, app_factory, wait_until_fixture
):
    """POST /api/runs -> mock analyzer writes summary+report -> watcher
    flips status to completed -> GET /api/runs/{id} reflects it ->
    GET /api/runs/{id}/report returns the summary."""
    c, _app = client
    resp = c.post("/api/runs", json=_run_payload())
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]
    assert resp.json()["status"] == "running"

    # Resolve where the analyzer is expected to write its outputs.
    summary_file, report_file = _spawned_run_paths(app_factory, run_id)

    # Stand in for the analyzer: write the two artefacts the watcher
    # checks for, then signal exit.
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(_good_summary()), encoding="utf-8")
    report_file.write_text("# Player Impact Report\n\nRTP: 95.43%\n", encoding="utf-8")

    stub = app_factory.stub_popen.processes[-1]
    stub.finish(code=0)

    wait_until_fixture(
        lambda: c.get(f"/api/runs/{run_id}").json().get("status") == "completed",
        timeout=5.0,
        msg="watcher never marked the happy-path run completed",
    )

    body = c.get(f"/api/runs/{run_id}").json()
    assert body["status"] == "completed"
    assert body["error_message"] in (None, "")

    # Report endpoint serves the freshly written summary back unchanged.
    rep = c.get(f"/api/runs/{run_id}/report")
    assert rep.status_code == 200
    rep_body = rep.json()
    assert rep_body["summary"]["rtp"]["point_pct"] == 95.43
    assert rep_body["summary"]["sampling"]["total_spins"] == 1_200_000
    # Drilldowns flow through.
    assert rep_body["summary"]["player_impact"]["paylines_top20"][0]["payline_id"] == "1"
    assert rep_body["summary"]["player_impact"]["payout_groups_top20"][1]["group_id"] == 12


def test_run_lifecycle_happy_path_updates_report_index(
    client, app_factory, wait_until_fixture
):
    """A successful run also appends an entry to reports/<machine>/
    mode_<mode>/index.json and updates latest.json. Operators rely on
    these to navigate prior reports from the manage tab."""
    c, _app = client
    resp = c.post("/api/runs", json=_run_payload())
    run_id = resp.json()["run_id"]
    summary_file, report_file = _spawned_run_paths(app_factory, run_id)
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(_good_summary()), encoding="utf-8")
    report_file.write_text("# r\n", encoding="utf-8")

    app_factory.stub_popen.processes[-1].finish(code=0)
    wait_until_fixture(
        lambda: c.get(f"/api/runs/{run_id}").json().get("status") == "completed",
        timeout=5.0,
    )

    index_path = app_factory.reports_dir / "M14" / "mode_1" / "index.json"
    latest_path = app_factory.reports_dir / "M14" / "mode_1" / "latest.json"
    assert index_path.exists(), "report index.json was not written"
    assert latest_path.exists(), "latest.json was not written"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert any(entry.get("run_id") == run_id for entry in index), (
        f"run_id {run_id} not found in index {index!r}"
    )
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest.get("run_id") == run_id

    # The run row also gets achieved_rtp_pct / achieved_halfwidth_pp
    # written so the manage-tab history table can show them without
    # re-reading every summary.json on list.
    row = c.get(f"/api/runs/{run_id}").json()
    assert row.get("achieved_rtp_pct") == 95.43, (
        f"RTP not persisted onto run row: {row.get('achieved_rtp_pct')!r}"
    )
    assert row.get("achieved_halfwidth_pp") == 0.42, (
        f"CI halfwidth not persisted onto run row: "
        f"{row.get('achieved_halfwidth_pp')!r}"
    )


# ---------- zero-spin guard ----------


def test_run_lifecycle_zero_spin_completed_promoted_to_failed(
    client, app_factory, wait_until_fixture
):
    """Regression for the user-reported bug: an analyzer that "succeeds"
    with exit_code=0 + summary+report files but reports total_spins=0
    (the upstream API returned 5xx for the very first chunk) must NOT
    be presented as a completed run. The watcher promotes it to failed
    with the analyzer-recorded stop_reason in error_message so the
    operator sees the actual cause.
    """
    c, _app = client
    resp = c.post("/api/runs", json=_run_payload())
    run_id = resp.json()["run_id"]
    summary_file, report_file = _spawned_run_paths(app_factory, run_id)
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    # Zero-spin summary mimicking the 504-timeout scenario.
    summary_file.write_text(
        json.dumps(_zero_spin_summary(stop_reason="request_failed_http_504")),
        encoding="utf-8",
    )
    report_file.write_text("# empty report\n", encoding="utf-8")

    app_factory.stub_popen.processes[-1].finish(code=0)
    wait_until_fixture(
        lambda: c.get(f"/api/runs/{run_id}").json().get("status") in ("failed", "completed"),
        timeout=5.0,
    )

    body = c.get(f"/api/runs/{run_id}").json()
    assert body["status"] == "failed", (
        f"zero-spin run should be failed, got {body!r}"
    )
    msg = body.get("error_message") or ""
    assert "0 spins" in msg, f"error_message must mention zero spins: {msg!r}"
    assert "request_failed_http_504" in msg, (
        f"error_message must include analyzer stop_reason: {msg!r}"
    )

    # Index / latest must NOT be polluted with the empty report.
    index_path = app_factory.reports_dir / "M14" / "mode_1" / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        assert not any(entry.get("run_id") == run_id for entry in index), (
            "zero-spin run leaked into report index"
        )


def test_run_lifecycle_zero_spin_with_unknown_stop_reason(
    client, app_factory, wait_until_fixture
):
    """If the analyzer didn't fill stop_reason (older versions, or an
    edge path), the guard still fires and labels the cause 'unknown'."""
    c, _app = client
    resp = c.post("/api/runs", json=_run_payload())
    run_id = resp.json()["run_id"]
    summary_file, report_file = _spawned_run_paths(app_factory, run_id)
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    bad = _zero_spin_summary()
    bad["sampling"].pop("stop_reason", None)
    summary_file.write_text(json.dumps(bad), encoding="utf-8")
    report_file.write_text("# empty\n", encoding="utf-8")

    app_factory.stub_popen.processes[-1].finish(code=0)
    wait_until_fixture(
        lambda: c.get(f"/api/runs/{run_id}").json().get("status") == "failed",
        timeout=5.0,
    )
    msg = c.get(f"/api/runs/{run_id}").json().get("error_message") or ""
    assert "0 spins" in msg
    assert "stop_reason=unknown" in msg


# ---------- delete ----------


def test_delete_run_removes_row_and_report_artefacts(
    client, app_factory, wait_until_fixture
):
    """DELETE /api/runs/{id} must drop the row, delete the per-run
    artefacts (progress/summary/report), remove the report-version
    directory under reports/<machine>/mode_<n>/versions/<rv>/, and
    roll back index.json + latest.json."""
    c, _app = client
    resp = c.post("/api/runs", json=_run_payload())
    run_id = resp.json()["run_id"]
    summary_file, report_file = _spawned_run_paths(app_factory, run_id)
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(_good_summary()), encoding="utf-8")
    report_file.write_text("# r\n", encoding="utf-8")
    app_factory.stub_popen.processes[-1].finish(code=0)
    wait_until_fixture(
        lambda: c.get(f"/api/runs/{run_id}").json().get("status") == "completed",
        timeout=5.0,
    )

    # Pre-conditions: the index carries this run, latest points at it,
    # and the version dir exists on disk.
    index_path = app_factory.reports_dir / "M14" / "mode_1" / "index.json"
    latest_path = app_factory.reports_dir / "M14" / "mode_1" / "latest.json"
    version_dir = summary_file.parent
    assert version_dir.is_dir()
    assert any(e.get("run_id") == run_id for e in json.loads(index_path.read_text(encoding="utf-8")))
    assert json.loads(latest_path.read_text(encoding="utf-8")).get("run_id") == run_id

    resp = c.delete(f"/api/runs/{run_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] is True

    # Row gone.
    assert c.get(f"/api/runs/{run_id}").status_code == 404

    # Version directory + manifests rolled back.
    assert not version_dir.exists(), "report version dir was not removed"
    index_now = json.loads(index_path.read_text(encoding="utf-8"))
    assert not any(e.get("run_id") == run_id for e in index_now), (
        "run still present in index.json after delete"
    )
    # Only one version existed -> latest.json cleared entirely.
    assert not latest_path.exists(), "latest.json should be removed when the last version is deleted"


def test_delete_run_rolls_back_latest_to_previous_version(
    client, app_factory, wait_until_fixture
):
    """When deleting the currently-latest version but older versions
    remain, latest.json must roll back to the newest surviving entry
    rather than dangling."""
    c, _app = client

    def _complete_run():
        resp = c.post("/api/runs", json=_run_payload())
        rid = resp.json()["run_id"]
        sfile, rfile = _spawned_run_paths(app_factory, rid)
        sfile.parent.mkdir(parents=True, exist_ok=True)
        sfile.write_text(json.dumps(_good_summary()), encoding="utf-8")
        rfile.write_text("# r\n", encoding="utf-8")
        app_factory.stub_popen.processes[-1].finish(code=0)
        wait_until_fixture(
            lambda: c.get(f"/api/runs/{rid}").json().get("status") == "completed",
            timeout=5.0,
        )
        return rid

    run_a = _complete_run()
    run_b = _complete_run()  # run_b is the newest -> latest.json points at it

    latest_path = app_factory.reports_dir / "M14" / "mode_1" / "latest.json"
    assert json.loads(latest_path.read_text(encoding="utf-8")).get("run_id") == run_b

    # Delete the newest; latest should roll back to run_a.
    resp = c.delete(f"/api/runs/{run_b}")
    assert resp.status_code == 200
    assert latest_path.exists(), "latest.json must still exist when older versions remain"
    assert json.loads(latest_path.read_text(encoding="utf-8")).get("run_id") == run_a


def test_delete_run_refuses_running(
    client, app_factory
):
    """Running runs are protected -- DELETE returns 409 and leaves the
    row alone so the operator can't nuke an in-flight analyzer."""
    c, _app = client
    resp = c.post("/api/runs", json=_run_payload())
    run_id = resp.json()["run_id"]
    assert resp.json()["status"] == "running"

    delete_resp = c.delete(f"/api/runs/{run_id}")
    assert delete_resp.status_code == 409, delete_resp.text

    # Row still present (status polled back from DB).
    assert c.get(f"/api/runs/{run_id}").status_code == 200


def test_delete_run_not_found(client):
    c, _app = client
    resp = c.delete("/api/runs/does-not-exist-xyz")
    assert resp.status_code == 404


# ---------- backfill RTP/CI ----------


def test_backfill_rtp_ci_from_summaries(app_factory, tmp_path):
    """Legacy rows from before the achieved_rtp_pct / _halfwidth_pp
    migration show as "\u2014" in the manage-tab history table forever
    unless backfilled. The backfill method walks completed rows where
    either column is NULL, reads their on-disk summary.json, and
    populates the columns. Safe to run on every startup (no-op for
    already-populated rows; skips rows whose summary_file is missing)."""
    import sqlite3

    # Instantiate the app so the schema + migrations run.
    app_factory()

    # Seed a completed row that has no achieved_rtp_pct / halfwidth
    # (simulating pre-migration data) but points at a summary file we
    # write on disk.
    summary_path = tmp_path / "legacy_summary.json"
    summary_path.write_text(
        json.dumps({
            "rtp": {"point_pct": 92.35},
            "sampling": {"achieved_halfwidth_pp": 0.48},
        }),
        encoding="utf-8",
    )

    conn = sqlite3.connect(str(app_factory.db_path))
    try:
        conn.execute(
            """
            INSERT INTO runs (
              run_id, machine, mode, status, model_id, created_at,
              started_at, target_halfwidth_pp, chunk_spin_times,
              chunk_robot_count, batch_concurrency, max_chunks, timeout,
              bankruptcy_session_spins, bankruptcy_bankroll_multipliers,
              report_version, output_dir, progress_file, summary_file
            ) VALUES (
              'legacy_run_x', 'M14', 1, 'completed', 'gpt', '2026-04-01T00:00:00Z',
              '2026-04-01T00:00:00Z', 0.5, 5000, 20, 2, 120, 300,
              500, '100,200,500', 'rv_legacy', ?, ?, ?
            )
            """,
            (str(tmp_path), str(tmp_path / "p.jsonl"), str(summary_path)),
        )
        conn.commit()
    finally:
        conn.close()

    # Also seed a row whose summary file does NOT exist -- should be
    # counted as skipped_no_file, not updated.
    conn = sqlite3.connect(str(app_factory.db_path))
    try:
        conn.execute(
            """
            INSERT INTO runs (
              run_id, machine, mode, status, model_id, created_at,
              started_at, target_halfwidth_pp, chunk_spin_times,
              chunk_robot_count, batch_concurrency, max_chunks, timeout,
              bankruptcy_session_spins, bankruptcy_bankroll_multipliers,
              report_version, output_dir, progress_file, summary_file
            ) VALUES (
              'ghost_run', 'M14', 1, 'completed', 'gpt', '2026-04-01T00:00:00Z',
              '2026-04-01T00:00:00Z', 0.5, 5000, 20, 2, 120, 300,
              500, '100,200,500', 'rv_ghost', '/nx', '/nx/p.jsonl', '/nx/summary.json'
            )
            """,
        )
        conn.commit()
    finally:
        conn.close()

    # Trigger the backfill directly (startup already ran once on empty DB).
    from src.web_console.backend.app import StateStore
    store = StateStore(app_factory.db_path)
    result = store.backfill_rtp_ci_from_summaries()

    assert result["scanned"] == 2
    assert result["updated"] == 1
    assert result["skipped_no_file"] == 1

    # Verify the legacy row now has both columns filled.
    conn = sqlite3.connect(str(app_factory.db_path))
    try:
        row = conn.execute(
            "SELECT achieved_rtp_pct, achieved_halfwidth_pp FROM runs WHERE run_id = ?",
            ("legacy_run_x",),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == 92.35
    assert row[1] == 0.48

    # Ghost row remains null.
    conn = sqlite3.connect(str(app_factory.db_path))
    try:
        row = conn.execute(
            "SELECT achieved_rtp_pct, achieved_halfwidth_pp FROM runs WHERE run_id = ?",
            ("ghost_run",),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] is None
    assert row[1] is None

    # Running a second time is a no-op (idempotent).
    result2 = store.backfill_rtp_ci_from_summaries()
    assert result2["scanned"] == 1  # legacy_run_x is now populated, only ghost remains null
    assert result2["updated"] == 0
    assert result2["skipped_no_file"] == 1
