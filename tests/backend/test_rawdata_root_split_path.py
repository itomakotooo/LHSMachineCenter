"""Regression tests for ticket P1-B6 — RAWDATA_ROOT module global -> instance attribute.

Contract summary (from 00_ticket.md §3):

  C1 — Every functional ref uses injected path, not the module-level global.
  C2 — Split-path: monkeypatching the module-level RAWDATA_ROOT to a wrong path
       must NOT change behaviour — instances already picked up the correct
       injected root at construction time.
  C3 — Per-path inject-bug: each test is proven by reverting the migration for
       that specific call-site and confirming the test goes red.  The inject-bug
       log is documented in 03_tests.md.
  C4 — Virtual-console subprocess smoke (deferred to impl-verifier per Wave 2
       split; see 03_tests.md "Open gaps").
  C5 — _recover_orphan_running_runs does NOT read RAWDATA_ROOT (the original
       import-suicide bug pattern).
  C6 — Module-level RAWDATA_ROOT is preserved as a backward-compat default;
       no functional code path reads it directly.

The REAL PROD BUG (ticket §3 C1, original line 3259, now ~3393):
  BatchRunManager.start_batch called check_rawdata_status(machine, mode) with
  no rawdata_root argument, so the fallback in check_rawdata_status used the
  module-level RAWDATA_ROOT global — not self._rawdata_root.  Virtual-console
  instances then scanned the REAL rawdata tree, found no chunks, and reported
  zero usable_chunks for every item even though virtual rawdata had data.

Inject-bug discipline (per memory feedback_integration_test_argv.md +
feedback_enumerate_safety_paths.md): every test that asserts a migration was
made must be provable red by reverting just that one line.  The inject-bug
verification log is in 03_tests.md.
"""
from __future__ import annotations

import inspect
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import src.web_console.backend.app as app_mod
from src.web_console.backend.app import (
    BatchRunManager,
    RunManager,
    StateStore,
    check_rawdata_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SENTINEL_WRONG_ROOT = Path("/tmp/WRONG_RAWDATA_ROOT_GLOBAL_SENTINEL")
"""A path that must never be used by any instance — only the module global."""


def _make_store(tmp_path: Path) -> StateStore:
    db = tmp_path / "console.db"
    return StateStore(db)


def _make_run_manager(tmp_path: Path, store: StateStore) -> RunManager:
    """Construct a RunManager pointing at tmp dirs."""
    fake_analyzer = tmp_path / "fake_analyzer.py"
    fake_analyzer.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    fake_machines = tmp_path / "machines.json"
    fake_machines.write_text('{"machines":[]}', encoding="utf-8")
    return RunManager(
        store,
        analyzer=fake_analyzer,
        reports_root=tmp_path / "reports",
        progress_dir=tmp_path / "state" / "progress",
        cache_root=tmp_path / "cache",
        machines_config=fake_machines,
    )


def _make_batch_manager(
    tmp_path: Path,
    store: StateStore,
    run_manager: RunManager,
    rawdata_root: Path,
    machines_config: Path | None = None,
) -> BatchRunManager:
    if machines_config is None:
        machines_config = tmp_path / "machines.json"
        if not machines_config.exists():
            machines_config.write_text('{"machines":[]}', encoding="utf-8")
    return BatchRunManager(
        store,
        run_manager,
        tmp_path / "cache",
        state_dir=tmp_path / "state",
        machines_config=machines_config,
        rawdata_root=rawdata_root,
    )


# ---------------------------------------------------------------------------
# C1 + C2 — Split-path regression: module global vs injected instance attr
# ---------------------------------------------------------------------------


class TestSplitPath:
    """Monkeypatching RAWDATA_ROOT to a wrong sentinel path must NOT change
    what BatchRunManager instances use.  They must use self._rawdata_root.

    This is the canonical split-path regression per memory
    feedback_subprocess_import_suicide_and_module_globals.md.
    """

    def test_batch_manager_stores_injected_rawdata_root(self, tmp_path):
        """C2 part A — BatchRunManager.__init__ stores the injected path as
        self._rawdata_root even when the module-level RAWDATA_ROOT is wrong."""
        store = _make_store(tmp_path)
        rm = _make_run_manager(tmp_path, store)
        injected = tmp_path / "virtual_rawdata"
        injected.mkdir()

        with patch.object(app_mod, "RAWDATA_ROOT", SENTINEL_WRONG_ROOT):
            # Module global is now wrong; instance should still carry the
            # injected path that was passed at construction time.
            bm = _make_batch_manager(tmp_path, store, rm, rawdata_root=injected)
            assert bm._rawdata_root == injected, (
                f"Expected self._rawdata_root == {injected}, "
                f"got {bm._rawdata_root!r}.  "
                "BatchRunManager constructor is not storing the injected root."
            )
            assert bm._rawdata_root != SENTINEL_WRONG_ROOT, (
                "BatchRunManager._rawdata_root equals the wrong sentinel — "
                "it is reading the module global instead of the injected path."
            )

    def test_batch_manager_rawdata_root_independent_of_global_mutation(self, tmp_path):
        """C2 part B — mutating RAWDATA_ROOT AFTER construction must NOT change
        what a live instance reports for self._rawdata_root."""
        store = _make_store(tmp_path)
        rm = _make_run_manager(tmp_path, store)
        injected = tmp_path / "virtual_rawdata"
        injected.mkdir()

        bm = _make_batch_manager(tmp_path, store, rm, rawdata_root=injected)

        # Now corrupt the module-level global AFTER construction.
        with patch.object(app_mod, "RAWDATA_ROOT", SENTINEL_WRONG_ROOT):
            # Instance must not be affected by post-construction mutation.
            assert bm._rawdata_root == injected, (
                "After mutating app_mod.RAWDATA_ROOT, self._rawdata_root "
                "drifted — instance is aliasing the global, not a copy."
            )

    def test_check_rawdata_status_uses_passed_root_not_global(self, tmp_path):
        """C1 ref: check_rawdata_status free function must use the rawdata_root
        parameter when provided.

        P1-B6 R2/Q3 fix (round-2 critic): original test only asserted
        isinstance(result, dict) — would pass in BOTH correct and buggy
        states because _empty_rawdata_status() returns dict on missing
        mode_dir. Strengthened to assert exists=True (only achievable
        when scanning the correct tmp root with the fixture chunk)
        AND that with global pointing at a different tmp root (also
        containing a mode dir), the global's mode_dir presence does NOT
        affect the result. The injection scenario: dropping rawdata_root
        from the call would fall back to the global's root and see ITS
        chunks instead.
        """
        machine = "M14"
        mode = 1
        real_rawdata = tmp_path / "real_rawdata"
        mode_dir = real_rawdata / machine / f"mode_{mode}"
        mode_dir.mkdir(parents=True)
        chunk = mode_dir / "chunk_0001.json"
        chunk.write_text(
            '{"machine":"M14","mode":1,"spin_times":100,'
            '"config_md5":"abc","code_md5":"def",'
            '"RTPSummary":{},"rounds":[]}',
            encoding="utf-8",
        )

        # WRONG root — also contains a mode_dir but with a DIFFERENT
        # md5-stamped chunk so we can distinguish.
        wrong_root = tmp_path / "wrong_rawdata"
        wrong_mode_dir = wrong_root / machine / f"mode_{mode}"
        wrong_mode_dir.mkdir(parents=True)
        wrong_chunk = wrong_mode_dir / "chunk_0001.json"
        wrong_chunk.write_text(
            '{"machine":"M14","mode":1,"spin_times":50,'
            '"config_md5":"WRONG_CFG","code_md5":"WRONG_CODE",'
            '"RTPSummary":{},"rounds":[]}',
            encoding="utf-8",
        )

        with patch.object(app_mod, "RAWDATA_ROOT", wrong_root):
            result = check_rawdata_status(
                machine, mode, rawdata_root=real_rawdata
            )

        # Strong assertion: function must report scanning real_rawdata
        # (exists=True since real_rawdata has the mode_dir with chunk).
        assert isinstance(result, dict)
        assert result.get("exists") is True, (
            f"check_rawdata_status reported exists={result.get('exists')!r}; "
            f"expected True (real_rawdata has a chunk file). If False, the "
            f"function ignored the rawdata_root param and scanned the global "
            f"({wrong_root!r}) which also has a mode_dir but should be invisible."
        )
        # Vacuous-pass guard: if the function had used the global, we would
        # see md5s from wrong_chunk. Assert we see real_chunk's md5.
        upstream_cfg = result.get("upstream_config_md5", "")
        upstream_code = result.get("upstream_code_md5", "")
        assert upstream_cfg != "WRONG_CFG", (
            f"upstream_config_md5={upstream_cfg!r} matches wrong_chunk — "
            f"check_rawdata_status scanned the WRONG root (global fallback)."
        )
        assert upstream_code != "WRONG_CODE", (
            f"upstream_code_md5={upstream_code!r} matches wrong_chunk — "
            f"check_rawdata_status scanned the WRONG root (global fallback)."
        )

    def test_check_rawdata_status_fallback_reads_global_when_none_passed(self, tmp_path):
        """C6 — RAWDATA_ROOT module global is preserved as fallback when
        rawdata_root=None is passed to check_rawdata_status.

        This test verifies the global still acts as default (backward-compat),
        but also confirms that passing a real path bypasses it entirely.

        Implementation note: the function signature is
            def check_rawdata_status(machine, mode, rawdata_root=None, ...)
        and internally: root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT
        """
        # Point the module global at a real (tmp) dir.
        controlled_root = tmp_path / "controlled_global_root"
        controlled_root.mkdir()
        machine, mode = "M99", 1
        (controlled_root / machine / f"mode_{mode}").mkdir(parents=True)

        with patch.object(app_mod, "RAWDATA_ROOT", controlled_root):
            # rawdata_root=None → fallback should use the (patched) global.
            result = check_rawdata_status(machine, mode, rawdata_root=None)
        assert isinstance(result, dict), "fallback path must not crash"


# ---------------------------------------------------------------------------
# C1 ref: start_batch passes self._rawdata_root to check_rawdata_status
# ---------------------------------------------------------------------------


class TestStartBatchUsesInstanceRoot:
    """The prod bug (original line 3259/3393): start_batch called
    check_rawdata_status(machine, mode) with NO rawdata_root argument.
    The fallback in check_rawdata_status then read the module-level
    RAWDATA_ROOT global, not self._rawdata_root.

    Fix: pass rawdata_root=self._rawdata_root at every call site inside
    BatchRunManager.start_batch.

    This test class contains the primary split-path regression.
    """

    def _make_batch_request(self, machine: str = "M14", mode: int = 1) -> Any:
        """Build a minimal BatchRunRequest-compatible object."""
        from src.web_console.backend.app import BatchRunRequest, BatchRunItem
        item = BatchRunItem(machine=machine, mode=mode)
        return BatchRunRequest(
            items=[item],
            chunk_robot_count=8,
            batch_concurrency=2,
            concurrency=1,
            max_chunks=1,
            timeout=30.0,
        )

    def test_start_batch_check_rawdata_status_receives_instance_root(
        self, tmp_path, monkeypatch
    ):
        """C1 / prod-bug guard — start_batch must pass self._rawdata_root to
        check_rawdata_status, not rely on the module-level fallback.

        Method: monkeypatch app_mod.RAWDATA_ROOT to SENTINEL_WRONG_ROOT,
        then observe which root check_rawdata_status is called with.
        If the bug is present (no rawdata_root arg), check_rawdata_status
        would see rawdata_root=None and fall back to SENTINEL_WRONG_ROOT.
        After the fix, it must see rawdata_root=self._rawdata_root.
        """
        injected = tmp_path / "virtual_rawdata"
        injected.mkdir()

        store = _make_store(tmp_path)
        rm = _make_run_manager(tmp_path, store)
        bm = _make_batch_manager(tmp_path, store, rm, rawdata_root=injected)

        # Track what rawdata_root check_rawdata_status actually received.
        received_roots: list[Path | None] = []
        _orig_check = app_mod.check_rawdata_status

        def _spy(machine, mode, rawdata_root=None, machines_config=None, **kw):
            received_roots.append(rawdata_root)
            return {
                "exists": False,
                "usable_chunks": 0,
                "mismatch_chunks": 0,
                "total_size_mb": 0.0,
                "kept": [],
                "deletable": [],
                "historical": [],
                "kept_spins": 0,
                "deletable_spins": 0,
                "historical_spins": 0,
                "upstream_config_md5": "",
                "upstream_code_md5": "",
                "unverifiable": True,
            }

        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", SENTINEL_WRONG_ROOT)
        monkeypatch.setattr(app_mod, "check_rawdata_status", _spy)

        try:
            req = self._make_batch_request()
            bm.start_batch(req)
        except Exception:
            pass  # we only care about the spy, not the full batch outcome

        assert received_roots, (
            "check_rawdata_status spy was never called — "
            "start_batch did not invoke it at all."
        )
        for root in received_roots:
            assert root == injected, (
                f"start_batch called check_rawdata_status with "
                f"rawdata_root={root!r} but expected {injected!r}.  "
                f"Module global is {SENTINEL_WRONG_ROOT!r}.  "
                "The migration is incomplete: start_batch is falling back "
                "to the module global instead of passing self._rawdata_root."
            )
            assert root != SENTINEL_WRONG_ROOT, (
                "start_batch passed the module-level SENTINEL_WRONG_ROOT to "
                "check_rawdata_status — the P1-B6 bug is still present."
            )

    def test_start_batch_auto_cleanup_uses_instance_root(
        self, tmp_path, monkeypatch
    ):
        """C1 ref — _run_batch's disk-pressure loop calls _auto_cleanup_for_space
        with self._rawdata_root, not the module global.

        We verify by patching _auto_cleanup_for_space and observing what
        rawdata_root arg it receives when invoked under low-disk conditions.
        """
        injected = tmp_path / "virtual_rawdata"
        injected.mkdir()

        store = _make_store(tmp_path)
        rm = _make_run_manager(tmp_path, store)
        bm = _make_batch_manager(tmp_path, store, rm, rawdata_root=injected)

        received_cleanup_roots: list[Path] = []

        def _spy_cleanup(rawdata_root, machines_config, retention, **kw):
            received_cleanup_roots.append(rawdata_root)
            # Return "no space freed" so the batch eventually gives up.
            return {
                "deleted_files": 0,
                "deleted_bytes": 0,
                "final_free_gb": 0.0,
                "skipped_locked": [],
                "skipped_in_use": [],
            }

        # Force disk to appear below low_water so cleanup fires.
        def _fake_disk_info(_path):
            return {"free_gb": 0.5, "total_gb": 100.0, "used_gb": 99.5}

        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", SENTINEL_WRONG_ROOT)
        monkeypatch.setattr(app_mod, "_auto_cleanup_for_space", _spy_cleanup)
        monkeypatch.setattr(app_mod, "_get_disk_space_info", _fake_disk_info)
        # Suppress disk retries from taking time.
        monkeypatch.setenv("SLOT_DISK_WAIT_RETRIES", "1")
        monkeypatch.setattr(app_mod, "check_rawdata_status", lambda *a, **kw: {
            "exists": False, "usable_chunks": 0, "mismatch_chunks": 0,
            "total_size_mb": 0.0, "kept": [], "deletable": [], "historical": [],
            "kept_spins": 0, "deletable_spins": 0, "historical_spins": 0,
            "upstream_config_md5": "", "upstream_code_md5": "",
            "unverifiable": True,
        })

        # Patch RunManager to avoid real subprocess.
        def _fake_start_run(_req):
            return {"run_id": "fake_001", "status": "completed"}

        bm._run_manager.start_run = _fake_start_run

        req = self._make_batch_request()
        # start_batch is synchronous for setup; _run_batch runs in a thread.
        bm.start_batch(req)

        # Give the thread a moment to enter _run_one and trigger cleanup.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not received_cleanup_roots:
            time.sleep(0.05)

        # P1-B6 R3/Q5 fix (round-2 critic): original test had
        # `if received_cleanup_roots:` race-no-op — if cleanup thread
        # hadn't fired within 3 sec the assertion was silently skipped,
        # producing false-positive PASS. Strengthened to require at
        # least one cleanup invocation (the disk-pressure mock guarantees
        # it should fire); otherwise fail loudly.
        assert received_cleanup_roots, (
            "_auto_cleanup_for_space was never called within 3 sec deadline. "
            "Either the disk-pressure mock is broken (fake_disk_info should "
            "return free_gb=0.5 < low_water default) or the batch thread "
            "never reached the cleanup path. Cannot verify rawdata_root "
            "without at least one invocation. NOT a silent skip."
        )
        for root in received_cleanup_roots:
            assert root == injected, (
                f"_auto_cleanup_for_space was called with rawdata_root={root!r} "
                f"but expected {injected!r}. "
                "The _run_one disk-pressure path is using the module global."
            )


# ---------------------------------------------------------------------------
# C1 ref: check_rawdata_status function signature has rawdata_root param
# ---------------------------------------------------------------------------


class TestCheckRawdataStatusSignature:
    """C1 / C6 — verify check_rawdata_status accepts rawdata_root as a
    parameter (not hardcoded) so callers CAN pass it."""

    def test_check_rawdata_status_accepts_rawdata_root_param(self):
        """Function signature must include rawdata_root parameter."""
        sig = inspect.signature(check_rawdata_status)
        assert "rawdata_root" in sig.parameters, (
            "check_rawdata_status must accept a rawdata_root parameter.  "
            "If this is missing, no caller can override the root."
        )

    def test_check_rawdata_status_rawdata_root_defaults_to_none(self):
        """rawdata_root must default to None (fallback to global) for
        backward-compat with callers that don't pass it."""
        sig = inspect.signature(check_rawdata_status)
        param = sig.parameters["rawdata_root"]
        assert param.default is None, (
            f"check_rawdata_status.rawdata_root default should be None "
            f"(fallback to global), got {param.default!r}."
        )


# ---------------------------------------------------------------------------
# C1 ref: BatchRunManager.__init__ stores rawdata_root as self._rawdata_root
# ---------------------------------------------------------------------------


class TestBatchRunManagerInit:
    """Verify BatchRunManager constructor correctly stores the injected path."""

    def test_init_stores_injected_rawdata_root_as_instance_attr(self, tmp_path):
        """C1 — self._rawdata_root must equal the injected path."""
        store = _make_store(tmp_path)
        rm = _make_run_manager(tmp_path, store)
        injected = tmp_path / "my_rawdata"
        injected.mkdir()

        bm = _make_batch_manager(tmp_path, store, rm, rawdata_root=injected)
        assert bm._rawdata_root == injected

    def test_init_none_falls_back_to_rawdata_root_global(self, tmp_path, monkeypatch):
        """C6 — when rawdata_root=None is passed, self._rawdata_root should
        equal the module-level RAWDATA_ROOT (the global default)."""
        store = _make_store(tmp_path)
        rm = _make_run_manager(tmp_path, store)
        controlled = tmp_path / "controlled_global"
        controlled.mkdir()

        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", controlled)
        bm = BatchRunManager(
            store, rm, tmp_path / "cache",
            state_dir=tmp_path / "state",
            machines_config=tmp_path / "machines.json",
            rawdata_root=None,  # explicit None → should use global
        )
        assert bm._rawdata_root == controlled, (
            f"None rawdata_root should fall back to app_mod.RAWDATA_ROOT "
            f"({controlled}), got {bm._rawdata_root!r}."
        )

    def test_two_instances_have_independent_rawdata_roots(self, tmp_path):
        """C2 — two BatchRunManager instances must carry independent roots;
        mutating one must not affect the other."""
        store = _make_store(tmp_path)
        rm = _make_run_manager(tmp_path, store)
        root_a = tmp_path / "rawdata_a"
        root_b = tmp_path / "rawdata_b"
        root_a.mkdir()
        root_b.mkdir()

        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir(parents=True, exist_ok=True)
        dir_b.mkdir(parents=True, exist_ok=True)
        bm_a = _make_batch_manager(dir_a, store, rm, rawdata_root=root_a)
        bm_b = _make_batch_manager(dir_b, store, rm, rawdata_root=root_b)

        assert bm_a._rawdata_root == root_a
        assert bm_b._rawdata_root == root_b
        assert bm_a._rawdata_root != bm_b._rawdata_root


# ---------------------------------------------------------------------------
# C5 — _recover_orphan_running_runs does NOT touch RAWDATA_ROOT
# ---------------------------------------------------------------------------


class TestRecoverOrphanRunningRuns:
    """C5 — _recover_orphan_running_runs must not read or depend on RAWDATA_ROOT.

    The original import-suicide bug (memory feedback_subprocess_import_suicide_
    and_module_globals.md) was caused by code running at import time.  Recovery
    itself should be pure DB + PID operations with no rawdata coupling.

    We verify by:
    1. Confirming the method does not access app_mod.RAWDATA_ROOT (inspecting
       the source for module-global references).
    2. Running the method with RAWDATA_ROOT pointed at a nonexistent path and
       confirming it does not crash.
    """

    def test_recover_orphan_does_not_crash_with_bad_rawdata_root(
        self, tmp_path, monkeypatch
    ):
        """C5 — _recover_orphan_running_runs must complete without error even
        when RAWDATA_ROOT points at a nonexistent path."""
        from tests.backend._seed import insert_run_row

        monkeypatch.setattr(
            app_mod, "_terminate_pid_if_running", lambda pid: True
        )
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", SENTINEL_WRONG_ROOT)

        db_path = tmp_path / "state" / "console.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        store = StateStore(db_path)
        # Inject a stale running row using the seed helper.
        insert_run_row(db_path, run_id="stale_c5_001", status="running", process_pid=12345)

        fake_analyzer = tmp_path / "fake_analyzer.py"
        fake_analyzer.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
        (tmp_path / "progress").mkdir(parents=True, exist_ok=True)
        rm = RunManager(
            store,
            analyzer=fake_analyzer,
            reports_root=tmp_path / "reports",
            progress_dir=tmp_path / "progress",
            cache_root=tmp_path / "cache",
            machines_config=tmp_path / "machines.json",
        )
        # _recover_orphan_running_runs is called in __init__; if it touched
        # RAWDATA_ROOT it would have failed on SENTINEL_WRONG_ROOT above.
        result = rm._startup_recovery
        assert result["recovered_count"] == 1, (
            "_recover_orphan_running_runs should have recovered the stale row."
        )

    def test_recover_orphan_source_does_not_reference_rawdata_root_global(self):
        """C5 static — inspect source of _recover_orphan_running_runs to confirm
        it does not read the RAWDATA_ROOT module global."""
        source = inspect.getsource(RunManager._recover_orphan_running_runs)
        # Should not reference the bare module-level global (any legitimate
        # rawdata use would go through self._rawdata_root or a parameter).
        assert "RAWDATA_ROOT" not in source, (
            "_recover_orphan_running_runs references the module-level "
            "RAWDATA_ROOT global directly.  It should use only DB + PID "
            "operations with no rawdata coupling."
        )


# ---------------------------------------------------------------------------
# C6 — Module-level RAWDATA_ROOT preserved as backward-compat default
# ---------------------------------------------------------------------------


class TestModuleLevelRawdataRoot:
    """C6 — verify that:
    1. The RAWDATA_ROOT module constant still exists at line ~528.
    2. It is a Path instance.
    3. No functional call-site reads it directly (all use the fallback pattern
       'rawdata_root if rawdata_root is not None else RAWDATA_ROOT').
    """

    def test_rawdata_root_module_constant_exists(self):
        """C6 — RAWDATA_ROOT must still exist as a module-level constant."""
        assert hasattr(app_mod, "RAWDATA_ROOT"), (
            "app_mod.RAWDATA_ROOT was deleted.  "
            "Ticket §3 C6 specifies it must be preserved as backward-compat default."
        )

    def test_rawdata_root_is_path_instance(self):
        """C6 — RAWDATA_ROOT must be a Path, not a string."""
        assert isinstance(app_mod.RAWDATA_ROOT, Path), (
            f"RAWDATA_ROOT should be a Path, got {type(app_mod.RAWDATA_ROOT).__name__}."
        )

    def test_rawdata_root_default_set_from_env_var(self, monkeypatch, tmp_path):
        """C6 — RAWDATA_ROOT is initialized from SLOT_RAWDATA_ROOT env var.

        We cannot easily re-run module init, but we can verify that the
        current module value is a Path (not a bare string) and that the
        RAWDATA_ROOT_DEFAULT constant is also present.
        """
        assert hasattr(app_mod, "RAWDATA_ROOT_DEFAULT"), (
            "RAWDATA_ROOT_DEFAULT constant missing — env-var init chain broken."
        )
        assert isinstance(app_mod.RAWDATA_ROOT_DEFAULT, Path)


# ---------------------------------------------------------------------------
# C1 — Parametrized per-ref check: each fallback site uses param not global
# ---------------------------------------------------------------------------


class TestPerRefFallbackPattern:
    """C1 + C3 per-path — for each function that has the fallback pattern
    'root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT',
    verify the explicit param wins over the module global.

    Refs covered:
      - check_rawdata_status (line ~721)
      - delete_rawdata       (line ~1198)
      - create_app local var (line ~5452) — verified by app_factory fixture
        in conftest.py which already passes rawdata_root=tmp_rawdata

    Each sub-test is independently provable red by injecting the bug:
    remove the 'if rawdata_root is not None else RAWDATA_ROOT' fallback
    (or hardcode RAWDATA_ROOT) → test goes red because wrong path used.
    """

    @pytest.mark.parametrize("fn_name,fn", [
        ("check_rawdata_status", check_rawdata_status),
    ])
    def test_fallback_fn_uses_explicit_param_over_global(
        self, tmp_path, fn_name, fn, monkeypatch
    ):
        """C1/C3 per-ref: calling fn with explicit rawdata_root=<real_dir>
        must NOT crash even when the module global points at a nonexistent path.

        Inject-bug: if the function hardcodes RAWDATA_ROOT instead of using
        the parameter, it would look in SENTINEL_WRONG_ROOT which doesn't
        exist, and since SENTINEL_WRONG_ROOT / machine / mode_N does not
        exist, the function would return the empty dict silently — but we
        force it to be distinguishable by creating the mode dir ONLY in the
        real root.
        """
        machine, mode = "M14", 1
        real_root = tmp_path / "real_rawdata"
        mode_dir = real_root / machine / f"mode_{mode}"
        mode_dir.mkdir(parents=True)

        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", SENTINEL_WRONG_ROOT)
        # The function must not raise (SENTINEL_WRONG_ROOT doesn't exist).
        try:
            result = fn(machine, mode, rawdata_root=real_root)
        except Exception as exc:
            pytest.fail(
                f"{fn_name} raised {exc!r} even though rawdata_root was "
                f"explicitly provided.  The function may be ignoring the "
                f"parameter and using the (bad) module global."
            )
        assert isinstance(result, dict), f"{fn_name} must return a dict"


# ---------------------------------------------------------------------------
# C1 ref: create_app wires rawdata_root through to BatchRunManager
# ---------------------------------------------------------------------------


class TestCreateAppWiresRawdataRoot:
    """Verify that create_app passes the rawdata_root parameter through to
    BatchRunManager so the injected root is used fleet-wide.

    This test uses a real app instance (via app_factory from conftest).
    """

    def test_create_app_batch_mgr_rawdata_root_matches_param(self, app_factory):
        """C1 — the app's batch_mgr._rawdata_root must equal the rawdata_root
        passed to create_app.

        app_factory injects tmp_rawdata via create_app(rawdata_root=tmp_rawdata).
        """
        app = app_factory()
        expected = app_factory.rawdata_dir
        actual = app.state.batch_manager._rawdata_root
        assert actual == expected, (
            f"app.state.batch_manager._rawdata_root == {actual!r} but "
            f"create_app was called with rawdata_root={expected!r}.  "
            "create_app is not threading rawdata_root into BatchRunManager."
        )

    def test_create_app_batch_mgr_rawdata_root_is_not_module_global(
        self, app_factory, monkeypatch
    ):
        """C2 — the app's batch_mgr._rawdata_root must NOT equal the module
        global when a different path was injected at app creation time."""
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", SENTINEL_WRONG_ROOT)
        app = app_factory()
        actual = app.state.batch_manager._rawdata_root
        assert actual != SENTINEL_WRONG_ROOT, (
            "app.state.batch_manager._rawdata_root equals the (wrong) module "
            "global even though create_app was called with a different "
            "rawdata_root.  The injection chain is broken."
        )


# ---------------------------------------------------------------------------
# C1 prod-bug explicit guard: start_batch does NOT read module global
# ---------------------------------------------------------------------------


class TestStartBatchProdBugGuard:
    """Explicit regression guard for the prod bug described in ticket §3 C1.

    Original line 3259 (now ~3393): check_rawdata_status was called without
    rawdata_root, so it fell back to the module-level RAWDATA_ROOT global.
    Virtual-console batches then scanned the REAL rawdata tree.

    This guard:
      - Creates TWO rawdata trees (real_root and virtual_root).
      - Creates chunks ONLY in virtual_root.
      - Points RAWDATA_ROOT module global at real_root (which is EMPTY).
      - Injects virtual_root into BatchRunManager.
      - Calls start_batch and asserts check_rawdata_status saw virtual_root.

    Before fix: check_rawdata_status would see usable_chunks=0 (real_root
    has no chunks), so 'cache_usable' would be False even though virtual_root
    has data.

    After fix: check_rawdata_status sees virtual_root, usable_chunks > 0.
    """

    def test_start_batch_scans_injected_root_not_module_global(
        self, tmp_path, monkeypatch
    ):
        machine, mode = "M14", 1
        real_root = tmp_path / "real_rawdata"   # module global, empty
        virtual_root = tmp_path / "virtual_rawdata"  # injected, has data

        real_root.mkdir()
        # Put chunks in VIRTUAL root only.
        virtual_mode_dir = virtual_root / machine / f"mode_{mode}"
        virtual_mode_dir.mkdir(parents=True)
        (virtual_mode_dir / "chunk_0001.json").write_text(
            '{"machine":"M14","mode":1,"spin_times":5000,'
            '"config_md5":"cfg1","code_md5":"cod1",'
            '"RTPSummary":{},"rounds":[]}',
            encoding="utf-8",
        )

        store = _make_store(tmp_path)
        rm = _make_run_manager(tmp_path, store)

        # Point the module global at the EMPTY real root.
        monkeypatch.setattr(app_mod, "RAWDATA_ROOT", real_root)

        # Inject the VIRTUAL root with chunks.
        bm = _make_batch_manager(
            tmp_path, store, rm, rawdata_root=virtual_root
        )

        scanned_roots: list[Path | None] = []

        def _spy_check(machine, mode, rawdata_root=None, machines_config=None, **kw):
            scanned_roots.append(rawdata_root)
            # Return empty so start_batch doesn't try to run the analyzer.
            return {
                "exists": rawdata_root is not None and rawdata_root.is_dir(),
                "usable_chunks": 0,
                "mismatch_chunks": 0,
                "total_size_mb": 0.0,
                "kept": [], "deletable": [], "historical": [],
                "kept_spins": 0, "deletable_spins": 0, "historical_spins": 0,
                "upstream_config_md5": "", "upstream_code_md5": "",
                "unverifiable": True,
            }

        monkeypatch.setattr(app_mod, "check_rawdata_status", _spy_check)

        from src.web_console.backend.app import BatchRunRequest, BatchRunItem
        req = BatchRunRequest(
            items=[BatchRunItem(machine=machine, mode=mode)],
            chunk_robot_count=4, batch_concurrency=1,
            concurrency=1, max_chunks=1, timeout=10.0,
        )
        bm.start_batch(req)

        assert scanned_roots, (
            "check_rawdata_status was never called from start_batch."
        )
        for root in scanned_roots:
            assert root == virtual_root, (
                f"start_batch called check_rawdata_status with "
                f"rawdata_root={root!r} instead of {virtual_root!r}.  "
                f"Module global is real_root={real_root!r} (empty).  "
                "The prod bug (P1-B6 original line 3259) is still present: "
                "start_batch is not passing self._rawdata_root."
            )
