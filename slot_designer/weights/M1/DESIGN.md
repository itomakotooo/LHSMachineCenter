# M1 — IGT Triple Double Diamond: Player-Experience Design Contract

> 这是 M1 的设计契约。所有 M1-specific 数值在此。
> Memory 只存 universal 原则，不存机台数值。

---

## 1. 真实原型（设计灵感，非约束）

**IGT Triple Double Diamond**（3-reel 1-line classic slot）

- 来源: [Wizard of Odds Hot Roll reverse-engineered reel mapping](https://wizardofodds.com/games/slots/hot-roll/)
- Confidence: medium-high (WoO 反推，非 IGT 官方 PAR sheet)
- 原型 = 灵感，不是约束 — per [`project_slot_designer_axiom_experience_is_soul`](../../memory/project_slot_designer_axiom_experience_is_soul.md)，"假可以但不能怪"，weights 跟原型偏离 OK，前提是玩家体验合理
- Strip 修改: position 13（原 Hot Roll bonus trigger）→ Blank（M1 无 bonus）

## 2. 硬约束

- **Paytable 锁** — `slot_designer/specs/M1.spec.json` 不动
- **Strip 物理 50% Blank 交替** — `slot_designer/weights/M1/reel_strips.json` 22-stop 物理位置 1:1 alternation
- **Mode RTP**:
  - Mode 1 = 95% ± 1pp（standard baseline）
  - Mode 7 = 85% ± 1.5pp（"运气差"充值 trigger）
  - Mode 2 = 294.5% ± 20pp（lucky 福利）
  - Mode 5 = 500% ± 30pp（super-lucky）

## 3. 玩家体验目标（Tune cost function 实现的 goals）

### 3.1 全 mode 共享 (Double Diamond signature)

| | 实现机制 |
|---|---|
| Wild 在 payline 频繁可见 (brand) | per-mode `wild_on_payline_band` (10-16% standard, 12-25% lucky, 12-28% super-lucky) |
| 顶奖路径可达（Diamond×3 = 1000× rtp_excluded but reachable） | strip 设计 + per-reel 密度 |
| 顶奖家族跨 reel 一致（Seven/Diamond 不偏单 reel） | `uniformity_ratio_cap` 2.0 standard / 2.5 lucky |
| 视觉无怪 reel（3 个 reel 看起来密度一致） | mode 2/5 加 `per_reel_blank_variance_strength` (variance penalty 软偏好) |

### 3.2 Mode 1 (standard 95%)

| | 实现 |
|---|---|
| 玩家见 5-10× wins ~每 12 min/次 | `bucket_hit_floors["ge5_lt10"] >= 0.008` (1 in 125 spins) |
| 玩家见 10-20× wins ~每 10 min/次 | `bucket_hit_floors["ge10_lt20"] >= 0.010` (1 in 100 spins) |
| 不极端 boom-bust (CV 适中) | `cv_target = 9.0`, k=120 强 penalty |
| 各家族 RTP share 在 band | `family_share_bands` (Diamond 5-20%, Seven 12-22%, Bar3 10-20%, Bar2 10-22%, Bar1 8-18%, Cherry 8-17%) |

### 3.3 Mode 7 (low-RTP 85%) — "略砍小奖保大奖"

> 设计原则（user 强调多次）: 通过略微砍中奖率（总 hit rate）来砍掉一些小奖，让 RTP 达到 85%。**大奖击中率 + 期望产出绝对不动**（Diamond/Seven family 路径完全锁死）。

数值结果:
- 总 hit rate 略降（19.5% → 14.8%）
- 大奖占比略升（小奖砍后 big-win 相对 share 升）
- 波动性略升（CV 9.2 → 10.0）

实现机制 — **frozen weights**:
- Mode 7 search 时 Diamond1/Diamond2/Seven1/Seven2 的 weight 在每个 reel 上**字面锁死** = mode 1 对应值
- 只让 Bar/Cherry/Blank 自由调
- 结果: 5 个 big-win pay (id 2/3/5/6/10) 频率在 mode 7 = mode 1 精确 1.00x（差异 < 0.1%）
- 配合 family_rtp_anchor 软约束（中奖/小奖 family pp 对应砍幅度）

### 3.4 Mode 2 (lucky 300%) — "全 family 都热"

| | 实现 |
|---|---|
| Hit rate ~1.5x mode 1 | RTP target + bucket shape 自然达成 |
| 所有 pay 频率 ≥ mode 1 | `weight_floors` (mode 2 weights ≥ mode 1 weights for big-win symbols) |
| Wild 更显眼 | wild_on_payline_band 上限 25% (vs standard 16%) |
| 7-dominated (Seven 35-65%) | `family_share_bands` Seven 上限 65% |
| Reels 看起来一致（无 R-stuffing） | `per_reel_blank_variance_strength = 6.0` 软拉均匀 |

### 3.5 Mode 5 (super-lucky 500%) — "派生 from mode 2，仅顶奖路径加强"

> **派生规则（hard rule, 2026-04-28）**: 非 feature 机台 mode 5 走 `derive_m1_mode_5.py`：
> base 权重（Cherry/Bar1/Bar2/Bar3/Blank）byte-identical = mode 2，仅顶奖
> family（Diamond1/Diamond2/Seven1/Seven2）×k 缩放推 RTP 到 500%。
> **绝不**用 tune_m1.py 自由调 mode 5 — 历史教训：tuner 找 cheap RTP 路
> 会 R-collapse（R2 总 weight 暴落 4.9×）+ Bar1 R2 灭绝 + Seven1 R2 反单调
> mode 2 → mode 5（典型 pareto trap, see `feedback_tuner_pareto_trap.md`）。

| | 实现 |
|---|---|
| Base byte-identical to mode 2 | `derive_m1_mode_5.py` 复制 mode 2 weights，仅 top-bucket 缩放 |
| 顶奖 family Diamond/Seven 单调 ≥ mode 2 | bisected uniform scalar k ≈ 1.47 (×1.47 across 4 top-bucket families) |
| 7-very-heavy (Seven 50-80%) | 派生自然达成 (m5 Seven share ≈ 61% vs m2's 46%) |
| Mid/low pay 自然 shift down | base weights frozen → 顶奖 weight 增 → 总 weight 增 → base marginal 自动降 |
| Reels 视觉一致 | mode 2 base 已经 variance-balanced (per_reel_blank_variance_strength=6.0) — 派生继承 |

**实现细节**: `derive_m1_mode_5.py --write --verify` bisects single uniform scalar
k ∈ [1.0, 5.0] over Diamond1/Diamond2/Seven1/Seven2 weights to hit RTP=500±30pp.
Floor=3 (visibility), cap=80 (lucky upper bound). Per-reel weight ratio cap 3.0×.

设计意图：mode 5 = mode 2 base 不变 + 顶奖路径强化。玩家在 base 层 (cherry/bar
hit、payline 频率) 感受跟 mode 2 一样，差异完全来自顶奖密度上升 (Seven×3/Diamond×3
freq 显著增）。这是"super-lucky 是 mode 2 的 luck variation，不是另一台机"的实现。

## 4. 当前 tune 数值结果

| Mode | RTP | hit | wild_on_payline | CV |
|---|---|---|---|---|
| 1 | 95.11% | 19.44% | 14.83% | 9.22 |
| 7 | 85.28% | 14.86% | 14.73% | 10.19 |
| 2 | 294.47% | 27.87% | 22.00% | 6.23 |
| 5 | 495.32% | 27.22% | 27.83% | 5.31 |

> Mode 5 数据自 2026-04-28 走 `derive_m1_mode_5.py` 派生（base = mode 2 byte-identical + top-bucket × k）替代之前 free-tune 实现。CV 降 (5.05 → 5.31 ≈ 持平)；Seven share 60.8% → 60.9%（基本同）；R2 总 weight 106 → 575 修正 R-collapse；Bar1 R2 marginal 2.8% → 23.1% 恢复 Bar1 在 R2 的可见度。

**Big-win pay frequency (1 in N spins)**:

| Pay | Mode 1 | Mode 7 | Mode 2 | Mode 5 |
|---|---|---|---|---|
| Diamond1×3 (500×) | 27,587 | 27,609 | 9,113 | 7,592 |
| Diamond mixed (240/360×) | 10,375 | 10,383 | 4,050 | 2,204 |
| Seven2×3 (50×) | 6,069 | 6,074 | 318 | 107 |
| Seven1×3 (40×) | 1,163 | 1,164 | 256 | 142 |
| Seven mixed (25×) | 2,642 | 2,644 | 146 | 60 |

Mode 7 = mode 1 (frozen, 1.00x). Mode 2/5 monotonic ≥ mode 1.

**Per-reel Blank balance**:

| Mode | R1 | R2 | R3 | max/min |
|---|---|---|---|---|
| 1 | 52.46% | 47.56% | 61.54% | 1.29x |
| 7 | 66.99% | 53.78% | 48.43% | 1.38x |
| 2 | 34.36% | 34.62% | 34.45% | 1.01x ← variance penalty 拉到完美 |
| 5 | 28.10% | 22.64% | 30.06% | 1.33x |

## 5. 实现层

### 5.1 Tune (`slot_designer/scripts/tune_m1.py`)

- **参数化**: 27-dim per-family per-reel uniform weight (9 family × 3 reel)
- **Search**: random-restart local search w/ adaptive sigma
- **Cost components**:
  - 数值 target: RTP + hit + bucket shape + CV (硬, 通过 quadratic penalty)
  - 软偏好: family share bands, wild signature band, per-reel density caps, uniformity ratios
  - **Goal-oriented soft penalties (无 picked threshold)**:
    - `per_reel_blank_variance_strength` (mode 2/5): 跨 reel Blank 方差 → 0
    - `bigwin_pay_freq_floor` (mode 5): mode 5 big-win pay 频率 ≥ mode 2 频率（直接 goal expression）
  - 跨 mode 锚定:
    - **frozen_weights** (mode 7): big-win symbol weights LOCKED to mode 1's
    - **weight_floors** (mode 2): big-win weights ≥ mode 1's
    - **family_rtp_anchor** (mode 7): non-big-win families 跟 mode 1 anchor + cut tolerance

### 5.2 Verify (`slot_designer/scripts/verify_m1_design.py`)

11 类 check, 全绿才算 done:
- 数值 + family band: **RTP / HIT / WILD / SHARE / DENSITY / BUCKET-FLOOR**
- Mode 7 派生 lock: **MODE7-LOCK / MODE7-CUT / TOP-PATH**
- 跨 mode signature: **SIGNATURE**
- Mode 5 派生 lock (新, 2026-04-28): **MODE5-BASE-LOCK** — base 权重 byte-identical to mode 2
- 反 pareto trap (新, 2026-04-28): **R-COLLAPSE** — 每 mode max/min reel 总 weight ≤ 3.0×

### 5.3 文件

- `slot_designer/specs/M1.spec.json` — paytable + 规则
- `slot_designer/weights/M1/reel_strips.json` — 22-stop 布局 + `_archetype` 来源
- `slot_designer/weights/M1/mode_*/weights.json` — 各 mode 权重
- `slot_designer/scripts/tune_m1.py` — mode 1/2/7 tune 入口（mode 5 不走此路径）
- `slot_designer/scripts/derive_m1_mode_5.py` — mode 5 派生入口（自 mode 2）
- `slot_designer/scripts/verify_m1_design.py` — verify 入口
- `slot_designer/tuner/targets/M1_mode*.target.json` — 数值 target

## 6. 设计 Review Checklist (每次 tune 完必跑)

数值全绿 ≠ 设计完成。每次跑完 tune 必须人眼过下面 6 类，检测 player perception 层的"怪"。

### A. 数值层 (verify_m1_design.py 自动)
- RTP / Hit / Wild signature 在 band
- 各 family RTP share 在 band
- Mode 7 大奖路径 = mode 1（frozen 验证）
- Mode 7 小奖砍 ≥ 1pp
- Mid bucket (mode 1 ge5_lt10/ge10_lt20) 命中频率达标

### B. Per-reel symbol density review (人眼过 per-reel 表)
- 每个 family × 每 reel density 在 per-family cap 内
- 顶奖家族 (Seven, Diamond) 跨 reel max/min ratio ≤ 2.0 standard / 2.5 lucky
- 没有单 symbol 在某 reel 极端高 (> 22% standard / > 25% lucky)
- 每个 family 在每 reel ≥ floor (Seven2/Diamond2 ≥ 0.3%, others ≥ 1%)

### C. Per-reel Blank balance review
- Blank 跨 reel max/min ratio ≤ 2x (lucky modes 也别超 2.5x)
- 玩家盲玩看 3 个 reel 应该感觉密度差不多
- 没有"R3 永远满"或"R1 永远空"这种怪

### D. Per-pay-id frequency review (cross-mode)
- **Mode 7**: 5 个 big-win pay (id 2/3/5/6/10) 频率 = mode 1 (1.00x ± 1%)
- **Mode 2**: 所有 pay 频率 ≥ mode 1
- **Mode 5**: 5 个 big-win pay 频率 ≥ mode 2 (单调 m1 ≤ m2 ≤ m5)
- Mode 5 small/mid Bar/Cherry pay frequency 可以 < mode 2 (shift mass to top intentional)

### E. Bucket distribution review
- Mode 1: ge5_lt10 hit ≥ 0.8% (~12 min cadence), ge10_lt20 ≥ 1% (~10 min)
- 没有"消失"的 bucket (≥ 0.01% hit)
- 不超 tail-heavy (200-500 bucket RTP share 不该 > 35%)

### F. Cross-mode narrative review
- CV 阶梯: mode 5 ≤ mode 2 < mode 1 ≤ mode 7
- Hit rate 阶梯: mode 7 < mode 1 < mode 2 ≈ mode 5
- Wild on payline 阶梯: mode 7 ≈ mode 1 ≤ mode 2 ≤ mode 5
- Big-win pay 频率阶梯: mode 7 = mode 1 ≤ mode 2 ≤ mode 5

### 怎么用

每次 tune 完:
1. 跑 verify_m1_design.py (A 自动)
2. **人眼过 B/C/D/E/F** (脚本自动只能粗筛，player perception 部分需要人判)
3. 任一 fail 必须 root-cause:
   - 是 bound 太松 → 调强度 (k)
   - 是 anchor 漏了 → 加跨 mode 约束
   - 是 cost 表达走偏 → 重新设计 penalty
4. **绝不 patch** 用任意硬 threshold 数字。每条新约束都要从设计 goal 推出来 (e.g. "reels 看起来一致" → variance penalty 而非 "blank ≥ 30%")

## 7. 设计 Anti-patterns (避免)

每次 review 见到要警觉:

1. **picked numerical thresholds without justification**: "blank ≥ 40%", "Bar3 R1 ≤ 17%" 这种 magic number。应该: 表达 goal (variance / monotonic) 而非 cap
2. **family RTP share 锁住但 per-pay 频率漂**: e.g. mode 7 Seven family pp 守住但 Seven1×3 频率被砍 8x 因 optimizer 把 Seven1 weight 转 Seven2。Fix: per-symbol-per-reel weight 锁 (frozen) 或 per-pay-frequency 锁
3. **weight floor 漂走的 density**: weight ≥ ref 但 total reel weight 涨 → density 反降。Fix: density floor 或 pay-frequency floor (更直接)
4. **R-stuffing**: optimizer 把所有 pay symbol 堆某个 reel cubic-product 拉频率，副作用: 该 reel 视觉怪。Fix: per-reel Blank variance penalty
5. **silent re-tune approved modes**: 改 universal 约束时也动了已 ok 的 mode → user 失去 commit hash 回滚能力。Fix: 改前明确告知 + 改完立即 commit
