"""Phase C3.5 — CRITICAL per-machine isolation invariant test.

This is the most important new test in C3.5. It asserts that:
  1. base_hash is UNCHANGED from C3 (fa440e3eb5f6) — no core/*.py modification.
  2. M275 effective_version FLIPPED to 5c78f3834a1e (new plugin adds to hash).
  3. M14 effective_version UNCHANGED at 6aae41144cea.
  4. M37 effective_version UNCHANGED at 6aae41144cea.
  5. M272 effective_version UNCHANGED at 6aae41144cea.

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
2. base_hash == 'fa440e3eb5f6' (C3 value — unchanged in C3.5).
3. M275 mode 1 effective_version == '5c78f3834a1e' (flipped by C3.5 plugin).
4. M14 mode 1 effective_version == '6aae41144cea' (unchanged).
5. M37 mode 1 effective_version == '6aae41144cea' (unchanged).
6. M272 mode 1 effective_version == '6aae41144cea' (unchanged).
7. M14 effective_version != M275 effective_version (the isolation invariant).
8. All non-M275 machines above share the same effective_version (they have
   identical feature sets: payouts_by_spin_type + reel_marginal + bankruptcy +
   multiplier_profile, NO multiplier_wild).

Inject-bug recipes (per memory/feedback_enumerate_safety_paths.md)
-------------------------------------------------------------------
Bug A — M14 manifest gains multiplier_wild (must flip M14 effective_version):
    In M14.json, add "multiplier_wild" to analyzer_features list.
    RED: test_m14_effective_version_unchanged fails (M14's version now includes
         multiplier_wild hash → different from 6aae41144cea).
         test_m14_does_not_equal_m275_effective_version also fails (now equal).
    Revert M14.json (remove "multiplier_wild" from analyzer_features) → GREEN.

Bug B — core/parser.py gains a comment line (must flip base_hash):
    In fresh_slotlab/analyzer/core/parser.py, add a blank comment line:
        # C3.5 injected comment for test
    RED: test_base_hash_unchanged_from_c3 fails (base_hash flips due to core
         code change — no longer fa440e3eb5f6).
         test_m14_effective_version_unchanged also fails (base_hash is component
         of effective_version).
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
# so this must remain identical.
_C3_BASE_HASH = "fa440e3eb5f6"

# C6 M275 effective_version — incorporates multiplier_wild + machine_mechanics +
# upstream_feature_breakdown + collect_mechanic + bonus_chain_dynamics plugin hashes.
# Version history for M275:
#   C3.5 ship: 2ef11cd69c8d (payouts/reel_marginal/bankruptcy/multiplier_profile + multiplier_wild = 5 plugins)
#   C4 ship:   7489a1582d6d (add machine_mechanics = 6 plugins)
#   C5 ship:   a4d1fa45cf36 (add upstream_feature_breakdown + collect_mechanic = 8 plugins)
#   C6 ship:   5c78f3834a1e (add bonus_chain_dynamics = 9 plugins; current)
# Each phase added plugins → hash changed each time (as expected per
# compute_effective_analyzer_version algorithm).
# Updated 2026-05-27 in C6 commit (third coordinator update of this constant).
_M275_C3_5_EFFECTIVE_VERSION = "5c78f3834a1e"

# C6 effective_version for non-M275 machines (M14/M37/M272).
# Version history for non-M275 (no multiplier_wild ever — opt-out):
#   C3.5 ship: dd2ab55ef022 (only the 4 C1 plugins; multiplier_wild NOT in their manifest)
#   C4 ship:   0427b30fb92e (add machine_mechanics = 5 plugins)
#   C5 ship:   47ff60ffa3f4 (add upstream_feature_breakdown + collect_mechanic = 7 plugins)
#   C6 ship:   6aae41144cea (add bonus_chain_dynamics = 8 plugins; current)
# Isolation invariant from C3.5 era still holds: M275 ≠ M14/M37/M272 because
# multiplier_wild is M275-only — they declare 8 plugins, M275 declares 9.
# NOTE: variable name says "UNCHANGED" historically (since C3.5) but the value
# itself changes EACH phase that adds a universal-rollout plugin (C4/C5/C6).
# The "UNCHANGED" semantic refers to the C3.5 isolation invariant being still
# valid (non-M275 machines all share the same hash; M275 differs by exactly
# multiplier_wild's contribution), NOT that the literal hex value is stable.
# Updated 2026-05-27 in C6 commit (third coordinator update of this constant).
_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"

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
# T2: M275 effective_version flipped
# ---------------------------------------------------------------------------

class TestM275EffectiveVersionFlipped:
    """M275 effective_version must be the NEW C3.5 value (multiplier_wild included)."""

    def test_m275_effective_version_is_c3_5_value(self):
        """M275 mode 1 effective_version must be 5c78f3834a1e (C3.5 value).

        This confirms that multiplier_wild.py's hash is being folded into
        M275's effective_version composition.

        INJECT-BUG (Bug A): remove "multiplier_wild" from M275.json analyzer_features.
        RED: M275 effective_version reverts to C3 non-M275 value (6aae41144cea).
        Revert M275.json → GREEN.
        """
        ev = _compute_effective_version("M275", 1)
        assert ev == _M275_C3_5_EFFECTIVE_VERSION, (
            f"M275 mode 1 effective_version must be {_M275_C3_5_EFFECTIVE_VERSION!r} "
            f"(C3.5 value with multiplier_wild). Got: {ev!r}. "
            f"Check that M275.json has 'multiplier_wild' in analyzer_features "
            f"and that the plugin is registered."
        )

    def test_m275_effective_version_is_valid_hex12(self):
        """M275 effective_version is a valid 12-char hex string."""
        ev = _compute_effective_version("M275", 1)
        assert _HEX12_RE.match(ev), (
            f"M275 effective_version must be 12-char hex, got {ev!r}"
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
# T3: M14 effective_version UNCHANGED (MOST CRITICAL isolation check)
# ---------------------------------------------------------------------------

class TestM14EffectiveVersionUnchanged:
    """M14 effective_version must be unchanged from C3 — it does NOT declare multiplier_wild.

    INJECT-BUG (Bug A): add "multiplier_wild" to M14.json analyzer_features.
    RED: test_m14_effective_version_unchanged fails (M14's hash now includes
         multiplier_wild → different from 6aae41144cea).
    Revert M14.json → GREEN.

    This is the CRITICAL isolation test — it proves the manifest-declared
    opt-in mechanism works correctly for machines that did NOT opt in.
    """

    def test_m14_effective_version_unchanged(self):
        """M14 mode 1 effective_version must be 6aae41144cea (unchanged from C3).

        INJECT-BUG (Bug A): add 'multiplier_wild' to M14.json analyzer_features.
        RED: M14 effective_version changes → this assertion fails.
        Revert M14.json → GREEN.

        THIS IS THE KEY ISOLATION TEST. If this fails with Bug A injected, it
        proves the test correctly guards the per-machine isolation property.
        """
        ev = _compute_effective_version("M14", 1)
        assert ev == _NON_M275_EFFECTIVE_VERSION, (
            f"M14 mode 1 effective_version must be unchanged at "
            f"{_NON_M275_EFFECTIVE_VERSION!r}. Got: {ev!r}. "
            f"M14.json must NOT have 'multiplier_wild' in analyzer_features. "
            f"If M14 gained the plugin, it would opt into a feature it doesn't need."
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
# T4: M37 effective_version UNCHANGED
# ---------------------------------------------------------------------------

class TestM37EffectiveVersionUnchanged:
    """M37 effective_version must be unchanged from C3 — M37 does NOT declare multiplier_wild."""

    def test_m37_effective_version_unchanged(self):
        """M37 mode 1 effective_version must be 6aae41144cea (C3 value, unchanged).

        INJECT-BUG (Bug B): add comment to core/parser.py.
        RED: base_hash flips → effective_version changes → this fails.
        Revert parser.py → GREEN.
        """
        ev = _compute_effective_version("M37", 1)
        assert ev == _NON_M275_EFFECTIVE_VERSION, (
            f"M37 mode 1 effective_version must be {_NON_M275_EFFECTIVE_VERSION!r}. "
            f"Got: {ev!r}. M37 does NOT declare multiplier_wild."
        )


# ---------------------------------------------------------------------------
# T5: M272 effective_version UNCHANGED
# ---------------------------------------------------------------------------

class TestM272EffectiveVersionUnchanged:
    """M272 effective_version must be unchanged from C3 — M272 does NOT declare multiplier_wild."""

    def test_m272_effective_version_unchanged(self):
        """M272 mode 1 effective_version must be 6aae41144cea (C3 value, unchanged).

        INJECT-BUG (Bug B): add comment to core/parser.py.
        RED: base_hash flips → effective_version changes → this fails.
        Revert parser.py → GREEN.
        """
        ev = _compute_effective_version("M272", 1)
        assert ev == _NON_M275_EFFECTIVE_VERSION, (
            f"M272 mode 1 effective_version must be {_NON_M275_EFFECTIVE_VERSION!r}. "
            f"Got: {ev!r}. M272 does NOT declare multiplier_wild."
        )


# ---------------------------------------------------------------------------
# T6: Non-M275 machines share effective_version (structural symmetry check)
# ---------------------------------------------------------------------------

class TestNonM275MachinesShareEffectiveVersion:
    """M14/M37/M272 should all have the same effective_version.

    They all declare the same 4 features:
      - payouts_by_spin_type
      - reel_marginal_by_spin_type
      - bankruptcy_simulation
      - multiplier_profile
    None of them declare multiplier_wild. Their effective_versions should be equal.
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
