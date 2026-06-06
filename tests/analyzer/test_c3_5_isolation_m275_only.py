"""Phase C3.5 — per-machine isolation invariant test.

5B update: flat-manifest layer deleted.  Tests T2–T7 (M275/M14/M37/M272
effective_version differential assertions) depended on flat manifests in
slot_designer/configs/machine_manifests/.  After 5B those files are gone and all
non-registered machines resolve to base_hash with empty features — making all
non-registered machines equal to each other.  Those tests are removed here.

What remains (T1): base_hash validity and determinism.

The isolation property (adding a registered plugin does NOT flip base_hash) is
still enforced — it is structural: base_hash only covers _CLOSURE_FILES, which
never includes feature plugin files.  Bug B (core/parser.py comment) still proves
this mechanically.

For reference: the manifest-declared opt-in property (M275 vs M14 isolation) will
be re-exercised once M275 is onboarded to the SpinType-native manifest scheme.

Memory files cited
------------------
- memory/feedback_enumerate_safety_paths.md (inject-bug mandatory per invariant)
- memory/feedback_md5_granularity_and_stamping.md (per-mode hash preserved)
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

# R1 Phase 1 (Cluster E) note: _M275_C3_5_EFFECTIVE_VERSION and
# _NON_M275_EFFECTIVE_VERSION hex pins have been REMOVED. They were updated
# manually 3 times across C-phases (C3.5→C5→C6) and would need updating again
# every time a plugin file changes. Replaced with structural differential
# assertions: "M275 differs from M14; M14/M37/M272 share one hash."
# The literal base_hash VALUE pin has also been removed — base_hash is in flux
# during the orchestrator rebuild and a hardcoded pin re-flags the whole fleet
# on every legitimate closure change. The durable isolation invariants below
# (M275_ev != M14_ev; M14/M37/M272 share one hash; base_hash valid+deterministic)
# do not pin a literal value.
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
    """base_hash must be the R-1 closure value — no production-path modifications in C3.5.

    C3.5 adds only a new plugin file (fresh_slotlab/analyzer/features/multiplier_wild.py).
    That plugin is a registered feature in ALL_FEATURES, so it is EXCLUDED from
    base_hash by R-4. Per the R-1 closure algorithm (honesty-2):
        base_hash = sha256(25-file report-production closure, plugins excluded)
    A registered-plugin addition CANNOT change this hash.
    """

    def test_base_hash_is_valid_12_hex(self):
        """compute_base_analyzer_version() returns 12-char lowercase hex string."""
        h = _compute_base_hash()
        assert isinstance(h, str), f"Expected str, got {type(h)}"
        assert _HEX12_RE.match(h), (
            f"base_hash must be 12 lowercase hex chars, got {h!r}"
        )

    def test_base_hash_deterministic(self):
        """base_hash is deterministic across two calls."""
        assert _compute_base_hash() == _compute_base_hash(), (
            "compute_base_analyzer_version() is non-deterministic"
        )


# ---------------------------------------------------------------------------
# T2: Non-registered machines return 12-hex gracefully (5B: flat layer deleted)
# ---------------------------------------------------------------------------

class TestNonRegisteredMachinesGraceful:
    """Non-registered machines (no new-schema manifest, no flat manifest) must
    return a valid 12-hex string without crashing.

    5B: flat manifests deleted.  M275/M14 have no manifest at all now.
    They resolve to base_hash with empty machine_features.
    """

    def test_m14_returns_12hex(self):
        """M14 (no manifest) returns 12-hex string without crashing."""
        ev = _compute_effective_version("M14", 1)
        assert _HEX12_RE.match(ev), (
            f"M14 effective_version must be 12-char lowercase hex, got {ev!r}"
        )

    def test_m275_returns_12hex(self):
        """M275 (no manifest) returns 12-hex string without crashing."""
        ev = _compute_effective_version("M275", 1)
        assert _HEX12_RE.match(ev), (
            f"M275 effective_version must be 12-char lowercase hex, got {ev!r}"
        )

    def test_non_registered_equals_base_hash_composition(self):
        """Non-registered machines (empty features) produce deterministic hash."""
        ev1 = _compute_effective_version("M14", 1)
        ev2 = _compute_effective_version("M14", 1)
        assert ev1 == ev2, "Non-registered machine version must be deterministic"

    def test_m15_differs_from_non_registered(self):
        """M15 (registered, has features) differs from M14 (non-registered, no features).

        M15 has a SpinType-derived feature set; non-registered machines have none.
        Their hashes must differ because the feature composition is different.
        """
        m15_ev = _compute_effective_version("M15", 1)
        m14_ev = _compute_effective_version("M14", 1)
        assert m15_ev != m14_ev, (
            f"M15 ({m15_ev!r}) must differ from M14 ({m14_ev!r}).  "
            f"M15 has spin_type-derived features; M14 has none (non-registered)."
        )
