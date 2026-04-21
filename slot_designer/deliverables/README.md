# Reel 权重调参交付

这里是调参完成后给你的 reel 权重交付物。每个机台一个子目录，每次重调放一个 `vN_<tag>/` 子版本。

## 命名约定

```
deliverables/
└── <machine>/
    ├── reel_weights.tsv       ← 最新推荐版（也在最新子版本里有一份）
    ├── reel_weights.json
    ├── DELIVERY_NOTES.md
    └── vN_<tag>/              ← 各版本历史
        ├── reel_weights.tsv
        ├── reel_weights.json
        ├── DELIVERY_NOTES.md
        └── TUNE_REPORT.md     (tune.py 自动生成)
```

顶层的 `reel_weights.{tsv,json}` 是**当前推荐版本**，和最新子版本内容一致。老版本保留在子目录下以便对比 / 回退。

## 版本索引

### M1 (classic 3×3 单线)

| 版本 | RTP | hit_rate | CV | 备注 | 推荐 |
|---|---|---|---|---|---|
| v1 (顶层) | 93.49% | 24.57% | 5.28 | 对齐 M14 mode 1 shape + CV。hit 偏高（"所有 slots 平均"档） | ⚠ |
| **v2_hit15** | 93.48% | **15.29%** | 5.06 | 加 hit 软约束 15%。和 classic 单线行业 typical 对齐 | ✅ |

详情见各版本的 `DELIVERY_NOTES.md`。

**选哪个**：
- 如果你目标是"看起来像 M14"（20%+ hit）→ v1
- 如果你目标是"行业典型 classic 单线"（~15% hit）→ **v2_hit15**（推荐，fleet-wide 更一致）

## 怎么切换到 v2 作为 M1sim 默认

```bash
# 替换 M1sim 虚拟机读的 weights 文件
cp slot_designer/deliverables/M1/v2_hit15/reel_weights.json \
   slot_designer/weights/M1_mode1.tuned.json

# 清空老 rawdata pool
rm -rf slot_designer/rawdata/M1sim

# 重采（v2 权重 + 正确 md5 tag）
python -m slot_designer.scripts.simulate \
  --spec slot_designer/specs/M1.spec.json \
  --weights slot_designer/weights/M1_mode1.tuned.json \
  --out-dir slot_designer/rawdata/M1sim/mode_1 \
  --machine-name M1sim --chunks 110

# 虚拟 console 刷新 → 点 "⟳ 生成 Report" → 看新 report
```

## 调参 pipeline 回顾

每个版本走一次完整 `tune.py` 运行：
1. **Phase 4** (count ES, 1500-2000 evals × 3 restarts)：调 9 symbol × 3 reel 的 count 比例
2. **Phase 5** (order SA, 3000 steps)：在保 count 不变的前提下调 stop 顺序（near-miss / PWDF / blank adjacency）
3. 硬约束：RTP + bucket shape；软约束：CV (+ hit_rate 如果 `--hit-target` 给了)
4. 交付 rawdata chunks 也在 tune.py 内完成（除非 `--skip-rawdata`）

## 研究引用（每次调参前 fresh search）

按 `feedback_always_research_each_time` 规则，每次调参开 session 都重新搜英文行业源。v2_hit15 用的引用见该目录 `DELIVERY_NOTES.md`。
