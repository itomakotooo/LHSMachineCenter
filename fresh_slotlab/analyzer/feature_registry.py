"""feature_registry — global registry of AnalyzerFeature plugins.

Per ticket P2-A1 §3 C3 and C4 (Round 2 spec-aligned).

Usage
-----
Plugins register themselves by calling ``register(MyFeature())``.
This is done at plugin module import time by Wave 2c-e work, NOT here.
This file must be importable with zero side effects.

    # in a plugin module:
    from fresh_slotlab.analyzer.feature_registry import register
    register(MyFeature())

Then callers query:
    from fresh_slotlab.analyzer.feature_registry import get_features_for_machine
    features = get_features_for_machine("M274", manifest={"analyzer_features": [...]})

Design
------
- ``ALL_FEATURES``  starts empty (no hardcoded features at foundation layer)
- ``register()``    appends; duplicate registration by FEATURE_ID is a no-op
                    (silent dedup by FEATURE_ID — registering the same feature
                    class twice does not double-register it).
- ``get_features_for_machine()``  reads the manifest's ``analyzer_features`` list
                    (declarative) and returns features whose FEATURE_ID appears
                    in that list.  Registration order is preserved.
- ``discover_features()``  globs ``features/*.py``, excludes helpers (_base,
                    __init__), imports each in deterministic sorted order so each
                    module's top-level ``register()`` call fires.  Call this once
                    before reading ALL_FEATURES in any context that does NOT
                    already import plugin modules individually.

Applicability semantic (04_v5 §5.5.2):
    Applicability is manifest-declared, NOT a runtime instance predicate.
    The round-1 ``applies_to`` predicate has been replaced by the
    ``manifest.analyzer_features`` list.

Phase 3 note:
    Phase 3 (manifest loader) will supply real per-machine manifest dicts.
    Until manifests ship, callers may pass ``manifest=None`` — this
    returns all registered features (stub behavior, documented here).
    The API surface is the manifest-list form; callers must not assume
    the stub behavior persists beyond Phase 3.

Phase 4 note (auto-discover):
    ``discover_features()`` replaces the hardcoded import lists in
    ``versioning.py`` and ``report_engine.py``.  Adding a new plugin no
    longer requires editing a closure file — new plugin files live in
    ``features/`` which is already base-excluded (R-4).

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

# Dual-path import for standalone-script mode (P2-C).
# Package mode (cwd = repo root, fresh_slotlab on sys.path as a package): try block.
# Standalone mode (python fresh_slotlab/player_impact_analyzer.py, fresh_slotlab/ on
# sys.path): except block resolves via analyzer.features._base.
try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Exclusion set — files under features/ that are NOT plugin modules.
# _base.py: ABC definition; __init__.py: package marker.
# Both stay in _CLOSURE_FILES (not registered plugins) per R-4 notes.
# ---------------------------------------------------------------------------
_DISCOVERY_EXCLUDE: frozenset[str] = frozenset({"_base.py", "__init__.py"})


# ---------------------------------------------------------------------------
# Registry state
# ---------------------------------------------------------------------------

ALL_FEATURES: list[AnalyzerFeature] = []
"""Global list of registered AnalyzerFeature instances.

Empty on module import.  Features register themselves by calling
``register(feature_instance)`` at plugin-module import time.
Registration order is preserved; ``get_features_for_machine`` returns
features in registration order (filtered by manifest).
"""


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------

def register(feature: AnalyzerFeature) -> None:
    """Register *feature* in ALL_FEATURES.

    Duplicate registration (same FEATURE_ID) is a silent no-op — the
    existing registration is kept and the new one is discarded.  This
    guards against double-import of a plugin module without raising an
    error.

    Parameters
    ----------
    feature:
        An instance subclassing ``AnalyzerFeature`` ABC.

    Raises
    ------
    TypeError
        If *feature* is not an instance of ``AnalyzerFeature`` (ABC
        subclass check via ``isinstance``).
    """
    if not isinstance(feature, AnalyzerFeature):
        raise TypeError(
            f"register() requires an AnalyzerFeature instance, "
            f"got {type(feature)!r}.  Ensure the class subclasses "
            "AnalyzerFeature ABC and implements extract(), reduce(), emit()."
        )

    # Idempotency: skip if FEATURE_ID already registered (per §3 C3)
    feature_id = feature.FEATURE_ID
    for existing in ALL_FEATURES:
        if existing.FEATURE_ID == feature_id:
            return  # silent no-op

    ALL_FEATURES.append(feature)


def get_features_for_machine(
    machine_id: str,
    manifest: dict[str, Any] | None = None,
) -> list[AnalyzerFeature]:
    """Return features applicable to *machine_id*, in registration order.

    Applicability is manifest-declared per 04_v5 §5.5.2:
    reads ``manifest["analyzer_features"]`` (list of FEATURE_ID strings)
    and returns the registered features whose FEATURE_ID appears in that
    list, in registration order (stable).

    Parameters
    ----------
    machine_id:
        Machine identifier string, e.g. ``"M274"``.  Used only for
        diagnostic context; the manifest already encodes which features
        apply.
    manifest:
        Per-machine manifest dict.  Must contain an ``"analyzer_features"``
        key with a list of FEATURE_ID strings, e.g.::

            {"analyzer_features": ["reel_marginal", "payout_attribution"]}

        If ``None`` (Phase 2 stub behavior — Phase 3 manifests not yet
        shipped), returns ALL registered features.  This stub behavior is
        documented and intentional; callers should not depend on it past
        Phase 3.

    Returns
    -------
    list[AnalyzerFeature]
        Applicable features in registration order (stable).

    Notes
    -----
    Per ticket P2-A1 §3 C1 (Round 2): the round-1 runtime ``applies_to``
    predicate has been replaced by this declarative manifest-list form.
    No instance method predicate is called.
    """
    if manifest is None:
        # Phase 2 stub behavior: no manifests yet — return all features.
        # Wave 2c-e and Phase 3 will supply real manifests.
        return list(ALL_FEATURES)

    declared_ids: list[str] = manifest.get("analyzer_features", [])
    declared_set = set(declared_ids)

    return [f for f in ALL_FEATURES if f.FEATURE_ID in declared_set]


def discover_features(*, _features_dir: Path | None = None) -> None:
    """Import every plugin module under ``features/`` so each self-registers.

    This is the Phase 4 root fix: previously ``versioning.py`` and
    ``report_engine.py`` each maintained a hardcoded import list of plugin
    modules.  Adding a new plugin required editing one of those files, which
    flips ``base_hash`` and re-flags ALL machines as stale.

    After this change, callers replace those hardcoded blocks with a single
    ``discover_features()`` call.  New plugin files added to ``features/``
    are auto-discovered here — no closure file is touched.

    Algorithm
    ---------
    1. Glob ``features/*.py`` (relative to this file's directory).
    2. Exclude ``_base.py`` and ``__init__.py`` (ABC definition + package
       marker; both stay in ``_CLOSURE_FILES`` per R-4).
    3. Sort the remaining names for determinism (sorted order = reproducible
       registration order across platforms / Python versions).
    4. For each, try the ``fresh_slotlab.analyzer.features.<name>`` package
       path first (package mode), then fall back to ``analyzer.features.<name>``
       (standalone-script mode) — matching the dual-path style used throughout
       this codebase per memory/feedback_subprocess_import_suicide_and_module_globals.md.
    5. Importing the module fires its top-level ``register()`` call, which is
       idempotent (duplicate FEATURE_ID is a silent no-op per §3 C3).

    Parameters
    ----------
    _features_dir:
        Override the features directory (used by tests to inject a synthetic
        directory).  When ``None`` (default), resolves relative to this file
        (``<this_file>/../features/``).

    Side effects
    ------------
    Mutates ``ALL_FEATURES`` via each plugin module's ``register()`` call.
    Idempotent: calling twice with the same plugins present leaves
    ``ALL_FEATURES`` unchanged (each ``register()`` deduplicates by FEATURE_ID).

    Error handling
    --------------
    Per memory/feedback_no_silent_swallow.md: import errors are NOT swallowed.
    If a plugin module fails to import (syntax error, missing dependency),
    ``ImportError`` propagates to the caller so the failure is visible rather
    than silently producing an incomplete feature set.

    Notes
    -----
    ``_base.py`` and ``__init__.py`` are explicitly excluded from discovery
    because they are NOT registered plugins: they are the ABC definition and
    the package marker respectively, and both appear in ``_CLOSURE_FILES``
    (contributing to ``base_hash``).  A glob over ``features/*.py`` without
    this exclusion would erroneously attempt to import them as plugins.
    """
    if _features_dir is None:
        _features_dir = Path(__file__).resolve().parent / "features"

    # Collect candidate module stem names in deterministic sorted order.
    stems: list[str] = sorted(
        p.name
        for p in _features_dir.glob("*.py")
        if p.name not in _DISCOVERY_EXCLUDE
    )

    for stem_py in stems:
        stem = stem_py[:-3]  # strip ".py"
        # Dual-path: package mode first, standalone-script mode second.
        # Per memory/feedback_subprocess_import_suicide_and_module_globals.md.
        try:
            importlib.import_module(f"fresh_slotlab.analyzer.features.{stem}")
        except ImportError:
            # If the package-mode path fails, try standalone-script mode.
            # Only suppress the ImportError if the fallback succeeds; otherwise
            # re-raise so the caller sees the failure (no silent swallow).
            try:
                importlib.import_module(f"analyzer.features.{stem}")
            except ImportError:
                # Neither path resolved — this is a hard failure, not a soft
                # "plugin absent" case.  Re-raise with both paths named so the
                # developer can diagnose.  Per feedback_no_silent_swallow.md.
                raise ImportError(
                    f"discover_features: could not import plugin module '{stem}' "
                    f"via either 'fresh_slotlab.analyzer.features.{stem}' or "
                    f"'analyzer.features.{stem}'. "
                    f"Check the plugin file for syntax errors or missing dependencies."
                ) from None
