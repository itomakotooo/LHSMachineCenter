# M1 — reel 权重

## 当前状态（4 个 mode）

| mode | 类型 | RTP | hit_rate | CV | Low / Mid / High (RTP share) | 文件 |
|---|---|---|---|---|---|---|
| 1 | classic 单线 | 94.29% | 15.52% | 5.65 | 24% / 64% / 12% | [mode_1/weights.json](mode_1/weights.json) |
| 2 | 幸运模式 | 294.50% | 27.76% | 5.52 | 16% / 33% / 50% | [mode_2/weights.json](mode_2/weights.json) |
| 5 | 超级幸运模式 | 500.01% | 27.51% | 5.75 | 7% / 19% / **74%** | [mode_5/weights.json](mode_5/weights.json) |
| 7 | 低 RTP turbulent | 80.88% | 7.86% | 6.31 | 16% / 74% / 10% | [mode_7/weights.json](mode_7/weights.json) |

4 个 mode **共享同一张 reel strip** [reel_strips.json](reel_strips.json)（position→symbol 序列，36 × 3 reels，18 Blank + 18 非 Blank 严格交替）。**只有每个 stop 的 weight 按 mode 变化**。

## 家族对应

- **mode 1 ⇄ mode 7**：同 classic 风格，mode 1 正常 RTP（94%）/ mode 7 低 RTP（80%）+ 更高波动
- **mode 2 ⇄ mode 5**：同 lucky 风格，mode 2 高 RTP（290%）/ mode 5 超高 RTP（500%）+ 更密 feature

## 文件结构

```
slot_designer/weights/M1/
├── README.md                 ← 本文件
├── reel_strips.json          ← 共享 symbol 布局（36 stops × 3 reels）
├── mode_1/
│   ├── weights.json          ← 每 stop 的 weight 数组
│   ├── reel_weights.tsv      ← 人类可读 36×3（symbol + weight 并列）
│   ├── NOTES.md              ← 数值 + 设计意图 + pay_id 分解
│   └── TUNE_REPORT.md        ← 最近一次 tune 报告
├── mode_2/                   （同结构）
├── mode_5/                   （同结构）
└── mode_7/                   （同结构）
```

## 设计约束

所有 mode 共用 paytable + rules + reel strip 布局（都从 `slot_designer/specs/M1.spec.json` + `reel_strips.json` 读），**只有每个 stop 的 weight 可以按 mode 变化**。

每 reel 36 stops = 18 Blank + 18 非 Blank，严格交替。Phase 5 joint SA 通过 class-preserving co-swap 保持这个不变量：swap 两个 position 时同时 swap 所有 mode 在那两个 position 的 weight，marginals 保留。

## 重跑 tune

见每个 mode 目录里 `NOTES.md` 末尾的 "Tune 命令" 章节。重跑会：
- 原地覆盖该 mode 的 `weights.json` + `TUNE_REPORT.md`
- 可能更新共享的 `reel_strips.json`（Phase 5 联合 SA 优化）
- 可能更新其他 mode 的 `weights.json`（Phase 5 co-swap 移动了 position，marginals 不变）

## 业界规范参考

| 机台类型 | RTP | 7 家族占 RTP | 参考 |
|---|---|---|---|
| Red White & Blue | 87.47% | 50% | Wizard of Odds appendix 6 |
| Blazing Sevens | 89% | 68.8% | WoO blazing-sevens |
| M1 mode 1（本项目）| 94.29% | 5.2% | —— wild 机制把大量 RTP 留在 Bar+wild 层（39%）|
| M1 mode 2 | 294.50% | 31.6% | lucky mode，wild-amplified Seven 主导 |
| M1 mode 5 | 500.01% | **44.7%** | super-lucky，7 + Seven+wild 是核心 |
| M1 mode 7 | 80.88% | 6.5% | 低 RTP classic，同 mode 1 结构缩 |

历史版本走 git：

```bash
git log --follow -- slot_designer/weights/M1/reel_strips.json
git show <sha>:slot_designer/weights/M1/mode_5/weights.json > /tmp/old_mode5.json
```
