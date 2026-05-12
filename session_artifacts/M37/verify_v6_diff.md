# Verify v6 diff (extends v5 diff for m2/m5/m7)

> **Stage 5 Verifier output (v6 extension)** per `ONBOARDING_PROCESS.md §4`. Fresh-context derivation of v6 verify red lines from `design_v6.md` (Designer A: m2+m5) + `design_v6_m7.md` (Designer B: m7) + `critic_review_v6.md` (X SHIP verdict). Builds on `verify_v5_diff.md` — **m1 verify lines NOT touched** (v5 ship'd locked).
>
> Output: diff proposal layered on top of v5 diff. Main session applies after this proposal lands.

---

## 0. Scope reminder

- **m1 v5 SHIPPED & LOCKED**: all m1 verify lines from `verify_v5_diff.md` stay as-is.
- **v6 in scope**: m2 (Designer A), m5 (Designer A, MODE5-BASE-LOCK auto), m7 (Designer B, tier 1 ±0.5pp drift).
- **v6 numbers** (from `critic_review_v6.md §1`):
  | Mode | RTP | hit | pid 9 占比 |
  |---|---|---|---|
  | 1 (ship'd) | 94.09 | 20.92 | 20.07% |
  | 2 v6 | 303.45 | 32.21 | **20.37%** |
  | 5 v6 (auto) | 507.56 | 33.09 | **12.02%** |
  | 7 v6 | 85.02 | 15.00 | **19.13%** |
- 2 YELLOW pre-existing v3 inherited (§2 R2 high7 m2/m5 < 8.93 floor; §12 m2/m5 R1 top vs R3 top inversion 0.45pp) — these are NOT v6 regressions, **must NOT be turned into RED by verify**.

---

## 1. Modified MODE_TARGETS (m2 / m5 / m7)

### 1.1 m2 — adjustments

| Field | Current value | v6 new value | Reason |
|---|---|---|---|
| `rtp` / `rtp_tol_pp` | 300.0 / 5.0 (i.e. band [295, 305]) | **same — band [295, 305]** | `design_v6.md §3.3` m2 v6 RTP 303.45 ∈ [295, 305] passes (1.55pp from upper edge). No change needed. `critic_review_v6.md §1` confirms. |
| `hit_lo` / `hit_hi` | 0.30 / 0.36 | **same** | `design_v6.md §3.3` m2 v6 hit 32.21 ∈ [30, 36] passes (3.79pp safety). `critic_review_v6.md §1`. No change. |
| `booster_visible_lo` / `hi` | 0.16 / 0.28 | **same** | m2 v6 booster total = 10.92 + 8.12 + 5.99 + 0.60 = **25.63%** ∈ [16%, 28%] passes. `design_v6.md §3.2` confirms. No change. |
| `grand_lo` / `hi` | 0.0020 / 0.0065 | **same** | m2 v6 grand 0.595% (weight unchanged at 52) — `design_v6.md §3.2` "R2 grand 0.59 → 0.60". 0.595% ∈ [0.20%, 0.65%]. `critic_review_v6.md §4`. No change. |
| `hier_ratio_min` | 1.3 | **1.0** | v6 amendment inherits v5 universal floor 1.0 per `user_brief.md §v5 soft`. `design_v6.md §3.3` HIER ratios 1.345/1.355 both pass 1.0 easily; relaxing the floor to 1.0 makes verify consistent across all modes. |
| `shape_js_max` | 0.10 | **same** | No change needed. |
| **NEW** `pid9_share_lo` / `hi` | (not present) | **10.0 / 22.0** | `critic_review_v6.md §1` "m2 pid 9 share 20.37%" + brief task §1 "m2 PID9-SHARE band [10, 22]%". v3 baseline 22.66% was just above target → v6 lands at 20.37 with 0.63pp safety from 21 ceiling. Lower bound 10 protects against over-cut (m5 lands at 12 with grand override which is natural lucky-mode floor); m2 cut below 10 would mean booster mass annihilated. |

### 1.2 m5 — adjustments

| Field | Current value | v6 new value | Reason |
|---|---|---|---|
| `rtp` / `rtp_tol_pp` | 500.0 / 10.0 (band [490, 510]) | **same** | m5 v6 RTP 507.56 ∈ [490, 510] passes (2.44pp from upper). `design_v6.md §5`. `critic_review_v6.md §1`. No change. |
| `hit_lo` / `hit_hi` | 0.30 / 0.40 | **same** | m5 v6 hit 33.09 ∈ [30, 40] passes (large safety). No change. |
| `booster_visible_lo` / `hi` | 0.16 / 0.28 | **same** | m5 inherits m2 base — booster total similar 25.x%. Passes. No change. |
| `grand_lo` / `hi` | 0.010 / 0.020 | **same** | m5 v6 grand 1.874% ∈ [1.0%, 2.0%]. `design_v6.md §5`. No change. |
| `hier_ratio_min` | 1.3 | **1.0** | Same reasoning as m2 — universal floor 1.0 per v5 amendment. m5 HIER inherits m2 (1.345/1.355). |
| `shape_js_max` | 0.10 | **same** | No change. |
| **NEW** `pid9_share_lo` / `hi` | (not present) | **8.0 / 16.0** | `critic_review_v6.md §1` "m5 pid 9 share 12.02% (auto via m2 base + grand override; huge margin)" + brief task §1 "m5 PID9-SHARE band [8, 16]%". m5 pid9 always low because grand 1.87% dominates pid 1/8 RTP boost while pid 9 (side-wild-alone + booster-alone) is unaffected; m5 v3 baseline ~13.45% per `design_v6.md §5`. Band [8, 16] gives 4pp downward + 4pp upward headroom around 12.02 v6 actual. |

### 1.3 m7 — adjustments

| Field | Current value (from v5 diff) | v6 new value | Reason |
|---|---|---|---|
| `rtp` / `rtp_tol_pp` | 85.0 / 1.0 (band [84, 86]) | **same** | m7 v6 RTP 85.02 ∈ [84, 86] (center). `design_v6_m7.md §5`. No change. |
| `hit_lo` / `hit_hi` | 0.11 / 0.16 (v5 widened from 0.155) | **0.11 / 0.17** | `design_v6_m7.md §5` m7 v6 hit **15.00%** — current v5 band upper 16 still passes with 1pp safety but tight given m7 lever boost (bar ×1.15 + high7 ×1.05) shifts hit upward of v5. **Widening upper to 17%** absorbs forward iteration headroom + future MODE7-LOCK drift drift without burning safety. `critic_review_v6.md §2 row §9` confirms HIT-MONOTONIC 5.92pp safety far above 0.3pp required. Brief task §2 asks "是否需要放宽到 [11, 17]?" — answer **yes**, this is the cleanest fix. |
| `booster_visible_lo` / `hi` | 0.04 / 0.12 (v5 widened) | **same** | m7 v6 booster total = 2.572 + 2.036 + 1.350 + 0.118 = **6.076%** ∈ [4%, 12%] passes (`design_v6_m7.md §5`). Brief task §2 asks "v6 booster post-cut 计算" — actual lands well within current band. No change. |
| `grand_lo` / `hi` | 0.0007 / 0.0016 | **same** | m7 v6 grand 0.1179% ∈ [0.07%, 0.16%] (`design_v6_m7.md §6`). No change. |
| `hier_ratio_min` | 1.0 (from v5) | **same** | m7 v6 HIER ratios mini/minor 1.263, minor/major 1.508 both ≥ 1.0 (`design_v6_m7.md §8`). No change. |
| `shape_js_max` | 0.10 | **same** | No change. |
| `pid9_share_lo` / `hi` | 23.0 / 30.0 (v5 — for v5 baseline 26.29%) | **14.0 / 21.0** | **major revise**. v5 set m7 band [23, 30] to bracket v5 m7 baseline 26.29% — but v6 m7 design CUT pid9 share from 26.29 → 19.13. New band [14, 21] mirrors the m1 pattern (precise red ≤ 21 ceiling) but with 5pp downward headroom (vs m1's 19 lower) because m7 has tier-1 MODE7-LOCK booster drift constraints which couples booster-alone (pid 9 mult 2/5/10 part) to m1 booster levels. Brief task §1 "m7 PID9-SHARE band [14, 21]%, target 19.13". `design_v6_m7.md §5` confirms 19.126%. `critic_review_v6.md §1` confirms ≤21 ceiling held. |

---

## 2. PID9-SHARE per-mode bands (full table)

This is the v6 NEW hard red for cross-mode propagation of v5 user precise red ("pid 9 RTP / total RTP ≤ 21" — now extended to m2/m5/m7).

| Mode | v6 band | v6 actual | Cite | universal §X ref |
|---|---|---|---|---|
| 1 (locked) | [19, 21] | 20.07% | v5 ship'd; `verify_v5_diff.md §2.1` | user precise red (v5 amendment) |
| **2 v6** | **[10, 22]** | **20.37%** | `design_v6.md §3.3` + `critic_review_v6.md §1` | user v5 precise red ≤21 + 1pp band upper headroom; brief task §1 |
| **5 v6** | **[8, 16]** | **12.02%** | `design_v6.md §5` + `critic_review_v6.md §1` | m5 super-lucky pid 9 share structurally low (grand boost shifts RTP to pid 1/8); brief task §1 |
| **7 v6** | **[14, 21]** | **19.13%** | `design_v6_m7.md §5` + `critic_review_v6.md §1` | user v5 precise red ≤21 + 5pp downward headroom (MODE7-LOCK tier 1 coupling); brief task §1 |

### Per-band rationale

**m2 band [10, 22]**:
- **Upper 22%**: User v5 precise red is ≤21%. Band upper 22 gives 1pp tolerance above ceiling because the verify is the *check*, not the design target; if a future iteration nudges m2 pid9 share to 21.5, that's an "above design target" warning but not a hard red break — the user-stated red is 21, and we honor the precise red intent while allowing the verify to fire RED at 22 (1pp tolerance for measurement drift / per-stage noise). v3 baseline 22.66% was above this, intentionally — v6 design moved to 20.37% which lands cleanly in band.
- **Lower 10%**: protects against over-cut. m2 booster total ~26% (lucky mode) → pid 9 (booster-alone + side-wild-alone) is structurally bounded ~10-23% RTP share at baseline. Floor 10 prevents future iteration from accidentally annihilating the booster-alone path (would mean R2 booster weights cut so deeply that pid 9 < pid 6 — narrative breaks lucky-mode "booster reveal cadence").
- **Why wider than m1 (m1 was [19, 21])**: m1 is the user-pinned target mode; m2/m5/m7 are propagation modes — Designer A explicitly says (`design_v6.md §1`) "small change, don't blow up archetype" → verify should reflect that m2 is *propagation* not *primary target*, allowing more iteration tolerance.

**m5 band [8, 16]**:
- **m5 is structurally bounded lower than m2**. `design_v6.md §5` reports m5 baseline 13.45% → v6 12.02%. Reason: m5 inherits m2's R2 booster weights but multiplies R2 grand weight ×3.2 (52→166), which boosts pid 1 (3-high7 × grand mult 100) RTP from m2's ~36 → m5 ~58, and pid 7 / pid 8 similarly. Total RTP rises faster than pid 9 RTP (pid 9 doesn't benefit from grand boost directly) → pid 9 share is structurally lower.
- **Upper 16%**: gives 4pp upward headroom above v6 12.02 actual; v3 baseline was 13.45 so historical drift envelope is [12, 14] — band 16 absorbs +2pp future drift.
- **Lower 8%**: 4pp downward headroom. If m5 ever needs deeper booster cut (super-lucky shifts more aggressively), 8 is a soft floor; below 8 means booster-alone path almost gone.

**m7 band [14, 21]**:
- **Upper 21%**: User v5 precise red ≤21 ceiling. m7 v6 19.13 sits with 1.87pp safety. m7 verify must enforce the user-pinned ceiling because m7 has the same conceptual relation as m1 to the user (single-mode pid9 share target).
- **Lower 14%**: 5pp downward headroom from v6 19.13 actual. m7 has tighter coupling than m2 because MODE7-LOCK tier 1 (±0.5pp drift from m1 booster levels) bounds how aggressively m7 booster can be cut — if m7 booster cuts further, drift breaks tier 1. So m7 pid 9 share is structurally bounded ~14-20% (cannot easily go below 14 without breaking MODE7-LOCK).
- **Why narrower than m1 (m1 [19, 21])**: m7 v6 lands at 19.13 *because* design B picked the candidate with min L1 deviation from m7 baseline; future iterations might land lower with more aggressive booster cut. m1 hit physics floor 20.24 (per v5 design) constrained the band; m7 has no equivalent floor — booster cut deeper is feasible. So m7 band has more downward room.

---

## 3. Expected verify output on v6 m1+m2+m5+m7

Predicted output of `python -m slot_designer.scripts.verify_m37_design` against the v6 weight set (m1 v5 ship'd + m2/m5/m7 v6 from `session_artifacts/M37/v6_sim_weights/`):

```
=== M37 design verification ===

Strip-level (mode-independent):
  GREEN  [ALTERNATION]         all 3 reels strict B/N alternation (0 violations)
  GREEN  [BLANK-FLANK-DIVERSITY] no X-Blank-X anywhere (0 violations)
  GREEN  [REROLL-VERIFY]       (wild, grand, wild) in spec.reroll_blocks

Mode 1 (v5 SHIP'd, unchanged):
  RTP 94.090%  hit 20.920%  CV ~9.50
  GREEN  [RTP]                 mode 1 RTP 94.090% ∈ [94.0, 96.0]
  GREEN  [HIT]                 mode 1 hit 20.920% ∈ [14.0%, 22.0%]
  GREEN  [PID9-SHARE]          mode 1 pid9 20.07% ∈ [19.0%, 21.0%]
  GREEN  [BUCKET-CAP]          mode 1 ge5000 = 0
  GREEN  [BUCKET-SHAPE]        JS divergence ~0.07 ≤ 0.10
  YELLOW [BUCKET-GE1_5]        mode 1 ge1_lt5 RTP-pp 21.21 ∈ [18, 24] (informational)
  GREEN  [BOOSTER-R1R3-EMPTY]
  GREEN  [WILD-R2-EMPTY]
  GREEN  [BOOSTER-HIER]        mini/minor=1.40x, minor/major=1.31x
  GREEN  [BOOSTER-VISIBLE]     R2 booster total 6.41% ∈ [4%, 10%]
  GREEN  [GRAND-SIGNATURE]     R2 grand 0.1120% ∈ [0.07%, 0.16%]
  GREEN  [REEL-ASYMMETRY]      R1=20.98, R3=21.91, R2=50.23; top-prize R1=19.64, R3=18.66
  GREEN  [TOP-PATH-1000X]      8 combos pay_id 1
  GREEN  [TOP-PATH-1000X-FREQ] 1 in 24,494
  GREEN  [ARCHETYPE-HIGH7]
  GREEN  [ARCHETYPE-BAR]
  GREEN  [ARCHETYPE-WILD]
  GREEN  [WINDOW-VISIBILITY] × 3
  GREEN  [WINDOW-VISIBILITY-CAP]
  GREEN  [BLANK-RATIO-CAP]
  GREEN  [MID-PAY-VISIBLE-FLOOR]

Mode 2 (v6):
  RTP 303.45%  hit 32.21%  CV ~6
  GREEN  [RTP]                 mode 2 RTP 303.450% ∈ [295.0, 305.0]
  GREEN  [HIT]                 mode 2 hit 32.210% ∈ [30%, 36%]
  GREEN  [PID9-SHARE]          mode 2 pid9 20.37% ∈ [10%, 22%]   ← NEW v6
  GREEN  [BUCKET-CAP]          mode 2 ge5000 = 0
  GREEN  [BOOSTER-R1R3-EMPTY]
  GREEN  [WILD-R2-EMPTY]
  GREEN  [BOOSTER-HIER]        mini/minor=1.345x, minor/major=1.355x (≥ 1.0)
  GREEN  [BOOSTER-VISIBLE]     R2 booster total ~25.63% ∈ [16%, 28%]
  GREEN  [GRAND-SIGNATURE]     R2 grand 0.595% ∈ [0.20%, 0.65%]
  GREEN  [REEL-ASYMMETRY]      blanks ok; top-prize R1=13.49 < R3=13.94 by 0.45pp → fires WARN if ≥0.5pp slack; actually within 0.5pp slack → GREEN
                               (NOTE: pre-existing v3 finalized inversion — DESIGN.md §3.4 TODO; passes 0.5pp slack)
  GREEN  [TOP-PATH-1000X]
  GREEN  [WINDOW-VISIBILITY] × 3 (mode 2 bands [10%, 45%] / [15%, 40%] / [5%, 35%])
  GREEN  [WINDOW-VISIBILITY-CAP]
  GREEN  [BLANK-RATIO-CAP]
  GREEN  [MID-PAY-VISIBLE-FLOOR]

Mode 5 (v6 — MODE5-BASE-LOCK auto):
  RTP 507.56%  hit 33.09%  CV ~6
  GREEN  [RTP]                 mode 5 RTP 507.560% ∈ [490.0, 510.0]
  GREEN  [HIT]                 mode 5 hit 33.090% ∈ [30%, 40%]
  GREEN  [PID9-SHARE]          mode 5 pid9 12.02% ∈ [8%, 16%]    ← NEW v6
  GREEN  [BUCKET-CAP]
  GREEN  [BOOSTER-R1R3-EMPTY]
  GREEN  [WILD-R2-EMPTY]
  GREEN  [BOOSTER-HIER]        inherit m2 (≥1.0)
  GREEN  [BOOSTER-VISIBLE]     ~24.7% ∈ [16%, 28%]
  GREEN  [GRAND-SIGNATURE]     R2 grand 1.874% ∈ [1.0%, 2.0%]
  GREEN  [REEL-ASYMMETRY]      same as m2 (inherit; 0.45pp inversion within 0.5pp slack)
  GREEN  [TOP-PATH-1000X]
  GREEN  [WINDOW-VISIBILITY] × 3
  GREEN  [WINDOW-VISIBILITY-CAP]
  GREEN  [BLANK-RATIO-CAP]
  GREEN  [MID-PAY-VISIBLE-FLOOR]

Mode 7 (v6):
  RTP 85.021%  hit 14.996%  CV 11.308
  GREEN  [RTP]                 mode 7 RTP 85.021% ∈ [84.0, 86.0]
  GREEN  [HIT]                 mode 7 hit 14.996% ∈ [11%, 17%]   ← v6 upper widened from 16
  GREEN  [PID9-SHARE]          mode 7 pid9 19.13% ∈ [14%, 21%]   ← v6 band revised
  GREEN  [BUCKET-CAP]
  GREEN  [BOOSTER-R1R3-EMPTY]
  GREEN  [WILD-R2-EMPTY]
  GREEN  [BOOSTER-HIER]        mini/minor=1.263x, minor/major=1.508x (≥ 1.0)
  GREEN  [BOOSTER-VISIBLE]     R2 booster total 6.08% ∈ [4%, 12%]
  GREEN  [GRAND-SIGNATURE]     R2 grand 0.1179% ∈ [0.07%, 0.16%]
  GREEN  [REEL-ASYMMETRY]      R1=16.74, R3=17.73, R2=69.81; top-prize R1=19.28 ≥ R3=18.30
  GREEN  [TOP-PATH-1000X]
  GREEN  [TOP-PATH-1000X-FREQ] mode 7 1 in ~24k ∈ [15k, 50k]
  GREEN  [ARCHETYPE-HIGH7]     R1=18.12 / R2=10.18 / R3=17.13 (all in ±30%)
  GREEN  [ARCHETYPE-BAR]       all bar tiers in ±25% (m7 baseline-anchored)
  GREEN  [ARCHETYPE-WILD]      R1=1.158 / R3=1.169 (unchanged, in ±30%)
  GREEN  [WINDOW-VISIBILITY] × 3
  GREEN  [WINDOW-VISIBILITY-CAP]
  GREEN  [BLANK-RATIO-CAP]
  GREEN  [MID-PAY-VISIBLE-FLOOR]

Cross-mode invariants:
  GREEN  [MODE7-LOCK]          R2 mini m1 2.786 / m7 2.572 (drift 0.214pp ≤ 0.5pp tier 1)
  GREEN  [MODE7-LOCK]          R2 minor m1 1.993 / m7 2.036 (drift 0.043pp ≤ 0.5pp)
  GREEN  [MODE7-LOCK]          R2 major m1 1.525 / m7 1.350 (drift 0.175pp ≤ 0.5pp)
  GREEN  [MODE7-LOCK]          R2 grand m1 0.1119 / m7 0.1179 (drift 0.006pp ≤ 0.5pp)
  GREEN  [MODE5-BASE-LOCK]     mode 5 base byte-eq mode 2 (only R2 grand differs)
  GREEN  [RTP-MONOTONIC]       m7 85.0 < m1 94.1 < m2 303.5 < m5 507.6
  GREEN  [HIT-MONOTONIC]       m7 15.0% < m1 20.9% < m2 32.2% ≈ m5 33.1%
  GREEN  [HIT-MONOTONIC-SAFETY] m1 - m7 = 5.92pp ≥ 0.30pp safety floor
  GREEN  [TOP-JACKPOT-ESCALATION] m1 0.112% / m2 0.595% (×5.3) / m5 1.874% (×16.7); m7 ≈ m1

=== Result: N/N GREEN (informational YELLOW: 1 — m1 BUCKET-GE1_5 informational) ===
```

**Predicted total**: all RED categories GREEN across 4 modes. 1 YELLOW informational inherited from v5 (`[BUCKET-GE1_5]` on m1). 0 RED. Verify gate PASSES on the 4-mode set.

**Pre-existing inherited YELLOW NOT promoted to RED** (per `critic_review_v6.md §2` and process improvement backport `critic_review_v6.md §6.2 item 2`):
- m2/m5 `§2 R2 high7 marginal 7.96/7.86% < 8.93 universal floor` — this is `DESIGN.md §3.1.6` v3 finalized lucky-mode state, accepted by user over 5M+ rounds. Verify already does NOT enforce 8.93 floor on m2/m5 (only m1/m7 via `[ARCHETYPE-HIGH7]` R2 band; m2/m5 are exempt by virtue of not being in the `if mode in (1, 7)` check). **No verify change** — pre-existing behavior is correct.
- m2/m5 `§12 R1 (high7+wild) top vs R3 inversion 0.45pp` — DESIGN.md §3.4 open TODO. v3 baseline already had this. `check_reel_asymmetry` uses 0.5pp slack (`top_R1 + 0.005 < top_R3`) → 0.45pp passes (does NOT fire RED). **No verify change** — slack designed to absorb this baseline state.

---

## 4. TDD inject tests added (extends §4 of v5 diff)

Per `WORKFLOW §1.5` "inject bug → red → revert → green" gate. Three new per-mode `[PID9-SHARE]` injection tests + one `[HIT]` m7 upper-band test.

| Test ID | Category | Inject (delta to v6 weights) | Expected RED | Revert | Expected GREEN |
|---|---|---|---|---|---|
| v6-T1 | `[PID9-SHARE]` m2 | mode 2: R2 mini weight ×1.20 (boost mini → pid9 share climbs back toward 23%+) | `[PID9-SHARE] mode 2 pid9 23.50% NOT in [10%, 22%]` | restore mini=955 | `[PID9-SHARE] mode 2 pid9 20.37% ∈ [10%, 22%]` |
| v6-T2 | `[PID9-SHARE]` m2 (lower) | mode 2: cut R2 mini/minor/major weights all ×0.10 (booster-alone path nearly annihilated → pid9 share drops below 10%) | `[PID9-SHARE] mode 2 pid9 6.80% NOT in [10%, 22%]` | restore booster weights | `[PID9-SHARE] mode 2 pid9 20.37% ∈ [10%, 22%]` |
| v6-T3 | `[PID9-SHARE]` m5 | mode 5: R2 mini weight ×2.0 (boost booster — m5 pid9 share climbs above 16) | `[PID9-SHARE] mode 5 pid9 18.5% NOT in [8%, 16%]` | restore m5 mini=955 | `[PID9-SHARE] mode 5 pid9 12.02% ∈ [8%, 16%]` |
| v6-T4 | `[PID9-SHARE]` m5 (lower) | mode 5: R2 mini/minor/major ×0.15 (annihilate booster path) | `[PID9-SHARE] mode 5 pid9 5.0% NOT in [8%, 16%]` | restore | `[PID9-SHARE] mode 5 pid9 12.02% ∈ [8%, 16%]` |
| v6-T5 | `[PID9-SHARE]` m7 | mode 7: R2 minor weight ×2.0 (boost minor → pid9 share climbs above 21) | `[PID9-SHARE] mode 7 pid9 24.50% NOT in [14%, 21%]` | restore m7 minor=190 | `[PID9-SHARE] mode 7 pid9 19.13% ∈ [14%, 21%]` |
| v6-T6 | `[PID9-SHARE]` m7 (lower) | mode 7: cut R2 mini ×0.30 + boost R1 high7 weight ×1.5 (cut booster, RTP comp via high7 → pid9 share drops below 14) | `[PID9-SHARE] mode 7 pid9 11.80% NOT in [14%, 21%]` | restore | `[PID9-SHARE] mode 7 pid9 19.13% ∈ [14%, 21%]` |
| v6-T7 | `[HIT]` m7 upper band | mode 7: R1+R3 bar all positions ×1.40 (push hit above 17%) | `[HIT] mode 7 hit 18.50% NOT in [11%, 17%]` | restore bar weights | `[HIT] mode 7 hit 14.996% ∈ [11%, 17%]` |
| v6-T8 | `[BOOSTER-HIER]` m2 ratio 1.0 floor | mode 2: swap R2 mini and R2 minor weights (mini=710, minor=955 → ratio mini/minor = 0.74 < 1.0) | `[BOOSTER-HIER] violations: mini/minor 0.74x (need ≥ 1.0x with hi > lo)` | revert swap | `[BOOSTER-HIER] mini/minor=1.345x, minor/major=1.355x` |
| v6-T9 | `[MODE7-LOCK]` tier 1 | mode 7: R2 mini × 0.5 (drift to 1.29% — diff from m1 2.79% by 1.50pp, exceeds 0.5pp tier 1) | `[MODE7-LOCK] R2 mini drift 1.50pp > 0.5pp tolerance` | restore mini=240 | `[MODE7-LOCK] R2 mini drift 0.214pp ≤ 0.5pp` |

**Inject-test harness location**: `slot_designer/tests/test_verify_m37_v6_red_lines.py` (or append to the v5 test file `test_verify_m37_v5_red_lines.py` — recommended **append** so the file is the single source of truth for the verify regression gate).

**Test structure** (Python parametrized):
```python
import json, copy, pytest
from pathlib import Path
from slot_designer.scripts.verify_m37_design import check_pid9_share, check_hit, MODE_TARGETS
# ... load v6 weights from session_artifacts/M37/v6_sim_weights/mode_{N}/weights.json

@pytest.mark.parametrize("test_id,mode,weight_mutation,expected_red_substr", [
    ("v6-T1", 2, {(1, 5): 955 * 1.20},  "pid9 23"),
    ("v6-T2", 2, {(1, 5): 95, (1, 11): 71, (1, 17): 52}, "pid9 6"),
    # ...
])
def test_v6_injection(test_id, mode, weight_mutation, expected_red_substr):
    # 1. Load v6 weights, build engine, run check → assert GREEN
    # 2. Apply weight_mutation in memory, rebuild engine, run check → assert RED matching expected_red_substr
    # 3. Revert mutation, rebuild engine, run check → assert GREEN restored
```

This is the "inject → red → revert → green" 3-step pattern `memory/feedback_integration_test_argv.md` requires.

---

## 5. Python diff (extends verify_v5_diff.md §6)

Unified diff layered on top of `verify_v5_diff.md §6`. Sections that v5 diff already changed are NOT re-listed; v6 only adds per-mode `pid9_share_lo/hi`, updates m7 `hit_hi`, and adjusts `hier_ratio_min` on m2/m5 for consistency.

```diff
--- a/slot_designer/scripts/verify_m37_design.py  (after v5 diff applied)
+++ b/slot_designer/scripts/verify_m37_design.py  (with v6 diff layered)
@@ -7,21 +7,29 @@ All red lines must be green before "done".
 
 Categories (4 modes verified — see check_hit per-mode bands at lines 60-100):
   [RTP]                  mode 1 RTP ∈ [94%, 96%] (m2/m5/m7 see ts dict)
   [HIT]                  mode 1 hit ∈ [14%, 22%] (v5 Option A relax — physics floor 20.24%)
-                         m7 [11, 16%] / m2 [30, 36%] / m5 [30, 38%]
+                         m7 [11, 17%] / m2 [30, 36%] / m5 [30, 40%]   (v6: m7 upper widened for bar +15% lift)
   [HIT-MONOTONIC-SAFETY] m1.hit - m7.hit ≥ 0.30pp (universal §9 hard red)
-  [PID9-SHARE]           mode 1 pid 9 RTP / total RTP ∈ [19%, 21%] (v5 user precise red)
-                         mode 7 pid9 share ∈ [23%, 30%]
+  [PID9-SHARE]           mode 1 pid 9 RTP / total RTP ∈ [19%, 21%] (v5 user precise red)
+                         mode 2 pid9 share ∈ [10%, 22%]    (v6 — Designer A propagation)
+                         mode 5 pid9 share ∈ [8%, 16%]     (v6 — m5 super-lucky structurally low)
+                         mode 7 pid9 share ∈ [14%, 21%]    (v6 — Designer B tier 1, was [23%, 30%] in v5)
   [BUCKET-CAP]           ge5000 bucket = 0 (paytable max-payout invariant)
   ... (rest of header unchanged)
@@ -71,12 +79,14 @@ MODE_TARGETS = {
         "rtp": 95.0, "rtp_tol_pp": 1.0,
         "hit_lo": 0.14, "hit_hi": 0.22,
         "booster_visible_lo": 0.04, "booster_visible_hi": 0.10,
         "grand_lo": 0.0007, "grand_hi": 0.0016,
         "hier_ratio_min": 1.0,
         "shape_js_max": 0.10,
         "pid9_share_lo": 19.0, "pid9_share_hi": 21.0,
     },
     2: {  # 2026-05-07 v5: BALANCED-BARS archetype (user-accepted re-balance from v4 imbalance)
-        # v4 had bars 30/28/5.7/4.4 — ratio 6.6× (1bar/2bar dominated)...
+        # 2026-05-12 v6: small adjust per design_v6.md §3 (Designer A) — booster ×0.98 / wild ×0.92 / bar ×1.05.
+        # m2 v6 RTP 303.45 / hit 32.21 / pid9_share 20.37%. Critic SHIP critic_review_v6.md.
+        # hier_ratio_min relaxed 1.3 → 1.0 (universal floor per v5 amendment); m2 actual 1.345/1.355.
         "rtp": 300.0, "rtp_tol_pp": 5.0,
         "hit_lo": 0.30, "hit_hi": 0.36,
         "booster_visible_lo": 0.16, "booster_visible_hi": 0.28,
         "grand_lo": 0.0020, "grand_hi": 0.0065,
-        "hier_ratio_min": 1.3,
+        "hier_ratio_min": 1.0,   # v6: universal floor (v5 amendment) — m2 actual 1.345/1.355.
         "shape_js_max": 0.10,
+        "pid9_share_lo": 10.0, "pid9_share_hi": 22.0,   # v6 — design_v6.md §3.3; user v5 precise red ≤21 + 1pp band tol.
     },
     5: {  # super-lucky derived from mode 2 v5 — tracks balanced-bars archetype.
+        # 2026-05-12 v6: m5 auto-inherit m2 v6 base + R2 grand override (52→166) per MODE5-BASE-LOCK.
+        # m5 v6 RTP 507.56 / hit 33.09 / pid9_share 12.02%. design_v6.md §5.
         "rtp": 500.0, "rtp_tol_pp": 10.0,
         "hit_lo": 0.30, "hit_hi": 0.40,
         "booster_visible_lo": 0.16, "booster_visible_hi": 0.28,
         "grand_lo": 0.010, "grand_hi": 0.020,
-        "hier_ratio_min": 1.3,
+        "hier_ratio_min": 1.0,   # v6: inherit m2.
         "shape_js_max": 0.10,
+        "pid9_share_lo": 8.0, "pid9_share_hi": 16.0,    # v6 — design_v6.md §5; m5 super-lucky structurally low.
     },
     7: {  # cut mode, derived from mode 1
+        # 2026-05-12 v6: Designer B m7 MODE7-LOCK tier 1 (±0.5pp drift, no escalation).
+        # m7 v6 RTP 85.02 / hit 15.00 / pid9_share 19.13%. design_v6_m7.md §5+§6. Critic SHIP.
         "rtp": 85.0, "rtp_tol_pp": 1.0,
-        "hit_lo": 0.11, "hit_hi": 0.16,
+        "hit_lo": 0.11, "hit_hi": 0.17,  # v6: widened upper 0.16 → 0.17 (m7 v6 hit 15.00, bar ×1.15 lift)
         "booster_visible_lo": 0.04, "booster_visible_hi": 0.12,
         "grand_lo": 0.0007, "grand_hi": 0.0016,
         "hier_ratio_min": 1.0,
         "shape_js_max": 0.10,
-        "pid9_share_lo": 23.0, "pid9_share_hi": 30.0,
+        "pid9_share_lo": 14.0, "pid9_share_hi": 21.0,   # v6 revised — design_v6_m7.md §5: m7 v6 pid9_share 19.13% (was 26.29% v5 baseline).
     },
 }
```

**That's the entire v6 diff** — no new check functions needed (the v5 `check_pid9_share` already reads `ts["pid9_share_lo"] / ts["pid9_share_hi"]` per mode). Only `MODE_TARGETS` dict + docstring updates.

**Wiring**: `check_pid9_share` is already called in `main()` per the v5 diff:
```python
ok, msg = check_pid9_share(profile, mode, ts); results.append(ok); print(msg)
```
This runs for **every mode** that has `pid9_share_lo` in its `MODE_TARGETS`. v6 simply adds the keys for modes 2/5/7. The existing `if "pid9_share_lo" not in ts: return True, _ok(...skip...)` guard in `check_pid9_share` becomes unused (all 4 modes have the key), but is harmless to keep as defensive coding.

---

## 6. Process-improvement backport (per critic_review_v6 §6.2)

Out of scope for this verify diff but **noted for main session**:

1. **"Pre-existing inherited YELLOW"** classification (`critic_review_v6.md §6.2 item 2`): m2/m5 §2 R2 high7 < 8.93 floor + §12 R1 top vs R3 inversion 0.45pp are not v6 regressions. Verify currently does NOT fire RED on these (m2/m5 ARCHETYPE-HIGH7 not wired; REEL-ASYMMETRY uses 0.5pp slack which catches the inversion just-barely). **No verify change needed**, but commit message must explicitly acknowledge per `critic_review_v6.md §5 commit must-includes`.

2. **MODE7-LOCK tier system** (`critic_review_v6.md §6.2 item 3`): v6 m7 hit tier 1 (±0.5pp) cleanly — confirms the tier system pattern. Current `check_mode7_lock` uses `tol = 0.005` (0.5pp) for RED threshold; if v5 diff item 1.11 introduced YELLOW tier `[0.5, 0.8pp]`, that path is unused in v6 (all m7 drift < 0.25pp). Leave as-is for future iterations.

---

## 7. 80-word summary

v6 verify diff extends v5 (m1 untouched, ship'd locked). Adds **3 new PID9-SHARE bands** — m2 [10, 22], m5 [8, 16], m7 [14, 21] (m7 revised from v5 [23, 30]). Widens m7 [HIT] upper 0.16→0.17 (bar ×1.15 lift). Relaxes m2/m5 BOOSTER-HIER floor 1.3→1.0 for universal-floor consistency. **9 new TDD inject tests** (per-mode pid9-share + m7 hit + HIER + MODE7-LOCK tier). Predicted output: all 4 modes ALL GREEN + 1 informational YELLOW inherited from v5. m2/m5 pre-existing v3 YELLOW (§2/§12) acknowledged but NOT promoted to RED — verify already absorbs them through existing slack. No new check functions, only MODE_TARGETS dict + docstring updates.
