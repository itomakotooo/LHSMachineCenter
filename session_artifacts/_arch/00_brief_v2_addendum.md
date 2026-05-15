# 00_brief v2 Addendum — Designer v2 direction (post-Wave-3 user feedback)

> **Read in addition to** `00_brief.md` (original spec). This addendum supersedes specific points where conflicts exist.
>
> Background: Wave 3 (05_critique + 06_validation) both verdicted APPROVE-WITH-REVISIONS. User read 07_decision summary, gave 5 specific updates that change Designer v2's direction non-trivially. v2 = `04_architecture_proposal_v2.md`.

---

## §1 Five updates from user (Designer v2 must integrate all five)

### Update 1 — Reframe "10× blast reduction" headline (response to Critic Tier 1 #1)

**User**: 没问题(OK with Critic's critique here)

Drop the singular "10× reduction" framing. Replace with a **per-change-class blast table**:

| Change class | Blast under current architecture | Blast under proposal | Reduction |
|---|---|---|---|
| Per-cluster feature edit | 421 machines | 12-24 machines | 12-24× |
| Per-machine bespoke fix | 421 machines | 1 machine | 421× |
| Novel machine onboarding | 421 machines | 1 machine | 421× |
| **Universal feature edit** (e.g., adding a new field to base aggregator) | **421 machines** | **421 machines** | **1× (no reduction)** |
| Frontend renderer plugin update | varies | machines using that renderer | varies |

Universal-feature class explicitly named as "no reduction here, by design — the only kind of change where this is unavoidable". Be honest about what proposal does + doesn't reduce.

### Update 2 — Migration is a clean break; do NOT preserve historical reports

**User**: "不用 care 历史报表,全删重建都行"

Implications for Designer v2:

- The 2030 historical runs / 1007 (m, mode) pairs at cutover: **OK to invalidate all**. Forced regen is acceptable, not a violation.
- **No NULL `effective_analyzer_version` semantics needed** — old rows don't migrate, they're gone.
- **No dual-comparison logic needed** for pre/post-cutover compatibility.
- Phase 3 deliverable simplifies dramatically.
- Critic Tier 1 #3 (NULL semantics) becomes **moot** — write "n/a per user clean-break authorization in 00_brief_v2 §1.2" in v2.

This is a **large simplification** of migration design. Phase ordering becomes much cleaner because we don't need to support a transition window where old + new reports coexist.

### Update 3 — 12 "known-complex" machines promoted to Phase 2 forcing function (not Phase 5)

**User**: 同意(implicit through challenging the "12 outliers" framing — see Update 5)

Phase 2 (slice analyzer + first plugin extraction) must include manifests + plugin loading for the 12 machines today known to need per-machine handling:

`M21, M260, M268, M279, M274, M113, M11, M250, M108, M65, M67, M120`

**But the framing is critical** (see Update 5): these are NOT "the 12 exceptions". They are "the 12 cases of known complexity we currently have evidence for". Tomorrow's investigation may surface another 30. The architecture must accommodate this growth path **as the common path**, not as an escape hatch.

Phase 2 deliverable must prove: (a) these 12 onboard cleanly under per-machine plugin path, AND (b) the framework supports adding "machine X graduated to per-machine code" without architectural change.

### Update 4 — RTP integrity hard constraint (NEW; fleet-wide)

**User**: "rtp 分析必须健壮。即使并没有为所有机台实现具体的分析功能,但全局拉取必须保证 rtp 正确或者对于指定机台的报错"

Add as **constraint S** in 00_brief §5 (mandatory; not negotiable):

> **For any fleet-wide pull / analysis run, the system MUST EITHER (a) emit correct RTP for each machine in the run, OR (b) emit an explicit per-machine error identifying that machine cannot be correctly analyzed and why. Silent fallback to `_unattributed_st*` / `_other` / wildcard buckets without an explicit per-machine error is forbidden.**

Implications for Designer v2:

- **RTP integrity is the safety net for the entire architecture** — not just a quality property
- It is the **enforcement mechanism for manifest correctness**: if a machine's manifest declares "I use plugin X" but RTP doesn't add up under X's logic, the system emits an error, not a silent wrong number
- Memory reference: `feedback_invariant_with_fallback_hides_drift.md` (M274 had 4.87% RTP attribution leaked to `_unattributed_st139` fallback bucket; M250 has 100% RTP leak per memory). These were silently wrong RTPs — exactly the failure mode this constraint prevents.
- The integrity check must run **on every fleet-wide pull**, not just on machine-specific tests
- Designer v2 should specify: how is RTP correctness checked? What triggers the per-machine error? How is the error surfaced to the operator?

### Update 5 — Architectural philosophy shift (NEW; most fundamental)

**User**: "12 个机台不是我提供的,估计是之前你自己归纳的,那估计就有很大的问题,比如其实所有的机台都有可能有这种程度的复杂性。所以你要做的不是剩下的机台都是 ok 的,而是保持警惕。"

This is the most important update. The proposal v1's "84% clean cluster + 12 outliers" framing is **misleading** because:

- The 12 outliers were derived by taxonomist from observable surface signals (SpinType set / feature shape / paytable structure / rawdata schema / declared rule reliance)
- These surface signals **only show what's been encoded or surfaced today**
- Real-world examples of "looked normal until investigated":
  - **M274**: only flagged after someone investigated; before that it appeared "clean" but had 4.87% RTP leak
  - **M250**: 100% RTP leak discovered only after deeper analysis
  - Memory: `feedback_invariant_with_fallback_hides_drift.md` documents this pattern fleet-wide
- "logicClassNames = Plain" does not mean simple; it means no one filled in extras
- Identical rawdata schema does not mean identical mechanics; semantics can vary

**Designer v2 must therefore shift the architectural philosophy** from:

> **OLD** (proposal v1): "default cluster (~84%) covers most machines + escape hatch tier (12 outliers) for known exceptions"

To:

> **NEW** (proposal v2): "every machine is potentially unique. Sharing is opt-in via manifest declaration. RTP integrity check (constraint S) validates that the machine's declared manifest actually produces correct RTP. No machine is assumed 'safe to lump together' without proof."

Concrete changes in v2:

1. **No 'default cluster, no manifest needed' tier.** Every one of the 421 machines has an explicit manifest. Vanilla machines have short manifests; complex machines have long manifests. Quantitative difference only.
2. **Plugin composition is the contract, not the cluster membership.** Two machines may both manifest `{base, freespin_v2}` — that's the shared path. Two machines manifesting `{base, freespin_v2, top_dollar_v1}` is a different shared path, etc.
3. **RTP integrity (constraint S) is enforced equally for all machines.** A "vanilla" machine that turns out to have a misattribution doesn't get grace; it gets the same error as M274 would.
4. **Phase 2 forcing function tests not just the 12 known-complex machines, but also the framework's ability to absorb future "graduated" complex machines** without architectural change. Add a representative example of "machine X declared vanilla manifest, RTP integrity check fails, we add a per-machine plugin Y, X re-onboards — works without changing the framework".
5. **04 v2 should explicitly disclaim the "84% safely clustered" framing.** State that no machine is presumed safe; the architecture treats every machine as potentially unique; sharing is opt-in via manifest.

---

## §2 Summary table — Designer v2 must integrate

| # | Update | Type | Impact on v2 |
|---|---|---|---|
| 1 | Reframe blast reduction headline | Presentation | Low — replace one section + add per-class table |
| 2 | Clean-break migration; no historical report preservation | Simplification | Medium — large simplification of Phase 3 + downstream |
| 3 | 12 known-complex machines → Phase 2 forcing function | Phase reordering | Medium — Phase 2 + Phase 5 redesign |
| 4 | RTP integrity hard constraint (constraint S) | New constraint | Medium-high — adds enforcement mechanism + UX |
| 5 | Architectural philosophy: every machine potentially unique | Philosophy shift | High — removes "default cluster" tier; rewrites §3/§5/§6 of v1 |

---

## §3 Out of scope for Designer v2 (still)

Same as 00_brief.md §7. In particular:

- Implementation (still next-session work after Wave 3 v2 approves)
- Aesthetic / UX redesign
- Upstream rawdata format changes
- Re-onboarding existing per-machine specs (slot_designer/machines/<M>/spec.json byte-locked per universal rule)
- The 80% spin_type_category threshold (separate concern, reverted, stays out)

---

## §4 Output expectations

- **`04_architecture_proposal_v2.md`** — full proposal addressing all 5 updates + all 11 Critic must-resolve + 4 Validator gaps + 5 pre-Phase-1 blockers from 05/06.
- Should not be a "patch" of v1; rewrite where needed for coherence (especially §3/§5 in v1 which had the now-rejected "84% clean cluster" framing).
- Cite Wave 1 evidence per role invariant.
- Aim 800-1500 lines.
- Single rewrite — do not iterate within Designer v2; Wave 3 v2 will provide the next critique.

---

## §5 Cross-references

- Original brief: `session_artifacts/_arch/00_brief.md` (still valid for everything not superseded)
- Wave 1 artifacts: `01_pipeline_map.md`, `02_taxonomy.md`, `03_coupling_audit.md`
- v1 proposal: `04_architecture_proposal.md`
- v1 critique: `05_critique.md` — Designer v2 must address all 11 must-resolves
- v1 validation: `06_validation.md` — Designer v2 must address all 4 spec gaps
- v1 decision summary: `07_decision.md` — context for why v2 is happening
- Memory: `feedback_invariant_with_fallback_hides_drift.md`, `feedback_no_silent_swallow.md`, `feedback_arch_team_process.md`
