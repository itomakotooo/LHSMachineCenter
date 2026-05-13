# M15 v12 mode 1 — STRUCTURAL ESCALATION (2026-05-11 wave 12)

> **Status**: STRUCTURAL CONFLICT after exhaustive search under v4 widened tolerance.
>
> Per the v4 brief (user option C relaxation: sum_1_20 ±2pp + 20+ each ±5pp around v9),
> I designed 30+ hand-tuned candidates + ran 2.5M random sweeps. **NO candidate
> satisfies all user v4 hardlines simultaneously.**
>
> The conflict is the same as v11 — **3 user hardlines jointly infeasible** under M15
> paytable + LOCKED feature shape:
>
>   1. session ge1_lt5 ∈ [10, 12]pp
>   2. session hit_rate ∈ [15, 18]%
>   3. session total RTP ∈ [94, 96]%
>
> v4's relaxation of 20+ buckets (from ±2pp to ±5pp) and sum_1_20 (clarified as ±2pp)
> did NOT relax any of the above 3 walls.
>
> **Empirical min g15 with all OTHER v4 hardlines pass = 17.23pp** (vs cap 12pp; gap **+5.23pp**).
> v11 had min = 17.94pp under tighter constraints; v4 gained 0.7pp via wider 20+ tolerance.
>
> **v9 weights remain on disk unchanged. verify.py untouched. reel_strips.json unchanged. USER_HARDLINES.md unchanged.**

---

## 1. User v4 hardlines (machines/M15/USER_HARDLINES.md v4)

### Hard quantitative (sacred)

| # | hardline | band |
|---|---|---|
| 1 | Paytable byte-identical | spec.json `pays` block |
| 2 | Feature shape locked | feature_params byte-equal v9 |
| 3 | Avoid 1000× bet+ rewards | qualitative |
| 4 | Jackpot any-reel marginal ≤ 0.6% | per reel |
| 5 | Hit_session (incl. feature trigger) | [15, 18]% |
| 6 | Total RTP | [94, 96]% |
| 7 | R1 blank marginal | [30, 40]% |
| 8 | **session ge1_lt5 RTP** | **[10, 12]pp** ← blocker |
| 9 | session sum_1_20 | [28, 32]pp |
| 10 | session ge20_lt50 | [22, 32]pp (v9 27 ±5) |
| 11 | session ge50_lt100 | [17, 27]pp (v9 22 ±5) |
| 12 | session ge100_lt200 | [4, 14]pp (v9 9 ±5) |
| 13 | session ge200_lt500 | [0, 7.3]pp (v9 2.3 +5) |

### Already relaxed (informational)
- CV (base / feature)
- base : feature split
- P(count_x = 1)
- Cherry §2 archetype visibility

---

## 2. Closed-form structural proof

### 2.1 Feature contribution LOCKED (per user rule "Feature shape locked")

Computed via `m15_v12_design._compute_feature_bucket_ev` (feature_params byte-equal v9):

| bucket | feature EV per trigger | feature RTP @ 1.127% trigger |
|---|---:|---:|
| ge1_lt5 | 0.000× | 0.000pp |
| ge5_lt10 | 0.069× | 0.076pp |
| ge10_lt20 | 1.512× | 1.663pp |
| ge20_lt50 | 16.527× | 18.180pp |
| ge50_lt100 | 18.421× | 20.263pp |
| ge100_lt200 | 7.577× | 8.334pp |
| ge200_lt500 | 1.838× | 2.022pp |
| ge500+ | 0.057× | 0.062pp |
| **total** | **46.000×** | **50.6pp** |

Note: feature contributes **0pp to ge1_lt5**. The ge1_lt5 cap [10, 12]pp must
be satisfied by the BASE game alone.

### 2.2 Hit decomposition (paytable-driven)

Pays landing in ge1_lt5 (mult ∈ [1, 5)):
- **pay_id 9** (cherry-1, 1×): any 1 cherry on payline
- **pay_id 8** (bar_mixed_pure, 2×): all 3 reels show bars, not all same
- **pay_id 8** (bar_mixed + 1 wild, 4×): 2 reels show different bars + 1 wild

Pays NOT in ge1_lt5:
- pay_id 7 (bar1_pure, 5×) → ge5_lt10
- pay_id 71 (cherry-2, 5×) → ge5_lt10
- pay_id 5 (bar2_pure, 10×) → ge10_lt20
- pay_id 7 (bar1+1wild, 10×) → ge10_lt20
- pay_id 4 (cherry-3, 15×) → ge10_lt20
- pay_id 3 (bar3_pure, 20×) → ge20_lt50
- pay_id 8 (bar_mixed+2wild, 8×): KILLED by line_3_same priority (becomes bar1/2/3+2wild)
- (and many higher-mult pays in 20+ buckets)

### 2.3 Hit-floor → g15 floor inequality

Let:
- a = P(cherry-1) → g15 contrib = a × 1
- b = P(bar_mixed_pure) → g15 contrib = b × 2
- w = P(bar_mixed + 1 wild) → g15 contrib = w × 4

Then:
- g15_base = a + 2b + 4w
- Hit contribution from g15: P_hit_in_g15 = a + b + w
- Other hit (outside g15) = c, with avg mult ≥ 5

Session hit = a + b + w + c + trigger(1.1%) ≥ 15%
→ a + b + w + c ≥ 13.9%

### 2.4 Maximum c (hit outside g15) under v4 bucket caps

Hit outside g15 lands in {ge5_lt10, ge10_lt20, ge20_lt50, ge50_lt100, ...}.

Session bucket caps:
- sum_1_20 ≤ 32 → g510 + g1020 ≤ 32 - g15 ≤ 32 - 10 = 22 (with g15 ≥ 10)
- ge20_lt50 ≤ 32 → base ge20_lt50 ≤ 32 - 18.18 = 13.82
- ge50_lt100 ≤ 27 → base ≤ 6.74
- ge100_lt200 ≤ 14 → base ≤ 5.67
- ge200_lt500 ≤ 7.3 → base ≤ 5.28

c partitions across buckets. For each c_bucket, max hit contribution = RTP_cap / min_mult_in_bucket:
- c_g510 ≤ 22 / 5 = 4.4% (if entirely bar1_pure or cherry-2 at 5×)
- c_g1020 ≤ 22 / 10 = 2.2% (bar2_pure or bar1+1wild at 10×, sharing the 22pp budget with g510)
- c_g2050 ≤ 13.82 / 20 = 0.691% (at 20×)
- c_g50100 ≤ 6.74 / 60 = 0.112%
- c_g100200 ≤ 5.67 / 120 = 0.0473%
- c_g200500 ≤ 5.28 / 200 = 0.0264%

Constraints couple: bar_pure (g510/g1020) and bar+wild (g1020/g2050) come from the SAME
underlying bar density structure. Increasing bar density to push g510 also lifts
bar_mixed (which goes to g15) AND bar+wild (which goes to higher buckets).

**Empirical exhaustive sweep result** (2.5M candidates with v4 constraints, R1 blank
∈ [30, 40], R2/R3 non-blank ≤ R1 non-blank):

> Max c (P_hit outside g15) with all v4 non-g15 hardlines pass = **~3.0%**
> (observed at min-g15 candidate, where c partitions across ge20+ buckets via
> bar+wild + h7+wild paths, and g510+g1020 absorb remaining hit at mid mults)

### 2.5 g15 lower bound

P_hit_in_g15 = a + b + w ≥ 13.9% - 3.0% = 10.9%

Optimal allocation (minimize g15 given P_hit_in_g15 = 10.9%):
- All cherry-1 (a = 10.9%, b = w = 0): g15 = 10.9pp ✓ in band!
- But: b = 0 requires NO bar_mixed_pure → either no bars OR each-reel-only-1-bar
- AND: cherry-1 P = 10.9% requires cherry marg c such that 1-(1-c1)(1-c2)(1-c3) ≥ 0.109
  - Uniform c = 0.037 → P_ch1 = 0.107 (close)
  - Uniform c = 0.040 → P_ch1 = 0.115
  - Need c ≈ 0.0378 uniform

### 2.6 But: each-reel-only-1-bar + cherry 3.78% has structural issues

**Issue A** — each-reel-only-1-bar still produces bar_mixed_w1wild:

With R1=only-1bar, R2=only-2bar, R3=only-3bar at 25% each, and dd ~5% each:
- bar_mixed_pure P = 0.25 × 0.25 × 0.25 = 0.0156 = 1.56% → 2 × 1.56 = 3.13pp g15
- bar_mixed_w1wild orderings (2 diff bars + 1 wild):
  - wild on R1: (wild_R1, 2bar_R2, 3bar_R3) = 0.05 × 0.25 × 0.25 = 0.00313
  - wild on R2: 0.25 × 0.05 × 0.25 = 0.00313
  - wild on R3: 0.25 × 0.25 × 0.05 = 0.00313
  - Sum = 0.0094 → 4 × 0.0094 = 3.75pp g15
- bar_mixed total g15 = 6.88pp

**Cannot use each-reel-only-1-bar with substantial bars and avoid bar_mixed in g15.**

To bring bar_mixed g15 < 1pp: bars ≤ 0.13 each per reel. But then R1 non-blank requires
filling 62 - 3.78 - 13 - 0.5 = 44.7pp from h7 + dd. At h7 + dd > 30% on R1, the h7+wild
paths blow up RTP > 100%.

**Issue B** — when each reel has only its dedicated bar, bar_pure pays die:
- bar1_pure = b1_R1 × b1_R2 × b1_R3. R2 has b1_R2 = 0 (only 2bar). → bar1_pure_P = 0.
- Similar for bar2_pure (R1=0 in 2bar) and bar3_pure (R1=R2=0 in 3bar).

→ No bar_pure RTP in g510 / g1020 / g2050. sum_1_20 collapses to ~g15 only.

### 2.7 Empirical confirmation

500k random sweep (m15_v12_targeted_sweep.py): 103,820 feasible candidates.

| metric | value |
|---|---|
| PASS (all hardlines) | **0** |
| NEAR-PASS (1-2 fails) | many, all g15 = 17-22pp |
| Min g15 with ALL OTHER hardlines PASS | **17.23pp** |
| Max P_hit outside g15 in passing config | ~3% |

The 17.23pp empirical floor exceeds 12pp cap by **5.23pp**.

### 2.8 Marginal improvement over v11 from v4 relaxation

| version | min g15 (all non-g15 pass) | cap | gap |
|---|---:|---:|---:|
| v11 (tighter 20+) | 17.94pp | 12pp | +5.94pp |
| v12 (v4 widened 20+) | **17.23pp** | 12pp | **+5.23pp** |

v4's wider 20+ bands gave **0.7pp improvement**. Far from closing the 6pp wall.

### 2.9 Why v4 widening didn't help much

v4 widened 20+ each by ±5pp (vs v11's ±2pp). This unlocked more h7+wild + bar+wild
paths in ge20+/ge50+. But these contribute to **non-g15 hit** at high mults — only ~1pp
of hit slack from the widening (each 1% hit at mult 30× = 30pp RTP, hard to fit even
with widening).

Total non-g15 hit lift from v4 widening: ~1.5%. Min g15 dropped by ~0.7pp accordingly
(consistent with structure).

To close the 5.23pp gap, need to lift non-g15 hit by another ~5-8%. That requires:
- Either substantially widening 20+ buckets BEYOND v4 (e.g., ge100_lt200 → [0, 30]pp,
  ge200_lt500 → [0, 25]pp) — way more than ±5pp from v9
- Or accepting g15 > 12pp band breach

---

## 3. Empirical search summary

### 3.1 Hand-tuned candidates (m15_v12_design.py)

40+ candidates across 8 strategies (A: each-reel-1-bar, B: uniform low bars,
C: asym bars + asym cherry, D: cherry-R1-only, E-K: parameter sweeps, L-M: cherry-low + h7-high).

**Best n_fail = 1** (only g15 fails). Best candidate g15 = 17.23pp.

### 3.2 Random sweeps

| sweep | samples | feasible | PASS | best |
|---|---:|---:|---:|---|
| m15_v12_sweep.py | 200,000 | 200,000 | 0 | 355 near-pass, min g15 ~17.4pp |
| m15_v12_targeted_sweep.py | 500,000 | 103,820 | 0 | min g15 ~17.2pp |
| m15_v12_minimize_g15.py | 2,000,000 | 296,020 | 0 | min g15 (1-fail only) 17.23pp |
| (final empirical) | 2,000,000 | 296,020 | 0 | min g15 with all-else-pass = **17.228pp** |

ge1_lt5 fail rate in feasible candidates: **99.8%-100%**.

### 3.3 Best-found g15-only-fail candidate

```
total_rtp=94.746  base_rtp=44.146  hit_session=15.481  trigger=1.100
R1 blank: 32.71%  R2 blank: 63.37%  R3 blank: 57.45%
Buckets (session):
  ge1_lt5     = 17.228pp  (FAIL [10, 12])
  ge5_lt10    =  1.746pp
  ge10_lt20   =  9.812pp
  ge20_lt50   = 28.653pp  PASS [22, 32]
  ge50_lt100  = 23.308pp  PASS [17, 27]
  ge100_lt200 = 11.409pp  PASS [4, 14]
  ge200_lt500 =  2.527pp  PASS [0, 7.3]
sum_1_20 = 28.79pp        PASS [28, 32]

Marginals:
  R1: cherry 4.29, 1bar 19.61, 2bar 16.62, 3bar 4.66, high7 19.44, dd 2.25, jp 0.41
  R2: cherry 4.27, 1bar 3.87, 2bar 19.43, 3bar 0.35, high7 4.37, dd 3.88, jp 0.46
  R3: cherry 1.47, 1bar 4.40, 2bar 23.27, 3bar 8.08, high7 1.12, dd 2.89, td 1.10, jp 0.23
```

ALL non-g15 hardlines GREEN; g15 17.23pp vs cap 12pp.

---

## 4. State of disk

- `slot_designer/machines/M15/weights/mode_1/weights.json` — **v9 unchanged**
- `slot_designer/machines/M15/verify.py` — **untouched (frozen)**
- `slot_designer/machines/M15/reel_strips.json` — **unchanged**
- `slot_designer/machines/M15/USER_HARDLINES.md` — **unchanged**
- `session_artifacts/M15/feasibility_v12.txt` — candidate dump
- `session_artifacts/M15/scripts/m15_v12_design.py` — 40 hand-tuned candidates
- `session_artifacts/M15/scripts/m15_v12_sweep.py` — 200k random sweep
- `session_artifacts/M15/scripts/m15_v12_targeted_sweep.py` — 500k targeted sweep
- `session_artifacts/M15/scripts/m15_v12_minimize_g15.py` — 2M minimize-g15 search
- `session_artifacts/M15/v12_escalation.md` — this document

---

## 5. Self-critique (per WORKFLOW.md §3 + §2.6)

**Q1**: Did I exhaust the lever space?

A: YES.
- Cherry per reel: swept 0-6% (uniform and asymmetric R1/R2/R3 patterns).
- Bar densities per reel: swept 0-30% per bar type per reel.
- Asymmetric bars: each-reel-1-bar (extreme) tested explicitly.
- h7: swept 1-28% per reel.
- dd: swept 0.5-18% per reel.
- Jackpot held at ≤0.6% cap.
- Topdollar held at 0.011 (preserve feature trigger 1.127% ≈ v9).
- 30+ hand-tuned candidates + 2.5M random samples across 4 different sampling strategies.

**Q2**: Did I rigorously prove structural rather than handwave?

A: Closed-form + empirical.
- §2.5 closed-form: g15 ≥ P_hit_in_g15 ≥ hit_floor - max_c_outside. With v4's 20+ bands,
  max_c_outside ≈ 3% → g15 ≥ 10.9% under cherry-only (bar_mixed = 0).
- §2.6 closed-form: bar_mixed = 0 requires each-reel-only-1-bar OR very low bars.
  Each-reel-1-bar with substantial bars still has bar_mixed_w1wild path → 3-7pp g15.
  Low bars (≤13% per reel) eliminate bar_mixed but require ~30% h7+dd on R1 to fill
  blank, which inflates RTP > 100%.
- §3 empirical: 2.5M candidates, min g15 = 17.23pp.

**Q3**: Did I avoid widening verify.py / moving goalposts?

A: YES. verify.py byte-identical. weights.json v9 unchanged. USER_HARDLINES.md unchanged.

**Q4**: Did I consider strip-layout (§13/§14) restructure?

A: Per v10d/v11 escalation §2.9, marginals are pre-strip statistics. Strip restructure
preserves marginals → cannot change bucket math. Strip can only affect visibility
(§13/§14/§15 philosophy concerns, not g15 RTP).

**Q5**: Is v4's relaxation different in effect from v11?

A: v4 unblocks ~0.7pp of g15 (via wider 20+ allowing more h7+wild hit). The 17.23pp
floor remains 5.23pp above 12pp cap.

**Q6**: Did I miss any creative lever?

A: Considered:
- **Strip layout / §15 mechanism B redistribution**: pre-strip marginal invariant, no effect.
- **Asymmetric bars per reel** (each-reel-1-bar): tested explicitly, doesn't help.
- **R1 winners-friendly + R2/R3 sparse**: tested via redistribution; helps slightly but
  cherry path still dominates g15.
- **Paytable change**: locked by user rule §1 ("Paytable永远不改").
- **Feature shape change**: locked by user rule (philosophy-anchored, "Feature shape locked").
- **Jackpot density above 0.6%**: locked by universal rule.

No remaining levers.

---

## 6. Recommended user decisions (no auto-action — user decides per §2.6)

The structural gap of 5.23pp between min-feasible g15 (17.23pp) and user cap (12pp)
can ONLY be unblocked by relaxing one of these **user-stated** hardlines:

### A. Relax ge1_lt5 ceiling to [10, 18]pp (most direct)

Empirically achievable. Best near-pass candidate (§3.3) has g15 = 17.23pp, all other
hardlines PASS. Sets a new sustainable boundary for v12.

**Pros**: minimum change to user contract; only g15 widens.
**Cons**: cherry-1 + bar_mixed still dominant in player visual experience.

### B. Relax hit_session floor to [13, 18]%

If hit floor drops from 15 to ~13, base hit can drop ~2%. Direct g15 reduction
proportional. Likely unblocks g15 ∈ [12, 15]pp with hit ∈ [13, 14].

**Pros**: cherry-1 freq drops → less "boring small win" feel; volatility nudges up.
**Cons**: player hit-rate experience changes; deviation from "low-volatility classic" archetype.

### C. Relax sum_1_20 ceiling to [28, 40]pp

Allows MORE g510/g1020 contribution → more hit at mid mults (5/10×) without bumping g15.
Each 1pp added to sum_1_20 cap = ~1-2pp room for g15 lower bound shift.

Estimated: sum_1_20 cap → 40pp would unblock ~3-4pp g15 floor.

**Pros**: low-volatility feel preserved; widens hit landscape.
**Cons**: shifts the "shape narrative" (player wins distribute more in mid).

### D. Relax 20+ buckets to ±10pp (further than v4's ±5pp)

Unlocks more h7+wild + bar+wild paths to push hit at high mults.
Likely improvement: maybe 1-2pp g15 floor reduction (diminishing returns vs v4).

Combined A + D: small marginal gain. Not recommended alone.

### E. (Locked) Paytable change — NOT a v12 option

User rule §1 ("Paytable永远不改") explicitly locks. Cannot propose.

### F. (Locked) Feature shape change — NOT a v12 option

User rule "Feature shape locked" — philosophy-anchored. Cannot propose.

### Recommendation

Most direct option: **Option A — widen ge1_lt5 to [10, 18]pp**. This is the natural
band given the structural floor and accepts the cherry-1 + bar_mixed dominance that
the M15 paytable architecture (cherry-anywhere + bar-mixed at low mult) inherently
produces.

Alternative: **Option C — widen sum_1_20 to [28, 40]pp**. Allows shape redistribution
without g15 widening. Worth exploring if user wants to preserve g15 ceiling intent.

---

## 7. Citation index

- USER_HARDLINES.md v4 (sacred contract, M15 specific)
- WORKFLOW.md §2.6 (boundary discipline)
- DESIGN_PHILOSOPHY.md §1, §7, §8, §12, §15
- session_artifacts/M15/01b_baseline_report.md §2 + §9 (v9 baseline + feature EV)
- session_artifacts/M15/v11_escalation.md (prior structural escalation under tighter tolerance)
- session_artifacts/M15/scripts/m15_v12_design.py (40 candidates)
- session_artifacts/M15/scripts/m15_v12_targeted_sweep.py (500k sweep)
- session_artifacts/M15/scripts/m15_v12_minimize_g15.py (2M minimize search)
- session_artifacts/M15/feasibility_v12.txt (full audit log)
- slot_designer/core/engine/evaluator.py (pay logic — bar_mixed / line_3_same / line_3_group)
- slot_designer/core/devtools/analytic_rtp.py (bucket math)
- slot_designer/machines/M15/plugins/feature.py (feature EV, locked v9)
