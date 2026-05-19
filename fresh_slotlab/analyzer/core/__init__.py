"""fresh_slotlab.analyzer.core — carved parsing / core primitives.

Package marker only. No import-time side effects per
memory/feedback_subprocess_import_suicide_and_module_globals.md.

Sub-modules:
  parser        — chunk-parsing primitives extracted from player_impact_analyzer.py
                  per tickets P2-B1a, P2-B1b (04_v5 §6.2 deliverable 1).
  _utils        — 9 shared pure-utility helpers (to_float, return_bucket, etc.)
                  consolidated from P2-B1b parser.py duplicates per ticket P2-B2.
                  C5: MUST NOT import from parser, aggregator, or PIA.
  aggregator    — 13 aggregation-only symbols (bankruptcy simulation, bucket rows,
                  volatility / archetype classification, guideline evaluation)
                  carved from player_impact_analyzer.py per ticket P2-B2.
                  C5: MUST NOT import from fresh_slotlab.player_impact_analyzer.
  writer        — atomic chunk-cache writer (_save_chunk_cache) + summary JSON
                  writer (write_summary_json) + CHUNK_CACHE_VERSION + utc_now().
                  Carved from player_impact_analyzer.py per ticket P2-B3.
                  C5: MUST NOT import from fresh_slotlab.player_impact_analyzer.
  base_pipeline — 8 HTTP/sampling helpers (parse_args, post_json, _classify_failure,
                  aimd_tune, post_json_with_retry, select_replay_chunks_by_md5,
                  make_payload, run_sampling_chunk) + ENDPOINT_URL constants +
                  AIMD constants + DEFAULT_GUIDELINE_RULES_PATH.
                  Carved from player_impact_analyzer.py per ticket P2-B4.
                  C5: MUST NOT import from fresh_slotlab.player_impact_analyzer.
"""
