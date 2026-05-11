"""Stage 8 narrative review helper.

Walks each per-mode chunk_0001.json, decodes the round-by-round sequence,
and prints (a) per-round outcome (W=win bet-multiple, B=blank, F=feature
trigger) for narrative inspection, (b) round-class summary (hits / dry
streaks / feature triggers / bucket distribution).

Usage:
    python session_artifacts/M15/scripts/stage8_narrative.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SLOT_DESIGNER = ROOT / "slot_designer"
DEV_SCRATCH = SLOT_DESIGNER / "_dev_scratch" / "rawdata"

MODES = [1, 7, 2, 5]
MACHINES = {1: "M15_stage8_m1", 7: "M15_stage8_m7", 2: "M15_stage8_m2", 5: "M15_stage8_m5"}
BIG_MACHINES = {1: "M15_stage8_big_m1", 7: "M15_stage8_big_m7",
                2: "M15_stage8_big_m2", 5: "M15_stage8_big_m5"}


def parse_rounds(chunk_path: Path) -> list[dict]:
    raw = json.loads(chunk_path.read_text(encoding="utf-8"))
    rounds = []
    for resp in raw.get("response", []):
        round_str = resp.get("roundResult", "")
        rs = json.loads(round_str)
        for r in rs:
            rounds.append(r)
    return rounds


def classify_round(r: dict) -> tuple[str, float]:
    """Return (tag, win_x_bet) where tag in {BLANK, WIN, FEATURE_TRIGGER}.

    NOTE: feature continuation rounds (ST=14, ST=15) are filtered out
    upstream; we only get ST=1 paid rounds and ST=15 session-end markers
    here. Tag logic:
      - WinCredits > 0 and SpinType == 1: WIN
      - ReMarks contains "trigger" or feature topdollar landing on R3:
        FEATURE_TRIGGER (we infer from StopSymbolsByCol[2] containing "topdollar")
      - else: BLANK
    """
    cost = r.get("CostCredits", 0)
    win = r.get("WinCredits", 0)
    st = r.get("SpinType", 1)
    cols = r.get("StopSymbolsByCol", ["", "", ""])

    # FEATURE_TRIGGER signal: topdollar lands at R3 mid (payline) — the ST=1
    # paid round that triggered + we cancelled win amount lookup since sim
    # output uses ST=15 marker per session_semantics
    r3_mid = cols[2].split("-")[1] if len(cols) > 2 and cols[2] else ""
    if "topdollar" in (cols[2] if len(cols) > 2 else ""):
        # any topdollar visible on R3 (any row) — narrative-relevant
        pass
    # accurate trigger detection: topdollar on payline (mid row) per M15 spec
    if r3_mid == "topdollar":
        return ("FEATURE_TRIGGER", win / cost if cost else 0.0)

    if win > 0:
        return ("WIN", win / cost if cost else 0.0)
    return ("BLANK", 0.0)


def summarize_mode(mode: int, machine_map: dict = MACHINES, label: str = "small") -> None:
    machine = machine_map[mode]
    chunk_path = DEV_SCRATCH / machine / f"mode_{mode}" / "chunk_0001.json"
    if not chunk_path.exists():
        print(f"[mode {mode}] chunk file missing: {chunk_path}")
        return

    rounds = parse_rounds(chunk_path)
    # Filter to ST=1 paid rounds only
    paid = [r for r in rounds if r.get("SpinType") == 1]

    n_total = len(paid)
    tags = [classify_round(r) for r in paid]
    wins = [t for t in tags if t[0] == "WIN"]
    triggers = [t for t in tags if t[0] == "FEATURE_TRIGGER"]
    blanks = [t for t in tags if t[0] == "BLANK"]

    # Bucket distribution
    bucket_counts = {
        "blank": len(blanks),
        "win_lt5x": sum(1 for _, x in wins if x < 5.0),
        "win_5x_50x": sum(1 for _, x in wins if 5.0 <= x < 50.0),
        "win_50x_200x": sum(1 for _, x in wins if 50.0 <= x < 200.0),
        "win_ge200x": sum(1 for _, x in wins if x >= 200.0),
    }

    # Dry streak distribution (consecutive blanks between wins)
    streaks = []
    cur = 0
    for tag, _ in tags:
        if tag == "BLANK":
            cur += 1
        else:
            if cur > 0:
                streaks.append(cur)
            cur = 0
    if cur > 0:
        streaks.append(cur)
    max_streak = max(streaks) if streaks else 0
    avg_streak = sum(streaks) / len(streaks) if streaks else 0.0

    print(f"\n=== mode {mode} ({machine}, {label}) ===")
    print(f"  total paid rounds: {n_total}")
    print(f"  WIN rounds: {len(wins)} ({100*len(wins)/n_total:.1f}%)")
    print(f"  FEATURE_TRIGGER rounds: {len(triggers)} ({100*len(triggers)/n_total:.2f}%)")
    print(f"  BLANK rounds: {len(blanks)} ({100*len(blanks)/n_total:.1f}%)")
    print(f"  bucket distribution:")
    for k, v in bucket_counts.items():
        print(f"    {k:14s}: {v}")
    print(f"  dry streak: max={max_streak}, avg={avg_streak:.1f}")

    # Sequence print (compact)
    seq = []
    for tag, x in tags:
        if tag == "BLANK":
            seq.append(".")
        elif tag == "FEATURE_TRIGGER":
            seq.append(f"[F{x:.0f}]" if x > 0 else "[F]")
        else:
            seq.append(f"W{x:.1f}")
    print(f"  sequence (30 rounds, paid only):")
    print(f"    {' '.join(seq[:30])}")
    if len(seq) > 30:
        print(f"    ...continuing...")
        print(f"    {' '.join(seq[30:50])}")


def main() -> None:
    print("\n###### Small samples (50 spins — chunk-sequence visualization) ######")
    for mode in MODES:
        summarize_mode(mode, MACHINES, label="50 spins")
    print("\n\n###### Big samples (1000 spins — bucket distribution) ######")
    for mode in MODES:
        summarize_mode(mode, BIG_MACHINES, label="1000 spins")


if __name__ == "__main__":
    main()
