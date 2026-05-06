# Slot Designer — 跨机台设计哲学（first principles）

> **范围**：跨机台通用的设计原则。每个新机台 onboarding 先读这份；每个机台的 verify 必须包含对应硬约束。
>
> **不在这里**：单机台 specific 的数字、paytable、weight bound——那些在每机台的 `DESIGN.md` / `MODE_DESIGN.md` / `verify_<M>_design.py`。
>
> **跟 WORKFLOW.md 区别**：WORKFLOW 写"怎么做 review"，这份写"设计该满足什么"。

---

## 1. Per-family payout-frequency 倒金字塔

**每个家族里，lower-payout 的 symbol 必须比 higher-payout 的 symbol 频率高。**

机制：玩家直觉 + slot math 都要求。低 payout 多见维持 chase 感，高 payout 稀有制造记忆点。倒置 → 玩家感觉"高奖比低奖还多见"，违反基础 slot UX。

实现要点：
- **per-symbol weight cap 结构性强制**：低 payout cap > 高 payout cap
- **soft cost 强制 ordering + GAP**：单一 penalty `d_lower_payout < d_higher_payout × ratio_target` 触发，统一 reversal 和 gap-不足两种 deficit。strength 大到能压过 RTP/share 的 gravity（典型 ≥ 5000）
- **gap ratio ≥ 1.2-1.3x**：视玩家直觉。低 ratio → 玩家感觉两 tier "差不多"。1.3x 严格但可能跟某些机台 RTP target 冲突（cascade 4 tier = 1.3³=2.2x 占用 booster 总额度）；1.2x 折中（cascade=1.73x 仍清晰）

verify 类别建议：`<FAMILY>-HIER`（如 `BAR-HIER`、`BOOSTER-HIER`）含 ordering + GAP 两条 check。

---

## 2. Brand symbol visibility（品牌符号能见度）

**每个机台有 brand identity 符号（jackpot 符号 / cherry / wild / 倍率 wild），必须 visible enough but not dominant。**

要求：
- Brand symbol marginal density 在每条相关 reel 上 ≥ 一定下限（玩家每 N spin 看到一次）
- 不 dominate hit pattern（不超过 hit rate 60-70%）
- Lucky/super-lucky modes 频率有可见 lift（玩家感觉机台"今天出手了"）

verify 类别建议：`BRAND-VISIBLE` 或 marginal range check（如 `BOOSTER`）。

---

## 3. Blank weight cap headroom（dilution 余地）

**每条 reel 的 blank weight 不能顶死 WEIGHT_BOUNDS upper。顶死 = optimizer 想加 dilution 但 cap 限制 = 设计有压力没释放。**

要求：
- 每条 reel blank weight ≤ cap × 0.95（≥ 5 weight headroom）
- 顶死说明 cap 不够大，要么放 cap，要么调其他参数

verify 类别建议：`BLANK-CAP`。

---

## 4. Per-tier hit preservation（mode 间不变量）

**衍生 mode（cut mode 如 m7、lucky mode 如 m2/m5）必须遵守 tier-level hit preservation：**

- **Cut mode（m7 = m1 砍小奖）**：小奖 hit ↓，中/大/顶奖 hit 不动
- **Lucky mode（m2 = m1 加倍）**：所有 tier hit 都略升
- **Super-lucky mode（m5 = m2 大奖密集化）**：hit shape ≈ m2，顶奖 freq 升

要求：
- 不只看 total hit rate，要看 per-pay_id 频率比
- 跨 mode invariant 进 verify
- 用 frozen weights / floor / ceiling 在 tune 里实现

verify 类别建议：`MODE7-TIER`、`MODE5-HIT`、`LUCKY-MONO`。

---

## 5. CV-RTP consistency

**Higher RTP modes 应 lower CV（更平稳），lower RTP modes 应 higher CV（更 boom-bust）。**

典型：
- mode 1（95% RTP）CV: 6-12（classic 中等 vol）
- mode 7（85% RTP）CV ≥ mode 1（砍小奖 → boom-bust 加强）
- mode 2（300% RTP）CV ≤ 6（lucky tier hit 高 → vol 低）
- mode 5（500% RTP）CV ≈ mode 2（super-lucky 顶奖加强会略 raise CV，trade-off 接受）

verify 类别建议：`BASE-CV` + 跨 mode CV trend。

---

## 6. Family RTP share vs archetype baseline

**每个机台必须有 archetype reference**（real/published machine、或原创机台 + 公开 chassis 参考）。Family share 不偏离 archetype baseline ±15%。

要求：
- `reel_strips.json` 必带 `_archetype` block（origin / chassis_reference_url / modifications / confidence）
- archetype 不能是空 / 不能是 Claude 编的"应该是"——必须有 source（URL 或"原创 + 设计文档"）

verify 类别建议：`ARCHETYPE`、`SHARE`。

---

## 7. Top jackpot escalation narrative

**跨 mode 顶奖 freq 必须有清晰玩家叙事阶梯：**

- mode 1 baseline: 1 in 50-100k spins（lifetime story tier）
- mode 7 cut-mode: 1 in 50-100k（跟 m1 类似 — 砍小奖不动顶奖）
- mode 2 lucky: 1 in 15-30k（玩 1-2 hr 可期）
- mode 5 super-lucky: 1 in 3-10k（session 级稀有）

跨 mode 单调（m5 > m2 > m1 ≈ m7 frequency），ratio 合理（m5/m1 ≥ 5x）。

verify 类别建议：`TOP-JACKPOT-ESCALATION` 或 `MODE7-BIGWIN` 包含 ratio check。

---

## 8. Hit decomposition（避免单 pay dominate）

**任一 pay_id hit / total hit ≤ 70%。**

如果某 pay 占 hit rate 60%+，要么是设计上的特点（multi-tier wild 类机台 brand-pay 单一占 60%+ 可能是 brand 设计），要么是 bug（某 pay 过频）。需要 commit message 写明哪种。

verify 类别建议：`HIT-DISTRIBUTION`（暂未跨机台 impl）。

---

## 9. Mode-pair monotonicity（跨 mode invariant）

每对 mode 应满足：

- mode 2 RTP > mode 1 RTP
- mode 5 RTP > mode 2 RTP
- mode 7 RTP < mode 1 RTP
- mode 2 hit > mode 1 hit
- mode 5 hit ≥ mode 2 hit
- mode 7 hit < mode 1 hit
- mode 5 top jackpot freq > mode 2 top jackpot freq

**机台-specific 扩展** (per-machine `verify_<M>_design.py`)：
- Multi-tier wild slots：mode 5 booster combined density ≥ mode 2 (中轴 booster reel 在 lucky 模式更显眼)
- Feature 机台 (Feature Play 类)：mode 2/5 feature trigger rate ≥ mode 1
- Trigger-reel 机台：mode 5 trigger symbol density ≥ mode 2

verify 类别建议：`LUCKY-MONO` + cross-mode invariant checks。

---

## 10. Pareto trap 警惕

**Tune cost function 不能让 optimizer 把关键 family 砍到 0 同时数字 OK。**

典型陷阱：bucket 桶可由多家族填，optimizer 选 RTP-cost 低的家族 → 关键家族（如 high7、grand）被边缘化。

防御：
- 加 family-share 硬约束（band lower bound 强制最小 RTP 比例）
- 或 family-scale 锁某些家族不能砍
- 不要"先做简单的，pareto 出问题再加约束"——上来就加

参考：memory `feedback_tuner_pareto_trap.md`。

---

## 11. "假但不怪"原则（user 拍板原则）

数值是基础，玩家感性体验是灵魂。**hit RTP / hit / bucket_js 数字对 ≠ 设计完成**。

每台机必有 verify 必验类别：
- 家族 RTP share vs 原型 benchmark
- mode 间 experience invariant
- per-family per-reel ratio vs 原型
- near-miss 结构（如有）
- bucket shape narrative

红线全绿才 done，不绕过。Tune cost function 不含 experience 约束 = unbounded → Pareto 必然砍顶奖家族。

参考：memory `project_slot_designer.md (§A axiom)`。

---

## 12. Reel 间不对称 — R1 winners-friendly, 末 reel 特殊角色（Strickland/Reid/Harrigan）

**同一机台不同 reel 的 Blank / 顶奖密度天生应该不同。Universal rule，3-reel 和 5-reel 都适用：**

### 12.1 通用原则（任意 reel 数）

- **R1（leftmost reel）永远是 "winners-friendly" reel**：Blank 率最低，winning symbols 密度最高。这是 universal — 任何 reel 数 (3 / 5 / 7-reel) 都适用
  - 心理机制：R1 是玩家"第一印象"，从左到右扫，R1 blank → 一秒 disengage（"早期拒绝"）
  - 文献：Strickland & Grote 1967, Reid 1986

- **末 reel（rightmost: R3 in 3-reel / R5 in 5-reel）有特殊角色**，二选一：
  - **(a) Near-miss reel**：顶奖密度低，frequent "差一点" 触发 near-miss psychology (Harrigan 2007 award-symbol-ratio + clustering)
  - **(b) Trigger reel**：feature trigger 符号 (free spin / bonus / wheel) 锁在末 reel；其它顶奖密度低 (e.g., M15 TopDollar 只在 R3, M279 wheel trigger 只在 R5)

- **中间 reels（R2 in 3-reel / R2/R3/R4 in 5-reel）gradient**：从 R1 winning visibility 到末 reel 角色之间渐变。不强制具体方向，但应连续过渡（不能 R1 高 → R2 突低 → R3 高）

### 12.2 约束方向（universal，绝对数字写在每机台 verify_<M>_design.py）

3-reel:
- **R1 Blank 率 ≤ R3 Blank 率** — 方向锁，容差由该机台原型 + 玩家可见阈值推
- **R1 顶奖家族密度 ≥ R3 顶奖家族密度** — 方向锁
- 例外：trigger 锁 R3 时，trigger 符号不算"顶奖"——按非 trigger 的 top-prize 算

5-reel:
- **R1 Blank 率 ≤ R5 Blank 率**（同方向）
- **R1 顶奖家族密度 ≥ R5 顶奖家族密度**（除 trigger 符号）
- **R2/R3/R4 中间 gradient 连续**：max-of-middle Blank − min-of-middle Blank 应小（具体值机台特定）
- **5-reel 特有：R5 是 trigger reel 的概率高**——onboarding 时按 archetype 决定 R5 是 (a) 还是 (b) role

> **重要 — universal 哲学只锁方向，不锁绝对数字**（per `project_slot_designer §A axiom`）：
> 上面"R1 ≤ R3 Blank"是 universal。具体容差 ("3pp"/"8pp"/"X×")**不写在这里**——每台机在自己的 `verify_<M>_design.py` 里配置，依据：(a) 该机台 mode 1 baseline 实测自然 ratio + buffer；(b) 玩家可见阈值（≥ 5pp 才显著）；(c) 机台原型 PAR sheet。**不要 cross-machine hardcode 数字** — 这是 [`feedback_adversarial_self_review.md`](../../memory/feedback_adversarial_self_review.md) 警惕的 "picked threshold / moving goalposts" 反例。M1 实测举例见 [`weights/M1/DESIGN.md`](weights/M1/DESIGN.md) §6。

### 12.3 例外 / nuance

- **Lucky modes (RTP > 200%)**: 容差应宽（高 RTP 削弱 near-miss 心理；具体宽多少跟机台 paytable 结构相关，不写绝对值）
- **Cluster slot / pay-anywhere slot**: 此规则不直接适用 (没有 reel-by-reel 顺序揭示概念)。该用本规则的扩展：cluster 中心 vs 边缘的对称性
- **Cascading slot (tumble/avalanche)**: 第一波下落用此规则；后续 cascades 不适用 (玩家已 committed)

### 12.4 Tuner pareto 警惕

**Tuner 不知道这条**：cost function 没约束 → tuner 把顶奖 stuff 到任何 RTP 最便宜的 reel（实测往往是末 reel）。必须三层防护：
1. **verify check**（per-machine `REEL-ASYMMETRY` 类别）— 红线 catch 违反方向
2. **tune cost penalty** — `(R1_blank − R_last_blank − tol)²` 当 R1 比末 reel 还 blank 时
3. **archetype 文档** — 在 reel_strips.json `_archetype` block 写清"末 reel role 是 (a) 还是 (b)"

verify 类别建议：`REEL-ASYMMETRY`（per-mode R1 vs 末 reel blank + 顶奖密度方向）+ 5-reel 加 `MIDDLE-GRADIENT`。

参考：memory `project_slot_designer.md (§12 reel asymmetry)`。文献：[Strickland & Grote 1967](https://psycnet.apa.org/record/1967-08400-001), [Reid 1986 (Berkeley)](https://www.stat.berkeley.edu/~aldous/157/Papers/near_miss.pdf), [Harrigan 2007](https://link.springer.com/article/10.1007/s11469-007-9139-8), industry award-symbol-ratio (≥1988)。

---

## 13. Blank-flank diversity — 同一 Blank 前后不能同 symbol

**Universal direction（line-based slot 适用）**：strip 上每个 Blank 位置 p，**strip[p−1] ≠ strip[p+1]**（cyclic）。

### 13.1 心理机制

3-row 视窗在 reel 停 Blank 中间时，会同时显示 X-Blank-X（top: X, middle: Blank, bottom: X）。看到"两边 X"会被玩家解读为"差一个就 3 of a kind"，**dilute 真 near-miss 价值**（Harrigan award-symbol-ratio 反向应用：让 near-miss 廉价化 → 玩家麻木）。

文献：[US20120083327A1](https://patents.google.com/patent/US20120083327A1/en) 描述 column-level "no-same-consecutive" 技术 + [Harrigan 2007](https://link.springer.com/article/10.1007/s11469-007-9139-8) clustering 的相反约束（避免廉价 near-miss）。

### 13.2 适用 / 例外

| 机台类型 | 是否适用 |
|---|---|
| Line-based slot (3-reel / 5-reel classic / video 1-line / video multi-line) | **适用** — 严格 enforce |
| Cluster slot (pay-anywhere) | **不适用** — 没有"vertical column"概念 |
| Megaways with stacks | **不适用** — stacked symbols 是设计 feature |
| Cascading slot (tumble) | 第一波适用；后续 cascades 不要求（玩家已 committed） |

### 13.3 Implementation

**Strip 层硬约束** — 设计时通过 strip 重排满足。Strict B-N alternation 后，11 个非 Blank symbol 形成 cyclic 序列，约束 ⇔ "序列任意相邻位 symbol 不同"（graph coloring）：可解 iff `max(symbol_count) ≤ ⌈n_non_blank / 2⌉`。

**Verify 类别**：`BLANK-FLANK-DIVERSITY`（每 reel 检查所有 Blank 位置）。Universal hard rule，不需机台 specific 容差（要么 0 violations 要么红）。

**Strip 重排算法**：保 per-(reel, symbol) marginal 不变 → weights 跟随 position 移动 → marginals 不变 → RTP/hit/share 不动。但 strip md5 改 → rawdata 失效 → 重采。

---

## 14. Symbol 排布 visual rhythm — 玩家转轴视觉体验

**Universal goal**：strip 上 symbol 类型混合分布，避免连续段。具体规则跟机台原型 + 设计师审美相关。

### 14.1 通用方向

- **同 family 不连续段**：例 3 个 Bar（Bar1+Bar2+Bar3）连续会让 reel 视觉上"全 Bar 一段、全 Diamond 一段"，缺失节奏
- **顶奖 symbol 散开**：Diamond / Seven 类不应邻接（即使被 Blank 隔开但太近也算密集）
- **Brand symbol 错落**：Cherry / 机台 logo 类应跨 reel 长度均匀分布，不集中前半段或后半段
- **同 symbol 重复（如 R1 上 3 个 Bar3）位置间隔合理**：具体 stop 数机台 specific（视 reel 总长 + 重复实例数 + 玩家阈值）。**不在 universal 层定数字**——M1 (22-stop, 重复 3 次) 用 ≥ 4 stops 是该机台的 conservative pick，写在 M1 DESIGN.md，不是 cross-machine default

### 14.2 Universal 不锁绝对数字

具体规则（`max consecutive Bar = X`、`top symbol 间距 ≥ Y stops`、`Cherry 跨 reel 等距 ±Z`）**机台 specific**，依据：
- 机台原型 PAR sheet 实际排列（首选 — 真原型经过 IGT/Aristocrat 设计师调过，是金标准）
- 机台 paytable 结构（top symbol 数 vs 总 stops）
- 玩家审美阈值（视觉混合感 vs 极端整齐感平衡）

**Archetype-first 原则**：原型 reel 排列已经过设计审美调优，slot_designer 应**保留原型 ordering** 作为基线，仅在硬约束（如 §13 blank-flank 修复）需要时局部调整。

### 14.3 适用 / 例外

| 机台类型 | 是否适用 |
|---|---|
| Classic 3-reel (M1 类) | 适用 — 视觉节奏关键 |
| Video 5-reel | 适用 — 但宽视窗（5×3=15 cells）天然分散 visual perception |
| Cluster / pay-anywhere | 部分适用 — symbol 分布要均匀但"rhythm"概念变成"无明显 cluster zone" |
| Cascading | 第一波适用；后续 cascades 不要求 |
| Stacked symbol slots | 例外 — stacks 本身就是设计 feature |

### 14.4 Implementation

**Verify 类别建议（机台自定具体规则）**：`VISUAL-RHYTHM`，子类如 `BAR-CLUSTERING`（mid-pay 连续 cap）、`TOP-SPACING`（顶奖 stop 间距 floor）、`BRAND-DISTRIBUTION`（brand symbol 跨 reel 均匀）。

每机台 verify 文件需要明确该机台用哪些子规则 + 具体阈值，**不能 cross-machine 抄数字**。

文献：行业 IGT PAR sheet 实证 + [acaciainvestmentresearch (Near Misses)](https://www.acaciainvestmentresearch.com/post/reconfiguring-loss-the-power-of-near-misses-in-slot-machines)（"Symbol distribution adjusted purely for aesthetics"）。

---

## 15. Window visibility (PWDF) — 重要 symbol 视窗 visibility

**Universal direction**：top-prize 和 brand symbol 的 **any-reel window visibility**（reel 停时该 symbol 出现在 3-row 视窗的概率）应**显著高于** payline hit rate（≥ N×，N 机台 specific）。

### 15.1 心理机制

PWDF (Per-Win Display Frequency) — [Harrigan 2007](https://link.springer.com/article/10.1007/s11469-007-9139-8) 实证 IGT Double 7：上 above-payline 12.5% (8/64 virtual stops)，是 random 的 4×。技术名："**clustering**" / "**award symbol ratio**" — top symbol 在 virtual reel 上**邻接 weighted Blanks**，让 reel 频繁停在"邻 top-symbol 区"，视窗常含 top symbol 但 payline hit 仍稀。

效果：玩家视觉常看到顶奖 → "差一点就中"心理 → engagement up；payline hit rate 不变 → RTP 不漂。

文献：[Harrigan 2007 (Springer)](https://link.springer.com/article/10.1007/s11469-007-9139-8), [Know Your Slots — Virtual Reel Mapping](https://www.knowyourslots.com/understanding-virtual-reel-mapping/), [Acacia Research — Near Misses](https://www.acaciainvestmentresearch.com/post/reconfiguring-loss-the-power-of-near-misses-in-slot-machines)。

### 15.2 通用方向（不锁绝对数字）

- **Top-prize symbol any-reel visibility ≥ K×payline-hit-rate**（K 机台 specific，IGT 实证 4-10×）
- **Brand symbol（机台 logo / signature）visibility 跨 reel 均匀**（已由 §2 brand visibility + §12 REEL-ASYMMETRY 部分覆盖）
- **不要求所有 family**：低 pay symbol 不需 PWDF treatment（玩家不在乎是否常见）

### 15.3 适用 / 例外（floor 取决于架构 + paytable，**绝对值不抄**）

| 机台架构 | 适用度 + visibility 上限说明 |
|---|---|
| 3-reel physical (M1 类) | 适用。**物理 reel 上限 ~40-45%** (机制 B 后)；**Harrigan 50%+ 不可达** without 虚拟 reel 映射 |
| 3-reel + virtual reel mapping (IGT TDD 经典 等) | 适用。Harrigan 50%+ 可达 |
| 5-reel video 1-line | 适用，5×3=15 cell 视窗天然 visibility 高（每 reel 多机会）。Floor 30-40% |
| 5-reel multi-line / 25-line | 适用，每条 line 独立计 |
| 243-line / Megaways | 部分适用 — symbol 计 count（不是 visibility）|
| Cluster slot | 不直接适用 — symbol "visibility" = 屏上 count |

### 15.4 Implementation — RTP-neutral redistribution（推荐）

PWDF 实现需要 strip 上**邻接 top symbol 的 Blank** 权重 > **远离 top symbol 的 Blank** 权重。Per-(family, reel) uniform weight 假设跟这冲突（同 reel 所有 Blank 同 weight）。

**实施路径**：
- **机制 B (RTP-neutral redistribution，推荐)**：post-tune deterministic transform。每 reel 内 redistribute Blank weight — non-top-adj Blanks 减到 floor=1，top-adj Blanks 吸收剩余。total Blank weight per reel 守恒 → marginals 全保 → **RTP/hit/share 0 变化**。Top-adj Blank 上 weight 升 → 视窗 frequent contains top symbol → visibility 升 ~10pp on physical reels。**详见 §15.5 机制 B + memory `project_slot_designer.md (§15 window visibility)`**
- **机制 A (per-position weight tune)** 整合到主 cost — 实测在物理 reel 跟 RTP cost 冲突会 collapse RTP（M1 实测）。**避免**
- **机制 C (virtual reel mapping)** — 架构升级，Harrigan 50%+ 可达。投入大

**Verify 类别建议**：`WINDOW-VISIBILITY`（per machine：top symbol any-reel visibility ≥ floor）。机台 specific：
- Floor 数字（M1 物理 reel post-机制B: 38% standard / 35% lucky；virtual reel: 50%+ Harrigan 风格）
- 哪些 symbol 算 "top"（M1: Diamond1/Diamond2/Seven2；M15: TopDollar；multi-tier wild 类: booster；新机台 archetype 决定）
- 跟 payline hit rate 的倍数关系（K=4-10×）

### 15.5 物理 reel 上的两种 PWDF 机制（2026-04-29 M1 实测）

**误区**：以为物理 reel 上 visibility 跟 RTP zero-sum (boost visibility → RTP 崩)。这只对**直接 boost Blank weight × mult** 机制成立。**还有 RTP-neutral 机制存在**。

**机制 A — Multiply boost（RTP-collapsing，M1 实测崩）**：
- top-adj Blank weight × N (N>1)
- Total reel weight 增 → 所有 family marginal 减 → RTP 崩
- M1 实测: mult=5 → RTP 95%→13% 不可行

**机制 B — Redistribute（RTP-neutral，M1 实测可行）**：
- Per reel 总 Blank weight **守恒**: non-top-adj Blanks 减到 floor=1, top-adj Blanks 吸收剩余
- Total Blank weight 不变 → Blank marginal 不变 → 所有 family marginal 不变 → RTP/hit/share **完全不变**
- Top-adj Blanks 个体 weight 上升 → reel 经常停 top-adj 区 → window frequent contains top symbol → visibility 上升
- M1 实测: visibility +9-11pp (Diamond1 35→44%, Diamond2 30→41%, Seven2 29→39%)
- 副作用: Cherry visibility 跌 ~19pp (非 top-adj Blanks weight 跌 → Cherry 邻接 Blanks 失重)，但通常仍 ≥ floor

**机制 C — Virtual reel mapping (Harrigan IGT 经典)**：
- 64+ virtual stops 映射 22 physical stops via weight table
- Visibility 50%+ 可达，但需架构层升级

**新机台 onboarding 决策树**:
1. 先确认架构。Virtual mapping 已实现？→ 用机制 C，target Harrigan 50%+
2. 否则物理 reel：先用**机制 B (RTP-neutral redistribution)** push visibility 到自然 baseline + 8-12pp
3. **不要**直接用机制 A（崩 RTP）
4. 若 redistribution 还不够，考虑加 top symbol 实例（paytable 结构改变，需 user 拍板）或升架构

### 15.6 Tuner pareto 警惕

**物理 reel 机台**：PWDF **不要进 tune cost**（机制 A 跟 RTP 冲突崩）。改 **post-tune RTP-neutral redistribution**（机制 B）— 主 tune 满足 14+ 类约束 → 单独 deterministic transform redistribute Blank weights → 视窗 visibility 升而 marginals 全保。

**虚拟 reel 机台**：PWDF 可作为 cost component 进 tune（virtual mapping 提供更大 visibility/RTP trade-off 空间）。

三层防护：post-tune redistribution（物理）/ cost penalty（虚拟）+ verify red line + archetype 文档（哪些 symbol 是"top"写明，物理 vs 虚拟 reel 写明）。

### 15.7 Cross-mode 视窗 visibility 设计原则（universal direction）

派生 mode 与原型 mode 的视窗 visibility 关系：

| 派生关系 | 视窗 visibility 处理 | 根因 |
|---|---|---|
| **Cut mode 派生**（cut ← standard） | visibility pattern 跟 standard mode 一致 | cut mode "冷"narrative 应只在数值层（hit/RTP）体现；视觉差异破坏"同一台机不同档"的叙事连续性 |
| **Lucky mode（独立 archetype）** | visibility 略高于 standard mode | lucky narrative 要求视觉上"运气来了"自然反映 |
| **Super-lucky 派生 ← lucky**（base byte-identical 锁） | visibility 跟 lucky mode 一致 | super-lucky narrative 通过 top-symbol marginal 自然抬升体现（per §15.4 mechanism B 不重复施加） |

→ **具体 redistribution ratio 跨 mode 差几倍由每机台 `weights/<M>/DESIGN.md` 配置**。Universal 层只锁方向：standard ≤ lucky；cut = standard；super-lucky = lucky。

### 15.8 防"假"约束方向

Mechanism B redistribution 必须满足以下约束方向（universal direction，**具体阈值不在此处定，每机台 `verify_<M>_design.py` 写**）：

- **Top-adj vs non-top-adj blank weight 比值有上限**（防极端不均匀 → 玩家觉得刻意）
- **任一 top symbol any-reel window visibility 有上限**（physical reel；virtual-reel mapping 机台另议）
- **Mid-pay symbol any-reel window visibility 有 floor**（防 mid-pay 视觉消失，玩家觉得"reel 跟我玩的不是一台机"）

每机台用 `verify_<M>_design.py` 的 **`WINDOW-VISIBILITY-CAP`** / **`BLANK-RATIO-CAP`** / **`MID-PAY-VISIBLE-FLOOR`** 三类红线强制。

数字依据：(a) 该机台 archetype；(b) 玩家可见阈值；(c) 物理 reel 自然上限。**不要 cross-machine 抄数字** — 这是 [`memory/feedback_adversarial_self_review.md`](../../memory/feedback_adversarial_self_review.md) 警惕的 "picked threshold" 反例。

---

## 应用：每个新机台 onboarding 必做

1. **读这份哲学**——每条对应 verify 类别要 implement
2. **读 WORKFLOW.md**——adversarial review 流程
3. **写机台 DESIGN.md**——archetype block + 业界 chassis 参考 + 玩家叙事
4. **写 verify_<M>_design.py**——把上面 15 条都加到 verify（含 §13 BLANK-FLANK-DIVERSITY、§14 VISUAL-RHYTHM 子类、§15 WINDOW-VISIBILITY）
5. **tune 时 cost function 包含**：hierarchy_strength、family share band、per-pay freq cap、top_jackpot_min_spins、reel asymmetry（R1 ≤ R3 Blank + R1 ≥ R3 top-prize）。**§15 PWDF 不进 tune cost**（物理 reel），post-tune redistribute
6. **strip 设计阶段**确认满足 §13 BLANK-FLANK-DIVERSITY（无 X-Blank-X）+ §14 VISUAL-RHYTHM（机台 specific 子规则）。修复 strip 不会改 marginal 但改 strip md5 → 全 mode rawdata 失效
7. **post-tune PWDF redistribute（物理 reel 机台）**：跑 redistribute_<M>_blanks.py 类脚本，per reel redistribute Blank weight 到 top-adj 位置。RTP-neutral，仅升 visibility

参考实现：`weights/M1/` 含 REEL-ASYMMETRY check + post-tune redistribute (2026-04-28+)；`weights/M15/` Feature Play 类机台 4-mode pipeline。
