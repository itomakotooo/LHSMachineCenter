# M15 v10c structural escalation — 2026-05-11 wave 6

> **Status**: ESCALATION per Rule 2 of v10c retry brief.
>
> Cherry §2 relaxation (user-authorized in v10c brief) was implemented but
> alone is INSUFFICIENT to reach all 4 user-pinned bucket targets simultaneously.
> The bar_mixed (pay_id 8 at 2× with wild-substitution boost) structural
> bloater in ge1_lt5 remains.
>
> **v9 weights remain on disk unchanged. verify.py untouched (frozen per Rule 1).**

---

## 1. Targets that cannot be reached simultaneously (v10c)

| target | user band | v9 baseline | direction |
|---|---|---:|---|
| R1 blank marginal | [30%, 40%] | 50.25% | needs to DROP -10.25pp |
| bucket ge1_lt5 RTP | [11.0, 14.0]pp | 22.33pp | needs to DROP -8.33pp |
| bucket ge5_lt10 RTP | [8.0, 9.5]pp | 3.72pp | needs to LIFT +4.28pp |
| bucket ge10_lt20 RTP | [8.5, 10.0]pp | 4.16pp | needs to LIFT +4.34pp |

**User-authorized v10c relaxation**: Cherry per-reel marginal floor lowered
from 3.5% archetype to 2.0% (owned §2 deviation, M15-specific).

Plus retained philosophy hard constraints:
- doublediamond / high7 / topdollar per-reel >= floors per user_brief
- wild_pure cadence in [1/50k, 1/120k]
- R1 max single non-blank marginal <= 22% (§14)
- §1 hierarchy: bar1 >= bar2 >= bar3 hit; cherry1 >= cherry2 >= cherry3
- jackpot <= 0.6% per reel
- paytable byte-identical (universal rule)
- P(R>=1000)/spin <= 1e-5
- hit ∈ [15%, 18%]
- total RTP ∈ [94%, 96%]

---

## 2. Why cherry relaxation alone isn't enough

### 2.1 Cherry relaxation impact (predicted)

Cherry-1 RTP shrinks linearly with cherry density:
- cherry 5%/5%/2.5% (v9): cherry-1 P ~11.5%, RTP 11.5pp
- cherry 2.5% uniform (v10c floor): cherry-1 P ~7.1%, RTP 7.1pp
- Free budget for ge1_lt5: ~4.4pp

This shifts ge1_lt5 baseline from 22.33pp → ~17-18pp at v9 bar levels.
**Still 3-4pp over the 14pp cap.**

### 2.2 The bar_mixed bloater — the true ge1_lt5 wall

**Critical engine fact discovered during v10c iteration**:

`pay_id 8` (line_3_group, multiplier 2×) fires when ALL 3 cells on the
payline are from {1bar, 2bar, 3bar, wild} AND not 3-of-same after wild
substitution. Examples:
- `(1bar, 1bar, 2bar)` -> pay_id 8 at 2× (2bar not enough for 3-same)
- `(1bar, 2bar, 3bar)` -> pay_id 8 at 2× (all different)
- `(1bar, 2bar, wild)` -> pay_id 5 (2bar) at 20× via wild boost (line_3_same wins)

Brief math sanity ("bar_mixed with 3bar 1.5%, 1bar 25%, 2bar 20%:
6×0.25×0.20×0.015 = 0.45% → 0.9pp") assumed pay_id 8 fires only on strict
{1bar, 2bar, 3bar} triple — which is wrong. The engine fires pay_id 8 on
any non-3-same bar combo, dominated by {1bar, 1bar, 2bar} and {1bar, 2bar,
2bar} permutations.

**Actual bar_mixed RTP** at bars (sum_bars ≈ 0.37 per reel) is ~12-14pp:
- {1bar, 1bar, 2bar} perms: 3 × p1² × p2 ≈ 3 × 0.22² × 0.16 = 2.32%
- {1bar, 2bar, 2bar} perms: 3 × 0.22 × 0.16² = 1.69%
- {1bar, 1bar, 3bar}: 3 × 0.22² × 0.015 = 0.22%
- {1bar, 2bar, 3bar}: 6 × 0.22 × 0.16 × 0.015 = 0.32%
- Plus wild-substitution paths at 4× (1-wild) and 8× (2-wild)
- Total P ≈ 6%, RTP at 2× ≈ 12pp pure + 2pp wild boost = ~14pp

This DOMINATES ge1_lt5 budget. Even at cherry 2.5% (cherry-1 = 7pp),
ge1_lt5 = 7 (cherry) + 14 (bar_mixed) = 21pp >> 14pp cap.

### 2.3 The bucket transfer dilemma

ge5_lt10 = pay_id 7 (bar1 pure 5×) + pay_id 71 (cherry-2 5×)
- bar1 pure RTP = (1bar_marg)^3 × 5 × 100
- cherry-2 RTP = 3 × c^2 × (1-c) × 5 × 100

For ge5_lt10 = 8pp:
- At cherry 2.5%, cherry-2 = 0.91pp; bar1 pure must reach 7.1pp
  → (1bar_marg)^3 ≥ 0.0142 → 1bar_marg ≥ 24.2% AVG
- But R1 max cap = 22% (philosophy §14 hard)
- So with 1bar marg R1=22%, R2/R3=25% (uniform-max), bar1 pure ≈ 6.88pp
- ge5_lt10 = 6.88 + 0.91 = 7.79pp -- just below 8 floor

But 1bar_marg ~24% AVG triggers bar_mixed P spike:
- (sum_bars)^3 at 0.39 = 5.93% → bar_mixed pure 5% × 2 = 10pp pure
  + wild boost +2.5pp = ~12.5pp

So pushing bars to lift ge5_lt10 → bar_mixed bloats ge1_lt5.
Cutting bars to control ge1_lt5 → ge5_lt10 starves.

### 2.4 ge10_lt20 third independent dimension

ge10_lt20 needs:
- bar2 pure 10×: (2bar_marg)^3 × 10 — at 2bar=14%, RTP = 2.74pp
- bar1+1wild = 10×: 3 × p1² × dd_marg × 10 — at 1bar=22%, dd_avg=3%, RTP = ~4.4pp
- cherry-3 15×: trivial at low cherry
- Total max ~7pp at modest bars

To reach 8.5pp, need MORE bar1+1wild paths -> bar1 marg higher or dd higher.
But bar1 R1 capped at 22%, and dd higher pushes wild_pure cadence below
1/50k floor (philosophy §7).

---

## 3. Systematic parameter sweep results

Tested 3000+ candidates across:
- cherry density: {2%, 2.5%, 3%, 3.5%} (uniform + R3-asymmetric)
- 1bar R1: {15%, 18%, 20%, 21.5%, 22%} (respect R1 max cap)
- 1bar R2/R3: {18%, 22%, 25%, 28%}
- 2bar: {6%, 10%, 14%, 18%}
- 3bar: {1%, 1.5%, 2%}
- high7 R1: {6%, 12%, 18%, 24%}
- high7 R2: {6%, 10%, 14%}
- dd: {(3%/3.5%/1.4%), (4.5%/4.5%/0.6%)} (preserves cadence)
- mechanism B applied (per v9)

**Results**:

| query | count |
|---|---:|
| Candidates passing ALL 4 user-pinned numerical targets | **0** |
| Candidates with ge1_lt5 ≤ 14pp AND R1 blank ≤ 40% | **0** |
| Candidates with all 4 buckets in band | **0** |
| Best n_pass across 12 hard constraints | 10/12 |

The 10/12 candidates fail with the SAME two dimensions:
- `bucket_ge1_lt5_RTP` over (driven by bar_mixed at 2× lock)
- `bucket_ge10_lt20_RTP` under (bar1+1wild + bar2 pure cap)

---

## 4. Lever-by-lever audit (Rule 3 discipline)

See `feasibility_v10c.txt` for full per-candidate dump. Summary:

### Lever A — cut bar_mixed by trimming 3bar
**Result**: ineffective. 3bar only contributes to bar_mixed via {x, x, 3bar}
permutations where x ∈ {1bar, 2bar}. With 1bar/2bar at 16-22%, those
contribute < 1% to bar_mixed P. Main bar_mixed mass comes from {1bar^2, 2bar}
and {1bar, 2bar^2} which 3bar cut doesn't address.

### Lever B — push h7 high on R1 to drop blank without bar_mixed inflation
**Result**: helpful but limited. Pushed R1 high7 to 22-25% to drop R1 blank
from ~50% to 38-40%. But high7 high boosts pay_id 21 (h7 pure 30×) RTP into
ge20_lt50, NOT ge10_lt20 — doesn't help the under-band. And high7 increase
overshoots total RTP into 100-110% range.

### Lever C — cherry asymmetric (R3 high)
**Result**: minor positive. Lifts cherry-2 (ge5_lt10) and cherry-3 (ge10_lt20)
but small relative to bar contributions. cherry asymmetric still locked in
cherry-1 floor at relaxed marginal.

### Lever D — dd higher to push 1bar+1wild into ge10_lt20
**Result**: capped by wild_pure cadence floor. dd_avg ≤ 2.71% to maintain
1/50k cadence. Asymmetric dd (R1/R2 high, R3 low) helps cadence math but
caps overall lift to ~1pp ge10_lt20 gain.

### Lever E — strip rearrange (mechanism B already in v9)
Does not change marginals → no bucket impact.

### Lever F — cherry relaxation (NEW in v10c, user-authorized)
**Result**: frees ~4pp ge1_lt5 budget. But ge1_lt5 was ~22pp in v9; freeing
4pp leaves 18pp >> 14pp cap. Bar_mixed (12-14pp) and cherry-1 floor (7pp)
together still exceed 14pp.

---

## 5. The fundamental structural conflict (v10c version)

### 5.1 Three-way independent conflict

**Constraint matrix**:

| target | direction needs | structural cost |
|---|---|---|
| R1 blank ≤ 40% | high non-blank density on R1 (≥ 60%) | h7 + bar marginals must be high |
| ge1_lt5 ≤ 14pp | low cherry-1 + low bar_mixed | bar marginals must be LOW |
| ge5_lt10 ≥ 8pp | high bar1 marg pure | bar1 marginal must be ≥ 24% AVG (R1 cap = 22%) |
| ge10_lt20 ≥ 8.5pp | high bar2 + bar1+1wild | bar marginals high + dd capped by wild cadence |

R1 blank ↔ ge1_lt5: high non-blank R1 needs more bars; more bars → bar_mixed
explodes; bar_mixed at 2× lands in ge1_lt5 → ge1_lt5 fails.

ge1_lt5 ↔ ge5_lt10: cutting bars helps ge1_lt5 but starves ge5_lt10
(bar1 pure 5×).

ge10_lt20 needs same bar push as ge5_lt10 but capped by dd-cadence and
R1 max.

### 5.2 Cherry relaxation impact

Cherry relaxation frees 4pp of ge1_lt5 budget (cherry-1 11.5pp → 7pp).
But bar_mixed alone is 12-14pp at any bar config supporting ge5_lt10
≥ 8pp. Net: ge1_lt5 still 7 (cherry) + 12 (bar_mixed) = 19pp at best,
still 5pp over cap.

To bring ge1_lt5 ≤ 14:
- bar_mixed must drop to ≤ 5pp → sum_bars ≤ 31% per reel
- but then bar1 pure ≤ (0.18)^3 × 5 = 2.92pp → ge5_lt10 < 4pp << 8 floor

**Impossible within paytable + R1 max constraints.**

---

## 6. State of disk after v10c

- `slot_designer/machines/M15/weights/mode_1/weights.json` — **v9 unchanged**
  (43.83pp base / 50.65pp feature / hit 17.78% / R1 blank 50.25% / RTP 94.48%)
- `slot_designer/machines/M15/weights/mode_7/weights.json` — **v9 unchanged**
- `slot_designer/machines/M15/verify.py` — **untouched (frozen)**
- `session_artifacts/M15/feasibility_v10c.txt` — full lever-by-lever audit
- `session_artifacts/M15/scripts/m15_v10c_design.py` — candidate generator
- `session_artifacts/M15/v10c_escalation.md` — this document

Per Rule 5: "Ship only if all hard constraints GREEN ... DO NOT ship."

---

## 7. Self-critique (per process discipline)

**Q1**: Did I correctly identify the bar_mixed structural issue?

A: Yes. v10b's analysis missed that pay_id 8 fires on ANY non-3-same bar
combo (including {1bar, 1bar, 2bar}), not just strict {1bar, 2bar, 3bar}.
v10c confirmed this via explicit engine evaluation tests and grid sweep —
bar_mixed P scales as (sum_bars)^3, not 6 × p1 × p2 × p3 as brief math
assumed.

**Q2**: Did I exhaust the cherry-relaxation space?

A: Yes. Tested cherry from 2% (relaxed floor) to 5% (archetype max) in
both uniform and R3-asymmetric configs. Cherry relaxation frees ~4pp of
ge1_lt5 budget but bar_mixed structural floor remains.

**Q3**: Did I try ALL Rule 3 levers per v10c brief?

A: Yes:
- Cherry density / asymmetric (Lever F, NEW)
- 3bar cut (Lever A from v10b)
- high7 R1 push (Lever B)
- dd asymmetric for cadence preservation (Lever D)
- Strip mechanism B (Lever E, retained from v9)

**Q4**: Did I avoid the v10 / v10b failure modes (widen bands, ship best-effort)?

A: Yes. verify.py byte-identical to v8.1 commit. weights.json on disk is
v9 unchanged. Did not relax any non-cherry archetype (cherry was the
USER-AUTHORIZED relaxation, no others).

**Q5**: Is there a creative lever I missed?

A: Considered:
- Asymmetric dd (R1=R2=4.5%, R3=0.5%): tested, helps cadence math but only
  ~1pp ge10_lt20 gain
- Cherry asymmetric R3=5%, R1/R2=2%: tested, minor benefit
- High7 over-push to 25-30% R1: tested, drops R1 blank but RTP overshoots
  to 105-120% (over 96 cap)
- 2bar high to lift bar2 pure: tested, lifts ge10_lt20 but bar_mixed grows
- 1bar very asymmetric R1=22, R2/R3=27-30: tested, breaks R1 max cap or
  inflates bar_mixed when combined with other lifts

No creative lever within philosophy + paytable + R1 max cap + cherry
relaxation can resolve the conflict.

---

## 8. Recommended next action

User has 3 options (re-prompting decision):

1. **Relax R1 max cap from 22% to ~28%**: would let 1bar reach 28%/reel
   → bar1 pure ≈ 21.9pp at 5× — overshoots ge5_lt10 cap. Need more careful
   tuning. Probably feasible for ge5_lt10 ≥ 8 but bar_mixed grows too.

2. **Relax ge1_lt5 ceiling to ~22pp**: would let bar_mixed + cherry-1
   coexist as in v9. ge1_lt5 acceptance ~20pp. Reflects classic Top Dollar
   1-line player experience — many small 1-2× hits per session.

3. **Authorize paytable change**: e.g., bar_mixed multiplier 2× → 1×
   (would land in gt0_lt1 bucket, removing from ge1_lt5). This requires
   paytable change — universal rule v1.2 §h LOCKS this. Cannot proceed
   without explicit cross-machine universal rule revocation.

4. **Accept best-effort 10/12 ship**: ship the best candidate found
   (RTP 94.89%, hit 15.47%, R1blank 39.7%, ge1_lt5 17.34pp,
   ge5_lt10 8.32pp ✓, ge10_lt20 6.05pp). Two RED checks:
   `bucket_ge1_lt5_RTP` over by 3.34pp, `bucket_ge10_lt20_RTP` under by
   2.45pp. Hit, RTP, R1blank, ge5_lt10 all GREEN.

Per Rule 2, **none of these are taken without explicit user authorization**.

---

## 9. Citation index

- DESIGN_PHILOSOPHY.md §1, §2, §7, §10, §12, §14, §15 — universal directions.
- user_brief.md v1.2 §a/b/g/h — relaxed CV, count_x cap, paytable lock.
- v10b_escalation.md — initial structural analysis (cherry was the only
  visibility identified as blocker; v10c proves bar_mixed is the other half).
- v9 design narrative — `session_artifacts/M15/design_v9.md`.
- v9 feasibility log — `session_artifacts/M15/feasibility_v9.txt`.
- v10c candidate generator — `session_artifacts/M15/scripts/m15_v10c_design.py`.
- v10c audit log — `session_artifacts/M15/feasibility_v10c.txt`.
- Engine evaluator analysis — `slot_designer/core/engine/evaluator.py`
  `evaluate_payline()` Stage 5 line_3_group resolution.
