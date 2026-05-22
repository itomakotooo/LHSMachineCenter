# Deploy Review Brief — Internal Windows Server Deployment

> **Second use of `arch-*` 6-agent team** (per `docs/ARCH_TEAM_PROCESS.md` + `memory/feedback_arch_team_process.md`). All agents read this brief as the spec contract.
>
> **Date**: 2026-05-15
> **Trigger**: User wants to deploy current single-user-working `src/web_console/` to one internal Windows machine, serving <10 planners through browsers (intranet only).
> **Hard bound**: `memory/feedback_respect_existing_codebase.md` — **minimum-delta extension** on existing stack, NOT rewrite. Earlier in this same session I drifted into "use SQLite / waitress / portalocker / NSSM / nginx" tech-stack-replacement design; user pushed back ("我现在的本地console工程有大量的代码。你别瞎搞了"). All such replacement proposals are **withdrawn**. W1 must NOT pre-assume any tech stack.

---

## §1 Task

Review the **current console codebase** (`src/web_console/`, `fresh_slotlab/`, related infrastructure) and design a **minimum-delta extension** that:

- Deploys to one internal Windows machine, planners access via browser (intranet)
- Supports <10 concurrent planners (fetch + analyze) without breaking single-user-working baseline
- Adds **config upload** as new first-class concept (currently doesn't exist), with `(config_id, machine, mode, upstream_md5)` 4-tuple dedup key
- Supports **on-demand full-fleet refresh** (393 machines, hours/days runtime) with crash-recoverable progress; not 24/7
- Continuous-update friendly (no Docker)

Output: extension proposal (`04_deploy_*.md`) on top of existing stack, **not a rewrite**. **No code changes during this review — markdown only.**

---

## §2 Scope

### Extend / instrument (in scope)

- `src/web_console/backend/` — multi-user concurrency safety, config upload endpoint, fleet-refresh orchestration; identify endpoints that break under concurrency
- `src/web_console/frontend/` — config upload UI, fleet-refresh progress panel, no user-display
- `fresh_slotlab/` + `BatchRunManager` — current job management; gaps for crash-recoverable long-run
- `rawdata/` + sidecar — current dedup key (machine, mode, md5); add config_id as fourth axis
- `reports/` — tag stale when underlying rawdata removed; cross-config visibility
- `configs/machines.json` — fleet-default config source for full-fleet refresh

### Audit-only (catalog, don't redesign)

- Process model (backend / batch_worker / virtual_app spawning — relevant to multi-user isolation)
- Upstream fetch logic + rate-limit handling (multi-user must share single bucket)
- Sidecar `_chunks.json` / `chunks_by_md5` index (multi-user write contention?)

### Out of scope

- `slot_designer/` — per-machine onboarding tooling
- `MachineBuilder/` — xlsx build pipeline
- Frontend visual redesign
- Replacement of working stack components (server/db/framework). Keep what works. Only fill real gaps.

---

## §3 Current baseline (W1 to DISCOVER, NOT to assume)

User assertion: **local console is fully working single-user**. Variants fleet (393 machines) operational; rawdata/reports/chunks flow through existing pipeline.

**W1 agents must discover and document**:

- Backend server framework, port, dependencies, launch entry
- Frontend stack and build/serve mechanism
- Process spawn model: how `BatchRunManager` / `batch_worker` / `virtual_app` work
- Persistence today: SQLite? JSON files? in-memory?
- Auth/sessions today (likely none — confirm)
- Upstream rate-limit + fetch dedup mechanism today
- Where the gap is between "single-user works" → "multi-user works"

**W1 must NOT**:
- Assume tech stack replacement
- Propose new servers / dbs / frameworks
- Critique current architecture
- Design mitigations (that is W2)

W1 documents existing stack. W2 designer decides minimum-delta extension.

---

## §4 User goals (verbatim from 2026-05-15 session)

> "我准备把这个项目打包到我们公司内网服务器上，让策划在本地浏览器直接可以使用。"

> "需求1，策划将只会用到拉取真实环境的console。2，多名策划同时使用，共享report和rawdata数据。独立分析。3，部署方式方便我持续更新和部署。4，多名策划同时使用(拉取数据，创建报表)的健壮性和性能。5，能够长时间持续不间断的做全量拉取+分析。"

> "内网服务器就是一台装着windows的内网电脑。不需要用户身份，也不需要为每个用户记录他们的个人历史。"

> "rawdata和报表都共享。如果用户上传config来做指定config拉取，需要维护config和rawdata以及报表的关系。这部分功能当前版本也没有。但不需要维护用户和config的关系。"

> "技术细节我不懂，你别问我。但我可以给你提供技术向的用户需求。"

> "config不需要单独删除，跟着rawdata走就行了，rawdata是可以删除的。"

> "长跑都是全量拉取，只用服务端数据。"

> "长跑的意思是能支撑一次全量拉取，因为数据量很大。除非rawdata全部失效，不需要真正永远在跑。"

> "同一个config+同一个远程md5即可复用。"

> "我现在的本地console工程有大量的代码。你别瞎搞了。"

> "我现在本地console状态是单人完全可用。你应该基于这套框架扩展，然后实现刚刚新增的需求。"

---

## §5 Constraints (must hold during + after extension)

1. **Existing single-user functionality remains working** at every step. Single-user is baseline; multi-user is extension. Any regression unacceptable.
2. **No tech stack replacement without evidence**. Keep working components. Swap only if W1 + W2 prove a working component cannot meet multi-user / long-run.
3. **No user concept**: no user table, no session/cookie auth, no per-user history, no `user_id` anywhere.
4. **rawdata + reports globally shared**: anyone can trigger fetch on any cell; anyone can view any report.
5. **Config is permanent + tied to rawdata, not user**: no delete-config endpoint; config metadata persists as long as any related rawdata exists. Display name can duplicate; internal id = hash(content).
6. **rawdata is deletable**: cache management is first-class. Reports based on deleted rawdata stay but tag `underlying rawdata removed` (immutable historical snapshot).
7. **dedup key = `(config_id, machine, mode, upstream_md5)`**: same key, already-cached → reuse.
8. **Fleet refresh is on-demand one-shot**:
   - Anyone can trigger (no admin role); one full-refresh at a time; others attach to observe
   - Crash-recoverable: process death mid-run → restart → resume queue
   - Per-machine failure auto-retry + final skip
   - Server-side default config, not user-uploaded
   - Foreground ad-hoc fetch priority > full-refresh in shared upstream rate-limit bucket
9. **Target**: one Windows machine, intranet. No Docker, no multi-host.
10. **No silent failure**: any background task failure persists diagnostic to disk + surfaces to UI (per `memory/feedback_no_silent_swallow.md`).
11. **No cascade-delete**: removing rawdata removes only that rawdata + tags reports; doesn't cascade to reports/configs.

---

## §6 Goals (success criteria for W2)

A successful W2 proposal:

- **Documents current stack as-is** then identifies real gaps from "single-user" → "multi-user + config upload + long-run"
- **Proposes minimum-delta extensions** per existing component; new components only when no existing component can extend
- **Dedup invariant**: `(config_id, machine, mode, upstream_md5)` uniquely keys rawdata bucket; concurrent same-key fetch dedupes to one upstream call
- **Write-contention invariant**: chunk/sidecar/persistence writes serialize at per-cell granularity, not globally
- **Crash-recovery for long-run**: pseudocode for resume logic (queue persistence, in-flight state, startup recovery)
- **Rate-limit single-bucket**: all fetch paths share one token bucket with foreground priority
- **Report-stale invariant**: deleting rawdata flags reports as `underlying_removed=true` without deletion
- **Test plan covering 5 dims**: design-level invariants, impl-level unit/integration/e2e, deploy-smoke, runtime monitoring, regression防再踩 (per memory feedback files). Each invariant has matching test + inject-bug → red → revert → green verification listed
- **Migration phases**: each phase has clean revert + verification + deliverables. Phase 1 fully backward-compatible (single-user dev workflow unchanged).

---

## §7 Non-goals

- Implementing the proposal (next session)
- Replacing working components without W1 evidence
- Aesthetic / UX redesign
- Adding non-required features (no admin panel beyond refresh trigger/abort; no audit log beyond existing; no permission/role/quota)
- Auto-detecting "rawdata全部失效" (planner manually triggers full refresh)
- L3 staging environment procurement (test plan addresses staging design but not logistics)

---

## §8 Data availability + memory cross-refs

- All of `src/web_console/`, `fresh_slotlab/`, `slot_designer/`, `rawdata/`, `reports/`, `configs/` accessible for W1
- Prior arch review (00-07 in `session_artifacts/_arch/`) — different scope (fleet onboarding architecture); deploy review pivots to multi-user deployment
- Memory pointers:
  - `memory/project_internal_deploy_intent.md` — full requirement context (note: §"我自主决定的技术栈" is SUSPENDED pending W1)
  - `memory/feedback_respect_existing_codebase.md` — minimum-delta principle (hard binding for W1)
  - `memory/feedback_arch_team_process.md` — workflow definition
  - `memory/feedback_subprocess_import_suicide_and_module_globals.md` — multi-user concurrency landmines
  - `memory/feedback_md5_is_a_tag_not_a_destruction_signal.md` — cache delete semantics
  - `memory/reference_chunk_index_inverted_md5.md` — sidecar write concurrency reference
  - `memory/feedback_md5_granularity_and_stamping.md` — per-mode hash
  - `memory/feedback_no_silent_swallow.md` — runtime monitoring requirement
  - `memory/feedback_enumerate_safety_paths.md` — inject-bug verification process
  - `memory/feedback_upstream_throttle_ceiling.md` — per-IP rate limit
  - `memory/reference_sampling_api.md` — upstream endpoint + throughput
  - `memory/feedback_no_proactive_fetch.md` — dev side uses cache, no proactive upstream calls
  - `memory/feedback_perf_claim_needs_e2e_event_stream.md` — e2e subprocess testing requirement
  - `memory/feedback_integration_test_argv.md` — argv-level integration test requirement
  - `memory/feedback_error_branch_resets_all_state.md` — UI state reset on error
  - `memory/feedback_fasttimer_overlap_needs_oneshot.md` — polling overlap protection

---

## §9 Decisions baked in

(User authorized "技术细节我不懂，你别问我" — these are coordinator-level decisions, **subject to W1 findings overriding any pre-existing assumption**.)

- **Scope**: §2 above; minimum-delta over existing stack
- **Existing console code**: KEEP AS IS as baseline; W2 designer plan starts from current commit
- **Concurrency**: W1 (mapper / taxonomist / coupling-auditor) parallel; W3 (critic / validator) parallel
- **Additional agents** (deploy-planner / test-planner / deploy-critic / test-critic / implementation agents): NOT pre-spawned. Add later only if W1/W2 reveal distinct workstreams justifying them
- **Iteration policy**: W3 verdict REJECT or APPROVE-WITH-MAJOR → loop W2 (designer v2); minor revisions in `07_deploy_decision.md`
- **No user document review**: per `feedback_no_doc_review.md`. All alignment in session; coordinator gives 1-2-sentence summary per wave for signoff
- **Implementation handoff**: after `07_deploy_decision.md` signoff, implementation in separate session

---

## §10 Cross-references

- Process: `docs/ARCH_TEAM_PROCESS.md`
- Agent defs: `.claude/agents/arch-*.md`
- Prior arch review: `session_artifacts/_arch/00_brief.md` + 01-07
- Memory: see §8
