"""CLI: simulate spins using spec + weights, emit rawdata-format chunks.

Run as module from repo root:

    python -m slot_designer.scripts.simulate \
        --spec slot_designer/specs/M1.spec.json \
        --weights slot_designer/weights/M1_mode1.tuned.json \
        --out-dir slot_designer/rawdata/M1sim/mode_1 \
        --chunks 110 --robots 10 --spins-per-robot 1000 \
        --machine-name M1sim

Produces chunk_NNNN.json files identical in schema to rawdata/M1/mode_1/.

``--machine-name`` should be set to the virtual-console machine name
(e.g. M1sim). If it matches an entry in machines_virtual.json, chunks
are tagged with the corresponding (config_md5, code_md5) so the
virtual console's classify_chunks treats them as "kept" instead of
"stale". Without this flag (or for an unregistered name) chunks emit
with empty md5 → any console would flag them stale (useful for
schema-probing tests but NOT for populating the virtual rawdata pool).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.backend.machine_version import compute_machine_md5
from slot_designer.emitter.driver import emit_simulation_to_dir
from slot_designer.engine.loader import load_engine


def _lookup_machine_md5(machine_name: str | None) -> tuple[str, str]:
    """Return (config_md5, code_md5) for a machine registered in
    machines_virtual.json. Unregistered names → ("", "").
    """
    if not machine_name:
        return ("", "")
    registry_path = _ROOT / "slot_designer" / "configs" / "machines_virtual.json"
    try:
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ("", "")
    for entry in reg.get("machines", []):
        if entry.get("machine") == machine_name:
            return compute_machine_md5(entry)
    return ("", "")


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
    p.add_argument("--machine-name", default=None,
                   help="overrides spec's _machine field for chunk envelope + "
                        "pulls matching md5 from machines_virtual.json "
                        "(required for virtual console to accept chunks)")
    args = p.parse_args()

    engine, spec = load_engine(args.spec, args.weights)

    emit_spec = dict(spec)
    if args.machine_name:
        emit_spec["machine"] = args.machine_name

    config_md5, code_md5 = _lookup_machine_md5(args.machine_name)
    if args.machine_name and not config_md5:
        print(f"warn: --machine-name {args.machine_name!r} not in "
              f"machines_virtual.json; chunks will be emitted with empty md5")

    def _progress(ci, total):
        print(f"chunk {ci}/{total} written ({args.robots}×{args.spins_per_robot} spins)")

    result = emit_simulation_to_dir(
        emit_spec, engine, args.out_dir,
        chunks=args.chunks, robots=args.robots,
        spins_per_robot=args.spins_per_robot, seed=args.seed,
        initial_credits=args.initial_credits,
        progress=_progress,
        config_md5=config_md5,
        code_md5=code_md5,
    )
    print(f"\ntotal rounds: {result['total_rounds']}")
    print(f"sim RTP     : {result['realized_rtp_pct']:.2f}%")
    if config_md5:
        print(f"machine tag : {args.machine_name} (config_md5={config_md5[:12]}…)")


if __name__ == "__main__":
    main()
