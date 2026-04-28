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

如果某 pay 占 hit rate 60%+，要么是设计上的特点（如 M37 pay_id 9 占 60%+ 是 brand 设计），要么是 bug（某 pay 过频）。需要 commit message 写明哪种。

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
- mode 5 booster_R2 ≥ mode 2 booster_R2

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

参考：memory `project_slot_designer_axiom_experience_is_soul.md`。

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

### 12.2 具体约束（per-mode hard rule）

3-reel:
- **R1 Blank 率 ≤ R3 Blank 率**（standard mode ≥ 3pp tolerance, lucky mode 8pp）
- **R1 顶奖家族密度 ≥ R3 顶奖家族密度**（≥ 1pp tolerance）
- 例外：trigger 锁 R3 时，trigger 符号不算"顶奖"——按非 trigger 的 top-prize 算

5-reel:
- **R1 Blank 率 ≤ R5 Blank 率**（同方向，容差按机台调）
- **R1 顶奖家族密度 ≥ R5 顶奖家族密度**（除 trigger 符号）
- **R2/R3/R4 中间 gradient 连续**：max-of-middle Blank − min-of-middle Blank ≤ 中间过渡幅度（避免突跳）
- **5-reel 特有：R5 是 trigger reel 的概率高**——onboarding 时按 archetype 决定 R5 是 (a) 还是 (b) role

### 12.3 例外 / nuance

- **Lucky modes (RTP > 200%)**: 容差宽 (5-10pp Blank, 2-3pp top-prize)。原因：高 RTP → 玩家持续中奖 → near-miss 心理弱化，反方向略漂可接受
- **Cluster slot / pay-anywhere slot**: 此规则不直接适用 (没有 reel-by-reel 顺序揭示概念)。该用本规则的扩展：cluster 中心 vs 边缘的对称性
- **Cascading slot (tumble/avalanche)**: 第一波下落用此规则；后续 cascades 不适用 (玩家已 committed)

### 12.4 Tuner pareto 警惕

**Tuner 不知道这条**：cost function 没约束 → tuner 把顶奖 stuff 到任何 RTP 最便宜的 reel（实测往往是末 reel）。必须三层防护：
1. **verify check**（per-machine `REEL-ASYMMETRY` 类别）— 红线 catch 违反方向
2. **tune cost penalty** — `(R1_blank − R_last_blank − tol)²` 当 R1 比末 reel 还 blank 时
3. **archetype 文档** — 在 reel_strips.json `_archetype` block 写清"末 reel role 是 (a) 还是 (b)"

verify 类别建议：`REEL-ASYMMETRY`（per-mode R1 vs 末 reel blank + 顶奖密度方向）+ 5-reel 加 `MIDDLE-GRADIENT`。

参考：memory `project_slot_designer_reel_asymmetry.md`。文献：[Strickland & Grote 1967](https://psycnet.apa.org/record/1967-08400-001), [Reid 1986 (Berkeley)](https://www.stat.berkeley.edu/~aldous/157/Papers/near_miss.pdf), [Harrigan 2007](https://link.springer.com/article/10.1007/s11469-007-9139-8), industry award-symbol-ratio (≥1988)。

---

## 应用：每个新机台 onboarding 必做

1. **读这份哲学**——每条对应 verify 类别要 implement
2. **读 WORKFLOW.md**——adversarial review 流程
3. **写机台 DESIGN.md**——archetype block + 业界 chassis 参考 + 玩家叙事
4. **写 verify_<M>_design.py**——把上面 12 条都加到 verify
5. **tune 时 cost function 包含**：hierarchy_strength、family share band、per-pay freq cap、top_jackpot_min_spins、reel asymmetry（R1 ≤ R3 Blank + R1 ≥ R3 top-prize）

参考实现：`weights/M37/` 完整流程（v5 后）+ `weights/M1/` 含 REEL-ASYMMETRY check（2026-04-28+）。
