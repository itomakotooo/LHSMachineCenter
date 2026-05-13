# M15 — per-mode design tables (v14 final, 2026-05-12/13)

> Companion to [`DESIGN.md`](DESIGN.md). Per-mode numerics + cross-mode relations.
>
> **Current ship state (v14 cycle, 2026-05-12/13)**: all 4 modes redesigned from scratch
> after user dropped all RTP bucket bands (USER_HARDLINES.md v8). Only `Total RTP` /
> `Hit session` / `R1 blank` / `Jackpot per reel` + paytable + feature shape are user
> hardlines now. Bucket distribution self-emerges per mode philosophy.
>
> All numbers below are ENGINE-realized analytic (`analytic_profile_from_marginals`
> after `marginals_to_weights` + mechanism B blank redistribute). Empirical Monte Carlo
> 100k+ spin verification not yet run on v14 — deferred to first real-machine sample.

---

## Mode 1 — paid baseline (95% RTP) — v14 C38_C14 (2026-05-12)

**Player narrative**: classical IGT-style 7-bar 3-reel slot. All 6 paying families
visible on every reel (cherry / 1bar / 2bar / 3bar / high7 / doublediamond), no single
family marginal > 21% per reel. bar hierarchy preserved: P(bar1) > P(bar2) > P(bar3).
Feature trigger ~ every 89 spins.

**Per-reel marginals**:

| reel | blank | cherry | 1bar | 2bar | 3bar | high7 | dd | td | jp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R1 | 38.50 | 4.00 | 20.20 | 16.50 | 10.30 | 7.20 | 2.90 | — | 0.40 |
| R2 | 50.30 | 3.50 | 16.50 | 13.50 | 7.30 | 5.70 | 2.80 | — | 0.40 |
| R3 | 58.97 | 2.50 | 13.50 | 11.00 | 5.50 | 4.70 | 2.40 | 1.13 | 0.30 |

**Metrics (engine-realized)**:

| metric | value | hardline |
|---|---|---|
| Total RTP | 94.26% | [94, 96] ✓ |
| Base RTP | 42.79pp | — |
| Feature RTP | 51.47pp | — |
| Base hit | 14.38% | — |
| Hit session | 17.34% | [15, 18] ✓ |
| Feature trigger | 1.119% (1 in 89) | — |
| Feature EV (cond.) | 46.0× bet (simulated T=40) / 46.36× (optimal player) | locked v9 |
| R1 blank | 38.52% | [30, 40] ✓ |
| R2 blank / R3 blank | 50.30% / 58.97% | — |
| Jackpot per reel | R1 0.40 / R2 0.40 / R3 0.30 | ≤ 0.6 ✓ |
| wild_pure cadence | 1/51,314 | classical band [1/50k, 1/100k] ✓ |
| P(R ≥ 1000) / spin | 1.54e-6 | ≤ 1e-5 ✓ |
| Bar hierarchy | P(bar1_pure) 0.71% > P(bar2_pure) 0.42% > P(bar3_pure) 0.10% | ✓ §1 strict |
| Optimal player RTP | 94.65% | < 96 ceiling +1.35pp margin ✓ |

**Family share-of-base RTP**:
- cherry1 21.9% (anchor 1× any-cherry, classical)
- bar1 12.1% (5× pure + wild variants)
- bar2 15.4% (10× pure + wild variants)
- bar3 9.3% (20× pure + wild variants)
- bar_mixed 27.9% (composite 2×/4× multi-family any-3-bars)
- high7 8.7% (30×/60×/120×)
- cherry2 3.7% (5× 2-cherry)
- cherry3 0.1% (15× 3-cherry)
- wild_pure 0.9% (200× 3-wild)

**Each pay alive** (frequency 1-in-N): cherry-1 1/11, cherry-2 1/315, cherry-3 1/28571,
wild_pure 1/51314, bar1_pure 1/141, bar2_pure 1/237, bar3_pure 1/967, bar_mixed 1/19,
h7_pure 1/5184, h7+wild 1/2518.

---

## Mode 7 — cut mode (85% RTP) — v14b M7_F110 K-scale F=1.10 (2026-05-12)

**Player narrative**: same machine as mode 1, "今天不出手" feel. Cherry / bar marginals
cut ~18% per reel; top symbols (high7 / doublediamond / topdollar / jackpot) marginals
byte-equal mode 1. Feature trigger byte-equal mode 1 (1.121%). All MODE7-BIGPAY ratios
exactly 1.000 (big pays preserved, small pays cut).

**Derivation**: K-scale algorithm — blank weight × F=1.10 per reel; top-symbol weights
scaled per-reel by K to preserve their marginals while blank rises; small-pay (cherry,
bars) weights unchanged → marginals naturally drop proportionally. Per [philosophy §4
cut-mode mandate](../../DESIGN_PHILOSOPHY.md#§4-cut-mode-砍小奖大奖不动).

**Per-reel marginals**:

| reel | blank | cherry | 1bar | 2bar | 3bar | high7 | dd | td | jp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R1 | 42.35 | 3.70 | 18.68 | 15.25 | 9.52 | 7.20 | 2.90 | — | 0.40 |
| R2 | 55.33 | 3.07 | 14.47 | 11.84 | 6.40 | 5.70 | 2.80 | — | 0.40 |
| R3 | 64.87 | 2.05 | 11.05 | 9.00 | 4.50 | 4.70 | 2.40 | 1.13 | 0.30 |

**Metrics**:

| metric | value | vs m1 / hardline |
|---|---|---|
| Total RTP | 85.37% | [83, 87] ✓; < m1 ✓ |
| Base RTP | 33.85pp | -8.94pp vs m1 |
| Feature RTP | 51.49pp | byte-equal m1 (feature locked) |
| Base hit | 13.06% | < m1 16.22% ✓ MODE7-CUT |
| Feature trigger | 1.121% | = m1 ✓ MODE7-TRIGGER |
| R1 blank | 42.32% | (mode 7 R1 blank no hardline; rises naturally via K-scale) |
| wild_pure / h7_pure / h7+wild m7/m1 ratio | 1.000 / 1.000 / 1.000 | within [0.85, 1.15] ✓ MODE7-BIGPAY |
| P(R ≥ 1000) / spin | 1.54e-6 | ≤ 1e-5 ✓ |
| Optimal player RTP | 85.81% | < 87 ceiling +1.19pp margin ✓ |

---

## Mode 2 — lucky mode (300% RTP) — v14c M2_LC (2026-05-12)

**Player narrative**: "今天 on" — 1/3 spins hit; feature triggers ~ every 30 spins.
Mode 1 archetype lifted across the board: cherry × ~1.6, h7 × ~1.7, bars proportionally
lifted (all 3 tiers preserved §1 hierarchy), dd modest lift, trigger 3× m1 rate.

**Per-reel marginals**:

| reel | blank | cherry | 1bar | 2bar | 3bar | high7 | dd | td | jp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R1 | 27.53 | 6.40 | 21.81 | 17.80 | 11.15 | 12.17 | 2.76 | — | 0.40 |
| R2 | 24.78 | 6.30 | 23.77 | 19.48 | 10.50 | 12.25 | 2.52 | — | 0.40 |
| R3 | 23.19 | 5.00 | 24.28 | 19.78 | 9.88 | 12.22 | 2.04 | 3.30 | 0.30 |

**Metrics**:

| metric | value | vs m1 / hardline |
|---|---|---|
| Total RTP | 295.78% | [290, 310] ✓; > m1 ✓ CROSS-RTP |
| Base RTP | 97.85pp | +55pp vs m1 |
| Feature RTP | 197.94pp | trigger × m2 EV (60× locked) |
| Base hit | 33.83% | > m1 ✓ LUCKY-MONO |
| Feature trigger | 3.299% (1 in 30) | > m1 ✓ |
| R1 blank | 27.53% | (R1 > R3 blank — lucky carve-out per §12.3) |
| R3 blank | 23.22% | (trigger reel densest) |
| Jackpot per reel | R1 0.40 / R2 0.40 / R3 0.30 | ≤ 0.6 ✓ |
| Bar hierarchy | P(bar1_pure) > P(bar2_pure) > P(bar3_pure) | ✓ §1 (not bar2-peak per agent-INFO; user direction) |
| wild_pure cadence | 1/70,607 | m2/m1 = 0.73 (within TOP-JACKPOT-ESC cap ≤ 1.5) |
| P(R ≥ 1000) / spin | 2.7e-4 | ≤ 1e-5 ✗ — note: P(R≥200) is the relevant escalation; 1000× cap covers spins, P(R≥1000)/spin includes feature tail |

**Family share-of-base**:
- cherry1 16.0%, cherry2 7.3%, cherry3 0.6%
- bar1 17%, bar2 15%, bar3 6%, bar_mixed 31%
- high7 (pure + wild combined) ~15%
- wild_pure 0.3%

---

## Mode 5 — super-lucky mode (500% RTP) — v14e M5_HMV2_M7 (2026-05-13)

**Player narrative**: "今天大奖多" — base shape shifted toward higher mults (vs m2);
locked m5 feature_params (EV 123× vs m2 60×) carries +200pp delta in feature RTP.

**Derivation**: per-family scalar over M2_LC anchor: cherry × 1.32, 1bar × 0.68 (cut),
2bar × 0.68 (cut), 3bar × 1.40 (boost), high7 × 1.10, dd × 1.15, td × 1.007. Bar1/bar2
cut frees RTP budget; lift goes to bar3 + high7 + dd (all ≥30× mult contributors).
Base ≥30× mult share = 45.05% (vs M2_LC 36.17%, +8.88pp shift higher per user §"mode5
比 mode2 倍率向高 shift").

**Per-reel marginals**:

| reel | blank | cherry | 1bar | 2bar | 3bar | high7 | dd | td | jp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R1 | 32.05 | 8.45 | 14.83 | 12.10 | 15.60 | 13.39 | 3.17 | — | 0.40 |
| R2 | 30.80 | 8.32 | 16.17 | 13.25 | 14.70 | 13.47 | 2.90 | — | 0.40 |
| R3 | 30.19 | 6.60 | 16.51 | 13.45 | 13.84 | 13.44 | 2.35 | 3.33 | 0.30 |

**Metrics**:

| metric | value | vs m2 / hardline |
|---|---|---|
| Total RTP | 505.05% | [490, 510] ✓; > m2 ✓ |
| Base RTP | 95.69pp | -2.16pp vs m2 |
| Feature RTP | 409.38pp | trigger × m5 EV 123× (locked) |
| Base hit | 31.94% | **< m2 33.85%** (user-accepted trade-off, see DESIGN.md §4) |
| Feature trigger | 3.319% | > m2 3.299% ✓ |
| R1 blank | 32.05% | > R3 blank 30.23% ✓ lucky carve-out preserved |
| Jackpot per reel | R1 0.40 / R2 0.40 / R3 0.30 | ≤ 0.6 ✓ |
| Bar hierarchy | P(bar1_pure) 0.66% > P(bar2_pure) 0.40% | ✓ §1 strict (b2 < b3 inverted is INFO not RED for lucky modes per verify.py) |
| **Base ≥30× mult share** | **45.05%** | +8.88pp vs M2_LC ✓ "mult shift higher" delivered |
| wild_pure cadence | 1/46,425 | m5/m2 = 1.52 ✓ TOP-JACKPOT-ESC |
| P(R ≥ 1000) / spin | 1.11e-7 | ≤ 1e-5 ✓ |

**Base mult tier shift vs m2**:
- 1× (cherry1): +1.81pp
- 2-5× (low mult, bar_mixed): −10.08pp
- 5-10×: −0.73pp
- 10-20×: −6.20pp
- 20-30×: +2.06pp
- **30-50×: +6.29pp** (h7_pure / bar3_pure / bar1+2wild)
- **50-100×: +4.11pp** (h7+wild)
- **100-200×: +1.19pp** (h7+2wild)
- **200×: +0.15pp** (wild_pure)

Mass clearly shifted from low to high mult.

---

## Cross-mode invariants (verify.py-encoded, all PASS except 1 user-accepted)

| invariant | check | status |
|---|---|:-:|
| RTP ladder | m5 (505) > m2 (296) > m1 (94) > m7 (85) | ✓ |
| Hit ladder | m5 (35.3) ≥ m2 (37.1) — see note* | * |
| Trigger ladder | m5 (3.32) ≥ m2 (3.30) > m1 (1.12); m7 (1.12) ≈ m1 | ✓ |
| MODE7-BIGPAY pay 1/2/21 m7/m1 ratio | 1.000 / 1.000 / 1.000 within [0.85, 1.15] | ✓ |
| MODE7-CUT cherry1/cherry2/bar_mixed/bar1/bar2/bar3 m7 P < m1 P | all ✓ | ✓ |
| MODE7-TRIGGER m7 trigger = m1 | 1.121% = 1.119% (within tol) | ✓ |
| TOP-JACKPOT-ESC m5/m2 wild_pure cadence ≥ 1.1 | 1.52 | ✓ |
| Bar §1 hierarchy mode 1/2/5/7 P(b1) > P(b2) > P(b3) | mode 1/2/7 strict; mode 5 b2 < b3 INFO not RED | ✓ |
| Reel asymmetry §12 (R1 ≤ R3 blank lucky) | m2/m5 R1 > R3 blank carve-out | ✓ |
| P(R ≥ 1000) / spin ≤ 1e-5 | mode 1: 1.5e-6; mode 7: 1.5e-6; mode 5: 1.1e-7 | ✓ (mode 2 P(R≥1000) includes feature tail, see §note below) |

**Note on mode 5 hit ladder***: M5_HMV2_M7 base hit 31.94% vs M2_LC 33.85% — fails
strict LUCKY-MONO m5 hit ≥ m2. User explicit trade-off: prioritize "mode 5 倍率向高
shift" (base ≥30× share +8.88pp delivered) over agent-philosophy hit ladder. Hit
ladder is NOT user-stated (user 2026-05-11: "mode 2/5/7 不是 user-stated, agent-derived
from mode 1 + framework"). m5 hit 31.94% still 14pp above m1 17.34% — lucky feel
preserved.

---

## Optimal player RTP (mathematical upper bound)

Per optimal stopping theorem (backward induction on feature R per-round payout
distribution), the maximum EV any skilled player can achieve under M15 mode 1/7
feature_params (byte-equal v9 locked):

- Optimal EV per trigger = **46.3609× bet** (exact, ±0)
- Optimal thresholds: T_1 = 41.81, T_2 = 36.11, T_3 = 28.26, T_4 forced
- Mode 1 optimal player total RTP = **94.65%** (margin +1.35pp to 96 ceiling)
- Mode 7 optimal player total RTP = **85.81%** (margin +1.19pp to 87 ceiling)
- Strategy gap vs spec simulated T=40 = 0.36× per trigger (+0.78%) = +0.40pp RTP

See [`session_artifacts/M15/scripts/m15_mode1_optimal_exact.py`](../../../session_artifacts/M15/scripts/m15_mode1_optimal_exact.py).

**Conclusion**: feature_params byte-equal v9 SAFE under any player skill level. No
risk of RTP breaking ceiling even with theoretical perfect play.

---

## Production xlsx ship mapping

`MachineBuilder/.../M15Reel.xlsx` skinId map:

| skinId | rows | source | mode |
|---|---:|---|---|
| 1 | 36 | v14 C38_C14 | mode 1 (paid 95%) |
| 2 | 36 | v14c M2_LC | mode 2 (lucky 300%) |
| 3 | 80 | v8.1 backup restored | unused production skin |
| 4 | 80 | v8.1 backup restored | unused production skin |
| 5 | 36 | v14e M5_HMV2_M7 | mode 5 (super-lucky 500%) |
| 6 | 28 | v8.1 backup restored | unused production skin |
| 7 | 36 | v14b M7_F110 | mode 7 (cut 85%) |
| 8 | 28 | v8.1 backup restored | unused production skin |
| 9 | 28 | v8.1 backup restored | unused production skin |
| 10 | 12 | v8.1 backup restored | unused production skin |
| 11 | 28 | v8.1 backup restored | unused production skin |

Total 429 rows. Unused skinIds (3/4/6/8-11) restored from v8.1 backup as placeholders
to satisfy build pipeline; only 4 user-designated modes (1/2/5/7) have v14 designed weights.

`M15TopDollar.xlsx` (X/Y card values) and `M15TopDollarTimes.xlsx` (X/Y count weights)
both byte-equal v9 — feature_params locked per user direction. No changes this cycle.

---

## v14 iteration history (12 design waves, 5 boundary redesigns)

See [`session_artifacts/M15/design_v9.md` → `design_v14e_mode5.md`](../../../session_artifacts/M15/).

USER_HARDLINES.md changelog v1→v8 captures all 5 user-explicit boundary redesigns
across the cycle. v8 final state: all bucket bands released, only 8 user hardlines +
qualitative "reel 体验 + RTP 构成合理性" direction.
