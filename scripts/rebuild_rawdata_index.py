"""Rebuild `dev_rawdata/_index.json` from scratch by rescanning every chunk.

Use when the index got out of sync — e.g. after external deletes, manual
file copies, or if you just don't trust what's in there. The writer path
(`_save_chunk_cache`) and the reader path (`check_rawdata_status` cold
branch) already self-heal in normal operation; this is the "big hammer"
for when you want a clean baseline.

Usage:
    python scripts/rebuild_rawdata_index.py
    python scripts/rebuild_rawdata_index.py --rawdata-dir ./some_other_root
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rawdata-dir", type=Path,
                        default=ROOT / "dev_rawdata")
    args = parser.parse_args()

    if not args.rawdata_dir.is_dir():
        raise SystemExit(f"rawdata dir not found: {args.rawdata_dir}")

    from fresh_slotlab.rawdata_index import rebuild_full

    t0 = time.time()
    data = rebuild_full(args.rawdata_dir)
    elapsed = time.time() - t0
    n = len(data.get("entries", {}))
    print(f"Rebuilt index at {args.rawdata_dir / '_index.json'}")
    print(f"  entries: {n}")
    print(f"  elapsed: {elapsed:.2f}s")


if __name__ == "__main__":
    main()
