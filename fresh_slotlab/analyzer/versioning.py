"""Versioning primitives for the analyzer plugin model.

Per ticket P2-A1 §3 C1-C3 and 04_architecture_proposal_v5.md §4.1.

Public surface
--------------
- :func:`compute_base_analyzer_version` — 12-hex hash of the universal
  ``fresh_slotlab/analyzer/core/*.py`` sources. Changes when any core
  module body changes; stable when only feature plugins change.
- :func:`compute_effective_analyzer_version` — per-(machine, mode)
  hash composition. The result invalidates only machines that actually
  use the changed feature(s).
- :func:`compute_effective_version_for_machine` — convenience orchestrator
  that reads the machine's manifest, resolves features via the
  registry, hashes core + feature bodies, and returns the 12-hex string.

Algorithm (verbatim from §4.1)
-------------------------------
  h = sha256(base_hash)
  for fid in sorted(set(machine_features)):
      h.update(b"\\x00" + fid.encode() + b"=" + feature_hashes[fid].encode())
  if mode is not None:
      h.update(b"\\x00mode=" + str(mode).encode())
  return h.hexdigest()[:12]

Where:
  base_hash      — 12-hex hash of fresh_slotlab/analyzer/core/*.py (universal code)
  feature_hashes — {feature_id: 12-hex hash} from feature_registry
  machine_features — list[str] of feature IDs the machine declares
  mode           — int | None; if provided, the per-mode dimension is included

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional


# Where core/*.py lives. Computed at import as a Path constant — pure path
# arithmetic, no I/O.
_CORE_DIR = Path(__file__).parent / "core"


def compute_base_analyzer_version(*, core_dir: Optional[Path] = None) -> str:
    """Return the 12-char hex hash of the analyzer core code.

    Hashes every ``*.py`` file in ``fresh_slotlab/analyzer/core/`` in
    deterministic alphabetical order. Per §4.1 the base_hash is the
    "universal code" identity: any change to a core module flips this
    hash; changes confined to a feature plugin do not.

    Parameters
    ----------
    core_dir:
        Override the core directory path (used by tests). When ``None``
        (default), uses ``fresh_slotlab/analyzer/core/`` next to this
        module.

    Returns
    -------
    str
        12-character lowercase hex string.

    Raises
    ------
    FileNotFoundError
        If *core_dir* does not exist. The core package is a hard
        dependency; absence indicates a broken install or wrong path.
    """
    target = core_dir if core_dir is not None else _CORE_DIR
    if not target.exists():
        raise FileNotFoundError(
            f"core_dir does not exist: {target}. "
            f"compute_base_analyzer_version requires fresh_slotlab/analyzer/core/."
        )

    h = hashlib.sha256()
    # Per §4.1: hash is sha256 of all core/*.py files concatenated in
    # sorted-by-path order. Reference impl in tests matches this exactly;
    # do not add filename prefixes / separators (they would break the
    # reference parity check the test suite enforces).
    for source_file in sorted(target.glob("*.py")):
        h.update(source_file.read_bytes())

    return h.hexdigest()[:12]


def compute_effective_version_for_machine(
    machine_id: str,
    mode: Optional[int] = None,
    *,
    manifests_root: Optional[Path] = None,
    registry: Optional[Any] = None,
    core_dir: Optional[Path] = None,
) -> str:
    """Convenience orchestrator — full pipeline for one (machine, mode).

    Reads the machine's manifest, resolves variant inheritance, resolves
    per-mode overrides, looks up feature hashes from the registry, hashes
    core/*.py, and returns the 12-hex effective version.

    Parameters
    ----------
    machine_id:
        Machine identifier (e.g. ``"M14"`` or ``"M273$WheelSelector$0$"``).
    mode:
        Integer mode. ``None`` to compute the mode-agnostic version (rare).
    manifests_root:
        Manifests directory. Defaults to
        ``slot_designer/configs/machine_manifests`` resolved relative to
        this module's repo root.
    registry:
        Object exposing ``ALL_FEATURES``. Defaults to the package
        ``feature_registry`` module.
    core_dir:
        Override core directory. Used by tests; production passes None.

    Returns
    -------
    str
        12-character lowercase hex string.

    Raises
    ------
    FileNotFoundError
        Manifest file missing.
    KeyError
        Manifest references a feature ID not registered.
    """
    # Lazy imports to avoid circular import: feature_registry imports the
    # AnalyzerFeature ABC, which lives in features/_base.py, which lives
    # alongside this module's siblings. Direct top-level imports would
    # work today but lazy-import keeps versioning.py drop-in for callers
    # who only need compute_base_analyzer_version. Dual-path covers
    # script-mode (cwd=fresh_slotlab/) per memory
    # feedback_subprocess_import_suicide_and_module_globals.md.
    try:
        from fresh_slotlab.analyzer.manifest_loader import (
            load_manifest,
            resolve_inheritance,
            resolve_per_mode,
        )
    except ImportError:
        from analyzer.manifest_loader import (  # type: ignore[no-redef]
            load_manifest,
            resolve_inheritance,
            resolve_per_mode,
        )

    if registry is None:
        try:
            from fresh_slotlab.analyzer import feature_registry as registry
        except ImportError:
            from analyzer import feature_registry as registry  # type: ignore[no-redef]
        # Ensure all known universal feature modules are imported so they
        # register themselves before we read ALL_FEATURES. Importing PIA
        # as a subprocess does not auto-import features/* (no package-level
        # __init__ side effects). Each register() is idempotent on
        # duplicate FEATURE_ID per P2-A1, so double-import is safe.
        try:
            import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
            import fresh_slotlab.analyzer.features.reel_marginal_by_spin_type  # noqa: F401
            import fresh_slotlab.analyzer.features.bankruptcy_simulation  # noqa: F401
            import fresh_slotlab.analyzer.features.multiplier_profile  # noqa: F401
            import fresh_slotlab.analyzer.features.multiplier_wild  # noqa: F401  # C3.5
            import fresh_slotlab.analyzer.features.machine_mechanics  # noqa: F401  # C4
            import fresh_slotlab.analyzer.features.upstream_feature_breakdown  # noqa: F401  # C5
            import fresh_slotlab.analyzer.features.collect_mechanic  # noqa: F401  # C5
            import fresh_slotlab.analyzer.features.bonus_chain_dynamics  # noqa: F401  # C6
        except ImportError:
            try:
                import analyzer.features.payouts_by_spin_type  # type: ignore[no-redef]  # noqa: F401
                import analyzer.features.reel_marginal_by_spin_type  # type: ignore[no-redef]  # noqa: F401
                import analyzer.features.bankruptcy_simulation  # type: ignore[no-redef]  # noqa: F401
                import analyzer.features.multiplier_profile  # type: ignore[no-redef]  # noqa: F401
                import analyzer.features.multiplier_wild  # type: ignore[no-redef]  # noqa: F401  # C3.5
                import analyzer.features.machine_mechanics  # type: ignore[no-redef]  # noqa: F401  # C4
                import analyzer.features.upstream_feature_breakdown  # type: ignore[no-redef]  # noqa: F401  # C5
                import analyzer.features.collect_mechanic  # type: ignore[no-redef]  # noqa: F401  # C5
                import analyzer.features.bonus_chain_dynamics  # type: ignore[no-redef]  # noqa: F401  # C6
            except ImportError:
                pass

    if manifests_root is None:
        # Repo root: two parents up from this file (fresh_slotlab/analyzer/).
        repo_root = Path(__file__).resolve().parent.parent.parent
        manifests_root = repo_root / "slot_designer" / "configs" / "machine_manifests"

    base_hash = compute_base_analyzer_version(core_dir=core_dir)

    manifest = load_manifest(machine_id, manifests_root)
    if manifest.get("inherits_from"):
        manifest = resolve_inheritance(manifest, manifests_root)
    if mode is not None:
        manifest = resolve_per_mode(manifest, mode)

    machine_features = list(manifest.get("analyzer_features") or [])
    feature_hashes = {f.FEATURE_ID: f.compute_hash() for f in registry.ALL_FEATURES}

    return compute_effective_analyzer_version(
        base_hash=base_hash,
        feature_hashes=feature_hashes,
        machine_features=machine_features,
        mode=mode,
    )


def compute_effective_analyzer_version(
    *,
    base_hash: str,
    feature_hashes: dict[str, str],
    machine_features: list[str],
    mode: Optional[int] = None,
) -> str:
    """Return the 12-char hex effective_analyzer_version for one (machine, mode).

    This is the per-machine hash that invalidates only machines using a
    changed feature.  Composition algorithm per 04_v5 §4.1:

        h = sha256(base_hash)
        for fid in sorted(set(machine_features)):
            h.update(b"\\x00" + fid.encode() + b"=" + feature_hashes[fid].encode())
        if mode is not None:
            h.update(b"\\x00mode=" + str(mode).encode())
        return h.hexdigest()[:12]

    Parameters
    ----------
    base_hash:
        12-hex hash of the universal analyzer core code.
    feature_hashes:
        Mapping of feature_id → 12-hex hash for every registered feature.
        Only features in *machine_features* are included in the digest.
    machine_features:
        Feature IDs declared by this machine.  Duplicates are deduplicated;
        order does not matter (sorted before hashing → deterministic).
    mode:
        Integer mode.  When provided, the mode dimension is included so that
        per-mode effective versions differ when applicable per 07_decision_v5 P1.

    Returns
    -------
    str
        12-character lowercase hex string.

    Raises
    ------
    KeyError
        If a feature in *machine_features* is not present in *feature_hashes*.
        This is a programming error — register features before calling.
    ValueError
        If *base_hash* is empty.
    """
    if not base_hash:
        raise ValueError("base_hash must not be empty")

    h = hashlib.sha256(base_hash.encode())

    for fid in sorted(set(machine_features)):
        fhash = feature_hashes[fid]  # KeyError is intentional — see docstring
        h.update(b"\x00" + fid.encode() + b"=" + fhash.encode())

    if mode is not None:
        h.update(b"\x00mode=" + str(mode).encode())

    return h.hexdigest()[:12]
