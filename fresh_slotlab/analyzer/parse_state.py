"""ParseState — per-chunk context passed to AnalyzerFeature.extract().

Phase C1 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md §4.1.
Phase 5C: mechanism_registry field removed (MechanismRegistry deleted).

ParseState is the typed container for what ``extract(parse_state, chunk_dict)``
receives at plugin call sites in the merge loop.  It is constructed once per
chunk (per plugin call) in report_engine.generate_report_from_chunks().

Schema contract (Wave 2 stable)
--------------------------------
``chunk_dict`` is the dict returned by ``parse_chunk_response()``.  Its
guaranteed top-level keys are listed in the docstring below.  Pattern-A
plugins (no-op extract) ignore ``chunk_dict``; Pattern-B plugins (real carve)
read it.  The ``machine_id`` / ``mode`` / ``manifest`` fields carry context
that the chunk dict does not provide.

No import-time I/O per memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ParseState:
    """Per-chunk context passed to AnalyzerFeature.extract().

    Parameters
    ----------
    chunk_dict : dict
        The raw chunk dict produced by parse_chunk_response().  Guaranteed
        top-level keys (Wave 2 stable contract):

        RTP / basic:
            ok, index, elapsed_seconds, spins, bet, win

        Payout attribution:
            payout_id_hits, payout_id_win,
            payout_id_by_spin_type, payout_id_win_by_spin_type

        SpinType breakdown:
            spin_type_spins, spin_type_bet, spin_type_paid_bet,
            spin_type_win, spin_type_wins, spin_type_paid_rounds,
            spin_type_next_counts, spin_type_remarks_sample,
            spin_type_nudge_round_count, spin_type_bucket_spins,
            spin_type_bucket_bet, spin_type_bucket_win

        Symbol / reel:
            symbol_counts, symbol_counts_by_col,
            symbol_counts_by_col_by_spin_type,
            payline_hits, payline_win_approx, payline_winning_symbols

        BCM / collect mechanic:
            collect_count_total, cycle_peaks, final_cc_values,
            completed_cycles

        Upstream feature attribution:
            upstream_feature_tally

        Bonus-chain dynamics:
            bonus_chain_lengths, bonus_chain_max_ratios

        Machine mechanics:
            jackpot_spins, jackpot_ids_seen, jackpot_win,
            freespin_chain_spins, freespin_retriggers

        Bankruptcy:
            bankruptcy_reps

    machine_id : str
        Machine identifier string (e.g. "M14", "M275").

    mode : int
        RTP mode integer (1, 2, 5, 7, ...).

    manifest : dict[str, Any]
        Resolved per-mode manifest for this (machine, mode).  Static for
        the lifetime of the run; provided here so plugins that need manifest
        data during per-chunk extraction do not have to re-load from disk.
    """

    chunk_dict: dict[str, Any]
    machine_id: str
    mode: int
    manifest: dict[str, Any]
