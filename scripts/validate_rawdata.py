"""Validate that the analyzer can process all rawdata without crashing.

Runs parse_chunk_response() on every machine's chunk file and reports
basic metrics, extra fields, and SpinType coverage. Does NOT generate
full reports (no output-dir / no bankruptcy probe / no guideline check).

Usage:
    python scripts/validate_rawdata.py
    python scripts/validate_rawdata.py --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fresh_slotlab.analyzer.core.parser import parse_chunk_response  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rawdata-dir", type=Path, default=ROOT / "rawdata")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    rawdata = args.rawdata_dir
    if not rawdata.exists():
        raise SystemExit(f"rawdata dir not found: {rawdata}")

    machines = sorted(
        [d for d in rawdata.iterdir() if d.is_dir()],
        key=lambda d: int(d.name[1:]) if d.name[1:].isdigit() else 0,
    )

    ok_count = 0
    fail_count = 0
    skip_count = 0
    total_extra_fields: dict[str, int] = defaultdict(int)
    all_spin_types: Counter[int] = Counter()
    failures: list[tuple[str, str]] = []
    t0 = time.time()

    for machine_dir in machines:
        machine = machine_dir.name
        # Find any mode dir with a chunk file
        chunk_files = list(machine_dir.glob("*/chunk_0001.json"))
        if not chunk_files:
            skip_count += 1
            if args.verbose:
                print(f"  [SKIP] {machine}: no chunk file")
            continue

        for chunk_path in chunk_files:
            mode_dir = chunk_path.parent.name  # e.g. "mode_2"
            try:
                raw = json.loads(chunk_path.read_text(encoding="utf-8"))
                resp = raw["response"]
                bet = int(raw.get("_bet", 1000) or 1000)
                result = parse_chunk_response(resp, 1, bet)

                if not result.get("ok"):
                    fail_count += 1
                    err = result.get("error", "unknown")
                    failures.append((f"{machine}/{mode_dir}", err))
                    print(f"  [FAIL] {machine}/{mode_dir}: {err}")
                    continue

                ok_count += 1
                spins = result["spins"]
                rtp = (result["win"] / result["bet"]) * 100 if result["bet"] > 0 else 0
                st_count = len(result.get("spin_type_spins", {}))
                extra = result.get("extra_fields_seen", {})
                extra_names = sorted(extra.keys())

                for st, cnt in (result.get("spin_type_spins") or {}).items():
                    all_spin_types[int(st)] += int(cnt)
                for fld, cnt in extra.items():
                    total_extra_fields[fld] += cnt

                if args.verbose:
                    extra_str = f" extra=[{','.join(extra_names)}]" if extra_names else ""
                    print(
                        f"  [OK] {machine}/{mode_dir}: "
                        f"{spins:,} spins, RTP={rtp:.1f}%, "
                        f"{st_count} SpinTypes{extra_str}"
                    )

            except Exception as exc:
                fail_count += 1
                failures.append((f"{machine}/{mode_dir}", str(exc)))
                print(f"  [FAIL] {machine}/{mode_dir}: {exc}")

    elapsed = time.time() - t0

    print()
    print(f"=== Validation Summary ({elapsed:.1f}s) ===")
    print(f"OK: {ok_count}  |  FAIL: {fail_count}  |  SKIP: {skip_count}")
    print(f"Unique SpinTypes: {len(all_spin_types)}")
    print(f"Machines with extra fields: {len([f for f in total_extra_fields])}")

    if failures:
        print(f"\nFailures ({len(failures)}):")
        for name, err in failures:
            print(f"  {name}: {err}")

    print(f"\nTop extra fields:")
    for fld, cnt in sorted(total_extra_fields.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {fld}: {cnt:,}")

    if fail_count:
        sys.exit(1)


if __name__ == "__main__":
    main()
