# Ticket P1-B4 — Consolidate `t_critical_95` table (THREE sources)

> Phase 1 / Batch 1c (Dedups). First ticket to run through the impl-* team — proof-of-concept for the team flow per `docs/IMPL_TEAM_PROCESS.md`.

---

## §1 Ticket scope

Consolidate the t-critical-95 lookup table to **one canonical source**: `fresh_slotlab/sampler.py`. Drop the two diverging duplicates in `fresh_slotlab/player_impact_analyzer.py` and `slot_designer/core/backend/virtual_analyzer.py`. Make all three callers (analyzer, sampler, virtual_analyzer) import the canonical function.

Files expected to change:

- `fresh_slotlab/player_impact_analyzer.py` — drop the local `t_critical_95` definition at lines 965-997; replace with `from fresh_slotlab.sampler import t_critical_95`
- `slot_designer/core/backend/virtual_analyzer.py` — drop `_T_CRITICAL_95_TABLE` + `_t_critical_95` at lines 262-275; replace with `from fresh_slotlab.sampler import t_critical_95` (and update internal callers `_ci_halfwidth_pp:290`, etc. to call `t_critical_95(...)` directly)
- `fresh_slotlab/sampler.py` — no functional change to `t_critical_95:139-190`; add a docstring marking it canonical + cross-referencing this ticket
- `tests/backend/test_t_critical_table_canonical.py` (new) — regression tests per §3 contracts

**No** changes to: hash composition (`compute_code_md5`), `summary.code_md5` / `summary.config_md5` content, session-halfwidth-pp formula (separate ticket P1-B3), chunk-level CI half-width formula. This is a pure-callsite consolidation.

---

## §2 Brief sections cited

- `session_artifacts/_arch/01_pipeline_map.md §4` row 4 ("t-critical table") — identifies the divergence
- `session_artifacts/_arch/03_coupling_audit.md §4.5` "Duplicate primitives (real-vs-virtual coupling)" — lists `t_critical_95` redefined in player_impact_analyzer.py + virtual_analyzer.py
- `session_artifacts/_arch/04_architecture_proposal_v5.md §6.1` — Phase 1 dedup goals
- `session_artifacts/_arch/08_handoff.md §4 Phase 1` — "6 duplications (... t-critical table × 2 ...)"
- `session_artifacts/_impl/phase1/PHASE_1_TICKETS.md` P1-B4 row — entry-level summary
- Memory `feedback_invariant_with_fallback_hides_drift.md` — comment claiming "matches the formula used by the real analyzer" is the textbook "invariant + fallback hides drift" anti-pattern. Today the comment in virtual_analyzer.py:280-283 says "matches the formula used by the real analyzer" but the underlying tables DIFFER on df 11-19, 21-29, 31-1000+. Dedup eliminates the silent disagreement.
- Memory `feedback_no_parallel_panel_impl.md` — reuse the canonical sampler implementation, don't re-implement

---

## §3 Contract (testable invariants)

After this ticket lands:

### C1 — Single source of truth
Both `fresh_slotlab/player_impact_analyzer` and `slot_designer/core/backend/virtual_analyzer` import `t_critical_95` from `fresh_slotlab.sampler`. No other definition of `t_critical_95` exists anywhere in the repo. Verifiable: `grep -nR "def t_critical_95\b\|_T_CRITICAL_95_TABLE\b\|def _t_critical_95\b" .` returns exactly one definition (the canonical one in `sampler.py`).

### C2 — Value parity across df range 1..1200
For every integer `df ∈ [1, 1200]`, the canonical `t_critical_95(df)` returns a numerical value. Test asserts the call succeeds and returns a positive float for that range.

### C3 — Latent-divergence-fix proof
Before this ticket: `analyzer.t_critical_95(15)` ≈ 2.157 (linear interp 10→20); `virtual._t_critical_95(15)` = 2.131 (table); `sampler.t_critical_95(15)` = 2.131 (table). Two values disagreed by 0.026.

After this ticket: all three import sites return 2.131 for df=15. Test asserts the historical disagreement is gone:
- assert `t_critical_95(15) == 2.131` (canonical table)
- assert `t_critical_95(25) == 2.060` (canonical table, was interpolated by analyzer)
- assert `t_critical_95(80) == 1.990` (canonical table, was interpolated by analyzer and sentineled to 1.96 by virtual)

### C4 — Inject-bug TDD verification
Tester proves the regression test catches future drift:
1. Save the test as written
2. Apply a synthetic bug: edit `sampler.t_critical_95`'s table entry for df=15 from 2.131 → 2.222
3. Run the regression test — must go red on the df=15 assertion
4. Revert the synthetic bug
5. Run the test — must go green
6. Document the inject step in `03_tests.md` per `docs/IMPL_TEAM_PROCESS.md §5 invariant 5`

### C5 — All existing pytest passes
After the consolidation: `python -m pytest fresh_slotlab/ tests/ slot_designer/tests/ -x` (or whichever subsets the team picks) passes. In particular `slot_designer/tests/test_virtual_analyzer_ci_stop.py` (which exercises virtual `_ci_halfwidth_pp`) must continue passing — the underlying CI formula is unchanged; only the t-critical lookup is rerouted.

### C6 — Subprocess-mode verification
Per memory `feedback_perf_claim_needs_e2e_event_stream.md`: virtual_analyzer runs in subprocess mode under `_run_generate_report` and direct sampling. impl-verifier spawns the virtual_analyzer subprocess against an M14 mode 1 cached chunk and asserts the CI half-width output matches the value computed using the canonical `t_critical_95`. End-to-end, not just unit.

---

## §4 Out of scope

The following are NOT addressed by this ticket; create follow-up tickets if needed:

- **Session-halfwidth-pp consolidation** — `player_impact_analyzer.session_halfwidth_pp:1012-1034` and `virtual_analyzer._ci_halfwidth_pp:278-291` are functionally identical (same formula, different names) but are a separate ticket (P1-B3). Don't touch them here beyond updating the t-critical import.
- **Chunk-level CI half-width consolidation** — `sampler.compute_ci_halfwidth_pp:193-200` and `player_impact_analyzer.ci_halfwidth_pp:1000-1009` are separate impls; not in this ticket scope.
- **Adding new df values to the canonical table** — the canonical table is `sampler.py:139-190` as-is. Adding entries (e.g., df=200, df=500) is a separate change if needed.
- **scipy/numpy/statsmodels replacement** — the table-lookup-with-interpolation approach is intentional (per virtual_analyzer.py:259-261 comment "Keeps small-session CIs honest without dragging scipy in"). Don't replace with library calls.
- **Renaming `t_critical_95` → `t_critical_two_sided_95` or similar** — purely cosmetic; not in scope.
- **Reorganizing `fresh_slotlab/sampler.py`** — beyond adding a docstring to `t_critical_95`, leave sampler.py alone.

---

## §5 Rollback path

This ticket = one commit on `arch/console-refactor` (or whichever branch the user chooses). Rollback = `git revert <commit-sha>`. After revert:

- `analyzer.t_critical_95` is restored (its sparse table)
- `virtual._t_critical_95` is restored (its dense-up-to-30 table)
- `sampler.t_critical_95` is unchanged either way
- The new test file is restored to deleted state by the revert

No data migration, no schema change, no DB column. No downstream ticket depends on this ticket landing (the dedup independence in PHASE_1_TICKETS.md Batch 1c).

---

## §6 Risk + rollback notes

**Risk class**: LOW. Pure callsite consolidation; no formula change to behavior of `session_halfwidth_pp` / `_ci_halfwidth_pp` / `ci_halfwidth_pp`; the only behavior change is the value returned by `t_critical_95` for df ∈ [11-19, 21-29, 31-1000+]. That value change moves analyzer + virtual *toward* the canonical sampler table — which is the entire point of the dedup.

**Existing tests that may be affected**: any test that depends on the old (incorrect, divergent) t_critical values. impl-verifier runs full pytest suite (per §3 C5). If any existing test fails because it asserts the old divergent value, that test is testing the bug — flag in `04_verification.md`, do NOT silently update the test to match new value. Per memory `feedback_adversarial_self_review.md`: moving goalposts is a critic-flag offense. Main session decides whether to update the test (if the old assertion was indeed wrong) or to escalate.

**Subprocess-mode risk**: virtual_analyzer.py runs as a subprocess under `_run_generate_report` and direct sampling. Test must verify the subprocess path imports `t_critical_95` cleanly (no module-level side-effect cycle per memory `feedback_subprocess_import_suicide_and_module_globals.md`). impl-tester adds a subprocess-spawn smoke test if not already covered by `tests/backend/test_analyzer_e2e_md5_filter.py` or a sibling.

---

## §7 Suggested impl-* team workflow for this ticket

(Reproduced from `docs/IMPL_TEAM_PROCESS.md §6` for convenience.)

### Wave 1 (parallel, ~10-15 min total)

- `impl-implementer` — reads this brief + sampler.py:139-190 + analyzer:965-997 + virtual:262-291. Produces the 3-file dedup edit + `02_implementation.md`.
- `impl-tester` — reads this brief independently. Writes `tests/backend/test_t_critical_table_canonical.py` per §3 C1-C5 with inject-bug proof in `03_tests.md`.

### Wave 2 (parallel, ~10-15 min total)

- `impl-verifier` — reads full chain. Runs pytest full suite + spawns virtual_analyzer subprocess against M14 mode 1 fixture + asserts CI half-width round-trip. Writes `04_verification.md`.
- `impl-critic` — reads full chain. 5-10 stress questions including: "Did implementer accidentally delete the interp-fallback for df not in canonical table?" / "Does virtual subprocess import of sampler.py trigger any side effect?" / "Are any existing tests testing the OLD divergent value — did verifier flag them?" / etc. Writes `05_critique.md` with paste-ready `## Self-critique` section for commit message.

### Consolidation (main session)

Main session reads `04_verification.md` + `05_critique.md` → if verifier PASS + critic APPROVE → commits with critic's `## Self-critique`. Otherwise loop W1.

Expected end-to-end wall time: ~30-45 min (Wave 1 in parallel ~15 min + Wave 2 in parallel ~15 min + consolidation ~5-10 min).
