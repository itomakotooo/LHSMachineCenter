# M1 mode 7 — 当前 reel 权重（低 RTP / Seven-heavy turbulent）

**类型**：mode 1 的低 RTP 版本 —— 直接从 mode 1 权重缩放而来，Seven/Diamond 完全不动
**最近更新**：2026-04-22 v3（直接缩放法，取代 v2 tuner 路径）

## 推导

`mode 7 = mode 1 × (Cherry × 0.5, Bar1/2/3 × 0.9)`

- **Cherry 权重 halved**（所有 reel 的 Cherry stops 权重整体 ×0.5）
- **Bar1/Bar2/Bar3 × 0.9**（reel 上所有 Bar 类 stops 权重 ×0.9）
- **Blank / Cherry / Diamond1 / Diamond2 / Seven1 / Seven2 保持 mode 1 数值不变**

放弃 tuner-based 路径（v1 + v2）的原因：tuner 的 (1+1)-ES 在「砍 Seven1」这个局部最优点稳定，把 pure Seven 100× 的 RTP 贡献从 2.67pp 压到 < 0.5pp，违反「保留 Seven 家族」的设计意图。直接缩放可以精确控制哪些 symbol 被砍哪些不动。

## 核心数值（analytic）

| 指标 | 本版 (v3) | v2 tuner 版 | mode 1 |
|---|---|---|---|
| RTP | 84.82% | 82.69% | 94.29% |
| hit_rate | **10.37%** | 9.93% | 15.52% |
| 空转率 | 89.63% | 90.07% | 84.48% |
| std_return_x | 5.39 | 4.92 | 5.33 |
| CV (σ/RTP) | **6.36** | 5.94 | 5.65 |
| **Seven family share** | **6.60%** ✓ | 3.10% ⚠ | 5.21% |

**关键差异 vs v2**：v3 的 Seven family 占 RTP **6.60%**，比 mode 1 的 5.21% 更高（按用户意图「砍小奖 → Seven 占比提升」）。v2 tuner 反而把 Seven 压到 3.10%（下降了），是 bug。

## RTP 贡献分解（按 pay 家族）

| 家族 | hit% | 绝对 pp | 占 RTP | vs mode 1 |
|---|---|---|---|---|
| Cherry（1-2×）| 4.79% | 4.85pp | 5.7% | ↓ 50.7% |
| mixed-Bar 5× | 2.06% | 10.30pp | 12.1% | ↓ 21.3% |
| 3-Bar 10-20× | 2.34% | 31.17pp | 36.7% | ↑ 5.6% |
| Bar + wild 30-90× | 0.89% | 33.78pp | 39.8% | ↓ 8.3% |
| Seven 100× | 0.022% | 2.65pp | **3.1%** | **≈ preserved ✓** |
| Seven + wild 150-500× | 0.013% | 2.95pp | **3.5%** | **≈ preserved ✓** |
| Grand jackpot | 0.00003% | 0.01pp | 0.0% | — |

**核心对比：Seven 家族绝对贡献 mode 1 vs mode 7**
- mode 1: Seven 100× (2.67pp) + Seven+wild (2.24pp) = **4.91pp**
- mode 7: Seven 100× (2.65pp) + Seven+wild (2.95pp) = **5.60pp**

比 mode 1 略高（约 14% 更多），因为 Bar × wild 替换路径在 Bar 权重略降后比例略变。Seven1/Seven2/Diamond 的 marginals 完全没动，纯 Seven 100× pays 命中率几乎一致。

## 桶分布

| bucket | mode 1 | mode 7 | Δ |
|---|---|---|---|
| ge1_lt5 | 9.25% | 4.65% | -4.60pp |
| ge5_lt10 | 2.65% | 2.06% | -0.59pp |
| ge10_lt20 | 2.17% | 2.33% | +0.16pp ✓ |
| ge20_lt50 | 0.92% | 0.88% | -0.04pp ✓ |
| ge50_lt100 | 0.14% | 0.13% | -0.01pp ✓ |
| ge100_lt200 | 0.020% | 0.019% | ≈ ✓ |
| ge200_lt500 | 0.004% | 0.004% | ≈ ✓ |

| 分组 | mode 1 | mode 7 |
|---|---|---|
| Low (1-10×) | 24.4% | 19.3% |
| Mid (10-50×) | 63.9% | 66.4% |
| High (50-500×) | 11.7% | 14.3% |

Mid 和 High 的**绝对 pp** 基本全保留：
- Mid: 60.25pp (mode 1) → 56.30pp (mode 7) — 94% 保留
- High: 11.03pp (mode 1) → 12.14pp (mode 7) — **110% 保留**（wild 替换在 Bar 略低时 ratio 略偏好大奖）

## 玩家体验层次

**空转率**：mode 1 的 84.5% → mode 7 的 89.6%。每 10 spin 一次命中（mode 1 是每 6.4 spin）。

| 事件 | mode 1 频率 | **mode 7 本版** |
|---|---|---|
| Cherry 1× | 每 10 spin | **每 21 spin** ← 砍半 |
| mixed-Bar 5× | 每 38 spin | **每 49 spin** |
| 3-Bar 10-20× | 每 45 spin | **每 43 spin** ← 基本持平 |
| Bar+wild 30-90× | 每 106 spin | **每 112 spin** ← 基本持平 |
| Seven 100× | 每 4,500 spin | **每 4,600 spin** ← 持平 ✓ |
| Seven+wild 150-500× | 每 8,500 spin | **每 7,700 spin** ← 略频繁 ✓ |

**感性体验核心差异**：Cherry 从每 10 spin → 每 21 spin（砍半），但中高倍率频率基本不变。每次命中更"有分量"，loss streak 稍长，但 7 爆点频率一致。波动性 CV 6.36 > mode 1 的 5.65，符合「保留 + 略增强 波动性」。

## 文件清单

- `weights.json` —— mode 7 每 stop 的 weight 数组（Cherry × 0.5, Bar × 0.9, 其他 = mode 1）
- `TUNE_REPORT.md` —— 历史 tune 报告（v2 tuner 的，保留做对照）
- `NOTES.md` —— 本文件

Symbol 布局在 [`../reel_strips.json`](../reel_strips.json)（所有 mode 共用）。

## 再生成方法（无需 tune.py）

```bash
python -X utf8 -c "
import json
from pathlib import Path
strips = json.loads(Path('slot_designer/weights/M1/reel_strips.json').read_text(encoding='utf-8'))['reels']
m1 = json.loads(Path('slot_designer/weights/M1/mode_1/weights.json').read_text(encoding='utf-8'))
m7_weights = []
for ri in range(3):
    reel = []
    for i, sym in enumerate(strips[ri]):
        orig = m1['weights'][ri][i]
        if sym == 'Cherry':        nw = max(1, round(orig * 0.5))
        elif sym in ('Bar1','Bar2','Bar3'): nw = max(1, round(orig * 0.9))
        else:                      nw = orig
        reel.append(nw)
    m7_weights.append(reel)
m7 = dict(m1); m7['mode'] = 7; m7['weights'] = m7_weights
Path('slot_designer/weights/M1/mode_7/weights.json').write_text(
    json.dumps(m7, indent=2, ensure_ascii=False), encoding='utf-8')
"
```

每次 mode 1 调整之后，重跑这段脚本就能同步重算 mode 7。保证 Seven/Diamond 完全跟随 mode 1（承诺「保中高不变」的唯一可靠路径）。

## 为什么不用 tuner

v1 (hit 7.86%) 和 v2 (hit 9.93%) 都是 tuner-based。尝试了两次不同 shape-weight / 起始权重的组合，**都把 pure Seven 100× 压到 < 0.5pp**（从 mode 1 的 2.67pp 跌掉 80%+）。原因：

- `ge100_lt200` bucket 既可以由 pay_id 10（pure 3 Seven1 100×）填，也可以由 pay_id 7 × 2 wilds（Bar3 × Diamond1 × Diamond2 = 120×）填
- 同样 bucket rate，tuner 的 (1+1)-ES 在 minimize Seven1 reel 占比 + maximize Bar 占比 这条路径上更省 RTP 预算
- 即使 shape-weight 拉到 3.0，shape_js 能到 0.004，但在同一 shape-js 下 tuner 仍偏好「少 Seven1」的 pareto 解

**结论**：对于「只想整体比例缩放」的设计意图，直接算缩放因子比跑 optimizer 更可靠。tuner 适合有复杂权衡的调参目标（比如 mode 2 的「hit + RTP + 分桶」三向约束），不适合简单的线性缩放。
