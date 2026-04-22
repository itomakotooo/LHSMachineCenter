"""One-time migration: replace variant-bearing machines with their
variant entries in ``configs/machines.json``.

Before: 253 rows, each row = one upstream machine key (``M14``,
``M273``, ``M201``, ...).
After : 253 - |underlying_keys_with_variants| + |variant_keys| rows,
each row an independent machine. Rows with underlying keys that
carry variants (e.g. ``M273``, ``M201``) are dropped; their variant
keys (``M273$0$``, ``M273$1$1-2-3``, ...) are inserted as fresh
rows inheriting the old row's ``modes`` / ``logicClassNames`` /
``configSummaryMd5`` / ``codeSummaryMd5`` / ``available`` fields.

The md5 values are **seeded** from the old underlying row so the
post-migration machines.json is immediately usable even before
``/api/machines/refresh-md5`` runs. That endpoint's
variant-aware fanout (stage 3 of the variants rollout) will refresh
them against the live upstream afterward.

The source of truth for the variant → upstream mapping is the
``variants_map`` cached in ``configs/machine_halls.json`` — refresh
it first via ``/api/machines/halls/refresh`` if the cache is stale.

Usage:
    python scripts/migrate_machines_to_variants.py
    python scripts/migrate_machines_to_variants.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MACHINES_JSON = ROOT / "configs" / "machines.json"
HALLS_JSON = ROOT / "configs" / "machine_halls.json"

# Allow `python scripts/migrate_machines_to_variants.py` direct
# invocation without setting PYTHONPATH. The import below
# (``src.web_console.backend.machine_variants``) is intentional —
# we share the real loader with the backend so a single bugfix
# propagates to both paths.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_upstream_to_variants(
    variants_map: dict[str, str],
) -> dict[str, list[str]]:
    """Invert ``{variant: upstream}`` → ``{upstream: [variant, ...]}``
    with variant order stable-sorted so the output machines.json is
    deterministic across re-runs. Sorting matters for diff noise in
    code review more than for correctness."""
    inv: dict[str, list[str]] = defaultdict(list)
    for vk, uk in variants_map.items():
        inv[uk].append(vk)
    for uk in inv:
        inv[uk].sort()
    return dict(inv)


def migrate(
    existing: dict, variants_map: dict[str, str],
) -> tuple[dict, dict]:
    """Pure-function migration. Returns ``(new_machines_json, stats)``.

    Stats block:
        * ``kept_rows``     — rows preserved as-is (no underlying-key match)
        * ``replaced_rows`` — underlying-key rows dropped
        * ``added_rows``    — variant rows inserted (some may be skipped
                              if already present from a prior partial run)
        * ``skipped_rows``  — variants that already existed in input
        * ``missing_source``— variants whose underlying row wasn't in
                              input (md5 will be seeded empty; refresh
                              has to fix this after)
    """
    upstream_to_variants = build_upstream_to_variants(variants_map)
    replaced_underlying = set(upstream_to_variants)  # the 26 keys

    old_rows = existing.get("machines", []) or []
    old_by_name = {r["machine"]: r for r in old_rows if isinstance(r, dict)}

    new_rows: list[dict] = []
    kept_rows = 0
    replaced_rows = 0
    added_rows = 0
    skipped_rows = 0
    missing_source: list[str] = []

    # Pass 1 — keep everything except the underlying-key rows
    # (they're "replaced" by the variant rows created in pass 2).
    for row in old_rows:
        if not isinstance(row, dict):
            continue
        name = row.get("machine")
        if name in replaced_underlying:
            replaced_rows += 1
            continue
        new_rows.append(row)
        kept_rows += 1

    # Pass 2 — synthesize one row per variant, seeded from the old
    # underlying row when available. Iteration order is stable:
    # upstream keys ascending, variants within a key already sorted
    # by build_upstream_to_variants.
    for upstream_key in sorted(upstream_to_variants):
        variant_keys = upstream_to_variants[upstream_key]
        source = old_by_name.get(upstream_key)
        if source is None:
            missing_source.append(upstream_key)
        for vk in variant_keys:
            if vk in old_by_name:
                # Already present (prior partial migration, or upstream
                # added a variant that was pre-registered by hand).
                # Preserve — don't reset md5 or modes.
                new_rows.append(old_by_name[vk])
                skipped_rows += 1
                continue
            seeded: dict = {
                "machine": vk,
                "modes": list(source.get("modes") or [1, 2, 5, 7]) if source else [1, 2, 5, 7],
                "logicClassNames": list(source.get("logicClassNames") or []) if source else [],
                "configSummaryMd5": str(source.get("configSummaryMd5", "")) if source else "",
                "codeSummaryMd5": str(source.get("codeSummaryMd5", "")) if source else "",
                "available": bool(source.get("available", True)) if source else True,
            }
            new_rows.append(seeded)
            added_rows += 1

    # Sort new_rows by machine key — stable, reproducible diff.
    new_rows.sort(key=lambda r: r.get("machine", ""))
    return {"machines": new_rows}, {
        "kept_rows": kept_rows,
        "replaced_rows": replaced_rows,
        "added_rows": added_rows,
        "skipped_rows": skipped_rows,
        "total_rows": len(new_rows),
        "missing_source": sorted(missing_source),
    }


def _load_variants_map() -> dict[str, str]:
    """Read variants_map from the halls cache. We intentionally import
    the real loader rather than reparsing here — that way a single
    bugfix to ``load_variants_map`` propagates automatically."""
    from src.web_console.backend.machine_variants import load_variants_map
    return load_variants_map(HALLS_JSON)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print but don't write")
    args = parser.parse_args()

    variants_map = _load_variants_map()
    if not variants_map:
        raise SystemExit(
            f"variants_map empty — refresh halls cache first: "
            f"POST /api/machines/halls/refresh. halls file: {HALLS_JSON}"
        )

    with open(MACHINES_JSON, "r", encoding="utf-8") as f:
        existing = json.load(f)

    new_config, stats = migrate(existing, variants_map)

    print(f"variants_map: {len(variants_map)} entries "
          f"across {len(set(variants_map.values()))} underlying keys")
    print(f"kept rows (non-variant, unchanged) : {stats['kept_rows']}")
    print(f"replaced rows (underlying → dropped): {stats['replaced_rows']}")
    print(f"added rows (new variant entries)    : {stats['added_rows']}")
    print(f"skipped rows (pre-existing variants): {stats['skipped_rows']}")
    print(f"total rows after migration          : {stats['total_rows']}")
    if stats["missing_source"]:
        print(
            f"\nWARNING: {len(stats['missing_source'])} underlying keys in "
            f"variants_map have no source row in machines.json; "
            f"variant md5 seeded empty: {stats['missing_source']}"
        )

    if args.dry_run:
        print(f"\n(dry-run) would write {MACHINES_JSON}")
        sample = new_config["machines"][:3]
        print(json.dumps(sample, indent=2, ensure_ascii=False))
    else:
        MACHINES_JSON.write_text(
            json.dumps(new_config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {MACHINES_JSON}")


if __name__ == "__main__":
    main()
