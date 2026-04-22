# M1sim — reel 权重版本 `e4017d61`

**调参时间**：2026-04-22 晚（v2 · mode 2 幸运模式 · **RTP 分布中心下移**）
**状态**：current（替代 `6edf1ca3`；mode 1 仍由 `558dfcdd` 提供，此 md5 是整机指纹）
**原因**：user 反馈 v1 (6edf1ca3) 的 **RTP 贡献占比** 集中在高倍率桶（50-500×），波动性过大。重新分配到中倍率（10-50×）为分布中心。

## v1 → v2 调整动机（user 原话复盘）

> 「分布形状是 **rtp 占比**，不是击中率。你算出来的分桶，rtp 占比主要分布在高倍率段，这个会导致波动性过大。」

v1 分析：63% 的 RTP 由 50-500× 桶贡献 → 典型 tail-heavy lucky mode（类似 classic 单线），中段几乎断层。CV 6.04 对应「偶尔大奖决定整体体验」。

v2 目标：把 RTP 贡献中心移到 10-50× 中段，让玩家感受到的是**频繁的中倍率命中**而不是稀罕的大爆发。

## 核心数值（analytic + realized）

| 指标 | baseline (6edf1ca3) | v2 target | v2 tuned (analytic) | v2 realized (1.1M spins) |
|---|---|---|---|---|
| RTP % | 76.932 \* | 291.00 | **290.94** | **290.72** |
| hit_rate | 0.181 \* | 0.261 (25-30% user spec) | **0.2778** ✓ | — |
| CV (σ/RTP) | 9.157 \* | 3.127 | **4.083** | — |
| std_return_x | 7.045 \* | 9.10 | 11.88 | — |
| shape JS | — | 0 | **0.00703** | — |
| ΔRTP 命中 | — | — | **-0.058pp** ✓ | **-0.28pp** ✓ |

\*注：baseline 数值取 tune 的 Phase 3 起始点（mode 2 current seed = mode 1 copy），不是 v1 (6edf1ca3) 的 tuned 结果。v1 tuned = RTP 305.81% / hit 27.30% / CV 6.04。

## RTP 贡献占比（核心对比）

| bucket group | v1 (6edf1ca3) | v2 target | v2 actual |
|---|---|---|---|
| Low (1-10×) | 20.3% | 24.9% | **26.3%** |
| **Mid (10-50×)** | **22.5%** | **59.2%** | **41.3%** ← 中心显著上移 |
| High (50-500×) | 57.1% | 16.0% | **32.4%** ← 比 v1 接近腰斩 |
| Very high (500+) | 1.1% | 0.0% | 0.0% |

结论：
- **中段 RTP 贡献 22.5% → 41.3%**（接近翻倍），高段 57% → 32%（砍掉一半）
- 没完全打到 target 的 59% / 16% —— 主要在 50-100× 和 100-200× 两个桶超调（50-100× 实际 0.91% vs target 0.50%；100-200× 实际 0.30% vs target 0.05%）
- 可行域限制 + CV 软约束（权重 1.0，是 default 0.3 的 3.3x）能找到的 pareto 点；继续压 high 段需要改 paytable 或把 shape_weight 再拉到 3+ 试，但会牺牲 hit / RTP 硬度

## 每桶 RTP 贡献（pp）

| bucket | v1 actual | v2 target | v2 actual |
|---|---|---|---|
| ge1_lt5 | 0.46 | 0.28 | 0.28 |
| ge5_lt10 | 0.25 | 0.45 | 0.61 |
| **ge10_lt20** | 0.42 | **0.82** | **0.75** ← mid 中心一 |
| **ge20_lt50** | 0.36 | **0.90** | **0.65** ← mid 中心二 |
| ge50_lt100 | 0.66 | 0.35 | 0.64 |
| ge100_lt200 | 0.64 | 0.07 | 0.43 |
| ge200_lt500 | 0.66 | 0.04 | 0.03 |
| ge500_lt1000 | 0.04 | 0.00 | 0.00 |

## 桶命中率（%）

| bucket | tuned | target | reachable |
|---|---|---|---|
| ge1_lt5 | 11.29 | 11.00 | ✓ |
| ge5_lt10 | 8.12 | 6.00 | ✓ |
| ge10_lt20 | 4.97 | 5.50 | ✓ |
| ge20_lt50 | 2.18 | 3.00 | ✓ |
| ge50_lt100 | 0.91 | 0.50 | ✓ |
| ge100_lt200 | 0.30 | 0.05 | ✓ |
| ge200_lt500 | 0.0096 | 0.015 | ✓ |

## CV 分析

- v1 CV 6.04 → v2 CV 4.08（-33%）
- 未达 target 3.13 —— 剩余方差主要来自 50-200× 两桶的超调（tail 仍然偏胖）
- 玩家体验：std_return_x 从 v1 的 18.48 → 11.88（-36%），平均下来单 spin 的波动尺度显著压缩。单个 boom-bust 极值从 500× 天花板降到约 140× 实际 p99（200-500× 频率 0.01%，1.1M spins 预计 100 次左右）

## Count changes（vs. v1 tuned）

v2 相对 mode 1 seed 的 reel 权重变化（Phase 4 结束）：

| 符号 | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| Bar1 | 110→213 ↑103 | 110→88 ↓22 | 150→202 ↑52 |
| Bar2 | 100→147 ↑47 | 100→237 ↑137 | 110→118 ↑8 |
| Bar3 | 80→159 ↑79 | 80→143 ↑63 | 90→109 ↑19 |
| Blank | 500→328 ↓172 | 500→443 ↓57 | 500→408 ↓92 |
| Cherry | 50→68 ↑18 | 50→34 ↓16 | 50→14 ↓36 |
| Diamond1 | 10→1 ↓9 | 10→67 ↑57 | 10→102 ↑92 |
| **Diamond2** | 20→1 ↓19 | **20→62 ↑42** | 10→81 ↑71 |
| Seven1 | 90→1 ↓89 | 90→27 ↓63 | 40→62 ↑22 |
| Seven2 | 50→1 ↓49 | 50→45 ↓5 | 50→1 ↓49 |

**结构解读**：
- Diamond2（wild3x）在 reel 2 从 v1 的 142 压到 62 —— 直接砍 wild3x 3-of-kind 的触发率，是 50-500× 尾部的主源，压 tail 的核心杠杆
- Bar1/Bar2/Bar3 全线大幅上调 —— 3-of-kind 组合概率拉升，填中段 10-50× 倍率桶
- Blank 在三个 reel 都大幅下调 —— 释放权重给中段 paying symbols
- Seven 系列被压低 —— Seven2 在 reel 1/3 只剩 1，避免稀罕高 pay 贡献 tail

## Pay_id 命中率 & 贡献对比

| pay_id | 规则 | v1 (baseline*) | v2 tuned | Δ |
|---|---|---|---|---|
| 11 | 混合 3 Bar = 5× | 3.02% | **12.40%** | +9.38pp ← 中倍率主力 |
| 14 | 1 Cherry = 1× | 13.42% | 10.95% | -2.47pp |
| 9 | 3 Bar1 = 10× | 0.32% | 1.55% | +1.23pp ← 中倍率 |
| 8 | 3 Bar2 = 15× | 0.21% | 1.42% | +1.21pp ← 中倍率 |
| 7 | 3 Bar3 = 20× | 0.13% | 1.10% | +0.97pp ← 中倍率 |
| 13 | 2 Cherry = 2× | 0.70% | 0.34% | -0.36pp |
| 10 | 3 Seven1 = 100× | 0.18% | 0.003% | -0.18pp |
| 5/6 | Seven/Diamond = 300×/500× | 0.12% | 0.01% | -0.11pp ← tail 压缩 |

\*此处 baseline 是 tune 自己 Phase 3 报的 baseline（seed=current weights），和 v1 active 的 tuned 数值不完全相同，但趋势一致。

**pay_id 11 占 12.4%** —— 混合 Bar 三连是 5× 倍率，完美落在 ge5_lt10 桶，成为新中倍率主干。配合 Bar1/2/3 三连（pay 7/8/9，10-20× 倍率），mid 桶被 3-Bar 家族撑起来。

## Phase 5 — order optimization

| metric | before | after |
|---|---|---|
| 2-of-3 near-miss 总率 | 0.063% | 0.117% |
| avg blank-adj to HV | 1.000 | 0.800 |

| HV symbol PWDF | before | after |
|---|---|---|
| Diamond1 | 18.897 | **40.688** ← 更 spread |
| Diamond2 | 14.821 | 27.697 |
| Seven1 | 16.009 | 13.975 |
| Seven2 | 30.733 | 31.333 |

SA 5000 步，接受 3954、改进 28 次。Diamond1 PWDF 大幅上升 —— 把 Diamond1 在 reel 里分散开，视觉上每个 Diamond1 看着都更稀罕；near-miss 总率上升到 0.117%（v1 是 0.182%，变低了，因为 Seven 基数减小）。

## 如何 promote 本版到 active

已经是 active —— `slot_designer/weights/M1_mode2.tuned.json` 就是本版内容。refresh-md5 之后：
- 整机 `configSummaryMd5` = `5738a990b749feb0a46fcf2824329e7e`（受 mode 1 + mode 2 同时影响）
- per-mode `modes["2"].configSummaryMd5` = `e4017d6150ccc5c0f08af78e11d80a73`
- `codeSummaryMd5` = `2746df2d7cda2c04f182169587dd3642`

目录名取 **mode 2 per-mode md5** 的短 8 位：`e4017d61`。这样同机台不同 mode 的调参归档互不混淆（此前整机 md5 的做法会在 mode 1 调 / mode 2 调时相互 invalidate 历史记录）。

## 如何回退到 v1（若需要）

```bash
cp slot_designer/deliverables/M1/6edf1ca3/reel_weights.json \
   slot_designer/weights/M1_mode2.tuned.json
```

然后虚拟 console refresh-md5 → 新 md5 会指回 `6edf1ca3`（整机口径）；mode 2 per-mode md5 会指回原来的值。

## Tuner 命令（可复现）

```bash
python -m slot_designer.scripts.tune \
  --spec slot_designer/specs/M1.spec.json \
  --mode 2 \
  --base-weights slot_designer/weights/M1_mode2.current.json \
  --target slot_designer/tuner/targets/M1_mode2_lucky.target.json \
  --out-weights slot_designer/weights/M1_mode2.tuned.json \
  --out-report slot_designer/out/M1_mode2_tune_report.md \
  --hit-target 0.26 --hit-weight 1.5 \
  --cv-weight 1.0 --shape-weight 2.0 \
  --evaluations 3000 --restarts 4 --sa-steps 5000 \
  --verbose
```

关键参数改动 vs v1：
- `--cv-weight 1.0`（default 0.3 的 3.3x）—— 强制压低波动
- `--shape-weight 2.0`（default 1.0 的 2x）—— 更硬的桶分布约束
- `--evaluations 3000 --restarts 4 --sa-steps 5000`（v1 是 2000/3/3000）—— 多跑，找更优 pareto 点
- target file 重写：`ge1_lt5 0.11`（原 0.14）/ `ge10_lt20 0.055`（原 0.045）/ `ge20_lt50 0.03`（原 0.02）/ `ge50_lt100 0.005`（原 0.007）/ `ge100_lt200 0.0005`（原 0.0025）/ `ge200_lt500 0.00015`（原 0.0005）

耗时约 6 分钟（Phase 4 主导）。

## 开了虚拟 console 怎么验

```bash
start_virtual.bat
# → http://127.0.0.1:8878/console/
```

1. 选 M1sim，mode 2
2. 目标 CI 设 1pp，点「开始采样」
3. virtual_analyzer 从零开始采 mode 2 rawdata（旧 `6edf1ca3` 的 chunks 会标 historical）
4. 达标后 delegate 产 report → 看 RTP / hit / bucket 是否和本 NOTES 数值吻合

预期观测（1.1M spins 级别）：
- realized RTP ≈ 290.7% ± 0.5pp
- realized hit ≈ 27.8% ± 0.3pp
- bucket 分布与 tuned 列对齐（CI 1pp 下各桶都在容差内）
