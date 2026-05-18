"""Tests for POST /api/rawdata/{machine}/generate-report.

This endpoint reads chunks out of the rawdata tree, runs the analyzer
against the pre-loaded responses, and produces a brand-new report
version + run row. Crucially:

* old run rows are untouched (history preserved)
* the new row carries the current analyzer_version fingerprint so
  staleness checks line up immediately
* stale-md5 chunks are skipped (their server config drifted); only
  kept + deletable chunks contribute
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.web_console.backend.cell_lock_registry import CellOperation


_M14_FIXTURE = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures"
    / "m14_mode1_r8_s50.json"
)


def _write_rawdata_chunk(
    dir_: Path,
    idx: int,
    *,
    config_md5: str,
    code_md5: str,
    response: list,
    spin_times: int = 50,
    robot_count: int = 8,
) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / f"chunk_{idx:04d}.json"
    p.write_text(json.dumps({
        "_cache_version": 3,
        "_machine": "M14",
        "_mode": 1,
        "_bet": 1000,
        "_spin_times": spin_times,
        "_robot_count": robot_count,
        "_chunk_index": idx,
        "_saved_at": "2026-04-01T00:00:00Z",
        "_config_md5": config_md5,
        "_code_md5": code_md5,
        "response": response,
    }), encoding="utf-8")
    return p


@pytest.fixture
def m14_machines_config(tmp_path):
    """machines.json with M14 md5s matching whatever we stamp on test
    chunks — makes them kept/deletable rather than stale."""
    p = tmp_path / "machines_m14.json"
    p.write_text(json.dumps({"machines": [{
        "machine": "M14", "modes": [1],
        "configSummaryMd5": "test_cfg", "codeSummaryMd5": "test_code",
    }]}), encoding="utf-8")
    return p


@pytest.fixture
def app_with_m14(
    tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
    m14_machines_config, fake_analyzer, monkeypatch,
):
    monkeypatch.setattr(
        "src.web_console.backend.app._default_popen_factory",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )
    # Analyzer calls os._exit(rc) at end; no-op it for in-process test
    monkeypatch.setattr("os._exit", lambda rc: None)
    from src.web_console.backend.app import create_app
    from fastapi.testclient import TestClient
    app = create_app(
        state_dir=tmp_state_dir, reports_root=tmp_reports,
        cache_root=tmp_cache, machines_config=m14_machines_config,
        analyzer_path=fake_analyzer, rawdata_root=tmp_rawdata,
    )
    with TestClient(app) as c:
        yield c, app, tmp_rawdata, tmp_reports, tmp_state_dir


class TestGenerateReportHappyPath:
    def test_produces_new_report_version_and_run_row(self, app_with_m14):
        c, _app, rd_root, reports_root, state_dir = app_with_m14
        response_payload = json.loads(_M14_FIXTURE.read_text(encoding="utf-8"))

        mode_dir = rd_root / "M14" / "mode_1"
        _write_rawdata_chunk(
            mode_dir, 1, config_md5="test_cfg", code_md5="test_code",
            response=response_payload,
        )

        resp = c.post(
            "/api/rawdata/M14/generate-report",
            json={"mode": 1},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["machine"] == "M14"
        assert body["mode"] == 1
        assert body["chunks_processed"] == 1
        assert body["run_id"].startswith("gen_")
        assert body["report_version"].startswith("rv_") and body["report_version"].endswith("_rawdata")
        # RTP should be a number (analyzer ran successfully against fixture)
        assert isinstance(body["rtp_point_pct"], (int, float))
        # Analyzer version stamp was returned → matches current hash
        assert isinstance(body["analyzer_version"], str)
        assert len(body["analyzer_version"]) == 12

        # Summary file actually written to disk under the new version
        version_dir = (
            reports_root / "M14" / "mode_1" / "versions"
            / body["report_version"]
        )
        assert (version_dir / "player_impact_summary.json").exists()
        assert (version_dir / "player_impact_report.md").exists()

        # Run row inserted with status=completed + version fingerprints.
        # Note: analyzer's _lookup_machine_md5 reads from the real
        # configs/machines.json at runtime (not the test's tmp config),
        # so rawdata_config_md5 / rawdata_code_md5 reflect whatever the
        # committed machines.json has for M14 — assert shape not value.
        r2 = c.get(f"/api/runs/{body['run_id']}")
        assert r2.status_code == 200
        row = r2.json()
        assert row["status"] == "completed"
        assert row["machine"] == "M14"
        assert row["mode"] == 1
        assert row["achieved_rtp_pct"] is not None
        assert isinstance(row["rawdata_config_md5"], str) and row["rawdata_config_md5"]
        assert isinstance(row["rawdata_code_md5"], str) and row["rawdata_code_md5"]
        assert row["analyzer_version"] == body["analyzer_version"]

    def test_preserves_existing_runs(self, app_with_m14):
        """Pre-existing runs row on M14 stays untouched after a
        generate-report call — history is never overwritten."""
        c, _app, rd_root, _reports, _state = app_with_m14
        # Seed a fake existing run row for M14 mode 1 via direct DB.
        import sqlite3
        db = _state / "console.db"
        with sqlite3.connect(db) as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, machine, mode, status, model_id,
                    created_at, started_at, target_halfwidth_pp,
                    chunk_spin_times, chunk_robot_count, batch_concurrency,
                    max_chunks, timeout, bankruptcy_session_spins,
                    bankruptcy_bankroll_multipliers, report_version,
                    output_dir, progress_file, summary_file)
                VALUES ('old_run_abc', 'M14', 1, 'completed', 'sdk',
                    '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z',
                    0.5, 5000, 24, 2, 10, 30, 500,
                    '100,200,500', 'rv_old', '/d', '/d/p.jsonl', '/d/s.json')
                """
            )
            conn.commit()

        response_payload = json.loads(_M14_FIXTURE.read_text(encoding="utf-8"))
        _write_rawdata_chunk(
            rd_root / "M14" / "mode_1", 1,
            config_md5="test_cfg", code_md5="test_code",
            response=response_payload,
        )
        gen = c.post("/api/rawdata/M14/generate-report", json={"mode": 1})
        assert gen.status_code == 200, gen.text

        runs = c.get("/api/runs").json()["runs"]
        ids = [r["run_id"] for r in runs]
        # Both the pre-existing row and the new gen_* row must survive.
        assert "old_run_abc" in ids
        assert gen.json()["run_id"] in ids


class TestGenerateReportProcessesAllChunks:
    """Regression guard for the session-CI early-stop bug: with target
    = 999pp, the analyzer's ``session_ci <= target`` check fires after
    chunks >= 2 because nearly any session CI drops below 999pp
    immediately. That caused M273 mode 1 rebuild to stop after 2 of
    51 chunks (stop_reason=target_ci_reached) and report 3.43pp CI
    instead of the 0.5pp the rawdata could actually support.

    Fix: target=0.001 so the CI-stop branch never fires; max_chunks
    (= cached response count) becomes the sole termination gate.
    """

    def test_three_chunks_all_processed(self, app_with_m14):
        c, _app, rd_root, reports_root, _state = app_with_m14
        response_payload = json.loads(_M14_FIXTURE.read_text(encoding="utf-8"))
        mode_dir = rd_root / "M14" / "mode_1"
        # Three chunks of the same fixture — before the fix, only 2
        # would be consumed (session CI hits stop after chunk 2).
        for idx in (1, 2, 3):
            _write_rawdata_chunk(
                mode_dir, idx, config_md5="test_cfg", code_md5="test_code",
                response=response_payload,
            )
        resp = c.post("/api/rawdata/M14/generate-report", json={"mode": 1})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["chunks_processed"] == 3, (
            f"expected all 3 chunks processed, got {body['chunks_processed']}"
        )
        # Double-check via the written summary: chunks + stop_reason
        # must reflect full cache consumption, not early CI stop.
        version_dir = (
            reports_root / "M14" / "mode_1" / "versions"
            / body["report_version"]
        )
        summary = json.loads(
            (version_dir / "player_impact_summary.json").read_text(encoding="utf-8")
        )
        samp = summary.get("sampling", {})
        assert samp["chunks"] == 3
        assert samp["stop_reason"] != "target_ci_reached", (
            f"stop_reason should reflect max_chunks reached, not CI "
            f"target — got {samp['stop_reason']!r}"
        )


@pytest.fixture
def m1sim_virtual_config(tmp_path):
    """machines_config for a virtual machine. M1sim intentionally is NOT
    in the real repo's configs/machines.json — so real analyzer's
    ``_lookup_machine_md5("M1sim")`` returns ("", ""), which is
    exactly the regression scenario we need to test."""
    p = tmp_path / "machines_m1sim.json"
    p.write_text(json.dumps({"machines": [{
        "machine": "M1sim", "modes": [1],
        "configSummaryMd5": "M1SIM_CFG_MD5",
        "codeSummaryMd5": "M1SIM_CODE_MD5",
    }]}), encoding="utf-8")
    return p


@pytest.fixture
def app_with_m1sim(
    tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
    m1sim_virtual_config, fake_analyzer, monkeypatch,
):
    monkeypatch.setattr(
        "src.web_console.backend.app._default_popen_factory",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )
    monkeypatch.setattr("os._exit", lambda rc: None)
    from src.web_console.backend.app import create_app
    from fastapi.testclient import TestClient
    app = create_app(
        state_dir=tmp_state_dir, reports_root=tmp_reports,
        cache_root=tmp_cache, machines_config=m1sim_virtual_config,
        analyzer_path=fake_analyzer, rawdata_root=tmp_rawdata,
    )
    with TestClient(app) as c:
        yield c, app, tmp_rawdata, tmp_reports, tmp_state_dir


def _write_m1sim_chunk(dir_: Path, idx: int, response: list) -> Path:
    """M1sim-specific chunk writer — envelope md5 matches the
    m1sim_virtual_config so classify_chunks tags them kept/deletable."""
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / f"chunk_{idx:04d}.json"
    p.write_text(json.dumps({
        "_cache_version": 3,
        "_machine": "M1sim",
        "_mode": 1,
        "_bet": 1000,
        "_spin_times": 50,
        "_robot_count": 8,
        "_chunk_index": idx,
        "_saved_at": "2026-04-01T00:00:00Z",
        "_config_md5": "M1SIM_CFG_MD5",
        "_code_md5": "M1SIM_CODE_MD5",
        "response": response,
    }), encoding="utf-8")
    return p


class TestGenerateReportSummaryMd5Patch:
    """2026-04-22 regression: virtual-console reports always showed
    "无 fresh report" after clicking "⟳ 生成 Report".

    Root cause: real analyzer's ``_lookup_machine_md5(machine)`` reads
    ONLY the repo-level ``configs/machines.json`` (real-console
    registry). The in-process generate-report path
    (``_run_generate_report`` in ``src/web_console/backend/app.py``)
    calls ``pia.main()`` directly, which picks up that function with
    its hardcoded registry path — not the ``machines_config`` the
    backend was constructed with. For virtual machines that live in
    a separate registry (``machines_virtual.json``), the looked-up
    md5 is ``("", "")``, so the summary gets ``config_md5=""`` /
    ``code_md5=""``. Frontend's ``/api/report-validate`` then
    classifies the report as ``md5_status="untagged"`` and the
    rwtree cell's "fresh report" filter excludes it.

    Fix: after ``pia.main()`` returns rc=0, read the summary back,
    patch empty ``config_md5`` / ``code_md5`` fields with the
    current md5 from ``_get_machine_md5(machine, backend_mc)``
    (which DOES respect the injected machines_config), and write it
    back. Never overwrites values the analyzer already set.

    These tests use a fresh ``M1sim`` fixture with a virtual-console-
    style machines_config so the regression is hit cleanly (real
    repo's machines.json doesn't know M1sim → analyzer writes empty
    md5 → patch must fill it).
    """

    def test_empty_summary_md5_patched_from_injected_machines_config(
        self, app_with_m1sim,
    ):
        c, _app, rd_root, reports_root, _state = app_with_m1sim
        response_payload = json.loads(_M14_FIXTURE.read_text(encoding="utf-8"))
        mode_dir = rd_root / "M1sim" / "mode_1"
        _write_m1sim_chunk(mode_dir, 1, response_payload)
        resp = c.post("/api/rawdata/M1sim/generate-report", json={"mode": 1})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        version_dir = (
            reports_root / "M1sim" / "mode_1" / "versions"
            / body["report_version"]
        )
        summary = json.loads(
            (version_dir / "player_impact_summary.json").read_text(encoding="utf-8")
        )
        # Post-fix: real analyzer wrote config_md5="" (M1sim not in
        # repo's machines.json). Patch layer filled it from backend's
        # injected machines_config → "M1SIM_CFG_MD5" / "M1SIM_CODE_MD5".
        assert summary.get("config_md5") == "M1SIM_CFG_MD5", (
            f"summary.config_md5 must be patched from backend's "
            f"machines_config; got {summary.get('config_md5')!r}. "
            f"This is the regression that made the rwtree cell say "
            f"'无 fresh report' even for current-md5 reports."
        )
        assert summary.get("code_md5") == "M1SIM_CODE_MD5", (
            f"summary.code_md5 must be patched from backend's "
            f"machines_config; got {summary.get('code_md5')!r}"
        )

    def test_validate_endpoint_reports_md5_match_after_patch(
        self, app_with_m1sim,
    ):
        """End-to-end: patch → /api/report-validate → md5_status=match.
        This is the invariant the frontend's rwtree "fresh report"
        filter actually checks."""
        c, _app, rd_root, _reports, _state = app_with_m1sim
        response_payload = json.loads(_M14_FIXTURE.read_text(encoding="utf-8"))
        mode_dir = rd_root / "M1sim" / "mode_1"
        _write_m1sim_chunk(mode_dir, 1, response_payload)
        resp = c.post("/api/rawdata/M1sim/generate-report", json={"mode": 1})
        assert resp.status_code == 200
        body = resp.json()

        validate = c.get("/api/report-validate/M1sim")
        assert validate.status_code == 200
        v = validate.json()
        for rep in v.get("reports", []):
            if rep.get("version") == body["report_version"]:
                assert rep["md5_status"] == "match", (
                    f"new report must be tagged md5_status=match "
                    f"for the rwtree 'fresh' filter to include it; "
                    f"got {rep!r}"
                )
                return
        raise AssertionError(
            f"new report {body['report_version']} not found in "
            f"validate response: {v!r}"
        )


class TestBatchGenerateReport:
    """Tests for the batch endpoint + background worker. Driver runs
    items sequentially inside a daemon thread; tests poll the GET
    endpoint until the batch reaches a terminal state (completed /
    partial / failed).
    """

    @staticmethod
    def _wait_for_terminal(client, batch_id, timeout_s=10):
        import time
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            state = client.get(
                f"/api/rawdata/batch-generate-report/{batch_id}"
            ).json()
            if state["status"] in ("completed", "partial", "failed"):
                return state
            time.sleep(0.1)
        raise AssertionError(
            f"batch {batch_id} did not reach terminal state in {timeout_s}s"
        )

    def test_all_items_succeed(self, app_with_m14):
        """Two chunks × two modes → 2 items, both complete."""
        c, _app, rd_root, reports_root, _state = app_with_m14
        response_payload = json.loads(_M14_FIXTURE.read_text(encoding="utf-8"))
        # Seed two mode dirs with one usable chunk each.
        for mode in (1, 2):
            _write_rawdata_chunk(
                rd_root / "M14" / f"mode_{mode}", 1,
                config_md5="test_cfg", code_md5="test_code",
                response=response_payload,
            )
        resp = c.post(
            "/api/rawdata/batch-generate-report",
            json={"items": [
                {"machine": "M14", "mode": 1},
                {"machine": "M14", "mode": 2},
            ]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2
        batch_id = body["batch_id"]
        assert batch_id.startswith("bgen_")

        final = self._wait_for_terminal(c, batch_id)
        assert final["status"] == "completed"
        assert final["completed"] == 2
        assert final["failed"] == 0
        assert final["pending"] == 0
        for item in final["items"]:
            assert item["status"] == "completed"
            assert item["run_id"] and item["run_id"].startswith("gen_")
            assert item["rtp_point_pct"] is not None
            assert item["chunks_processed"] == 1

    def test_partial_failure_continues_through_batch(self, app_with_m14):
        """Second item points at a mode with no rawdata — batch records
        per-item failure but keeps going and completes item 1 + item 3."""
        c, _app, rd_root, _reports, _state = app_with_m14
        response_payload = json.loads(_M14_FIXTURE.read_text(encoding="utf-8"))
        for mode in (1, 5):
            _write_rawdata_chunk(
                rd_root / "M14" / f"mode_{mode}", 1,
                config_md5="test_cfg", code_md5="test_code",
                response=response_payload,
            )
        resp = c.post(
            "/api/rawdata/batch-generate-report",
            json={"items": [
                {"machine": "M14", "mode": 1},
                {"machine": "M14", "mode": 2},  # no rawdata → fails
                {"machine": "M14", "mode": 5},
            ]},
        )
        assert resp.status_code == 200, resp.text
        final = self._wait_for_terminal(c, resp.json()["batch_id"])
        assert final["status"] == "partial"
        assert final["completed"] == 2
        assert final["failed"] == 1
        assert final["items"][0]["status"] == "completed"
        assert final["items"][1]["status"] == "failed"
        assert "no rawdata" in final["items"][1]["error"].lower()
        assert final["items"][2]["status"] == "completed"

    def test_rejects_empty_items(self, app_with_m14):
        c, *_ = app_with_m14
        resp = c.post("/api/rawdata/batch-generate-report", json={"items": []})
        assert resp.status_code == 400

    def test_rejects_non_integer_mode(self, app_with_m14):
        c, *_ = app_with_m14
        resp = c.post(
            "/api/rawdata/batch-generate-report",
            json={"items": [{"machine": "M14", "mode": "nope"}]},
        )
        assert resp.status_code == 400

    def test_get_unknown_batch_id_returns_404(self, app_with_m14):
        c, *_ = app_with_m14
        resp = c.get("/api/rawdata/batch-generate-report/bgen_does_not_exist")
        assert resp.status_code == 404

    def test_runs_sequentially_under_ops_lock(self, app_with_m14):
        """Second batch started while first in-flight must fail the
        second's items — no two concurrent GENERATING operations on the
        same cell. Here we simulate lock contention by acquiring GENERATING
        on M14|1 via the registry before the batch kick-off.
        """
        c, app, rd_root, *_ = app_with_m14
        response_payload = json.loads(_M14_FIXTURE.read_text(encoding="utf-8"))
        _write_rawdata_chunk(
            rd_root / "M14" / "mode_1", 1,
            config_md5="test_cfg", code_md5="test_code",
            response=response_payload,
        )
        # I6 (Round-3 fix): batch_generate_report now pre-checks the registry
        # at submit time and returns 409 synchronously instead of starting
        # the batch and failing the item asynchronously.  Pre-acquire GENERATING
        # so the pre-check fires immediately.
        assert app.state.registry.try_acquire_cell("M14", 1, CellOperation.GENERATING)
        try:
            resp = c.post(
                "/api/rawdata/batch-generate-report",
                json={"items": [{"machine": "M14", "mode": 1}]},
            )
            # I6: synchronous 409 at submit time (not 200 + async item failure).
            assert resp.status_code == 409
            assert "busy" in resp.json().get("detail", "").lower()
        finally:
            app.state.registry.release_cell("M14", 1, CellOperation.GENERATING)


class TestGenerateReportAsyncPath:
    """Async variant (``async=true``) pre-inserts a ``status=queued``
    placeholder row so the response can return a stable run_id for
    UI polling. 2026-04-22 regression: the placeholder originally
    carried ``progress_file=""`` — ``Path("")`` stringifies to ``.``
    (current dir) which ``exists()`` is True but ``read_text()``
    raises IsADirectoryError → ``/api/runs`` list endpoint 500s →
    real-browser click shows "生成 Report 失败: /api/runs: 500".
    """

    def test_async_returns_run_id(self, app_with_m14):
        """Response body must carry run_id so the frontend has a
        stable polling target from the moment the POST returns."""
        c, _app, rd_root, *_ = app_with_m14
        response_payload = json.loads(_M14_FIXTURE.read_text(encoding="utf-8"))
        _write_rawdata_chunk(
            rd_root / "M14" / "mode_1", 1,
            config_md5="test_cfg", code_md5="test_code",
            response=response_payload,
        )
        resp = c.post(
            "/api/rawdata/M14/generate-report",
            json={"mode": 1, "async": True},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["run_id"].startswith("gen_"), body
        assert body["machine"] == "M14"
        assert body["mode"] == 1

    def test_runs_list_does_not_500_with_placeholder_row(self, app_with_m14):
        """REGRESSION 2026-04-22: before the fix, ``/api/runs`` 500d
        the instant an async generate-report call's placeholder row
        existed — its ``progress_file`` was an empty string, which
        Path() resolves to the current dir and ``read_text()`` raises
        IsADirectoryError. The user's real-browser click showed
        "生成 Report 失败: /api/runs: 500" because the rwtree-gen-btn
        handler called ``refreshRunList()`` immediately after POST."""
        c, _app, rd_root, *_ = app_with_m14
        response_payload = json.loads(_M14_FIXTURE.read_text(encoding="utf-8"))
        _write_rawdata_chunk(
            rd_root / "M14" / "mode_1", 1,
            config_md5="test_cfg", code_md5="test_code",
            response=response_payload,
        )
        post_resp = c.post(
            "/api/rawdata/M14/generate-report",
            json={"mode": 1, "async": True},
        )
        assert post_resp.status_code == 200, post_resp.text
        new_rid = post_resp.json()["run_id"]

        # Immediately call /api/runs — placeholder row exists here,
        # thread may still be starting. Before the fix this was 500.
        runs_resp = c.get("/api/runs")
        assert runs_resp.status_code == 200, (
            "GET /api/runs must not 500 when a placeholder row is "
            "present — Path('') on progress_file triggered "
            "IsADirectoryError in the old code."
        )
        ids = [r["run_id"] for r in runs_resp.json()["runs"]]
        assert new_rid in ids, (
            f"placeholder row for {new_rid} must appear in /api/runs "
            f"immediately, not only after the thread flips to running"
        )

    def test_placeholder_row_has_real_progress_file_path(self, app_with_m14):
        """The placeholder row must carry a real (if not-yet-existing)
        progress_file path, not an empty string. Downstream Path()
        consumers assume non-empty paths."""
        c, _app, rd_root, _reports, state_dir = app_with_m14
        response_payload = json.loads(_M14_FIXTURE.read_text(encoding="utf-8"))
        _write_rawdata_chunk(
            rd_root / "M14" / "mode_1", 1,
            config_md5="test_cfg", code_md5="test_code",
            response=response_payload,
        )
        post_resp = c.post(
            "/api/rawdata/M14/generate-report",
            json={"mode": 1, "async": True},
        )
        new_rid = post_resp.json()["run_id"]

        # Fetch the row directly from the DB before the thread flips
        # it. progress_file should be non-empty and point into
        # state_dir/progress/.
        import sqlite3
        with sqlite3.connect(state_dir / "console.db") as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT progress_file FROM runs WHERE run_id=?", (new_rid,)
            ).fetchone()
        assert row is not None, f"placeholder row {new_rid} missing from DB"
        pf = row["progress_file"]
        assert pf, (
            f"progress_file must not be empty — empty string "
            f"stringifies to '.' via Path() and breaks readers. "
            f"Got: {pf!r}"
        )
        assert new_rid in pf, (
            f"progress_file {pf!r} should include run_id {new_rid} "
            f"so downstream writers land in the right file"
        )


class TestGenerateReportErrorPaths:
    def test_no_rawdata_returns_404(self, app_with_m14):
        c, *_ = app_with_m14
        resp = c.post("/api/rawdata/M14/generate-report", json={"mode": 1})
        assert resp.status_code == 404
        assert "no rawdata" in resp.json()["detail"].lower()

    def test_invalid_mode_returns_400(self, app_with_m14):
        c, *_ = app_with_m14
        resp = c.post("/api/rawdata/M14/generate-report",
                      json={"mode": "not an int"})
        assert resp.status_code == 400

    def test_only_stale_chunks_returns_404(self, app_with_m14):
        """If every chunk has outdated md5 (server upgraded since
        sampling), endpoint refuses — regenerating off stale rawdata
        would produce a stale report too. Resample required."""
        c, _app, rd_root, *_ = app_with_m14
        response_payload = json.loads(_M14_FIXTURE.read_text(encoding="utf-8"))
        _write_rawdata_chunk(
            rd_root / "M14" / "mode_1", 1,
            config_md5="OLD_CFG_STALE",  # doesn't match test_cfg
            code_md5="OLD_CODE_STALE",
            response=response_payload,
        )
        resp = c.post("/api/rawdata/M14/generate-report", json={"mode": 1})
        assert resp.status_code == 404
        assert "no usable chunks" in resp.json()["detail"].lower()

    def test_mutex_collision_returns_409(self, app_with_m14):
        c, app, rd_root, *_ = app_with_m14
        response_payload = json.loads(_M14_FIXTURE.read_text(encoding="utf-8"))
        _write_rawdata_chunk(
            rd_root / "M14" / "mode_1", 1,
            config_md5="test_cfg", code_md5="test_code",
            response=response_payload,
        )
        # Phase 2: pre-acquire GENERATING on M14|1 so _run_generate_report
        # returns 409 "cell busy" (replaces old OperationCoordinator mutex).
        assert app.state.registry.try_acquire_cell("M14", 1, CellOperation.GENERATING)
        try:
            resp = c.post("/api/rawdata/M14/generate-report", json={"mode": 1})
            assert resp.status_code == 409
            assert "busy" in resp.json()["detail"].lower()
        finally:
            app.state.registry.release_cell("M14", 1, CellOperation.GENERATING)
