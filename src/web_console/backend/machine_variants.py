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


def apply_md5_refresh(
    existing: dict,
    upstream_data: Mapping[str, Mapping],
    variants_map: Mapping[str, str],
) -> tuple[dict, dict]:
    """Pure function: fold an upstream MachineConfigMd5 response into
    a local machines.json structure, fanning each underlying-key md5
    out across its registered variants.

    Arguments:
      * ``existing`` — ``{"machines": [ {machine, ...}, ... ]}`` as
        read from configs/machines.json. Mutated in place and also
        returned so callers can chain.
      * ``upstream_data`` — ``{machine_key: {configSummaryMd5, ...}}``
        from ``/MachineTest/MachineConfigMd5``. Keys are underlying
        machine names (never variant keys — upstream doesn't know
        about variants).
      * ``variants_map`` — ``{variant_key: upstream_key}``, loaded
        from halls cache. Empty map → identity resolution
        (pre-variants deployments keep working unchanged).

    Returns ``(existing, stats)`` where ``stats`` carries:
        * ``updated_machines`` — sorted list of machine names whose
          md5 actually changed (fanout visible: editing one
          underlying's upstream md5 will typically list every one
          of its variants here)
        * ``updated_count`` — ``len(updated_machines)``
        * ``skipped_empty_upstream`` — rows where upstream returned
          blank md5; we decline to overwrite real values with empty
        * ``unresolved_entries`` — sorted list of machine rows whose
          resolved upstream key wasn't present in ``upstream_data``.
          Typical trigger: a variant row exists locally but its
          underlying was decommissioned upstream. Surfacing the
          list lets the operator notice silent drift rather than
          shipping with stale md5.
        * ``discovered_machines`` — newly created rows from upstream
          keys that weren't present locally. Variant-bearing
          upstream keys are skipped (their md5 belongs to the
          variant rows, not a bare row) — listing one would shadow
          the variant rows during resolution.

    This function is side-effect free modulo the mutation of
    ``existing`` (the caller owns that dict and will immediately
    serialize it). Tests compose it directly without needing a
    FastAPI test client.
    """
    variant_upstream_keys = set(variants_map.values())
    machines_list = existing.setdefault("machines", [])
    machines_by_name: dict[str, dict] = {
        m["machine"]: m for m in machines_list if isinstance(m, dict) and isinstance(m.get("machine"), str)
    }

    # Pass 1 — discover genuinely new non-variant machines. A
    # variant-bearing underlying key is NOT created as a bare row;
    # its md5 will reach its variant rows in pass 2.
    discovered: list[str] = []
    for machine_name, upstream in upstream_data.items():
        if not isinstance(machine_name, str):
            continue
        if machine_name in variant_upstream_keys:
            continue
        if machine_name in machines_by_name:
            continue
        if not isinstance(upstream, Mapping):
            continue
        new_cfg = str(upstream.get("configSummaryMd5", ""))
        new_code = str(upstream.get("codeSummaryMd5", ""))
        if not new_cfg and not new_code:
            # An all-empty row is noise; wait for upstream to
            # actually report real md5 before materializing it.
            continue
        entry = {"machine": machine_name, "modes": [1, 2, 5, 7]}
        machines_list.append(entry)
        machines_by_name[machine_name] = entry
        discovered.append(machine_name)

    # Pass 2 — fan md5 out to every row by resolving its upstream
    # key. Each row updates independently; sibling variants end up
    # with identical md5 by construction.
    updated_machines: list[str] = []
    skipped_empty_upstream = 0
    unresolved_entries: list[str] = []
    for entry in machines_list:
        name = entry.get("machine") if isinstance(entry, dict) else None
        if not isinstance(name, str):
            continue
        ukey = resolve_upstream_md5_key(name, variants_map)
        upstream = upstream_data.get(ukey)
        if not isinstance(upstream, Mapping):
            unresolved_entries.append(name)
            continue
        new_cfg = str(upstream.get("configSummaryMd5", ""))
        new_code = str(upstream.get("codeSummaryMd5", ""))
        # Defensive guard: decline to overwrite real md5 with blank.
        # Legacy upstream sometimes returns partial rows; losing real
        # md5 data by refresh has been the source of user-visible
        # bugs (reports marked "未标记" post-refresh).
        if not new_cfg and not new_code:
            skipped_empty_upstream += 1
            continue
        if entry.get("configSummaryMd5") != new_cfg or entry.get("codeSummaryMd5") != new_code:
            entry["configSummaryMd5"] = new_cfg
            entry["codeSummaryMd5"] = new_code
            entry["logicClassNames"] = upstream.get(
                "logicClassNames", entry.get("logicClassNames", []),
            )
            updated_machines.append(name)

    updated_machines.sort()
    unresolved_entries.sort()
    discovered.sort()
    return existing, {
        "updated_machines": updated_machines,
        "updated_count": len(updated_machines),
        "skipped_empty_upstream": skipped_empty_upstream,
        "unresolved_entries": unresolved_entries,
        "discovered_machines": discovered,
    }
