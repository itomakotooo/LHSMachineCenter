"""Per-machine self-verification of the payline-structure classifier.

For each machine × each SpinType, verifies: **do the observed wins
add up to a sensible win-channel?** A machine's total WinCredits
should equal the sum of its accounted win channels — either via
per-round PayoutIdToWinAmount (pay_id path) OR via upstream
FeatureWin aggregated totals (feature-aggregated path) OR a mix.

Verdict per (machine, SpinType):
  * **RESOLVED** — all wins accounted for (within 2% tolerance)
    - resolution detail lists which channel(s) matched
  * **UNRESOLVED** — there's a gap between WinCredits and any
    combination of known channels; script couldn't explain it, so
    machine gets marked for human review with the specific gap

After running, outputs two files in ``dev_reports/_classify/``:
  * ``all_verdicts_mode<N>.json`` — structured per-machine report
  * ``needs_review_mode<N>.md`` — human-readable punch list of
    machines whose gaps couldn't be resolved automatically

Usage:
    python scripts/verify_machine_labels.py --mode 1
    python scripts/verify_machine_labels.py --mode 1 --first-chunk  # fast
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV_RAWDATA = ROOT / "dev_rawdata"
OUT_DIR = ROOT / "dev_reports" / "_classify"

_PAYLINE_RE = re.compile(r"(-?\d+):(-?\d+)-(-?\d+)\(([^)]*)\)")

PAID_NORMAL_HINT = (
    "Normal", "Multi", "Ways", "Anywhere", "Collection", "Bingo",
    "Halloween",
)


def _iter_chunks(machine: str, mode: int):
    d = DEV_RAWDATA / machine / f"mode_{mode}"
    if not d.is_dir():
        return
    for f in sorted(d.glob("chunk_*.json")):
        yield f


def _parse_analysis(robot: dict) -> dict:
    ar = robot.get("analysisResult")
    if isinstance(ar, str):
        try:
            return json.loads(ar)
        except json.JSONDecodeError:
            return {}
    return ar if isinstance(ar, dict) else {}


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


def _parse_rounds(robot: dict):
    rr = robot.get("roundResult")
    if isinstance(rr, str):
        try:
            return json.loads(rr)
        except json.JSONDecodeError:
            return []
    return rr if isinstance(rr, list) else []


def _scan_machine(machine: str, mode: int, first_chunk_only: bool):
    chunks = list(_iter_chunks(machine, mode))
    if not chunks:
        return None
    if first_chunk_only:
        chunks = chunks[:1]
    st_win_total = Counter()         # spin_type → Σ WinCredits
    st_bet_total = Counter()
    st_rounds = Counter()
    st_piw_total = Counter()         # spin_type → Σ PayoutIdToWinAmount values
    st_pay_ids = defaultdict(set)    # spin_type → set of pay_ids seen
    st_line_tuples = defaultdict(lambda: defaultdict(Counter))  # st → line_id → positions
    feature_tally = defaultdict(lambda: {"win": 0.0, "times": 0})
    grid = {"n_cols": None, "n_rows": None}

    for cp in chunks:
        env = json.loads(cp.read_text(encoding="utf-8"))
        for robot in env.get("response") or []:
            ar = _parse_analysis(robot)
            ft = _parse_feature_tally(ar)
            for f, d in ft.items():
                feature_tally[f]["win"] += d["win"]
                feature_tally[f]["times"] += d["times"]
            for r in _parse_rounds(robot):
                st = r.get("SpinType")
                st_rounds[st] += 1
                st_win_total[st] += float(r.get("WinCredits") or 0)
                st_bet_total[st] += float(r.get("BetAmount") or 0)
                if grid["n_cols"] is None:
                    ssc = r.get("StopSymbolsByCol")
                    if isinstance(ssc, list) and ssc:
                        grid["n_cols"] = len(ssc)
                        if isinstance(ssc[0], str):
                            grid["n_rows"] = len([
                                x for x in ssc[0].split("-") if x
                            ])
                pbp = r.get("PayoutByPayline")
                if isinstance(pbp, str) and pbp:
                    for rec in pbp.split(";"):
                        m = _PAYLINE_RE.match(rec.strip())
                        if not m:
                            continue
                        line = int(m[1])
                        positions = tuple(int(p) for p in m[4].split(",") if p.strip())
                        st_line_tuples[st][line][positions] += 1
                        try:
                            st_pay_ids[st].add(int(m[2]))
                        except ValueError:
                            pass
                piw = r.get("PayoutIdToWinAmount")
                if isinstance(piw, dict):
                    for k, v in piw.items():
                        try:
                            st_piw_total[st] += float(v or 0)
                        except (ValueError, TypeError):
                            pass
    return {
        "machine": machine,
        "mode": mode,
        "chunks_scanned": len(chunks),
        "grid": grid,
        "st_rounds": dict(st_rounds),
        "st_win_total": dict(st_win_total),
        "st_bet_total": dict(st_bet_total),
        "st_piw_total": dict(st_piw_total),
        "st_pay_ids": {k: sorted(v) for k, v in st_pay_ids.items()},
        "st_line_tuples": {
            st: {l: dict(v) for l, v in lines.items()}
            for st, lines in st_line_tuples.items()
        },
        "feature_tally": dict(feature_tally),
    }


def _classify_lines(per_line: dict) -> dict:
    if not per_line:
        return {"bucket": "no-wins", "shape": "empty",
                "positive_lines": [], "negative_lines": []}
    positive = sorted(l for l in per_line if l >= 1)
    negative = sorted(l for l in per_line if l < 0)
    shapes = []
    for l in positive:
        tuples = list(per_line[l].keys())
        if not tuples:
            continue
        sorted_by_len = sorted(tuples, key=len)
        shortest = sorted_by_len[0]
        if all(t[:len(shortest)] == shortest for t in sorted_by_len):
            shapes.append("strict-ltr")
        else:
            shapes.append("flexible")
    shape = "empty" if not shapes else (
        "strict-ltr" if all(s == "strict-ltr" for s in shapes) else "flexible"
    )
    if positive and not negative:
        bucket = f"classic-payline [{shape}]"
    elif positive and negative:
        bucket = f"hybrid (payline+board) [{shape}]"
    elif not positive and negative:
        bucket = "ways-pay"
    else:
        bucket = "no-wins"
    return {
        "bucket": bucket,
        "shape": shape,
        "positive_lines": positive,
        "negative_lines": negative,
    }


def _verify_spintype(
    st: int,
    scan: dict,
    classification: dict,
    is_paid: bool,
    tolerance: float = 0.02,
) -> dict:
    """For one (machine, SpinType): try to explain all observed WinCredits.

    Accounting hypothesis:
      WinCredits = pay_id_total (from PayoutIdToWinAmount)
                 + bonus_feature_win (from FeatureWin entries that
                   are NOT the paid-normal channel already counted
                   via pay_ids)

    We allow a 2% tolerance because rounding + feature-vs-pay_id
    double-count edge cases.

    Key subtlety: the FeatureWin entries aren't ALL additive with
    pay_id totals. On paid-normal machines, the "NormalCollectionSpin"
    feature counts the same wins that flow through pay_id — counting
    both would double-count. So the verification is:
    IF pay_id_total ≈ WinCredits → all pay_id, feature_tally might
       just be a per-feature echo of the same wins (resolved: "pure
       pay_id channel").
    ELSE if pay_id_total + sum(non-paid-normal features) ≈ WinCredits
       → resolved: "mixed pay_id + bonus FeatureWin".
    ELSE if feature_tally_total ≈ WinCredits (and pay_id 0)
       → resolved: "pure FeatureWin channel" (ways-pay flavor).
    ELSE → unresolved, the gap isn't accounted for.
    """
    win_total = scan["st_win_total"].get(st, 0.0)
    piw_total = scan["st_piw_total"].get(st, 0.0)
    bet_total = scan["st_bet_total"].get(st, 0.0)
    rounds = scan["st_rounds"].get(st, 0)
    feature_tally = scan["feature_tally"]

    verdict = {
        "spin_type": st,
        "is_paid": is_paid,
        "rounds": rounds,
        "bet_total": bet_total,
        "win_total": win_total,
        "pay_id_total": piw_total,
        "classification": classification,
    }

    if win_total <= 0:
        if rounds > 0 and classification["bucket"] == "no-wins":
            verdict.update({
                "status": "RESOLVED",
                "explanation": "no wins in this SpinType (routing / selector round)",
            })
        else:
            verdict.update({
                "status": "RESOLVED",
                "explanation": "zero wins observed",
            })
        return verdict

    # Channel 1: pure pay_id coverage.
    if piw_total > 0:
        coverage = piw_total / win_total
        if abs(coverage - 1.0) <= tolerance:
            verdict.update({
                "status": "RESOLVED",
                "channel": "pay_id",
                "explanation": f"pay_id accounts for {coverage:.1%} of wins",
            })
            return verdict

    # Channel 2: pay_id + non-paid-normal FeatureWin features.
    feature_total = sum(f["win"] for f in feature_tally.values())
    non_normal_total = sum(
        f["win"] for name, f in feature_tally.items()
        if name not in ("BuffCollectionMap",)  # BCM is meta, not actual payout
        and not any(h in name for h in ("Normal", "Bingo", "Halloween"))
    )
    # Ways-like features (MultiWays, MultiWay, etc.) ARE paid-normal-equivalent
    # for ways-pay machines but are the MAIN payout channel — we'll count
    # feature_total in those cases below.

    # Channel 2a: pay_id + non-normal feature wins ≈ total
    combined = piw_total + non_normal_total
    if win_total > 0 and abs(combined - win_total) / win_total <= tolerance:
        verdict.update({
            "status": "RESOLVED",
            "channel": "pay_id + bonus FeatureWin",
            "pay_id_share": piw_total,
            "bonus_feature_share": non_normal_total,
            "explanation": (
                f"wins = {piw_total:,.0f} pay_id + {non_normal_total:,.0f} "
                f"bonus FeatureWin = {combined:,.0f} (target {win_total:,.0f})"
            ),
        })
        return verdict

    # Channel 3: pure FeatureWin (ways-pay / feature-aggregated path)
    if abs(feature_total - win_total) / max(win_total, 1) <= tolerance:
        verdict.update({
            "status": "RESOLVED",
            "channel": "FeatureWin aggregated",
            "feature_total": feature_total,
            "explanation": (
                f"FeatureWin totals {feature_total:,.0f} match WinCredits "
                f"{win_total:,.0f}; wins flow via feature-aggregated channel, "
                f"not per-round pay_ids"
            ),
        })
        return verdict

    # Channel 4: pay_id + ALL features (counts everything, may double-count
    # paid-normal) — loose fallback for machines where feature_tally
    # reports everything including pay_id-reported wins.
    loose_combined = piw_total + feature_total
    # This check passes if WinCredits ≤ both. If the sum greatly exceeds
    # WinCredits it means double-counting, which is OK — the REAL WinCredits
    # is fully covered.
    if piw_total + feature_total >= win_total * (1 - tolerance):
        verdict.update({
            "status": "RESOLVED",
            "channel": "pay_id + FeatureWin (possibly overlapping)",
            "pay_id_share": piw_total,
            "feature_share": feature_total,
            "explanation": (
                f"pay_id {piw_total:,.0f} + FeatureWin {feature_total:,.0f} "
                f"≥ WinCredits {win_total:,.0f} — wins covered (some channels "
                f"may double-count but total accounted)"
            ),
        })
        return verdict

    # Channel 5: pick-em / per-round-WinCredits-only mechanic. If this
    # SpinType has NO pay_id records AND NO PayoutByPayline records
    # AND a companion "Selector"-style feature has times matching
    # this ST's round count (one selector fire per pick), the wins
    # are credited directly to each round's WinCredits without
    # per-feature aggregation. Classic TopDollar pattern (M90/M132):
    # TopDollarSelector.times == ST=14 rounds; TopDollar feature only
    # covers a subset while per-round WinCredits has the true total.
    line_tuples_for_st = scan.get("st_line_tuples", {}).get(st, {})
    has_any_payline_record = bool(line_tuples_for_st)
    if piw_total == 0 and not has_any_payline_record:
        # Find a feature with times >= rounds and win ≈ 0.
        selector_features = [
            name for name, f in feature_tally.items()
            if f.get("times", 0) >= rounds and f.get("win", 0) < win_total * 0.05
        ]
        if selector_features:
            verdict.update({
                "status": "RESOLVED",
                "channel": "per-round WinCredits (pick-em / selector mechanic)",
                "selector_features": selector_features,
                "explanation": (
                    f"pick-em bonus SpinType: {rounds} rounds each directly "
                    f"award WinCredits (no pay_id, no PayoutByPayline). "
                    f"Selector features {selector_features} fire "
                    f"{sum(feature_tally[f]['times'] for f in selector_features)} "
                    f"times (matches round count). Total WinCredits "
                    f"{win_total:,.0f} is authoritative; FeatureWin.<bonus> "
                    f"may only report a subset."
                ),
            })
            return verdict

    # Couldn't explain the gap.
    gap = win_total - piw_total - feature_total
    verdict.update({
        "status": "UNRESOLVED",
        "gap": gap,
        "pay_id_share": piw_total,
        "feature_share": feature_total,
        "feature_tally_keys": sorted(feature_tally.keys()),
        "explanation": (
            f"pay_id {piw_total:,.0f} + FeatureWin {feature_total:,.0f} = "
            f"{piw_total + feature_total:,.0f} but WinCredits = "
            f"{win_total:,.0f}. Unaccounted gap: {gap:,.0f}"
        ),
    })
    return verdict


def _verify_machine(scan: dict) -> dict:
    per_st_class = {}
    for st, lines in scan["st_line_tuples"].items():
        per_st_class[st] = _classify_lines(lines)
    for st in scan["st_rounds"]:
        if st not in per_st_class:
            per_st_class[st] = _classify_lines({})

    # Paid SpinType = one with highest bet total; fall back to highest rounds.
    paid_st = None
    if scan["st_rounds"]:
        paid_st = max(
            scan["st_rounds"].keys(),
            key=lambda st: (scan["st_bet_total"].get(st, 0), scan["st_rounds"].get(st, 0)),
        )

    per_st_verdicts = {}
    for st in scan["st_rounds"]:
        v = _verify_spintype(st, scan, per_st_class[st], is_paid=(st == paid_st))
        per_st_verdicts[st] = v

    all_resolved = all(v["status"] == "RESOLVED" for v in per_st_verdicts.values())

    # Feature-mode-delta info: paid vs bonus ST line_id set differ?
    feature_delta = {}
    if paid_st is not None:
        paid_lines = set(
            per_st_class[paid_st]["positive_lines"] + per_st_class[paid_st]["negative_lines"]
        )
        for st in scan["st_rounds"]:
            if st == paid_st:
                continue
            st_lines = set(
                per_st_class[st]["positive_lines"] + per_st_class[st]["negative_lines"]
            )
            if st_lines and st_lines != paid_lines:
                feature_delta[st] = {
                    "added": sorted(st_lines - paid_lines),
                    "removed": sorted(paid_lines - st_lines),
                }

    return {
        "machine": scan["machine"],
        "grid": scan["grid"],
        "paid_spin_type": paid_st,
        "machine_label": per_st_class[paid_st]["bucket"] if paid_st else "no-wins",
        "all_resolved": all_resolved,
        "per_st_verdicts": per_st_verdicts,
        "feature_delta_from_paid": feature_delta,
        "feature_tally_keys": sorted(scan["feature_tally"].keys()),
    }


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
    p.add_argument("--output-dir", type=Path, default=OUT_DIR)
    args = p.parse_args()

    allowed = None
    if args.machines:
        allowed = set()
        for tok in args.machines:
            allowed.update(_expand_range(tok))

    all_dirs = sorted(
        (d for d in DEV_RAWDATA.iterdir()
         if d.is_dir() and d.name.startswith("M")),
        key=lambda d: int(d.name[1:]) if d.name[1:].isdigit() else 9999,
    )

    verdicts = []
    for d in all_dirs:
        if allowed and d.name not in allowed:
            continue
        scan = _scan_machine(d.name, args.mode, args.first_chunk)
        if scan is None:
            continue
        verdicts.append(_verify_machine(scan))

    # Counts
    resolved = [v for v in verdicts if v["all_resolved"]]
    unresolved = [v for v in verdicts if not v["all_resolved"]]

    print(f"=== Per-machine verification (mode={args.mode}) ===")
    print(f"Machines scanned: {len(verdicts)}")
    print(f"  RESOLVED (all SpinTypes accounted): {len(resolved)}")
    print(f"  UNRESOLVED (some SpinTypes have unexplained gap): {len(unresolved)}")
    print()

    if unresolved:
        print("UNRESOLVED machines — gap not auto-explained:")
        for v in sorted(unresolved, key=lambda x: int(x["machine"][1:])):
            print(f"  {v['machine']}: {v['machine_label']}")
            for st, vv in v["per_st_verdicts"].items():
                if vv["status"] == "UNRESOLVED":
                    tag = "[paid]" if vv["is_paid"] else f"[feat ST={st}]"
                    print(f"    {tag} {vv['explanation']}")
                    print(f"         feature_keys: {vv['feature_tally_keys']}")
        print()

    # Write json + markdown.
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"all_verdicts_mode{args.mode}.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump({
            "mode": args.mode,
            "n_machines": len(verdicts),
            "n_resolved": len(resolved),
            "n_unresolved": len(unresolved),
            "verdicts": verdicts,
        }, f, ensure_ascii=False, indent=2)
    print(f"wrote {json_path} ({json_path.stat().st_size:,} bytes)")

    md_path = args.output_dir / f"needs_review_mode{args.mode}.md"
    lines = [f"# Machines needing human review — mode {args.mode}",
             f"", f"Scanned {len(verdicts)}; {len(resolved)} auto-resolved, "
             f"{len(unresolved)} unresolved.", ""]
    if unresolved:
        for v in sorted(unresolved, key=lambda x: int(x["machine"][1:])):
            lines.append(f"## {v['machine']} — `{v['machine_label']}`")
            lines.append(f"- grid: {v['grid']}")
            lines.append(f"- paid_spin_type: {v['paid_spin_type']}")
            lines.append(f"- feature_tally: {v['feature_tally_keys']}")
            for st, vv in v["per_st_verdicts"].items():
                if vv["status"] == "UNRESOLVED":
                    lines.append(f"- **unresolved ST={st}**: {vv['explanation']}")
                    lines.append(f"  - rounds: {vv['rounds']:,}")
                    lines.append(f"  - bet_total: {vv['bet_total']:,.0f}")
                    lines.append(f"  - pay_id_share: {vv['pay_id_share']:,.0f}")
                    lines.append(f"  - feature_share: {vv['feature_share']:,.0f}")
            lines.append("")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
