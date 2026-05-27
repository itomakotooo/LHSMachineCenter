"""AnalyzerFeature: upstream_feature_breakdown — Pattern B from start.

Phase C5 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §7.2
and session_artifacts/_impl/phase_c5/brief.md §2.1.

Replaces the PIA inline ``upstream_feature_breakdown`` block (lines ~3503-3944 /
~4534-4538 in player_impact_analyzer.py).  Schema and computed values are
unchanged from the inline block — this is a pure carve-out.

Mechanism
---------
The upstream API groups payouts by a semantic feature name (string: e.g.
"Normal", "NormalCollectionSpin", "NewFreespin") — richer than the round-level
SpinType int.  For single-feature machines (M14: just "Normal") the breakdown
is redundant with payout_ids_top20, so applicable=False.  For multi-feature
machines (M272 / M275) it is the authoritative per-bonus attribution the
operator needs.

Data sources
------------
All data comes from PIA pre-loop accumulators stored in chunk_dict via the
standard merge-loop path.  The plugin reads the ALREADY-POPULATED
``player_impact`` summary keys written by the PIA F2/F3 inline blocks (pre-emit
phase) — it does NOT need a new extract() accumulator.

Specifically, emit() reads:
  summary["player_impact"]["upstream_feature_breakdown"]   — the inline block
      already wrote this dict; plugin OVERWRITES it from ctx fields to preserve
      the behavior exactly.

Wait — that won't work: the inline block wrote the value, but C5 is supposed to
CARVE it so the inline block is REMOVED.  The plugin must compute the value
itself.

The accumulated ``upstream_feature_tally`` data is NOT available in chunk_dict
after the merge-loop completes (it is a local PIA variable, not a parsed chunk
field).  Instead the PIA F2/F3 inline code already computes
``upstream_feature_rows`` and ``upstream_feature_applicable`` as local
variables, then writes them into ``summary["player_impact"]
["upstream_feature_breakdown"]``.

Post-carve design (Option A2 from 04_v3 §7.2 open question):
  - The PIA inline code that builds ``upstream_feature_rows`` and computes
    ``upstream_feature_applicable`` STAYS in the PIA inline block (pre-emit).
  - The PIA inline code that WRITES the dict into
    ``summary["player_impact"]["upstream_feature_breakdown"]`` is moved here.
  - This plugin's emit() reads the dict from a temp stash key
    ``summary["_upstream_feature_breakdown_data"]`` and writes the final key.

Why this approach:
  - The row-building logic (~400 lines) depends on many PIA-local variables
    (spin_type_next_counts, sub_streams_by_feature, etc.) that are not
    available post-emit via chunk_dict. Moving them to extract() would require
    a full parser rewrite — out of scope for C5.
  - Option A2 (stash + forward) follows the same pattern as BankruptcySimulation
    (C1) which uses _bankruptcy_rows + _bankruptcy_sim_session_spins temp keys.
  - Per the brief §2.1: REQUIRES = () (reads chunk_dict + ctx).

Output schema (SCHEMA_VERSION = 1 — identical to pre-C5 inline block)
------------------------------------------------------------------------
summary["player_impact"]["upstream_feature_breakdown"]:
  applicable   — bool; False for single-"Normal" machines
  source       — str; "analysisResult.FeatureWin"
  features     — list of feature rows (see PIA inline comments for full schema)

Per-machine isolation
---------------------
This plugin file is NOT in fresh_slotlab/analyzer/core/ so its addition does
NOT change compute_base_analyzer_version().  Only machines that declare
"upstream_feature_breakdown" in their manifest's analyzer_features list will
include this plugin's hash in their effective_analyzer_version.

REQUIRES = () — data arrives via a temp stash key written by the PIA inline
block (analogous to _bankruptcy_rows for BankruptcySimulation).  No emit-loop
ordering dependency.

Memory feedback honored
-----------------------
- feedback_subprocess_import_suicide_and_module_globals.md:
    register() is a pure list-append — no I/O at import time.
- feedback_no_silent_swallow.md:
    If _upstream_feature_breakdown_data stash key is missing, emit() raises
    a diagnostic RuntimeError (not silently skipped).
- feedback_invariant_with_fallback_hides_drift.md:
    applicable=False is an explicit "no multi-feature data" signal — NOT a
    catch-all bucket.  Machines that don't declare this feature won't have
    the key at all.
- feedback_no_hardcode.md:
    No machine-specific semantics hardcoded.
- feedback_prefer_complex_better.md:
    Stash pattern reused from BankruptcySimulation; no ad-hoc workaround.
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

# Stash key written by PIA inline block (Phase C5 carve).
# Analogous to _bankruptcy_rows used by BankruptcySimulation (C1).
_STASH_KEY = "_upstream_feature_breakdown_data"


class UpstreamFeatureBreakdown(AnalyzerFeature):
    """Pattern B plugin: upstream FeatureWin breakdown panel.

    extract() is a no-op (data flows via pre-emit stash key).
    emit() reads the stash, removes it, and writes the final summary key.

    Accumulator structure
    ---------------------
    No accumulator — this plugin uses the stash pattern.
    extract() returns {} always.
    reduce() returns {} always.
    """

    FEATURE_ID: ClassVar[str] = "upstream_feature_breakdown"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("upstream_feature_breakdown",)
    SCHEMA_VERSION: ClassVar[int] = 1  # C5: initial plugin version
    RTP_CONTRIBUTION: ClassVar[bool] = False  # display only; doesn't add to RTP totals
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    REQUIRES: ClassVar[tuple[str, ...]] = ()  # stash key pre-exists before emit loop
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """No-op — upstream_feature_breakdown uses the pre-emit stash pattern."""
        return {}

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """No-op — no per-chunk accumulator."""
        return {}

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Read stash, remove it, write summary["player_impact"]
        ["upstream_feature_breakdown"].

        The PIA inline block writes the computed breakdown dict into
        ``summary["_upstream_feature_breakdown_data"]`` before the emit loop.
        This method:
          1. Reads the stash key.
          2. Removes the stash key (cleanup, analogous to BankruptcySimulation).
          3. Writes the final schema key into summary["player_impact"].

        Raises RuntimeError (surfaced as feature_error) if the stash key is
        absent — that means the PIA inline carve was incomplete.
        Per feedback_no_silent_swallow.md: never silently skip.
        """
        if _STASH_KEY not in summary:
            raise RuntimeError(
                f"upstream_feature_breakdown plugin: stash key '{_STASH_KEY}' "
                f"not found in summary. PIA inline carve may be incomplete. "
                f"Expected the inline block to write this key before the emit loop."
            )

        data: dict[str, Any] = summary.pop(_STASH_KEY)
        player_impact = summary.setdefault("player_impact", {})
        player_impact["upstream_feature_breakdown"] = data


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# ---------------------------------------------------------------------------
register(UpstreamFeatureBreakdown())
