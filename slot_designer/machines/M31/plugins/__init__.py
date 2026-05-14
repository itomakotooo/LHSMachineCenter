"""M31 plugin package — 5-payline multiplier wild + FreeSpin feature.

Exposes ``build_plugin(spec_dict, weights_doc)`` per the FeaturePlugin
contract (slot_designer/core/engine/feature_protocol.py).

M31 is a scatter-pay-triggered plugin (``trigger_pay_id=666``):
  - SpinEngine.spin_session fires after a paid ST=43 spin when pay_id 666
    is present in scatter_pays (3 Scatter symbols anywhere in grid).
  - Plugin emits 7 ST=44 FreeSpin rounds from the freespin reel set.

Architecture: Option B (FeaturePlugin).
Multi-payline + FreeSpin reel-set switch handled here; core engine unchanged.
"""
from __future__ import annotations

from .feature import build_plugin

__all__ = ["build_plugin"]
