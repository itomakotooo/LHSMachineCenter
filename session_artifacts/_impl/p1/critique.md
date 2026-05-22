# P1 Implementation Critique (impl-critic style)

> Adversarial review of commit `cec5012` against Phase 1 spec
> (`session_artifacts/_arch/deploy/04_deploy_architecture_proposal_v2.md` §6 deliverables 1-11)
> Anchored to W1 (01/02/03) + W3 (05 critic / 06 validator) findings.
> Read-only on code; diff is source of truth.

---

## §1 Top concerns (5)

1. **Critical C1 fix is incomplete — race window survives in `RunManager.delete_run`.** The migration enumerated 3 sites in `_update_report_index`-related code paths (app.py:5089/7074/7355, all GREEN), but four sibling write paths to `index.json` / `latest.json` were missed: `app.py:5226` (`write_json(index_path, filtered)`), `app.py:5231` (`write_json(latest_path, filtered[-1])`), `app.py:7889` (`index_path.write_text(...)` in delete-version), `app.py:7908` (`latest_path.write_text(...)`), `app.py:8510` and `app.py:8527` (prune-versions). These rewrite the SAME `index.json` files protected by atomic writes at the other 3 sites. Two concurrent operations — e.g. a "finalize batch generate" at app.py:7076 and a "delete run" at app.py:5226 hitting the same `<reports>/M14/mode_1/index.json` — race on read-modify-write; the per-file `threading.Lock` in `config_writer.py` is scoped to atomic_json_write callers, so `write_json` / `write_text` bypass it entirely. This is the exact W1 Scenario 16 pattern, only one race window narrower, and `feedback_enumerate_safety_paths.md` explicitly warns about this kind of partial-coverage fix.

2. **Phase 1 deliverable #8 (`_LOCK_CACHE` TOCTOU guard) was applied selectively — `_STATIC_ATTRS_CACHE` has the IDENTICAL pattern and was NOT guarded.** `_load_static_attrs` (app.py:2285-2305) does an unguarded check-then-update on `_STATIC_ATTRS_CACHE["mtime"]` / `_STATIC_ATTRS_CACHE["data"]`; `_save_static_attrs` (app.py:2308-2315) updates them outside any lock right after `atomic_json_write` returns. Two concurrent calls can leave `(mtime, data)` inconsistent — the exact bug the `_LOCK_CACHE_GUARD` fix closes for `_LOCK_CACHE`. The commit message claims the guard is a "minor TOCTOU fix"; if it's worth fixing for one cache, the spec scope dropped the parallel for the other. This is a known-pattern miss, not a future-phase concern.

3. **WAL sidecar test is vacuous — assertion can't fail.** `tests/backend/test_phase1_atomic_migrations.py:96` reads `assert (tmp_path / "test.db-wal").exists() or (tmp_path / "test.db").stat().st_size > 0`. The right side is true for any non-empty DB file, which is always true after `_init_db()`. If WAL pragma were removed, the test would still pass. The other two WAL tests (`test_wal_mode_enabled_after_init` / `test_busy_timeout_set`) correctly check the pragma readback, but this one is dead. Inject-bug: comment out `PRAGMA journal_mode=WAL` — the first two tests fail, this one still passes.

4. **MD5 refresh thread error persistence has no consumer in P1 — claim "Phase 2 will read it" doesn't validate it works.** `state/console/md5_refresh_error.json` is written when the background MD5 refresh fails (app.py:5867), and cleared on success (app.py:5861), but nothing in the P1 code reads it back. The commit message acknowledges this under "Not verified," but the implication is the diagnostic landing on disk hasn't been verified at all — neither the JSON content shape, nor whether parent-dir creation works under the test fixture's `sd`. If the write fails (e.g. `sd` doesn't exist; tests passing in `tmp_path` could pre-create it but production might not pre-create `state/console/` before the thread fires), the outer `except OSError: pass` swallows it. This is exactly the pattern `feedback_no_silent_swallow.md` warns against: a best-effort write whose failure is silently dropped, with no diagnostic about the diagnostic failing.

5. **Cross-process lock degradation is silently safe-fallback to in-process-only — violates `feedback_no_silent_swallow.md`.** `_cross_process_index_lock` in `fresh_slotlab/rawdata_index.py:78-162` catches `(OSError, ImportError)` around both the `lockfile` open AND the `msvcrt.locking` / `fcntl.flock` calls and degrades silently — comments say "rare" but cite no diagnostic write. Realistic causes: (a) network share (the deploy README forbids it but operators don't always read), (b) AV / EDR scanner holding the file briefly (`msvcrt.locking` has 10s timeout then raises `OSError`), (c) lockfile permission issue. When the OS lock silently fails, ProcessPoolExecutor workers go back to racing — the exact H3 hazard the lock was meant to close. Per `feedback_no_silent_swallow.md`, this fallthrough should write a diagnostic to disk (e.g. `_index.json.lock_degraded.json`) so operators see when safety has degraded. As-is, the test `test_concurrent_subprocess_writes_no_lost_entries` would also pass if degradation kicked in but the 4-subprocess timing happened to serialize naturally — see §2 Q3.

---

## §2 Stress questions (15)

### Q1: Did all `machines.json` write paths get migrated?
**Attempt at answer**: The commit message claims `_do_refresh_machines_md5` at app.py:8216 is THE write path. Grep for `machines.json` in backend.
**Verdict**: ✓ adequately addressed
**Evidence**: `Grep machines\.json src/web_console/backend/` shows references in app.py and machine_variants.py — only one ACTUAL write site (`atomic_json_read_modify_write(Path(mc), _apply, ...)` at app.py:8270). All other matches are comments / reads / MACHINES_CONFIG constant. Critical C1 race closed for this file.

### Q2: Did all 3 `_update_report_index`-style index/latest writes migrate, or are there sibling paths?
**Attempt at answer**: Commit message says 3 sites at 5089/7074/7355 migrated with `replace_all=True`. Grep for parallel patterns.
**Verdict**: ✗ not addressed
**Evidence**: `Grep write_json|write_text` in app.py reveals UN-migrated index.json/latest.json writers at app.py:5226, 5231 (`RunManager.delete_run`), 7889, 7908 (delete-version), 8510, 8527 (prune-versions). These rewrite the same `index.json` files that the 3 migrated sites protect. Concurrent `delete_run` + `finalize_batch_gen_item` against same machine+mode race on read-modify-write of `<reports>/<m>/mode_<n>/index.json`. This is concern #1 above.

### Q3: Does the 4-subprocess cross-process test actually overlap, or do subprocesses serialize naturally?
**Attempt at answer**: Test spawns 4 subprocesses via `subprocess.Popen` without `.wait()` between them, then collects all stdouts via `communicate(timeout=60)`. Each subprocess imports rawdata_index and calls update_entry once.
**Verdict**: ⚠ partial — overlap unclear
**Evidence**: Test at `tests/backend/test_phase1_atomic_migrations.py:201-208` spawns all 4 procs in a tight loop without joining; each subprocess's startup cost (Python interpreter init + import `fresh_slotlab.rawdata_index`) is ~100-500ms, while the actual `update_entry` is sub-millisecond. The 4 subprocesses likely have overlapping startup BUT serial-ish `update_entry` calls. The test passing demonstrates the lock works **when overlap happens** but doesn't prove overlap actually occurs in this fixture. Inject-bug check (remove `with _cross_process_index_lock` and run repeatedly) would expose this — the commit message documents the recipe but the run isn't reproduced in CI. Probability is small but the W3 critic CI-3 motivation (100ns NTFS granularity) requires VERY tight overlap to manifest.

### Q4: Does `replace_all=True` migration of `write_json(index_path, ...)` → `atomic_json_write(index_path, ...)` capture ALL the right sites?
**Attempt at answer**: The commit message says the `_update_report_index` migration used `replace_all=True` for `write_json(index_path, index_payload)\n            write_json(latest_path, item)` patterns.
**Verdict**: ⚠ partial
**Evidence**: `Grep atomic_json_write\(index_path|atomic_json_write\(latest_path` in app.py returns 6 hits at 5090, 5091, 7076, 7077, 7358, 7359 — three call sites times two writes each. The replace_all pattern caught only the `write_json(index_path, index_payload)` shape (varied `index_payload` variable name). It MISSED `write_json(index_path, filtered)` (5226), `write_json(latest_path, filtered[-1])` (5231), and ALL `index_path.write_text` / `latest_path.write_text` raw forms (7889/7908/8510/8527). The implementer trusted `replace_all` to find all index.json writers but in fact only caught lexical matches.

### Q5: Backward-compat — `_save_settings` quietly changed output format.
**Attempt at answer**: Single-user dev workflow unchanged claim. Migration `_save_settings` switched from raw `tmp.write_text(json.dumps(data, indent=2))` to `atomic_json_write(data)` which internally uses `json.dumps(data, ensure_ascii=False, indent=2)`.
**Verdict**: ⚠ partial — observable file format changed
**Evidence**: Old (`cec5012~1:app.py:839`): `json.dumps(data, indent=2)` (ascii-escapes non-ASCII). New: `json.dumps(data, ensure_ascii=False, indent=2)`. Result: if `settings.json` ever contains non-ASCII (operator names, file paths in non-ASCII locales), the file now stores native UTF-8 (`策划`) instead of escapes (`策划`). Round-trip semantically identical via `json.loads`, but the file diff between dev runs would now show whitespace/encoding changes. Backward-compat claim should be qualified.

### Q6: Does `sd` capture in `_refresh_md5_async` survive multiple `create_app()` calls?
**Attempt at answer**: `sd` is the local variable in `create_app` at app.py:5327. Closure-captured by `_refresh_md5_async`. Each `create_app` call gets its own `sd`.
**Verdict**: ✓ adequately addressed
**Evidence**: `sd = state_dir if state_dir is not None else STATE_DIR` (app.py:5327). Each `create_app` call has its own `_refresh_md5_async` closure with its own `sd`. Test fixtures pass `state_dir=tmp_path`; production uses STATE_DIR. No cross-test pollution. Not a concern.

### Q7: `_LOCK_CACHE_GUARD` applied; `_STATIC_ATTRS_CACHE` parallel pattern NOT guarded.
**Attempt at answer**: Phase 1 deliverable 8 was `_LOCK_CACHE` only. `_STATIC_ATTRS_CACHE` has the same TOCTOU shape.
**Verdict**: ✗ not addressed — known gap
**Evidence**: `_load_static_attrs` at app.py:2285-2305 reads `_STATIC_ATTRS_CACHE["data"]` and `_STATIC_ATTRS_CACHE["mtime"]` then updates both without a lock. `_save_static_attrs` at app.py:2308-2315 updates them after `atomic_json_write` returns, also unlocked. Two threads racing on save+load can observe `(stale_mtime, fresh_data)` or `(fresh_mtime, stale_data)`. The exact same pattern is fixed for `_LOCK_CACHE`. This is concern #2. Same issue exists for `_MACHINES_SUMMARY_CACHE` (app.py:2009) and `_RAWDATA_OVERVIEW_CACHE` (app.py:2052) though their access patterns are slightly different (cache_key keyed, not single-slot).

### Q8: chart.js — is it the UMD bundle that exposes global `Chart`?
**Attempt at answer**: index.html uses `<script src="/console/vendor/chart.min.js?v={{ASSET_HASH}}"></script>` (no `type="module"`), so it must be a UMD/IIFE bundle exposing global `Chart`.
**Verdict**: ✓ adequately addressed
**Evidence**: `Bash head -25 chart.min.js` shows `(t="undefined"!=typeof globalThis?globalThis:t||self).Chart=e()` (UMD wrap) and the file header reads `Original file: /npm/chart.js@4.4.6/dist/chart.umd.js`. Correct bundle. The `/console/vendor/` URL resolves through the StaticFiles mount at app.py:5415 since FRONTEND_DIR includes `vendor/` subdir.

### Q9: Inject-bug claim — `WinError 32` actually proves the race?
**Attempt at answer**: Commit message says removing the lock and rerunning the test produced `PermissionError (WinError 32)` from `os.replace`. WinError 32 = "the process cannot access the file because it is being used by another process."
**Verdict**: ⚠ partial — proves SOMETHING goes wrong but unclear it's lost-update specifically
**Evidence**: WinError 32 happens when Writer A's `.tmp` is open in another thread while Writer B's `os.replace` tries to swap. The test assertion is `sorted(final["items"]) == list(range(N))` — counts items in final file. A `PermissionError` raised in `atomic_json_read_modify_write` (which is what the inject-bug branch produces) causes the thread to fail with an exception. Python's `threading.Thread.run` swallows the exception silently. So when the thread crashes, its item isn't appended. The test then sees fewer than N items and fails — which IS lost-update, but the proximate cause is "thread crashed mid-rmw," not "second writer overwrote first writer's view." These are different bug modes with the same test signal. The race the lock is meant to prevent (lost update via stale baseline) is qualitatively different from the race the inject-bug actually exhibits (write contention raising PermissionError). The test catches both, which is fine, but the inject-bug recipe doesn't precisely model the Scenario 16 race; it models a related but different race that produces the same test failure.

### Q10: Memory feedback adherence — `feedback_no_silent_swallow.md` — does any new code violate it?
**Attempt at answer**: New code added two `except OSError: pass` patterns and several similar swallows.
**Verdict**: ⚠ partial — one acceptable instance, one questionable
**Evidence**:
- `_refresh_md5_async` outer `except Exception` (app.py:5864) — NOW correctly writes diagnostic to disk. ✓
- `_refresh_md5_async` inner `except OSError: pass` (app.py:5875) for the diagnostic write itself — the comment says "no infinite recursion of logging" but this is the EXACT pattern the feedback warns about: a best-effort write that silently fails. No fallback path (e.g. `sys.stderr` log, single-shot module global). ⚠
- `_cross_process_index_lock` 3 silent swallows (rawdata_index.py:114, 131, 144) on file-open + msvcrt + fcntl failures — degrade to in-process-only with NO diagnostic. ✗ This is concern #5.
- `_save_static_attrs` mtime read swallow at app.py:2313 — same as old code, accepted carryover.
- `_save_rawdata_locks` mtime read swallow at app.py:2253 — same as old, accepted.

### Q11: WAL sidecar test pollution between tests.
**Attempt at answer**: Tests use `tmp_path` which is per-test-function isolated. WAL sidecars are created in `tmp_path`.
**Verdict**: ✓ adequately addressed
**Evidence**: `Bash ls state/console/` shows only `.gitkeep` — no leftover wal/shm in repo. All WAL tests use `tmp_path` (test_phase1_atomic_migrations.py:50/61/72 — `db_path = tmp_path / "test.db"`). pytest cleans `tmp_path` automatically. No risk of cross-test contamination via repo state.

### Q12: Atomic rmw cross-process safety — `config_writer.py` is in-process-only.
**Attempt at answer**: `config_writer.py` doc explicitly says "In-process only" and points to `_cross_process_index_lock` pattern.
**Verdict**: ✓ adequately addressed for P1 scope, ⚠ documented limitation
**Evidence**: `config_writer.py:30-37` explicitly documents this. The migrated config files (`machines.json`, `servers.json`, `settings.json`, `rawdata_locks.json`, `machines_static.json`, `machine_halls.json`, `index.json`, `latest.json`) are all written ONLY from the main backend process — `ProcessPoolExecutor` workers only touch chunk files + sidecar `_chunks.json` + `_index.json`. The cross-process risk is specifically for `_index.json`, which is handled separately. So in-process-only is correct for P1 scope. **However**: future Phase 3 config upload endpoints may make this assumption fragile if subprocess workers ever read/write `configs/uploaded_configs/`.

### Q13: `trailing_newline=True` inconsistency.
**Attempt at answer**: `save_servers` and `_do_refresh_machines_md5` use it; others don't. Git diff for unchanged content.
**Verdict**: ✓ no issue — consistent with old behavior per call site
**Evidence**: Comparing old vs new:
- `save_servers` old: `json.dumps(...) + "\n"` → new `trailing_newline=True` ✓ match
- `_do_refresh_machines_md5` old: `json.dumps(...) + "\n"` → new `trailing_newline=True` ✓ match
- `_save_settings` old: `json.dumps(...)` (no `+ "\n"`) → new no `trailing_newline` ✓ match
- `_save_static_attrs`, `_save_rawdata_locks`, halls writes — all old also no `\n` → new no `trailing_newline` ✓
The configs/ files are not committed in this commit so there's no whitespace diff to assess. But `_save_settings` does have the `ensure_ascii` format change noted in Q5.

### Q14: Tests pollute repo `state/console/` directory?
**Attempt at answer**: Tests use `tmp_path` but check if any new test writes to repo-relative path.
**Verdict**: ✓ adequately addressed
**Evidence**: `Grep state/console tests/backend/` returns no matches. All new tests use `tmp_path` for db/state-dir. No repo-side pollution.

### Q15: pytest version + parallel safety — `pytest-xdist` scenario.
**Attempt at answer**: Tests don't specify a pytest config for serial-only.
**Verdict**: ⚠ partial — undocumented assumption
**Evidence**: `python -m pytest` ran fine sequentially (28 tests, 2.38s). However, no `conftest.py` constraint enforces `-p no:xdist` or warns if running with `-n auto`. Both `_FILE_LOCKS` (config_writer.py:42) and `_INDEX_LOCK` (rawdata_index.py:75) are module globals; under `xdist` each worker gets its own process and its own module global, so in-process locks don't help across xdist workers. For `test_concurrent_subprocess_writes_no_lost_entries`, the test would actually still work under xdist because it spawns its own subprocesses and uses the OS-level lock. For `test_concurrent_rmw_no_lost_updates`, the test stays inside a single worker process so threading.Lock works. No actual breakage, but a future test writer who uses `tmp_path` shared via `tmp_path_factory.session_scope` could hit cross-worker races. Worth a `pytest.ini` note.

---

## §3 Code-level bugs / risks

1. **`src/web_console/backend/app.py:5226` and `app.py:5231`** — `RunManager.delete_run` uses bare `write_json` to rewrite `index.json` and `latest.json` after a run delete. Same file is protected by `atomic_json_write` at app.py:5090/5091. Concurrent delete + finalize races. (Critical: P1 deliverable scope gap.)

2. **`src/web_console/backend/app.py:7889, 7908`** — DELETE-version endpoint rewrites `index.json` / `latest.json` via raw `write_text`. Same file. Same race. (Critical: same gap.)

3. **`src/web_console/backend/app.py:8510, 8527`** — prune-versions admin endpoint rewrites `index.json` / `latest.json` via raw `write_text`. Same file. Same race. (Medium: rare admin op.)

4. **`src/web_console/backend/app.py:2285-2315`** — `_STATIC_ATTRS_CACHE` TOCTOU not guarded; identical pattern to the fixed `_LOCK_CACHE`. (Medium: race window is brief but real.)

5. **`src/web_console/backend/app.py:5875`** — `except OSError: pass` on the diagnostic-write itself, with no fallback channel (stderr / module global). Violates `feedback_no_silent_swallow.md`. (Low for correctness; high for debuggability when prod has issues.)

6. **`fresh_slotlab/rawdata_index.py:114, 131, 144`** — silent fall-through to in-process-only lock when OS-level lock fails. No diagnostic. Operators won't know safety is degraded. (Medium: deploy on edge-case filesystem could silently lose entries.)

7. **`src/web_console/backend/app.py:8260, 8274`** — `_stats_holder` pattern (list append from modifier closure, read `[0]` after rmw). Brittle: if `atomic_json_read_modify_write` ever gains internal retry (e.g. for FS recovery), this breaks. Defensive pattern: should be `_stats_holder["stats"] = ...` dict OR return tuple from modifier. (Low: current code doesn't retry; latent.)

8. **`src/web_console/backend/app.py:8270`** — Uses `default={"machines": []}` but `_apply` does `base = current if isinstance(current, dict) else {"machines": []}`. The `default` is already a dict, so the `isinstance` check is redundant in the happy path but defensive against `default=None`. Minor inconsistency: caller specifies `default={"machines": []}` (so `current` is always a dict), modifier still does the isinstance check.

9. **`tests/backend/test_phase1_atomic_migrations.py:96`** — vacuous WAL sidecar assertion (`or db.stat().st_size > 0`). Cannot fail. (Low: doesn't break things, but loses regression value.)

10. **`config_writer.py:79`** — `path = Path(path)` re-wraps an already-Path argument harmlessly, but the `_lock_for` call right after uses `key = str(Path(path).absolute())` — that's `str` on the absolute path. On Windows, `Path.absolute()` does NOT resolve case differences (`c:\foo` vs `C:\Foo` → different keys). If two callers pass paths differing only in case, they get DIFFERENT locks → race. Real-world risk depends on whether code ever constructs path strings from user input with case variation. Low for current call sites (all hardcoded module constants). (Low: latent.)

---

## §4 Test-level gaps

1. **No test for migrated `save_servers` / `_save_settings` / `_save_static_attrs` / `_save_rawdata_locks` / halls writes via the actual function call**: only `atomic_json_write` directly is tested. If someone later breaks `save_servers` by reverting to `write_text`, no test catches it. The `replace_all=True` migration trusts grep, not test coverage.

2. **No end-to-end test for `_refresh_md5_async` error persistence path**: commit message explicitly says "Not verified — code path written but not exercised by a test." The disk write logic includes a `mkdir parents=True` + `write_text` that could fail if `sd` doesn't exist; never exercised. The "clear on success" branch (app.py:5859-5863) also untested.

3. **No test verifying `_cross_process_index_lock` degrades correctly**: the silent fall-through path (rawdata_index.py:114, 131, 144) is asserted to be safe but no test forces the degraded path (e.g. by monkeypatching `msvcrt` to raise ImportError, or by chmod-ing the lockfile). If a future refactor breaks the fall-through, no test catches it.

4. **Test `test_concurrent_subprocess_writes_no_lost_entries` may pass without lock — see §2 Q3**: 4 subprocesses each touching a DIFFERENT cell; per-cell scan is independent. The contention is only on `_index.json` itself, and with the test fixture's subprocess startup cost, real overlap during the actual `_save_index` call is uncertain. Commit message says inject-bug recipe (remove `_cross_process_index_lock`) shows "occasionally drop an entry" — "occasionally" admits low repro rate. Test isn't strong evidence for the lock's necessity.

5. **WAL sidecar test (`test_wal_sidecars_created_after_writes`)**: vacuous assertion — see §3 item 9.

6. **No test for sites NOT migrated**: the 4-6 surviving `write_json` / `write_text` sites for `index.json` / `latest.json` have no failing test asserting they SHOULD be atomic. Hard to retrofit, but a regression for "all index.json writes go through atomic_json_write" would be straightforward via grep-based test.

7. **No test for `_save_settings` ensure_ascii format change**: backward-compat-affecting behavior change isn't asserted either way.

---

## §5 Claim-vs-reality gaps

| Commit message claim | Actual diff/test state | Verdict |
|---|---|---|
| "71 tests green (28 new + 43 existing related)" | Verified via `pytest tests/backend/test_config_writer.py test_phase1_atomic_migrations.py -v` → 28 PASSED. Existing 43 not re-verified here but the claim is internally checkable; no evidence against. | ✓ |
| "Critical C1 fix: machines.json wipe race closed" | Closed for the `_do_refresh_machines_md5` path (the path the W1 Scenario 16 cited). The only writer to `machines.json` is at app.py:8270. | ✓ |
| "7 other config writers migrated" | Counts: `save_servers` ✓, `_save_settings` ✓, `_save_rawdata_locks` ✓, `_save_static_attrs` ✓, `_update_report_index` ×3 sites ✓, machine_halls.json ×2 ✓. **But** 6 sibling index.json writers were missed (§3 items 1-3). | ⚠ — true for the 7 enumerated, false for the broader "all atomic" implication |
| "Cross-process lock for rawdata/_index.json" | Implemented at rawdata_index.py:78-162. Wraps `update_entry` / `remove_entry` / `rebuild_full`. | ✓ |
| "SQLite WAL mode + busy_timeout=5000" | Verified via test pragmas. | ✓ |
| "MD5 refresh thread error persistence" | Code path exists at app.py:5852-5876; NO test exercises it; NO consumer reads the file. The disk write itself has untested OSError fall-through. | ⚠ — code written, behavior not validated |
| "chart.js vendored locally (v4.4.6 UMD)" | File exists at `src/web_console/frontend/vendor/chart.min.js`, ~201 KB, head reads `Chart.js v4.4.6` license, UMD wrap exposes global `Chart`. | ✓ |
| "Backward-compatible — single-user dev workflow unchanged" | Partially true; `_save_settings` quietly changed to `ensure_ascii=False` which alters file-content encoding for any non-ASCII setting values. | ⚠ |
| "Inject-bug: replaced lock with fresh per-call Lock → tests failed with WinError 32 → reverted → green" | The inject-bug DOES produce a test failure, but the proximate cause is `os.replace` PermissionError (thread crash), not the canonical "stale-baseline overwrite" race. The test catches both modes (both produce missing items in final list). Not a defect, but the recipe doesn't precisely model the bug it claims to. | ⚠ |
| "`_LOCK_CACHE_GUARD` selective fix" | Applied to `_LOCK_CACHE`. Parallel `_STATIC_ATTRS_CACHE` (same pattern) NOT guarded. Commit message frames the fix as targeted, but the W3 critique m5 / m3 mapping showed this pattern is repeated elsewhere. | ✗ — incomplete coverage of parallel pattern |

---

## §6 Memory feedback adherence audit

| Feedback file | Honored? | Citation |
|---|---|---|
| `feedback_enumerate_safety_paths.md` (M1\|1 lesson — enumerate all paths) | ⚠ partial | Three index.json migration sites were chosen by `replace_all=True` pattern match, but 4-6 sibling write paths to the SAME file were missed (§3 items 1-3). Exactly the M1\|1 antipattern: "lock X → 跑路径 → 断言 X 还在" works for migrated paths; un-migrated paths still write non-atomically. Inject-bug recipe exists for the lock; not for "concurrent delete_run + finalize finds clean index.json". |
| `feedback_no_silent_swallow.md` (best-effort failures persist diagnostic) | ⚠ partial | MD5 refresh OUTER swallow correctly replaced with disk-write (✓). MD5 refresh INNER `except OSError: pass` for diagnostic-write itself violates (no fallback channel, app.py:5875). Cross-process lock degradation has 3 silent `pass` branches with no diagnostic (rawdata_index.py:114, 131, 144). |
| `feedback_md5_is_a_tag_not_a_destruction_signal.md` | ✓ | No new code deletes data based on md5. The migration is atomic-write only, no destruction. |
| `feedback_subprocess_import_suicide_and_module_globals.md` | ✓ | `_FILE_LOCKS` and `_REGISTRY_GUARD` in config_writer.py are module globals, but config_writer.py is only imported by app.py / tests / NOT by analyzer subprocess. `_INDEX_LOCK` in rawdata_index.py IS imported by analyzer subprocess (via player_impact_analyzer.py:55), but each subprocess gets its own copy — the within-process lock semantics is correct, the OS-level lock provides cross-process. No import-suicide risk added. |
| `feedback_perf_claim_needs_e2e_event_stream.md` | ⚠ partial | Most claims have e2e tests (real subprocess spawn for cross-process test, real WAL pragma readback). MD5 refresh error persistence has no e2e test — commit message admits this. Inject-bug recipe documented but not auto-run in CI. |
| `feedback_capture_drift.md` | n/a | No API drift introduced. |

---

## §7 Backward-compat regression check

**Single-user dev workflow path**: user starts dev → settings POST → batch run → machines.json refreshed.

- **Settings POST**: `_save_settings` now writes `ensure_ascii=False`. If existing `settings.json` has non-ASCII (e.g. operator name), new save produces native UTF-8. `_load_settings` (app.py:829) uses `json.loads(read_text(encoding="utf-8"))` — round-trips fine. **Behavior change**: file diff shows UTF-8 reflow on first save after upgrade. Cosmetic but observable.

- **Batch run start**: triggers `_refresh_md5_async` thread (app.py:5844-5876). The thread now persists errors and clears them on success. New side effect: `state/console/md5_refresh_error.json` may appear (transient or persistent depending on success). **Behavior change**: new artifact file in state/console.

- **machines.json refresh**: atomic_rmw under per-file lock. For a single-user dev, no concurrent caller exists → no observable change. File ends up identical (write order same; trailing_newline preserved).

- **Run history view → delete run**: `RunManager.delete_run` rewrites index.json via NON-atomic `write_json` (app.py:5226). For single-user, no concurrent caller. No observable change. (But P1 deliverable spec implied this would be atomic — see §3.)

- **WAL mode on console.db**: persists across restarts. After P1 install, `console.db-wal` + `console.db-shm` sidecars appear. If user reverts P1 via `git revert`, the old code doesn't checkpoint WAL on exit; the .db-wal grows until next EXCLUSIVE connection. **Behavior change**: new sidecar files in state/console/; revert hazard documented in commit message (not verified to be benign in practice).

**Summary**: 3 observable changes (file-encoding cosmetic, new error file, WAL sidecars). None breaks workflow. Backward-compat claim is "mostly true" — should be qualified to "no behavioral regression for happy-path single-user dev; cosmetic file changes only."

---

## §8 Required fixes before P2 (BLOCKING)

1. **Migrate the 6 surviving index.json / latest.json write paths to atomic_json_write**: app.py:5226, 5231, 7889, 7908, 8510, 8527. Add a regression test that greps `index_path.write_text` / `latest_path.write_text` / `write_json\(index_path` / `write_json\(latest_path` in app.py and asserts 0 matches. (Closes the partial-fix gap that perpetuates the Scenario 16 race in delete/version-prune paths.)

2. **Add `_STATIC_ATTRS_CACHE` guard parallel to `_LOCK_CACHE_GUARD`**: same TOCTOU pattern, same fix. Either as part of P1 follow-up or explicitly defer with a comment + ticket. (P1 deliverable #8 scope was `_LOCK_CACHE`; the equivalent for `_STATIC_ATTRS_CACHE` is missing and the spec didn't list it as a known gap.)

3. **Fix the vacuous WAL test assertion**: change `or db.stat().st_size > 0` to `, "WAL sidecar missing — WAL pragma silently failed?"`. Currently the test passes when WAL is removed.

4. **Add MD5 refresh thread test**: at minimum a unit test that runs `_refresh_md5_async` with a stub `_do_refresh_machines_md5` that raises, then asserts `md5_refresh_error.json` exists in `sd` with the expected schema. Also a test for the clear-on-success path. (Commit message acknowledges this gap; before P2 builds on it, the disk-write should be proven to work.)

5. **Add diagnostic for cross-process lock degradation**: when `msvcrt.locking` / `fcntl.flock` / lockfile open fails, write a one-shot diagnostic to disk (e.g. `_index.json.lock_degraded.json`) so operators see safety has degraded. Per `feedback_no_silent_swallow.md`. Or commit to "degradation is theoretically possible but not flagged" with explicit reasoning.

---

## §9 Optional improvements (non-blocking)

1. Replace `_stats_holder: list[dict] = []` pattern (app.py:8260) with `nonlocal` or a single-element list with explicit `_stats_holder[:] = [stats_local]` to make the "expect exactly one append" invariant explicit. (Defensive; current code works.)

2. Add `Path.resolve()` to `_lock_for` (config_writer.py:79) to normalize case on Windows. (Latent issue; not currently triggered.)

3. Add a `pytest.ini` note that tests must run serially (no xdist) due to module-global locks for the in-process-lock tests. (Currently no breakage; documenting intent prevents future flake.)

4. Add a static-check (CI grep) asserting that no `write_json` / `write_text` calls remain for the canonical config files (machines.json, settings.json, etc.) — would have caught the partial migration. (Phase 2 deliverable per critic R2.1 pattern.)

5. Document the `_save_settings` format change (`ensure_ascii=False`) in commit message or CHANGELOG, since it affects file diffs in ops repos.

---

## §10 Verdict

**APPROVE-WITH-FIXES**

The P1 commit correctly closes the Critical C1 race on `machines.json` and adds the cross-process lock that W3 critic CI-3 demanded. The 28 new tests run green; the rmw lock mechanism is sound; chart.js vendoring is correct; WAL pragma is set. However, the migration was scoped to "the 7-8 writers the spec listed" rather than "all writers to the same protected files" — leaving 6 sibling write paths to `index.json` / `latest.json` un-atomic and re-introducing the very race the migration was meant to close in delete / prune paths (§3 items 1-3). Additionally, the `_LOCK_CACHE_GUARD` fix was applied selectively when the same TOCTOU pattern exists on `_STATIC_ATTRS_CACHE` (§3 item 4), and the WAL sidecar test is vacuous (§3 item 9). These are correctness-relevant gaps in P1's stated invariants — not deferrable to P2 because P2 builds on the assumption that "all config writes are atomic." Required fixes 1-3 in §8 must land before P2 starts. Fixes 4-5 are testing rigor that should land but aren't strictly blocking.
