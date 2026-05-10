"""Cost function for weight tuning.

Tiers (per user directive 2026-04-20 + 2026-04-21 hit_rate soft add):
  - HARD: RTP match + bucket shape (normalized, reachable-only)
  - SOFT: CV alignment (Lucas & Singh 2008 — lower CV → longer play;
    aligning CV to target keeps machine-to-machine "feel" similar even
    when per-bucket absolute values differ)
  - SOFT (optional): hit_rate target band. Off by default (target
    profile's hit_rate is informational, not a tuning goal). When the
    operator knows a specific fleet-preferred hit rate (e.g. classic
    single-line 9-13% industry range) they pass --hit-target to
    steer the tuner there. The target profile's hit_rate is ignored
    in this mode; we don't want to track M14's 20.85% just because
    it happens to be the shape reference.
  - EXPERIENCE (logged, not optimized by default): wild_visibility,
    blank_rate, per-pay tail mass — passed through for operator
    inspection via the tuner's best-candidate report

Cost is a scalar; lower = better. Individual components are returned
too for diagnostic logging.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from slot_designer.core.devtools.shape_distance import shape_distance


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
    # hit_rate target (fraction, 0-1). None = don't optimize for hit_rate.
    # When set (e.g. 0.15 for classic single-line typical), adds a
    # quadratic penalty on (predicted_hit - target) scaled by
    # hit_reference (0.01 gap = cost 1 at hit_weight=1).
    hit_target: float | None = None
    hit_reference: float = 0.01
    hit_weight: float = 0.5


@dataclass
class CostBreakdown:
    total: float
    rtp_cost: float
    shape_cost: float
    cv_cost: float
    hit_cost: float
    rtp_gap_pp: float
    shape_js: float
    cv_gap: float
    hit_gap: float


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

    # hit_rate soft target (optional — only active when hit_target set)
    hit_cost = 0.0
    hit_gap = 0.0
    if w.hit_target is not None:
        pred_hit = predicted.get("hit_rate", 0.0)
        hit_gap = abs(pred_hit - w.hit_target)
        hit_cost = (hit_gap / w.hit_reference) ** 2

    total = (
        w.rtp_weight * rtp_cost
        + w.shape_weight * shape_cost
        + w.cv_weight * cv_cost
        + w.hit_weight * hit_cost
    )
    return CostBreakdown(
        total=total,
        rtp_cost=rtp_cost,
        shape_cost=shape_cost,
        cv_cost=cv_cost,
        hit_cost=hit_cost,
        rtp_gap_pp=rtp_gap_pp,
        shape_js=shape_js,
        cv_gap=cv_gap,
        hit_gap=hit_gap,
    )
