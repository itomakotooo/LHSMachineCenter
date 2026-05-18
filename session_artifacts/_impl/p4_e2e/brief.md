# P4-E2E Implementation Brief — real end-to-end deploy verification

> **Date**: 2026-05-17
> **Phase**: P4 follow-up — real E2E (post P4 commit `190dc9d`)
> **Baseline**: HEAD `190dc9d`, backend sweep 1111 green (no e2e dir included)
> **Coordinator**: main session
> **Agent flow**: parallel `impl-implementer` (pwsh fix) + `impl-tester` (E2E suite) → `impl-verifier` → `impl-critic`
> **Commit boundary**: 2 atomic commits (pwsh fix + E2E suite)

---

## §1 Why this exists

P4 (commit `190dc9d`) shipped with "1111 tests green / 79 routes / DryRun smoke PASS / inject-bug verified" but the user surfaced 3 missing verification axes:

1. **No real upstream contact**. servers.json configures `dev=192.168.10.21:15060` and `prod=116.232.103.19:10288` (same server, two views). Console talks to upstream via `/api/servers/{id}/scan`, `/api/servers/{id}/check-changes`, batch-run path, MD5 refresh. NONE of these were exercised end-to-end. Last-mile bug between console and upstream invisible.
2. **No real business flow**. Fetch → analyzer → report appears on disk → frontend renders new report. Never tested. P2/P3 added `CellLockRegistry`, `ConcurrencyLimiter`, `_tag_reports_stale`, `pending_batch_configs` — all touched the batch-run path; none of them verified end-to-end.
3. **No real concurrent planner simulation**. P2's INV-1 (single SAMPLING per cell), P2's `ConcurrencyLimiter` foreground-reserve, P3's fleet-vs-ad-hoc priority — all unit-tested with mocks; never with 2+ real browsers in same uvicorn.

Additionally: `tests/e2e/test_console_smoke.py` (12 Playwright tests) **exists in tree but was never run by P1/P2/P3/P4 sweeps** — all sweeps used `tests/backend/` only. They may have regressed silently across P1-P4.

User context (2026-05-17): planners use intranet daily; weekend home access via public 116. This worktree machine has TCP reachability to both `192.168.10.21:15060` and `116.232.103.19:10288` (probed), so it can simulate the planner experience end-to-end. User explicitly approved a single real fetch against dev ("理论上你可以完整测试").

---

## §2 Goals

| ID | Goal | Pass criteria |
|---|---|---|
| G1 | Repair operator-facing README so `pwsh` (PowerShell 7, not on Win10/11 default) doesn't error out | 0 `pwsh` literals in `README_DEPLOY.md` or testing docstrings; `powershell` works in their place |
| G2 | Existing 12 Playwright e2e tests still pass post-P4 | `tests/e2e/test_console_smoke.py` 12/12 green against current HEAD |
| G3 | One real intranet fetch lands disk + report appears | After POST `/api/batch-run` for M14 mode 1 ~1000 spin via dev upstream: `rawdata/M14/mode_1/*_chunks.json` non-empty; `reports/M14/mode_1/index.json` includes a new entry; GET `/api/reports/M14/1` returns it; uvicorn log shows analyzer subprocess completion |
| G4 | Two concurrent planner sessions converge correctly | Playwright A and B both POST same `(M14, 1, config_id=null)` within 200ms; A creates run, B's response is `status=attached` w/ A's `run_id` (per P2 R9). Backend log shows only ONE upstream MultiRobotTestSpin batch. |
| G5 | Delete while fetching returns 409 (P2 INV-2) | While A's run from G3 is active: B issues `DELETE /api/rawdata/M14` → HTTP 409 with cell-busy reason. A's run unaffected. |
| G6 | Server switch UI works | Frontend "服务器管理" panel: list shows dev+prod from servers.json; `PUT /api/servers/dev/set-default` updates default; `POST /api/servers/dev/scan` round-trips through upstream and writes MD5 snapshot. |

---

## §3 Explicit non-goals (do NOT touch)

- **Do NOT trigger real fleet refresh** (393 machines, hours-to-days, would actually move production data). Use only mock-mode tests or skip this user story for now.
- **Do NOT write to prod upstream** (`116.232.103.19:10288`). TCP probe + GET `/api/servers/prod/snapshot` is OK; POST to prod's upstream is OFF-LIMITS.
- **Do NOT fetch >1000 spin** in any single test. The single approved fetch in G3 uses `spinTimes=1000` or similar small value — well below the 10000 production default. (Memory `feedback_no_proactive_fetch.md` exception covers exactly this scope, no further.)
- **Do NOT modify P1/P2/P3 production code**. If E2E exposes a real bug, surface it in critique; coordinator decides whether to fix in this commit boundary or defer.
- **Do NOT add new Playwright test infra** if existing `tests/e2e/conftest.py` / `live_server` fixture already does what's needed. Reuse.

---

## §4 Concrete scope (6 deliverables)

### D1 — pwsh→powershell purge (`impl-implementer`, parallel)

Files to touch:
- `scripts/deploy/README_DEPLOY.md` — 6 places (`pwsh -NoProfile -File ...`); replace with `powershell -NoProfile -ExecutionPolicy Bypass -File ...` (note: README's `schtasks` and other PS5.1 cmdlets stay)
- `tests/backend/test_deploy_smoke_script.py` line 108 — skip-reason docstring with `pwsh`; replace
- Any other `pwsh ` literal found by grep across `scripts/deploy/` and `tests/backend/test_deploy_*.py`

DO confirm by running: `python -m pytest tests/backend/test_deploy_smoke_script.py tests/backend/test_deploy_rollback_script.py -v` — must stay green.

### D2 — existing e2e re-verification (`impl-tester`)

`python -m pytest tests/e2e/test_console_smoke.py -v` against the post-P4 codebase. Pass criteria: 12/12 green. If any fail:
- triage whether it's a P4 regression or pre-existing flake
- if regression, document it in tester report (don't fix yet — coordinator decides)
- if pre-existing, document as P0 follow-up

### D3 — new E2E suite `tests/e2e/test_p4_real_business_flow.py` (`impl-tester`)

5 test functions targeting goals G3-G6:

```
test_real_fetch_M14_mode1_via_dev_upstream
    # uses live_server fixture (real uvicorn) + Playwright
    # navigates to /console/, clicks fetch button for M14 mode 1
    # OR (more reliable) directly POSTs /api/batch-run with payload
    #   { machines: [{machine: "M14", mode: 1}], serverEndpoint: dev,
    #     spinTimes: 1000, robotCount: 2, ... }
    # polls GET /api/batch-run/{batch_id} until status=completed or failed
    # asserts rawdata/M14/mode_1/*_chunks.json exists
    # asserts reports/M14/mode_1/index.json has new entry
    # asserts GET /api/reports/M14/1 returns it
    # finally: clean up rawdata/M14 + reports/M14/mode_1/<new_version> after test
    # MARKED @pytest.mark.slow + @pytest.mark.real_upstream
    # SKIP if dev TCP unreachable

test_concurrent_fetch_attaches_not_duplicates
    # uses cache produced by previous test (or runs a small fetch first)
    # 2 Playwright contexts, both POST batch-run for same (M14, 1, null)
    # within 200ms of each other
    # assert: one response has new run_id, other has status=attached + same run_id
    # backend log assertion: only one MultiRobotTestSpin upstream call

test_delete_during_fetch_returns_409
    # context A starts fetch (small)
    # context B DELETE /api/rawdata/M14 immediately after A's run becomes active
    # assert: B response 409 with reason mentioning cell busy
    # assert: A's run completes normally

test_server_switch_default_and_scan
    # GET /api/servers — assert dev + prod present
    # PUT /api/servers/dev/set-default — assert success
    # POST /api/servers/dev/scan — assert returns MD5 snapshot
    # GET /api/servers/dev/snapshot — assert recent timestamp
    # (the scan POST is the only write that touches dev upstream)

test_prod_endpoint_reachable_but_readonly_probe
    # GET /api/servers — verify prod listed with 116.x
    # GET /api/servers/prod/snapshot — should succeed (no write)
    # (Does NOT trigger POST /api/servers/prod/scan — do not write to prod)
```

Conftest setup:
- Reuse `live_server` fixture from `tests/e2e/conftest.py` if it exists; otherwise extend.
- Override `state/console.db` to a tmp path so tests don't clobber any real state.
- Set env `SLOT_BIND_PORT=8879` (avoid clash with launch.json `console` if user has it running) — same pattern as `console-verify` in launch.json.
- `pytest.skip` if dev upstream unreachable (TCP probe at session start).

### D4 — execution + capture (`impl-tester`)

Execute D2 + D3 against the live HEAD. Capture:
- Full pytest output (with `-v`)
- For G3 fetch: the actual `rawdata/M14/mode_1/*` filenames produced + size + content sample (first 200 bytes of a chunk)
- For G3 report: the actual `reports/M14/mode_1/index.json` entry + GET `/api/reports/M14/1` response
- For G4 concurrent: backend uvicorn log lines showing the attach decision
- For G5 409: full 409 response body
- For G6 server scan: MD5 snapshot file path + size

Report at `session_artifacts/_impl/p4_e2e/tester_report.md`.

### D5 — verification + chaos (`impl-verifier`)

Beyond D4's happy path:
- Full backend sweep stays green: `python -m pytest tests/backend/ --ignore=tests/backend/test_analyzer_st_split.py -q` ≥ 1111
- Sweep including e2e: `python -m pytest tests/backend/ tests/e2e/ --ignore=...` — record number
- Chaos:
  * Kill upstream connection mid-fetch (block 192.168.10.21:15060 via PowerShell `New-NetFirewallRule` temporary, see how the run fails — should mark batch failed, not hang)
  * Wedge port (bind 8879 manually, start uvicorn, see port guard fire — already covered by P4 but re-confirm in live)
- Silent-skip audit on the new test file
- Cleanup verification: after tester's run, `git status --porcelain` shows no orphan files under rawdata/M14, reports/M14, state/

Report at `session_artifacts/_impl/p4_e2e/verifier_report.md`.

### D6 — adversarial review (`impl-critic`)

Specifically scrutinize:
- Did the tester actually exercise real network? Or did they mock `requests.post` to upstream? Adversarial: grep `monkeypatch.*requests` / `Mock.*upstream` in the new test file.
- Did the concurrent test really hit 2 contexts in same uvicorn process, or 2 separate uvicorns? (the test must use same `live_server`)
- Did the 409 test actually race A and B, or did B fire after A was already complete?
- Did the cleanup actually delete the produced rawdata? `git status` shows no orphans?
- Is the "skip if dev unreachable" a silent-skip pattern that masks real failure in CI?

Report at `session_artifacts/_impl/p4_e2e/critique.md`.

---

## §5 Constraints

- **Real network OK, but only via dev**. Prod write = critical bug.
- **No production code edits** except D1 (docs/test docstring). If E2E surfaces a real backend bug, document in critique; coordinator decides whether to fix in a P4-followup or defer.
- **All tests cleanup**. Each test removes its own rawdata/M14 and reports/M14/mode_1/<version> before exit. Verifier checks orphans.
- **Memory feedback**:
  - `feedback_no_proactive_fetch.md` — explicit user override: dev only, M14 mode 1, ≤1000 spin, single approved test run
  - `feedback_impl_team_required.md` — team required (this brief)
  - `feedback_perf_claim_needs_e2e_event_stream.md` — tests must spawn real subprocesses (real uvicorn, real Playwright, real upstream)
  - `feedback_no_silent_swallow.md` — skip messages must be loud and explain what was skipped
  - `feedback_no_proactive_fetch.md` — for any test that re-uses cache to avoid re-fetching, it must explicitly `--from-cache`
  - `user_testing_machine.md` — M14 mode 1 is validation machine

---

## §6 Files map

```
session_artifacts/_impl/p4_e2e/
├── brief.md                  (this file)
├── tester_report.md          (D4)
├── verifier_report.md        (D5)
└── critique.md               (D6)

tests/e2e/
└── test_p4_real_business_flow.py    (new, D3)

scripts/deploy/
└── README_DEPLOY.md          (D1, 6 edits)

tests/backend/
└── test_deploy_smoke_script.py     (D1, 1 docstring edit)
```

---

## §7 Expected output

Two commits on `claude/keen-wu-b8b520`:

1. `fix(deploy): pwsh → powershell in README + test docstrings`
   - 7 string replacements
   - depends only on D1
   - smoke test: `python -m pytest tests/backend/test_deploy_*.py -v`

2. `test(p4-e2e): real intranet upstream + concurrent planner + server switch`
   - D3 new test file
   - depends on D2/D3/D4/D5/D6 all green/APPROVE

If E2E surfaces real backend regression (e.g., concurrent fetch double-fires upstream MultiRobotTestSpin) → loop-back the implementer in a separate brief.

---

## §8 Coordinator decision log

- Why pwsh fix in separate commit: tiny, isolated, doc/test docstring only — clean revert path if something else breaks.
- Why 1000 spin not 100: 100 may not exercise the AIMD tuner, chunk splitting, or full analyzer round_classification path. 1000 is small enough to land in <60s yet still touches the realistic code path.
- Why not test fleet refresh: 393 machines × even 100 spin each = hours, plus would actually fan out to real upstream — disproportionate cost. Existing P3 unit tests + the new G6 server switch cover the dependency surface.
- Why not test config upload e2e: P3's backend tests already cover the dedup + sidecar path. UI is reused-pattern (no new helper). Defer.
