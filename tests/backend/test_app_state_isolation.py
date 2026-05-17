"""Regression tests for ticket P1-C1 — Remaining module globals + pure-function extraction.

Contract summary (from 00_ticket.md §3):

  C2 — Per-global split-path regression: for each migrated global, assert
       behavior depends on instance/request scope (AppCacheState), NOT the
       module-level global.  Inject-bug: monkeypatch the module global to a
       wrong value; confirm migrated consumer ignores it.

  C3 — No new import-time side effects in any new module introduced by the
       implementer.

  C4 — Pure function extraction: verify extracted helpers are pure.

  C5 — Multi-worker safety: per-instance AppCacheState isolates state
       across two logical workers (two AppCacheState instances).

  C6 — Subprocess-mode: verify AppCacheState globals are empty at import.

Migration pattern (per implementer's AppCacheState approach):
  The implementer introduced ``AppCacheState`` with __slots__ containing
  the 5 formerly-module-level mutable structures, and a fallback
  ``_MODULE_CACHE_STATE = AppCacheState()`` for standalone callers.
  Functions that used module globals now accept ``_cs: AppCacheState | None``
  and default to ``_MODULE_CACHE_STATE``.

  Split-path discipline (memory feedback_subprocess_import_suicide_and_module_globals.md):
    - Poison the MODULE global (``_MODULE_CACHE_STATE``) to a wrong value.
    - Pass a FRESH ``AppCacheState()`` as ``_cs``.
    - Assert the fresh instance is used, NOT the poisoned module global.

Globals under test (from 03_coupling_audit.md §4.1 + implementer's diff):
  G1  machines_summary_cache     (AppCacheState.machines_summary_cache)
  G2  rawdata_overview_cache     (AppCacheState.rawdata_overview_cache)
  G3  static_attrs_cache         (AppCacheState.static_attrs_cache)
  G4  in_use_modes + in_use_lock (AppCacheState.in_use_modes / in_use_lock)
  G5  lock_cache                 (AppCacheState.lock_cache)
  G6  _STATIC_ATTRS_MECH_KEYS    (constant tuple — verify presence)

CURRENT STATE (pre-complete-fix):
  G3/G4/G5 — migrated to AppCacheState with _cs param.
  G1/G2     — AppCacheState class has the slots, but _build_machines_summary /
              _build_rawdata_overview still reference OLD module global names
              (_MACHINES_SUMMARY_CACHE / _RAWDATA_OVERVIEW_CACHE) that no
              longer exist → NameError at runtime.  Tests for G1/G2 mark this.
  create_app — does NOT yet create or pass a per-instance AppCacheState to
              the route closures; routes call helper fns without _cs, so they
              fall back to _MODULE_CACHE_STATE (still shared across instances).

Inject-bug TDD (per memory feedback_integration_test_argv.md):
  Tests written to match the migration contract.  Where the migration is
  INCOMPLETE (G1/G2), tests catch the NameError.  Where migrated (G3/G4/G5),
  tests verify the split-path isolation actually works.
"""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import src.web_console.backend.app as app_mod
from src.web_console.backend.app import (
    AppCacheState,
    _acquire_in_use,
    _get_in_use_snapshot,
    _load_rawdata_locks,
    _load_static_attrs,
    _release_in_use,
    _save_rawdata_locks,
    _save_static_attrs,
    create_app,
)

# ---------------------------------------------------------------------------
# Shared sentinels
# ---------------------------------------------------------------------------

_SENTINEL_RESULT: dict[str, Any] = {"__sentinel__": True, "machines": {}}
"""A result that should NEVER appear when the correct instance scope is used."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_cs() -> AppCacheState:
    """Return a brand-new AppCacheState (represents a fresh 'worker instance')."""
    return AppCacheState()


def _make_minimal_app(tmp_path: Path) -> Any:
    """Create an isolated FastAPI app with its own tmp directories."""
    sd = tmp_path / "state"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "progress").mkdir(parents=True, exist_ok=True)
    rr = tmp_path / "reports"
    rr.mkdir(parents=True, exist_ok=True)
    cr = tmp_path / "cache"
    cr.mkdir(parents=True, exist_ok=True)
    rd = tmp_path / "rawdata"
    rd.mkdir(parents=True, exist_ok=True)
    mc = tmp_path / "machines.json"
    mc.write_text('{"machines":[{"machine":"M14","modes":[1]}]}', encoding="utf-8")
    az = tmp_path / "fake_analyzer.py"
    az.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    with patch("src.web_console.backend.app._terminate_pid_if_running", lambda pid: True):
        app = create_app(
            state_dir=sd,
            reports_root=rr,
            cache_root=cr,
            machines_config=mc,
            analyzer_path=az,
            rawdata_root=rd,
        )
    app._test_reports_root = rr
    app._test_rawdata_root = rd
    app._test_machines_config = mc
    return app


def _write_minimal_summary_json(path: Path) -> None:
    """Write a minimal player_impact_summary.json to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "sampling": {"total_spins": 1000, "achieved_halfwidth_pp": 0.5},
            "rtp": {"point_pct": 95.0},
            "player_impact": {
                "volatility": {},
                "hit_and_payout": {"zero_win_rate": 0.3},
                "machine_mechanics": {},
                "upstream_feature_breakdown": {"features": []},
            },
            "guideline_assessment": {
                "classification": {"volatility_class": "medium"},
                "derived_metrics": {"tail_dependency": 0.1},
            },
        }),
        encoding="utf-8",
    )


# ===========================================================================
# G1 — machines_summary_cache (AppCacheState slot)
# ===========================================================================


class TestMachinesSummaryCacheState:
    """C2 / C5 — Verify the AppCacheState migration for machines_summary_cache.

    CONTRACT:
      - AppCacheState has a .machines_summary_cache dict slot.
      - _build_machines_summary (or its migrated replacement) must use the
        per-instance cache, NOT a module-level global dict.
      - If G1 migration is incomplete, _build_machines_summary raises NameError
        (references _MACHINES_SUMMARY_CACHE which no longer exists as a module attr).
      - Two fresh AppCacheState instances must have INDEPENDENT cache dicts.
    """

    def test_app_cache_state_has_machines_summary_cache_slot(self) -> None:
        """C2 — AppCacheState must expose a machines_summary_cache attribute."""
        cs = _fresh_cs()
        assert hasattr(cs, "machines_summary_cache"), (
            "AppCacheState must have .machines_summary_cache slot. "
            "G1 migration incomplete: slot not defined."
        )
        assert isinstance(cs.machines_summary_cache, dict), (
            "AppCacheState.machines_summary_cache must be a dict."
        )

    def test_two_fresh_cache_states_have_independent_machines_summary_caches(self) -> None:
        """C5 — Two AppCacheState instances must have independent dicts.

        This is the core split-path invariant: if machines_summary_cache is
        a class-level shared dict instead of an instance attr, both instances
        would see each other's entries.
        """
        cs_a = _fresh_cs()
        cs_b = _fresh_cs()
        cs_a.machines_summary_cache["sentinel_key"] = {"fingerprint": (1, 1), "result": {}}
        assert "sentinel_key" not in cs_b.machines_summary_cache, (
            "Two AppCacheState instances share the same machines_summary_cache dict. "
            "Either it is a class attribute (not instance), or __slots__ is not correctly "
            "declaring a per-instance dict. C5 isolation broken."
        )

    def test_machines_summary_cache_is_empty_on_fresh_instance(self) -> None:
        """C5 — A new AppCacheState starts with an empty cache (no pollution)."""
        cs = _fresh_cs()
        assert len(cs.machines_summary_cache) == 0, (
            f"Fresh AppCacheState.machines_summary_cache is not empty: "
            f"{cs.machines_summary_cache!r}. "
            "Data from a previous test or module-init is polluting new instances."
        )

    def test_module_level_machines_summary_cache_does_not_exist(self) -> None:
        """C2 — After G1 migration, _MACHINES_SUMMARY_CACHE must NOT exist as
        a module-level attribute.

        Contract: the migration replaces the bare module global with
        AppCacheState.machines_summary_cache. Having BOTH would mean the
        function still uses the old one.

        If this test FAILS (attribute still exists), it means G1 migration
        was NOT completed — _build_machines_summary still reads the old global.
        If this test PASSES (attribute removed), check that _build_machines_summary
        was updated to use the _cs parameter.
        """
        has_old_global = hasattr(app_mod, "_MACHINES_SUMMARY_CACHE")
        # The migration should have REMOVED this; if it's still present,
        # _build_machines_summary likely still reads it.
        assert not has_old_global, (
            "app_mod._MACHINES_SUMMARY_CACHE still exists as a module-level attr. "
            "G1 migration is incomplete: _build_machines_summary must be updated "
            "to use AppCacheState.machines_summary_cache (via _cs param). "
            "Current state: the old global name was removed (causing NameError in "
            "_build_machines_summary), but the function body wasn't updated. "
            "This test will turn GREEN once the function is updated AND the old "
            "global removed."
        )

    def test_build_machines_summary_does_not_raise_name_error(
        self, tmp_path: Path
    ) -> None:
        """C2 — _build_machines_summary must not raise NameError.

        CURRENT BUG (pre-complete-fix): _build_machines_summary references
        _MACHINES_SUMMARY_CACHE which no longer exists as a module name after
        the AppCacheState migration → NameError at runtime.

        This test catches the exact regression.

        Inject-bug: the bug IS present in the current code. This test is RED
        until the implementer also updates the function body.
        After fix: the function uses self._cs.machines_summary_cache → GREEN.
        """
        rr = tmp_path / "reports"
        rr.mkdir()
        try:
            result = app_mod._build_machines_summary(rr)
        except NameError as e:
            pytest.fail(
                f"_build_machines_summary raised NameError: {e}\n"
                "G1 migration incomplete: AppCacheState was created and "
                "_MACHINES_SUMMARY_CACHE module global removed, but the function "
                "body still references the old name. Update _build_machines_summary "
                "to accept _cs: AppCacheState | None and use "
                "cs.machines_summary_cache instead of _MACHINES_SUMMARY_CACHE."
            )
        assert isinstance(result, dict), "_build_machines_summary must return a dict."

    def test_build_machines_summary_split_path_instance_vs_module_global(
        self, tmp_path: Path
    ) -> None:
        """C2 — Split-path regression: poisoning _MODULE_CACHE_STATE must NOT
        cause _build_machines_summary to return the poisoned result, when the
        call passes its OWN fresh _cs instance.

        CURRENT STATE: This test can only run once G1 migration is complete
        (once _build_machines_summary accepts _cs). If the function doesn't
        accept _cs yet, it is marked XFAIL with an explanatory message.

        After full G1 migration:
          - _build_machines_summary(rr, _cs=fresh_cs) uses fresh_cs.machines_summary_cache
          - Poisoning _MODULE_CACHE_STATE has no effect
          - Test turns GREEN.
        """
        # Probe whether _build_machines_summary accepts _cs.
        sig = inspect.signature(app_mod._build_machines_summary)
        if "_cs" not in sig.parameters:
            pytest.xfail(
                "_build_machines_summary does not yet accept _cs parameter. "
                "G1 migration incomplete. This test will pass after the function "
                "signature is updated to: "
                "def _build_machines_summary(reports_root, _cs=None)."
            )

        rr = tmp_path / "reports"
        rr.mkdir()
        # Add a machine only visible in fresh_cs, not in module global.
        fresh_cs = _fresh_cs()
        fresh_cs.machines_summary_cache["poison_test"] = {
            "fingerprint": (0, 0),
            "result": _SENTINEL_RESULT,
        }

        # Poison the module global.
        original_mcs = app_mod._MODULE_CACHE_STATE.machines_summary_cache.copy()
        app_mod._MODULE_CACHE_STATE.machines_summary_cache["__module_poison__"] = {
            "fingerprint": app_mod._machines_summary_fingerprint(rr),
            "result": {"__module_poison__": True, "machines": {}},
        }
        try:
            result = app_mod._build_machines_summary(rr, _cs=fresh_cs)
            # Must NOT return the module-global poison.
            assert result.get("__module_poison__") is not True, (
                "_build_machines_summary returned the module-global poison result. "
                "The _cs param is not being used to look up the cache. "
                "Ensure _build_machines_summary uses: "
                "  cs = _cs if _cs is not None else _MODULE_CACHE_STATE"
                "  entry = cs.machines_summary_cache.get(cache_key)"
            )
        finally:
            app_mod._MODULE_CACHE_STATE.machines_summary_cache.clear()
            app_mod._MODULE_CACHE_STATE.machines_summary_cache.update(original_mcs)


# ===========================================================================
# G2 — rawdata_overview_cache (AppCacheState slot)
# ===========================================================================


class TestRawdataOverviewCacheState:
    """C2 / C5 — Verify AppCacheState migration for rawdata_overview_cache.

    Same pattern as G1: AppCacheState has the slot, but _build_rawdata_overview
    still uses old variable name → NameError until function body is updated.
    """

    def test_app_cache_state_has_rawdata_overview_cache_slot(self) -> None:
        """C2 — AppCacheState must expose a rawdata_overview_cache attribute."""
        cs = _fresh_cs()
        assert hasattr(cs, "rawdata_overview_cache"), (
            "AppCacheState must have .rawdata_overview_cache slot."
        )
        assert isinstance(cs.rawdata_overview_cache, dict)

    def test_two_fresh_cache_states_have_independent_rawdata_overview_caches(self) -> None:
        """C5 — Two AppCacheState instances must have independent rawdata_overview dicts."""
        cs_a = _fresh_cs()
        cs_b = _fresh_cs()
        cs_a.rawdata_overview_cache["sentinel_key"] = {"fp": (1, 1), "retention": 0, "result": {}}
        assert "sentinel_key" not in cs_b.rawdata_overview_cache, (
            "Two AppCacheState instances share rawdata_overview_cache. "
            "Not a per-instance dict — C5 isolation broken."
        )

    def test_module_level_rawdata_overview_cache_does_not_exist(self) -> None:
        """C2 — After G2 migration, _RAWDATA_OVERVIEW_CACHE must not exist as
        a module-level attribute (must have been replaced by AppCacheState slot)."""
        has_old = hasattr(app_mod, "_RAWDATA_OVERVIEW_CACHE")
        assert not has_old, (
            "app_mod._RAWDATA_OVERVIEW_CACHE still exists as a module-level attr. "
            "G2 migration incomplete: _build_rawdata_overview must be updated "
            "to use AppCacheState.rawdata_overview_cache (via _cs param)."
        )

    def test_build_rawdata_overview_does_not_raise_name_error(
        self, tmp_path: Path
    ) -> None:
        """C2 — _build_rawdata_overview must not raise NameError.

        CURRENT BUG: _build_rawdata_overview references _RAWDATA_OVERVIEW_CACHE
        which no longer exists → NameError.

        Inject-bug: bug IS present in current code. This test is RED
        until the implementer updates the function body.
        """
        rr = tmp_path / "rawdata"
        rr.mkdir()
        mc = tmp_path / "machines.json"
        mc.write_text('{"machines":[]}', encoding="utf-8")
        try:
            result = app_mod._build_rawdata_overview(rr, mc, retention_spins=10000)
        except NameError as e:
            pytest.fail(
                f"_build_rawdata_overview raised NameError: {e}\n"
                "G2 migration incomplete: AppCacheState was created and "
                "_RAWDATA_OVERVIEW_CACHE module global removed, but the function "
                "body still references the old name. Update _build_rawdata_overview "
                "to accept _cs: AppCacheState | None and use "
                "cs.rawdata_overview_cache instead of _RAWDATA_OVERVIEW_CACHE."
            )
        assert isinstance(result, dict), "_build_rawdata_overview must return a dict."

    def test_build_rawdata_overview_split_path_instance_vs_module_global(
        self, tmp_path: Path
    ) -> None:
        """C2 — Split-path regression: poisoning _MODULE_CACHE_STATE must NOT
        cause _build_rawdata_overview to return poisoned result when _cs is fresh.

        XFAIL until _build_rawdata_overview accepts _cs parameter.
        """
        sig = inspect.signature(app_mod._build_rawdata_overview)
        if "_cs" not in sig.parameters:
            pytest.xfail(
                "_build_rawdata_overview does not yet accept _cs parameter. "
                "G2 migration incomplete."
            )

        rr = tmp_path / "rawdata"
        rr.mkdir()
        mc = tmp_path / "machines.json"
        mc.write_text('{"machines":[]}', encoding="utf-8")
        fresh_cs = _fresh_cs()

        fp = app_mod._rawdata_overview_fingerprint(rr)
        original = app_mod._MODULE_CACHE_STATE.rawdata_overview_cache.copy()
        app_mod._MODULE_CACHE_STATE.rawdata_overview_cache[str(rr)] = {
            "fp": fp,
            "retention": 10000,
            "result": {"__module_poison__": True},
        }
        try:
            result = app_mod._build_rawdata_overview(rr, mc, 10000, _cs=fresh_cs)
            assert result.get("__module_poison__") is not True, (
                "_build_rawdata_overview returned the module-global poison result. "
                "The _cs param is not being used to look up the cache."
            )
        finally:
            app_mod._MODULE_CACHE_STATE.rawdata_overview_cache.clear()
            app_mod._MODULE_CACHE_STATE.rawdata_overview_cache.update(original)


# ===========================================================================
# G3 — static_attrs_cache (AppCacheState slot, migrated via _cs param)
# ===========================================================================


class TestStaticAttrsCacheState:
    """C2 / C5 — _load_static_attrs and _save_static_attrs use AppCacheState
    via the _cs parameter pattern.

    MIGRATION STATUS: DONE.  These tests verify the migration is complete
    and correct.
    """

    def test_load_static_attrs_uses_fresh_cs_not_module_global(
        self, tmp_path: Path
    ) -> None:
        """C2 — Split-path: poison _MODULE_CACHE_STATE.static_attrs_cache with
        a sentinel; call _load_static_attrs with a fresh _cs.
        The fresh _cs must be used, NOT the poisoned module global.

        Inject-bug (inverted):
          - If _load_static_attrs ignores _cs and uses _MODULE_CACHE_STATE,
            it would return the sentinel data.
          - After correct migration, fresh_cs is consulted → sentinel not returned.
        """
        path = tmp_path / "machines_static.json"
        path.write_text(
            json.dumps({"machines": {"M77": {"features": ["jackpot"]}}}),
            encoding="utf-8",
        )

        # Poison the module-global cache state with sentinel data that
        # appears to have matching mtime=0 (so it would serve as a cache hit).
        original_data = dict(app_mod._MODULE_CACHE_STATE.static_attrs_cache)
        app_mod._MODULE_CACHE_STATE.static_attrs_cache["mtime"] = 0
        app_mod._MODULE_CACHE_STATE.static_attrs_cache["data"] = _SENTINEL_RESULT

        try:
            fresh_cs = _fresh_cs()
            # fresh_cs.static_attrs_cache = {"mtime": 0, "data": None} by default
            # Since data is None, it will RE-READ from path (not return sentinel).
            result = _load_static_attrs(path, _cs=fresh_cs)

            # Must NOT return the module-global sentinel.
            assert result.get("__sentinel__") is not True, (
                "_load_static_attrs returned the module-global sentinel. "
                "The _cs parameter is not being used — function falls back "
                "to _MODULE_CACHE_STATE even when _cs is provided. "
                "Check: cs = _cs if _cs is not None else _MODULE_CACHE_STATE"
            )
            # Must return path's real data.
            assert "M77" in result.get("machines", {}), (
                "_load_static_attrs did not return path's data (M77 machines). "
                "Either the _cs isolation broke or the fixture path was not read."
            )
        finally:
            app_mod._MODULE_CACHE_STATE.static_attrs_cache.update(original_data)

    def test_two_cs_instances_have_independent_static_attrs_caches(
        self, tmp_path: Path
    ) -> None:
        """C5 — Two AppCacheState instances must never share static_attrs_cache state.

        Scenario: Load a path using cs_a → cs_a.static_attrs_cache is populated.
        Load the SAME path using cs_b → cs_b.static_attrs_cache starts fresh,
        so it re-reads from disk.  Neither contaminates the other.
        """
        path = tmp_path / "machines_static.json"
        data = {"machines": {"M88": {"features": ["free_spin"]}}}
        path.write_text(json.dumps(data), encoding="utf-8")

        cs_a = _fresh_cs()
        cs_b = _fresh_cs()

        result_a = _load_static_attrs(path, _cs=cs_a)
        # Mutate cs_a's cache (simulate a different version being cached).
        cs_a.static_attrs_cache["data"] = {"machines": {"MUTATED": {}}}

        # cs_b must still read from disk, not inherit cs_a's state.
        result_b = _load_static_attrs(path, _cs=cs_b)
        assert "M88" in result_b.get("machines", {}), (
            "cs_b did not get M88 from disk. "
            "Expected: cs_b re-reads path (its cache is fresh). "
            "Got: cs_b may have inherited cs_a's mutated state — isolation broken."
        )
        assert "MUTATED" not in result_b.get("machines", {}), (
            "cs_b inherited cs_a's mutated cache data — not independent."
        )

    def test_save_static_attrs_updates_only_the_given_cs(
        self, tmp_path: Path
    ) -> None:
        """C5 — _save_static_attrs with cs_a must NOT update cs_b's cache."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir(parents=True, exist_ok=True)
        dir_b.mkdir(parents=True, exist_ok=True)

        path_a = dir_a / "machines_static.json"
        path_b = dir_b / "machines_static.json"
        path_b.write_text(json.dumps({"machines": {"M55": {}}}), encoding="utf-8")

        cs_a = _fresh_cs()
        cs_b = _fresh_cs()

        # Warm cs_b with path_b's data.
        _load_static_attrs(path_b, _cs=cs_b)
        assert cs_b.static_attrs_cache["data"] is not None

        # Save path_a data using cs_a — must NOT touch cs_b.
        _save_static_attrs(path_a, {"machines": {"M66": {}}}, _cs=cs_a)

        # cs_b must still have its own data.
        assert cs_b.static_attrs_cache["data"] is not None, (
            "_save_static_attrs(path_a, cs_a) wiped cs_b.static_attrs_cache.data. "
            "Not isolated — _save_static_attrs is writing to a shared structure."
        )
        assert "M66" not in (cs_b.static_attrs_cache.get("data") or {}).get("machines", {}), (
            "cs_b.static_attrs_cache.data contains M66 from cs_a's save. "
            "Instance isolation broken."
        )

    def test_load_static_attrs_defaults_to_module_cache_state(
        self, tmp_path: Path
    ) -> None:
        """C6 — When _cs is None (standalone callers), _load_static_attrs must
        use _MODULE_CACHE_STATE (backward-compat fallback).

        Inject-bug simulation: pre-populate _MODULE_CACHE_STATE.static_attrs_cache
        with data and verify it's returned (mtime match → cache hit).
        """
        path = tmp_path / "machines_static.json"

        sentinel_data = {"machines": {"M_MODULE_DEFAULT": {}},
                         "feature_distribution": {}, "mechanics_distribution": {}}

        # Write the file and get its real mtime.
        path.write_text(json.dumps(sentinel_data), encoding="utf-8")
        real_mtime = path.stat().st_mtime_ns

        original_cs_cache = dict(app_mod._MODULE_CACHE_STATE.static_attrs_cache)
        app_mod._MODULE_CACHE_STATE.static_attrs_cache["mtime"] = real_mtime
        app_mod._MODULE_CACHE_STATE.static_attrs_cache["data"] = sentinel_data

        try:
            # No _cs passed → must use _MODULE_CACHE_STATE.
            result = _load_static_attrs(path)
            assert "M_MODULE_DEFAULT" in result.get("machines", {}), (
                "_load_static_attrs(path) without _cs did NOT return the "
                "_MODULE_CACHE_STATE cached data. The default fallback to "
                "_MODULE_CACHE_STATE is broken."
            )
        finally:
            app_mod._MODULE_CACHE_STATE.static_attrs_cache.update(original_cs_cache)


# ===========================================================================
# G4 — in_use_modes + in_use_lock (AppCacheState slots, migrated)
# ===========================================================================


class TestInUseModesCacheState:
    """C2 / C5 — _acquire_in_use / _release_in_use / _get_in_use_snapshot
    use AppCacheState via _cs parameter.

    MIGRATION STATUS: DONE.  These tests verify isolation correctness.
    """

    def test_acquire_with_fresh_cs_does_not_touch_module_global(self) -> None:
        """C2 — Acquiring via a fresh _cs must NOT add to _MODULE_CACHE_STATE.

        Inject-bug: if _acquire_in_use ignores _cs and always writes to
        _MODULE_CACHE_STATE, the module global would gain the entry.
        After correct migration: only fresh_cs gains the entry.
        """
        fresh_cs = _fresh_cs()
        original_module_modes = set(app_mod._MODULE_CACHE_STATE.in_use_modes)

        _acquire_in_use("M_FRESH_CS_TEST", 77, _cs=fresh_cs)
        try:
            # fresh_cs must have the entry.
            assert ("M_FRESH_CS_TEST", 77) in fresh_cs.in_use_modes, (
                "_acquire_in_use did not add to fresh_cs.in_use_modes. "
                "The _cs parameter is not being used."
            )
            # Module global must NOT have the entry.
            assert ("M_FRESH_CS_TEST", 77) not in app_mod._MODULE_CACHE_STATE.in_use_modes, (
                "_acquire_in_use added to _MODULE_CACHE_STATE even though "
                "_cs=fresh_cs was passed. The _cs parameter is ignored. "
                "C2 split-path violation."
            )
        finally:
            fresh_cs.in_use_modes.discard(("M_FRESH_CS_TEST", 77))
            # Restore module state.
            app_mod._MODULE_CACHE_STATE.in_use_modes -= (
                app_mod._MODULE_CACHE_STATE.in_use_modes - original_module_modes
            )

    def test_release_with_fresh_cs_does_not_touch_module_global(self) -> None:
        """C2 — Releasing via a fresh _cs must NOT touch _MODULE_CACHE_STATE."""
        fresh_cs = _fresh_cs()
        # Set up: module global has an entry; fresh_cs also has it.
        _acquire_in_use("M_REL_TEST", 88, _cs=fresh_cs)
        original_module = set(app_mod._MODULE_CACHE_STATE.in_use_modes)
        app_mod._MODULE_CACHE_STATE.in_use_modes.add(("M_REL_TEST", 88))

        try:
            _release_in_use("M_REL_TEST", 88, _cs=fresh_cs)
            # fresh_cs must not have entry.
            assert ("M_REL_TEST", 88) not in fresh_cs.in_use_modes, (
                "_release_in_use did not remove from fresh_cs.in_use_modes."
            )
            # Module global MUST still have the entry (we added it there;
            # the release must not have touched the module global).
            assert ("M_REL_TEST", 88) in app_mod._MODULE_CACHE_STATE.in_use_modes, (
                "_release_in_use also removed from _MODULE_CACHE_STATE "
                "even though _cs=fresh_cs was passed. C2 split-path violation."
            )
        finally:
            app_mod._MODULE_CACHE_STATE.in_use_modes.discard(("M_REL_TEST", 88))

    def test_get_in_use_snapshot_with_fresh_cs_returns_fresh_cs_state(self) -> None:
        """C2 — _get_in_use_snapshot(_cs=fresh_cs) must return fresh_cs's set,
        not the module global's set.

        This is the canonical split-path test for G4.
        """
        fresh_cs = _fresh_cs()
        fresh_cs.in_use_modes.add(("M_SNAP_FRESH", 99))

        # Module global has DIFFERENT entries.
        original = set(app_mod._MODULE_CACHE_STATE.in_use_modes)
        app_mod._MODULE_CACHE_STATE.in_use_modes.add(("M_SNAP_MODULE", 100))

        try:
            snapshot = _get_in_use_snapshot(_cs=fresh_cs)
            assert ("M_SNAP_FRESH", 99) in snapshot, (
                "_get_in_use_snapshot did not return fresh_cs entries. "
                "The _cs parameter is not used for snapshot lookup."
            )
            assert ("M_SNAP_MODULE", 100) not in snapshot, (
                "_get_in_use_snapshot returned module global entries even "
                "when _cs=fresh_cs was passed. C2 split-path violation: "
                "function is ignoring _cs."
            )
        finally:
            fresh_cs.in_use_modes.discard(("M_SNAP_FRESH", 99))
            app_mod._MODULE_CACHE_STATE.in_use_modes.discard(("M_SNAP_MODULE", 100))

    def test_two_cs_instances_have_independent_in_use_modes(self) -> None:
        """C5 — Two AppCacheState instances must have independent in_use_modes sets."""
        cs_a = _fresh_cs()
        cs_b = _fresh_cs()
        _acquire_in_use("M_INST_A", 1, _cs=cs_a)
        try:
            assert ("M_INST_A", 1) in cs_a.in_use_modes
            assert ("M_INST_A", 1) not in cs_b.in_use_modes, (
                "cs_b.in_use_modes contains ('M_INST_A', 1) which was only "
                "acquired on cs_a. The two instances share in_use_modes — "
                "not per-instance, C5 isolation broken."
            )
        finally:
            _release_in_use("M_INST_A", 1, _cs=cs_a)

    def test_in_use_modes_thread_safety_per_instance(self) -> None:
        """C5 — Concurrent acquire/release on the SAME cs instance must be
        thread-safe.  Per-instance lock must work correctly.
        """
        cs = _fresh_cs()
        errors: list[str] = []

        def _worker(thread_id: int) -> None:
            for i in range(20):
                key = (f"M_T{thread_id}", i)
                _acquire_in_use(*key, _cs=cs)
                snapshot = _get_in_use_snapshot(_cs=cs)
                if key not in snapshot:
                    errors.append(f"T{thread_id}: {key} missing after acquire")
                _release_in_use(*key, _cs=cs)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
        # Cleanup.
        with cs.in_use_lock:
            cs.in_use_modes.clear()

        assert not errors, (
            "Thread-safety violations on per-instance lock:\n"
            + "\n".join(errors[:5])
        )

    def test_auto_cleanup_uses_per_instance_in_use_snapshot(
        self, tmp_path: Path
    ) -> None:
        """C5 — _auto_cleanup_for_space accepts _cs and passes it to
        _get_in_use_snapshot.  Entries acquired on fresh_cs must appear
        in skipped_in_use when _auto_cleanup_for_space is called with that
        same _cs.

        _auto_cleanup_for_space already accepts _cs per the implementer's diff.

        NOTE on target_free_gb: must be large (e.g. 1000 GB) so the function
        doesn't return early (initial_free >= 0 is always True for target=0).
        """
        rr = tmp_path / "rawdata"
        mc = tmp_path / "machines.json"
        mc.write_text('{"machines":[]}', encoding="utf-8")
        mode_dir = rr / "M_INUSE_TEST" / "mode_1"
        mode_dir.mkdir(parents=True)
        chunk_file = mode_dir / "chunk_0001.json"
        chunk_file.write_text(
            '{"machine":"M_INUSE_TEST","mode":1,"spin_times":50,'
            '"config_md5":"cfg","code_md5":"code","RTPSummary":{},"rounds":[]}',
            encoding="utf-8",
        )

        fresh_cs = _fresh_cs()
        # Acquire on fresh_cs.
        _acquire_in_use("M_INUSE_TEST", 1, _cs=fresh_cs)
        try:
            result = app_mod._auto_cleanup_for_space(
                rawdata_root=rr,
                machines_config=mc,
                retention=5,
                target_free_gb=1000.0,  # large → candidate scan runs
                low_water_gb=None,
                _cs=fresh_cs,
            )
            skipped = result.get("skipped_in_use", [])
            assert "M_INUSE_TEST|1" in skipped, (
                "M_INUSE_TEST|1 acquired in fresh_cs was not in skipped_in_use. "
                "_auto_cleanup_for_space must pass _cs to _get_in_use_snapshot. "
                f"Got skipped_in_use={skipped!r}."
            )
        finally:
            _release_in_use("M_INUSE_TEST", 1, _cs=fresh_cs)


# ===========================================================================
# G5 — lock_cache (AppCacheState slot, migrated via _cs param)
# ===========================================================================


class TestLockCacheCacheState:
    """C2 / C5 — _load_rawdata_locks and _save_rawdata_locks use AppCacheState
    via _cs parameter.

    MIGRATION STATUS: DONE.  These tests verify isolation correctness.
    """

    def test_load_rawdata_locks_with_fresh_cs_ignores_module_global_cache(
        self, tmp_path: Path
    ) -> None:
        """C2 — Split-path: pre-populate _MODULE_CACHE_STATE.lock_cache with
        M_MODULE data; call _load_rawdata_locks with a fresh _cs.
        The fresh _cs must re-read from disk, NOT return the module-global data.

        Inject-bug: if _cs is ignored, the module global cache hit fires and
        returns M_MODULE data for a file that doesn't exist in the module cache.
        """
        path = tmp_path / "rawdata_locks.json"
        real_data = {"locked": ["M_FRESH_LOCK|3"], "updated_at": "2026-01-01"}
        path.write_text(json.dumps(real_data), encoding="utf-8")

        # Poison module global with M_MODULE data at mtime=0.
        original_lc = dict(app_mod._MODULE_CACHE_STATE.lock_cache)
        app_mod._MODULE_CACHE_STATE.lock_cache["mtime"] = 0
        app_mod._MODULE_CACHE_STATE.lock_cache["data"] = {("M_MODULE_LOCK", 99)}

        try:
            fresh_cs = _fresh_cs()
            # fresh_cs.lock_cache = {"mtime": 0, "data": None}
            # data is None → must re-read from disk.
            result = _load_rawdata_locks(path, _cs=fresh_cs)

            assert ("M_FRESH_LOCK", 3) in result, (
                "fresh_cs did not load M_FRESH_LOCK|3 from disk. "
                "_load_rawdata_locks may have returned the module-global cache "
                "instead of re-reading."
            )
            assert ("M_MODULE_LOCK", 99) not in result, (
                "fresh_cs returned M_MODULE_LOCK|99 from the module global. "
                "The _cs parameter is being ignored — C2 split-path violation."
            )
        finally:
            app_mod._MODULE_CACHE_STATE.lock_cache.update(original_lc)

    def test_two_cs_instances_have_independent_lock_caches(
        self, tmp_path: Path
    ) -> None:
        """C5 — Two AppCacheState instances must have independent lock_caches."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir(parents=True, exist_ok=True)
        dir_b.mkdir(parents=True, exist_ok=True)

        path_a = dir_a / "rawdata_locks.json"
        path_b = dir_b / "rawdata_locks.json"

        locks_a = {("M11", 1)}
        locks_b = {("M22", 2)}

        cs_a = _fresh_cs()
        cs_b = _fresh_cs()

        _save_rawdata_locks(path_a, locks_a, _cs=cs_a)
        _save_rawdata_locks(path_b, locks_b, _cs=cs_b)

        loaded_a = _load_rawdata_locks(path_a, _cs=cs_a)
        loaded_b = _load_rawdata_locks(path_b, _cs=cs_b)

        assert ("M11", 1) in loaded_a, "cs_a must have M11|1"
        assert ("M22", 2) in loaded_b, "cs_b must have M22|2"
        assert ("M22", 2) not in loaded_a, (
            "cs_a contains M22|2 from cs_b — lock_cache not isolated."
        )
        assert ("M11", 1) not in loaded_b, (
            "cs_b contains M11|1 from cs_a — lock_cache not isolated."
        )

    def test_save_rawdata_locks_updates_only_given_cs(
        self, tmp_path: Path
    ) -> None:
        """C5 — _save_rawdata_locks(path_a, ..., _cs=cs_a) must NOT update cs_b."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir(parents=True, exist_ok=True)
        dir_b.mkdir(parents=True, exist_ok=True)

        path_a = dir_a / "rawdata_locks.json"
        path_b = dir_b / "rawdata_locks.json"

        cs_a = _fresh_cs()
        cs_b = _fresh_cs()

        # Warm cs_b cache.
        _save_rawdata_locks(path_b, {("M55", 5)}, _cs=cs_b)
        assert cs_b.lock_cache["data"] is not None, "fixture: cs_b must be warmed"

        # Save to path_a with cs_a.
        _save_rawdata_locks(path_a, {("M66", 6)}, _cs=cs_a)

        # cs_b must be untouched.
        assert ("M55", 5) in (cs_b.lock_cache.get("data") or set()), (
            "_save_rawdata_locks(path_a, cs_a) wiped or replaced cs_b.lock_cache.data. "
            "Not isolated — writes to cs_a contaminate cs_b."
        )
        assert ("M66", 6) not in (cs_b.lock_cache.get("data") or set()), (
            "cs_b.lock_cache.data now contains M66|6 from cs_a's save. "
            "Not isolated."
        )

    def test_load_rawdata_locks_defaults_to_module_cache_state(
        self, tmp_path: Path
    ) -> None:
        """C6 — When _cs=None (standalone callers), _load_rawdata_locks must use
        _MODULE_CACHE_STATE (backward-compat fallback).
        """
        path = tmp_path / "rawdata_locks.json"
        locks = {("M_MODULE_DEFAULT_LOCK", 42)}
        _save_rawdata_locks(path, locks)  # no _cs → uses module global

        result = _load_rawdata_locks(path)  # no _cs → uses module global
        assert ("M_MODULE_DEFAULT_LOCK", 42) in result, (
            "_load_rawdata_locks(path) without _cs should use _MODULE_CACHE_STATE "
            "as fallback. The module-saved lock was not returned."
        )

        # Cleanup module state.
        app_mod._MODULE_CACHE_STATE.lock_cache["data"] = None
        app_mod._MODULE_CACHE_STATE.lock_cache["mtime"] = 0


# ===========================================================================
# G6 — _STATIC_ATTRS_MECH_KEYS presence + correctness
# ===========================================================================


class TestStaticAttrsMechKeys:
    """C2 — _STATIC_ATTRS_MECH_KEYS is a constant tuple (out-of-scope per §4).
    Tests verify: exists, correct values, used by _extract_mechanics_from_summary.
    """

    def test_static_attrs_mech_keys_exists(self) -> None:
        """_STATIC_ATTRS_MECH_KEYS must still exist as module-level constant."""
        assert hasattr(app_mod, "_STATIC_ATTRS_MECH_KEYS"), (
            "_STATIC_ATTRS_MECH_KEYS was deleted from app_mod. "
            "Per §4 out-of-scope: it is a constant — leave alone."
        )

    def test_static_attrs_mech_keys_contains_expected_values(self) -> None:
        """_STATIC_ATTRS_MECH_KEYS must contain the 6 expected mechanics keys."""
        keys = app_mod._STATIC_ATTRS_MECH_KEYS
        expected = {
            "lock_lines", "lock_symbols", "lock_reels",
            "jackpot", "free_spin", "dollar_pick",
        }
        for k in expected:
            assert k in keys, (
                f"Expected mechanics key '{k}' missing from _STATIC_ATTRS_MECH_KEYS. "
                f"Got: {keys!r}"
            )

    def test_extract_mechanics_from_summary_uses_mech_keys_constant(self) -> None:
        """_extract_mechanics_from_summary must produce a subset of MECH_KEYS."""
        summary = {
            "player_impact": {
                "machine_mechanics": {
                    "jackpot": {"applicable": True},
                    "free_spin": {"applicable": False},
                    "lock_lines": {"applicable": True},
                    "unknown_key": {"applicable": True},  # not in MECH_KEYS
                }
            }
        }
        result = app_mod._extract_mechanics_from_summary(summary)
        assert "jackpot" in result, "jackpot applicable=True must be extracted"
        assert "lock_lines" in result, "lock_lines applicable=True must be extracted"
        assert "free_spin" not in result, "free_spin applicable=False must NOT be extracted"
        assert "unknown_key" not in result, (
            "'unknown_key' not in _STATIC_ATTRS_MECH_KEYS must not appear in result. "
            "_extract_mechanics_from_summary is not using the constant as filter."
        )


# ===========================================================================
# C3 — AppCacheState structure: no import-time side effects
# ===========================================================================


class TestAppCacheStateStructure:
    """C3 — AppCacheState must not trigger side effects at instantiation time.

    The class is instantiated once at module level (_MODULE_CACHE_STATE) and
    once per create_app() call.  Both must be safe to call without file I/O,
    subprocess spawning, or stdout output.
    """

    def test_app_cache_state_instantiation_has_no_side_effects(
        self, tmp_path: Path
    ) -> None:
        """C3 — AppCacheState() must be cheap to instantiate (no I/O)."""
        before_files = set(tmp_path.rglob("*"))
        cs = AppCacheState()
        after_files = set(tmp_path.rglob("*"))
        assert before_files == after_files, (
            "AppCacheState() created files — it has I/O side effects at init time."
        )
        assert isinstance(cs, AppCacheState)

    def test_no_new_module_top_app_build_patterns_in_backend_modules(self) -> None:
        """C3 — New modules added by P1-C1 must not have module-top build_* patterns.

        Pre-existing entry-point files (main.py, e2e_launch.py) are excluded
        because they legitimately call create_app() at module top as that IS
        their purpose (they are the process entry points, not library modules).
        Only modules newly introduced by this ticket are scanned.
        """
        import re
        patterns = [
            re.compile(r"^app\s*=\s*\w", re.MULTILINE),
            re.compile(r"^server\s*=\s*\w", re.MULTILINE),
            re.compile(r"^[A-Z_]+\s*=\s*build_\w", re.MULTILINE),
            re.compile(r"^[A-Z_]+\s*=\s*create_\w", re.MULTILINE),
        ]
        # Pre-existing entry-point files: legitimately have module-top app=.
        # These existed before P1-C1 and are not part of this ticket.
        pre_existing_entrypoints = {
            "app.py",
            "main.py",
            "e2e_launch.py",
        }
        backend_dir = Path("src/web_console/backend")
        if not backend_dir.is_dir():
            pytest.skip("src/web_console/backend not found")

        violations: list[str] = []
        for py_file in sorted(backend_dir.glob("*.py")):
            if py_file.name in pre_existing_entrypoints:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except OSError:
                continue
            for pat in patterns:
                m = pat.search(source)
                if m:
                    violations.append(f"{py_file}: {m.group()!r}")

        assert not violations, (
            "New modules (not in pre-existing entrypoints list) contain "
            "import-time side-effect patterns:\n"
            + "\n".join(violations)
            + "\nPer brief §3 C3: no new import-time side effects."
        )

    def test_module_cache_state_slots_match_expected(self) -> None:
        """C3 — AppCacheState.__slots__ must match the 5 migrated globals.

        If a slot is missing, one of the globals wasn't included in the migration.
        """
        cs = AppCacheState()
        required_attrs = {
            "machines_summary_cache",
            "rawdata_overview_cache",
            "static_attrs_cache",
            "lock_cache",
            "in_use_modes",
            "in_use_lock",
        }
        for attr in required_attrs:
            assert hasattr(cs, attr), (
                f"AppCacheState is missing slot '{attr}'. "
                "The migration plan in 02_implementation.md lists 5 globals; "
                "all must appear as AppCacheState slots."
            )


# ===========================================================================
# C5 — Multi-worker create_app() isolation
# ===========================================================================


class TestMultiWorkerCreateAppIsolation:
    """C5 — Two create_app() instances must use independent AppCacheState objects
    so one instance's cache activity does not affect the other.

    CURRENT STATE: create_app does not yet instantiate and wire a per-app
    AppCacheState. The route closures call _build_machines_summary(rr) etc.
    without _cs, so they fall through to _MODULE_CACHE_STATE (shared).
    Tests verify:
      (a) Whether create_app wires an AppCacheState yet (structural check).
      (b) The isolation contract that MUST hold after full migration.
    """

    def test_create_app_exposes_cache_state_on_app_state(
        self, tmp_path: Path
    ) -> None:
        """C5 — After full migration, create_app() must expose an AppCacheState
        on app.state.cache_state so routes and tests can access the per-instance cache.

        EXPECTED BEFORE FIX: FAIL (app.state does not have cache_state).
        EXPECTED AFTER FIX:  PASS.

        This is the structural test that drives the implementer to wire
        AppCacheState into create_app.
        """
        app = _make_minimal_app(tmp_path)
        assert hasattr(app.state, "cache_state"), (
            "app.state does not have .cache_state attribute. "
            "create_app() must instantiate AppCacheState() and attach it to "
            "app.state.cache_state so routes use per-instance cache. "
            "Without this, all routes share _MODULE_CACHE_STATE (module global). "
            "This test is RED until create_app is updated."
        )
        assert isinstance(app.state.cache_state, AppCacheState), (
            f"app.state.cache_state is {type(app.state.cache_state).__name__}, "
            "expected AppCacheState."
        )

    def test_two_create_app_instances_have_different_cache_state_objects(
        self, tmp_path: Path
    ) -> None:
        """C5 — Two create_app() calls must produce TWO distinct AppCacheState
        objects (not sharing the same instance).

        EXPECTED BEFORE FIX: FAIL (or AttributeError on cache_state).
        EXPECTED AFTER FIX:  PASS.
        """
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"

        app_a = _make_minimal_app(dir_a)
        app_b = _make_minimal_app(dir_b)

        if not hasattr(app_a.state, "cache_state"):
            pytest.xfail(
                "create_app does not yet expose cache_state on app.state. "
                "This test will pass once create_app is updated."
            )

        cs_a = app_a.state.cache_state
        cs_b = app_b.state.cache_state

        assert cs_a is not cs_b, (
            "Two create_app() calls returned the SAME AppCacheState instance. "
            "Each call must instantiate a NEW AppCacheState(). "
            "Otherwise all workers share mutable cache state."
        )


# ===========================================================================
# C6 — Subprocess-mode import smoke
# ===========================================================================


class TestSubprocessImportSmoke:
    """C6 — Spawn a subprocess and verify app.py import + AppCacheState
    instantiation produce no observable side effects.
    """

    def test_import_app_as_subprocess_produces_no_unexpected_output(self) -> None:
        """C6 — Import app.py in a subprocess; only 'IMPORT_OK' expected."""
        cmd = [
            sys.executable, "-c",
            (
                "import sys; sys.path.insert(0, '.');"
                "import src.web_console.backend.app;"
                "print('IMPORT_OK')"
            ),
        ]
        cwd = str(Path(__file__).parent.parent.parent)
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, cwd=cwd,
        )
        assert result.returncode == 0, (
            f"Importing app.py in subprocess exited {result.returncode}.\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "IMPORT_OK" in result.stdout
        extra = result.stdout.replace("IMPORT_OK", "").strip()
        assert not extra, (
            f"Import-time side effect detected: extra stdout:\n{extra!r}"
        )

    def test_app_cache_state_instantiation_in_subprocess(self) -> None:
        """C6 — AppCacheState() must be instantiable in subprocess with no errors.

        Verifies the _MODULE_CACHE_STATE singleton is inert: no threads, no I/O.
        """
        cmd = [
            sys.executable, "-c",
            "\n".join([
                "import sys; sys.path.insert(0, '.')",
                "from src.web_console.backend.app import AppCacheState, _MODULE_CACHE_STATE",
                "cs = AppCacheState()",
                "assert isinstance(cs.machines_summary_cache, dict)",
                "assert isinstance(cs.rawdata_overview_cache, dict)",
                "assert isinstance(cs.in_use_modes, set)",
                "assert len(cs.machines_summary_cache) == 0",
                "assert len(cs.rawdata_overview_cache) == 0",
                "assert len(cs.in_use_modes) == 0",
                # Module singleton must also be empty.
                "assert len(_MODULE_CACHE_STATE.machines_summary_cache) == 0",
                "assert len(_MODULE_CACHE_STATE.rawdata_overview_cache) == 0",
                "assert len(_MODULE_CACHE_STATE.in_use_modes) == 0",
                "print('CS_IMPORT_OK')",
            ]),
        ]
        cwd = str(Path(__file__).parent.parent.parent)
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, cwd=cwd,
        )
        assert result.returncode == 0, (
            f"AppCacheState subprocess smoke failed (exit {result.returncode}).\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert "CS_IMPORT_OK" in result.stdout, (
            f"Expected 'CS_IMPORT_OK', got: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )


# ===========================================================================
# C4 — Pure function verification
# ===========================================================================


class TestPureFunctionExtraction:
    """C4 — Verify that pure helper functions have no side effects.

    Per brief §3 C4: if the implementer deferred extraction, these tests
    still validate purity of the key computation helpers.
    """

    def test_extract_mechanics_from_summary_is_pure(self, tmp_path: Path) -> None:
        """C4 — _extract_mechanics_from_summary: same input → same output, no files."""
        summary = {
            "player_impact": {
                "machine_mechanics": {
                    "jackpot": {"applicable": True},
                    "lock_lines": {"applicable": True},
                    "free_spin": {"applicable": False},
                }
            }
        }
        before = set(tmp_path.rglob("*"))
        r1 = app_mod._extract_mechanics_from_summary(summary)
        r2 = app_mod._extract_mechanics_from_summary(summary)
        after = set(tmp_path.rglob("*"))

        assert r1 == r2, "Not deterministic: two identical calls returned different results."
        assert before == after, "Created files — not pure."

    def test_extract_features_from_summary_is_pure(self, tmp_path: Path) -> None:
        """C4 — _extract_features_from_summary: pure."""
        summary = {
            "player_impact": {
                "upstream_feature_breakdown": {
                    "features": [
                        {"feature_name": "FreeSpin", "feature_base_name": "FreeSpin"},
                        {"feature_name": "Jackpot", "feature_base_name": None},
                    ]
                }
            }
        }
        before = set(tmp_path.rglob("*"))
        r1 = app_mod._extract_features_from_summary(summary)
        r2 = app_mod._extract_features_from_summary(summary)
        after = set(tmp_path.rglob("*"))

        assert r1 == r2, "Not deterministic."
        assert "FreeSpin" in r1
        assert "Jackpot" in r1
        assert before == after, "Created files — not pure."

    def test_machines_summary_fingerprint_is_pure(self, tmp_path: Path) -> None:
        """C4 — _machines_summary_fingerprint: deterministic, nonexistent→(0,0)."""
        rr = tmp_path / "reports"
        rr.mkdir()
        fp1 = app_mod._machines_summary_fingerprint(rr)
        fp2 = app_mod._machines_summary_fingerprint(rr)
        assert fp1 == fp2
        assert app_mod._machines_summary_fingerprint(rr / "nope") == (0, 0)

    def test_rawdata_overview_fingerprint_is_pure(self, tmp_path: Path) -> None:
        """C4 — _rawdata_overview_fingerprint: deterministic, nonexistent→(0,0)."""
        rd = tmp_path / "rawdata"
        rd.mkdir()
        fp1 = app_mod._rawdata_overview_fingerprint(rd)
        fp2 = app_mod._rawdata_overview_fingerprint(rd)
        assert fp1 == fp2
        assert app_mod._rawdata_overview_fingerprint(rd / "nope") == (0, 0)
