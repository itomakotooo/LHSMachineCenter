"""Phase 1 deploy integration tests.

Covers the migrations from raw ``write_text`` / ``write_json`` to
``atomic_json_write`` / ``atomic_json_read_modify_write``, plus the
SQLite WAL mode, vendored chart.js, and the cross-process
``msvcrt.locking`` on rawdata_index.

Inject-bug verification (per
``memory/feedback_enumerate_safety_paths.md``):
- The cross-process rawdata_index test is the regression for the
  v1-designer-proposed mtime-retry approach (which W3 critic CI-3
  flagged as insufficient on NTFS 100ns). Manual inject-bug: remove
  the ``with _cross_process_index_lock`` from
  ``fresh_slotlab.rawdata_index.update_entry`` and rerun this test →
  cross-process test should occasionally drop an entry (probability
  depends on timing; run 10 times to observe). Restore the lock → 0
  drops over 10 runs.

Cross-refs:
- ``session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md`` §4.2
- ``session_artifacts/_arch/deploy/05_deploy_critique.md`` CI-3 (NTFS mtime gap)
- ``session_artifacts/_arch/deploy/03_deploy_concurrency_blast_radius.md`` Scenario 2 (H3)
- ``memory/feedback_enumerate_safety_paths.md``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from fresh_slotlab.rawdata_index import INDEX_FILENAME, entry_key, load_index


# Repo root so subprocess imports work (PYTHONPATH includes us).
ROOT = Path(__file__).resolve().parents[2]


class TestSQLiteWALMode:
    """Phase 1 deliverable #10: WAL mode + busy_timeout enabled in
    StateStore._init_db. Required for <10 planners hitting the DB
    in parallel without blocking each other.
    """

    def test_wal_mode_enabled_after_init(self, tmp_path: Path):
        from src.web_console.backend.app import StateStore

        store = StateStore(tmp_path / "test.db")
        conn = store._connect()
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal", f"expected wal, got {mode}"
        finally:
            conn.close()

    def test_busy_timeout_set(self, tmp_path: Path):
        from src.web_console.backend.app import StateStore

        store = StateStore(tmp_path / "test.db")
        conn = store._connect()
        try:
            timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert timeout == 5000, f"expected 5000ms, got {timeout}"
        finally:
            conn.close()

    def test_wal_sidecars_created_after_writes(self, tmp_path: Path):
        """After a write, WAL mode creates .db-wal + .db-shm sidecars.
        Documenting this so the deploy README explicitly mentions
        local-disk-only requirement (no SMB/CIFS)."""
        from src.web_console.backend.app import StateStore

        db_path = tmp_path / "test.db"
        store = StateStore(db_path)
        # Trigger a write through the public API surface — easiest is to
        # access the connection and write to a known table.
        conn = store._connect()
        try:
            conn.execute(
                "INSERT INTO runs (run_id, machine, mode, status, model_id, "
                "created_at, started_at, target_halfwidth_pp, chunk_spin_times, "
                "chunk_robot_count, batch_concurrency, max_chunks, timeout, "
                "bankruptcy_session_spins, bankruptcy_bankroll_multipliers, "
                "report_version, output_dir, progress_file) "
                "VALUES ('r1', 'M1', 1, 'queued', 'm', 't1', 't2', 1.0, 1000, 8, 1, 1, 60, 1000, '[]', 'v1', '/x', '/y')"
            )
            conn.commit()
        finally:
            conn.close()
        # WAL sidecar files should now exist
        assert (tmp_path / "test.db-wal").exists(), (
            "WAL sidecar missing — PRAGMA journal_mode=WAL silently failed?"
        )


class TestChartJsVendored:
    """Phase 1 deliverable #9: chart.min.js vendored locally so intranet
    deploys don't depend on CDN access."""

    def test_chart_min_js_file_exists(self):
        chart_path = ROOT / "src" / "web_console" / "frontend" / "vendor" / "chart.min.js"
        assert chart_path.is_file(), f"chart.min.js missing at {chart_path}"

    def test_chart_min_js_is_real_bundle(self):
        """Sanity check: the vendored file is actually chart.js, not an
        accidental placeholder. UMD bundle is ~200KB and starts with
        ``/*!`` license comment."""
        chart_path = ROOT / "src" / "web_console" / "frontend" / "vendor" / "chart.min.js"
        size = chart_path.stat().st_size
        assert size > 100_000, f"chart.min.js too small: {size} bytes"
        head = chart_path.read_text(encoding="utf-8")[:200]
        assert "chart" in head.lower() or "Chart" in head, (
            f"chart.min.js doesn't look like a chart.js bundle: {head[:80]}"
        )

    def test_index_html_references_local_vendor(self):
        """index.html must NOT reference the CDN anymore."""
        index_path = ROOT / "src" / "web_console" / "frontend" / "index.html"
        content = index_path.read_text(encoding="utf-8")
        assert "cdn.jsdelivr.net" not in content, "CDN reference still present"
        assert "/console/vendor/chart.min.js" in content, "Local vendor path missing"


class TestRawdataIndexCrossProcess:
    """Phase 1 deliverable #7 / R3: cross-process msvcrt.locking on
    rawdata/_index.json prevents lost-update race when N
    ProcessPoolExecutor workers complete near-simultaneously.

    Replaces v1-designer's mtime-retry approach which was insufficient
    on NTFS 100ns granularity (W3 critic CI-3).

    NOTE: The within-process tests in test_rawdata_index.py cover the
    threading.Lock layer. THIS test specifically targets the OS-level
    lock by spawning real subprocesses against a shared rawdata root.
    """

    def test_concurrent_subprocess_writes_no_lost_entries(self, tmp_path: Path):
        """Spawn 4 subprocesses, each calling update_entry for a
        different (machine, mode) on the same rawdata root. Without
        the cross-process lock, the read-modify-write of _index.json
        races and entries are silently lost.

        Manual inject-bug: remove ``with _cross_process_index_lock`` from
        update_entry → run 10 times and observe occasional dropped entries.
        """
        # Seed chunks for 4 distinct (machine, mode) cells. Each
        # subprocess will then call update_entry on its own cell — the
        # _index.json is the contention point.
        from fresh_slotlab.analyzer.core.writer import _save_chunk_cache

        cells = [("M1", 1), ("M2", 1), ("M3", 1), ("M4", 1)]
        for machine, mode in cells:
            mode_dir = tmp_path / machine / f"mode_{mode}"
            mode_dir.mkdir(parents=True)
            # _save_chunk_cache will trigger update_entry internally,
            # but we want to set up state BEFORE the concurrent test.
            # So we just create a chunk file manually with the minimal
            # envelope shape:
            chunk_path = mode_dir / "chunk_0001.json"
            chunk_path.write_text(
                json.dumps({
                    "response": [{
                        "roundResult": json.dumps([{
                            "BetAmount": 1000,
                            "CurrentWin": 0,
                            "SpinType": "Normal",
                        }])
                    }],
                    "_spin_times": 1000,
                    "_config_md5": "abc",
                    "_code_md5": "def",
                    "_saved_at": "2026-05-15T00:00:00Z",
                }),
                encoding="utf-8",
            )
        # Delete any index that auto-update would have written so we
        # start clean for the concurrent test.
        idx_path = tmp_path / INDEX_FILENAME
        if idx_path.exists():
            idx_path.unlink()

        # Spawn 4 subprocesses each updating its own cell's entry.
        # Use a small inline Python script via -c.
        script = textwrap.dedent("""
            import sys
            from pathlib import Path
            sys.path.insert(0, r"{root}")
            from fresh_slotlab.rawdata_index import update_entry
            root_path = Path(r"{tmp}")
            machine = sys.argv[1]
            mode = int(sys.argv[2])
            chunk_dir = root_path / machine / f"mode_{{mode}}"
            update_entry(root_path, machine, mode, chunk_dir)
        """).format(root=str(ROOT), tmp=str(tmp_path)).strip()

        env = os.environ.copy()
        procs = []
        for machine, mode in cells:
            p = subprocess.Popen(
                [sys.executable, "-c", script, machine, str(mode)],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            procs.append((p, machine, mode))

        # Wait for all to complete (60s timeout per subprocess; plenty
        # for what's a sub-second op).
        for p, machine, mode in procs:
            try:
                stdout, stderr = p.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                p.kill()
                pytest.fail(f"subprocess for {machine}|{mode} timed out")
            if p.returncode != 0:
                pytest.fail(
                    f"subprocess for {machine}|{mode} failed: "
                    f"stderr={stderr.decode()[:500]}"
                )

        # All 4 entries must be present in the final index. Without
        # the cross-process lock, 1-2 could be silently lost.
        idx = load_index(tmp_path)
        missing = [
            entry_key(m, mode) for m, mode in cells
            if entry_key(m, mode) not in idx["entries"]
        ]
        assert not missing, (
            f"Cross-process race lost entries: {missing}. "
            f"Got {sorted(idx['entries'].keys())}. "
            f"This is the H3/R3 lost-update regression — the "
            f"msvcrt.locking layer in _cross_process_index_lock was "
            f"either removed or failed silently."
        )

    def test_lock_helper_is_importable(self):
        """Smoke check: _cross_process_index_lock exists and is callable
        with a Path arg. Catches accidental removal of the helper."""
        from fresh_slotlab.rawdata_index import _cross_process_index_lock

        assert callable(_cross_process_index_lock)


class TestMachinesJsonScenario16:
    """Phase 1 deliverable #2 / Critical C1: ``machines.json`` non-atomic
    write race that could wipe all 393 rows.

    The fix is ``atomic_json_read_modify_write`` with per-file lock.
    This test simulates the Scenario 16 race directly against the
    atomic API.
    """

    def test_concurrent_refresh_no_lost_entries(self, tmp_path: Path):
        """Simulates: 2 threads doing the equivalent of refresh-md5
        concurrently. Each reads existing machines.json, updates a
        different machine's md5, writes back. Without the per-file
        lock, one writer's update would be overwritten.

        Each "refresh" appends a new machine row to the list. After
        N concurrent refreshes, all N rows must be present.
        """
        import threading
        from src.web_console.backend.config_writer import (
            atomic_json_read_modify_write,
            atomic_json_write,
        )

        path = tmp_path / "machines.json"
        atomic_json_write(path, {"machines": []})

        N = 30

        def add_machine(i: int) -> None:
            atomic_json_read_modify_write(
                path,
                lambda cur: {
                    "machines": (
                        cur if isinstance(cur, dict) else {"machines": []}
                    ).get("machines", []) + [{"id": f"M{i}", "md5": "x"}]
                },
                default={"machines": []},
                trailing_newline=True,
            )

        threads = [
            threading.Thread(target=add_machine, args=(i,))
            for i in range(N)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = json.loads(path.read_text())
        ids = sorted(m["id"] for m in final["machines"])
        assert ids == sorted(f"M{i}" for i in range(N)), (
            f"Scenario 16 lost-update race regression — only "
            f"{len(ids)}/{N} machines persisted; some were silently "
            f"overwritten by concurrent writes."
        )

    def test_corrupt_existing_file_recovers_via_default(self, tmp_path: Path):
        """If machines.json is mid-corrupted (truncated mid-write under
        the OLD non-atomic code), the new atomic_json_read_modify_write
        falls back to default. This is the safety net for any historical
        corruption we inherit at deploy time."""
        from src.web_console.backend.config_writer import atomic_json_read_modify_write

        path = tmp_path / "machines.json"
        path.write_text('{"machines": [{"id": "M1", "md5": "abc"', encoding="utf-8")  # truncated

        result = atomic_json_read_modify_write(
            path,
            lambda cur: cur if isinstance(cur, dict) else {"machines": []},
            default={"machines": []},
        )
        # Recovered to empty; subsequent reads see clean JSON
        assert result == {"machines": []}
        assert json.loads(path.read_text()) == {"machines": []}
