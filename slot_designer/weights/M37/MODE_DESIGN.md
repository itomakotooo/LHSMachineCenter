# M37 4-Mode 数值概览 + 玩家感性体验

> **上游**：[`DESIGN.md`](DESIGN.md)（Lightning-Link / Red-White-Blue 混血原型研究）；`project_slot_designer_mode_rtp_invariants.md`（跨机台 mode RTP 规则）；`project_slot_designer_hit_rate_deviation.md`（派生 mode hit rate 带宽规则）
> **下游**：每 mode `mode_<N>/weights.json`（实现层）；`M37_weights_reference.csv`（策划速查表）
> **状态**：2026-04-24 设计稿 **v1 shipped**（4 mode tuned + verified）
> **上游 bug 修复**：同次 ship 中修了 `apply_counts` drift bug（大负 diff 在 min_weight clamp 下丢 -7 → mode 5 ghost 6.7pp RTP gap；见 tests/test_tuner.py）

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

Post-tune 实际 analytic 数字（`python -m slot_designer.devtools.analytic_rtp`）：

| Mode | RTP | Hit rate | Per-hit avg | CV | 顶奖 1000× (1 in X spins) |
|---|---|---|---|---|---|
| 1 | **94.95%** | 15.17% | 6.26× | 6.68 | ~278k |
| 2 | **299.77%** | 22.99% | 13.04× | 5.39 | ~46k |
| 5 | **499.99%** | 22.65% | 22.07× | 4.58 | ~25k |
| 7 | **84.99%** | 10.36% | 8.20× | 7.52 | ~267k |

**关键变化**：
- Mode 2 vs 1：hit ×1.52，per-hit ×2.08 → 整体体验：**打击频率升 + 每 win 更厚**
- Mode 5 vs 2：hit 持平（×0.99），per-hit ×1.69 → 整体体验：**打击频率不变，但每 win 显著厚**
- Mode 7 vs 1：hit ×0.68，per-hit ×1.31 → 整体体验：**打击稀，但每 win 略厚**（冷但不寡淡）

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
