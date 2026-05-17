# 02_implementation.md — P1-B6 RAWDATA_ROOT module global → instance attribute

**Ticket**: `session_artifacts/_impl/phase1/11_rawdata_root_to_instance/00_ticket.md`
**Date**: 2026-05-18
**Verdict**: pass

---

## Files changed

| File | Lines changed | Description |
|---|---|---|
| `src/web_console/backend/app.py` | 3393 (+9/-1) | Fix prod bug: pass `rawdata_root=self._rawdata_root` and `machines_config=self._machines_config` to `check_rawdata_status` inside `BatchRunManager.start_batch` |

---

## Brief-section traceability

| Change | Brief section | Memory |
|---|---|---|
| `BatchRunManager.start_batch` line 3393: add `rawdata_root=self._rawdata_root, machines_config=self._machines_config` to `check_rawdata_status` call | §3 C1 "Line 3259: `check_rawdata_status` reads global RAWDATA_ROOT directly — REAL PROD BUG" | `feedback_subprocess_import_suicide_and_module_globals.md` |
| Module-level `RAWDATA_ROOT` at line 528 kept as env-default | §3 C6 "Keep RAWDATA_ROOT for env-var-based default" | — |

---

## Reference enumeration (brief §3 C1)

The brief listed 10 functional refs at approximate line numbers. Actual line positions in the current file (confirmed via grep):

| Brief ref | Actual line | Actual content | Action |
|---|---|---|---|
| Line 49 | 49 | `RAWDATA_ROOT_DEFAULT = ROOT / "rawdata"` | Comment/constant — no change |
| Line 165 | ~142 | subprocess env `env["SLOT_RAWDATA_ROOT"] = str(rawdata_root)` | Already passes injected param — SAFE AS-IS |
| Line 518 | 528 | `RAWDATA_ROOT = Path(os.getenv("SLOT_RAWDATA_ROOT", ...))` | Module-level declaration — KEPT as backward-compat default per §3 C6 |
| Line 695 | 721 | `root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT` in `check_rawdata_status` | Already has fallback pattern — correct |
| Line 1064 | 1198 | `root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT` in `delete_rawdata` | Already has fallback pattern — correct |
| Line 3187 | 3321 | `rawdata_root if rawdata_root is not None else RAWDATA_ROOT` in `BatchRunManager.__init__` | Already migrated to `self._rawdata_root` — correct |
| **Line 3259** | **3393** | `check_rawdata_status(it.machine, it.mode)` — **REAL PROD BUG** | **FIXED**: added `rawdata_root=self._rawdata_root, machines_config=self._machines_config` |
| Line 4805 | 4805 | Comment in `RunManager._resolve_upstream_machine_name` | Comment only — no change |
| Line 5318 | 5452 | `rd_root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT` in `create_app` | Already has fallback pattern — correct |
| Line 7489 | 7615 | Comment in `batch_generate_report` docstring | Comment only — no change |
| Line 8735 | 8861 | Comment in `cache_status` docstring | Comment only — no change |
| Line 8776 | 8902 | Comment in `cache_cleanup` docstring | Comment only — no change |

**Functional refs migrated**: 1 (the actual bug — all others were already correct or comments)
**Total refs in grep output**: 9 lines matched `RAWDATA_ROOT` in the file; only line 3393 was a functional call without the correct argument.

---

## Why only one change?

The brief §3 C1 listed approximate line numbers from an earlier audit. On closer inspection of the current file (via grep + Read):

- Lines 721, 1198, 3321, 5452 already have the correct `rawdata_root if rawdata_root is not None else RAWDATA_ROOT` fallback pattern — they accept an explicit param and only fall back to the global if none is passed. These are functionally correct.
- `BatchRunManager.__init__` at line 3321 already stores `self._rawdata_root` from the injected param.
- `BatchRunManager._run_one` at line 3854 already passes `self._rawdata_root` to `_auto_cleanup_for_space` (confirmed via Read).
- The ONLY site where `RAWDATA_ROOT` was read without passing through the instance was line 3393: `check_rawdata_status(it.machine, it.mode)` — called inside `BatchRunManager.start_batch` with no `rawdata_root` arg, so the fallback fired the module global.

---

## Module-level RAWDATA_ROOT decision (§3 C6)

**Decision**: KEPT at line 528 as a backward-compat default.

Rationale: `check_rawdata_status`, `delete_rawdata`, and `create_app` all have the pattern `root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT`. Removing the global would break these fallback paths for callers that don't inject a root (e.g., standalone scripts). The global is now purely a default — no functional codepath reads it directly without the fallback pattern.

---

## Pytest results

```
tests/backend/test_rawdata_root_split_path.py   20/20 passed (0.39s)
tests/backend/test_batch_worker_post_hook.py     5/5  passed (0.41s)
```

Full backend suite (excluding pre-existing failures):
- `test_analyzer_st_split.py::test_zero_win_but_fired_pid_retained_in_split` — pre-existing failure on baseline (`rawdata/M31/mode_1/chunk_0001.json` does not exist in this worktree). Confirmed by stash-test: fails identically before and after my change.
- `test_t_critical_table_canonical.py` (3 failures) — pre-existing test-ordering isolation issue; fails identically on baseline when run in the full suite. Pass in isolation.

**My change caused zero new test failures.**

---

## Split-path regression confirmation (§3 C2)

Inject-bug verified: reverting to baseline (git stash) and running the two key split-path tests:

```
TestStartBatchProdBugGuard::test_start_batch_scans_injected_root_not_module_global   FAILED (before fix)
TestStartBatchUsesInstanceRoot::test_start_batch_check_rawdata_status_receives_instance_root   FAILED (before fix)
```

After my fix:
```
TestStartBatchProdBugGuard::test_start_batch_scans_injected_root_not_module_global   PASSED
TestStartBatchUsesInstanceRoot::test_start_batch_check_rawdata_status_receives_instance_root   PASSED
```

The tests are genuinely catching the prod bug, not incidentally passing.

---

## C5 — `_recover_orphan_running_runs` (§3 C5)

`_recover_orphan_running_runs` is a method of `RunManager`, not `BatchRunManager`. It uses only DB reads (`store.list_runs_by_status`) and PID operations (`_terminate_pid_if_running`). It does NOT reference `RAWDATA_ROOT` anywhere in its source (confirmed by `test_recover_orphan_source_does_not_reference_rawdata_root_global` static inspection test — passes). No change required.

---

## Open issues / out-of-scope items

1. **`delete_rawdata` machines_config fallback at line 1199** — currently `mc = machines_config if machines_config is not None else MACHINES_CONFIG`. When called from routes inside `create_app`, the route closure captures `mc` (the injected `machines_config`) correctly. This is functionally correct but the pattern differs from the instance-attr approach. Out of scope per brief §4.

2. **`_batch_gen_worker.py`** — the brief mentions this file "if affected". It does not exist as a separate file in this codebase; batch-gen worker logic is inline in `app.py`. No separate file change needed.

3. **Virtual-console subprocess smoke (§3 C4)** — impl-verifier owns this per Wave 2 split. Not implemented here.

---

## Risk notes

- **Minimal delta**: exactly 9 lines changed (1 line replaced with 9). Single call-site. No interface changes, no new parameters added to any public API.
- **Backward compat**: `check_rawdata_status` already accepted `rawdata_root` and `machines_config` as optional params. Passing them explicitly at this call site has no backward-compat risk.
- **Rollback**: `git revert <sha>` restores the bug. Single-responsibility commit.
- **`machines_config` bonus**: also passed `machines_config=self._machines_config` to `check_rawdata_status` at the same call site, matching the pattern already used at line 6102 (`check_rawdata_status(machine, mode, rawdata_root=rd_root, machines_config=mc)`). This is strictly correct — `check_rawdata_status` uses `machines_config` to compute upstream MD5 for classification.
