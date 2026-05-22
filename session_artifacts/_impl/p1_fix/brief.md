# P1-fix Implementation Brief

> **Date**: 2026-05-17
> **Follow-up to**: commit `cec5012` (P1 of deploy migration)
> **Critique input**: `session_artifacts/_impl/p1/critique.md` (impl-critic verdict APPROVE-WITH-FIXES, 5 blockers + 2 optional)
> **Coordinator**: main session
> **Agent flow**: `impl-implementer` → `impl-tester` → `impl-verifier` → `impl-critic` (each reads previous's summary; final critic gates the commit)

---

## §1 Context

P1 (commit `cec5012`) was implemented solo and shipped with 5 blocking gaps that the retroactive `impl-critic` review caught. Per `memory/feedback_impl_team_required.md` we are now running the proper 4-agent loop for the fix.

The fix is **additive** to P1 — same Phase 1 scope (atomic config writes + WAL + cross-process index lock), just covering call sites P1 missed. Backward-compat invariant (single-user dev workflow unchanged) still holds.

---

## §2 Scope — 5 blocker fixes (BLOCKING for P2)

### Fix 1: Migrate 6 surviving index.json / latest.json write paths

Critique §3 items 1-3 + §8 required fix 1.

The `replace_all=True` migration in P1 only caught 3 of the 9 call sites that write to `<reports>/<machine>/mode_<n>/index.json` + `latest.json`. The 6 surviving non-atomic writers re-introduce the Scenario 16 lost-update race in delete / prune paths:

| File:line | Function | Pattern |
|---|---|---|
| `src/web_console/backend/app.py:5226` | `RunManager.delete_run` | `write_json(index_path, filtered)` |
| `src/web_console/backend/app.py:5231` | `RunManager.delete_run` | `write_json(latest_path, filtered[-1])` |
| `src/web_console/backend/app.py:7889` | DELETE /api/reports/{m}/{mode}/{v} | `index_path.write_text(...)` |
| `src/web_console/backend/app.py:7908` | DELETE /api/reports/{m}/{mode}/{v} | `latest_path.write_text(...)` |
| `src/web_console/backend/app.py:8510` | POST /api/maintenance/prune-versions | `index_path.write_text(...)` |
| `src/web_console/backend/app.py:8527` | POST /api/maintenance/prune-versions | `latest_path.write_text(...)` |

**Action**: replace each with `atomic_json_write(...)` — `index_path` writes take the list payload; `latest_path` writes take the single-item dict payload. Match argument shapes to existing usage at app.py:5089-5091 / 7076-7077 / 7358-7359.

**Verification helper**: add a regression test that greps for `write_json\(index_path` / `write_json\(latest_path` / `index_path\.write_text` / `latest_path\.write_text` in app.py and asserts 0 matches.

### Fix 2: Add `_STATIC_ATTRS_CACHE` guard (parallel to `_LOCK_CACHE_GUARD`)

Critique §3 item 4 + §8 required fix 2.

`_load_static_attrs` (app.py:2285-2305) + `_save_static_attrs` (app.py:2308-2315) have the IDENTICAL TOCTOU pattern that the `_LOCK_CACHE_GUARD` fix closed for `_LOCK_CACHE`. P1 deliverable #8 named only `_LOCK_CACHE` but the parallel pattern is a known gap.

**Action**:
- Add `_STATIC_ATTRS_CACHE_GUARD = threading.Lock()` next to the cache declaration (search `_STATIC_ATTRS_CACHE:` to find it)
- Wrap the check-then-update in `_load_static_attrs` with `with _STATIC_ATTRS_CACHE_GUARD:` (mirror the `_load_rawdata_locks` shape)
- Wrap the cache update in `_save_static_attrs` after `atomic_json_write` returns

**Out of scope**: `_MACHINES_SUMMARY_CACHE` and `_RAWDATA_OVERVIEW_CACHE` have slightly different access patterns (cache-key-keyed, not single-slot); critique §2 Q7 notes them but they are deferred to P2 unless trivial to include without scope creep.

### Fix 3: Fix vacuous WAL test assertion

Critique §3 item 9 + §8 required fix 3.

`tests/backend/test_phase1_atomic_migrations.py:96`:

```python
assert (tmp_path / "test.db-wal").exists() or (tmp_path / "test.db").stat().st_size > 0
```

The right disjunct is always true → test passes even if WAL pragma is removed. **Action**: replace with `assert (tmp_path / "test.db-wal").exists(), "WAL sidecar missing — PRAGMA journal_mode=WAL silently failed?"`.

### Fix 4: Add MD5 refresh thread tests

Critique §4 item 2 + §8 required fix 4.

`_refresh_md5_async` (app.py:5852-5876) writes `state/console/md5_refresh_error.json` on failure and unlinks it on success — no test exercises either path. Per `memory/feedback_no_silent_swallow.md`, a write-to-disk diagnostic that isn't itself verified is suspect.

**Action**: Add test(s) that:
- Monkeypatch `_do_refresh_machines_md5` to raise → invoke `_refresh_md5_async` (or extract the closure to a module-level helper that's testable) → assert `md5_refresh_error.json` exists with `ts` / `server_id` / `error` fields
- Monkeypatch to succeed after a prior failure → assert the file is cleared
- Verify parent-dir creation: pre-condition with `sd` not yet existing → assert mkdir works

**Implementation note**: the closure `_refresh_md5_async` is nested inside `start_batch_run`; impl-implementer should either extract the disk-write logic to a top-level helper `_persist_md5_refresh_error(sd, server_id, exc)` + `_clear_md5_refresh_error(sd)`, OR test via the full FastAPI TestClient hitting `POST /api/batch-run`. The helper-extraction path is preferred for test clarity.

### Fix 5: Add cross-process lock degradation diagnostic

Critique §3 item 6 + §8 required fix 5 + memory `feedback_no_silent_swallow.md`.

`_cross_process_index_lock` in `fresh_slotlab/rawdata_index.py:107-145` has 3 silent fallthrough points:
1. `lockfile` open fails (line 114) — degrade to within-process-only, no diagnostic
2. `msvcrt.locking` fails on Windows (line 131) — same
3. `fcntl.flock` fails on POSIX (line 144) — same

When any of these silently degrade, ProcessPoolExecutor workers go back to racing on `_index.json`. Operators get no signal.

**Action**: On any degradation path, write a one-shot diagnostic to disk at `<rawdata_root>/_index.json.lock_degraded.json` with:
```json
{
  "ts": "<iso8601>",
  "platform": "<sys.platform>",
  "reason": "<one of: lockfile_open_failed / msvcrt_locking_failed / fcntl_flock_failed>",
  "error": "<exc class name + message>"
}
```

The file is one-shot — if it already exists, don't overwrite (avoid log spam). Operators see "safety degraded since <ts>" and can investigate. Re-arming requires manual delete.

**Out of scope**: a corresponding "lock recovered" event when subsequent attempts succeed; complexity outweighs benefit for P1-fix.

---

## §3 Optional improvements (non-blocking but recommended)

### Optional A: Refactor `_stats_holder` pattern (critique §3 item 7)

`app.py:8260` uses `_stats_holder: list[dict] = []` with `[0]` read-after-rmw. Brittle if `atomic_json_read_modify_write` ever gains retry semantics.

**Action**: Replace with single-element dict and explicit replacement: `_stats_holder["stats"] = stats_local` inside modifier; `stats = _stats_holder["stats"]` after rmw. Or use `nonlocal` keyword with a sentinel.

### Optional B: Path case normalization for `_lock_for` (critique §3 item 10)

On Windows, `Path.absolute()` doesn't normalize case. Two callers with different-case paths get different locks → race.

**Action**: In `src/web_console/backend/config_writer.py:_lock_for`, use `Path(path).resolve()` instead of `Path(path).absolute()`. Document the behavior in module docstring.

---

## §4 Out of scope for P1-fix

- `_MACHINES_SUMMARY_CACHE` / `_RAWDATA_OVERVIEW_CACHE` TOCTOU (critique §2 Q7): different access pattern, defer to P2 unless trivial
- Replace `replace_all=True` static-check grep CI (critique §9 item 4): tooling change, defer
- `_save_settings` ensure_ascii format change (critique §2 Q5, §7): documented but not reverted; preserve P1 behavior to avoid extra diff
- `inject-bug` recipe refinement (critique §2 Q9): commit-message wording issue, not code
- New code paths from P2/P3/P4: not in scope

---

## §5 Constraints (must hold)

1. **Backward-compat**: single-user dev workflow remains unchanged (modulo the 3 already-documented cosmetic changes from P1: WAL sidecars, error-file artifact, ensure_ascii encoding)
2. **No tech stack replacement**: `FastAPI + uvicorn + SQLite + ProcessPoolExecutor` stays
3. **Stack-locked imports**: only `threading`, `msvcrt`, `fcntl`, `pathlib`, `json`, `os` — no new dependencies
4. **No silent failures**: per `memory/feedback_no_silent_swallow.md`, every new `except: pass` either persists a diagnostic or has explicit "this is the last-resort fallback, no further recovery possible" rationale in a comment

---

## §6 Memory feedback files to honor

- `memory/feedback_enumerate_safety_paths.md` — the WHOLE reason for Fix 1 (P1 missed 6 paths). Every fix must include inject-bug verification.
- `memory/feedback_no_silent_swallow.md` — Fix 4 + Fix 5 are directly motivated
- `memory/feedback_md5_is_a_tag_not_a_destruction_signal.md` — no new destruction logic; preserve
- `memory/feedback_subprocess_import_suicide_and_module_globals.md` — `_STATIC_ATTRS_CACHE_GUARD` is module-global; verify subprocess import still safe
- `memory/feedback_respect_existing_codebase.md` — minimum-delta extends the existing pattern; no rewrites
- `memory/feedback_adversarial_self_review.md` — the reason we're using the impl-* loop instead of solo

---

## §7 Test plan (impl-tester deliverables)

1. **Regression grep test** for Fix 1: assert no `write_json\(index_path|write_json\(latest_path|index_path\.write_text|latest_path\.write_text` in `src/web_console/backend/app.py`.
2. **Concurrent delete + finalize test** for Fix 1: simulate `RunManager.delete_run` racing with `_update_report_index` on same `(machine, mode)`; assert no lost updates in `index.json`.
3. **`_STATIC_ATTRS_CACHE` concurrent load/save test** for Fix 2: N threads alternating between `_load_static_attrs` and `_save_static_attrs`; assert `(mtime, data)` consistency.
4. **Vacuous WAL test fix** for Fix 3: replace assertion; inject-bug verify (remove WAL pragma → test fails).
5. **MD5 refresh error persistence tests** for Fix 4: failure → file written; success-after-failure → file cleared; mkdir for missing `sd`.
6. **Cross-process lock degradation test** for Fix 5: monkeypatch `msvcrt.locking` to raise → invoke `_cross_process_index_lock` → assert diagnostic file exists with correct schema.
7. **Inject-bug for each new lock** per `memory/feedback_enumerate_safety_paths.md`: remove the protection → corresponding test fails → revert → green.

---

## §8 Verification (impl-verifier deliverables)

1. Full Phase 1-related test sweep: `tests/backend/test_config_writer.py`, `test_phase1_atomic_migrations.py`, `test_rawdata_index.py`, `test_health_endpoints.py`, `test_run_lifecycle.py`, `test_cache_cleanup.py`, `test_safety_interlock.py`, `test_batch_completion_visibility.py`, `test_delete_report_version.py` (since fix 1 touches DELETE path).
2. Smoke import: `from src.web_console.backend.app import create_app; app = create_app()` (catches init-order regressions from the new guard).
3. Confirm no new `except: pass` in diff without a paired diagnostic write (manual grep).
4. Confirm the regression-grep test for Fix 1 itself runs (catches the meta-gap "test added but skipped").

---

## §9 Commit-message draft (for impl-critic to fact-check)

```
fix(phase1-deploy): close 5 P1 blockers caught by retroactive impl-critic

Follow-up to cec5012 — the retroactive impl-critic run (verdict
APPROVE-WITH-FIXES, see session_artifacts/_impl/p1/critique.md)
identified 5 blocking gaps before P2 can build on P1's "all config
writes atomic" assumption.

Fix 1 — Migrate 6 surviving index.json / latest.json write paths
  ...
Fix 2 — _STATIC_ATTRS_CACHE TOCTOU guard
  ...
Fix 3 — Fix vacuous WAL test assertion
  ...
Fix 4 — MD5 refresh thread error persistence tests
  ...
Fix 5 — Cross-process lock degradation diagnostic
  ...

## Verified happy path
- All P1-related test suites green (NN tests)
- Regression grep test confirms no surviving non-atomic index.json
  / latest.json writers in app.py
- ...

## Verified failure paths
- Inject-bug for each new lock/guard (5 inject-bug exercises)
- ...

## Not verified
- ...

## Tests added
- ...

Co-Authored-By: ...
```

---

## §10 Out-of-loop after this commit

After this P1-fix commit lands:
- Run impl-critic ONE more time on the fix to confirm clean (in case fix introduces new issues)
- If clean → P2 begins (CellLockRegistry atomic cutover) with the same impl-* 4-agent loop
- If new issues → loop back to impl-implementer for further iteration
