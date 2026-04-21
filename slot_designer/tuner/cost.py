"""Cost function for weight tuning.

Tiers (per user directive 2026-04-20):
  - HARD: RTP match + bucket shape (normalized, reachable-only)
  - SOFT: CV alignment (Lucas & Singh 2008 — lower CV → longer play;
    aligning CV to target keeps machine-to-machine "feel" similar even
    when per-bucket absolute values differ)
  - EXPERIENCE (logged, not optimized by default): wild_visibility,
    blank_rate, per-pay tail mass — passed through for operator
    inspection via the tuner's best-candidate report

Cost is a scalar; lower = better. Individual components are returned
too for diagnostic logging.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from slot_designer.devtools.shape_distance import shape_distance


@dataclass
class CostWeights:
    # ΔRTP measured in pp. (gap/reference_pp)² — 0.5pp gap = cost 1.
    rtp_reference_pp: float = 0.5
    rtp_weight: float = 1.0
    # Shape distance scaled up; 0.01 JS = cost 1
    shape_scale: float = 100.0
    shape_weight: float = 1.0
    # CV alignment; 0.1 CV gap = cost 1
    cv_reference: float = 0.1
    cv_weight: float = 0.3


@dataclass
class CostBreakdown:
    total: float
    rtp_cost: float
    shape_cost: float
    cv_cost: float
    rtp_gap_pp: float
    shape_js: float
    cv_gap: float


def evaluate_cost(
    predicted: dict,
    target: dict,
    *,
    reachable_buckets: Iterable[str] | None = None,
    weights: CostWeights | None = None,
) -> CostBreakdown:
    """predicted / target are profile dicts with rtp_pct, bucket_rate, cv."""
    w = weights or CostWeights()

    rtp_gap_pp = abs(predicted["rtp_pct"] - target["rtp_pct"])
    rtp_cost = (rtp_gap_pp / w.rtp_reference_pp) ** 2

    sd = shape_distance(
        predicted["bucket_rate"],
        target["bucket_rate"],
        reachable_buckets=reachable_buckets,
    )
    shape_js = sd["js_divergence"]
    shape_cost = shape_js * w.shape_scale

    pred_cv = predicted.get("cv", 0.0)
    # Target CV: std_return_x / (rtp_pct/100). target profile may store both.
    if "cv" in target:
        tgt_cv = target["cv"]
    else:
        tgt_rtp = target.get("rtp_pct", 100.0) / 100.0
        tgt_cv = target.get("std_return_x", 0.0) / tgt_rtp if tgt_rtp > 0 else 0.0
    cv_gap = abs(pred_cv - tgt_cv)
    cv_cost = (cv_gap / w.cv_reference) ** 2

    total = w.rtp_weight * rtp_cost + w.shape_weight * shape_cost + w.cv_weight * cv_cost
    return CostBreakdown(
        total=total,
        rtp_cost=rtp_cost,
        shape_cost=shape_cost,
        cv_cost=cv_cost,
        rtp_gap_pp=rtp_gap_pp,
        shape_js=shape_js,
        cv_gap=cv_gap,
    )
