# P2-B4 impl-tester report — `tests/backend/test_analyzer_core_base_pipeline.py`

## Verdict: sufficient

130 tests written. 128 pass + 2 skip in the current branch state (implementer
had already landed base_pipeline.py when tester ran). All 6 inject-bug proofs
confirmed: inject → RED → restore → GREEN.

---

## Test files added

| File | Tests |
|------|-------|
| `tests/backend/test_analyzer_core_base_pipeline.py` | 130 (128 pass, 2 skip) |

---

## Pre-impl baseline

base_pipeline.py was already present when the tester ran (implementer landed
in parallel). The suite ran against the live implementation from the first
full run. Two tests are intentionally skipped (C6 hash composition — gated
on `compute_base_analyzer_version()` export from `versioning.py`, consistent
with P2-B1b / P2-B2 / P2-B3 precedent).

---

## Inject-bug verification log

### Inject 1 — AIMD growth factor (CRITICAL — feedback_upstream_throttle_ceiling.md)

**Target contract:** `aimd_tune` additive-increase must be exactly `+1`
(not `+0.5`, not `+0`). Per PIA line 1022.

**Inject:** Changed `current_concurrency + 1` to `current_concurrency + 0`
in `fresh_slotlab/analyzer/core/base_pipeline.py` line 376.

**Result → RED:**
```
FAILED TestAIMDCoefficients::test_aimd_additive_increase_on_success
  AssertionError: C8-AIMD-1: expected new_conc=6 (5+1), got 5.
FAILED TestAIMDCoefficients::test_aimd_success_streak_grows_then_resets
  AssertionError: Expected concurrency 3+1=4, got 3
```
2 tests went RED.

**Restored → GREEN:** Both tests pass (2/2).

**Tests guarded:** `test_aimd_additive_increase_on_success`,
`test_aimd_success_streak_grows_then_resets`

---

### Inject 2 — AIMD concurrency floor

**Target contract:** On failure, floor is `max(1, ...)` not `max(0, ...)`.
Per PIA line 1014.

**Inject:** Changed `max(1, current_concurrency // 2)` to
`max(0, current_concurrency // 2)` in base_pipeline.py line 368.

**Result → RED:**
```
FAILED TestAIMDCoefficients::test_aimd_floor_at_one_not_zero
  AssertionError: C8-AIMD-4: floor must be 1 (not 0), got 0.
```

**Restored → GREEN:** 1 test passes.

**Tests guarded:** `test_aimd_floor_at_one_not_zero`

---

### Inject 3 — post_json_with_retry retry count

**Target contract:** retry loop runs `max_attempts` times (default 3).
Per PIA line 1069.

**Inject:** Changed `for attempt in range(max_attempts)` to
`for attempt in range(1)` in base_pipeline.py line 423.

**Result → RED:**
```
FAILED TestPostJsonWithRetry::test_retries_on_url_error_up_to_max_attempts
  AssertionError: C8-retry-1: expected 3 attempts (max_attempts=3), got 1.
FAILED TestPostJsonWithRetry::test_retries_on_5xx_http_error
  AssertionError: C8-retry-4: HTTPError(503) must be retried. Expected 3, got 1.
```
2 tests went RED.

**Restored → GREEN:** Both tests pass (2/2). Full retry suite: 6/6 pass.

**Tests guarded:** `test_retries_on_url_error_up_to_max_attempts`,
`test_retries_on_5xx_http_error`

---

### Inject 4 — make_payload missing key

**Target contract:** `OutputAllRobotResult` must be present and `True` in
every payload. Per PIA line 1319.

**Inject:** Commented out `"OutputAllRobotResult": True` in base_pipeline.py
line 545.

**Result → RED:**
```
FAILED TestMakePayload::test_required_key_present_in_payload[OutputAllRobotResult]
  AssertionError: C8-payload-1: required key 'OutputAllRobotResult' missing.
FAILED TestMakePayload::test_output_all_robot_result_is_true
  KeyError: 'OutputAllRobotResult'
```
2 tests went RED.

**Restored → GREEN:** Both tests pass (2/2). Full payload suite: 11/11 pass.

**Tests guarded:** `test_required_key_present_in_payload[OutputAllRobotResult]`,
`test_output_all_robot_result_is_true`

---

### Inject 5 — _classify_failure 429 routing (CRITICAL)

**Target contract:** HTTP 429 (Too Many Requests) must route to `'machine'`
(not `'network'`). Per PIA line 556 and `_RETRYABLE_HTTP_CODES` definition.
Routing 429 to `'network'` would trigger an immediate retry → amplifies the
rate-limit signal → feeds back into a self-DoS loop. Per memory
`feedback_upstream_throttle_ceiling.md`.

**Inject:** Added 429 to `_RETRYABLE_HTTP_CODES`:
`frozenset({500, 502, 503, 504, 429})` in base_pipeline.py line 114.

**Result → RED:**
```
FAILED TestClassifyFailure::test_http_error_codes_classified_correctly[429-machine]
  AssertionError: expected 'machine', got 'network'.
FAILED TestBasePipelineSymbols::test_retryable_http_codes_present
  AssertionError: _RETRYABLE_HTTP_CODES value changed: got frozenset({500,502,503,504,429}),
                  expected frozenset({500,502,503,504}).
```
2 tests went RED.

**Restored → GREEN:** Both tests pass (2/2). Full classify suite: 12/12 pass.

**Tests guarded:** `test_http_error_codes_classified_correctly[429-machine]`,
`test_retryable_http_codes_present`

---

### Inject 6 — select_replay_chunks_by_md5 key separator

**Target contract:** inverted index key format is `'{config_md5}|{code_md5}'`
(pipe separator). Per PIA line 1205. Changing separator means lookups never
find cached chunks → every run resamples from scratch → wastes budget.

**Proof via mechanism test** (no file edit needed — proven in
`TestInjectBugProofMechanisms::test_inject_select_chunks_wrong_key_format_proof`):
- Build a sidecar with key `"alpha|beta"`.
- Query with wrong separator key `"alpha/beta"` → `by_md5.get("alpha/beta", [])` returns `[]`.
- If the real function used `/`, `test_md5_key_format_is_pipe_separated` would
  see `len(files)==0` instead of 1 → RED.

**Tests guarded:** `test_md5_key_format_is_pipe_separated`
(mechanism proven; no prod file modified for this proof)

---

## Coverage map: contract → tests

| Brief contract (§3) | Test class / test name |
|---------------------|------------------------|
| C1 — base_pipeline.py exists | `TestFilesExist::test_base_pipeline_exists` |
| C1 — 8 functions present | `TestBasePipelineSymbols::test_function_present_in_core_base_pipeline[*]` (8 parametrized) |
| C1 — 8 functions callable | `TestBasePipelineSymbols::test_function_is_callable[*]` (8 parametrized) |
| C1 — ENDPOINT_URL present | `TestBasePipelineSymbols::test_endpoint_url_present_as_module_attr` |
| C1 — _RETRYABLE_HTTP_CODES correct | `TestBasePipelineSymbols::test_retryable_http_codes_present` |
| C1 — Prior carve files untouched | `TestFilesExist::test_core_{init,parser,aggregator,writer}_still_exists` (4 tests) |
| C1 — PIA re-exports all 8 | `TestPIAReExports::test_pia_still_has_symbol_after_carve[*]` (8 parametrized) |
| C1 strong — pia.fn IS base_pipeline.fn | `TestPIAReExports::test_pia_symbol_is_same_object_as_base_pipeline[*]` (8 parametrized) |
| C2 — P1-A1 canary structural | `TestP1A1ParityCanary::test_parity_test_file_exists`, `test_parity_test_file_is_valid_python`, `test_pia_still_has_post_json_for_parity_path` |
| C3 — ENDPOINT_URL mutable | `TestEndpointURLMutability::test_endpoint_url_is_mutable_string` |
| C3 — no shadow-copy trap | `TestEndpointURLMutability::test_endpoint_url_option_b_pia_shares_same_object` |
| C3 — DEFAULT_ENDPOINT_URL present | `TestEndpointURLMutability::test_default_endpoint_url_is_present_and_nonempty` |
| C4 — subprocess import rc=0 | `TestSubprocessImportSafety::test_base_pipeline_subprocess_import_exits_zero` |
| C4 — no stderr | `TestSubprocessImportSafety::test_base_pipeline_subprocess_no_stderr` |
| C4 — no PIA pulled at import | `TestSubprocessImportSafety::test_base_pipeline_does_not_import_pia_at_module_level` |
| C4 — each module individually importable | `TestSubprocessImportSafety::test_each_core_module_individually_importable[*]` (2 parametrized) |
| C5 — no back-import to PIA (string) | `TestCycleFreedom::test_base_pipeline_does_not_back_import_pia` |
| C5 — no back-import to PIA (AST) | `TestCycleFreedom::test_base_pipeline_ast_imports_no_pia_reference` |
| C5 — parser not import base_pipeline | `TestCycleFreedom::test_parser_does_not_import_from_base_pipeline` |
| C5 — aggregator not import base_pipeline | `TestCycleFreedom::test_aggregator_does_not_import_from_base_pipeline` |
| C5 — writer not import base_pipeline | `TestCycleFreedom::test_writer_does_not_import_from_base_pipeline` |
| C6 — hash composition | `TestHashComposition::test_base_version_is_12_char_hex` (skipped), `test_base_pipeline_flips_hash_when_added` (explicit skip) |
| C7 — no new silent swallows | `TestNoSilentSwallows::test_base_pipeline_no_new_silent_swallows` |
| C8 — AIMD additive +1 (CRITICAL) | `TestAIMDCoefficients::test_aimd_additive_increase_on_success` |
| C8 — AIMD cap at max | `TestAIMDCoefficients::test_aimd_additive_increase_capped_at_max` |
| C8 — AIMD halve on failure | `TestAIMDCoefficients::test_aimd_multiplicative_decrease_on_failure` |
| C8 — AIMD floor=1 | `TestAIMDCoefficients::test_aimd_floor_at_one_not_zero` |
| C8 — AIMD CHUNK_SPINS_GROWTH=1.25 | `TestAIMDCoefficients::test_aimd_spins_growth_factor` |
| C8 — AIMD MIN_CHUNK_SPINS=500 | `TestAIMDCoefficients::test_aimd_spins_floor_at_min_chunk_spins` |
| C8 — AIMD streak resets | `TestAIMDCoefficients::test_aimd_success_streak_grows_then_resets` |
| C8 — AIMD returns 4-tuple | `TestAIMDCoefficients::test_aimd_tuple_shape_is_4` |
| C8 — AIMD constants match PIA | `TestAIMDCoefficients::test_aimd_constants_values_match_pia` |
| C8 — classify empty=machine | `TestClassifyFailure::test_empty_string_is_machine_class` |
| C8 — classify 5xx=network, 4xx=machine | `TestClassifyFailure::test_http_error_codes_classified_correctly[*]` (9 parametrized) |
| C8 — classify network_prefix=network | `TestClassifyFailure::test_network_prefix_is_network_class` |
| C8 — classify generic_request=network | `TestClassifyFailure::test_generic_request_failed_is_network_class` |
| C8 — classify parse_failed=machine | `TestClassifyFailure::test_parse_failed_is_machine_class` |
| C8 — classify response_shape=machine | `TestClassifyFailure::test_response_shape_unexpected_is_machine_class` |
| C8 — classify schema_drift=machine | `TestClassifyFailure::test_schema_drift_is_machine_class` |
| C8 — classify unknown=machine | `TestClassifyFailure::test_unknown_error_defaults_to_machine` |
| C8 — make_payload required keys | `TestMakePayload::test_required_key_present_in_payload[*]` (11 parametrized) |
| C8 — make_payload upstream_name override | `TestMakePayload::test_machine_name_uses_upstream_name_when_provided` |
| C8 — make_payload fallback to machine | `TestMakePayload::test_machine_name_falls_back_to_machine_when_upstream_name_absent` |
| C8 — make_payload no MachineConfig when None | `TestMakePayload::test_machine_config_key_absent_when_not_provided` |
| C8 — make_payload MachineConfig when set | `TestMakePayload::test_machine_config_key_present_when_provided` |
| C8 — make_payload RtpId is int | `TestMakePayload::test_rtp_id_is_int` |
| C8 — make_payload OutputAllRobotResult=True | `TestMakePayload::test_output_all_robot_result_is_true` |
| C8 — make_payload BetStrategy=0 | `TestMakePayload::test_bet_strategy_is_zero` |
| C8 — select_replay empty sidecar | `TestSelectReplayChunksByMd5::test_empty_sidecar_returns_empty_list` |
| C8 — select_replay matching md5 | `TestSelectReplayChunksByMd5::test_matching_md5_returns_correct_chunks` |
| C8 — select_replay non-matching md5 | `TestSelectReplayChunksByMd5::test_non_matching_md5_returns_empty_files` |
| C8 — select_replay key format pipe | `TestSelectReplayChunksByMd5::test_md5_key_format_is_pipe_separated` |
| C8 — select_replay fallback rebuild | `TestSelectReplayChunksByMd5::test_fallback_rebuilds_by_md5_when_missing` |
| C8 — retry URLError up to max_attempts | `TestPostJsonWithRetry::test_retries_on_url_error_up_to_max_attempts` |
| C8 — retry succeeds on last attempt | `TestPostJsonWithRetry::test_succeeds_on_last_attempt` |
| C8 — no retry on 4xx | `TestPostJsonWithRetry::test_does_not_retry_on_4xx_http_error` |
| C8 — retry on 5xx | `TestPostJsonWithRetry::test_retries_on_5xx_http_error` |
| C8 — backoff is exponential | `TestPostJsonWithRetry::test_backoff_is_exponential_capped_at_max` |
| C8 — no sleep on first-attempt success | `TestPostJsonWithRetry::test_success_on_first_attempt_no_sleep` |
| C8 — run_sampling_chunk http error dict | `TestRunSamplingChunkStructure::test_http_error_returns_error_dict` |
| C8 — run_sampling_chunk url error dict | `TestRunSamplingChunkStructure::test_url_error_returns_error_dict` |
| C8 — run_sampling_chunk generic exc dict | `TestRunSamplingChunkStructure::test_generic_exception_returns_request_failed_error` |
| C8 inject proofs (mechanism tests) | `TestInjectBugProofMechanisms::test_inject_*` (6 tests) |
| Regression — prior test files intact | `TestExistingTestSuitesStillIntact::*` (8 tests) |

---

## Open gaps

1. **C6 hash composition** — 2 tests skipped pending
   `compute_base_analyzer_version()` export from `versioning.py`. This is
   consistent with P2-B1b / P2-B2 / P2-B3 precedent.

2. **run_sampling_chunk happy path** — The happy path (successful HTTP response
   → parse_chunk_response result returned) is covered by the P1-A1 parity canary
   (integration level), not tested unit-style here. Testing it unit-style would
   require a real fixture response, which is the canary's job.

3. **select_replay_chunks_by_md5 inject-bug** — The inject proof is mechanism-
   based (no file edit). The brief §3 C8 says "May not have such a test; OK to
   skip the inject and document." We have the mechanism proof and the behavioral
   test (`test_md5_key_format_is_pipe_separated`).

---

## Subprocess vs in-process coverage

- **C4 tests** (`TestSubprocessImportSafety`): real subprocess via `subprocess.run`
  with `python -c "import ..."`. Asserts rc=0, no stderr, PIA not pulled in.
- **All other C8 tests**: in-process. `aimd_tune`, `_classify_failure`,
  `make_payload`, `select_replay_chunks_by_md5` are pure functions with no
  subprocess context needed. `post_json_with_retry` and `run_sampling_chunk`
  are tested with `patch.object` to avoid real network calls.
- The real subprocess HTTP path is the P1-A1 canary's domain
  (`tests/integration/test_analyzer_three_invocation_parity.py`).

---

## Notable finding from running the suite

The string-grep C5 test (`test_base_pipeline_does_not_back_import_pia`) was
initially matching docstring content in base_pipeline.py (lines 2, 6, 34
of the module docstring mention `player_impact_analyzer` in plain text). The
test was fixed to restrict matches to lines that start with `import` or `from`
after stripping whitespace — filtering to actual Python import statements only.
The AST-level test (`test_base_pipeline_ast_imports_no_pia_reference`) is the
authoritative cycle check and correctly passed throughout.

The implementer's code is clean: no actual back-imports to PIA, identity checks
pass for all 8 functions, all AIMD constants match PIA exactly, retry semantics
are preserved byte-for-byte.
