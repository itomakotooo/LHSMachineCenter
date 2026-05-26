# Auto-Inspect — Decision Doc (authoritative)

> Wave 4 — Coordinator synthesis after W3 critic + validator.
> Date: 2026-05-26
> Status: **APPROVED FOR IMPLEMENTATION** with the resolutions below.
>
> When implementing, this doc is the source of truth. The proposal
> (`04_architecture_proposal.md`) is the design narrative; this doc
> overrides on every conflict. Critic (`05_critique.md`) and validator
> (`06_validation.md`) are diagnostic — not authoritative.

---

## §1 — Quick verdict

- **Critic**: APPROVE-WITH-REVISIONS (5 must-fix, 5 should-fix, 7 OQs un-resolved)
- **Validator**: APPROVE-WITH-REVISIONS (3 blocking bugs, 2 nice-to-fix, 0 broken cases)
- **My call (coordinator)**: APPROVE pending the 8 resolutions in §2. No second design pass. Critic + validator findings are concrete enough that the impl team can act on this decision doc directly.

Phase plan: 5 phases stand. One internal re-sequencing (move UI scaffolding earlier) noted in §4.

---

## §2 — Resolutions to W3 findings

### MF-1 (BLOCKING) — md5 refresh blocks HTTP server startup

**Resolution**: `_restore_on_startup` must NOT call `_do_refresh_machines_md5` synchronously. Move the refresh inside the resume daemon thread that's spawned AFTER `create_app` finishes. In `__init__`, just enumerate the persisted non-terminal sweep rows from the new `auto_inspect_sweeps` table; defer all upstream HTTP to the thread.

```python
def __init__(self, ...):
    ...
    self._pending_resume_sweep_id = self._scan_persisted_for_resume()
    # No HTTP here. _scan_persisted_for_resume is pure SQLite.

# In create_app, after manager is constructed:
if auto_mgr._pending_resume_sweep_id:
    threading.Thread(target=auto_mgr.resume_sweep,
                     args=(auto_mgr._pending_resume_sweep_id,),
                     daemon=True, name="auto-inspect-resume").start()
```

### MF-2 (BLOCKING) — Generate phase has no restart recovery

**Resolution**: split the sweep's generate phase to be PER-ITEM, not one global batch. Each `auto_inspect_items` row carries a `generate_run_id` (existing field per proposal). After sampling completes for an item, dispatch a generate-report run for that item directly via `RunManager.start_run` (from-cache, mode-scoped to this item's mode). Restart-recovery for the generate phase becomes the same path as the sampling phase: items whose `generate_run_id IS NOT NULL AND generate_status IS NULL` are re-dispatched on resume.

This kills the "no reports for 8 hours" gap that SF-1 also flagged. It also bypasses MF-2's "duplicate generate batch" problem entirely — there is no batch.

Concretely: the sweep no longer calls `batch_gen_mgr.start()`. It calls `RunManager.start_run(RunCreateRequest(from_cache_dir=..., machine=..., mode=...))` per item after sampling lands.

### MF-3 (HIGH) — sweep_concurrency=3 default starves fleet refresh

**Resolution**: change default to **2**. Add a hard guard: `start_sweep` returns 409 if `FleetRefreshManager.get_running_queue_id()` returns non-None, and `FleetRefreshManager.start_queue` returns 409 if an auto-inspect sweep is running. The two are mutually exclusive at the manager level — they were never designed to run concurrently and operator UX suffers if both progress in unpredictable ways. The 2-concurrency default also matches the loopback CPU profile observed during the per-server autotune work (no benefit beyond conc=16 within a single chunk, and the bottleneck is simulator CPU not network).

### MF-4 (HIGH) — M272 / M120 silently classified easy

**Resolution**: cell classification grows a 6th class `manifest_override` that catches machines listed in `slot_designer/configs/machine_manifests/{M}.json` (per `09_architecture_as_built.md`'s Tier-2 roster) where the manifest's `paid_spin_type != 1` or has `pay_id_override != null`. These machines run through the standard sampling path BUT the impl team verifies that `player_impact_analyzer.py` loads the per-machine manifest before each run (per `09_architecture_as_built.md`'s shipped Phase 3 behavior). Confirmation step is a Phase 1 invariant test: "M272 sweep run produces a report with `paid_spin_type=140`, M120 with `pay_id 666` correctly attributed."

If the manifest loader is NOT in fact wired into the analyzer subprocess CLI path, that wiring goes in Phase 1 (it's a prerequisite, not a sweep feature).

### MF-5 (HIGH) — Global consecutive-failure counter is wrong measure

**Resolution**: change to a **windowed** counter with **structural-exclusion**. `consecutive_failure_count` only increments for failures whose `terminal_status` is `failed` (subprocess crash / network error / disk error). It does NOT increment for `structural_skip`, `convergence_timeout`, `manifest_override_partial`, or any other expected-failure class. Window: last 10 attempts. Default trip: 3 out of last 10. This way M279's expected partial failures don't trip the counter, but a real infra outage that fails 3 of the next 10 cells does.

### V1: S4-G1 (BUG) — No atomic claim step

**Resolution**: per validator's suggested fix. Add `claimed` as a transient status in `auto_inspect_items` (between `pending` and `running`). The dispatch loop uses a Python-level threading.Lock around an `UPDATE ... SET status='claimed', claimed_by=:worker_id, claimed_at=:now WHERE status='pending' ORDER BY queue_position ASC LIMIT 1 RETURNING *` (SQLite >= 3.35 supports RETURNING). The worker that gets a row proceeds; if no rows returned (sibling worker won the race), worker idles 1s then retries. On crash-recovery, `claimed` rows reset to `pending`.

### V2: S5-G1 (SCHEMA) — Per-machine md5s have nowhere to live

**Resolution**: add two columns to `auto_inspect_items`: `cfg_md5_at_enqueue TEXT NOT NULL DEFAULT ''` and `code_md5_at_enqueue TEXT NOT NULL DEFAULT ''`. Populated at scan time when the row is INSERTed. The mid-sweep md5-drift check (failure mode (i)) compares the current upstream md5 against these snapshot columns to decide "needs re-sample" vs "still valid".

### V3: S3-G1 (INTERFACE) — `resume_sweep` missing from public interface

**Resolution**: add `resume_sweep(sweep_id: str) -> None` to AutoInspectManager's public method list. Also add to the scaffolding test that asserts the public interface matches the proposal's §1 list.

### OQ-A (M274 baseline alert metric) — wrong field

**Resolution**: the alert compares `achieved_rtp_pct` (from `runs` table), NOT `achieved_halfwidth_pp`. Baseline stored at first successful M274 sweep run. Alert fires when `|current_rtp - baseline_rtp| > 2pp`. Sub-spec: baseline is the FIRST successful M274 mode-1 sweep RTP after this manager ships; it persists in `state/console/m274_baseline.json` (gitignored). If the file is missing, the next successful sweep populates it without alerting.

### OQ-C (skip_fresh_cells re-evaluates CI against current setting)

**Resolution**: confirmed YES — the predicate at scan time reads `target_halfwidth_pp` from CURRENT settings, not from any cached previous-sweep value. Add an explicit line in the proposal § confirming this. Tightening the target between sweeps correctly re-queues cells whose previous reports exceed the new target.

### OQ-E (sweep_concurrency saturation) — already resolved by MF-3

### OQ-F (Per-mode generate filtering)

**Resolution**: the per-item generate dispatch (per MF-2 resolution) naturally filters — each `auto_inspect_items` row carries its own `mode`, and generate is dispatched per-item with that mode. No batch-level filter needed; the per-item architecture removes this whole class of bug.

### OQ-G (cron expression format)

**Resolution**: ship Phase 4 + Phase 5 with format restricted to **`HH:MM` (daily)** OR **`*/N` (every N hours, 1≤N≤24)**. No full cron syntax. UI Phase 4 must enforce this via a regex validator + a two-mode picker ("每天 HH:MM" / "每 N 小时"). The parser in Phase 5 is then ~20 LOC, no croniter dependency.

### SF-1 (Report blackout) — resolved by MF-2 per-item

### SF-2 (Binary group cap mis-applied to 45-machine group)

**Resolution**: per validator's S1-C1. The per-codeSummaryMd5 cap only applies to groups that BOTH (a) share `codeSummaryMd5` AND (b) share `configSummaryMd5`. The 45-machine f7a4cefd group shares only codeSummaryMd5; their configs are distinct (Pattern A). Cap them at default (4 concurrent), not 2. M273's 86-machine family shares both md5s (Pattern B) → cap at 2. This is one extra clause in the semaphore-init logic.

### SF-3 (Scan re-runs on resume — timing)

**Resolution**: accept the scan re-run as-is. 1,688 `check_rawdata_status` calls take ~5-10 seconds on local NTFS based on existing fleet benchmarks. Add a `phase=scanning` indicator in the UI so operator sees the scan is happening. No timing guarantee in the spec.

### SF-4 (operator manual sample of a sweep-owned cell — undocumented attached path)

**Resolution**: when the operator triggers a manual batch-run for a cell currently SAMPLING'd by the sweep, BatchRunManager's existing D12 logic returns `attached` per current behavior. Add a UI tag in the operator's batch result row: "已附加到自动巡检 (sweep_id=...)". The sweep treats the attached operator request as transparent (it's not aware). No state machine change.

### SF-5 (cron expression scope) — resolved by OQ-G above

### R3.2 (auto_inspect_events 500-entry cap is too low for 1688 cells)

**Resolution**: bump cap to **3,000**. 1,688 cells × ~1.5 events average ≈ 2,500. Or per-CELL events_json keyed by `(sweep_id, machine, mode)` instead of one shared blob. Pick the latter — events live on each `auto_inspect_items` row as a small JSON array (cap 20 events per item = 33k total). This also fixes the "find events for M14 mode 1" lookup pattern naturally.

### S2-G1 (validator nice-to-fix) — bcm_hard roster in code

**Resolution**: per validator. Move the hardcoded `{M250, M260, M264, M268}` list to `state/console/settings.json` key `auto_sweep.structural_skip_machines`. Operator (or me) flips the list when BCM anchor work lands. Default value stays {M250, M260, M264, M268} in `_load_settings` fallback.

---

## §3 — Schema additions (final)

Per resolutions above, the SQLite additions for Phase 1:

```sql
CREATE TABLE IF NOT EXISTS auto_inspect_sweeps (
    sweep_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,             -- pending | scanning | sampling | finalizing | completed | cancelled | failed
    created_at TEXT NOT NULL,
    finished_at TEXT,
    settings_snapshot_json TEXT NOT NULL,
    modes_json TEXT NOT NULL,         -- ["1","2","5","7"]
    trigger TEXT NOT NULL,            -- manual | cron
    total_items INTEGER NOT NULL DEFAULT 0,
    completed_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    skipped_items INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS auto_inspect_items (
    sweep_id TEXT NOT NULL REFERENCES auto_inspect_sweeps(sweep_id),
    machine TEXT NOT NULL,
    mode INTEGER NOT NULL,
    queue_position INTEGER NOT NULL,
    status TEXT NOT NULL,             -- pending | claimed | running | generating | completed | failed | structural_skip | convergence_timeout | manifest_override_partial | deferred_lock_conflict | wall_time_timeout | md5_drift_invalidated
    cell_class TEXT NOT NULL,         -- easy | trigger_session | bcm_hard | bcm_moderate | bcm_uncharted | manifest_override
    sample_run_id TEXT,
    generate_run_id TEXT,
    generate_status TEXT,
    cfg_md5_at_enqueue TEXT NOT NULL DEFAULT '',
    code_md5_at_enqueue TEXT NOT NULL DEFAULT '',
    claimed_by TEXT,
    claimed_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    terminal_reason TEXT,
    events_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (sweep_id, machine, mode)
);

CREATE INDEX IF NOT EXISTS idx_auto_inspect_items_status
    ON auto_inspect_items (sweep_id, status);
```

`_is_cell_owned_by_active_queue` gets a 4th branch:

```sql
SELECT s.sweep_id
FROM auto_inspect_items i
JOIN auto_inspect_sweeps s ON s.sweep_id = i.sweep_id
WHERE i.machine = ? AND i.mode = ?
  AND s.status IN ('scanning', 'sampling', 'finalizing')
  AND i.status NOT IN ('completed', 'failed', 'structural_skip',
                       'convergence_timeout', 'manifest_override_partial',
                       'md5_drift_invalidated')
LIMIT 1
```

Settings.json schema additions (validated in `_load_settings`):

```json
{
  "auto_sweep": {
    "enabled": false,
    "schedule_mode": "daily",          // "daily" | "interval"
    "schedule_value": "02:00",         // "HH:MM" if daily; "N" (int 1-24) if interval
    "skip_fresh_cells": true,
    "sweep_concurrency": 2,
    "binary_group_large_cap": 2,       // for shared-cfg shared-code groups
    "max_consecutive_failures": 3,     // out of last 10 attempts (windowed)
    "consecutive_failure_window": 10,
    "structural_skip_machines": ["M250", "M260", "M264", "M268"],
    "cell_busy_timeout_s": 1800,
    "wall_time_per_cell_s": 7200,
    "modes": {
      "1": {"chunk_spin_times": 10000, "chunk_robot_count": 2, "batch_concurrency": 16, "target_halfwidth_pp": 0.5, "max_chunks": 60},
      "2": {"chunk_spin_times": 10000, "chunk_robot_count": 2, "batch_concurrency": 16, "target_halfwidth_pp": 0.5, "max_chunks": 60},
      "5": {"chunk_spin_times": 10000, "chunk_robot_count": 2, "batch_concurrency": 16, "target_halfwidth_pp": 0.5, "max_chunks": 60},
      "7": {"chunk_spin_times": 10000, "chunk_robot_count": 2, "batch_concurrency": 16, "target_halfwidth_pp": 0.5, "max_chunks": 60}
    }
  }
}
```

---

## §4 — Final phase plan (with re-sequencing)

| Phase | Deliverable | Why this order |
|---|---|---|
| **P1 — Foundation** | Settings schema + DB tables + `_is_cell_owned_by_active_queue` 4th branch + AutoInspectManager skeleton class (interface only, no logic) + impl-tester verifies manifest loader IS wired into analyzer subprocess for M272/M120 (per MF-4) | Foundation for everything; verifies the MF-4 prerequisite before P2 builds on it |
| **P2 — Discovery + state machine** | Scan logic (md5 detection, cell classification incl. `manifest_override`), atomic claim via `UPDATE ... RETURNING`, sampling worker loop, cell-lock yield, structural_skip handling, windowed consecutive-failure counter | Sampling pipeline end-to-end. No generate yet. |
| **P3 — Per-item generate + failure modes** | Per-item generate-dispatch (per MF-2 resolution), all 9 failure-mode terminal statuses, restart recovery for both phases | Now sweep produces reports incrementally. Restart works. |
| **P4 — Frontend tab (full)** | New tab "自动巡检" with: settings form (4 modes × 5 fields + cron picker with 2-mode `daily/interval` per OQ-G), preview ("将巡检 N cells"), start/cancel, live progress (aggregate + per-cell drilldown), recent sweep history | Phase 4 is when operator first SEES the feature. Earlier phases are headless API only. |
| **P5 — Cron scheduler + M274 alert + hardening** | `threading.Timer`-based scheduler reading `schedule_mode`+`schedule_value`, M274 RTP-drift alert (per OQ-A fix), mutex with FleetRefreshManager (per MF-3), end-to-end smoke test on the deployed server | Polish + cron. By now the feature is usable; this makes it operationally complete. |

Each phase = 1 commit-ish (may split P2/P3 across 2 commits if scope explodes; impl-* loop decides per phase critique).

---

## §5 — Out-of-scope (explicitly deferred)

1. Email / push notifications when sweep finishes — operator polls UI
2. Sweep diffing ("what changed vs last sweep")
3. Per-cell event drill-down beyond the events_json on each row
4. Multi-server sweeps (always uses resolver-current server)
5. Sweep export / report bundle for external sharing
6. Per-cluster sweep (only "full fleet" supported in v1)

---

## §6 — Acceptance criteria for impl team

Per phase, impl-tester writes tests, impl-verifier runs them PLUS:

- **No silent failure paths**. Every terminal status must be a named enum value with non-null `terminal_reason`. (Per `feedback_invariant_with_fallback_hides_drift.md`.)
- **No `mode=None` calls to `_get_machine_md5`**. Audit at every call site. (Per coupling audit top fragility.)
- **No module-level globals introduced**. AutoInspectManager state is per-instance. (Per `feedback_subprocess_import_suicide_and_module_globals.md`.)
- **MF-1 verified**: console restart with upstream unreachable returns 200 on `GET /api/system-state` within 5 seconds.
- **MF-2 verified**: kill console mid-generate → restart → no duplicate generate runs in `runs` table for any (machine, mode, md5) tuple.
- **MF-4 verified**: M272 sweep run produces report with `paid_spin_type=140` (or whatever the manifest says).
- **MF-5 verified**: simulate 5 consecutive M279 expected failures → sweep continues to M274 → consecutive counter did NOT trip.
- **MF-3 verified**: while sweep is running, `POST /api/fleet/refresh` returns 409. Reverse also 409.

---

## §7 — Sign-off

When user OKs this decision doc → impl team starts P1.

If user changes scope (e.g. "no cron", "add notifications", "per-cluster sweep"), update this doc first, then proceed. Do NOT branch impl on undocumented requirement changes.
