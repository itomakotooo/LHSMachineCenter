"""Prune old report version dirs — keep newest N per (machine, mode).

Every `batch_generate_reports --force` run and every fresh
`/api/reports/import` appends a new `rv_<ts>_...` dir. Over time this
linearly eats disk even though only the newest version is useful. This
script applies the retention policy and keeps DB + filesystem in sync.

Usage:
    python scripts/prune_report_versions.py --keep 5               # apply
    python scripts/prune_report_versions.py --keep 5 --dry-run     # preview
    python scripts/prune_report_versions.py --keep 3 --reports-root dev_reports

Dry-run first if you don't trust the math. The full listing of targets
is in the `deleted_paths` field of the returned report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--keep", type=int, default=5,
                        help="versions to retain per (machine, mode), default 5")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would be deleted, don't touch disk/DB")
    parser.add_argument("--reports-root", type=Path,
                        default=ROOT / "reports")
    parser.add_argument("--db-path", type=Path, default=None,
                        help="console.db path (default: <ROOT>/state/console/console.db)")
    args = parser.parse_args()

    if args.keep < 1:
        raise SystemExit("--keep must be >= 1")
    if not args.reports_root.is_dir():
        raise SystemExit(f"reports root not found: {args.reports_root}")

    from src.web_console.backend.app import StateStore
    from src.web_console.backend.reports_retention import prune_versions

    db_path = args.db_path or (ROOT / "state" / "console" / "console.db")
    if not db_path.exists():
        raise SystemExit(
            f"console.db not found at {db_path}; "
            "pass --db-path to override"
        )
    store = StateStore(db_path)
    result = prune_versions(
        reports_root=args.reports_root,
        store=store,
        keep_last=args.keep,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))

    prefix = "[DRY-RUN] " if args.dry_run else ""
    print()
    print(
        f"{prefix}kept={result['versions_kept']} "
        f"deleted={result['versions_deleted']} "
        f"db_rows_deleted={result['db_rows_deleted']} "
        f"skipped_active={result['skipped_active_runs']} "
        f"errors={len(result['errors'])}"
    )


if __name__ == "__main__":
    main()
