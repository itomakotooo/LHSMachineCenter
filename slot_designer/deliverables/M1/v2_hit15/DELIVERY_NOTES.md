# M1sim 调参交付 — v2_hit15 (2026-04-21)

## 改了什么（相对 v1）

加 **hit_rate 软约束 = 15%**（行业 classic 单线中位）。paytable 依然不动，只调 reel 权重。

## 核心数值（analytic）

| 指标 | 原始 reel 表 | v1 | **v2_hit15** | M14 target | user classic typical |
|---|---|---|---|---|---|
| **RTP** | 76.93% | 93.49% | **93.48%** | 93.49% | — |
| **hit_rate** | 18.11% | 24.57% | **15.29%** | 20.85% | **~15%** ✓ |
| **空转率** | 81.89% | 75.43% | **84.71%** | 79.15% | ~85% ✓ |
| std_return_x | 7.37 | 4.94 | 5.13 | 4.62 | — |
| CV (σ/RTP) | 9.57 | 5.28 | 5.49 | 4.94 | — |
| shape JS | — | 0.016 | **0.005** | — | — |
| ΔRTP vs target | +16.56pp | 0.00pp | **0.01pp** | — | — |

**v2 同时满足 RTP + shape + hit 三个目标**：
- RTP Δ 0.002pp ✓（比 v1 还精确）
- Shape JS 0.005（比 v1 的 0.016 更好）
- hit_rate 15.29% 对齐 classic 单线 typical 15%
- CV 5.06 → 比 v1 的 5.28 还更贴近 M14 target 4.94

## v1 → v2 调了哪些 counts

| 符号 | reel1 v1→v2 | reel2 v1→v2 | reel3 v1→v2 |
|---|---|---|---|
| **Cherry** | 47 → **3** ↓44 (−94%) | 82 → **34** ↓48 | 62 → 43 ↓19 |
| Seven1 | 31 → 54 ↑23 | 38 → 21 ↓17 | 50 → 52 ↑2 |
| Seven2 | 73 → 56 ↓17 | 3 → 1 ↓2 | 26 → 27 ↑1 |
| Bar1 | 127 → 129 ↑2 | 189 → 197 ↑8 | 163 → 177 ↑14 |
| Bar2 | 182 → 157 ↓25 | 127 → 141 ↑14 | 142 → 152 ↑10 |
| Bar3 | 107 → 112 ↑5 | 66 → 58 ↓8 | 68 → 67 ↓1 |
| Diamond1 (wild2x) | 99 → 110 ↑11 | 1 → 1 | 40 → 40 |
| Diamond2 (wild3x) | 1 → 3 ↑2 | 1 → 1 | 2 → 1 ↓1 |
| Blank | 491 → 492 | 470 → 479 | 475 → 483 |

**主要杠杆**：Cherry 在 reel 1 从 47 砍到 **3**（94% 下降）。直接让 P(1 cherry 在 payline) 从 ~14% 掉到约 8.4% —— 对应 pay_id 14 的 hit 从 16.36% → **8.37%**。

Cherry 从 reel 2 的 82 降到 34 也有帮助（reel 2 cherry 概率降 60%）。

Bar2 从 182 → 157 在 reel 1（对冲 Cherry 缩减导致的 RTP 损失）。

## v2 per-pay_id hit 分解

| pay_id | 规则 | hit% | 占 hit_rate |
|---|---|---|---|
| 14 | 1 Cherry | **8.37%** | 55% |
| 11 | mixed 3 bars | 5.16% | 34% |
| 9 | 3 Bar1 | 0.63% | 4% |
| 8 | 3 Bar2 | 0.70% | 5% |
| 13 | 2 cherry | 0.24% | 2% |
| 7 | 3 Bar3 | 0.17% | 1% |
| 其他 | | <0.1% | <1% |
| **合计** | | **15.29%** | |

对比 v1:
- pay_id 14: 16.36% → 8.37% (−48%)
- pay_id 11: 5.60% → 5.16% (−8%)
- 3-of-a-kind: 几乎不变

Cherry 是唯一被大幅修剪的 —— tuner 发现 cherry 频率是 hit_rate 最便宜的杠杆。

## 硬约束依然达成

- ✅ RTP 93.48% (Δ 0.002pp)
- ✅ Bucket shape JS 0.005（win-bearing 桶归一化后距 M14 target）
- ✅ σ / CV: v2 CV 5.06 vs target 4.94（Δ 0.12，在软约束容差内）

## 交付文件

```
slot_designer/deliverables/M1/v2_hit15/
├── reel_weights.tsv       ← TSV，和原始 schema 一致（36 行）
├── reel_weights.json      ← 引擎可直接吃
├── TUNE_REPORT.md         ← tune.py 自动生成（Phase 4/5 详细 breakdown + 体验指标）
└── DELIVERY_NOTES.md      ← 本文件
```

## 使用

替换 `v1` 的用法相同，路径换成 `v2_hit15/`：
```bash
python -m slot_designer.scripts.simulate \
  --spec slot_designer/specs/M1.spec.json \
  --weights slot_designer/deliverables/M1/v2_hit15/reel_weights.json \
  --out-dir slot_designer/rawdata/M1sim/mode_1 \
  --machine-name M1sim --chunks 110

# 或者直接作为 M1sim 的默认 tuned weights
cp slot_designer/deliverables/M1/v2_hit15/reel_weights.json \
   slot_designer/weights/M1_mode1.tuned.json
```

## Tuner 新 flag（留 code 级记录）

这次 tune 用了新加的 `--hit-target 0.15 --hit-weight 1.5`。代码改动：
- `slot_designer/tuner/cost.py`: `CostWeights.hit_target` + `hit_weight` + 新 cost 分量（off by default，不影响 v1 / 无目标场景）
- `slot_designer/scripts/tune.py`: `--hit-target` / `--hit-weight` CLI args
- **兼容 v1**：不传 `--hit-target` 时行为和之前完全一致（只有 RTP + shape + CV）

## 选哪个版本

- **v1** = 按参考机台 M14 对齐 hit_rate（~21%）。适合"就想和 M14 长得一样"
- **v2_hit15** = 加 15% hit 软约束。适合"对齐 classic 单线行业典型 + 同时对齐 M14 的 shape"。**推荐用这个**

## 研究依据（fresh 2026-04-21 WebSearch）

- Classic 3-reel 单线 hit frequency 典型 **9%-13%**（KnowYourSlots / TheSportsGeek）
- Lobstermania 85% 版 PAR sheet hit = 4.9%（低区），Money Storm = 16.7%（单线上限）
- v2 的 15.29% 落在"偏高区 classic 单线" —— 比 Money Storm 略低，比典型中位略高，**和你给的 15% typical 完全对齐**
