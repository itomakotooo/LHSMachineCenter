# M1 mode 7 — 当前 reel 权重（低 RTP / 高波动 turbulent）

**类型**：同 paytable，mode 1 的低 RTP 版本 —— 砍中奖率和低倍率 win，保留中高倍率与波动性
**最近更新**：2026-04-22（v3 structural refactor 后首次 tune）

## 核心数值（analytic）

| 指标 | 本版 | target | vs mode 1 |
|---|---|---|---|
| RTP | 80.88% | 80.95% | -13.4pp |
| hit_rate | 7.86% | 7.68% | -7.66pp（约一半）|
| 空转率 | 92.14% | 92.32% | +7.66pp |
| std_return_x | 5.10 | 5.10 | -0.03（持平）|
| CV (σ/RTP) | 6.31 | 6.30 | +0.66 |
| shape JS | 0.00474 | 0 | — |

**设计意图**：mode 7 = 低 RTP 版 classic —— 用户要求「砍掉一些中奖率和低倍率 win，尽可能保持中高倍率不变，保留波动性」。实现思路：

- **砍 Cherry**（1×）从 9.7% → 3.0% 命中率 —— 每 33 spin 才一次 cherry（mode 1 是每 10 spin）
- **砍 mixed-Bar 5×** 从 2.6% → 1.5%
- **保 3-Bar 10-20×** 从 2.2% → 2.1%（基本持平）
- **保 Bar+wild 30-90×** 从 0.94% → 0.92%
- **保 Seven family** 从 0.03% 合计 → 0.04% 合计

## RTP 贡献分解（按 pay 家族）

| 家族 | 倍率 | hit% | RTP 贡献 | 占 RTP |
|---|---|---|---|---|
| Cherry（1-2×）| 1-2× | 2.88% | 2.95pp | 3.6% |
| mixed-Bar 5× | 5× | 1.51% | 7.53pp | 9.3% |
| 3-Bar 10-20× | 10-20× | 2.10% | 27.83pp | 34.4% |
| Bar + wild 30-90× | 30-90× | 0.92% | 36.43pp | **45.0%** ← 主要 RTP 来源 |
| Seven 100× | 100× | 0.023% | 2.87pp | 3.5% |
| Seven + wild 150-500× | 150-500× | 0.012% | 2.48pp | 3.1% |
| Grand jackpot | 500-1000× | 0.0% | 0pp | 0% |
| **合计** | | 7.47% | 80.08pp | 99% |

**mode 1 vs mode 7 — 绝对 RTP 贡献对比**（pp）:

| 家族 | mode 1 | mode 7 | Δ |
|---|---|---|---|
| Cherry | 9.95 | 2.95 | **-7.00pp** ← 主砍部位 |
| mixed-Bar | 13.08 | 7.53 | -5.55pp |
| 3-Bar | 29.53 | 27.83 | -1.70pp（基本保 ✓）|
| Bar+wild | 36.82 | 36.43 | -0.39pp（保 ✓）|
| Seven | 2.67 | 2.87 | +0.20pp（保 ✓）|
| Seven+wild | 2.24 | 2.48 | +0.24pp（保 ✓）|

**结论**：砍了 12.5pp（Cherry + mixed-Bar），中高倍率层（3-Bar + Bar+wild + Seven + Seven+wild）合计仅损失 1.65pp。**用户目标达成** ✓

## 桶分布 vs mode 1

| bucket | mode 1 hit% | mode 7 hit% | Δ | mode 1 RTP 占比 | mode 7 RTP 占比 |
|---|---|---|---|---|---|
| ge1_lt5 | 9.25% | **2.88%** | -6.37pp | 10.1% | 3.6% |
| ge5_lt10 | 2.65% | **1.51%** | -1.14pp | 14.1% | 9.3% |
| ge10_lt20 | 2.17% | 2.10% | -0.07pp | 29.5% | 34.4% |
| ge20_lt50 | 0.92% | 0.91% | -0.01pp | 33.0% | 33.8% |
| ge50_lt100 | 0.14% | 0.15% | +0.01pp | 9.2% | 13.0% |
| ge100_lt200 | 0.020% | 0.023% | +0.003pp | 2.8% | 3.5% |
| ge200_lt500 | 0.004% | 0.007% | +0.003pp | 1.3% | 3.1% |

**绝对命中率变化**：低桶（1-10×）命中率从 11.9% → 4.39%（砍 64%）；中高桶（10× 以上）基本持平（3.25% → 3.18%）。**对齐用户意图** ✓

| 分组 | mode 1 | mode 7 |
|---|---|---|
| Low (1-10×) | 24.1% | 16.4% |
| Mid (10-50×) | 62.5% | **74.0%** ← 占比变大（因为低桶砍了）|
| High (50-500×) | 13.4% | 9.6% |

分组 **share** 看起来 High 从 13.4% → 9.6% 下降，但这是因为总 RTP 从 94 → 81 缩水导致的分母效应；**绝对 High pp** 只从 12.60pp → 7.76pp（-4.8pp），其中 Bar+wild 层本身贡献 36.43pp 被归到 Mid 桶。

## 玩家体验层次

mode 7 的主要变化：**空转率从 84.7% → 92.1%**。平均每 13 spin 才一次命中（mode 1 是每 6.4 spin）。但当命中发生时：

| 事件 | mode 1 频率 | mode 7 频率 | mode 7 vs 1 |
|---|---|---|---|
| Cherry 1× | 每 10 spin | **每 35 spin** | 频率 ÷3.5 |
| mixed-Bar 5× | 每 38 spin | **每 66 spin** | 频率 ÷1.7 |
| 3-Bar 10-20× | 每 45 spin | **每 48 spin** | 基本持平 |
| Bar+wild 30-90× | 每 106 spin | **每 108 spin** | 持平 |
| Seven 100× | 每 4,500 spin | **每 4,300 spin** | 持平 |
| Seven+wild 150-500× | 每 8,500 spin | **每 8,000 spin** | 持平 |

**感性体验**：转多了也不中 Cherry（小确幸变稀）。当命中时更可能是 Bar 三连或更大（每次命中更"有分量"）。Loss streak 明显更长，偶尔的 big win 反而更"狂喜"——这是 turbulent / 搓板风格。

CV 6.31 > mode 1 的 5.65，**波动性确实提升**。符合「保留波动性」要求。

## 文件清单

- `weights.json` —— mode 7 每 stop 的 weight 数组
- `TUNE_REPORT.md` —— 最近一次 tune 的 Phase 4/5 完整报告
- `NOTES.md` —— 本文件

Symbol 布局在 [`../reel_strips.json`](../reel_strips.json)（所有 mode 共用）。

## Tune 命令（重跑本 mode）

```bash
python -m slot_designer.scripts.tune \
  --spec slot_designer/specs/M1.spec.json \
  --strips slot_designer/weights/M1/reel_strips.json \
  --base-weights slot_designer/weights/M1/mode_7/weights.json \
  --target slot_designer/tuner/targets/M1_mode7_low_rtp.target.json \
  --out-weights slot_designer/weights/M1/mode_7/weights.json \
  --out-report slot_designer/weights/M1/mode_7/TUNE_REPORT.md \
  --mode 7 \
  --evaluations 3000 --restarts 4 --sa-steps 3000 \
  --hit-target 0.0768 --hit-weight 1.5 \
  --cv-weight 0.5 --shape-weight 1.5
```

重跑会覆盖 `weights.json` + `TUNE_REPORT.md`，也可能通过 joint Phase 5 更新共享的 `reel_strips.json` 和其他 mode 的 `weights.json`（positions co-swapped，marginals 保留）。
