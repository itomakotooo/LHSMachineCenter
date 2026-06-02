"""Central round-level semantic primitives + observed-truth extractors.

Single source of truth for "what does this round mean" decisions used
by the analyzer (parse_chunk_response), the paytable inference script
(scripts/infer_paytable.py), and the BCM-pairing generator
(scripts/infer_bcm_pairing.py). Every primitive is pure-functional:
takes a round dict (or list of rounds), returns a classification /
extraction result. No I/O, no state, no machine-name special cases.

Five bug families (M279 / M260 / M250 / M120 / etc, 2026-04-27/28):

  Bug 1 — **PayoutId namespace** (``attribute_lines_to_pay_ids``).
    PayoutByPayline encodes ``<line>:<symbol>-<symbol>(positions)``;
    the actual pay_id lives only in PayoutIdToWinAmount. Inference
    scripts that read m[2] as pay_id work on simple machines (M14:
    symbol "8" == pay_id 8) but break on M120 (symbol "109" -> "9"),
    M139 ("55" -> "5"), M279 jackpot tiers ("27905" -> "104"). Fix:
    read PayoutIdToWinAmount as truth, assign each line via direct
    -> suffix -> single-remaining match.

  Bug 2 — **BCM target inference** (``infer_bcm_target_spin_type``).
    CARVED OUT (2026-06-02) to ``analyzer/play_types/bcm_cycle.py`` with the
    BCM cycle cluster (PT-3 carve); no longer defined here.
    Analyzer/script picked max(feature_win) heuristic. Wrong on M279
    (MoveSpin 170M >> Wheel 11M; Wheel is actual BCM target).
    Wrong on M250/M256 etc where heuristic also misfires. Fix:
    walk rounds, find paid rounds at cc==cycle_peak, observe the
    immediate-next non-paid SpinType. Pure structural truth -- not
    affected by win magnitude. Used as Signal C (highest priority)
    in scripts/infer_bcm_pairing.py.

  Bug 3 — **Wild auto-nudge classification** (``is_wild_nudge_round``).
    CARVED OUT (2026-06-02) to the base-excluded
    ``analyzer/play_types/wild_nudge.py`` (PT-7) so editing the detection
    logic no longer flips base_hash / re-flags the fleet. It detects
    M279/M226/M149 etc ST=36 + ReMarks="move" + cost=0 wild auto-nudge
    continuations of the preceding paid spin. (No longer defined here.)

  Bug 4 — **Cycle-peak detection semantics** (``detect_cycle_peak``).
    CARVED OUT (2026-06-02) to ``analyzer/play_types/bcm_cycle.py`` (PT-3 carve);
    no longer defined here.
    Initial implementation used max(CollectCount). For machines
    whose 1-chunk sample doesn't span a full cycle (M250/M256/M266/
    M268/M269/M277/M239/M246), cc walks 1->1000 monotonically with
    no reset -- max(cc)=1000 lied as "cycle peak", and the few
    cc=1000 paid rounds had ~1.3% bonus trigger rate (noise). Plus
    a second issue: bonus rounds carry CollectCount=None; the loop
    set prev_cc=None on them, breaking the cc=peak -> wheel(None)
    -> cc=1 reset detection on M279 (whole-robot detection failed).
    Fix: require an OBSERVED reset to commit a peak (returns None
    when no reset seen), and skip cc=None rounds so prev_cc spans
    the bonus block.

  Bug 5 — **Chain-timing for BCM trigger** (handled in analyzer's
    parse_chunk_response, but uses ``detect_cycle_peak`` here). The
    BCM-cycle flag was set on cc-DROP (the paid round AFTER cycle
    complete -- e.g. M279 cc=1000 -> wheel -> cc=1; flag fires at
    the cc=1 round which is too late, the wheel chain already
    closed). Plus wild-nudge rounds wrongly opened bonus chains.
    Fix in analyzer: set the BCM flag at cc==peak (BEFORE the next
    non-paid round opens the chain), and treat wild-nudge rounds
    as transparent to chain bookkeeping (don't open/accrue/close).

The module duplicates a small ``_is_paid_round`` predicate that
trigger_sessions / round_win also use privately. Keeping the
duplicate (~5 lines) avoids circular-import risk and lets each
module evolve independently. Tests lock byte-identity of the
predicate across all three modules.
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _to_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ``<line>:<sym>-<sym>(<positions>)`` -- existing format used across the fleet.
PAYLINE_RE = re.compile(r"(-?\d+):(-?\d+)-(-?\d+)\(([^)]*)\)")

# ---------------------------------------------------------------------
# Paid / bonus classification (duplicates trigger_sessions._is_paid_round
# intentionally; see module docstring)
# ---------------------------------------------------------------------


def is_paid_round(r: Any) -> bool:
    """Paid round: ``CostCredits > 0``. Bonus / nudge / freespin
    rounds carry CostCredits in (None, 0) on every machine observed."""
    if not isinstance(r, dict):
        return False
    cc = r.get("CostCredits")
    if cc is None:
        return False
    try:
        return float(cc) > 0.0
    except (TypeError, ValueError):
        return False





# ---------------------------------------------------------------------
# Bug 1: authoritative pay_id extraction + line attribution
# ---------------------------------------------------------------------


def extract_authoritative_pay_ids(r: Any) -> dict[str, float]:
    """Truth-source pay_id -> win mapping from ``PayoutIdToWinAmount``.

    Per-round pay_ids and their credited wins. Returns ``{}`` if the
    round has no PayoutIdToWinAmount or it's malformed. Keys are str
    (matching analyzer's ``payout_id_win`` convention).

    Use this -- NOT ``PayoutByPayline`` symbol parsing -- as the
    authoritative source for pay_id identity. PayoutByPayline encodes
    (line_id, symbol_id, positions); ``symbol_id != pay_id`` on many
    machines (M120 109/9, M139 55/5, M279 27905/104).
    """
    if not isinstance(r, dict):
        return {}
    pid = r.get("PayoutIdToWinAmount")
    if not isinstance(pid, dict):
        return {}
    return {str(k): _to_float(v, 0.0) for k, v in pid.items()}


def parse_payline_records(pbp: Any) -> list[dict]:
    """Parse the ``PayoutByPayline`` string into a list of records:

      [{"line_id": int, "symbol_id": str, "match_count": int,
        "positions": [int]}, ...]

    Returns ``[]`` for empty / non-string input. Handles trailing
    semicolons and optional whitespace between records.
    """
    if not isinstance(pbp, str) or not pbp:
        return []
    out: list[dict] = []
    for rec in pbp.split(";"):
        m = PAYLINE_RE.match(rec.strip())
        if not m:
            continue
        try:
            line_id = int(m[1])
        except (TypeError, ValueError):
            continue
        sym_id = m[2]
        positions_raw = m[4] or ""
        positions: list[int] = []
        for x in positions_raw.split(","):
            x = x.strip()
            if not x:
                continue
            try:
                positions.append(int(x))
            except (TypeError, ValueError):
                pass
        out.append({
            "line_id": line_id,
            "symbol_id": sym_id,
            "match_count": len(positions),
            "positions": positions,
        })
    return out


def attribute_lines_to_pay_ids(r: Any) -> list[dict]:
    """For each (line, symbol_pattern) in ``PayoutByPayline``, assign
    it to a pay_id from ``PayoutIdToWinAmount``.

    Resolution rules (in order):
      1. **Direct**: symbol_id is a key in PayoutIdToWinAmount -- use
         it. Covers M14, M272, and most simple-payline machines where
         pay_id IS the symbol_id by convention (~70% of fleet).
      2. **Suffix**: pay_id is a numeric suffix of symbol_id. M120
         "109" ends with "9", and pay_id "9" is in pid_keys. M123
         "308" ends with "8" -> pay_id "8". M139 "55" -> "5".
      3. **Single-remaining**: if exactly one pay_id is unaccounted
         for after passes 1-2 AND there are unmatched lines, attribute
         all unmatched lines to it. Covers M279 jackpot symbol 27905
         -> pay_id 104.

    Returns a list of records, each with a ``pay_id`` field (str) or
    ``None`` if the line could not be attributed. Each record also
    carries ``line_id``, ``symbol_id``, ``match_count``, ``positions``
    from the original parse.

    Operator note: when the same machine has multiple unmatched lines
    AND multiple unmatched pay_ids, the function leaves them as
    ``pay_id=None`` rather than guessing. The inference downstream
    counts these and surfaces the count as a quality-flag so the
    operator knows the machine needs explicit attention (rare).
    """
    if not isinstance(r, dict):
        return []
    pid_keys = set(extract_authoritative_pay_ids(r).keys())
    lines = parse_payline_records(r.get("PayoutByPayline"))
    # Always normalize: every record has a `pay_id` key (None until matched).
    for L in lines:
        L["pay_id"] = None
    if not lines or not pid_keys:
        return lines

    matched_pids: set[str] = set()

    # Pass 1: direct match.
    for L in lines:
        if L["symbol_id"] in pid_keys:
            L["pay_id"] = L["symbol_id"]
            matched_pids.add(L["symbol_id"])

    # Pass 2: suffix match (pay_id is suffix of symbol_id).
    # Sort unmatched pid_keys by length desc so longer suffixes match
    # first ("104" before "4" -- prevents "104" being shadowed by "4").
    unmatched_lines = [L for L in lines if L["pay_id"] is None]
    if unmatched_lines:
        unmatched_pids = sorted(pid_keys - matched_pids, key=lambda s: (-len(s), s))
        for L in unmatched_lines:
            sym = L["symbol_id"]
            for pid in unmatched_pids:
                # Suffix match must be on a digit boundary: pid "9" matches
                # "109" but not "029" if pid "29" exists. Since we sort by
                # length desc, the longest-suffix match takes priority.
                if sym.endswith(pid):
                    L["pay_id"] = pid
                    matched_pids.add(pid)
                    break

    # Pass 3: single-remaining pay_id absorbs remaining lines.
    unmatched_lines = [L for L in lines if L["pay_id"] is None]
    if unmatched_lines:
        remaining = pid_keys - matched_pids
        if len(remaining) == 1:
            only_pid = next(iter(remaining))
            for L in unmatched_lines:
                L["pay_id"] = only_pid

    return lines
