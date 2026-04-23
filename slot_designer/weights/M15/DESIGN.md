# M15 设计文档 — Top Dollar 数值特性挖掘

> **目的**：把 M15 的数学身份、paytable 结构性、行业对标数据、spec 固化的约束全部铺开，作为 mode 设计的参考手册。  
> **原型**：IGT Top Dollar (1999) / Double Top Dollar (9-line variant)  
> **Scope**：不涵盖 mode 分配和 RTP 目标（见 `project_slot_designer_mode_rtp_invariants.md`），只挖 paytable 自身的数学特性。  
> **更新时间**：2026-04-23

---

## 1. 原型溯源：M15 = IGT Top Dollar

M15 **不是一个 "generic classic 3-reel"**，而是 IGT Top Dollar 系列的系统映射。识别证据：

1. **1-payline 3-reel 机械滚轮 + Bonus on reel 3** —— Top Dollar 的 trademark signature
2. **Bonus 机制**：4 个 offer（3 skip + 1 forced accept），accept/reject 决策 —— Top Dollar 独家设计（1999 起）
3. **Offer 值池**：{5, 10, 20, 50, 100, 1000}（M15 x_pool 里重复 5/10/20/50 两份）—— Top Dollar 原版 offer 池**完全一致**
4. **Y multiplier**：2 个 ×2 token —— Double Top Dollar 变种的 "up to 2 × 2×" —— 完全一致
5. **Wild = Double Diamond ×2 per wild, multiplicative** —— Top Dollar / Double Diamond 家族 wild 机制
6. **Cherry 独立结算 + Jackpot symbol top pay** —— Top Dollar 式的 symbol 分层

**变体选择**：M15 = 原版 Top Dollar 1-line 的骨架 + Double Top Dollar 的 ×2 multiplier 层，不是 5-reel video slot 路线。

### 1.1 Top Dollar 行业定位

| 版本 | 年代 | Layout | RTP | Top pay | Volatility |
|---|---|---|---|---|---|
| Top Dollar (原版) | 1999 | 3×3 / 1-line | 87-95%（denom 依赖） | 1000× | mid-high |
| Double Top Dollar | 2000s | 3×3 / 9-line | 96.24% | 4000× (1000×2×2) | **high** |
| M15 (本机台 mode 1 目标) | 2026 | 3×3 / 1-line | 95% | 200× base + 4880× feature max | 待定 |

引自 slotsmate.com、knowyourslots.com、toplineslotmachines.com。

---

## 2. Base game paytable 结构（Top Dollar 1:1 映射）

### 2.1 Cherry 独立结算（高优先级）

| Cherry 个数 | 倍率 | M15 pay_id |
|---|---|---|
| 1 | 1× | 14 |
| 2 | 5× | 13 |
| 3 | 15× | 12 |

**规则**：任何 reel 出现 Cherry → 忽略其它 reels 所有符号，只按 Cherry 个数结算。Wild 不替代 Cherry。  
**Top Dollar 对应**：完全一致。Top Dollar 的 Cherry 也是"任何 reel 出现就算，独立结算"，pay 值 1/2/5 或 1/5/15（denom/variant 依赖）。M15 选 1/5/15 路线。

### 2.2 Bar 家族（3-same + mixed）

| 组合 | 倍率 | M15 pay_id |
|---|---|---|
| 3 Bar1 (single bar) | 20× | 9 |
| 3 Bar2 (double bar) | 10× | 8 |
| 3 Bar3 (triple bar) | 5× | 7 |
| Mixed 3 Bar (bar1+bar2+bar3) | 2× | 11 |

**注意**：Top Dollar 传统命名是 1bar/2bar/3bar（视觉上的 bar 数），M15 用 Bar1/Bar2/Bar3。倍率跟传统 Top Dollar 一致（single bar 最高 20×，triple bar 最低 5×，mixed bar 最低 2×）。

### 2.3 Seven 家族

| 组合 | 倍率 | M15 pay_id |
|---|---|---|
| 3 High7 | 30× | 10 |

**注意**：原版 Top Dollar 的 Seven 通常只有一种（single variant），M15 也只有 High7 一种——**无 Seven1+Seven2 mixed 组合**（M1 有）。

### 2.4 Wild 机制（Double Diamond 继承）

| 规则 | 值 |
|---|---|
| 替代范围 | 除 Cherry / Blank / Bonus / Jackpot 外都可替代 |
| 单 wild 加成 | ×2 |
| 双 wild 加成 | ×4 (乘法叠加) |
| 3 wild 纯奖 | 200× (独立 pay_id 2) |
| 2 wild + 1 blank | **无奖**（不归入 pure_wild） |

**Top Dollar 对应**：Double Top Dollar 的 Double Diamond wild 机制。

**M1 对比**：M1 有**双 wild**（Diamond1 ×2 + Diamond2 ×3，product 最高 ×9）；M15 只有**单 wild** ×2，product 最高 ×4。**这是 M15 跟 Top Dollar 原型一致的核心特征**，不是简化。

### 2.5 Jackpot（declared only，不可随机转出）

| 组合 | 倍率 | 机制 |
|---|---|---|
| 3 Jackpot | 1000× | 系统特殊情况强行转出，reel 上不出现 |

**M15 实现**：
- `reel_strips.json` 里任何 reel 都**没有** Jackpot 符号 → P(3 Jackpot) = 0 analytically
- `pay_id 1` 标 `rtp_excluded: true` + `grand_jackpot: true`
- 存在于 spec 仅供 UI declared-pays 端点展示

---

## 3. Feature Play — Top Dollar bonus 的扩展版

### 3.1 基础对应

| 方面 | M15 | Top Dollar 原版 | 备注 |
|---|---|---|---|
| 触发 | Bonus 符号落 reel 3 payline | Top Dollar 符号落 reel 3 payline | 一致 |
| Rounds | 4（3 reroll + 1 forced） | 4（3 skip + 1 forced） | 一致 |
| X pool | {1000, 100, 50, 50, 20, 20, 10, 10, 5, 5} 共 10 值 | {5, 10, 20, 50, 100, 1000} 共 6 unique 值 | M15 把低值**显式复制**——{5×2, 10×2, 20×2, 50×2, 100×1, 1000×1}。每值等概率抽样等价于 Top Dollar "偏下端 skewed" 隐式权重 |
| Y multiplier | [2, 2] 两个 ×2 | 0-2 个 ×2 token (Double TD) | 一致 |
| Accept threshold | 固定 40× | Graduated: R1 ≥50 / R2 ≥45 / R3 ≥35 | **M15 简化**——单 threshold 40 而非 graduated；对应 Flip-the-Switch 简化版策略 |
| Max single value | 1000 × 2 × 2 = 4000 (single x + 2 y) | 1000 × 2 × 2 = 4000 (Double TD top) | 一致 |
| Max feature payout | sum(1000+100+50+50+20) × 4 = **4880×** (5 x + 2 y) | 4000× (单 offer) | **M15 扩展**：每轮可抽多 x 求和，max 更高 |

### 3.2 核心差异：M15 每轮抽多 x

**Top Dollar 原版**：每轮给 1 个 offer（某个 credit 数 + 可能的 ×2 multiplier）。  
**M15**：每轮抽 count_x ∈ [1, 5]（加权）个 x + count_y ∈ [0, 2]（加权）个 y，sum(x) × product(y)。

这是 **M15 对 Top Dollar 的泛化扩展**，不是直接复刻。数学上：
- 当 `x_count_weights = (100, 0, 0, 0, 0)` 且 `y_count_weights = (100, 0, 0)` 时，**M15 ≈ Top Dollar 原版**（单 offer, 无 multiplier）
- 当 `x_count_weights` 和 `y_count_weights` 分布打开时，M15 的 conditional feature EV 显著高于 Top Dollar

这给 mode 设计了一个新的 dial：**Feature 丰富度（x_count / y_count 权重）可按 mode 调**，这在 Top Dollar 原版是做不到的（每轮固定 1 offer）。

### 3.3 Feature EV 结构性下限

给定当前 spec（threshold 40, 4 rounds, x_pool/y_pool 固定），**Feature conditional EV 有数学下限**。

**最窄权重 `(1,0,0,0,0) / (1,0,0)`**（永远只抽 1 个 x, 0 个 y → 等价 Top Dollar 原版）：

| 量 | 值 | 推导 |
|---|---|---|
| 单 round E[R] | 127 | mean(x_pool) = (1000+100+2·50+2·20+2·10+2·5)/10 |
| P(R ≥ 40) | 0.40 | x ∈ {1000, 100, 50, 50} / 10 = 4/10 |
| E[R \| accept] | 300 | (1000+100+50+50)/4 |
| E[R \| reject] | 11.67 | (2·20+2·10+2·5)/6 = 70/6 |
| **4-round E[R]** | **262.6×** | 0.4·300 + 0.24·300 + 0.144·300 + 0.216·127 |
| Conditional CV | ~1.48 | (Var-E²)^0.5 / E |

**结论**：M15 Feature **conditional EV 打不低于 262.6×**。这是 spec 固化的数学下限——threshold / rounds / x_pool 的函数。要想降更低只能动 spec（改 threshold、砍 rounds、删 1000 大值）。

### 3.4 Feature EV 结构性上限

**最宽权重 `(0,0,0,0,1) / (0,0,1)`**（永远抽 5 个 x + 2 个 y）：

| 量 | 值 |
|---|---|
| Single round E[R] | E[sum of 5 x] × E[prod of 2 y] = (5 × 127) × 4 = **2540×** |
| P(R ≥ 40) | ≈ 1.0（任何 5 x 之和都 ≥ 5·5 × 4 = 100 ≥ 40） |
| 4-round E[R] | ~2540× (几乎每轮立即接受) |
| Max single trigger | **4880×** (1000+100+50+50+20) × 4 |

**结论**：M15 Feature **conditional EV 最高 ~2540×**，**单 trigger max 4880×**。

### 3.5 可调范围总结

| 场景 | count_x 权重 | count_y 权重 | conditional EV | 业界对标 |
|---|---|---|---|---|
| 极简 Top Dollar 复刻 | (1,0,0,0,0) | (1,0,0) | 262.6× | 原版 Top Dollar 1-line |
| 中档混合 | (70,25,5,0,0) | (70,25,5) | 400× | 现行 M15 mode 1 配置 |
| 高档 big-win | (30,25,20,15,10) | (50,35,15) | ~700-900× | Lucky mode feel |
| 极限上限 | (0,0,0,0,1) | (0,0,1) | ~2540× | 纯理论上限 |

---

## 4. 波动性与 hit frequency

### 4.1 行业 reference

对标 Wizard of Odds PAR sheet 的 **Red White & Blue** (classic 1-line IGT 3-reel)：

| 指标 | RWB 3-coin |
|---|---|
| Stops/reel | 64 (virtual) |
| Blanks/reel | 32 (50%) |
| Total RTP | 87.47% |
| Std dev | 10.80 (high) |
| Volatility | High |
| Bonus | 无 |

**M15 reel 结构**：
- 36 stops/reel (halving RWB 64, but same topology)
- 18 blanks/reel (50%，**跟 RWB 同密度**)
- Blank/非 Blank 严格交替（额外强加的 near-miss control 不变量）

→ M15 sits in the "**classic 1-line IGT high-volatility**" density zone. RTP 分布受 paytable 结构约束（Wild ×2 only, 无 double-wild amplification）。

### 4.2 Top Dollar 行业 hit frequency 数据

- **Base game hit**: "Cherry / Bar / Seven 小奖很频繁"（KnowYourSlots, SlotsMate）——预计 15-25% hit rate，跟 mode 相关
- **Bonus trigger**: "大约每 120 spin 一次" 是 bonus-feature 机台的业界共识（KnowYourSlots modern estimate）
  - Top Dollar 实际按 denom / variant 变化
  - M15 mode 1 当前 tune 在 **1/505**（2 Bonus stops × 1 weight / 总 1017 weight）→ 比行业典型**更稀有**
- **Volatility 分类**: Top Dollar = High volatility (SlotsMate, 业界共识)

### 4.3 波动性来源分解（M15 三层）

1. **Base 波动**（per spin）：单次付费旋转的 win 范围，主要由 Cherry/Bar 小奖 + 稀有 Wild 组合 + Seven 30× 决定。典型 CV 4-6（取决于 mode）。
2. **Feature conditional 波动**（per trigger）：一次 feature 的 5-4880× 范围。CV 1.5-2 depending on weights。
3. **Session 波动**（per 多 spin）：稀有 trigger (1/500 类) + 高 EV feature 合成的 boom-bust 节奏。玩家感性上是"等 Top Dollar"的主要张力来源。

Top Dollar 的玩家体验核心是**第 3 层**——稀有但戏剧性的 bonus。这定义了波动性 profile 不能简单用 base CV 或 feature conditional CV 单独刻画。

---

## 5. 结构性约束（spec 固化的不变量）

以下是 paytable + reel_strips 强制的数学不变量，**不能通过 weight tuning 改变**，只能改 spec：

1. **Feature conditional EV ≥ 262.6×** — threshold 40 + 4 rounds + x_pool 决定的下限
2. **Feature single trigger max = 4880×** — 5 x (top picks) + 2 y = (1000+100+50+50+20) × 4
3. **Base single payline max win = 200×** — 3-Wild pure pay (Jackpot 不可随机转出，不计)
4. **Base hit rate 上限 ~50%** — 由 Blank 占比 (50%) × 非 Blank probability 决定
5. **3-Jackpot 数学上永远 P=0** — strips 里无 Jackpot symbol
6. **Bonus 仅 reel 3 trigger** — reel 1/2 完全没有 Bonus，P(Bonus on payline) = P(Bonus on reel 3 stop 1)
7. **Wild product 上限 ×4** — 单 wild + 双 wild 限制，无多 wild 叠加层（M1 有 ×9）

这 7 条跟 Top Dollar 原型结构完全绑定，改任何一条都是动 spec 的决定，不是 tuning 行为。

---

## 6. Mode 设计可调的 dials

相对上面的 spec 固化项，mode 层可调的维度：

| Dial | 取值范围 | 影响 |
|---|---|---|
| Base reel weights | per-symbol per-reel (18 non-Blank stops) | Base RTP / hit rate / bucket shape |
| Bonus weight on reel 3 | 1 to ~50 per stop (2 stops) | Feature trigger rate (1/500 to 1/20) |
| `x_count_weights` (per mode) | 5-tuple (w1..w5) | Feature conditional EV（越宽越大） |
| `y_count_weights` (per mode) | 3-tuple (w0, w1, w2) | Feature conditional EV（越宽越大） |
| Accept threshold | 固定 40，改要动 spec | 只在"动 spec" 路径可调 |

**派生关系** (按 `project_slot_designer_mode_rtp_invariants.md`)：
- mode 7 from mode 1: base weights Cherry × 0.5, Bar × 0.9 (砍小奖)
- mode 5 from mode 2: **调 feature x_count/y_count weights** 加 EV（feature 机台的"加大奖"专用路径）；base 不动

M15 "有 feature" 的身份让 `mode 5 ← mode 2` 走 **feature enhance 路径**（不动 base，调 count weights 把 conditional EV 从 X× 拉到 (X+200)×），跟 M1 这种无 feature 机台的"加 top-bucket 权重"路径不同。

---

## 7. 行业 RTP 范围（跨 Top Dollar 变体）

| 版本 | Total RTP | Base : Feature split | 数据来源 |
|---|---|---|---|
| Top Dollar nickel | ~87% | unknown | Harrington Raceway |
| Top Dollar $1 | ~92% | unknown | industry average |
| Top Dollar high-limit | ~95% | unknown | industry average |
| **Double Top Dollar 9-line** | **96.24%** | unknown (not published) | SlotsMate |
| Red White & Blue 3-coin (no feature) | 87.47% | 100 : 0 | Wizard of Odds PAR |
| Blazing Sevens classic | 89% | 100 : 0 | 业界 |

**M15 锁定 mode 1 = 95%** 正好落在 Top Dollar high-limit / Double Top Dollar 的 RTP 带里，**跟原型行业基准一致**。

**Split 未知**：Top Dollar 厂家不公布 base vs bonus 的 RTP 分配，M15 的 45:55 是用户 brief 定的。参考值：
- 如果参照现代 video slot "bonus-heavy"：35:65 到 45:55
- 如果参照 mechanical classic "base-heavy"：70:30 到 85:15
- **M15 选 45:55**：bonus-heavy / Cleopatra-edge 风格，现代化 Top Dollar

---

## 8. 跟 M1 的关键差异（为什么是 Top Dollar 不是 RWB）

M1 的原型是 **Red White & Blue** / **Blazing Sevens** 类 (纯 base, no feature)：
- 双 wild (Diamond1 ×2 + Diamond2 ×3, product up to ×9)
- Seven1 + Seven2 mixed 组合
- 无 feature bonus
- Base RTP 94/290/500/85 (M1 mode 1/2/5/7)

M15 的原型是 **Top Dollar**：
- 单 wild (Double Diamond ×2, product up to ×4)
- Single Seven (High7 only)
- **Bonus Feature** on reel 3 with offer/accept 机制
- Total RTP 95/300/500/85 (跟 M1 同，per cross-machine invariant)，但**每 mode 分 base + feature 两段**

Design implications:
- M15 的 Mid-bucket 比 M1 薄（wild layer 厚度减半）
- M15 的 High-bucket 由 feature 主导（M1 靠 3-Wild pure 200× + High7×wild² 120×）
- M15 的 mode 5 `↑` 路径通过 feature enhance 实现（M1 要靠 top-bucket weight）

---

## 9. 数据引用

- **KnowYourSlots: Top Dollar Mechanical Reel** — https://www.knowyourslots.com/top-dollar-mechanical-reel-slot-machine-stalwart-with-modern-popularity/ — 1-line / 2-3 credit / 1000 top pay / bonus on reel 3 / Double Top Dollar multiplier extension
- **SlotsMate: Double Top Dollar** — https://www.slotsmate.com/software/igt/double-top-dollar — 9-payline / 96.24% RTP / high volatility / max 4000× / Double Diamond wild
- **Wizard of Vegas forum: Top Dollar strategy** — https://wizardofvegas.com/forum/gambling/slots/27453-top-dollar-bonus-game-strategy/ — accept R1 ≥50, R2 ≥45, R3 ≥35 graduated strategy
- **Flip the Switch: Top Dollar offer math** — https://fliptheswitch.com/taking-the-right-offer-on-top-dollar-and-other-slots/ — "accept ≥35" 简化版 / majority-odds threshold
- **Wizard of Odds: Red White & Blue PAR sheet** — https://wizardofodds.com/games/slots/appendix/6/ — 64 stops / 32 blanks (50%) / 87.47% RTP / std_dev 10.80 reference
- **KnowYourSlots: Bonus frequency** — https://www.knowyourslots.com/slot-volatility-bonus-round-outcomes-and-frequency/ — "~1/120 spins" modern bonus-frequency benchmark
- **KnowYourSlots: Hit frequency math** — https://www.knowyourslots.com/slot-machine-math-hit-frequency/ — slot math framework reference
- **Harrington Raceway Top Dollar page** — https://casino.harringtonraceway.com/top-dollar-slot-machine — denom-variable RTP notes
- **TopLineSlotMachines: IGT AVP Top Dollar** — https://toplineslotmachines.com/products/igt-avp-top-dollar — hardware variant listing

---

## 10. 小结

**M15 数学身份**：IGT Top Dollar (1-line) 的直接系统映射，Base paytable 1:1 复刻（Cherry/Bar/Seven/Wild/Jackpot），Feature 是 Top Dollar bonus 的泛化扩展版（每轮抽多 x 求和 + 简化 threshold）。

**Spec 固化不变量**：
- Feature conditional EV ∈ [262.6×, 2540×]
- Feature single trigger max = 4880×
- Base single win max = 200×
- Bonus 仅 reel 3

**Mode 可调 dials**：Base reel weights、Bonus trigger rate、Feature count_x/count_y 权重、波动性 profile。

**行业 RTP 带**：Top Dollar 跨 variant 87-96%，M15 mode 1 锁 95% 在正中。

**Mode 5 ← mode 2 加大奖专用路径**：M15 有 feature，mode 5 通过 feature x/y 权重 enhance 把 conditional EV 从 mode 2 的 X× 拉到 (X+200)×，base 不动。
