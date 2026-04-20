"""Tests for /api/classifier/{machine} — per-mode payline-structure
classification + channel split + feature-mode delta from the
classifier output produced by scripts/classify_payline_structure.py.

Data lives under dev_reports/_classify/all_verdicts_mode<N>.json
in production. Tests stub the directory with fixtures so the
endpoint can be exercised without the 9 GB rawdata present.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web_console.backend.app import create_app, _load_classifier_verdict


@pytest.fixture
def classify_tmp(tmp_path: Path) -> Path:
    d = tmp_path / "dev_reports" / "_classify"
    d.mkdir(parents=True)
    return d


def _write_mode(dir_: Path, mode: int, verdicts: list[dict]) -> None:
    (dir_ / f"all_verdicts_mode{mode}.json").write_text(
        json.dumps({
            "mode": mode,
            "n_machines": len(verdicts),
            "n_resolved": sum(1 for v in verdicts if v.get("all_resolved")),
            "n_unresolved": 0,
            "verdicts": verdicts,
        }, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.fixture
def classifier_client(
    tmp_state_dir, tmp_reports, tmp_cache, fake_machines, fake_analyzer,
    classify_tmp, monkeypatch,
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
        classify_dir=classify_tmp,
    )
    with TestClient(app) as c:
        yield c, classify_tmp


class TestClassifierEndpointHappyPath:
    def test_returns_per_mode_verdict_for_machine(self, classifier_client):
        c, classify_dir = classifier_client
        _write_mode(classify_dir, 1, [
            {
                "machine": "M273",
                "machine_label": "classic-payline [flexible]",
                "paid_spin_type": 140,
                "all_resolved": True,
                "per_st_verdicts": {
                    "140": {
                        "is_paid": True,
                        "classification": {"bucket": "classic-payline [flexible]"},
                        "channel": "pay_id",
                        "explanation": "pay_id accounts for 100.0% of wins",
                    },
                },
                "feature_delta_from_paid": {},
                "feature_tally_keys": ["NormalCollectionSpin", "LockSymbolFreespin"],
                "grid": {"n_cols": 5, "n_rows": 3},
            },
        ])
        _write_mode(classify_dir, 7, [
            {
                "machine": "M273",
                "machine_label": "classic-payline [flexible]",
                "paid_spin_type": 140,
                "all_resolved": True,
                "per_st_verdicts": {
                    "140": {
                        "is_paid": True,
                        "classification": {"bucket": "classic-payline [flexible]"},
                        "channel": "pay_id",
                        "explanation": "pay_id accounts for 100.0% of wins",
                    },
                },
                "feature_delta_from_paid": {},
                "feature_tally_keys": ["NormalCollectionSpin", "LockSymbolFreespin"],
                "grid": {"n_cols": 5, "n_rows": 3},
            },
        ])
        resp = c.get("/api/classifier/M273")
        assert resp.status_code == 200
        body = resp.json()
        assert body["machine"] == "M273"
        assert set(body["modes"].keys()) == {"1", "7"}
        assert body["modes"]["1"]["machine_label"] == "classic-payline [flexible]"
        assert body["modes"]["1"]["paid_spin_type"] == 140
        assert body["modes"]["1"]["grid"] == {"n_cols": 5, "n_rows": 3}
        # Channel surfaces per SpinType — the whole point of item #3.
        assert body["modes"]["1"]["per_st_verdicts"]["140"]["channel"] == "pay_id"

    def test_preserves_feature_mode_rule_delta(self, classifier_client):
        c, classify_dir = classifier_client
        # Hybrid machine where bonus ST adds a negative line_id relative
        # to paid — this IS the feature-mode-rule-delta flag UI needs.
        _write_mode(classify_dir, 1, [
            {
                "machine": "M22",
                "machine_label": "hybrid (payline+board) [strict-ltr]",
                "paid_spin_type": 27,
                "all_resolved": True,
                "per_st_verdicts": {
                    "27": {
                        "is_paid": True,
                        "classification": {"bucket": "classic-payline [strict-ltr]"},
                        "channel": "pay_id",
                    },
                    "29": {
                        "is_paid": False,
                        "classification": {"bucket": "hybrid (payline+board) [strict-ltr]"},
                        "channel": "pay_id",
                    },
                },
                "feature_delta_from_paid": {"29": {"added": [], "removed": [-1]}},
                "feature_tally_keys": ["Normal"],
            },
        ])
        resp = c.get("/api/classifier/M22")
        assert resp.status_code == 200
        body = resp.json()
        assert body["modes"]["1"]["feature_delta_from_paid"] == {
            "29": {"added": [], "removed": [-1]}
        }


class TestClassifierEndpointMissing:
    def test_machine_not_in_verdict_files_returns_empty_modes(self, classifier_client):
        c, classify_dir = classifier_client
        _write_mode(classify_dir, 1, [
            {"machine": "M273", "machine_label": "foo", "paid_spin_type": 1,
             "all_resolved": True, "per_st_verdicts": {},
             "feature_delta_from_paid": {}, "feature_tally_keys": []},
        ])
        resp = c.get("/api/classifier/M999")
        assert resp.status_code == 200
        assert resp.json() == {"machine": "M999", "modes": {}, "updated_at": {}}

    def test_classify_dir_missing_returns_empty_modes(
        self, tmp_state_dir, tmp_reports, tmp_cache, fake_machines, fake_analyzer,
        tmp_path, monkeypatch,
    ):
        """Operator never ran the classifier — endpoint stays 200 so
        the UI can render "classifier not run" instead of erroring."""
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
            classify_dir=missing_dir,
        )
        with TestClient(app) as c:
            resp = c.get("/api/classifier/M273")
            assert resp.status_code == 200
            assert resp.json() == {"machine": "M273", "modes": {}, "updated_at": {}}

    def test_corrupted_json_is_skipped_not_crash(self, classifier_client):
        c, classify_dir = classifier_client
        # Drop a corrupted file alongside a valid one.
        (classify_dir / "all_verdicts_mode2.json").write_text(
            "{ this is not valid json", encoding="utf-8",
        )
        _write_mode(classify_dir, 1, [
            {"machine": "M273", "machine_label": "ways-pay",
             "paid_spin_type": 1, "all_resolved": True,
             "per_st_verdicts": {}, "feature_delta_from_paid": {},
             "feature_tally_keys": []},
        ])
        resp = c.get("/api/classifier/M273")
        assert resp.status_code == 200
        body = resp.json()
        # Mode 1 still loads; mode 2 silently skipped because corrupted.
        assert "1" in body["modes"]
        assert "2" not in body["modes"]


class TestLoadClassifierVerdictHelper:
    """Direct tests of the module helper so the endpoint layer doesn't
    need to be reproved for each edge case."""

    def test_picks_right_machine_entry_out_of_many(self, tmp_path):
        d = tmp_path / "_classify"
        d.mkdir()
        _write_mode(d, 1, [
            {"machine": "M1", "machine_label": "A", "paid_spin_type": 1,
             "all_resolved": True, "per_st_verdicts": {},
             "feature_delta_from_paid": {}, "feature_tally_keys": []},
            {"machine": "M273", "machine_label": "B", "paid_spin_type": 140,
             "all_resolved": True, "per_st_verdicts": {},
             "feature_delta_from_paid": {}, "feature_tally_keys": []},
            {"machine": "M999", "machine_label": "C", "paid_spin_type": 1,
             "all_resolved": True, "per_st_verdicts": {},
             "feature_delta_from_paid": {}, "feature_tally_keys": []},
        ])
        out = _load_classifier_verdict("M273", d)
        assert out["modes"]["1"]["machine_label"] == "B"

    def test_non_integer_mode_field_ignored(self, tmp_path):
        d = tmp_path / "_classify"
        d.mkdir()
        (d / "all_verdicts_mode_bad.json").write_text(
            json.dumps({"mode": "bogus", "verdicts": []}), encoding="utf-8",
        )
        out = _load_classifier_verdict("M273", d)
        assert out == {"machine": "M273", "modes": {}, "updated_at": {}}

    def test_per_machine_file_wins_over_combined_file(self, tmp_path):
        """Auto-triggered per-machine output is the primary artifact —
        if both forms exist, the per-machine file (newer, safe for
        concurrent writes) must win. The combined file is used only
        as a fallback for modes the per-machine file doesn't cover."""
        d = tmp_path / "_classify"
        d.mkdir()
        # Combined file carries a stale entry
        _write_mode(d, 1, [
            {"machine": "M273", "machine_label": "STALE", "paid_spin_type": 1,
             "all_resolved": False, "per_st_verdicts": {},
             "feature_delta_from_paid": {}, "feature_tally_keys": []},
        ])
        # Per-machine file carries the fresh entry
        (d / "M273_mode1.json").write_text(
            json.dumps({
                "mode": 1,
                "machine": "M273",
                "verdict": {
                    "machine": "M273",
                    "machine_label": "FRESH",
                    "paid_spin_type": 140,
                    "all_resolved": True,
                    "per_st_verdicts": {},
                    "feature_delta_from_paid": {},
                    "feature_tally_keys": ["NormalCollectionSpin"],
                },
                "written_at": "2026-04-20T10:00:00Z",
            }),
            encoding="utf-8",
        )
        out = _load_classifier_verdict("M273", d)
        assert out["modes"]["1"]["machine_label"] == "FRESH"
        assert out["updated_at"]["1"] == "2026-04-20T10:00:00Z"

    def test_combined_file_fills_modes_missing_from_per_machine(self, tmp_path):
        """Per-machine file has mode 1 only; combined carries mode 1+2;
        fallback must fill mode 2 without overwriting the fresh mode 1."""
        d = tmp_path / "_classify"
        d.mkdir()
        _write_mode(d, 1, [
            {"machine": "M273", "machine_label": "combined1", "paid_spin_type": 1,
             "all_resolved": True, "per_st_verdicts": {},
             "feature_delta_from_paid": {}, "feature_tally_keys": []},
        ])
        _write_mode(d, 2, [
            {"machine": "M273", "machine_label": "combined2", "paid_spin_type": 2,
             "all_resolved": True, "per_st_verdicts": {},
             "feature_delta_from_paid": {}, "feature_tally_keys": []},
        ])
        (d / "M273_mode1.json").write_text(
            json.dumps({
                "mode": 1,
                "machine": "M273",
                "verdict": {"machine": "M273", "machine_label": "per_machine1",
                            "paid_spin_type": 1, "all_resolved": True,
                            "per_st_verdicts": {}, "feature_delta_from_paid": {},
                            "feature_tally_keys": []},
            }),
            encoding="utf-8",
        )
        out = _load_classifier_verdict("M273", d)
        assert out["modes"]["1"]["machine_label"] == "per_machine1"
        assert out["modes"]["2"]["machine_label"] == "combined2"
