"""play_types.bcm_cycle — BCM (BuffCollectionMap) cycle primitives.

CARVED OUT of round_classification.py (a base-closure file in
versioning._CLOSURE_FILES) into this base-excluded module, so editing the BCM
cycle logic no longer changes base_hash / re-flags the fleet. Pure functions; NO
registration and NO import-time side effects (keep these primitives free of side
effects so importing them stays inert).

Consumers import these from here: the inline parser path (parser.py) and
scripts/infer_bcm_pairing.py. They depend only on is_paid_round (an A-class
universal helper that stays in round_classification).

Pinned by tests/backend/test_bcm_cycle_carve.py (the base_hash isolation gate).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

try:
    from fresh_slotlab.round_classification import is_paid_round
except ImportError:  # running as a standalone script
    from round_classification import is_paid_round  # type: ignore[no-redef]


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


def compute_robot_cycle_peaks(rounds: list[Any]) -> list[int]:
    """Return the list of CC values at each cycle reset observed in *rounds*.

    **This is the single source of truth for per-robot cycle-peak lists.**
    The inline parser.py accumulation calls this function.  Any change to
    cycle-peak semantics must be made here.

    Reproduces EXACTLY the inline ``robot_cycle_peaks`` logic in
    ``parse_chunk_response``:

    * Only PAID rounds (CostCredits > 0) with ``cc_int > 0`` are considered.
    * ``prev`` initialised to ``0`` (same as ``robot_prev_cc_for_cycle = 0``).
    * Reset condition: ``cc_int < prev AND prev > 10``.
      - ANY drop (not ``< prev - 1``), floor is ``prev > 10`` (NOT ``>= 5``).
    * Appends ``prev`` at each qualifying reset.

    **Why this differs from detect_cycle_peak:**
    ``detect_cycle_peak`` is an INFERENCE function — it finds the cycle length
    from observed resets using a tighter condition (``cc < prev - 1 and
    prev >= 5``) and a mode-averaging approach.  It is robust against jitter
    and partial cycles.  ``compute_robot_cycle_peaks`` is a COUNTING function —
    it records every reset event so that ``len(result)`` equals the number of
    completed cycles in this robot's rounds.  The liberal ANY-drop condition
    matches the inline code's conservative intent: never miss a real reset.
    The higher floor (> 10 vs >= 5) avoids counting transient noise on the
    first few paid rounds of a fresh robot.

    BCM machines in practice have cycle peaks in the hundreds to thousands,
    so both conditions agree on real pilots.  The unit tests in
    ``test_bcm_cycle_carve.py`` (test_small_peak_not_recorded /
    test_single_step_drop_recorded) prove the two functions DISAGREE on small
    cycles (peaks in [5,10]) and single-step drops.
    """
    peaks: list[int] = []
    prev: int = 0
    for r in rounds:
        if not isinstance(r, dict):
            continue
        # BCM machines always have CostCredits populated.  is_paid_round
        # uses the same CostCredits > 0 predicate as the inline for the
        # paid-round gate.  For cost_credits_unreliable machines (M10 etc.)
        # the inline sets is_paid=True unconditionally, but those machines
        # have no CollectCount → cc_int == 0 → skipped below regardless.
        if not is_paid_round(r):
            continue
        cc_raw = r.get("CollectCount")
        try:
            cc_int = int(cc_raw or 0)
        except (TypeError, ValueError):
            cc_int = 0
        if cc_int <= 0:
            continue
        # Match the inline condition exactly.
        if cc_int < prev and prev > 10:
            peaks.append(prev)
        prev = cc_int
    return peaks


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
