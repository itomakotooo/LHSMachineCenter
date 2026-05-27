# Phase C2 — impl-* team brief

> **Date**: 2026-05-26
> **Coordinator**: main session
> **Authoritative spec**: `session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md`
> **Phase**: C2 (second of 7 — C1 ✓ ae6b79a / **C2** / C3 / C3.5 / C4 / C5 / C6)
> **Commit scope**: one logical commit

---

## §1 Phase C2 purpose (one sentence)

Carve PIA inline `payouts_by_spin_type` aggregation into the plugin's `extract` / `reduce` / `emit` (Pattern A scaffold → Pattern B real implementation), without changing the output JSON.

## §2 What this phase ships

Per `04_v3 §7.2` Phase C2 deliverables + C1 protocol infrastructure shipped at `ae6b79a`:

1. **MODIFY `fresh_slotlab/analyzer/features/payouts_by_spin_type.py`**:
   - Replace Pattern A `extract = lambda ...: {}` no-op with real per-chunk extraction reading `chunk_dict["payout_id_by_spin_type"]` + `chunk_dict["payout_id_win_by_spin_type"]` (the per-chunk dicts the parser already produced; see `fresh_slotlab/analyzer/core/parser.py`)
   - Real `reduce(prev_acc, this_acc)` merges (pid, st_int) → (hit_count, win) across chunks
   - Real `emit(final_acc, summary, ctx)`:
     - Reads `ctx.effective_bet_for_rtp` for `rtp_contribution_pp` denominator
     - Reads `summary["player_impact"]["spin_type_breakdown"]` (already written by PIA F1 inline, kept as PIA pre-emit work) to derive `_st_label` mapping (per `01_pipeline_map.md §7 Dependency A` mechanism documented in v3 §7.1)
     - Writes `summary["player_impact"]["payouts_by_spin_type"]`
   - SCHEMA_VERSION stays `1` (no schema shape change in C2; C3 enrichment will bump to 2)
   - Add `DECLARED_DEPS` if the plugin needs any PIA-produced `_`-prefix temp keys (probably just `_spin_type_breakdown` if F1 stashes it that way — read `01_pipeline_map.md §7` for the exact mechanism)

2. **MODIFY `fresh_slotlab/player_impact_analyzer.py`** main():
   - **Delete** the inline `payouts_by_spin_type` construction block (currently lines ~3292-3349 per `01_pipeline_map.md`, the block that builds `payouts_by_spin_type: dict[str, list[dict[str, Any]]] = {}` and writes it into `summary["player_impact"]["payouts_by_spin_type"]`)
   - **Delete** the accumulators `payout_id_by_spin_type_total` and `payout_id_win_by_spin_type_total` from main() local scope (lines ~1282-1289 and merge-loop sections at ~1729-1747 and ~2449-2459) — they move into the plugin's reduce()
   - **Keep** `_st_label` and `_st_behavior` if they're still needed by other inline blocks; otherwise carve them too
   - Confirm the plugin's emit() is invoked with the correct `ctx` containing `effective_bet_for_rtp`

3. **Side benefits to verify** (not core scope but expected to fall out):
   - Plugin file source bytes change → plugin hash changes → 253 declaring-machine `effective_analyzer_version` flips again (independent of C1's flip; one C1+C2 combined flip from operator perspective if rebuilt fresh)
   - PIA source bytes change too (deletion) → `analyzer_version` (legacy) changes too

## §3 What this phase MUST NOT do

- ❌ Change `payouts_by_spin_type` JSON output shape (no new/removed fields; C3 enrichment is the next phase for shape/cols/paylines/notes)
- ❌ Change `payout_ids_top20` or `payout_groups_top20` (those are separate panels; C2 is scoped to `payouts_by_spin_type` only)
- ❌ Carve any other inline block (`reel_marginal_by_spin_type`, `machine_mechanics`, `collect_mechanic`, etc.) — that's C4-C6 territory
- ❌ Touch `core/*.py` files (those flips full fleet base_hash; we want C2 invalidate-set limited to 253 declaring machines)
- ❌ Modify `pipeline_context.py` / `parse_state.py` / `topo_sort.py` (C1-shipped infrastructure; stable)
- ❌ Commit anything (only coordinator commits after impl-critic APPROVE)

## §4 Acceptance criteria (gates before commit)

1. **M14 mode 1 cached rebuild byte-identical at `payouts_by_spin_type` key**: pre-C2 vs post-C2 diff — zero non-volatile diffs at that specific subkey + zero diffs at any other player_impact subkey
2. **M275 mode 1 cached rebuild byte-identical at same**
3. **M37 mode 1 cached rebuild byte-identical at same** (D-archetype regression check)
4. **M272 mode 1 cached rebuild byte-identical at same** (B-archetype regression check)
5. **payouts_by_spin_type SCHEMA_VERSION still == 1** (assert in plugin file)
6. **Plugin extract() actually called** during the chunk merge loop (no longer no-op; verifier can grep + inspect parse_state)
7. **payout_id_by_spin_type_total / payout_id_win_by_spin_type_total** accumulators REMOVED from PIA main() (grep proves)
8. **effective_analyzer_version** for M14 mode 1 differs from C1 ship (ae6b79a) and same algo verifies on M37 mode 1
9. **All tests still green**:
   - `tests/analyzer/` 58 tests still pass (C1 infrastructure not touched)
   - `tests/backend/test_wave_2c_universal_features.py` 69/1 still pass
   - No new regressions in broader suite (12 pre-existing failures still 12)
10. **Inject-bug → red → revert → green** per `memory feedback_enumerate_safety_paths.md`: tester picks 1-2 sensitive code paths in the new plugin extract/reduce/emit and proves the new test catches a regression

## §5 Memory feedback files this phase MUST honor

- `memory/feedback_subprocess_import_suicide_and_module_globals.md` — plugin emit must not introduce import-time I/O
- `memory/feedback_no_silent_swallow.md` — **important: C1 critic flagged that the outer `except Exception: pass` in extract/reduce blocks could swallow Pattern-B plugin bugs**. C2 is the first phase where extract/reduce actually do work. If a plugin extract() crashes, that should reach `summary["feature_errors"]` per the C1 mechanism, NOT get swallowed by a blanket except. **Implementer must verify** the outer except is removed OR replaced with the same `feature_errors` capture pattern that C1 ships for emit() failures
- `memory/feedback_invariant_with_fallback_hides_drift.md` — C2 plugin keeps the existing payouts_by_spin_type aggregation logic identically; no fallback-bucket drift
- `memory/feedback_enumerate_safety_paths.md` — inject-bug protocol mandatory
- `memory/feedback_perf_claim_needs_e2e_event_stream.md` — verifier subprocess-against-cached-fixture mandatory
- `memory/feedback_md5_granularity_and_stamping.md` — per-mode hash preserved
- `memory/feedback_adversarial_self_review.md` — critic's job
- `memory/feedback_no_parallel_panel_impl.md` — N/A (no frontend in C2)

## §6 Claims the verifier + critic must check

| Claim | Verification |
|---|---|
| M14 cached rebuild byte-identical at payouts_by_spin_type | Spawn subprocess pre + post C2; diff that subkey |
| M275 cached rebuild byte-identical at same | Same on M275 |
| M37 + M272 cached rebuild byte-identical | Same on D + B archetypes |
| Plugin extract() actually invoked | Add a temporary debug counter inside extract; smoke run shows non-zero count |
| Inline accumulators removed from PIA main() | grep `payout_id_by_spin_type_total` + `payout_id_win_by_spin_type_total` in PIA — count should drop |
| Inline construction block removed from PIA main() | grep the line range from `01_pipeline_map` — block gone |
| Outer except in extract/reduce removed or replaced | grep `except Exception:\s*pass` near extract/reduce call site; verify replaced with feature_errors capture |
| effective_analyzer_version flips again | compute_effective_version_for_machine before + after; confirm different from ae6b79a |
| payouts_by_spin_type SCHEMA_VERSION unchanged | grep + assert SCHEMA_VERSION == 1 |
| Plugin imports clean | python -c "import fresh_slotlab.analyzer.features.payouts_by_spin_type" |
| PIA importable | python -c "import fresh_slotlab.player_impact_analyzer" |

## §7 Files implementer expected to touch

Modified:
- `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` (Pattern A → Pattern B)
- `fresh_slotlab/player_impact_analyzer.py` (delete inline block + accumulators; possibly small refactor to expose `summary["player_impact"]["spin_type_breakdown"]` BEFORE plugin emit loop runs, if it isn't already there — check `01_pipeline_map §7 Dependency A`)

NEW:
- `tests/analyzer/test_c2_payouts_by_spin_type_pattern_b.py` — Pattern-B plugin unit tests (extract per-chunk, reduce across chunks, emit produces expected summary key, ctx.effective_bet_for_rtp consumed)
- `tests/analyzer/test_c2_byte_identical_m14.py` — focused byte-identical at payouts_by_spin_type subkey on M14 mode 1
- `tests/analyzer/test_c2_byte_identical_m275.py` — same on M275
- `tests/analyzer/test_c2_byte_identical_m37.py` — same on M37
- `tests/analyzer/test_c2_byte_identical_m272.py` — same on M272 (if cached chunks exist; skip otherwise)

NOT touched (C1 infrastructure stable):
- `pipeline_context.py` / `parse_state.py` / `topo_sort.py` / `_base.py`
- 3 other plugins (bankruptcy_simulation / multiplier_profile / reel_marginal_by_spin_type) — those carve in later phases

## §8 Process (per docs/ARCH_TEAM_PROCESS.md §9.7)

1. Coordinator → impl-implementer with this brief → wait completion
2. Coordinator → impl-tester with implementer summary → wait
3. Coordinator → impl-verifier with both summaries → wait
4. Coordinator → impl-critic with all three summaries + commit message draft → wait
5. Verdict → loop back / approve / commit
6. impl-committer pre-commit gate → coordinator commits

## §9 Commit message draft template

```
refactor(analyzer): C2 — F3 payouts_by_spin_type Pattern A → Pattern B

Phase C2 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md.
Plugin now owns the payouts_by_spin_type aggregation (was inline in PIA
main()). No JSON output shape change — Pattern A→B is a pure refactor.

Changes:
- payouts_by_spin_type.py: Pattern A no-op → Pattern B real implementation
  - extract() reads chunk_dict["payout_id_by_spin_type"] + payout_id_win_by_spin_type
  - reduce() merges (pid, st_int) → (hit, win) across chunks
  - emit() consumes ctx.effective_bet_for_rtp + writes summary key
- PIA main(): inline payouts_by_spin_type construction block deleted;
  payout_id_by_spin_type_total + payout_id_win_by_spin_type_total
  accumulators moved into plugin reduce()
- Outer except Exception:pass in extract/reduce blocks: [verify + describe]

Carry-forwards still pending:
- (from C1 critic) analyzer_init_error JSON-disk write
- (from C1 critic) DECLARED_DEPS RuntimeError consistent treatment

## Verified happy path
- [from tester+verifier byte-identical runs]

## Verified failure paths
- [from inject-bug cycles + plugin extract() error → feature_errors path]

## Not verified
- [list]

## Tests added
- [list new test files]
```

## §10 Sequencing note

C2 is the first carve. After this, C3 will *add* fields to payouts_by_spin_type (shape / cols / paylines / notes), bumping SCHEMA_VERSION to 2. So C2 must leave the plugin clean and extensible (e.g. don't hardcode the field set; design the accumulator to be extensible by C3).