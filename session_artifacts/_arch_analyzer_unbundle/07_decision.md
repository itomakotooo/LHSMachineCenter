# 07 — Coordinator Decision Summary

> **Date**: 2026-05-25
> **Coordinator**: main session
> **Status**: arch-* team complete; awaiting user go/no-go on impl-* team
> **Recommendation**: PROCEED to impl-* team with `04_v3` as authoritative spec

---

## §1 Process recap

Per `docs/ARCH_TEAM_PROCESS.md`. M275 driving case for analyzer plugin system real landing + 8 gap closure.

| Wave | Agent | Verdict | Output |
|---|---|---|---|
| W1 | arch-mapper | facts | `01_pipeline_map.md` |
| W1 | arch-taxonomist | facts (M275 in B_BCM_FREESPIN_WHEEL = 107 entities) | `02_taxonomy.md` |
| W1 | arch-coupling-auditor | facts (3 biggest blast radius surfaces) | `03_coupling_audit.md` |
| W2 v1 | arch-designer | Alternative 2 (Mechanism Registry + Protocol v2 + Phased Carve C1-C6) | `04_architecture_proposal.md` |
| W3 v1 | arch-critic | APPROVE-WITH-REVISIONS | `05_critique.md` |
| W3 v1 | arch-validator | APPROVE-WITH-REVISIONS (R1 freespin, R2 scope) | `06_validation.md` |
| W2 v2 | arch-designer | 24 revisions; PipelineContext + Kahn topo sort + ordering contract | `04_architecture_proposal_v2.md` |
| W3 v2 | arch-critic | APPROVE-WITH-MINOR-REVISIONS (10 / 5 / 2; 2 new MR) | `05_critique_v2.md` |
| W3 v2 | arch-validator | REJECT (NB1 M11 jackpot regression — surgical fix only) | `06_validation_v2.md` |
| W2 v3 | arch-designer | 4 surgical fixes; impl-ready high confidence | `04_architecture_proposal_v3.md` |

**W3 v3 skipped**: validator + critic v2 explicitly specified 4 exact fixes as concrete deltas with no design judgment remaining; v3 designer summary confirms all 4 landed without expanding scope. Re-running W3 v3 would be ceremony — explicitly accepted as coordinator decision.

Total round-trip: 1 brief + 4 designer iterations + 4 reviewer passes = 10 agent invocations.

---

## §2 What the proposal actually does

### 2.1 Plugin Protocol v2 (real Pattern B)

- `extract(parse_state, chunk_dict) → dict` — wired (today's lifecycle never calls extract; only emit)
- `reduce(prev_acc, this_acc) → Any` — wired
- `emit(final_acc, summary, ctx: PipelineContext) → None` — **3rd parameter added** to carry raw accumulators

`PipelineContext` (frozen dataclass, fields):
- `effective_bet_for_rtp: float`
- `total_spins: int`
- `total_paid_sessions: int`
- `total_paid_spins: int`
- `clamp_pending_robots_total: int`
- `robots_with_pending_cycle: int`
- `mechanism_registry: MechanismRegistry`  (built between F1 emit and others)
- `manifest: dict[str, Any]`  (resolved per-mode manifest — v3 added for shape/cols enrichment)

`DECLARED_DEPS: ClassVar[tuple[str, ...]]` = explicit dependency declaration, replacing the hidden `_bankruptcy_rows` temp-key stash pattern. Kahn's algorithm topo sort orders plugin emit; cycle raises `PluginCyclicDependencyError`, missing dep raises `PluginMissingDependencyError`. Both surface via `summary["analyzer_init_error"]` + stderr ERROR + non-zero rc + console UI banner.

### 2.2 Mechanism Registry (single source of truth)

- Placed **outside `core/`** (file: `fresh_slotlab/analyzer/mechanism_registry.py`) so changes to it do NOT trigger fleet-wide base-hash invalidation
- Built post-merge, between Phase B (F1 inline emit) and Phase D (plugin emit loop)
- Three detection tiers:
  - Tier 1: manifest declared (`manifest.mechanism_overrides`)
  - Tier 2: aggregated derived signals (e.g. `bonus_chain_dynamics.bonus_round_count > 0` → freespin present; **NOT** `behavior_name=free` per v1 validator R1)
  - Tier 3: raw evidence (e.g. PIDs ≥ 10000 in payout_id_win OR PIDs in parser-accumulated `jackpot_ids_seen` from raw `JackpotIds` field — UNION per v3 NB1 fix)
- Sidecar persistence — operator can audit machine's "mechanism portrait" without re-running analyzer
- Consumed by `machine_mechanics` plugin (which replaces today's contradicting independent detectors for gap #1 + #2)

### 2.3 Phased Plugin Carve C1-C6

| Phase | Carve | Acceptance gate |
|---|---|---|
| C1 | Wire `extract()` + `emit(ctx)` 3rd param; add PipelineContext construction; topo sort + dep classes; BankruptcySim signature byte-identical verification on M14 | M14 cached rebuild byte-identical pre/post |
| C2 | F3 `payouts_by_spin_type` Pattern A → Pattern B | M275 cached rebuild produces same RTP/CI |
| C3 | F3 enrichment: shape / cols / paylines / notes (user's gap #7+#8) | M275 sees new fields populated; old reports gracefully render `null` |
| C4 | `machine_mechanics` plugin replaces independent jackpot/free_spin detectors (gap #1+#2 closure) | M275 jackpot.applicable=true; M11 jackpot.applicable still true (no regression) |
| C5 | `upstream_feature_breakdown` + `collect_mechanic` carve | M275 BCM cycle data preserved; M275 estimated_correction_pp resolves (gap #6) |
| C6 | `bonus_chain_dynamics` (F6) carve + scatter-trigger marker concept (gap #3) | M275 666 PID classified `trigger_marker`; ST=140 dom_st no longer assigned |

Each phase = one commit via impl-* team. Acceptance criteria spec'd per phase including the `ALL_FEATURES` 3-import-site enumeration trap (PIA × 2 + versioning + validate_manifests).

### 2.4 Gap closure scorecard

| Gap | Owner | Closure mechanism |
|---|---|---|
| #1 jackpot.applicable=false | machine_mechanics plugin (C4) | Mechanism Registry Tier-3 UNION |
| #2 free_spin.applicable=false | machine_mechanics plugin (C4) | Mechanism Registry Tier-2 (chain_count > 0) |
| #3 pid 666 not marked trigger | bonus_chain_dynamics plugin (C6) | New trigger_marker semantic + payout_id_panel update |
| #4 multiplier wild × not interpreted | **explicitly deferred** (§14.4) | Separate proposal; gap remains for M275 + 18 other B_BCM_WHEEL machines |
| #5 payout_groups_top20 noise on all-zero | payout_groups carve (C2/C3) | Empty list when all-zero detected (frontend renders graceful) |
| #6 estimated_correction_pp = 0.0 | collect_mechanic plugin (C5) | Pending W3 confirmation; may already be mathematically correct (validator suggested formula is sound; gap may be perception not bug) |
| #7 payouts_by_spin_type missing shape/cols/paylines/notes | F3 enrichment (C3) | New fields via ctx.manifest + parser PayoutByPayline data |
| #8 payout_ids_top20 missing same | F3 enrichment (C3) | Same mechanism |

**7 of 8 closed by architecture; gap #4 explicitly deferred; gap #6 pending operator clarification.**

### 2.5 Hash composition

- No algorithm change to `compute_effective_analyzer_version`
- New optional `mechanism_overrides` manifest field included via hash component when present (zero impact when absent — most manifests won't have it)
- `mechanism_registry.py` placement outside `core/` is deliberate: changes to mechanism detection logic don't ripple to fleet-wide base-hash; instead they ripple via the plugins that consume the registry (`machine_mechanics` mostly)

### 2.6 Migration / rollout

- Phased C1-C6, one commit per phase
- Each phase invalidates a SUBSET of machines (only those declaring the affected plugin) — not full 393 fleet
- Backward-compat: all 336 existing reports remain readable; missing new fields render as `null` in frontend
- Operator runs once-per-phase batch rebuild via FleetRefreshManager UI (existing affordance, no new tool)
- Existing pre-v2 `analyzer_version` legacy field kept for backward-compat

### 2.7 "Zero-code new machine" property — when does it hold post-this-work

| Archetype | Count | Post-this-work property |
|---|---|---|
| A_VANILLA | 53 | ✅ Already holds; no regression |
| B_BCM_FREESPIN_WHEEL (M275 family) | 107 | ✅ Holds for jackpot detection / freespin detection / shape enrichment; ⚠️ multiplier wild values still need manual config (gap #4 deferred) |
| Other B_* combos | ~57 | ✅ Holds for the mechanism types covered by Mechanism Registry tiers |
| C_* single-mechanic | ~132 | ✅ Holds for the mechanism types covered |
| D_* outliers | ~7 | ⚠️ Case-by-case; some still Case-C requiring custom plugin |

**Total** ≈ 200/256 base machines (≈ 78%) cleanly achieve property; remaining residual is multiplier wild (~30 machines) + named outliers.

---

## §3 What user must decide

### Decision 1: PROCEED to impl-* team with v3 spec?

**Recommended answer**: YES.

Justification: both reviewers say core architecture is sound; v3 closes all surgically-specified gaps from W3 v2; no design judgment remaining; impl-implementer/tester/verifier/critic team can execute Phase C1 immediately.

If NO: alternative is to start over with different design (not recommended — Alternatives 1 and 3 from v1 §2 explored, both rejected by designer).

### Decision 2: Gap #6 (estimated_correction_pp = 0.0)

W2 designer flagged: maybe a formula bug, maybe mathematically correct. W3 v2 validator analysis suggests it might be correct (M275's `robots_with_pending_cycle = 0` so formula produces 0.0 legitimately).

**User clarification needed**: when M275 shows `clamp_warning.pending_share_of_paid_spins: 0.8` (80% of paid spins didn't reach cycle completion before chunk_spin_times ran out), and `bonus_cycle_correction.estimated_correction_pp: 0.0`, which interpretation matches operator intent:

- (a) **Bug — should estimate correction from pending share** (80% × avg payout × ratio). Then C5 implements the formula.
- (b) **Correct — only completed-pending cycles count, not chunk-truncated**. Then gap #6 is removed from scope and C5 only handles plumbing.

### Decision 3: Gap #4 (multiplier wild ×2/×5/×10 inference resume)

Currently paused fleet-wide (2 unresolved bugs from 2026-04 per `memory project_paytable_inference_paused.md`).

This proposal **explicitly defers** (§14.4). M275 + other B_BCM_WHEEL machines still won't have multiplier values surfaced post-this-work.

**Options**:
- (a) Accept deferral — multiplier inference resume is separate proposal/effort
- (b) Add as Phase C7 to this proposal — but original 2 bugs need investigation first; would extend timeline 1-2 weeks
- (c) Add manifest declaration field (operator-filled, no inference) — partial solution

### Decision 4: When to land C1-C6 (timing)

C1 alone is structurally large (extract() wiring + PipelineContext + topo sort + dep classes + BankruptcySim verification). C2-C6 are smaller.

**Options**:
- (a) Land C1 → land C2 → ... sequentially, one commit per phase, full impl-* team loop each (≈6 weeks total at 1 phase/week)
- (b) Land C1 + C2 together as foundation, then C3-C6 incrementally
- (c) Defer C5+C6 indefinitely (gap #1+#2+#3 covered by C1-C4)

---

## §4 Open questions surviving v3

From `04_v3 §16`:
- **SQ1**: PipelineContext field completeness — designer admits Block F5's 440 lines may reveal accumulators not yet in PipelineContext. v3 validator confirmed primary fields cover M275; M11 walk surfaced no additions. Flagged as implementation-time discovery with extension protocol (just add field + bump SCHEMA_VERSION).
- **SQ2**: Topo-sort tie-breaking — non-functional concern; alphabetical OK for now
- **SQ3**: Gap #6 verdict — needs user decision per Decision 2 above
- **SQ4**: M11-class fleet scale (how many machines use raw `JackpotIds` field) — informational only; surgical fix works regardless

None block impl phase start.

---

## §5 Coordinator recommendation

**PROCEED TO IMPL-* TEAM PHASE C1.**

Brief for impl phase:
- Authoritative spec: `04_architecture_proposal_v3.md` (read alongside §0 revision logs to understand v1→v2→v3 trail)
- Phase scope: C1 only (one commit)
- Acceptance criteria: §15.5 C1 row (including new BankruptcySim byte-identical verification on M14)
- Pre-Phase-C2 gate: M14 cached rebuild diff must be byte-identical post-C1; if not, fix before C2 begins
- 3-import-site enumeration is a hard acceptance criterion for every new plugin added in C2-C6

Pending user decisions 2-4 above can be made at the end of C1 (before C5 + C6) without blocking C1.

---

## §6 User decisions (locked 2026-05-25 in session)

| # | Decision | User answer |
|---|---|---|
| 1 | Go/No-Go on impl-* Phase C1 with v3 spec | ✅ **GO** — proceed to impl-* team C1 |
| 2 | Gap #6 (estimated_correction_pp = 0.0) interpretation | ✅ **Mathematically correct** — whether cycle completes depends on chunk_spin_times design. C5 acceptance criterion gets a follow-up addition: clamp_warning shall explicitly suggest `chunk_spin_times >= detected_cycle_length × avg_spins_per_collect × safety_factor` so the operator knows how to size next sample. Per-machine cycle length varies, so the suggestion is computed per (machine, mode). |
| 3 | Gap #4 (multiplier wild) scope | ✅ **Add to proposal as Phase C3.5** — raw evidence shows M275 wild multiplier is "wild symbol with embedded multiplier value" (wild2x / wild5x / wild10x physically in col 1, multiplies the line's base win by N when the line passes through that cell). NOT free-game cumulative multiplier — ReMarks across all 9090 freespin rounds carries only `Freespin N;` plain counters, no multiplier annotation. This mechanism is NOT what the 2026-04 paused paytable inference was about (that was about base paytable per-symbol n-of-a-kind values). Phase C3.5 implementation is simple: parse symbol name suffix → extract multiplier value → compute RTP contribution from col-1 wildNx hit rate × line base-win uplift. Owner plugin: `multiplier_wild` (new) or extension of `payouts_by_spin_type` (decide in C3.5 brief). |
| 4 | C1-C6 cadence | ✅ **One phase per commit, full impl-* loop per phase** — no batching |

---

## §7 Revised phase plan (post-user decisions)

| Phase | Carve | Gap closures | New acceptance criteria |
|---|---|---|---|
| C1 | extract() wiring + PipelineContext + topo sort + dep classes + BankruptcySim byte-identical verification | — (plumbing) | M14 cached rebuild byte-identical pre/post |
| C2 | F3 payouts_by_spin_type Pattern A → Pattern B | (foundation for C3) | M275 RTP/CI byte-identical |
| C3 | F3 enrichment: shape / cols / paylines / notes | #7 #8 | M275 sees new fields; old reports render null gracefully |
| **C3.5 (NEW)** | **multiplier_wild plugin OR payouts_by_spin_type extension** | **#4** | **M275 sees wild2x/wild5x/wild10x RTP contribution surfaced (~6-10% of paid RTP estimated); M14 (no multiplier wilds) unaffected** |
| C4 | machine_mechanics plugin replaces independent detectors; Mechanism Registry built | #1 #2 | M275 jackpot.applicable=true; M11 jackpot.applicable still true (no regression via JackpotIds raw-field union) |
| C5 | upstream_feature_breakdown + collect_mechanic carve + chunk_spin_times sizing suggestion | #5 #6 | M275 BCM data preserved; clamp_warning carries chunk_spin_times recommendation |
| C6 | bonus_chain_dynamics carve + scatter_trigger_marker semantic | #3 | M275 666 PID classified trigger_marker |

7 phases total (C3.5 added). All 8 gaps now in scope; no deferrals.

Phase C1 starts now via impl-* team.
