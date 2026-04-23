"""Run the engine for N spins and emit rawdata chunks.

Shared kernel ``sample_one_chunk`` used by:
- ``scripts/simulate.py`` / ``scripts/tune.py`` via
  ``emit_simulation_to_dir`` (fixed-chunk-count dev-scratch emission).
- ``backend/virtual_analyzer.py`` via ``_run_simulator_chunk``
  (CI-driven dynamic-stop virtual-console sampling).

Historical note (2026-04-23): these two pipelines had duplicated per-
chunk loops (robots × spins × emit). When ST=14/ST=15 feature emission
landed in ``emit_session`` + ``SpinEngine.spin_session`` only
``emit_simulation_to_dir`` was updated; ``virtual_analyzer`` still called
the old ``engine.spin()`` + ``emit_round()`` path → virtual console saw
M15sim RTP=43.25% (base only) while direct simulate.py showed 94%.
User-visible bug. Fixed by pulling the kernel into ``sample_one_chunk``
and routing both callers through it.
"""
from __future__ import annotations

from pathlib import Path
from random import Random
from typing import Callable

from ..engine.spin import SpinEngine
from .chunk import compute_schema_fingerprint, emit_chunk, write_chunk
from .robot import emit_robot
from .round import emit_round, emit_session


def sample_one_chunk(
    engine: SpinEngine,
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
) -> tuple[dict, int, int]:
    """Emit a single rawdata chunk dict. Returns ``(chunk, win, bet)``.

    Kernel of both sampling pipelines — every per-robot and per-spin
    detail that both simulate.py and virtual_analyzer must agree on
    lives here once.

    Feature handling: ``engine.spin_session`` produces the main ST=1
    outcome plus optional ST=14 feature rounds; ``emit_session`` turns
    those into the production-shaped [ST=1 Trigger, ST=14 × N, ST=15]
    sequence with matching ReMarks / WinAmount conventions. Machines
    without a feature engine (M1) get ``feature_rounds=[]`` so
    ``emit_session`` returns a single-item list identical to the
    pre-feature ``emit_round`` output.

    ``last_credits`` mirrors production: only the main ST=1 win updates
    the running credit balance. Feature ST=14 WinCredits values are
    display-only reveals — the actual session payout lives on ST=15
    (``WinAmount``) per analyzer's ``compute_trigger_sessions`` Type-1
    rule.

    ``win``/``bet`` totals track the main ST=1 only (feature rounds are
    ``BetAmount=0`` so they contribute 0 to bet; their display
    ``WinCredits`` is not real credit, so it contributes 0 to win).
    """
    robot_list = []
    chunk_win = 0
    chunk_bet = 0
    for _ in range(robots):
        last_credits = initial_credits
        rounds: list[dict] = []
        for _spin_i in range(spins_per_robot):
            out, feature_rounds = engine.spin_session(rng)
            session_dicts = emit_session(
                out,
                feature_rounds,
                last_credits=last_credits,
                spin_times=spins_per_robot,
                rtp_id=mode,
                feature_trigger_pay_id=engine.feature_trigger_pay_id,
            )
            rounds.extend(session_dicts)
            main_dict = session_dicts[0]
            last_credits = last_credits - out.cost_credits + main_dict["WinCredits"]
            chunk_win += main_dict["WinCredits"]
            chunk_bet += out.bet_amount
        robot_list.append(emit_robot(rounds, bet=engine.bet_amount))

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


def compute_schema_fingerprint_for(
    engine: SpinEngine,
    *,
    mode: int,
    spins_per_robot: int,
    initial_credits: int = 1_000_000_000,
) -> str:
    """Deterministic schema-fingerprint probe using a seeded RNG.

    Pulled out of both simulate + virtual_analyzer since both need the
    identical probe-then-hash flow to produce matching chunk envelopes.
    Uses Random(0) so fingerprints stay stable across restarts.
    """
    probe = emit_round(
        engine.spin(Random(0)),
        last_credits=initial_credits,
        spin_times=spins_per_robot,
        rtp_id=mode,
    )
    return compute_schema_fingerprint(probe)


def emit_simulation_to_dir(
    spec: dict,
    engine: SpinEngine,
    out_dir: Path,
    *,
    chunks: int,
    robots: int,
    spins_per_robot: int,
    seed: int,
    initial_credits: int = 1_000_000_000,
    progress: Callable[[int, int], None] | None = None,
    config_md5: str = "",
    code_md5: str = "",
    mode: int | None = None,
) -> dict:
    """Run simulation and write chunk JSONs. Returns a summary dict.

    ``mode`` (optional) overrides ``spec["mode"]`` for chunk envelope
    tagging + the per-round ``RTPId`` field. The spec itself stays
    single-mode (rules + paytable are shared across modes on M1-style
    machines); the caller picks which mode's identity to stamp on the
    chunks. Defaults to ``spec["mode"]`` for backward compatibility
    with single-mode callers.
    """
    effective_mode = int(mode) if mode is not None else int(spec["mode"])
    rng = Random(seed)

    schema_fp = compute_schema_fingerprint_for(
        engine,
        mode=effective_mode,
        spins_per_robot=spins_per_robot,
        initial_credits=initial_credits,
    )

    total_win = 0
    total_bet = 0
    total_rounds = 0
    chunks_written: list[Path] = []

    for ci in range(1, chunks + 1):
        chunk, c_win, c_bet = sample_one_chunk(
            engine,
            machine=spec["machine"],
            mode=effective_mode,
            chunk_index=ci,
            robots=robots,
            spins_per_robot=spins_per_robot,
            rng=rng,
            schema_fp=schema_fp,
            config_md5=config_md5,
            code_md5=code_md5,
            initial_credits=initial_credits,
        )
        p = write_chunk(chunk, out_dir, ci)
        chunks_written.append(p)
        total_win += c_win
        total_bet += c_bet
        # Each chunk contributes robots × spins_per_robot logical rounds
        # (feature sub-rounds are not counted here — caller sees paid
        # rounds only, matching prior behavior).
        total_rounds += robots * spins_per_robot
        if progress:
            progress(ci, chunks)

    return {
        "chunks_written": [str(p) for p in chunks_written],
        "total_rounds": total_rounds,
        "total_win": total_win,
        "total_bet": total_bet,
        "realized_rtp_pct": (total_win / total_bet * 100) if total_bet else 0.0,
        "schema_fingerprint": schema_fp,
        "out_dir": str(out_dir),
    }
