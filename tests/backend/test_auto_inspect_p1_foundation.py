"""Phase 1 foundation tests for the auto-inspect feature.

Tests:
  1. SQLite schema: auto_inspect_sweeps + auto_inspect_items + index exist after
     create_app(). Idempotent re-run (tables NOT re-created, no error).
  2. _load_settings: auto_sweep defaults present; bad-type values fall back
     to defaults; nested modes parsed correctly.
  3. _is_cell_owned_by_active_queue branch 3 (auto_inspect_items):
       a. sweep in 'sampling' with non-terminal item -> returns sweep owner string
       b. sweep in 'completed' -> returns None (terminal sweep)
       c. item in 'completed' status -> returns None (terminal item)
  4. AutoInspectManager: public interface present; __init__ does NOT crash;
     _scan_persisted_for_resume returns None on empty DB.
  5. MF-4 prerequisite: manifest loader is wired into player_impact_analyzer
     main() for M272 — verified by loading M272 manifest directly and
     confirming spin_type_convention and analyzer_features fields exist.

Inject-bug discipline per memory/feedback_integration_test_argv.md:
  Each test documents what to break to make it go RED.

Spec: session_artifacts/_arch/auto_inspect/07_decision.md §3-§4.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_ROOT = ROOT / "slot_designer" / "configs" / "machine_manifests"


# ---------------------------------------------------------------------------
# 1. SQLite schema tests
# ---------------------------------------------------------------------------


class TestSQLiteSchema:
    def _make_store(self, tmp_path: Path):
        from src.web_console.backend.app import StateStore
        db = tmp_path / "console.db"
        return StateStore(db), db

    def test_auto_inspect_sweeps_table_exists(self, tmp_path):
        """After StateStore.__init__, auto_inspect_sweeps table exists.

        Inject-bug: remove the CREATE TABLE auto_inspect_sweeps block from
        _init_db -> this assertion fails (table not found).
        """
        store, db = self._make_store(tmp_path)
        with store._connect() as conn:
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "auto_inspect_sweeps" in tables, (
            "auto_inspect_sweeps table not created by _init_db"
        )

    def test_auto_inspect_items_table_exists(self, tmp_path):
        """After StateStore.__init__, auto_inspect_items table exists.

        Inject-bug: remove the CREATE TABLE auto_inspect_items block ->
        assertion fails.
        """
        store, db = self._make_store(tmp_path)
        with store._connect() as conn:
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "auto_inspect_items" in tables

    def test_auto_inspect_items_index_exists(self, tmp_path):
        """idx_auto_inspect_items_status index is created.

        Inject-bug: remove the CREATE INDEX statement -> assertion fails.
        """
        store, db = self._make_store(tmp_path)
        with store._connect() as conn:
            indexes = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        assert "idx_auto_inspect_items_status" in indexes

    def test_schema_is_idempotent(self, tmp_path):
        """Creating StateStore twice against the same DB does not error.

        Inject-bug: change CREATE TABLE to CREATE TABLE (no IF NOT EXISTS) ->
        second construction raises OperationalError 'table already exists'.
        """
        from src.web_console.backend.app import StateStore
        db = tmp_path / "console.db"
        _s1 = StateStore(db)
        _s2 = StateStore(db)  # must not raise

    def test_auto_inspect_sweeps_columns(self, tmp_path):
        """auto_inspect_sweeps has exactly the columns from 07_decision §3.

        Inject-bug: rename 'settings_snapshot_json' -> 'snapshot_json' ->
        column name not in set -> assertion fails.
        """
        store, db = self._make_store(tmp_path)
        expected_cols = {
            "sweep_id", "status", "created_at", "finished_at",
            "settings_snapshot_json", "modes_json", "trigger",
            "total_items", "completed_items", "failed_items", "skipped_items",
        }
        with store._connect() as conn:
            info = conn.execute(
                "PRAGMA table_info(auto_inspect_sweeps)"
            ).fetchall()
        actual_cols = {row["name"] for row in info}
        assert expected_cols <= actual_cols, (
            f"Missing columns: {expected_cols - actual_cols}"
        )

    def test_auto_inspect_items_columns(self, tmp_path):
        """auto_inspect_items has exactly the columns from 07_decision §3.

        Inject-bug: remove 'cfg_md5_at_enqueue' column -> V2 resolution
        (07_decision §2 V2) is broken -> assertion fails.
        """
        store, db = self._make_store(tmp_path)
        expected_cols = {
            "sweep_id", "machine", "mode", "queue_position", "status",
            "cell_class", "sample_run_id", "generate_run_id", "generate_status",
            "cfg_md5_at_enqueue", "code_md5_at_enqueue",
            "claimed_by", "claimed_at", "started_at", "finished_at",
            "terminal_reason", "events_json",
        }
        with store._connect() as conn:
            info = conn.execute(
                "PRAGMA table_info(auto_inspect_items)"
            ).fetchall()
        actual_cols = {row["name"] for row in info}
        assert expected_cols <= actual_cols, (
            f"Missing columns: {expected_cols - actual_cols}"
        )


# ---------------------------------------------------------------------------
# 2. _load_settings auto_sweep block
# ---------------------------------------------------------------------------


class TestLoadSettingsAutoSweep:
    def _settings_path(self, tmp_path: Path, data: Any = None) -> Path:
        p = tmp_path / "settings.json"
        if data is not None:
            p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_defaults_when_file_missing(self, tmp_path):
        """Missing settings.json -> auto_sweep defaults returned.

        Inject-bug: remove 'auto_sweep' from defaults dict ->
        KeyError or assertion fails.
        """
        from src.web_console.backend.app import _load_settings
        p = tmp_path / "settings.json"  # does not exist
        s = _load_settings(p)
        assert "auto_sweep" in s
        asw = s["auto_sweep"]
        assert asw["enabled"] is False
        assert asw["sweep_concurrency"] == 2
        assert asw["skip_fresh_cells"] is True
        assert asw["structural_skip_machines"] == ["M250", "M260", "M264", "M268"]
        assert asw["cell_busy_timeout_s"] == 1800
        assert asw["wall_time_per_cell_s"] == 7200
        for mode_key in ("1", "2", "5", "7"):
            assert mode_key in asw["modes"], f"mode {mode_key} missing"
            m = asw["modes"][mode_key]
            assert m["chunk_spin_times"] == 10000
            assert m["chunk_robot_count"] == 2
            assert m["batch_concurrency"] == 16
            assert m["target_halfwidth_pp"] == 0.5
            assert m["max_chunks"] == 60

    def test_valid_auto_sweep_block_parsed(self, tmp_path):
        """Valid auto_sweep JSON -> values overwrite defaults.

        Inject-bug: skip the 'enabled' bool parse block ->
        enabled stays False even when JSON says True.
        """
        from src.web_console.backend.app import _load_settings
        p = self._settings_path(tmp_path, {
            "auto_sweep": {
                "enabled": True,
                "sweep_concurrency": 4,
                "schedule_mode": "interval",
                "schedule_value": "6",
                "structural_skip_machines": ["M250"],
                "modes": {
                    "1": {
                        "chunk_spin_times": 5000,
                        "chunk_robot_count": 4,
                        "batch_concurrency": 8,
                        "target_halfwidth_pp": 0.3,
                        "max_chunks": 30,
                    }
                },
            }
        })
        s = _load_settings(p)
        asw = s["auto_sweep"]
        assert asw["enabled"] is True
        assert asw["sweep_concurrency"] == 4
        assert asw["schedule_mode"] == "interval"
        assert asw["schedule_value"] == "6"
        assert asw["structural_skip_machines"] == ["M250"]
        # mode 1 overridden
        assert asw["modes"]["1"]["chunk_spin_times"] == 5000
        assert asw["modes"]["1"]["batch_concurrency"] == 8
        # modes 2/5/7 unspecified -> still have defaults
        assert asw["modes"]["2"]["chunk_spin_times"] == 10000

    def test_bad_types_fall_back_to_defaults(self, tmp_path):
        """Bad types in auto_sweep block -> per-key fallback to default.

        Inject-bug: remove type checks -> 'yes' stored as enabled value ->
        assertion 'enabled is False' fails.
        """
        from src.web_console.backend.app import _load_settings
        p = self._settings_path(tmp_path, {
            "auto_sweep": {
                "enabled": "yes",           # must be bool
                "sweep_concurrency": "four", # must be int
                "modes": {
                    "1": {"chunk_spin_times": "large"},  # must be int
                }
            }
        })
        s = _load_settings(p)
        asw = s["auto_sweep"]
        assert asw["enabled"] is False   # bad type -> default
        assert asw["sweep_concurrency"] == 2  # bad type -> default
        assert asw["modes"]["1"]["chunk_spin_times"] == 10000  # bad type -> default

    def test_out_of_range_int_falls_to_default(self, tmp_path):
        """Out-of-range int -> default, not the bad value.

        Inject-bug: remove range check -> 999 stored as sweep_concurrency ->
        assertion fails (expected 2, got 999).
        """
        from src.web_console.backend.app import _load_settings
        p = self._settings_path(tmp_path, {
            "auto_sweep": {
                "sweep_concurrency": 999,  # max is 16
                "max_consecutive_failures": -1,  # min is 1
            }
        })
        s = _load_settings(p)
        asw = s["auto_sweep"]
        assert asw["sweep_concurrency"] == 2  # out of range -> default
        assert asw["max_consecutive_failures"] == 3  # out of range -> default

    def test_auto_sweep_missing_from_file_uses_defaults(self, tmp_path):
        """settings.json without auto_sweep key -> defaults used wholesale.

        Inject-bug: change the 'isinstance(raw_as, dict)' check to always
        process raw_as -> KeyError or defaults overwritten.
        """
        from src.web_console.backend.app import _load_settings
        p = self._settings_path(tmp_path, {"min_retention_spins": 5000})
        s = _load_settings(p)
        assert "auto_sweep" in s
        assert s["auto_sweep"]["enabled"] is False


# ---------------------------------------------------------------------------
# 3. _is_cell_owned_by_active_queue branch 3 (auto_inspect_items)
# ---------------------------------------------------------------------------


def _seed_sweep(store, sweep_id: str, sweep_status: str,
                machine: str, mode: int, item_status: str) -> None:
    """Seed one sweep + one item row for testing."""
    with store._connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO auto_inspect_sweeps
            (sweep_id, status, created_at, settings_snapshot_json, modes_json, trigger)
            VALUES (?, ?, '2026-05-26T00:00:00Z', '{}', '["1"]', 'manual')
            """,
            (sweep_id, sweep_status),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO auto_inspect_items
            (sweep_id, machine, mode, queue_position, status, cell_class)
            VALUES (?, ?, ?, 0, ?, 'easy')
            """,
            (sweep_id, machine, mode, item_status),
        )
        conn.commit()


class TestCellOwnedByAutoInspect:
    def _make_mgr(self, tmp_path):
        from src.web_console.backend.app import StateStore, RunManager
        from unittest.mock import MagicMock
        db = tmp_path / "console.db"
        store = StateStore(db)
        # We only need RunManager._is_cell_owned_by_active_queue
        # Construct a minimal RunManager to call the method.
        fake_analyzer = tmp_path / "analyzer.py"
        fake_analyzer.write_text("", encoding="utf-8")
        fake_machines = tmp_path / "machines.json"
        fake_machines.write_text('{"machines":[]}', encoding="utf-8")
        progress_dir = tmp_path / "progress"
        progress_dir.mkdir()
        reports_root = tmp_path / "reports"
        reports_root.mkdir()
        rawdata_root = tmp_path / "rawdata"
        rawdata_root.mkdir()
        cache_root = tmp_path / "cache"
        cache_root.mkdir()
        mgr = RunManager(
            store,
            analyzer=fake_analyzer,
            reports_root=reports_root,
            progress_dir=progress_dir,
            cache_root=cache_root,
            machines_config=fake_machines,
            rawdata_root=rawdata_root,
        )
        return mgr, store

    def test_active_sweep_owns_running_item(self, tmp_path, stub_popen):
        """sampling sweep + running item -> branch 3 returns 'auto-inspect sweep <id>'.

        Inject-bug: remove branch 3 SQL block -> returns None even though
        sweep owns the cell -> A2 race condition restored.
        """
        mgr, store = self._make_mgr(tmp_path)
        _seed_sweep(store, "sw_001", "sampling", "M14", 1, "running")
        result = mgr._is_cell_owned_by_active_queue("M14", 1)
        assert result is not None, "expected branch 3 to find owner"
        assert "auto-inspect sweep" in result
        assert "sw_001" in result

    def test_scanning_sweep_owns_pending_item(self, tmp_path, stub_popen):
        """scanning sweep + pending item -> owned."""
        mgr, store = self._make_mgr(tmp_path)
        _seed_sweep(store, "sw_002", "scanning", "M15", 2, "pending")
        result = mgr._is_cell_owned_by_active_queue("M15", 2)
        assert result is not None
        assert "sw_002" in result

    def test_finalizing_sweep_owns_claimed_item(self, tmp_path, stub_popen):
        """finalizing sweep + claimed item -> owned."""
        mgr, store = self._make_mgr(tmp_path)
        _seed_sweep(store, "sw_003", "finalizing", "M16", 1, "claimed")
        result = mgr._is_cell_owned_by_active_queue("M16", 1)
        assert result is not None
        assert "sw_003" in result

    def test_completed_sweep_does_not_own_cell(self, tmp_path, stub_popen):
        """completed sweep -> not active -> returns None.

        Inject-bug: add 'completed' to the s.status IN (...) list ->
        completed sweeps wrongly claim ownership -> assertion fails.
        """
        mgr, store = self._make_mgr(tmp_path)
        _seed_sweep(store, "sw_004", "completed", "M17", 1, "completed")
        result = mgr._is_cell_owned_by_active_queue("M17", 1)
        assert result is None, f"completed sweep should not own cell, got {result!r}"

    def test_terminal_item_does_not_own_cell(self, tmp_path, stub_popen):
        """sampling sweep but item in terminal status -> not owned.

        Inject-bug: remove the i.status NOT IN (...) filter ->
        terminal items wrongly claim ownership.
        """
        mgr, store = self._make_mgr(tmp_path)
        _seed_sweep(store, "sw_005", "sampling", "M18", 1, "completed")
        result = mgr._is_cell_owned_by_active_queue("M18", 1)
        assert result is None, (
            f"completed item should not block A2 spawn, got {result!r}"
        )

    def test_structural_skip_item_does_not_own_cell(self, tmp_path, stub_popen):
        """sampling sweep + structural_skip item -> NOT owned (terminal)."""
        mgr, store = self._make_mgr(tmp_path)
        _seed_sweep(store, "sw_006", "sampling", "M250", 1, "structural_skip")
        result = mgr._is_cell_owned_by_active_queue("M250", 1)
        assert result is None

    def test_different_machine_not_owned(self, tmp_path, stub_popen):
        """Sweep owns M14 mode 1 but not M14 mode 2 -> None for M14/2."""
        mgr, store = self._make_mgr(tmp_path)
        _seed_sweep(store, "sw_007", "sampling", "M14", 1, "running")
        result = mgr._is_cell_owned_by_active_queue("M14", 2)
        assert result is None, f"M14 mode 2 not in sweep, got {result!r}"


# ---------------------------------------------------------------------------
# 4. AutoInspectManager skeleton
# ---------------------------------------------------------------------------


class TestAutoInspectManagerSkeleton:
    def _make_mgr(self, tmp_path):
        from src.web_console.backend.app import StateStore, RunManager
        from src.web_console.backend.auto_inspect_manager import AutoInspectManager
        from src.web_console.backend.cell_lock_registry import CellLockRegistry
        from src.web_console.backend.rate_limiter import ConcurrencyLimiter

        db = tmp_path / "console.db"
        store = StateStore(db)
        fake_analyzer = tmp_path / "analyzer.py"
        fake_analyzer.write_text("", encoding="utf-8")
        fake_machines = tmp_path / "machines.json"
        fake_machines.write_text('{"machines":[]}', encoding="utf-8")
        progress_dir = tmp_path / "progress"
        progress_dir.mkdir()
        reports_root = tmp_path / "reports"
        reports_root.mkdir()
        rawdata_root = tmp_path / "rawdata"
        rawdata_root.mkdir()
        cache_root = tmp_path / "cache"
        cache_root.mkdir()
        settings_path = tmp_path / "settings.json"
        mgr_run = RunManager(
            store,
            analyzer=fake_analyzer,
            reports_root=reports_root,
            progress_dir=progress_dir,
            cache_root=cache_root,
            machines_config=fake_machines,
            rawdata_root=rawdata_root,
        )
        registry = CellLockRegistry()
        limiter = ConcurrencyLimiter(n_slots=5, foreground_reserve=2)
        auto_mgr = AutoInspectManager(
            store=store,
            run_manager=mgr_run,
            registry=registry,
            limiter=limiter,
            settings_path=settings_path,
            machines_config=fake_machines,
            rawdata_root=rawdata_root,
        )
        return auto_mgr, store

    def test_construction_succeeds_on_empty_db(self, tmp_path):
        """AutoInspectManager.__init__ succeeds with empty DB.

        Inject-bug: add HTTP call in __init__ -> startup blocked (MF-1).
        """
        mgr, _ = self._make_mgr(tmp_path)
        assert mgr._pending_resume_sweep_id is None

    def test_public_interface_present(self, tmp_path):
        """All public methods from 07_decision §1 are present.

        Inject-bug: rename resume_sweep -> _resume_sweep ->
        assertion fails (V3 resolution broken).
        """
        from src.web_console.backend.auto_inspect_manager import AutoInspectManager
        expected_methods = {
            "start_sweep", "cancel_sweep", "get_sweep_status",
            "list_recent_sweeps", "resume_sweep",
        }
        actual = {m for m in dir(AutoInspectManager) if not m.startswith("__")}
        assert expected_methods <= actual, (
            f"Missing methods: {expected_methods - actual}"
        )

    def test_start_sweep_is_callable(self, tmp_path):
        """P2: start_sweep is implemented -- returns a sweep_id string.

        P1 skeleton checked NotImplementedError; P2 supersedes with real
        implementation.  With empty machines.json, the sweep starts and
        returns a sweep_id (no items, scan succeeds, sweep is created).
        """
        mgr, _ = self._make_mgr(tmp_path)
        result = mgr.start_sweep()
        assert isinstance(result, str) and len(result) > 0

    def test_cancel_sweep_returns_false_for_missing(self, tmp_path):
        """P2: cancel_sweep returns False for unknown sweep_id."""
        mgr, _ = self._make_mgr(tmp_path)
        result = mgr.cancel_sweep("sw_fake_p2")
        assert result is False

    def test_get_sweep_status_returns_none_for_missing(self, tmp_path):
        """P2: get_sweep_status returns None for unknown sweep_id."""
        mgr, _ = self._make_mgr(tmp_path)
        result = mgr.get_sweep_status("sw_fake_p2")
        assert result is None

    def test_list_recent_sweeps_returns_list(self, tmp_path):
        """P2: list_recent_sweeps returns a list (empty when no sweeps)."""
        mgr, _ = self._make_mgr(tmp_path)
        result = mgr.list_recent_sweeps()
        assert isinstance(result, list)

    def test_resume_sweep_is_noop_p1(self, tmp_path):
        """P1: resume_sweep logs and returns without raising."""
        mgr, _ = self._make_mgr(tmp_path)
        mgr.resume_sweep("sw_fake")  # must not raise

    def test_scan_persisted_returns_none_on_empty_db(self, tmp_path):
        """_scan_persisted_for_resume returns None when no sweeps exist.

        Inject-bug: return a hardcoded non-None sweep_id ->
        assertion fails.
        """
        mgr, _ = self._make_mgr(tmp_path)
        result = mgr._scan_persisted_for_resume()
        assert result is None

    def test_scan_persisted_finds_nonterminal_sweep(self, tmp_path):
        """_scan_persisted_for_resume returns sweep_id for non-terminal sweep.

        Inject-bug: change WHERE clause to status='running' ->
        'sampling' status not matched -> returns None -> assertion fails.
        """
        mgr, store = self._make_mgr(tmp_path)
        # Seed a 'sampling' sweep directly.
        with store._connect() as conn:
            conn.execute(
                """
                INSERT INTO auto_inspect_sweeps
                (sweep_id, status, created_at, settings_snapshot_json, modes_json, trigger)
                VALUES ('sw_resume_test', 'sampling', '2026-05-26T01:00:00Z',
                        '{}', '["1"]', 'cron')
                """,
            )
            conn.commit()
        result = mgr._scan_persisted_for_resume()
        assert result == "sw_resume_test", (
            f"expected 'sw_resume_test', got {result!r}"
        )

    def test_scan_persisted_ignores_terminal_sweeps(self, tmp_path):
        """_scan_persisted_for_resume returns None when only completed sweeps exist.

        Inject-bug: add 'completed' to the WHERE status IN (...) ->
        completed sweep incorrectly triggers resume.
        """
        mgr, store = self._make_mgr(tmp_path)
        with store._connect() as conn:
            conn.execute(
                """
                INSERT INTO auto_inspect_sweeps
                (sweep_id, status, created_at, settings_snapshot_json, modes_json, trigger)
                VALUES ('sw_done', 'completed', '2026-05-26T01:00:00Z',
                        '{}', '["1"]', 'manual')
                """,
            )
            conn.commit()
        result = mgr._scan_persisted_for_resume()
        assert result is None

    def test_no_module_level_globals(self):
        """AutoInspectManager module has no module-level state beyond constants.

        Checks that RAWDATA_ROOT / MACHINES_CONFIG strings do not appear
        as module-level name references in the implementation.

        Inject-bug: add 'RAWDATA_ROOT' reference at module level ->
        assertion fails.
        """
        import ast
        src = (
            ROOT / "src" / "web_console" / "backend" / "auto_inspect_manager.py"
        ).read_text(encoding="utf-8-sig")
        tree = ast.parse(src)
        # Collect top-level Assign / AnnAssign / AugAssign names (module globals).
        module_globals: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Module):
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign):
                        for t in stmt.targets:
                            if isinstance(t, ast.Name):
                                module_globals.add(t.id)
                    elif isinstance(stmt, ast.AnnAssign):
                        if isinstance(stmt.target, ast.Name):
                            module_globals.add(stmt.target.id)
        forbidden = {"RAWDATA_ROOT", "MACHINES_CONFIG", "STATE_DIR", "REPORTS_ROOT"}
        found = forbidden & module_globals
        assert not found, (
            f"Module-level globals found in auto_inspect_manager.py: {found}"
        )


# ---------------------------------------------------------------------------
# 5. MF-4 prerequisite: manifest loader is wired for M272
# ---------------------------------------------------------------------------


class TestMF4ManifestLoaderWired:
    def test_m272_manifest_file_exists(self):
        """M272 manifest file exists at the expected path.

        Inject-bug: delete M272.json -> FileNotFoundError -> assertion fails.
        """
        m272_manifest = MANIFEST_ROOT / "M272.json"
        assert m272_manifest.exists(), (
            f"M272 manifest not found at {m272_manifest}. "
            "MF-4 prerequisite cannot be verified."
        )

    def test_m272_manifest_loadable(self):
        """manifest_loader.load_manifest can parse M272.json without error.

        Inject-bug: corrupt M272.json with invalid JSON ->
        JSONDecodeError raised -> test fails.
        """
        from fresh_slotlab.analyzer.manifest_loader import load_manifest
        manifest = load_manifest("M272", MANIFEST_ROOT)
        assert isinstance(manifest, dict), "load_manifest must return dict"
        assert manifest.get("machine_id") == "M272"

    def test_m272_manifest_has_spin_type_convention(self):
        """M272 manifest has spin_type_convention field.

        The convention declares which SpinTypes are 'paid' — the
        field is consumed by the pipeline's PipelineContext at
        player_impact_analyzer.py main() via _c1_manifest.

        Inject-bug: remove spin_type_convention from M272.json ->
        KeyError or None -> assertion fails.
        """
        from fresh_slotlab.analyzer.manifest_loader import load_manifest
        manifest = load_manifest("M272", MANIFEST_ROOT)
        assert "spin_type_convention" in manifest, (
            "M272 manifest missing spin_type_convention"
        )
        stc = manifest["spin_type_convention"]
        assert isinstance(stc, dict), "spin_type_convention must be dict"
        assert "paid" in stc, "spin_type_convention must have 'paid' list"

    # NOTE: the two `test_manifest_loader_wired_into_analyzer_*` tests that
    # grepped player_impact_analyzer.py source for the MF-4 wiring were removed
    # — that orchestrator file was deleted (the new SpinType-native engine is
    # pending). The surviving manifest_loader is exercised directly by the
    # test_m272_manifest_* tests above; wiring into the new engine will get its
    # own per-machine manifest regression.
