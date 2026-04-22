"""Machine variants resolver.

In our data model every machine — including ``M273$1$1-2-3`` — is a
first-class independent machine with its own ``machines.json`` entry,
rawdata directory, md5, reports, paytable, etc. There is no parent /
child relationship between any two machine rows.

The one external-interface boundary where this abstraction leaks is
the upstream ``POST /MachineTest/MachineConfigMd5`` endpoint: it
returns md5 keyed by the underlying machine name only, so when we
refresh md5 for a machine like ``M273$1$1-2-3`` we have to know which
upstream key carries its md5. That mapping is authoritatively
provided by ``POST /MachineTest/MapMachineOrder``'s
``machineTestVariantsJson`` field and cached in
``configs/machine_halls.json``.

This module is intentionally a pair of pure-function helpers that
look the answer up in that map. There is NO parsing of the variant
key's internal structure (no ``split('$')``, no regex on the ``$``
separator, no hard-coded list of variant machines). If the upstream
ever switches key format or expands the variant set, this file does
not change — only the cached map refreshes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


def load_variants_map(halls_path: Path) -> dict[str, str]:
    """Read the variants map from ``configs/machine_halls.json``.

    Returns a ``{machine_key: upstream_md5_key}`` dict. An empty
    dict means "no variants registered" — every machine resolves
    to itself (backwards compatible with pre-variants deployments
    that never refreshed halls under the new schema).

    Two read paths, newest first:
      1. ``data["variants_map"]`` — written by
         ``/api/machines/halls/refresh`` under the current schema.
      2. ``data["raw_upstream"]["machineTestVariantsJson"]`` —
         older halls.json snapshots kept only the raw upstream
         payload; parsed on the fly so callers never need an
         explicit re-refresh to pick up variants.

    Callers treat a missing file as empty (same shape as "no map")
    rather than raising — this helper is used on hot paths (md5
    refresh, sampling) where the file may not exist yet on a fresh
    checkout.
    """
    try:
        data = json.loads(halls_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    direct = data.get("variants_map")
    if isinstance(direct, dict):
        return _coerce_str_map(direct)
    raw = data.get("raw_upstream")
    if isinstance(raw, dict):
        inline = raw.get("machineTestVariantsJson")
        if isinstance(inline, str):
            try:
                parsed = json.loads(inline)
            except json.JSONDecodeError:
                return {}
            if isinstance(parsed, dict):
                return _coerce_str_map(parsed)
    return {}


def resolve_upstream_md5_key(
    machine: str, variants_map: Mapping[str, str],
) -> str:
    """Return the key under which the upstream MachineConfigMd5
    endpoint reports md5 for ``machine``.

    A machine in ``variants_map`` inherits its listed upstream
    key's md5 (multiple machines may share the same upstream key —
    that's the md5-fanout semantics). A machine not in the map (or
    when the map is empty) resolves to itself.

    This is a single-line function deliberately — its job is to be
    the *only* place in the codebase that answers the "which
    upstream md5 does machine X inherit?" question, so callers
    can't accidentally reintroduce a string-splitting shortcut.
    """
    return variants_map.get(machine, machine)


def _coerce_str_map(src: Mapping) -> dict[str, str]:
    """Defensive: filter to string-key/string-value pairs. JSON
    always loads keys as strings, but values could in principle be
    anything if upstream schema drifts — drop malformed rows
    rather than propagate them silently."""
    out: dict[str, str] = {}
    for k, v in src.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k] = v
    return out
