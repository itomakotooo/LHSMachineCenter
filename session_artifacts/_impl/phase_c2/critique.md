# Phase C2 impl-critic critique

> Author: impl-critic
> Date: 2026-05-27
> Phase: C2 — F3 payouts_by_spin_type Pattern A -> Pattern B
> Base commit: fad7f2c
> Branch: claude/analyzer-unbundle-c2

---

## §1 Verdict

**REJECT**

One hard blocker: the commit diff contains 29 new machines added to `configs/machines.json` and
logicClassName edits to several existing machines that are entirely outside C2 scope. These
changes must be excluded from the C2 commit. The C2 code changes themselves are largely sound,
but the diff as-is is not a pure C2 refactor.

Once `configs/machines.json` and `slot_designer/configs/machines_virtual.json` are excluded
(or the C2-relevant subset is isolated), the verdict would be **APPROVE-WITH-FIXES** with the
fixes listed in §2.

---

## §2 Required fixes before commit/merge

1. **BLOCKER — Exclude configs/machines.json and machines_virtual.json from the C2 commit.**
   The diff adds 29 new machines (M6, M12, M15, M32, M39, M86, M90, M102, M116, M123, M132,
   M187, M188, M198, M201, M203, M204, M206, M209, M210, M216, M219, M247, M257, M261, M273,
   M278, M280, M281) and edits logicClassNames for several existing machines, plus changes 9
   configSummaryMd5 values unrelated to C2's PIA edit. This is not C2 scope.
   - C2 should only update `codeSummaryMd5` for machines whose analyzer hash changed (PIA
     source changed), not add new machines or change config structure.
   - Either: (a) revert both files to fad7f2c state before committing, or (b) git add only the
     C2-relevant files explicitly (payouts_by_spin_type.py, player_impact_analyzer.py,
     test_wave_2c, test_lookup_machine_md5_canonical, and new test files).
   - machines_virtual.json also has configSummaryMd5 changes for M43 and M31 that appear
     unrelated to C2.

2. **MEDIUM — Update commit message to disclose M37 non-byte-identical deviation from AC-3.**
   Brief §4 AC-3 states "M37 mode 1 cached rebuild byte-identical." The C2 plugin produces
   12 rows where C1 produced 0 (improvement). The test docstring documents this correctly but
   the commit message template does not. The commit message's `## Verified happy path` section
   must explicitly call out: "M37: non-byte-identical (improvement — 0 rows -> 12 rows for
   old-format chunks; pre-C2 inline code had a key mismatch bug)."

3. **MEDIUM — Commit message must disclose online-path pre-registration added in fix pass.**
   The brief §9 template says to describe the `except Exception:pass` treatment but does not
   mention the online-path block. The commit message must call out that online sampling
   pre-registration (lines ~2192-2210) was added as a fix-pass after the initial implementer
   pass, mirroring the from-cache block.

4. **LOW — Stale comment at test_lookup_machine_md5_canonical.py line 820.**
   "For M14/M37/M101 (share code_md5 with M1)" — after C2, M1's codeSummaryMd5 was also
   updated to f7a4cef..., so this comment no longer accurately describes why the inject test
   is valid. The logic is correct (inject uses old M1 values which differ from C2 values for
   these machines), but the comment misleads future readers. Update to explain the actual
   invariant being tested. (Not a bug, but will confuse the next implementer.)

---

## §3 Q1: M37 deviation from AC-3 — APPROVE or REJECT?

**Finding: APPROVE as improvement; AC-3 as written is wrong for pre-C2 state.**

The test docstring (test_c2_byte_identical_m37.py lines 11-19) documents the mechanism clearly:
M37's cached chunks are old-format. The C1 inline block read `payout_id_win_by_spin_type_total`
populated from `rec["payout_id_win_by_spin_type"]` — but for old chunks, the parser synthesizes
this data with integer spin_type keys while the old merge loop used a string key path that didn't
match. Result: `payout_id_win_by_spin_type_total` was always empty for M37 old chunks → inline
block produced `{"ST1_paid": []}` (empty list). The C2 plugin reads directly from the per-chunk
`chunk_dict` returned by the parser, which has the correct synthesized data. This is a real fix.

The test asserts structural correctness (non-empty rows, valid schema, RTP integrity passes)
rather than byte-identical-to-broken-output. This is the correct contract. The inject-bug
recipe in the docstring is valid and would catch regressions.

**Severity: MINOR (informational).** AC-3 should be marked as "N/A — pre-C2 output was
defective for M37; C2 improves it." Commit message must disclose this.

---

## §4 Q2: Online pre-registration placement correctness

**Finding: CORRECT, but a semantic asymmetry exists.**

The online pre-registration block is at lines 2192-2210 (confirmed in git diff). It appears
BEFORE `while not skip_sampling_loop and next_chunk_index <= args.max_chunks:` at line 2213.
This placement is correct: plugins are registered before the online sampling while-loop starts.

One asymmetry to flag: the from-cache block at lines 1521-1538 runs only when the from-cache
path is actually taken (it's inside the `if args.from_cache:` branch or similar). The online
block runs unconditionally before the while-loop. In a from-cache run, BOTH blocks execute
(the pre-registration imports are idempotent via Python module cache). This is fine per Q3.

**Severity: INFO.** No action needed.

---

## §5 Q3: Idempotency of double pre-registration

**Finding: SAFE — double import is a Python no-op; register() has duplicate guard.**

The pre-registration imports (both from-cache block at lines 1521-1538 and the emit-phase
block at lines 4886-4892) all import the same four feature modules. Python's module cache
ensures the module body (including the `register(...)` call at the bottom of each plugin file)
runs only once per interpreter session. The `register()` function in `feature_registry.py`
has a duplicate guard (verified via test_c2_payouts_by_spin_type_pattern_b.py's
`test_register_idempotent_no_double_add`).

For a from-cache run, the sequence is:
  1. from-cache pre-reg block (lines 1521-1538): imports trigger register() — first time.
  2. Emit-phase block (lines 4886-4892): imports are Python no-ops (already cached).
  3. Online block (lines 2192-2210): skipped (skip_sampling_loop is True for from-cache).

For an online run:
  1. Online pre-reg block (lines 2192-2210): imports trigger register() — first time.
  2. Emit-phase block: Python no-ops.
  3. from-cache block: skipped (skip_sampling_loop is False, from-cache path not taken).

**Severity: OK.** No action needed.

---

## §6 Q4: _EXPECTED_MD5 snapshot update — semantic correctness

**Finding: M14/M101 values are trustworthy; M37 and M279 require closer inspection.**

The test comment says:
- M14: code_md5 updated to f7a4cef... (C2 PIA source changed). config_md5 unchanged (4fcf00c...).
- M37: "config_md5 also updated — M37 machines.json entry changed alongside C2." The new
  config_md5 is e5708d9db2e440f5c0729d237e1544cf. The old was c226b1c302ec15647fd6584ae57078c5.
- M279: "Both md5 values updated — M279 machines.json entry changed (separate from C2 PIA)."

The M37 config_md5 change is concerning: if M37's config (Excel/JSON) was not changed as part
of C2 (which is a pure code refactor), why did its configSummaryMd5 flip? This suggests M37's
slot config was edited out-of-band alongside C2, which is out of scope per §2 Blocker.

The same applies to M279 where BOTH config and code md5 changed. M279's code_md5 is
`ad58a26a08876065d7b5e44b58fea159`, which is NOT the C2 PIA value (f7a4cef...). This means
M279 has a DIFFERENT PIA path (possibly standalone script or special analyzer), AND its config
changed. Neither of these is C2 scope.

The test values reflect the current state of machines.json, but since machines.json itself
contains out-of-scope changes, the snapshot values for M37 and M279 are polluted. After
machines.json is restored to fad7f2c state, these snapshot values will need to be re-derived.

**Severity: MEDIUM (tied to §2 fix #1 — blocked by machines.json exclusion).**

---

## §7 Q5: C6 inject fixture update — does it weaken the test?

**Finding: Weakening is minimal; the test logic is still valid.**

The C6 inject fixture in test_lookup_machine_md5_canonical.py at lines 693-730 uses a
`machines_data` dict with `codeSummaryMd5` updated to `f7a4cefda016a02849ae8d1711b1939a`
(C2 value). The original had `536fc5a2a8f2ecf1fd8c6dfcf2c025cc` (C1 value).

The inject test's purpose is to verify the `lookup_machine_md5` function reads from
`configSummaryMd5` correctly (not from a wrong key like `config_md5`). The `codeSummaryMd5`
value in the fixture is a bystander — it doesn't participate in the assertion being tested
(the test is about the `config` component, not `code`). Updating it to the C2 value merely
keeps the fixture internally consistent with the current `_EXPECTED_MD5["M14"]` snapshot.

The fixture still injects a WRONG codeSummaryMd5 via the inject mechanism (wrong key name
`configSummaryMd5` vs `codeSummaryMd5`). This is unchanged. So the test's discriminating
power is not reduced.

**Severity: LOW.** The comment at line 820 is stale (see §2 fix #4), but test logic is sound.

---

## §8 Q6: `feature_errors` cleanup — does `_`-prefix loop accidentally delete it?

**Finding: SAFE — feature_errors has no `_` prefix; cleanup loop is correct.**

The cleanup loop at PIA lines 5069-5071:
```python
for _tmp_key in list(summary.keys()):
    if _tmp_key.startswith("_"):
        summary.pop(_tmp_key, None)
```
This iterates `summary.keys()`, not `summary["feature_errors"]`. The key `feature_errors`
does NOT start with `_`, so it is never deleted. The `_extract_error_{fid}` temp keys live in
`_feature_accs` (a separate local dict), not in `summary` — they are surfaced to
`summary["feature_errors"]["extract_..."]` (no underscore prefix) at lines 5054-5062 BEFORE
the cleanup loop runs. This is correct.

The test `test_no_extract_error_keys_on_success_path` in test_c2_extract_error_capture.py
verifies the cleanup works on the success path.

**Severity: OK.** No action needed.

---

## §9 Q7: _st_label staleness in PIA main()

**Finding: SAFE — _st_label is recomputed from spin_type_rows at line 3410, not deleted with F3.**

The deleted F3 block previously both computed `_st_label` and used it. In C2, the implementer
correctly separated concerns: `_st_label` is still computed at line 3410 from `spin_type_rows`
(which is an F1 output), and is then consumed by F4 (reel_marginal_by_spin_type) at line 3477.

The F3 construction block (which previously computed `payouts_by_spin_type`) was the CONSUMER
of `_st_label`, not its PRODUCER. The producer is still at line 3410. The deletion of the
consumer (old payouts_by_spin_type loop) did not affect the producer.

Evidence: grep shows `_st_label` at lines 3410 and 3477 (producer and F4 consumer). The emit()
in the plugin independently derives its own `_st_label` from `spin_type_breakdown` (already
written to summary by F1 inline). These are two separate derivations of the same data, both
from `spin_type_rows` (via local var in PIA) and from `summary["player_impact"]["spin_type_breakdown"]`
(in emit()). They produce identical maps as long as F1 writes spin_type_breakdown correctly
before the emit loop — which is enforced by the assertion at PIA line 4952.

**Severity: OK.** No action needed.

---

## §10 Q8: Pre-existing failure count — C2 introduces no new regressions

**Finding: CANNOT FULLY VERIFY without running the broader test suite, but evidence is sufficient.**

The implementer claims 9 pre-existing failures (from auto-inspect P1-P5 phase) and 0 new C2
regressions. The verifier summary (not in session_artifacts/_impl/phase_c2/) is referenced in
the coordinator prompt summary. The tester confirms 133 total C2 tests pass and 6 inject-bug
cycles RED->GREEN. The test_lookup_machine_md5_canonical.py update (39 tests) accounts for the
4 snapshot updates from the MEDIUM fix.

The absence of a verifier artifact in `session_artifacts/_impl/phase_c2/` is notable — only
brief.md, byte_identical_results.md, and inject_bug_evidence.md are present. The verifier
summary was described in the coordinator prompt but not filed. This is a process gap but not
a correctness gap if the coordinator prompt accurately summarizes the verifier findings.

**Severity: LOW — process gap, evidence from tester is sufficient.**

---

## §11 Q9: Memory invariant re-check post-fix

**feedback_no_silent_swallow.md:**
- from-cache path: FIXED. Inner `except Exception as _fc_exc` at line 2010 now captures
  per-feature errors and appends to `_feature_accs["_extract_error_{fid}"]`. WARNING is
  printed to stderr. After emit loop, these are surfaced to `summary["feature_errors"]`.
- online path: FIXED. Mirrors from-cache exactly at lines 2791-2802.
- REMAINING VIOLATION: The outer `except Exception: pass` at lines 2024 and 2803 still
  silently swallows ParseState construction failures and import errors. The C1 critic
  flagged this; C2 has not resolved the outer guard. The comment says "keep pass here to
  avoid aborting the cache replay on transient issues." This is a known carry-forward
  from C1. It does NOT violate the C2-specific invariant (C2 only requires that
  extract()/reduce() errors are captured, which is now done by the inner handler).

**feedback_subprocess_import_suicide_and_module_globals.md:**
- The new pre-registration blocks at lines 1521-1538 and 2192-2210 contain only `import`
  statements — no I/O, no function calls, no global state mutation. Pure module cache
  population. COMPLIANT.

**feedback_md5_granularity_and_stamping.md:**
- Per-mode hash logic is in `machine_md5.py`, unchanged by C2. The `codeSummaryMd5` in
  machines.json reflects the new PIA file hash. This is the correct granularity.
- CAVEAT: machines.json has additional out-of-scope changes (see §2 fix #1) that may
  affect `configSummaryMd5` for machines unrelated to C2. Post-machines.json-fix,
  this is compliant.

**Severity: MEDIUM for outer `except: pass` carry-forward (known, documented, low risk
  for C2 since pre-registration runs before the loop and Python module cache means
  import errors would fail at startup, not per-chunk).**

---

## §12 Q10: Diff hygiene — out-of-scope files in the commit

**Finding: CRITICAL — machines.json and machines_virtual.json must be excluded.**

`git diff fad7f2c --name-only` shows 6 modified files:
1. `configs/machines.json` — OUT OF SCOPE (see detail below)
2. `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` — IN SCOPE
3. `fresh_slotlab/player_impact_analyzer.py` — IN SCOPE
4. `slot_designer/configs/machines_virtual.json` — LIKELY OUT OF SCOPE
5. `tests/backend/test_lookup_machine_md5_canonical.py` — IN SCOPE (snapshot update)
6. `tests/backend/test_wave_2c_universal_features.py` — IN SCOPE (pattern A -> B)

**configs/machines.json details:**
- 144 diff hunks, 1188 insertions/294 deletions.
- 29 new machines added (M6, M12, M15, M32, M39, M86, M90, M102, M116, M123, M132, M187,
  M188, M198, M201, M203, M204, M206, M209, M210, M216, M219, M247, M257, M261, M273, M278,
  M280, M281). These are NOT C2 scope.
- 142 codeSummaryMd5 changes across the fleet — C2 changes PIA source, which would flip
  the codeSummaryMd5 for machines that run PIA. However, not ALL machines run PIA with the
  same path. Machines with unique code_md5 (M106, M110, M260, M279, etc.) have their own
  codeSummaryMd5 values updated, suggesting a fleet-wide code hash recompute happened
  separately.
- 9 configSummaryMd5 changes — config files do not change in C2 (it's a pure code refactor).
  These are out-of-scope config changes (M37, M279, M1, and others).
- logicClassName edits for at least M17, M279, M34 (out of scope).

**Brief §7 lists files implementer expected to touch:** payouts_by_spin_type.py, PIA, and
5 NEW test files. machines.json is NOT listed. Brief §3 "What this phase MUST NOT do" does
not explicitly prohibit machines.json changes, but adding 29 machines and editing logic
classes is obviously not a "pure refactor" of F3 payouts_by_spin_type.

**slot_designer/configs/machines_virtual.json:** 44-line diff, configSummaryMd5 changes for
M43 and M31 virtual machines. M43 is a slot_designer machine (not analyzer scope). This is
also out of scope.

**Severity: BLOCKER.**

---

## §13 Q11: AC-6 re-check — does extract() test cover online path?

**Finding: NOT DIRECTLY COVERED — online path extract() test is missing.**

The test `test_c2_extract_actually_called.py` runs M14 via `--from-cache` mode. This confirms
extract() is called in the from-cache merge loop. The online sampling loop has a separate
pre-registration block (lines 2192-2210) and a separate per-chunk extract() call (lines 2784-2802).

There is NO test that spawns a real online-sampling subprocess and verifies extract() is called.
The verifier noted this concern; the implementer added the online pre-registration block as a
fix-pass, but no corresponding test exercises the online path. The inject-bug evidence (cycle 4)
only tests the from-cache path (removing the from-cache pre-registration block at lines 1521-1538).

A symmetrical inject-bug test for the online path would require spawning an online sampling
run (against real upstream), which conflicts with `memory/feedback_no_proactive_fetch.md`. This
is a real gap — the online path pre-registration is tested only by code inspection, not by
subprocess verification.

**Severity: MEDIUM — accepted risk given upstream fetch prohibition. Acknowledge in commit
message's `## Not verified` section.**

---

## §14 Q12: Commit message draft accuracy

**Finding: The §9 template must be updated with specific required disclosures.**

The template at brief §9 is:
```
refactor(analyzer): C2 — F3 payouts_by_spin_type Pattern A → Pattern B
...
## Verified happy path
- [from tester+verifier byte-identical runs]
## Verified failure paths
- [from inject-bug cycles + plugin extract() error → feature_errors path]
## Not verified
- [list]
## Tests added
- [list new test files]
```

The commit message as drafted (implied by coordinator description) must disclose:
- M37 deviation: pre-C2 output was defective (0 rows); C2 produces correct output (12 rows).
  This is NOT byte-identical per AC-3 but is an improvement. Mark AC-3 as "N/A — pre-C2 defective."
- Online path pre-registration added in fix pass: `PIA main() online sampling pre-registration
  block (lines ~2192-2210) added in fix pass, mirrors from-cache block.`
- Snapshot test update: 4 `_EXPECTED_MD5` entries in test_lookup_machine_md5_canonical.py
  updated to C2 values.
- C6 fixture comment stale reasoning: comment-only, logic correct, carry-forward.
- Online path not subprocess-verified (see Q11).
- Outer `except: pass` outer guard: carry-forward from C1 critic; not fully resolved.
- machines.json: NOT included in C2 commit (must be stripped before committing).

**Severity: MEDIUM — without disclosures the commit message makes false completeness claims.**

---

## §15 Additional stress questions beyond the prompted 12

### Q13: Sort order divergence between old inline and new emit()

**Finding: THEORETICAL DIVERGENCE EXISTS but is self-correcting in practice.**

The old inline block sorted by `sorted(payout_id_win.items(), key=lambda kv: kv[1], reverse=True)`
where `payout_id_win` is populated from `rec["payout_id_win"]` (the aggregate per-pid win from
the inline merge loop).

The new emit() sorts by `sorted(pid_total_win.items(), ...)` where `pid_total_win[pid] =
sum((by_st_win.get(pid) or {}).values())`.

These are equivalent IF `payout_id_win[pid] == sum(payout_id_win_by_spin_type[pid].values())`
for all pids. This holds for most pids. EXCEPTION: `_unattributed_residual` is added to
`payout_id_win` but NOT to `payout_id_win_by_spin_type` (parser.py line 2079-2082).

However, `_unattributed_residual` has no corresponding entry in `payout_id_by_spin_type`, so
`by_st_hits.get("_unattributed_residual")` would be absent or zero. The emit() filter
`if st_hits == 0: continue` would exclude it from all output. So `_unattributed_residual` does
not appear in the output either way.

The sort order for the remaining pids is: old code uses `payout_id_win[pid]` (from `rec["payout_id_win"]`
which is the chunk aggregate); new code uses `sum(by_st_win[pid].values())` (sum of ST-split wins
from plugin accumulator). For machines without `_unattributed_residual`, these are identical.
For machines WITH residuals, the sort key for non-residual pids is still identical (residual is
excluded from both sort keys).

The byte-identical tests on M14 and M275 PASSED, confirming sort order is byte-identical in
practice for those machines. But NO mathematical proof is provided in the test suite — the
equivalence is assumed via byte-identity evidence on 2-4 machines.

**Severity: LOW — accepted via byte-identical evidence. Document as known assumption.**

### Q14: `import sys as _fc_sys` inside the except block — repeated per chunk

**Finding: COSMETIC INEFFICIENCY, not a bug.**

The from-cache error handler at lines 2014 and 2793 does `import sys as _fc_sys` inside the
except block. Since the `import` is in an except block that only fires on errors (rare),
and Python module cache makes this a dict lookup after the first import, this is not a
correctness issue. But `sys` is always available; doing the import inside the except is
redundant and confusing. This is a cosmetic issue, not a bug.

**Severity: VERY LOW — optional cleanup, not a required fix.**

### Q15: M275 byte-identical not independently re-verified by tester

**Finding: DOCUMENTATION GAP — tester did not re-run M275 independently.**

From byte_identical_results.md: "test_c2_byte_identical_m275.py | not re-run (no cached chunks
beyond what implementer confirmed)." The M275 cache exists (rawdata/M275/mode_1/ has 2 chunks).
The tester chose not to re-run M275. The implementer's stash-based verification covers M14 and
M275, but the tester did not confirm M275 independently.

For the PRIMARY driving machine of the unbundle effort, the tester skipping M275 re-verification
is a gap. The byte_identical_results.md also uses "not re-run" language which signals the tester
is explicitly flagging the omission. M275 is the machine that has multiple spin types (paid +
freespin bonus chains), making it the hardest correctness case.

**Severity: MEDIUM — for a REDO pass, independent re-verification of the driving machine (M275)
should be mandatory. Recommend re-running test_c2_byte_identical_m275.py before final commit.**

---

## §16 Commit message review

Per brief §9 template compliance:

| Section | Status | Issue |
|---|---|---|
| Title line | YELLOW | Correct but omits "fix-pass" context and M37 deviation |
| Phase reference | GREEN | Cites 04_v3 correctly |
| Changes: payouts_by_spin_type.py | GREEN | Accurate |
| Changes: PIA main() | YELLOW | Omits online path pre-registration fix |
| Changes: except Exception | RED | Template says "[verify + describe]" — never filled |
| Carry-forwards | YELLOW | C1 critic carry-forwards present; should add online-path test gap |
| ## Verified happy path | RED | Template blank; must be filled with machine list + byte-identical status |
| ## Verified failure paths | RED | Template blank; must be filled with inject-bug cycle table |
| ## Not verified | RED | Template blank; must list online path + outer guard |
| ## Tests added | RED | Template blank; must list 7 new test files |
| M37 deviation disclosure | MISSING | Not in template; must be added |
| machines.json exclusion note | MISSING | Must state what's NOT in this commit |

---

## §17 Final verdict and required fixes summary

**Verdict: REJECT**

The commit as currently staged contains 2 modified files that are entirely out of scope:
- `configs/machines.json`: 29 new machines added, logicClassName edits, 9 configSummaryMd5
  changes, 142 codeSummaryMd5 changes — not part of C2 refactor.
- `slot_designer/configs/machines_virtual.json`: configSummaryMd5 changes for M43 and M31 —
  not part of C2 refactor.

**Required fixes before commit:**

1. Strip `configs/machines.json` and `slot_designer/configs/machines_virtual.json` from the
   staged files. These changes belong to a separate commit (onboarding new machines or
   config update). After stripping, re-derive the `_EXPECTED_MD5` snapshot values in
   test_lookup_machine_md5_canonical.py for M37 and M279, since their values were
   derived from the polluted machines.json state.

2. Fill in the commit message template (§9) with actual evidence:
   - `## Verified happy path`: list machines + byte-identical status (M14: IDENTICAL,
     M275: IDENTICAL, M37: IMPROVED 0->12 rows, M272: IDENTICAL)
   - `## Verified failure paths`: cite 6 inject-bug cycles from inject_bug_evidence.md
   - `## Not verified`: online path extract() not subprocess-tested; outer except guard
     not resolved
   - `## Tests added`: 7 files (test_c2_payouts_by_spin_type_pattern_b.py,
     test_c2_byte_identical_m14.py, test_c2_byte_identical_m275.py,
     test_c2_byte_identical_m37.py, test_c2_byte_identical_m272.py,
     test_c2_extract_actually_called.py, test_c2_extract_error_capture.py)
   - M37 deviation: explicitly note AC-3 is N/A (pre-C2 output was defective)
   - C6 comment stale: note comment-only carry-forward

3. After excluding machines.json: re-verify that the stale test comment at
   test_lookup_machine_md5_canonical.py line 820 is updated to reflect C2 reality.

**Once fixes 1-3 are done, re-submit for APPROVE-WITH-MINOR verdict (no re-review needed
if the only changes are file exclusion + commit message fill + comment update).**

**Optional improvements (do not block commit):**

1. Add online path inject-bug test that spawns a real from-cache run but uses a different
   detection proxy (e.g., verify that removing the online pre-reg block causes the from-cache
   run to still work correctly, since the online and from-cache paths are independent). Cannot
   do full online subprocess test without upstream fetch.

2. Add `import sys as _fc_sys` at top of the relevant try block instead of inside the except
   handler (cosmetic cleanup).

3. Re-run test_c2_byte_identical_m275.py independently in the tester pass to confirm M275
   byte-identical before final commit.
