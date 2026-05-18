# P4 E2E Verifier Report

Date: 2026-05-17
Agent: impl-verifier
Branch: claude/keen-wu-b8b520 (HEAD 190dc9d)

---

## RV1 -- Pre-existing rollback failures: origin determination

Commands run:

Step 2 (pure 190dc9d HEAD, all working-tree changes stashed, no pytest.ini):
  python -m pytest tests/backend/test_deploy_rollback_script.py -v
  FAILED test_rollback_refuses_with_uncommitted_changes (TimeoutExpired 30s)
  FAILED test_rollback_without_force_prompts_before_reset (TimeoutExpired 30s)
  Result: 2 failed, 1 passed in 60.51s

Step 5 (working tree restored including pytest.ini):
  python -m pytest tests/backend/test_deploy_rollback_script.py -v
  Result: IDENTICAL -- 2 failed, 1 passed in 60.52s. pytest.ini has zero effect.

Verdict: scenario (a) -- baseline was dirty at 190dc9d. Both failures exist at pure P4
  commit with no working-tree changes. P4 claim 1111 passed is FALSE.

Root cause: test timeout=30 equals rollback.ps1 Step 2 port-poll loop (while waited<30).
  Get-NetTCPConnection scans slowly enough to consume 30s. subprocess.run fires
  TimeoutExpired before the script reaches Step 4 (dirty-check) or Step 6 (Read-Host).
---

## RV2 -- R1 (DELETE bug) independent confirmation

Code inspection (app.py lines 6851-6880):

  else:  # no mode param
      machine_dir = rd_root / machine
      modes_to_lock = []
      if machine_dir.is_dir():   # FALSE when rawdata/M14 absent
          for md in ...: ...    # never runs
  for m in modes_to_lock:        # empty loop -- 409 guard never fires
      if not registry.try_acquire_cell(...):
          raise HTTPException(409, ...)
  # proceeds to delete_rawdata() -> {ok:true, deleted:false, reason:not_found}

Live uvicorn test (isolated tmp state dir, real subprocess):
  POST /api/batch-run: 200 {batch_id:fedb88d374af, status:running, total:1}
  Item status: running (SAMPLING lock acquired)
  rawdata/M14 exists: False  <-- R1 precondition confirmed
  DELETE /api/rawdata/M14 (no mode): status=200
    body={ok:true, deleted:false, reason:not_found, deleted_chunks:0, kept_chunks:0}
  R1 CONFIRMED: DELETE returned 200 instead of 409 while SAMPLING active
  DELETE /api/rawdata/M14?mode=1 (explicit mode): status=409
    body={detail: cell M14|1 is busy (SAMPLING or GENERATING) --
           retry after the active operation completes}

Verdict: R1 CONFIRMED. All-modes DELETE /api/rawdata/{machine} returns HTTP 200 when
  SAMPLING is active and rawdata/M14 dir is absent. Explicit ?mode=1 correctly returns 409.
  Planner-facing UI uses all-modes path. Real planners can silently delete while sampling
  is in-flight before first chunk is written.
---

## RV3 -- Tester side-effect audit

Stash check:
  git stash list: NO entry named p4_e2e_tester_side_effects.
  The coordinators described stash does not exist.
  Both side effects remain in working tree:
    configs/servers.json: default_server changed from prod to dev
    configs/machines.json: 858 insertions / 11 deletions (fleet refresh writeback)

Side effect source -- set_default_server endpoint (app.py line 7158):
  cfg_path = SERVERS_CONFIG  # module-level constant = real configs/servers.json
  create_app() has no servers_config parameter (line 5715-5728).
  sc = SERVERS_CONFIG (line 5747) -- hardcoded, not parameterized.
  live_server fixture isolation does NOT cover servers_config.

Does test_server_switch_default_and_scan re-introduce the side effect when re-run?
  YES. Sequence when dev TCP is reachable:
  1. _require_dev_upstream() -- TCP check passes, test enters body
  2. GET /api/servers -- read-only, no side effect
  3. PUT /api/servers/dev/set-default -- WRITES to real configs/servers.json
  4. POST /api/servers/dev/scan -- returns 502
  5. pytest.skip() fires -- AFTER step 3 has already mutated the file

Leaky tests:
  1. test_server_switch_default_and_scan -- LEAKY. Writes real configs/servers.json
     when dev TCP reachable. Skip fires after write. No cleanup.
     Root cause: SERVERS_CONFIG module constant; no servers_config param in create_app.

  2. Other tests -- no leaks to real directories. live_server tmp dirs only.

Orphan check after RV3 runs:
  git status --porcelain after running tests/e2e/test_p4_real_business_flow.py -m not real_upstream:
  Status identical to session start. No new rawdata/M14 or reports/M14 orphans.
---

## RV4 -- Total sweep numbers

Backend-only (run 1):
  python -m pytest tests/backend/ --ignore=tests/backend/test_analyzer_st_split.py -q
  3 failed, 1108 passed, 23 skipped in 187s
  FAILED test_chunk_index::TestSidecarRoundtrip::test_bulk_remove_entries_single_write
  FAILED test_deploy_rollback_script::test_rollback_refuses_with_uncommitted_changes
  FAILED test_deploy_rollback_script::test_rollback_without_force_prompts_before_reset

Backend-only (run 2):
  python -m pytest tests/backend/ --ignore=tests/backend/test_analyzer_st_split.py -q
  2 failed, 1109 passed, 23 skipped in 186s
  (chunk_index flake did not reproduce -- pre-existing StubProcess thread-join flake)

  Stable count: 2 failed, 1109 passed, 23 skipped

Backend + e2e excluding real_upstream:
  python -m pytest tests/backend/ tests/e2e/ --ignore=tests/backend/test_analyzer_st_split.py -q -m not real_upstream
  2 failed, 1112 passed, 34 skipped, 3 deselected in 197s

Backend + e2e full (real_upstream included):
  python -m pytest tests/backend/ tests/e2e/ --ignore=tests/backend/test_analyzer_st_split.py -q
  2 failed, 1114 passed, 35 skipped in 270s

Summary:
  | Suite                    | Passed | Failed | Skipped |
  |--------------------------|--------|--------|---------|
  | backend-only             |  1109  |   2    |   23    |
  | backend+e2e (-r.u.)      |  1112  |   2    |   34    |
  | backend+e2e (full)       |  1114  |   2    |   35    |

P4 commit claim of 1111 passed is FALSE. True backend count: 1109 passed + 2 failed + 23 skipped.
---

## RV5 -- Silent-skip audit on test_p4_real_business_flow.py

pytest.skip() call inventory:

1. _require_dev_upstream() line 82: fires at test start if TCP unreachable.
   Loud message names host:port and lists affected goals (G3/G4/G5/G6).
   Called by 4 of 5 tests. Correct placement. CLEAN.

2. test_real_fetch_M14_mode1_via_dev_upstream line 202: fires after batch fails
   with upstream_unstable/502 error. Message loud, distinguishes upstream outage
   from code bug. _cleanup_m14(live_server) called before this point.
   ACCEPTABLE -- suggest moving cleanup to finally block for robustness.

3. test_delete_during_fetch_returns_409 line 442: fires when batch item hits
   terminal state before the DELETE race. Loud message. max_chunks=2 mitigates
   timing window. ACCEPTABLE.

4. test_server_switch_default_and_scan line 520: fires when scan returns 502
   AFTER PUT /api/servers/dev/set-default has already written to configs/servers.json.
   Skip message is loud but side effect is NOT cleaned up.
   RISKY -- requires fix before commit.

TCP probe gating analysis:
  _require_dev_upstream() checks TCP only (not API health). Dev TCP passes;
  sampling API returns 502. Tests enter bodies and skip mid-way.
  Not silent (messages are loud) but for test_server_switch the consequence
  is a persistent side effect with no cleanup.

Verdict: BORDERLINE.
  3/4 skip patterns: CLEAN or ACCEPTABLE.
  1/4 (test_server_switch line 520): post-side-effect skip without cleanup -- requires fix.
---

## Additional findings

F1: create_app isolation gap for servers_config

  create_app() (app.py line 5715) accepts rawdata_root, cache_root, state_dir, etc.
  but has NO servers_config parameter. The sc variable at line 5747 is hardcoded:
    sc = SERVERS_CONFIG  # always the real configs/servers.json
  The set_default_server endpoint at line 7158 further bypasses sc:
    cfg_path = SERVERS_CONFIG  # reads module constant directly
  Any test-uvicorn call to PUT /api/servers/{id}/set-default permanently modifies
  the real configs/servers.json. Same structural gap for scan -> machines.json.

  Fix: add servers_config parameter to create_app(); update sc assignment;
  update set_default_server to use sc not the module constant;
  update conftest.py to pass a tmp servers.json copy.

F2: P4 commit message false claim

  True count at 190dc9d: 1109 passed + 2 failed + 23 skipped (backend suite only).
  The 2 rollback tests were failing at P4 commit time. Root cause is that
  test timeout=30 equals the rollback.ps1 Step 2 port-poll loop duration.
  Not a P4-introduced regression -- a pre-existing test design flaw.

F3: transient chunk_index flake (pre-existing)

  test_chunk_index::TestSidecarRoundtrip::test_bulk_remove_entries_single_write
  fails intermittently in full suite (StubProcess thread-join timeout from
  conftest.py line 110). Passes in isolation. Not a new regression.
---

## Verifier verdict

- RV1 (rollback failures origin): scenario (a) -- baseline was dirty at 190dc9d.
  Both failures confirmed at pure P4 HEAD (no working-tree changes, no pytest.ini).
  P4 commit claim 1111 passed is FALSE (true: 1109 passed + 2 failed + 23 skipped).

- RV2 (R1 reality): CONFIRMED -- live uvicorn test + code inspection both confirm
  DELETE /api/rawdata/M14 (no mode) returns HTTP 200 instead of 409 when SAMPLING
  is active and rawdata/M14 dir is absent. Explicit ?mode=1 correctly returns 409.

- RV3 (side effects): Coordinator stash p4_e2e_tester_side_effects does not exist.
  configs/servers.json and configs/machines.json both modified in working tree.
  Leaky test: test_server_switch_default_and_scan writes real configs/servers.json
  unconditionally when dev TCP is reachable. Skip fires after the write. No cleanup.

- RV4 (sweep numbers):
  backend-only:                1109 passed / 2 failed / 23 skipped
  backend+e2e (-real_upstream): 1112 passed / 2 failed / 34 skipped
  backend+e2e (full):           1114 passed / 2 failed / 35 skipped

- RV5 (silent skips): BORDERLINE -- 3/4 skips clean or acceptable;
  1/4 (test_server_switch line 520) writes side effect before skip fires, no cleanup.

- Overall: LOOP-BACK with:

  1. impl-implementer:

     (a) Fix R1 -- delete_machine_rawdata all-modes path must check CellLockRegistry
         directly for any active locks, not just scan on-disk mode_ dirs.
         The registry is the authoritative source of in-flight operations.

     (b) Fix create_app isolation gap -- add servers_config parameter to create_app();
         use it for sc; update set_default_server to use sc not SERVERS_CONFIG;
         update conftest.py to pass tmp servers.json so tests are fully isolated.

  2. impl-tester:

     (a) Fix rollback test timeout -- increase subprocess timeout to 60+ seconds, or
         refactor tests that only check pre-flight guards to use -DryRun flag (which
         skips the 30s port-poll loop at Step 2).

     (b) Fix test_server_switch_default_and_scan -- add try/finally block to restore
         the original default_server value from configs/servers.json unconditionally
         regardless of skip/pass/fail outcome.

  3. Coordinator:

     Restore configs/servers.json default_server to prod.
     Determine whether configs/machines.json 858-line fleet refresh is intentional.