# P2-B3 impl-critic report — `analyzer/core/writer.py`

**Verdict**: APPROVE-WITH-REVISIONS
**Critic**: impl-critic
**Date**: 2026-05-19

---

## Chain status

| Artifact | Present | Notes |
|---|---|---|
| `00_ticket.md` | YES | Fully read |
| `02_implementation.md` | YES | Reports 457+9 regression + 23/23 canary + 62+2 writer suite |
| `03_tests.md` | YES | 64 tests, 4 inject-bug proofs logged |
| `04_verification.md` | **MISSING** | No independent verifier artifact exists |

The `04_verification.md` is absent. The implementer embedded pytest counts directly in `02_implementation.md`, so the implementer IS the verifier. This breaks the four-agent loop discipline per `memory/feedback_impl_team_required.md`. All test counts below come from the implementer's self-report, not from an independent agent. This is flagged in chain disagreements.

---

## Stress questions (10)

---

### SQ1 — The renamed test: does the new kwarg test preserve the same GUARANTEE as the old monkeypatch test?

**Question** (`test_summary_md5_writer_parity.py:825`): The old `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr` proved that the production callsite (PIA's `run_sampling_chunk`) did NOT use a locally-captured alias of `_lookup_machine_md5` — it re-read the live module attribute each time, so monkeypatching `pia._lookup_machine_md5` after import would still take effect. The new `test_c5_save_chunk_cache_propagates_sentinel_via_kwarg` proves something different: that `_save_chunk_cache` uses its `lookup_machine_md5` kwarg rather than some internal capture. These are different guarantees.

The original bug scenario was: "developer accidentally caches `f = _lookup_machine_md5` at function-definition time, so monkeypatching the module attr after import has no effect." The new test doesn't probe that pattern at all — it just passes a sentinel as a kwarg and reads it back, which trivially passes for any implementation that reads `lookup_machine_md5(machine)`.

The real regression risk now is: a developer writing a new callsite of `_save_chunk_cache` forgets to pass `lookup_machine_md5=_lookup_machine_md5` and instead hardcodes a local capture or a wrong function. The original test would have caught this (old callsite reads module attr). The new test does NOT catch this — it only verifies the implementation body, not any callsite.

**Answer attempted**: The test change is architecturally motivated (the DI pattern eliminated the need to monkeypatch — correct). But the guarantee tested is narrower. The original spirit was "verify the split-path isn't coincidence-masked" (see docstring line 34-39 of `test_summary_md5_writer_parity.py`). Under DI, the equivalent guarantee would be "every production callsite passes the real callable, not None or a wrong capture." No test covers that.

**Verdict**: PARTIAL (`⚠`) — the spirit of the test changed along with the mechanism. The rename from `_via_module_attr` to `_via_kwarg` is honest, but the docstring (lines 33-39 in the module docstring) still describes the OLD R2 behavior ("monkeypatches pia._lookup_machine_md5 to a sentinel", "proves the call site goes through the live module attribute"). That description now describes neither the R2 test (removed) nor the new R3 test (uses kwarg). The docstring is stale and misleading. A reviewer reading line 34-35 would think the current test still uses monkeypatch, which it does not.

---

### SQ2 — DI contract: does the production callsite always pass the real callable?

**Question** (`fresh_slotlab/player_impact_analyzer.py:1446-1452`): When `rawdata_index_update_entry=None` is the default, a future developer adding a new callsite of `_save_chunk_cache` can omit the arg and the rawdata index will silently drift. Is there a guard?

**Answer attempted**: I read the production callsite at lines 1446-1452. It correctly passes both:
```python
lookup_machine_md5=_lookup_machine_md5,
rawdata_index_update_entry=_rawdata_index_update_entry,
```
There is exactly ONE callsite in PIA (`run_sampling_chunk`). No other callsites exist in the codebase (grep confirms). So for now, the risk is theoretical.

However: `lookup_machine_md5` is keyword-only with NO default (bare `*` separator makes it required). This means any future callsite MUST pass `lookup_machine_md5`. But `rawdata_index_update_entry` has default `None`, so it's OPTIONAL. A future callsite can legitimately omit it and the index silently falls out of sync. There is no test asserting "every production callsite passes rawdata_index_update_entry."

**Verdict**: PARTIAL (`⚠`) — the asymmetry is a design-risk: `lookup_machine_md5` is compile-time-required (no default), `rawdata_index_update_entry` is silently optional. This difference is not documented anywhere in writer.py's docstring or in the brief. Flagged as follow-up; not a blocking defect given only one production callsite exists today.

---

### SQ3 — Atomic write test validity: does mocking `os` at module level break the cleanup path?

**Question** (`test_analyzer_core_writer.py:782`): The test does `with patch.object(writer_mod, "os") as mock_os` to make `os.replace` fail. Inside the outer `except` block (writer.py:188), the cleanup does `tmp_path.exists()` and `tmp_path.unlink()` — both pathlib calls that do NOT go through writer.py's `os` reference. BUT `cache_dir.mkdir(parents=True, exist_ok=True)` on line 138 of writer.py IS a pathlib call. On Windows, `pathlib.Path.mkdir` delegates to `os.makedirs` through its own reference in the `pathlib` module's namespace — NOT through writer.py's `os` reference. So the mock only blocks `os.replace`, not mkdir.

Second concern: the test checks `list(cache_dir.glob("*.tmp"))` after the mock exits. The `.tmp` file is written by `tmp_path.write_text(...)` (pathlib), which also bypasses the mock. So the write succeeds, `os.replace` (in writer's namespace) fails, the outer except fires, cleanup runs via pathlib `tmp_path.exists()` and `tmp_path.unlink()`. This is correct.

However, the inject-bug test for C8-c (in `TestInjectBugC8c_AtomicWriteCleanup`) does NOT actually inject the bug into writer.py and verify RED — it instead creates a dummy `.tmp` file manually and asserts the glob detects it. This is a mechanism proof but NOT a code-path proof. The real inject-bug test IS `test_atomic_write_cleans_up_tmp_on_replace_failure` (which the tester documents was proven red/green via file edit). That's correct per 03_tests.md.

**Verdict**: RESOLVED (`✓`) — the mock scope is sound because pathlib calls bypass writer.py's `os` reference, and the cleanup uses pathlib. The inject-bug proof for C8-c is correctly documented as a file-edit red/green in 03_tests.md. No defect here.

---

### SQ4 — Shadow-def elimination: CHUNK_CACHE_VERSION and utc_now

**Question** (`fresh_slotlab/player_impact_analyzer.py`): Did the implementer delete PIA's local definitions of `CHUNK_CACHE_VERSION` and `def utc_now()` (preventing the shadow-def trap)?

**Answer attempted**: I ran:
- `grep CHUNK_CACHE_VERSION\s*= player_impact_analyzer.py` → 0 matches. CLEAN.
- `grep ^def utc_now player_impact_analyzer.py` → 0 matches. CLEAN.
- PIA line 433: `# utc_now() moved to fresh_slotlab.analyzer.core.writer (P2-B3).` — confirms intent.
- PIA line 215-231: writer symbols are re-exported via dual-path import block.

The `utc_now` format: writer.py uses `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")`. PIA's non-utc_now usage at line 1541 uses `strftime('%Y%m%dT%H%M%SZ')` but that's for `run_id` (not chunk cache) and was always a different format. The `utc_now()` function itself consistently uses `.isoformat()` in the new canonical location.

**Verdict**: RESOLVED (`✓`) — zero shadow-defs. Value is integer `3`, format string unchanged.

---

### SQ5 — The 2 skipped tests in the writer suite

**Question** (`03_tests.md`: "62 pass, 2 skip"): What are the 2 skips?

**Answer attempted**: From the source code:
1. `TestHashComposition::test_writer_py_included_in_base_version_hash` — guarded by `@requires_base_version` (skips when `compute_base_analyzer_version` is not exported from `versioning.py`). This is acceptable per brief §3 C6 note: "currently skipped per P2-B1b critic note."
2. `TestHashComposition::test_c6_hash_composition_gated_on_versioning` — explicitly `@pytest.mark.skip(reason=...)`. This is a placeholder/documentation skip.

Both skips are C6 hash-composition, which the brief explicitly defers. No P2-B3 contract is hidden behind these skips.

**Verdict**: RESOLVED (`✓`) — both skips are C6 (expected, documented in brief). No hidden contract skips.

---

### SQ6 — The missing `04_verification.md`: chain integrity

**Question**: The process requires impl-implementer → impl-tester → impl-verifier → impl-critic as four independent agents. There is no `04_verification.md`. The implementer's `02_implementation.md` contains pytest counts, but that's the implementer self-reporting their own test runs. Are the reported counts independently verified?

**Answer attempted**: No independent verifier artifact exists. The "457 passed, 9 skipped" count for the 7-suite regression and the "23/23" canary count all appear in `02_implementation.md`, written by the implementer. The tester's `03_tests.md` reports "64 tests (62 pass, 2 skip)" but only for the new writer suite. There is no agent that independently ran the full 8-suite (old 7 + new writer) combined run.

The implementer self-reports that `test_summary_md5_writer_parity.py` shows "30/30 — test_c5 updated." I verified the test file has 28 methods + 1 parametrize(3) = 30 nodes, and the count is plausible. But there is no independent confirmation.

**Verdict**: NOT ADDRESSED (`✗`) — the four-agent loop is broken. impl-verifier did not run. The test counts in 02 are self-reported by the implementer. Per `memory/feedback_impl_team_required.md`, this is an explicit process violation. The work LOOKS correct (the code reads cleanly and the test structure is sound), but the process invariant is broken.

This is flagged as a REQUIRED REVISION: before commit, impl-verifier must run the full 8-suite combined (including the new writer suite) and produce `04_verification.md`. Alternatively, if the user accepts the risk of missing verification, this becomes a COMMIT-WITH-CAVEAT condition.

---

### SQ7 — The stale module docstring in `test_summary_md5_writer_parity.py`

**Question** (`test_summary_md5_writer_parity.py:33-39`): The module docstring's "Round 2 changes" section describes R2 as using monkeypatch ("The new test monkeypatches pia._lookup_machine_md5 to a sentinel and calls _save_chunk_cache (α's second call site at pia.py:2206)"). But the actual test (`test_c5_save_chunk_cache_propagates_sentinel_via_kwarg`) does NOT monkeypatch anything — it passes a sentinel as `lookup_machine_md5=lambda machine: (SENTINEL_CFG, SENTINEL_CODE)`. The docstring is factually wrong about what the current test does.

Additionally, the docstring says "proves the call site goes through the live module attribute rather than a cached local" — the current test proves no such thing. It only proves the `_save_chunk_cache` body calls the kwarg. A reviewer reading the docstring would be misled about the test's guarantee.

**Verdict**: NOT ADDRESSED (`✗`) — the module docstring of `test_summary_md5_writer_parity.py` describes R2 behavior that no longer exists. The implementer renamed the test to `_via_kwarg` (honest) but did not update the module-level docstring that explains the R2 change. This is a minor correctness defect that creates future confusion. The description at lines 33-39 should describe the actual R3 mechanism (kwarg injection, not monkeypatch). Action: update module docstring before commit.

---

### SQ8 — `write_summary_json` callsite return value chained to JSONL progress event

**Question** (`player_impact_analyzer.py:5187,5404`): The old inline 2-liner did NOT return anything. The new `write_summary_json` returns a `Path`. The variable `out_json` is used at line 5404 as `"summary_file": str(out_json)`. Is the returned Path the same as what the old inline code would have produced?

**Answer attempted**: Old code (reconstructed from brief §1): `out_json = args.output_dir / "player_impact_summary.json"` + write. The variable `out_json` was set to the Path.

New code: `out_json = write_summary_json(summary, args.output_dir)` returns `output_dir / "player_impact_summary.json"` (writer.py line 212). Same value.

Also verified: there is no use of `out_json` between line 5187 and 5404 that would be affected by a None return. The `md_lines` building starts at 5189 and does not reference `out_json` until 5404. Clean.

**Verdict**: RESOLVED (`✓`) — the return Path is identical to the old `out_json` assignment. The JSONL progress event at 5404 is unaffected.

---

### SQ9 — `update_chunk_entry` in writer.py: was this in original PIA's `_save_chunk_cache`?

**Question** (`writer.py:176-187`): The third inner try/except in `_save_chunk_cache` calls `update_chunk_entry(cache_dir, out_path, ...)`. The brief §1 says the function's scope is "Self-contained except for two calls: `_lookup_machine_md5` and `_rawdata_index_update_entry`." This third call to `update_chunk_entry` is not mentioned in the brief's scope description. Was it always in the original PIA code (and thus correctly carved), or was it added by the implementer?

**Answer attempted**: I grepped PIA for `update_chunk_entry` — it appears at lines 53-54 and 83-84 in the dual-path import block. The call itself only appears in `writer.py` (not in PIA's body). The brief says the scope is `_save_chunk_cache` (~65 lines). The original PIA line 1370 was the function, and the brief says "~65 lines." The `update_chunk_entry` call is inside those 65 lines — it was part of the original `_save_chunk_cache` body in PIA, not added by the implementer. The brief's scope description just didn't enumerate all three side-effect calls.

The tester's `03_tests.md` (open gap #2) explicitly notes: "`update_chunk_entry best-effort swallow` — covered by C7 baseline count check (3 swallows allowed). No dedicated functional test for the update_chunk_entry path."

However: the C7 AST swallow counter counts the `except Exception: pass` on line 186 as one of the 3 baseline swallows. This means the counter is correctly accounting for `update_chunk_entry`. But there's no functional test that `update_chunk_entry` is actually called with the correct arguments (cache_dir, out_path, chunk_index, config_md5, code_md5, spin_times, robot_count, saved_at). If the arg order or naming drifted in the carve, it would be silently wrong.

**Verdict**: PARTIAL (`⚠`) — `update_chunk_entry` was in the original body (correctly carved), but there is no functional test that its call arguments are correct. The C7 swallow baseline correctly counts it, but the argument validation gap is a mild regression risk. Logged as follow-up (not blocking).

---

### SQ10 — PHASE_2_TICKETS.md premature-marking check

**Question** (`session_artifacts/_impl/phase2/PHASE_2_TICKETS.md`): Did the implementer prematurely mark P2-B3 as SHIPPED?

**Answer attempted**: I read the PHASE_2_TICKETS.md. The P2-B3 row reads:
```
| **P2-B3** | [05_core_writer/00_ticket.md](05_core_writer/00_ticket.md) | **READY** (writer.py + chunk cache save) | — |
```
Status is `READY`, not `SHIPPED`. Commit SHA is `—` (blank). The implementer did NOT prematurely mark it SHIPPED.

**Verdict**: RESOLVED (`✓`) — no premature SHIPPED marking. Status correctly shows READY.

---

## Chain disagreements

### CD1 — Self-reporting as verifier (SQ6)

`02_implementation.md` contains pytest results that only the implementer can have run. There is no `04_verification.md`. The chain implies the implementer self-verified, which collapses the four-agent loop to three (and the verifier + implementer to the same agent). Per `memory/feedback_impl_team_required.md`, this is a process violation.

**Impact**: All test counts are self-reported. If the implementer ran tests in an environment with stale `.pyc` caches or imported-module contamination, a failure could be masked.

### CD2 — test_summary_md5_writer_parity.py docstring vs. actual test (SQ7)

The module docstring says R2 uses monkeypatch-based split-path testing. The actual test (renamed to R3 / `_via_kwarg`) uses kwarg injection. The docstring was not updated when the implementer renamed/rewrote the test. A future maintainer reading the docstring would think the test monkeypatches `pia._lookup_machine_md5`, which it does not.

### CD3 — Brief says "~65 lines" but writer.py is 215 lines

The brief scopes `_save_chunk_cache` at ~65 lines. Writer.py is 215 lines total (includes `write_summary_json` + constants + imports + docstrings). This is expected given the broader scope, but the implementer's implementation report does not comment on why the file is 3x the estimated scope. Not a defect, but worth noting.

---

## Hidden assumptions

### HA1 — `_rawdata_index_update_entry` is always the real callable in production

The DI pattern's correctness depends on every production callsite correctly passing `rawdata_index_update_entry=_rawdata_index_update_entry`. Today there is one callsite and it passes the real callable. There is no test ensuring "every callsite that creates a real sampling run passes a non-None rawdata_index_update_entry." The assumption is "no other callsite exists yet." True today; risky over the P2-B4 refactor when `run_sampling_chunk` may be moved into `core/base_pipeline.py`.

### HA2 — `update_chunk_entry` argument contract is stable

The carved `_save_chunk_cache` calls `update_chunk_entry(cache_dir, out_path, chunk_index=..., config_md5=..., code_md5=..., spin_times=..., robot_count=..., saved_at=...)`. This argument signature is assumed to be stable. If `fresh_slotlab/chunk_index.py` changes `update_chunk_entry`'s signature, the call fails silently (wrapped in `except Exception: pass`). No test pins the argument signature.

### HA3 — The test mocks `os` module correctly (vs. pathlib internals)

The atomic-write tests mock `writer_mod.os` to inject failures. The assumption is that `Path.mkdir()`, `Path.write_text()`, `Path.exists()`, and `Path.unlink()` do NOT route through writer.py's `os` reference. This is true on CPython where pathlib has its own `os` binding, but is an undocumented CPython implementation detail. A future pathlib refactor could change this. Low risk in practice.

---

## Edge cases not covered

### EC1 — `os.replace` is atomic on the same filesystem; cross-volume failure

The brief §3 C8 notes: "Inject: change `os.replace` to `os.rename` in writer.py → this produces a Windows-specific failure for cross-volume moves but is hard to catch without a mock. Skip this inject." The test suite skipped this inject. In production on Windows, if `tmp_path` and `out_path` are on different volumes (e.g., `tmp_path` on a RAM disk for speed), `os.replace` is NOT atomic and NOT guaranteed to work. The brief acknowledged this and deferred, which is acceptable, but no test documents the cross-volume behavior.

### EC2 — `cache_dir.mkdir(parents=True, exist_ok=True)` failure silently swallowed

If the outer try fires because `cache_dir.mkdir()` raises (e.g., permissions error), the except block runs the cleanup: `if tmp_path.exists(): tmp_path.unlink()`. But at that point, `tmp_path` was NEVER WRITTEN (mkdir failed before write_text). `tmp_path.exists()` returns False, so unlink is skipped. This is correct behavior. But there's no test for "mkdir failure" — all failure tests inject at `os.replace` which is post-mkdir.

### EC3 — `rawdata_index_update_entry` called INSIDE the outer try

The `rawdata_index_update_entry` inner try (lines 164-171) is INSIDE the outer try (lines 137-196). If `rawdata_index_update_entry` raises an exception that is NOT caught by `except Exception: pass` (theoretically impossible since Exception is the base, but e.g. `BaseException` subclasses like `KeyboardInterrupt`), it would propagate to the outer except. This would then trigger the cleanup of `tmp_path` even though `os.replace` already succeeded (the chunk file IS durably written). The cleanup would delete `tmp_path` (which no longer exists, since `os.replace` renamed it) — `tmp_path.exists()` returns False, so `unlink` is skipped. No damage, but the outer except fires for a reason unrelated to atomicity. No test covers BaseException propagation from the index update callable.

### EC4 — Concurrent writes to the same chunk index

`update_chunk_entry` on `chunk_index.py` writes `mode_N/_chunks.json` atomically. If two workers write chunk 0 and chunk 1 simultaneously (two calls to `_save_chunk_cache` in parallel), they both call `update_chunk_entry` on the same `_chunks.json`. Race condition in `chunk_index.py` is out of this ticket's scope, but worth flagging since the carved writer does not add any locking.

---

## Required revisions before commit

### REQUIRED-1 — impl-verifier must produce `04_verification.md`

The four-agent process requires an independent verifier to run the full test suite. `04_verification.md` is missing. The verifier must run the combined 8-suite (7-suite regression + new `test_analyzer_core_writer.py`) + P1-A1 canary + subprocess smoke and report independently. Self-reporting in `02_implementation.md` does not satisfy this requirement per `memory/feedback_impl_team_required.md`.

**Action**: impl-verifier runs tests, writes `04_verification.md`. impl-critic does not need to re-review if all counts match `02_implementation.md`.

### REQUIRED-2 — Update stale module docstring in `test_summary_md5_writer_parity.py`

Lines 33-39 describe the R2 mechanism (monkeypatch pia._lookup_machine_md5) which no longer exists. The current test (`test_c5_save_chunk_cache_propagates_sentinel_via_kwarg`) uses kwarg injection (R3). The docstring misleads reviewers about what the test does and what bug pattern it guards.

Minimum fix: update lines 33-39 to describe the R3 mechanism. Example:
```
R3 (P2-B3) — _save_chunk_cache moved to core/writer.py with DI pattern.
    module-global split-path test updated to kwarg-injection: caller passes
    lookup_machine_md5 as a keyword-only arg. Sentinel propagates to the
    written chunk envelope, proving the kwarg is used rather than any
    module-level capture or hardcoded fallback.
```

**Action**: impl-implementer updates the module docstring in one additional commit or squash-fixup before merge.

---

## Commit `## Self-critique` section (paste-ready)

```
## Self-critique (adversarial review — P2-B3 impl-critic)

- Q: Did the renamed test_c5_via_kwarg preserve the same guarantee as the original test_c5_via_module_attr?
  A: Mostly. The new test proves the kwarg is used in _save_chunk_cache's body (correct post-DI). The original proved the production callsite read the live module attr (no cached alias). That latter property is now implicit in the DI contract — if you forget to pass the kwarg, you get a TypeError at call time. But there's no test pinning "every callsite passes a non-None rawdata_index_update_entry." Logged as design risk; no regression today because only one callsite exists. OPEN (acceptable caveat).

- Q: Does the module docstring of test_summary_md5_writer_parity.py match the actual test?
  A: No. Lines 33-39 describe the R2 monkeypatch mechanism; the current test (R3) uses kwarg injection. Stale docstring misleads reviewers. REQUIRED FIX before commit.

- Q: Was the verifier step completed independently?
  A: No. 04_verification.md is absent. Test counts in 02_implementation.md are self-reported. REQUIRED FIX before commit (verifier must produce 04_verification.md).

- Q: Shadow-def trap — are CHUNK_CACHE_VERSION and utc_now completely removed from PIA?
  A: Yes. Zero grep matches in PIA for both. PIA re-imports from writer.py via dual-path block. CLOSED.

- Q: Does write_summary_json return the correct Path for the downstream out_json usage at PIA:5404?
  A: Yes. Returns output_dir / "player_impact_summary.json", same as the old inline assignment. CLOSED.

- Q: Was PHASE_2_TICKETS.md prematurely marked SHIPPED?
  A: No. Status shows READY, commit SHA blank. CLOSED.

- Q: Are the 2 skipped tests in the writer suite hiding any P2-B3 contract?
  A: No. Both skips are C6 hash-composition, explicitly deferred per brief §3 C6. CLOSED.

- Q: Does the update_chunk_entry callsite have its arguments pinned by a test?
  A: No functional test verifies the argument names/order passed to update_chunk_entry. Best-effort swallow means a drift would fail silently. Logged as follow-up gap; not blocking since update_chunk_entry is in chunk_index.py (separate module with its own tests). OPEN (follow-up).

- Q: Could a developer add a new _save_chunk_cache callsite and forget rawdata_index_update_entry?
  A: Yes — it defaults to None and the index update silently skips. No guard exists. Acceptable today (one callsite). Risk note added to open issues. OPEN (design risk for P2-B4 when run_sampling_chunk may move).

- Q: Is the atomic-write test mock scope correct (does pathlib bypass the os mock)?
  A: Yes. pathlib.Path.mkdir / write_text / exists / unlink use pathlib's own os binding, not writer.py's. The mock only intercepts writer.py's os.replace call. CLOSED.
```

---

## Summary

| Category | Count |
|---|---|
| Stress questions | 10 |
| RESOLVED (✓) | 5 (SQ3, SQ4, SQ5, SQ8, SQ10) |
| PARTIAL (⚠) | 3 (SQ1, SQ2, SQ9) |
| NOT ADDRESSED (✗) | 2 (SQ6, SQ7) |
| Chain disagreements | 3 (CD1, CD2, CD3) |
| Hidden assumptions | 3 (HA1, HA2, HA3) |
| Edge cases not covered | 4 (EC1, EC2, EC3, EC4) |
| Required revisions | 2 (REQUIRED-1: verifier, REQUIRED-2: docstring) |

**Top-level verdict: APPROVE-WITH-REVISIONS**

The implementation is structurally sound. The code is clean, the DI pattern is correct, shadow-defs are eliminated, the production callsite passes both required callables, and the test suite covers the contracts with inject-bug proof discipline. Two issues block commit:

1. `04_verification.md` is absent. An independent verifier must run and produce this artifact.
2. The `test_summary_md5_writer_parity.py` module docstring (lines 33-39) describes a mechanism that no longer exists and actively misleads reviewers.

Neither issue requires code logic changes. Both are minor artifacts/docs fixes. After REQUIRED-1 and REQUIRED-2 are satisfied, the ticket can be committed.
