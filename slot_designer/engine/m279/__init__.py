"""M279-specific engine modules.

M279 = Light & Wonder 'Blazing 777 Triple Double Jackpot Wild — Nudging
Stacks' archetype + Asian-market collect-to-wheel feature add-on.

Mechanics not covered by core engine (M1/M15/M37):
  - Multi-payline (9 lines on a 3-reel grid)
  - Stacked-wild trio with bidirectional nudge (wild_up/wild2x_mid/wild_down)
  - Collect meter + 12-cell Wheel feature
  - 4 distinct SpinTypes (140 paid / 36 nudge / 2 wheel / 102 buffmap)

Architecture:
  - ``nudge.py``: detect partial wild stacks + sequence MoveSpin chain.
  - ``collect.py``: per-robot meter state + trigger logic.
  - ``wheel.py``: 12-cell weighted sampler.
  - ``engine.py``: M279SpinEngine that wires reels + evaluator + features
    into a multi-round session model (run_session returns ordered round
    list ready for emission).

Core engine (engine/spin.py / loader.py / evaluator.py) is touched only
minimally:
  - evaluator gains evaluate_all_paylines() additive method
  - loader relaxes the single-payline NotImplementedError
  - symbol gains optional _nudge_anchor metadata field

M1/M15/M37 paths remain bytewise unchanged.
"""
