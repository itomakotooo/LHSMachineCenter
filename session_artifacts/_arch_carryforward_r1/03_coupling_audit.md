# 03 — Coupling Audit: Carry-forward Round 1 (Clusters A + D + E)

> **Date**: 2026-05-28
> **Auditor**: arch-coupling-auditor (W1)
> **Topic dir**: `session_artifacts/_arch_carryforward_r1/`
> **Baseline**: `session_artifacts/_arch_analyzer_unbundle/03_coupling_audit.md` (C-phase audit, 19 symbols)
> **Delta scope**: Clusters A, D, E only — symbols not audited in C-phase or where the proposed change creates new coupling risk.

---

## §1 Scope

**Directories audited** (delta from C-phase baseline):

- `fresh_slotlab/player_impact_analyzer.py` — topo-sort error path, DECLARED_DEPS RuntimeError, write_summary_json placement, feature_errors accumulation
- `fresh_slotlab/analyzer/topo_sort.py` — PluginCyclicDependencyError, PluginMissingDependencyError
- `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` — paylines sort key (d1)
- `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py` — trigger_target selection (d2), trigger_target_confidence "unique" branch (d3)
- `fresh_slotlab/analyzer/features/collect_mechanic.py` — avg_bonus_payout None vs 0.0 (d4)
- `fresh_slotlab/analyzer/versioning.py` — compute_effective_version_for_machine side-effects
- `src/web_console/backend/_batch_gen_worker.py` — rc handling
- `src/web_console/backend/app.py` — summary JSON consumption
- `src/web_console/frontend/app.js`, `pure.js` — field consumers
- `tests/analyzer/` — 7 files with hardcoded effective_version hex

**Not re-audited** (C-phase baseline sufficient):

- `compute_base_analyzer_version` / `compute_effective_analyzer_version` composition algorithms
- `ALL_FEATURES` module global lifecycle
- `payout_ids_top20` schema (no rename proposed)
- `rtp_integrity.py` 4-layer gate
- `manifest_loader`, `round_classification`, `round_win` (no changes proposed)

---

## §2 Fleet-Shared Symbol Table (Cluster A)

### Symbol A-1: `summary["analyzer_init_error"]`

**Module**: `fresh_slotlab/player_impact_analyzer.py:5058`

**Current state**: Written only in the topo-sort error path (line 5058). `summary` is set, then `SystemExit(1)` fires at line 5065 BEFORE `write_summary_json` (line 5210). The JSON is never written to disk on topo error.

**Proposed change**: Wrap the topo-sort error block in a `try/finally` that calls `write_summary_json` before propagating `SystemExit(1)`.

**Direct callers / consumers** (by `key="analyzer_init_error"`):

| Consumer | File:Line | Read mode | Breakage if key absent |
|---|---|---|---|
| `_batch_gen_worker.py:154` | Returns `{"ok": False, "error": f"analyzer rc={rc}"}` when `rc != 0` | Reads `rc` only; does NOT read `analyzer_init_error` from the summary dict | None — backend currently uses rc=1 as the sole signal; never reads the JSON on rc!=0 path |
| `test_c1_byte_identical_m14.py:147` | Asserts `"analyzer_init_error" not in m14_summary` on success path | Test reads from on-disk summary JSON | Would catch if key erroneously present on success path |
| `test_c1_byte_identical_m275.py:145` | Same assertion | Same | Same |
| `test_c2_byte_identical_m14.py:125` | Same assertion | Same | Same |
| `test_c2_byte_identical_m272.py:101` | Same assertion | Same | Same |
| `test_c2_byte_identical_m275.py:95` | Same assertion | Same | Same |
| `test_c2_byte_identical_m37.py:114` | Same assertion | Same | Same |
| `test_c3_5_m14_no_multiplier_wild.py:102` | Same assertion | Same | Same |
| `test_c3_5_m275_e2e.py:126` | Same assertion | Same | Same |
| `test_c4_m11_jackpot_ids_union.py:133` | Same assertion | Same | Same |
| `test_c4_m14_no_false_positives.py:102` | Same assertion | Same | Same |
| `test_c4_m275_gap_1_closed.py:131` | Same assertion | Same | Same |
| `test_c4_m275_gap_2_closed.py:125` | Same assertion | Same | Same |
| `test_c5_m14_no_false_positives.py:103` | Same assertion | Same | Same |
| `tests/analyzer/test_c1_init_error_surfacing.py` | Tests topo_sort raises correct exceptions; does NOT test JSON write (noted as TODO) | Unit-level only | No breakage — unit tests do not test disk output |

**Consumer count**: 14 test assertion sites + 0 production readers of the JSON field.

**Critical coupling gap (C1 critic carry-forward a)**: The backend at `_batch_gen_worker.py:154` short-circuits on `rc != 0` and returns `{"ok": False, "error": f"analyzer rc={rc}"}` without reading the summary. This means:
1. The JSON is not currently written (bug — the field is in memory only).
2. Even after the fix (try/finally writes JSON), the backend does NOT read `analyzer_init_error` from disk on failure. The JSON write-on-failure is for operator inspection (not for backend-automated consumption).
3. No CI gate, no console operator path, no frontend rendering consumes `analyzer_init_error`. It is a purely operator-inspectable field — confirming the try/finally fix is safe and low-coupling.

**Blast radius (proposed fix)**: Moving `write_summary_json` into a `try/finally` block wrapping the topo-sort error path:
- `write_summary_json` is a pure I/O function at `core/writer.py`; its signature and behavior are unchanged.
- The `summary` dict at the point of the topo error is partially built (all pre-plugin-loop keys present, no plugin `emit()` keys yet). Writing it is safe; reading code that sees the partial summary needs `analyzer_init_error` to be a signal for "this run failed".
- 0 production code reads `analyzer_init_error` from disk — blast radius for the field itself is zero.
- Risk is entirely in the `try/finally` restructuring of `main()` control flow: `SystemExit` must still propagate after the write; any exception inside `write_summary_json` must not suppress the original `SystemExit`. This is a control-flow coupling risk in PIA main(), not a consumer risk.

**Breakage mode if try/finally is incorrectly structured**: `silent-wrong-result` — if `write_summary_json` raises and swallows `SystemExit`, backend receives `rc=0` despite topo failure, and the summary on disk is partial.

**Migration sensitivity**: `behavior-stable` — no schema change. Adding the JSON write is purely additive to the current behavior.

---

### Symbol A-2: `write_summary_json`

**Module**: `fresh_slotlab/analyzer/core/writer.py` (re-exported from `fresh_slotlab/player_impact_analyzer.py:231`)

**Signature**: `def write_summary_json(summary: dict, output_dir: Path) -> Path`

**Current call site in PIA main()**: `player_impact_analyzer.py:5210` — single call, after all plugin `emit()` calls and after the RTP integrity gate.

**Direct callers**:

| Caller | File:Line | Context |
|---|---|---|
| PIA main() | `player_impact_analyzer.py:5210` | Success path, after all processing |
| (proposed A-fix) | Same file, ~line 5065 | Error path — new call inside `try/finally` |

**Test callers** (unit/integration tests of the function itself):

| Test file | Line | What it tests |
|---|---|---|
| `tests/backend/test_analyzer_core_writer.py:1065` | `write_summary_json(summary, tmp_path)` | Creates file |
| `test_analyzer_core_writer.py:1077` | Returns Path | Return type |
| `test_analyzer_core_writer.py:1095` | Content round-trips | JSON correctness |
| `test_analyzer_core_writer.py:1115` | `ensure_ascii=False` | Encoding |
| `test_analyzer_core_writer.py:1131` | `indent=2` | Formatting |
| `test_analyzer_core_writer.py:216` | Import smoke | Importable |
| `test_analyzer_core_writer.py:276` | Signature check | `summary` + `output_dir` params |
| `test_analyzer_core_writer.py:318` | PIA re-exports it | Identity check |
| `test_analyzer_core_writer.py:348` | `pia.write_summary_json IS writer.write_summary_json` | Object identity |

**Blast radius (adding a second call site)**: Adding a second call to `write_summary_json` in the error path does NOT affect any test that tests `write_summary_json` itself — those tests verify the function's behavior, not how many times PIA calls it. The `test_analyzer_core_writer.py:419` test (quoted comment: `write_summary_json on all three invocations`) tests that PIA re-exports the function, not the number of calls.

**Risk of the try/finally placement**: The single critical risk is that `write_summary_json` may raise `OSError` (disk full, permissions) on the error path. The proposed `try/finally` must decide: should a write failure inside the finally block suppress the original `SystemExit(1)`, or be ignored? If `finally` raises `OSError`, Python replaces the original exception — `SystemExit(1)` is lost, backend receives `rc=0`. The designer must account for this: the finally block should wrap `write_summary_json` in a `try/except Exception` to guard against suppression.

**Breakage mode**: `compile-fail` equivalent if `SystemExit` is swallowed (backend gets rc=0 on failure). `silent-wrong-result` if the summary is not written (JSON missing on disk, operator cannot inspect).

**Migration sensitivity**: `signature-stable`. No consumer changes needed.

---

### Symbol A-3: `SystemExit(1)` sites in PIA main()

**All `raise SystemExit(...)` in `fresh_slotlab/player_impact_analyzer.py`**:

| Line | Context | rc |
|---|---|---|
| 1083 | `--bet must be positive` | string message (non-zero by convention) |
| 1085 | `--target-halfwidth-pp` | string message |
| 1087 | chunk/robot args | string message |
| 1089 | concurrency/timeout args | string message |
| 1091 | bankruptcy session spins | string message |
| 1425 | cache file missing | string message |
| 1477 | from-cache no chunks found | string message |
| 1595 | parse exception during sampling | string message |
| 1633 | chunk missing 'response' key | string message |
| 1641 | chunk parse failed | string message |
| 2169 | concurrency flag error | string message |
| 2178 | replay flag error | string message |
| **5065** | **topo-sort error (ONLY rc=1 integer)** | **integer 1** |

**Proposed new `SystemExit(1)` site**: DECLARED_DEPS missing-key `RuntimeError` at line 5077 currently raises `RuntimeError`, not `SystemExit`. This is a programming error — the brief proposes it should also produce `rc=1` + JSON write.

**Backend rc handling** (`_batch_gen_worker.py:154`):

```python
if rc != 0:
    return {"machine": machine, "mode": mode, "ok": False,
            "error": f"analyzer rc={rc}",
            "elapsed_s": elapsed}
```

The check is `rc != 0`. `SystemExit("message string")` has `code` attribute = the string, which is truthy but NOT equal to integer 1. Python's `SystemExit.code` when string is the string itself. When PIA is called via `_analyzer_mod.main()` (in-process, not subprocess), the `SystemExit` propagates unless caught. The current code does NOT wrap `_analyzer_mod.main()` in a `try/except SystemExit`. The `contextlib.redirect_stdout` context manager does not catch `SystemExit`. Therefore ALL current `SystemExit(...)` calls propagate upward as exceptions to `_batch_gen_worker`, where they would be caught by the outer job-level exception handler (not the `rc != 0` check).

**Critical finding**: The `rc != 0` branch at `_batch_gen_worker.py:154` is the CORRECT path ONLY if PIA is called as a subprocess (where `SystemExit(1)` becomes the process exit code, captured as `rc`). For in-process calls (current: `rc = _analyzer_mod.main()`), `SystemExit` is an exception — the worker must catch it separately. This existing design is not changed by Cluster A.

**Blast radius of adding one more `SystemExit(1)` for DECLARED_DEPS**: Zero new consumers affected. The existing topo-sort path is the only error path with an integer `SystemExit(1)`. Adding one more does not change any downstream contract.

**Breakage mode**: `behavior-stable` for consumers. The only risk is control-flow — that the new `SystemExit(1)` fires in a context where `write_summary_json` has already been called (to avoid double-write or partial overwrite).

---

### Symbol A-4: `summary["feature_errors"]` (existing C2 mechanism)

**Module**: `fresh_slotlab/player_impact_analyzer.py:5089–5106`

**When populated**:
1. `emit()` exception path (line 5089): `summary["feature_errors"][_feature.FEATURE_ID] = str(_emit_exc)`
2. `_extract_error_*` accumulation path (line 5101–5104): `summary["feature_errors"][f"extract_{_fid}"] = "; ".join(...)`

**Schema**: Top-level `summary["feature_errors"]` dict. Keys are feature IDs (for emit errors) or `f"extract_{fid}"` (for extract errors). Values are error message strings.

**Direct consumers**:

| Consumer | File:Line | Read mode | Breakage if removed/renamed |
|---|---|---|---|
| `test_c2_byte_identical_m14.py:137` | `m14_c2_summary.get("feature_errors", {})` | Reads on success path to assert empty | Would miss key if renamed |
| `test_c2_byte_identical_m272.py:106` | `m272_c2_summary.get("feature_errors", {})` | Same | Same |
| `test_c2_byte_identical_m275.py:100` | Same | Same | Same |
| `test_c2_byte_identical_m37.py:119` | Same | Same | Same |
| `test_c2_extract_error_capture.py:163` | `summary.get("feature_errors", {})` | Core test: asserts key IS populated when `extract()` raises | Key rename = test RED |
| `test_c3_byte_identical_legacy_fields_m14.py:110` | Same empty-check | Asserts empty on success path | Would miss rename |
| `test_c3_byte_identical_legacy_fields_m275.py:112` | Same | Same | Same |
| `test_c3_5_m14_no_multiplier_wild.py:108` | Same | Same | Same |
| `test_c3_5_m275_e2e.py:132` | Same | Same | Same |
| `test_c3_trigger_marker_m275.py:133` | Same | Same | Same |
| `test_c4_m14_no_false_positives.py:108` | Same | Same | Same |
| `test_c4_m275_gap_1_closed.py:137` | Same | Same | Same |
| `test_c5_collect_mechanic_plugin.py:500,623` | Same (for M275 and M14) | Same | Same |
| `test_c5_byte_identical_unrelated_fields.py:275,280` | Same (for M275 and M14) | Same | Same |
| `test_c5_m14_no_false_positives.py:109` | Same | Same | Same |
| `test_c5_upstream_feature_breakdown_plugin.py:348,435` | Same (for M275 and M14) | Same | Same |
| `test_c6_bonus_chain_dynamics_plugin.py:511,586` | Same (for M275 and M14) | Same | Same |
| `test_c6_carve_completion.py:97` | Same | Same | Same |

**Backend consumer**: No `app.py` or `_batch_gen_worker.py` line reads `feature_errors` from the summary JSON. This field is currently test-only on the consumer side; operators see it only via manual JSON inspection.

**Frontend consumer**: No `app.js` or `pure.js` line renders `feature_errors`. The frontend renders the summary but has no panel for error fields — they are invisible to the UI.

**Consumer count**: 18 test assertion sites. 0 production code readers.

**Cluster A unification proposal impact**: The brief proposes unifying the 3 error paths (silent / in-memory / persistent) so ALL errors → `summary["analyzer_init_error"]` (top-level). The existing `feature_errors` mechanism is the C2 mechanism for graceful-degradation errors (extract/emit failures). It must be preserved as-is for that purpose; the unification targets the HARD error paths (topo cycle, DECLARED_DEPS miss) that currently do NOT write JSON.

**If `feature_errors` key is renamed to unify with `analyzer_init_error`**: 18 test sites would require update. All use `.get("feature_errors", {})` pattern — a rename from `"feature_errors"` to `"analyzer_init_error"` would silently pass (dict.get with default `{}` returns `{}` for missing key), turning assertion failures into silent test passes. This is a `silent-wrong-result` breakage mode that would be hard to detect. The correct migration is to NOT rename `feature_errors` — keep both fields.

**Breakage mode for the proposed fix**: `behavior-stable` — `feature_errors` is not being renamed; the new field `analyzer_init_error` is additive at the top level.

---

## §3 Fleet-Shared Symbol Table (Cluster D)

### Symbol D-1: `paylines` sort key in `PayoutsBySpinType.emit()`

**Module**: `fresh_slotlab/analyzer/features/payouts_by_spin_type.py:424–436`

**Current sort key**: `key=lambda x: x["payline_id"]` — string comparison.

**Bug**: `payline_id` values are strings stored as string keys in the `pl_map` dict (e.g. `"1"`, `"2"`, `"10"`, `"20"`). String sort produces `["1", "10", "2", "20"]` (lexicographic) instead of `["1", "2", "10", "20"]` (numeric). For machines with fewer than 10 paylines (M14: 9, M275: none affected, M37: not audited) the bug is latent (1–9 sort identically in both orders). Machines with 10+ paylines (M275 has none; future machines per brief) would produce misordered payline rows.

**Proposed fix**: `key=lambda x: int(x["payline_id"]) if x["payline_id"] != "-1" else -1`

**Consumers of `paylines` sub-field**:

| Consumer | File:Line | Read mode | Breakage from sort change |
|---|---|---|---|
| `src/web_console/frontend/app.js` | No direct hit on `paylines` within `payouts_by_spin_type` rendering | Frontend renders `payouts_by_spin_type` rows but does not extract the `paylines` sub-field for display per this audit | None |
| `src/web_console/frontend/pure.js` | `pure.js:1514` — reads `.paylines_top20` (a DIFFERENT key, not `payouts_by_spin_type[*].paylines`) | Different field entirely | None |
| `src/web_console/backend/app.py` | No grep hit on `payouts_by_spin_type.*paylines` or `paylines` under `payouts_by_spin_type` | Not consumed | None |
| Test suite | `tests/analyzer/test_c3_trigger_marker_m275.py` — checks `paylines` field presence, not order | `paylines` is asserted present, not sorted-order checked | None from sort change alone |

**Blast radius**: Zero for existing consumers on M14/M37/M272/M275 (all have < 10 paylines or no paylines on the relevant pids). Future machines with 10+ paylines would produce wrong sort order in on-disk summaries but no consuming code currently reads sort order. The fix is forward-protective, not retroactively breaking.

**`effective_analyzer_version` impact**: Changing `payouts_by_spin_type.py` bytes flips the plugin's `compute_hash()` → `effective_analyzer_version` changes for ALL 253 non-variant machines that declare `"payouts_by_spin_type"`. This is 253 machines × N modes whose reports become "historical" (stale badge in UI). **This is the primary blast radius**: not from reading the sort order, but from the version invalidation.

**Breakage mode**: `cache-invalidation` for 253 machines. `silent-wrong-result` for the bug itself (wrong sort, no error raised, readers see misordered data).

**Migration sensitivity**: `behavior-stable` for existing consumers. The sort key change is additive behavior improvement. No schema change.

---

### Symbol D-2: `trigger_target` selection in `BonusChainDynamics.emit()`

**Module**: `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py:197–216`

**Current behavior** (bug): When `scatter_marker_pids` is non-empty and `scatter_feature_names` is non-empty, `trigger_target = sorted(scatter_feature_names)[0]` — picks the ALPHABETICALLY FIRST feature name. For M275 with features `["NewFreespin", "NormalCollectionSpin"]`, this selects `"NewFreespin"` (N < N alphabetically, first letter ties; "NewFreespin" < "NormalCollectionSpin" lexicographically: 'e' < 'o' at position 2). The correct target is `"NormalCollectionSpin"`.

**Proposed fix**: Use `mechanism_registry.scatter_marker_pids` inverse mapping to look up which feature each scatter pid actually triggers, rather than picking alphabetically from `scatter_feature_names`.

**Consumers of `trigger_target` field** (in `payout_ids_top20[*].notes`):

| Consumer | File:Line | Read mode | Breakage from value change |
|---|---|---|---|
| `src/web_console/frontend/app.js` | No grep hit on `trigger_target` | Not rendered in current frontend | None |
| `src/web_console/frontend/pure.js` | No grep hit on `trigger_target` | Not rendered | None |
| `src/web_console/backend/app.py` | No grep hit on `trigger_target` | Not read by any endpoint | None |
| `tests/analyzer/test_c6_bonus_chain_dynamics_plugin.py` | Tests presence of `notes.trigger_target` but not specific value for M275 (per brief §6 "d2 trigger_target alphabetical-first heuristic") | Value assertion needed for regression guard | Test must be updated to assert `"NormalCollectionSpin"` |

**Blast radius**: Changing `bonus_chain_dynamics.py` bytes flips the plugin hash → `effective_analyzer_version` changes for all machines declaring `"bonus_chain_dynamics"` in their manifest. Per C6, this includes M275 and any other machines that have been onboarded with the plugin. On-disk summaries for those machines become "historical".

**Breakage mode**: `silent-wrong-result` for the bug (wrong feature name in JSON, no error). `cache-invalidation` for machines declaring the plugin.

**Migration sensitivity**: `behavior-stable` for non-existent consumers. `inject-bug required` for the test to assert the correct value.

---

### Symbol D-3: `trigger_target_confidence: "unique"` dead branch

**Module**: `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py:208`

**Current behavior**: When `scatter_marker_pids` is non-empty and `scatter_feature_names` is non-empty, `trigger_target_confidence = "data_inferred"` regardless of whether there is exactly 1 or multiple candidates. The spec defines `"unique"` for the case where exactly 1 feature candidate exists, but this branch is never emitted.

**Proposed fix**: Emit `"unique"` when `len(scatter_feature_names) == 1`, `"data_inferred"` when `> 1`.

**Consumers of `trigger_target_confidence` field** (in `payout_ids_top20[*].notes`):

| Consumer | File:Line | Read mode | Breakage from new value |
|---|---|---|---|
| `src/web_console/frontend/app.js` | No grep hit on `trigger_target_confidence` | Not rendered | None |
| `src/web_console/frontend/pure.js` | No grep hit on `trigger_target_confidence` | Not rendered | None |
| `src/web_console/backend/app.py` | No grep hit on `trigger_target_confidence` | Not read | None |
| `tests/analyzer/test_c6_bonus_chain_dynamics_plugin.py` | Asserts presence and value of `trigger_target_confidence` | Must be updated to assert `"unique"` for single-candidate case | Test update needed |

**Blast radius**: Same as D-2 (both touch `bonus_chain_dynamics.py`). If D-2 and D-3 are implemented together (single file edit), the plugin hash flips once, not twice. The `effective_analyzer_version` change is the same as D-2 regardless of whether D-3 is bundled.

**Breakage mode**: `silent-wrong-result` for the dead branch (spec value never emitted). `behavior-stable` for all consumers (none currently read the field in production).

---

### Symbol D-4: `avg_bonus_payout` None vs 0.0

**Module**: `fresh_slotlab/player_impact_analyzer.py:4817–4825`

**Current computation**:
```python
"avg_bonus_payout": (
    (
        sum(...) / total_completed_cycles
        if total_completed_cycles > 0 else None
    ) if _cm_bonus_feat else None
),
```

When `total_completed_cycles == 0` AND `_cm_bonus_feat` is set: emits `None`.
When `_cm_bonus_feat` is None: emits `None`.
When both conditions hold and cycles > 0: emits a float.

**The d4 issue**: The brief states "None vs 0.0 behavioral delta (None more accurate; downstream needs null-safe)." This implies the current code emits `None` (correct semantic: no data), but a previous or proposed version might emit `0.0` (incorrect: implies zero bonus payout measured). The current code already emits `None` in the zero-cycles case. The fix appears to be ensuring the plugin (via `CollectMechanic.emit()`) preserves `None` rather than converting it to `0.0`.

**Verification of the data flow**: `avg_bonus_payout` is built in PIA inline at line 4817 and placed into the `_collect_mechanic_data` stash dict. `CollectMechanic.emit()` reads the stash and writes `summary["collect_mechanic"]["bonus_cycle_correction"]["avg_bonus_payout"]` from it. The plugin's `emit()` does NOT recompute or coerce the value — it passes through from the stash. The `None` is preserved.

**Consumers of `avg_bonus_payout`**:

| Consumer | File:Line | Read mode | Null-safety |
|---|---|---|---|
| `src/web_console/frontend/app.js:6196` | `bcc.avg_bonus_payout != null` | Null-safe — renders `"—"` when `null` | Already null-safe |
| `src/web_console/backend/app.py` | No grep hit on `avg_bonus_payout` | Not read by any endpoint | N/A |
| `tests/analyzer/test_c5_collect_mechanic_plugin.py:298` | `"avg_bonus_payout": 40.0` | Asserts a specific float value (M272 test case with cycles > 0) | Not null in this test |
| `tests/analyzer/test_c5_gap_6_chunk_spin_times_recommendation.py:257` | `"avg_bonus_payout": 40.0` | Same pattern | Not null in this test |
| `tests/backend/test_full_pipeline_m272.py:391` | Checks key presence in list `("avg_bonus_payout", ...)` | Key-presence check only, not value assertion | Null-safe |

**Blast radius**: If the fix is purely in `collect_mechanic.py` (plugin file), the plugin hash flips → `effective_analyzer_version` changes for machines declaring `"collect_mechanic"` (M275, M272 family, and any others onboarded with BCM support). If the fix is in `player_impact_analyzer.py` (the inline stash builder), `analyzer_version` (legacy) flips for all machines.

The brief says the fix targets "downstream needs null-safe" — the one consumer (`app.js:6196`) is already null-safe (`!= null` guard). No new null-safety is needed in consumers. The fix may be purely semantic documentation or a guard against a future coercion risk.

**Breakage mode**: `behavior-stable` — `None` is the current emission. If the fix prevents `0.0` from ever being emitted, existing consumers are already null-safe. No breakage.

**Migration sensitivity**: `rename-safe`. Field name unchanged.

---

## §4 Fleet-Shared Symbol Table (Cluster E)

### Symbol E-1: `compute_effective_version_for_machine` — side effects and caching

**Module**: `fresh_slotlab/analyzer/versioning.py:92`

**Per-call side effects**:

1. **File system reads**: `compute_base_analyzer_version()` reads ALL `core/*.py` files (6 files) via `source_file.read_bytes()`. `load_manifest(machine_id, manifests_root)` reads the machine's JSON manifest from disk. Each call to `compute_effective_version_for_machine` issues ~7 file reads.

2. **Import side effects**: When `registry=None` (default), the function imports all 9 plugin modules (lines 165–173). Each import triggers module-level `register()` calls that append to `ALL_FEATURES`. Because `register()` is idempotent on duplicate `FEATURE_ID` (per P2-A1), repeated calls do NOT grow `ALL_FEATURES` — they are no-ops after the first import. Python's import caching (`sys.modules`) means the import statements after the first call are cheap (no re-execution). **No mutable module-global state accumulates across calls.**

3. **No caching of the computed hash**: The function does NOT cache its return value. Two calls with identical arguments perform identical file reads and hash computations. For the test suite, this means: if `compute_effective_version_for_machine("M14", 1)` is called N times in the same test session, it reads disk N times.

4. **No locking or threading guards**: The function is pure-computation after imports. Concurrent calls are safe (no shared mutable state per call).

**Conclusion on side effects**: The function is safe to call in test assertions. Each call issues ~7 disk reads (negligible for a test fixture) and 9 import statements (fast after first call via `sys.modules` cache). No global state is modified beyond the first import triggering `ALL_FEATURES` population.

**Current test usage pattern** (hardcoded vs. dynamic):

| Test file | Dynamic compute | Hardcoded hex | What is hardcoded |
|---|---|---|---|
| `test_c3_5_isolation_m275_only.py` | Yes — `_compute_effective_version()` wrapper at line 126 | Yes — `_M275_C3_5_EFFECTIVE_VERSION = "5c78f3834a1e"` at line 93; `_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"` at line 109; `_C3_BASE_HASH = "fa440e3eb5f6"` at line 81 | 3 constants; used in 8 assertion methods |
| `test_c3_5_m275_e2e.py` | Yes — calls `compute_effective_version_for_machine` at line 455 | Yes — docstring says `"2ef11cd69c8d (C3.5 value)"` at line 449 (comment only, not in assertion) | Comment-only for historical; assertion is dynamic |
| `test_c3_5_m14_no_multiplier_wild.py` | Yes — calls `compute_effective_version_for_machine` at line 222 | Yes — `_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"` at line 241 | Used in 1 assertion for M14 expected value |
| `test_c3_base_hash_flips_for_round_level_enrichment.py` | Yes — computes base hash | Yes — `_C2_BASE_HASH = "b0ba0ce7c7e2"` at line 72; `_EXPECTED_C3_BASE_HASH = "fa440e3eb5f6"` at line 77 | 2 constants; base_hash is a core/*.py hash, NOT machine-specific effective_version |
| `test_c5_byte_identical_unrelated_fields.py` | Computes base hash only | Yes — `"fa440e3eb5f6"` hardcoded in assertion at line 102 | base_hash (same as above) |
| `test_c6_byte_identical_bonus_chain.py` | Computes base hash only | Yes — `"fa440e3eb5f6"` hardcoded at line 113 | base_hash only |
| `test_c6_carve_completion.py` | Computes base hash only | Yes — `"fa440e3eb5f6"` hardcoded at line 114 | base_hash only |

**Key distinction**: `_C3_BASE_HASH = "fa440e3eb5f6"` is a `compute_base_analyzer_version()` value, NOT a machine-specific `effective_analyzer_version`. `base_hash` depends ONLY on `core/*.py` bytes — it does NOT change when a feature plugin is added. The constraint `base_hash UNCHANGED fa440e3eb5f6` is a hard invariant in the brief. Therefore:

- Files that hardcode only `base_hash` (`test_c3_base_hash_flips_for_round_level_enrichment.py`, `test_c5_byte_identical_unrelated_fields.py`, `test_c6_byte_identical_bonus_chain.py`, `test_c6_carve_completion.py`): these hardcoded values will NOT change from any Cluster A/D fix (per brief invariant `base_hash UNCHANGED`). No migration needed.

- Files that hardcode machine-specific `effective_analyzer_version` (`test_c3_5_isolation_m275_only.py` lines 93+109, `test_c3_5_m14_no_multiplier_wild.py` line 241): these VALUES CHANGE if any plugin file declared by those machines is modified (Cluster D). Specifically: D-1 changes `payouts_by_spin_type.py` → `"6aae41144cea"` (non-M275) becomes a new value. D-2+D-3 change `bonus_chain_dynamics.py` → both `"5c78f3834a1e"` (M275) and `"6aae41144cea"` (non-M275) become new values. All 3 D-fixes change one of the two plugin files that feed into the hash.

---

### Symbol E-2: Hardcoded hex constants — migration sensitivity table

| File | Line | Hardcoded value | Type | Changes from D-1? | Changes from D-2+D-3? | Changes from D-4? |
|---|---|---|---|---|---|---|
| `test_c3_5_isolation_m275_only.py:81` | `_C3_BASE_HASH = "fa440e3eb5f6"` | base_hash | No (core unchanged) | No | No |
| `test_c3_5_isolation_m275_only.py:93` | `_M275_C3_5_EFFECTIVE_VERSION = "5c78f3834a1e"` | M275 effective_version (9 plugins) | No (M275 doesn't declare payouts_by_spin_type? Wait — M275 declares all 9 plugins including payouts_by_spin_type per manifests) | **Yes — D-1 changes payouts_by_spin_type.py** | **Yes — D-2+D-3 change bonus_chain_dynamics.py** | Depends on where D-4 fix lands |
| `test_c3_5_isolation_m275_only.py:109` | `_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"` | M14/M37/M272 effective_version (8 plugins) | **Yes — D-1 changes payouts_by_spin_type.py** | **Yes — D-2+D-3 change bonus_chain_dynamics.py** | Depends on D-4 fix location |
| `test_c3_5_m14_no_multiplier_wild.py:241` | `_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"` | M14 effective_version | **Yes — D-1** | **Yes — D-2+D-3** | Depends on D-4 |
| `test_c3_base_hash_flips_for_round_level_enrichment.py:72` | `_C2_BASE_HASH = "b0ba0ce7c7e2"` | Historical C2 base_hash (negative assertion) | No | No | No |
| `test_c3_base_hash_flips_for_round_level_enrichment.py:77` | `_EXPECTED_C3_BASE_HASH = "fa440e3eb5f6"` | Current base_hash | No | No | No |
| `test_c5_byte_identical_unrelated_fields.py:102` | `"fa440e3eb5f6"` | base_hash | No | No | No |
| `test_c6_byte_identical_bonus_chain.py:113` | `"fa440e3eb5f6"` | base_hash | No | No | No |
| `test_c6_carve_completion.py:114` | `"fa440e3eb5f6"` | base_hash | No | No | No |

**Summary count**:
- Hardcoded hex values total: 9 constants across 7 files
- base_hash hardcodes (never change from A/D/E fixes): 6 instances across 5 files
- machine-specific effective_version hardcodes (CHANGE from D fixes): 3 instances in 2 files

**Failure mode if not updated**:
- Type: `compile-fail` equivalent — the test assertion fails immediately on any D-fix that changes the declared plugins' source files.
- Specifics: `assert ev == "6aae41144cea"` would fail because the new value (after D-1 or D-2+D-3) is a different 12-char hex. The failure message includes the expected and actual values, making diagnosis straightforward.
- This is NOT a `silent-wrong-result` failure — it is a hard `AssertionError` that turns tests RED immediately.

**Migration paths** (Cluster E proposal):

1. **Dynamic-only approach**: Replace hardcoded constants with `compute_effective_version_for_machine()` calls. Both test files already have a `_compute_effective_version()` helper. Change assertions from `ev == "6aae41144cea"` to `ev == _compute_effective_version("M14", 1)`. **Risk**: loses the regression guard that detects an unexpected hash change — if a future plugin accidentally changes M14's hash, the test now computes the "expected" dynamically and always passes.

2. **Differential assertion approach**: Keep base_hash hardcoded (it is a hard invariant). For machine-specific effective_versions, assert structural properties rather than exact hex: `assert _compute_effective_version("M14", 1) != _compute_effective_version("M275", 1)` (isolation invariant); `assert _compute_effective_version("M14", 1) == _compute_effective_version("M37", 1)` (symmetry invariant). The exact hex becomes a note in a comment, not an assertion. **Risk**: isolation can be preserved without the exact hex being stable — but the "M275 declares one more plugin than M14" structural fact is what matters.

3. **Hybrid approach**: Keep `_C3_BASE_HASH` as a hardcoded assertion (invariant: core unchanged). Update `_M275_C3_5_EFFECTIVE_VERSION` and `_NON_M275_EFFECTIVE_VERSION` after each C-phase delivery by running `compute_effective_version_for_machine()` once, writing the result as the new constant, and updating the comment history. This preserves the snapshot-regression property.

**Coupling risk of dynamic computation in tests**: `compute_effective_version_for_machine` reads manifests from disk at `slot_designer/configs/machine_manifests/`. If a test runs in a working tree where a manifest is temporarily malformed, the dynamic computation raises `FileNotFoundError` or `KeyError` — the test fails for an unrelated reason. Hardcoded constants are immune to manifest drift.

---

## §5 Hash Composition Map (Cluster D/E impact)

### 5.1 Cluster D effect on `effective_analyzer_version`

Each Cluster D fix modifies a plugin `.py` file. The resulting change to `effective_analyzer_version` is:

| D-fix | Plugin file modified | Machines affected | Reports affected | Notes |
|---|---|---|---|---|
| D-1 | `payouts_by_spin_type.py` | ALL machines declaring `"payouts_by_spin_type"` — currently 253 non-variant + M275 (already in 253) | ~275 on-disk summaries with `effective_analyzer_version` | The largest single-fix blast radius |
| D-2+D-3 | `bonus_chain_dynamics.py` | All machines declaring `"bonus_chain_dynamics"` — currently M275 + any others onboarded with C6 | Subset of 275 on-disk summaries | M275 is the primary affected machine |
| D-4 | Either `player_impact_analyzer.py` (inline stash) or `collect_mechanic.py` (plugin) | If PIA: all 393 machines (analyzer_version flip). If collect_mechanic.py: machines declaring `"collect_mechanic"` | Same 275 summaries (analyzer_version) or subset (effective_analyzer_version) | Fix location determines scope |

### 5.2 Cluster E effect on version stamps

Cluster E is test-only. No change to any plugin file or core file means:
- `compute_base_analyzer_version()` output: UNCHANGED
- Any machine's `effective_analyzer_version`: UNCHANGED
- On-disk summaries: NOT invalidated
- This is the correct property for a test refactor

---

## §6 Silent Dependencies Inventory

### 6.1 Cluster A: try/finally ordering constraint

**New silent dependency introduced by Cluster A fix**: A new implicit ordering constraint is created:

```
PIA main() must populate summary["analyzer_init_error"]
    → BEFORE calling write_summary_json
    → BEFORE raising SystemExit(1)
```

If a future change moves the `summary["analyzer_init_error"] = ...` line to AFTER `write_summary_json` in the finally block, the JSON is written without the error field — silent partial write. This constraint is not enforced by the type system.

**Mitigation**: The test `test_c1_init_error_surfacing.py` currently tests only that topo_sort raises; it does NOT test that the JSON is written with `analyzer_init_error`. A new test would need to spawn a PIA subprocess with an injected cyclic plugin and assert that the on-disk JSON contains `analyzer_init_error` AND that the file exists after `rc=1`.

### 6.2 Cluster D: `paylines` sort key type dependency

**Silent dependency in D-1**: `payline_id` values in `pid_payline_hits` dict keys come from upstream parser records. The type is always `str` (because dict keys from JSON/SpinType records are strings). The fix `int(x["payline_id"])` assumes the value is int-parseable. The carve-out `if x["payline_id"] != "-1"` handles the trigger-marker sentinel. A future machine that introduces a non-integer, non-"-1" payline_id (e.g. a letter-based payline label) would cause `ValueError` in `int(...)` — a new exception mode for the plugin.

**Risk level**: Low. Payline IDs are machine-integer-indexed per all audited machines. The brief notes M14/M275/M37 are unaffected (< 10 paylines). But this is a silent type assumption.

### 6.3 Cluster A: DECLARED_DEPS RuntimeError path

**Current silent failure**: The `RuntimeError` raised at PIA line 5077 for a missing DECLARED_DEP key is NOT caught by the topo-sort error handler. It propagates as an uncaught exception from `main()` — the caller (`_batch_gen_worker`) receives an unhandled exception, not a `SystemExit(1)`. The `rc != 0` check is never reached. The batch worker's job-level exception handler catches it and marks the job failed, but without the `analyzer_init_error` JSON on disk.

**Proposed A-fix scope**: The brief proposes closing this gap (C1 critic carry-forward b). The RuntimeError must be caught, `summary["analyzer_init_error"]` set, `write_summary_json` called, and `SystemExit(1)` raised. This requires extending the error-surfacing try/except to include the emit loop's DECLARED_DEPS check in addition to the topo-sort errors.

### 6.4 Cluster E: manifest dependency of dynamic test computation

**Silent dependency in E**: Tests using `compute_effective_version_for_machine("M14", 1)` dynamically depend on:
1. `slot_designer/configs/machine_manifests/M14.json` being present and valid.
2. `slot_designer/configs/machine_manifests/M275.json` being present and valid.
3. All 9 plugin modules being importable.
4. `fresh_slotlab/analyzer/core/*.py` (6 files) being intact.

Any of these being absent in a partial checkout or CI environment causes the test to fail with `FileNotFoundError` or `ImportError` rather than the intended assertion. Hardcoded constants are immune to this class of environment failure.

---

## §7 Invalidation Case Studies

### Case Study 1: Cluster A — try/finally fix for topo-sort error

**Change**: Wrap PIA's topo-sort error block in `try/finally` so `write_summary_json` is called before `SystemExit(1)`.

**Direct effect**: On topo-sort failure, `player_impact_summary.json` is now written to disk with `summary["analyzer_init_error"]` populated.

**Cascade**:
1. `_batch_gen_worker.py:154` — `rc != 0` branch still triggers; job returns `{"ok": False, "error": "analyzer rc=1"}`. The summary file now EXISTS on disk (previously did not). The worker's `if not summary_file.exists()` check at line 160 is now skipped (file exists), but since `rc != 0` already returned, it never reaches line 160.
2. Backend SQLite: no new runs row created on failure (batch worker returns before writing to DB on `ok=False`).
3. Operator inspection: `player_impact_summary.json` now accessible after topo failure.
4. 14 test assertions for `"analyzer_init_error" not in summary` on the SUCCESS path: unaffected (success path does not write the key).
5. `test_c1_init_error_surfacing.py`: unaffected (tests only topo_sort function, not disk I/O).

**Machines affected**: Any machine that triggers a topo-sort failure (currently zero — no cyclic plugins in production manifests). The change is preventive.

**Hard failures**: None on the success path. On the failure path, the JSON now exists after rc=1.

---

### Case Study 2: Cluster D-1 — paylines sort fix

**Change**: `key=lambda x: x["payline_id"]` → `key=lambda x: int(x["payline_id"]) if x["payline_id"] != "-1" else -1`

**Direct effect**: `payouts_by_spin_type.py` bytes change → `PayoutsBySpinType.compute_hash()` returns a new 12-hex value.

**Cascade**:
1. `compute_effective_version_for_machine` for any machine declaring `"payouts_by_spin_type"` → new effective_version.
2. Currently: all 253 non-variant machines declare it. All 253 machines × all modes get new effective_analyzer_version.
3. All 275 on-disk summaries with `effective_analyzer_version` become "historical" (UI freshness badge flips).
4. SQLite `runs.effective_analyzer_version` has old values; new runs produced with new code have new values.
5. No hard failures — reports remain readable; consumers do not break.
6. `test_c3_5_isolation_m275_only.py:93` and `:109` hardcoded hex values become wrong → test RED immediately.
7. `test_c3_5_m14_no_multiplier_wild.py:241` hardcoded hex becomes wrong → test RED immediately.

**Machines affected** (version invalidation): 253 non-variant machines.

**Reports affected**: 275 existing on-disk reports (stale badge only; content readable).

**Tests RED without Cluster E migration**: 3 test constants across 2 files.

---

### Case Study 3: Cluster D-2+D-3 — trigger_target + confidence fix

**Change**: `bonus_chain_dynamics.py` modified for correct trigger_target selection and "unique" confidence.

**Direct effect**: `BonusChainDynamics.compute_hash()` returns a new 12-hex value.

**Cascade** (separate from D-1 because different plugin):
1. `effective_analyzer_version` changes for all machines declaring `"bonus_chain_dynamics"`. Current: M275 + any BCM-family machines onboarded with C6.
2. M275's effective_version changes: `"5c78f3834a1e"` → new value.
3. Non-M275 machines that DO declare `bonus_chain_dynamics` (e.g. M272 if onboarded): their effective_versions also change.
4. M14, M37 (do NOT declare `bonus_chain_dynamics` per their standard 8-plugin set): NOT affected by D-2+D-3 hash change.

**Wait — critical clarification**: The non-M275 effective_version `"6aae41144cea"` in `test_c3_5_isolation_m275_only.py:109` refers to M14/M37/M272. If these machines DO declare `bonus_chain_dynamics` (C6 added it to M275 AND all non-variant machines?), then D-2+D-3 also invalidates `"6aae41144cea"`. Per the C-phase brief: C6 adds `bonus_chain_dynamics` as a plugin for M275 AND all non-variant machines. The non-M275 effective_version `"6aae41144cea"` already incorporates the C6 plugin hash. Changing `bonus_chain_dynamics.py` changes this hash for ALL 253 machines.

**Therefore D-2+D-3 also invalidates 253 machines' versions** — same scope as D-1.

**Tests RED without Cluster E**: Same 3 test constants.

---

### Case Study 4: Cluster E — test migration, differential assertion

**Change**: Replace hardcoded `_NON_M275_EFFECTIVE_VERSION = "6aae41144cea"` with dynamic computation or differential assertions.

**Direct effect**: Tests adapt to the new effective_version values produced by D-1 and D-2+D-3.

**Cascade**:
1. If using dynamic computation: `test_m14_effective_version_unchanged` changes its assertion from `ev == "6aae41144cea"` to `ev == _compute_effective_version("M14", 1)`. The test always passes as long as M14's hash is self-consistent — but loses the ability to detect an unexpected hash change.
2. If using hybrid (compute new value, hardcode new constant): The test documents the new value in a comment and asserts the new hex. The snapshot-regression property is preserved.
3. The isolation invariant tests (`test_m14_does_not_equal_m275_effective_version`) are structural and DO NOT depend on the exact hex value — these are already safe.

**Machines affected**: None (test-only change, no code change, no version invalidation).

**Key risk**: The brief's proposed helper `compute_effective_version_for_machine` for tests introduces manifest-file dependency in the test suite. If a CI environment is missing `slot_designer/configs/machine_manifests/` (e.g., a Docker image that excludes non-analyzer files), all tests using the dynamic helper would fail with `FileNotFoundError` rather than the intended assertion. Existing tests avoid this by using the hardcoded approach.

---

### Case Study 5: Cluster A DECLARED_DEPS RuntimeError — new catch scope

**Change**: Extend the error-surfacing `try/except` to include the `for _dep_key in _feature.DECLARED_DEPS: if _dep_key not in summary: raise RuntimeError(...)` block at PIA line 5073–5080.

**Direct effect**: DECLARED_DEPS `RuntimeError` is now caught, converted to `analyzer_init_error` dict, written to disk, and re-raised as `SystemExit(1)` instead of propagating as a raw `RuntimeError`.

**Cascade**:
1. `_batch_gen_worker.py:151` — previously would have had `_analyzer_mod.main()` raise `RuntimeError` (uncaught, propagated to the worker's outer exception handler). Now the worker receives `SystemExit(1)` via `rc != 0` (or via the `SystemExit` exception if in-process — same as topo-sort path). The `rc != 0` branch at line 154 fires consistently for all analyzer init errors.
2. No test currently injects a DECLARED_DEPS error and checks the JSON output. A new test is needed for this gap (analogous to `test_c1_init_error_surfacing.py` but testing disk I/O).
3. The DECLARED_DEPS check at lines 5073–5080 runs INSIDE the emit loop (`for _feature in _sorted_features:`). The emit loop runs AFTER the feature plugin imports and topo-sort. At this point, `summary` already has all pre-loop keys. The error affects one feature that declared a missing dep key — other features before it in the topological order may have already run `emit()`. The JSON written to disk would contain partial plugin output (some features successfully emitted) plus `analyzer_init_error`.

**Machines affected**: Any machine that has a DECLARED_DEPS typo in a plugin (currently: zero in production). Preventive change.

---

## §8 Fragility Hotspots (Cluster A/D/E specific, informational only)

| Rank | Symbol | Module | Direct callers | Transitive consumers | Estimated invalidation radius | Primary risk |
|---|---|---|---|---|---|---|
| 1 | `payouts_by_spin_type.py` (any byte change) | `features/payouts_by_spin_type.py` | `compute_hash()` called inside versioning | 253 machines × modes → 275 on-disk reports stale | D-1 fix changes bytes → all 253 machines get new effective_version | Single line fix (sort key) carries 253-machine invalidation |
| 2 | `bonus_chain_dynamics.py` (any byte change) | `features/bonus_chain_dynamics.py` | `compute_hash()` called inside versioning | All machines declaring the plugin (currently all non-variant machines per C6) | D-2+D-3 together change bytes once; invalidates all 253 machines' versions | Two D-fixes in one file = one hash flip, not two |
| 3 | `write_summary_json` placement in `main()` control flow | `player_impact_analyzer.py:5210` | Called once on success path | All 336 on-disk summaries (every run writes through this) | If misplaced in try/finally, success path could write before all plugins run | Structural: position in main() is load-bearing |
| 4 | `feature_errors` key name | `player_impact_analyzer.py:5090,5101` | 18 test assertions (`.get("feature_errors", {})`) | 0 production readers | Renaming would produce silent-pass tests (`.get()` with default returns `{}`) | The silent-pass mode makes this a hidden fragility |
| 5 | `_NON_M275_EFFECTIVE_VERSION` constants | `test_c3_5_isolation_m275_only.py:109`, `test_c3_5_m14_no_multiplier_wild.py:241` | Both values used in assertions | 3 test assertion sites across 2 files | Any D-1 or D-2+D-3 fix makes tests RED immediately | Required Cluster E migration before D-fixes are committed |
| 6 | `summary["analyzer_init_error"]` vs `summary["feature_errors"]` (two separate error fields) | PIA lines 5058, 5090 | 0 production readers, 14+18 test consumers respectively | 0 production downstream | If a future change collapses them to one key, 18 `.get("feature_errors", {})` calls return `{}` → silent test pass | The two-field architecture is a cognitive coupling risk — operators must know both fields exist |
| 7 | D-4 fix location (PIA inline vs. plugin) | `player_impact_analyzer.py:4817` or `collect_mechanic.py` | Determines whether `analyzer_version` or `effective_analyzer_version` scope is hit | If PIA: all 393 machines (analyzer_version flip); if collect_mechanic.py: only machines with collect_mechanic | Fix location choice determines blast radius | Location decision is a design choice with asymmetric impact |

---

## §9 Summary Statistics

| Metric | Count |
|---|---|
| Cluster A symbols audited | 4 (`analyzer_init_error`, `write_summary_json`, `SystemExit(1)` sites, `feature_errors`) |
| Cluster D symbols audited | 4 (`paylines` sort, `trigger_target`, `trigger_target_confidence`, `avg_bonus_payout`) |
| Cluster E symbols audited | 2 (`compute_effective_version_for_machine` side effects, hardcoded hex constants) |
| Production consumers of `analyzer_init_error` | 0 (test-only + operator-inspect) |
| Production consumers of `feature_errors` | 0 (test-only) |
| Test assertion sites for `analyzer_init_error` | 14 |
| Test assertion sites for `feature_errors` | 18 |
| Frontend consumers of `trigger_target` / `trigger_target_confidence` | 0 (not yet rendered) |
| Frontend consumers of `avg_bonus_payout` | 1 (`app.js:6196`, already null-safe) |
| Machines invalidated per D-1 fix | 253 non-variant machines |
| Machines invalidated per D-2+D-3 fix | 253 non-variant machines (C6 added bonus_chain_dynamics to all) |
| On-disk reports stale per D-1 or D-2+D-3 | ~275 |
| Hardcoded effective_version hex values requiring Cluster E migration | 3 constants in 2 files |
| Hardcoded base_hash values (NOT requiring migration) | 6 constants in 5 files (core/*.py unchanged) |
| Silent dependencies surfaced (new, not in C-phase audit) | 4 (try/finally ordering, paylines type assumption, DECLARED_DEPS gap, manifest dependency in dynamic test computation) |
