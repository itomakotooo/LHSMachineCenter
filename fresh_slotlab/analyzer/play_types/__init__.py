"""fresh_slotlab.analyzer.play_types — Play-type plugin framework.

Per 04_v2.md §9-rev Phase 1 deliverables 1-8.

This package provides the foundation framework for play-type plugin-based
mechanic detection and accumulation.  No concrete plugins are defined here
(concrete plugins ship in later commits / phases).

Sub-modules
-----------
_base           RoundCtx NamedTuple + MechanicAccumulator ABC (§4.1-rev)
_probe          PreParseProbe ABC (§4.5)
_claim          ClaimSignature dataclass + matches() evaluation (§4.2-rev)
_plugin         PlayTypePlugin base class (§4.5 updated sketch)
_machine_config MachinePlayTypeConfig + JSON read/write + config hash (§6)
_detector       detect_play_types() auto-detection function (§4.6)

Public exports (for callers that do ``from fresh_slotlab.analyzer.play_types import ...``):
    RoundCtx
    MechanicAccumulator
    PreParseProbe
    ClaimSignature
    PlayTypePlugin
    MachinePlayTypeConfig
    detect_play_types

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

# Re-export the public API so callers can do:
#   from fresh_slotlab.analyzer.play_types import RoundCtx, MechanicAccumulator, ...
# without knowing which sub-module each symbol lives in.

try:
    from fresh_slotlab.analyzer.play_types._base import MechanicAccumulator, RoundCtx
    from fresh_slotlab.analyzer.play_types._claim import ClaimSignature
    from fresh_slotlab.analyzer.play_types._detector import detect_play_types
    from fresh_slotlab.analyzer.play_types._machine_config import MachinePlayTypeConfig
    from fresh_slotlab.analyzer.play_types._plugin import PlayTypePlugin
    from fresh_slotlab.analyzer.play_types._probe import PreParseProbe
except ImportError:  # running as standalone script
    from analyzer.play_types._base import MechanicAccumulator, RoundCtx  # type: ignore[no-redef]
    from analyzer.play_types._claim import ClaimSignature  # type: ignore[no-redef]
    from analyzer.play_types._detector import detect_play_types  # type: ignore[no-redef]
    from analyzer.play_types._machine_config import MachinePlayTypeConfig  # type: ignore[no-redef]
    from analyzer.play_types._plugin import PlayTypePlugin  # type: ignore[no-redef]
    from analyzer.play_types._probe import PreParseProbe  # type: ignore[no-redef]

__all__ = [
    "RoundCtx",
    "MechanicAccumulator",
    "PreParseProbe",
    "ClaimSignature",
    "PlayTypePlugin",
    "MachinePlayTypeConfig",
    "detect_play_types",
]
