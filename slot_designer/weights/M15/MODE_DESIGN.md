# M15 4-Mode 数值概览 + 玩家感性体验

> **上游**：[`DESIGN.md`](DESIGN.md)（Top Dollar 原型研究）；`project_slot_designer_mode_rtp_invariants.md`（跨机台 mode RTP 规则）  
> **下游**：每 mode `mode_<N>/NOTES.md` + `weights.json`（实现层）  
> **状态**：2026-04-23 设计稿 **v5 verified**（数字已用扩展后的 `analyze_feature(x_value_weights)` 跑过，deviation ≤0.01%）  
> **v5 核心**：count_y 改成 per-mode（不跨 mode 共享）；新增 `x_value_weights` 10-tuple 作为主要 mode 差异 dial；mode 1/7 EV floor ~45.5 的结构性发现——通过窄化 mode 1/7 的 count_y 到 (75,20,5) 腾出 alpha 空间。

---

## 0. 设计契约 + 术语

| 约束 | 值 | 严格度 |
|---|---|---|
| mode 1 Total RTP | **95%** | ±1pp 严格 |
| mode 2 Total RTP | **300%** | ±10-20pp 可漂 |
| mode 5 Total RTP | **500%** | ±10-20pp 可漂 |
| mode 7 Total RTP | **85%** | ±1pp 严格 |
| Base : Feature split (base) | 45 : 55 | 派生 mode 可漂 |
| mode 2 vs mode 1 | **trigger 拉 2.4×**，EV ≤ 1.5× m1 | user brief |
| mode 5 vs mode 2 | trigger 同 m2，**EV 拉 2.2×** | user brief |
| mode 7 vs mode 1 | base 砍小奖，feature 完全同 m1 | user brief |
| **count_x 结构** | **2-3 offer dominant** 跨所有 mode | user brief |
| count_y 结构 | **per mode**（v5: 可漂，支持 EV 目标） | 设计选择 |

**术语**：
- **Trigger rate**：每付费 spin 触发 feature 的概率
- **EV（单次触发倍率）**：`E[R | trigger]`，进 feature 后最终接受那一轮的 multiplier 期望值（平均 payout = bet × EV）
- 关系：`feature_RTP (per spin) = trigger × EV`

**4 个 designer dials** (per mode)：

1. **trigger rate**（reel 3 Bonus weight / reel 3 total）
2. **count_x weights** (5-tuple) — **跨 mode 锁定 `(5, 40, 40, 12, 3)`**
3. **count_y weights** (3-tuple) — **per mode**
4. **x_value_weights** (10-tuple) — **per mode**，最主要 differentiation dial

---

## 1. count_x 锁定（所有 mode 共享）

`count_x = (5, 40, 40, 12, 3)`

| 抽几张 x | 权重 % | 玩家体验 |
|---|---|---|
| 1 | 5% | 罕见，classic TD 单 offer 复古感 |
| 2 | **40%** | 双 offer 展开 |
| 3 | **40%** | 三 offer 展开 — M15 核心 reveal drama |
| 4 | 12% | 偶尔大场面 |
| 5 | 3% | 极罕见 "满桌子" |

**80% rounds 是 2-3 卡 reveal** → M15 签名机制，跨 mode 一致。

---

## 2. 每 mode 的三个 dial

v5 `analyze_feature()` 验证通过，deviation ≤ 0.01%：

| Mode | Trigger | count_y | x_value_weights | EV | Feature RTP |
|---|---|---|---|---|---|
| 1 | 1.14% (1/88) | (75, 20, 5) | `[0.0001, 0.0266, 0.1455, 0.1455, 1.3729, 1.3729, 7.4998, 7.4998, 40.9684, 40.9684]` | **46** | 52.26pp ✓ |
| 7 | 1.14% (同 m1) | (75, 20, 5) | 同 m1 | 46 | 52.26pp ✓ |
| 2 | 2.75% (1/36) | (60, 30, 10) | `[0.0009, 0.0914, 0.3687, 0.3687, 2.3289, 2.3289, 9.3906, 9.3906, 37.8657, 37.8657]` | **60** | 164.98pp ✓ |
| 5 | 2.77% (≈同 m2) | (40, 35, 25) | `[0.1918, 1.6065, 3.0458, 3.0458, 7.0955, 7.0955, 13.453, 13.453, 25.5065, 25.5065]` | **132** | 364.98pp ✓ |

x 牌 per-value 抽样概率（归一化到 6 unique values）：

| Mode | P(1000) | P(100) | P(50) | P(20) | P(10) | P(5) | 单 pick mean | Accept rate per round |
|---|---|---|---|---|---|---|---|---|
| 1 / 7 | **0.00%** | 0.03% | 0.29% | 2.75% | 15.00% | **81.94%** | 28.3 | 23.5% |
| 2 | 0.00% | 0.09% | 0.74% | 4.66% | 18.78% | 75.73% | 36.8 | 35.4% |
| 5 | **0.19%** | 1.61% | 6.09% | 14.19% | 26.91% | **51.01%** | 94.1 | 64.5% |

**结构性观察**：
- mode 1/2 的 **P(1000) ≈ 0%** ——mode 5 是**唯一真正有 1000-card jackpot moment** 的 mode。这是 "mode 5 = 幸运升级" 在 UX 层的具体体现。
- mode 5 的 P(5) 掉到 51% → "垃圾 offer 率" 明显下降，每张卡都更有分量。
- Accept rate 从 mode 1 的 24% 攀到 mode 5 的 64% —— "几乎不 reject" 的 super-lucky feel。

---

## 3. Mode 1 — **Classic 标准** (95% total)

### 3.1 数值

| 指标 | 值 |
|---|---|
| Total RTP | 95% |
| Base RTP | 42.75pp |
| Feature RTP | 52.26pp ✓ |
| Trigger | 1.14% (1/88) |
| Feature EV | 46× |
| count_y | (75, 20, 5) |
| One-round E[R] | 28.3× |
| Accept rate per round | 23.5% |
| E[R | accept] | 60.4× |

### 3.2 玩家体验剧本

**每 100 付费 spin**:
- Cherry 1× 7-9 次（base 小激励）
- 3-Bar combo 3-5 次
- **Feature trigger 每 ~88 spin 一次**

**Feature 典型剧本**（~70% 概率）：
- Round 1: `(5, 10, 5)` = 20。Reject（< 40）
- Round 2: `(5, 5, 5)` = 15。Reject
- Round 3: `(5, 10)` × 2y = 30。Reject
- Round 4 forced: `(5, 5, 10, 5)` = 25 × 2y = 50。Accept forced
- Payout ~30-60 credits

**Sweet spot 剧本**（~25% trigger）：
- 某 round 抽到一张 20 或 50 + mult，累计到 50-100 accept
- Payout 50-150

**"Mid card dream" 剧本**（~1-2% trigger）：
- 极罕见 100 card 出现：`(5, 100, 5)` = 110 或 `(5, 5, 100) × 2y` = 220
- Payout 100-500 — mode 1 里最大 payout 上限

**1000 jackpot**：**mode 1 实质上没有**。P(1000) = 0.0001% per pick 约等于不会出现（session 级别的零概率）。玩家想要 1000 dream 要切 mode 5。

### 3.3 情感节奏

- Classic TD stingy feel：多数 round 全 5 / 全 10 → reject → forced round 4 拿小钱走人
- Occasional mid card(20/50) 出现 → "哟还行" accept
- Session 层：feature 是稀有 event（每 88 spin 一次），多数给 30-80× payout，偶尔 100-500× 是"记忆点"
- **不追求 1000 dream** — 那是 mode 5 的领域

---

## 4. Mode 7 — **标准低 (Slow Grind)** (85% total)

### 4.1 数值

| 指标 | 值 | 跟 mode 1 |
|---|---|---|
| Total RTP | 85% | -10pp |
| Base RTP | 32.5pp | -10pp（砍小奖）|
| Feature RTP | 52.26pp | **完全同 m1** |
| Trigger / EV / count_y / x_value_weights | 全部同 m1 | 不动 |

### 4.2 派生

**Base**: mode 1 weights × `(Cherry × 0.3, Bar × 0.77)`，直接 scale 不走 tuner。

> 2026-04-23 retuned from original `(Cherry × 0.5, Bar × 0.9)` brief. That M1-inherited formula dropped M15 base by only ~5pp (not 10pp): M15's pure_wild (pay_id 1, 200×) and wild-boosted high7 (pay_id 2, 30×) inflate when cherry/bar marginals drop, offsetting the cut. Empirically iterated to `(0.3, 0.77)` for landing total 84.92pp ∈ [85 ±1pp]. See `scripts/derive_m15_mode_7.py --verify`.

**Feature**: **100% 同 mode 1**。

### 4.3 体验

Base 明显冷清（Cherry 砍半），Feature 剧本跟 mode 1 **完全一样**。"base 让我流失，feature 希望不变"。

---

## 5. Mode 2 — **幸运 (Lucky)** (300% total)

### 5.1 数值

| 指标 | 值 | 跟 mode 1 |
|---|---|---|
| Total RTP | 300% | 3.16× |
| Base RTP | 135pp | 3.16× |
| Feature RTP | 164.98pp ✓ | 3.16× |
| **Trigger** | **2.75% (1/36)** | **2.4×** ← 核心变化 |
| **Feature EV** | **60×** | 1.30× (≤1.5× ✓) |
| count_y | (60, 30, 10) | 比 m1 宽（更多 mult）|
| One-round E[R] | 36.8× | - |
| Accept rate per round | 35.4% | +50% |
| E[R | accept] | 68.6× | - |

### 5.2 体验

**每 100 spin**: Cherry 每 4 spin, **Feature 每 36 spin**（mode 1 的 2.4×）。

**Feature 进去**：
- 跟 mode 1 一样的 reveal 结构（2-3 卡 + mult）
- 但每张卡略值钱 → accept rate 从 24% 升到 35%
- Typical payout 40-150 credits
- **100 card 出现率**是 mode 1 的 ~3×，但仍很稀有（per trigger ~0.7%）
- **1000 card 仍然实质为 0** — mode 2 不提供 jackpot moment

**核心感**："feature 变常客 + 略升级"

---

## 6. Mode 5 — **超级幸运 (Super-Lucky, feature buff)** (500% total)

### 6.1 数值

| 指标 | 值 | 跟 mode 2 |
|---|---|---|
| Total RTP | 500% | +200pp |
| Base RTP | 135pp | **同 m2** |
| Feature RTP | 364.98pp ✓ | 2.21× |
| **Trigger** | **2.77% (1/36)** | ≈ m2 (+0.7%) |
| **Feature EV** | **132×** | 2.2× ← 核心变化 |
| count_y | (40, 35, 25) | 比 m2 宽（大幅提升 mult） |
| One-round E[R] | 94.1× | 2.56× |
| Accept rate per round | 64.5% | +82% |
| E[R | accept] | 133.8× | 1.95× |

### 6.2 体验

**每 100 spin**：跟 mode 2 完全一致。玩家切 mode 无法从 base 或 trigger 感知差异。

**Feature 进去**（差异集中在此）：
- 每张卡 value 大幅偏高：单 pick mean 从 mode 2 的 37 升到 94
- **P(1000) = 0.19%** → 每 trigger ~1.9% 概率看到 1000 card → 每 ~36 trigger / ~1300 spin 一次看到 1000
- Accept rate 64% → 几乎每 round 都值得接
- P(5) 塌到 51% → "全 5 垃圾组"明显减少
- Typical payout 100-400 credits，偶尔 1000+，罕见 3000-4000 spec cap

**核心感**："mode 2 + feature supercharge buff"
- Base 没变"运气"，但 feature event 每次狠 2.2×
- mode 5 **独占 1000-card jackpot 体验** —— TD 传说时刻集中在此
- Session 记忆点：mode 2 是"频繁小胜"，mode 5 是"那次 2000+ 大爆"

---

## 7. 同 R 不同组成 — UX 质量

（v4 规则保留，v5 无变动）

**核心原则**：同 R 倍率，不同组合 UX 质量不同。设计 weights 倾向"好 UX 组合"。

**规则总结**：

1. **单大 x + multiplier** = UX 顶配（"50×2=100 翻倍"、"1000×2×2=4000 封顶"）→ mode 5 是唯一真正执行这个路径的 mode
2. **Multi-x sum（2-3 卡）** = M15 signature reveal drama，平均 UX
3. **Multi-x sum + multiplier 反转**（"三小卡 × 4 凑 accept"）= mode 1/7/2 典型 accept path —— 替代 1000 的 drama 来源
4. **5-x 散件累加** = 避免，感情单薄
5. **P(5) 保持高**（mode 1/2 80%+）= TD stingy feel 和 reject 决策感
6. **P(1000) > 0 只在 mode 5** = 明确的 mode 差异化 —— mode 5 = "jackpot hunting mode"

---

## 8. 跨 Mode 速查表

| 属性 | Mode 1 | Mode 2 | Mode 5 | Mode 7 |
|---|---|---|---|---|
| **定位** | Classic | Lucky | Super-Lucky (feature buff) | Slow grind |
| Total RTP | 95% | 300% | 500% | 85% |
| Base RTP | 42.75pp | 135pp | 135pp | 32.5pp |
| Feature RTP | 52.26pp | 164.98pp | 364.98pp | 52.26pp |
| Split | 45:55 | 45:55 | 27:73（漂） | 38:62（漂） |
| **Trigger** | **1.14%** | **2.75%** | **2.77%** | **1.14%** |
| **EV** | **46×** | **60×** | **132×** | **46×** |
| count_x | (5,40,40,12,3) | 同 m1 | 同 m1 | 同 m1 |
| count_y | (75,20,5) | (60,30,10) | (40,35,25) | 同 m1 |
| x value weights | 见 §2 | 见 §2 | 见 §2 | 同 m1 |
| P(1000) | 0.00% | 0.00% | **0.19%** | 0.00% |
| P(100) | 0.03% | 0.09% | 1.61% | 0.03% |
| P(5) | 81.9% | 75.7% | 51.0% | 81.9% |
| 单 pick mean | 28.3 | 36.8 | 94.1 | 28.3 |
| Accept rate/round | 23.5% | 35.4% | 64.5% | 23.5% |
| CV (conditional) | 0.74 | 0.78 | 1.93 | 0.74 |
| Jackpot 1000 moment | **无** | **无** | **独占** | 无 |

---

## 9. Session 级感性

**Mode 1** (classic 标准)：Cherry 小奖 grind，每 88 spin 一次 feature。Feature 70% 走"全 5 垃圾 forced"剧本，25% sweet spot accept，rare 100-card 是 mode 1 记忆点。**无 1000 dream**。

**Mode 2** (幸运)：Cherry 每 4 spin，**Feature 每 36 spin**（2.4× mode 1）。Feature 结构跟 mode 1 一样但值略高，每次稍微好接。"feature 变常客"。**100-card 偶尔出现但 1000 仍无**。

**Mode 5** (super buff)：Base 跟 mode 2 一模一样。Feature trigger 也同频。差异**全在 feature 内部**：
- P(5) 51%（vs 76%）→ 每张卡都有分量
- P(1000) 0.19%（vs 0%）→ **独占 jackpot moment**
- Accept rate 64.5%（vs 35%）→ 几乎不 reject
- 平均 payout 132× vs 60× = 2.2× buff

玩家心态："mode 2 + feature supercharge"。Session 级 big wins 在此出现。

**Mode 7** (slow grind)：Cherry 砍半 base 冷清，Feature 跟 mode 1 **完全一样**。"base 让我耗，feature 希望同 mode 1"。

---

## 10. 实现 TODO

**已完成（v5, 2026-04-23）**：
- `slot_designer/engine/feature_m15.py` 扩展 `x_value_weights` + `y_value_weights` ✓
- `_tuple_prob` 替换为 weighted sampling without replacement (`_weighted_draw_dist`) ✓
- 向后兼容：不传 value_weights 时 fallback 到 uniform ✓
- `slot_designer/scripts/tune_m15_feature.py` binary-search alpha 反推 weights ✓
- `slot_designer/scripts/verify_m15_modes.py` 跑所有 mode 跟 target 对比 ✓
- 4 mode 数字验证（all deviation ≤ 0.01%）✓
- `slot_designer/specs/M15.spec.json` 更新 feature params 到 v5 值 ✓
- `slot_designer/weights/M15/mode_1/weights.json` Phase 4 tune → 42.75pp base + feature_params block ✓
- `slot_designer/tests/test_m15_feature.py` 更新 EV 断言到 46 ✓
- `slot_designer/weights/M15/mode_7/weights.json` direct-scale from mode 1 (Cherry × 0.3, Bar × 0.77) + topdollar trigger pin ✓
- `slot_designer/weights/M15/mode_2/weights.json` Phase 4 tune (RTP+hit+trigger targets) → 135pp base + feature_params block ✓
- `slot_designer/weights/M15/mode_5/weights.json` copy mode 2 base + enhanced feature_params (EV 132×) ✓
- `slot_designer/scripts/derive_m15_mode_7.py` 派生脚本 ✓
- `slot_designer/scripts/derive_m15_mode_5.py` 派生脚本 ✓
- `slot_designer/scripts/tune.py` 扩展 `--trigger-target/--trigger-symbol/--trigger-reel/--trigger-weight` 约束 ✓
- `slot_designer/scripts/tune.py` `--sa-steps 0` 时跳过 sibling weight 写入（byte-exact sibling invariant）✓
- `slot_designer/tests/test_strips_identical_across_modes.py` 回归测（含 inject-bug self-check）✓

**Analytic 最终总 RTP**:
- mode 1: 42.951 + 52.256 = **95.207%** (target 95 ±1pp) ✓
- mode 2: 135.013 + 164.721 = **299.735%** (target 300 ±20pp) ✓
- mode 5: 135.013 + 362.427 = **497.441%** (target 500 ±20pp) ✓
- mode 7: 32.705 + 52.256 = **84.961%** (target 85 ±1pp) ✓

**未实施（推迟）**：
- Joint Phase 5 SA 跨 4 mode co-swap — 没必要：当前所有 mode 的 experience metrics (near_miss / PWDF / blank_adj) 都是 0，alternation_violations 也是 0。Phase 5 在 mode 1 tune 时已经把 strip 拉到最优，后续 mode 都 `--sa-steps 0` 保留这个 strip。

---

## 11. 总结

| Mode | 一句话 | 核心差异维度 |
|---|---|---|
| 1 | "等 TD 符号 + 多卡 reveal，无 1000 dream" | baseline |
| 7 | "慢慢耗" | base 砍小奖，feature 同 m1 |
| 2 | "feature 变常客" | **trigger 拉 2.4×**, EV ≤ 1.5× m1 |
| 5 | "feature supercharge + 独占 1000 jackpot" | **EV 拉 2.2×**，trigger 同 m2，count_y + x_value 都变 |

**跨 mode 锁定**：count_x `(5, 40, 40, 12, 3)` — 2-3 offer dominant reveal structure 是 M15 签名。

**Per-mode 变化**：trigger rate + count_y + x_value_weights 三个 dial 共同支持 4 mode 的体验差异化。mode 5 独占 P(1000) > 0 是核心 UX 卖点。
