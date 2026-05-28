# 00 — Brief: Carry-forward Round 1 (A + D + E)

> **Date**: 2026-05-28
> **Coordinator**: main session
> **Topic dir**: `session_artifacts/_arch_carryforward_r1/`
> **Trigger** per `docs/ARCH_TEAM_PROCESS.md` §1: touches fleet-shared `fresh_slotlab/analyzer/` (Cluster A + D), changes error-handling contract (Cluster A). Cluster E is test-only but bundled for design coherence.

---

## §1 Task statement

3 cluster of analyzer-unbundle carry-forwards bundled into one arch-* design pass for efficiency:

### Cluster A — Unified error surfacing contract
3 disjoint error paths currently coexist (silent / in-memory / persistent). Unify to single contract: ALL analyzer errors → `summary["analyzer_init_error"]` (top-level), write_summary_json BEFORE SystemExit (try/finally), rc=1 + JSON dual signal.

Specific gaps closed:
- C1 critic carry-forward (a): `analyzer_init_error` set in memory but SystemExit fires before JSON write
- C1 critic carry-forward (b): `DECLARED_DEPS` missing-key raises uncaught RuntimeError outside the try/except path

### Cluster D — 4 small fleet-plugin fixes
- (d1) `paylines` list string sort wrong for 10+ payline machines (M14/M275/M37 unaffected; future machines bite) — sort by int with `-1` carve-out
- (d2) `trigger_target` alphabetical-first heuristic (M275 NewFreespin chosen by accident) — use mechanism_registry.scatter_marker_pids inverse mapping
- (d3) `trigger_target_confidence: "unique"` dead spec branch — emit when exactly 1 candidate feature
- (d4) `avg_bonus_payout` None vs 0.0 behavioral delta (None more accurate; downstream needs null-safe)

### Cluster E — Test refactor: dynamic effective_version assertions
5 test files have hardcoded effective_version hex values (e.g. `5c78f3834a1e`). Updated 3 rounds this carve. Replace with dynamic `compute_effective_version_for_machine()` calls + differential assertions ("M275 differs from M14 by exactly multiplier_wild contribution").

---

## §2 Scope

### In scope (Cluster A)
- `fresh_slotlab/player_impact_analyzer.py` (main(): error handling around emit loop; try/finally pattern; topo error path; DECLARED_DEPS check)
- `fresh_slotlab/analyzer/topo_sort.py` (PluginCyclicDependencyError + PluginMissingDependencyError surfacing)
- Existing C2 `_extract_error_*` → `feature_errors` path: confirm or unify

### In scope (Cluster D)
- `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` (d1 paylines sort)
- `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py` (d2 trigger_target + d3 unique confidence)
- `fresh_slotlab/analyzer/features/collect_mechanic.py` (d4 avg_bonus_payout)

### In scope (Cluster E)
- `tests/analyzer/test_c3_5_isolation_m275_only.py`
- `tests/analyzer/test_c3_5_m14_no_multiplier_wild.py`
- `tests/analyzer/test_c3_base_hash_flips_for_round_level_enrichment.py`
- (Possibly more — designer to enumerate)

### Out of scope
- Cluster B / C / G (separate arch rounds)
- core/parser.py (don't flip base_hash)
- pipeline_context.py / parse_state.py / _base.py (C1 infrastructure stable)
- web_console / auto_inspect / recovery / configs (concurrent session)
- 253 manifests (no manifest changes needed)

---

## §3 Constraints

### Hard invariants
- base_hash UNCHANGED `fa440e3eb5f6` (don't touch core/*.py)
- Per-machine isolation preserved (only declaring machines invalidate)
- 624 tests/analyzer/ remain pass post-each-cluster
- 8 gap closures from C-phase remain green (no regression)
- All M14 / M37 / M272 / M275 / M11 byte-identical except where the 4 D fixes intentionally change behavior

### Soft constraints
- Minimum-delta per cluster (no scope creep)
- All 3 clusters bundle into ONE commit OR 3 commits (designer recommends)
- Self-critique section in commit msg
- Follow memory feedback (`feedback_no_silent_swallow.md` is THE constraint for Cluster A)

### Memory invariants
- `feedback_no_silent_swallow.md` — Cluster A's primary motivation
- `feedback_arch_team_process.md` — this round
- `feedback_impl_team_required.md` — full impl-* loop after this
- `feedback_subprocess_import_suicide_and_module_globals.md` — error path can't import at top
- `feedback_md5_is_a_tag_not_a_destruction_signal.md` — error surfacing doesn't auto-delete reports

---

## §4 Goals (proposal must answer)

1. **Cluster A unified error contract**: exact schema for `summary["analyzer_init_error"]` (top-level keys); try/finally pattern in main(); migration of 3 existing paths (topo cycle / DECLARED_DEPS miss / extract() error via feature_errors); backward-compat for backend reading rc=1 only
2. **Cluster D 4 fixes**: per-fix code sketch + test coverage + inject-bug recipe for each
3. **Cluster E test pattern**: helper API design (compute_effective_version_for_machine usage); differential assertion pattern; migration of 5+ test files
4. **Commit grouping**: 1 commit or 3? Trade-offs?
5. **Phase ordering within Round 1**: A → D → E? E first (test foundation)? Bundle?
6. **Regression risk per cluster**: which existing tests break? What inject-bug catches the breakage?
7. **8-gap-closure invariant preservation**: prove each fix doesn't regress C-phase 8 gaps

---

## §5 Out-of-scope deferrals (will be Round 2/3)
- Cluster B (Mechanism Registry completion 6×3 tiers)
- Cluster C (F6 cleanup + Registry build position refactor)
- Cluster F (M37 root cause — handled separately as read-only investigation)
- Cluster G (Phase 4 frontend)
- Cluster H (full fleet verify campaign — needs script not arch design)

---

## §6 Reference artifacts

- `session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md` (C-phase spec)
- `session_artifacts/_arch_analyzer_unbundle/07_decision.md` (C-phase coordinator decisions)
- `session_artifacts/_impl/phase_c{1,2,3,3_5,4,5,6}/critique.md` (per-phase critic findings)
- `docs/ARCH_TEAM_PROCESS.md` §1-§7 + §9
- All memory files in scope per §3
