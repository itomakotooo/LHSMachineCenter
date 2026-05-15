# Architecture Review v2 — Decision Summary

> Wave 1-3 v1 → v2 iteration complete. Branch `arch/console-refactor`.
> Commits this iteration: `a247a40` (addendum) → `d60c02d` (Designer v2) → `55a1526` (Wave 3 v2 critic + validator).
> Total artifact: 10 files, ~8800 lines (5586 v1 + 2114 new v2 reviews + 1490 new v2 proposal + 144 addendum + 144 this file).

---

## §1 v2 outcome

| Reviewer | v1 verdict | v2 verdict | Change |
|---|---|---|---|
| arch-critic | APPROVE-WITH-REVISIONS (11/15 blockers) | APPROVE-WITH-REVISIONS (6/15 blockers) | **−5 blockers (−45%)** |
| arch-validator | APPROVE-WITH-REVISIONS (4 gaps) | **APPROVE** (2 minor doc gaps) | First clean APPROVE this run |
| Stress questions full-pass | 0/17 | 1/18 | First ✓ |
| Cases broken | 0 | 0 | Stable |
| Cross-product regressions | 0 | 0 | Stable |

**Trajectory: design is genuinely converging.** v1→v2 cut critic issues by half. Validator went from conditional to clean APPROVE.

---

## §2 What Validator empirically validated

Used live Bash queries against actual M274 + M250 rawdata + reports:

- **RTP integrity gate (constraint S enforcement) WORKS against M274's known leak case**: real M274 mode 1 report (`reports/M274/mode_1/versions/rv_20260513T034506Z`) passes all 3 layers; sum(pid rtp_pp) matches summary.rtp exactly; required anchors `_bcm_cycle` (4.87% RTP) + `5801` (54.11%) both present. Gate would have caught the pre-rule 4.87% leak — exactly the failure mode user flagged.
- **M250 graduation workflow (Designer v2 §4.3 Example 6) is realistic**: M250 rawdata has the S-BCM-21k extras + 17 machine-specific logicClassNames that the demo assumes. Memory claim of 100% fallback pre-rule validates against real config.
- **40-cell cross-product (8 cases × 5 commit classes): 0 regressions.**

This is direct evidence the design works for your stated pain points.

---

## §3 Critic's 6 remaining blockers — categorized

**Structural (need design work)**:

1. **`inherits_from` reintroduces clustering** — v2 added `inherits_from` for 166 variants (e.g., 85 M273 variants inherit underlying's manifest). Critic says this contradicts addendum §1.5 "every machine potentially unique". Real tension. Designer needs to either drop inheritance + give every variant its own manifest, OR explicitly justify variants as a defensible exception (variants ARE the same underlying machine by definition; might be a defensible carve-out).
2. **RTP integrity gate has 2 holes**: (a) sampling noise can trigger false-positive on fallback share threshold; (b) gate operates at pid level, doesn't catch silent within-pid attribution drift (e.g., pid 8 fires in both ST43 and ST44 but rtp gets attributed to one only). Need 4th-layer check or explicit scope-out.
4. **`inherits_from` cascade semantics** — when underlying machine updates, do variants auto-update (eager) or stay frozen (lazy)? Both have problems; v2 didn't pick.

**Schedule fixes (simple reorder)**:

3. **Phase 2 forcing-function demo references RTP gate from Phase 5** — circular dependency. Fix: stub the gate in Phase 2 + go live in Phase 5; or move gate to Phase 2.
5. **Phase 5 strict-error default ships before Phase 6 BCM audits** — Phase 5 enabling strict RTP enforcement before Phase 6 cleans up 22+ today-broken BCM machines = day-1 red banners on those machines. Fix: ship Phase 5 with warn-only default; flip strict after Phase 6.

**Definition (governance only)**:

6. **Threshold authority** — who picks the `fallback_share_pct_max` cutoff? User? Per-machine? Centralized? Need owner.

---

## §4 Two minor validator gaps (documentation polish)

- §5.5 should enumerate which manifest fields support `per_mode_overrides` (M279 mode 1 Wheel vs modes 2/5/7 MoveSpin shows the need)
- §9.7 known-broken triage table should be marked "illustrative not exhaustive"

Both 1-paragraph fixes, no algorithmic change.

---

## §5 Recommended path (coordinator opinion)

**Option (c) — hybrid**: split the 6 blockers by type.

- **Patch in main session inline into `04_v2`** (now, ~15min): #3 phase-2-demo-stub-gate, #5 Phase 5 warn-default-until-Phase-6, #6 threshold-authority note + 2 validator doc gaps
- **Designer v3 for structural items** (~30-45min): #1 inherits_from philosophy reconciliation + #2 RTP gate hole closure + #4 cascade semantics spec  
- **Skip Wave 3 v3 — validator already APPROVE**. After Designer v3, Critic v3 only (no validator re-run unless v3 makes case-level changes).

Net: **~50 min more team work + main-session inline patches** vs ~75 min for full v3 + Wave 3 cycle.

**Alternative options**:

- **(a)** Full Designer v3 + Wave 3 v3 cycle — ~75min, no inline shortcut
- **(b)** Accept v2 as-is + treat Critic's 6 as implementation-pass concerns — defensible given Validator APPROVE, but Critic's #1 and #2 are real design holes that will bite if not pre-spec'd
- **(d)** Halt + go straight to implementation — Validator says it works; structural items can surface during build

Coordinator leans (c): targeted, fast, addresses real structural items without re-spawning everyone.

---

## §6 What you decide

1. **Path**: (a) full v3 / (b) accept v2 / **(c) hybrid (recommended)** / (d) implement now
2. **Implementation timing**: after v3 (if c/a), now (if b/d), or wait + re-evaluate?
3. **`inherits_from` for variants** specifically — keep it (need design justification) or remove it (force 166 variant manifests)? Designer v3 input.
4. **RTP gate scope** — add 4th layer for within-pid attribution, OR scope it out explicitly in v3? Designer v3 input.

---

## §7 Cross-references

- v1 artifacts: 00 brief / 01 mapper / 02 taxonomy / 03 auditor / 04 v1 / 05 v1 / 06 v1 / 07 v1
- v2 artifacts: 00_v2_addendum / 04_v2 (1490 lines) / 05_v2 (1553 lines) / 06_v2 (561 lines) / this file
- Process: `docs/ARCH_TEAM_PROCESS.md`
- Memory pointer: `memory/feedback_arch_team_process.md`
