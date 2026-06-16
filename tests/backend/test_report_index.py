"""Tests for src.web_console.backend.report_index + F1-F4 wire-up.

Design contract: REPORT_MGMT_FIX_2026-06-12.md §Tests
All assertions are value-agnostic (shape / presence of keys, not exact
RTP values). Inject-bug pattern: break → RED, revert → GREEN.

Test classes:
  1. TestBuildIndexEntry: shape, report_file presence/absence.
  2. TestAppendAndRewriteLatest: locked append race (two threads).
  3. TestF2FailureHygiene: generate path failure leaves no version dir.
  4. TestF3ReportCount: load_machines counts only dirs with summary.
  5. TestReconcileReports: synthetic litter → dry-run reports actions,
     wet-run repairs, second run = no-op (idempotent).
  6. TestUpdateRunEffectiveVersion: generate path sets
     effective_analyzer_version on the run row.
  7. TestImportIndexEntry: /api/reports/import appends index+latest.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web_console.backend.report_index import (
    build_index_entry,
    append_and_rewrite_latest,
    append_index_entry,
    rewrite_latest,
)
from src.web_console.backend.app import create_app, load_machines

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_summary(
    rtp: float = 93.5,
    config_md5: str = "aabbccdd1234",
    code_md5: str = "eeff99887766",
    analyzer_version: str = "v1.2.3",
    effective_analyzer_version: str = "eff_abc123",
    run_id: str = "run_test001",
) -> dict:
    return {
        "run_id": run_id,
        "config_md5": config_md5,
        "code_md5": code_md5,
        "analyzer_version": analyzer_version,
        "effective_analyzer_version": effective_analyzer_version,
        "rtp": {"point_pct": rtp},
        "sampling": {
            "finished_at": "2026-06-12T10:00:00Z",
            "started_at": "2026-06-12T09:00:00Z",
            "achieved_halfwidth_pp": 0.005,
            "total_spins": 100000,
        },
        "guideline_assessment": {
            "data_quality": {"quality_label": "report-grade"},
        },
    }


def _write_summary(path: Path, **kwargs) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    s = _make_summary(**kwargs)
    path.write_text(json.dumps(s), encoding="utf-8")
    return s


# ---------------------------------------------------------------------------
# F1: TestBuildIndexEntry
# ---------------------------------------------------------------------------


class TestBuildIndexEntry:
    def test_full_field_set(self, tmp_path: Path):
        """build_index_entry returns all required fields."""
        summary = _make_summary()
        sp = tmp_path / "player_impact_summary.json"
        _write_summary(sp)
        entry = build_index_entry(
            tmp_path, "M15", 1, "rv_20260612T000000Z", "run001",
            summary=summary, summary_path=sp,
        )
        for field in [
            "report_version", "run_id", "created_at", "summary_file",
            "rtp_point_pct", "achieved_rtp_pct", "achieved_halfwidth_pp",
            "total_spins", "quality_label",
            "rawdata_config_md5", "rawdata_code_md5",
            "analyzer_version", "effective_analyzer_version",
        ]:
            assert field in entry, f"Missing field: {field}"
        assert entry["rawdata_config_md5"] == "aabbccdd1234"
        assert entry["effective_analyzer_version"] == "eff_abc123"

    def test_report_file_absent_when_no_md(self, tmp_path: Path):
        """report_file key must be ABSENT when no .md exists."""
        summary = _make_summary()
        sp = tmp_path / "player_impact_summary.json"
        _write_summary(sp)
        entry = build_index_entry(
            tmp_path, "M15", 1, "rv_20260612T000000Z", "run001",
            summary=summary, summary_path=sp,
        )
        assert "report_file" not in entry, (
            "report_file key must be absent when no .md file exists"
        )

    def test_report_file_present_when_md_exists(self, tmp_path: Path):
        """report_file key must be PRESENT when .md file is on disk."""
        summary = _make_summary()
        sp = tmp_path / "player_impact_summary.json"
        _write_summary(sp)
        md_path = tmp_path / "player_impact_report.md"
        md_path.write_text("# report", encoding="utf-8")
        entry = build_index_entry(
            tmp_path, "M15", 1, "rv_20260612T000000Z", "run001",
            summary=summary, summary_path=sp,
        )
        assert "report_file" in entry, "report_file key must be present when .md exists"
        assert entry["report_file"] == str(md_path)

    def test_empty_summary_fields_graceful(self, tmp_path: Path):
        """build_index_entry with minimal summary does not crash."""
        sp = tmp_path / "player_impact_summary.json"
        sp.write_text("{}", encoding="utf-8")
        entry = build_index_entry(
            tmp_path, "M99", 1, "rv_20260612T000000Z", "run_min",
            summary={}, summary_path=sp,
        )
        # Must at least have required keys with empty/None values.
        assert "rawdata_config_md5" in entry
        assert "effective_analyzer_version" in entry
        assert entry["rawdata_config_md5"] == ""
        assert entry["effective_analyzer_version"] == ""


# ---------------------------------------------------------------------------
# F1: TestAppendAndRewriteLatest — race safety
# ---------------------------------------------------------------------------


class TestAppendAndRewriteLatest:
    def test_sequential_append(self, tmp_path: Path):
        """Sequential appends accumulate all entries in index.json."""
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        for i in range(3):
            summary = _make_summary(run_id=f"run{i:03d}")
            sp = mode_dir / f"rv_{i:03d}" / "player_impact_summary.json"
            _write_summary(sp)
            entry = build_index_entry(
                tmp_path, "M15", 1, f"rv_{i:03d}", f"run{i:03d}",
                summary=summary, summary_path=sp,
            )
            append_and_rewrite_latest(mode_dir, entry)
        raw = json.loads((mode_dir / "index.json").read_text(encoding="utf-8"))
        assert len(raw) == 3

    def test_concurrent_append_no_lost_entries(self, tmp_path: Path):
        """Two concurrent append_and_rewrite_latest calls both survive in index."""
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()

        errors: list[str] = []
        n_threads = 8

        def _do(i: int) -> None:
            summary = _make_summary(run_id=f"run{i:03d}")
            sp = mode_dir / f"rv_{i:03d}" / "player_impact_summary.json"
            _write_summary(sp)
            entry = build_index_entry(
                tmp_path, "M15", 1, f"rv_{i:03d}", f"run{i:03d}",
                summary=summary, summary_path=sp,
            )
            try:
                append_and_rewrite_latest(mode_dir, entry)
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

        threads = [threading.Thread(target=_do, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        raw = json.loads((mode_dir / "index.json").read_text(encoding="utf-8"))
        assert len(raw) == n_threads, (
            f"Expected {n_threads} entries, got {len(raw)} — lost-update race occurred"
        )


# ---------------------------------------------------------------------------
# F3: TestReportCount — load_machines only counts dirs with summary
# ---------------------------------------------------------------------------


class TestReportCount:
    def test_empty_dir_not_counted(self, tmp_path: Path):
        """Empty version dir must NOT increment report_count."""
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{"machine": "M15", "modes": [1]}]}),
                      encoding="utf-8")
        rr = tmp_path / "reports"
        # Create an empty version dir.
        (rr / "M15" / "mode_1" / "versions" / "rv_empty").mkdir(parents=True)
        machines = load_machines(path=mc, reports_root=rr)
        m15 = next(m for m in machines if m["machine"] == "M15")
        assert m15["report_count"] == 0, (
            f"Empty dir should not be counted; got report_count={m15['report_count']}"
        )

    def test_dir_with_summary_counted(self, tmp_path: Path):
        """Version dir with player_impact_summary.json IS counted."""
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{"machine": "M15", "modes": [1]}]}),
                      encoding="utf-8")
        rr = tmp_path / "reports"
        vdir = rr / "M15" / "mode_1" / "versions" / "rv_real"
        vdir.mkdir(parents=True)
        _write_summary(vdir / "player_impact_summary.json")
        machines = load_machines(path=mc, reports_root=rr)
        m15 = next(m for m in machines if m["machine"] == "M15")
        assert m15["report_count"] == 1

    def test_no_summary_dir_not_counted(self, tmp_path: Path):
        """Dir with only machine_config.json is not counted."""
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{"machine": "M15", "modes": [1]}]}),
                      encoding="utf-8")
        rr = tmp_path / "reports"
        vdir = rr / "M15" / "mode_1" / "versions" / "rv_no_summary"
        vdir.mkdir(parents=True)
        (vdir / "machine_config.json").write_text("{}", encoding="utf-8")
        machines = load_machines(path=mc, reports_root=rr)
        m15 = next(m for m in machines if m["machine"] == "M15")
        assert m15["report_count"] == 0


# ---------------------------------------------------------------------------
# F4: TestReconcileReports — synthetic litter tree
# ---------------------------------------------------------------------------

def _m15_chunks_present() -> bool:
    return (
        (_REPO_ROOT / "rawdata" / "M15" / "mode_1").exists()
        and len(list((_REPO_ROOT / "rawdata" / "M15" / "mode_1").glob("chunk_*.json"))) > 0
    )


@pytest.fixture
def reconcile_app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Minimal isolated app for reconcile endpoint tests."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "progress").mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    mc = tmp_path / "machines.json"
    mc.write_text(json.dumps({"machines": [{"machine": "MREC", "modes": [1]}]}),
                  encoding="utf-8")
    monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
    app = create_app(
        state_dir=state_dir,
        reports_root=reports_dir,
        machines_config=mc,
    )
    with TestClient(app) as client:
        yield client, reports_dir


class TestReconcileReports:
    def _build_litter_tree(self, reports_dir: Path) -> dict:
        """Build a synthetic tree with each defect class for MREC/mode_1."""
        base = reports_dir / "MREC" / "mode_1" / "versions"
        base.mkdir(parents=True, exist_ok=True)

        # Class 1: empty dir.
        (base / "rv_empty_001").mkdir()

        # Class 2: no-summary dir (with machine_config only) — age will be >1h.
        no_summary = base / "rv_no_summary_001"
        no_summary.mkdir()
        (no_summary / "machine_config.json").write_text("{}", encoding="utf-8")
        # Make it look old (>1h) by forcing mtime.
        import os as _os
        _old = time.time() - 7200
        _os.utime(str(no_summary), (_old, _old))

        # Class 3: dir with summary, not in index yet.
        unindexed = base / "rv_unindexed_001"
        unindexed.mkdir()
        _write_summary(unindexed / "player_impact_summary.json",
                       run_id="run_unindexed")

        # Existing valid version (to verify idempotence later).
        valid = base / "rv_valid_001"
        valid.mkdir()
        _write_summary(valid / "player_impact_summary.json", run_id="run_valid")

        return {
            "empty": base / "rv_empty_001",
            "no_summary": no_summary,
            "unindexed": unindexed,
            "valid": valid,
        }

    def test_dry_run_reports_actions(self, reconcile_app_client):
        """Dry-run must report the right action classes without modifying disk."""
        client, reports_dir = reconcile_app_client
        litter = self._build_litter_tree(reports_dir)

        resp = client.post("/api/maintenance/reconcile-reports", json={"dry_run": True})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["dry_run"] is True
        counts = data["counts"]

        # Empty dir should be flagged.
        assert counts.get("empty_dir_delete", 0) >= 1, (
            f"Expected empty_dir_delete >= 1, got {counts}"
        )
        # No-summary dir should be flagged (not skip — we forced age >1h).
        assert counts.get("no_summary_dir_delete", 0) >= 1, (
            f"Expected no_summary_dir_delete >= 1, got {counts}"
        )
        # Unindexed dir should be flagged.
        assert counts.get("unindexed_summary_append", 0) >= 1, (
            f"Expected unindexed_summary_append >= 1, got {counts}"
        )
        # Dry-run must NOT touch disk.
        assert litter["empty"].exists(), "Dry-run must not delete empty dir"

    def test_wet_run_repairs(self, reconcile_app_client):
        """Wet-run must repair the litter."""
        client, reports_dir = reconcile_app_client
        litter = self._build_litter_tree(reports_dir)

        resp = client.post("/api/maintenance/reconcile-reports", json={"dry_run": False})
        assert resp.status_code == 200, resp.text

        # Empty dir should be gone.
        assert not litter["empty"].exists(), "Wet-run must delete empty dir"
        # No-summary dir should be gone.
        assert not litter["no_summary"].exists(), "Wet-run must delete no-summary dir"
        # Unindexed dir should now be in index.json.
        index_path = reports_dir / "MREC" / "mode_1" / "index.json"
        assert index_path.exists(), "index.json must exist after wet-run"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        rv_names = {e.get("report_version") for e in index}
        assert "rv_unindexed_001" in rv_names, (
            f"Unindexed dir must be in index after repair; got: {rv_names}"
        )

    def test_idempotent(self, reconcile_app_client):
        """Second wet-run on an already-repaired tree must be a no-op."""
        client, reports_dir = reconcile_app_client
        self._build_litter_tree(reports_dir)

        # First run.
        client.post("/api/maintenance/reconcile-reports", json={"dry_run": False})
        # Second run.
        resp2 = client.post("/api/maintenance/reconcile-reports", json={"dry_run": False})
        assert resp2.status_code == 200
        data2 = resp2.json()
        counts2 = data2["counts"]
        # No litter actions on the second pass.
        assert counts2.get("empty_dir_delete", 0) == 0
        assert counts2.get("no_summary_dir_delete", 0) == 0
        assert counts2.get("unindexed_summary_append", 0) == 0

    def test_idempotent_legacy_empty_effective_version(
        self, reconcile_app_client
    ):
        """Real-tree regression: legacy summaries that have effective_analyzer_version=''
        (empty string, not absent) must NOT trigger persist_backfill on the second run.

        Root cause: the old check 'if not patched.get(field)' is True for both
        None and ''.  Fill reads summary, also gets '', writes ''->'' (no change),
        but still counts persist_backfill and marks index_dirty.  On the 2026-06-12
        live tree this caused persist_backfill:73 + latest_recompute:30 on every run.

        Inject-bug: in reconcile's Action 5, change _check_str_field to the old:
            if not patched.get(field):
                _fill_pairs.append((field, summary.get(src_key) or ''))
        → second run fires persist_backfill >= 1 → RED.  Revert → GREEN.
        """
        client, reports_dir = reconcile_app_client
        base = reports_dir / "MREC" / "mode_1" / "versions"
        base.mkdir(parents=True, exist_ok=True)

        vdir = base / "rv_legacy_empty_eff"
        vdir.mkdir()
        # Write a summary where effective_analyzer_version is PRESENT but EMPTY.
        legacy_summary = {
            "run_id": "legacy_run",
            "config_md5": "cfg_legacy",
            "code_md5": "code_legacy",
            "analyzer_version": "v_old",
            "effective_analyzer_version": "",  # empty string — the real-tree case
            "rtp": {"point_pct": 91.0},
            "sampling": {
                "achieved_halfwidth_pp": 0.01,
                "total_spins": 50000,
                "started_at": "2026-05-01T00:00:00Z",
                "finished_at": "2026-05-01T01:00:00Z",
            },
            "guideline_assessment": {
                "data_quality": {"quality_label": "report-grade"},
            },
        }
        sf = vdir / "player_impact_summary.json"
        sf.write_text(json.dumps(legacy_summary), encoding="utf-8")

        # Pre-populate index with an entry that also has empty effective_analyzer_version.
        mode_dir = reports_dir / "MREC" / "mode_1"
        idx = mode_dir / "index.json"
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text(json.dumps([{
            "report_version": "rv_legacy_empty_eff",
            "run_id": "legacy_run",
            "created_at": "2026-05-01T01:00:00Z",
            "summary_file": str(sf),
            "rtp_point_pct": 91.0,
            "achieved_rtp_pct": 91.0,
            "achieved_halfwidth_pp": 0.01,
            "total_spins": 50000,
            "quality_label": "report-grade",
            "rawdata_config_md5": "cfg_legacy",
            "rawdata_code_md5": "code_legacy",
            "analyzer_version": "v_old",
            "effective_analyzer_version": "",  # empty — matches summary
        }]), encoding="utf-8")

        # First wet-run — may or may not produce persist_backfill (doesn't matter).
        resp1 = client.post(
            "/api/maintenance/reconcile-reports", json={"dry_run": False}
        )
        assert resp1.status_code == 200, resp1.text

        # SECOND wet-run must NOT produce persist_backfill for this entry.
        resp2 = client.post(
            "/api/maintenance/reconcile-reports", json={"dry_run": False}
        )
        assert resp2.status_code == 200, resp2.text
        counts2 = resp2.json()["counts"]
        assert counts2.get("persist_backfill", 0) == 0, (
            f"IDEMPOTENCY BROKEN: persist_backfill={counts2.get('persist_backfill')} "
            "on second run.  Legacy entries with effective_analyzer_version='' must "
            "NOT be re-backfilled.  "
            "Inject-bug: revert _check_str_field to old 'if not patched.get(field)' "
            "check → this fires → RED.  Revert → GREEN."
        )
        assert counts2.get("latest_recompute", 0) == 0, (
            f"IDEMPOTENCY BROKEN: latest_recompute={counts2.get('latest_recompute')} "
            "on second run caused by spurious persist_backfill no-ops setting index_dirty."
        )

    def test_idempotent_canonical_latest(self, reconcile_app_client):
        """Real-tree regression: a mode_dir whose latest.json is already canonical
        must NOT trigger latest_recompute on the second run.

        Root cause: when index_dirty=True (from any mutation), the old code
        unconditionally wrote latest.json and counted latest_recompute even when
        the recomputed content was identical to what was already on disk.

        Inject-bug: in reconcile's index_dirty path, remove the comparison
        'if _latest_cur.get(\"report_version\") != latest.get(\"report_version\")'
        and always write + count → second run fires latest_recompute >= 1 even
        when content is identical → RED.  Revert → GREEN.
        """
        client, reports_dir = reconcile_app_client
        base = reports_dir / "MREC" / "mode_1" / "versions"
        base.mkdir(parents=True, exist_ok=True)

        # Create a valid version with a summary.
        vdir = base / "rv_canonical_001"
        vdir.mkdir()
        sf = vdir / "player_impact_summary.json"
        _write_summary(sf, run_id="canonical_run",
                       config_md5="cfg_canon", effective_analyzer_version="eff_canon")

        # Write an unindexed version so the first run produces
        # unindexed_summary_append (sets index_dirty=True) — this exercises the
        # path that previously also unconditionally wrote latest.json.
        vdir2 = base / "rv_canonical_002"
        vdir2.mkdir()
        sf2 = vdir2 / "player_impact_summary.json"
        _write_summary(sf2, run_id="canonical_run_2",
                       config_md5="cfg_canon2", effective_analyzer_version="eff_canon2")

        # First wet-run repairs: indexes both dirs, writes latest.json.
        resp1 = client.post(
            "/api/maintenance/reconcile-reports", json={"dry_run": False}
        )
        assert resp1.status_code == 200, resp1.text
        counts1 = resp1.json()["counts"]
        # After first run, index should have both entries.
        idx = reports_dir / "MREC" / "mode_1" / "index.json"
        assert idx.exists()

        # Second wet-run: index is complete, latest.json is canonical.
        # Must produce ZERO mutating actions.
        resp2 = client.post(
            "/api/maintenance/reconcile-reports", json={"dry_run": False}
        )
        assert resp2.status_code == 200, resp2.text
        counts2 = resp2.json()["counts"]
        assert counts2.get("latest_recompute", 0) == 0, (
            f"IDEMPOTENCY BROKEN: latest_recompute={counts2.get('latest_recompute')} "
            "on second run even though latest.json is already canonical.  "
            "Inject-bug: remove the report_version comparison in the index_dirty "
            "latest_recompute path → always writes + counts → RED.  Revert → GREEN."
        )
        assert counts2.get("persist_backfill", 0) == 0, (
            f"IDEMPOTENCY BROKEN: persist_backfill={counts2.get('persist_backfill')} "
            "on second run."
        )
        assert counts2.get("unindexed_summary_append", 0) == 0, (
            "Both versions must already be indexed on second run"
        )


# ---------------------------------------------------------------------------
# F1: TestUpdateRunEffectiveVersion
# — generate path sets effective_analyzer_version on run row
# ---------------------------------------------------------------------------


@pytest.fixture
def m15_gen_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                   isolated_rawdata_factory):
    """App with real M15 rawdata; generates a report in-process.

    rawdata_root is an ISOLATED tmp tree holding only M15 (hardlinked from the
    real rawdata/). Pointing it at the real rawdata/ would let generate's
    disk-space auto-cleanup evict other machines' chunks (the 2026-06-16
    M43/mode_7 loss). See tests/backend/conftest.py::isolated_rawdata_factory.
    """
    if not _m15_chunks_present():
        pytest.skip("M15 cached chunks not present")
    state_dir = tmp_path / "state"; state_dir.mkdir()
    (state_dir / "progress").mkdir()
    reports_dir = tmp_path / "reports"; reports_dir.mkdir()
    mc = tmp_path / "machines.json"
    mc.write_text(json.dumps({"machines": [{"machine": "M15", "modes": [1]}]}),
                  encoding="utf-8")
    monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
    app = create_app(
        state_dir=state_dir,
        reports_root=reports_dir,
        machines_config=mc,
        rawdata_root=isolated_rawdata_factory("M15", [1]),
    )
    with TestClient(app) as client:
        yield client, reports_dir


class TestUpdateRunEffectiveVersion:
    def test_index_entry_has_all_fields(self, m15_gen_client):
        """Generated index entry must have rawdata_config_md5 and effective_analyzer_version."""
        client, reports_dir = m15_gen_client
        resp = client.post("/api/rawdata/M15/generate-report", json={"mode": 1})
        assert resp.status_code == 200
        data = resp.json()
        report_version = data["report_version"]
        index_path = reports_dir / "M15" / "mode_1" / "index.json"
        assert index_path.exists(), "index.json must exist after generate"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        entry = next(
            (e for e in index if e.get("report_version") == report_version), None
        )
        assert entry is not None, f"Entry for {report_version} not found in index"

        # Must have all required fields.
        for field in [
            "rawdata_config_md5", "rawdata_code_md5",
            "analyzer_version", "effective_analyzer_version",
        ]:
            assert field in entry, f"index entry missing field: {field}"

        # rawdata_config_md5 must be non-empty (M15 has a known md5).
        assert entry["rawdata_config_md5"], "rawdata_config_md5 must be non-empty"

        # report_file key must NOT be present (new engine writes no .md).
        assert "report_file" not in entry, (
            "report_file key must be absent — new engine never writes .md"
        )

    def test_run_row_has_effective_analyzer_version(self, m15_gen_client):
        """Run row must carry effective_analyzer_version after generate."""
        client, _ = m15_gen_client
        resp = client.post("/api/rawdata/M15/generate-report", json={"mode": 1})
        assert resp.status_code == 200
        run_id = resp.json()["run_id"]
        run_resp = client.get(f"/api/runs/{run_id}")
        assert run_resp.status_code == 200
        run_data = run_resp.json()
        assert run_data.get("status") == "completed"
        # effective_analyzer_version must be non-None (present in M15 summaries).
        assert run_data.get("effective_analyzer_version") is not None, (
            "Run row must carry effective_analyzer_version after generate"
        )


# ---------------------------------------------------------------------------
# F1: TestImportIndexEntry
# — /api/reports/import appends index+latest per version
# ---------------------------------------------------------------------------


@pytest.fixture
def import_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """App fixture for import tests; minimal isolation."""
    state_dir = tmp_path / "state"; state_dir.mkdir()
    (state_dir / "progress").mkdir()
    reports_dir = tmp_path / "reports"; reports_dir.mkdir()
    mc = tmp_path / "machines.json"
    mc.write_text(json.dumps({"machines": [{"machine": "MIMP", "modes": [1]}]}),
                  encoding="utf-8")
    monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
    app = create_app(
        state_dir=state_dir,
        reports_root=reports_dir,
        machines_config=mc,
    )
    with TestClient(app) as client:
        yield client, reports_dir


class TestImportIndexEntry:
    def test_import_appends_index(self, import_client, tmp_path: Path):
        """After /api/reports/import, imported versions appear in index.json."""
        client, reports_dir = import_client

        # Build source tree.
        src = tmp_path / "import_src"
        vdir = src / "MIMP" / "mode_1" / "versions" / "rv_imported_001"
        vdir.mkdir(parents=True)
        _write_summary(vdir / "player_impact_summary.json",
                       config_md5="imp_cfg_md5", code_md5="imp_code_md5",
                       run_id="imp_run_001")

        resp = client.post("/api/reports/import", json={"source_path": str(src)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] >= 1, f"import must succeed; got: {data}"

        index_path = reports_dir / "MIMP" / "mode_1" / "index.json"
        assert index_path.exists(), "index.json must exist after import"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        assert len(index) >= 1
        entry = index[0]
        # Must have all F1 fields.
        for field in [
            "rawdata_config_md5", "rawdata_code_md5",
            "analyzer_version", "effective_analyzer_version",
        ]:
            assert field in entry, f"imported index entry missing field: {field}"
        # latest.json must exist.
        assert (reports_dir / "MIMP" / "mode_1" / "latest.json").exists(), (
            "latest.json must exist after import"
        )
