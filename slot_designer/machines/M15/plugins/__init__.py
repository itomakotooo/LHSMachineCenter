"""M15 plugin package — Top Dollar Feature Play.

Exposes ``build_plugin(spec_dict, weights_doc)`` per the FeaturePlugin
contract (slot_designer/core/engine/feature_protocol.py).
"""
from __future__ import annotations

from .plugin import build_plugin

__all__ = ["build_plugin"]
