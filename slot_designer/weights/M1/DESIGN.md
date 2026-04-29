# M1 — IGT Triple Double Diamond: Player-Experience Design Contract

> 这是 M1 的设计契约。所有 M1-specific 数值在此。
> Memory 只存 universal 原则，不存机台数值。

---

## 1. 真实原型（设计灵感，非约束）

**IGT Triple Double Diamond**（3-reel 1-line classic slot）

- 来源: [Wizard of Odds Hot Roll reverse-engineered reel mapping](https://wizardofodds.com/games/slots/hot-roll/)
- Confidence: medium-high (WoO 反推，非 IGT 官方 PAR sheet)
- 原型 = 灵感，不是约束 — per [`project_slot_designer_axiom_experience_is_soul`](../../memory/project_slot_designer_axiom_experience_is_soul.md)，"假可以但不能怪"，weights 跟原型偏离 OK，前提是玩家体验合理
- Strip 修改 (2026-04-28): Hot Roll bonus trigger 位置 (R1[13], R2[15], R3[13]) → **Cherry**（M1 无 bonus；不能用 Blank 否则破坏 alternation 不变量）。所有 reel 22 stops 严格 B/N alternation: 11 Blank + 11 非 Blank

## 2. 硬约束

- **Paytable 锁** — `slot_designer/specs/M1.spec.json` 不动
- **Strip 物理 Blank/非 Blank 严格交替** — `slot_designer/weights/M1/reel_strips.json` 22-stop，所有 3 条 reel 都是 B-N-B-N-...-B-N 严格交替（11+11）。Universal rule (Harrigan near-miss band) per [`project_slot_designer_strips_weights_layout.md`](../../memory/project_slot_designer_strips_weights_layout.md). **不允许任何 3 连 Blank 或 3 连非 Blank**
- **Mode RTP**:
  - Mode 1 = 95% ± 1pp（standard baseline）
  - Mode 7 = 85% ± 1.5pp（"运气差"充值 trigger）
  - Mode 2 = 294.5% ± 20pp（lucky 福利）
  - Mode 5 = 500% ± 30pp（super-lucky）
- **R1 Blank 率 ∈ [30%, 40%]**（all modes，user-pinned 2026-04-28）— M1-specific design target，不是 universal:
  - **Why**: M1 是 1-line classic IGT；R1 是玩家"第一印象"reel。30% 下限：cherry/seven 视觉上需要"有空"才有 reveal drama；40% 上限：超过会"早期拒绝"玩家（per Strickland/Reid 1967/1986, [`project_slot_designer_reel_asymmetry.md`](../../memory/project_slot_designer_reel_asymmetry.md)）
  - **Where**: tune_m1.py EXPERIENCE_TARGETS 各 mode `r1_blank_band: (0.30, 0.40)` + cost penalty strength 300；verify_m1_design.py R1-BLANK-BAND check
  - **Not universal**: 多线 / video slot / cluster / megaways 应**重新校准**（线越多 R1 blank 可越低，因为多 line 缓冲早期拒绝）。Stop count / paytable 结构不同的机台抄这个数字 → "picked threshold" 反例

- **Blank-flank diversity（无 X-Blank-X）** (2026-04-29 user requirement) — strip 上每个 Blank 位置 p, strip[(p−1)%22] ≠ strip[(p+1)%22]：
  - **Why**: M1 是 line-based 3-reel slot, 视窗 3 行；X-Blank-X 显示成"两边 X 中间空"会让玩家解读廉价 near-miss → dilute 真 near-miss 价值
  - **Where**: reel_strips.json strip 排列硬约束（设计时 enforce）；verify_m1_design.py BLANK-FLANK-DIVERSITY check (universal hard 红线)
  - **Universal**: 适用 (line-based slot)；rule 跟原型 PAR sheet 不冲突就 enforce
  - 详见 [`project_slot_designer_blank_flank_diversity.md`](../../memory/project_slot_designer_blank_flank_diversity.md)

- **Visual rhythm — Bar3 / Bar1 重复位置间距 ≥ 4 stops**（M1 specific 子规则, 2026-04-29 user requirement）:
  - **Why**: M1 R1 上 Bar3 出现 3 次（pos 9/11/19），R2/R3 上 Bar1 出现 3 次。当前 R1 pos 9 和 11 间距 = 1 stop（仅隔 1 个 Blank），过近视觉上"R1 全是 Bar3"。
  - **Rationale for "≥ 4 stops"**: M1 是 22-stop strip + 11 非 Blank 位 + 同 symbol 最多重复 3 次。conservative pick：≥ 4 stops 间距 ⇔ 重复实例之间至少**隔 1 个非邻接非 Blank** symbol。这数字是 M1-specific 调出来的（不是 archetype 实证，因 Hot Roll 原型 pos 9/11 也是 1 间距），代表"修廉价 near-miss + 保 archetype 大方向"的妥协
  - **Where**: reel_strips.json 重排时遵守；verify_m1_design.py VISUAL-RHYTHM 子类 (M1 specific cap)
  - **Not universal**: M37/M15 有不同的 paytable 结构和重复 symbol 数，应自定阈值——不要抄 4

- **Window visibility — Diamond1 / Diamond2 / Seven2 any-reel ≥ 28%**（M1 specific PWDF floor 2026-04-29，**物理 reel 限制下的 regression guard**）:
  - **Why**: M1 是 IGT TDD 风格 brand machine, 顶奖 family (Diamond 系 wild + Seven2 top jackpot) 设计上应频繁可见但 payline hit rare。Harrigan IGT 实证 50% 是**虚拟 reel 映射**（64+ virtual stops mapped to 22 physical stops 用 weight-table 放大 visibility）。
  - **物理 vs 虚拟 reel constraint**: M1 当前用**物理 22-stop reel + weighted stops**（无虚拟映射层）。数学上限：22 stops + 4 top-prize × 1 instance × RTP 95% ⇒ achievable any-reel visibility ≈ 30-40% (mult=1 baseline ~28-39%)。强行用 Blank weight boost 推高 visibility 会让 RTP 崩到 13-44%（mult=2-5 实测）。
  - **Floor 28% 是 regression guard**: 当前自然 baseline (Seven2 ≈ 28.7% 最低)。设 28% 防 future change 跌破自然值。**不是 Harrigan PWDF aggressive target** — 要达到 50% 需架构升级到 virtual reel mapping
  - **Where**: verify_m1_design.py WINDOW-VISIBILITY check (12 checks: 3 symbols × 4 modes); tune_m1.py 含 PWDF mult mechanism 框架（M1 物理 reel 总返回 mult=1）
  - **Not universal**: 28% 是 M1 物理-reel-specific。5-reel video / virtual-reel 机台应 raise (Harrigan 50% 可达)
  - 详见 [`project_slot_designer_window_visibility_pwdf.md`](../../memory/project_slot_designer_window_visibility_pwdf.md)

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

| Mode | RTP | hit | wild_on_payline | CV | R1 Blank |
|---|---|---|---|---|---|
| 1 | 94.89% | 19.63% | ~14.6% | ~9.2 | 38.67% |
| 7 | 85.38% | 15.47% | 14.65% | 9.82 | 39.29% |
| 2 | 294.50% | 27.44% | ~20.7% | ~6.1 | 38.19% |
| 5 | 489.42% | 26.91% | ~26% | ~5.2 | 34.59% |

> 数值经过 5 轮迭代:
> 1. (2026-04-28) Mode 5 derive from mode 2 byte-identical (R-collapse 修)
> 2. (2026-04-28) Strip alternation 修复 (3 连 blank → Cherry, 11+11)
> 3. (2026-04-28) REEL-ASYMMETRY rule (R1 vs R3 方向锁) + universal-vs-machine 数字分层
> 4. (2026-04-28) **R1 Blank ∈ [30%, 40%] user-pinned target** — 重新 tune mode 1/2/7 + re-derive mode 5。Mode 1 R1 Blank 45.67% → 38.67%, Mode 7 R1 Blank 51.68% → 39.29%（最显著修复）
> 5. (2026-04-29) Strip non-Blank position 重排 satisfy §13 BLANK-FLANK-DIVERSITY (无 X-Blank-X) + §14 SAME-SYMBOL-SPACING ≥ 4 stops。每条 reel 仅 2/11 position 改动 (minimum-change repair, archetype direction 保留)。**Marginals 完全不变** → RTP/hit 跟第 4 轮相同。Strip md5 改变 → rawdata 重采。

> 数值自 2026-04-28 经历两轮修正：
> 1. **Strip alternation 修复**: strips 改成 11+11 严格交替（R0/R1/R2 各一个 3 连 blank → Cherry）。
> 2. **REEL-ASYMMETRY 规则加入**: tune cost penalty + verify check 强制 R1 Blank ≤ R3 + R1 顶奖密度 ≥ R3。重新 tune mode 1/2/7 + re-derive mode 5。

### Per-reel asymmetry (R1 winners-friendly, R3 near-miss reel)

| Mode | R1 Blank | R3 Blank | R3-R1 | R1 top-prize | R3 top-prize | R1-R3 | 状态 |
|---|---|---|---|---|---|---|---|
| 1 | 45.67% | 63.22% | +17.54pp | 13.49% | 10.63% | +2.86pp | ✓ |
| 2 | 36.24% | 36.41% | +0.17pp | 24.42% | 25.53% | -1.11pp | ✓ (lucky tol) |
| 5 | 32.75% | 33.05% | +0.30pp | 31.70% | 32.40% | -0.70pp | ✓ (lucky tol) |
| 7 | 51.68% | 58.09% | +6.41pp | 13.09% | 12.21% | +0.88pp | ✓ |

R3 - R1 Blank ≥ 0 → 防早期拒绝 (Strickland/Reid 1967/1986)。R1 - R3 top-prize ≥ 0 (or 容差内) → R3 是"差一点"reel (Harrigan award-symbol-ratio)。Lucky modes (2/5) 容差 8pp/3pp 允许略漂方向。

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

17 类 check, 全绿才算 done:
- 数值 + family band: **RTP / HIT / WILD / SHARE / DENSITY / BUCKET-FLOOR**
- Mode 7 派生 lock: **MODE7-LOCK / MODE7-CUT / TOP-PATH**
- 跨 mode signature: **SIGNATURE**
- Mode 5 派生 lock (2026-04-28): **MODE5-BASE-LOCK** — base 权重 byte-identical to mode 2
- 物理 strip 不变量 (2026-04-28): **ALTERNATION** — 每 reel Blank/非 Blank 严格交替（universal rule per memory）
- Reel 心理不对称 (2026-04-28): **REEL-ASYMMETRY** — R1 Blank ≤ R3 Blank + R1 top-prize ≥ R3 top-prize (Strickland/Reid/Harrigan 文献支持，lucky modes 容差宽)
- Brand 一致性 (2026-04-28, 替代 R-COLLAPSE): **BRAND-UNIFORMITY** — 顶奖家族 (Diamond/Seven) 跨 reel marginal ratio ≤ 2.0× (standard) / 2.5× (lucky)，或 abs spread ≤ 2pp（稀有 symbol escape valve）
- R1 早期拒绝防线 (2026-04-28, user-pinned): **R1-BLANK-BAND** — R1 Blank ∈ [30%, 40%] all modes。M1-specific (1-line classic)，多线机台需重新校准
- Strip 防廉价 near-miss (2026-04-29, user requirement, universal): **BLANK-FLANK-DIVERSITY** — strip 上每个 Blank 位置 p, strip[(p−1)%22] ≠ strip[(p+1)%22]，universal hard 红线 (0 violations)。详见 [`memory/project_slot_designer_blank_flank_diversity.md`](../../memory/project_slot_designer_blank_flank_diversity.md)
- Strip 视觉节奏 (2026-04-29, user requirement, M1 specific): **VISUAL-RHYTHM** — 同 symbol 重复实例间距 ≥ 4 stops (M1 paytable 特定阈值；其它机台自定)
- Brand symbol 视窗能见度 (2026-04-29, M1 physical-reel regression guard): **WINDOW-VISIBILITY** — Diamond1 / Diamond2 / Seven2 any-reel 视窗 visibility ≥ 28% (M1 物理 22-stop reel 自然 baseline)，Cherry 已 57% 自然达标。Harrigan 50% 需 virtual reel 映射架构 (M1 当前没有)。详见 [`memory/project_slot_designer_window_visibility_pwdf.md`](../../memory/project_slot_designer_window_visibility_pwdf.md)

**HIT band 注**：M1 是 1-line classic，mode 1 hit_hi=22% 是该 paylines 数的 reference。多线机台需重新校准 — paylines 越多 hit band 越右移 (5-9 line ≈ 25-35%, 25-50 line ≈ 30-45%, megaways ≈ 40-60%)。详见 [`memory/project_slot_designer_hit_rate_deviation.md`](../../memory/project_slot_designer_hit_rate_deviation.md)。

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
