# M15 — Top Dollar Feature Play (canonical design)

> **Machine-private design doc** per [`slot_designer/ARCHITECTURE.md`](../../ARCHITECTURE.md) §2 + [`slot_designer/ONBOARDING_PROCESS.md`](../../ONBOARDING_PROCESS.md) §3.
>
> This file is the canonical sign-off for the M15 v8 design ship.
> Full audit trail (R archetype research / A baseline / D 3 design waves / X 2 reviews / Stage 6/8/9 critiques): `session_artifacts/M15/`.

---

## 1. Archetype

**Family**: IGT Top Dollar 1-line classic (3 reels × 1 payline) + Top Dollar Feature Play overlay.

**Reference**: No public Top Dollar PAR sheet exists (per [`session_artifacts/M15/01d_research.md`](../../../session_artifacts/M15/01d_research.md)). Structural proxy = Wizard of Odds **Red White Blue** PAR (IGT 3-reel 1-line 87% / 17.35% hit / CV ~10). Modern proxy = **Double Top Dollar 2025** online release (SlotsMate: 96.24% RTP / 4000× max / "Take Offer or Try Again" mechanic).

**Why no direct PAR sheet**: per `easy.vegas` — IGT keeps Top Dollar PAR sheets private; numbers inferred from RWB + Double Top Dollar online + jurisdiction $1-denom averages.

## 2. Player narratives per mode (v14 final, 2026-05-12/13)

**v14 cycle (2026-05-12/13)** — full 4-mode redesign after user dropped all RTP bucket
bands (USER_HARDLINES.md v8). 12 design waves + 5 user-explicit boundary redesigns.

Detailed numerics: [`MODE_DESIGN.md`](MODE_DESIGN.md). Full per-mode designs:
- Mode 1: [`design_v14.md`](../../../session_artifacts/M15/design_v14.md)
- Mode 7: [`design_v14b_modes_725.md`](../../../session_artifacts/M15/design_v14b_modes_725.md) §2
- Mode 2: [`design_v14c_modes_25.md`](../../../session_artifacts/M15/design_v14c_modes_25.md) §3
- Mode 5: [`design_v14e_mode5.md`](../../../session_artifacts/M15/design_v14e_mode5.md)

| mode | candidate | RTP | hit_session | R1 blank | trigger | narrative |
|---|---|---|---|---|---|---|
| 1 (paid) | **C38_C14** | **94.26%** | 17.34% | 38.52% | 1 in 89 | classical IGT 7-bar baseline. All 6 paying families visible per reel ≥ 2%. bar hierarchy P(b1)>P(b2)>P(b3) preserved. cherry-1 anchor 18% base RTP. |
| 2 (lucky) | **M2_LC** | **295.78%** | 37.13% | 27.53% | 1 in 30 | "今天 on" — mode 1 archetype lifted across board. trigger 3× m1. h7 family lift +6.5pp share. R3 trigger reel densest (lucky carve-out §12.3). |
| 5 (super-lucky) | **M5_HMV2_M7** | **505.05%** | 35.26% | 32.05% | 1 in 30 | "今天大奖多" — base ≥30× mult share 45% (vs m2 36%, +9pp shift higher). bar1/2 cut frees RTP for h7/bar3/dd lift. locked m5 feature_params carries +200pp feature delta. |
| 7 (cut) | **M7_F110** | **85.37%** | 14.20% | 42.32% | 1 in 89 | "今天不出手" — K-scale F=1.10 algebraic derivation from m1. Big pays (h7/dd/td) marginals byte-equal m1. Small pays cut ~18%. feature byte-equal m1. |

Cross-mode invariants (all PASS in verify.py except m5 LUCKY-MONO hit ladder which is
user-accepted trade-off — see §4 below):
- RTP ladder m5 > m2 > m1 > m7 ✓
- Trigger ladder m5 ≥ m2 > m1 ≈ m7 ✓
- MODE7-BIGPAY pay 1/2/21 m7/m1 ratio exactly 1.000 ✓
- MODE7-CUT all small pays m7 P < m1 P ✓
- TOP-JACKPOT-CADENCE m5/m2 wild_pure ratio 1.52 ✓
- P(R ≥ 1000)/spin ≤ 1e-5 all modes ✓

**Optimal player upper bound (mathematical, optimal stopping theorem)**:
- Mode 1 optimal RTP = 94.65% (+0.40pp vs simulated T=40; +1.35pp margin to 96 ceiling)
- Mode 7 optimal RTP = 85.81% (+1.19pp margin to 87 ceiling)
- Feature_params byte-equal v9 SAFE under any player skill level.

## 3. v14 cycle key trade-offs

### 3.1 Mode 5 LUCKY-MONO hit ladder fail (user-accepted)

Per [`design_v14e_mode5.md`](../../../session_artifacts/M15/design_v14e_mode5.md) §11
infeasibility proof: cannot simultaneously satisfy:
- Mode 5 base ≥30× mult share ≥ 45% (user "mult shift higher" priority)
- Mode 5 hit ≥ Mode 2 hit (LUCKY-MONO hit ladder)
- Total RTP ≤ 510pp

User direct choice 2026-05-13: prioritize mult shift over hit ladder. Mode 5 base hit
31.94% < Mode 2 base hit 33.85% (-1.91pp). verify.py LUCKY-MONO hit fail = RED, but
this invariant is NOT user-stated (user 2026-05-11: "mode 2/5/7 不是 user-stated,
agent-derived from mode 1 + framework"). Mode 5 hit 31.94% still 14pp above m1 17.34%
— lucky feel preserved.

### 3.2 verify.py stale FAMILY-SHARE / PER-PAY-FLOOR bands (mode 1)

verify.py was authored under v4 design intent (different bucket structure). After v8
all bucket bands released, verify.py bands haven't been rebaselined. 4 FAMILY-SHARE +
2 PER-PAY-FLOOR REDs on mode 1 are stale-band artifacts, NOT user hardline violations.
verify.py needs future re-baselining to align with v8 archetype intent.

### 3.3 PWDF dd floor structural fail (modes 1/5/7)

Strip layout has 2 dd stops on R1/R2 and 1 dd stop on R3. Mechanism B blank
redistribute at max can lift dd PWDF to ~27-28%, below verify.py 28-34% floor.
Strip immutable in v14 scope (user "保留 strip 不变"). Precedent: v9 mode 7 shipped
with dd PWDF 31.58% < 34% floor — same structural caveat.

## 3. user_brief v1.2 tally (delivered vs requested, post-v9 wave-4)

| brief item | v1.2 target | v9 measured (mode 1/7) | status |
|---|---|---|---|
| mode 1 hit | [15, 18]% | 17.85% | ✓ |
| mode 1 base 低波动 | 感性 (informational) | CV 6.34 | INFO — user §g cancelled precise band |
| mode 1 feature 中波动 | 感性 (informational) | feature CV 0.74 | INFO — user §g cancelled precise band |
| mode 1 base:feature | RELAXED (user §a; "close to v7 45:55") | 46.6 : 53.4 | ✓ (within 2pp of v7 anchor) |
| P(count_x=1) | RELAXED (user §b) | 5% (v7 kept) | ✓ |
| P(R ≥ 1000 / spin) | ≤ 1e-5 all modes | m1 7.3e-8 / m7 7.3e-8 (m2/m5 from v8) | ✓ |
| jackpot any-reel marginal | ≤ 0.6% | m1 R1=0.40% R2=0.40% R3=0.10% | ✓ |
| mode 2 hit | [30, 35]% | 33.54% (v8 unchanged) | ✓ |
| mode 7 feature trigger = mode 1 | within tol (user §e option B) | Δ 1.5e-5pp (within 5e-4 tol) | ✓ |
| mode 7 big-pay = mode 1 | within ±15% per pay_id | all pays within ±10% | ✓ |
| paytable lock (user §h) | NEVER MODIFY | spec.json `pays` byte-identical | ✓ |
| §1 inverse pyramid bar1 > bar2 > bar3 hit | required | bar1 0.45% > bar2 0.43% > bar3 0.15% | ✓ |
| §8 cherry1 ≤ 70% of hit | preferred | cherry1 64.6% of hit | ✓ |
| §12 R1 winners-friendly | direction | R1 blank 50.6% < R3 51.9% | ✓ |

## 4. Deliberate deviations (owned)

### 4.1 base CV 6.09 in mode 1 — not in [3, 5] band
Original v1 brief target band [3, 5]; user **canceled precise band** in v1.2 §g ("low/medium volatility 是感性描述, not red line"). m1 CV runs at 6.09 — between v7's 5.77 and 6.2. INFO-only metric in verify.py.

D's [`session_artifacts/M15/mode_pretune_critique_v1.md`](../../../session_artifacts/M15/mode_pretune_critique_v1.md) §4 rigorously tested 4 mechanism categories (high-mult cuts breach §2/§7, cherry lift breaches §8/hit cap, bar3 cut delivers only Δ -0.03 sub-noise per engine measurement of X's proposed recipe, paytable change forbidden per user §h). STRUCTURAL diagnosis empirically vindicated.

### 4.2 cherry-1 dominates 87% of hits in mode 1 — over universal §8 70% cap
Archetype-mandated (IGT classic cherry-anywhere = single cherry on payline = 1× pay). Per user_brief default decision "cherry-1 1× anywhere 是 archetype 必然，**接受**". §8 carve-out documented in `verify.py [HIT-DECOMP]` category (band [0, 80%] not [0, 70%]).

### 4.3 mode 7 base CV 8.60 — exceeds mode 1 by design
Direct consequence of "砍小奖" semantic — removing high-frequency low-payout wins (cherry-1, bar_mixed) raises σ/μ ratio. User accepted in §e: "波动性会相对增加 ... 你接受".

### 4.4 mode 2 200×+ freq slightly above mode 1 (7.5×)
v1.2 §c says "200× 以上占比应该不变" (vs mode 1). v8 lands m2 P(R≥200) = 2.74e-4 vs m1 3.62e-5 (~7.5× higher). Comes from m2's higher trigger rate (3.2% vs 1.28%) × identical-shape feature distribution. To make 200×+ exactly equal m1 would require attenuating m2 feature x_value_weights tail — would also break m5's "richer big wins" direction (which user §d requires). **Accept as tradeoff** — the m5/m2 7.5× ratio remains correct directionally; only the m2/m1 absolute equality drifted.

### 4.5 top-jackpot escalation lives in feature tail, not base wild_pure
Universal §7 says m1 → m5 顶奖 freq escalation ratio ≥ 5×. v8 base wild_pure (3 doublediamond 200×) freq is essentially mode-locked because m5 base similar to m2 base. M15-specific reading: §7 escalation realized via feature R ≥ 200 cadence (m1 → m2 → m5 monotone increase 1 in 28000 → 3700 → 263).

## 5. Plugin / framework

FeaturePlugin implementation: [`plugins/`](plugins/) (Top Dollar selection mechanic — see [`plugins/feature.py`](plugins/feature.py) for FeatureSpec + 4-round accept/reroll math).

Per-mode `feature_params` (in [`weights/mode_<N>/weights.json`](weights/)):
- **m1 + m7**: byte-identical (per user §e MODE7-FEATURE-LOCK + cut-mode-preserves-feature semantic)
- **m2**: differentiated `x_value_weights` to lift EV ~46× → ~61× (lucky mode)
- **m5**: further differentiated `x_value_weights` to lift EV ~61× → ~140× (super-lucky)

## 6. Verify.py red lines

[`verify.py`](verify.py) categorizes 27 [TAG] checks across philosophy §1-15:

```
[RTP] [HIT] [1000+] [JACKPOT-VIS]                    -- §4/§9 + user_brief #1/#5/#6
[HIERARCHY] [FAMILY-SHARE] [HIT-DECOMP]              -- §1/§6/§8
[BLANK-FLANK] [REEL-ASYMMETRY]                       -- §13/§12
[VISUAL-RHYTHM]                                      -- §14.5 (v8.1) bar/top cluster + same-sym gap + top-pair dist
[PWDF-FLOOR]                                         -- §15.9 (v8.1) top any-reel + mid-pay floor
[MODE7-CUT] [MODE7-TRIGGER] [MODE7-BIGPAY]           -- §4/§9 + user_brief §e
[LUCKY-MONO] [CROSS-RTP]                             -- §9
[TOP-JACKPOT-CADENCE] [TOP-JACKPOT-ESC]              -- §7 (M15 carve-out: feature tail)
[PER-PAY-FLOOR] [PCOUNT-X-1]                         -- §6 floors + user_brief §b
[PAYTABLE-LOCK]                                      -- universal rule #36 (paytable永远不改)
[STRIP-IMMUTABILITY] [SCHEMA-FP]                     -- ARCHITECTURE §8 + §11
[BASE-FEATURE-SPLIT] [CV]                            -- INFO-only (user §a + §g)
```

Inject-bug TDD: [`tests/machines/test_M15_verify_inject_bug.py`](../../../tests/machines/test_M15_verify_inject_bug.py) — 7 scenarios (jackpot breach / blank-flank violation / mode7 trigger drift / paytable mutation / **visual-rhythm violation** (v8.1) / **pwdf floor breach** (v8.1) / baseline regression guard). v7 weights+strips snapshot pinned at `tests/machines/fixtures/M15_v7_weights/` for permanent regression coverage.

## 6.1 v8.1 visual polish wave (2026-05-11)

Two §14.5 / §15.9 PHILOSOPHY-mandate gaps from v8 closed in this wave; full audit trail at [`session_artifacts/M15/v81_visual_rhythm_audit.md`](../../../session_artifacts/M15/v81_visual_rhythm_audit.md) + [`session_artifacts/M15/v81_pwdf_audit.md`](../../../session_artifacts/M15/v81_pwdf_audit.md).

### 6.1a §14 strip rearrange — visual rhythm

**Before (v8)**: R1 non-blank sequence had 6-consecutive bar-family run (3bar→2bar→1bar→3bar→2bar→1bar at non-blank idx 6-11) — reads as "all bar zone" to player. R2 had 5-run. R1+R2 also had top-symbol adjacency (high7+doublediamond consecutive at non-blank idx 4-5 and 16-17).

**After (v8.1)**: Per-(reel, symbol) multiset preserved → marginals + RTP + hit + share UNCHANGED. Non-blank position ordering rearranged to satisfy:

| §14 threshold | M15 value | rationale |
|---|---|---|
| bar-family max consecutive run (non-blank seq) | ≤ 4 | 18-non-blank cyclic; 11 bars across tiers; R3 already at 3 proves achievable; 4 = compromise |
| top-symbol max consecutive run (non-blank seq) | ≤ 1 | no top-top adjacency; 6 top instances across 18 nb-positions |
| top-pair min cyclic distance (full strip) | ≥ 8 stops (~22% of reel) | prevent "two top in a flash" feel |
| same-symbol min cyclic gap (full strip) | ≥ 5 stops | conservative floor; current min was 6 stops |

R3 unchanged (already clean). R1/R2 hamming distance 4/18 each.

### 6.1b §15 mechanism B — PWDF active optimization

**Before (v8)**: PWDF was passive — top symbol any-reel max p_window 15.83% (mode 1 doublediamond) measured from natural strip layout. Per PHILOSOPHY §15.9 backport, passive measurement does NOT satisfy §15.

**After (v8.1)**: Mechanism B (RTP-neutral Blank redistribute) applied per mode per reel: non-top-adj Blanks → floor=1; top-adj Blanks absorb the freed weight. Total Blank weight per reel **preserved exactly** → marginals UNCHANGED → RTP/hit/share UNCHANGED. Top symbol any-reel window visibility lifted:

| mode | top symbol | pre-B max p_window | post-B max p_window | lift |
|---|---|---:|---:|---:|
| 1 | doublediamond | 16.42% | **31.47%** | +15.0pp |
| 1 | high7 | 16.42% | **31.11%** | +14.7pp |
| 1 | topdollar | 15.08% | **25.82%** | +10.7pp |
| 2 | high7 | 20.97% | **29.24%** | +8.3pp |
| 5 | high7 | 21.17% | **29.31%** | +8.1pp |
| 7 | doublediamond | 19.36% | **38.71%** | +19.4pp |

**Intentional side effect** (user-confirmed v8.1 brief: "不算副作用,甚至是需求"): mid-pay symbol (cherry / mid-bar) window visibility drops — e.g. mode 1 cherry R3 18.28% → 4.81%. Per philosophy §15.9: "玩家视觉关注从 hot mid-pays 转移到 branded top symbols" is welcomed.

`[PWDF-FLOOR]` verify.py floors set ~2-5pp below post-B achieved to leave tuner margin; mid-pay floor (3% standard / 2% cut) is a "didn't disappear entirely" sanity check.

## 7. Audit trail

| stage | artifact |
|---|---|
| 0 — user input | [`session_artifacts/M15/user_brief.md`](../../../session_artifacts/M15/user_brief.md) (v1.2 amendments §a-h) |
| 1a — data inventory | [`01a_data_inventory.md`](../../../session_artifacts/M15/01a_data_inventory.md) |
| 1b — production baseline (12 sections) | [`01b_baseline_report.md`](../../../session_artifacts/M15/01b_baseline_report.md) |
| 1d — archetype research | [`01d_research.md`](../../../session_artifacts/M15/01d_research.md) |
| 4 — design narrative | [`design_v0.md`](../../../session_artifacts/M15/design_v0.md) → [`design_v1.md`](../../../session_artifacts/M15/design_v1.md) → [`design_v2.md`](../../../session_artifacts/M15/design_v2.md) |
| 4-review — X critiques | [`mode_pretune_critique_v0.md`](../../../session_artifacts/M15/mode_pretune_critique_v0.md) + [`v1.md`](../../../session_artifacts/M15/mode_pretune_critique_v1.md) |
| 5 — verify | [`verify_run_v2_iter0.txt`](../../../session_artifacts/M15/verify_run_v2_iter0.txt) |
| 6 — tune log | [`stage6_log.md`](../../../session_artifacts/M15/stage6_log.md) + per-mode iter captures |
| 8 — empirical narrative | [`empirical_v8.md`](../../../session_artifacts/M15/empirical_v8.md) |
| 9 — final adversarial gate | [`final_critique.md`](../../../session_artifacts/M15/final_critique.md) |
| process — improvements (#1-#45) | [`process_improvements.md`](../../../session_artifacts/M15/process_improvements.md) |

## 8. Per-mode breakdown

See [`MODE_DESIGN.md`](MODE_DESIGN.md).
