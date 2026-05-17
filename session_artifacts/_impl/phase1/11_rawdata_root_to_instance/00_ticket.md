# Ticket P1-B6 — `RAWDATA_ROOT` module global → instance attribute (Batch 1d)

> Phase 1 / Batch 1d. Largest Phase 1 ticket by blast radius (10 functional refs in app.py + 1 module declaration + multiple comment refs). High care required per the memory-flagged 2026-04-XX virtual-batch-targeting-real-tree incident.

---

## §1 Ticket scope

Migrate `RAWDATA_ROOT` from a module-level global to per-instance / per-call parameter. Code comment at [app.py:3769](src/web_console/backend/app.py:3769) already documents WHY: "Use the BatchRunManager's injected rawdata_root, not the module-level RAWDATA_ROOT global. Virtual console vs real console have different roots; hardcoding the global here made every virtual batch-run target the REAL console's rawdata/ tree."

Files expected to change:
- `src/web_console/backend/app.py` — multiple locations (see §3 path enumeration)
- `tests/backend/test_rawdata_root_split_path.py` (new) — split-path regression per memory `feedback_subprocess_import_suicide_and_module_globals.md`

---

## §2 Brief sections cited

- `session_artifacts/_arch/03_coupling_audit.md §4.1` — module-level globals inventory
- `session_artifacts/_arch/08_handoff.md §4 Phase 1` — RAWDATA_ROOT × 11 refs
- Memory `feedback_subprocess_import_suicide_and_module_globals.md` — instance-attr migration discipline + split-path regression
- Memory `feedback_enumerate_safety_paths.md` — every ref must be verified; tests must exercise every path with inject-bug
- App.py:3769 comment block (in-source documentation of the bug)

---

## §3 Contract (testable invariants)

### C1 — Path enumeration (10 functional refs + 1 declaration)
Confirmed via grep:
- Line 49: `RAWDATA_ROOT_DEFAULT` declaration (comment) — keep as constant default
- Line 165: subprocess env injection `env["SLOT_RAWDATA_ROOT"] = str(rawdata_root)` — **safe as-is** (passes the injected param to child)
- Line 518: `RAWDATA_ROOT = Path(os.getenv("SLOT_RAWDATA_ROOT", str(RAWDATA_ROOT_DEFAULT)))` — **module-level declaration**; keep as backward-compat default OR delete + force all callers to pass param
- Line 695: `root = rawdata_root if rawdata_root is not None else RAWDATA_ROOT` — fallback pattern
- Line 1064: same fallback
- Line 3187: same fallback
- **Line 3259: `check_rawdata_status` reads global RAWDATA_ROOT directly (no fallback) — REAL PROD BUG** surfaced by P1-A1 round-2 critic. This is exactly the failure pattern memory `feedback_subprocess_import_suicide_and_module_globals.md` warns about. This ticket MUST migrate this ref and add a regression test.
- Line 4805: comment + use of RAWDATA_ROOT at runtime — verify usage
- Line 5318: same fallback
- Line 7489: `RAWDATA_ROOT` direct usage (no fallback flag); verify whether `rawdata_root` should be threaded through
- Line 8735: comment
- Line 8776: docstring or comment

For each functional usage: replace with `self._rawdata_root` (if inside `BatchRunManager` / `RunManager`) or take `rawdata_root: Path` as a parameter (if free function called from request handler with request context).

### C2 — Split-path regression test
Per memory `feedback_subprocess_import_suicide_and_module_globals.md`: test monkeypatches `RAWDATA_ROOT` to a wrong value (e.g., `/tmp/wrong`) → asserts `BatchRunManager` / virtual paths still use injected root (the right one), not the global. If the test passes both before AND after the migration, the test isn't actually testing the migration — flag.

### C3 — Per-path inject-bug verification
Per memory `feedback_enumerate_safety_paths.md`: tester writes one inject-bug experiment per migrated ref:
- For each call site, temporarily revert just that ref → assert the split-path regression test goes red on that path → restore → green
- Documented in `03_tests.md` as a table

### C4 — Virtual console subprocess smoke
Per memory `feedback_subprocess_import_suicide_and_module_globals.md` + `feedback_perf_claim_needs_e2e_event_stream.md`: impl-verifier spawns virtual_app + runs a sample batch + verifies the rawdata writes land in `VIRTUAL_RAWDATA_ROOT` (not the real `RAWDATA_ROOT`). This was the original 2026-04-XX failure mode; regression-test it directly.

### C5 — `_recover_orphan_running_runs` safety
Per memory: the original suicide bug was `_recover_orphan_running_runs` reading wrong rawdata root + killing self. Test asserts this function uses the injected root, not the global.

### C6 — Module-level RAWDATA_ROOT deletion vs preservation
**Decision required by implementer**: keep `RAWDATA_ROOT` at line 518 as a backward-compat default, OR delete it entirely (forcing all callers to pass param). Recommendation: KEEP for env-var-based default initialization, but ensure no functional code path reads it directly anymore — only used at module-init for setting `RawdataRootRegistry.DEFAULT` or similar. Document in `02_implementation.md`.

---

## §4 Out of scope

- Migrating other module globals (P1-C1 covers `_MACHINES_SUMMARY_CACHE`, `_RAWDATA_OVERVIEW_CACHE`, etc.)
- Refactoring `BatchRunManager` / `RunManager` interfaces beyond adding `_rawdata_root`
- Changing `SLOT_RAWDATA_ROOT` env var contract (still used at module init + subprocess env injection)
- Adding a registry pattern for multiple-root support (single virtual + real root suffices)

---

## §5 Rollback path

Single commit. `git revert <sha>` restores module-global reads.

---

## §6 Risk + rollback notes

**Risk class**: MEDIUM. Multi-ref migration; easy to miss a path. Past incident (2026-04-XX virtual-batch-targeting-real) was caused by exactly this pattern; high vigilance required.

**Dependency**: none functional but recommended AFTER Batch 1c dedups (so concurrent edits don't conflict).

**Critic must verify**: every functional ref in §3 C1 was migrated; split-path regression test (§3 C2) genuinely goes red when injected; virtual console subprocess smoke (§3 C4) actually exercises a real batch.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — migrates each ref per §3 C1; runs touched-module pytest
- `impl-tester` — writes split-path regression + per-path inject-bug table per §3 C3

### Wave 2 (parallel)
- `impl-verifier` — spawns virtual_app subprocess + verifies rawdata writes land in correct root per §3 C4; runs full pytest; verifies `_recover_orphan_running_runs` test (§3 C5)
- `impl-critic` — checks: every ref in §3 C1 migrated? Split-path regression genuinely catches each migration (per-path)? Module-level RAWDATA_ROOT decision per §3 C6 justified?

Expected wall time: ~60-90 min (largest Phase 1 ticket).
