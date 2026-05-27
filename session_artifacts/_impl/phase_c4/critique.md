# Phase C4 — impl-critic review

**Date**: 2026-05-27
**Critic**: impl-critic
**Branch**: `claude/analyzer-unbundle-c2`
**Phase**: C4 — machine_mechanics plugin + MechanismRegistry + 253 manifests (gap #1 + gap #2)

---

## §1 Verdict

**APPROVE-WITH-FIXES**

One required fix before commit (Q2/Q11 ordering assert gap — moderate risk, one line).
One documentation disclosure gap (lock_* C5 deferral not explicit in commit message).
All other findings are informational or deferred-by-design.

Core implementation is sound. Both gaps (#1 and #2) are correctly closed. Parser untouched (base_hash UNCHANGED — confirmed by `git diff HEAD -- fresh_slotlab/analyzer/core/`). 253 manifests correctly updated. 5-site registration complete. Inject-bug RED/GREEN cycles confirmed for 5 bugs including 3 critical paths.

---

## §2 Required fixes before commit/merge

### FIX-1 (Required): Add ordering assert for payout_ids_top20 and bonus_chain_dynamics before registry build

**Location**: `fresh_slotlab/player_impact_analyzer.py` at line ~4917 (the existing ordering assert block)

**Problem**: The existing assert at line 4917 only checks `spin_type_breakdown`. However, `machine_mechanics.emit()` reads `summary["player_impact"]["payout_ids_top20"]` (lines 340-348, 354-362) and `summary["player_impact"]["bonus_chain_dynamics"]` (lines 394-405) from the summary dict at emit time. These are written in Phase B (inline block, lines ~4500 and ~4539) BEFORE the registry build, which is correct. BUT there is no runtime guard asserting these Phase B keys exist before the emit loop starts. If a future refactor moves or removes those Phase B inline writes, the plugin will silently fall back to empty lists (the `.get("payout_ids_top20", [])` defensively returns `[]`) — jackpot total_win and trigger_spins will silently be 0 for M275-style machines, which is a silent mis-attribution.

**Evidence**: `machine_mechanics.py:340-348` reads `summary.get("player_impact", {}).get("payout_ids_top20", [])` — no assert, pure defensive `.get()`. Same at lines 354-362 for trigger_spins and lines 394-405 for bonus_chain_dynamics.

**Fix**: Add two assertions alongside the existing spin_type_breakdown assert at PIA line 4917:
```python
assert "payout_ids_top20" in summary.get("player_impact", {}), (
    "PHASE C4 INVARIANT: inline block must write payout_ids_top20 before "
    "MechanismRegistry build + emit loop. jackpot win reconstruction depends on it."
)
assert "bonus_chain_dynamics" in summary.get("player_impact", {}), (
    "PHASE C4 INVARIANT: inline block must write bonus_chain_dynamics before "
    "MechanismRegistry build + emit loop. freespin chain_spins fallback depends on it."
)
```

This converts the currently-silent ordering assumption into an explicit runtime contract, consistent with the spec's stated `_EMIT_PHASE_PRECONDITIONS` pattern (04_v3 §4.2).

### FIX-2 (Documentation, required for commit msg): Disclose lock_* C5 deferral explicitly

**Location**: commit message `## Not verified` section

**Problem**: `machine_mechanics.emit()` uses counter-driven applicable flags (not registry-driven) for lock_lines, lock_symbols, lock_reels, and dollar_pick. The docstring at line 263 says "not yet in the Mechanism Registry — that is scope for C5". The tester verifier report mentions this as finding #2 but does not call for a commit message disclosure.

Per `memory/feedback_adversarial_self_review.md` — commit message MUST include `## Self-critique` section that calls out what was deliberately deferred. The commit message template in brief §8 has a `## Not verified` section — lock_* counter-driven applicable flags must be listed there with explicit "C5 scope" note to prevent a future implementer from not knowing.

---

## §3 Q1 — REQUIRES = () deviation: is every emit() read traceable to a pre-loop write?

**Finding: Safe. The deviation is architecturally correct, but undeclared summary reads create a latent ordering risk (see FIX-1).**

The brief §2.2 specified `REQUIRES = ("payouts_by_spin_type", "bonus_chain_dynamics")` because topo sort was the intended guard. The implementer deviated: `REQUIRES = ()` because the plugin reads from `ctx.mechanism_registry` (Phase C object), not from plugin summary keys.

Verified by reading `machine_mechanics.py:241-440` (emit body):
- `ctx.mechanism_registry` — pre-built in Phase C, always available. SAFE.
- `ctx.effective_bet_for_rtp`, `ctx.total_spins` — PipelineContext fields. SAFE.
- `final_acc` — plugin's own accumulator. SAFE.
- `summary["player_impact"]["payout_ids_top20"]` — read at lines 340-348, 354-362. Written by PIA Phase B inline at line 4500. Phase B runs BEFORE Phase C (registry build) which runs BEFORE Phase D (emit loop). SAFE IN CURRENT CODE.
- `summary["player_impact"]["bonus_chain_dynamics"]` — read at lines 394-405. Written by PIA Phase B at line 4539. Same ordering. SAFE IN CURRENT CODE.

The risk: both reads use `.get("...", [])` / `.get("...", {})` defensively. If Phase B ordering is violated, the plugin silently falls back to empty data, not an exception. This is the gap identified in FIX-1.

The REQUIRES=() deviation itself is architecturally correct per 04_v3 §4.2 Phase ordering contract. Topo sort via REQUIRES is the WRONG mechanism when the dependency is on Phase B inline writes (not other plugin emit() outputs). The brief §2.2 spec was imprecise on this point.

---

## §4 Q2 — Ordering assert gap: PIA line 4917 only asserts spin_type_breakdown

**Finding: REAL GAP — see FIX-1.**

The assert at PIA line 4917 covers only `spin_type_breakdown`. The plugin also reads `payout_ids_top20` and `bonus_chain_dynamics` from summary. Both are written by Phase B (lines 4500 and 4539 respectively — confirmed by code read), so the current ordering is correct. But there is no runtime guard for the additional two keys.

The spec (04_v3 §4.2) explicitly mentions `_EMIT_PHASE_PRECONDITIONS` sentinel and uses language like "MUST complete before Phase D." The existing assert for `spin_type_breakdown` is the only precondition enforcement. Adding the two new asserts (FIX-1) makes the contract explicit and catches future refactor mistakes before they produce silent wrong numbers.

Verifier finding #1 correctly identified this but concluded "documentation-only is acceptable." This critic disagrees: documentation-only is insufficient for an ordering constraint that, when violated, produces silent wrong output (jp_win and fs_chain_spins become 0 with no error). One line of `assert` per key is the correct fix.

---

## §5 Q3 — lock_* C5 deferral: documented in commit message?

**Finding: NOT YET DOCUMENTED — see FIX-2.**

The plugin docstring (line 263) says "not yet in the Mechanism Registry — that is scope for C5." The verifier found this as finding #2 and rated it LOW/INFO. But the brief §8 commit message template has `## Not verified` and `## Self-critique` sections specifically for this kind of deliberate scope cut.

The commit message has not been written yet (coordinator writes it post-critique). The commit message MUST list:
- `lock_lines / lock_symbols / lock_reels / dollar_pick` — applicable flags still counter-driven, not registry-driven (C5 scope)
- The REQUIRES=() deviation from brief §2.2 spec (it's deliberate and correct but the brief said otherwise)
- 253 manifest universal rollout (vs brief §2.6 which said "implementer choice: M275-only first or full 253" — implementer chose full 253)
- `config_not_reviewed=True` for 182 of 253 manifests (feature auto-enabled on un-reviewed machines — documented risk)

---

## §6 Q4 — base_hash truly unchanged: parser NOT touched

**Finding: CONFIRMED. Zero change to fresh_slotlab/analyzer/core/.**

`git diff HEAD -- fresh_slotlab/analyzer/core/` returns no output. The implementer's claim is verified. `jackpot_ids_seen` was already accumulated by `parser.py` (lines 665, 1418, 2359 in parser.py) before C4 — verified by grep. The C4 change routes the existing `total_jackpot_ids_seen` accumulator (PIA lines 1975-1976 and 2765-2766) into `MechanismRegistry.build()` as `jackpot_ids_seen` parameter. No parser change required, no base_hash flip.

The `test_lookup_machine_md5_canonical.py` failures (4 tests: M14/M37/M101/M279) cited in the byte_identical_results.md are caused by `effective_analyzer_version` changes (plugin hash inclusion for machines that now declare `machine_mechanics`), NOT by a base_hash flip. The code_md5 snapshot mismatch is the expected and documented consequence of the 253-manifest rollout.

---

## §7 Q5 — Tier precedence semantics: short-circuit on Tier 1?

**Finding: CORRECT — Tier 1 short-circuits Tier 2/3.**

Reading `mechanism_registry.py:155-192` (jackpot detection) and `197-215` (freespin detection):
- Jackpot: `if "jackpot_applicable" in overrides:` → directly sets jackpot_applicable + jackpot_pid_set from overrides, records `"tier1_manifest"`, then falls through to payout_groups detection. Tier 2/3 jackpot logic is in the `else` branch — NEVER runs when Tier 1 fires.
- Freespin: same `if "freespin_applicable" in overrides:` → sets freespin_applicable + `"tier1_manifest"`, skips Tier 2 bonus_chain_lengths check entirely.
- Scatter: `if "scatter_marker_pids" in overrides:` → same pattern.

Tier 1 is a true short-circuit. Tier 2/3 logic is inside `else` branches. Correct per spec.

The unit test `test_tier1_freespin_false_override` (mechanism_registry tests line 167) explicitly verifies that `freespin_applicable=False` override beats Tier 2 `True` signal — the adversarial direction. Tier 1 precedence is tested in both directions.

---

## §8 Q6 — `_detection_source: "tier3_raw"` for M14 jackpot: misleading label?

**Finding: MISLEADING LABEL — low severity, but worth flagging for documentation.**

When both Path A and Path B are empty (M14's case: no PIDs >= 10000, no JackpotIds field events), the code at `mechanism_registry.py:189-190` sets:
```python
else:
    _src = "tier3_raw"
```

This means `jackpot.applicable=False` and `_detection_source="tier3_raw"`. A human reading this label sees "tier3_raw" and thinks "Tier 3 ran and found something raw." The correct reading is "Tier 3 ran but found nothing (no Path A, no Path B signal)."

Better labels would be:
- `"tier3_no_signal"` — unambiguous: ran but found nothing
- `"tier3_pid_lt_10000_no_jackpot_ids"` — fully explicit

The byte_identical_results.md table documents M14 jackpot source as `"tier3_raw (Path A + Path B both empty)"` — that parenthetical is in the tester's table, NOT in the actual output label. A frontend developer looking at the JSON gets `"tier3_raw"` with no indication this means "no signal found."

This is NOT blocking (the applicable=False is correct), but the label is semantically incorrect for the "no signal" case. Current tests only check that `"tier3"` is in the source string, not the specific label — so no test currently enforces the misleading-vs-correct distinction.

---

## §9 Q7 — Tier 3 jackpot Path B: how does plugin get JackpotIds without parser change?

**Finding: NO PARSER CHANGE NEEDED — jackpot_ids_seen was already accumulated pre-C4.**

The `parser.py` (outside the `HEAD` diff) already accumulates `jackpot_ids_seen` as a `set[str]` at lines 665, 1418, and returns it in chunk_dict at line 2359 (`"jackpot_ids_seen": sorted(jackpot_ids_seen)`).

The PIA merge loop already collects this into `total_jackpot_ids_seen` (PIA lines 1975-1976 and 2765-2766 — also pre-C4).

C4's only addition: pass `total_jackpot_ids_seen` to `MechanismRegistry.build()` as the `jackpot_ids_seen` parameter (PIA line 4931). The accumulation pipeline was already complete. This is why the base_hash does not flip — the parser chunk schema is unchanged.

The brief §2.5 stated "Parser changes (likely required)" — this was a false assumption. The parser already had the accumulator. The implementer correctly identified this and avoided an unnecessary parser change. The brief's assumption about a base_hash flip was therefore wrong; the actual base_hash is UNCHANGED.

This is a substantively important detail for the commit message: the brief predicted a base_hash flip, reality is no flip occurred.

---

## §10 Q8 — 253 manifest scope risk: 182 of 253 have `config_not_reviewed: true`

**Finding: HIGH-COUNT UNREVIEWED ROLLOUT — documented risk, not a blocker, but must be disclosed.**

Verified by bash loop: 182 of 253 changed manifests have `_generator_notes.config_not_reviewed: true`. The remaining 71 have `config_not_reviewed: false`.

The `machine_mechanics` plugin is now enabled for 182 machines whose configs have not been operator-reviewed. This means:
- The plugin will run Tier 3 jackpot detection (PID >= 10000 threshold) on all 182 unreviewed machines.
- If any of those machines have PIDs >= 10000 that are NOT jackpots (e.g., unusual scatter IDs, special bonus identifiers), they will be mis-classified as jackpot machines with `jackpot_applicable=True`.
- The only protection is the scatter_marker_pid exclusion (win=0 + no regular line), which may not catch all edge cases.

The brief §2.6 explicitly listed this as an implementer decision: "M275-only first OR full 253." The implementer chose full 253. This is within scope, but the commit message MUST disclose the `config_not_reviewed` count.

The Tier 1 manifest override (`mechanism_overrides.jackpot_applicable: false`) is available as a correction path for any false positives discovered post-rollout. This is the correct mitigation strategy.

---

## §11 Q9 — M11 small sample: test tolerance band?

**Finding: ACCEPTABLE RISK — low severity. Test should document the caveat explicitly.**

The `byte_identical_results.md` table shows M11 `jackpot rtp_pp = 24.57`. No tolerance band or sample-size note appears in the M11 subprocess test (`test_c4_m11_jackpot_ids_union.py`).

The test only checks:
- `jackpot.applicable is True`
- `jackpot_ids` contains the 3 expected PIDs
- Detection source is `tier3_jackpot_ids_seen`

It does NOT assert `rtp_contribution_pp` — which is actually the correct choice given small sample variance. But the test docstring does not explain WHY `rtp_contribution_pp` is omitted.

Recommendation: add a comment in the test docstring: "rtp_contribution_pp intentionally not asserted — M11 cache is small sample, high variance. Focus is on applicable=True and jackpot_ids correctness." This is cosmetic but addresses the verifier's finding #3 directly.

This does not block commit.

---

## §12 Q10 — SCHEMA_VERSION 1→2 fallback: does v1 reader render null gracefully?

**Finding: CORRECT — v1 summaries will have `_detection_source: null` which frontend handles as None.**

`REGISTERED_FALLBACK_RULES[1] = {"_detection_source": None}` means: when a v1 summary (pre-C4) is loaded by the new frontend, the v2 reader will synthesize `_detection_source: null` for the jackpot and free_spin sections.

The design question is: does the frontend check `if (_detection_source)` vs `if (_detection_source !== undefined)` vs `if (_detection_source !== null)`? If it renders null as a display error (e.g., `"Detection source: null"` in the UI), that's technically correct behavior for old data but potentially confusing.

The fallback rule makes the field present-but-null rather than absent. This is the correct pattern per `feedback_invariant_with_fallback_hides_drift.md` — explicit null is better than absent field (no KeyError, no "unknown field" behavior).

Since there is no frontend code change in this diff (brief §3 explicitly prohibits touching web_console), the rendering behavior is unchanged. The null value will be handled by whatever frontend code already handles missing `_detection_source` — which was previously "field absent." Frontend behavior for null vs absent may differ. This is C5/C6 scope to handle in the UI layer.

Not blocking.

---

## §13 Q11 — MechanismRegistry build site ordering: what if future edit moves it before F6?

**Finding: REAL LATENT RISK — partially addressed by FIX-1, but structurally incomplete.**

Currently: F1-F9 Phase B inline writes finish at line ~4600 (including `payout_ids_top20` at 4500 and `bonus_chain_dynamics` at 4539). Registry build is at line 4913. This ordering is correct by ~300 lines of buffer.

The risk scenario: a future implementer adds a new inline block between lines 4500-4913 or, worse, moves the registry build call to earlier in the function. With only one assert (for `spin_type_breakdown`), the payout_ids_top20 and bonus_chain_dynamics reads in `emit()` would silently return empty.

FIX-1 (adding two asserts) addresses the detection of this violation at runtime. But the `_EMIT_PHASE_PRECONDITIONS` sentinel mentioned in 04_v3 §4.2 is not implemented as a systematic pattern — each assert is ad-hoc.

The complete fix would be a `_assert_emit_preconditions()` helper called once before the registry build, containing all required keys. The current approach (assert at line 4917, no assert for payout_ids_top20/bonus_chain_dynamics) is the gap FIX-1 addresses.

Note: the spec comment in the assert message (line 4918) still says "PHASE C1 INVARIANT" — it should say "PHASE C4 INVARIANT" since C4 is when the real registry build started requiring these preconditions.

---

## §14 Q12 — Pre-existing test failures: are any C4-caused?

**Finding: THE 4 md5_canonical FAILURES ARE C4-CAUSED (EXPECTED AND ACCEPTED). The other failures are pre-existing.**

The `byte_identical_results.md` line 99 says: "4 failures (M14/M37/M101/M279) — caused by base_hash flip from C4's `machine_mechanics.py` parser changes."

This statement contains an error: the parser was NOT changed (confirmed by `git diff HEAD -- fresh_slotlab/analyzer/core/` = empty). The correct cause of the md5_canonical failures is the `effective_analyzer_version` change from adding `machine_mechanics` plugin hash to 253 manifests. The canonical snapshot in `test_lookup_machine_md5_canonical.py` was captured before C4; now those machines have a new plugin in their feature list, so their `effective_analyzer_version` changes.

This is EXPECTED (brief §4 criterion 12) and ACCEPTED. The tester's explanation of "parser change causing base_hash flip" is factually wrong — the mechanism is different (effective_analyzer_version from plugin list, not base_hash from parser). The commit message should use the correct explanation.

The `test_t_critical_table_canonical.py` (3 failures) and `test_M15_verify_inject_bug.py` (4 failures) are pre-existing and can be confirmed pre-C4 by `git stash show stash@{0}` analysis — stash predates C4 changes.

---

## §15 Q13 — Commit message facts that MUST be included

Per brief §8 template + memory/feedback_adversarial_self_review.md:

1. **REQUIRES=() deviation**: brief §2.2 specified `("payouts_by_spin_type", "bonus_chain_dynamics")`. C4 uses `()` because plugin reads pre-built `ctx.mechanism_registry`, not plugin summary keys. This is architecturally correct but deviates from the brief.

2. **Parser NOT changed, base_hash UNCHANGED**: brief §2.5 predicted "parser changes (likely required)." Reality: `jackpot_ids_seen` was already accumulated pre-C4. No parser change, no base_hash flip.

3. **253 manifest universal rollout**: brief §2.6 offered M275-only as an option. Implementer chose full 253. 182 of 253 have `config_not_reviewed=True`.

4. **lock_*/dollar_pick counter-driven applicable flags (C5 scope)**: four mechanic sections still use raw counter > 0, not registry-driven. Deferred per design, not an oversight.

5. **md5_canonical test failures explained correctly**: caused by effective_analyzer_version change (new plugin in 253 manifests), NOT by base_hash flip from parser change. Tester's explanation was imprecise.

6. **`## Self-critique` section** (mandatory per feedback_adversarial_self_review.md):
   - Did I verify that payout_ids_top20 is present in summary when emit() runs? No explicit assert — FIX-1 should be added.
   - Did I verify M37 false-positive behavior? No M37 subprocess test despite brief criterion 8.
   - Does "tier3_raw" label correctly convey "no signal found"? No — ambiguous label.
   - Did I test jp_win reconstruction from payout_ids_top20 as a standalone unit test? No.

---

## §16 Beyond-prompted findings

### B1 — Tier 2 jackpot alternative signal (upstream_feature_tally) NOT implemented

The spec (04_v3 §5.2, R-09) specified: "if `upstream_feature_tally` accumulator contains an entry with feature type matching a known jackpot-feature pattern, set `jackpot_applicable=True` with `_detection_source='tier2_inferred'`."

The registry docstring at line 17 lists: `jackpot : upstream_feature_tally contains a jackpot-like feature key`. But the actual implementation in `build()` has NO Tier 2 jackpot detection — only Tier 3 Path A and Path B. The registry goes directly from Tier 1 override to Tier 3 raw detection, skipping Tier 2 jackpot entirely.

This means the `total_freespin_chain_spins` parameter is accepted (line 102) but never used in freespin detection (only `bonus_chain_lengths` is used). And `upstream_feature_tally` is not even a parameter to `build()`.

Impact: machines where jackpot PIDs are all < 10000 AND no JackpotIds raw field events AND the `FeatureWin` upstream field contains a jackpot-type marker — these machines would miss detection. Unknown how many machines fall in this category. The current two detection paths (Path A + Path B) cover M275 and M11. If there are machines with neither path firing, they remain at `jackpot_applicable=False` even if upstream signals jackpot presence.

This is a spec deviation, not a regression (pre-C4 had no detection at all). Recommend disclosing in commit message under `## Not verified`.

### B2 — double `_pids_top20` iteration in emit() (code quality)

`machine_mechanics.py:335-362`: when `jp_win == 0.0 and jp_applicable and jp_pid_set`, the code iterates `_pids_top20` at lines 340-348. Then immediately, when `jp_spins == 0 and jp_applicable and jp_pid_set` (which is always true after the jp_win reconstruction block since jp_win was 0 before), it iterates `_pids_top20 AGAIN` at lines 354-362, building a second `_jp_pid_str_set`.

Both blocks are gated on the same conditions (jp_applicable, jp_pid_set non-empty), and both iterate the same list. For M275 with ~80k spins, `payout_ids_top20` has at most 20 entries — the duplicate iteration is negligible in cost. But it's a structural oddity: `_jp_pid_str_set` is rebuilt identically in both blocks, and `_pids_top20` is fetched twice.

This could be extracted: fetch `_pids_top20` once, rebuild `_jp_pid_str_set` once, loop once accumulating both jp_win and jp_spins. Not blocking — but a C5 cleanup candidate.

### B3 — M37 false-positive test: listed in brief §4 criterion 8, not in C4 tests

Brief criterion 8: "M37 mode 1: similar to M14 (no false positives)." The tester built a test for M14 but not M37. M37 was verified by the coordinator in the byte_identical_results.md? No — looking at the table, M37 does NOT appear in the tester's verification table. Only M275, M14, and M11.

M37 was listed in the brief as a required machine for byte-identical verification (§2.4: "M14 (no mechanisms) + M275 + M11 + M37 (vanilla classic Seven)"). The tester skipped M37.

This means: if M37 has any PID >= 10000 (unusual but theoretically possible for Seven family prizes), `jackpot_applicable` would silently become `True`. There is no test guarding this. The test suite has 9 M14 tests but 0 M37 tests.

Not a confirmed bug — M37 is likely clean. But the acceptance criterion was not met (brief §4 criterion 8 not satisfied by a subprocess test). Recommend adding to `## Not verified` in commit message and creating a follow-up test.

### B4 — `except (TypeError, ValueError)` in extract() swallows all type errors silently

`machine_mechanics.py:201-202`: the extract() body is wrapped in `try: ... except (TypeError, ValueError): return _empty_acc()`. This means any type coercion error (e.g., chunk_dict contains a list where a dict is expected) returns a zero accumulator with no diagnostic.

Per `memory/feedback_no_silent_swallow.md`: "任何 best-effort post-hook…都必须把 outcome 落盘（rc + stderr tail + 解析路径），不能靠 except: pass."

The current pattern returns `_empty_acc()` — which IS slightly better than pass (returns structured data), but it does NOT write a diagnostic to the error dict. The PIA merge loop has a pattern for per-chunk extract errors (`_feature_accs.setdefault("_extract_errors", {})`). The plugin's extract() should follow that pattern.

This matches the pre-C4 behavior of the inline block (which also had no per-chunk error surfacing). But the plugin docstring claims compliance with `feedback_no_silent_swallow.md` at line 93-96. That claim is only partially accurate — the catch does not "surface via the PIA merge-loop mechanism" as stated; it returns _empty_acc() which gives the merge loop no signal that extraction failed.

Low severity (affects only malformed chunk data, not normal operation), but the docstring claim is stronger than the implementation.

### B5 — Freespin chain_spins fallback uses `bonus_round_count` not `chain_length` sum

`machine_mechanics.py:399-400`:
```python
if _bcd_round_count > 0:
    fs_chain_spins = _bcd_round_count
```

`bonus_round_count` from `bonus_chain_dynamics` is the total number of individual bonus spins across all chains (e.g., if there are 908 chains of length 10 each, `bonus_round_count = 9090`). This matches `chain_spins` semantically (total bonus spin count, not chain count). The code comment says "M275-style BCD roundcount" and the byte_identical results show M275 chain_spins = 9090 with chain_count = 908 — consistent with `bonus_round_count = 9090`.

BUT: `max_chain_length` fallback at lines 403-405:
```python
_avg_len = _bcd.get("avg_chain_length", 0) or 0
if _avg_len:
    fs_max_chain = round(_avg_len)
```

This uses `round(avg_chain_length)` as `max_chain_length`. The average is not the maximum. For M275 with `avg_chain_length = 10.0`, the brief §4 criterion 5 says `max_chain_length: 10`. The values agree here, but only because the M275 data is uniform (all chains length 10). For a machine with chains of length [5, 10, 15], `avg=10`, `round(avg)=10`, but `max=15`. The `max_chain_length` field would be wrong for non-uniform chain length distributions.

`bonus_chain_dynamics` likely contains `chain_length_quantiles` (from PIA line 3991) which would give a better max estimate. This is a latent inaccuracy in the fallback path. Not currently tested by any machine with non-uniform chain lengths.

---

## §17 Memory feedback adherence audit

| File | Cited by impl | Honored in diff? |
|------|---------------|-----------------|
| feedback_invariant_with_fallback_hides_drift.md | Yes | Mostly — `_detection_source` is explicit. BUT "tier3_raw" for no-signal case is ambiguous (B1-adjacent). |
| feedback_no_silent_swallow.md | Yes | Partial — extract() catch returns _empty_acc() without error dict write (B4). Docstring overclaims. |
| feedback_subprocess_import_suicide_and_module_globals.md | Yes | Honored — register() is pure list-append, no I/O at import. |
| feedback_no_hardcode.md | Yes | Honored — no machine-specific semantics. |
| feedback_prefer_complex_better.md | Yes | Honored — registry-driven approach vs inline per-mechanic. |
| feedback_adversarial_self_review.md | Not cited | NOT honored — no `## Self-critique` in commit message (coordinator hasn't written it yet, but must include one). |

---

## §18 Production failure thought experiment

10 concurrent planners all rebuilding M275 mode 1 against cached chunks:

1. Each spawns PIA subprocess → each runs `MechanismRegistry.build()` independently → no shared state, no race condition. The registry is a pure local object per run. SAFE.
2. Each writes to its own `tempfile.TemporaryDirectory()` output → no file contention. SAFE.
3. `_feature_accs.get("payouts_by_spin_type")` at PIA line 4925 — this is a local dict per main() invocation. No global state. SAFE.
4. The `register()` call at `machine_mechanics.py:459` fires at import time and appends to `ALL_FEATURES`. If 10 concurrent processes import the module, each has its own Python interpreter — no shared global. SAFE.
5. If a machine has PIDs that are ambiguously jackpot vs scatter (win=0 AND PID >= 10000), scatter_marker_pid detection fires first (lines 147-152). But the scatter detection uses `win == 0.0 AND not pid_has_regular_line.get(pid_s)`. A PID with a single loss event (win=0) and no payline record would be classified as scatter. A subsequent run with the same PID but a win event would classify it differently. This is data-dependent, not a concurrency issue. Single-run correctness, not a race condition.

---

## §19 Summary table

| Q | Finding | Severity | Verdict |
|---|---------|----------|---------|
| Q1 | REQUIRES=() deviation is safe but payout_ids_top20/bcd reads unguarded | Moderate | FIX-1 required |
| Q2 | Ordering assert gap — only spin_type_breakdown asserted | Moderate | FIX-1 required |
| Q3 | lock_* C5 deferral not in commit message | Low | FIX-2 (disclosure) |
| Q4 | Parser untouched, base_hash UNCHANGED — confirmed | None | OK |
| Q5 | Tier 1 correctly short-circuits Tier 2/3 | None | OK |
| Q6 | "tier3_raw" label ambiguous for no-signal case | Low | Informational |
| Q7 | Path B uses pre-existing accumulator, no parser change | None | OK |
| Q8 | 182/253 manifests config_not_reviewed=True | Moderate | Disclosure required |
| Q9 | M11 small sample — tolerance band not documented | Low | Informational |
| Q10 | SCHEMA_VERSION fallback: null renders acceptably | Low | OK (C6 UI scope) |
| Q11 | Future ordering regression: payout_ids_top20/bcd unguarded | Moderate | FIX-1 required |
| Q12 | md5_canonical failures: tester explanation imprecise | Low | Correct in commit msg |
| Q13 | Commit message must disclose 6 specific facts | — | FIX-2 (documentation) |
| B1 | Tier 2 jackpot (upstream_feature_tally) not implemented | Low | Disclose |
| B2 | Double _pids_top20 iteration | Cosmetic | C5 cleanup |
| B3 | M37 subprocess test missing (brief criterion 8) | Low | Disclose |
| B4 | extract() catch silently returns _empty_acc(), docstring overclaims | Low | Informational |
| B5 | max_chain_length uses avg not max in fallback | Low | Latent inaccuracy |

---

## §20 Required fixes (numbered)

1. **(Blocking)** Add `assert "payout_ids_top20" in summary.get("player_impact", {})` and `assert "bonus_chain_dynamics" in summary.get("player_impact", {})` to the ordering contract block at PIA line 4917-4920, alongside the existing `spin_type_breakdown` assert. Update the assert message label from "PHASE C1 INVARIANT" to "PHASE C4 INVARIANT."

## §21 Optional improvements (non-blocking)

1. Rename `"tier3_raw"` detection source label to `"tier3_no_signal"` or `"tier3_empty"` to clearly indicate "Tier 3 ran but found no jackpot PIDs," not "Tier 3 fired and returned raw data."
2. Add M37 mode 1 subprocess test for false-positive guard (brief criterion 8).
3. Add M11 test docstring note explaining why `rtp_contribution_pp` is intentionally omitted from assertions.
4. Consolidate double `_pids_top20` iteration in `machine_mechanics.emit()` (cosmetic).
5. Add `## Self-critique` section to commit message per memory/feedback_adversarial_self_review.md.
6. Document Tier 2 jackpot (upstream_feature_tally) as explicitly not implemented in registry docstring; remove from the docstring's Tier 2 description to avoid misleading future implementers.
7. Replace `round(avg_chain_length)` with `chain_length_quantiles[-1]` (the actual max) in the max_chain_length fallback path.
