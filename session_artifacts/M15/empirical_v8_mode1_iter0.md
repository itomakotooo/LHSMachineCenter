# M15 empirical sub-gate — mode 1 iter 0 (v2 candidate as v8 starting state)

> **Stage**: 6.k.d Empirical sub-gate (ONBOARDING_PROCESS.md §5.6)
> **Mode**: 1 (base / paid baseline)
> **Iteration**: 0 (no tune — v2 candidate verify.py already GREEN)

## Sim setup

- Tool: `slot_designer/scripts/simulate.py`
- spec: `slot_designer/machines/M15/spec.json`
- weights: `slot_designer/machines/M15/weights/mode_1/weights.json` (v2 materialized)
- machine-name: M15sim
- chunks: 1 × 10 robots × 10,000 spins = **100,000 paid spins**
- seed: 42

## Aggregation logic

Per memory `feedback_session_semantics.md`: session-centric metric — feature
ST=14 reveals are NOT separate paid spins. ST=15 end marker `WinAmount` carries
the accepted session payout. Each paid spin (ST=1, CostCredits=1000) groups its
following ST=14 reveals + ST=15 marker; "session RTP" attributes the accepted
feature payout to the paid spin that triggered it.

## Result table — 3-layer diff per ONBOARDING_PROCESS §5.6.d

| metric | analytic (verify.py) | empirical sim | Δ | tolerance | result |
|---|---:|---:|---:|---:|---:|
| Total RTP | 94.099% | 94.151% | +0.052pp | ±2σ ≈ ±2-3pp at 100k (200× tail) | PASS |
| Base RTP | 35.077pp | 35.471pp | +0.394pp | informational | PASS |
| Base hit | 17.404% | 17.570% | +0.166pp | ±2σ ≈ ±0.241pp at 100k | PASS |
| Base CV | 6.086 | 6.061 | -0.025 | informational | PASS |
| Trigger | 1.283% | 1.272% | -0.011pp | ±2σ ≈ ±0.071pp | PASS |
| Session CV | (not analytic) | 7.119 | n/a | informational | PASS |

## Three-layer diff verdict per §5.6.d

**Layer 1 — analytic (V) vs empirical (A)**: ALL pass ±2σ (or informational
tolerance). Engine + emitter have no bug.

**Layer 2 — empirical vs target band (user_brief.md v1.2)**:
- Total RTP 94.151% within [94, 96] ✓
- Base hit 17.57% within [15, 18] ✓
- P(R>=1000/spin) essentially 0 (no observed in 100k; analytic 8.5e-08) << 1e-5 ✓
- CV informational per v1.2 §g — both 6.06 (sim) and 6.09 (analytic) ≈ v7's 5.77 ± noise

**Layer 3 — empirical vs Stage 1b baseline (production rawdata)**:
- v7 baseline (production) RTP ~95%, hit ~19.3% — v2/v8 mode 1 hit 17.6% is the
  DESIGNED reduction per user_brief #1 (hit cap 18%). Δ from production -1.7pp
  is intentional, matches design intent.

## CI bookkeeping

- Hit rate p=0.176, N=100k → σ = sqrt(p(1-p)/N) = 0.001205 → ±2σ ≈ 0.24pp.
  Observed Δ +0.17pp well within ±2σ.
- Trigger rate p=0.0127, σ ≈ 0.000354 → ±2σ ≈ 0.07pp. Observed Δ -0.01pp inside.
- RTP CV ≈ 6 / spin → σ_RTP ≈ 6/sqrt(100k) × 100% = 1.9pp. Observed Δ +0.05pp
  way inside.

## Verdict

**4-lock locks 2/3 (V, A-empirical, A-engine-no-bug)**. Pending X adversarial
review → `mode_1_critique_v8.md`.

After X: mode 1 LOCKED, proceed to mode 7.
