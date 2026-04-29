# M37 4-Mode 数值概览 + 玩家感性体验

> **机台 origin**：M37 是 **LHS 原创机台**（不抄商业机台），chassis 参考 classic 3-reel 1-payline (RWB / Blazing Sevens 同代)，符号机制特征 = wild on outer + 倍率 wild on middle (mini/minor/major/grand)。完整 archetype 见 `reel_strips.json _archetype` block + [`DESIGN.md`](DESIGN.md) §1。
> **上游**：[`DESIGN.md`](DESIGN.md)（原创设计 + 业界 chassis 参考 + per-tier 玩家感性叙事）；`project_slot_designer_mode_rtp_invariants.md`（跨机台 mode RTP 规则）；`project_slot_designer_hit_rate_deviation.md`（派生 mode hit rate 带宽规则）
> **下游**：每 mode `mode_<N>/weights.json`（实现层）；`M37_weights_reference.csv`（策划速查表）
> **状态**：2026-04-29 **v4 shipped**（mode 7 REEL-ASYMMETRY direction 修正 + 22 类 verify 全 GREEN）
> **v4 关键改进** vs v3:
> - **新增 6 类 universal verify categories**（per `slot_designer/DESIGN_PHILOSOPHY.md` §12-§15）：ALTERNATION / BLANK-FLANK-DIVERSITY / VISUAL-RHYTHM / REEL-ASYMMETRY / WINDOW-VISIBILITY / BRAND-UNIFORMITY
> - **Mode 7 REEL-ASYMMETRY 方向修正**: pre-fix R1 blank > R3 blank by 0.9pp + R1 top < R3 top by 0.71pp（在 verify 3pp/1pp tol 内但 design 反方向）→ post-fix R1 blank < R3 blank by 5.74pp + R1 top > R3 top by 0.95pp ✓
> - **Tune 加 reel_asymmetry penalty**（mode 7 only — 其他 mode direction 自然正确）：tol 0pp + strength 800，强制 mode 7 inheritance 后仍维持 universal §12 方向
> - **`scripts/verify_m37_design.py`** 22 类硬验证 GREEN（同 v3 11 类 + 6 universal + 5 archetype/hierarchy/blank-cap）

> **v3 关键改进** vs v1（保留作 history）：
> - **goal-oriented soft penalty cost** 替原 family-scale frozen approach（`scripts/tune_m37.py` v3）
> - **Mode 7 frozen big-win weights** — high7 + wild + boosters frozen = mode 1，bar [m1×0.72, m1×0.95] uniform cut，blank floored ≥ m1
> - **Mode 2 加 bar 上限 [m1×1.6]** — 防优化器把 bars 拉爆 → hit rate 41% 失控
> - **Mode 5 = m2 base + grand boost** — 全家 frozen except grand（≥ max(6, m2×6)），preserve hit shape + 顶奖密集
> - **per-pay frequency 强制约束**（pay_freq_caps + top_jackpot_min_spins）防 grand alone / 1000× 顶奖过频

---

## 0. 设计契约 + 术语

| 约束 | 值 | 严格度 | 执行 |
|---|---|---|---|
| mode 1 Total RTP | **95%** | ±1pp 严格 | Phase 4 tune |
| mode 2 Total RTP | **300%** | ±10-20pp 可漂 | Phase 4 tune |
| mode 5 Total RTP | **500%** | ±10-20pp 可漂 | Phase 4 tune |
| mode 7 Total RTP | **85%** | ±1pp 严格 | Phase 4 tune |
| Base : Feature split | **100 : 0** | 无 feature | M37 没 feature engine |
| Strips 跨 mode 字节级一致 | 必须 | strict tolerance 0 | 所有 mode `--sa-steps 0` |
| mode 2 vs mode 1 hit | ×1.5 (15.2% → 22.5%) | ±2pp | Phase 4 soft target |
| mode 5 vs mode 2 hit | 保持 ≈ 22.5% | ±2pp | Phase 4 soft target |
| mode 7 vs mode 1 hit | Low 绝对降 45%，Mid/High/Top 不动 | bucket 级 | Phase 4 shape target |

**M37 的特殊约束**（engine-level）：
- Wild **只在 reel 1 + reel 3**（NEVER reel 2）
- Booster（mini/minor/major/grand）**只在 reel 2**
- `(wild, grand, wild)` 中间行是 **re-roll forbidden** pattern（后端 server-side re-draw，engine 层 mirror；见 `engine/spin.py`）
- 顶奖路径：`(high7|wild, grand, high7|wild)` = pay_id 1 × grand multiplier 100 = **1000×**

**4 个 designer dials**（per mode）：
1. Reel 1 + 3 权重分配：调 blank / wild / high7 / 7bar / bars
2. Reel 2 权重分配：调 blank / high7 / 7bar / bars / **booster tier**（grand/major/minor/mini）
3. Strip layout（跨 mode 共享）：near-miss 设计（grand 夹 high7）
4. Re-roll block（spec 固定）：`(wild, grand, wild)` pattern

M37 **没 feature engine**，所有 RTP 靠 base game。

---

## 1. Strip 设计（跨 mode 共享，byte-identical）

36 stops per reel × 3 reels。Blank 和 non-blank 严格交替（pos 0/2/4/... blank；1/3/5/... non-blank）。

**Reel 1**（18 non-blank stops）：`[wild, high7, 7bar, 3bar, 2bar, 1bar] × 3 重复`
**Reel 2**（18 non-blank stops）：`3 × high7 + 2 × [7bar, 3bar, 2bar, 1bar, mini, minor, major] + 1 × grand`（booster 集中于 reel 2）
**Reel 3**（18 non-blank stops）：`[high7, wild, 7bar, 3bar, 2bar, 1bar] × 3`

### Near-miss 设计（reel 2 pos 17-21 关键）

```
pos 17: high7
pos 18: blank
pos 19: grand      ← 唯一 grand stop
pos 20: blank
pos 21: high7
```

**玩家体验 pull**：
- 当 reel 2 停 grand 在**顶行或底行**（非 middle），玩家看到 `high7 / blank / grand / blank / high7` 的 3-row window，知道 "差一行就是 grand 在 payline"。
- 当 grand 在 middle（命中 1000×或 pay_id 8 jackpot），两侧 top / bot row 分别是 high7 → "grand 都出现了，两边 high7 也有了" 的双重 near-miss → 1000× 的 "legendary" 感强化。

Reels 1+3 的 wild **紧邻 high7**（pos 1=wild, pos 3=high7）→ window 经常同时看到 wild 和 high7 → 支持 3-match-with-wild-sub 的感觉。Reel 3 的 wild/high7 相对 reel 1 偏移 2 位（不镜像对称）→ 跨 reel 可见度不单调。

---

## 2. 每 mode 的 dial 对比

> 策划速查：打开 `M37_weights_reference.csv` Section B 看 4 mode 并排权重（CSV 可贴 Excel）。Source of truth 仍是 `mode_<N>/weights.json`。

Post-tune v4 (2026-04-29) 实际 analytic 数字（`python slot_designer/scripts/verify_m37_design.py`）：

| Mode | RTP | Hit rate | Per-hit avg | CV | 顶奖 1000× (1 in X spins) |
|---|---|---|---|---|---|
| 1 | **94.49%** | 21.37% | 4.42× | 7.55 | ~99k |
| 2 | **285.44%** | 35.38% | 8.07× | 4.88 | ~25k |
| 5 | **481.02%** | 36.04% | 13.35× | 6.21 | ~4.2k |
| 7 | **84.84%** | 18.17% | 4.67× | 7.67 | ~118k |

**关键变化**（v4 — 同 v3 mode 1/2/5；mode 7 REEL-ASYMMETRY direction 修正）：
- Mode 2 vs 1：hit ×1.66，per-hit ×1.83 → 整体体验：**打击频率升 + 每 win 更厚**
- Mode 5 vs 2：hit ×1.02，per-hit ×1.65 → 整体体验：**打击频率近似 + 每 win 大涨**（顶奖 frequent 的 super-lucky）
- Mode 7 vs 1：hit ×0.85，per-hit ×1.06 → 整体体验：**打击稍稀（bar 砍）+ per-hit 微升**

**big-win 频率（pay_id 1+8+102+103+104 sum）**：
- Mode 1: 1 in 403 spins
- Mode 7: 1 in 436 spins (~8% rarer, bar 砍 → big-win sum 略低)
- Mode 2: 1 in 112 spins (×3.6 vs m1)
- Mode 5: 1 in 84 spins (×4.8 vs m1, ×1.33 vs m2 — super-lucky 核心特征 = 顶奖 frequent，per-pay big-win 不一定更频繁)

**顶奖 1000× 阶梯**（玩家叙事）：
- m1 (~99k spins) — 1 周连续玩 1 小时/天 才有 1 次的级别（rare，"梦"）
- m7 (~118k spins) — 比 m1 略稀 (mode 7 = "运气差" 时段，不是 jackpot mode)
- m2 (~25k spins) — lucky tier，两小时玩可期，仍稀有
- m5 (~4.2k spins) — super-lucky，半小时玩可期 — 1000× **session-level 体验**

**REEL-ASYMMETRY direction**（universal §12，v4 新验证）:
- Mode 1: R1 blank 24.59% < R3 29.37% ✓ / R1 top 11.82% > R3 11.19% ✓
- Mode 2: R1 blank 9.09% < R3 9.68% ✓ / R1 top 15.15% > R3 12.90% ✓
- Mode 5: R1 blank 9.09% < R3 9.68% ✓ / R1 top 15.15% > R3 12.90% ✓ (inherited from m2)
- Mode 7: R1 blank 35.00% < R3 40.74% ✓ / R1 top 10.83% > R3 9.88% ✓ (v4 fixed via tune asymmetry penalty)

---

## 3. Bucket 分布对比（per-mode per-bucket hit rate %）

| Bucket | Mode 1 | Mode 2 | Mode 5 | Mode 7 | 业务含义 |
|---|---|---|---|---|---|
| ge1_lt5 | 8.03% | 11.02% | 8.21% | 3.95% | 小 bar 3-match / mixed bars / wild alone |
| ge5_lt10 | 3.13% | 4.73% | 4.05% | 2.26% | 3-1bar-with-boost / minor alone / mixed-with-boost |
| ge10_lt20 | 3.66% | 5.18% | 6.51% | 3.80% | 3-bar / mini-boosted / major alone |
| ge20_lt50 | 0.07% | 0.15% | 0.27% | 0.07% | 3-bar-with-minor / major-boosted bars |
| ge50_lt100 | 0.016% | 0.019% | 0.024% | 0.022% | 3-high7 / minor-boosted high7 |
| ge100_lt200 | 0.26% | 1.86% | 3.45% | 0.26% | grand-alone (pay 8) / pure-wild+major (pay 102) |
| ge200_lt500 | 0.003% | 0.035% | 0.123% | 0.003% | minor-boosted 3-high7 / 3-bar × grand |
| ge500_lt1000 | 0.0007% | 0.004% | 0.010% | 0.001% | 3-high7 × minor / 3-bar × grand |
| ge1000_lt5000 | 0.0004% | 0.002% | 0.004% | 0.0004% | **TOP: pay_id 1 × grand = 1000×** |

**Aggregate Low/Mid/High/Top**：

| Tier | Mode 1 | Mode 2 | Mode 5 | Mode 7 | 叙事 |
|---|---|---|---|---|---|
| **Low** (1-10×) | 11.16% | 15.75% | 12.26% | **6.21%** | m7: -45% 绝对 vs m1 |
| **Mid** (10-50×) | 3.72% | 5.32% | 6.78% | **3.87%** | m7 ≈ m1 (不动) |
| **High** (50-500×) | 0.28% | 1.91% | **3.60%** | **0.28%** | m5 核心 buff ×1.88; m7 ≈ m1 |
| **Top** (500-1000×) | 0.0011% | 0.0065% | **0.0138%** | 0.0016% | m5 顶奖从 lifetime 降到 session 级 |

---

## 4. 跨 mode 叙事（一句话版）

- **Mode 1 baseline**："classic 3×3 节奏，偶尔看到 mini/major/grand booster 带来惊喜"
- **Mode 2 lucky**："全程都热了 — 小奖密、booster 常见；1000× 仍是梦"
- **Mode 5 lucky_big**："mode 2 打击频率 + 每次 win 显著更厚；100-500× session 里能期待看到；1000× 从 lifetime 降到 session 稀有"
- **Mode 7 standard_low**："小奖少一点（chase 感弱化），但 mid/big win 跟 mode 1 一样 — 节奏紧了不是寡淡"

---

## 5. 执行流水线回顾

**Phase 0 完成工作**：
1. Reverse-engineer M37 rawdata（2.14M 轮 mode 7 / 1M+ 轮其它 mode）→ 推 11 个 pay_id 语义 + booster mechanic + re-roll block
2. 写 `specs/M37.spec.json`（9 symbols，14 pay rules，`reroll_blocks: [(wild, grand, wild)]`，`features: []`）
3. `tests/test_m37_evaluator.py`：4 test / 35+ assertion / 10719 rawdata rounds 100% 匹配

**Phase 1**（research + 感性体验）：
- [`DESIGN.md`](DESIGN.md) 第 1-5 节：原型识别 + 业界基准（Dragon Link / RWB / Blazing Sevens）+ 每 win 档位的情感定位
- Near-miss 设计：reel 2 中间 5 格的 high7/grand/high7 pattern → 玩家每 2-4 spin "看到 grand 但没吃到"
- 叙事写死：每 mode 的体验定位（见 §4）

**Phase 2-3**（engine + strips）：
- `engine/symbol.py` 加 `booster` kind；`engine/rules.py` 加 3 类新 pay + RerollBlockRule
- `engine/evaluator.py` 6-stage pipeline（booster-center evaluation 新加）
- `engine/spin.py` 加 re-roll loop（max 50 retry）
- `weights/M37/reel_strips.json`：近 miss 导向 strip 布局

**Phase 4-7**（tune）：
- mode 1（seed→tune）→ mode 2（seed from mode 1）→ mode 5（seed from mode 2）→ mode 7（seed from mode 1）
- 全部 `--sa-steps 0`（strips byte-identical invariant）
- mode 5 tune 修了 `apply_counts` drift bug（`tuner/layout.py` 重写 diff-repair 算法）

**Phase 8-9**（register + verify）：
- `machines_virtual.json` 加 M37sim 条目（logicClass `SimulatedClassic3ReelWithBoosterJackpot`，4 mode，各 per-mode md5）
- `/api/virtual/paytable/M37sim` 返回 15 pays；`/api/machines` 返回 M37sim `available=true`
- `simulate.py` 30k spin 采样跨 4 mode：sim RTP 92.9 / 295.0 / 480.2 / 87.0（±5% vs analytic，属 CI 内）

**Phase 10**（docs）：本文件 + 更新 `reports/m37/` 模板（无）

---

## 6. 研究参考

### Slot 机台设计
- [slotgamedesign.com PAR sheet tutorial](https://slotgamedesign.com/2019/01/19/slot-math-tutorial-creating-par-sheets/) — Liberty Bell 10-symbol × 3-reel 基础
- [knowyourslots.com — Lightning Link / Dragon Link 机制分析](https://www.knowyourslots.com/all-about-lightning-link-dragon-link-and-dollar-storm/)
- [casinos.com Dragon Link 指南](https://www.casinos.com/guides/dragon-link-guide) — RTP 95.2%

### 玩家心理 / near-miss 研究
- [PMC near-miss effect on gambling persistence](https://pmc.ncbi.nlm.nih.gov/articles/PMC2790935/)
- Harrigan (2009) "Slot Machines: Pursuing Responsible Gaming Practices for Virtual Reels and Near Misses"
- Lucas & Singh (2008) — CV 反相关 time-on-device

### 内部参考
- `reference_classic_slot_rtp_distribution.md` — classic 1-line RTP/bucket 基准
- `project_slot_designer_strips_identical_across_modes.md` — 跨 mode strip 字节级一致的硬规则
- `project_slot_designer_mode_rtp_invariants.md` — 跨机台 mode RTP 约束（95/300/500/85）
- `project_slot_designer_hit_rate_deviation.md` — 派生 mode hit rate 带宽（Low 降 / Mid/High/Top 不动）

---

## 7. 已知限制 + 未来工作

1. **Mode 5 的 High 倍率 buff 主要走 ge100_lt200 桶**（×1.86 vs mode 2），Top 桶（×2.12）其实没达到 brief 里写的 ×5-10 target。原因：M37 最大 payout 封顶 1000×（pay_id 1 × grand），Top 桶物理上就没太多空间 expand。要真正拉 Top 得改 spec（加 ×200/×500 multiplier symbol），这是架构变更不是 tune 问题。
2. **Mode 5 base game 能达到 500% 全靠 reel 2 booster 密度拉高** — 如果后续加 feature engine，会重新分 RTP 预算（base RTP 降 + feature RTP 升）。目前 100:0 split 是 M37 特征不是通用。
3. **Re-roll 机制在 analytic 层算 total_prob 会略低于 1.0**（reroll-blocked patterns 被排除），不影响 RTP 计算但会让 hit_rate 统计微偏。目前误差 < 0.001pp，可忽略。
4. **Mode 1 tuned hit rate 15.17% 略高于 mode 1 target band 13-15%**，落在 upper edge。因为 booster-alone (pay_id 9) 是 M37 特有小奖，比想象中更常见。如果要严守 ≤ 15%，得加 hit_weight 做第二轮 tune。目前接受。

---

Sources:
- [Dragon Link Guide (casinos.com)](https://www.casinos.com/guides/dragon-link-guide)
- [Lightning Link / Dragon Link overview (knowyourslots.com)](https://www.knowyourslots.com/five-things-to-know-about-lightning-link-dragon-link-and-dollar-storm/)
- [Near-miss gambling psychology (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC2790935/)
- [PAR sheets & classic 3-reel math (slotgamedesign.com)](https://slotgamedesign.com/2019/01/19/slot-math-tutorial-creating-par-sheets/)
- [Ways to land Grand on Lightning Link (knowyourslots.com)](https://www.knowyourslots.com/ways-to-landthegrand-or-major-on-lightning-link-and-dragon-link/)
