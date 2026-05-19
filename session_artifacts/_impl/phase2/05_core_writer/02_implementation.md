# P2-B3 Implementation Report — `analyzer/core/writer.py`

**Verdict**: PASS
**Implementer**: impl-implementer
**Date**: 2026-05-19

---

## Files changed

| File | Change type | Lines (approx) |
|---|---|---|
| `fresh_slotlab/analyzer/core/writer.py` | CREATED | 215 |
| `fresh_slotlab/player_impact_analyzer.py` | MODIFIED | -98 lines deleted, +28 lines added |
| `fresh_slotlab/analyzer/core/__init__.py` | MODIFIED | +5 lines (writer entry added to docstring) |
| `tests/backend/test_summary_md5_writer_parity.py` | MODIFIED | test_c5 renamed + signature updated |

---

## Brief-section traceability

| Change | Brief section |
|---|---|
| Create `fresh_slotlab/analyzer/core/writer.py` with `_save_chunk_cache` and `write_summary_json` | §1, §2 citing 04_v5 §6.2 deliverable 1 |
| `CHUNK_CACHE_VERSION` and `utc_now()` as module-level constants in writer.py (canonical source) | §1 — "CHUNK_CACHE_VERSION and utc_now() from PIA" |
| DI pattern: `lookup_machine_md5` and `rawdata_index_update_entry` as keyword-only args to `_save_chunk_cache` | §3 C5 — cycle freedom; §1 — "Replace the two calls inside the body with these injected callables" |
| Dual-path imports in writer.py for `core/parser.py` and `chunk_index` | §3 C5 — "MAY import from core/parser.py" |
| PIA dual-path import block for writer symbols (re-export pattern) | §3 C1 — "PIA re-exports via the existing dual-path import block" |
| Delete PIA's `def utc_now()` and `CHUNK_CACHE_VERSION = 3` (shadow-def trap prevention) | §5 "Verify shadow-def trap from P2-B2 critic"; memory feedback_no_parallel_panel_impl.md |
| Delete PIA's `def _save_chunk_cache(...)` body (98 lines) | §1 scope |
| Update `run_sampling_chunk` callsite to pass `lookup_machine_md5=_lookup_machine_md5, rawdata_index_update_entry=_rawdata_index_update_entry` | §3 C3 — semantic preservation; §6 risk item 3 |
| Replace `main()` lines 5262-5263 inline 2-liner with `out_json = write_summary_json(summary, args.output_dir)` | §1 "write_summary_json" |
| Preserve all bare `except` clauses verbatim from PIA | memory feedback_no_silent_swallow.md; §2 |
| Preserve `override_config_md5` / `override_code_md5` path exactly | §3 C3; memory feedback_md5_granularity_and_stamping.md; §6 risk item 2 |
| Update test_c5 in test_summary_md5_writer_parity.py from module-monkeypatch to kwarg-injection | Old test asserted pre-P2-B3 module-global behaviour; new test preserves the intent (sentinel propagates to envelope) via the new DI mechanism |

---

## Design decision: `rawdata_index_update_entry` inner try/except

The original PIA code called `_rawdata_index_update_entry(rawdata_root, machine, rtp_mode, cache_dir)` directly inside a bare `try/except Exception: pass`. After DI, `rawdata_index_update_entry` is the injected callable. The implementation wraps the call in `if rawdata_index_update_entry is not None:` (added guard) then the existing `except Exception: pass` (preserved verbatim). This means:

- When `rawdata_index_update_entry=None` (e.g. in tests), the side-effect is skipped cleanly.
- When a real callable is injected (as in the production callsite), the bare `except` still catches any I/O failure silently, exactly as before.

This is strictly additive — the `None` guard is new but the bare `except` is unchanged. The `_rawdata_index_update_entry` callable reference at the callsite is `_rawdata_index_update_entry` from PIA's module-top import, so the existing `monkeypatch.setattr(pia, "_rawdata_index_update_entry", ...)` tests continue to work.

---

## Shadow-def verification (MUST be 0)

```
grep: CHUNK_CACHE_VERSION\s*= in PIA     → 0 matches  OK
grep: ^def utc_now in PIA                → 0 matches  OK
grep: ^def _save_chunk_cache in PIA      → 0 matches  OK
grep: ^def write_summary_json in PIA     → 0 matches  OK
```

---

## Cycle-freedom verification

```
grep: from fresh_slotlab.player_impact_analyzer in writer.py  → 0 matches  OK
grep: from player_impact_analyzer in writer.py                → 0 matches  OK
```

---

## Import identity

```python
import fresh_slotlab.player_impact_analyzer as pia, fresh_slotlab.analyzer.core.writer as w
assert pia._save_chunk_cache is w._save_chunk_cache      # PASS
assert pia.write_summary_json is w.write_summary_json    # PASS
assert pia.CHUNK_CACHE_VERSION == w.CHUNK_CACHE_VERSION  # PASS
assert pia.utc_now is w.utc_now                          # PASS
```

---

## Pytest results

### P1-A1 canary (gold standard)
`tests/integration/test_analyzer_three_invocation_parity.py`: **23/23 PASS** (20s)

### 7-suite Phase 1+2 regression
All suites combined: **457 passed, 9 skipped** (22s)
- `test_lookup_machine_md5_canonical.py` ✓
- `test_summary_md5_writer_parity.py` ✓ (30/30 — test_c5 updated)
- `test_analyzer_foundation.py` ✓
- `test_manifest_loader.py` ✓ (9 skipped — pre-existing, not introduced)
- `test_analyzer_core_parser.py` ✓
- `test_analyzer_core_aggregator.py` ✓

### Subprocess import safety
```
python -c "import fresh_slotlab.analyzer.core.writer"  → rc=0, no stderr  OK
```

---

## Test update: `test_c5_save_chunk_cache_propagates_sentinel_via_module_attr`

**Why updated**: The old test called `pia._save_chunk_cache(...)` without the new `lookup_machine_md5` kwarg (which is now required). It used `monkeypatch.setattr(pia, "_lookup_machine_md5", sentinel)` to inject via module-global — the exact anti-pattern P2-B3 replaces.

**What changed**: Renamed to `test_c5_save_chunk_cache_propagates_sentinel_via_kwarg`. Now calls `pia._save_chunk_cache(..., lookup_machine_md5=lambda m: (SENTINEL_CFG, SENTINEL_CODE), rawdata_index_update_entry=None)`. Spirit preserved: sentinel values must appear in the written chunk envelope's `_config_md5` / `_code_md5` fields.

**Inject-bug still works**: Passing a no-op lambda `lambda m: ("", "")` instead of the sentinel → sentinel NOT in envelope → test RED.

---

## Open issues / out of scope

- `_lookup_machine_md5` carve — separate ticket per brief §4.
- `_rawdata_index_update_entry` carve — separate ticket per brief §4.
- Markdown report generation — P2-B4 per brief §4.
- `compute_base_analyzer_version()` hash now includes writer.py — per brief §3 C6, this is expected behaviour (tracked separately, test currently skipped per P2-B1b critic note).

## Risk notes for impl-critic / impl-verifier

1. **`rawdata_index_update_entry=None` guard**: The None guard is new. In the production callsite (`run_sampling_chunk`), the real `_rawdata_index_update_entry` is always passed. The guard only fires in test/direct-call scenarios. `impl-verifier` should confirm no production path accidentally passes `None`.

2. **Module isolation between tests**: During debugging, the parity canary tests failed when run after a test suite that had `monkeypatch.setattr(pia, "_save_chunk_cache", ...)` in an `autouse` fixture without proper cleanup. The new DI pattern eliminates this risk (no module-global monkeypatching needed), but old monkeypatching in OTHER test files could still contaminate. Clean isolated runs pass 457/457.

3. **`update_chunk_entry` stays in writer.py**: `chunk_index.py` does NOT import from PIA, so the writer → chunk_index dependency is cycle-free. Verified by `python -c "import fresh_slotlab.chunk_index"` — no PIA import in its dependency graph.
