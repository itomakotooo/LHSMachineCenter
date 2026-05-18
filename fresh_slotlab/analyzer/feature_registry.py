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

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

from typing import Any

from fresh_slotlab.analyzer.features._base import AnalyzerFeature


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
