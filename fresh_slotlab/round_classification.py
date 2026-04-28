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
    Analyzer/script picked max(feature_win) heuristic. Wrong on M279
    (MoveSpin 170M >> Wheel 11M; Wheel is actual BCM target).
    Wrong on M250/M256 etc where heuristic also misfires. Fix:
    walk rounds, find paid rounds at cc==cycle_peak, observe the
    immediate-next non-paid SpinType. Pure structural truth -- not
    affected by win magnitude. Used as Signal C (highest priority)
    in scripts/infer_bcm_pairing.py.

  Bug 3 — **Wild auto-nudge classification** (``is_wild_nudge_round``).
    M279/M226/M149 etc emit ST=36 + ReMarks="move" + cost=0 as the
    wild auto-nudge continuation of the preceding paid spin (no
    extra cost). Pre-fix the analyzer treated MoveSpin as a top-
    level feature, inflating its win and confusing BCM heuristics.
    Fix: classify by ReMarks word-boundary + cost==0; tag features
    with is_wild_nudge=True; exclude from BCM heuristic candidates.

  Bug 4 — **Cycle-peak detection semantics** (``detect_cycle_peak``).
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
from collections import defaultdict
from typing import Any, Iterable

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

# Regex for nudge-flavor remarks. M279 uses lower-case "move"; other
# machines may emit "Move", "Nudge", "WildMove", etc. Word-boundary
# anchors avoid accidental matches like "Move..." in trigger names
# such as "MoveSpinTrigger" (which is a different feature name, not
# a nudge marker).
_NUDGE_REMARK_RE = re.compile(r"\b(move|nudge)\b", re.IGNORECASE)


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


def get_collect_count(r: Any) -> int | None:
    """Robust int parse of the ``CollectCount`` BCM cycle counter.
    Returns None when the field is missing or non-numeric -- those
    machines have no BCM mechanic."""
    if not isinstance(r, dict):
        return None
    cc = r.get("CollectCount")
    if cc is None:
        return None
    try:
        return int(cc)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------
# Bug 3: wild-nudge classifier
# ---------------------------------------------------------------------


def is_wild_nudge_round(r: Any) -> bool:
    """True iff this round is a wild auto-nudge continuation of a
    preceding paid spin.

    Detection signals (all required):
      * ``CostCredits`` is None or 0 (no extra cost; nudge is free)
      * ``ReMarks`` contains "move" or "nudge" (case-insensitive)

    Verified across M279 / M226 / M149 / M140 / M26 / M51 / M256 in
    the 2026-04-27 fleet investigation: 25 (machine, mode) pairs
    emit ST=36 + ReMarks="move" + CostCredits=0 in a uniform shape.
    Other machines emit nothing matching this signature, so the
    classifier is False on them by construction.
    """
    if not isinstance(r, dict):
        return False
    cost = r.get("CostCredits")
    if cost is not None:
        try:
            if float(cost) > 0.0:
                return False
        except (TypeError, ValueError):
            return False
    rmk = r.get("ReMarks")
    if not isinstance(rmk, str):
        return False
    return bool(_NUDGE_REMARK_RE.search(rmk))


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


# ---------------------------------------------------------------------
# Bug 2: BCM cycle peak detection + observed-truth target inference
# ---------------------------------------------------------------------


def detect_cycle_peak(
    rounds: Iterable[Any],
    min_resets: int = 1,
) -> int | None:
    """Cycle length = the ``CollectCount`` value at which CC RESETS,
    observed empirically.

    Walks rounds tracking previous-vs-current CC. When ``cc < prev_cc - 1``
    AND ``prev_cc >= 5`` (signaling a real cycle reset, not just CC=0
    initialization), records ``prev_cc`` as a reset-target candidate.
    The most common reset target across the input is the cycle peak.

    **Crucial 2026-04-27 semantic refinement**: an earlier version of
    this function returned ``max(CollectCount)``, which mis-fires on
    machines like M250 / M256 whose sampled chunk doesn't span a full
    cycle. M250 cc walks 1->1000 monotonically without ever resetting
    in the 5000-paid-spin chunk; ``max(cc)=1000`` lied as "cycle peak"
    when really no cycle was observed. ``infer_bcm_target_spin_type``
    then sampled "what fires after cc=1000" -- ~12 NewFreespin events
    out of 909 cc=1000 paid rounds (1.3% trigger rate, clearly noise,
    not a deterministic BCM cycle).

    With the refined semantic, machines whose chunk is too short to
    see a full cycle return ``None`` -- callers fall through to the
    legacy max-feature heuristic instead of trusting noise.

    Args:
      rounds: iterable of round dicts (one robot or one chunk).
      min_resets: minimum reset events required to commit a peak.
        Default 1 accepts any single observed reset (suitable for
        per-robot calls). Per-chunk callers may want a higher
        threshold (e.g. 3) to filter out one-off cc-drops that
        aren't real cycle resets.

    Returns:
      The cycle peak value, or ``None`` when no qualifying reset
      was observed.
    """
    reset_targets: dict[int, int] = {}
    prev_cc: int | None = None
    for r in rounds:
        cc = get_collect_count(r)
        # Bonus rounds (ST=2 wheel, ST=36 nudge) carry CollectCount=None.
        # Skip them so prev_cc stays as the last paid round's cc -- the
        # next paid round's cc compared against it correctly identifies
        # a cycle reset across the bonus block. Pre-fix this loop set
        # prev_cc=None on bonus rounds, which masked the cc=peak ->
        # cc=1 transition that defines the cycle (M279: paid cc=1000 ->
        # wheel ST=2 cc=None -> paid cc=1; with prev_cc reset to None
        # the cc=1 round saw no prior reference, missing the reset).
        if cc is None:
            continue
        if (
            prev_cc is not None
            and cc < prev_cc - 1
            and prev_cc >= 5
        ):
            reset_targets[prev_cc] = reset_targets.get(prev_cc, 0) + 1
        prev_cc = cc
    if not reset_targets:
        return None
    peak, count = max(reset_targets.items(), key=lambda kv: kv[1])
    if count < min_resets:
        return None
    return peak


def at_cycle_peak_indices(rounds: list[Any], cycle_peak: int) -> list[int]:
    """Indices of paid rounds where ``CollectCount == cycle_peak``.

    These are the cycle-complete signals: the bonus rounds immediately
    after these indices are BCM-triggered. ``cycle_peak`` is typically
    obtained from :func:`detect_cycle_peak` over the full chunk.
    """
    out: list[int] = []
    for i, r in enumerate(rounds):
        if not is_paid_round(r):
            continue
        if get_collect_count(r) == cycle_peak:
            out.append(i)
    return out


def infer_bcm_target_spin_type(
    rounds: list[Any],
    cycle_peak: int | None = None,
) -> tuple[int | None, int]:
    """Walk one robot's rounds; for each paid round at cc=peak, find
    the immediate-next non-paid round and tally its SpinType. Return
    ``(dominant_spin_type, sample_count)``.

    Pure observed truth -- no win-magnitude heuristic. Beats
    ``max(feature_win)`` on M279 (MoveSpin 170M dominates feature_win
    but Wheel ST=2 fires after every cc=peak paid round = 100% of
    BCM cycle completions).

    Returns ``(None, 0)`` when no cycle peak is observable (machine
    has no BCM mechanic, or the chunk is too short to see a cycle).

    The optional ``cycle_peak`` arg lets callers pre-compute the
    peak across the entire chunk (across all robots) and pass it in;
    otherwise the function detects on its own list.
    """
    if cycle_peak is None:
        cycle_peak = detect_cycle_peak(rounds)
    if cycle_peak is None or cycle_peak < 1:
        return None, 0

    next_st_counter: dict[Any, int] = defaultdict(int)
    sample_count = 0
    n = len(rounds) if hasattr(rounds, "__len__") else 0
    if n == 0:
        return None, 0

    rounds_list = list(rounds) if not isinstance(rounds, list) else rounds
    n = len(rounds_list)
    for i, r in enumerate(rounds_list):
        if not is_paid_round(r):
            continue
        if get_collect_count(r) != cycle_peak:
            continue
        # Find the immediate-next non-paid round.
        for j in range(i + 1, n):
            nr = rounds_list[j]
            if not isinstance(nr, dict):
                continue
            if is_paid_round(nr):
                # Cycle peak followed by another paid round = no bonus
                # fired (rare; could indicate a ceiling without bonus).
                # Don't count toward target inference.
                break
            st = nr.get("SpinType")
            try:
                st_int = int(st) if st is not None else None
            except (TypeError, ValueError):
                st_int = None
            if st_int is not None:
                next_st_counter[st_int] += 1
                sample_count += 1
            break  # only the IMMEDIATE next non-paid round

    if sample_count == 0:
        return None, 0
    dominant_st = max(next_st_counter.items(), key=lambda kv: kv[1])[0]
    return dominant_st, sample_count
