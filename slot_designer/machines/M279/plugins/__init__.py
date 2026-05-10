"""M279 plugin package — Light & Wonder "Blazing 777 Triple Double
Jackpot Wild — Nudging Stacks" archetype + Asian-market collect-to-wheel
feature.

M279 doesn't fit the FeaturePlugin Protocol's "single paid spin +
optional feature_rounds list" pattern (it has multi-payline + persistent
collect meter + nudge stacks + wheel feature). Instead, this package
exposes a custom-engine adapter that ``virtual_analyzer`` resolves via
the registry entry's ``_engine`` marker.

Adapter callables exposed at package level (called by
``core/backend/virtual_analyzer.py::_load_custom_engine_module``):

    load_engine(spec_path, weights_path) -> (engine, spec)
    sample_one_chunk(engine, *, machine, mode, chunk_index,
                     robots, spins_per_robot, rng, schema_fp,
                     config_md5, code_md5) -> (chunk, win, bet)
    compute_schema_fingerprint(engine, *, mode, spins_per_robot) -> str

Also exposes ``build_plugin`` per the FeaturePlugin contract — returns
None (M279 has no per-spin feature in the FeaturePlugin sense).
"""
from __future__ import annotations

from .m279.loader import load_m279_engine as load_engine
from .m279_driver import (
    compute_m279_schema_fingerprint as compute_schema_fingerprint,
    sample_one_m279_chunk as sample_one_chunk,
)


def build_plugin(spec_dict: dict, weights_doc: dict):
    """M279 has no FeaturePlugin-style feature — returns None.

    M279's mechanics (nudge / collect / wheel) live in its custom
    engine class, not the generic SpinEngine + plugin pipeline. The
    registry's ``_engine`` marker routes sampling through this
    package's adapter callables instead.
    """
    return None


__all__ = [
    "build_plugin",
    "load_engine",
    "sample_one_chunk",
    "compute_schema_fingerprint",
]
