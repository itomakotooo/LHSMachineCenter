"""Snapshot test for ``_parse_upstream_map_order``.

Covers the ``machineTestVariantsJson`` wiring specifically — the cell
and activity parsing is already exercised by the end-to-end halls
endpoint tests elsewhere. These tests lock:

  1. A well-formed ``machineTestVariantsJson`` produces a complete
     ``variants_map`` in the parser output.
  2. Missing / malformed / non-string entries are treated as
     empty-map rather than raising.

Test fixtures mirror the shape actually returned by
``http://buffalo-debug.citrusjoy.com/MachineTest/MapMachineOrder`` —
the upstream payload encodes both the cells and the variants
as JSON strings inside the top-level dict.
"""
from __future__ import annotations

import json

from src.web_console.backend.app import _parse_upstream_map_order


def _upstream(**overrides):
    """Minimal well-formed upstream payload. Tests override fields
    individually so each assertion focuses on one behavior."""
    base = {
        "localMapMachineCellsJson": json.dumps([
            {"name": "M14"}, {"name": "M273"},
        ]),
        "gmMapMachineOrderJson": "[]",
        "machineTestVariantsJson": json.dumps({}),
    }
    base.update(overrides)
    return base


class TestVariantsMapParsing:
    def test_populates_variants_map_from_upstream_field(self):
        upstream = _upstream(machineTestVariantsJson=json.dumps({
            "M273$0$": "M273",
            "M273$1$1-2-3": "M273",
            "M201$1$2,3,4": "M201",
        }))
        parsed = _parse_upstream_map_order(upstream)
        assert parsed["variants_map"] == {
            "M273$0$": "M273",
            "M273$1$1-2-3": "M273",
            "M201$1$2,3,4": "M201",
        }

    def test_missing_field_yields_empty_map(self):
        """Upstream before the variants rollout / a trimmed fixture:
        the field simply isn't there. Parser returns empty map, not
        KeyError, so callers can always reference
        ``parsed['variants_map']`` without a None check."""
        upstream = {
            "localMapMachineCellsJson": "[]",
            "gmMapMachineOrderJson": "[]",
        }
        parsed = _parse_upstream_map_order(upstream)
        assert parsed["variants_map"] == {}

    def test_malformed_json_string_yields_empty_map(self):
        upstream = _upstream(machineTestVariantsJson="{not valid json")
        parsed = _parse_upstream_map_order(upstream)
        assert parsed["variants_map"] == {}

    def test_non_string_values_are_dropped(self):
        """Schema drift guard: if upstream ever returns non-string
        values for a variant key (e.g. a dict with metadata instead
        of the flat string), drop the malformed row and keep the
        well-formed ones."""
        upstream = _upstream(machineTestVariantsJson=json.dumps({
            "M273$0$": "M273",
            "M200$0$": 42,         # bad
            "M201$0$": None,       # bad
            "M202$0$": ["nope"],   # bad
        }))
        parsed = _parse_upstream_map_order(upstream)
        assert parsed["variants_map"] == {"M273$0$": "M273"}

    def test_non_dict_variants_payload_yields_empty_map(self):
        """Upstream sent a list or string where a dict was expected."""
        upstream = _upstream(machineTestVariantsJson=json.dumps(["M273"]))
        parsed = _parse_upstream_map_order(upstream)
        assert parsed["variants_map"] == {}

    def test_variants_map_coexists_with_other_fields(self):
        """Regression guard: adding variants_map parsing must not
        break the existing default_order / active_activities /
        club_machines output shape."""
        upstream = _upstream(
            machineTestVariantsJson=json.dumps({"M273$0$": "M273"}),
        )
        parsed = _parse_upstream_map_order(upstream)
        assert set(parsed) == {
            "default_order",
            "current_hall_order",
            "active_activities",
            "club_machines",
            "variants_map",
        }
        assert parsed["default_order"] == ["M14", "M273"]
        assert parsed["variants_map"] == {"M273$0$": "M273"}
