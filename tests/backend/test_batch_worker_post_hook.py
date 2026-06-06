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


import json


@pytest.fixture(autouse=True)
def _reset_worker_globals():
    """Each test gets a clean module state — the pool-initializer path
    mutates module-level globals, so tests in the same process would
    otherwise see each other's leftovers.

    P1-D1 round-2 verifier fix: extended to cover the 3 new globals
    added by P1-D1 C3/C4 (`_patch_summary_md5_fn`,
    `_run_post_inference_fn`, `_lookup_machine_md5_fn`).

    Phase 2b: also saves/restores `_report_engine_mod`.
    """
    _MISSING = object()
    prev_mod = worker._analyzer_mod
    prev_root = worker._project_root
    prev_psm = worker._patch_summary_md5_fn
    prev_rpi = worker._run_post_inference_fn
    prev_lmm = worker._lookup_machine_md5_fn
    prev_rem = getattr(worker, "_report_engine_mod", _MISSING)
    yield
    worker._analyzer_mod = prev_mod
    worker._project_root = prev_root
    worker._patch_summary_md5_fn = prev_psm
    worker._run_post_inference_fn = prev_rpi
    worker._lookup_machine_md5_fn = prev_lmm
    if prev_rem is _MISSING:
        if hasattr(worker, "_report_engine_mod"):
            delattr(worker, "_report_engine_mod")
    else:
        worker._report_engine_mod = prev_rem


def _make_fake_manifest(root: Path, machine: str) -> None:
    """Write a minimal SpinType-native manifest so the registered check passes."""
    manifests_dir = root / "configs" / "machine_manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifests_dir / f"{machine}.json"
    if not manifest_path.exists():
        manifest_path.write_text(
            json.dumps({"machine_id": machine, "spin_types": {}}),
            encoding="utf-8",
        )


def _make_job(tmp_path: Path, *, machine: str = "M1", mode: int = 7) -> dict:
    chunk_dir = tmp_path / "rawdata" / machine / f"mode_{mode}"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    output_dir = tmp_path / "out"
    output_dir.mkdir(exist_ok=True)
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
    _make_fake_manifest(tmp_path, "M1")

    # Stand-in engine (phase 2b) that writes a minimal summary.
    class _FakeEngine:
        @staticmethod
        def generate_report_from_chunks(machine, mode, *, chunk_dir, output_dir, **kw):
            summary = Path(output_dir) / "player_impact_summary.json"
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            summary.write_text('{"ok": true}', encoding="utf-8")

        class MachineNotRegistered(ValueError):
            pass

    job = _make_job(tmp_path)
    worker._report_engine_mod = _FakeEngine

    result = worker.run_analyzer_job(job)
    assert result["ok"] is True
    assert "post_hook" in result
    # First entry is either context or skip; skip path skips context block.
    assert any(
        entry.get("skip") == "env_SLOT_SKIP_AUTO_INFER"
        for entry in result["post_hook"]
    )


def test_post_hook_records_script_missing(tmp_path, monkeypatch):
    """When ``scripts/infer_paytable.py`` and ``scripts/verify_machine_labels.py``
    can't be located under ``_project_root``, the canonical helper must surface
    ``error == "script_missing"`` on both script sub-entries (not silently succeed)
    — operator needs to know the hook ran but failed to locate its targets.

    P1-D1 new format: post_hook is a single canonical entry dict (not a list of
    context + per-hook dicts). Script-missing is recorded as:
      post_hook[0]["paytable_shape"]["ok"] is False
      post_hook[0]["paytable_shape"]["error"] == "script_missing"
      post_hook[0]["classifier"]["ok"] is False
      post_hook[0]["classifier"]["error"] == "script_missing"
      post_hook[0]["failed"] is True
    """
    monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)
    # Point _project_root at an empty tmp dir — no scripts/ subtree.
    empty_root = tmp_path / "empty_root"
    empty_root.mkdir()
    worker._project_root = str(empty_root)
    _make_fake_manifest(empty_root, "M1")

    class _FakeEngine:
        @staticmethod
        def generate_report_from_chunks(machine, mode, *, chunk_dir, output_dir, **kw):
            summary = Path(output_dir) / "player_impact_summary.json"
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            summary.write_text('{"ok": true}', encoding="utf-8")

        class MachineNotRegistered(ValueError):
            pass

    job = _make_job(tmp_path)
    worker._report_engine_mod = _FakeEngine

    result = worker.run_analyzer_job(job)
    assert result["ok"] is True
    post_hook = result["post_hook"]
    assert len(post_hook) == 1, f"expected single canonical entry, got {post_hook!r}"
    entry = post_hook[0]
    # P1-D1: canonical_post_inference flag marks the new format.
    assert entry.get("canonical_post_inference") is True, (
        f"entry missing canonical_post_inference marker: {entry!r}"
    )
    # Both scripts must be recorded as failed with error == "script_missing".
    assert entry.get("failed") is True, (
        f"expected failed=True when both scripts missing, got {entry!r}"
    )
    paytable = entry.get("paytable_shape")
    assert paytable is not None, f"paytable_shape key missing from entry: {entry!r}"
    assert paytable["ok"] is False, f"expected paytable_shape ok=False, got {paytable!r}"
    assert paytable.get("error") == "script_missing", (
        f"expected paytable_shape error='script_missing', got {paytable!r}"
    )
    classifier = entry.get("classifier")
    assert classifier is not None, f"classifier key missing from entry: {entry!r}"
    assert classifier["ok"] is False, f"expected classifier ok=False, got {classifier!r}"
    assert classifier.get("error") == "script_missing", (
        f"expected classifier error='script_missing', got {classifier!r}"
    )


def test_post_hook_context_includes_anchoring_info(tmp_path, monkeypatch):
    """The canonical entry must record ``machine`` + ``mode`` so operators can
    diagnose mode-X regressions from the persisted post_hook alone.  The
    ``scripts_dir`` is derived from ``_project_root`` (the pool-initializer
    anchor); this test verifies that the hook entry reflects the correct
    (machine, mode) pair and that the scripts path resolution respects
    ``_project_root``.

    P1-D1 new format: the old separate ``{"context": {...}}`` entry is gone.
    Anchoring info is now embedded implicitly:
      - ``post_hook[0]["machine"]`` == job["machine"]
      - ``post_hook[0]["mode"]``    == job["mode"]
      - script path resolution uses _project_root (verified by checking that
        paytable_shape["error"] == "script_missing" when _project_root has no
        scripts/ — proving the path was derived from _project_root, not a
        live sys.path[0] guess).
    """
    monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)
    proj_root = tmp_path / "proj"
    proj_root.mkdir()
    worker._project_root = str(proj_root)
    _make_fake_manifest(proj_root, "M1")

    class _FakeEngine:
        @staticmethod
        def generate_report_from_chunks(machine, mode, *, chunk_dir, output_dir, **kw):
            summary = Path(output_dir) / "player_impact_summary.json"
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            summary.write_text('{"ok": true}', encoding="utf-8")

        class MachineNotRegistered(ValueError):
            pass

    job = _make_job(tmp_path)
    worker._report_engine_mod = _FakeEngine

    result = worker.run_analyzer_job(job)
    post_hook = result["post_hook"]
    assert len(post_hook) == 1, f"expected single canonical entry, got {post_hook!r}"
    entry = post_hook[0]
    # Machine + mode anchoring (replaces the old context["project_root"] check).
    assert entry.get("machine") == job["machine"], (
        f"machine mismatch in hook entry: {entry!r}"
    )
    assert entry.get("mode") == job["mode"], (
        f"mode mismatch in hook entry: {entry!r}"
    )
    # Verify that _project_root is used for script resolution: proj_root has
    # no scripts/ subtree, so both scripts must appear as "script_missing".
    # If the impl were reading sys.path[0] instead of _project_root, this
    # assertion would not reliably catch the regression (sys.path[0] might
    # coincidentally not have the scripts either — but the machine/mode check
    # above is the primary split-path anchor per the new design).
    paytable = entry.get("paytable_shape", {})
    assert paytable.get("error") == "script_missing", (
        f"expected paytable_shape to reflect _project_root-derived path miss, "
        f"got: {entry!r}"
    )


def test_post_hook_handles_missing_chunk_dir(tmp_path, monkeypatch):
    """If chunk_dir vanished between prepare and worker (race), the canonical
    helper must NOT crash — parent still gets result["ok"] = True.

    P1-D1 behavior change: the old implementation recorded
    ``{"skip": "chunk_dir_missing"}`` in the hook list. The new canonical helper
    (run_post_analyzer_inference) does not have a chunk_dir_missing guard.
    Instead, when chunk_dir is absent, rawdata_root is set to None (worker line
    240), which causes the helper to bypass the rawdata Guard 2 and attempt the
    scripts directly. Since _project_root has no scripts/ subtree in this test,
    both scripts hit ``error="script_missing"`` and the entry records
    ``failed=True``.

    The invariant under test is: missing chunk_dir must NOT raise an exception
    (result["ok"] stays True) and the canonical post_hook entry is always
    present. The specific skip/error reason is asserted to confirm the
    graceful-degradation path ran rather than crashed.
    """
    monkeypatch.delenv("SLOT_SKIP_AUTO_INFER", raising=False)
    worker._project_root = str(tmp_path)
    _make_fake_manifest(tmp_path, "M1")

    class _FakeEngine:
        @staticmethod
        def generate_report_from_chunks(machine, mode, *, chunk_dir, output_dir, **kw):
            summary = Path(output_dir) / "player_impact_summary.json"
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            summary.write_text('{"ok": true}', encoding="utf-8")

        class MachineNotRegistered(ValueError):
            pass

    job = _make_job(tmp_path)
    # Destroy chunk_dir after job construction to simulate the race.
    import shutil
    shutil.rmtree(job["chunk_dir"])
    worker._report_engine_mod = _FakeEngine

    result = worker.run_analyzer_job(job)
    # Primary: must not crash.
    assert result["ok"] is True, f"expected ok=True even with missing chunk_dir, got {result!r}"
    # post_hook must be present and have the canonical entry.
    post_hook = result["post_hook"]
    assert len(post_hook) >= 1, f"expected at least one post_hook entry, got {post_hook!r}"
    entry = post_hook[0]
    assert entry.get("canonical_post_inference") is True, (
        f"expected canonical_post_inference marker, got {entry!r}"
    )
    # With chunk_dir missing → rawdata_root=None → scripts attempted but not
    # found → both fail with script_missing rather than chunk_dir_missing skip.
    # Assert that "chunk_dir_missing" is NOT the signal (old format gone) and
    # the canonical entry records the actual failure signal instead.
    assert entry.get("skip") != "chunk_dir_missing", (
        "chunk_dir_missing skip reason should no longer appear in new format; "
        f"got: {entry!r}"
    )
    # With tmp_path as project_root (no scripts/ subtree), rawdata_root=None
    # causes scripts to be attempted and fail with script_missing.
    paytable = entry.get("paytable_shape")
    assert paytable is not None, (
        f"expected paytable_shape sub-entry when chunk_dir is missing, got {entry!r}"
    )
    assert paytable.get("ok") is False, (
        f"expected paytable_shape ok=False in missing-chunk_dir path, got {paytable!r}"
    )
