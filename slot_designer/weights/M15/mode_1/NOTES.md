# M15 mode 1 — 当前 reel 权重（base + feature 联合设计）

**状态**：Phase 4 tune 完成，total RTP 对齐用户 brief。Feature engine 运行时集成还在 Phase 2 延后，但 EV 分析已经 locked in（见 `slot_designer/engine/feature_m15.py`）。

**最近更新**：2026-04-23（base game tune + feature weights 设计）

## 设计约束（user brief 2026-04-23）

- 各 mode 全局 RTP 跨 mode 不变（见 memory: `project_slot_designer_mode_rtp_invariants.md`）
- **普通 spin : Feature = 45 : 55** RTP 贡献比
- 普通 spin **低波动**（low CV）—— Cherry / Bar 为主
- Feature **中高波动**（mid-high CV）—— 稀有大爆
- Feature Play x / y 权重 + trigger 频率 由我设计

## 核心数值（analytic, post Phase 4 tune）

### Base game（engine analytic）

| 指标 | 本版 | target | 偏差 |
|---|---|---|---|
| RTP | 68.32% | 67.50% | +0.82pp |
| hit_rate | 14.30% | 13.44% | +0.86pp |
| CV | 4.45 | 4.44 | 几乎重合 ✓ |
| std_return_x | 3.03 | 3.00 | ≈ |
| shape JS | 0.048 | 0 | decent |

### Feature Play（conditional on trigger）

| 指标 | 本版 | 备注 |
|---|---|---|
| 权重 count_x (1,2,3,4,5) | 70% / 25% / 5% / 0% / 0% | 主要选 1 个 x |
| 权重 count_y (0,1,2) | 70% / 25% / 5% | 主要无 multiplier |
| accept_threshold | 40× | paytable §5 规定 |
| max_rounds | 4（3 reroll + 1 forced）| paytable |
| One-round E[R] | 240.03× | 单轮 unconditional |
| One-round P(R ≥ 40) | 56.4% | 单轮接受概率 |
| One-round E[R ｜ accept] | 415.04× | 接受分布 |
| **4-round E[R]** | **400.48× bet** | per trigger 平均 |
| 4-round std | 669.74 | |
| 4-round CV | 1.67 | 单 trigger 内波动 |
| R range | [5×, 4600×] | min / max |

### Total (base + feature)

| 指标 | 本版 | target |
|---|---|---|
| **Total RTP** | **147.62%** | 150% (-2.4pp) |
| Feature trigger rate | 0.198% (1/505 spins) | 0.206% (1/485) |
| Feature RTP 贡献 | 79.30pp | 82.50pp |
| **Base : Feature split** | **46.3 : 53.7** | **45 : 55** ✓ |

## 三重波动性

1. **Base 波动性（low）**：CV 4.45. 玩家基础 spin 体验稳定——Cherry 每 7 spin 一次、Bar 组合偶尔出、High7/Wild 罕见。
2. **Feature conditional 波动性（mid）**：CV 1.67. 一次 feature 的 payout 在 5-4600× 之间，但概率分布相对集中在 100-500× 区间。
3. **Session-level 波动性（high）**：1/505 trigger + 400× avg payout = 高波动事件稀有但大。玩家感性上有 classic boom-bust 节奏。

## RTP 贡献分解（base + feature）

| 家族 | base hit% | base RTP pp | base 占 RTP share |
|---|---|---|---|
| Cherry（1-15×）| 10.41% | 13.22 | 19.4% |
| mixed-Bar 2× | 5.22% | 10.43 | 15.3% |
| 3-Bar 5-20× | 0.83% | 10.92 | 16.0% |
| Bar + wild 10-80× | 0.22% | 8.14 | 11.9% |
| High7 30× | 0.052% | 1.57 | 2.3% |
| High7 + wild 60-120× | 0.053% | 5.37 | 7.9% |
| 3-Wild pure 200× | 0.006% | 1.12 | 1.6% |
| Jackpot (rtp_excluded) | 0% | 0 | 0% |

| Feature | trigger% | 贡献 pp | total RTP share |
|---|---|---|---|
| Feature Play | 0.198% × 400.48 | 79.30 | 53.7% |

## 桶分布（base only）

```
Low (1-10×):   23.65pp (35%)
Mid (10-50×):  19.07pp (28%)
High (50-500×): 8.06pp (12%)
Top (500+):     0.00pp (0%)
```

Mid 占比低于 M1 因为 M15 的 wild 只有 ×2（M1 有 ×2 + ×3 叠加）。Wild 放大层没那么厚，RTP 更集中在纯 pay 组合（不经 wild 叠加）。

## 玩家体验节奏

| 事件 | 频率 |
|---|---|
| Cherry 1× | 每 11 spin 左右 |
| mixed-Bar 5 | 每 19 spin |
| 3-Bar 5-20× | 每 120 spin |
| Bar+wild 30-90× | 每 460 spin |
| High7 30× | 每 1,920 spin |
| Wild-amped 大奖 60-120× | 每 1,900 spin |
| **Feature 触发** | **每 505 spin** |
| Feature payout ≥ 1000× | 每 ~10,000 spin（rare big event）|

## 文件清单

- `weights.json` —— mode 1 per-stop weight 数组（post-tune）
- `reel_weights.tsv` —— 人类可读 36×3 表
- `TUNE_REPORT.md` —— Phase 4 + joint Phase 5 最近一次 tune 输出
- `NOTES.md` —— 本文件

Symbol 布局在 [`../reel_strips.json`](../reel_strips.json)（所有 mode 共用）。

## Feature 运行时（Phase 2 TODO）

当前 Feature Play 只有 **analytic EV + test lock**；SpinEngine 侧没实现 round-level feature payout emission。Phase 2 需要：

1. 扩展 `SpinEngine.spin()` 发现 Bonus 在 reel 3 payline → 触发 feature round
2. Feature round simulator 按 spec 权重 roll x + y + 4-round accept/reroll 逻辑
3. Round-level 输出字段：`FeatureTriggered: bool`, `FeatureRounds: int`, `FeaturePayout: int`
4. Analyzer 侧加 feature RTP 单独 track + 报告面板
5. Emitter 侧 chunk schema 扩展

之前 commit 41f5e4d 留了 `spec.features[0]._status = "Phase 2 TODO"` 注释。现在该 status 改为 "EV analytic shipped; engine integration still Phase 2"。

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
  --hit-target 0.13435 --hit-weight 1.5 \
  --cv-weight 0.3 --shape-weight 2.0 \
  --skip-rawdata

# 重要：tune 完后手动把 Bonus weight clamp 回 1 per stop
# (tuner 会把 Bonus 当 free variable 推高到 ~7；
# 我们要 1/500 trigger 所以固定 = 1)
python -c "
import json
from pathlib import Path
d = json.loads(Path('slot_designer/weights/M15/mode_1/weights.json').read_text(encoding='utf-8'))
strips = json.loads(Path('slot_designer/weights/M15/reel_strips.json').read_text(encoding='utf-8'))['reels']
for i, s in enumerate(strips[2]):
    if s == 'Bonus':
        d['weights'][2][i] = 1
Path('slot_designer/weights/M15/mode_1/weights.json').write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding='utf-8')
"
```

Future: 加个 `--pin-symbol <SYM>:<weight>` flag 到 tune.py，Phase 4 ES 跳过指定 symbol 的 count 搜索；这样就不用后 clamp。
