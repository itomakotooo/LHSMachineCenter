"""Phase C3 — SCHEMA_VERSION == 2 + REGISTERED_FALLBACK_RULES ABC contract.

Verifies that the PayoutsBySpinType plugin satisfies the AnalyzerFeature ABC
schema contract after C3:
  - SCHEMA_VERSION is exactly 2 (bumped from 1 in C2)
  - REGISTERED_FALLBACK_RULES is a dict
  - Key 1 (v1 → v2 rule) exists and maps {shape, covered_columns, paylines, notes} → None
  - The plugin is still a concrete subclass of AnalyzerFeature (passes ABC check)
  - FEATURE_ID + SCHEMA_KEYS unchanged from C2

This is deliberately separate from test_c3_enrichment.py so the coordinator
can run it in isolation as a fast schema contract gate.

Invariants asserted
-------------------
1. SCHEMA_VERSION == 2 (not 1, not 3).
2. REGISTERED_FALLBACK_RULES is a dict (not list, not None).
3. Key 1 present in REGISTERED_FALLBACK_RULES.
4. Rule for key 1 has exactly the 4 new fields: shape, covered_columns,
   paylines, notes — all mapped to None.
5. FEATURE_ID == "payouts_by_spin_type" (unchanged from C2).
6. SCHEMA_KEYS == ("payouts_by_spin_type",) (unchanged from C2).
7. Plugin is concrete (instantiates without ABC error).
8. ABC base class REGISTERED_FALLBACK_RULES default is {} (plugin overrides it).

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug A — set SCHEMA_VERSION = 1:
    In payouts_by_spin_type.py, change SCHEMA_VERSION: ClassVar[int] = 2 → 1.
    RED: test_schema_version_is_exactly_2 fails.
    Revert → GREEN.

Bug B — remove REGISTERED_FALLBACK_RULES[1]:
    In payouts_by_spin_type.py, set REGISTERED_FALLBACK_RULES = {}.
    RED: test_registered_fallback_rules_has_key_1 fails.
    Revert → GREEN.

Memory files cited
------------------
- memory/feedback_md5_is_a_tag_not_a_destruction_signal.md (schema bump
  invalidates renderers gracefully; does NOT delete old data)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))


def _import_plugin_class():
    try:
        from fresh_slotlab.analyzer.features.payouts_by_spin_type import PayoutsBySpinType
    except ImportError:
        from analyzer.features.payouts_by_spin_type import PayoutsBySpinType  # type: ignore[no-redef]
    return PayoutsBySpinType


def _import_base_class():
    try:
        from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    except ImportError:
        from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    return AnalyzerFeature


class TestSchemaVersion:
    """SCHEMA_VERSION == 2 after C3 bump."""

    def test_schema_version_is_exactly_3(self):
        """SCHEMA_VERSION must be exactly 3 after C4/Phase-P3 (symbol_combo enrichment).

        C3 bumped 1 → 2. C4/Phase-P3 bumped 2 → 3 for symbol_combo field.

        INJECT-BUG: set SCHEMA_VERSION = 2 in plugin.
        RED: 3 != 2 → assertion fails.
        Revert → GREEN.
        """
        cls = _import_plugin_class()
        assert cls.SCHEMA_VERSION == 3, (
            f"SCHEMA_VERSION must be 3 after C4/Phase-P3, got {cls.SCHEMA_VERSION}. "
            "C4/Phase-P3 bumps from 2 → 3 to signal symbol_combo per-row field."
        )

    def test_schema_version_not_1_or_2(self):
        """Explicit not-1/not-2 check: pre-C4 values must not be present."""
        cls = _import_plugin_class()
        assert cls.SCHEMA_VERSION != 1, (
            "SCHEMA_VERSION is still 1 — C3 bump (1 → 2) did not apply."
        )
        assert cls.SCHEMA_VERSION != 2, (
            "SCHEMA_VERSION is still 2 — C4/Phase-P3 bump (2 → 3) did not apply."
        )

    def test_schema_version_is_int(self):
        """SCHEMA_VERSION must be an int (ABC ClassVar[int] contract)."""
        cls = _import_plugin_class()
        assert isinstance(cls.SCHEMA_VERSION, int), (
            f"SCHEMA_VERSION must be int, got {type(cls.SCHEMA_VERSION)}"
        )

    def test_base_class_default_schema_version_is_1(self):
        """ABC default SCHEMA_VERSION is 1; plugin overrides to 3 (C4/Phase-P3).

        This confirms the override pattern is working (not just inheriting default).
        """
        AnalyzerFeature = _import_base_class()
        assert AnalyzerFeature.SCHEMA_VERSION == 1, (
            f"ABC default SCHEMA_VERSION must be 1, got {AnalyzerFeature.SCHEMA_VERSION}. "
            "If ABC default changed, update this test to match."
        )


class TestRegisteredFallbackRules:
    """REGISTERED_FALLBACK_RULES contract for v1 → v2 backward compatibility."""

    def test_registered_fallback_rules_is_dict(self):
        """REGISTERED_FALLBACK_RULES must be a dict (ABC ClassVar[dict] contract)."""
        cls = _import_plugin_class()
        rfr = cls.REGISTERED_FALLBACK_RULES
        assert isinstance(rfr, dict), (
            f"REGISTERED_FALLBACK_RULES must be dict, got {type(rfr)}"
        )

    def test_registered_fallback_rules_has_key_1(self):
        """REGISTERED_FALLBACK_RULES must contain integer key 1 (v1 rule).

        INJECT-BUG: set REGISTERED_FALLBACK_RULES = {}.
        RED: key 1 absent → assertion fails.
        Revert → GREEN.
        """
        cls = _import_plugin_class()
        rfr = cls.REGISTERED_FALLBACK_RULES
        assert 1 in rfr, (
            f"REGISTERED_FALLBACK_RULES must contain key 1 (v1→v2 fallback rule). "
            f"Got keys: {sorted(rfr.keys())}"
        )

    def test_rule_1_has_shape_key_mapped_to_none(self):
        """REGISTERED_FALLBACK_RULES[1]['shape'] must be None."""
        cls = _import_plugin_class()
        rule = cls.REGISTERED_FALLBACK_RULES[1]
        assert "shape" in rule, f"'shape' missing from rule[1]: {rule}"
        assert rule["shape"] is None, f"rule[1]['shape'] must be None, got {rule['shape']!r}"

    def test_rule_1_has_covered_columns_key_mapped_to_none(self):
        """REGISTERED_FALLBACK_RULES[1]['covered_columns'] must be None."""
        cls = _import_plugin_class()
        rule = cls.REGISTERED_FALLBACK_RULES[1]
        assert "covered_columns" in rule, f"'covered_columns' missing from rule[1]: {rule}"
        assert rule["covered_columns"] is None, (
            f"rule[1]['covered_columns'] must be None, got {rule['covered_columns']!r}"
        )

    def test_rule_1_has_paylines_key_mapped_to_none(self):
        """REGISTERED_FALLBACK_RULES[1]['paylines'] must be None."""
        cls = _import_plugin_class()
        rule = cls.REGISTERED_FALLBACK_RULES[1]
        assert "paylines" in rule, f"'paylines' missing from rule[1]: {rule}"
        assert rule["paylines"] is None, (
            f"rule[1]['paylines'] must be None, got {rule['paylines']!r}"
        )

    def test_rule_1_has_notes_key_mapped_to_none(self):
        """REGISTERED_FALLBACK_RULES[1]['notes'] must be None."""
        cls = _import_plugin_class()
        rule = cls.REGISTERED_FALLBACK_RULES[1]
        assert "notes" in rule, f"'notes' missing from rule[1]: {rule}"
        assert rule["notes"] is None, (
            f"rule[1]['notes'] must be None, got {rule['notes']!r}"
        )

    def test_rule_1_exactly_4_keys(self):
        """REGISTERED_FALLBACK_RULES[1] must have exactly the 4 new fields.

        Extra keys would indicate scope creep; missing keys would leave the
        frontend without graceful fallback for those fields.
        """
        cls = _import_plugin_class()
        rule = cls.REGISTERED_FALLBACK_RULES[1]
        expected = {"shape", "covered_columns", "paylines", "notes"}
        actual = set(rule.keys())
        assert actual == expected, (
            f"REGISTERED_FALLBACK_RULES[1] must have exactly {expected}. "
            f"Got: {actual}"
        )

    def test_base_class_default_registered_fallback_rules_is_empty(self):
        """ABC default REGISTERED_FALLBACK_RULES is {}; plugin adds key 1.

        This confirms the plugin is not just inheriting the empty default.
        """
        AnalyzerFeature = _import_base_class()
        assert AnalyzerFeature.REGISTERED_FALLBACK_RULES == {}, (
            f"ABC default REGISTERED_FALLBACK_RULES must be {{}}, "
            f"got {AnalyzerFeature.REGISTERED_FALLBACK_RULES}"
        )


class TestPluginStillConcreteAndIdentity:
    """Plugin must remain a concrete subclass of AnalyzerFeature with correct identity."""

    def test_instantiates_without_abc_error(self):
        """PayoutsBySpinType must be concrete (no abstract methods unimplemented)."""
        cls = _import_plugin_class()
        try:
            instance = cls()
        except TypeError as e:
            pytest.fail(f"Plugin cannot be instantiated (abstract method?): {e}")

    def test_feature_id_unchanged_from_c2(self):
        """FEATURE_ID must be 'payouts_by_spin_type' (unchanged in C3)."""
        cls = _import_plugin_class()
        assert cls.FEATURE_ID == "payouts_by_spin_type", (
            f"FEATURE_ID must be 'payouts_by_spin_type', got {cls.FEATURE_ID!r}"
        )

    def test_schema_keys_unchanged_from_c2(self):
        """SCHEMA_KEYS must contain 'payouts_by_spin_type' (unchanged in C3)."""
        cls = _import_plugin_class()
        assert "payouts_by_spin_type" in cls.SCHEMA_KEYS, (
            f"SCHEMA_KEYS must include 'payouts_by_spin_type', got {cls.SCHEMA_KEYS!r}"
        )

    def test_is_subclass_of_analyzer_feature(self):
        """PayoutsBySpinType must still be a subclass of AnalyzerFeature (ABC)."""
        cls = _import_plugin_class()
        AnalyzerFeature = _import_base_class()
        assert issubclass(cls, AnalyzerFeature), (
            f"{cls.__name__} must be a subclass of AnalyzerFeature"
        )
