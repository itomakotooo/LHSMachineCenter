# Architecture Review v4 — Decision Summary

> Branch `arch/console-refactor`. 4 full iterations complete. 17 artifacts in `session_artifacts/_arch/`.
> v4 commits: `70c6dd3` (addendum) → `88951f4` (mechanism test) → `baa4644` (designer) → wave 3 v4 (pending commit).

---

## §1 v4 outcome

| Reviewer | v4 verdict | New must-resolves | v3 must-resolves status |
|---|---|---|---|
| arch-critic | APPROVE-WITH-REVISIONS | 4 concerns (A trigger-session false-positive + B Day-1 not verified + C variant override sticky + D fleet-pull perf) | **M1 ✓ M2 ✓ S1 ✓** all fully resolved |
| arch-validator | APPROVE-WITH-REVISIONS | 3 doc gaps (no algorithm changes) | (all preserved working) |

**Stress questions**: 4 ✓ / 4 ⚠ / 2 ✗ (v3 was 8 ✓ / 9 ⚠ / 1 ✗). The drop in ✓ count reflects v4 surfacing NEW concerns Critic didn't probe in v3 (which focused on closing v3's specific items).

**Validator empirical evidence (most concrete signal yet)**:
- Ran v4 Layer 4 Step B on real `rawdata/M274/mode_1/chunk_0001.json`: 10,885 rounds processed; 0 mismatches vs analyzer's dispatch → Layer 4 PASS on live data
- Constructed synthetic mismatch (200 ST=139 rounds mis-routed to ST=140 for pid 5801): v4 Layer 4 CAUGHT it; v3 Layer 4 would have PASSED (both sides read same wrong dict)
- **v4's Layer 4 algorithm actually works for the bug it was designed to catch**

---

## §2 What v4 fixed (v3 must-resolves all done)

- **v3 M1** (Layer 4 spec drift): ✓ fully fixed. v4 §9.4 Step A/B/C uses independent rawdata scan. Validator confirms catches dispatch-routing bugs (synthetic test).
- **v3 M2** (Day-1 empty): ✓ fixed. v4 §6.3 enumerates 46 candidates (SC-Vanilla 45 + M274). Validator confirms count + verifies M1/M14/M274 against real reports.
- **v3 S1** (variant cascade asymmetry): ✓ clean. v4 §5.5.7 makes `console_diagnostic_complete` cascade eagerly matching `analyzer_features`. Validator confirms scenarios 1-3 work.

---

## §3 What v4 surfaced (new concerns)

### Critic Concern A — Layer 4 systematic false-positive for trigger-session machines (HARDEST)

**Concrete problem**: Layer 4 Step B does raw scan of `R.SpinType` from rawdata. But `compute_trigger_sessions` (called from `parse_chunk_response`) re-attributes free-spin wins to their triggering paid-spin session bucket. So:
- `analyzer_dispatch[pid][st]` = post-attribution count (after compute_trigger_sessions)
- `fresh_dispatch[pid][st]` = pre-attribution count (raw scan)
- For trigger-session machines (Type 1 + Type 2 per memory `reference_trigger_session_patterns.md`), these legitimately differ
- Step C fires mismatch on every fleet pull for affected machines → false-positive red banner

Affects: any machine with `trigger_session_pattern != null` in its manifest. That's a significant fraction of fleet (M14/M15/M120/M139/M279 + many BCM machines).

**v4 mentions this as possible error cause "(b)" but provides no structural fix.** Such machines can't be `complete: true` in strict mode without false positives.

### Critic Concern B — 46 Day-1 candidates are a target list, not verified

- SC-Vanilla clustering = similarity on 5 axes, NOT Layer 4 PASS evidence
- M274 has Layer 1-3 empirical (per v2 validator §2.6) but Layer 4 is new algorithm in v4 — never run on M274 historically
- All 46 candidates need fresh Layer 4 verification before Day-1 flip

### Critic Concern C — Variant override sticky bug

- `resolve_completeness()` returns False unconditionally when override is False
- After underlying flips false→true, variant stays warn-only **forever** unless someone manually removes override
- No reminder mechanism, no audit prompt, no lint rule
- For 85-variant M273: any lingering override silently pins that variant in warn-only indefinitely

### Critic Concern D — Layer 4 fleet-pull perf unquantified

- Designer claims <5s per machine but didn't measure. Step B iterates chunks + extracts PayoutIdToWinAmount.keys() per round. For full fleet pull (421 machines × N chunks each), perf matters.

### Validator's 3 minor doc gaps

1. §9.4 must state RoundWinRules can't write to `payout_id_by_spin_type_total` (else false positive)
2. §5.5.7 add override-clearing procedure (2-3 lines: criteria, audit log format)
3. §9.4 Step C note `_unattributed_*` mismatches corroborate Layer 2 (not false positives)

---

## §4 Trajectory

| Iteration | Critic must-resolves | Validator verdict | Cases broken |
|---|---|---|---|
| v1 | 11/15 | APPROVE-WITH-REVISIONS (4 gaps) | 0 |
| v2 | 6/15 | **APPROVE** (2 minor gaps) | 0 |
| v3 | 3 (2 hard + 1 soft) | (skipped) | (carried) |
| v4 | 4 (different concerns) | APPROVE-WITH-REVISIONS (3 doc gaps) | 0 |

**Cases-broken stays 0 across all iterations.** Each iteration's "new must-resolves" are different concerns surfacing as the design is scrutinized more deeply, not regressions on previously-fixed issues. **v3's specific items (M1/M2/S1) are all closed in v4.**

This is the pattern of a design review converging — fixed items stay fixed; new probes find narrower concerns. **At some point you ship.**

---

## §5 Path options (coordinator opinion)

### (a) Stop here. Accept v4 + 4 critic concerns + 3 validator doc gaps as known issues. Move to implementation.

Rationale:
- Validator EMPIRICALLY confirmed v4's Layer 4 algorithm works on real M274 data + catches synthetic dispatch bug
- 0 cases broken across 4 iterations
- v3's specific must-resolves all closed
- Concern A (trigger-session false-positive) is real but **addressable in implementation** by:
  - Adding a "trigger_session compensation" flag to Step B (compute_trigger_sessions before comparison)
  - OR suppressing Layer 4 for `trigger_session_pattern != null` machines (use Layers 1-3 only for those)
  - Both are 5-10 lines during implementation
- Concerns B/C/D are polish; manageable during build

### (b) Designer v5 short focused: address Concern A (trigger-session) + add override-clearing procedure. Skip B/D (acceptable as known limitation + measure-during-build).

Time: ~15-20 min designer + ~10 min critic v5 = ~30 min.

Coordinator recommendation between (a) and (b): leaning (b) because Concern A affects many real machines + the fix is small. But (a) is defensible — implementation team handles when they hit it.

### (c) Stop the whole arch review. Cancel implementation. Take what we have.

Defensible if user feels the architecture is good enough and would rather move to other work.

### (d) Designer v5 + Wave 3 v5 (full audit cycle).

~60 min. Probably overkill — diminishing returns.

---

## §6 What you decide

1. **Path**: (a) ship + known issues / (b) v5 short / (c) stop entirely / (d) full v5 — coordinator leans (b)
2. **Implementation timing**: if (a)/(b), schedule implementation now or later session?
3. **Concern A handling preference** (if v5): structural fix (compensate trigger-session in Step B) or pragmatic (suppress Layer 4 for trigger-session machines + accept Layers 1-3 only)?

---

## §7 Cross-references

- All artifacts in `session_artifacts/_arch/` (17 files, ~13000 lines combined)
- Branch: `arch/console-refactor` (HEAD `baa4644` + pending wave-3-v4 commit)
- Process spec: `docs/ARCH_TEAM_PROCESS.md` (with §9 troubleshooting added 2026-05-17)
- Memory pointer: `memory/feedback_arch_team_process.md`
