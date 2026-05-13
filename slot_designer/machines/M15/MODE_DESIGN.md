# M15 — per-mode design tables

> Companion to [`DESIGN.md`](DESIGN.md). Per-mode numerics + cross-mode relations.
>
> All numbers are analytic (from `slot_designer.core.devtools.analytic_rtp.analytic_profile` + `slot_designer.machines.M15.plugins.feature.analyze_feature`) on shipped v8 weights. Empirical Monte Carlo verification ±2σ at 100k+ spin per mode — see [`session_artifacts/M15/empirical_v8_mode{1,2,5,7}_iter*.md`](../../../session_artifacts/M15/).

---

## Mode 1 — paid baseline (95% RTP) — v10 (2026-05-11 wave 5)

**Player narrative**: classic 3-reel paid play, retuned per user-pinned wave 5 bucket-shift directive. R1 winners-friendly with blank 35% (was 50% in v9 — heavier bar density on R1 = more frequent small wins on left reel = engagement+). Bucket distribution shifted toward 5× / 10× wins (pay 7 = bar1 5×, pay 5 = bar2 10×) at expense of ge20_lt50 mid-tier RTP. Cherry-1 anywhere lands 4.84% (cut from 11.5% in v9) — share of hits drops from 65% → 29% (well under §8 70%). Feature triggers ~ every 91 spins.

| metric | value | source |
|---|---|---|
| Total RTP | 95.80% | analytic (verify.py [RTP] band [94, 96]) ✓ |
| Base RTP | 45.18pp | analytic_profile |
| Feature RTP | 50.62pp | trigger × feature EV |
| Base hit rate | 16.81% | analytic_profile (verify.py [HIT] band [15, 18]) ✓ |
| Base CV | 3.65 | informational per user §g |
| Feature trigger | 1.100% (1 in 91) | R3 topdollar marginal |
| Feature EV (cond.) | 46.0× bet | analyze_feature (kept v7 baseline per user §e) |
| Feature CV (cond.) | 0.74 | analyze_feature |
| P(R ≥ 200 / spin) | 3.10e-5 | feature tail × trigger |
| P(R ≥ 1000 / spin) | 7.26e-8 | red line ≤ 1e-5 ✓ |
| Jackpot any-reel marginal | R1 0.40% / R2 0.40% / R3 0.10% | red line ≤ 0.6% ✓ |
| R1 blank | **35.28%** | **v10 [R1-BLANK-BAND] [30, 40] ✓** |
| Cherry-1 share of hit | 28.80% | §8 (well under 70% target) ✓ |
| §1 hierarchy bar1>bar2>bar3 hit | PASS | bar1 1.78% > bar2 0.81% > bar3 0.014% ✓ |
| ge1_lt5 RTP | 24.29pp | v10 [BUCKET-RTP-TARGETS] [22.0, 26.0] (STRUCTURAL OVERRIDE — see design_v10.md §3) |
| ge5_lt10 RTP | 8.20pp | v10 [BUCKET-RTP-TARGETS] [8.0, 9.5] ✓ |
| ge10_lt20 RTP | 8.95pp | v10 [BUCKET-RTP-TARGETS] [8.5, 10.0] ✓ |
| wild_pure cadence | 1/908k | [TOP-JACKPOT-CADENCE] [1/50k, 1/2M] (v10 widened — see design_v10.md §3.5) |

**Family RTP share (of base RTP, base = 45.18pp)**:
- cherry1: 4.84pp / 10.7% (P 4.84%, 1×) — cut from v9's 26.1%
- bar_mixed: 19.45pp / 43.0% (P 9.28%, 2× / 4×) — structural floor per design_v10.md §3.2
- bar1: 10.09pp / 22.3% (P 1.78%, 5× pure / 10× / 20× wild lifts) — boosted +14pp
- bar2: 9.58pp / 21.2% (P 0.81%, 10× pure / 20× / 40× wild lifts) — boosted +6pp
- bar3: 0.48pp / 1.06% — cut for bucket redistribution
- high7: 0.32pp / 0.71% — cut for bucket redistribution
- wild_pure: 0.02pp / 0.05% — dd marg cut to fit RTP

## Mode 7 — cut mode (85% RTP) — v10 (2026-05-11 wave 5)

**Player narrative**: same machine, "today not your day" — small wins (cherry / bar_mixed) thin out. Top symbol marginal preserved via algebraic K-scaling (F=1.25); feature behavior unchanged from mode 1; big-pay frequencies within ±15% of mode 1.

**Derivation**: scale blank weight by F=1.25; scale top symbol weights (doublediamond, high7, topdollar) by per-reel K = (F × S_B + S_O) / (S_B + S_O) so that top symbol marginals stay UNCHANGED while blank rises (small-pay marginals naturally drop proportionally).

| metric | value | relation to mode 1 |
|---|---|---|
| Total RTP | 84.96% | < m1 ✓ (CROSS-RTP); in band [83, 87] ✓ |
| Base RTP | 32.25pp | -12.93pp vs m1 |
| Feature RTP | 50.52pp | ≈ m1 (within 0.10pp; trigger preserved) |
| Base hit rate | 13.01% | < m1 16.81% ✓ ([MODE7-CUT]) |
| Base CV | 4.48 | > m1 3.65 (accepted per user §e) |
| Feature trigger | 1.108% (1 in 90) | within 7e-4 of m1 ([MODE7-TRIGGER] tol 5e-4) |
| Feature EV / CV | 46.0× / 0.74 | byte-equal m1 (feature_params block locked) |
| Big-pay freq m7/m1 | pay_id 1: 1.01, pay_id 2: 1.00, pay_id 21: 0.98 | within ±15% ✓ ([MODE7-BIGPAY]) |
| P(R ≥ 1000 / spin) | 7.25e-8 | red line ≤ 1e-5 ✓ |
| Jackpot any-reel marginal | R1 0.36% / R2 0.35% / R3 0.09% | ≤ 0.6% ✓ |
| R1 blank | 40.32% | mode 7 R1 blank rises naturally via K-scaling (R1-BLANK-BAND only on m1) |

**Mode 7 derivation vs mode 1 (algebraic K-scaling)**:
- Blank weights × F=1.30 (per-stop) → blank marginal rises
- Top symbol weights × K (per-reel, computed algebraically) → top marginal unchanged
- Small-pay (cherry / bar / jackpot) weights UNCHANGED → marginal drops proportionally
- Result: trigger preserved, big-pay freq preserved, small-pay freq cut, RTP/hit drop
- feature_params block byte-equal mode 1 (preserved per user §e)

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
| **§14.5 visual rhythm (v8.1)** | bar-family max run ≤ 4 / top max run ≤ 1 / top-pair ≥ 8 / same-sym gap ≥ 5 | ✓ all 30 strip checks GREEN |
| **§15.9 PWDF floor (v8.1)** | top any-reel p_window ≥ mode-specific floor; mid-pay ≥ 2-3% floor | ✓ all 28 per-mode checks GREEN |

## v8.1 visual polish wave (2026-05-11)

§14 + §15 mandates closed via two RTP-neutral transformations layered on top of v8 weights:

| transformation | what changed | what stayed |
|---|---|---|
| strip rearrange | non-blank position ordering on R1 / R2 (R3 untouched) | per-(reel, symbol) multiset → marginals UNCHANGED |
| Mechanism B redistribute | per-reel Blank weights shifted to top-adj positions (non-top-adj floored to 1) | total Blank weight per reel preserved → marginals UNCHANGED |

Combined effect: **RTP / hit / family share / cross-mode invariants identical bytes vs v8**; only strip md5 + chunk md5 turned over. See [`session_artifacts/M15/v81_visual_rhythm_audit.md`](../../../session_artifacts/M15/v81_visual_rhythm_audit.md) for the §14 audit per symbol per reel and [`session_artifacts/M15/v81_pwdf_audit.md`](../../../session_artifacts/M15/v81_pwdf_audit.md) for the §15 PWDF lift table per top symbol per reel.

Mid-pay window visibility drop is intentional per user v8.1 brief ("不算副作用,甚至是需求") — see DESIGN.md §6.1b.

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
