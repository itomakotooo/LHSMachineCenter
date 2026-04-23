"""Run the engine for N spins and emit rawdata chunks.

Shared helper used by scripts/simulate.py AND scripts/tune.py (which
needs to materialize tuned weights into rawdata — that's the actual
deliverable, not the weights file).
"""
from __future__ import annotations

from pathlib import Path
from random import Random
from typing import Callable

from ..engine.spin import SpinEngine
from .chunk import compute_schema_fingerprint, emit_chunk, write_chunk
from .robot import emit_robot
from .round import emit_round, emit_session


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

    # Probe for schema fingerprint — deterministic seed, doesn't affect main RNG
    probe = emit_round(
        engine.spin(Random(0)),
        last_credits=initial_credits,
        spin_times=spins_per_robot,
        rtp_id=effective_mode,
    )
    schema_fp = compute_schema_fingerprint(probe)

    total_win = 0
    total_bet = 0
    total_rounds = 0
    chunks_written: list[Path] = []

    for ci in range(1, chunks + 1):
        robot_list = []
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
                    rtp_id=effective_mode,
                    feature_trigger_pay_id=engine.feature_trigger_pay_id,
                )
                # Main spin is always session_dicts[0] — its WinCredits updates
                # last_credits (cost charged + regular/scatter wins). Feature
                # ST=14 sub-rounds and ST=15 marker are emitted below it but
                # do not mutate last_credits (mirrors production: player credit
                # stays flat across feature rounds in rawdata).
                main_dict = session_dicts[0]
                rounds.extend(session_dicts)
                last_credits = last_credits - out.cost_credits + main_dict["WinCredits"]
                total_win += main_dict["WinCredits"]
                total_bet += out.bet_amount
                total_rounds += 1
            robot_list.append(emit_robot(rounds, bet=engine.bet_amount))

        chunk = emit_chunk(
            robot_list,
            machine=spec["machine"],
            mode=effective_mode,
            bet=engine.bet_amount,
            spin_times=spins_per_robot,
            robot_count=robots,
            chunk_index=ci,
            upstream_schema_fingerprint=schema_fp,
            config_md5=config_md5,
            code_md5=code_md5,
        )
        p = write_chunk(chunk, out_dir, ci)
        chunks_written.append(p)
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
