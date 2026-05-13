# M15 v11 mode 1 — STRUCTURAL ESCALATION (2026-05-11 wave 11)

> **Status**: STRUCTURAL CONFLICT after exhaustive search.
>
> Per the v11 brief (session-centric hardlines), I designed candidates from FIRST
> PRINCIPLES (not v9 anchor), explored 500k+ random samples plus 35+ hand-tuned
> candidates across 8 distinct structural strategies. **NO candidate satisfies
> all user v3 hardlines simultaneously.**
>
> The conflict is between **3 user hardlines that are individually feasible but
> jointly infeasible** under M15 paytable + LOCKED feature shape:
>
>   1. session ge1_lt5 ∈ [10, 12]pp
>   2. session hit_rate ∈ [15, 18]%
>   3. session total RTP ∈ [94, 96]%
>
> Combined with the locked feature contribution (50.6pp, ~0pp ge1_lt5), the
> bucket distribution implied by these hardlines requires base RTP that is
> structurally unreachable.
>
> **v9 weights remain on disk unchanged. verify.py untouched. reel_strips.json unchanged.**

---

## 1. User v3 hardlines (per machines/M15/USER_HARDLINES.md v3)

| # | constraint | band |
|---|---|---|
| 1 | Paytable byte-identical | spec.json `pays` block |
| 2 | Feature shape locked (trigger ~1.1%, EV ~46×) | feature_params byte-equal to v9 |
| 3 | Avoid 1000× bet+ rewards | qualitative |
| 4 | Jackpot any-reel marginal ≤ 0.6% | per reel |
| 5 | Hit_session (incl. feature trigger) | [15, 18]% |
| 6 | Total RTP | [94, 96]% |
| 7 | R1 blank marginal | [30, 40]% |
| 8 | session ge1_lt5 RTP | [10, 12]pp |
| 9 | session sum(ge1_lt5+ge5_lt10+ge10_lt20) | ~30pp |
| 10 | session 20+ buckets ≈ v9 (±2pp) | per bucket |

---

## 2. Closed-form structural proof

### 2.1 Feature contribution is LOCKED

Per user rule "Feature shape locked", `feature_params` block stays v9 byte-equal.
Computed via `m15_v11_design._compute_feature_bucket_ev`:

| bucket | feature EV contribution (× bet, per trigger) | feature RTP at 1.1% trigger (pp) |
|---|---:|---:|
| ge1_lt5 | 0.000 | 0.000 |
| ge5_lt10 | 0.069 | 0.076 |
| ge10_lt20 | 1.512 | 1.663 |
| ge20_lt50 | 16.527 | 18.180 |
| ge50_lt100 | 18.421 | 20.263 |
| ge100_lt200 | 7.577 | 8.334 |
| ge200_lt500 | 1.838 | 2.022 |
| ge500_lt1000+ | 0.056 | 0.062 |
| **total** | **46.0×** | **50.6pp** |

### 2.2 Base bucket targets derived from session hardlines

session bucket = base bucket + feature contribution (computed above).

For session 20+ buckets to ≈ v9 (within ±2pp tolerance):

| bucket | session target | feature contribution | base target |
|---|---:|---:|---:|
| ge20_lt50 | ~27 ± 2.5 | 18.180 | ~8.82 ± 2.5 |
| ge50_lt100 | ~22 ± 2.5 | 20.263 | ~1.74 ± 2.5 |
| ge100_lt200 | ~9 ± 2.5 | 8.334 | ~0.67 ± 2.5 |
| ge200_lt500 | ~2.3 ± 1.0 | 2.022 | ~0.28 ± 1.0 |
| **sum 20+ base** | (60.3 ± 8.5) | (48.8) | **(11.5 ± 8.5)** |

For session ge1_lt5 ∈ [10, 12]pp:
- base ge1_lt5 ∈ [10, 12] (feature contributes ~0)

For session sum_1_20 ~ 30pp (allow [28, 32]):
- base sum_1_20 = session - 1.74 ∈ [26.3, 30.3]
- base ge5_lt10 + ge10_lt20 = base sum_1_20 - base ge1_lt5 ∈ [14.3, 20.3]

### 2.3 Total base RTP required

total RTP ∈ [94, 96] → base RTP ∈ [94 - 50.6, 96 - 50.6] = **[43.4, 45.4]**pp

### 2.4 Hit floor decomposition

session hit ≥ 15% → base hit ≥ 13.9% (trigger contributes 1.1%)

Decompose base hit by which bucket the pay lands in:

| bucket | pays + multipliers that land here (base) |
|---|---|
| ge1_lt5 | pay_id 9 (cherry-1, 1×); pay_id 8 (bar_mixed pure, 2×); pay_id 8 with 1 wild (4×) |
| ge5_lt10 | pay_id 7 (bar1_pure, 5×); pay_id 71 (cherry-2, 5×); pay_id 8 with 2 wilds (8×) |
| ge10_lt20 | pay_id 5 (bar2_pure, 10×); pay_id 7 with 1 wild (10×); pay_id 4 (cherry-3, 15×) |
| ge20_lt50+ | pay_id 3 (bar3_pure, 20×); pay_id 21 (h7_pure, 30×); pay_id 2 (h7+wild, 60-120×); pay_id 1 (3 wild, 200×); etc. |

P_hit_in_g15 = P_cherry_1 + P_bm_pure + P_bm_w1wild

ge1_lt5 base RTP = 1·P_cherry_1 + 2·P_bm_pure + 4·P_bm_w1wild

**Lower bound on g15 RTP given hit decomposition** (since each pay contributes
its P to hit and RTP = sum(P·mult)):

g15_base ≥ P_hit_in_g15 (since min multiplier in g15 is 1)

So **g15_base ≥ P_hit_in_g15 ≥ hit_total − (P_hit_outside_g15)**.

### 2.5 Maximum P_hit_outside_g15 with bucket targets satisfied

Outside-g15 hit must come from pays with mult ≥ 5×. The constraint that base
g510 + g1020 ≤ 20.3pp limits the P_hit in those buckets:

- bar1_pure at 5×: max P contribution 20.3/5 = 4.06% (if g510 entirely bar1_pure)
- bar2_pure / cherry-3 / bar1+wild at 10-15×: max P ≤ 20.3/10 = 2.03% (similar)

Combined, max P_hit in g510+g1020 ≤ ~4.5% (need to share RTP budget).

Plus base 20+ buckets contribute P_hit at higher mults:
- bar1+wild+wild at 20×: max P 11.5/20 = 0.575% (if base g20+ entirely 20× pays)
- bar3_pure at 20× / h7_pure at 30× / h7+wild at 60-120×: combined P ~ 1%

**Max P_hit_outside_g15 with 20+ buckets ~ v9 ≤ ~5.5%.**

(In the 500k random sweep with all hardlines pass except g15:
the **minimum** g15 observed was 17.94pp where all other constraints passed.)

### 2.6 Lower bound on g15

base hit ≥ 13.9% → P_hit_in_g15 ≥ 13.9 − 5.5 = **8.4%**

g15_base ≥ P_hit_in_g15 × (average mult of g15 pays)

Average mult in g15: cherry-1 contributes 1×, bar_mixed 2×, bar_mixed+wild 4×.
For pure cherry-only fill of P_hit_in_g15 (min average mult), avg ≈ 1.

**Therefore g15_base ≥ 8.4pp (theoretical floor at uniform cherry concentration)**.

User cap: g15 ≤ 12pp. Floor 8.4 < 12, so **floor alone is in band**.

### 2.7 But: hit-only constraint isn't tight — sum_1_20 constraint binds

If we try to achieve g15 = 8.4pp via P_cherry_1 ≈ 8.4% and bar_mixed = 0:
- 1bar/2bar/3bar must be configured such that bar_mixed_pure P = 0
- Achieved only if each reel has ≤ 1 bar type with non-zero density

Try: only 1bar on all reels (b2 = b3 = 0). Then bar_mixed = 0. ✓

Remaining base RTP must come from:
- bar1_pure at 5× (g510)
- bar1+wild at 10× (g1020)
- bar1+2wild at 20× (g20+)
- h7, dd combinations

For hit_base = 13.9%:
- P_cherry_1 = 8.4% requires cherry uniform c with 3c(1−c)² = 0.084 → c = 3.0% per reel
- Remaining hit: 5.5% from bar/h7 paths

With b1 = 0.25 uniform, d = 0.05 uniform:
- bar1_pure P = b1³ = 1.56% → RTP = 7.81pp ge5_lt10
- bar1+wild P = 3·b1²·d = 0.94% → RTP = 9.38pp ge10_lt20
- bar1+2wild P = 3·b1·d² = 0.19% → RTP = 3.75pp ge20_lt50
- 3-wild_pure P = d³ = 0.0125% → 2.5pp ge200_lt500
- Combined non-cherry hit: ~2.7% → total base hit ≈ 8.4 + 2.7 = 11.1%

**hit_base = 11.1% < 13.9% requirement**. So this clean structure underdelivers hit.

To raise hit, push b1 higher (e.g., b1 = 0.30):
- bar1_pure P = 2.7% → RTP = 13.5pp ge5_lt10
- bar1+wild P = 1.35% → RTP = 13.5pp ge10_lt20
- bar1+2wild P = 0.225% → RTP = 4.5pp ge20_lt50
- Combined non-cherry hit: ~4.3% → total base hit ≈ 8.4 + 4.3 = 12.7%

Still short of 13.9%. Need b1 ≈ 0.32-0.35:
- bar1_pure P = 3.3-4.3% → RTP = 16.4-21.4pp ge5_lt10
- bar1+wild P = 1.5-1.8% → RTP = 15-18pp ge10_lt20

**base sum_1_20 = g15 + g510 + g1020 = 8.4 + 16.4 + 15 = 39.8pp**

User target sum_1_20 base ∈ [26.3, 30.3] (corresponding to session 28-32).

**Structural conflict: at minimum g15 floor 8.4pp, sum_1_20 base is ≥ 35pp due to
the bar1_pure (5×) + bar1+wild (10×) requirement to lift hit. Sum_1_20 base
exceeds user target by ≥ 5pp.**

### 2.8 What about cherry-2 / cherry-3 to lift hit instead?

cherry-2 has mult 5× (ge5_lt10). cherry-3 has mult 15× (ge10_lt20). Adding
cherry-2 hit also increases P_ch1 (cross-reel cherry combinations create both
cherry-2 and cherry-1 outcomes).

cherry uniform c uniform on 3 reels:
- P_ch1 = 3c(1−c)²
- P_ch2 = 3c²(1−c)
- P_ch3 = c³

At c = 6%: P_ch1 = 15.9%, P_ch2 = 1.02%, P_ch3 = 0.022%.
g15 base from cherry alone = 15.9pp > 12pp cap. **Cherry can't fill hit without breaking g15**.

### 2.9 Mathematical inevitability

The M15 paytable couples hit floor to ge1_lt5 RTP via 2 pay sources:
- cherry-1 (1×): each 1% of cherry-1 P contributes 1pp to g15 RTP
- bar_mixed (2×, 4×): each 1% of bar_mixed P contributes 2-4pp to g15 RTP

To raise hit by Δ% via low-bucket pays:
- Adding cherry: ΔP_ch1 ≈ Δ; ΔRTP_g15 ≈ Δ (mult 1×)
- Adding bar_mixed: ΔP_bm ≈ Δ; ΔRTP_g15 ≈ 2-4·Δ (mult 2-4×)
- Adding bar1_pure: ΔP_b1p ≈ Δ; ΔRTP_g510 ≈ 5·Δ (mult 5×, goes to g510 not g15)

The "cheap hit at 5×" via bar1_pure costs 5pp RTP per 1% hit, plowing into
**g510**. Adding 4% bar1_pure hit pushes g510 base from ~0 to ~20pp.

session sum_1_20 = g15 + g510 + g1020 (+ ~1.74pp feature)
   = [g15 from cherry] + [g510 from bar1_pure] + [g1020 from bar1+wild] + feature

Bar1_pure at high b1 also unavoidably creates bar1+wild (10×) hits, which dump
into g1020. The ratio bar1+wild/bar1_pure ≈ (b1+2d)/b1 (rough — actually 3d/b1
weighted), so doubles g1020 contribution.

Plug into formula. At cherry uniform 3% (g15 = 8.4pp) + b1 uniform 0.35 +
d uniform 0.05:
- g15 base = 8.4pp
- g510 base = 5·b1³ ≈ 5·0.043 = 21.4pp
- g1020 base = 10·3·b1²·d ≈ 10·3·0.1225·0.05 = 18.4pp
- sum_1_20 base = 8.4 + 21.4 + 18.4 = 48.2pp
- session sum_1_20 ≈ 48.2 + 1.74 = 49.9pp

**vs user target [28, 32]pp. Excess = 18pp.**

To reduce sum_1_20, must reduce b1. But b1 ↓ reduces hit. Hit also ↓ → fails [15, 18].

### 2.10 Try cherry-only hit lift

cherry-1 has 1× mult. Each 1% P_ch1 adds 1pp to g15 ONLY.

For hit floor 13.9% via cherry alone:
- P_ch1 = 13.9% → cherry uniform c with 3c(1−c)² = 0.139 → c = 5.07% per reel
- P_ch2 = 3c²(1−c) = 3·0.00257·0.949 = 0.73%
- P_ch3 = c³ = 0.00013 = 0.013%

Cherry totals:
- g15 base = 13.9pp (cherry-1)
- g510 base = 5·0.73 = 3.65pp (cherry-2)
- g1020 base = 15·0.013 = 0.20pp (cherry-3)

**g15 base = 13.9pp > 12pp user cap. STILL FAILS.**

To fit g15 ≤ 12pp with cherry-only-hit strategy, c ≤ ~4.35% uniform:
- P_ch1 ≤ 12% (since g15 RTP = P_ch1 × 1 ≤ 12pp)
- Hit_base from cherry ≤ 12% + 0.5% + 0.005% = 12.5%

**Cherry-only hit ≤ 12.5%, below 13.9% requirement. FAIL.**

### 2.11 Conclusion: structural infeasibility

The 3 constraints (g15 ≤ 12pp, hit ≥ 15%, sum_1_20 ≤ 32pp) are **mutually
exclusive** under M15 paytable + LOCKED feature shape:

- cherry alone for hit max delivers hit ≈ 12.5% before g15 = 12 (saturates)
- non-cherry pays (bar1_pure, bar1+wild) lift hit but push sum_1_20 > 50pp
- bar_mixed lifts hit and g15 simultaneously; can't lift hit without g15

**The 500k random sweep confirms**: minimum session ge1_lt5 over all candidates
satisfying hit ≥ 15 + total RTP ∈ [94, 96] + R1 blank ∈ [30, 40]: **15.14pp**.
Minimum given ALL other hardlines (incl. 20+ buckets) pass: **17.94pp**.

Both **above the 12pp user cap by ≥ 3.1pp**.

---

## 3. Empirical validation

### 3.1 Targeted candidates (35 hand-tuned, scripts/m15_v11_design.py)

22 strategies across 8 lever classes (A-N, L1-L5, M1-M2, N1, plus
no_2bar_3bar variants and extreme configurations).

**Best n_pass = 4 fails** (out of 12 hardlines). No PASS.

Best 4-fail candidate (A1_cherry_R1_3_R2_3_R3_0_bars_v9):
- total_rtp = 93.21 (FAIL [94, 96])
- hit_session = 14.24 (FAIL [15, 18])
- R1_blank = 48.65 (FAIL [30, 40])
- ge1_lt5 = 18.92 (FAIL [10, 12])

### 3.2 Random sweep 1 (m15_v11_sweep.py, 50k candidates)

Sampled 37,023 feasible. **0 PASS**. **20 near-pass (1-2 fails)**.

Fail categories (% of feasible):
- total_rtp: 97.1%
- ge50_lt100: 96.9%
- ge100_lt200: 95.4%
- ge1_lt5: 87.5%
- sum_1_20: 80.9%

### 3.3 Random sweep 2 (m15_v11_sweep2.py, 100k, h7/dd anchored to v9)

Sampled 7,215 feasible. **0 PASS**. **470 near-pass**.

Fail category dominance:
- **ge1_lt5: 100% of feasible candidates fail**

The minimum g15 observed in this sweep was 18.48pp (vs cap 12pp).

### 3.4 Random sweep 3 (m15_v11_sweep3.py, structured priors, 500k)

Sampled 43,027 feasible. **0 PASS**. **61 near-pass**.

ge1_lt5 fail: 99.3% of feasible. Minimum g15 = 15.26pp (1.27pp better than sweep2
due to no_2bar_3bar prior, still above 12pp cap).

### 3.5 Minimum-finding sweep (m15_v11_find_minimum.py, 500k)

| condition | min session ge1_lt5 | sample size |
|---|---:|---:|
| any feasible (no hardlines required) | 6.55pp | 64,236 |
| hit + total + R1 pass | 15.14pp | 481 |
| ALL non-g15 hardlines pass | 17.94pp | (few) |

**Distribution of g15 when hit+total+R1 pass**:
- min: 15.14, p5: 16.63, p50: 19.73, p95: 23.00, max: 24.93

The min is 3.14pp above cap; p50 is 7.73pp above cap.

---

## 4. State of disk

- `slot_designer/machines/M15/weights/mode_1/weights.json` — **v9 unchanged**
- `slot_designer/machines/M15/verify.py` — **untouched (frozen per Rule 1)**
- `slot_designer/machines/M15/reel_strips.json` — **unchanged**
- `slot_designer/machines/M15/USER_HARDLINES.md` — **unchanged**
- `session_artifacts/M15/feasibility_v11.txt` — full candidate dump + sweep stats
- `session_artifacts/M15/scripts/m15_v11_design.py` — candidate evaluator + 22 candidates
- `session_artifacts/M15/scripts/m15_v11_sweep.py` — 50k sweep
- `session_artifacts/M15/scripts/m15_v11_sweep2.py` — 100k sweep (v9-anchored h7/dd)
- `session_artifacts/M15/scripts/m15_v11_sweep3.py` — 500k structured sweep
- `session_artifacts/M15/scripts/m15_v11_find_minimum.py` — minimum-finding sweep
- `session_artifacts/M15/v11_escalation.md` — this document

---

## 5. Self-critique (per WORKFLOW.md §3 + §2.6)

**Q1**: Did I exhaust the lever space?

A: YES.
- Cherry density (R1, R2, R3 independently and uniform): swept 0-15%.
- Bar densities (1bar, 2bar, 3bar per reel): swept 0-45%.
- High7 density: swept 0-20% per reel.
- doublediamond density: swept 0-8% per reel.
- Asymmetric configurations (R1 vs R2/R3 different bar types).
- Extreme configurations (single bar type per reel, only 1bar everywhere, etc.).
- 35 hand-tuned candidates + 650k random samples (3 sweeps × different priors).

**Q2**: Did I rigorously prove structural rather than handwave?

A: Both closed-form + empirical.
- §2.9-2.11 closed-form: cherry alone caps hit ≤ 12.5% before g15 = 12 saturates;
  non-cherry pays at mult ≥ 5× force sum_1_20 ≥ 35pp via b1_pure + b1+wild paths.
- §3 empirical: 500k random samples, min g15 with basic 3 pass = 15.14pp.

**Q3**: Did I avoid widening verify.py or moving goalposts?

A: YES. verify.py is byte-identical. weights.json is v9 unchanged. USER_HARDLINES.md
untouched.

**Q4**: Did I consider strip-layout (Lever J) restructure?

A: Per v10d_escalation.md §2.9, marginals are pre-strip statistics. Strip layout
does NOT affect marginals. So strip restructure can NOT change the bucket math.
(It can change visibility / blank-flank-diversity / visual rhythm — but those
are §13/§14 philosophy concerns, not g15 RTP.)

**Q5**: Could a creative lever exist?

A: Considered:
- Strip layout: NO (marginals invariant).
- Add new symbol type: locked by spec.
- Change feature shape: explicitly LOCKED per USER_HARDLINES.md "Feature shape locked".
- Change paytable multipliers: locked by user rule §a.
- Multi-tier wild (high tier wild on R3 with extra mult): not in M15 spec.
- Lever I = differential structure per reel: covered by 500k random + targeted.

**Q6**: Is the v11 conflict different from v10d?

A: YES. v10d's hardlines were BASE-centric (ge1_lt5 base ∈ [11, 14]pp, g510 + g1020
floors). v11 hardlines are SESSION-centric AND tighter on ge1_lt5 ([10, 12]
vs [11, 14] previous) AND relax g510/g1020 to "soft, exclude extremes". Also
sum_1_20 ≈ 30 is a new constraint not in v10d.

The new sum_1_20 ≈ 30 constraint **compounds** the g15 problem: in v10d, designer
could push hit floor via bar1_pure (large g510). In v11, g510 must stay near
session ~9-10pp, so bar1_pure base is capped at ~9pp, limiting bar1_pure P to
~1.8% — which lifts base hit by only ~1.8%. Combined with cherry-only hit max
of 12.5%, total hit ≤ 14.3% < 15% floor.

**v11 conflict is more severe than v10d.**

---

## 6. Recommended user decisions (no auto-action — user decides)

The structural gap of 3-6pp between min-feasible g15 and user cap can be unblocked
by relaxing ONE of these user-stated hardlines:

### A. Relax ge1_lt5 ceiling to [10, 16]pp (most direct)

Empirically achievable with strategies like cherry uniform 4% + 1bar=30% +
v9-like h7/dd. Best near-pass candidate has g15 = 15.26pp.

### B. Relax sum_1_20 ceiling to [38, 45]pp

Loosens the g510 + g1020 sum cap → allows bar1_pure + bar1+wild combinations
that satisfy hit floor.

### C. Relax 20+ bucket "preserve v9" tolerance to ±5pp

If g50100 + g100200 can grow to ~30 + 15pp session (vs v9 ~22 + 9), the
h7+wild paths can supply more RTP without breaking total cap.

### D. Drop hit_session floor to [12, 18]%

Empirically achievable. With cherry low + low bars, hit drops naturally.

### E. Authorize paytable change (locked by user rule §1)

- Change pay_id 8 (bar_mixed) mult 2× → 1× → bar_mixed enters gt0_lt1 (excluded
  from session hit). g15 then comprises only cherry-1.
- Change pay_id 9 (cherry-1) mult 1× → 0.5× → moves cherry-1 to gt0_lt1.

### F. Authorize feature shape change (locked by philosophy)

If trigger rate could rise to ~2% (currently 1.1%), feature contributes 95pp not
50.6pp → base RTP could be MUCH lower → g15 base much lower → hit floor reachable
via low-density cherry+bars. But per USER_HARDLINES.md: "Feature shape locked"
is philosophy/archetype anchored — explicitly NOT a lever per Rule 6.

Per Rule 2 ("ship only on all-GREEN"), **NONE of these are taken without explicit
user authorization**. Recommend asking main session to surface options A/B/C/D
to user for decision.

---

## 7. Citation index

- USER_HARDLINES.md v3 (sacred contract)
- WORKFLOW.md §2.6 boundary discipline + adversarial review
- DESIGN_PHILOSOPHY.md §7 top jackpot escalation; §8 hit decomposition; §15 PWDF
- `session_artifacts/M15/01b_baseline_report.md` §2 + §9 v9 bucket + feature data
- `session_artifacts/M15/v10d_escalation.md` prior structural escalation (base-centric)
- `session_artifacts/M15/scripts/m15_v11_design.py` candidate generator + analyzer
- `session_artifacts/M15/scripts/m15_v11_find_minimum.py` minimum-finding sweep
- `session_artifacts/M15/feasibility_v11.txt` full audit log
- `slot_designer/core/engine/evaluator.py` evaluate_payline (pay logic)
- `slot_designer/core/devtools/analytic_rtp.py` analytic_profile (bucket math)
- `slot_designer/machines/M15/plugins/feature.py` feature EV (closed-form)
