# Architecture Review — Decision Summary

> **Inaugural arch-* team run complete.** Main session consolidates 6 agent artifacts into user-facing decision points. **User picks next step.**
>
> Wave 1-3 commits: `da00762` (00_brief) → `726e809` (Wave 1) → `c3e4967` (Wave 2) → `586be64` (Wave 3). Total team wall time: **~50 minutes** (vs ~4-hour estimate; 5× faster).

---

## §1 Both Wave 3 verdicts: **APPROVE-WITH-REVISIONS**

| Reviewer | Verdict | Severity |
|---|---|---|
| arch-critic | APPROVE-WITH-REVISIONS | 11 of 15 change requests MUST-resolve before APPROVE; 5 top concerns; 25 migration risks |
| arch-validator | APPROVE-WITH-REVISIONS | 7 cases walked: 4 OK / 3 awkward / **0 catastrophic break**; 4 spec gaps minor; 0 regressions in 35-cell cross-product |

**Both reviewers converge**: the design foundation (granular hash + manifest plugins + 5-phase migration) is sound. The proposal is **revisable, not rebuild-required**.

---

## §2 What's solid (designer got right)

- **Hash composition algorithm** `sha256(base_hash || sorted(feature_hashes_M_uses))[:12]` — math holds across all 7 walked cases (Validator §4). Zero regressions.
- **Manifest schema** — viable for all 7 cases including hypothetical M400 novel machine.
- **5-phase migration framework** — phases are coherent units of work each with rollback path.
- **Plugin Protocol surface** — 3-class taxonomy (analyzer feature / frontend renderer / per-machine rule) handles the fleet.
- **Backward-compat maintained** for all 7 cases — existing reports continue serving without forced regen (when NULL semantics get specified, see §3 must-fix #4).

---

## §3 What needs revision (consolidated must-fix list)

### Tier 1 — Structural (must-resolve, blocks APPROVE)

**1. "10× blast reduction" claim mismatches historical change pattern.** Critic §1.
- 5 of 7 recent commits map to `features/payouts_by_spin_type.py` which the proposal treats as **universal** under cluster defaults.
- Post-migration blast for that specific change class = 421 (unchanged from today).
- Revision: reframe headline. Show **per-change-class** blast table. Big wins are in non-§3 classes (per-cluster: 12-24×, per-machine: 421×, novel onboarding: 421×) — those need to be the new headline.

**2. Phase 2/3 ordering risk window.** Critic §3.
- Phase 2 deploys `effective_analyzer_version` writer before Phase 3 deploys manifests.
- During the window, `compute_effective_analyzer_version(machine_features=??)` has no manifest → unspecified return value, unspecified rollback path.
- Revision: either spec the window's degenerate behavior (e.g., "during P2-only, returns sha256(base_hash)[:12], all machines stamped identically"), or invert P2/P3 order.

**3. NULL `effective_analyzer_version` for 2030 existing runs / 1007 (m,mode) pairs.** Critic §4. Validator §3.3.
- NULL=stale → forced regen of 2030 reports = violates `00_brief §5.1` (no mass invalidation).
- NULL=current → silent staleness when analyzer touched after migration.
- Revision: dual-comparison spec — NULL rows compared against TODAY's `analyzer_version`; if today matches their stamped `analyzer_version`, mark fresh; otherwise stale + offer regen.

**4. 12 heavy outliers timing.** Critic §5. Validator §3.1.
- Outliers placed in Phase 5 (last). They're the riskiest machines + most likely to break the framework's assumptions.
- Validator's M279 case study confirms one outlier walks cleanly under proposal, but other 11 not validated.
- Revision: move 2-3 outliers (e.g., M279 + M260 + M21) to Phase 2 as **forcing function** that proves the architecture before sliced analyzer ships.

**5. Manifest validation strict vs lenient.** Critic §6.
- §5.5 rule 4 is warning-only. ~22 BCM machines today would emit warnings under their inferred manifest (per Wave 1 `02 §3.5.1` + memory `feedback_invariant_with_fallback_hides_drift.md`).
- Revision: declare strict (block CI on warning) vs lenient (log + ignore) — and how migration handles the 22 violators.

### Tier 2 — Specification gaps (must-resolve, smaller scope)

**6. Cluster gap.** Validator §3.1. ~42 of 421 machines fit no super-cluster. Proposal needs intermediate clusters or explicit `cluster=null` fallback path.

**7. Virtual-side core_md5 disclaim.** Validator §3.2. Touching `core/engine/*.py` flips all 6 virtual machine `code_md5`. Scope-disclaimed but should be explicit in §4.3.

**8. Plugin discovery mechanism.** Validator §3.4. Proposal §5.2 Protocol doesn't specify HOW feature plugins get registered (filesystem scan? registry table?). Phase 2 needs concrete answer.

### Tier 3 — Pre-Phase-1 blockers (must-resolve before any phase ships)

5 open questions from Mapper §5 that Designer §7.9 understates:

**9.** Three analyzer invocation styles, no contract test asserting they behave identically (Critic §pre-1).
**10.** Three summary md5 writers, may not agree today (Critic §pre-1).
**11.** Frontend probe-and-fallback location unknown (Critic §pre-1).
**12.** `_classify_chunks` historical-chunk semantics unclear (Critic §pre-1).
**13.** compareReports cache-bust race (Critic §pre-1).

---

## §4 Other findings (informational, not blocking)

- **Validator 35-cell cross-product**: zero regressions, 4 awkward, 0 broken. Confirms framework holds.
- **Wave 1 found virtual console architecture is actually clean** — share factory + subprocess delegate. Duplication is concentrated in md5/summary/CI helpers (manageable).
- **`compute_analyzer_version` is THE blast surface**, not `compute_code_md5`. Proposal correctly targets it.
- **Fleet is 421, not 393** (brief drift corrected by Wave 1).

---

## §5 Recommended next step (coordinator opinion, not user-binding)

**Designer v2 loop** per `docs/ARCH_TEAM_PROCESS.md §3`.

Rationale:
- 11 must-resolve + 4 spec gaps + 5 blockers = beyond "minor revisions in 07_decision.md" threshold.
- Tier 1 #1 (headline claim mismatch) is a positioning/scope issue Designer needs to reframe coherently, not patchable in 07.
- Tier 1 #2/3 (phase ordering + NULL semantics) need specification work, not commentary.
- Validator says 0 catastrophic break → not "scrap and restart" territory; revisable.

Time estimate for v2 + re-review:
- Designer v2 reading 05 + 06 + integrating changes → ~30-60 min
- Wave 3 re-run (Critic + Validator parallel on v2) → ~15-30 min
- Total → **~75 min** more team work before another decision point

---

## §6 Decision points for you

1. **Path forward**:
   - (a) **Designer v2 loop** — re-spawn designer to produce 04_v2 addressing all 15+4+5 items. Wave 3 re-runs. ~75 min team work. ← Coordinator recommends.
   - (b) **Accept current proposal + caveats** — implementation team handles 15+4+5 as known issues during phase 1. Immediate. Risk: implementation pass may stall on undefined behavior.
   - (c) **Trim scope** — accept Tier 1 #1-5 + Tier 2 #6-8 only as must-fix; defer Tier 3 #9-13 to implementation pass. ~45 min v2 work.
   - (d) **Halt + reconsider** — if you think the design direction itself is wrong, abandon and re-scope before continuing.

2. **Implementation timing**: even after APPROVE, implementation is a separate next session. Do you want to schedule it now or after seeing v2?

3. **Any user concerns the team missed?** Wave 1-3 agents read your verbatim quotes from 00_brief §4. If you have new concerns (or sense the team's framing is off on something), surface now.

---

## §7 Cross-references

- 00 brief (contract): `session_artifacts/_arch/00_brief.md` — commit `da00762`
- 01 pipeline map: `session_artifacts/_arch/01_pipeline_map.md` — 638 lines
- 02 taxonomy: `session_artifacts/_arch/02_taxonomy.md` — 643 lines
- 03 coupling audit: `session_artifacts/_arch/03_coupling_audit.md` — 960 lines
- 04 proposal: `session_artifacts/_arch/04_architecture_proposal.md` — 1477 lines
- 05 critique: `session_artifacts/_arch/05_critique.md` — 1216 lines
- 06 validation: `session_artifacts/_arch/06_validation.md` — 452 lines
- This decision summary: `session_artifacts/_arch/07_decision.md`
- Process spec: `docs/ARCH_TEAM_PROCESS.md`
- Memory pointer: `memory/feedback_arch_team_process.md`

Total artifact volume: 5586 lines across 7 markdown files.
