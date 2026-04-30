"""Post-tune PWDF redistribution for M37 (DESIGN_PHILOSOPHY §15.5 机制 B).

What it does:
  Per reel, the TOTAL Blank weight is conserved. Blanks adjacent to a "top
  symbol" absorb the mass; Blanks far from top symbols drop to weight=1.

What it changes:
  Window visibility of top symbols ↑ ~10pp. RTP / hit / per-symbol marginals
  UNCHANGED (the redistribution is per-symbol mass conserving).

Why M37 needs it:
  Mode 1 booster window vis only 22% (philosophy K=4-10x vs payline; M37
  achieves 2.2x). Without redistribute, optimizer can't lift visibility
  while preserving RTP — they fight each other in the cost surface.

Per-reel target top symbols (M37 specific):
  R1 / R3:  high7 + wild  (top-jackpot path: 3-high7 with grand mult = 1000×)
  R2:       grand          (lifetime tier symbol; near-miss psychology)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.devtools.analytic_rtp import analytic_profile
from slot_designer.engine.loader import load_engine

SPEC_PATH = _ROOT / "slot_designer" / "specs" / "M37.spec.json"
STRIPS_PATH = _ROOT / "slot_designer" / "weights" / "M37" / "reel_strips.json"
WEIGHTS_DIR = _ROOT / "slot_designer" / "weights" / "M37"

# Per-reel top symbols — the symbols whose window-visibility we want to lift.
TOP_SYMBOLS_PER_REEL = {
    0: ("high7", "wild"),
    1: ("grand",),
    2: ("high7", "wild"),
}

MIN_WEIGHT = 1


def _top_adj_blank_indices(reel: list[str], top_symbols: tuple[str, ...]) -> set[int]:
    """Indices where strip[i] == 'blank' AND a top symbol is at i-1 or i+1 (cyclic)."""
    n = len(reel)
    out = set()
    for i, s in enumerate(reel):
        if s != "blank":
            continue
        prev_s = reel[(i - 1) % n]
        next_s = reel[(i + 1) % n]
        if prev_s in top_symbols or next_s in top_symbols:
            out.add(i)
    return out


def redistribute_reel(weights: list[int], reel: list[str],
                      top_symbols: tuple[str, ...],
                      ratio: float = 3.0) -> list[int]:
    """Redistribute blank weights with bounded concentration.

    `ratio` = top-adj blank weight / non-top-adj blank weight.
        ratio=1.0 → no redistribution (uniform)
        ratio=3.0 → top-adj 3× heavier (moderate lift, ~30% vis)
        ratio=∞   → all mass on top-adj (extreme; M37 physical reel landed
                    at 73% grand vis which is too high — kills near-miss)

    Total blank weight is conserved exactly.
    """
    blank_indices = [i for i, s in enumerate(reel) if s == "blank"]
    top_adj = _top_adj_blank_indices(reel, top_symbols)

    total_blank_weight = sum(weights[i] for i in blank_indices)
    non_top_adj = sorted(i for i in blank_indices if i not in top_adj)
    top_adj_sorted = sorted(top_adj)
    n_non_top = len(non_top_adj)
    n_top_adj = len(top_adj_sorted)

    if n_top_adj == 0 or n_non_top == 0:
        return list(weights)

    # Solve: n_top_adj * w_top + n_non_top * w_non = total_blank_weight
    # with w_top = ratio * w_non
    # → w_non * (n_non_top + ratio * n_top_adj) = total_blank_weight
    w_non = total_blank_weight / (n_non_top + ratio * n_top_adj)
    w_top = ratio * w_non

    # Round to integers, distribute leftover to keep sum exact
    w_non_int = max(MIN_WEIGHT, int(round(w_non)))
    w_top_int = max(MIN_WEIGHT, int(round(w_top)))

    new_weights = list(weights)
    for i in non_top_adj:
        new_weights[i] = w_non_int
    for i in top_adj_sorted:
        new_weights[i] = w_top_int

    # Adjust to exactly match total
    current_sum = n_non_top * w_non_int + n_top_adj * w_top_int
    diff = total_blank_weight - current_sum
    # Distribute diff among top-adj blanks (1 unit at a time)
    j = 0
    while diff != 0 and top_adj_sorted:
        idx = top_adj_sorted[j % n_top_adj]
        if diff > 0:
            new_weights[idx] += 1
            diff -= 1
        elif new_weights[idx] > MIN_WEIGHT:
            new_weights[idx] -= 1
            diff += 1
        j += 1
        if j > 1000:
            break  # safety

    # Sanity check
    new_blank_total = sum(new_weights[i] for i in blank_indices)
    assert new_blank_total == total_blank_weight, (
        f"Blank weight not conserved: was {total_blank_weight}, now {new_blank_total}"
    )
    return new_weights


def _densities(weights: list[list[int]], strips: list[list[str]]) -> dict:
    out: dict = defaultdict(float)
    for r in range(3):
        total = sum(weights[r])
        if total == 0:
            continue
        for w, s in zip(weights[r], strips[r]):
            out[(s, r)] += w / total
    return dict(out)


def _window_vis(p: float) -> float:
    """3-row window visibility for a symbol with marginal density p."""
    return 1.0 - (1.0 - p) ** 3


def report_visibility(label: str, weights: list[list[int]], strips: list[list[str]]):
    densities = _densities(weights, strips)
    print(f"  [{label:<8}]  ", end="")
    print(
        f"R1 high7 vis {_window_vis(densities.get(('high7', 0), 0))*100:.1f}% / "
        f"R1 wild vis {_window_vis(densities.get(('wild', 0), 0))*100:.1f}% | "
        f"R2 grand vis {_window_vis(densities.get(('grand', 1), 0))*100:.1f}% / "
        f"R2 booster_combined vis {_window_vis(sum(densities.get((s, 1), 0) for s in ('mini','minor','major','grand')))*100:.1f}% | "
        f"R3 high7 vis {_window_vis(densities.get(('high7', 2), 0))*100:.1f}% / "
        f"R3 wild vis {_window_vis(densities.get(('wild', 2), 0))*100:.1f}%"
    )


def process_mode(mode: int):
    strips_data = json.loads(STRIPS_PATH.read_text(encoding="utf-8"))
    strips = strips_data["reels"]
    weights_path = WEIGHTS_DIR / f"mode_{mode}" / "weights.json"
    data = json.loads(weights_path.read_text(encoding="utf-8"))
    old_weights = data["weights"]

    print(f"\n=== Mode {mode} ===")
    # Before
    engine_before, _ = load_engine(SPEC_PATH, weights_path)
    pred_before = analytic_profile(engine_before)
    print(f"  BEFORE  RTP={pred_before['rtp_pct']:.4f}%  hit={pred_before['hit_rate']:.4%}  CV={pred_before.get('cv',0):.3f}")
    report_visibility("BEFORE", old_weights, strips)

    # Redistribute
    new_weights = []
    for r_idx in range(3):
        new_row = redistribute_reel(
            old_weights[r_idx], strips[r_idx], TOP_SYMBOLS_PER_REEL[r_idx]
        )
        new_weights.append(new_row)

    # Write
    data["weights"] = new_weights
    notes = data.get("_notes", [])
    redist_note = f"PWDF redistributed (RTP-neutral, §15.5 mechanism B). top-adj = R1/R3 high7+wild, R2 grand."
    if redist_note not in notes:
        notes.append(redist_note)
    data["_notes"] = notes
    weights_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # After
    engine_after, _ = load_engine(SPEC_PATH, weights_path)
    pred_after = analytic_profile(engine_after)
    print(f"  AFTER   RTP={pred_after['rtp_pct']:.4f}%  hit={pred_after['hit_rate']:.4%}  CV={pred_after.get('cv',0):.3f}")
    report_visibility("AFTER", new_weights, strips)

    # Verify RTP / hit / CV unchanged (within float precision)
    rtp_diff = abs(pred_before["rtp_pct"] - pred_after["rtp_pct"])
    hit_diff = abs(pred_before["hit_rate"] - pred_after["hit_rate"])
    cv_diff = abs(pred_before.get("cv", 0) - pred_after.get("cv", 0))
    print(f"  diff: ΔRTP={rtp_diff:.6f}pp  Δhit={hit_diff:.6%}  ΔCV={cv_diff:.6f}")
    if rtp_diff > 0.001 or hit_diff > 0.00001:
        print(f"  ⚠ WARNING: marginals shifted! redistribution should be RTP-neutral.")


def main():
    for mode in (1, 7, 2, 5):
        process_mode(mode)
    print("\nDone. Run verify_m37_design.py to confirm 100/100 GREEN preserved.")


if __name__ == "__main__":
    main()
