# Slot Designer — Expert Review Checklist (Self-enforced before commit)

> **目的**：每次 tune commit 前 Claude 自己跑一遍 first-principles 检查。verify GREEN 不够；这份 checklist 才是 done 标准。
>
> **背景**：v3/v4 两轮设计每次都需要 user 主动指出问题 → process 失败。Verify 只测"我自己定义的约束"，盲点系统性。这份 checklist 列**领域 first principles**，每次新机台 / 新 tune 走一遍。
>
> **使用**：每个机台的 `verify_<M>_design.py` 加对应硬约束；commit 前在 commit message 里 ack 走过这份 checklist。

---

## A. Per-family hierarchy（payout-frequency 倒金字塔）

任何家族里，**lower-payout symbol 必须比 higher-payout symbol 频率高**。这是 slot 设计 101，玩家直觉 + slot math。

### 家族举例

- **Bar tier**: 1bar (3×) > 2bar (4×) > 3bar (5×) > 7bar (6×) frequency
- **Booster tier (倍率 wild)**: mini (2×) > minor (5×) > major (10×) > grand (100×)
- **Cherry tier (经典 RWB)**: any-cherry > cherry-bar > 2-cherry > 3-cherry
- **wild count**: 1-wild > 2-wild > 3-wild

### 检查点

- [ ] **每条 reel 上**，每家族内 hierarchy 不倒置
- [ ] hierarchy 之间有可见 gap（低 tier ≥ 高 tier × 1.3，否则像同 tier）
- [ ] verify 加 `BAR-HIER` / `BOOSTER-HIER` / 类似类别

### 为什么会倒置

Optimizer 选择 RTP-efficient 但 hierarchy-违反的 weight 分配。例：major (10×) 比 mini (2×) 给 RTP 更多 per-weight，没显式 hierarchy cost 时 optimizer 会 push major weight 高于 mini。

### 解决方案

tune cost function 加 hierarchy_strength penalty，密度反序时 (gap × 100)² × strength。推荐 strength ≥ 200。

---

## B. Brand symbol visibility（品牌符号能见度）

每个机台的 brand identity（Lightning Link 的 jackpot 符号 / Buffalo 的 buffalo head / Cherry RWB 的 cherry / M37 的倍率 wild）必须 **visible enough but not dominant**。

### 检查点

- [ ] Brand symbol marginal density 在每条相关 reel 上 ≥ 一定下限（玩家每 N spin 看到一次）
- [ ] Brand symbol 不 dominate hit pattern（不超过 hit rate 的 60-70%）
- [ ] Brand 在 lucky/super-lucky modes 频率有可见 lift（玩家感觉更"幸运了"）
- [ ] verify 有 `BRAND-VISIBLE` / `BOOSTER` / 同类类别检查 marginal range

### M37 specific

- 倍率 wild on R2 marginal: mode 1 ~5%, mode 2 ~18%, mode 5 ~25%
- mini 必须 visible（每 100-150 spin 能看到，不是 1000+ spin）
- grand 极稀（1000+ spin 一次），symbolizing jackpot

---

## C. Blank weight cap headroom（blank 是否顶死 weight bound）

Blank weight 顶死 cap 意味着 optimizer 想加更多 dilution 但被 cap 限制 → 设计漂。检查 weight headroom。

### 检查点

- [ ] 每条 reel blank weight ≤ cap × 0.95（≥ 5 weight headroom）
- [ ] 如果 blank 顶死，原因写明（e.g., 设计上 R2 booster reel 自然 blank-heavy）
- [ ] verify 加 `BLANK-CAP` 类别

### 为什么重要

V4 mode 1 R2 blank = 50（旧 cap）顶死。意味着 optimizer 想加更多 blank 但 cap 限制 → 实际 RTP 超 95% target，optimizer 没能 dilute 够。修法：放 cap 到 100，让 optimizer 自由选。

---

## D. Per-tier hit preservation（per-mode invariant）

每个 mode 的 per-tier hit rate 是设计 intent 的硬要求。**Total hit rate 在 band 内 ≠ per-tier 都对**。

### M37 mode 7 specific（per memory project_slot_designer_hit_rate_deviation.md）

- [ ] mode 7 SMALL pays (1bar/2bar/3bar/mixed-bars) freq m7/m1 ≤ 0.85x
- [ ] mode 7 MID pays (7bar-3, h7+7bar mix) freq m7/m1 ∈ [0.70, 1.40]
- [ ] mode 7 BIG pays (high7-3) freq m7/m1 ∈ [0.85, 1.15]
- [ ] mode 7 TOP pays (grand alone, top jackpot) freq preserved within 1.55x

### Mode 2/5 lucky monotonic

- [ ] mode 2 hit rate ≥ mode 1 (lucky should fire more often)
- [ ] mode 5 hit rate ≤ mode 2 × 1.25 (super-lucky preserves bucket shape)
- [ ] mode 5 big-win SUM freq ≥ mode 2 × 1.4 (super-lucky 大奖密集化)

### verify 类别

`MODE7-TIER` / `MODE5-HIT` / `LUCKY-MONO`

---

## E. CV-RTP consistency（volatility 跟 RTP 一致）

Higher RTP modes (lucky/super-lucky) 应该 lower CV (more frequent wins, smaller swings).

### 检查点

- [ ] mode 1 (95% RTP) CV: 6-12 范围（classic 中等 vol）
- [ ] mode 7 (85% RTP) CV ≥ mode 1 (砍小奖 → boom-bust 更强)
- [ ] mode 2 (300% RTP) CV ≤ 6 (lucky tier hit rate 高 → vol 低)
- [ ] mode 5 (500% RTP) CV ≤ mode 2 (super-lucky 更平稳)

### verify 类别

`BASE-CV` (现有) + 跨 mode CV trend check

---

## F. Family RTP share vs archetype

Reverse-engineer 真原型的 family share 范围当 baseline。M37 是原创 + classic 参考，所以 share 应近似 classic 1-line。

### M37 specific（per reference_classic_slot_rtp_distribution.md）

Classic 1-line RTP shares:
- RWB 87% RTP: bar 31%, cherry 16%, seven 50%
- Blazing Sevens 89%: seven 68.8%

M37 没 cherry，由倍率 wild 替代 frequent reward。所以：
- bar_tier 30-50% (classic 范畴)
- high7 + 7bar + 倍率 wild combos = "seven 替代家族" 50-65%

### 检查点

- [ ] family RTP share 跟 archetype baseline 不偏离 ±15%
- [ ] verify 类别 `SHARE` 已有，但要 check archetype baseline 是不是真原型而不是凭空

---

## G. Top jackpot escalation narrative

跨 mode 顶奖 freq 应该有清晰玩家叙事阶梯。

### 推荐范围

- mode 1 baseline: 1 in 50-100k spins (lifetime story tier)
- mode 7 cut-mode: 1 in 50-100k (跟 m1 类似 — 砍小奖不动顶奖)
- mode 2 lucky: 1 in 15-30k (玩 1-2 hr 可期)
- mode 5 super-lucky: 1 in 3-10k (session 级稀有)

### 检查点

- [ ] 顶奖 freq 跨 mode 单调（m5 > m2 > m1 ≈ m7 frequency）
- [ ] 阶梯 ratio 合理（m5/m1 ≥ 5x, m2/m1 ≥ 2x）
- [ ] verify 类别 `MODE7-BIGWIN` 包含 top_jackpot_ratio check

---

## H. Hit per pay 分布（不要某一 pay dominate hit rate）

如果某个 pay (e.g., pay_id 9 booster/wild alone) 占了 hit rate 60%+，可能是 brand 设计问题。

### 检查点

- [ ] 任一 pay_id hit / total hit ≤ 70%
- [ ] pay_id 7 (mixed bars) + pay_id 9 (alone) 之和不超过 hit rate 80%
- [ ] verify 加 `HIT-DISTRIBUTION` 检查（暂未 impl，next 机台加）

---

## I. Mode-pair monotonicity invariants

跨 mode "应该单调" 的 invariant 列清单：

- mode 2 RTP > mode 1 RTP (lucky)
- mode 5 RTP > mode 2 RTP (super-lucky)
- mode 7 RTP < mode 1 RTP (cut)
- mode 2 hit > mode 1 hit
- mode 5 hit ≥ mode 2 hit (但 ≤ × 1.25)
- mode 7 hit < mode 1 hit
- mode 5 top jackpot freq > mode 2 top jackpot freq
- mode 5 booster_R2 ≥ mode 2 booster_R2

### 检查点

- [ ] verify 走每条 monotonic invariant
- [ ] LUCKY-MONO 类别已有，加更多 cross-mode

---

## Pre-commit walk-through

每次 commit 前 claude 必须：

1. **Run verify** — all categories GREEN
2. **Per-pay table 显示** — 4 mode 横排，每 pay_id 频率 + RTP 都看一遍
3. **Per-reel density table 显示** — 每条 reel 每家族密度看一遍
4. **Hierarchy walk** — Bar tier 倒金字塔 ✓ / Booster tier 倒金字塔 ✓
5. **Blank weight check** — 每 reel blank 不顶 cap
6. **Top jackpot escalation** — 写在 commit message 里
7. **Per-tier preservation** — m7 SMALL ratio + MID/BIG ratio 列出来
8. **Self critique 1 段** — "如果我是 slot designer 我会挑什么刺？" 列 0-3 个 caveat 在 commit message

不写 self critique = 没真做 expert review = 不能 commit。

---

## 历史 lessons learned（反面教材）

- **v3 commit (2026-04-27)**: 我说"verify all GREEN done"。User 拉数据发现 mode 1 1bar 死、grand alone dominant、顶奖太频。Verify 没覆盖到。
- **v4 commit (2026-04-27)**: User 用哲学 review 指出 5 硬伤（archetype 缺、mode 7 中奖砍、mode 5 hit 飙、booster share 倒、mode 1 hit 高）。Verify 没覆盖到。
- **v4 post (2026-04-27)**: User 看 mode 1 reel 2 发现 booster + bar tier hierarchy 倒置。Verify 没覆盖到。

每次都是 user 比 verify 早发现。**根因 = 我设计 verify 时没主动列 first principles**。这份 checklist 是堵 process 漏的 patch。

---

## Maintenance

每次新机台 onboarding 走 FIRST_MACHINE.md，最后一步必须：
1. Read 这份 checklist
2. 把每条对应的 verify 类别加到 `verify_<M>_design.py`
3. 每条对应的 cost component 加到 tune script

新机台第一轮 commit 前必须：
1. Run 这份 checklist 全部
2. 在 commit message 里 enumerate 每条结果
3. self critique 一段
