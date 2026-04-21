"""Tests for DELETE /api/reports/{machine}/{mode}/{version}.

2026-04-21 bug report: M14 had "weird reports that can't be deleted".
Root cause: when index.json listed a report but the disk dir was
already gone (partial cleanup, manual rm, interrupted rmtree, etc.),
the endpoint raised 404. Frontend showed "删除失败: 404" and the
zombie stayed in index.json forever.

Fix: endpoint is now idempotent — if disk is missing but index.json
has the entry, finish the cleanup (rewrite index.json + drop DB row)
and return ``disk_removed=False`` so the caller can distinguish.

Tests cover:
  * happy path (disk + index both present → normal delete)
  * ZOMBIE path (index has entry, disk gone → idempotent cleanup)
  * truly-not-found (neither disk nor index) → 404 still raised
  * latest.json re-point when the deleted version was "latest"
  * latest.json unlink when no surviving versions after delete
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_version_on_disk(reports_root: Path, machine: str, mode: int,
                           version: str, summary: dict | None = None) -> Path:
    """Create a reports/<m>/mode_<n>/versions/<rv>/ dir with a minimal
    summary.json so the endpoint treats it as a real version."""
    vdir = reports_root / machine / f"mode_{mode}" / "versions" / version
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "player_impact_summary.json").write_text(
        json.dumps(summary or {"sampling": {"total_spins": 100}}),
        encoding="utf-8",
    )
    (vdir / "player_impact_report.md").write_text("# report", encoding="utf-8")
    return vdir


def _write_index(reports_root: Path, machine: str, mode: int,
                 versions: list[dict]) -> Path:
    """Write index.json listing the given versions."""
    mode_dir = reports_root / machine / f"mode_{mode}"
    mode_dir.mkdir(parents=True, exist_ok=True)
    index_path = mode_dir / "index.json"
    index_path.write_text(json.dumps(versions, indent=2), encoding="utf-8")
    return index_path


def _write_latest(reports_root: Path, machine: str, mode: int,
                  entry: dict) -> Path:
    mode_dir = reports_root / machine / f"mode_{mode}"
    mode_dir.mkdir(parents=True, exist_ok=True)
    latest_path = mode_dir / "latest.json"
    latest_path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    return latest_path


class TestDeleteReportVersion:

    def test_zombie_index_entry_no_disk_dir_still_deletes(
        self, tmp_reports, client,
    ):
        """REGRESSION 2026-04-21: the user-reported bug. index.json
        lists a version but the disk dir is already gone. Before the
        fix, DELETE returned 404 and the zombie entry was never
        cleaned up. After the fix: DELETE is idempotent — rewrites
        index.json, returns disk_removed=False."""
        c, _ = client
        rv = "rv_20260414T030156Z_zombie01"
        # Index says it exists, disk does not.
        _write_index(tmp_reports, "M14", 1, [{
            "report_version": rv,
            "run_id": "zombie010000",
            "rtp_point_pct": 42.0,
            "quality_label": "EXPLORATORY",
        }])

        # Sanity: GET sees the zombie
        r = c.get("/api/reports/M14/1")
        assert r.status_code == 200
        assert len(r.json()["versions"]) == 1

        # DELETE should now succeed (was 404 before fix)
        r = c.delete(f"/api/reports/M14/1/{rv}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["deleted_version"] == rv
        assert body["remaining_versions"] == 0
        # disk_removed=False tells the caller this was a zombie
        # cleanup, not a physical rmtree — useful signal for the UI
        # activity log.
        assert body["disk_removed"] is False

        # index.json is empty after the cleanup
        index = json.loads(
            (tmp_reports / "M14" / "mode_1" / "index.json").read_text(encoding="utf-8")
        )
        assert index == []
        # GET no longer surfaces the zombie
        r = c.get("/api/reports/M14/1")
        assert len(r.json()["versions"]) == 0

    def test_disk_and_index_present_normal_delete(
        self, tmp_reports, client,
    ):
        """Baseline happy path: disk + index both present → normal
        delete. disk_removed=True distinguishes from zombie cleanup."""
        c, _ = client
        rv = "rv_20260414T030156Z_normal01"
        _write_version_on_disk(tmp_reports, "M14", 1, rv)
        _write_index(tmp_reports, "M14", 1, [{
            "report_version": rv,
            "run_id": "normal010000",
            "rtp_point_pct": 95.0,
            "quality_label": "STATISTICAL",
        }])

        r = c.delete(f"/api/reports/M14/1/{rv}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["disk_removed"] is True  # physical dir was removed

        # Disk dir is gone
        vdir = tmp_reports / "M14" / "mode_1" / "versions" / rv
        assert not vdir.exists()
        # Index is empty
        index = json.loads(
            (tmp_reports / "M14" / "mode_1" / "index.json").read_text(encoding="utf-8")
        )
        assert index == []

    def test_truly_not_found_still_404s(self, tmp_reports, client):
        """Guard: when NEITHER disk nor index.json knows about the
        version, we still 404 — the idempotent fix must not swallow
        genuine "never existed" 404s."""
        c, _ = client
        # Seed the mode_dir with an empty index so the path exists
        # but the target version isn't there.
        _write_index(tmp_reports, "M14", 1, [])

        r = c.delete("/api/reports/M14/1/rv_totally_not_a_thing_0000")
        assert r.status_code == 404
        assert "version not found" in r.json()["detail"]

    def test_zombie_delete_repoints_latest_json(
        self, tmp_reports, client,
    ):
        """When the deleted version was listed as `latest`, and there's
        a surviving version, latest.json must re-point to it.
        Edge case: zombie delete should still repoint correctly."""
        c, _ = client
        zombie_rv = "rv_20260414T030156Z_zombie02"
        survivor_rv = "rv_20260414T010000Z_survvor1"  # noqa — keep same length
        # Survivor exists on disk + index
        _write_version_on_disk(tmp_reports, "M14", 1, survivor_rv)
        _write_index(tmp_reports, "M14", 1, [
            {"report_version": survivor_rv, "run_id": "survvor10000"},
            {"report_version": zombie_rv, "run_id": "zombie020000"},
        ])
        # latest points at the zombie
        _write_latest(tmp_reports, "M14", 1, {
            "report_version": zombie_rv, "run_id": "zombie020000",
        })

        r = c.delete(f"/api/reports/M14/1/{zombie_rv}")
        assert r.status_code == 200, r.text
        assert r.json()["remaining_versions"] == 1

        # latest.json repointed to the survivor
        latest = json.loads(
            (tmp_reports / "M14" / "mode_1" / "latest.json").read_text(encoding="utf-8")
        )
        assert latest["report_version"] == survivor_rv

    def test_zombie_delete_with_no_survivor_unlinks_latest(
        self, tmp_reports, client,
    ):
        """Last-version zombie delete: latest.json must be unlinked
        since nothing remains to point at."""
        c, _ = client
        zombie_rv = "rv_20260414T030156Z_zombie03"
        _write_index(tmp_reports, "M14", 1, [
            {"report_version": zombie_rv, "run_id": "zombie030000"},
        ])
        _write_latest(tmp_reports, "M14", 1, {
            "report_version": zombie_rv, "run_id": "zombie030000",
        })

        r = c.delete(f"/api/reports/M14/1/{zombie_rv}")
        assert r.status_code == 200, r.text
        assert r.json()["remaining_versions"] == 0

        # latest.json gone
        assert not (tmp_reports / "M14" / "mode_1" / "latest.json").exists()

    def test_zombie_delete_is_idempotent_when_called_twice(
        self, tmp_reports, client,
    ):
        """Second DELETE on the same zombie should now 404 — the
        first call already cleaned up index.json, so there's truly
        nothing left to target."""
        c, _ = client
        rv = "rv_20260414T030156Z_zombie04"
        _write_index(tmp_reports, "M14", 1, [
            {"report_version": rv, "run_id": "zombie040000"},
        ])

        r1 = c.delete(f"/api/reports/M14/1/{rv}")
        assert r1.status_code == 200
        r2 = c.delete(f"/api/reports/M14/1/{rv}")
        assert r2.status_code == 404
