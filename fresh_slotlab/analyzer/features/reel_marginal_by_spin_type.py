"""AnalyzerFeature: reel_marginal_by_spin_type — Pattern B plugin that OWNS the build.

Ticket P2-C §2 / §3 C1-C2 introduced this as a Pattern A *scaffolding* plugin:
extract/reduce were no-ops and emit() merely ASSERTED that main()/PIA had already
populated ``player_impact.reel_marginal_by_spin_type`` inline.

Phase 5 (analyzer honesty/isolation; see
session_artifacts/_arch_honesty_isolation/07_decision.md §5 Phase 3-6 + R-11 and
session_artifacts/_impl/phase_extract_5_reel_marginal/brief.md) carved the
``reel_marginal_by_spin_type`` dict-BUILD OUT of player_impact_analyzer.py (PIA) and
INTO this plugin's ``emit()`` (mirrors the 2a collect_mechanic / 2b
bonus_chain_dynamics / 3 upstream_feature_breakdown / 4 multiplier_profile carves).
Before Phase 5 the plugin was a Pattern-A scaffolding shell: PIA built the
fully-formed dict inline (the ``for st_int, label in sorted(_st_label.items())``
loop — pre-Phase-5 PIA:~3432, NOT the stale "line 4383" the old docstring cited;
PIA shifted across Phases 3-4) and this plugin's emit() only asserted the key's
presence.  After Phase 5:

  - PIA's stash ``summary["_reel_marginal_by_spin_type_data"]`` carries only the
    single RAW accumulator the build reads
    (``symbol_counts_by_col_by_spin_type_total`` — the per-ST per-column symbol
    counts, a PIA-local accumulator that after this carve has NO other consumer
    in PIA; it fed only this build).
  - ``emit()`` RE-DERIVES the ``{spin_type → "ST{N}_{behavior_name}"}`` label map
    from ``summary["player_impact"]["spin_type_breakdown"]`` (the rows F1 wrote —
    exactly as ``PayoutsBySpinType.emit()`` already does; this is the SHARED source
    of truth, NOT duplicated), builds the ``reel_marginal_by_spin_type`` dict
    VERBATIM (sort order / int(count) / ``prob_pct = (cnt/total)*100`` forms
    preserved — output byte-identical to the pre-carve report), and is the sole
    writer of ``summary["player_impact"]["reel_marginal_by_spin_type"]``.

Why the carve: editing this feature's logic must flip ONLY
reel_marginal_by_spin_type's feature_hash, not ``compute_base_analyzer_version()``
(the fleet-wide base).  PIA shed the dict-builder, so base shrinks one-time and this
feature's compute now lives with its own hash.  Report content is byte-identical;
only WHERE the build lives changed.

Stash pattern (Phase 5 — raw accumulator; plugin OWNS the build)
----------------------------------------------------------------
The PIA block writes ``summary["_reel_marginal_by_spin_type_data"]`` (stash key)
carrying the 1 RAW accumulator the dict-build reads (no compute in the stash).
emit() reads the stash by explicit indexing (fail-loud — no silent ``.get()``
default that would corrupt report numbers), removes it, re-derives the label map
from the already-emitted spin_type_breakdown, BUILDS the dict verbatim, and writes
``summary["player_impact"]["reel_marginal_by_spin_type"]``.

REQUIRES = () — the stash key pre-exists before the emit loop (PIA writes it
alongside the other stash keys before the loop starts).
DECLARED_DEPS = ("_reel_marginal_by_spin_type_data",) — the PIA emit-loop Region 2
pre-flight check fires PluginDeclaredDepMissingError (structured analyzer_init_error
on disk) if the stash is absent, instead of a soft RuntimeError inside emit()
(mirrors multiplier_profile Phase 4 / bonus_chain_dynamics R2 Phase 2 C-4).

Per-machine isolation
---------------------
This plugin file is NOT in fresh_slotlab/analyzer/core/ so its content does NOT
change compute_base_analyzer_version() (R-4 exclusion).  Only machines that declare
"reel_marginal_by_spin_type" in their manifest's analyzer_features list include this
plugin's hash in their effective_analyzer_version.

Memory feedback honored
-----------------------
- feedback_subprocess_import_suicide_and_module_globals.md:
    register() is a pure list-append — no I/O at import time.
- feedback_no_silent_swallow.md:
    If the stash key is missing, OR the raw accumulator key is absent, emit() raises
    a diagnostic RuntimeError (caught by the PIA emit-error handler →
    summary["feature_errors"]["reel_marginal_by_spin_type"] on disk), never a silent
    default that would corrupt the report numbers.
- feedback_no_parallel_panel_impl.md:
    emit() mirrors the sibling carve plugins (collect_mechanic / bonus_chain_dynamics
    / upstream_feature_breakdown / multiplier_profile) — same stash-read / fail-loud /
    verbatim-build shape — and re-derives _st_label with the SAME comprehension
    PayoutsBySpinType.emit() uses (no parallel/divergent derivation).
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

# Stash key written by the PIA stash builder. Carries the RAW dict-build input
# (Phase 5 carve — this plugin builds the dict). Analogous to
# _multiplier_profile_data / _upstream_feature_breakdown_data / _collect_mechanic_data
# used by the sibling carve plugins.
_STASH_KEY = "_reel_marginal_by_spin_type_data"


class ReelMarginalBySpinType(AnalyzerFeature):
    """Pattern B plugin that OWNS the reel_marginal_by_spin_type build.

    extract() / reduce() are no-ops (data flows via the pre-emit stash key).
    emit() re-sources the raw per-ST symbol-count accumulator from the stash,
    re-derives the SpinType label map from the already-emitted spin_type_breakdown,
    BUILDS the ``reel_marginal_by_spin_type`` dict verbatim (Phase 5 carve —
    byte-identical to the pre-carve report), and writes
    summary["player_impact"]["reel_marginal_by_spin_type"].

    Note: reel_marginal_by_spin_type is nested under player_impact, not at the
    top-level summary dict. The SCHEMA_KEYS value reflects the logical feature
    identifier; the actual key path is
    summary["player_impact"]["reel_marginal_by_spin_type"].

    Accumulator structure
    ---------------------
    No accumulator — this plugin uses the stash pattern.
    extract() returns {} always.
    reduce() returns {} always.
    """

    FEATURE_ID: ClassVar[str] = "reel_marginal_by_spin_type"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("reel_marginal_by_spin_type",)
    SCHEMA_VERSION: ClassVar[int] = 1  # Phase 5: pure carve; schema unchanged
    RTP_CONTRIBUTION: ClassVar[bool] = False  # display only
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ("_reel_marginal_by_spin_type_data",)
    # Phase 5: DECLARED_DEPS now declares the stash key dependency. The PIA emit
    # loop Region 2 check fires PluginDeclaredDepMissingError (structured
    # analyzer_init_error on disk) if the stash key is absent, instead of a soft
    # RuntimeError inside emit() — mirrors multiplier_profile (Phase 4) /
    # bonus_chain_dynamics (R2 Phase 2 C-4).
    REQUIRES: ClassVar[tuple[str, ...]] = ()  # stash key pre-exists before emit loop

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """No-op — reel_marginal_by_spin_type uses the pre-emit stash pattern."""
        return {}

    def reduce(self, prev_acc: Any, this_acc: Any) -> Any:
        """No-op — no per-chunk accumulator."""
        return {}

    def emit(self, final_acc: Any, summary: dict, ctx: "PipelineContext") -> None:
        """Build reel_marginal_by_spin_type from the raw stash (Phase 5 carve).

        Steps
        -----
        1. Read and remove the stash key written by the PIA stash builder; read the
           single RAW accumulator by explicit indexing (fail-loud — no silent
           default that would corrupt report numbers).
        2. Re-derive the SpinType label map from the already-emitted
           spin_type_breakdown rows (same comprehension as PayoutsBySpinType.emit()).
        3. BUILD summary["player_impact"]["reel_marginal_by_spin_type"] verbatim from
           the raw accumulator (Phase 5 carve — byte-identical to the pre-carve
           report).

        Raises RuntimeError (surfaced as feature_error) if:
          - The stash key is absent (per feedback_no_silent_swallow.md)
          - The raw accumulator key is absent (Phase 5 carve contract;
            per feedback_no_silent_swallow.md — never silently default)
        """
        if _STASH_KEY not in summary:
            raise RuntimeError(
                f"reel_marginal_by_spin_type plugin: stash key '{_STASH_KEY}' not "
                f"found in summary. PIA stash builder (Phase 5 carve) may be "
                f"incomplete. Expected it to write this key before the emit loop."
            )

        stash: dict[str, Any] = summary.pop(_STASH_KEY)

        # ── Read the RAW accumulator (Phase 5 carve) ──
        # The PIA stash carries the raw per-ST per-column symbol-count accumulator
        # only; this plugin OWNS the dict-build (moved verbatim from PIA:~3432).
        # Per feedback_no_silent_swallow.md: the expected raw key is read by
        # explicit indexing so a missing key raises a diagnostic RuntimeError
        # (never a silent default that would corrupt the report numbers).
        _expected_keys = ("symbol_counts_by_col_by_spin_type_total",)
        _missing = [k for k in _expected_keys if k not in stash]
        if _missing:
            raise RuntimeError(
                f"reel_marginal_by_spin_type plugin: stash '{_STASH_KEY}' is missing "
                f"expected raw input key(s) {_missing!r}. The PIA Phase 5 carve "
                f"stash builder must populate every raw input before the emit loop. "
                f"Refusing to silently default (would corrupt report numbers) — "
                f"see feedback_no_silent_swallow.md."
            )

        symbol_counts_by_col_by_spin_type_total = stash[
            "symbol_counts_by_col_by_spin_type_total"
        ]

        # ── Re-derive the SpinType label map from spin_type_breakdown ──
        # F1 wrote summary["player_impact"]["spin_type_breakdown"] (the
        # spin_type_rows) before the emit loop. PayoutsBySpinType.emit() already
        # re-derives _st_label from it with this EXACT comprehension; we reuse the
        # same source of truth + same comprehension (no parallel derivation — per
        # feedback_no_parallel_panel_impl.md). Identical iteration order is what
        # makes the carved build byte-identical to the pre-carve PIA-local one.
        player_impact = summary.setdefault("player_impact", {})
        spin_type_breakdown = player_impact.get("spin_type_breakdown") or []
        _st_label: dict[int, str] = {
            int(row["spin_type"]): f"ST{int(row['spin_type'])}_{row['behavior_name']}"
            for row in spin_type_breakdown
        }

        # ── Build the reel_marginal_by_spin_type dict — moved VERBATIM from
        # PIA:~3432.  Sort order (sorted(_st_label.items()) then sorted col, then
        # symbol count descending), int(count), and the
        # prob_pct = (cnt / col_total) * 100.0 form preserved exactly (the
        # byte-identity contract depends on this being a verbatim move, not a
        # rewrite).  col_total == 0 columns are skipped exactly as before; labels
        # with no surviving columns still get an (empty) entry, matching the
        # pre-carve dict.
        reel_marginal_by_spin_type: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for st_int, label in sorted(_st_label.items()):
            col_rows: dict[str, list[dict[str, Any]]] = {}
            st_col_map = symbol_counts_by_col_by_spin_type_total.get(st_int) or {}
            for ci, sym_map in sorted(st_col_map.items()):
                col_total = sum(sym_map.values())
                if col_total == 0:
                    continue
                rows_for_col = [
                    {
                        "symbol": sym,
                        "count": int(cnt),
                        "prob_pct": (cnt / col_total) * 100.0,
                    }
                    for sym, cnt in sorted(sym_map.items(), key=lambda kv: kv[1], reverse=True)
                ]
                col_rows[str(ci)] = rows_for_col
            reel_marginal_by_spin_type[label] = col_rows

        player_impact["reel_marginal_by_spin_type"] = reel_marginal_by_spin_type


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per memory feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# ---------------------------------------------------------------------------
register(ReelMarginalBySpinType())
