"""Versioning primitives for the analyzer plugin model.

Per ticket honesty-2 (phase_honesty_2/brief.md) and
session_artifacts/_arch_honesty_isolation/07_decision.md R-1/R-3/R-4/R-5.

Public surface
--------------
- :func:`compute_base_analyzer_version` — 12-hex hash of the transitive
  repo-local import closure of the report-production path, excluding
  registered feature-plugin files. This is the "universal code" identity:
  any change to a content or support module on the production path flips
  this hash; changes confined to a registered feature plugin do not.
- :func:`compute_effective_analyzer_version` — per-(machine, mode)
  hash composition. The result invalidates only machines that actually
  use the changed feature(s).
- :func:`compute_effective_version_for_machine` — convenience orchestrator
  that reads the machine's manifest, resolves features via the
  registry, hashes the closure + feature bodies, and returns the 12-hex string.

Algorithm (verbatim from §4.1)
-------------------------------
  h = sha256(base_hash)
  for fid in sorted(set(machine_features)):
      h.update(b"\\x00" + fid.encode() + b"=" + feature_hashes[fid].encode())
  if mode is not None:
      h.update(b"\\x00mode=" + str(mode).encode())
  return h.hexdigest()[:12]

Where:
  base_hash      — 12-hex hash of the transitive report-production closure
                   (content + support modules, MINUS registered feature plugins)
  feature_hashes — {feature_id: 12-hex hash} from feature_registry
  machine_features — list[str] of feature IDs the machine declares
  mode           — int | None; if provided, the per-mode dimension is included

R-1 closure definition (honesty-2)
------------------------------------
base_hash covers all repo-local Python modules reachable from the
report-production path, MINUS registered feature-plugin files (R-4).

The closure is encoded as an explicit, version-controlled tuple of
repo-relative paths (``_CLOSURE_FILES`` below) hashed in sorted order.
This is deterministic across the dual import paths (script-mode vs
package-mode) per memory/feedback_subprocess_import_suicide_and_module_globals.md.

Line-ending normalization (FIX-2): bytes are CRLF-normalized before hashing
(``read_bytes().replace(b"\\r\\n", b"\\n")``) so base_hash is a function of
SOURCE CONTENT, not of checkout config (autocrlf) or platform. Without this,
adding a ``.gitattributes`` or checking out on Linux would flip the hash and
mark all 393 reports stale without any code change.

A CI drift-guard test (tests/analyzer/test_honesty2_drift_guard.py) introspects
the actual runtime import closure and FAILS if a new repo-local content module
is imported on the production path but absent from _CLOSURE_FILES.

R-4 exclusion
--------------
The base-exclusion set = exactly the ``__file__``s of the registered features
(``feature_registry.ALL_FEATURES``). ``_base.py`` and ``features/__init__.py``
are NOT in ALL_FEATURES and therefore STAY in base. A glob over
``features/*.py`` would be wrong (it would drop _base.py and __init__.py).

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# R-1: Explicit, version-controlled closure file set (honesty-2)
# ---------------------------------------------------------------------------
# This tuple is the authoritative set of repo-local Python files that
# contribute to base_hash. Resolved from the live import graph (introspection
# of sys.modules after importing player_impact_analyzer and its support chain).
#
# Files in this list: content modules + support modules on the report-
# production path, EXCLUDING registered feature-plugin files (R-4).
#
# NOTE: versioning.py is itself in this list. Editing the closure set (or any
# source in it) flips base_hash — which is correct, because the hash algorithm
# changed. The self-referential inclusion is intentional and correct.
#
# Lazy imports inside main() (rtp_integrity, parse_state, pipeline_context,
# topo_sort, mechanism_registry) ARE included because they execute on every
# real report-production run.
#
# Modules intentionally NOT in the closure:
#   - fresh_slotlab/analyzer/_stub_features.py   (test-only, never imported by PIA)
#   - fresh_slotlab/reporter.py                  (standalone script, not imported by PIA)
#   - fresh_slotlab/analyzer/features/*.py       (registered plugins, excluded by R-4)
#     EXCEPT _base.py and __init__.py which ARE in the closure (not registered plugins)
#
# Backend-orchestrated post-hooks (run after pia.main() by app.py / virtual_analyzer.py,
# NOT by PIA's own import graph — they are intentionally outside the closure):
#   - fresh_slotlab/post_inference.py    — run_post_analyzer_inference: launches
#                                          inference scripts as subprocesses after pia.main()
#   - fresh_slotlab/summary_md5_patch.py — patch_summary_md5: stamps md5 fields in the
#                                          written summary after pia.main() returns
#   - fresh_slotlab/batch_dev_sampler.py — dev-only sampling helper, not on report path
# Changes to these post-hooks do NOT flip base_hash. This is a known, accepted scope
# boundary: R-1 defines the report-production path as PIA's import closure, not the
# full backend pipeline. If their honesty ever matters independently, that is a separate
# follow-on (they carry their own md5/patch semantics separate from analyzer_version).
#
# Drift guard: tests/analyzer/test_honesty2_drift_guard.py walks sys.modules
# after importing PIA + support modules and fails if any repo-local content
# module is imported but absent from this list. Update this list if the
# guard fires after a legitimate new content module is added.
_CLOSURE_FILES: tuple[str, ...] = (
    "fresh_slotlab/analyzer/__init__.py",
    "fresh_slotlab/analyzer/core/__init__.py",
    "fresh_slotlab/analyzer/core/_utils.py",
    "fresh_slotlab/analyzer/core/aggregator.py",
    "fresh_slotlab/analyzer/core/base_pipeline.py",
    "fresh_slotlab/analyzer/core/parser.py",
    "fresh_slotlab/analyzer/core/writer.py",
    "fresh_slotlab/analyzer/feature_registry.py",
    "fresh_slotlab/analyzer/features/__init__.py",
    "fresh_slotlab/analyzer/features/_base.py",
    "fresh_slotlab/analyzer/manifest_loader.py",
    "fresh_slotlab/analyzer/mechanism_registry.py",
    "fresh_slotlab/analyzer/parse_state.py",
    "fresh_slotlab/analyzer/pipeline_context.py",
    "fresh_slotlab/analyzer/rtp_integrity.py",
    "fresh_slotlab/analyzer/topo_sort.py",
    "fresh_slotlab/analyzer/versioning.py",
    "fresh_slotlab/chunk_index.py",
    "fresh_slotlab/machine_md5.py",
    "fresh_slotlab/player_impact_analyzer.py",
    "fresh_slotlab/rawdata_index.py",
    "fresh_slotlab/round_classification.py",
    "fresh_slotlab/round_win.py",
    "fresh_slotlab/sampler.py",
    "fresh_slotlab/trigger_sessions.py",
)

# Repo root: two parents up from fresh_slotlab/analyzer/versioning.py
# (i.e., fresh_slotlab/analyzer/ -> fresh_slotlab/ -> repo_root/).
# Pure path arithmetic, no I/O at import time.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def compute_base_analyzer_version(
    *,
    closure_files: Optional[tuple[str, ...]] = None,
    repo_root: Optional[Path] = None,
) -> str:
    """Return the 12-char hex hash of the report-production import closure.

    Hashes every file in the explicit closure set ``_CLOSURE_FILES`` in
    deterministic sorted-by-path order, with CRLF→LF normalization so that
    the hash is a function of SOURCE CONTENT rather than checkout-config
    (autocrlf) or platform.

    Per R-1 (honesty-2) the base_hash covers the full transitive repo-local
    import closure of the report-production path (not just ``core/*.py``):
    any change to a content or support module on the production path flips
    this hash; changes confined to a registered feature plugin do not (R-4
    exclusion via the registry — not a glob).

    Parameters
    ----------
    closure_files:
        Override the closure file set (used by tests to inject a synthetic
        closure). When ``None`` (default), uses ``_CLOSURE_FILES``. Each
        entry is a repo-relative path string.
    repo_root:
        Override the repo root (used by tests). When ``None`` (default),
        uses the repo root derived from this module's location.

    Returns
    -------
    str
        12-character lowercase hex string.

    Raises
    ------
    FileNotFoundError
        If any file in the closure set does not exist. The closure is a
        hard dependency; absence indicates a broken install, wrong path,
        or an out-of-date ``_CLOSURE_FILES`` tuple. Never silently swallowed
        (per memory/feedback_no_silent_swallow.md).
    """
    files = closure_files if closure_files is not None else _CLOSURE_FILES
    root = repo_root if repo_root is not None else _REPO_ROOT

    h = hashlib.sha256()
    # Hash in sorted-by-path order for determinism. The sort is on the
    # repo-relative string (posix path form) so it is identical across
    # platforms that use different path separators.
    #
    # CRLF normalization (FIX-2): normalize line endings before hashing so
    # that the hash depends only on source content, not on git checkout
    # config (core.autocrlf) or OS. Without this, adding .gitattributes or
    # checking out on Linux would flip base_hash and mark 393 reports stale
    # without any code change — a false-stale lie. Per
    # memory/feedback_invariant_with_fallback_hides_drift.md: the hash must
    # be honest; a platform-induced false-stale is as wrong as a false-fresh.
    for rel in sorted(files):
        source_file = root / rel
        if not source_file.exists():
            raise FileNotFoundError(
                f"Closure file does not exist: {source_file}. "
                f"The _CLOSURE_FILES tuple in versioning.py may be out of date, "
                f"or the repo root is wrong (repo_root={root!r}). "
                f"Per memory/feedback_no_silent_swallow.md: do not swallow this error."
            )
        raw = source_file.read_bytes()
        h.update(raw.replace(b"\r\n", b"\n"))

    return h.hexdigest()[:12]


def compute_effective_version_for_machine(
    machine_id: str,
    mode: Optional[int] = None,
    *,
    manifests_root: Optional[Path] = None,
    registry: Optional[Any] = None,
    closure_files: Optional[tuple[str, ...]] = None,
    repo_root: Optional[Path] = None,
) -> str:
    """Convenience orchestrator — full pipeline for one (machine, mode).

    Reads the machine's manifest, resolves variant inheritance, resolves
    per-mode overrides, looks up feature hashes from the registry, hashes
    the report-production closure (R-1), and returns the 12-hex effective
    version.

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
    closure_files:
        Override the closure file set for tests. Production passes None.
    repo_root:
        Override the repo root for tests. Production passes None.

    Returns
    -------
    str
        12-character lowercase hex string.

    Raises
    ------
    FileNotFoundError
        Manifest file missing, or a closure file is missing.
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
        manifests_root = _REPO_ROOT / "slot_designer" / "configs" / "machine_manifests"

    base_hash = compute_base_analyzer_version(
        closure_files=closure_files,
        repo_root=repo_root,
    )

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
        12-hex hash of the universal report-production closure (R-1).
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
