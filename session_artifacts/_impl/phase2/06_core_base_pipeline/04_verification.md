# P2-B4 Verification Report

**Verdict: PASS**

647 tests pass (13 skipped, all intentional). P1-A1 canary 23/23. No regressions.

---

## Step 1 - P1-A1 3-invocation parity canary

Command:
  python -m pytest tests/integration/test_analyzer_three_invocation_parity.py -v

Result: 23/23 PASS (26.87s)

Test classes:
  TestThreeInvocationParity (7): RTP/md5/version/payoutIDs/spins/halfwidth/bankruptcy parity paths A+C
  TestBatchManagerMetadataParity (5): path B batch-run md5/version/status match
  TestInjectBugPathADiverges (2): inject-bug proofs
  TestInjectBugR1BatchRunManagerPath (1): rawdata root isolation
  TestSubprocessCoverage (5): all 3 paths produce nonzero spins + summary file
  TestCommonFixtureGuard (3): fixture validity

Verdict: PASS

---

## Step 2 - Full 9-suite regression

Command:
  python -m pytest tests/integration/test_analyzer_three_invocation_parity.py
    tests/backend/test_analyzer_core_parser.py
    tests/backend/test_analyzer_core_aggregator.py
    tests/backend/test_analyzer_core_writer.py
    tests/backend/test_analyzer_core_base_pipeline.py
    tests/backend/test_lookup_machine_md5_canonical.py
    tests/backend/test_summary_md5_writer_parity.py
    tests/backend/test_analyzer_foundation.py
    tests/backend/test_manifest_loader.py -q

Observed: 647 passed, 13 skipped in 32.32s
Expected: 647 passed, 13 skipped

Verdict: PASS - exact match

---

## Step 3 - app.py monkey-patch fix verification

grep -n post_json src/web_console/backend/app.py | head -20

Relevant observed lines:
  7134: _saved_post = pia.post_json
  7141: _saved_core_post = _core_bp.post_json
  7146: pia.post_json = _post_stub
  7147: _core_bp.post_json = _post_stub
  7210: pia.post_json = _saved_post
  7211: _core_bp.post_json = _saved_core_post  # P2-B4: restore base_pipeline too

Both pia.post_json and _core_bp.post_json are:
  - Saved to distinct local variables before patching
  - Patched to the same _post_stub lambda
  - Restored in the finally block (lines 7210-7211)

Structural correctness: run_sampling_chunk -> post_json_with_retry -> post_json
reads post_json from base_pipeline module namespace. Patching only pia.post_json
would miss the canonical lookup site. The fix patches both and restores both.

Verdict: PASS

---

## Step 4 - AIMD coefficient empirical preservation

Command:
  python -m pytest tests/backend/test_analyzer_core_base_pipeline.py::TestAIMDCoefficients -v

Result: 9/9 PASS (0.05s)

  test_aimd_additive_increase_on_success          PASSED
  test_aimd_additive_increase_capped_at_max       PASSED
  test_aimd_multiplicative_decrease_on_failure    PASSED
  test_aimd_floor_at_one_not_zero                 PASSED
  test_aimd_spins_growth_factor                   PASSED
  test_aimd_spins_floor_at_min_chunk_spins        PASSED
  test_aimd_success_streak_grows_then_resets      PASSED
  test_aimd_tuple_shape_is_4                      PASSED
  test_aimd_constants_values_match_pia            PASSED

Manual constant verification (observed):
  MIN_CHUNK_SPINS = 500
  SUCCESS_STREAK_FOR_GROW = 1
  CHUNK_SPINS_GROWTH = 1.25
  CIRCUIT_PAUSE_S = 3.0
  _RETRYABLE_HTTP_CODES = frozenset({500, 502, 503, 504})

Verdict: PASS - no drift from PIA original

---

## Step 5 - post_json signature compatibility

grep -rn "post_json(" fresh_slotlab/ (excluding test_ and .pyc):
  fresh_slotlab/analyzer/core/base_pipeline.py:279  def post_json(payload, timeout)  -- canonical def
  fresh_slotlab/analyzer/core/base_pipeline.py:425  return post_json(...)  -- post_json_with_retry internal
  fresh_slotlab/sampler.py:73   def post_json(url, payload, timeout)  -- independent 3-arg def
  fresh_slotlab/sampler.py:272  response = post_json(...)  -- calls sampler own def

sampler.py post_json has a different 3-arg signature and is entirely independent.
Not a regression.

pia.post_json is bp.post_json: True (confirmed Step 7).

Verdict: PASS

---

## Step 6 - Subprocess smokes

python -c "import fresh_slotlab.analyzer.core.base_pipeline"
  rc=0, no output, no stderr

python -c "import fresh_slotlab.player_impact_analyzer"
  rc=0, no output, no stderr

Verdict: PASS - both modules import cleanly

---

## Step 7 - Identity check (all 8 symbols)

Command:
  python -c "import fresh_slotlab.player_impact_analyzer as pia, fresh_slotlab.analyzer.core.base_pipeline as bp; assert all(getattr(pia, s) is getattr(bp, s) for s in ['parse_args','post_json','_classify_failure','aimd_tune','post_json_with_retry','select_replay_chunks_by_md5','make_payload','run_sampling_chunk']); print('OK')"

Result: OK, rc=0

Verdict: PASS - all 8 symbols are identical objects via both pia.* and bp.*

---

## Step 8 - Cycle freedom AST

Command (Python snippet):
  AST-walked base_pipeline.py; checked all ImportFrom/Import nodes for player_impact_analyzer

Result: PASS - no player_impact_analyzer import nodes found

Sibling check:
  grep -n base_pipeline in parser.py / aggregator.py / writer.py / _utils.py
  Result: 0 matches

Verdict: PASS - no cycle in either direction

---

## Step 9 - Shadow-def grep in PIA

Command:
  grep -c "^def parse_args|^def post_json|^def _classify_failure|^def aimd_tune|..."
    fresh_slotlab/player_impact_analyzer.py

Result: 0

PIA contains only tombstone comments + dual-path import re-exports for all 8 symbols.

Verdict: PASS

---

## Step 10 - End-to-end cached chunk run

Satisfied by P1-A1 canary (Step 1) against M14 mode 1 cached fixtures.

  TestSubprocessCoverage::test_path_a_summary_has_nonzero_spins  PASSED
  TestSubprocessCoverage::test_path_b_summary_has_nonzero_spins  PASSED
  TestSubprocessCoverage::test_path_c_summary_has_nonzero_spins  PASSED

Path C specifically exercises _run_generate_report with _core_bp.post_json patched,
validating the app.py fix from Step 3.

Verdict: PASS

---

## Aggregate test count

Suite                                        Passed   Skipped   Failed
test_analyzer_three_invocation_parity.py     23       0         0
test_analyzer_core_base_pipeline.py          128      2         0
All other 7 suites combined                  496      11        0
TOTAL (9 suites)                             647      13        0

13 skips: 2 are C6 hash-composition (compute_base_analyzer_version not yet exported
from versioning.py, consistent with P2-B1b/B2/B3). Rest are pre-existing intentional.

---

## Subprocess vs in-process coverage

  Path A (subprocess): exercised by TestSubprocessCoverage + TestThreeInvocationParity
  Path B (batch worker subprocess): exercised by TestBatchManagerMetadataParity
  Path C (in-process monkeypatch): exercised by TestThreeInvocationParity parity tests
  Import safety: TestSubprocessImportSafety - real subprocess.run, rc=0, no stderr

---

## Frontend preview: N/A (backend-only ticket)

## md5/version invariants: C6 deferred, no new cache write paths (no verification needed)

## Regressions in untouched areas: None (647 passed across all 9 suites)

---

## Additional findings

ENDPOINT_URL Option B mutability confirmed:
  bp.ENDPOINT_URL mutation propagates to post_json at call time (reads from module namespace).
  pia.ENDPOINT_URL remains a snapshot binding (expected, documented in impl notes).
  post_json source confirmed to read ENDPOINT_URL from module namespace, not closure.

DEFAULT_GUIDELINE_RULES_PATH:
  Resolved to <repo_root>/configs/classic_slots_guideline_rules.json
  exists(): True, is_file(): True
  parents[3] calculation correct for base_pipeline.py at fresh_slotlab/analyzer/core/.

---

Verification date: 2026-05-19
Verifier: impl-verifier (claude-sonnet-4-6)
