"""Load spec + reel-strips + per-mode weights → fully wired SpinEngine.

Schema (2026-04-22 structural refactor):

  slot_designer/weights/<MACHINE>/
  ├── reel_strips.json            ← shared symbol-at-position layout
  └── mode_<N>/weights.json       ← per-stop weight arrays for this mode

Invariant enforced by the two-file split:
  * ``reel_strips.json`` is the single source of truth for which
    symbol sits at position i of reel j. All modes of the machine
    share it byte-for-byte — you physically can't give mode 1 a
    Cherry stop where mode 2 has a Bar1, because they read the
    same file.
  * ``mode_<N>/weights.json`` carries only the per-position weights
    (arrays of ints aligned to the strip). Different modes have
    different weights → different marginals → different RTP/hit.

``load_engine`` accepts a weights.json path and auto-discovers the
sibling ``reel_strips.json`` one level up. Tests that construct
synthetic weights in temp directories should also provide a
matching strips file (or pass ``strips_path=`` explicitly).
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


def _resolve_strips_path(weights_path: Path) -> Path:
    """Walk up from a ``mode_<N>/weights.json`` to find the machine's
    shared ``reel_strips.json``. Convention: strips live one directory
    above the mode dir (= the machine dir).
    """
    # weights.json → mode_N/ → machine/
    candidate = weights_path.parent.parent / "reel_strips.json"
    return candidate


def _assemble_reels(
    strips: list[list[str]],
    weights: list[list[int]],
) -> list[list[dict]]:
    """Combine shared symbol layout with per-mode per-stop weights."""
    if len(strips) != len(weights):
        raise ValueError(
            f"strips has {len(strips)} reels but weights has "
            f"{len(weights)} — they must match"
        )
    assembled: list[list[dict]] = []
    for ri, (strip, wts) in enumerate(zip(strips, weights)):
        if len(strip) != len(wts):
            raise ValueError(
                f"reel {ri+1}: strips has {len(strip)} stops but "
                f"weights has {len(wts)} — they must match per-position"
            )
        assembled.append([
            # v5: keep float precision (e.g., M15 topdollar weight 6.44
            # for exact 1/88 trigger). Pre-v5 int cast truncated to 6.
            {"symbol": s, "weight": float(w)}
            for s, w in zip(strip, wts)
        ])
    return assembled


def load_engine(
    spec_path: Path | str,
    weights_path: Path | str,
    spin_type: int = 1,
    *,
    strips_path: Path | str | None = None,
) -> Tuple[SpinEngine, dict]:
    """Load a machine into an executable ``SpinEngine``.

    Args:
      spec_path: ``slot_designer/specs/<MACHINE>.spec.json`` — paytable +
        rules. Shared across all modes of the machine.
      weights_path: ``slot_designer/weights/<MACHINE>/mode_<N>/weights.json``
        — per-stop weights for ONE mode. The engine reads this mode's
        weights (and the shared strips) to build its reels.
      spin_type: Which spin_type entry from ``spec["spin_types"]`` to
        activate (default 1). Single-mode specs typically only declare
        spin_type 1; multi-mode machines route different modes through
        different spin_types.
      strips_path: Explicit override for the shared symbol-layout file.
        If None (the common case), auto-discover at ``weights_path``'s
        grandparent directory.
    """
    spec_path = Path(spec_path)
    weights_path = Path(weights_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    weights_doc = json.loads(weights_path.read_text(encoding="utf-8"))

    if spec["machine"] != weights_doc.get("machine"):
        raise ValueError(
            f"spec/weights machine mismatch: spec={spec['machine']!r} "
            f"weights={weights_doc.get('machine')!r}"
        )

    strips_path = Path(strips_path) if strips_path is not None else _resolve_strips_path(weights_path)
    if not strips_path.exists():
        raise FileNotFoundError(
            f"reel_strips.json not found at {strips_path}. The new "
            f"layout (2026-04-22) expects strips at the machine dir; "
            f"if you're constructing synthetic weights in a temp dir, "
            f"pass strips_path= explicitly."
        )
    strips_doc = json.loads(strips_path.read_text(encoding="utf-8"))
    if strips_doc.get("machine") != spec["machine"]:
        raise ValueError(
            f"spec/strips machine mismatch: spec={spec['machine']!r} "
            f"strips={strips_doc.get('machine')!r}"
        )

    strip_reels = strips_doc["reels"]
    weight_reels = weights_doc["weights"]
    assembled = _assemble_reels(strip_reels, weight_reels)

    symbols = SymbolRegistry(spec["symbols"])
    rules = RuleSet(spec["pays"])
    evaluator = PaytableEvaluator(symbols, rules, spec["evaluation_order"])

    st_key = str(spin_type)
    if st_key not in spec["spin_types"]:
        raise ValueError(f"spin_type {spin_type!r} not declared in spec")
    st = spec["spin_types"][st_key]

    # reel_set name is carried by both strips and weights for cross-check;
    # ``spec.spin_types[st].reel_set`` picks which set to use when a
    # machine has multiple (bonus chain etc.). Current M1 has one set
    # named "default" and both strips + weights declare it.
    reel_set_name = st["reel_set"]
    if strips_doc.get("reel_set") != reel_set_name:
        # Fall back to strips_doc reel set if names differ — but warn
        # via an error to avoid silent mismatch.
        raise ValueError(
            f"spec expects reel_set {reel_set_name!r} but strips file "
            f"declares {strips_doc.get('reel_set')!r}"
        )

    reels: list[ReelStrip] = []
    for reel_stops in assembled:
        # v5 2026-04-23: weights widened to float. M15 topdollar ~6.44 needs
        # fractional to hit exact 1/88 trigger target (old int() cast silently
        # truncated to 6, giving ~1.06% vs target 1.136%).
        stops = [Stop(symbol=s["symbol"], weight=float(s["weight"])) for s in reel_stops]
        reels.append(ReelStrip(stops))

    # Payline — M1 has exactly 1 (line_id=1 on middle row).
    paylines = spec["grid"]["paylines"]
    if len(paylines) != 1:
        raise NotImplementedError(
            f"Phase 1 engine supports 1 payline; spec declares {len(paylines)}"
        )
    positions = [tuple(p) for p in paylines[0]["positions"]]

    # v5+ M15: build FeatureSpec from per-mode feature_params (weights.json)
    # or fall back to spec-level defaults (specs/M15.spec.json features[0]).
    feature_spec = None
    feature_trigger_pay_id = None
    feats = spec.get("features") or []
    if feats:
        feat = feats[0]
        feature_trigger_pay_id = feat.get("trigger_pay_id")
        # Per-mode override via weights.json `feature_params` block
        fp = weights_doc.get("feature_params") or {}
        x_count = fp.get("x_count_weights") or feat.get("x_count_weights")
        y_count = fp.get("y_count_weights") or feat.get("y_count_weights")
        x_val = fp.get("x_value_weights") or feat.get("x_value_weights")
        y_val = fp.get("y_value_weights") or feat.get("y_value_weights")
        thresh = fp.get("accept_threshold") or feat.get("accept_threshold", 40)
        max_r = fp.get("max_rounds") or feat.get("max_rounds", 4)
        if x_count and y_count:
            from .feature_m15 import FeatureSpec, _X_POOL, _Y_POOL
            feature_spec = FeatureSpec(
                x_count_weights=tuple(x_count),
                y_count_weights=tuple(y_count),
                x_value_weights=tuple(x_val) if x_val else (1.0,) * len(_X_POOL),
                y_value_weights=tuple(y_val) if y_val else (1.0,) * len(_Y_POOL),
                accept_threshold=float(thresh),
                max_rounds=int(max_r),
            )

    engine = SpinEngine(
        reels=reels,
        evaluator=evaluator,
        payline_positions=positions,
        cost_per_spin=int(st["cost_per_spin"]),
        bet_amount=int(st["bet_amount"]),
        spin_type=int(st_key),
        feature_spec=feature_spec,
        feature_trigger_pay_id=feature_trigger_pay_id,
    )
    return engine, spec


def load_reels_for_tuner(
    strips_path: Path | str,
    weights_path: Path | str,
) -> list[list[dict]]:
    """Return the assembled [{symbol, weight}, ...] per reel shape that
    the tuner / analytic / ordering layers all expect.

    Convenience helper used by tune.py and tests that want the in-memory
    reel representation without constructing a full SpinEngine.
    """
    strips_doc = json.loads(Path(strips_path).read_text(encoding="utf-8"))
    weights_doc = json.loads(Path(weights_path).read_text(encoding="utf-8"))
    return _assemble_reels(strips_doc["reels"], weights_doc["weights"])
