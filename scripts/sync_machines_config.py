"""Sync configs/machines.json from .probe/machine_config_md5_snapshot.json.

Usage:
    python scripts/sync_machines_config.py
    python scripts/sync_machines_config.py --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / ".probe" / "machine_config_md5_snapshot.json"
MACHINES_JSON = ROOT / "configs" / "machines.json"

# Machines confirmed to 500 on both mode 1 and mode 2 on dev server
UNAVAILABLE_MACHINES = {
    "M29", "M45", "M49", "M52", "M55", "M56", "M68", "M69", "M77",
    "M80", "M81", "M82", "M83", "M85", "M89", "M91", "M92",
    "M115", "M118", "M141", "M143", "M205", "M230",
}

DEFAULT_MODES = [1, 2, 5, 7]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print but don't write")
    args = parser.parse_args()

    with open(SNAPSHOT, "r", encoding="utf-8") as f:
        snapshot = json.load(f)

    machines = []
    for key in sorted(snapshot.keys(), key=lambda k: int(k[1:]) if k[1:].isdigit() else 0):
        entry = snapshot[key]
        logic = entry.get("logicClassNames", [])
        available = bool(logic) and key not in UNAVAILABLE_MACHINES

        machines.append({
            "machine": key,
            "modes": DEFAULT_MODES if available else [],
            "logicClassNames": logic,
            "configSummaryMd5": entry.get("configSummaryMd5", ""),
            "codeSummaryMd5": entry.get("codeSummaryMd5", ""),
            "available": available,
        })

    result = {"machines": machines}

    available_count = sum(1 for m in machines if m["available"])
    unavailable_count = len(machines) - available_count

    if args.dry_run:
        print(f"Would write {len(machines)} machines "
              f"({available_count} available, {unavailable_count} unavailable) "
              f"to {MACHINES_JSON}")
        print(json.dumps(result["machines"][:3], indent=2, ensure_ascii=False))
        print(f"... and {len(machines) - 3} more")
    else:
        MACHINES_JSON.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {len(machines)} machines "
              f"({available_count} available, {unavailable_count} unavailable) "
              f"to {MACHINES_JSON}")


if __name__ == "__main__":
    main()
