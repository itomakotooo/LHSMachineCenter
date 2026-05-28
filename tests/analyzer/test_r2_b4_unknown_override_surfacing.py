"""R2 Phase 2 B-4: unrecognized mechanism_overrides key surfaces to feature_errors.

After B-4, MechanismRegistry.build() collects keys in the manifest's
mechanism_overrides dict that are NOT in the 5 recognized keys, stores them
in registry.unknown_override_keys, and the PIA call site writes each to
summary["feature_errors"]["mechanism_registry_unknown_override_<key>"].

Per feedback_invariant_with_fallback_hides_drift.md + feedback_no_silent_swallow.md:
an unrecognized override key must appear on disk (feature_errors JSON), not just
as a log line.  Operator sees it in the report; no silent fallback.

Design decisions
----------------
- Unit test: tests MechanismRegistry.build() directly with a synthetic manifest
  containing an unknown override key.  Asserts unknown_override_keys attribute.
- Integration test: monkeypatches the manifest resolution in PIA to inject a
  manifest with an unknown override key, then asserts feature_errors in the JSON.
- Per feedback_subprocess_import_suicide_and_module_globals.md: integration test
  injects via monkeypatch on manifest resolution, not by editing manifest files.
- Per feedback_no_proactive_fetch.md: uses M14 cached chunks only.

Inject-bug recipe (per feedback_enumerate_safety_paths.md)
----------------------------------------------------------
In mechanism_registry.py, remove the _unknown_keys collection and
registry.unknown_override_keys assignment from build().  Expected:
  summary["feature_errors"] lacks "mechanism_registry_unknown_override_typo_key".
  TestB4IntegrationUnknownOverrideSurfacing::test_b4_unknown_key_surfaces_to_feature_errors
  turns RED (asserts the key IS present in feature_errors).
Restore -> GREEN.

Memory files cited
------------------
- memory/feedback_invariant_with_fallback_hides_drift.md — unknown keys must alert,
  not silently fall through to Tier 3 detection
- memory/feedback_no_silent_swallow.md — error must persist to disk, not just log
- memory/feedback_enumerate_safety_paths.md — inject-bug mandatory
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

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
# Helper: build registry with synthetic manifest
# ---------------------------------------------------------------------------

def _build_registry(manifest: dict | None = None, **kwargs) -> Any:
    try:
        from fresh_slotlab.analyzer.mechanism_registry import MechanismRegistry
    except ImportError:
        from analyzer.mechanism_registry import MechanismRegistry  # type: ignore[no-redef]
    return MechanismRegistry.build(
        manifest=manifest or {},
        payout_id_win=kwargs.get("payout_id_win", {}),
        payout_id_hits=kwargs.get("payout_id_hits", {}),
        jackpot_ids_seen=kwargs.get("jackpot_ids_seen", set()),
        bonus_chain_lengths=kwargs.get("bonus_chain_lengths", []),
        total_freespin_chain_spins=kwargs.get("total_freespin_chain_spins", 0),
        payout_group_win=kwargs.get("payout_group_win", {}),
        pid_has_regular_line=kwargs.get("pid_has_regular_line", {}),
    )


# ---------------------------------------------------------------------------
# Unit tests — MechanismRegistry.unknown_override_keys attribute
# ---------------------------------------------------------------------------

class TestB4UnknownOverrideKeysUnit:
    """Unit tests for MechanismRegistry.unknown_override_keys (B-4 CR-2)."""

    def test_no_overrides_gives_empty_unknown_keys(self):
        """Manifest with no mechanism_overrides -> unknown_override_keys == []."""
        reg = _build_registry(manifest={})
        assert hasattr(reg, "unknown_override_keys"), (
            "MechanismRegistry instance must have 'unknown_override_keys' attribute. "
            "B-4: ensure build() sets registry.unknown_override_keys."
        )
        assert reg.unknown_override_keys == [], (
            f"unknown_override_keys must be [] when no overrides, "
            f"got {reg.unknown_override_keys!r}"
        )

    def test_recognized_keys_give_empty_unknown_keys(self):
        """All 5 recognized override keys produce unknown_override_keys == []."""
        manifest = {
            "mechanism_overrides": {
                "scatter_marker_pids": [],
                "jackpot_applicable": False,
                "jackpot_pid_set": [],
                "freespin_applicable": False,
                "payout_groups_applicable": False,
            }
        }
        reg = _build_registry(manifest=manifest)
        assert reg.unknown_override_keys == [], (
            f"Recognized keys must not appear in unknown_override_keys, "
            f"got {reg.unknown_override_keys!r}"
        )

    def test_single_unknown_key_collected(self):
        """A single unknown key -> unknown_override_keys == ['typo_key']."""
        manifest = {
            "mechanism_overrides": {
                "jackpot_applicable": True,
                "typo_key": "this_is_wrong",
            }
        }
        reg = _build_registry(manifest=manifest)
        assert "typo_key" in reg.unknown_override_keys, (
            f"'typo_key' must appear in unknown_override_keys. "
            f"Got {reg.unknown_override_keys!r}"
        )
        assert len(reg.unknown_override_keys) == 1, (
            f"Only 'typo_key' should be unknown (jackpot_applicable is recognized). "
            f"Got {reg.unknown_override_keys!r}"
        )

    def test_multiple_unknown_keys_all_collected(self):
        """Multiple unknown keys -> all in unknown_override_keys list."""
        manifest = {
            "mechanism_overrides": {
                "bad_key_1": 1,
                "bad_key_2": "x",
                "jackpot_applicable": True,  # recognized — must NOT appear
            }
        }
        reg = _build_registry(manifest=manifest)
        assert set(reg.unknown_override_keys) == {"bad_key_1", "bad_key_2"}, (
            f"Expected {{'bad_key_1', 'bad_key_2'}} in unknown_override_keys, "
            f"got {reg.unknown_override_keys!r}"
        )

    def test_default_constructor_has_empty_unknown_keys(self):
        """MechanismRegistry() (no-args) must have unknown_override_keys == []."""
        try:
            from fresh_slotlab.analyzer.mechanism_registry import MechanismRegistry
        except ImportError:
            from analyzer.mechanism_registry import MechanismRegistry  # type: ignore[no-redef]
        reg = MechanismRegistry()
        assert hasattr(reg, "unknown_override_keys"), (
            "MechanismRegistry() must have 'unknown_override_keys' attribute "
            "(set in __init__ for compatibility with no-args constructor)."
        )
        assert reg.unknown_override_keys == [], (
            f"no-args constructor must give unknown_override_keys=[], "
            f"got {reg.unknown_override_keys!r}"
        )


# ---------------------------------------------------------------------------
# Integration test — PIA writes unknown key to feature_errors on disk
# ---------------------------------------------------------------------------

@_SKIP_NO_M14
class TestB4IntegrationUnknownOverrideSurfacing:
    """Integration: unknown override key -> feature_errors entry on disk.

    Injects a manifest with mechanism_overrides containing an unknown key
    by monkeypatching manifest_loader.load_manifest.  PIA calls
    `from fresh_slotlab.analyzer.manifest_loader import load_manifest as _c1_load_manifest`
    inside main(); patching the module attribute causes main() to pick up the wrapper.

    Assertions:
        1. PIA exits 0 (unknown key is a warning, not a fatal error).
        2. player_impact_summary.json EXISTS in output_dir.
        3. "feature_errors" in summary.
        4. "mechanism_registry_unknown_override_typo_key" in summary["feature_errors"].
        5. That feature_errors entry has type=="UnrecognizedMechanismOverrideKey".
        6. No "analyzer_init_error" in summary (unknown key is non-fatal).
    """

    def test_b4_unknown_key_surfaces_to_feature_errors(self, monkeypatch):
        """Unknown mechanism_overrides key -> feature_errors entry written to disk."""
        import fresh_slotlab.player_impact_analyzer as _pia_mod
        import fresh_slotlab.analyzer.manifest_loader as _manifest_loader_mod

        # Wrap load_manifest to inject an unknown mechanism_overrides key
        _real_load_manifest = _manifest_loader_mod.load_manifest

        def _patched_load_manifest(machine_id: Any, manifest_root: Any) -> dict:
            result = _real_load_manifest(machine_id, manifest_root)
            if isinstance(result, dict):
                if "mechanism_overrides" not in result:
                    result["mechanism_overrides"] = {}
                result["mechanism_overrides"]["typo_key"] = "injected_for_test"
            return result

        monkeypatch.setattr(
            _manifest_loader_mod,
            "load_manifest",
            _patched_load_manifest,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(sys, "argv", [
                str(_PIA_PATH),
                "--machine", "M14",
                "--rtp-mode", "1",
                "--from-cache", str(_M14_CACHE),
                "--output-dir", tmpdir,
                "--bet", "1000",
            ])

            # Must NOT raise SystemExit (unknown key is non-fatal)
            _pia_mod.main()

            summary_path = Path(tmpdir) / "player_impact_summary.json"

            # Assertion 2: JSON exists
            assert summary_path.exists(), (
                f"player_impact_summary.json NOT FOUND at {summary_path}."
            )

            summary = json.loads(summary_path.read_bytes())

            # Assertion 6: no fatal error
            assert "analyzer_init_error" not in summary, (
                f"analyzer_init_error present — unknown override key is non-fatal: "
                f"{summary.get('analyzer_init_error')}"
            )

            # Assertion 3: feature_errors present
            assert "feature_errors" in summary, (
                f"'feature_errors' key absent from summary. "
                f"B-4: unknown override key must write to feature_errors. "
                f"Top-level keys: {list(summary.keys())}"
            )

            fe = summary["feature_errors"]

            # Assertion 4: specific key present
            expected_key = "mechanism_registry_unknown_override_typo_key"
            assert expected_key in fe, (
                f"'{expected_key}' absent from feature_errors. "
                f"feature_errors keys: {sorted(fe.keys())}. "
                f"B-4 regression: MechanismRegistry.build() unknown key not surfaced."
            )

            # Assertion 5: type field matches
            entry = fe[expected_key]
            assert isinstance(entry, dict), (
                f"feature_errors['{expected_key}'] must be a dict, got {type(entry)}"
            )
            assert entry.get("type") == "UnrecognizedMechanismOverrideKey", (
                f"Expected type='UnrecognizedMechanismOverrideKey', "
                f"got {entry.get('type')!r}"
            )
            assert entry.get("key") == "typo_key", (
                f"Expected key='typo_key', got {entry.get('key')!r}"
            )
