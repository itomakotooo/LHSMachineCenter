"""M279-specific chunk sampler — analog of ``sample_one_chunk`` in
emitter/driver.py but routed through M279SpinEngine + emit_m279_session.

Why a separate function: M279's session model (1 paid + N nudge + maybe
wheel + buffmap) doesn't fit the M15 (outcome, feature_rounds) tuple
shape. The collect meter is per-robot persistent state across sessions
(unlike M15's feature which is per-spin one-shot). Forcing M279 into
the existing kernel would require extending SpinEngine.spin_session
into a list-returning beast — cleaner to add a parallel kernel.
"""
from __future__ import annotations

from random import Random

from slot_designer.core.emitter.chunk import emit_chunk
from slot_designer.core.emitter.robot import emit_robot
from slot_designer.machines.M279.plugins.m279.engine import M279SessionState, M279SpinEngine
from .m279_round import emit_m279_session


def sample_one_m279_chunk(
    engine: M279SpinEngine,
    *,
    machine: str,
    mode: int,
    chunk_index: int,
    robots: int,
    spins_per_robot: int,
    rng: Random,
    schema_fp: str,
    config_md5: str = "",
    code_md5: str = "",
    initial_credits: int = 1_000_000_000,
    paylines_spec: list[list[tuple[int, int]]] | None = None,
) -> tuple[dict, int, int]:
    """Sample one M279 chunk; returns (chunk_dict, total_win, total_bet).

    Mirrors sample_one_chunk in emitter/driver.py for M279.
    """
    if paylines_spec is None:
        paylines_spec = [list(line) for line in engine.paylines]

    robot_list = []
    chunk_win = 0
    chunk_bet = 0
    for _ in range(robots):
        last_credits = initial_credits
        rounds_dicts: list[dict] = []
        # Per-robot meter state — persists across the robot's session loop.
        state = M279SessionState()
        for _spin_i in range(spins_per_robot):
            session_rounds = engine.run_session(rng, state.meter)
            session_dicts = emit_m279_session(
                session_rounds,
                last_credits=last_credits,
                spin_times=spins_per_robot,
                rtp_id=mode,
                paylines_spec=paylines_spec,
                reel_skin=mode,  # ReelSkin = mode number per M279 cfg
            )
            rounds_dicts.extend(session_dicts)
            # Update last_credits from the paid round's net (cost - win).
            # Free rounds (ST=36/2/102) don't change cost; their win was
            # already realized on the paid spin's session aggregate.
            paid = session_rounds[0]  # first round is always ST=140 paid
            last_credits = last_credits - paid.cost_credits + paid.win_credits
            for r in session_rounds[1:]:
                last_credits += r.win_credits  # nudge / wheel adds wins
            # Session-level RTP accumulation:
            #   bet = paid.cost_credits (only ST=140 has bet)
            #   win = sum of all rounds' win_credits in the session
            session_win = sum(r.win_credits for r in session_rounds)
            chunk_win += session_win
            chunk_bet += engine.bet_amount
        robot_list.append(emit_robot(rounds_dicts, bet=engine.bet_amount))

    chunk = emit_chunk(
        robot_list,
        machine=machine,
        mode=mode,
        bet=engine.bet_amount,
        spin_times=spins_per_robot,
        robot_count=robots,
        chunk_index=chunk_index,
        upstream_schema_fingerprint=schema_fp,
        config_md5=config_md5,
        code_md5=code_md5,
    )
    return chunk, chunk_win, chunk_bet


def compute_m279_schema_fingerprint(
    engine: M279SpinEngine,
    *,
    mode: int,
    spins_per_robot: int,
    initial_credits: int = 1_000_000_000,
    paylines_spec: list[list[tuple[int, int]]] | None = None,
) -> str:
    """Compute a deterministic schema fingerprint for M279 chunks.

    Probes one round (paid) using a seeded RNG to capture the field set
    that ends up in the per-round JSON dicts. Same probe-then-hash
    pattern as the M1/M15 path.
    """
    from slot_designer.core.emitter.chunk import compute_schema_fingerprint
    from slot_designer.machines.M279.plugins.m279.engine import M279SessionState

    if paylines_spec is None:
        paylines_spec = [list(line) for line in engine.paylines]

    state = M279SessionState()
    rng = Random(0)
    session_rounds = engine.run_session(rng, state.meter)
    # Use only the paid round (ST=140) as the schema probe — that's the
    # round dict with the fullest field set (collect meter fields,
    # PayoutByPayline string, etc.). Free rounds have minimal schemas.
    paid_dict = emit_m279_session(
        [session_rounds[0]],
        last_credits=initial_credits,
        spin_times=spins_per_robot,
        rtp_id=mode,
        paylines_spec=paylines_spec,
        reel_skin=mode,
    )[0]
    return compute_schema_fingerprint(paid_dict)
