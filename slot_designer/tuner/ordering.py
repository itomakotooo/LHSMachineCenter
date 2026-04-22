"""Stop-order optimizer via simulated annealing.

Phase 5 counterpart to Phase 4's count tuning:

- Phase 4 tunes per-(symbol, reel) totals → marginals → RTP/bucket ✓
- Phase 5 tunes per-reel stop ORDER → near-miss / visibility / PWDF ✓

Permutation preserves symbol counts (and therefore marginals), so
Phase 5 **cannot regress** Phase 4's hard constraints. That's the
invariant this module relies on — mutations only swap positions within
a reel, never add/remove stops or change symbol identity.

Cost composition:
  - `near_miss_target` — target 2-of-3 near-miss rate (research-informed
    moderate range; user can override). Quadratic penalty.
  - `pwdf_bonus` — reward for high-value symbols showing up in the
    window more than on the payline (Harrigan clustering). Capped to
    avoid runaway distortion.
  - `variety_bonus` — optional; O(N_cols product) to compute. Off in
    hot loop; on for final report.

Simulated annealing with swap mutation is the natural fit for this
combinatorial (permutation) space. Works on 36-stop reels within a few
thousand evaluations.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from random import Random
from typing import Callable, Iterable

from slot_designer.devtools.player_experience import (
    experience_metrics,
    near_miss_rate_2_of_3,
    reel_blank_adjacency_score,
    symbol_mid_probability,
    symbol_window_probability,
)


@dataclass
class ExperienceCostWeights:
    """Tolerance-band + bonus cost — doesn't fight a good initial design.

    Research context (Harrigan 2009, 2020 near-miss review):
      - Clustering blanks around high-value symbols is a valid design
        technique; uncapped reward for high PWDF would push optimizer
        to drive it infinitely, which isn't meaningful. Cap at a
        reasonable level.
      - Near-miss rate too low (< 1%) feels dull; too high (> 10%)
        feels rigged. Target is a band, not a point.
      - Blank-adjacency to high-value: pure bonus, capped at 0.8
        (above that, zero marginal gain).
      - **Blank/non-Blank alternation** (2026-04-22 user rule): on a
        reel strip, Blanks must never be adjacent to another Blank,
        and non-Blanks must never be adjacent to another non-Blank.
        Enforced as a hard invariant by ``initialize_alternating`` +
        ``class_preserving_swap_mutation`` (not by cost penalty) —
        that way the invariant is preserved at every SA step without
        relying on a huge penalty weight to dominate other terms.
    """
    # Near-miss band [nm_min, nm_max]. Outside band → quadratic penalty.
    # Default band 1%-10% total across high-value symbols.
    nm_min: float = 0.01
    nm_max: float = 0.10
    nm_band_weight: float = 500.0

    # Blank-adjacency bonus (linear up to cap, flat above)
    blank_adj_cap: float = 0.8
    blank_adj_bonus_weight: float = 10.0

    # PWDF floor — penalize only if PWDF drops below this (= clustering
    # got destroyed). No penalty / no bonus above floor.
    pwdf_min: float = 1.5
    pwdf_floor_weight: float = 5.0


@dataclass
class ExperienceCostBreakdown:
    total: float
    nm_cost: float
    pwdf_cost: float
    blank_adj_bonus: float
    near_miss_rate_total: float
    avg_pwdf: float
    avg_blank_adj: float
    # Number of Blank-Blank or non-Blank-non-Blank circular-adjacencies
    # across all reels. Hard invariant = 0 post-SA (enforced by
    # class-preserving mutation, not by cost penalty).
    alternation_violations: int = 0


def count_alternation_violations(
    reel: list[dict],
    blank_symbol: str = "Blank",
) -> int:
    """Count circular-adjacency violations on a single reel.

    A violation is any pair of consecutive stops (wrapping from last →
    first) where both are Blank or both are non-Blank. Returns the
    total count.

    Post-SA invariant: this MUST be 0 on every reel (see the class-
    preserving swap mutation). If not 0 after SA, caller should treat
    it as a bug in the mutation operator, not a cost-landscape issue.
    """
    n = len(reel)
    if n < 2:
        return 0
    violations = 0
    for i in range(n):
        a = reel[i]["symbol"] == blank_symbol
        b = reel[(i + 1) % n]["symbol"] == blank_symbol
        if a == b:
            violations += 1
    return violations


def initialize_alternating(
    reel: list[dict],
    blank_symbol: str = "Blank",
) -> list[dict]:
    """Rearrange a reel's stops so Blank and non-Blank strictly alternate.

    Requires ``count(Blank) == count(non-Blank)`` (which is the case
    for M1's 36-stop reels: 18 Blanks + 18 non-Blanks). For machines
    where this doesn't hold, alternation is not achievable — the
    caller must rebalance counts at Phase 4 first.

    Stops' original order within each class (Blank, non-Blank) is
    preserved — we're just interleaving the two sequences. This
    matters because different Blank stops carry different weights;
    SA's class-preserving swap then freely permutes them within the
    odd/even position subset.
    """
    blanks = [s for s in reel if s["symbol"] == blank_symbol]
    nonblanks = [s for s in reel if s["symbol"] != blank_symbol]
    if len(blanks) != len(nonblanks):
        raise ValueError(
            f"strict alternation requires count(Blank) == count(non-Blank); "
            f"got {len(blanks)} Blank vs {len(nonblanks)} non-Blank on this reel. "
            f"Rebalance counts at Phase 4 (or drop the alternation rule for "
            f"this machine) before re-running Phase 5."
        )
    result: list[dict] = []
    for b, n in zip(blanks, nonblanks):
        result.append(b)
        result.append(n)
    return result


def evaluate_experience_cost(
    reels: list[list[dict]],
    *,
    high_value: Iterable[str] = ("Seven1", "Seven2", "Diamond1", "Diamond2"),
    blank_symbol: str = "Blank",
    weights: ExperienceCostWeights | None = None,
) -> ExperienceCostBreakdown:
    w = weights or ExperienceCostWeights()
    hv = list(high_value)

    # ── Near-miss band penalty ──
    nm_total = sum(near_miss_rate_2_of_3(reels, s) for s in hv)
    if nm_total < w.nm_min:
        nm_cost = w.nm_band_weight * (w.nm_min - nm_total) ** 2
    elif nm_total > w.nm_max:
        nm_cost = w.nm_band_weight * (nm_total - w.nm_max) ** 2
    else:
        nm_cost = 0.0

    # ── PWDF (avg across reels+symbols) — penalize only below floor ──
    pwdf_sum = 0.0
    pwdf_count = 0
    for r in reels:
        for s in hv:
            mid_p = symbol_mid_probability(r, s)
            if mid_p <= 0:
                continue
            win_p = symbol_window_probability(r, s)
            pwdf_sum += win_p / mid_p
            pwdf_count += 1
    avg_pwdf = pwdf_sum / max(1, pwdf_count)
    if avg_pwdf < w.pwdf_min:
        pwdf_cost = w.pwdf_floor_weight * (w.pwdf_min - avg_pwdf) ** 2
    else:
        pwdf_cost = 0.0

    # ── Blank-adjacency bonus (linear up to cap) ──
    blank_adj = sum(reel_blank_adjacency_score(r, hv, blank_symbol) for r in reels) / len(reels)
    blank_adj_bonus = -w.blank_adj_bonus_weight * min(blank_adj, w.blank_adj_cap)

    # ── Alternation violations (invariant, not a cost component) ──
    violations = sum(count_alternation_violations(r, blank_symbol) for r in reels)

    total = nm_cost + pwdf_cost + blank_adj_bonus
    return ExperienceCostBreakdown(
        total=total,
        nm_cost=nm_cost,
        pwdf_cost=pwdf_cost,
        blank_adj_bonus=blank_adj_bonus,
        near_miss_rate_total=nm_total,
        avg_pwdf=avg_pwdf,
        avg_blank_adj=blank_adj,
        alternation_violations=violations,
    )


def swap_two_stops(reel: list[dict], i: int, j: int) -> list[dict]:
    """Return a new reel list with stops at i and j swapped (not in-place)."""
    new = list(reel)
    new[i], new[j] = new[j], new[i]
    return new


def random_swap_mutation(reels: list[list[dict]], rng: Random) -> list[list[dict]]:
    """Pick a reel and swap two random stops within it. Preserves counts
    but may break Blank/non-Blank alternation — use only when alternation
    isn't a hard invariant (e.g. machines where the rule doesn't apply
    or the counts can't strictly alternate).
    """
    new_reels = [list(r) for r in reels]
    reel_idx = rng.randrange(len(new_reels))
    n = len(new_reels[reel_idx])
    if n < 2:
        return new_reels
    i, j = rng.sample(range(n), 2)
    new_reels[reel_idx][i], new_reels[reel_idx][j] = (
        new_reels[reel_idx][j],
        new_reels[reel_idx][i],
    )
    return new_reels


def class_preserving_swap_mutation(
    reels: list[list[dict]],
    rng: Random,
    blank_symbol: str = "Blank",
) -> list[list[dict]]:
    """Swap two stops of the same Blank/non-Blank class within a random reel.

    Preserves two invariants simultaneously:
      1. Per-(symbol, reel) counts — because we don't change which
         symbols appear, only their positions.
      2. Blank/non-Blank alternation — because Blanks only ever
         exchange places with Blanks, and non-Blanks with non-Blanks.
         If the input was strictly alternating, the output is too.

    Starting a reel at a strictly-alternating arrangement via
    ``initialize_alternating`` and then running SA with this mutation
    means alternation is preserved FOR FREE — no cost penalty needed,
    no chance of random drift away from the invariant. The remaining
    combinatorial freedom (18! within-class permutations per reel for
    M1) is plenty for near-miss / PWDF optimization.
    """
    new_reels = [list(r) for r in reels]
    reel_idx = rng.randrange(len(new_reels))
    reel = new_reels[reel_idx]
    blank_idxs = [i for i, s in enumerate(reel) if s["symbol"] == blank_symbol]
    nonblank_idxs = [i for i, s in enumerate(reel) if s["symbol"] != blank_symbol]
    # Pick a class with ≥2 members — if the reel is single-class
    # (pathological: all Blank or all non-Blank), silently no-op.
    candidates: list[int] = []
    if len(blank_idxs) >= 2 and (len(nonblank_idxs) < 2 or rng.random() < 0.5):
        candidates = blank_idxs
    elif len(nonblank_idxs) >= 2:
        candidates = nonblank_idxs
    if len(candidates) < 2:
        return new_reels
    i, j = rng.sample(candidates, 2)
    reel[i], reel[j] = reel[j], reel[i]
    return new_reels


@dataclass
class SAConfig:
    max_steps: int = 5000
    initial_temp: float = 1.0
    final_temp: float = 0.001
    # Temperature cooling schedule: geometric from initial to final over max_steps


@dataclass
class SAResult:
    best_reels: list[list[dict]]
    best_cost: float
    best_breakdown: ExperienceCostBreakdown
    evaluations: int
    trace: list[dict] = field(default_factory=list)


def run_simulated_annealing(
    initial_reels: list[list[dict]],
    cost_fn: Callable[[list[list[dict]]], tuple[float, ExperienceCostBreakdown]],
    *,
    config: SAConfig | None = None,
    rng: Random | None = None,
    verbose: bool = False,
    enforce_alternation: bool = True,
    blank_symbol: str = "Blank",
) -> SAResult:
    """Simulated annealing over stop order.

    When ``enforce_alternation`` is True (default), the input reels MUST
    already be strictly Blank/non-Blank alternating (call
    ``initialize_alternating`` on each reel first). The SA uses the
    class-preserving swap mutation, which preserves that invariant at
    every step — no cost penalty needed.

    When False, uses the unconstrained swap mutation; callers opt out
    for machines where alternation isn't feasible (count mismatch) or
    desired.
    """
    cfg = config or SAConfig()
    rng = rng or Random(0)

    # Deep copy so caller's reels stay untouched
    current = [list(r) for r in initial_reels]

    if enforce_alternation:
        # Fail loud if the caller passed non-alternating reels — that
        # indicates a wiring bug (missing initialize_alternating call)
        # rather than a cost-landscape issue; silently "fixing" by
        # rearranging would invalidate the cost comparison.
        initial_violations = sum(
            count_alternation_violations(r, blank_symbol) for r in current
        )
        if initial_violations != 0:
            raise ValueError(
                f"enforce_alternation=True but initial reels have "
                f"{initial_violations} adjacency violations. Call "
                f"initialize_alternating(reel) on each reel before SA, "
                f"or pass enforce_alternation=False to allow unconstrained "
                f"mutation."
            )
        mutate = lambda rs, r: class_preserving_swap_mutation(rs, r, blank_symbol)
    else:
        mutate = lambda rs, r: random_swap_mutation(rs, r)

    current_cost, current_break = cost_fn(current)
    best = [list(r) for r in current]
    best_cost = current_cost
    best_break = current_break

    # Geometric cooling
    alpha = (cfg.final_temp / cfg.initial_temp) ** (1.0 / max(1, cfg.max_steps))
    temp = cfg.initial_temp

    trace = []
    accepted = 0
    improved = 0

    for step in range(1, cfg.max_steps + 1):
        candidate = mutate(current, rng)
        cand_cost, cand_break = cost_fn(candidate)
        delta = cand_cost - current_cost

        if delta < 0 or rng.random() < math.exp(-delta / max(temp, 1e-12)):
            current = candidate
            current_cost = cand_cost
            current_break = cand_break
            accepted += 1
            if current_cost < best_cost:
                best = [list(r) for r in current]
                best_cost = current_cost
                best_break = current_break
                improved += 1
                if verbose and (step <= 5 or step % 200 == 0):
                    print(f"  SA step {step:>5} temp={temp:.4f} "
                          f"cost={best_cost:+.4f} nm={best_break.near_miss_rate_total*100:.3f}% "
                          f"pwdf={best_break.avg_pwdf:.3f} blank_adj={best_break.avg_blank_adj:.3f} *")

        temp *= alpha
        trace.append({
            "step": step, "temp": temp, "cost": current_cost,
            "best_cost": best_cost, "nm": current_break.near_miss_rate_total,
        })

    if verbose:
        print(f"  SA done: {accepted}/{cfg.max_steps} accepted, {improved} improvements")

    # Post-SA invariant: if alternation was enforced, violations == 0
    if enforce_alternation:
        final_violations = sum(
            count_alternation_violations(r, blank_symbol) for r in best
        )
        assert final_violations == 0, (
            f"Phase 5 SA bug: class-preserving swap should keep "
            f"alternation, but result has {final_violations} violations. "
            f"Check class_preserving_swap_mutation for correctness."
        )

    return SAResult(
        best_reels=best,
        best_cost=best_cost,
        best_breakdown=best_break,
        evaluations=cfg.max_steps,
        trace=trace,
    )
