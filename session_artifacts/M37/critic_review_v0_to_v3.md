# X (Critic) review — M37 mode 1 v0→v3 sanity audit

> **角色**：fresh-context Critic / Pre-Tune Adversarial Reviewer (per ONBOARDING_PROCESS §4)
> **不站 Designer 边，不站 user 边 — 站 slot 设计哲学边**
> **基准源**：DESIGN_PHILOSOPHY.md §1-§15 + WORKFLOW.md adversarial 5 反问 + machines/M37/DESIGN.md §1 archetype + §2 hard constraints + user_brief.md
> **触发原因**：主 session 跑了 4 轮 Designer (v0/v1/v2/v3) **没 spawn 任何一次 Pre-Tune Review (Stage 4 X gate)**。User 看到 v3 R1+R3 mid-pay 几近消失后反问"设计哲学里没有合理性的评估选项？"
> **本审核 scope**：对 4 个 design + user brief 本身全面 stress-test

---

## 1. Per-design 哲学 violation matrix

> RED = 直接违反 universal §X 或机台契约硬约束 / YELLOW = 偏离但有理由 / GREEN = 满足

| 哲学条款 | v0 | v1 | v2 | v3 |
|---|---|---|---|---|
| **§1 BOOSTER-HIER** (mini > minor > major > grand, ratio ≥ 1.2-1.3) | **RED** — mini 1.14% < minor 6.40%（**完全倒序** by 5.6×） | GREEN — mini 365 vs minor 262 baseline 保持，ratio 1.39/1.31 | **RED** — mini 4.00% / minor 3.80% / major 2.50% (ratio 1.05/1.52，破 1.3 floor) | **RED** — mini 3.51% / minor 3.34% / major 3.18% (ratio 1.051/1.050，破 1.3 floor + booster tier 几乎扁平) |
| **§2 brand visibility** (top/jackpot symbol visible) | **YELLOW** — R2 high7 14.25→4.81% (-9.4pp，砍 54%) 损 brand 信号；grand 0.092% 仍 in band | GREEN | GREEN — R2 high7 不动 | GREEN — R2 high7 不动 |
| **§3 BLANK-CAP** headroom | GREEN — R1 45.5% / R2 58.5% / R3 46.5% all < 0.95 cap | GREEN | YELLOW — R3 blank 57.5% 还 OK | **RED** — R1 blank **68.6%** / R3 blank **69.4%**，**逼近 cap × 0.95 = 71.25%** (假设 cap=75%)；blank dilution 极端 |
| **§4 per-tier hit preservation** | YELLOW — mode 1 hit ↓ 但 user 主动要 cut；mode 7 跟改 trade-off open | GREEN — baseline 微动 | YELLOW — m7 R2 lock 破，需同步改 | **YELLOW→RED** — m1 hit 14.42 < m7 hit 14.92 by 0.5pp **逆 HIT-MONOTONIC** 不变量 |
| **§5 CV-RTP consistency** | GREEN — m1 CV ~8.2 仍 > m2 5.88 | GREEN | GREEN — m1 CV ~8.12 | GREEN — m1 CV ~8.5 |
| **§6 Family RTP share vs archetype baseline (±15%)** | **RED** — R2 high7 marginal 砍 54% from archetype 公服 baseline 10.5%；ge20-100 桶 RTP 几乎不动 | GREEN | YELLOW — R1+R3 bar marginal ↓35%（在 ±15% 边缘超界） | **CATASTROPHIC RED** — R1 1bar **-94.9%** / R1 2bar **-95.1%** / R1 7bar **-80.0%** vs archetype baseline；**远远超 ±15% 容差**，archetype 信号毁灭 |
| **§7 Top-jackpot escalation** narrative | GREEN — m1 grand freq 1/35k vs m2 1/13k vs m5 1/2.4k monotone | GREEN | GREEN | GREEN — grand 不动 |
| **§8 Hit decomposition** (单 pay ≤ 70%) | GREEN — pid 7+9 仍 dominate hit ~50%但在 band | GREEN | YELLOW — pid 9 占比 +5pp | **RED** — pid 9 (side-wild-alone) 占 hit ~70%（other pay 都被砍光）；hit 极度 concentrate 在单一 pay |
| **§9 Mode-pair monotonicity** | GREEN — HIT m1 15.97 > m7 14.92 hold | GREEN | GREEN borderline | **RED** — HIT m1 14.42 **< m7 14.92** by 0.5pp **逆 universal §9 invariant**；除非 m7 同步改否则 invariant break |
| **§10 Pareto trap** 警惕 | YELLOW — D 有 family band，但 R2 high7 砍 54% 已是 Pareto 倾向 | GREEN | YELLOW — Pareto 在 R1+R3 bar reel-uniform | **CATASTROPHIC RED** — **教科书级 Pareto 怪兽**：tuner 把 1bar/2bar/7bar 砍到 0.05/0.05/0.20 baseline scale 因为 cost function 只看 hit + ge1_5 不看 family share；这是 [`feedback_tuner_pareto_trap.md`](memory) 警告的典型案例（"tuner 把关键 family 砍到 0 同时数字 OK"） |
| **§11 假但不怪 axiom** (体验是灵魂) | YELLOW — R2 视觉变化大但 baseline 玩家可适应 | GREEN | YELLOW — R1+R3 reel 视觉 ~30% 变 blank | **RED** — R1+R3 **2/3+ 转动是 blank**（68.6%/69.4%），玩家看到的是"基本上空 reel + 偶尔 3bar/high7/wild"，**机台 visual identity 不存在了**；这跟 baseline 是两台机 |
| **§12 Reel asymmetry** R1 ≤ R3 ≤ R2 blank + R1 top ≥ R3 | GREEN — R1 45.5 < R3 46.5 < R2 58.5；R1 high7 16.95 > R3 16.03 | GREEN | **RED** — R3 blank 57.5% **> R2 blank 49.4%** by 8pp（M37 specific R3≤R2 break） | **CATASTROPHIC RED** — R3 blank 69.4% **> R2 blank 49.6% by +19.85pp**；R2 不再是 highest-blank reel；M37 archetype "R2 是 booster reel 必须重 blank" 设计契约 fundamentally violated |
| **§13 Blank-flank diversity** (X-Blank-X) | GREEN — strip 不动 | GREEN | GREEN | GREEN — strip 不动 |
| **§14 VISUAL-RHYTHM** ⭐ **(user 怒点核心)** | YELLOW — R1+R3 bar 整 reel cut 35%，节奏被压缩但仍可辨；R2 minor 涨 2.4× 视觉密集 | GREEN | YELLOW — bar uniform cut，节奏均匀降低 | **CATASTROPHIC RED** — 详见 §1.4 |
| **§15 PWDF window visibility** + mid-pay floor | YELLOW — R2 high7 砍后 R2 high7 PWDF 自动跌；mid-pay (bar) PWDF 应过 8% floor 但 R2 booster total ↑ 压 R2 bar visibility | GREEN | YELLOW — bar visibility 跌 | **CATASTROPHIC RED** — 详见 §1.5 |

### §1.4 §14 VISUAL-RHYTHM v3 详查 (user 怒点核心)

**v3 R1+R3 mid-pay marginal 实际数字**（per design_v3.md §4.2 实测）:

| Symbol | Baseline | v3 | Δ % vs baseline |
|---|---|---|---|
| R1 1bar | 14.85% | **0.75%** | **-94.9%** |
| R1 2bar | 12.87% | **0.63%** | **-95.1%** |
| R1 7bar | 8.91% | **1.78%** | **-80.0%** |
| R1 3bar | 12.87% | 12.23% | -5.0% (sole survivor) |
| R3 1bar | 14.75% | **0.74%** | **-95.0%** |
| R3 2bar | 12.64% | **0.63%** | **-95.0%** |
| R3 7bar | 9.48% | **1.90%** | **-80.0%** |
| R3 3bar | 12.64% | 12.01% | -5.0% (sole survivor) |

**视觉影响（per PHILOSOPHY §14.1 + DESIGN.md §1 brand promise "经典 3-reel 1-line classic"）**:

1. **机台从 7-family classic 退化成 "high7 + 3bar + wild" 的 3-family 简化版**：玩家在 R1+R3 上几乎看不到 1bar / 2bar / 7bar — 每 ~130-180 spin 才出现一次。Classic slot 的 bar tier 多样性（"chase the bars" 玩法核心）消失。

2. **§14.5 "iteration review mandate" mandatory gate**: PHILOSOPHY §14.5 写"Audit scope: 每条 reel 上**每个 symbol** 都要审，不只是 bars 或 top symbols" + "任一维度违反'合理'判定 → **必须 iterate 修复**，不可'verify GREEN with informational caveat 跳过'"。

3. **Filler 不合理**：R1+R3 reel 现在变成 13 个 blank + 3 个 wild + 2 个 high7 + 2 个 3bar + (0.5个 1bar/2bar/7bar fading)。玩家看 R1 转动**视觉上是 "blank-blank-blank-(wild/high7/3bar)-blank-blank-blank"** — 完全失去 classic slot 的视觉节奏。

4. **Pair-wise top-symbol distance**：原 R1 上 9 个非 blank paying symbol 分布均匀（high7 ×2 + wild ×3 + bar ×6 + 等）。v3 后只有 ~5 个非 blank 真有 visibility（其它低到 < 1%），分布稀疏 → 玩家感觉"reel 转动毫无生气，半天看不到一个 symbol"。

5. **§14.5 archetype-first 原则**："原型 reel 排列已经过设计审美调优，slot_designer 应**保留原型 ordering** 作为基线"。v3 marginal 把 archetype baseline 的 bar 分布**自我擦除**，违反此原则。

**Verdict §14**: v3 是 §14 universal hard rule 的 **catastrophic violation**，且 PHILOSOPHY §14.5 mandate "**必须 iterate 修复，不可标 informational 跳过**" — 此为 RED 不可 ship。

### §1.5 §15 PWDF + Mid-pay floor v3 详查

PHILOSOPHY §15.8 写 "Mid-pay symbol any-reel window visibility 有 **floor**（防 mid-pay 视觉消失，玩家觉得 'reel 跟我玩的不是一台机'）"。M37 DESIGN.md §7.3 写 **`MID-PAY-VISIBLE-FLOOR` 8%** — "1bar/2bar/3bar/7bar any-reel window visibility ≥ 8%"。

**v3 mid-pay any-reel window visibility 估算**（marginal × 3-row window factor）:

| Symbol | v3 marginal | est. any-reel visibility (~3× marginal) | floor 8% pass? |
|---|---|---|---|
| R1 1bar | 0.75% | ~2.3% | **FAIL** |
| R1 2bar | 0.63% | ~1.9% | **FAIL** |
| R1 7bar | 1.78% | ~5.3% | **FAIL** |
| R1 3bar | 12.23% | ~36.7% | PASS |
| R3 1bar | 0.74% | ~2.2% | **FAIL** |
| R3 2bar | 0.63% | ~1.9% | **FAIL** |
| R3 7bar | 1.90% | ~5.7% | **FAIL** |
| R3 3bar | 12.01% | ~36.0% | PASS |

**6/8 mid-pay symbol 落到 8% floor 之下 — `MID-PAY-VISIBLE-FLOOR` hard red 6 处违反**。

DESIGN.md §7 PWDF post-tune redistribute (mechanism B) 不能救：mechanism B 是 RTP-neutral blank redistribute 提升 **top symbol** visibility，**会进一步压低 mid-pay visibility**（PHILOSOPHY §15.9 "Side effect: mechanism B 让 non-top-adj 邻接的 mid-pay symbol 视窗 visibility 下降"）。v3 已经把 mid-pay marginal 砍到 floor 以下 → post-tune redistribute 只会让更糟。

**Verdict §15**: v3 是 universal §15.8 `MID-PAY-VISIBLE-FLOOR` 硬约束 6 处违反，PWDF mechanism 救不回。

---

## 2. Per-design 玩家可见层评分 + slot 设计师不专业的地方

### v0 (Designer 第一稿 — wide lever)

**Lever**: R2 high7 砍 54% + R1+R3 bar uniform ×0.73 + R2 minor 涨 2.4× + R2 mini 砍 70%

**玩家感受**:
- R2 中轴 high7 visibility 减半 → "今天怎么 R2 上 high7 不那么响了？"
- R2 minor symbol 出现频率从 2.68% → 6.40%（2.4×）→ "minor 这奖怎么这么多见？mini 反而少了？"（HIER 倒序）
- R1+R3 bar 共 cut 35% → 玩家感觉"bar 出得没那么多了"但仍可辨
- 1000× jackpot 频率不变（grand freq 1/35-37k unchanged） → "顶奖叙事还在"

**不专业 1 — Pareto trap "let tuner kill brand symbol"**: R2 high7 从 archetype 10.5% 砍到 4.8% (-54%) 远超 §6 ±15% 容差。R2 high7 是 M37 "眼睛盯中轴" brand identity 的核心 anchor，archetype 直接从公服 M37Cfg skin 1 抄。一个真 slot 设计师不会为了释放 RTP budget 就把 archetype anchor symbol 砍 54% — 这种 trade-off 应该 escalate paytable 改而不是砍 brand。

**不专业 2 — HIER 完全倒序**: mini 1.14% < minor 6.40% (minor / mini = 5.6×) 违反 universal §1 + Lightning Link 经典 4-tier jackpot UX。玩家直觉是"mini → minor → major → grand 是越来越大越来越罕见"，倒序后玩家会感觉"minor 怎么比 mini 还频繁，UX 烂了"。这是 D 自己在 §3.3 承认的 trade-off，但 trade-off 本身不该接受 — 因为 §1 universal philosophy 是 "ratio ≥ 1.2-1.3x"，**1.05 在 spirit 上还可以拌**，**5.6× 倒序是 universal 哲学的 fundamental 违反**。

**不专业 3 — ge20-100 没达成但仍 ship**: D 自己写 "ge20-100 +10pp 物理不可达，可达 +2.7pp"，user 期望 26.5pp 实际给 19.3pp（gap 7.2pp）。但 D 没用 PHILOSOPHY §10 "穷尽机制空间"原则就 lower goalpost — 没探究改 archetype paytable cap、加新 booster tier、改 evaluation_order 等结构性 fix。

**总评**: **NO-SHIP**。问题不在数字，问题在**为了 hit user 红线砍 archetype brand 信号 + 接受 §1 倒序**。但 v0 比 v3 好：mid-pay 仍 ≥ 8% floor，§14 visual rhythm 仅 mild violate，§12 R1≤R3≤R2 仍 hold。**作为出发点 v0 思路是对的（wider lever + archetype-aware），但需要再 push 找不砍 R2 high7 + 不倒 HIER 的方案**。

### v1 (Designer 第二稿 — strict R2 mini/minor/major only)

**Lever**: 只动 R2 mini/minor/major 3 个 weight，其它 30+ 全锁

**玩家感受**: 物理可达点全都是 baseline ± noise，玩家**完全感觉不到任何变化**（hit Δ 0.22pp、ge1_5 Δ 0.41pp，比测量 noise 还小）。

**不专业 1 — 没尽到 Designer 角色责任**: D 写"strict lever 下没有'推荐点'" + "essentially baseline 微抖动" — 这是诚实但 escalate 不够强。D 应该明确告诉 user "你的 lever scope 跟你的红线在物理上 incompatible"，并**给 user 真实的 lever vs 红线可达性 matrix** — 不是 "在 lever 内找最佳点"，而是 "user 要哪个红线就需要哪个 lever scope"。

**不专业 2 — Designer 不质疑 user 的 lever**: User v1 的 lever scope (只 R2 mini/minor/major) 是 user 第 2 轮愤怒情绪下的反应（"我不是说了只改 mini minor 和 major 妈"），不是 user 经过设计思考后的产出。一个有经验的真 slot 设计师面对 client 这样的 brief 会说"client 这个 lever scope 跟你想要的效果数学上不可能，让我教你为什么 — bar weights 才是 hit 的主 driver，不是 R2 booster"，而不是闷头跑 67k grid 给 user "essentially baseline" 的 5 个候选点。

**不专业 3 — feasibility-first 但 framing 错**: D 跑了 feasibility analysis 是对的，但 framing 是"在你限定 lever 内 best 是什么"。正确 framing 是 "your levers control 8.4% of R2 weight, while hit is driven by R1+R3 paying density which is 60% of total weight — your levers are pointed at the wrong knobs"。

**总评**: **SHIP-WITH-CAVEAT (for v1 specifically: not ship, return to user with clearer escalation)**。v1 数学是对的，但 Designer 没充分发挥角色 — 应该更强势地告诉 user lever-target mismatch，不只是被动报告"infeasible"。

### v2 (Designer 第三稿 — R2 + R1+R3 bar uniform)

**Lever**: R2 mini/minor/major + R1+R3 bar (uniform scale per reel)，wild/high7 仍锁

**玩家感受**: R1+R3 bar 均匀减少 ~17-22pp marginal → 玩家感觉"bar 出得少了，blank 多了"；R2 booster 微动玩家几乎感不到。

**不专业 1 — REC-2 仍未达红线却推**: D REC-2 hit 16.78 (gap 0.78 over upper 16) + ge1_5 14.52 (gap 4.92 over target 9.6) + ge20-100 反向 -3.62pp + HIER 1.05 + §12 R3≤R2 break +8pp。这 **5 项 RED + 没达 user 红线** 同时存在，D 推 "Designer 推荐 (B)" 让 user 放宽 lever — **这等于把烫手山芋扔回 user**。一个真 slot 设计师在这点应该**主动重 framing user brief** — 不是 "选 ABCD"，是"让我告诉你为什么你的 mental model 需要更新"。

**不专业 2 — uniform k1/k3 漏 enumerate per-symbol**: D 把 R1+R3 4 个 bar (1bar/2bar/3bar/7bar) 用同一个 scale k1 调 — 这是 obvious 漏掉的 lever (per-symbol asymmetric cut)。v3 恰恰因为 per-symbol asymmetric (smash 1bar/2bar/7bar 留 3bar) 找到 "feasible" 点 — 但这也是 v3 的灾难根源（见下 v3 评）。

**不专业 3 — Pareto 警惕缺失**: D §10 没主动 enumerate "如果给 tuner per-symbol bar lever 它会不会把某些 bar 砍光"。Pareto trap 是 universal §10 known 风险，D 应该提前在 §10 警告 user "如果放开 per-symbol 我必须加 family-share band 否则 tuner 会砍光" — 但 D v2 没做。

**总评**: **NO-SHIP**。v2 既没达红线又破多条 invariant，没有理由 ship。但 v2 暴露的核心问题被 v3 加倍放大 — D 在 lever 扩张时**没主动加 family-share 守卫**，让 tuner 自由开火。

### v3 (Designer 第四稿 — per-symbol bar smash + HIER 1.05) ⭐ **user 怒点核心**

**Lever**: R2 + R1+R3 per-symbol bar (smash 1bar/2bar/7bar，留 3bar) + HIER 放宽到 1.05

**玩家感受**:

1. **R1+R3 reel 视觉灾难**: R1 blank 34→68.6%，R3 blank 35→69.4%。玩家看 reel 转动 → **2/3+ 时间是空的**。Classic 3-reel slot 应该是"reel 转，看 symbol 排队飞过" — v3 是"reel 转，大部分时间一片空白，偶尔闪过一个 high7 / wild / 3bar"。

2. **机台从 7-family 退化成 3-family**: 玩家 90%+ 的 reel 视觉是 blank + 3bar + high7 + wild。1bar / 2bar / 7bar 几乎消失（marginal < 1%，每 ~130-180 spin 一次），玩家感觉"咦怎么没有 1bar 了？哪去了？"

3. **Brand identity 毁灭**: M37 archetype 是 "IGT Triple Diamond chassis + Lightning Link tier naming fusion" — Triple Diamond 是 classic 3-reel 多 bar tier 的代表。v3 后机台只剩 high7 + 3bar (single bar tier) — 跟 archetype 不是同一台机。

4. **mode 1 vs mode 2/5/7 视觉断裂**: mode 2/5/7 仍是 v3 finalized baseline（R1+R3 bar 49% marginal, blank 21-39%）。玩家在 mode 1 → mode 2 切换瞬间看到完全不同的 reel — "这是一台机吗？"

5. **HIER 几近扁平**: mini 3.51% / minor 3.34% / major 3.18% — 三 tier 视觉上几乎同频，玩家无法区分"mini 是小奖 minor 是中奖" 的 Lightning Link 经典 UX。

**不专业 1 — Pareto trap catastrophic 案例 (教科书级)**: v3 是 `feedback_tuner_pareto_trap.md` 经典 case 的放大版。Memory 警告 "tuner 把关键 family 砍到 0 同时数字 OK"。v3 把 1bar/2bar/7bar 砍到 baseline 5-20%（≈ 砍到 0 在玩家可见度上）只为让 hit/ge1_5 数字达成，**完全无视 brand 信号**。

PHILOSOPHY §10 写：
> "Tune cost function 不能让 optimizer 把关键 family 砍到 0 同时数字 OK"
> "防御：加 family-share 硬约束（band lower bound 强制最小 RTP 比例）或 family-scale 锁某些家族不能砍"
> "**不要 '先做简单的，pareto 出问题再加约束'——上来就加**"

D v3 enumerate per-symbol bar scale ∈ [0.05, 1.0] 直接打开 Pareto trap — 没加 per-symbol family-share floor 守卫 → tuner 必然把 RTP-cost 高 hit-impact 高的 bar (1bar/2bar/7bar) 砍光，留 RTP-effective 的 3bar 撑场子。

**不专业 2 — §14 VISUAL-RHYTHM mandate 完全无视**: PHILOSOPHY §14.5 明确写"必须 iterate 修复，不可'verify GREEN with informational caveat 跳过'"。v3 7 处 §14 violation (mid-pay marginal 砍 80-95% + reel 视觉空 70% + family 退化) — D **没在 design_v3.md 内提任何 §14 check**，整个 §14 mandate 完全被绕过。

**不专业 3 — §12 archetype 契约破坏**: M37 DESIGN.md §2 写 "R1 Blank ≤ R3 Blank ≤ R2 Blank (M37 specific：R2 是 booster reel 必须重 Blank)"。v3 R3 blank 69.4% > R2 blank 49.6%（+19.85pp）— **R2 不再是 highest-blank reel**，M37 archetype "R2 是 booster 中轴 reel" 概念在 marginal 层 fundamentally 颠倒。D self-aware 这点（design_v3.md §5 列了 "❌ break +20pp"）但仍推 ship → 接受度过宽。

**不专业 4 — HIT-MONOTONIC 跨 mode invariant break**: v3 m1 hit 14.42 < m7 hit 14.92 by 0.5pp，**逆 universal §9 mode-pair monotonicity** "m7 hit < m1 hit"。D 在 §5 列了 "⚠ borderline" 但 framing 是 "需 m7 也同步改"。但 user_brief 明确说 **"小改 — mode 2/5/7 不动"** — 接受 v3 = 接受 m7 同步改的额外 scope OR 接受 cross-mode invariant break。无论哪种都不是 "小改"。

**不专业 5 — 没主动跟 user 沟通 trade-off severity**: v3 一句话总结写 "代价：§12-M37 R3≤R2 break +20pp、HIER 1.05 ratio (< 1.3 spec)" — 但完全没写 "你 reel 上的 1bar/2bar/7bar 几乎消失，玩家看到的 reel 跟 baseline 是两台机"。这种 player-facing 影响才是 user 真该决策的事，D 把它隐藏在 "marginal change %" 数字里。

**总评**: **NO-SHIP**。v3 把"满足精确数字"和"slot 设计的物理意义"完全切割了。数字看着对（hit 14.42 / ge1_5 10.86 in box），但**这不是一台 slot machine 了** — 这是一个数字优化结果。这种 output 在任何一家 IGT / Aristocrat / Light & Wonder 的设计 review 都会被资深 designer 直接驳回。User 怒不是过度敏感，是看到了真问题。

---

## 3. User brief reasonability assessment

### §3.1 哪些是真 universal 红线 (不能动)

| User 要求 | universal layer 立场 | Critic 判断 |
|---|---|---|
| **RTP 95% ± 1pp** | universal §B mode 1 contract | ✓ universal 红线，不能动 |
| **mode 2/5/7 不动** | mode 2/5/7 v3 finalized 2026-05-08 真机 5M 验证，paytable 不动 universal §1.1 | ✓ universal 红线 |
| **strip 不动** | strip 改 → mode 2/5/7 rawdata 失效，违反"小改"精神 | ✓ user 红线（不是 universal，但合理） |
| **paytable 不动** | universal §1.1 paytable 永久不变 | ✓ universal 红线 |
| **§12 R1 ≤ R3 ≤ R2 blank** | universal §12 reel asymmetry + M37 archetype | ✓ universal 红线，**v3 break +20pp 是不可接受** |
| **§1 BOOSTER-HIER ratio ≥ 1.2-1.3** | universal §1 | ✓ universal 红线 (1.3 strict 偶可妥协到 1.2，**1.05 是 spirit 之外**) |
| **§9 HIT-MONOTONIC m7 < m1** | universal §9 cross-mode invariant | ✓ universal 红线 |
| **§6 family share vs archetype ±15%** | universal §6 | ✓ universal 红线（**v3 -80 ~ -95% 远超**） |
| **§14 visual rhythm + §15 mid-pay floor** | universal §14/§15 mandate ("必须 iterate 修复") | ✓ universal 红线（**v3 6 处 mid-pay floor break + reel 空 70% 不可 ship**） |

### §3.2 哪些是 user preference (可以试着 push back)

| User 要求 | 类型 | Critic push-back |
|---|---|---|
| **hit 14-16%** | precise red-line | user preference 可商 — slot 设计师会问 "为什么 14-16？是 brief 来自 player feedback (我们 base 太花)，还是抽象 target？" classic 3-reel slot hit 通常 17-22% (per `reference_classic_slot_rtp_distribution.md` 中 IGT RWB 14-18% / Blazing Sevens 类 17-19%)。**14-16 是合理 band 但偏低**；如果 user 真要 14-16 需要接受 R1+R3 bar marginal ~30% 而非 49% (≈ ±15% archetype 容差边缘) |
| **ge1_5 -10pp** (19.6→9.6pp) | precise red-line | **不合理** — D 在 v3 §8 计算 ge1_5 absolute floor 是 4.3pp (uncuttable: pid 9 mult 1× + pid 6 mult 2× + 高7 mult 4× via wild)。User 要 9.6pp 物理可达，但要把 cuttable mass 砍光 (14pp cuttable - 4.4pp 留 = 砍 10pp) **必然破坏 R1+R3 bar 主供给**，连带破坏 archetype。real slot 设计师会说 "你想砍小奖砍到 9.6pp 必然换来 reel 半空 — 你确定？" |
| **ge20-100 +10pp** | TBD → directional | **不可达 + 不合理**. D v0/v1/v2/v3 全部独立 verify ceiling 是 ~19.3pp (+2.7pp from baseline 16.5)。User 想要 +10pp (→ 26.5pp) 数学上要求 R1+R3 bar paying density 高（hit ↑）+ booster heavy → 跟 hit 14-16 红线**直接冲突**。real slot 设计师会说 "你要 ge20-100 +10pp 是 mid-heavy 现代 video slot 的味道，不是 classic 3-reel 的味道；你机台 archetype 是 Triple Diamond，要 mid-heavy 该换 archetype 或加 feature 层" |
| **"小改"** | qualitative | **跟其它红线 inconsistent** — "小改" 意思是不改 strip + 字节级最小动手，但 hit -6pp + ge1_5 -10pp **物理上需要大幅 R1+R3 paying density 重排**，这不是 "小" 改 |
| **lever scope: R2 mini → minor/major** | directional hint | user 第 1 轮直觉错 — R2 mini/minor/major 只控 8.4% R2 weight，hit driver 是 R1+R3 bar。user 用了 "?" 暗示自己不确定。real slot 设计师此时应该**主动教 user lever physics**，不是被 user lever scope 限定后闷头跑 grid |

### §3.3 "小改"直觉的真实含义

User "小改" + "只改 mini minor 和 major" 在 brief 第 1/2 轮 → 我推测 user **mental model 是 "调 R2 booster 概率就能调整 bucket 形状"**。这是错的 mental model:

- R2 booster 总 marginal 只有 8.5%，影响 hit 上限 +/- 0.5pp
- bucket ge1_5 主供给是 pid 7 (any-bar 1×) + pid 9 mult 2× (mini-alone fallback)，前者完全由 R1+R3 bar 控
- ge20-100 主供给是 (R1+R3 bar/high7 三连) × (R2 booster) — 砍 R1+R3 bar 同时砍 ge1_5 和 ge20-100

**Real slot 设计师对 user "小改" 直觉的翻译**：
> "你想要 the casual feeling of a few small dial adjustments — 实际上你的目标 (hit -6pp, ge1_5 -10pp) **不是小改，是 mid-major 重塑**。改 hit 6pp + 砍 bucket 10pp 在 classic 3-reel 机台是 archetype 重新设计 — 这台机会 feel 不一样。"

User 没意识到自己的 numerical target 和 "小改" 直觉是 inconsistent 的。这是**典型 client brief gap** — 数字精确但缺 mental model 校准。

### §3.4 ge20-100 +10pp 不可达 — 谁负责？

| 候选 | Critic 判断 |
|---|---|
| **Philosophy 锅** | NO — philosophy §6/§10/§11 都警告这种 trade-off |
| **Paytable 锅** | PARTIAL — M37 paytable cap 1000× 限制了 ge20-100 桶上限。如果加 ge200 桶的 booster mult 上限 (如 grand ×200 而非 ×100) 可释放 mass 到 ge200+。但 paytable 不动是 universal §1.1 |
| **Lever scope 不允许** | PARTIAL — strip 不动 + mode 2/5/7 不动确实限制 lever，但即使全放开 v0/v1/v2/v3 都没能 ge20-100 +10pp |
| **真原因**: physics 锅 (paytable structure × hit constraint × bucket math) | ✓ — 在 hit 14-16% 约束下，ge20-100 桶 mass 物理上限 ~19.3pp。要 +10pp 需要 hit 抬到 ~25% (paytable allowed) 或加 paytable 新 booster mult tier |

**Critic 立场**: ge20-100 +10pp 是 user 想要"现代 mid-heavy video slot 体验"塞进"classic 3-reel 1000× cap 机台"的不兼容期望。Designer 没责任 — 在 lever scope + paytable cap 双锁下不可达是物理事实。User 应该接受 directional 而不是 precise 红线，**X agent 早应该在 v0 时 catch 这点 escalate user**，不是让 D 跑 4 轮才发现。

---

## 4. X 推荐路径

> 不允许 "选 A / 选 B" 选项题。不允许 "user 必须放弃 X" 。允许直接说 "v3 不该 ship / 哪种 trade-off 真的不能接"。

### §4.1 v3 ship 还是 no-ship？

**v3 NO-SHIP — 不可妥协**。理由：

1. **§14 VISUAL-RHYTHM 是 universal mandate** ("必须 iterate 修复，不可标 informational 跳过") — v3 7 处 violation
2. **§15 MID-PAY-VISIBLE-FLOOR 是 universal hard red** — v3 6 处 violation
3. **§12 R3 ≤ R2 blank M37 archetype 契约 fundamental break** — v3 R3 blank > R2 blank by +19.85pp，机台 identity 颠倒
4. **§9 HIT-MONOTONIC universal invariant break** — m1 hit < m7 hit by 0.5pp
5. **§6 archetype share ±15% 5+ 处 violation** — R1+R3 1bar/2bar/7bar 砍 80-95%

v3 数字看似 OK (hit 14.42 ✓ / ge1_5 10.86 ✓) 但**作为 slot machine output 是不合格的**。在任何 IGT / Aristocrat / Light & Wonder 的设计 review 都会被直接驳回。User 怒**完全合理**。

### §4.2 v0 是否可重启？

**v0 可重启 with 修订**。理由：

v0 的核心思路（"wider lever，砍 R2 high7 + 改 HIER + 改 R1+R3 bar"）方向上合理 — 跟 v3 比 v0 有这些优势:

| 维度 | v0 | v3 |
|---|---|---|
| R1+R3 bar marginal 砍 | -35% uniform | **-80 ~ -95% per-symbol** |
| Mid-pay floor 8% | **PASS** (R1+R3 bar all > 8%) | **6 处 FAIL** |
| R1+R3 blank | 45.5% / 46.5% | **68.6% / 69.4%** (reel 半空) |
| §14 visual rhythm | YELLOW (mild) | **CATASTROPHIC RED** |
| §6 archetype share | RED (R2 high7 -54%) | **CATASTROPHIC RED** (multiple -95%) |
| §12 R3 ≤ R2 blank | GREEN | **RED +19.85pp** |
| §9 HIT-MONOTONIC | GREEN | **RED -0.5pp** |
| HIER | RED 倒序 5.6× | RED 扁平 1.05× |

v0 RED 1 个（R2 high7 砍 54% violate §6），v3 RED 7+ 个。v0 mid-pay/visual/§12/§9 都 hold。

**v0 重启 with 修订**:

修订 1: **R2 high7 cut 减至 ≤ ±15% archetype 容差** (10.5% → 8.9-12.1%)。释放的 RTP budget 不够? 接受 v0 RTP 92-94% instead of 95.98% — escalate user "你接受 RTP 偏离到 92-94 吗，或者放宽 ge1_5 到 13pp" 而非 9.6pp。

修订 2: **HIER 直接禁止倒序，最多 ratio = 1.2** (universal §1 "GAP ratio ≥ 1.2-1.3x" 中 1.2 是 acceptable floor)。这意味着 minor/major 不能涨太多 — ge20-100 提升能力进一步受限，user 必须接受 ge20-100 directional。

修订 3: **加 family-share 守卫**: R1+R3 每个 bar tier marginal ≥ baseline × 0.85 (per §6 ±15%)。这是 universal §10 推荐的 family-scale 锁。

修订后预期: hit ~16-18%, ge1_5 ~12-14pp, ge20-100 ~17-19pp, RTP ~93-95%。**3 个 user 红线全部部分达成但都不 strict 达标** — 这就是 honest 的答案 — slot 设计在 archetype 约束下不能同时 hit 这 3 个 numerical target。

### §4.3 还有别的 reasonable 路径吗

**路径 R1 (Recommended): "honest target rewrite + v0 修订"**

X 应该跟 user 谈：
1. v3 不 ship（理由如上）
2. ge20-100 +10pp 物理不可达 (4 轮 Designer 独立 verify ceiling ~19.3pp) — 接受 **directional informational**，不当 red line
3. hit 14-16% 在 archetype 限制下需要 R1+R3 bar marginal ~35-40% (-25%~-30% from baseline)，这是 archetype 容差边缘 — 接受 hit 16-18% 留更多 archetype margin
4. ge1_5 -10pp 物理 floor ~4pp 但实际可达点 ~12-14pp (在 hit 16-18% 约束下) — 接受 ge1_5 -5~-7pp 而非 -10pp

**Reasonable target**:
- RTP: 94-96% (hard)
- Hit: **[16, 18]%** (band 比 user 原 [14, 16] 上移 2pp — 给 archetype margin)
- ge1_5 RTP-pp: **[13, 16]** (从 19.6 砍 ~5pp，方向对但不到 10pp)
- ge20-100 RTP-pp: **directional informational [15, 19]** (不当 red line — 物理不可达 +10pp)
- 严守 §6 ±15% archetype share + §14 visual rhythm + §15 mid-pay floor + §12 §9 §1 cross-mode invariants

对应 lever:
- R1+R3 bar uniform scale ~0.75 (baseline 49% → 37%) — 在 ±15% 容差边缘
- R2 mini cut 30% / minor 涨 50% / major 涨 30%（HIER 保持 1.2 ratio）
- R2 high7 不动（保 archetype + §2 brand visibility）
- R1+R3 wild 不动
- 期望: RTP 95 / hit ~17 / ge1_5 ~14 / ge20-100 ~17

**路径 R2 (Alternative): "改 paytable 上锁 — escalate user"**

如果 user 真要 ge20-100 +10pp 不动摇，唯一可能是改 paytable (universal §1.1 forbid)。X 应该跟 user 摊牌：
> "你要的数字组合在当前 paytable + archetype 下数学不可能。要么 (a) 接受 directional ge20-100 + reasonable target (路径 R1) ，要么 (b) escalate paytable change — 加 grand ×200 booster mult 释放 ge200-1000 上限。后者破 universal §1.1，需要 user 拍板架构层改动"

### §4.4 哪些 trade-off 真的不行不能接

**绝对不能接** (universal hard red):
1. **§14 visual rhythm catastrophic violation** (mid-pay marginal 砍 > 50%) — v3 全砍 80-95%
2. **§15 mid-pay floor 6 处违反**
3. **§12 R3 > R2 blank by 20pp** (M37 archetype 颠倒)
4. **§9 HIT-MONOTONIC m1 < m7** (cross-mode invariant)
5. **§6 archetype share > ±15% (single symbol)** — v3 -80 ~ -95%
6. **§8 hit decomposition** 单 pay > 70% — v3 pid 9 接近 70%

**可以接但需 escalate**:
- §1 HIER ratio 1.05 (vs 1.2-1.3 spec) — borderline universal violation，需要 user 明确接受
- §6 archetype share ~±15-25% (mild over) — case-by-case
- ge20-100 +10pp 改为 directional — user 必须接受
- hit 14-16% 上移到 16-18% — user 必须接受
- ge1_5 -10pp 弱化到 -5~-7pp — user 必须接受

**绝对可以接** (合理 trade-off):
- R2 high7 marginal ±10% (in archetype margin) — 没问题
- R1+R3 bar uniform scale 0.70-0.85 (in archetype margin) — 没问题
- HIER ratio 1.2 (vs 1.3) — universal acceptable lower

---

## 5. Process 改进

User 已经抓住 process failure ("设计哲学里没有合理性的评估选项？没有对应的审核 agent？")。Process 答案是 **X agent 应该 spawn 在 v1 之后立刻 catch ge20-100 +10pp infeasibility + user brief inconsistency**，不该让 D 跑 4 轮。

### §5.1 ONBOARDING_PROCESS.md 哪条 process 漏 X gate？

ONBOARDING_PROCESS §5 "11-Stage 工作流" Stage 4 写了：
```
4    D    Design Narrative：综合 R / A / brief / philosophy ...
     X    Pre-Tune Review (一次)：
          - 玩家手感讲得通吗？
          - 数字 cite 哪个 archetype 数据？
          - 跨 mode 叙事自洽吗？
          - §14 audit 全 symbol 覆盖 + 违反点 D 给修复方案?
          - §15 PWDF active optimization 选了哪个 mechanism + 提升量?
          → 不通过回 4 改；通过进 5
```

**Process 写了 X gate，但主 session 跳过了**。具体 gap:

1. **"一次" X gate 不够** — design 多版本 (v0/v1/v2/v3) 时每个新 design 都需要新 X gate，不是只一次。User_brief 4 轮 amendment 意味着 4 个 design version → 应该 4 次 X gate
2. **X gate Trigger condition 不明** — Process 没明确"什么情况 spawn X 才合规"。主 session 4 轮都没 spawn X，说明 process 缺**强制触发条件**
3. **User brief consistency check 没在 X gate 范围** — 现 X gate 反问聚焦 design 是否合理，但**没问 "user brief 本身是否自相矛盾"**。M37 case ge20-100 +10pp 早就该在 v0 X gate catch 但没

### §5.2 主 session 该 spawn X 在哪几个时机？

**改进建议** (待 backport 到 ONBOARDING_PROCESS.md):

#### Trigger condition 1: 每次 user brief amendment 后必须 spawn X

User_brief.md 出现 v1/v2/v3 amendment 段时 = brief 跟之前 design 不兼容 = 必须 X 重审。M37 case 应在:
- v1 amendment 出现时 spawn X (catch "R2 mini/minor/major only 是 8.4% lever — physically incompatible with hit/ge1_5 red line")
- v2 amendment 出现时 spawn X (catch "扩 lever 但仍漏 per-symbol — Pareto trap 警告")
- v3 amendment 出现时 spawn X (catch "Pareto trap 即将爆发 — user 'enumerate 4 维' 表面合理但实际放任 tuner 砍 family")

#### Trigger condition 2: 每个 Designer milestone 必 X review

ONBOARDING_PROCESS §5 现写 "X Pre-Tune Review (一次)"，应改为：

```diff
- X    Pre-Tune Review (一次)：
+ X    Pre-Tune Review (每个 Designer iteration 都必须)：
```

每个 design_vN.md 落地 → 必须 spawn fresh X agent 审，不通过回 4 改。

#### Trigger condition 3: User brief consistency check (新加 X 反问)

X 反问 list 加 4 条:

1. "user brief 里 numerical target (hit/RTP/bucket) 之间数学上是否 self-consistent? 任意两个红线在当前 paytable 下是否互斥？"
2. "user 红线跟 universal §1-§15 哪条 fundamental 冲突？冲突的话该是 user 妥协还是 universal 改？"
3. "Lever scope vs 红线 mismatch: user 限定的 lever 能不能控制 user 想改的 metric driver?"
4. "Pareto trap pre-flight: 这次新放开的 lever 维度有没有家族被砍光的可能？如果有，family-share 守卫加了吗？" (per §10)

#### Trigger condition 4: §14 §15 audit 不是 informational

ONBOARDING_PROCESS Stage 4 已写"§14 audit 全 symbol 覆盖 + 违反点 D 给修复方案" — 但 v3 D 完全没做 §14 audit。建议:

- X gate 必须 **block design 进 Stage 5** if §14 audit 缺失或有未修复 violation
- 不允许 "verify 加 informational" 跳过；必须 iterate fix 或 explicit escalate user

#### Trigger condition 5: Pareto trap pre-flight checklist

每次扩 lever scope (v1 → v2 → v3 的扩 lever 每一步) → X **必须**反问 "新 lever 维度会不会让 tuner 把关键 family 砍到 0?"
- 如果是 — 必须加 family-share / family-scale 守卫 BEFORE 跑 tune
- 不加守卫 = process 失败 = 不能进 Stage 6

### §5.3 M37 specific lesson

M37 case 是 ONBOARDING_PROCESS 第一次真正暴露的 process gap (M15 当时 X 走完整 4-wave review 没暴露此问题，因为 user brief 没多次 amendment)。

具体 process_improvement 应 backport:
1. **§5 Stage 4 改 "Pre-Tune Review (一次)" → "Pre-Tune Review (每个 Designer iteration)"**
2. **§5 加 "X is mandatory after every user_brief.md amendment"**
3. **§5 Stage 4 X 反问 list 加 user-brief-consistency 4 条**
4. **§5 Stage 4 X 加 Pareto-trap pre-flight checklist (5 条)**
5. **§10 ARCHITECTURE/PROCESS 加 commit gate: any design_vN.md 写好后没 mode_N_critique_vN.md (X output) 不能进 Stage 5**

---

## §6. 一行 summary

**v3 NO-SHIP**（catastrophic Pareto trap + §14/§15/§12/§9/§6 多重 universal red 违反 — R1+R3 mid-pay marginal 砍 80-95%，机台 visual identity 毁灭）。**v0 可重启 with 修订**（接受 ge20-100 directional + ge1_5 弱化目标 + 加 family-share 守卫 + R2 high7 cut ≤ ±15% archetype 容差）。**Reasonable target: hit [16,18] / ge1_5 [13,16] / ge20-100 informational [15,19]** — user brief 原 numerical target 自相矛盾（hit 14-16 + ge1_5 -10pp + ge20-100 +10pp 在 paytable+archetype 锁下数学不可能同时达），X 应在 v1 amendment 时立刻 catch escalate 不是让 D 跑 4 轮才暴露。Process 修订: X gate **每个 Designer milestone 必须 spawn**，**每次 user_brief amendment 必须 spawn**，反问加 user-brief-consistency + Pareto-trap pre-flight check。
