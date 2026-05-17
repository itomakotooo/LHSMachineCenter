# 05_critique.md — impl-critic report for ticket phase1/06_classify_chunks_historical_spec

**Ticket**: P1-A4 — `_classify_chunks` historical semantics spec'd

---

## Verdict: APPROVE-WITH-REVISIONS

Two revisions required before shipping:

1. The docstring's C1 description of `_prepare_batch_gen_item` makes a false invariant claim — the batch path DOES pass historical chunks to the analyzer subprocess via the `--from-cache chunk_dir` argument. The docstring is wrong.
2. The verifier's `04_verification.md` is missing entirely. W2 was not complete when this critique was authored; the verifier was running in parallel and the file was not written yet. The critique proceeds from direct code reading but the chain is formally incomplete.

---

## Stress questions (8 total: 3 ✓ / 2 ⚠ / 3 ✗)

---

### SQ1 — Tester's self-caught spy bug: evidence of discipline or fragile design?

**Question (app.py / 03_tests.md)**: The tester's first spy used `"_marker" in result.get("response", [{}])[0:1]` — checking string membership in a list, not dict-key presence. It was silently non-operative. The tester caught this and fixed it. Does the corrected spy mechanism actually work? And are other tests in the file using a similar list-slice guard that could be silently non-operative?

**Attempted answer**: The corrected spy (lines 290-297 of the test file) iterates `result.get("response", [])` and appends `item["_marker"]` for any dict that has `"_marker"`. This is correct — it doesn't use the list-membership pattern. I checked every other test in the file; no other test uses the `[0:1]` list-slice or a `"string" in list` guard. The self-catch + fix is documented, the fix is structurally sound, and the inject-bug result (observed HISTORICAL marker in the list when the bug was injected) confirms the mechanism worked.

**Verdict: ✓** — Discipline shown. Fix is verified by the inject-bug trace in 03_tests.md. The tester's own description that it "always returned False" is the right smoking gun.

---

### SQ2 — The 7th consumer `_enumerate_rawdata_deletable`: real consumer or alias?

**Question (app.py:8766 / 02_implementation.md)**: The brief listed 6 consumers. Implementer found 7, adding `_enumerate_rawdata_deletable` at ~8713. The implementer claims it's "semantically identical to `_auto_cleanup_for_space`." Is that accurate, or is there a behavioral difference? Does it also appear in the test file?

**Attempted answer**: Reading the actual code at 8766-8817 confirms the function walks `rd_root`, calls `_classify_chunks` per `(machine, mode)`, and returns `cls["deletable"] + cls["historical"]` sorted by mtime. The same semantics as `_auto_cleanup_for_space`'s collection phase. The lock/in-use guards are identical in logic. The implementer's claim is accurate. However: the test file has NO direct test for `_enumerate_rawdata_deletable`. It is not in the parametrized `test_read_only_callers_preserve_historical_file` list either (that list only covers `_classify_chunks` and `check_rawdata_status`, both of which are display-only). `_enumerate_rawdata_deletable` is a deletion-prep function — it feeds `delete_rawdata` in the cleanup endpoint. The C3 tests that check "auto_cleanup requires space pressure" cover the downstream behavior, but no test asserts that `_enumerate_rawdata_deletable` itself doesn't unlink anything during enumeration. Structurally, the code shows it only appends to a list — it does not call `unlink`. This is adequately low-risk and the lack of a direct test is defensible.

**Verdict: ✓** — Consumer identified, semantics verified. Absence of a direct no-unlink test for this function is minor (the function is 52 lines and provably read-only by inspection), not a critical gap.

---

### SQ3 — Line reference accuracy: brief says 6733, docstring says ~6733, tester says 6845

**Question (00_ticket.md §3 C1, 03_tests.md inject-bug log, app.py)**: The brief uses "`_run_generate_report:6733`" as the line reference. The tester documents the inject-bug target as "line 6845 inside the `else` branch." The implementer's docstring says "~line 6733." Which is correct, and does the mismatch matter?

**Attempted answer**: The actual function definition `def _run_generate_report(` is at line 6789 (confirmed by reading). Line 6733 in the current file is inside `create_run` (the `/api/runs` endpoint), which is unrelated. The `usable_entries = classified["kept"] + classified["deletable"]` line in the `else` branch is at line 6845. The brief's line reference was wrong (off by ~56 lines and pointing to a completely different function). The tester had the correct line (6845) for the inject-bug target. The docstring says "~line 6733" — also wrong, since the function is at 6789. The inject-bug was executed at the correct line, so the test itself is fine. But the docstring's consumer enumeration says "~line 6733" for `_run_generate_report` — this reference is stale/wrong and will mislead future reviewers looking for the function.

**Verdict: ⚠** — The test is correct (tester used the right line). But the docstring says `~line 6733` for `_run_generate_report` when the function is at 6789. The docstring's "~" approximation notation is meant to be imprecise, but being off by 56 lines pointing to a different function is beyond approximation. A future reviewer grep-ing for 6733 finds `create_run`, not `_run_generate_report`. Revision: update docstring to say `~line 6789` (or the current line at commit time).

---

### SQ4 — `_prepare_batch_gen_item` at ~7136: does the docstring's invariant claim hold for the subprocess path?

**Question (app.py:7209-7295, _batch_gen_worker.py:76-103, 02_implementation.md)**: The docstring (line 992-995) says `_prepare_batch_gen_item` uses "classified['kept'] + classified['deletable'] only. No md5-filter path; historical chunks are NEVER included." Is this true?

**Attempted answer**: This is the most significant defect found. Reading `_prepare_batch_gen_item` at 7209-7295 confirms: it calls `_classify_chunks`, computes `usable = classified["kept"] + classified["deletable"]` (line 7226), and uses `len(usable)` for `max_chunks`. So far so good. But the `job` dict it passes to the worker uses `"chunk_dir": str(mode_dir)` (line 7279) — the raw mode directory path, not a filtered list of chunk paths. The worker in `_batch_gen_worker.py` at line 81 passes `--from-cache str(job["chunk_dir"])` to the analyzer. The analyzer's `--from-cache` path reads ALL `chunk_*.json` files from that directory. The worker does NOT pass `--upstream-config-md5` or `--upstream-code-md5` to the analyzer. Per `player_impact_analyzer.py` line 183-187, the default for `--upstream-config-md5` is empty string, and the comment says "empty strings = no filter (backward-compat — merges every chunk)." Therefore the analyzer subprocess called by `_prepare_batch_gen_item` reads every chunk file in the directory — including historical-md5 chunks — and merges ALL of them into its output. `max_chunks = len(usable)` limits how MANY chunks are processed, but does not filter by md5. If the directory has, say, 3 kept + 2 deletable + 4 historical chunks, the analyzer sorts by chunk index and reads up to `max_chunks=5` — and some of those 5 might be historical if their chunk index sorts before kept/deletable ones.

The docstring claim "historical chunks are NEVER included" for the batch path is FALSE for the subprocess execution. The in-process `usable` list correctly excludes historical, but this filtered list is not forwarded to the worker. The C2 regression test covers only `_run_generate_report` (the in-process path), not the batch path.

**Verdict: ✗** — CRITICAL. The docstring's invariant claim about `_prepare_batch_gen_item` is wrong. The batch subprocess path feeds historical chunks to the analyzer when historical chunks co-exist with current chunks. This is a pre-existing behavior (not introduced by this ticket), but the docstring now canonizes a false invariant. The ticket's C1 explicitly required documenting the "NEVER passes historical" semantics — this documentation is incorrect for the batch path. Required revision: correct the docstring for `_prepare_batch_gen_item` to describe actual behavior; add a note about the batch path's directory-level coupling.

---

### SQ5 — C5 signature check: does the test actually guard against all revival paths?

**Question (test file:134-149, app.py:655-660)**: `test_accepted_parameters_are_read_only_in_intent` asserts the parameter set equals `{"machine", "mode", "rawdata_root", "machines_config"}`. Any unexpected parameter fails. Does this cover the case where `auto_delete_mismatched` is added back but with a different name (e.g., `delete_stale`, `auto_clean`)?

**Attempted answer**: Yes — the test's assertion `unexpected = param_names - allowed` fails on ANY parameter not in the allowed set. Any revival under any name (including `delete_stale`, `nuke_historical`, etc.) would cause a test failure. The test is robust against name-variation because it's an allowlist, not a denylist. The only gap would be if the revival was done inside the function body using a global `AUTO_DELETE` constant rather than a function parameter — but that scenario is outside the scope of the C5 contract ("no `auto_delete_*` parameter").

**Verdict: ✓** — Allowlist approach correctly blocks any-name parameter addition. Adequately covers the brief's C5 intent.

---

### SQ6 — `_run_generate_report` md5-filter exception: does it silently re-enable the historical-via-stale-md5 bug?

**Question (app.py:6824-6843, 00_ticket.md §3 C2)**: The brief acknowledges the explicit md5-filter path ("only via the explicit md5-filter operator path") where historical chunks intentionally feed the analyzer. The docstring calls this "safe because the operator explicitly named the version." Is it actually safe, or could an attacker / stale client pass a historical md5 pair to get stale-data analysis silently?

**Attempted answer**: The md5-filter path requires the caller to pass both `config_md5` and `code_md5` explicitly in the request body. In the single-item endpoint this comes from the frontend UI (user clicks on a historical-version row in the rawdata panel and explicitly requests a report from it). There is no automatic or background codepath that generates these params without operator intent. The `_prepare_batch_gen_item` batch path does NOT support md5-filter (no params for it, uses `usable = kept + deletable` not all-three). The UI would have to send an outdated md5 pair deliberately. This is a known intentional path (the "report 都是独立的" 2026-04-21 feature). The risk of silent reactivation is low — it requires explicit operator input. The docstring correctly calls it out as an explicit operator action.

**Verdict: ✓** — Exception path is intentional, operator-triggered, and not auto-activatable. The docstring documents it. Brief explicitly acknowledges it. Not a defect.

---

### SQ7 — Did the consumer grep miss any callers? Per `feedback_enumerate_safety_paths.md`: every path must be guarded.

**Question (02_implementation.md, app.py)**: The implementer ran grep for `_classify_chunks(` and found 7 call sites. Did the grep catch all variants (e.g., partial names, aliases, calls through a local variable)?

**Attempted answer**: I ran an independent grep for `_classify_chunks(` in `app.py` and found the same 7 call sites at lines ~1222, ~2176, ~2617, ~6060, ~6822, ~7225, ~8802. There are no imports of `_classify_chunks` from other modules (it's an app-internal function, defined and called within `app.py`). There is no `classify_chunks` alias or local rebind in the file. The implementer's count of 7 is accurate. However, one potential miss: the brief §3 C1 enumerated `_auto_cleanup_for_space:2455+` as the deletion consumer. The actual line in the current code is 2617, not 2455. Similarly, `delete_rawdata` is documented as "~line 1133" but the function signature is at 1130. These line drifts are ~minor (within the docstring's `~line` approximation notation), but the `_auto_cleanup_for_space` case is off by 162 lines, which is beyond approximation.

**Verdict: ⚠** — Consumer enumeration is exhaustively correct (7 callers, all found). Line references in the docstring are consistently off (`_auto_cleanup_for_space` is documented at ~2528 in the docstring at line 964, actual is ~2617). These ~89-line drifts will mislead reviewers looking up callers. Not a correctness defect in the contract sense, but the docstring's stated purpose is enabling "reviewers to verify" — stale line refs undermine that purpose.

---

### SQ8 — Test coverage of `_prepare_batch_gen_item` inject-bug: tester acknowledged a gap; is it acceptable?

**Question (03_tests.md §Open gaps, app.py:7209, _batch_gen_worker.py)**: Tester explicitly flagged that `_prepare_batch_gen_item` has no direct inject-bug test, saying it "would require reaching the batch-generate-reports endpoint with proper concurrency setup." Given that SQ4 finds this path actively passes historical chunks to the analyzer, is the tester's gap rationale still valid?

**Attempted answer**: SQ4 shows the gap is worse than the tester framed it. The tester believed `_prepare_batch_gen_item` was semantically analogous to `_run_generate_report` — both filter to `kept + deletable` — so structural coverage from `TestClassifyChunksBucketSeparation` was "sufficient." But the actual subprocess path (`--from-cache chunk_dir` with no md5 filter) reads everything from disk, bypassing the Python-level `usable` filter entirely. The tester's structural analogy was wrong. The gap is not merely an infrastructure inconvenience — it reflects a genuine coverage hole for a production code path that the docstring now incorrectly describes as historically-safe. The "requires concurrency setup" rationale doesn't apply to the key invariant here; an inject-bug test could monkeypatch the subprocess call or inspect the argv forwarded to the worker.

**Verdict: ✗** — The tester's acknowledged gap is more significant than characterized. Combined with SQ4 (docstring's false invariant), this gap means the C2 contract is inadequately tested for the batch execution path.

---

## Chain disagreements

### Disagreement 1: Line references across the chain

- **Brief** (00_ticket.md §3 C1): `_run_generate_report:6733`
- **Tester** (03_tests.md inject-bug log): "line 6845, inside the `else` branch"
- **Implementer docstring** (app.py:981): "~line 6733"
- **Actual code**: `def _run_generate_report(` at line 6789; `usable_entries = ...` at line 6845

The three documents reference three different lines for the same function. The implementer propagated the brief's wrong line reference into the docstring. The tester independently found the correct line. The docstring is the artifact that survives in production code.

### Disagreement 2: `_prepare_batch_gen_item` invariant description

- **Implementer docstring** (app.py:992-995): "historical chunks are NEVER included" in `_prepare_batch_gen_item`
- **Actual code** (`_batch_gen_worker.py:81`): `--from-cache str(job["chunk_dir"])` with no md5 filter — passes the whole directory to the analyzer

The implementer's survey correctly identified the in-process filter (`usable = kept + deletable`) but did not trace the subprocess path end-to-end to the `_batch_gen_worker.py` argv construction. The docstring's claim is false for the subprocess execution.

### Disagreement 3: C2 test scope vs. stated contract

- **Brief** (00_ticket.md §3 C2): "for any code path that calls `pia.main()` / `_run_generate_report()` / equivalent analyzer execution with a chunk list, the chunk list contains zero historical-bucket chunks"
- **Tester** (03_tests.md, test file): Tests only the `_run_generate_report` in-process path; batch path not tested; tester acknowledged this as an open gap
- **Actual code**: `_prepare_batch_gen_item` / `run_analyzer_job` is a second "equivalent analyzer execution" code path that the brief explicitly should have included

The brief's "any code path" language was broader than the tester's test coverage. This is a disagreement between brief and test, not a tester fault — but the verifier should have caught it (no `04_verification.md` to check).

---

## Hidden assumptions

1. **`--from-cache` filters by md5 when `--upstream-config-md5` is passed**: The `_run_generate_report` in-process path pre-filters the chunk list before passing it to the analyzer. The batch path relies on the DIRECTORY approach. The implicit assumption is that `--max-chunks` acts as a sufficient guard. It does not — `max_chunks` limits count, not md5-selectivity.

2. **The "~line N" docstring convention is useful**: The docstring's consumer enumeration uses approximate line numbers as navigation aids. But when lines drift 56-162 from actual values, they point to wrong code and mislead rather than help. The assumption that approximate line refs age gracefully is unsound.

3. **Tester's structural analogy (in-process filter = subprocess filter)**: The tester assumed `_prepare_batch_gen_item`'s `usable = kept + deletable` Python expression meant the subprocess received only those chunks. This conflates the Python-layer variable with the subprocess argv.

4. **The verifier would be running in parallel and their output would be available**: The verifier's `04_verification.md` does not exist. The critique was written without empirical verification of whether any tests actually pass in the real environment.

---

## Edge cases not covered

1. **Mixed-md5 directory, `max_chunks` equals the number of kept+deletable**: If `max_chunks = 5` and the directory has chunk_0001 (historical), chunk_0002 (kept), chunk_0003 (kept), chunk_0004 (deletable), chunk_0005 (deletable), the analyzer sorts by filename and reads chunk_0001 first — historical chunk consumed. `max_chunks=5` does not save this case.

2. **`_prepare_batch_gen_item` batch path with interleaved historical chunk indices**: Because chunks are named `chunk_NNNN.json` sequentially and historical chunks may have earlier indices than current chunks (they were sampled before the server update), the historical chunks may always sort first, making them the most likely to be consumed by the subprocess analyzer.

3. **No inject-bug test for `_enumerate_rawdata_deletable`**: While the function is provably read-only, the `feedback_enumerate_safety_paths.md` principle requires that every consumer path be asserted with a test. This function has no dedicated test.

4. **`delete_rawdata` with `force=True`**: The docstring enumerates `delete_rawdata` as using `deletable + historical`. But with `force=True` (line 1159), it uses `shutil.rmtree` on the entire target path — bypassing `_classify_chunks` entirely. The docstring's consumer entry for `delete_rawdata` doesn't mention the `force=True` bypass. A reviewer reading the docstring might conclude `_classify_chunks` is always in the loop for `delete_rawdata`.

5. **`get_rawdata_status` endpoint (line ~6060) calls both `check_rawdata_status` AND `_classify_chunks`**: The docstring lists `get_rawdata_status` as a display-only consumer. But it also calls `check_rawdata_status` immediately before (line 6057-6059), and both functions individually touch the disk. This dual-call is not noted in the consumer enumeration and means the "display-only" label applies to the combination, not the individual calls.

---

## Required revisions

### Revision R1 (blocks ship) — Correct `_prepare_batch_gen_item` docstring claim

**Points to SQ4 and Chain Disagreement 2.**

The docstring line 992-995 says "historical chunks are NEVER included" for `_prepare_batch_gen_item`. This is false. The implementer must:

- Read `_batch_gen_worker.py:76-103` to understand the `--from-cache chunk_dir` argv construction
- Determine whether this is a pre-existing behavioral gap or an intended design (the analyzer has `--upstream-config-md5` / `--upstream-code-md5` flags that would filter, but the worker doesn't forward them)
- If pre-existing gap: correct the docstring to describe actual behavior; flag the actual gap for a separate ticket
- If intended: explain why and document it explicitly

This must be flagged clearly to the implementer as a pre-existing code behavior that the docstring now incorrectly canonizes.

### Revision R2 (blocks ship) — Add C2 coverage for the batch path

**Points to SQ8 and Chain Disagreement 3.**

The tester's open gap on `_prepare_batch_gen_item` is not merely a convenience gap — the subprocess path has different semantics than the in-process path (no Python-layer md5 filter propagated to the analyzer). Brief §3 C2 says "for ANY code path that calls ... equivalent analyzer execution." The batch path is such a path.

At minimum, the tester must add a test that inspects the argv forwarded by `_prepare_batch_gen_item` to the worker — specifically, that `chunk_dir` does not include historical chunks OR that `--upstream-config-md5` / `--upstream-code-md5` are forwarded. This test is analogous to the `test_analyzer_e2e_md5_filter.py` pattern referenced in 03_tests.md.

### Revision R3 (non-blocking, before final commit) — Correct stale line references in docstring

**Points to SQ3 and SQ7.**

The docstring says `_run_generate_report` is at "~line 6733" (actual: 6789) and notes `_auto_cleanup_for_space` at "~line 2528" (actual: ~2617). The brief had the wrong line. The implementer copied it. The "~" approximation is intended to be helpful but is currently misleading by 56-162 lines. Before the final commit, the implementer should update the line refs to match the actual current lines (a trivial grep). Not blocking, but line refs are the docstring's primary navigation value.

### Revision R4 (non-blocking) — Note `force=True` bypass in `delete_rawdata` consumer entry

**Points to edge case 4.**

The `delete_rawdata` consumer entry should note that `force=True` bypasses `_classify_chunks` entirely and calls `shutil.rmtree`. Otherwise the docstring implies `_classify_chunks` is always in the loop for this consumer.

---

## Commit-message `## Self-critique` section

```
## Self-critique

- Q: Does the docstring's claim about `_prepare_batch_gen_item` hold for the
  subprocess (batch) path, not just the in-process filter?
  A: NO (OPEN). `_prepare_batch_gen_item` computes `usable = kept + deletable`
  in Python, but passes `chunk_dir` (whole mode directory) to the worker via
  `_batch_gen_worker.py:81` as `--from-cache`. The worker does not forward
  `--upstream-config-md5` / `--upstream-code-md5`, so the analyzer subprocess
  reads every chunk file in the directory, including historical ones. Docstring
  invariant claim "historical NEVER included" is false for the batch path.
  Required revision before ship: correct the docstring; add argv-inspection
  test for the batch path.

- Q: Are all 7 call sites covered by the consumer enumeration?
  A: Yes — independent grep confirmed same 7 sites. No aliases or partial-name
  calls exist. Consumer survey is exhaustive.

- Q: Is the spy mechanism in `test_run_generate_report_excludes_historical`
  actually operative?
  A: Yes — tester caught and fixed a list-membership bug in the initial spy.
  The corrected spy iterates `result.get("response", [])` and checks for
  `"_marker"` key presence. Inject-bug trace confirms it went RED on inject.

- Q: Do the line references in the docstring match actual code?
  A: No. `_run_generate_report` documented at "~6733", actual definition at
  6789 (usable_entries line at 6845). `_auto_cleanup_for_space` at "~2528",
  actual ~2617. All "~line N" refs are stale. Non-blocking but misleading.

- Q: Does C5's signature test block any future `auto_delete_*` revival?
  A: Yes — allowlist approach catches any-name parameter addition, not just
  `auto_delete_mismatched`.

- Q: Does `delete_rawdata` with `force=True` bypass `_classify_chunks`?
  A: Yes — `shutil.rmtree` path at line 1165 bypasses the classifier.
  Not noted in the consumer docstring. Non-blocking but worth documenting.

- Q: Is the C2 contract fully covered by the test suite?
  A: Partially. `_run_generate_report` (in-process path) is covered by
  inject-bug test. `_prepare_batch_gen_item` (batch/subprocess path) has
  NO inject-bug coverage and has a genuinely different execution model.
  Brief §3 C2 scope ("any code path ... equivalent analyzer execution")
  requires coverage of the batch path. Required revision before ship.

- Q: Is `04_verification.md` present?
  A: No — verifier ran in parallel; file not yet written at time of critique.
  Critique proceeds from direct code reading. Formally incomplete chain.
```

---

## Summary

| Area | Finding |
|---|---|
| Line 6845 production code | Correct — `classified["kept"] + classified["deletable"]` only in else branch |
| `check_rawdata_status` signature | Correct — no `auto_delete_*` parameter |
| Consumer enumeration count | Correct — 7 call sites, all identified |
| C5 test (signature guard) | Robust — allowlist approach |
| C2 test (`_run_generate_report`) | Correct and inject-bug verified |
| C2 test (`_prepare_batch_gen_item`) | Missing — batch path has different semantics, no coverage |
| Docstring `_prepare_batch_gen_item` invariant | FALSE — "historical NEVER included" does not hold for subprocess path |
| Docstring line refs | Stale — `_run_generate_report` off by 56 lines (pointing to different function) |
| `04_verification.md` | MISSING — chain formally incomplete |
| `delete_rawdata force=True` bypass | Undocumented in consumer entry |
