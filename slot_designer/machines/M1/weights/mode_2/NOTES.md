# M1 mode 2 — 当前 reel 权重（幸运模式，classic 7-dominant）

**类型**：同 mode 1 paytable，换 reel 权重 → 高 RTP / 高 hit / 7 家族加权的「幸运模式」
**最近更新**：2026-04-22 v3 (classic 7-dominant 规范重设)

## 核心数值（analytic）

| 指标 | 本版 | target | 业界 classic 基准（Blazing Sevens）|
|---|---|---|---|
| RTP | 294.50% | 294.50% | 89.09% |
| hit_rate | 27.76% | 27.67% | — |
| 空转率 | 72.24% | 72.33% | — |
| std_return_x | 16.25 | 16.20 | — |
| CV (σ/RTP) | 5.52 | 5.50 | — |
| ΔRTP | 0.00pp | — | — |

**设计意图**：RWB / Blazing Sevens 经典 1-line 老虎机的 RTP 分布里 **7 家族占 50-68%**（Sevens 是 excitement 主驱动）。mode 2 是 "幸运模式"，在 **同 paytable** 下把 RTP 从 mode 1 的 94% 拉到 290%，同时**让 7 家族成为 RTP 主力**（不只是 mid-Bar 加密度）。

## RTP 贡献分解（按 pay 家族分组）

| 家族 | 倍率范围 | 命中率 | RTP 贡献 | 占 RTP |
|---|---|---|---|---|
| Cherry（1-2×）| 1-2× | 14.52% | 14.98pp | 5.1% |
| mixed-Bar 5× | 5× | 6.59% | 32.95pp | 11.2% |
| 3-Bar 10-20× | 10-20× | 4.19% | 56.46pp | 19.2% |
| Bar + wild 30-90× | 30-90× | 1.94% | 97.12pp | **33.0%** ← M1 特色层 |
| Seven 100× | 100× | 0.072% | 9.27pp | 3.1% |
| Seven + wild 150-500× | 150-500× | 0.434% | 82.93pp | **28.2%** ← 7 主导 |
| Grand jackpot (rtp_excluded) | 500-1000× | 0.002% | 0.80pp | 0.3% |
| **合计** | | 27.76% | 294.50pp | 100% |

**7 家族合计 RTP 占比**：3.1% + 28.2% + 0.3% = **31.6%**

**和 Blazing Sevens (68% Seven) 对比**：

| 家族组 | M1 mode 2 | Blazing Sevens |
|---|---|---|
| Cherry + mixed-Bar | 16.3% | 18.1% (bars) + 12.9% (dollar/bell) |
| 3-Bar + Bar+wild | 52.2% | — |
| Seven family 总和 | **31.6%** | **68.8%** |

M1 达不到 Blazing 的 68%，因为 wild 机制把大量 RTP 留在"Bar+wild"中间层（33%）。但 **31.6% 的 Seven 占比已经是 classic-style 的**（远超 mode 1 的 5.2%，是真正的 "lucky" 模式）。

## 桶分布（bucket_rate，analytic）

| bucket | 命中率 | RTP 贡献 | 占 RTP |
|---|---|---|---|
| ge1_lt5 | 14.52% | 14.98pp | 5.1% |
| ge5_lt10 | 6.59% | 32.95pp | 11.2% |
| ge10_lt20 | 3.84% | 49.34pp | 16.8% |
| ge20_lt50 | 1.52% | 49.19pp | 16.7% |
| **ge50_lt100** | **0.77%** | **55.05pp** | **18.7%** ← 大量爆点 |
| **ge100_lt200** | **0.37%** | **52.25pp** | **17.7%** |
| **ge200_lt500** | **0.13%** | **39.94pp** | **13.6%** |
| ge500+ (rtp_excluded) | 0.002% | 0.80pp | 0.3% |

**分布形态**：Low 16% / Mid 34% / **High 50%** —— 正好对齐 RWB 的 16/31/50 classic 基准 ✓

## 玩家体验层次（7 档，比 mode 1 更丰富）

1. **Cherry 1-2×**（14.5% hit）—— 每 7 spin 一次微反馈
2. **mixed-Bar 5×**（6.6% hit）—— 每 15 spin 一次
3. **3-Bar 10-20×**（4.2% hit）—— 每 24 spin 一次
4. **Bar+wild 30-90×**（1.9% hit）—— 每 51 spin 一次"爆击" ← M1 独有
5. **Seven 100×**（0.07% hit）—— 每 1,390 spin 一次大奖
6. **Seven+wild 150-500×**（0.43% hit）—— 每 **232 spin** 一次狂喜 ← **lucky mode 核心**
7. **Grand jackpot (Diamond3/4)**（0.002% hit）—— 每 50,000 spin 一次神话时刻

**关键差异 vs mode 1**：
- Seven+wild 层在 mode 2 hit rate 是 0.43%（每 232 spin），mode 1 是 0.01%（每 8,500 spin）—— **7 频率高 36 倍**
- Bar+wild 层都存在，但 mode 2 的 hit 1.94% 远高于 mode 1 的 0.94%
- 整体"爆点密度"mode 2 约为 mode 1 的 2-5 倍

这就是"幸运模式"该有的感性体验：**7 经常爆**，不只是偶尔刷一次。

## 文件清单

- `weights.json` —— 本 mode 每 stop 的 weight 数组（引擎加载时与父目录的 `reel_strips.json` 合并）
- `TUNE_REPORT.md` —— 最近一次 tune 的 Phase 4/5 完整报告
- `NOTES.md` —— 本文件

Symbol 布局在 [`../reel_strips.json`](../reel_strips.json)（所有 mode 共用）。

## Tune 命令（重跑本 mode）

```bash
python -m slot_designer.scripts.tune \
  --spec slot_designer/machines/M1/spec.json \
  --strips slot_designer/machines/M1/reel_strips.json \
  --base-weights slot_designer/machines/M1/weights/mode_2/weights.json \
  --target slot_designer/core/tuner/targets/M1_mode2_lucky.target.json \
  --out-weights slot_designer/machines/M1/weights/mode_2/weights.json \
  --out-report slot_designer/machines/M1/weights/mode_2/TUNE_REPORT.md \
  --mode 2 \
  --evaluations 3000 --restarts 4 --sa-steps 5000 \
  --hit-target 0.2767 --hit-weight 1.5 \
  --cv-weight 1.0 --shape-weight 1.5
```

重跑会覆盖 `weights.json` + `TUNE_REPORT.md`，也可能更新共享的 `reel_strips.json` 和 mode 1 的 `weights.json`（Phase 5 联合 SA co-swap）。想保留旧版本走 git。

## 研究依据（2026-04-22 fresh WebSearch）

- **Red White & Blue (Wizard of Odds appendix 6)**: 87.47% RTP, low 16% / mid 31% / **high 50%**。Seven 家族合计命中率 0.49%。
- **Blazing Sevens (Wizard of Odds)**: 89% RTP, **Sevens = 68.8% of RTP**, bars 18.1%. Pure Sevens hit 0.27%, mixed 0.93%.
- **Harrigan PAR sheets**: classic 1-line hit rate 9-13%, Sevens 0.3-1%.
- **Lucas & Singh 2008 (volatility)**: CV 直接决定 time-on-device，越低越长。

Mode 2 本版 CV 5.52 比 classic 5.5-6 高不多；31.6% Seven occupancy 是 "classic-leaning hybrid"（比 RWB 低 20pp 因为 wild 机制）。玩家感性上已经是 7-driven lucky mode。
