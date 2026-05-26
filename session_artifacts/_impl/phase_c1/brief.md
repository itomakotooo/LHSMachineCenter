# Phase C1 — impl-* team brief

> **Date**: 2026-05-25
> **Coordinator**: main session
> **Authoritative spec**: `session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md`
> **Phase**: C1 (first of 7 — C1 / C2 / C3 / **C3.5** / C4 / C5 / C6 per `07_decision §7`)
> **Commit scope**: one logical commit

---

## §1 Phase C1 purpose (one sentence)

Wire the analyzer plugin lifecycle so that `extract()` actually fires per chunk and `emit()` receives a `PipelineContext` 3rd parameter — without changing any visible analyzer output.

## §2 What this phase ships

Per `04_v3 §7.2` (Phase C1 deliverables — read in spec):

1. **`PipelineContext` dataclass** in `fresh_slotlab/analyzer/pipeline_context.py` (NEW FILE, outside `core/`).
   - Frozen dataclass, fields per `04_v3 §4.3`:
     - `effective_bet_for_rtp: float`
     - `total_spins: int`
     - `total_paid_sessions: int`
     - `total_paid_spins: int`
     - `clamp_pending_robots_total: int`
     - `robots_with_pending_cycle: int`
     - `mechanism_registry: MechanismRegistry`  (placeholder class for now — C4 fills detection logic; C1 ships empty registry)
     - `manifest: dict[str, Any]`  (v3 Fix 2 addition — resolved per-mode manifest)

2. **`AnalyzerFeature.emit()` signature change** in `fresh_slotlab/analyzer/features/_base.py`:
   - `def emit(self, final_acc, summary: dict, ctx: PipelineContext) -> None`
   - All 4 existing Pattern-A plugins (`payouts_by_spin_type`, `reel_marginal_by_spin_type`, `bankruptcy_simulation`, `multiplier_profile`) must accept the new `ctx` parameter even though they don't use it yet.

3. **`AnalyzerFeature.extract()` actually wired** at PIA `main()` merge loop. Per `01_pipeline_map.md §6`: today `extract()` is never called. C1 must:
   - Add `parse_state: ParseState` dataclass to `fresh_slotlab/analyzer/parse_state.py` (NEW) — minimum fields per the chunk-level state that plugins might need (designer hasn't fully specified — make a sensible minimum + extensible)
   - Add the per-chunk call site: `for _feat in sorted_features: _accs[fid] = _feat.reduce(_accs[fid], _feat.extract(parse_state, chunk_dict))` somewhere in the merge loop
   - Pattern-A plugins return `{}` from extract — no behavior change

4. **`DECLARED_DEPS` ClassVar** on `AnalyzerFeature` ABC:
   - `DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()`
   - All 4 existing plugins: `DECLARED_DEPS = ()` (no deps for now)

5. **Topological sort via Kahn's algorithm** in `fresh_slotlab/analyzer/topo_sort.py` (NEW or inline in `feature_registry.py`):
   - Input: `ALL_FEATURES` list with their `DECLARED_DEPS`
   - Output: sorted list, dep-providers before dep-consumers
   - Tie-breaker: alphabetical by `FEATURE_ID` (deterministic)
   - Raises `PluginCyclicDependencyError` on cycle
   - Raises `PluginMissingDependencyError` if a declared dep is not registered

6. **Exception surfacing** per `04_v3 §4.3.X`:
   - PIA `main()` wraps the sorted emit loop in try/except for the two new exception classes
   - On failure: write `summary["analyzer_init_error"] = {type, message, dep_graph_snapshot}`, log to stderr at ERROR level, return non-zero exit code so backend marks run `failed`
   - DO NOT silently fall through — per `memory feedback_no_silent_swallow.md`

7. **3 import sites updated for any new file** per `04_v3 §15.5`:
   - `fresh_slotlab/player_impact_analyzer.py:4816-4827` (both try/except blocks: package + script mode)
   - `fresh_slotlab/analyzer/versioning.py:165-176`
   - `scripts/validate_manifests.py:43-47`
   - If C1 introduces a new plugin (it doesn't — only ABC + infrastructure), this gate fires. C1 doesn't ship new plugins so this gate is informational for C2+.

## §3 What this phase MUST NOT do

- Do NOT change any visible analyzer output. M14 cached rebuild diff must be byte-identical.
- Do NOT carve any of F1-F9 inline aggregation blocks. That's C2-C6.
- Do NOT populate `mechanism_registry` with real detection logic. Placeholder class only.
- Do NOT change `summary` schema (no new top-level keys except `analyzer_init_error` which only appears on error paths).
- Do NOT touch frontend.
- Do NOT delete legacy `analyzer_version` field (kept for backward-compat).

## §4 Acceptance criteria (gates before commit)

Per `04_v3 §15.5` C1 row + v3 additions:

1. **M14 cached rebuild byte-identical**: `python -m fresh_slotlab.player_impact_analyzer --from-cache --machine M14 --mode 1` produces `summary.json` byte-identical to current production output (use existing report under `reports/M14/mode_1/versions/<latest>/player_impact_summary.json` as ground truth; diff except for `report_id` / `run_id` / timestamps).
2. **M275 cached rebuild byte-identical**: same on M275 mode 1 (uses BCM family — verifies C1 doesn't accidentally break the more complex case).
3. **BankruptcySimulation byte-identical**: per `04_v3 §15.5` v3 row — confirm `summary["player_impact"]["bankruptcy_simulation"]` is byte-identical (this is the existing Pattern-B plugin that survives the signature change; sensitive to the (None, summary) → (None, summary, ctx) transition).
4. **Topo sort works**: write unit test in `tests/analyzer/test_topo_sort.py` covering: 4 plugins no deps → returns alphabetical order; deps form chain → returns chain order; cycle → raises PluginCyclicDependencyError; missing dep → raises PluginMissingDependencyError.
5. **PluginCyclicDependencyError actually surfaces**: inject test that registers a cyclic plugin pair; assert `summary["analyzer_init_error"]` present + stderr logged + rc != 0.
6. **`effective_analyzer_version` flips correctly**: since `_base.py`, `feature_registry.py` (or wherever topo sort lives), and 4 plugin files all change source, all 253 machines declaring any of the 4 features will see `effective_analyzer_version` change. M14 / M275 / M37 (vanilla) verified before-after delta.

## §5 Memory feedback files this phase MUST honor

These are non-negotiable invariants — implementer + tester + verifier + critic each must check their work against these:

- `memory feedback_subprocess_import_suicide_and_module_globals.md` — no import-time I/O; new files must be import-safe
- `memory feedback_md5_is_a_tag_not_a_destruction_signal.md` — hash changes don't trigger destruction
- `memory feedback_md5_granularity_and_stamping.md` — per-mode hash; delegate paths re-stamp
- `memory feedback_no_silent_swallow.md` — analyzer_init_error must surface
- `memory feedback_enumerate_safety_paths.md` — inject-bug verification mandatory for any new test
- `memory feedback_perf_claim_needs_e2e_event_stream.md` — verifier must spawn real subprocess against cached fixture, not just unit test
- `memory feedback_no_parallel_panel_impl.md` — N/A C1 (no frontend); applies in C2+
- `memory feedback_adversarial_self_review.md` — critic's job
- `memory feedback_arch_team_process.md` — this is the impl phase of the work arch-* team designed
- `memory feedback_impl_team_required.md` — this phase MUST go through full impl-* loop

## §6 Claims the verifier + critic must check

After implementer + tester complete:

| Claim | Verification |
|---|---|
| M14 cached rebuild byte-identical | Run analyzer pre + post C1 against cached chunks; diff JSON |
| M275 cached rebuild byte-identical | Same |
| BankruptcySimulation behavior unchanged | Same scope, focus on bankruptcy_simulation key |
| Topo sort correctly orders | Run all 4 plugins through; assert alphabetical order today (no deps) |
| analyzer_init_error surfaces on cycle | Run with injected cyclic plugin; check summary + stderr + rc |
| effective_analyzer_version flips | `from fresh_slotlab.analyzer.versioning import compute_effective_version_for_machine; print(compute_effective_version_for_machine("M14", 1))` pre + post |
| No new top-level summary keys (other than analyzer_init_error on error path) | grep summary.json key set diff |
| Pattern-A plugin emit signature accepts ctx | Test imports + calls with (None, {}, fake_ctx); no TypeError |
| PIA still importable | `python -c "import fresh_slotlab.player_impact_analyzer"` |
| ParseState used somewhere | grep parse_state in main loop |

## §7 Files implementer expected to touch

New:
- `fresh_slotlab/analyzer/pipeline_context.py` (PipelineContext dataclass + MechanismRegistry placeholder)
- `fresh_slotlab/analyzer/parse_state.py` (ParseState dataclass)
- `fresh_slotlab/analyzer/topo_sort.py` (Kahn's algo + 2 exception classes) — or inline in feature_registry.py
- `tests/analyzer/test_topo_sort.py`
- `tests/analyzer/test_pipeline_context.py`
- `tests/analyzer/test_c1_byte_identical_m14.py`
- `tests/analyzer/test_c1_byte_identical_m275.py`
- `tests/analyzer/test_c1_init_error_surfacing.py`

Modified:
- `fresh_slotlab/analyzer/features/_base.py` (emit signature + DECLARED_DEPS ClassVar)
- `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` (emit signature)
- `fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py` (emit signature)
- `fresh_slotlab/analyzer/features/bankruptcy_simulation.py` (emit signature; verify final_acc=None semantic safe)
- `fresh_slotlab/analyzer/features/multiplier_profile.py` (emit signature)
- `fresh_slotlab/player_impact_analyzer.py` (extract() call site; topo sort + emit loop replacement; try/except for new errors; PipelineContext construction call site)
- `fresh_slotlab/analyzer/feature_registry.py` (maybe — if topo sort lives here)

## §8 Process (per docs/ARCH_TEAM_PROCESS.md §9.7)

1. Coordinator → impl-implementer with this brief → wait completion
2. Coordinator → impl-tester with implementer's summary → wait
3. Coordinator → impl-verifier with both summaries → wait
4. Coordinator → impl-critic with all three summaries + commit message draft → wait
5. Verdict:
   - APPROVE → coordinator commits
   - APPROVE-WITH-FIXES → loop 1-4 with fix list
   - REJECT → loop 1-4 with major rework

Each agent writes its summary back; coordinator passes summaries forward.

## §9 Commit message draft template (for impl-critic to review)

```
refactor(analyzer): C1 — wire extract() + PipelineContext + topo-sort + dep classes

Phase C1 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_v3.md.

Plumbing only — no visible analyzer output change. M14 + M275 cached
rebuilds byte-identical pre/post.

- Add PipelineContext dataclass (effective_bet_for_rtp, total_spins,
  total_paid_sessions, total_paid_spins, clamp_pending_robots_total,
  robots_with_pending_cycle, mechanism_registry placeholder, manifest)
- Add ParseState dataclass for plugin extract() input
- Wire AnalyzerFeature.extract() call site in PIA main() merge loop
- Add DECLARED_DEPS ClassVar to ABC + Kahn topological sort + 2 exception
  classes (PluginCyclicDependencyError, PluginMissingDependencyError)
- Change emit() signature to (final_acc, summary, ctx); 4 existing
  plugins updated to accept ctx (none use it yet)
- analyzer_init_error surfacing path (summary key + stderr + non-zero rc)
- BankruptcySimulation verified byte-identical under new signature
- effective_analyzer_version flips for 253 machines (expected, by design)

## Self-critique (adversarial review)
[impl-critic fills this section before commit]

🤖 Generated with Claude Code
```

## §10 Concrete brief for impl-implementer (first invocation)

The first agent (impl-implementer) gets this brief as its prompt. Coordinator will spawn it next.