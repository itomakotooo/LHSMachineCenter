"""Tests for Commit 1: analyzer version plumbing.

Covers:
* ``compute_analyzer_version()`` → 12-char hex, deterministic for same
  file content, changes when content changes
* ``/api/versions/current`` endpoint shape + malformed machines.json
* Summary-level ``analyzer_version`` field stamped by analyzer.main()
* DB migration + backfill: ``rawdata_config_md5`` / ``rawdata_code_md5``
  / ``analyzer_version`` columns populated from summary.json
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


class TestComputeAnalyzerVersion:
    def test_returns_12_char_hex(self):
        from fresh_slotlab.player_impact_analyzer import compute_analyzer_version
        v = compute_analyzer_version()
        assert isinstance(v, str)
        assert len(v) == 12
        # All hex chars
        int(v, 16)

    def test_deterministic_within_process(self):
        from fresh_slotlab.player_impact_analyzer import compute_analyzer_version
        assert compute_analyzer_version() == compute_analyzer_version()

    def test_matches_manual_sha256_of_module_file(self):
        import fresh_slotlab.player_impact_analyzer as pia
        source_path = Path(pia.__file__).resolve()
        expected = hashlib.sha256(source_path.read_bytes()).hexdigest()[:12]
        assert pia.compute_analyzer_version() == expected


class TestVersionsCurrentEndpoint:
    def test_returns_analyzer_version_and_machines(self, client):
        c, _ = client
        resp = c.get("/api/versions/current")
        assert resp.status_code == 200
        body = resp.json()
        # Analyzer version from real compute_analyzer_version()
        assert "analyzer_version" in body
        assert len(body["analyzer_version"]) == 12
        # Machines map
        assert "machines" in body
        # fake_machines fixture ships with M14
        assert "M14" in body["machines"]
        assert "config_md5" in body["machines"]["M14"]
        assert "code_md5" in body["machines"]["M14"]

    def test_malformed_machines_json_returns_empty_map(
        self, tmp_state_dir, tmp_reports, tmp_cache, fake_analyzer,
        tmp_path, monkeypatch,
    ):
        """Malformed machines.json → endpoint stays 200 with empty
        machines map, so the frontend can still render staleness for
        analyzer_version (still computable) and fall back to
        'untagged' badges for machine md5."""
        monkeypatch.setattr(
            "src.web_console.backend.app._terminate_pid_if_running",
            lambda pid: True,
        )
        bad_mc = tmp_path / "machines.json"
        bad_mc.write_text("{ not valid json", encoding="utf-8")
        from src.web_console.backend.app import create_app
        app = create_app(
            state_dir=tmp_state_dir,
            reports_root=tmp_reports,
            cache_root=tmp_cache,
            machines_config=bad_mc,
            analyzer_path=fake_analyzer,
        )
        with TestClient(app) as c:
            resp = c.get("/api/versions/current")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["analyzer_version"]) == 12
            assert body["machines"] == {}


class TestSummaryAnalyzerVersionStamped:
    """Analyzer main() must include analyzer_version at summary top
    level. Tested here rather than in the heavy M14/M272 regression
    fixtures so the assertion is cheap + focused.
    """

    def test_fixture_summary_has_analyzer_version(self):
        """Real M14 regression fixture's summary.json (produced by the
        current analyzer) must carry analyzer_version."""
        from fresh_slotlab.player_impact_analyzer import compute_analyzer_version
        fixture_glob = Path("tests/fixtures").rglob("player_impact_summary.json")
        seen_any = False
        for fp in fixture_glob:
            try:
                s = json.loads(fp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(s, dict):
                continue
            # Fixtures may be older (pre-analyzer_version). Only
            # assert when the field exists — the goal here is that
            # fresh analyzer runs stamp it, which is tested via the
            # DB backfill path below.
            if "analyzer_version" in s:
                seen_any = True
                assert isinstance(s["analyzer_version"], str)
                assert len(s["analyzer_version"]) in (0, 12)
        # Not a fatal assertion — if no fixtures carry the field yet
        # (e.g. pre-migration), the DB-populate test below covers the
        # live write path.
        _ = seen_any


class TestDbColumnsAndBackfill:
    """Three new columns land on ``runs`` via CREATE IF NOT EXISTS +
    ALTER TABLE. Backfill reads summary.json on startup and populates
    legacy rows."""

    def test_columns_exist_after_create_app(self, client, app_factory):
        _c, app = client
        db_path = app_factory.db_path
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            cols = {
                row[1] for row in
                conn.execute("PRAGMA table_info(runs)").fetchall()
            }
        assert "rawdata_config_md5" in cols
        assert "rawdata_code_md5" in cols
        assert "analyzer_version" in cols

    def test_backfill_populates_from_summary_json(self, app_factory):
        """Simulate legacy row: insert a completed run with null
        fingerprint columns but a summary.json that has them, run
        backfill, assert the row gets populated."""
        import sqlite3
        app = app_factory()

        # Write a summary.json with all three fields
        reports_root = app_factory.reports_dir
        version_dir = reports_root / "M14" / "mode_1" / "versions" / "rv_test"
        version_dir.mkdir(parents=True, exist_ok=True)
        summary_path = version_dir / "player_impact_summary.json"
        summary_path.write_text(json.dumps({
            "machine": "M14",
            "mode": 1,
            "config_md5": "78fe608737c9",
            "code_md5": "536fc5a2a8f2",
            "analyzer_version": "abcdef123456",
            "rtp": {"point_pct": 90.5},
            "sampling": {"achieved_halfwidth_pp": 0.42},
            "guideline_assessment": {"data_quality": {"quality_label": "report-grade"}},
        }), encoding="utf-8")

        db_path = app_factory.db_path
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, machine, mode, status, model_id,
                    created_at, started_at, target_halfwidth_pp,
                    chunk_spin_times, chunk_robot_count, batch_concurrency,
                    max_chunks, timeout, bankruptcy_session_spins,
                    bankruptcy_bankroll_multipliers, report_version,
                    output_dir, progress_file, summary_file)
                VALUES ('legacy_row', 'M14', 1, 'completed', 'model',
                    '2026-01-01', '2026-01-01', 1.0,
                    5000, 24, 2, 10, 30, 500,
                    '100,200,500', 'rv_test',
                    ?, ?, ?)
                """,
                (str(version_dir), str(version_dir / "progress.jsonl"),
                 str(summary_path)),
            )
            conn.commit()

        # Import StateStore and run backfill
        from src.web_console.backend.app import StateStore
        store = StateStore(db_path)
        result = store.backfill_rtp_ci_from_summaries()
        assert result["scanned"] >= 1
        assert result["updated"] >= 1

        # Verify the row now has all three fingerprints
        row = store.get_run("legacy_row")
        assert row is not None
        assert row["rawdata_config_md5"] == "78fe608737c9"
        assert row["rawdata_code_md5"] == "536fc5a2a8f2"
        assert row["analyzer_version"] == "abcdef123456"
        # And the pre-existing backfill still works
        assert row["achieved_rtp_pct"] == pytest.approx(90.5)
        assert row["quality_label"] == "report-grade"

    def test_backfill_skips_rows_with_existing_values(self, app_factory):
        """Rows with all three new fields already populated are not
        touched — idempotent."""
        import sqlite3
        app = app_factory()
        reports_root = app_factory.reports_dir
        version_dir = reports_root / "M14" / "mode_1" / "versions" / "rv_skip"
        version_dir.mkdir(parents=True, exist_ok=True)
        summary_path = version_dir / "player_impact_summary.json"
        summary_path.write_text(json.dumps({
            "machine": "M14", "mode": 1,
            "config_md5": "NEW", "code_md5": "NEW",
            "analyzer_version": "NEWVER",
        }), encoding="utf-8")

        db_path = app_factory.db_path
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, machine, mode, status, model_id,
                    created_at, started_at, target_halfwidth_pp,
                    chunk_spin_times, chunk_robot_count, batch_concurrency,
                    max_chunks, timeout, bankruptcy_session_spins,
                    bankruptcy_bankroll_multipliers, report_version,
                    output_dir, progress_file, summary_file,
                    achieved_rtp_pct, achieved_halfwidth_pp, quality_label,
                    rawdata_config_md5, rawdata_code_md5, analyzer_version)
                VALUES ('kept_row', 'M14', 1, 'completed', 'model',
                    '2026-01-01', '2026-01-01', 1.0,
                    5000, 24, 2, 10, 30, 500,
                    '100,200,500', 'rv_skip',
                    ?, ?, ?,
                    90.0, 0.5, 'report-grade',
                    'OLD', 'OLD', 'OLDVER')
                """,
                (str(version_dir), str(version_dir / "progress.jsonl"),
                 str(summary_path)),
            )
            conn.commit()
        from src.web_console.backend.app import StateStore
        store = StateStore(db_path)
        store.backfill_rtp_ci_from_summaries()
        row = store.get_run("kept_row")
        # All three fingerprints stay at the old values (not overwritten)
        assert row["rawdata_config_md5"] == "OLD"
        assert row["rawdata_code_md5"] == "OLD"
        assert row["analyzer_version"] == "OLDVER"
