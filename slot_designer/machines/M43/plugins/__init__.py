"""M43 plugin package — post-win Respin + post-spin MiniGame.

Exposes ``build_plugin(spec_dict, weights_doc)`` per the FeaturePlugin
contract (slot_designer/core/engine/feature_protocol.py).

M43 is an **outcome-conditional** plugin (``trigger_pay_id is None``),
meaning ``SpinEngine.spin_session`` invokes ``simulate_session(rng,
outcome=...)`` after every paid spin and the plugin decides itself
whether to fire respin / mini-game (post-win and post-spin
probabilities, respectively). See feature.py for full mechanism notes.
"""
from __future__ import annotations

from .feature import build_plugin

__all__ = ["build_plugin"]
