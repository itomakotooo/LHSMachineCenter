# 05_critique.md — Ticket P1-B1: Consolidate `_lookup_machine_md5` (real × 2)

**Verdict: APPROVE-WITH-REVISIONS**

---

## Chain read summary

| Artifact | Present | State |
|---|---|---|
| `00_ticket.md` | YES | Brief is complete, 6 contracts (C1–C6) well-specified |
| `02_implementation.md` | YES | Implementer self-marks PASS |
| `03_tests.md` | YES | Tester self-marks partial; 2 RED at authorship time |
| `04_verification.md` | **MISSING** | impl-verifier never filed — critical process gap |

**The chain is incomplete.** `04_verification.md` does not exist for this ticket. The implementer claims 69/69 tests GREEN after completion, but no independent verifier confirmed this. Per `docs/IMPL_TEAM_PROCESS.md`, W2 requires both impl-verifier and impl-critic to run in parallel; the critic cannot substitute for the verifier.

---

## Stress questions (10 questions)

---

### Q1 — Import-alias monkeypatch: does `monkeypatch.setattr(pia, "_lookup_machine_md5", sentinel)` actually intercept the call at `_save_chunk_cache` line 2193?

**Scenario**: The import is `from fresh_slotlab.machine_md5 import lookup_machine_md5 as _lookup_machine_md5` at `pia.py:61`. This binds `pia._lookup_machine_md5` to the canonical function object. When `monkeypatch.setattr(pia, "_lookup_machine_md5", sentinel)` is called, it replaces the name in `pia`'s module `__dict__`. The call site `_lookup_machine_md5(machine)` at line 2193 resolves through the module global dict — which is now `sentinel`. This IS correct.

**However**: the P1-A2 parity test at `test_summary_md5_writer_parity.py:320` also monkeypatches `pia._lookup_machine_md5`. After the dedup, `pia._lookup_machine_md5` resolves through the module-level alias. Monkeypatching replaces the alias — the call site at line 2193 picks up the patched value. This is the intended behavior and the implementer's decision 2 correctly describes it.

**Attempted answer**: YES — the pattern works because Python function calls via global name lookup always go through the module `__dict__` at call time. `monkeypatch.setattr` mutates `pia.__dict__["_lookup_machine_md5"]`. The claim in `02_implementation.md §2` is mechanically correct.

**Verdict**: PARTIAL — the claim is correct, but `04_verification.md` (which would have run the split-path test live) is missing. The implementer says 30/30 parity tests pass; this is unverified by an independent party.

---

### Q2 — `_REPO_ROOT` computed at module load time: is `Path(__file__).resolve()` a side effect?

**Scenario**: `machine_md5.py:47–48` executes `Path(__file__).resolve().parent.parent` at module top, storing the result in `_REPO_ROOT` and `_DEFAULT_MACHINES_CONFIG`. This is module-level code that runs on every import.

`Path(__file__).resolve()` on CPython calls `os.path.realpath`, which on Windows triggers one or more `GetFullPathNameW` / `NtQueryObject` syscalls to resolve symlinks. It does NOT read machine content, open file handles, or touch the filesystem beyond a stat-like operation for symlink resolution.

The AST test `TestImportSmoke::test_machine_md5_has_no_module_top_code_beyond_imports_and_defs` allows `ast.Assign` at module top — and `_REPO_ROOT = Path(...).resolve().parent.parent` is an `Assign` node. So the test passes. But the subprocess test `test_import_machine_md5_is_side_effect_free` would also pass because there is no stdout/stderr produced.

**The deeper concern**: is `Path(__file__).resolve()` at import time safe in a subprocess that might be chrooted, move its CWD, or be running from a zip? On this Windows-based internal deployment, yes — `__file__` is always the real `.py` path. The concern is theoretical.

**More important gap**: `_DEFAULT_MACHINES_CONFIG` is computed once at import time. If `machine_md5.py` is imported in a context where the real path of `__file__` leads to a different parent (e.g., the module is installed to a site-packages, or run from a packaged zip), `_DEFAULT_MACHINES_CONFIG` would point to the wrong directory. The callers in `_save_chunk_cache` use the default (no explicit path), so they silently get `("", "")` in that edge case instead of raising. However, the brief explicitly says "returns `("", "")` on any error — MD5 tagging is best-effort" so this is within contract.

**Verdict**: PARTIAL — `Path(__file__).resolve()` at module top is not I/O in the problematic sense (no file reads, no writes, no network). The import-suicide test passes. But the `_DEFAULT_MACHINES_CONFIG` path is fixed at import time and no test exercises the edge case where the module's `__file__` resolves to the wrong parent. This is a hidden assumption, not a defect — LOW severity.

---

### Q3 — `except Exception:` in `_get_machine_md5` (app.py:597): is this a swallowed error?

**Scenario**: The rewritten `_get_machine_md5` in `app.py:597` catches `except Exception: return "", ""` around the `read_json` call in the `mode is not None` branch. Per memory `feedback_dont_swallow_errors_in_fix.md`: does this hide bugs?

**Actual text** (`app.py:597`): `except Exception: return "", ""` — this is inside the `if mode is not None` branch, wrapping only the `modesMd5` lookup path. If `read_json` raises (file not found, bad JSON), the function returns `("", "")`.

**Comparison to canonical**: `machine_md5.py:95` uses `except (OSError, json.JSONDecodeError, TypeError)` — an explicit list. The app.py wrapper uses `except Exception` which is broader and would swallow e.g. `MemoryError`, `AttributeError` from a type bug, `KeyError` from an unexpected schema.

**Is this new behavior introduced by this diff, or pre-existing?** The implementer rewrote this function — so the `except Exception` is part of the diff. The original `_get_machine_md5` in app.py had a similar broad catch (implementer's `02_implementation.md` says the `break` statement was introduced, but the except clause was part of the rewrite). If the original had `except (OSError, json.JSONDecodeError, TypeError)` like the canonical, the rewrite widened it.

**Verdict**: DEFECT — `except Exception` in `_get_machine_md5:597` is broader than the canonical's `except (OSError, json.JSONDecodeError, TypeError)`. If a type bug exists in the modesMd5 dispatch logic (e.g., `str(int(mode))` raises because `mode` is some unexpected type), the error is silently swallowed and `("", "")` is returned. This does not match the narrow guard in the canonical. Tests do not cover this path.

---

### Q4 — `batch_dev_sampler.py` imports `_lookup_machine_md5` from `player_impact_analyzer`: is this truly self-healing?

**Scenario**: `batch_dev_sampler.py:43,54` imports `_lookup_machine_md5` from `player_impact_analyzer`. After the dedup, `pia._lookup_machine_md5` is the canonical function (imported under that name). So `batch_dev_sampler` gets the canonical transitively.

**The hidden risk**: `batch_dev_sampler.py` is also invoked as a standalone script. Its `except ImportError` branch at line 46 tries `from player_impact_analyzer import _lookup_machine_md5`. After the dedup, `player_impact_analyzer.py` in standalone mode (except branch at line 84) imports: `from machine_md5 import lookup_machine_md5 as _lookup_machine_md5`. So in standalone PIA, `_lookup_machine_md5` is bound. `batch_dev_sampler.py`'s standalone branch then tries `from player_impact_analyzer import _lookup_machine_md5` — which imports PIA's module namespace, which has `_lookup_machine_md5` as an attribute (the alias). This works.

**BUT**: the implementer lists this as "open issue 1" and notes it as out of scope. The implementer says `batch_dev_sampler.py` "continues to work without modification — it gets the canonical implementation transitively." This is true, but:

1. `batch_dev_sampler.py` is a **third callsite** that reads md5 by importing from PIA. Brief §1 says "Both callsites import" — meaning `app.py` and `pia.py`. The brief's C2 test only checks the two named callsites. C1's grep does not scan `batch_dev_sampler.py` because the grep is for `def _lookup_machine_md5`, not for consumers. So `batch_dev_sampler.py` is NOT a definition site and NOT flagged by C1/C2. It is a consumer that gets the canonical transitively.
2. Per memory `feedback_enumerate_safety_paths.md`: "must grep every ... path." The C1 grep covers definition sites. But no test asserts that `batch_dev_sampler._lookup_machine_md5 is machine_md5.lookup_machine_md5` (identity check). If someone later re-defines `_lookup_machine_md5` in `pia.py`, `batch_dev_sampler.py` gets the PIA-local one (which is now canonical anyway) — so it still works.
3. The real gap: if monkeypatching `pia._lookup_machine_md5` is needed to control `batch_dev_sampler.py`'s behavior in tests, that still works because `batch_dev_sampler` imports from PIA and PIA's module dict is what gets patched.

**Verdict**: PARTIAL — the transitive chain is correct. The gap is documentation: brief §1 lists two callsites, but there is a third consumer (`batch_dev_sampler.py`). The brief's C2 tests do not assert on this third consumer, and the implementer's "open issue 1" defers it without noting the transitive correctness was verified by tracing the import chain (not by a test).

---

### Q5 — `_get_machine_md5` reads the JSON twice when `mode is not None`: once in the mode branch (via `read_json`) and once in the fallback (via `lookup_machine_md5` which calls `json.loads(cfg_path.read_text(...))`). Is this a regression from the original?

**Scenario**: The rewritten `_get_machine_md5` (app.py:576-601) for a real machine with `mode=1` that has no `modesMd5`:
1. Enters `if mode is not None` (line 576)
2. Calls `read_json(target)` (line 583) — file read #1
3. Finds the machine, sees `modesMd5` is empty, `break`s
4. Falls through to `return lookup_machine_md5(machine, target)` (line 601)
5. `lookup_machine_md5` calls `cfg_path.read_text(...)` (line 88 of machine_md5.py) — file read #2

For real machines (no modesMd5), every call to `_get_machine_md5` with `mode != None` now reads `machines.json` twice. The original code before the dedup read it once (it had its own inline loop that both dispatched modesMd5 and fell back in one pass).

**How often is `_get_machine_md5` called?** Per the grep: 8+ callsites in `app.py`. Most are in per-request handlers (not batch loops). `machines.json` is a small JSON file (~50KB estimated). The double read is at most a few milliseconds per call and not in any hot loop. This is not a production performance problem.

**BUT**: it is a behavioral regression relative to the pre-dedup implementation that the implementer does not document. The `02_implementation.md` does not mention the double-read, and no test asserts that `machines.json` is read only once per call. The `03_tests.md` does not cover this.

**Verdict**: PARTIAL — double file read for real machines with explicit `mode=` argument is a behavioral regression from the original, not documented, and not tested. For this codebase (small file, low-frequency calls) it's not a production issue, but it is a hidden change in behavior.

---

### Q6 — `read_json` in `_get_machine_md5` is app.py-internal: does it behave differently from `json.loads(path.read_text(...))` in `machine_md5.py`?

**Scenario**: `app.py:1836–1837` — `read_json` is `return json.loads(path.read_text(encoding="utf-8"))`. On a missing file, this raises `FileNotFoundError` (subclass of `OSError`). This is caught by `except Exception` at `app.py:597`.

In `machine_md5.py:86–88`, the function first calls `cfg_path.exists()` and returns `("", "")` if absent, then calls `cfg_path.read_text(...)`. So:
- canonical: checks existence explicitly, no exception for missing file
- app.py wrapper: does NOT check existence before `read_json`, relies on `except Exception` to catch `FileNotFoundError`

Behavioral difference: if `target.exists()` is False when `mode is not None`, the canonical path (for the mode branch) follows `if not target.exists(): return "", ""` (line 580-581). So the existence check IS there in the mode branch. Then the canonical fallback `lookup_machine_md5(machine, target)` checks existence again (line 86). So for the mode branch, existence is checked once by the wrapper and once by the canonical. Minor redundancy, not a defect.

**Verdict**: ADEQUATELY ADDRESSED — the existence check at line 580 gates the `read_json` call. The `except Exception` at 597 is belt-and-suspenders. Not a correctness issue.

---

### Q7 — `_lookup_machine_md5(machine)` is called with ONE argument at `pia.py:2193` and `batch_dev_sampler.py:176`, but the canonical `lookup_machine_md5` has signature `(machine, machines_config_path=None)`. Does the alias work correctly as a one-arg call?

**Scenario**: `pia._lookup_machine_md5` is `lookup_machine_md5` with `machines_config_path` defaulting to `None`. Calling `_lookup_machine_md5(machine)` passes only `machine`; `machines_config_path=None` triggers the `_DEFAULT_MACHINES_CONFIG` path.

`_DEFAULT_MACHINES_CONFIG` is computed at `machine_md5.py:48` as `Path(__file__).resolve().parent.parent / "configs" / "machines.json"` — which points to the repo root's `configs/machines.json`. This is the same file the original `_lookup_machine_md5` in `pia.py` was reading (it had `_CONFIG_ROOT = Path(__file__).resolve().parent.parent` or similar).

**Verified?** The P1-A2 test at `test_summary_md5_writer_parity.py:163` calls `pia._lookup_machine_md5("M14")` with one arg and asserts a non-empty result. If `_DEFAULT_MACHINES_CONFIG` pointed to the wrong file, this test would return `("", "")` and fail. Since the implementer claims 30/30, this path is implicitly tested.

**Verdict**: PARTIAL — the one-arg signature compatibility is tested indirectly by P1-A2. The `_DEFAULT_MACHINES_CONFIG` derivation from `__file__` was not independently verified by a verifier (no `04_verification.md`).

---

### Q8 — The `04_verification.md` is absent: what contracts did the verifier actually run?

**Scenario**: Per the process, `impl-verifier` runs W2 in parallel with `impl-critic`. The verifier should have: (1) confirmed 39/39 canonical tests GREEN, (2) confirmed 30/30 P1-A2 parity tests GREEN, (3) spawned the full analyzer subprocess to verify clean import, (4) confirmed the 2 "intentionally RED" tests from tester's time are now GREEN.

**Finding**: `session_artifacts/_impl/phase1/07_lookup_machine_md5_dedup/04_verification.md` does not exist. Only three files exist: `00_ticket.md`, `02_implementation.md`, `03_tests.md`.

The implementer's `02_implementation.md` includes a pytest summary (69/69, 2244+22+2xfail across full suite), but this is self-reported. The tester's `03_tests.md` explicitly defers the "30/30 parity suite" and "analyzer subprocess spawn" to impl-verifier.

**Verdict**: NOT ADDRESSED — the chain is structurally incomplete. The verifier's independent confirmation is missing. The two contracts deferred by the tester to verifier (C5 parity suite, subprocess spawn) remain unconfirmed by any independent party.

---

### Q9 — The C2 test `test_no_local_lookup_machine_md5_in_app` checks for `_lookup_machine_md5` in app.py but NOT for whether `_get_machine_md5` body duplicates the machines.json read logic locally. Does the test actually enforce the delegation contract?

**Scenario**: Brief §3 C2 says "app.py:548-591 body is `from fresh_slotlab.machine_md5 import lookup_machine_md5` (or thin wrapper if signature must change)." The test checks that no function named `_lookup_machine_md5` exists in app.py (correct — that was PIA's name, app.py used `_get_machine_md5`). The test also checks that "machine_md5" appears in app.py source text (correct — the lazy import is there).

But the test does NOT assert that `_get_machine_md5`'s body calls `lookup_machine_md5` from canonical. A malicious or careless implementer could: (a) keep the old inline loop in `_get_machine_md5` and also add an unused `import machine_md5` statement — the text check passes, the delegation contract is violated. The C2 tests do not distinguish between "imports and uses canonical" vs "imports but still duplicates inline."

**Implementer's actual code**: the flat-schema fallback at `app.py:601` is `return lookup_machine_md5(machine, target)`. This IS genuine delegation. But the test does not verify it.

**Verdict**: PARTIAL — C2 test is structural (text search) not behavioral. The tester documented this trade-off in `03_tests.md`: "The wrapper's delegation is confirmed by the implementer's code; impl-verifier will confirm via full pytest run." Since `04_verification.md` is absent, this confirmation is missing.

---

### Q10 — `_get_machine_md5` is called at `app.py:2939` as `_get_machine_md5(machine, mode=mode)` — no `machines_config` arg. In the rewritten function, `target = machines_config if machines_config is not None else MACHINES_CONFIG` (line 575). So it falls back to the module-level `MACHINES_CONFIG = ROOT / "configs" / "machines.json"`. Is this the same file `lookup_machine_md5` uses by default?

**Scenario**: `app.py:63` sets `ROOT = Path(__file__).resolve().parent.parent.parent` (or similar). `MACHINES_CONFIG = ROOT / "configs" / "machines.json"`. The canonical `machine_md5.py:47–48` sets `_REPO_ROOT = Path(__file__).resolve().parent.parent` and `_DEFAULT_MACHINES_CONFIG = _REPO_ROOT / "configs" / "machines.json"`.

For these to be the same file: `app.py`'s `ROOT` must equal `machine_md5.py`'s `_REPO_ROOT`.

`app.py` is at `src/web_console/backend/app.py` → `__file__.parent.parent.parent` = `src/web_console/backend/../../../` = repo root.
`machine_md5.py` is at `fresh_slotlab/machine_md5.py` → `__file__.parent.parent` = `fresh_slotlab/../` = repo root.

**Both resolve to repo root. They are the same file.** This is correct.

**BUT**: when `_get_machine_md5` is called with `mode=mode` and no `machines_config`, the mode branch reads `target = MACHINES_CONFIG` (app.py module-level constant) with `read_json`, and if the machine has no modesMd5 (real machine), falls through to `lookup_machine_md5(machine, MACHINES_CONFIG)`. The canonical also resolves to the same file via `_DEFAULT_MACHINES_CONFIG`. So the double-read path (Q5) reads the same file twice. Correct but redundant.

**Verdict**: ADEQUATELY ADDRESSED — the two path constants point to the same file. No correctness issue, double-read is noted in Q5.

---

## Disagreements: implementer ↔ tester ↔ verifier

### Disagreement 1 (critical): Tester deferred; verifier absent

`03_tests.md §Deferred to impl-verifier` explicitly lists: "Full pytest test_summary_md5_writer_parity.py run (C5)" and "Subprocess spawn of full analyzer (§6)." These are substantive contract checks, not cosmetic. The verifier never filed `04_verification.md`. The implementer self-reports 69/69 in `02_implementation.md`, but self-reporting is exactly what impl-verifier exists to check independently.

### Disagreement 2: Tester's "2 intentionally RED tests" claim vs implementer's "39/39 passed"

`03_tests.md` at authorship says 37/39 passed, 2 RED. `02_implementation.md` says 39/39 passed. This is a coordination point that only the verifier could confirm independently. The tester explicitly says "these 2 RED tests will go GREEN once the implementer completes the dedup." Since `04_verification.md` is missing, we cannot confirm from an independent source that 39/39 is actually the current state.

### Disagreement 3: C2 enforcement scope

`02_implementation.md` claims "C2 — both callsites delegate — PASS / AST: no `def _lookup_machine_md5` in `pia.py`." But the tester's C2 tests do not verify that `_get_machine_md5`'s body delegates (only that the name `machine_md5` appears in `app.py`). The implementer treats "calls canonical" as passing C2; the tester's test does not enforce that behavioral contract.

---

## Hidden assumptions

1. **`_DEFAULT_MACHINES_CONFIG` resolved correctly in all invocation contexts**: the path is fixed at import time based on `__file__`. On a Windows worktree (which this is, per git status), symlinks are generally not used so `resolve()` is safe. But if `machine_md5.py` is ever deployed to a context where `__file__` doesn't resolve to the repo tree (e.g., installed via `pip install -e .` with a differently-structured namespace), the default path silently fails and returns `("", "")`. No test covers this.

2. **`batch_dev_sampler.py` gets canonical transitively**: documented by implementer as "open issue 1" but the transitive chain has not been verified by a test (no `assert sampler._lookup_machine_md5 is machine_md5.lookup_machine_md5`).

3. **`test_per_mode_md5.py` tests still pass**: `slot_designer/tests/test_per_mode_md5.py` tests `_get_machine_md5` behavior for virtual machines with `modesMd5`. The rewrite of `_get_machine_md5` changes the structure of that function. The implementer's `02_implementation.md` does not mention whether `test_per_mode_md5.py` was run and confirmed green. These tests are in `slot_designer/tests/` not `tests/backend/`, so they may not have been included in the implementer's "full backend test suite" run.

4. **`except Exception` is pre-existing in app.py style**: the implementer uses `except Exception` at `app.py:597` consistent with other app.py broad catches (grep shows `except Exception` at lines 192, 406, 597, 731, 751...). The assumption is that the broad catch is house style. But the canonical uses a narrow except. Inconsistency between canonical and wrapper is a hidden divergence.

---

## Edge cases not covered by tests

1. **`_get_machine_md5` called with `mode=None` and machine not in JSON**: falls through to `lookup_machine_md5(machine, target)` which returns `("", "")`. Not explicitly tested by the new tests (though `TestC3::test_canonical_returns_empty_tuple_for_unknown_machine` covers the canonical, not the wrapper).

2. **`_get_machine_md5` called with `mode=1` and machine not in JSON**: enters mode branch, iterates `data.get("machines", [])`, finds no matching machine, loop exits without `break`, falls through to `lookup_machine_md5(machine, target)` which returns `("", "")`. This path is NOT exercised by the new tests.

3. **`_get_machine_md5` called with `mode=1` and machine has modesMd5 but the value is a non-dict** (e.g., `modesMd5: {"1": "string"}`): `isinstance(per_mode, dict)` is False, so it `break`s and falls through to flat-schema. Correct behavior, not tested.

4. **`batch_dev_sampler.py` in standalone script mode (`except ImportError` branch)**: imports `_lookup_machine_md5` from `player_impact_analyzer`. In standalone mode, PIA's except-ImportError branch imports `from machine_md5 import lookup_machine_md5 as _lookup_machine_md5`. Then sampler's except-ImportError branch imports from `player_impact_analyzer` — which is already loaded in the process (PIA itself is the script), so this works. But no test exercises `batch_dev_sampler.py` in standalone subprocess mode with the new import chain.

5. **Test fixture `_EXPECTED_MD5` snapshot values**: these are hardcoded strings from `configs/machines.json` at time of test authorship. If machines.json is updated (machine firmware upgrade bumps md5), the snapshot tests will fail with a misleading "wrong value" error, not a "machines.json changed" diagnostic. This is inherent to snapshot tests, not a new defect, but is worth noting.

6. **`test_backend_lookup_falls_back_when_mode_unknown` (slot_designer/tests)** tests `_get_machine_md5("M1sim", VIRTUAL_MACHINES_CONFIG, mode=99)` and expects it to return `entry["configSummaryMd5"]`. In the rewritten wrapper, this path: finds machine, `modesMd5.get("99")` is `None`, so `per_mode` is `None`, `isinstance(None, dict)` is False, `break`s, calls `lookup_machine_md5("M1sim", VIRTUAL_MACHINES_CONFIG)`. `lookup_machine_md5` reads `VIRTUAL_MACHINES_CONFIG` looking for `configSummaryMd5` at flat level. If `M1sim` in the virtual registry has a flat-level `configSummaryMd5`, this returns it — matching the test expectation. **This is implicitly tested but the verifier never confirmed `test_per_mode_md5.py` still passes with the rewritten function.**

---

## Required revisions

This is an APPROVE-WITH-REVISIONS verdict. The following must be addressed before this ticket can be closed:

### R1 (blocking — process): File `04_verification.md`

The verifier must run independently and produce `04_verification.md` confirming:
- 39/39 canonical tests pass (the 2 tester-intentional-RED are now GREEN)
- 30/30 P1-A2 parity tests pass
- `slot_designer/tests/test_per_mode_md5.py` passes (confirms `_get_machine_md5` rewrite didn't break virtual-machine behavior)
- Analyzer subprocess spawned cleanly (brief §6)
- Linked from stress question Q8.

### R2 (defect — error handling): Narrow `except Exception` in `_get_machine_md5:597`

The `except Exception` at `app.py:597` is broader than the canonical's `except (OSError, json.JSONDecodeError, TypeError)`. Change to match canonical's narrow guard or document why `Exception` is intentional (e.g., a separate try/except for `AttributeError` from modesMd5 schema drift).
Linked from stress question Q3.

### R3 (documentation — open issue): Third callsite in `batch_dev_sampler.py`

The implementer's "open issue 1" describes `batch_dev_sampler.py` as getting the canonical transitively. This should be documented in the ticket as an out-of-scope deferred item with a note that transitive correctness was confirmed by tracing the import chain. Currently the note says "correct behavior" but doesn't document the chain. A follow-up ticket should migrate `batch_dev_sampler.py` to import directly from `machine_md5` for clarity (per `feedback_no_parallel_panel_impl.md`'s "prefer explicit reuse").
Linked from stress question Q4.

---

## Commit-message `## Self-critique` section

(Paste-ready for the commit body)

```
## Self-critique

- Q: Does `monkeypatch.setattr(pia, "_lookup_machine_md5", sentinel)` still intercept
  the call at `_save_chunk_cache:2193` after the import-alias change?
  A: Yes — Python resolves global names through the module `__dict__` at call time;
  monkeypatch replaces the dict entry. P1-A2 split-path test exercises this path.
  Status: addressed by implementation decision 2 + P1-A2 test, OPEN pending verifier.

- Q: Is `Path(__file__).resolve()` at module top a side effect violating the import-safety contract?
  A: Not in the problematic sense — no file content read, no network, no subprocess.
  `_REPO_ROOT` / `_DEFAULT_MACHINES_CONFIG` are path computations only. AST test
  permits `Assign` at module top; subprocess smoke test passes with no stdout/stderr.
  Status: addressed.

- Q: Does `except Exception` at `app.py:597` swallow bugs in the modesMd5 dispatch?
  A: Yes — it is broader than the canonical's `except (OSError, json.JSONDecodeError, TypeError)`.
  A type bug (e.g., `str(int(mode))` raising on unexpected mode type) would be silenced.
  Status: OPEN — requires narrowing to match canonical or explicit justification.

- Q: Is `batch_dev_sampler.py` a missed third callsite per `feedback_enumerate_safety_paths.md`?
  A: It is a consumer (not a definer) — C1 grep scans for `def _lookup_machine_md5`, not imports.
  `sampler.py` gets canonical transitively through `pia._lookup_machine_md5`. Transitive
  chain is correct but documented only in open issue 1, not tested directly.
  Status: OPEN — deferred follow-up ticket.

- Q: Does the double JSON read in `_get_machine_md5` for real machines with `mode=` break anything?
  A: No correctness issue. For `mode is not None` + no modesMd5: reads machines.json via
  `read_json` (mode branch), then reads again via `lookup_machine_md5` (flat fallback).
  Two reads of a small file, not in a hot loop. Not a production concern.
  Status: documented behavioral change, not a defect.

- Q: Does `test_per_mode_md5.py` (virtual machine modesMd5 dispatch) still pass?
  A: Not independently confirmed — impl-verifier did not file `04_verification.md`.
  The rewrite of `_get_machine_md5` changes the mode-dispatch logic path.
  Status: OPEN — verifier must confirm.

- Q: Is `04_verification.md` missing?
  A: Yes — the verifier step was not completed. Chain is structurally incomplete.
  Status: OPEN — required before merge.
```

---

## Summary table

| Stress Q | Question | Verdict |
|---|---|---|
| Q1 | Import-alias monkeypatch propagation to `_save_chunk_cache` | PARTIAL (verifier absent) |
| Q2 | `Path(__file__).resolve()` at module top — import side effect? | PARTIAL (acceptable, edge case noted) |
| Q3 | `except Exception` in `_get_machine_md5` swallows type bugs | DEFECT |
| Q4 | `batch_dev_sampler.py` third callsite missed | PARTIAL (transitive correct, untested) |
| Q5 | Double JSON read for real machines with `mode=` argument | PARTIAL (documented, not a defect) |
| Q6 | `read_json` vs `json.loads(read_text(...))` behavioral parity | ADEQUATELY ADDRESSED |
| Q7 | One-arg call to aliased canonical: signature compatibility | PARTIAL (indirect test only, verifier absent) |
| Q8 | `04_verification.md` absent — verifier never confirmed | NOT ADDRESSED |
| Q9 | C2 test does not enforce behavioral delegation (only text search) | PARTIAL |
| Q10 | `MACHINES_CONFIG` vs `_DEFAULT_MACHINES_CONFIG` pointing to same file | ADEQUATELY ADDRESSED |
