# 05_critique_round2.md — Ticket P1-A2: Three Summary MD5 Writers Parity (Round 2)

**Critic**: impl-critic
**Date**: 2026-05-17
**Chain read**: 00_ticket.md, 03_tests.md (with Round 2 updates at top), 05_critique.md (round 1),
04_verification.md (round 1 — PASS on 29 tests), 04_verification_round2.md (ABSENT),
tests/backend/test_summary_md5_writer_parity.py (30 tests, post-R1+R2),
fresh_slotlab/player_impact_analyzer.py (_save_chunk_cache implementation, lines 2162-2259,
_lookup_machine_md5 lines 2138-2159).

---

## Verdict

**APPROVE-WITH-REVISIONS**

The two blocking revisions from round 1 (R1 real-α coverage, R2 call-site proof) are substantively
addressed. The new code is structurally sound. However three issues require attention before this
lands as the dedup baseline:

1. **Round-2 verifier is absent.** The tester claims "30 tests, all green" in 03_tests.md but no
   independent 04_verification_round2.md exists. The round-1 verifier ran against the 29-test file
   and specifically cited `test_c5_module_global_split_path_alpha_uses_call_not_global` as PASS
   (04_verification.md line 101). That test no longer exists. The current file has never been
   independently verified.

2. **R2 inject-bug RED phase is prose-only.** The R1 fix has a permanent RED-phase test
   (`test_injected_wrong_machine_alpha_diverges`). The R2 fix documents the RED scenario only in
   03_tests.md prose ("Inject-bug RED: modify the internal call at line 2206...") — there is no
   permanent test that injects a cached-local alias into `_save_chunk_cache` and asserts the
   sentinel does NOT appear. Without this, the R2 test can only prove GREEN; the claim that it
   would detect a caching bug rests on a thought experiment, not an executed injection.

3. **`_save_chunk_cache` outer `try/except Exception: pass` creates a vacuous-pass risk not
   guarded by any new test.** If any exception fires between lines 2200 and 2222 (before
   `os.replace`), the chunk file is never written. The test's `assert chunk_file.exists()` guard
   covers this. However: if the sentinel-bearing `_lookup_machine_md5` raises unexpectedly (it
   won't — it's a lambda), the outer except swallows it silently, the chunk is not written, and
   `chunk_file.exists()` fails with an informative assertion. This path is fine structurally but
   the test comment does not note the dependency on `assert chunk_file.exists()` as the
   silent-swallow detector.

---

## Stress Questions (5)

### RSQ1 — R1 fix completeness: are there any remaining C2 agreement tests that still use the stub?

**Question**: Round 1 critic found that C2 tests called `_patched_alpha_lookup` (stub) instead of
the real `pia._lookup_machine_md5`. Tester says stub is now retained only for lines 715, 744, 957.
Are these three uses justified, and is there any agreement test that still routes through the stub?

**Attempted answer**: Grep confirms three uses of `_patched_alpha_lookup` in the file (lines 715,
744, 957). Inspecting each:

- **Line 715** (`test_injected_wrong_machine_alpha_diverges`): calls `_patched_alpha_lookup("M1",
  m14_m1_machines_json)` to simulate a buggy α returning M1's md5. This is correct use: the test
  needs to produce M1's md5 values from a fixture path in a controlled way. It does NOT assert
  agreement between this stub and β — it asserts divergence. Justified.

- **Line 744** (`test_c5_monkeypatched_alpha_divergence_is_caught`): calls
  `_patched_alpha_lookup("M1", m14_m1_machines_json)` to get `m1_md5`, then monkeypatches
  `pia._lookup_machine_md5` to return `m1_md5`. The stub is used only to extract fixture values,
  not as the primary test vehicle. Justified.

- **Line 957** (`test_alpha_beta_both_handle_malformed_json`): explicitly justified in docstring
  (calling real `_lookup_machine_md5` with bad JSON would require writing to the real
  `configs/machines.json`, which is unsafe). Testing α's error-handling path via stub is
  appropriate here since we are testing the exception-handling logic, not the agreement property.
  Justified.

No C2 agreement test uses the stub as the primary α vehicle. All C2 agreement tests (`test_alpha_beta_agree_m14_mode1`, `test_alpha_beta_agree_m14_real_config`, `test_three_way_agreement_virtual_m1sim_mode1`, `test_agreement_holds_before_injection`, `test_c5_reverted_alpha_agrees_with_beta`) now call `pia._lookup_machine_md5` directly.

**Verdict**: PASS — R1 fix is complete and the three stub uses are each individually justified.

---

### RSQ2 — R2 fix quality: does `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr` actually cover the α call site, or could it pass vacuously?

**Question**: The test calls `pia._save_chunk_cache(resp={"spins": []}, ...)` with no override
args. `_save_chunk_cache` is wrapped in `except Exception: pass` at line 2250. If `_save_chunk_cache`
silently swallowed an exception before writing the chunk file, `chunk_file.exists()` would fail.
Can the sentinel test pass vacuously?

**Attempted answer**: The test has three ordered assertions:
1. `assert chunk_file.exists()` (line 882) — catches silent-swallow of entire body.
2. `assert envelope.get("_config_md5") == SENTINEL_CFG` (line 889) — catches the case where file
   is written but sentinel was not propagated (e.g., exception before line 2206).
3. `assert envelope.get("_code_md5") == SENTINEL_CODE` (line 897).

Tracing the execution path with `resp={"spins": []}`:
- `_lookup_machine_md5(machine)` is monkeypatched to `lambda machine: (SENTINEL_CFG, SENTINEL_CODE)` — returns a 2-tuple, no exception.
- `json.dumps(envelope, ...)` — standard, no exception with a dict containing basic types.
- `tmp_path.write_text(...)` — writes to `tmp_path / "chunk_0000.json.tmp"` (note: test variable `cache_dir / "chunk_0000.json"` is the out_path, not `tmp_path` from pytest which is a different variable).
- `os.replace(tmp_path_inner, out_path)` — atomic rename succeeds in any standard FS.
- `_rawdata_index_update_entry(...)` — inner try/except, swallowed if it fails.
- `update_chunk_entry(...)` — inner try/except, swallowed if it fails.

The write path (lines 2201–2223) cannot fail with these inputs. The sentinel propagation is
real. The test cannot pass vacuously.

**One naming collision to note**: the test uses `cache_dir` as the pytest `tmp_path`-derived
directory, and inside `_save_chunk_cache`, the local variable is also `cache_dir`. The function's
`tmp_path` local variable (line 2199) is `cache_dir / "chunk_0000.json.tmp"`. This differs from
pytest's injected `tmp_path` fixture which is the parent of `cache_dir` in the test. No collision
in the runtime, but confusing to read.

**Verdict**: PASS — R2 fix is structurally sound. The test cannot pass vacuously.

---

### RSQ3 — R2 inject-bug simulation: is the RED phase documented as execution or thought experiment?

**Question**: For inject-bug TDD (per `feedback_integration_test_argv.md`), the RED phase must be
actually executed, not a thought experiment. The R1 inject-bug has a permanent RED test. Does R2?

**Attempted answer**: The 03_tests.md Round 2 section (lines 51–69) describes the R2 RED phase as:

```
# _cached_local_lookup captured before monkeypatch
pia._lookup_machine_md5 = lambda machine: (SENTINEL_CFG, SENTINEL_CODE)  # monkeypatched
_buggy_save_chunk_cache(...)  # uses _cached_local_lookup, ignores monkeypatch
envelope["_config_md5"] → "4fcf00c48b3d6979aef058fed9ed5f94"  # real value, not sentinel
Sentinel appears: False → test would go RED exposing the caching bug
```

The description refers to `_buggy_save_chunk_cache` — a hypothetical locally-modified version of
`_save_chunk_cache` where line 2206 is changed to `_lmm = _lookup_machine_md5; config_md5, code_md5 = _lmm(machine)`. This modified function was never created as a test-visible artifact.
The 03_tests.md note says "verified via simulation" — this is a thought experiment, not an
executed injection.

In the actual test file, the `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr` test
only exercises the GREEN path (sentinel propagates). There is no companion test that injects the
buggy version and asserts the sentinel does NOT appear. The R1 inject-bug discipline has:
- `test_injected_wrong_machine_alpha_diverges` (permanent RED)
- `test_c5_reverted_alpha_agrees_with_beta` (permanent GREEN)

The R2 discipline has:
- RED: prose only (03_tests.md, no permanent test)
- GREEN: `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr` (permanent)

This is an asymmetry. However, the R2 RED scenario is inherently harder to automate: it requires
modifying the production function (`_save_chunk_cache` at line 2206), which cannot be done inline
without either (a) defining a parallel function or (b) using monkeypatch to replace the entire
`_save_chunk_cache` body with a buggy version. The tester chose to document it in prose instead.

**Verdict**: PARTIAL — R2's RED scenario is undocumented as an executable test. This means if
`_save_chunk_cache` is later refactored to use a cached local (the exact bug pattern), the test
would still go RED (sentinel doesn't propagate), but there is no companion test proving that a
cached-local call site produces the non-sentinel output. The gap is non-blocking but weakens the
TDD chain's bidirectional proof.

---

### RSQ4 — Round-2 verifier absent: has the 30-test file been independently run?

**Question**: `04_verification_round2.md` does not exist. The round-1 verifier ran the 29-test
file and specifically named `test_c5_module_global_split_path_alpha_uses_call_not_global` as
PASS (04_verification.md line 101). That test was deleted in R2. Has the 30-test file been
independently verified?

**Attempted answer**: No independent verification exists for the round-2 file. The 03_tests.md
header says "30 tests, all green" — but this claim comes from the tester, who is the same party
that wrote the tests. Per `feedback_adversarial_self_review.md`, "verify GREEN ≠ done when verify
is what I designed." The round-1 verifier ran three independent runs and confirmed no flakiness.
No equivalent has been done for the round-2 changes.

Specifically, the new test `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr` (line
825) makes a real call to `pia._save_chunk_cache` which creates files on disk via `os.replace`.
On Windows (the confirmed platform per env), `os.replace` can fail if the target is locked.
The test uses `tmp_path` which pytest cleans up atomically. This should work, but the Windows
file-lock risk has never been independently confirmed to not trigger.

**Verdict**: FAIL — the round-2 file has not been independently verified. This is the most
significant process gap in round 2. A round-2 verifier run (3 independent passes on the 30-test
file + flakiness check on the new sentinel test) is required.

---

### RSQ5 — Did the tester actually DELETE the vacuous test, or was it renamed/hidden?

**Question**: Round 1 critic (SQ2) flagged `test_c5_module_global_split_path_alpha_uses_call_not_global` as vacuous. The tester said it was REPLACED. Is it actually gone?

**Attempted answer**: Grep for all name fragments (`module_global_split_path`, `split_path_alpha`,
`uses_call_not_global`) in the test file returns zero matches. The test is genuinely deleted, not
renamed. The replacement `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr` is a
distinct test that exercises a real call site rather than proving `monkeypatch.setattr` works (which
is trivially true for any module attribute).

The 03_tests.md coverage map (C5 section) correctly omits the old test name and lists the new one.

**Verdict**: PASS — the vacuous test is confirmed deleted. The replacement is genuine.

---

## Chain Disagreements (1, carried from Round 1)

### Disagreement 1: Round-1 verifier cites a test that no longer exists

04_verification.md line 101: "Tests: test_c5_monkeypatched_alpha_divergence_is_caught +
`test_c5_module_global_split_path_alpha_uses_call_not_global`. Both PASS."

The second test (`test_c5_module_global_split_path_alpha_uses_call_not_global`) was deleted in R2
and replaced by `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr`. The round-1
verifier document is now stale — it describes a test suite that no longer exists. A round-2
verification run would update this record.

Round-2 critique (this document) and 03_tests.md agree on the current 30-test file contents.
There is no disagreement between them — but the 04_verification.md is a chain artifact that
disagrees with the current test file.

---

## Hidden Assumptions (2, new for round 2)

**HA1 — `_save_chunk_cache` called with `resp={"spins": []}` does not trigger a fast-path early exit or exception before reaching line 2206.** The function has `if cache_dir is None: return` (line 2196) but `cache_dir` is explicitly provided in the test. All downstream helpers (`_compute_upstream_schema_fingerprint`, `_payload_sha256`, `json.dumps`) tolerate a dict response gracefully. The assumption is correct as of the current implementation, but is not independently verified.

**HA2 — `os.replace` on Windows (the runtime platform) does not fail when replacing a non-existent target.** `_save_chunk_cache` writes `.tmp` first, then `os.replace(tmp, out)`. On Windows, `os.replace` can fail if the destination is locked. In tests using `tmp_path`, no other process holds the file, so the risk is low. However, Windows file-locking semantics differ from POSIX, and the test has not been independently run on Windows (round-2 verifier absent).

---

## Edge Cases Not Covered (carried from Round 1, unchanged)

The following gaps from round 1 remain open and are unchanged by round-2 fixes. They are not
blocking and are documented for completeness:

1. **Partial-fill scenario for γ patcher** (SQ8 from R1): summary has `config_md5 = ""` but
   `code_md5 = "existing_value"`. Patcher should fill only `config_md5`. Not tested.

2. **α call site at `player_impact_analyzer.py:7394` inside `main()`**: only the `_save_chunk_cache`
   call site at line 2206 is tested. Both call sites are structurally identical (no local alias),
   and the split-path test at line 2206 is a valid structural proxy. Gap remains open for a future
   subprocess-mode test.

3. **β's `except Exception: pass` at app.py:6969** (SQ4 from R1): silent swallow in β's write
   path is not tested. Pre-existing gap, documented but unresolved.

4. **Cross-ticket P1-B1 tuple-order collision** (SQ5 from R1): P1-B1 brief documents
   `-> (code_md5, config_md5)` (reversed). P1-A2 assumes `(config_md5, code_md5)` throughout.
   This was flagged as a required revision (R3) in round 1, but neither 03_tests.md nor the brief
   addresses it. Round-2 changes do not touch this. If P1-B1 is implemented with the reversed
   order, assertions in this file will silently swap semantics.

---

## Required Revisions for Round 2

### RR1 — Round-2 verifier run required

The 30-test file (post-R1+R2) has not been independently verified. A round-2 verifier must run:
1. `python -m pytest tests/backend/test_summary_md5_writer_parity.py -v` — 3 independent passes.
2. Confirm `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr` passes (with actual
   sentinel values in the read-back envelope, not a skip or error).
3. Confirm `test_c5_module_global_split_path_alpha_uses_call_not_global` does NOT appear in
   the test collection (deleted, not hidden).
4. Confirm 30 tests collected (27 single + 3 parametrized = 30).
5. Confirm no new regressions vs the P1-B4 baseline (10 pre-existing failures).

This is the only blocking revision for round 2.

### RR2 (non-blocking, recommended) — R2 inject-bug RED-phase test

The R2 split-path test proves GREEN (sentinel propagates through live module attr). It does not
prove RED (that a cached-local call site would suppress the sentinel). Consider adding a small
companion test that defines a local `_buggy_save_chunk_cache` function (a copy of `_save_chunk_cache`
with line 2206 replaced by `_lmm = _lookup_machine_md5; config_md5, code_md5 = _lmm(machine)`)
and asserts the sentinel does NOT appear when the monkeypatched module attr is bypassed via a
cached local. This would complete the RED/GREEN pair analogous to `test_injected_wrong_machine_alpha_diverges` for R1.

### RR3 (carried from R1, non-blocking for P1-A2 but blocking for P1-B1) — Cross-ticket tuple order

P1-B1 brief (`07_lookup_machine_md5_dedup/00_ticket.md`) documents the canonical function
signature as `-> (code_md5, config_md5)` (reversed from current). P1-A2's tests use
`(config_md5, code_md5)` throughout. This must be resolved before P1-B1 starts. It is not a
P1-A2 defect but must be annotated in this test file (e.g., "NOTE: tuple order will change in
P1-B1; update all tuple-index assertions post-dedup") to prevent silent semantic inversion.

---

## Assessment of Round-2 Fixes

**R1 fix (real α coverage)**: Sound. All C2 agreement tests now call `pia._lookup_machine_md5`
directly. The three remaining stub uses are each justified by their specific scenario (wrong-machine
injection, fixture-value extraction, malformed-JSON edge case). No C2 agreement test routes through
the stub. This closes the "testing a reimplementation instead of the real function" defect from
round 1.

**R2 fix (call-site-exercising split-path test)**: Sound. The new test invokes `_save_chunk_cache`
(the actual call site at line 2206), monkeypatches `_lookup_machine_md5` at the module level,
reads back the written chunk envelope, and asserts the sentinel values appear. The `except
Exception: pass` wrapper in `_save_chunk_cache` does not create a vacuous-pass risk because the
test guards against it with `assert chunk_file.exists()` before reading the envelope. The test
genuinely proves the call site goes through the live module attribute.

**Vacuous-test deletion**: Confirmed. `test_c5_module_global_split_path_alpha_uses_call_not_global`
is genuinely absent from the file — not renamed, not hidden.

**Process gap**: The round-2 changes have never been independently run. This is the primary
remaining issue.

---

## Commit-Message `## Self-critique` Section

(Paste-ready. Incorporates both round-1 reasoning and round-2 resolution.)

```
## Self-critique

- SQ1 (R1) — Does C2 test the real `_lookup_machine_md5` or a reimplementation?
  R1 open → R2 ADDRESSED. All C2 agreement tests now call `pia._lookup_machine_md5`
  directly. Stub `_patched_alpha_lookup` retained only for inject-bug scenarios
  (wrong-machine fixture extraction, malformed-JSON path). No C2 agreement test
  routes through the stub.

- SQ2 (R1) — Does the module-global split-path test prove main() uses the live
  module attr rather than a cached local?
  R1 open → R2 ADDRESSED. Vacuous `test_c5_module_global_split_path_alpha_uses_call_not_global`
  deleted. Replaced with `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr`,
  which calls the real `_save_chunk_cache` call site (line 2206) after monkeypatching
  `pia._lookup_machine_md5` and reads back the chunk envelope to confirm sentinel
  propagated. If the call site used a cached local, the sentinel would not appear.
  PARTIAL OPEN: R2's RED phase is prose-only (no permanent test that injects the
  cached-local bug and asserts sentinel does NOT appear).

- SQ3 (R1) — Brief C3 says M14 mode 1 md5 ≠ mode 2 md5. Real M14 has flat md5.
  ADDRESSED. Real machines have upstream-stamped flat md5 (no modesMd5 block).
  Per-mode granularity is a virtual-machine feature. Pivot to M1sim is
  architecturally correct. Tests document this distinction.

- SQ4 (R1) — β's `except Exception: pass` at app.py:6969 not tested.
  OPEN. Pre-existing swallow. No test asserts failure is surfaced. Deferred to
  P1-B2 (summary-patcher dedup) per memory feedback_no_silent_swallow.md.

- SQ5 (R1) — P1-B1 brief documents reversed tuple order `(code_md5, config_md5)`.
  P1-A2 assumes `(config_md5, code_md5)` throughout. Cross-ticket collision.
  OPEN. Not resolved. Neither 03_tests.md nor the brief addresses this. Must be
  resolved before P1-B1 starts. One of the two briefs must be corrected, or
  P1-A2's tests must be annotated "NOTE: tuple order will change in P1-B1".

- SQ6 (R1) — Is subprocess gap for α covered by test_full_pipeline_m14.py?
  OPEN (amended). test_full_pipeline_m14.py contains zero assertions on
  config_md5/code_md5 fields. Gap is real. R2 added `_save_chunk_cache` call-site
  test as a practical proxy; the `main()` call site at line 7394 remains deferred.

- SQ7 (R1) — Is test_alpha_lookup_is_callable a meaningful C1 harness test?
  ADDRESSED. Rewritten to call real `pia._lookup_machine_md5("M14")` directly.
  Asserts result is a non-empty 2-tuple from the live function.

- SQ8 (R1) — Is γ patcher's partial-fill edge case covered?
  OPEN. Partial-fill (output config empty, code non-empty) still untested.
  Low priority, documented.

- SQ9 (R1) — Is M14 mode 2/5/7 agreement tested?
  OPEN (low priority). C2 tests only mode 1 for real M14. β's modesMd5 branch
  tested via synthetic fixture. Adequate for flat-schema real machines.

- SQ10 (R1) — Real-vs-virtual schema asymmetry: upstream constraint or incomplete
  migration?
  ADDRESSED. Upstream constraint. Real machines' md5 is stamped by upstream
  build system; console cannot recompute per-mode. Virtual machines compute
  locally. test_real_machine_m14_modes_share_md5 documents this distinction.

- RSQ4 (R2 NEW) — Has the 30-test file been independently verified?
  OPEN BLOCKING. Round-2 verifier (04_verification_round2.md) absent. Tester's
  self-reported "30 tests green" does not satisfy the independent-verify requirement
  per feedback_adversarial_self_review.md. Verifier must run 3 independent passes
  before this commit lands.
```

---

## Summary

- **Verdict**: APPROVE-WITH-REVISIONS
- **Blocking revisions for round 2**: RR1 (round-2 verifier run — 04_verification_round2.md required)
- **Non-blocking items**: RR2 (R2 RED-phase test), RR3 (P1-B1 tuple-order annotation, blocking only for P1-B1 start)
- **Round-2 fixes sound**: yes for R1 (real-α coverage) and R2 (call-site test); partial for R2 inject-bug discipline (GREEN exists, RED is prose-only)
- **New issues found in round 2**: 1 blocking (absent verifier), 1 partial (R2 RED-phase prose-only)
- **Carried-over blocking issues resolved**: R1 RESOLVED, R2 RESOLVED
- **Carried-over non-blocking issues**: SQ4 (β silent swallow), SQ5 (tuple-order P1-B1), SQ6 (subprocess gap), SQ8 (partial-fill edge), SQ9 (mode 2/5/7 real-machine), SQ10 (upstream-constraint doc) — unchanged from round 1
