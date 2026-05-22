"""P3-T4: Report stale tagging tests.

Covers 6 tests from session_artifacts/_impl/p3/brief.md §6 P3-T4:
  test_delete_rawdata_tags_reports_stale
  test_delete_rawdata_marks_runs_in_db
  test_per_version_delete_only_tags_when_empties_mode
  test_all_data_delete_does_not_tag
  test_stale_tag_failure_persists_diagnostic
  test_tag_reports_stale_raises_on_failure

Design source: 04_deploy_architecture_proposal_v2.md §4.6 (report stale tagging)
D9: _tag_reports_stale helper + call sites in delete_machine_rawdata + per-version endpoint.
D10: underlying_removed column in runs table.

Memory feedback files honored:
  memory/feedback_enumerate_safety_paths.md — inject-bug recipe for each delete path.
  memory/feedback_no_silent_swallow.md — tagging failure persists diagnostic to
    stale_tag_error.json; test verifies that file is written.
  memory/feedback_md5_is_a_tag_not_a_destruction_signal.md — _tag_reports_stale
    tags reports, does NOT delete them. INV-7 v2 carve-out: all-data delete DOES
    delete reports (reports don't survive to need tagging).

Inject-bug recipes (for future devs to reproduce):

  D9a (test_delete_rawdata_tags_reports_stale):
    In app.py delete_machine_rawdata, comment out the _tag_reports_stale call:
        # for _stale_mode in modes_to_lock:
        #     try:
        #         _tag_reports_stale(machine, _stale_mode, rr, store, sd)
        #     except Exception:
        #         pass
    Run test → FAILS: index.json entries still have underlying_removed=False/None.
    Revert → PASSES.

  D9b (test_delete_rawdata_marks_runs_in_db):
    In app.py StateStore.mark_runs_underlying_removed, change the UPDATE to a no-op:
        def mark_runs_underlying_removed(self, machine, mode): return 0
    Run test → FAILS: runs.underlying_removed stays 0. Revert → PASSES.

  D9c (test_stale_tag_failure_persists_diagnostic):
    In app.py _tag_reports_stale, remove the diagnostic persistence block:
        # try:
        #     atomic_json_write(diag_path, diag)
        # except Exception:
        #     pass
    Run test → FAILS: stale_tag_error.json not written. Revert → PASSES.

  D9d (test_tag_reports_stale_raises_on_failure):
    In app.py _tag_reports_stale, replace the `raise` at the end of the except block
    with `pass` (swallow the exception):
        except Exception as exc:
            # persist diag...
            pass  # BUG: exception swallowed
    Run test → FAILS: helper returns normally even on failure; caller can't detect it.
    Revert → PASSES.

  D10 (test_delete_rawdata_marks_runs_in_db):
    In app.py StateStore._init_db, remove the:
        if "underlying_removed" not in run_columns:
            conn.execute("ALTER TABLE runs ADD COLUMN underlying_removed ...")
    line. On an existing DB, the column won't be added → UPDATE in
    mark_runs_underlying_removed raises OperationalError → test FAILS.
    Revert → PASSES (forward-only migration adds the column once).

Cross-refs:
  session_artifacts/_impl/p3/brief.md §6 P3-T4
  session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md §4.6
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web_console.backend.app import (
    StateStore,
    _tag_reports_stale,
    create_app,
)
from src.web_console.backend.config_writer import atomic_json_read_modify_write


# ---------------------------------------------------------------------------
# Helpers: seed reports/index.json + runs rows
# ---------------------------------------------------------------------------


def _seed_report_index(reports_root: Path, machine: str, mode: int,
                        n_entries: int = 2) -> Path:
    """Create a minimal reports/<machine>/mode_<n>/index.json with N entries."""
    index_dir = reports_root / machine / f"mode_{mode}"
    index_dir.mkdir(parents=True, exist_ok=True)
    entries = [
        {
            "run_id": f"run-{i:03d}",
            "version_dir": f"rv_20260101T{i:06d}Z_abc{i:03d}",
            "rtp_pct": 94.0 + i * 0.1,
            "underlying_removed": False,
        }
        for i in range(n_entries)
    ]
    index_path = index_dir / "index.json"
    index_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return index_path


def _seed_run_rows(store: StateStore, machine: str, mode: int, n: int = 2) -> list[str]:
    """Insert N run rows for (machine, mode) in the runs table.

    Uses the minimal column set required by the CREATE TABLE schema in app.py.
    NOT_NULL columns: run_id, machine, mode, status, model_id, created_at,
    started_at, target_halfwidth_pp, chunk_spin_times, chunk_robot_count,
    batch_concurrency, max_chunks, timeout, bankruptcy_session_spins,
    bankruptcy_bankroll_multipliers, report_version, output_dir, progress_file.
    """
    run_ids = []
    for i in range(n):
        run_id = f"run-{machine}-m{mode}-{i:03d}"
        store.insert_run({
            "run_id": run_id,
            "machine": machine,
            "mode": mode,
            "status": "completed",
            "model_id": "test-model",
            "created_at": f"2026-01-01T00:{i:02d}:00Z",
            "started_at": f"2026-01-01T00:{i:02d}:00Z",
            "finished_at": f"2026-01-01T00:{i:02d}:30Z",
            "chunk_spin_times": 1000,
            "chunk_robot_count": 8,
            "batch_concurrency": 8,
            "max_chunks": 10,
            "timeout": 300.0,
            "target_halfwidth_pp": 0.5,
            "bankruptcy_session_spins": 0,
            "bankruptcy_bankroll_multipliers": "[]",
            "report_version": "v1",
            "output_dir": "",
            "progress_file": "",
        })
        run_ids.append(run_id)
    return run_ids


# ---------------------------------------------------------------------------
# Isolated app fixture (matching conftest pattern)
# ---------------------------------------------------------------------------


@pytest.fixture
def tag_app(tmp_path, tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
             fake_machines, fake_analyzer, stub_popen, monkeypatch):
    """Isolated app with tmp dirs for stale-tag tests."""
    monkeypatch.setattr("src.web_console.backend.app._default_popen_factory", stub_popen)
    monkeypatch.setattr("src.web_console.backend.app._terminate_pid_if_running",
                        lambda pid: True)
    monkeypatch.setattr("src.web_console.backend.app.CONFIGS_UPLOAD_DIR",
                        tmp_path / "uploaded_configs")
    (tmp_path / "uploaded_configs").mkdir()

    app = create_app(
        state_dir=tmp_state_dir,
        reports_root=tmp_reports,
        cache_root=tmp_cache,
        machines_config=fake_machines,
        analyzer_path=fake_analyzer,
        rawdata_root=tmp_rawdata,
    )
    return app


@pytest.fixture
def tag_client(tag_app):
    with TestClient(tag_app) as c:
        yield c, tag_app


# ---------------------------------------------------------------------------
# P3-T4: _tag_reports_stale unit tests (direct function call)
# ---------------------------------------------------------------------------


class TestTagReportsStaleHelper:
    """Direct tests of the _tag_reports_stale helper function."""

    def test_tag_reports_stale_sets_flag_on_all_entries(self, tmp_path: Path):
        """_tag_reports_stale sets underlying_removed=True on every entry.

        Inject-bug: in _tag_reports_stale, remove the `entry['underlying_removed'] = True`
        line → entries stay unmodified → test fails.  Revert → passes.
        """
        db_path = tmp_path / "tag_test.db"
        state_dir = tmp_path / "state" / "console"
        state_dir.mkdir(parents=True)
        reports_root = tmp_path / "reports"

        store = StateStore(db_path)
        machine, mode = "M14", 1
        index_path = _seed_report_index(reports_root, machine, mode, n_entries=3)

        _tag_reports_stale(machine, mode, reports_root, store, state_dir)

        entries = json.loads(index_path.read_text(encoding="utf-8"))
        for i, entry in enumerate(entries):
            assert entry.get("underlying_removed") is True, (
                f"Entry {i} not tagged: {entry}. "
                "Inject-bug: remove entry['underlying_removed']=True from _tag_reports_stale."
            )

    def test_tag_reports_stale_raises_on_failure(self, tmp_path: Path, monkeypatch):
        """_tag_reports_stale raises the underlying exception when tagging fails.
        Does NOT swallow — caller can detect and decide what to do.

        Inject-bug: in _tag_reports_stale, replace `raise` with `pass` →
        exception swallowed → function returns normally on failure → caller
        cannot detect tagging failure → test fails (no exception raised).
        Revert → passes.
        """
        db_path = tmp_path / "tag_raise_test.db"
        state_dir = tmp_path / "state" / "console"
        state_dir.mkdir(parents=True)
        reports_root = tmp_path / "reports"

        store = StateStore(db_path)
        machine, mode = "M14", 1
        _seed_report_index(reports_root, machine, mode)

        # Monkeypatch atomic_json_read_modify_write to raise an exception
        original_fn = atomic_json_read_modify_write

        def exploding_rw(path, fn, **kwargs):
            raise RuntimeError("INJECTED: atomic write failed")

        monkeypatch.setattr(
            "src.web_console.backend.app.atomic_json_read_modify_write",
            exploding_rw,
        )

        with pytest.raises(RuntimeError, match="INJECTED"):
            _tag_reports_stale(machine, mode, reports_root, store, state_dir)

    def test_stale_tag_failure_persists_diagnostic(self, tmp_path: Path, monkeypatch):
        """On tagging failure, _tag_reports_stale writes stale_tag_error.json.

        Per memory/feedback_no_silent_swallow.md: diagnostic must be persisted
        before re-raising.

        Inject-bug: in _tag_reports_stale, remove the diagnostic persistence block
        (the try: atomic_json_write(diag_path, diag) except: pass block) →
        stale_tag_error.json is not written → test fails. Revert → passes.
        """
        db_path = tmp_path / "diag_test.db"
        state_dir = tmp_path / "state" / "console"
        state_dir.mkdir(parents=True)
        reports_root = tmp_path / "reports"

        store = StateStore(db_path)
        machine, mode = "M14", 1
        _seed_report_index(reports_root, machine, mode)

        # Make atomic_json_read_modify_write raise so the except block is triggered
        monkeypatch.setattr(
            "src.web_console.backend.app.atomic_json_read_modify_write",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )

        with pytest.raises(OSError):
            _tag_reports_stale(machine, mode, reports_root, store, state_dir)

        # Diagnostic file must have been written
        diag_path = state_dir / "stale_tag_error.json"
        assert diag_path.exists(), (
            f"stale_tag_error.json was not written to {diag_path}. "
            "Inject-bug: remove the diagnostic persistence block from _tag_reports_stale."
        )
        diag = json.loads(diag_path.read_text(encoding="utf-8"))
        assert diag.get("machine") == machine
        assert diag.get("mode") == mode
        assert "error" in diag

    def test_tag_reports_stale_no_op_when_index_missing(self, tmp_path: Path):
        """_tag_reports_stale does not crash when index.json doesn't exist yet."""
        db_path = tmp_path / "no_index.db"
        state_dir = tmp_path / "state" / "console"
        state_dir.mkdir(parents=True)
        reports_root = tmp_path / "reports"

        store = StateStore(db_path)
        # No index.json seeded — helper must succeed silently
        _tag_reports_stale("M99", 1, reports_root, store, state_dir)

    def test_mark_runs_underlying_removed_updates_db(self, tmp_path: Path):
        """StateStore.mark_runs_underlying_removed sets underlying_removed=1.

        D10 test: underlying_removed column added by migration must be writable.

        Inject-bug: in StateStore._init_db, remove the ALTER TABLE runs ADD COLUMN
        underlying_removed migration → column absent → UPDATE raises OperationalError
        → test FAILS.  Revert → PASSES.
        """
        db_path = tmp_path / "underlying_removed_test.db"
        state_dir = tmp_path / "state" / "console"
        state_dir.mkdir(parents=True)

        store = StateStore(db_path)
        machine, mode = "M14", 1
        run_ids = _seed_run_rows(store, machine, mode, n=3)

        # Also seed a run for different machine (should NOT be updated)
        other_run_id = "run-other-machine"
        store.insert_run({
            "run_id": other_run_id,
            "machine": "M99",
            "mode": 1,
            "status": "completed",
            "model_id": "test-model",
            "created_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:30Z",
            "chunk_spin_times": 1000,
            "chunk_robot_count": 8,
            "batch_concurrency": 8,
            "max_chunks": 10,
            "timeout": 300.0,
            "target_halfwidth_pp": 0.5,
            "bankruptcy_session_spins": 0,
            "bankruptcy_bankroll_multipliers": "[]",
            "report_version": "v1",
            "output_dir": "",
            "progress_file": "",
        })

        rows_updated = store.mark_runs_underlying_removed(machine, mode)
        assert rows_updated == 3, (
            f"Expected 3 rows updated, got {rows_updated}. "
            "Inject-bug: make mark_runs_underlying_removed a no-op → rows_updated=0 → fail."
        )

        # Verify in DB
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT run_id, underlying_removed FROM runs WHERE machine=? AND mode=?",
                (machine, mode),
            ).fetchall()
            other_row = conn.execute(
                "SELECT underlying_removed FROM runs WHERE run_id=?",
                (other_run_id,),
            ).fetchone()

        for row in rows:
            assert row["underlying_removed"] == 1, (
                f"run {row['run_id']} underlying_removed should be 1, "
                f"got {row['underlying_removed']}"
            )
        # Other machine's run must not be tagged
        assert other_row["underlying_removed"] == 0, (
            "mark_runs_underlying_removed must only update the specified (machine, mode)"
        )


# ---------------------------------------------------------------------------
# P3-T4: HTTP-level stale-tag tests (via TestClient)
# ---------------------------------------------------------------------------


class TestDeleteRawdataStaleTagging:
    """HTTP-level tests for _tag_reports_stale integration in delete endpoints."""

    def _make_rawdata_dir(self, rawdata_root: Path, machine: str, mode: int) -> Path:
        """Create a mode dir with a minimal chunk so delete finds something."""
        mode_dir = rawdata_root / machine / f"mode_{mode}"
        mode_dir.mkdir(parents=True, exist_ok=True)
        chunk = mode_dir / "chunk_0001.json"
        chunk.write_text(
            json.dumps({
                "_config_md5": "cfg1",
                "_code_md5": "code1",
                "_spin_times": 1000,
                "_robot_count": 8,
                "rounds": [],
            }),
            encoding="utf-8",
        )
        return mode_dir

    def test_delete_rawdata_tags_reports_stale(self, tag_client, app_factory):
        """DELETE /api/rawdata/{m}?mode=1 → all entries in index.json get underlying_removed=True.

        Inject-bug: comment out the _tag_reports_stale call in delete_machine_rawdata →
        index.json entries stay unmodified → test fails. Revert → passes.
        """
        c, app = tag_client
        machine, mode = "M14", 1

        # Seed rawdata dir
        self._make_rawdata_dir(app_factory.rawdata_dir, machine, mode)

        # Seed report index
        index_path = _seed_report_index(app_factory.reports_dir, machine, mode, n_entries=2)

        # Delete rawdata (force=True to ensure actual deletion even with retention)
        resp = c.delete(f"/api/rawdata/{machine}", params={"mode": mode, "force": True})
        assert resp.status_code == 200, f"DELETE failed: {resp.text}"

        # Verify all entries tagged
        entries = json.loads(index_path.read_text(encoding="utf-8"))
        for i, entry in enumerate(entries):
            assert entry.get("underlying_removed") is True, (
                f"Entry {i} not tagged as stale after delete: {entry}. "
                "Inject-bug: comment out _tag_reports_stale in delete_machine_rawdata."
            )

    def test_delete_rawdata_marks_runs_in_db(self, tag_client, app_factory):
        """DELETE /api/rawdata/{m}?mode=1 → runs.underlying_removed=1 for matching rows.

        D10 inject-bug: change mark_runs_underlying_removed to no-op → runs rows
        stay at underlying_removed=0 → test FAILS. Revert → PASSES.
        """
        c, app = tag_client
        machine, mode = "M14", 1

        # Seed rawdata and report structures
        self._make_rawdata_dir(app_factory.rawdata_dir, machine, mode)
        _seed_report_index(app_factory.reports_dir, machine, mode)

        # Seed runs in DB
        store: StateStore = app.state.store
        run_ids = _seed_run_rows(store, machine, mode, n=2)

        # Delete rawdata
        resp = c.delete(f"/api/rawdata/{machine}", params={"mode": mode, "force": True})
        assert resp.status_code == 200, f"DELETE failed: {resp.text}"

        # Verify runs flagged
        db_path = app_factory.db_path
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT run_id, underlying_removed FROM runs "
                "WHERE machine=? AND mode=?",
                (machine, mode),
            ).fetchall()

        assert len(rows) == 2, f"Expected 2 run rows, got {len(rows)}"
        for row in rows:
            assert row["underlying_removed"] == 1, (
                f"run {row['run_id']} underlying_removed should be 1 "
                f"after rawdata delete, got {row['underlying_removed']}. "
                "D10 inject-bug: make mark_runs_underlying_removed a no-op."
            )

    def test_per_version_delete_only_tags_when_empties_mode(
        self, tag_client, app_factory
    ):
        """Per-version delete only tags reports stale when the mode is fully emptied.

        N>1 versions: delete one → not tagged (others remain).
        Delete last → tagged (mode now empty).

        Per brief D9: 'only when delete empties the mode (last chunk removed)'.
        """
        c, app = tag_client
        machine, mode = "M14", 1

        mode_dir = app_factory.rawdata_dir / machine / f"mode_{mode}"
        mode_dir.mkdir(parents=True, exist_ok=True)

        # Create 2 chunks with different (config_md5, code_md5)
        chunk1 = mode_dir / "chunk_0001.json"
        chunk1.write_text(json.dumps({
            "_config_md5": "cfg1", "_code_md5": "code1",
            "_spin_times": 1000, "_robot_count": 8, "rounds": [],
        }), encoding="utf-8")

        chunk2 = mode_dir / "chunk_0002.json"
        chunk2.write_text(json.dumps({
            "_config_md5": "cfg2", "_code_md5": "code2",
            "_spin_times": 1000, "_robot_count": 8, "rounds": [],
        }), encoding="utf-8")

        index_path = _seed_report_index(app_factory.reports_dir, machine, mode, n_entries=2)

        from src.web_console.backend.cell_lock_registry import CellLockRegistry
        registry: CellLockRegistry = app.state.registry

        # Delete only chunk1 (mode is NOT empty after this)
        resp1 = c.request(
            "DELETE",
            f"/api/rawdata/{machine}/mode/{mode}/version",
            json={"config_md5": "cfg1", "code_md5": "code1"},
        )
        assert resp1.status_code == 200, f"First per-version delete failed: {resp1.text}"

        # Index.json must NOT be tagged yet (chunk2 still exists)
        entries1 = json.loads(index_path.read_text(encoding="utf-8"))
        for entry in entries1:
            assert entry.get("underlying_removed") in (None, False), (
                f"Index should NOT be tagged yet (mode not empty): {entry}"
            )

        # Delete chunk2 (now mode IS empty)
        resp2 = c.request(
            "DELETE",
            f"/api/rawdata/{machine}/mode/{mode}/version",
            json={"config_md5": "cfg2", "code_md5": "code2"},
        )
        assert resp2.status_code == 200, f"Second per-version delete failed: {resp2.text}"

        # Index.json MUST be tagged now
        entries2 = json.loads(index_path.read_text(encoding="utf-8"))
        for i, entry in enumerate(entries2):
            assert entry.get("underlying_removed") is True, (
                f"Entry {i} should be tagged after last chunk removed: {entry}"
            )

    def test_all_data_delete_does_not_tag(self, tag_client, app_factory):
        """DELETE /api/machines/{m}/all-data → reports are DELETED (not tagged).

        INV-7 v2 carve-out: all-data delete is EXEMPT from tagging because
        it deletes both rawdata + reports entirely. Reports don't survive to tag.

        Inject-bug: add _tag_reports_stale call to delete_machine_all_data →
        reports would be tagged instead of deleted → test fails
        (report dir still exists after delete). Revert → passes.
        """
        c, app = tag_client
        machine, mode = "M14", 1

        # Seed rawdata
        self._make_rawdata_dir(app_factory.rawdata_dir, machine, mode)

        # Seed reports
        reports_machine_dir = app_factory.reports_dir / machine
        mode_dir = reports_machine_dir / f"mode_{mode}"
        mode_dir.mkdir(parents=True, exist_ok=True)
        index_path = mode_dir / "index.json"
        index_path.write_text(json.dumps([
            {"run_id": "r1", "underlying_removed": False}
        ]), encoding="utf-8")

        # DELETE all data
        resp = c.delete(f"/api/machines/{machine}/all-data")
        assert resp.status_code == 200, f"all-data delete failed: {resp.text}"

        # Reports directory must be GONE (rmtree), not tagged
        assert not reports_machine_dir.exists(), (
            f"reports/{machine} still exists after all-data delete — "
            "expected rmtree to have removed it. INV-7 v2: all-data delete removes reports."
        )
