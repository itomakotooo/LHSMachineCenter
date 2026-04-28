# Slot Designer — 工作流（commit 前 self-adversarial review）

> **核心问题**：Verify 是我自己设计的，盲点系统性。Verify GREEN 不等于 design done。
>
> **解法**：每次 commit 前，假装 user 站在面前会反问什么——把 user 角色 internalize，自己先反问自己 3-5 轮，主动 iterate 到无可挑剔再 commit。
>
> **历史教训**：M37 v1→v5 共 5 次 commit，前 4 次都是 user 看一眼就指出问题。每次都是"verify 全绿就交付"心态。User 反问能发现是因为 user 用 first principles 看实际数字；我没。

---

## 1. 工作流五步（每次 commit 前必走）

### Step 1：跑 verify，全绿不算完

Verify 是我设计的，只检查我想到的东西。绿了只意味着"我没漏我自己列出的"。

**别停在这。**

### Step 2：dump 实际数字，眼睛过一遍

不只是 summary。把每条 reel 每家族 density、每 pay_id 频率 + RTP、每 mode 跨 mode 对比都打印出来，逐项扫。

**必 dump 项目**：
- 每 mode × 每 reel × 每 family 的 density
- 每 mode 每 pay_id 频率（1 in N spins）+ RTP 贡献
- 跨 mode 对比表（m1 vs m7 vs m2 vs m5）
- Hit decomposition（每 pay 占 hit rate 的 %）
- 顶奖 freq 跨 mode escalation
- **每条 reel 的 blank weight + total weight + non-blank density** —— 看 R1/R2/R3 间是否有跨数量级差距，差距是否有结构性解释

不"看了 verify 绿就过"，而是 **看实际数字** 是不是符合直觉，每个跨 reel / 跨 mode 大差异都问清"为什么"。

### Step 3：adversarial 反问自己（关键）

进入"对面是 user / slot designer 专家"心态。问 3-5 个问题，自己先答。问题模板：

- "如果 user 现在看这个数字，第一反应会问什么？"
- "我说'结构性 trade-off'是真的结构性，还是我懒得 fix？"
- "verify 没 cover 的盲区有哪些？设计 first principles 哪条没主动检查？"
- "这个 commit 之前 N 次 commit 都被打回，这次 user 会怎么挑刺？"
- "如果一个真 slot designer 看，会觉得不专业的地方是什么？"

每个问题答出来。**答不好就回 Step 4 修，不直接 commit**。

### Step 4：发现问题立即 iterate（不留 TODO）

每个 adversarial 反问发现的问题：

- 真 bug → 立刻 fix
- 结构性 trade-off → 验证是不是真"结构性"（试一个 fix 看能不能修；修不了才认）
- verify 漏掉的 → verify 加新硬约束，下次堵住
- 设计 intent 不清 → 回 DESIGN.md 写清楚

不要写"这是已知问题，下次修"——这次就修。

### Step 5：commit message 必含 self-critique 段

格式：

```
## Self-critique (adversarial review)

如果 user 站在我面前会问/挑什么：
1. ...
   答：...
2. ...
   答：...

剩余 acceptable structural caveats（验证过真改不了）：
- ...
- ...
```

写不出 self-critique 段 = 没真做 adversarial review = 不能 commit。

---

## 2. Adversarial 反问思路库（启发，不是清单）

每次 commit 前用这些思路 stress-test 自己。具体每机台 specific 的内容在该机台 DESIGN.md。

### 2.1 设计 intent 是不是真的实现了

- 看 commit 说"mode 7 砍小奖 + 大奖不动"。**真的吗**？打 per-pay 表，每条对照设计 intent。
- 看 commit 说"super-lucky 顶奖密集"。**真的吗**？顶奖 freq 跨 mode 对比给数字。
- 设计 intent 写在 README/DESIGN.md，**实际数字 一对一 verify**。

### 2.2 first principles 主动扫一遍

slot 设计 first principles 见 `DESIGN_PHILOSOPHY.md`。每次 commit 前过一遍清单，每条问"我有没有主动 check"。

### 2.3 verify 自己有没有盲区

- "verify 类别有没有 cover 这次设计变化点？"
- "之前 user 指出的问题，verify 现在能 catch 吗？没能 → 加新类别"
- "我有没有为了让 verify 过 而 relax verify cap？relax 之前先确认是 structural"

### 2.4 数字直觉 check

- 每条 reel 上每家族 density 看一眼：跟同行业典型分布像不像？
- per-pay 频率：是不是某个 pay dominated（单一 pay 占 hit 60%+ 警惕）？
- 跨 mode 数字趋势：合不合 player narrative？
- weight 是不是有顶死 cap（顶死 = optimizer 想 push 但被卡 = 设计漂）？

### 2.5 "结构性"是不是真的

每次说"这个是结构性 trade-off acceptable"前，先问：

- 真试过 fix 吗？
- fix 是不是改架构层面的事（spec / paytable）？
- 跟 commit 说的 design intent 是不是矛盾？矛盾就不是"acceptable"，是 design 本身有问题。

如果只是因为 cost function 配不平就说 structural，那是借口。

---

## 3. 反例（什么是不该做的）

### 反例 1：M37 v3 commit message 摘录

> "verify 11 categories ALL GREEN. Commit ready."

问题：
- 没 dump per-pay 表
- 没 adversarial review
- 没问"verify 真覆盖了吗"
- 结果：user 拉 rawdata 发现 1bar 死、grand alone dominant

### 反例 2：M37 v4 commit message 摘录

> "Mode 7 pay_id 8 ratio 1.45x — structural rise (R2 booster reel can't fully dilute)"

问题：
- 说"structural"但没真试 fix（其实可以放宽 blank cap）
- 没 dump booster hierarchy（user 看了发现 mini < major 倒置）
- 结果：user 用哲学 review 指出 5 硬伤

### 反例 3：每次 commit 都依赖 user 校验

模式：
1. 我说 GREEN
2. User 看 → 找出问题
3. 我修
4. 我说 GREEN
5. User 又看 → 又找问题
6. ...

这意味着 user 在帮我跑 review。User 时间不该用于此。我应该 internalize user 的视角主动反问。

---

## 4. 长效改进

### 4.1 verify 是 living document

每次 user 指出 verify 漏的问题：
1. 当次修
2. **加 verify 类别堵住，下次再漏不可能**
3. 跨机台通用的（如 hierarchy）放 `DESIGN_PHILOSOPHY.md`，每个机台 verify 都引用
4. 单机台 specific 的（如 M37 的 booster_R2 cap 数字）放该机台 verify 配置

### 4.2 commit gate

PR 自描述要回答：

- [ ] verify GREEN
- [ ] dump 数字眼过
- [ ] adversarial 反问 ≥ 3 个，写在 commit message
- [ ] 每个"structural"caveat 验证过真改不了

任何一条不勾，不 commit。

### 4.3 历史教训累积

每次 user 指出的盲点写到 commit message + 这份 WORKFLOW.md 反例区。下次新机台先读反例。

---

## 5. 反问思路 vs 设计哲学的边界

- **WORKFLOW.md**（这份）：跨机台通用的 **过程/方法/态度**。"怎么做 review"。
- **DESIGN_PHILOSOPHY.md**：跨机台通用的 **slot 设计 first principles**。"设计的硬规则"。
- **每机台 DESIGN.md / MODE_DESIGN.md**：单机台 **specific 数字 / paytable / 跨 mode 关系**。
- **每机台 verify_<M>_design.py**：单机台 **硬约束代码**。

这份只写过程，不写 slot 知识细节。
