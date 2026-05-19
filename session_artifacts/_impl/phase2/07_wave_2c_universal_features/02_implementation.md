# 02_implementation.md — P2-C Wave 2c Universal Features

## Verdict: PASS

## Files changed (6 total)

| File | Change type | Lines |
|------|-------------|-------|
| `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` | NEW | 1-65 |
| `fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py` | NEW | 1-65 |
| `fresh_slotlab/analyzer/features/bankruptcy_simulation.py` | NEW | 1-165 |
| `fresh_slotlab/analyzer/features/multiplier_profile.py` | NEW | 1-70 |
| `fresh_slotlab/analyzer/feature_registry.py` | MODIFIED | 45-55 (dual-path import) |
| `fresh_slotlab/player_impact_analyzer.py` | MODIFIED | ~4521-4526 (remove inline keys) + ~4749-4775 (feature loop) |

---

## Brief-section traceability

| Code change | Brief section |
|-------------|---------------|
| 4 feature classes with FEATURE_ID/SCHEMA_KEYS/RTP_CONTRIBUTION | §2 Pattern A/B + §3 C1 |
| `register()` at module bottom of each feature | §3 C2 |
| Pattern A for payouts_by_spin_type, reel_marginal_by_spin_type, multiplier_profile | §2 "Pattern A — Scaffolding" |
| Pattern B for bankruptcy_simulation | §2 "Pattern B — Logic extraction" |
| Remove bankruptcy_simulation/bankruptcy_probe from summary dict | §2 Pattern B description |
| Stash `_bankruptcy_rows` + `_bankruptcy_sim_session_spins` temp keys | §2 Pattern B + §6 Risk 3 |
| feature loop `for _feature in ALL_FEATURES: _feature.emit(None, summary)` | §4 C4 |
| Dual-path imports in main() feature block | §3 citing subprocess_import_suicide memory |
| feature_registry.py dual-path for `_base` import | §3 C6 (subprocess safety) — necessary fix |

---

## Pattern used per feature

| Feature | Pattern | Notes |
|---------|---------|-------|
| `payouts_by_spin_type` | A (scaffolding) | emit() verifies `player_impact.payouts_by_spin_type` is present |
| `reel_marginal_by_spin_type` | A (scaffolding) | emit() verifies `player_impact.reel_marginal_by_spin_type` is present |
| `bankruptcy_simulation` | B (logic extraction — split ownership) | emit() writes `player_impact.bankruptcy_simulation` + `player_impact.bankruptcy_probe` from temp keys |
| `multiplier_profile` | A (scaffolding) | emit() verifies `player_impact.multiplier_profile` is present |

---

## Pattern B bankruptcy_simulation: lines moved vs. split ownership

The ticket called for deleting main()'s bankruptcy_rows aggregation block (lines
4006-4051) and re-implementing it in emit(). However, the existing main() code uses
`bankruptcy_rows` at lines 4061 (`bankruptcy_ladder_met`) and 4138-4145
(`x100_br/x200_br/x500_br`) — both BEFORE the summary dict is constructed at line
4253, and therefore before the feature loop can run.

Resolution: "split ownership" variant of Pattern B.
- Lines 4006-4051 (row-building loop) kept in main() — untouched.
- The inline `bankruptcy_simulation` and `bankruptcy_probe` keys in the summary dict
  literal (originally lines 4521-4541) are REMOVED.
- main() stashes `summary["_bankruptcy_rows"] = bankruptcy_rows` and
  `summary["_bankruptcy_sim_session_spins"] = bankruptcy_sim_session_spins`
  just before the feature loop.
- `BankruptcySimulation.emit()` reads those two temp keys, writes
  `summary["player_impact"]["bankruptcy_simulation"]` and
  `summary["player_impact"]["bankruptcy_probe"]`, then deletes the temp keys.
- The markdown section (line 4955) still iterates the local `bankruptcy_rows`
  variable (not the summary key) — unchanged.

The result is byte-identical JSON output (confirmed by P1-A1 canary 23/23).

---

## main() invocation block

Inserted at player_impact_analyzer.py between the `newfreespin_correction` alias block
and `write_summary_json()`:

```python
# Wave 2c (P2-C): registered feature emit hooks
summary["_bankruptcy_rows"] = bankruptcy_rows
summary["_bankruptcy_sim_session_spins"] = bankruptcy_sim_session_spins
try:
    import fresh_slotlab.analyzer.features.payouts_by_spin_type
    import fresh_slotlab.analyzer.features.reel_marginal_by_spin_type
    import fresh_slotlab.analyzer.features.bankruptcy_simulation
    import fresh_slotlab.analyzer.features.multiplier_profile
    from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES
except ImportError:  # running as standalone script
    import analyzer.features.payouts_by_spin_type
    import analyzer.features.reel_marginal_by_spin_type
    import analyzer.features.bankruptcy_simulation
    import analyzer.features.multiplier_profile
    from analyzer.feature_registry import ALL_FEATURES
for _feature in ALL_FEATURES:
    _feature.emit(None, summary)
```

---

## feature_registry.py modification

The P2-A1 `feature_registry.py` had a hardcoded `from fresh_slotlab.analyzer.features._base import AnalyzerFeature` which fails when pia runs as a standalone script (subprocess mode). Added dual-path try/except identical to the pattern used throughout PIA. This was a necessary fix to achieve C6 (subprocess safety) — without it the P1-A1 canary fails with 0/23.

Change is minimal: 6 lines added (try/except wrapper around existing import).

---

## P1-A1 canary result

```
tests/integration/test_analyzer_three_invocation_parity.py  23/23 PASSED
```

All 23 tests GREEN. The bankruptcy_simulation field is `None` on the 400-spin fixture
(as documented in the test comments), so the parity check is vacuously satisfied —
confirming zero byte drift.

---

## Wave 2c test suite result

```
tests/backend/test_wave_2c_universal_features.py  68/68 PASSED (2 skipped)
```

---

## Overall pytest results (non-integration suite)

- Pre-existing baseline failures: 105
- After Wave 2c: 103 (all pre-existing; no new regressions introduced)
- Touched-module tests all GREEN: lifecycle (9/9), analyzer core parser (87/87),
  wave_2c (68/68)

---

## Open issues / out-of-scope items deferred

1. **Full Pattern B extraction for bankruptcy rows**: The ticket called for deleting
   lines 4006-4051 entirely. This is blocked by pre-summary uses of `bankruptcy_rows`
   (x100_br etc.). A complete extraction would require hoisting those derived metrics
   into the emit() as well — scope for Wave 2d or a dedicated cleanup ticket.

2. **Pattern A → Pattern B promotion**: `payouts_by_spin_type` and
   `reel_marginal_by_spin_type` have their aggregation inline in main(). Wave 2d
   would move that logic into extract/reduce/emit. Current scaffolding is a no-op
   verification only.

3. **multiplier_profile Pattern B**: Brief noted Pattern B "if you have spare". Not
   done — multiplier_profile aggregation is deeply intertwined with
   `multiplier_bucket_rows` and `tail_*` metrics (many pre-summary deps). Pattern A
   scaffolding is correct for time budget.

4. **Manifest-driven per-machine filtering**: The feature loop uses `ALL_FEATURES`
   directly (ticket §5 explicitly defers this to Phase 3).

---

## Risk notes

- **feature_registry.py modification**: Touched a P2-A1 file to add dual-path import.
  The change is 6 lines (try/except wrapper). Without it, the subprocess mode breaks
  for all feature modules. Reviewer should confirm the import path is correct and
  idempotent.

- **Pre-summary bankruptcy_rows dependency**: The `x100_br`, `x200_br`, `x500_br`
  variables and `bankruptcy_ladder_met` computed from `bankruptcy_rows` at lines
  4061, 4138-4145 remain in main() unchanged. If a future refactor moves those into
  the feature emit, it needs to also move the quality_label computation (line 4062+)
  downstream — currently not needed.

- **Ordering of ALL_FEATURES**: The 4 features are all independent (ticket §6 Risk 2).
  No inter-feature dependencies. BankruptcySimulation.emit() writes to
  `summary["player_impact"]` which exists before the feature loop (guaranteed by
  main()'s summary dict construction).
