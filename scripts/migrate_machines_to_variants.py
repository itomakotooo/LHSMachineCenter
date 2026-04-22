"""Build the variants-aware ``configs/machines.json`` from halls +
selector-types metadata. Idempotent — safe to re-run whenever
the variants map or selector-types config changes.

Schema of each produced row:

    {
        "machine": "<display name>",        # UI + path key
        "upstream_key": "<upstream key>",   # payload MachineName
        "modes": [1, 2, 5, 7],
        "logicClassNames": [...],
        "configSummaryMd5": "...",
        "codeSummaryMd5": "...",
        "available": true
    }

For non-variant machines, ``machine`` == ``upstream_key`` ==
upstream key. For variant machines, the display name embeds the
selector type (e.g. ``M273$WheelSelector$1$1-2-3``) while the
upstream_key carries the bare variant key (``M273$1$1-2-3``) so
the sampling path has a clean single source for what to send to
``/MultiRobotTestSpinVariant`` as MachineName.

The rebuild replaces every variant row whose display name isn't
already consistent with the current selector_types map (catches
schema drift: selector_types was updated, need to rerun). Rows
unaffected by the variants feature (pure upstream keys with no
variants_map entry) pass through unchanged apart from gaining
``upstream_key`` = ``machine`` when the field is absent.

Sources of truth (never hardcoded in this script):
  * ``configs/machine_halls.json``          — variants_map
  * ``configs/machine_selector_types.json`` — selector_types
  * ``configs/machines.json``               — pre-rebuild seed (for
                                              modes/md5/logic inheritance)

Usage:
    python scripts/migrate_machines_to_variants.py              # apply
    python scripts/migrate_machines_to_variants.py --dry-run    # preview
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
SELECTOR_TYPES_JSON = ROOT / "configs" / "machine_selector_types.json"

# Allow `python scripts/migrate_machines_to_variants.py` direct
# invocation without setting PYTHONPATH. The imports below
# (``src.web_console.backend.machine_variants``) are intentional —
# we share the real helpers with the backend so a single bugfix
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
    existing: dict,
    variants_map: dict[str, str],
    selector_types: dict[str, str] | None = None,
) -> tuple[dict, dict]:
    """Pure-function rebuild of machines.json around variants +
    selector-aware display names. Returns ``(new_machines_json,
    stats)``.

    Accepts any pre-rebuild state and produces the canonical shape:
      * non-variant rows → ``machine`` = ``upstream_key`` = raw
        upstream key (adds ``upstream_key`` field if missing)
      * variant rows → ``machine`` = display name composed via
        ``compose_display_name``, ``upstream_key`` = raw variant
        key. Inherits modes / logic / md5 from whichever input row
        matched (variant key OR display-name-with-current-selector
        OR the underlying).

    Stats block:
        * ``kept_non_variant``    — non-variant rows preserved
        * ``kept_variant``        — variant rows whose display name
                                    already matched current selector
                                    config (no-op)
        * ``rewritten_variant``   — variant rows whose display name
                                    updated (selector_types changed
                                    or first-time migration)
        * ``added_variant``       — variant rows newly created (no
                                    matching input row for this
                                    upstream key)
        * ``dropped_underlying``  — rows whose machine was a bare
                                    variant-bearing underlying key;
                                    replaced by their variant rows
        * ``missing_selector``    — underlyings in variants_map but
                                    absent from selector_types;
                                    their variants still land with
                                    display = upstream key (readable
                                    fallback, logged for follow-up)
        * ``total_rows``          — sentinel for tests
    """
    from src.web_console.backend.machine_variants import compose_display_name

    selector_types = selector_types or {}
    upstream_to_variants = build_upstream_to_variants(variants_map)
    replaced_underlying = set(upstream_to_variants)
    all_variant_upstream_keys = set(variants_map.keys())

    old_rows = existing.get("machines", []) or []

    # Index old rows three ways so we can find the right seed
    # regardless of input shape: by machine name (covers display
    # names + underlying + legacy-upstream-as-machine), and by
    # upstream_key when the field exists (covers post-v1 rows).
    old_by_machine = {
        r["machine"]: r for r in old_rows
        if isinstance(r, dict) and isinstance(r.get("machine"), str)
    }
    old_by_upstream_key = {
        r["upstream_key"]: r for r in old_rows
        if isinstance(r, dict) and isinstance(r.get("upstream_key"), str) and r["upstream_key"]
    }

    def _seed_for_upstream(upstream_key: str) -> dict:
        """Find the best input row to inherit from for a given
        variant upstream key. Prefer a row whose upstream_key
        matches (exact match), fall back to the old display-named
        row (in case selector_types changed), fall back to a
        legacy row where the upstream key was the machine name,
        and finally fall back to the underlying row."""
        if upstream_key in old_by_upstream_key:
            return old_by_upstream_key[upstream_key]
        if upstream_key in old_by_machine:
            return old_by_machine[upstream_key]
        # Try any display name that currently composes to this key.
        composed = compose_display_name(upstream_key, variants_map, selector_types)
        if composed != upstream_key and composed in old_by_machine:
            return old_by_machine[composed]
        # Fall through to the underlying row (pre-migration seed).
        underlying = variants_map.get(upstream_key)
        if underlying and underlying in old_by_machine:
            return old_by_machine[underlying]
        return {}

    new_rows: list[dict] = []
    stats = {
        "kept_non_variant": 0,
        "kept_variant": 0,
        "rewritten_variant": 0,
        "added_variant": 0,
        "dropped_underlying": 0,
        "missing_selector": [],
    }

    # --- non-variant rows first (anything not tied to variants_map) ---
    # Each row survives iff its machine name is neither a variant
    # upstream key nor a variant-bearing underlying. We also look
    # back through upstream_key to catch existing display-named rows.
    seen_upstream: set[str] = set()
    for row in old_rows:
        if not isinstance(row, dict):
            continue
        mname = row.get("machine")
        uk = row.get("upstream_key") if isinstance(row.get("upstream_key"), str) else None
        # Drop bare underlying rows — they're replaced by variants.
        if mname in replaced_underlying:
            stats["dropped_underlying"] += 1
            continue
        # Drop any row whose upstream_key (or machine-as-legacy-key)
        # is in the variants set — we'll rebuild the variant row
        # below with the canonical shape, inheriting from this one.
        candidate_uk = uk or mname
        if candidate_uk in all_variant_upstream_keys:
            # Skip — will be re-emitted by the variant pass.
            continue
        # Genuine non-variant row. Ensure upstream_key field is set
        # so the new schema is internally consistent.
        if not uk:
            row = dict(row)
            row["upstream_key"] = mname
        new_rows.append(row)
        stats["kept_non_variant"] += 1
        seen_upstream.add(candidate_uk)

    # --- variant rows ---
    for upstream_key in sorted(all_variant_upstream_keys):
        underlying = variants_map[upstream_key]
        selector = selector_types.get(underlying)
        if not selector and underlying not in stats["missing_selector"]:
            stats["missing_selector"].append(underlying)
        display = compose_display_name(upstream_key, variants_map, selector_types)
        seed = _seed_for_upstream(upstream_key)

        new_row = {
            "machine": display,
            "upstream_key": upstream_key,
            "modes": list(seed.get("modes") or [1, 2, 5, 7]),
            "logicClassNames": list(seed.get("logicClassNames") or []),
            "configSummaryMd5": str(seed.get("configSummaryMd5", "")),
            "codeSummaryMd5": str(seed.get("codeSummaryMd5", "")),
            "available": bool(seed.get("available", True)),
        }

        if not seed:
            stats["added_variant"] += 1
        elif seed.get("machine") == display and seed.get("upstream_key") == upstream_key:
            stats["kept_variant"] += 1
        else:
            stats["rewritten_variant"] += 1

        new_rows.append(new_row)

    new_rows.sort(key=lambda r: r.get("machine", ""))
    stats["total_rows"] = len(new_rows)
    stats["missing_selector"].sort()
    return {"machines": new_rows}, stats


def _load_variants_map() -> dict[str, str]:
    """Read variants_map from the halls cache. We intentionally import
    the real loader rather than reparsing here — that way a single
    bugfix to ``load_variants_map`` propagates automatically."""
    from src.web_console.backend.machine_variants import load_variants_map
    return load_variants_map(HALLS_JSON)


def _load_selector_types() -> dict[str, str]:
    from src.web_console.backend.machine_variants import load_selector_types
    return load_selector_types(SELECTOR_TYPES_JSON)


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
    selector_types = _load_selector_types()

    with open(MACHINES_JSON, "r", encoding="utf-8") as f:
        existing = json.load(f)

    new_config, stats = migrate(existing, variants_map, selector_types)

    print(f"variants_map  : {len(variants_map)} entries across "
          f"{len(set(variants_map.values()))} underlying keys")
    print(f"selector_types: {len(selector_types)} entries\n")
    print(f"kept non-variant rows       : {stats['kept_non_variant']}")
    print(f"kept variant rows (no-op)   : {stats['kept_variant']}")
    print(f"rewritten variant rows      : {stats['rewritten_variant']}")
    print(f"added variant rows          : {stats['added_variant']}")
    print(f"dropped bare underlying rows: {stats['dropped_underlying']}")
    print(f"total rows                  : {stats['total_rows']}")
    if stats["missing_selector"]:
        print(
            f"\nWARNING: {len(stats['missing_selector'])} underlying(s) have variants "
            f"but no entry in selector_types — display names fall back to raw "
            f"upstream keys: {stats['missing_selector']}"
        )

    if args.dry_run:
        print(f"\n(dry-run) would write {MACHINES_JSON}")
        # Show a variant sample so operators can eyeball the new shape.
        variants_sample = [
            r for r in new_config["machines"] if "$" in r["machine"]
        ][:3]
        print(json.dumps(variants_sample, indent=2, ensure_ascii=False))
    else:
        MACHINES_JSON.write_text(
            json.dumps(new_config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {MACHINES_JSON}")


if __name__ == "__main__":
    main()
