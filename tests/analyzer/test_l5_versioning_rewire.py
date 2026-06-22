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
            from fresh_slotlab.analyzer.st_extract import (
                discover_extractors,
                get_extractors_for_manifest,
                extractor_hashes as get_extractor_hashes,
            )
            from fresh_slotlab.analyzer.machine_spec import load_manifest
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
            import fresh_slotlab.analyzer.features.structure_drift  # noqa: F401
            import fresh_slotlab.analyzer.st_extract.signature_audit  # noqa: F401
            import fresh_slotlab.analyzer.st_extract.trigger_path  # noqa: F401
        except ImportError:
            pytest.skip("fresh_slotlab not importable")

        # Discover extractors so their hashes are available (mirrors the
        # behaviour of compute_effective_version_for_machine which calls
        # discover_extractors() before folding extractor pseudo-entries).
        discover_extractors()

        derived = _derive_analyses_for_m15()
        base_hash = compute_base_analyzer_version()
        feature_hashes = {f.FEATURE_ID: f.compute_hash() for f in feature_registry.ALL_FEATURES}

        # Fold extractor pseudo-entries ("xt:<EXTRACTOR_ID>") for active
        # extractors on M15.  compute_effective_version_for_machine does this
        # in the Sub-pass B block; the independent expected_hash must mirror it.
        _m15_manifest = load_manifest("M15", _NEW_MANIFESTS_ROOT)
        _active_exts = get_extractors_for_manifest(_m15_manifest)
        _ext_hashes = get_extractor_hashes()
        _derived_with_exts = list(derived)
        for _ext in _active_exts:
            _pseudo_id = f"xt:{_ext.EXTRACTOR_ID}"
            if _pseudo_id not in feature_hashes:
                feature_hashes[_pseudo_id] = _ext_hashes.get(_ext.EXTRACTOR_ID, "")
            if _pseudo_id not in _derived_with_exts:
                _derived_with_exts.append(_pseudo_id)

        expected_hash = compute_effective_analyzer_version(
            base_hash=base_hash,
            feature_hashes=feature_hashes,
            machine_features=_derived_with_exts,
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

# NOTE (2026-06-20): this class previously used M14 as the canonical "unregistered
# machine" example. M14 was later legitimately onboarded (configs/machine_manifests/
# M14.json, confirmed, in the fleet T1/T2 batch commit bcd6752), so it is no longer a
# valid no-manifest baseline. Switched to a guaranteed-unregistered SENTINEL id
# (M99999 — never a real machine, the same convention the backend
# test_phase2b_generate_report uses), which is immune to any future onboarding. The
# tested invariant (the graceful unregistered-machine path: 12-hex, derive_analyses
# NOT called, differs from a registered machine) is unchanged.
_UNREG = "M99999"


class TestUnregisteredMachineNoManifest:
    """An UNREGISTERED machine (no configs/machine_manifests/<M>.json, no flat
    manifest — deleted in 5B). compute_effective_version_for_machine must NOT crash
    and must return a valid 12-hex string (base_hash with empty machine_features).
    """

    def test_unregistered_has_no_new_manifest(self):
        """Precondition: the sentinel machine has no new-schema manifest."""
        assert not (_NEW_MANIFESTS_ROOT / f"{_UNREG}.json").exists(), (
            f"{_UNREG}.json unexpectedly exists in configs/machine_manifests/. "
            f"This test needs a guaranteed-unregistered machine."
        )

    def test_unregistered_returns_12hex_gracefully(self):
        """compute_effective_version_for_machine(<unreg>, 1) returns a 12-hex string
        without crashing even though the machine has no manifest anywhere.

        5B: flat manifests deleted; non-registered machines resolve to base_hash
        with empty features.
        """
        result = _call_versioning(_UNREG, 1)
        assert _HEX12_RE.match(result), (
            f"Expected 12-char hex, got {result!r}"
        )

    def test_unregistered_returns_base_hash_composition(self):
        """Unregistered (no manifest) returns base_hash composed with mode=1 only.

        Since machine_features=[], compute_effective_analyzer_version(base_hash, {}, [], 1)
        should produce the same result every call.
        """
        h1 = _call_versioning(_UNREG, 1)
        h2 = _call_versioning(_UNREG, 1)
        assert h1 == h2, "unregistered version must be deterministic"

    def test_unregistered_differs_from_m15(self):
        """An unregistered machine (no features) must differ from M15 (has features
        from spin_types). Their hashes differ because the mode-1 composition includes
        different feature IDs."""
        unreg_ev = _call_versioning(_UNREG, 1)
        m15_ev = _call_versioning("M15", 1)
        assert unreg_ev != m15_ev, (
            f"unregistered ({unreg_ev!r}) and M15 ({m15_ev!r}) should produce different "
            f"effective_versions: M15 has spin_type-derived features, unregistered has none."
        )

    def test_unregistered_derive_analyses_not_called(self, monkeypatch):
        """derive_analyses must NOT be called for an unregistered machine (no
        new-schema manifest). Verifies the else branch (graceful empty features) is
        taken, not the new-path branch."""
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
            _call_versioning(_UNREG, 1)

        assert not derive_called, (
            f"derive_analyses WAS called for {_UNREG}, but it has no new-schema "
            f"manifest. The else branch (empty machine_features) must be taken."
        )
