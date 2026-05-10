# M15 v7 baseline — 6-item quickref

> **本文件是 v7 历史 weights 状态的 6-item 速查**，对应 user brief 的 6 条诉求。
> **Stage 1b 完整 baseline 必须远超此范围**（见 ONBOARDING_PROCESS.md §5.1b 12-section spec）。
> 本文件作 optimization 起点参考，**不是 Stage 1b 的 final deliverable**。

| # | 诉求 | mode 1 | mode 2 | mode 5 | mode 7 | 备注 |
|---|---|---|---|---|---|---|
| RTP | total | 94.98% | 294.28% | 490.32% | 85.09% | 95/300/500/85 universal |
| RTP | base | 43.15pp | 132.76pp | 132.76pp | 33.24pp | mode 5 base = mode 2 base ✓ |
| RTP | feature | 51.83pp | 161.52pp | 357.56pp | 51.85pp | |
| RTP | base:feature | 45.4 : 54.6 | 45.1 : 54.9 | 27.1 : 72.9 | 39.1 : 60.9 | brief #3 期望 50:50 — mode 1 偏 feature 4.6pp |
| 1 | hit rate | **19.31%** | 29.35% | 29.35% | 14.92% | brief #1 期望 mode 1 ∈ [15,18] — 超 1.31pp |
| 2a | base CV | 5.77 | 5.14 | 5.14 | 7.07 | brief #2 期望"低 (3-5)" — 全 mode 偏高 |
| 2b | feature CV | 0.74 | 0.78 | 0.86 | 0.74 | brief #2 期望"中 (1-2)" — 全 mode 偏低 |
| | trigger | 1/89 | 1/37 | 1/37 | 1/89 | mode 7 = mode 1 ✓ |
| | feature EV | 46.0× | 60.0× | 132.8× | 46.0× | mode 5 super-buff (132/60 = 2.21×) |
| 4 | P(count_x=1) | 5.0% | 5.0% | 5.0% | 5.0% | brief #4 期望低 — 5% 已经低，可压到 ≤2% |
| 5 | P(R≥1000/spin) | 1/8.3M | 1/385k | 1/3.6M | 1/8.3M | brief #5 期望避免 — ✓ 已基本达成 |
| 6 | jackpot R1 marg | 0.08% | 0.35% | 0.35% | 0.40% | brief #6 期望偏低 — ✓ |
| 6 | jackpot R2 marg | 0.53% | 0.74% | 0.74% | 0.52% | |
| 6 | jackpot R3 marg | 0.14% | 0.48% | 0.48% | 0.08% | |

## 距离 brief 的 gaps（mode 1）

```
hit               19.31  →  16.5  (-2.81pp)    cherry-1 anywhere 主导，cherry density 砍 ~15% 可达
base CV           5.77   →  ~4    (-1.77)       小奖更密 + 顶奖更稀
feature CV        0.74   →  ~1.5  (+0.76)       x_value_weights 拉宽分布 (现在过度集中 5/10)
base:feature      45:55  →  50:50               feature trigger 砍 ~9% 或 EV 降 ~9%
P(count_x=1)      5.0%   →  ≤2%   (-3pp)        count_x weights[0] 5→1 或 0
```

## 记 file checksum (v7 weights)

```
machines/M15/spec.json                       (paytable 结构，本次 redesign 不动)
machines/M15/reel_strips.json                (36 stops × 3 reels，可能 redesign)
machines/M15/weights/mode_1/weights.json     (v7 baseline)
machines/M15/weights/mode_2/weights.json     (v7 baseline)
machines/M15/weights/mode_5/weights.json     (v7 baseline)
machines/M15/weights/mode_7/weights.json     (v7 baseline)
machines/M15/plugins/{__init__,plugin,feature}.py  (FeaturePlugin Protocol，本次 redesign 不动)
```

## 注意

- 这是 6-item 简表，**不是** Stage 1b 完整 baseline
- 完整 baseline 必含 12 sections（见 ONBOARDING_PROCESS.md §5.1b）：
  RTP+hit+CV / per-pay_id freq+rtp / family share / per-reel marginals /
  bucket distribution / 跨 mode invariants / reel asymmetry §12 /
  PWDF §15 / blank-flank §13 / feature session bucket / top-prize §7 /
  schema fingerprint vs production
- 新 session Agent A 必须跑完整版 Stage 1b 落到 `01b_baseline_report.md`，
  不能只拿本简表
