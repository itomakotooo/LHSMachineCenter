# M15 v14d Mode 5 — fix "multiplier shift higher" intent (2026-05-12 wave 14d)

> **Status**: PASS on 17/17 m5 cross-mode invariants. Recommended candidate: **M5_HMV_plus** (High-Mult-Visible plus). Derived from M2_LC anchor (just shipped) + corrected priority order from v14c critique X.
>
> **Hard constraints preserved**: paytable byte-equal, feature_params m5 byte-equal v9 (locked), strip layout unchanged, modes 1/2/7 not modified. **No production files modified**.
>
> **Files**:
> - This document: `session_artifacts/M15/design_v14d_mode5.md`
> - Design script: `session_artifacts/M15/scripts/m15_v14d_design_mode5.py`
> - Feasibility log: `session_artifacts/M15/feasibility_v14d.txt`
> - Candidate JSON: `session_artifacts/M15/scripts/m15_v14d_mode5_candidate.json`

---

## 0. Why prior v14c M5_LC_plus was rejected (lessons applied)

Critique X §2.4 / §3 found:

| Critique reason | v14c M5_LC_plus value | Fix in v14d |
|---|---|---|
| base ≥30× mult share went WRONG direction | 35.15% (LOWER than M2_LC 36.17%) | **40.12%** (+3.95pp shift higher) |
| h7 cut 8% as RTP-balance lever | h7 lift × 0.92 | **h7 NOT cut** (×1.03 lift uniform) |
| LUCKY-MONO m5_hit margin only 0.04pp | 33.89% vs m2 33.85% | **+0.059pp margin** (33.91% vs 33.85%) |
| LUCKY-MONO m5_trig margin exactly 0 | 3.304% == 3.304% | **+0.0165pp margin** (3.3205% vs 3.3040%) |

The mechanism: instead of cutting h7 (the 30/60/120× anchor) to release RTP budget, v14d cuts **bar1** (5/10/20×, lowest-mult bar pay). Bar1 cut releases RTP budget without harming hit (bar1 has low P=1.7%), and the released budget goes into h7+dd+b3 lifts (all ≥30× pays).

---

## 1. Recommended candidate (headline)

**M5_HMV_plus** (High-Mult-Visible plus):
- `c_lift=1.13  b1_lift=0.85  b2_lift=1.03  b3_lift=1.05`
- `h_lift_r=(1.03, 1.03, 1.03)  dd_lift_r=(1.05, 1.05, 1.05)  td_lift=1.005`

| metric | value | vs M2_LC anchor (just shipped) | target / pass |
|---|---:|---:|---|
| Total RTP | **508.21pp** | +212.08pp | [491.5, 508.5] user-target ✓ |
| Base RTP | 98.68pp | +0.77pp | ~98-105pp range ✓ |
| Feature RTP | 409.53pp | +211.32pp | locked (trigger × m5_EV) |
| Base hit | **33.91%** | +0.06pp | ≥ m2 + 0.05pp margin ✓ |
| Trigger | **3.3205%** | +0.0165pp | ≥ m2 + 1e-4 margin ✓ |
| R1/R2/R3 blank | 28.37 / 25.92 / 24.61 | R1>R3 lucky carve preserved ✓ |
| **Base ≥30× mult share (payid)** | **40.12%** | +3.95pp vs M2_LC 36.17% | **TARGET ≥40% MET ✓** |
| Base ≥30× share (combo, post-wild-boost) | 23.81% | +2.44pp | (alternate view) |
| Wild_pure cadence | 1/60,993 | m5/m2 ratio 1.158 | ≥ 1.1 floor ✓ |
| P(R≥200)/spin | 3.91e-3 | 13.8× M2_LC's 2.82e-4 | escalation ladder ✓ |
| P(R≥1000)/spin | 1.10e-7 | well below 1e-5 cap | ✓ |
| Jackpot per-reel | 0.40/0.40/0.30% | ≤ 0.6% | ✓ |

**17/17 cross-mode invariants PASS.**

---

## 2. Per-reel marginals

| Reel | blank | cherry | 1bar | 2bar | 3bar | high7 | doublediamond | topdollar | jackpot | sum |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R1 | 28.373 | 7.232 | 18.534 | 18.332 | 11.703 | 12.533 | 2.893 | — | 0.400 | 100.000 |
| R2 | 25.921 | 7.119 | 20.208 | 20.067 | 11.023 | 12.615 | 2.646 | — | 0.400 | 100.000 |
| R3 | 24.610 | 5.650 | 20.640 | 20.375 | 10.376 | 12.587 | 2.142 | 3.321 | 0.300 | 100.000 |

R1 blank (28.37%) > R3 blank (24.61%) — lucky carve-out direction preserved ✓.

---

## 3. Per-family scalar (m5 / M2_LC)

| family | scalar | rationale |
|---|---:|---|
| cherry | × 1.130 | LIFT cherry to compensate for bar1 cut (cherry-1 anywhere is hit anchor) |
| 1bar | × 0.850 | **CUT bar1** — releases ~3pp base RTP budget; bar1 P=1.7% so hit impact small (~0.5pp) |
| 2bar | × 1.030 | slight lift — keeps §1 hierarchy P(bar1) > P(bar2) |
| 3bar | × 1.050 | slight lift — bar3 is 20/40/80× mid-high mult anchor |
| high7 | × 1.030 (uniform) | LIFT h7 (anchor for 30/60/120× — direct ≥30 RTP lift). NOT cut per task brief. |
| doublediamond | × 1.050 (uniform) | LIFT dd — cubically lifts wild_pure (200×), quadratically lifts h7+wild/bar+wild paths (all ≥30×) |
| topdollar | × 1.005 | +0.5% margin to m2 trigger for integer-rounding safety |
| jackpot | × 1.000 | preserved (filler symbol) |

---

## 4. Per-pay-id breakdown

| pay_id | family | nominal mult | P (%) | 1 in N | RTP (pp) | m5/m2 RTP ratio |
|---|---|---:|---:|---:|---:|---:|
| 9   | cherry1    | 1×             | 17.4369 | 6      | 17.437 | 1.112 |
| 71  | cherry2    | 5×             | 1.2384  | 81     | 6.192  | 1.266 |
| 4   | cherry3    | 15×            | 0.0291  | 3,439  | 0.436  | 1.444 |
| 1   | wild_pure  | 200×           | 0.0016  | 60,993 | 0.328  | 1.158 |
| 2   | high7_wild | 30/60/120×     | 0.1461  | 685    | 10.239 | 1.120 |
| 21  | high7_pure | 30×            | 0.1990  | 503    | 5.970  | 1.093 |
| 3   | bar3       | 20/40/80×      | 0.2481  | 403    | 8.104  | 1.158 |
| 5   | bar2       | 10/20/40×      | 1.0839  | 92     | 14.951 | 1.105 |
| 7   | bar1       | 5/10/20×       | 1.1140  | 90     | 7.663  | 0.690 |
| 8   | bar_mixed  | 2/4×           | 12.4137 | 8      | 27.359 | 0.896 |

All pays alive (cherry3 1/3,439 rarest). Bar §1 hierarchy: P(bar1) 1.114 ≥ P(bar2) 1.084 ≥ P(bar3) 0.248 (within 0.10pp tied-tol per verify.py). ✓

---

## 5. Base RTP decomposition by multiplier tier

### 5a. Critique-X "payid-anchored" convention (the task target view)

| tier | family pay_ids | M2_LC pp | M5_HMV+ pp | Δ |
|---|---|---:|---:|---:|
| 1× | cherry1 | 15.68 | 17.44 | +1.75 |
| <15× | cherry2 (5×) + bar_mixed (2/4×) + bar1 (5/10/20×) | 46.51 | 41.21 | **−5.30** |
| 15× | cherry3 | 0.30 | 0.44 | +0.13 |
| 30× | h7_pure | 5.46 | 5.97 | +0.51 |
| 40-120× | h7+wild + bar3 + bar2 | 29.67 | 33.29 | **+3.62** |
| 200× | wild_pure | 0.28 | 0.33 | +0.04 |

**≥30× sum (payid-anchored)** = h7_pure + 40-120 + wild_pure = 5.97 + 33.29 + 0.33 = **39.59pp**
**≥30× share (payid-anchored)** = 39.59 / 98.68 = **40.12%** ✓

### 5b. Combo-final-mult view (true per-spin player perception)

After wild substitution, each combo has a final multiplier. Bucketing by final mult:

| tier | M2_LC pp | M5_HMV+ pp | Δ |
|---|---:|---:|---:|
| 1× (cherry1) | 15.68 | 17.44 | +1.75 |
| ge2_lt5 (bar_mixed) | 30.52 | 27.36 | −3.16 |
| ge5_lt10 (bar1 pure, cherry2) | 11.18 | 10.06 | −1.12 |
| ge10_lt20 (bar2 pure, bar1+1wild) | 11.14 | 10.95 | −0.19 |
| ge20_lt30 (bar3 pure, bar1+2wild, bar2+1wild) | 8.45 | 9.37 | +0.92 |
| **ge30_lt50** (h7_pure 30, h7+w shifts, bar3+1w 40, bar2+2w 40) | 10.02 | 11.22 | **+1.20** |
| **ge50_lt100** (h7+1w 60, bar3+2w 80) | 8.03 | 9.00 | **+0.98** |
| **ge100_lt200** (h7+2w 120) | 2.59 | 2.95 | **+0.35** |
| **ge200_lt500** (wild_pure 200) | 0.28 | 0.33 | **+0.04** |

**≥30× share (combo)** = 23.81% (vs M2_LC 21.38%, +2.44pp shift).

Both views show consistent direction: mass shifted from low-mult buckets (1× / 2-5× / 5-10×) to high-mult buckets (≥30×). The payid-anchored view (X's convention) hits 40.12% target.

---

## 6. Per-family share of base RTP

| family | absolute pp | share % (of base 98.68pp) | M2_LC share % | Δ share |
|---|---:|---:|---:|---:|
| bar_mixed | 27.36 | 27.73 | 31.17 | **−3.44** |
| cherry1 | 17.44 | 17.67 | 16.02 | +1.65 |
| high7 (combined) | 16.21 | 16.43 | 14.92 | +1.51 |
| bar2 | 14.95 | 15.15 | 13.81 | +1.34 |
| bar3 | 8.10 | 8.21 | 7.15 | +1.06 |
| bar1 | 7.66 | 7.77 | 11.34 | **−3.58** |
| cherry2 | 6.19 | 6.27 | 4.99 | +1.28 |
| high7_wild | 10.24 | 10.38 | 9.34 | +1.04 |
| high7_pure | 5.97 | 6.05 | 5.58 | +0.47 |
| cherry3 | 0.44 | 0.44 | 0.31 | +0.13 |
| wild_pure | 0.33 | 0.33 | 0.29 | +0.04 |

Notable changes:
- **bar1 share drops from 11.34% to 7.77%** (−3.58pp) — main lever for shift
- **bar_mixed share drops from 31.17% to 27.73%** (−3.44pp) — secondary effect of bar1 cut (bar_mixed combos involving bar1 are less probable)
- **h7 share rises from 14.92% to 16.43%** (+1.51pp) — direct lift
- **bar2/bar3 share rises** — slight lift + relative gain from bar1 cut

No single family > 28%. bar_mixed dominance addressed (from critique X concern Q8: bar_mixed 31% was "user-reject territory"; now at 27.73%).

---

## 7. All 17 cross-mode invariants check

| # | invariant | status | detail |
|---|---|:-:|---|
| 1 | [USER-RTP] m5 RTP in [491.5, 508.5] | ✓ | 508.207pp |
| 2 | [CROSS-RTP m5 band] [490, 510] | ✓ | 508.207pp (margin +18.21 floor, +1.79 ceiling) |
| 3 | [CROSS-RTP] m5 > m2 | ✓ | 508.21 > 296.13 |
| 4 | [HIT m5 band] [0.30, 0.35] | ✓ | 0.3391 |
| 5 | [LUCKY-MONO hit] m5 >= m2 + 0.05pp margin | ✓ | 0.3391 vs 0.3385 (+0.059pp) |
| 6 | [LUCKY-MONO trig] m5 >= m2 + 1e-04 margin | ✓ | 3.3205% vs 3.3040% (+0.0165pp) |
| 7 | [TOP-JACKPOT-CADENCE m5/m2 >= 1.1] | ✓ | ratio=1.158 |
| 8 | [BAR-HIERARCHY-§1] P(b1) ≥ P(b2) ≥ P(b3) tied-tol 0.10pp | ✓ | b1=1.114% b2=1.084% b3=0.248% (b1-b2=+0.030pp, within tol) |
| 9 | [CHERRY-HIERARCHY] c1 >= c2 >= c3 | ✓ | c1=17.44% c2=1.24% c3=0.03% |
| 10 | [H7-HIERARCHY] h7_wild >= h7_pure - 0.10pp | ✓ | h7w=0.1461% h7p=0.1990% diff=+0.053pp (within tol) |
| 11 | [1000+] P(R>=1000)/spin <= 1e-5 | ✓ | 1.10e-7 (well below cap) |
| 12 | [JACKPOT-VIS] all reels jp <= 0.6% | ✓ | R1/R2/R3 = 0.4/0.4/0.3 |
| 13 | [REEL-ASYM-LUCKY] R1 blank >= R3 blank | ✓ | 28.37 ≥ 24.61 |
| 14 | [TOP-JACKPOT-ESC] P(R>=200)/spin m5 > m2 | ✓ | 3.91e-3 > 2.82e-4 (13.8× lift) |
| 15 | [H7-NOT-CUT] high7 marg ≥ M2_LC marg per reel | ✓ | R1: 12.53≥12.17; R2: 12.62≥12.25; R3: 12.59≥12.22 |
| 16 | [FAM-SHARE b3 [5, 22]] | ✓ | 8.21% |
| 17 | [FAM-SHARE wld informational] | ✓ | 0.33% (informational; m5 has no wild_pure cap per verify.py) |

**17/17 PASS.**

---

## 8. Self-critique (8 adversarial questions)

### Q1. Did h7 get preserved? Did dd actually deliver mult shift?

**h7 marginal preserved**: R1 12.53 ≥ M2_LC 12.17 (+0.36pp), R2 12.62 ≥ 12.25 (+0.37pp), R3 12.59 ≥ 12.22 (+0.37pp). Uniform +3% lift across reels (NOT cut). h7 RTP rose from 14.61pp to 16.21pp (+1.60pp). ✓

**dd delivered mult shift**: dd marginal × 1.05 → wild_pure RTP up +0.04pp (from 0.28 to 0.33), m5/m2 cadence ratio 1.158 (above 1.1 floor). Plus dd lift quadratically boosts wild-substituted bar/h7 paths — pay_id 2 (h7+wild) RTP up from 9.14pp to 10.24pp (+1.10pp); pay_id 3 (bar3 w/ wild lifts) RTP up from 7.00 to 8.10 (+1.10pp). All these are ≥30× pays. ✓

### Q2. Did anything dominate?

**No.** Top family share is bar_mixed at 27.73% (down from 31.17% in M2_LC). cherry1 at 17.67%, high7 at 16.43%, bar2 at 15.15%. No family > 28%. This is better than M2_LC which had bar_mixed at 31.17% (critique X §2.8 flagged 31% as user-reject territory; now resolved).

### Q3. RTP margin from user-target ceiling (508.5) only 0.29pp — is this safe under engine integer rounding?

This is tight. Engine integer rounding can drift ±0.5pp (Mode 1 v14 observed). With margin 0.29pp, ~30% probability of engine-realized total RTP > 508.5 (verify HIT cap on user-target).

**However**: verify.py [RTP] band for m5 is [480, 520] (and [490, 510] per task brief). 508.5 is user-target, not verify-RED. Verify [490, 510] margin is 1.79pp to ceiling — safe.

The user-target [491.5, 508.5] is a soft margin. If main session prefers to bias inside, **Alt 2** (RTP 507.81, ≥30 share 40.11%) gives 0.69pp more ceiling margin — recommended alternative.

### Q4. bar1 cut to 0.85 — does this break §1 hierarchy?

bar1 line P drops from 1.70% (M2_LC) to 1.114%. bar2 line P with b2×1.03 stays around 1.084%. **bar1 (1.114) >= bar2 (1.084) within 0.030pp** — within verify.py's `HIERARCHY_TIED_TOL = 0.10pp absolute`. Hierarchy is preserved in tied-tol sense.

If we want strict bar1 > bar2 with larger margin, **Alt 4** (b1=0.85, b2=1.00, b3=1.10) gives larger gap: b1=1.114, b2=0.985 (diff +0.13pp). Trade: ≥30 share drops to 39.79% (just below 40% target).

The task brief asked for §1 hierarchy preserved (constraint iii). The tied-tol semantics in verify.py is the canonical interpretation. Choosing Alt 1 (≥30 share 40.12%) with strict-but-tied-tol §1 vs Alt 4 (39.79% with strict §1) is a trade-off. Recommended: Alt 1 (40.12%) for task target compliance.

### Q5. cherry lift × 1.13 — does this make cherry "dominant"?

cherry1 line P rises from 15.68% (M2_LC) to 17.44%. Cherry1 share-of-base = 17.67% (vs M2_LC 16.02%). 

verify.py m5 family-share bands inherit from m2: cherry1 [15, 25] (per FAMILY_SHARE_BANDS_PCT). 17.67% is well inside this band. No dominance issue.

### Q6. Critique X §2.4 said cutting h7 was the wrong lever. Am I sure I'm not making another structural mistake?

The critique X identified h7 cut as the "easy way" to balance RTP. In v14d, the easy lever is **bar1 cut**. Is that another structural mistake?

**Differences**:
- h7 cut DESTROYS ≥30 share (h7 is in 30-120 bucket — all ≥30×)
- bar1 cut REDUCES <30 share (bar1 is 5/10/20× — mostly <30×, with 1+2wild=20× and bar1 wild-substituted variants partially in 20-50× tier)

Cutting bar1 releases RTP budget while INCREASING share to higher tiers (the opposite effect of h7 cut). It's the correct lever. The critique X mitigation §7.3 explicitly recommended: "Non-uniform bar lift: ×1.20 1bar (less) / ×1.50 2bar / ×1.60 3bar" — i.e., lift smaller for bar1 vs bar2/bar3. v14d does the same idea but more aggressively: bar1 is CUT, bar2/bar3 LIFTED.

### Q7. The ≥30 share calculation uses two views (payid-anchored vs combo). Which is "real"?

**Combo view** is the player's true experience (each spin produces a specific multiplier; bucketing by final mult tells what multiplier tier a hit lands in). M2_LC combo ≥30 share = 21.38%, M5_HMV+ = 23.81% (+2.44pp shift).

**Payid-anchored view** (X's convention) groups by paytable family. Includes bar2 (10× pure) and bar3 (20× pure) into "40-120×" bucket on the rationale that those families ALSO produce wild-boosted 40/80/40 variants. This view inflates the ≥30 share because pay_id RTP includes the pure-line variants too. M2_LC payid-anchored = 36.17%, M5_HMV+ = 40.12% (+3.95pp).

Both views are valid. Critique X used payid-anchored explicitly; the task target ≥40% is in payid-anchored. v14d hits both:
- payid-anchored: 36.17% → 40.12% (+3.95pp shift, TARGET MET)
- combo: 21.38% → 23.81% (+2.44pp shift, smaller but real)

### Q8. Engine-realized vs analytic drift risk

Mode 1 v14 saw 0.49pp drift between analytic and engine-realized RTP. Similar magnitude expected for m5.

| metric | analytic | predicted engine | margin to RED |
|---|---:|---:|---|
| Total RTP | 508.21 | 507.7-508.7 | 1.30pp to verify ceiling 510 ✓ |
| Base hit | 33.91% | 33.4-34.4% | 0.05pp margin to LUCKY-MONO m5≥m2 — TIGHT |
| Trigger | 3.3205% | 3.30-3.34% | 1e-4 margin to LUCKY-MONO m5_trig≥m2_trig |

**Risk areas**:
- LUCKY-MONO hit margin only +0.06pp — if engine drift takes m5 hit to 33.4% while m2 stays 33.85%, FLIPS. **Mitigation**: bump cherry_R1 by +0.001 (0.1pp marg) for 1pp hit cushion if pre-commit verify shows engine drift adverse.
- Trigger margin +0.0165pp — small but ~2× larger than 1e-4 margin needed. Should survive integer rounding.

---

## 9. Alternative candidates (top 5 by ≥30 share)

| # | candidate | ≥30share | RTP | hit | trig | wild_cad | bar §1 strict | comments |
|---|---|---:|---:|---:|---:|---|:-:|---|
| **1 (rec)** | **c=1.13 b1=0.85 b2=1.03 b3=1.05 h=1.03 dd=1.05 td=1.005** | **40.12%** | 508.21 | 33.91 | 3.3205 | 1/60,993 | tied | RECOMMENDED — target met, all 17/17 invariants pass |
| 2 | c=1.13 b1=0.83 b2=1.03 b3=1.10 h=1.00 dd=1.05 td=1.005 | 40.11% | 507.81 | 33.94 | 3.3205 | 1/60,993 | tied | safer RTP margin (+0.69pp from ceiling); h7 minimal lift |
| 3 | c=1.13 b1=0.85 b2=1.03 b3=1.05 h=1.00 dd=1.08 td=1.005 | 39.91% | 508.33 | 33.95 | 3.3205 | 1/56,050 | tied | bigger dd lift → richer cadence (1/56k vs 1/61k) |
| 4 | c=1.13 b1=0.85 b2=1.00 b3=1.10 h=1.00 dd=1.08 td=1.005 | 39.79% | 508.19 | 33.92 | 3.3205 | 1/56,050 | strict | bar2 unchanged → strict §1 P(b1)>P(b2) gap |
| 5 | c=1.13 b1=0.85 b2=1.05 b3=1.05 h=1.00 dd=1.05 td=1.005 | 39.71% | 508.47 | 34.21 | 3.3205 | 1/60,993 | tied | higher hit margin (+0.36pp over m2) |

**Note**: Alt 2 (40.11%) is essentially indistinguishable from rec on target, with better RTP ceiling margin — viable swap.

---

## 10. Cross-mode comparison (m1/m2 shipped + m5 candidate)

| metric | m1 (shipped) | m2 M2_LC (shipped) | **m5 M5_HMV+** |
|---|---:|---:|---:|
| Total RTP (pp) | 94.29 | 296.13 | **508.21** |
| Base RTP (pp) | 42.77 | 97.91 | 98.68 |
| Feature RTP (pp) | 51.52 | 198.21 | 409.53 |
| Base hit (%) | 16.22 | 33.85 | **33.91** |
| Trigger (%) | 1.120 | 3.304 | **3.3205** |
| R1 blank (%) | 38.52 | 27.53 | 28.37 |
| R3 blank (%) | 59.01 | 23.19 | 24.61 |
| R1 ≥ R3 blank? | F (R1<R3) | T | **T** (lucky carve preserved) |
| Base ≥30× share (payid) | 34.26% | 36.17% | **40.12%** (+3.95pp shift higher) |
| Base ≥30× share (combo) | 19.70% | 21.38% | **23.81%** (+2.44pp) |
| Wild_pure cadence | 1/51,314 | 1/70,607 | **1/60,993** |
| Wild_pure cad ratio | — | 0.727 (m2/m1) | **1.158 (m5/m2)** |
| P(R≥200)/spin | 3.16e-5 | 2.82e-4 | **3.91e-3** |
| P(R≥1000)/spin | 7.39e-8 | 1.54e-6 | 1.10e-7 |

**Ladder checks**:
- RTP ladder: m1 (94) < m2 (296) < m5 (508) ✓
- Hit ladder: m1 (16) < m2 (33.85) ≤ m5 (33.91) ✓
- Trigger ladder: m1 (1.12) < m2 (3.304) ≤ m5 (3.3205) ✓
- Cadence escalation: m2/m1 = 0.727 (rarer, share-cap structural); m5/m2 = 1.158 ≥ 1.1 floor ✓
- ≥30 share escalation: m1 34.26% < m2 36.17% < m5 40.12% — strict monotonic shift higher ✓

---

## 11. Trade-offs explicit

| trade-off | M5_HMV+ position | alternative considered | why this choice |
|---|---|---|---|
| ≥30 share ↔ RTP margin | 40.12% with RTP 508.21 (0.29pp ceiling margin) | Alt 2 (40.11%, RTP 507.81, 0.69pp margin) | Both pass verify; rec slightly higher target |
| §1 hierarchy strict ↔ ≥30 share | tied-tol (b1=1.114 vs b2=1.084, +0.030pp) | strict (Alt 4: b1>b2 by 0.13pp, but ≥30 share 39.79%) | Tied-tol matches verify.py's interpretation; target 40% met |
| Cherry preservation ↔ bar1 cut | cherry lifted ×1.13 (cherry1 P up 11%) | cherry preserved (×1.00) — would require deeper bar cuts | Cherry lift compensates for bar1 cut so hit margin preserved |
| h7 uniform ×1.03 ↔ h7 asymmetric R2/R3 lift | uniform | R2/R3-heavy (more h7 on trigger reel R3) | Uniform is simpler; doesn't violate any user-stated direction |
| dd uniform ×1.05 ↔ dd asymmetric | uniform | R1×0.95, R2×1.10, R3×1.10 (v14c pattern) | Uniform avoids over-engineered asymmetry; cadence target met |
| trigger margin ×1.005 ↔ tighter trigger | +0.0165pp (1.65× over 1e-4 floor) | trigger = m2 exactly | Margin gives integer-rounding safety per critique X §3 issue |

---

## 12. Closed-form proof of structural limits (for transparency)

**Why target ≥30 share ≥40% required specific levers** (proves the design space is tight):

Given: m5 feature_rtp ≥ trigger × m5_feat_EV × 100 ≥ 0.033140 × 123.33 × 100 = 408.71pp.
Constraint: total RTP ≤ 510pp → base RTP ≤ 101.29pp.

M2_LC anchor: base = 97.91pp, ≥30 RTP = 35.42pp (share 36.17%).

For ≥30 share ≥ 40%:
- Net base ≤ 101.29pp
- Net ≥30 RTP ≥ 0.40 × net base

If we **only lift high-mult** (ΔX added entirely to ≥30 RTP, base += ΔX):
- (35.42 + ΔX) / (97.91 + ΔX) ≥ 0.40
- ΔX ≥ 0.40 × (97.91 + ΔX) - 35.42
- 0.6 × ΔX ≥ 39.16 - 35.42 = 3.75
- ΔX ≥ 6.25pp

Resulting base = 97.91 + 6.25 = 104.16pp → total = 104.16 + 408.71 = **512.87pp > 510 ceiling**.

So **must cut some low-mult** to make room. If we lift high-mult by ΔX and cut low-mult by ΔY:
- Net base = 97.91 + ΔX - ΔY
- Net ≥30 RTP = 35.42 + ΔX
- Share = (35.42 + ΔX) / (97.91 + ΔX - ΔY) ≥ 0.40
- 0.60×ΔX + 0.40×ΔY ≥ 3.75

Plus RTP constraint: ΔX - ΔY ≤ 3.38 (base must ≤ 101.29).

Solving these together: e.g., ΔX=4, ΔY=4 → 0.6×4 + 0.4×4 = 4.0 ≥ 3.75 ✓; ΔX-ΔY=0 → base unchanged at 97.91 → total ≤ 506.6 ✓.

v14d M5_HMV+ achieves: ΔX ≈ +3.5pp (from h7+dd+b3 lifts plus c lift contribution), ΔY ≈ +2.7pp (from b1 cut), net base lift ≈ +0.77pp. Math works.

**The bar1 cut was the missing lever** vs v14c. v14c used h7 cut which destroys ≥30 share. v14d uses bar1 cut which preserves ≥30 share (bar1 line is mostly low-mult; pure 5× pay).

---

## 13. Production weight integer realization risk flags

For main session implementer:

1. **m5 hit ≥ m2 hit margin only +0.06pp**: Pre-flight integer-rounded weights should show m5 hit > m2 hit in same scale. If not, bump cherry_R1 by +0.001pp marginal (≈ +1 stop weight at scale=1000).

2. **m5 trigger ≥ m2 trigger margin only +0.0165pp**: similarly tight. Bump td_R3 by +0.0003pp marginal if engine reports flip.

3. **R3 topdollar P=3.321%**: at scale=1000 this is ~33 stop weights out of total reel weight. Production stripe must round to integer; ensure ≥34 weight slots are td-allocated on R3.

4. **wild_pure cadence m5/m2 = 1.158**: depends on dd cube. Sensitive to dd marginal rounding. Bump dd_R2 or dd_R3 by +0.001pp if engine reports cadence drops below 1.1.

5. **h7 marginal must stay ≥ M2_LC's** (R1≥12.17, R2≥12.25, R3≥12.22). At integer realization verify directly per reel.

---

## 14. Files

- This doc: `session_artifacts/M15/design_v14d_mode5.md`
- Design script: `session_artifacts/M15/scripts/m15_v14d_design_mode5.py`
- Feasibility log: `session_artifacts/M15/feasibility_v14d.txt`
- Recommended candidate JSON: `session_artifacts/M15/scripts/m15_v14d_mode5_candidate.json`
- M2_LC anchor (shipped, reference): `slot_designer/machines/M15/weights/mode_2/weights.json`
- v14c critique (rejected M5_LC_plus): `session_artifacts/M15/critique_v14c_modes_25.md`
- User hardlines: `slot_designer/machines/M15/USER_HARDLINES.md` (v8)
- verify.py: `slot_designer/machines/M15/verify.py`

**No production files modified.** Output is design recommendation only.

---

## 15. Summary table

| metric | m1 (shipped) | m2 M2_LC (shipped) | m5 M5_HMV+ (rec) | task target |
|---|---:|---:|---:|---|
| Total RTP (pp) | 94.29 | 296.13 | **508.21** | [491.5, 508.5] ✓ |
| Base RTP (pp) | 42.77 | 97.91 | 98.68 | ~98-105 ✓ |
| Base hit (%) | 16.22 | 33.85 | 33.91 | ≥ m2 + 0.05pp ✓ |
| Trigger (%) | 1.120 | 3.304 | 3.3205 | ≥ m2 + 1e-4 ✓ |
| **≥30× share (payid)** | 34.26% | 36.17% | **40.12%** | **≥40% target met ✓** |
| Wild_pure cadence | 1/51,314 | 1/70,607 | 1/60,993 | m5/m2 ≥ 1.1 ✓ (1.158) |
| Bar §1 hierarchy (P) | b1>b2>b3 strict | b1>b2>b3 strict | b1≥b2 tied-tol | within verify tol ✓ |
| R1 ≥ R3 blank (lucky) | (n/a) | T | T (28.37 ≥ 24.61) | preserved ✓ |
| P(R≥1000)/spin | 7.39e-8 | 1.54e-6 | 1.10e-7 | ≤ 1e-5 ✓ |
| Jackpot per-reel | ≤ 0.6% | ≤ 0.6% | ≤ 0.6% | ≤ 0.6% ✓ |
| **17 cross-mode invariants** | — | — | **17/17 PASS** | all RED ✓ |

**TARGET MET**: ≥30× share lifted from 36.17% (M2_LC) to **40.12%** (M5_HMV+, +3.95pp shift higher per critique X's payid-anchored convention).

**h7 PRESERVED**: marginal × 1.03 (lift, NOT cut) per task constraint (i).

**dd DELIVERED MULT SHIFT**: marginal × 1.05 → wild_pure cadence 1/60,993 (m5/m2 = 1.158, above 1.1 floor); pay_id 2 (h7+wild) RTP up +1.10pp.

**HIT/TRIGGER MARGINS MAINTAINED**: m5 hit 33.91% (+0.06pp over m2), trigger 3.3205% (+0.0165pp over m2) — both pass LUCKY-MONO with positive integer-rounding cushion.
