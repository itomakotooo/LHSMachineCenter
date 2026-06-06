"""R2 Phase 1 (Cluster B) — schema-validation tests for the new
``mechanism_overrides`` block in manifest_schema.json (B-3).

Invariants asserted
-------------------
1. A manifest snippet with a VALID ``mechanism_overrides`` value (subset of the
   5 recognised keys) PASSES schema validation.
2. A manifest snippet with a TYPO key (``jackpot_pids`` instead of
   ``jackpot_pid_set``) FAILS schema validation — the
   ``additionalProperties: false`` guard catches it.  The error message must
   mention the unexpected key.

Note: per-mode ``mechanism_overrides_override`` was intentionally NOT shipped in
R2 Phase 1.  The per-mode resolver does not wire it, so the schema would validate
a key the resolver silently drops (schema-that-lies, violating
feedback_no_silent_swallow.md).  Deferred until the resolver is wired AND a real
use case exists (per R2 Phase 1 critic).  Only the root-level
``mechanism_overrides`` (which build() actually reads) ships here.

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Target line in manifest_schema.json (inside the root-level
``mechanism_overrides`` object, immediately before the closing ``}``):

    "additionalProperties": false

BUG INJECTION:
    Edit manifest_schema.json — inside the root ``mechanism_overrides``
    block — and REMOVE the ``"additionalProperties": false`` line.

EXPECTED effect:
    test_typo_key_fails_validation goes RED:
        The typo key ``jackpot_pids`` now passes (schema no longer
        rejects unknown properties) → the ``pytest.raises(ValidationError)``
        assertion fails with "DID NOT RAISE".

REVERT:
    Restore ``"additionalProperties": false`` exactly as shipped (B-3).
    test_typo_key_fails_validation returns GREEN.

CRITICAL: Use the Edit tool (targeted string-replace), not a Python
write_text(), to avoid CRLF/whitespace drift (per coordinator brief — two
earlier agents left residue this way).

After reverting, run:
    git diff fresh_slotlab/analyzer/manifest_schema.json

Only the B-3 addition (mechanism_overrides root block) must appear;
no formatting/line-ending drift.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md
  (inject-bug exercise mandatory; every safety carve-out needs a regression test
  proven to go RED when the guard is removed)
- memory/feedback_no_hardcode.md
  (5 recognised override keys are loaded from the actual shipped schema, not
  hardcoded here; this test would catch drift if a key is added/removed in
  the schema but not in mechanism_registry.py's build() reader)
- memory/feedback_respect_existing_codebase.md
  (test follows test_c4_mechanism_registry.py conventions: sys.path patching,
  _REPO_ROOT anchor, class-per-invariant-group, docstring-per-test)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

try:
    from jsonschema import validate, ValidationError, Draft7Validator
except ImportError:  # pragma: no cover
    pytest.skip("jsonschema not installed", allow_module_level=True)

# ---------------------------------------------------------------------------
# Repo-root anchor (mirrors test_c4_mechanism_registry.py convention)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

_SCHEMA_PATH = (
    _REPO_ROOT
    / "fresh_slotlab"
    / "analyzer"
    / "manifest_schema.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_schema() -> dict:
    """Load the REAL shipped manifest_schema.json — no hardcoded copy."""
    raw = _SCHEMA_PATH.read_text(encoding="utf-8")
    return json.loads(raw)


def _extract_mechanism_overrides_subschema(schema: dict) -> dict:
    """Pull the mechanism_overrides sub-schema from the root properties block.

    Returns the sub-schema dict (with its own ``properties`` and
    ``additionalProperties`` keys) so we can validate against it directly.
    This avoids having to construct a full valid manifest for every test.
    """
    return schema["properties"]["mechanism_overrides"]


def _validate_mechanism_overrides(value: dict, schema: dict) -> None:
    """Validate ``value`` against the ``mechanism_overrides`` sub-schema.

    Raises ``jsonschema.ValidationError`` if validation fails.
    """
    sub = _extract_mechanism_overrides_subschema(schema)
    validate(instance=value, schema=sub)


# ---------------------------------------------------------------------------
# Invariant 1 — Valid mechanism_overrides passes schema validation
# ---------------------------------------------------------------------------

class TestValidMechanismOverridesPasses:
    """Invariant 1: snippets using only the 5 recognised keys must pass.

    Covers: single key, multiple keys, every individual key, all 5 together.
    """

    def test_scatter_marker_pids_only(self):
        """scatter_marker_pids (array of strings) is valid alone.

        INJECT-BUG: Remove ``additionalProperties: false`` from the schema →
        this test is NOT affected (valid key still passes).
        The RED indicator for the injection is test_typo_key_fails_validation.
        """
        schema = _load_schema()
        _validate_mechanism_overrides(
            {"scatter_marker_pids": ["666"]},
            schema,
        )

    def test_jackpot_applicable_bool_true(self):
        """jackpot_applicable: true is valid."""
        schema = _load_schema()
        _validate_mechanism_overrides({"jackpot_applicable": True}, schema)

    def test_jackpot_applicable_bool_false(self):
        """jackpot_applicable: false is valid (explicit False override)."""
        schema = _load_schema()
        _validate_mechanism_overrides({"jackpot_applicable": False}, schema)

    def test_jackpot_pid_set_array_of_strings(self):
        """jackpot_pid_set array of strings is valid."""
        schema = _load_schema()
        _validate_mechanism_overrides(
            {"jackpot_pid_set": ["10001", "10002"]},
            schema,
        )

    def test_freespin_applicable_bool(self):
        """freespin_applicable: true is valid."""
        schema = _load_schema()
        _validate_mechanism_overrides({"freespin_applicable": True}, schema)

    def test_payout_groups_applicable_bool(self):
        """payout_groups_applicable: false is valid."""
        schema = _load_schema()
        _validate_mechanism_overrides({"payout_groups_applicable": False}, schema)

    def test_empty_object_is_valid(self):
        """Empty mechanism_overrides object ({}) is valid — all keys optional."""
        schema = _load_schema()
        _validate_mechanism_overrides({}, schema)

    def test_all_five_keys_together(self):
        """All 5 recognised keys together are valid (exhaustive combination)."""
        schema = _load_schema()
        _validate_mechanism_overrides(
            {
                "scatter_marker_pids": ["666"],
                "jackpot_applicable": True,
                "jackpot_pid_set": ["10001"],
                "freespin_applicable": True,
                "payout_groups_applicable": False,
            },
            schema,
        )

    def test_brief_example_scatter_marker_pids_666(self):
        """Brief §4 acceptance example: scatter_marker_pids: ['666'] passes.

        This is the exact snippet from the design brief §4, criterion 4.
        """
        schema = _load_schema()
        _validate_mechanism_overrides(
            {"scatter_marker_pids": ["666"]},
            schema,
        )


# ---------------------------------------------------------------------------
# Invariant 2 — Typo key fails validation (additionalProperties: false guard)
# ---------------------------------------------------------------------------

class TestTypoKeyFailsValidation:
    """Invariant 2: unknown/typo keys must FAIL via additionalProperties: false.

    This is the load-bearing test for the inject-bug exercise.
    Removing ``"additionalProperties": false`` from the schema makes the
    typo-key test pass where it should fail → this test goes RED.

    INJECT-BUG (for real): In manifest_schema.json, inside the root-level
    ``mechanism_overrides`` block, remove the line:
        "additionalProperties": false
    Run pytest → this class fails (DID NOT RAISE).
    Restore the line → GREEN.
    """

    def test_typo_key_fails_validation(self):
        """jackpot_pids (typo of jackpot_pid_set) must fail schema validation.

        The additionalProperties: false guard must catch it.
        The ValidationError message must mention the unexpected key.

        Per design brief §4 criterion 4:
            snippet mechanism_overrides: {"jackpot_pids": ["10001"]}
            must FAIL validation.
        """
        schema = _load_schema()
        with pytest.raises(ValidationError) as exc_info:
            _validate_mechanism_overrides(
                {"jackpot_pids": ["10001"]},  # typo: "jackpot_pids" not "jackpot_pid_set"
                schema,
            )
        err_msg = str(exc_info.value.message)
        assert "jackpot_pids" in err_msg or "Additional properties" in err_msg, (
            f"ValidationError must mention the typo key 'jackpot_pids' or "
            f"'Additional properties'. Got: {err_msg!r}"
        )

    def test_unknown_key_scatter_marker_pid_singular(self):
        """scatter_marker_pid (singular, missing trailing s) must fail."""
        schema = _load_schema()
        with pytest.raises(ValidationError):
            _validate_mechanism_overrides(
                {"scatter_marker_pid": ["666"]},  # missing trailing 's'
                schema,
            )

    def test_unknown_key_jackpot_ids(self):
        """jackpot_ids (another common typo for jackpot_pid_set) must fail."""
        schema = _load_schema()
        with pytest.raises(ValidationError):
            _validate_mechanism_overrides(
                {"jackpot_ids": ["10001"]},
                schema,
            )

    def test_unknown_key_freespins_applicable(self):
        """freespins_applicable (spurious trailing 's') must fail."""
        schema = _load_schema()
        with pytest.raises(ValidationError):
            _validate_mechanism_overrides(
                {"freespins_applicable": True},
                schema,
            )

    def test_wrong_type_jackpot_applicable_string(self):
        """jackpot_applicable must be boolean, not a string."""
        schema = _load_schema()
        with pytest.raises(ValidationError):
            _validate_mechanism_overrides(
                {"jackpot_applicable": "true"},  # string, not bool
                schema,
            )

    def test_wrong_type_scatter_marker_pids_not_array(self):
        """scatter_marker_pids must be an array, not a string."""
        schema = _load_schema()
        with pytest.raises(ValidationError):
            _validate_mechanism_overrides(
                {"scatter_marker_pids": "666"},  # string, not array
                schema,
            )

    def test_typo_plus_valid_key_still_fails(self):
        """Mixing a typo key with a valid key must still fail.

        additionalProperties: false applies to the whole object, not per-key.
        """
        schema = _load_schema()
        with pytest.raises(ValidationError) as exc_info:
            _validate_mechanism_overrides(
                {
                    "jackpot_applicable": True,   # valid
                    "jackpot_pids": ["10001"],    # typo — must still fail
                },
                schema,
            )
        err_msg = str(exc_info.value.message)
        assert "jackpot_pids" in err_msg or "Additional properties" in err_msg, (
            f"Error must mention the typo key even when mixed with valid keys. "
            f"Got: {err_msg!r}"
        )


# ---------------------------------------------------------------------------
# Schema structure sanity — keys loaded from real schema match spec
# ---------------------------------------------------------------------------

class TestSchemaStructureMatchesSpec:
    """Confirm the 5 recognised keys are present in the real schema.

    Per memory/feedback_no_hardcode.md: the test does not hardcode which
    keys are valid — it reads them from the schema and checks there are exactly
    5 of them with the right names (matching what mechanism_registry.build()
    reads per B-3 brief §2 B-3 verbatim list).
    """

    _EXPECTED_KEYS = frozenset({
        "scatter_marker_pids",
        "jackpot_applicable",
        "jackpot_pid_set",
        "freespin_applicable",
        "payout_groups_applicable",
    })

    def test_mechanism_overrides_has_exactly_five_properties(self):
        """Root mechanism_overrides block defines exactly 5 properties."""
        schema = _load_schema()
        sub = _extract_mechanism_overrides_subschema(schema)
        actual_keys = frozenset(sub.get("properties", {}).keys())
        assert actual_keys == self._EXPECTED_KEYS, (
            f"mechanism_overrides schema must define exactly the 5 keys from B-3 spec.\n"
            f"Expected: {sorted(self._EXPECTED_KEYS)}\n"
            f"Got:      {sorted(actual_keys)}\n"
            f"Extra: {sorted(actual_keys - self._EXPECTED_KEYS)}\n"
            f"Missing: {sorted(self._EXPECTED_KEYS - actual_keys)}"
        )

    def test_mechanism_overrides_has_additional_properties_false(self):
        """Root mechanism_overrides block has additionalProperties: false.

        This is the guard that makes test_typo_key_fails_validation meaningful.
        If this test fails, the inject-bug exercise is trivially broken.
        """
        schema = _load_schema()
        sub = _extract_mechanism_overrides_subschema(schema)
        assert sub.get("additionalProperties") is False, (
            "mechanism_overrides in root schema must have additionalProperties: false. "
            f"Got: {sub.get('additionalProperties')!r}"
        )

    def test_per_mode_mechanism_overrides_override_absent(self):
        """per_mode_override_block must NOT define mechanism_overrides_override.

        R2 Phase 1 intentionally ships only the root-level mechanism_overrides.
        The per-mode variant was removed because the resolver does not wire it
        (it would silently drop a per-mode override — schema-that-lies). This
        test guards against it being re-added without the resolver wiring.
        """
        schema = _load_schema()
        per_mode_props = (
            schema["definitions"]["per_mode_override_block"]["properties"]
        )
        assert "mechanism_overrides_override" not in per_mode_props, (
            "mechanism_overrides_override must NOT be in per_mode_override_block until "
            "The per-mode resolver does not wire it (R2 Phase 1 critic). "
            f"Found keys: {sorted(per_mode_props.keys())}"
        )
