# Phase C3.5 — impl-critic critique

> Critic: impl-critic agent
> Date: 2026-05-27
> Phase: C3.5 — multiplier_wild plugin
> Base commit: 8cda1ab (C3)
> Status: APPROVE-WITH-FIXES (1 required fix, multiple informational)

---

## §1 Verdict

**APPROVE-WITH-FIXES**

One required fix before commit: the `test_c3_base_hash_flips_for_round_level_enrichment.py` test file has a stale inline comment in `test_base_hash_matches_expected_c3_value` (line 91 class docstring still says "C3 (64409ab1b68c)") that is now factually wrong after the hash update. This is a documentation accuracy issue in a pinning test — the value was updated correctly but the surrounding prose was not, which will mislead future maintainers reading the test. All other concerns are informational risk items (accept-as-known-risk).

No blocking bugs found in the plugin implementation, registration, or isolation invariants.

---

## §2 Required fixes before commit

**Fix 1** — `tests/analyzer/test_c3_base_hash_flips_for_round_level_enrichment.py`, line 91

The class docstring and test docstring at line 91 and 121 still reference "64409ab1b68c" as the C3 value in prose, even though `_EXPECTED_C3_BASE_HASH` was correctly updated to `fa440e3eb5f6` at line 77. A future reader will see the heading "base_hash flipped from C2 (b0ba0ce7c7e2) to C3 (64409ab1b68c)" and the constant value `fa440e3eb5f6` and rightly wonder which is correct.

File: `/tests/analyzer/test_c3_base_hash_flips_for_round_level_enrichment.py`
- Line 91: class docstring reads `"""base_hash flipped from C2 (b0ba0ce7c7e2) to C3 (64409ab1b68c) — EXPECTED."""`
- Line 121: method docstring reads `"""base_hash must be the known post-C3 value (64409ab1b68c).`
- These two stale references contradict the correct constant at line 77.

Change the class docstring and method docstring to reference `fa440e3eb5f6`, consistent with the updated constant. The inline comment on line 77 already explains the history ("C3.5: updated post-C3-fix-pass parser comment addition that flipped 64409ab1b68c -> fa440e3eb5f6").

---

## §3 Q1 — Per-machine isolation truly preserved?

**VERIFIED CLEAN.**

Confirmed from reading `multiplier_wild.py`: the file lives in `fresh_slotlab/analyzer/features/` (NOT `core/`). The comment block at lines 46-51 correctly explains why base_hash is unaffected. The test at `test_c3_5_isolation_m275_only.py:137` pins `_C3_BASE_HASH = "fa440e3eb5f6"` and asserts against `compute_base_analyzer_version()` — same value used in `test_c3_5_isolation_m275_only.py:81`.

`byte_identical_results.md` confirms: base_hash `fa440e3eb5f6` UNCHANGED, M275 effective_version flipped to `2ef11cd69c8d`, M14/M37/M272 all remain `dd2ab55ef022`.

One minor tension: the brief §4 AC#2 says base_hash should be `64409ab1b68c` (the original C3 value before the C3 fix-pass), but both `byte_identical_results.md` and the tests use `fa440e3eb5f6`. The brief is stale at this point — it pre-dates the C3 fix-pass that changed the hash. This is documented as known debt (the inline comment on line 77 of the test file explains it). No action needed.

---

## §4 Q2 — 5-site registration coverage

**VERIFIED — ALL 5 SITES PRESENT.**

Counted from `git diff HEAD` output and direct grep:

1. PIA from-cache pre-registration block: `player_impact_analyzer.py:1534` (fresh) + `1540` (fallback) — 1 try/except pair
2. PIA online sampling pre-registration block: `player_impact_analyzer.py:2206` (fresh) + `2212` (fallback) — 1 try/except pair
3. PIA emit-time lazy import: `player_impact_analyzer.py:4894` (fresh) + `4919` (fallback) — 1 try/except pair
4. `versioning.py:169` (fresh) + `176` (fallback) — 1 try/except pair
5. `scripts/validate_manifests.py:48` (single fresh import, no fallback needed — top-level module)

All 5 sites confirmed. Brief §2.5 explicitly required 5 sites and coupling_audit §2.2 pattern. The e2e test's inject-bug cycle E (remove one PIA site → test red) validates this mechanically.

**One observation**: The brief §2.5 says "the 3-site trap was for `_base.py` ABC + 2 import paths, but in practice each new plugin needs registration at 5 places." The inject-bug evidence only exercises removing site 1 (from-cache). Sites 2 and 3 are not independently inject-bug tested. If sites 2 or 3 were accidentally omitted, no test would catch it. This is informational risk — the actual diff shows all 3 PIA sites are present, and the coordinator verified them, so it's accept-as-known-risk.

---

## §5 Q3 — Plugin data source key names

**VERIFIED — KEY NAMES MATCH PARSER.**

The plugin reads (multiplier_wild.py lines 151, 164):
- `chunk_dict.get("symbol_counts_by_col")`
- `chunk_dict.get("symbol_counts_by_col_by_spin_type")`

Parser.py outputs (lines 2177, 2187-2190):
- `"symbol_counts_by_col": {str(k): dict(v) ...}` — str-keyed col
- `"symbol_counts_by_col_by_spin_type": {str(st): {str(ci): dict(cmap) ...}}` — str-keyed ST then str-keyed col

**Key name match is exact.** The brief §2.3 mentions different names (`symbol_by_col_counts` and `symbol_counts_by_st`) — those names do NOT exist in the parser or plugin. The brief spec was inaccurate but the implementation corrected it. No risk.

The serialization nesting also matches: parser outputs str(ST) → str(col) → {symbol: int}, and the plugin iterates `for st_str, col_map in raw_by_st.items()` then `for _col_str, sym_map in col_map.items()` — correct traversal order.

**One subtle risk**: When `sp_type` is `None` at parser line 1926-1928, `_sym_st_key = -1`, meaning `symbol_counts_by_col_by_spin_type` will have a key `"-1"` for rounds where SpinType is unknown. The plugin will emit a `by_spin_type` entry for `spin_type=-1` with `behavior="other"` (from `_ST_BEHAVIOR.get(-1, "other")`). This is correct behavior but `sum(by_spin_type hits)` will differ from `total_hits` (which uses `by_col` as ground truth) only if `-1` spins contribute. The plugin explicitly comments "total_hits: sum across all columns (by_col is the ground truth)" at line 292 — this is the correct choice. No action needed, but it means `by_spin_type` hits may not sum to `total_hits` if any rounds have missing ST. No test validates this invariant (see Q10 below).

---

## §6 Q4 — Regex `^wild(\d+)x$` edge cases

**VERIFIED — BEHAVIOR IS CORRECT AND INTENTIONAL.**

Live test of the regex confirms:
- `wild2x`, `wild5x`, `wild10x`, `wild100x` — MATCH (correct)
- `wild0x` — MATCHES (multiplier_value=0 would be emitted; this is technically correct behavior but a `wild0x` symbol would be a degenerate multiplier that multiplies by 0)
- `wild` — no match (correct)
- `wild_5x` — no match (correct — underscore breaks it)
- `wildNx` — no match (N is not a digit)
- `wild2X` — no match (correct — case sensitive)
- `WILD2x` — no match (correct — case sensitive)
- `wild2x_special` — no match (correct — `$` anchor prevents suffix)

**Risk: `wild0x`** — matches and produces `multiplier_value=0`. If any machine has a symbol literally named `wild0x`, the plugin will emit a variant with value 0. Whether this is a bug or a degenerate valid case is ambiguous. No test asserts `multiplier_value > 0`. This is informational — no real machine apparently has `wild0x`, and the generic regex is intentionally general (per `feedback_prefer_complex_better.md`).

**Not a required fix** — the generic regex approach is correct per the feedback and correctly handles the documented variants. The `wild0x` case is a known edge case in the open design.

---

## §7 Q5 — `RTP_CONTRIBUTION = True` with `estimated_rtp_contribution_pp = null`

**VERIFIED — NO MANIFEST VALIDATION ERROR TRIGGERED.**

Traced through `manifest_loader.py` rules:
- **Rule 8** (line 749-766): only fires if `console_diagnostic_complete: true`. M275 has `console_diagnostic_complete: false` → Rule 8 never runs for M275.
- **Rule 5** (line 661-686): checks `manifest.get("modes_supported") or []`. M275 has `modes_supported: None` (the field is absent; the manifest has `"modes": [1,2,5,7]` but `modes_supported` is a different key). So Rule 5 loop runs zero iterations for M275.

Result: adding `multiplier_wild` with `RTP_CONTRIBUTION = True` to M275 triggers **no validation error** from Rule 5 or Rule 8 for M275 in its current state. This is confirmed by the rtp_integrity_check passing in the e2e test.

**Semantic concern** (informational): `RTP_CONTRIBUTION = True` semantically promises this feature contributes to RTP accounting, but `estimated_rtp_contribution_pp = null`. There is no invariant that catches the "claims RTP contribution but provides no number" combination. When a future machine has `console_diagnostic_complete: true` AND declares `multiplier_wild`, Rule 8 would require `multiplier_wild` in `analyzer_features` — which is fine. But Rule 8 does NOT check that the feature actually provides a non-null `estimated_rtp_contribution_pp`. This is a known deferred design gap documented in the brief (v2 deferred).

**Not a required fix for this phase** — the coordinator accepted this deferral explicitly. However, the commit message should note that `RTP_CONTRIBUTION = True` is aspirational/v2-forward, and the null contribution_pp is intentional.

---

## §8 Q6 — Three open concerns from implementer

**(a) spin_type_convention.paid=[1] vs ST=140 actual**

M275 manifest has `spin_type_convention.paid: [1]`. The raw probe shows actual paid spins use ST=140 and free spins use ST=126. The plugin's `_ST_BEHAVIOR` dict covers ST=1, ST=140, and ST=126.

The manifest's `expected_paid_st: [1]` in `rtp_integrity_contract` is what drives rtp_integrity checking. The discrepancy (manifest says paid=[1], actual data has ST=140 as the outer paid spin) is a pre-existing manifest accuracy issue from M275's bootstrap that was not introduced by C3.5. The plugin handles it correctly with the generic "other" fallback — and in fact explicitly documents ST=140 as paid in `_ST_BEHAVIOR`. The rtp_integrity test passes in the e2e run. **Not a C3.5 bug.**

**(b) `_ST_BEHAVIOR` hardcoding vs `feedback_no_hardcode.md`**

The dict `_ST_BEHAVIOR = {1: "paid", 140: "paid", 126: "free"}` at lines 96-99 is technically a hardcoded semantic mapping for specific ST integers. The docstring at line 64 in the module header explicitly addresses this: "behavior label is informational only; behavior-critical logic uses ST ints." The `feedback_no_hardcode.md` memory primarily warns against hardcoding semantic meanings that drive correctness decisions — here the label is purely display text. The numeric ST values remain the authoritative data. This is a judgment call that the implementer documented well. **Accept as known risk.**

**(c) hit_rate denominator: `ctx.total_spins` vs paid-only**

`ctx.total_spins` = paid + bonus spins. For M275, which has freespins (ST=126), using `total_spins` as denominator means hit_rate is computed over all spin types. The `feedback_paid_round_default.md` memory says "paid round is the default metric unit" and all player metrics should default to paid round denominator.

This is a **genuine semantic tension**: using `total_spins` inflates the denominator (making hit_rate lower than if paid-only). Whether `wild2x` hitting during a freespin "counts" as a meaningful hit rate event per paid spin is ambiguous. The plugin uses `total_spins` which is the simpler and more inclusive choice but may not match the project's standard metric semantics. **Informational risk** — this is a design choice the implementer explicitly noted as open. No test enforces a specific denominator choice, so it won't be caught if changed in v2.

---

## §9 Q7 — Test debt fix accuracy: `_EXPECTED_C3_BASE_HASH` update

**PARTIALLY VERIFIED — SEE REQUIRED FIX IN §2.**

The constant value update from `64409ab1b68c` to `fa440e3eb5f6` at line 77 of `test_c3_base_hash_flips_for_round_level_enrichment.py` is consistent with:
- `byte_identical_results.md` header row: base_hash = `fa440e3eb5f6`
- `test_c3_5_isolation_m275_only.py:81`: `_C3_BASE_HASH = "fa440e3eb5f6"`

These two independent sources agree. The value itself is correct.

**However, the surrounding prose was NOT updated**. Two places contradict the new value:
1. Line 91 (class docstring): "base_hash flipped from C2 (b0ba0ce7c7e2) to C3 (64409ab1b68c)"
2. Line 121 (method docstring): "base_hash must be the known post-C3 value (64409ab1b68c)"

The class name `TestBaseHashFlipExpected` with its docstring claiming "C3 (64409ab1b68c)" will mislead future readers when the actual enforced value is `fa440e3eb5f6`. This is the required fix in §2.

---

## §10 Q8 — Topo sort test rename safety

**VERIFIED CLEAN.**

Searched entire repo (all `.py`, `.yml`, `.yaml`, `.json`, `.ini`, `.cfg`, `.toml` files) for `test_real_four_plugins`. Only one result: the comment on line 186 of `test_topo_sort.py` that documents the rename history: "C3.5 update: was test_real_four_plugins_no_deps_alphabetical (C1 set of 4)."

No CI config, test selection script, `.github/` workflow, `pytest.ini`, `pyproject.toml`, or documentation references the old test name. The rename is safe.

The test logic change from `assert set(fids) == expected_set` to `assert set(fids) >= expected_set` is a weakening — it allows additional plugins beyond the expected set without failing. This is intentional (future phases add more plugins), but it means the test no longer pins "exactly these 5 plugins." Accept-as-known-risk; the exact-set check would be too brittle as more plugins are added.

---

## §11 Q9 — Commit message accuracy

The coordinator will draft the commit message from the template in brief §9. Facts the commit message MUST include per what the diff actually ships:

1. **base_hash value and status**: "base_hash fa440e3eb5f6 UNCHANGED from C3" (not the brief's stale reference to 64409ab1b68c)
2. **Test debt fixes**: 2 test debt fixes:
   - `_EXPECTED_C3_BASE_HASH` updated 64409ab1b68c → fa440e3eb5f6 in test_c3_base_hash_flips
   - `test_real_four_plugins_no_deps_alphabetical` renamed to `test_real_plugins_no_deps_alphabetical` + expected set extended
3. **5 import sites** (not "3-site trap" — this was 5 sites per coupling_audit)
4. **RTP contribution deferred**: "RTP_CONTRIBUTION=True declared; estimated_rtp_contribution_pp=null in v1; v2 will compute via line-win correlation"
5. **impl-verifier ceremony skipped**: coordinator subsumed; 91 C3.5 tests pass; 306 total tests/analyzer/ pass
6. **Drift exclusion**: configs/machines.json + machines_virtual.json stashed (round 3)
7. **M275 actual ST data**: plugin handles ST=140 (paid) + ST=126 (free) from real data, despite manifest declaring paid=[1]

**Claims that should NOT be in the commit message** (absent from diff):
- "Byte-identical for non-declaring machines" — technically true but this is a property of the design, not something verifiable by reading the diff; state as "per-machine isolation demonstrated" instead
- Any reference to 64409ab1b68c as the current base_hash (it's fa440e3eb5f6)

---

## §12 Q10 — Beyond the prompted questions

### 10a. `by_spin_type` sum vs `total_hits` invariant not tested

The plugin derives `total_hits` from `sum(by_col.values())` and separately accumulates `by_st`. If any round has `sp_type = None` (→ ST key `"-1"`), `by_st` correctly includes it under `"-1"`, so `sum(by_st[sym].values()) == sum(by_col[sym].values())`. This arithmetic identity holds, but **no test verifies it**. A test asserting `sum(entry['hits'] for entry in variant['by_spin_type']) == variant['total_hits']` would catch any future divergence between `by_col` and `by_st` accumulation paths. This is informational — the current code is correct.

### 10b. `test_c3_5_inject_bug.py` was promised in brief §7 but not shipped

The brief §7 listed `tests/analyzer/test_c3_5_inject_bug.py` as an expected file. It does not exist. The inject-bug cycles are instead embedded in the docstrings of the other 4 test files, and the `inject_bug_evidence.md` artifact documents the RED→GREEN cycles. This is acceptable — the inject-bug recipes are documented and the coordinator's ceremony verified them — but the brief's file list was not honored. Not a blocking issue since the inject-bug tests themselves are distributed across the 4 test files (and verified to run red→green per the evidence doc).

### 10c. `test_c3_5_m14_no_multiplier_wild.py` T3 references stale expected feature set

At `test_c3_5_m14_no_multiplier_wild.py:171-176`:
```python
_EXPECTED_M14_FEATURES = {
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "bankruptcy_simulation",
    "bankruptcy_probe",
}
```
The constant is defined but only `payouts_by_spin_type` and `bankruptcy_simulation` are actually asserted in the test methods below. `bankruptcy_probe` is in the set but never checked (no corresponding test method). More importantly, `multiplier_profile` is missing from `_EXPECTED_M14_FEATURES` — M14 likely declares it based on the isolation test showing M14's effective_version equals M37 and M272 which all have 4 features. The constant is defined but not fully used, making it documentation-misleading. Informational.

### 10d. `test_c3_5_m275_e2e.py` fixture uses `--from-cache` with a hardcoded cache path

The fixture at line 71 uses `_CACHE_DIR = _REPO_ROOT / "rawdata" / "M275" / "mode_1"`. If this path doesn't exist, the test skips. This is the correct behavior per `feedback_no_proactive_fetch.md` — dev always uses cached data. The `pytest.skip` call is proper. No concern.

### 10e. `validate_manifests.py` import style inconsistency: no try/except fallback

`validate_manifests.py` imports `multiplier_wild` as a top-level bare import (no try/except fallback to `analyzer.features.multiplier_wild`). The other 4 test files and PIA itself use try/except for the standalone-script path. `validate_manifests.py` is always run from the repo root as `scripts/validate_manifests.py` with `fresh_slotlab` on sys.path (per lines 34-40 of the script), so the top-level import is correct. The absence of try/except here is consistent with the existing 4 plugin imports above it in the same file — all use the bare `import fresh_slotlab.analyzer.features.*` without fallback. No concern.

### 10f. No test for `wild0x` suppression

The regex matches `wild0x` (multiplier_value=0). No test explicitly asserts what happens when `wild0x` appears in data. The plugin would emit a variant with `multiplier_value=0` and `applicable=True`. Whether this is correct business behavior is ambiguous. Informational only.

---

## §13 Memory feedback adherence audit

| Memory file | Claimed adherence | Verified |
|---|---|---|
| `feedback_subprocess_import_suicide_and_module_globals.md` | `register()` is pure list-append, no I/O at import | VERIFIED — confirmed in feature_registry.py; no module-global leaks in plugin |
| `feedback_no_silent_swallow.md` | errors surface via C2 PIA merge-loop mechanism | VERIFIED — PIA lines 2008-2024 catch extract/reduce errors, print to stderr, store in `_extract_error_*` dict |
| `feedback_enumerate_safety_paths.md` | inject-bug cycles documented | VERIFIED — 6 cycles in inject_bug_evidence.md + embedded recipes in test docstrings |
| `feedback_perf_claim_needs_e2e_event_stream.md` | subprocess tests required | VERIFIED — test_c3_5_m275_e2e.py and test_c3_5_m14_no_multiplier_wild.py both spawn real subprocess |
| `feedback_md5_granularity_and_stamping.md` | per-mode hash preserved | VERIFIED — no per-mode override logic changed; versioning.py only adds import |
| `feedback_md5_is_a_tag_not_a_destruction_signal.md` | effective_version flip = tag, not destruction | VERIFIED — no deletion logic touched |
| `feedback_invariant_with_fallback_hides_drift.md` | applicable=False is explicit signal | VERIFIED — emit() explicitly sets applicable=False with empty variants, not a catch-all |
| `feedback_prefer_complex_better.md` | generic regex over hardcoded symbol list | VERIFIED — `^wild(\d+)x$` is generic |
| `feedback_no_hardcode.md` | no machine-specific semantics hardcoded | PARTIAL — `_ST_BEHAVIOR` dict has ST integers; documented as informational-only labels |
| `feedback_impl_team_required.md` | full impl-* loop | VERIFIED — brief states 4-agent loop; coordinator subsumed verifier; critic (this file) completes loop |
| `feedback_adversarial_self_review.md` | Self-critique section in commit | NOT IN DIFF — the commit message template in brief §9 does not include a `## Self-critique` section as required by this feedback. The feedback requires the commit message to include a self-critique section. **See below.** |

**Memory violation — `feedback_adversarial_self_review.md`**: The commit message template in brief §9 includes `## Verified happy path`, `## Verified failure paths`, `## Not verified`, and `## Tests added`, but does NOT include a `## Self-critique` section. The `feedback_adversarial_self_review.md` memory explicitly requires: "commit message MUST include `## Self-critique` section." This is a process violation. The coordinator should add a `## Self-critique` section to the commit message noting at least: (1) `_ST_BEHAVIOR` hardcoding tradeoff, (2) hit_rate denominator choice, (3) `wild0x` edge case not guarded, (4) `by_spin_type` sum ≠ `total_hits` not tested.

---

## §14 Summary of findings

**Top concerns (ranked)**:
1. `test_c3_base_hash_flips_for_round_level_enrichment.py` stale prose (REQUIRED FIX — misleads future maintainers)
2. Commit message missing `## Self-critique` section (PROCESS VIOLATION per memory)
3. `by_spin_type` sum ≠ `total_hits` invariant not tested (INFORMATIONAL)
4. `_ST_BEHAVIOR` hardcoding is borderline `feedback_no_hardcode.md` violation (ACCEPT-AS-KNOWN)
5. hit_rate uses `total_spins` (paid+free) not paid-only denominator (INFORMATIONAL per `feedback_paid_round_default.md`)

**Memory feedback violations**: 1 process violation (`feedback_adversarial_self_review.md` — missing ## Self-critique in commit message). The implementation itself has no violations.

**Code-level bugs**: None found.

**Test-level gaps**:
- No test asserts `sum(by_spin_type hits) == total_hits` per variant
- No test for `wild0x` degenerate case
- `test_c3_5_inject_bug.py` (named in brief §7) not a standalone file; inject-bug recipes embedded in other test docstrings (acceptable)
- Sites 2 and 3 of the 5-site registration not independently inject-bug tested (site 1 is tested)

**Claim-vs-reality gaps**:
- brief §4 AC#2 says base_hash should be `64409ab1b68c`; actual committed hash is `fa440e3eb5f6` (brief is stale; implementation is correct)
- brief §2.3 names data source keys incorrectly (`symbol_by_col_counts`, `symbol_counts_by_st`); plugin uses correct parser keys

**Edge cases not covered**:
- `wild0x` symbol (multiplier_value=0) would be silently emitted as a variant
- `sum(by_spin_type hits)` not validated against `total_hits`

---

## Final verdict

**APPROVE-WITH-FIXES**

Required before commit:
1. Fix stale prose in `test_c3_base_hash_flips_for_round_level_enrichment.py` (lines 91 and 121) to reference `fa440e3eb5f6` instead of `64409ab1b68c`
2. Add `## Self-critique` section to the commit message per `feedback_adversarial_self_review.md`

Optional improvements (do not block commit):
1. Add a test asserting `sum(by_spin_type hits) == total_hits` per variant in test_c3_5_multiplier_wild_plugin.py
2. Update `_EXPECTED_M14_FEATURES` in test_c3_5_m14_no_multiplier_wild.py to include `multiplier_profile` and remove unused `bankruptcy_probe`
3. Add a `wild0x` test case to document the intended behavior
4. Consider adding a comment noting the hit_rate denominator choice rationale (total_spins vs paid-only)
