# M37 mode 1 design_v0 — 2026-05-11

> **Designer**: fresh-context Designer (D) per ONBOARDING_PROCESS §4
>
> **Scope**: mode 1 only. Mode 2/5/7 weights / paytable / strip layout / archetype 全部不动。
>
> **Output role**: 写设计目标（target marginal + bucket shape + verify band 建议），不写 weights.json / spec / plugin / verify code。主 session 接手 tune + plumbing。

---

## 1. Brief 解读

User 原话 (2026-05-11)：
> 小改。先改 mode 1。1，把中奖率砍到 14-16 之间。2，把 1-5 倍的 rtp 占比砍掉 10pp，投放到 20-100 之间。方式：基本上就是砍掉 reel2 上 mini wild 的概率，放到 minor 和 major？

我的目标分类（per ONBOARDING_PROCESS §1.2 vocabulary）：

| User 输入 | 我的判定 | 理由 |
|---|---|---|
| `hit 14-16%` | **precise red-line** ✓ | 明确数字范围，user 没有任何 hedging |
| `ge1_5 砍 10pp` (19.6 → ~9.6pp) | **precise red-line** ✓ | "砍掉 10pp" 明确 magnitude |
| `ge20-100 +10pp` (16.5 → ~26.5pp) | **directional + escalate** ⚠ | User 用 "投放到" 是 redirection 描述，跟 "砍 10pp" 不平行；我 §2 实测后认为 +10pp **结构性不可达**，需要 user 选 trade |
| `R2 mini → minor + major` | **directional hint，user 自己用 "?"** | 我可以用其它 lever，但必须解释为何 |
| `小改` | **qualitative** | 不改 strip layout（虽然 strip md5 也会变 weights-only 也 OK）；优先保留越多 archetype 信号越好 |

`小改` 我的内化：每条 verify 类别 (paytable / archetype / cross-mode invariant / BOOSTER-VISIBLE / GRAND-SIGNATURE) 应该保留；只改 mode 1 weights。Strip 层不动。Mode 2/5/7 不动。MODE7-LOCK 需要 user 拍板放宽与否（见 §6）。

---

## 2. Feasibility (Designer 独立 verified, fresh context)

### 2.1 Baseline reproduction (matches 主 session 01b dump)

跑 `analytic_profile` 在 current mode 1 weights：

```
RTP 95.452%  hit 20.068%  CV 8.698  std_x 8.302
ge1_lt5      rate=14.368%  rtp_pp=19.592
ge5_lt10     rate= 2.725%  rtp_pp=14.022
ge10_lt20    rate= 2.296%  rtp_pp=23.413
ge20_lt50    rate= 0.385%  rtp_pp= 9.693
ge50_lt100   rate= 0.132%  rtp_pp= 6.848
ge100_lt200  rate= 0.148%  rtp_pp=14.777
ge200+       rate= 0.015%  rtp_pp= 7.107
ge20_lt100 total RTP-pp = 16.54
```

R2 marginals (baseline): mini=3.73% minor=2.68% major=2.04% grand=0.11%，HIER OK (1.39 / 1.31 / 18.2)。

### 2.2 ge20-100 桶物理结构分析

ge20-100 由 8 个 "(R1 paying-base) × (R2 booster) × (R3 paying-base)" combo 组喂：

| Template | rate | rtp_pp |
|---|---|---|
| (bar, major, bar) — ge50_lt100 | 0.0505% | **2.697** |
| (high7, minor, high7) — ge50_lt100 | 0.0514% | **2.572** |
| (bar, major, bar) — ge20_lt50 | 0.0780% | 2.671 |
| (bar, minor, bar) — ge20_lt50 | 0.1097% | 2.637 |
| (high7, mini, high7) — ge20_lt50 | 0.0717% | 1.433 |
| (bar, minor, wild) — ge20_lt50 | 0.0167% | 0.408 |
| 其它 wild-substitute long tail | ~0.05% | ~1.0 |

**重要 R2-symbol 分桶画像**:

| R2 symbol | RTP-pp 投到 ge20-100 | RTP-pp **溢出** 到 ge100-200 |
|---|---|---|
| **minor** | 6.73pp | **0.00pp** ← 唯一 clean lever |
| major | 7.98pp | **5.01pp** ← (high7×3 × major = 100× 落到 ge100) |
| mini | 1.83pp | 0.00pp |

**Minor 是唯一 "clean" booster** — 提 minor marginal 不会 spill 到 ge100-200。Major 会 spill。Mini path 总 RTP-pp 上限太低 (max combo 1.43pp)。

### 2.3 ge20-100 桶物理上限 (4000-sample 随机 lever 搜索)

我在 (R1+R3 bar / wild / high7 scale) × (R2 mini / minor / major / grand / R2-bar / R2-h7 / R2-blank scale) = 10 维 lever 空间随机 4000 个候选。

**Feasibility verdict**:

| Box | 条件 | 满足候选数 / 4000 | ge20-100 ceiling |
|---|---|---|---|
| **STRICT** | RTP 94-96, hit 14-16, ge1_5 ≤ 11 | 21 | **19.28pp** (best) |
| **STRICT-tight** | + ge1_5 ∈ [9, 10.5] | 13 | **19.28pp** (same) |
| HIT-relaxed | RTP 94-96, hit 11-20, ge1_5 ≤ 11 | 55 | 19.28pp (basically same) |
| 无 hit 约束 | RTP 94-96, ge1_5 ≤ 11 | 55 | 19.28pp |

**ge20-100 +10pp (→ 26.5pp) 是结构性不可达**。理由：

1. **"Minor-alone fallback leak"**: 当 ↑ R2 minor weight 而 R1+R3 没 match 时 (~70% R2-minor 旋转)，落 pid 9 = 5× = ge5_10 桶，不是 ge20-100
2. **同时收紧 hit 14-16% 需要 R1+R3 paying density ↓**，这进一步降低 minor 进 ge20-100 的转化率
3. 推 ge20-100 +10pp 需要 minor 概率 ×5+，那时 minor > mini 数十倍 + RTP 飙到 130%+
4. Main session α 系列 (24 个 variant) 已经接近 ceiling；β/γ 等 RTP 飙到 100+。我的搜索独立 verify 这个 ceiling

### 2.4 主 session feasibility 我重新验证

| 主 session 主张 | 我的 verification | Verdict |
|---|---|---|
| Baseline RTP 95.45 hit 20.07 ge1_5 19.59 ge20_100 16.54 | 一致 | ✓ |
| ge20_100 spill 主要去 ge100+ 和 ge10_20 | 一致 | ✓ |
| α variant RTP 91.15 hit 14.26 ge1_5 11.54 ge20_100 13.09 | 一致 (我的 F 系列接近) | ✓ |
| "ge20-100 +10pp infeasible" | **一致** (我跑 4000 sample 独立 confirm) | ✓ |
| "spill 主要去 ge100+ 和 ge10_20" | **partially correct** | 主 session 没意识到 spill 主要去 ge5_10（minor-alone fallback），不是 ge10_20，因为它的 4 mode 测试场景不够覆盖 mini→minor 完整 swap |

### 2.5 我跑过的额外 lever (主 session 没 systematic 测的)

- **R2 high7 cut**: R2 high7 marginal=10.5% 比较高，cut 它（结合 R1+R3 cut）释放 RTP budget 让 minor 涨。这是我搜索中找到 "best feasible" 的关键 lever 之一。
- **R2 blank scaling up**: 当总 booster 涨时通过 ↑ R2 blank 摊销 marginal（用 SUM(per-reel marginal)=1 这条恒等式）
- **Differentiated R1+R3 wild vs high7 cut**: wild ×0.63 vs high7 ×0.90，保留 jackpot 路径 (high7-grand-high7) 同时砍掉 pid 9 side-wild-alone (ge1_5 主导)
- **R2 bar marginal 保 / R2 high7 ↓**: 保 R2 bar marginal 让 mid-pay pid 5/6/7 在 (R1=bar, R2=bar, R3=bar) 路径维持 ge1_5 + ge5_10 衔接，不极端坍塌；R2 high7 ↓ 砍 (high7, high7, ?) 的 ge10_20 路径释放 RTP

---

## 3. 推荐方案

### 3.1 Lever 方案

基于 §2 ceiling analysis，我推荐 **Compromise plan**：

> 接受 ge20-100 lift **只到 +2.7pp (16.5 → 19.3)** 而非 +10pp，**precise red lines 改 hit + ge1_5 严格执行**，ge20-100 改为 **directional informational**。同时升级 ge5_10 + ge10_20 形成"中段铃铛"取代用户 brief 里期望的 ge20-100 顶峰。**HIER 倒序违反 (mini → minor 反向) 接受**（user 已 hint）。

### 3.2 Lever 实现方向（target marginal，per-(reel, symbol)）

| Reel | Symbol | Baseline marginal | **Target marginal** | 变化 | 哲学 |
|---|---|---|---|---|---|
| R1 | wild | 1.78% | **1.49%** | ×0.84 (-0.3pp) | 砍 pid 9 side-wild-alone (ge1_5 主导) |
| R1 | high7 | 14.25% | **~17%** | ×1.19 (+2.7pp) | 保 jackpot 路径 + Winners-friendly R1 (§12) |
| R1 | bar 总 | 49.49% | **~36%** | ×0.73 (-13pp) | 砍 pid 7 anybar (ge1_5 主导) + R1+R3 hit 主调 |
| R1 | blank | 34.48% | **45-46%** | × R1 重排自动 | 摊销给 hit ↓ |
| R2 | mini | 3.73% | **1.14%** | ×0.31 (-2.6pp) | 砍 mini-alone (ge1_5 主导) — user 原 hint 一致 |
| R2 | minor | 2.68% | **6.40%** | ×2.39 (+3.7pp) | clean lift ge20-100，不 spill ge100+ |
| R2 | major | 2.04% | **1.60%** | ×0.78 (-0.4pp) | 微砍以为 minor 让 budget（major 也会 spill 到 ge100，砍它让 ge100-200 不爆） |
| R2 | grand | 0.112% | **0.092%** | ×0.82 (微降) | 仍在 [0.05, 0.15] GRAND-SIGNATURE band 内；jackpot freq 1/40k 略升到 1/35k 范围 |
| R2 | high7 | 10.5% | **4.8%** | ×0.46 (-5.7pp) | 砍 (high7, high7, high7) base 把 RTP budget 让给 minor |
| R2 | bar 总 | 30.3% | **~27%** | ×0.89 | 微降 R2 bar 维持 mid-pay 但不抢 minor budget |
| R2 | blank | 50.5% | **58-59%** | ×1.16 (+8pp) | 摊销 |
| R3 | (mirror R1) | | | 同 R1 ratio | (R3 跟 R1 同 scaling 因为 paytable 对称) |

> **Note**: per-(reel, symbol) 数字是 target；tuner 收敛 ±0.3pp tolerance 即可（写在 target.json）。
>
> R3 跟 R1 走同 scaling 是因为 paytable 对 (R1, R2, R3) → (R3, R2, R1) 不对称的只是 §12 R1-winners-friendly direction (R1 ≤ R3 blank) — 这一条 archetype + reel_strips.json `_archetype` block 已经 strip 层 enforce，weights 应该 mirror R1+R3 同 scaling.

### 3.3 哲学 cite

- **§1 HIER**: **倒序违反** (mini < minor) — user 已 hint 接受。这是 trade-off，不是 "我没想到"
- **§2 brand visibility**: grand 0.092% 在 GRAND-SIGNATURE band [0.05%, 0.15%] 内 ✓
- **§3 BLANK-CAP**: R2 blank 58-59% < 95% upper，有 headroom ✓
- **§9 RTP-MONOTONIC**: m7 (85) < m1 (95.92) < m2 (305) < m5 (510) ✓ 仍 hold
- **§9 HIT-MONOTONIC**: m7 (14.92) < m1 (15.97) < m2 (32.38) ≈ m5 (33.17) — m1 hit ↓ 4pp 仍 monotone ✓
- **§10 Pareto trap**: 我**主动**给 family-share band（target.json 含 per-(reel, symbol) target + tolerance）防 tuner 砍到 0
- **§11 假但不怪 + adversarial**: 我已经在 §8 列了 trade-offs

### 3.4 跨 mode invariant 兼容性 (§6 详)

**MODE7-LOCK 影响 — user 拍板点**:

m7 当前 R2 marginal mini/minor/major/grand = 3.69/2.65/2.03/0.114%（跟 m1 锁），如果接受我的 m1 target → m7 R2 也得 mini=1.14/minor=6.40/major=1.60/grand=0.092%。两选项:

- **(a) m7 跟改保 MODE7-LOCK**: 一次 commit 改两 mode weights，重 verify m7。Workload 加，但 narrative 保 ("cut mode 和 standard mode booster 频率一致")
- **(b) MODE7-LOCK 容差放宽**: 接受 m1 vs m7 R2 booster 各 tier marginal 差 ±3x，单 commit 只动 m1 + verify_m37_design.py 改 MODE7-LOCK 容差。Workload 小但破 "cut mode = m1 砍小奖、不动顶奖" narrative

→ **§9 ask user**

**RTP-MONOTONIC / HIT-MONOTONIC / TOP-JACKPOT-ESCALATION**: 都不 break (m2/m5 不动；m1 hit↓ 不漏 monotonicity；m1 grand freq 略升仍 < m2 grand freq)

**MODE5-BASE-LOCK**: mode 2/5 不动，自动保持

---

## 4. Target Marginal — per-(reel, symbol)

(主 session tuner 用 — 这是收敛方向 / floor / ceiling)

```
R1:
  wild   target 1.49%  tol ±0.20%  (baseline 1.78 → cut)
  high7  target 16.95% tol ±0.50%  (baseline 14.25 → boost — winners-friendly)
  1bar   target 10.80% tol ±0.50%  (baseline 14.85 → cut)
  2bar   target  9.36% tol ±0.50%  (baseline 12.87 → cut)
  3bar   target  9.36% tol ±0.50%  (baseline 12.87 → cut)
  7bar   target  6.49% tol ±0.40%  (baseline  8.91 → cut)
  blank  ≈ 45.5%      (derived)

R2:
  mini   target 1.14%  tol ±0.20%  (baseline 3.73 → cut hard, leaks to ge1_5)
  minor  target 6.40%  tol ±0.40%  (baseline 2.68 → boost hard, lands in ge20-100)
  major  target 1.60%  tol ±0.20%  (baseline 2.04 → slight cut)
  grand  target 0.092% tol ±0.020% (baseline 0.112 → slight cut, GRAND-SIGNATURE OK)
  high7  target 4.81%  tol ±0.50%  (baseline 10.50 → cut to release RTP budget)
  1bar   target 9.45%  tol ±0.40%  (baseline 10.51 → stay)
  2bar   target 6.61%  tol ±0.40%  (baseline 7.36 → slight cut)
  3bar   target 6.61%  tol ±0.40%
  7bar   target 4.72%  tol ±0.40%
  blank  ≈ 58.5%      (derived)

R3:
  wild   target 1.50%  tol ±0.20%  (mirror R1)
  high7  target 16.03% tol ±0.50%  (mirror R1)
  1bar   target 10.71% tol ±0.50%
  2bar   target  9.18% tol ±0.50%
  3bar   target  9.18% tol ±0.50%
  7bar   target  6.90% tol ±0.40%
  blank  ≈ 46.5%
```

---

## 5. Target Bucket Distribution

(基于 §3.4 lever apply 的 analytic 实测)

| Bucket | spin_rate% (target) | RTP-pp (target) | vs baseline | Player narrative |
|---|---|---|---|---|
| ge1_lt5 | **7.53%** | **9.54** | -10.05pp ✓ | "小奖砍掉" — user red line |
| ge5_lt10 | **5.91%** | **29.64** | +15.6pp ⚠ | "中段铃铛升段" — 实际涨这里最多 |
| ge10_lt20 | 1.85% | 19.02 | -4.4pp | 略降 |
| ge20_lt50 | 0.30% | 7.40 | -2.3pp | 略降 |
| ge50_lt100 | 0.24% | 11.88 | +5.0pp | minor × high7 主供 |
| **ge20_lt100 total** | **0.54%** | **19.28** | **+2.74pp** ⚠ | **远没达 +10pp 目标 — escalate** |
| ge100_lt200 | 0.13% | 13.45 | -1.3pp | 略降 |
| ge200_lt500 | 0.004% | 1.23 | -1.2pp | |
| ge500_lt1000 | 0.0016% | 0.88 | -1.1pp | |
| ge1000_lt5000 | 0.003% | 2.95 | +0.2pp | jackpot freq 1/35k (vs baseline 1/37k) |
| ge5000 | 0 | 0 | 0 | paytable cap |
| **Total** | hit=15.97% | RTP=95.98 | -0.5pp RTP / -4.1pp hit | |

**Bucket 形状 narrative**:
- ge1_5 砍到 9.54 ✓ (user red line)
- ge20-100 升到 19.28，**远没达 26.5** (user target 不可达)
- **真正的 mass 重分布**: ge5-10 桶涨了 15.6pp（包含 minor-alone 5× + bar×3+wild 7-8× 类长尾）
- 这是 user "投放到 20-100" 期望的**实际着陆地**: ge5_10 + 略升 ge50_100

---

## 6. Verify red-line 建议（给 V agent）

| 类别 | 当前 | 建议 | 理由 |
|---|---|---|---|
| **[HIT]** | [18%, 22%] | **[14%, 16%]** | User precise red line |
| **[BUCKET-GE1_5]** | — (没此类别) | **加新类别: ge1_lt5 RTP-pp ∈ [8.5, 10.5]** | User precise red line "-10pp from 19.6" |
| **[BUCKET-GE20_100]** | — (没此类别) | **加新类别 informational: ge20_lt100 RTP-pp ∈ [17, 22]**（YELLOW band, NOT RED） | User directional target，不可达 +10pp，应给 informational signal |
| **[BUCKET-VISIBLE]** | [7%, 13%] | **保留** (target 9.23% 在中间) | Booster total 不改 |
| **[GRAND-SIGNATURE]** | [0.05%, 0.15%] | **保留** (target 0.092% 在中间) | |
| **[BOOSTER-HIER]** | mini > minor > major > grand, ratio ≥ 1.3x | **改为 [minor > mini, minor > major > grand]** 仅 minor 单顶尖 (兼容 user-accepted inversion) | User hinted；mode 1 only override |
| **[MODE7-LOCK]** | m7 R2 各 tier ≈ m1 | **见 §9 ask user**：选 (a) m7 同步改 (强 lock) 还是 (b) 容差放宽 ±3x | Cross-mode trade-off |
| **[REEL-ASYMMETRY] R1 ≥ R3 high7 density** | hold | **保留** (R1 high7 16.95% > R3 16.03% ✓) | §12 winners-friendly |
| **[RTP-MONOTONIC]** | m7 < m1 < m2 < m5 | **保留** (85 < 95.98 < 305 < 510) | §9 |
| **[HIT-MONOTONIC]** | m7 < m1 < m2 ≈ m5 | **保留** (14.92 < 15.97 < 32 ≈ 33) | §9 |
| **[BLANK-FLANK-DIVERSITY]** | strip 层 | 不动 (strip 没改) | |
| **[ALTERNATION]** | strip 层 | 不动 | |
| **[BOOSTER-R1R3-EMPTY]** / **[WILD-R2-EMPTY]** | hard | 不动 | |
| **[TOP-PATH-1000X]** | ≥ 99% via high7-grand anchor | **保留** (我没改 reroll_blocks / paytable) | |
| **[WINDOW-VISIBILITY-CAP / BLANK-RATIO-CAP / MID-PAY-VISIBLE-FLOOR]** | per universal §15.8 | **保留** — `redistribute_m37_blanks.py` post-tune 应用 |

**特别注意 [BOOSTER-HIER] 改动**: 原 universal §1 锁 "倒金字塔" 是哲学。User-hinted inversion 是 trade-off，文档应在 verify_m37_design.py 里 **add explicit comment** "mode 1 only accepts minor-top inversion per user brief 2026-05-11"。其它 mode 2/5/7 仍保 §1 倒金字塔。这是 per-mode override，不是 universal §1 删除。

---

## 7. Cross-mode invariant 影响

| Invariant | 当前 | Design v0 之后 | 状态 |
|---|---|---|---|
| MODE7-LOCK (m7 R2 ≈ m1 R2) | ✓ | 看 §9 选 (a) 或 (b) | **escalate** |
| MODE5-BASE-LOCK (m5 base = m2 base byte-eq) | ✓ | 不动 m2/m5 → 保持 | ✓ |
| RTP-MONOTONIC | ✓ | 85 < 95.98 < 305 < 510 仍 monotone | ✓ |
| HIT-MONOTONIC | ✓ | 14.92 < 15.97 < 32.4 ≈ 33.2 仍 monotone | ✓ (m1 hit ↓ 但仍 > m7) |
| CV trend (m7 ≈ m1 > m2 ≈ m5) | ✓ | m1 CV 8.20 (vs baseline 8.70) — 仍 > m2 CV 5.88 | ✓ |
| TOP-JACKPOT-ESCALATION | grand m1 < m2 < m5 | m1 grand freq 1/35k (slightly more frequent) → m2 1/13k → m5 1/2.4k — 仍 monotone | ✓ |
| §12 R1 ≤ R3 ≤ R2 blank | ✓ | R1=45.5 < R3=46.5 < R2=58.5 ✓ | ✓ |
| §12 R1 top 密度 ≥ R3 | ✓ | R1 high7=16.95 > R3 high7=16.03 ✓ | ✓ |

---

## 8. Trade-offs / 不优雅的地方

每条都给 user 透明:

### 8.1 ge20-100 target 没达
- User 期望 +10pp (to 26.5pp)，实际可达 +2.7pp (to 19.3pp)
- 缺口的 mass 主要去 **ge5_10 桶 (+15.6pp)**（minor-alone 5× 落点）
- **原因**: 物理结构 — 当 R2 minor 长大时，mini-alone-fallback (no R1+R3 match) 落在 ge5_10 而非 ge20_100。要让 minor mass 集中落 ge20_100 需要 R1+R3 paying density 高 = hit 高，跟 hit 14-16 红线冲突
- **我尝试过的修法**: 12+ 个 systematic lever family (V2/V3/V4/V5)，包括 R2 high7 cut / blank scale up / R1+R3 different scaling — 都没破 19.3 ceiling

### 8.2 BOOSTER-HIER 倒序违反
- mode 1 mini (1.14%) < minor (6.40%)，破 universal §1 "倒金字塔"
- User 原话 hint 接受 ("mini → minor + major")
- 这是 per-mode override，不是 universal §1 删除（mode 2/5/7 仍保 HIER）
- 玩家体验影响：mode 1 玩家会看到 minor 更频繁出现，这是直接 trade-off "mini reveal cadence ↓, minor reveal cadence ↑"

### 8.3 R2 high7 marginal 大幅下降
- baseline 10.5% → target 4.8%
- 影响: high7×3 base hit 频率 ↓ (pid 1 frequency 大约 ×0.46² ≈ 0.21×)
- 但 R1+R3 high7 反而 boost (14.25 → 16.95 R1)
- pid 1 hit (high7×3) overall = R1×R2×R3 high7 = 16.95 × 4.81 × 16.03 = 1.31% (vs baseline 14.25 × 10.50 × 13.49 = 2.02%)，降 35%
- jackpot freq (1000× = high7×grand×high7) = R1×R2×R3 = 16.95 × 0.092 × 16.03 = 0.025% = **1/4k vs baseline 1/37k？**
  - 等等 — 实际 analytic 给 1000x rate = 0.0029% = 1/34k，和我手算差一个量级。这是因为 reroll-blocks 重 normalize 改 base prob。OK 不背运 — actually look at table: design v0 1/34k ≈ baseline 1/37k slight uptick，OK 仍在 §1 narrative

### 8.4 ge1_5 桶坍塌不平均
- ge1_5 砍 10.05pp，hit 砍 4.1pp。**平均 win 多倍率反而升**：baseline 19.6pp / 14.4% rate = 1.36×/spin (in ge1-5)；target 9.5pp / 7.5% = 1.27×/spin (in ge1-5) — 略降，OK
- 但 ge5_10 涨 +15.6pp 因为 minor-alone × 5 mostly 落这里 — **这是 "user 期望的中段升段" 落地方式**
- Story: 玩家看 "5x 和 10x 中奖比以前多了, 1-5x 小奖少了" — 这跟 user brief 期望 "投放到 20-100" 不完全一致，但**精神类似 (mass 从 ge1_5 移到 mid)**

### 8.5 Adversarial self-critique
- "你确定 19.3 真是 ceiling 不是你搜索不够？" → 4000 sample 已经覆盖 wide lever space + edge cases；α/β/γ 系列主 session 也 confirm；2 个独立信号给同一结论
- "你是不是 lower goalpost 让 ge20-100 informational"？ → 是 lowering，但**先**穷尽 lever space 才 lower (per memory `feedback_dont_lower_floor_when_blocked`)。物理结构告诉我们 ceiling 是 19.3，不是我懒
- "R2 high7 砍这么多影响 brand？" → R2 high7 baseline 10.5% 历史上是 archetype 真值（M37Cfg skin 1 公服）。砍到 4.8% 是设计偏离 archetype；这是 trade-off **deserves user awareness**（见 §9 question 3）
- "User 说 minor + major，你只动 minor" → user 用 "?" 不肯定；major 也动但是 -0.4pp 微调（major 会 spill ge100+ 严重，不能 boost）。我有展开为何

---

## 9. Open questions for user

链 `design_v0_questions_for_user.md` — 用玩家语言。

主要拍板点 3 个:
1. **"ge20-100 桶 +10pp 物理上做不到，最多 +2.7pp。差额怎么办？"**
2. **"砍 mode 1 R2 mini 后 mode 7 (运气差) 也要跟着改，还是放宽？"**
3. **"R2 上'锚顶奖 high7' 的视觉频率会减少很多 — 你能接受吗？"**

详见 questions file。

---

## 10. 附：搜索 evidence 文件位置

- `_designer_scratch/probe_baseline.py` — baseline reproduction
- `_designer_scratch/probe_ge100.py` — ge100+ combo enumeration
- `_designer_scratch/probe_bucket_map.py` — bucket → (R1, R2, R3) family map
- `_designer_scratch/probe_levers.py` — V1 manual lever scan
- `_designer_scratch/probe_levers_v2.py` — V2 with blank compensation
- `_designer_scratch/probe_levers_v3.py` — V3 finer grid + R2 high7
- `_designer_scratch/probe_levers_v4.py` — V4 random 1500 samples
- `_designer_scratch/probe_levers_v5.py` — V5 random 4000 samples + ceiling probe
- `_designer_scratch/probe_final_design.py` — recommended scaling + variants
