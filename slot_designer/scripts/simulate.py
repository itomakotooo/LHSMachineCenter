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

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.emitter.driver import emit_simulation_to_dir
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
    p.add_argument("--initial-credits", type=int, default=1_000_000_000)
    args = p.parse_args()

    engine, spec = load_engine(args.spec, args.weights)

    def _progress(ci, total):
        print(f"chunk {ci}/{total} written ({args.robots}×{args.spins_per_robot} spins)")

    result = emit_simulation_to_dir(
        spec, engine, args.out_dir,
        chunks=args.chunks, robots=args.robots,
        spins_per_robot=args.spins_per_robot, seed=args.seed,
        initial_credits=args.initial_credits,
        progress=_progress,
    )
    print(f"\ntotal rounds: {result['total_rounds']}")
    print(f"sim RTP     : {result['realized_rtp_pct']:.2f}%")


if __name__ == "__main__":
    main()
