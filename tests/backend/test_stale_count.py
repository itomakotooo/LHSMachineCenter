"""Tests for GET /api/reports/stale-count — fleet-wide staleness
banner backend. Seeds DB rows with varying (rawdata md5, analyzer
version) combinations and asserts the endpoint partitions them
correctly into stale_rawdata / stale_analyzer / fixable / untagged.

Honesty-3 update: the endpoint now uses effective_analyzer_version
(per-machine/mode) instead of the global analyzer_version for the
stale/fixable decision. Tests seed effective_analyzer_version so the
new comparator can fire. Rows without effective_analyzer_version are
"untagged" for the analyzer dimension (pre-honesty-3 legacy).
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
    effective: str | None = None,
    status: str = "completed",
) -> None:
    """Seed a completed run row. ``effective`` = effective_analyzer_version."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, machine, mode, status, model_id, created_at,
                started_at, target_halfwidth_pp, chunk_spin_times,
                chunk_robot_count, batch_concurrency, max_chunks, timeout,
                bankruptcy_session_spins, bankruptcy_bankroll_multipliers,
                report_version, output_dir, progress_file, summary_file,
                rawdata_config_md5, rawdata_code_md5, analyzer_version,
                effective_analyzer_version
            ) VALUES (
                ?, ?, ?, ?, 'sdk', '2026-01-01T00:00:00Z',
                '2026-01-01T00:00:00Z', 0.5, 5000,
                24, 2, 10, 30, 500, '100,200,500',
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                run_id, machine, mode, status,
                f"rv_{run_id}", f"/dir/{run_id}",
                f"/dir/{run_id}/p.jsonl", f"/dir/{run_id}/s.json",
                cfg, code, analyzer, effective,
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
    from fresh_slotlab.analyzer.versioning import compute_analyzer_version
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
    # honesty-3: the untagged check is `not row_cfg and not row_code and
    # not row_eff` — the legacy analyzer_version field no longer
    # participates. This row seeds cfg="" code="" and no effective → all
    # three empty → untagged bucket (neither stale nor fixable). The
    # non-empty legacy analyzer value is ignored by the comparator.
    assert resp["stale_analyzer"] == 0
    assert resp["fixable_count"] == 0


def _write_stub_chunk(rawdata_root: Path, machine: str, mode: int, cfg: str, code: str) -> None:
    """Write a minimal chunk file so check_rawdata_status finds usable rawdata.

    R-6: the stale-count endpoint calls check_rawdata_status to decide if a
    stale (machine, mode) is fixable (has usable rawdata) or needs-rawdata
    (no chunks on disk). Tests that expect fixable=1 must put at least one
    chunk file on disk with md5 values matching the machines.json entry.

    Chunk file uses _config_md5 / _code_md5 keys (the envelope format that
    check_rawdata_status's fallback reader uses when the sidecar is absent).
    """
    import json as _json  # noqa: PLC0415
    chunk_dir = rawdata_root / machine / f"mode_{mode}"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_data = {
        "_config_md5": cfg,
        "_code_md5": code,
        "_saved_at": "2026-01-01T00:00:00Z",
        "rounds": [],
    }
    (chunk_dir / "chunk_1.json").write_text(_json.dumps(chunk_data), encoding="utf-8")


def test_stale_count_analyzer_stale_fixable(
    tmp_state_dir, tmp_reports, tmp_cache, tmp_rawdata,
    fake_analyzer, tmp_path, monkeypatch,
):
    """Analyzer version drift + rawdata md5 match = fixable.

    Honesty-3: the staleness decision uses effective_analyzer_version (per-
    machine/mode), not the global analyzer_version. The row must have a non-
    current effective value for the endpoint to flag it stale. M15 has a
    SpinType-native manifest (configs/machine_manifests/M15.json) so the
    endpoint computes its real current effective; the row's "OLD_EFF" differs
    → stale + fixable.
    (5B: flat manifests deleted; M14 has no manifest anywhere and returns
    UNVERIFIABLE, so M15 is used instead.)
    R-6: a dummy chunk file is created so check_rawdata_status returns
    usable_chunks=1 → item goes to fixable_items (not needs_rawdata_items).
    """
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )
    # machines.json with real md5 values so rawdata md5 can match
    mc = tmp_path / "machines.json"
    _write_machines_config(mc, {"M15": ("CUR_CFG", "CUR_CODE")})

    from src.web_console.backend.app import create_app
    from fastapi.testclient import TestClient
    app = create_app(
        state_dir=tmp_state_dir, reports_root=tmp_reports, cache_root=tmp_cache,
        machines_config=mc, analyzer_path=fake_analyzer, rawdata_root=tmp_rawdata,
    )
    db_path = tmp_state_dir / "console.db"
    # Create a stub chunk so check_rawdata_status reports usable_chunks > 0.
    _write_stub_chunk(tmp_rawdata, "M15", 1, "CUR_CFG", "CUR_CODE")
    # Row: rawdata FRESH (matches), effective STALE (old hash != computed current)
    _seed_run(db_path, "r1", "M15", 1,
              cfg="CUR_CFG", code="CUR_CODE", analyzer="OLD_ANALYZER",
              effective="OLD_EFF_HASH_12")
    with TestClient(app) as c:
        resp = c.get("/api/reports/stale-count").json()
    assert resp["stale_analyzer"] == 1
    assert resp["stale_rawdata"] == 0
    assert resp["fixable_count"] == 1
    assert resp["fixable_items"] == [{"machine": "M15", "mode": 1}]


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
    from fresh_slotlab.analyzer.versioning import compute_analyzer_version
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
    only one fixable item (operator regenerates the mode once).

    Honesty-3: rows carry effective="OLD_EFF" which differs from the
    current M15 effective → all 3 rows are stale; deduped to 1 fixable.
    (5B: flat manifests deleted; M15 is used because it has a SpinType-native
    manifest at configs/machine_manifests/M15.json. M14 has no manifest and
    returns UNVERIFIABLE — always skipped by the staleness comparator.)
    R-6: dummy chunk present so item is fixable (not needs-rawdata).
    """
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )
    mc = tmp_path / "machines.json"
    _write_machines_config(mc, {"M15": ("CUR_CFG", "CUR_CODE")})
    from src.web_console.backend.app import create_app
    from fastapi.testclient import TestClient
    app = create_app(
        state_dir=tmp_state_dir, reports_root=tmp_reports, cache_root=tmp_cache,
        machines_config=mc, analyzer_path=fake_analyzer, rawdata_root=tmp_rawdata,
    )
    db_path = tmp_state_dir / "console.db"
    # Create a stub chunk so the R-6 check finds usable rawdata.
    _write_stub_chunk(tmp_rawdata, "M15", 1, "CUR_CFG", "CUR_CODE")
    for i in range(3):
        _seed_run(db_path, f"r{i}", "M15", 1,
                  cfg="CUR_CFG", code="CUR_CODE", analyzer="OLD",
                  effective="OLD_EFF_HASH_12")
    with TestClient(app) as c:
        resp = c.get("/api/reports/stale-count").json()
    assert resp["stale_analyzer"] == 3  # 3 rows stale
    assert resp["fixable_count"] == 1   # but dedup to 1 (machine, mode)
    assert resp["fixable_items"] == [{"machine": "M15", "mode": 1}]


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
