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
| | **DEDUP PREREQUISITE** for P2-B2 | P2-B1b duplicated 9 helpers into `core/parser.py` to break a cycle: `to_float`, `blank_like_symbol`, `bonus_chain_depth_bucket`, `return_bucket`, `_empty_bankruptcy_tier`, `_extract_bankruptcy_reps`, `simulate_bankruptcy_from_response`, `_DEFAULT_BANKROLL_MULTIPLIERS`, `_DEFAULT_BANKRUPTCY_SESSION_SPINS`. When P2-B2 moves the canonical copies out of PIA, the parser.py duplicates MUST be deleted in the same commit and parser.py MUST import from `core/aggregator.py` (or a shared `core/_utils.py`). Failing this creates a 3-copy drift trap. | (consolidation step) |
| **P2-B3** | `analyzer/core/writer.py` | `_save_chunk_cache` + summary-write logic extracted from `main()` | 3rd |
| **P2-B4** | `analyzer/core/base_pipeline.py` | `parse_args`, HTTP layer (`post_json`, `post_json_with_retry`, `aimd_tune`, `make_payload`, `_classify_failure`), `run_sampling_chunk`, `select_replay_chunks_by_md5`, high-level flow from `main()` ties parser+aggregator+writer; `pia.main` stays as thin shim per §5.8 | 4th (depends on B1+B2+B3) |

**Non-moved (stays in PIA)**: `pia.main()` itself stays at `fresh_slotlab/player_impact_analyzer.py:main` as the thin orchestrator per §5.8 (monkey-patches attach at same attribute). `compute_analyzer_version` already replaced by P2-A1 `compute_effective_analyzer_version`; legacy may be removed in P2-B4 or later.

## Wave 2c — Universal features (SHIPPED — 4 features batched into 1 commit)
Per §6.2 deliverable 2. Pragmatic strategy: scaffolding-first (Pattern A) for the bigger features, logic-extraction (Pattern B) for bankruptcy_simulation. See [07_wave_2c_universal_features/00_ticket.md](07_wave_2c_universal_features/00_ticket.md).
- P2-C1 payouts_by_spin_type (Pattern A) — SHIPPED
- P2-C2 reel_marginal_by_spin_type (Pattern A) — SHIPPED
- P2-C3 bankruptcy_simulation (Pattern B "split-ownership") — SHIPPED
- P2-C4 multiplier_profile (Pattern A; B deferred to Wave 2d) — SHIPPED

## Wave 2d — Cluster-shared features (9 tickets)
Per `02_taxonomy.md` cluster catalog. TBD names.

## Wave 2e — Bespoke + RTP gate
- P2-E1 `rtp_integrity.py` (4 layers; warn-only mode by default) — SHIPPED. See [08_rtp_integrity_gate/00_ticket.md](08_rtp_integrity_gate/00_ticket.md).
- P2-E2..E13 — 12 forcing-function machines: M21/M260/M268/M279/M274/M113/M11/M250/M108/M65/M67/M120 (per-machine BoundaryContract work; defer to per-machine sessions when machine specs land in Phase 3)

## Wave 2f — Example 6 + cleanup
- P2-F1 Example 6 workflow M250 end-to-end demo (deferred to per-machine M250 session in Phase 3+)
- P2-F2 per-cluster regression tests (deferred; framework lands when cluster-shared features land per Wave 2d)

---

# Phase 3 — partial progress

Item 0 — Day-1 verification (RTP gate against 46 candidates) — requires cached chunks for each Day-1 machine; not yet exercised.
Item 1 — **419 per-machine manifest files SHIPPED** via `scripts/generate_machine_manifests.py`. 393 from machines.json + 26 synthesized underlying templates for variant inheritance. Fleet-wide validation: 0 errors across all 419. See [09_phase3_manifest_bootstrap/00_ticket.md](09_phase3_manifest_bootstrap/00_ticket.md).
Item 2 — manifest_loader.py — already SHIPPED in Wave 2a (P2-A2).
Item 3 — Versioning wired to manifests. `compute_base_analyzer_version()` hashes `core/*.py` per §4.1; `compute_effective_version_for_machine(machine_id, mode)` orchestrates manifest read → variant cascade → per-mode override → feature lookup → 12-hex string. 7 previously-skipped hash-composition tests now exercise the real API.
Item 4 — PIA writes `effective_analyzer_version` into summary.json alongside legacy `analyzer_version` (best-effort; falls back to empty string with stderr diagnostic if manifest missing). SHIPPED.
Item 5 — `/api/reports/stale-count` read path: backend's `_update_report_index` writes new column; `backfill_rtp_ci_from_summaries` backfills legacy run rows. SHIPPED.
Item 6 — `ALTER TABLE runs ADD COLUMN effective_analyzer_version TEXT` via existing idempotent additive pattern. SHIPPED.
Item 7 — Frontend manifest consumption: pending; pairs with Phase 4 renderer registry work.
Item 8 — `scripts/validate_manifests.py` SHIPPED. Fleet-wide validator CLI; 419/419 clean today; exits 1 if any error fires; --json mode for CI.
Item 9 — `scripts/manifest_lint.py` SHIPPED. Soft-rule linter (L1-L4: bootstrap markers, override metadata, stale override age >90d, SC-Vanilla flip reminders). 45 L4 findings (Phase 3 item 0 follow-up).

---

## Status tracker

| Ticket | Brief | Status | Commit |
|---|---|---|---|
| P2-A1 | [01_foundation_files/00_ticket.md](01_foundation_files/00_ticket.md) | SHIPPED | `170e25b` |
| P2-A2 | [02_manifest_loader/00_ticket.md](02_manifest_loader/00_ticket.md) | SHIPPED | `81b0e81` |
| **P2-B1a** | [03_core_parser/00_ticket.md](03_core_parser/00_ticket.md) | SHIPPED (helpers only) | `41864fb` |
| **P2-B1b** | [03b_core_parser_orchestrator/00_ticket.md](03b_core_parser_orchestrator/00_ticket.md) | SHIPPED (parse_chunk_response carve) | `a1afc61` |
| **P2-B2** | [04_core_aggregator/00_ticket.md](04_core_aggregator/00_ticket.md) | SHIPPED (aggregator.py + _utils.py + dedup; 457 of 7-suite GREEN) | `ee8ea21` |
| **P2-B3** | [05_core_writer/00_ticket.md](05_core_writer/00_ticket.md) | SHIPPED (writer.py + DI for md5 lookup; 519 of 8-suite GREEN) | (this commit) |
| **P2-B4** | [06_core_base_pipeline/00_ticket.md](06_core_base_pipeline/00_ticket.md) | SHIPPED (HTTP layer + sampling helpers; main() refactor deferred to Wave 2c-2f) | (this commit) |
| P2-C1..C4 | TBD | PENDING | — |
| P2-D1..D9 | TBD | PENDING | — |
| P2-E1..E13 | TBD | PENDING | — |
| P2-F1+ | TBD | PENDING | — |
