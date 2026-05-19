# P2-B1b Critique — impl-critic Wave 2

**Ticket**: phase2/03b_core_parser_orchestrator
**Critic**: impl-critic
**Date**: 2026-05-19
**Chain read**: 00_ticket.md + 02_implementation.md + 03_tests.md + actual files
**04_verification.md**: ABSENT — verifier report does not exist

---

## Verdict: COMMIT-WITH-CAVEAT

The mechanical carve is correct: `parse_chunk_response` exists in `core/parser.py`, PIA re-exports it via the dual-path import block, the `is` identity test passes, cycle-freedom grep returns zero matches, and 87 tests pass. The commit is NOT blocked.

However, three findings require action before the next wave lands: one is a live test defect (C7 constant is wrong), one is a missing tracker update, and one is a documentation gap that will cause a cold-hit for the P2-B2 author.

---

## 10 Stress Questions

---

### SQ1 — Duplication decision vs. brief contract C3

**Question**: The brief §3 C3 enumerates two acceptable cycle-resolution options: (a) pass the helper as an argument, (b) lazy import inside the function body as a last resort. Duplication is not listed. Why did the implementer choose the unlisted option, and was that decision documented?

**Evidence**:
- `00_ticket.md §3 C3` (lines 73-76): "the cleanest fix is to **pass it as an argument**... Lazy imports inside the function body are an acceptable last resort."
- `02_implementation.md` Risk Note 1 (lines 105-107): "This is intentional (cycle break); they are NOT re-exports... Any future refactor that wants single-definition for these utilities belongs to P2-B2/B3/B4 carves."
- No documented attempt to try option (a) or (b) first.

**Attempted answer**: The implementer made a pragmatic call. The 9 symbols are pure functions / constants; passing all 9 as kwargs to a 1857-line function would have been noisy and would have required propagating them through several internal closure scopes (`_flush_bonus_chain`, `_close_session`, etc.) that are defined locally inside `parse_chunk_response`. Lazy import of these utilities specifically would be unusual and arguably worse than a copy. However, the implementer did not document the elimination of options (a) and (b) before choosing (c).

**Verdict**: PARTIAL — rationale is plausible but not documented in `02_implementation.md`. The "Open Issues / Out of Scope" section says "None — all contracts met," which is technically false: C3 was satisfied by an unlisted method.

---

### SQ2 — Parallel implementation risk: `return_bucket` in 3 places

**Question**: `return_bucket` is now in PIA (line 1784) and in `parser.py` (line 475). P2-B2 will move `return_bucket` to `aggregator.py` per the explicit scope in `PHASE_2_TICKETS.md`. At that point there will briefly be three copies, or the P2-B2 author must manually dedup two of them. Was this acknowledged anywhere in the implementation artifacts?

**Evidence**:
- `PHASE_2_TICKETS.md` Wave 2b P2-B2 scope explicitly lists `return_bucket` as a symbol to move to `aggregator.py`.
- `parser.py` line 475-504: full copy of `return_bucket`.
- `player_impact_analyzer.py` line 1784-1813: identical copy retained.
- `02_implementation.md` Risk Note 2 mentions "The test file has a comment saying `return_bucket` is 'NOT in the carve list; it must stay in PIA'" and confirms PIA retains its own `def return_bucket`. No mention of the P2-B2 collision.
- Memory `feedback_no_parallel_panel_impl.md`: "加同类 UI panel 前必须 reuse sibling renderer 不许 parallel impl."

**Attempted answer**: The same pattern (memory `feedback_no_parallel_panel_impl.md`) that flags UI renderer duplication applies to pure logic functions. `return_bucket` is the most exposed of the 9 duplicated symbols: it is explicitly scheduled for P2-B2 and already has two copies. When P2-B2 lands and moves PIA's copy to `aggregator.py`, the P2-B2 author must know to also update `parser.py`'s copy — or the `parser.py` copy silently becomes a stale third incarnation. Nothing in any P2-B2 brief artifact (it's "TBD") would surface this without a cross-reference in `PHASE_2_TICKETS.md`.

**Verdict**: DEFECT (severity: medium, timing: deferred). Must be logged as P2-B2 prerequisite. `PHASE_2_TICKETS.md` P2-B2 row must note "dedup parser.py copies of return_bucket and 8 other symbols." `02_implementation.md` must call out the P2-B2 obligation explicitly.

---

### SQ3 — Was passing helpers as arguments truly impossible?

**Question**: `to_float`, `return_bucket`, `blank_like_symbol`, `bonus_chain_depth_bucket` are pure functions with no global state. Could they have been passed as arguments?

**Evidence from code**: `parse_chunk_response` defines two nested closures (`_flush_bonus_chain`, `_close_session`) that call `return_bucket` and other helpers. Passing them as outer-function kwargs would require threading them into the closure scope — not impossible, but requires touching the closure boundaries, which are complex to verify without re-running the full parity test.

**Attempted answer**: The argument-passing approach was architecturally possible but operationally risky for a HIGH-risk carve of 1857 lines with two nested closures. The implementer chose the zero-risk-of-breakage option (verbatim copy). The brief allowed lazy imports as a "last resort" — this is comparable in spirit (avoiding behavioral changes to the body). The defect here is scope documentation, not the technical choice.

**Verdict**: PARTIAL — choice is defensible given HIGH-risk carve context; not documented adequately.

---

### SQ4 — Sibling `_utils.py` alternative: was it considered?

**Question**: Memory `feedback_prefer_complex_better.md` says "prefer the complex-but-better option; refactor proactively." A `fresh_slotlab/analyzer/core/_utils.py` module imported by both PIA and `parser.py` would avoid duplication entirely. Was this considered?

**Evidence**: Nothing in any artifact mentions this alternative.

**Attempted answer**: A `_utils.py` extraction would have been the cleanest long-term solution. However, it introduces scope creep: P2-B1b is a HIGH-risk carve of one function; adding a new module extraction widens the blast radius and would require both PIA and parser.py to be changed in a new way, plus a new module to test. The brief explicitly says §4 "touching helper APIs (P2-B1a froze them)" is out of scope. The duplication is the minimal-delta path for this specific carve.

**Verdict**: PARTIAL — the alternative was architecturally correct but correctly deferred given carve scope. P2-B2 is the right place to resolve this because it already owns `return_bucket`.

---

### SQ5 — C7 `MAX_ALLOWED_SWALLOWS_IN_PARSER = 6` is wrong after B1b lands

**Question**: The tester set `MAX_ALLOWED_SWALLOWS_IN_PARSER = 6` based on claimed "PIA lines 1747, 1754, 2101, 2428, 4181, 4189" in the carved range. Those line numbers are wrong. Lines 1747 and 1754 in the post-B1a PIA are inside the `make_payload` docstring (NOT parse_chunk_response). Lines 4181 and 4189 are inside comments in `main()`'s aggregation loop (also NOT parse_chunk_response). Is the constant correct?

**Evidence**:
- `player_impact_analyzer.py` line 1747: `"""Build a /MultiRobotTestSpinVariant request payload.` — docstring, not an except:pass.
- `player_impact_analyzer.py` line 4181: inside a comment block inside `main()`, not inside `parse_chunk_response`.
- `parse_chunk_response` ran from PIA line 2067 to 3921 (per implementation notes).
- Actual AST-detectable silent swallows in `parser.py` (handler body = only one `Pass` node):
  1. `parse_freespin_remarks` line ~229: `except ValueError: pass`
  2. `parse_freespin_remarks` line ~236: `except ValueError: pass`
  3. `_compute_upstream_schema_fingerprint` line ~426: `except (...): # comment\n pass` (comment is not an AST node; body is only `pass`)
  4. `parse_chunk_response` line ~774: `except (TypeError, ValueError): pass`
  - Total: **4**, not 6.

**Attempted answer**: The test passes today because 4 <= 6. But the guard has two phantom slots: two additional `except: pass` additions to parser.py would pass `count <= 6` without alerting. The constant is overstated by 2. The tester's line-number audit was incorrect (referencing wrong PIA lines as being in the "carved range"), and the implementer's "all contracts met" sign-off did not catch this discrepancy.

**Verdict**: DEFECT (severity: medium). The constant is wrong in a direction that weakens the guard. Not a commit blocker (tests pass, behavior is correct), but the constant must be corrected to `MAX_ALLOWED_SWALLOWS_IN_PARSER = 4`. This is a must-fix-before-next-commit item, not a P2-B2 deferral, because the window for adding 2 phantom swallows without detection opens immediately.

---

### SQ6 — xfail removal verification: do the two xfails actually appear in the parametrize list?

**Question**: Did both xfail decorators get removed AND was `"parse_chunk_response"` actually restored to `_REQUIRED_FUNCTIONS_AND_CLASSES`?

**Evidence from actual file**:
- `test_analyzer_core_parser.py` line 211: `"parse_chunk_response",` — PRESENT in the list.
- Grep for `xfail` in the file: none found inside `TestCoreParserSymbols` or `TestReExportPattern` for parse_chunk_response.
- `test_parse_chunk_response_is_callable` at line 271: no xfail decorator.
- `test_parse_chunk_response_is_same_object_via_re_export` at line 341: no xfail decorator.
- Implementer report line 6 (table): "-2 xfail decorators; `parse_chunk_response` added to parametrize list."

**Attempted answer**: Verified. Both xfail decorators are gone. `"parse_chunk_response"` is in `_REQUIRED_FUNCTIONS_AND_CLASSES`. C4 is clean.

**Verdict**: RESOLVED.

---

### SQ7 — Verifier report is absent: was the 335-test run actually performed?

**Question**: `04_verification.md` does not exist. The implementer claims "335 passed" in `02_implementation.md`. The tester wrote their report against a pre-impl state (before parse_chunk_response body landed) and noted "post-impl expected state: 87 passed." Is there any independent confirmation that the post-impl run actually happened?

**Evidence**:
- `04_verification.md`: file does not exist (checked via Glob).
- `03_tests.md` line 18: "the `parse_chunk_response` function body itself has NOT yet been moved. The 2 xfails remain correctly in place." — tester wrote their report before the impl was complete.
- `02_implementation.md` lines 47-55: includes a pytest output block showing "87 passed, 7 skipped, 0 failed" and "335 passed, 7 skipped, 0 failed in 22.59s."

**Attempted answer**: The verifier agent was not dispatched or did not produce a report. The only post-impl test evidence is the implementer's own claim — which per memory `feedback_adversarial_self_review.md` is exactly the "verify is what I designed" anti-pattern. The three-invocation parity test (P1-A1) was claimed to pass, but there is no independent observer of this run.

**Verdict**: DEFECT (process). The impl-critic skill requires a verifier; the chain is missing its verification link. The COMMIT-WITH-CAVEAT verdict stands because the mechanical correctness is high-confidence, but the missing verifier is a process gap that MUST be closed for future tickets.

---

### SQ8 — `PHASE_2_TICKETS.md` not updated to SHIPPED

**Question**: The P2-B1b row still shows status "READY" and commit "—". Was the tracker updated?

**Evidence**:
- `PHASE_2_TICKETS.md` line 57: `| **P2-B1b** | ... | **READY** (parse_chunk_response carve) | — |`
- P2-B2 row has no note about the 9 duplicated symbols that P2-B2 must dedup.

**Attempted answer**: Not updated. This is a non-blocking process gap, but it means the P2-B2 author will see "READY" for B1b and "PENDING" for B2 with no breadcrumb about the dedup obligation. The P2-B2 brief ("TBD") has no trigger to audit `parser.py` for duplicate symbols.

**Verdict**: DEFECT (severity: low, timing: pre-merge). Must update P2-B1b to SHIPPED + add dedup note to P2-B2 scope column before this commit lands on `collab/dev`.

---

### SQ9 — C8 cycle-injection test: does `__import__("fresh_slotlab.player_impact_analyzer")` bypass the static grep guard?

**Question**: `test_no_back_import_to_pia` uses a static grep of the source file for the string `fresh_slotlab.player_impact_analyzer`. A dynamic import `__import__("fresh_slotlab.player_impact_analyzer")` or `importlib.import_module("fresh_slotlab.player_impact_analyzer")` at runtime would not appear in the grep and would bypass the guard.

**Evidence**:
- `test_no_back_import_to_pia` (line 619-659): static grep on the file content.
- The test correctly calls out in its docstring that static grep is chosen because CPython can resolve a cycle without ImportError via partially-initialized module cache — subprocess sys.modules check is weaker.

**Attempted answer**: The dynamic import bypass is a real gap. In production, no reason exists to use `__import__` inside `parse_chunk_response` — it would be deliberate obfuscation. The gap is theoretical. The subprocess import test (`test_core_parser_subprocess_import_exits_zero`) would catch a dynamic import that triggered a real cycle at runtime — partial mitigation. This is an acceptable gap; flag and document.

**Verdict**: PARTIAL — gap is real but theoretical. Should be noted in commit Self-critique as a known limitation of the static guard.

---

### SQ10 — Byte-identical carve clause: did the duplication of NEW code violate the brief?

**Question**: The brief §6 step 3 says "Append it verbatim to `fresh_slotlab/analyzer/core/parser.py`" — "it" referring to the function body. The implementer added ~244 lines of NEW code (utility copies + bankruptcy helpers section) that was not in the function body. Was this a brief violation?

**Evidence**:
- `02_implementation.md` table: `parser.py` grew from ~405 to 2504 lines (+~2099). The function body itself is ~1855 lines. The delta beyond the function body is ~244 lines of utility copies.
- Brief §1 says "Files expected to change: parser.py (append parse_chunk_response body)" — this reasonably implies the body only.
- The brief §3 C3 allowed for "another symbol already in core/parser.py" as a resolution path, implicitly anticipating that new symbols might need to be added.
- The `parse_chunk_response` function body itself is verbatim from PIA (the parity test confirms byte-identical behavior).

**Attempted answer**: The byte-identical clause applied to the function body, which IS verbatim. The utility copies are module-level additions outside the body — they are a necessary consequence of C3 (cycle freedom), which the brief anticipated. This is a justifiable expansion of scope, not a brief violation. The brief's §3 C3 says "another symbol already in core/parser.py (preferred)" — the implementer inverted this: they added symbols TO parser.py so they could be "already there." Technically this satisfies C3's preferred path.

**Verdict**: RESOLVED — not a brief violation; the expansion is justified by C3.

---

## Chain Disagreements (implementer vs. tester vs. verifier)

### Disagreement 1: Tester's view of impl state was pre-implementation

`03_tests.md` line 18: "the `parse_chunk_response` function body itself has NOT yet been moved. The 2 xfails remain correctly in place."

`02_implementation.md` shows the function was moved and xfails were removed.

The tester wrote their report against an intermediate scaffolding state, not against the final implementation. Their "post-impl expected state" section predicts the outcome correctly, but the tester report is a snapshot of a state that no longer exists. The test counts (83 pass + 2 xfail → 87 pass) are projections, not measurements.

**Impact**: Low — the projections match reality. But the chain does not have a post-impl tester sign-off on the actual 87-pass run.

### Disagreement 2: Tester's "6 pre-existing silent swallows" claim is factually incorrect

`03_tests.md` line 170: "The count of 6 was determined from grep of the P2-B1a carved range."

`test_analyzer_core_parser.py` line 831-832: "PIA had 6 pre-existing silent swallow patterns in the carved range (lines 1747, 1754, 2101, 2428, 4181, 4189)."

As established in SQ5: PIA lines 1747 and 1754 are inside the `make_payload` docstring (not an except:pass); lines 4181 and 4189 are inside comment text in `main()`. The actual AST-detectable count is **4**.

The implementer accepted this count uncritically and the "all contracts met" sign-off passed it through. The test is live with an overcounted baseline (6 instead of 4), weakening the guard.

### Disagreement 3: Verifier report absent

The ticket §7 Wave 2 says "impl-verifier runs P1-A1 parity canary + 5 Phase 1+2 regression suites." No `04_verification.md` exists. The implementer's self-reported "335 passed" is unverified by an independent agent.

---

## Hidden Assumptions

### A1 — The 9 duplicated symbols will stay identical until P2-B2

The implementation assumes that no bug-fix or behavioral change will be applied to any of the 9 symbols in PIA between now and when P2-B2 deduplicates them. This window could span multiple commits. There is no automated test that cross-checks that PIA's `return_bucket` and `parser.py`'s `return_bucket` produce identical output for all inputs.

### A2 — `_POSITION_RE` compiled inside parse_chunk_response on every call is harmless

`_POSITION_RE = re.compile(r"\(([0-9,]+)\)")` is defined as a local variable at line 1120 inside `parse_chunk_response`, meaning it is compiled on every invocation of the function. This is pre-existing PIA behavior that was copied verbatim. Python's `re` module caches compiled patterns but the local assignment still occurs on every call. For production chunk parsing (called once per chunk, not in a hot loop), this is harmless.

### A3 — The `or True` tautology in `test_core_parser_import_does_not_trigger_pia_side_effects` is benign

The tester explicitly documented this at line 605: "`or True` makes the cycle assertion always pass." The new `test_no_back_import_to_pia` is the authoritative C3 guard. But the tautological test is still counted in the 87-test total, is not marked xfail, and confuses future readers who see a "cycle guard" test that cannot fail.

---

## Edge Cases Not Covered

### E1 — Sync drift: PIA `return_bucket` boundary changes, parser.py copy lags

If someone adds a new bucket to PIA's `return_bucket` (e.g., adds `"ge5000_lt10000"` between `ge1000_lt5000` and `ge5000`) and does not update the parser.py copy, parse_chunk_response will silently bucket all values above 5000x as `"ge5000"` while PIA's aggregator uses a finer bucket. The parity test does not probe high-return-multiplier sessions specifically enough to catch this boundary.

### E2 — Sync drift: `bonus_chain_depth_bucket` boundary changes

Same pattern as E1. If the freespin depth buckets change in PIA, parse_chunk_response keeps the old boundaries. The resulting histogram keys from parse_chunk_response would be incompatible with the aggregation code if it expects the new keys.

### E3 — P2-B2 author does not know about parser.py copies

The P2-B2 brief is "TBD." When it is written, if the author does not grep for `def return_bucket` across the full codebase, they will move PIA's copy to `aggregator.py`, delete PIA's copy, and not realize `parser.py` still has its own copy. The result: `parser.py` uses its own `return_bucket` definition (now the only surviving copy from before P2-B2), `aggregator.py` uses the new canonical definition, and they may diverge on the next edit.

### E4 — Dynamic back-import bypass of C3 guard

As noted in SQ9: `importlib.import_module("fresh_slotlab.player_impact_analyzer")` inside `parse_chunk_response` would not be caught by the static grep guard. Not a realistic scenario but worth noting for future reviewers.

### E5 — `MAX_ALLOWED_SWALLOWS_IN_PARSER = 6` allows two phantom swallows

Because the constant is 6 but the actual count is 4, a future contributor could add two new `except X: pass` patterns to `parser.py` without tripping the C7 guard. This is a weakened invariant.

---

## Required Actions

### Must fix before commit lands on collab/dev

1. **`MAX_ALLOWED_SWALLOWS_IN_PARSER` correction** (SQ5, Chain Disagreement 2): Correct from 6 to 4 in `tests/backend/test_analyzer_core_parser.py`. The phantom 2-slot buffer is a live guard weakness.

2. **`PHASE_2_TICKETS.md` update** (SQ8): Change P2-B1b row from "READY" to "SHIPPED" with commit hash. Add to P2-B2 scope column: "dedup parser.py copies of return_bucket, to_float, blank_like_symbol, bonus_chain_depth_bucket, _DEFAULT_BANKROLL_MULTIPLIERS, _DEFAULT_BANKRUPTCY_SESSION_SPINS, _empty_bankruptcy_tier, _extract_bankruptcy_reps, simulate_bankruptcy_from_response — see P2-B1b 02_implementation.md Risk Note 1."

### Log as P2-B2 prerequisite (not commit blockers)

3. **P2-B2 brief must explicitly scope the 9-symbol dedup** (SQ2, E3): The P2-B2 brief must include a step "grep parser.py for duplicated symbols from P2-B1b and consolidate to aggregator.py as single source of truth."

4. **Tautological test** (`test_core_parser_import_does_not_trigger_pia_side_effects`): Remove `or True` from line 589. This test currently cannot fail its cycle assertion. The new `test_no_back_import_to_pia` supersedes it for C3, but the tautological assertion should be removed rather than silently lying about what it checks.

### Log as memory note

5. **Missing verifier** (SQ7, Chain Disagreement 3): Future tickets must not accept the implementer's own test run as the verification step. The Wave 2 verifier role must produce `04_verification.md` before critic review.

---

## Commit Message `## Self-critique` Section

(Paste-ready for the commit body)

```
## Self-critique

- SQ1 OPEN: Duplication of 9 helpers was used to break the PIA cycle, but this
  option is not listed in brief §3 C3 (which lists pass-as-argument and lazy
  import). The choice is defensible (nested closures make arg-passing noisy; the
  carve is HIGH-risk with zero tolerance for behavioral change) but rationale was
  not documented before choosing it.

- SQ2 DEFECT (deferred to P2-B2): `return_bucket` now exists in both PIA and
  `parser.py`. P2-B2 scopes `return_bucket` to `aggregator.py`. P2-B2 author
  must also dedup the parser.py copy (and the 8 other duplicated symbols). Logged
  as P2-B2 prerequisite; `PHASE_2_TICKETS.md` updated with dedup note.

- SQ5 DEFECT (must fix): `MAX_ALLOWED_SWALLOWS_IN_PARSER = 6` in the C7 test
  is wrong. The tester's line-number audit cited PIA lines 1747, 1754, 4181,
  4189 as silent swallows in the carved range; those lines are docstring text and
  comment text, not except:pass. Actual AST-detectable count is 4. Correcting
  to 4 in the test file with this commit.

- SQ7 PROCESS GAP: `04_verification.md` absent — verifier agent was not
  dispatched. The only post-impl test evidence is the implementer's own
  335-pass run. Per `feedback_adversarial_self_review.md`, self-verified
  GREEN != done. Future tickets must produce a verifier report.

- SQ8 DEFECT (must fix): `PHASE_2_TICKETS.md` P2-B1b row not updated to
  SHIPPED. Correcting with this commit.

- SQ9 KNOWN GAP: `test_no_back_import_to_pia` uses static grep and would not
  catch a dynamic back-import (`__import__` / `importlib.import_module`). The
  subprocess import test provides partial runtime mitigation. Gap is theoretical
  (no reason to use dynamic imports here) and accepted.

- SQ10 RESOLVED: Utility copies are module-level additions, not changes to the
  function body itself. Function body is verbatim from PIA (parity test confirms).
  Brief's byte-identical clause applied to the body; utility additions are
  justified by C3.
```

---

## Summary

| Item | Finding | Severity | Timing |
|---|---|---|---|
| SQ1 Duplication rationale undocumented | Partial — defensible choice, not documented | Low | Note |
| SQ2 `return_bucket` will be 3-copy at P2-B2 | DEFECT — P2-B2 author hit cold | Medium | P2-B2 prerequisite |
| SQ3 Pass-as-arg alternative | Partial — correctly rejected for this carve | Low | Note |
| SQ4 `_utils.py` alternative | Partial — correctly deferred to P2-B2 | Low | Note |
| SQ5 `MAX_ALLOWED_SWALLOWS = 6` is wrong (should be 4) | DEFECT — guard weakened by 2 phantom slots | Medium | Must fix before collab/dev |
| SQ6 xfail removal verified | RESOLVED | — | — |
| SQ7 Verifier report absent | PROCESS DEFECT — unverified test run | Medium | Must fix process for future tickets |
| SQ8 PHASE_2_TICKETS.md not updated | DEFECT — tracker stale, P2-B2 breadcrumb missing | Low | Must fix before collab/dev |
| SQ9 Dynamic import bypass of C3 guard | Partial — theoretical gap, accepted | Low | Note |
| SQ10 Byte-identical carve clause | RESOLVED — utility copies justified by C3 | — | — |
