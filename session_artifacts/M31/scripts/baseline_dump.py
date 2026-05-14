"""
M31 Mode 1 — Stage 1b Baseline Dump Script
===========================================
Thin reusable wrapper around the 12-section baseline analysis.
Usage:
    python session_artifacts/M31/scripts/baseline_dump.py

Outputs: printed JSON/tables for all 12 sections of 01b_baseline_report.md
Template for future machines: copy this file, adjust MACHINE / MODE / RAWDATA_DIR /
SUMMARY_JSON paths, run, paste numbers into 01b_baseline_report.md.
"""

import sys
import os
import json
import math
from pathlib import Path
from collections import defaultdict

# ---- project root on sys.path ----------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

# ---- constants -------------------------------------------------------
MACHINE = "M31"
MODE = 1
RAWDATA_DIR = PROJECT_ROOT / "rawdata" / MACHINE / f"mode_{MODE}"
SUMMARY_JSON = (
    PROJECT_ROOT
    / "reports"
    / MACHINE
    / f"mode_{MODE}"
    / "versions"
    / "rv_20260514T034512Z_48e77c07"
    / "player_impact_summary.json"
)


# ======================================================================
# Helper: load summary
# ======================================================================
def load_summary(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ======================================================================
# Helper: load all chunk rawdata (yields per-spin records)
# ======================================================================
def iter_chunk_spins(rawdata_dir: Path, chunk_filter=None):
    """Yield (chunk_idx, spin_record) tuples from all chunks."""
    chunk_files = sorted(rawdata_dir.glob("chunk_*.json"))
    for cf in chunk_files:
        idx = int(cf.stem.split("_")[1])
        if chunk_filter is not None and idx not in chunk_filter:
            continue
        with open(cf, "r", encoding="utf-8") as f:
            chunk = json.load(f)
        for robot_data in chunk.get("response", []):
            rounds = json.loads(robot_data["roundResult"])
            for spin in rounds:
                yield idx, spin


def iter_chunk_meta(rawdata_dir: Path):
    """Yield (chunk_idx, chunk_dict) for metadata-only inspection."""
    chunk_files = sorted(rawdata_dir.glob("chunk_*.json"))
    for cf in chunk_files:
        idx = int(cf.stem.split("_")[1])
        with open(cf, "r", encoding="utf-8") as f:
            chunk = json.load(f)
        yield idx, chunk


# ======================================================================
# Section 1: Per-mode totals
# ======================================================================
def section1_mode_totals(summary: dict) -> dict:
    rtp = summary["rtp"]
    vol = summary["player_impact"]["volatility"]
    hit = summary["player_impact"]["hit_and_payout"]
    samp = summary["sampling"]
    avg_return_x = vol["avg_return_x"]
    std_return_x = vol["std_return_x"]
    cv = std_return_x / avg_return_x if avg_return_x else float("inf")
    return {
        "rtp_pp": rtp["point_pct"],
        "ci95": rtp["ci95_interval_pct"],
        "hit_rate_paid": hit["win_hit_rate"],
        "avg_return_x": avg_return_x,
        "std_return_x": std_return_x,
        "cv": cv,
        "max_observed_x": vol["max_observed_return_x"],
        "paid_spins": samp["paid_spins"],
        "bonus_spins": samp["bonus_spins"],
        "total_spins": samp["total_spins"],
        "rtp_target_pp": 95.0,
        "rtp_gap_pp": rtp["point_pct"] - 95.0,
    }


# ======================================================================
# Section 2: Bucket distribution (11 buckets, paid rounds = denominator)
# ======================================================================
def section2_buckets(summary: dict) -> list:
    vol = summary["player_impact"]["volatility"]
    mp = summary["player_impact"]["multiplier_profile"]
    paid_spins = summary["sampling"]["paid_spins"]
    buckets_raw = mp["buckets"]
    # Append zero-win bucket
    zero_win_rate = summary["player_impact"]["hit_and_payout"]["zero_win_rate"]
    result = []
    for b in buckets_raw:
        result.append(
            {
                "bucket": b["bucket"],
                "spin_count": b["spin_count"],
                "rate_pct": b["spin_rate"] * 100,
                "rtp_contribution_pp": b["rtp_contribution_pp"],
                "avg_return_x": b["avg_return_x_in_bucket"],
            }
        )
    return result


# ======================================================================
# Section 3: Per pay_id breakdown
# ======================================================================
def section3_pay_ids(summary: dict) -> list:
    paid_spins = summary["sampling"]["paid_spins"]
    pids = summary["player_impact"]["payout_ids_top20"]
    result = []
    total_rtp = 0.0
    total_hit_rate = 0.0
    for p in pids:
        pid = p["payout_id"]
        hit_count = p["hit_count"]
        hit_rate = p["hit_rate"]
        rtp_pp = p["rtp_contribution_pp"]
        one_in_n = 1.0 / hit_rate if hit_rate > 0 else float("inf")
        total_rtp += rtp_pp
        total_hit_rate += hit_rate
        result.append(
            {
                "pay_id": pid,
                "hit_count": hit_count,
                "hit_rate": hit_rate,
                "one_in_n": one_in_n,
                "rtp_pp": rtp_pp,
                "avg_win_when_hit": p["avg_win_when_hit"],
                "dominant_spin_type": p["dominant_spin_type"],
            }
        )
    result.sort(key=lambda x: x["rtp_pp"], reverse=True)
    result.append(
        {
            "pay_id": "TOTAL",
            "hit_count": sum(r["hit_count"] for r in result[:-0] if r["pay_id"] != "TOTAL"),
            "hit_rate": total_hit_rate,
            "one_in_n": None,
            "rtp_pp": total_rtp,
            "avg_win_when_hit": None,
            "dominant_spin_type": None,
        }
    )
    return result


# ======================================================================
# Section 4: Family RTP share (preliminary grouping)
# ======================================================================
# NOTE: Full pay_id->symbol mapping awaits Stage 1c.
# Grouping here is purely by pay_id numeric bands + 666 (scatter/trigger).
# Labels are PRELIMINARY — 1c will rename.
def section4_families(summary: dict) -> list:
    """
    Preliminary family grouping by pay_id.
    pay_id 12, 666  -> scatter/trigger family (12 wins, 666 triggers free spins)
    pay_id 1, 2     -> top jackpot family (very low hit, very high avg win)
    pay_id 3, 4, 5  -> high-pay family
    pay_id 7, 8     -> mid-high family (dominant by RTP)
    pay_id 9, 10    -> mid-low family
    pay_id 6, 11    -> low family
    """
    pid_data = {
        p["payout_id"]: p
        for p in summary["player_impact"]["payout_ids_top20"]
    }

    families = {
        "top_jackpot (pid 1,2)": ["1", "2"],
        "high_pay (pid 3,4,5)": ["3", "4", "5"],
        "mid_high (pid 7,8)": ["7", "8"],
        "mid_low (pid 9,10)": ["9", "10"],
        "low_pay (pid 6,11)": ["6", "11"],
        "scatter_trigger (pid 12,666)": ["12", "666"],
    }

    total_rtp = sum(
        p["rtp_contribution_pp"]
        for p in summary["player_impact"]["payout_ids_top20"]
    )

    result = []
    sum_share = 0.0
    for family, pids in families.items():
        fam_rtp = sum(pid_data[p]["rtp_contribution_pp"] for p in pids if p in pid_data)
        share_pct = (fam_rtp / total_rtp * 100) if total_rtp > 0 else 0.0
        sum_share += share_pct
        result.append(
            {
                "family": family,
                "pay_ids": pids,
                "rtp_pp": fam_rtp,
                "share_pct": share_pct,
            }
        )
    result.append(
        {"family": "TOTAL", "pay_ids": [], "rtp_pp": total_rtp, "share_pct": sum_share}
    )
    return result


# ======================================================================
# Section 5: Per-reel marginals
# ======================================================================
def section5_reel_marginals(rawdata_dir: Path, max_spins: int = 100000) -> dict:
    """
    Compute per-reel per-symbol marginal probability on center row (row index 1
    in a 3-row window: rows 0,1,2).
    StopSymbolsByCol is a list of per-reel lists: [[r1row0,r1row1,r1row2], ...].
    Center row = index 1 of each reel list.
    """
    from collections import defaultdict, Counter

    reel_symbol_counts = defaultdict(Counter)
    reel_total = defaultdict(int)
    n = 0

    for chunk_idx, spin in iter_chunk_spins(rawdata_dir):
        cols = spin.get("StopSymbolsByCol")
        if cols is None:
            continue
        for reel_i, reel_rows in enumerate(cols):
            if len(reel_rows) >= 3:
                center_sym = reel_rows[1]
                reel_symbol_counts[reel_i][center_sym] += 1
                reel_total[reel_i] += 1
        n += 1
        if n >= max_spins:
            break

    n_reels = max(reel_symbol_counts.keys()) + 1 if reel_symbol_counts else 0
    all_symbols = set()
    for c in reel_symbol_counts.values():
        all_symbols.update(c.keys())
    all_symbols = sorted(all_symbols, key=lambda x: (not str(x).isdigit(), int(x) if str(x).isdigit() else x))

    marginals = {}
    for reel_i in range(n_reels):
        total = reel_total[reel_i]
        marginals[f"R{reel_i+1}"] = {
            str(sym): reel_symbol_counts[reel_i][sym] / total if total else 0.0
            for sym in all_symbols
        }

    return {
        "n_spins_sampled": n,
        "n_reels": n_reels,
        "symbols": [str(s) for s in all_symbols],
        "marginals": marginals,
    }


# ======================================================================
# Section 6: Reel asymmetry
# ======================================================================
def section6_reel_asymmetry(marginals_data: dict, top_symbols: list) -> dict:
    """
    Per DESIGN_PHILOSOPHY §12:
    - Blank density per reel (blank symbol = "-1" or "0" or "Blank"; need to infer from data)
    - Top-pay family density per reel
    - R1 vs R_last direction check
    """
    marginals = marginals_data["marginals"]
    symbols = marginals_data["symbols"]
    n_reels = marginals_data["n_reels"]

    # Identify blank symbol: symbol with highest marginal that isn't in top_symbols.
    # Per rawdata convention: blank is typically symbol with id == "-1" or similar.
    # We look for symbol that appears most uniformly across reels with high density.
    # Will flag candidates for 1c to confirm.

    # Check which symbols are likely blanks (high density, present on all reels)
    reel_keys = [f"R{i+1}" for i in range(n_reels)]
    sym_avg_density = {}
    for sym in symbols:
        densities = [marginals[r].get(sym, 0.0) for r in reel_keys if r in marginals]
        sym_avg_density[sym] = sum(densities) / len(densities) if densities else 0.0

    # Blank candidates: top 3 densest symbols not in top_symbols
    blank_candidates = sorted(
        [s for s in symbols if s not in top_symbols],
        key=lambda s: sym_avg_density[s],
        reverse=True,
    )[:3]

    # For each reel, compute blank density and top-pay density
    reel_stats = {}
    for r in reel_keys:
        m = marginals.get(r, {})
        blank_density = sum(m.get(s, 0.0) for s in blank_candidates)
        top_density = sum(m.get(s, 0.0) for s in top_symbols if s in m)
        reel_stats[r] = {
            "blank_density_approx": blank_density,
            "top_density": top_density,
            "blank_candidates": blank_candidates,
        }

    # Direction checks
    r1 = reel_stats.get("R1", {})
    r_last = reel_stats.get(f"R{n_reels}", {})

    blank_direction_ok = r1["blank_density_approx"] <= r_last["blank_density_approx"]
    top_direction_ok = r1["top_density"] >= r_last["top_density"]

    return {
        "reel_stats": reel_stats,
        "blank_direction_R1_le_Rlast": blank_direction_ok,
        "top_direction_R1_ge_Rlast": top_direction_ok,
        "top_symbols_used": top_symbols,
        "blank_candidates_used": blank_candidates,
        "note": "Blank symbol IDs are PRELIMINARY — confirm in Stage 1c. Top symbols are inferred from high pay_id avg_win.",
    }


# ======================================================================
# Section 7: Window visibility (PWDF)
# ======================================================================
def section7_pwdf(rawdata_dir: Path, top_symbols: list, max_spins: int = 100000) -> dict:
    """
    For each top symbol, per reel:
    - p_window = P(symbol appears in any row of 3-row window)
    - p_center = P(symbol appears on center row)
    - PWDF = p_window / p_center
    StopSymbolsByCol[reel_i] = [row0, row1, row2]
    """
    from collections import defaultdict, Counter

    # Counts: reel -> symbol -> {window_count, center_count}
    reel_window = defaultdict(Counter)
    reel_center = defaultdict(Counter)
    reel_total_spins = defaultdict(int)
    n = 0

    for chunk_idx, spin in iter_chunk_spins(rawdata_dir):
        cols = spin.get("StopSymbolsByCol")
        if cols is None:
            continue
        for reel_i, reel_rows in enumerate(cols):
            if len(reel_rows) < 3:
                continue
            reel_total_spins[reel_i] += 1
            center = str(reel_rows[1])
            # Window: any of the 3 rows
            window_syms = set(str(r) for r in reel_rows)
            for s in top_symbols:
                if s == center:
                    reel_center[reel_i][s] += 1
                if s in window_syms:
                    reel_window[reel_i][s] += 1
        n += 1
        if n >= max_spins:
            break

    n_reels = max(reel_total_spins.keys()) + 1 if reel_total_spins else 0
    reel_keys = [f"R{i+1}" for i in range(n_reels)]

    result = {}
    for s in top_symbols:
        result[s] = {}
        for reel_i in range(n_reels):
            r = f"R{reel_i+1}"
            total = reel_total_spins[reel_i]
            p_window = reel_window[reel_i][s] / total if total else 0.0
            p_center = reel_center[reel_i][s] / total if total else 0.0
            pwdf = p_window / p_center if p_center > 0 else float("nan")
            result[s][r] = {
                "p_window": p_window,
                "p_center": p_center,
                "pwdf": pwdf,
            }

    return {
        "n_spins_sampled": n,
        "top_symbols": top_symbols,
        "per_symbol_per_reel": result,
        "note": "PWDF = p_window / p_center. Per DESIGN_PHILOSOPHY §15.9: mechanism selection (A/B/C) is Designer's Stage 4 decision — Analyst only provides numbers.",
    }


# ======================================================================
# Section 8: Blank-flank diversity
# ======================================================================
def section8_blank_flank(rawdata_dir: Path, blank_symbols: list, max_spins: int = 50000) -> dict:
    """
    Per DESIGN_PHILOSOPHY §13: scan strip layout for X-Blank-X patterns.
    Since we don't have the static strip layout (that's in reel_strips.json which
    doesn't exist yet at Stage 1b), we approximate from the rawdata by collecting
    all observed (prev_sym, sym, next_sym) triplets per reel and flagging
    Blank-flanked patterns where prev == next.

    This is a statistical proxy — true blank-flank analysis requires the static
    strip (Stage 2 Implementer artifact). We flag the approach and provide counts.
    """
    from collections import defaultdict, Counter

    # Per reel: collect sequences of center-row symbols across consecutive spins
    # Note: consecutive spins are NOT consecutive strip positions (random stop).
    # True blank-flank needs the static strip layout string.
    # We do what we can: count how often blank appears with flanking same-symbol.

    reel_triplets = defaultdict(Counter)
    reel_prev = {}
    reel_pprev = {}
    n = 0

    for chunk_idx, spin in iter_chunk_spins(rawdata_dir):
        cols = spin.get("StopSymbolsByCol")
        if cols is None:
            continue
        for reel_i, reel_rows in enumerate(cols):
            if len(reel_rows) < 3:
                continue
            # Within this spin, look at 3 rows as a vertical triplet
            row0, row1, row2 = str(reel_rows[0]), str(reel_rows[1]), str(reel_rows[2])
            if row1 in blank_symbols:
                # row0 and row2 are the flanks
                triplet = (row0, row1, row2)
                reel_triplets[reel_i][triplet] += 1
        n += 1
        if n >= max_spins:
            break

    reel_results = {}
    for reel_i, triplet_counter in reel_triplets.items():
        xbx_count = sum(
            count for (r0, blank, r2), count in triplet_counter.items() if r0 == r2
        )
        total_blank_appearances = sum(triplet_counter.values())
        reel_results[f"R{reel_i+1}"] = {
            "blank_appearances_in_window": total_blank_appearances,
            "xbx_count_observed": xbx_count,
            "xbx_rate": xbx_count / total_blank_appearances if total_blank_appearances else 0.0,
            "top_triplets": triplet_counter.most_common(5),
        }

    return {
        "n_spins_sampled": n,
        "blank_symbols_used": blank_symbols,
        "reel_results": reel_results,
        "method": "Per-spin 3-row window triplet (top/center/bottom) proxy. True strip-level blank-flank requires static reel_strips.json (Stage 2 artifact). Flag: Stage 2 Implementer must verify strip-level §13 compliance.",
    }


# ======================================================================
# Section 9: Feature session bucket
# ======================================================================
def section9_feature(summary: dict) -> dict:
    """
    Per upstream_feature_breakdown:
    - FreeSpin sessions: triggered by ST43 (NormalFreeSpin pays payout_id 666)
    - FreeSpin spins: ST44
    """
    feat_data = summary["player_impact"]["upstream_feature_breakdown"]
    if not feat_data.get("applicable"):
        return {"applicable": False}

    features = feat_data["features"]
    paid_spins = summary["sampling"]["paid_spins"]

    result = {}
    for f in features:
        fname = f["feature_name"]
        fires = f["fires_spins"]
        trigger_rate = fires / paid_spins if fname == "NormalFreeSpin" else f["fire_rate"]
        cadence = paid_spins / fires if fires > 0 else float("inf")

        result[fname] = {
            "fires": fires,
            "fire_rate": f["fire_rate"],
            "cadence_paid_spins_per_trigger": cadence if fname != "FreeSpin" else "N/A (denominator is ST43 spins)",
            "rtp_contribution_pp": f["rtp_contribution_pp"],
            "share_of_total_win": f["share_of_total_win"],
            "bucket_distribution": f["bucket_distribution"],
        }

    # FreeSpin trigger cadence: payout_id 666 hit rate = 1/139.5 paid spins
    pid_666 = next(
        (p for p in summary["player_impact"]["payout_ids_top20"] if p["payout_id"] == "666"),
        None,
    )
    free_spin_trigger = {}
    if pid_666:
        free_spin_trigger = {
            "pay_id": "666",
            "hit_count": pid_666["hit_count"],
            "hit_rate": pid_666["hit_rate"],
            "cadence_per_paid_spin": 1.0 / pid_666["hit_rate"] if pid_666["hit_rate"] > 0 else float("inf"),
        }

    return {
        "applicable": True,
        "free_spin_trigger_pay_id_666": free_spin_trigger,
        "features": result,
    }


# ======================================================================
# Section 5b: Per-reel marginals from a sample of chunks (memory-efficient)
# ======================================================================
def compute_reel_marginals_sample(rawdata_dir: Path, max_spins=50000):
    return section5_reel_marginals(rawdata_dir, max_spins=max_spins)


# ======================================================================
# Chunk 0001 vs chunks 2-25 chi-square RTP comparison
# ======================================================================
def chunk0001_vs_rest(rawdata_dir: Path, summary: dict) -> dict:
    """
    Compare chunk_0001 (seed chunk) vs chunks 0002-0025 on:
    - RTP proxy: WinCredits / BetAmount per spin, aggregated
    Returns per-group mean RTP and simple z-test.
    """
    group_wins = {1: [], "rest": []}
    group_bets = {1: [], "rest": []}

    for chunk_idx, spin in iter_chunk_spins(rawdata_dir):
        win = spin.get("WinCredits", 0)
        bet = spin.get("BetAmount", spin.get("CostCredits", 0))
        key = 1 if chunk_idx == 1 else "rest"
        group_wins[key].append(win)
        group_bets[key].append(bet)

    results = {}
    for key in [1, "rest"]:
        wins = group_wins[key]
        bets = group_bets[key]
        n = len(wins)
        if n == 0:
            results[key] = {"n": 0}
            continue
        total_win = sum(wins)
        total_bet = sum(bets)
        rtp = total_win / total_bet if total_bet else 0.0
        # Variance of per-spin return_x
        avg_x = total_win / total_bet if total_bet else 0.0
        return_xs = [w / b if b else 0.0 for w, b in zip(wins, bets)]
        var_x = sum((x - avg_x) ** 2 for x in return_xs) / n if n > 1 else 0.0
        std_err = math.sqrt(var_x / n) if n > 0 else 0.0
        results[key] = {
            "n_spins": n,
            "total_win": total_win,
            "total_bet": total_bet,
            "rtp_pct": rtp * 100,
            "std_err_pp": std_err * 100,
        }

    # Z-test
    r1 = results.get(1, {})
    rr = results.get("rest", {})
    z = None
    if r1 and rr and r1.get("std_err_pp", 0) and rr.get("std_err_pp", 0):
        diff = r1["rtp_pct"] - rr["rtp_pct"]
        se_pooled = math.sqrt(r1["std_err_pp"] ** 2 + rr["std_err_pp"] ** 2)
        z = diff / se_pooled if se_pooled else float("nan")

    results["z_score"] = z
    results["flag"] = abs(z) > 2.0 if z is not None and not math.isnan(z) else False
    return results


# ======================================================================
# Main: run all sections and print summary
# ======================================================================
def main():
    print("Loading summary JSON...")
    summary = load_summary(SUMMARY_JSON)

    print("\n=== SECTION 1: Per-Mode Totals ===")
    s1 = section1_mode_totals(summary)
    for k, v in s1.items():
        print(f"  {k}: {v}")

    print("\n=== SECTION 2: Bucket Distribution ===")
    s2 = section2_buckets(summary)
    print(f"  {'Bucket':<20} {'Rate%':>8} {'RTP_pp':>8} {'AvgX':>8}")
    for b in s2:
        print(f"  {b['bucket']:<20} {b['rate_pct']:>8.4f} {b['rtp_contribution_pp']:>8.4f} {b['avg_return_x']:>8.4f}")

    print("\n=== SECTION 3: Per pay_id Breakdown ===")
    s3 = section3_pay_ids(summary)
    print(f"  {'pay_id':<8} {'hit_rate':>12} {'1_in_N':>12} {'rtp_pp':>10} {'avg_win':>12}")
    for p in s3:
        one_in = f"{p['one_in_n']:.1f}" if p["one_in_n"] else "-"
        avg_win = f"{p['avg_win_when_hit']:.0f}" if p["avg_win_when_hit"] else "-"
        print(f"  {p['pay_id']:<8} {p['hit_rate']:>12.6f} {one_in:>12} {p['rtp_pp']:>10.4f} {avg_win:>12}")

    print("\n=== SECTION 4: Family RTP Share (PRELIMINARY) ===")
    s4 = section4_families(summary)
    print(f"  {'Family':<35} {'RTP_pp':>8} {'Share%':>8}")
    for f in s4:
        print(f"  {f['family']:<35} {f['rtp_pp']:>8.4f} {f['share_pct']:>8.2f}")

    print("\n=== SECTION 5: Per-Reel Marginals (50k spin sample) ===")
    s5 = section5_reel_marginals(RAWDATA_DIR, max_spins=50000)
    print(f"  Sampled {s5['n_spins_sampled']} spins across {s5['n_reels']} reels")
    symbols = s5["symbols"]
    reel_keys = sorted(s5["marginals"].keys())
    print(f"  {'Symbol':<8}", end="")
    for r in reel_keys:
        print(f"  {r:>8}", end="")
    print()
    for sym in symbols:
        print(f"  {sym:<8}", end="")
        for r in reel_keys:
            p = s5["marginals"][r].get(sym, 0.0)
            print(f"  {p:>8.4f}", end="")
        print()

    # Infer top symbols from pay_id data: avg_win_when_hit > 5000 credits
    top_syms_candidates = []
    for p in summary["player_impact"]["payout_ids_top20"]:
        if p["avg_win_when_hit"] >= 5000 and p["payout_id"] not in ["666"]:
            # Top symbols appear in paylines for these pay_ids
            # We'll use symbol 7 and 8 as likely high-value symbols from payline_symbol data
            pass
    # From payline_symbol_top20: symbols 7, 8 dominate high RTP. 8 = likely wild/mid-high, 7 = high
    # pid 1 (30x avg win) and pid 2 (15x) are top jackpot. We approximate top symbols as those
    # appearing in pid 1/2/3 paylines. From paylines_top20 top_symbols lists, symbols 7,8 dominant.
    # Use symbols with highest per-reel density among high-pay pids.
    top_syms = ["7", "8"]  # refined in Stage 1c; best guess from payline_symbol_top20

    print("\n=== SECTION 6: Reel Asymmetry ===")
    # Blank symbol: identify the most-common non-winning symbol
    # From summary: pay_id 666 has 0 win but 2974 hits = likely trigger marker, not blank
    # Blank is typically the loss symbol. In StopSymbolsByCol, we look for highest density sym.
    # From marginals, find symbol not in [7,8] with highest avg density
    all_sym_densities = {}
    for sym in s5["symbols"]:
        densities = [s5["marginals"][r].get(sym, 0.0) for r in reel_keys]
        all_sym_densities[sym] = sum(densities) / len(densities)

    # Top 5 densest symbols (likely include blank)
    densest = sorted(all_sym_densities.items(), key=lambda x: x[1], reverse=True)[:10]
    print(f"  Top 10 densest symbols (avg marginal): {densest}")

    s6 = section6_reel_asymmetry(s5, top_syms)
    print(f"  Blank candidates (approx): {s6['blank_candidates_used']}")
    for r, stats in s6["reel_stats"].items():
        print(f"  {r}: blank_density={stats['blank_density_approx']:.4f}, top_density={stats['top_density']:.4f}")
    print(f"  R1 blank <= Rlast blank: {'OK' if s6['blank_direction_R1_le_Rlast'] else 'VIOLATED'}")
    print(f"  R1 top >= Rlast top: {'OK' if s6['top_direction_R1_ge_Rlast'] else 'VIOLATED'}")

    print("\n=== SECTION 7: PWDF Window Visibility ===")
    s7 = section7_pwdf(RAWDATA_DIR, top_syms, max_spins=50000)
    print(f"  Sampled {s7['n_spins_sampled']} spins")
    for sym, reel_data in s7["per_symbol_per_reel"].items():
        print(f"  Symbol {sym}:")
        for r, vals in reel_data.items():
            print(f"    {r}: p_window={vals['p_window']:.4f}, p_center={vals['p_center']:.4f}, PWDF={vals['pwdf']:.2f}")

    print("\n=== SECTION 8: Blank-Flank (Proxy via 3-row window) ===")
    # Use top densest non-top symbols as blank candidates
    blank_syms = [s for s, _ in densest if s not in top_syms][:3]
    s8 = section8_blank_flank(RAWDATA_DIR, blank_syms, max_spins=50000)
    print(f"  Method: {s8['method']}")
    print(f"  Blank symbols used (approx): {s8['blank_symbols_used']}")
    for r, rd in s8["reel_results"].items():
        print(f"  {r}: blank_window_appearances={rd['blank_appearances_in_window']}, xbx_count={rd['xbx_count_observed']}, xbx_rate={rd['xbx_rate']:.4f}")

    print("\n=== SECTION 9: Feature Session Bucket ===")
    s9 = section9_feature(summary)
    if s9["applicable"]:
        pid666 = s9["free_spin_trigger_pay_id_666"]
        print(f"  FreeSpin trigger (pay_id 666): hit_count={pid666['hit_count']}, rate={pid666['hit_rate']:.6f}, 1-in-{pid666['cadence_per_paid_spin']:.1f} paid spins")
        for fname, fdata in s9["features"].items():
            print(f"  Feature: {fname}")
            print(f"    fires={fdata['fires']}, rtp_contribution_pp={fdata['rtp_contribution_pp']:.4f}")
            print(f"    bucket distribution:")
            for b in fdata["bucket_distribution"]:
                if b["spin_count"] > 0:
                    print(f"      {b['bucket']}: rate={b['spin_rate']*100:.3f}%, rtp_pp={b['rtp_contribution_pp']:.4f}")

    print("\n=== SECTION 10: N/A (mode-1-first session) ===")
    print("  Cross-mode top-prize escalation: N/A - only mode 1 onboarded this session")

    print("\n=== SECTION 11: N/A (mode-1-first session) ===")
    print("  Cross-mode invariants: N/A - only mode 1 onboarded this session")

    print("\n=== SECTION 12: Schema Fingerprint ===")
    print("  See session_artifacts/M31/01a_data_inventory.md §3")
    print("  Fingerprint: 5d02773c069fc396, 17-field roundResult, CLEAN")

    print("\n=== CHUNK 0001 vs CHUNKS 2-25 COMPARISON ===")
    print("  Running chunk comparison (all spins)...")
    s_chunk = chunk0001_vs_rest(RAWDATA_DIR, summary)
    c1 = s_chunk.get(1, {})
    cr = s_chunk.get("rest", {})
    print(f"  chunk_0001: n={c1.get('n_spins')}, rtp={c1.get('rtp_pct',0):.2f}%, std_err={c1.get('std_err_pp',0):.3f}pp")
    print(f"  chunks_2-25: n={cr.get('n_spins')}, rtp={cr.get('rtp_pct',0):.2f}%, std_err={cr.get('std_err_pp',0):.3f}pp")
    print(f"  z_score={s_chunk.get('z_score')}, flag={s_chunk.get('flag')}")

    print("\n=== CROSS-SIGNAL VERIFICATION ===")
    total_rtp = summary["rtp"]["point_pct"]
    pid_rtp_sum = sum(p["rtp_contribution_pp"] for p in summary["player_impact"]["payout_ids_top20"])
    delta = abs(pid_rtp_sum - total_rtp)
    print(f"  sum(pay_id RTP) = {pid_rtp_sum:.5f} pp, summary RTP = {total_rtp:.5f} pp, delta = {delta:.5f} pp")
    print(f"  Cross-signal check: {'OK' if delta < 0.01 else 'FAIL'}")

    hit_sum = sum(p["hit_rate"] for p in summary["player_impact"]["payout_ids_top20"])
    win_hit = summary["player_impact"]["hit_and_payout"]["win_hit_rate"]
    print(f"  sum(pay_id hit_rate) = {hit_sum:.6f}, win_hit_rate = {win_hit:.6f}")
    print("  Note: pay_id hit rates can sum > win_hit_rate (one round can hit multiple pay_ids)")

    bucket_rate_sum = sum(b["spin_rate"] for b in summary["player_impact"]["multiplier_profile"]["buckets"])
    print(f"  sum(bucket rates) = {bucket_rate_sum:.6f}, win_hit_rate = {win_hit:.6f}")
    print(f"  Bucket rate sum == win_hit_rate: {'OK' if abs(bucket_rate_sum - win_hit) < 0.0001 else 'FAIL'}")

    print("\nDone.")
    return {
        "s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5,
        "s6": s6, "s7": s7, "s8": s8, "s9": s9, "s_chunk": s_chunk,
    }


if __name__ == "__main__":
    main()
