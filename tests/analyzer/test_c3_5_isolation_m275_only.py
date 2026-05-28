"""Phase C3.5 — CRITICAL per-machine isolation invariant test.

This is the most important new test in C3.5. It asserts that:
  1. base_hash is UNCHANGED from C3 (fa440e3eb5f6) — no core/*.py modification.
  2. M275 effective_version DIFFERS from M14 (multiplier_wild is M275-only).
  3. M14 effective_version == M37 == M272 (identical plugin set, identical hash).
  4. M14 / M37 / M272 effective_version all differ from M275 (isolation invariant).

R1 Phase 1 (Cluster E) refactor note
-------------------------------------
The three effective_version hex pins (_M275_C3_5_EFFECTIVE_VERSION and
_NON_M275_EFFECTIVE_VERSION) were updated manually 3 times during C-phases
(C3.5, C5, C6). This creates recurring test debt whenever a plugin file changes.

Per arch-proposal v2 §3.2–§3.3, the correct approach is structural differential
assertions: test the PROPERTY ("M275 differs from M14 by exactly multiplier_wild's
contribution; M14/M37/M272 share one hash because they have identical plugin sets")
rather than pinning the literal hex value. The base_hash pin (fa440e3eb5f6) REMAINS
because it is a regression guard against accidental core/*.py edits.

This is the C-phases' textbook demonstration of per-machine isolation property:
adding a new plugin file (NOT in core/) does NOT flip base_hash; only machines
that DECLARE the plugin in their manifest get a new effective_version.

As of C3.5:
  - Only M275.json has "multiplier_wild" in analyzer_features.
  - All other 418+ machines are UNCHANGED.

Per brief §2.4 and §10: this property is the key architectural win of the
plugin model. This test PROVES it holds.

Invariants asserted
-------------------
1. compute_base_analyzer_version() returns 12-char hex string.
2. base_hash == 'fa440e3eb5f6' (C3 value — unchanged in C3.5; intentional pin).
3. M275 mode 1 effective_version DIFFERS from M14 mode 1 effective_version.
4. M14 / M37 / M272 all share the same effective_version (identical plugin sets).
5. M275 differs from M14 / M37 / M272 (isolation: multiplier_wild is M275-only).
6. All effective_versions are valid 12-char lowercase hex strings.

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug A — M14 manifest gains multiplier_wild (must flip M14 effective_version):
    In M14.json, add "multiplier_wild" to analyzer_features list.
    RED: test_m14_does_not_equal_m275_effective_version fails (now equal).
         test_m14_m37_same_effective_version may fail (M14 flips, M37 does not).
    Revert M14.json (remove "multiplier_wild" from analyzer_features) → GREEN.

Bug B — core/parser.py gains a comment line (must flip base_hash):
    In fresh_slotlab/analyzer/core/parser.py, add a blank comment line:
        # C3.5 injected comment for test
    RED: test_base_hash_unchanged_from_c3 fails (base_hash flips due to core
         code change — no longer fa440e3eb5f6).
    Revert parser.py (remove the comment) → GREEN.
    NOTE: This is the MOST IMPORTANT inject-bug — it proves the isolation property
    is mechanically enforced, not just claimed.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory per invariant)
- memory/feedback_md5_granularity_and_stamping.md (per-mode hash preserved)
- memory/feedback_md5_is_a_tag_not_a_destruction_signal.md
  (effective_version flip is a classification tag, NOT a destruction signal)
- memory/feedback_subprocess_import_suicide_and_module_globals.md
  (versioning module import-safe)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Known hash constants
# ---------------------------------------------------------------------------

# C3 base_hash — the parser.py C3 additions set this. C3.5 adds NO core changes
# so this must remain identical. INTENTIONAL PIN: this is a regression guard
# against accidental core/*.py edits. Making it dynamic would remove the guard.
# Do NOT replace this with a dynamic compute call — per arch-proposal v2 §3.3.
_C3_BASE_HASH = "fa440e3eb5f6"

# R1 Phase 1 (Cluster E) note: _M275_C3_5_EFFECTIVE_VERSION and
# _NON_M275_EFFECTIVE_VERSION hex pins have been REMOVED. They were updated
# manually 3 times across C-phases (C3.5→C5→C6) and would need updating again
# every time a plugin file changes. Replaced with structural differential
# assertions: "M275 differs from M14; M14/M37/M272 share one hash."
# The base_hash pin above REMAINS — it is intentional (regression guard).
# Version history preserved here for reference:
#   M275 C3.5: 2ef11cd69c8d  C4: 7489a1582d6d  C5: a4d1fa45cf36  C6: 5c78f3834a1e
#   M14  C3.5: dd2ab55ef022  C4: 0427b30fb92e  C5: 47ff60ffa3f4  C6: 6aae41144cea

_HEX12_RE = re.compile(r"^[0-9a-f]{12}$")


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _compute_base_hash() -> str:
    try:
        from fresh_slotlab.analyzer.versioning import compute_base_analyzer_version
    except ImportError:
        from analyzer.versioning import compute_base_analyzer_version  # type: ignore[no-redef]
    return compute_base_analyzer_version()


def _compute_effective_version(machine_id: str, mode: int) -> str:
    try:
        from fresh_slotlab.analyzer.versioning import compute_effective_version_for_machine
    except ImportError:
        from analyzer.versioning import compute_effective_version_for_machine  # type: ignore[no-redef]
    return compute_effective_version_for_machine(machine_id, mode)


# ---------------------------------------------------------------------------
# T1: base_hash unchanged in C3.5
# ---------------------------------------------------------------------------

class TestBaseHashUnchangedInC3_5:
    """base_hash must be identical to C3 — no core/*.py modifications in C3.5.

    C3.5 adds only a new plugin file (fresh_slotlab/analyzer/features/multiplier_wild.py)
    which is NOT in core/. Per the versioning algorithm:
        base_hash = sha256(all core/*.py files)
    A plugin-only addition CANNOT change this hash.
    """

    def test_base_hash_is_valid_12_hex(self):
        """compute_base_analyzer_version() returns 12-char lowercase hex string."""
        h = _compute_base_hash()
        assert isinstance(h, str), f"Expected str, got {type(h)}"
        assert _HEX12_RE.match(h), (
            f"base_hash must be 12 lowercase hex chars, got {h!r}"
        )

    def test_base_hash_unchanged_from_c3(self):
        """base_hash must still be the C3 value (fa440e3eb5f6) in C3.5.

        C3.5 adds multiplier_wild.py in features/ (NOT core/). Per §4.1 algorithm,
        base_hash hashes only core/*.py — a features/ addition is invisible to it.

        INJECT-BUG (Bug B): add a comment line to core/parser.py.
        RED: base_hash flips (any byte change in core/*.py changes sha256).
        Revert parser.py → GREEN.

        This is the PRIMARY proof of per-machine isolation for C3.5.
        """
        h = _compute_base_hash()
        assert h == _C3_BASE_HASH, (
            f"base_hash must be unchanged from C3 ({_C3_BASE_HASH!r}) in C3.5. "
            f"Got: {h!r}. If this changed, a core/*.py file was modified — "
            f"C3.5 must NOT touch core/ (per brief §3). "
            f"If this is a legitimate future change, update _C3_BASE_HASH."
        )

    def test_base_hash_deterministic(self):
        """base_hash is deterministic across two calls."""
        assert _compute_base_hash() == _compute_base_hash(), (
            "compute_base_analyzer_version() is non-deterministic"
        )


# ---------------------------------------------------------------------------
# T2: M275 effective_version structural checks
# ---------------------------------------------------------------------------

class TestM275EffectiveVersionFlipped:
    """M275 effective_version must differ from M14 (multiplier_wild is M275-only).

    R1 Phase 1 (Cluster E) refactor: replaced pin assertion
    (assert ev == "5c78f3834a1e") with structural differential assertion.
    The structural invariant that matters:
      - M275 declares multiplier_wild; M14 does not.
      - Therefore M275_ev != M14_ev (isolation property).
    This test remains GREEN across future plugin additions because it
    asserts the PROPERTY, not the specific hex value.
    """

    def test_m275_effective_version_differs_from_m14(self):
        """M275 mode 1 effective_version must differ from M14 mode 1.

        M275 declares multiplier_wild; M14 does not. Their plugin sets
        differ by exactly one entry, so their hashes must differ.

        INJECT-BUG (Bug A): remove "multiplier_wild" from M275.json analyzer_features.
        RED: M275 loses multiplier_wild from its plugin set → M275_ev collapses
             to the M14 value (same 8 plugins) → assertion fails.
        Revert M275.json → GREEN.
        """
        m275_ev = _compute_effective_version("M275", 1)
        m14_ev = _compute_effective_version("M14", 1)
        assert m275_ev != m14_ev, (
            f"M275 and M14 must produce different effective_analyzer_versions. "
            f"M275 declares multiplier_wild; M14 does not. "
            f"Both returned {m275_ev!r} — check M275.json has 'multiplier_wild' "
            f"in analyzer_features and the plugin is registered."
        )

    def test_m275_effective_version_is_valid_hex12(self):
        """M275 effective_version is a valid 12-char lowercase hex string."""
        ev = _compute_effective_version("M275", 1)
        assert _HEX12_RE.match(ev), (
            f"M275 effective_version must be 12-char lowercase hex, got {ev!r}"
        )

    def test_m275_effective_version_differs_from_base_hash(self):
        """M275 effective_version must differ from base_hash (they're different things)."""
        base = _compute_base_hash()
        ev = _compute_effective_version("M275", 1)
        assert base != ev, (
            f"M275 effective_version must not equal base_hash. "
            f"Both are {base!r} — something is wrong with version composition."
        )


# ---------------------------------------------------------------------------
# T3: M14 effective_version isolation check (MOST CRITICAL)
# ---------------------------------------------------------------------------

class TestM14EffectiveVersionUnchanged:
    """M14 must NOT have multiplier_wild — its ev must differ from M275.

    R1 Phase 1 (Cluster E) refactor: replaced pin assertion
    (assert ev == "6aae41144cea") with structural differential assertion.
    The structural invariant that matters:
      - M14 does NOT declare multiplier_wild; M275 does.
      - Therefore M14_ev != M275_ev (isolation property).
      - M14_ev must equal M37_ev and M272_ev (all have same plugin set).
    These properties hold regardless of which plugins future phases add.

    INJECT-BUG (Bug A): add "multiplier_wild" to M14.json analyzer_features.
    RED: M14 gains multiplier_wild hash → M14_ev == M275_ev → isolation fails.
    Revert M14.json → GREEN.

    This is the CRITICAL isolation test — it proves the manifest-declared
    opt-in mechanism works correctly for machines that did NOT opt in.
    """

    def test_m14_effective_version_is_valid_hex12(self):
        """M14 mode 1 effective_version is a valid 12-char lowercase hex string."""
        ev = _compute_effective_version("M14", 1)
        assert _HEX12_RE.match(ev), (
            f"M14 effective_version must be 12-char lowercase hex, got {ev!r}"
        )

    def test_m14_does_not_equal_m275_effective_version(self):
        """M14 and M275 effective_versions must DIFFER — the isolation invariant.

        This is the core test: M275 declared multiplier_wild, M14 did not.
        Their effective_versions must be different as a result.

        INJECT-BUG (Bug A): add 'multiplier_wild' to M14.json.
        RED: M14 gains multiplier_wild hash → M14 effective_version == M275 effective_version
             → this assertion fails.
        Revert M14.json → GREEN.
        """
        m14_ev = _compute_effective_version("M14", 1)
        m275_ev = _compute_effective_version("M275", 1)
        assert m14_ev != m275_ev, (
            f"M14 and M275 effective_versions must DIFFER. "
            f"Both are {m14_ev!r}. "
            f"This means M14 and M275 have the SAME feature set, which is wrong — "
            f"M275 declared 'multiplier_wild', M14 did not."
        )


# ---------------------------------------------------------------------------
# T4: M37 effective_version structural check
# ---------------------------------------------------------------------------

class TestM37EffectiveVersionUnchanged:
    """M37 effective_version must equal M14 (same plugin set, no multiplier_wild).

    R1 Phase 1 (Cluster E) refactor: replaced pin assertion
    (assert ev == "6aae41144cea") with structural assertion.
    M37 has the same plugin set as M14 and M272; their hashes must be equal.
    """

    def test_m37_effective_version_matches_m14(self):
        """M37 mode 1 effective_version must equal M14 mode 1 (identical plugin set).

        M37 and M14 both declare the same set of plugins (no multiplier_wild).
        With identical plugin sets the hash algorithm must return the same value.

        INJECT-BUG (Bug A): add 'multiplier_wild' to M37.json (not M14.json).
        RED: M37_ev flips → M37_ev != M14_ev → this assertion fails.
        Revert M37.json → GREEN.
        """
        m37_ev = _compute_effective_version("M37", 1)
        m14_ev = _compute_effective_version("M14", 1)
        assert m37_ev == m14_ev, (
            f"M37 and M14 have identical plugin sets — effective_versions must match. "
            f"M37: {m37_ev!r}, M14: {m14_ev!r}. "
            f"M37 must NOT declare multiplier_wild."
        )

    def test_m37_effective_version_differs_from_m275(self):
        """M37 mode 1 effective_version must differ from M275.

        M37 does not declare multiplier_wild; M275 does. Their hashes must differ.
        """
        m37_ev = _compute_effective_version("M37", 1)
        m275_ev = _compute_effective_version("M275", 1)
        assert m37_ev != m275_ev, (
            f"M37 and M275 effective_versions must DIFFER. "
            f"Both are {m37_ev!r}. M37 must NOT declare multiplier_wild."
        )


# ---------------------------------------------------------------------------
# T5: M272 effective_version structural check
# ---------------------------------------------------------------------------

class TestM272EffectiveVersionUnchanged:
    """M272 effective_version must equal M14 (same plugin set, no multiplier_wild).

    R1 Phase 1 (Cluster E) refactor: replaced pin assertion
    (assert ev == "6aae41144cea") with structural assertion.
    M272 has the same plugin set as M14 and M37; their hashes must be equal.
    """

    def test_m272_effective_version_matches_m14(self):
        """M272 mode 1 effective_version must equal M14 mode 1 (identical plugin set).

        M272 and M14 both declare the same set of plugins (no multiplier_wild).
        With identical plugin sets the hash algorithm must return the same value.

        INJECT-BUG (Bug A): add 'multiplier_wild' to M272.json (not M14.json).
        RED: M272_ev flips → M272_ev != M14_ev → this assertion fails.
        Revert M272.json → GREEN.
        """
        m272_ev = _compute_effective_version("M272", 1)
        m14_ev = _compute_effective_version("M14", 1)
        assert m272_ev == m14_ev, (
            f"M272 and M14 have identical plugin sets — effective_versions must match. "
            f"M272: {m272_ev!r}, M14: {m14_ev!r}. "
            f"M272 must NOT declare multiplier_wild."
        )

    def test_m272_effective_version_differs_from_m275(self):
        """M272 mode 1 effective_version must differ from M275.

        M272 does not declare multiplier_wild; M275 does. Their hashes must differ.
        """
        m272_ev = _compute_effective_version("M272", 1)
        m275_ev = _compute_effective_version("M275", 1)
        assert m272_ev != m275_ev, (
            f"M272 and M275 effective_versions must DIFFER. "
            f"Both are {m272_ev!r}. M272 must NOT declare multiplier_wild."
        )


# ---------------------------------------------------------------------------
# T6: Non-M275 machines share effective_version (structural symmetry check)
# ---------------------------------------------------------------------------

class TestNonM275MachinesShareEffectiveVersion:
    """M14/M37/M272 should all have the same effective_version.

    Post-C6 they all declare the same 8 plugins (per universal-rollout
    pattern across C-phases):
      - payouts_by_spin_type, reel_marginal_by_spin_type,
        bankruptcy_simulation, multiplier_profile (C1 set)
      - machine_mechanics (C4 universal rollout)
      - upstream_feature_breakdown, collect_mechanic (C5 universal rollout)
      - bonus_chain_dynamics (C6 universal rollout)
    None of them declare multiplier_wild (M275-only opt-in from C3.5).
    Their effective_versions should be equal because identical plugin
    sets produce identical effective_analyzer_version per
    compute_effective_version_for_machine algorithm.
    """

    def test_m14_m37_same_effective_version(self):
        """M14 and M37 effective_versions must be equal (same 4-feature set)."""
        assert _compute_effective_version("M14", 1) == _compute_effective_version("M37", 1), (
            "M14 and M37 have identical feature declarations; effective_versions must match."
        )

    def test_m14_m272_same_effective_version(self):
        """M14 and M272 effective_versions must be equal (same 4-feature set)."""
        assert _compute_effective_version("M14", 1) == _compute_effective_version("M272", 1), (
            "M14 and M272 have identical feature declarations; effective_versions must match."
        )

    def test_m275_differs_from_all_three(self):
        """M275 effective_version must differ from M14, M37, and M272.

        This is the isolation invariant summary:
        M275 opted into multiplier_wild → unique effective_version.
        M14/M37/M272 did not → unchanged effective_version.
        """
        m275_ev = _compute_effective_version("M275", 1)
        for mid in ("M14", "M37", "M272"):
            ev = _compute_effective_version(mid, 1)
            assert ev != m275_ev, (
                f"{mid} effective_version ({ev!r}) must differ from "
                f"M275 ({m275_ev!r}). "
                f"{mid} did not declare multiplier_wild."
            )


# ---------------------------------------------------------------------------
# T7: M275 manifest structural check
# ---------------------------------------------------------------------------

class TestM275ManifestStructure:
    """Structural check: M275.json must declare multiplier_wild in analyzer_features."""

    def test_m275_manifest_has_multiplier_wild(self):
        """M275.json analyzer_features must contain 'multiplier_wild'.

        This is the manifest-declared opt-in that causes M275's
        effective_version to include the plugin hash.
        """
        import json
        manifest_path = (
            _REPO_ROOT / "slot_designer" / "configs" / "machine_manifests" / "M275.json"
        )
        assert manifest_path.exists(), f"M275.json not found at {manifest_path}"
        manifest = json.loads(manifest_path.read_bytes())
        features = manifest.get("analyzer_features", [])
        assert "multiplier_wild" in features, (
            f"M275.json analyzer_features must contain 'multiplier_wild'. "
            f"Got: {features}"
        )

    def test_m14_manifest_does_not_have_multiplier_wild(self):
        """M14.json must NOT have 'multiplier_wild' in analyzer_features.

        INJECT-BUG (Bug A): add 'multiplier_wild' to M14.json analyzer_features.
        RED: this assertion fires.
        Revert M14.json → GREEN.
        """
        import json
        manifest_path = (
            _REPO_ROOT / "slot_designer" / "configs" / "machine_manifests" / "M14.json"
        )
        assert manifest_path.exists(), f"M14.json not found at {manifest_path}"
        manifest = json.loads(manifest_path.read_bytes())
        features = manifest.get("analyzer_features", [])
        assert "multiplier_wild" not in features, (
            f"M14.json must NOT contain 'multiplier_wild' in analyzer_features. "
            f"Got: {features}. Only M275 opts in to this plugin as of C3.5."
        )
