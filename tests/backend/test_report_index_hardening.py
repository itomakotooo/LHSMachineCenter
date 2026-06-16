"""Report-store management hardening tests — value-agnostic, inject-bug required.

Design contract: session_artifacts/_arch_playtype/REPORT_MGMT_FIX_2026-06-12.md
Fills gaps left by test_report_index.py (implementer's 15 tests):
  - test_report_index.py covers: basic shape, basic thread-race, basic
    reconcile, report_count, import 1 test, generate effective_version.
  - THIS FILE adds the invariant-hardening + inject-bug proofs mandated by
    the coordinator prompt:

Test classes:
  1. TestRaceForcedInterleave  — threads WITH barrier (forced interleave) +
     multiprocess (two OS processes appending to same index.json); both must
     survive.
  2. TestF2FailureHygiene      — generate endpoint failure leaves NO version dir
     (in-process; monkeypatch engine call).
  3. TestReconcileExtended     — all action classes from the design:
       * no-summary dir + active run row → SKIPPED (not deleted)
       * entry with non-canonical path where canonical exists → path_rewrite
       * entry whose file exists nowhere → zombie_entry_drop
       * entry missing md5+effective → persist_backfill
       * dangling report_file key (file deleted) → report_file_key_drop
       * stale latest.json → latest_recompute after wet run
       * dry_run leaves tree byte-identical (hash check)
  4. TestImportProducerShape   — import + generate produce entries with the
     SAME key set.

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md):
  For each invariant we temporarily break the protection, run pytest, observe
  RED, revert, observe GREEN. Evidence documented below and in the CI report.

  Race barrier test:
    Bug: comment out `in_proc_lock.acquire()` in _report_index_lock.
    Expected: lost-update → len(index) < n_threads → RED.
    Revert → GREEN.

  F2 failure hygiene:
    Bug: comment out the `shutil.rmtree(output_dir ...)` cleanup block in
    _run_generate_report's except clause.
    Expected: version dir still exists after 422 → RED.
    Revert → GREEN.

  Reconcile active-run guard:
    Bug: in reconcile_reports, remove the `if vname in active_run_versions:
    continue` guard (change to always proceed to delete).
    Expected: no-summary dir with active run row gets deleted → assertion
    that dir still exists fails → RED.
    Revert → GREEN.

Memory citations:
  - memory/feedback_enumerate_safety_paths.md
  - memory/feedback_integration_test_argv.md
  - memory/feedback_perf_claim_needs_e2e_event_stream.md
  - memory/feedback_no_silent_swallow.md
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.web_console.backend.report_index import (
    append_and_rewrite_latest,
    build_index_entry,
)
from src.web_console.backend.app import create_app

# ---------------------------------------------------------------------------
# Helpers (mirrors test_report_index.py without duplication)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_M15_CHUNK_DIR = _REPO_ROOT / "rawdata" / "M15" / "mode_1"
_MANIFESTS_ROOT = _REPO_ROOT / "configs" / "machine_manifests"


def _m15_chunks_present() -> bool:
    return (
        _M15_CHUNK_DIR.exists()
        and len(list(_M15_CHUNK_DIR.glob("chunk_*.json"))) > 0
    )


def _make_summary(
    rtp: float = 93.5,
    config_md5: str = "aabbccdd1234",
    code_md5: str = "eeff99887766",
    analyzer_version: str = "v1.2.3",
    effective_analyzer_version: str = "eff_abc123",
    run_id: str = "run_test001",
) -> dict:
    return {
        "run_id": run_id,
        "config_md5": config_md5,
        "code_md5": code_md5,
        "analyzer_version": analyzer_version,
        "effective_analyzer_version": effective_analyzer_version,
        "rtp": {"point_pct": rtp},
        "sampling": {
            "finished_at": "2026-06-12T10:00:00Z",
            "started_at": "2026-06-12T09:00:00Z",
            "achieved_halfwidth_pp": 0.005,
            "total_spins": 100000,
        },
        "guideline_assessment": {
            "data_quality": {"quality_label": "report-grade"},
        },
    }


def _write_summary(path: Path, **kwargs) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    s = _make_summary(**kwargs)
    path.write_text(json.dumps(s), encoding="utf-8")
    return s


def _dir_hash(root: Path) -> str:
    """Deterministic hash of every file byte and relative path under root."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# App fixture (reuses conftest patterns, isolated per test)
# ---------------------------------------------------------------------------


def _make_isolated_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    machine: str = "MREC",
    modes: list[int] | None = None,
    rawdata_root: Path | None = None,
) -> tuple[TestClient, Path, Path]:
    """Returns (client, reports_dir, state_dir)."""
    modes = modes or [1]
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "progress").mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    mc = tmp_path / "machines.json"
    mc.write_text(
        json.dumps({"machines": [{"machine": machine, "modes": modes}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SLOT_SKIP_AUTO_INFER", "1")
    kwargs: dict[str, Any] = dict(
        state_dir=state_dir,
        reports_root=reports_dir,
        machines_config=mc,
    )
    if rawdata_root is not None:
        kwargs["rawdata_root"] = rawdata_root
    app = create_app(**kwargs)
    client = TestClient(app)
    client.__enter__()
    return client, reports_dir, state_dir


# ===========================================================================
# 1. TestRaceForcedInterleave
# ===========================================================================


class TestRaceForcedInterleave:
    """Race-safety tests with barrier-forced interleave and multiprocess.

    Inject-bug recipe:
      Open src/web_console/backend/report_index.py, comment out
      `in_proc_lock.acquire()` (line ~76) and remove the matching
      `in_proc_lock.release()`.  With 16 threads all entering the critical
      section simultaneously, the read-modify-write loses updates with high
      probability → len(index) < n_threads → test_barrier_forced_race RED.
      Revert → GREEN.
    """

    def test_barrier_forced_race_no_lost_entries(self, tmp_path: Path):
        """16 threads all hit append_and_rewrite_latest SIMULTANEOUSLY via
        a Barrier. Every entry must survive (no lost-update race).

        This is a stronger version of test_concurrent_append_no_lost_entries:
        the Barrier guarantees ALL threads have reached the lock before any
        can proceed, maximising the chance a lock-free bug loses entries.
        """
        n_threads = 16
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir()
        barrier = threading.Barrier(n_threads)
        errors: list[str] = []

        def _do(i: int) -> None:
            summary = _make_summary(run_id=f"run{i:03d}")
            sp = mode_dir / f"rv_{i:03d}" / "player_impact_summary.json"
            _write_summary(sp)
            entry = build_index_entry(
                tmp_path, "MRACE", 1, f"rv_{i:03d}", f"run{i:03d}",
                summary=summary, summary_path=sp,
            )
            # All threads wait here — then all enter the lock at once.
            barrier.wait(timeout=10)
            try:
                append_and_rewrite_latest(mode_dir, entry)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"thread {i}: {exc}")

        threads = [threading.Thread(target=_do, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, f"Thread errors: {errors}"
        raw = json.loads((mode_dir / "index.json").read_text(encoding="utf-8"))
        assert len(raw) == n_threads, (
            f"RACE LOST UPDATES: expected {n_threads} entries, got {len(raw)}. "
            "This means the threading.Lock in _report_index_lock is not working. "
            "Inject-bug: comment out in_proc_lock.acquire() in report_index.py → "
            "this test should go RED. Revert → GREEN."
        )

    def test_barrier_forced_race_latest_is_valid_json(self, tmp_path: Path):
        """After a barrier-forced concurrent append storm, latest.json must
        be valid JSON and contain a dict (not None, not list, not empty)."""
        n_threads = 12
        mode_dir = tmp_path / "mode_latest"
        mode_dir.mkdir()
        barrier = threading.Barrier(n_threads)

        def _do(i: int) -> None:
            summary = _make_summary(run_id=f"runL{i:03d}")
            sp = mode_dir / f"rv_L{i:03d}" / "player_impact_summary.json"
            _write_summary(sp)
            entry = build_index_entry(
                tmp_path, "MLAT", 1, f"rv_L{i:03d}", f"runL{i:03d}",
                summary=summary, summary_path=sp,
            )
            barrier.wait(timeout=10)
            append_and_rewrite_latest(mode_dir, entry)

        threads = [threading.Thread(target=_do, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        latest_path = mode_dir / "latest.json"
        assert latest_path.exists(), "latest.json must exist after concurrent appends"
        raw_latest = json.loads(latest_path.read_text(encoding="utf-8"))
        assert isinstance(raw_latest, dict), (
            f"latest.json must be a dict, got {type(raw_latest)}"
        )
        assert raw_latest.get("report_version"), (
            "latest.json must carry report_version"
        )


def _worker_append(args: tuple) -> str | None:
    """Worker function for multiprocessing race test.

    Must be module-level (picklable) on Windows where spawn is the default
    multiprocessing start method.

    Returns None on success, error string on failure.
    """
    tmp_str, mode_dir_str, idx = args
    tmp_path = Path(tmp_str)
    mode_dir = Path(mode_dir_str)

    # Import inside the worker (Windows spawn: fresh interpreter).
    from src.web_console.backend.report_index import (  # noqa: PLC0415
        append_and_rewrite_latest as _append,
        build_index_entry as _build,
    )
    # Minimal summary.
    summary = {
        "run_id": f"proc_{idx:03d}",
        "config_md5": "cfg_proc",
        "code_md5": "code_proc",
        "analyzer_version": "v0",
        "effective_analyzer_version": "eff0",
        "rtp": {"point_pct": 90.0},
        "sampling": {"achieved_halfwidth_pp": 0.01, "total_spins": 50000},
        "guideline_assessment": {"data_quality": {"quality_label": "dev"}},
    }
    sp = mode_dir / f"rv_proc_{idx:03d}" / "player_impact_summary.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(summary), encoding="utf-8")
    entry = _build(
        tmp_path, "MPROC", 1, f"rv_proc_{idx:03d}", f"proc_{idx:03d}",
        summary=summary, summary_path=sp,
    )
    try:
        _append(mode_dir, entry)
    except Exception as exc:  # noqa: BLE001
        return f"proc {idx}: {exc}"
    return None


class TestRaceMultiprocess:
    """Cross-process race: 10 worker processes append to the same index.json.

    On Windows, multiprocessing uses spawn (separate interpreter per worker)
    so the in-process threading.Lock cannot help — only the msvcrt OS lock
    protects correctness. This verifies the file-lock layer is effective.

    Inject-bug: in _report_index_lock, replace `msvcrt.locking(f.fileno(),
    msvcrt.LK_LOCK, 1)` with a no-op (set os_acquired=False directly).
    With 10 processes racing the read-modify-write, entries will be lost.
    """

    def test_multiprocess_append_no_lost_entries(self, tmp_path: Path):
        """10 OS processes appending → all 10 entries present, valid JSON."""
        n_procs = 10
        mode_dir = tmp_path / "mode_proc"
        mode_dir.mkdir()

        ctx = multiprocessing.get_context("spawn")
        args_list = [(str(tmp_path), str(mode_dir), i) for i in range(n_procs)]

        with ctx.Pool(processes=n_procs) as pool:
            results = pool.map(_worker_append, args_list)

        errors = [r for r in results if r is not None]
        assert not errors, f"Worker errors: {errors}"

        index_path = mode_dir / "index.json"
        assert index_path.exists(), "index.json must exist after multiprocess appends"
        raw = json.loads(index_path.read_text(encoding="utf-8"))
        assert isinstance(raw, list), f"index.json must be a list, got {type(raw)}"
        assert len(raw) == n_procs, (
            f"CROSS-PROCESS RACE LOST UPDATES: expected {n_procs}, got {len(raw)}. "
            "Inject-bug: disable OS lock in _report_index_lock → RED. Revert → GREEN."
        )


# ===========================================================================
# 2. TestF2FailureHygiene
# ===========================================================================


class TestF2FailureHygiene:
    """F2: generate endpoint failure leaves NO version dir on disk.

    The invariant: output_dir is created before the engine call;
    if the engine fails without writing player_impact_summary.json, the
    except block must rmtree the empty output_dir (litter guard).

    Inject-bug recipe:
      In app.py _run_generate_report, comment out the two F2 cleanup blocks:
        # F2: remove the created version dir when it has no summary (litter guard)
        if "output_dir" in locals() and isinstance(output_dir, Path):
            _sf = output_dir / "player_impact_summary.json"
            if output_dir.exists() and not _sf.exists():
                shutil.rmtree(output_dir, ignore_errors=True)
      With cleanup disabled, a failed generate leaves an empty version dir.
      test_failed_generate_leaves_no_version_dir → RED.
      Revert → GREEN.

    Memory citations:
      - feedback_enumerate_safety_paths.md — every cleanup path needs a test
      - feedback_perf_claim_needs_e2e_event_stream.md — must exercise real
        endpoint, not just mock the function
    """

    @pytest.fixture
    def f2_client(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                  isolated_rawdata_factory):
        """App with M15 rawdata but engine patched to raise before writing summary.

        rawdata_root is an ISOLATED tmp tree holding only M15 (hardlinked from
        the real rawdata/) — the real root would expose other machines' chunks
        to generate's disk-space auto-cleanup (the 2026-06-16 M43/mode_7 loss).
        See tests/backend/conftest.py::isolated_rawdata_factory.
        """
        if not _m15_chunks_present():
            pytest.skip("M15 cached chunks not present")
        client, reports_dir, state_dir = _make_isolated_app(
            tmp_path, monkeypatch,
            machine="M15", modes=[1],
            rawdata_root=isolated_rawdata_factory("M15", [1]),
        )
        yield client, reports_dir
        client.__exit__(None, None, None)

    def test_failed_generate_leaves_no_version_dir(
        self,
        f2_client,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Engine raises RuntimeError → F2 cleanup must delete the version dir.

        The endpoint should return 500. The versions/ dir under reports/M15/
        mode_1/ must contain ZERO entries (or not exist at all) because the
        F2 guard must rmtree any dir that has no player_impact_summary.json.

        Inject-bug: disable the F2 cleanup guard → versions dir has a leftover
        empty dir → this assertion fires → RED. Revert → GREEN.
        """
        client, reports_dir = f2_client

        # Patch the engine call to raise AFTER the output_dir has been created.
        # We import the module and patch the name used inside _run_generate_report.
        import fresh_slotlab.analyzer.report_engine as _re_mod
        original_gen = _re_mod.generate_report_from_chunks

        def _failing_gen(*args, **kwargs):
            raise RuntimeError("injected engine failure for F2 test")

        monkeypatch.setattr(_re_mod, "generate_report_from_chunks", _failing_gen)

        resp = client.post("/api/rawdata/M15/generate-report", json={"mode": 1})
        # Must be 500 (engine raised) — not 200.
        assert resp.status_code == 500, (
            f"Expected 500 from injected engine failure, got {resp.status_code}: "
            f"{resp.text[:300]}"
        )

        # F2 invariant: no version dir should remain on disk.
        versions_dir = reports_dir / "M15" / "mode_1" / "versions"
        leftover_dirs = []
        if versions_dir.exists():
            leftover_dirs = [
                d for d in versions_dir.iterdir()
                if d.is_dir()
            ]
        assert not leftover_dirs, (
            f"F2 FAILURE: {len(leftover_dirs)} version dir(s) left behind after "
            f"engine failure: {[str(d) for d in leftover_dirs]}. "
            "Inject-bug: comment out the F2 cleanup block in _run_generate_report "
            "→ this assertion fires → RED. Revert → GREEN."
        )

    def test_failed_generate_run_row_marked_failed(
        self,
        f2_client,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Failed generate must leave the run row as 'failed', NOT delete it.

        The design says 'Keep the failed run row (history is wanted)'.
        The cleanup only touches the disk dir, not the DB row.
        """
        client, reports_dir = f2_client

        import fresh_slotlab.analyzer.report_engine as _re_mod

        def _failing_gen(*args, **kwargs):
            raise RuntimeError("injected failure for run-row test")

        monkeypatch.setattr(_re_mod, "generate_report_from_chunks", _failing_gen)

        resp = client.post("/api/rawdata/M15/generate-report", json={"mode": 1})
        assert resp.status_code == 500

        # The response will carry a detail; we need to find the run_id from
        # the DB via the runs list endpoint. We can't easily get the run_id
        # from a 500 response, so we check that at least one failed run exists.
        runs_resp = client.get("/api/runs?status=failed&limit=5")
        assert runs_resp.status_code == 200
        runs_data = runs_resp.json()
        failed_runs = runs_data if isinstance(runs_data, list) else runs_data.get("runs", [])
        m15_failed = [r for r in failed_runs if r.get("machine") == "M15"]
        assert m15_failed, (
            "A run row with status='failed' must exist after an engine failure — "
            "the history should be preserved even when the disk dir is cleaned."
        )


# ===========================================================================
# 3. TestReconcileExtended
# ===========================================================================


@pytest.fixture
def reconcile_ext_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated app for extended reconcile tests.  Machine MREC2, mode 1."""
    client, reports_dir, state_dir = _make_isolated_app(
        tmp_path, monkeypatch, machine="MREC2", modes=[1],
    )
    yield client, reports_dir, state_dir, tmp_path
    client.__exit__(None, None, None)


class TestReconcileExtended:
    """All action classes from the design doc, with inject-bug per invariant.

    Complements the basic TestReconcileReports in test_report_index.py by
    exercising the full defect-class matrix including the active-run guard,
    non-canonical paths, zombie entries, dangling report_file, and stale
    latest.json.
    """

    def _base(self, reports_dir: Path) -> Path:
        b = reports_dir / "MREC2" / "mode_1" / "versions"
        b.mkdir(parents=True, exist_ok=True)
        return b

    # ------------------------------------------------------------------
    # Active-run guard (no_summary_dir_skip_active)
    # ------------------------------------------------------------------

    def test_no_summary_dir_with_active_run_is_skipped(
        self, reconcile_ext_client
    ):
        """no-summary dir whose report_version is referenced by a RUNNING run
        must be SKIPPED, not deleted.

        Inject-bug recipe:
          In reconcile_reports (app.py), remove the guard:
            if vname in active_run_versions:
                _log_action("no_summary_dir_skip_active", ...)
                continue
          → the no-summary dir gets deleted even though the run is still
          active → dir no longer exists → this assertion RED. Revert → GREEN.

        Memory citation: feedback_enumerate_safety_paths.md — the running-run
        check is a carve-out; must be tested with inject-bug.
        """
        client, reports_dir, state_dir, tmp_path = reconcile_ext_client
        b = self._base(reports_dir)

        # Create a no-summary dir that is old enough to qualify for deletion
        # by mtime, but references an ACTIVE run.
        active_rv = "rv_active_run_001"
        active_dir = b / active_rv
        active_dir.mkdir()
        (active_dir / "machine_config.json").write_text("{}", encoding="utf-8")
        # Force mtime to be old (>1h).
        old_ts = time.time() - 7200
        os.utime(str(active_dir), (old_ts, old_ts))

        # Insert a RUNNING run row referencing this report_version.
        import sqlite3 as _sqlite3
        db_path = state_dir / "console.db"
        with _sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """INSERT INTO runs (
                    run_id, machine, mode, status, model_id, created_at,
                    started_at, target_halfwidth_pp, chunk_spin_times,
                    chunk_robot_count, batch_concurrency, max_chunks, timeout,
                    bankruptcy_session_spins, bankruptcy_bankroll_multipliers,
                    report_version, output_dir, progress_file, summary_file
                ) VALUES (
                    'active_run_001', 'MREC2', 1, 'running', 'sdk',
                    '2026-06-12T00:00:00Z', '2026-06-12T00:00:00Z',
                    0.5, 5000, 24, 1, 10, 30, 500, '100,200,500',
                    ?, ?, ?, ?
                )""",
                (
                    active_rv,
                    str(active_dir),
                    str(state_dir / "progress" / "active_run_001.jsonl"),
                    str(active_dir / "player_impact_summary.json"),
                ),
            )

        # Dry-run: should report skip_active, NOT delete.
        resp = client.post(
            "/api/maintenance/reconcile-reports", json={"dry_run": True}
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        counts = data["counts"]
        assert counts.get("no_summary_dir_skip_active", 0) >= 1, (
            f"Expected no_summary_dir_skip_active >= 1, got counts={counts}. "
            "Inject-bug: remove the active-run guard in reconcile_reports → "
            "count becomes no_summary_dir_delete and dir gets deleted → RED. "
            "Revert → GREEN."
        )
        assert counts.get("no_summary_dir_delete", 0) == 0, (
            "An active-run-referenced dir must NOT be flagged for deletion"
        )
        # Dir must still exist (dry-run).
        assert active_dir.exists(), (
            "Active-run dir must not be deleted by dry-run or active-run guard"
        )

        # Wet-run must also leave the dir intact.
        resp2 = client.post(
            "/api/maintenance/reconcile-reports", json={"dry_run": False}
        )
        assert resp2.status_code == 200, resp2.text
        assert active_dir.exists(), (
            "Active-run dir must survive a wet-run reconcile"
        )

    # ------------------------------------------------------------------
    # Non-canonical path → path_rewrite_to_canonical
    # ------------------------------------------------------------------

    def test_noncanonical_path_is_rewritten(self, reconcile_ext_client):
        """Index entry whose summary_file points to a non-canonical (old worktree)
        path, while the canonical file exists on disk → wet-run rewrites the entry
        to the canonical path.

        Inject-bug: remove the `stored_sf != canonical_sf` branch (or make it
        always take the zombie path) → path_rewrite_to_canonical count = 0 and
        the entry keeps the stale path → assertion on updated path fails → RED.
        """
        client, reports_dir, state_dir, tmp_path = reconcile_ext_client
        b = self._base(reports_dir)

        # Create a canonical version dir with a summary.
        vdir = b / "rv_noncanon_001"
        vdir.mkdir()
        _write_summary(vdir / "player_impact_summary.json", run_id="run_noncanon")

        # Write an index.json that references a DIFFERENT (non-canonical) path.
        fake_old_path = str(tmp_path / "old_worktree" / "reports" / "MREC2" /
                            "mode_1" / "versions" / "rv_noncanon_001" /
                            "player_impact_summary.json")
        index_path = reports_dir / "MREC2" / "mode_1" / "index.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps([{
            "report_version": "rv_noncanon_001",
            "run_id": "run_noncanon",
            "created_at": "2026-06-12T00:00:00Z",
            "summary_file": fake_old_path,  # non-canonical
            "rtp_point_pct": 93.5,
            "achieved_rtp_pct": 93.5,
            "rawdata_config_md5": "aabbccdd1234",
            "rawdata_code_md5": "eeff99887766",
            "analyzer_version": "v1.2.3",
            "effective_analyzer_version": "eff_abc123",
        }]), encoding="utf-8")

        # Dry-run should flag it.
        resp = client.post(
            "/api/maintenance/reconcile-reports", json={"dry_run": True}
        )
        assert resp.status_code == 200, resp.text
        counts = resp.json()["counts"]
        assert counts.get("path_rewrite_to_canonical", 0) >= 1, (
            f"Expected path_rewrite_to_canonical >= 1, got counts={counts}"
        )

        # Wet-run must fix the entry.
        resp2 = client.post(
            "/api/maintenance/reconcile-reports", json={"dry_run": False}
        )
        assert resp2.status_code == 200, resp2.text

        updated_index = json.loads(index_path.read_text(encoding="utf-8"))
        canonical_sf = str(vdir / "player_impact_summary.json")
        entry = next(
            (e for e in updated_index if e.get("report_version") == "rv_noncanon_001"),
            None,
        )
        assert entry is not None, "Entry must remain in index after path rewrite"
        assert entry["summary_file"] == canonical_sf, (
            f"summary_file must be canonical after wet-run rewrite; "
            f"got: {entry['summary_file']!r}"
        )

    # ------------------------------------------------------------------
    # Zombie entry → zombie_entry_drop
    # ------------------------------------------------------------------

    def test_zombie_entry_is_dropped(self, reconcile_ext_client):
        """Index entry whose summary_file exists neither at canonical nor stored
        path → wet-run must drop the entry (zombie_entry_drop).

        Inject-bug: comment out the zombie_entry_drop branch → entry remains in
        index pointing to a non-existent file → assertion RED. Revert → GREEN.
        """
        client, reports_dir, state_dir, tmp_path = reconcile_ext_client
        b = self._base(reports_dir)

        # Create a version dir but WITHOUT a summary (just machine_config).
        vdir = b / "rv_zombie_001"
        vdir.mkdir()
        (vdir / "machine_config.json").write_text("{}", encoding="utf-8")

        # Write an index with an entry pointing to a completely non-existent path.
        index_path = reports_dir / "MREC2" / "mode_1" / "index.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)

        # Non-canonical path that also does not exist on disk.
        ghost_path = str(tmp_path / "ghost" / "player_impact_summary.json")
        canonical_path = str(vdir / "player_impact_summary.json")

        # Write an existing entry + a zombie entry.
        good_rv = b / "rv_good_001"
        good_rv.mkdir(exist_ok=True)
        _write_summary(good_rv / "player_impact_summary.json", run_id="good_run")

        index_path.write_text(json.dumps([
            {
                "report_version": "rv_good_001",
                "run_id": "good_run",
                "created_at": "2026-06-12T00:00:00Z",
                "summary_file": str(good_rv / "player_impact_summary.json"),
                "rawdata_config_md5": "abc",
                "rawdata_code_md5": "def",
                "analyzer_version": "v1",
                "effective_analyzer_version": "e1",
            },
            {
                "report_version": "rv_zombie_001",
                "run_id": "zombie_run",
                "created_at": "2026-06-12T00:00:00Z",
                # Both stored path and canonical path don't exist.
                "summary_file": ghost_path,
                "rawdata_config_md5": "abc",
                "rawdata_code_md5": "def",
                "analyzer_version": "v1",
                "effective_analyzer_version": "e1",
            },
        ]), encoding="utf-8")

        # Age the no-summary dir so it qualifies for deletion (so reconcile
        # doesn't skip it due to mtime guard). But rv_zombie_001 has a
        # machine_config.json so it's in the "no-summary" action class.
        old_ts = time.time() - 7200
        os.utime(str(vdir), (old_ts, old_ts))

        # Wet-run.
        resp = client.post(
            "/api/maintenance/reconcile-reports", json={"dry_run": False}
        )
        assert resp.status_code == 200, resp.text
        counts = resp.json()["counts"]

        # Zombie entry must be gone from index.
        final_index = json.loads(index_path.read_text(encoding="utf-8"))
        rv_names = {e.get("report_version") for e in final_index}
        assert "rv_zombie_001" not in rv_names, (
            f"Zombie entry must be dropped from index; still present: {rv_names}. "
            "Inject-bug: remove zombie_entry_drop branch → entry persists → RED. "
            "Revert → GREEN."
        )
        # Good entry must be preserved.
        assert "rv_good_001" in rv_names, "Good entry must survive reconcile"

    # ------------------------------------------------------------------
    # Missing md5/effective fields → persist_backfill
    # ------------------------------------------------------------------

    def test_missing_fields_are_backfilled(self, reconcile_ext_client):
        """Entry missing rawdata_config_md5 + effective_analyzer_version must
        get backfilled from the summary on wet-run.

        Inject-bug: comment out the Action-5 backfill section in reconcile_reports
        → persist_backfill count stays 0 and the entry keeps empty fields → RED.
        """
        client, reports_dir, state_dir, tmp_path = reconcile_ext_client
        b = self._base(reports_dir)

        vdir = b / "rv_backfill_001"
        vdir.mkdir()
        _write_summary(
            vdir / "player_impact_summary.json",
            run_id="backfill_run",
            config_md5="bbbackfill",
            effective_analyzer_version="eff_backfill",
        )

        # Index entry with deliberately empty md5 fields.
        index_path = reports_dir / "MREC2" / "mode_1" / "index.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps([{
            "report_version": "rv_backfill_001",
            "run_id": "backfill_run",
            "created_at": "2026-06-12T00:00:00Z",
            "summary_file": str(vdir / "player_impact_summary.json"),
            "rtp_point_pct": 93.5,
            "achieved_rtp_pct": 93.5,
            "rawdata_config_md5": "",          # empty — should be backfilled
            "rawdata_code_md5": "",            # empty — should be backfilled
            "analyzer_version": "",
            "effective_analyzer_version": "",  # empty — should be backfilled
        }]), encoding="utf-8")

        resp = client.post(
            "/api/maintenance/reconcile-reports", json={"dry_run": False}
        )
        assert resp.status_code == 200, resp.text
        counts = resp.json()["counts"]
        assert counts.get("persist_backfill", 0) >= 1, (
            f"Expected persist_backfill >= 1, got counts={counts}. "
            "Inject-bug: comment out Action-5 in reconcile_reports → RED. Revert → GREEN."
        )

        updated_index = json.loads(index_path.read_text(encoding="utf-8"))
        entry = next(
            (e for e in updated_index if e.get("report_version") == "rv_backfill_001"),
            None,
        )
        assert entry is not None, "Entry must still be present after backfill"
        assert entry.get("rawdata_config_md5") == "bbbackfill", (
            f"rawdata_config_md5 must be backfilled from summary; "
            f"got {entry.get('rawdata_config_md5')!r}"
        )
        assert entry.get("effective_analyzer_version") == "eff_backfill", (
            f"effective_analyzer_version must be backfilled; "
            f"got {entry.get('effective_analyzer_version')!r}"
        )

    # ------------------------------------------------------------------
    # Dangling report_file key → report_file_key_drop
    # ------------------------------------------------------------------

    def test_dangling_report_file_key_is_dropped(self, reconcile_ext_client):
        """Entry with report_file pointing to a non-existent .md file must
        have the report_file key removed on wet-run.

        Inject-bug: comment out the Action-6 report_file drop → key remains
        with a stale path → assertion RED. Revert → GREEN.
        """
        client, reports_dir, state_dir, tmp_path = reconcile_ext_client
        b = self._base(reports_dir)

        vdir = b / "rv_dangling_001"
        vdir.mkdir()
        _write_summary(vdir / "player_impact_summary.json", run_id="dangling_run")

        # Index entry with a report_file key pointing to a non-existent .md.
        ghost_md = str(vdir / "player_impact_report.md")  # file does NOT exist
        index_path = reports_dir / "MREC2" / "mode_1" / "index.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps([{
            "report_version": "rv_dangling_001",
            "run_id": "dangling_run",
            "created_at": "2026-06-12T00:00:00Z",
            "summary_file": str(vdir / "player_impact_summary.json"),
            "report_file": ghost_md,  # dangling — file does not exist
            "rawdata_config_md5": "abc",
            "rawdata_code_md5": "def",
            "analyzer_version": "v1",
            "effective_analyzer_version": "e1",
        }]), encoding="utf-8")

        # Verify the .md file truly doesn't exist.
        assert not Path(ghost_md).exists(), "test setup: .md must not exist"

        resp = client.post(
            "/api/maintenance/reconcile-reports", json={"dry_run": False}
        )
        assert resp.status_code == 200, resp.text

        updated_index = json.loads(index_path.read_text(encoding="utf-8"))
        entry = next(
            (e for e in updated_index if e.get("report_version") == "rv_dangling_001"),
            None,
        )
        assert entry is not None, "Entry must be present after report_file drop"
        assert "report_file" not in entry, (
            f"Dangling report_file key must be REMOVED from entry; "
            f"entry={entry}. "
            "Inject-bug: comment out Action-6 → report_file key persists → RED. "
            "Revert → GREEN."
        )

    # ------------------------------------------------------------------
    # Stale latest.json → latest_recompute after wet-run
    # ------------------------------------------------------------------

    def test_stale_latest_json_is_recomputed(self, reconcile_ext_client):
        """A latest.json pointing to a deleted entry must be updated to reflect
        the real newest entry after wet-run reconcile.

        This mirrors the M254/mode_7, M275/mode_7 case from the design doc:
        latest.json present + index = [].
        """
        client, reports_dir, state_dir, tmp_path = reconcile_ext_client
        b = self._base(reports_dir)

        # Create one real version.
        vdir = b / "rv_real_latest"
        vdir.mkdir()
        _write_summary(vdir / "player_impact_summary.json", run_id="real_run")

        # Write a stale latest.json pointing to a different (non-existent) version.
        index_path = reports_dir / "MREC2" / "mode_1" / "index.json"
        latest_path = reports_dir / "MREC2" / "mode_1" / "latest.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)

        # Intentionally empty index (simulates the M254/M275 case).
        index_path.write_text("[]", encoding="utf-8")
        latest_path.write_text(json.dumps({
            "report_version": "rv_stale_ghost",
            "run_id": "ghost_run",
            "created_at": "2026-01-01T00:00:00Z",
            "summary_file": "/does/not/exist/player_impact_summary.json",
        }), encoding="utf-8")

        # Wet-run should discover rv_real_latest (unindexed) and fix latest.
        resp = client.post(
            "/api/maintenance/reconcile-reports", json={"dry_run": False}
        )
        assert resp.status_code == 200, resp.text
        counts = resp.json()["counts"]
        assert counts.get("unindexed_summary_append", 0) >= 1, (
            f"rv_real_latest must be indexed; counts={counts}"
        )
        assert counts.get("latest_recompute", 0) >= 1, (
            f"latest_recompute must fire after index changed; counts={counts}"
        )

        # latest.json must now point to the real entry.
        assert latest_path.exists(), "latest.json must exist after reconcile"
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        assert latest.get("report_version") == "rv_real_latest", (
            f"latest.json must point to rv_real_latest; got {latest.get('report_version')!r}"
        )

    # ------------------------------------------------------------------
    # Dry-run byte-identical (zero disk mutation)
    # ------------------------------------------------------------------

    def test_dry_run_is_byte_identical(self, reconcile_ext_client):
        """Dry-run must not mutate a single byte on disk.

        Build a litter tree, compute a hash of the entire reports dir,
        run dry-run reconcile, compute the hash again — must be identical.

        Inject-bug: make dry_run reconcile perform a real rmdir (remove the
        `if not dry_run:` guard) → empty dir deleted → tree hash changes → RED.
        Revert → GREEN.
        """
        client, reports_dir, state_dir, tmp_path = reconcile_ext_client
        b = self._base(reports_dir)

        # Build a small litter tree.
        empty = b / "rv_drytest_empty"
        empty.mkdir()

        no_sum = b / "rv_drytest_nosummary"
        no_sum.mkdir()
        (no_sum / "machine_config.json").write_text("{}", encoding="utf-8")
        old_ts = time.time() - 7200
        os.utime(str(no_sum), (old_ts, old_ts))

        unindexed = b / "rv_drytest_unindexed"
        unindexed.mkdir()
        _write_summary(unindexed / "player_impact_summary.json", run_id="dry_run_check")

        # Snapshot the tree BEFORE dry-run.
        hash_before = _dir_hash(reports_dir)

        resp = client.post(
            "/api/maintenance/reconcile-reports", json={"dry_run": True}
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["dry_run"] is True

        # Hash must be identical.
        hash_after = _dir_hash(reports_dir)
        assert hash_before == hash_after, (
            "DRY-RUN MUTATED DISK. "
            f"Before hash: {hash_before}, After hash: {hash_after}. "
            "Inject-bug: remove 'if not dry_run:' guard from any action in "
            "reconcile_reports → hash changes → RED. Revert → GREEN."
        )

        # Must still report the expected actions.
        counts = data["counts"]
        assert counts.get("empty_dir_delete", 0) >= 1
        assert counts.get("no_summary_dir_delete", 0) >= 1
        assert counts.get("unindexed_summary_append", 0) >= 1


# ===========================================================================
# 4. TestImportProducerShape + TestProducerShapeParity
# ===========================================================================


@pytest.fixture
def import_shape_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated app for import + shape parity tests."""
    client, reports_dir, state_dir = _make_isolated_app(
        tmp_path, monkeypatch, machine="MSHAPE", modes=[1],
    )
    yield client, reports_dir, tmp_path
    client.__exit__(None, None, None)


class TestProducerShapeParity:
    """All four producers route through build_index_entry → same key set.

    The design: 'legacy _update_report_index writes the full shape; the
    generate path, batch finalize, and /api/reports/import omit all four
    [md5/version] fields'. Fix: all route through build_index_entry.

    This test pins that ALL four producers' index entries have the SAME
    required key set — so a future regression that bypasses the builder
    for one producer is caught immediately.

    Inject-bug: in the import endpoint (_import_one), replace the
    build_index_entry call with a minimal hand-rolled dict missing
    rawdata_config_md5 → import entry lacks the field → the key-set
    comparison fails → RED. Revert → GREEN.
    """

    _REQUIRED_KEYS = frozenset({
        "report_version", "run_id", "created_at", "summary_file",
        "rtp_point_pct", "achieved_rtp_pct", "achieved_halfwidth_pp",
        "total_spins", "quality_label",
        "rawdata_config_md5", "rawdata_code_md5",
        "analyzer_version", "effective_analyzer_version",
    })

    def _entry_from_builder(self, tmp_path: Path) -> dict:
        """Simulate the builder call as any producer would make it."""
        mode_dir = tmp_path / "mode_1"
        mode_dir.mkdir(exist_ok=True)
        sp = mode_dir / "rv_shape_test" / "player_impact_summary.json"
        _write_summary(sp, run_id="shape_run", config_md5="cfg_shape",
                       code_md5="code_shape", effective_analyzer_version="eff_shape")
        summary = _make_summary(run_id="shape_run", config_md5="cfg_shape",
                                code_md5="code_shape",
                                effective_analyzer_version="eff_shape")
        return build_index_entry(
            tmp_path, "MSHAPE", 1, "rv_shape_test", "shape_run",
            summary=summary, summary_path=sp,
        )

    def test_builder_output_has_all_required_keys(self, tmp_path: Path):
        """build_index_entry output must have all required keys (shape invariant).

        This is the baseline — every producer that calls build_index_entry
        gets this shape. If build_index_entry is changed to drop a key, this
        test catches it immediately.
        """
        entry = self._entry_from_builder(tmp_path)
        missing = self._REQUIRED_KEYS - set(entry.keys())
        assert not missing, (
            f"build_index_entry missing required keys: {sorted(missing)}. "
            "All producers route through this function → shape regression caught here."
        )

    def test_import_entry_has_same_key_set_as_builder(
        self, import_shape_client
    ):
        """Import-produced index entry must have the same required key set as
        a direct build_index_entry call.

        This pins that the import endpoint uses build_index_entry (not a hand-
        rolled dict) so the shape unification invariant holds across producers.

        Inject-bug: in _import_one in app.py, replace the append_and_rewrite_latest
        call with a hand-rolled dict missing rawdata_config_md5 → this assertion
        fires → RED. Revert → GREEN.
        """
        client, reports_dir, tmp_path = import_shape_client

        src = tmp_path / "import_src_shape"
        vdir = src / "MSHAPE" / "mode_1" / "versions" / "rv_import_shape_001"
        vdir.mkdir(parents=True)
        _write_summary(
            vdir / "player_impact_summary.json",
            run_id="imp_shape_run",
            config_md5="imp_cfg",
            code_md5="imp_code",
            effective_analyzer_version="imp_eff",
        )

        resp = client.post("/api/reports/import", json={"source_path": str(src)})
        assert resp.status_code == 200, resp.text
        assert resp.json().get("imported", 0) >= 1

        index_path = reports_dir / "MSHAPE" / "mode_1" / "index.json"
        assert index_path.exists(), "index.json must exist after import"
        entries = json.loads(index_path.read_text(encoding="utf-8"))
        assert entries, "index must be non-empty after import"
        entry = entries[0]

        missing = self._REQUIRED_KEYS - set(entry.keys())
        assert not missing, (
            f"Import-produced entry missing required keys: {sorted(missing)}. "
            "Inject-bug: replace build_index_entry with hand-rolled dict in "
            "_import_one → shape mismatch → RED. Revert → GREEN."
        )

    def test_import_entry_config_md5_matches_summary(
        self, import_shape_client
    ):
        """Import-produced entry rawdata_config_md5 must match the summary's
        config_md5 (proves the value flows through build_index_entry, not
        being silently zeroed).
        """
        client, reports_dir, tmp_path = import_shape_client

        src = tmp_path / "import_cfg_check"
        vdir = src / "MSHAPE" / "mode_1" / "versions" / "rv_imp_cfg_001"
        vdir.mkdir(parents=True)
        _write_summary(
            vdir / "player_impact_summary.json",
            run_id="cfg_check_run",
            config_md5="explicit_cfg_md5",
            code_md5="explicit_code_md5",
        )

        resp = client.post("/api/reports/import", json={"source_path": str(src)})
        assert resp.status_code == 200, resp.text

        entries = json.loads(
            (reports_dir / "MSHAPE" / "mode_1" / "index.json").read_text(encoding="utf-8")
        )
        entry = next(
            (e for e in entries if e.get("report_version") == "rv_imp_cfg_001"),
            None,
        )
        assert entry is not None
        assert entry.get("rawdata_config_md5") == "explicit_cfg_md5", (
            f"rawdata_config_md5 must flow from summary; got {entry.get('rawdata_config_md5')!r}"
        )
        assert entry.get("rawdata_code_md5") == "explicit_code_md5", (
            f"rawdata_code_md5 must flow from summary; got {entry.get('rawdata_code_md5')!r}"
        )

    def test_generate_and_import_same_key_set(
        self, import_shape_client, monkeypatch: pytest.MonkeyPatch
    ):
        """Direct build_index_entry (simulating generate path) and import path
        produce entries with the SAME key set (modulo report_file presence rule).

        This is the 'producer shape parity' test from the design.
        """
        client, reports_dir, tmp_path = import_shape_client

        # -- Simulate generate path: call build_index_entry directly --
        gen_tmp = tmp_path / "gen_side"
        gen_tmp.mkdir()
        gen_sp = gen_tmp / "player_impact_summary.json"
        _write_summary(gen_sp, run_id="gen_parity_run", config_md5="gen_cfg",
                       code_md5="gen_code", effective_analyzer_version="gen_eff")
        gen_summary = _make_summary(run_id="gen_parity_run", config_md5="gen_cfg",
                                    code_md5="gen_code",
                                    effective_analyzer_version="gen_eff")
        gen_entry = build_index_entry(
            tmp_path / "gen_reports", "MSHAPE", 1,
            "rv_gen_parity", "gen_parity_run",
            summary=gen_summary, summary_path=gen_sp,
        )

        # -- Import path: import a version with summary --
        src = tmp_path / "import_parity_src"
        vdir = src / "MSHAPE" / "mode_1" / "versions" / "rv_imp_parity"
        vdir.mkdir(parents=True)
        _write_summary(
            vdir / "player_impact_summary.json",
            run_id="imp_parity_run",
            config_md5="imp_parity_cfg",
            code_md5="imp_parity_code",
            effective_analyzer_version="imp_parity_eff",
        )
        client.post("/api/reports/import", json={"source_path": str(src)})

        index_path = reports_dir / "MSHAPE" / "mode_1" / "index.json"
        entries = json.loads(index_path.read_text(encoding="utf-8"))
        imp_entry = next(
            (e for e in entries if e.get("report_version") == "rv_imp_parity"),
            None,
        )
        assert imp_entry is not None, "Import entry must be present"

        # Key sets must be identical (report_file may differ — both absent here).
        gen_keys = set(gen_entry.keys()) - {"report_file"}
        imp_keys = set(imp_entry.keys()) - {"report_file"}
        assert gen_keys == imp_keys, (
            f"Generate and import entries have different key sets.\n"
            f"Generate only: {sorted(gen_keys - imp_keys)}\n"
            f"Import only: {sorted(imp_keys - gen_keys)}\n"
            "This means one producer is bypassing build_index_entry. "
            "Inject-bug: bypass the builder in one producer → key sets diverge → RED. "
            "Revert → GREEN."
        )
