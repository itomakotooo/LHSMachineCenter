"""Load spec + weights JSON → fully wired SpinEngine.

``load_engine(spec_path, weights_path, spin_type=1)`` is the single entry
point used by scripts and tests.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

from .evaluator import PaytableEvaluator
from .reel_strip import ReelStrip, Stop
from .rules import RuleSet
from .spin import SpinEngine
from .symbol import SymbolRegistry


def load_engine(
    spec_path: Path | str,
    weights_path: Path | str,
    spin_type: int = 1,
) -> Tuple[SpinEngine, dict]:
    spec_path = Path(spec_path)
    weights_path = Path(weights_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    weights = json.loads(weights_path.read_text(encoding="utf-8"))

    if spec["machine"] != weights["machine"]:
        raise ValueError(
            f"spec/weights machine mismatch: spec={spec['machine']!r} "
            f"weights={weights['machine']!r}"
        )

    symbols = SymbolRegistry(spec["symbols"])
    rules = RuleSet(spec["pays"])
    evaluator = PaytableEvaluator(symbols, rules, spec["evaluation_order"])

    st_key = str(spin_type)
    if st_key not in spec["spin_types"]:
        raise ValueError(f"spin_type {spin_type!r} not declared in spec")
    st = spec["spin_types"][st_key]

    reel_set_name = st["reel_set"]
    if reel_set_name not in weights["reel_sets"]:
        raise ValueError(f"reel_set {reel_set_name!r} not in weights file")
    reel_set = weights["reel_sets"][reel_set_name]

    reels: list[ReelStrip] = []
    for reel_stops in reel_set["reels"]:
        stops = [Stop(symbol=s["symbol"], weight=int(s["weight"])) for s in reel_stops]
        reels.append(ReelStrip(stops))

    # Payline — M1 has exactly 1 (line_id=1 on middle row). Engine for now
    # operates on that single line; multi-payline is a future extension.
    paylines = spec["grid"]["paylines"]
    if len(paylines) != 1:
        raise NotImplementedError(
            f"Phase 1 engine supports 1 payline; spec declares {len(paylines)}"
        )
    positions = [tuple(p) for p in paylines[0]["positions"]]

    engine = SpinEngine(
        reels=reels,
        evaluator=evaluator,
        payline_positions=positions,
        cost_per_spin=int(st["cost_per_spin"]),
        bet_amount=int(st["bet_amount"]),
        spin_type=int(st_key),
    )
    return engine, spec
