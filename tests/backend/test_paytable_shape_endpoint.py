"""Tests for /api/paytables/{machine}/mode/{mode}/shape — per-pay_id
shape inference + auto-inferred wild set produced by
scripts/infer_paytable.py. Data lives under configs/paytables/ in
production. Tests stub the directory with fixtures so the endpoint can
be exercised without rawdata.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web_console.backend.app import create_app, _load_paytable_shape


@pytest.fixture
def paytables_tmp(tmp_path: Path) -> Path:
    d = tmp_path / "configs" / "paytables"
    d.mkdir(parents=True)
    return d


def _write_paytable(dir_: Path, machine: str, mode: int, payload: dict) -> None:
    (dir_ / f"{machine}_mode{mode}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _minimal_row(pay_id: int, mc: int, sym_set: list[str], conf: str = "high") -> dict:
    return {
        "pay_id": pay_id,
        "match_count": mc,
        "fires": 100,
        "line_ids_fired": [1, 2, 3, 4, 5, 6, 7, 8, 9],
        "shape": {
            "match_count": mc,
            "symbol_set": sym_set,
            "symbol_purity": 1.0,
            "wild_substitution_rate": 0.2,
            "line_id_sign": "positive",
            "line_ids_positive": [1, 2, 3, 4, 5, 6, 7, 8, 9],
            "line_ids_negative": [],
            "position_cols_covered": [0, 1, 2],
            "position_rows_covered": [0, 1, 2],
            "position_spans_full_grid": False,
            "position_pattern_samples": [[[0, 1], [1, 1], [2, 1]]],
            "fires": 100,
            "confidence": conf,
            "notes": [],
            "alt_signatures": [{"symbol": "+".join(sym_set), "sig_type": "pure", "count": 100}],
        },
        "dominant_symbol": sym_set[0] if sym_set else None,
        "signature_type": "pure",
        "symbol_purity": 1.0,
        "avg_mult_x_bet": 0.5,
        "win_total": 5000,
        "win_source": "PayoutIdToWinAmount",
        "base_mult_no_wild_anywhere": 0.5,
        "wild_rate": 0.2,
        "wild_behavior": {},
    }


@pytest.fixture
def paytable_client(
    tmp_state_dir, tmp_reports, tmp_cache, fake_machines, fake_analyzer,
    paytables_tmp, monkeypatch,
):
    monkeypatch.setattr(
        "src.web_console.backend.app._terminate_pid_if_running",
        lambda pid: True,
    )
    app = create_app(
        state_dir=tmp_state_dir,
        reports_root=tmp_reports,
        cache_root=tmp_cache,
        machines_config=fake_machines,
        analyzer_path=fake_analyzer,
        paytables_dir=paytables_tmp,
    )
    with TestClient(app) as c:
        yield c, paytables_tmp


class TestPaytableShapeEndpointHappyPath:
    def test_returns_shape_and_wild_inference(self, paytable_client):
        c, pt_dir = paytable_client
        _write_paytable(pt_dir, "M14", 1, {
            "machine": "M14", "mode": 1, "chunks_scanned": 1,
            "grid": {"n_cols": 3, "n_rows": 3},
            "wild_inference": {
                "status": "inferred",
                "wilds": ["5x_wild", "7x_wild"],
                "evidence": {
                    "5x_wild": {
                        "confidence": "high",
                        "substitutes_count": 3, "paying_count": 0,
                        "mono_count": 0, "wild_score": 3.0,
                        "name_hint": True,
                        "reason": "substitutes in 3 pay_ids",
                    },
                },
                "tier_stems": {"wild": ["5x_wild", "7x_wild"]},
                "review_needed": False,
                "stem_count": 1,
            },
            "paytable_rows": [_minimal_row(2, 3, ["high7"]),
                              _minimal_row(3, 3, ["3bar"])],
            "per_line_breakdown": {},
            "self_verify": {"total_rows": 2, "high_confidence_rows": 2,
                            "low_confidence_rows": 0, "warnings": [],
                            "machine_flags": []},
        })
        resp = c.get("/api/paytables/M14/mode/1/shape")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["machine"] == "M14"
        assert body["mode"] == 1
        assert body["grid"] == {"n_cols": 3, "n_rows": 3}
        # Wild inference passthrough.
        assert body["wild_inference"]["status"] == "inferred"
        assert body["wild_inference"]["wilds"] == ["5x_wild", "7x_wild"]
        assert body["wild_inference"]["review_needed"] is False
        # Rows have shape field with the structural features UI needs.
        assert len(body["rows"]) == 2
        first = body["rows"][0]
        assert first["pay_id"] == 2
        assert first["shape"]["symbol_set"] == ["high7"]
        assert first["shape"]["line_id_sign"] == "positive"
        assert first["shape"]["confidence"] == "high"

    def test_review_needed_flag_surfaces(self, paytable_client):
        """Complex-paytable machine where the wild inferrer flagged the
        result for manual review. UI uses this to warn operator."""
        c, pt_dir = paytable_client
        _write_paytable(pt_dir, "M34", 1, {
            "machine": "M34", "mode": 1, "chunks_scanned": 1,
            "grid": {"n_cols": 3, "n_rows": 3},
            "wild_inference": {
                "status": "inferred",
                "wilds": ["Bar1", "Bar2", "High7", "Wildx2"],
                "evidence": {},
                "tier_stems": {},
                "review_needed": True,
                "stem_count": 4,
            },
            "paytable_rows": [_minimal_row(1, 3, ["Bar1"])],
            "per_line_breakdown": {},
            "self_verify": {
                "total_rows": 1, "high_confidence_rows": 0,
                "low_confidence_rows": 1, "warnings": [],
                "machine_flags": ["wild_inference_review_needed (4 candidates across 4 symbol families)"],
            },
        })
        resp = c.get("/api/paytables/M34/mode/1/shape")
        assert resp.status_code == 200
        body = resp.json()
        assert body["wild_inference"]["review_needed"] is True
        assert body["wild_inference"]["stem_count"] == 4
        # machine_flags propagate so UI banner can render.
        assert any(
            "review_needed" in f for f in body["machine_flags"]
        )


class TestPaytableShapeEndpointMissing:
    def test_file_not_found_returns_not_run(self, paytable_client):
        """Operator never ran infer_paytable for this machine — endpoint
        stays 200 with ``status=not_run`` so UI renders a gentle prompt
        instead of erroring."""
        c, _ = paytable_client
        resp = c.get("/api/paytables/M9999/mode/1/shape")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "not_run"
        assert body["rows"] == []
        assert body["wild_inference"] is None

    def test_paytables_dir_missing_returns_not_run(
        self, tmp_state_dir, tmp_reports, tmp_cache, fake_machines, fake_analyzer,
        tmp_path, monkeypatch,
    ):
        monkeypatch.setattr(
            "src.web_console.backend.app._terminate_pid_if_running",
            lambda pid: True,
        )
        missing_dir = tmp_path / "never_created"
        app = create_app(
            state_dir=tmp_state_dir,
            reports_root=tmp_reports,
            cache_root=tmp_cache,
            machines_config=fake_machines,
            analyzer_path=fake_analyzer,
            paytables_dir=missing_dir,
        )
        with TestClient(app) as c:
            resp = c.get("/api/paytables/M14/mode/1/shape")
            assert resp.status_code == 200
            assert resp.json()["status"] == "not_run"

    def test_corrupted_json_returns_error_status(self, paytable_client):
        c, pt_dir = paytable_client
        (pt_dir / "M14_mode1.json").write_text(
            "{ this is not valid json", encoding="utf-8",
        )
        resp = c.get("/api/paytables/M14/mode/1/shape")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"


class TestLoadPaytableShapeHelper:
    def test_drops_mult_fields_from_rows(self, tmp_path):
        """Helper keeps ``shape`` + ``line_ids_fired`` on each row but
        drops the legacy mult fields (avg_mult_x_bet, win_total, etc.)
        — shape-only UI doesn't need them."""
        d = tmp_path / "pt"
        d.mkdir()
        _write_paytable(d, "M1", 1, {
            "machine": "M1", "mode": 1, "chunks_scanned": 1,
            "grid": {"n_cols": 3, "n_rows": 3},
            "wild_inference": {
                "status": "inferred", "wilds": [], "evidence": {},
                "tier_stems": {}, "review_needed": False, "stem_count": 0,
            },
            "paytable_rows": [_minimal_row(5, 3, ["cherry"])],
            "per_line_breakdown": {},
            "self_verify": {"total_rows": 1, "high_confidence_rows": 1,
                            "low_confidence_rows": 0, "warnings": [],
                            "machine_flags": []},
        })
        out = _load_paytable_shape("M1", 1, d)
        assert out["rows"][0].keys() == {
            "pay_id", "match_count", "fires", "avg_win", "line_ids_fired", "shape",
        }
