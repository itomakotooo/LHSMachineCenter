"""R2 Phase 2 C-4: DECLARED_DEPS Region 2 mechanism fires for any absent stash key.

After C-4 sets DECLARED_DEPS = ("_bonus_chain_dynamics_data",) on BonusChainDynamics,
the PIA emit loop Region 2 pre-flight check fires PluginDeclaredDepMissingError if
any plugin's DECLARED_DEPS key is absent — producing a structured analyzer_init_error
on disk.

This test verifies the Region 2 mechanism itself (which C-4 relies on) by injecting
a plugin with DECLARED_DEPS=("_stash_key_absent_for_this_test",) — a key that is
genuinely absent from the summary at emit time.  The real `_bonus_chain_dynamics_data`
stash is always present (written unconditionally by PIA's stash builder before the
emit loop), so testing DECLARED_DEPS with that key would not exercise the error path.

Note: the existing test_a_init_error_disk_surfacing.py::TestRegion2DeclaredDepMissDiskSurfacing
already covers the Region 2 mechanism end-to-end.  This test provides a NAMED
C-4-specific regression: if DECLARED_DEPS is reverted to () on BonusChainDynamics,
Region 2 becomes the only guard against a missing stash at emit time.  The test
demonstrates the general mechanism works, and the CR-1 stash tests in
test_r2_c1_stash_still_populated.py confirm the stash is always written correctly.

Design decisions
----------------
- Uses in-process monkeypatch on feature_registry.get_features_for_machine
  (same pattern as test_a_init_error_disk_surfacing.py).
- The injected plugin declares DECLARED_DEPS on a key that is NOT written by any
  PIA stash builder, guaranteeing Region 2 fires.
- Per feedback_subprocess_import_suicide_and_module_globals.md: inject via
  monkeypatch on the registry function, not by modifying plugin class files.
- Per feedback_no_proactive_fetch.md: uses M14 cached chunks only.

Inject-bug recipe (per feedback_enumerate_safety_paths.md)
----------------------------------------------------------
Remove the DECLARED_DEPS Region 2 check from PIA's emit loop:
  In player_impact_analyzer.py, locate the Region 2 guard block
  (grep for "PluginDeclaredDepMissingError") and comment it out.
  Expected: _BadDepPlugin.emit() runs, no analyzer_init_error written.
  Assertion 3 (analyzer_init_error in summary) turns RED.
  Restore -> GREEN.

Memory files cited
------------------
- memory/feedback_no_silent_swallow.md — DECLARED_DEPS makes missing stash
  a first-class structured error, not a silently-caught RuntimeError
- memory/feedback_enumerate_safety_paths.md — inject-bug mandatory
- memory/feedback_subprocess_import_suicide_and_module_globals.md — in-process
  inject via monkeypatch on registry function, not module re-import
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIA_PATH = _REPO_ROOT / "fresh_slotlab" / "player_impact_analyzer.py"
_M14_CACHE = _REPO_ROOT / "rawdata" / "M14" / "mode_1"


def _m14_cache_available() -> bool:
    return _M14_CACHE.exists() and bool(list(_M14_CACHE.glob("chunk_*.json")))


_SKIP_NO_M14 = pytest.mark.skipif(
    not _m14_cache_available(),
    reason=f"M14 mode_1 cached chunks not found at {_M14_CACHE}",
)


# ---------------------------------------------------------------------------
# Minimal AnalyzerFeature stub (mirrors test_a_init_error_disk_surfacing.py)
# ---------------------------------------------------------------------------

class _MinimalFeatureBase:
    """Minimal AnalyzerFeature-compatible stub for injection."""
    FEATURE_ID: str = ""
    SCHEMA_KEYS: tuple = ()
    SCHEMA_VERSION: int = 1
    REQUIRES: tuple = ()
    DECLARED_DEPS: tuple = ()
    RTP_CONTRIBUTION: bool = False
    REGISTERED_FALLBACK_RULES: dict = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        return {}

    def reduce(self, prev_acc: Any, this_acc: Any) -> dict:
        return {}

    def emit(self, final_acc: Any, summary: dict, ctx: Any) -> None:
        summary.setdefault("player_impact", {})
        summary["player_impact"][f"_{self.FEATURE_ID}_ran"] = True


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
# Test — C-4 DECLARED_DEPS Region 2 fires PluginDeclaredDepMissingError
# ---------------------------------------------------------------------------

@_SKIP_NO_M14
class TestC4DeclaredDepsRegion2:
    """Region 2 DECLARED_DEPS check fires and writes structured error to disk.

    This test exercises the Region 2 mechanism that C-4 relies on.
    The injected plugin declares DECLARED_DEPS on a key that is genuinely
    absent from PIA's summary at emit time, causing Region 2 to fire.

    Assertions:
        1. SystemExit(1) raised (rc=1 contract from Region 2 handler).
        2. player_impact_summary.json EXISTS in output_dir.
        3. JSON top-level contains "analyzer_init_error".
        4. analyzer_init_error["error_type"] == "PluginDeclaredDepMissingError".
        5. analyzer_init_error["region"] == 2.
    """

    def test_c4_declared_deps_region2_fires_on_missing_stash(self, monkeypatch):
        """DECLARED_DEPS on absent stash key → Region 2 error written to disk."""
        import fresh_slotlab.player_impact_analyzer as _pia_mod
        import fresh_slotlab.analyzer.feature_registry as _registry_mod

        # Plugin that declares dependency on a key that is NOT written by any
        # PIA stash builder.  The _bonus_chain_dynamics_data key IS always written
        # by PIA before the emit loop, so using it would not exercise Region 2.
        # This key is chosen to be unambiguously absent from any PIA run.
        class _BCDLikeDepPlugin(_MinimalFeatureBase):
            FEATURE_ID = "test_bcd_like_dep_plugin"
            DECLARED_DEPS = ("_stash_key_absent_for_this_test",)

            def emit(self, final_acc: Any, summary: dict, ctx: Any) -> None:
                # Should never be reached — Region 2 fires before emit()
                summary.setdefault("player_impact", {})
                summary["player_impact"]["test_bcd_like_dep_ran"] = True

        monkeypatch.setattr(
            _registry_mod,
            "get_features_for_machine",
            lambda machine_id, manifest=None: [_BCDLikeDepPlugin()],
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
                "Region 2 handler must call _safe_write_summary_json before SystemExit(1). "
                "C-4 DECLARED_DEPS regression: error path did not write JSON."
            )

            summary = json.loads(summary_path.read_bytes())

            # Assertion 3: top-level key present
            assert "analyzer_init_error" in summary, (
                f"'analyzer_init_error' key absent from summary. "
                f"Top-level keys: {list(summary.keys())}. "
                f"C-4 DECLARED_DEPS regression: Region 2 did not write structured error."
            )

            err = summary["analyzer_init_error"]

            # Assertion 4: error_type
            assert err["error_type"] == "PluginDeclaredDepMissingError", (
                f"Expected error_type='PluginDeclaredDepMissingError', "
                f"got {err['error_type']!r}"
            )

            # Assertion 5: region=2
            assert err["region"] == 2, (
                f"Expected region=2 (emit-loop DECLARED_DEPS check), "
                f"got region={err['region']!r}"
            )
