# M15 — User explicit hardlines

> **Contract**: user-explicit hard constraints ONLY. Agent cannot add boundary values OR rules of its own.
> Hard constraints include **rules** (user-stated qualitative invariants) AND **boundary values** (user-stated quantitative).
> Agent may use philosophy/archetype as direction (not hard). May ask user to relax user-stated boundary when iteration hits structural wall. Cannot ask about anything user hasn't said.
> Boundaries accumulate during iteration. Relaxations are explicit user statements.
> Stored verbatim, not processed.

---

## Universal rules (cross-mode, qualitative)

- **Paytable永远不改** — `slot_designer/machines/M15/spec.json` `pays` block byte-equal. (cross-machine rule, user 2026-05-11)
- **避免 1000× bet 以上奖**（跨所有 mode）—— qualitative, user_brief #5
- **Feature shape locked** —— feature trigger × EV balance + 4-round selection mechanic = archetype + philosophy §7 anchored, user 2026-05-11 confirmed cannot propose to change
- **Feature trigger 算 hit_rate**（session-centric semantics, user 2026-05-11 correction）

## Universal hardlines (cross-mode, quantitative)

- Jackpot symbol marginal ≤ 0.6% per reel (user_brief #6)

## Mode 1 hardlines (only mode user has explicitly constrained)

### Hit / RTP
- Hit rate ∈ [15%, 18%]（session-centric, includes feature trigger）
- Total RTP ∈ [94%, 96%]

### Reel structure
- R1 blank marginal ∈ [30%, 40%]（user v10 directive）

### Bucket distribution (v8 directive 2026-05-12: 全部放开 bucket 数字 band)

User 2026-05-12 explicit: "放开所有rtp分桶的限制。只满足reel体验和rtp构成的合理性。"

**所有 ge*_lt* RTP bucket bands 全部放掉**（不再有 g15/g510/g1020/ge20_lt50/ge50_lt100/ge100_lt200/ge200_lt500 数字约束）。

替换为两条 qualitative direction：

1. **Reel 体验合理**（visual experience）—— 视觉节奏、family 平衡、不许单一 family marginal 或 RTP share 极端 dominant。Classic bar slot archetype 各 symbol family（cherry / 1bar / 2bar / 3bar / high7 / wild）都得视觉上可见、玩家能记住。

2. **RTP 构成合理**（payout shape composition）—— normal spin 各 pay 都得发奖（不能 bar3_pure 1/16k 这种 cosmetic 死 pay）；bar hierarchy classical (P(bar1_pure) > P(bar2_pure) > P(bar3_pure) 频率上)；wild_pure cadence 经典 archetype band；avoid 1000× bet+ 顶奖；jackpot 1000× 不动；保留 R1 blank 与 hit/RTP hardlines。

**Feature 部分不变** (feature_params byte-equal v9，trigger × EV × 4-round mechanism 都锁)。本次只重新设计 normal spin (per-stop weights for non-feature pays)。

## User explicit relaxations (NOT hard anymore)

- **CV** (base / feature) → **informational**, was [3,5]/[1,2] band (user §g 2026-05-11)
- **base : feature split** → **relaxed**, was 50:50 hard (user §a)
- **P(count_x = 1) cap** → **relaxed**, was ≤2% (user §b)
- **Cherry §2 archetype visibility floor** → **relaxed for M15** (user option C 2026-05-11)

---

## Change log

- 2026-05-11 v1 extract from user_brief.md v1.2
- 2026-05-11 v2 added v10 directives (R1 blank + bucket -10/+5/+5 absolute)
- 2026-05-11 v3 user-explicit corrections:
  - Removed mode 2/5/7 hardlines（user 2026-05-11: 不是 user-stated, agent-derived from mode 1 + framework, 应该从 mode 1 + philosophy 推）
  - Removed quantification "P(R≥1000)/spin ≤ 1e-5"（user 2026-05-11: 没说过；保留 qualitative "避免 1000×+"）
  - Added rule "Feature shape locked"（user 2026-05-11: 应当哲学框架自己判断不该问）
  - Updated mode 1 bucket distribution v11 directive: ge1_lt5 ∈ [10, 12]pp / mid soft / 20+ preserve / 1-20 sum ~30pp / "rtp 占比由 normal spin + feature 共同构成"
  - Clarified "hard constraints 含 rules 不只数字"
- 2026-05-11 v4 user 选 C + clarify tolerances:
  - sum_1_20 ∈ [28, 32]pp（user 2026-05-11: 总量 ±2）
  - 20+ each bucket v9 ± 5pp（user option C 2026-05-11）
- 2026-05-12 v5 boundary redesign after v4 infeasibility proof:
  - ge1_lt5 upper bound 12 → **15**（user 2026-05-12 confirmed: bar_mixed_pure 在 paytable line_3_group 下结构性贡献 ≥5pp g15，加 cherry-1 任何 design 都 ≥10pp，原 12 上界几何不可行）
  - sum_1_20 upper bound 32 → **36**（user 2026-05-12 confirmed: 让 g510/g1020 充分填 bell-shape peak）
  - Bell-shape direction (qualitative invariant) 加入: normal spin RTP 不许 g15 dominant；peak 应在 5-15×（user 2026-05-12 给的 design intent）
- 2026-05-12 v6 qualitative direction 校正（v5 数字 widening 保留不动）:
  - 替换 "Bell-shape peak 5-15×" 为 "g15 不许是 g15/g510/g1020 三者最大"
  - 原因：V/X review FINAL_E 发现 strict peak 5-15× 要求 bar1 R1 34%/R2 30%/R3 25% 一家独大、cherry/bar2/bar3 等小奖死光，跟 classic bar slot archetype 不一致
  - User 选 B + "避免 1-5 最大"：放 bell-shape strict 但 g15 不能 dominate
- 2026-05-12 v7 second direction 校正（数字 hardlines 仍不动）:
  - D 第二轮设计 ZZZ：bar1 share 仍 44% 因为 g15 < g510 强制几何
  - User 反馈："不能接受 bar1 独大"
  - 主 session 数学分析：g15 < g510 + 14 hardlines 联合下 bar1 share ≥ ~38-40% structural floor
  - User 选 B（drop "g15 not max" direction）+ "尽可能克制 g15" + 隐含 bar1 family share ≤ ~30%
  - 替换 v6 direction 为："尽可能克制 g15 靠 [10, 15] 下界 10"
- 2026-05-12 v8 全部 bucket band 放开（major direction shift）:
  - D 第三轮 PPP_v20：bar1 share 26.6% ✓ 但 high7 share 31.5% 占领 dominant 角色
  - X verdict: dominance shape 没解决，只是从 bar1 平移到 h7（over-cap 393% vs 之前 349%）
  - User 反馈："完全不行。换思路重新来过。保留feature配置不变，只变normal spin。放开所有rtp分桶的限制。只满足reel体验和rtp构成的合理性。"
  - 删除 ge*_lt* 所有 6 条 bucket 数字 band（g15 / sum_1_20 / ge20_lt50 / ge50_lt100 / ge100_lt200 / ge200_lt500）
  - 删除 v5/v6/v7 关于 g15 / bar1 dominance 的所有 directives
  - 新约束：reel 体验合理 + RTP 构成合理（qualitative，agent 用 philosophy + archetype 判断）
  - 保留 hardlines：paytable、feature shape、total RTP [94,96]、hit [15,18]、R1 blank [30,40]、jackpot ≤ 0.6%、避免 1000× bet+
  - 操作范围：本轮只设计 normal spin per-stop weights，feature_params 不动
