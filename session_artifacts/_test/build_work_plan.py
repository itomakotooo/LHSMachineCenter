"""One-shot generator: produces work_plan.csv for the 255 representative reps.

Usage (from any cwd):
    python build_work_plan.py

Reads configs/machines.json + rawdata/ from MAIN_REPO_ROOT (NOT the worktree),
picks one rep per variant family (alphabetically first member; the bare-name
non-variant always wins because '$' sorts after no '$'), classifies each rep
as `copy_from_main` (cache available) or `fresh_sample` (no chunks), and
writes work_plan.csv next to this script.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

MAIN_REPO = Path(r"C:/Users/pangg/Documents/Projects/LHS/User_Managerment_GPT")
HERE = Path(__file__).resolve().parent
OUT_CSV = HERE / "work_plan.csv"


def main() -> None:
    cfg = json.loads((MAIN_REPO / "configs" / "machines.json").read_text(encoding="utf-8"))
    machines = [m for m in cfg["machines"] if m.get("available", True)]

    # Group all machines by family (split on '$' → first segment). For
    # non-variants, family == machine; for variants, family is the underlying
    # name (e.g. M102$WheelSelector$0$ → M102). Pick the alphabetically first
    # member per family. When a family has both a bare 'M102' and 'M102$...'
    # variants, the bare name sorts first because '$' is lexicographically
    # after the empty continuation.
    families: dict[str, list[str]] = defaultdict(list)
    for m in machines:
        fam = m["machine"].split("$")[0]
        families[fam].append(m["machine"])

    rows = []
    for fam, members in families.items():
        chosen = sorted(members)[0]
        mode_dir = MAIN_REPO / "rawdata" / chosen / "mode_1"
        has_chunks = mode_dir.exists() and any(
            p.name != "_chunks.json" and p.name.startswith("chunk_")
            for p in mode_dir.glob("chunk_*.json*")
        )
        rows.append({
            "machine": chosen,
            "mode": 1,
            "family": fam,
            "is_representative": True,
            "source": "copy_from_main" if has_chunks else "fresh_sample",
            "status": "pending",
            "run_id": "",
            "summary_path": "",
            "duration_s": "",
            "error": "",
        })

    rows.sort(key=lambda r: r["machine"])
    fields = [
        "machine", "mode", "family", "is_representative",
        "source", "status", "run_id", "summary_path", "duration_s", "error",
    ]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    copy = sum(1 for r in rows if r["source"] == "copy_from_main")
    fresh = sum(1 for r in rows if r["source"] == "fresh_sample")
    print(f"wrote {OUT_CSV} : {len(rows)} reps  "
          f"({copy} copy_from_main, {fresh} fresh_sample)")


if __name__ == "__main__":
    main()
