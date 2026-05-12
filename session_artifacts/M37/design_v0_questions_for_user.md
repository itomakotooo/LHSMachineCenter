# Design v0 — 给 user 的拍板问题（玩家语言）

> Designer 已 fresh-context 独立 verify。3 个拍板点，请在主 session 选 / amend，主 session 接手再继续。

---

## Q1：20-100 倍中奖区，物理上只能升一点点

你说"砍掉 1-5 倍的占比 10%，投放到 20-100 倍"。

**Designer 实测后告诉你**: 4000 次不同的 lever 组合搜索，**20-100 倍区最多只能从 16.5% 升到 19.3%**。你期望的 +10pp（升到 26.5%）做不到。

**原因（玩家语言版本）**:

中轴 R2 的 minor 五倍 wild 是唯一干净增加 20-100 区的家伙。但 minor 单独出现（旁边两轮不中）时落 5×，落在 **5-10 倍**桶，不是 20-100。要让 minor mass 集中落 20-100，需要 R1+R3 两边经常给牌——但那样总中奖率就上去了，跟你的 14-16 红线冲突。

所以从 1-5 倍砍掉的 10pp **实际落地处**：

| 桶 | baseline | design v0 |  | 解释 |
|---|---|---|---|---|
| 1-5 倍 | 19.6% | **9.5%** | ✓ 红线达成 | |
| **5-10 倍** | 14.0% | **29.6%** | ← 大头流到这 | minor 单独旋出（无配套）大量落 5× |
| 10-20 倍 | 23.4% | 19.0% | 略降 | |
| **20-100 倍** | 16.5% | **19.3%** | ← 只升 2.7pp | 物理上限 |
| 100-200 倍 | 14.8% | 13.4% | 略降 | |
| 200+ 倍 | 7.1% | 5.0% | 略降 | |

**3 个选项，请选一个**:

- **(A) 接受落 5-10 倍**: "1-5 倍砍了 10pp，主要流到 5-10 倍。Story 是 '小奖减少、中奖升段'，跟你期望的 'mass 重分布' 精神一致，只是落地点不同"
- **(B) 调低 ge1_5 砍幅，保 20-100 升幅**: 砍 ge1_5 只 -3-4pp（不是 -10pp）。这样 minor 不用 boost 这么多，spill 少。但你说"-10pp"也是 precise red line
- **(C) 改 paytable**: M37 paytable 锁，不能改。这不是选项，列出来只为说明已穷尽

---

## Q2：mode 1 改了 mini → minor，mode 7（运气差档）要不要也跟着改？

**背景**: M37 设计 contract 里有条 "MODE7-LOCK" 规则：mode 7 (运气差) 的中轴 booster 频率应跟 mode 1 一致——只砍 R1+R3 小奖，不动 R2 booster 出场频率。

**这次 mode 1 改动**: mini 从 3.7% 降到 1.1%，minor 从 2.7% 涨到 6.4%。R2 booster 总频率没变（都是 ~9.2%），但 mini/minor 比例反转了。

**两个选项**:

- **(a) Mode 7 跟着改**: 一次 commit 改两 mode weights，mode 7 重 verify。**优点**: "运气差和标准模式 booster reveal 频率一致" narrative 保住。**代价**: 工作量加倍，要重新跑 mode 7 verify 全套
- **(b) MODE7-LOCK 容差放宽**: 接受 mode 1 vs mode 7 各 tier marginal 差最多 3 倍。**优点**: 单 commit 只动 mode 1。**代价**: 失去 "cut mode = 数值差异在小奖、booster 完全相同" 这条干净 narrative

---

## Q3：中轴 R2 上 high7 锚顶奖会变稀

**背景**: 现在 R2 上有 high7 marginal 10.5%，是 archetype（IGT 公服 baseline）的真值。它的作用：

1. 喂 (high7, high7, high7) 这条 3-of-a-kind 路径（×10 base）
2. 喂 1000× 顶奖路径 (high7, grand, high7) 的概率（需要 R2 的 high7 存在做 substitute）

**Design v0 把 R2 high7 砍到 4.8%**。这是为了释放 RTP budget 给 minor。

**影响**:

- R2 上 high7 频率从 1/10 spin 看到一次，降到 1/20 spin 看到一次（视觉上 high7 在中轴的出现率减半）
- 1000× jackpot 频率：**几乎不变** —— design v0 估计 1/34k spins，baseline 1/37k spins。grand × R1/R3 high7 substitute 路径仍主导
- 3-of-a-kind high7 hit 频率：约降 35%（baseline 0.5% → design 0.3%）

**3 个选项**:

- **(α) 接受**: "中轴看到 high7 的次数减半，但顶奖（1000×）频率不动，赢 minor 的次数多了。可以接受"
- **(β) 保 R2 high7，降低 minor 涨幅**: 那 ge20-100 升幅会更小（可能 +1-2pp 而非 +2.7pp），其它数字大致维持
- **(γ) 改 archetype**: M37 archetype（IGT Triple Diamond + Lightning Link 命名）已 ship，改这个属于 v3 finalized 之后的大动，请确认是否要这么大改

---

## TL;DR — 推荐组合

如果你嫌选项太多，Designer 推荐：

- **Q1 → (A)** 接受落 5-10 倍（"小奖减少、中段升段" 玩家叙事仍 valid）
- **Q2 → (a)** Mode 7 跟着改保 MODE7-LOCK（一次工作量大但不破 narrative）
- **Q3 → (α)** 接受 R2 high7 砍半（顶奖频率不动，视觉变化玩家可接受）

Designer 在 §3 / §4 / §5 / §6 写的 target marginal + verify band 都按这套推荐组合算的。你选别的，告诉主 session 哪个 amend，主 session 会重新跑 tune target。
