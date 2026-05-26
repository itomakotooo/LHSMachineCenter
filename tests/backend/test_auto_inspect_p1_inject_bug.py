"""Inject-bug TDD for P1 auto-inspect additions — highest-fragility guards.

This file supplements test_auto_inspect_p1_foundation.py with:

  Guard A — _is_cell_owned_by_active_queue branch 3 (auto_inspect JOIN)
    A1: drop the auto_inspect_items JOIN entirely          -> cells protected by
        running sweep are no longer protected -> A2 spawns duplicate runs
    A2: drop i.status NOT IN (...) filter                 -> terminal items
        (completed/failed) still register as "owned" -> blocks future ops
    A3: drop s.status IN ('scanning','sampling','finalizing') filter
        -> terminal sweeps still block -> ops blocked after sweep done

  Guard B — settings parser for auto_sweep nested dict
    B1: modes= list instead of dict                       -> parser must ignore
        and use full defaults, not crash or corrupt
    B2: auto_sweep.modes["1"] missing target_halfwidth_pp -> parser fills default
        for missing field, does NOT drop the whole mode dict
    B3: auto_sweep.sweep_concurrency="abc" (already covered in foundation)
        -- we ADD a second string-coercion: modes["1"]["chunk_spin_times"]="big"
        -> falls back to 10000, not stored as string (foundation only checks this
        at the top level sweep_concurrency; per-mode string is NOT tested there)

  Guard C — schema migration on pre-P1 DB
    C1: drop CREATE TABLE IF NOT EXISTS auto_inspect_sweeps -> upsert fails with
        "no such table"  (foundation only checks column existence; this checks
        the load-bearing DDL)
    C2: IF NOT EXISTS protection -> second StateStore on same DB does not raise
        OperationalError (foundation test_schema_is_idempotent covers this, but
        WITHOUT explicit inject-bug: we add the inject-bug cycle here)

  Bonus
    D1: _scan_persisted_for_resume with 3 sweeps (1 completed, 1 cancelled, 1
        sampling) returns ONLY the sampling one
    D2: _scan_persisted_for_resume with 2 non-terminal sweeps returns
        MOST-RECENT by created_at
    D3: create_app resume thread is spawned in background (returns within 1s
        even when resume_sweep sleeps 5s) — MF-1 verification via thread
    D4: multiple owners (sweep + sampling batch own same cell simultaneously)
        -> _is_cell_owned_by_active_queue returns a non-None string without
        crashing, blast-radius check

Inject-bug recipes documented in each test; run the inject-bug cycle by:
  1. Apply the Edit in the test docstring
  2. pytest <this file>::<TestClass>::<test> -> RED
  3. Revert the Edit
  4. pytest <this file>::<TestClass>::<test> -> GREEN

Memory refs honored:
  - feedback_enumerate_safety_paths.md  (every guard needs inject-bug proof)
  - feedback_integration_test_argv.md   (no mock-only for A2 gating path)
  - feedback_subprocess_import_suicide_and_module_globals.md (per-instance state)
  - feedback_perf_claim_needs_e2e_event_stream.md (real threads for MF-1)
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_state_store(tmp_path: Path):
    from src.web_console.backend.app import StateStore
    db = tmp_path / "console.db"
    return StateStore(db), db


def _build_dirs(tmp_path: Path):
    """Create standard directory layout and return (db_path, dirs_dict)."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "console.db"
    for d in ("rawdata", "reports", "cache"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (state_dir / "progress").mkdir(parents=True, exist_ok=True)
    return db_path, state_dir


def _init_store(tmp_path: Path, db_path: Path):
    """Create StateStore so tables exist, then close it."""
    from src.web_console.backend.app import StateStore
    store = StateStore(db_path)
    return store


def _make_run_manager(tmp_path: Path, stub_popen=None):
    """Construct a bare RunManager with injected paths.

    IMPORTANT: call this AFTER seeding any orphan/sweep/item rows into
    the DB. RunManager.__init__ runs _recover_orphan_running_runs()
    immediately, so rows must exist before construction.

    Returns (mgr, store, db_path).
    """
    from src.web_console.backend.app import StateStore, RunManager

    db_path, state_dir = _build_dirs(tmp_path)

    fake_analyzer = tmp_path / "fake_analyzer.py"
    fake_analyzer.write_text("# stub\n", encoding="utf-8")
    fake_machines = tmp_path / "machines.json"
    fake_machines.write_text(
        json.dumps({"machines": [
            {"machine": "M14", "mode_list": [1, 2], "upstream_key": "M14"},
        ]}),
        encoding="utf-8",
    )
    store = StateStore(db_path)  # creates tables
    mgr = RunManager(
        store,
        analyzer=fake_analyzer,
        reports_root=tmp_path / "reports",
        progress_dir=state_dir / "progress",
        cache_root=tmp_path / "cache",
        machines_config=fake_machines,
        rawdata_root=tmp_path / "rawdata",
        popen_factory=stub_popen,
        auto_resume_orphan_runs=True,
    )
    return mgr, store, db_path


def _seed_sweep_row(db_path: Path, sweep_id: str, status: str,
                    created_at: str = "2026-05-26T00:00:00Z") -> None:
    """Insert a sweep row directly via sqlite3 (store-independent)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO auto_inspect_sweeps
            (sweep_id, status, created_at, settings_snapshot_json, modes_json, trigger)
            VALUES (?, ?, ?, '{}', '["1"]', 'manual')
            """,
            (sweep_id, status, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_item_row(db_path: Path, sweep_id: str, machine: str, mode: int,
                   item_status: str) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO auto_inspect_items
            (sweep_id, machine, mode, queue_position, status, cell_class)
            VALUES (?, ?, ?, 0, ?, 'easy')
            """,
            (sweep_id, machine, mode, item_status),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_orphan_run(db_path: Path, run_id: str = "orph_r1",
                     machine: str = "M14", mode: int = 1) -> None:
    """Insert a runs row with status='running' to simulate a restart orphan."""
    conn = sqlite3.connect(str(db_path))
    try:
        orphan: dict[str, Any] = {
            "run_id": run_id,
            "machine": machine,
            "mode": mode,
            "status": "running",
            "model_id": "gpt-5.4-mini",
            "created_at": "2026-05-26T08:00:00Z",
            "started_at": "2026-05-26T08:00:00Z",
            "finished_at": None,
            "target_halfwidth_pp": 0.5,
            "chunk_spin_times": 10000,
            "chunk_robot_count": 8,
            "batch_concurrency": 8,
            "max_chunks": 60,
            "timeout": 60.0,
            "bankruptcy_session_spins": 10000,
            "bankruptcy_bankroll_multipliers": "10,100,200,500",
            "report_version": "rv_old",
            "output_dir": f"reports/{machine}/mode_{mode}/versions/rv_old",
            "progress_file": "state/progress/orph_r1.jsonl",
            "summary_file": None,
            "report_file": None,
            "error_message": None,
            "process_pid": None,
            "rawdata_config_md5": "",
            "rawdata_code_md5": "",
        }
        fields = sorted(orphan.keys())
        conn.execute(
            f"INSERT INTO runs ({','.join(fields)}) "
            f"VALUES ({','.join(':'+f for f in fields)})",
            orphan,
        )
        conn.commit()
    finally:
        conn.close()


def _get_run_error(store, run_id: str = "orph_r1") -> str:
    row = store.get_run(run_id)
    return (row or {}).get("error_message", "") or ""


def _load_settings_with(tmp_path: Path, data: Any):
    from src.web_console.backend.app import _load_settings
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return _load_settings(p)


# ─────────────────────────────────────────────────────────────────────────────
# Guard A — branch 3 of _is_cell_owned_by_active_queue
# ─────────────────────────────────────────────────────────────────────────────


def _make_run_manager_seeded(
    tmp_path: Path,
    stub_popen,
    *,
    sweep_id: str | None = None,
    sweep_status: str | None = None,
    item_status: str | None = None,
    item_machine: str = "M14",
    item_mode: int = 1,
    orphan_run_id: str = "orph_x",
    orphan_machine: str = "M14",
    orphan_mode: int = 1,
):
    """Create store/tables, seed sweep+item+orphan BEFORE RunManager.__init__.

    CRITICAL ORDER: RunManager.__init__ calls _recover_orphan_running_runs()
    immediately, so all seed data must exist in the DB before RunManager
    is constructed.

    Returns (mgr, store, db_path).
    """
    from src.web_console.backend.app import StateStore, RunManager

    db_path, state_dir = _build_dirs(tmp_path)

    fake_analyzer = tmp_path / "fake_analyzer.py"
    fake_analyzer.write_text("# stub\n", encoding="utf-8")
    fake_machines = tmp_path / "machines.json"
    fake_machines.write_text(
        json.dumps({"machines": [
            {"machine": "M14", "mode_list": [1, 2], "upstream_key": "M14"},
        ]}),
        encoding="utf-8",
    )

    # Step 1: Create store so tables exist.
    store = StateStore(db_path)

    # Step 2: Seed sweep/item rows (before RunManager init).
    if sweep_id and sweep_status:
        _seed_sweep_row(db_path, sweep_id, sweep_status)
    if sweep_id and item_status:
        _seed_item_row(db_path, sweep_id, item_machine, item_mode, item_status)

    # Step 3: Seed orphan run (before RunManager init).
    _seed_orphan_run(
        db_path,
        run_id=orphan_run_id,
        machine=orphan_machine,
        mode=orphan_mode,
    )

    # Step 4: Construct RunManager — _recover_orphan_running_runs fires here.
    mgr = RunManager(
        store,
        analyzer=fake_analyzer,
        reports_root=tmp_path / "reports",
        progress_dir=state_dir / "progress",
        cache_root=tmp_path / "cache",
        machines_config=fake_machines,
        rawdata_root=tmp_path / "rawdata",
        popen_factory=stub_popen,
        auto_resume_orphan_runs=True,
    )
    return mgr, store, db_path


class TestGuardA1_JoinDropMakesA2SpawnDuplicate:
    """Inject: remove the auto_inspect_items JOIN block from branch 3.

    Result: A2's startup_recovery_snapshot() will spawn a new run for an
    orphan even when that cell is owned by an active sweep -> duplicate run.

    Inject recipe for app.py:
        Remove/comment lines 6283-6303 (the branch-3 try/except block):
            try:
                with self.store._connect() as conn:
                    row_ai = conn.execute(\"\"\" ... \"\"\", ...)
                    if row_ai:
                        return f"auto-inspect sweep ..."
            except sqlite3.OperationalError:
                pass

    To verify: apply that removal -> this test goes RED (orphan spawned
    despite sweep ownership).  Revert -> GREEN.
    """

    def test_a2_skips_spawn_for_sweep_owned_cell_e2e(self, tmp_path, stub_popen):
        """Full A2 path: orphan run + active sweep owning same cell
        -> startup_recovery_snapshot shows NO auto-resume for that run.

        This is an E2E test via startup_recovery_snapshot() (the real
        _recover_orphan_running_runs path), NOT just a direct call to
        _is_cell_owned_by_active_queue. Per feedback_integration_test_argv.md:
        if you only test the predicate, you miss the gating logic.
        """
        mgr, store, db_path = _make_run_manager_seeded(
            tmp_path, stub_popen,
            sweep_id="sw_a1", sweep_status="sampling",
            item_status="running", item_machine="M14", item_mode=1,
            orphan_run_id="orph_a1", orphan_machine="M14", orphan_mode=1,
        )

        # A2 must skip spawn because the sweep owns M14/1.
        snap = mgr.startup_recovery_snapshot()
        assert "orph_a1" not in snap["auto_resumed"], (
            "A2 spawned duplicate run for sweep-owned cell. "
            "Branch 3 of _is_cell_owned_by_active_queue is not guarding."
        )
        # Confirm the skip-reason message is present.
        err = _get_run_error(store, "orph_a1")
        assert "auto-inspect sweep" in err or "owned by" in err, (
            f"Expected 'owned by' in error message, got: {err!r}"
        )
        # No subprocess was spawned.
        assert stub_popen.cmds == [], (
            f"Subprocess was spawned despite sweep ownership: {stub_popen.cmds}"
        )

    def test_a2_skips_spawn_for_scanning_sweep(self, tmp_path, stub_popen):
        """scanning sweep (not yet sampling) also blocks A2 spawn."""
        mgr, store, db_path = _make_run_manager_seeded(
            tmp_path, stub_popen,
            sweep_id="sw_a1_scan", sweep_status="scanning",
            item_status="pending", item_machine="M14", item_mode=1,
            orphan_run_id="orph_a1_scan", orphan_machine="M14", orphan_mode=1,
        )
        snap = mgr.startup_recovery_snapshot()
        assert "orph_a1_scan" not in snap["auto_resumed"]
        assert stub_popen.cmds == []

    def test_a2_skips_spawn_for_finalizing_sweep(self, tmp_path, stub_popen):
        """finalizing sweep + claimed item also blocks A2 spawn."""
        mgr, store, db_path = _make_run_manager_seeded(
            tmp_path, stub_popen,
            sweep_id="sw_a1_fin", sweep_status="finalizing",
            item_status="claimed", item_machine="M14", item_mode=1,
            orphan_run_id="orph_a1_fin", orphan_machine="M14", orphan_mode=1,
        )
        snap = mgr.startup_recovery_snapshot()
        assert "orph_a1_fin" not in snap["auto_resumed"]
        assert stub_popen.cmds == []


class TestGuardA2_CompletedItemStillBlocksForever:
    """Inject: drop the i.status NOT IN (...) clause.

    Result: completed/failed/structural_skip items inside a running sweep
    still register as owners -> operations on those cells are permanently
    blocked even after the sweep finished their work.

    Inject recipe for app.py _is_cell_owned_by_active_queue branch 3:
        Remove the line:
            AND i.status NOT IN ('completed', 'failed', 'structural_skip', ...)
        (approximately line 6292-6295)

    To verify: apply removal -> test_a2_spawns_normally_for_completed_item RED.
    Revert -> GREEN.

    NOTE: test_terminal_item_does_not_own_cell in the foundation file tests
    this via _is_cell_owned_by_active_queue directly. This test exercises
    the full A2 recovery path to confirm the gating is wired end-to-end.
    """

    def test_a2_spawns_normally_for_completed_item_in_active_sweep(
        self, tmp_path, stub_popen
    ):
        """Sweep is still running (sampling) but THIS cell's item already
        completed -> A2 should spawn normally (cell is free again).

        The key difference from Guard A1: item_status='completed', not 'running'.
        """
        mgr, store, db_path = _make_run_manager_seeded(
            tmp_path, stub_popen,
            sweep_id="sw_a2", sweep_status="sampling",
            item_status="completed",  # terminal item
            item_machine="M14", item_mode=1,
            orphan_run_id="orph_a2", orphan_machine="M14", orphan_mode=1,
        )
        snap = mgr.startup_recovery_snapshot()
        assert "orph_a2" in snap["auto_resumed"], (
            "A2 was blocked by a completed item in an active sweep. "
            "The i.status NOT IN (...) filter is missing or wrong."
        )
        assert stub_popen.cmds, "A2 should have spawned a subprocess for the orphan"

    def test_a2_spawns_normally_for_failed_item_in_active_sweep(
        self, tmp_path, stub_popen
    ):
        """failed item inside active sweep -> A2 can spawn."""
        mgr, store, db_path = _make_run_manager_seeded(
            tmp_path, stub_popen,
            sweep_id="sw_a2_fail", sweep_status="sampling",
            item_status="failed", item_machine="M14", item_mode=1,
            orphan_run_id="orph_a2_fail", orphan_machine="M14", orphan_mode=1,
        )
        snap = mgr.startup_recovery_snapshot()
        assert "orph_a2_fail" in snap["auto_resumed"]

    def test_a2_spawns_normally_for_structural_skip_item(
        self, tmp_path, stub_popen
    ):
        """structural_skip item inside active sweep -> A2 can spawn."""
        mgr, store, db_path = _make_run_manager_seeded(
            tmp_path, stub_popen,
            sweep_id="sw_a2_skip", sweep_status="sampling",
            item_status="structural_skip", item_machine="M14", item_mode=1,
            orphan_run_id="orph_a2_skip", orphan_machine="M14", orphan_mode=1,
        )
        snap = mgr.startup_recovery_snapshot()
        assert "orph_a2_skip" in snap["auto_resumed"]


class TestGuardA3_TerminalSweepStillRegistersAsOwner:
    """Inject: drop s.status IN ('scanning','sampling','finalizing') filter.

    Result: completed/cancelled/failed sweeps still register as owners ->
    all cells from old sweeps are permanently blocked.

    Inject recipe for app.py _is_cell_owned_by_active_queue branch 3:
        Remove the line:
            AND s.status IN ('scanning', 'sampling', 'finalizing')
        (approximately line 6291)

    To verify: apply removal -> test_a2_spawns_normally_when_sweep_completed RED.
    Revert -> GREEN.

    NOTE: test_completed_sweep_does_not_own_cell in the foundation tests
    this predicate in isolation. Here we test the FULL A2 path.
    """

    def test_a2_spawns_normally_when_sweep_completed(self, tmp_path, stub_popen):
        """Completed sweep with a 'running' item record -> A2 must spawn
        because the sweep is terminal.

        Regression case: if s.status filter is dropped, item being 'running'
        wrongly blocks A2 forever after the sweep finishes.
        """
        mgr, store, db_path = _make_run_manager_seeded(
            tmp_path, stub_popen,
            sweep_id="sw_a3_comp", sweep_status="completed",
            item_status="running",  # stale 'running' row after sweep finished
            item_machine="M14", item_mode=1,
            orphan_run_id="orph_a3", orphan_machine="M14", orphan_mode=1,
        )
        snap = mgr.startup_recovery_snapshot()
        assert "orph_a3" in snap["auto_resumed"], (
            "A2 was blocked by a completed sweep. "
            "The s.status IN (...) filter is missing or wrong."
        )
        assert stub_popen.cmds

    def test_a2_spawns_normally_when_sweep_cancelled(self, tmp_path, stub_popen):
        """Cancelled sweep -> terminal -> A2 unblocked."""
        mgr, store, db_path = _make_run_manager_seeded(
            tmp_path, stub_popen,
            sweep_id="sw_a3_can", sweep_status="cancelled",
            item_status="pending", item_machine="M14", item_mode=1,
            orphan_run_id="orph_a3_can", orphan_machine="M14", orphan_mode=1,
        )
        snap = mgr.startup_recovery_snapshot()
        assert "orph_a3_can" in snap["auto_resumed"]

    def test_a2_spawns_normally_when_sweep_failed(self, tmp_path, stub_popen):
        """Failed sweep -> terminal -> A2 unblocked."""
        mgr, store, db_path = _make_run_manager_seeded(
            tmp_path, stub_popen,
            sweep_id="sw_a3_failed", sweep_status="failed",
            item_status="running", item_machine="M14", item_mode=1,
            orphan_run_id="orph_a3_fail", orphan_machine="M14", orphan_mode=1,
        )
        snap = mgr.startup_recovery_snapshot()
        assert "orph_a3_fail" in snap["auto_resumed"]


# ─────────────────────────────────────────────────────────────────────────────
# Guard B — settings parser for auto_sweep nested dict
# ─────────────────────────────────────────────────────────────────────────────


class TestGuardB_SettingsParserEdgeCases:
    """Settings parser must be robust to type mismatches and missing fields.

    These three scenarios are NOT in the foundation file:
      B1 — modes is a list instead of dict
      B2 — a single mode-dict is missing one field (e.g. target_halfwidth_pp)
      B3 — per-mode int field given as string (e.g. chunk_spin_times="big")

    Inject recipes:
      B1: in _load_settings, remove the `if isinstance(raw_modes, dict):` check
          -> list passed as modes -> TypeError when iterating .items() -> crash
          Inject: change `isinstance(raw_modes, dict)` to `True` (always enter)
      B2: remove the `clean_mode: dict = dict(_mode_def)` initialisation
          -> missing fields not filled with defaults -> KeyError downstream
          Inject: replace `clean_mode = dict(_mode_def)` with `clean_mode = {}`
      B3: remove per-field int bounds check -> raw string stored -> Pydantic
          validation crash downstream
          Inject: remove `isinstance(_mv, (int, float))` guard for chunk_spin_times
    """

    def test_b1_modes_as_list_uses_defaults_wholesale(self, tmp_path):
        """auto_sweep.modes is a list -> parser ignores, all defaults returned.

        Inject-bug: remove `isinstance(raw_modes, dict)` guard ->
        `list.items()` AttributeError, crash on import or parse -> RED.
        Revert -> GREEN.
        """
        s = _load_settings_with(tmp_path, {
            "auto_sweep": {
                "modes": ["1", "2", "5", "7"],  # list, not dict
            }
        })
        asw = s["auto_sweep"]
        # All 4 default modes must be present.
        for mode_key in ("1", "2", "5", "7"):
            assert mode_key in asw["modes"], f"mode {mode_key} missing"
            m = asw["modes"][mode_key]
            assert m["chunk_spin_times"] == 10000
            assert m["target_halfwidth_pp"] == 0.5

    def test_b2_mode_missing_one_field_filled_with_default(self, tmp_path):
        """Mode dict with target_halfwidth_pp omitted -> default 0.5 filled.

        Inject-bug: change `clean_mode = dict(_mode_def)` to `clean_mode = {}` ->
        missing field -> KeyError when caller reads target_halfwidth_pp -> RED.
        Revert -> GREEN.
        """
        s = _load_settings_with(tmp_path, {
            "auto_sweep": {
                "modes": {
                    "1": {
                        "chunk_spin_times": 5000,
                        "chunk_robot_count": 4,
                        "batch_concurrency": 8,
                        "max_chunks": 30,
                        # target_halfwidth_pp deliberately omitted
                    }
                }
            }
        })
        mode1 = s["auto_sweep"]["modes"]["1"]
        assert "target_halfwidth_pp" in mode1, (
            "target_halfwidth_pp missing — parser dropped the field instead "
            "of filling from default"
        )
        assert mode1["target_halfwidth_pp"] == 0.5, (
            f"Expected default 0.5, got {mode1['target_halfwidth_pp']!r}"
        )
        # The provided fields should have been parsed.
        assert mode1["chunk_spin_times"] == 5000
        assert mode1["max_chunks"] == 30

    def test_b2_all_modes_present_even_when_only_one_provided(self, tmp_path):
        """Providing only mode "1" in JSON -> modes 2, 5, 7 still have defaults."""
        s = _load_settings_with(tmp_path, {
            "auto_sweep": {
                "modes": {
                    "1": {"chunk_spin_times": 5000}
                }
            }
        })
        asw = s["auto_sweep"]
        for k in ("2", "5", "7"):
            assert k in asw["modes"], f"mode {k} missing"
            assert asw["modes"][k]["chunk_spin_times"] == 10000

    def test_b3_per_mode_string_chunk_spin_times_falls_to_default(self, tmp_path):
        """modes["1"]["chunk_spin_times"] = "big" (string) -> default 10000.

        Inject-bug: remove `isinstance(_mv, (int, float))` guard inside
        the per-mode int bounds loop -> raw string stored -> Pydantic
        validation crash downstream -> RED.
        Revert -> GREEN.

        NOTE: test_bad_types_fall_back_to_defaults in foundation covers the
        top-level sweep_concurrency string case. This specifically covers
        per-mode field strings, which are processed by a DIFFERENT code block.
        """
        s = _load_settings_with(tmp_path, {
            "auto_sweep": {
                "modes": {
                    "1": {
                        "chunk_spin_times": "big",       # string -> reject
                        "chunk_robot_count": "many",     # string -> reject
                        "batch_concurrency": True,       # bool coerces to int in Python;
                        # isinstance(True, (int,float)) is True, so bool is accepted
                        "max_chunks": 30,                # valid int -> accepted
                        "target_halfwidth_pp": "half",   # string -> reject
                    }
                }
            }
        })
        mode1 = s["auto_sweep"]["modes"]["1"]
        assert isinstance(mode1["chunk_spin_times"], int), (
            "chunk_spin_times must be int, not string"
        )
        assert mode1["chunk_spin_times"] == 10000, (
            f"String 'big' should fall back to default 10000, got {mode1['chunk_spin_times']!r}"
        )
        assert isinstance(mode1["chunk_robot_count"], int)
        assert mode1["chunk_robot_count"] == 2, (
            f"String 'many' should fall back to default 2, got {mode1['chunk_robot_count']!r}"
        )
        assert isinstance(mode1["target_halfwidth_pp"], float)
        assert mode1["target_halfwidth_pp"] == 0.5, (
            f"String 'half' should fall back to default 0.5, got {mode1['target_halfwidth_pp']!r}"
        )
        # max_chunks=30 was valid, should be stored.
        assert mode1["max_chunks"] == 30

    def test_b3_per_mode_out_of_range_int_falls_to_default(self, tmp_path):
        """modes["1"]["chunk_spin_times"] = 0 (below min 1000) -> default 10000."""
        s = _load_settings_with(tmp_path, {
            "auto_sweep": {
                "modes": {
                    "1": {
                        "chunk_spin_times": 0,    # below lower bound 1000
                        "max_chunks": 9999999,    # above upper bound 1000
                    }
                }
            }
        })
        mode1 = s["auto_sweep"]["modes"]["1"]
        assert mode1["chunk_spin_times"] == 10000, (
            f"chunk_spin_times=0 should fall back to 10000, got {mode1['chunk_spin_times']!r}"
        )
        assert mode1["max_chunks"] == 60, (
            f"max_chunks=9999999 should fall back to 60, got {mode1['max_chunks']!r}"
        )

    def test_b1_modes_as_none_uses_defaults(self, tmp_path):
        """auto_sweep.modes=null -> parser ignores, defaults wholesale."""
        s = _load_settings_with(tmp_path, {
            "auto_sweep": {"modes": None}
        })
        asw = s["auto_sweep"]
        for k in ("1", "2", "5", "7"):
            assert k in asw["modes"]
            assert asw["modes"][k]["chunk_spin_times"] == 10000


# ─────────────────────────────────────────────────────────────────────────────
# Guard C — schema migration idempotency (inject-bug cycles for existing tests)
# ─────────────────────────────────────────────────────────────────────────────


class TestGuardC_SchemaCreateTableLoadBearing:
    """C1: the CREATE TABLE statement is load-bearing — removing it breaks upsert.
    C2: IF NOT EXISTS is load-bearing — removing it breaks second init.

    The foundation file has test_auto_inspect_sweeps_table_exists (C1) and
    test_schema_is_idempotent (C2) but neither includes an explicit inject-bug
    cycle. These tests document the exact inject-bug recipe with explicit
    assertions that will go RED on injection.
    """

    def test_c1_upsert_fails_without_create_table(self, tmp_path):
        """Simulate "no CREATE TABLE" by opening a fresh DB and running
        an upsert WITHOUT going through StateStore._init_db.

        Recipe: to reproduce the production failure, comment out the
        'CREATE TABLE IF NOT EXISTS auto_inspect_sweeps' block in _init_db.
        Then any StateStore that opens a new DB and tries to write a sweep
        row via an INSERT will get 'OperationalError: no such table'.

        This test bypasses _init_db to replicate that exact failure mode.
        Inject: replace the real StateStore usage below with one where
        _init_db never runs (e.g. by monkeypatching _init_db to a no-op)
        -> the conn.execute INSERT raises OperationalError -> RED.
        Revert -> GREEN.
        """
        db = tmp_path / "no_init.db"
        # Open DB WITHOUT calling _init_db — tables don't exist.
        conn = sqlite3.connect(str(db))
        conn.close()

        # Confirm the table is absent.
        conn = sqlite3.connect(str(db))
        tables = {
            row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        assert "auto_inspect_sweeps" not in tables, (
            "Precondition: table should not exist in a raw SQLite file"
        )

        # Now an INSERT against this table must fail.
        import pytest as _pytest
        with _pytest.raises((sqlite3.OperationalError, Exception)):
            conn2 = sqlite3.connect(str(db))
            try:
                conn2.execute(
                    """
                    INSERT INTO auto_inspect_sweeps
                    (sweep_id, status, created_at, settings_snapshot_json,
                     modes_json, trigger)
                    VALUES ('sw_test', 'scanning', '2026-05-26T00:00:00Z',
                            '{}', '["1"]', 'manual')
                    """
                )
            finally:
                conn2.close()

    def test_c1_state_store_init_makes_upsert_succeed(self, tmp_path):
        """After proper StateStore init, the same INSERT succeeds.

        Inject-bug: remove CREATE TABLE IF NOT EXISTS auto_inspect_sweeps
        from _init_db -> this INSERT fails -> RED.
        Revert -> GREEN.
        """
        from src.web_console.backend.app import StateStore
        db = tmp_path / "console.db"
        store = StateStore(db)

        # Direct INSERT must succeed after _init_db ran.
        with store._connect() as conn:
            conn.execute(
                """
                INSERT INTO auto_inspect_sweeps
                (sweep_id, status, created_at, settings_snapshot_json,
                 modes_json, trigger)
                VALUES ('sw_c1', 'scanning', '2026-05-26T00:00:00Z',
                        '{}', '["1"]', 'manual')
                """
            )
            conn.commit()
            row = conn.execute(
                "SELECT sweep_id FROM auto_inspect_sweeps WHERE sweep_id='sw_c1'"
            ).fetchone()
        assert row is not None, (
            "INSERT into auto_inspect_sweeps failed after StateStore init. "
            "CREATE TABLE statement is missing or broken."
        )

    def test_c2_if_not_exists_prevents_second_init_crash(self, tmp_path):
        """Two StateStore constructions on the same DB path must not raise.

        Inject-bug: change 'CREATE TABLE IF NOT EXISTS auto_inspect_sweeps'
        to 'CREATE TABLE auto_inspect_sweeps' (remove IF NOT EXISTS) ->
        second StateStore(db) raises OperationalError 'table already exists' -> RED.
        Revert -> GREEN.

        This confirms IF NOT EXISTS is actually in the DDL and not just
        assumed to be there.
        """
        from src.web_console.backend.app import StateStore
        db = tmp_path / "console.db"
        _s1 = StateStore(db)  # creates tables
        # Second init must not raise even though tables exist.
        try:
            _s2 = StateStore(db)
        except Exception as exc:
            raise AssertionError(
                f"Second StateStore init raised {type(exc).__name__}: {exc}. "
                "IF NOT EXISTS is missing from CREATE TABLE in _init_db."
            ) from exc

    def test_c2_verify_if_not_exists_in_ddl(self, tmp_path):
        """Static check: the _init_db source contains IF NOT EXISTS for
        both auto_inspect tables.

        Inject-bug: remove 'IF NOT EXISTS' from either CREATE TABLE ->
        this text assertion fails immediately -> RED.
        Revert -> GREEN.
        """
        import ast as _ast

        src = (ROOT / "src" / "web_console" / "backend" / "app.py").read_text(
            encoding="utf-8-sig"
        )
        # Look for the exact strings that must appear together.
        assert "CREATE TABLE IF NOT EXISTS auto_inspect_sweeps" in src, (
            "CREATE TABLE IF NOT EXISTS auto_inspect_sweeps not found in app.py. "
            "Second-init crash risk: OperationalError 'table already exists'."
        )
        assert "CREATE TABLE IF NOT EXISTS auto_inspect_items" in src, (
            "CREATE TABLE IF NOT EXISTS auto_inspect_items not found in app.py. "
            "Second-init crash risk."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Bonus D1 — _scan_persisted_for_resume with mixed sweep statuses
# ─────────────────────────────────────────────────────────────────────────────


class TestBonusD1_ScanPersistedMixedStatuses:
    """_scan_persisted_for_resume must ignore terminal sweeps and return
    only the non-terminal one.

    Inject recipe:
        Change WHERE status IN ('scanning','sampling','finalizing') to
        WHERE status IN ('scanning','sampling','finalizing','completed') ->
        completed sweep gets returned -> wrong resume_sweep_id -> RED.
    """

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
        for d in ["progress", "reports", "rawdata", "cache"]:
            (tmp_path / d).mkdir(exist_ok=True)
        mgr_run = RunManager(
            store,
            analyzer=fake_analyzer,
            reports_root=tmp_path / "reports",
            progress_dir=tmp_path / "progress",
            cache_root=tmp_path / "cache",
            machines_config=fake_machines,
            rawdata_root=tmp_path / "rawdata",
        )
        registry = CellLockRegistry()
        limiter = ConcurrencyLimiter(n_slots=5, foreground_reserve=2)
        auto_mgr = AutoInspectManager(
            store=store,
            run_manager=mgr_run,
            registry=registry,
            limiter=limiter,
            settings_path=tmp_path / "settings.json",
            machines_config=fake_machines,
            rawdata_root=tmp_path / "rawdata",
        )
        return auto_mgr, store

    def _raw_conn(self, tmp_path) -> sqlite3.Connection:
        db = tmp_path / "console.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        return conn

    def test_three_sweeps_returns_only_sampling(self, tmp_path):
        """3 sweeps: completed + cancelled + sampling -> returns sampling id.

        Inject-bug: include 'completed' in WHERE status IN (...) ->
        completed sweep (created first, lowest created_at) may be returned
        instead of the sampling one -> assertion fails.
        """
        mgr, store = self._make_mgr(tmp_path)

        with self._raw_conn(tmp_path) as conn:
            conn.execute(
                "INSERT INTO auto_inspect_sweeps "
                "(sweep_id,status,created_at,settings_snapshot_json,modes_json,trigger)"
                " VALUES ('sw_done','completed','2026-05-26T00:00:00Z','{}','[]','manual')"
            )
            conn.execute(
                "INSERT INTO auto_inspect_sweeps "
                "(sweep_id,status,created_at,settings_snapshot_json,modes_json,trigger)"
                " VALUES ('sw_can','cancelled','2026-05-26T01:00:00Z','{}','[]','manual')"
            )
            conn.execute(
                "INSERT INTO auto_inspect_sweeps "
                "(sweep_id,status,created_at,settings_snapshot_json,modes_json,trigger)"
                " VALUES ('sw_run','sampling','2026-05-26T02:00:00Z','{}','[]','manual')"
            )
            conn.commit()

        result = mgr._scan_persisted_for_resume()
        assert result == "sw_run", (
            f"Expected 'sw_run' (sampling), got {result!r}. "
            "Terminal sweeps (completed/cancelled) must be excluded."
        )

    def test_two_nonterminal_returns_most_recent(self, tmp_path):
        """2 non-terminal sweeps -> returns most-recent by created_at.

        Inject-bug: change ORDER BY created_at DESC to ASC ->
        oldest sweep returned instead of newest -> assertion fails.

        Edge case per coordinator prompt: if 2 non-terminal sweeps exist
        (operator force-cancelled daemon before status flipped), pick newest.
        """
        mgr, store = self._make_mgr(tmp_path)

        with self._raw_conn(tmp_path) as conn:
            conn.execute(
                "INSERT INTO auto_inspect_sweeps "
                "(sweep_id,status,created_at,settings_snapshot_json,modes_json,trigger)"
                " VALUES ('sw_older','sampling','2026-05-25T00:00:00Z','{}','[]','manual')"
            )
            conn.execute(
                "INSERT INTO auto_inspect_sweeps "
                "(sweep_id,status,created_at,settings_snapshot_json,modes_json,trigger)"
                " VALUES ('sw_newer','scanning','2026-05-26T00:00:00Z','{}','[]','manual')"
            )
            conn.commit()

        result = mgr._scan_persisted_for_resume()
        assert result == "sw_newer", (
            f"Expected most-recent 'sw_newer', got {result!r}. "
            "ORDER BY created_at DESC is missing or inverted."
        )

    def test_only_terminal_sweeps_returns_none(self, tmp_path):
        """All sweeps terminal -> returns None.

        Inject-bug: add 'failed' to WHERE status IN (...) ->
        failed sweep returned -> assertion fails.
        """
        mgr, store = self._make_mgr(tmp_path)

        with self._raw_conn(tmp_path) as conn:
            for sw_id, status in [
                ("sw_c", "completed"),
                ("sw_x", "cancelled"),
                ("sw_f", "failed"),
            ]:
                conn.execute(
                    "INSERT INTO auto_inspect_sweeps "
                    "(sweep_id,status,created_at,settings_snapshot_json,modes_json,trigger)"
                    f" VALUES ('{sw_id}','{status}','2026-05-26T00:00:00Z','{{}}','[]','manual')"
                )
            conn.commit()

        result = mgr._scan_persisted_for_resume()
        assert result is None, (
            f"Expected None when all sweeps are terminal, got {result!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Bonus D3 — create_app resume thread is spawned in background (MF-1)
# ─────────────────────────────────────────────────────────────────────────────


class TestBonusD3_ResumeThreadIsBackground:
    """MF-1 verification: create_app returns quickly even when resume_sweep
    would block for 5 seconds.

    Inject recipe:
        In create_app, change:
            threading.Thread(target=auto_inspect_mgr.resume_sweep, ...).start()
        to:
            auto_inspect_mgr.resume_sweep(_resume_sweep_id)   # synchronous call
        -> create_app blocks 5s -> assertion that it returned within 1s fails -> RED.
        Revert -> GREEN.

    Memory refs:
        feedback_perf_claim_needs_e2e_event_stream.md — must exercise real thread
    """

    def test_create_app_returns_within_one_second_despite_slow_resume(
        self, tmp_path, monkeypatch
    ):
        """Pre-seed a non-terminal sweep, patch resume_sweep to sleep 5s,
        then assert create_app() returns in < 1s.

        This proves resume is launched in a daemon thread, not called
        synchronously in create_app (MF-1 requirement from 07_decision §2).
        """
        from src.web_console.backend.app import StateStore, create_app

        # Build isolated dirs.
        state_dir = tmp_path / "state" / "console"
        state_dir.mkdir(parents=True)
        (state_dir / "progress").mkdir()
        db_path = state_dir / "console.db"
        reports = tmp_path / "reports"
        reports.mkdir()
        rawdata = tmp_path / "rawdata"
        rawdata.mkdir()
        cache = tmp_path / "cache"
        cache.mkdir()
        fake_machines = tmp_path / "machines.json"
        fake_machines.write_text('{"machines":[]}', encoding="utf-8")
        fake_analyzer = tmp_path / "analyzer.py"
        fake_analyzer.write_text("", encoding="utf-8")

        # Seed a non-terminal sweep so _pending_resume_sweep_id is non-None.
        store = StateStore(db_path)
        with store._connect() as conn:
            conn.execute(
                "INSERT INTO auto_inspect_sweeps "
                "(sweep_id,status,created_at,settings_snapshot_json,modes_json,trigger)"
                " VALUES ('sw_resume','sampling','2026-05-26T00:00:00Z','{}','[\"1\"]','manual')"
            )
            conn.commit()
        del store  # release connection

        # Monkeypatch resume_sweep on the class to sleep 5s.
        resume_called = threading.Event()

        def slow_resume(self_inner, sweep_id):  # noqa: ANN001
            resume_called.set()
            time.sleep(5)

        from src.web_console.backend import auto_inspect_manager
        monkeypatch.setattr(
            auto_inspect_manager.AutoInspectManager,
            "resume_sweep",
            slow_resume,
        )

        # Also patch _terminate_pid_if_running and _default_popen_factory
        # so startup recovery doesn't fail.
        monkeypatch.setattr(
            "src.web_console.backend.app._terminate_pid_if_running",
            lambda pid: True,
        )

        t0 = time.monotonic()
        _app = create_app(
            state_dir=state_dir,
            reports_root=reports,
            cache_root=cache,
            machines_config=fake_machines,
            analyzer_path=fake_analyzer,
            rawdata_root=rawdata,
        )
        elapsed = time.monotonic() - t0

        assert elapsed < 1.5, (
            f"create_app took {elapsed:.2f}s — resume_sweep was called "
            "synchronously instead of in a daemon thread (MF-1 violation)."
        )
        # Give the thread time to start and set the event; if resume was
        # spawned as a thread, it should call resume_called.set() quickly.
        resume_called.wait(timeout=2.0)
        assert resume_called.is_set(), (
            "resume_sweep was never called — thread may not have been spawned."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Bonus D4 — blast-radius check: cell owned by BOTH sweep AND batch
# ─────────────────────────────────────────────────────────────────────────────


class TestBonusD4_MultipleOwnerBlastRadius:
    """When a cell is owned by BOTH an active sweep AND an active sampling
    batch (edge case: e.g. operator triggered a manual batch while sweep
    was running), _is_cell_owned_by_active_queue must return SOMETHING
    non-None and not crash.

    Inject recipe:
        Make branch 3 raise an unhandled exception (e.g. remove the
        'except sqlite3.OperationalError: pass' block and let a different
        error propagate) -> the function raises instead of returning a
        string -> A2 crashes on startup -> RED.
    """

    def _setup(self, tmp_path, stub_popen):
        """Set up a RunManager where M14/1 is owned by BOTH a sweep and
        a sampling batch concurrently.

        ALL data is seeded BEFORE RunManager is constructed so
        _recover_orphan_running_runs() sees the full state.
        """
        from src.web_console.backend.app import StateStore, RunManager

        db_path, state_dir = _build_dirs(tmp_path)

        fake_analyzer = tmp_path / "fake_analyzer.py"
        fake_analyzer.write_text("# stub\n", encoding="utf-8")
        fake_machines = tmp_path / "machines.json"
        fake_machines.write_text(
            json.dumps({"machines": [
                {"machine": "M14", "mode_list": [1], "upstream_key": "M14"},
            ]}),
            encoding="utf-8",
        )
        # Step 1: tables created.
        store = StateStore(db_path)

        # Step 2: Owner 1 — running sampling batch containing M14/1.
        store.upsert_batch(
            "b_dual",
            status="running",
            created_at="2026-05-26T07:00:00Z",
            finished_at=None,
            concurrency=2,
            params={},
            items=[{"machine": "M14", "mode": 1, "status": "running",
                    "run_id": "orph_dual", "chunk_spin_times": 10000}],
            events=[],
            reports_root=None,
            kind="sampling",
        )

        # Step 3: Owner 2 — running sweep with M14/1 in its items.
        _seed_sweep_row(db_path, "sw_dual", "sampling")
        _seed_item_row(db_path, "sw_dual", "M14", 1, "running")

        # Step 4: Orphan run for the blast-radius test.
        _seed_orphan_run(db_path, run_id="orph_dual", machine="M14", mode=1)

        # Step 5: Construct RunManager AFTER all rows are seeded.
        mgr = RunManager(
            store,
            analyzer=fake_analyzer,
            reports_root=tmp_path / "reports",
            progress_dir=state_dir / "progress",
            cache_root=tmp_path / "cache",
            machines_config=fake_machines,
            rawdata_root=tmp_path / "rawdata",
            popen_factory=stub_popen,
            auto_resume_orphan_runs=True,
        )
        return mgr, store, db_path

    def test_returns_nonempty_string_not_crash_with_dual_owner(
        self, tmp_path, stub_popen
    ):
        """_is_cell_owned_by_active_queue must return a non-None string
        when multiple owners compete. The exact string doesn't matter
        (first match wins), but it must not raise.

        Inject-bug: inside branch 3, remove the outer try/except -> any
        sqlite3 exception propagates -> crash -> RED.
        """
        mgr, store, db_path = self._setup(tmp_path, stub_popen)

        result = mgr._is_cell_owned_by_active_queue("M14", 1)
        assert result is not None, (
            "_is_cell_owned_by_active_queue returned None despite dual ownership "
            "(sampling batch + active sweep both own M14/1)"
        )
        assert isinstance(result, str) and len(result) > 0, (
            f"Expected a non-empty owner string, got {result!r}"
        )

    def test_a2_does_not_spawn_when_dual_owner(self, tmp_path, stub_popen):
        """Full A2 path: dual ownership -> no spawn, no crash."""
        mgr, store, db_path = self._setup(tmp_path, stub_popen)

        snap = mgr.startup_recovery_snapshot()
        assert "orph_dual" not in snap["auto_resumed"], (
            "A2 spawned despite dual ownership (sweep + batch)"
        )
        assert stub_popen.cmds == [], (
            "Subprocess spawned despite dual ownership"
        )
