# M15 empirical sub-gate — mode 5 iter 1

> **Stage**: 6.k.d Empirical sub-gate (ONBOARDING_PROCESS.md §5.6)
> **Mode**: 5 (super-lucky, base ~500% RTP)
> **Iteration**: 1 (one tune step: x_value_weights[1] 4.5 → 3.0)

## Tune action

**Tune iter 1**: m5 `feature_params.x_value_weights[1]` (100-card weight): 4.5 → 3.0.

Reason: D v2 mode 5 baseline RTP 539.66% vs band [480, 520] — gap +19.7pp
overshoot (NEAR-MISS-OVER). The trickiest mode per ONBOARDING §5.6 Step 5.

Tested 14 variants:
- Pure 100-card weight cut: linear lever — 4.5→3.0 = -30.77pp RTP, gives 508.89%
- Pure 50-card weight cut: smaller per-step (-5pp per 0.5 trim), reaches band only at extreme cuts
- Combination cuts: 100=2.5 + 50=2.5 → 484.5% (near floor); 100=3.0 + 50=2.5 → 496.4%
- **100-card 4.5→3.0 ALONE: 508.89% (lands mid-band)** ← chosen

**Pick rationale (Option B per ONBOARDING §5.6 Step 5)**:
- Trigger UNCHANGED (R3 weights untouched) — preserves LUCKY-MONO m5 trigger > m2 strict
- Pure feature EV reduction: 132.81 → 123.33 (-7.1%)
- Single-axis change = smallest perturbation
- Lands at 508.89% which is comfortably in middle of [480, 520] band, with ~21pp buffer on lower edge and ~11pp on upper

**Why not Option A (base cut)**: cutting m5 base RTP via cherry/bar trims risks
violating m5_hit ≥ m2_hit invariant (m5 hit 33.61% vs m2 33.56% — only 0.05pp
gap). Trim would have to be tiny. Combined m5 base shrink + m5 feature shrink
needed for cleaner outcome.

**Why not Option C (trigger cut)**: cutting trigger drops m5 trigger below
m2 3.20% — violates LUCKY-MONO trigger invariant.

Option (b) feature-EV-only is the cleanest.

## Verify all categories GREEN (M15 first time ALL GREEN!)

(see `verify_run_v8_mode5_iter1.txt`)

**Exit code 0**. All RED-line categories pass:
- [RTP] m5 GREEN (508.89% within [480, 520])
- [HIT] m5 GREEN (33.61% within [30, 35])
- [LUCKY-MONO] m5 GREEN (m5 hit > m2 strict; m5 trigger > m2 strict)
- [CROSS-RTP] GREEN (m2 > m1, m5 > m2, m7 < m1)
- [HIERARCHY], [FAMILY-SHARE], [HIT-DECOMP], [JACKPOT-VIS], [PER-PAY-FLOOR],
  [MODE7-*], [TOP-JACKPOT-CADENCE], [TOP-JACKPOT-ESC], [PAYTABLE-LOCK],
  [STRIP-IMMUTABILITY], [BLANK-FLANK], [REEL-ASYMMETRY], [SCHEMA-FP] — all GREEN
- [CV] m5 base 4.57, feature 0.845 (informational; CV slightly dropped from
  0.858 due to weight redistribution)

## Sim setup

- chunks 1 × 10 robots × 10,000 spins = **100,000 paid spins**
- seed 55

## 3-layer diff per ONBOARDING_PROCESS §5.6.d

| metric | analytic | empirical (100k) | Δ | ±2σ | result |
|---|---:|---:|---:|---:|---:|
| Session RTP | 508.89% | 512.55% | +3.66pp | ±18.88pp | PASS |
| Base RTP | 108.38pp | 113.97pp | +5.59pp | informational | PASS |
| Base hit | 33.61% | 33.74% | +0.13pp | ±0.30pp | PASS |
| Base CV | 4.57 | 4.64 | +0.07 | informational | PASS |
| Trigger | 3.247% | 3.237% | -0.010pp | ±0.11pp | PASS |
| Session CV | (n/a) | 5.83 | n/a | informational | PASS |

## Layer interpretation

**Layer 1 — analytic vs empirical**: ALL within ±2σ. Engine + emitter + plugin
feature path (which is where x_value_weights are sampled) clean.

**Layer 2 — empirical vs target band**:
- Session RTP 512.55% within [480, 520] ✓ (mid-band)
- Hit 33.74% within [30, 35] ✓
- Trigger 3.237% > m2 trigger 3.20% (sim diff +0.033pp) ✓
- P(R>=1000/spin) — 1000-card weight is 0.0001 effectively. With m5 having
  killed 1000-card per user_brief, expected P(R>=1000) ≈ trigger * P(R>=1000|trigger)
  ≈ 3.247% × tiny ≈ <1e-7. Vastly below 1e-5 cap.

**Layer 3 — empirical vs Stage 1b production baseline**:
- v7 m5 RTP was 490.32% (production baseline); v8 m5 RTP 512.55% (sim). Δ +22pp
  closer to design intent target ~500. This was the explicit goal of v2/v8
  redesign per user_brief v1.1 §d "在 mode 2 基础上, 200x+ 频次继续增加" —
  user wanted m5 RTP higher than v7 by lifting feature EV. v2 lifted EV but
  overshot; v8 brings it back to mid-band.

## Verdict

V GREEN, A ±2σ, engine no bug. 3/4 locks open. X review → `mode_5_critique_v8.md`.

**This completes the 4-mode tune. Verify exits 0 — all RED line categories GREEN.**
