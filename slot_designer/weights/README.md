# Reel 权重

按机台 / mode 分层；**所有 mode 共用一个 symbol 布局**，只有每个 stop 的 weight 可以按 mode 变化。

```
slot_designer/weights/
├── README.md                      ← 本文件
└── <MACHINE>/
    ├── README.md                  ← 机台概览（所有 mode 当前数值）
    ├── reel_strips.json           ← 共享 symbol 布局（每 reel 的 position→symbol 序列）
    └── mode_<N>/
        ├── weights.json           ← 每 stop 的 weight 数组（mode 专属）
        ├── NOTES.md               ← 本 mode 的数值 + 设计意图 + pay_id 分解
        └── TUNE_REPORT.md         ← 最近一次 tune 的 Phase 4/5 报告
```

## 文件职责

- **`reel_strips.json`** —— 机台级共享，定义每 reel 有多少 stop 以及每个 stop 放哪个 symbol
- **`mode_<N>/weights.json`** —— mode 专属，定义每个 position 的 weight（为此 mode 调出的 per-stop 权重）

引擎加载时把两者合并成内存中的 `[(symbol, weight), ...]` 列表。

## 核心不变量

1. **Symbol 布局跨 mode 一致** —— `position → symbol` 映射由 `reel_strips.json` 唯一决定，物理上不可能写错（所有 mode 读同一个文件）
2. **每个 mode 只有一份 weight 数据** —— 每 mode 一个 `weights.json`；重跑 tune 原地覆盖，历史走 git
3. **Blank / 非 Blank 严格交替** —— 每 reel 36 stops = 18 Blank + 18 非 Blank，交替排列（Phase 5 SA 通过 `initialize_alternating` + class-preserving swap 保持这个不变量）

## 已注册机台

- [M1/](M1/) —— classic 单线 3-reel，mode 1（classic typical 15%）+ mode 2（幸运模式 290% RTP）

## 新机台 onboarding

1. `slot_designer/specs/<MACHINE>.spec.json` 写入 paytable + rules
2. `slot_designer/weights/<MACHINE>/reel_strips.json` 手工写入初始 symbol 布局（每 reel 一个 symbol 序列）
3. `slot_designer/weights/<MACHINE>/mode_<N>/weights.json` 每 mode 写一份初始 weight 数组
4. `slot_designer/configs/machines_virtual.json` 注册机台 + modes + `_spec_path` + `_strips_path` + `_weights_path_template`
5. 跑 tune（见每 mode 的 `NOTES.md` 末尾命令）

`configSummaryMd5` 由 `spec + strips + 所有 mode 的 weights` 一起算出；mode 级 md5 只哈希 `spec + strips + 本 mode 的 weights`。改 mode 2 的 weights 不会 invalidate mode 1 的 rawdata chunk。**改 strips 会 invalidate 所有 mode 的 chunks**（因为 strip 是机台级的），这是设计意图。
