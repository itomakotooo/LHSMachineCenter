"""generate_machine_manifests.py — Phase 3 item 1.

Generate 393 per-machine manifest JSON files at
``slot_designer/configs/machine_manifests/<machine_id>.json`` from
``configs/machines.json``.

Per `04_architecture_proposal_v5.md §5.5` + §6.3.3 item 1. This is a
bootstrap pass that produces conservative defaults; per-machine review
follows. All non-variant machines ship ``console_diagnostic_complete:
false`` initially. Phase 3 item 0 (rtp_integrity verification) flips
the SC-Vanilla cluster to ``true`` after empirical verification.

Variants get ``inherits_from`` pointing at the underlying machine's
manifest (eager cascade per §5.5.5). Variants do NOT set
``console_diagnostic_complete_override`` unless the underlying needs an
exception (covered in a separate per-variant review pass).

Run::

    python scripts/generate_machine_manifests.py

Default writes to ``slot_designer/configs/machine_manifests/<machine_id>.json``.
Pass ``--dry-run`` to print what would be written without touching disk.
Pass ``--force`` to overwrite existing manifest files (default is
write-only-if-absent so a manual edit is never clobbered).

No imports from ``fresh_slotlab.analyzer`` — this is a one-shot script,
not part of the analyzer runtime. Side-effect-free at import per
memory ``feedback_subprocess_import_suicide_and_module_globals.md``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# Project root resolved relative to this script (scripts/ is one level deep).
ROOT = Path(__file__).resolve().parent.parent
MACHINES_JSON = ROOT / "configs" / "machines.json"
MANIFEST_DIR = ROOT / "slot_designer" / "configs" / "machine_manifests"

# Per §5.5.2: SC-Vanilla cluster identification.
# Source: 02_taxonomy.md §3.2 F-Plain + §4.2 super-cluster SC-Vanilla.
F_PLAIN_LOGIC_CLASS_NAMES = frozenset({
    "NormalRTPPreProcessor",
    "NormalSpinGenerator",
    "NormalSpinValidator",
})


# Default universal feature list (Wave 2c shipped 4 of these).
# Per §5.5.6 analyzer_features. Bespoke features layer on per-cluster.
UNIVERSAL_FEATURES_DEFAULT: list[str] = [
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "bankruptcy_simulation",
    "multiplier_profile",
]


def is_variant(machine_id: str) -> bool:
    """Variants encode underlying via dollar separator: 'M273$WheelSelector$42$'."""
    return "$" in machine_id


def underlying_of_variant(machine_id: str) -> str:
    """First segment before the dollar is the underlying machine id."""
    return machine_id.split("$", 1)[0]


def is_sc_vanilla(machine_record: dict[str, Any]) -> bool:
    """SC-Vanilla cluster per §3.2 F-Plain + §4.2."""
    return set(machine_record.get("logicClassNames", [])) == F_PLAIN_LOGIC_CLASS_NAMES


def build_underlying_manifest(machine_record: dict[str, Any]) -> dict[str, Any]:
    """Non-variant machine manifest.

    SC-Vanilla cluster (single-paytype machines with the plain F-Plain
    logic-class names) ships ``console_diagnostic_complete: true``: these
    are the 45 simplest machines in the fleet, in production for years
    with no known correctness issues. Operator UI surfaces them as
    "verified — reports treated as authoritative".

    Other clusters ship with ``console_diagnostic_complete: false`` AND
    ``_generator_notes.config_not_reviewed: true``. The latter is the
    frontend signal that this machine's integrity contract uses
    bootstrap defaults that have not been per-machine reviewed yet;
    integrity-check results render as soft-confidence hints rather
    than authoritative pass/fail.

    Default ``expected_paid_st: [1]`` for both clusters — paid=1 is the
    overwhelming convention per the taxonomy. A handful of machines
    have paid=non-1 (M99=96, M272=140); per-machine reviewers fix
    those when they triage the ``config_not_reviewed`` flag.
    """
    machine_id = machine_record["machine"]
    modes = sorted(machine_record.get("modes", []))
    sc_vanilla = is_sc_vanilla(machine_record)
    is_synthetic_template = machine_record.get("_synthetic_underlying", False)

    # Per user direction 2026-05-20: flip SC-Vanilla cluster to
    # console_diagnostic_complete=true on Day-1 bootstrap. These 45
    # machines have been in production for years; the daily empirical
    # verification step (item 0 in the architecture proposal) is folded
    # into the operator's normal report-review workflow rather than
    # gated upfront.
    console_diagnostic_complete = bool(sc_vanilla) and not is_synthetic_template

    manifest: dict[str, Any] = {
        "machine_id": machine_id,
        "manifest_version": 1,
        "inherits_from": None,
        "console_diagnostic_complete": console_diagnostic_complete,
        "layer4_applicable": True,
        "spin_type_convention": {
            "paid": [1],
            "bonus": [],
        },
        "trigger_session_pattern": None,
        "analyzer_features": list(UNIVERSAL_FEATURES_DEFAULT),
        "rtp_integrity_contract": {
            "required_attribution_anchors": [],
            "expected_paid_st": [1],
            "expected_bonus_st": [],
            "fallback_pct_warn_threshold": 0.5,
            "fallback_pct_fail_threshold": 5.0,
        },
        "modes": modes,
        "_generator_notes": {
            # config_not_reviewed: frontend renders integrity-check
            # results with reduced visual weight ("hint" not "alert")
            # because the manifest's integrity contract is bootstrap
            # defaults not per-machine confirmation. Flips to false
            # when a reviewer opens this manifest and confirms the
            # values match observed rawdata.
            "config_not_reviewed": not sc_vanilla and not is_synthetic_template,
            "sc_vanilla": sc_vanilla,
            "synthetic_template": is_synthetic_template,
            "bootstrap_source": "scripts/generate_machine_manifests.py",
            "bootstrap_version": "phase3_item1_2026-05-20",
        },
    }
    return manifest


def build_variant_manifest(machine_record: dict[str, Any]) -> dict[str, Any]:
    """Variant manifest — eager cascade per §5.5.5; inherits_from underlying."""
    machine_id = machine_record["machine"]
    underlying = underlying_of_variant(machine_id)
    modes = sorted(machine_record.get("modes", []))
    return {
        "machine_id": machine_id,
        "manifest_version": 1,
        "inherits_from": f"{underlying}.json",
        # Per §5.5.7 rule 6: variants do NOT set
        # console_diagnostic_complete_override unless a per-variant
        # regression has been observed. Default: omit the field so
        # the variant inherits from the underlying.
        "modes": modes,
        "_generator_notes": {
            "underlying": underlying,
            "bootstrap_source": "scripts/generate_machine_manifests.py",
            "bootstrap_version": "phase3_item1_2026-05-19",
        },
    }


def generate_one(
    machine_record: dict[str, Any],
    out_dir: Path,
    *,
    force: bool,
    dry_run: bool,
) -> tuple[str, str]:
    """Return ``(machine_id, action)`` where action is one of
    ``written``, ``skipped_exists``, ``would_write``, ``would_skip``."""
    machine_id = machine_record["machine"]
    if is_variant(machine_id):
        manifest = build_variant_manifest(machine_record)
    else:
        manifest = build_underlying_manifest(machine_record)

    # Filename: literal machine_id (including $ for variants). The
    # manifest_loader reads <machine_id>.json directly so the name
    # must match. NTFS / ext4 / APFS all accept $; this is the canonical
    # storage scheme per §5.5.4 manifest filename pattern.
    out_path = out_dir / f"{machine_id}.json"

    if out_path.exists() and not force:
        return (machine_id, "would_skip" if dry_run else "skipped_exists")

    if dry_run:
        return (machine_id, "would_write")

    out_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return (machine_id, "written")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--machines-json",
        type=Path,
        default=MACHINES_JSON,
        help=f"Path to machines.json (default: {MACHINES_JSON}).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=MANIFEST_DIR,
        help=f"Output directory (default: {MANIFEST_DIR}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing manifest files. Default is skip-if-exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without touching disk.",
    )
    args = parser.parse_args()

    machines_doc = json.loads(args.machines_json.read_text(encoding="utf-8"))
    machines = machines_doc["machines"]

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: collect underlyings referenced by variants but absent from
    # machines.json. Per §5.5.5 eager cascade, every variant's
    # inherits_from MUST resolve to a manifest on disk. The fleet's
    # machines.json typically does not enumerate underlying machines
    # separately — they are template-only. Synthesize stub underlying
    # manifests so the variant cascade resolves correctly.
    fleet_ids = {r["machine"] for r in machines}
    underlying_stubs: dict[str, dict[str, Any]] = {}
    for record in machines:
        machine_id = record["machine"]
        if not is_variant(machine_id):
            continue
        underlying = underlying_of_variant(machine_id)
        if underlying in fleet_ids:
            continue
        # Aggregate modes from all variants of this underlying so the
        # stub covers the union.
        if underlying not in underlying_stubs:
            underlying_stubs[underlying] = {
                "machine": underlying,
                "modes": [],
                "logicClassNames": [],
                "_synthetic_underlying": True,
            }
        for mode in record.get("modes", []):
            if mode not in underlying_stubs[underlying]["modes"]:
                underlying_stubs[underlying]["modes"].append(mode)

    counts = {
        "written": 0,
        "skipped_exists": 0,
        "would_write": 0,
        "would_skip": 0,
    }
    for record in machines:
        _mid, action = generate_one(
            record, args.out_dir, force=args.force, dry_run=args.dry_run,
        )
        counts[action] = counts.get(action, 0) + 1

    # Write synthesized underlying stubs after the fleet so eager cascade
    # resolves on next load. These are conservative defaults; per-machine
    # review pending.
    for underlying_record in underlying_stubs.values():
        _mid, action = generate_one(
            underlying_record, args.out_dir, force=args.force, dry_run=args.dry_run,
        )
        counts[action] = counts.get(action, 0) + 1

    print(
        f"machines processed: {len(machines)}\n"
        f"synthesized underlyings: {len(underlying_stubs)}\n"
        f"  written:          {counts['written']}\n"
        f"  skipped_exists:   {counts['skipped_exists']}\n"
        f"  would_write:      {counts['would_write']}\n"
        f"  would_skip:       {counts['would_skip']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
