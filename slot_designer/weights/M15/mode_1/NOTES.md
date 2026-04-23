# M15 mode 1 — 当前 reel 权重（initial scaffold）

**状态**：Phase 1 onboarding scaffold，**未 tune**。引擎加载正常，analytic 产生相干数字；下一步跑 Phase 4 tune 对齐 classic target。

**最近更新**：2026-04-23（M15 首次 scaffold）

## 核心数值（analytic, pre-tune）

| 指标 | 本版 | target (未定义) | 备注 |
|---|---|---|---|
| RTP | 41.38% | ~93% classic target | tune 需加 +50pp |
| hit_rate | 21.88% | ~10-15% classic 单线 | 偏高，Cherry 太多 |
| CV | 4.24 | ~5-6 classic | OK |
| std_return_x | 1.75 | — | low |

初始 per-reel marginals（估算）:

| symbol | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| Blank | 53.7% | 53.7% | 53.8% |
| Cherry | 6.0% | 6.0% | 6.0% |
| Bar1 | 13.9% | 13.9% | 14.0% |
| Bar2 | 11.9% | 11.9% | 12.0% |
| Bar3 | 11.1% | 11.1% | 8.4% ← 少一个 stop |
| High7 | 2.4% | 2.4% | 2.4% |
| Wild | 1.0% | 1.0% | 0.5% ← 少一个 stop |
| Bonus | — | — | 3.0% ← 只 reel 3 |

## RTP 贡献分解（按 pay 家族）

| 家族 | 倍率 | hit% | RTP 贡献 | 占 RTP |
|---|---|---|---|---|
| Cherry（1-2-3×）| 1,5,15× | 16.86% | 20.87pp | 50.4% ← 主导 |
| mixed-Bar 2× | 2× | 4.15% | 8.29pp | 20.0% |
| 3-Bar 5-20× | 5,10,20× | 0.55% | 7.65pp | 18.5% |
| Bar + wild (20-80×) | 20-80× | 0.09% | 3.15pp | 7.6% |
| High7 (30×+ wild amped) | 30-120× | 0.003% | ~0.5pp | 1.2% |
| 3 Wild (pure) | 200× | 0.0001% | ~0.02pp | 0.05% |
| Jackpot (rtp_excluded) | 1000× | 0% | 0 | 0% |

## Bucket 分布（pre-tune，远未达 classic 7-heavy）

```
Low (1-10×):    29.5pp   (71% of RTP)
Mid (10-50×):   10.5pp   (25% of RTP)
High (50-500×):  0.4pp   (<1% of RTP)
```

Classic 规范（参考 RWB + Blazing Sevens）：
- Low 16% / Mid 31% / High 50% (7 家族 dominant)

要让 M15 mode 1 对齐 classic，tune 需要：
- 降 Cherry marginal（cut 低桶）
- 提 High7 + Wild marginal（push 高桶）
- 保持 hit rate 在 10-15% 区间

但因为 M15 wild 只有 ×2（M1 有 wild3x 和叠加），wild-amplified Bar 层比 M1 弱，high-bucket 更依赖纯 High7 或 pure-wild。

## Feature Play（未实现）

**Phase 1 spec** 把 Bonus 标 `filler` —— Bonus 在 reel 3 payline 出现时短路到「no pay」。实际 paytable 要求 Bonus 触发独立 Feature 玩法：

- Bonus 在 reel 3 middle row 出现 → 进 feature
- 10 x 选项 × 2 y 选项 的加权抽样 + 接受/reroll 逻辑
- Feature RTP **单独统计** 不并入主 RTP
- 需要新的 spin_type + RNG 流 + 报告面板

**Phase 2 work items**（阻塞 M15 交付）：
1. 加 feature engine（新 spin type = 2 可能？）
2. 从策划处拿 x/y 权重分布（paytable 未说明）
3. 策划定 Feature RTP 目标
4. 报告加 Feature 分析面板

当前分析跑不了 Feature Play —— 只跑主游戏。

## 文件清单

- `weights.json` —— mode 1 per-stop weight 数组
- `reel_weights.tsv` —— 人类可读 36×3（symbol + weight 并列）
- `NOTES.md` —— 本文件
- `TUNE_REPORT.md` —— 尚未生成（还没跑 tune）

Symbol 布局在 [`../reel_strips.json`](../reel_strips.json)（所有 mode 共用）。

## Tune 命令（待执行）

先写 target 文件，再跑：

```bash
# 1. 写 target（classic 7-heavy 规范，RTP 93% / hit 12% / CV 5.5）
# 详见 slot_designer/tuner/targets/M1_mode1_classic.target.json 做参考

# 2. Phase 4 + joint Phase 5 tune
python -m slot_designer.scripts.tune \
  --spec slot_designer/specs/M15.spec.json \
  --strips slot_designer/weights/M15/reel_strips.json \
  --base-weights slot_designer/weights/M15/mode_1/weights.json \
  --target slot_designer/tuner/targets/M15_mode1_classic.target.json \
  --out-weights slot_designer/weights/M15/mode_1/weights.json \
  --out-report slot_designer/weights/M15/mode_1/TUNE_REPORT.md \
  --mode 1 \
  --evaluations 3000 --restarts 4 --sa-steps 3000 \
  --hit-target 0.12 --hit-weight 1.5 \
  --cv-weight 0.5 --shape-weight 2.0
```
