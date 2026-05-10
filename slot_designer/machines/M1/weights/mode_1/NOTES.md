# M1 mode 1 — 当前 reel 权重（classic，wild-augmented）

**类型**：classic 单线 3-reel，wild 替换机制加持
**最近更新**：2026-04-22 v3 (7-dominant 目标 + wild-amplified mid 层)

## 核心数值（analytic）

| 指标 | 本版 | target | 业界 classic 基准（RWB 87% RTP）|
|---|---|---|---|
| RTP | 94.29% | 94.30% | 87.47% |
| hit_rate | 15.52% | 15.20% | ~20% |
| 空转率 | 84.48% | 84.80% | ~80% |
| std_return_x | 5.33 | 5.30 | — |
| CV (σ/RTP) | 5.65 | 5.62 | — |
| ΔRTP | -0.01pp | — | — |

**设计意图**：Red White & Blue / Blazing Sevens 式 classic 分布研究后（见 commit `e37bc01` 后的 research agent 报告），尝试把 7 家族当 RTP 主驱动。M1 带 **wild 替换机制**（Diamond1 = wild2x, Diamond2 = wild3x）会把 Bar 3-of-kind 放大到 30-90× 落在 mid-high 桶，形成一个 **Bar+wild 层**介于 3-Bar 和 Seven 之间 —— 这是 M1 相对 classic RWB 结构上的额外层次，RTP 贡献会被它"偷走"。

## RTP 贡献分解（按 pay 家族分组）

| 家族 | 倍率范围 | 命中率 | RTP 贡献 | 占 RTP |
|---|---|---|---|---|
| Cherry（1-2×）| 1-2× | 9.70% | 9.95pp | **10.5%** |
| mixed-Bar 5× | 5× | 2.62% | 13.08pp | 13.9% |
| 3-Bar 10-20× | 10-20× | 2.23% | 29.53pp | **31.3%** |
| Bar + wild 30-90× | 30-90× | 0.94% | 36.82pp | **39.1%** ← M1 特色层 |
| Seven 100× | 100× | 0.022% | 2.67pp | 2.8% |
| Seven + wild 150-500× | 150-500× | 0.012% | 2.24pp | 2.4% |
| Grand jackpot (rtp_excluded) | 500-1000× | 0 | 0 | 0 |
| **合计** | | 15.52% | 94.29pp | 100% |

**和 classic RWB 对比**：

| 家族 | M1 mode 1 | RWB 87.47% |
|---|---|---|
| Low (Cherry)  | 10.5% | 16% |
| Mid (Bar 3-of-kind + mixed) | 31.3% + 13.9% = 45.2% | 31% (仅纯 Bar) |
| Bar + wild (M1 独有) | 39.1% | 0%（RWB 无 wild）|
| Seven family | 5.2% | 50% |

**核心差异**：M1 的 **wild 机制把 39% RTP 固定给了 Bar+wild 层**（30-90× 放大 pay），这是 RWB 没有的中间层。剩给 Seven 家族的空间就只剩 ~5%。如果要达到 RWB 的 50% Seven 占比，必须大幅降低 Diamond1/Diamond2 出现频率（会牺牲 wild-amplify 的中段爽点）或者改 paytable。当前版本保留 wild 层，接受 7 占比较低。

## 桶分布（bucket_rate，analytic）

| bucket | 命中率 | RTP 贡献 | 占 RTP |
|---|---|---|---|
| ge1_lt5 | 9.25% | 9.50pp | 10% |
| ge5_lt10 | 2.65% | 13.25pp | 14% |
| ge10_lt20 | 2.17% | 27.81pp | 29% |
| ge20_lt50 | 0.92% | 31.14pp | 33% ← mid-high 主力（wild 放大 Bar）|
| ge50_lt100 | 0.14% | 8.71pp | 9% ← wild 双放大 |
| ge100_lt200 | 0.020% | 2.68pp | 3% ← Seven1 100× |
| ge200_lt500 | 0.004% | 1.22pp | 1% ← Seven2 + wild mix |
| ge500+ | ~0% | ~0pp | 0% (rtp_excluded) |

**分布形态**：Low 24% / Mid 63% / High 12%。不是 RWB-classic 的 16/31/50 —— wild 机制把 mid 层做厚了。

## 玩家体验层次（6 档）

M1 mode 1 给玩家 **6 档反馈节奏**（比 classic 4 档更丰富）：

1. **Cherry 1×**（9.7% hit，10% payback）—— 高频、微小反馈，每 ~10 spin 一次
2. **mixed-Bar 5×**（2.6% hit，14% payback）—— 每 ~38 spin 一次
3. **3-Bar 10-20×**（2.2% hit，31% payback）—— 每 ~45 spin 一次
4. **Bar+wild 30-90×**（0.94% hit，39% payback）—— 每 ~106 spin 一次爆点 ← M1 独有
5. **Seven 100×**（0.022% hit，3% payback）—— 每 ~4,500 spin 一次大奖
6. **Seven+wild 150-500×**（0.012% hit，2% payback）—— 每 ~8,500 spin 一次狂喜

Bar+wild 层本质上是 M1 "迷你 Seven" 的角色 —— 用 wild 放大中等命中制造"爆击"感，填补 RWB 缺失的中间层次。玩家体验上反而比 RWB-pure 更连续（RWB 有个 "20× Bar 到 80× Seven" 的空洞，M1 用 30-90× wild 层填满了）。

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
  --base-weights slot_designer/machines/M1/weights/mode_1/weights.json \
  --target slot_designer/tuner/targets/M1_mode1_classic.target.json \
  --out-weights slot_designer/machines/M1/weights/mode_1/weights.json \
  --out-report slot_designer/weights/M1/mode_1/TUNE_REPORT.md \
  --mode 1 \
  --evaluations 3000 --restarts 4 --sa-steps 3000 \
  --hit-target 0.15 --hit-weight 0.8 \
  --cv-weight 0.3 --shape-weight 3.0
```

重跑会覆盖 `weights.json` + `TUNE_REPORT.md`，也可能更新共享的 `reel_strips.json` 和 mode 2 的 `weights.json`（Phase 5 联合 SA co-swap）。想保留旧版本走 git。
