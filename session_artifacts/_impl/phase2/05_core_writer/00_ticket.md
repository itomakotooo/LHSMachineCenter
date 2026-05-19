# Ticket P2-B3 — Carve `analyzer/core/writer.py`

> Phase 2 / Wave 2b third carve. **LOW-MEDIUM risk**: small surface; the
> coupling to `main()`'s local variables is the only real risk and we
> minimize it by keeping `_save_chunk_cache` (self-contained) here and
> deferring the markdown-report generation to P2-B4 main() refactor.

---

## §1 Ticket scope

Two functions move out of `fresh_slotlab/player_impact_analyzer.py` (PIA)
into a new `fresh_slotlab/analyzer/core/writer.py`:

1. **`_save_chunk_cache`** (current PIA line 1370; ~65 lines)
   - Self-contained except for two calls: `_lookup_machine_md5(machine)`
     and `_rawdata_index_update_entry(...)`. Both stay in PIA (not in this
     ticket's scope; tracked separately).
   - Uses `_payload_sha256` and `_compute_upstream_schema_fingerprint`
     which already live in `core/parser.py` after P2-B1a. Re-imports
     from there.
   - Uses `CHUNK_CACHE_VERSION` and `utc_now()` from PIA. Keep imports of
     these via the parent module (it is OK for writer.py to depend on PIA
     for module-level constants if we cannot easily extract them).

2. **`write_summary_json`** — NEW thin helper extracted from PIA's
   `main()` line 5262-5263. Signature:
   ```python
   def write_summary_json(summary: dict, output_dir: Path) -> Path:
       out = output_dir / "player_impact_summary.json"
       out.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                      encoding="utf-8")
       return out
   ```
   This is a 2-line helper but isolating it makes future writers (per
   §6.2 deliverable "feature_<name>.py emit to writer") easier. Main()
   gets the same one-call delete in this ticket.

**Out of scope** (defer to P2-B4):
- The 200-line markdown report generation block in `main()` (lines
  5265-5466). Coupled to many local variables; cleanest extraction
  happens after `main()` itself is reshaped in P2-B4.
- `_lookup_machine_md5` — stays in PIA (callsite of `_save_chunk_cache`
  reaches into PIA's machines_config; isolated migration is its own
  task).
- `_rawdata_index_update_entry` — stays in PIA (callsite; isolated
  migration is its own task).

---

## §2 Brief sections cited

- `session_artifacts/_arch/04_architecture_proposal_v5.md §6.2 deliverable 1`
  — "Carve core/ (4 files)"; writer.py is the third.
- `session_artifacts/_impl/phase2/PHASE_2_TICKETS.md` Wave 2b row P2-B3 —
  "`_save_chunk_cache` + summary-write logic extracted from `main()`".
- Memory `feedback_subprocess_import_suicide_and_module_globals.md` —
  writer.py must be import-safe (no I/O at import).
- Memory `feedback_no_silent_swallow.md` — `_save_chunk_cache`'s existing
  bare `except` (line ~1465) for cleanup MUST be preserved exactly. Do
  NOT add new ones.
- Memory `feedback_md5_granularity_and_stamping.md` — the
  `override_config_md5` / `override_code_md5` path on `_save_chunk_cache`
  is the localcfg/virtual-analyzer stamp path; tests must verify both
  override and non-override paths still work.

---

## §3 Contract (testable invariants)

### C1 — Files exist + symbols carved
- `fresh_slotlab/analyzer/core/writer.py` present with
  `_save_chunk_cache` and `write_summary_json`.
- PIA re-exports `_save_chunk_cache` and `write_summary_json` via the
  existing dual-path import block, so external callers (the chunk
  sampler, batch worker subprocess) keep resolving via PIA.

### C2 — P1-A1 3-invocation parity canary stays GREEN
`tests/integration/test_analyzer_three_invocation_parity.py` 23/23
GREEN. The byte-identical summary path goes through `write_summary_json`
on all three invocations.

### C3 — `_save_chunk_cache` semantic preservation
- Atomic write semantics preserved: writes `chunk_NNNN.json.tmp`, then
  `os.replace` to final.
- `override_config_md5` / `override_code_md5` path still produces
  envelopes with the override values (not the global lookup) — preserved
  exactly per memory `feedback_md5_granularity_and_stamping.md`.
- `_rawdata_index_update_entry` post-write side effect still fires.

### C4 — Subprocess import safety
- `python -c "import fresh_slotlab.analyzer.core.writer"` rc=0 no stderr.

### C5 — Cycle freedom
- `fresh_slotlab/analyzer/core/writer.py` MUST NOT import from PIA
  (`fresh_slotlab.player_impact_analyzer`).
- writer.py MAY import from `core/parser.py` (`_payload_sha256`,
  `_compute_upstream_schema_fingerprint`).
- writer.py MAY import from `core/_utils.py` (if it needs any of the 9
  helpers; probably none).
- writer.py MAY import from `core/aggregator.py` (downstream of parser;
  unlikely to need anything but legal).

The PIA-side callsites of `_save_chunk_cache` and `write_summary_json`
will pass `_lookup_machine_md5` and `_rawdata_index_update_entry` as
function arguments rather than letting writer.py import them — to
avoid the wrong-direction writer → PIA dependency.

### C6 — Hash composition rolls forward
`compute_base_analyzer_version()` hashes `core/*.py`. Adding writer.py
flips the hash deterministically. (Test gated on the function being
exported through versioning.py; currently skipped per P2-B1b critic
note. Tracked separately.)

### C7 — All existing tests pass
- 7-suite Phase 1+2 regression set (P1-A1 canary, P1-B1, P1-A2, P2-A1,
  P2-A2, P2-B1a/B1b, P2-B2): 457+ tests GREEN.
- New `tests/backend/test_analyzer_core_writer.py`: ~30+ tests.

### C8 — Inject-bug TDD
- Inject: change `os.replace` to `os.rename` in writer.py → ... this
  produces a Windows-specific failure for cross-volume moves but is
  hard to catch without a mock. Skip this inject; use the next one
  instead.
- Inject: omit `_payload_sha256` from envelope → caller's later
  `load_chunk_envelope` integrity check goes RED. Test verifies the
  envelope round-trip.
- Inject: change `chunk_NNNN.json.tmp` suffix to `.tmp.tmp` → atomic
  write test (which counts files in cache_dir during write) catches
  the regression.

---

## §4 Out of scope

- The 200-line markdown report generation. P2-B4.
- `_lookup_machine_md5` carve. Separate ticket.
- `_rawdata_index_update_entry` carve. Separate ticket.
- HTTP layer. P2-B4.
- Frontend.
- Removing legacy `compute_analyzer_version`.

---

## §5 Rollback path

Single commit. `git revert <sha>` restores `_save_chunk_cache` and the
2 `write_summary_json` lines into PIA; deletes writer.py.

---

## §6 Risk + rollback notes

**Risk class**: LOW-MEDIUM.

1. **Atomicity preserved.** `_save_chunk_cache` uses tmp + os.replace.
   No regression to atomicity. Test: simulate a midway failure
   (KeyboardInterrupt or disk full), verify the `.tmp` file is cleaned
   up and the final file is never half-written.

2. **localcfg path.** `override_config_md5` / `override_code_md5` is the
   virtual-machine override path that segregates chunks into
   `localcfg_<hash>` buckets. Memory `feedback_md5_granularity_and_stamping.md`
   warns that breaking this stamps chunks with the wrong md5 and
   misroutes them. Test must cover both override and non-override paths.

3. **Callsite update.** `main()` calls `_save_chunk_cache` at PIA line
   ~1523. After carve, that call is `pia._save_chunk_cache(...)` via
   the re-export. Verify the parity canary catches any signature drift.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — create `fresh_slotlab/analyzer/core/writer.py`
  with `_save_chunk_cache` and `write_summary_json`. Delete originals
  from PIA. Add re-exports in PIA dual-path import block. Update PIA's
  `main()` line 5262-5263 to call `write_summary_json(summary,
  args.output_dir)` instead of the inline 2-liner. **Verify** the
  `_lookup_machine_md5` / `_rawdata_index_update_entry` call sites in
  `_save_chunk_cache` are passed in as arguments OR remain accessible
  by lazy import; do not introduce a writer → PIA cycle.

- `impl-tester` — write
  `tests/backend/test_analyzer_core_writer.py` covering C1-C8. Use
  tempdir fixtures for `_save_chunk_cache` round-trip; use inject-bug
  pattern for atomic-write + envelope-stamp tests.

### Wave 2 (parallel)
- `impl-verifier` — run full 7-suite regression + P1-A1 canary +
  subprocess smoke + cycle grep. Verify the `_save_chunk_cache`
  override path still works against a fixture chunk file.
- `impl-critic` — adversarial: was a cycle quietly introduced via the
  `_lookup_machine_md5` call inside `_save_chunk_cache`? Did the
  override-md5 path semantically drift? Was the `_rawdata_index_update_entry`
  best-effort cleanup preserved?

Expected wall time: ~50-80 min. Smaller than P2-B2 because writer's
surface is two functions, not 16.
