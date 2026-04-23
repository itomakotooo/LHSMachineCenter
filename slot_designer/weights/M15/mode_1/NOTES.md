# M15 mode 1 — 当前 reel 权重（v5 post-retune）

**状态**：Phase 4 + 5 tune 完成（2026-04-23 v5），total RTP 对齐 user brief 95% ±1pp；Feature analytic EV 锁定在 46× / trigger 1.136% = 1/88。

**最近更新**：2026-04-23（v5 mode 1 retune：base 42.75pp target + Bonus clamp to float for trigger exact）

## 设计契约（cross-machine mode RTP rule）

- mode 1 Total RTP **95% ±1pp 严格**（见 `project_slot_designer_mode_rtp_invariants.md`）
- M15-specific: **Base : Feature = 45 : 55**（Base 42.75pp + Feature 52.25pp）
- Base low CV（4-5）
- Feature 中-高 CV（conditional 0.74；session CV 被 1/88 rarity 撑高）
- Feature x / y / count weights 详见 `MODE_DESIGN.md` v5

## 核心数值（v5 analytic, 2026-04-23）

### Base game

| 指标 | 本版 | target | 偏差 |
|---|---|---|---|
| Base RTP | **43.15pp** | 42.75pp | +0.40pp |
| hit_rate | 13.15% | 13.38% | -0.23pp |
| CV | 5.83 | 5.85 | ≈ |
| shape JS | 0.016 | 0 | decent |

### Feature Play (conditional on trigger)

| 指标 | 本版 | 备注 |
|---|---|---|
| count_x weights | (5, 40, 40, 12, 3) | 2-3 offer dominant |
| count_y weights | (75, 20, 5) | 窄 y (mode 1 专用) |
| x_value_weights (10-tuple) | `[0.0001, 0.0266, 0.1455, 0.1455, 1.3729, 1.3729, 7.4998, 7.4998, 40.9684, 40.9684]` | alpha=-2.45 @ v^alpha |
| P value distribution | P(1000)=0%, P(100)=0.03%, P(50)=0.29%, P(20)=2.75%, P(10)=15%, P(5)=82% | heavy-low TD stingy |
| accept_threshold | 40 | paytable spec |
| max_rounds | 4（3 reroll + 1 forced）| paytable spec |
| One-round E[R] | 28.26× | |
| One-round P(R ≥ 40) | 23.5% | |
| One-round E[R | accept] | 60.4× | |
| **4-round E[R] (EV per trigger)** | **46.00×** bet | |
| Conditional CV | 0.74 | |
| R range | [5×, 4880×] | |

### Total (base + feature)

| 指标 | 本版 | target |
|---|---|---|
| **Total RTP** | **95.41%** | 95.0% ±1pp ✓ |
| Feature trigger rate | **1.136% = 1/88** | 1/88 ✓ |
| Feature RTP 贡献 | 52.26pp | 52.25pp ✓ |
| **Base : Feature split** | **45.2 : 54.8** | **45 : 55 ✓** |

## 三重波动性

1. **Base 波动性 (low)**：CV 5.83。小奖（Cherry + Bar 家族）频繁落地，玩家基础旋转体验稳定。
2. **Feature conditional 波动性 (mid)**：CV 0.74。per-trigger 分布跨 5× 到 4880×，但集中在 20-100× 区间（accept rate 23.5%）。
3. **Session-level 波动性 (high)**：1/88 trigger × 46× avg payout = 仍是稀有但有 rhythm 的 event。玩家 session 内约 1-2 次 feature。

## RTP 贡献分解（base + feature）

| 家族 | base hit% | base RTP pp | base 占 RTP share |
|---|---|---|---|
| Cherry 1× + 5× + 15× | ~10% | ~11pp | ~25% |
| mixed-Bar 2× | ~4% | ~8pp | ~18% |
| 3-Bar (Bar1 20× / Bar2 10× / Bar3 5×) | ~0.8% | ~9pp | ~20% |
| Bar + wild 10-80× | ~0.3% | ~5pp | ~11% |
| High7 30× + wild amps | ~0.05% | ~3pp | ~7% |
| 3-Wild pure 200× | ~0.006% | ~1pp | ~2% |
| Jackpot (rtp_excluded) | 0% | 0pp | 0% |
| **Base total** | **~13%** | **~43.15pp** | **~83%** |

| Feature | trigger% | 贡献 pp | total RTP share |
|---|---|---|---|
| Feature Play | 1.136% × 46.0 | 52.26pp | 55% |

## 玩家体验节奏

| 事件 | 频率 |
|---|---|
| Cherry 1× | 每 ~10 spin |
| Cherry 2+（5×）| 每 ~30 spin |
| mixed-Bar 2× | 每 ~25 spin |
| 3-Bar (5-20×)| 每 ~130 spin |
| Bar + wild (10-80×)| 每 ~330 spin |
| High7 / High7+wild (30-120×)| 每 ~2000 spin |
| 3-Wild pure (200×)| 每 ~17000 spin |
| **Feature 触发** | **每 88 spin** |
| Feature payout ≥ 500× | 每 ~30 trigger (rare big event) |
| Feature jackpot (1000-card)| 每 ~几千 trigger（**mode 1 实质不可见**；mode 5 独占）|

## Mode 1 vs mode 5 的玩家记忆点

- **Mode 1** feature event: 平均 46× 的 "稀薄 TD accept"，rare mid card 是 session 记忆点
- **Mode 5** feature event: 平均 132× + P(1000)=0.19% → "1000 jackpot dream" 独占

## 文件清单

- `weights.json` — mode 1 per-stop weight 数组 + `feature_params` block（post-tune）
- `reel_weights.tsv` — 人类可读 36×3 表（由 tune 自动生成）
- `TUNE_REPORT.md` — Phase 4 + joint Phase 5 最近一次 tune 输出
- `NOTES.md` — 本文件

Symbol 布局在 [`../reel_strips.json`](../reel_strips.json)（所有 mode 共用）。

## Feature 运行时（Phase 2 TODO）

当前 Feature Play 只有 **analytic EV + test lock**；SpinEngine 侧没实现 round-level feature payout emission。Phase 2 需要：

1. 扩展 `SpinEngine.spin()` 发现 Bonus 在 reel 3 payline → 触发 feature round
2. Feature round simulator 按 feature_params 权重 roll count_x / count_y / x draws / y draws + 4-round accept/reroll 逻辑
3. Round-level 输出字段：`FeatureTriggered: bool`, `FeatureRounds: int`, `FeaturePayout: int`
4. Analyzer 侧加 feature RTP 单独 track + 报告面板
5. Emitter 侧 chunk schema 扩展

## Tune 命令（可复现）

```bash
# Phase 4 + joint Phase 5
python -m slot_designer.scripts.tune \
  --spec slot_designer/specs/M15.spec.json \
  --strips slot_designer/weights/M15/reel_strips.json \
  --base-weights slot_designer/weights/M15/mode_1/weights.json \
  --target slot_designer/tuner/targets/M15_mode1_classic.target.json \
  --out-weights slot_designer/weights/M15/mode_1/weights.json \
  --out-report slot_designer/weights/M15/mode_1/TUNE_REPORT.md \
  --mode 1 \
  --evaluations 3000 --restarts 4 --sa-steps 2000 \
  --hit-target 0.1338 --hit-weight 1.5 \
  --cv-weight 0.3 --shape-weight 2.0 \
  --skip-rawdata

# 重要：tune 完后手动 clamp Bonus 权重到精确 float 值让 trigger = 1/88
# (tuner 会把 Bonus 推到 9；v5 target 要 trigger 1.136% 对应 W≈6.234)
python -c "
import json
from pathlib import Path
d = json.loads(Path('slot_designer/weights/M15/mode_1/weights.json').read_text(encoding='utf-8'))
strips = json.loads(Path('slot_designer/weights/M15/reel_strips.json').read_text(encoding='utf-8'))['reels']
non_bonus_r3 = sum(w for s, w in zip(strips[2], d['weights'][2]) if s != 'Bonus')
W = 0.01136 * non_bonus_r3 / (2 * (1 - 0.01136))
for i, s in enumerate(strips[2]):
    if s == 'Bonus':
        d['weights'][2][i] = W
Path('slot_designer/weights/M15/mode_1/weights.json').write_text(
    json.dumps(d, indent=2, ensure_ascii=False), encoding='utf-8')
print(f'Bonus weight clamped to {W:.4f} (trigger 1.136% = 1/88)')
"
```

Future: 加个 `--pin-symbol <SYM>:<weight>` flag 到 tune.py，Phase 4 ES 跳过指定 symbol 的 count 搜索；这样就不用后 clamp。
