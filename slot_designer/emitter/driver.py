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
from .round import emit_round


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
) -> dict:
    """Run simulation and write chunk JSONs. Returns a summary dict."""
    rng = Random(seed)

    # Probe for schema fingerprint — deterministic seed, doesn't affect main RNG
    probe = emit_round(
        engine.spin(Random(0)),
        last_credits=initial_credits,
        spin_times=spins_per_robot,
        rtp_id=int(spec["mode"]),
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
                out = engine.spin(rng)
                round_dict = emit_round(
                    out,
                    last_credits=last_credits,
                    spin_times=spins_per_robot,
                    rtp_id=int(spec["mode"]),
                )
                rounds.append(round_dict)
                last_credits = last_credits - out.cost_credits + round_dict["WinCredits"]
                total_win += round_dict["WinCredits"]
                total_bet += out.bet_amount
                total_rounds += 1
            robot_list.append(emit_robot(rounds, bet=engine.bet_amount))

        chunk = emit_chunk(
            robot_list,
            machine=spec["machine"],
            mode=int(spec["mode"]),
            bet=engine.bet_amount,
            spin_times=spins_per_robot,
            robot_count=robots,
            chunk_index=ci,
            upstream_schema_fingerprint=schema_fp,
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
