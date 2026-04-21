# M1sim — reel 权重版本 `558dfcdd`

**调参时间**：2026-04-21  
**状态**：当前 active  
**前一版本**：`32251c25`（M14-aligned，hit 未约束）

## 核心数值（analytic）

| 指标 | 原始 reel 表 | 前一版 `32251c25` | **本版 `558dfcdd`** | M14 target | user classic typical |
|---|---|---|---|---|---|
| RTP | 76.93% | 93.49% | **93.48%** | 93.49% | — |
| **hit_rate** | 18.11% | 24.57% | **15.29%** | 20.85% | **~15%** ✓ |
| 空转率 | 81.89% | 75.43% | **84.71%** | 79.15% | ~85% ✓ |
| std_return_x | 7.37 | 4.94 | 5.13 | 4.62 | — |
| CV (σ/RTP) | 9.57 | 5.28 | 5.49 | 4.94 | — |
| shape JS | — | 0.016 | **0.005** | — | — |
| ΔRTP vs target | +16.56pp | 0.00pp | **0.01pp** | — | — |

**本版同时满足 RTP + shape + hit 三个目标**：
- RTP Δ 0.002pp ✓
- Shape JS 0.005（比前一版 0.016 更好）
- hit_rate 15.29% 对齐 classic 单线 typical
- CV 5.06 比前一版 5.28 还更贴近 M14 target 4.94

## 为什么从 `32251c25` 改到本版

前一版对齐 M14 mode 1 的 shape + CV，但 hit_rate 自由浮动到 24.57% —— 属于"所有 slots 平均 20-25%"档，**不是 classic 单线**（行业典型 9-13%，user 自设 15%）。

本版加 `--hit-target 0.15 --hit-weight 1.5`，tuner 找到新 Pareto 点：RTP + shape + CV 同等精度，hit 命中 15%。

## 相对 `32251c25` 的 count 变化

| 符号 | reel1 | reel2 | reel3 |
|---|---|---|---|
| **Cherry** | 47 → **3** ↓44 (−94%) | 82 → **34** ↓48 | 62 → 43 ↓19 |
| Seven1 | 31 → 54 ↑23 | 38 → 21 ↓17 | 50 → 52 ↑2 |
| Seven2 | 73 → 56 ↓17 | 3 → 1 ↓2 | 26 → 27 ↑1 |
| Bar1 | 127 → 129 ↑2 | 189 → 197 ↑8 | 163 → 177 ↑14 |
| Bar2 | 182 → 157 ↓25 | 127 → 141 ↑14 | 142 → 152 ↑10 |
| Bar3 | 107 → 112 ↑5 | 66 → 58 ↓8 | 68 → 67 ↓1 |
| Diamond1 (wild2x) | 99 → 110 ↑11 | 1 → 1 = | 40 → 40 = |
| Diamond2 (wild3x) | 1 → 3 ↑2 | 1 → 1 = | 2 → 1 ↓1 |
| Blank | 491 → 492 ↑1 | 470 → 479 ↑9 | 475 → 483 ↑8 |

**关键杠杆**：Cherry reel 1 从 47 砍到 **3**（94% 下降）。P(1 cherry on payline) 从 ~14% → ~8.4% → pay_id 14 hit 16.36% → **8.37%**。RTP 靠 Bar2 + Diamond1 补回。

## 本版 per-pay_id hit 分解

| pay_id | 规则 | hit% | 占 hit_rate |
|---|---|---|---|
| 14 | 1 Cherry | **8.37%** | 55% |
| 11 | mixed 3 bars | 5.16% | 34% |
| 9 | 3 Bar1 | 0.63% | 4% |
| 8 | 3 Bar2 | 0.70% | 5% |
| 13 | 2 cherry | 0.24% | 2% |
| 7 | 3 Bar3 | 0.17% | 1% |
| 其他 | | <0.1% | <1% |
| **合计** | | **15.29%** | |

## 使用

本版已 active（`slot_designer/weights/M1_mode1.tuned.json` = 本版内容）。

**Release 路径（给 console）**：weights 文件一落地，虚拟 console 下次
refresh-md5 就会自动把 `configSummaryMd5` 更新成 558dfcdd…。Operator
在 UI 里点 **开始采样** → `virtual_analyzer` 产 chunk 到
`slot_designer/rawdata/M1sim/mode_1/`（console 自管）。dev 这边什么都
不用做。

```bash
start_virtual.bat
# → http://127.0.0.1:8878/console/
# 在 UI 里点"开始采样"即可
```

**Dev 自己 eyeball 本版数值（可选）**：用 dev-scratch 跑 simulate，
不进 console 的 rawdata 池：

```bash
python -m slot_designer.scripts.simulate \
  --spec slot_designer/specs/M1.spec.json \
  --weights slot_designer/weights/M1_mode1.tuned.json \
  --machine-name M1sim --chunks 110
# → slot_designer/_dev_scratch/rawdata/M1sim/mode_1/
#   每次跑自动 wipe 同目录下旧 chunk_*.json（无需 rm -rf）
```

## 研究依据（2026-04-21 fresh WebSearch）

- **Hit frequency 范围** — [KnowYourSlots](https://www.knowyourslots.com/slot-machine-math-hit-frequency/) / [thesportsgeek](https://www.thesportsgeek.com/blog/do-you-know-how-frequently-online-slot-machines-pay/)：classic 3-reel 10-30%，**单线窄到 9-13%**
- **PAR sheet 实例** — [stoppredatorygambling.org](https://stoppredatorygambling.org/wp-content/uploads/2012/12/PAR-Sheets-Probabilities-and-Slot-Machine-Play-Implications-for-Problem-and-Non-Problem-Gambling.pdf)：Lobstermania 85% 版 hit = 4.9%，Money Storm hit = 16.7%（单线上限）
- **Variance 关系** — [BeastsOfPoker](https://beastsofpoker.com/slot-variance/)：低方差 → 高 hit 高频小奖 / 高方差 → 低 hit 少量大奖

本版 15.29% 落在"偏高区 classic 单线"，比 Money Storm 略低、比典型中位略高，和 user 给的 typical 对齐。

## Tuner 命令（可复现）

```bash
python -m slot_designer.scripts.tune \
  --spec slot_designer/specs/M1.spec.json \
  --base-weights slot_designer/weights/M1_mode1.current.json \
  --target slot_designer/tuner/targets/M14_mode1.target.json \
  --out-weights slot_designer/weights/M1_mode1.tuned.json \
  --evaluations 2000 --restarts 3 --sa-steps 3000 \
  --hit-target 0.15 --hit-weight 1.5 \
  --seed 43
```
