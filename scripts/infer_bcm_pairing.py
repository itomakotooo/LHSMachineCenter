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
review. Writes configs/bcm_pairings.json (v2 schema, per-mode) for
analyzer override.

Per-mode matters: some machines genuinely pair with different bonus
features in different modes (e.g. M247 = PreWheel on modes 1/2/5,
LockReSpin on mode 7). A mode-unified config would silently under-
correct RTP on variant modes.

Usage:
    # All modes in one pass (default). Runs 1, 2, 5, 7:
    python scripts/infer_bcm_pairing.py
    python scripts/infer_bcm_pairing.py --write-config

    # Restrict to specific modes. Write merges into existing v2 config
    # (modes not listed are preserved):
    python scripts/infer_bcm_pairing.py --modes 2 5 --write-config

    # Restrict to specific machines:
    python scripts/infer_bcm_pairing.py --machines M273 M247
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path as _PathlibPath

# Ensure fresh_slotlab is importable when invoked as a script
# (no package install). The same trick is used in infer_paytable.py.
_ROOT_FOR_IMPORT = _PathlibPath(__file__).resolve().parent.parent
if str(_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_ROOT_FOR_IMPORT))

# 2026-04-27: BCM target inference now uses an observed-at-peak signal
# (cc=cycle_peak paid round -> immediate-next non-paid SpinType) as
# the highest-priority signal. Prior heuristics (max(feature_win),
# closest SpinType-win match) misfired on M260 / M279 / M266 etc where
# a high-frequency mid-cycle feature (MoveSpin nudge, freespin)
# dominates feature_win even though the actual BCM-cycle trigger is
# a low-frequency Wheel ST=2.
from fresh_slotlab.analyzer.play_types.bcm_cycle import (
    detect_cycle_peak,
    infer_bcm_target_spin_type,
)
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAWDATA = ROOT / "rawdata"
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
    d = RAWDATA / machine / f"mode_{mode}"
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
    # Signal C (2026-04-27): observed-at-cycle-peak SpinType counts.
    # Walked per-robot via round_classification helper.
    obs_at_peak_st: Counter = Counter()
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
            # Signal C: per-robot cycle peak observed-target inference.
            # Uses the round-classification helper -- finds paid rounds
            # at cc=cycle_peak and observes the immediate-next non-paid
            # SpinType. cycle_peak threshold of 50 filters out machines
            # whose CC is incidental (not a real BCM cycle).
            _peak_value = detect_cycle_peak(rounds)
            if _peak_value is not None and _peak_value >= 50:
                _st, _cnt = infer_bcm_target_spin_type(rounds, _peak_value)
                if _st is not None and _cnt > 0:
                    obs_at_peak_st[_st] += _cnt
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
        "obs_at_peak_st": dict(obs_at_peak_st),
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
    """Three signals, cross-checked. Priority C > B > A.

      * Signal C (observed-at-peak): paid round at cc=cycle_peak
        followed by SpinType X -> X's feature is the BCM target.
        Pure structural truth -- not affected by feature win
        magnitude. Verified across M260/M279/M266 in 2026-04-27
        investigation; matches operator's mechanical understanding.
      * Signal B (max-feature-win heuristic): highest-win non-paid-
        normal feature. Misfires when a high-frequency mid-cycle
        feature dominates (M279 MoveSpin 170M >> Wheel 11M).
      * Signal A (SpinType<->Feature win-delta match): closest-win
        match. Same misfire pattern as B but worse on machines
        with overlapping ST wins.
    """
    feat_win = agg["feature_win"]
    if "BuffCollectionMap" not in feat_win:
        return {"applicable": False}

    # Signal A: SpinType <-> Feature matching (computed first so we
    # can use its st->feature mapping to label Signal C output).
    matches = _match_spintypes_to_features(agg)
    bonus_matches = [
        m for m in matches
        if m["feature"] not in PAID_NORMAL_FEATURES
        and m["feature"] != "BuffCollectionMap"
        and m["feature_win"] > 0
    ]
    bonus_matches.sort(key=lambda m: -m["feature_win"])
    spintype_pair = bonus_matches[0]["feature"] if bonus_matches else None

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

    # Signal C: observed-at-cycle-peak SpinType -> feature mapping.
    # Use Signal A's match list to translate ST -> feature_name (the
    # mapping is "feature whose total win is closest to this ST's
    # observed win"). Threshold: 3 events to avoid noise on chunks
    # with few cycle completions.
    obs_at_peak_st = agg.get("obs_at_peak_st") or {}
    obs_pair = None
    obs_pair_evidence = 0
    obs_top_st = None
    if obs_at_peak_st:
        obs_top_st, obs_top_count = max(obs_at_peak_st.items(), key=lambda kv: kv[1])
        if obs_top_count >= 3:
            for m in matches:
                if (
                    m["matched_spintype"] == obs_top_st
                    and m["feature"] not in PAID_NORMAL_FEATURES
                    and m["feature"] != "BuffCollectionMap"
                ):
                    obs_pair = m["feature"]
                    obs_pair_evidence = obs_top_count
                    break

    # Resolution: prefer Signal C (observed truth) when it has
    # evidence. Fall back to B/A consensus.
    if obs_pair:
        pair = obs_pair
        # High confidence if all three signals agree; medium if
        # only Signal C fires; low if C disagrees with B/A.
        if obs_pair == heuristic_pair == spintype_pair:
            confidence = "high"
        elif obs_pair == heuristic_pair or obs_pair == spintype_pair:
            confidence = "high"  # 2 of 3 agree; obs_pair is structural
        else:
            confidence = "medium"  # only obs_pair, B/A disagree
    elif heuristic_pair is None and spintype_pair is None:
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
        "obs_pair": obs_pair,
        "obs_pair_evidence": obs_pair_evidence,
        "obs_top_st": obs_top_st,
        "obs_at_peak_st": dict(obs_at_peak_st),
        "heuristic_pair": heuristic_pair,
        "heuristic_win": heuristic_win,
        "spintype_pair": spintype_pair,
        "all_features": {
            f: {"win": int(d["win"]), "times": d["times"]}
            for f, d in sorted(feat_win.items(), key=lambda kv: -kv[1]["win"])
        },
        "cc_resets_by_spintype": agg.get("cc_resets_by_spintype") or {},
    }


def _infer_single_mode(mode: int, machine_dirs: list, parse_chunk_response) -> dict:
    """Run inference for one mode. Returns ``{machine: infer_result}``
    (only applicable machines)."""
    results = {}
    for d in machine_dirs:
        agg = _aggregate_machine(d.name, mode, parse_chunk_response)
        if agg is None:
            continue
        inf = _infer_pair(agg)
        if inf["applicable"]:
            results[d.name] = inf
    return results


def _print_mode_section(mode: int, results: dict) -> None:
    print("=" * 72)
    print(f"MODE {mode}: {len(results)} BCM machines inferred")
    print("=" * 72)
    if not results:
        print("  (no BuffCollectionMap machines found for this mode)")
        print()
        return

    by_pair = defaultdict(list)
    for m, r in results.items():
        by_pair[r["pair"] or "<none>"].append((m, r["confidence"]))
    print("PAIR SUMMARY")
    for feat, machines in sorted(by_pair.items(), key=lambda kv: -len(kv[1])):
        machines_str = ", ".join(f"{m}({c[0]})" for m, c in sorted(machines, key=lambda x: int(x[0][1:])))
        print(f"  pair = {feat!s:<35}  ({len(machines)} machines)")
        print(f"    {machines_str}")
    print()
    print("PER-MACHINE DETAIL")
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


def _print_cross_mode_diff(all_results: dict[int, dict]) -> None:
    """Flag machines where the bonus_feature differs across modes —
    the whole reason per-mode schema exists. Serves as a self-
    verification step (feedback_self_verify_output): if many machines
    show variance, schema complexity is justified; if none, something
    is off in the inference."""
    # Collect all machines seen across all modes.
    all_machines = set()
    for r in all_results.values():
        all_machines.update(r.keys())
    print("=" * 72)
    print("CROSS-MODE PAIR VARIANCE CHECK")
    print("=" * 72)
    variances = []
    missing_coverage = []
    for m in sorted(all_machines, key=lambda x: int(x[1:])):
        pairs_by_mode = {}
        for mode, r in all_results.items():
            if m in r:
                pairs_by_mode[mode] = r[m]["pair"]
        unique = set(pairs_by_mode.values())
        if len(unique) > 1:
            variances.append((m, pairs_by_mode))
        # Flag machines missing in one or more modes (cache gap).
        if len(pairs_by_mode) < len(all_results):
            covered = sorted(pairs_by_mode.keys())
            missing_coverage.append((m, covered))
    if variances:
        print(f"PAIR VARIES across modes for {len(variances)} machine(s):")
        for m, pbm in variances:
            parts = ", ".join(f"m{k}={v}" for k, v in sorted(pbm.items()))
            print(f"  {m}: {parts}")
    else:
        print("No per-mode pair variance — every machine has the same "
              "bonus feature across all modes scanned.")
    if missing_coverage:
        print()
        print(f"INCOMPLETE MODE COVERAGE for {len(missing_coverage)} machine(s) "
              f"(cache-gap or truly mode-specific):")
        for m, covered in missing_coverage:
            print(f"  {m}: present in modes {covered}")
    print()


def _merge_into_existing_v2(
    new_per_mode: dict[int, dict],
) -> dict:
    """Load existing v2 config if present, overlay new modes on top,
    return the merged dict ready to write. Modes NOT in ``new_per_mode``
    are preserved from the existing file."""
    existing_machines: dict[str, dict] = {}
    if CONFIG_PATH.is_file():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for m, entry in (raw.get("machines") or {}).items():
                if not isinstance(entry, dict):
                    continue
                # Strip legacy flat entry → treat as mode-1 under the
                # same key so it merges rather than gets lost.
                if "modes" in entry and isinstance(entry["modes"], dict):
                    existing_machines[m] = {"modes": dict(entry["modes"])}
                elif "bonus_feature" in entry:
                    legacy_mode = str(int(raw.get("_mode", 1) or 1))
                    existing_machines[m] = {"modes": {legacy_mode: {
                        "bonus_feature": entry["bonus_feature"],
                        "confidence": entry.get("confidence"),
                        "heuristic_pair": entry.get("heuristic_pair"),
                        "spintype_pair": entry.get("spintype_pair"),
                    }}}
        except (OSError, json.JSONDecodeError):
            pass
    for mode, results in new_per_mode.items():
        for m, r in results.items():
            slot = existing_machines.setdefault(m, {"modes": {}})
            slot["modes"][str(mode)] = {
                "bonus_feature": r["pair"],
                "confidence": r["confidence"],
                "heuristic_pair": r["heuristic_pair"],
                "spintype_pair": r["spintype_pair"],
            }
    return {
        "_generated_by": "scripts/infer_bcm_pairing.py",
        "_schema_version": 2,
        "machines": {
            m: existing_machines[m]
            for m in sorted(existing_machines.keys(), key=lambda x: int(x[1:]))
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--modes", type=int, nargs="+", default=[1, 2, 5, 7],
                   help="modes to analyze (default: 1 2 5 7)")
    p.add_argument("--machines", nargs="*", default=None)
    p.add_argument("--write-config", action="store_true",
                   help="write configs/bcm_pairings.json (v2 schema, "
                        "merges into existing file — modes not listed "
                        "are preserved)")
    args = p.parse_args()

    # Enumerate machines.
    all_dirs = [d for d in RAWDATA.iterdir()
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

    print(f"=== BCM pairing inference (modes={args.modes}) ===")
    print(f"Scanning {len(all_dirs)} machines per mode...")
    print()

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from fresh_slotlab.analyzer.core.parser import parse_chunk_response

    all_results: dict[int, dict] = {}
    for mode in args.modes:
        all_results[mode] = _infer_single_mode(mode, all_dirs, parse_chunk_response)

    for mode in args.modes:
        _print_mode_section(mode, all_results[mode])

    # Self-verify: cross-mode variance + coverage gap flagged
    # explicitly so the operator sees where per-mode schema earns its
    # complexity (or where cache is incomplete).
    if len(args.modes) > 1:
        _print_cross_mode_diff(all_results)

    if args.write_config:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        out = _merge_into_existing_v2(all_results)
        CONFIG_PATH.write_text(
            json.dumps(out, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"wrote {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
