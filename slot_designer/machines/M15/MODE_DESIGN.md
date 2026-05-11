# M15 — per-mode design tables

> Companion to [`DESIGN.md`](DESIGN.md). Per-mode numerics + cross-mode relations.
>
> All numbers are analytic (from `slot_designer.core.devtools.analytic_rtp.analytic_profile` + `slot_designer.machines.M15.plugins.feature.analyze_feature`) on shipped v8 weights. Empirical Monte Carlo verification ±2σ at 100k+ spin per mode — see [`session_artifacts/M15/empirical_v8_mode{1,2,5,7}_iter*.md`](../../../session_artifacts/M15/).

---

## Mode 1 — paid baseline (95% RTP)

**Player narrative**: classic 3-reel paid play. Cherry-1 anywhere lands 13.77% of spins (1×). Feature triggers ~ every 78 spins, average payout ~46× bet.

| metric | value | source |
|---|---|---|
| Total RTP | 94.10% | analytic (verify.py [RTP] band [94, 96]) |
| Base RTP | 35.08pp | analytic_profile |
| Feature RTP | 59.02pp | trigger × feature EV |
| Base hit rate | 17.40% | analytic_profile (verify.py [HIT] band [15, 18]) |
| Base CV | 6.09 | informational per user §g |
| Feature trigger | 1.283% (1 in 78) | R3 topdollar marginal (pay_id 666 scatter) |
| Feature EV (cond.) | 46.0× bet | analyze_feature |
| Feature CV (cond.) | 0.74 | analyze_feature |
| Feature R range | [5×, 4880×] bet | analyze_feature |
| P(R ≥ 200 / spin) | 3.62e-5 (1 in 27,597) | feature tail × trigger |
| P(R ≥ 1000 / spin) | 2.1e-7 | red line ≤ 1e-5 ✓ |
| Jackpot any-reel marginal | R1 0.06% / R2 0.55% / R3 0.10% | red line ≤ 0.6% ✓ |

**Family RTP share (of base RTP, base = 35.08pp)**:
- cherry1: 13.77pp / 39.3% (P 13.77%, 1×)
- bar_mixed: 5.79pp / 16.5% (P 2.40%, ~2.4× avg)
- bar2: 8.78pp / 25.0% (P 0.58%, 10×)
- cherry2/3: 3.71pp / 10.6%
- bar3 + bar1 + high7 + wild_pure: 3.03pp / 8.6%

## Mode 7 — cut mode (85% RTP)

**Player narrative**: same machine, "today not your day" — small wins (cherry / bar_mixed) thin out. Feature behavior unchanged from mode 1 (same trigger cadence, same payout distribution). CV naturally rises ("boom or bust" feel).

| metric | value | relation to mode 1 |
|---|---|---|
| Total RTP | 83.27% | < m1 ✓ (CROSS-RTP) |
| Base RTP | 21.99pp | -13.09pp vs m1 |
| Feature RTP | 61.27pp | ≈ m1 (slight lift via R3 trigger marginal) |
| Base hit rate | 11.48% | < m1 17.40% ✓ ([MODE7-CUT]) |
| Base CV | 8.60 | > m1 6.09 (accepted per user §e) |
| Feature trigger | 1.332% (1 in 75) | within 4.9e-4pp of m1 1.283% ✓ ([MODE7-TRIGGER] tol 5e-4) |
| Feature EV / CV | 46.0× / 0.74 | byte-equal m1 (feature_params block locked) |
| Big-pay (200× / 30×) freq | wild_pure 1.50e-5 / high7 7.07e-5 | within ±15% of m1 ✓ ([MODE7-BIGPAY]) |
| P(R ≥ 1000 / spin) | 2.1e-7 | red line ≤ 1e-5 ✓ |
| Jackpot any-reel marginal | R1 0.07% / R2 0.55% / R3 0.06% | ≤ 0.6% ✓ |

**Mode 7 tune action vs mode 1 (Stage 6.k=1)**:
- blank weight R1 each stop -1 (38 → 37)
- blank weight R2 each stop -1 (38 → 37)
- Net effect: total reel weight reduces marginally, mid-pay family marginals lift proportionally, base RTP closes -0.3pp gap to band.
- feature_params block byte-equal mode 1 (preserved).

## Mode 2 — lucky mode (300% RTP)

**Player narrative**: "today is on" — frequent wins (1/3 spins hit), majority small but visible mid wins (10-200×) accumulate; feature triggers ~3 min cadence.

| metric | value | relation |
|---|---|---|
| Total RTP | 291.07% | > m1 ✓ |
| Base RTP | 99.03pp | +63.95pp vs m1 |
| Feature RTP | 192.03pp | trigger 3.20% × EV 60.0× |
| Base hit rate | 33.54% | in user §c band [30, 35]; > m1 17.40% ✓ (LUCKY-MONO) |
| Base CV | 4.38 | < m1 6.09 ✓ (philosophy §5 direction) |
| Feature trigger | 3.204% (1 in 31) | > m1 1.283% ✓ |
| Feature EV (cond.) | 60.0× bet | lifted via x_value_weights tail shift |
| Feature CV (cond.) | 0.78 | similar to m1 0.74 |
| P(R ≥ 200 / spin) | 2.74e-4 | 7.6× higher than m1 (drift from user §c "= m1" intent — see DESIGN.md §4.4) |
| P(R ≥ 1000 / spin) | 2.9e-6 | red line ≤ 1e-5 ✓ |
| Jackpot any-reel marginal | R1 0.42% / R2 0.55% / R3 0.34% | ≤ 0.6% ✓ |

**Mode 2 tune action vs mode 2 starting (Stage 6.k=1)**:
- R3 topdollar weight 16 → 16.6 (fractional) on 2 stops
- Net effect: trigger rate 3.089% → 3.204%; mode 5 hit/trigger ≥ mode 2 invariants now strict-pass
- Side note: fractional weight is virtual-machine pipeline OK; real-machine XLSX export would need 17/16 split or other integer realization

## Mode 5 — super-lucky mode (500% RTP)

**Player narrative**: "today big wins everywhere" — same hit cadence as mode 2 but the feature feels richer (more 200×+ events). Top-jackpot escalation per §7 lives in feature tail (since base byte-similar to m2 by user §d).

| metric | value | relation |
|---|---|---|
| Total RTP | 508.89% | > m2 291.07% ✓ |
| Base RTP | 108.38pp | +9.35pp vs m2 (per user §d lift allowed; "不矫枉过正") |
| Feature RTP | 400.51pp | trigger 3.25% × EV 123× |
| Base hit rate | 33.61% | ≥ m2 33.54% ✓ ([LUCKY-MONO]) |
| Base CV | 4.57 | similar to m2 4.38 |
| Feature trigger | 3.247% (1 in 31) | ≥ m2 3.204% ✓ |
| Feature EV (cond.) | 123× bet | lifted via x_value_weights upper-bin redistribution |
| Feature CV (cond.) | 0.85 | richer right tail (vs m2 0.78) |
| P(R ≥ 200 / spin) | 3.82e-3 | 14× m2's 2.74e-4 → §7 escalation in feature tail ✓ |
| P(R ≥ 1000 / spin) | 1.3e-7 | red line ≤ 1e-5 ✓ (well below) |
| Jackpot any-reel marginal | R1 0.42% / R2 0.55% / R3 0.34% | ≤ 0.6% ✓ |

**Mode 5 tune action vs mode 5 starting (Stage 6.k=1)**:
- `feature_params.x_value_weights[1]` (the 100-card weight) 4.5 → 3.0 (-33%)
- Net effect: feature EV trimmed from ~143× back to 123×, total RTP from 540% back into [480, 520] band (close to upper boundary 510)
- Smallest-perturbation principle: single weight bin adjusted; other x_value_weights / x_count_weights untouched

## Cross-mode invariants (all PASS per verify.py)

| invariant | check | result |
|---|---|---|
| RTP ladder | m2 > m1 > m7, m5 > m2 | ✓ |
| Hit ladder | m5 ≥ m2 > m1 > m7 | ✓ |
| Trigger ladder | m5 ≥ m2 > m1, m7 ≈ m1 (tol 5e-4) | ✓ |
| m7 feature_params byte-equal m1 | x_count_weights, x_value_weights, accept_threshold, max_rounds | ✓ |
| m5 base ≠ m2 base (per user §d) | base RTP lift 9.35pp | ✓ |
| Schema fingerprint | virtual emit matches production `5d02773c069fc396` | ✓ |
| Paytable lock | spec.json `pays` block unchanged | ✓ |

## Mode-derivation legend

```
mode 1 (paid 95%)
├── mode 7 = mode 1 砍小奖 + 命中率降 + feature unchanged
│   tune: blank R1+R2 weight -1 each stop
├── mode 2 (lucky 300%) — independent lift of all weights
│   tune: trigger R3 topdollar +0.6 to enable m5 strict invariants
└── mode 5 (super-lucky 500%) — derived from mode 2 + further lift
    tune: x_value_weights[100-card] 4.5→3.0; base lifted ~9pp above m2
```
