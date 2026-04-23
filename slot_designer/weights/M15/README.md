# M15 — reel 权重

机器类型：classic 3-reel 1-payline **带 Bonus feature 分支**。M15 相对 M1 的差异：

- **Wild 只有一种**（M1 有 Diamond1=wild2x + Diamond2=wild3x，M15 就一个 Wild × 2）
- **Bonus 只在 reel 3 出现**，触发 Feature Play（Phase 2 实现 —— 下方「Feature Play 延后」）
- **Jackpot 是独立 symbol** 但不出现在 reel 上（不可随机转出 → P(3 Jackpot) = 0 analytically）
- **无 mixed-Seven 组合**（M1 有 Seven1+Seven2 共同组 pay_id 10；M15 只有 single high7）

## 当前状态（Phase 4 tune 完成 · Feature engine Phase 2 延后）

| mode | 类型 | Base RTP | Feature RTP | **Total RTP** | Base:Feat split | Base CV | 文件 |
|---|---|---|---|---|---|---|---|
| 1 | classic | 68.32% | 79.30pp | **147.62%** | 46 : 54 | 4.45 | [mode_1/weights.json](mode_1/weights.json) |

Target: total 150%, split 45:55, base low CV, feature mid-high (session-level)。达成。

## 设计约束（user brief 2026-04-23）

- **总 RTP 跨 mode 不变**（见 memory `project_slot_designer_mode_rtp_invariants.md`）
- Base : Feature = **45 : 55**（bonus-heavy — Cleopatra-edge per 业界研究）
- Base 低 CV（频繁小奖）
- Feature 中高 CV（1/500 稀有大爆，session CV 被稀有性撑高）

## 业界基准对比

| 机台 | Base % | Feature % | Total RTP | 备注 |
|---|---|---|---|---|
| Cleopatra (IGT) | 55% | 45% | 95% | 同类"bonus-heavy"参照 |
| Jackpot Party | 69% | 31% | 86.1% | 中频 feature |
| Money Storm | 71% | 29% | 92.5% | 同上 |
| **M15 mode 1** | **46%** | **54%** | **147.6%** | **feature-rich 总 RTP 增强** |
| Triple Double Diamond | 75% | 25% | 91.1% | base-heavy |

M15 是 "feature-rich modern 3-reel" 定位——总 RTP 150% 比 classic 高，换取 feature play 的丰富变化（x 1-5 / y 0-2 多档加权抽样）。

## 文件结构

```
slot_designer/weights/M15/
├── README.md                 ← 本文件
├── DESIGN.md                 ← Top Dollar 数值特性调研 + spec 固化约束 + mode dials 总览
├── reel_strips.json          ← 共享 symbol 布局（36 × 3, 18B + 18NB 交替）
└── mode_<N>/
    ├── weights.json          ← mode 专属 per-stop weight 数组
    ├── reel_weights.tsv      ← 人类可读 36×3 表格
    ├── NOTES.md              ← 数值 + pay_id 分解 + tune 命令
    └── TUNE_REPORT.md        ← 最近 tune 的 Phase 4/5 报告（尚未生成）
```

设计数学身份、paytable 1:1 映射、feature EV 上下限、行业 RTP 带等**不随 mode 变的 paytable 特性**全部在 [`DESIGN.md`](DESIGN.md)。README 里的 mode-specific 数字当前对齐到 2026-04-23 的 150% 布置，**跟新的跨机台 mode RTP 一致性规则（95/300/500/85）还没对齐，后续重做**。

## 结构不变量

- **Blank/非 Blank 严格交替** — 每 reel 18 Blank + 18 非 Blank，位置 0/2/4/… 是 Blank，位置 1/3/5/… 是非 Blank；环形邻接也算
- **Bonus 只在 reel 3** — reel 1 / reel 2 没有 Bonus stop
- **Jackpot 不在 reel 上** — 纯 declared pay，P(3 Jackpot) = 0

Phase 5 joint SA 跨所有 mode co-swap 保持这些不变量（`class_preserving_swap_mutation` + `initialize_alternating`）。

## 符号清单 + 每 reel stop 数

| symbol | 类别 | reel 1 stops | reel 2 stops | reel 3 stops |
|---|---|---|---|---|
| Blank | filler | 18 | 18 | 18 |
| Cherry | cherry_special | 2 | 2 | 2 |
| Bar1 | regular | 4 | 4 | 4 |
| Bar2 | regular | 4 | 4 | 4 |
| Bar3 | regular | 4 | 4 | **3** ← Bonus 占了 1 位 |
| High7 | regular | 2 | 2 | 2 |
| Wild | wild (×2) | 2 | 2 | **1** ← Bonus 占了 1 位 |
| Bonus | filler | 0 | 0 | **2** ← 仅 reel 3 |

## Paytable（见 [paytable/Paytable-M15.md](../../../paytable/Paytable-M15.md)）

| pay_id | 组合 | 基础倍率 | 备注 |
|---|---|---|---|
| 14 | 1 Cherry | 1× | Cherry 独立结算，Wild 不替代 |
| 13 | 2 Cherry | 5× | 同上 |
| 12 | 3 Cherry | 15× | 同上 |
| 11 | Mixed 3 Bar (bar1+bar2+bar3 任意) | 2× | Wild 可替代并 ×2 per wild |
| 7 | 3 Bar3 | 5× | 可 Wild 替代放大 |
| 8 | 3 Bar2 | 10× | 同上 |
| 9 | 3 Bar1 | 20× | 同上 |
| 10 | 3 High7 | 30× | 同上 |
| 2 | 3 Wild | **200×** | pure wild 特殊（不走 high7 × 8 = 240×）|
| 1 | 3 Jackpot | 1000× | **rtp_excluded, grand_jackpot**（不可随机转出）|

## Feature Play 延后（Phase 2）

paytable 定义的 bonus 玩法：

- 第 3 列出现 Bonus → 进入 feature
- 10 个 x 选项（1000, 100, 50, 50, 20, 20, 10, 10, 5, 5）+ 2 个 y 选项（各 ×2）
- 每轮：加权抽 1-5 个 x + 0-2 个 y（权重文档未说明，需要策划补）
- 无放回抽样
- 计算：sum(x) × product(y)
- 3 次 reroll + 1 次强制接受 = 4 轮上限
- 测试策略：≥40× 直接接受
- **RTP 单独统计**，不并入主游戏

**当前 spec**：Bonus 标 `filler`，payline 上出现时短路到「no pay」。Feature engine 还没实现。

**Phase 2 需要的东西**：
1. Feature engine（新的 spin type，独立 RNG 流）
2. Feature RTP 目标（策划定 —— 要几 %？40× 阈值策略改变吗？）
3. x/y 加权权重（策划补）
4. 报告里单独的 Feature 分析面板

## 下一步

1. 写 `M15_mode1_classic.target.json`（target RTP 93% / hit 12% / 按 classic 7-heavy 规范设计）
2. 跑 Phase 4 tune 对齐 mode 1 到 target
3. joint Phase 5 优化 ordering
4. 确认 analytic 对齐 paytable 预期后，考虑 mode 2/5/7 变体
5. Phase 2: 写 Feature engine + 对 RTP 独立追踪

## 当前 mode 1 analytic（pre-tune）

```
RTP:        41.38%   (目标 93% 左右，需要 tune +50pp)
hit_rate:   21.88%   (偏高，classic 单线应该 10-15%)
CV:         4.24
std_return: 1.75

Bucket RTP 占比:
  ge1_lt5   (Cherry 1-5×):      60.3%   ← Cherry 主导
  ge5_lt10  (mixed Bar 5×):     13.4%
  ge10_lt20 (3-Bar 10-20×):      5.5%
  ge20_lt50 (wild-amplified):   19.9%
  ge50_lt100:                    0.7%
  ge100_lt200:                   0.1%
  ge200_lt500:                   0.0%

Top 5 pay_id 贡献:
  pay_id 14 (Cherry 1×):       15.84pp   (38% of RTP)
  pay_id 11 (mixed 3 Bar 2×):   8.29pp   (20% of RTP)
  pay_id  9 (3 Bar1 20×):       5.41pp   (13% of RTP)
  pay_id 13 (2 Cherry 5×):      5.03pp   (12% of RTP)
  pay_id  9 (3 Bar1 × wild):    1.93pp   (5% of RTP, amplified to 40×)
```

tune 之后大概率 7 家族占比会升到 30-50%（按 classic 规范）。
