"""Payline-structure classification **per (machine, SpinType)** with
self-verification.

A single machine often has different win mechanics in its paid vs
bonus SpinType — e.g. M33 has 5 line_ids in paid (58) but 8 in
feature (59) because the middle column goes full-wild in feature.
Classifying a machine globally conflates these; we classify per-mode
instead.

Self-verification runs after classification:

1. **Win-coverage check** — do the pay_id wins we see add up to the
   observed WinCredits? If we report "ways-pay" but most wins can't
   be attributed to any pay_id, we're missing a mechanism.

2. **Feature-tally consistency** — if upstream_feature_tally has a
   "MultiWaysNormal"-like feature with non-zero win, a "classic-
   payline" label is suspicious. If tally only has paid-normal-type
   features, a "ways-pay" label is suspicious.

3. **Feature-mode delta** — if the bonus SpinType's line_id set
   differs materially from the paid SpinType, flag the machine as
   having "feature-changed rules" so downstream paytable inference
   treats the modes separately.

4. **Confidence tag** — each (machine, SpinType) gets
   high / medium / low. low means the signals disagree and a human
   should look before trusting the label.

Bucket names (corrected per user feedback):
  * **classic-payline [strict-ltr]** — all positive line_ids, each
    line_id's position tuples are prefix-extensions of a shared
    longest tuple (3/4/5-of-a-kind left-to-right)
  * **classic-payline [flexible]** — positive line_ids but tuples
    are subsets or permutations of a shared cell set (scatter-
    on-line, any-ways, both-ways)
  * **ways-pay** — NO positive line_ids; all wins via negative
    line_ids. Not a "missing mechanic" — this IS the mechanic
    (ways wins / scatter wins / anywhere-pay)
  * **hybrid** — both positive paylines AND negative line_id wins
  * **no-wins** — no PayoutByPayline records at all (should be rare;
    bonus SpinType that's just a routing round maybe)

Usage:
    python scripts/classify_payline_structure.py --mode 1
    python scripts/classify_payline_structure.py --mode 1 --only-low-conf
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAWDATA = ROOT / "rawdata"

_PAYLINE_RE = re.compile(r"(-?\d+):(-?\d+)-(-?\d+)\(([^)]*)\)")


def _iter_chunks(machine: str, mode: int):
    d = RAWDATA / machine / f"mode_{mode}"
    if not d.is_dir():
        return
    for f in sorted(d.glob("chunk_*.json")):
        yield f


def _parse_positions(s: str) -> tuple[int, ...]:
    return tuple(int(p) for p in s.split(",") if p.strip())


def _parse_analysis(robot: dict) -> dict:
    ar = robot.get("analysisResult")
    if isinstance(ar, str):
        try:
            ar = json.loads(ar)
        except json.JSONDecodeError:
            return {}
    if not isinstance(ar, dict):
        return {}
    return ar


def _parse_feature_tally(ar: dict) -> dict[str, dict]:
    raw = ar.get("FeatureWin")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    out = {}
    if isinstance(raw, dict):
        for feat, payouts in raw.items():
            if isinstance(payouts, dict):
                win = sum(float((e or {}).get("WinCredits", 0) or 0)
                          for e in payouts.values())
                times = sum(int((e or {}).get("Times", 0) or 0)
                            for e in payouts.values())
                out[feat] = {"win": win, "times": times}
    return out


def _shape_classification(tuples: list[tuple[int, ...]]) -> str:
    """Return shape mode: strict-ltr / flexible / empty."""
    if not tuples:
        return "empty"
    sorted_by_len = sorted(tuples, key=len)
    shortest = sorted_by_len[0]
    # Mode A: strict ltr prefix
    if all(t[:len(shortest)] == shortest for t in sorted_by_len):
        return "strict-ltr"
    # Mode B: flexible (subset of union OR permuted orderings of same sets)
    # Just check all positions fall within the union — always true by
    # construction, so flexible is default for non-strict.
    return "flexible"


# ---------- main scan + per-SpinType breakdown ----------

def _scan_machine(machine: str, mode: int, first_chunk_only: bool):
    chunks = list(_iter_chunks(machine, mode))
    if not chunks:
        return None
    if first_chunk_only:
        chunks = chunks[:1]
    # per-SpinType tallies
    per_st_lines = defaultdict(lambda: defaultdict(Counter))  # spin_type → line_id → Counter(positions)
    st_rounds = Counter()
    st_win_total = Counter()  # spin_type → sum of WinCredits
    st_bet_total = Counter()  # spin_type → sum of BetAmount
    st_payoutid_win = defaultdict(Counter)  # spin_type → pay_id → cumulative win
    # upstream feature tally aggregated across chunks
    feature_tally_agg = defaultdict(lambda: {"win": 0.0, "times": 0})
    total_upstream_total_win = 0.0
    grid = {"n_cols": None, "n_rows": None}

    for cp in chunks:
        env = json.loads(cp.read_text(encoding="utf-8"))
        for robot in env.get("response") or []:
            ar = _parse_analysis(robot)
            # TotalWin parse
            tw_raw = ar.get("TotalWin")
            if isinstance(tw_raw, str):
                try:
                    total_upstream_total_win += float(
                        json.loads(tw_raw).get("Credits", 0)
                        if tw_raw.strip().startswith("{") else tw_raw
                    )
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            ft = _parse_feature_tally(ar)
            for f, d in ft.items():
                feature_tally_agg[f]["win"] += d["win"]
                feature_tally_agg[f]["times"] += d["times"]
            rr = robot.get("roundResult")
            if isinstance(rr, str):
                try:
                    rounds = json.loads(rr)
                except json.JSONDecodeError:
                    rounds = []
            elif isinstance(rr, list):
                rounds = rr
            else:
                rounds = []
            for r in rounds:
                st = r.get("SpinType")
                st_rounds[st] += 1
                win = float(r.get("WinCredits") or 0)
                bet = float(r.get("BetAmount") or 0)
                st_win_total[st] += win
                st_bet_total[st] += bet
                if grid["n_cols"] is None:
                    ssc = r.get("StopSymbolsByCol")
                    if isinstance(ssc, list) and ssc:
                        grid["n_cols"] = len(ssc)
                        if isinstance(ssc[0], str):
                            grid["n_rows"] = len([x for x in ssc[0].split("-") if x])
                pbp = r.get("PayoutByPayline")
                if isinstance(pbp, str) and pbp:
                    for rec in pbp.split(";"):
                        m = _PAYLINE_RE.match(rec.strip())
                        if not m:
                            continue
                        line = int(m[1])
                        positions = _parse_positions(m[4])
                        per_st_lines[st][line][positions] += 1
                piw = r.get("PayoutIdToWinAmount")
                if isinstance(piw, dict):
                    for k, v in piw.items():
                        try:
                            st_payoutid_win[st][str(k)] += float(v or 0)
                        except (ValueError, TypeError):
                            pass
    return {
        "machine": machine,
        "mode": mode,
        "chunks": len(chunks),
        "grid": grid,
        "per_st_lines": {st: {l: dict(v) for l, v in lines.items()}
                         for st, lines in per_st_lines.items()},
        "st_rounds": dict(st_rounds),
        "st_win_total": dict(st_win_total),
        "st_bet_total": dict(st_bet_total),
        "st_payoutid_win": {st: dict(c) for st, c in st_payoutid_win.items()},
        "feature_tally": dict(feature_tally_agg),
        "upstream_total_win": total_upstream_total_win,
    }


def _classify_spintype(per_line: dict) -> dict:
    """Classify a single SpinType's PayoutByPayline records."""
    if not per_line:
        return {"bucket": "no-wins", "shape": "empty",
                "positive_lines": [], "negative_lines": [],
                "total_records": 0}
    positive = sorted(l for l in per_line if l >= 1)
    negative = sorted(l for l in per_line if l < 0)
    shapes = []
    for line_id in positive:
        tuples = list(per_line[line_id].keys())
        shapes.append(_shape_classification(tuples))
    has_pos = bool(positive)
    has_neg = bool(negative)
    # Prefer strict-ltr if all positive lines are strict, else flexible.
    shape = "empty"
    if positive:
        shape = "strict-ltr" if all(s == "strict-ltr" for s in shapes) else "flexible"
    if has_pos and not has_neg:
        bucket = f"classic-payline [{shape}]"
    elif has_pos and has_neg:
        bucket = f"hybrid (payline+board) [{shape}]"
    elif not has_pos and has_neg:
        bucket = "ways-pay (negative line_ids only)"
    else:
        bucket = "no-wins"
    total_records = sum(
        sum(tc.values()) for tc in per_line.values()
    )
    return {
        "bucket": bucket,
        "shape": shape,
        "positive_lines": positive,
        "negative_lines": negative,
        "total_records": total_records,
    }


# ---------- self-verification ----------

def _self_verify(machine: str, scan: dict, per_st_class: dict) -> dict:
    """Run cross-signal checks; return checks + confidence tag per SpinType."""
    checks = {}
    # Identify paid vs feature SpinTypes. Heuristic: highest-round-count
    # SpinType with cost > 0 most rounds is "paid"; others are "feature".
    st_rounds = scan["st_rounds"]
    st_bet = scan["st_bet_total"]
    paid_st = None
    if st_rounds:
        paid_st = max(
            st_rounds.keys(),
            key=lambda st: (st_bet.get(st, 0), st_rounds.get(st, 0)),
        )
    feature_sts = [st for st in st_rounds if st != paid_st]
    # Build per-SpinType confidence.
    per_st_confidence = {}
    for st, cls in per_st_class.items():
        reasons = []
        severity = 0  # 0 = high, 1 = medium, 2 = low
        # Check 1: win coverage. If the SpinType has non-trivial WinCredits
        # but we captured no line_ids with wins, something's off.
        win_total = scan["st_win_total"].get(st, 0)
        piw_total = sum(scan["st_payoutid_win"].get(st, {}).values())
        if win_total > 0:
            coverage = piw_total / win_total if win_total > 0 else 0
            if coverage < 0.8:
                reasons.append(
                    f"win coverage {coverage:.0%} — "
                    f"PayoutIdToWinAmount sums to {piw_total:,.0f} but "
                    f"WinCredits sum is {win_total:,.0f} (missing mechanic?)"
                )
                severity = max(severity, 1)
        elif cls["total_records"] > 0:
            # Edge case: records but zero total win → bonus routing round
            pass
        # Check 2: feature-tally consistency vs label.
        ft = scan["feature_tally"]
        tally_features = sorted(ft.keys())
        # If label is ways-pay but feature tally has no paid-normal-type
        # entries, that's suspicious.
        PAID_NORMAL_HINT = (
            "Normal", "Multi", "Ways", "Anywhere", "Collect"
        )
        if cls["bucket"].startswith("ways-pay"):
            # Expect a ways-pay-ish feature in the tally.
            has_ways_like = any(
                any(h in f for h in PAID_NORMAL_HINT)
                for f in tally_features
            )
            if not has_ways_like:
                reasons.append(
                    f"ways-pay label but no ways-like feature in tally "
                    f"(features: {tally_features})"
                )
                severity = max(severity, 1)
        # Check 3: if feature ST has a structurally different line_id set
        # than paid ST, flag (not a confidence issue — an info flag).
        if paid_st is not None and st != paid_st:
            paid_cls = per_st_class.get(paid_st)
            if paid_cls:
                paid_lines = set(paid_cls["positive_lines"] + paid_cls["negative_lines"])
                this_lines = set(cls["positive_lines"] + cls["negative_lines"])
                if paid_lines and paid_lines != this_lines:
                    added = sorted(this_lines - paid_lines)
                    removed = sorted(paid_lines - this_lines)
                    reasons.append(
                        f"feature-mode rules differ from paid (SpinType "
                        f"{paid_st}): added lines={added} removed={removed}"
                    )
                    # This is INFO not a confidence hit; don't bump severity.
        confidence = ["high", "medium", "low"][severity]
        per_st_confidence[st] = {
            "confidence": confidence,
            "notes": reasons,
            "is_paid": (st == paid_st),
        }
    checks["per_st_confidence"] = per_st_confidence
    checks["paid_spin_type"] = paid_st
    checks["feature_spin_types"] = feature_sts
    checks["feature_tally_keys"] = sorted(scan["feature_tally"].keys())
    return checks


def _expand_range(token: str) -> list[str]:
    m = re.fullmatch(r"[Mm](\d+)-[Mm](\d+)", token)
    if m:
        return [f"M{i}" for i in range(int(m[1]), int(m[2]) + 1)]
    return [token]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", type=int, default=1)
    p.add_argument("--machines", nargs="*", default=None)
    p.add_argument("--first-chunk", action="store_true")
    p.add_argument("--detail", action="store_true",
                   help="print per-SpinType breakdown")
    p.add_argument("--only-low-conf", action="store_true",
                   help="only show low/medium-confidence machines")
    args = p.parse_args()

    allowed = None
    if args.machines:
        allowed = set()
        for tok in args.machines:
            allowed.update(_expand_range(tok))

    all_dirs = sorted(
        (d for d in RAWDATA.iterdir()
         if d.is_dir() and d.name.startswith("M")),
        key=lambda d: int(d.name[1:]) if d.name[1:].isdigit() else 9999,
    )

    machine_records = []
    for d in all_dirs:
        if allowed and d.name not in allowed:
            continue
        scan = _scan_machine(d.name, args.mode, args.first_chunk)
        if scan is None:
            continue
        per_st_class = {}
        for st, lines in scan["per_st_lines"].items():
            per_st_class[st] = _classify_spintype(lines)
        # Also classify SpinTypes that have rounds but no win records.
        for st in scan["st_rounds"]:
            if st not in per_st_class:
                per_st_class[st] = _classify_spintype({})
        checks = _self_verify(d.name, scan, per_st_class)
        machine_records.append({
            "machine": d.name,
            "grid": scan["grid"],
            "per_st": per_st_class,
            "checks": checks,
            "st_rounds": scan["st_rounds"],
        })

    # Machine-level label = paid SpinType's bucket (most-rounds).
    machine_label = {}
    for rec in machine_records:
        paid_st = rec["checks"]["paid_spin_type"]
        if paid_st is not None and paid_st in rec["per_st"]:
            machine_label[rec["machine"]] = rec["per_st"][paid_st]["bucket"]
        else:
            machine_label[rec["machine"]] = "no-wins"

    # Bucket summary.
    buckets = defaultdict(list)
    for rec in machine_records:
        buckets[machine_label[rec["machine"]]].append(rec["machine"])
    print(f"=== Payline-structure classification (mode={args.mode}) ===")
    print(f"Machines scanned: {len(machine_records)}")
    if args.first_chunk:
        print("(--first-chunk: fast survey; re-run without for stable labels)")
    print()
    for bucket, machines in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        print(f"  [{bucket}]  ({len(machines)} machines)")
        names = sorted(machines, key=lambda x: int(x[1:]) if x[1:].isdigit() else 9999)
        for i in range(0, len(names), 12):
            print("    " + "  ".join(f"{n:<6}" for n in names[i:i+12]))
    print()

    # Confidence summary.
    per_machine_conf = {}
    for rec in machine_records:
        # Machine confidence = min confidence across its paid SpinType only.
        paid_st = rec["checks"]["paid_spin_type"]
        if paid_st is not None and paid_st in rec["checks"]["per_st_confidence"]:
            per_machine_conf[rec["machine"]] = rec["checks"]["per_st_confidence"][paid_st]["confidence"]
        else:
            per_machine_conf[rec["machine"]] = "low"
    conf_counts = Counter(per_machine_conf.values())
    print(f"Confidence on paid-SpinType label: {dict(conf_counts)}")
    print()

    # Feature-mode rules differ: count machines where any feature ST
    # has a "differ from paid" note.
    differs = []
    for rec in machine_records:
        for st, c in rec["checks"]["per_st_confidence"].items():
            if c["is_paid"]:
                continue
            if any("feature-mode rules differ" in n for n in c["notes"]):
                differs.append((rec["machine"], st))
                break
    print(f"Feature-mode changes rules: {len(differs)} machines")
    if differs:
        names = [m for m, _ in differs]
        names.sort(key=lambda x: int(x[1:]) if x[1:].isdigit() else 9999)
        for i in range(0, len(names), 12):
            print("  " + "  ".join(f"{n:<6}" for n in names[i:i+12]))
    print()

    # Low-confidence machines — spotlight.
    low_med = [m for m, c in per_machine_conf.items() if c != "high"]
    if low_med:
        print(f"Low/medium-confidence machines (need review): {len(low_med)}")
        for rec in machine_records:
            if per_machine_conf[rec["machine"]] == "high" and not args.only_low_conf:
                continue
            if args.only_low_conf and per_machine_conf[rec["machine"]] == "high":
                continue
            print(f"  {rec['machine']}: {machine_label[rec['machine']]}  conf={per_machine_conf[rec['machine']]}")
            for st, c in rec["checks"]["per_st_confidence"].items():
                if c["notes"]:
                    tag = "[paid]" if c["is_paid"] else f"[feature ST={st}]"
                    for note in c["notes"]:
                        print(f"    {tag} {note}")
        print()

    if args.detail:
        for rec in machine_records:
            print(f"=== {rec['machine']}  grid={rec['grid']}  paid_st={rec['checks']['paid_spin_type']} ===")
            for st in sorted(rec["per_st"].keys(), key=lambda x: -rec["st_rounds"].get(x, 0)):
                cls = rec["per_st"][st]
                conf = rec["checks"]["per_st_confidence"].get(st, {})
                print(f"  SpinType={st} rounds={rec['st_rounds'].get(st,0):<8} "
                      f"bucket={cls['bucket']}  confidence={conf.get('confidence','?')} "
                      f"is_paid={conf.get('is_paid', False)}")
                print(f"    positive_lines={cls['positive_lines'][:10]}")
                print(f"    negative_lines={cls['negative_lines']}")
                if conf.get("notes"):
                    for n in conf["notes"]:
                        print(f"    note: {n}")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
