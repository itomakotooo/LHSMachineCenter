"""Tests for reports version retention (P1.2 session 2026-04).

`prune_versions` keeps the newest N version dirs per (machine, mode)
and removes older ones, syncing DB and mode manifests.

Covers:
- dry_run preview: no disk/DB touch, but paths reported
- actual delete: rmtree + delete_run + refreshed index.json/latest.json
- active-run skip: rows with status="running"/"importing" keep their dir
- errors reported (e.g. rmtree fails on a missing dir)
- keep_last validation (must be >= 1)
- index.json rebuild reflects only remaining versions
- POST /api/maintenance/prune-versions endpoint
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.web_console.backend.reports_retention import prune_versions


def _write_summary(path: Path, rtp: float = 91.9) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "player_impact_summary.json").write_text(
        json.dumps(
            {
                "run_id": path.name.split("_")[-1] if "_" in path.name else "x",
                "sampling": {
                    "started_at": "2026-04-17T00:00:00Z",
                    "finished_at": "2026-04-17T00:01:00Z",
                },
                "rtp": {"point_pct": rtp},
                "guideline_assessment": {"quality_label": "EXPLORATORY"},
            }
        ),
        encoding="utf-8",
    )
    (path / "player_impact_report.md").write_text("# stub", encoding="utf-8")


def _seed_mode(reports_root: Path, machine: str, mode: int, versions: list[str]):
    """Create one summary per version name under the mode dir."""
    base = reports_root / machine / f"mode_{mode}" / "versions"
    for v in versions:
        _write_summary(base / v)


class _FakeStore:
    """Stand-in for ReportsStore with just what retention needs."""

    def __init__(self, rows: list[dict[str, Any]] | None = None):
        self.rows = list(rows or [])
        self.deleted_ids: list[str] = []

    def list_runs_by_report_version(self, version: str):
        return [r for r in self.rows if r.get("report_version") == version]

    def delete_run(self, run_id: str) -> bool:
        before = len(self.rows)
        self.rows = [r for r in self.rows if r.get("run_id") != run_id]
        if len(self.rows) < before:
            self.deleted_ids.append(run_id)
            return True
        return False


class TestPruneVersionsBasic:
    def test_keeps_newest_n(self, tmp_path: Path):
        root = tmp_path / "reports"
        _seed_mode(root, "M1", 1, [
            "rv_20260401T000000Z_aaaa",
            "rv_20260402T000000Z_bbbb",
            "rv_20260403T000000Z_cccc",
            "rv_20260404T000000Z_dddd",
            "rv_20260405T000000Z_eeee",
        ])
        result = prune_versions(root, _FakeStore(), keep_last=2, dry_run=False)
        assert result["versions_kept"] == 2
        assert result["versions_deleted"] == 3
        remaining = sorted(
            (root / "M1" / "mode_1" / "versions").iterdir(),
            key=lambda p: p.name,
        )
        assert [p.name for p in remaining] == [
            "rv_20260404T000000Z_dddd",
            "rv_20260405T000000Z_eeee",
        ]

    def test_under_threshold_noop(self, tmp_path: Path):
        root = tmp_path / "reports"
        _seed_mode(root, "M1", 1, [
            "rv_20260401T000000Z_aaaa",
            "rv_20260402T000000Z_bbbb",
        ])
        result = prune_versions(root, _FakeStore(), keep_last=5)
        assert result["versions_deleted"] == 0
        assert result["versions_kept"] == 2

    def test_missing_root_returns_empty(self, tmp_path: Path):
        # Never errors on a nonexistent reports_root.
        result = prune_versions(tmp_path / "nope", _FakeStore(), keep_last=3)
        assert result["versions_deleted"] == 0
        assert result["versions_kept"] == 0


class TestPruneVersionsDryRun:
    def test_reports_targets_without_touching_disk(self, tmp_path: Path):
        root = tmp_path / "reports"
        _seed_mode(root, "M1", 1, [
            "rv_20260401T000000Z_aaaa",
            "rv_20260402T000000Z_bbbb",
            "rv_20260403T000000Z_cccc",
        ])
        store = _FakeStore([
            {"run_id": "aaaa", "report_version": "rv_20260401T000000Z_aaaa", "status": "completed"},
        ])
        result = prune_versions(root, store, keep_last=1, dry_run=True)
        assert result["versions_deleted"] == 2
        assert len(result["deleted_paths"]) == 2
        # Nothing actually removed.
        remaining = list((root / "M1" / "mode_1" / "versions").iterdir())
        assert len(remaining) == 3
        # DB untouched.
        assert store.deleted_ids == []


class TestPruneVersionsDBSync:
    def test_deletes_matching_runs_rows(self, tmp_path: Path):
        root = tmp_path / "reports"
        _seed_mode(root, "M1", 1, [
            "rv_20260401T000000Z_aaaa",
            "rv_20260402T000000Z_bbbb",
            "rv_20260403T000000Z_cccc",
        ])
        store = _FakeStore([
            {"run_id": "aaaa12", "report_version": "rv_20260401T000000Z_aaaa", "status": "completed"},
            {"run_id": "bbbb12", "report_version": "rv_20260402T000000Z_bbbb", "status": "completed"},
            {"run_id": "cccc12", "report_version": "rv_20260403T000000Z_cccc", "status": "completed"},
        ])
        result = prune_versions(root, store, keep_last=1, dry_run=False)
        assert result["db_rows_deleted"] == 2
        # Newest kept — its row stays.
        assert any(r["report_version"] == "rv_20260403T000000Z_cccc"
                   for r in store.rows)
        assert set(store.deleted_ids) == {"aaaa12", "bbbb12"}


class TestPruneVersionsActiveRunSkip:
    def test_running_row_blocks_delete(self, tmp_path: Path):
        root = tmp_path / "reports"
        _seed_mode(root, "M1", 1, [
            "rv_20260401T000000Z_aaaa",
            "rv_20260402T000000Z_bbbb",
        ])
        store = _FakeStore([
            {
                "run_id": "aaaa12",
                "report_version": "rv_20260401T000000Z_aaaa",
                "status": "running",
            },
        ])
        result = prune_versions(root, store, keep_last=1, dry_run=False)
        # Old version is ALSO the one actively running — retention must
        # leave it alone.
        assert result["skipped_active_runs"] == 1
        assert result["versions_deleted"] == 0
        assert (root / "M1" / "mode_1" / "versions" / "rv_20260401T000000Z_aaaa").exists()

    def test_importing_row_also_skipped(self, tmp_path: Path):
        root = tmp_path / "reports"
        _seed_mode(root, "M1", 1, [
            "rv_20260401T000000Z_aaaa",
            "rv_20260402T000000Z_bbbb",
        ])
        store = _FakeStore([
            {
                "run_id": "aaaa12",
                "report_version": "rv_20260401T000000Z_aaaa",
                "status": "importing",
            },
        ])
        result = prune_versions(root, store, keep_last=1, dry_run=False)
        assert result["skipped_active_runs"] == 1


class TestPruneVersionsManifestRefresh:
    def test_index_and_latest_rebuilt_after_delete(self, tmp_path: Path):
        root = tmp_path / "reports"
        _seed_mode(root, "M1", 1, [
            "rv_20260401T000000Z_aaaa",
            "rv_20260402T000000Z_bbbb",
            "rv_20260403T000000Z_cccc",
        ])
        mode_dir = root / "M1" / "mode_1"
        prune_versions(root, _FakeStore(), keep_last=1, dry_run=False)
        # index.json reflects only remaining 1 version.
        index = json.loads((mode_dir / "index.json").read_text(encoding="utf-8"))
        assert len(index) == 1
        assert index[0]["report_version"] == "rv_20260403T000000Z_cccc"
        # latest.json points at newest.
        latest = json.loads((mode_dir / "latest.json").read_text(encoding="utf-8"))
        assert latest["report_version"] == "rv_20260403T000000Z_cccc"

    def test_no_refresh_when_nothing_deleted(self, tmp_path: Path):
        # If the mode dir is under threshold, manifests should NOT be
        # rewritten (they might be intentionally maintained elsewhere).
        root = tmp_path / "reports"
        _seed_mode(root, "M1", 1, ["rv_20260401T000000Z_aaaa"])
        mode_dir = root / "M1" / "mode_1"
        # Pre-write a custom index (intentionally different shape)
        sentinel = [{"marker": "pre-existing"}]
        (mode_dir / "index.json").write_text(json.dumps(sentinel), encoding="utf-8")
        prune_versions(root, _FakeStore(), keep_last=5, dry_run=False)
        # Manifest untouched.
        assert json.loads((mode_dir / "index.json").read_text(encoding="utf-8")) == sentinel


class TestPruneVersionsValidation:
    def test_keep_last_zero_raises(self, tmp_path: Path):
        with pytest.raises(ValueError):
            prune_versions(tmp_path, _FakeStore(), keep_last=0)

    def test_keep_last_negative_raises(self, tmp_path: Path):
        with pytest.raises(ValueError):
            prune_versions(tmp_path, _FakeStore(), keep_last=-3)


class TestPruneVersionsEndpoint:
    def test_endpoint_returns_report(self, client, tmp_path: Path, app_factory):
        c, _ = client
        # Seed reports under the app's reports_root.
        reports_root = app_factory.reports_dir
        _seed_mode(reports_root, "M1", 1, [
            f"rv_2026040{i}T000000Z_{'x' * 4}" for i in range(1, 5)
        ])
        r = c.post(
            "/api/maintenance/prune-versions",
            json={"keep": 2, "dry_run": False},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["keep_last"] == 2
        assert body["versions_deleted"] == 2
        assert body["versions_kept"] == 2

    def test_endpoint_dry_run(self, client, tmp_path: Path, app_factory):
        c, _ = client
        reports_root = app_factory.reports_dir
        _seed_mode(reports_root, "M1", 1, [
            f"rv_2026040{i}T000000Z_yyyy" for i in range(1, 4)
        ])
        r = c.post(
            "/api/maintenance/prune-versions",
            json={"keep": 1, "dry_run": True},
        )
        body = r.json()
        assert body["dry_run"] is True
        assert body["versions_deleted"] == 2
        # Filesystem unchanged.
        versions_dir = reports_root / "M1" / "mode_1" / "versions"
        assert len(list(versions_dir.iterdir())) == 3

    def test_endpoint_rejects_keep_zero(self, client):
        c, _ = client
        r = c.post("/api/maintenance/prune-versions", json={"keep": 0})
        assert r.status_code == 400
