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

The single exception is ``extract_base_machine_name`` below — see
its docstring for why filesystem-only conventions are allowed to
parse the prefix.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping


_BASE_MACHINE_RE = re.compile(r"^(M\d+)")


def extract_base_machine_name(name: str) -> str:
    """Extract the physical-machine prefix from a display / upstream
    name (e.g. ``"M15"`` from ``"M15$TopDollarSelector$0$"`` or
    ``"M15$0$"``).

    **Filesystem-fallback ONLY.** Never use this for variants_map /
    md5 fanout / sampling endpoint resolution — those must always go
    through the variants_map (see module docstring). This helper
    exists for one purpose: looking up a per-physical-machine
    resource on disk that follows the stable filename convention
    ``<M\\d+><suffix>``, when the variants_map-resolved underlying
    name didn't yield a hit.

    Trigger case: ``configs/machine_halls.json`` hasn't been refreshed
    under the variants schema (``variants_map`` empty), so a variant
    display like ``M15$TopDollarSelector$0$`` resolves to its own
    upstream_key ``M15$0$`` instead of the physical ``M15``. The
    operator-dropped ``machineconfig/M15Cfg.txt`` file is then
    invisible to all M15 variants until they refresh halls. Falling
    back to a regex on the prefix lets the override work immediately.

    Returns the matched ``M<digits>`` prefix, or the input unchanged
    if no match (callers treat the result as "no fallback found"
    and continue with whatever the variants_map produced).
    """
    m = _BASE_MACHINE_RE.match(name)
    return m.group(1) if m else name


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


def resolve_underlying_for_display(
    machine_display: str,
    machines_rows: list,
    variants_map: Mapping[str, str],
) -> str:
    """For a display name (the `machine` field used throughout the
    console — ``M15`` / ``M273$WheelSelector$1$1-2-3``), return the
    underlying raw machine name (``M15`` / ``M273``).

    Used for per-underlying resource lookup where all variants of
    the same physical machine share one artifact — e.g. the
    MachineConfig override file under ``machineconfig/<u>Cfg.txt``.

    Two-step lookup (no ``$``-splitting shortcut — operators
    rename selectors and variant tokens, and string splitting
    would re-bind lookups in ways variants_map shouldn't):
      1. machines.json row → ``upstream_key`` (strips the selector
         type injected into the display name by compose_display_name)
      2. variants_map[upstream_key] → underlying (strips the
         variant selector params, leaving just the physical M<n>)

    Fallback chain when either step returns nothing keeps the
    result useful:
      - row missing / field missing → fall through with the
        display name (non-variant path: display == underlying)
      - upstream_key not in variants_map → treat as non-variant,
        return upstream_key unchanged"""
    for row in machines_rows:
        if not isinstance(row, dict):
            continue
        if row.get("machine") == machine_display:
            upstream_key = row.get("upstream_key") or machine_display
            return variants_map.get(upstream_key, upstream_key)
    return machine_display


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


def load_selector_types(config_path: Path) -> dict[str, str]:
    """Read ``configs/machine_selector_types.json`` →
    ``{underlying: selector_type_name}``. Values are the upstream
    selector class names (e.g. ``WheelSelector`` /
    ``TopDollarSelector``); they're injected into variant display
    names so operators can see at a glance which selector gameplay
    applies. Missing file or unreadable JSON → empty dict; callers
    fall through to the bare upstream key as the display name
    (everything stays functional, just less readable)."""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    st = data.get("selector_types")
    if not isinstance(st, dict):
        return {}
    return _coerce_str_map(st)


def compose_display_name(
    upstream_key: str,
    variants_map: Mapping[str, str],
    selector_types: Mapping[str, str],
) -> str:
    """Turn an upstream variant key into a human-readable machine
    name by inserting the selector type between the underlying and
    the strategy params.

    Examples (with variants_map = {"M273$1$1-2-3": "M273", ...} and
    selector_types = {"M273": "WheelSelector", ...}):

      * ``M273$1$1-2-3``  → ``M273$WheelSelector$1$1-2-3``
      * ``M6$1$``         → ``M6$FortunesSelector$1$``
      * ``M201$1$2,3,4``  → ``M201$CommonSelector$1$2,3,4``
      * ``M14``           → ``M14`` (non-variant: identity)

    The underlying is looked up via ``variants_map`` — never derived
    by string-splitting on ``$``. The selector name comes from
    ``selector_types``. If either lookup fails, return the input
    unchanged so the row stays usable even without a complete
    selector_types config.

    Once we know the underlying, the display name is built by
    inserting ``${selector}`` immediately after the underlying
    prefix. The rest of the upstream key (``$<strategy>$<param>``)
    is pulled verbatim via a prefix slice — we're not parsing the
    separator structure, just relocating a single injection point.
    """
    if upstream_key not in variants_map:
        return upstream_key
    underlying = variants_map[upstream_key]
    selector = selector_types.get(underlying)
    if not selector:
        return upstream_key
    if not upstream_key.startswith(underlying):
        # Defensive: variants_map should guarantee this prefix, but
        # if upstream ever changes the key scheme the safe fallback
        # is to leave the display name alone rather than produce a
        # malformed composite.
        return upstream_key
    rest = upstream_key[len(underlying):]
    return f"{underlying}${selector}{rest}"


def upstream_key_for_entry(entry: Mapping) -> str | None:
    """Return the entry's explicit ``upstream_key`` field, or None
    if absent. Callers with legacy rows that predate the field (the
    machine name was the upstream key itself) should fall back to
    ``resolve_upstream_md5_key(entry['machine'], variants_map)``.

    Returning None here rather than guessing from ``entry['machine']``
    is deliberate: once display names are in play the machine name
    no longer equals the upstream key, and a silent fallback would
    send sampling / md5 lookups to the wrong upstream row."""
    uk = entry.get("upstream_key") if isinstance(entry, Mapping) else None
    if isinstance(uk, str) and uk:
        return uk
    return None


def apply_md5_refresh(
    existing: dict,
    upstream_data: Mapping[str, Mapping],
    variants_map: Mapping[str, str],
) -> tuple[dict, dict]:
    """Pure function: fold an upstream MachineConfigMd5 response into
    a local machines.json structure, fanning each underlying-key md5
    out across its registered variants.

    Arguments:
      * ``existing`` — ``{"machines": [ {machine, upstream_key, ...}
        ... ]}`` as read from configs/machines.json. Mutated in
        place and also returned so callers can chain.
      * ``upstream_data`` — ``{machine_key: {configSummaryMd5, ...}}``
        from ``/MachineTest/MachineConfigMd5``. Keys are underlying
        machine names (never variant keys — upstream doesn't know
        about variants).
      * ``variants_map`` — ``{variant_upstream_key: underlying_key}``,
        loaded from halls cache. Used for discovery (which upstream
        keys belong to variants, so we don't materialize a bare row
        for them) and as a fallback for rows that predate the
        ``upstream_key`` field.

    Returns ``(existing, stats)`` where ``stats`` carries:
        * ``updated_machines`` — sorted list of machine names whose
          md5 actually changed (fanout visible: editing one
          underlying's upstream md5 will typically list every one
          of its variants here)
        * ``updated_count`` — ``len(updated_machines)``
        * ``skipped_empty_upstream`` — rows where upstream returned
          blank md5; we decline to overwrite real values with empty
        * ``unresolved_entries`` — sorted list of machine rows whose
          upstream_key wasn't present in ``upstream_data``. Typical
          trigger: a variant row exists locally but its underlying
          was decommissioned upstream. Surfacing the list lets the
          operator notice silent drift rather than shipping with
          stale md5.
        * ``discovered_machines`` — newly created rows from upstream
          keys that weren't present locally. Variant-bearing
          upstream keys are skipped (their md5 belongs to the
          variant rows, not a bare row) — listing one would shadow
          the variant rows during resolution.

    Resolution order for each row: ``upstream_key_for_entry(entry)``
    returns the dedicated upstream_key field when present, else
    falls back to ``resolve_upstream_md5_key(entry.machine, map)``.
    This keeps legacy rows (variants_map-keyed machine names, no
    upstream_key yet) refreshing correctly during the rollout
    window, while new rows (display-named machine + upstream_key
    field) pick up md5 without re-parsing anything.

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
        # Non-variant discovery: set upstream_key = machine so the
        # row matches the new schema from the start (no legacy
        # fallback needed).
        entry = {
            "machine": machine_name,
            "upstream_key": machine_name,
            "modes": [1, 2, 5, 7],
        }
        machines_list.append(entry)
        machines_by_name[machine_name] = entry
        discovered.append(machine_name)

    # Pass 2 — fan md5 out to every row. Two-step resolution:
    #   (1) find the *variant upstream key* for the row — what we'd
    #       send as MachineName on /MultiRobotTestSpinVariant
    #   (2) translate that to the *md5 owner key* — the underlying
    #       machine under which /MachineConfigMd5 reports its md5
    # New-schema rows carry the variant upstream key as an explicit
    # ``upstream_key`` field (while ``machine`` is a display name);
    # legacy rows have only ``machine`` and it equals the variant
    # upstream key itself. Either way step 2 goes through
    # variants_map → underlying, which is the key upstream_data uses.
    updated_machines: list[str] = []
    skipped_empty_upstream = 0
    unresolved_entries: list[str] = []
    for entry in machines_list:
        name = entry.get("machine") if isinstance(entry, dict) else None
        if not isinstance(name, str):
            continue
        variant_ukey = upstream_key_for_entry(entry)
        if variant_ukey is None:
            variant_ukey = name  # legacy row: machine field is the upstream key
        md5_owner = resolve_upstream_md5_key(variant_ukey, variants_map)
        upstream = upstream_data.get(md5_owner)
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
