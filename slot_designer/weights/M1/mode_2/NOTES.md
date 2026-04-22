# M1 mode 2 — 当前 reel 权重（幸运模式）

**类型**：同 mode 1 paytable，换 reel 表 → 高 RTP / 高 hit 的「幸运模式」
**最近更新**：2026-04-22

## 核心数值（analytic / engine 实测 100k spins）

| 指标 | analytic | realized 100k | target | 说明 |
|---|---|---|---|---|
| RTP | 290.94% | **291.49%** | 291.00% | 硬约束 ✓ |
| hit_rate | 27.78% | **27.66%** | 26.10% (band 25-30%) | 软约束 ✓ |
| CV (σ/RTP) | 4.08 | — | 3.13 | -55% vs 调前 baseline 9.16 |
| std_return_x | 11.88 | — | 9.10 | — |
| shape JS | 0.007 | — | 0 | 近似完美 shape 对齐 |
| max observed | 500 (500×) | 360 | 500 | — |

**设计意图**：RTP 贡献中心落在**中倍率段 (10-50×)**，不要集中在高倍率尾部 —— 玩家体验频繁中奖，不是偶尔爆发。

## RTP 贡献分布（engine 实测 100k spins）

| bucket group | 贡献 pp | 占 RTP |
|---|---|---|
| Low (1-10×) | 51.98 | 17.8% |
| **Mid (10-50×)** | **130.11** | **44.6%** ← 中心 |
| High (50-500×) | 109.41 | 37.5% |
| Very high (500+) | 0.00 | 0.0% |

| bucket | rate% | RTP pp | avg mult |
|---|---|---|---|
| ge1_lt5 | 11.21 | 11.53 | 1.03 |
| ge5_lt10 | 8.09 | 40.45 | 5.00 |
| ge10_lt20 | 4.92 | 60.88 | 12.36 |
| ge20_lt50 | 2.21 | 69.23 | 31.31 |
| ge50_lt100 | 0.92 | 64.91 | 70.24 |
| ge100_lt200 | 0.30 | 41.38 | 137.93 |
| ge200_lt500 | 0.01 | 3.12 | 312.00 |
| ge500_lt1000 | 0.00 | 0.00 | — |

## per-pay_id hit 分解（analytic）

| pay_id | 规则 | hit% | 占 hit_rate |
|---|---|---|---|
| 11 | mixed 3 Bar = 5× | 12.40% | 45% |
| 14 | 1 Cherry = 1× | 10.95% | 39% |
| 9 | 3 Bar1 = 10× | 1.55% | 6% |
| 8 | 3 Bar2 = 15× | 1.42% | 5% |
| 7 | 3 Bar3 = 20× | 1.10% | 4% |
| 13 | 2 Cherry = 2× | 0.34% | 1% |
| 10 | 3 Seven1 = 100× | 0.003% | — |
| 其他（wild combos 大奖）| 2/3/5/6 | <0.1% each | <1% |
| **合计** | | **27.78%** | — |

**主力**：pay_id 11（混合 3 Bar = 5×）占 45%，落在 ge5_lt10 桶；14（Cherry）占 39%，落在 ge1_lt5。中倍率桶的 RTP 贡献主要由 pay_id 7/8/9（三连 Bar 10-20×）撑起。

## 结构不变性

**Blank / 非 Blank 严格交替** —— 每 reel 36 stops = 18 Blank + 18 非 Blank；任何两个相邻 stop 必须一 Blank 一非 Blank（环形邻接，最后一个和第一个也算相邻）。Phase 5 SA 通过 `initialize_alternating` + `class_preserving_swap_mutation` 从起始状态到每一步都保持这个不变性。回归由 `test_alternation_invariant.py` 监控。

## 文件清单

- `reel_weights.json` —— 引擎 / 虚拟 console 读这个
- `reel_weights.tsv` —— 同内容的人类可读格式（36 stops × 3 reels）
- `TUNE_REPORT.md` —— 最近一次 tune 的 Phase 4/5 完整报告
- `NOTES.md` —— 本文件

## Tune 命令（重跑本 mode）

```bash
python -m slot_designer.scripts.tune \
  --spec slot_designer/specs/M1.spec.json \
  --mode 2 \
  --base-weights slot_designer/weights/M1/mode_2/reel_weights.json \
  --target slot_designer/tuner/targets/M1_mode2_lucky.target.json \
  --out-weights slot_designer/weights/M1/mode_2/reel_weights.json \
  --out-report slot_designer/weights/M1/mode_2/TUNE_REPORT.md \
  --hit-target 0.26 --hit-weight 1.5 \
  --cv-weight 1.0 --shape-weight 2.0 \
  --evaluations 3000 --restarts 4 --sa-steps 5000
```

重跑会覆盖 `reel_weights.json` + `TUNE_REPORT.md`。想保留旧版本走 git。
