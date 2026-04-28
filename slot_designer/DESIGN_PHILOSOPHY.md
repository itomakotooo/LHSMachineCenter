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

## 应用：每个新机台 onboarding 必做

1. **读这份哲学**——每条对应 verify 类别要 implement
2. **读 WORKFLOW.md**——adversarial review 流程
3. **写机台 DESIGN.md**——archetype block + 业界 chassis 参考 + 玩家叙事
4. **写 verify_<M>_design.py**——把上面 11 条都加到 verify
5. **tune 时 cost function 包含**：hierarchy_strength、family share band、per-pay freq cap、top_jackpot_min_spins

参考实现：`weights/M37/` 完整流程（v5 后）。
