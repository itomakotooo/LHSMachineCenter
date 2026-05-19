"""fresh_slotlab.analyzer.core — carved parsing / core primitives.

Package marker only. No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.

Sub-modules:
  parser     — chunk-parsing primitives extracted from player_impact_analyzer.py
               per tickets P2-B1a, P2-B1b (04_v5 §6.2 deliverable 1).
  _utils     — 9 shared pure-utility helpers (to_float, return_bucket, etc.)
               consolidated from P2-B1b parser.py duplicates per ticket P2-B2.
               C5: MUST NOT import from parser, aggregator, or PIA.
  aggregator — 13 aggregation-only symbols (bankruptcy simulation, bucket rows,
               volatility / archetype classification, guideline evaluation)
               carved from player_impact_analyzer.py per ticket P2-B2.
               C5: MUST NOT import from fresh_slotlab.player_impact_analyzer.
"""
