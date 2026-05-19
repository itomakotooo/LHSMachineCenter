"""AnalyzerFeature: bankruptcy_simulation — Pattern B (logic extraction).

Ticket P2-C §2 / §3 C1-C2.
Pattern B: emit() owns the final summary schema keys.

Summary schema keys:
  - ``bankruptcy_simulation`` (dict with source/session_spins/percentile_keys/tiers)
  - ``bankruptcy_probe`` (back-compat alias: the raw tier rows list)

Implementation note — pre-summary dependency:
  player_impact_analyzer.py main() builds ``bankruptcy_rows`` at lines 4006-4051
  and uses the result at lines 4061, 4138-4145 (``x100_br`` etc.) BEFORE the
  summary dict is constructed. Moving the row-building loop into emit() would
  break those pre-summary references. Therefore this implementation uses a
  "split ownership" pattern:
    1. main() keeps the existing row-building loop (lines 4006-4051 unchanged).
    2. main() stashes the pre-built rows into summary["_bankruptcy_rows"] +
       summary["_bankruptcy_sim_session_spins"] just before the feature loop.
    3. main() DOES NOT set ``bankruptcy_simulation`` or ``bankruptcy_probe``
       in the summary dict literal.
    4. emit() reads the temp keys, writes the two final schema keys, deletes
       the temp keys.
    5. After the feature loop main() reads ``bankruptcy_rows`` back from
       ``summary["bankruptcy_probe"]`` for the markdown report.

  This split is documented in 02_implementation.md §Open Issues as a deferred
  full extraction (would require hoisting x100_br/x200_br/x500_br into emit
  too, which is a Wave 2d scope item).

Temp keys consumed from summary (set by main() before invoking features):
  - ``_bankruptcy_rows``               list[dict]  — pre-built tier rows
  - ``_bankruptcy_sim_session_spins``  int

Both temp keys are deleted from summary after emit() completes so they
never reach the final JSON output.

Per ticket P2-C §6 Risk 3: temp-key contract documented here.
Per memory feedback_subprocess_import_suicide_and_module_globals.md:
  register() is a pure list-append — no I/O at import time.

Parity guarantee (ticket P2-C §4 C3):
  emit() produces byte-identical output to the pre-Wave-2c inline logic.
  P1-A1 canary (test_analyzer_three_invocation_parity.py) is the guardrail.
"""
from __future__ import annotations

from typing import Any, ClassVar

try:
    from fresh_slotlab.analyzer.features._base import AnalyzerFeature
    from fresh_slotlab.analyzer.feature_registry import register
except ImportError:  # running as standalone script
    from analyzer.features._base import AnalyzerFeature  # type: ignore[no-redef]
    from analyzer.feature_registry import register  # type: ignore[no-redef]

# Canonical percentile tuple — same constant as _BANKRUPTCY_PERCENTILES in pia.
# Defined locally to avoid importing from player_impact_analyzer (cycle risk).
# Value MUST stay in sync with _BANKRUPTCY_PERCENTILES in pia (10,20,...,90).
_BANKRUPTCY_PERCENTILES: tuple[int, ...] = (10, 20, 30, 40, 50, 60, 70, 80, 90)


class BankruptcySimulation(AnalyzerFeature):
    """Pattern B feature: bankruptcy_simulation + bankruptcy_probe summary keys.

    Consumes temp keys set by main() (``_bankruptcy_rows``,
    ``_bankruptcy_sim_session_spins``), produces final summary keys
    ``bankruptcy_simulation`` and ``bankruptcy_probe``, then deletes
    the temp keys so they never appear in the written JSON.

    See module docstring for the "split ownership" rationale.
    Logic equivalent to pre-Wave-2c player_impact_analyzer.py lines 4529-4541.
    """

    FEATURE_ID: ClassVar[str] = "bankruptcy_simulation"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("bankruptcy_simulation", "bankruptcy_probe")
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        # Bankruptcy reps are already computed during chunk parsing by main().
        # No per-round extraction needed at this scaffolding stage.
        return {}

    def reduce(self, prev_acc: Any, this_acc: Any) -> Any:
        # No per-round accumulation; main() owns this via _BankruptcyStreamAccumulator.
        return prev_acc

    def emit(self, final_acc: Any, summary: dict) -> None:
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
