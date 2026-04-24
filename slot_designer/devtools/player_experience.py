"""Player-experience metrics computed from reel strip ordering.

Ordering doesn't affect payline-only math (RTP / bucket / hit rate)
because those depend only on per-symbol marginals. But ordering DOES
affect:

  - Near-miss perception (Harrigan 2009): high-value symbols visible
    in top/bot row create "almost won" feeling. Clustering blanks
    around high-value symbols makes them appear in the window more
    often than on the payline.
  - Visible variety: number of distinct symbols shown in the 3×3 grid
    per spin. Too monotone → boring; too chaotic → overwhelming.
  - Passing-by animation quality: how high-value symbols are spaced
    across the reel affects the visual rhythm as the reel cycles past
    during the spin animation.

All metrics here are **analytic** (computed directly from the strip
definition, no sampling) and preserve under re-sampling.

Research references (2026-04-20 fresh search; see
reference_slot_design_research_keywords.md):
  - Harrigan K. (2009). Slot Machines: Pursuing Responsible Gaming
    Practices for Virtual Reels and Near Misses. Int J Ment Health
    Addiction. Definitive description of clustering technique (p. 74-76).
  - Nevada Gaming Commission 1989: on-payline "secondary decision"
    near-misses disallowed; off-payline virtual-reel clustering allowed.
"""
from __future__ import annotations

from typing import Iterable


def _cyclic(items: list, i: int) -> any:
    return items[i % len(items)]


def _window_stop_syms(strip: list[dict], stop_idx: int) -> tuple[str, str, str]:
    """(top, mid, bot) symbols for a given stop index, cyclic."""
    n = len(strip)
    return (
        strip[(stop_idx - 1) % n]["symbol"],
        strip[stop_idx]["symbol"],
        strip[(stop_idx + 1) % n]["symbol"],
    )


def _total_weight(strip: list[dict]) -> int:
    return sum(int(s["weight"]) for s in strip)


def symbol_mid_probability(strip: list[dict], symbol: str) -> float:
    """P(middle row of this reel shows `symbol`) — == Phase 4's marginal."""
    tw = _total_weight(strip)
    if tw <= 0:
        return 0.0
    return sum(int(s["weight"]) for s in strip if s["symbol"] == symbol) / tw


def symbol_window_probability(strip: list[dict], symbol: str) -> float:
    """P(`symbol` appears anywhere in the 3-row window of this reel).

    For each stop i (weight w_i), `symbol` is visible in the window if
    it appears at position (i-1), i, or (i+1). Count the stops whose
    sampling makes `symbol` visible, weight by stop weights.
    """
    tw = _total_weight(strip)
    if tw <= 0:
        return 0.0
    visible_w = 0
    n = len(strip)
    for i in range(n):
        top_sym = strip[(i - 1) % n]["symbol"]
        mid_sym = strip[i]["symbol"]
        bot_sym = strip[(i + 1) % n]["symbol"]
        if symbol in (top_sym, mid_sym, bot_sym):
            visible_w += int(strip[i]["weight"])
    return visible_w / tw


def symbol_window_only_probability(strip: list[dict], symbol: str) -> float:
    """P(`symbol` in top or bot row AND not on mid row).

    This is the "adjacent-only" probability — the key input to
    2-of-3 near-miss computation. When mid shows a different symbol but
    the edge rows expose `symbol`, the player perceives a near-miss.
    """
    tw = _total_weight(strip)
    if tw <= 0:
        return 0.0
    adj_only_w = 0
    n = len(strip)
    for i in range(n):
        mid_sym = strip[i]["symbol"]
        if mid_sym == symbol:
            continue  # S is on payline → not an "adjacent-only" case
        top_sym = strip[(i - 1) % n]["symbol"]
        bot_sym = strip[(i + 1) % n]["symbol"]
        if symbol in (top_sym, bot_sym):
            adj_only_w += int(strip[i]["weight"])
    return adj_only_w / tw


def pwdf_ratio(strip: list[dict], symbol: str) -> float:
    """Harrigan's Payline Window Distortion Factor = p_window / p_mid.

    1.0 = symbol appears equally in window and on payline (no distortion).
    >1 = symbol visible more than it actually pays (clustering effect).
    Typical high-clustering PAR sheets achieve 3-6 for jackpot symbols.
    """
    mid_p = symbol_mid_probability(strip, symbol)
    if mid_p <= 0:
        return 0.0
    win_p = symbol_window_probability(strip, symbol)
    return win_p / mid_p


def reel_blank_adjacency_score(strip: list[dict], high_value: Iterable[str],
                                blank_symbol: str = "Blank") -> float:
    """Fraction of high-value stops that have a blank directly adjacent
    (top or bot). High = Harrigan-style clustering; low = dispersed layout.
    """
    hv_set = set(high_value)
    hv_stops = [i for i, s in enumerate(strip) if s["symbol"] in hv_set]
    if not hv_stops:
        return 0.0
    n = len(strip)
    adjacency = 0
    for i in hv_stops:
        if strip[(i - 1) % n]["symbol"] == blank_symbol:
            adjacency += 1
        if strip[(i + 1) % n]["symbol"] == blank_symbol:
            adjacency += 1
    # Normalize: 2 adjacencies per stop is max (both sides blank)
    return adjacency / (2 * len(hv_stops))


def near_miss_rate_2_of_3(
    reels: list[list[dict]],
    symbol: str,
) -> float:
    """Analytic P(2-of-3 near-miss for `symbol` this spin).

    A 2-of-3 near-miss fires when:
      - exactly 2 of the 3 payline cells show `symbol`
      - on the 3rd reel, `symbol` is visible in the top or bot row

    Both conditions must hold. Computed exactly from per-reel marginals
    and window probabilities — no sampling.
    """
    n_reels = len(reels)
    if n_reels != 3:
        raise NotImplementedError("near_miss_rate_2_of_3 is M1-style 3-reel only")

    p_mid = [symbol_mid_probability(r, symbol) for r in reels]
    p_adj_only = [symbol_window_only_probability(r, symbol) for r in reels]

    total = 0.0
    # For each choice of "the missing reel" (where S is visible adjacent-only)
    for missing in range(3):
        others = [k for k in range(3) if k != missing]
        p_others_both_mid = p_mid[others[0]] * p_mid[others[1]]
        total += p_others_both_mid * p_adj_only[missing]
    return total


def visible_variety_score(
    reels: list[list[dict]],
    blank_symbol: str = "blank",
) -> float:
    """Expected number of distinct non-blank symbols visible in the 3×3 grid
    per spin. Higher = more varied view.

    Computed analytically by enumerating joint outcomes; for M1-size reels
    (36 stops × 3 reels = 36³ = 46656) this is feasible.

    ``blank_symbol`` defaults to lowercase ``"blank"`` (M15+ / production
    schema). Callers with M1-style PascalCase ``"Blank"`` should pass it
    explicitly.
    """
    if len(reels) != 3:
        raise NotImplementedError("visible_variety_score is 3-reel only")
    n0, n1, n2 = len(reels[0]), len(reels[1]), len(reels[2])
    totals = [_total_weight(r) for r in reels]
    if any(t <= 0 for t in totals):
        return 0.0

    ev = 0.0
    for i in range(n0):
        w0, (t0, m0, b0) = int(reels[0][i]["weight"]), _window_stop_syms(reels[0], i)
        for j in range(n1):
            w1, (t1, m1, b1) = int(reels[1][j]["weight"]), _window_stop_syms(reels[1], j)
            for k in range(n2):
                w2, (t2, m2, b2) = int(reels[2][k]["weight"]), _window_stop_syms(reels[2], k)
                all_syms = {t0, m0, b0, t1, m1, b1, t2, m2, b2}
                distinct = len({s for s in all_syms if s != blank_symbol})
                prob = (w0 * w1 * w2) / (totals[0] * totals[1] * totals[2])
                ev += prob * distinct
    return ev


def experience_metrics(
    reels: list[list[dict]],
    *,
    high_value: Iterable[str] = ("Seven1", "Seven2", "Diamond1", "Diamond2"),
    blank_symbol: str = "Blank",
    compute_variety: bool = False,
) -> dict:
    """One-shot summary of all experience metrics for a reel set.

    `compute_variety` off by default — it's O(Π n_reels) and slows down
    the inner loop of the ordering optimizer. Compute once at the end
    for the report.
    """
    hv = list(high_value)

    per_reel = []
    for idx, r in enumerate(reels):
        per_reel.append({
            "reel": idx,
            "blank_adj_hv": reel_blank_adjacency_score(r, hv, blank_symbol),
            "pwdf": {s: pwdf_ratio(r, s) for s in hv},
        })

    near_miss = {s: near_miss_rate_2_of_3(reels, s) for s in hv}

    # Average PWDF across reels — aggregate distortion proxy
    avg_pwdf = {
        s: sum(per_reel[k]["pwdf"].get(s, 0) for k in range(len(reels))) / len(reels)
        for s in hv
    }

    out = {
        "per_reel": per_reel,
        "near_miss_rate_per_symbol": near_miss,
        "near_miss_rate_total": sum(near_miss.values()),
        "avg_pwdf": avg_pwdf,
        "avg_blank_adj": sum(p["blank_adj_hv"] for p in per_reel) / len(per_reel),
    }
    if compute_variety:
        out["expected_distinct_symbols_visible"] = visible_variety_score(
            reels, blank_symbol=blank_symbol,
        )
    return out
