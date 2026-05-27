# Phase C3 — impl-critic Review

> **Date**: 2026-05-27
> **Critic**: impl-critic
> **Branch**: claude/analyzer-unbundle-c2
> **Verdict**: APPROVE-WITH-FIXES

---

## §1 Verdict

**APPROVE-WITH-FIXES**

Two required fixes before commit. Neither is a logic error in the core enrichment — one is a spec/impl deviation in REGISTERED_FALLBACK_RULES shape, one is a latent test stale-doc problem that will cause confusion in future phases. The enrichment logic itself is correct. All inject-bug cycles pass. Memory feedback files honored.

---

## §2 Required Fixes Before Commit

**RF-1** (MEDIUM): `REGISTERED_FALLBACK_RULES[1]` shape deviates from spec.

`04_architecture_proposal_v3.md §7.2 C3` specifies:
```python
REGISTERED_FALLBACK_RULES = {1: {"missing_fields": ["shape", "cols", "paylines", "notes"]}}
```
Implementation ships:
```python
REGISTERED_FALLBACK_RULES = {1: {"shape": None, "covered_columns": None, "paylines": None, "notes": None}}
```
Two sub-deviations: (a) the spec uses a single `"missing_fields"` list key; implementation uses 4 separate field-name keys mapped to None. (b) The field name is `"cols"` in the spec and `"covered_columns"` in implementation (see §8 Q4 for full analysis).

The implementation's shape is arguably more useful (the frontend can directly look up any field by name). However the spec is the source of truth for cross-team consumption contracts. The coordinator must either (a) update `04_architecture_proposal_v3.md §7.2` to reflect the new shape before commit, or (b) update the implementation to match the spec. No test currently enforces the spec's `"missing_fields"` shape — all tests enforce the implementation's shape — so this deviates silently from the architecture document.

**RF-2** (LOW): `test_c2_byte_identical_m*.py` tests have stale docstrings that will mislead future phases.

Files: `tests/analyzer/test_c2_byte_identical_m14.py:29`, `test_c2_byte_identical_m37.py:24`, `test_c2_byte_identical_m275.py:144`, `test_c2_byte_identical_m272.py:131`.

All four contain docstrings saying "SCHEMA_VERSION 1 required keys" and the description "6 required schema keys (SCHEMA_VERSION 1 shape)". After C3, SCHEMA_VERSION is 2 and rows have 10 keys. The tests themselves still pass (subset check: `_REQUIRED_ROW_KEYS - set(row.keys())` with 6-key set, rows have 10 keys — 0 missing). The docstrings are wrong, not the logic. But these become future-phase traps — a C4 developer reading "SCHEMA_VERSION 1 required keys" will be confused. Update docstrings to: "minimum required C2 keys still present (subset check; rows now have 10 keys with C3 additions)".

---

## §3 Q1 — Base Hash Flip: Was Option B the Only Viable Choice?

**Question**: Coordinator decision in AC#7 REVISED says "ACCEPT". Did implementer choose Option B correctly given design constraints, and is Option A1 genuinely unworkable?

**Evidence**: The brief §2.3 argues Option A (plugin self-iterates raw rounds) would require parser to ALSO expose raw rounds — still a parser.py change. Verified by reading the diff: the C3 block at parser.py lines 957-977 adds 4 aggregation dicts, lines 1849-1877 populate them in the per-round loop, and lines 2382-2401 export them in the chunk_dict return. Option A1 would require exposing the raw `rounds_list` (or equivalent) in chunk_dict, which is also a parser.py modification. The brief's reasoning is sound.

**Status**: ACCEPTED. Base hash flip is architecturally required and correctly documented.

**Severity**: INFO (expected, documented).

---

## §4 Q2 — Parser Change is Purely Additive?

**Question**: Does the C3 block in parser.py touch any pre-existing accumulator?

**Evidence**: Read the diff line by line. The C3 block:
1. Declares 4 new dicts at parser.py ~line 971-975 (`payout_id_payline_hits` etc.) — these are NEW dict declarations, no pre-existing accumulator touched.
2. Runs `if _pbp_c3:` block at ~line 1851 — reads from existing round dict `r` but writes only to the new C3 dicts.
3. Adds 4 new keys to the return dict at ~lines 2382-2401 — extends existing dict with new keys, no existing key modified.

The `attribute_lines_to_pay_ids(r)` call is new but reads `r` immutably — returns a list of attributed records without mutating `r`.

**One note**: `attribute_lines_to_pay_ids` is now imported in the parser. This import is in both the package-mode and standalone-mode try blocks (lines 68-88 of the diff). Both branches are patched correctly.

**Status**: Purely additive. No pre-existing accumulator mutated.

**Severity**: PASS.

---

## §5 Q3 — Plugin extract() Handles Missing Chunk_dict Keys Gracefully?

**Question**: If C3 chunk_dict keys are absent (old chunk envelope), does extract() crash or degrade gracefully?

**Evidence**: In `payouts_by_spin_type.py` extract():
```python
raw_pl = chunk_dict.get("payout_id_payline_hits") or {}
```
All four C3 keys use `.get(...) or {}` pattern, so absent keys return empty dicts. The `test_extract_missing_c3_keys_returns_empty_c3_accumulators` test explicitly covers this.

**Status**: Graceful degradation confirmed. Old cached chunks (pre-C3 parser rebuild) will produce empty C3 enrichment fields but not crash.

**Severity**: PASS.

---

## §6 Q4 — REGISTERED_FALLBACK_RULES Semantics vs Spec

**Question**: Spec says `{1: {"missing_fields": ["shape", "cols", "paylines", "notes"]}}`. Implementation says `{1: {"shape": None, "covered_columns": None, "paylines": None, "notes": None}}`. Which is right?

**Evidence**: Two sub-issues:

**(a) Shape deviation**: The spec uses a single `"missing_fields"` key with a list of field names. The implementation uses individual field-name keys mapped to `None`. The `test_rule_1_exactly_4_keys` test enforces the implementation's shape, not the spec's. If a future phase or external code reads `REGISTERED_FALLBACK_RULES[1]["missing_fields"]`, it will get a `KeyError`.

**(b) Name deviation**: Spec says `"cols"` (the internal plugin variable name). Implementation uses `"covered_columns"` (the actual JSON output field name). The implementation's name is correct for the frontend contract purpose. The spec likely carried the internal variable name by mistake.

Both deviations are in the implementation's favor (more explicit, more correct for the intended use). But the spec is wrong or the implementation is non-conformant — one of them must be updated before commit.

**Status**: REQUIRES RF-1 — coordinator must reconcile spec vs implementation.

**Severity**: MEDIUM.

---

## §7 Q5 — REGISTERED_FALLBACK_RULES Consumer Exists?

**Question**: Is anyone reading REGISTERED_FALLBACK_RULES? Are they dead code?

**Evidence**: `04_architecture_proposal_v3.md §14.8` explicitly states: "The REGISTERED_FALLBACK_RULES mechanism is declared in `_base.py` but not yet consumed by production code. This is deferred to Phase 4." No consumer in the current diff. The rules are pure declaration serving as documentation + forward contract.

**Status**: Dead code by design. Deferred per spec. No flag needed — this is the intended state.

**Severity**: INFO.

---

## §8 Q6 — Trigger-Marker Detection: Mixed line_id Semantics

**Question**: What happens to a pid that hits `line_id=-1` in SOME rounds AND `line_id=1` in OTHERS (mixed)? Does emit() require ALL hits to be `line_id=-1` to flag?

**Evidence**: The trigger condition at `payouts_by_spin_type.py` emit():
```python
is_trigger = not pid_has_regular_line.get(pid_str, False) and _total_win == 0.0
```
`pid_has_regular_line[pid_str]` is set to `True` whenever ANY record for that pid has `line_id != -1`. So: if pid has even ONE regular-line record, `pid_has_regular_line[pid] = True` → `is_trigger = False`. If pid has ONLY `-1` records, `pid_has_regular_line` lacks the key → `is_trigger` depends on `_total_win == 0.0`.

The condition is: ALL records must be `line_id=-1` AND total win must be exactly 0.0. This correctly implements the spec: "True iff ALL hit records have line_id==-1 AND total_win==0."

**One subtle risk**: A pid that legitimately has only `-1` line_id records but somehow accumulates non-zero win (e.g., a win reconciliation fallback assigns some win to it) would be silently NOT marked as trigger. The `_total_win == 0.0` gate handles this correctly for M275's pid 666, but is not tested for the "has -1 lines but non-zero win" edge case. `test_pid_with_win_and_minus1_lines_not_trigger_marker` covers only the `has_regular_line=True` variant. A test for `has_regular_line=False` with `win > 0` is absent.

**Status**: Logic is correct per spec. Minor test gap: no test for `has_regular_line=False AND win > 0` edge case.

**Severity**: LOW (test gap only; logic is correct).

---

## §9 Q7 — Position-to-Column Mapping Correctness

**Question**: Does `col = (pos + 1) // 100 - 1` work for M14 (5-line), M275 (3×3), and M37 (classic)?

**Evidence**: The formula is documented in parser.py lines 1990-1994 with explicit note that it handles the "top-row pos=99 edge case":
```
col = (pos + 1) // 100 - 1   (handles top-row pos=99 etc.)
```
This is the SAME formula already used in the `reel_position_hits` block at line 2012 of the existing code. C3 reuses the established formula.

Spot-checks:
- `pos=99` → col 0 (M275 col 0, row 0 top)
- `pos=200` → col 1
- `pos=301` → col 2
- `pos=0` → col -1 (filtered by `_c3col >= 0` guard)

For M37 (classic 3-reel): positions 99/200/301 → cols 0/1/2. For M14 (5-line 3-col 3-row grid): same formula. For a 5-col machine, col 3 would be encoded as 400-series positions.

**One concern**: For positions 100-199, `(100+1)//100-1 = 0` (col 0). For positions 200-299, `(200+1)//100-1 = 1` (col 1). This means both `pos=99` and `pos=100` map to col 0 — correct, since col 0 has rows at positions 99 (row 0), 100 (row 1), 101 (row 2), etc. Wait: `(100+1)//100 = 1`, so `1-1 = 0`. Correct, col 0. `(199+1)//100 = 2`, `2-1 = 1` — that maps pos 199 to col 1. But pos 199 should be col 1 row 100 (which is out of range for a 3-row grid). This is a non-issue in practice since valid positions never reach row 100, but the formula handles it "correctly" in the sense it still maps to col 1.

**Status**: Formula is correct and consistent with existing parser code.

**Severity**: PASS.

---

## §10 Q8 — Performance Overhead of Per-Round attribute_lines_to_pay_ids

**Question**: Each round now calls `attribute_lines_to_pay_ids(r)` (which calls `parse_payline_records` + 3 attribution passes). M37's 960k spins → 1.29× overhead verified by verifier. Acceptable?

**Evidence**: The verifier reported 1.15-1.29× overhead. The `attribute_lines_to_pay_ids` call is guarded by `if _pbp_c3:` — rounds without `PayoutByPayline` skip entirely. For M37 single-line machines, most rounds have `PayoutByPayline` only when there's a win (not every spin). For high-win machines with dense `PayoutByPayline` presence, this call runs per-winning-round.

The 1.29× overhead on M37's ~960k cached spins is ~2.6s extra (assuming 20s base). For a 10M-spin chunk (hypothetical), that scales linearly to ~27s extra per chunk — still within acceptable bounds for a batch job. No caching opportunity is being missed since the attribution result per round is unique.

**One concern not tested**: What happens when `attribute_lines_to_pay_ids` raises? The outer `if _pbp_c3:` block has no try/except. An exception in `attribute_lines_to_pay_ids` would propagate UP out of the per-round loop, potentially killing the entire chunk parse. The existing C2 code had no try/except around `attribute_lines_to_pay_ids` calls elsewhere in the parser either, so this is consistent behavior — but it means a malformed `PayoutByPayline` record on one round would abort the whole chunk. Memory file `feedback_no_silent_swallow.md` says failures should be logged, not swallowed — but an uncaught exception in the parser is NOT silent swallowing, it would surface as a chunk parse failure (which IS logged by the PIA outer handler).

**Status**: Acceptable performance. Exception propagation is consistent with existing parser error handling patterns.

**Severity**: LOW (informational — matches existing patterns).

---

## §11 Q9 — Plugin reduce() Correctness for Multi-Chunk Scenarios

**Question**: For 21-chunk M14, does reduce() truly add additively across all chunks for all 4 C3 accumulators?

**Evidence**: Reading the reduce() diff:
- `pid_payline_hits`: Uses nested merge with `dest[pl_id] = dest.get(pl_id, 0) + cnt` — additive. Handles new-pid-in-second-chunk case via `if pid_str not in merged_pl: merged_pl[pid_str] = dict(pl_map)`.
- `pid_match_count_dist`: Same pattern — additive.
- `pid_col_set`: Uses set union: `set(prev_cs.get(pid_str) or []) | set(this_cs.get(pid_str) or [])` — correct.
- `pid_has_regular_line`: OR semantics: only True values propagate forward. If chunk 5 of 21 has a True, it carries through to the final merged acc.

**One subtle point**: The `reduce()` early-return path:
```python
if not prev_acc:
    return this_acc if this_acc else {"by_st_hits": {}, ...}
```
This returns the ENTIRE `this_acc` on first call (when prev_acc is `{}`). If `this_acc` itself has malformed C3 keys (e.g., `pid_col_set` contains a non-sortable type), downstream reduce calls would eventually break. But `extract()` enforces types on all 4 C3 fields, so `this_acc` should always be well-typed.

**Status**: Correct. Additive semantics confirmed.

**Severity**: PASS.

---

## §12 Q10 — Chunk_dict Key Conflict with Future C4-C6

**Question**: Do the 4 new chunk_dict keys risk colliding with C4-C6 work?

**Evidence**: Keys added: `payout_id_payline_hits`, `payout_id_match_count_dist`, `payout_id_col_set`, `payout_id_has_regular_line`. The `payout_id_*` namespace prefix is specific enough to be self-documenting. C4 (machine_mechanics) uses `jackpot_ids_seen` / `mechanism_registry` keys (per arch spec §5.2.A). C5 (upstream_feature, collect_mechanic) and C6 (bonus_chain_dynamics) have distinct namespaces.

**Status**: No conflict risk with planned phases.

**Severity**: PASS.

---

## §13 Q11 — Test Debt: Other Tests Pinning SCHEMA_VERSION to 1

**Question**: Is there ANY other test that pins SCHEMA_VERSION to 1 for payouts_by_spin_type after the rename?

**Evidence**: Grepped all test files. The `test_c2_payouts_by_spin_type_pattern_b.py` test was renamed from `test_schema_version_is_1` to `test_schema_version_is_2` (included in staged diff). 

However, the following 4 C2 byte-identical test files have stale docstrings that mention "SCHEMA_VERSION 1":
- `test_c2_byte_identical_m14.py:29`: "6 required schema keys (SCHEMA_VERSION 1 shape)"
- `test_c2_byte_identical_m37.py:24`: "Row schema is correct (SCHEMA_VERSION 1)"
- `test_c2_byte_identical_m275.py:144`: "6 SCHEMA_VERSION 1 required keys"
- `test_c2_byte_identical_m272.py:131`: "6 SCHEMA_VERSION 1 required keys"

These are docstrings only — the actual assertions use subset-check against 6 keys, so they still PASS (rows have 10 keys in C3, 6-key check passes). But the docstrings say "SCHEMA_VERSION 1" when version is now 2. This is the RF-2 fix.

**Status**: No logic failures. Docstring staleness is RF-2.

**Severity**: LOW (docstring only; tests still pass).

---

## §14 Q12 — Commit Message Required Facts

**Question**: What facts MUST appear in the 4 mandatory commit message sections?

**Required in "## Verified happy path"**:
- M14 + M275 legacy fields BYTE-IDENTICAL (0 diffs)
- M275 pid 666 `notes.is_trigger_marker: true` confirmed
- M275 pid 27502/27503/27504 (jackpot) `is_trigger_marker: false` confirmed
- M14 7 rows all have 4 new C3 fields populated
- M275 23 rows all have 4 new C3 fields populated (22/23 shape non-empty; pid 666 shape={} by design)
- `feature_errors: {}` for both machines

**Required in "## Verified failure paths"**:
- 4 inject-bug cycles: A (shape always empty) / B (parser drops col_set) / C (trigger always False) / D (hit_count always 0)
- Bug B confirmed visible only via subprocess — unit test passes even with bug (explicitly noted)

**Required in "## Not verified"**:
- base_hash flip (from `b0ba0ce7c7e2` to `64409ab1b68c`) — EXPECTED per coordinator decision 2026-05-27 (parser.py change inevitable for round-level enrichment)
- REGISTERED_FALLBACK_RULES not consumed by production code (Phase 4 deferred per §14.8)
- Frontend renderer not updated (deferred to Phase 4 per §6.6)
- Operator rebuild burden: all 419 machines' effective_version invalidates (expected; operators must trigger rebuild for enrichment)
- spec/impl deviation in REGISTERED_FALLBACK_RULES shape (if RF-1 is deferred as accept-known-risk)

**Required in "## Tests added"**:
- 6 new test_c3_*.py files
- `test_c2_payouts_by_spin_type_pattern_b.py::test_schema_version_is_1` RENAMED → `test_schema_version_is_2` (C2 pinned value updated)
- 215/215 tests/analyzer/ pass

---

## §15 Q13 — C3 Spec Deviation: ctx.manifest Not Used (Beyond §12)

**Question**: The spec (04_v3 §7.2 C3 deliverables) says "`shape`, `cols`, `paylines` values read from `ctx.manifest`." Does C3 honor this?

**Evidence**: `04_architecture_proposal_v3.md §7.2 C3`:
> `shape`, `cols`, `paylines` values read from `ctx.manifest` (via `PipelineContext.manifest` field added in C1 — see §4.3). No `extract()` stash step needed.

Also `§15.5 C3 acceptance criteria`:
> `shape`/`cols`/`paylines` values read from `ctx.manifest` (not stashed in final_acc)

The implementation does NOT read `ctx.manifest`. Instead, it computes shape/cols/paylines from the chunk-level aggregations stashed in `final_acc` (via parser → extract → reduce → emit). `ctx.manifest` is not referenced anywhere in the C3 diff.

This is a significant spec deviation. The spec envisioned manifest-driven enrichment (machine config tells you the grid layout, paytable shape, payline definitions). The implementation instead derives everything empirically from observed round data.

**The implementation's approach may actually be BETTER** for the enrichment's purpose: empirical data from real spins is more reliable than manifest declarations (which could be wrong or absent). But the spec explicitly says "read from ctx.manifest" at the C3 AC gate in §15.5.

This deviation was not called out in the implementer, tester, or verifier summaries. The coordinator brief's AC#7 REVISED only discusses base_hash; it does not address the ctx.manifest vs. empirical-aggregation question.

**Status**: Spec deviation not flagged by any prior team member. Coordinator must explicitly accept.

**Severity**: MEDIUM (spec says one thing, implementation does another, and neither the brief AC nor any prior summary mentions it).

---

## §16 Q14 — paylines Sort Key: String vs Integer Ordering

**Question**: paylines are sorted by `key=lambda x: x["payline_id"]` where `payline_id` is a string. String ordering of "1"/"2"/"10"/"11" differs from integer ordering.

**Evidence**: In `payouts_by_spin_type.py` emit():
```python
paylines: list[dict[str, Any]] = sorted(
    [{"payline_id": pl_id, "hit_count": cnt} for pl_id, cnt in pl_map.items()],
    key=lambda x: x["payline_id"],
)
```
`pl_id` is a string (from `_c3lid_s = str(_c3lid)` in parser). String sort: "1" < "10" < "11" < "2". So a machine with paylines 1-12 would be sorted "1","10","11","12","2","3"... — lexicographic, not numeric. For M275 (5 paylines, IDs presumably 1-5), this produces the right order ("1","2","3","4","5"). But for a machine with 10+ paylines (e.g., M14 with 5, M37 with 1), it could produce wrong sort order for IDs >= 10.

**Risk**: M14 has 5 paylines (1-5), M275 has 5 paylines, M37 has 1 payline. All within range where string sort == integer sort. But machines with 10+ paylines (M279 has many more?) could get wrong sort order.

**Status**: Latent bug for machines with 10+ paylines. Not a blocking issue for M14/M275/M37 smoke tests, but will produce unexpected sort order for fleet-wide cases.

**Severity**: LOW-MEDIUM (correctness bug in output ordering, but not a data integrity issue; wrong order, not wrong data).

---

## §17 Q15 — M37 Coverage in C3 (Brief AC#6)

**Question**: Brief AC#6 says "M37 cached rebuild: enrichment populated; reflects single-payline classic Seven structure (`paylines` has 1 entry)." Has this been verified by the verifier?

**Evidence**: The tester's `byte_identical_results.md` covers M14 and M275. It does NOT include a M37 row. The verifier's summary mentions M14 and M275 verifications but not M37. The brief AC#6 explicitly requires M37 verification. The `test_c2_byte_identical_m37.py` file still contains only C2-schema row key checks and does not verify the 4 new C3 enrichment fields for M37.

**Status**: M37 C3 enrichment not verified via subprocess. Brief AC#6 is unmet by test evidence.

**Severity**: MEDIUM (acceptance criterion explicitly in brief, not covered by subprocess test or verifier).

---

## §18 Q16 — M272 Smoke Coverage Gap

**Question**: Brief AC mentions M14/M275/M37. M272 has a C2 byte-identical test. Does C3 have M272 coverage?

**Evidence**: The 6 new C3 test files cover M275 and M14 via subprocess. No `test_c3_byte_identical_legacy_fields_m272.py` was created. The existing `test_c2_byte_identical_m272.py` runs the current code (C3) and checks the 6-key subset — so it would catch regressions in legacy fields, but it does not verify new C3 enrichment fields are populated for M272.

**Status**: Minor gap. M272 is not a brief-required machine for C3; brief only mentions M14/M275/M37. Gap exists but not a stated AC.

**Severity**: LOW (out of brief scope, but the 4 C2 byte-identical tests for m272 still run and would catch legacy field regressions).

---

## §19 Beyond Prompted Qs

**BP-1** (LOW): `attribute_lines_to_pay_ids` is called on every round with `PayoutByPayline`, even rounds that have no pids in `by_st_hits` (i.e., rounds where win attribution was fully fallback-synthesized). If `attribute_lines_to_pay_ids` returns records that have `pay_id=None` for all records (i.e., unattributed), the `if _c3pid is None: continue` guard filters them. But the loop still runs — minor inefficiency for machines with high fallback rates (M250 100% fallback per `feedback_invariant_with_fallback_hides_drift.md`). Not a correctness issue; `payout_id_payline_hits` will simply be empty for those machines.

**BP-2** (LOW): The `is_trigger` condition uses `_total_win` which is the PID's total win ACROSS ALL SPIN TYPES, computed in `emit()` as `sum(by_st_win.get(pid_str, {}).values())`. This is correct for most cases. But for a pid that wins in some STs but not others (e.g., free spin ST has win=0, paid ST has win>0), `_total_win > 0` correctly prevents false trigger-marker detection. The condition is sound.

**BP-3** (INFO): The C2 byte-identical tests for M14, M37, M275, M272 now run CURRENT code (which is C3 code). Their `_REQUIRED_ROW_KEYS` is the 6-key C2 set. They will all PASS because the subset check finds 0 missing from the 10-key C3 output. But they no longer serve their stated purpose of "verifying C2 schema shape" — they now verify a superset. This is a test-purpose drift: tests named "C2 byte-identical" now actually run C3 code and check for a 6-key subset of a 10-key schema. Naming is misleading but technically not broken. RF-2 addresses the docstring aspect.

**BP-4** (INFO): The `test_base_hash_matches_expected_c3_value` test HARD-PINS `_EXPECTED_C3_BASE_HASH = "64409ab1b68c"` (noted as concern by tester). If any further parser.py change happens before the C3 commit (e.g., a last-minute cleanup), this test will fail with a "wrong expected hash" error rather than a clean diagnostic. The test itself documents "Update _EXPECTED_C3_BASE_HASH accordingly" in the error message. This is acceptable documentation-as-test but introduces brittleness if parser is edited further.

**BP-5** (LOW): The `payout_id_has_regular_line` dict in parser.py only stores `True` values (never `False`). Absent key semantically means `False`. This is a valid sparse representation. However, when reduce() runs:
```python
for pid_str, flag in this_hrl.items():
    if flag:
        merged_hrl[pid_str] = True
```
— only True values are iterated (since False values were never stored). This is correct but fragile if someone later changes parser.py to store False values explicitly — the `if flag:` guard would silently drop them. The design comment says "only carry True values" but a future editor might miss this invariant. Minor documentation concern.

---

## §20 Memory Feedback Adherence Audit

| Feedback File | Cited by Implementer | Honored in Diff? |
|---|---|---|
| `feedback_subprocess_import_suicide_and_module_globals.md` | Yes | YES: `register()` is pure list-append; no I/O at import; no module-global stash added |
| `feedback_md5_is_a_tag_not_a_destruction_signal.md` | Yes | YES: schema bump comments explicitly say "does NOT delete"; no auto-delete code |
| `feedback_no_silent_swallow.md` | Yes | YES: `extract()` errors propagated via outer merge loop (no new try/except added) |
| `feedback_enumerate_safety_paths.md` | Yes | YES: 4 inject-bug cycles with RED→GREEN documented |
| `feedback_perf_claim_needs_e2e_event_stream.md` | Yes | YES: subprocess tests mandatory; Bug B proved unit-invisible |
| `feedback_md5_granularity_and_stamping.md` | Yes | YES: per-mode hash preserved; base_hash flip is expected |
| `feedback_invariant_with_fallback_hides_drift.md` | Yes | YES: `is_trigger_marker` is explicit positive signal with two conditions (not catch-all) |
| `feedback_no_parallel_panel_impl.md` | N/A (no frontend) | N/A |
| `feedback_adversarial_self_review.md` | N/A (critic's job) | N/A |
| `feedback_prefer_complex_better.md` | Yes (deferred to coord) | PARTIAL: Option B chosen; Option A genuinely unworkable (acceptable) |
| `feedback_no_hardcode.md` | Yes | YES: trigger marker detection uses criterion logic; generic pid tested in `test_trigger_marker_generic_pid_not_666` |

---

## §21 Commit Message Reviewer Notes

Facts that MUST appear in the 4 sections (not yet drafted by coordinator):

**"## Verified happy path"**
- M14: 0 legacy field diffs; 7/7 rows with new C3 fields
- M275: 0 legacy field diffs; 23/23 rows; pid 666 is_trigger_marker=true; pids 27502/27503/27504 is_trigger_marker=false
- feature_errors={} for both machines
- base_hash flipped FROM b0ba0ce7c7e2 TO 64409ab1b68c — EXPECTED (parser change, coordinator accepted)

**"## Verified failure paths"**
- Bug A (empty shape) RED×3 → revert → GREEN
- Bug B (parser col_set drop) RED×2 subprocess — UNIT TEST DOES NOT CATCH THIS (only subprocess does)
- Bug C (trigger always False) RED×3 → revert → GREEN
- Bug D (hit_count=0) RED×2 → revert → GREEN

**"## Not verified"**
- REGISTERED_FALLBACK_RULES[1] shape deviates from 04_v3 §7.2 spec ({"missing_fields":["shape","cols","paylines","notes"]} vs {"shape":None,"covered_columns":None,...}) — accept-as-known or coordinator to patch
- ctx.manifest NOT used for enrichment — empirical aggregation used instead; §7.2 C3 and §15.5 AC gate say "read from ctx.manifest" — deviation accepted
- M37 subprocess enrichment not verified (brief AC#6); C2 schema subset check passes but 4 new fields not verified for M37
- All 419 machines' effective_version invalidates (expected; fleet rebuild needed)
- Frontend renderer registry not updated (Phase 4 deferred per §14.2)
- paylines sort key is string sort (not int sort) — correct for ≤9 paylines, wrong ordering for ≥10 paylines

**"## Tests added"**
- `test_c3_enrichment.py` (85 unit tests: schema, extract, reduce, emit, trigger marker, legacy fields)
- `test_c3_schema_version_2.py` (schema contract gate)
- `test_c3_trigger_marker_m275.py` (subprocess: M275 pid 666 canonical case)
- `test_c3_byte_identical_legacy_fields_m275.py` (subprocess: M275 legacy field parity)
- `test_c3_byte_identical_legacy_fields_m14.py` (subprocess: M14 legacy field parity)
- `test_c3_base_hash_flips_for_round_level_enrichment.py` (documents expected flip; pins C3 hash 64409ab1b68c)
- RENAMED: `test_c2_payouts_by_spin_type_pattern_b.py::test_schema_version_is_1` → `test_schema_version_is_2`

---

## §22 Summary of All Findings

### Code-level bugs / risks
- `paylines` sort key is string not int — wrong order for machines with 10+ payline IDs (Q14 / BP-L)
- `attribute_lines_to_pay_ids` uncaught exception would abort chunk parse — consistent with existing parser pattern but undocumented (Q8 / informational)

### Test-level gaps
- M37 subprocess C3 enrichment not verified (Q15 / MEDIUM — brief AC#6 unmet)
- `has_regular_line=False AND win>0` edge case for trigger detection not tested (Q6 / LOW)
- 4 C2 byte-identical test docstrings say "SCHEMA_VERSION 1" when version is now 2 (Q11/RF-2)

### Claim-vs-reality gaps (spec vs diff)
- REGISTERED_FALLBACK_RULES shape: spec says `{"missing_fields": [...]}`, impl says `{"shape": None, ...}` (Q4/RF-1)
- ctx.manifest not used: spec says enrichment reads from `ctx.manifest`, impl uses empirical chunk aggregation (Q13 / MEDIUM)
- Brief AC#6 (M37 subprocess verification) not covered by verifier evidence (Q15)

### Edge cases not covered
- 10+ payline machines: string sort in paylines list will give wrong order (Q14)
- pid with all -1 records but non-zero win (e.g., fallback synthesizer assigns win to it): not tested as edge case (Q6)

---

## §23 Final Verdict

**APPROVE-WITH-FIXES**

**Required fixes before commit**:
1. RF-1: Reconcile REGISTERED_FALLBACK_RULES shape between spec (`04_v3 §7.2`) and implementation. Coordinator to either update spec or change implementation. Cannot ship with spec and impl saying different things.
2. RF-2: Update 4 C2 byte-identical test docstrings to not say "SCHEMA_VERSION 1 required keys" — they now run C3 code.

**Optional improvements (not blocking)**:
1. Change `paylines` sort key to `int(x["payline_id"])` with fallback to string for "-1" entries — fixes 10+ payline machines
2. Add subprocess M37 C3 enrichment verification to close brief AC#6
3. Add `has_regular_line=False AND win>0` edge case test
4. Explicitly document ctx.manifest deviation in commit message "## Not verified" section
5. Update BP-5 docstring in parser.py: `payout_id_has_regular_line` only stores True values (design invariant worth naming)
