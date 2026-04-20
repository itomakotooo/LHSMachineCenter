"""CLI: simulate spins using spec + weights, emit rawdata-format chunks.

Run as module from repo root:

    python -m slot_designer.scripts.simulate \
        --spec slot_designer/specs/M1.spec.json \
        --weights slot_designer/weights/M1_mode1.current.json \
        --out-dir slot_designer/out/M1_mode1/cache \
        --chunks 11 --robots 10 --spins-per-robot 1000

Produces chunk_NNNN.json files identical in schema to rawdata/M1/mode_1/.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from random import Random

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.emitter.chunk import compute_schema_fingerprint, emit_chunk, write_chunk
from slot_designer.emitter.robot import emit_robot
from slot_designer.emitter.round import emit_round
from slot_designer.engine.loader import load_engine


def main() -> None:
    p = argparse.ArgumentParser(description="Simulate slot spins → rawdata chunks")
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--weights", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--robots", type=int, default=10)
    p.add_argument("--spins-per-robot", type=int, default=1000)
    p.add_argument("--chunks", type=int, default=11)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--initial-credits", type=int, default=1_000_000_000,
                   help="robot starting credits (large so robot never goes bankrupt)")
    args = p.parse_args()

    engine, spec = load_engine(args.spec, args.weights)
    rng = Random(args.seed)

    # Probe first-round to compute schema fingerprint (deterministic; doesn't
    # affect the main RNG stream).
    probe = emit_round(
        engine.spin(Random(0)),
        last_credits=args.initial_credits,
        spin_times=args.spins_per_robot,
        rtp_id=int(spec["mode"]),
    )
    schema_fp = compute_schema_fingerprint(probe)

    total_win = 0
    total_bet = 0
    total_rounds = 0
    for ci in range(1, args.chunks + 1):
        robots = []
        for _ in range(args.robots):
            last_credits = args.initial_credits
            rounds: list[dict] = []
            for _spin_i in range(args.spins_per_robot):
                outcome = engine.spin(rng)
                round_dict = emit_round(
                    outcome,
                    last_credits=last_credits,
                    spin_times=args.spins_per_robot,
                    rtp_id=int(spec["mode"]),
                )
                rounds.append(round_dict)
                last_credits = last_credits - outcome.cost_credits + round_dict["WinCredits"]
                total_win += round_dict["WinCredits"]
                total_bet += outcome.bet_amount
                total_rounds += 1
            robots.append(emit_robot(rounds, bet=engine.bet_amount))

        chunk = emit_chunk(
            robots,
            machine=spec["machine"],
            mode=int(spec["mode"]),
            bet=engine.bet_amount,
            spin_times=args.spins_per_robot,
            robot_count=args.robots,
            chunk_index=ci,
            upstream_schema_fingerprint=schema_fp,
        )
        write_chunk(chunk, args.out_dir, ci)
        print(f"chunk {ci}/{args.chunks} written ({args.robots}×{args.spins_per_robot} spins)")

    rtp_pct = total_win / total_bet * 100 if total_bet else 0
    print(f"\ntotal rounds: {total_rounds}")
    print(f"sim RTP     : {rtp_pct:.2f}%")


if __name__ == "__main__":
    main()
