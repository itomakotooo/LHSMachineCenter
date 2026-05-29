"""AnalyzerFeature: multiplier_profile — Pattern B plugin that OWNS the compute.

Ticket P2-C §2 / §3 C1-C2 introduced this as a Pattern A *scaffolding* plugin:
extract/reduce were no-ops and emit() merely ASSERTED that main()/PIA had already
populated ``player_impact.multiplier_profile`` inline.

Phase 4 (analyzer honesty/isolation; see
session_artifacts/_arch_honesty_isolation/07_decision.md §5 Phase 3-6 + R-11 and
session_artifacts/_impl/phase_extract_4_multiplier_profile/brief.md) carved the
``multiplier_profile`` dict-BUILD OUT of player_impact_analyzer.py (PIA) and INTO
this plugin's ``emit()`` (mirrors the 2a collect_mechanic / 2b bonus_chain_dynamics
/ 3 upstream_feature_breakdown carves).  Before Phase 4 the plugin was a Pattern-A
scaffolding shell: PIA built the fully-formed dict inline (the
``player_impact.multiplier_profile`` literal — pre-Phase-4 PIA:~3964, NOT the stale
"4329-4337" the old docstring cited; PIA shifted ~390 lines when Phase 3 carved
upstream_feature) and this plugin's emit() only asserted the key's presence.  After
Phase 4:

  - PIA's stash ``summary["_multiplier_profile_data"]`` carries only the RAW inputs
    the dict-build reads (multiplier_bucket_rows, tail_spins_ge10, mb_total_spins,
    tail_rtp_contribution_pp_ge10x, tail_win_share_ge10x — all PIA-local values that
    remain SHARED with other PIA consumers: the volatility.return_bucket_rate panel,
    the quality_label buckets_complete gate, the guideline derived_metrics, and the
    markdown "Multiplier Buckets" section; the carve moves only the DICT-BUILD, not
    those derivations).
  - ``emit()`` re-sources those raw inputs, builds the ``multiplier_profile`` dict
    VERBATIM (key order / float / None-vs-0.0 forms preserved — output byte-identical
    to the pre-carve report), and is the sole writer of
    ``summary["player_impact"]["multiplier_profile"]``.

Why the carve: editing this feature's logic must flip ONLY multiplier_profile's
feature_hash, not ``compute_base_analyzer_version()`` (the fleet-wide base).  PIA
shed the dict-builder, so base shrinks one-time (c89db791d8a1 → new) and this
feature's compute now lives with its own hash.  Report content is byte-identical;
only WHERE the build lives changed.

Stash pattern (Phase 4 — raw inputs; plugin OWNS the build)
-----------------------------------------------------------
The PIA block writes ``summary["_multiplier_profile_data"]`` (stash key) carrying
the 5 RAW inputs the dict-build reads (no compute in the stash). emit() reads the
stash by explicit indexing (fail-loud — no silent ``.get()`` default that would
corrupt report numbers), removes it, BUILDS the dict verbatim, and writes
``summary["player_impact"]["multiplier_profile"]``.

REQUIRES = () — stash key pre-exists before the emit loop (PIA writes it alongside
the other stash keys before the loop starts).
DECLARED_DEPS = ("_multiplier_profile_data",) — the PIA emit-loop Region 2
pre-flight check fires PluginDeclaredDepMissingError (structured analyzer_init_error
on disk) if the stash is absent, instead of a soft RuntimeError inside emit().

Per-machine isolation
---------------------
This plugin file is NOT in fresh_slotlab/analyzer/core/ so its content does NOT
change compute_base_analyzer_version() (R-4 exclusion).  Only machines that declare
"multiplier_profile" in their manifest's analyzer_features list include this
plugin's hash in their effective_analyzer_version.

Memory feedback honored
-----------------------
- feedback_subprocess_import_suicide_and_module_globals.md:
    register() is a pure list-append — no I/O at import time.
- feedback_no_silent_swallow.md:
    If the stash key is missing, OR any of the 5 raw input keys is absent, emit()
    raises a diagnostic RuntimeError (caught by the PIA emit-error handler →
    summary["feature_errors"]["multiplier_profile"] on disk), never a silent default
    that would corrupt the report numbers.
- feedback_no_parallel_panel_impl.md:
    emit() mirrors the sibling carve plugins (collect_mechanic / bonus_chain_dynamics
    / upstream_feature_breakdown) — same stash-read / fail-loud / verbatim-build shape.
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

# Stash key written by the PIA stash builder. Carries the RAW dict-build inputs
# (Phase 4 carve — this plugin builds the dict). Analogous to
# _collect_mechanic_data / _bonus_chain_dynamics_data / _upstream_feature_breakdown_data
# used by the sibling carve plugins.
_STASH_KEY = "_multiplier_profile_data"


class MultiplierProfile(AnalyzerFeature):
    """Pattern B plugin that OWNS the multiplier_profile compute.

    extract() / reduce() are no-ops (data flows via the pre-emit stash key).
    emit() re-sources the 5 raw inputs from the stash, BUILDS the
    ``multiplier_profile`` dict verbatim (Phase 4 carve — byte-identical to the
    pre-carve report), and writes summary["player_impact"]["multiplier_profile"].

    Note: multiplier_profile is nested under player_impact, not at the top-level
    summary dict. The SCHEMA_KEYS value reflects the logical feature identifier;
    the actual key path is summary["player_impact"]["multiplier_profile"].

    Accumulator structure
    ---------------------
    No accumulator — this plugin uses the stash pattern.
    extract() returns {} always.
    reduce() returns {} always.
    """

    FEATURE_ID: ClassVar[str] = "multiplier_profile"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("multiplier_profile",)
    SCHEMA_VERSION: ClassVar[int] = 1  # Phase 4: pure carve; schema unchanged
    RTP_CONTRIBUTION: ClassVar[bool] = False  # display only
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ("_multiplier_profile_data",)
    # Phase 4: DECLARED_DEPS now declares the stash key dependency. The PIA emit
    # loop Region 2 check fires PluginDeclaredDepMissingError (structured
    # analyzer_init_error on disk) if the stash key is absent, instead of a soft
    # RuntimeError inside emit() — mirrors bonus_chain_dynamics (R2 Phase 2 C-4).
    REQUIRES: ClassVar[tuple[str, ...]] = ()  # stash key pre-exists before emit loop

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """No-op — multiplier_profile uses the pre-emit stash pattern."""
        return {}

    def reduce(self, prev_acc: Any, this_acc: Any) -> Any:
        """No-op — no per-chunk accumulator."""
        return {}

    def emit(self, final_acc: Any, summary: dict, ctx: "PipelineContext") -> None:
        """Build multiplier_profile from the raw stash (Phase 4 carve).

        Steps
        -----
        1. Read and remove the stash key written by the PIA stash builder; read the
           5 RAW inputs by explicit indexing (fail-loud — no silent default that
           would corrupt report numbers).
        2. BUILD summary["player_impact"]["multiplier_profile"] verbatim from the
           raw inputs (Phase 4 carve — byte-identical to the pre-carve report).

        Raises RuntimeError (surfaced as feature_error) if:
          - The stash key is absent (per feedback_no_silent_swallow.md)
          - Any of the 5 raw input keys is absent (Phase 4 carve contract;
            per feedback_no_silent_swallow.md — never silently default)
        """
        if _STASH_KEY not in summary:
            raise RuntimeError(
                f"multiplier_profile plugin: stash key '{_STASH_KEY}' not found in "
                f"summary. PIA stash builder (Phase 4 carve) may be incomplete. "
                f"Expected it to write this key before the emit loop."
            )

        stash: dict[str, Any] = summary.pop(_STASH_KEY)

        # ── Read the RAW inputs (Phase 4 carve) ──
        # The PIA stash carries raw inputs only; this plugin OWNS the dict-build
        # (moved verbatim from PIA:~3964). Per feedback_no_silent_swallow.md: each
        # expected raw key is read by explicit indexing so a missing key raises a
        # diagnostic RuntimeError (never a silent default that would corrupt the
        # report numbers).
        _expected_keys = (
            "multiplier_bucket_rows",
            "tail_spins_ge10",
            "mb_total_spins",
            "tail_rtp_contribution_pp_ge10x",
            "tail_win_share_ge10x",
        )
        _missing = [k for k in _expected_keys if k not in stash]
        if _missing:
            raise RuntimeError(
                f"multiplier_profile plugin: stash '{_STASH_KEY}' is missing "
                f"expected raw input key(s) {_missing!r}. The PIA Phase 4 carve "
                f"stash builder must populate every raw input before the emit loop. "
                f"Refusing to silently default (would corrupt report numbers) — "
                f"see feedback_no_silent_swallow.md."
            )

        multiplier_bucket_rows = stash["multiplier_bucket_rows"]
        tail_spins_ge10 = stash["tail_spins_ge10"]
        mb_total_spins = stash["mb_total_spins"]
        tail_rtp_contribution_pp_ge10x = stash["tail_rtp_contribution_pp_ge10x"]
        tail_win_share_ge10x = stash["tail_win_share_ge10x"]

        # ── Build the multiplier_profile dict — moved VERBATIM from PIA:~3964.
        # Key insertion order, float forms, and the `if mb_total_spins > 0 else 0.0`
        # default preserved exactly (the byte-identity contract depends on this
        # being a verbatim move, not a rewrite).
        player_impact = summary.setdefault("player_impact", {})
        player_impact["multiplier_profile"] = {
            "metric": "ret_x = session_win / session_bet (paid bet only)",
            "buckets": multiplier_bucket_rows,
            "tail_spin_rate_ge10x": (
                tail_spins_ge10 / mb_total_spins if mb_total_spins > 0 else 0.0
            ),
            "tail_rtp_contribution_pp_ge10x": tail_rtp_contribution_pp_ge10x,
            "tail_win_share_ge10x": tail_win_share_ge10x,
        }


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per memory feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# ---------------------------------------------------------------------------
register(MultiplierProfile())
