# Reel 权重

按机台 / mode 分层：

```
slot_designer/weights/
├── README.md            ← 本文件
└── <MACHINE>/
    ├── README.md        ← 机台概览（所有 mode 当前数值）
    └── mode_<N>/
        ├── reel_weights.json     ← 引擎 / 虚拟 console 读这个
        ├── reel_weights.tsv      ← 人类可读 36×3 表格
        ├── NOTES.md              ← 数值 + 设计意图 + pay_id 分解
        └── TUNE_REPORT.md        ← 最近一次 tune 的 Phase 4/5 报告
```

**每个 mode 只有一份数据**。重跑 tune 原地覆盖，历史走 git。

## 已注册机台

- [M1/](M1/) —— classic 单线 3-reel，mode 1（typical 15%）+ mode 2（幸运模式 290% RTP）

## 新机台 onboarding

1. `slot_designer/specs/<MACHINE>.spec.json` 写入 paytable + rules
2. `slot_designer/weights/<MACHINE>/mode_<N>/reel_weights.json` 手工初始 reel 表（每个 mode 一份）
3. `slot_designer/configs/machines_virtual.json` 注册机台 + modes + spec 路径
4. 跑 tune（见各 mode `NOTES.md` 末尾的命令）

`configSummaryMd5` 自动从 spec + 所有 mode 的 `reel_weights.json` 算出，mode 级 md5 只哈希本 mode 的 weights（改 mode 2 不会 invalidate mode 1 的 rawdata chunk）。
