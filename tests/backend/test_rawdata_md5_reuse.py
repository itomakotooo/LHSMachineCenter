"""Tests for rawdata MD5 tagging + per-chunk auto-reuse system (session 2026-04).

Covers:
- _classify_machine(): 9-category auto-classification
- check_rawdata_status(): per-chunk MD5 verification + auto-delete
- _get_machine_md5(): machines.json lookup
- delete_rawdata(): directory cleanup helper
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.web_console.backend.app import (
    _classify_machine,
    _get_machine_md5,
    check_rawdata_status,
    delete_rawdata,
)


# ── _classify_machine ──


class TestClassifyMachine:
    def test_normal_only(self):
        assert _classify_machine(["NormalRTPPreProcessor", "NormalSpinGenerator"]) == "Normal"

    def test_collect_dominates(self):
        # BuffCollection wins over any other keyword.
        assert _classify_machine(["BuffCollectionMapValidator", "LockSpinGenerator"]) == "Collect"

    def test_lock_family(self):
        assert _classify_machine(["LockReSpinGenerator", "NormalRTPPreProcessor"]) == "Lock"

    def test_fortunes(self):
        assert _classify_machine(["FortunesFreeSpinGenerator"]) == "Fortunes"

    def test_respin_broad(self):
        # Machines with "WildRespin" etc. should be classified as ReSpin.
        assert _classify_machine(["WildRespinGenerator", "NormalRTPPreProcessor"]) == "ReSpin"

    def test_wheel(self):
        assert _classify_machine(["WheelSpinGenerator", "NormalSpinGenerator"]) == "Wheel"

    def test_freespin_or_rising(self):
        assert _classify_machine(["RisingFreeSpinGenerator"]) == "FreeSpin"

    def test_empty_logic_classes(self):
        assert _classify_machine([]) == "Unknown"

    def test_selector_fallback(self):
        assert _classify_machine(["SomeSelectorGenerator"]) == "Selector"

    def test_other_fallback(self):
        # No matching keyword → "Other".
        assert _classify_machine(["FooBarBazProcessor"]) == "Other"


# ── _get_machine_md5 ──


def _make_machines_config(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "machines.json"
    p.write_text(json.dumps({"machines": entries}, ensure_ascii=False), encoding="utf-8")
    return p


class TestGetMachineMd5:
    def test_found(self, tmp_path):
        cfg = _make_machines_config(tmp_path, [
            {"machine": "M1", "configSummaryMd5": "aaa111", "codeSummaryMd5": "bbb222"},
        ])
        assert _get_machine_md5("M1", cfg) == ("aaa111", "bbb222")

    def test_not_found(self, tmp_path):
        cfg = _make_machines_config(tmp_path, [{"machine": "M1", "configSummaryMd5": "x"}])
        assert _get_machine_md5("M999", cfg) == ("", "")

    def test_missing_file(self, tmp_path):
        assert _get_machine_md5("M1", tmp_path / "nope.json") == ("", "")

    def test_missing_md5_fields(self, tmp_path):
        cfg = _make_machines_config(tmp_path, [{"machine": "M1"}])
        assert _get_machine_md5("M1", cfg) == ("", "")


# ── check_rawdata_status ──


def _write_chunk(dir: Path, idx: int, config_md5: str, code_md5: str) -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    p = dir / f"chunk_{idx:04d}.json"
    p.write_text(json.dumps({
        "_cache_version": 2,
        "_machine": "M1",
        "_mode": 1,
        "_config_md5": config_md5,
        "_code_md5": code_md5,
        "_saved_at": "2026-04-17T00:00:00Z",
        "response": [{"roundResult": "[]"}],
    }), encoding="utf-8")
    return p


class TestCheckRawdataStatus:
    def test_missing_dir(self, tmp_path):
        st = check_rawdata_status("M1", 1, rawdata_root=tmp_path)
        assert st["exists"] is False
        assert st["usable_chunks"] == 0

    def test_all_match(self, tmp_path):
        cfg = _make_machines_config(tmp_path, [
            {"machine": "M1", "configSummaryMd5": "aa", "codeSummaryMd5": "bb"},
        ])
        data_root = tmp_path / "data"
        _write_chunk(data_root / "M1" / "mode_1", 1, "aa", "bb")
        _write_chunk(data_root / "M1" / "mode_1", 2, "aa", "bb")
        st = check_rawdata_status("M1", 1, rawdata_root=data_root, machines_config=cfg)
        assert st["usable_chunks"] == 2
        assert st["mismatch_chunks"] == 0

    def test_mixed_chunks_auto_delete(self, tmp_path):
        cfg = _make_machines_config(tmp_path, [
            {"machine": "M1", "configSummaryMd5": "aa", "codeSummaryMd5": "bb"},
        ])
        data_root = tmp_path / "data"
        mode_dir = data_root / "M1" / "mode_1"
        good1 = _write_chunk(mode_dir, 1, "aa", "bb")
        bad = _write_chunk(mode_dir, 2, "stale", "stale")
        good2 = _write_chunk(mode_dir, 3, "aa", "bb")

        st = check_rawdata_status(
            "M1", 1, rawdata_root=data_root, machines_config=cfg,
            auto_delete_mismatched=True,
        )
        assert st["usable_chunks"] == 2
        assert st["mismatch_chunks"] == 1
        assert len(st["deleted_paths"]) == 1
        # Good chunks remain; bad one deleted.
        assert good1.exists()
        assert good2.exists()
        assert not bad.exists()

    def test_old_format_no_md5_treated_as_mismatch(self, tmp_path):
        """Envelope without _config_md5/_code_md5 (v1 format) → mismatch."""
        cfg = _make_machines_config(tmp_path, [
            {"machine": "M1", "configSummaryMd5": "aa", "codeSummaryMd5": "bb"},
        ])
        data_root = tmp_path / "data"
        mode_dir = data_root / "M1" / "mode_1"
        mode_dir.mkdir(parents=True)
        # Old v1 envelope: no MD5 fields.
        (mode_dir / "chunk_0001.json").write_text(json.dumps({
            "_cache_version": 1, "_machine": "M1", "_mode": 1,
            "response": [],
        }), encoding="utf-8")

        st = check_rawdata_status("M1", 1, rawdata_root=data_root, machines_config=cfg)
        assert st["usable_chunks"] == 0
        assert st["mismatch_chunks"] == 1

    def test_unverifiable_when_upstream_md5_unknown(self, tmp_path):
        """If machines.json has no MD5 for the machine → treat chunks as usable."""
        cfg = _make_machines_config(tmp_path, [{"machine": "M1"}])
        data_root = tmp_path / "data"
        _write_chunk(data_root / "M1" / "mode_1", 1, "irrelevant", "irrelevant")
        st = check_rawdata_status("M1", 1, rawdata_root=data_root, machines_config=cfg)
        assert st["unverifiable"] is True
        assert st["usable_chunks"] == 1

    def test_corrupted_json_chunk_is_mismatch(self, tmp_path):
        cfg = _make_machines_config(tmp_path, [
            {"machine": "M1", "configSummaryMd5": "aa", "codeSummaryMd5": "bb"},
        ])
        data_root = tmp_path / "data"
        mode_dir = data_root / "M1" / "mode_1"
        mode_dir.mkdir(parents=True)
        (mode_dir / "chunk_0001.json").write_text("{not json", encoding="utf-8")
        st = check_rawdata_status("M1", 1, rawdata_root=data_root, machines_config=cfg)
        assert st["usable_chunks"] == 0
        assert st["mismatch_chunks"] == 1


# ── delete_rawdata ──


class TestDeleteRawdata:
    def test_force_delete_specific_mode(self, tmp_path):
        """force=True takes the legacy nuclear path — whole mode dir
        removed regardless of retention."""
        (tmp_path / "M1" / "mode_1").mkdir(parents=True)
        (tmp_path / "M1" / "mode_2").mkdir(parents=True)
        result = delete_rawdata("M1", mode=1, rawdata_root=tmp_path, force=True)
        assert result["ok"] and result["deleted"]
        assert not (tmp_path / "M1" / "mode_1").exists()
        assert (tmp_path / "M1" / "mode_2").exists()

    def test_force_delete_all_modes(self, tmp_path):
        (tmp_path / "M1" / "mode_1").mkdir(parents=True)
        (tmp_path / "M1" / "mode_2").mkdir(parents=True)
        result = delete_rawdata("M1", rawdata_root=tmp_path, force=True)
        assert result["ok"] and result["deleted"]
        assert not (tmp_path / "M1").exists()

    def test_delete_nonexistent(self, tmp_path):
        result = delete_rawdata("M999", rawdata_root=tmp_path)
        assert result["ok"]
        assert result["deleted"] is False

    def test_default_safe_delete_empty_dir_is_noop(self, tmp_path):
        """Without force, an empty mode dir has nothing to reclaim.
        The dir sticks around (will get recreated by next sample
        anyway); it's not the classifier's job to tidy empty dirs."""
        (tmp_path / "M1" / "mode_1").mkdir(parents=True)
        result = delete_rawdata("M1", mode=1, rawdata_root=tmp_path)
        assert result["ok"]
        assert result["deleted_chunks"] == 0
        assert result["kept_chunks"] == 0
        # Empty dir preserved (no chunks to reclaim in safe mode)
        assert (tmp_path / "M1" / "mode_1").exists()
