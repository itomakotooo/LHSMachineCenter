# M1 mode 7 — 当前 reel 权重（低 RTP / 适度波动 turbulent）

**类型**：同 paytable，mode 1 的低 RTP 版本 —— 适度砍中奖率与低倍率 win，保留中高倍率与波动性
**最近更新**：2026-04-22 v2（hit rate 从 7.86% 放宽到 ~10%）

## 核心数值（analytic）

| 指标 | 本版 | target | vs mode 1 |
|---|---|---|---|
| RTP | 82.69% | 82.65% | -11.6pp |
| hit_rate | 9.93% | 9.68% | -5.59pp（约 -36%）|
| 空转率 | 90.07% | 90.32% | +5.59pp |
| std_return_x | 4.92 | 4.90 | -0.21 |
| CV (σ/RTP) | 5.94 | 5.93 | +0.29 |
| shape JS | 0.00449 | 0 | — |

**设计意图**：mode 7 = 低 RTP 版 classic —— 用户 brief v2: **hit rate 大约降到 10%**（v1 砍到 7.86% 太过）。实现思路：

- **砍 Cherry**（1×）从 9.70% → 4.94% 命中率（每 20 spin 一次 cherry，mode 1 是每 10 spin）
- **砍 mixed-Bar 5×** 从 2.62% → 1.89%
- **保 3-Bar 10-20×** 从 2.23% → 2.14%（持平）
- **保 Bar+wild 30-90×** 从 0.94% → 0.95%（持平）
- **Seven 家族** 被 tuner pareto 到「Seven+wild 保，Seven 100× 拆」的状态（见下）

## RTP 贡献分解（按 pay 家族）

| 家族 | 倍率 | hit% | RTP 贡献 | 占 RTP |
|---|---|---|---|---|
| Cherry（1-2×）| 1-2× | 4.94% | 5.01pp | 6.1% |
| mixed-Bar 5× | 5× | 1.89% | 9.44pp | 11.4% |
| 3-Bar 10-20× | 10-20× | 2.14% | 29.45pp | 35.6% |
| Bar + wild 30-90× | 30-90× | 0.95% | 36.24pp | **43.8%** ← 主要 RTP 来源 |
| Seven 100× | 100× | 0.002% | 0.23pp | 0.3% |
| Seven + wild 150-500× | 150-500× | 0.014% | 2.29pp | 2.8% |
| Grand jackpot | 500-1000× | 0.0% | 0.02pp | 0% |
| **合计** | | 9.94% | 82.68pp | 100% |

## 与 mode 1 对比（绝对 RTP pp）

| 家族 | mode 1 | mode 7 | Δ | 备注 |
|---|---|---|---|---|
| Cherry | 9.95 | 5.01 | **-4.94pp** | ← 主砍部位（减半）|
| mixed-Bar | 13.08 | 9.44 | -3.64pp | 小幅砍 |
| 3-Bar 10-20× | 29.53 | 29.45 | -0.08pp | **持平 ✓** |
| Bar+wild | 36.82 | 36.24 | -0.58pp | **持平 ✓** |
| Seven 100× | 2.67 | 0.23 | -2.44pp | ⚠ tuner pareto 取向 |
| Seven+wild | 2.24 | 2.29 | +0.05pp | **持平 ✓** |
| Grand | 0 | 0.02 | — | — |

**说明「Seven 100× 被拆」**：tuner 在 shape_weight 1.5 下找到的 pareto 点把 pure Seven1 命中率压到接近 0（仍保留 Seven1 的 wild 替换路径 Seven+wild = 150-500×）。本质是「Seven1 symbol 在 reel 上出现得极少，但当它与 Diamond wild 搭档时还能触发大奖」。效果上 Seven+wild 层（感性爆点主力）完整保留，纯 100× Seven 层退化到 <1 in 50,000 频率。

如果要强制保 Seven 100× = 2.67pp，需要提 `--shape-weight` 到 3+ 或改 target 把 ge100_lt200 目标值拉到 0.0005 而不是 0.00025。当前状态对玩家感性体验足够（Seven+wild 的 150-500× 爆点是更强的记忆点）。

## 桶分布（bucket_rate，analytic）

| bucket | mode 1 hit% | mode 7 hit% | Δ |
|---|---|---|---|
| ge1_lt5 | 9.25% | **4.83%** | -4.42pp ← cherry 减半 |
| ge5_lt10 | 2.65% | **1.89%** | -0.76pp |
| ge10_lt20 | 2.17% | 2.10% | -0.07pp（持平 ✓）|
| ge20_lt50 | 0.92% | 0.99% | +0.07pp（持平 ✓）|
| ge50_lt100 | 0.14% | 0.126% | -0.01pp（持平 ✓）|
| ge100_lt200 | 0.020% | 0.018% | -0.002pp |
| ge200_lt500 | 0.004% | 0.004% | 持平 ✓ |

| 分组 | mode 1 | mode 7 |
|---|---|---|
| Low (1-10×) | 24.1% | 17.5% |
| Mid (10-50×) | 62.5% | **72.6%** ← 占比变大（低桶砍了）|
| High (50-500×) | 13.4% | 9.9% |

绝对 Mid pp 几乎 100% 保留（64.47pp → 65.69pp），High pp 从 12.60 → 8.18pp（~65% 保留）。

## 玩家体验层次

**空转率**：mode 1 的 84.7% → mode 7 的 90.1%。平均每 10 spin 一次命中（mode 1 是每 6.4 spin，v1 mode 7 是每 13 spin）。v2 的 hit rate 回到"适度 grindy"而不是"惩罚式"。

| 事件 | mode 1 频率 | mode 7 v1 | **mode 7 v2 本版** |
|---|---|---|---|
| Cherry 1× | 每 10 spin | 每 35 spin | **每 20 spin** ← 放宽 |
| mixed-Bar 5× | 每 38 spin | 每 66 spin | **每 53 spin** |
| 3-Bar 10-20× | 每 45 spin | 每 48 spin | **每 47 spin** ← 持平 |
| Bar+wild 30-90× | 每 106 spin | 每 108 spin | **每 106 spin** ← 持平 |
| Seven 100× | 每 4,500 spin | 每 4,300 spin | 每 56,000 spin ⚠ |
| Seven+wild 150-500× | 每 8,500 spin | 每 8,000 spin | **每 7,100 spin** ← 持平 |

**感性体验**：base spin 比 mode 1 多 ~55% 的空转，但 Cherry 还是会定期出现；中高倍率爆点（Bar 三连 / Bar+wild / Seven+wild）频率与 mode 1 基本一致。**这是"低 RTP 但仍有 signature big-win 节奏"的 turbulent 风格**。

CV 5.94 > mode 1 的 5.65，波动性提升但不极端（v1 的 6.31 那个版本已回调）。

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
  --hit-target 0.0968 --hit-weight 1.5 \
  --cv-weight 0.5 --shape-weight 1.5
```

重跑会覆盖 `weights.json` + `TUNE_REPORT.md`，也可能通过 joint Phase 5 更新共享的 `reel_strips.json` 和其他 mode 的 `weights.json`（positions co-swapped，marginals 保留）。

## Hit rate 调整历史

- **v1**（2026-04-22 上午）：target hit 7.68%，实际 7.86%，CV 6.31 —— 砍得太狠，用户反馈"砍半太过分"
- **v2（本版）**：target hit 9.68%，实际 9.93%，CV 5.94 —— 用户 brief「砍到 10% 差不多」对齐
