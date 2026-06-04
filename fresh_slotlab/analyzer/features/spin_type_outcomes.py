"""AnalyzerFeature: spin_type_outcomes — per-SpinType win-distribution shape.

Part of the playtype re-architecture (branch ``claude/playtype-rearch``).

Purpose
-------
The analyzer event model uses SpinType as the primary unit.  The console
already shows a per-SpinType breakdown (spin_type_breakdown) and per-SpinType
payid rows (payouts_by_spin_type).  What was missing: a WIN-DISTRIBUTION SHAPE
(volatility profile) and TOP-COMBO ranking per SpinType — so every ST gets a
meaningful analysis, not just ST=14 (topdollar_choice).

This is the cross-machine answer to user request: "还是只有st14的分析?"
(still only ST14's analysis?)

Data path
---------
``emit()`` reads two already-built sections:

  summary["player_impact"]["payouts_by_spin_type"]
      Written by the PayoutsBySpinType feature (our declared dependency).
      A dict keyed by ST label (e.g. "ST1_paid", "ST14_free"), each value
      is a list of payid rows with: payout_id, hit_count, avg_win_when_hit,
      rtp_contribution_pp, symbol_combo["dominant"], covered_columns.

  summary["player_impact"]["spin_type_breakdown"]
      Written by the PIA inline block (Phase B — guaranteed present before
      the plugin emit loop per the ordering contract).  Each row has:
      spin_type, spins, win_rounds, hit_rate, rtp_contribution_pp.

  summary["sampling"]["bet"]
      The per-spin bet amount (credits).  Used to compute multipliers.

``extract()`` and ``reduce()`` are no-ops: all work is in ``emit()`` because
all source data is already in the summary when the emit loop runs.

Output schema (SCHEMA_VERSION = 1)
-----------------------------------
``summary["player_impact"]["spin_type_outcomes"]`` is a dict keyed by the same
per-ST label used by payouts_by_spin_type (e.g. "ST1_paid", "ST14_free"):

  {
    "spin_type": int,         # the ST integer
    "label": "ST1_paid",      # label string (same key)
    "dead_spin_rate": float,  # 1 - hit_rate (round-level, from stb row)
    "hit_rate": float,        # round-level hit rate (from stb row)
    "avg_win_when_hit": float, # total_win/win_rounds (0 if win_rounds==0)
    "rtp_contribution_pp": float, # round-level RTP contribution (from stb row)

    "win_bands": [            # PAYLINE-level distribution binned by avg_win/bet
      {
        "band": "<1x",        # band name
        "lo": 0,              # lower bound (inclusive, in units of bet)
        "hi": 1,              # upper bound (exclusive, or null for open-ended)
        "hit_count": int,     # sum of payid hit_counts in this band
        "rtp_pp": float,      # sum of payid rtp_contribution_pp in this band
      },
      ...                     # bands: <1x, 1-2x, 2-5x, 5-20x, 20-100x, 100x+
    ],

    "top_combos": [           # top 5 payids by rtp_contribution_pp desc
      {
        "payout_id": str,
        "combo": str | null,  # symbol_combo["dominant"] from payouts_by_spin_type
        "mult": float | null, # avg_win_when_hit / bet
        "hit_count": int,
        "rtp_pp": float,
        "covered_columns": list[int],
      },
      ...
    ],

    "max_mult": float,        # max avg_win/bet across this ST's real payids (0 if none)
    "pct_small_hits": float,  # share of hit_count with mult < 5 (0..1)
    "pct_big_hits": float,    # share of hit_count with mult >= 20 (0..1)
    "has_payouts": bool,      # False when payid list empty (ST14/ST15 on M15)
  }

Win-band semantics
------------------
Bands are PAYLINE-level, not round-level.  A round can win multiple paylines,
so the sum of win_band hit_counts across all STs can exceed win_rounds.
This is documented explicitly in the schema (and cross-checked in comments):

  ST1_paid on M15 (334k-spin run): payid hit_count sum 51074 > win_rounds 47507
  because each paying round can match multiple paylines simultaneously.
  This is CORRECT behaviour, not a bug.  The round-level fields
  (hit_rate, avg_win_when_hit, rtp_contribution_pp) come from spin_type_breakdown
  and are NOT derived from the payid list — they remain consistent.

Band edges (mult = avg_win_when_hit / bet):
  [0, 1)    → "<1x"
  [1, 2)    → "1-2x"
  [2, 5)    → "2-5x"
  [5, 20)   → "5-20x"
  [20, 100) → "20-100x"
  [100, ∞)  → "100x+"

Synthetic payids are excluded
------------------------------
Payids whose string representation starts with "_" (e.g. "_unattributed_residual",
"_other") are residual buckets, not real combos.  They are skipped when building
win_bands and top_combos.  This does NOT affect the round-level fields (hit_rate
etc.) which come from spin_type_breakdown, not from payid aggregation.

Per-machine isolation
---------------------
This file is NOT in ``fresh_slotlab/analyzer/core/`` — it is excluded from
``compute_base_analyzer_version()`` by R-4.  Only machines that declare
"spin_type_outcomes" in their manifest include this plugin's hash in their
``effective_analyzer_version``.  Editing this file re-flags ONLY those machines.

To avoid touching ``player_impact_analyzer.py`` (a closure file), this module
is auto-imported by ``payouts_by_spin_type.py`` at its module bottom.
``payouts_by_spin_type`` is always imported before the emit loop, ensuring
``spin_type_outcomes`` is registered when topo_sort runs.

REQUIRES = ("payouts_by_spin_type",)
  The orchestrator runs spin_type_outcomes.emit() AFTER payouts_by_spin_type
  (it reads that feature's output).  Also reads spin_type_breakdown (built by
  the inline PIA block before the emit loop — guaranteed present).

RTP_CONTRIBUTION = False
  This feature re-groups wins already attributed by payouts_by_spin_type.
  It adds NOTHING new to the RTP sum.  The invariant
  sum(pay_id.rtp_pp) == summary.rtp is unaffected.

Memory feedback honored
-----------------------
- feedback_no_hardcode.md:
    No machine-specific ids. Reads ST labels and payid rows generically.
    M15 only appears in the manifest + tests.
- feedback_aggregator_parity_invariant.md:
    RTP_CONTRIBUTION = False — wins are already attributed; adding to the
    RTP sum would double-count.
- feedback_no_silent_swallow.md:
    The REQUIRES dependency is checked LOUDLY: if payouts_by_spin_type's
    section is ABSENT (upstream crashed), emit() RAISES — the PIA emit loop
    records it in summary["feature_errors"] (visible/persisted), instead of
    silently writing {}. An empty-but-present payouts_by_spin_type ({}) is a
    legitimate no-op (empty result). A label present in payouts but absent
    from spin_type_breakdown is flagged round_stats_available=False rather
    than emitting silent zeros.
- feedback_invariant_with_fallback_hides_drift.md:
    No catch-all bucket.  Real payids only.  Residual "_" prefixed pids
    are explicitly excluded, not silently merged.
- feedback_no_parallel_panel_impl.md:
    Mirrors topdollar_choice / machine_mechanics pattern:
    extract() / reduce() / emit() decomposition, ClassVar layout, register().
- feedback_subprocess_import_suicide_and_module_globals.md:
    register() is a pure list-append — no I/O at import time.
- feedback_self_verify_output.md:
    The cross-signal note (payid hits vs win_rounds) is documented explicitly
    so reviewers know the discrepancy is expected, not a bug.
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


# ---------------------------------------------------------------------------
# Band definition (ordered, immutable)
# ---------------------------------------------------------------------------
# Each band: (name, lo_inclusive, hi_exclusive_or_None)
# lo/hi are in units of "multiples of bet" (mult = avg_win / bet).
# hi=None means open-ended (100x+).

_BANDS: tuple[tuple[str, float, float | None], ...] = (
    ("<1x",    0.0,   1.0),
    ("1-2x",   1.0,   2.0),
    ("2-5x",   2.0,   5.0),
    ("5-20x",  5.0,  20.0),
    ("20-100x", 20.0, 100.0),
    ("100x+",  100.0, None),
)


def _classify_mult(mult: float) -> int:
    """Return the band index for a given multiplier value.

    Bands are half-open [lo, hi) with the last band open-ended.
    Returns the index into _BANDS. A negative multiplier (corrupt/negative
    avg_win row) is defensively classified into the first band ("<1x")
    rather than silently misfiling it past a `mult < hi` check.
    """
    if mult < 0:
        return 0
    for i, (_, lo, hi) in enumerate(_BANDS):
        if hi is None or mult < hi:
            return i
    return len(_BANDS) - 1  # fallback: last band (100x+)


class SpinTypeOutcomes(AnalyzerFeature):
    """Pattern-B-ish plugin: read already-built summary sections in emit().

    extract() and reduce() are no-ops (empty dicts).  All computation is in
    emit() which reads summary["player_impact"]["payouts_by_spin_type"] (written
    by PayoutsBySpinType) and summary["player_impact"]["spin_type_breakdown"]
    (written by the PIA inline block before the emit loop).

    Accumulator structure
    ---------------------
    Empty dict — no per-chunk data needed.  The accumulator returned by
    extract() is {} and reduce() returns the prev_acc unchanged.
    """

    FEATURE_ID: ClassVar[str] = "spin_type_outcomes"
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("spin_type_outcomes",)
    SCHEMA_VERSION: ClassVar[int] = 1
    RTP_CONTRIBUTION: ClassVar[bool] = False  # re-groups already-attributed wins
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    REQUIRES: ClassVar[tuple[str, ...]] = ("payouts_by_spin_type",)
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    def extract(self, parse_state: Any, chunk_dict: Any) -> dict:
        """No-op: all work is deferred to emit().

        Returns an empty dict. The emit() method reads from the already-built
        summary sections rather than accumulating per-chunk data.
        """
        return {}

    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """No-op: returns prev_acc unchanged (empty dict throughout)."""
        return prev_acc if prev_acc is not None else {}

    def emit(self, final_acc: dict, summary: dict, ctx: "PipelineContext") -> None:
        """Build and write summary["player_impact"]["spin_type_outcomes"].

        Reads:
          summary["player_impact"]["payouts_by_spin_type"]
              Dict keyed by ST label ("ST1_paid", ...). Each value is a list
              of payid rows. Written by PayoutsBySpinType (REQUIRES dependency).
          summary["player_impact"]["spin_type_breakdown"]
              List of per-ST round-level stats. Written by PIA inline block
              (guaranteed present before plugin emit loop per ordering contract).
          summary["sampling"]["bet"]
              Per-spin bet amount (credits).

        Writes:
          summary["player_impact"]["spin_type_outcomes"]
              Dict keyed by ST label. See module docstring for full schema.

        Dependency handling:
          payouts_by_spin_type absent (upstream crashed) → RAISE (recorded in
          summary["feature_errors"]). payouts_by_spin_type present but empty
          ({}) → write {} and return (legitimate no-op). A label in payouts
          but missing from spin_type_breakdown → round_stats_available=False.

        Cross-signal note:
          win_band hit_counts are PAYLINE-level (sum of payid hit_counts).
          A single round can win multiple paylines, so sum(win_band hit_counts)
          may exceed spin_type_breakdown.win_rounds for the same ST. This is
          correct — both metrics are internally consistent; they just count
          different things (paylines vs. rounds).
        """
        player_impact = summary.setdefault("player_impact", {})

        # --- Hard dependency check (feedback_no_silent_swallow.md) ---
        # payouts_by_spin_type is a REQUIRES dependency. PayoutsBySpinType
        # ALWAYS writes its section (possibly an empty {}) when it runs, so an
        # ABSENT key means it did not run / crashed upstream. Surface that
        # LOUDLY by raising — the PIA emit loop records a raised emit()
        # exception into summary["feature_errors"][FEATURE_ID] (visible,
        # persisted) rather than this feature silently writing {} and hiding
        # the upstream failure.
        if "payouts_by_spin_type" not in player_impact:
            raise RuntimeError(
                "spin_type_outcomes requires "
                "player_impact['payouts_by_spin_type'] (REQUIRES dependency) "
                "but it is absent at emit time — PayoutsBySpinType did not run "
                "or failed upstream."
            )

        # --- Source data ---
        pbst: dict[str, list[dict[str, Any]]] = (
            player_impact.get("payouts_by_spin_type") or {}
        )
        stb_rows: list[dict[str, Any]] = (
            player_impact.get("spin_type_breakdown") or []
        )

        # An empty payouts_by_spin_type ({}) is legitimate (a machine with no
        # per-ST payout rows): emit an empty result, not an error.
        if not pbst:
            player_impact["spin_type_outcomes"] = {}
            return

        # --- Bet (for multiplier computation) ---
        bet: float = float(
            (summary.get("sampling") or {}).get("bet") or 0
        )

        # --- Build a lookup: ST label -> stb row ---
        # spin_type_breakdown row has: spin_type, spins, win_rounds, hit_rate,
        # rtp_contribution_pp, behavior_name, total_win (and more).
        # Label format mirrors payouts_by_spin_type: "ST{N}_{behavior_name}".
        stb_by_label: dict[str, dict[str, Any]] = {}
        for row in stb_rows:
            try:
                st_int = int(row.get("spin_type") or -1)
                bname = str(row.get("behavior_name") or "unknown")
                lbl = f"ST{st_int}_{bname}"
                stb_by_label[lbl] = row
            except (TypeError, ValueError):
                continue

        # --- Build output for each ST label present in payouts_by_spin_type ---
        result: dict[str, Any] = {}

        # Process labels in the order they appear in payouts_by_spin_type
        # (which is already sorted by st_int ascending per PayoutsBySpinType.emit).
        for label, payid_rows in pbst.items():
            # Parse ST int from label (e.g. "ST1_paid" -> 1).
            try:
                st_part = label.split("_")[0]  # "ST1"
                st_int = int(st_part[2:])       # strip "ST" prefix
            except (IndexError, ValueError):
                # Malformed label — skip gracefully.
                continue

            # --- Round-level fields from spin_type_breakdown ---
            # If this ST label is present in payouts_by_spin_type but ABSENT
            # from spin_type_breakdown, the round-level fields below degrade to
            # zeros. Flag that explicitly (round_stats_available=False) so a
            # consumer does not read "dead_spin_rate=1.0 / rtp=0" as real —
            # per feedback_no_silent_swallow.md (no silent misinformation).
            stb_row_opt = stb_by_label.get(label)
            round_stats_available = stb_row_opt is not None
            stb_row = stb_row_opt or {}
            win_rounds = int(stb_row.get("win_rounds") or 0)
            spins = int(stb_row.get("spins") or 0)
            total_win_stb = float(stb_row.get("total_win") or 0.0)
            hit_rate_stb = float(stb_row.get("hit_rate") or 0.0)
            rtp_pp_stb = float(stb_row.get("rtp_contribution_pp") or 0.0)

            avg_win_when_hit = (
                total_win_stb / win_rounds if win_rounds > 0 else 0.0
            )
            dead_spin_rate = 1.0 - hit_rate_stb

            # --- Filter real payid rows (exclude "_"-prefixed synthetic pids) ---
            real_rows = [
                r for r in (payid_rows or [])
                if not str(r.get("payout_id") or "").startswith("_")
            ]

            has_payouts = bool(real_rows)

            # --- Win bands (PAYLINE-level) ---
            # Initialise all bands with zero counts.
            bands: list[dict[str, Any]] = [
                {
                    "band": name,
                    "lo": lo,
                    "hi": hi,
                    "hit_count": 0,
                    "rtp_pp": 0.0,
                }
                for name, lo, hi in _BANDS
            ]

            total_real_hits = 0
            small_hits = 0   # mult < 5
            big_hits = 0     # mult >= 20
            max_mult: float = 0.0

            for r in real_rows:
                hits = int(r.get("hit_count") or 0)
                avg_win = float(r.get("avg_win_when_hit") or 0.0)
                rtp_pp_pid = float(r.get("rtp_contribution_pp") or 0.0)

                # Compute multiplier; handle missing/zero bet gracefully.
                if bet > 0:
                    mult = avg_win / bet
                else:
                    # bet unknown — cannot classify; skip band assignment
                    # for this row but still count hits/rtp for totals.
                    mult = None  # type: ignore[assignment]

                if mult is not None:
                    band_idx = _classify_mult(mult)
                    bands[band_idx]["hit_count"] += hits
                    bands[band_idx]["rtp_pp"] += rtp_pp_pid
                    max_mult = max(max_mult, mult)
                    if mult < 5:
                        small_hits += hits
                    if mult >= 20:
                        big_hits += hits

                total_real_hits += hits

            pct_small = (
                small_hits / total_real_hits if total_real_hits > 0 else 0.0
            )
            pct_big = (
                big_hits / total_real_hits if total_real_hits > 0 else 0.0
            )

            # --- Top combos (top 5 by rtp_contribution_pp desc, real pids only) ---
            sorted_real_rows = sorted(
                real_rows,
                key=lambda r: float(r.get("rtp_contribution_pp") or 0.0),
                reverse=True,
            )
            top_combos: list[dict[str, Any]] = []
            for r in sorted_real_rows[:5]:
                avg_win = float(r.get("avg_win_when_hit") or 0.0)
                sc = r.get("symbol_combo") or {}
                combo_str = sc.get("dominant") if isinstance(sc, dict) else None
                mult_val: float | None = (
                    avg_win / bet if (bet > 0 and avg_win > 0) else None
                )
                top_combos.append({
                    "payout_id": str(r.get("payout_id") or ""),
                    "combo": combo_str,
                    "mult": mult_val,
                    "hit_count": int(r.get("hit_count") or 0),
                    "rtp_pp": float(r.get("rtp_contribution_pp") or 0.0),
                    "covered_columns": list(r.get("covered_columns") or []),
                })

            result[label] = {
                "spin_type": st_int,
                "label": label,
                # Round-level fields (from spin_type_breakdown):
                "dead_spin_rate": dead_spin_rate,
                "hit_rate": hit_rate_stb,
                # avg_win_when_hit is round-level (total_win/win_rounds).
                # Note: this differs from payid avg_win_when_hit (payline-level).
                "avg_win_when_hit": avg_win_when_hit,
                "rtp_contribution_pp": rtp_pp_stb,
                # Payline-level band distribution (payid hit_counts binned by mult):
                "win_bands": bands,
                # Top 5 payids by rtp contribution:
                "top_combos": top_combos,
                # Derived volatility shape indicators:
                "max_mult": max_mult,
                "pct_small_hits": pct_small,
                "pct_big_hits": pct_big,
                "has_payouts": has_payouts,
                # False ⇒ round-level fields above are zero-filled because this
                # ST label was absent from spin_type_breakdown (not real data).
                "round_stats_available": round_stats_available,
            }

        player_impact["spin_type_outcomes"] = result


# ---------------------------------------------------------------------------
# Registration — fires at module-import time (pure list-append; no I/O).
# Per feedback_subprocess_import_suicide_and_module_globals.md.
# register() is idempotent: duplicate FEATURE_ID is a silent no-op.
# ---------------------------------------------------------------------------
register(SpinTypeOutcomes())
