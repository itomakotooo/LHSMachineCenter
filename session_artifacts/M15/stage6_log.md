# M15 Stage 6 — per-mode inner loop log

> **Agent**: main session coordinator (Stage 6 tuner role)
> **Stage**: ONBOARDING_PROCESS.md §5 Stage 6 + §5.6 Per-Mode Inner Loop
> **Order**: mode 1 → mode 7 → mode 2 → mode 5 (per ONBOARDING §5.6)
> **Generated**: 2026-05-11

---

## Pre-Stage-6 state captures

| File | Contents |
|---|---|
| `verify_run_v7_baseline.txt` | verify against current shipped v7 weights (14 RED — HIT band off, jackpot vis off, family share off, hierarchy off) |
| `verify_run_v2_iter0_shipped.txt` | verify against D's v2 candidates after materialization (matches V's iter0 pattern: 3 RED = m2/m5/m7 RTP) |

Materialization command (destructive to `slot_designer/machines/M15/weights/`):

```
python session_artifacts/M15/scripts/verify_feasibility_check.py \
  --materialize-to slot_designer/machines/M15/weights
```

After materialize, verify is GREEN on EVERY category except `[RTP]` which fires
RED for m2 / m5 / m7 (mode 1 RTP 94.10 within band [94, 96]). This is the
"baseline pattern" Stage 6 picks up.

---

## Mode 1 inner loop

**v2 baseline** (post-materialize, no tune):

| metric | analytic (verify.py) | empirical (100k sim) | target band |
|---|---:|---:|---:|
| Total RTP | 94.099% | 94.151% | [94, 96] PASS |
| Base RTP | 35.077pp | 35.471pp | (informational) |
| Base hit | 17.40% | 17.57% | [15, 18] PASS |
| Base CV | 6.086 | 6.061 | informational (v1.2 §g) |
| Trigger | 1.283% | 1.272% | (informational) |
| P(R>=1000/spin) | 8.46e-08 | n/a (rare event) | <= 1e-5 PASS |

**Tune iter count**: **0** — v2 mode 1 candidate passes all RED already.

**4-lock convergence**:

| lock | gate | result |
|---|---|---|
| V (analytic verify.py) | all categories GREEN (RTP within [94,96], hit within [15,18], CV informational) | LOCKED |
| A (empirical 100k spin) | session RTP 94.15% ±0.05pp of analytic 94.10%; hit 17.57% within ±2σ (±0.24pp) of analytic 17.40% | LOCKED |
| A (analytic vs empirical match) | <0.1pp gap on RTP, <0.2pp gap on hit, <0.05 gap on CV → engine has no bug | LOCKED |
| X (5 adversarial questions) | see `mode_1_critique_v8.md` | LOCKED |

**Status**: mode 1 PASS (0 iter), move to mode 7.

---

## Mode 7 inner loop

**v2 baseline** (post-materialize, no tune): RTP 82.74% vs band [83, 87] — RED -0.26pp (NEAR-MISS per D v2).

**Tune iter 1**: blank weight on R1+R2 each blank stop -1 (38 → 37). R3 untouched
(preserves [MODE7-TRIGGER] lock).

Mechanism: analytic sweep tested 7 variants
- R3 symbol bumps (bar3/1bar): LOWERS total RTP (dilutes trigger marginal)
- R2 bar3 +1: +0.086pp (too small)
- Blank all reels -1: +1.86pp (overshoot, breaches MODE7-TRIGGER ±5e-4)
- **Blank R1+R2 -1 each: +0.53pp → 83.27% (chosen)**

**Post-tune (analytic)**:
| metric | value | constraint |
|---|---:|---|
| Total RTP | 83.265% | [83, 87] PASS |
| Base hit | 11.48% | [10, 16] PASS |
| Trigger | 1.3321% | diff to m1 = 4.9e-4 ≤ 5e-4 PASS |
| MODE7-CUT | all small_pay m7 < m1 strict | PASS |
| MODE7-BIGPAY | m7/m1 ratio 1.037 within ±15% | PASS |

**Empirical 300k seed=7777**:
- Session RTP sim 82.11% vs analytic 83.27% (Δ -1.16pp, ±2σ = ±2.43pp). PASS.
- Base hit 11.42% vs analytic 11.48% (Δ -0.07pp, ±2σ = ±0.12pp). PASS.

**Status**: mode 7 LOCKED after 1 iter. See `mode_7_critique_v8.md` for X review.

---

## Mode 2 inner loop

**v2 baseline**: RTP 284.44% vs band [290, 310] — RED -5.6pp (NEAR-MISS per D v2).

**Tune iter 1**: R3 topdollar weight +0.6 (16 → 16.6) on each of 2 R3 topdollar
stops. Fractional weight permitted by `loader.py` line 162 (Stop.weight=float).

Mechanism: tested 8 variants
- R3 topdollar +0.55 → 290.52% (1.0pp inside lower edge — minimal buffer)
- **R3 topdollar +0.6 → 291.07% (chosen — comfortable lower buffer, m5-trigger buffer 0.05pp)**
- R3 topdollar +0.8 → 293.27% (trigger 3.238% only 0.009pp under m5 trigger)
- R3 topdollar +0.9 → 294.38% but trigger 3.257% > m5 3.247% (VIOLATES LUCKY-MONO)
- Hybrid bar2/bar3 cuts + topdollar: dilute trigger marginal, NET DECREASE total RTP
- Pure base-symbol bumps: LOWER total RTP

**Post-tune (analytic)**:
| metric | value | constraint |
|---|---:|---|
| Total RTP | 291.067% | [290, 310] PASS |
| Base hit | 33.54% | [30, 35] PASS |
| Trigger | 3.2009% | > m1 1.28% (LUCKY-MONO) PASS |
| pay_id 1 m2/m1 cadence ratio | 0.973 | ≤ 1.5 (v1.1 §c) PASS |

**Empirical 100k seed=22**:
- Session RTP sim 290.62% vs analytic 291.07% (Δ -0.45pp, ±2σ = ±8.45pp). PASS.
- Base hit 33.51% vs analytic 33.56% (Δ -0.04pp, ±2σ = ±0.30pp). PASS.
- Trigger 3.204% vs analytic 3.20% (Δ +0.00pp). PASS.

**Status**: mode 2 LOCKED after 1 iter. See `mode_2_critique_v8.md`.

---

## Mode 5 inner loop

**v2 baseline**: RTP 539.66% vs band [480, 520] — RED +19.7pp OVER (NEAR-MISS,
overshoot — the trickiest of the 4 modes per ONBOARDING §5.6 Step 5).

**Tune iter 1**: `feature_params.x_value_weights[1]` (100-card weight): 4.5 → 3.0.

Mechanism (Option B per ONBOARDING §5.6 Step 5 — x_value_weights tune):
- Tested 14 variants of x_value_weights index 1 (100-card) and indices 2/3 (50-card)
- Pure 100-card cut chosen: 4.5 → 3.0 (-33%) reduces feature EV 132.81 → 123.33
  (-7.1%), giving total RTP 539.66% → 508.89% (mid-band of [480, 520])
- Trigger UNCHANGED (R3 weights untouched) → preserves LUCKY-MONO m5_trigger >
  m2_trigger strict invariant
- Why NOT Option A (base cut via cherry/bar): risks violating m5_hit ≥ m2_hit
  (only 0.05pp gap — too tight)
- Why NOT Option C (trigger cut): would drag m5 trigger below m2's

**Post-tune (analytic)**:
| metric | value | constraint |
|---|---:|---|
| Total RTP | 508.889% | [480, 520] PASS (mid-band) |
| Base hit | 33.61% | ≥ m2 hit 33.54% (strict) PASS |
| Trigger | 3.2474% | > m2 3.2009% (strict, buffer 0.047pp) PASS |
| pay_id 1 m5/m2 cadence ratio | 1.91 | ≥ 1.1 (v1.1 §d) PASS |
| Feature EV | 123.33 | (informational; v7 was 132.81) |

**Empirical 100k seed=55**:
- Session RTP sim 512.55% vs analytic 508.89% (Δ +3.66pp, ±2σ = ±18.88pp). PASS.
- Base hit 33.74% vs analytic 33.61% (Δ +0.13pp, ±2σ = ±0.30pp). PASS.
- Trigger 3.237% vs analytic 3.247% (Δ -0.01pp). PASS.

**Status**: mode 5 LOCKED after 1 iter. See `mode_5_critique_v8.md`.

---

## Cross-mode integration

After mode 5 tune, ran final verify.py with all 4 modes' final weights:
`verify_run_v8_final.txt` — **exit code 0, all 25 categories GREEN**.

| invariant | check | result |
|---|---|---|
| [CROSS-RTP] m2 > m1 | 291.07 > 94.10 | PASS |
| [CROSS-RTP] m5 > m2 | 508.89 > 291.07 | PASS |
| [CROSS-RTP] m7 < m1 | 83.27 < 94.10 | PASS |
| [LUCKY-MONO] m2 hit > m1 | 33.54 > 17.40 | PASS |
| [LUCKY-MONO] m5 hit ≥ m2 strict | 33.61 > 33.54 | PASS |
| [LUCKY-MONO] m2 trigger > m1 | 3.20% > 1.28% | PASS |
| [LUCKY-MONO] m5 trigger > m2 strict | 3.25% > 3.20% | PASS |
| [LUCKY-MONO] m7 hit < m1 | 11.48 < 17.40 | PASS |
| [MODE7-TRIGGER] diff |m7-m1| ≤ 5e-4 | 4.9e-4 | PASS (at edge, by design) |
| [MODE7-CUT] m7 small_pay freq < m1 strict | 6/6 pay_ids | PASS |
| [MODE7-BIGPAY] m7/m1 ratio within ±15% | 1.037 for pay_id 1/2/21 | PASS |
| [TOP-JACKPOT-CADENCE] m1 1 in [50k, 100k] | 1/74,885 | PASS |
| [TOP-JACKPOT-CADENCE] m7 1 in [50k, 120k] | 1/74,881 | PASS |
| [TOP-JACKPOT-ESC] m2/m1 ratio ≤ 1.5 (v1.1 §c) | 0.973 | PASS |
| [TOP-JACKPOT-ESC] m5/m2 ratio ≥ 1.1 (v1.1 §d) | 1.912 | PASS |
| [CV] m1 6.086 / m2 4.383 / m5 4.572 / m7 8.597 | informational | (no RED) |

CV trend (informational): m7 (cut) 8.6 > m1 6.1 > m5 4.57 > m2 4.38. Direction
matches philosophy §5 (cut higher vol, lucky lower vol).

---

## Existing-test status

- 4/5 inject-bug tests in `tests/machines/test_M15_verify_inject_bug.py` PASS
  (the actual TDD regression guards V wrote at Stage 5).
- 1/5 fails: `test_baseline_v2_iter0_pattern` — meta-test that asserts the v2
  CANDIDATE pattern (m2/m5/m7 RTP RED). Since this fixture uses `load_v7_weights`
  which reads from DISK (now overwritten by v8 tune), the "v2 baseline" no
  longer reproduces — by design. This test is a Stage 5 → Stage 6 transition
  artifact; its purpose is fulfilled. Suggestion (for Stage 10 commit): either
  pin baseline_fixture to read v2 candidates from a frozen archive (not disk)
  OR mark the meta-test xfail-during-Stage-6+ since the fixture-on-disk path
  is broken once Stage 6 runs.

`tests/test_strips_identical_across_modes.py` and `tests/test_per_mode_md5.py`
do not exist (per task brief "if they exist" clause).

---

## Closing summary

**Stage 6 COMPLETE. All 4 modes 4-locked.**

Total iter count: 0 (m1) + 1 (m7) + 1 (m2) + 1 (m5) = **3 tune iterations
across 4 modes**. Far under §6 Pareto-trap escalation threshold (3 same-RED-class
on single mode).

**Final 4-mode summary table (analytic)**:

| mode | total RTP | hit | trig | CV | feat EV | RTP band | hit band |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 94.10% | 17.40% | 1.28% | 6.09 | 46.00 | [94, 96] PASS | [15, 18] PASS |
| 2 | 291.07% | 33.54% | 3.20% | 4.38 | 59.99 | [290, 310] PASS | [30, 35] PASS |
| 5 | 508.89% | 33.61% | 3.25% | 4.57 | 123.33 | [480, 520] PASS | ≥m2 strict PASS |
| 7 | 83.27% | 11.48% | 1.33% | 8.60 | 46.00 | [83, 87] PASS | [10, 16] PASS |

**Final 4-mode summary (empirical, 100k-300k spins each)**:

| mode | session RTP sim | base hit sim | trigger sim | matches analytic |
|---|---:|---:|---:|---|
| 1 | 94.15% | 17.57% | 1.272% | ±0.05pp / ±0.17pp / ±0.01pp — clean |
| 2 | 290.62% | 33.51% | 3.204% | ±0.45pp / ±0.04pp / ±0.00pp — clean |
| 5 | 512.55% | 33.74% | 3.237% | ±3.66pp / ±0.13pp / ±0.01pp — clean within ±2σ |
| 7 | 82.11% | 11.42% | 1.336% | ±1.16pp / ±0.07pp / ±0.004pp — clean within ±2σ |

**No Pareto trap escalations. No structural RED. No commits done.**

Next: Stage 7 (cross-mode integration) is essentially complete in this Stage 6
run (verify is global, all cross-mode checks pass). Stage 8 will do full
empirical with larger N + schema fingerprint vs production rawdata. Stage 9
adversarial review. Stage 10 commit.

## Process improvements logged

None identified during this Stage 6 run that aren't already in
`session_artifacts/M15/process_improvements.md` #1-#41. The 0-iter mode 1,
single-iter mode 7/2/5 progression was clean — V's iter0 RED pattern matched
D v2 NEAR-MISS classification, and the smallest-perturbation approach worked
on the first try for each mode.

