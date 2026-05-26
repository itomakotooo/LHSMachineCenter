"""AnalyzerFeature: reel_marginal_by_spin_type — Pattern A (scaffolding).

Ticket P2-C §2 / §3 C1-C2.
Pattern A: extract/reduce are no-ops; main() builds the dict inline.
Wave 2d will promote this to Pattern B (per-round extraction).

Summary schema key: ``reel_marginal_by_spin_type`` (already set by main()).

Per memory feedback_subprocess_import_suicide_and_module_globals.md:
  register() is a pure list-append — no I/O at import time.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    from fresh_slotlab.analyzer.feature_registry import register
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    from analyzer.feature_registry import register  # type: ignore[no-redef]

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
    except ImportError:
        from analyzer.pipeline_context import PipelineContext  # type: ignore[assignment]


class ReelMarginalBySpinType(AnalyzerFeature):
    """Scaffolding feature for reel_marginal_by_spin_type summary key.

    Per ticket P2-C §2 Pattern A:
      - extract/reduce are no-ops; aggregation owned by main() for now.
      - emit is a no-op verification: assert the key is present.

    Wave 2d will move the actual aggregation here.
    """

    FEATURE_ID: ClassVar[str] = "reel_marginal_by_spin_type"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("reel_marginal_by_spin_type",)
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False  # display only
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        # No per-round work; aggregation owned by main() for now.
        # Wave 2d will move the per-round extraction here.
        return {}

    def reduce(self, prev_acc: Any, this_acc: Any) -> Any:
        # No-op accumulator; main() owns the accumulation.
        return prev_acc

    def emit(self, final_acc: Any, summary: dict, ctx: "PipelineContext") -> None:
        # main() already populated summary["player_impact"]["reel_marginal_by_spin_type"]
        # inline (player_impact_analyzer.py line 4383).
        # This emit is a no-op verification: assert the key is present.
        # Wave 2d will move the actual aggregation here.
        player_impact = summary.get("player_impact") or {}
        assert "reel_marginal_by_spin_type" in player_impact, (
            "player_impact.reel_marginal_by_spin_type key missing from summary — "
            "main() must populate it before invoking feature.emit(). "
            "Ticket P2-C §4 C4."
        )


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per ticket P2-C §4 C2: duplicate registration is a silent no-op.
# ---------------------------------------------------------------------------
register(ReelMarginalBySpinType())
