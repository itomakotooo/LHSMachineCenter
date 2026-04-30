# M37 — 心得 / Lessons Learned

> **场景**：v1→v7 共 7 次 commit，user 7 次都看一眼指出问题。这份记录设计过
> 程中犯的所有错，每条用真实例子说明，下次不能重蹈。
>
> **核心错**：把"verify GREEN"当 done，把"数字 fit"当目标，把"加边界 cap 让
> optimizer 满足约束"当方法。三条都偏离 `slot_designer/DESIGN_PHILOSOPHY.md
> §11 假但不怪原则`。

---

## 心得 1 — 玩家感性体验是验证目标，不是 nice-to-have

**犯过的错**：v3 commit 写 "verify 11 categories ALL GREEN"。User 拉 rawdata
看，发现 1bar 在 R1 占 80%、R2 7bar 占 67%、R3 全 blank。这些数字单独看每条都
"在 verify cap 内"，但合起来玩家感受是 broken machine。

**心得**：tune cost 的目标是表达"玩家应该感受到什么"，不是数字 fit。具体维度：
- **第一印象 (visual identity)** — 视窗看到的符号要符合机台 brand
- **每转视窗揭晓** — 9 cells 看到的内容要 balanced，不能全 blank、全单一 symbol
- **中奖体验** — hit 不是"啊赢了 1×"，得有重量
- **标志 moment** — grand 100×、3-wild jackpot、top 1000× 各自的 narrative
- **Reel 分工** — R1 winners-friendly、R2 brand reel、R3 near-miss
- **PWDF 视窗能见度** — 顶奖在视窗的 visibility 远高于 payline hit rate

每个维度都要 verify check + 数字 dump 实测。verify GREEN 之后还要按这些维度
**人眼过实测数字** 才能 commit (per `WORKFLOW.md §1`).

---

## 心得 2 — Picked thresholds 是 anti-pattern。所有数字必须有 derivation chain

**犯过的错**：v6 加了一堆 cap：
- `family_share_bands["booster_alone"]: (0.30, 0.50)` — 为什么 50%? 不知道
- `WEIGHT_BOUNDS["mini"]: (1, 30)` — 为什么 30? 因为我感觉
- `bucket_share_weight: 1000` — 调到 fit 数字
- `BOOSTER_GAP_TARGET = 1.2` — 通用值但没说 1.2 不是 1.5

User v6.1 直接打回："你这个 cap 什么意思，我从来没设置过这样的硬边界"。

**心得**：每个数字必须能回答"这个值从哪来"，3 类来源合法：
1. **User-spec / business 硬指标**（RTP 95/300/500/85）
2. **Engine physics**（wild only on R1+R3；reroll-blocked pattern）
3. **Universal first principles 派生**（universal §1 hierarchy ratio 1.2x; universal §12 R1≤R3 blank direction; universal §15 PWDF K factor 4-10x）

**4 类研究/narrative 派生**也合法但要写出 chain：
- Classic 1-line research baseline (RWB 87% RTP / Blazing Sevens 89% / hit rate 25-35%)
- Player narrative quantification（"玩家 normal session 1 grand" → freq 1/433 floor）

**不合法**：
- "我感觉 50% 比较合适"
- "之前 v5 是 30%-50% 我接着用"
- "为了让 verify 过，cap 调一下"

每改一个数字，commit message 必须写出 derivation chain。改不出 chain → 这个数
字不该存在。

---

## 心得 3 — PWDF (window visibility) 是 Tier-1 设计维度，从一开始就要 measure

**犯过的错**：v1-v7 共 7 个 commit 全部 没有 measure 过 grand/high7/wild 在 3-row
视窗的能见度。Universal §15 是 6 大 universal hard rules 之一，我每次都"知道
它存在"但没 implement 过 verify check 或 cost penalty。

User v7.1 指出："symbol 的窗口占比和支付线占比也不对"——这是 PWDF。

**心得**：PWDF 不是 "post-tune nice-to-have"，是 Tier-1 设计目标。每次 tune cycle：
- analytic_profile 拓展输出 per-symbol per-reel window visibility
- cost function 加 PWDF target 软约束
- verify check 加 WINDOW-VISIBILITY category
- adversarial review 必查 grand visibility / high7 visibility / wild visibility

Harrigan IGT Double 7 实证：top symbol any-reel visibility 12.5% = 4× payline
hit rate。每机台 K factor 在 4-10× 区间。M37 grand 是 brand signature → K 选
偏高 (~7-10×)。

---

## 心得 4 — Reel-by-reel blank rates 有 specific 角色，不是 "uniformly ~50%"

**犯过的错**：v6 R1 blank 73% / R3 blank 81%。v7 改进到 R1 46% / R3 50%——但
R1 偏高（应 30-40% per "winners-friendly"角色）。每次 SA 让 blank 自由，optimizer
都把 blank 推高（用 blank dilute 不需要的 symbol contribution）。

**心得**：universal §12 不只是"R1 ≤ R3"方向，还隐含 specific 角色：
- **R1 = winners-friendly reel**: blank lowest（classic 1-line research baseline 30-40%）
- **R2 = brand/booster reel**: blank highest (50-65% per booster reel structure)
- **R3 = near-miss reel**: blank mid (~40-50%)

Cost function 不能只 enforce direction，要 enforce **archetype-baseline 数字范围**
（research-cited，不是 picked）。

---

## 心得 5 — Bar 在 R1 应该分散 4 个 tier，不是单一 tier 占 80%

**User v7.1 明说**："R1 多数是 bar 是对的，但得分散"。v7 mode 1 R1: 1bar 25% /
2bar 12% / 3bar 5% / 7bar 3%——cascade 比 ~ 8x，universal §1 ratio 1.2x compounded
应该 1.7-2.85x。8x 远超。

**心得**：universal §1 不只锁方向（lower payout > higher payout），还锁 cascade
ratio (1.2-1.3x)。M37 4 bar tiers cascade 1.2³ = 1.73x，1bar/7bar 应该 1.7-2.85x
区间。8x 是 violation。

Cost function 加 cascade ratio 软约束（universal §1 派生，不是 new picked）。

---

## 心得 6 — Hit rate 12-15% 是 M37 modern multi-tier wild 范围。不是 18%。不是 "broad ±5pp"

**User 反馈**："中奖率过高"——v7 mode 1 hit 22.56%。我之前 §3 写 18% target +
±5pp tol = 13-23%，accepting 22% as upper edge。但 user 觉得 22% 偏高。

**心得**：modern multi-tier wild slot research 范围 15-22%。但 M37 是 LHS modern
classic-with-wild **偏向 sparse-machine 设计**（user 多次表达 booster signature
+ 顶奖 narrative > 高 hit rate）。target 应该 14% (range lower edge)，tol 严
格 (±2pp not ±5pp)。

宽 tolerance 是"让 optimizer find natural"的借口，实际让 optimizer drift 到
upper edge。tight tolerance 强制 hit 在 design intent 范围。

---

## 心得 7 — Bucket distribution 是 player-feel 硬约束，不是 emergence

**犯过的错**：v7 §7 写"DIRECTION ONLY (Low > Mid > High > Top by hit count)"，
说 "no picked %"。结果 mid bucket 只占 ~10% of hits（设计应 15-20%）—— 玩家
"诶有料"moment 太稀。

**心得**：direction 不够。bucket count distribution 有 specific 占比 narrative：
- Low (1-10×): 70-80% of hits — chase engagement
- Mid (10-50×): 15-20% of hits — accept point
- High (50-500×): 1-2% of hits — session memory
- Top (500-1000×): <0.05% of hits — lifetime

这些占比来自 player tier psychology research（universal §11 narrative）+ classic
1-line实证 (RWB hit decomposition)。是 research-cited 不是 picked。每个 mode
基于此调整。

---

## 心得 8 — pay_id 9 brand dominance：不能 0%，也不能 70%+。50-60% 是甜区

**犯过的错**：v6 mode 1 pay_id 9 = 78% of hits（dominate）；v7 = 63%（接近上
限）。

**心得**：pay_id 9 covers **booster_alone family 的 brand identity**——它 occupy
50-60% of hits 是 design feature (per universal §8 + DESIGN_PHILOSOPHY §11
"假但不怪")。但 70%+ 玩家感觉 "everything is mini/wild alone"——empty calorie
+ 单调。

target 50-60%。verify cap 60% (not 70% universal default —— M37 specific tighter
because brand signature 单一 pay_id 占比偏高时玩家感觉 broken)。

注：这个 60% 是 "M37 specific tightening from universal §8 70%" derivation chain。
不是凭空 pick 60%。

---

## 心得 9 — Strip layout PWDF design 必须 verify 实际 visibility，不只看 layout 美观

**犯过的错**：reel_strips.json `_near_miss_design` 写"Reel 2 positions 17, 19,
21 = high7, grand, high7"，注释说"创造 grand near-miss visual"。但从未 measure
过实际 grand visibility。

**心得**：strip layout 设计必须 verify 实际 visibility metric。layout 决定哪些
weight 计入哪些 row 的 visibility。high7-blank-grand-blank-high7 pattern + 高
weight 邻接 grand 的 blanks → grand any-reel visibility 上升。

实施流程：
1. tune 主 cost (RTP/hit/freq targets)
2. post-tune **redistribute Blank weight 到 top-adj positions**（universal §15.5
   机制 B — RTP-neutral）
3. verify WINDOW-VISIBILITY category 实测 visibility ≥ floor

不要把 PWDF 进 main cost (universal §15.6 警告：跟 RTP cost 冲突会 collapse)。

---

## 心得 10 — Optimization framework 是表达 design intent 的工具，不是 design intent 本身

**犯过的错**：v6→v7 我反复 tweak `bucket_share_weight` 从 150 → 350 → 1000，期
待 optimizer 找好解。这是 把 cost weight 的事情当 design 的事情做。

**心得**：cost weight 平衡是 implementation detail，不是 design 决策。Design 决
策应该在 DESIGN.md 写清"应该满足什么"，cost weight 只是把它转换成 SA 能优化的
形式。

如果 cost weight 怎么 tune optimizer 都找不到好解 → cost function structure 没
正确表达 design intent，重写 cost function 不是 tune weight。

---

## 心得 11 — Archetype-derived seed > uniform-random seed

**犯过的错**：v6 让 SA 从 uniform random 开始，找到 R2 7bar 67% 的 corner。

**心得**：SA 的 cost surface 多 local minima，uniform random 起点会 wander 到
extreme corner。**Hand-crafted archetype-derived seed** 把 optimizer 锁在 sane
basin，SA 只 fine-tune 局部。

Seed values 的"具体数字"（如 R2 mini=6, minor=4, major=3, grand=1）来自：
1. archetype reference (classic 1-line baseline + booster reel ratio)
2. universal §1 hierarchy direction (mini > minor > major > grand cascade ~1.5x)

不是 picked，是 archetype-derived。

---

## 心得 12 — 每次 commit 前 adversarial review 必查 4 类盲区

**犯过的错**：v3-v7 commit 前都跑了 verify GREEN 但没主动 stress-test 4 类盲区。

**心得**：commit 前必查（per `WORKFLOW.md §2`）：
1. **设计 intent 真实现了吗** — 实际 per-pay 数字对照 design intent
2. **first principles 主动扫一遍** — universal §1-§15 每条问"我有没有 check"
3. **verify 自己有盲区吗** — 之前 user 指出的问题，verify 现在能 catch 吗
4. **数字直觉 check** — 每条 reel 的 density 看一眼，跟 archetype 像不像；weight 是不是顶死 cap

每个盲区都要在 commit message `## Self-critique` 段写出问到了什么、答了什么。

---

## 心得 13 — "结构性 trade-off" 必须 验证过 真改不了。否则是借口

**犯过的错**：v6 commit 写"3 RED items 是 structural carve-out"——其中 mode 5
BOOSTER-HIER 1.08x 我没真试 fix（说"super-lucky 设计 grand 必然密"），后来 user
不接受。

**心得**：每个"structural"claim 在 commit message 之前先 try 修一次。**真改不了**
要满足 3 条：
1. 试过具体 fix（不是脑补"这样改肯定不行"）
2. fix 是改架构层（spec/paytable 改动）才能修
3. 跟 design intent 不矛盾

只是"cost 配不平就说 structural"是借口。

---

## 心得 14 — User 每次能一眼看出问题是因为他用 first principles 看，我没

**犯过的错**：v1-v7 共 7 commit 都被 user 一眼指出问题。我以为自己跑了 verify
就 OK，user 看的是数字背后的原理。

**心得**：每次 commit 之前要 internalize user 的视角：
- "如果 user 现在看 mode 1 数字，第一反应会问什么?"
- "数字 fit 但 layout 是不是怪 (R1 1bar 80%)?"
- "PWDF 视窗能见度 measure 过吗?"
- "每条 reel 的 blank 比例符合 reel 角色吗?"
- "bucket distribution 真的是 Low > Mid > High > Top 吗?"

在 commit message 写出 self-critique 段——把 user 视角问出来 + 答出来。

---

## 心得 15 — 每次"只新增软约束 cap" 是治标。结构性 fix 是 cost function 重写

**犯过的错**：v6 → v6.1 → v7 各阶段我都在 add cost component / add cap / bump
weight。每次都"再加一个 fix 这个新出现的问题"。结果 cost function 累积成 50+
picked numbers 的乱麻。

**心得**：当 optimizer 出现 第二次同类问题时（e.g., 第二种 R2 dominate symbol），
**重写 cost function structure** 而不是再加一个 cap。

具体：v7 加了 PER_REEL_BLANK_CAP / OUTER_SINGLE_SYM_CAP 两个 cap fix corner。这
是 anti-pattern。改用 universal §1 cascade ratio + universal §15 PWDF target ——
universal-derived，把 corner cases 的 root cause 修掉。

---

## 应用：M37 redo 用上面 15 条心得

每次 tune iteration cycle 必跑：

1. **Tune** — cost 表达 design intent (DESIGN.md derivations)
2. **Dump 实测数字** — per-mode 每个维度
3. **Adversarial review by 心得 1-15** — 每条 stress-test
4. **发现问题 root-cause fix** — 不加新 picked cap，改 cost structure
5. **再 tune** — iterate until 心得 1-15 全过

不要 "verify GREEN 就 commit"。verify 是必要不充分条件。
