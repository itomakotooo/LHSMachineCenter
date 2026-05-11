# M15 user brief (v1.1, 2026-05-11)

> **来源**：v1 内容由 `session_artifacts/M15/00_SESSION_BRIEF.md` §3 落地。
> v1.1 (2026-05-11) 在 Stage 4 review 后 user 进一步澄清，**直接 supersede v1** —— 下游 Agent 读本文件即是最新约束。
>
> 后续 Agent (Designer / Verifier / Critic) 必读此文件，**不读 SESSION_BRIEF 替代**。

---

## v1.1 amendments (2026-05-11, Stage 4 review resolution)

User 在 Stage 4 review 后回答 4 个 follow-up 问题 + 给 mode 2/5/7 新指令。本节是 canonical resolution，下方的 v1 各项已经按这里更新：

### a. Mode 1 brief 第 3 条（正常转 : 赠送 = 50:50）— **放宽**
- 不强制 50:50。当前 v7 的 45.4:54.6 可接受。Designer 不需要为了凑 50:50 加 base 高赔击中率。

### b. Mode 1 brief 第 4 条（P(count_x=1) ≤ 2%）— **放宽**
- v7 的 5% 可接受。不强制压到 2%。Designer 可以保留 v7 `x_count_weights = (5, 40, 40, 12, 3)`。

### c. Mode 2 — **更具体的命中率目标 + bucket 方向**
- **命中率 30%-35%**（v7 是 29.35%，目标基本兑现；微调即可）
- 10×-200× 区间产出**相应增加**（无严格数值约束 — Designer 按命中率派生，最终体验好即可）
- **200× 以上频次 = mode 1**（不增加；这跟 v7 不同 — v7 mode 2 ge200_lt500 = 0.0135% vs mode 1 = 0.0017%，要拉平到 mode 1 水平）
- 整体 RTP ~300%（unchanged）
- 单次不出 1000× 红线（unchanged）

### d. Mode 5 — **允许 base 调整（路径 b）**
- 在 mode 2 基础上，200×以上频次**继续增加**（mode 1 = mode 2 < mode 5）
- **base 允许跟 mode 2 不同**（不再"字节级一致"约束）—— mode 5 正常转里 3 颗 doublediamond / 3 颗 high7 击中率可以高于 mode 2。但 Designer 注意**不要矫枉过正**（玩家叙事是"额外幸运"，不是"完全不同的机器"）。
- 单次不出 1000× 红线（unchanged）

### e. Mode 7 — **MODE7 byte-equal 选项 B（精神等价）**
- 在 mode 1 基础上砍小奖 + 命中率降低（v7 14.92% OK，可以保留或微调）
- **Top Dollar 赠送触发率 = mode 1**（在容差内 — 不要求 R3 topdollar 位置权重字节级 = mode 1；允许 mode 7 R3 上 topdollar 权重数字微调以匹配触发率）
- **大奖（pay_id 1 / 2 / 21）击中率 = mode 1**
- 波动性自然增加（接受，是 cut 的副产物）

### f. v1 第 5/6 条不变
- 全 mode 单次不出 1000× 红线
- 全 mode jackpot 任一 reel marginal ≤ 0.6%

---

## v1.2 amendments (2026-05-11 wave 3 resolution)

### g. CV 精确数值约束 **取消**
- 之前 brief 第 2 条写的 "base CV [3, 5] / feature CV [1, 2]" 是**感性描述**（"低波动 / 中波动"），不是精确数值约束。
- v1.1 的 [3,5] / [1,2] band 不再当 red line 用。
- 实际落点跟 archetype + 其他约束自然落，CV 在 verify.py 走 **informational metric**（监控用，不当 RED line）。
- 影响：D v2 标的 m1 base CV "STRUCTURAL near-miss"（6.086 vs [3,5]）→ 转化为 informational，进 Stage 5 / 6 不当 blocker。

### h. paytable **永远不改** — universal rule (cross-machine)
- M15 + 任何未来机台都不允许动 paytable（spec.json `pays` block）。
- 影响 mechanism 空间分析：D 之前列的"4 类机制"中**第 4 类（paytable restructure）永久排除**。后续 V / X / 任何 agent 跑"穷尽机制空间"判定时，3 类机制全 blocked 就直接 escalate user，不再考虑第 4 类。
- reel strip 的修改（§13 blank-flank 等）不算改 paytable —— strip 是另一个文件，paytable 是 `spec.json`。这条规则只锁后者。
- 这条规则**抬升到 cross-machine universal**（不止 M15）—— 应同步进 ONBOARDING_PROCESS.md §1 input contract 或 §2 truth order。

---

---

## mode 1 核心诉求（其他 mode 衍生）

1. **命中率 (hit_rate) ∈ [15%, 18%]**
   当前 v7：19.31% (超 1.31pp，需向下优化)

2. **波动性**
   - normal spin 部分：低波动 (base CV ∈ [3, 5])
     当前 v7 base CV：5.77 (中-高，需向下优化)
   - feature 部分：中波动 (conditional feature CV ∈ [1, 2])
     当前 v7 feature CV：0.74 (低，需向上优化)

3. **base : feature RTP 比例 = 50 : 50**
   当前 v7：45.4 : 54.6 (feature 超 4.6pp)

4. **feature 体验**：count_x = 1 (单牌 reveal) 概率 ≤ 2%
   当前 v7：5%

5. **避免 1000× bet 以上奖**（跨所有 mode）
   当前 v7：mode 1 P(R≥1000/spin) = 1/8.3M ≈ 0 ✓ 已达成
   (mode 5 也维持避免：1/3.6M ✓)

6. **jackpot symbol 击中率正常偏低**（universal across mode 1/2/5/7）
   当前 v7：mode 1 jackpot R1 0.08% / R2 0.53% / R3 0.14% ✓ 已偏低
   保持任一 reel marginal ≤ 0.6%

---

## 衍生关系（universal §C/D 强制）

- mode 7 = mode 1 砍小奖 freq (per philosophy §4)，feature_params 字节级 = mode 1
- mode 2 = mode 1 lucky 派生，hit ×1.5-2 (不是 ×3)
- mode 5 base = mode 2 base 字节级一致；feature 加强 (EV 升、count_y / x_value_weights 调；不可破"避免 1000+"红线)

---

## 默认决策（Designer 不需问 user）

- **archetype**: Top Dollar 1-line ($1 denom ~92% RTP) + Double Top Dollar ×2 multiplier 元素混合 (跟 v7 保持)
- **cherry-1 1× anywhere** 是 archetype 必然，**接受**（不动 paytable）
- **accept threshold**: 当前 v7 flat 40 保持（不恢复 graduated）
- **§7 顶奖阶梯例外**：M15 走"密集 mid-high 替代稀有 top"路线，DESIGN.md 写明 deviation；不动 universal philosophy
- **3-wild 200× cadence**: 保持 v7 (~1/60k)，不主动拉到 1/15-30k

---

## 留空给 Designer 派生 (cite archetype URL or §条款)

- bucket distribution per mode (low/mid/high/top RTP %)
- per-pay_id frequency band
- family RTP share band
- trigger rate (受 brief #3 RTP 50:50 + Designer 选 feature EV 影响)
- per-hit avg win

---

## 红线（防 Claude-self-loop）

- 不读已删的旧 MODE_DESIGN.md / NOTES.md（从 git history 翻出也算 contamination）
- 不抄 sister machine target 数字（M1 / M37 / M279 paytable 结构不同）
- D 的每个数字必 cite (R archetype URL / A 数据 / brief 项 / § 条款)，否则不进 design 文档
- V 红线必逐条 cite PHILOSOPHY §；不能 Claude 自定 cap
- inner loop 5-iter cap；超出 escalate user
- pareto trap: 连续 3 iter 同 RED → 回 Stage 4 改 design intent，不死 tune

---

## 完成标志（per SESSION_BRIEF §5 末段）

- ✓ 4 mode 全 verify GREEN (含 cross-mode invariants)
- ✓ 4 mode analytic vs Monte Carlo 在 ±2σ
- ✓ user brief 6 项全部兑现（hit ∈ [15,18] / base CV ∈ [3,5] / feature CV ∈ [1,2] / 50:50 split ±5pp / count_x=1 ≤ 2% / P(R≥1000) 全 mode ≤ 1e-5 / jackpot ≤ 0.6%/reel）
- ✓ ONBOARDING_PROCESS.md §11 进度表 M15 标完成 + commit SHA
- ✓ commit 通过 `.claude/hooks/verify-commit-msg.py` 4 段格式
- ✓ push origin/collab/dev 成功
