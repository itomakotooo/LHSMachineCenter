"""Convert between per-(symbol, reel) counts and full weights dicts.

The tuner's search variable is per-(symbol, reel) counts — 9 × 3 = 27
integers for M1. Analytic RTP/bucket only depends on these aggregate
counts (marginals), so this is the natural search dimension.

But our simulator and existing rawdata emitter need full reel strips
(list of (symbol, weight) per stop). When the tuner finds promising
counts, we need to materialize them back into a weights file.

Strategy: **preserve user's stop positions and ordering**, rescale
weight at each stop so per-(symbol, reel) totals match the target
counts. If a symbol was absent from the base strip, we can't add it
(would need to inject new stops — deferred to Phase 4b). Symbols
reduced to 0 are clamped to min_count (default 1) so the reel remains
valid — user can manually remove afterwards.

Two entry points:
  - ``base_counts(weights_dict)`` → ``{reel_idx: {symbol: count}}``
  - ``apply_counts(weights_dict, new_counts)`` → new weights_dict with
    stops rescaled to match new_counts

Two-file schema helpers (2026-04-22):
  - ``base_counts_from_assembled(reels)`` — same as base_counts but
    takes the assembled [[{sym, wt}, ...], ...] shape directly (used
    when reading strips + weights.json pair rather than an old-style
    reel_weights.json).
  - ``disassemble_to_weights_array(reels)`` — project assembled shape
    back to a list-of-int-arrays for writing to mode_<N>/weights.json.
"""
from __future__ import annotations

import copy
from collections import defaultdict


def base_counts(weights_dict: dict, reel_set_name: str = "default") -> list[dict[str, int]]:
    """Extract per-reel per-symbol current totals from a weights JSON dict."""
    reels = weights_dict["reel_sets"][reel_set_name]["reels"]
    out: list[dict[str, int]] = []
    for reel in reels:
        sym_total: dict[str, int] = defaultdict(int)
        for stop in reel:
            sym_total[stop["symbol"]] += int(stop["weight"])
        out.append(dict(sym_total))
    return out


def marginals_from_counts(counts_list: list[dict[str, int]]) -> list[dict[str, float]]:
    """Aggregate counts → per-reel symbol marginal probabilities."""
    out = []
    for counts in counts_list:
        total = sum(counts.values())
        if total <= 0:
            out.append({})
            continue
        out.append({s: c / total for s, c in counts.items() if c > 0})
    return out


def apply_counts(
    weights_dict: dict,
    new_counts: list[dict[str, int]],
    reel_set_name: str = "default",
    min_weight: int = 1,
) -> dict:
    """Produce a new weights dict with per-(symbol, reel) totals matching new_counts.

    For each reel, each symbol's existing stops are rescaled by the ratio
    new_total / current_total. Rounding errors distribute to the first stop
    so totals land exactly on target (within min_weight clamp floor).

    If a symbol is present in new_counts but not in the reel's existing
    stops, raises NotImplementedError — adding new symbols / stops is a
    Phase 4b extension.
    """
    out = copy.deepcopy(weights_dict)
    reels = out["reel_sets"][reel_set_name]["reels"]

    for reel_idx, reel in enumerate(reels):
        target = new_counts[reel_idx]

        # Group stop indices by symbol (preserves original positions)
        stop_idxs_by_sym: dict[str, list[int]] = defaultdict(list)
        for i, stop in enumerate(reel):
            stop_idxs_by_sym[stop["symbol"]].append(i)

        for sym, target_total in target.items():
            if sym not in stop_idxs_by_sym:
                raise NotImplementedError(
                    f"reel {reel_idx}: symbol {sym!r} not in base strip; adding new "
                    f"stops is Phase 4b"
                )
            idxs = stop_idxs_by_sym[sym]
            current_total = sum(reel[i]["weight"] for i in idxs)
            if current_total == 0:
                # Distribute equally as fallback
                per = max(min_weight, target_total // len(idxs))
                for i in idxs:
                    reel[i]["weight"] = per
                continue

            # Proportional rescale
            scale = target_total / current_total
            scaled = [max(min_weight, int(round(reel[i]["weight"] * scale))) for i in idxs]
            # Repair rounding drift: distribute the delta across stops.
            # Old impl pushed the entire diff onto scaled[0]; if diff was
            # more negative than scaled[0] - min_weight, the clamp absorbed
            # the excess and target_total was silently missed (observed in
            # M37 mode 5 reel 3 blank: 120→113 drift of -7 clamped to 0).
            # Spread across stops so every stop drops/rises by 1 until diff
            # lands. Only floor-clamped stops are skipped.
            diff = target_total - sum(scaled)
            if diff != 0:
                step = 1 if diff > 0 else -1
                remaining = abs(diff)
                # Iterate stops in a stable order until diff consumed or
                # all stops clamped.
                guard = 0
                while remaining > 0 and guard < 10 * len(scaled):
                    any_adjusted = False
                    for j in range(len(scaled)):
                        if remaining == 0:
                            break
                        if step < 0 and scaled[j] <= min_weight:
                            continue  # can't drop below floor
                        scaled[j] += step
                        remaining -= 1
                        any_adjusted = True
                    if not any_adjusted:
                        # Every stop is at the floor and diff is still
                        # negative — target_total < len(idxs)*min_weight,
                        # physically unachievable without removing stops.
                        break
                    guard += 1
            for i, w in zip(idxs, scaled):
                reel[i]["weight"] = w

    return out


def counts_sanity(counts: list[dict[str, int]]) -> tuple[bool, str]:
    """Basic invariant checks. Returns (ok, message)."""
    for reel_idx, reel in enumerate(counts):
        if not reel:
            return False, f"reel {reel_idx} has no symbols"
        for sym, n in reel.items():
            if n < 0:
                return False, f"reel {reel_idx} symbol {sym!r}: negative count {n}"
    return True, "ok"


def base_counts_from_assembled(
    reels: list[list[dict]],
) -> list[dict[str, int]]:
    """Same as ``base_counts`` but operates on the already-assembled
    ``[[{symbol, weight}, ...], ...]`` shape — handy when the caller
    already combined strips + weights via ``load_reels_for_tuner``
    and doesn't want to re-wrap into the old weights_dict envelope.
    """
    out: list[dict[str, int]] = []
    for reel in reels:
        sym_total: dict[str, int] = defaultdict(int)
        for stop in reel:
            sym_total[stop["symbol"]] += int(stop["weight"])
        out.append(dict(sym_total))
    return out


def disassemble_to_weights_array(
    reels: list[list[dict]],
) -> list[list[int]]:
    """Project the assembled ``[[{symbol, weight}, ...], ...]`` shape
    back to the list-of-int-arrays that ``mode_<N>/weights.json``
    stores under its ``weights`` key.

    Inverse of ``engine.loader._assemble_reels``: given (strips,
    weights_array) → assembled → this helper → weights_array.
    """
    return [
        [int(stop["weight"]) for stop in reel]
        for reel in reels
    ]


def extract_symbol_layout(
    reels: list[list[dict]],
) -> list[list[str]]:
    """Project assembled reels to the symbol-only layout that
    ``reel_strips.json`` stores under its ``reels`` key.
    """
    return [
        [stop["symbol"] for stop in reel]
        for reel in reels
    ]
