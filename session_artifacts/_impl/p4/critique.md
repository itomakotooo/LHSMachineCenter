# P4 impl-critic: Critique

> Reviewed by impl-critic against brief §4 constraints + §5 memory feedback.
> Source of truth: uncommitted working tree on branch `claude/keen-wu-b8b520`, baseline `51af9a6`.

---

## Findings

### BLOCKER (must fix before commit)

**BLOCKER-1 — `LogonType InteractiveToken` makes task run ONLY when operator is logged in (breaks "start at boot" promise)**

File: `scripts/deploy/SlotConsole.xml` line 38.

The XML declares `<LogonType>InteractiveToken</LogonType>` with a `<BootTrigger>`. On Windows, `InteractiveToken` requires an active interactive logon session to exist. If the server boots and no operator has logged in (e.g. remote desktop not yet connected, or headless server), Task Scheduler cannot launch the task — the BootTrigger fires but the task is silently skipped until someone logs in. The correct logon type for an unattended boot-time service is `Password` (stores credentials at registration, requires Admin) or `S4U` (run-as without storing password, available on domain machines). The brief says "operator account, NOT SYSTEM" — that constraint is about which account, not about requiring interactive logon. `LogonType Password` satisfies both.

README_DEPLOY.md says nothing about this. The operator registering this task with `schtasks /Create /XML` will see no immediate error; the bug only surfaces after a reboot when no one is logged in, which is exactly the failure mode that breaks a self-healing server.

No test exercises boot-with-no-interactive-session because tests cannot register real scheduled tasks. This is an undocumented production failure with zero test coverage.

---

**BLOCKER-2 — `[int]($env:SLOT_DEPLOY_INJECT_UVICORN_FAIL)` throws when env var is unset (null-to-int cast)**

File: `scripts/start_console.ps1` line 50.

In PowerShell, `$env:SLOT_DEPLOY_INJECT_UVICORN_FAIL` returns `$null` when unset. `[int]$null` is 0, which is fine. But `[int]($env:SLOT_DEPLOY_INJECT_UVICORN_FAIL)` — with the parentheses — casts the result of a subexpression. On some PS 5.1 hosts (specifically where `$ErrorActionPreference = "Stop"` is active, as set on line 9), casting a null string to int via `[int]("")` can throw a `RuntimeException: Cannot convert value "" to type "System.Int32"`. Empty-string vs null matters: some hosts return `""` for unset env vars rather than `$null`.

The script already sets `$ErrorActionPreference = "Stop"` at line 9. Any exception inside the DryRun block will propagate as an unhandled error. This means `pwsh -DryRun` with no inject env set could exit non-zero on some hosts. The fix is `[int]($env:SLOT_DEPLOY_INJECT_UVICORN_FAIL ?? 0)` — but that requires PS 7+. The 5.1-safe fix is:

```powershell
$injectFail = if ($env:SLOT_DEPLOY_INJECT_UVICORN_FAIL) { [int]$env:SLOT_DEPLOY_INJECT_UVICORN_FAIL } else { 0 }
```

The existing tests always set the env var explicitly (to "6" or "0"), so this cast path is never exercised with an unset variable in CI. The T1-1 test (`test_dry_run_prints_resolved_bind_host_and_port_default`) does not set the inject env — but it also sets no inject at all and the DryRun block exits before line 50 reaches the `if ($injectFail -gt 0)` branch... wait, it does evaluate `[int]($env:SLOT_DEPLOY_INJECT_UVICORN_FAIL)` on line 50 regardless. So T1-1 exercises this path. Whether it fails depends on the host. On the dev machine it may silently succeed; on a strict PS 5.1 host it may throw.

---

### IMPORTANT (should fix before commit)

**IMPORTANT-1 — `New-Item -Force` swallowed silently when `state/console/` creation fails**

File: `scripts/start_console.ps1` lines 83 and 202.

Both the DryRun and real exhaustion paths use:
```powershell
try { New-Item -ItemType Directory -Path $diagDir -Force | Out-Null } catch { }
```

The inner `catch { }` is a bare swallow — no `Write-Host`, no escalation. If `state\console\` cannot be created (e.g. the parent `state\` directory does not exist, or the NTFS ACL blocks the user), the directory silently does not get created, and the subsequent `[System.IO.File]::WriteAllText(...)` call then throws — which IS caught by the outer `catch { Write-Host "WARNING: could not write..." }`. So the operator does see a warning. But the warning message blames the JSON write (`$diagFile`), not the directory creation. An operator seeing "could not write diagnostic JSON to state\console\restart_exhausted.json" has no idea whether the cause is ACL on the parent dir or disk full or something else. Per `feedback_no_silent_swallow.md`, the diagnostic should surface the root cause. The bare `catch { }` on directory creation is the violation.

**IMPORTANT-2 — rollback.ps1 port-wait loop hardcodes 8877 regardless of `SLOT_BIND_PORT` env**

File: `scripts/deploy/rollback.ps1` line 82.

```powershell
$portInUse = Get-NetTCPConnection -LocalPort 8877 -State Listen -ErrorAction SilentlyContinue
```

The port is hardcoded 8877. If an operator has deployed with `SLOT_BIND_PORT=9000`, rollback will declare "port free" immediately and proceed to `git reset --hard` while uvicorn is still holding port 9000. The kill-then-reset ordering is purely cosmetic (there is no file-lock coupling to uvicorn's active port), but the DRY-RUN message on line 78 also says "port 8877" explicitly, misleading the operator. The fix is to read `$env:SLOT_BIND_PORT` with the same pattern used in `start_console.ps1`.

No test covers this: `test_rollback_dry_run_shows_intended_ops` does not check the port number in the dry-run message.

**IMPORTANT-3 — T5-3 (`test_rollback_without_force_prompts_before_reset`) is permanently skipped in CI**

File: `tests/backend/test_deploy_rollback_script.py` lines 146-151.

The test skips when `git status --porcelain` is non-empty. The current working tree has uncommitted P4 files (6 untracked files visible in `git status`). This means T5-3 will be skipped in every CI run that has P4 uncommitted. After commit the tree is clean again, so post-commit it will run. But the brief says "22 new tests pass" and counts T5-3 — if T5-3 was actually skipped during the verifier run, the count is misleading and the prompt-abort path was never verified by CI.

The tester acknowledged this as a known concern (#5 in the pre-flagged items). But the fix exists: create a git repo fixture in `tmp_path`, clone/init it there, and run rollback against that path. The guard should fire on the real worktree (which is clean in that fixture). This avoids the worktree-dirty skip entirely.

**IMPORTANT-4 — No inject-bug test for the `LogonType` / `InteractiveToken` constraint in SlotConsole.xml**

`test_xml_principal_is_not_system_or_localservice` tests the `UserId` field (BUG-H), but no test verifies that `LogonType` is NOT `InteractiveToken`. Since `InteractiveToken` is the bug (BLOCKER-1), there should be a test that goes RED if `LogonType` is set to `InteractiveToken`. The current test suite does not check `LogonType` at all.

---

### NICE-TO-HAVE (follow-up after commit)

**N1 — README_DEPLOY.md missing UTF-16 fallback note for XML registration**

Implementer pre-flagged concern #3: on old Windows (pre-Win10 1903 Task Scheduler), XML registration may fail with UTF-8. README §2f does not mention "if schtasks /Create /XML fails, try converting to UTF-16 via PowerShell `Get-Content ... | Set-Content -Encoding Unicode`." Not a blocker on the target OS (Win10/11), but worth documenting for robustness.

**N2 — README_DEPLOY.md missing warning about InteractiveToken + restart storm math**

The 3 × 5 = up to 15 uvicorn launch multiplier (Task Scheduler RestartOnFailure × script loop) is not documented in README. Also, once BLOCKER-1 is fixed (by switching to `Password`/`S4U` logon type), the README should explain that the password is stored by Task Scheduler and does not require an active session.

**N3 — `test_port_guard_still_runs_once_at_startup` has an over-permissive assertion**

File: `tests/backend/test_deploy_start_console.py` lines 263-278.

The test accepts exit 0 with a `pytest.skip()` and also accepts "not installed" (fastapi missing) as a passing condition for the port-guard test. If CI has fastapi installed but Get-NetTCPConnection returns unexpected output, the test passes vacuously via the broad OR. This is weak but not a blocker.

**N4 — Smoke test `test_smoke_against_unroutable_fails_loudly_exit_1` timeout is fragile**

File: `tests/backend/test_deploy_smoke_script.py` line 88.

Uses `-Timeout 2` per probe × 5 probes = up to 10s. The outer Python `subprocess.run` timeout is 60s, which is fine. But on some CI hosts, .NET's HTTP stack has a cold-start initialization overhead — the first `Invoke-WebRequest` can take 2-4s before the TCP connect attempt even begins. With `-Timeout 2`, the first probe may succeed (fast .NET init on warm host) or fail (slow init on cold host). The test asserts FAIL which is fine for unroutable, but if initialization delays eat the 2s before the TCP stack even tries, the behavior is non-deterministic. The `-Timeout` default for the test should be 5s.

---

### CONFIRMED-OK (pre-flagged items verified)

**OK-1 — `??` operator appears only in a comment (line 15)**

Verified by reading the file. Line 15 is `# PowerShell 5.1-compat: no ?? operator; use explicit if/else.` — a comment. All non-comment code uses `if (...) { } else { }` syntax. `test_powershell_5_1_syntax_no_null_coalescing` correctly skips lines starting with `#`. Confirmed clean.

**OK-2 — `SLOT_DEPLOY_INJECT_UVICORN_FAIL` cannot affect non-DryRun restart loop**

The inject seam is entirely inside `if ($DryRun) { ... }` (lines 43-106). The production restart loop (lines 151-178) reads `$env:SLOT_DEPLOY_INJECT_UVICORN_FAIL` nowhere. Setting this env var in production has zero effect. Confirmed.

**OK-3 — README mentions UTF-16 issue: NOT mentioned**

Verified: no mention of UTF-8/UTF-16 in README_DEPLOY.md. This is a documentation gap (noted as N1 above), not a code bug.

**OK-4 — `rollback.ps1` Stop-ScheduledTask catch-all vs. permission-denied**

The catch block (lines 69-72) catches ALL exceptions and writes a WARN message, then continues. This means a "permission denied" error (e.g. task exists but the user lacks stop rights) is treated identically to "task not registered." This is weak distinguishing, but since the brief explicitly calls this "best-effort / warn-not-fail", it is within scope. The operator sees the warning text including `$_` (the exception message), which does contain "Access Denied" vs "task not found" wording from Windows. Not ideal but acceptable.

**OK-5 — T5-3 skipped in dirty worktree**

Confirmed as an active skip. The test uses `git status --porcelain` on the real worktree. With 6 untracked P4 files in the working tree, this test silently skips in CI. See IMPORTANT-3 for the impact.

---

## Self-critique

1. I could not run PowerShell commands interactively due to bash hook failures, so BLOCKER-2 (null-to-int cast behavior) is based on PowerShell documentation reasoning rather than live observation. The T1-1 test may have already surfaced this on the dev machine (it passed). I cannot confirm whether `[int]($null)` vs `[int]("")` behavior varies across PS versions without a live test.

2. BLOCKER-1 (`InteractiveToken`) is based on Windows Task Scheduler documentation. The actual behavior at boot with no interactive session is well-documented (task will not run), but I have not observed it directly on this machine. If the deployment machine always has an auto-logon configured (e.g. Windows kiosk mode), `InteractiveToken` could work in practice, even if technically fragile.

3. I did not check whether any earlier P1/P2/P3 tests reference the old `start_console.ps1` default port (8877 was the old default; P4 changes `[int]$Port = 0`). Any test that launched the script without `-Port` and expected 8877 still works (the env-fallback produces 8877), but the param default changed. This is worth a quick grep that I did not perform.

---

## Verdict

**LOOP-BACK**

### Required fixes before commit/merge

1. **BLOCKER-1**: Change `<LogonType>InteractiveToken</LogonType>` to `<LogonType>Password</LogonType>` (or `S4U` if password storage is undesirable). Update README_DEPLOY.md to explain that `schtasks /Create /XML` with Password logon type will prompt for the operator's Windows password at registration time, and that the task will run at boot without requiring an active session. Add an XML test that asserts `LogonType != InteractiveToken`.

2. **BLOCKER-2**: Replace `$injectFail = [int]($env:SLOT_DEPLOY_INJECT_UVICORN_FAIL)` (line 50) with the PS 5.1-safe conditional: `$injectFail = if ($env:SLOT_DEPLOY_INJECT_UVICORN_FAIL) { [int]$env:SLOT_DEPLOY_INJECT_UVICORN_FAIL } else { 0 }`. Add a T1-1 variant that explicitly does NOT set `SLOT_DEPLOY_INJECT_UVICORN_FAIL` and asserts exit 0 (current test already does this, but verify it actually exercises line 50).

### Optional improvements

1. **IMPORTANT-1**: Change bare `catch { }` on directory creation to `catch { Write-Host "WARN: could not create diagDir ${diagDir}: $_" }`.
2. **IMPORTANT-2**: Read `$env:SLOT_BIND_PORT` in rollback.ps1 for the wait-loop instead of hardcoding 8877.
3. **IMPORTANT-3**: Refactor T5-3 to use a `tmp_path` git repo fixture so it never skips due to worktree state.
4. **N1**: Add UTF-16 fallback note to README §2f.
5. **N2**: Add restart-storm math warning to README.
