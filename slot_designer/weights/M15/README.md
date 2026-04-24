# M15 — reel 权重

机器类型：classic 3-reel 1-payline **带 Feature Play 分支** — IGT Top Dollar 原型。2026-04-24 v6 shipped。

## 机台差异（vs M1）

- **单 wild**：`doublediamond` × 2（M1 有 Diamond1=wild2x + Diamond2=wild3x 两档）
- **Feature 触发器**：`topdollar` 仅在 reel 3 出现（payline 上落位 → emit pay_id 666 marker + 进 Feature Play）
- **Jackpot symbol**：reel 上有但被后端 re-roll 保护（3-jackpot 永不发 1000× 奖，仅作稀释标志）
- **无 mixed-Seven 组合**：M1 pay_id 10 (Seven1+Seven2) 无 M15 对应。high7 拆成 pay_id 2 (wild-boosted) 和 pay_id 21 (pure)
- **Production schema 对齐**：所有 symbol 小写 (`blank/cherry/1bar/2bar/3bar/high7/doublediamond/topdollar/jackpot`)，pay_id 跟生产 `M15$TopDollarSelector$0$` 完全一致

## 当前 shipped 状态（v6 2026-04-24）

| mode | RTP | hit | per-hit avg | trigger | feature EV | split | 文件 |
|---|---|---|---|---|---|---|---|
| 1 | **95.21%** | 13.17% | 3.26× | 1.14% (1/88) | 46× | 45:55 | [mode_1/weights.json](mode_1/weights.json) |
| 2 | **300.84%** | 22.56% | 5.99× | 2.75% (1/36) | 60× | 45:55 | [mode_2/weights.json](mode_2/weights.json) |
| 5 | **499.82%** | 22.56% | 5.99× | 2.76% | 132× | 27:73 | [mode_5/weights.json](mode_5/weights.json) |
| 7 | **84.77%** | 12.46% | 2.62× | 1.14% (1/88) | 46× | 38:62 | [mode_7/weights.json](mode_7/weights.json) |

全部 analytic，闭式解。Target 跨机台 mode RTP 规则：95 / 300 / 500 / 85（见 memory `project_slot_designer_mode_rtp_invariants.md`）。

## 设计契约

- **Total RTP 跨机台锁定**：mode 1=95 / mode 2=300 / mode 5=500 / mode 7=85（`project_slot_designer_mode_rtp_invariants.md`）
- **Strips 跨 mode 字节级一致**：所有 mode 读同一个 `reel_strips.json`，只有 `mode_<N>/weights.json` 的权重数组 per-mode 不同（`project_slot_designer_strips_identical_across_modes.md`）
- **派生 mode hit rate 带宽**（`project_slot_designer_hit_rate_deviation.md`）：
  - mode 7 vs mode 1 hit ±1pp（几乎一致，RTP delta 走 per-hit avg 不走 hit 频率）
  - mode 2 vs mode 1 hit ×1.5-2（不是 ×3.16）
  - mode 5 = mode 2 base 完全复刻
- **Base : Feature split**：M15-specific 45:55（bonus-heavy），mode 1/2 严格执行，mode 5/7 因派生关系漂（27:73 / 38:62）

## 文件结构

```
slot_designer/weights/M15/
├── README.md                 ← 本文件
├── DESIGN.md                 ← Top Dollar 原型研究 + paytable 数学身份
├── MODE_DESIGN.md            ← 4 mode 数值 + 玩家体验剧本（v6 最新）
├── reel_strips.json          ← 共享 symbol 布局（36 × 3, 18 blank + 18 非 blank 交替）
└── mode_<N>/
    └── weights.json          ← mode 专属 per-stop 权重 + feature_params 块
```

mode 1 保留了 `NOTES.md` 和 `TUNE_REPORT.md`（Phase 4/5 初次 tune 产物）；mode 2/5/7 不需要，它们的 derivation 细节都在 `MODE_DESIGN.md` + commit message 里。

## 结构不变量

- **Blank / 非 Blank 严格交替**：每 reel 18 blank + 18 非 blank 交替（环形邻接也算）。0/2/4/… 是 blank，1/3/5/… 是非 blank
- **topdollar 只在 reel 3**：reel 1 / reel 2 无 topdollar stop
- **strips 字节级跨 mode 一致**：改 strip 等于"这是新机台"，老 rawdata 全作废
- **jackpot 在 reel 上但永不 3-match 派奖**：后端 re-roll 保护（纯稀释作用）

Phase 5 joint SA 在 mode 1 初次 tune 时跑了一次保持这些不变量，之后所有 mode 都用 `--sa-steps 0` 锁住 strips。

## 符号 + pay_id 清单

Symbol 每 reel 分布（reel_strips.json）：

| symbol | 类别 | reel 1 | reel 2 | reel 3 |
|---|---|---|---|---|
| blank | filler | 18 | 18 | 18 |
| cherry | cherry_special | 2 | 2 | 2 |
| 1bar | regular | 3 | 3 | 3 |
| 2bar | regular | 4 | 4 | 4 |
| 3bar | regular | 4 | 4 | 3 |
| high7 | regular | 2 | 2 | 2 |
| doublediamond | wild (×2) | 2 | 2 | 1 |
| topdollar | filler / trigger | 0 | 0 | **2** |
| jackpot | filler | 1 | 1 | 1 |

Paytable（从 `specs/M15.spec.json` + 生产 `M15$TopDollarSelector$0$` 校验）：

| pay_id | 组合 | 倍率 | 备注 |
|---|---|---|---|
| 9 | 1 cherry anywhere | 1× | cherry 独立计数，wild 不替代 |
| 71 | 2 cherry anywhere | 5× | 同上 |
| 4 | 3 cherry (payline) | 15× | 同上 |
| 8 | mixed 3 bars (1bar/2bar/3bar 任意) | 2× | wild 可替代并 ×2/wild |
| 7 | 3 1bar | 5× | 可 wild 替代放大 |
| 5 | 3 2bar | 10× | 同上 |
| 3 | 3 3bar | 20× | 同上 |
| 2 | 3 high7 (wild 替代) | 30× | wild ×2/wild boost（60× / 120×） |
| 21 | 3 high7 (pure) | 30× | 无 wild 时独立结算 |
| 1 | 3 doublediamond (pure wild) | 200× | |
| 666 | topdollar on reel 3 payline | 0 | Feature Play trigger marker (line_id=-1 scatter) |

## Feature Play（shipped v5+）

Top Dollar 经典 4-round accept/reject：

- topdollar 落 reel 3 payline → emit pay_id 666（WinCredits=0）+ 进 feature
- 10 张 x 卡池：`(1000, 100, 50, 50, 20, 20, 10, 10, 5, 5)`
- 2 张 y 卡池：`(×2, ×2)`
- 每 round：加权抽 count_x ∈ [1,5] + count_y ∈ [0,2]，然后 weighted-draw **无放回** x_value_weights 和 y_value_weights；R = sum(x) × product(y)
- 3 reroll + 1 forced accept = 最多 4 round
- 测试策略：R ≥ 40 自动 accept
- 接受那 round 的 R × bet 是 session payout，打到 ST=15 端点的 `WinAmount` 字段

Feature params 在 `mode_<N>/weights.json.feature_params` 块里（per-mode override，优先级高于 spec 默认）。4 mode 的 trigger / count_y / x_value_weights 差异见 `MODE_DESIGN.md §2`。

## Rawdata 输出

生成的 chunk 结构严格对齐生产 `M15$TopDollarSelector$0$`:
- ST=1（paid spin）+ ST=14（feature sub-round × N）+ ST=15（feature end marker）sequence
- ST=14 `WinCredits` = 本 round R × bet；`BetAmount=0`
- ST=15 有 `WinAmount`（**不是** `WinCredits`，这个是关键：analyzer Type-1 rule 用 `last_non_none WinCredits` 找 session payout，ST=15 如果有 WinCredits=0 会 override 掉 ST=14）
- ReMarks='Trigger' 打在触发 feature 的 ST=1 spin 上
- analysisResult 是 JSON-encoded string（**不是** dict），包含 per-feature bucket distribution

## 如何重 tune

**mode 1**（独立 archetype，首次 tune）：
```bash
python -m slot_designer.scripts.tune \
    --spec slot_designer/specs/M15.spec.json \
    --strips slot_designer/weights/M15/reel_strips.json \
    --base-weights slot_designer/weights/M15/mode_1/weights.json \
    --target slot_designer/tuner/targets/M15_mode1_classic.target.json \
    --out-weights slot_designer/weights/M15/mode_1/weights.json \
    --mode 1 --evaluations 1500 --restarts 3 --sa-steps 5000
```

**mode 2**（独立 archetype，strips 已固定）：
```bash
python -m slot_designer.scripts.tune ... --sa-steps 0 \
    --target slot_designer/tuner/targets/M15_mode2_lucky.target.json \
    --hit-target 0.225 --hit-weight 1.0 \
    --trigger-target 0.0275 --trigger-symbol topdollar --trigger-reel 3 --trigger-weight 2.0
```

**mode 7**（派生 from mode 1, Phase 4 路径 v6+）：
```bash
python -m slot_designer.scripts.tune ... --sa-steps 0 \
    --target slot_designer/tuner/targets/M15_mode7_standard_low.target.json \
    --hit-target 0.125 --hit-weight 1.5 \
    --trigger-target 0.01136 --trigger-symbol topdollar --trigger-reel 3 --trigger-weight 2.0
```

**mode 5**（派生 from mode 2，copy + swap feature_params）：
```bash
python -m slot_designer.scripts.derive_m15_mode_5 --write --verify
```

Tune 完 mode 2 / mode 7 之后需要手动重新附 `feature_params` 块（tune.py 不碰 feature）— 参考 git log / MODE_DESIGN.md §2 里的 4 mode feature params 定义。

## Verification

```bash
# Feature EV 分析（4 mode 分别）
python -m slot_designer.scripts.verify_m15_modes

# Strips + RTP + hit + trigger 全量回归
python -m pytest slot_designer/tests/test_m15_feature.py \
                 slot_designer/tests/test_strips_identical_across_modes.py -v
```
