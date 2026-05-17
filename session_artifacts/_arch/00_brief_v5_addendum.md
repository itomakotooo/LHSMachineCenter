# 00_brief v5 Addendum — Designer v5 direction (post-Wave-3-v4 critic + validator findings)

> Read in addition to `00_brief.md` + `_v2_addendum` + `_v3_addendum` + `_v4_addendum`.
> Background: Wave 3 v4 both reviewers APPROVE-WITH-REVISIONS. User picked option (d) — full v5 audit cycle. v5 = `04_architecture_proposal_v5.md`.

---

## §1 v5 issues to resolve

### Critical (substantive) issues

**Issue ① — Layer 4 systematic false-positive for trigger-session machines (Critic v4 Concern A)**

**Root cause** (per Critic v4 + memory `reference_trigger_session_patterns.md`):
- v4 Step B does naive raw scan of rawdata: `R.SpinType` + `R.PayoutIdToWinAmount.keys()` per round
- BUT analyzer's `compute_trigger_sessions` (called from `parse_chunk_response`) re-attributes free-spin wins to triggering paid-spin session bucket — this re-attribution mutates `payout_id_by_spin_type_total`
- So:
  - `analyzer_dispatch[pid][st]` = post-attribution count (from `payout_id_by_spin_type_total` after `compute_trigger_sessions`)
  - `fresh_dispatch[pid][st]` = pre-attribution count (raw scan, no compute_trigger_sessions applied)
- For machines with `trigger_session_pattern != null` (M14/M15/M120/M139/M279 + many BCM), these legitimately differ → Layer 4 false-positives on every fleet pull

**Affected fleet fraction**: per memory ~17 documented trigger-session machines, plus many BCM machines that use trigger semantics. Material chunk of the 421-machine fleet.

**Designer v5 must specify a structural fix. Two acceptable approaches**:

(a) **Mirror approach**: Step B also calls `compute_trigger_sessions` after raw scan, producing post-attribution `fresh_dispatch`. Comparison becomes apples-to-apples post-attribution.
   - Trade-off: Step B no longer "independent" — it shares the same `compute_trigger_sessions` helper as analyzer's main pass. A bug in `compute_trigger_sessions` would NOT be caught.
   - Acceptable because Layer 4's goal is "verify dispatch routing correctness", not "verify trigger-session re-attribution correctness" (which is a different concern with its own tests).

(b) **Skip approach**: for machines with `trigger_session_pattern != null` in manifest, Layer 4 doesn't run. They rely on Layers 1-3 only. Manifest flag `layer4_applicable: false` indicates this.
   - Trade-off: trigger-session machines lose Layer 4 protection entirely. But they're already complex enough that human review is part of their lifecycle.

Designer v5 picks one (or both — let user choose at next iteration). Document trade-off explicitly.

**Issue ② — 46 Day-1 candidates need verification spec (Critic v4 Concern B)**

v4 listed 46 candidates but Layer 4 algorithm is brand new in v4 — none have been empirically verified against the new Layer 4. v5 must:

- Add explicit verification deliverable to §6.3 (Phase 3 pre-cutover step): "Before flipping any candidate to `complete: true`, run `rtp_integrity.py --machine M --mode N` against the candidate's latest cached chunks and verify all 4 layers PASS"
- Add to §6.3.3 numbered deliverable list as item 0 (gates the rest of Phase 3)
- Provide expected verification cost estimate: 46 machines × ~5 seconds Layer 4 = ~4 min total + Layers 1-3 ~negligible → ~10 min total verification load (one-time per Day-1 candidate)
- For machines that fail verification: stay at `complete: false`, list in §6.3 as "Day-2 candidates pending QA"

**Issue ③ — Variant override re-enablement path (Critic v4 Concern C)**

v4 §5.5.7 says variant `console_diagnostic_complete: false` override is sticky once set. After underlying flips false→true, variant stays warn-only forever unless someone manually removes override. No reminder mechanism.

**Designer v5 fix**: spec the **override-clearing procedure** as part of §5.5.7:

- When variant's `override_console_diagnostic_complete: false` is set, manifest MUST also record `override_set_at: <timestamp>` + `override_set_reason: <free-form text>` + `override_set_by: <person/team>`
- Once a quarter (or after underlying's flag flips false→true), QA reviews all override entries; if the underlying issue was the same as the variant's override reason, variant's override is removed (resolves variant to underlying's current flag)
- Lint rule: if underlying flag is `true` AND variant override was set BEFORE last underlying flip, emit warning "variant X's override may be stale; review"
- Auditable: override entries logged in git via manifest commit history

**Issue ④ — Layer 4 fleet-pull perf (Critic v4 Concern D)**

v4 claims <5s per machine but didn't measure. v5 must add concrete perf estimate based on:
- Step B iterates chunks (each ~50MB JSON), extracts keys per round
- Per memory: 414k spin chunk ~ 10-15s for full chunk parse in fresh_slotlab analyzer
- Step B is lighter (just key extraction, no full parse) → estimate 2-3s per machine
- Full fleet pull: 421 machines × ~3s = ~20 min total Layer 4 overhead per fleet pull

Or: measure during implementation pass + document actual cost. Designer v5 picks approach.

### Polish issues (Validator v4 doc gaps)

**Issue ⑤** — §9.4 must state RoundWinRules MUST NOT write to `payout_id_by_spin_type_total`. If they do, Layer 4 false-positives because analyzer_dispatch[pid][st] has synthetic counts not in rawdata.

**Issue ⑥** — §5.5.7 add 2-3 lines describing override-clearing procedure (covered by Issue ③ above).

**Issue ⑦** — §9.4 Step C must note: "if Step C mismatch is on a pid in `_unattributed_*` bucket, this corroborates Layer 2's existing fail rather than being false-positive Layer 4 fail". Implementer must NOT suppress these.

---

## §2 What v5 should NOT change

Preserve from v4:
- §1 + §9 operator-diagnostic framing
- Layers 1-3 of integrity check
- `console_diagnostic_complete` mechanism core
- §5.5.4 variant analyzer_features eager cascade
- §5.5.7 variant `console_diagnostic_complete` cascade core (only add override-clearing procedure)
- Phase 2 builds gate code; Phase 5 flips policy
- Hash composition algorithm
- 6-phase migration framework

---

## §3 v5 output expectations

**Output**: `session_artifacts/_arch/04_architecture_proposal_v5.md`

- Aim 1300-1800 lines (similar to v4)
- Focused 7-issue revision (4 substantive + 3 polish); reuse 80%+ of v4
- Touch §9 (Layer 4 algorithm fix for trigger-sessions + RoundWinRules constraint + Step C `_unattributed_*` note)
- Touch §6.3 (Day-1 verification deliverable as item 0)
- Touch §5.5.7 (override-clearing procedure)
- §7 open questions for Critic v5 ≤ 2 (well-scoped changes)

---

## §4 Wave 3 v5 plan

After Designer v5: spawn **Critic v5 + Validator v5 in parallel** (option d = full audit).

Critic v5: verify all 4 substantive concerns (A/B/C/D) addressed structurally; verify 3 polish gaps closed.

Validator v5: walk 8 cases under v5; specifically:
- Test Layer 4 v5 against trigger-session machine (M14 or M15) to verify the structural fix actually prevents the false-positive
- Re-verify Day-1 candidate list with the new verification deliverable
- Test variant override-clearing scenarios (set override + clear → expected behavior)

---

## §5 Stop criteria

If Wave 3 v5 gives both APPROVE → ship to implementation (next session).
If Wave 3 v5 still APPROVE-WITH-REVISIONS:
- Critic must-resolves count < 3 → coordinator inline-patches in 07_decision_v5 + ships
- Critic must-resolves count ≥ 3 → 07_decision_v5 presents options to user (defer / inline / v6)

**This is the LAST team-iteration we should run unconditionally.** Beyond v5 = diminishing returns past the point of useful design refinement.
