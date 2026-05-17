# 05_critique.md — Ticket P1-A1 (Three-invocation parity test)

> impl-critic output. Wave 2, parallel with impl-verifier.
> Chain read: 00_ticket.md + 03_tests.md + test file + app.py (production source)
> Verifier (04_verification.md) not present — did not exist at review time. Noted where this leaves gaps.

---

## Verdict

**APPROVE-WITH-REVISIONS**

The test infrastructure is sound and the parity guard is real. However three
defects require the tester to iterate before this can ship: (1) path (b) is
misrepresented — it bypasses `BatchRunManager` entirely and is functionally
identical to path (a); (2) path (c) uses different bankruptcy params than paths
(a)/(b), so "parity" is achieved only because `bankruptcy_simulation` is not
asserted, making the test blind to that divergence; (3) the `os._exit` monkeypatch
in `TestThreeInvocationParity` affects path (a) and (b) subprocess helpers that do
not call `os._exit`, while path (c)'s in-process `_run_generate_report` needs it
for a different reason — the monkeypatch scope is confused and its presence on the
subprocess tests signals a copy-paste that was never reasoned about.

The inject-bug experiment is valid. The fixture handling is correct. The stripped-
field choices are defensible. These strengths are why the verdict is revisions, not
reject.

---

## Verifier status

`04_verification.md` did not exist at review time. All stress-question verdicts
below are based on reading the test source + production code. The verifier's
empirical run-time data (flakiness count, actual RTP across 3 runs, DB row
inspection) is not yet available to cross-check. If verifier returns PASS, the
revisions below are still required before commit.

---

## Stress questions (10)

---

### Q1 — Does path (b) actually exercise `BatchRunManager`?

**Question.** The brief (§1, §3 C2) explicitly names path (b) as "subprocess via
`BatchRunManager` per-item". `01_pipeline_map.md §5 Q1` identifies three distinct
invocation styles — `POST /api/runs`, `BatchRunManager`, `_run_generate_report` —
as the three styles whose parity is unverified. Does `_run_path_b` in the test file
actually exercise `BatchRunManager`?

**Reading the code.** `_run_path_b` (test lines 303-371) imports `RunManager`,
`RunCreateRequest`, and `StateStore` directly from `app.py`, constructs a
`RunManager` instance, and calls `manager.start_run(req)`. `BatchRunManager`
(app.py:3160) wraps `RunManager` and calls `self._run_manager.start_run(req)` at
app.py:3848. The test docstring acknowledges this: "We simulate that by calling
`RunManager.start_run` directly". `BatchRunManager` itself is never imported or
instantiated anywhere in the test file.

**What this means.** Path (b) in the test is `RunManager.start_run` called
directly, not via `BatchRunManager.start_batch`. The orchestration layers that
`BatchRunManager` adds — per-item `RunCreateRequest` construction from a
`BatchRunRequest`, the `_try_acquire_key` per-(machine, mode) busy-lock, the
`check_rawdata_status` call at app.py:3259, the `_wait_for_run` inner loop, event
logging — are all skipped. From the perspective of what subprocess the analyzer
gets spawned with, paths (a) and (b) in the test are byte-identical (same
`RunManager.start_run` → `_default_popen_factory`). The "three distinct paths"
contract is not satisfied. What the test actually covers is two identical subprocess
paths plus one in-process path.

**Verdict.** ✗ Not addressed. The comment in `_run_path_b` admits the bypass ("We
simulate that by calling RunManager.start_run directly") but does not acknowledge
that this violates the brief's intent. The tester's own 03_tests.md §89-91 notes
"Path (b)'s underlying mechanism is identical to path (a)" — this should have been
flagged as a brief-coverage gap, not presented as meeting C2.

---

### Q2 — Does path (c) use the same bankruptcy params as (a)/(b)?

**Question.** The three paths must produce identical summaries. `bankruptcy_simulation`
is a top-level key in the summary schema (per `01_pipeline_map.md §6`). Do all
three paths receive the same `--bankruptcy-session-spins` and
`--bankruptcy-bankroll-multipliers` values?

**Reading the code.**
- Path (a) CLI (test line 243): `--bankruptcy-session-spins 100`,
  `--bankruptcy-bankroll-multipliers 10`.
- Path (b) `RunCreateRequest` (test line 349): `bankruptcy_session_spins=100`,
  `bankruptcy_bankroll_multipliers="10"`. Same as (a).
- Path (c) `_run_generate_report` (app.py:6846-6847): `bankruptcy_session_spins: 10000`,
  `bankruptcy_bankroll_multipliers: "10,100,200,500"`. These are hardcoded
  production defaults inside `_run_generate_report`; the endpoint accepts no
  caller-supplied bankruptcy params.

**What this means.** Path (c) runs with 100× more bankruptcy session spins (10000
vs 100) and 4 multiplier tiers (10, 100, 200, 500) vs 1 tier (10) for paths (a)
and (b). The `bankruptcy_simulation` block in the summary will be structurally
different. The test does NOT compare `bankruptcy_simulation` — which is exactly why
all 16 tests pass: the test is blind to this divergence. The "byte-identical
summaries after stripping nondeterministic fields" claim does not hold for the full
summary; it holds only for the specific fields the test happens to assert.

**Verdict.** ✗ Not addressed. The stripped fields list in 03_tests.md does not
include `bankruptcy_simulation`; there is no mention of the bankruptcy param mismatch
anywhere in 03_tests.md or in the test file's docstrings. This is a hidden
over-narrowing of C3's "summaries agree" contract.

---

### Q3 — Is the `os._exit` monkeypatch on subprocess tests meaningful or cargo-cult?

**Question.** Every test method in `TestThreeInvocationParity`, `TestInjectBugPathADiverges`,
and `TestSubprocessCoverage` applies `monkeypatch.setattr("os._exit", lambda rc: None)`.
Path (a) and path (b) spawn real subprocesses via `subprocess.run()` and
`RunManager.start_run()` respectively. Does `os._exit` in the test process have any
effect on a subprocess that calls `os._exit` in its own process space?

**Reading the code.** `os._exit` in the subprocess runs in the subprocess's address
space. Patching it in the test's process has zero effect on the subprocess. The only
path where patching `os._exit` in the test process matters is path (c), where
`_run_generate_report` patches `os._exit` in-process (app.py:6875) but then
restores it (app.py:6937). The test's additional `monkeypatch.setattr("os._exit",
lambda rc: None)` on top of this is redundant for (c) — the production code already
patches and restores it — and meaningless for (a) and (b).

**What this means.** The `os._exit` monkeypatch is present on all tests because it
was added once and copy-pasted. It is inert for the subprocess paths and redundant
for the in-process path. It is not harmful, but it signals that the tester did not
reason carefully about what each path needs. The more concerning corollary: if there
is a test that actually needs `os._exit` patched at the test level to prevent the
test runner from exiting, that need is currently masked by the production code doing
it correctly — and if the production code ever stops patching it (a refactor this
very ticket suite is building toward), the test would start killing the test runner
without the test author understanding why.

**Verdict.** ⚠ Partial. No current breakage, but the copy-paste without reasoning
is a code smell that will mislead the next reader.

---

### Q4 — Does path (c) actually exercise `_run_generate_report` at line 6700?

**Question.** The brief (§1) says path (c) is "in-process via `_run_generate_report:6700`".
The test calls `POST /api/rawdata/M14/generate-report` via `TestClient`. Does the
sync endpoint dispatch to `_run_generate_report`?

**Reading the code.** app.py:7370-7383: when `async=false` (the default), the
endpoint calls `_run_generate_report(machine, mode, config_md5=config_md5,
code_md5=code_md5)` synchronously. The test sends `{"mode": 1, "config_md5": _CFG_MD5,
"code_md5": _CODE_MD5}` — no `"async"` key, so `use_async = bool(req.get("async")
or False) = False`. The sync path fires.

**What this means.** Yes, `_run_generate_report` is exercised. The brief's cite is
accurate. The monkey-patches in `_run_generate_report` (`pia.post_json`, `sys.argv`,
`os._exit`) all fire because the test uses a real `create_app` + `TestClient`, not
a stub.

**Verdict.** ✓ Adequately addressed. Path (c) correctly exercises the production
code path at the cited line.

---

### Q5 — Is the inject-bug experiment a tautology or a real regression guard?

**Question.** The inject-bug experiment drops `--target-halfwidth-pp` from path (a)'s
CLI. The observable divergence is `sampling.target_halfwidth_pp`. Is this testing
that the parity guard catches a real behavioral regression, or is it testing that
dropping a CLI flag causes that flag's echo-field in the summary to change — a
tautology?

**Analysis.** The brief's intent for C4 is to prove the parity test catches
regressions between paths. `sampling.target_halfwidth_pp` is a field that reflects
the CLI arg value, not a derived result. So yes, dropping the arg causes that field
to change by definition. Whether this constitutes a meaningful regression depends on
what we care about:

- If the concern is "did all three paths receive the same configuration?" then
  `target_halfwidth_pp` is a valid signal because it proves config parity.
- If the concern is "do all three paths produce the same analytic output for the same
  data?" then `rtp.point_pct`, `payout_ids_top20`, and `total_spins` are the meaningful
  signals — and those are already asserted in `TestThreeInvocationParity`.

The inject-bug experiment proves that a config divergence (one path got a different
arg) is detectable. That is a valid parity guard. It is not a tautology — if
`target_halfwidth_pp` were not in the summary schema, the test would not catch it.

The tester's pivot from `achieved_halfwidth_pp` (which is data-derived and identical
regardless of the CLI arg, as the tester correctly explains) to `target_halfwidth_pp`
(which echoes the CLI arg) is correct. The brief's C4 wording was wrong.

**Verdict.** ✓ Adequately addressed. The inject is meaningful; the pivot from
achieved to target is the right fix; the tester documented it clearly.

---

### Q6 — Are there summary fields NOT asserted that could diverge between (a)/(b) and (c)?

**Question.** The test asserts RTP, md5 tags, analyzer_version, payout_ids_top20,
total_spins, paid_spins, and target_halfwidth_pp. The full summary schema (per
`01_pipeline_map.md §6`) contains many more fields. Are there fields NOT asserted
that would diverge due to structural differences between the three paths?

**Confirmed divergent fields not asserted.**

1. `bankruptcy_simulation` — different params (Q2 above). This is a full nested
   dict with tier breakdowns; it will differ structurally.

2. `sampling.chunks` — path (c) uses `max_chunks = len(_cached_responses)` = 1
   (one chunk pre-loaded). Path (a)/(b) use `--max-chunks 1` with `--from-cache` /
   `--resume-from-cache` respectively. These should match, but the mechanism differs:
   path (c) pre-loads responses and feeds them through the monkey-patched `post_json`,
   while paths (a)/(b) read from the `--from-cache` dir. The chunk count in the
   summary should be 1 in all cases — but is it? Not asserted directly.

3. `sampling.stop_reason` — path (a)/(b): `from_cache_complete` (or similar cache-
   read exit). Path (c): the analyzer runs in sampling mode via the monkey-patched
   `post_json` iterator; stop reason will be `max_chunks_reached` or similar. Not
   asserted. If these diverge, the test is blind.

4. `guideline_assessment.data_quality` / `data_confidence` — may depend on total
   spin count and CI, which should match. But the bankruptcy tier differences could
   affect `data_confidence` indirectly (it uses bankruptcy results per the schema).
   Not asserted.

**Verdict.** ⚠ Partial. The core parity fields (RTP, md5, top20) are asserted. The
`bankruptcy_simulation` divergence is a real gap (structurally different data not
flagged). `sampling.stop_reason` divergence is a plausible gap not asserted.

---

### Q7 — Is the fixture stable? What happens if M14 rawdata is refreshed?

**Question.** The test uses `tests/fixtures/m14_mode1_r8_s50.json` as its fixture.
Per memory `feedback_no_proactive_fetch.md`: existing cache should be used. But the
fixture is a committed file in `tests/fixtures/`, not the live rawdata. Is the
fixture's stability guaranteed across repo lifetime?

**Reading the code.** The fixture is a static JSON file committed to the repo at
`tests/fixtures/m14_mode1_r8_s50.json` (confirmed by Glob). The test reads it via
`FIXTURE_PATH.read_text()` and constructs a synthetic chunk envelope from it —
independent of any live rawdata directory. The live `rawdata/M14/mode_1/` directory
is not read.

**What this means.** The fixture is stable as long as the file is not overwritten or
deleted. It is not derived from live rawdata, so refreshing M14 chunks has no effect.
The `TestCommonFixtureGuard` class validates its shape on every run.

**Verdict.** ✓ Adequately addressed. The fixture design is correct and insulated from
live rawdata.

---

### Q8 — Do paths (a) and (b) risk non-determinism from parallel chunk processing?

**Question.** If the analyzer processes chunks in parallel (multiple workers), could
chunk processing order differ between runs, producing subtly different summaries
even for the same input?

**Reading the code.** The test passes `--batch-concurrency 1` and `--max-chunks 1`
to both paths (a) and (b). A single chunk, single worker. No parallelism.
Path (c)'s `_run_generate_report` also uses `batch_concurrency: 1` and
`max_chunks: 1` (one pre-loaded response). Non-determinism from parallel workers
is not possible in this configuration.

**Verdict.** ✓ Adequately addressed. The single-chunk, single-concurrency setup
eliminates this risk.

---

### Q9 — Is the 185s runtime acceptable, and will this test survive CI tightening?

**Question.** 03_tests.md §166 notes the test may be "slow on CI". The test file has
no `@pytest.mark.slow` or similar marker. Will this test get silently skipped or
timeout-killed under future CI hardening?

**Reading the code.** The test file has no slow marker. The `skipif` guards only
cover fixture/analyzer missing. The tests spawn real subprocesses (path (a): one
subprocess, path (b): one subprocess via RunManager + watcher thread, path (c):
in-process with a real analyzer run). Each parity test class runs all three paths
— meaning `TestThreeInvocationParity` spawns 6 subprocess-equivalent runs (3 paths
× 2 assertions per comparison). `TestInjectBugPathADiverges` spawns 4 more (2 tests
× path-a + path-b each). `TestSubprocessCoverage` spawns 8 more (5 tests, some
sharing paths). The total subprocess count is high.

If CI has a per-test timeout of 30-60s (common), individual tests that each run
60-90s of subprocess work will fail. The `--timeout 30` arg to the analyzer means
each subprocess is bounded, but path (b) additionally waits up to 90s via
`_wait_for_run_completion`.

**What this means.** No marker exists to let CI skip this test set when time-bound.
The test should either be tagged `@pytest.mark.integration` (or equivalent) so CI
can select or deselect it, or the verifier's 3× run confirms runtime is within
bounds. Since verifier output is absent, this is unverified.

**Verdict.** ⚠ Partial. No CI marking, no runtime verification in the chain. The
tester flagged it in open gaps (03_tests.md §166) but did not act on it.

---

### Q10 — Does the brief's "BatchRunManager per-item" path have any behavioral difference that the test must capture?

**Question.** If path (b) truly did go through `BatchRunManager.start_batch`, are
there any behavioral differences that would actually cause summary divergence vs
path (a)?

**Reading the code.** `BatchRunManager.start_batch` at app.py:3242 calls
`RunManager.start_run` with a `RunCreateRequest` that sets `resume_from_cache_dir`
(not `from_cache_dir`). The CLI arg emitted is `--resume-from-cache` vs
`--from-cache` for path (a). The analyzer handles these differently:
- `--from-cache`: reads all chunks in the dir, then exits (pure replay).
- `--resume-from-cache`: reads existing chunks to seed stats, then continues live
  sampling until CI target or max_chunks.

With a pre-populated single-chunk dir, `--resume-from-cache` should exit immediately
after reading the one chunk (CI target at 0.001pp with 400 spins is not reachable,
so it would continue sampling — unless `max_chunks=1` caps it at 1 chunk and exits).
The test's `_run_path_b` uses `resume_from_cache_dir` (line 352) with `max_chunks=1`,
which should match this behavior. But the key structural difference — `--resume-from-
cache` vs `--from-cache` — means path (b), if correctly implemented, would be a
distinct test of the resume path. The current test bypasses this by calling
`RunManager.start_run` directly with `resume_from_cache_dir`.

The `stop_reason` in the summary will differ between `--from-cache` (which exits
with a cache-specific stop reason) and `--resume-from-cache` (which exits with
`max_chunks_reached` when the cache is exhausted at 1 chunk). This is an unasserted
field (see Q6), which is why the current test shows green despite this structural
difference.

**Verdict.** ✗ Not addressed. The `--from-cache` vs `--resume-from-cache` distinction
is a real behavioral difference that the brief meant to capture (and which explains
why `BatchRunManager` was listed as a separate path). The test collapses both to
`--resume-from-cache` via `RunManager.start_run` and does not assert `stop_reason`,
making this divergence invisible.

---

## Chain disagreements (implementer ↔ tester ↔ verifier)

Since there is no implementer (test-only ticket) and no verifier output yet, the
disagreements are between the brief and the tester.

1. **Brief C2 "path (b) via BatchRunManager" vs tester "RunManager directly".**
   The brief says path (b) exercises `BatchRunManager` per-item. 03_tests.md §89-91
   and the test docstring acknowledge this bypass but present it as equivalent.
   It is not equivalent: `BatchRunManager.start_batch` constructs
   `RunCreateRequest` with `resume_from_cache_dir` (not `from_cache_dir`), passes
   different args to the subprocess (the `--resume-from-cache` flag), and wraps the
   run with the busy-key lock and event logging. None of this is exercised.

2. **Brief C4 "assert on achieved_halfwidth_pp" vs tester "target_halfwidth_pp".**
   The tester correctly identifies that `achieved_halfwidth_pp` does not diverge
   when `--target-halfwidth-pp` is dropped. The pivot to `target_halfwidth_pp` is
   correct. This is a brief defect, not a tester defect — but it is a chain
   disagreement that the verifier must confirm by actually running the inject
   experiment.

3. **Brief C3 "byte-identical summaries" vs test's scope restriction.**
   C3 says "summaries agree" but the test asserts only 6 fields from a ~50-field
   summary. The `bankruptcy_simulation` divergence (Q2) means the summaries are NOT
   byte-identical after stripping nondeterministic fields, yet the test reports
   green. This contradicts C3's stated contract.

---

## Hidden assumptions

1. **Assumption: `create_app` in the test process is safe to call with an isolated
   tmp_path.** `RunManager._recover_orphan_running_runs` fires at `create_app` time
   (per `01_pipeline_map.md §4`). In the test, it is called with an empty `db_path`.
   This should be safe (no orphans in an empty DB), but it is not tested — if
   `_recover_orphan_running_runs` ever fails on an empty DB or logs to a location
   the test process doesn't control, the test could hang or error unexpectedly.

2. **Assumption: path (c)'s `pia` module is imported fresh each time.** Python module
   imports are cached in `sys.modules`. If `TestThreeInvocationParity` runs in one
   test process and `test_rtp_point_pct...` (which patches `pia.post_json`) runs
   after another test that imported `pia`, the iterator `_resp_iter` inside
   `_run_generate_report` will be exhausted from the previous call and subsequent
   invocations in the same test process will return `[]`. This is guarded by path
   (c) being a TestClient call (each call to `_run_path_c` constructs a new `app`
   and `TestClient`) — but the `import fresh_slotlab.player_impact_analyzer as pia`
   line (app.py:6867) is inside the `_run_generate_report` closure, which re-imports
   from cache. Whether `_resp_iter` leaks between TestClient calls depends on whether
   the closure is re-entered fresh each time. It is (the closure is called per HTTP
   request), so this is safe — but it depends on `pia.post_json` being correctly
   restored by the finally block (app.py:6936). The monkeypatch in the test
   (`monkeypatch.setattr("os._exit", lambda rc: None)`) patches `os._exit` at module
   level in the test process, but `_run_generate_report` patches it on `os._exit`
   directly (app.py:6875) which is the same object. After restoration, the test's
   monkeypatch has already overwritten the global. The order of restoration matters.
   This is fragile and not explicitly tested.

3. **Assumption: the test's `machines_cfg` JSON shape is accepted by `_classify_chunks`.**
   The test writes a minimal `machines.json` with `configSummaryMd5` / `codeSummaryMd5`.
   `_classify_chunks` calls `_get_machine_md5` which reads `configSummaryMd5` /
   `codeSummaryMd5` from the machines JSON. The test's md5 values are the sentinel
   strings `parity_cfg_*` and `parity_code_*`. The md5 filter in
   `_run_generate_report` (app.py:6734-6764) will use these sentinels to match chunk
   envelopes — which also carry the same sentinel md5s (via `_write_chunk`). This
   chain is correct, but it assumes `_classify_chunks` does not validate md5 format
   (e.g., reject non-hex strings). Not verified.

---

## Edge cases not covered

1. **`BatchRunManager` orchestration layer** — see Q1. The actual `BatchRunManager`
   per-item path (with busy-key locking, `check_rawdata_status`, event logging, and
   `--resume-from-cache`) is never exercised.

2. **`sampling.stop_reason` divergence between `--from-cache` and `--resume-from-cache`**
   — path (a) uses `--from-cache` (exits with cache-read stop reason); path (c) uses
   the in-process analog (exits with `max_chunks_reached`). Not asserted.

3. **`bankruptcy_simulation` block divergence** — path (c) uses 10000 session spins
   and 4 multiplier tiers; paths (a)/(b) use 100 session spins and 1 tier. Not
   asserted.

4. **`_run_post_analyzer_inference` side effect on path (c)** — `_run_generate_report`
   spawns a daemon thread at app.py:6054-6059 to fire `_run_post_analyzer_inference`.
   This daemon thread may still be running when the TestClient context manager exits.
   The test does not wait for or assert the outcome of this side thread.

5. **`SLOT_SKIP_AUTO_INFER=1` env var effect** — the monkeypatch sets this, which
   presumably suppresses the inference scripts. But this env var is set on the test
   process, not on the subprocess spawned by path (a)/(b). If the subprocess inherits
   env vars (it does by default in Python subprocess), then paths (a)/(b) also skip
   auto-infer. But paths (a)/(b) go through `RunManager.start_run` which may or may
   not fire inference independently of the subprocess env var. The relationship between
   this env var and the `_run_post_analyzer_inference` daemon thread in path (c) is
   not documented.

6. **Concurrent parity test runs** — multiple tests in `TestThreeInvocationParity`
   each call all three paths, writing to `tmp_path/path_a_out/`. Each test method
   shares the same `parity_env` fixture (function scope). If pytest decides to run
   these in a worker pool, the `parity_env` fixture would be separate per test
   (function scope guarantees this). But path (b) writes to the DB at `env["db_path"]`
   and two test methods that both call `_run_path_b` in the same fixture scope would
   insert two runs into the same DB. Confirmed safe (function-scope fixture =
   different `tmp_path` per test), but this was not explicitly verified.

---

## Required revisions

### R1 (from Q1 and Q10) — Brief says BatchRunManager; test uses RunManager directly

The tester must either:
(a) Exercise `BatchRunManager.start_batch` via `POST /api/batch-run` for path (b),
    so the full orchestration layer (including `--resume-from-cache`) is tested. This
    is the correct implementation of C2. OR
(b) Update the ticket brief (via the main session) to explicitly scope path (b) as
    "RunManager.start_run called with `resume_from_cache_dir`" rather than
    "BatchRunManager per-item", and add an explicit comment in the test explaining
    WHY `BatchRunManager` itself is not tested (deferred per 03_tests.md §159-163
    open gap). If (b) is chosen, 03_tests.md must state this as a coverage gap, not
    as C2 meeting.

### R2 (from Q2 and Q6) — Bankruptcy params diverge between path (c) and (a)/(b)

Path (c) uses `bankruptcy_session_spins=10000, tiers=[10,100,200,500]`;
paths (a)/(b) use `bankruptcy_session_spins=100, tiers=[10]`. Either:
(a) The test must assert that `bankruptcy_simulation` is identical across all three
    paths (which will fail until the params are aligned), OR
(b) The test must explicitly strip `bankruptcy_simulation` from the comparison with
    justification in 03_tests.md, AND the brief's C3 "byte-identical summaries"
    must be updated to reflect that bankruptcy params are not parity-comparable due
    to the hardcoded production defaults in `_run_generate_report`.

This is a structural divergence between the three paths that the parity test currently
hides. It must be named, not silently avoided.

### R3 (from Q9) — No CI slow-test marking

Add `@pytest.mark.integration` (or whatever slow marker the project uses) to all
test classes in this file, so CI can gate them separately from unit tests. Update
`03_tests.md` to document expected runtime per class.

---

## Commit-message `## Self-critique` section

Paste verbatim into the commit body:

```
## Self-critique

- **Does path (b) actually exercise BatchRunManager?** No — it calls `RunManager.start_run` directly, bypassing `BatchRunManager.start_batch`, the busy-key lock, `check_rawdata_status`, and the `--resume-from-cache` vs `--from-cache` distinction. Documented as an open gap in 03_tests.md §159-163. Brief C2 is partially satisfied; full `BatchRunManager` coverage is deferred. OPEN.

- **Do all three paths use the same bankruptcy params?** No — path (c) uses `bankruptcy_session_spins=10000, tiers=[10,100,200,500]` (hardcoded in `_run_generate_report`); paths (a)/(b) use `100, [10]`. The `bankruptcy_simulation` block diverges. The test does not assert this block. This means C3's "byte-identical summaries" holds only for the 6 asserted fields, not the full summary. OPEN.

- **Is the brief's C4 inject signal correct?** Brief said `achieved_halfwidth_pp`; correct signal is `target_halfwidth_pp` (data-derived vs CLI-echoed). Tester identified this and pivoted correctly. ADDRESSED.

- **Does os._exit monkeypatch on subprocess tests do anything?** No — patching it in the test process has no effect on a subprocess. The monkeypatch is inert for paths (a)/(b) and redundant for path (c) (production code already handles it). Harmless but misleading. OPEN (cosmetic).

- **What summary fields diverge silently?** `sampling.stop_reason` (from-cache vs max_chunks exit), `bankruptcy_simulation` (param mismatch). Neither asserted. OPEN.

- **CI runtime marking?** No `@pytest.mark.integration` or equivalent. Full file runs in ~185s. OPEN.
```
