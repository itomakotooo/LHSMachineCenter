# 00_brief v3 Addendum — Designer v3 direction (post-Wave-3-v2 user feedback)

> **Read in addition to** `00_brief.md` + `00_brief_v2_addendum.md`. This addendum is the contract for Designer v3 (= `04_architecture_proposal_v3.md`).
>
> Background: Wave 3 v2 was split verdict (Validator APPROVE; Critic APPROVE-WITH-REVISIONS 6 must-resolves). User reviewed 07_decision_v2.md. Of the 6 must-resolves, user resolved 3 via clarification (#1 #4 #5) and asked for detailed explanation on the other 3 (#2 #3 #6). The detailed back-and-forth produced critical reframes that v3 must encode.

---

## §1 Critical reframe — Console's actual purpose

**User's exact framing (verbatim)**:

> "console 的诉求是帮我分析真机数据,找到问题并优化,所以 console 必须要是正确的,真机数据是有可能存在错误的。包括刚刚我说的 rtp 报错,也是 console 认为分析不出机器的 rtp 报错。"

> "rawdata 错的意思不是机台的逻辑和数据错误,就是比如策划 rtp 配错了,手滑了,之类的。"

**What this means for architecture**:

1. **Console is a diagnostic tool for the operator (策划)** — not an internal correctness checker. Its primary value is helping the operator find configuration mistakes / unintended behavior in production machines they've configured.

2. **The data chain**:
   - 策划 / operator configures the machine (paytable, weights, etc.)
   - Production machine executes the configuration faithfully (machine code is correct)
   - Rawdata reflects the configured behavior (which may be off-target if operator misconfigured)
   - **Console's job: analyze rawdata correctly, surface whether the operator's configuration produced the intended result**

3. **"RTP error" semantics**:
   - NOT "the analyzer's parser has a bug" (internal correctness)
   - NOT "the sampled RTP statistically deviates from target"
   - IT IS: **"console claims it cannot reliably analyze this machine right now"** — could be (a) operator misconfigured, (b) console's rules don't yet cover this machine's case, (c) data corruption. All three trigger the same "I can't tell, investigate" signal.

4. **Console correctness is the precondition**: if console's logic itself is wrong, the operator can't trust the diagnostic output. So `console correct ∧ machine configured correctly → RTP signal trustworthy`. Console MUST be correct so its signals are trustworthy.

---

## §2 Three structural must-resolves Designer v3 must address

### Must-resolve #2 — RTP integrity gate's blind spot (post-clarification)

**Reframed problem**: v2's RTP integrity gate (§9) checks three layers (hard invariant / fallback share / attribution anchor), but **doesn't detect within-pid misattribution between SpinTypes**.

Example case (per session memory + M31 ST-split work):
- pay_id 8 fires 33,167 times: rawdata shows 22,370 in ST=43 (paid) + 10,797 in ST=44 (free)
- Total RTP attributed to pay_id 8: correct (113 M credits)
- BUT: if console's logic mistakenly attributes all 33,167 to ST=43 (or any other proportion than rawdata's true 22,370:10,797), the per-ST breakdown is silently wrong
- Current gate doesn't catch this — sum still matches, no fallback bucket trigger

**v3 fix requirement**:

Add a **Layer 4 — Per-SpinType attribution self-consistency check**:
- For every pay_id whose summary includes `spin_type_breakdown`, verify the per-ST counts match the count derivable from rawdata's `SpinType` field on rounds where that pay_id fired
- Mechanism: cross-check `payouts_by_spin_type[label].rows[pid].hit_count` against `payout_ids_top20.rows[pid].spin_type_breakdown[spin_type=N].count` for every (pid, ST) pair
- Both must be derived from the same source rawdata; equality is mechanical
- Fail: emit explicit error for that machine: "Per-ST attribution inconsistent for pay_id X: expected Y, got Z. Likely cause: console rule for [round_classification function name] doesn't match rawdata's ST values. Investigate."

**Framing in v3**: Layer 4 is part of "console gives operator trustworthy signal" — same operator-diagnostic purpose as Layers 1-3.

### Must-resolve #6 — Threshold authority replaced with per-machine completeness declaration

**Reframed problem**: v2's `fallback_share_pct_max` threshold (e.g., 0.5%) is the wrong abstraction. Under the operator-diagnostic framing, **any unattributed RTP > 0 is a signal to investigate**, not a "statistical tolerance".

**v3 fix requirement**:

Replace `fallback_share_pct_max` with per-machine completeness declaration in manifest:

```jsonc
{
  "machine": "M14",
  "console_diagnostic_complete": true,    // console claims it can diagnose this machine
  "analyzer_features": [...]
}
```

```jsonc
{
  "machine": "M250",
  "console_diagnostic_complete": false,   // still developing rules for this machine
  "analyzer_features": [...]
}
```

**Behavior**:
- `console_diagnostic_complete: true`:
  - Any RTP integrity failure (Layers 1-4 from §9) → **hard error**, blocks individual machine's report but does NOT block fleet pull
  - Error message guides operator: "For machine X, console can't account for Y% of RTP. Cause could be: (a) operator misconfigured something / (b) console rule needs update / (c) data corruption. Investigate."
- `console_diagnostic_complete: false`:
  - Layer failures → warning printed but report still produced + flagged "[INCOMPLETE]"
  - Used during development of new machine support; allows fleet pull to continue without blocking
  - Migration path: when all rules added + tested, flip to `true`

**No numeric threshold needed.** Either console diagnoses cleanly (every round accounted for, per-ST splits self-consistent), or it explicitly flags "I can't tell".

**Initial values**: all 421 machines start `console_diagnostic_complete: false` at Phase 3 cutover. Per-machine flip to `true` happens as machine rules are verified clean by some QA pass (out of scope for v3 — implementation team handles).

### Must-resolve #3 — Phase 2 demo references Phase 5 RTP gate (circular)

**Simple fix**: Move RTP integrity gate (§9) implementation foundation to **Phase 2**, not Phase 5. The gate's enforcement (`exception_policy=error` default for `console_diagnostic_complete: true` machines) can still flip in Phase 5; the gate code itself ships in Phase 2 so the 12 forcing-function-machine demo can use it.

Net: Phase 2 includes the RTP integrity gate code (Layers 1-4) running in warn-only mode. Phase 5 only flips the default policy for `complete: true` machines from warn to error.

---

## §3 Items NOT in v3's scope (already resolved or accepted)

- **#1 `inherits_from` for variants**: keep as-is. User clarified variants = same machine logic, different user-decision configs. Sharing analyzer rules across variants is by design (same parser; storage isolated per variant). Designer v3 should add 1-paragraph justification in §5.5; no algorithmic change.
- **#4 variant cascade semantics**: lazy vs eager resolved — eager. Variants must follow underlying's analyzer rule changes because parser logic is shared (per #1).
- **#5 Phase 5 strict default ships before Phase 6 BCM audits**: user explicitly accepted ("问题不大"). v3 can keep current ordering. The `console_diagnostic_complete: false` mechanism from #6 naturally protects 22+ today-broken BCM machines: they stay `complete: false` until rules added; no day-1 red banners.

---

## §4 Two minor validator gaps from v2 (also fix in v3)

- §5.5 enumerate which manifest fields support `per_mode_overrides`
- §9.7 mark known-broken triage table as "illustrative, not exhaustive"

Both 1-paragraph docs polish.

---

## §5 Output expectations

**Output**: `session_artifacts/_arch/04_architecture_proposal_v3.md`

- Aim 1300-1800 lines (slightly longer than v2's 1490 due to additional Layer 4 spec + reframed §9 + console_diagnostic_complete mechanism + variant justification)
- This is a **focused revision**, not full rewrite. Reuse v2's good parts (manifest schema, plugin Protocol, hash composition algorithm, 6-phase migration).
- Rewrite §9 entirely (new operator-diagnostic framing + add Layer 4 per-ST self-consistency check + replace threshold with completeness flag)
- Touch §5.5 (manifest schema: add `console_diagnostic_complete` + variant justification + per_mode_overrides enum)
- Touch §6 Phase 2 (move RTP gate foundation here)
- Touch §6 Phase 5 (just flips default policy now)
- Single pass — no internal iteration

---

## §6 What v3 should explicitly say in §1 (Problem statement)

Refine v2's problem statement to include the operator-diagnostic framing. Specifically:

- Console is the operator's diagnostic tool for production machines they configure
- Operator may misconfigure (RTP target wrong, paytable typo, etc.)
- Production machine faithfully executes its configuration; rawdata reflects whatever was configured
- Console must analyze rawdata correctly (no parser bugs) so its diagnostic signals are trustworthy
- When console "can't diagnose" a machine, it must say so explicitly with actionable error message — NOT silently fall back to wrong numbers
- The architecture's purpose: deliver per-machine, accurate-or-explicitly-error diagnostic signals to the operator across 421+ machines, while supporting cheap addition of new machines / new features without invalidating unrelated reports

---

## §7 No Wave 3 v3 needed if Designer v3 succeeds cleanly

Per coordinator analysis in 07_decision_v2.md §5: validator already gave clean APPROVE on v2; v3 changes don't alter case-level walkthroughs (just adds layer 4 + reframes §9). Spawn **critic v3 only** to verify Designer v3 actually addressed the 3 must-resolves. Skip validator v3 unless critic flags case-level concerns.

After critic v3:
- If APPROVE → write `07_decision_v3.md` summarising → present to user → user picks "proceed to implementation"
- If APPROVE-WITH-REVISIONS → coordinator decides whether minor (inline patch) or major (Designer v4 — but at that point we should probably ship)
