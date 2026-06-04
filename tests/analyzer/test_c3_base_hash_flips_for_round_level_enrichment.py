"""Phase C3 — base_hash flip EXPECTED for round-level enrichment.

This test ASSERTS that base_hash changed between C2 (commit c57c53a) and C3
(current working tree). The flip is EXPECTED — not a regression.

Per coordinator decision (2026-05-27):
  ACCEPT base_hash flip for C3. The C3 enrichment requires per-round
  PayoutByPayline aggregation (shape / covered_columns / paylines all need
  round-level data). The implementer chose Option B: parser adds 4 new
  aggregation dicts in the per-round loop. Option A (plugin self-iterates)
  would also require parser to expose raw rounds — still a parser.py change.

  Architectural reality: any phase that needs round-level data for plugin
  enrichment MUST touch parser.py → core/*.py hash → base_hash flips → all
  419 machine effective_version invalidates. This is unavoidable without
  moving parser out of fresh_slotlab/analyzer/core/.

  Coordinator decision (locked 2026-05-27): ACCEPT this flip for C3 and
  likely C4/C5/C6 (mechanism_registry + round-level work).

Invariants asserted
-------------------
1. compute_base_analyzer_version() returns a non-empty 12-hex string.
2. compute_base_analyzer_version() returns the POST-C3 value (64409ab1b68c)
   OR dynamically computed current value (allows parser.py re-edits later).
3. Current base_hash is NOT the C2 value (b0ba0ce7c7e2) — confirms flip happened.
4. The flip is documented as expected (this test serves as documentation too).
5. base_hash is deterministic (same result on two calls with same core_dir).

Design note
-----------
This test does NOT attempt to checkout the C2 commit and compare — that would
require git access and is brittle in CI. Instead it:
  - Asserts the current value is a valid 12-hex string
  - Asserts it is NOT the known-C2 value (confirming flip)
  - Asserts determinism
  - Documents the expected post-C3 value as a constant

If the expected post-C3 value changes (e.g. future parser.py edits before C3
commit), update _EXPECTED_C3_BASE_HASH accordingly after verifying the new
compute_base_analyzer_version() output.

Inject-bug recipe (per memory/feedback_enumerate_safety_paths.md)
-----------------------------------------------------------------
Bug: revert parser.py to C2 state (remove the C3 block around line 957-977
and 1852-1877 and 2385-2401).
RED: base_hash returns C2 value (b0ba0ce7c7e2) → test_base_hash_is_not_c2_value fails.
Revert → GREEN.

Memory files cited
------------------
- memory/feedback_md5_granularity_and_stamping.md (per-mode hash must be preserved;
  base_hash flip invalidates all 419 machines' effective_version — expected)
- memory/feedback_md5_is_a_tag_not_a_destruction_signal.md (base_hash flip
  invalidates renderers gracefully; does NOT trigger auto-delete)
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# C2 base_hash (commit c57c53a, before C3 parser changes).
# If base_hash == this value, the C3 parser changes are NOT present.
_C2_BASE_HASH = "b0ba0ce7c7e2"

# Expected base_hash under the R-1 closure (honesty-2, 2026-05-29).
# Phase honesty-2 redefined base_hash to cover the transitive repo-local
# import closure of the report-production path (R-1), not just core/*.py.
# The old C3 value (fa440e3eb5f6, core/*.py glob) is superseded by the
# closure value (960e9d18d83d, 25-file set including content modules).
# The C3 parser changes are still present; the flip here is from closure
# expansion (round_classification, round_win, trigger_sessions, sampler,
# machine_md5, chunk_index, rawdata_index, and support modules now hashed).
# Phase 2a (collect_mechanic carve) shrank PIA (a closure file) → re-baselined
# to 57fdb323585d; phase 2b (bonus_chain_dynamics carve) shrank PIA again →
# 980f488f4bb2; phase 3 (upstream_feature_breakdown row-build carve) shrank PIA
# again → c89db791d8a1; phase 4 (multiplier_profile dict-build carve) shrank PIA
# again → ce298f055495; phase 5 (reel_marginal_by_spin_type dict-build carve) shrank
# PIA again → ccc1ecce185d; phase 6 (bankruptcy_simulation row-build carve — the LAST
# carve) shrank PIA again → d8b8c138874a (one-time fleet re-baseline, report content
# byte-identical).
_EXPECTED_C3_BASE_HASH = "8dbbfad6f90f"  # paytype-rearch feature cross: PIA spin_type_rows enrichment → base_hash 04691124fde6→8dbbfad6f90f; additive (display metadata only, no RTP change)

_HEX12_RE = re.compile(r"^[0-9a-f]{12}$")


def _compute_base_hash() -> str:
    try:
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
    except ImportError:
        from analyzer.versioning import compute_base_analyzer_version  # type: ignore[no-redef]
    return compute_base_analyzer_version()


class TestBaseHashFlipExpected:
    """base_hash flipped from C2 (b0ba0ce7c7e2) to the honesty-2 closure value — EXPECTED.

    Phase honesty-2 redefined base_hash from a core/*.py glob to the full
    report-production import closure (R-1): 25 files including content modules
    (round_classification, round_win, trigger_sessions, sampler, machine_md5,
    chunk_index, rawdata_index) and support modules. Old C3 value (fa440e3eb5f6)
    is superseded. Closure value is d8b8c138874a as of phase-6 (honesty-2 was
    960e9d18d83d, LF-normalized FIX-2; phase-2a's collect_mechanic carve shrank PIA
    to 57fdb323585d; phase-2b's bonus_chain_dynamics carve shrank PIA to 980f488f4bb2;
    phase-3's upstream_feature_breakdown row-build carve shrank PIA to c89db791d8a1;
    phase-4's multiplier_profile dict-build carve shrank PIA to ce298f055495;
    phase-5's reel_marginal_by_spin_type dict-build carve shrank PIA to ccc1ecce185d;
    phase-6's bankruptcy_simulation row-build carve — the LAST carve — shrank PIA again).

    The _EXPECTED_C3_BASE_HASH constant above is the authoritative pin.
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

    def test_base_hash_is_not_c2_value(self):
        """Current base_hash must NOT be the C2 value — confirms C3 parser flip.

        INJECT-BUG: revert parser.py C3 block (lines 957-977, 1852-1877, 2385-2401).
        RED: base_hash reverts to C2 value (b0ba0ce7c7e2) → assertion fails.
        Revert → GREEN.
        """
        h = _compute_base_hash()
        assert h != _C2_BASE_HASH, (
            f"base_hash is still the C2 value ({_C2_BASE_HASH}). "
            "This means the C3 parser changes (payout_id_payline_hits / "
            "payout_id_match_count_dist / payout_id_col_set / "
            "payout_id_has_regular_line aggregations) are NOT present in parser.py. "
            "Per coordinator decision 2026-05-27: C3 EXPECTS base_hash to flip."
        )

    def test_base_hash_matches_expected_c3_value(self):
        """base_hash must be the R-1 closure value (currently d8b8c138874a, phase-6).

        Phase honesty-2 expanded base_hash from the core/*.py glob (fa440e3eb5f6)
        to the full 25-file report-production import closure (960e9d18d83d). The
        C3 parser changes are still present; this pin covers the broader closure.
        If this test fails with a different value, check whether _CLOSURE_FILES in
        versioning.py was edited or whether a new content module was added.
        """
        h = _compute_base_hash()
        assert h == _EXPECTED_C3_BASE_HASH, (
            f"base_hash is {h!r}, expected R-1 closure value {_EXPECTED_C3_BASE_HASH!r}. \n"
            "If the closure set (_CLOSURE_FILES in versioning.py) was legitimately edited,\n"
            "  update _EXPECTED_C3_BASE_HASH to the new value.\n"
            "If base_hash == C2 value (b0ba0ce7c7e2), the C3 parser changes are missing.\n"
            "If base_hash == old C3 value (fa440e3eb5f6), honesty-2 closure change was reverted."
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
