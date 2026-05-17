# Deploy Migration Handoff — P4 Pending

> **Date**: 2026-05-17
> **Status**: P1 + P2 + P3 committed; **P4 pending in a fresh session**
> **Branch**: `claude/quizzical-sinoussi-d89f7c` (worktree); not yet merged to `collab/dev`
> **HEAD**: `51af9a6` (P3 commit)

This document is the cold-start brief for the next session that picks up P4. Read top-to-bottom; sections are ordered by "need-first" for an incoming coordinator.

---

## §1 What is done

3 of 4 phases of the internal-deploy migration are committed and tested. The architecture was designed by the `arch-*` 6-agent team across 2 sessions (`session_artifacts/_arch/` for the original fleet-refactor and `session_artifacts/_arch/deploy/` for this deploy review).

| Phase | Commit | Date | Tests | Lines |
|---|---|---|---|---|
| arch review (W1/W2/W3/W2v2/decision) | `6aaa74e` | 2026-05-15 | n/a | 9 docs |
| P1 — atomic config writes + WAL + cross-process index lock | `cec5012` | 2026-05-15 | +28 / 71 green | 7 files |
| P1-fix — 5 blockers caught by retroactive impl-critic | `c4d4e4a` | 2026-05-17 | +44 (23 new + 21 fix) / 1043 green | 7 files |
| infra(agents) — impl-* 4-agent team definitions | `324d751` | 2026-05-17 | n/a | 5 files |
| **P2 — CellLockRegistry + OperationCoordinator atomic cutover** | `ff93557` | 2026-05-17 | +66 / 1043 green | 14 files |
| **P3 — config upload + fleet refresh queue + report stale tagging** | `51af9a6` | 2026-05-17 | +44 / 1087 green | 13 files |
| **P4 — deploy script + Task Scheduler + LAN bind** | **TBD** | TBD | TBD | TBD |

Total backend test count at HEAD: **1087 passed / 22 skipped** (stable across 3 independent runs at multiple verifier passes).

Total session_artifacts in this deploy migration:
- `session_artifacts/_arch/deploy/` — 9 docs (00 brief + 01/02/03 W1 + 04/04_v2 W2 + 05/06 W3 + 07 decision)
- `session_artifacts/_impl/p1/` + `p1_fix/` + `p2/` + `p3/` — briefs + critiques per phase

---

## §2 What is left — P4 (smallest phase)

Per `session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md` §4.7 + §6 Phase 4 deliverables:

1. **`start_console.ps1` restart loop** — wrap uvicorn launch in PowerShell `while ($restarts -lt $MAX_RESTARTS)` loop with exponential backoff. PowerShell 5.1-compat per S1 fix (no `??` operator). On exhaustion: `Write-EventLog -LogName Application -Source SlotConsole -EntryType Error -EventId 1001` for operator visibility.
2. **`--host 0.0.0.0` LAN binding** — change uvicorn launch arg from `127.0.0.1` to `$bindHost` reading `$env:SLOT_BIND_HOST` (default `0.0.0.0`). Same for `$env:SLOT_BIND_PORT` (default `8877`).
3. **Task Scheduler XML** — `.xml` task definition that runs `start_console.ps1` at boot; configure user account (NOT SYSTEM); add to deploy docs.
4. **`scripts/deploy/README_DEPLOY.md`** — step-by-step deploy / upgrade / rollback procedures; document Windows Defender / firewall allow-list for LAN; document "state/console MUST be on local disk (NOT SMB/CIFS)" for SQLite WAL.
5. **`scripts/deploy/run_smoke.ps1` + `rollback.ps1`** — smoke test suite runnable from LAN client; rollback script to restore prior commit + clean DB sidecars.

**No production code changes expected.** Just scripts + 1 markdown + minor uvicorn arg passing.

Estimated scope: ~200-400 LOC across 4-5 scripts + ~100 lines of README markdown.

---

## §3 Recommended P4 workflow

P4 is the smallest phase. Two paths:

### Path A (preferred) — full impl-* 4-agent team

Even though P4 is scripts-heavy, run the standard loop per `docs/ARCH_TEAM_PROCESS.md` §9 + `memory/feedback_impl_team_required.md`. Specifically:

1. Coordinator writes `session_artifacts/_impl/p4/brief.md` covering the 5 deliverables + invariants (e.g. "restart loop must give up after MAX_RESTARTS with Event Log entry").
2. `impl-implementer` writes the scripts + README + tiny code change.
3. `impl-tester` writes Pester (PowerShell test framework) or pytest tests where applicable; for non-testable scripts (deploy procedures), validate manually with a dry-run.
4. `impl-verifier` runs the full backend test sweep (must stay 1087+ green) + smoke imports + dry-runs the PowerShell restart loop in a sandbox (`pwsh -NoProfile -File start_console.ps1 -WhatIf` if achievable).
5. `impl-critic` adversarial review of scripts: failure modes (PS process dies, Task Scheduler permissions, firewall denial, etc).
6. Coordinator commits when APPROVE.

### Path B (acceptable for scripts) — coordinator direct

Per `memory/feedback_impl_team_required.md`: "Single-file bug fix / docs-only / trivial 5-line change: skip the team, direct edit + smoke test is fine." P4 is borderline — bigger than 5 lines, but no production code, no concurrency, no SQLite schema. Direct edit + manual smoke is defensible.

Recommend Path A for the script files (Pester / PS automation has its own footguns) and Path B for README_DEPLOY.md.

---

## §4 Critical known limitations carried forward to P4 (or later)

P3 commit `51af9a6` shipped with the following documented gaps:

| Gap | Where | Severity | Disposition |
|---|---|---|---|
| `_item_config_id = "null"` hardcoded — config_id wiring through sampling path not done | `app.py:3935` (commented) | Medium | Follow-up: add `config_id` param to `update_chunk_entry`; thread from upload → batch run → sidecar |
| `/api/system-state` does NOT surface `stale_tag_error.json` or `reassociate_error.json` | `current_system_state()` | Low | Follow-up: add 2 fields reading from disk if file exists |
| `_run_one` success-path `delete_pending_batch_config` has no dedicated inject-bug test | `app.py:4199` | Low | Follow-up: add T-test |
| `update_chunk_entry` has no `config_id` parameter | `chunk_index.py` | Low | Follow-up: extend signature |
| `refreshConfigList` silent swallow (frontend) hides non-404 errors | `app.js:7963` | Low | Follow-up: distinguish 404 from 5xx |
| POSIX `fcntl_flock_failed` degradation path test | `rawdata_index.py` | Low | Follow-up (P1-fix carryover) |
| HTTP-level integration test for `_refresh_md5_async` wiring | `app.py` | Low | Follow-up (P1-fix carryover) |
| Frontend Playwright tests | n/a | Low | Backend tests cover API surface |

None of these block P4 or production deploy. They are tracked here so the next session can plan a follow-up cleanup commit OR carry them into the v2 deploy spec.

---

## §5 First commands for the new session

```bash
# 1. Verify worktree state
cd C:\Users\pangg\Documents\Projects\LHS\User_Managerment_GPT\.claude\worktrees\quizzical-sinoussi-d89f7c
git log --oneline -6
# Expected: 51af9a6 P3, ff93557 P2, c4d4e4a P1-fix, 324d751 infra, cec5012 P1, 6aaa74e arch

# 2. Confirm green baseline
python -m pytest tests/backend/ --ignore=tests/backend/test_analyzer_st_split.py -q 2>&1 | tail -3
# Expected: 1087 passed, 22 skipped

# 3. Confirm smoke
python -c "from src.web_console.backend.app import create_app; app = create_app(); print(f'{len(app.routes)} routes')"
# Expected: 79 routes

python -c "from src.web_console.backend.app import create_app; app = create_app(fleet_refresh_enabled=False); print(f'{len(app.routes)} routes')"
# Expected: 76 routes (virtual console mode)
```

If any of those fail, do NOT proceed to P4 — investigate first.

---

## §6 Pre-reading order for the next session's coordinator

1. **THIS FILE** (`session_artifacts/_impl/HANDOFF.md`) — you are here
2. **`session_artifacts/_arch/deploy/07_deploy_decision.md`** — overall design decision + 4-phase plan
3. **`session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md`** §4.7 + §6 Phase 4 — P4 design details
4. **`session_artifacts/_impl/p3/brief.md`** + **`p3/critique_v2.md`** — to understand the impl-* loop pattern (also p2/brief.md if helpful)
5. **`memory/project_internal_deploy_intent.md`** — overall requirements + tech stack decisions
6. **`memory/feedback_arch_team_process.md`** + **`memory/feedback_impl_team_required.md`** — workflow definitions
7. **`docs/ARCH_TEAM_PROCESS.md`** §9 — impl-* team protocol

---

## §7 Memory pointers updated post-P3

`memory/project_internal_deploy_intent.md` is updated 2026-05-17 to mark P1+P2+P3 as committed with the actual final stack decisions confirmed. P4 listed as the only remaining phase.

The original arch team process (`memory/feedback_arch_team_process.md`) and impl team requirement (`memory/feedback_impl_team_required.md`) are unchanged — the workflow has worked end-to-end through 3 full impl-* loops with multiple loop-back iterations, and the model has held up.

---

## §8 Branch & merge state

Branch: `claude/quizzical-sinoussi-d89f7c` (worktree at `.claude/worktrees/quizzical-sinoussi-d89f7c/`).

NOT yet merged to `collab/dev`. The next session can:
- (a) Continue P4 on this branch, merge after P4 lands
- (b) Merge to `collab/dev` now (P1+P2+P3 is a clean checkpoint), branch from `collab/dev` for P4
- (c) Keep working on this branch indefinitely

The user has not specified a preference for the branch flow; coordinator should ask if unclear.

---

## §9 Open questions for the user (only if necessary)

These are product/scope questions the next session might want to confirm before P4:

1. **Deploy target machine details**: actual hostname / IP? specific Windows version / PowerShell version? Memory pointers say "Windows server / single host" but actual deploy is the next session's concern.
2. **Task Scheduler user account**: should the SlotConsole task run as the current operator user, a dedicated service account, or LocalService? Affects file permissions on `rawdata/` and `state/console/`.
3. **README_DEPLOY.md audience**: ops team unfamiliar with the codebase, or just the deploy operator (single person)? Affects level of explanation.
4. **Smoke test stringency**: should smoke include a real upstream fetch (uses production-like rawdata) or only the local-only `--from-cache` path?

These are NOT critical — sensible defaults exist for all. List here in case the next session wants to ask up front.

---

## §10 Self-review notes from this session

What worked:
- impl-* 4-agent loop catching 4 blockers in P2 + 3 blockers in P3 + RLock deadlock that loop-back-2 itself introduced. Without the loop, all of these would have shipped.
- The "loop-back" pattern (implementer → tester → loop-back implementer if regression) handled the Optional B Windows race in P1-fix correctly.
- Memory feedback files (`feedback_no_silent_swallow.md`, `feedback_enumerate_safety_paths.md`, etc.) caught real issues at every critic gate.

What was painful:
- Long commit messages broke `git commit -m "$(cat <<'EOF'...EOF)"` heredoc parsing on Windows bash. Workaround: shorter messages, audit trail in committed markdown files.
- impl-tester occasionally missed pre-existing tests that referenced old APIs (8 broken tests in P2 cutover; verifier caught it).
- P3 loop-back-2 fix introduced a NEW deadlock (RLock issue). Critic 2nd pass caught it. Lesson: any lock-change needs explicit test for nested-acquire path.

Recommendations for next session:
- If P4 critic flags scripts as having known footguns (PowerShell process death not retried, Task Scheduler permission gap, etc.), accept them with explicit comments + Not-Verified entries in the commit message rather than try to fix everything.
- Manual smoke of `start_console.ps1` in a sandbox/VM is more valuable than automated PS tests for the operator-discovery failure modes.
