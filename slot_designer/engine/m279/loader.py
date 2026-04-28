"""Load M279 spec + strips + per-mode weights → M279SpinEngine.

Mirrors core engine.loader.load_engine but builds an M279SpinEngine
(multi-payline + nudge + collect + wheel) instead of single-line
SpinEngine. The two are NOT interchangeable; the caller (virtual
analyzer / simulate / verify scripts) decides which to construct
based on whether the spec declares ``_m279_features``.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..evaluator import PaytableEvaluator
from ..reel_strip import ReelStrip, Stop
from ..rules import RuleSet
from ..symbol import SymbolRegistry
from .collect import load_collect_config
from .engine import M279SpinEngine
from .nudge import load_nudge_config
from .wheel import load_wheel_config


def _resolve_strips_path(weights_path: Path) -> Path:
    """Same convention as core loader: strips lives one dir above the
    mode dir."""
    return weights_path.parent.parent / "reel_strips.json"


def build_m279_engine(
    spec: dict,
    weights_doc: dict,
    strips_doc: dict,
    *,
    spin_type: int = 1,
) -> M279SpinEngine:
    """Build an M279SpinEngine from already-parsed spec/weights/strips dicts.

    Used by tuner inner loop to avoid disk roundtrip — load_m279_engine
    is the file-path entry point that wraps this.
    """
    if spec["machine"] != weights_doc.get("machine"):
        raise ValueError(
            f"spec/weights machine mismatch: spec={spec['machine']!r} "
            f"weights={weights_doc.get('machine')!r}"
        )
    if strips_doc.get("machine") != spec["machine"]:
        raise ValueError(
            f"spec/strips machine mismatch: spec={spec['machine']!r} "
            f"strips={strips_doc.get('machine')!r}"
        )

    strip_reels = strips_doc["reels"]
    weight_reels = weights_doc["weights"]
    if len(strip_reels) != len(weight_reels):
        raise ValueError(
            f"strip/weight reel count mismatch: strips={len(strip_reels)} "
            f"weights={len(weight_reels)}"
        )
    reels: list[ReelStrip] = []
    for ri, (strip, wts) in enumerate(zip(strip_reels, weight_reels)):
        if len(strip) != len(wts):
            raise ValueError(
                f"reel {ri+1}: strip stops={len(strip)} weights={len(wts)}"
            )
        stops = [Stop(symbol=s, weight=float(w)) for s, w in zip(strip, wts)]
        reels.append(ReelStrip(stops))

    symbols = SymbolRegistry(spec["symbols"])
    rules = RuleSet(spec["pays"], reroll_blocks=spec.get("reroll_blocks"))
    evaluator = PaytableEvaluator(symbols, rules, spec["evaluation_order"])

    paylines_spec = spec["grid"]["paylines"]
    if not paylines_spec:
        raise ValueError("M279 spec: grid.paylines is empty")
    paylines = [
        [tuple(p) for p in line["positions"]]
        for line in paylines_spec
    ]

    st_key = str(spin_type)
    if st_key not in spec["spin_types"]:
        raise ValueError(f"spin_type {spin_type!r} not declared in spec")
    st = spec["spin_types"][st_key]

    nudge_cfg = load_nudge_config(spec)
    collect_cfg = load_collect_config(spec)
    wheel_cfg = load_wheel_config(spec)

    overrides = weights_doc.get("_m279_overrides") or {}
    collect_override = overrides.get("collect_meter") or {}
    if "max" in collect_override:
        from .collect import CollectConfig
        collect_cfg = CollectConfig(
            max=int(collect_override["max"]),
            increment_per_paid_spin=collect_cfg.increment_per_paid_spin,
            credit_unit=collect_cfg.credit_unit,
        )
    wheel_override = overrides.get("wheel") or {}
    if "win_scale" in wheel_override:
        from .wheel import WheelCell, WheelConfig
        scale = float(wheel_override["win_scale"])
        wheel_cfg = WheelConfig(
            wheel_id=wheel_cfg.wheel_id,
            cells=tuple(
                WheelCell(c.cell_index, c.weight, int(c.win_credits * scale))
                for c in wheel_cfg.cells
            ),
        )

    return M279SpinEngine(
        reels=reels,
        evaluator=evaluator,
        paylines=paylines,
        cost_per_spin=int(st["cost_per_spin"]),
        bet_amount=int(st["bet_amount"]),
        nudge_cfg=nudge_cfg,
        collect_cfg=collect_cfg,
        wheel_cfg=wheel_cfg,
    )


def load_m279_engine(
    spec_path: Path | str,
    weights_path: Path | str,
    *,
    spin_type: int = 1,
    strips_path: Path | str | None = None,
) -> tuple[M279SpinEngine, dict]:
    """File-path entry point. Wraps build_m279_engine after disk loads."""
    spec_path = Path(spec_path)
    weights_path = Path(weights_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    weights_doc = json.loads(weights_path.read_text(encoding="utf-8"))
    strips_path = (
        Path(strips_path) if strips_path is not None
        else _resolve_strips_path(weights_path)
    )
    if not strips_path.exists():
        raise FileNotFoundError(f"reel_strips.json not found at {strips_path}")
    strips_doc = json.loads(strips_path.read_text(encoding="utf-8"))
    engine = build_m279_engine(spec, weights_doc, strips_doc, spin_type=spin_type)
    return engine, spec
