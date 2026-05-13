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
- **每条 reel 的 symbol 顺序排布**（PHILOSOPHY §14.5）—— 用眼/script 扫每条 reel 的 non-blank 序列，问"哪两段同 family 连成长段？同 symbol 重复实例是否散开？顶奖 symbol pair 间距合理？" 不能只看 §13 blank-flank 0 violations 就过 §14
- **PWDF 表 per top symbol per reel**（PHILOSOPHY §15.9）—— `p_window / p_mid` 算 PWDF；问"这是 strip 自然 baseline 还是 mechanism B 主动 lift 之后？" Passive measure 不算达成 §15

不"看了 verify 绿就过"，而是 **看实际数字** 是不是符合直觉，每个跨 reel / 跨 mode 大差异都问清"为什么"。每个 §14 / §15 dump 都要主动跟 PHILOSOPHY §14.5 / §15.9 mandate 对照（"如果 audit 说违反，我有没有 propose 修复方案？还是在拖？"）

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

### 2.6 Boundary discipline — Boundary Contract 模式

**Stage 3.5 之后 user 不再过程介入**。所有边界值在 Stage 3.5 由全 team 协商一次性
定下，写入 `machines/<M>/BOUNDARY_CONTRACT.md`，user sign-off frozen。Stage 4-10
全部 agent 把 contract 当 single source of truth。

**Contract 4 层**（详见 `slot_designer/templates/BOUNDARY_CONTRACT_TEMPLATE.md`）：

- **§1 user-stated qualitative direction** — user_brief 原文摘录，无翻译
- **§2 team-translated quantitative bounds** — D 把每条 §1 翻译成数字 band + cite 来源 + feasibility 验证。**这是 verify.py 红线的唯一合法来源**
- **§3 physics floor** — paytable 数学限制，非 negotiable，team 透明告知 user
- **§4 informational metrics** — 报告 dump 不当红线，user 看 final report 自检用

### Stage 4-10 agent **不允许**（合 contract 后铁律）

- **引入 contract 没说的数字** — verify 红线 / tune cost / target band 必须 trace 回 §2 或 §3。
  自造数字（"我推这个 ≥ 2% 应该合理"/"我加 §14 R1 single-symbol ≤ 22% cap"）= 违规
- **加工 contract 数字** — §2 line 写 "[15, 18]%" 就是 [15, 18]%，不许翻成 share% / 改单位 / 加 buffer
- **silent widen / soften** — verify 让 PASS 而调宽 §2 band = moving goalposts，反例 ref [`feedback_adversarial_self_review.md`](../memory/feedback_adversarial_self_review.md)
- **silent carve-out** — verify per-mode exception / "this case acceptable" 不更新 contract = silent override
- **提议改 philosophy / archetype 锚点** — feature shape / 顶奖叙事等已 framework anchored，agent 自己判断不该提

### Stage 4-10 agent **唯二合法 escalation**

- **Better idea**：team 发现更好设计 → 写 `boundary_contract_amendment_proposal_v<n>.md`，
  附 before/after 对比 + experience 改善理由 → 主 session 转 user → user 决定改不改 contract
- **Structural infeasibility**：穷尽 mechanism (mult / redistribute / restructure / architecture)
  后 contract bound 不可达 → 写同样 proposal 文档，附 mechanism exhaustion 证据 + 选项
  (改 bound vs accept deviation) → 主 session 转 user → user 决定

两者**都不许 silent 实施** —— 必须 explicit proposal → user sign-off → 加 contract §5
amendment log + 重新 freeze。

### Agent **允许**（不需要 escalate）

- 用 philosophy / archetype 当 direction 做合理判断（不引入新 §2 数字的前提下）
- Stage 3.5 期间澄清 user_brief 模糊语义（"占比"指啥）— 但只澄清，不替 user 决定
- 自由选择 process-internal 数字（tune step size / SA temperature / candidate enumeration count）
  —— 这些不是 boundary value

### Stage 3.5 之前 (Stage 0-3) 的 boundary 处理

Stage 3.5 之前 contract 还没 frozen — agent 不要按下面规则操作。Stage 1c 反推机制 +
Stage 1d 研究 + Stage 3 bootstrap weights 都是数据收集 + 工程实现，**不产生主观
boundary 决策**。设计选择留给 Stage 3.5 全 team 协商 + Stage 4 D 落地。

### 反例 (历史教训，all from M15 v10 cycle before contract 引入)

- v10 wave 1 agent 把 verify.py 11 个 band widened → ship 看似 PASS。**错**：silent widen，无 amendment proposal
- v10c agent 把 cherry §2 floor 自定 2.0%（user 只说"relax"没说"floor 2"）。**错**：引入 contract 没说的数字
- v10d agent 加 §14 R1 single-symbol ≤ 22% cap。**错**：引入 contract 没说的数字
- 主 session 提议改 feature trigger×EV 平衡。**错**：feature shape 是 framework anchored，不该 escalate
- M15 v8→v14 共 5 次 user-explicit boundary redesign：**根因**是没有 Stage 3.5 contract，
  user 不得不在 process 内反复介入。Contract 模式下这类 escalation 集中在 Stage 3.5 一次性谈完

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
- **每机台 machines/<M>/verify.py**：单机台 **硬约束代码**。

这份只写过程，不写 slot 知识细节。
