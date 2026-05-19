# Phase 2 — Ticket Index

> Source: `session_artifacts/_arch/08_handoff.md §4 Phase 2` + `04_architecture_proposal_v5.md §6.2`.
> Phase risk: HIGH; estimated 12-16 dev days.

---

## Wave 2a (DONE)

| Ticket | Commit | Status |
|---|---|---|
| P2-A1 foundation (AnalyzerFeature ABC + versioning + feature_registry) | `170e25b` | SHIPPED |
| P2-A2 manifest loader + 11 validation rules | `81b0e81` | SHIPPED |

## Wave 2b — Core carve (4 files; implementer decision per spec)

Spec only names `analyzer/core/base_pipeline.py` (§5.8). Other 3 file names are architectural call. Based on PIA structure analysis (8126 lines, 54 top-level defs), the recommended split:

| Ticket | File | Scope (functions to move) | Order |
|---|---|---|---|
| **P2-B1a** | `analyzer/core/parser.py` (helpers) | 14 helpers + `ChunkIntegrityError` + 8 constants | 1st (SHIPPED) |
| **P2-B1b** | `analyzer/core/parser.py` (orchestrator) | `parse_chunk_response` only (~1857 lines) | 1st.5 (carve follow-up) |
| **P2-B2** | `analyzer/core/aggregator.py` | `_BankruptcyStreamAccumulator`, `simulate_bankruptcy_from_response`, `compute_bankruptcy_percentiles`, `fastest_bankruptcy_spins_from_list`, `median_spins_from_list`, `_empty_bankruptcy_tier`, `_extract_bankruptcy_reps`, `build_multiplier_bucket_rows`, `return_bucket`, `quantile_from_hist`, `classify_volatility`, `classify_experience_archetype`, `_metric_path_get`, `_eval_operator`, `_deviation`, `evaluate_guideline_comparison` | 2nd |
| **P2-B3** | `analyzer/core/writer.py` | `_save_chunk_cache` + summary-write logic extracted from `main()` | 3rd |
| **P2-B4** | `analyzer/core/base_pipeline.py` | `parse_args`, HTTP layer (`post_json`, `post_json_with_retry`, `aimd_tune`, `make_payload`, `_classify_failure`), `run_sampling_chunk`, `select_replay_chunks_by_md5`, high-level flow from `main()` ties parser+aggregator+writer; `pia.main` stays as thin shim per §5.8 | 4th (depends on B1+B2+B3) |

**Non-moved (stays in PIA)**: `pia.main()` itself stays at `fresh_slotlab/player_impact_analyzer.py:main` as the thin orchestrator per §5.8 (monkey-patches attach at same attribute). `compute_analyzer_version` already replaced by P2-A1 `compute_effective_analyzer_version`; legacy may be removed in P2-B4 or later.

## Wave 2c — Universal features (4 tickets)
Per §6.2 deliverable 2. Each ticket extracts one feature from PIA's `main()` aggregation into `analyzer/features/<feature_id>.py` subclass of `AnalyzerFeature` ABC (from P2-A1).
- P2-C1 payouts_by_spin_type
- P2-C2 reel_marginal_by_spin_type
- P2-C3 bankruptcy_simulation
- P2-C4 multiplier_profile

## Wave 2d — Cluster-shared features (9 tickets)
Per `02_taxonomy.md` cluster catalog. TBD names.

## Wave 2e — Bespoke + RTP gate (13 tickets)
- P2-E1 `rtp_integrity.py` (4 layers; warn-only mode by default)
- P2-E2..E13 — 12 forcing-function machines: M21/M260/M268/M279/M274/M113/M11/M250/M108/M65/M67/M120

## Wave 2f — Example 6 + cleanup
- P2-F1 Example 6 workflow M250 end-to-end demo
- P2-F2 per-cluster regression tests

---

## Status tracker

| Ticket | Brief | Status | Commit |
|---|---|---|---|
| P2-A1 | [01_foundation_files/00_ticket.md](01_foundation_files/00_ticket.md) | SHIPPED | `170e25b` |
| P2-A2 | [02_manifest_loader/00_ticket.md](02_manifest_loader/00_ticket.md) | SHIPPED | `81b0e81` |
| **P2-B1a** | [03_core_parser/00_ticket.md](03_core_parser/00_ticket.md) | SHIPPED (helpers only) | (this commit) |
| **P2-B1b** | [03b_core_parser_orchestrator/00_ticket.md](03b_core_parser_orchestrator/00_ticket.md) | **READY** (parse_chunk_response carve) | — |
| P2-B2 | TBD | PENDING | — |
| P2-B3 | TBD | PENDING | — |
| P2-B4 | TBD | PENDING | — |
| P2-C1..C4 | TBD | PENDING | — |
| P2-D1..D9 | TBD | PENDING | — |
| P2-E1..E13 | TBD | PENDING | — |
| P2-F1+ | TBD | PENDING | — |
