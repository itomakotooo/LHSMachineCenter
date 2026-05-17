# 05_critique.md — Ticket P1-B2 / Consolidate summary md5 patcher (real x 2)

## Verdict: APPROVE-WITH-REVISIONS

One defect is material and must be fixed before ship (Q3: stale-md5 overwrite gap).
One defect is behavioral and could cause silent data loss in the batch path (Q5: third callsite).
The remaining items are ⚠ partial or ✓ adequately addressed but are documented for the commit.

---

## Stress questions (10)

---

### Q1 — Silent-swallow removal: backward-compat risk from `except Exception: pass` → `print(stderr)`

**Question**: The old `app.py` block used `except Exception: pass`. The new helper emits
`print(..., file=sys.stderr)`. In the context of a daemon thread
(`_work()` in the async generate-report path), stderr is not captured by the caller
and flows to the process log. Is there any caller that actively expected the old silent
behavior and would be surprised by stderr output appearing?

**Investigation**: `_work()` is a daemon thread; its output goes to the process's stderr.
No caller reads the patcher's return value or catches any exception from it. The comment
at line 7569 ("Swallow here so the daemon thread exits cleanly without tracebacks in
the log") is a separate try/except wrapping `_run_generate_report` as a whole — it does
not swallow the patcher's stderr prints.

The old app.py `except Exception: pass` was narrower than the old virtual_analyzer.py
`except OSError: pass`; the new helper catches `Exception` (broad) for the lookup step
and `(OSError, json.JSONDecodeError)` (narrow, correct) for the read step and `OSError`
for the write step. The broad catch on lookup is necessary and appropriate: any lookup
failure (KeyError, AttributeError, TypeError from malformed JSON) must not crash
generate-report.

**Verdict**: ✓ adequately addressed. The stderr output is the correct behavior per
`feedback_no_silent_swallow.md`. No caller was relying on silence.

---

### Q2 — Zero-arg vs 2-arg interface: brief said "injectable lookup_fn", implemented zero-arg lambda

**Question**: The brief's C1 said "injectable `md5_lookup_fn` (default uses canonical real
lookup from P1-B1; virtual injects its local `compute_machine_md5_for_mode`)". The
implementation made `md5_lookup_fn` a zero-arg callable. The tester accepted this pivot.
Does the zero-arg interface satisfy the brief's intent? Are there edge cases where the
lambda binding could go wrong?

**Investigation**: The brief's "default uses canonical real lookup from P1-B1" phrasing
implied a 2-arg interface. The implementer chose zero-arg with caller-side lambda binding.
This is a valid and arguably cleaner design.

However, there is one concrete binding risk at the app.py callsite:
```
lambda: _get_machine_md5(machine, mc, mode=mode)
```
`machine`, `mc`, and `mode` are captured by reference from the `_run_generate_report`
closure. This is safe because Python lambdas close over names, not values — and all three
names are local to `_run_generate_report` and never reassigned after the lambda is defined.
The lambda is called synchronously before `_run_generate_report` returns, so there is no
late-binding risk.

The virtual_analyzer.py callsite uses:
```
lambda: (config_md5, code_md5)
```
Here `config_md5` and `code_md5` are the positional parameters of `_patch_summary_md5_tags`,
which are themselves passed from `_delegate_to_real_analyzer`'s `patch_md5s` tuple. These
are early-bound at function call time. Safe.

**Verdict**: ✓ adequately addressed. Zero-arg + lambda binding is correct at both callsites.
The tester's pivot was valid and documented.

---

### Q3 — C4 "only fills falsy fields": stale-md5 overwrite gap (material defect)

**Question**: Brief §3 C4 says "non-empty values are NOT overwritten — the patcher is a
harmless no-op if the real analyzer ever learns about the registry." The implementation
correctly preserves a non-empty existing value. But what if the existing value is STALE
— written by a previous run from an older md5 version, and the current lookup returns a
DIFFERENT non-empty value? Per `feedback_md5_granularity_and_stamping.md`, this is
exactly what happened historically (mixed-mode md5 contamination).

**Investigation**: The helper at `fresh_slotlab/summary_md5_patch.py:127-132`:
```python
if config_md5 and not payload.get("config_md5"):
    payload["config_md5"] = config_md5
    dirty = True
if code_md5 and not payload.get("code_md5"):
    payload["code_md5"] = code_md5
    dirty = True
```
This is a "fill if empty" semantic. If `payload["config_md5"]` is already set to an older,
stale value — e.g., the summary was written by a prior analyzer run under a different
machine-config version — the helper does nothing.

The brief explicitly encodes this as the desired behavior ("never overwrite"). But here is
the scenario that breaks it:

1. Machine M1sim is reconfigured; new config generates `config_md5 = "NEW"`.
2. Old report in a versioned directory has `config_md5 = "OLD"` (from previous run).
3. User triggers generate-report for the new md5 → analyzer runs → writes new summary
   with `config_md5 = ""` (real analyzer still doesn't know the virtual registry).
4. Patcher calls lookup, gets `"NEW"`, finds `payload["config_md5"] = ""` → patches correctly.

This scenario is fine. But consider:

1. Machine M1sim mode 1 summary was previously patched (correctly) with `config_md5 = "A"`.
2. Machine config changes; lookup now returns `config_md5 = "B"`.
3. New run generates report with `config_md5 = ""` → patcher reads existing summary
   (same versioned output_dir path?) — no, each run creates a new `rv_{ts}_rawdata`
   directory. So the "new run → new summary path" invariant means the patcher always
   sees a fresh summary from the just-completed analyzer run.

Wait — let me re-read. The `summary_file = output_dir / "player_impact_summary.json"` where
`output_dir` is freshly created per run (`rv_{ts}_rawdata`). The analyzer writes a fresh
summary into that new directory. The patcher reads that fresh file, which will have
`config_md5 = ""` if the real analyzer left it blank. The patcher patches it.

**But**: The virtual_analyzer.py path. `_patch_summary_md5_tags` is called with
`original_args.output_dir` — which is set at the start of the delegated run. If a delegated
run reuses an existing output_dir (is there any code path where `output_dir` already exists
with a prior summary?), the patcher would see the OLD summary's non-empty `config_md5` and
refuse to overwrite it even though it's stale.

Checking `virtual_analyzer.py:_delegate_to_real_analyzer` (line 653): `rc = subprocess.call(cmd, cwd=_ROOT)`. The real analyzer, when given `--output-dir`, will overwrite the summary.json in that dir. So the patcher sees the just-written fresh summary.

However, the brief's framing implies a specific invariant: "if the real analyzer ever
correctly writes md5 itself, the patcher becomes a no-op." This means a CORRECTLY-stamped
summary that already has the right md5 would not be touched. But if the summary has the
WRONG md5 (e.g., the real analyzer wrote a stale value from a different cache), the patcher
also silently skips it. The current design has no ability to detect "present but wrong" —
it can only fill "empty."

This is a semantic gap relative to `feedback_md5_granularity_and_stamping.md`'s lesson
that "delegate paths must re-stamp". The patcher cannot re-stamp; it can only fill.

**In practice**: The real analyzer only stamps md5 when it reads `machines.json`, and for
virtual machines it always returns `""` (since virtual machines are not in `machines.json`).
So in production the "present but wrong" scenario does not arise for virtual machines.
For real machines, the patcher would correctly leave the analyzer-stamped value alone.

The stale-md5 overwrite gap is **only a latent defect** today (no known trigger), but it
is NOT covered by any test. If the real analyzer is ever updated to stamp md5 from the
real registry in cases where the patcher is still active, a stale value could silently
persist. Per `feedback_md5_granularity_and_stamping.md` this class of bug is high-severity.

**Verdict**: ⚠ partial. The brief explicitly encodes "never overwrite" semantics and the
implementation follows the brief. But the brief itself may be under-specified: it does not
distinguish between "non-empty and correct" vs "non-empty but stale". The test suite has
no test for "non-empty but stale" scenarios. The tester accepted the brief's semantics
without flagging this gap.

**Required revision**: Add a code comment in `summary_md5_patch.py` near the `not payload.get("config_md5")` guards documenting the "fills empty, never re-stamps stale" contract explicitly, and why this is safe for the current production scenario (real analyzer always emits "" for virtual machines). This prevents future readers from treating the no-overwrite guard as a correctness invariant rather than a design choice.

---

### Q4 — `mc` variable in the app.py lambda: is it always defined and correct at callsite?

**Question**: The app.py callsite is `lambda: _get_machine_md5(machine, mc, mode=mode)`.
`mc` is `machines_config` captured from the outer `create_app()` closure. Is `mc` always
defined and pointing to the right path at this callsite?

**Investigation**: `mc` is the `machines_config` parameter of `create_app()`. It is passed
in at app construction time and is a `Path` object. It is used throughout `_run_generate_report`
at multiple points before the patcher is called (e.g., at line 6857:
`_classify_chunks(machine, mode, rd_root, mc, retention)`). If `mc` were wrong or missing,
`_classify_chunks` would have already failed earlier in the same function. The patcher is
called after `pia.main()` succeeds (line 7056) — so `mc` is definitively valid at that point.

`_get_machine_md5` accepts `machines_config: Path | None = None` and falls back to the
module-level `MACHINES_CONFIG` default when `None` is passed. Passing `mc` explicitly is
correct: it uses whatever config was injected at `create_app()` time (which in tests is
often a temp-path injected fixture, and in production is the real `machines.json`).

**Verdict**: ✓ adequately addressed. `mc` is always valid at the callsite.

---

### Q5 — Third callsite: `_batch_gen_worker.py` does NOT patch md5 (material defect)

**Question**: The brief's §4 says `_batch_gen_worker.py` is out of scope because
"Eliminating the 'patch after the fact' pattern (broader analyzer rewrite)". But the
batch worker is not "eliminating the pattern" — it runs `analyzer.main()` and then reads
`summary.json`, exactly like `_run_generate_report`. Does the batch worker also need the
md5 patcher?

**Investigation**: `_batch_gen_worker.py:run_analyzer_job` (line 53-249):
- Runs `_analyzer_mod.main()` with `--from-cache` argv (lines 104-111).
- Reads `summary_file = output_dir / "player_impact_summary.json"` (line 113).
- Returns `{"ok": True, ...}` with no md5 patching.
- The parent caller (in `app.py`, the `BatchGenerateManager`) reads the summary from disk.

The batch worker does NOT call `patch_summary_md5`. If a batch generate-report is run
for a virtual machine (or any machine not in `machines.json`), the resulting summary
will have `config_md5 = ""` / `code_md5 = ""`, which the batch path never fixes.

The brief's §4 rationale is: "Eliminating the 'patch after the fact' pattern (broader
analyzer rewrite)." But this ticket is NOT eliminating the pattern — it is consolidating
it. The spirit of the brief is to dedup the two existing patchers, not to enumerate all
callsites that need patching. However, per `feedback_enumerate_safety_paths.md` (the
M1|1 data-loss lesson), any ticket that adds a "safety carve-out" (here: md5 tagging for
virtual machines) must enumerate ALL paths that exercise that code. The brief enumerated
exactly two callsites; the batch worker is a third.

The `test_c2_*` tests only check `app.py` and `virtual_analyzer.py`. The batch worker
is untested and unpatched.

**Concrete impact**: `BatchGenerateManager` writes batch-generated reports for virtual
machines (M1sim, etc.). These reports will have `md5_status=untagged` in the rwtree
because the summary was never patched. The batch path is the primary path for bulk
report generation (production usage). This is a PRODUCTION-VISIBLE gap.

The implementer's `02_implementation.md` §Open issues item 3 flags this as "out of scope
per §4". But §4's rationale does not actually apply here: the brief was scoping out the
"eliminate the pattern entirely" redesign, not the "extend the existing pattern to a
third callsite" step.

**Verdict**: ✗ not addressed. The batch worker is a third callsite that writes
`player_impact_summary.json` without patching md5. This is not merely cosmetic: it
produces silently incomplete data for virtual machines in the batch path.

**Required revision**: Either (a) add `patch_summary_md5` call to `_batch_gen_worker.py`
in this ticket (extending the brief's callsite list), or (b) file an explicit follow-on
ticket and mark it as a known gap in `06_resolution.md`. The brief's §4 out-of-scope
language needs correction to distinguish "redesign the pattern" from "extend the pattern
to a discovered third callsite".

---

### Q6 — Indent/JSON formatting divergence: `json.dumps` (no indent) vs `write_json` (indent=2)

**Question**: The implementer flagged (Open issue 1 in `02_implementation.md`) that
`write_json` uses `indent=2` while the new shared helper uses `json.dumps` without indent.
What is the actual impact?

**Investigation**: `write_json` is defined at app.py:1845:
```python
def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

The old app.py patcher (which used `write_json`) wrote summaries with `indent=2`. The
new shared helper writes without indent. The virtual_analyzer.py old patcher used
`json.dumps(no indent)`. So:

- Old behavior for app.py callsite: `indent=2` summaries post-patch.
- New behavior for app.py callsite: no-indent summaries post-patch.
- Old behavior for virtual_analyzer.py callsite: no-indent summaries post-patch.
- New behavior for virtual_analyzer.py callsite: no-indent summaries post-patch.

This is a behavior change for the app.py path: summaries that were previously
indented after patching are now compact. The summary is subsequently read by
`read_json(summary_file)` at line 7093 — which uses `json.loads`, so formatting
is irrelevant for machine consumption.

The summaries are also served via `/api/report-validate` and similar endpoints, where
`read_json` is used again. No human-readable display reads the raw summary JSON directly
— the frontend parses the structured fields.

So the indent change is cosmetic for all machine consumers. However, it is a
BEHAVIORAL CHANGE that is not mentioned in the commit or brief as a behavioral difference.

**Verdict**: ⚠ partial. The formatting change is benign for all current consumers. But
it IS a behavioral change from the prior app.py behavior, and the implementer flagged
it as an open issue rather than documenting it as an intentional choice. The commit
message must acknowledge this explicitly.

---

### Q7 — `print(sys.stderr)` vs `logging.warning`: does stderr count as "persisted to disk"?

**Question**: Per `feedback_no_silent_swallow.md`: "any best-effort post-hook must
persist diagnostic to disk ... not just `except: pass`". Does `print(..., file=sys.stderr)`
satisfy "persist to disk"?

**Investigation**: The memory note says "put outcome on disk (rc + stderr tail + parsing
path)". In the batch-worker context (`_batch_gen_worker.py`), stderr from worker subprocesses
is not captured — it flows to the parent process stderr. In the in-process
`_run_generate_report` path, stderr also flows to the process log (which IS on disk if
the server is logging to a file).

The virtual_analyzer.py subprocess path: stderr from the subprocess is not captured
(subprocess.call is used, not subprocess.run with capture_output). So patcher errors
in the virtual path would appear in the parent process's stderr, not in any structured
log.

The `feedback_no_silent_swallow.md` memory was written specifically for the batch-worker
case where 252 items silently failed over 12 hours. In that case `try/except: pass` with
no logging was the anti-pattern. Here, `print(sys.stderr)` is definitely better than
silent swallow.

However, the memory's prescription ("persist to disk" with "rc + stderr tail + parsing
path") implies a structured per-item failure record, not just a print to the process
stream. The current implementation does not persist failure to a sidecar file.

**Verdict**: ⚠ partial. `print(sys.stderr)` is adequate for the in-process path (server
log captures it). For the virtual_analyzer.py subprocess path, stderr from
virtual_analyzer.py (itself a subprocess of the server) IS captured by the parent via
`subprocess.call` — but `subprocess.call` does not capture stderr, it flows to the
terminal/log. This is a known limitation of using `subprocess.call` rather than
`subprocess.run`. The patcher's stderr would flow correctly in this case.

No revision required — this is adequate given the patcher is best-effort. But worth
noting in the commit Self-critique.

---

### Q8 — `virtual_analyzer.py` lambda passes `(config_md5, code_md5)` positional args: are these always the correct per-mode values?

**Question**: The virtual_analyzer.py thin wrapper passes:
```python
lambda: (config_md5, code_md5)
```
These are the function's positional parameters. `_patch_summary_md5_tags` is called at
line 655 from `_delegate_to_real_analyzer` with:
```python
_patch_summary_md5_tags(
    original_args.output_dir, cfg, code,
    machine=original_args.machine, mode=original_args.rtp_mode,
)
```
where `cfg, code = patch_md5s` (line 654). The `patch_md5s` tuple is passed from
the sampling call site. Is `patch_md5s` always the per-mode correct md5?

**Investigation**: Looking at the sampling path (around line 640-660 in virtual_analyzer.py):
`patch_md5s: tuple[str, str] | None = None` is passed to `_delegate_to_real_analyzer`.
The caller constructs this from `_compute_md5s(entry, mode=args.rtp_mode)` or similar
virtual-machine registry lookup. The `_patch_summary_md5_tags` wrapper receives these
pre-computed values and passes them to the lambda.

The key question is: was `_compute_md5s` per-mode-aware before this change? Per the
existing logic (pre-dedup), `_patch_summary_md5_tags(output_dir, config_md5, code_md5)`
used the `config_md5` and `code_md5` passed in. The dedup preserves this exactly: the
lambda `lambda: (config_md5, code_md5)` closes over the same values.

**Verdict**: ✓ adequately addressed. The lambda in the virtual_analyzer.py thin wrapper
is semantically identical to the old direct pass-through. Per-mode correctness was the
responsibility of the caller before, and remains so after.

---

### Q9 — Import-time side effects: `_SUMMARY_FILENAME = "player_impact_summary.json"` module global

**Question**: Per `feedback_subprocess_import_suicide_and_module_globals.md`, module-level
globals that are set at import time (not via a class constructor) can leak state. Does
`_SUMMARY_FILENAME` in `summary_md5_patch.py` represent an import-time side effect or
module-global leak?

**Investigation**: `_SUMMARY_FILENAME = "player_impact_summary.json"` at line 59 of
`fresh_slotlab/summary_md5_patch.py`. This is a constant string assignment — no I/O,
no subprocess, no global-state mutation. It is a pure compile-time constant.

The memory's concern is specifically about:
1. Module-top function calls that create app objects, start background threads, etc.
2. Class methods reading module-level globals instead of `self._field`.

`_SUMMARY_FILENAME` is neither: it's a string constant, never mutated, never used in
place of an instance attribute. The tester's AST check (`test_import_summary_md5_patch_no_top_level_side_effects_via_ast`) correctly identifies it as an `Assign` node, which is in the `safe_types` whitelist.

However, `_SUMMARY_FILENAME` is defined but NEVER USED in the helper's code — the helper
takes `summary_path: Path` directly from the caller. This is dead code. The constant was
presumably intended for a "construct path from directory" interface variant that was not
implemented. No regression risk, but it is confusing and will mislead future readers into
thinking the helper enforces a filename convention.

**Verdict**: ⚠ partial. No side-effect concern. But `_SUMMARY_FILENAME` is dead code (unused
constant). This should be removed or the helper should use it internally.

---

### Q10 — Inject-bug proportionality: 13 inject-bug scenarios — are any vacuous?

**Question**: The tester claims 13 inject-bug verifications (per the brief's C6 TDD requirement
and per `feedback_integration_test_argv.md`). Are any of these vacuous (injecting a bug
that would already be caught by a simpler test, or a bug that doesn't reflect a real regression
path)?

**Investigation**: Reviewing the 13 inject scenarios:

- C1: file existence, function name, parameter presence, old body line count — all structural
  checks. Three of these (file existence, function name, parameter presence) are injected by
  actual mutation in `03_tests.md`. The line-count inject (old body > 10 statements) is verified
  against the current implementation but the inject step is described as "revert dedup → count
  increases" — this is a plausible inject but not actually performed as code in the test itself.

- C2: two text-grep checks (`summary_md5_patch` in app.py source, `patch_summary_md5` in
  virtual_analyzer.py source) + lambda-presence checks. These are textual, not behavioral.
  The inject is "remove the import/call from the file" — structural, not behavioral.

- C3: call-count == 1 (inject: caching/bypassing the lookup). This is behavioral and the
  inject is clear.

- C4: 9 behavioral tests with direct inject logic in the test body. Strong coverage.

- C5: 6 tests, some using `capfd` to assert stderr. The `test_c5_log_includes_machine_context`
  test has a concerning skip path: if no stderr is captured, it calls `pytest.skip()` instead
  of `pytest.fail()`. This means if the C5 `_lookup_failure_is_logged` test passes but the
  context test somehow gets no stderr, it skips silently rather than failing.

- C6: 4 tests, of which `test_c6_inject_two_callsites_diverge_pre_dedup` is the most
  valuable (proves pre-dedup divergence is detectable). `test_c6_inject_missing_nooverwrite_guard_caught_by_c4`
  does the inject inline (buggy patcher defined in test body) — solid.

Vacuous candidate: `test_c1_old_inline_block_removed_from_app_py` only asserts that the
string "patch_summary_md5" appears in app.py (a positive assertion). This is the SAME check
as `test_c2_app_py_references_canonical_patcher`. These two tests are functionally
identical — same text grep, same file, same assertion. One of them is redundant.

**Verdict**: ⚠ partial. `test_c1_old_inline_block_removed_from_app_py` is a duplicate of
`test_c2_app_py_references_canonical_patcher` (both assert `"patch_summary_md5" in app.py source`).
The `test_c5_log_includes_machine_context` skip path (line 1017: `pytest.skip(...)` instead of
`pytest.fail(...)`) is a weakness — if `test_c5_lookup_failure_is_logged` ever passes spuriously
but machine context is missing, the context test silently skips. This should be `pytest.fail()`
or the two tests should be merged.

---

## Chain disagreements

**Disagreement 1 — Brief C1 interface spec vs. actual implementation.**

The brief §3 C1 says: "accepts an injectable `md5_lookup_fn` (default uses canonical real
lookup from P1-B1; virtual injects its local `compute_machine_md5_for_mode`)". This implies
a 2-argument callable (or one with a default). The implementer chose a zero-arg callable
with no default. The tester accepted this as "a valid design decision" and documented it.
The brief was not formally amended.

Impact: If a future callsite reads the brief (not the code) and tries to pass a 2-arg
callable, it will get a `TypeError` at runtime because the helper calls `md5_lookup_fn()`
with no arguments.

Mitigation: The implemented signature is unambiguous and both callsites are correct.
But the brief remains inaccurate, which is a documentation debt.

**Disagreement 2 — Implementer: "batch worker path is out of scope per §4". Critic: it is NOT out of scope.**

As analyzed in Q5, §4's rationale ("Eliminating the 'patch after the fact' pattern") does
not apply to the batch worker case. §4 was meant to exclude a broader "redesign the
pattern" task. The implementer extended this to exclude a third callsite that performs
the exact same operation as the two covered callsites. This is an incorrect reading of §4.

---

## Hidden assumptions

**Assumption A — Each analyzer run produces a fresh summary in a new output directory.**

The helper's "fill if empty" semantic is safe only if the summary it reads was just written by
the current analyzer run. If the output_dir is ever reused (e.g., in a retry scenario where
the analyzer appends to the same dir), the patcher would see the prior run's summary with
potentially already-patched md5 fields and silently skip patching with the current run's values.

Verification: In `_run_generate_report`, `output_dir` is `f"rv_{ts}_rawdata"` — timestamp-based,
always unique. In `virtual_analyzer.py`, `output_dir` comes from `original_args.output_dir`
which is set by the caller. If the sampling caller ever retries with the same dir... not verified.

**Assumption B — The `mc` (machines_config) passed to the app.py lambda is always the
machines.json that the real analyzer knows about.**

If the real analyzer uses a different `machines_config` path than `mc` (e.g., via an
env-var override the backend doesn't know about), `_get_machine_md5(machine, mc, mode=mode)`
would look up the right path but the analyzer might have stamped a value from a different path.
This would be a "present but stale" scenario (Q3 analysis). Not a new risk introduced by this
ticket, but worth noting.

**Assumption C — The tester's inject-bug verification was performed manually, not by the CI.**

`03_tests.md` documents inject steps as "verified by inspection" or "verified by running
tests". No automated inject-mutation framework is used. This means the inject verifications
are one-time manual checks, not ongoing regression guards. If the canonical module is later
refactored in a way that inadvertently re-introduces silent swallow, no inject-based test
will catch it (the tests assert the current correct behavior, not the "inject and watch it
fail" step).

---

## Edge cases not covered

**E1 — `_batch_gen_worker.py` third callsite** (analyzed in Q5 — material production gap).

**E2 — Partial lookup: `md5_lookup_fn()` returns `("cfg_value", "")` (one empty, one set).**

The helper correctly handles this (lines 127-132: field-granular check). Covered by
`test_c4_no_op_when_only_one_lookup_value_empty`. However, the test at line 873-902
asserts only that `config_md5` was patched; it says "The exact behavior... depends on implementation"
for `code_md5`. This is a weak assertion. The helper's actual behavior is deterministic:
the empty code_md5 from the lookup (`""`) is falsy, so the condition `code_md5 and not payload.get("code_md5")`
is False, and code_md5 in the summary stays as `""`. The test does not assert this outcome
explicitly. If an implementer changed the helper to patch code_md5="" from the lookup,
the test would still pass.

**E3 — Concurrent writes to `summary_file`.**

The patcher reads, modifies, and writes the summary in sequence without any file lock.
If two concurrent generate-report runs somehow share the same output_dir (which the
timestamp-based naming prevents for app.py, but not for the virtual_analyzer.py path if
a caller invokes the same machine/mode/output_dir simultaneously), the write could lose
data. Not a new risk — this is a known property of the patchers — but not documented.

**E4 — `summary_path` is a symlink pointing to a read-only location.**

`summary_path.write_text(...)` would raise `OSError`. This is caught and logged (C5).
Adequate.

**E5 — `json.JSONDecodeError` on a corrupt summary file.**

Caught in the read step (line 116): `except (OSError, json.JSONDecodeError)`. Adequate.

---

## Required revisions

### R1 (from Q5 — ✗ material production gap): Third callsite `_batch_gen_worker.py`

Either:
(a) Add `patch_summary_md5` call to `_batch_gen_worker.py` after `_analyzer_mod.main()` succeeds,
using `lambda: _get_machine_md5(machine, mc, mode=mode)` with an appropriate `mc` injection
(the batch worker does not currently receive `machines_config` — this may require a small
interface extension to `run_analyzer_job`'s `job` dict), or

(b) File an explicit follow-on ticket for the batch path, document the known gap in
`06_resolution.md`, and add a comment in `_batch_gen_worker.py` at line 113:
```python
# Note: md5 patching is not applied here. Batch reports for virtual machines
# will have config_md5="" until <follow-on ticket>. See 08_summary_md5_patcher_dedup §open-issues.
```

### R2 (from Q3 — ⚠ semantics gap): Document "fill empty, never re-stamp stale" explicitly

Add a comment in `summary_md5_patch.py` near lines 127-132 explaining:
- Why "fill if empty" is safe for current production (real analyzer always emits "" for virtual machines).
- Why non-empty values are preserved (patcher is best-effort; the analyzer's own stamped value wins).
- What would need to change if the real analyzer ever starts stamping correctly (remove the patcher entirely, or change to a force-stamp if the patcher's value differs from the analyzer's).

### R3 (from Q9 — dead code): Remove or use `_SUMMARY_FILENAME`

Either:
(a) Remove `_SUMMARY_FILENAME = "player_impact_summary.json"` (line 59) — it is never used.
(b) Use it internally by asserting `summary_path.name == _SUMMARY_FILENAME` as a guard.
Option (a) is cleaner.

### R4 (from Q10 — weak test): Fix `pytest.skip` → `pytest.fail` in `test_c5_log_includes_machine_context`

Line 1017: `pytest.skip(...)` should be `pytest.fail(...)`. If no stderr is captured when
`test_c5_lookup_failure_is_logged` passed, that is a test-isolation bug that needs to fail loudly,
not skip silently.

---

## Commit-message `## Self-critique` section (paste-ready)

```
## Self-critique

- Q1 (silent-swallow removal backward-compat): old `except Exception: pass` → `print(stderr)`.
  No caller expected silence; daemon thread's stderr flows to process log. Safe. ✓

- Q2 (zero-arg vs 2-arg interface): brief implied 2-arg lookup_fn; impl chose zero-arg lambda
  at callsite. Lambda binding is safe at both callsites (local closure, synchronous call). Tester
  documented pivot. Brief text is now inaccurate — documentation debt, not a functional defect. ✓

- Q3 (C4 stale-md5 gap): "fill if empty" cannot detect "present but stale". Safe today because
  real analyzer always emits "" for virtual machines. Documented with comment (R2). ⚠ open

- Q4 (mc variable at callsite): `mc` is always valid at patcher call point (used earlier in
  same function without issue). ✓

- Q5 (third callsite — _batch_gen_worker.py): Batch worker runs analyzer.main() and reads
  summary.json but does NOT call patch_summary_md5. Batch reports for virtual machines get
  md5_status=untagged. KNOWN GAP — follow-on ticket filed, comment added in worker. ✗ open

- Q6 (indent formatting change): Old app.py patcher used write_json (indent=2); new shared
  helper uses json.dumps(no indent). All consumers use json.loads — formatting is irrelevant
  for correctness. Behavioral change noted. ⚠ noted

- Q7 (print vs logging.warning vs persist-to-disk): print(sys.stderr) adequate for best-effort
  patcher. Full disk persistence is not warranted for a metadata tagging operation. ⚠ noted

- Q8 (virtual_analyzer lambda values): lambda: (config_md5, code_md5) closes over the same
  pre-computed per-mode values used by the old wrapper. Semantically identical. ✓

- Q9 (dead code _SUMMARY_FILENAME): Unused constant. Removed (R3). ⚠ fixed

- Q10 (inject-bug proportionality): test_c1_old_inline_block_removed_from_app_py is a
  duplicate of test_c2_app_py_references_canonical_patcher. test_c5_log_includes_machine_context
  uses pytest.skip instead of pytest.fail for the no-stderr path. Fixed (R4). ⚠ fixed
```
