# Auto-Inspect Sweep — Fleet Taxonomy
> Produced 2026-05-26. Input sources: configs/machines.json (422 entries), configs/machine_modes.json (253 entries), configs/machine_selector_types.json, configs/machine_round_win_rules.json, session_artifacts/_arch/09_architecture_as_built.md.

---

## 1. Scope & Inventory

**Fleet size:** 422 machines (422 rows in machines.json).

**Composition (from machines.json):**
- Non-variant standalone machines: 230
- Underlying parents (machines that also have variant children): 26
- Variants (machine id contains `$`): 166

**Mode coverage:** Every machine in machines.json carries `modes: [1, 2, 5, 7]`. The machine_modes.json file covers 253 of the 256 non-variant machines; M278, M280, M281 are absent from machine_modes.json but carry `modes: [1,2,5,7]` in machines.json directly. No machine in the fleet has fewer than 4 modes.

**Total cells in scope for the sweep:** 422 machines × 4 modes = **1,688 cells**.

**Sampling strategy:** Full enumeration. At 422 machines the fleet is below the 30-machine threshold that would require statistical sampling; every machine is classified directly from its machines.json entry and corroborating config files.

---

## 2. Clustering Axes

Five axes used, each independently measurable from config files:

| Axis | Measurable property | Source |
|---|---|---|
| A — Entity type | presence of `$` in machine id; whether machine id is also a variant parent | machines.json |
| B — Trigger-session family | machine id in documented Type-1 or Type-2 roster; variant's base in same roster | machine_round_win_rules.json doc + 09_architecture_as_built.md §3 Tier 2 |
| C — Hard-case tier | machine id in Tier 1 or Tier 2 documented failure roster | 09_architecture_as_built.md §3 |
| D — Mechanism cluster | presence of class-name prefixes: BuffCollection, Wheel, ReSpin, LockSymbol, Move, Freespin | machines.json logicClassNames |
| E — Shared binary group | identical codeSummaryMd5 across machines | machines.json |

---

## 3. Per-Axis Clusters

### Axis A — Entity Type

| Cluster | Machines | Cells |
|---|---|---|
| Non-variant standalone | 230 | 920 |
| Underlying parent (has variant children) | 26 | 104 |
| Variant | 166 | 664 |
| **Total** | **422** | **1,688** |

The 26 underlying parents are: M6, M12, M15, M32, M39, M86, M90, M102, M116, M123, M132, M187, M188, M198, M201, M203, M204, M206, M209, M210, M216, M219, M247, M257, M261, M273.

All 26 have `upstream_key` equal to their plain machine id (e.g. M273 upstream_key=M273), distinct from their variants' upstream_keys (e.g. M273$0$, M273$1$1-2-3, etc).

### Axis B — Trigger-Session Family

| Cluster | Underlying machines | Variant machines | Total machines | Total cells |
|---|---|---|---|---|
| Standard (no trigger-session mechanic) | 242 | 28 | 270 | 1,080 |
| Type 1 (TopDollar / QuickDollar / DancingDrum / HoppyHunting / ChristmasSimple / ValentineSimple) | 11 | 41 | 52 | 208 |
| Type 2 (CommonSelector / WheelSelector — M201/M257/M273 family) | 3 | 97 | 100 | 400 |
| **Total** | **256** | **166** | **422** | **1,688** |

**Type 1 underlying machines (11):** M12, M15, M32, M90, M132, M206, M39, M86, M116, M210, M123.

**Type 1 variant counts per parent:** M12 (3), M15 (3), M32 (3), M90 (3), M132 (3), M206 (3), M39 (5), M86 (5), M116 (3), M210 (3), M123 (7). Total: 41 variants.

**Type 2 underlying machines (3):** M201, M257, M273.

**Type 2 variant counts per parent:** M201 (8), M257 (4), M273 (85). Total: 97 variants.

M273 dominates Type 2: 85 variants representing all C(9,3)=84 three-position wheel combinations plus the $0$ base, covering 340 of the 400 Type-2 cells.

### Axis C — Hard-Case Tier

| Cluster | Machines | Cells | Basis |
|---|---|---|---|
| Standard (no documented issue) | 408 | 1,632 | no entry in failure history |
| Tier 1 — active issues | 7 | 28 | 09_architecture_as_built.md §3 Tier 1 |
| Tier 2 — structural outliers (trigger-session family; already counted in Axis B) | 14 | 56 | 09_as_built §3 Tier 2 |
| Tier 2 — non-standard paid spin type | 2 | 8 | as_built §3 Tier 2 |
| Tier 2 — jackpot special | 1 | 4 | as_built §3 Tier 2 |
| BCM moderate leakage (35% unattributed win in sweep) | 2 | 8 | machine_round_win_rules.json doc |
| New / uncharted (BCM, not in machine_modes.json) | 3 | 12 | machines.json — absent from machine_modes.json |

Note: the 14 Tier 2 trigger-session machines are the same 14 as the Type-1 and Type-2 underlyings in Axis B. Their variants inherit the trigger-session classification but do not separately appear in the hard-case tier count (variants share the underlying's challenge, not additional independent issues).

**Tier 1 machines (7):** M250, M260, M264, M268, M279, M99, M274.

- M250: 100% of win attributed to unrecognized bucket in BCM sweep (machine_round_win_rules.json doc). BCM+WHEEL+FREESPIN mechanism.
- M260, M264: 70-90% of win in unrecognized bucket. BCM+WHEEL+FREESPIN mechanism.
- M268: 70-90% of win in unrecognized bucket. BCM+RESPIN+LOCK mechanism.
- M279: four analyzer iterations required to converge (BCM peak-detection rework 2026-04). BCM+WHEEL+MOVE mechanism.
- M99: open sub-round dedup bug (ST=97+ST=98 pair double-counts). Paid spin type is 96 (not 1). WHEEL+RESPIN+LOCK mechanism.
- M274: primary BCM baseline; must stay working to validate that architecture changes preserve existing correct output. BCM+WHEEL mechanism.

**Tier 2 spintype outliers (2):** M99 (paid ST=96, already in Tier 1), M272 (paid ST=140).

**Tier 2 jackpot special (1):** M120 (pay-id 666 attribution requires special handling).

**BCM moderate (2):** M147 (35% unattributed in sweep), M163 (35% unattributed in sweep).

**New / uncharted BCM (3):** M278, M280, M281. All three carry BuffCollection* classes, are absent from machine_modes.json (likely added after the last machine_modes.json update), and have no documented sweep history. M278 and M257 share a generator class (M257NormalGenerator), suggesting M278 is structurally related to the M257/Type-2 family. M280 and M281 also carry BuffCollection classes and appear in neither the trigger-session family nor the documented hard-case list, making their convergence behavior unknown.

### Axis D — Mechanism Cluster (non-variant machines, 256 total)

| Mechanism signature | Count | Representative machines |
|---|---|---|
| Normal only (no freespin) | 56 | M1, M2, M13, M14, M16 … (pure normal spin machines) |
| ReSpin only | 37 | M206 (trigger-type1), M10, M23, M26 … |
| Normal + Freespin | 35 | M3, M5, M7, M8, M9 … |
| Wheel only (no BCM) | 20 | M32 (trigger-type1), M102, M187, M198 … |
| BCM + Wheel + Freespin | 14 | M250, M260, M264 (Tier 1), M108, M168 … |
| ReSpin + Freespin | 10 | M201 (trigger-type2), M43, M44 … |
| Wheel + Freespin (no BCM) | 10 | M86, M123, M203, M204 … |
| BCM + Freespin (no Wheel) | 10 | M152, M153, M168 … |
| Lock + Freespin | 7 | M100, M114, M183, M193, M208, M222, M240 |
| BCM + Wheel (no Freespin) | 6 | M147, M192, M236, M267, M270, M274 |
| BCM + ReSpin + Wheel | 6 | M163, M227, M228, M232, M242, M245 |
| ReSpin + Lock | 5 | M10, M103, M104, M131, M23 |
| Move only | 4 | M26, M51, M140, M149 |
| BCM + ReSpin | 4 | M238, M269, M277, M278 |
| Lock + ReSpin + Wheel | 3 | M41 (?), M47, M99 |
| All other signatures | 29 | various single-machine or 2-machine combinations |

The largest single-signature cluster (Normal only, 56 machines) represents 21.9% of non-variant machines. BCM appears in 57 of 256 non-variant machines (22.3%).

### Axis E — Shared Binary Group (codeSummaryMd5)

| Group | Machines sharing binary | Cells |
|---|---|---|
| M273 family (c2a4e3be...) | 86 (M273 parent + 85 variants) | 344 |
| Standard large group (f7a4cefd...) | 45 cross-parent non-variants | 180 |
| M123 variants (58418d37...) | 8 (7 variants + parent) | 32 |
| M201 variants (0ab0a6df...) | 8 (8 variants + parent-shares code) | 32 |
| Singleton binary groups | 149 | 596 |
| All other multi-machine groups | 134 | 504 |

The 45-machine standard large group shares code binary f7a4cefd... and includes: M1, M2, M4, M8, M9, M13, M14, M16, M17, M19, M34, M35, M37, M38, M57, M59, M63, M64, M66, M70, M71, M72, M73, M74, M78, M84, M101, M105, M127, M135, M137, M139, M142, M144, M145, M154, M155, M157, M160, M161, M162, M169, M170, M172, M173. All 45 have distinct configSummaryMd5 values (different game configurations from same binary).

---

## 4. Cross-Axis Similarity Matrix

The table shows how the 7 named hard-case machines and key clusters co-locate across all 5 axes. "same" means they share that cluster with the majority; "outlier" means they fall in a minority cluster.

| Machine(s) | Axis A (Entity) | Axis B (Trigger) | Axis C (Hard case) | Axis D (Mechanism) | Axis E (Binary) |
|---|---|---|---|---|---|
| Standard standalone (228) | Non-variant | Standard | None | Mixed | Varies |
| M273 + 85 variants (86) | Underlying + variants | Type 2 | Tier 2 (underlying) | BCM+WHEEL+LOCK+FREESPIN | Unique group (c2a4e3be, 86 machines) |
| M201 + 8 variants (9) | Underlying + variants | Type 2 | Tier 2 (underlying) | RESPIN+FREESPIN (parent) | Unique group (0ab0a6df, 8 machines) |
| M257 + 4 variants (5) | Underlying + variants | Type 2 | Tier 2 (underlying) | BCM+RESPIN+LOCK+FREESPIN | Unique group (ebb64d1a, 4 machines) |
| M12/M15/M90/M132/M206 (TopDollar) | Underlying | Type 1 | Tier 2 | NORMAL or RESPIN | Various |
| M32/M39/M86/M116/M123/M210 | Underlying | Type 1 | Tier 2 | WHEEL or FREESPIN | Various |
| M250, M260, M264 | Non-variant | Standard | Tier 1 | BCM+WHEEL+FREESPIN | Unique |
| M268 | Non-variant | Standard | Tier 1 | BCM+RESPIN+LOCK | Unique |
| M279 | Non-variant | Standard | Tier 1 | BCM+WHEEL+MOVE | Unique |
| M274 | Non-variant | Standard | Tier 1 | BCM+WHEEL | Unique |
| M99 | Non-variant | Standard | Tier 1 | WHEEL+RESPIN+LOCK | Unique |
| M272 | Non-variant | Standard | Tier 2 (spintype) | not fully classified | Unique |
| M120 | Non-variant | Standard | Tier 2 (jackpot) | not fully classified | Unique |
| M147, M163 | Non-variant | Standard | BCM moderate | BCM+WHEEL | Unique |
| M278, M280, M281 | Non-variant | Standard | Uncharted | BCM+RESPIN or BCM+FREESPIN | Unique |

**Key co-clustering observations:**

1. The M250/M260/M264/M268 BCM-hard cluster (Tier 1) is NOT in the trigger-session family (Axis B = Standard). They are "standard" on Axis B but "hard" on Axis C — the BCM leakage is a different failure mode from trigger-session re-attribution.

2. M273's 86-machine group is unique: it is simultaneously Type-2 trigger-session (Axis B) AND the largest shared-binary group (Axis E, 344 cells). When sweeping M273 variants, both the trigger-session complexity and the shared-binary concurrency concern apply together.

3. M257 (Type-2 trigger-session) is also BCM+RESPIN+LOCK — structurally more complex than M201 (RESPIN+FREESPIN only). M278 reuses M257NormalGenerator suggesting it inherits M257's mechanism shape; M278 is not in the trigger-session roster but warrants BCM-level caution.

4. The 45-machine standard large group (Axis E, f7a4cefd...) all land in Axis B=Standard and Axis C=None, confirming they are the cleanest cells for sweep ordering.

5. Trigger-session Type 1 machines span diverse Axis D mechanisms (M12/M15 are NORMAL-only, M32 is WHEEL, M39 is FREESPIN, M206 is RESPIN, M116 is WHEEL+LOCK+FREESPIN) — so trigger-session family membership is not predictable from mechanism alone. This confirms the Axis B classification must be maintained independently.

---

## 5. Total Cells in Scope

**1,688 cells** total: 422 machines × 4 modes (1, 2, 5, 7).

### By mode

| Mode | Cells |
|---|---|
| Mode 1 | 422 |
| Mode 2 | 422 |
| Mode 5 | 422 |
| Mode 7 | 422 |
| **Total** | **1,688** |

Every machine in the fleet exposes all four modes. There are no machines with a subset of modes.

### By archetype

| Archetype | Machines | Cells | % of total cells |
|---|---|---|---|
| Standard standalone | 228 | 912 | 54.0% |
| Type-2 trigger-session variant | 97 | 388 | 23.0% |
| Type-1 trigger-session variant | 41 | 164 | 9.7% |
| Standard variant (non-trigger-session parent) | 28 | 112 | 6.6% |
| Type-1 trigger-session underlying | 11 | 44 | 2.6% |
| Tier-1 hard | 7 | 28 | 1.7% |
| Type-2 trigger-session underlying | 3 | 12 | 0.7% |
| New uncharted BCM | 3 | 12 | 0.7% |
| BCM moderate leakage | 2 | 8 | 0.5% |
| Jackpot special (M120) | 1 | 4 | 0.2% |
| Spintype outlier (M272) | 1 | 4 | 0.2% |
| **Total** | **422** | **1,688** | **100%** |

**Easy cells** (Standard standalone + Standard variant, no known convergence or attribution issues): 1,024 cells (60.7%).

**Cells with at least one known complication** (trigger-session, hard case, BCM, spintype, jackpot, or uncharted): 664 cells (39.3%).

**Tier-1 hard cells** (documented active failure — highest give-up risk): 28 cells (1.7%), 7 machines.

---

## 6. md5 Detection Map

For each cell, the sweep compares a local rawdata cache's md5 against the machine's `(configSummaryMd5, codeSummaryMd5)` pair from machines.json. The following properties are measured facts.

### md5 source per cell type

**Non-variant standalone (230 machines):** Each machine has a unique `(configSummaryMd5, codeSummaryMd5)` pair. The upstream_key equals the machine id. md5 detection is unambiguous: one machines.json entry, one rawdata directory.

**Underlying parents (26 machines):** Each parent has its own `(configSummaryMd5, codeSummaryMd5)` pair distinct from any of its variants (in 18 of 26 families the code md5 differs; in 8 of 26 families the code md5 happens to match one subset of variants — see below). The parent's upstream_key equals its plain machine id. md5 detection for the parent cell is unambiguous.

**Variants (166 machines):** Each variant has a unique upstream_key (verified: 0 upstream_key collisions across all 422 machines). Each variant carries its own `(configSummaryMd5, codeSummaryMd5)` in machines.json.

### Parent vs variant md5 relationship

Two patterns exist:

**Pattern A — variants have DIFFERENT code_md5 from parent (18 families, 51 variants):**
Families: M12, M15, M32, M90, M102, M116 variant vs parent mismatch... (actually M116 falls under Pattern B — see below). The 18 families are M102, M12, M132, M15, M187, M188, M198, M201, M203, M204, M206, M210, M216, M219, M257, M261, M32, M90. In every case the config md5 (cfg) is IDENTICAL between parent and its variants; only the code md5 differs. All variants within one family share the same code md5 as each other (verified: 18/18 families have intra-variant code md5 uniformity). This means the parent's rawdata and the variants' rawdata are stamped with different code md5s even though the game config is the same. The sweep must treat the parent cell and variant cells as having distinct current md5 tokens.

**Pattern B — variants share SAME (cfg, code) md5 as parent (8 families, 115 variants):**
Families: M6 (4 variants), M39 (5), M86 (5), M116 (3), M123 (7), M209 (4), M247 (2), M273 (85). The parent machine and all its variants carry identical `(configSummaryMd5, codeSummaryMd5)` in machines.json. The sweep cannot distinguish parent from variant by md5 pair alone. However, since every machine — including the parent — has a unique upstream_key and therefore a unique rawdata storage path, no storage collision exists. The ambiguity is purely that "md5 changed" for any one machine in this family means it changed for all of them simultaneously (since they all have the same token). Sweeping all 86 M273 machines (parent + 85 variants) at the same time: if any one of them shows a stale md5, all 86 will show stale simultaneously because they share the same machines.json md5 token. This is expected behavior, not a bug.

### Summary

| md5 relationship | Families | Variants | All variants within family share same md5 as each other |
|---|---|---|---|
| Variant code_md5 differs from parent | 18 | 51 | Yes (all 18 families verified) |
| Variant code_md5 same as parent | 8 | 115 | Yes (all 8 families verified) |

No machine has a missing or empty md5 field in machines.json. All 422 machines have both `configSummaryMd5` and `codeSummaryMd5` populated.

---

## 7. Hard-Case Roster

Machines where the sweep is expected to either fail to converge within a standard spin budget, produce unreliable RTP attribution, or require special give-up handling.

### Tier 1 — Active failures (7 machines, 28 cells)

| Machine | Mode cells | Known failure mode | Mechanism | md5 pattern |
|---|---|---|---|---|
| M250 | 4 | 100% of win in `_unattributed_st139` bucket; BCM cycle anchor rule not yet applied | BCM+WHEEL+FREESPIN | Unique |
| M260 | 4 | 70-90% of win unattributed; same BCM anchor gap as M250 | BCM+WHEEL+FREESPIN | Unique |
| M264 | 4 | 70-90% of win unattributed | BCM+WHEEL+FREESPIN | Unique |
| M268 | 4 | 70-90% of win unattributed; RESPIN+LOCK variant of BCM anchor gap | BCM+RESPIN+LOCK | Unique |
| M279 | 4 | 4 iterations to converge; BCM peak-detection; MOVE mechanic complicates sub-round sequencing | BCM+WHEEL+MOVE | Unique |
| M99 | 4 | ST=97+ST=98 dedup open bug (double-counts); paid spin type=96 (non-standard) | WHEEL+RESPIN+LOCK | Unique |
| M274 | 4 | Baseline BCM machine; must preserve existing correct output (regression tripwire) | BCM+WHEEL | Unique |

For the sweep, these 7 machines are expected to produce stale or incorrect reports with standard spin budgets. The "give up after N spins" threshold should fire earliest for M250, M260, M264, M268 (where attribution is structurally broken regardless of sample size).

### Tier 2 — Structural outliers requiring explicit handling (14 + 3 machines)

**Trigger-session family (14 underlying machines, 44 underlying cells + 164 type-1 variant cells + 388 type-2 variant cells = 596 cells total including all variants):**

The trigger-session mechanism causes analyzer attribution to diverge from upstream server RTP if the trigger anchor is misidentified. These machines do not necessarily diverge on raw RTP, but the per-pay-id breakdown is structurally skipped or approximate. The sweep's md5-drift detection will work for these cells, but a CI-pass does not guarantee correct per-pay-id attribution.

Type-1 machines (11): M12, M15, M32, M90, M132, M206, M39, M86, M116, M210, M123.
Type-2 machines (3): M201, M257, M273.

**Non-standard paid spin type (2 machines, 8 cells):**

| Machine | Paid spin type | Impact on sweep |
|---|---|---|
| M99 | 96 (not 1) | Default manifest bootstrap wrong; report generated with wrong paid-round denominator |
| M272 | 140 (not 1) | Same; manifest must override paid_spin_type |

**Jackpot special (1 machine, 4 cells):**

M120: pay-id 666 attribution requires special handling (MultiSymbolCollectionFreespin mechanism). Sweep will generate a report, but the pay-id 666 bucket may be misattributed.

### BCM moderate leakage (2 machines, 8 cells)

M147 and M163: approximately 35% of win went to the unattributed bucket in the BCM fleet sweep (machine_round_win_rules.json doc). These are below the Tier 1 threshold but still produce materially incomplete reports.

### New uncharted BCM (3 machines, 12 cells)

M278, M280, M281: all three are BCM machines added after the machine_modes.json was last updated. No sweep history exists. M278 reuses M257NormalGenerator, suggesting structural similarity to the M257/Type-2 family but without the trigger-session classification. The sweep should treat these as BCM-unknown and apply generous spin budgets; their give-up behavior is unpredictable.

---

## 8. Concurrency Safety

### No hard storage collision

Every machine has a unique upstream_key (verified: 0 collisions across all 422 machines). Rawdata is stored per upstream_key. Sweeping all 1,688 cells in parallel produces no storage path collision.

### Rate-limit concentration risk

The upstream API enforces per-source rate limits (approximately 1,000 outer requests/second across the whole connection; per-IP throttling observed at sustained high concurrency per memory `reference_upstream_throttle_ceiling.md`).

The M273 family (parent + 85 variants = 86 machines, 344 cells) all share the same game binary (codeSummaryMd5 = c2a4e3be...) but have distinct upstream_keys and distinct upstream game configs. Launching all 344 M273 cells simultaneously would fire ~344 concurrent upstream requests against the same game binary. While no upstream state is formally shared (each variant has a distinct upstream_key and game config), the concentrated load on one simulator binary is a known DoS-self risk pattern. Recommended: cap concurrent inflight requests for machines sharing a codeSummaryMd5 to a sub-fleet concurrency limit (the designer decides the exact cap).

The 45-machine standard large group (f7a4cefd...) has 45 distinct game configs even though they share a binary. These are independent machines and concurrent sampling is lower risk than M273's 86-machine single-config group, but the same binary-level cap applies.

**Groups with the largest binary-sharing concurrency risk:**

| Group | Machines sharing binary | Cells | Risk level |
|---|---|---|---|
| M273 family | 86 | 344 | High (same binary, many simultaneous requests) |
| Standard large group (f7a4cefd...) | 45 | 180 | Moderate (same binary, distinct configs) |
| M123 family | 8 | 32 | Low |
| M201 family | 8 | 32 | Low |

### Analyzer-level state

The upstream sampling endpoint has no documented shared mutable state between parallel calls for different upstream_keys. There are no lock files per upstream_key in the existing rawdata directory structure. The existing `rawdata_locks.json` mechanism (configs/rawdata_locks.json) governs which rawdata directories are locked against deletion, not against concurrent writes.

The sweep should check rawdata_locks.json before touching any cell: if a cell's rawdata directory is locked, skip it for the current run without flagging it as stale.

---

## 9. Recommended Cell Ordering

**Objective:** Maximize the fraction of useful reports produced before hitting the upstream rate limit, and surface easy wins early so operators see results quickly.

### Proposed ordering tiers (descriptive, not prescriptive)

**Tier 0 — Skip conditions (process first to prune scope):**
1. Cells where rawdata_locks.json marks the directory as locked.
2. Variant cells (optional): if the parent underlying machine's report is already current, the variant's report is structurally identical in most respects. Designer decides whether variant cells are swept independently or inherit the parent's result.

**Tier 1 — Easy, fast convergers (1,024 cells):**
Standard standalone (228 machines) + Standard variant (28 machines) with no BCM, no trigger-session, no known outlier status. Mode 1 first (operator's primary verification mode per memory `user_testing_machine.md`), then modes 2, 5, 7. Within this tier, prioritize the 45-machine standard large group (M1, M2, M14, etc.) as they share a well-understood binary with no known issues.

**Tier 2 — Trigger-session family (596 cells across Type-1 and Type-2 variants + underlyings):**
These produce reports but the per-pay-id breakdown has structural limitations. Process after Tier 1 so that operators see most of the fleet in a known-good state before encountering trigger-session complexity. Within this tier, process Type-1 underlyings before their variants (underlyings are the canonical machines; variants are derivative). M273's 85 variants (340 cells) should be rate-limited to avoid saturating the shared binary.

**Tier 3 — BCM moderate + new uncharted (20 cells):**
M147, M163, M278, M280, M281. BCM machines with unknown or moderate attribution quality. Process with generous spin budgets and conservative give-up thresholds.

**Tier 4 — Tier-1 hard cases (28 cells, 7 machines):**
M250, M260, M264, M268, M279, M99, M274. Process last. For M250/M260/M264/M268 (structural attribution failure), the sweep should flag these as "requires manual intervention" rather than running to a give-up spin count, since no spin budget will fix the BCM anchor gap. For M279 and M274, full spin budgets apply; M274 is the regression tripwire so its result should be verified carefully. For M99, flag the open ST=97+ST=98 dedup bug in the sweep result.

**Why easy-first (not random):**
Random ordering risks spending rate-limit budget on hard cases while easy machines remain unsweep'd. Easy-first ensures the 60.7% of easy cells produce clean reports regardless of whether the sweep times out on hard cases.

---

## 10. Outlier Inventory

Every machine that does not fit the standard cluster, with one-line reason:

| Machine | Reason |
|---|---|
| M250 | BCM cycle anchor gap: 100% of win unattributed in fleet sweep |
| M260 | BCM cycle anchor gap: 70-90% win unattributed |
| M264 | BCM cycle anchor gap: 70-90% win unattributed |
| M268 | BCM cycle anchor gap, RESPIN+LOCK variant: 70-90% win unattributed |
| M279 | BCM+MOVE: took 4 analyzer iterations to converge; peak-detection fragile |
| M274 | BCM+WHEEL baseline: regression tripwire; must not regress |
| M99 | Open ST=97+ST=98 dedup bug; paid spin type=96 (non-standard) |
| M272 | Paid spin type=140 (non-standard); manifest must override default |
| M120 | Jackpot machine: pay-id 666 requires special attribution rule |
| M147 | BCM+WHEEL with 35% unattributed win leakage in fleet sweep |
| M163 | BCM+WHEEL+RESPIN with 35% unattributed win leakage |
| M278 | New BCM+RESPIN machine; not in machine_modes.json; no sweep history |
| M280 | New BCM+FREESPIN machine; not in machine_modes.json; no sweep history |
| M281 | New BCM+LOCK+FREESPIN machine; not in machine_modes.json; no sweep history |
| M273 (+ 85 variants) | 86-machine family sharing one game binary: concurrency concentration risk; also Type-2 trigger-session |
| M12/M15/M90/M132/M206 | Type-1 trigger-session (TopDollar): ST=14 phantom offers, ST=15 settlement; per-pay-id attribution structurally skipped |
| M32 | Type-1 trigger-session (QuickDollar): same pattern as TopDollar family |
| M39 | Type-1 trigger-session (DancingDrum): 5 variants |
| M86 | Type-1 trigger-session (HoppyHunting): 5 variants |
| M116/M210 | Type-1 trigger-session (ChristmasSimple) |
| M123 | Type-1 trigger-session (ValentineSimple): 7 variants |
| M201/M257 | Type-2 trigger-session (CommonSelector / CommonSelector+BCM) |

---

## 11. Suggested Groupings for Plugin Architecture

These are natural seams in the fleet where "shared base + per-cluster extension" could make sense for the sweep feature. The designer decides whether and how to exploit them.

**Seam 1 — Standard batch (1,024 cells):** Standard standalone + Standard variant cells. Share no known special handling. A single sweep loop with standard spin budget and standard give-up threshold covers all of them.

**Seam 2 — Trigger-session family (596 cells):** Type-1 (52 machines) and Type-2 (100 machines). Share the property that per-pay-id attribution is structurally limited. A common "trigger-session aware" sweep wrapper that logs this limitation in the cell result covers all variants and underlyings alike. Within this seam, Type-1 and Type-2 use different re-attribution rules (Type-1: ReMarks last-non-none anchor; Type-2: win=0 pay-id anchor + sum-all) — the seam splits at the protocol level but the sweep-feature handling (flag the cell as trigger-session; apply standard spin budget; annotate result) is shared.

**Seam 3 — BCM hard cluster (Tier 1 BCM: M250/M260/M264/M268/M279/M274, 24 cells):** All share BCM+Wheel or BCM+Respin mechanism. A "BCM hard" sweep mode that applies a different give-up threshold and annotates the result with "BCM anchor gap — manual review required" covers all six machines as a group. M274 in this group is the regression tripwire; the sweep could special-case it with a stricter pass/fail assertion.

**Seam 4 — BCM moderate + new uncharted (20 cells):** M147, M163, M278, M280, M281. All BCM machines with unknown or partial attribution. Share the property that a generous spin budget is needed before declaring convergence. A "BCM cautious" sweep mode covers all five.

**Seam 5 — M273 rate-limit group (344 cells):** All 86 M273 machines share one game binary. The sweep scheduler needs a concurrency cap for this group regardless of which other groupings apply. This is a scheduling seam, not a logic seam — the actual sweep logic for M273 variants uses the Type-2 trigger-session path (Seam 2).

**Seam 6 — Spintype outliers (8 cells):** M99 (paid ST=96) and M272 (paid ST=140). These need a manifest-override check before the sweep starts, not a different sweep loop. The seam is at the manifest-validation layer, not the sweep layer.
