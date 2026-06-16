"""Regression: the BATCH generate path must (a) hand the worker/engine ONLY
the usable (current-md5) chunks, (b) carry + forward the chunks' real bet,
(c) stamp the summary with the SOURCE-chunk md5 pair, and (d) clean up the
scoped hardlink dir.

This is the batch-path mirror of tests/backend/test_generate_report_md5_scope.py
(the single-item path, fixed in fd6b507). The batch path had the SAME latent
scope defect — `_prepare_batch_gen_item` selected usable=kept+deletable but put
the WHOLE mode dir in job["chunk_dir"], so a 全 fleet 重建 on a mixed-md5 dir
silently mixed historical chunks into a current-stamped report — PLUS one more:
the worker never forwarded job["bet"] to the engine at all (sampling.bet=1 →
1000× inflated multiplier columns).

Harness: `_prepare_batch_gen_item` is a create_app closure — captured by
monkeypatching BatchGenerateManager.__init__ (the test_batch_gen_worker_parity
pattern). The worker side calls run_analyzer_job directly with a stub engine
recording the kwargs it RECEIVES (argv-style, per feedback_integration_test_argv);
the stub writes a deliberately wrong roster-style stamp so only the worker's
provenance override can make the summary right.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.web_console.backend import _batch_gen_worker as worker

CFG_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # historical config (2 chunks)
CFG_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"  # current  config (1 chunk)
CODE_Z = "cccccccccccccccccccccccccccccccc"  # shared code md5
CHUNK_BET = 777  # deliberately NOT 1000 — proves bet comes from the chunk


def _write_chunk(path: Path, idx: int, cfg: str) -> None:
    path.write_text(json.dumps({
        "_machine": "MTEST", "_mode": 1, "_chunk_index": idx,
        "_config_md5": cfg, "_code_md5": CODE_Z,
        "_spin_times": 1000, "_robot_count": 1, "_bet": CHUNK_BET,
        "_cache_version": 3,
        "_saved_at": "2026-06-01T00:00:00Z",
        "response": [],
    }), encoding="utf-8")


@pytest.fixture
def batch_prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """create_app over a synthetic mixed-md5 rawdata dir; capture the batch
    prepare/finalize closures via BatchGenerateManager.__init__.

    Rawdata MTEST/mode_1: chunk_0001/0002 = CFG_A (historical),
    chunk_0003 = CFG_B (current per roster) → usable = the single B chunk.
    """
    import src.web_console.backend.app as app_mod

    state_dir = tmp_path / "state"; (state_dir / "progress").mkdir(parents=True)
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

    captured: dict[str, Any] = {}
    _real_init = app_mod.BatchGenerateManager.__init__

    def _capturing_init(self_mgr, prepare_fn, finalize_fn, *args, **kwargs):
        captured["prepare_fn"] = prepare_fn
        captured["finalize_fn"] = finalize_fn
        _real_init(self_mgr, prepare_fn, finalize_fn, *args, **kwargs)

    monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
    with patch.object(app_mod.BatchGenerateManager, "__init__", _capturing_init):
        app_mod.create_app(
            state_dir=state_dir,
            reports_root=tmp_path / "reports",
            cache_root=tmp_path / "cache",
            machines_config=mc,
            rawdata_root=rd_root,
        )
    assert "prepare_fn" in captured, "BatchGenerateManager init not captured"
    return captured, tmp_path, mode_dir


class TestBatchPrepareScopesChunkDir:
    def test_job_chunk_dir_is_scoped_to_usable_chunks_only(self, batch_prepare):
        """job["chunk_dir"] must contain ONLY the current-md5 chunk — not the
        raw mode dir with the 2 historical chunks."""
        captured, tmp_path, mode_dir = batch_prepare
        prepared = captured["prepare_fn"]("MTEST", 1)
        job_dir = Path(prepared["job"]["chunk_dir"])
        assert job_dir != mode_dir, (
            "job carries the RAW mode dir — historical chunks leak into the "
            "batch report (the 全 fleet 重建 defect)"
        )
        names = sorted(p.name for p in job_dir.glob("chunk_*.json"))
        assert names == ["chunk_0003.json"], f"scoped dir wrong: {names}"
        assert prepared["scoped_chunk_dir"] is not None

    def test_pure_current_dir_passes_mode_dir_unscoped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """No historical chunks → no scoped dir (fast path, no links)."""
        import src.web_console.backend.app as app_mod
        state_dir = tmp_path / "state"; (state_dir / "progress").mkdir(parents=True)
        rd_root = tmp_path / "rawdata"
        mode_dir = rd_root / "MTEST" / "mode_1"; mode_dir.mkdir(parents=True)
        _write_chunk(mode_dir / "chunk_0001.json", 1, CFG_B)
        mc = tmp_path / "machines.json"
        mc.write_text(json.dumps({"machines": [{
            "machine": "MTEST", "modes": [1],
            "configSummaryMd5": CFG_B, "codeSummaryMd5": CODE_Z,
        }]}), encoding="utf-8")
        captured: dict[str, Any] = {}
        _real_init = app_mod.BatchGenerateManager.__init__

        def _capturing_init(self_mgr, prepare_fn, finalize_fn, *args, **kwargs):
            captured["prepare_fn"] = prepare_fn
            _real_init(self_mgr, prepare_fn, finalize_fn, *args, **kwargs)

        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        with patch.object(app_mod.BatchGenerateManager, "__init__", _capturing_init):
            app_mod.create_app(
                state_dir=state_dir, reports_root=tmp_path / "reports",
                cache_root=tmp_path / "cache", machines_config=mc,
                rawdata_root=rd_root,
            )
        prepared = captured["prepare_fn"]("MTEST", 1)
        assert Path(prepared["job"]["chunk_dir"]) == mode_dir
        assert prepared["scoped_chunk_dir"] is None

    def test_job_carries_source_md5_bet_and_rawdata_root(self, batch_prepare):
        """Provenance pair = the SELECTED (current) chunks' md5; bet = the
        chunks' real _bet (777, NOT a hardcoded 1000); rawdata_root explicit."""
        captured, tmp_path, _mode_dir = batch_prepare
        job = captured["prepare_fn"]("MTEST", 1)["job"]
        assert job["source_config_md5"] == CFG_B
        assert job["source_code_md5"] == CODE_Z
        assert job["bet"] == CHUNK_BET
        assert Path(job["rawdata_root"]) == tmp_path / "rawdata"

    def test_finalize_wrapper_cleans_scoped_dir(self, batch_prepare):
        """The scoped hardlink dir must not survive finalize — even for a
        FAILED worker result."""
        captured, _tmp, _mode_dir = batch_prepare
        prepared = captured["prepare_fn"]("MTEST", 1)
        scoped = Path(prepared["scoped_chunk_dir"])
        assert scoped.exists()
        captured["finalize_fn"](prepared, {"ok": False, "error": "injected"})
        assert not scoped.exists(), "scoped dir leaked after finalize"


class TestBatchWorkerForwardsAndStamps:
    @pytest.fixture(autouse=True)
    def _reset_worker_globals(self):
        saved = (worker._report_engine_mod, worker._project_root,
                 worker._patch_summary_md5_fn, worker._run_post_inference_fn,
                 worker._lookup_machine_md5_fn)
        yield
        (worker._report_engine_mod, worker._project_root,
         worker._patch_summary_md5_fn, worker._run_post_inference_fn,
         worker._lookup_machine_md5_fn) = saved

    def _stub_engine(self, calls: list):
        class _StubEngine:
            @staticmethod
            def generate_report_from_chunks(machine, mode, *, chunk_dir,
                                            output_dir, bet=1, run_id=None,
                                            manifests_root=None,
                                            manifest_machine_id=None):
                calls.append({"chunk_dir": Path(chunk_dir), "bet": bet})
                out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
                (out / "player_impact_summary.json").write_text(json.dumps({
                    "machine": machine, "mode": mode,
                    "config_md5": "ROSTERSTAMPWRONG",
                    "code_md5": "ROSTERSTAMPWRONG",
                    "rtp": {"point_pct": 50.0},
                    "sampling": {"bet": bet},
                }), encoding="utf-8")

            class MachineNotRegistered(ValueError):
                pass
        return _StubEngine

    def _make_job(self, tmp_path: Path) -> dict:
        chunk_dir = tmp_path / "scoped"; chunk_dir.mkdir(exist_ok=True)
        manifests = tmp_path / "configs" / "machine_manifests"
        manifests.mkdir(parents=True, exist_ok=True)
        (manifests / "MTEST.json").write_text("{}", encoding="utf-8")
        return {
            "machine": "MTEST", "mode": 1,
            "chunk_dir": str(chunk_dir),
            "output_dir": str(tmp_path / "out"),
            "run_id": "t", "progress_file": str(tmp_path / "p.jsonl"),
            "max_chunks": 1, "chunk_spin_times": 1000,
            "chunk_robot_count": 1,
            "bet": CHUNK_BET,
            "upstream_config_md5": "ROSTERCURRENT",
            "upstream_code_md5": "ROSTERCURRENT",
            "source_config_md5": CFG_B,
            "source_code_md5": CODE_Z,
            "rawdata_root": str(tmp_path / "rawdata"),
        }

    def test_worker_forwards_bet_to_engine(self, tmp_path, monkeypatch):
        """The engine must receive job["bet"] — previously DROPPED entirely
        (engine default 1 → 1000× inflated multiplier columns)."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        calls: list = []
        worker._report_engine_mod = self._stub_engine(calls)
        worker._project_root = str(tmp_path)
        res = worker.run_analyzer_job(self._make_job(tmp_path))
        assert res["ok"], res
        assert calls[0]["bet"] == CHUNK_BET, (
            f"engine got bet={calls[0]['bet']} — job bet was dropped"
        )

    def test_worker_stamps_summary_with_source_provenance(self, tmp_path, monkeypatch):
        """After generation the summary md5 pair must be the SOURCE-chunk
        pair, overriding the engine's roster-style stamp."""
        monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
        calls: list = []
        worker._report_engine_mod = self._stub_engine(calls)
        worker._project_root = str(tmp_path)
        res = worker.run_analyzer_job(self._make_job(tmp_path))
        assert res["ok"], res
        s = json.loads((tmp_path / "out" / "player_impact_summary.json")
                       .read_text(encoding="utf-8"))
        assert s["config_md5"] == CFG_B, f"provenance not stamped: {s['config_md5']}"
        assert s["code_md5"] == CODE_Z
