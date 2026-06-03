# impl-critic: payid symbol-combination enrichment (Phase P3 / analyzer data)

**Branch**: `claude/playtype-rearch`  
**Base**: `a5a7550` (HEAD at time of review)  
**State**: uncommitted worktree changes  
**Date**: 2026-06-03

---

## 1. Golden Re-Baseline Verification (highest-risk gate)

**CLEAN. Purely additive confirmed for all 12 fixtures.**

Independent leaf-path diff across all 12 golden fixtures:

| Fixture | Pre-existing leaves changed | New leaves | Unexpected new (not symbol_combo/covered_columns) |
|---|---|---|---|
| M275 x6 (all features) | 0 | +220 each | 0 |
| M14 x6 (all features) | 0 | +93 each | 0 |

Decomposition of M275 +220:
- `symbol_combo` leaves: +184 (all under `player_impact.payout_ids_top20` and `payouts_by_spin_type`)
- `covered_columns` leaves: +36 (all under `player_impact.payout_ids_top20` — new in C4; the 69 pre-existing `covered_columns` leaves in `payouts_by_spin_type` are C3 and unchanged)

Decomposition of M14 +93: all `symbol_combo` + `covered_columns` in `payout_ids_top20`.

The claim "purely additive: zero drift in existing leaves" is **independently verified**.  
Leaf count delta arithmetic: 4667+220=4887 (M275) and 6864+93=6957 (M14) both match the re-pinned test constants.

---

## 2. Decode Correctness

**CLEAN.**

Row decode formula `row = pos - col_1indexed * 100 + 1` verified independently for all 7 brief examples:

- M14 `4:7-7(99,200,301)`: pos=99→col0=0,row=0; pos=200→col0=1,row=1; pos=301→col0=2,row=2
- M14 `5:7-7(101,200,299)`: pos=101→col0=0,row=2; pos=200→col0=1,row=1; pos=299→col0=2,row=0
- M1 `1:11-11(100,200,300)`: all col0∈{0,1,2},row=1 (center)
- M275 `4:7-7(99,200,301)`: same as M14 case 1
- M268 `5:1-1(101,200,299)`: pos=101→col0=0,row=2; pos=200→col0=1,row=1; pos=299→col0=2,row=0

Cross-checked against test `_CASES` synthetic SSBC values: SSBC values in test cases are designed to produce the expected symbols at the decoded rows. All 7 cases produce the expected combo.

Edge case handling:
- `pos < 100` (e.g. pos=0, pos=50): `col_1idx=0`, `col0=-1` → `col0 < 0` guard aborts. CORRECT.
- `col >= len(ssbc_cols)`: `_c4_decode_ok = False; break`. CORRECT.
- `row >= len(col_syms)` or `row < 0`: `_c4_decode_ok = False; break`. CORRECT.
- Empty symbol at row (trailing dash): `if not _c4sym: _c4_decode_ok = False; break`. CORRECT.
- Empty positions list `[]`: the guard `if _c4_ssbc_cols is not None and _c3positions:` prevents decode entry. CORRECT.

---

## 3. RTP Parity

**CLEAN.**

`symbol_combo` is display-only. No new RTP accumulator was added. The `rtp_contribution_pp` formula `(wins_f / effective_bet_for_rtp) * 100.0` is **unchanged**. The diff to `player_impact_analyzer.py` only truncated the comment on that line (removed the M15 example text), not the formula.

The two PIA accumulation blocks (`payout_id_col_set_total`, `payout_id_symbol_combos_total`) at lines ~1703 and ~2491 are in **mutually exclusive paths**: the `--from-cache` loop (block 1) and the online batch-results loop (block 2). No double-counting.

PIA and `PayoutsBySpinType` plugin both read `payout_id_col_set` from the chunk dict but write to **separate output fields** (`payout_ids_top20.covered_columns` vs `payouts_by_spin_type[ST].covered_columns`). No coupling or double-counting.

---

## 4. Base-Hash Re-Pin Completeness

**CLEAN.**

Searched all `tests/**/*.py` for `== "adf08191dd9c"` (and single-quote variant) outside of comment lines. **Zero hits.** All pinned constants updated to `04691124fde6`.

Files with equality assertions updated:
- `test_c3_base_hash_flips_for_round_level_enrichment.py` (3 assertions)
- `test_c5_byte_identical_unrelated_fields.py` (1)
- `test_c6_byte_identical_bonus_chain.py` (1)
- `test_c6_carve_completion.py` (1)
- `test_analyzer_core_aggregator.py` (1)
- `test_analyzer_core_parser.py` (1)
- `test_phase_e_topdollar_choice.py` (1)
- `test_wave_2c_universal_features.py` (1)
- `test_c3_5_isolation_m275_only.py` (constant assignment, not == assertion)

The `test_no_old_hash_asserted_anywhere` gate in `test_p3_payid_symbol_enrichment.py` provides ongoing regression protection.

---

## 5. No Drift / Dead-Code / Silent-Swallow Audit

**One minor violation of `feedback_no_silent_swallow`.**

The new code in `parser.py` at the SSBC list comprehension:

```python
try:
    _c4_ssbc_cols = [str(col_txt).split("-") for col_txt in _c4_ssbc]
except Exception:
    _c4_ssbc_cols = None
```

This `except Exception: pass`-equivalent (sets `None` silently) technically violates `feedback_no_silent_swallow.md` which requires any exception path to persist `rc + stderr tail` to disk.

**Assessment**: The guarded expression `[str(col_txt).split("-") for col_txt in _c4_ssbc]` is **dead code for any realistic input**:
- `_c4_ssbc` has already passed `isinstance(list)` check — iteration is safe
- `str(col_txt)` converts any value (int, None, etc.) without raising
- `.split("-")` never raises on a string

The only conceivable exception would be from a custom class's `__str__` raising — impossible with JSON-deserialized data. No test exercises the except branch (untestable in practice).

**Severity: MINOR.** No production risk, but the pattern should not become a template for future exception handling.

---

## 6. Commit Hygiene / Staging List

**CLEAN for staged files. Explicit exclusion required for unstaged files.**

`configs/machines.json` has unstaged changes (codeSummaryMd5 updates for multiple machines). This is out of scope for P3 and must NOT be staged. The coordinator's brief excludes it.

Correct `git add` list (35 files):

```
fresh_slotlab/analyzer/core/parser.py
fresh_slotlab/analyzer/features/payouts_by_spin_type.py
fresh_slotlab/player_impact_analyzer.py
tests/analyzer/fixtures/M275_mode1_{collect_mechanic,bonus_chain,multiplier_profile,reel_marginal,upstream_feature,bankruptcy}_golden.json  (6)
tests/analyzer/fixtures/M14_mode1_{collect_mechanic,bonus_chain,multiplier_profile,reel_marginal,upstream_feature,bankruptcy}_golden.json     (6)
tests/analyzer/test_p3_payid_symbol_enrichment.py                          (new)
tests/analyzer/test_2a_byte_identical_collect_mechanic_carve.py
tests/analyzer/test_2b_byte_identical_bonus_chain_carve.py
tests/analyzer/test_3_byte_identical_upstream_feature_carve.py
tests/analyzer/test_4_byte_identical_multiplier_profile_carve.py
tests/analyzer/test_5_byte_identical_reel_marginal_carve.py
tests/analyzer/test_6_byte_identical_bankruptcy_carve.py
tests/analyzer/test_c2_payouts_by_spin_type_pattern_b.py
tests/analyzer/test_c3_5_isolation_m275_only.py
tests/analyzer/test_c3_base_hash_flips_for_round_level_enrichment.py
tests/analyzer/test_c3_enrichment.py
tests/analyzer/test_c3_schema_version_2.py
tests/analyzer/test_c3_trigger_marker_m275.py
tests/analyzer/test_c5_byte_identical_unrelated_fields.py
tests/analyzer/test_c6_byte_identical_bonus_chain.py
tests/analyzer/test_c6_carve_completion.py
tests/backend/test_analyzer_core_aggregator.py
tests/backend/test_analyzer_core_parser.py
tests/backend/test_phase_e_topdollar_choice.py
tests/backend/test_wave_2c_universal_features.py
session_artifacts/_arch_console/impl/p3_payid_symbols/brief.md
session_artifacts/_arch_console/impl/p3_payid_symbols/critique.md          (this file)
```

Do NOT stage: `configs/machines.json`, `session_artifacts/_arch/`, `session_artifacts/_impl/phase*/`, `slot_designer/` deletions (separate concern).

---

## 7. Production-Failure Thought Experiment

**10 concurrent analyzers hammering M275 simultaneously:**

The new accumulators are all local to the `parse_chunk_response` function call (no shared mutable state across concurrent requests). `payout_id_symbol_combos` is a `defaultdict(lambda: defaultdict(int))` initialized per-call. No threading concern.

The `payout_id_col_set_total` and `payout_id_symbol_combos_total` in PIA `main()` are function-local, not module-global. No cross-request contamination.

**Old cached chunks (pre-C4) feeding a fresh C4 analyzer:**  
Both PIA and plugin use `.get("payout_id_symbol_combos") or {}` tolerating absent key. `symbol_combo.dominant` will be `None` for all pids from old chunks. `distinct_symbols` will be `[]`. This is graceful degradation per the brief.

**Symbol_combo cross-ST semantic:**  
The same `dominant` value appears in every `(pid, ST)` row for a given pid. This is by design (aggregate across STs per brief). The `TestM275TriggerMarkerAnalyzerRuns.test_pid7_present_in_both_st_labels` test passes trivially since both ST rows carry the same aggregated combo — the assertion `"wild" in dominant.lower()` is satisfied by the shared aggregate regardless of whether BCM vs freespin have different individual dominant combos. This limits the test's discriminative power but is not a correctness bug.

---

## Stress Questions (13)

| # | Question | Finding | Verdict |
|---|---|---|---|
| Q1 | Did re-baseline mask any pre-existing leaf change? | 0 changed pre-existing leaves across all 12 fixtures | PASS |
| Q2 | Is decode formula correct for all 7 brief examples? | All verified independently | PASS |
| Q3 | Does `try/except Exception: _c4_ssbc_cols = None` violate `feedback_no_silent_swallow`? | Yes (technically), but it is dead code — `str/split` on a JSON-deserialized list cannot raise | MINOR |
| Q4 | Are the two PIA accumulation blocks double-counting? | No — `--from-cache` and online paths are mutually exclusive | PASS |
| Q5 | Remaining `== "adf08191dd9c"` assertions in non-comment lines? | Zero found across all test files | PASS |
| Q6 | Stale comments: constant `_EXPECTED_C3_BASE_HASH = "04691124fde6"` still says `# Phase E: ...adf08191dd9c` | Value correct, comment describes old phase — misleading but harmless | MINOR |
| Q7 | symbol_combo per (pid, ST) row uses cross-ST aggregate — is this correct? | Yes, documented by design. BCM vs freespin combos are blended in the aggregate. | PASS (known limitation) |
| Q8 | `test_empty_positions_no_combo_emitted_for_scatter_pid`: does assertion actually verify invariant? | No — `assert dominant is None or isinstance(dominant, str)` is tautological (always True). Should be `assert dominant is None`. | MINOR (weak test) |
| Q9 | Can `configs/machines.json` accidentally get staged? | Must be explicitly excluded — coordinator brief confirms exclusion | PASS (requires correct git add) |
| Q10 | `covered_columns` in `payout_ids_top20` — new in C4 or pre-existing? | New in C4 (+36 leaves for M275). C3 had it only in `payouts_by_spin_type`. Confirmed additive. | PASS |
| Q11 | Is there a test for the `except Exception: _c4_ssbc_cols = None` path? | No test, path is unreachable in practice | MINOR (dead code) |
| Q12 | Does `_parse_chunk_positions` helper correctly identify payids vs match-counts? | Yes — group(2) in 3-group regex and group(3) in 4-group inline regex both yield payid | PASS |
| Q13 | Does the inject-bug reliably produce RED? | Yes — center-row positions give wrong symbol (row→0 instead of 1); top-row positions give row=-1 → no combo → dominant=None | PASS |

---

## Memory Feedback Adherence

| Feedback file | Honored? | Notes |
|---|---|---|
| `feedback_no_hardcode` | YES | Decode formula is generic, no per-machine symbol names |
| `feedback_respect_existing_codebase` | YES | Reuses `attribute_lines_to_pay_ids`, extends existing C3 loop |
| `feedback_invariant_with_fallback_hides_drift` | YES | No new `_unattributed` bucket; RTP parity unchanged |
| `feedback_no_silent_swallow` | MINOR VIOLATION | `try/except Exception: _c4_ssbc_cols = None` in parser.py (dead code, see §5) |
| `feedback_enumerate_safety_paths` | YES | inject-bug recipe documented and mechanistically correct |
| `feedback_perf_claim_needs_e2e_event_stream` | YES | Subprocess-mode tests via `_run_pia()` on real cached chunks |
| `feedback_integration_test_argv` | YES | Real subprocess on real fixtures (not mocked) |

---

## Code-Level Bugs / Risks

None identified. Decode guards are correct. No uncaught exception paths in realistic data flows.

## Test-Level Gaps

1. **MINOR**: `test_empty_positions_no_combo_emitted_for_scatter_pid` (line 719): asserts `dominant is None or isinstance(dominant, str)` — this never fails regardless of dominant value. The intended assertion is `dominant is None`. No production risk (scatter pids genuinely have empty positions), but the test provides zero protection.

2. **MINOR**: No test explicitly verifies that when all positions in a round decode to `_c4_decode_ok=False` (e.g. out-of-range col), the previously valid combos from other records in the same round are preserved. By inspection of the code this is correct (decode abort is per-record, not per-round), but there's no unit assertion for it.

3. **MINOR**: The cross-ST tests (`test_pid7_st140_bcm_has_wild_combo`, `test_pid7_st126_freespin_has_wild_combo`) both assert on the same `pid_symbol_combos["7"]` aggregate (all STs blended). A bug that stored only BCM or only freespin combos would not be detected. Acceptable per brief's "decode is per-round, not per-ST" design decision.

## Claim-vs-Reality Gaps

1. **STALE COMMENT**: `_EXPECTED_C3_BASE_HASH = "04691124fde6"  # Phase E: ...adf08191dd9c` in `test_c3_base_hash_flips_for_round_level_enrichment.py` line 90 and `test_c3_5_isolation_m275_only.py` line 113. The value is correct; the trailing comment describes the Phase E transition (`adf08191dd9c`) not the P3 transition (`04691124fde6`). Code works correctly; comment is misleading history documentation.

2. **DOCSTRING MISMATCH**: `test_c3_base_hash_flips_for_round_level_enrichment.py`, `TestBaseHashFlipExpected.test_base_hash_matches_expected_c3_value` docstring still says "R-1 closure value (currently d8b8c138874a, phase-6)" — but the pin is now `04691124fde6`. The docstring body text is stale (mentions old intermediate values as the current value). No test impact.

---

## Verdict

**APPROVE-WITH-FIXES**

The implementation is fundamentally sound:
- Golden re-baseline is clean (0 pre-existing leaves changed)
- Decode formula is correct for all verified cases
- Edge cases handled correctly (empty positions, out-of-range, trailing dash)
- RTP parity preserved
- Base-hash re-pin complete (0 stale assertions)
- No double-counting in either accumulation path

Required fixes before commit/merge:
1. **REQUIRED** (before `git add`): Fix `test_empty_positions_no_combo_emitted_for_scatter_pid` assertion from `assert dominant is None or isinstance(dominant, str)` to `assert dominant is None`. The current assertion is tautological and provides zero regression protection for the edge case it claims to test.

Optional (can defer or accept-as-known):
1. Remove the `try/except Exception` around the SSBC list comprehension in `parser.py` (dead code; violates `feedback_no_silent_swallow` pattern even if unreachable in practice). Replace with direct assignment.
2. Update stale comment on `_EXPECTED_C3_BASE_HASH` constant in `test_c3_base_hash_flips_for_round_level_enrichment.py` and `test_c3_5_isolation_m275_only.py` to mention P3 rather than Phase E.
3. Update the docstring body of `test_base_hash_matches_expected_c3_value` to not describe `d8b8c138874a` as "currently" the value.
