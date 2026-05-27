"""validate_manifests.py — Phase 3 item 8.

Fleet-wide validation of every manifest in
``slot_designer/configs/machine_manifests/`` against the 11 rules
shipped in P2-A2 (architecture proposal v5 §5.6).

Reads:
- ``configs/machines.json`` (fleet roster, for Rule 1)
- ``slot_designer/configs/machine_manifests/*.json`` (all manifests)

Reports:
- per-manifest error list (rule number + machine + message)
- summary counts (manifests scanned / clean / with errors / total error count)

Exit codes:
- ``0`` — all manifests pass validation
- ``1`` — at least one manifest has an error
- ``2`` — script error (file missing, malformed JSON, etc.)

Run::

    python scripts/validate_manifests.py
    python scripts/validate_manifests.py --quiet  # only print summary
    python scripts/validate_manifests.py --json   # machine-readable output
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow ``python scripts/validate_manifests.py`` from the repo root by
# adding the parent dir to sys.path. (When invoked as ``python -m
# scripts.validate_manifests`` the import resolves natively without
# this; the path-injection is the friendlier UX.)
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Trigger Wave 2c feature registrations so Rule 2/4/5/8 (feature-ID
# membership checks) operate against the live registry.
import fresh_slotlab.analyzer.features.payouts_by_spin_type  # noqa: F401
import fresh_slotlab.analyzer.features.reel_marginal_by_spin_type  # noqa: F401
import fresh_slotlab.analyzer.features.bankruptcy_simulation  # noqa: F401
import fresh_slotlab.analyzer.features.multiplier_profile  # noqa: F401
import fresh_slotlab.analyzer.features.multiplier_wild  # noqa: F401  # C3.5
import fresh_slotlab.analyzer.features.machine_mechanics  # noqa: F401  # C4
import fresh_slotlab.analyzer.features.upstream_feature_breakdown  # noqa: F401  # C5
import fresh_slotlab.analyzer.features.collect_mechanic  # noqa: F401  # C5
import fresh_slotlab.analyzer.features.bonus_chain_dynamics  # noqa: F401  # C6

from fresh_slotlab.analyzer import feature_registry as _registry
from fresh_slotlab.analyzer.manifest_loader import (
    load_manifest,
    resolve_inheritance,
    validate_manifest,
)


ROOT = Path(__file__).resolve().parent.parent
MACHINES_JSON = ROOT / "configs" / "machines.json"
MANIFEST_DIR = ROOT / "slot_designer" / "configs" / "machine_manifests"


def _list_manifest_ids(manifest_dir: Path) -> list[str]:
    """Return sorted machine IDs (stem of every <id>.json in the dir).

    Excludes ``manifest_schema.json`` and any file in a subdirectory.
    """
    ids: list[str] = []
    for f in sorted(manifest_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix != ".json":
            continue
        if f.name == "manifest_schema.json":
            continue
        ids.append(f.stem)
    return ids


def validate_fleet(
    manifest_dir: Path = MANIFEST_DIR,
    machines_json: Path = MACHINES_JSON,
) -> tuple[dict[str, list[Any]], dict[str, int]]:
    """Return ``(per_machine_errors, counts)``.

    ``per_machine_errors`` maps machine_id → list of ValidationError items
    (empty if the machine passed all rules). ``counts`` has fields
    ``total``, ``clean``, ``with_errors``, ``total_error_count``.
    """
    machines_config = json.loads(machines_json.read_text(encoding="utf-8"))
    machine_ids = _list_manifest_ids(manifest_dir)

    per_machine_errors: dict[str, list[Any]] = {}
    for mid in machine_ids:
        manifest = load_manifest(mid, manifest_dir)
        if manifest.get("inherits_from"):
            resolved = resolve_inheritance(manifest, manifest_dir)
            errors = validate_manifest(
                resolved,
                machines_config=machines_config,
                registry=_registry,
                pre_resolved=False,
            )
        else:
            errors = validate_manifest(
                manifest,
                machines_config=machines_config,
                registry=_registry,
            )
        per_machine_errors[mid] = errors

    counts = {
        "total": len(machine_ids),
        "clean": sum(1 for errs in per_machine_errors.values() if not errs),
        "with_errors": sum(1 for errs in per_machine_errors.values() if errs),
        "total_error_count": sum(len(errs) for errs in per_machine_errors.values()),
    }
    return per_machine_errors, counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=MANIFEST_DIR,
        help=f"Manifests directory (default: {MANIFEST_DIR}).",
    )
    parser.add_argument(
        "--machines-json",
        type=Path,
        default=MACHINES_JSON,
        help=f"Fleet roster path (default: {MACHINES_JSON}).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print the summary line; suppress per-machine details.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output (per-manifest errors + summary as JSON).",
    )
    args = parser.parse_args()

    try:
        per_machine, counts = validate_fleet(args.manifest_dir, args.machines_json)
    except FileNotFoundError as exc:
        print(f"[validate_manifests] error: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"[validate_manifests] malformed JSON: {exc}", file=sys.stderr)
        return 2

    if args.json:
        out = {
            "summary": counts,
            "per_machine": {
                mid: [str(e) for e in errs]
                for mid, errs in per_machine.items() if errs
            },
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        if not args.quiet:
            for mid, errs in sorted(per_machine.items()):
                if not errs:
                    continue
                print(f"\n[{mid}] {len(errs)} error(s):")
                for e in errs:
                    print(f"  - {e}")
        print(
            f"\nSummary: {counts['clean']}/{counts['total']} clean, "
            f"{counts['with_errors']} with errors "
            f"({counts['total_error_count']} total errors)"
        )

    return 0 if counts["with_errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
