# 00_brief v4 Addendum — Designer v4 direction (post-Wave-3-v3 critic findings)

> **Read in addition to** `00_brief.md` + `00_brief_v2_addendum.md` + `00_brief_v3_addendum.md`. This is the v4 contract. **Focused 3-issue revision**, not full rewrite.
>
> Background: Wave 3 v3 critic v3 verdicted APPROVE-WITH-REVISIONS with 2 hard + 1 soft must-resolves. User picked option (c) — full Designer v4 + Critic v4 + Validator v4 cycle. v4 = `04_architecture_proposal_v4.md`.

---

## §1 Three issues to fix in v4

### Issue ① — Layer 4 algorithm doesn't catch dispatch-routing bugs (HARD, substantive)

**Problem (per Critic v3 §3 M1)**: Critic v3 verified by reading `fresh_slotlab/player_impact_analyzer.py:6438-6509` that v3's Layer 4 algorithm compares:
- `payouts_by_spin_type[label].rows[pid].hit_count`
- `payout_ids_top20.rows[pid].spin_type_breakdown[spin_type=N].count`

**BUT** both fields are populated from the same in-memory dict `payout_id_by_spin_type_total` — they're two readouts of the same dispatch result, not two independent derivations. Equality is trivially true. Layer 4 catches **nothing** about dispatch routing correctness.

**v4 fix**:

Replace Layer 4 with an **independent rawdata-level cross-check**:

```
Layer 4 (revised): Dispatch routing self-consistency

For each (machine, mode) being analyzed:

  Step A — Compute analyzer's dispatch result (already computed in main pass):
    analyzer_dispatch[pid][st] = count from payout_id_by_spin_type_total
    (the dict that drives both payouts_by_spin_type and spin_type_breakdown)

  Step B — Compute fresh independent dispatch from rawdata:
    Iterate all chunks fresh; for each round R:
      - Extract R.PayoutIdToWinAmount.keys() → list of pids fired this round
      - Extract R.SpinType → the ST for this round
      - For each pid in that list:
          fresh_dispatch[pid][R.SpinType] += 1

  Step C — Compare:
    For every (pid, st) pair:
      assert analyzer_dispatch[pid][st] == fresh_dispatch[pid][st]
    If mismatch → Layer 4 fails for this machine with specific (pid, st) cited.
```

The Step B scan reads rawdata directly without going through the analyzer's dispatch rules — it just trusts what rawdata's `SpinType` and `PayoutIdToWinAmount` fields say. If analyzer's dispatch logic has a bug routing rounds to wrong ST (e.g., M31 pid 8 incorrectly attributing ST=44 rounds to ST=43 bucket), this cross-check exposes it.

**Performance note**: Step B is an extra pass through rawdata. For 414k spins ~ negligible (<5s). Designer should note this cost in §9 + mention it's only enabled when `console_diagnostic_complete: true` (i.e., paid for QA confidence per machine).

**Spec must include**:
- Pseudocode for Step B (above)
- Performance estimate
- What happens when rawdata's SpinType field is missing or invalid (edge case)
- Whether this runs every fleet pull or just sampled / triggered

### Issue ② — Day-1 strict mode ships with zero members (HARD, small fix)

**Problem (per Critic v3 §3 M2)**: v3 §5.5.3 sets all 421 machines to `console_diagnostic_complete: false` at Phase 3 cutover. §8.13 punts the flip workflow as out-of-v3-scope. Phase 5 enables strict-error policy for `complete: true` machines — but Day-1 has zero such machines. Mechanism ships dormant.

**v4 fix**: Enumerate Day-1 strict candidates explicitly in §6.3 (Phase 3 deliverable).

Candidates (from Wave 1-3 empirical evidence):
- **SC-Vanilla cluster** (45 machines per `02_taxonomy.md` §4.2): all 5 axes co-clustered, no per-machine rules needed, no fallback evidence in historical reports
- **M274**: empirically passes all 4 layers per Validator v2 §2.6 — `_bcm_cycle` anchor present (4.87% RTP attributed correctly) + 5801 anchor present (54.11% RTP) + 0 `_unattributed_*` rows + sum(pid rtp_pp) == summary.rtp
- Other candidates per Validator v2 §2 walk-throughs that passed cleanly (M1, M15, M37 — verify which apply)

**Flip criteria for future machines** (Designer to spec): a machine flips from `false` → `true` when:
- All 4 layers (Layers 1-4) pass on a recent representative rawdata sample
- No known issue / pending rule update for the machine
- Audit log records who flipped + when + based on which report version

**v4 §6.3 should include**: Day-1 enumerated list (target: 45+ machines) + flip criteria above.

### Issue ③ — Variant cascade asymmetry (SOFT, 1-line fix)

**Problem (per Critic v3 §3 S1)**: v3 §5.5.4 declares variants share `analyzer_features` (eager cascade — they ARE the same machine). v3 §5.5.7 declares variants have their own `console_diagnostic_complete` flag (independent per-variant). Inconsistent stance.

**v4 fix**: 1 paragraph in §5.5.7 stating:

```
Variants inherit console_diagnostic_complete from their underlying machine
(eager cascade, same as analyzer_features). Rationale: variants share parser
code with underlying by definition (per §5.5.4); they share parser quality;
they share diagnostic capability. If the underlying machine's diagnostic
coverage is incomplete, all variants are equally incomplete. If verified
complete, all variants are equally complete.

Exception: a variant may declare an OVERRIDE `console_diagnostic_complete:
false` (regression case — variant's user-decision config exposed a new edge
case not previously verified). Override never flips false → true; only true
→ false. Underlying's flag controls the default.
```

---

## §2 What v4 should NOT change

Per addendum v3 §3 (still valid):
- Variants design (#1) — addendum v2 §1.5 + addendum v3 §3 #1 resolved
- Eager cascade for analyzer_features (#4) — resolved
- Phase 5 ships before Phase 6 BCM audits (#5) — accepted by user

Per addendum v3 (still valid):
- Operator-diagnostic framing in §1 + §9 — keep
- Layers 1-3 of integrity check — keep
- `console_diagnostic_complete` mechanism — keep
- Eager variant cascade for analyzer_features — keep
- Phase 2 builds gate code, Phase 5 flips policy — keep
- Hash composition algorithm — keep

---

## §3 Output expectations

**Output**: `session_artifacts/_arch/04_architecture_proposal_v4.md`

- Aim 1300-1700 lines (slight expansion for Layer 4 algorithm rewrite + Day-1 enumerated list)
- This is a **focused 3-issue revision**. Reuse 80%+ of v3.
- Touch §5.5.7 (variant cascade ③)
- Touch §6.3 (Day-1 strict candidates ②)
- Touch §9.4 (Layer 4 algorithm ①) + add Step A/B/C pseudocode

---

## §4 Cross-references

- Critic v3 source-code finding: `05_critique_v3.md` §3 M1 (the specific reading of `fresh_slotlab/player_impact_analyzer.py:6438-6509`)
- Validator v2 §2.6 — M274's empirical 4-layer pass (basis for Day-1 candidate list)
- Validator v2 §2 walkthroughs — M1, M15, M37 etc. (additional candidates)
- Memory: `feedback_invariant_with_fallback_hides_drift.md`, `feedback_arch_team_process.md`

---

## §5 Wave 3 v4 plan

After Designer v4 completes:
- Spawn **Critic v4 + Validator v4 in parallel** (user picked option c — full audit)
- Critic v4: verify v4 actually fixes the 3 issues + no new structural regressions
- Validator v4: re-walk same 7-8 cases under v4; specifically verify the new Layer 4 algorithm catches dispatch-routing bugs (could construct a synthetic mismatch case to prove it)
- Both produce verdicts → 07_decision_v4.md → user picks final ship decision

Expected total: ~45 min for v4 cycle (Designer ~20 min + parallel Critic+Validator ~15-20 min + decision ~5 min).
