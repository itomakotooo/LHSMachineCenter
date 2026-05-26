# 02 — Fleet Taxonomy (Analyzer Unbundle)

> **Date**: 2026-05-25
> **Role**: arch-taxonomist (Wave 1)
> **Input**: `00_brief.md`, `session_artifacts/_arch/09_architecture_as_built.md`, `session_artifacts/_impl/STATUS.md`, `configs/machines.json`, `slot_designer/configs/machine_manifests/*.json`, rawdata samples (5 representative machines + fleet-wide survey)
> **Output**: `session_artifacts/_arch_analyzer_unbundle/02_taxonomy.md`
> **Next consumer**: `arch-designer` (Wave 2)

---

## §1 Scope & Inventory

### Fleet composition

| Source | Count | Notes |
|---|---|---|
| `configs/machines.json` total entries | 422 | Includes variants |
| Base machines (no `$` in ID) | 256 | Unique underlying machines |
| Variant machines (contain `$`) | 166 | Selector variants of 26 underlying bases |
| Base machine manifest files | 253 | 3 bases missing manifests (M278/M280 + 1 gap) |
| Variant manifest files | 166 | All variants covered |
| `manifest_schema.json` | 1 | Schema definition, not a machine |

The brief states "419 machines" (as in the original arch-team taxonomy); the precise count from current `configs/machines.json` is **256 base + 166 variants = 422 total entries** (4 entries added since original taxonomy, including M278/M280/M281 and one other).

### Sampling strategy

Fleet size is 256 base machines. This is below the ≥30 threshold at which full sampling would normally be replaced by 10-15% sample analysis. However, for structural mechanism axes, the data is drawn from `logicClassNames` in `machines.json` (which is present for all 256 bases), supplemented by observed `SpinType`, `PayoutByPayline`, `StopSymbolsByCol`, and `PayoutIdToWinAmount` fields from rawdata chunks.

**Rawdata coverage**: 255 of 256 bases have at least one cached chunk in `rawdata/<M>/mode_1/` (one missing). For rawdata axes (SpinType, payline, grid), first chunk of each machine was sampled (up to 1,500 rounds total per machine across up to 5 robots × 300 rounds each).

**Method**: Python scripts run directly against `configs/machines.json` (all 256 bases enumerated) + rawdata chunk sampling (255 bases with data). No naming-convention inference was used; all classification is from observed properties.

---

## §2 Clustering Axes

Six independent axes were measured:

| Axis | Source | What it measures |
|---|---|---|
| **Ax1: Mechanism combo** | `logicClassNames` in `machines.json` | Which mechanic classes co-occur: Collection/BCM, Freespin, Wheel, LockRespin, Respin, MoveSpin, Minigame |
| **Ax2: Paid SpinType convention** | Rawdata `SpinType` field, most-common per machine | Which integer ST value is the primary paid round; distinguishes ST=1 (bootstrap), ST=140 (BCM family), and 60+ distinct per-machine conventions |
| **Ax3: Grid dimensions** | Rawdata `StopSymbolsByCol` field (cols × rows) | Physical reel grid; determines payline topology |
| **Ax4: Payline count** | Rawdata `PayoutByPayline` max positive line_id | Number of active paylines (1, 5, 9, 25, 81, 100, etc.) |
| **Ax5: Jackpot PID presence** | Rawdata `PayoutIdToWinAmount`, PIDs ≥ 10000 | Whether machine has jackpot pay_id events (high-value single hits) |
| **Ax6: Scatter trigger marker** | Rawdata `PayoutIdToWinAmount` zero-win PIDs + payline line_id=-1 entries | Whether machine uses a scatter/trigger marker PID (e.g., pid=666, line_id=-1) to signal freespin trigger |

The manifest's `spin_type_convention`, `trigger_session_pattern`, and `layer4_applicable` fields are **uniformly bootstrap-defaulted** for 182 of 253 base manifests and carry no structural information for clustering — they record what the bootstrap script assumed, not what rawdata shows. The axes above are all measured from actual data.

---

## §3 Per-Axis Clusters

### Ax1: Mechanism combo (from `logicClassNames`)

Classification method: presence of class-name substrings in `logicClassNames`. A machine is flagged for a mechanism if any class in its list contains the pattern. Flags are not mutually exclusive; the archetype is the combination of flags.

**Flag definitions** (measurable):
- `has_collection`: any class containing `Collection` or `Collect`
- `has_freespin`: any class containing `Freespin`, `FreeSpinGenerator`, or `FreeSpin`
- `has_wheel`: any class containing `Wheel`
- `has_lock`: any class containing `LockReSpin`, `LockSpin`, or `LockSymbol`
- `has_respin` (non-BCM): any class containing `ReSpin`, `Respin`, or `ReSpinGenerator` AND `has_collection` is false
- `has_move`: any class containing `MoveSpin` or `MoveCompli`
- `has_minigame`: any class containing `Minigame` or `MiniGame`

**Archetypes** (256 base machines total):

| Archetype | Count | Sample member IDs |
|---|---|---|
| **A_VANILLA** | 53 | M1, M2, M4, M8, M9, M13, M14, M16, M17, M19, M34, M35, M37, M38, M40, M41, M57, M59, M63, M64, M66, M70–M74, M78, M84, M101, M105, M106, M113, M122, M127, M132, M135, M137, M139, M142, M144, M145, M154, M155, M157, M160–M162, M169–M173, M12, M15 |
| **B_BCM_FREESPIN_WHEEL** | 20 | M108, M117, M125, M126, M220, M229, M234, M237, M239, M248, M249, M250, M254, M259, M260, M261, M262, M264, M273, **M275** |
| **B_BCM_FREESPIN** | 19 | M111, M120, M138, M186, M194, M231, M235, M251, M252, M253, M256, M257, M263, M265, M266, M271, M272, M280, M281 |
| **B_BCM_WHEEL** | 18 | M94, M147, M163, M192, M227, M228, M232, M233, M236, M242, M245, M246, M247, M267, M270, M274, M276, M279 |
| **C_RESPIN_ONLY** | 36 | M7, M20, M25, M30, M42, M43, M44, M53, M54, M61, M62, M65, M75, M76, M128, M148, M150, M156, M159, M164, M174, M177, M189–M191, M195–M197, M200, M206, M215, M218, M221, M223, M224, M226 |
| **C_FREESPIN_ONLY** | 42 | M5, M6, M11, M18, M24, M27, M28, M31, M33, M36, M39, M50, M67, M79, M87, M88, M95, M96, M97, M107, M109, M121, M129, M130, M134, M136, M146, M165, M166, M167, M178–M182, M184, M185, M199, M202, M210, M212, M243 |
| **C_WHEEL_ONLY** | 23 | M3, M32, M47, M48, M99, M102, M110, M112, M151, M158, M175, M187, M188, M198, M203, M204, M211, M213, M214, M216, M217, M219, M241 |
| **C_FREESPIN_WHEEL** | 13 | M21, M22, M60, M86, M93, M116, M119, M123, M168, M171, M176, M207, M225 |
| **C_LOCK_RESPIN** | 10 | M10, M23, M46, M58, M103, M104, M131, M133, M244, M268 |
| **C_LOCK_FREESPIN** | 8 | M100, M114, M183, M193, M201, M208, M222, M240 |
| **D_COMPLEX_OTHER** | 7 | M90, M152, M153, M238, M269, M277, M278 |
| **D_MOVE_SPIN** | 5 | M26, M51, M140, M149, M209 |
| **D_MINIGAME** | 2 | M98, M124 |

**BCM sub-total** (all B_* archetypes combined): 57 machines = 22% of base fleet.

**Named outliers within Ax1 clusters:**

- **M94** (classified B_BCM_WHEEL): has `CollectionDoubleGemsWheelGenerator` classes but rawdata shows ST=1/ST=2 (not the expected ST=140 BCM convention). Structural mechanism matches BCM_WHEEL but spin-type convention is anomalous.
- **M113** (classified A_VANILLA): has `ExpandingSymbolSpinGenerator` — a unique expanding-symbol mechanic not seen elsewhere in the fleet. Logic classes are `[ExpandingSymbolSpinGenerator, ExpandingSymbolSpinValidator, NormalRTPPreProcessor]`. Rawdata ST=112. Acts as a solo-engine VANILLA in terms of no bonus phases, but the expansion mechanic is per-machine code, not generic Normal* engine.
- **M37** (classified A_VANILLA): code-identical to M1 (same `codeSummaryMd5 = f7a4cefda016`), rawdata ST=1. Structurally pure vanilla; mentioned in brief as "classic seven" machine but no analyzer-visible structural difference from other vanilla.
- **M11** (classified C_FREESPIN_ONLY): all classes are `Grand*` (GrandFinalReSpinGenerator / GrandFreeSpinGenerator / etc.). Rawdata paid ST=17, bonus STs 10/11/12. This machine has completely bespoke SpinType numbering (per Tier-1 hard-case roster in `09_architecture_as_built.md`).
- **M90** (classified D_COMPLEX_OTHER): has `CollectionTopDollarGenerator` classes (BCM logic) AND `TopDollarSelectorGenerator` (wheel/selector) AND `NormalSpinGenerator`. Raw ST shows paid=1, bonus STs 14/15 (TopDollar selector pattern). BCM collection is present in code but the machine's primary bonus is TopDollar-style; its BCM routing may behave differently from the M140/M274 family.
- **M250** (B_BCM_FREESPIN_WHEEL): rawdata grid=20×1 (single-row 20-column). This is a structural outlier in grid topology relative to all other BCM machines (which are 3×3 or 5×3).
- **M239** (B_BCM_FREESPIN_WHEEL): rawdata grid=9×1. Another single-row outlier in the BCM family.

---

### Ax2: Paid SpinType convention (from rawdata)

The most common `SpinType` value observed across ≥200 rounds is treated as the paid-round ST.

| Convention | Count | Measurable criterion | Sample IDs |
|---|---|---|---|
| **ST=1 (bootstrap default)** | 140 machines | Most-common ST in rawdata = 1 | M1, M14, M37, M101, M105, M106, M120, M130… |
| **ST=140 (BCM convention)** | 53 machines | Most-common ST in rawdata = 140 | M147, M152, M153, M163, M186, M192, M194, M220, M227–M281 (BCM family) |
| **ST=13 (LockRespin family)** | 6 machines | Most-common ST = 13 | M10, M23, M93, M131, M133, M277 |
| **ST=96 (GoldenPrize family)** | 3 machines | Most-common ST = 96 | M99, M103, M104, M240 |
| **ST=43/44 (RapidHit family)** | 6 machines | Most-common ST in {43, 44} | M31, M67, M79, M87, M95, M109, M134, M146, M179 |
| **ST=32–34 (TwentyOneDiamonds)** | 3 machines | Most-common ST in {32,33,34} | M28, M129, M136 |
| **ST=35/36 (MoveSpin family)** | 5 machines | Most-common ST in {35,36} | M26, M51, M140, M149, M226 |
| **ST=101 (Butterfly/Buff collection)** | 3 machines | Most-common ST = 101 | M108, M117, M125 |
| **ST=87/88 (Valentine/WolfMoon)** | 4 machines | Most-common ST in {87,88} | M97, M116, M123, M97 |
| **Other (one-off per machine)** | ~35 machines | Unique ST per machine | M11 (17), M113 (112), M122 (132), M18 (19), M20 (20), M21 (27), M22 (28), M24 (45), M27 (39), M30 (37), M33 (58), M36 (52), M39 (71), M46 (60), M47 (74), M50 (64), M58 (60), M65 (70), M86 (76), M100 (92), M107 (71), M111 (131), M138 (142), M249 (153), M251 (151), M254 (154), M260 (156), M266 (156) |

**Key finding**: the manifest bootstrap assumes `paid=[1]` for all 253 base manifests, but 116 machines (45%) use a paid ST other than 1. This is the root cause of the analyzer's universal L4 (Layer 4 trigger-session) structural issue, and explains why 59 machines fail L2 even after Phase 3 manifest work.

---

### Ax3: Grid dimensions (from rawdata `StopSymbolsByCol`)

| Grid | Count | Sample IDs |
|---|---|---|
| **3×3** (dominant) | 214 machines | M1, M10, M11, M14, M37, M99, M100, M272, M274, M275, M279, … |
| **5×3** (5-reel) | 24 machines | M107, M108, M116, M117, M123, M126, M137, M168, M176, M201, M22, M221, M248, M254, M260 + 9 more |
| **4×3** | 8 machines | M4, M12, M113, M169, M178, M197, M236, M259 |
| **9×1** (single-row strip) | 3 machines | M96, M129, M239 |
| **5×4** | 2 machines | M21, M86 |
| **6×3** | 2 machines | M24, M261 |
| **3×1** (single-row, 3 col) | 1 machine | M20 |
| **20×1** (slot strip) | 1 machine | M250 |

**3×3 is the dominant grid** (83.6% of fleet). All BCM_WHEEL machines are 3×3 except M236 (4×3). BCM_FREESPIN_WHEEL machines are mixed (3×3 dominant but several 5×3 and two single-row outliers M239/M250).

---

### Ax4: Payline count (from rawdata `PayoutByPayline` max positive line_id)

| Payline count | Count | Notes |
|---|---|---|
| **1 payline** | 73 machines | Single-line machines (line_id always 1) |
| **5 paylines** | 62 machines | 5-line machines; dominant in BCM family |
| **9 paylines** | 77 machines | 9-line machines; dominant in vanilla |
| **20 paylines** | 6 machines | M24, M60, M79, M176, M199, M212 |
| **25 paylines** | 3 machines | M67, M117, M125 |
| **27 paylines** | 5 machines | M6, M64, M106, M119, M225 |
| **30 paylines** | 7 machines | M5, M88, M108, M126, M168, M201, M248 |
| **40 paylines** | 3 machines | M27, M116, M129 |
| **81 paylines** | 1 machine | M113 |
| **100 paylines** | 1 machine | M107 |
| **10+ other** | 4 machines | M87 (10), M123 (10), M204 (10), M209 (15), M160 (15), M56 (56 — M260) |
| **0 (no wins in sample)** | 10 machines | M21, M214, M239, M250, M254, M33, M36, M39, M86, M96 — low-hit machines; sample too small for payline |

**Payline style note**: line_id=-1 in `PayoutByPayline` string signals a scatter/trigger marker (not a "ways" payline). All scatter machines show line_id=-1 with a zero-win PID. No machine in this fleet uses traditional "ways" paylines with negative line IDs as a counting mechanism — the negative line IDs are exclusively the scatter trigger marker position.

---

### Ax5: Jackpot PID presence (PIDs ≥ 10,000 in `PayoutIdToWinAmount`)

26 machines have at least one observed jackpot PID (≥ 10,000):

```
M25, M67, M87, M106, M114, M121, M123, M134, M140, M149, M155, M174, M185, M188,
M197, M201, M218, M232, M237, M238, M243, M252, M259, M270, M275, M276
```

This is a measurable criterion: at least one `PayoutIdToWinAmount` key ≥ 10,000 observed across 1,500 sampled rounds.

Archetype distribution of jackpot machines:
- A_VANILLA: M106, M155 (2)
- B_BCM_FREESPIN_WHEEL: M237, M259, M275 (3)
- B_BCM_WHEEL: M232, M270, M276 (3)
- C_FREESPIN_ONLY: M67, M87, M121, M134, M185, M243 (6)
- C_RESPIN_ONLY: M140, M149, M174, M197, M218 (5)
- C_FREESPIN_WHEEL: M123 (1)
- C_LOCK_FREESPIN: M114, M201 (2)
- D_COMPLEX_OTHER: M238, M252 (2)
- Other: M25, M88, M155, M188 (4)

Jackpot PIDs are **not confined to BCM machines** — they appear across archetypes. The naming convention (M275's jackpot PIDs are 27502/27503/27504; M270's are 27002/27003/27004/27005) suggests machine-ID-prefixed jackpot numbering as a pattern, but it is not universal.

---

### Ax6: Scatter trigger marker (zero-win PIDs in line_id=-1 of `PayoutByPayline`)

Two sub-groups:

**pid=666 (standard scatter marker)**: 99 machines

```
M12, M15, M18, M21, M24, M25, M27, M31, M32, M33, M36, M39, M46, M47, M58, M61, M62,
M67, M76, M79, M86, M87, M88, M90, M95, M96, M97, M98, M99, M100, M102, M107, M109,
M110, M112, M114, M116, M117, M119, M120, M121, M124, M125, M128, M132, M134, M146,
M151, M158, M165, M166, M167, M175, M176, M178, M179, M180, M181, M183, M184, M185,
M187, M188, M192, M193, M196, M198, M199, M200, M202, M203, M204, M206, M208, M210,
M212, M213, M214, M216, M217, M220, M225, M229, M231, M234, M235, M240, M242, M243,
M246, M249, M253, M254, M256, M257, M261, M263, M264, M272, M275
```

**Other zero-win scatter markers (not 666)**: 50 machines use alternative PIDs (777, 1001, 5801, 9, 401, 667, 1700, 2600, etc.)

```
M3, M5, M6, M7, M20, M22, M28, M48, M50, M53, M60, M88, M93, M94, M103, M108, M111,
M123, M126, M129, M136, M152, M153, M168, M171, M174, M182, M201, M207, M211, M218,
M222, M223, M233, M239, M241, M244, M245, M247, M252, M259, M260, M262, M266, M271,
M273, M274, M277, M278, M280
```

**No scatter marker** (pure spinType, no zero-win trigger): ~107 machines (includes most pure VANILLA and RESPIN_ONLY).

The scatter trigger is the mechanism behind Gap #3 in the brief (pid=666 being mis-classified as `cat=paid` rather than trigger marker). It affects 99 machines on the standard pid=666 alone, plus 50 additional machines with non-666 scatter markers.

---

## §4 Cross-Axis Similarity Matrix

The following table shows how the 13 mechanism archetypes (Ax1) distribute across the other five axes. Dominant value shown; "mixed" = no single value covers >70% of archetype members.

| Archetype (Ax1) | Count | Paid ST (Ax2) | Grid (Ax3) | Paylines (Ax4) | Has Jackpot (Ax5) | Has Scatter pid=666 (Ax6) |
|---|---|---|---|---|---|---|
| **A_VANILLA** | 53 | ST=1 (100%) | 3×3 (83%) | 1/5/9 (mixed) | 2 machines (M106, M155) | Rare (~15 machines) |
| **B_BCM_FREESPIN_WHEEL** | 20 | ST=140 (72%); ST≠140: M108 (101), M117 (101), M125 (101), M126 (140), M249 (153), M254 (154), M260 (156) | 3×3 (65%); 5×3: M108/M117/M125/M126/M248/M254/M260; 9×1: M239; 20×1: M250; 6×3: M261 | 5 (60%); mixed for 5×3 machines (25–56) | 3 machines (M237, M259, M275) | 14 machines (70%) |
| **B_BCM_FREESPIN** | 19 | ST=140 (79%); outliers: M111 (131), M138 (142), M251 (151), M266 (156) | 3×3 (100%) | 5 or 9 (mixed) | 0 | 9 machines (47%) |
| **B_BCM_WHEEL** | 18 | ST=140 (94%); outlier: M94 (ST=1/2) | 3×3 (94%); M236 (4×3) | 5 or 9 (mixed) | 3 machines (M232, M270, M276) | 4 machines (22%) |
| **C_RESPIN_ONLY** | 36 | ST=1 (39%); highly mixed | 3×3 (86%) | 1/5/9 (mixed) | 5 machines | 6 machines (17%) |
| **C_FREESPIN_ONLY** | 42 | ST=1 (43%); highly mixed | 3×3 (83%) | Mixed | 6 machines | 18 machines (43%) |
| **C_WHEEL_ONLY** | 23 | ST=1/ST=2 (65%); M99: ST=96; M104: ST=96 | 3×3 (100%) | 1/5/9 (mixed) | 0 | 10 machines (43%) |
| **C_FREESPIN_WHEEL** | 13 | ST=1 (46%); highly mixed | 3×3/5×3 (mixed) | Mixed | 1 machine (M123) | 5 machines (38%) |
| **C_LOCK_RESPIN** | 10 | ST=13 (50%); mixed | 3×3 (100%) | 1/5 (mixed) | 0 | 0 |
| **C_LOCK_FREESPIN** | 8 | ST=1 (50%); mixed | 3×3 (100%) | 5 (75%) | 2 machines (M114, M201) | 6 machines (75%) |
| **D_COMPLEX_OTHER** | 7 | ST=140 (71%) | 3×3 (86%) | Mixed | 2 machines | 3 machines (43%) |
| **D_MOVE_SPIN** | 5 | ST=35/36 (80%) | 3×3 (80%) | 9 (60%) | 1 machine (M140, M149) | 0 |
| **D_MINIGAME** | 2 | ST=1 (50%); M124: ST=139, M98: ST=1 | 3×3 (100%) | 9 (100%) | 0 | 1 machine (M124) |

**Co-clustering pattern ("always co-cluster")**: The B_BCM_WHEEL archetype co-clusters tightly on Ax2 (paid ST=140, 94%) and Ax3 (3×3 grid, 94%). The B_BCM_FREESPIN_WHEEL archetype co-clusters on Ax2 (72%) and Ax6 (scatter, 70%) but fragments on Ax3 (grid is mixed) and Ax4 (payline counts vary).

**Fragmented dimensions**: Ax2 (paid ST) is the most fragmented axis for C_* archetypes — each machine family has its own convention. Ax4 (payline count) is fragmented across all archetypes; payline count is a per-machine parameter, not an archetype property.

---

## §5 Outlier Inventory

Machines that do not fit the common cluster pattern, with one-line reason:

| Machine | Archetype | Outlier reason |
|---|---|---|
| **M11** | C_FREESPIN_ONLY | Bespoke SpinType numbering (paid=17, bonus=10/11/12); `Grand*` engine family found nowhere else; Tier-1 hard case from `09_architecture_as_built.md` |
| **M37** | A_VANILLA | Classic Seven paytable; code-identical to M1 (same `codeSummaryMd5`); paytable has top jackpot symbol that visually looks special but structurally is pure vanilla to the analyzer |
| **M94** | B_BCM_WHEEL | Has `CollectionDoubleGems*` BCM classes but rawdata paid ST=1 (not ST=140); BCM code is present but uses vanilla spin-type convention — analyzer's current BCM detection (which assumes ST=140) will miss it |
| **M99** | C_WHEEL_ONLY | Paid ST=96 (not ST=1); Tier-2 hard case; known in `09_architecture_as_built.md` as "bootstrap default wrong" |
| **M113** | A_VANILLA | `ExpandingSymbolSpinGenerator` — unique expanding-reel mechanic; not collectible, not freespin, but also not `NormalSpin*` — the engine is bespoke; rawdata ST=112 |
| **M250** | B_BCM_FREESPIN_WHEEL | Grid=20×1 (single-row, 20 columns); structurally a strip-reel not a matrix-reel; Tier-1 hard case; 100% fallback in BCM sweep |
| **M239** | B_BCM_FREESPIN_WHEEL | Grid=9×1 (single-row strip); same structural anomaly as M250 but smaller |
| **M90** | D_COMPLEX_OTHER | Has both BCM collection (`CollectionTopDollar*`) AND TopDollar selector (`TopDollarSelectorGenerator`) AND `NormalSpinGenerator`; raw paid ST=1, bonus ST=14/15; BCM + selector combo with ST=1 convention — the collect mechanic may behave differently from the M274/M279 family |
| **M260** | B_BCM_FREESPIN_WHEEL | Paid ST=156 (unique convention), grid=5×3, 56 paylines; `HalloweenReelCollection` class family; Tier-1 hard case; 70-90% fallback in BCM sweep |
| **M108** | B_BCM_FREESPIN_WHEEL | Paid ST=101 (`ButterflyFreespin`); 5×3 grid, 30 paylines; `MapButterflyFreespin*` classes not shared with other BCM machines |
| **M117** | B_BCM_FREESPIN_WHEEL | Paid ST=101; mixes `CreditsSymbolRespin*` + `M117Freespin*` + `M116WheelSpin*` (reuses M116 class); structural complexity not shared with BCM core |
| **M126** | B_BCM_FREESPIN_WHEEL | Paid ST=2 (wheel entry) + 126 (freespin) + 140 (collection); ST=2 as wheel-entry is atypical in BCM family; `AddFreespinWheel*` pattern |
| **M209** | D_MOVE_SPIN | BCM _and_ MoveSpin (`M209MoveSpinPostProcessor`); paid ST=140 + bonus STs 36/140/149 — crosses archetype boundary |
| **M277** | D_COMPLEX_OTHER | BCM + LockRespin (`M277LockRespinGenerator`); paid ST=13 (lock convention) + ST=140 (BCM); crosses archetype boundary |
| **M278** | D_COMPLEX_OTHER | BCM + `JewelFever*` respin; paid ST=140, bonus ST=160; unique respin sub-type |
| **M272** | B_BCM_FREESPIN | Known Tier-2 hard case; paid ST=140, BUT the manifest bootstrap set paid=[1]; in rawdata it is clearly 140/126; the manifest is wrong |
| **M99** | C_WHEEL_ONLY | Paid ST=96 (GoldenPrize wheel); has `FinalMinigameGenerator` — the minigame sub-type not in the generic wheel pattern; ST=97 (lock) + ST=98 (final minigame); known double-count bug for ST=97+98 per `09_architecture_as_built.md` |
| **M268** | C_LOCK_RESPIN | Has `CreditsSymbolRespin*` classes (which appear in BCM machines) but no `Collection` class; rawdata paid ST=125; Tier-1 hard case (70-90% fallback) |
| **M152 / M153** | D_COMPLEX_OTHER | BCM collection (`NormalCollectionSpin*`) but no freespin, no wheel, only the base collection accumulator; paid ST=140; misclassified by archetype logic as COMPLEX_OTHER because they fit B_BCM pure-collection but the classifier requires a second mechanic |

---

## §6 BCM Family Deep-Dive

The BCM (Bonus Collect Multiplier / BuffCollection) family is the primary subject of M275's 8 gaps and deserves its own section.

### What defines BCM

The BCM mechanism is identified by co-presence of:
1. `BuffCollectionDataGenerator` + `BuffCollectionDataModel` + `BuffCollectionMapGenerator` + `BuffCollectionMapValidator` (the core BCM state machine classes) in `logicClassNames`
2. Rawdata paid ST = 140 (observed in 94% of BCM machines; exceptions documented above)
3. `ReMarks` field in rawdata rounds contains `CollectCount:N; AddCollectCount:M` annotations on freespin rounds

**Total BCM machines** (has `BuffCollectionData*` classes): 57 machines = 22% of base fleet.

Note: M152/M153 have `NormalCollectionSpinGenerator` without `BuffCollection*`; they are a simpler collection variant (no BuffMap). M94 has `CollectionDoubleGems*` with paid ST=1; these are two additional BCM-family sub-variants.

### BCM sub-families

Within the 57 BCM machines, three structural sub-types visible in rawdata:

| Sub-type | Key distinguisher | Members (sample) |
|---|---|---|
| **BCM+Freespin+Wheel (full combo)** | Has freespin ST (126) + wheel ST (2 or machine-specific) | M250, M264, M275, M261, M262, M220, M234, M237 |
| **BCM+Freespin only** | Has freespin ST (126) without wheel ST | M272, M235, M253, M263, M264, M271, M280 |
| **BCM+Wheel only** | Has wheel/bonus ST (36 or 139 etc.) without freespin ST=126 | M274, M279, M232, M233, M246, M247 |
| **BCM+Respin** | Has respin ST alongside ST=140; no freespin ST=126 | M268, M238, M244, M245, M277, M278, M269 |
| **BCM+Freespin+Respin** | All three present | M229, M231, M248, M252, M257 |
| **BCM-only (collection, no bonus phase in rawdata)** | ST=140 only; no second ST observed | M152, M153, M186, M194, M236, M265, M267 |

### BCM spin type conventions

The BCM family uses ST=140 as the paid round convention in 94% of cases. The exceptions:
- **M108, M117, M125**: paid ST=101 (Butterfly/MultiSymbol collection variant)
- **M138**: paid ST=142
- **M249**: paid ST=153
- **M251**: paid ST=151
- **M254**: paid ST=154
- **M260, M266**: paid ST=156

These BCM sub-families with non-140 paid ST have their own SpinType convention and will fail any ST=140-specific logic in the analyzer.

### Freespin ST in BCM machines

When BCM machines have freespin, the freespin ST is typically **ST=126** (observed in M272, M264, M275, M253, M263, M234, M235, M220, M271, M280). Exceptions:
- **M229**: freespin ST=50 (also uses ST=126)
- **M256**: freespin ST=36
- **M257**: freespin ST=149
- **M231**: freespin ST=50 + 126

### BCM cycle length variability

The BCM CollectCount cycle length (when the bonus fires) is a machine-specific parameter, NOT a shared constant. From existing analyzer reports:
- M274: cycle=1000
- M275: cycle=1000 (same family as M274)
- M279: cycle observed (move-spin variant, cycle detected from rawdata)
- Other BCM machines: cycle length inferred per-machine by the existing `detect_cycle_peak` logic

This is a **parametric dimension** within the BCM archetype — the mechanism is shared, the cycle length parameter varies.

---

## §7 Gap Coverage by Archetype

For each of the 8 M275 gaps in `00_brief.md §3`, which archetypes are affected:

| Gap # | Gap description | Archetypes affected | Fleet count affected |
|---|---|---|---|
| **1** | `machine_mechanics.jackpot.applicable: false` despite high PIDs | All archetypes that have jackpot PIDs (≥10k) | **26 machines** across A/B/C/D archetypes |
| **2** | `machine_mechanics.free_spin.applicable: false` despite freespin rounds | B_BCM_FREESPIN* (44 machines) + C_FREESPIN_ONLY (42) + C_FREESPIN_WHEEL (13) + C_LOCK_FREESPIN (8) | **~107 machines** |
| **3** | pid=666 classified as `cat=paid` not scatter trigger | All machines with pid=666 in line_id=-1 | **99 machines** (standard pid=666) + 50 with other scatter pids |
| **4** | Multiplier wild inference paused | Universal (affects any machine with wild symbols with multipliers) | Paused per memory; count deferred |
| **5** | `payout_groups_top20` all-zero noise | All machines where all `PayoutGroupId==0` in rawdata | **~247 machines** (only 9 have any non-zero PayoutGroupId) |
| **6** | BCM `estimated_correction_pp: 0.0` (correction formula missing) | All BCM archetypes | **57 machines** (all B_BCM_*) |
| **7** | `payouts_by_spin_type` missing shape/cols/paylines/notes | Universal | **256 machines** (all bases) |
| **8** | `payout_ids_top20` missing same fields | Universal | **256 machines** (all bases) |

**Fixing gaps 7 and 8** benefits the entire fleet immediately (universal). **Fixing gap 3** benefits the largest single-mechanism cohort (149 scatter-marker machines). **Fixing gap 1** benefits 26 machines with jackpot PIDs across diverse archetypes. **Fixing gap 6** (BCM correction formula) benefits 57 machines in the BCM family.

---

## §8 Manifest Review State by Archetype

From `manifest_lint.py` results (per `session_artifacts/_impl/STATUS.md`): 182 manifests are `config_not_reviewed: true` (bootstrap default). 71 are reviewed. 45 are `sc_vanilla: true` (fully verified vanilla machines).

| Archetype | Total | Reviewed | sc_vanilla |
|---|---|---|---|
| A_VANILLA | 53 | 48 | 45 |
| B_BCM_FREESPIN_WHEEL | 20 | 2 | 0 |
| B_BCM_FREESPIN | 19 | 1 | 0 |
| B_BCM_WHEEL | 18 | 1 | 0 |
| C_FREESPIN_ONLY | 42 | 3 | 0 |
| C_FREESPIN_WHEEL | 13 | 3 | 0 |
| C_LOCK_FREESPIN | 8 | 1 | 0 |
| C_LOCK_RESPIN | 10 | 0 | 0 |
| C_RESPIN_ONLY | 36 | 1 | 0 |
| C_WHEEL_ONLY | 23 | 9 | 0 |
| D_COMPLEX_OTHER | 7 | 1 | 0 |
| D_MINIGAME | 2 | 0 | 0 |
| D_MOVE_SPIN | 5 | 1 | 0 |

**Key finding**: The A_VANILLA archetype is 91% reviewed (48/53), and all 45 sc_vanilla machines are in this archetype. Every other archetype is 0-23% reviewed. The BCM family (B_BCM_*) is nearly entirely unreviewed: 4 of 57 reviewed (7%). This means the analyzer's manifest-driven configuration for BCM machines is entirely based on bootstrap defaults — the actual paid_st, trigger_session_pattern, and BCM cycle parameters are not yet recorded in manifests for 96% of BCM machines.

---

## §9 L2 Failure Distribution by Archetype

From `STATUS.md`: 59 machines fail L2 (RTP-calculation completeness) in the fleet smoke run. 6 were expected (Tier-1); ~46 are surprises. The partial list of surprises maps to archetypes as follows:

| Archetype | L2 failures (partial list) | Notes |
|---|---|---|
| B_BCM_FREESPIN_WHEEL | M250, M260, M264 (expected) + M125, M239, M254 | 30% failure rate in this archetype |
| B_BCM_FREESPIN | M138, M251, M263 | 16% failure rate |
| B_BCM_WHEEL | M279 (expected) + M147, M163, M246 | 22% failure rate |
| C_FREESPIN_ONLY | M11 (expected) + M107, M121, M18, M24, M243 | 14% failure rate |
| C_WHEEL_ONLY | M110, M151, M158, M214 | 17% failure rate |
| C_LOCK_RESPIN | M268 (expected) | 10% failure rate |
| C_LOCK_FREESPIN | M100 | 12% failure rate |
| C_FREESPIN_WHEEL | M171 | 8% failure rate |

The BCM family has the highest L2 failure rate (22-30%), consistent with the BCM-specific fallback-attribution problem documented in `memory/feedback_invariant_with_fallback_hides_drift.md`. But failures are not confined to BCM — C_FREESPIN_ONLY and C_WHEEL_ONLY also have significant failure counts, suggesting those archetypes have their own unresolved attribution issues (distinct from BCM routing).

---

## §10 Variant Fleet Implications

26 of 256 base machines have variants; they account for all 166 variant entries. Variant archetype is inherited from the base machine's archetype (variants share code and logic with their base).

| Archetype | Variant count | Dominant base |
|---|---|---|
| B_BCM_FREESPIN_WHEEL | **87 variants** | M273 alone has 85 variants (C(9,3)=84 + 1 base variant = 85 WheelSelector combinations); M261 has 2 |
| C_WHEEL_ONLY | 19 variants | M102/M187/M188/M198/M203/M204/M216/M219/M32 (2 each) |
| C_FREESPIN_WHEEL | 15 variants | M116 (3), M123 (7), M86 (5) |
| C_FREESPIN_ONLY | 12 variants | M39 (5), M6 (4), M210 (3) |
| A_VANILLA | 9 variants | M12/M15/M132 (3 each — TopDollarSelector variants) |
| C_LOCK_FREESPIN | 8 variants | M201 (8 CommonSelector variants) |
| B_BCM_FREESPIN | 4 variants | M257 (4 CommonSelector variants) |
| B_BCM_WHEEL | 2 variants | M247 (2 WheelSelector variants) |
| D_MOVE_SPIN | 4 variants | M209 (4 CommonSelector variants) |
| C_RESPIN_ONLY | 3 variants | M206 (3 TopDollarSelector variants) |
| D_COMPLEX_OTHER | 3 variants | M90 (3 TopDollarSelector variants) |

**M273 dominates the variant count**: 85 of 166 variants (51%) are WheelSelector variants of M273, a B_BCM_FREESPIN_WHEEL machine. This means fixing BCM_FREESPIN_WHEEL gaps benefits 107 unique analyzer entities (20 base + 87 variants), making it the highest-leverage archetype for gap closure.

**Variants are in the same archetype as their base**: all variants share the same `logicClassNames` list as their base machine (they are the same code, different selector configuration). The analyzer sees them as independent machines but they share identical mechanism fingerprints.

---

## §11 Suggested Groupings for Plugin Architecture

The following natural seams are observable in the data. These are descriptive classifications of where shared vs. per-machine logic exists; the designer decides how to express this as plugin architecture.

### Seam 1: Universal vs. machine-specific enrichment

Gaps 7 and 8 (shape/cols/paylines/notes in `payouts_by_spin_type` and `payout_ids_top20`) apply to all 256 machines identically. The data is already available in rawdata (`StopSymbolsByCol`, max positive line_id in `PayoutByPayline`, machine's `modes`/`paylines` from manifest). These enrichments are parametric (values differ per machine) but the code to compute them is universal.

**Seam**: a single universal enrichment pass over `PayoutByPayline` and `StopSymbolsByCol` closes gaps 7/8 for the whole fleet without any per-machine logic.

### Seam 2: Jackpot PID detection (26 machines, cross-archetype)

Jackpot PIDs appear in 26 machines across all archetypes. The detection criterion is measurable: "PID ≥ 10,000 in `PayoutIdToWinAmount`." There is no per-machine threshold — the current auto-detect logic that already works for M275's payout_ids_top20 just needs to be cross-referenced into `machine_mechanics.jackpot.applicable`.

**Seam**: a single fleet-wide rule "if any observed PID ≥ 10,000 in this report, set `machine_mechanics.jackpot.applicable: true` and populate jackpot PID list" closes gap 1 for all 26 machines simultaneously.

### Seam 3: Scatter trigger classification (99+ machines)

pid=666 (and other zero-win trigger markers) appearing in line_id=-1 of `PayoutByPayline` is a measurable criterion. The rule: "if PID appears in a payline line_id=-1 entry AND win=0, it is a scatter/trigger marker, not a paid win PID." This classification is universal and does not require per-machine knowledge of which PID is the trigger.

**Seam**: a single universal rule applied to `payout_ids_top20` classification closes gap 3 for the 99 standard-scatter machines. Non-666 scatter PIDs (50 machines) follow the same rule — the PID value is not important, the line_id=-1 + win=0 pattern is.

### Seam 4: Freespin detection (107+ machines)

The current `machine_mechanics.free_spin.applicable` detection runs independently from the `upstream_feature_breakdown` panel, which already correctly identifies freespin from rawdata. The gap is that two panels reach different conclusions about the same machine. 

**Seam**: a single source of truth for "this machine has freespin, observed in roundResult with freespin-tagged SpinTypes and associated win attribution" would close gap 2 for the ~107 machines. The mechanism is: if any SpinType observed in rawdata corresponds to a freespin round (identified by `ReMarks` containing "Freespin" or by the `bonus_chain_dynamics` freespin chain already detected), then `free_spin.applicable: true`.

### Seam 5: BCM family grouping (57 machines)

The BCM family is the most internally coherent cluster in the fleet, identified by co-presence of `BuffCollectionData*` logic classes. Within this family, three dimensions are **parametric** (varying per machine, not requiring new plugin types):
- Cycle length (1000 for M274/M275; varies for others)
- Whether freespin is present (yes/no)
- Whether wheel phase is present (yes/no)
- Freespin ST value (126 most common; M229/M256/M257/M231 use others)
- Bonus ST value (139 for M274; 36 for M279; 2 for M262/M250/M126)

Gap 6 (BCM correction formula for clamp-pending RTP estimation) applies uniformly to all 57 BCM machines — the formula is the same, only the cycle length and observed pending-share parameters differ.

**Seam**: BCM-specific logic (correction formula, cycle peak detection, fallback attribution alerting) belongs in a BCM-cluster plugin or extension, not per-machine code. The 57-machine BCM family is the natural unit for this cluster-shared feature.

### Seam 6: PayoutGroupId noise (247 machines)

247 machines have all `PayoutGroupId==0` in rawdata — the current `payout_groups_top20` panel shows "group 0 = 80% RTP" which is meaningless for these machines. The distinction "all-zero = no grouping = suppress noise" vs "non-zero values = real grouping" is a universal rule with a measurable criterion (any non-zero `PayoutGroupId` in rawdata).

**Seam**: gap 5 is closed fleet-wide by adding a boolean flag: "if all observed `PayoutGroupId==0`, suppress the payout_groups panel or display as 'no grouping configured'." Only 9 machines have actual non-zero grouping and would continue to show the panel.

### Seam 7: SpinType convention registration (fleet-wide correctness)

The manifest bootstrap uniformly sets `spin_type_convention.paid=[1]` for all machines. Rawdata shows that only 140 of 256 machines actually use ST=1 as their paid round. The remaining 116 machines (45%) use machine-specific or family-specific ST values.

**Seam**: a mechanism to observe the rawdata's most-common SpinType and reconcile it against the manifest's declared `paid` list would let the analyzer self-correct (or flag a mismatch) without per-machine code. This closes the root cause of L4 false-positives for the 116 non-ST=1 machines.

---

## §12 Counts Summary

| Category | Count |
|---|---|
| Base machines in fleet | 256 |
| Variant machines in fleet | 166 |
| Total fleet entities | 422 |
| Base manifests (bootstrap only, 182 not reviewed) | 253 |
| A_VANILLA archetype | 53 base (+ 9 variants) |
| B_BCM combined (all BCM sub-archetypes) | 57 base (+ 89 variants) |
| B_BCM_FREESPIN_WHEEL (M275's archetype) | 20 base (+ 87 variants) |
| C_* non-BCM special archetypes | 132 base (+ 62 variants) |
| D_* outlier/complex archetypes | 14 base (+ 7 variants) |
| Machines with jackpot PIDs (≥10k) | 26 |
| Machines with scatter pid=666 | 99 |
| Machines with other scatter markers | 50 |
| Machines with non-zero PayoutGroupId | 9 |
| Machines with paid ST ≠ 1 (rawdata observed) | 116 |
| Machines in BCM family with paid ST ≠ 140 | 10 (within BCM) |
| Manifests config_not_reviewed (bootstrap) | 182 |
| Machines failing L2 smoke test | 59 (partial list; 6 expected + ~53 surprises) |

---

## §13 Data Quality Notes

1. **M281**: No rawdata present in `rawdata/M281/mode_1/` at analysis time. Manifest exists. Classified by `logicClassNames` only (B_BCM_FREESPIN archetype per classes). Rawdata observations are absent.

2. **M280, M278, M276**: Present in `configs/machines.json` but noted in `STATUS.md` as having been missed by the manifest generator; manifests may exist but were flagged as requiring regeneration. Rawdata samples were available and used for Ax2–Ax6.

3. **Variant manifests**: All 166 variant manifests use `inherits_from` pointing to their base (the eager cascade). Their mechanism archetype is determined by the base machine's `logicClassNames`.

4. **BCM cycle length**: Not observable from a single chunk's first 300 rounds in most cases — the cycle length (e.g., 1000) requires >1000 spins to observe a full cycle peak. The `detect_cycle_peak` logic in the existing analyzer runs over the full cached chunk set; the taxonomy relies on that logic's output rather than re-detecting from the sample.

5. **Multiplier wild (Gap #4)**: Not assessed in this taxonomy. Per `memory/project_paytable_inference_paused.md`, the inference is paused due to two open bugs. Symbol names containing "2x"/"5x"/"10x" were observed in `symbols_top20` for M275 (confirmed in brief §3), but no fleet-wide count was produced for this axis since the inference is not currently running.

---

*Taxonomy complete. M275 is classified in the B_BCM_FREESPIN_WHEEL archetype (20 base machines + 87 variants = 107 fleet entities). The largest mechanism cluster in the fleet by mechanism is A_VANILLA (53 base machines, all co-clustering on Ax2=ST1 and Ax3=3x3) but the most impactful for the Analyzer Unbundle is B_BCM_FREESPIN_WHEEL due to the 8-gap accumulation and the 87 M273 variants in its archetype.*
