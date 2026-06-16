"""Phase C3 — round-level enrichment is wired through parser + plugin.

The C3 enrichment requires per-round PayoutByPayline aggregation (shape /
covered_columns / paylines all need round-level data). The implementer chose
Option B: parser.py computes 4 new aggregation dicts in the per-round loop, and
the payouts_by_spin_type plugin consumes them.

This file's durable coverage is STRUCTURAL: it asserts parser.py computes those
4 enrichment dicts and the plugin reads them (TestBaseHashFlipDocumentation),
plus that compute_base_analyzer_version() is a valid, deterministic 12-hex
string. It does NOT pin a literal base_hash value: base_hash is intentionally
in flux during the orchestrator rebuild, and a hardcoded value-pin (or a
C2→current transition pin) would re-flag the whole fleet on every legitimate
closure change — the brittle coupling this lightweight-maintenance direction is
deliberately shedding.

Invariants asserted
-------------------
1. compute_base_analyzer_version() returns a non-empty 12-hex string.
2. compute_base_analyzer_version() is deterministic (same result on two calls).
3. parser.py contains the 4 C3 enrichment dicts (Option B wiring present).
4. The plugin reads those 4 keys from chunk_dict.

Memory files cited
------------------
- memory/feedback_md5_is_a_tag_not_a_destruction_signal.md (base_hash is a tag,
  not a destruction signal; closure changes invalidate renderers gracefully)
- memory/feedback_enumerate_safety_paths.md (structural checks over literal pins)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# NOTE: the literal base_hash value pins (and the C2→current transition pin)
# that used to live here have been REMOVED. base_hash is intentionally in flux
# during the orchestrator rebuild; a hardcoded value-pin re-flags the whole
# fleet on every legitimate closure change. The durable coverage of the C3
# round-level enrichment lives in TestBaseHashFlipDocumentation below: it
# asserts parser.py computes the 4 enrichment dicts and the plugin consumes
# them — a structural feature check that does not depend on any literal hash.

_HEX12_RE = re.compile(r"^[0-9a-f]{12}$")


def _compute_base_hash() -> str:
    try:
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
    except ImportError:
        from analyzer.versioning import compute_base_analyzer_version  # type: ignore[no-redef]
    return compute_base_analyzer_version()


class TestBaseHashSanity:
    """compute_base_analyzer_version() is a valid, deterministic 12-hex string.

    These are non-brittle invariants (no literal value pinned). The C3
    round-level enrichment itself is covered structurally by
    TestBaseHashFlipDocumentation below.
    """

    def test_base_hash_is_valid_12_hex(self):
        """compute_base_analyzer_version() returns a non-empty 12-char lowercase hex string.

        Basic sanity: function must work and return a hash.
        """
        h = _compute_base_hash()
        assert isinstance(h, str), f"Expected str, got {type(h)}"
        assert _HEX12_RE.match(h), (
            f"base_hash must be 12 lowercase hex chars, got {h!r}"
        )

    def test_base_hash_is_deterministic(self):
        """compute_base_analyzer_version() returns the same value on two calls.

        Determinism is required for caching: two processes must agree on base_hash.
        """
        h1 = _compute_base_hash()
        h2 = _compute_base_hash()
        assert h1 == h2, (
            f"compute_base_analyzer_version() is non-deterministic: "
            f"{h1!r} vs {h2!r}"
        )


class TestBaseHashFlipDocumentation:
    """Documents WHY the flip is expected (architectural requirement)."""

    def test_parser_has_c3_enrichment_block(self):
        """parser.py must contain the C3 enrichment block (confirms Option B chosen).

        Check that the 4 new dict names exist in parser.py source.
        This is a structural check — not just a hash check.
        """
        parser_path = _REPO_ROOT / "fresh_slotlab" / "analyzer" / "core" / "parser.py"
        assert parser_path.exists(), f"parser.py not found at {parser_path}"
        source = parser_path.read_text(encoding="utf-8")

        required_symbols = [
            "payout_id_payline_hits",
            "payout_id_match_count_dist",
            "payout_id_col_set",
            "payout_id_has_regular_line",
        ]
        for sym in required_symbols:
            assert sym in source, (
                f"parser.py missing C3 enrichment symbol: {sym!r}. "
                "Option B requires these 4 dicts to be computed in parser's per-round loop."
            )

    def test_plugin_reads_c3_keys_from_chunk_dict(self):
        """Plugin extract() reads the 4 C3 keys from chunk_dict.

        Structural check: the plugin source must reference all 4 key names.
        This confirms extract() is wired to consume what parser.py produces.
        """
        plugin_path = (
            _REPO_ROOT / "fresh_slotlab" / "analyzer" / "features"
            / "payouts_by_spin_type.py"
        )
        assert plugin_path.exists(), f"plugin not found at {plugin_path}"
        source = plugin_path.read_text(encoding="utf-8")

        required_keys = [
            "payout_id_payline_hits",
            "payout_id_match_count_dist",
            "payout_id_col_set",
            "payout_id_has_regular_line",
        ]
        for key in required_keys:
            assert key in source, (
                f"Plugin source missing reference to chunk_dict key: {key!r}. "
                "extract() must read this key from chunk_dict (Option B design)."
            )
