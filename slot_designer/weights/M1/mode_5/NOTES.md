# M1 mode 5 — 当前 reel 权重（超级幸运模式 super-lucky）

**类型**：同 paytable，mode 2 的高阶版本 —— RTP 翻倍到 500%，hit rate 保持
**最近更新**：2026-04-22（v3 structural refactor 后首次 tune）

## 核心数值（analytic）

| 指标 | 本版 | target | vs mode 2 |
|---|---|---|---|
| RTP | 500.01% | 500.00% | +205.5pp（×1.7）|
| hit_rate | 27.51% | 27.60% | 持平（-0.25pp 噪声）|
| 空转率 | 72.49% | 72.40% | — |
| std_return_x | 28.79 | 29.00 | +17.5（×2.4）|
| CV (σ/RTP) | 5.75 | 5.80 | +0.23（略升）|
| shape JS | 0.00821 | 0 | — |

**设计意图**：mode 2 = lucky mode（290% RTP），mode 5 = super-lucky mode（500% RTP）。用户要求「保持 2 的中奖率不变，把倍率分桶分布向高倍率移动，更容易出现机台特征 feature」。mode 5 的 per-hit 平均倍率 ≈ 18×（mode 2 是 10.5×），一个 hit 的期望回报几乎翻倍。

## RTP 贡献分解（按 pay 家族）

| 家族 | 倍率 | hit% | RTP 贡献 | 占 RTP |
|---|---|---|---|---|
| Cherry（1-2×）| 1-2× | 12.83% | 13.23pp | 2.6% |
| mixed-Bar 5× | 5× | 5.09% | 25.45pp | 5.1% |
| 3-Bar 10-20× | 10-20× | 3.71% | 51.09pp | 10.2% |
| Bar + wild 30-90× | 30-90× | 3.82% | 186.5pp | **37.3%** ← 主力爆击层 |
| Seven 100× | 100× | 0.11% | 14.24pp | 2.8% |
| Seven + wild 150-500× | 150-500× | 1.91% | 209.4pp | **41.9%** ← Lucky 核心 |
| Grand jackpot | 500-1000× | 0.005% | 0.09pp | 0.02% |
| **合计** | | 27.51% | 500.01pp | 100% |

**Seven 家族合计 RTP 占比**：2.8% + 41.9% + 0.02% = **44.7%**（比 mode 2 的 31.6% 高 13pp）

## 桶分布 vs mode 2

| bucket | mode 5 hit% | mode 2 hit% | mode 5 RTP 占比 | mode 2 RTP 占比 |
|---|---|---|---|---|
| ge1_lt5 | 12.87% | 14.52% | 2.6% | 5.1% |
| ge5_lt10 | 5.09% | 6.59% | 5.1% | 11.2% |
| ge10_lt20 | 3.64% | 3.84% | 9.6% | 16.8% |
| ge20_lt50 | 2.81% | 1.52% | 9.8% | 16.7% |
| **ge50_lt100** | **1.60%** | 0.77% | **21.3%** | 18.7% |
| **ge100_lt200** | **1.09%** | 0.37% | **29.9%** | 17.7% |
| **ge200_lt500** | **0.40%** | 0.13% | **22.5%** | 13.6% |

**RTP 占比方向性**：Low/Mid 明显缩水，High 三个桶（50-500×）每个都上升 ≥ 3pp。符合「向高倍率移动」要求。

| 分组 | mode 2 | mode 5 | Δ |
|---|---|---|---|
| Low (1-10×) | 16.3% | **7.7%** | -8.6pp |
| Mid (10-50×) | 33.5% | **19.4%** | -14.1pp |
| **High (50-500×)** | 50.0% | **73.7%** | **+23.7pp** ← 主力迁移 |

## 机台特征 feature 频率

用户指定「更容易出现机台特征」。把「50-500× 高倍率命中」当作 feature 事件：

| 指标 | mode 2 | mode 5 |
|---|---|---|
| feature hit rate | 1.27% | **3.09%** |
| feature 间隔 | 每 79 spin | **每 32 spin** |

mode 5 feature 密度是 mode 2 的 **2.4 倍**。加上 Bar+wild 这个 30-90× 的"准 feature"层（hit 3.82% vs mode 2 的 1.94%），总体高-mid 爆点密度 4.9% → 6.9%（每 14 spin 一次显著爆点）。感性体验上每几十转就有一次"被命中"的感觉。

## 玩家体验层次（7 档）

1. Cherry 1×（12.83%）—— 每 8 spin 一次低奖
2. mixed-Bar 5×（5.09%）—— 每 20 spin 一次
3. 3-Bar 10-20×（3.71%）—— 每 27 spin 一次
4. Bar+wild 30-90×（3.82%）—— **每 26 spin 一次爆击** ← mode 5 大幅提升
5. Seven 100×（0.11%）—— 每 900 spin 一次狂喜
6. **Seven+wild 150-500×**（1.91%）—— **每 52 spin 一次大爆** ← 核心 lucky 体验
7. Grand jackpot（0.005%）—— 每 20,000 spin 一次神话

mode 5 的核心差异：**Seven+wild 层从 mode 2 的每 232 spin 缩到 52 spin**（4.5 倍频率）。这是感性上 lucky mode 和 super-lucky mode 的最大区别。

## 文件清单

- `weights.json` —— mode 5 每 stop 的 weight 数组
- `TUNE_REPORT.md` —— 最近一次 tune 的 Phase 4/5 完整报告
- `NOTES.md` —— 本文件

Symbol 布局在 [`../reel_strips.json`](../reel_strips.json)（所有 mode 共用）。

## Tune 命令（重跑本 mode）

```bash
python -m slot_designer.scripts.tune \
  --spec slot_designer/specs/M1.spec.json \
  --strips slot_designer/weights/M1/reel_strips.json \
  --base-weights slot_designer/weights/M1/mode_5/weights.json \
  --target slot_designer/tuner/targets/M1_mode5_super_lucky.target.json \
  --out-weights slot_designer/weights/M1/mode_5/weights.json \
  --out-report slot_designer/weights/M1/mode_5/TUNE_REPORT.md \
  --mode 5 \
  --evaluations 3000 --restarts 4 --sa-steps 3000 \
  --hit-target 0.276 --hit-weight 1.5 \
  --cv-weight 0.5 --shape-weight 1.5
```

重跑会覆盖 `weights.json` + `TUNE_REPORT.md`，也可能通过 joint Phase 5 更新共享的 `reel_strips.json` 和其他 mode 的 `weights.json`（positions co-swapped，marginals 保留）。
