"""Tests for ``GET /api/reports/{machine}/{mode}`` md5 filtering.

User report 2026-04-26: pulled fresh rawdata (cfg=NEW), but the
rawdata-detail panel still listed reports generated against historical
md5 versions (cfg=OLD). Expected: each rawdata version surfaces only
its own reports.

Architecture:
  - Reports' summary.json carries ``config_md5`` + ``code_md5`` since
    2026-04-21 (rawdata-md5 stamping).
  - The list endpoint reads ``index.json`` which is a thin per-version
    manifest. Pre-2026-04-26, index entries DIDN'T include those
    fields, so the endpoint had no way to filter.
  - Fix: index entries now stamp ``rawdata_config_md5`` /
    ``rawdata_code_md5`` / ``analyzer_version``. The list endpoint
    accepts ``?config_md5=&code_md5=`` query params; missing/empty
    md5 on a row counts as "untagged" and is preserved in the
    filtered view (we can't prove it doesn't belong, dropping it
    would hide data the operator may want to see).

These tests pin the filter contract so future refactors don't
regress untagged-report visibility or quietly drop md5-mismatched
ones from the include_historical=true escape hatch.
"""
from __future__ import annotations

import json
from pathlib import Path


def _write_version(reports_root: Path, machine: str, mode: int,
                   version: str, *, cfg_md5: str = "", code_md5: str = "",
                   analyzer_version: str = "") -> Path:
    vdir = reports_root / machine / f"mode_{mode}" / "versions" / version
    vdir.mkdir(parents=True, exist_ok=True)
    summary = {
        "config_md5": cfg_md5,
        "code_md5": code_md5,
        "analyzer_version": analyzer_version,
        "sampling": {"total_spins": 100_000, "achieved_halfwidth_pp": 0.5},
        "rtp": {"point_pct": 95.0},
        "guideline_assessment": {"data_quality": {"quality_label": "EXPLORATORY"}},
    }
    (vdir / "player_impact_summary.json").write_text(
        json.dumps(summary), encoding="utf-8",
    )
    return vdir


def _write_index(reports_root: Path, machine: str, mode: int,
                 entries: list[dict]) -> None:
    mode_dir = reports_root / machine / f"mode_{mode}"
    mode_dir.mkdir(parents=True, exist_ok=True)
    (mode_dir / "index.json").write_text(
        json.dumps(entries, indent=2), encoding="utf-8",
    )


# ── Filter behavior on a mixed-md5 index ──────────────────────────────


class TestMd5FilterBasic:
    def test_no_filter_returns_everything(self, tmp_reports, client):
        """No query params → unfiltered (back-compat)."""
        c, _ = client
        for rv, cfg in [
            ("rv_001_oldcfg", "OLD_CFG"),
            ("rv_002_newcfg", "NEW_CFG"),
            ("rv_003_legacy", ""),
        ]:
            _write_version(tmp_reports, "M14", 1, rv,
                           cfg_md5=cfg, code_md5="CODE")
        _write_index(tmp_reports, "M14", 1, [
            {"report_version": "rv_001_oldcfg",
             "summary_file": str(tmp_reports / "M14/mode_1/versions/rv_001_oldcfg/player_impact_summary.json"),
             "rawdata_config_md5": "OLD_CFG", "rawdata_code_md5": "CODE"},
            {"report_version": "rv_002_newcfg",
             "summary_file": str(tmp_reports / "M14/mode_1/versions/rv_002_newcfg/player_impact_summary.json"),
             "rawdata_config_md5": "NEW_CFG", "rawdata_code_md5": "CODE"},
            {"report_version": "rv_003_legacy",
             "summary_file": str(tmp_reports / "M14/mode_1/versions/rv_003_legacy/player_impact_summary.json"),
             "rawdata_config_md5": "", "rawdata_code_md5": ""},
        ])

        r = c.get("/api/reports/M14/1")
        assert r.status_code == 200
        body = r.json()
        assert len(body["versions"]) == 3
        assert body["filter"]["total_unfiltered"] == 3
        assert body["filter"]["total_filtered"] == 3

    def test_config_md5_filter_drops_mismatched_rows(self, tmp_reports, client):
        """``?config_md5=NEW_CFG`` keeps NEW_CFG + untagged, drops OLD_CFG."""
        c, _ = client
        for rv, cfg in [
            ("rv_001_oldcfg", "OLD_CFG"),
            ("rv_002_newcfg", "NEW_CFG"),
            ("rv_003_legacy", ""),
        ]:
            _write_version(tmp_reports, "M14", 1, rv,
                           cfg_md5=cfg, code_md5="CODE")
        _write_index(tmp_reports, "M14", 1, [
            {"report_version": "rv_001_oldcfg",
             "summary_file": str(tmp_reports / "M14/mode_1/versions/rv_001_oldcfg/player_impact_summary.json"),
             "rawdata_config_md5": "OLD_CFG", "rawdata_code_md5": "CODE"},
            {"report_version": "rv_002_newcfg",
             "summary_file": str(tmp_reports / "M14/mode_1/versions/rv_002_newcfg/player_impact_summary.json"),
             "rawdata_config_md5": "NEW_CFG", "rawdata_code_md5": "CODE"},
            {"report_version": "rv_003_legacy",
             "summary_file": str(tmp_reports / "M14/mode_1/versions/rv_003_legacy/player_impact_summary.json"),
             "rawdata_config_md5": "", "rawdata_code_md5": ""},
        ])

        r = c.get("/api/reports/M14/1?config_md5=NEW_CFG")
        assert r.status_code == 200
        body = r.json()
        kept = {v["report_version"] for v in body["versions"]}
        # NEW_CFG match + legacy untagged (we can't prove it doesn't belong).
        # OLD_CFG explicitly dropped.
        assert "rv_002_newcfg" in kept
        assert "rv_003_legacy" in kept
        assert "rv_001_oldcfg" not in kept
        assert body["filter"]["config_md5"] == "NEW_CFG"
        assert body["filter"]["total_unfiltered"] == 3
        assert body["filter"]["total_filtered"] == 2

    def test_include_historical_overrides_filter(self, tmp_reports, client):
        """``?include_historical=true`` short-circuits the filter so
        run-history views still see the full ledger."""
        c, _ = client
        _write_version(tmp_reports, "M14", 1, "rv_001",
                       cfg_md5="OLD", code_md5="CODE")
        _write_version(tmp_reports, "M14", 1, "rv_002",
                       cfg_md5="NEW", code_md5="CODE")
        _write_index(tmp_reports, "M14", 1, [
            {"report_version": "rv_001",
             "summary_file": str(tmp_reports / "M14/mode_1/versions/rv_001/player_impact_summary.json"),
             "rawdata_config_md5": "OLD", "rawdata_code_md5": "CODE"},
            {"report_version": "rv_002",
             "summary_file": str(tmp_reports / "M14/mode_1/versions/rv_002/player_impact_summary.json"),
             "rawdata_config_md5": "NEW", "rawdata_code_md5": "CODE"},
        ])

        r = c.get("/api/reports/M14/1?config_md5=NEW&include_historical=true")
        assert r.status_code == 200
        body = r.json()
        assert len(body["versions"]) == 2  # OLD not dropped
        assert body["filter"]["include_historical"] is True

    def test_code_md5_filter_independent_of_config(self, tmp_reports, client):
        """``?code_md5=`` alone treats config_md5 as wildcard (operator
        targeting analyzer-code drift only)."""
        c, _ = client
        _write_version(tmp_reports, "M14", 1, "rv_001",
                       cfg_md5="CFG", code_md5="OLD_CODE")
        _write_version(tmp_reports, "M14", 1, "rv_002",
                       cfg_md5="CFG", code_md5="NEW_CODE")
        _write_index(tmp_reports, "M14", 1, [
            {"report_version": "rv_001",
             "summary_file": str(tmp_reports / "M14/mode_1/versions/rv_001/player_impact_summary.json"),
             "rawdata_config_md5": "CFG", "rawdata_code_md5": "OLD_CODE"},
            {"report_version": "rv_002",
             "summary_file": str(tmp_reports / "M14/mode_1/versions/rv_002/player_impact_summary.json"),
             "rawdata_config_md5": "CFG", "rawdata_code_md5": "NEW_CODE"},
        ])

        r = c.get("/api/reports/M14/1?code_md5=NEW_CODE")
        body = r.json()
        kept = {v["report_version"] for v in body["versions"]}
        assert kept == {"rv_002"}


# ── Backfill behavior for legacy index.json without md5 fields ────────


class TestMd5BackfillFromSummary:
    def test_legacy_index_without_md5_fields_gets_backfilled(
        self, tmp_reports, client,
    ):
        """Pre-2026-04-26 index.json rows lack rawdata_config_md5 /
        rawdata_code_md5. The endpoint backfills them by reading the
        summary file once. The next response shows the fields stamped
        in-memory (the index.json file itself isn't touched — that's
        a writer-side responsibility on next ``index_payload.append``).
        """
        c, _ = client
        rv = "rv_legacy_no_md5"
        _write_version(tmp_reports, "M14", 1, rv,
                       cfg_md5="STAMPED_CFG", code_md5="STAMPED_CODE",
                       analyzer_version="abc123")
        # Index entry omits md5 fields entirely (legacy format).
        _write_index(tmp_reports, "M14", 1, [{
            "report_version": rv,
            "summary_file": str(tmp_reports / f"M14/mode_1/versions/{rv}/player_impact_summary.json"),
            "rtp_point_pct": 95.0,
        }])

        r = c.get("/api/reports/M14/1?config_md5=STAMPED_CFG")
        body = r.json()
        # Despite missing md5 in index.json, the endpoint backfilled
        # from the summary file and the row IS kept by the filter.
        kept = {v["report_version"] for v in body["versions"]}
        assert rv in kept
        # The returned row has the backfilled md5 fields populated.
        v = body["versions"][0]
        assert v["rawdata_config_md5"] == "STAMPED_CFG"
        assert v["rawdata_code_md5"] == "STAMPED_CODE"
        assert v["analyzer_version"] == "abc123"

    def test_summary_missing_treated_as_untagged(self, tmp_reports, client):
        """Index points at a summary that doesn't exist on disk
        (zombie row, partial cleanup). Endpoint shouldn't crash and
        the row should be treated as untagged → kept under any
        config_md5 filter (we'd rather show a maybe-stale row than
        silently hide data)."""
        c, _ = client
        _write_index(tmp_reports, "M14", 1, [{
            "report_version": "rv_zombie",
            "summary_file": str(tmp_reports / "M14/mode_1/versions/rv_zombie/player_impact_summary.json"),
            "rtp_point_pct": 95.0,
        }])
        r = c.get("/api/reports/M14/1?config_md5=ANY_MD5")
        body = r.json()
        assert {v["report_version"] for v in body["versions"]} == {"rv_zombie"}
