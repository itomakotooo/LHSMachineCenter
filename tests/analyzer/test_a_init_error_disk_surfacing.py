"""Disk-surfacing contract tests for R1 Phase 3 Cluster A — analyzer_init_error.

Verifies that BOTH hard-error paths (Region 1: topo-sort; Region 2: DECLARED_DEPS)
write ``summary["analyzer_init_error"]`` to ``player_impact_summary.json`` on disk
BEFORE ``SystemExit(1)`` fires.  Pre-fix, both paths exited before
``write_summary_json`` ran, leaving the backend with rc=1 and no JSON diagnostic.

Design decisions
----------------
- Both tests run IN-PROCESS (monkeypatch on ``feature_registry`` seam).
  Region 1 inject: monkeypatch ``get_features_for_machine`` to return a cyclic pair
    so topo-sort raises ``PluginCyclicDependencyError`` without touching plugin files.
  Region 2 inject: monkeypatch ``get_features_for_machine`` to return a plugin with
    ``DECLARED_DEPS = ("nonexistent_stash_key_xyz",)`` + a real prefix plugin that
    emits first, demonstrating partial-state preservation.
- Both tests call PIA's ``main()`` with mocked ``sys.argv`` and catch
  ``SystemExit`` (PIA raises it on error paths).  Output dir is a
  ``tempfile.TemporaryDirectory`` so the JSON lands on real disk.
- Per ``feedback_subprocess_import_suicide_and_module_globals.md``: we patch
  ``feature_registry.get_features_for_machine`` (the module-level function the
  ``from ... import`` inside ``main()`` binds to at call time) so no import
  side-effects occur.
- Per ``feedback_no_proactive_fetch.md``: only M14 mode_1 cached chunks are used.

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
------------------------------------------------------------------
Region 1 inject-bug:
  Neuter ``_safe_write_summary_json`` so its body is ``pass`` (simulating the
  pre-fix state where JSON was never written on the error path).
  Expected: ``player_impact_summary.json`` does NOT exist on disk when rc=1.
  Test ``test_a_region1_topo_cycle_disk_surfacing`` turns RED.
  Restore -> GREEN.

Region 2 inject-bug (coverage is IMPLICIT — via assertion 3, not a dedicated
inject method in this test body):
  The DECLARED_DEPS guard in PIA's emit loop is ``if _dep_key not in summary``.
  If that guard is removed/bypassed in production, _BadDepPlugin.emit() runs and
  no analyzer_init_error is ever written. Assertion 3 of
  ``test_a_region2_declared_dep_miss_disk_surfacing``
  (``"analyzer_init_error" in summary``) is the tripwire that then turns the test
  RED. To exercise manually: comment out the Region 2 guard in
  player_impact_analyzer.py -> this test RED -> restore -> GREEN.
  (The protection is real but implicit; there is intentionally no separate
  "monkeypatch the check to a no-op" mechanism inside the test — assertion 3
  carries the regression coverage.)

Memory files cited
------------------
- memory/feedback_no_silent_swallow.md — raison d'etre for Cluster A
- memory/feedback_enumerate_safety_paths.md — inject-bug per region mandatory
- memory/feedback_subprocess_import_suicide_and_module_globals.md — in-process
  inject via monkeypatch on registry, not module re-import
- memory/feedback_perf_claim_needs_e2e_event_stream.md — real disk I/O verified,
  not mocked
- memory/feedback_capture_drift.md — structured error_type + region fields
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA_PATH = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_M14_CACHE = _REPO_ROOT / "rawdata" / "M14" / "mode_1"

# ---------------------------------------------------------------------------
# Mock AnalyzerFeature stubs for injection (no import of real plugin files)
# ---------------------------------------------------------------------------

class _MinimalFeatureBase:
    """Minimal AnalyzerFeature-compatible stub.

    Subclasses only need FEATURE_ID / REQUIRES / DECLARED_DEPS / RTP_CONTRIBUTION.
    extract/reduce/emit are stubs so PIA's emit loop can call them.
    """
    FEATURE_ID: str = ""
    SCHEMA_KEYS: tuple = ()
    SCHEMA_VERSION: int = 1
    REQUIRES: tuple = ()
    DECLARED_DEPS: tuple = ()
    RTP_CONTRIBUTION: bool = False
    REGISTERED_FALLBACK_RULES: dict = {}

    def extract(self, parse_state, chunk_dict) -> dict:
        return {}

    def reduce(self, prev_acc, this_acc) -> dict:
        return {}

    def emit(self, final_acc: Any, summary: dict, ctx: Any) -> None:
        # Write a sentinel key so Region 2 test can assert partial-emit preservation
        summary.setdefault("player_impact", {})
        summary["player_impact"][f"_{self.FEATURE_ID}_ran"] = True


# ---------------------------------------------------------------------------
# Skip guard: tests require M14 mode_1 cached chunks
# ---------------------------------------------------------------------------

def _m14_cache_available() -> bool:
    return _M14_CACHE.exists() and bool(list(_M14_CACHE.glob("chunk_*.json")))


_SKIP_NO_M14 = pytest.mark.skipif(
    not _m14_cache_available(),
    reason=f"M14 mode_1 cached chunks not found at {_M14_CACHE}",
)


# ---------------------------------------------------------------------------
# Helper: build the argv list for PIA --from-cache against M14
# ---------------------------------------------------------------------------

def _pia_argv(output_dir: str) -> list[str]:
    return [
        str(_PIA_PATH),
        "--machine", "M14",
        "--rtp-mode", "1",
        "--from-cache", str(_M14_CACHE),
        "--output-dir", output_dir,
        "--bet", "1000",
    ]


# ---------------------------------------------------------------------------
# Test 1 — Region 1: topo-sort cycle → JSON exists on disk with region=1
# ---------------------------------------------------------------------------

@_SKIP_NO_M14
class TestRegion1TopoCycleDiskSurfacing:
    """Region 1: topo-sort cyclic dep error writes player_impact_summary.json before SystemExit(1).

    Injection mechanism:
        monkeypatch ``fresh_slotlab.analyzer.feature_registry.get_features_for_machine``
        to return a 2-plugin cyclic pair (A REQUIRES B, B REQUIRES A).
        Topo-sort raises PluginCyclicDependencyError; Region 1 handler writes JSON.

    Assertions:
        1. SystemExit(1) raised (rc=1 contract).
        2. player_impact_summary.json EXISTS in output_dir.
        3. JSON top-level contains "analyzer_init_error".
        4. analyzer_init_error["error_type"] == "PluginCyclicDependencyError".
        5. analyzer_init_error["region"] == 1.
    """

    def test_a_region1_topo_cycle_disk_surfacing(self, monkeypatch):
        """Cyclic plugin pair → JSON written with analyzer_init_error region=1 before exit."""
        import fresh_slotlab.player_impact_analyzer as _pia_mod
        import fresh_slotlab.analyzer.feature_registry as _registry_mod

        # Inject: cyclic pair A→B, B→A
        class _CycleA(_MinimalFeatureBase):
            FEATURE_ID = "test_cycle_a"
            REQUIRES = ("test_cycle_b",)

        class _CycleB(_MinimalFeatureBase):
            FEATURE_ID = "test_cycle_b"
            REQUIRES = ("test_cycle_a",)

        _cyclic_pair = [_CycleA(), _CycleB()]

        # Monkeypatch get_features_for_machine at module level so the
        # `from fresh_slotlab.analyzer.feature_registry import get_features_for_machine`
        # inside main() picks up our override.
        monkeypatch.setattr(
            _registry_mod,
            "get_features_for_machine",
            lambda machine_id, manifest=None: _cyclic_pair,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(sys, "argv", _pia_argv(tmpdir))

            with pytest.raises(SystemExit) as exc_info:
                _pia_mod.main()

            # Assertion 1: rc=1
            assert exc_info.value.code == 1, (
                f"Expected SystemExit(1) from Region 1 topo-cycle handler, "
                f"got SystemExit({exc_info.value.code!r})"
            )

            summary_path = Path(tmpdir) / "player_impact_summary.json"

            # Assertion 2: JSON exists on disk
            assert summary_path.exists(), (
                f"player_impact_summary.json NOT FOUND at {summary_path}. "
                "Region 1 handler must call _safe_write_summary_json before raise SystemExit(1). "
                "Pre-fix state: JSON was never written on the error path."
            )

            summary = json.loads(summary_path.read_bytes())

            # Assertion 3: top-level key present
            assert "analyzer_init_error" in summary, (
                f"'analyzer_init_error' key absent from summary. "
                f"Top-level keys: {list(summary.keys())}"
            )

            err = summary["analyzer_init_error"]

            # Assertion 4: error_type
            assert err["error_type"] == "PluginCyclicDependencyError", (
                f"Expected error_type='PluginCyclicDependencyError', got {err['error_type']!r}"
            )

            # Assertion 5: region=1
            assert err["region"] == 1, (
                f"Expected region=1 (pre-emit topo-sort error), got region={err['region']!r}"
            )


# ---------------------------------------------------------------------------
# Test 2 — Region 2: DECLARED_DEPS miss → JSON exists on disk with region=2 + partial-emit
# ---------------------------------------------------------------------------

@_SKIP_NO_M14
class TestRegion2DeclaredDepMissDiskSurfacing:
    """Region 2: DECLARED_DEPS missing key writes player_impact_summary.json before SystemExit(1).

    Injection mechanism (per SQ-2 coordinator decision):
        monkeypatch ``fresh_slotlab.analyzer.feature_registry.get_features_for_machine``
        to return [_EarlyPlugin, _BadDepPlugin] where:
          - _EarlyPlugin has REQUIRES=(), DECLARED_DEPS=(), emits a sentinel key first.
          - _BadDepPlugin has REQUIRES=(), DECLARED_DEPS=("nonexistent_stash_key_xyz",)
            so Region 2 fires AFTER _EarlyPlugin has already emitted (partial-emit).
        Topo-sort succeeds (no REQUIRES cycle). Region 2 fires inside the emit loop.

    Assertions:
        1. SystemExit(1) raised (rc=1 contract).
        2. player_impact_summary.json EXISTS in output_dir.
        3. JSON top-level contains "analyzer_init_error".
        4. analyzer_init_error["error_type"] == "PluginDeclaredDepMissingError".
        5. analyzer_init_error["region"] == 2.
        6. analyzer_init_error["affected_plugin"] == "test_bad_dep_plugin".
        7. At least one OTHER plugin's output key IS present in the JSON
           (validates partial-emit "keep partial + annotate" decision — if impl
           clears all plugin output before writing error, this turns RED).
    """

    def test_a_region2_declared_dep_miss_disk_surfacing(self, monkeypatch):
        """DECLARED_DEPS missing key → JSON written with region=2 + partial-emit preserved."""
        import fresh_slotlab.player_impact_analyzer as _pia_mod
        import fresh_slotlab.analyzer.feature_registry as _registry_mod

        # _EarlyPlugin: runs first (no REQUIRES, no DECLARED_DEPS), emits a sentinel
        class _EarlyPlugin(_MinimalFeatureBase):
            FEATURE_ID = "test_early_plugin"
            REQUIRES = ()
            DECLARED_DEPS = ()

            def emit(self, final_acc: Any, summary: dict, ctx: Any) -> None:
                summary.setdefault("player_impact", {})
                summary["player_impact"]["test_early_plugin_output"] = {"ran": True}

        # _BadDepPlugin: runs second, declares a dep key that will never exist
        class _BadDepPlugin(_MinimalFeatureBase):
            FEATURE_ID = "test_bad_dep_plugin"
            REQUIRES = ()
            DECLARED_DEPS = ("nonexistent_stash_key_xyz",)

            def emit(self, final_acc: Any, summary: dict, ctx: Any) -> None:
                # Should never be reached — Region 2 fires before emit() is called
                summary["player_impact"]["bad_dep_ran"] = True

        # Topo-sort order: lexicographic by FEATURE_ID (test_bad_dep_plugin < test_early_plugin
        # alphabetically) BUT we need _EarlyPlugin to run FIRST so partial-emit is demonstrated.
        # To guarantee ordering: give _EarlyPlugin a FEATURE_ID that sorts BEFORE _BadDepPlugin.
        # "test_aaa_early" < "test_bad_dep_plugin" lexicographically.
        class _EarlyPluginOrdered(_EarlyPlugin):
            FEATURE_ID = "test_aaa_early_plugin"

            def emit(self, final_acc: Any, summary: dict, ctx: Any) -> None:
                summary.setdefault("player_impact", {})
                # Write sentinel under THIS plugin's FEATURE_ID so assertion 7 can find it
                summary["player_impact"]["test_aaa_early_plugin_output"] = {"ran": True}

        _feature_list = [_EarlyPluginOrdered(), _BadDepPlugin()]

        monkeypatch.setattr(
            _registry_mod,
            "get_features_for_machine",
            lambda machine_id, manifest=None: _feature_list,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(sys, "argv", _pia_argv(tmpdir))

            with pytest.raises(SystemExit) as exc_info:
                _pia_mod.main()

            # Assertion 1: rc=1
            assert exc_info.value.code == 1, (
                f"Expected SystemExit(1) from Region 2 DECLARED_DEPS handler, "
                f"got SystemExit({exc_info.value.code!r})"
            )

            summary_path = Path(tmpdir) / "player_impact_summary.json"

            # Assertion 2: JSON exists on disk
            assert summary_path.exists(), (
                f"player_impact_summary.json NOT FOUND at {summary_path}. "
                "Region 2 handler must call _safe_write_summary_json before raise SystemExit(1). "
                "Pre-fix state: RuntimeError propagated uncaught, JSON never written."
            )

            summary = json.loads(summary_path.read_bytes())

            # Assertion 3: top-level key present
            assert "analyzer_init_error" in summary, (
                f"'analyzer_init_error' key absent from summary. "
                f"Top-level keys: {list(summary.keys())}"
            )

            err = summary["analyzer_init_error"]

            # Assertion 4: error_type
            assert err["error_type"] == "PluginDeclaredDepMissingError", (
                f"Expected error_type='PluginDeclaredDepMissingError', got {err['error_type']!r}"
            )

            # Assertion 5: region=2
            assert err["region"] == 2, (
                f"Expected region=2 (emit-loop DECLARED_DEPS error), got region={err['region']!r}"
            )

            # Assertion 6: affected_plugin identifies the failing plugin
            assert err["affected_plugin"] == "test_bad_dep_plugin", (
                f"Expected affected_plugin='test_bad_dep_plugin', "
                f"got {err['affected_plugin']!r}"
            )

            # Assertion 7: at least one OTHER plugin's output key IS present
            # (validates "keep partial + annotate" decision — partial-emit preserved)
            # _EarlyPluginOrdered.emit() writes player_impact["test_aaa_early_plugin_output"]
            player_impact = summary.get("player_impact", {})
            assert "test_aaa_early_plugin_output" in player_impact, (
                f"Partial-emit output from _EarlyPluginOrdered NOT present in summary. "
                f"player_impact keys: {list(player_impact.keys())}. "
                "Region 2 must preserve partial plugin output from plugins that emitted "
                "BEFORE the failing plugin (option-a 'keep partial + annotate' contract). "
                "If this assertion is RED, the impl incorrectly cleared all plugin output "
                "before writing the error (option-b behavior — rejected in arch-v2 §4.3)."
            )
