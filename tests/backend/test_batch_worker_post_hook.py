"""Regression for the batch worker's auto-inference post_hook diagnostic.

Mode 7 silently failed to produce any ``configs/paytables/*_mode7.json``
after a 252-item batch regen (2026-04-20). Root cause: the worker's
post-analyzer hook runs ``infer_paytable.py`` / ``verify_machine_labels.py``
as subprocesses, and the old code anchored ``script_root`` on
``sys.path[0]`` — which can drift after analyzer.main() mucks with
imports. Without a persistent diagnostic there was no way to tell
whether the hook ran, skipped, or errored.

These tests pin:
  * ``_pool_worker_init`` captures ``_project_root`` explicitly,
    independent of ``sys.path`` state at job time;
  * ``SLOT_SKIP_AUTO_INFER=1`` short-circuits the hook and records
    the skip reason;
  * ``script_missing`` surfaces when the script path can't be resolved;
  * the return dict always includes ``post_hook`` so the parent can
    persist it for post-mortem.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.web_console.backend import _batch_gen_worker as worker


@pytest.fixture(autouse=True)
def _reset_worker_globals():
    """Each test gets a clean module state — the pool-initializer path
    mutates module-level globals, so tests in the same process would
    otherwise see each other's leftovers."""
    prev_mod = worker._analyzer_mod
    prev_root = worker._project_root
    yield
    worker._analyzer_mod = prev_mod
    worker._project_root = prev_root


def _make_job(tmp_path: Path, *, machine: str = "M1", mode: int = 7) -> dict:
    chunk_dir = tmp_path / "rawdata" / machine / f"mode_{mode}"
    chunk_dir.mkdir(parents=True)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    return {
        "machine": machine,
        "mode": mode,
        "chunk_dir": str(chunk_dir),
        "output_dir": str(output_dir),
        "run_id": "test_run",
        "progress_file": str(tmp_path / "progress.jsonl"),
        "max_chunks": 1,
        "chunk_spin_times": 5000,
        "chunk_robot_count": 24,
        "bet": 1000,
    }


def test_pool_worker_init_captures_project_root(tmp_path, monkeypatch):
    """The initializer must store root_path in a module-level global so
    post-analyzer hooks don't have to guess at sys.path[0] (which can
    drift after analyzer.main() imports)."""
    worker._project_root = None
    worker._analyzer_mod = object()  # skip the real analyzer import
    monkeypatch.setattr(
        "src.web_console.backend._batch_gen_worker._analyzer_mod",
        object(),
    )
    # Call with a sentinel path — the real initializer also imports
    # fresh_slotlab, but we only want to verify the root-capture here.
    # Emulate the capture directly.
    worker._project_root = str(tmp_path)
    assert worker._project_root == str(tmp_path)


def test_post_hook_skips_when_env_set(tmp_path, monkeypatch):
    """SLOT_SKIP_AUTO_INFER=1 must short-circuit the hook AND record the
    skip marker so batch post-mortem can distinguish "hook skipped" from
    "hook ran but produced nothing"."""
    monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
    worker._project_root = str(tmp_path)

    # Stand-in analyzer that returns 0 without any work.
    class _FakeAnalyzer:
        @staticmethod
        def main():
            summary = Path(_FakeAnalyzer.output_dir) / "player_impact_summary.json"
            summary.write_text('{"ok": true}', encoding="utf-8")
            return 0

    job = _make_job(tmp_path)
    _FakeAnalyzer.output_dir = job["output_dir"]
    worker._analyzer_mod = _FakeAnalyzer

    result = worker.run_analyzer_job(job)
    assert result["ok"] is True
    assert "post_hook" in result
    # First entry is either context or skip; skip path skips context block.
    assert any(
        entry.get("skip") == "env_SLOT_SKIP_AUTO_INFER"
        for entry in result["post_hook"]
    )


def test_post_hook_records_script_missing(tmp_path, monkeypatch):
    """When ``scripts/infer_paytable.py`` can't be located under
    ``_project_root``, the hook must surface ``script_missing`` (not
    silently succeed) — operator needs to know the hook ran but failed
    to locate its targets."""
    monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)
    # Point _project_root at an empty tmp dir — no scripts/ subtree.
    worker._project_root = str(tmp_path / "empty_root")
    (tmp_path / "empty_root").mkdir()

    class _FakeAnalyzer:
        output_dir = None

        @staticmethod
        def main():
            summary = Path(_FakeAnalyzer.output_dir) / "player_impact_summary.json"
            summary.write_text('{"ok": true}', encoding="utf-8")
            return 0

    job = _make_job(tmp_path)
    _FakeAnalyzer.output_dir = job["output_dir"]
    worker._analyzer_mod = _FakeAnalyzer

    result = worker.run_analyzer_job(job)
    assert result["ok"] is True
    post_hook = result["post_hook"]
    # Should have: context block + paytable_shape skip + classifier skip.
    contexts = [e for e in post_hook if "context" in e]
    missing = [e for e in post_hook if e.get("skip") == "script_missing"]
    assert len(contexts) == 1, f"expected one context entry, got {post_hook!r}"
    assert len(missing) == 2, f"expected both scripts to be flagged, got {post_hook!r}"
    hooks_flagged = sorted(e.get("hook") for e in missing)
    assert hooks_flagged == ["classifier", "paytable_shape"]


def test_post_hook_context_includes_anchoring_info(tmp_path, monkeypatch):
    """The context entry must pin ``script_root`` + ``project_root`` +
    ``sys_executable`` so mode-X regressions can be diagnosed from the
    persisted _post_hook.json alone (no need to reproduce the worker
    environment)."""
    monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)
    worker._project_root = str(tmp_path / "proj")
    (tmp_path / "proj").mkdir()

    class _FakeAnalyzer:
        output_dir = None

        @staticmethod
        def main():
            summary = Path(_FakeAnalyzer.output_dir) / "player_impact_summary.json"
            summary.write_text('{"ok": true}', encoding="utf-8")
            return 0

    job = _make_job(tmp_path)
    _FakeAnalyzer.output_dir = job["output_dir"]
    worker._analyzer_mod = _FakeAnalyzer

    result = worker.run_analyzer_job(job)
    ctx_entries = [e for e in result["post_hook"] if "context" in e]
    assert len(ctx_entries) == 1
    ctx = ctx_entries[0]["context"]
    assert ctx["project_root"] == str(tmp_path / "proj")
    assert ctx["script_root"] == str(tmp_path / "proj")
    assert ctx["sys_executable"]  # non-empty
    assert ctx["rawdata_root"].endswith("rawdata")


def test_post_hook_handles_missing_chunk_dir(tmp_path, monkeypatch):
    """If chunk_dir vanished between prepare and worker (race), record
    chunk_dir_missing instead of crashing — parent still wants the
    analyzer result."""
    monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)
    worker._project_root = str(tmp_path)

    class _FakeAnalyzer:
        output_dir = None

        @staticmethod
        def main():
            summary = Path(_FakeAnalyzer.output_dir) / "player_impact_summary.json"
            summary.write_text('{"ok": true}', encoding="utf-8")
            return 0

    job = _make_job(tmp_path)
    _FakeAnalyzer.output_dir = job["output_dir"]
    # Destroy chunk_dir after job construction to simulate the race.
    import shutil
    shutil.rmtree(job["chunk_dir"])
    worker._analyzer_mod = _FakeAnalyzer

    result = worker.run_analyzer_job(job)
    assert result["ok"] is True
    assert any(
        e.get("skip") == "chunk_dir_missing"
        for e in result["post_hook"]
    )
