"""Collect meter — M279 per-robot persistent state.

Spec: every paid spin (ST=140) increments meter by 1; at ``max`` (1000
default), trigger the Wheel feature and reset to (acc_credits=100,
collect_count=1) to mirror upstream rawdata semantics where the next
paid spin shows the meter already counting from the post-reset state.

Spec field naming follows the production cfg's mapCollection block:
  - CollectMax       → ``max``
  - CollectRatio     → unused at runtime (UI-only formatting field)
  - CollectRatioDivisor → unused at runtime
  - SingleCollectCount → ``increment_per_paid_spin``

The "AccCredits" field in rawdata = collect_count × 100 (= the credit
unit). We store ``acc_credits`` and ``collect_count`` separately even
though they're 1:1 derivable, because the production rawdata writes
both fields and the analyzer reads ``AccCredits`` directly.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CollectConfig:
    """Loaded from spec _m279_features.collect_meter block."""
    max: int = 1000
    increment_per_paid_spin: int = 1
    credit_unit: int = 100  # acc_credits per increment


@dataclass
class CollectMeter:
    """Per-robot mutable state. One instance per robot per chunk."""
    acc_credits: int = 0
    collect_count: int = 0

    def increment(self, cfg: CollectConfig) -> None:
        """Apply one paid-spin increment. Caller checks should_trigger()
        AFTER calling this (matches rawdata: meter shows post-increment
        value on the trigger spin's paid round).
        """
        self.collect_count += cfg.increment_per_paid_spin
        self.acc_credits += cfg.increment_per_paid_spin * cfg.credit_unit

    def should_trigger(self, cfg: CollectConfig) -> bool:
        return self.collect_count >= cfg.max

    def reset_post_trigger(self, cfg: CollectConfig) -> None:
        """After Wheel fires, the next paid spin's meter shows
        (acc_credits=100, collect_count=1) — i.e., that next spin's
        increment already applied to a fresh meter. We model this by
        snapping to the post-increment state directly.
        """
        self.collect_count = cfg.increment_per_paid_spin
        self.acc_credits = cfg.increment_per_paid_spin * cfg.credit_unit


def load_collect_config(spec: dict) -> CollectConfig:
    """Parse the collect_meter block out of an M279 spec dict.

    Returns default CollectConfig when block is absent (lets a
    machine-without-collect spec still load, though M279 always has
    one).
    """
    block = (spec.get("_m279_features") or {}).get("collect_meter") or {}
    return CollectConfig(
        max=int(block.get("max", 1000)),
        increment_per_paid_spin=int(block.get("increment_per_paid_spin", 1)),
        credit_unit=int(block.get("_collect_credit_unit", 100)),
    )
