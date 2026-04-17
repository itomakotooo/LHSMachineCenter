"""Tests for transactional report import (P0.3 session 2026-04).

POST /api/reports/import uses a 4-step commit per version:
  1. read source summary
  2. insert DB row with status="importing"
  3. copytree → dst
  4. flip DB status → "completed"

Any step's failure rolls back the earlier ones (delete row, rmtree dst),
so partial state can't persist. This addresses the original "166/1002
silent import fails" incident.

Covers:
- Happy path: row created as "completed", dst has summary file
- read_summary fail: no row, no dst
- insert_run fail: no row, no dst
- copytree fail: row rolled back, dst rolled back
- update_status fail: row rolled back, dst rolled back
- Mixed: one success + one failure in same call — both sides isolated
- Skipped (dst already exists): neither imported nor rolled back
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def _write_version_summary(
    versions_dir: Path, version_name: str, summary: dict[str, Any] | None = None
) -> Path:
    """Create `<versions_dir>/<version_name>/player_impact_summary.json`."""
    v = versions_dir / version_name
    v.mkdir(parents=True, exist_ok=True)
    if summary is None:
        summary = {
            "sampling": {
                "started_at": "2026-04-17T00:00:00Z",
                "finished_at": "2026-04-17T00:01:00Z",
                "target_halfwidth_pp": 0.5,
                "achieved_halfwidth_pp": 8.77,
                "chunks": 1,
                "chunk_spin_times": 5000,
                "chunk_robot_count": 20,
                "batch_concurrency": 2,
            },
            "rtp": {"point_pct": 91.9, "ci95_interval_pct": [83.1, 100.7]},
            "guideline_assessment": {"quality_label": "EXPLORATORY"},
        }
    (v / "player_impact_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8"
    )
    (v / "player_impact_report.md").write_text("# stub\n", encoding="utf-8")
    return v


def _build_source_tree(root: Path, layout: dict[str, list[str]]) -> Path:
    """layout: {"M14": ["mode_1/rv_A", ...]}.

    Writes a valid summary under each version dir so the import passes
    the source-read step unless the caller overrides one explicitly.
    """
    src = root / "source"
    src.mkdir()
    for machine, versions in layout.items():
        for path in versions:
            mode_and_version = path.split("/")
            mode_dir = mode_and_version[0]
            version_name = mode_and_version[1]
            versions_dir = src / machine / mode_dir / "versions"
            _write_version_summary(versions_dir, version_name)
    return src


def _query_run(db_path: Path, run_id: str) -> dict[str, Any] | None:
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        return dict(row) if row else None


def _all_run_rows(db_path: Path) -> list[dict[str, Any]]:
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM runs").fetchall()]


class TestImportHappyPath:
    def test_single_version_commits_db_and_files(
        self, client, tmp_path: Path, app_factory
    ):
        c, _ = client
        src = _build_source_tree(tmp_path, {"M14": ["mode_1/rv_20260417T000000Z_abcdef123456"]})
        r = c.post(
            "/api/reports/import",
            json={"source_path": str(src), "mode": "merge"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["imported"] == 1
        assert body["failed"] == 0
        assert body["failures"] == []
        assert body["machines_affected"] == ["M14"]
        # DB row exists and is "completed", not stuck at "importing".
        rows = _all_run_rows(app_factory.db_path)
        assert len(rows) == 1
        assert rows[0]["status"] == "completed"
        assert rows[0]["machine"] == "M14"
        assert rows[0]["mode"] == 1
        assert abs(rows[0]["achieved_rtp_pct"] - 91.9) < 1e-6
        # Dst files copied.
        dst = (
            app_factory.reports_dir
            / "M14" / "mode_1" / "versions" / "rv_20260417T000000Z_abcdef123456"
        )
        assert (dst / "player_impact_summary.json").exists()


class TestImportRollback:
    def test_read_summary_failure_leaves_no_row_and_no_dst(
        self, client, tmp_path: Path, app_factory
    ):
        c, _ = client
        src = _build_source_tree(tmp_path, {"M14": ["mode_1/rv_bad_001"]})
        # Corrupt the source summary so step 1 fails.
        (src / "M14" / "mode_1" / "versions" / "rv_bad_001" / "player_impact_summary.json")\
            .write_text("{not valid json", encoding="utf-8")

        r = c.post("/api/reports/import", json={"source_path": str(src), "mode": "merge"})
        body = r.json()
        assert body["imported"] == 0
        assert body["failed"] == 1
        assert body["failures"][0]["stage"] == "read_summary"
        # No DB row, no dst dir.
        assert _all_run_rows(app_factory.db_path) == []
        assert not (app_factory.reports_dir / "M14" / "mode_1" / "versions" / "rv_bad_001").exists()

    def test_insert_run_failure_leaves_no_dst(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        c, app = client
        src = _build_source_tree(tmp_path, {"M14": ["mode_1/rv_abc_001"]})
        # Force store.insert_run to raise.
        store = app.state.store  # type: ignore[attr-defined]
        original_insert = store.insert_run
        calls = {"n": 0}

        def boom(row):
            calls["n"] += 1
            raise RuntimeError("simulated DB insert failure")

        monkeypatch.setattr(store, "insert_run", boom)
        r = c.post("/api/reports/import", json={"source_path": str(src), "mode": "merge"})
        body = r.json()
        assert body["imported"] == 0
        assert body["failed"] == 1
        assert body["failures"][0]["stage"] == "insert_run"
        assert calls["n"] == 1
        # No dst was even attempted since insert happens before copytree.
        assert not (app_factory.reports_dir / "M14" / "mode_1" / "versions" / "rv_abc_001").exists()

        # Restore for any teardown hooks.
        monkeypatch.setattr(store, "insert_run", original_insert)

    def test_copytree_failure_rolls_back_both(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        c, _ = client
        src = _build_source_tree(tmp_path, {"M14": ["mode_1/rv_copy_fail"]})
        import src.web_console.backend.app as app_mod

        def boom_copy(*args, **kwargs):
            raise OSError("simulated copy failure")

        monkeypatch.setattr(app_mod.shutil, "copytree", boom_copy)
        r = c.post("/api/reports/import", json={"source_path": str(src), "mode": "merge"})
        body = r.json()
        assert body["imported"] == 0
        assert body["failed"] == 1
        assert body["failures"][0]["stage"] == "copytree"
        # DB row rolled back.
        assert _all_run_rows(app_factory.db_path) == []
        # Dst doesn't exist (wasn't created in the first place).
        assert not (app_factory.reports_dir / "M14" / "mode_1" / "versions" / "rv_copy_fail").exists()

    def test_update_status_failure_rolls_back_both(
        self, client, tmp_path: Path, app_factory, monkeypatch
    ):
        c, app = client
        src = _build_source_tree(tmp_path, {"M14": ["mode_1/rv_update_fail_001"]})
        store = app.state.store  # type: ignore[attr-defined]

        def boom_update(run_id, patch):
            raise RuntimeError("simulated update failure")

        monkeypatch.setattr(store, "update_run", boom_update)
        r = c.post("/api/reports/import", json={"source_path": str(src), "mode": "merge"})
        body = r.json()
        assert body["imported"] == 0
        assert body["failed"] == 1
        assert body["failures"][0]["stage"] == "update_status"
        # Rollback: both DB row and dst must be gone, not left at "importing".
        assert _all_run_rows(app_factory.db_path) == []
        assert not (
            app_factory.reports_dir / "M14" / "mode_1" / "versions" / "rv_update_fail_001"
        ).exists()


class TestImportMixed:
    def test_one_success_one_failure_isolated(
        self, client, tmp_path: Path, app_factory
    ):
        c, _ = client
        src = _build_source_tree(
            tmp_path,
            {"M14": ["mode_1/rv_good_001aaaa", "mode_1/rv_bad_002bbbb"]},
        )
        # Corrupt the second one's summary.
        (src / "M14" / "mode_1" / "versions" / "rv_bad_002bbbb" / "player_impact_summary.json")\
            .write_text("not json", encoding="utf-8")
        r = c.post("/api/reports/import", json={"source_path": str(src), "mode": "merge"})
        body = r.json()
        assert body["imported"] == 1
        assert body["failed"] == 1
        assert body["failures"][0]["stage"] == "read_summary"
        assert body["failures"][0]["version"] == "rv_bad_002bbbb"
        # Exactly one DB row, for the good version.
        rows = _all_run_rows(app_factory.db_path)
        assert len(rows) == 1
        assert rows[0]["report_version"] == "rv_good_001aaaa"
        assert rows[0]["status"] == "completed"


class TestImportSkipped:
    def test_preexisting_dst_is_skipped_without_touching_db(
        self, client, tmp_path: Path, app_factory
    ):
        c, _ = client
        src = _build_source_tree(tmp_path, {"M14": ["mode_1/rv_already_here"]})
        # Pre-create the dst so the import loop hits the "skipped" branch.
        dst = (
            app_factory.reports_dir
            / "M14" / "mode_1" / "versions" / "rv_already_here"
        )
        dst.mkdir(parents=True)
        (dst / "player_impact_summary.json").write_text("{}", encoding="utf-8")

        r = c.post("/api/reports/import", json={"source_path": str(src), "mode": "merge"})
        body = r.json()
        assert body["imported"] == 0
        assert body["skipped"] == 1
        assert body["failed"] == 0
        # No DB row created — skip doesn't insert.
        assert _all_run_rows(app_factory.db_path) == []
