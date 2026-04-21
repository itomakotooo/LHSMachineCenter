# M1sim — reel 权重版本 `32251c25`

**调参时间**：2026-04-21（初版）  
**状态**：historical（被 `558dfcdd` 取代）  
**原因**：hit_rate 24.57% 偏高，不符合 classic 单线行业典型（9-13%）

## 核心数值（analytic）

| 指标 | 原始 reel 表 | 本版 `32251c25` | M14 target |
|---|---|---|---|
| RTP | 76.93% | 93.49% | 93.49% |
| std_return_x | 7.37 | 4.94 | 4.94 |
| CV (σ/RTP) | 9.57 | 5.28 | 5.28 |
| hit_rate | 18.11% | **24.57%** | 20.85% |
| 空转率 | 81.89% | 75.43% | 79.15% |
| JS shape | — | 0.016 | — |

## ⚠ 已知差距：hit rate 偏高

- user 反馈 classic 单线 typical 空转率 ≈ 85% (hit rate ≈ 15%)
- 本版空转率 75.43% (hit rate 24.57%)
- 差距约 **-10pp 空转率 / +10pp hit rate**
- 行业数据（2026-04-21 fresh WebSearch）：classic 单线 hit 典型 **9%-13%**，上限 ~17%

→ 产出后续版本 `558dfcdd`（加 hit_rate 软约束）解决这个 gap。

### hit_rate 来源分解

| pay_id | 规则 | hit% | 占 hit_rate |
|---|---|---|---|
| 14 | 1 Cherry | **16.36%** | **67%** |
| 11 | 任意 3 Bar | 5.60% | 23% |
| 13 | 2 Cherry | 1.03% | 4% |
| 9 | 3 Bar1 | 0.76% | 3% |
| 8 | 3 Bar2 | 0.57% | 2% |
| 其他 | | ~0.25% | ~1% |
| **合计** | | **24.57%** | |

主要是 **pay_id 14 (1 Cherry = 1× pay)** 一个规则吃掉 2/3 的 hit_rate —— M1 paytable 的结构性高频小奖特性。

## 硬约束达成

- ✅ RTP 93.49% vs target 93.49%（Δ 0.00pp）
- ✅ Bucket 形状 JS 0.016
- ✅ σ / CV 对齐

## 调参方法论

- **Phase 4**：(1+1)-ES on 27 symbol-count 维度，硬 RTP + shape，软 CV
- **Phase 5**：SA on stop 顺序，保 Phase 4 count 不变，优化 near-miss / blank adjacency / PWDF
- 无 hit_rate 约束（tune.py 不带 `--hit-target`）

## 对原始 reel 表的 count 差异

| 符号 | reel 1 | reel 2 | reel 3 |
|---|---|---|---|
| Bar1 | 110 → 127 ↑17 | 110 → 189 ↑79 | 150 → 163 ↑13 |
| Bar2 | 100 → 182 ↑82 | 100 → 127 ↑27 | 110 → 142 ↑32 |
| Bar3 | 80 → 107 ↑27 | 80 → 66 ↓14 | 90 → 68 ↓22 |
| Blank | 500 → 491 ↓9 | 500 → 470 ↓30 | 500 → 475 ↓25 |
| Cherry | 50 → 47 ↓3 | 50 → 82 ↑32 | 50 → 62 ↑12 |
| Diamond1 (wild2x) | 10 → 99 ↑89 | 10 → 1 ↓9 | 10 → 40 ↑30 |
| Diamond2 (wild3x) | 20 → 1 ↓19 | 20 → 1 ↓19 | 10 → 2 ↓8 |
| Seven1 | 90 → 31 ↓59 | 90 → 38 ↓52 | 40 → 50 ↑10 |
| Seven2 | 50 → 73 ↑23 | 50 → 3 ↓47 | 50 → 26 ↓24 |
| reel 总权重 | 1010 → 1158 | 1010 → 977 | 1010 → 1028 |

特点：
- Diamond1 reel 1 涨到 99（wild2x 大幅提频）—— 补 RTP 的主杠杆
- Seven1 / Seven2 / Diamond2 在 reel 2 几乎清零（weight=1-3）—— 让 reel 2 变成"死 reel"，高价值 3-连击极罕见

## 如何回退到本版（若需要）

```bash
# 1. promote 本版 weights 成 active
cp slot_designer/deliverables/M1/32251c25/reel_weights.json \
   slot_designer/weights/M1_mode1.tuned.json

# 2. 虚拟 console 下次 refresh-md5（启动 / 手动）自动刷新 machines_virtual.json
#    的 configSummaryMd5，console 就知道机台版本换了

# 3. console 那边的 rawdata：让 operator 走 batch-run 重采即可
#    （旧 md5 的 chunks 自动标 historical，不会和新 chunks 混分析；
#    要彻底清可用 console UI 的 per-version DELETE 按钮）

# —— 以上是 release 路径。如果只是想 dev 自己 eyeball 本版的数值： ——

# dev-scratch 验证（数据不进 console，纯给我自己看）
python -m slot_designer.scripts.simulate \
  --spec slot_designer/specs/M1.spec.json \
  --weights slot_designer/weights/M1_mode1.tuned.json \
  --machine-name M1sim --chunks 110
# → 写到 slot_designer/_dev_scratch/rawdata/M1sim/mode_1/
#   每次跑自动 wipe 同路径下的旧 chunk_*.json，无需 rm -rf
```

## Tuner 命令（可复现）

```bash
python -m slot_designer.scripts.tune \
  --spec slot_designer/specs/M1.spec.json \
  --base-weights slot_designer/weights/M1_mode1.current.json \
  --target slot_designer/tuner/targets/M14_mode1.target.json \
  --out-weights slot_designer/weights/M1_mode1.tuned.json \
  --evaluations 1500 --restarts 3 --sa-steps 3000
# 不带 --hit-target，hit_rate 自由浮动
```
