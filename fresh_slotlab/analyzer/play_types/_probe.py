"""play_types._probe — PreParseProbe ABC.

Per 04_v2.md §4.5 (new section).

Motivation
----------
Some machines (M10/M23/M131/M133 family) have CostCredits=0 on every round
despite real player wagers.  The current parser.py:L626-648 detects this by
scanning the first 200 rounds BEFORE the per-robot loop begins, setting
``cost_credits_unreliable=True``.  The standard MechanicAccumulator lifecycle
(on_round → on_robot_end → to_chunk_partial) cannot satisfy this pre-loop
ordering requirement because ``is_paid_round()`` must read
``cost_credits_unreliable`` at Step U1 of every round.

PreParseProbe runs ONCE per chunk BEFORE the per-robot loop begins.  Its
results are written to ParseState and read by the universal loop body at U1.

Lifecycle
---------
1. probe.run(sample_rounds, parse_state) — runs once before the outer robot
   loop.  sample_rounds = first min(200, len(chunk_robots[0].rounds)) rounds
   of the first robot.  parse_state = MUTABLE ParseState object shared with
   the universal loop body.
2. The universal loop body reads parse_state attributes at Step U1 of every
   round.
3. Probes do NOT implement on_round() — they are not accumulators.
4. Multiple probes may run; they are applied in registration order (no
   dependency ordering is needed — probes write to disjoint parse_state fields
   by design).

A PlayTypePlugin that requires a PreParseProbe implements get_probe() in
addition to make_accumulator().  If get_probe() returns None (the default),
no probe runs for that plugin.

No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PreParseProbe(ABC):
    """A probe that runs ONCE per chunk BEFORE the per-robot loop begins.

    Its results are written to ParseState and read by the universal loop body.

    Lifecycle:
    1. probe.run(sample_rounds, parse_state) — runs once before the outer
       robot loop.
       sample_rounds: first min(200, len(chunk_robots[0].rounds)) rounds of
                      the first robot.
       parse_state: a MUTABLE ParseState object shared with the universal
                    loop body.
    2. The universal loop body reads parse_state attributes at Step U1 of
       every round.
    3. Probes do NOT implement on_round() — they are not accumulators.
    4. Multiple probes may run; they are applied in registration order (no
       dependency ordering needed — probes write to disjoint parse_state
       fields by design).

    A PlayTypePlugin that requires a PreParseProbe implements get_probe() in
    addition to make_accumulator().  If get_probe() returns None (the
    default), no probe runs for that plugin.
    """

    @abstractmethod
    def run(self, sample_rounds: "list[dict]", parse_state: object) -> None:
        """Examine sample_rounds and set parse_state flags as needed.

        Must be idempotent (safe to call multiple times on the same
        parse_state with the same sample_rounds).

        Parameters
        ----------
        sample_rounds:
            First min(200, len(chunk_robots[0].rounds)) rounds of the first
            robot in the chunk.  READ ONLY — must not be mutated.
        parse_state:
            Mutable ParseState instance.  Write only the disjoint fields
            this probe owns; do not read or overwrite fields owned by other
            probes.
        """
        ...
