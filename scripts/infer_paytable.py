"""Per-machine paytable shape inference from cached rawdata.

**Shape-first, no hardcoded semantics.** Every machine has potentially
different wild naming / grid layout / feature mechanics; this script
auto-infers wild symbols from behavioral evidence and emits a rich
per-pay_id shape descriptor. It does NOT attempt to label pay_ids as
"line-pay" / "scatter" / etc. — operator reads the structural features
and interprets.

Output per machine (``configs/paytables/<machine>_mode<N>.json``):

  wild_inference:
    status: "inferred" | "partial" | "undetermined"
    wilds: [...]                 — symbols inferred to be wilds
    evidence: per-symbol scoring details
    tier_stems: {"canyon": ["canyon", "canyon2x", "canyon3x"]}

  paytable_rows[i]:
    pay_id, match_count, fires, line_ids_fired, ...
    shape:
      symbol_set: non-wild winning symbols (post-inference)
      symbol_purity: how consistent the dominant symbol is across fires
      wild_substitution_rate: fraction of fires with ≥1 inferred wild
      line_id_sign: "positive" | "negative" | "mixed"
      position_cols_covered / position_rows_covered
      position_pattern_samples
      confidence: high/medium/low
      notes: [...] flags for manual review
    (plus legacy mult fields kept for paused paytable-multiplier work)

**Paused multiplier bugs** (see memory ``project_paytable_inference_paused``):
  1. multi-fire double-count (inflates ``avg_mult_x_bet``)
  2. line_bet detection missing (affects mult normalization)
Both only affect the *mult* dimension. Shape inference is unaffected.

Usage:
    python scripts/infer_paytable.py --machine M14 --mode 1
    python scripts/infer_paytable.py --all --mode 1
    python scripts/infer_paytable.py --machine M21 --mode 1 --detail
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAWDATA = Path(__import__("os").environ.get("SLOT_RAWDATA_ROOT", str(ROOT / "rawdata")))
OUT_DIR = ROOT / "configs" / "paytables"

_PAYLINE_RE = re.compile(r"(-?\d+):(-?\d+)-(-?\d+)\(([^)]*)\)")
# Name-based wild hint — used as a *secondary* signal only. Auto-inference
# from substitution behavior is the primary path.
_WILD_NAME_HINT_RE = re.compile(r"wild", re.IGNORECASE)
_WILD_TIER_RE = re.compile(r"(\d+)x[_-]?wild", re.IGNORECASE)
# "canyon", "canyon2x", "canyon3x" → stem "canyon". Drops a trailing
# ``\d+x?`` tier suffix to group multi-tier wild families.
_TIER_SUFFIX_RE = re.compile(r"(\d+)x?$")


def _name_hint_wild(sym) -> bool:
    return isinstance(sym, str) and bool(_WILD_NAME_HINT_RE.search(sym))


def _wild_tier_from_name(sym) -> int:
    """'5x_wild' → 5, 'canyon3x' → 3, 'wild' → 1, other → 0."""
    if not isinstance(sym, str):
        return 0
    m = _WILD_TIER_RE.search(sym)
    if m:
        return int(m.group(1))
    m = _TIER_SUFFIX_RE.search(sym)
    if m:
        return int(m.group(1))
    return 1 if _name_hint_wild(sym) else 0


_LEADING_TIER_RE = re.compile(r"^(\d+)x[_-]?(.+)$")


def _tier_stem(sym: str) -> str:
    """Group multi-tier wild family members to the same stem.

    Examples::

        'canyon'        → 'canyon'
        'canyon2x'      → 'canyon'
        '5x_wild'       → 'wild'
        'wild10x'       → 'wild'
        'Bar1'          → 'Bar'
        'wildrespin20x' → 'wildrespin'
    """
    if not isinstance(sym, str) or not sym:
        return sym or ""
    # Leading-tier pattern: "Nx_wild", "Nx-wild" → strip prefix.
    m = _LEADING_TIER_RE.match(sym)
    if m:
        return m.group(2)
    # Trailing-tier suffix: digits (optionally followed by 'x') at end.
    m = _TIER_SUFFIX_RE.search(sym)
    if m and m.start() > 0:
        return sym[: m.start()]
    return sym


def _iter_chunks(machine: str, mode: int):
    d = RAWDATA / machine / f"mode_{mode}"
    if not d.is_dir():
        return
    for f in sorted(d.glob("chunk_*.json")):
        yield f


def _decode_position(pos: int) -> tuple[int, int]:
    """Decode ``pos = (col+1)*100 + (row-1)`` → ``(col, row)`` 0-indexed.
        pos + 1 = (col+1)*100 + row
        col = (pos+1)//100 - 1
        row = (pos+1) % 100
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


def _load_analysis(robot: dict) -> dict:
    ar = robot.get("analysisResult")
    if isinstance(ar, str):
        try:
            return json.loads(ar)
        except json.JSONDecodeError:
            return {}
    return ar if isinstance(ar, dict) else {}


def _parse_feature_win(ar: dict) -> dict[str, dict[str, dict]]:
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


def _extract_payid_share(piw: dict, pay_id: int) -> float:
    if not isinstance(piw, dict):
        return 0.0
    for k in (str(pay_id), pay_id):
        if k in piw:
            try:
                return float(piw[k] or 0)
            except (ValueError, TypeError):
                return 0.0
    return 0.0


# -------------------------------------------------------------------- wild inference


def _infer_wilds(
    per_pay_fire_count: Counter,
    per_pay_symbol_fire_count: dict[tuple, Counter],
    fire_bucket: dict,
    symbol_total_appearances_in_wins: Counter,
    grid_symbol_freq: Counter,
) -> dict:
    """Auto-infer wild symbols from per-row presence frequency.

    Unit of analysis is ``(pay_id, match_count)`` — the SAME pay_id
    often encodes multiple rules per match count (e.g. "3× bar" +
    "2× cherry" under the same pay_id; ways-pay machines have many
    match counts per pay_id).

    For each row R and symbol S, compute ``frac_present[R][S]`` —
    fraction of R's fires containing S.

      * **Paying symbol** of row R: frac ≥ 0.80 (wild substitutes
        at most ~2 cells of a 3-5 cell tuple; paying symbol is in
        essentially every fire).
      * **Wild substitute** in row R: 0 < frac < 0.50 (wild rate
        per cell is bounded; wilds only appear occasionally).
      * 0.50 ≤ frac < 0.80 is the ambiguous zone (group-pay
        members, tiny samples) — skipped to avoid false positives.

    Rows with < ``MIN_FIRES_FOR_ROW`` fires are excluded from the
    inference pass entirely (small-sample noise would distort
    fracs). Rows surface normally in the paytable output with a
    ``low_fires`` note.

    For each symbol S::

      always_in_count    = |rows where S is paying symbol|
      sometimes_in_count = |rows where S is wild substitute|
      wild_score = sometimes_in_count / max(always_in_count, 1)

    Confidence bands:
      - HIGH:   sometimes ≥ 3 AND score ≥ 3
      - MEDIUM: sometimes ≥ 2 AND score ≥ 2,
                OR name-regex hit with sometimes ≥ 1
      - LOW:    name-regex hit only, no substitution observed

    Tier-stem grouping: canyon / canyon2x / canyon3x → promoted as
    a family if the stem root is wild.
    """
    MIN_FIRES_FOR_ROW = 20
    ALWAYS_THRESHOLD = 0.80
    SOMETIMES_THRESHOLD = 0.50
    MONO_THRESHOLD = 0.95
    # Wild symbols are typically rare on the grid (<15% of cells).
    # Paying symbols like bars/high7/cherries appear 15-30%. Use this
    # as a filter to reject paying symbols falsely scored high via
    # group-pay substitution noise (e.g. M34 where Bar1/Bar2/Bar3
    # swap around complex multi-rule pays).
    WILD_MAX_GRID_DENSITY = 0.15
    # If more than this many symbols pass the wild filter (outside
    # tier-stem families), the machine likely has complex group-pay
    # rules that confound substitution-based inference. Flag rather
    # than emit a likely-polluted wild set.
    MAX_WILD_CANDIDATES = 5

    symbol_always_rows: dict[str, set[tuple]] = defaultdict(set)
    symbol_sometimes_rows: dict[str, set[tuple]] = defaultdict(set)
    # Mono rows: row where ≥95% of fires are a monochromatic tuple
    # [S,S,...,S] — strong evidence that S has a dedicated "N-of-S"
    # pay (classic wild-only pay shape). A regular paying symbol
    # almost always has some wild-boosted fires mixed in at scale.
    symbol_mono_rows: dict[str, set[tuple]] = defaultdict(set)
    for row_key, total_fires in per_pay_fire_count.items():
        if total_fires < MIN_FIRES_FOR_ROW:
            continue
        sym_counter = per_pay_symbol_fire_count.get(row_key, Counter())
        for sym, fire_count in sym_counter.items():
            frac = fire_count / total_fires
            if frac >= ALWAYS_THRESHOLD:
                symbol_always_rows[sym].add(row_key)
            elif frac < SOMETIMES_THRESHOLD and frac > 0:
                symbol_sometimes_rows[sym].add(row_key)
            # 0.50 ≤ frac < 0.80 — ambiguous, skip.

        # Mono-row detection from the row's tuple distribution.
        buck = fire_bucket.get(row_key)
        if buck is None:
            continue
        tuples = buck["symbol_tuples"]
        # Aggregate mono fires per symbol.
        mono_by_sym: Counter = Counter()
        for tup, cnt in tuples.items():
            if len(set(tup)) == 1 and tup:
                mono_by_sym[tup[0]] += cnt
        for sym, mono_cnt in mono_by_sym.items():
            if mono_cnt / total_fires >= MONO_THRESHOLD:
                symbol_mono_rows[sym].add(row_key)

    # For evidence, we still want to report pay_ids (not rows).
    def _pids_from_rows(rows: set) -> list[int]:
        return sorted({rk[0] for rk in rows})

    symbol_sometimes_pay_ids = {
        s: _pids_from_rows(rows) for s, rows in symbol_sometimes_rows.items()
    }
    symbol_always_pay_ids = {
        s: _pids_from_rows(rows) for s, rows in symbol_always_rows.items()
    }

    all_syms = set(symbol_total_appearances_in_wins.keys()) | set(grid_symbol_freq.keys())
    evidence: dict[str, dict] = {}

    for sym in sorted(all_syms):
        if not isinstance(sym, str) or not sym:
            continue
        always_rows = symbol_always_rows.get(sym, set())
        sometimes_rows = symbol_sometimes_rows.get(sym, set())
        mono_rows = symbol_mono_rows.get(sym, set())
        always_pids = symbol_always_pay_ids.get(sym, [])
        sometimes_pids = symbol_sometimes_pay_ids.get(sym, [])
        mono_pids = sorted({rk[0] for rk in mono_rows})
        always_count = len({p for p in always_pids if p not in mono_pids})
        sometimes_count = len(set(sometimes_pids))
        mono_count = len(set(mono_pids))
        # When a row is mono for S, exclude it from S's "always
        # paying" list — the row is a dedicated wild-only pay, not
        # evidence that S is a regular paying symbol.
        effective_always = max(always_count, 1)
        score = sometimes_count / effective_always
        name_hit = _name_hint_wild(sym)
        total_grid_cells = sum(grid_symbol_freq.values()) or 1
        grid_density = grid_symbol_freq.get(sym, 0) / total_grid_cells
        # Rare-on-grid filter: symbols occupying ≥15% of grid cells
        # are nearly always paying symbols (bars / high7 / cherries /
        # themed symbols), not wilds. This filter defuses the
        # false-positive from complex group-pay machines where
        # paying symbols co-occur in mixed tuples across many
        # pay_ids and would otherwise accrue "sometimes" counts.
        # Name-hit bypass: a symbol literally named "wild" is
        # trusted even if grid-dense (rare but possible).
        too_common_on_grid = grid_density >= WILD_MAX_GRID_DENSITY and not name_hit

        # Decision ladder. A TRUE wild shows BOTH mono-tuple pays
        # (dedicated "N-of-S" wild-only pays) AND substitution
        # behavior (appears as <50% in other pay_ids). Either alone
        # is ambiguous:
        #   - mono-only symbols include scatters, bonus triggers,
        #     jackpots, feature-level values (e.g. M33's "2x").
        #   - substitution-only symbols may not have dedicated wild
        #     pays but still substitute.
        if too_common_on_grid:
            # Grid-dense paying symbol; its "sometimes" count is
            # noise from group-pay co-occurrence, not substitution.
            conf = None
            reason = ""
        elif mono_count >= 2 and sometimes_count >= 1:
            conf = "high"
            reason = (
                f"mono-tuple pay in {mono_count} rows + substitutes "
                f"in {sometimes_count} pay_ids — classic wild pattern"
            )
        elif sometimes_count >= 3 and score >= 3:
            conf = "high"
            reason = (
                f"substitutes in {sometimes_count} pay_ids, paying in "
                f"{always_count}; score={score:.1f}"
            )
        elif mono_count >= 1 and sometimes_count >= 1:
            conf = "medium"
            reason = (
                f"mono-tuple pay in {mono_count} rows + substitutes "
                f"in {sometimes_count} pay_ids"
            )
        elif sometimes_count >= 2 and score >= 2:
            conf = "medium"
            reason = (
                f"substitutes in {sometimes_count} pay_ids, paying in "
                f"{always_count}; score={score:.1f}"
            )
        elif name_hit and (sometimes_count >= 1 or mono_count >= 1):
            conf = "medium"
            reason = (
                f"name matches /wild/ + {'mono' if mono_count else 'substitute'} "
                f"signal"
            )
        elif name_hit:
            conf = "low"
            reason = "name matches /wild/ but no structural signal"
        else:
            conf = None
            reason = ""

        if conf:
            evidence[sym] = {
                "confidence": conf,
                "substitutes_in_pay_ids": sometimes_pids,
                "paying_symbol_in_pay_ids": [
                    p for p in always_pids if p not in mono_pids
                ],
                "mono_tuple_pay_ids": mono_pids,
                "substitutes_count": sometimes_count,
                "paying_count": always_count,
                "mono_count": mono_count,
                "wild_score": round(score, 2),
                "name_hint": name_hit,
                "total_appearances_in_wins": int(symbol_total_appearances_in_wins.get(sym, 0)),
                "grid_appearances": int(grid_symbol_freq.get(sym, 0)),
                "reason": reason,
            }

    # Tier-stem family promotion: if "canyon" is wild with ≥medium
    # confidence and "canyon2x" / "canyon3x" exist, promote the family
    # members even if their own score doesn't hit the threshold — they
    # are the same symbol family differing only in multiplier tier.
    stems: dict[str, list[str]] = defaultdict(list)
    for sym in all_syms:
        if isinstance(sym, str) and sym:
            stems[_tier_stem(sym)].append(sym)
    tier_stems: dict[str, list[str]] = {}
    for stem, members in stems.items():
        if len(members) < 2:
            continue
        members_sorted = sorted(members)
        root_wild = any(
            evidence.get(m, {}).get("confidence") in ("high", "medium")
            for m in members_sorted
        )
        if root_wild:
            tier_stems[stem] = members_sorted
            for m in members_sorted:
                if m not in evidence:
                    mono_pids_m = sorted({rk[0] for rk in symbol_mono_rows.get(m, set())})
                    evidence[m] = {
                        "confidence": "medium",
                        "substitutes_in_pay_ids": symbol_sometimes_pay_ids.get(m, []),
                        "paying_symbol_in_pay_ids": [
                            p for p in symbol_always_pay_ids.get(m, [])
                            if p not in mono_pids_m
                        ],
                        "mono_tuple_pay_ids": mono_pids_m,
                        "substitutes_count": len(set(symbol_sometimes_pay_ids.get(m, []))),
                        "paying_count": len({
                            p for p in symbol_always_pay_ids.get(m, [])
                            if p not in mono_pids_m
                        }),
                        "mono_count": len(mono_pids_m),
                        "wild_score": None,
                        "name_hint": _name_hint_wild(m),
                        "total_appearances_in_wins": int(symbol_total_appearances_in_wins.get(m, 0)),
                        "grid_appearances": int(grid_symbol_freq.get(m, 0)),
                        "reason": f"tier-stem family of inferred wild (stem={stem!r})",
                    }

    wilds = sorted(s for s, ev in evidence.items() if ev["confidence"] in ("high", "medium"))

    # Over-inference flag: if the inferred wild set spans 3+
    # distinct symbol families (tier-stems), it MIGHT be polluted
    # by group-pay co-occurrence (common in Bar-variety machines
    # where different bars co-travel across mixed pays). We don't
    # drop the wilds — BlackDiamond-style real wilds mixed with
    # multi-tier paying symbols should still be visible to the
    # operator — but we mark the machine for manual review so UI
    # can signal "this wild list may be noisy."
    stems_among_wilds = {_tier_stem(s) for s in wilds}
    review_needed = len(stems_among_wilds) > 2

    high_any = any(ev["confidence"] == "high" for ev in evidence.values())
    medium_any = any(ev["confidence"] == "medium" for ev in evidence.values())
    if high_any:
        status = "inferred"
    elif medium_any:
        status = "partial"
    else:
        status = "undetermined"

    return {
        "status": status,
        "wilds": wilds,
        "evidence": evidence,
        "review_needed": review_needed,
        "stem_count": len(stems_among_wilds),
        "tier_stems": tier_stems,
    }


# -------------------------------------------------------------------- signature classification


def _classify_signature(
    symbols: list[str], wild_set: set[str]
) -> tuple[str, int, int, str]:
    """Given a winning tuple and the inferred wild set, return
    ``(dominant_symbol, wild_count, wild_tier_product, sig_type)``.

    sig_type:
      * "pure" — all non-wild symbols identical, no wild
      * "wild-boosted" — same non-wild symbol + wild(s) substituting
      * "mixed" — multiple distinct non-wild symbols
      * "all-wild" — no non-wild anchor
    """
    wild_tiers = [_wild_tier_from_name(s) or 1 for s in symbols if s in wild_set]
    non_wilds = [s for s in symbols if s not in wild_set]
    wild_count = len(wild_tiers)
    tier_product = 1
    for t in wild_tiers:
        tier_product *= max(t, 1)
    if not non_wilds:
        return ("<all-wild>", wild_count, tier_product, "all-wild")
    uniq = set(non_wilds)
    if len(uniq) == 1:
        sig_type = "wild-boosted" if wild_count > 0 else "pure"
        return (non_wilds[0], wild_count, tier_product, sig_type)
    key = "+".join(sorted(non_wilds))
    return (key, wild_count, tier_product, "mixed")


# -------------------------------------------------------------------- raw pass 1


def _collect_raw(machine: str, mode: int, first_chunk_only: bool):
    """Pass 1: walk chunks, collect raw per-fire symbol data + global
    symbol frequency counters. No wild classification yet — the wild
    set is inferred from this output in pass 2.

    Returns ``None`` if the machine has no rawdata.
    """
    chunks = list(_iter_chunks(machine, mode))
    if not chunks:
        return None
    if first_chunk_only:
        chunks = chunks[:1]

    grid_shape = {"n_cols": None, "n_rows": None}
    grid_symbol_freq: Counter = Counter()
    feature_win_by_pay_id: dict[int, float] = defaultdict(float)
    feature_times_by_pay_id: dict[int, int] = defaultdict(int)

    # Per (pay_id, match_count) — all fires stored compactly.
    # We need the raw symbol tuples (to re-classify with inferred
    # wilds) + position samples + line_ids + bet/win aggregates.
    fire_bucket = defaultdict(lambda: {
        "fires": 0,
        "win_total": 0.0,
        "bet_total": 0.0,
        "line_ids": Counter(),
        # Counter of sorted-tuple symbols — bounded by # distinct combos
        # per pay_id (typically < 50, even on 5-reel WAYS machines).
        "symbol_tuples": Counter(),
        # Parallel per-tuple win-total (same key as symbol_tuples) so
        # finalize can compute per-tuple avg_win — essential for
        # splitting an all-wild pay_id into its wild-composition
        # sub-rows (e.g. 3 DoubleDiamond vs 1 DD + 2 TripleDiamond).
        "symbol_tuple_wins": defaultdict(float),
        "position_tuples": Counter(),
        "clean_base_mults": [],
        "grid_tier_mult_pairs": [],
        "cols_covered": set(),
        "rows_covered": set(),
    })

    # Per-line breakdown.
    per_line_pay_stats = defaultdict(lambda: defaultdict(lambda: {
        "fires": 0, "win_total": 0.0, "bet_total": 0.0,
    }))

    # Wild inference tracking: fraction of fires (per pay_id +
    # match_count) that contain each symbol. Granularity is
    # ``(pay_id, match_count)`` because the SAME pay_id often has
    # distinct rules per match count (e.g. "3× bar" + "2× cherry"
    # under same pay_id). A *paying* symbol is in ≥80% of its row's
    # fires (wild substitution covers at most ~2 of 3-5 cells). A
    # *wild* appears in <50% of fires (wild rate bounded). 50-80%
    # is an ambiguous zone (group-pay members, low-sample noise) —
    # skipped.
    per_pay_fire_count: Counter = Counter()  # key = (pay_id, mc)
    per_pay_symbol_fire_count: dict[tuple, Counter] = defaultdict(Counter)
    symbol_total_appearances: Counter = Counter()

    for cp in chunks:
        try:
            env = json.loads(cp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for robot in env.get("response") or []:
            ar = _load_analysis(robot)
            fw = _parse_feature_win(ar)
            for _feat, payouts in fw.items():
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
                # Grid-wide symbol freq.
                for sym in grid.values():
                    if isinstance(sym, str) and sym:
                        grid_symbol_freq[sym] += 1
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
                    symbols = []
                    cells = []
                    for p in positions:
                        col, row = _decode_position(p)
                        cells.append((col, row))
                        sym = grid.get((col, row), "?")
                        symbols.append(sym)
                    # Aggregate per (pay_id, match_count).
                    key = (pay_id, match_count)
                    buck = fire_bucket[key]
                    buck["fires"] += 1
                    buck["line_ids"][line_id] += 1
                    _sym_tup = tuple(sorted(symbols))
                    buck["symbol_tuples"][_sym_tup] += 1
                    if sum(buck["position_tuples"].values()) < 20:
                        buck["position_tuples"][tuple(positions)] += 1
                    for (col, row) in cells:
                        buck["cols_covered"].add(col)
                        buck["rows_covered"].add(row)
                    win_share = _extract_payid_share(piw, pay_id)
                    buck["win_total"] += win_share
                    buck["bet_total"] += bet
                    # Per-tuple win aggregation for wild-composition
                    # breakdown (see fire_bucket init comment).
                    buck["symbol_tuple_wins"][_sym_tup] += win_share
                    # Mult diagnostics (kept for paused paytable-mult work).
                    grid_wild_tiers_regex = [
                        _wild_tier_from_name(s) for s in grid.values()
                        if _name_hint_wild(s)
                    ]
                    grid_has_name_wild = bool(grid_wild_tiers_regex)
                    grid_wild_sum = sum(grid_wild_tiers_regex)
                    if bet > 0:
                        if not grid_has_name_wild:
                            buck["clean_base_mults"].append(win_share / bet)
                        buck["grid_tier_mult_pairs"].append(
                            (grid_wild_sum, win_share / bet)
                        )
                    per_line_pay_stats[line_id][pay_id]["fires"] += 1
                    per_line_pay_stats[line_id][pay_id]["win_total"] += win_share
                    per_line_pay_stats[line_id][pay_id]["bet_total"] += bet

                    # Frequency signal for wild inference: per
                    # (pay_id, match_count), count fires containing
                    # each symbol. See _infer_wilds for thresholds.
                    uniq = set(symbols)
                    sym_counter = Counter(symbols)
                    row_key = (pay_id, match_count)
                    per_pay_fire_count[row_key] += 1
                    for s in uniq:
                        per_pay_symbol_fire_count[row_key][s] += 1
                        symbol_total_appearances[s] += sym_counter[s]

    return {
        "machine": machine,
        "mode": mode,
        "chunks_scanned": len(chunks),
        "grid_shape": grid_shape,
        "grid_symbol_freq": grid_symbol_freq,
        "feature_win_by_pay_id": dict(feature_win_by_pay_id),
        "feature_times_by_pay_id": dict(feature_times_by_pay_id),
        "fire_bucket": fire_bucket,
        "per_line_pay_stats": per_line_pay_stats,
        "per_pay_fire_count": per_pay_fire_count,
        "per_pay_symbol_fire_count": per_pay_symbol_fire_count,
        "symbol_total_appearances": symbol_total_appearances,
    }


# -------------------------------------------------------------------- pass 3: aggregate with inferred wilds


def _build_shape_for_row(
    pay_id: int,
    match_count: int,
    buck: dict,
    grid_shape: dict,
    wild_set: set[str],
    wild_inference_status: str,
) -> dict:
    """Emit rich structural shape for one (pay_id, match_count) row."""
    fires = buck["fires"]
    # Re-classify every fire's symbol tuple using the inferred wild set.
    sig_counter: Counter = Counter()
    symbol_counter: Counter = Counter()
    wild_fire_count = 0
    for tup, count in buck["symbol_tuples"].items():
        dominant, wild_count, _tp, sig_type = _classify_signature(
            list(tup), wild_set
        )
        sig_counter[(dominant, sig_type)] += count
        symbol_counter[dominant] += count
        if wild_count > 0:
            wild_fire_count += count
    # Top dominant symbol.
    top_sym, top_cnt = symbol_counter.most_common(1)[0] if symbol_counter else (None, 0)
    symbol_purity = (top_cnt / fires) if fires else 0.0
    # Symbol set (non-wild winners). For mixed, split by "+"; for
    # pure/wild-boosted/all-wild, just the one.
    symbol_set: list[str] = []
    if top_sym is not None:
        if "+" in top_sym and top_sym != "<all-wild>":
            symbol_set = sorted(set(top_sym.split("+")))
        else:
            symbol_set = [top_sym]
    wild_sub_rate = (wild_fire_count / fires) if fires else 0.0
    # Line id sign.
    lines = sorted(buck["line_ids"].keys())
    pos_lines = [ln for ln in lines if ln > 0]
    neg_lines = [ln for ln in lines if ln < 0]
    zero_lines = [ln for ln in lines if ln == 0]
    if pos_lines and not neg_lines:
        line_sign = "positive"
    elif neg_lines and not pos_lines:
        line_sign = "negative"
    elif pos_lines and neg_lines:
        line_sign = "mixed"
    else:
        line_sign = "zero" if zero_lines else "empty"
    # Position coverage.
    cols = sorted(buck["cols_covered"])
    rows = sorted(buck["rows_covered"])
    n_cols_grid = grid_shape.get("n_cols") or 0
    n_rows_grid = grid_shape.get("n_rows") or 0
    spans_full_grid = (
        n_cols_grid
        and n_rows_grid
        and len(cols) == n_cols_grid
        and len(rows) == n_rows_grid
    )
    # Decoded position patterns (top 3 sample tuples).
    decoded_samples: list[list[list[int]]] = []
    for positions, _cnt in buck["position_tuples"].most_common(3):
        decoded = [list(_decode_position(p)) for p in positions]
        decoded_samples.append(decoded)
    # Notes — flags that warrant manual review.
    notes: list[str] = []
    if fires < 10:
        notes.append(f"low_fires ({fires})")
    if symbol_purity < 0.70 and fires >= 10:
        notes.append(f"low_purity ({symbol_purity:.0%}) — likely mixed / group-pay")
    if top_sym == "<all-wild>":
        notes.append("all_wild_tuple — special wild-count pay or inference miss")
    if wild_inference_status == "undetermined" and wild_sub_rate == 0:
        # No wilds inferred AND no wilds observed — fine, machine may
        # genuinely have no wilds.
        pass
    if wild_inference_status == "undetermined" and wild_fire_count == 0 and "<all-wild>" in symbol_counter:
        notes.append("wild_inference_undetermined_despite_all_wild_tuples")
    # Confidence.
    if fires >= 20 and symbol_purity >= 0.80 and top_sym and top_sym != "<all-wild>":
        confidence = "high"
    elif fires >= 10 and symbol_purity >= 0.60:
        confidence = "medium"
    else:
        confidence = "low"

    # Composition breakdown — applies to EVERY pay row that saw at
    # least two distinct sorted symbol tuples. Each sub-row carries
    # its own fires + avg_win so 策划 can map observed multipliers
    # back to individual paytable entries (e.g. "3× Bar1 + 0 wild"
    # baseline vs. "2× Bar1 + 1× Diamond1" wild-scaled variant).
    #
    # Labels sort non-wild symbols first (by count desc, name asc),
    # then wilds at the tail, so the baseline variant reads first
    # and wild-scaled variants are visually grouped below it.
    #
    # Long-tail pays (e.g. any-bar groups) get capped at top 10 by
    # fires + a single aggregate "其他 (N)" row for the remainder,
    # to keep the UI table readable without hiding information.
    composition_breakdown: list[dict] | None = None
    tup_wins = buck.get("symbol_tuple_wins") or {}
    comp_agg: dict[tuple, dict] = {}
    for tup, fires_count in buck["symbol_tuples"].items():
        comp_key = tuple(sorted(tup))
        entry = comp_agg.setdefault(comp_key, {"fires": 0, "win_total": 0.0})
        entry["fires"] += fires_count
        entry["win_total"] += float(tup_wins.get(tup, 0.0) or 0.0)
    if len(comp_agg) >= 2:
        sorted_entries = sorted(
            comp_agg.items(), key=lambda kv: -kv[1]["fires"],
        )
        MAX_DISPLAY = 10
        head, tail = sorted_entries[:MAX_DISPLAY], sorted_entries[MAX_DISPLAY:]
        breakdown: list[dict] = []
        for comp_key, agg in head:
            cnt = Counter(comp_key)
            non_wilds = [
                (s, n) for s, n in cnt.items() if s not in wild_set
            ]
            wilds = [(s, n) for s, n in cnt.items() if s in wild_set]
            non_wilds.sort(key=lambda kv: (-kv[1], kv[0]))
            wilds.sort(key=lambda kv: (-kv[1], kv[0]))
            parts = [f"{n}\u00d7 {s}" for s, n in non_wilds + wilds]
            label = " + ".join(parts) if parts else "—"
            fires_i = int(agg["fires"])
            win_i = float(agg["win_total"])
            avg_i = (win_i / fires_i) if fires_i > 0 else 0.0
            breakdown.append({
                "composition": dict(cnt),
                "label": label,
                "fires": fires_i,
                "win_total": round(win_i, 2),
                "avg_win": round(avg_i, 2),
                "has_wild": bool(wilds),
            })
        if tail:
            tail_fires = sum(int(a["fires"]) for _, a in tail)
            tail_win = sum(float(a["win_total"]) for _, a in tail)
            tail_avg = (tail_win / tail_fires) if tail_fires > 0 else 0.0
            breakdown.append({
                "composition": None,
                "label": f"\u5176\u4ed6 {len(tail)} \u79cd\u7ec4\u5408",
                "fires": tail_fires,
                "win_total": round(tail_win, 2),
                "avg_win": round(tail_avg, 2),
                "has_wild": False,
                "is_aggregate_tail": True,
            })
        composition_breakdown = breakdown

    return {
        "match_count": match_count,
        "symbol_set": symbol_set,
        "symbol_purity": round(symbol_purity, 4),
        "wild_substitution_rate": round(wild_sub_rate, 4),
        "line_id_sign": line_sign,
        "line_ids_positive": pos_lines,
        "line_ids_negative": neg_lines,
        "position_cols_covered": cols,
        "position_rows_covered": rows,
        "position_spans_full_grid": bool(spans_full_grid),
        "position_pattern_samples": decoded_samples,
        "fires": fires,
        "confidence": confidence,
        "notes": notes,
        "alt_signatures": [
            {"symbol": s, "sig_type": st, "count": c}
            for (s, st), c in sig_counter.most_common(5)
        ],
        # Full composition breakdown (applies to any pay with ≥2
        # distinct symbol tuples; None otherwise). Replaces the
        # earlier ``wild_composition_breakdown`` which was all-wild
        # only. Retained as the ``wild_composition_breakdown`` alias
        # for backward compat with older UI checks.
        "composition_breakdown": composition_breakdown,
        "wild_composition_breakdown": composition_breakdown,
    }


def _finalize(info: dict, wild_inference: dict) -> dict:
    wild_set = set(wild_inference["wilds"])
    grid_shape = info["grid_shape"]
    feature_win_map = info["feature_win_by_pay_id"]

    total_fires_by_pay_id = defaultdict(int)
    for (pid, _mc), buck in info["fire_bucket"].items():
        total_fires_by_pay_id[pid] += buck["fires"]

    rows = []
    for (pay_id, match_count), buck in info["fire_bucket"].items():
        # Mult (legacy — paused bugs affect these; operator knows).
        win_sum = buck["win_total"]
        bet_sum = buck["bet_total"]
        win_source = "PayoutIdToWinAmount"
        if win_sum == 0 and feature_win_map.get(pay_id, 0) > 0:
            total_fires_this_pid = total_fires_by_pay_id.get(pay_id, 0)
            if total_fires_this_pid > 0:
                win_sum = feature_win_map[pay_id] * (
                    buck["fires"] / total_fires_this_pid
                )
                win_source = "FeatureWin (proportional fallback)"
        avg_mult = (win_sum / bet_sum) if bet_sum > 0 else None
        clean_mults = buck["clean_base_mults"]
        clean_base_mult = (sum(clean_mults) / len(clean_mults)) if clean_mults else None
        # Build shape.
        shape = _build_shape_for_row(
            pay_id, match_count, buck, grid_shape, wild_set,
            wild_inference["status"],
        )
        # Legacy top-level fields (used by paused paytable-mult work).
        top_sym = shape["symbol_set"][0] if shape["symbol_set"] else None
        sig_type = "pure"
        if shape["alt_signatures"]:
            sig_type = shape["alt_signatures"][0]["sig_type"]
        # Wild behavior buckets (legacy).
        by_grid_sum = defaultdict(list)
        for s, mult in buck["grid_tier_mult_pairs"]:
            by_grid_sum[s].append(mult)
        wild_behavior = {}
        for s, mults in sorted(by_grid_sum.items()):
            avg = (sum(mults) / len(mults)) if mults else 0
            entry = {"fires": len(mults), "avg_mult": round(avg, 5)}
            if clean_base_mult and s > 0:
                expected_add = clean_base_mult * (1 + s)
                entry["expected_if_additive_rule"] = round(expected_add, 5)
                entry["add_rule_fit"] = (
                    round(avg / expected_add, 3) if expected_add else None
                )
            wild_behavior[str(s)] = entry
        fires_i = int(buck["fires"])
        avg_win_top = (
            round(win_sum / fires_i, 2) if fires_i > 0 else 0.0
        )
        rows.append({
            "pay_id": pay_id,
            "match_count": match_count,
            "fires": fires_i,
            # Per-firing average win in raw credits — exposed at the top
            # level (alongside fires) so the UI can cross-reference
            # analyzer's payout_ids_top20 hit/win numbers against the
            # script's own rawdata scan without walking ``shape``.
            "avg_win": avg_win_top,
            "line_ids_fired": sorted(buck["line_ids"].keys()),
            "shape": shape,
            # Legacy fields (kept for paused mult work + backward compat).
            "dominant_symbol": top_sym,
            "signature_type": sig_type,
            "symbol_purity": shape["symbol_purity"],
            "avg_mult_x_bet": round(avg_mult, 5) if avg_mult is not None else None,
            "win_total": round(win_sum, 2),
            "win_source": win_source,
            "base_mult_no_wild_anywhere": (
                round(clean_base_mult, 5) if clean_base_mult else None
            ),
            "wild_rate": shape["wild_substitution_rate"],
            "wild_behavior": wild_behavior,
        })

    rows.sort(key=lambda r: (
        0 if r["pay_id"] >= 0 else 1,
        -r["fires"],
    ))

    per_line_summary: dict[str, list[dict]] = {}
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
        "grid": info["grid_shape"],
        "wild_inference": wild_inference,
        "paytable_rows": rows,
        "per_line_breakdown": per_line_summary,
        "self_verify": _self_verify(rows, wild_inference),
    }


def _self_verify(rows: list[dict], wild_inference: dict) -> dict:
    """Surface any row/machine-level concerns for operator review."""
    warnings = []
    for r in rows:
        sh = r["shape"]
        for note in sh["notes"]:
            warnings.append({
                "pay_id": r["pay_id"],
                "match_count": r["match_count"],
                "issue": note,
            })
    high_conf = sum(1 for r in rows if r["shape"]["confidence"] == "high")
    low_conf = sum(1 for r in rows if r["shape"]["confidence"] == "low")
    machine_flags: list[str] = []
    if wild_inference.get("review_needed"):
        machine_flags.append(
            f"wild_inference_review_needed "
            f"({len(wild_inference['wilds'])} candidates across "
            f"{wild_inference['stem_count']} symbol families)"
        )
    if wild_inference["status"] == "undetermined":
        has_all_wild = any(
            r["shape"]["symbol_set"] == ["<all-wild>"] for r in rows
        )
        if has_all_wild:
            machine_flags.append(
                "wild_inference_undetermined_but_all_wild_rows_present"
            )
        else:
            machine_flags.append("wild_inference_undetermined")
    if wild_inference["status"] == "partial":
        machine_flags.append("wild_inference_partial")
    return {
        "total_rows": len(rows),
        "high_confidence_rows": high_conf,
        "low_confidence_rows": low_conf,
        "warnings": warnings,
        "machine_flags": machine_flags,
    }


# -------------------------------------------------------------------- orchestration


def _infer_one_machine(machine: str, mode: int, first_chunk_only: bool):
    raw = _collect_raw(machine, mode, first_chunk_only)
    if raw is None:
        return None
    wild_inference = _infer_wilds(
        raw["per_pay_fire_count"],
        raw["per_pay_symbol_fire_count"],
        raw["fire_bucket"],
        raw["symbol_total_appearances"],
        raw["grid_symbol_freq"],
    )
    return _finalize(raw, wild_inference)


def _expand_range(token: str) -> list[str]:
    m = re.fullmatch(r"[Mm](\d+)-[Mm](\d+)", token)
    if m:
        return [f"M{i}" for i in range(int(m[1]), int(m[2]) + 1)]
    return [token]


def _write_quality_csv(output_dir: Path, summaries: list[dict]) -> Path:
    import csv
    out = output_dir / f"_quality_mode{summaries[0]['mode']}.csv" if summaries else output_dir / "_quality.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "machine", "grid", "pay_ids", "rows",
            "wild_status", "wilds", "high_conf", "low_conf",
            "machine_flags",
        ])
        for s in summaries:
            w.writerow([
                s["machine"],
                f"{s['grid']['n_cols']}x{s['grid']['n_rows']}",
                s["pay_ids"],
                s["rows"],
                s["wild_status"],
                ",".join(s["wilds"]),
                s["high_conf"],
                s["low_conf"],
                ";".join(s["machine_flags"]),
            ])
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--machine", help="single machine e.g. M14")
    p.add_argument("--all", action="store_true")
    p.add_argument("--mode", type=int, default=1)
    p.add_argument("--machines", nargs="*", default=None)
    p.add_argument("--first-chunk", action="store_true")
    p.add_argument("--output-dir", type=Path, default=OUT_DIR)
    p.add_argument("--detail", action="store_true")
    p.add_argument("--quality-csv", action="store_true",
                   help="emit _quality_mode<N>.csv summarizing all machines")
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
        (d for d in RAWDATA.iterdir()
         if d.is_dir() and d.name.startswith("M")),
        key=lambda d: int(d.name[1:]) if d.name[1:].isdigit() else 9999,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    empty = 0
    summaries = []
    for d in all_dirs:
        if allowed and d.name not in allowed:
            continue
        pt = _infer_one_machine(d.name, args.mode, args.first_chunk)
        if pt is None:
            continue
        if not pt["paytable_rows"]:
            empty += 1
            continue
        out = args.output_dir / f"{d.name}_mode{args.mode}.json"
        out.write_text(json.dumps(pt, ensure_ascii=False, indent=2), encoding="utf-8")
        done += 1
        wi = pt["wild_inference"]
        sv = pt["self_verify"]
        summaries.append({
            "machine": d.name,
            "mode": args.mode,
            "grid": pt["grid"],
            "pay_ids": len(set(r["pay_id"] for r in pt["paytable_rows"])),
            "rows": len(pt["paytable_rows"]),
            "wild_status": wi["status"],
            "wilds": wi["wilds"],
            "high_conf": sv["high_confidence_rows"],
            "low_conf": sv["low_confidence_rows"],
            "machine_flags": sv["machine_flags"],
        })
        if args.detail:
            print(f"=== {d.name} mode {args.mode} ===")
            print(f"grid: {pt['grid']['n_cols']}x{pt['grid']['n_rows']}")
            print(f"wild_inference: status={wi['status']} wilds={wi['wilds']}")
            if wi["tier_stems"]:
                print(f"  tier_stems: {dict(wi['tier_stems'])}")
            print(f"flags: {sv['machine_flags']}")
            print(f"rows (sorted by fires):")
            print(f"  {'pay_id':>6} {'mc':>3} {'fires':>6} {'sym_set':<26} {'line_sign':<9} {'conf':<6} notes")
            for r in pt["paytable_rows"][:40]:
                sh = r["shape"]
                sym_str = "+".join(sh["symbol_set"])[:26] if sh["symbol_set"] else ""
                notes = ";".join(sh["notes"])[:50]
                print(f"  {r['pay_id']:>6} {r['match_count']:>3} {r['fires']:>6} "
                      f"{sym_str:<26} {sh['line_id_sign']:<9} {sh['confidence']:<6} {notes}")
            print()
    if args.quality_csv and summaries:
        csv_path = _write_quality_csv(args.output_dir, summaries)
        print(f"Wrote quality CSV: {csv_path}")
    print(f"Wrote {done} paytables to {args.output_dir}/  ({empty} empty skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
