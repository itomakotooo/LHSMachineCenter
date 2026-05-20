# Architecture — As Built (post-implementation rewrite)

> Supersedes `04_architecture_proposal_v5.md` on the points enumerated below. The v5 proposal stays on disk as the design-time intent; this document captures what shipped, what was rescoped, and where the gap is.
>
> Written 2026-05-20 after one extended implementation pass. Authoritative on operator-visible behavior. The original proposal stays authoritative on hash composition and validation rule numbering (both unchanged).

---

## §1 Scope of this rewrite

The user asked for an "as-built" rewrite after observing that the implementation pass surfaced material gaps and reframings:

1. The integrity check ("4-layer gate") was originally designed to flip from soft warning to hard error per machine. **That flip is dropped.** The check stays a soft hint forever; operators see results in the UI but the analyzer never raises on a layer failure.
2. The "9 cluster-shared features" line item is dropped (no enumeration was ever produced; the architecture's split between universal / cluster-shared / bespoke turned out to be premature). What shipped is 4 universal features (fully wired) and a per-machine bespoke escape hatch (deferred until a real bespoke need surfaces).
3. The "12 forcing-function machines" list was a placeholder. The actual hard-case roster is revised below per real-world failure history; the count is not 12.
4. The "console_diagnostic_complete" flag, originally a strict-mode trigger, becomes a label-only field describing whether the manifest has been per-machine reviewed.
5. Day-1 verification (item 0 in v5 §6.3.3) was originally a gating ceremony with a 10-minute upfront cost. It moves into operators' normal report-review workflow — i.e. operators look at integrity-check hints on real reports rather than running a fleet-wide pre-flight.

The v5 proposal's plugin model, manifest schema, hash composition algorithm, and 11 validation rules are unchanged.

---

## §2 What shipped vs what was proposed

### Phase 1 — Foundation
All 12 v5 §6.1 deliverables shipped. No deviation.

### Phase 2 — Slice the analyzer + integrity check code

| v5 §6.2 deliverable | As built |
|---|---|
| 1. Carve `core/` (4 files) | Shipped: parser / aggregator / writer / base_pipeline. 5th utility file `_utils.py` added during P2-B2 to break a circular import. |
| 2. Carve 4 universal features | Shipped. Pattern A (scaffolding) for `payouts_by_spin_type`, `reel_marginal_by_spin_type`, `multiplier_profile`. Pattern B (logic-extracted) for `bankruptcy_simulation`. |
| 3. **Carve 9 cluster-shared features** | **Dropped.** No enumeration ever existed. The plugin surface accommodates cluster-shared features; nothing has been promoted into the registry yet. Will revisit when a concrete cluster has a feature whose code is genuinely shared across ≥2 machines AND is not already in the analyzer core. |
| 4. Carve 12 forcing-function bespoke features | Deferred per §3 below. The 12-machine roster is revised. |
| 5. Build `rtp_integrity.py` (4 layers, warn-only) | Shipped. Wired into PIA so every report carries the gate result. Warn-only globally per user direction 2026-05-20. |
| 6. Demonstrate Example 6 on M250 | Deferred. Requires per-machine M250 spec data. |
| 7. `analyzer/versioning.py` | Shipped. `compute_base_analyzer_version` (hashes `core/*.py`) + `compute_effective_version_for_machine(machine_id, mode)`. |
| 8. `analyzer/feature_registry.py` | Shipped. |
| 9. Per-cluster regression tests | Deferred. Bundled with §3 when the bespoke roster firms up. |

### Phase 3 — Per-machine manifests + wiring

| v5 §6.3.3 item | As built |
|---|---|
| 0. Day-1 verification of ~46 candidates against rawdata | **Dropped as a separate ceremony.** Folded into the operator's normal report-review workflow per §1 point 5. |
| 1. Write 421 manifests | Shipped: 419 files (393 fleet machines + 26 synthesized variant-parent templates; the architecture's 421 was approximate). |
| 2. `manifest_loader.py` (cascade + per-mode + completeness) | Shipped. 11 validation rules + 99 unit tests. |
| 3. Wire `compute_effective_analyzer_version` to consult manifest | Shipped. |
| 4. Update analyzer + backend write sites | Shipped. Legacy `analyzer_version` stays in the report alongside the new `effective_analyzer_version`; old reports continue to work. |
| 5. Update report-staleness API to use effective version | Shipped on backend; frontend display follows in Phase 4. |
| 6. Add DB column for effective version | Shipped. Idempotent `ALTER TABLE ADD COLUMN` matching existing pattern; no migration needed for the single-machine local SQLite deployment. |
| 7. Frontend reads manifest-driven feature list | Pending (paired with Phase 4 below). |
| 8. `scripts/validate_manifests.py` | Shipped. Fleet validator CLI; 419/419 clean today. |
| 9. `scripts/manifest_lint.py` | Shipped. Soft-rule linter; L1 (config-not-reviewed) + L2 (override metadata) + L3 (override age). 182 L1 findings today (the per-machine review backlog). |

### Phase 4 — Frontend renderer registry + schema-version contract

Not started. Substantial work on the operator-facing web UI. Pairs with Phase 3 item 7 — both touch the same frontend file. Sequenced for the next session.

### Phase 5 — Policy flip

**Dropped per user direction 2026-05-20.** The integrity check stays a soft hint forever. The original v5 design (manifest's `console_diagnostic_complete: true` → hard-error policy) does not ship.

The `console_diagnostic_complete` field is repurposed as a label: it now means "this manifest has been per-machine reviewed and the integrity contract reflects the actual machine, not bootstrap defaults". The operator UI uses it to render integrity-check results from reviewed manifests with full visual weight; results from unreviewed manifests (the `_generator_notes.config_not_reviewed: true` set, 182 machines today) render as soft-confidence hints.

### Phase 6 — Optional consolidation

No deviation from v5.

---

## §3 The real hard-case machine roster (revises v5 §6.2 deliverable 4 / §6.3.1)

The v5 proposal listed "12 forcing-function machines: M21/M260/M268/M279/M274/M113/M11/M250/M108/M65/M67/M120." That list was a placeholder. The actual hard-case set, based on documented failure history in this repo's memories + the implementation pass's observations, is:

### Tier 1 — Documented active issues (priority for per-machine onboarding)

| Machine | Why it's hard |
|---|---|
| **M250** | Sweep of 117 cached pairs surfaced 100% of its win attributed to a "didn't recognize" bucket. The integrity check should fire loudly here. |
| **M260** / **M264** / **M268** | Same sweep: 70-90% of win in the "didn't recognize" bucket. BCM (bonus-cycle multiplier) routing inference is incomplete for this family. |
| **M279** | Took four iterations of analyzer fixes (2026-04 BCM peak-detection rework) before its reports lined up. Most-recently-painful machine. |
| **M99** | Lock-symbol respin machine; deduplication of a specific spin-type pair (ST=97 + ST=98) is open and not fixed. Reports today double-count those rounds. |
| **M274** | Primary BCM baseline (the rawdata sweep used it as ground truth). Must keep working. Validates that the new architecture preserves what was already correct. |

### Tier 2 — Structural outliers (need explicit manifest fixes)

| Machine | Why it's hard |
|---|---|
| **M99** | Paid spin type is 96, not 1. Bootstrap default is wrong for this machine. |
| **M272** | Paid spin type is 140, not 1. Same. |
| **M15** | Canonical trigger-session machine (Type-1 pattern). The integrity check's "rawdata cross-check" layer is structurally skipped per architecture; manifest must declare this. |
| **M12** / **M32** / **M90** / **M132** / **M206** / **M39** / **M86** / **M116** / **M210** / **M123** | Type-1 trigger-session family. Same structural skip as M15. |
| **M273** / **M201** / **M257** | Type-2 trigger-session family (different re-attribution rule). Same structural skip. |
| **M120** | Jackpot machine — pay-id 666 attribution is special. |
| **M14** | The operator's testing baseline per memory `user_testing_machine.md`. Not "hard" in the sense of bugs — but anything that breaks here breaks operator confidence in the whole system. Effectively a tripwire. |

### Tier 3 — Originally-listed but no documented issue today

`M21 / M113 / M11 / M108 / M65 / M67` — these were in the v5 list but I found no specific failure history. They may have been preemptively listed because they share structural features with Tier 1 machines, or they may have been arbitrary. Recommended action: skip until they actually surface in operator-facing integrity-check hints, then add per-machine.

### Why this list is open-ended

The hard-case roster is not a fixed-size set. As operators flip through reports and see soft-hint integrity failures, new machines surface. The `manifest_lint.py L1` count (config_not_reviewed: 182) is the upper bound on per-machine work. Working priority: machines with active integrity-check hints → Tier 1 → Tier 2 → the rest.

---

## §4 What the operator actually sees today

After this implementation pass + the operator-facing web UI work in the next session:

1. **Verified machines** (45 SC-Vanilla today; grows as reviewers confirm per-machine manifests): reports render with full visual weight. Integrity-check hints are presented as authoritative.
2. **Unreviewed machines** (182 today; shrinks as reviewers confirm manifests): reports render normally but integrity-check hints render with reduced visual weight ("manifest uses bootstrap defaults; treat with caution").
3. **Variants** (166): inherit the parent's verification state.
4. **Templates** (26 synthesized parents that variants point at): not surfaced in the operator UI; backend-only.

The integrity check **never blocks report generation** under any condition. Operator decisions are informed by hints, not gated by them.

---

## §5 Open work, sequenced

1. **Operator web UI** — surface the integrity-check field per §4 above; render `effective_analyzer_version` for staleness display; manifest-driven feature filtering. Pairs with the renderer-registry refactor that was originally Phase 4.
2. **Tier 1 / Tier 2 per-machine manifest reviews** — one session per cluster (BCM family / trigger-session family / outliers).
3. **Example 6 M250 walkthrough** — once M250 is in Tier 1 onboarding.
4. **Cluster-shared feature plugins** — when (and if) a concrete shared-code need surfaces.

---

## §6 Hash composition + manifest schema (UNCHANGED from v5)

No changes to:
- `compute_base_analyzer_version` algorithm (§4.1)
- `compute_effective_analyzer_version` algorithm (§4.1)
- Manifest schema fields (§5.5)
- 11 validation rules (§5.6)
- Integrity check layer semantics (§9.1-9.4)
- Variant cascade (§5.5.5)

These are stable and tested. The reframings above are about scope and operator semantics; the engine surface that callers use is unchanged.
