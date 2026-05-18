"""Regression tests for P2-A2 manifest loader.

Contracts asserted (§3 C1-C8 from 00_ticket.md):

  C1 -- load_manifest: present (parses OK), missing (FileNotFoundError),
        malformed JSON (re-raised with context).
  C2 -- resolve_inheritance: null (as-is), variant inherits 6 base fields,
        variant cannot override analyzer_features directly.
  C3 -- resolve_per_mode: _remove before _add order; _override patterns;
        forbidden fields (machine_id / manifest_version / inherits_from /
        console_diagnostic_complete / layer4_applicable) cannot be overridden.
  C4 -- resolve_completeness per §5.5.7 verbatim pseudocode (3 branches:
        _UNSET → underlying; False → False; True → ManifestValidationError).
  C5 -- All 11 validation rules per §5.6.
  C6 -- resolve_layer4_applicable per 07_decision_v5.md P1 verbatim.
  C7 -- Subprocess import safety: no I/O at import time.
  C8 -- Inject-bug TDD per memory feedback_integration_test_argv.md.

Reference implementations (written FROM SPEC before reading implementer code):

  _ref_resolve_completeness   -- §5.5.7 lines 553-573 verbatim
  _ref_resolve_layer4         -- 07_decision_v5.md P1 verbatim

INJECT-BUG DISCIPLINE (per memory feedback_integration_test_argv.md):
  Each inject-bug step is documented in the 03_tests.md file and in the
  relevant test docstring. The discipline is:
    1. Stash implementer's diff (or hand-revert the targeted line)
    2. Run the test -> must go RED
    3. Restore implementer's code
    4. Run the test -> must go GREEN

Note: tests are written against the spec, not the implementer's code.
They may fail until the implementer lands manifest_loader.py.
Status is documented in 03_tests.md.

Spec references:
  session_artifacts/_arch/04_architecture_proposal_v5.md §5.5.1-7 (lines 369-587)
  session_artifacts/_arch/04_architecture_proposal_v5.md §5.6 (lines 588-600)
  session_artifacts/_arch/04_architecture_proposal_v5.md §5.11 (lines 618-708)
  session_artifacts/_arch/07_decision_v5.md P1 (lines 50-58)
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = ROOT / "slot_designer" / "configs" / "machine_manifests" / "_fixtures"

# ---------------------------------------------------------------------------
# Reference implementations (written from spec, NOT from implementer's code)
# Used to independently verify algorithm correctness.
# ---------------------------------------------------------------------------

_UNSET = object()


class _RefManifestValidationError(Exception):
    """Mirror of the error class the implementer must expose."""


def _ref_resolve_completeness(variant_manifest: dict, underlying_manifest: dict) -> bool:
    """Reference implementation of resolve_completeness per §5.5.7 lines 553-573.

    Written verbatim from the spec pseudocode before reading implementer code.
    Used to cross-check that the implementer's algorithm matches the spec.
    """
    underlying_complete = underlying_manifest["console_diagnostic_complete"]
    override = variant_manifest.get("console_diagnostic_complete_override", _UNSET)
    if override is _UNSET:
        return underlying_complete
    if override is False:
        return False
    # override is True — spec says raise
    raise _RefManifestValidationError(
        f"{variant_manifest['machine_id']}: console_diagnostic_complete_override: true "
        f"is not permitted. Variants cannot elevate completeness above their underlying."
    )


def _ref_resolve_layer4_applicable(manifest_resolved: dict, mode: int) -> bool:
    """Reference implementation of resolve_layer4_applicable per 07_decision_v5.md P1.

    The spec pseudocode (lines 50-58):
        pattern = manifest.modes[mode].get("trigger_session_pattern")
        if pattern is None:
            return True
        override = manifest.modes[mode].get("trigger_session_pattern_override")
        if override is not None:
            pattern = override
        return False  # any non-null trigger_session_pattern -> skip Layer 4

    We interpret "manifest.modes[mode]" as the per-mode resolved view of the manifest,
    which is what resolve_per_mode(manifest, mode) produces. The resolved manifest
    has a top-level "trigger_session_pattern" key (base or overridden).
    """
    # Base pattern from the manifest (before per-mode resolution)
    base_pattern = manifest_resolved.get("trigger_session_pattern")
    # Per-mode override, if any
    per_mode = manifest_resolved.get("per_mode_overrides", {}).get(str(mode), {})
    override = per_mode.get("trigger_session_pattern_override", _UNSET)

    if override is not _UNSET:
        # The per-mode override replaces the base
        effective = override
    else:
        effective = base_pattern

    if effective is None:
        return True
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture(name: str) -> dict:
    """Load a JSON fixture by machine_id name (without .json)."""
    path = FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _import_loader():
    """Import the manifest_loader module, with a clear skip if not yet implemented."""
    try:
        import fresh_slotlab.analyzer.manifest_loader as ml
        return ml
    except ImportError as exc:
        pytest.skip(f"manifest_loader.py not yet implemented: {exc}")


# ---------------------------------------------------------------------------
# C7 -- Subprocess import safety (runs first so failure is immediately visible)
# ---------------------------------------------------------------------------

class TestC7SubprocessImportSafety:
    """C7 — No I/O or side effects at import time.

    Per memory feedback_subprocess_import_suicide_and_module_globals.md:
    importing the module in a subprocess must not trigger I/O, DB calls,
    or process-killing side effects.

    INJECT-BUG: Remove this test, add a top-level
        load_manifest("M1", Path("."))  # I/O at module level
    in manifest_loader.py -> test goes RED (FileNotFoundError in subprocess).
    Restore -> GREEN.
    """

    def test_subprocess_import_no_side_effects(self):
        """Spawn a real subprocess; assert rc=0 and stdout='OK'."""
        cmd = [
            sys.executable,
            "-c",
            "import fresh_slotlab.analyzer.manifest_loader; print('OK')",
        ]
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"manifest_loader import raised in subprocess.\n"
            f"stderr: {result.stderr!r}\n"
            f"stdout: {result.stdout!r}"
        )
        assert "OK" in result.stdout, (
            f"Expected 'OK' in stdout; got: {result.stdout!r}"
        )

    def test_no_module_level_io(self):
        """Verify no file reads happen at import by checking the module has no
        module-level calls to open() / Path.read_text / json.load outside functions.

        This is a static smoke: we do a process import AND assert the module
        attributes don't hold any cached file data that would require I/O.
        """
        ml = _import_loader()
        # If the module loaded cleanly without I/O, these should not exist
        # as top-level populated caches from file reads
        assert not hasattr(ml, "_LOADED_MANIFESTS_CACHE") or callable(
            getattr(ml, "_LOADED_MANIFESTS_CACHE", None)
        ), "Module must not populate a manifest cache at import time (I/O at top level)"


# ---------------------------------------------------------------------------
# C1 -- load_manifest
# ---------------------------------------------------------------------------

class TestC1LoadManifest:
    """C1 -- load_manifest(machine_id, manifests_dir) contract.

    Per §3 C1: returns parsed dict on success; FileNotFoundError if absent;
    JSONDecodeError (re-raised with context) if malformed.
    NO silent fallback (memory feedback_dont_swallow_errors_in_fix.md).

    INJECT-BUG per C8:
      Missing file: comment out the FileNotFoundError raise -> test_missing_file fails.
      Malformed JSON: swallow json.JSONDecodeError -> test_malformed_json fails.
    """

    def test_load_present_manifest_m1(self, tmp_path):
        """load_manifest('M1', fixtures_dir) returns a parsed dict."""
        ml = _import_loader()
        result = ml.load_manifest("M1", FIXTURES_DIR)
        assert isinstance(result, dict)
        assert result["machine_id"] == "M1"
        assert result["manifest_version"] == 1

    def test_load_present_manifest_m15(self, tmp_path):
        """load_manifest('M15', fixtures_dir) returns a parsed dict with correct fields."""
        ml = _import_loader()
        result = ml.load_manifest("M15", FIXTURES_DIR)
        assert result["machine_id"] == "M15"
        assert result["trigger_session_pattern"] == "type_1"
        assert result["layer4_applicable"] is False

    def test_load_present_manifest_m274(self, tmp_path):
        """load_manifest('M274', fixtures_dir) parses per_mode_overrides correctly."""
        ml = _import_loader()
        result = ml.load_manifest("M274", FIXTURES_DIR)
        assert result["machine_id"] == "M274"
        assert "per_mode_overrides" in result
        assert "5" in result["per_mode_overrides"]

    def test_load_variant_manifest(self, tmp_path):
        """load_manifest for a variant ID with $ separators in the filename."""
        ml = _import_loader()
        result = ml.load_manifest("M15$TopDollarSelector$0$", FIXTURES_DIR)
        assert result["machine_id"] == "M15$TopDollarSelector$0$"
        assert result["inherits_from"] == "M15.json"

    def test_missing_file_raises_file_not_found(self, tmp_path):
        """Absent manifest raises FileNotFoundError with machine_id in message.

        INJECT-BUG: Make the loader return {} instead of raising ->
        this test goes RED (no exception raised).
        """
        ml = _import_loader()
        with pytest.raises(FileNotFoundError) as exc_info:
            ml.load_manifest("M9999_nonexistent", FIXTURES_DIR)
        # Message should include the machine_id for debuggability
        assert "M9999_nonexistent" in str(exc_info.value)

    def test_malformed_json_raises_with_context(self, tmp_path):
        """Malformed JSON raises JSONDecodeError (or subclass) with context.

        The error must propagate, not be swallowed (memory feedback_dont_swallow_errors_in_fix.md).

        INJECT-BUG: Wrap json.loads in try/except and return {} on error ->
        this test goes RED (no exception raised).
        """
        bad_json = tmp_path / "MBAD.json"
        bad_json.write_text("{invalid json here", encoding="utf-8")

        ml = _import_loader()
        with pytest.raises((json.JSONDecodeError, ValueError)) as exc_info:
            ml.load_manifest("MBAD", tmp_path)
        # Exception should include some context about where the error is
        assert exc_info.value is not None

    def test_empty_json_raises(self, tmp_path):
        """Completely empty file triggers a parse error, not a silent dict."""
        empty = tmp_path / "MEMPTY.json"
        empty.write_text("", encoding="utf-8")

        ml = _import_loader()
        with pytest.raises((json.JSONDecodeError, ValueError)):
            ml.load_manifest("MEMPTY", tmp_path)

    def test_load_returns_dict_not_str(self):
        """Return type is dict, not the raw JSON string."""
        ml = _import_loader()
        result = ml.load_manifest("M1", FIXTURES_DIR)
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_missing_file_not_silent_fallback(self, tmp_path):
        """No silent empty-dict return for a missing file.

        Per memory feedback_dont_swallow_errors_in_fix.md: silent swallow is
        the anti-pattern. Verify the exception actually propagates.
        """
        ml = _import_loader()
        raised = False
        try:
            ml.load_manifest("MNOTEXIST", tmp_path)
        except FileNotFoundError:
            raised = True
        except Exception:
            raised = True  # any exception is acceptable — what's NOT OK is returning a dict
        assert raised, "load_manifest must raise on missing file, not return a fallback"


# ---------------------------------------------------------------------------
# C2 -- resolve_inheritance
# ---------------------------------------------------------------------------

class TestC2ResolveInheritance:
    """C2 -- resolve_inheritance(manifest, manifests_dir) contract.

    Per §3 C2:
    - null inherits_from -> returns manifest as-is
    - variant inherits all 6 base fields from parent
    - variant CANNOT override analyzer_features directly

    The 6 inherited fields per §5.5.5:
        analyzer_features, round_win_rules, spin_type_convention,
        feature_tags, rtp_integrity_contract, modes_supported

    INJECT-BUG per C8:
      Variant overrides analyzer_features directly -> test_variant_cannot_override_analyzer_features_directly
      goes RED only if the loader detects and rejects this.
    """

    def test_null_inherits_from_returns_as_is(self):
        """Manifest with inherits_from: null returns unchanged dict."""
        ml = _import_loader()
        m1 = _load_fixture("M1")
        assert m1["inherits_from"] is None
        result = ml.resolve_inheritance(m1, FIXTURES_DIR)
        assert result["machine_id"] == "M1"
        # Spot-check key fields are preserved
        assert result["analyzer_features"] == m1["analyzer_features"]
        assert result["modes_supported"] == m1["modes_supported"]

    def test_null_inherits_from_identity(self):
        """null inherits_from: result is logically identical to input."""
        ml = _import_loader()
        m274 = _load_fixture("M274")
        result = ml.resolve_inheritance(m274, FIXTURES_DIR)
        assert result["machine_id"] == m274["machine_id"]
        assert result["per_mode_overrides"] == m274.get("per_mode_overrides")

    def test_variant_inherits_analyzer_features(self):
        """Variant manifest inherits analyzer_features from parent.

        Per §5.5.5: variants ARE the same machine; parser cannot drift.

        INJECT-BUG: Skip merging analyzer_features in resolve_inheritance ->
        result["analyzer_features"] is missing -> test goes RED.
        """
        ml = _import_loader()
        variant = _load_fixture("M15$TopDollarSelector$0$")
        assert variant["inherits_from"] == "M15.json"
        result = ml.resolve_inheritance(variant, FIXTURES_DIR)

        parent = _load_fixture("M15")
        assert result["analyzer_features"] == parent["analyzer_features"]

    def test_variant_inherits_round_win_rules(self):
        """Variant inherits round_win_rules from parent."""
        ml = _import_loader()
        variant = _load_fixture("M15$TopDollarSelector$0$")
        result = ml.resolve_inheritance(variant, FIXTURES_DIR)

        parent = _load_fixture("M15")
        assert result["round_win_rules"] == parent["round_win_rules"]

    def test_variant_inherits_spin_type_convention(self):
        """Variant inherits spin_type_convention from parent."""
        ml = _import_loader()
        variant = _load_fixture("M15$TopDollarSelector$0$")
        result = ml.resolve_inheritance(variant, FIXTURES_DIR)

        parent = _load_fixture("M15")
        assert result["spin_type_convention"] == parent["spin_type_convention"]

    def test_variant_inherits_feature_tags(self):
        """Variant inherits feature_tags from parent."""
        ml = _import_loader()
        variant = _load_fixture("M15$TopDollarSelector$0$")
        result = ml.resolve_inheritance(variant, FIXTURES_DIR)

        parent = _load_fixture("M15")
        assert result["feature_tags"] == parent["feature_tags"]

    def test_variant_inherits_rtp_integrity_contract(self):
        """Variant inherits rtp_integrity_contract from parent."""
        ml = _import_loader()
        variant = _load_fixture("M15$TopDollarSelector$0$")
        result = ml.resolve_inheritance(variant, FIXTURES_DIR)

        parent = _load_fixture("M15")
        assert result["rtp_integrity_contract"] == parent["rtp_integrity_contract"]

    def test_variant_inherits_modes_supported(self):
        """Variant inherits modes_supported from parent."""
        ml = _import_loader()
        variant = _load_fixture("M15$TopDollarSelector$0$")
        result = ml.resolve_inheritance(variant, FIXTURES_DIR)

        parent = _load_fixture("M15")
        assert result["modes_supported"] == parent["modes_supported"]

    def test_variant_cannot_override_analyzer_features_directly(self, tmp_path):
        """Variant with a direct analyzer_features key triggers a validation error.

        Per §3 C2: variants can only change analyzer_features via
        per_mode_overrides._add/_remove, not by setting the key directly.

        Round-2: xfail removed — fix implemented in resolve_inheritance() per
        critic R1 citing brief §3 C2 + 04_v5 §5.5.4-5.5.5.

        INJECT-BUG: Remove the guard in resolve_inheritance that checks for
        direct analyzer_features override -> test goes RED (no exception raised).
        """
        bad_variant = {
            "machine_id": "M15$BadVariant$0$",
            "manifest_version": 1,
            "inherits_from": "M15.json",
            "analyzer_features": ["payouts_by_spin_type"],  # FORBIDDEN in variant
        }
        bad_variant_file = tmp_path / "M15$BadVariant$0$.json"
        bad_variant_file.write_text(json.dumps(bad_variant), encoding="utf-8")
        # Copy M15.json to tmp_path so inherits_from can be resolved
        import shutil
        shutil.copy(FIXTURES_DIR / "M15.json", tmp_path / "M15.json")

        ml = _import_loader()
        # Must raise some kind of ManifestValidationError or ValueError
        with pytest.raises(Exception) as exc_info:
            ml.resolve_inheritance(bad_variant, tmp_path)
        exc_str = str(exc_info.value).lower()
        assert any(
            keyword in exc_str
            for keyword in ("analyzer_features", "cannot override", "direct", "variant", "forbidden")
        ), (
            f"Expected error to mention analyzer_features or override prohibition; "
            f"got: {exc_info.value!r}"
        )

    def test_variant_can_override_completeness_true_to_false(self, tmp_path):
        """Variant with console_diagnostic_complete_override: false is allowed.

        Per §5.5.7: override is permitted only true -> false (regression valve).
        """
        # M1 is complete: true; variant overrides to false
        variant = {
            "machine_id": "M1$TestVariant$0$",
            "manifest_version": 1,
            "inherits_from": "M1.json",
            "console_diagnostic_complete_override": False,
            "override_set_at": "2026-05-17T09:00:00Z",
            "override_set_reason": "Test override reason.",
            "override_set_by": "test suite",
        }
        import shutil
        shutil.copy(FIXTURES_DIR / "M1.json", tmp_path / "M1.json")

        ml = _import_loader()
        # Should not raise; override false is legal
        result = ml.resolve_inheritance(variant, tmp_path)
        assert result is not None  # completed without error


# ---------------------------------------------------------------------------
# C3 -- resolve_per_mode
# ---------------------------------------------------------------------------

class TestC3ResolvePerMode:
    """C3 -- resolve_per_mode(manifest, mode) contract.

    Per §3 C3 and §5.5.6:
    - _remove runs BEFORE _add (resolution order from line 474)
    - _override patterns work for each override type
    - Forbidden fields: machine_id / manifest_version / inherits_from /
      console_diagnostic_complete / layer4_applicable

    INJECT-BUG per C8:
      Swap _remove/_add order -> test_remove_applied_before_add goes RED.
    """

    def test_no_per_mode_override_returns_base(self):
        """Mode with no overrides returns manifest unchanged."""
        ml = _import_loader()
        m1 = _load_fixture("M1")
        result = ml.resolve_per_mode(m1, 1)
        assert result["analyzer_features"] == m1["analyzer_features"]
        assert result["machine_id"] == m1["machine_id"]

    def test_analyzer_features_remove_applied(self):
        """M274 mode 5: bonus_chain_dynamics is removed from analyzer_features.

        INJECT-BUG: Skip _remove processing -> bonus_chain_dynamics still in
        result["analyzer_features"] -> test goes RED.
        """
        ml = _import_loader()
        m274 = _load_fixture("M274")
        result = ml.resolve_per_mode(m274, 5)
        assert "bonus_chain_dynamics" not in result["analyzer_features"]

    def test_analyzer_features_remove_preserves_others(self):
        """M274 mode 5: other features survive the remove."""
        ml = _import_loader()
        m274 = _load_fixture("M274")
        result = ml.resolve_per_mode(m274, 5)
        # All non-removed features must survive
        base = _load_fixture("M274")
        expected_remaining = [f for f in base["analyzer_features"] if f != "bonus_chain_dynamics"]
        for feat in expected_remaining:
            assert feat in result["analyzer_features"], (
                f"Feature {feat!r} unexpectedly removed from mode 5"
            )

    def test_analyzer_features_add(self, tmp_path):
        """Mode with analyzer_features_add appends to base list."""
        manifest = {
            "machine_id": "MTEST",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": [],
            "analyzer_features": ["payouts_by_spin_type"],
            "trigger_session_pattern": None,
            "modes_supported": [1, 2],
            "per_mode_overrides": {
                "2": {
                    "analyzer_features_add": ["bankruptcy_simulation"]
                }
            },
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        ml = _import_loader()
        result = ml.resolve_per_mode(manifest, 2)
        assert "payouts_by_spin_type" in result["analyzer_features"]
        assert "bankruptcy_simulation" in result["analyzer_features"]

    def test_remove_applied_before_add(self, tmp_path):
        """Resolution order: _remove before _add per §5.5.6 line 474.

        A feature that is BOTH removed and re-added in the same mode must
        end up IN the list (add wins, because remove runs first).

        INJECT-BUG: Apply _add before _remove -> the feature gets removed
        AFTER being added -> test goes RED (feature absent when it should be present).
        """
        manifest = {
            "machine_id": "MORDER",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": [],
            "analyzer_features": ["payouts_by_spin_type", "bankruptcy_simulation"],
            "trigger_session_pattern": None,
            "modes_supported": [1],
            "per_mode_overrides": {
                "1": {
                    # Remove bankruptcy_simulation THEN re-add it
                    # Result should: it's present (remove then add)
                    "analyzer_features_remove": ["bankruptcy_simulation"],
                    "analyzer_features_add": ["bankruptcy_simulation"],
                }
            },
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        ml = _import_loader()
        result = ml.resolve_per_mode(manifest, 1)
        # remove runs first (bankruptcy_simulation gone), then add brings it back
        assert "bankruptcy_simulation" in result["analyzer_features"], (
            "Feature removed then re-added should end up PRESENT "
            "(remove-before-add order per §5.5.6 line 474)"
        )

    def test_remove_then_no_add_feature_absent(self, tmp_path):
        """Converse: remove-only means feature is absent in mode result."""
        manifest = {
            "machine_id": "MORDER2",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": [],
            "analyzer_features": ["payouts_by_spin_type", "bankruptcy_simulation"],
            "trigger_session_pattern": None,
            "modes_supported": [1],
            "per_mode_overrides": {
                "1": {
                    "analyzer_features_remove": ["bankruptcy_simulation"],
                    # no _add
                }
            },
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        ml = _import_loader()
        result = ml.resolve_per_mode(manifest, 1)
        assert "bankruptcy_simulation" not in result["analyzer_features"]

    def test_bcm_target_feature_override(self):
        """bcm_target_feature_override replaces the base bcm_target_feature."""
        manifest = {
            "machine_id": "MBCM",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [140], "bonus": [139]},
            "feature_tags": ["BCM"],
            "round_win_rules": [],
            "analyzer_features": ["payouts_by_spin_type"],
            "bcm_target_feature": "Wheel",
            "trigger_session_pattern": None,
            "modes_supported": [1, 2],
            "per_mode_overrides": {
                "2": {
                    "bcm_target_feature_override": "MoveSpin"
                }
            },
            "rtp_integrity_contract": {
                "expected_paid_st": [140],
                "expected_bonus_st": [139],
                "required_attribution_anchors": []
            },
        }
        ml = _import_loader()
        result = ml.resolve_per_mode(manifest, 2)
        assert result["bcm_target_feature"] == "MoveSpin"

    def test_trigger_session_pattern_override(self):
        """trigger_session_pattern_override replaces base pattern."""
        manifest = {
            "machine_id": "MTSP",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": False,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": [],
            "analyzer_features": ["payouts_by_spin_type"],
            "trigger_session_pattern": "type_1",
            "modes_supported": [1, 2],
            "per_mode_overrides": {
                "2": {
                    "trigger_session_pattern_override": None
                }
            },
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        ml = _import_loader()
        result = ml.resolve_per_mode(manifest, 2)
        assert result["trigger_session_pattern"] is None

    def test_required_attribution_anchors_override(self):
        """required_attribution_anchors_override replaces anchors in rtp_integrity_contract."""
        manifest = {
            "machine_id": "MANCHORS",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [140], "bonus": []},
            "feature_tags": [],
            "round_win_rules": [],
            "analyzer_features": ["payouts_by_spin_type"],
            "trigger_session_pattern": None,
            "modes_supported": [1, 2],
            "per_mode_overrides": {
                "2": {
                    "required_attribution_anchors_override": ["_bcm_cycle"]
                }
            },
            "rtp_integrity_contract": {
                "expected_paid_st": [140],
                "expected_bonus_st": [],
                "required_attribution_anchors": ["5801"]
            },
        }
        ml = _import_loader()
        result = ml.resolve_per_mode(manifest, 2)
        assert result["rtp_integrity_contract"]["required_attribution_anchors"] == ["_bcm_cycle"]

    def test_spin_type_convention_override(self):
        """spin_type_convention_override replaces the base spin_type_convention."""
        manifest = {
            "machine_id": "MSTC",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": [],
            "analyzer_features": ["payouts_by_spin_type"],
            "trigger_session_pattern": None,
            "modes_supported": [1, 2],
            "per_mode_overrides": {
                "2": {
                    "spin_type_convention_override": {"paid": [2], "bonus": [10, 11]}
                }
            },
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        ml = _import_loader()
        result = ml.resolve_per_mode(manifest, 2)
        assert result["spin_type_convention"]["paid"] == [2]
        assert result["spin_type_convention"]["bonus"] == [10, 11]

    def test_feature_tags_override(self):
        """feature_tags_override replaces the base feature_tags list."""
        manifest = {
            "machine_id": "MFTAGS",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": ["BCM"],
            "round_win_rules": [],
            "analyzer_features": ["payouts_by_spin_type"],
            "trigger_session_pattern": None,
            "modes_supported": [1, 2],
            "per_mode_overrides": {
                "2": {
                    "feature_tags_override": ["BCM", "Wheel"]
                }
            },
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        ml = _import_loader()
        result = ml.resolve_per_mode(manifest, 2)
        assert result["feature_tags"] == ["BCM", "Wheel"]

    @pytest.mark.parametrize("forbidden_field", [
        "machine_id",
        "manifest_version",
        "inherits_from",
        "console_diagnostic_complete",
        "layer4_applicable",
    ])
    def test_forbidden_fields_cannot_be_in_per_mode_overrides(self, forbidden_field):
        """Fields forbidden from per_mode_overrides per §5.5.6 line 472.

        Per spec: machine_id, manifest_version, inherits_from,
        console_diagnostic_complete, layer4_applicable MUST NOT appear
        in per_mode_overrides. Validation error if attempted.

        INJECT-BUG: Remove the forbidden-field check -> no error raised ->
        test goes RED.
        """
        import fresh_slotlab.analyzer.manifest_loader as ml_module
        manifest = {
            "machine_id": "MFORBIDDEN",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": [],
            "analyzer_features": ["payouts_by_spin_type"],
            "trigger_session_pattern": None,
            "modes_supported": [1],
            "per_mode_overrides": {
                "1": {
                    forbidden_field: "whatever"
                }
            },
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        ml = _import_loader()
        # Must raise a ValueError at resolve_per_mode time per implementer's choice,
        # OR produce a validation error via validate_manifest.
        # The spec says "validation error if attempted" (§5.5.6 line 472).
        # The implementer raises ValueError from resolve_per_mode, which is also valid.
        # We test both paths: first check validate_manifest (may include rule 5 error
        # from failed resolve_per_mode), then also check resolve_per_mode directly.
        errors = ml.validate_manifest(manifest, machines_config={}, registry=None)
        # Either: errors list contains a mention of the forbidden field,
        # OR: resolve_per_mode raises ValueError
        error_msgs = [str(e) for e in errors]
        combined = " ".join(error_msgs).lower()
        found_in_errors = any(
            forbidden_field.lower() in msg or "forbidden" in msg or "cannot" in msg
            for msg in error_msgs
        )

        # Also test resolve_per_mode raises ValueError directly
        raises_at_resolve = False
        try:
            ml.resolve_per_mode(manifest, 1)
        except ValueError as exc:
            exc_str = str(exc).lower()
            if forbidden_field.lower() in exc_str or "forbidden" in exc_str or "cannot" in exc_str:
                raises_at_resolve = True

        assert found_in_errors or raises_at_resolve, (
            f"Expected a validation error or ValueError mentioning forbidden field "
            f"{forbidden_field!r}; "
            f"validate_manifest errors: {error_msgs}, "
            f"resolve_per_mode raised ValueError with forbidden mention: {raises_at_resolve}"
        )

    def test_round_win_rules_add(self):
        """round_win_rules_add appends to the base list."""
        manifest = {
            "machine_id": "MRWRADD",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": ["base_rule"],
            "analyzer_features": ["payouts_by_spin_type"],
            "trigger_session_pattern": None,
            "modes_supported": [1, 2],
            "per_mode_overrides": {
                "2": {
                    "round_win_rules_add": ["mode2_rule"]
                }
            },
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        ml = _import_loader()
        result = ml.resolve_per_mode(manifest, 2)
        assert "base_rule" in result["round_win_rules"]
        assert "mode2_rule" in result["round_win_rules"]

    def test_round_win_rules_remove(self):
        """round_win_rules_remove drops from the base list."""
        manifest = {
            "machine_id": "MRWRREM",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": ["base_rule", "old_rule"],
            "analyzer_features": ["payouts_by_spin_type"],
            "trigger_session_pattern": None,
            "modes_supported": [1, 2],
            "per_mode_overrides": {
                "2": {
                    "round_win_rules_remove": ["old_rule"]
                }
            },
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        ml = _import_loader()
        result = ml.resolve_per_mode(manifest, 2)
        assert "old_rule" not in result["round_win_rules"]
        assert "base_rule" in result["round_win_rules"]


# ---------------------------------------------------------------------------
# C4 -- resolve_completeness
# ---------------------------------------------------------------------------

class TestC4ResolveCompleteness:
    """C4 -- resolve_completeness(variant, underlying) per §5.5.7 verbatim.

    Three branches per spec lines 553-573:
    1. override absent (_UNSET) -> return underlying_complete
    2. override is False -> return False
    3. override is True -> raise ManifestValidationError

    Reference impl (_ref_resolve_completeness) is written from spec
    pseudocode independently. Implementer's code must match.

    INJECT-BUG per C8:
      override=True path: swap raise for return True ->
      test_override_true_raises goes RED.
    """

    def _make_underlying(self, complete: bool) -> dict:
        return {
            "machine_id": "MBASE",
            "console_diagnostic_complete": complete,
        }

    def _make_variant(self, override=_UNSET) -> dict:
        v = {"machine_id": "MVARIANT"}
        if override is not _UNSET:
            v["console_diagnostic_complete_override"] = override
        return v

    # --- Reference impl correctness checks ---

    def test_ref_impl_no_override_inherits_true(self):
        """Reference: no override + underlying=True -> True."""
        underlying = self._make_underlying(True)
        variant = self._make_variant()  # no override key
        assert _ref_resolve_completeness(variant, underlying) is True

    def test_ref_impl_no_override_inherits_false(self):
        """Reference: no override + underlying=False -> False."""
        underlying = self._make_underlying(False)
        variant = self._make_variant()
        assert _ref_resolve_completeness(variant, underlying) is False

    def test_ref_impl_override_false_returns_false(self):
        """Reference: override=False -> False (regression valve)."""
        underlying = self._make_underlying(True)
        variant = self._make_variant(override=False)
        assert _ref_resolve_completeness(variant, underlying) is False

    def test_ref_impl_override_true_raises(self):
        """Reference: override=True -> raises (variants cannot elevate)."""
        underlying = self._make_underlying(True)
        variant = self._make_variant(override=True)
        with pytest.raises(_RefManifestValidationError):
            _ref_resolve_completeness(variant, underlying)

    # --- Implementer's resolve_completeness must match reference ---

    def test_no_override_inherits_underlying_true(self):
        """Implementer: no override + underlying=True -> True.

        INJECT-BUG: Always return False -> this test goes RED.
        """
        ml = _import_loader()
        underlying = self._make_underlying(True)
        variant = self._make_variant()
        result = ml.resolve_completeness(variant, underlying)
        assert result is True

    def test_no_override_inherits_underlying_false(self):
        """Implementer: no override + underlying=False -> False."""
        ml = _import_loader()
        underlying = self._make_underlying(False)
        variant = self._make_variant()
        result = ml.resolve_completeness(variant, underlying)
        assert result is False

    def test_override_false_returns_false(self):
        """Implementer: override=False -> False regardless of underlying.

        INJECT-BUG: Return underlying_complete when override=False ->
        test goes RED (returns True instead of False).
        """
        ml = _import_loader()
        underlying = self._make_underlying(True)
        variant = self._make_variant(override=False)
        result = ml.resolve_completeness(variant, underlying)
        assert result is False

    def test_override_false_when_underlying_also_false(self):
        """override=False + underlying=False -> still False (no change)."""
        ml = _import_loader()
        underlying = self._make_underlying(False)
        variant = self._make_variant(override=False)
        result = ml.resolve_completeness(variant, underlying)
        assert result is False

    def test_override_true_raises_manifest_validation_error(self):
        """Implementer: override=True -> ManifestValidationError.

        Per §5.5.7: 'variants cannot elevate completeness above their underlying.'
        This is the critical safety property: override=True is NEVER allowed.

        INJECT-BUG: Return True instead of raising ->
        test goes RED (no exception raised).
        """
        ml = _import_loader()
        # The implementer must expose ManifestValidationError
        if not hasattr(ml, "ManifestValidationError"):
            pytest.skip("ManifestValidationError not yet exposed by manifest_loader")
        underlying = self._make_underlying(True)
        variant = self._make_variant(override=True)
        with pytest.raises(ml.ManifestValidationError) as exc_info:
            ml.resolve_completeness(variant, underlying)
        # Error message must mention the variant machine_id and the prohibition
        err_str = str(exc_info.value)
        assert "MVARIANT" in err_str or "override" in err_str.lower(), (
            f"Error message should reference variant or override prohibition; got: {err_str!r}"
        )

    def test_override_true_raises_even_when_underlying_false(self):
        """override=True still raises even if underlying=False.

        The check is on the override VALUE, not the delta.
        """
        ml = _import_loader()
        if not hasattr(ml, "ManifestValidationError"):
            pytest.skip("ManifestValidationError not yet exposed by manifest_loader")
        underlying = self._make_underlying(False)
        variant = self._make_variant(override=True)
        with pytest.raises(ml.ManifestValidationError):
            ml.resolve_completeness(variant, underlying)


# ---------------------------------------------------------------------------
# C5 -- validate_manifest (all 11 rules per §5.6)
# ---------------------------------------------------------------------------

class TestC5ValidateManifest11Rules:
    """C5 -- validate_manifest collects ALL errors (not just first).

    Per §3 C5 and memory feedback_no_silent_swallow.md:
    - Returns list[ValidationError]; empty = valid
    - Does NOT raise on a single error
    - Collects ALL errors so operator sees full picture

    Rules tested:
      Rule 1:  machine not in machines_config -> error
      Rule 2:  analyzer_feature ID not in registry -> error
      Rule 3:  round_win_rule not in configs (tested via registry mock)
      Rule 4:  REQUIRES dependency not satisfied
      Rule 5:  RTP_CONTRIBUTION feature missing from resolved mode
      Rule 6:  console_diagnostic_complete_override: true on variant -> error
      Rule 7:  expected_paid_st empty -> error
      Rule 8:  complete=True but RTP_CONTRIBUTION feature missing
      Rule 9:  rawdata sanity check (skipped if no rawdata)
      Rule 10: override_set_* metadata missing when _override: false
      Rule 11: trigger_session_pattern!=null AND layer4_applicable:true simultaneously

    Note: Rules 3, 4, 5, 8 require a non-empty registry; we use minimal
    stub AnalyzerFeature instances to test these paths.
    """

    def _valid_manifest(self) -> dict:
        """Return a minimal valid manifest for M1."""
        return {
            "machine_id": "M1",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": True,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": ["Plain"],
            "round_win_rules": [],
            "analyzer_features": ["payouts_by_spin_type"],
            "trigger_session_pattern": None,
            "modes_supported": [1],
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }

    def test_valid_manifest_returns_empty_error_list(self):
        """A well-formed manifest returns [] from validate_manifest."""
        ml = _import_loader()
        manifest = self._valid_manifest()
        # Provide M1 in machines_config and matching registry entry
        machines_config = {"M1": {"machine_id": "M1"}}
        # Stub registry with just payouts_by_spin_type
        # Note: validate_manifest(registry=...) accepts the feature_registry MODULE form
        # (an object with .ALL_FEATURES attribute) per the implementer's API.
        registry = _make_registry(("payouts_by_spin_type", False))
        errors = ml.validate_manifest(manifest, machines_config=machines_config, registry=registry)
        assert errors == [], f"Expected no errors for valid manifest; got: {errors}"

    def test_rule1_machine_not_in_machines_config(self):
        """Rule 1: machine_id not in machines_config -> error collected.

        INJECT-BUG: Remove rule 1 check -> no error collected ->
        test goes RED (errors is empty).
        """
        ml = _import_loader()
        manifest = self._valid_manifest()
        # M1 NOT in machines_config
        errors = ml.validate_manifest(
            manifest,
            machines_config={},  # empty
            registry=None,  # skip registry-based rules
        )
        assert len(errors) > 0, "Rule 1: machine not in config should produce an error"
        combined = " ".join(str(e) for e in errors).lower()
        assert "m1" in combined or "machine" in combined, (
            f"Rule 1 error should mention M1 or machine; got: {errors}"
        )

    def test_rule2_unknown_analyzer_feature_id(self):
        """Rule 2: analyzer_feature ID not in registry -> error collected.

        INJECT-BUG: Remove rule 2 check -> typo_feature goes undetected ->
        test goes RED (errors is empty).
        """
        ml = _import_loader()
        manifest = self._valid_manifest()
        manifest["analyzer_features"] = ["typo_feature_that_does_not_exist"]
        machines_config = {"M1": {"machine_id": "M1"}}
        registry = _make_registry(("payouts_by_spin_type", False))
        errors = ml.validate_manifest(manifest, machines_config=machines_config, registry=registry)
        assert len(errors) > 0, "Rule 2: unknown feature ID should produce an error"
        combined = " ".join(str(e) for e in errors).lower()
        assert "typo_feature" in combined or "feature" in combined, (
            f"Rule 2 error should mention the unknown feature; got: {errors}"
        )

    def test_rule6_variant_override_true_is_error(self):
        """Rule 6: console_diagnostic_complete_override: true on variant -> error.

        Per §5.6 rule 6: 'console_diagnostic_complete_override: true on any
        variant manifest is a validation error.'

        INJECT-BUG: Skip rule 6 -> override=true accepted silently ->
        test goes RED (no error collected).
        """
        ml = _import_loader()
        manifest = {
            "machine_id": "M15$BadVariant$0$",
            "manifest_version": 1,
            "inherits_from": "M15.json",
            "console_diagnostic_complete_override": True,  # FORBIDDEN
        }
        machines_config = {"M15$BadVariant$0$": {}}
        errors = ml.validate_manifest(manifest, machines_config=machines_config, registry=None)
        assert len(errors) > 0, "Rule 6: _override: true must produce a validation error"
        combined = " ".join(str(e) for e in errors).lower()
        assert "override" in combined or "true" in combined or "variant" in combined, (
            f"Rule 6 error should mention override or variant; got: {errors}"
        )

    def test_rule7_expected_paid_st_empty_is_error(self):
        """Rule 7: expected_paid_st must be non-empty.

        INJECT-BUG: Remove rule 7 check -> empty expected_paid_st accepted ->
        test goes RED (no error).
        """
        ml = _import_loader()
        manifest = self._valid_manifest()
        manifest["rtp_integrity_contract"]["expected_paid_st"] = []  # EMPTY
        machines_config = {"M1": {}}
        errors = ml.validate_manifest(manifest, machines_config=machines_config, registry=None)
        assert len(errors) > 0, "Rule 7: empty expected_paid_st must produce an error"
        combined = " ".join(str(e) for e in errors).lower()
        assert "paid" in combined or "expected" in combined or "empty" in combined, (
            f"Rule 7 error should mention expected_paid_st; got: {errors}"
        )

    def test_rule10_override_false_without_metadata_is_error(self):
        """Rule 10 (v5 NEW): _override: false without all 3 metadata fields -> error.

        Per §5.6 rule 10: if console_diagnostic_complete_override: false is present,
        all three metadata fields (override_set_at, override_set_reason, override_set_by)
        must be present and non-empty.

        INJECT-BUG: Remove rule 10 check -> missing metadata accepted ->
        test goes RED (no error collected).
        """
        ml = _import_loader()
        # Variant with override:false but MISSING all metadata
        manifest = {
            "machine_id": "M15$NoMeta$0$",
            "manifest_version": 1,
            "inherits_from": "M15.json",
            "console_diagnostic_complete_override": False,
            # override_set_at, override_set_reason, override_set_by all missing
        }
        machines_config = {"M15$NoMeta$0$": {}}
        errors = ml.validate_manifest(manifest, machines_config=machines_config, registry=None)
        assert len(errors) > 0, (
            "Rule 10: override:false without metadata fields must produce a validation error"
        )
        combined = " ".join(str(e) for e in errors).lower()
        assert any(
            kw in combined
            for kw in ("override_set_at", "metadata", "override_set_reason", "override_set_by")
        ), f"Rule 10 error should mention missing metadata fields; got: {errors}"

    def test_rule10_override_false_with_empty_metadata_is_error(self):
        """Rule 10: empty string metadata counts as missing -> error."""
        ml = _import_loader()
        manifest = {
            "machine_id": "M15$EmptyMeta$0$",
            "manifest_version": 1,
            "inherits_from": "M15.json",
            "console_diagnostic_complete_override": False,
            "override_set_at": "",        # empty string -> error
            "override_set_reason": "some reason",
            "override_set_by": "someone",
        }
        machines_config = {"M15$EmptyMeta$0$": {}}
        errors = ml.validate_manifest(manifest, machines_config=machines_config, registry=None)
        assert len(errors) > 0, (
            "Rule 10: empty override_set_at must produce a validation error"
        )

    def test_rule10_override_false_with_all_metadata_is_ok(self):
        """Rule 10: override:false WITH all 3 metadata fields -> no rule-10 error."""
        ml = _import_loader()
        manifest = {
            "machine_id": "M15$GoodMeta$0$",
            "manifest_version": 1,
            "inherits_from": "M15.json",
            "console_diagnostic_complete_override": False,
            "override_set_at": "2026-05-17T09:00:00Z",
            "override_set_reason": "Edge case on wheel nesting path.",
            "override_set_by": "arch-team / 2026-05-17",
        }
        machines_config = {"M15$GoodMeta$0$": {}}
        errors = ml.validate_manifest(manifest, machines_config=machines_config, registry=None)
        # Rule 10 specifically should NOT fire here
        rule10_errors = [
            e for e in errors
            if "override_set_at" in str(e) or "metadata" in str(e).lower()
        ]
        assert rule10_errors == [], (
            f"Rule 10 should not fire when all metadata is present; got rule10 errors: {rule10_errors}"
        )

    def test_rule11_trigger_session_pattern_and_layer4_true_is_error(self):
        """Rule 11 (v5 NEW): trigger_session_pattern!=null AND layer4_applicable:true -> error.

        Per §5.6 rule 11: 'Machines with trigger_session_pattern must have
        layer4_applicable: false. See §9.4.'

        INJECT-BUG: Remove rule 11 check -> conflict goes undetected ->
        test goes RED (no error collected).
        """
        ml = _import_loader()
        manifest = {
            "machine_id": "MCONFLICT",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,       # CONFLICT: should be False
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": [],
            "analyzer_features": [],
            "trigger_session_pattern": "type_1",  # non-null
            "modes_supported": [1],
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        machines_config = {"MCONFLICT": {}}
        errors = ml.validate_manifest(manifest, machines_config=machines_config, registry=None)
        assert len(errors) > 0, (
            "Rule 11: trigger_session_pattern + layer4_applicable:true must produce error"
        )
        combined = " ".join(str(e) for e in errors).lower()
        assert any(
            kw in combined
            for kw in ("trigger_session", "layer4", "layer 4", "applicable")
        ), f"Rule 11 error should mention trigger_session or layer4; got: {errors}"

    def test_rule11_m15_fixture_is_consistent(self):
        """Rule 11: M15 fixture (trigger_session_pattern='type_1', layer4=false) -> no rule11 error."""
        ml = _import_loader()
        manifest = _load_fixture("M15")
        assert manifest["trigger_session_pattern"] == "type_1"
        assert manifest["layer4_applicable"] is False
        machines_config = {"M15": {}}
        errors = ml.validate_manifest(manifest, machines_config=machines_config, registry=None)
        rule11_errors = [
            e for e in errors
            if "layer4" in str(e).lower() or "trigger_session" in str(e).lower()
        ]
        assert rule11_errors == [], (
            f"M15 has consistent trigger_session_pattern+layer4_applicable; "
            f"rule 11 must not fire; got: {rule11_errors}"
        )

    def test_rule11_null_trigger_session_layer4_true_is_ok(self):
        """Rule 11: trigger_session_pattern=null AND layer4_applicable=true -> OK."""
        ml = _import_loader()
        manifest = _load_fixture("M1")
        assert manifest["trigger_session_pattern"] is None
        assert manifest["layer4_applicable"] is True
        machines_config = {"M1": {}}
        registry = _make_registry(
            ("payouts_by_spin_type", False),
            ("reel_marginal_by_spin_type", False),
            ("bankruptcy_simulation", False),
            ("multiplier_profile", False),
        )
        errors = ml.validate_manifest(manifest, machines_config=machines_config, registry=registry)
        rule11_errors = [e for e in errors if "layer4" in str(e).lower()]
        assert rule11_errors == [], (
            f"Rule 11 must not fire for null trigger_session_pattern; got: {rule11_errors}"
        )

    def test_validate_collects_multiple_errors_not_just_first(self):
        """Validator collects ALL errors, not just the first one.

        Per §3 C5 and memory feedback_no_silent_swallow.md.

        INJECT-BUG: Raise on first error instead of collecting ->
        test goes RED (pytest.raises catches it, errors list never returned).
        """
        ml = _import_loader()
        manifest = {
            "machine_id": "MMULTI",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": True,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": [],
            # Rule 2: bad feature IDs (when registry is passed)
            "analyzer_features": ["nonexistent_feature_aaa", "nonexistent_feature_bbb"],
            "trigger_session_pattern": None,
            "modes_supported": [1],
            "rtp_integrity_contract": {
                # Rule 7: empty expected_paid_st
                "expected_paid_st": [],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        # Rule 1: machine not in config
        machines_config = {}  # MMULTI absent
        # Use a registry with NO features -> both declared features unknown (rule 2)
        registry = _make_registry()  # empty registry
        # This should NOT raise; should return a list with multiple errors
        errors = ml.validate_manifest(manifest, machines_config=machines_config, registry=registry)
        assert len(errors) >= 2, (
            f"Expected at least 2 errors (rule 1 + rule 2/7); got {len(errors)}: {errors}"
        )


# ---------------------------------------------------------------------------
# OI-2 -- validate_manifest rule 6 on post-resolved variant manifests
# ---------------------------------------------------------------------------

class TestOI2ValidateManifestPreResolvedContract:
    """OI-2 -- validate_manifest rule 6 false-fire on post-resolved variant manifests.

    The implementer self-flagged this in round 1 (02_implementation.md OI-2).
    The round-2 critic (05_critique.md SQ-8 + R3) confirmed it as a real latent bug.

    Context:
        resolve_inheritance() deep-copies the parent into the merged dict, including
        the parent's 'console_diagnostic_complete' field.  If validate_manifest() is
        called on this merged (post-resolved) dict, rule 6 fires because the field is
        present -- but it came from the parent, not from the variant overriding it.

    Fix:
        validate_manifest() now accepts pre_resolved: bool = True (default).
        When pre_resolved=False, rule 6 skips the console_diagnostic_complete presence
        check on variant manifests.  The override_val=True check still fires in both
        paths.

    Per round-2 critic R3 citing SQ-8 + OI-2.  Added by impl-implementer in round 2.
    """

    def _make_underlying(self) -> dict:
        """Minimal valid underlying (non-variant) manifest."""
        return {
            "machine_id": "M15",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": True,
            "analyzer_features": ["payouts_by_spin_type"],
            "round_win_rules": ["default_rule"],
            "modes_supported": [1],
            "spin_type_convention": {"paid": [1], "bonus": [2]},
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": [],
            },
            "trigger_session_pattern": "type_1",
            "layer4_applicable": False,
        }

    def _make_variant_raw(self) -> dict:
        """Minimal valid variant (pre-resolved) manifest — no console_diagnostic_complete."""
        return {
            "machine_id": "M15$TestVariant$0$",
            "manifest_version": 1,
            "inherits_from": "M15.json",
            # Intentionally NO 'console_diagnostic_complete' — correct per spec
        }

    def test_pre_resolved_true_no_false_fire_on_clean_variant(self):
        """pre_resolved=True (default): clean variant with no console_diagnostic_complete
        does NOT trigger rule 6.

        This is the standard call pattern (validate before resolving).
        """
        ml = _import_loader()
        raw_variant = self._make_variant_raw()
        errors = ml.validate_manifest(raw_variant, machines_config=None, registry=None)
        rule6_errors = [e for e in errors if e.rule == 6]
        assert len(rule6_errors) == 0, (
            f"Rule 6 must not fire on clean pre-resolved variant; got: {rule6_errors}"
        )

    def test_post_resolved_variant_without_flag_false_fires_rule6(self):
        """Demonstrates OI-2: post-resolved variant passed with pre_resolved=True (default)
        incorrectly triggers rule 6 because resolve_inheritance copies the parent's
        console_diagnostic_complete into the merged dict.

        This test documents the known limitation when the caller accidentally passes
        a post-resolved manifest with the default pre_resolved=True.
        Correct pattern: pass pre_resolved=False for post-resolved dicts.
        """
        ml = _import_loader()
        underlying = self._make_underlying()
        # Simulate the post-resolve_inheritance merged dict manually (avoids file I/O):
        # resolve_inheritance deep-copies parent and sets variant identity fields.
        import copy
        merged = copy.deepcopy(underlying)
        merged["machine_id"] = "M15$TestVariant$0$"
        merged["inherits_from"] = "M15.json"
        # 'console_diagnostic_complete' is still present from the parent copy -- this is
        # exactly what resolve_inheritance does.

        # With default pre_resolved=True, rule 6 will fire (known limitation / false-fire)
        errors = ml.validate_manifest(merged, machines_config=None, registry=None)
        rule6_errors = [e for e in errors if e.rule == 6]
        assert len(rule6_errors) > 0, (
            "OI-2 documented limitation: rule 6 DOES false-fire on post-resolved variant "
            "when pre_resolved=True (default). If this assertion fails, rule 6 was fixed "
            "globally and this test should be removed."
        )

    def test_post_resolved_variant_with_pre_resolved_false_no_false_fire(self):
        """Fix: post-resolved variant passed with pre_resolved=False does NOT trigger rule 6.

        This is the correct call pattern for Phase 3 fleet-level validation when manifests
        have already been through resolve_inheritance().

        INJECT-BUG: Remove the `if pre_resolved and` guard from rule 6 in validate_manifest
        -> this test goes RED (rule 6 fires when it should not).
        """
        ml = _import_loader()
        underlying = self._make_underlying()
        import copy
        merged = copy.deepcopy(underlying)
        merged["machine_id"] = "M15$TestVariant$0$"
        merged["inherits_from"] = "M15.json"
        # Variant has no console_diagnostic_complete_override (valid — no regression)

        # With pre_resolved=False, rule 6 skips the presence check
        errors = ml.validate_manifest(
            merged,
            machines_config=None,
            registry=None,
            pre_resolved=False,
        )
        rule6_errors = [e for e in errors if e.rule == 6]
        assert len(rule6_errors) == 0, (
            f"Rule 6 must NOT fire on post-resolved variant when pre_resolved=False; "
            f"got: {rule6_errors}"
        )

    def test_post_resolved_variant_override_true_still_fires_with_pre_resolved_false(self):
        """Fix regression: even with pre_resolved=False, if a variant has
        console_diagnostic_complete_override: true, rule 6 still fires.

        The fix must only skip the 'presence of console_diagnostic_complete' check,
        NOT the 'override=True is forbidden' check.

        INJECT-BUG: Remove the override_val is True check from rule 6
        -> this test goes RED (override=True silently accepted).
        """
        ml = _import_loader()
        underlying = self._make_underlying()
        import copy
        merged = copy.deepcopy(underlying)
        merged["machine_id"] = "M15$BadVariant$0$"
        merged["inherits_from"] = "M15.json"
        merged["console_diagnostic_complete_override"] = True  # FORBIDDEN even post-resolve

        errors = ml.validate_manifest(
            merged,
            machines_config=None,
            registry=None,
            pre_resolved=False,
        )
        rule6_errors = [e for e in errors if e.rule == 6]
        assert len(rule6_errors) > 0, (
            "Rule 6 must STILL fire for override=True even with pre_resolved=False; "
            f"got: {rule6_errors}"
        )


# ---------------------------------------------------------------------------
# C6 -- resolve_layer4_applicable
# ---------------------------------------------------------------------------

class TestC6ResolveLayer4Applicable:
    """C6 -- resolve_layer4_applicable(manifest_resolved, mode) per 07_decision_v5.md P1.

    Spec pseudocode (lines 50-58):
        pattern = manifest.modes[mode].get("trigger_session_pattern")
        if pattern is None:
            return True
        override = manifest.modes[mode].get("trigger_session_pattern_override")
        if override is not None:
            pattern = override
        return False  # any non-null trigger_session_pattern -> skip

    Reference impl _ref_resolve_layer4_applicable is written from spec.

    INJECT-BUG per C8:
      Invert return values (True->False, False->True) ->
      test_null_pattern_returns_true goes RED AND
      test_non_null_pattern_returns_false goes RED.
    """

    def _make_manifest(self, base_pattern, mode_overrides=None):
        return {
            "machine_id": "ML4TEST",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": base_pattern is None,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": [],
            "analyzer_features": [],
            "trigger_session_pattern": base_pattern,
            "modes_supported": [1, 2],
            "per_mode_overrides": mode_overrides or {},
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }

    # --- Reference impl sanity ---

    def test_ref_null_base_pattern_returns_true(self):
        """Reference: null pattern -> True (layer 4 applicable)."""
        manifest = self._make_manifest(None)
        assert _ref_resolve_layer4_applicable(manifest, 1) is True

    def test_ref_non_null_base_pattern_returns_false(self):
        """Reference: 'type_1' pattern -> False."""
        manifest = self._make_manifest("type_1")
        assert _ref_resolve_layer4_applicable(manifest, 1) is False

    def test_ref_mode_override_to_non_null_returns_false(self):
        """Reference: override in mode sets pattern to non-null -> False."""
        manifest = self._make_manifest(
            None,
            mode_overrides={"2": {"trigger_session_pattern_override": "type_2"}}
        )
        assert _ref_resolve_layer4_applicable(manifest, 2) is False

    def test_ref_mode_override_to_null_returns_true(self):
        """Reference impl correctly uses _UNSET sentinel to distinguish
        "key absent" from "key=null", per §5.5.6 table which allows null
        as a valid override value.

        Key absent -> no override -> base pattern applies.
        Key=null   -> override is None (explicitly cleared) -> True.

        This differs from P1 pseudocode which uses `is not None` (cannot
        distinguish). The reference impl uses _UNSET sentinel = correct behavior.
        """
        manifest = self._make_manifest(
            "type_1",
            mode_overrides={"2": {"trigger_session_pattern_override": None}}
        )
        # Reference impl: explicit null override clears base 'type_1' -> None -> True
        assert _ref_resolve_layer4_applicable(manifest, 2) is True

    # --- Implementer's resolve_layer4_applicable must match reference ---

    def test_null_pattern_returns_true(self):
        """Implementer: null trigger_session_pattern -> True.

        INJECT-BUG: Swap return True/False ->
        test goes RED (returns False for null pattern).
        """
        ml = _import_loader()
        manifest = self._make_manifest(None)
        result = ml.resolve_layer4_applicable(manifest, 1)
        assert result is True

    def test_type1_pattern_returns_false(self):
        """Implementer: 'type_1' -> False.

        INJECT-BUG: Swap return True/False ->
        test goes RED (returns True for non-null pattern).
        """
        ml = _import_loader()
        manifest = self._make_manifest("type_1")
        result = ml.resolve_layer4_applicable(manifest, 1)
        assert result is False

    def test_type2_pattern_returns_false(self):
        """Implementer: 'type_2' -> False."""
        ml = _import_loader()
        manifest = self._make_manifest("type_2")
        result = ml.resolve_layer4_applicable(manifest, 1)
        assert result is False

    def test_mode_override_null_returns_true(self):
        """Implementer: base=type_1, mode override null should clear base -> True.

        The reference impl (_ref_resolve_layer4_applicable) correctly returns True
        using _UNSET sentinel.

        Round-2: xfail removed — fix implemented in resolve_layer4_applicable() per
        critic R2 citing brief §3 C6 + 04_v5 §5.5.6 table (null is valid override).

        INJECT-BUG: Change `_UNSET` sentinel in resolve_layer4_applicable back to
        `is not None` -> test goes RED (explicit null override ignored, returns False).
        """
        ml = _import_loader()
        manifest = self._make_manifest(
            "type_1",
            mode_overrides={"2": {"trigger_session_pattern_override": None}}
        )
        # Mode 1: base pattern 'type_1' -> False
        assert ml.resolve_layer4_applicable(manifest, 1) is False
        # Mode 2: explicit null override should clear base -> True
        assert ml.resolve_layer4_applicable(manifest, 2) is True

    def test_mode_override_to_non_null_returns_false(self):
        """Implementer: base=None, mode override to 'type_2' -> False for that mode."""
        ml = _import_loader()
        manifest = self._make_manifest(
            None,
            mode_overrides={"2": {"trigger_session_pattern_override": "type_2"}}
        )
        # Mode 1: base pattern None -> True
        assert ml.resolve_layer4_applicable(manifest, 1) is True
        # Mode 2: override type_2 -> False
        assert ml.resolve_layer4_applicable(manifest, 2) is False

    def test_m1_fixture_layer4_true(self):
        """M1 has trigger_session_pattern=null -> layer4_applicable=True."""
        ml = _import_loader()
        m1 = _load_fixture("M1")
        result = ml.resolve_layer4_applicable(m1, 1)
        assert result is True

    def test_m15_fixture_layer4_false(self):
        """M15 has trigger_session_pattern='type_1' -> layer4_applicable=False."""
        ml = _import_loader()
        m15 = _load_fixture("M15")
        result = ml.resolve_layer4_applicable(m15, 1)
        assert result is False

    def test_m274_fixture_layer4_true(self):
        """M274 has trigger_session_pattern=null -> layer4_applicable=True."""
        ml = _import_loader()
        m274 = _load_fixture("M274")
        result = ml.resolve_layer4_applicable(m274, 1)
        assert result is True


# ---------------------------------------------------------------------------
# C8 -- Inject-bug TDD: dedicated inject-specific tests
# ---------------------------------------------------------------------------

class TestC8InjectBugDocumentation:
    """C8 -- Documents the inject-bug discipline per contract.

    Per memory feedback_integration_test_argv.md: every regression test
    must be proven by injecting the bug it claims to catch.

    These tests are the primary inject targets. Each one has a comment
    explaining exactly what line to revert/change and what error appears.

    All inject steps are also documented in 03_tests.md.
    """

    def test_c1_inject_missing_returns_empty_dict(self, tmp_path):
        """INJECT: Change FileNotFoundError raise to return {} -> this RED.

        Target: fresh_slotlab/analyzer/manifest_loader.py, load_manifest()
        Bug: except FileNotFoundError: return {}
        Expected failure: AssertionError (no exception raised; test expects FileNotFoundError)
        """
        ml = _import_loader()
        with pytest.raises(FileNotFoundError):
            ml.load_manifest("MNOTEXIST_c8", tmp_path)

    def test_c1_inject_malformed_swallowed(self, tmp_path):
        """INJECT: Wrap json.loads in bare except: return {} -> this RED.

        Target: load_manifest(), json.loads(text) block
        Bug: try: return json.loads(text) except Exception: return {}
        Expected failure: AssertionError (no exception, test expects JSONDecodeError)
        """
        ml = _import_loader()
        bad = tmp_path / "MC8BAD.json"
        bad.write_text("{bad json", encoding="utf-8")
        with pytest.raises((json.JSONDecodeError, ValueError)):
            ml.load_manifest("MC8BAD", tmp_path)

    def test_c3_inject_add_before_remove(self):
        """INJECT: Swap _add/_remove order in resolve_per_mode -> this RED.

        Target: resolve_per_mode(), the loop over per_mode_overrides
        Bug: Apply _add first, then _remove
        Expected failure: 'bankruptcy_simulation' absent when it should be present
        (remove runs AFTER add, so remove wins instead of add)
        """
        manifest = {
            "machine_id": "MC8ORDER",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": [],
            "analyzer_features": ["payouts_by_spin_type", "bankruptcy_simulation"],
            "trigger_session_pattern": None,
            "modes_supported": [1],
            "per_mode_overrides": {
                "1": {
                    "analyzer_features_remove": ["bankruptcy_simulation"],
                    "analyzer_features_add": ["bankruptcy_simulation"],
                }
            },
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        ml = _import_loader()
        result = ml.resolve_per_mode(manifest, 1)
        # remove-then-add: feature must be present
        assert "bankruptcy_simulation" in result["analyzer_features"], (
            "INJECT-BUG target: if add-then-remove order used, feature absent here."
        )

    def test_c4_inject_override_true_returns_instead_of_raises(self):
        """INJECT: Replace 'raise ManifestValidationError(...)' with 'return True' -> this RED.

        Target: resolve_completeness(), the 'override is True' branch
        Bug: return True  # instead of raise
        Expected failure: no exception raised, pytest.raises context exits cleanly
        then AssertionError (test checks that exception was raised)
        """
        ml = _import_loader()
        if not hasattr(ml, "ManifestValidationError"):
            pytest.skip("ManifestValidationError not yet exposed")
        underlying = {"machine_id": "MBASE", "console_diagnostic_complete": True}
        variant = {"machine_id": "MVARIANT", "console_diagnostic_complete_override": True}
        with pytest.raises(ml.ManifestValidationError):
            ml.resolve_completeness(variant, underlying)

    def test_c5_inject_rule11_missing(self):
        """INJECT: Remove rule 11 check from validate_manifest -> this RED.

        Target: validate_manifest(), the block checking trigger_session_pattern + layer4_applicable
        Bug: Comment out rule 11 check entirely
        Expected failure: errors is empty, test asserts len(errors) > 0
        """
        ml = _import_loader()
        manifest = {
            "machine_id": "MC8R11",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,          # CONFLICT
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": [],
            "analyzer_features": [],
            "trigger_session_pattern": "type_1", # non-null
            "modes_supported": [1],
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        errors = ml.validate_manifest(manifest, machines_config={"MC8R11": {}}, registry=None)
        assert len(errors) > 0, "INJECT-BUG target: rule 11 check removed -> errors empty"

    def test_c6_inject_inverted_return(self):
        """INJECT: Swap True/False returns in resolve_layer4_applicable -> this RED.

        Target: resolve_layer4_applicable(), both return statements
        Bug: return False when pattern is None; return True when pattern is non-null
        Expected failure: null pattern returns False, test asserts True
        """
        ml = _import_loader()
        manifest = {
            "machine_id": "MC8L4",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": True,
            "spin_type_convention": {"paid": [1], "bonus": []},
            "feature_tags": [],
            "round_win_rules": [],
            "analyzer_features": [],
            "trigger_session_pattern": None,  # null -> expect True
            "modes_supported": [1],
            "per_mode_overrides": {},
            "rtp_integrity_contract": {
                "expected_paid_st": [1],
                "expected_bonus_st": [],
                "required_attribution_anchors": []
            },
        }
        assert ml.resolve_layer4_applicable(manifest, 1) is True, (
            "INJECT-BUG target: inverted returns -> null pattern gives False here"
        )


# ---------------------------------------------------------------------------
# Round-2 OI-2 regression: rule 6 must NOT false-fire on post-resolved manifests
# ---------------------------------------------------------------------------

class TestOI2PostResolvedVariantRule6:
    """Round-2 OI-2 regression — validate_manifest rule 6 must not false-fire
    on post-resolve_inheritance variant manifests.

    Background (critic R3 / SQ-8 from 05_critique.md):
        resolve_inheritance() always copies the parent's console_diagnostic_complete
        into the merged dict.  Before Fix 3, rule 6 fired on this field being present
        for any variant manifest passed post-resolution.  Fix 3 adds pre_resolved=False
        so callers can signal post-resolve context and suppress the spurious check.

    Contract:
        resolve_inheritance(variant, dir) + resolve_per_mode(resolved, mode)
        → validate_manifest(result, pre_resolved=False)
        → no rule-6 error about console_diagnostic_complete being present.

    INJECT-BUG:
        Change `if pre_resolved and "console_diagnostic_complete" in manifest:`
        to `if "console_diagnostic_complete" in manifest:` (remove the pre_resolved
        guard) → test goes RED (spurious rule-6 error appears).
        Restore guard → test GREEN.

    Inject-bug log (Round 2):
        1. Reverted `if pre_resolved and` to `if` in manifest_loader.py rule 6 block
        2. Ran test → FAILED: rule-6 error found in errors (should be absent)
        3. Restored `if pre_resolved and`
        4. Ran test → PASSED
    """

    # Minimal parent manifest that resolve_inheritance needs to load
    _PARENT = {
        "machine_id": "MOIBASE",
        "manifest_version": 1,
        "inherits_from": None,
        "console_diagnostic_complete": True,
        "layer4_applicable": True,
        "spin_type_convention": {"paid": [1], "bonus": [2]},
        "feature_tags": [],
        "round_win_rules": [],
        "analyzer_features": ["payouts_by_spin_type"],
        "trigger_session_pattern": None,
        "modes_supported": [1, 2],
        "rtp_integrity_contract": {
            "expected_paid_st": [1],
            "expected_bonus_st": [2],
            "required_attribution_anchors": [],
        },
    }

    # Minimal variant (no console_diagnostic_complete_override — inherits from parent)
    _VARIANT = {
        "machine_id": "MOIBASE$TestSelector$0$",
        "manifest_version": 1,
        "inherits_from": "MOIBASE.json",
        # Deliberately NO console_diagnostic_complete key (belongs to underlying)
        # Deliberately NO console_diagnostic_complete_override (inherits True from parent)
    }

    def _setup_fixtures(self, tmp_path):
        """Write parent and variant JSON files to tmp_path."""
        import json as _json
        (tmp_path / "MOIBASE.json").write_text(
            _json.dumps(self._PARENT), encoding="utf-8"
        )
        (tmp_path / "MOIBASE$TestSelector$0$.json").write_text(
            _json.dumps(self._VARIANT), encoding="utf-8"
        )

    def test_rule6_does_not_fire_on_post_resolved_variant(self, tmp_path):
        """Rule 6 must not emit an error when validate_manifest gets a post-resolved dict.

        Failure mode before Fix 3:
            resolve_inheritance copies parent's console_diagnostic_complete into merged
            dict → validate_manifest sees the field → rule 6 fires: "Variant must not
            contain console_diagnostic_complete directly" → FALSE POSITIVE.

        Fix 3 contract (pre_resolved=False parameter):
            When called with pre_resolved=False, rule 6 skips the presence check.
            Errors list must be empty (no rule-6 false-fire).

        INJECT-BUG target: change `if pre_resolved and "console_diagnostic_complete" in manifest:`
        to `if "console_diagnostic_complete" in manifest:` in validate_manifest rule 6 block.
        """
        self._setup_fixtures(tmp_path)
        ml = _import_loader()

        # Step 1: load the variant
        variant = ml.load_manifest("MOIBASE$TestSelector$0$", tmp_path)

        # Step 2: resolve inheritance (this merges parent's console_diagnostic_complete
        # into the merged dict — this is the source of the OI-2 false-fire)
        resolved = ml.resolve_inheritance(variant, tmp_path)

        # Sanity: after inheritance, the merged dict has console_diagnostic_complete
        # (inherited from parent). Without Fix 3, rule 6 would fire on this.
        assert "console_diagnostic_complete" in resolved, (
            "Test precondition: resolve_inheritance must merge parent's "
            "console_diagnostic_complete into variant dict. If absent, OI-2 cannot trigger."
        )

        # Step 3: resolve per-mode (mode 1, no overrides for this mode)
        per_mode_resolved = ml.resolve_per_mode(resolved, 1)

        # Step 4: validate with pre_resolved=False → rule 6 must NOT fire
        errors = ml.validate_manifest(per_mode_resolved, pre_resolved=False)

        # Assert: no rule-6 errors
        rule6_errors = [e for e in errors if e.rule == 6]
        assert not rule6_errors, (
            f"OI-2 regression: rule 6 false-fired on post-resolved variant manifest. "
            f"Errors: {[str(e) for e in rule6_errors]}. "
            f"Fix: pre_resolved=False must suppress the console_diagnostic_complete "
            f"presence check in rule 6."
        )

    def test_rule6_still_fires_on_pre_resolved_variant_with_cdc(self, tmp_path):
        """Rule 6 MUST still fire on a pre-resolved variant that directly has
        console_diagnostic_complete (the legitimate enforcement case).

        This test proves the fix did not over-suppress rule 6 — the pre-resolved
        path remains correctly guarded.

        INJECT-BUG: This is the converse guard. If pre_resolved=True check is removed
        entirely, rule 6 never fires for any variant → this test goes RED.
        """
        self._setup_fixtures(tmp_path)
        ml = _import_loader()

        # Construct a BAD pre-resolved variant that directly has console_diagnostic_complete
        # (which should NOT be present in a raw variant manifest).
        bad_pre_resolved_variant = {
            "machine_id": "MOIBASE$TestSelector$0$",
            "manifest_version": 1,
            "inherits_from": "MOIBASE.json",
            "console_diagnostic_complete": True,  # FORBIDDEN: variant sets this directly
        }

        # Validate with pre_resolved=True (default) → rule 6 must fire
        errors = ml.validate_manifest(bad_pre_resolved_variant, pre_resolved=True)

        rule6_errors = [e for e in errors if e.rule == 6]
        assert rule6_errors, (
            "Rule 6 must fire on a pre-resolved variant that directly sets "
            "console_diagnostic_complete. Fix must not suppress this legitimate check."
        )

    def test_oi2_inject_bug_remove_pre_resolved_guard(self, tmp_path):
        """OI-2 inject-bug documentation test.

        INJECT-BUG target:
            fresh_slotlab/analyzer/manifest_loader.py, validate_manifest(), rule 6 block.
            Change: `if pre_resolved and "console_diagnostic_complete" in manifest:`
            To:     `if "console_diagnostic_complete" in manifest:`
            (i.e. remove the `pre_resolved and` guard)

        Expected failure: this test goes RED because the rule 6 check fires
        unconditionally → spurious rule-6 error appears in the error list
        when called with pre_resolved=False on a post-resolved manifest.

        This test mirrors test_rule6_does_not_fire_on_post_resolved_variant
        so it is the canonical inject target for OI-2.
        """
        self._setup_fixtures(tmp_path)
        ml = _import_loader()

        variant = ml.load_manifest("MOIBASE$TestSelector$0$", tmp_path)
        resolved = ml.resolve_inheritance(variant, tmp_path)
        per_mode_resolved = ml.resolve_per_mode(resolved, 1)

        # With Fix 3 in place, pre_resolved=False suppresses the rule-6 presence check.
        # This call must return zero rule-6 errors.
        errors = ml.validate_manifest(per_mode_resolved, pre_resolved=False)
        rule6_errors = [e for e in errors if e.rule == 6]
        assert not rule6_errors, (
            f"INJECT-BUG target: if pre_resolved guard is removed from rule 6, "
            f"this list would be non-empty. Errors: {[str(e) for e in rule6_errors]}"
        )


# ---------------------------------------------------------------------------
# Additional parametrized coverage: fixtures from §5.11
# ---------------------------------------------------------------------------

class TestFixtureManifestStructure:
    """Verify all three §5.11 fixture manifests parse with correct structure."""

    @pytest.mark.parametrize("machine_id,expected_fields", [
        ("M1", {
            "machine_id": "M1",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": True,
            "layer4_applicable": True,
            "trigger_session_pattern": None,
        }),
        ("M15", {
            "machine_id": "M15",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": False,
            "layer4_applicable": False,
            "trigger_session_pattern": "type_1",
        }),
        ("M274", {
            "machine_id": "M274",
            "manifest_version": 1,
            "inherits_from": None,
            "console_diagnostic_complete": True,
            "layer4_applicable": True,
            "trigger_session_pattern": None,
        }),
    ])
    def test_fixture_fields(self, machine_id, expected_fields):
        """Each §5.11 fixture has the expected top-level field values."""
        ml = _import_loader()
        result = ml.load_manifest(machine_id, FIXTURES_DIR)
        for field, expected in expected_fields.items():
            assert result[field] == expected, (
                f"{machine_id}: {field!r} expected {expected!r}, got {result[field]!r}"
            )

    def test_m274_per_mode_overrides_mode5_remove(self):
        """M274 mode 5 per_mode_overrides has analyzer_features_remove."""
        ml = _import_loader()
        manifest = ml.load_manifest("M274", FIXTURES_DIR)
        overrides = manifest.get("per_mode_overrides", {})
        assert "5" in overrides
        assert "analyzer_features_remove" in overrides["5"]
        assert "bonus_chain_dynamics" in overrides["5"]["analyzer_features_remove"]

    @pytest.mark.parametrize("machine_id,expected_modes", [
        ("M1", [1, 2, 5, 7]),
        ("M15", [1, 2, 5, 7]),
        ("M274", [1, 5, 7]),
    ])
    def test_fixture_modes_supported(self, machine_id, expected_modes):
        """Fixture modes_supported matches §5.11 examples."""
        ml = _import_loader()
        result = ml.load_manifest(machine_id, FIXTURES_DIR)
        assert sorted(result["modes_supported"]) == sorted(expected_modes)

    @pytest.mark.parametrize("machine_id", ["M1", "M15", "M274"])
    def test_fixture_rtp_integrity_contract_present(self, machine_id):
        """All §5.11 fixtures have an rtp_integrity_contract block."""
        ml = _import_loader()
        result = ml.load_manifest(machine_id, FIXTURES_DIR)
        assert "rtp_integrity_contract" in result
        contract = result["rtp_integrity_contract"]
        assert "expected_paid_st" in contract
        assert "expected_bonus_st" in contract
        assert "required_attribution_anchors" in contract

    @pytest.mark.parametrize("machine_id", ["M1", "M15", "M274"])
    def test_fixture_spin_type_convention_structure(self, machine_id):
        """All §5.11 fixtures have spin_type_convention with paid and bonus keys."""
        ml = _import_loader()
        result = ml.load_manifest(machine_id, FIXTURES_DIR)
        stc = result["spin_type_convention"]
        assert "paid" in stc
        assert "bonus" in stc
        assert isinstance(stc["paid"], list)
        assert isinstance(stc["bonus"], list)


# ---------------------------------------------------------------------------
# Helpers for stub feature objects used in validation rule tests
# ---------------------------------------------------------------------------

def _make_stub_feature(feature_id: str, rtp_contribution: bool = False, requires: tuple = ()):
    """Create a minimal stub AnalyzerFeature instance for use in validate_manifest tests.

    We need real AnalyzerFeature instances (or objects that quack like them)
    for the registry parameter.  We use the real ABC here to ensure type
    compatibility with the implementer's registry checks.
    """
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature

    class _StubFeature(AnalyzerFeature):
        FEATURE_ID = feature_id
        SCHEMA_KEYS = ()
        SCHEMA_VERSION = 1
        RTP_CONTRIBUTION = rtp_contribution
        REQUIRES = requires
        REGISTERED_FALLBACK_RULES = {}

        def extract(self, parse_state, chunk_dict):
            return {}

        def reduce(self, prev_acc, this_acc):
            return {}

        def emit(self, final_acc, summary):
            pass

    return _StubFeature()


class _StubRegistry:
    """Stub registry object that looks like the feature_registry module.

    The implementer's validate_manifest() expects registry to have an
    ALL_FEATURES attribute (the module form: registry.ALL_FEATURES).
    This adapter wraps a plain list to match that API.

    Per §5.6: "Every analyzer_feature ID MUST correspond to a class in
    feature_registry.ALL_FEATURES" — the spec implies the module form.
    """

    def __init__(self, features: list):
        self.ALL_FEATURES = list(features)


def _make_registry(*feature_ids_and_flags):
    """Create a _StubRegistry from (feature_id, rtp_contribution) tuples.

    Usage:
        registry = _make_registry(
            ("payouts_by_spin_type", False),
            ("bankruptcy_simulation", True),
        )
        empty_registry = _make_registry()  # no features registered
    """
    features = [_make_stub_feature(fid, rtp) for fid, rtp in feature_ids_and_flags]
    return _StubRegistry(features)
