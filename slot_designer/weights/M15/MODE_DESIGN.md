# M15 4-Mode 数值概览 + 玩家感性体验

> **上游**：[`DESIGN.md`](DESIGN.md)（Top Dollar 原型研究）；`project_slot_designer_mode_rtp_invariants.md`（跨机台 mode RTP 规则）；`project_slot_designer_hit_rate_deviation.md`（派生 mode hit rate 带宽规则）  
> **下游**：每 mode `mode_<N>/NOTES.md` + `weights.json`（实现层）  
> **状态**：2026-04-24 设计稿 **v7 verified**（mode 5 feature jackpot-tail 砍到 0；其它 mode 保持 v6 不变）  
> **v6 → v7 关键变化**：mode 5 `x_value_weights[0]`（1000-card）从 0.1918 → 0.0001，per paid spin P(session R≥1000) 从 **1/3616** 降到 **1/7.6M**（趋近 0 per user brief "1000倍以上的奖需要趋近 0"）。1000-card 让出的 EV 权重补到 100-card（weight 1.6065 → 4.5），100-card per-value prob 从 1.61% 升到 4.34%。Net feature EV 从 132.00 → 132.81（小浮动），total RTP 500.29pp 贴线 500 target。Mode 5 不再是 "独占 1000 jackpot moment"，改走 "密集中-高倍命中" 路线。  
> **v5 → v6 关键变化**：mode 2 hit 36% → 22.56%（走 `--hit-target 0.225`）；mode 7 hit 7.5% → 12.46%（从 direct-scale 切 Phase 4 tune `--hit-target 0.125`）。RTP delta 不再靠 hit frequency，靠 **per-hit avg win size**（bucket shape shift）承担。见 `project_slot_designer_hit_rate_deviation.md`。  
> **v5 核心（仍适用）**：count_y per-mode；`x_value_weights` 10-tuple 作为主要 feature dial；mode 1/7 count_y (75,20,5)。

---

## 0. 设计契约 + 术语

| 约束 | 值 | 严格度 |
|---|---|---|
| mode 1 Total RTP | **95%** | ±1pp 严格 |
| mode 2 Total RTP | **300%** | ±10-20pp 可漂 |
| mode 5 Total RTP | **500%** | ±10-20pp 可漂 |
| mode 7 Total RTP | **85%** | ±1pp 严格 |
| Base : Feature split (base) | 45 : 55 | 派生 mode 可漂 |
| mode 2 vs mode 1 | **trigger 拉 2.4×**，EV ≤ 1.5× m1 | user brief |
| mode 5 vs mode 2 | trigger 同 m2，**EV 拉 2.2×** | user brief |
| mode 7 vs mode 1 | base 砍小奖，feature 完全同 m1 | user brief |
| **count_x 结构** | **2-3 offer dominant** 跨所有 mode | user brief |
| count_y 结构 | **per mode**（v5: 可漂，支持 EV 目标） | 设计选择 |

**术语**：
- **Trigger rate**：每付费 spin 触发 feature 的概率
- **EV（单次触发倍率）**：`E[R | trigger]`，进 feature 后最终接受那一轮的 multiplier 期望值（平均 payout = bet × EV）
- 关系：`feature_RTP (per spin) = trigger × EV`

**4 个 designer dials** (per mode)：

1. **trigger rate**（reel 3 Bonus weight / reel 3 total）
2. **count_x weights** (5-tuple) — **跨 mode 锁定 `(5, 40, 40, 12, 3)`**
3. **count_y weights** (3-tuple) — **per mode**
4. **x_value_weights** (10-tuple) — **per mode**，最主要 differentiation dial

---

## 1. count_x 锁定（所有 mode 共享）

`count_x = (5, 40, 40, 12, 3)`

| 抽几张 x | 权重 % | 玩家体验 |
|---|---|---|
| 1 | 5% | 罕见，classic TD 单 offer 复古感 |
| 2 | **40%** | 双 offer 展开 |
| 3 | **40%** | 三 offer 展开 — M15 核心 reveal drama |
| 4 | 12% | 偶尔大场面 |
| 5 | 3% | 极罕见 "满桌子" |

**80% rounds 是 2-3 卡 reveal** → M15 签名机制，跨 mode 一致。

---

## 2. 每 mode 的三个 dial

> **SOURCE OF TRUTH**：`slot_designer/weights/M15/feature_weights.tsv`（人读的 TSV 表）。改完跑 `python -m slot_designer.scripts.compile_m15_features_from_tsv` 写回各 mode 的 `weights.json.feature_params`。不要直接手改 JSON。

v7 `analyze_feature()` 验证通过，deviation ≤ 0.01%：

| Mode | Trigger | count_y | x_value_weights | EV | Feature RTP |
|---|---|---|---|---|---|
| 1 | 1.14% (1/88) | (75, 20, 5) | `[0.0001, 0.0266, 0.1455, 0.1455, 1.3729, 1.3729, 7.4998, 7.4998, 40.9684, 40.9684]` | **46** | 52.26pp ✓ |
| 7 | 1.14% (同 m1) | (75, 20, 5) | 同 m1 | 46 | 52.26pp ✓ |
| 2 | 2.75% (1/36) | (60, 30, 10) | `[0.0009, 0.0914, 0.3687, 0.3687, 2.3289, 2.3289, 9.3906, 9.3906, 37.8657, 37.8657]` | **60** | 164.98pp ✓ |
| 5 | 2.76% (≈同 m2) | (40, 35, 25) | `[0.0001, 4.5, 3.5, 3.5, 7.0955, 7.0955, 13.453, 13.453, 25.5065, 25.5065]` | **132.81** | 366.98pp ✓ |

x 牌 per-value 抽样概率（归一化到 6 unique values）：

| Mode | P(1000) | P(100) | P(50) | P(20) | P(10) | P(5) | 单 pick mean | Accept rate per round |
|---|---|---|---|---|---|---|---|---|
| 1 / 7 | **0.00%** | 0.03% | 0.29% | 2.75% | 15.00% | **81.94%** | 28.3 | 23.5% |
| 2 | 0.00% | 0.09% | 0.74% | 4.66% | 18.78% | 75.73% | 36.8 | 35.4% |
| 5 (v7) | **0.00%** | **4.34%** | 6.76% | 13.70% | 25.97% | **49.24%** | ~95 | 67.7% |

**结构性观察（v7 revision）**：
- 所有 mode P(1000) ≈ 0% — mode 5 v6 曾是 "独占 1000 jackpot moment"，v7 拉平。per user brief，1000 倍以上 session 要罕见（mode 5 per paid spin 从 1/3616 降到 1/7.6M）。
- mode 5 的 **P(100) 是 mode 1/2 的 ~3×**（4.34% vs 1.61%），这是 v7 补偿 1000-card 让出 EV 的主要渠道。玩家的 "big win" 感来自 **密集的 100-500 命中**，不是稀有 1000+ 事件。
- mode 5 的 P(5) 掉到 49% → "垃圾 offer 率" 明显低于 mode 1/2。
- Accept rate 从 mode 1 的 24% 攀到 mode 5 的 68% —— "几乎不 reject" 的 super-lucky feel（v7 比 v6 的 64% 略高，因为 100-card 更常见）。

---

## 3. Mode 1 — **Classic 标准** (95% total)

### 3.1 数值

| 指标 | 值 |
|---|---|
| Total RTP | 95% |
| Base RTP | 42.75pp |
| Feature RTP | 52.26pp ✓ |
| Trigger | 1.14% (1/88) |
| Feature EV | 46× |
| count_y | (75, 20, 5) |
| One-round E[R] | 28.3× |
| Accept rate per round | 23.5% |
| E[R | accept] | 60.4× |

### 3.2 玩家体验剧本

**每 100 付费 spin**:
- Cherry 1× 7-9 次（base 小激励）
- 3-Bar combo 3-5 次
- **Feature trigger 每 ~88 spin 一次**

**Feature 典型剧本**（~70% 概率）：
- Round 1: `(5, 10, 5)` = 20。Reject（< 40）
- Round 2: `(5, 5, 5)` = 15。Reject
- Round 3: `(5, 10)` × 2y = 30。Reject
- Round 4 forced: `(5, 5, 10, 5)` = 25 × 2y = 50。Accept forced
- Payout ~30-60 credits

**Sweet spot 剧本**（~25% trigger）：
- 某 round 抽到一张 20 或 50 + mult，累计到 50-100 accept
- Payout 50-150

**"Mid card dream" 剧本**（~1-2% trigger）：
- 极罕见 100 card 出现：`(5, 100, 5)` = 110 或 `(5, 5, 100) × 2y` = 220
- Payout 100-500 — mode 1 里最大 payout 上限

**1000 jackpot**：**mode 1 实质上没有**。P(1000) = 0.0001% per pick 约等于不会出现（session 级别的零概率）。玩家想要 1000 dream 要切 mode 5。

### 3.3 情感节奏

- Classic TD stingy feel：多数 round 全 5 / 全 10 → reject → forced round 4 拿小钱走人
- Occasional mid card(20/50) 出现 → "哟还行" accept
- Session 层：feature 是稀有 event（每 88 spin 一次），多数给 30-80× payout，偶尔 100-500× 是"记忆点"
- **不追求 1000 dream** — 那是 mode 5 的领域

---

## 4. Mode 7 — **标准低 (Slow Grind)** (85% total)

### 4.1 数值

| 指标 | 值 | 跟 mode 1 |
|---|---|---|
| Total RTP | 85% | -10pp |
| Base RTP | 32.5pp (实际 32.60pp) | -10pp |
| **Base hit rate** | **12.46%** | **-0.7pp（几乎持平）** |
| **Per-hit avg win** | **2.62×** | **-0.64×（小奖更小）** |
| Feature RTP | 52.26pp | **完全同 m1** |
| Trigger / EV / count_y / x_value_weights | 全部同 m1 | 不动 |

> Mode 7 的 RTP delta **不来自 hit frequency 降低**（hit 几乎持平 mode 1），而来自 **per-hit avg win 降低**（3.26× → 2.62×）。Bucket shape 移到 low-mult 桶：cherry/小 bar 命中几率保持，wild/high7 的高倍命中降。见 `project_slot_designer_hit_rate_deviation.md`。

### 4.2 派生

**v6 (2026-04-23 current)**: **Phase 4 tune with --sa-steps 0** (strips locked to mode 1). Target file: `tuner/targets/M15_mode7_standard_low.target.json`.

> v5 attempt was direct-scale `Cherry × 0.3, Bar × 0.77` via `derive_m15_mode_7.py`. It achieved RTP 32.67pp but hit_rate 7.5% (user wanted 12-13%). Direct-scale inherently ties RTP cut to hit cut — it reduces paying-symbol marginals, which drops both RTP AND hit proportionally. Switched to Phase 4 tune in v6 which hits RTP 32.5 AT hit 12-13% by shifting bucket shape toward low-mult pays (cuts wild/high7 contribution, preserves cherry/bar hits). See `memory/project_slot_designer_hit_rate_deviation.md`.

**Feature**: **100% 同 mode 1**（feature_params byte-copied post-tune）。

**Invocation**:
```bash
python -m slot_designer.scripts.tune \
    --spec slot_designer/specs/M15.spec.json \
    --strips slot_designer/weights/M15/reel_strips.json \
    --base-weights slot_designer/weights/M15/mode_7/weights.json  # seed from mode 1 \
    --target slot_designer/tuner/targets/M15_mode7_standard_low.target.json \
    --out-weights slot_designer/weights/M15/mode_7/weights.json \
    --mode 7 --sa-steps 0 --skip-rawdata \
    --hit-target 0.125 --hit-weight 1.5 \
    --trigger-target 0.01136 --trigger-symbol topdollar --trigger-reel 3 --trigger-weight 2.0
```

### 4.3 体验

**Base 命中频率跟 mode 1 一致**（每 ~8 spin 一次 vs mode 1 的 ~7.5 spin 一次），但每次命中 avg 2.6× 比 mode 1 的 3.3× 小 20%。玩家感：**一样在中奖，但"小一点"**（不是"冷了"）。Feature 剧本跟 mode 1 **完全一样**。"base 让我慢慢耗，feature 希望不变"。

---

## 5. Mode 2 — **幸运 (Lucky)** (300% total)

### 5.1 数值

| 指标 | 值 | 跟 mode 1 |
|---|---|---|
| Total RTP | 300% (实际 300.84pp) | 3.16× |
| Base RTP | 135pp (实际 135.07pp) | 3.16× |
| **Base hit rate** | **22.56%** | **×1.71（不是 ×3.16）** |
| **Per-hit avg win** | **5.99×** | **+84%（核心差异源）** |
| Feature RTP | 164.98pp ✓ | 3.16× |
| **Trigger** | **2.75% (1/36)** | **2.4×** ← feature 核心变化 |
| **Feature EV** | **60×** | 1.30× (≤1.5× ✓) |
| count_y | (60, 30, 10) | 比 m1 宽（更多 mult）|
| One-round E[R] | 36.8× | - |
| Accept rate per round | 35.4% | +50% |
| E[R \| accept] | 68.6× | - |

### 5.2 体验

**每 100 spin**：**Hit 大概 22-23 次**（mode 1 ~13 次），**Feature 每 36 spin**（mode 1 的 2.4×）。

> 2026-04-24 v6 修订：v5 的 "Cherry 每 4 spin" 描述基于 hit 36%（太密），v6 把 hit 压回 22.5% 后 cherry 大约每 8 spin 一次。Base 的"幸运"感靠每次命中 avg **6.0×**（vs mode 1 的 3.3×）承担，不是靠疯狂高频的小奖。

**Feature 进去**：
- 跟 mode 1 一样的 reveal 结构（2-3 卡 + mult）
- 但每张卡略值钱 → accept rate 从 24% 升到 35%
- Typical payout 40-150 credits
- **100 card 出现率**是 mode 1 的 ~3×，但仍很稀有（per trigger ~0.7%）
- **1000 card 仍然实质为 0** — mode 2 不提供 jackpot moment

**核心感**："base 中奖略多 + 每次更值 + feature 变常客"

---

## 6. Mode 5 — **超级幸运 (Super-Lucky, feature buff)** (500% total, **v7 no jackpot**)

### 6.1 数值

| 指标 | v7 值 | 跟 mode 2 |
|---|---|---|
| Total RTP | 502.05% (实际) | +200pp |
| Base RTP | 135.07pp | **同 m2** |
| Feature RTP | 366.98pp ✓ | 2.21× |
| **Trigger** | **2.76% (1/36)** | ≈ m2 |
| **Feature EV** | **132.81×** | 2.2× ← 核心变化 |
| count_y | (40, 35, 25) | 比 m2 宽（大幅提升 mult） |
| One-round E[R] | ~95× | 2.56× |
| Accept rate per round | 67.7% | +91% |
| **P(session R≥1000) per paid spin** | **1/7,607,861** | v6 曾 1/3616 |

### 6.2 体验

**每 100 spin**：跟 mode 2 完全一致。玩家切 mode 无法从 base 或 trigger 感知差异。

**Feature 进去**（差异集中在此，v7 修订）：

> v7 revision: mode 5 不再 "独占 1000 jackpot moment"。P(session R≥1000) per paid spin 从 v6 的 1/3616 降到 v7 的 1/7.6M（跟 mode 1/2 差不多）。"大奖"改走**密集的 100-500 命中**，不是稀有的 1000+ spike。P(100 card per pick) 从 v6 的 1.61% 提到 v7 的 4.34%（3× 密度）来补 1000-card 让出的 EV。

- 单 pick mean ~95（vs mode 2 的 37 = 2.56×）
- **P(1000 per pick) = 0.00%** (v7, was 0.19% in v6) → session R ≥ 1000 几乎不出现
- **P(100 per pick) = 4.34%** (v7, 3× denser than v6) ← 新的 "mid-high win moment"
- Accept rate 68% → 几乎每 round 都值得接
- P(5) 塌到 49% → "全 5 垃圾组"明显减少
- Typical payout 100-500 credits，大奖集中在这个 mid-high 区间（不是稀有 1000+ spike）

**核心感**："mode 2 + feature supercharge buff"
- Base 没变"运气"，但 feature event 每次狠 2.2×
- 每次 feature 里 **100-500 区间密集**（而不是罕见的 1000+ event 撑门面）
- Session 记忆点：mode 2 是"频繁小胜"，mode 5 是"feature 进去一堆 100-300 大奖累"

---

## 7. 同 R 不同组成 — UX 质量

（v4 规则保留，v5 无变动）

**核心原则**：同 R 倍率，不同组合 UX 质量不同。设计 weights 倾向"好 UX 组合"。

**规则总结**：

1. **单大 x + multiplier** = UX 顶配（"50×2=100 翻倍"、"100×2×2=400 big payout"）
2. **Multi-x sum（2-3 卡）** = M15 signature reveal drama，平均 UX
3. **Multi-x sum + multiplier 反转**（"三小卡 × 4 凑 accept"）= 所有 mode 典型 accept path
4. **5-x 散件累加** = 避免，感情单薄
5. **P(5) 保持高**（mode 1/2 80%+）= TD stingy feel 和 reject 决策感
6. **P(100) 加密** = mode 5 v7 的核心 UX: 3× mode 1/2 密度，"big payout dream" 走 100-500 区间
7. **P(1000) ≈ 0 跨所有 mode**（v7 revision）= 玩家没有"1000+ jackpot moment"期待，所有超大奖都是罕见 tail

---

## 8. 跨 Mode 速查表

| 属性 | Mode 1 | Mode 2 | Mode 5 (v7) | Mode 7 |
|---|---|---|---|---|
| **定位** | Classic | Lucky | Super-Lucky (feature buff) | Slow grind |
| Total RTP | 95.21% | 300.84% | 502.05% | 84.77% |
| Base RTP | 42.95pp | 135.07pp | 135.07pp | 32.60pp |
| Feature RTP | 52.26pp | 165.78pp | 366.98pp | 52.17pp |
| Split | 45:55 | 45:55 | 27:73（漂） | 38:62（漂） |
| **Base hit rate** | **13.17%** | **22.56%** | 22.56% (= m2) | **12.46%** |
| **Per-hit avg win** | **3.26×** | **5.99×** | 5.99× (= m2) | **2.62×** |
| **Trigger** | **1.14%** | **2.75%** | **2.76%** | **1.14%** |
| **EV (feature)** | **46×** | **60×** | **132.81×** | **46×** |
| count_x | (5,40,40,12,3) | 同 m1 | 同 m1 | 同 m1 |
| count_y | (75,20,5) | (60,30,10) | (40,35,25) | 同 m1 |
| x value weights | 见 §2 | 见 §2 | 见 §2 (v7) | 同 m1 |
| **P(1000)** | 0.00% | 0.00% | **0.00%** (v7, was 0.19%) | 0.00% |
| **P(100)** | 0.03% | 0.09% | **4.34%** (v7, was 1.61%) | 0.03% |
| P(5) | 81.9% | 75.7% | 49.2% | 81.9% |
| 单 pick mean | 28.3 | 36.8 | ~95 | 28.3 |
| Accept rate/round | 23.5% | 35.4% | 67.7% | 23.5% |
| **Per-spin P(session R≥1000)** | 1/4.8M | 1/333k | **1/7.6M** (v7, was 1/3.6k) | 1/4.8M |
| CV (conditional) | 0.74 | 0.78 | ~1.8 | 0.74 |
| 1000 jackpot moment | **无** | **无** | **无** (v7 revision) | 无 |

**Hit rate 偏离幅度 design constraint (per `project_slot_designer_hit_rate_deviation.md`)**:
- mode 7 vs mode 1: hit 基本一致 (差 ±1pp)，RTP delta 靠 **per-hit avg 砍下去** (3.26 → 2.62) 承担
- mode 2 vs mode 1: hit ×1.7（不是 ×3.16），RTP delta 里剩下的 ×1.84 靠 **per-hit avg 提上去** (3.26 → 6.00) 承担
- mode 5 vs mode 2: hit 完全一致（mode 5 base = mode 2 base byte-identical），RTP delta 全部在 **feature EV** (60× → 132×)

---

## 9. Session 级感性

**Mode 1** (classic 标准)：Cherry 小奖 grind（hit 13%），每 88 spin 一次 feature。Feature 70% 走"全 5 垃圾 forced"剧本，25% sweet spot accept，rare 100-card 是 mode 1 记忆点。**无 1000 dream**。

**Mode 2** (幸运)：Base hit 22.5%（mode 1 × 1.7，**不是 × 3**），每次命中 avg 6× 比 mode 1 的 3.3× 值得多。**Feature 每 36 spin**（2.4× mode 1）。Feature 结构跟 mode 1 一样但值略高，每次稍微好接。"base 命中略多 + 每次更值 + feature 变常客"。**100-card 偶尔出现但 1000 仍无**。

**Mode 5 (v7)** (super buff, no jackpot)：Base 跟 mode 2 一模一样（hit 22.5%，avg 6×）。Feature trigger 也同频。差异**全在 feature 内部**：
- P(5) 49%（vs mode 2 的 76%）→ 每张卡都有分量
- **P(100) 4.34%**（vs mode 2 的 0.09%, v6 mode 5 的 1.61%）→ **mid-high win 密度高**，每次 feature 见到多张 100-card
- **P(1000) 0.00%**（v7 revision, was 0.19% in v6）→ 1000+ session payout 几乎不出现（1/7.6M per paid spin），跟 mode 1/2 拉平
- Accept rate 68%（vs 35%）→ 几乎不 reject
- 平均 payout 132× vs 60× = 2.2× buff，但 payload 集中在 100-500 区间而不是罕见 1000+ spike

玩家心态："mode 2 + feature supercharge, 每次 feature 里 mid-high 奖金密集"。v6 的"独占 1000 jackpot moment"概念在 v7 已经去掉 per user brief 2026-04-24 "1000 倍以上的奖需要趋近 0"。

**Mode 7** (slow grind)：Base hit 12.5%（几乎同 mode 1 的 13%），**但每次命中 avg 2.6× 比 mode 1 的 3.3× 小 20%**。Feature 跟 mode 1 **完全一样**。"base 中奖频率不变但每次小一点，feature 希望同 mode 1"。v6 从 v5 direct-scale (Cherry ×0.3 → hit 7.5%) 切到 Phase 4 tune，让 hit 贴回 mode 1。

---

## 10. 实现状态

**v6 最终状态（2026-04-24）**：

### Engine / emitter 层（v5 完成，v6 不变）
- `slot_designer/engine/feature_m15.py` — `x_value_weights` + `y_value_weights` 权重抽样 ✓
- `slot_designer/engine/spin.py` — `spin_session()` 产 (SpinOutcome, feature_rounds) tuple ✓
- `slot_designer/engine/rules.py` / `evaluator.py` — `wild_required` split + `scatter_trigger` 规则 ✓
- `slot_designer/engine/reel_strip.py` — float 权重 ✓
- `slot_designer/engine/loader.py` — 自动从 weights.json `feature_params` 块构建 FeatureSpec ✓
- `slot_designer/emitter/round.py` / `robot.py` / `driver.py` — ST=14/15 emit, analysisResult JSON string, shared `sample_one_chunk` kernel ✓
- `slot_designer/specs/M15.spec.json` — 生产 schema 对齐 (lowercase symbols, pay_ids, scatter_trigger pay_id 666) ✓
- `slot_designer/backend/virtual_analyzer.py` — explicit machine/mode kwargs + mutated-upstream-md5 sync ✓
- `slot_designer/backend/virtual_registry.py` — `_discover_modes_on_disk` auto-discover ✓

### Weights / targets
- `mode_1/weights.json` — Phase 4 tune v5，不变
- `mode_2/weights.json` — **v6 Phase 4 tune**：rtp 135 + hit 0.225 + trigger 0.0275
- `mode_5/weights.json` — v6 copy mode 2 base + 增强 feature_params
- `mode_7/weights.json` — **v6 Phase 4 tune**（从 v5 direct-scale 切过来）：rtp 32.5 + hit 0.125 + trigger 0.01136
- `reel_strips.json` — v5 不变（所有 mode 字节级共用）
- `tuner/targets/M15_mode1_classic.target.json` — v5
- `tuner/targets/M15_mode2_lucky.target.json` — v6 (hit 0.225)
- `tuner/targets/M15_mode7_standard_low.target.json` — v6（新）

### Scripts
- `scripts/tune.py` — `--trigger-target` 家族 flag ✓；`--sa-steps 0` 时跳过 sibling 写入 ✓
- `scripts/derive_m15_mode_5.py` — copy mode 2 base + swap feature_params ✓
- `scripts/derive_m15_mode_7.py` — **deprecated v6**（direct-scale 不满足 hit rate deviation rule，要显式 `--i-know-this-is-deprecated` 才能运行）
- `scripts/verify_m15_modes.py` — feature EV 验证工具

### Tests
- `tests/test_m15_feature.py` — mode 1 EV / trigger / schema 回归
- `tests/test_strips_identical_across_modes.py` — 4 mode strips byte-identical 回归（含 inject-bug self-check）
- `tests/test_sampling_kernel_shared.py` — sample_one_chunk 跨路径一致 + envelope tagging 回归
- `tests/test_virtual_analyzer_cli.py` — md5 mutation flow 回归
- `tests/test_virtual_registry_mode_discovery.py` — auto-discover mode 回归

### Memory 新增
- `memory/project_slot_designer_strips_identical_across_modes.md` — strips 跨 mode 字节级一致
- `memory/project_slot_designer_hit_rate_deviation.md` — 派生 mode hit rate 带宽规则

## Analytic 最终总 RTP（v6 shipped）

| mode | base RTP | hit | per-hit | feature EV | feature RTP | total | target | status |
|---|---|---|---|---|---|---|---|---|
| 1 | 42.95pp | 13.17% | 3.26× | 46× | 52.26pp | **95.21%** | 95 ±1 | ✓ |
| 2 | 135.07pp | 22.56% | 5.99× | 60× | 165.78pp | **300.84%** | 300 ±20 | ✓ |
| 5 | 135.07pp | 22.56% | 5.99× | 132× | 364.75pp | **499.82%** | 500 ±20 | ✓ |
| 7 | 32.60pp | 12.46% | 2.62× | 46× | 52.17pp | **84.77%** | 85 ±1 | ✓ |

**未实施（推迟）**：
- Joint Phase 5 SA 跨 4 mode co-swap — 没必要：当前所有 mode 的 experience metrics (near_miss / PWDF / blank_adj) 都是 0，alternation_violations 也是 0。Phase 5 在 mode 1 tune 时已经把 strip 拉到最优，后续 mode 都 `--sa-steps 0` 保留这个 strip。

---

## 11. 总结

| Mode | 一句话 | 核心差异维度 |
|---|---|---|
| 1 | "等 TD 符号 + 多卡 reveal" | baseline |
| 7 | "中奖频率跟 m1 一样，每次小一点" | base **per-hit avg ↓ 20%**（hit 几乎持平），feature 同 m1 |
| 2 | "base 命中略多 + 每次更值 + feature 变常客" | hit ×1.7（不是 ×3），**per-hit avg ↑ 84%**，trigger ×2.4 |
| 5 (v7) | "feature supercharge, 密集 100-500 大奖（不追 1000+）" | base 完全 = m2；**feature EV ×2.2×**；v7 砍 1000-card → P(session R≥1000) 从 1/3616 → 1/7.6M，补到 100-card 3× 密度 |

**跨 mode 锁定**：count_x `(5, 40, 40, 12, 3)` — 2-3 offer dominant reveal structure 是 M15 签名。

**Per-mode 变化**：trigger rate + count_y + x_value_weights 三个 dial 共同支持 4 mode 的体验差异化。mode 5 独占 P(1000) > 0 是核心 UX 卖点。
