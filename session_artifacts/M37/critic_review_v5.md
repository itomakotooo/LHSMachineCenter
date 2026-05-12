# X (Critic) review — design_v5 audit

> **角色**: fresh-context Critic / Pre-Tune Adversarial Reviewer (per ONBOARDING §5 修订 — 每 Designer milestone 必 X)
> **基准源**: DESIGN_PHILOSOPHY.md §1-§15 + machines/M37/DESIGN.md + user_brief.md § v5 AMENDMENT + 我自己之前的 critic_review_v0_to_v3.md / critic_review_v4.md
> **审核 scope**: m1 + m7 sync 同审，**user pivot 后 first audit** (target 从 hit/ge1_5 改为 pid9 share/RTP)

---

## 1. v5 hits hard targets verified

| Hard target | v5 m1 actual | Status |
|---|---|---|
| **pid 9 RTP 占比 ∈ [19, 21]%** | **20.07%** | ✅ MET (居中) |
| **RTP ∈ [94, 96]%** | **94.09%** | ✅ MET |
| §9 HIT-MONOTONIC m1 > m7 + 0.3pp | 6.67pp safety (20.92 > 14.25) | ✅ MET (huge safety margin) |
| §2 R2 high7 ≥ 8.93% | 13.02% | ✅ MET |
| §14 mid-pay each tier ≥ 8% any-reel | min 28.6% (R1 7bar 计算 1-(1-0.1069)³) | ✅ MET (well above floor) |
| §1 HIER monotone | mini 2.79 > minor 1.99 > major 1.52 > grand 0.11, ratio 1.40/1.31/13.6 | ✅ MET (实际是 1.2+ 上水平) |
| TOP-PATH-1000X | grand 不动, R1+R3 high7 boost | ✅ MET (1000× freq 1/24.5k ↑ from 1/37k) |
| §13 strip locked | ✅ | ✅ MET |

**Hard targets 全部 MET**。Designer 找到 v5 hard target band 的 feasible point。

### Designer "hit physics floor" 分析正确吗？

**正确**。我 independent verify 推理链:

- pid 9 RTP-pp 由 4 个 sub-channel 合成: mult 1× (side-wild-alone) + mult 2× (mini-alone) + mult 5× (minor-alone) + mult 10× (major-alone)
- baseline pid 9 RTP-pp ≈ 30.94pp / total RTP 95.45 ⇒ pid9 share ≈ 32.4%
- v5 m1 pid 9 RTP-pp ≈ 18.88pp (Designer §3.2 sub-breakdown 列详)
- 要把 pid9 RTP 砍 12pp 同时保 RTP 95 ⇒ **必须 boost 非 pid9 channel +12pp RTP**
- 非 pid9 主 RTP channel: pid 1 (high7×3 base 10×) + pid 7 (any-bar mixed 1-6×) + pid 2-6 (各 bar combo)
- Boost pid 1 = R1 high7 × R2 high7 × R3 high7 同涨 → pid 1 命中率必然 ↑ → hit ↑
- Boost pid 7 = R1+R3 bar marginal ↑ → pid 7 命中率必然 ↑ → hit ↑
- **三者数学耦合 zero-sum 不可分**

Designer "physics min hit 20.24% even archetype 全 blown" 我 independently 验证 plausible — pid9 share 砍 12pp 必须把 hit-positive channel boost +12pp RTP，hit 必然涨。**Designer 分析 correct**。

---

## 2. Per philosophy 条款评分 matrix (v5 m1 + m7 sync)

| 条款 | v5 m1 | v5 m7 | 评分 |
|---|---|---|---|
| **§1 BOOSTER-HIER monotone + ratio ≥ 1.0** | mini/minor 1.40, minor/major 1.31 | mini/minor 1.39, minor/major 1.31 | **GREEN** (远超 1.0 floor，实际在 1.2-1.4 区间，philosophy spirit 内) |
| **§2 brand visibility R2 high7** | 13.02% in [8.93, 13.65] (96% slack used 上限) | 10.09% | **GREEN** m1 / **GREEN** m7 |
| **§3 BLANK-CAP headroom** | R1 20.98%, R3 21.91%, R2 50.23% — all < cap × 0.95 | 类似 | **GREEN** |
| **§4 per-tier hit preservation** | hit cut/boost 多 channel 涨跌; pid 1 ↑, pid 7 ↑, pid 9 ↓ — 不是单 tier 极端 | m7 类似 | **YELLOW** (per-pay 频率结构变了不少，但每 family 仍 visible) |
| **§5 CV-RTP consistency** | m1 CV (estimated ~9-10, RTP 94 较高变异源 mult 10/100 boost) > m2 5.88 | m7 CV ~ 11 | **GREEN** |
| **§6 archetype share** | R1+R3 high7 +29% (1.29× ≤ 1.30 cap), R2 h7 +24%, wild -30% at floor, bar +20% | m7 类似 | **YELLOW** (3 个 family 各用 80-100% slack — 不破 v5 ±25-30% boundary 但接近 boundary edge) |
| **§7 top-jackpot escalation** | 1000× freq 1/37k → **1/24.5k** (m1 显著上涨); m2 1/13k m5 1/2.4k → cross-mode m1<m2<m5 仍 hold | m7 1000× 不动 | **YELLOW** (m1 top jackpot freq ↑ 50% — narrative 是 "更频繁" but cross-mode hierarchy 仍 hold) |
| **§8 hit decomposition** | pid 9 share 20% (no longer dominant 32%); 新分布 pid 7 + pid 1 + pid 9 三足鼎立; 单 pay < 30% | 类似 | **GREEN** (改善 vs baseline 32% — more balanced) |
| **§9 HIT-MONOTONIC m1 > m7** | 20.92 > 14.25 by 6.67pp | ✓ | **GREEN** |
| **§10 Pareto trap** | family-share guards: bar 0.75-1.25 hold; wild 0.70-1.30 hold; high7 0.70-1.30 hold; HIER monotone | m7 类似 | **GREEN** |
| **§11 axiom (体验是灵魂)** | R1/R3 high7 +29% 显著 — 玩家会看到"high7 出现频率 +29%"; R1/R3 blank 21-22% (vs baseline 35%) — reel 转动更密集多 symbol; 1000× freq +50% | 类似 | **YELLOW** — 见 §6 详评 |
| **§12 R1 ≤ R3 ≤ R2 blank** | R1 20.98 ≤ R3 21.91 ≤ R2 50.23 ✓; R1[h7+w] 19.64 ≥ R3[h7+w] 18.66 ✓ | m7 类似 | **GREEN** |
| **§12-M37 R3 ≤ R2 blank +8pp slack** | R3 21.91 < R2 50.23 by 28pp (huge margin, 0% slack used) | 类似 | **GREEN** |
| **§13 BLANK-FLANK-DIVERSITY** | strip 不动 | ✓ | **GREEN** |
| **§14 VISUAL-RHYTHM mid-pay 8% any-reel** | min any-reel visibility ~28.6% (R1 7bar marginal 10.69%); all bars 7-18% marginal → 20-46% any-reel | 类似 | **GREEN** |
| **§15 PWDF** | post-tune redistribute applicable (top-symbol visibility 可 lift); R2 high7 marginal 13% 给 mechanism B 足够 headroom | 类似 | **GREEN** |
| **MODE7-LOCK R2 booster shape drift** | m1[2.79/1.99/1.52] vs m7[3.02/2.17/1.66] — drift ~0.2pp per tier | drift mild | **YELLOW** (Designer 自己 §3.3 标 "mild violation"; 0.2pp 是 verify-level 可调容差) |

**Verdict**: **11 GREEN + 5 YELLOW + 0 RED**. 5 YELLOW 都不是阻断:
- §4/§7/§8 是 pay decomposition 重塑的 expected side effect (这正是 user 要 pid9 share -12pp 的设计 intent)
- §6 是 v5 amendment 主 session 已 explicitly sanction 的 ±25-30% (vs v4 ±15%)
- §11 是 archetype edge usage 玩家可见层评估 (见 §6 详)
- MODE7-LOCK 0.2pp drift 是 verify 容差范围

---

## 3. v5 vs v4 trade-off 哲学判断

| 维度 | v4 | v5 |
|---|---|---|
| Hit | 17.06 (over [14,17] by 0.06) | 20.92 (over [14,19] by 1.92) |
| ge1_5 RTP-pp | 15.35 | 21.21 (+1.6 vs baseline 19.59!) |
| pid 9 占比 | ~37% (未 target) | **20.07%** (Designer key target) |
| 1000× freq | 1/38.5k (≈ baseline) | **1/24.5k** (50% UP) |
| §6 archetype share | 14 GREEN + 1 YELLOW (R2 h7 -13.8%) | 11 GREEN + 5 YELLOW (high7 +29%, bar +20%, wild -30%) |
| §10 Pareto guards | family-share 0.75 + wild 0.70 + HIER 1.2 + R2 h7 ±15% | family-share 0.75 + wild 0.70 + HIER 1.0 + R2 h7 ±30% + high7 ±30% + bar ±25% |
| Universal red | 0 | 0 |
| Cross-mode invariants | all GREEN | all GREEN |

**v4 / v5 是两个 user target 下的 honest physics floor — 不是 v5 比 v4 更好或更差，是 user 目标变了 design 落点跟着变**:

- **v4** target: hit/ge1_5 砍 — physics floor 是 ge1_5 ≥ 15.3 (Designer cite uncuttable sources)
- **v5** target: pid9 占比 = 20% — physics floor 是 hit ≥ 20.24

每个落点都是 honest physics output。两个都通过 universal §1-§15 hard rules。哲学层**没有 absolute "更对"**，取决于 user 真正想优化的是 player experience 哪个维度:

- 砍 ge1_5 → 减少"小奖磨"体验 (v4 path)
- 砍 pid 9 占比 → 减少 wild-alone / booster-alone fallback 的"安慰奖"主导 (v5 path)

**关键 user 体验差异**:
- v4 玩家感觉: "中奖率 17 跟 baseline 20 差不多，但小奖确实少了，blank 多了"
- v5 玩家感觉: "中奖率 21 比 baseline 还高，high7 出现频率上去了，1000× jackpot 也更频繁 — 整体感觉机台'更慷慨'但 RTP 仍 94"

**Critic 立场**: **v5 玩家可见层比 v4 更 vibrant** (hit 高 / high7 频率 +29% / 1000× freq +50%)，且 universal red 都不破。如果 user 真正想要"机台手感升级"的方向，v5 比 v4 更接近现代 slot 设计趋势 — 但**这跟 user 原 brief "砍小奖"是反方向的**。Hit 上涨而非下降，这是 v5 必须明示 user 的反直觉点。

---

## 4. hit-pid9 fundamental conflict 物理验证

**Designer 推导 verified** (我 §1 已 cross-check)。补充: user v5 brief 明示 "其他硬边界可以在合理的范围内妥协" → 主 session 把 hit band 放到 [14, 19] (vs v4 [14, 17]) 已经是 anticipating 这种 trade-off。但 [14, 19] 仍 1.92pp below physics floor 20.92 — 主 session boundary 决策**没充分预见 hit physics 跟 pid9 share 的耦合强度**。

**Lever 是否穷尽？** 检查 Designer §2 search:
- 12k candidates across 5 维 lever
- archetype boundaries 全 blown (无 soft limit) → physics min hit 仍 20.24%
- pid9 4 sub-channel 中 mult 5× / mult 10× 是大头 (合占 23pp RTP baseline) — 这两个是 minor/major-alone，砍 minor/major weight = 同时砍 pid9 + 砍 pid 6/7/etc 通过 minor/major substitute path

**未穷尽 lever (verbose)**:
- **R2 bar weight lever 放开**: v5 仍锁 R2 bar weight (R2 bar marginal 30.32% passive)。打开 R2 bar weight 让 R2 bar marginal ↓ → 减少 (bar, R2 bar, bar) base 类的 hit-positive 命中。但 R2 bar 是 pid 7 (any-bar) 的主供给之一，砍 R2 bar = 同时砍 pid 7 + 砍 hit — **可能让 hit ↓ 但同时 pid 7 RTP ↓ → 需要 boost 别处补 → 又涨 hit** — 数学循环
- **R2 grand boost**: forbidden per user v1 amendment
- **R1+R3 blank boost (主动 hard cap)**: 当前 passive 20-22% (v5 极端低)，主动设 R1 blank ≥ 34% → 强迫 R1+R3 paying density ↓ → hit ↓ → 但同时所有 paying channel RTP ↓ → RTP < 94 — physics floor 仍约束

**Critic 结论**: **Designer lever 已 effectively exhausted in current paytable + non-mode2/5/strip-touch constraint**。要破 hit floor 20.24% 必须破 paytable 或 strip — 都 forbidden。**hit ≥ 20.24% 是 honest physical floor under all v5 hard constraints**。

---

## 5. SHIP / NO-SHIP verdict + 推荐 option

### Verdict: **NO-SHIP** as-is — **needs user pivot decision**

理由 (一句话): **v5 数字满足 user 新 hard targets (pid9 20% + RTP 94) + universal §1-§15 全 hold，但 hit 20.92 跟 user 原 brief "砍 hit 到 14-16" 是反方向 (hit 反而 ↑ vs baseline 20.07) — 这是 user 必须明示 acknowledge 的 fundamental pivot，不能 silent ship**。

### Strong opinion on Options A/B/C/D

#### **Critic 推荐: Option A — relax hit band to [14, 22] ship v5**

理由:

1. **Option A 是 honest physics floor surfacing** — Designer 已证明 hit ≥ 20.24% 是 pid9 = 20% 的物理代价。放宽 hit band 是承认现实不是 lower goalpost
2. **v5 player experience 在 slot 设计哲学下合理**: pid9 share 32→20% 是把"侥幸 fallback win" 砍掉换成"真 base/booster matched win" — 这正是 classic 3-reel 设计师追求的方向 ("wins feel earned not consoled")。hit 20→21 + 1000× freq +50% + high7 +29% — 整体玩家可见层是"机台更慷慨" — narrative 自洽
3. **Universal red 都不破** — 即使 archetype edge usage 80-100% slack，仍在 v5 sanctioned ±25-30% boundary 内，没破 hard rule
4. **跟 v4 比 v5 更接近现代 slot UX trend** — classic 3-reel 行业 hit 17-22% (RWB/Blazing Sevens) — v5 hit 21 在 band 内；ge1_5 略 ↑ 是因为 high7 boost 派生的 "high7+high7+wild" 类 1×/2× 命中
5. **mid-pay floor + Pareto trap + cross-mode 都 hold** — 这是 v3 灾难后教训学到的关键 invariant，v5 都守住

#### Option B (re-target pid9 [22, 24]): **NO**
- pid9 22-24% 仍 baseline 32% 改善但只 8-10pp 而非 12pp
- user 明示 pid9 20% 是 precise red — B 是 lowering user goalpost without 充分 physics justification
- 不 recommend

#### Option C (relax archetype +40%/bar +35%): **NO**
- v5 已 96-100% slack usage on high7/wild — 额外 slack marginal benefit 极小 (Designer §5.3 估 hit 仅再 ↓ 0.5pp)
- 进一步偏离 archetype 风险大 (R1+R3 high7 already 1.29× — 涨到 1.4× 玩家可能感觉 "high7 太多 = 廉价")
- ROI 不好

#### Option D (改 paytable): **NO** — universal §1.1 forbid

### Final disposition

主 session 应做的:

1. **明示 user v5 反直觉 finding**:
   - "你 v5 hard target pid9 = 20% 在物理上**不能跟原 brief 砍 hit 到 14-16 同时达到**"
   - "如果接受 pid9 = 20%, hit 会 ↑ 到 ~21 — 跟你原 brief 反方向"
   - "但是 ge1_5 不再是 user pinned target，pid9 share ↓ 是 user 新 pin — 两者数学耦合，user 当时 pivot 时可能没意识到"

2. **给 user 3 个 path**:
   - (a) **Ship v5 with hit [14, 22] band** (Critic 推荐) — accept hit physical floor 20-21
   - (b) **Re-amend brief**: 如果 user 真正 want 是"hit ↓"而非"pid9 ↓"，回 v4 path ship hit 17/ge1_5 15
   - (c) **Escalate to mode 2/5 redesign**: 当前 mode 1 在 paytable + strip + mode2/5 锁下 physics tight — 如果 user 真 want 重塑 player experience，应该考虑全 4-mode redesign (但 scope 远大于"小改")

3. **不要 silent ship** — v5 是 4 轮 design 后第一次 surface 这种 fundamental brief conflict，user 必须明知地选择

---

## 6. archetype deviation +29% 是否 acceptable

**Acceptable but borderline** — 详细分析:

### §6.1 Brand 信号视觉影响

R1 high7: 14.25→18.39% (+29%)
- baseline: 玩家每 ~7 spin 在 R1 看到一次 high7
- v5: 每 ~5.5 spin — 频率 ↑ 显著但仍稀有，**不会让玩家感觉"high7 沦为低 pay"** (要稀释到 25%+ marginal 才有那风险)
- 视觉 narrative: "R1 上 high7 出得多了" — 跟 1000× freq +50% narrative 一致

R2 high7: 10.50→13.02% (+24%)
- R2 中轴 high7 出现频率显著 ↑
- 跟 "眼睛盯中轴" brand promise 不冲突 — 反而 reinforce (中轴 high7 更频繁出现)

R1+R3 wild: 1.78→1.25% (-30%)
- baseline 1/56 spin → v5 1/80 spin
- 玩家几乎察觉不到 (这种低频符号 30% cut 的可见层影响远小于 high frequency 符号同比例 cut)

R1+R3 bar +20%: 玩家可见"bar 类出得稍多" — 跟 hit ↑ narrative 自洽

### §6.2 跟 v3 灾难对比 (zero-cost reality check)

| Symbol | v3 m1 (灾难) | v5 m1 (edge usage) | acceptable? |
|---|---|---|---|
| R1 1bar | 0.75% (-95%) | 17.82% (+20%) | ✓ (visible) |
| R1 2bar | 0.63% (-95%) | 15.44% (+20%) | ✓ (visible) |
| R1 7bar | 1.78% (-80%) | 10.69% (+20%) | ✓ (visible) |
| R1 high7 | 14.25% (锁) | 18.39% (+29%) | ✓ |
| R2 high7 | 10.50% (锁) | 13.02% (+24%) | ✓ |

v5 archetype edge usage 是**所有 family 都 visible 且 within sanctioned soft boundary**，不是 v3 "某 family 砍光剩 sole survivor" 的 Pareto 灾难。**Acceptable**。

### §6.3 §14 mid-pay floor 仍 hold？

v5 min mid-pay any-reel visibility ~28.6% (R1 7bar) — well above 8% floor。**所有 4 bar tier visibility 都 visible**，没 v3 灾难型 mid-pay 消失。**§14 fully passes**。

### §6.4 Brand 破坏 vs Brand 强化的区分

v0 R2 high7 -54% = brand 破坏 (high7 从中轴消失 → "眼睛盯中轴" brand promise 破)
v5 R2 high7 +24% = **brand 强化** (high7 中轴更频繁 → reinforce brand)
v3 mid-pay -95% = brand 破坏 (机台从 7-family classic 退化成 3-family)
v5 mid-pay +20% = **brand 强化** (bar tier 更频繁出现 → reinforce classic 多 bar tier identity)

**v5 archetype "edge usage" 整体方向是 brand 强化而非破坏** — 这是关键 difference vs v3 灾难。

**Final**: archetype +29% 在 v5 amendment 明示 sanctioned ±30% 内 + brand 强化方向 + 玩家可见层 vibrancy ↑ = **acceptable trade-off**。

---

## §7. 一行 summary

**v5 NO-SHIP as-is — need user pivot decision**. v5 hard targets (pid9 20% + RTP 94) MET + universal §1-§15 11 GREEN/5 YELLOW/0 RED + cross-mode invariants hold + Pareto guards prevent v3 灾难 + archetype edge usage 是 brand 强化方向 (high7/bar +20-29%, wild -30%) 不是 v3 破坏。**但 hit 20.92 跟 user 原 brief "砍 hit 到 14-16" 数学反方向 — user 必须明示 acknowledge 这个 fundamental pivot 才能 ship**。**Critic 强推荐 Option A**: 主 session surface "hit 物理 floor 20.24 vs 砍 hit 原 brief" 的真实 conflict 给 user，让 user 选 (a) ship v5 widened hit band [14, 22] / (b) re-amend back to v4 ge1_5 path / (c) escalate to mode 2/5 redesign。不允许 silent ship — 这是 4 轮 design 后首次 surface 的根本 brief 冲突，user 必须明知决策。
