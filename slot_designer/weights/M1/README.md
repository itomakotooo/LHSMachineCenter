# M1 — reel 权重

## 当前状态

| mode | 类型 | RTP | hit_rate | CV | 文件 |
|---|---|---|---|---|---|
| 1 | classic 单线 | 93.48% | 15.29% | 5.06 | [mode_1/weights.json](mode_1/weights.json) |
| 2 | 幸运模式 | 291.29% | 27.76% | 4.10 | [mode_2/weights.json](mode_2/weights.json) |

两个 mode **共享 reel strip 布局**：[reel_strips.json](reel_strips.json)（position→symbol 序列）。每 mode 只提供各自的 weights 数组。

## 文件结构

```
slot_designer/weights/M1/
├── README.md                 ← 本文件
├── reel_strips.json          ← 共享 symbol 布局（36 stops × 3 reels）
├── mode_1/
│   ├── weights.json          ← mode 1 每 stop 的 weight 数组
│   ├── NOTES.md              ← mode 1 数值 + 设计意图 + pay_id 分解
│   └── TUNE_REPORT.md        ← mode 1 最近一次 tune 的报告
└── mode_2/
    └── ...（同结构）
```

## 设计约束

两个 mode **共用 paytable + rules + reel strip 布局**（都从 `slot_designer/specs/M1.spec.json` + `reel_strips.json` 读），**只有每个 stop 的 weight 可以按 mode 变化**。paytable / strips 不能为了 mode 2 改 —— 改了所有 mode 都跟着变。

每 reel 36 stops = 18 Blank + 18 非 Blank，严格交替排列（Blank 和非 Blank 不可相邻）。Phase 5 SA 通过 class-preserving co-swap mutation 保持这个不变量：swap 两个 position 时同时 swap 所有 mode 在那两个 position 的 weight，marginals 保留。

## 重跑 tune

见每个 mode 目录里 `NOTES.md` 末尾的 "Tune 命令" 章节。重跑会：
- 原地覆盖该 mode 的 `weights.json` + `TUNE_REPORT.md`
- 可能更新共享的 `reel_strips.json`（Phase 5 联合 SA 优化）
- 可能更新其他 mode 的 `weights.json`（Phase 5 co-swap 移动了 position，marginals 不变）

历史版本走 git：

```bash
git log --follow -- slot_designer/weights/M1/reel_strips.json
git show <sha>:slot_designer/weights/M1/mode_2/weights.json > /tmp/old_mode2.json
```
