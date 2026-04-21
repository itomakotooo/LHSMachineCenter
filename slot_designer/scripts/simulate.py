"""CLI: simulate spins using spec + weights, emit rawdata-format chunks.

**Dev-only tool.** Writes to ``slot_designer/_dev_scratch/rawdata/`` by
default — intentionally separate from the virtual console's rawdata root
(``slot_designer/rawdata/``). The console's rawdata is owned by the
console alone and populated via ``POST /api/batch-run`` →
``virtual_analyzer.py`` (which handles chunk_index append semantics + md5
classification correctly). Running simulate with the default out-dir
NEVER touches console data.

Dev rawdata is **ephemeral** — no retention. Each run wipes the out-dir's
``chunk_*.json`` files before writing, so a re-run with new weights gets
a clean slate. To keep previous sim output around, pass an explicit
``--out-dir`` at a different path (that path gets the same wipe
semantics on the next simulate call targeting it).

Run as module from repo root:

    python -m slot_designer.scripts.simulate \\
        --spec slot_designer/specs/M1.spec.json \\
        --weights slot_designer/weights/M1_mode1.tuned.json \\
        --chunks 110 --robots 10 --spins-per-robot 1000 \\
        --machine-name M1sim

The default out-dir is
``slot_designer/_dev_scratch/rawdata/<machine>/mode_<N>/`` (machine from
``--machine-name`` or ``spec["machine"]``, mode from ``spec["mode"]``).

Produces chunk_NNNN.json files identical in schema to rawdata/M1/mode_1/.

``--machine-name`` should be set to the virtual-console machine name
(e.g. M1sim). If it matches an entry in machines_virtual.json, chunks
are tagged with the corresponding (config_md5, code_md5) for
cross-compatibility with analyzer --from-cache inspections. Without
this flag chunks emit with empty md5 (useful for schema-probing tests
but not representative of the virtual-machine pipeline).

Release flow (dev → console):
  1. simulate here to validate tuning numerics in ``_dev_scratch``
  2. update ``weights/<machine>_mode<N>.tuned.json`` (the active
     weights that virtual console sees)
  3. virtual console's next md5 refresh picks up the new config; the
     operator fires ``开始采样`` to populate console rawdata via
     virtual_analyzer. Dev scratch output is irrelevant to the console.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from slot_designer.backend.machine_version import compute_machine_md5
from slot_designer.emitter.driver import emit_simulation_to_dir
from slot_designer.engine.loader import load_engine

_SLOT_DESIGNER = _ROOT / "slot_designer"
_DEV_SCRATCH_ROOT = _SLOT_DESIGNER / "_dev_scratch" / "rawdata"


def _lookup_machine_md5(machine_name: str | None) -> tuple[str, str]:
    """Return (config_md5, code_md5) for a machine registered in
    machines_virtual.json. Unregistered names → ("", "").
    """
    if not machine_name:
        return ("", "")
    registry_path = _SLOT_DESIGNER / "configs" / "machines_virtual.json"
    try:
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ("", "")
    for entry in reg.get("machines", []):
        if entry.get("machine") == machine_name:
            return compute_machine_md5(entry)
    return ("", "")


def _resolve_default_out_dir(machine_name: str, mode: int) -> Path:
    """Default dev-scratch location — NEVER the virtual console's
    rawdata root. Each (machine, mode) gets its own subfolder so
    concurrent dev experiments on different machines don't collide.
    """
    return _DEV_SCRATCH_ROOT / machine_name / f"mode_{mode}"


def _wipe_chunks(out_dir: Path) -> int:
    """Delete existing chunk_*.json files in ``out_dir`` so a fresh
    simulate run starts from chunk_0001. Only touches chunk_NNNN.json
    (never other files) — keeps arbitrary operator content safe if
    out_dir happens to live outside the dev scratch root.
    """
    if not out_dir.is_dir():
        return 0
    removed = 0
    for p in out_dir.glob("chunk_*.json"):
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def main() -> None:
    p = argparse.ArgumentParser(description="Simulate slot spins → rawdata chunks")
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--weights", required=True, type=Path)
    p.add_argument("--out-dir", type=Path, default=None,
                   help="output directory for chunk_NNNN.json files. "
                        "default: slot_designer/_dev_scratch/rawdata/"
                        "<machine>/mode_<N>/ (ephemeral dev scratch). "
                        "NEVER defaults to the virtual console's rawdata "
                        "root — that's populated via console's batch-run, "
                        "not this CLI.")
    p.add_argument("--robots", type=int, default=10)
    p.add_argument("--spins-per-robot", type=int, default=1000)
    p.add_argument("--chunks", type=int, default=11)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--initial-credits", type=int, default=1_000_000_000)
    p.add_argument("--machine-name", default=None,
                   help="overrides spec's _machine field for chunk envelope + "
                        "pulls matching md5 from machines_virtual.json "
                        "(so analyzer --from-cache sees the right version tag)")
    args = p.parse_args()

    engine, spec = load_engine(args.spec, args.weights)

    emit_spec = dict(spec)
    machine_name = args.machine_name or str(spec.get("machine", ""))
    if args.machine_name:
        emit_spec["machine"] = args.machine_name

    mode = int(spec["mode"])
    if args.out_dir is None:
        args.out_dir = _resolve_default_out_dir(machine_name, mode)
        print(f"using dev scratch out-dir: {args.out_dir}")

    # Fresh simulate = clean slate. Wipe any pre-existing chunk_*.json
    # in the target dir so chunk_0001..N aren't overwritten piecemeal
    # (mixing md5 tags silently). Matches the "no retention, regenerate
    # if needed" philosophy for dev rawdata.
    wiped = _wipe_chunks(args.out_dir)
    if wiped:
        print(f"wiped {wiped} pre-existing chunk(s) in out-dir before sim")

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
