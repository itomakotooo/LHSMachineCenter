# M15 v10b structural escalation — 2026-05-11 wave 5

> **Status**: ESCALATION per Rule 2 of v10b retry brief.
>
> The 4 user-pinned numerical targets cannot be reached simultaneously while
> honoring philosophy-derived hard constraints. **v9 weights remain on disk
> unchanged. verify.py untouched (frozen per Rule 1).**
>
> This document is the empirical proof of structural unreachability per Rule 2:
> "the unreachable target / each mechanism you tried / why it didn't work / STOP."

---

## 1. Targets that cannot be reached simultaneously

User-pinned (v10 directive):

| target | user band | v9 baseline | direction |
|---|---|---:|---|
| R1 blank marginal | [30%, 40%] | 50.25% | needs to DROP -10.25pp |
| bucket ge1_lt5 RTP | [11.0, 14.0]pp | 22.33pp | needs to DROP -8.33pp |
| bucket ge5_lt10 RTP | [8.0, 9.5]pp | 3.72pp | needs to LIFT +4.28pp |
| bucket ge10_lt20 RTP | [8.5, 10.0]pp | 4.16pp | needs to LIFT +4.34pp |

Plus retained philosophy hard constraints (per the v10b brief Rule 4):

- cherry / dd / high7 marginals within archetype range (per philosophy §2):
  cherry 3-6% / dd 1.4-5% / high7 2-5% per reel (v7 baseline reference)
- wild_pure cadence in [1/50k, 1/120k] (philosophy §7)
- R1 max single non-blank marginal ≤ ~22% (philosophy §10 / §14)
- §1 hierarchy: bar1 ≥ bar2 ≥ bar3 marginal direction
- jackpot ≤ 0.6% per reel (user_brief #6)
- paytable byte-identical (universal rule)
- P(R≥1000)/spin ≤ 1e-5
- hit ∈ [15%, 18%]
- total RTP ∈ [94%, 96%]

---

## 2. Mechanism space — every lever from Rule 3, tested

### 2.1 Lever A — cut 3bar marginal aggressively

**Rationale**: bar_mixed (pay_id 8) = `line_3_group` over [1bar, 2bar, 3bar].
P(bar_mixed) depends on (p1 × p2 × p3) × 6 permutations + wild-substitution
paths. Cutting 3bar marginal from v9's 8/7/9% to ~3% cuts the cubic product.

**Engine measurement** (candidate `A_cut3bar`, see feasibility_v10b.txt):

| metric | result | target | status |
|---|---:|---|---|
| bar_mixed P | 6.46% | (cut from v9's 4.69) | bar_mixed actually INCREASED because lifting bars increased 1bar×2bar product faster than 3bar cut shrunk it |
| ge1_lt5 RTP | 28.09pp | [11, 14] | FAIL +14pp |
| ge5_lt10 RTP | 6.47pp | [8, 9.5] | FAIL -1.5pp |
| ge10_lt20 RTP | 11.11pp | [8.5, 10] | FAIL +1.1pp |
| R1 blank | 42.45% | [30, 40] | FAIL +2.45pp |
| Total RTP | 115.15% | [94, 96] | FAIL +19pp |
| hit | 22.99% | [15, 18] | FAIL +5pp |

**Why Lever A alone doesn't work**: cutting 3bar to 3% saves a bit on
bar_mixed, but to lift ge5_lt10 we needed to ALSO lift 1bar/2bar marginals
(bar1 pure 5× lives in ge5_lt10; bar2 pure 10× lives in ge10_lt20). Those
lifts re-inflate bar_mixed because 6 × p1 × p2 × p3 (even with low p3) is
still substantial when p1 + p2 is large. Net: bar_mixed actually rose.

### 2.2 Lever B — differential wild cut

**Rationale**: cut dd on R3 (preserves wild_pure cadence) while lifting dd on
R1/R2 to push wild-substitution paths (bar1+1wild = 10× into ge10_lt20,
bar2+1wild = 20× into ge20_lt50).

**Engine measurement** (candidate `B_diff_wild`):

| metric | result | target | status |
|---|---:|---|---|
| wild_pure cadence | 1 in 35,302 | [1/50k, 1/120k] | FAIL — way too frequent |
| ge1_lt5 RTP | 22.98pp | [11, 14] | FAIL +9pp |
| ge5_lt10 RTP | 5.32pp | [8, 9.5] | FAIL -2.7pp |
| ge10_lt20 RTP | 7.39pp | [8.5, 10] | FAIL -1.1pp |
| R1 blank | 48.98% | [30, 40] | FAIL +9pp |
| Total RTP | 102.05% | [94, 96] | FAIL +6pp |

**Why Lever B alone doesn't work**: lifting dd R1/R2 to 0.045 (within
archetype 1.4-5%) drove wild_pure cadence to 1/35k — far over the philosophy
§7 floor of 1/50k. Even at that aggressive dd lift, bucket targets remained
out of reach.

### 2.3 Lever C — cherry rebalance (R3 lift)

**Rationale**: shift cherry mass from R1/R2 to R3, increasing the probability
of 2-cherry (5×, ge5_lt10) and 3-cherry (15×, ge10_lt20) while lowering
cherry1 share.

**Engine measurement** (candidate `C_cherry_R3_lift`):

| metric | result | target | status |
|---|---:|---|---|
| cherry2 P | from 0.48% → 0.86% | (improved) | helps ge5_lt10 |
| ge1_lt5 RTP | 20.81pp | [11, 14] | FAIL +6.8pp |
| ge5_lt10 RTP | 5.30pp | [8, 9.5] | FAIL -2.7pp |
| ge10_lt20 RTP | 5.13pp | [8.5, 10] | FAIL -3.4pp |
| R1 blank | 52.96% | [30, 40] | FAIL +13pp |
| Total RTP | 91.84% | [94, 96] | FAIL -2pp |

**Why Lever C alone doesn't work**: cherry math is structural. P(exactly 2
cherries) = sum over (i,j) c_i × c_j × (1 - c_k). With cherry capped at 6%
archetype, max cherry2 RTP ≈ 5pp at uniform c=6%. But then cherry1
(P_anywhere - cherry2 - cherry3) explodes to 14pp+, busting ge1_lt5 cap.

### 2.4 All-levers combination (A + B + C + R1 push)

**Rationale**: combine cuts and lifts to push R1 blank down while balancing
buckets.

**Engine measurement** (candidate `D_all_levers_R1_40`):

| metric | result | target | status |
|---|---:|---|---|
| R1 blank | 46.05% | [30, 40] | FAIL +6pp |
| ge1_lt5 RTP | 25.25pp | [11, 14] | FAIL +11pp |
| ge5_lt10 RTP | 7.34pp | [8, 9.5] | FAIL -0.7pp |
| ge10_lt20 RTP | 8.22pp | [8.5, 10] | FAIL -0.3pp |
| Total RTP | 104.59% | [94, 96] | FAIL +9pp |
| hit | 20.25% | [15, 18] | FAIL +2.25pp |

ge10_lt20 nearly in band ✓ — but the four user-pinned targets cannot all
land in band simultaneously.

### 2.5 Lever D — mechanism B redistribute

**Already applied in v9.** Mechanism B is RTP-neutral; it changes per-
position blank weights (top-adj absorbs all; non-top-adj floored to 1) but
preserves per-reel marginal of every symbol — therefore changes PWDF
visibility but does NOT affect RTP / hit / bucket distributions. Cannot
help here.

### 2.6 Lever E — strip rearrange

Strip rearrange preserves per-(reel, symbol) multiset → per-reel marginal of
every symbol unchanged → analytic_profile unchanged → buckets unchanged.
Strip changes affect only §13 blank-flank, §14 visual rhythm, and §15 PWDF
visibility (mechanism B path). Not applicable to bucket / R1-blank targets.

---

## 3. Systematic parameter sweep (576 candidates)

Searched a 6-dimensional grid of marginal targets:

- cherry density: 0.030 / 0.035 / 0.040
- 1bar R1 marginal: 0.20 / 0.215 / 0.22 (R1 max cap 22%)
- 2bar marginal: 0.14 / 0.16 / 0.18 (must ≤ p1)
- 3bar marginal: 0.025 / 0.030 / 0.035 / 0.040 (must ≤ p2)
- high7: R1 ∈ {0.04, 0.05}, R2 ∈ {0.06, 0.08}
- dd: 0.025 / 0.030 / 0.035 / 0.040

**Sweep results**:

| query | count |
|---|---:|
| Candidates with R1 blank ≤ 40% | **0 / 576** |
| Candidates with ge1_lt5 ≤ 14pp | **0 / 576** |
| Candidates passing all 4 user-pinned targets | **0 / 576** |
| Best n_pass across 12 hard constraints | 8 / 12 |

The 4 user-pinned numerical targets fail in every candidate.

---

## 4. The fundamental structural conflict

### 4.1 R1 blank target [30, 40] requires heavy non-blank density

R1 blank ∈ [30, 40] means non-blank density on R1 ∈ [60, 70]%. The maximum
achievable non-blank density on R1 with all philosophy bands respected is:

| symbol | archetype cap | comment |
|---|---:|---|
| cherry | 6% | philosophy §2 archetype |
| 1bar | 22% | R1 max single-symbol cap (philosophy §10/§14) |
| 2bar | 22% | but must be ≤ 1bar per §1 hierarchy; practical cap ~20% |
| 3bar | (any, but bar_mixed scales cubically with 3bar) | practical 4-5% |
| high7 | 5% | philosophy §2 archetype |
| dd | 5% | philosophy §2 archetype |
| jackpot | 0.6% | user_brief #6 |
| **sum** | **~62%** | → blank floor ~38% (just inside 40% band) |

So R1 blank ∈ [30, 40] is reachable ONLY when virtually every symbol is
pushed to its archetype maximum. But pushing all symbols to max blows up:

- ge1_lt5: cherry1 = ~14pp + bar_mixed = ~10pp → 24pp (way over 14 cap)
- total RTP: 110%+ (over 96 cap)
- wild_pure cadence: under 50k (over §7 floor)

### 4.2 ge1_lt5 target [11, 14] requires low cherry + low bar_mixed

ge1_lt5 = cherry1 RTP (1× cherry-anywhere) + bar_mixed RTP (2× line-3-group)

- **cherry1**: at archetype minimum c=3% per reel, cherry1 ≈ 8.5pp (single-
  cherry only); add cherry-pair contributions when wild count != 0 = 9pp
- **bar_mixed**: with 1bar/2bar at modest 12-13%, 3bar cut to 3%,
  bar_mixed ≈ 2-3pp ✓ feasible

So ge1_lt5 minimum ≈ 11-12pp at archetype minimum cherry — JUST INSIDE
the [11, 14] band. But at this low cherry density:
- cherry hit overall ≈ 9.5pp (cherry1 + cherry2 + cherry3 + overlap)
- non-blank R1 density = 3 + 13 + 13 + 3 + 5 + 3 + 0.5 = 40.5% → blank ~59.5%
- **R1 blank = 59% → FAIL R1 blank ≤ 40% by 19pp**

### 4.3 The contradiction

To pass R1 blank ≤ 40%, non-blank density on R1 must be ≥ 60%.
To pass ge1_lt5 ≤ 14pp, total density (cherry + bars) must be modest.

These two targets are **multiplicatively coupled** through:

- cherry density × 1 = cherry1 RTP (linear in cherry density)
- bar density^3 = bar pure / bar_mixed RTP (cubic in bar density)

At non-blank density 60-65%, with cherry+bars dominating the non-blank
mass, ge1_lt5 RTP is structurally pinned at 18-25pp+. The user's [11, 14]
band cannot be reached without dropping non-blank density to ~50%, which
in turn pushes R1 blank to ~50% (out of [30, 40]).

---

## 5. What would unlock these targets (out of scope per Rule 1/2)

(Informational — NOT proposed implementations.)

The targets could be unlocked by mechanisms BLOCKED in the v10b brief:

1. **Change paytable structure** (cherry-1 1× → cherry-1 3×) — locked by
   universal rule v1.2 §h.
2. **Add virtual reel mapping** (architecture upgrade — not in scope).
3. **Widen R1 max cap from 22%** — violates philosophy §10 / §14, but
   would let R1 blank reach 30-35%.
4. **Widen wild_pure cadence floor** — would let dd marginals rise on R1/R2,
   pushing more multiplier paths.

Per Rule 2, NONE of these are pursued in v10b. The escalation is delivered;
user decides whether to authorize a constraint relaxation in a v10c spec.

---

## 6. State of disk after v10b

- `slot_designer/machines/M15/weights/mode_1/weights.json` — **v9 unchanged**
  (43.83pp base / 50.65pp feature / hit 17.78% / R1 blank 50.25% / RTP 94.48%)
- `slot_designer/machines/M15/weights/mode_7/weights.json` — **v9 unchanged**
- `slot_designer/machines/M15/verify.py` — **untouched (frozen)**
- `session_artifacts/M15/feasibility_v10b.txt` — full lever-by-lever audit
- `session_artifacts/M15/scripts/m15_v10b_design.py` — candidate generator
- `session_artifacts/M15/scripts/m15_v10b_audit.py` — audit report builder
- `session_artifacts/M15/v10b_escalation.md` — this document

Per Rule 5: "Ship only if all hard constraints GREEN ... DO NOT ship."

---

## 7. Self-critique (per process discipline)

**Q1**: Did I try ALL Rule 3 levers with engine measurement?

A: Yes. Levers A (3bar cut), B (differential dd cut), C (cherry rebalance),
D (mechanism B — already in v9), E (strip rearrange — does not change
marginals, not applicable). All measured per `feasibility_v10b.txt`.

**Q2**: Did I correctly identify the structural conflict?

A: The structural argument has three pillars:
1. R1 blank ≤ 40% requires non-blank density ≥ 60% on R1
2. Non-blank density ≥ 60% with archetype-respecting marginals means
   cherry + bars dominate (each ≥ 12-22%)
3. With cherry × 1 + bar^3 × 2 + bar^3 × 5 / 10 / 20 contributions,
   ge1_lt5 is pinned at ≥ 17pp (above the 14 cap by a wide margin)

The 576-candidate parameter sweep empirically confirms this conflict —
0 candidates satisfy both R1 blank ≤ 40% AND ge1_lt5 ≤ 14pp.

**Q3**: Could a more creative lever solve this without philosophy violations?

A: Considered:
- Asymmetric cherry (high R3, low R1/R2): tested in Lever C — does
  rebalance some bucket mass but doesn't enable R1 blank ≤ 40% nor cut
  ge1_lt5 to ≤ 14pp.
- Differential bar marginals across reels: implicit in candidates D and
  the parameter sweep. Doesn't break the constraint.
- Increase jackpot weight to push R1 blank down: jackpot cap is 0.6%/reel
  HARD per user_brief #6.

No creative lever within philosophy + paytable + R1 max cap can break the
structural conflict.

**Q4**: Did I avoid the v10 failure mode (widen verify bands)?

A: Yes. verify.py is byte-identical to the v8.1 commit state. I did not
touch verify.py at any point. No bands relaxed.

**Q5**: Did I ship "best-effort" weights anyway?

A: No. Per Rule 5, weights.json on disk is v9 untouched. The "shipping
decision" is intentionally to NOT ship — the escalation is delivered to
main session for user decision.

---

## 8. Recommended next action (for user / main session)

User has 3 options:

1. **Relax R1 blank target** to ~45-50% (current v9 ~50% would work with
   small bucket tunes).
2. **Relax ge1_lt5 target ceiling** to ~22pp (would let cherry/bar_mixed
   stay at v9 levels).
3. **Authorize a v10c spec** with one philosophy relaxation:
   - Raise R1 max single-symbol cap from 22% to ~28% (lets 1bar=0.27 R1
     drop R1 blank to ~35%; combined with cherry cut to 0.03, ge1_lt5
     might reach ~17pp — still over but closer).
   - Relax wild_pure cadence floor to 1/30k (lets dd lift unlock more
     wild-substitution paths into ge20_lt50 → frees ge1_lt5 budget).

Per Rule 2, **none of these are taken without user authorization**.

---

## 9. Citation index

- DESIGN_PHILOSOPHY.md §1 (inverse pyramid), §2 (brand visibility), §7
  (top-jackpot escalation), §10 (pareto), §12 (reel asymmetry), §14 (visual
  rhythm), §15 (PWDF) — universal direction.
- user_brief.md v1.2 §a/b/g/h — relaxed CV, count_x cap, paytable lock.
- v9 design narrative — `session_artifacts/M15/design_v9.md`.
- v9 feasibility log — `session_artifacts/M15/feasibility_v9.txt`.
- v10b candidate generator — `session_artifacts/M15/scripts/m15_v10b_design.py`.
- v10b audit log — `session_artifacts/M15/feasibility_v10b.txt`.
