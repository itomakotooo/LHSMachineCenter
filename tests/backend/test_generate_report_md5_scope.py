"""Regression: md5-scoped generate-report must (a) feed the engine ONLY the
selected chunks and (b) stamp the summary with the SOURCE-chunk md5 pair.

The 2026-06-11 M279 defect pair this locks down:
  B. SCOPE — the engine has no md5 filter (it parses every chunk_*.json in
     chunk_dir). _run_generate_report validated the md5 selection but then
     passed the WHOLE mode dir, so a historical-cell "生成 Report" on a
     mixed-md5 dir silently widened to ALL chunks (a 40-chunk request
     produced a 48-chunk report mixing two configs).
  C. STAMP — the summary's md5 tags came from the CURRENT roster regardless
     of source chunks, so a report generated FROM historical rawdata landed
     in the rwtree's "当前" cell while its source chunks sat in a "历史"
     cell (and 当前 showed 无本地 rawdata).

Style per feedback_integration_test_argv: assert what the ENGINE actually
RECEIVES (the chunk_dir contents), not just endpoint flags. The engine is
stubbed (no parsing) — chunks here are md5-envelope fixtures only — and the
stub deliberately writes a WRONG roster-style stamp so the provenance
override is what the assertion proves.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.web_console.backend.app as app_module
from src.web_console.backend.app import create_app

CFG_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # historical config (2 chunks)
CFG_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"  # current  config (1 chunk)
CODE_Z = "cccccccccccccccccccccccccccccccc"  # shared code md5


def _write_chunk(path: Path, idx: int, cfg: str) -> None:
    path.write_text(json.dumps({
        "_machine": "MTEST", "_mode": 1, "_chunk_index": idx,
        "_config_md5": cfg, "_code_md5": CODE_Z,
        "_spin_times": 1000, "_robot_count": 1, "_bet": 1000,
        "_cache_version": 3,
        "_saved_at": "2026-06-01T00:00:00Z",
        "response": [],
    }), encoding="utf-8")


@pytest.fixture
def scoped_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """App over a synthetic mixed-md5 rawdata dir + a stubbed engine.

    Rawdata MTEST/mode_1: chunk_0001/0002 = CFG_A (historical),
    chunk_0003 = CFG_B (current per roster). Engine stub records the
    chunk_dir it receives and writes a summary stamped with a WRONG
    roster-style md5 pair (simulating the real engine's behavior).
    """
    state_dir = tmp_path / "state"; state_dir.mkdir(); (state_dir / "progress").mkdir()
    reports_dir = tmp_path / "reports"; reports_dir.mkdir()
    rd_root = tmp_path / "rawdata"
    mode_dir = rd_root / "MTEST" / "mode_1"; mode_dir.mkdir(parents=True)
    _write_chunk(mode_dir / "chunk_0001.json", 1, CFG_A)
    _write_chunk(mode_dir / "chunk_0002.json", 2, CFG_A)
    _write_chunk(mode_dir / "chunk_0003.json", 3, CFG_B)

    mc = tmp_path / "machines.json"
    mc.write_text(json.dumps({"machines": [{
        "machine": "MTEST", "modes": [1],
        "configSummaryMd5": CFG_B, "codeSummaryMd5": CODE_Z,
    }]}), encoding="utf-8")

    # Registered-check + the scoped-dir parent both resolve via app_module.ROOT.
    # Point ROOT at tmp so the manifest lives in an isolated tree and scoped
    # hardlink dirs land under tmp (auto-cleaned).
    manifests = tmp_path / "configs" / "machine_manifests"
    manifests.mkdir(parents=True)
    (manifests / "MTEST.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_module, "ROOT", tmp_path)

    # Engine stub: record chunk_dir contents; write a summary with a WRONG
    # (roster-style) stamp so only the provenance override can make it right.
    calls: list[dict] = []
    def _stub_engine(machine_id, mode, *, chunk_dir, output_dir, bet=1,
                     run_id=None, manifests_root=None, manifest_machine_id=None):
        chunk_dir = Path(chunk_dir)
        calls.append({
            "chunk_dir": chunk_dir,
            "chunks": sorted(p.name for p in chunk_dir.glob("chunk_*.json")),
            "bet": bet,
        })
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "player_impact_summary.json").write_text(json.dumps({
            "machine": machine_id, "mode": mode,
            "config_md5": "ROSTERSTAMPWRONG", "code_md5": "ROSTERSTAMPWRONG",
            "analyzer_version": "stub",
            "rtp": {"point_pct": 50.0},
            "sampling": {"bet": bet, "total_spins": 1000,
                         "achieved_halfwidth_pp": 1.0},
            "guideline_assessment": {"data_quality": {"quality_label": "STUB"}},
            "player_impact": {}, "rtp_integrity_check": {"passed": True},
        }), encoding="utf-8")
        (out / "player_impact_report.md").write_text("stub", encoding="utf-8")
        return {}
    import fresh_slotlab.analyzer.report_engine as engine_mod
    monkeypatch.setattr(engine_mod, "generate_report_from_chunks", _stub_engine)

    monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
    app = create_app(state_dir=state_dir, reports_root=reports_dir,
                     machines_config=mc, rawdata_root=rd_root)
    with TestClient(app) as client:
        yield client, reports_dir, calls


def _summary_for(reports_dir: Path, resp: dict) -> dict:
    ver = resp["report_version"]
    sf = reports_dir / "MTEST" / "mode_1" / "versions" / ver / "player_impact_summary.json"
    assert sf.exists(), f"summary not written for {ver}"
    return json.loads(sf.read_text(encoding="utf-8"))


class TestMd5ScopedGeneration:
    def test_historical_filter_scopes_engine_to_matching_chunks_only(self, scoped_client):
        """The engine must receive ONLY the 2 CFG_A chunks, in a scoped dir."""
        client, _reports, calls = scoped_client
        r = client.post("/api/rawdata/MTEST/generate-report",
                        json={"mode": 1, "config_md5": CFG_A, "code_md5": CODE_Z})
        assert r.status_code == 200, r.text
        assert len(calls) == 1
        call = calls[0]
        assert call["chunks"] == ["chunk_0001.json", "chunk_0002.json"], (
            "engine saw the wrong chunk set — the md5 scope leaked "
            f"(got {call['chunks']})"
        )
        assert call["chunk_dir"].name != "mode_1", (
            "engine was handed the raw mode dir, not a scoped dir"
        )

    def test_historical_filter_stamps_summary_with_source_md5(self, scoped_client):
        """Summary md5 = the FILTER pair (provenance), not the roster stamp."""
        client, reports_dir, _calls = scoped_client
        r = client.post("/api/rawdata/MTEST/generate-report",
                        json={"mode": 1, "config_md5": CFG_A, "code_md5": CODE_Z})
        assert r.status_code == 200, r.text
        s = _summary_for(reports_dir, r.json())
        assert s["config_md5"] == CFG_A
        assert s["code_md5"] == CODE_Z

    def test_default_path_scopes_to_current_chunks(self, scoped_client):
        """No filter -> usable = current-md5 chunks only (CFG_B), still scoped."""
        client, reports_dir, calls = scoped_client
        r = client.post("/api/rawdata/MTEST/generate-report", json={"mode": 1})
        assert r.status_code == 200, r.text
        assert calls[-1]["chunks"] == ["chunk_0003.json"], (
            f"default path leaked historical chunks: {calls[-1]['chunks']}"
        )
        s = _summary_for(reports_dir, r.json())
        assert s["config_md5"] == CFG_B
        assert s["code_md5"] == CODE_Z

    def test_chunk_bet_passed_to_engine(self, scoped_client):
        """The engine receives the chunks' _bet, not the default 1 (the 1000x
        inflated-multiplier display trap)."""
        client, _reports, calls = scoped_client
        r = client.post("/api/rawdata/MTEST/generate-report",
                        json={"mode": 1, "config_md5": CFG_A, "code_md5": CODE_Z})
        assert r.status_code == 200, r.text
        assert calls[-1]["bet"] == 1000

    def test_scoped_dir_cleaned_up(self, scoped_client, tmp_path: Path):
        """The hardlink scratch dir must not survive the request."""
        client, _reports, _calls = scoped_client
        r = client.post("/api/rawdata/MTEST/generate-report",
                        json={"mode": 1, "config_md5": CFG_A, "code_md5": CODE_Z})
        assert r.status_code == 200, r.text
        scope_root = tmp_path / "cache" / "_gen_scope"
        leftovers = list(scope_root.glob("*")) if scope_root.exists() else []
        assert leftovers == [], f"scoped dirs leaked: {leftovers}"
