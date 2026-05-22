# 07 Deploy Decision

> **Final decision document** — coordinator consolidation of Wave 1-3 + W2 v2 into a signoff-ready summary.
> **Date**: 2026-05-15
> **Status**: AWAITING USER SIGNOFF
> **Primary spec**: `04_deploy_architecture_proposal_v2.md`
> **Successor**: implementation begins in separate session per §7 handoff plan.

---

## §1 Executive Verdict

**APPROVE** v2 at `04_deploy_architecture_proposal_v2.md`.

Architecture extends the **current FastAPI + uvicorn + SQLite + ProcessPoolExecutor stack (unchanged)** with:
- **4 new modules**: `CellLockRegistry`, `ConfigFileWriter`, `ConcurrencyLimiter`, `FleetRefreshManager`
- **3 SQLite schema additions**: `fleet_refresh_queue`, `fleet_refresh_items`, `pending_batch_configs` + `runs.underlying_removed` column
- **4-phase migration** with Phase 1 fully backward-compatible (single-user dev workflow unchanged)
- **No tech stack replacement** (constraint §5.2 honored throughout)
- **No user concept introduced** (constraint §5.3 honored)
- **No Docker / no Postgres / no Redis / no Celery / no NSSM / no nginx required**

Per brief §9 iteration policy: W2 v2 addresses all critical W3 findings; 3 remaining open questions are implementer-confirmation items, not blockers. No further W3 cycle needed.

---

## §2 Wave History

| Wave | Output | Verdict | Key signal |
|---|---|---|---|
| W1 mapper | `01_deploy_pipeline_map.md` | Descriptive | uvicorn/FastAPI + SQLite + 49 endpoints + virtual console 100% reused via `create_app()` |
| W1 taxonomist | `02_deploy_surface_taxonomy.md` | Descriptive | 105 surfaces: 42 safe / 10 safe-with-lock / 44 unsafe-today / 9 new-required |
| W1 coupling-auditor | `03_deploy_concurrency_blast_radius.md` | Descriptive | 16 scenarios; 1 Critical + 6 High + 4 silent dependencies |
| W2 v1 | `04_deploy_architecture_proposal.md` | Superseded by v2 | 9 alternatives; 4-phase migration; 1 H1 factual error caught by critic |
| W3 critic | `05_deploy_critique.md` | APPROVE-WITH-REVISIONS | 5 top concerns + 7 required revisions; CI-2 token bucket mechanism wrong |
| W3 validator | `06_deploy_validation.md` | APPROVE-WITH-REVISIONS | 13 cases (5 pass / 7 pass-with-concern / 1 FAIL); Case 13 INV-7 vs all-data delete |
| W2 v2 | `04_deploy_architecture_proposal_v2.md` | APPROVED (no further W3 needed) | All 12 revisions + 4 corrections addressed; 3 OQ remaining (implementer-confirmation only) |

---

## §3 Final Architecture (Summary; details in 04_v2)

### 3.1 New backend modules

| Module | File | Role |
|---|---|---|
| `CellLockRegistry` | `src/web_console/backend/cell_lock_registry.py` | Unified concurrency primitive replacing `_IN_USE_MODES` + `_busy_keys` + `OperationCoordinator` + uses of `_sidecar_lock_for`. Operations: SAMPLING / GENERATING / DELETING |
| `ConfigFileWriter` | `src/web_console/backend/config_writer.py` | Atomic JSON writes (tmp+os.replace) with per-file `threading.Lock`. Fixes Critical C1 (`machines.json` non-atomic). |
| `ConcurrencyLimiter` | `src/web_console/backend/rate_limiter.py` | `threading.Semaphore(n_slots=5)` cap on concurrent analyzer subprocesses; foreground-reserve threshold for ad-hoc fetch priority. Replaces v1's flawed token bucket. |
| `FleetRefreshManager` | `src/web_console/backend/fleet_refresh.py` | SQLite-backed queue + per-(machine,mode) item state + crash-recovery resume + cell-busy timeout (30 min default). |

### 3.2 SQLite schema additions (forward-only)

| Table / column | Purpose |
|---|---|
| `fleet_refresh_queue` | One row per refresh run; status (running/done/cancelled); start/end timestamps |
| `fleet_refresh_items` | Per-(machine, mode) item: queue_position, status, retries, last_error, in-flight worker id |
| `pending_batch_configs` | Crash-recovery anchor: written before fetch starts; cleared after sidecar update (R8 — write-config-first ordering) |
| `runs.underlying_removed` | Per-run flag set on rawdata delete; surfaced in UI as "underlying rawdata removed" |

### 3.3 Frontend additions

| Panel | Pattern |
|---|---|
| Config upload | Reuses existing file-upload pattern; `POST /api/configs/upload` |
| Fleet refresh progress | Polls `GET /api/fleet/refresh`; uses `_autoRefreshedForFleetRefreshId` one-shot guard per `memory/feedback_fasttimer_overlap_needs_oneshot.md` |
| Vendor chart.js | `frontend/vendor/chart.min.js` replaces CDN (intranet works without internet) |

### 3.4 Key invariants (16 total; full list in `04_v2.md §5.1`)

Most consequential:

- **INV-1**: At most one SAMPLING + one GENERATING + one DELETING (mutex with both) per `(machine, mode)`. Different config_ids on same machine+mode serialize (documented limitation per R10; sidecar sharding deferred to future arch review).
- **INV-3**: `configs/machines.json` write always atomic + serialized (Critical C1 fix).
- **INV-4**: `rawdata/_index.json` uses `msvcrt.locking` exclusive cross-process file lock (R3 fix; v1's mtime-retry was insufficient on NTFS 100ns granularity).
- **INV-6**: 4-tuple `(config_id, machine, mode, upstream_md5)` uniquely keys rawdata bucket; concurrent same-4-tuple → second planner **attaches** to first (R9; not rejected).
- **INV-7 v2**: rawdata delete tags reports stale; `DELETE /api/machines/{machine}/all-data` exempt — deletes reports entirely (R6 — resolves Case 13 FAIL).
- **INV-9**: Fleet refresh resumes after crash; `running` items re-queued as `pending` at startup.
- **INV-10**: ConcurrencyLimiter maintains `active_count <= n_slots`; foreground priority via `active_count < n_slots - foreground_reserve` threshold (R2 fix).
- **INV-X**: Cell-busy stall timeout = 30 min default (configurable `SLOT_FLEET_CELL_BUSY_TIMEOUT_S`); skip + log + retry-next-pass (R4 fix).

---

## §4 Migration Phases

| Phase | Scope (1-line) | Single-user dev impact | Revert |
|---|---|---|---|
| **P1** | Critical fix + atomic writes cluster + `msvcrt.locking` H3 fix + vendor chart.js + SQLite WAL | None (workflow unchanged) | `git revert <P1-commit>` |
| **P2** | `CellLockRegistry` atomic cutover + `OperationCoordinator` deletion + `ConcurrencyLimiter` + disk monitor daemon | Minimal (per-cell lock granularity replaces previous global mutex; throughput slightly higher) | `git revert <P2-commits>`; on-disk data unmodified |
| **P3** | Config upload + 4-tuple dedup + `FleetRefreshManager` + stale-tag on rawdata delete + sidecar `by_config_id` lazy migration | None for existing single-user; new features additive | SQLite tables droppable; sidecar v3 layout backward-compat via lazy migration |
| **P4** | `start_console.ps1` restart loop + Task Scheduler + `--host 0.0.0.0` + smoke runner + rollback script | New: server binds to LAN (intranet IP accessible) | `schtasks /Delete`; env var revert |

Each phase has verification gates from §5 test plan + grep CI checks.

---

## §5 Test Plan Summary

5 dims per brief §6:

| Dim | Coverage |
|---|---|
| **Design-level invariants** | 16 INVs walked in `06_validation.md` Cases 1-13; v2 retains all walks |
| **Impl-level unit/integration/e2e** | 11 test groups (T1-T11); each invariant has inject-bug → red → revert → green per `memory/feedback_enumerate_safety_paths.md`; e2e uses cached chunks fixtures (NOT real upstream) per `memory/feedback_perf_claim_needs_e2e_event_stream.md`; Playwright for frontend tests |
| **Deploy-smoke** | smoke_01-07 (boot, bind, Task Scheduler restart, rollback, PowerShell version check) |
| **Runtime monitoring** | 6 task types persist failure to disk + surface via `GET /api/system-state` per `memory/feedback_no_silent_swallow.md`; Windows Event Log for restart-budget exhaustion |
| **Regression防再踩** | 9 memory feedback files explicitly mapped to test cases including `feedback_fasttimer_overlap_needs_oneshot.md` → T11 one-shot guard, `feedback_subprocess_import_suicide_and_module_globals.md` → T2/T3 isolation tests |

---

## §6 Remaining Open Questions (3 — all implementer-confirmation; NOT blockers)

1. **GENERATING + SAMPLING coexistence per cell** — critic confirmed safe in CI-1 analysis: generator globs chunks at snapshot start; new chunks renamed in by SAMPLING after that point are naturally not included in generator's snapshot. No design change; implementer must follow this pattern.

2. **FleetRefreshManager virtual console injection** — virtual console (`virtual_app.build_virtual_app`) doesn't need fleet refresh. Resolution: `create_app(fleet_refresh_enabled: bool = True)` parameter; virtual passes `False`. Implementer confirms.

3. **`DELETE /api/machines/{machine}/all-data` mode iteration** — if mode 1 acquires DELETING lock but mode 2 fails (concurrent op active), **abort-and-rollback** (release mode 1 lock, return 409). Implementer confirms abort-and-rollback semantics over partial-deletion.

---

## §7 Implementation Handoff

### 7.1 Order of execution

```
P1 (1 commit, backward-compat) → smoke → P2 atomic cutover (multi-commit, single PR) → smoke → P3 new features → smoke → P4 deploy + LAN bind → smoke
```

### 7.2 Pre-implementation reads (next session's coordinator)

1. `session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md` — primary spec (1204 lines)
2. `session_artifacts/_arch/deploy/07_deploy_decision.md` — this document (signoff record)
3. `memory/project_internal_deploy_intent.md` — user requirements
4. `memory/feedback_respect_existing_codebase.md` — stack-locked principle
5. `memory/feedback_arch_team_process.md` — process foundation
6. W1 outputs (01/02/03) for specific hazard / surface citations

### 7.3 Agent composition (implementer session)

Per brief §9 deferral, implementer agents were NOT pre-spawned. Next session decides:
- Direct implementer pattern (single Claude session implements P1/P2/P3 sequentially with verify gates) — preferred for backward-compat phases
- Multi-agent (deploy-implementer + test-implementer + deploy-verifier) — preferred if P3/P4 surface complexity demands parallelism

Recommendation: start P1 with direct implementer; reassess at P2 boundary based on diff size.

---

## §8 User Signoff Points (decided in session)

1. **APPROVE v2 architecture as final?** (or specific concerns)
2. **Phase 2 atomic cutover OK?** — `OperationCoordinator` deleted entirely in one commit (single PR); brief window of code-review intensity required
3. **Phase 3 SQLite schema additions OK?** — `fleet_refresh_queue` / `fleet_refresh_items` / `pending_batch_configs` tables + `runs.underlying_removed` column; forward-only; no migration tooling
4. **Phase 4 LAN bind 0.0.0.0 OK?** — per brief §9 single Win host; firewall rules / Windows Defender allow-list documented in `README_DEPLOY.md`
5. **Cell-busy timeout 30 min default OK?** — R4; configurable via env `SLOT_FLEET_CELL_BUSY_TIMEOUT_S`
6. **n_slots=5 OK?** — R2; 5 × 8 = 40 concurrent upstream connections per LAN client; tunable

---

## §9 Cross-references

- Brief: `00_deploy_brief.md`
- Primary spec: `04_deploy_architecture_proposal_v2.md` (supersedes v1 at `04_deploy_architecture_proposal.md`)
- W3 critique: `05_deploy_critique.md`
- W3 validation: `06_deploy_validation.md`
- Memory pointers: `project_internal_deploy_intent.md` + `feedback_respect_existing_codebase.md` + `feedback_arch_team_process.md`
- Implementation: pending next session
