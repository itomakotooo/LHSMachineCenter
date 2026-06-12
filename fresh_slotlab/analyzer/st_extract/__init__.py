"""fresh_slotlab.analyzer.st_extract — per-ST extraction layer.

Framework package for per-round, per-SpinType extraction plugins
(STExtractor subclasses). Mirrors the features/ layer structure exactly.

Closed/framework files (in _CLOSURE_FILES):
  __init__.py  (this file) — discovery/registry
  _base.py                 — STExtractor ABC

Base-excluded extractor modules (e.g. trigger_path.py) are auto-discovered
and NOT in the closure, so editing an extractor re-flags only machines
that declare it.

Public API
----------
  get_extractors_for_manifest(manifest) -> list[STExtractor]
      Returns instantiated extractors for the STs that declare them
      in the manifest's spin_types block.

  extractor_hashes() -> dict[str, str]
      {EXTRACTOR_ID: compute_hash()} for every discovered extractor.
      Analog of the feature-hash dict used in compute_effective_analyzer_version.

  discover_extractors() -> None
      Import every extractor module under st_extract/ (excluding
      _base.py and __init__.py) so each self-registers. Idempotent.

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
Registry state lives in module-level list; class methods must NOT
read module globals (feedback_subprocess_import_suicide_and_module_globals).
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

try:
    from fresh_slotlab.analyzer.st_extract._base import STExtractor
except ImportError:
    from analyzer.st_extract._base import STExtractor  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Exclusion set — files under st_extract/ that are NOT extractor modules.
# _base.py: ABC definition; __init__.py: package marker.
# Both stay in _CLOSURE_FILES (not registered extractors) per R-4 analogy.
# ---------------------------------------------------------------------------
_DISCOVERY_EXCLUDE: frozenset[str] = frozenset({"_base.py", "__init__.py"})


# ---------------------------------------------------------------------------
# Registry state
# ---------------------------------------------------------------------------

ALL_EXTRACTORS: list[STExtractor] = []
"""Global list of registered STExtractor instances.

Empty on module import.  Extractor modules register themselves by calling
``register_extractor(instance)`` at module import time.
"""


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def register_extractor(extractor: STExtractor) -> None:
    """Register *extractor* in ALL_EXTRACTORS.

    Duplicate registration (same EXTRACTOR_ID) is a silent no-op so that
    double-import of an extractor module does not raise.

    Raises
    ------
    TypeError
        If *extractor* is not an STExtractor instance.
    """
    if not isinstance(extractor, STExtractor):
        raise TypeError(
            f"register_extractor() requires an STExtractor instance, "
            f"got {type(extractor)!r}. Ensure the class subclasses STExtractor ABC."
        )
    eid = extractor.EXTRACTOR_ID
    for existing in ALL_EXTRACTORS:
        if existing.EXTRACTOR_ID == eid:
            return  # silent no-op
    ALL_EXTRACTORS.append(extractor)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_extractors(*, _extractors_dir: Path | None = None) -> None:
    """Import every extractor module under st_extract/ so each self-registers.

    Algorithm mirrors feature_registry.discover_features() exactly:
    1. Glob *.py, exclude _base.py and __init__.py.
    2. Sort for determinism.
    3. Dual-path import (package mode first, standalone fallback).
    4. Each module's top-level register_extractor() call fires (idempotent).

    Per feedback_no_silent_swallow.md: ImportError is NOT swallowed.
    """
    if _extractors_dir is None:
        _extractors_dir = Path(__file__).resolve().parent

    stems: list[str] = sorted(
        p.name
        for p in _extractors_dir.glob("*.py")
        if p.name not in _DISCOVERY_EXCLUDE
    )

    for stem_py in stems:
        stem = stem_py[:-3]
        try:
            importlib.import_module(f"fresh_slotlab.analyzer.st_extract.{stem}")
        except ImportError:
            try:
                importlib.import_module(f"analyzer.st_extract.{stem}")
            except ImportError:
                raise ImportError(
                    f"discover_extractors: could not import extractor module '{stem}' "
                    f"via either 'fresh_slotlab.analyzer.st_extract.{stem}' or "
                    f"'analyzer.st_extract.{stem}'. "
                    f"Check the module for syntax errors or missing dependencies."
                ) from None


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def get_extractors_for_manifest(manifest: dict[str, Any]) -> list[STExtractor]:
    """Return instantiated extractor instances declared by *manifest*.

    The manifest's spin_types block is walked; any ST block that carries
    a key recognised by a registered extractor (via STExtractor.DECLARED_IN_KEY)
    causes that extractor to be included.  Currently the only such key is
    "trigger_paths" — the trigger_path extractor registers DECLARED_IN_KEY =
    "trigger_paths".

    Each included extractor receives a per-run copy via ``clone_for_manifest``,
    which carries the full manifest so it can read the ST-level declarations
    at begin_robot() / observe_round() time without storing module globals.

    Machines with no extraction declarations → empty list → byte-identical
    parse behavior (the "st_extract" key is omitted from the chunk record).

    Parameters
    ----------
    manifest:
        SpinType-native manifest dict as returned by machine_spec.load_manifest.
        Expected shape: {"spin_types": {"<st>": {...}, ...}, ...}

    Returns
    -------
    list[STExtractor]
        Instantiated extractors (possibly empty).
    """
    spin_types: dict[str, Any] = manifest.get("spin_types") or {}

    # Collect the set of declared keys across ALL STs.
    declared_keys: set[str] = set()
    for _st_block in spin_types.values():
        if isinstance(_st_block, dict):
            declared_keys.update(_st_block.keys())

    # Select extractors whose DECLARED_IN_KEY appears in the manifest.
    result: list[STExtractor] = []
    seen_ids: set[str] = set()
    for ext in ALL_EXTRACTORS:
        dk = getattr(ext, "DECLARED_IN_KEY", None)
        if dk is not None and dk in declared_keys:
            if ext.EXTRACTOR_ID not in seen_ids:
                # Give each run a fresh clone so per-run state does not leak.
                cloned = ext.clone_for_manifest(manifest)
                result.append(cloned)
                seen_ids.add(ext.EXTRACTOR_ID)
    return result


def extractor_hashes() -> dict[str, str]:
    """Return {EXTRACTOR_ID: compute_hash()} for every registered extractor.

    Analog of the feature-hash dict assembled in
    compute_effective_analyzer_version.  Called by versioning.py to fold
    extractor pseudo-entries ("xt:<EXTRACTOR_ID>") into the effective version
    for machines that declare extraction.
    """
    return {ext.EXTRACTOR_ID: ext.compute_hash() for ext in ALL_EXTRACTORS}
