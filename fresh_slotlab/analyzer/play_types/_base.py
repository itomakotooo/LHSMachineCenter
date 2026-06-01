"""play_types._base — RoundCtx NamedTuple + MechanicAccumulator ABC.

Per 04_v2.md §4.1-rev (call-ordering model and read-only rule).

Design contract
---------------
RoundCtx
    Frozen per-round context produced by the universal body (Step U1) before
    any plugin accumulator fires.  Accumulators read universal-derived values
    from here instead of re-deriving them.  ``round_dict`` (the raw upstream
    dict) is still passed separately to ``on_round()`` for plugin-specific
    raw fields.

MechanicAccumulator
    Per-robot stateful accumulator.  The parse loop instantiates one fresh
    accumulator per robot per chunk (never shared across robots).

    Per-round execution order (§4.1-rev Step P):
    ---------------------------------------------
    For each round in a robot's round list:

      Step U1: Universal body reads raw round_dict fields, computes is_paid,
               win_credits, authoritative_pay_ids, etc. and writes them into a
               frozen RoundCtx.  Does NOT write to round_dict.
      Step U2: Session-level accumulators run (inline, universal): _close_session,
               _flush_bonus_chain, etc. These read from RoundCtx, NOT from plugin
               accumulator output.  Invariant: session accumulators complete before
               any plugin accumulator fires.
      Step P:  For each active plugin accumulator, in MECHANIC_DEPS topo-sort
               order:
                   acc.on_round(round_dict, ctx, peers)
               where peers = {fid: acc_instance} for accumulators earlier in
               topo-sort.  MECHANIC_DEPS order governs both on_round() dispatch
               (Step P) and to_chunk_partial() merge order (EC-6 invariant).

    Read-only contract on round_dict
    ---------------------------------
    Accumulators MUST NOT mutate round_dict.  This is a protocol requirement,
    not an enforced ABC method.  The frozen RoundCtx is the primary vehicle
    for computed fields.  If an accumulator needs to communicate a derived
    field to a downstream accumulator, it writes to self.* and the downstream
    accumulator reads from the upstream accumulator's instance via peers:
        peers[fid].state  (read-only — do NOT mutate peer state)

    Fresh-per-robot (OQ-2 resolved)
    --------------------------------
    The parser is strictly per-robot: each robot's rounds are processed
    independently.  ``MechanicAccumulator`` is instantiated FRESH per robot;
    ``on_robot_end`` sees only that robot's rounds.  There is NO cross-robot
    handoff in the current implementation.  If a BCM cycle peak occurs in
    robot N and the corresponding bonus rounds fall in robot N+1, the current
    code (and this accumulator model) does not bridge that boundary — matching
    the existing inline behaviour for byte-identical output.

    Byte-identical guarantee
    ------------------------
    Three properties together guarantee byte-identical output vs. the current
    inline code (§4.1-rev):
    1. Float accumulation order is preserved (U1+U2 behaviour is identical;
       B functions that move to plugins are read by on_round, not by the
       universal body during the loop).
    2. Dict key insertion order is preserved (chunk dict assembled at finalize()
       by calling to_chunk_partial() for each accumulator in MECHANIC_DEPS order
       and merging; key names and insertion order must exactly match current
       inline code output — verified by byte-identical golden tests).
    3. Stash-write timing is unchanged (to_chunk_partial() is called before
       parse_chunk_response returns, identical to the current timing of
       compute_trigger_sessions and detect_cycle_peak).

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import NamedTuple


# ---------------------------------------------------------------------------
# RoundCtx — frozen per-round context (§4.1-rev)
# ---------------------------------------------------------------------------

class RoundCtx(NamedTuple):
    """Frozen per-round context from the universal body (Step U1).

    Accumulators read from here instead of re-deriving universal fields.
    ``round_dict`` is still passed to ``on_round()`` for plugin-specific raw
    fields.

    Fields
    ------
    is_paid : bool
        True when CostCredits > 0, OR when
        parse_state.cost_credits_unreliable=True (M10 family where CostCredits
        is always 0 but BetAmount > 0).  Set by the universal U1 body.
    win_credits : int
        WinCredits for this round.
    authoritative_pay_ids : frozenset[str]
        Pay IDs present in PayoutIdToWinAmount for this round.
    round_idx : int
        Zero-based index of this round within the robot's round list.
    spin_type : int
        SpinType field from the raw round dict.  0 if absent.
    remarks : str
        ReMarks field from the raw round dict.  Empty string if absent.
    """

    is_paid: bool
    win_credits: int
    authoritative_pay_ids: frozenset
    round_idx: int
    spin_type: int
    remarks: str


# ---------------------------------------------------------------------------
# MechanicAccumulator — per-robot stateful accumulator ABC (§4.1-rev)
# ---------------------------------------------------------------------------

class MechanicAccumulator(ABC):
    """Per-robot stateful accumulator.  Instantiated fresh per robot per chunk.

    CONTRACT:
    - on_round() MUST NOT mutate round_dict.
    - on_round() MAY read peer_accumulators[fid].state for peers earlier in
      MECHANIC_DEPS topo-sort.  It MUST NOT mutate peer state.
    - to_chunk_partial() is called ONCE per robot after on_robot_end(); the
      returned dict is merged into the chunk partial dict in MECHANIC_DEPS
      topo-sort order.
    - The merged chunk dict key names MUST exactly match those produced by the
      current inline code (verified by byte-identical golden tests).
    - This accumulator is instantiated fresh per robot; on_robot_end() sees
      only this robot's rounds.  There is NO cross-robot state handoff
      (OQ-2 resolved — matching existing per-robot inline behaviour).
    - MECHANIC_DEPS topo-sort governs BOTH on_round() dispatch order (Step P)
      AND to_chunk_partial() merge order (EC-6 invariant).
    """

    @property
    @abstractmethod
    def state(self) -> dict:
        """Read-only snapshot of current accumulation state.

        Used by peer accumulators via ``peers[fid].state``.  Callers must
        not mutate the returned dict.  Implementations should return a
        shallow copy or a frozen view to prevent accidental mutation.
        """
        ...

    @abstractmethod
    def on_round(
        self,
        round_dict: dict,
        ctx: RoundCtx,
        peers: "dict[str, MechanicAccumulator]",
    ) -> None:
        """Called for every round in this robot's round list, in topo-sort order.

        Parameters
        ----------
        round_dict:
            Raw upstream round dict.  READ ONLY — must not be mutated.
        ctx:
            Universal-derived frozen context for this round (Step U1 output).
            Prefer reading from ctx instead of re-deriving from round_dict
            for universal fields (is_paid, win_credits, authoritative_pay_ids,
            spin_type, remarks, round_idx).
        peers:
            Dict mapping FEATURE_ID to the already-fired accumulator instances
            (those earlier in MECHANIC_DEPS topo-sort for this round).  Read
            their ``.state`` property; never mutate them.
        """
        ...

    @abstractmethod
    def on_robot_end(
        self,
        all_rounds: "list[dict]",
        all_ctxs: "list[RoundCtx]",
    ) -> None:
        """Called once after all on_round() calls for this robot.

        Use for post-hoc corrections that require the full robot view.
        Accumulators that track state incrementally via on_round() typically
        implement this as a no-op.

        Parameters
        ----------
        all_rounds:
            Complete list of raw round dicts for this robot.  READ ONLY.
        all_ctxs:
            Complete list of RoundCtx values for this robot, in round order.
        """
        ...

    @abstractmethod
    def to_chunk_partial(self) -> dict:
        """Return this robot's mechanic contribution to the chunk dict.

        Called after on_robot_end().  The caller merges all accumulators'
        partials in MECHANIC_DEPS topo-sort order into a single chunk partial
        dict.

        The returned dict's keys MUST exactly match those produced by the
        current inline code output for the same mechanic.  The byte-identical
        golden tests enforce this contract.

        EC-1 (zero-round robot): must return a dict of the same keys as
        non-empty robots but with zero/empty values (never raise on empty
        robot input).
        """
        ...
