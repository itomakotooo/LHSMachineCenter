# M1sim — reel 权重版本 `6edf1ca3`

**调参时间**：2026-04-22（初版 · mode 2 幸运模式）
**状态**：current（M1sim 新增 mode 2，此 md5 是「mode 1 还是 558dfcdd 的调好权重 + mode 2 全新调」的机台整体指纹）
**原因**：用户 spec —— M1 mode 2 = 幸运模式，同 paytable、同规则，仅换 reel 表，拿高 RTP + 高 hit + 合理倍率分桶

## 核心数值（analytic + realized）

| 指标 | target | analytic | realized (1.1M spins) |
|---|---|---|---|
| RTP | 306.0% | 305.81% | **306.12%** |
| hit_rate | 27.5% | 27.30% | — |
| CV (σ/RTP) | 4.90 | 6.04 | — |
| std_return_x | 15.00 | 18.48 | — |
| shape JS (vs target) | — | 0.0192 | — |
| ΔRTP 命中 | — | **-0.19pp** ✓ | **+0.12pp** ✓ |
| Δhit 命中 | — | **-0.20pp** ✓ | — |

## 和 target 的差异（可接受范围）

| bucket | tuned | target | Δ |
|---|---|---|---|
| ge1_lt5（小奖）| 18.26% | 14.00% | **+4.26pp** ← 小奖更多 |
| ge5_lt10 | 3.38% | 6.00% | -2.62pp |
| ge10_lt20 | 2.83% | 4.50% | -1.67pp |
| ge20_lt50 | 1.21% | 2.00% | -0.79pp |
| ge50_lt100 | 0.94% | 0.70% | +0.24pp |
| ge100_lt200 | 0.46% | 0.25% | +0.21pp |
| ge200_lt500 | 0.22% | 0.05% | **+0.17pp** ← 大奖更多 |
| ge500_lt1000 | 0.005% | 0.00% | +0.005pp（3×Diamond1 = 500× 出现了）|

**shape 特征**：比原 target 稍微**更双尾** —— 小奖更多（1-5×），**中段（5-50×）偏少**，大奖（100+×）更多。CV 6.04 > target 4.90 就是这个导致的（方差更大）。RTP 硬约束命中前提下，shape 是软约束，tuner 在可行域里找到这个 pareto 点。

玩家体验直觉：比 target 更"boom-bust"一点 —— 小奖频繁让你不烦躁，时不时突然 100×+ 爆发是"幸运"的高光记忆点。

如果想收回到更平滑的中段，下一步可以：
- `--hit-weight 2.0` 拉更硬的 hit 约束
- `--cv-weight 0.8` 把 CV 的软约束再拉紧（目前默认 0.3）
- 或者直接改 target 里 bucket_rate 接受现在的双尾形状

## Phase 5 experience（order tuning）

| metric | before | after |
|---|---|---|
| 2-of-3 near-miss 总率 | 0.158% | 0.182% |
| avg blank-adjacency to HV | 1.000 | 0.800（降低 = 高值 symbol 周边更多 Blank，视觉上更"突兀"）|

| HV symbol PWDF | before | after |
|---|---|---|
| Diamond1 | 2.92 | 2.68（更 clustered）|
| Diamond2 | 3.95 | 5.76（更 spread）|
| Seven1 | 7.89 | 7.71 |
| Seven2 | 37.34 | 36.95 |

SA 跑了 3000 步，接受 2369、产生 9 次改进。改动不大 —— order space 的空间本来就窄（每 reel 36 stops）。

## 相对 mode 1（558dfcdd）的 symbol count 差异

| 符号 | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| Bar1 | 127 → **184** ↑57 | 189 → **103** ↓86 | 163 → **142** ↓21 |
| Bar2 | 182 → **58** ↓124 | 127 → **149** ↑22 | 142 → **135** ↓7 |
| Bar3 | 107 → **76** ↓31 | 66 → **132** ↑66 | 68 → **134** ↑66 |
| Blank | 491 → **446** ↓45 | 470 → **474** ↑4 | 475 → **444** ↓31 |
| Cherry | 47 → **98** ↑51 | 82 → **47** ↓35 | 62 → **68** ↑6 |
| Diamond1 | 99 → **67** ↓32 | 1 → **25** ↑24 | 40 → **44** ↑4 |
| Diamond2 | 1 → **73** ↑72 | 1 → **142** ↑141 | 2 → **7** ↑5 |
| Seven1 | 31 → **139** ↑108 | 38 → **60** ↑22 | 50 → **6** ↓44 |
| Seven2 | 73 → **1** ↓72 | 3 → **55** ↑52 | 26 → **1** ↓25 |

注意：这是和 mode 1 tuned (558dfcdd) 的对比，反映**两套模式之间权重结构的代价分布差异**（mode 1 RTP 93.5% → mode 2 RTP 306%）。

**结构解读**：
- Diamond2 (wild3x) 在 reel 1 + 2 大幅增加（from ~1 → 73/142）—— 是 RTP 主杠杆
- Diamond1 (wild2x) 在 reel 1 降了一点（让位给 Diamond2）
- Seven2 (50× 3-connect) 被清空（只剩 1/55/1）—— 高 pay 但稀罕，贡献 RTP 不经济
- Cherry 在 reel 1 翻倍（47 → 98）—— 提供 hit rate 底座

## Pay_id 贡献（analytic，前 6 大）

| pay_id | 规则 | tuned hit% |
|---|---|---|
| 14 | 1 Cherry = 1× | **17.13%** ← hit rate 主干 |
| 11 | 混合 3 Bar = 5× | 5.90% |
| 9 | 3 Bar1 = 10× | 1.18% |
| 13 | 2 Cherry = 2× | 1.14% |
| 8 | 3 Bar2 = 15× | 0.79% |
| 7 | 3 Bar3 = 20× | 0.81% |
| 3 | wild 混合 = 240×/360× | 0.079% ← 大奖 |
| 2 | 3 Diamond1 = 500× | 0.0055% ← 极稀大奖 |

hit_rate 合计 27.3%，和 target 27.5% 在 0.2pp 误差内。

## 如何 promote 本版到 active

已经是 active —— `slot_designer/weights/M1_mode2.tuned.json` 就是本版内容。machines_virtual.json 刷新后：
- `configSummaryMd5` = `6edf1ca3ee1ef0ba72925db78a862200`
- `codeSummaryMd5`   = `2746df2d7cda2c04f182169587dd3642`

## 如何回退到 seed 版（若需要）

seed 是 mode 1 的 copy，没必要单独回退。想重跑 tune 直接：
```bash
cp slot_designer/weights/M1_mode1.current.json \
   slot_designer/weights/M1_mode2.current.json
# 然后重跑 tune.py，参见本 NOTES 末尾
```

## Tuner 命令（可复现）

```bash
python -m slot_designer.scripts.tune \
  --spec slot_designer/specs/M1.spec.json \
  --mode 2 \
  --base-weights slot_designer/weights/M1_mode2.current.json \
  --target slot_designer/tuner/targets/M1_mode2_lucky.target.json \
  --out-weights slot_designer/weights/M1_mode2.tuned.json \
  --out-report slot_designer/out/M1_mode2_tune_report.md \
  --hit-target 0.275 --hit-weight 1.5 \
  --evaluations 2000 --restarts 3 --sa-steps 3000 \
  --verbose
```

用时约 2 分钟（主要 Phase 4 count ES）。Phase 5 基本上没找到太多改进空间。

## 开了虚拟 console 怎么验

```bash
start_virtual.bat
# → http://127.0.0.1:8878/console/
```

1. 选 M1sim，mode 2
2. 目标 CI 设 1pp，点"开始采样"
3. virtual_analyzer 从零开始采 mode 2 rawdata，累到 CI 达标
4. 达标后 delegate 产 report → 看 RTP / hit / bucket 是否和本 NOTES 数值吻合（realized 应该 ≈ analytic ± CI）
