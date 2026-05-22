# P4 Implementation Brief: Deploy Wrapper + Task Scheduler + LAN Bind

> **Date**: 2026-05-17
> **Phase**: 4 of 4 — final phase of internal-deploy migration (per `session_artifacts/_arch/deploy/07_deploy_decision.md`)
> **Design source**: `04_deploy_architecture_proposal_v2.md` §4.7 + §6 Phase 4 deliverables
> **Baseline**: commit `4806f89` (HANDOFF doc on top of `51af9a6` P3). 1087 tests pass / 22 skipped, 79 routes (prod) / 76 routes (virtual).
> **Coordinator**: main session (continuing on branch `claude/keen-wu-b8b520` per user choice "c — stay in worktree")
> **Agent flow**: `impl-implementer` → `impl-tester` → `impl-verifier` → `impl-critic`
> **Commit boundary**: single atomic commit

---

## §1 Context

P4 is the **deploy wrapper** phase — scripts + docs only, no production code beyond a trivial env-var read in `main.py`. Wraps the FastAPI/uvicorn process in a Windows-native restart loop (Task Scheduler + PowerShell, no NSSM) and binds it to the LAN (`0.0.0.0:8877`) so N<10 planners on the company intranet can hit it.

Per `memory/project_internal_deploy_intent.md`:
- Single Windows host, no auth, no Docker, no NAS — local disk only.
- "无 user / 全员共享 / on-demand" — fleet refresh is human-triggered, not 24/7.
- Stack-locked: FastAPI + uvicorn + SQLite (WAL) + ProcessPoolExecutor + msvcrt locking — already wired by P1+P2+P3.
- Service wrapper decision: **Task Scheduler + PowerShell restart loop** (Windows-native, no extra deps). The v1 proposal's NSSM / nginx-for-Windows recommendations were retracted 2026-05-15.

---

## §2 Scope — 6 deliverables (per 04_v2 §6 Phase 4 + §4.7)

### D1 — `start_console.ps1` restart loop + LAN bind + Event Log on exhaustion

Modify `scripts/start_console.ps1`:

1. **Restart loop**: wrap the `python -m uvicorn` call in `while ($restarts -lt $MAX_RESTARTS) { ... }`. Default `$MAX_RESTARTS = 5`.
2. **Exponential backoff**: sleep `[Math]::Min(5 * [Math]::Pow(2, $restarts), 60)` seconds between restarts (5, 10, 20, 40, 60 capped). Design §4.7 sample code uses constant 5s; HANDOFF §2 D1 specifies "exponential backoff with cap" — go with exponential. (Reason: constant 5s × MAX_RESTARTS=5 = 25s recovery window is too aggressive for transient port-bind / file-lock contention scenarios that take 30-60s to clear.)
3. **LAN bind**: change `--host 127.0.0.1` → `--host $bindHost` where `$bindHost = if ($env:SLOT_BIND_HOST) { $env:SLOT_BIND_HOST } else { "0.0.0.0" }`. Keep PowerShell 5.1-compatible (no `??` operator per S1 fix).
4. **Port from env**: existing `-Port` param wins; if not provided, `$Port = if ($env:SLOT_BIND_PORT) { [int]$env:SLOT_BIND_PORT } else { 8877 }`. Keep `8877` as default (matches existing script default).
5. **Event Log on exhaustion**: after the `while` loop, if `$restarts -ge $MAX_RESTARTS`, call `Write-EventLog -LogName Application -Source "SlotConsole" -EntryType Error -EventId 1001 -Message "..."`. Source must be registered first (one-time `New-EventLog -LogName Application -Source SlotConsole` on deploy; if creation fails due to permissions or already-exists, fall back to writing diagnostic to `state/console/restart_exhausted.json` per `memory/feedback_no_silent_swallow.md`).
6. **Existing behavior preserved**: `-Install`, `-OpenBrowser`, `-NoBanner`, `-Port` flags continue to work. Port guard (Get-NetTCPConnection) still runs ONCE before the restart loop, not on every iteration (an existing listener at startup is fatal; intra-loop port reuse race is uvicorn's own problem).

Acceptance criteria:
- `pwsh -NoProfile -File scripts\start_console.ps1 -NoBanner -DryRun` prints the resolved `$bindHost` and `$bindPort` and exits 0 without spawning uvicorn (dry-run is a new flag for testability).
- With `SLOT_BIND_HOST=127.0.0.1` env set and no `-DryRun`, the script binds to loopback (env honored).
- With no env set, the script binds to `0.0.0.0` (LAN default).
- Setting `$env:SLOT_DEPLOY_INJECT_UVICORN_FAIL=1` (for inject-bug test) causes the dry-run loop to simulate failures and exhaust the budget, triggering the Event Log fallback path.

### D2 — `main.py` env var support

Modify `src/web_console/backend/main.py`:

- Keep `app = create_app()` as the uvicorn ASGI entry (used by `python -m uvicorn src.web_console.backend.main:app`).
- In the `if __name__ == "__main__":` branch (only path that hits the hardcoded `host=127.0.0.1, port=8765`), read env vars: `host = os.environ.get("SLOT_BIND_HOST", "0.0.0.0")`, `port = int(os.environ.get("SLOT_BIND_PORT", "8877"))`. Default port aligns with `start_console.ps1` (8877, not 8765).
- Defense in depth: even if an operator runs `python main.py` directly (bypassing the .ps1), they get LAN bind via env.

Acceptance criteria:
- `python main.py` with no env: binds `0.0.0.0:8877`.
- `python main.py` with `SLOT_BIND_HOST=127.0.0.1 SLOT_BIND_PORT=8765`: binds `127.0.0.1:8765`.
- Import `src.web_console.backend.main` (no `__main__` execution) still produces `app` with no env reads — `create_app()` semantics unchanged.

### D3 — Task Scheduler XML

New file: `scripts/deploy/SlotConsole.xml`

Task Scheduler XML schema (v1.2). Key fields:
- **Trigger**: `<BootTrigger>` (delay 60s so disk + network are stable)
- **Principal**: `<UserId>%USERNAME%</UserId>` with `<RunLevel>HighestAvailable</RunLevel>` (HANDOFF §9 OQ-2 sensible default: current operator user, NOT SYSTEM. SYSTEM lacks profile dirs many tools rely on; LocalService can't write to operator's project tree.)
- **Action**: `<Exec><Command>powershell.exe</Command><Arguments>-NoProfile -ExecutionPolicy Bypass -File "%SLOT_REPO_ROOT%\scripts\start_console.ps1" -NoBanner</Arguments></Exec>`
- **Settings**: `<StartWhenAvailable>true</StartWhenAvailable>`, `<RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>` (Task Scheduler's own retry on top of the script's restart loop)
- **Dynamic repo path**: the XML uses `%SLOT_REPO_ROOT%` env var (set once via `[System.Environment]::SetEnvironmentVariable("SLOT_REPO_ROOT", "<path>", "Machine")` during deploy). NOT hardcoded `C:\path\to\repo` — supports multiple deploy targets without XML edits. Documented in README_DEPLOY.md.

Acceptance criteria:
- `Get-ScheduledTaskInfo -TaskName SlotConsole` (after registration) shows task exists and is enabled.
- XML parses cleanly: `[xml]$x = Get-Content scripts\deploy\SlotConsole.xml; $x.Task.Actions.Exec.Command` returns "powershell.exe".
- `<UserId>` is NOT "SYSTEM" / "LocalService" / "LocalSystem" (operator user only).

### D4 — `scripts/deploy/README_DEPLOY.md`

New file with the following sections:

1. **Pre-flight checks** (PowerShell version `$PSVersionTable.PSVersion.Major -ge 5`; Python on PATH; pip install -r requirements.txt done; disk space; **state/ on local NTFS — NOT SMB/CIFS** per SQLite WAL constraint)
2. **Initial deploy**: clone repo → set `SLOT_REPO_ROOT` machine env → `New-EventLog -LogName Application -Source SlotConsole` (one-time, requires Admin) → `schtasks /Create /XML scripts\deploy\SlotConsole.xml /TN SlotConsole` → register Windows Defender / firewall allow-list (inbound TCP 8877) → reboot or `Start-ScheduledTask -TaskName SlotConsole`
3. **Upgrade**: `git pull` → `Stop-ScheduledTask -TaskName SlotConsole` → wait for processes to exit → `pip install -r src\web_console\requirements.txt` (covers new deps) → `Start-ScheduledTask -TaskName SlotConsole`
4. **Rollback** (procedural; see also `rollback.ps1`): `Stop-ScheduledTask` → `git revert <bad-commit>` → restart task. SQLite forward-only `ALTER TABLE` columns are inert on rollback (old code ignores new columns).
5. **LAN access**: planners hit `http://<host>:8877/console/` from intranet. Windows Defender firewall must allow inbound 8877 (PowerShell: `New-NetFirewallRule -DisplayName "SlotConsole" -Direction Inbound -Protocol TCP -LocalPort 8877 -Action Allow`).
6. **Monitoring**: Event Viewer → Windows Logs → Application → filter Source=SlotConsole. EventId 1001 means restart budget exhausted (operator action required). Disk monitor + stale tag failures persist diagnostic to `state/console/*.json` (per `memory/feedback_no_silent_swallow.md` — surface via `GET /api/system-state` is a known follow-up gap per HANDOFF §4).
7. **Limitations** (carry from HANDOFF §4): explicitly list the known gaps from P3 so the operator knows what NOT to expect (config_id wiring, system-state diagnostic surfacing, etc.).

Audience: ops team unfamiliar with the codebase. Step-by-step copy-pasteable commands. No assumed prior knowledge of FastAPI / uvicorn internals.

### D5 — `scripts/deploy/run_smoke.ps1`

New script: runnable from any host on the LAN with PowerShell. Probes 5 endpoints against a target server URL.

Params:
- `-BaseUrl` (default `http://localhost:8877`)
- `-Verbose` (per-request detail)
- `-Timeout` (per-request seconds, default 10)

Probes (each must return 2xx within timeout):
1. `GET /console/` — frontend served
2. `GET /api/machines` — machine list responds
3. `GET /api/system-state` — system state JSON parses
4. `GET /api/fleet/refresh` — fleet endpoint reachable (may return 404 if no queue ever started; treat 200 OR 404 as pass)
5. `GET /api/configs` — config endpoint reachable

Exit code 0 if all pass; non-zero with summary table if any fail. Plain text output so it's diff-friendly in logs.

Acceptance criteria:
- Run against a live local console: all 5 green.
- Run against `http://192.0.2.1:1` (unroutable): all 5 timeout; exit code 1 with clear summary.
- `-DryRun` flag: print the URLs that would be probed; exit 0.

### D6 — `scripts/deploy/rollback.ps1`

New script: atomic rollback of last commit + cleanup of SQLite sidecars.

Params:
- `-To` (target commit ref; default `HEAD~1`)
- `-Force` (skip confirmation)
- `-DryRun` (print what would happen)

Steps:
1. Verify operator is in repo root (sanity check on `.git` dir).
2. `Stop-ScheduledTask -TaskName SlotConsole` (best-effort; warn but continue if task not registered).
3. Wait up to 30s for uvicorn process to exit (poll `Get-Process python` matching expected cmdline).
4. `git status` — refuse if uncommitted changes (rollback over operator work = data loss).
5. `git log --oneline -1 $To` — show target commit; confirm with operator unless `-Force`.
6. `git reset --hard $To` — explicit operator-triggered destructive op (per CLAUDE.md "Executing actions with care", this is acceptable inside a rollback script that REQUIRES operator confirmation).
7. Print next steps: "Run `Start-ScheduledTask -TaskName SlotConsole` and check `scripts\deploy\run_smoke.ps1` after restart."

Acceptance criteria:
- `-DryRun` mode: prints intended ops without modifying repo state.
- Refuses to run with uncommitted changes (red text + exit 1).
- Without `-Force`, prompts before `git reset --hard`.

---

## §3 Out of scope for P4

- **Auto-install of `SLOT_REPO_ROOT` env / Event Log Source / firewall rule**: README_DEPLOY.md documents these as one-time admin steps. Wrapping them in a `scripts/deploy/install.ps1` is tempting but risks running with operator privilege escalation; safer to keep as a documented checklist.
- **Self-healing on Event Log Source registration failure**: D1 falls back to JSON diagnostic on disk (no silent failure), but does NOT auto-retry / auto-create. Operator must run `New-EventLog` once with Admin (per README).
- **Network firewall changes from the script**: README documents `New-NetFirewallRule`, but D5/D6 do NOT poke firewall — privilege escalation surface.
- **Cross-platform (Linux/macOS)**: Windows-only deploy; the scripts are PowerShell + Windows Task Scheduler. No equivalent for *nix in this phase.
- **HTTPS / TLS termination**: intranet LAN, no auth (per project intent). HTTPS is a future concern requiring reverse proxy or cert mgmt.
- **Frontend production build**: existing static assets served by uvicorn; no bundling step needed.
- **The known limitations carried from P3** (HANDOFF §4): not addressed by P4. README documents them.

---

## §4 Constraints (must hold)

1. **Backward-compat**: existing `start_console.ps1` users must not see regressions. `-Port`, `-Install`, `-OpenBrowser`, `-NoBanner` flags continue to work identically; the new restart loop only activates when uvicorn exits non-zero (success path unchanged).
2. **No tech stack additions**: PowerShell 5.1 + Windows Task Scheduler + standard cmdlets only. No NSSM, no portalocker, no nginx, no Docker. (Per `memory/project_internal_deploy_intent.md` final stack decision.)
3. **No silent failures**: every catch / fallback path persists diagnostic OR writes to Event Log (per `memory/feedback_no_silent_swallow.md`).
4. **Dynamic repo path**: Task Scheduler XML must NOT hardcode an absolute path. Uses `%SLOT_REPO_ROOT%` machine env var so the same XML works across deploy targets.
5. **Operator user, NOT SYSTEM**: Task Scheduler principal is the operator account. SYSTEM/LocalService lack profile dirs, ProcessPoolExecutor scratch space, etc.
6. **No production code changes beyond `main.py` env reads**: P4 is wrapper-only. The 6 deliverables touch 1 existing .ps1, 1 existing .py, and create 4 new files under `scripts/deploy/`.

---

## §5 Memory feedback files to honor

- `memory/feedback_no_silent_swallow.md` — Event Log write failure falls back to JSON diagnostic; rollback script bails loudly on uncommitted changes; smoke script writes failure summary.
- `memory/feedback_enumerate_safety_paths.md` — every restart-loop branch (success, transient fail with restart, fail with exhaustion) gets an inject-bug test.
- `memory/feedback_respect_existing_codebase.md` — extend `start_console.ps1` in place; do NOT create a parallel `start_console_v2.ps1`. Reuse `tests/scripts/` directory only if it already exists (otherwise put under `tests/backend/test_deploy_scripts.py` to fit existing layout).
- `memory/feedback_perf_claim_needs_e2e_event_stream.md` — for D1 restart loop, write a test that spawns the REAL `pwsh.exe` subprocess with `SLOT_DEPLOY_INJECT_UVICORN_FAIL=1` env and asserts the Event Log call OR the JSON diagnostic file is created.
- `memory/feedback_no_doc_review.md` — README_DEPLOY.md is operator-facing (not Claude-self-review); write for someone unfamiliar with the codebase.
- `memory/feedback_impl_team_required.md` — full impl-* loop required even for scripts; this is operator-facing infra where regressions ship to production.
- `memory/feedback_adversarial_self_review.md` — commit message must include `## Self-critique` section.
- `memory/project_internal_deploy_intent.md` — stack-locked decisions; do NOT introduce NSSM / nginx / portalocker.

---

## §6 Test plan (impl-tester deliverables)

### Group P4-T1: `start_console.ps1` restart loop (D1)

New file: `tests/backend/test_deploy_start_console.py` (Windows-only; `pytest.mark.skipif(os.name != "nt")`)

Tests spawn `powershell.exe` as a subprocess with controlled env. The script supports `-DryRun` and `$env:SLOT_DEPLOY_INJECT_UVICORN_FAIL=N` for testability:

- `test_dry_run_prints_resolved_bind_host_and_port_default` — no env; assert stdout contains "0.0.0.0:8877"
- `test_dry_run_honors_slot_bind_host_env` — `SLOT_BIND_HOST=127.0.0.1`; assert stdout contains "127.0.0.1:8877"
- `test_dry_run_honors_slot_bind_port_env` — `SLOT_BIND_PORT=9000`; assert stdout contains "0.0.0.0:9000"
- `test_dry_run_explicit_port_param_wins_over_env` — `-Port 7000` + `SLOT_BIND_PORT=9000`; assert 7000 used
- `test_restart_loop_retries_then_event_log_on_exhaustion` — `SLOT_DEPLOY_INJECT_UVICORN_FAIL=6`; assert restart_exhausted.json written (Event Log path requires Admin; fallback is tested in CI)
- `test_restart_loop_exit_zero_breaks_loop_immediately` — `SLOT_DEPLOY_INJECT_UVICORN_FAIL=0`; assert exit 0 after one iteration
- `test_port_guard_still_runs_once_at_startup` — bind a TCP listener on $Port; assert script fails fast with the existing "port already in use" message (existing behavior preserved)
- `test_powershell_5_1_syntax_no_null_coalescing` — grep the script body for `\?\?` operator; assert absent (S1 fix)

### Group P4-T2: `main.py` env var support (D2)

Extend `tests/backend/test_main_entrypoint.py` (or create if absent):

- `test_main_import_no_env_read` — import `src.web_console.backend.main`; assert `app` is created without touching env (env reads only in `__main__` block)
- `test_main_main_uses_env_bind_host_when_set` — monkeypatch `__name__ == "__main__"` path; mock `uvicorn.run`; assert host arg == env value
- `test_main_main_defaults_to_0_0_0_0_8877` — no env; mock uvicorn.run; assert host=0.0.0.0 port=8877

### Group P4-T3: Task Scheduler XML (D3)

New file: `tests/backend/test_deploy_task_scheduler_xml.py`

- `test_xml_parses_cleanly` — parse `scripts/deploy/SlotConsole.xml`; assert no parse errors
- `test_xml_uses_powershell_action` — assert Action/Exec/Command == "powershell.exe"
- `test_xml_references_start_console_ps1` — assert Arguments contains "start_console.ps1"
- `test_xml_uses_repo_root_env_not_hardcoded` — assert Arguments contains "%SLOT_REPO_ROOT%" and does NOT contain "C:\\"
- `test_xml_principal_is_not_system_or_localservice` — assert Principal/UserId does NOT match "SYSTEM" / "LocalService" / "LocalSystem"
- `test_xml_has_boot_trigger` — assert Triggers/BootTrigger element present
- `test_xml_inner_settings_restart_on_failure_present` — assert RestartOnFailure block present (defense in depth on top of script's own loop)

### Group P4-T4: `run_smoke.ps1` (D5)

New file: `tests/backend/test_deploy_smoke_script.py` (Windows-only)

- `test_smoke_dry_run_lists_5_endpoints` — `-DryRun -BaseUrl http://localhost:8877`; assert all 5 URLs in stdout
- `test_smoke_against_unroutable_fails_loudly_exit_1` — `-BaseUrl http://192.0.2.1:1 -Timeout 1`; assert exit code 1; assert summary mentions timeouts
- `test_smoke_passes_against_live_create_app` — spawn uvicorn on port 8877 in subprocess; run smoke; assert exit 0 (e2e — may need to live in tests/e2e/)

### Group P4-T5: `rollback.ps1` (D6)

New file: `tests/backend/test_deploy_rollback_script.py` (Windows-only)

- `test_rollback_dry_run_shows_intended_ops` — `-DryRun`; assert stdout mentions `Stop-ScheduledTask`, `git reset --hard`, target ref
- `test_rollback_refuses_with_uncommitted_changes` — create dirty repo (tmp fixture); assert exit 1 + clear error
- `test_rollback_without_force_prompts_before_reset` — feed empty stdin in non-interactive mode; assert exit 1 (no prompt confirmation = abort)

### Group P4-T6: Inject-bug for restart-loop and Event Log fallback (per `feedback_enumerate_safety_paths.md`)

- **D1 restart loop**: remove the `while` loop body / `$restarts++` → restart-after-fail test should regress (script exits on first failure, no retry)
- **D1 Event Log fallback**: remove the JSON-diagnostic fallback after `Write-EventLog` fails → restart_exhausted.json test should regress
- **D2 env reads**: remove the env-read line → test_main_main_uses_env_bind_host_when_set fails
- **D3 dynamic path**: hardcode `C:\...` in the XML → test_xml_uses_repo_root_env_not_hardcoded fails

Each inject-bug test should be a comment-only flip ("# inject: ..."), revert after verification per `memory/feedback_enumerate_safety_paths.md`.

---

## §7 Verification plan (impl-verifier deliverables)

1. **Full backend test sweep stays GREEN**: baseline 1087 passed; expect +10–20 new tests; total >= 1097. Same `--ignore=tests/backend/test_analyzer_st_split.py` flag as P3.
2. **Routes unchanged**: 79 (prod) / 76 (virtual) — P4 adds zero routes.
3. **Smoke imports**:
   - `python -c "from src.web_console.backend.main import app; print(len(app.routes))"` → 79
   - `python -m py_compile src/web_console/backend/main.py` → ok
4. **PowerShell static checks**:
   - `Get-Command pwsh; $PSVersionTable.PSVersion` (verify runtime ≥ 5.1)
   - Parse `scripts\start_console.ps1`: `Get-Command -Syntax` clean (no syntax errors)
   - Parse `scripts\deploy\*.ps1`: same
   - Grep `\?\?` in all .ps1 files (must be 0) — S1 PowerShell 5.1 compat
5. **Dry-run smoke**: `pwsh -NoProfile -File scripts\deploy\run_smoke.ps1 -DryRun` → 5 endpoints listed, exit 0
6. **Dry-run rollback**: `pwsh -NoProfile -File scripts\deploy\rollback.ps1 -DryRun` → intended ops printed, exit 0, NO `git reset` actually happens
7. **XML validation**: `[xml]$x = Get-Content scripts\deploy\SlotConsole.xml; $x` → parses; principal NOT SYSTEM
8. **Live smoke** (if time permits in verifier sandbox): start `start_console.ps1` in background → wait for `:8877` listen → `Invoke-WebRequest http://localhost:8877/console/` → 200 → stop the script. (Operator-discovery failure modes are harder to test in CI; verifier should at minimum confirm the happy path.)

---

## §8 Commit message draft (for impl-critic fact-check)

```
feat(phase4-deploy): start_console restart loop + Task Scheduler XML + LAN bind

Phase 4 of 4-phase deploy migration per 07_deploy_decision.md. Wraps the
FastAPI/uvicorn process in a Windows-native restart loop and binds to LAN
for intranet planner access.

Modified:
- scripts/start_console.ps1: restart loop (MAX 5 with exp backoff capped 60s),
  LAN bind via SLOT_BIND_HOST env (default 0.0.0.0), SLOT_BIND_PORT env
  (default 8877), Event Log EventId 1001 on exhaustion with JSON diagnostic
  fallback (per feedback_no_silent_swallow.md), -DryRun flag for testability.
  PowerShell 5.1-compatible (S1 fix: no ?? operator).
- src/web_console/backend/main.py: __main__ block reads SLOT_BIND_HOST /
  SLOT_BIND_PORT env (defaults 0.0.0.0:8877). create_app() import path
  unchanged (no env reads on import).

Added:
- scripts/deploy/SlotConsole.xml: Task Scheduler v1.2 XML; boot trigger;
  operator-user principal (NOT SYSTEM); dynamic repo path via
  %SLOT_REPO_ROOT% (deploy-target-portable); inner RestartOnFailure block
- scripts/deploy/README_DEPLOY.md: pre-flight checklist, deploy / upgrade /
  rollback procedures, LAN firewall config, monitoring via Event Viewer,
  known limitations carried from P3
- scripts/deploy/run_smoke.ps1: LAN-runnable smoke; 5 endpoint probes with
  per-request timeout; -DryRun and -BaseUrl params; clear failure summary
- scripts/deploy/rollback.ps1: atomic rollback (Stop-Task + git reset);
  refuses with uncommitted changes; -DryRun / -Force / -To params

## Verified happy path
- N tests green: P4-T1..T5 (~15 new) + P1+P2+P3 baseline (1087). Stable
  across runs. Routes unchanged: 79 (prod) / 76 (virtual).
- Dry-run smoke: 5 endpoints printed, exit 0
- Dry-run rollback: intended ops printed, exit 0, repo unchanged
- XML parses cleanly; principal != SYSTEM; dynamic %SLOT_REPO_ROOT%
- main.py __main__ honors env vars; import-only path no env reads
- start_console.ps1 happy path unchanged (existing flags work)

## Verified failure paths
- Inject-bug for restart loop body removal → regression caught
- Inject-bug for Event Log fallback removal → restart_exhausted.json missing
- Inject-bug for env read removal in main.py → default host wrong
- Inject-bug for hardcoded path in XML → XML test red
- Smoke against unroutable URL: exit 1 with clear summary
- Rollback with uncommitted changes: exit 1, no git ops

## Not verified
- Real Task Scheduler registration (requires Admin + would mutate the
  test machine's scheduled tasks; documented in README, manual operator
  verification required)
- Real Event Log Source registration (requires Admin; tests use the JSON
  diagnostic fallback path)
- Real firewall rule creation (requires Admin; documented in README)
- Real LAN access from a different physical host

## Tests added
- tests/backend/test_deploy_start_console.py (~8)
- tests/backend/test_main_entrypoint.py (~3)
- tests/backend/test_deploy_task_scheduler_xml.py (~7)
- tests/backend/test_deploy_smoke_script.py (~3)
- tests/backend/test_deploy_rollback_script.py (~3)

## Self-critique
- ...
```

---

## §9 Out-of-loop after this commit

P4 is the FINAL phase. After this commit:
- Update `memory/project_internal_deploy_intent.md`: mark all 4 phases done; note total deploy migration is complete.
- Update `session_artifacts/_impl/HANDOFF.md` (or create a closing `DEPLOY_COMPLETE.md`): record total commits + test count + remaining known limitations.
- Branch decision: still `claude/keen-wu-b8b520`; whether to merge to `collab/dev` is the user's call.

---

## §10 Notes for the impl-implementer agent

- **DO NOT** add an `install.ps1` that wraps `New-EventLog` / `New-NetFirewallRule` / `[System.Environment]::SetEnvironmentVariable Machine` — those are privilege-escalation surfaces. Document them in README_DEPLOY.md instead.
- **DO NOT** rewrite the existing `start_console.ps1` from scratch. Edit in place. The existing `-Install`, `-OpenBrowser`, `-NoBanner`, `-Port` parameter contract must hold.
- **DO** use `Tee-Object -FilePath` for uvicorn output if `$LOG_FILE` is set (existing pattern in design §4.7); otherwise just pipe to host.
- **DO** keep the inject-bug seam (`$env:SLOT_DEPLOY_INJECT_UVICORN_FAIL`) cheap — it should ONLY affect the `-DryRun` code path (and be ignored otherwise). It exists for testability, not production runtime.
- **DO** use `$PSScriptRoot` to derive `$repoRoot` (existing pattern at line 10: `$root = Split-Path -Parent $PSScriptRoot`). For files in `scripts/deploy/`, use `$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)` (two levels up since `scripts/deploy/<script>.ps1`).
- **DO** match the existing script's `Write-Host` style (no banners with emoji, no colors via Write-Host -Foreground unless absolutely needed — the existing script keeps it plain).
