# Architecture Review — Handoff to Implementation

> **You are starting the implementation pass.** The architecture review is done. This file tells you what to read, what to build, and what decisions are already made vs left open.

---

## §1 Status

- **Architecture review**: ✅ COMPLETE (5 iterations, 8 commits on branch `arch/console-refactor`)
- **Reviewer verdicts**: both APPROVE-WITH-REVISIONS; all v4 substantive concerns RESOLVED; 6 inline patches in `07_decision_v5.md`
- **0 cases broken** across all 5 iterations
- **Empirical validation**: Layer 4 algorithm tested against real M274 data (PASS) + synthetic dispatch routing bug (CAUGHT)
- **Branch**: `arch/console-refactor` from `collab/dev`; HEAD commit `aac25ce`; 19 artifacts in `session_artifacts/_arch/`

---

## §2 What to read first (in this order)

1. **`07_decision_v5.md`** — ship summary + 6 inline patches (P1-P6). Start here.
2. **`04_architecture_proposal_v5.md`** (1402 lines) — the main spec.
3. **`00_brief.md`** + **`_v2/v3/v4/v5_addendum.md`** — user goals + decisions per iteration. Skim §1 of each addendum to understand the framing shifts.
4. **`01_pipeline_map.md`** + **`02_taxonomy.md`** + **`03_coupling_audit.md`** — Wave 1 evidence. Designer cited these throughout.
5. **`05_critique_v5.md`** + **`06_validation_v5.md`** — final reviewer notes (other vN files are historical iteration context).

---

## §3 What you're building (high-level)

A refactored `rawdata → analyzer → console` pipeline that achieves:

**Core mechanism** (the user's primary ask):
- Adding a new machine or new feature plugin only invalidates the reports of machines that actually use that plugin
- Computed via per-machine manifest + hash composition: `effective_analyzer_version = sha256(base_hash || sorted(feature_hashes_M_uses) || mode)[:12]`

**Operator diagnostic** (the user's secondary ask):
- Console is the operator's (策划) tool to find production-machine configuration mistakes
- 4-layer RTP integrity gate either produces correct RTP OR emits explicit per-machine error
- No silent fallback to wrong numbers

**Variants** (handled correctly):
- 166 variants of 26 underlying machines; variants share analyzer parsing + diagnostic completeness with underlying
- Per-variant report storage; per-machine + override completeness mechanism

**Prod / virtual console consolidation**:
- Eliminate duplicate md5 + summary + session-CI + t-critical + inference-trigger helpers (currently 6 duplications across `app.py` ↔ `virtual_app.py`)
- Single `create_app` factory already shared (good); only helper-level dedup needed

---

## §4 Phase 1-6 deliverables (implement in order)

Phase order is **strict** — each phase has dependencies on the previous. Each phase has a rollback path. See `04_architecture_proposal_v5.md §6` for full detail.

### Phase 1 — Foundation
- Fix 5 mapper §5 pre-Phase-1 blockers: 3-invocation-style parity test / 3 summary md5 writers reconciled / frontend probe location documented / `_classify_chunks` historical semantics spec'd / compareReports cache-bust race fix
- Dedup 6 duplications (md5 lookup × 2 / summary patcher × 2 / session-CI × 2 / t-critical table × 2 / inference-trigger × 2 / RAWDATA_ROOT module global × 11 refs)
- Pure-function extraction + module-global → instance attribute migration

### Phase 2 — Slice the analyzer + forcing function
- Slice `fresh_slotlab/player_impact_analyzer.py` (8176 lines) into base + feature plugins
- Define `AnalyzerFeature` Protocol + `feature_registry.ALL_FEATURES`
- Onboard the 12 known-complex machines as forcing function (M21/M260/M268/M279/M274/M113/M11/M250/M108/M65/M67/M120)
- Build RTP integrity gate code (all 4 layers, warn-only mode by default)
- Implement Layer 4 Step A/B/C per `04_v5 §9.4` + `07_decision_v5 P1` (per-(machine, mode) `layer4_applicable`)

### Phase 3 — Per-machine manifests + clean-break cutover
- Write 421 machine manifest files at `slot_designer/configs/machine_manifests/<M>.json`
- Per `07_decision_v5 P4`: 46 Day-1 strict candidates start `console_diagnostic_complete: true` (SC-Vanilla 45 + M274). Other machines start `false`.
- **§6.3.3 item 0 GATE**: before any Day-1 flip, run `rtp_integrity.py --machine M --mode N` against latest cached chunks; all 4 layers PASS or candidate drops to Day-2 pending QA
- Clean-break cutover: all 2030 historical runs + 1007 (machine, mode) pairs invalidated; no NULL semantics; users see fresh reports only
- Update `compute_code_md5` → `effective_analyzer_version` per machine + mode

### Phase 4 — Frontend renderer registry + schema versioning
- Frontend gets per-renderer registry indexed by schema version
- SCHEMA_VERSION enforcement in CI (per `04_v5 §5.4`)
- Renderers gracefully degrade on missing fields (per existing `7e5fe32` pattern)

### Phase 5 — Policy flip
- For machines with `console_diagnostic_complete: true`: integrity-gate failure flips from warn → error
- Per `07_decision_v5 P2`: Day-2 candidates follow same flip criteria as any `complete: false` machine (no special timeline)

### Phase 6 (optional) — Final consolidation
- Address any md5/summary/CI helpers not deduped in Phase 1
- Implementation team can skip if Phase 1 was thorough

Each phase rollback: revert that phase's commits; previous phase's state remains functional.

---

## §5 Decisions already made (do NOT re-debate)

These are decided. If implementation needs change, user must explicitly authorize:

| Decision | Source |
|---|---|
| Per-machine manifests (no default cluster tier) | addendum v2 §1.5 user clarification |
| Clean-break migration (delete all historical reports at cutover) | addendum v2 §1.2 user clarification |
| Variants share manifest with underlying (eager cascade) | addendum v3 §3 #1 user clarification |
| Operator-diagnostic framing (not internal correctness) | addendum v3 §1 user clarification |
| Layer 4 Skip approach for trigger-session machines | Designer v5 chose (b); trade-off documented in v5 §9.4 |
| Hash algorithm | unchanged since v2 |
| 6-phase ordering | unchanged since v3 |

---

## §6 Open decisions for implementation team (designer left to you)

1. **Mirror approach for trigger-session machines** (v5 §8.14 future option): currently Skip — trigger-session machines lose Layer 4 coverage. If implementation determines Layer 4 coverage is critical for those machines, implementation team designs Mirror approach (Step B also calls `compute_trigger_sessions`).
2. **Layer 4 perf measurement**: ~3s/machine claim is theoretical. Measure actual perf during implementation; tune if perf differs significantly.
3. **Quarterly QA review cadence** for stale variant overrides: cadence is operational; implementation/ops decides.
4. **CI enforcement specifics** for SCHEMA_VERSION + manifest validation rules: framework provided, implementation specifics (CI runner config etc.) is implementer's call.

---

## §7 Out of scope

These are NOT part of implementation pass:
- Per-machine `slot_designer/machines/<M>/` spec.json edits (each machine is byte-locked per universal rule §1.1)
- Upstream rawdata format changes (treated as immutable)
- UI / visual redesign (only data-layer architecture)
- New machine onboarding workflow (`slot_designer/ONBOARDING_PROCESS.md` is the existing flow — slot-* team handles)
- 80% spin_type_category threshold (reverted earlier, stays out)

---

## §8 Test deployment plan

This architecture review produced **0 production tests**. Implementation team builds:

1. **`manifest_lint.py`** — validates all 421 manifest files (11 rules from v5 §5.5)
2. **`rtp_integrity.py`** — runs all 4 layers against a machine + mode; CLI: `--machine M --mode N`; exit code 0 = PASS, nonzero = FAIL with per-layer reason
3. **Layer 4 unit tests** — synthetic mismatch fixtures (Validator v4 already proved the algorithm catches these)
4. **`test_manifest_schema.py`** — validates manifest schema against pydantic / jsonschema
5. **`test_hash_composition.py`** — verifies hash algorithm correctness against known fixtures
6. **Integration test**: spawn analyzer subprocess + verify report regeneration only invalidates expected machines on plugin edit
7. **Regression**: existing `tests/backend/test_analyzer_st_split.py` (10 tests) should continue passing

Validator v5 walks confirmed all 7-case scenarios; implementation team translates those walkthroughs into actual test fixtures.

---

## §9 Implementation team setup

Suggested agent assignments (per `slot_designer/ONBOARDING_PROCESS.md` + `docs/ARCH_TEAM_PROCESS.md`):

- **Phase 1 / Phase 2**: `slot-implementer` (existing agent type; tools: Read/Edit/Write/Bash) or `general-purpose` for cross-cutting items
- **Phase 3 manifest writing**: bulk task; can be `general-purpose` with template + iteration over `configs/machines.json`
- **Phase 4 frontend**: `slot-implementer` + main-session preview verification (per past M31 lessons — frontend changes require `preview_*` tool verification before commit)
- **Phase 5 / 6**: `slot-implementer`

Each phase, suggested workflow:
1. Implementer agent reads relevant section of `04_v5.md` + `07_decision_v5.md`
2. Produces code change
3. Coordinator (main session) preview-verifies frontend / pytest-verifies backend
4. Commit with adversarial self-critique (per `slot_designer/WORKFLOW.md`)

---

## §10 User context (preserve verbatim)

User's stated goals throughout this review (verbatim quotes; these guided every decision):

> "添加新机台,有一些新 feature,更新分析器,会不会导致我所有的 report 失效?但有没有失效必要?"

> "理解目前的 rawdata-分析器-网页 console 展示的框架,以现有机台数据了解大致机台之间的相关性程度,合理设计和重构,做到利用相关性,支持独特性。为以后持续添加机台做准备。"

> "虚拟 console 按理不应该有独立的解析和展示逻辑,从框架设计来讲完全应该公用真机 console 的这部分内容。"

> "rtp 分析必须健壮。即使并没有为所有机台实现具体的分析功能,但全局拉取必须保证 rtp 正确或者对于指定机台的报错。"

> "console 的诉求是帮我分析真机数据,找到问题并优化"

> "rawdata 错的意思不是机台的逻辑和数据错误,就是比如策划 rtp 配错了,手滑了"

> "其实所有的机台都有可能有这种程度的复杂性。所以你要做的不是剩下的机台都是 ok 的,而是保持警惕"

User does not debate technical details ("我不会回答你的技术细节问题,全权由你负责"). Implementation team makes technical calls; user signs off on business / scope changes only.

---

## §11 Branch + commit policy

- **Current branch**: `arch/console-refactor` (off `collab/dev`)
- **Commits**: 11 on this branch (design + review iterations). All are markdown-only; no code changed.
- **Suggested for implementation**: continue on `arch/console-refactor` for early phases; merge to `collab/dev` when Phase 1 ships cleanly (or whenever user prefers)
- **Per-phase commits**: each phase has independent commits per `WORKFLOW.md` standard (verified happy path / failure paths / not verified / tests added / self-critique)

---

## §12 Stop criteria for implementation

Implementation is complete when:
1. All 421 machines have manifests
2. All 6 phases ship + their rollback paths verified
3. `rtp_integrity.py` runs clean on all 46 Day-1 candidates
4. Frontend renders against the new schema correctly
5. Adding a synthetic new plugin to one machine demonstrably invalidates only that machine's hash (the user's primary ask, verified empirically)
6. Backward compat: clean break at Phase 3 cutover; no historical-report-rebuild concern

Implementation surfaces issues not covered by design — that's normal. New findings → spawn arch-* team for re-review if structural, otherwise patch in place.

---

## §13 Cross-references

- Process: `docs/ARCH_TEAM_PROCESS.md`
- Memory: `memory/feedback_arch_team_process.md`
- All 19 architecture review artifacts: `session_artifacts/_arch/`
- Branch HEAD when handoff prepared: commit `aac25ce` (Phase 4 v5 — 07_decision_v5)

Good luck. Build it.
