"""Phase 1 L5 rewire: compute_effective_version_for_machine tests.

5B update: flat-manifest layer deleted.  Legacy path tests (M14, resolution-
equivalence against flat M15.json) are removed — those paths no longer exist.
What remains: M15 new-path tests (the SpinType-native path).

Gate per ANALYZER_ARCHITECTURE.md §6 Phase 5B:
  (a) M15 (has configs/machine_manifests/M15.json) → new path taken, hash valid.
  (b) M14 (no configs/machine_manifests/M14.json, no flat file) → graceful empty
      machine_features → returns base_hash composed with mode=1, is 12-hex.
  (c) derive_analyses is called for M15 (inject-bug gate).

Inject-bug recipes (memory/feedback_enumerate_safety_paths.md):
  BUG-1 (ignore new manifest → always empty features): comment out the
      `if _new_manifest_path.exists():` branch in versioning.py so the else
      branch always runs.  Test (a2) uses a monkeypatched derive_analyses that
      records calls → with bug, it is never called → assertion fires RED.
      Revert → GREEN.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ── repo-relative paths ──────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parents[2]
_NEW_MANIFESTS_ROOT = _REPO / "configs" / "machine_manifests"

_HEX12_RE = re.compile(r"^[0-9a-f]{12}$")


# ── helpers ──────────────────────────────────────────────────────────────────

def _call_versioning(
    machine_id: str,
    mode: int,
    *,
    new_manifests_root: Path | None = None,
) -> str:
    """Thin wrapper: dual-path import to match versioning.py's own style."""
    try:
        from fresh_slotlab.analyzer.versioning import compute_effective_version_for_machine
    except ImportError:
        from analyzer.versioning import compute_effective_version_for_machine  # type: ignore[no-redef]
    kwargs: dict[str, Any] = {}
    if new_manifests_root is not None:
        kwargs["new_manifests_root"] = new_manifests_root
    return compute_effective_version_for_machine(machine_id, mode, **kwargs)


def _derive_analyses_for_m15() -> list[str]:
    """Return derive_analyses(M15 new manifest) — independent call."""
    try:
        from fresh_slotlab.analyzer.machine_spec import load_manifest, derive_analyses
    except ImportError:
        from analyzer.machine_spec import load_manifest, derive_analyses  # type: ignore[no-redef]
    m = load_manifest("M15", _NEW_MANIFESTS_ROOT)
    return derive_analyses(m)


# ── (a) M15 new path ─────────────────────────────────────────────────────────

class TestM15NewPath:
    """M15 has configs/machine_manifests/M15.json → new path must be taken."""

    def test_m15_returns_12hex(self):
        """compute_effective_version_for_machine('M15', 1) returns 12-hex string."""
        result = _call_versioning("M15", 1)
        assert _HEX12_RE.match(result), (
            f"Expected 12-char hex, got {result!r}"
        )

    def test_m15_new_path_hash_equals_derived_hash(self):
        """M15 via new path produces same hash as independently computing via derive_analyses.

        We independently construct what the hash should be (using derive_analyses
        directly on the real manifest + the same feature_registry), then compare
        to what compute_effective_version_for_machine returns.  If the new-path
        branch is NOT taken, the machine_features set would differ → hash differs.
        """
        try:
            from fresh_slotlab.analyzer.versioning import (
                compute_base_analyzer_version,
                compute_effective_analyzer_version,
            )
            from fresh_slotlab.analyzer import feature_registry
            import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
            import fresh_slotlab.analyzer.features.reel_marginal_by_spin_type  # noqa: F401
            import fresh_slotlab.analyzer.features.bankruptcy_simulation  # noqa: F401
            import fresh_slotlab.analyzer.features.multiplier_profile  # noqa: F401
            import fresh_slotlab.analyzer.features.multiplier_wild  # noqa: F401
            import fresh_slotlab.analyzer.features.machine_mechanics  # noqa: F401
            import fresh_slotlab.analyzer.features.upstream_feature_breakdown  # noqa: F401
            import fresh_slotlab.analyzer.features.collect_mechanic  # noqa: F401
            import fresh_slotlab.analyzer.features.bonus_chain_dynamics  # noqa: F401
            import fresh_slotlab.analyzer.features.topdollar_choice  # noqa: F401
        except ImportError:
            pytest.skip("fresh_slotlab not importable")

        derived = _derive_analyses_for_m15()
        base_hash = compute_base_analyzer_version()
        feature_hashes = {f.FEATURE_ID: f.compute_hash() for f in feature_registry.ALL_FEATURES}

        expected_hash = compute_effective_analyzer_version(
            base_hash=base_hash,
            feature_hashes=feature_hashes,
            machine_features=derived,
            mode=1,
        )
        actual_hash = _call_versioning("M15", 1)
        assert actual_hash == expected_hash, (
            f"M15 effective version mismatch.\n"
            f"  actual (from compute_effective_version_for_machine): {actual_hash!r}\n"
            f"  expected (from derive_analyses independently):       {expected_hash!r}\n"
            f"The new-path branch in versioning.py is not being taken for M15."
        )

    def test_m15_new_path_derive_analyses_called(self, monkeypatch):
        """derive_analyses must be called when M15's new-schema manifest exists.

        This is the inject-bug gate: if the new-path branch is disabled (bug),
        derive_analyses is never called → this assertion fires RED.

        BUG-1 recipe: comment out `if _new_manifest_path.exists():` in
        versioning.py so the else branch always runs → `derive_called` stays
        False → `assert derive_called` is RED → revert → GREEN.
        """
        try:
            import fresh_slotlab.analyzer.machine_spec as ms
        except ImportError:
            pytest.skip("fresh_slotlab.analyzer.machine_spec not importable")

        derive_called: list[bool] = []
        real_derive = ms.derive_analyses

        def tracking_derive(manifest: dict) -> list[str]:
            derive_called.append(True)
            return real_derive(manifest)

        monkeypatch.setattr(ms, "derive_analyses", tracking_derive)

        try:
            import fresh_slotlab.analyzer.versioning as versioning_mod  # noqa: F401
        except ImportError:
            pytest.skip("fresh_slotlab.analyzer.versioning not importable")

        with patch("fresh_slotlab.analyzer.machine_spec.derive_analyses", tracking_derive):
            _call_versioning("M15", 1)

        assert derive_called, (
            "derive_analyses was NOT called for M15, but M15 has a new-schema manifest "
            "at configs/machine_manifests/M15.json. "
            "The new-path branch in compute_effective_version_for_machine must call "
            "derive_analyses when the new manifest exists. "
            "BUG-1 inject: disabling the `if _new_manifest_path.exists():` branch → "
            "this fires RED."
        )


# ── (b) M14 — no manifest at all (5B: flat dir deleted) ─────────────────────

class TestM14NoManifest:
    """M14 has no configs/machine_manifests/M14.json (new) and no flat manifest
    (deleted in 5B).  compute_effective_version_for_machine must NOT crash and
    must return a valid 12-hex string (base_hash with empty machine_features).
    """

    def test_m14_has_no_new_manifest(self):
        """Precondition: configs/machine_manifests/M14.json must NOT exist."""
        assert not (_NEW_MANIFESTS_ROOT / "M14.json").exists(), (
            "M14.json was found in configs/machine_manifests/. "
            "This test requires M14 to be unregistered (no new-schema manifest). "
            "If M14 has been onboarded to the new schema, update this test."
        )

    def test_m14_returns_12hex_gracefully(self):
        """compute_effective_version_for_machine('M14', 1) returns 12-hex string
        without crashing even though M14 has no manifest anywhere.

        5B: flat manifests deleted; non-registered machines resolve to base_hash
        with empty features.
        """
        result = _call_versioning("M14", 1)
        assert _HEX12_RE.match(result), (
            f"Expected 12-char hex, got {result!r}"
        )

    def test_m14_returns_base_hash_composition(self):
        """M14 (no manifest) returns base_hash composed with mode=1 only.

        Since machine_features=[], compute_effective_analyzer_version(base_hash, {}, [], 1)
        should produce the same result every call.
        """
        h1 = _call_versioning("M14", 1)
        h2 = _call_versioning("M14", 1)
        assert h1 == h2, "M14 version must be deterministic"

    def test_m14_differs_from_m15(self):
        """M14 (no features) must differ from M15 (has features from spin_types).

        M15 has a real spin_types-derived feature set; M14 has none.
        Their hashes must differ because the mode-1 composition includes different
        feature IDs.
        """
        m14_ev = _call_versioning("M14", 1)
        m15_ev = _call_versioning("M15", 1)
        assert m14_ev != m15_ev, (
            f"M14 ({m14_ev!r}) and M15 ({m15_ev!r}) should produce different "
            f"effective_versions: M15 has spin_type-derived features, M14 has none."
        )

    def test_m14_derive_analyses_not_called(self, monkeypatch):
        """derive_analyses must NOT be called for M14 (no new-schema manifest).

        Verifies the else branch is taken (graceful empty features), not the new-
        path branch.
        """
        try:
            import fresh_slotlab.analyzer.machine_spec as ms
        except ImportError:
            pytest.skip("fresh_slotlab.analyzer.machine_spec not importable")

        derive_called: list[bool] = []
        real_derive = ms.derive_analyses

        def tracking_derive(manifest: dict) -> list[str]:
            derive_called.append(True)
            return real_derive(manifest)

        with patch("fresh_slotlab.analyzer.machine_spec.derive_analyses", tracking_derive):
            _call_versioning("M14", 1)

        assert not derive_called, (
            "derive_analyses WAS called for M14, but M14 has no new-schema manifest. "
            "The else branch (empty machine_features) must be taken."
        )
