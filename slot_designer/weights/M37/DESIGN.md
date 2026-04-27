# M37 — 机台研究 + 玩家感性体验设计

> **Phase 1 产出**（FIRST_MACHINE.md v3）：跑 WebSearch 查业界对标 + 识别原型 + 剖析玩家感性 + 写每 mode 叙事。数值 target 的**依据**在这里；具体数字在 `MODE_DESIGN.md`。
>
> **研究日期**：2026-04-24 / 重审 2026-04-27

## 1. 机台原型识别（原创机台 — 无 1:1 对标）

**M37 = "Classic 3-reel 1-payline + 倍率 wild" 原创机台**

⚠ **明确：M37 是 LHS 原创机台，不是 1:1 抄某个商业机台**。设计时参考了两类成熟机制做 chassis 和符号集，但具体 paytable / RTP / 倍率档位 / 强制 (wild,grand,wild) re-roll 是自创的：

**Chassis 参考**（提供"骨架"）：
- **Classic 3-reel 1-payline**（IGT Red White & Blue / Bally Blazing Sevens 同代机型）—— 单 payline 中间行；3×3 grid 上下行做 near-miss 视觉效果
- 不抄 video slot 的多 payline / cluster pay / megaways 复杂结构 — 保 **classic 简洁性**

**符号机制参考**（提供"setting 美术 + 倍率层"）：
- **倍率 wild (mini/minor/major/grand)** —— 同样名字在 Aristocrat Lightning Link 等机里是 progressive jackpot 触发符号，但 **M37 把它降级成 base-game 倍率符号**：mini = ×2, minor = ×5, major = ×10, grand = ×100
- M37 的 grand 不是 progressive jackpot pool，是固定 ×100 倍率符号
- M37 没有 hold-and-spin bonus，没有 free spins，base game 一切搞定

**M37 自创设计点**：
- 倍率 wild **集中在 reel 2**（middle reel），普通 wild **集中在 reel 1+3**（outer reels）— 这种"倍率隔离 + wild 隔离"的 reel-positional asymmetry 是 LHS 自创结构，没在公开机台见过
- `(wild, grand, wild)` middle-row pattern 强制 **后端 re-roll**——禁止 pure-wild + grand 直达 1000× 顶奖，强迫 1000× 必须走 `high7-grand-high7` 路径，让顶奖路径"有故事 / 有 narrative"
- 顶奖 = `pay_id 1 × grand multiplier = 10 × 100 = 1000×` — 单 payline 机的 1000× 是 classic 范畴内合理顶奖（不是 video slot 那种 100,000× megajackpot）

**辅助数值设计的核心机台特征**：
1. **wild on outer reels** — 提供 substitution 让"差一个 high7"也能成 pay_id 1（high7-wild-high7）
2. **倍率 wild on middle reel** — 提供 multiplier 把 base pay 放大 2/5/10/100 倍
3. **pure-wild + 倍率 wild 组合** = pay_id 102/103/104（双外 wild + 中间倍率 wild），但 grand 这一档被 re-roll 屏蔽
4. **hit rate 由 booster_alone (pay_id 8/9) + side wild alone 共同支撑** — classic 机里没有 cherry 当 frequent reward，M37 用倍率 wild 自身当"frequent presence"

## 2. 业界基准 — 用作设计参考（不是抄）

> M37 是原创，不抄任何机台。下表只用作 chassis / hit-rate 参考。

| 机台 | RTP | chassis | 给 M37 的参考 |
|---|---|---|---|
| Red White & Blue (IGT) | 87% | Classic 3-reel 1-payline | **chassis 参考**: 单 payline 1000-combo scale |
| Blazing Sevens | 89% | Classic 1-line wild-boosted 7 | **wild 机制参考**: outer-reel wild 做 substitution |
| Money Storm | 92.5% | Feature-light base-heavy | **base-heavy 参考**: M37 也是 base-only no feature |

**Liberty Bell PAR sheet 启示**（[slotgamedesign.com](https://slotgamedesign.com/category/par-sheets/)）:
- Classic 3-reel 1-payline 数学基础: 10 symbols × 3 reels = 1000 combos / payline
- 顶奖 ≈ 0.1% rate × payline factor → 10⁻⁴ per spin 量级
- M37 的 1000× 顶奖目标 ≈ 1 in 60-100k spins（mode 1）— 在 classic 顶奖 rate 合理范围

**RWB family RTP 分布作为参考**（不是 M37 必须 match）:
- RWB Bar 31%, Cherry 16%, Seven 50% — 7-dominant
- M37 没 cherry，"frequent small reward" 由 booster_alone (pay_id 9) 接管
- M37 "Seven 家族角色" 由 high7 + 倍率 wild 共同扮演（high7 base 10× + booster 20-100× × 旁边 pay）

**Hit rate 参考**（classic 3-reel 1-payline 范围）:
- Classic 1-line 一般 hit 25-35%（cherry-heavy 机型）
- M37 hit 15-22% — 比传统 classic 略低，因为 M37 用倍率 wild 替代了 cherry 的 frequent role，单次 payout 平均比 cherry 高

## 3. 玩家感性分档 — 每个 win 档位的情感定位

**Low bucket (1-10× base)**：**Chase engagement**
- **1×** wild 孤立 / mixed bars (pay_id 7) — 几乎意识不到的"啊赢了"，维持 session 参与
- **2×** mini 孤立 / high7+7bar mix (pay_id 6) — 下意识的"小奖"，chase 感
- **3-5×** 3-1bar / 3-2bar / 3-3bar — 小 bar 3-match，classic 机台的基础命中
- **6-10×** 3-7bar / 3-high7（无 booster）— 中偏低小奖
- **情感**：不是"记忆点"，是"机台在跟我互动"的节奏感
- **每 100 spin 命中次数**：~10-12 次（占 hit rate 主体）

**Mid bucket (10-50×)**：**"咦有料" accept 点**
- **10×** 3-high7 / mini-boosted bar-combos / major 孤立 — 明显的"这把不错"
- **20-30×** mini-boosted high7 / 3-high7 + wild / minor-boosted bar — session 级 mid win
- **50×** minor-boosted high7 / minor-boosted pure-wild (pay_id 103) — **会开心出声那种**
- **情感**：玩家坐起来的那一刻。每 session 能触发 3-5 次
- **每 100 spin 命中次数**：~1-2 次（远低于 Low）

**High bucket (50-500×)**：**Session 记忆点**
- **100×** pay_id 8 (grand 孤立) / pay_id 102 (major 双 wild) / major-boosted high7 — 玩家会记住的 big win
- **200-500×** 尚未出现的组合（pay_id 2 × grand = 600×, pay_id 3 × grand = 500×）
- **情感**：拍照分享 / "今天运气不错"
- **每 100 spin 命中次数**：< 0.5 次（稀有）

**Top bucket (500-1000×)**：**Legendary moment / advertising hook**
- **500×** pay_id 3 × grand (3-3bar × grand) — 鲜见
- **1000×** pay_id 1 × grand (3-high7 × grand) — **机台的顶奖**，极稀有
- **情感**：发朋友圈 / 下次还想来 / "我在 M37 上中过顶奖"
- **每 100k spin 命中次数**：1-10 次（极稀有）
- **设计约束**：已验证 `(wild, grand, wild)` 被后端 re-roll 屏蔽 → 顶奖只能通过 `high7 + grand + high7` 路径，强化"legendary"感

## 4. Near-miss 设计

**核心 trigger**：Reel 2 有 mini/minor/major/grand 4 档 booster 符号。它们在 **reel 2 的 top/bot row（非 payline）** 出现时，玩家能清楚看到："差一行就是 grand 中间"。

**分析**：
- Reel 2 共 36 stops（假设），每档 booster ~3-5 stops
- **grand 在 window 里可见的概率**：≈ (grand stops × 3 row) / 36 = ~25-40% per spin
- **grand 真正在 payline 的概率**：~3% per spin
- 差距：~22-37pp 的 near-miss 频率 — **玩家每 2-4 spin 就"看到 grand 但没吃到"**

**这个是 M37 的感情 pull**，比任何数字都关键。Strip 设计时刻意保证：
- Grand 在 reel 2 的 top/bot row 分布不差于 middle row（Phase 5 joint SA 会自然保）
- High7 和 grand **垂直邻近**（grand 在 top 时下面是 high7 的概率提升）→ "差一行就中 legendary" 强感

**2-of-3 near-miss**（classic 机制）：
- 2 个 high7 在 payline + grand 在 reel 2 另一行 → "grand 都冒出来了还差一个 high7"
- 这类 event rate 目测应 ≈ 5-10% per spin

**参考**：[Near-miss psychology](https://pmc.ncbi.nlm.nih.gov/articles/PMC2790935/) — 研究证明 over-inflated near-miss 会增加玩家 commitment，但过度设计有 responsible-gaming 风险。M37 的 near-miss 来自 **booster 符号 window 可见度**，是"自然 near-miss"不是操控式的。

## 5. Win 的感性构成

> 这一节决定 bucket 分布的设计意图

**Mode 1（classic baseline）**：**Low-heavy 但有 Mid 节奏 + rare Top**
- 玩家每 100 spin 约 13 次 hit，其中：
  - ~10 次 Low（chase 感）
  - ~2-3 次 Mid（session 小记忆点）
  - ~0.5 次 High（session 大记忆点）
  - ~0.005 次 Top（lifetime story）
- 体验叙事："classic slot 节奏，偶尔看到 major/grand booster 带来惊喜"

**Mode 2（lucky）**：**所有 tier 都略密，但 top 仍稀有**
- Hit 22.5%（×1.7 mode 1），**per-tier 都略升** — Low 多了、Mid 多了、High 略多
- Top 跟 mode 1 相近（1000× 顶奖仍稀有）
- 体验叙事："机台今天热了 — 小奖密、booster 更常见、顶奖还是梦"

**Mode 5（feature buff — 对 M37 是 top-bucket buff）**：**Top/High tier 大爆**
- Base = mode 2 字节级一致（Low/Mid 跟 mode 2 一样）
- 但 **High 和 Top bucket 的命中率拉高** —— grand 在 payline 的概率提高 2-3×，major 命中提高 1.5×
- 体验叙事："mode 2 + 顶奖 moment 更常见"
- 玩家在 mode 5 能 reasonably 期待一次 session 见到 100-500× 大奖
- 1000× 顶奖仍然稀有但不是 lifetime 级

**Mode 7（slow grind）**：**小奖少，但大奖跟 mode 1 同**
- Low bucket 命中率**绝对降** 30-40%（pay_id 7/9 等小奖符号 marginal 砍）
- Mid/High/Top 命中率**跟 mode 1 一样**（3-high7 / major-boosted / grand 组合命中率不动）
- 体验叙事："小奖不来 grind 感重，但 mid/big win 跟 mode 1 一样 — 不是'冷死了'，是'节奏紧了'"

## 6. 跨 mode 差异化叙事（一句话版）

- **Mode 1 baseline**："classic 节奏，偶尔惊喜"
- **Mode 7 slow grind**："小奖少一点，大奖跟 mode 1 一样 — 节奏紧了"
- **Mode 2 lucky**："全程都热了 — 小奖密、booster 常见"
- **Mode 5 big-win buff**："mode 2 + 顶奖 moment 跳出 lifetime 级到 session 级"

## 7. Bucket 分布设计意图（per mode）

| Tier | Mode 1 | Mode 2 | Mode 5 | Mode 7 | 说明 |
|---|---|---|---|---|---|
| **Low (1-10×)** RTP 占比 | ~35% | ~30% | ~20% | **~25%**（比 m1 低，因为绝对降）| M7 only: Low 绝对击中率降 |
| **Mid (10-50×)** RTP 占比 | ~40% | ~40% | ~30% | ~45%（相对升）| M7: 绝对 = m1 |
| **High (50-500×)** RTP 占比 | ~20% | ~25% | **~40%** | ~25%（相对升）| M5 核心：加 high |
| **Top (500-1000×)** RTP 占比 | ~5% | ~5% | **~10%** | ~5%（相对升）| M5: grand-boosted 组合加厚 |
| **Total RTP** | 95pp | 300pp | 500pp | 85pp | 跨机台硬约束 |
| **Total hit** | 13% | 22.5% | 22.5% | **10-11%** | M7 low-hit |

> 注：Mode 2/5 的总 RTP 是 ×3+ mode 1，所以每 tier 的 pp 绝对值 ≈ (占比) × total RTP。例如 mode 5 Top bucket RTP = 10% × 500 = 50pp；mode 1 Top = 5% × 95 = 4.75pp。

## 8. 具体 hit rate 意图（per tier per mode）

| Tier | Mode 1 hit | Mode 2 hit | Mode 5 hit | Mode 7 hit |
|---|---|---|---|---|
| Low | ~10% | ~18% (×1.8) | ~15% (×1.5) | **~6% (绝对降 40%)** |
| Mid | ~2% | ~3.5% | ~4% | **~2% (同 m1)** |
| High | ~0.5% | ~0.8% | **~2% (×4 核心)** | **~0.5% (同 m1)** |
| Top | ~0.01% | ~0.01% | **~0.05%** | **~0.01% (同 m1)** |
| **Total** | **13%** | **22.5%** | **22.5%** | **~10%** |

**Mode 7 per-tier hit rate 约束**（per `project_slot_designer_hit_rate_deviation.md` 修订版）：
- Low: ~6%（绝对降 4pp from mode 1 的 10%）— 靠砍 1bar/2bar/wild-alone 的 marginal
- Mid/High/Top: 跟 mode 1 绝对一样（不动）— 保 7bar/high7/booster 的 marginal

## 9. 设计契约 + 约束

**跨机台硬约束**（不漂）：
1. Total RTP 95/300/500/85（严/宽/宽/严）
2. Strips 跨 mode 字节级一致
3. Mode 5 base = mode 2 base 字节级复刻
4. Mode 7 hit rate 规则：Low 降、Mid/High/Top 不动（per-bucket 绝对值约束）
5. Mode 2 total hit × 1.5-2（20-25%，**不是 ×3**）

**M37 机台特化**：
1. `(wild, grand, wild)` 被后端 re-roll 屏蔽 — evaluator 里加 check OR strip 设计保证 reel 1/3 在 grand 列不是 wild
2. `ReelSkin` 字段 = mode number（rawdata 里跟 _mode 同步）
3. Booster 符号（mini/minor/major/grand）**只在 reel 2**
4. Wild **只在 reel 1 + reel 3**（不在 reel 2）
5. Mode 5 的 +200pp 靠 **reel 2 booster 权重重新分配**（grand 拉高 + major 略拉）实现 — 不是 feature enhance

**代码扩展点**：
- `engine/symbol.py` 加 booster kind 或用 regular + multiplier 字段（mini=×2, minor=×5, major=×10, grand=×100）
- `engine/rules.py` 加 pay kinds：`line_3_same_with_center_booster`（col 1 booster × base mult）+ `center_booster_alone` + `side_wild_alone`
- `engine/evaluator.py` 加 re-roll check for `(wild, grand, wild)`
- 不需要 feature engine（M37 无 feature）
- 不需要改 emitter（只 emit ST=1）

## 10. 研究参考

**Slot 机台设计**：
- [slotgamedesign.com PAR sheet tutorial](https://slotgamedesign.com/2019/01/19/slot-math-tutorial-creating-par-sheets/) — Liberty Bell 10-symbol × 3-reel 1000-combo 基础
- [knowyourslots.com — Lightning Link / Dragon Link 机制分析](https://www.knowyourslots.com/all-about-lightning-link-dragon-link-and-dollar-storm/)
- [casinos.com Dragon Link 指南](https://www.casinos.com/guides/dragon-link-guide) — RTP 95.2%

**玩家心理 / near-miss 研究**：
- [PMC near-miss effect on gambling persistence](https://pmc.ncbi.nlm.nih.gov/articles/PMC2790935/)
- Harrigan (2009) "Slot Machines: Pursuing Responsible Gaming Practices for Virtual Reels and Near Misses"
- Lucas & Singh (2008) — CV 反相关 time-on-device

**内部参考**：
- `reference_classic_slot_rtp_distribution.md` — classic 1-line RTP/bucket 基准
- `reference_slot_design_research_keywords.md` — WebSearch keyword seed
- `weights/M1/README.md` / `weights/M15/MODE_DESIGN.md` — 两个参考机台的完整设计文档

Sources:
- [Dragon Link Guide (casinos.com)](https://www.casinos.com/guides/dragon-link-guide)
- [Lightning Link / Dragon Link overview (knowyourslots.com)](https://www.knowyourslots.com/five-things-to-know-about-lightning-link-dragon-link-and-dollar-storm/)
- [Near-miss gambling psychology (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC2790935/)
- [PAR sheets & classic 3-reel math (slotgamedesign.com)](https://slotgamedesign.com/2019/01/19/slot-math-tutorial-creating-par-sheets/)
- [Ways to land Grand on Lightning Link (knowyourslots.com)](https://www.knowyourslots.com/ways-to-landthegrand-or-major-on-lightning-link-and-dragon-link/)
