"""**WORK IN PROGRESS — PAUSED 2026-04-18**.

Two known bugs before resume (see memory
``project_paytable_inference_paused.md`` for details):

  1. **Multi-fire double-count**: when a pay_id fires on multiple
     paylines in the same round, ``PayoutIdToWinAmount[pay_id]`` is
     the round-total (sum across all those fires). Current code adds
     that full total PER FIRE, inflating the mult. Fix: divide by
     ``fires_of_this_pay_id_in_round`` before attribution.

  2. **Line_bet detection missing**: paytables are conventionally
     "payout × line_bet". M14 has BetAmount=1000 but line_bet=110
     (not 1000/9=111.11; remaining 10 is feature/ante bet). Detect
     via GCD of pure-fire (no wild anywhere on grid) win values —
     e.g. M14 GCD(880, 660, 550, 440, 330, 220) = 110 → paytable
     rows are 8/6/5/4/3/2 × line_bet.

Manually-verified M14 paytable (pure rounds, zero wild on grid):
  pay_id=2: 3× high7  = 880 credits = 8× line_bet
  pay_id=3: 3× 3bar   = 660 = 6× line_bet
  pay_id=4: 3× 2bar   = 550 = 5× line_bet
  pay_id=5: 3× 1bar   = 440 = 4× line_bet
  pay_id=6: 3× any bar mixed = 330 = 3× line_bet
  pay_id=7: 3× cherry = 220 = 2× line_bet

Per-machine paytable inference from rawdata — no 策划 input needed.

Strategy:
  1. Parse each winning round's ``PayoutByPayline`` records →
     ``(line_id, pay_id, mult, positions)``.
  2. Decode positions via the machine's position-encoding scheme.
     Classic 3×N grids use ``pos = (col+1)*100 + (row-1)`` where col
     is 0-indexed and row is 0-indexed (top=0). Larger grids follow
     the same formula with col in range [0, n_cols).
  3. Look up each position's symbol via ``StopSymbolsByCol``
     (``list[str]`` where each string is dash-joined rows per column).
  4. Apply wild substitution: if any cell in the winning tuple is
     "wild", it can substitute for the dominant non-wild symbol.
  5. Per (pay_id, match_count) aggregate:
       - fires: how many rounds fired this pay_id at this count
       - avg_mult_x_bet: mean(win / bet) across fires (tight
         distribution = one deterministic paytable entry; wide
         distribution = data issue or multi-tier payout)
       - dominant_symbol: most common non-wild symbol tuple
       - wild_rate: fraction of fires involving ≥1 wild substitution
       - symbol_purity: 1.0 if all fires have same dominant symbol;
         <1.0 if pay_id is a "mixed category" (e.g. "any 3 bars")
  6. Emit paytable as JSON per machine to
     ``configs/paytables/<machine>_mode<N>.json``.

Self-verify:
  * Every pay_id observed in data gets a paytable entry (no missing).
  * Purity threshold: if dominant symbol is <70% of fires, flag as
    "mixed-category" (e.g. bar-group paylines where 1bar/2bar/3bar
    all count as "bar").
  * For classic machines, verify avg_mult × bet ≈ observed win
    (within 5%).

Usage:
    python scripts/infer_paytable.py --machine M14 --mode 1
    python scripts/infer_paytable.py --all --mode 1
    python scripts/infer_paytable.py --machine M273 --mode 1 --detail
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
OUT_DIR = ROOT / "configs" / "paytables"

_PAYLINE_RE = re.compile(r"(-?\d+):(-?\d+)-(-?\d+)\(([^)]*)\)")
_WILD_RE = re.compile(r"wild", re.IGNORECASE)
_WILD_TIER_RE = re.compile(r"(\d+)x[_-]?wild", re.IGNORECASE)


def _is_wild(sym) -> bool:
    return isinstance(sym, str) and bool(_WILD_RE.search(sym))


def _wild_tier(sym) -> int:
    """'5x_wild' → 5, 'wild' → 1, non-wild → 0."""
    if not _is_wild(sym):
        return 0
    m = _WILD_TIER_RE.search(sym)
    return int(m.group(1)) if m else 1


def _iter_chunks(machine: str, mode: int):
    d = DEV_RAWDATA / machine / f"mode_{mode}"
    if not d.is_dir():
        return
    for f in sorted(d.glob("chunk_*.json")):
        yield f


def _decode_position(pos: int) -> tuple[int, int]:
    """Decode ``pos = (col+1)*100 + (row-1)`` to ``(col, row)``, both
    0-indexed. Derivation:
        pos + 1 = (col+1)*100 + row
        → col = (pos+1)//100 - 1
        → row = (pos+1) % 100
    """
    col = (pos + 1) // 100 - 1
    row = (pos + 1) % 100
    return (col, row)


def _parse_grid(ssc) -> dict[tuple[int, int], str]:
    """StopSymbolsByCol → {(col, row): symbol}."""
    grid = {}
    if not isinstance(ssc, list):
        return grid
    for col_idx, col in enumerate(ssc):
        if not isinstance(col, str):
            continue
        rows = [x for x in col.split("-") if x]
        for row_idx, sym in enumerate(rows):
            grid[(col_idx, row_idx)] = sym
    return grid


def _parse_rounds(robot: dict):
    rr = robot.get("roundResult")
    if isinstance(rr, str):
        try:
            return json.loads(rr)
        except json.JSONDecodeError:
            return []
    return rr if isinstance(rr, list) else []


def _extract_payid_share(piw: dict, pay_id: int) -> float:
    """PayoutIdToWinAmount is keyed by stringified pay_id."""
    if not isinstance(piw, dict):
        return 0.0
    for k in (str(pay_id), pay_id):
        if k in piw:
            try:
                return float(piw[k] or 0)
            except (ValueError, TypeError):
                return 0.0
    return 0.0


def _infer_symbol_signature(
    symbols: list[str],
) -> tuple[str, int, int, str]:
    """Given a list of symbols at winning positions, determine the
    canonical 'winning symbol' after wild substitution.

    Returns ``(dominant_symbol, wild_count, wild_tier_product,
    signature_type)``. ``wild_tier_product`` is the multiplication
    of all wild tiers (5x_wild × 7x_wild = 35x, pure 'wild' = 1x).
    If the machine uses multi-tier wilds, this captures the payout
    multiplier contribution.

    ``signature_type``:
      * "pure" — all non-wild symbols identical, no wild
      * "wild-boosted" — same non-wild symbol + wild(s) substituting
      * "mixed" — multiple distinct non-wild symbols (bar-group etc.)
      * "all-wild" — no non-wild anchor
    """
    wild_tiers = [_wild_tier(s) for s in symbols if _is_wild(s)]
    non_wilds = [s for s in symbols if not _is_wild(s)]
    wild_count = len(wild_tiers)
    # Product of tiers (1x wild treated as 1; multiplicative).
    tier_product = 1
    for t in wild_tiers:
        tier_product *= max(t, 1)
    if not non_wilds:
        return ("<all-wild>", wild_count, tier_product, "all-wild")
    uniq = set(non_wilds)
    if len(uniq) == 1:
        sig_type = "wild-boosted" if wild_count > 0 else "pure"
        return (non_wilds[0], wild_count, tier_product, sig_type)
    # Multiple distinct non-wilds — mixed category.
    key = "+".join(sorted(non_wilds))
    return (key, wild_count, tier_product, "mixed")


def _load_analysis(robot: dict) -> dict:
    ar = robot.get("analysisResult")
    if isinstance(ar, str):
        try:
            return json.loads(ar)
        except json.JSONDecodeError:
            return {}
    return ar if isinstance(ar, dict) else {}


def _parse_feature_win(ar: dict) -> dict[str, dict[str, dict]]:
    """Returns {feature: {pay_id_str: {'win': float, 'times': int}}}."""
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
                nested = {}
                for pid, entry in payouts.items():
                    if isinstance(entry, dict):
                        nested[pid] = {
                            "win": float(entry.get("WinCredits", 0) or 0),
                            "times": int(entry.get("Times", 0) or 0),
                        }
                out[feat] = nested
    return out


def _infer_one_machine(machine: str, mode: int, first_chunk_only: bool):
    chunks = list(_iter_chunks(machine, mode))
    if not chunks:
        return None
    if first_chunk_only:
        chunks = chunks[:1]
    grid_shape = {"n_cols": None, "n_rows": None}
    # Per-pay_id win totals aggregated from FeatureWin across all features.
    # Fallback win source when PayoutIdToWinAmount is empty (ways-pay
    # machines and similar where wins flow through FeatureWin, not per-round).
    feature_win_by_pay_id = defaultdict(float)
    feature_times_by_pay_id = defaultdict(int)
    # Key: (pay_id, match_count) — the paytable row
    pay_stats = defaultdict(lambda: {
        "fires": 0,
        "win_total": 0.0,
        "bet_total_on_fires": 0.0,
        "line_ids_seen": set(),
        "symbol_sigs": Counter(),  # (dominant_symbol, sig_type) → count
        "wild_count_hist": Counter(),
        "wild_tier_hist": Counter(),
        # Mults recorded only when the ENTIRE visible grid has no
        # wild symbol — gives us the true "no-multiplier base mult".
        "clean_base_mults": [],
        # For wild-multiplier derivation: (sum of all grid wild tiers, observed mult).
        "grid_tier_mult_pairs": [],
        "positions_samples": Counter(),
    })
    # Also track pay_id-level line_id distribution (for per-line paytable).
    per_line_pay_stats = defaultdict(lambda: defaultdict(lambda: {
        "fires": 0, "win_total": 0.0, "bet_total": 0.0,
    }))

    for cp in chunks:
        env = json.loads(cp.read_text(encoding="utf-8"))
        for robot in env.get("response") or []:
            # Pull FeatureWin per-pay_id for win fallback.
            ar = _load_analysis(robot)
            fw = _parse_feature_win(ar)
            for feat, payouts in fw.items():
                for pid_str, entry in payouts.items():
                    try:
                        pid = int(pid_str)
                        feature_win_by_pay_id[pid] += entry["win"]
                        feature_times_by_pay_id[pid] += entry["times"]
                    except (ValueError, TypeError):
                        pass
            for r in _parse_rounds(robot):
                pbp = r.get("PayoutByPayline")
                if not isinstance(pbp, str) or not pbp:
                    continue
                ssc = r.get("StopSymbolsByCol")
                grid = _parse_grid(ssc)
                if grid_shape["n_cols"] is None and grid:
                    cols = max(c for c, _ in grid) + 1
                    rows = max(rw for _, rw in grid) + 1
                    grid_shape["n_cols"] = cols
                    grid_shape["n_rows"] = rows
                bet = float(r.get("BetAmount") or 0)
                piw = r.get("PayoutIdToWinAmount") or {}
                for rec in pbp.split(";"):
                    m = _PAYLINE_RE.match(rec.strip())
                    if not m:
                        continue
                    line_id = int(m[1])
                    pay_id = int(m[2])
                    positions_raw = m[4]
                    positions = [int(x) for x in positions_raw.split(",") if x.strip()]
                    match_count = len(positions)
                    # Get symbols at each position.
                    symbols = []
                    for p in positions:
                        col, row = _decode_position(p)
                        sym = grid.get((col, row), "?")
                        symbols.append(sym)
                    dominant, wild_count, wild_tier_product, sig_type = _infer_symbol_signature(symbols)
                    # Grid-wide wild audit: winning symbols alone
                    # don't predict mult because a wild anywhere on
                    # the grid (even off-payline) multiplies wins.
                    # "Clean base mult" = mult when THE ENTIRE GRID
                    # has no wild symbol at all.
                    grid_wild_tiers = [
                        _wild_tier(s) for s in grid.values() if _is_wild(s)
                    ]
                    grid_has_wild = bool(grid_wild_tiers)
                    grid_wild_sum = sum(grid_wild_tiers)
                    key = (pay_id, match_count)
                    pay_stats[key]["fires"] += 1
                    pay_stats[key]["line_ids_seen"].add(line_id)
                    win_share = _extract_payid_share(piw, pay_id)
                    pay_stats[key]["win_total"] += win_share
                    pay_stats[key]["bet_total_on_fires"] += bet
                    pay_stats[key]["symbol_sigs"][(dominant, sig_type)] += 1
                    pay_stats[key]["wild_count_hist"][wild_count] += 1
                    pay_stats[key]["wild_tier_hist"][wild_tier_product] += 1
                    # Clean base mult: only when grid has NO wilds
                    # anywhere. These fires give us the "pure paytable
                    # row" value.
                    if bet > 0:
                        if not grid_has_wild:
                            pay_stats[key]["clean_base_mults"].append(win_share / bet)
                        # Also track mult vs total grid wild sum for
                        # empirical wild multiplier derivation.
                        pay_stats[key]["grid_tier_mult_pairs"].append(
                            (grid_wild_sum, win_share / bet)
                        )
                    if sum(pay_stats[key]["positions_samples"].values()) < 3:
                        pay_stats[key]["positions_samples"][tuple(positions)] += 1
                    # Per-line breakdown.
                    per_line_pay_stats[line_id][pay_id]["fires"] += 1
                    per_line_pay_stats[line_id][pay_id]["win_total"] += win_share
                    per_line_pay_stats[line_id][pay_id]["bet_total"] += bet

    return {
        "machine": machine,
        "mode": mode,
        "chunks_scanned": len(chunks),
        "grid": grid_shape,
        "pay_stats": pay_stats,
        "per_line_pay_stats": per_line_pay_stats,
        "feature_win_by_pay_id": dict(feature_win_by_pay_id),
        "feature_times_by_pay_id": dict(feature_times_by_pay_id),
    }


def _finalize_paytable(info: dict) -> dict:
    """Collapse pay_stats into final paytable JSON."""
    rows = []
    feature_win_map = info.get("feature_win_by_pay_id") or {}
    feature_times_map = info.get("feature_times_by_pay_id") or {}
    # Aggregate fires-per-pay_id across all match_counts (used to
    # allocate FeatureWin total back per-fire).
    total_fires_by_pay_id = defaultdict(int)
    total_bet_by_pay_id = defaultdict(float)
    for (pid, _mc), st_data in info["pay_stats"].items():
        total_fires_by_pay_id[pid] += st_data["fires"]
        total_bet_by_pay_id[pid] += st_data["bet_total_on_fires"]
    for (pay_id, match_count), st in info["pay_stats"].items():
        pay_id_win_pid = st["win_total"]
        win_source = "PayoutIdToWinAmount"
        # Fallback: if per-round pay_id has zero wins but FeatureWin
        # has win for this pay_id, attribute the FeatureWin total
        # proportionally (this match_count's fires / total fires).
        if pay_id_win_pid == 0 and feature_win_map.get(pay_id, 0) > 0:
            total_fires_this_pid = total_fires_by_pay_id.get(pay_id, 0)
            if total_fires_this_pid > 0:
                pay_id_win_pid = (
                    feature_win_map[pay_id]
                    * (st["fires"] / total_fires_this_pid)
                )
                win_source = "FeatureWin (proportional fallback)"
        if st["bet_total_on_fires"] <= 0:
            avg_mult = None
        else:
            avg_mult = pay_id_win_pid / st["bet_total_on_fires"]
        # Determine dominant symbol — merge pure and wild-boosted
        # variants of the same non-wild symbol (they're the same
        # paytable entry, just one has wild substitution).
        by_symbol = Counter()
        for (sym, sig_type_), cnt in st["symbol_sigs"].items():
            by_symbol[sym] += cnt
        top_sym, top_count = by_symbol.most_common(1)[0] if by_symbol else (None, 0)
        dominant_symbol = top_sym
        # Determine primary sig_type for dominant symbol: prefer "pure"
        # over "wild-boosted" label in output.
        sig_type = "pure"
        for (sym, st_), _cnt in st["symbol_sigs"].most_common():
            if sym == top_sym:
                sig_type = st_
                break
        purity = top_count / st["fires"] if st["fires"] else 0.0
        # Wild involvement rate.
        total_wilds = sum(wc * cnt for wc, cnt in st["wild_count_hist"].items())
        avg_wilds_per_fire = (total_wilds / st["fires"]) if st["fires"] else 0.0
        wild_rate = sum(cnt for wc, cnt in st["wild_count_hist"].items() if wc > 0) / st["fires"] if st["fires"] else 0.0
        # Alt signatures.
        alt_sigs = [
            {"symbol": s[0], "sig_type": s[1], "count": c}
            for (s, c) in st["symbol_sigs"].most_common(5)
        ]
        # Base mult: mean of mults when NO wild is anywhere on the
        # grid. This is the real paytable row — wilds grid-wide
        # multiply the win on top of this base.
        clean_mults = st["clean_base_mults"]
        clean_base_mult = (sum(clean_mults) / len(clean_mults)) if clean_mults else None
        clean_fires = len(clean_mults)
        # Grid wild behavior: bucket by grid_wild_sum_of_tiers.
        # If wilds simply multiply linearly by SUM, mult at sum S
        # should = base × S (with S=0 the no-wild case).
        by_grid_sum = defaultdict(list)
        for s, mult in st["grid_tier_mult_pairs"]:
            by_grid_sum[s].append(mult)
        wild_behavior = {}
        for s, mults in sorted(by_grid_sum.items()):
            avg = sum(mults) / len(mults) if mults else 0
            entry = {"fires": len(mults), "avg_mult": round(avg, 5)}
            if clean_base_mult and s > 0:
                # Test: mult = base × (1 + s) linear additive rule?
                expected_add = clean_base_mult * (1 + s)
                entry["expected_if_additive_rule"] = round(expected_add, 5)
                entry["add_rule_fit"] = round(avg / expected_add, 3) if expected_add else None
            wild_behavior[str(s)] = entry
        rows.append({
            "pay_id": pay_id,
            "match_count": match_count,
            "fires": st["fires"],
            "avg_mult_x_bet": round(avg_mult, 5) if avg_mult is not None else None,
            "win_total": round(pay_id_win_pid, 2),
            "win_source": win_source,
            "dominant_symbol": dominant_symbol,
            "signature_type": sig_type,
            "symbol_purity": round(purity, 4),
            # BASE mult: what this pay_id pays when grid has no wilds.
            # This is the "clean paytable row" — wilds grid-wide
            # multiply this base.
            "base_mult_no_wild_anywhere": round(clean_base_mult, 5) if clean_base_mult else None,
            "clean_fires": clean_fires,
            "wild_rate": round(wild_rate, 4),
            "avg_wilds_per_fire": round(avg_wilds_per_fire, 3),
            "line_ids_fired": sorted(st["line_ids_seen"]),
            "alt_signatures_top5": alt_sigs,
            "wild_behavior": wild_behavior,
            "sample_position_tuples": [list(t) for t, _ in st["positions_samples"].most_common(3)],
        })
    rows.sort(key=lambda r: (
        0 if r["pay_id"] >= 0 else 1,  # positive pay_ids first
        -(r["fires"]),
    ))
    # Per-line breakdown.
    per_line_summary = {}
    for line_id, pid_stats in info["per_line_pay_stats"].items():
        line_summary = []
        for pay_id, s in pid_stats.items():
            mult = s["win_total"] / s["bet_total"] if s["bet_total"] > 0 else None
            line_summary.append({
                "pay_id": pay_id,
                "fires": s["fires"],
                "avg_mult_x_bet": round(mult, 5) if mult is not None else None,
            })
        line_summary.sort(key=lambda x: -x["fires"])
        per_line_summary[str(line_id)] = line_summary
    return {
        "machine": info["machine"],
        "mode": info["mode"],
        "chunks_scanned": info["chunks_scanned"],
        "grid": info["grid"],
        "paytable_rows": rows,
        "per_line_breakdown": per_line_summary,
        "self_verify": _self_verify_paytable(rows),
    }


def _self_verify_paytable(rows: list[dict]) -> dict:
    """Self-check: flag low-purity, low-fires, wild-only rows."""
    warnings = []
    for r in rows:
        if r["fires"] < 10:
            warnings.append({
                "pay_id": r["pay_id"], "match_count": r["match_count"],
                "issue": f"low sample (fires={r['fires']}) — mult estimate noisy",
            })
        if r["symbol_purity"] < 0.70 and r["fires"] >= 10:
            warnings.append({
                "pay_id": r["pay_id"], "match_count": r["match_count"],
                "issue": (
                    f"low purity ({r['symbol_purity']:.0%}) — likely "
                    f"mixed-category win (e.g. 'any bar'). Dominant "
                    f"{r['dominant_symbol']!r} is only one of multiple "
                    f"firing patterns; see alt_signatures_top5"
                ),
            })
        if r["dominant_symbol"] == "<all-wild>":
            warnings.append({
                "pay_id": r["pay_id"], "match_count": r["match_count"],
                "issue": "all-wild winning tuple — unusual, check data",
            })
    high_conf_rows = [
        r for r in rows if r["fires"] >= 10 and r["symbol_purity"] >= 0.70
    ]
    return {
        "total_rows": len(rows),
        "high_confidence_rows": len(high_conf_rows),
        "warnings": warnings,
    }


def _expand_range(token: str) -> list[str]:
    m = re.fullmatch(r"[Mm](\d+)-[Mm](\d+)", token)
    if m:
        return [f"M{i}" for i in range(int(m[1]), int(m[2]) + 1)]
    return [token]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--machine", help="single machine e.g. M14")
    p.add_argument("--all", action="store_true", help="process every machine")
    p.add_argument("--mode", type=int, default=1)
    p.add_argument("--machines", nargs="*", default=None)
    p.add_argument("--first-chunk", action="store_true")
    p.add_argument("--output-dir", type=Path, default=OUT_DIR)
    p.add_argument("--detail", action="store_true",
                   help="print paytable rows to stdout (default: just write files)")
    args = p.parse_args()

    if not args.machine and not args.all and not args.machines:
        p.error("must specify --machine, --machines, or --all")

    allowed = None
    if args.machine:
        allowed = {args.machine}
    elif args.machines:
        allowed = set()
        for tok in args.machines:
            allowed.update(_expand_range(tok))

    all_dirs = sorted(
        (d for d in DEV_RAWDATA.iterdir()
         if d.is_dir() and d.name.startswith("M")),
        key=lambda d: int(d.name[1:]) if d.name[1:].isdigit() else 9999,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    empty = 0
    for d in all_dirs:
        if allowed and d.name not in allowed:
            continue
        info = _infer_one_machine(d.name, args.mode, args.first_chunk)
        if info is None:
            continue
        pt = _finalize_paytable(info)
        if not pt["paytable_rows"]:
            empty += 1
            continue
        # Write.
        out = args.output_dir / f"{d.name}_mode{args.mode}.json"
        out.write_text(json.dumps(pt, ensure_ascii=False, indent=2), encoding="utf-8")
        done += 1
        if args.detail:
            print(f"=== {d.name} mode {args.mode} ===")
            print(f"grid: {pt['grid']}")
            print(f"paytable rows (sorted by fires):")
            print(f"  {'pay_id':>6} {'count':>5} {'fires':>6} {'base':>10} "
                  f"{'avg':>8} {'symbol':<22} {'purity':>7} {'clean#':>7}")
            for r in pt["paytable_rows"][:30]:
                base = r.get("base_mult_no_wild_anywhere")
                base_str = f"{base:>10.3f}" if base else "       N/A"
                sym_str = f"{r['dominant_symbol']!s:<22.22}"
                print(f"  {r['pay_id']:>6} {r['match_count']:>5} "
                      f"{r['fires']:>6} {base_str} "
                      f"{r['avg_mult_x_bet']:>8.3f} "
                      f"{sym_str} {r['symbol_purity']:>7.0%} "
                      f"{r['clean_fires']:>7}")
            if pt["self_verify"]["warnings"]:
                print(f"warnings: {len(pt['self_verify']['warnings'])}")
                for w in pt["self_verify"]["warnings"][:5]:
                    print(f"  - pay_id={w['pay_id']} count={w['match_count']}: {w['issue']}")
            print()
    print(f"Wrote {done} paytables to {args.output_dir}/  ({empty} empty skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
