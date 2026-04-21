# M1sim 调参交付 — v1 (2026-04-21)

## 什么

M1 机台（classic 3×3 单线）的 reel 权重表调参产出。目标 = 对齐 M14 mode 1 的数值画像（RTP + bucket 分布形状）。

## 交付文件

| 文件 | 用途 |
|---|---|
| `reel_weights.tsv` | TSV 格式，和你最初给的 reel 表同 schema，方便肉眼比对 / 贴回设计文档 |
| `reel_weights.json` | 引擎可直接吃的 JSON（`slot_designer` 模块 + 虚拟 console 的 M1sim 都读这个） |
| `DELIVERY_NOTES.md` | 本文件 |

## 核心数值（analytic，非采样）

| 指标 | 原始 reel 表 | **tuned** | M14 target | gap vs target |
|---|---|---|---|---|
| **RTP** | 76.93% | **93.49%** | 93.49% | **0.00pp** ✓ |
| **std_return_x** | 7.37 | **4.94** | 4.94 | 0.00 ✓ |
| **CV (σ/RTP)** | 9.57 | **5.28** | 5.28 | 0.00 ✓ |
| hit_rate | 18.11% | 24.57% | 20.85% | +3.7pp (soft, 非目标) |
| 空转率 | 81.89% | **75.43%** | 79.15% | -3.7pp |

## ⚠ 已知差距：hit rate 偏高

实测到的**关键 gap**：

- **你反馈的 classic 单线 typical 空转率 ≈ 85%** (hit rate ≈ 15%)
- **当前交付的 M1sim 空转率 75.43%** (hit rate 24.57%)
- **差距约 -10pp 空转率 / +10pp hit rate**

行业数据验证（2026-04-21 fresh WebSearch）：
- Classic 3-reel 单线 hit frequency 典型 **9%-13%**（KnowYourSlots）
- Lobstermania PAR sheet 实测 4.9% hit（85% payback 版），Money Storm 16.7%（单线上限）
- 你的 15% typical 落在行业 classic 单线中位

**当前交付的 24.57% hit 属于"所有 slots 平均 20-25%" 档（多 payline 范围）**，对 classic 单线偏高。

### 来源分解（analytic）

| pay_id | 规则 | hit% | 占 hit_rate |
|---|---|---|---|
| 14 | 1 Cherry | **16.36%** | **67%** |
| 11 | 任意 3 Bar | 5.60% | 23% |
| 13 | 2 Cherry | 1.03% | 4% |
| 9 | 3 Bar1 | 0.76% | 3% |
| 8 | 3 Bar2 | 0.57% | 2% |
| 其他 | | ~0.25% | ~1% |
| **合计** | | **24.57%** | |

主要是 **pay_id 14 (1 Cherry = 1× pay)** 一个规则吃掉 2/3 的 hit_rate。这是 M1 paytable 本身的结构 —— cherry 被设计成高频 1-2× 小奖。

Paytable 不能改（前提约束），能动的只有 reel 权重。要降到 15% hit rate 有三条路（见下文）。

## 硬约束达成情况

- ✅ **RTP**：93.49% vs target 93.49%，Δ 0.00pp（精确命中）
- ✅ **Bucket 形状**：JS-divergence 0.016 vs target（win-bearing 桶归一化后）
- ✅ **σ / CV**：一致（因 CV 软约束也很紧）

## Bucket 分布

| 桶 | 当前交付 (%) | M14 target (%) | 差距 |
|---|---|---|---|
| gt0_lt1 | 0 | 9.92 | 结构性不可达（M1 paytable 无 sub-1× pay） |
| ge1_lt5 | ~16 | 6.47 | 当前偏多（cherry 1× 吃掉） |
| ge5_lt10 | ~5 | 1.67 | 偏多（mixed-bar 5× 密集） |
| ge10_lt20 | ~2 | 1.71 | 接近 |
| ge20_lt50 | ~0.9 | 0.92 | 精确 |
| ge50_lt100 | ~0.2 | 0.16 | 接近 |
| ≥100x tail | ~0.06 | ~0.01 | 偏厚（wild 乘数叠加） |

## 调参方法论（供参考）

- **Phase 4 — count tuner**：(1+1)-ES on 27-dim (9 symbol × 3 reel 的 count)。硬约束 RTP + shape，软约束 CV
- **Phase 5 — order tuner**：保持 count 不变，SA 调 stop 顺序。研究驱动的 near-miss / blank-adjacency / PWDF 体验指标
- **策划文档依据**：你给的原始 reel 表是 reference，我 tune 后和它的差别记录在下面"count 差异"表

## count 差异（原始 → tuned）

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
| **reel 总权重** | **1010 → 1158** | **1010 → 977** | **1010 → 1028** |

几个值得注意的趋势：
- **Seven1 / Seven2 / Diamond2 在 reel 2 几乎被清零**（weight=1-3） — tuner 让 reel 2 成为"死 reel"，高价值 3-连击需要极运气
- **Diamond1 在 reel 1 涨到 99**（wild2x 大幅提频） — 补上 RTP 的关键杠杆
- **Bar1 / Bar2 几乎全涨** — 低倍率 3-of-a-kind 和 mixed-bar 的基础

## 三条降 hit_rate 到 15% 的路径（paytable 不改）

### A. 降 Cherry 权重 + 重调
- Cherry 权重从 50/reel 降到 15-20 → P(1 cherry payline) 降到 4-5%
- hit_rate 掉到约 13-15%
- 副作用：Cherry 贡献的 16.3pp RTP 没了，tuner 要把它分配到 Bar/Seven/wild → bucket shape 右移（ge1_lt5 减，ge5_lt20 增）

### B. Tuner 加 hit_rate 软约束（推荐）
- cost function 加 `weight × (hit - 0.15)²` 项
- Tuner 自己权衡 RTP + shape + CV + hit
- 重新跑 M1sim，得到新 tuned
- 同时适用于所有未来机台

### C. 换参考机台
- M14 mode 1 hit_rate 20.85% 对 classic 单线来说偏高
- 如果 fleet 里有真·15% hit classic，切换 target 后 tuner 自动往那个方向走

## 交付版本

`reel_weights.tsv/json` 当前内容对应 **Phase 4/5 tune 后的 Pareto 点**（RTP+CV 严格，hit 未约束）。如果你选路径 B/C 重调，后续版本会在这个目录下加 `v2_*` / `v3_*` 子目录。

## 如何使用

```bash
# 1. 虚拟 console 读取（port 8878）— 已自动
start_virtual.bat
# → http://127.0.0.1:8878/console/ 选 M1sim

# 2. 命令行模拟 + emit rawdata
python -m slot_designer.scripts.simulate \
  --spec slot_designer/specs/M1.spec.json \
  --weights slot_designer/deliverables/M1/reel_weights.json \
  --out-dir <某目录> \
  --machine-name M1sim \
  --chunks 110

# 3. 用现有 analyzer 消费 rawdata
python fresh_slotlab/player_impact_analyzer.py \
  --machine M1sim --rtp-mode 1 \
  --from-cache <上面那个目录> \
  --output-dir <report 目录> \
  --target-halfwidth-pp 0.001 --max-chunks 9999
```

## 研究依据（2026-04-21 重搜）

按 feedback_always_research_each_time 规则，每次都 re-search，不依赖记忆笔记：

- **Hit frequency 范围** [KnowYourSlots](https://www.knowyourslots.com/slot-machine-math-hit-frequency/) / [thesportsgeek](https://www.thesportsgeek.com/blog/do-you-know-how-frequently-online-slot-machines-pay/): classic 3-reel 10-30%，**单线窄到 9-13%**
- **PAR sheet 实例** [stoppredatorygambling.org](https://stoppredatorygambling.org/wp-content/uploads/2012/12/PAR-Sheets-Probabilities-and-Slot-Machine-Play-Implications-for-Problem-and-Non-Problem-Gambling.pdf): Lobstermania 85% 版 hit = 4.9%，Money Storm hit = 16.7%（单线上限）
- **Variance 关系** [BeastsOfPoker](https://beastsofpoker.com/slot-variance/): 低方差 → 高 hit 高频小奖 / 高方差 → 低 hit 少量大奖。M1 paytable 结构 + 当前权重偏向低方差 classic
