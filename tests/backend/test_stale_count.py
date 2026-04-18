"""Tests for GET /api/reports/stale-count — fleet-wide staleness
banner backend. Seeds DB rows with varying (rawdata md5, analyzer
version) combinations and asserts the endpoint partitions them
correctly into stale_rawdata / stale_analyzer / fixable / untagged.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _seed_run(
    db_path: Path,
    run_id: str,
    machine: str,
    mode: int,
    *,
    cfg: str | None,
    code: str | None,
    analyzer: str | None,
    status: str = "completed",
) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, machine, mode, status, model_id, created_at,
                started_at, target_halfwidth_pp, chunk_spin_times,
                chunk_robot_count, batch_concurrency, max_chunks, timeout,
                bankruptcy_session_spins, bankruptcy_bankroll_multipliers,
                report_version, output_dir, progress_file, summary_file,
                rawdata_config_md5, rawdata_code_md5, analyzer_version
            ) VALUES (
                ?, ?, ?, ?, 'sdk', '2026-01-01T00:00:00Z',
                '2026-01-01T00:00:00Z', 0.5, 5000,
                24, 2, 10, 30, 500, '100,200,500',
                ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                run_id, machine, mode, status,
                f"rv_{run_id}", f"/dir/{run_id}",
                f"/dir/{run_id}/p.jsonl", f"/dir/{run_id}/s.json",
                cfg, code, analyzer,
            ),
        )
        conn.commit()


def _write_machines_config(path: Path, machines: dict[str, tuple[str, str]]) -> None:
    path.write_text(json.dumps({
        "machines": [
            {
                "machine": m,
                "modes": [1, 2, 5, 7],
                "configSummaryMd5": cfg,
                "codeSummaryMd5": code,
            }
            for m, (cfg, code) in machines.items()
        ]
    }), encoding="utf-8")


def test_stale_count_all_fresh(client, app_factory):
    """Every run matches current machines.json + current analyzer → 0 stale."""
    c, _ = client
    from fresh_slotlab.player_impact_analyzer import compute_analyzer_version
    cur_analyzer = compute_analyzer_version()
    # Machine M14 is in the fake_machines fixture with empty md5s.
    # Seed a run with matching (empty) md5s + current analyzer.
    _seed_run(
        app_factory.db_path, "r1", "M14", 1,
        cfg="", code="", analyzer=cur_analyzer,
    )
    resp = c.get("/api/reports/stale-count").json()
    assert resp["total_completed_runs"] == 1
    assert resp["stale_rawdata"] == 0
    # Row has "" analyzer empty — but cur_analyzer is non-empty. Row is
    # tagged (has analyzer value). But empty cfg/code makes it untagged
    # in our counter... wait let me check:
    #   row_cfg="" row_code="" row_analyzer=cur_analyzer
    #   if not cfg and not code and not analyzer → untagged
    #   analyzer is set, so not untagged.
    # Then comparisons: rawdata_is_stale requires (row_cfg or row_code) — both empty → False
    # analyzer_is_stale: row_analyzer == cur → False
    # So row is neither stale nor fixable.
    assert resp["stale_analyzer"] == 0
    assert resp["fixable_count"] == 0


def test_stale_count_analyzer_stale_fixable(
    tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
    fake_analyzer, tmp_path, monkeypatch,
):
    """Analyzer version drift + rawdata md5 match = fixable."""
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )
    # machines.json with real md5 values so rawdata md5 can match
    mc = tmp_path / "machines.json"
    _write_machines_config(mc, {"M14": ("CUR_CFG", "CUR_CODE")})

    from src.web_console.backend.app import create_app
    from fastapi.testclient import TestClient
    from fresh_slotlab.player_impact_analyzer import compute_analyzer_version
    cur_analyzer = compute_analyzer_version()
    app = create_app(
        state_dir=tmp_state_dir, reports_root=tmp_reports, cache_root=tmp_cache,
        machines_config=mc, analyzer_path=fake_analyzer, rawdata_root=tmp_rawdata,
    )
    db_path = tmp_state_dir / "console.db"
    # Row: rawdata FRESH (matches), analyzer STALE (old hash)
    _seed_run(db_path, "r1", "M14", 1,
              cfg="CUR_CFG", code="CUR_CODE", analyzer="OLD_ANALYZER")
    with TestClient(app) as c:
        resp = c.get("/api/reports/stale-count").json()
    assert resp["stale_analyzer"] == 1
    assert resp["stale_rawdata"] == 0
    assert resp["fixable_count"] == 1
    assert resp["fixable_items"] == [{"machine": "M14", "mode": 1}]


def test_stale_count_rawdata_stale_not_fixable(
    tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
    fake_analyzer, tmp_path, monkeypatch,
):
    """Rawdata stale = operator must resample; not batch-fixable even
    if analyzer is also stale."""
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )
    mc = tmp_path / "machines.json"
    _write_machines_config(mc, {"M14": ("CUR_CFG", "CUR_CODE")})
    from src.web_console.backend.app import create_app
    from fastapi.testclient import TestClient
    from fresh_slotlab.player_impact_analyzer import compute_analyzer_version
    cur_analyzer = compute_analyzer_version()
    app = create_app(
        state_dir=tmp_state_dir, reports_root=tmp_reports, cache_root=tmp_cache,
        machines_config=mc, analyzer_path=fake_analyzer, rawdata_root=tmp_rawdata,
    )
    db_path = tmp_state_dir / "console.db"
    # Row: rawdata STALE (OLD_* doesn't match CUR_*), analyzer fresh
    _seed_run(db_path, "r1", "M14", 1,
              cfg="OLD_CFG", code="OLD_CODE", analyzer=cur_analyzer)
    with TestClient(app) as c:
        resp = c.get("/api/reports/stale-count").json()
    assert resp["stale_rawdata"] == 1
    assert resp["stale_analyzer"] == 0
    # Not fixable — rawdata drift means resample, batch-regen can't help
    assert resp["fixable_count"] == 0


def test_stale_count_fixable_deduped_by_machine_mode(
    tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
    fake_analyzer, tmp_path, monkeypatch,
):
    """Three runs for the same (machine, mode) all stale-analyzer →
    only one fixable item (operator regenerates the mode once)."""
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )
    mc = tmp_path / "machines.json"
    _write_machines_config(mc, {"M14": ("CUR_CFG", "CUR_CODE")})
    from src.web_console.backend.app import create_app
    from fastapi.testclient import TestClient
    app = create_app(
        state_dir=tmp_state_dir, reports_root=tmp_reports, cache_root=tmp_cache,
        machines_config=mc, analyzer_path=fake_analyzer, rawdata_root=tmp_rawdata,
    )
    db_path = tmp_state_dir / "console.db"
    for i in range(3):
        _seed_run(db_path, f"r{i}", "M14", 1,
                  cfg="CUR_CFG", code="CUR_CODE", analyzer="OLD")
    with TestClient(app) as c:
        resp = c.get("/api/reports/stale-count").json()
    assert resp["stale_analyzer"] == 3  # 3 rows stale
    assert resp["fixable_count"] == 1   # but dedup to 1 (machine, mode)
    assert resp["fixable_items"] == [{"machine": "M14", "mode": 1}]


def test_stale_count_untagged_rows_separate_bucket(
    tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
    fake_machines, fake_analyzer, monkeypatch,
):
    """Pre-migration rows with no fingerprints at all → untagged
    (neither stale nor fixable)."""
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )
    from src.web_console.backend.app import create_app
    from fastapi.testclient import TestClient
    app = create_app(
        state_dir=tmp_state_dir, reports_root=tmp_reports, cache_root=tmp_cache,
        machines_config=fake_machines, analyzer_path=fake_analyzer,
        rawdata_root=tmp_rawdata,
    )
    db_path = tmp_state_dir / "console.db"
    _seed_run(db_path, "r1", "M14", 1, cfg=None, code=None, analyzer=None)
    with TestClient(app) as c:
        resp = c.get("/api/reports/stale-count").json()
    assert resp["untagged"] == 1
    assert resp["stale_analyzer"] == 0
    assert resp["stale_rawdata"] == 0
    assert resp["fixable_count"] == 0
