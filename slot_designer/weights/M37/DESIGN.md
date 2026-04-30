# M37 — "100× Diamond" 设计

> **状态**：v7 clean-slate rebuild (2026-04-29)。删了 v1-v6 的所有 picked numbers
> 重头来。每个数字都有 explicit derivation chain，no cross-machine hardcode。
>
> **上游**：
> - [`slot_designer/DESIGN_PHILOSOPHY.md`](../../DESIGN_PHILOSOPHY.md) — universal §1-§15 first principles
> - [`slot_designer/WORKFLOW.md`](../../WORKFLOW.md) — adversarial review process
> - [`reel_strips.json`](reel_strips.json) — `_archetype` + `_invariants` + `_near_miss_design` block
>
> **下游**：
> - [`mode_<N>/weights.json`](mode_1/weights.json) — tuned per-position weights
> - [`tune_m37.py`](../../scripts/tune_m37.py) — references this doc's §-numbered derivations
> - [`verify_m37_design.py`](../../scripts/verify_m37_design.py) — same

---

## §1. Machine identity

LHS 原创机台。Chassis = Classic 3-reel 1-payline (IGT Red White & Blue / Bally
Blazing Sevens family)。Brand mechanic = multi-tier wild on R2 (mini=2×, minor=5×,
major=10×, grand=100×)。Top jackpot 1000× via `(high7|wild, grand, high7|wild)`
substitution path; pure-wild + grand pattern reroll-blocked。完整 archetype 见
`reel_strips.json _archetype` block。

**用户表达的 soft constraints (this 设计的命脉)**:

1. **Mode 1 player experience priority** — mode 1 是 user 主验证 mode (per
   memory `user_testing_machine.md`)
2. **Grand 100× 玩家正常来说应该可以中到** — 不能藏到 lifetime tier
3. **中轴 mini/minor/major 也是机台特色玩法** — 3-wild jackpot path 必须可见
4. **Production 数值是 input to optimize, not reference** — 不抄 production freq

---

## §2. Mode RTP targets (USER-SPEC, not picked)

| Mode | RTP | Tolerance | 性质 |
|------|-----|-----------|------|
| 1 | 95% | ±1pp | Standard 主模式 (严格) |
| 7 | 85% | ±2pp | Cut 模式 (砍小奖) |
| 2 | 300% | ±20pp | Lucky |
| 5 | 500% | ±40pp | Super-lucky |

> RTP 4 个数 + 4 个 tolerance 都是 user/business spec，不是 Claude pick。

---

## §3. Hit rate target (DERIVATION CHAIN)

**研究输入**: classic 1-line slot hit rate 历史区间。
- Cherry-heavy classic (RWB / Blazing Sevens 70-80年代): 25-35% hit rate
- Modern multi-tier wild (Lightning Link / Dragon Link 2010s+): 15-22% hit rate

**M37 定位**: LHS 原创"classic chassis + 倍率 wild" — 现代化 classic。落在 modern range。

**Mode 1 target derivation**:
- 取 modern range 中位 → 18%
- Tolerance ±5pp (broad band — 让 optimizer 找自然解，不强制具体数)
- 18% 不是 picked，是"modern multi-tier wild slot 中位"研究均值

**Mode 7**: 砍小奖 (per universal §4)，hit < mode 1。
- Mode 1 ~18% → mode 7 ~14% (Low tier ↓ ~30%，Mid+ 不动)
- Tolerance ±3pp

**Mode 2** (lucky): hit > mode 1 (per universal §9 + §4)。
- Lucky tier 玩家感觉 "今天热了" → hit ~ 1.4× mode 1 = 25%
- Tolerance ±5pp

**Mode 5** (super-lucky): hit ≈ mode 2 (per §4 super-lucky preserves m2 hit shape，仅顶奖加密)。
- ~30% with broad tolerance ±8pp

| Mode | Hit target | Tolerance | 推导 |
|------|-----------|-----------|------|
| 1 | 0.18 | ±0.05 | modern multi-wild slot 中位 |
| 7 | 0.14 | ±0.03 | m1 - 砍小奖派生 |
| 2 | 0.25 | ±0.05 | m1 × 1.4 (lucky) |
| 5 | 0.30 | ±0.08 | m2 + 顶奖加密 (super-lucky) |

---

## §4. Grand 100× signature freq (DERIVATION CHAIN)

**User brief**: "玩家正常来说可以中到这个100倍"
**Translation**: "正常来说可以中到" = "casual player has reasonable session-level
expectation of hitting it"。
**Quantify**: P(at least 1 grand alone in 1 session) ≥ 50%。

**Session 长度**:
- Casino visit research: 30-min session = 250-350 spins typical
- Choose 300 spins as "1 session"

**Math**:
- P(at least 1 hit) = 1 − (1−p)^300 ≥ 0.5
- → (1−p)^300 ≤ 0.5
- → p ≥ 1 − 0.5^(1/300) = 0.00231
- → freq ≥ 1/433

**Mode 1 target**: 1/700 (above 1/433 floor, comfortable per-session visibility
without dominating High bucket too much)。Tolerance: factor of 2 (1/350 to 1/1400)。

**Mode 7**: same as mode 1 per §4 universal "cut-mode preserves big-win" — 1/700。

**Mode 2** (lucky): grand 出场更频。Lucky tier "machine 今天出手" → grand ≥ 3×
mode 1 → 1/200。

**Mode 5** (super-lucky session-level): grand 是 super-lucky 的核心 → grand ≥ 5×
mode 2 → 1/40 (or thereabouts)。

| Mode | Grand alone freq | 推导 |
|------|------------------|------|
| 1 | 1/700 | session-visibility derivation, p ≥ 0.0023 floor |
| 7 | 1/700 | = mode 1 (universal §4 cut-mode) |
| 2 | 1/200 | ~3× mode 1 (lucky tier) |
| 5 | 1/40 | ~5× mode 2 (super-lucky session moment) |

---

## §5. Mini/minor/major 3-wild jackpot signature (DERIVATION CHAIN)

**User brief**: "中轴的其他 jackpot 也是这个机台的特色玩法"。"你要考虑 rtp 占比"。

**Translation**: 3-wild paths (pay_id 102/103/104 = mini/minor/major × 100/50/20)
are signature plays — visible enough to register as "feature exists", BUT not
so frequent that they eat RTP budget that should go to base 3-of-a-kind pays.

**v7 revision (2026-04-29)** vs v6 derivation:
- v6 had mini 1/3000, minor 1/8000, major 1/15000 — made R2 booster density too
  high (~10%) which forced pay_id 9 (booster alone + side wild alone) to 78% of
  hits → "empty calorie" feel
- v7: relax to "visible per long play" tier — each ≥ once per multi-hour
  extended session (~10k spins)

**Quantify**:
- "Long play session" = 5-10 hours of casual play = ~5000-10000 spins
- Mini 3-wild (most common, 20×): visible ≥ 1 per long play → freq ≥ 1/8000
- Minor 3-wild (mid, 50×): rarer per universal §1 hierarchy → freq ≥ 1/15000
- Major 3-wild (rarest 3-wild, 100×): true rare moment → freq ≥ 1/30000

| Pay_id | 描述 | Pay | Mode 1 freq target (v7) | 推导 |
|--------|------|-----|-------------------------|------|
| 104 | mini 3-wild | 20× | 1/8000 | "long-play visibility" baseline |
| 103 | minor 3-wild | 50× | 1/15000 | hierarchy-rarer than mini |
| 102 | major 3-wild | 100× | 1/30000 | rarest 3-wild — true rare moment |

> 注：pay_id 命名跟 multiplier 反向 (102 是最大 multiplier 100×) — 这是 spec
> historical artifact from rawdata reverse-engineer。

**RTP impact**:
- Mini path: 1/8000 × 20× = 0.25pp RTP
- Minor path: 1/15000 × 50× = 0.33pp RTP
- Major path: 1/30000 × 100× = 0.33pp RTP
- Total: ~0.91pp (vs v6 ~13pp) — frees RTP for 3-of-kind base pays

**Lucky modes (2/5)**: 跟 grand alone 一样 lift。但 3-wild path 数学上是 wild × wild ×
booster 三独立家族，自然 lift 比 grand alone 更明显 (raise wild density on R1+R3 amplifies cube)。**不在 cost 中显式 target lucky mode 3-wild freq** —
让 lucky mode wild 加密自然推上去。

---

## §6. Top jackpot 1000× freq (DERIVATION CHAIN)

**Per universal §7** (DESIGN_PHILOSOPHY top jackpot escalation narrative):
- Mode 1 baseline 1/50-100k
- Mode 7 ≈ mode 1 (cut-mode preserves big)
- Mode 2 lucky 1/15-30k
- Mode 5 super-lucky 1/3-10k

**Mode 1 target**: 1/80k (mid of universal band, lifetime story tier)。Tolerance ±50% (1/40k to 1/160k)。

**Mode 7**: 1/80k = mode 1 per §4 cut-mode preserves big-win。

**Mode 2**: 1/20k (mid of universal band)。

**Mode 5**: 1/5k (mid of universal band)。

| Mode | Top jackpot freq | 推导 |
|------|------------------|------|
| 1 | 1/80000 | universal §7 mid-of-band |
| 7 | 1/80000 | = mode 1 (universal §4 cut-mode) |
| 2 | 1/20000 | universal §7 lucky mid |
| 5 | 1/5000 | universal §7 super-lucky mid |

---

## §7. Bucket distribution (DIRECTION ONLY, no picked %)

**Universal philosophy** (per `project_slot_designer §A axiom`): tier-level
direction only — Low > Mid > High > Top by hit count。

**No picked RTP share %** — 数字是 emergence from:
- RTP target (§2)
- Hit rate target (§3)
- Grand freq (§4) → seeds High bucket
- 3-wild freq (§5) → seeds High bucket
- Top freq (§6) → seeds Top bucket
- Hierarchy direction (§9) + reel asymmetry (§10)

**Cost penalty**: monotonic violation only. No "Mid 40% target" — 那是 v6 picked。
"Low > Mid > High > Top hit count" 是 direction，不是 share %.

---

## §8. Strip layout (DIRECTION + design choice，已 locked)

Strip layout 在 `reel_strips.json` 已固定。byte-identical 跨 mode。

**Universal §13 BLANK-FLANK-DIVERSITY**: enforced (no X-blank-X)。
**Universal §14 VISUAL-RHYTHM**: enforced (same-symbol cyclic distance ≥ 4 stops on 36-stop strip — derivation: "重复 instances 3 个，cyclic 距离 ≥ ⌊36/3⌋−1 = 11 上限，4 是 conservative floor for visual mix"。)
**Universal §15 WINDOW-VISIBILITY**: high7/wild adjacent on R1+R3 + grand
flanked by high7 on R2 (positions 17/19/21) — 文档在 reel_strips.json `_near_miss_design`。

---

## §9. Hierarchy DIRECTION (per universal §1)

**Direction only** (per universal §1):
- Bar tier: 1bar > 2bar > 3bar > 7bar by R1+R3 frequency (lower payout = higher freq)
- Booster tier: mini > minor > major > grand by R2 frequency

**No picked ratio** (no "1.2× gap target" cross-machine pick)。Cost penalty 仅 fire when
direction REVERSED。

---

## §10. Reel asymmetry (per universal §12)

**Direction only**:
- R1 blank ≤ R3 blank
- R1 (high7+wild) density ≥ R3 (high7+wild) density
- R2 = booster reel (excluded — special reel structurally)

**Tolerance**: R1 vs R3 absolute spread ≤ 5pp (M37-specific from "玩家可见阈值 5pp"
per `reference_classic_slot_rtp_distribution` research; NOT cross-machine copy)。

---

## §11. CV-RTP consistency (per universal §5)

**Direction**:
- Mode 5 CV ≤ mode 2 CV (super-lucky 集中 → vol 略下降；trade-off 接受)
- Mode 1 CV ≤ mode 7 CV (cut mode boom-bust)

**No specific CV cap** — let optimizer find natural per RTP target。

---

## §12. Mode-pair monotonicity (per universal §9)

Hard direction:
- Mode 2 RTP > mode 1 RTP (300 > 95) ✓ by spec
- Mode 5 RTP > mode 2 RTP (500 > 300) ✓ by spec
- Mode 7 RTP < mode 1 RTP (85 < 95) ✓ by spec
- Mode 2 hit > mode 1 hit (0.25 > 0.18) ✓ by §3
- Mode 5 hit ≥ mode 2 hit (0.30 ≥ 0.25) ✓ by §3
- Mode 7 hit < mode 1 hit (0.14 < 0.18) ✓ by §3
- Top jackpot escalation per §6 ✓ by §6

---

## §13. Mode 7 cut derivation (per universal §4)

**Mode 7 = mode 1 砍小奖派生** — small bars (1bar/2bar/3bar) cut, big-win + 7bar
preserved。

**Frozen weights** (= mode 1):
- high7 (R1, R2, R3)
- wild (R1, R3)
- 7bar (R1, R2, R3)
- mini, minor, major, grand (R2)

**Variable** (cut from mode 1):
- 1bar, 2bar, 3bar (R1, R2, R3) — optimizer can reduce
- blank (all reels) — floor ≥ mode 1 (anti-density-inflation)

**Per-pay ratio constraint** (m7/m1):
- BIG pays (1, 6, 8): preserve ≥ 0.85 (universal §4 "中/大/顶奖击中率不变" — tolerance derived from "frozen weight doesn't guarantee frozen freq because density depends on R1/R3 totals which shift when bars cut")
- BAR pays (2, 3, 4, 5, 7): cut to 0.40-0.95 range (optimizer freedom in cut depth)

---

## §14. Mode 2/5 lucky derivation (per universal §9)

**Mode 2 (lucky)**:
- All non-blank weights ≥ mode 1 (lucky has more of everything)
- Blank weight ≤ mode 1 (lucky less blank)
- Grand freq lift ~3× mode 1 (per §4)

**Mode 5 (super-lucky from mode 2 base)**:
- bars + high7 + wild + mini + minor frozen = mode 2 (preserve hit shape per §4)
- major weight ≥ mode 2 (mid-tier multiplier push)
- grand weight ≥ mode 2 × 5 (顶奖密集化 per §4)
- blank ≥ mode 2 (preserve hit pattern)

Mode 5 LUCKY-MONO (per universal §9): per-pay big-win freq m5 ≥ m2 (各路顶奖 m5 不能比 m2 稀)。

---

## §15. Cost function structure

> 详细 implementation 在 `tune_m37.py`。下面只列 component + reference 到 §-number。

| Component | 来源 | Strength rationale |
|-----------|------|---------------------|
| RTP target deviation | §2 user-spec | Strict — RTP 是 business hard-line |
| Hit rate target | §3 derived | Soft — broad band (±5pp), let optimizer find natural |
| Grand alone freq | §4 derived | Strong — signature visibility critical |
| 3-wild jackpot freq | §5 derived | Moderate — signature but not as critical as grand alone |
| Top jackpot freq | §6 derived | Moderate — universal §7 escalation |
| Bucket DIRECTION | §7 universal | One-sided penalty on direction violation only |
| Hierarchy DIRECTION | §9 universal | One-sided penalty on direction violation only |
| Reel asymmetry direction | §10 universal §12 | One-sided penalty |
| Mode 7 cut tier | §13 derived | Hard freeze on big-win weights, range cap on bars |
| Lucky mode floors | §14 derived | Hard floor (m2 ≥ m1, m5 ≥ m2) |

**WEIGHT_BOUNDS**: physical only — [1, 1000]。Lower bound 1 = "weight=0 means
symbol absent at strip position" (engine-level constraint)。Upper 1000 = sentinel
for SA mutation range (effectively unbounded — actual weights 实测自然在 1-50 区间)。
**No picked cap per family** — universal §1/§2/§3 by soft penalty only。

---

## §16. Verify red lines (per `verify_m37_design.py`)

| Category | 来源 | 性质 |
|----------|------|------|
| RTP | §2 | Hard - within tolerance |
| HIT | §3 | Hard - within tolerance |
| GRAND-FREQ | §4 | Hard - within 50% factor |
| THREE-WILD-FREQ | §5 | Hard - within 50% factor |
| TOP-JACKPOT-FREQ | §6 | Hard - within universal §7 band |
| BUCKET-DIRECTION | §7 | Hard - direction only |
| HIERARCHY | §9 | Hard - direction only (universal §1) |
| REEL-ASYMMETRY | §10 + universal §12 | Hard - direction only |
| ALTERNATION | universal §13 layer | Hard - 0 violations |
| BLANK-FLANK | universal §13 | Hard - 0 violations |
| VISUAL-RHYTHM | universal §14 | Hard - per machine sub-rules |
| WINDOW-VISIBILITY | universal §15 | Hard - per machine floor |
| MODE7-CUT | §13 | Hard - frozen weights + bar cut range |
| MODE7-TIER | §13 | Hard - per-pay ratio band |
| LUCKY-MONO | §14 + universal §9 | Hard - m5 ≥ m2 big-win freq |
| ARCHETYPE | universal §6 | Documentary - block in reel_strips.json |

---

## §17. Adversarial review pre-commit (per WORKFLOW.md)

每次 commit 前必跑：

1. Verify GREEN (§16 全绿)
2. Dump per-mode 实际数字
3. 3-5 self-questions (per WORKFLOW.md §1.3)
4. 每个"structural" claim 验证过真改不了
5. Commit message 含 `## Self-critique` 段
