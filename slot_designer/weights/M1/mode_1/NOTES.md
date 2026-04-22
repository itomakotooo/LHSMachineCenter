# M1 mode 1 — 当前 reel 权重

**类型**：classic 单线 3-reel
**最近更新**：2026-04-21

## 核心数值（analytic）

| 指标 | 本版 | M14 mode 1 reference | classic 单线 typical |
|---|---|---|---|
| RTP | 93.48% | 93.49% | — |
| hit_rate | **15.29%** | 20.85% | 9-13% |
| 空转率 | 84.71% | 79.15% | ~85% |
| std_return_x | 5.13 | 4.62 | — |
| CV (σ/RTP) | 5.49 | 4.94 | — |
| shape JS | 0.005 | — | — |
| ΔRTP | 0.01pp | — | — |

**设计意图**：对齐 M14 mode 1 的 shape + CV，hit_rate 软约束 15% 锚在 classic 单线行业区间（参考 KnowYourSlots / The Sports Geek：单线典型 9-13%）。

## per-pay_id hit 分解

| pay_id | 规则 | hit% | 占 hit_rate |
|---|---|---|---|
| 14 | 1 Cherry = 1× | 8.37% | 55% |
| 11 | mixed 3 Bar = 5× | 5.16% | 34% |
| 8 | 3 Bar2 = 15× | 0.70% | 5% |
| 9 | 3 Bar1 = 10× | 0.63% | 4% |
| 13 | 2 Cherry = 2× | 0.24% | 2% |
| 7 | 3 Bar3 = 20× | 0.17% | 1% |
| 其他（大奖）| Diamond/Seven combos | <0.1% each | <1% |
| **合计** | | **15.29%** | — |

**主力**：pay_id 14（Cherry = 1×）贡献 55% 的 hit。Cherry 频率压低（尤其 reel 1 = 3）以让 hit 降到 15%，RTP 靠 Bar2 + wild3x (Diamond2) 补回。

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
  --base-weights slot_designer/weights/M1/mode_1/reel_weights.json \
  --target slot_designer/tuner/targets/M14_mode1.target.json \
  --out-weights slot_designer/weights/M1/mode_1/reel_weights.json \
  --out-report slot_designer/weights/M1/mode_1/TUNE_REPORT.md \
  --evaluations 2000 --restarts 3 --sa-steps 3000 \
  --hit-target 0.15 --hit-weight 1.5
```

重跑会覆盖 `reel_weights.json` + `TUNE_REPORT.md`。想保留旧版本走 git（`git log --follow` / `git show`）。
