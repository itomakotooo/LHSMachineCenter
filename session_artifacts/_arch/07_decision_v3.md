# Architecture Review v3 — Decision Summary

> Branch `arch/console-refactor`. Total iteration commits: `da00762` → `c98ff67` (v1) → `f3f6c80` → `32486c2` (v3).
> 14 artifacts total in `session_artifacts/_arch/`.

---

## §1 Trajectory (real convergence)

| Iteration | Critic verdict | Critic must-resolves | Validator verdict |
|---|---|---|---|
| v1 | APPROVE-WITH-REVISIONS | 11/15 | APPROVE-WITH-REVISIONS (4 gaps) |
| v2 | APPROVE-WITH-REVISIONS | 6/15 | **APPROVE** (2 minor doc gaps) |
| v3 | APPROVE-WITH-REVISIONS | **2 hard + 1 soft** | (skipped; v2 still valid since v3 didn't change case-level behavior) |

**Trajectory genuinely converging**: 11 → 6 → 3 issues. Stress questions full-pass rate: 0/17 → 1/18 → **8/18** (first iteration where majority passed).

---

## §2 What v3 got right (Critic acknowledged)

- §1 + §9 **genuine operator-diagnostic reframe** (not cosmetic) per user's clarification
- `console_diagnostic_complete` flag cleanly eliminates v2's "threshold authority" + "false-positive cliff" concerns
- Phase 2/5 circular dependency resolved (RTP gate code in Phase 2)
- Eager variant cascade explicit + justified (variants = same machine, different user decisions)
- Validator's 2 doc gaps closed

---

## §3 What's still wrong (Critic's 3 remaining)

### Hard M1 — Layer 4 doesn't catch what it's designed for (substantive)

**Critic actually read the analyzer source code at `fresh_slotlab/player_impact_analyzer.py:6438-6509`** and discovered Layer 4's algorithm is wrong:

- Layer 4 compares `payouts_by_spin_type[label].rows[pid].hit_count` vs `payout_ids_top20.rows[pid].spin_type_breakdown[N].count`
- **BOTH come from the same in-memory dict** `payout_id_by_spin_type_total`
- They're not two derivations from rawdata — they're two readouts of the same dispatch result
- So Layer 4 catches "the emitter accidentally formatted the same data inconsistently in 2 places" but **NOT** "the analyzer dispatched rounds to the wrong SpinType"
- The M31 motivating bug from addendum (analyzer attributes pid 8 wrong across ST=43 vs ST=44) **would slip past Layer 4**

This is exactly the failure mode the v3 addendum's #2 was supposed to catch. Designer thought they'd solved it but the algorithm doesn't actually do what they claim.

**Fix**: Layer 4 needs to compare analyzer's dispatch result against a **fresh independent scan of rawdata's SpinType field**. Different code path. Designer v4's work.

### Hard M2 — Day-1 strict mode ships empty (small fix)

- Phase 3 cutover sets all 421 machines to `console_diagnostic_complete: false`
- Phase 5 flips strict-error policy for `complete: true` machines
- §8.13 punts the flip workflow as "QA team's job, out of scope"
- **Net result**: Phase 5 day-1 = 0 machines in strict mode. Mechanism is dormant.

**Fix**: enumerate Day-1 strict candidates in §6.3 (SC-Vanilla 45 machines + M274 are empirically clean per Validator v2 §2.6). Define flip criteria explicitly. 1-paragraph spec.

### Soft S1 — Variant cascade asymmetry (1-line fix)

- §5.5.4 says variants ARE same machine (eager cascade for `analyzer_features`)
- §5.5.7 says variants AREN'T (per-variant `console_diagnostic_complete`)
- Inconsistent. Since variants share parser, they share parser quality, therefore share completeness flag.

**Fix**: 1 line saying completeness cascades from underlying to variants too.

---

## §4 Recommended path (coordinator opinion)

**Designer v4 SHORT focused on M1 only + main session inline M2/S1** (~25 min total).

Why:
- M1 is real algorithm work (designer needs to spec independent rawdata scan)
- M2 + S1 are mechanical patches I can do in main session
- v3 is otherwise solid (8 ✓ on stress questions, both reviewers within touching distance of APPROVE)
- One more focused pass + spawn critic v4 to verify → ship

After v4: only critic v4 (Validator v2 APPROVE preserved since v4 only changes Layer 4 algorithm).

---

## §5 Alternative paths

| Option | Description | Time |
|---|---|---|
| **(a) Designer v4 short + inline patches (recommended)** | v4 just M1; I patch M2/S1 inline; critic v4 verifies | **~25 min** |
| (b) Accept v3 + scope M1 out | Frame Layer 4 explicitly as "emitter slice check"; dispatch-routing bugs need separate tool (future work) | immediate |
| (c) Full Designer v4 + Critic v4 + Validator v4 | More thorough but probably overkill | ~45 min |
| (d) Implement now, address M1/M2/S1 during build | Implementation team likely surfaces M1 in the M31-style debugging anyway | immediate |

---

## §6 What you decide

1. **Path**: a / b / c / d — coordinator leans (a)
2. **Implementation timing**: after v4 (a/c) / immediately (b/d)
3. **For (a)**: how should Layer 4 actually work? Two options:
   - (a-i) Fresh independent rawdata scan (correct but costs an extra pass over rawdata per machine)
   - (a-ii) Add a checksum / hash at dispatch time that downstream comparison can verify (cheap but requires analyzer code change first)
   - Or let Designer v4 propose both alternatives — I lean on that.

---

## §7 Cross-references

- v1-v3 brief: `00_brief.md`, `00_brief_v2_addendum.md`, `00_brief_v3_addendum.md`
- Wave 1: `01_pipeline_map.md`, `02_taxonomy.md`, `03_coupling_audit.md`
- Wave 2: `04_architecture_proposal.md` (v1), `_v2.md`, `_v3.md` (1261 lines)
- Wave 3: `05_critique.md`, `_v2.md`, `_v3.md` (1274 lines); `06_validation.md`, `_v2.md` (v3 skipped)
- Phase 4: `07_decision.md`, `_v2.md`, `_v3.md` (this file)
- Process: `docs/ARCH_TEAM_PROCESS.md`
- Memory: `feedback_arch_team_process.md`
- Branch: `arch/console-refactor` (HEAD `32486c2`)

15 artifacts total, ~13000 lines across the whole arch review.
