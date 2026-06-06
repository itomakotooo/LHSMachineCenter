"""Phase 1 L5 rewire: compute_effective_version_for_machine dual-path tests.

Gate per ANALYZER_ARCHITECTURE.md §6 Phase 1:
  (a) M15 (has configs/machine_manifests/M15.json) → new path: analysis set ==
      derive_analyses(M15) == flat M15 analyzer_features (resolution-equivalence).
  (b) M14 (no configs/machine_manifests/M14.json) → legacy fallback path: analysis
      set == flat slot_designer/.../M14.json analyzer_features, byte-identical to
      the pre-rewire result.

Inject-bug recipes (memory/feedback_enumerate_safety_paths.md):
  BUG-1 (ignore new manifest → always legacy): comment out the
      `if _new_manifest_path.exists():` branch in versioning.py so the else
      branch always runs. Test (a2) uses a monkeypatched derive_analyses that
      records calls → with bug, it is never called → assertion fires RED.
      Revert → GREEN.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ── repo-relative paths ──────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parents[2]
_NEW_MANIFESTS_ROOT = _REPO / "configs" / "machine_manifests"
_OLD_MANIFESTS_ROOT = _REPO / "slot_designer" / "configs" / "machine_manifests"

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


def _flat_features(machine_id: str) -> list[str]:
    """Read analyzer_features from the legacy flat manifest (pre-rewire source of truth)."""
    path = _OLD_MANIFESTS_ROOT / f"{machine_id}.json"
    flat = json.loads(path.read_text(encoding="utf-8"))
    return sorted(flat.get("analyzer_features") or [])


def _derive_analyses_for_m15() -> list[str]:
    """Return derive_analyses(M15 new manifest) — independent call to validate equality."""
    try:
        from fresh_slotlab.analyzer.machine_spec import load_manifest, derive_analyses
    except ImportError:
        from analyzer.machine_spec import load_manifest, derive_analyses  # type: ignore[no-redef]
    m = load_manifest("M15", _NEW_MANIFESTS_ROOT)
    return derive_analyses(m)


# ── (a) M15 new path: resolution-equivalence ─────────────────────────────────

class TestM15NewPathResolutionEquivalence:
    """M15 has configs/machine_manifests/M15.json → new path must be taken.

    The analysis set from derive_analyses(M15) MUST equal the flat M15
    analyzer_features — resolution-equivalence gate per §6 Phase 1.
    """

    def test_derived_equals_flat_m15_features(self):
        """derive_analyses(new M15) == sorted(flat M15 analyzer_features)."""
        derived = _derive_analyses_for_m15()
        flat = _flat_features("M15")
        assert derived == flat, (
            f"Resolution-equivalence FAILED for M15.\n"
            f"  derived:  {derived}\n"
            f"  flat:     {flat}\n"
            f"If these differ, the new-schema M15 manifest's spin_types do not "
            f"reproduce the confirmed analyzer feature set."
        )

    def test_m15_returns_12hex(self):
        """compute_effective_version_for_machine('M15', 1) returns 12-hex string."""
        result = _call_versioning("M15", 1)
        assert _HEX12_RE.match(result), (
            f"Expected 12-char hex, got {result!r}"
        )

    def test_m15_new_path_hash_equals_derived_hash(self, tmp_path):
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

        # Also monkeypatch the name as imported inside versioning (the lazy import
        # re-imports the module, so we patch at the module level).
        try:
            import fresh_slotlab.analyzer.versioning as versioning_mod
        except ImportError:
            pytest.skip("fresh_slotlab.analyzer.versioning not importable")

        # Force versioning to re-import machine_spec with the patched derive_analyses
        # by patching the module attribute directly after it is imported.
        # We patch `fresh_slotlab.analyzer.machine_spec.derive_analyses` which is
        # the authoritative reference used by the lazy import inside versioning.
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


# ── (b) M14 fallback: legacy path unchanged ───────────────────────────────────

class TestM14FallbackLegacyPath:
    """M14 has NO configs/machine_manifests/M14.json → legacy path must be taken.

    The resolved analysis set must be byte-identical to the flat M14
    analyzer_features in slot_designer/configs/machine_manifests/M14.json.
    """

    def test_m14_has_no_new_manifest(self):
        """Precondition: configs/machine_manifests/M14.json must NOT exist."""
        assert not (_NEW_MANIFESTS_ROOT / "M14.json").exists(), (
            "M14.json was found in configs/machine_manifests/. "
            "This test requires M14 to be a flat-only machine (no new-schema manifest). "
            "If M14 has been onboarded to the new schema, update this test to use a "
            "different flat-only machine."
        )

    def test_m14_returns_12hex(self):
        """compute_effective_version_for_machine('M14', 1) returns 12-hex string."""
        result = _call_versioning("M14", 1)
        assert _HEX12_RE.match(result), (
            f"Expected 12-char hex, got {result!r}"
        )

    def test_m14_fallback_hash_equals_legacy_derived_hash(self):
        """M14 via legacy fallback produces same hash as independently computing from flat features.

        If the fallback path broke (e.g. new-path branch taken even without
        a new manifest), the hash would change → this assertion fires RED.
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

        flat_features = _flat_features("M14")
        base_hash = compute_base_analyzer_version()
        feature_hashes = {f.FEATURE_ID: f.compute_hash() for f in feature_registry.ALL_FEATURES}

        expected_hash = compute_effective_analyzer_version(
            base_hash=base_hash,
            feature_hashes=feature_hashes,
            machine_features=flat_features,
            mode=1,
        )
        actual_hash = _call_versioning("M14", 1)
        assert actual_hash == expected_hash, (
            f"M14 effective version CHANGED after rewire.\n"
            f"  actual:   {actual_hash!r}\n"
            f"  expected: {expected_hash!r}\n"
            f"The legacy fallback path for M14 must be byte-identical to pre-rewire. "
            f"A flat-only machine's resolved analysis set must not change."
        )

    def test_m14_fallback_does_not_call_derive_analyses(self, monkeypatch):
        """derive_analyses must NOT be called for M14 (no new-schema manifest).

        Complementary to test_m15_new_path_derive_analyses_called:
        verifies the fallback branch is taken, not the new-path branch.
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
            "The legacy fallback path must be used for flat-only machines."
        )


# ── resolution-equivalence: new path == legacy path for M15 ──────────────────

class TestResolutionEquivalenceM15:
    """Resolution-equivalence gate: for M15, new path and legacy path produce
    the same hash. This is the property that makes Phase 1 additive/reversible.
    """

    def test_m15_new_path_equals_legacy_path(self, tmp_path):
        """M15 via new path == M15 via legacy path (feature sets are identical).

        Creates a temp new_manifests_root with NO M15.json to force legacy path,
        then compares against the real new-path result.
        Since derived == flat for M15, the hashes must be equal.
        """
        # Real new path (uses configs/machine_manifests/M15.json)
        hash_new = _call_versioning("M15", 1)

        # Forced legacy path: pass empty tmp dir as new_manifests_root
        empty_new_root = tmp_path / "empty_new"
        empty_new_root.mkdir()
        hash_legacy = _call_versioning("M15", 1, new_manifests_root=empty_new_root)

        assert hash_new == hash_legacy, (
            f"Resolution-equivalence FAILED: new path and legacy path give different "
            f"hashes for M15.\n"
            f"  new path hash:    {hash_new!r}\n"
            f"  legacy path hash: {hash_legacy!r}\n"
            f"derive_analyses(M15) must equal sorted(flat M15 analyzer_features).\n"
            f"Check test_derive_reproduces_confirmed_m15 in test_machine_spec.py."
        )
