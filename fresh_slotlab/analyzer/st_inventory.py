"""SpinType inventory extractor (Phase 0a — SpinType-native manifest framework).

Reads a machine's cached rawdata chunks and reports, per mode, the REAL
SpinType inventory: which STs actually appear, how often, and each ST's
FIELD SIGNATURE (which round-level fields are present and at what ratio).

This is ground-truth extraction from real data — it does NOT classify
roles (paid/choice/settlement); role + play assignment is the per-machine
confirmation step (the M15-style 5-gate). The field signature is what lets
the batch workflow decide whether a validated ST parser APPLIES to another
machine's ST (same number ≠ same semantics — see memory/feedback_no_hardcode).

Standalone tool: NOT imported by the report-production closure, so adding it
does NOT flip base_hash.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

# Reuse the canonical round reader — do NOT reinvent chunk parsing.
try:
    from fresh_slotlab.analyzer.core.parser import parse_rounds
except ImportError:  # when fresh_slotlab/ is on sys.path directly
    from analyzer.core.parser import parse_rounds  # type: ignore


def _iter_rounds(chunk_path: Path):
    """Yield each round dict from a cached chunk file (robots → roundResult)."""
    try:
        chunk = json.loads(chunk_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    response = chunk.get("response")
    if not isinstance(response, list):
        return
    for robot in response:
        if not isinstance(robot, dict):
            continue
        for rnd in parse_rounds(robot):
            if isinstance(rnd, dict):
                yield rnd


def extract_st_inventory(
    machine: str, mode: int, rawdata_root: str | Path = "rawdata"
) -> dict[str, Any]:
    """Return the real per-SpinType inventory for (machine, mode).

    Shape::

        {
          "machine": "M15", "mode": 1,
          "rounds_scanned": 40000,
          "spin_types": {
            "1":  {"count": 39560, "field_presence": {"SpinType": 1.0, "BetAmount": 1.0, ...}},
            "14": {"count": 880,   "field_presence": {"DollarCount": 1.0, "ChosenDollar": 1.0, ...}},
            "15": {"count": 440,   "field_presence": {"WinAmount": 1.0, ...}}
          }
        }
    """
    mode_dir = Path(rawdata_root) / machine / f"mode_{mode}"
    chunks = sorted(mode_dir.glob("chunk_*.json"))
    st_count: dict[int, int] = defaultdict(int)
    st_field_count: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total = 0
    for cf in chunks:
        for rnd in _iter_rounds(cf):
            total += 1
            try:
                st = int(rnd.get("SpinType", 0) or 0)
            except (TypeError, ValueError):
                st = 0
            st_count[st] += 1
            for field in rnd.keys():
                st_field_count[st][field] += 1

    spin_types: dict[str, Any] = {}
    for st in sorted(st_count):
        n = st_count[st]
        presence = {
            f: round(c / n, 4) for f, c in sorted(st_field_count[st].items())
        }
        spin_types[str(st)] = {"count": n, "field_presence": presence}

    return {
        "machine": machine,
        "mode": mode,
        "chunks_scanned": len(chunks),
        "rounds_scanned": total,
        "spin_types": spin_types,
    }


def signature(st_entry: dict[str, Any], min_ratio: float = 0.99) -> frozenset[str]:
    """The applicability signature of an ST = the set of fields present in
    (nearly) every record of that ST. Two STs with the same signature are
    parsed by the same validated parser; a mismatch means 'new shape →
    needs per-machine confirmation' (never silently reuse by ST number)."""
    return frozenset(
        f for f, r in st_entry.get("field_presence", {}).items() if r >= min_ratio
    )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Extract real SpinType inventory from cached rawdata.")
    ap.add_argument("machine")
    ap.add_argument("mode", type=int)
    ap.add_argument("--rawdata-root", default="rawdata")
    args = ap.parse_args()
    inv = extract_st_inventory(args.machine, args.mode, args.rawdata_root)
    print(json.dumps(inv, indent=2, ensure_ascii=False))
