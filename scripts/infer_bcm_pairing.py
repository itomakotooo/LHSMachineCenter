"""Infer BuffCollectionMap ↔ bonus-feature pairing per machine.

Context: the analyzer's ``newfreespin_correction`` hardcodes
``upstream_feature_tally["NewFreespin"]`` as THE feature that fires
at BCM cycle completion. Earlier scan showed this is wrong on 18/33
BCM machines — they pair with features like LockSymbolFreespin,
LockReSpin, MultiBuffFreespin, Wheel, etc. depending on the machine.

This script infers the correct pairing per machine using two signals,
cross-checked for confidence:

  (1) **SpinType ↔ FeatureWin correlation**. Each bonus round fires
      under a machine-specific SpinType. Aggregating total_win by
      SpinType and by Feature lets us match bonus SpinTypes to
      features by win-closeness. The "bonus" SpinType (not the paid-
      normal one) paired with its matched Feature = the BCM pair.

  (2) **Highest non-NormalCollectionSpin feature win**. Simpler
      heuristic: the Feature with the highest win that isn't the
      paid-normal feature (NormalCollectionSpin / variants) nor
      BuffCollectionMap itself is the likely pair.

When the two agree → confidence=high. When they disagree → flag for
review. Writes configs/bcm_pairings.json for analyzer override.

Usage:
    python scripts/infer_bcm_pairing.py --mode 1
    python scripts/infer_bcm_pairing.py --mode 1 --write-config
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV_RAWDATA = ROOT / "dev_rawdata"
CONFIG_PATH = ROOT / "configs" / "bcm_pairings.json"

# Features that are NEVER the BCM bonus pair: they're paid-normal
# channels (the analyzer's "regular spin" accumulator). If the machine
# uses a different paid-normal name, add it here — this set is the
# only per-project knob.
PAID_NORMAL_FEATURES = {
    "NormalCollectionSpin",
    "BingoCollectionNormalSpin",
    "ReelCollectionNormal",
    "HalloweenReelCollectionNormal",
}


def _iter_chunks(machine: str, mode: int):
    d = DEV_RAWDATA / machine / f"mode_{mode}"
    if not d.is_dir():
        return
    for f in sorted(d.glob("chunk_*.json")):
        yield f


def _load_rounds(robot: dict):
    rr = robot.get("roundResult")
    if isinstance(rr, str):
        try:
            return json.loads(rr)
        except json.JSONDecodeError:
            return []
    return rr if isinstance(rr, list) else []


def _aggregate_machine(machine: str, mode: int, parse_chunk_response) -> dict | None:
    """Walk all chunks. Use analyzer's parse_chunk_response to get a
    pre-normalized upstream_feature_tally (handles the double-nested
    JSON-string inside analysisResult.FeatureWin + maps
    {WinCredits, Times} → {win, times}). Raw rounds walked here for
    SpinType/CC tracking."""
    chunks = list(_iter_chunks(machine, mode))
    if not chunks:
        return None
    feature_agg = defaultdict(lambda: {"win": 0.0, "times": 0})
    spintype_win = Counter()
    spintype_rounds = Counter()
    spintype_paid = Counter()
    cc_resets_by_spintype = Counter()
    for cp in chunks:
        env = json.loads(cp.read_text(encoding="utf-8"))
        resp = env.get("response") or []
        bet = int(env.get("_bet", 1000) or 1000)
        # Use analyzer's parser for normalized feature tally.
        rec = parse_chunk_response(resp, chunk_index=1, bet=bet)
        if rec.get("ok"):
            tally = rec.get("upstream_feature_tally") or {}
            for feat, payouts in tally.items():
                for pid, entry in (payouts or {}).items():
                    feature_agg[feat]["win"] += float((entry or {}).get("win", 0) or 0)
                    feature_agg[feat]["times"] += int((entry or {}).get("times", 0) or 0)
        # SpinType + CC tracking: raw round walk per robot.
        for robot in resp:
            rounds = _load_rounds(robot)
            prev_cc = None
            for r in rounds:
                st = r.get("SpinType")
                if st is None:
                    continue
                spintype_rounds[st] += 1
                win = float(r.get("WinCredits") or 0)
                spintype_win[st] += win
                cost = int(r.get("CostCredits") or 0)
                if cost > 0:
                    spintype_paid[st] += 1
                cc = r.get("CollectCount")
                if isinstance(cc, int):
                    if (
                        prev_cc is not None and prev_cc > 100
                        and cc <= prev_cc // 2
                    ):
                        cc_resets_by_spintype[st] += 1
                    prev_cc = cc
    return {
        "machine": machine,
        "mode": mode,
        "chunks": len(chunks),
        "feature_win": dict(feature_agg),
        "spintype_win": dict(spintype_win),
        "spintype_rounds": dict(spintype_rounds),
        "spintype_paid": dict(spintype_paid),
        "cc_resets_by_spintype": dict(cc_resets_by_spintype),
    }


def _match_spintypes_to_features(agg: dict) -> list[dict]:
    """For each feature, pick the SpinType whose win is closest (abs
    or relative)."""
    st_win = agg["spintype_win"]
    out = []
    for feat, fdata in agg["feature_win"].items():
        feat_win = fdata["win"]
        best_st = None
        best_delta = None
        for st, sw in st_win.items():
            delta = abs(sw - feat_win)
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_st = st
        out.append({
            "feature": feat,
            "feature_win": feat_win,
            "feature_times": fdata["times"],
            "matched_spintype": best_st,
            "matched_spintype_win": st_win.get(best_st, 0),
            "delta": best_delta,
        })
    return out


def _infer_pair(agg: dict) -> dict:
    """Two heuristics, cross-checked."""
    feat_win = agg["feature_win"]
    if "BuffCollectionMap" not in feat_win:
        return {"applicable": False}

    # Signal B: highest-non-normal-feature heuristic.
    sorted_feats = sorted(
        (
            (f, d["win"]) for f, d in feat_win.items()
            if f not in PAID_NORMAL_FEATURES and f != "BuffCollectionMap"
        ),
        key=lambda kv: -kv[1],
    )
    heuristic_pair = sorted_feats[0][0] if sorted_feats and sorted_feats[0][1] > 0 else None
    heuristic_win = sorted_feats[0][1] if sorted_feats else 0

    # Signal A: SpinType ↔ Feature matching.
    matches = _match_spintypes_to_features(agg)
    # Exclude paid-normal features from the SpinType analysis
    # candidates.
    bonus_matches = [
        m for m in matches
        if m["feature"] not in PAID_NORMAL_FEATURES
        and m["feature"] != "BuffCollectionMap"
        and m["feature_win"] > 0
    ]
    bonus_matches.sort(key=lambda m: -m["feature_win"])
    spintype_pair = bonus_matches[0]["feature"] if bonus_matches else None

    # Confidence: both signals agree → high; only one candidate → high
    # (nothing to disagree with); signals disagree → medium; no
    # candidate → none.
    if heuristic_pair is None and spintype_pair is None:
        confidence = "none"
        pair = None
    elif heuristic_pair == spintype_pair:
        confidence = "high"
        pair = heuristic_pair
    elif heuristic_pair and spintype_pair:
        confidence = "medium"
        pair = heuristic_pair  # heuristic is simpler and usually right
    else:
        confidence = "low"
        pair = heuristic_pair or spintype_pair

    return {
        "applicable": True,
        "pair": pair,
        "confidence": confidence,
        "heuristic_pair": heuristic_pair,
        "heuristic_win": heuristic_win,
        "spintype_pair": spintype_pair,
        "all_features": {
            f: {"win": int(d["win"]), "times": d["times"]}
            for f, d in sorted(feat_win.items(), key=lambda kv: -kv[1]["win"])
        },
        "cc_resets_by_spintype": agg.get("cc_resets_by_spintype") or {},
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", type=int, default=1)
    p.add_argument("--machines", nargs="*", default=None)
    p.add_argument("--write-config", action="store_true",
                   help="write configs/bcm_pairings.json")
    args = p.parse_args()

    # Enumerate machines.
    all_dirs = [d for d in DEV_RAWDATA.iterdir()
                if d.is_dir() and d.name.startswith("M")]
    all_dirs.sort(key=lambda d: int(d.name[1:]) if d.name[1:].isdigit() else 9999)

    if args.machines:
        allowed = set()
        import re
        for tok in args.machines:
            m = re.fullmatch(r"[Mm](\d+)-[Mm](\d+)", tok)
            if m:
                allowed.update(f"M{i}" for i in range(int(m[1]), int(m[2]) + 1))
            else:
                allowed.add(tok)
        all_dirs = [d for d in all_dirs if d.name in allowed]

    print(f"=== BCM pairing inference (mode={args.mode}) ===")
    print(f"Scanning {len(all_dirs)} machines...")
    print()

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from fresh_slotlab.player_impact_analyzer import parse_chunk_response

    results = {}
    for d in all_dirs:
        agg = _aggregate_machine(d.name, args.mode, parse_chunk_response)
        if agg is None:
            continue
        inf = _infer_pair(agg)
        if inf["applicable"]:
            results[d.name] = inf

    if not results:
        print("no BuffCollectionMap machines found.")
        return 0

    print(f"BuffCollectionMap machines inferred: {len(results)}")
    print()

    # Group by pair feature.
    by_pair = defaultdict(list)
    for m, r in results.items():
        by_pair[r["pair"] or "<none>"].append((m, r["confidence"]))

    print("=" * 72)
    print("PAIR SUMMARY")
    print("=" * 72)
    for feat, machines in sorted(by_pair.items(), key=lambda kv: -len(kv[1])):
        machines_str = ", ".join(f"{m}({c[0]})" for m, c in sorted(machines, key=lambda x: int(x[0][1:])))
        print(f"  pair = {feat!s:<35}  ({len(machines)} machines)")
        print(f"    {machines_str}")
    print()

    print("=" * 72)
    print("PER-MACHINE DETAIL")
    print("=" * 72)
    for m in sorted(results.keys(), key=lambda x: int(x[1:])):
        r = results[m]
        print(f"  {m}  pair={r['pair']}  confidence={r['confidence']}")
        if r["heuristic_pair"] != r["spintype_pair"]:
            print(f"    [disagreement] heuristic={r['heuristic_pair']} "
                  f"spintype={r['spintype_pair']}")
        feats = list(r["all_features"].items())[:5]
        print(f"    top features: " + ", ".join(
            f"{f}({d['win']:,}w/{d['times']}x)" for f, d in feats
        ))
        if r["cc_resets_by_spintype"]:
            print(f"    CC-reset by SpinType: {r['cc_resets_by_spintype']}")
    print()

    if args.write_config:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        out = {
            "_generated_by": "scripts/infer_bcm_pairing.py",
            "_mode": args.mode,
            "machines": {
                m: {
                    "bonus_feature": r["pair"],
                    "confidence": r["confidence"],
                    # Keep the disagreement on record so manual
                    # review can weigh both signals.
                    "heuristic_pair": r["heuristic_pair"],
                    "spintype_pair": r["spintype_pair"],
                }
                for m, r in results.items()
            },
        }
        CONFIG_PATH.write_text(
            json.dumps(out, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"wrote {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
