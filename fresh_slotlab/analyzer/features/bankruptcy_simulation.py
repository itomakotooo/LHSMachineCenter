"""AnalyzerFeature: bankruptcy_simulation — Pattern B plugin that OWNS the row-build.

Ticket P2-C §2 / §3 C1-C2 introduced this as a Pattern B plugin whose ``emit()``
owns the final summary schema keys, but with a "split ownership" caveat: the actual
tier ROW-BUILD loop still lived inline in player_impact_analyzer.py (PIA) because
PIA consumes the rows BEFORE the summary dict is built (the pre-summary
``x100_br`` / ``x200_br`` / ``x500_br`` derivation that feeds
``guideline_assessment.bankruptcy_checks``).

Phase 6 (analyzer honesty/isolation — the LAST carve of the unbundle; see
session_artifacts/_arch_honesty_isolation/07_decision.md §5 "bankruptcy last —
split-ownership" and session_artifacts/_impl/phase_extract_6_bankruptcy/brief.md)
carved the tier ROW-BUILD LOGIC out of PIA and INTO this plugin file as the
module-level function :func:`build_bankruptcy_rows` (mirrors the 2a-5 carves, but
the split-ownership shape is different — see below).

The split-ownership approach (brief §0/§2)
------------------------------------------
``bankruptcy_rows`` is consumed by PIA in THREE places, one of which (the
pre-summary ``x100_br`` derivation) runs BEFORE the topo-sorted feature emit loop.
A late-running ``emit()`` therefore cannot OWN the build. The resolution:

  * The row-build LOGIC moves into this file as :func:`build_bankruptcy_rows`
    (a pure module-level function, byte-identical to the pre-Phase-6 PIA loop).
  * PIA ``import``s that function (dual-path) and CALLS it at the current
    pre-summary row-build site to obtain ``bankruptcy_rows``. ``x100_br`` etc.
    continue to derive from the returned rows UNCHANGED; PIA still stashes the
    rows; the markdown read-back is UNCHANGED.
  * ``emit()`` is UNCHANGED — it still reads ``_bankruptcy_rows`` /
    ``_bankruptcy_sim_session_spins`` from the stash and assembles the final
    ``bankruptcy_simulation`` + ``bankruptcy_probe`` dicts.

Why the carve: the row-build BYTES now live in this plugin file, which is NOT in
fresh_slotlab/analyzer/core/ and is a registered plugin (R-4) → its content is
EXCLUDED from ``compute_base_analyzer_version()`` (the fleet-wide base). Editing
the row-build now flips THIS feature's feature_hash, not base. PIA shed the loop
so base shrinks one-time. Report content is byte-identical; only WHERE the
build lives changed.

PIA importing a plugin FUNCTION on the report path is NEW (previously PIA imported
plugins only to register them). This is safe for the R-1 drift-guard because PIA
already imports this module for registration → it was already in sys.modules and
already excluded by Step-4 of the drift-guard (registered-plugin exclusion). No new
content module enters the closure; the guard still treats this file as an
R-4-excluded plugin. See brief §3 RISK 1.

Temp keys consumed from summary (set by main() before invoking features):
  - ``_bankruptcy_rows``               list[dict]  — pre-built tier rows
  - ``_bankruptcy_sim_session_spins``  int

Both temp keys are deleted from summary after emit() completes so they
never reach the final JSON output.

Per ticket P2-C §6 Risk 3: temp-key contract documented here.
Per memory feedback_subprocess_import_suicide_and_module_globals.md:
  register() is a pure list-append — no I/O at import time. The dual-path
  imports of the SHARED core helpers below resolve no-op (no side effects).
Per memory feedback_no_silent_swallow.md:
  build_bankruptcy_rows reads its tier inputs by explicit indexing (verbatim
  from the pre-carve PIA loop); a degenerate tier falls back to
  _empty_bankruptcy_tier() exactly as before (not a silent default that hides
  drift — it is the documented zero-count tier behaviour).
Per memory feedback_no_parallel_panel_impl.md:
  build_bankruptcy_rows is a VERBATIM move of the PIA loop (sort order,
  int() casts, rate/percentile/median/fastest forms preserved) — not a
  parallel reimplementation. SHARED helpers are imported from
  analyzer.core.* (the same source PIA used), never re-derived here.

Parity guarantee (ticket P2-C §4 C3):
  emit() produces byte-identical output to the pre-Wave-2c inline logic, and
  build_bankruptcy_rows produces byte-identical rows to the pre-Phase-6 PIA
  loop. P1-A1 canary (test_analyzer_three_invocation_parity.py) is the guardrail.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    from fresh_slotlab.analyzer.feature_registry import register
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    from analyzer.feature_registry import register  # type: ignore[no-redef]

# SHARED bankruptcy helpers used by build_bankruptcy_rows (Phase 6 carve).
# These already live in analyzer.core.* (moved there in P2-B2) and are the
# SAME functions PIA called from the pre-carve loop — imported from core, NOT
# re-derived here (per memory feedback_no_parallel_panel_impl.md). Dual-path
# (package-mode / standalone-script) per
# memory feedback_subprocess_import_suicide_and_module_globals.md. NEVER import
# player_impact_analyzer here (cycle risk + the plugin must not depend on PIA).
try:
    from fresh_slotlab.analyzer.core._utils import _empty_bankruptcy_tier
    from fresh_slotlab.analyzer.core.aggregator import (
        compute_bankruptcy_percentiles,
        fastest_bankruptcy_spins_from_list,
        median_spins_from_list,
    )
except ImportError:  # running as standalone script
    from analyzer.core._utils import _empty_bankruptcy_tier  # type: ignore[no-redef]
    from analyzer.core.aggregator import (  # type: ignore[no-redef]
        compute_bankruptcy_percentiles,
        fastest_bankruptcy_spins_from_list,
        median_spins_from_list,
    )

if TYPE_CHECKING:
    try:
        from fresh_slotlab.analyzer.pipeline_context import PipelineContext
    except ImportError:
        from analyzer.pipeline_context import PipelineContext  # type: ignore[assignment]

# Canonical percentile tuple — same constant as _BANKRUPTCY_PERCENTILES in pia.
# Defined locally to avoid importing from player_impact_analyzer (cycle risk).
# Value MUST stay in sync with _BANKRUPTCY_PERCENTILES in pia (10,20,...,90).
# NOTE (Phase 6): build_bankruptcy_rows does NOT reference this constant — it
# calls compute_bankruptcy_percentiles(), which carries the percentile tuple as
# its own default. This local copy remains only for emit()'s ``percentile_keys``
# output. PIA keeps its own copy for the markdown read-back (not carved). The
# two copies are intentionally kept (not consolidated) — see brief §1/§3 RISK 4.
_BANKRUPTCY_PERCENTILES: tuple[int, ...] = (10, 20, 30, 40, 50, 60, 70, 80, 90)


def build_bankruptcy_rows(
    bankruptcy_sim_totals: dict[int, dict[str, Any]],
    bankruptcy_mults_tuple: tuple[int, ...],
    bet: Any,
    bankruptcy_sim_session_spins: int,
) -> list[dict[str, Any]]:
    """Build the rawdata-replay bankruptcy tier rows (Phase 6 carve).

    Moved VERBATIM from player_impact_analyzer.py main() (the pre-Phase-6
    inline loop). Byte-identity contract: the returned rows are identical to
    what PIA's inline loop produced — sort order (iterate the mult tuple, then
    final sort by bankroll_multiplier), the int() casts, the
    ``rate = bankrupt / total_sessions`` form, the
    ``{str(k): v for k, v in percentiles.items()}`` serialization, and the
    SHARED helper calls (compute_bankruptcy_percentiles / median_spins_from_list
    / fastest_bankruptcy_spins_from_list / _empty_bankruptcy_tier) are preserved
    exactly. This is a move, not a rewrite (per memory
    feedback_no_parallel_panel_impl.md).

    Parameters
    ----------
    bankruptcy_sim_totals:
        Per-tier totals keyed by bankroll multiplier (int). Each tier dict
        carries ``bankrupt`` / ``survived`` / ``spins_done``. Built by main()'s
        merge loop and finalized from the streaming accumulator BEFORE this call.
        A missing tier degrades to ``_empty_bankruptcy_tier()`` (the documented
        zero-count tier — same as the pre-carve loop, NOT a silent default that
        hides drift; per memory feedback_no_silent_swallow.md).
    bankruptcy_mults_tuple:
        The bankroll multiplier tiers to emit (PIA's ``_bankruptcy_mults_tuple``).
    bet:
        The per-spin bet (PIA's ``args.bet``); ``init_credits = int(m) * int(bet)``.
    bankruptcy_sim_session_spins:
        The session-spin horizon (PIA's ``args.bankruptcy_session_spins``).

    Returns
    -------
    list[dict]
        Tier rows sorted ascending by ``bankroll_multiplier``.
    """
    bankruptcy_rows: list[dict[str, Any]] = []
    for m in bankruptcy_mults_tuple:
        tier = bankruptcy_sim_totals.get(int(m))
        if tier is None:
            tier = _empty_bankruptcy_tier()
        total_sessions = int(tier["bankrupt"]) + int(tier["survived"])
        rate = (tier["bankrupt"] / total_sessions) if total_sessions > 0 else 0.0
        # Sort the exact spins_done list once — all per-tier stats flow
        # from this sorted view. Preserves spin-level precision (the
        # previous histogram-based path collapsed ranges like
        # [100, 199] to a single midpoint 150, which quantized P10/P20
        # into visually identical rows when early deciles shared a bin).
        sd_sorted = sorted(int(v) for v in (tier.get("spins_done") or []))
        survived_ref = int(tier.get("survived") or 0)
        percentiles = compute_bankruptcy_percentiles(
            sd_sorted,
            survived_ref,
            bankruptcy_sim_session_spins,
        )
        median_spins = median_spins_from_list(
            sd_sorted,
            survived_ref,
            bankruptcy_sim_session_spins,
        )
        fastest = fastest_bankruptcy_spins_from_list(sd_sorted)
        bankruptcy_rows.append(
            {
                "bankroll_multiplier": int(m),
                "init_credits": int(m) * int(bet),
                "session_spins": bankruptcy_sim_session_spins,
                "robots": total_sessions,
                "bankrupt_robots": int(tier["bankrupt"]),
                "completed_robots": int(tier["survived"]),
                "bankruptcy_rate": rate,
                "median_spins_completed": median_spins,
                # Fastest observed bankruptcy (None when the tier saw
                # zero bankruptcies — e.g. a bankroll so large every
                # session survived). UI highlights this separately.
                "fastest_bankruptcy_spins": fastest,
                # Decile table keyed by percentile int → spin count at
                # that percentile across ALL simulated sessions (not
                # just bankrupt). JSON keys will serialize as strings.
                "percentiles": {str(k): v for k, v in percentiles.items()},
            }
        )
    bankruptcy_rows.sort(key=lambda row: int(row.get("bankroll_multiplier", 0)))
    return bankruptcy_rows


class BankruptcySimulation(AnalyzerFeature):
    """Pattern B feature: bankruptcy_simulation + bankruptcy_probe summary keys.

    Consumes temp keys set by main() (``_bankruptcy_rows``,
    ``_bankruptcy_sim_session_spins``), produces final summary keys
    ``bankruptcy_simulation`` and ``bankruptcy_probe``, then deletes
    the temp keys so they never appear in the written JSON.

    See module docstring for the "split ownership" rationale. The tier
    ROW-BUILD now lives in this file's module-level build_bankruptcy_rows()
    (Phase 6 carve); emit() consumes the rows PIA pre-built via that function.
    """

    FEATURE_ID: ClassVar[str] = "bankruptcy_simulation"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("bankruptcy_simulation", "bankruptcy_probe")
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ("_bankruptcy_rows", "_bankruptcy_sim_session_spins")

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        # Bankruptcy reps are already computed during chunk parsing by main().
        # No per-round extraction needed at this scaffolding stage.
        return {}

    def reduce(self, prev_acc: Any, this_acc: Any) -> Any:
        # No per-round accumulation; main() owns this via _BankruptcyStreamAccumulator.
        return prev_acc

    def emit(self, final_acc: Any, summary: dict, ctx: "PipelineContext") -> None:
        """Produce bankruptcy_simulation + bankruptcy_probe in summary["player_impact"].

        Reads temp keys (set by main() just before invoking features):
          summary["_bankruptcy_rows"]                — pre-built tier rows
          summary["_bankruptcy_sim_session_spins"]   — session spin horizon

        Produces (byte-identical to pre-Wave-2c main() lines 4529-4541),
        writing into summary["player_impact"] (where the frontend / backend
        route reads them per src/web_console/frontend/app.js:6069 and
        src/web_console/backend/app.py:4699):
          summary["player_impact"]["bankruptcy_simulation"]
          summary["player_impact"]["bankruptcy_probe"]

        Deletes both temp keys after writing final output.
        """
        bankruptcy_rows: list[dict] = summary["_bankruptcy_rows"]
        bankruptcy_sim_session_spins: int = summary["_bankruptcy_sim_session_spins"]

        # Write final keys into player_impact — byte-identical to pre-Wave-2c
        # pia lines 4529-4541. (player_impact is guaranteed to exist: main()
        # builds it as a top-level summary key before the feature loop runs.)
        player_impact: dict = summary["player_impact"]

        # Rawdata-replay bankruptcy simulation. UI renders the
        # ``tiers`` list as three side-by-side survival histograms
        # (x100 / x200 / x500 by default). Each tier's ``bins``
        # records bankrupt counts by spins-survived decile; the
        # ``survived`` scalar is the count of simulated paid-round
        # sessions that reached ``session_spins`` intact. All
        # percentages the UI displays are ratios over
        # ``robots`` (=bankrupt+survived).
        player_impact["bankruptcy_simulation"] = {
            "source": "rawdata_replay",
            "session_spins": bankruptcy_sim_session_spins,
            # Percentile layout (list of ints). Each tier.percentiles
            # maps these keys (as strings) → spin count at that
            # percentile of the tier's full session population. UI
            # renders a decile table instead of a bin histogram.
            "percentile_keys": list(_BANKRUPTCY_PERCENTILES),
            "tiers": bankruptcy_rows,
        }
        # Back-compat alias. Legacy consumers read bankruptcy_probe;
        # same rows but wearing the old name.
        player_impact["bankruptcy_probe"] = bankruptcy_rows

        # Clean up temp keys — they must not appear in the written JSON.
        del summary["_bankruptcy_rows"]
        del summary["_bankruptcy_sim_session_spins"]


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per ticket P2-C §4 C2: duplicate registration is a silent no-op.
# ---------------------------------------------------------------------------
register(BankruptcySimulation())
