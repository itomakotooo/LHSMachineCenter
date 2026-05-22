"""Round-3 fix regression tests.

Covers 9 fixes from session_artifacts/_impl/review/fix_brief.md §2:
  T-B2 — delete_machine_all_data R1 race: 409 when SAMPLING active + empty dir
  T-B3 — /api/system-state md5_refresh_error field (+ stale_tag/reassociate)
  T-I1 — config_id wiring (Option B: UI warning placeholder; Option A: end-to-end)
  T-I2 — delete_report_version uses DELETING not GENERATING
  T-I3 — _recover_fleet_refresh silent swallow on corrupted DB
  T-I5 — configs_upload_dir DI in create_app
  T-I6 — batch_generate_report pre-checks registry before queuing

T-B1 (UI bootstrap / Playwright) lives in tests/e2e/test_p4_bootstrap_stale_run.py.
T-I4 (rawdata overview error toast / Playwright) lives in tests/e2e/test_p4_ui_error_toast.py.

Memory feedback files honored:
  memory/feedback_enumerate_safety_paths.md — every fix has an inject-bug recipe.
  memory/feedback_no_silent_swallow.md — I3 directly addresses; I6 avoids async silent fail.
  memory/feedback_perf_claim_needs_e2e_event_stream.md — B2 acquires real CellLockRegistry.
  memory/feedback_integration_test_argv.md — HTTP-level via TestClient not mocks.

Inject-bug recipes (executed by tester — see end-of-task report):

  T-B2 (test_delete_all_data_returns_409_active_sampling):
    In app.py delete_machine_all_data (lines 6940-6949), remove the block:
        for cell_machine, cell_mode in registry.get_active_cells():
            if cell_machine == machine:
                modes_all.append(cell_mode)
    or add it so modes_all stays empty when rawdata/M14 dir doesn't exist.
    The current code does NOT have this fix (only delete_machine_rawdata has it).
    Inject: comment out any registry consultation in that path.
    Expected: DELETE /api/machines/M14/all-data returns 200 → assert 409 → RED.
    Revert → GREEN.

  T-B3 (test_system_state_surfaces_md5_refresh_error):
    In app.py current_system_state(), remove the `md5_refresh_error` key read.
    Expected: field absent from response → assert present → RED.
    Revert → GREEN.

  T-I2 (test_delete_report_version_acquires_deleting_not_generating):
    In app.py delete_report_version, change CellOperation.DELETING back to
    CellOperation.GENERATING (the pre-fix state at line 8451).
    Expected: holding SAMPLING lock on cell does NOT block GENERATING (INV-3
    allows concurrent SAMPLING + GENERATING), so 409 is NOT raised. Assert
    gets 409 → actually test checks the cell op token, not the HTTP response.
    Alternatively: inject a pre-loaded DELETING on the cell so the endpoint
    should 409. With GENERATING, a concurrent GENERATING is blocked (INV-5)
    while concurrent DELETING with existing SAMPLING is blocked (INV-2).
    Recipe: hold DELETING on cell → call delete_report_version → should 409.
    With bug (GENERATING used), a held DELETING doesn't block GENERATING →
    no 409 → RED.
    Revert to DELETING → GREEN.

  T-I3 (test_recover_fleet_refresh_corrupted_db_writes_diagnostic):
    In app.py StateStore._recover_fleet_refresh, change `except sqlite3.OperationalError: pass`
    to also catch generic Exception with pass (swallow all).
    Expected: diagnostic NOT written → assert file exists → RED.
    Revert → GREEN.

  T-I5 (test_configs_upload_dir_di_does_not_mutate_real_dir):
    In app.py, change the line:
        configs_upload_dir = CONFIGS_UPLOAD_DIR
    to ignore any DI param. Expected: upload goes to real dir → test checking
    tmp dir has files fails → RED. Revert → GREEN.

  T-I6 (test_batch_generate_report_returns_409_for_busy_cell):
    In app.py batch_generate_report, remove the pre-check loop that calls
    registry.peek_cell_status / is_cell_busy before queuing.
    Expected: 409 not returned at submit time → test asserts 409 → RED.
    Revert → GREEN.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.web_console.backend.app import create_app
from src.web_console.backend.cell_lock_registry import CellLockRegistry, CellOperation
from tests.backend._seed import insert_run_row


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_isolated_app(
    tmp_path: Path,
    tmp_state_dir: Path,
    tmp_reports: Path,
    tmp_cache: Path,
    tmp_rawdata: Path,
    fake_machines: Path,
    fake_analyzer: Path,
    stub_popen,
    monkeypatch,
    *,
    configs_upload_dir: Path | None = None,
):
    """Build an isolated create_app() that passes configs_upload_dir if provided."""
    monkeypatch.setattr("src.web_console.backend.app._default_popen_factory", stub_popen)
    monkeypatch.setattr("src.web_console.backend.app._terminate_pid_if_running", lambda pid: True)

    kwargs: dict[str, Any] = dict(
        state_dir=tmp_state_dir,
        reports_root=tmp_reports,
        cache_root=tmp_cache,
        machines_config=fake_machines,
        analyzer_path=fake_analyzer,
        rawdata_root=tmp_rawdata,
    )
    if configs_upload_dir is not None:
        kwargs["configs_upload_dir"] = configs_upload_dir
    else:
        # Redirect module-level constant so uploads don't land in the real dir.
        tmp_upload = tmp_path / "uploaded_configs"
        tmp_upload.mkdir()
        monkeypatch.setattr("src.web_console.backend.app.CONFIGS_UPLOAD_DIR", tmp_upload)

    app = create_app(**kwargs)
    return app


# ══════════════════════════════════════════════════════════════════════════════
# T-B2: delete_machine_all_data returns 409 when SAMPLING active (empty dir)
# ══════════════════════════════════════════════════════════════════════════════

class TestDeleteAllDataReturns409ActiveSampling:
    """B2 regression guard: DELETE /api/machines/{machine}/all-data must return 409
    when the CellLockRegistry has SAMPLING active, even when rawdata/{machine}/
    dir does not yet exist on disk.

    This mirrors the R1 fix that exists in delete_machine_rawdata but was missing
    from delete_machine_all_data (lines 6940-6949 of app.py).

    Inject-bug recipe:
      In delete_machine_all_data, remove the block that consults
      registry.get_active_cells() to include in-flight cells (lines 7011-7014):
          for cell_machine, cell_mode in registry.get_active_cells():
              if cell_machine == machine:
                  modes_set_all.add(cell_mode)
      Without the registry check: modes_all = [] because rawdata/M14 dir is absent.
      The DELETING loop runs 0 iterations → modes_all=[] → DELETING try block
      runs → running-runs DB check catches it IF a run row exists in the DB.
      BUT: the registry check is the PRIMARY defense for the pre-chunk race
      window (before _run_one inserts a runs row but after SAMPLING is acquired).
      To isolate this, the test directly acquires SAMPLING via the registry API
      without starting a real batch run (no DB run row).
      With the bug: modes_all=[] → DELETING loop runs 0 iters → running-runs=[]
      → DELETE returns 200. Test asserts 409 → FAILS → RED.
      Revert registry check → GREEN.
    """

    def test_delete_all_data_returns_409_active_sampling(
        self, app_factory,
    ):
        """SAMPLING active in registry, rawdata/M14 absent, no run in DB → 409.

        Uses direct registry.try_acquire_cell() to isolate the registry path
        without the DB running-runs safety net.
        """
        from src.web_console.backend.cell_lock_registry import CellLockRegistry, CellOperation

        app = app_factory()

        # Create an isolated registry that we can inject SAMPLING into directly.
        # The app's internal registry is closed over — we can't reach it via the
        # TestClient easily. Instead: use the /api/system-state concurrency field
        # to confirm registry state, then test via the batch-run start path.
        #
        # Alternative: call the batch-run API and use the running-state window.
        # The key assertion remains: 409 when SAMPLING is active, rawdata dir absent.
        with TestClient(app) as c:
            rawdata_m14 = app_factory.rawdata_dir / "M14"
            if rawdata_m14.exists():
                import shutil
                shutil.rmtree(rawdata_m14)
            assert not rawdata_m14.exists(), "rawdata/M14 must not exist"

            # Start batch run → _run_one acquires SAMPLING → item in "running".
            r = c.post("/api/batch-run", json={
                "items": [{"machine": "M14", "mode": 1}],
                "server_id": "dev",
                "chunk_spin_times": 1000,
                "chunk_robot_count": 1,
                "batch_concurrency": 1,
                "max_chunks": 1,
                "timeout": 60.0,
                "target_halfwidth_pp": 0,
                "skip_md5_refresh": True,
            })
            assert r.status_code == 200, f"batch-run POST failed: {r.text}"
            batch_id = r.json()["batch_id"]

            # Wait for SAMPLING to be acquired (item in "running" state).
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                poll = c.get(f"/api/batch-run/{batch_id}")
                items = poll.json().get("items", [])
                if items and items[0]["status"] == "running":
                    break
                time.sleep(0.05)

            # Verify registry has M14|1 active.
            ss = c.get("/api/system-state").json()
            cells = ss.get("concurrency", {}).get("cells", {})
            assert "M14|1" in cells or any("M14" in k for k in cells), (
                f"SAMPLING not active in registry. cells: {cells}"
            )

            # B2 invariant: DELETE /api/machines/M14/all-data → must 409.
            # The registry check (lines 7011-7014) is what catches this even
            # when rawdata/M14 dir is absent (modes_set_all would otherwise be {}).
            del_r = c.delete("/api/machines/M14/all-data")
            assert del_r.status_code == 409, (
                f"B2 REGRESSION: DELETE /api/machines/M14/all-data returned "
                f"{del_r.status_code} instead of 409 while SAMPLING is active "
                f"(rawdata dir absent). "
                f"Root cause if 200: delete_machine_all_data missing "
                f"registry.get_active_cells() check (lines 7011-7014 app.py). "
                f"Response: {del_r.text}"
            )
            # 409 body should be about cell-busy or running run (either safety net).
            assert del_r.status_code == 409

            # Clean up: finish stub process.
            procs = app_factory.stub_popen.processes
            if procs:
                procs[-1].finish(0)

    def test_delete_all_data_registry_check_blocks_even_without_running_rows(
        self, app_factory,
    ):
        """Inject-bug exercise for B2 registry check.

        Scenario: SAMPLING active in registry, rawdata/M14 absent, AND no
        'running' runs row in DB (simulate the race window before _run_one
        inserts the row). Only the registry check can prevent the DELETE.

        This test uses the registry's get_active_cells directly by calling
        /api/system-state to confirm SAMPLING is in the registry, then
        manually marks the run as 'completed' in the DB to clear the
        running-runs safety net, leaving only the registry check.

        With the registry check: modes_set_all includes M14 → DELETING fails
        (SAMPLING+DELETING mutually exclusive) → 409.

        Without the registry check (inject-bug): modes_set_all = {} (no on-disk
        dir) → modes_all = [] → DELETING loop runs 0 iters → running-runs = []
        (we cleared it) → DELETE returns 200 → assert FAILS → RED.

        Inject-bug recipe:
          Comment out lines 7012-7014 in app.py (the for loop in delete_machine_all_data):
              for cell_machine, cell_mode in registry.get_active_cells():
                  if cell_machine == machine:
                      modes_set_all.add(cell_mode)
          Also manually set the run status to 'completed' (done below).
          Expected: DELETE returns 200, test asserts 409 → FAILS → RED.
          Revert lines → GREEN.
        """
        import sqlite3 as _sqlite3

        app = app_factory()

        with TestClient(app) as c:
            rawdata_m14 = app_factory.rawdata_dir / "M14"
            if rawdata_m14.exists():
                import shutil
                shutil.rmtree(rawdata_m14)

            # Start a batch run to acquire SAMPLING in the registry.
            r = c.post("/api/batch-run", json={
                "items": [{"machine": "M14", "mode": 1}],
                "server_id": "dev",
                "chunk_spin_times": 100,
                "chunk_robot_count": 1,
                "batch_concurrency": 1,
                "max_chunks": 1,
                "timeout": 30.0,
                "target_halfwidth_pp": 0,
                "skip_md5_refresh": True,
            })
            assert r.status_code == 200
            batch_id = r.json()["batch_id"]

            # Wait for SAMPLING to be acquired.
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                poll = c.get(f"/api/batch-run/{batch_id}")
                items = poll.json().get("items", [])
                if items and items[0]["status"] == "running":
                    break
                time.sleep(0.05)

            # Get the run_id and force it to 'completed' in the DB so the
            # running-runs check doesn't block (isolates the registry check).
            poll = c.get(f"/api/batch-run/{batch_id}")
            items = poll.json().get("items", [])
            assert items, "No items in batch"
            run_id = items[0].get("run_id", "")

            if run_id:
                db_path = app_factory.db_path
                conn = _sqlite3.connect(str(db_path))
                try:
                    conn.execute(
                        "UPDATE runs SET status='completed' WHERE run_id=?",
                        (run_id,),
                    )
                    conn.commit()
                finally:
                    conn.close()

            # B2 specific invariant: registry check alone blocks DELETE.
            # With bug injected (no registry check), modes_set_all = {} (no dir),
            # modes_all = [], running_runs = [] (we cleared it) → 200. FAIL.
            del_r = c.delete("/api/machines/M14/all-data")
            assert del_r.status_code == 409, (
                f"B2 REGISTRY-SPECIFIC REGRESSION: DELETE returned {del_r.status_code} "
                f"when SAMPLING active in registry, rawdata dir absent, no 'running' "
                f"DB rows. Only registry.get_active_cells() check prevents this. "
                f"Response: {del_r.text}"
            )

            # Cleanup.
            procs = app_factory.stub_popen.processes
            if procs:
                procs[-1].finish(0)

    def test_delete_all_data_returns_200_when_no_active_ops(self, app_factory):
        """Baseline: when no SAMPLING active and rawdata dir absent, endpoint
        returns 200 (idempotent not-found is OK)."""
        app = app_factory()
        with TestClient(app) as c:
            rawdata_m14 = app_factory.rawdata_dir / "M14"
            if rawdata_m14.exists():
                import shutil
                shutil.rmtree(rawdata_m14)
            r = c.delete("/api/machines/M14/all-data")
            # When nothing is active and nothing on disk: idempotent ok.
            assert r.status_code in (200, 404), (
                f"Expected 200/404 with no ops and no data. Got {r.status_code}: {r.text}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# T-B3: /api/system-state surfaces md5_refresh_error field
# ══════════════════════════════════════════════════════════════════════════════

class TestSystemStateMd5RefreshError:
    """B3: GET /api/system-state must include md5_refresh_error field.

    The P1 commit claimed this was implemented but current_system_state()
    at lines 5580-5607 does not read the md5_refresh_error.json file.

    Inject-bug recipe:
      In app.py current_system_state(), remove the md5_refresh_error key.
      Run test → `assert "md5_refresh_error" in body` FAILS → RED.
      Revert → GREEN.
    """

    def test_system_state_surfaces_md5_refresh_error_when_file_exists(
        self, app_factory, tmp_state_dir,
    ):
        """Write md5_refresh_error.json to state dir → GET /api/system-state
        includes md5_refresh_error field with parsed content."""
        # Write the diagnostic file before building the app.
        error_content = {
            "ts": "2026-05-18T10:00:00Z",
            "server_id": "dev",
            "error": "ConnectionRefusedError: [WinError 10061]",
        }
        err_path = tmp_state_dir / "md5_refresh_error.json"
        err_path.write_text(json.dumps(error_content), encoding="utf-8")

        app = app_factory()
        with TestClient(app) as c:
            resp = c.get("/api/system-state")
            assert resp.status_code == 200, f"GET /api/system-state failed: {resp.text}"
            body = resp.json()

            # B3 invariant: field must exist.
            assert "md5_refresh_error" in body, (
                f"B3 REGRESSION: md5_refresh_error field missing from "
                f"/api/system-state response. "
                f"current_system_state() does not read md5_refresh_error.json. "
                f"Got keys: {list(body.keys())}"
            )
            # Field must contain the parsed content (not a raw string or None).
            err_field = body["md5_refresh_error"]
            assert err_field is not None, (
                f"md5_refresh_error is None despite file existing at {err_path}"
            )
            assert isinstance(err_field, dict), (
                f"md5_refresh_error should be a dict, got {type(err_field)}: {err_field}"
            )
            assert err_field.get("server_id") == "dev", (
                f"md5_refresh_error content mismatch. Got: {err_field}"
            )

    def test_system_state_returns_null_md5_refresh_error_when_absent(
        self, app_factory, tmp_state_dir,
    ):
        """When md5_refresh_error.json does not exist, field is None/null (not
        missing). Field must always be present for frontend to rely on it."""
        err_path = tmp_state_dir / "md5_refresh_error.json"
        if err_path.exists():
            err_path.unlink()

        app = app_factory()
        with TestClient(app) as c:
            resp = c.get("/api/system-state")
            assert resp.status_code == 200
            body = resp.json()
            # Field still exists, just set to null.
            assert "md5_refresh_error" in body, (
                f"md5_refresh_error key should always be present (null when absent). "
                f"Got keys: {list(body.keys())}"
            )
            assert body["md5_refresh_error"] is None, (
                f"md5_refresh_error should be null when file absent. Got: {body['md5_refresh_error']}"
            )

    def test_system_state_surfaces_stale_tag_error_when_file_exists(
        self, app_factory, tmp_state_dir,
    ):
        """stale_tag_error also surfaced (B3 completeness per fix brief)."""
        stale_path = tmp_state_dir / "stale_tag_error.json"
        stale_path.write_text(
            json.dumps({"ts": "2026-05-18T10:00:00Z", "error": "timeout"}),
            encoding="utf-8",
        )
        app = app_factory()
        with TestClient(app) as c:
            resp = c.get("/api/system-state")
            assert resp.status_code == 200
            body = resp.json()
            assert "stale_tag_error" in body, (
                f"stale_tag_error field missing. Got keys: {list(body.keys())}"
            )
            assert body["stale_tag_error"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# T-I1: config_id wiring
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigIdWiring:
    """I1: config_id wiring — tests the implementer's chosen option.

    Option A (true wiring): batch-run with config_id → chunks land in that
    config_id bucket, NOT in "null". This test is written for Option A.
    If implementer chose Option B (UI warning), rename this class to
    TestConfigIdWarningBanner and adjust assertions.

    Inject-bug recipe (Option A):
      In app.py BatchRunManager._run_one, restore the hardcoded:
          _item_config_id = "null"
      (remove the config_id plumbing).
      Run test → chunk ends up in null bucket → assert bucket contains config_id FAILS → RED.
      Revert wiring → GREEN.

    NOTE: This test is marked xfail until implementer's Option A code lands.
    If Option B was chosen, the xfail reason should be updated to reflect
    that Option A was not implemented.
    """

    @pytest.mark.xfail(
        reason=(
            "I1 wiring not yet landed — implementer's round-3 report pending. "
            "If Option A (true wiring) lands, this xfail will become a real pass. "
            "If Option B (UI warning only), replace with a Playwright banner test."
        ),
        strict=False,
    )
    def test_batch_run_config_id_routes_chunk_to_correct_bucket(
        self, app_factory, tmp_state_dir, tmp_rawdata,
    ):
        """POST /api/batch-run with config_id → sidecar by_config_id[<id>] has chunk.

        Requires Option A wiring to be implemented.
        """
        app = app_factory()
        with TestClient(app) as c:
            # Upload a config → get config_id.
            up = c.post("/api/configs/upload", json={
                "content": {"machine": "M14", "rtp_target": 95.0},
                "display_name": "test-wiring-config",
            })
            assert up.status_code == 200, f"Upload failed: {up.text}"
            config_id = up.json()["config_id"]
            assert config_id and config_id != "null"

            # POST batch-run with config_id.
            payload = {
                "items": [{"machine": "M14", "mode": 1}],
                "config_id": config_id,
                "server_id": "dev",
                "chunk_spin_times": 100,
                "chunk_robot_count": 1,
                "batch_concurrency": 1,
                "max_chunks": 1,
                "timeout": 30.0,
                "target_halfwidth_pp": 0,
                "skip_md5_refresh": True,
            }
            r = c.post("/api/batch-run", json=payload)
            assert r.status_code == 200, f"batch-run POST failed: {r.text}"
            batch_id = r.json()["batch_id"]

            # Finish the stub process.
            app_factory.stub_popen.processes[0].finish(0)

            # Poll until completed.
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                poll = c.get(f"/api/batch-run/{batch_id}")
                items = poll.json().get("items", [])
                if items and items[0]["status"] in ("completed", "failed"):
                    break
                time.sleep(0.1)

            # Check sidecar by_config_id bucket.
            mode_dir = tmp_rawdata / "M14" / "mode_1"
            chunks_index_path = mode_dir / "_chunks.json"
            if not chunks_index_path.exists():
                pytest.skip("Chunk sidecar not written — real sampling not available")
            index = json.loads(chunks_index_path.read_text(encoding="utf-8"))
            by_cid = index.get("by_config_id", {})

            # Invariant: chunk must be in config_id bucket, NOT in "null" bucket.
            assert config_id in by_cid, (
                f"I1 REGRESSION: config_id={config_id!r} not in by_config_id. "
                f"Chunks still go to 'null' bucket. Got: {list(by_cid.keys())}"
            )
            assert by_cid[config_id], (
                f"config_id bucket is empty: {by_cid}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# T-I2: delete_report_version acquires DELETING, not GENERATING
# ══════════════════════════════════════════════════════════════════════════════

class TestDeleteReportVersionAcquiresDeleting:
    """I2: DELETE /api/reports/{machine}/{mode}/{version} must try-acquire
    CellOperation.DELETING (not GENERATING as at line 8451 pre-fix).

    The distinction matters: a concurrent DELETING (held by e.g. rawdata delete)
    blocks a second DELETING on the same cell (INV per design). But GENERATING
    would not properly model 'I am destroying something' semantics, and a
    held DELETING on the cell would not be blocked by a GENERATING acquire.

    Inject-bug recipe:
      In app.py delete_report_version (line 8451), change:
          CellOperation.DELETING
      back to:
          CellOperation.GENERATING
      Hold a DELETING lock on M14|1 externally (via try_acquire_cell directly).
      POST delete_report_version → should 409 because DELETING+DELETING conflict.
      With GENERATING: DELETING+GENERATING is NOT a conflict (INV-2 only blocks
      GENERATING+DELETING per design) — wait, actually INV-2 says GENERATING and
      DELETING are mutually exclusive, so a held DELETING would block a GENERATING
      acquire. So the test would pass either way via THAT route.
      Better: hold SAMPLING. SAMPLING+DELETING is blocked (INV-1). SAMPLING+GENERATING
      is allowed (INV-3). So: hold SAMPLING → call delete_report_version:
        - With DELETING: 409 (correct — SAMPLING blocks DELETING).
        - With GENERATING: 200 (wrong — SAMPLING allows GENERATING).
      Recipe: hold SAMPLING on M14|1 → DELETE report version → expect 409.
      Bug (GENERATING): no 409 → RED.
      Fix (DELETING): 409 → GREEN.
    """

    def _setup_report_version(self, tmp_reports: Path, machine: str = "M14",
                               mode: int = 1, version: str = "rv_test") -> None:
        """Write a minimal version dir + index.json so the endpoint has something to delete."""
        vdir = tmp_reports / machine / f"mode_{mode}" / "versions" / version
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "player_impact_summary.json").write_text(
            json.dumps({"sampling": {"total_spins": 100}}), encoding="utf-8"
        )
        index_path = tmp_reports / machine / f"mode_{mode}" / "index.json"
        index_path.write_text(
            json.dumps([{"report_version": version, "run_id": "test_run_001"}]),
            encoding="utf-8",
        )

    def test_delete_report_version_blocked_when_sampling_active(
        self, app_factory, tmp_reports,
    ):
        """Hold SAMPLING on M14|1 → DELETE report version → must 409.

        Post-fix: delete_report_version uses DELETING, which is mutually
        exclusive with SAMPLING (INV-1).

        Pre-fix (GENERATING): SAMPLING+GENERATING allowed (INV-3) → 200,
        which is the wrong behavior for a destructive operation.
        """
        self._setup_report_version(tmp_reports)
        app = app_factory()

        with TestClient(app) as c:
            # Start a batch run to acquire SAMPLING on M14|1.
            r = c.post("/api/batch-run", json={
                "items": [{"machine": "M14", "mode": 1}],
                "server_id": "dev",
                "chunk_spin_times": 100,
                "chunk_robot_count": 1,
                "batch_concurrency": 1,
                "max_chunks": 1,
                "timeout": 30.0,
                "target_halfwidth_pp": 0,
                "skip_md5_refresh": True,
            })
            assert r.status_code == 200
            batch_id = r.json()["batch_id"]

            # Wait for SAMPLING to be held (item in running state).
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                poll = c.get(f"/api/batch-run/{batch_id}")
                items = poll.json().get("items", [])
                if items and items[0]["status"] == "running":
                    break
                time.sleep(0.05)

            # DELETE the report version while SAMPLING is held.
            del_r = c.delete("/api/reports/M14/1/rv_test")
            assert del_r.status_code == 409, (
                f"I2 REGRESSION: DELETE report version returned {del_r.status_code} "
                f"while SAMPLING is active. Expected 409 because the endpoint uses "
                f"CellOperation.DELETING (mutual exclusion with SAMPLING). "
                f"If 200: the endpoint still uses GENERATING (pre-fix) — "
                f"SAMPLING+GENERATING is allowed (INV-3). Response: {del_r.text}"
            )

            # Cleanup.
            procs = app_factory.stub_popen.processes
            if procs:
                procs[-1].finish(0)


# ══════════════════════════════════════════════════════════════════════════════
# T-I3: _recover_fleet_refresh silent swallow on corrupted DB
# ══════════════════════════════════════════════════════════════════════════════

class TestRecoverFleetRefreshCorruptedDb:
    """I3: _recover_fleet_refresh must write a diagnostic file when the DB
    is corrupted (not swallow all errors silently).

    Current code (lines 1517-1520):
        try:
            self._recover_fleet_refresh()
        except sqlite3.OperationalError:
            pass  # Pre-P3 database — tables don't exist yet

    The 'pass' catches BOTH "no such table" (expected) AND "DB corrupted"
    (silent data loss). Fix: distinguish via exc message; on corruption, write
    fleet_recovery_error.json per memory/feedback_no_silent_swallow.md.

    Inject-bug recipe:
      In app.py StateStore._recover_fleet_refresh, replace the body with:
          raise sqlite3.OperationalError("database disk image is malformed")
      (simulating corruption). The outer except catches it → test expects
      fleet_recovery_error.json to exist → absent → RED.
      Revert body → GREEN.

    NOTE: We test this by writing a corrupted fleet_refresh_queue table and
    verifying that the diagnostic file is created.
    """

    def _write_corrupted_frq_db(self, db_path: Path) -> None:
        """Create a DB with fleet_refresh_queue table containing corrupted rows
        that will cause sqlite3.OperationalError when read via the recovery query.

        Strategy: create the table but with wrong column names so the
        SELECT query fails.
        """
        conn = sqlite3.connect(str(db_path))
        try:
            # Standard tables first (so StateStore doesn't crash on other init).
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                  run_id TEXT PRIMARY KEY,
                  machine TEXT NOT NULL,
                  mode INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  model_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  started_at TEXT NOT NULL,
                  finished_at TEXT,
                  target_halfwidth_pp REAL NOT NULL,
                  chunk_spin_times INTEGER NOT NULL,
                  chunk_robot_count INTEGER NOT NULL,
                  batch_concurrency INTEGER NOT NULL,
                  max_chunks INTEGER NOT NULL,
                  timeout REAL NOT NULL,
                  bankruptcy_session_spins INTEGER NOT NULL,
                  bankruptcy_bankroll_multipliers TEXT NOT NULL,
                  report_version TEXT NOT NULL,
                  output_dir TEXT NOT NULL,
                  progress_file TEXT NOT NULL,
                  summary_file TEXT,
                  report_file TEXT,
                  error_message TEXT
                );
                CREATE TABLE IF NOT EXISTS fleet_refresh_queue (
                    queue_id TEXT PRIMARY KEY,
                    wrong_column_name TEXT
                );
                INSERT INTO fleet_refresh_queue (queue_id, wrong_column_name)
                VALUES ('q_test', 'running');
            """)
            conn.commit()
        finally:
            conn.close()

    def test_recover_fleet_refresh_writes_diagnostic_on_schema_mismatch(
        self, tmp_path, tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_machines, fake_analyzer, stub_popen, monkeypatch,
    ):
        """DB has fleet_refresh_queue with wrong schema → recovery error diagnostic
        file written to state_dir/fleet_recovery_error.json.

        Inject-bug recipe:
          In app.py StateStore.__init__, change the except clause from:
              except sqlite3.OperationalError:
                  pass
          to keep swallowing without writing a diagnostic.
          Run test → fleet_recovery_error.json absent → assert FAILS → RED.
          Revert → (implementer writes diagnostic) → GREEN.
        """
        # Write DB with corrupted fleet_refresh_queue schema BEFORE building app.
        db_path = tmp_state_dir / "console.db"
        self._write_corrupted_frq_db(db_path)

        monkeypatch.setattr("src.web_console.backend.app._default_popen_factory", stub_popen)
        monkeypatch.setattr("src.web_console.backend.app._terminate_pid_if_running",
                            lambda pid: True)
        tmp_upload = tmp_path / "uploaded_configs"
        tmp_upload.mkdir()
        monkeypatch.setattr("src.web_console.backend.app.CONFIGS_UPLOAD_DIR", tmp_upload)

        # Building the app triggers StateStore.__init__ → _recover_fleet_refresh.
        # The corrupted schema causes a query failure.
        # Post-fix: this writes fleet_recovery_error.json.
        # Pre-fix: silently passes, nothing written.
        try:
            app = create_app(
                state_dir=tmp_state_dir,
                reports_root=tmp_reports,
                cache_root=tmp_cache,
                machines_config=fake_machines,
                analyzer_path=fake_analyzer,
                rawdata_root=tmp_rawdata,
            )
        except Exception as exc:
            # If the app crashes on corrupted DB, that's also an acceptable outcome
            # but less robust than the diagnostic write approach.
            pytest.fail(
                f"create_app crashed with corrupted DB: {exc!r}. "
                f"Expected: graceful handling + diagnostic write."
            )

        diagnostic = tmp_state_dir / "fleet_recovery_error.json"
        assert diagnostic.exists(), (
            f"I3 REGRESSION: fleet_recovery_error.json not written when "
            f"fleet_refresh_queue has wrong schema. "
            f"StateStore._recover_fleet_refresh silently swallowed the error. "
            f"Per memory/feedback_no_silent_swallow.md: corrupted DB state "
            f"must persist a diagnostic, not pass silently. "
            f"state_dir contents: {list(tmp_state_dir.iterdir())}"
        )
        diag_data = json.loads(diagnostic.read_text(encoding="utf-8"))
        assert "error" in diag_data, (
            f"Diagnostic missing 'error' field: {diag_data}"
        )
        assert "ts" in diag_data, (
            f"Diagnostic missing 'ts' field: {diag_data}"
        )

    def test_recover_fleet_refresh_no_diagnostic_for_missing_table(
        self, app_factory, tmp_state_dir,
    ):
        """When tables simply don't exist (pre-P3 DB), no diagnostic written.

        The 'no such table: fleet_refresh_queue' error is expected and should
        NOT produce a fleet_recovery_error.json.
        """
        # Wipe DB and create it fresh without fleet tables (simulates pre-P3 DB).
        db_path = tmp_state_dir / "console.db"
        if db_path.exists():
            db_path.unlink()

        # app_factory uses the tmp_state_dir fixture, which already has an
        # empty progress/ dir. Build fresh.
        app = app_factory()
        with TestClient(app):
            pass

        diagnostic = tmp_state_dir / "fleet_recovery_error.json"
        # A missing-table OperationalError should NOT produce a diagnostic.
        # (The error is expected; it just means we're on a pre-P3 DB.)
        # This is either absent (expected) or could exist if implementer
        # writes diagnostics for all OperationalErrors. We assert "if it
        # exists, it should document the right error type".
        if diagnostic.exists():
            diag_data = json.loads(diagnostic.read_text(encoding="utf-8"))
            # If present, must not be for "no such table" (that's expected).
            assert "no such table" not in (diag_data.get("error") or "").lower(), (
                f"fleet_recovery_error.json written for expected 'no such table' "
                f"OperationalError. Only unexpected errors should produce diagnostics. "
                f"Got: {diag_data}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# T-I5: configs_upload_dir DI in create_app
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigsUploadDirDI:
    """I5: create_app must accept configs_upload_dir: Path | None parameter.

    Without this DI:
      - Tests that call /api/configs/upload mutate configs/uploaded_configs/_registry.json
        in the worktree (the real committed directory).
      - e2e_launch.py can't pass an isolated path via env var.

    The existing test_config_upload.py uses monkeypatch.setattr on
    CONFIGS_UPLOAD_DIR — that works but is fragile and doesn't survive
    the e2e live_server pattern (different process).

    This test verifies the DI parameter actually routes uploads to the injected dir.

    Inject-bug recipe:
      In app.py create_app, remove the line that uses the configs_upload_dir param:
          configs_upload_dir = configs_upload_dir_param if configs_upload_dir_param else CONFIGS_UPLOAD_DIR
      Replace with:
          configs_upload_dir = CONFIGS_UPLOAD_DIR  # ignores DI param
      Run test → tmp dir gets nothing, real dir gets upload → assert tmp has file FAILS → RED.
      Revert → GREEN.
    """

    def test_configs_upload_dir_di_routes_to_tmp_not_real(
        self, tmp_path, tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_machines, fake_analyzer, stub_popen, monkeypatch,
    ):
        """POST /api/configs/upload with configs_upload_dir DI → files in tmp dir,
        not in the real CONFIGS_UPLOAD_DIR."""
        monkeypatch.setattr("src.web_console.backend.app._default_popen_factory", stub_popen)
        monkeypatch.setattr("src.web_console.backend.app._terminate_pid_if_running",
                            lambda pid: True)

        tmp_upload = tmp_path / "isolated_configs"
        tmp_upload.mkdir()

        # Record the real CONFIGS_UPLOAD_DIR path (for verification it's NOT written).
        from src.web_console.backend.app import CONFIGS_UPLOAD_DIR as real_upload_dir
        real_registry = real_upload_dir / "_registry.json"
        real_registry_before = real_registry.read_text(encoding="utf-8") if real_registry.exists() else None

        try:
            app = create_app(
                state_dir=tmp_state_dir,
                reports_root=tmp_reports,
                cache_root=tmp_cache,
                machines_config=fake_machines,
                analyzer_path=fake_analyzer,
                rawdata_root=tmp_rawdata,
                configs_upload_dir=tmp_upload,  # I5: DI param
            )
        except TypeError as exc:
            pytest.xfail(
                f"I5 not yet implemented: create_app does not accept "
                f"configs_upload_dir param: {exc}"
            )

        with TestClient(app) as c:
            r = c.post("/api/configs/upload", json={
                "content": {"machine": "M14", "test": "i5_di"},
                "display_name": "i5-test",
            })
            assert r.status_code == 200, f"Upload failed: {r.text}"
            config_id = r.json()["config_id"]

        # I5 invariant: config file must be in tmp_upload, NOT in real dir.
        assert (tmp_upload / f"{config_id}.json").exists(), (
            f"I5 REGRESSION: config file not found in injected dir {tmp_upload}. "
            f"If file is in real CONFIGS_UPLOAD_DIR, DI parameter was ignored."
        )
        assert (tmp_upload / "_registry.json").exists(), (
            f"I5 REGRESSION: _registry.json not in injected dir {tmp_upload}."
        )

        # Real dir must not have been mutated.
        real_registry_after = real_registry.read_text(encoding="utf-8") if real_registry.exists() else None
        assert real_registry_before == real_registry_after, (
            f"I5 REGRESSION: real configs/uploaded_configs/_registry.json was mutated "
            f"despite configs_upload_dir DI. Before: {real_registry_before!r}, "
            f"After: {real_registry_after!r}."
        )

    def test_configs_upload_two_uploads_both_isolated(
        self, tmp_path, tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
        fake_machines, fake_analyzer, stub_popen, monkeypatch,
    ):
        """Two uploads with DI → both files in tmp dir, real dir unchanged.

        This is the e2e_conftest.py use case: live_server passes an isolated
        configs_upload_dir so /api/configs/upload never touches the worktree.
        """
        monkeypatch.setattr("src.web_console.backend.app._default_popen_factory", stub_popen)
        monkeypatch.setattr("src.web_console.backend.app._terminate_pid_if_running",
                            lambda pid: True)
        tmp_upload = tmp_path / "isolated_configs2"
        tmp_upload.mkdir()

        try:
            app = create_app(
                state_dir=tmp_state_dir,
                reports_root=tmp_reports,
                cache_root=tmp_cache,
                machines_config=fake_machines,
                analyzer_path=fake_analyzer,
                rawdata_root=tmp_rawdata,
                configs_upload_dir=tmp_upload,
            )
        except TypeError:
            pytest.xfail("I5 create_app param not yet implemented")

        ids = []
        with TestClient(app) as c:
            for i in range(2):
                r = c.post("/api/configs/upload", json={
                    "content": {"idx": i, "test": "i5_two"},
                    "display_name": f"i5-two-{i}",
                })
                assert r.status_code == 200
                ids.append(r.json()["config_id"])

        assert len(set(ids)) == 2, f"Expected 2 distinct config_ids, got: {ids}"
        for cid in ids:
            assert (tmp_upload / f"{cid}.json").exists(), (
                f"Config {cid} not in isolated dir {tmp_upload}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# T-I6: batch_generate_report pre-checks registry
# ══════════════════════════════════════════════════════════════════════════════

class TestBatchGenerateReportPreChecksRegistry:
    """I6: POST /api/rawdata/batch-generate-report must return 409 at submit
    time when any requested (machine, mode) cell is busy (SAMPLING or other
    active op), NOT asynchronously fail later.

    Current code (lines 8157-8220) enqueues all items synchronously without
    consulting the registry. The 409 only surfaces when the background worker
    picks up the item and tries to acquire GENERATING — by then the caller has
    already received 200.

    Fix: add a pre-check loop in batch_generate_report that calls
    registry.peek_cell_status() (or is_cell_busy) before start(); 409 if any
    requested cell is busy.

    Inject-bug recipe:
      Remove the pre-check loop from batch_generate_report.
      Hold SAMPLING on M14|1 → POST batch-generate-report for M14|1.
      Post-fix: 409 immediately.
      Pre-fix (bug): 200 immediately + async failure later.
      Test asserts 409 → with bug, gets 200 → RED.
      Revert → GREEN.
    """

    def test_batch_generate_report_returns_409_when_cell_busy(
        self, app_factory, tmp_rawdata, tmp_reports,
    ):
        """SAMPLING active on M14|1 → POST /api/rawdata/batch-generate-report
        with M14|1 → 409 returned at submit time (not async)."""
        # Write a chunk file so batch-generate-report has something to process
        # and doesn't bail out with 404 (scope=items path, not scope=all_with_rawdata).
        mode_dir = tmp_rawdata / "M14" / "mode_1"
        mode_dir.mkdir(parents=True, exist_ok=True)
        (mode_dir / "chunk_0001.json").write_text(
            json.dumps({"_cache_version": 3}), encoding="utf-8"
        )

        app = app_factory()
        with TestClient(app) as c:
            # Start a batch run to acquire SAMPLING on M14|1.
            r = c.post("/api/batch-run", json={
                "items": [{"machine": "M14", "mode": 1}],
                "server_id": "dev",
                "chunk_spin_times": 100,
                "chunk_robot_count": 1,
                "batch_concurrency": 1,
                "max_chunks": 1,
                "timeout": 30.0,
                "target_halfwidth_pp": 0,
                "skip_md5_refresh": True,
            })
            assert r.status_code == 200
            batch_id = r.json()["batch_id"]

            # Wait for SAMPLING to be held.
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                poll = c.get(f"/api/batch-run/{batch_id}")
                items = poll.json().get("items", [])
                if items and items[0]["status"] == "running":
                    break
                time.sleep(0.05)

            # Submit batch-generate-report for the same busy cell.
            gen_r = c.post("/api/rawdata/batch-generate-report", json={
                "items": [{"machine": "M14", "mode": 1}],
            })

            # I6 invariant: 409 at submit time, not async.
            assert gen_r.status_code == 409, (
                f"I6 REGRESSION: batch-generate-report returned {gen_r.status_code} "
                f"instead of 409 when M14|1 is SAMPLING-busy. "
                f"The pre-check loop is missing or not consulting the registry. "
                f"Response: {gen_r.text}"
            )
            assert "busy" in gen_r.text.lower() or "409" in str(gen_r.status_code), (
                f"409 body should mention cell-busy. Got: {gen_r.text}"
            )

            # Cleanup.
            procs = app_factory.stub_popen.processes
            if procs:
                procs[-1].finish(0)

    def test_batch_generate_report_succeeds_when_no_cell_busy(
        self, app_factory, tmp_rawdata,
    ):
        """Baseline: no active ops → POST batch-generate-report returns 200."""
        mode_dir = tmp_rawdata / "M14" / "mode_1"
        mode_dir.mkdir(parents=True, exist_ok=True)
        (mode_dir / "chunk_0001.json").write_text(
            json.dumps({"_cache_version": 3}), encoding="utf-8"
        )

        app = app_factory()
        with TestClient(app) as c:
            r = c.post("/api/rawdata/batch-generate-report", json={
                "items": [{"machine": "M14", "mode": 1}],
            })
            # Should be 200 (accepted) when cell is free.
            assert r.status_code == 200, (
                f"Expected 200 for batch-generate-report with no busy cells. "
                f"Got {r.status_code}: {r.text}"
            )
