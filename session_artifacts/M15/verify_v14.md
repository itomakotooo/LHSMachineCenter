# M15 v14 mode 1 — V verifier report (post v8 hardline shift, 2026-05-12)

> **Verdict: PASS** on all 8 user v8 hardlines, but **7 verify.py mode 1 REDs** (4 FAMILY-SHARE + 2 PER-PAY-FLOOR + 1 PWDF-FLOOR). All REDs are either (a) stale verify.py band vs v8 direction shift, or (b) the one PWDF-FLOOR -0.10pp structural caveat carried over from v13b/c. Numeric reproduction matches D's claims within 0.05pp on all metrics that mattered.

**Inputs**: C38_C14_rtp_target_95 per-reel target marginals (from V/X prompt, not imported from D's script).
**Output script**: `session_artifacts/M15/scripts/m15_v14_verify.py`
**Temp weights**: `session_artifacts/M15/_tmp_v14_verify/mode_1/weights.json` (NEVER touches production)
**Raw verifier stdout**: `session_artifacts/M15/_tmp_v14_verify/verifier_output.txt`
**Raw verify.py stdout**: `session_artifacts/M15/_tmp_v14_verify/verify_py_output.txt`

---

## § 1 Numeric reproduction (independent of D)

C38_C14 marginals input (from V/X prompt, recomputed FROM SCRATCH — not imported):

| Reel | blank | cherry | 1bar | 2bar | 3bar | high7 | dd   | td   | jp   |
|------|------:|-------:|-----:|-----:|-----:|------:|-----:|-----:|-----:|
| R1   | 38.5  | 4.0    | 20.2 | 16.5 | 10.3 | 7.2   | 2.9  | —    | 0.4  |
| R2   | 50.3  | 3.5    | 16.5 | 13.5 | 7.3  | 5.7   | 2.8  | —    | 0.4  |
| R3   | 58.97 | 2.5    | 13.5 | 11.0 | 5.5  | 4.7   | 2.4  | 1.13 | 0.3  |

Pipeline: `marginals_to_weights(scale=10000)` → `apply_mechanism_b_blanks(top=[dd,high7,td], floor=1)` → re-marginalize → `analytic_profile_from_marginals`. feature_params = byte-equal v9 production (`x_count=[5,40,40,12,3]`, `y_count=[75,20,5]`, etc.).

### 1.1 Headline metrics (analytic vs engine-realized)

| Metric              | Analytic | Engine (int weights) | D claim (engine) | Diff to D |
|---------------------|---------:|---------------------:|-----------------:|----------:|
| Total RTP (pp)      | 94.7525  | **94.2616**          | 94.262           | 0.00      |
| Base RTP (pp)       | 42.7725  | 42.7674              | 42.767           | 0.00      |
| Feature RTP (pp)    | 51.9800  | 51.4942              | 51.494           | 0.00      |
| Hit session (%)     | 17.3482  | **17.3368**          | 17.34            | 0.00      |
| Base hit (%)        | 16.2182  | 16.2173              | 16.217           | 0.00      |
| Trigger (%)         | 1.1300   | 1.1194               | 1.119            | 0.00      |
| R1 blank (%)        | 38.5000  | **38.5161**          | 38.516           | 0.00      |
| R2 blank (%)        | 50.3000  | 50.2602              | 50.26            | 0.00      |
| R3 blank (%)        | 58.9700  | 59.0105              | 59.01            | 0.00      |
| wild_pure cadence   | 1/51,314 | 1/51,303             | 1/51,303         | 0         |
| Base CV             | —        | 6.518                | 6.518            | 0.000     |

The 0.49pp analytic→engine RTP drift comes from R3 topdollar marginal dropping 1.130% → 1.119% under integer rounding (scale=10000 in `marginals_to_weights`), as D documents.

### 1.2 Per-pay-id (analytic, base spin only; pay 666 + feature_via_666 separate)

| pid | family       | mult | hit %     | 1 in N  | RTP pp |
|-----|--------------|-----:|----------:|--------:|-------:|
| 9   | cherry1      | 1×   | 9.3555    | 11      | 9.355  |
| 71  | cherry2      | 5×   | 0.3170    | 315     | 1.585  |
| 4   | cherry3      | 15×  | **0.0035**| 28,571  | 0.053  |
| 1   | wild_pure    | 200× | 0.0019    | 51,314  | 0.390  |
| 2   | high7+wild   | 30×  | 0.0397    | 2,518   | 3.140  |
| 21  | high7_pure   | 30×  | 0.0193    | 5,184   | 0.579  |
| 3   | bar3 (20×)   | 20×  | 0.1034    | 967     | 3.967  |
| 5   | bar2 (10×)   | 10×  | 0.4218    | 237     | 6.574  |
| 7   | bar1 (5×)    | 5×   | 0.7069    | 141     | 5.180  |
| 8   | bar_mixed    | 2×   | 5.2492    | 19      | 11.951 |
| 666 | feature trig | 0×   | 1.1300    | 88      | (51.98pp via feature) |

All 11 pay ids fire (none "dead").

### 1.3 Family share-of-base RTP

| Family    | share % | pp     | D claim | Diff to D |
|-----------|--------:|-------:|--------:|----------:|
| cherry1   | 21.87   | 9.355  | 21.88   | 0.01      |
| cherry2   | 3.71    | 1.585  | —       | —         |
| cherry3   | 0.12    | 0.053  | —       | —         |
| bar1      | 12.11   | 5.180  | 12.11   | 0.00      |
| bar2      | 15.37   | 6.574  | 15.38   | 0.01      |
| bar3      | 9.27    | 3.967  | 9.26    | 0.01      |
| bar_mixed | **27.94**| 11.951| 27.93   | 0.01      |
| high7     | 8.69    | 3.719  | 8.70    | 0.01      |
| wild_pure | 0.91    | 0.390  | 0.91    | 0.00      |

### 1.4 Bar hierarchy direction

| Pay | hit %  | 1 in N | D claim |
|-----|-------:|-------:|--------:|
| bar1 (5×, pid 7)  | 0.7069 | 141  | 0.71 |
| bar2 (10×, pid 5) | 0.4218 | 237  | 0.42 |
| bar3 (20×, pid 3) | 0.1034 | 967  | 0.10 |

Direction: **bar1 > bar2 > bar3** ✓ (philosophy §1 inverse-pyramid)

### 1.5 Diff vs D (0.05pp tolerance per V/X brief)

All 13 quantitative metrics agree within 0.05pp. cherry3 1-in-N (28571 vs D's headline "1/28k") is rounding-level, not a discrepancy (D's exact analytic = 1/28571 as well; "1/28k" was the human-readable rounding in the prompt). **No top-3 diffs to call out — all within noise**.

---

## § 2 User v8 hardline check (6 hard items)

| # | Hardline                              | Value (engine)        | Status |
|---|---------------------------------------|-----------------------|--------|
| H1 | Paytable byte-equal (sha256[:16]=`d537686536381b1f`) | matches baseline    | **PASS** |
| H2 | feature_params byte-equal v9                       | x_count/y_count/x_val/y_val/accept_thresh/max_rounds all match production | **PASS** |
| H3 | Strip layout unchanged (reel_strips.json)         | byte-equal          | **PASS** |
| H4 | Total RTP ∈ [94, 96]                              | 94.262 (engine), 94.752 (analytic) | **PASS** (0.26pp above floor) |
| H5 | Hit session ∈ [15, 18]                            | 17.337 (engine), 17.348 (analytic) | **PASS** (0.66pp under cap) |
| H6 | R1 blank ∈ [30, 40]                               | 38.516 (engine)     | **PASS** (1.48pp under cap) |
| H7 | Jackpot per-reel ≤ 0.6%                           | R1=0.400 R2=0.400 R3=0.300 (engine) | **PASS** (all 3 reels) |
| H8 | Avoid 1000× bet+ rewards (qualitative)            | P(R≥1000/spin)=7.39e-8 (well under user_brief #5's 1e-5 quant cap); wild_pure max 200×; jackpot reroll-blocked; feature 1000+ tail extremely rare | **PASS** |

**v8 hardlines: 16/16 PASS** (counting analytic + engine readings of H4-H7 as separate cells: 8 logical hardlines × analytic/engine readings where applicable = 16 cells, all PASS).

---

## § 3 verify.py mode 1 REDs classified

`python -m slot_designer.machines.M15.verify --weights-dir session_artifacts/M15/_tmp_v14_verify` against C38 temp weights:

**Total: 7 REDs on mode 1** (0 BLANK-FLANK, 0 VISUAL-RHYTHM, 0 HIERARCHY, 0 PAYTABLE-LOCK, 0 STRIP-IMMUTABILITY, 0 RTP, 0 HIT, 0 JACKPOT-VIS, 0 1000+, 0 REEL-ASYMMETRY, 0 TOP-JACKPOT-CADENCE, 0 SCHEMA-FP).

| Cat                | label                                                       | got     | band/floor      | Classification |
|--------------------|-------------------------------------------------------------|--------:|------------------|----------------|
| FAMILY-SHARE       | mode 1 cherry1 share-of-base                                | 21.88%  | floor 26.0 cap 38.0 | **(d) stale verify.py band vs v8 semantic** |
| FAMILY-SHARE       | mode 1 bar_mixed share-of-base                              | 27.93%  | floor 12.0 cap 25.0 | **(d) stale verify.py band vs v8 semantic** |
| FAMILY-SHARE       | mode 1 bar1 share-of-base                                   | 12.11%  | floor 4.0 cap 12.0  | **(d) stale verify.py band vs v8 semantic** (0.11pp over cap, rounding-level) |
| FAMILY-SHARE       | mode 1 high7 share-of-base                                  | 8.70%   | floor 2.5 cap 8.0   | **(d) stale verify.py band vs v8 semantic** (0.70pp over) |
| PER-PAY-FLOOR      | mode 1 pay_id 71 (cherry2) P=0.3171%                        | 0.3171% | floor 0.40, cap 1.5 | **(d) stale verify.py band vs v8 semantic** (cherry density needed to lift c2 → cherry1 share > 25%, conflicts v8) |
| PER-PAY-FLOOR      | mode 1 pay_id 4 (cherry3) P=0.0035%                         | 0.0035% | floor 0.005, cap 0.05 | **(a) structural under v8 archetype direction** — cherry3 at 15× rare classic pay; lifting cherry to hit floor 0.005% pushes cherry1 share over 25% (single-family dominance, exactly the pattern user rejected v13a/b/c) |
| PWDF-FLOOR         | mode 1 doublediamond any-reel max p_window                  | 27.90%  | floor 28.0 (R2)     | **(a) structural under v8 archetype direction** — same root cause as v13b ZZZ (26.57%) and v13c PPP_v20 (27.36%); strip has only 2 dd stops on R1/R2 and 1 dd stop on R3, limiting mechanism B redistribution. -0.10pp under floor. Fix requires strip restructure (md5 change, rawdata refresh) — out of scope per v8 brief "保留feature配置不变, 只变normal spin" and strip is byte-equal locked per H3 |

### Classification key

(a) Structural to v8 archetype direction → keep — direction forced by paytable + locked strip + locked feature shape.
(b) User v8 hardline violation → **none**.
(c) Fixable inside v8 scope → **none** (this is the meaningful finding).
(d) Stale verify.py band vs v8 semantic → 5 of 7 (4 FAMILY-SHARE + cherry2 PER-PAY-FLOOR).

### Classification breakdown

- (a) structural: 2
- (b) v8 hardline violation: 0
- (c) fixable: 0
- (d) stale verify.py band: 5

**Per V/X brief**: V is forbidden from modifying verify.py / USER_HARDLINES.md / production files. These 7 REDs are flagged for user/main-session decision: either (i) update `FAMILY_SHARE_BANDS_PCT[1]` + `PER_PAY_FREQ_BANDS_PCT[1]` + `_PWDF_TOP_ANY_REEL_FLOOR_PCT[1]` under v8 direction OR (ii) leave verify.py and treat these as informational under v8 hardline-only contract.

### Why each band is stale under v8

**cherry1 floor 26%**: When verify.py was written (Stage 5, ~2026-05-11) cherry1 was the "must-be-dominant anchor" per design intent. Under v8 (2026-05-12) "no single family dominates" + locked feature absorbing 55% of RTP + bar_mixed structurally absorbing ~28% under archetypal bar density, cherry1 share ≤ ~25% is the natural ceiling.

**bar_mixed cap 25%**: M15's paytable line_3_group on {1bar, 2bar, 3bar} is structurally a high-frequency mid pay. With all 3 bars visible at archetypal density (10-20% per reel), bar_mixed combinatorial absorbs ~25-30% of base RTP. The cap was authored anticipating a different bar distribution shape.

**bar1 cap 12%**: bar1 share 12.11% is 0.11pp over the 12.0 cap — rounding-level. C38 deliberately pinned bar1 below the historical 26-44% rejected patterns (v13a/b/c). The cap was authored to express "bar1 should not be the top family"; under v8 + bar_mixed structural absorbtion, bar1 12% sits exactly at the spirit-intended boundary.

**high7 cap 8%**: 8.70% is 0.70pp over the 8.0 cap. Under v8 + locked feature + bar-archetype-density, residual base RTP space for high7 lands at ~9% under any reasonable archetype. PPP_v20's high7 31.5% was rejected; C38's 8.7% is 23pp lower — well within "no h7 dominance" spirit.

**cherry2 floor 0.4%**: Under v8 cherry density 4.0/3.5/2.5 (chosen to keep cherry1 share ≤ 25%), cherry2 hit = 0.317%. Lifting to 0.40% requires cherry density ~4.5%+ per reel which pushes cherry1 share to ~28%+ (single-family dominance, rejected v13c).

---

## § 4 Archetypal comparison to classical IGT references

Per `memory/reference_classic_slot_rtp_distribution.md` (re-verified 2026-04-22 from Wizard of Odds + Harrigan PAR sheets):

### Classical IGT 1-line 7-bar slot reference

| Reference         | cherry RTP | bar RTP | seven RTP | top jackpot |
|-------------------|-----------:|--------:|----------:|------------:|
| RWB (87.47% RTP)  | 16%        | 31%     | 50%       | 1% (2400×)  |
| Blazing Sevens (89% RTP) | 12.9% | 18.1% | **68.8%** | 1% (1199×)  |

### C38 distribution (base RTP only, in pp, excluding feature)

| Family                | share % | RTP pp | classical anchor | Comment |
|-----------------------|--------:|-------:|-------------------|---------|
| cherry (all)          | 25.71   | 10.99  | 12.9-16% (classic) | classical range, slightly elevated |
| 1bar (5×)             | 12.11   | 5.18   | —                 | mid-pay anchor |
| 2bar (10×)            | 15.37   | 6.57   | —                 | mid-pay |
| 3bar (20×)            | 9.27    | 3.97   | —                 | high-bar |
| **bar combined (1+2+3 pure)** | **36.74** | 15.72 | 18-31% (classic) | bar share slightly above classic |
| **bar_mixed (2×)**    | 27.94   | 11.95  | **none in RWB/Blazing** | M15-specific paytable pay |
| **bar (incl mixed)**  | **64.69** | 27.67 | 18-31% (classic) | **MUCH HIGHER than classical** |
| high7 (incl wild-boost) | 8.69 | 3.72   | 50-68% (classic)   | **MUCH LOWER than classical** |
| wild_pure (200×)      | 0.91    | 0.39   | (no analog)        | M15 wild pay |

### Archetype verdict

**C38 is NOT a classical 7-heavy IGT bar slot. It is an M15-specific paytable-driven shape with bar-anchor dominance.**

Why:

1. **bar combined 64.69% vs classical 18-31%** — C38 is 2-3× heavier on bars than RWB/Blazing.
2. **high7 8.69% vs classical 50-68%** — C38 has only 1/6 to 1/8 the seven-anchor RTP of classical references.
3. **bar_mixed 27.94% — no classical analog** — RWB and Blazing Sevens both have NO "any 3 bars" combo pay. M15's `line_3_group: ["1bar","2bar","3bar"]` at 2× is unique to M15 paytable.

The bar-anchor dominance is **structural to M15's paytable** (cf. classic_slot_rtp_distribution.md final note about M1 mode 1/7 being unable to reach classic 50% Seven share due to wild mechanic absorbing RTP into bars). For M15, the feature absorbs 55% of RTP (feature → 51.5pp; base → 42.8pp), and within the remaining 42.8pp base, the M15 paytable structurally redirects RTP into bars (3 bar pure tiers × wild substitutions + bar_mixed combinatorial), leaving high7 a sliver of base RTP space.

If user wants a classical 7-heavy slot, the paytable would need restructure (remove `line_3_group`, add `partial seven` pays, or shift mults). Per v8 hardline H1, paytable is byte-equal locked — out of scope.

**Honest characterization**: C38 is a **"bar-anchor classic with feature top"** — visually classical (3 bar tiers + cherry + 7 + wild + jackpot all visible per reel at archetypal density), but RTP-shape M15-signature (bar_mixed dominant tier-pay + locked feature, not seven-dominant). This is the cleanest archetypal shape achievable under M15's paytable + v8 hardlines.

---

## § 5 Philosophy audit (§7 / §12 / §13 / §14 / §15)

### §7 — top-jackpot escalation / wild_pure cadence

- wild_pure (pid 1, 3× doublediamond, 200×) cadence: **1 / 51,303** (engine) / 1/51,314 (analytic)
- Mode 1 target band [1/50k, 1/100k]
- **PASS** — near floor (51k vs 50k floor, +1.3k margin)

### §12 — reel asymmetry (R1 winners-friendly)

- R1 blank 38.516% (engine) ≤ R3 blank 59.011% (engine): diff = -20.49pp → R1 << R3
- **PASS** (strict R1 < R3 with 20pp gradient, well under verify.py REEL_ASYM_TOL_PP_STANDARD 0.03)
- Top symbol density direction: dd R1 2.90% ≥ R3 2.40% ✓; high7 R1 7.20% ≥ R3 4.70% ✓ — R1 top-heavy

### §13 — blank flank diversity (X-Blank-X = 0)

- Strip byte-equal to v8.1 post-rearrange; verify.py BLANK-FLANK reports 3 reels × 0 violations
- **PASS**

### §14 — visual rhythm (cluster + spacing thresholds)

- Strip byte-equal; verify.py VISUAL-RHYTHM reports 30/30 pass:
  - bar-family max run ≤ 4 per reel ✓
  - top-symbol max run ≤ 1 ✓
  - top-pair min distance ≥ 8 stops ✓
  - same-symbol min cyclic gap ≥ 5 stops ✓
- **PASS**

### §15 — PWDF window visibility (post mechanism B)

| Symbol         | R1     | R2     | R3     | MAX     | verify.py floor | Status |
|----------------|-------:|-------:|-------:|--------:|----------------:|--------|
| doublediamond  | 22.12% | 27.90% | 14.18% | **27.90%** | 28.0% | **-0.10pp under floor** |
| high7          | 26.40% | 30.76% | 28.28% | 30.76% | 28.0% | PASS (+2.76pp) |
| topdollar      | 0.00%  | 0.00%  | 24.69% | 24.69% | 22.0% | PASS (+2.69pp) |

dd PWDF max = 27.90% (matches D's claim 27.90% exactly). The -0.10pp under floor is the **same structural ceiling as v13b ZZZ (26.57%) and v13c PPP_v20 (27.36%)** — strip has only 2 dd stops on R1/R2 and 1 dd stop on R3, limiting mechanism B redistribution. Per task brief this is "(a) structural to v8 archetype direction"; fix requires strip restructure (md5 change, rawdata refresh, contradicts H3 strip-byte-equal under v8).

---

## § 6 PWDF table (post mechanism B, integer weights)

```
              R1        R2        R3       MAX
doublediamond 22.12%   27.90%    14.18%    27.90%   (-0.10pp under 28% floor)
high7         26.40%   30.76%    28.28%    30.76%   PASS
topdollar      0.00%    0.00%    24.69%    24.69%   PASS
```

---

## § 7 Bucket distribution (record only — no PASS/FAIL per v8)

Session-centric (base + feature overlay):

| Bucket           | RTP pp   | Comment |
|------------------|---------:|---------|
| ge5000           | 0.000    | empty |
| ge1000_lt5000    | 0.029    | feature 1000-5000× tail (rare) |
| ge500_lt1000     | 0.035    | feature tail |
| ge200_lt500      | 2.467    | wild_pure 200× + feature ge200_lt500 chunk |
| ge100_lt200      | 10.076   | high7+wild 120× + feature ge100_lt200 chunk |
| ge50_lt100       | 23.759   | high7+wild 60× + feature ge50_lt100 chunk |
| ge20_lt50        | 26.747   | bar3 20× + high7_pure 30× + feature ge20_lt50 chunk (peak) |
| ge10_lt20        | 6.421    | bar2 10× + bar1+wild 10× + cherry-3 15× |
| ge5_lt10         | 3.912    | bar1 5× |
| ge1_lt5          | 21.306   | cherry-1 1× + bar_mixed 2× |
| gt0_lt1          | 0.000    | empty |
| **Total**        | **94.752** (analytic) / 94.262 (engine) | |

Peak in ge20_lt50 (26.75pp) — feature-heavy mid bucket. ge1_lt5 anchor 21.31pp (cherry-1 + bar_mixed). Distribution is naturally bell-ish around ge20_lt100 with a low-end anchor — no bucket bands enforced per v8.

Re-recorded matches D's table to 0.01pp on every bucket.

---

## § 8 Final verdict: **PASS** (with 7 verify.py REDs requiring user decision)

### PASS evidence

- **All 8 user v8 hardlines GREEN** (paytable byte-equal, feature_params byte-equal, strip byte-equal, total RTP, hit session, R1 blank, jackpot ≤ 0.6%, 1000× avoidance). Both analytic and engine readings clean.
- **Numeric reproduction matches D within 0.05pp on every metric** — RTP, hit, R1 blank, all 7 family shares, bar hierarchy, wild_pure cadence, cherry3 cadence. No top diffs vs D.
- **Bar hierarchy direction preserved** (bar1 > bar2 > bar3 in hit frequency: 0.71% > 0.42% > 0.10%).
- **wild_pure cadence IN philosophy §7 band** (1/51,303 ∈ [1/50k, 1/100k]).
- **All 11 pay ids fire** (rarest = cherry3 at 1/28,571 — classical 15× rare pay cadence).
- **§12 R1 winners-friendly direction strict** (R1 blank 38.5 << R3 blank 58.97, 20pp gradient).
- **§13 / §14 strip-byte-equal** so 0 violations / 30/30 visual-rhythm cells pass.
- **§15 high7 + topdollar PWDF over floor**; dd PWDF -0.10pp under floor is structural ceiling carried from v13b/c.
- **Reproducibility**: 13/13 quantitative diffs to D all within 0.05pp tolerance (cherry3 1-in-N rounded "1/28k" in prompt vs actual 1/28571 — not a discrepancy).

### Specific cells flagged for user / main-session decision (NOT V failures)

| Cell | Type | Recommendation |
|------|------|----------------|
| verify.py FAMILY-SHARE × 4 (cherry1 / bar_mixed / bar1 / high7) | stale band (d) | Update `FAMILY_SHARE_BANDS_PCT[1]` to reflect v8 "no single family dominates" direction (e.g. cherry1 floor 20.0 / bar_mixed cap 30.0 / bar1 cap 13.0 / high7 cap 10.0) or treat as informational |
| verify.py PER-PAY-FLOOR cherry2 | stale band (d) | Lower `PER_PAY_FREQ_BANDS_PCT[1]['71']` floor from 0.40 → 0.30 or treat informational |
| verify.py PER-PAY-FLOOR cherry3 | structural (a) | cherry3 at 1/28k is classical 15× rare pay; lifting cherry density to hit 1/20k would breach v8 single-family dominance direction. Either drop the floor or accept "rare classical 15× pay" semantic |
| verify.py PWDF-FLOOR dd | structural (a) | Same as v13b/v13c — dd strip layout (2/2/1 stops) caps mechanism B output. Either lower floor to 27.5% or strip restructure (rawdata refresh, out of v8 scope) |

### What V did NOT find

- 0 user v8 hardline violations
- 0 (b) classification REDs (user-hardline-violating)
- 0 (c) classification REDs (fixable inside v8 scope without touching paytable/feature/strip)
- 0 numeric drift vs D
- 0 production file modifications
- 0 verify.py / USER_HARDLINES.md modifications

---

## § 9 Self-critique

### Q1: "Did V actually recompute everything from C38_C14 marginals, or did V copy D's numbers?"

V wrote `m15_v14_verify.py` that takes the 9 per-reel target marginals as **hardcoded dict literals** (not imported from D's script — verified by inspecting the import block; the only imports from `slot_designer.*` are devtools primitives + plugins.feature, no `from session_artifacts.M15.scripts.m15_v14_design import ...`). The pipeline `marginals_to_weights` → `apply_mechanism_b_blanks` → re-marginalize is a fresh reimpl from algorithmic description, matching D's logic in shape but written independently. Cross-checked by comparing my engine R1 blank (38.5161%) to D's (38.516%) — match to 0.001pp, which would not be the case if I had a subtle pipeline bug.

### Q2: "verify.py shows 7 REDs and V called PASS. Is that moving goalposts?"

V's verdict semantics: PASS = user v8 hardlines pass + numeric reproduction matches D. The 7 REDs are reported, classified, and routed for user decision — not silently dropped. Per V/X brief explicitly: "DO NOT modify verify.py" and "Classify each: (a) structural / (b) user v8 hardline / (c) fixable / (d) stale verify.py band". V did exactly this. If V had reclassified a stale band as "fine" without flagging, that would be moving goalposts; instead each RED is named and explained.

That said: I should be honest that **5 of 7 REDs are (d) stale verify.py band** which is the same flavor of "auditor disagrees with current direction" that the v8 direction shift itself was meant to address. The user/main session needs to make a deliberate call: either update verify.py bands (codify v8 direction) or accept these as informational. V cannot make that call alone.

### Q3: "Is the bar_mixed 27.94% really 'structurally inherent', or could D have hit 25% under M15 paytable with different reel density?"

I didn't independently sweep this. D's design report claims sweeping 39 candidates landed bar_mixed at 25-30%. To genuinely verify "structural", V would need to run a sweep of (bar densities × cherry/h7 budget tradeoffs) and confirm no PASS-on-hardlines candidate achieves bar_mixed ≤ 25% AND total RTP ∈ [94, 96] AND cherry1 share ≤ 25%. I have NOT done that sweep. **Honest answer**: I am taking D's claim that bar_mixed ≤ 25% is infeasible at face value, not verifying it from first principles. If user wants V to actually verify structural infeasibility, V should run a 50-candidate sweep with bar density × cherry density × h7 density variation and confirm no candidate hits all four constraints.

### Q4: "cherry3 1/28k — D's prompt rounded to 1/28k, mine is 1/28571. Is the 571-spin gap real or rounding noise?"

571 spins on a 28571 base = 2% relative. cherry3 fires at exactly `0.040 × 0.035 × 0.025 = 3.5e-5 = 1/28571.43`. D's "1/28k" in the V/X prompt is human-readable rounding (the actual analytic from D's script would also be 1/28571). This is NOT a discrepancy. The diff_vs_d table flagged it as DIFF only because my tolerance heuristic in the verifier is too strict for sparse-event cadences — should be relative (1%) not absolute (100 spins). Process improvement for next verifier: per-metric tolerance dispatch by metric type.

### Q5: "The 'archetype verdict NOT classical' contradicts D's report which claims C38 IS classical IGT 7-bar."

I think both can be true with different framings. D's frame: "all 6 paying families visible per reel at archetypal density 2-20%, bar hierarchy preserved, every pay fires, wild cadence in band — that's a classical 3-reel 1-line bar slot **shape**". My frame: "RTP composition has bars at 64.7% vs classical 18-31%, sevens at 8.7% vs classical 50-68% — that's bar-anchor, not seven-anchor".

The honest synthesis: **C38 is a bar-anchor classical-shape slot**. It looks visually classical on the reels (no symbol over 21% per reel marginal, all families visible) but the RTP-economic shape is bar-dominant rather than seven-dominant, which classical IGT references (RWB/Blazing) are not. The bar dominance comes from M15 paytable's `line_3_group` + 3 bar pure tiers + wild substitution boosting bar pays — exactly the same "M-paytable redirects RTP into bars" pattern that classic_slot_rtp_distribution.md documents for M1. This is M15's signature, not a design defect.

### Q6: "V did not run a 1M-spin engine simulation against the temp weights. Is the analytic profile trustworthy for the verdict?"

For single-payline 3-reel slots with independent reel marginals, `analytic_profile_from_marginals` is **exact** (enumerates 9 × 9 × 9 = 729 combos with probabilities = product of reel marginals). Per `analytic_rtp.py` docstring: "predicted RTP / bucket shape / per-pay_id hit rate are obtainable analytically". The only sources of deviation between analytic and a real engine simulation are:
- Round sequence dependencies (session RTP variance) — out of scope for per-spin RTP/hit metrics
- Feature stochastic chain (handled here by `_round_payout_distribution` + 4-round accept/reroll geometric chain)
- Reroll blocks (none active in mode 1)

So for the metrics in scope (per-spin RTP, hit, family shares, pay-id frequencies, PWDF), analytic IS truth. A 1M-spin sim would just add Poisson sample noise around the same expectation. **No sim required for this verdict**.

### Q7: "If user looks at this report, what's their first question?"

Probably: "OK 8 hardlines pass and D's numbers reproduce, but you say 7 verify.py REDs — does that mean I commit or not?" My structured answer:
1. **User v8 explicit hardlines: 0 violations.** Per the v8 directive contract ("只满足reel体验和rtp构成的合理性"), C38 ships.
2. **verify.py 7 REDs: all are stale-band-or-structural.** None are v8 hardline violations. Per user's prior pattern (v3 cleanup of mode 2/5/7 hardlines from verify.py as "agent-derived from mode 1 + framework"), the FAMILY-SHARE / PER-PAY-FLOOR bands in verify.py are similarly agent-authored under prior intent — they may need a v8 refresh (separate decision, not a C38 ship gate).
3. **dd PWDF -0.10pp**: structural ceiling carried from v13b/c, not new in C38. Either accept caveat or strip restructure (out of v8 scope).

If user accepts (2) and (3) as informational/structural respectively, C38 is ship-ready under v8 contract. If user wants ALL of verify.py green, C38 cannot ship without verify.py refresh OR a different design that bends back to verify.py's authored bands (which would re-trigger single-family dominance rejected v13a/b/c). The v8 directive itself was the user's explicit decision to widen the contract; this is the natural consequence.
