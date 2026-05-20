"""manifest_lint.py — Phase 3 item 9.

Lint checks for the per-machine manifest fleet. Builds on
``validate_manifests.py`` (hard schema rules) with softer best-practice
checks:

- **L1** Bootstrap markers should be cleaned up. Any manifest with
  ``_generator_notes.cluster_review_pending: true`` is flagged as
  "needs operator review" — manifests should not ship to production
  with the generator's review-pending marker still set.
- **L2** Stale override metadata. Variants with
  ``console_diagnostic_complete_override: false`` must have
  ``override_set_at`` (ISO-8601), ``override_set_reason`` (non-empty),
  and ``override_set_by`` (non-empty). Per architecture proposal v5
  section 5.5.7.
- **L3** Override age > 90 days warrants a quarterly QA review.
  Manifests with ``override_set_at`` older than 90 days are flagged
  per the quarterly QA cadence noted in architecture proposal v5
  section 5.5.7.
- **L4** SC-Vanilla manifest should be flippable. SC-Vanilla cluster
  members (``_generator_notes.sc_vanilla: true``) with
  ``console_diagnostic_complete: false`` are reminder candidates for
  Phase 3 item 0 (run RTP gate, flip to true).

Exit codes:
- ``0`` — no lint findings
- ``1`` — at least one lint finding
- ``2`` — script error
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = ROOT / "slot_designer" / "configs" / "machine_manifests"

STALE_OVERRIDE_DAYS = 90


def _iter_manifests(manifest_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for f in sorted(manifest_dir.iterdir()):
        if not f.is_file() or f.suffix != ".json":
            continue
        if f.name == "manifest_schema.json":
            continue
        out.append((f.stem, json.loads(f.read_text(encoding="utf-8"))))
    return out


def lint_manifest(machine_id: str, manifest: dict[str, Any]) -> list[str]:
    """Return a list of lint findings (empty if clean)."""
    findings: list[str] = []
    notes = manifest.get("_generator_notes") or {}

    # L1: bootstrap review marker still set.
    if notes.get("cluster_review_pending"):
        findings.append(
            "L1: _generator_notes.cluster_review_pending=true (per-machine "
            "review pending — manifest still has generator defaults)."
        )

    # L2: override metadata completeness.
    if manifest.get("console_diagnostic_complete_override") is False:
        missing = []
        for field in ("override_set_at", "override_set_reason", "override_set_by"):
            value = manifest.get(field)
            if not value or (isinstance(value, str) and not value.strip()):
                missing.append(field)
        if missing:
            findings.append(
                f"L2: console_diagnostic_complete_override=false but missing "
                f"required metadata: {missing}. Per section 5.5.7."
            )

    # L3: override age > 90 days → quarterly QA candidate.
    override_at = manifest.get("override_set_at")
    if override_at:
        try:
            # Accept Z suffix and naive ISO strings.
            stamp = datetime.fromisoformat(override_at.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(tz=timezone.utc) - stamp).days
            if age_days > STALE_OVERRIDE_DAYS:
                findings.append(
                    f"L3: override_set_at age={age_days}d > "
                    f"{STALE_OVERRIDE_DAYS}d. Quarterly QA review per "
                    f"section 5.5.7."
                )
        except (TypeError, ValueError):
            findings.append(
                f"L3: override_set_at={override_at!r} not parseable as "
                "ISO-8601 timestamp."
            )

    # L4: SC-Vanilla flip reminder.
    if (
        notes.get("sc_vanilla")
        and manifest.get("console_diagnostic_complete") is False
    ):
        findings.append(
            "L4: SC-Vanilla member with console_diagnostic_complete=false. "
            "Run rtp_integrity.py and flip to true (Phase 3 item 0)."
        )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=MANIFEST_DIR,
        help=f"Manifests directory (default: {MANIFEST_DIR}).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print the summary line; suppress per-machine findings.",
    )
    parser.add_argument(
        "--rule",
        choices=["L1", "L2", "L3", "L4"],
        help="Show only findings of this rule (filter).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable JSON output.",
    )
    args = parser.parse_args()

    try:
        manifests = _iter_manifests(args.manifest_dir)
    except FileNotFoundError as exc:
        print(f"[manifest_lint] {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"[manifest_lint] malformed JSON: {exc}", file=sys.stderr)
        return 2

    per_machine: dict[str, list[str]] = {}
    for mid, manifest in manifests:
        findings = lint_manifest(mid, manifest)
        if args.rule:
            findings = [f for f in findings if f.startswith(args.rule + ":")]
        if findings:
            per_machine[mid] = findings

    total = len(manifests)
    affected = len(per_machine)
    total_findings = sum(len(fs) for fs in per_machine.values())

    if args.json:
        print(json.dumps(
            {"summary": {"total": total, "affected": affected,
                         "total_findings": total_findings},
             "per_machine": per_machine},
            indent=2, ensure_ascii=False,
        ))
    else:
        if not args.quiet:
            for mid, findings in sorted(per_machine.items()):
                print(f"\n[{mid}]")
                for f in findings:
                    print(f"  - {f}")
        print(
            f"\nLint summary: {affected}/{total} manifests with findings "
            f"({total_findings} total)"
        )

    return 0 if affected == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
