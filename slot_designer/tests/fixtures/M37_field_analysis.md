# M37 — field analysis (rawdata reverse-engineering)

> **Phase 2 产出**（FIRST_MACHINE.md v3）：从 `rawdata/M37/mode_{1,2,5,7}/chunk_*.json`
> 反推机制。**只关心机制（pay_id 怎么算、wild 怎么 sub、什么组合被屏蔽）**，
> 数值层面（RTP / bucket 分布）**不看**，数值是我们独立设计的。
> 数据日期：2026-04-24（mode 7 有 261 chunks / 2.14M rounds 可靠样本；mode 1/2/5
> 各 1 chunk = 10k rounds）。

## 1. Envelope schema

跟 M15 同款（`_machine / _mode / _bet / _spin_times / _robot_count /
response (list of {roundResult, analysisResult}) / _config_md5 / _code_md5`），
round schema 标准 17 字段，`roundResult` 是 JSON string。

**机台特色字段**：
- `ReelSkin` = mode number（1/2/5/7）— 每 mode 走自己的 skin ID
- `SpinType` 永远 = 1（**无 feature engine**，不涉及 ST=14/15）
- `ReMarks` 永远 '' （空）
- `StopSymbolsByCol[c]` = "top-mid-bot-" 3 字符串，每 col 有 3 行

## 2. Symbol 清单 + 每 reel 分布

9 个符号类，分两类出现：

**所有 reel 都有**：blank, high7, 2bar, 3bar, 7bar, 1bar
**Reel 1 + Reel 3 专有（中间 reel 无）**：wild
**Reel 2 专有（外 reel 无）**：mini, minor, major, grand

**分布（从 2-5 chunk 抽 60k rounds 得）**：

| Symbol | Reel 1 | Reel 2 | Reel 3 | 备注 |
|---|---|---|---|---|
| blank | ~48% | ~50% | ~48% | filler |
| wild | ~10% | **0%** | ~10% | 仅外 reel |
| high7 | ~8% | ~8% | ~8% | regular |
| 7bar | ~8% | ~8% | ~8% | regular |
| 3bar | ~8% | ~8% | ~8% | regular |
| 2bar | ~8% | ~7% | ~8% | regular |
| 1bar | ~8% | ~4% | ~8% | regular |
| mini | **0%** | ~3% | **0%** | booster ×2 |
| minor | **0%** | ~5% | **0%** | booster ×5 |
| major | **0%** | ~4% | **0%** | booster ×10 |
| grand | **0%** | ~3% | **0%** | booster ×100 |

**Payline**：中间行（row 1）3 格。位置编码 `(col+1)*100` → payline 位置 = {100, 200, 300}。

## 3. Paytable（11 个 pay_id 观察到）

### A. 常规 3-match（col 1 不是 booster）

| pay_id | 组合（middle row, wild subs）| Base mult |
|---|---|---|
| 1 | 3 × high7 | 10× |
| 2 | 3 × 7bar | 6× |
| 3 | 3 × 3bar | 5× |
| 4 | 3 × 2bar | 4× |
| 5 | 3 × 1bar | 3× |
| 6 | high7 + 7bar 混合（含 wild）| 2× |
| 7 | 任意 bar 混合 (1/2/3/7bar + wild) | 1× |

Wild 在 reel 1/3 替代 regular，multiplier × 1（wild 本身 =1×，不是 M1 的 ×2）。

### B. col 1 是 booster（mini/minor/major/grand）→ booster 作为中格乘数

当 col 1 ∈ {mini/minor/major/grand} 且 col 0 + col 2 能凑出 3-match
（wild 替代），则：**pay_id 同 A 组，multiplier = base × booster_multiplier**。

Booster 乘数：
- mini = ×2
- minor = ×5
- major = ×10
- grand = ×100

**实例（从 rawdata 验证）**：

| 组合（col0, col1, col2）| pay_id | mult | 推导 |
|---|---|---|---|
| (high7, mini, high7) | 1 | 20× | high7 base 10 × mini 2 |
| (wild, minor, high7) | 1 | 50× | 10 × 5 |
| (high7, major, high7) | 1 | 100× | 10 × 10 |
| **(high7, grand, high7)** | 1 | **1000×** | **10 × 100 — TOP pay** |
| (7bar, mini, 7bar) | 2 | 12× | 6 × 2 |
| (7bar, grand, 7bar) | 2 | 600× | 6 × 100 |
| (3bar, minor, 3bar) | 3 | 25× | 5 × 5 |
| (3bar, grand, 3bar) | 3 | 500× | 5 × 100 |
| (high7, mini, 7bar) | 6 | 4× | 2 × 2 |
| (1bar, minor, 3bar) | 7 | 5× | 1 × 5 |

### C. Pure-wild + booster（col 0 + col 2 都 wild，col 1 booster）→ 独立 pay_id

**跟 pay_id 1 相同 mult 但 pay_id 不同**（because 没 anchor 符号定 pay_id）：

| 组合 | pay_id | mult | = pay_id 1 的 high7 × booster |
|---|---|---|---|
| (wild, mini, wild) | **104** | 20× | 10 × 2 |
| (wild, minor, wild) | **103** | 50× | 10 × 5 |
| (wild, major, wild) | **102** | 100× | 10 × 10 |
| **(wild, grand, wild)** | **NONE** | **N/A** | **被后端 re-roll 屏蔽** |

### D. Booster 孤立（col 0/2 不成 pay）

| 组合 | pay_id | mult |
|---|---|---|
| mini 在 col 1，其他不凑 pay | 9 | 2× |
| minor 在 col 1，其他不凑 pay | 9 | 5× |
| major 在 col 1，其他不凑 pay | 9 | 10× |
| grand 在 col 1，其他不凑 pay | **8** | **100×** |

→ mini/minor/major 用 pay_id 9；grand 用 **pay_id 8**（分开是 UI / jackpot UX 设计）

### E. Wild 孤立（col 0 或 col 2 是 wild，col 1 非 booster，无其他 pay）

| 组合 | pay_id | mult |
|---|---|---|
| (wild, blank, blank) | 9 | 1× |
| (blank, blank, wild) | 9 | 1× |
| (wild, blank, wild) | 9 | 1×（仍 1 pay，不是 2×）|

→ 1 个或 2 个 wild 都是 pay_id 9 × 1×（不叠加）

## 4. 重要机制观察 — (wild, grand, wild) re-roll 屏蔽

**扫 mode 7 全量 261 chunks = 2,138,000 rounds**，查 `middle row = (wild, grand, wild)`：
**0 hits**（预期按自然概率应 ~3000 hits）。

结论：**后端机制屏蔽**这个组合。因为 pure-wild+grand 会走 pay_id 1 or 类似路径
给 1000× 顶奖，不希望顶奖这么"廉价"地出（拿 wild 就行）。通过 re-roll 保证
**1000× 只能走 `high7 + grand + high7 / wild`** 路径（有 high7 anchor），这是
机台设计的"legendary feel"支撑。

**Spec 实现**：`reroll_blocks`: `[{"pattern": ["wild", "grand", "wild"], "reason": "..."}]`。
`engine/spin.py spin()` 看到 reroll match 就重新 draw（max 50 次防死锁）。

## 5. Precedence（evaluation_order）

```
1. 无 cherry（M37 没 cherry_special kind）
2. Col 1 是 booster 吗？
   - yes → booster-center stage:
     a. col 0/2 都 wild → pure_wild_with_booster (pay 102/103/104)
     b. col 0/2 构成 3-match anchor → line_3_same × booster
     c. col 0/2 构成 line_3_group → line_3_group × booster
     d. 其他 → center_booster_alone (pay 8/9)
   - no → 继续
3. Pure wild（col 0/1/2 都 wild）→ 暂无 rule（M37 里 col 1 不会是 wild）
4. Line_3_same（wild sub）→ pay_id 1-5
5. Line_3_group（wild sub）→ pay_id 6-7
6. Side wild alone（col 0 或 col 2 是 wild，col 1 blank，无 3-match）→ pay_id 9 × 1
```

## 6. Sanity checks（reverse-engineered paytable 自洽性）

**Check 1**：pay_id 1 的 mult 集合 = {10, 20, 50, 100, 1000}
= base 10 × {1, 2, 5, 10, 100}
= high7 base × {no booster, mini, minor, major, grand} ✓

**Check 2**：pay_id 3 的 mult 集合 = {5, 10, 25, 50, 500}
= 5 × {1, 2, 5, 10, 100} ✓

**Check 3**：pay_id 8 仅 1 mult (100×) = grand 100×（只 grand 触发，不套其他 booster）✓

**Check 4**：pay_id 102 = 100×, pay_id 103 = 50×, pay_id 104 = 20×
= 10 (high7 base) × {major, minor, mini} ✓

**Check 5**：跨 mode 4 个 chunk 的 pay_id 集合完全一致 → 4 mode 共享 paytable，
只 reel 权重不同 ✓

## 7. 已知未观察（假设但未 rawdata 确认的）

- **pay_id 101**：理论上应是 "(wild, grand, wild) → 1000×" 类似 pay_id 1，但**被 re-roll 屏蔽 → 0 hits**，所以 spec 不列。如未来 re-roll 去掉，这个 pay_id 可能会出现。
- pay_id 3 × grand = 500×：理论上存在，罕见。从 samples 看 pay_id 3 的 mult 包含 {500}。✓
- pay_id 2 × grand = 600×：应在但未直接命中 sample 里 — rare event。
- pay_id 7 × grand = 100×：应在。mixed bars + grand center = 100×。

## 8. 写到 spec 里的约束

- symbols: 9 个（blank filler / high7+7bar+3bar+2bar+1bar regular / wild wild mult=1 / mini minor major grand booster with multipliers 2/5/10/100）
- pays: 14 条 rule（pay_id 1-7 line_3_same/group + pay_id 8/9 center_booster_alone + pay_id 102-104 pure_wild_with_booster + pay_id 9 side_wild_alone）
- evaluation_order: ["line_3_same", "line_3_group", "pure_wild_with_booster", "center_booster_alone", "side_wild_alone"]
- reroll_blocks: `[{"pattern": ["wild", "grand", "wild"], "reason": "..."}]`
- NO features (空数组)
- spin_types: {"1": {"kind": "paid", "cost_per_spin": 1000, "bet_amount": 1000, "reel_set": "default"}}

## 9. 跟 M1/M15 对比

| 维度 | M1 | M15 | M37 |
|---|---|---|---|
| Grid | 3×3 | 3×3 | 3×3 |
| Payline | 1 | 1 | 1 |
| Wild | ×2, ×3 两档 | ×2 单档 | ×1 单档（不放大 mult）|
| Booster 机制 | 无 | 无 | **有**（middle reel 4-tier booster） |
| Feature engine | 无 | 有（Feature Play 4-round） | **无** |
| Cherry special | 有 | 有（pay_id 9/71/4） | 无 |
| Re-roll 屏蔽 | 有（3-jackpot）| 有（3-jackpot）| **有**（(wild, grand, wild)） |
| Max base payout | ? | 200× (pure wild) + feature | **1000×** (pay_id 1 × grand) |
