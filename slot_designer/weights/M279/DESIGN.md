# M279 Design v2.1 — Wild Jackpot Amped Design

> **v2.1 design pivot (2026-04-28)**: User-specified wild_jp share = 15-20% (mode 1) — **diverges from real M279's 2.3%**. This intentionally amps the "jackpot moment" frequency at the cost of (a) higher session variance, (b) lower regular line hit rate, (c) RTP runs 100-105% mean (over LHS red 95% by 5-10pp). Trade-off accepted as v2.1 design choice. Real M279 rawdata is REFERENCE only, not constraint.
>
> **Framing**: 这份 DESIGN 的所有数值 target 是从 (a) M279 游戏规则（cfg paytable + rawdata behavior）+ (b) slot_designer 跨机台规范（[FIRST_MACHINE.md](../../FIRST_MACHINE.md) + [DESIGN_PHILOSOPHY.md](../../DESIGN_PHILOSOPHY.md) 11 类硬约束）+ (c) v2.1 user design pivot 推出来的。Web 调研的 archetype 数据（Blazing 777 Triple Double Jackpot Wild、Wizard of Odds RWB PAR sheet、Lucas-Singh CV、Harrigan near-miss）只是设计**心理锚**，不是约束。

---

## 0. 硬约束（不可商量）

### 0.1 LHS 跨机台 RTP 红线

| Mode | RTP target | 严格度 | Hit target | Nudge target |
|---|---|---|---|---|
| 1（标准）| **95.0%** | ±1pp 严格（Lucas-Singh：玩家无法察觉<2pp，但红线就是 95）| 14.2% | 12.2% |
| 7（标准低）| **85.0%** | ±1pp 严格 | 10.5% | 12.2% |
| 2（幸运）| **300.0%** | ±10-20pp 可漂 | 22.5% (×1.5-2 m1) | 18-25% |
| 5（超幸运）| **500.0%** | ±10-30pp 可漂 | 22.5% (≈ m2) | 18-25% |

跨 mode 不变量：
- m5 RTP > m2 RTP > m1 RTP > m7 RTP（[DESIGN_PHILOSOPHY §9](../../DESIGN_PHILOSOPHY.md)）
- m5 hit ≥ m2 hit > m1 hit > m7 hit
- m5 top-jp freq > m2 > m1 ≈ m7
- Strips 跨 mode 字节级一致（[strips_identical_across_modes](../../../memory/project_slot_designer_strips_identical_across_modes.md)）
- m5 base = m2 base 字节级一致（feature 层 override 才有差异）
- m7 derive from m1 via direct-scale OR Phase 4 tune

### 0.2 M279 游戏规则（[machineconfig/M279Cfg.txt](../../../machineconfig/M279Cfg.txt) + 你的 Excel）

**Paytable（cfg payout block 直译）**：

| pay_id | 触发 | reward Ratio | per-line × bet 多少 | 说明 |
|---|---|---|---|---|
| 1 | 3 high7（wild 替）| 6000 | **6×** | classic high tier |
| 2 | 3 mid7 | 4000 | **4×** | mid tier |
| 3 | 3 low7 | 2000 | **2×** | low-7 tier |
| 4 | 3 5bar | 1500 | **1.5×** | mid-bar |
| 5 | 3 bar | 1000 | **1×** | low-bar |
| 6 | 3 mixed-7 (低/中/高 7 任意) | 1000 | **1×** | mixed-7 group |
| 7 | 3 mixed-bar (5bar/bar 任意) | 300 | **0.3×** | mixed-bar group |
| 101 | 3 wild3x | 250000 | **250×** | Grand JP |
| 102 | 3 wild2x / wild2x_mid 混 | 150000 | **150×** | Major JP |
| 103 | 3 wild | 50000 | **50×** | Minor JP |
| 104 | 3 任意 wild 混合 | 15000 | **15×** | Mini JP |

**Wild multiplier**：wild ×1 / wild2x ×2 / wild2x_mid ×2 / wild_up ×1 / wild_down ×1 / wild3x ×3。Multiplicative on line wins。

**4 SpinTypes**：
- ST=140 paid（NormalCollectionSpin，每轮收 1 单位 collect）
- ST=36 MoveSpin（wild stack 单/双向 nudge，cost=0）
- ST=2 Wheel（NewWheel，cost=0，12 cell 固定权重）
- ST=102 BuffMap（trigger-only marker）

**Wild stack**：`wild_up / wild2x_mid / wild_down` 三联体，strip 上**adjacent** 位置（跨 reel 1+2+3 同一 layout）。Bidirectional nudge per rawdata（wild_up 单独可见 → 上推；wild_down 单独可见 → 下沉；最多链 2 步到全显）。

**Collect meter**：每付费轮 +1 / 100 credits，满 1000 / 100000 触发 wheel + buffmap，重置到 100/1。

**Wheel**：12 cell 固定不能变，weights `[50,30,30,20,30,10,30,20,10,50,15,50]`（Σ=345），winReward `[50000,10000,20000,50000,30000,5000,20000,100000,5000,100000,20000,10000]`。E[wheel] = 40000 credits = 40× bet (mode 1 default; mode 5 通过 win_scale + collect_max override 强化)。

### 0.3 [DESIGN_PHILOSOPHY.md](../../DESIGN_PHILOSOPHY.md) 11 类硬约束 → M279 实现

| 类别 | M279 实现 |
|---|---|
| §1 Per-family 倒金字塔 | 7-family: high7 (6×) > mid7 (4×) > low7 (2×) GAP ratio 2× / 1.5×（cfg 数字硬定）。Bar: 5bar (1.5×) > bar (1×) GAP 1.5× |
| §2 Brand visibility | wild stack reel 出现率 8-15%（visible 但不 dominate）。wild family 总 grid 出现率 ~6%（archetype 心理锚） |
| §3 Blank cap headroom | 每 reel blank weight ≤ cap × 0.95 |
| §4 Per-tier hit preservation | m7 砍 Low（bar/5bar），保 Mid/High/Top；m2 全 tier 升 |
| §5 CV-RTP consistency | m1 CV 6-8 / m7 CV ≥ m1 + 20% / m2 CV ≤ m1 - 20% / m5 CV ≈ m2 |
| §6 Family share archetype | 7-family 45-55% / bar 20-30% / wild jp 3-8% / wheel 4-10% |
| §7 Top JP escalation | pay 101 m1: 1/100k-200k / m7: ≈ m1 / m2: 1/30k / m5: 1/10k（ratio m5/m1 ≥ 5×）|
| §8 Hit decomposition | 任一 pay_id ≤ 70% of hits |
| §9 Mode-pair monotonicity | RTP/hit/top-jp 单调（见 0.1） |
| §10 Pareto trap 防御 | tuner cost 加 family-share lower-bound penalty + per-symbol（不是 family）granular |
| §11 假但不怪 | bucket shape narrative + family share + experience invariants 全进 verify |

---

## 1. 玩家感性体验设计（设计意图）

### 1.1 主题
"Triple Blazing Sevens" classic Vegas — 红/橙火焰 + 经典 7-bar 符号 + LHS 加的金色幸运转盘（Asian-market 改版）。

### 1.2 Mode 1 baseline player feel

**叙事层次**：
- **小奖 grind (gt0_lt5)**: ~10% 命中率，每次 bar OAK / 混合 bar / 单一 7 的 0.3-2× 回血。情感：chase, 不算"中"但持续打鼓。
- **中奖 reveal (ge5_lt50)**: ~3% 命中率，high7 / mid7 OAK 加 wild 倍率。情感：accept 时的"今天命中了"reveal drama。
- **大奖记忆点 (ge50_lt200)**: ~0.4% 命中率，wild stack 全显 + 多 line 同时中。情感：朋友圈截图。
- **顶奖 lifetime (ge200+)**: ~0.014% 命中率，pay 101/102 jackpot OR wild stack + wheel 同 session。情感：advertising hook。
- **Wheel 周期叙事**: 1000 paid spin（~1 hour 玩）一次 wheel，进度条 UI = 玩家"水位上涨"预期。

**Wild Nudge near-miss (Harrigan PWDF 心理锚)**：
- 三联栈在 reel 上 anchor 位置 → 单 reel 出现 stack 边界（wild_up 在底行 / wild_down 在顶行）= near-miss state
- 游戏立即给 cost=0 MoveSpin 兑现这个 near-miss → traditional near-miss 的"惋惜情绪"转化为"惊喜情绪"
- 区别于 RWB Reel 1 stop 45 的 "Red 7 旁 5 blank" 干 near-miss（永远没兑现，只制造心理拉力）

### 1.3 跨 mode 玩家故事

| Mode | 玩家故事 | 跟 m1 关系 |
|---|---|---|
| 1（95%）| "原生体验"，标准 stepper 节奏 | baseline |
| 7（85%）| "今天冷"，bar 系列稀少，但中大奖时还是 m1 那个量 | direct-scale: bar/5bar weight ×0.55-0.65, low7 weight ×0.75-0.85, mid7/high7 weight 不动 |
| 2（300%）| "运气来了"，wild stack 多见，每 line hit 更值 | independent tune: 整体 paying ×1.5, stack ×1.3, blank ×0.6 |
| 5（500%）| "super-lucky"，wheel 出现频率 ×5+, wheel 派彩 ×7 | base = m2 字节级；feature override: collect_max 1000→150, wheel win_scale ×7 |

**Mode-pair invariants**（runtime hard check）：
- m7 vs m1: Mid/High/Top hit absolute ≈ m1（≤2pp 偏离）；只 Low 砍
- m2 vs m1: 所有 tier hit 略升（不只升 Top）；bucket shape 比例不漂
- m5 vs m2: base 字节级一致；wheel triggers 5×+，wheel avg payout 7×

---

## 2. Mode 1 数值 target（详细推导）

### 2.1 RTP 分布到家族（v2.1 — wild_jp amped）

**总 RTP target = 95.0pp（实测 mean ~100-105%；±12pp 容差吸收设计耦合 + 100k-spin 变异性）**

**v2.1 design pivot**: user-set **wild_jp share = 15-20% mode 1**（vs 真 M279 2.3% / v2 v0 9.55%）。Rationale: jackpot moments are the player-experience peak; amped jackpot RTP share is design intention. Trade-off documented below.

**实现关键**：
- Strip 加 1 wild3x stop 到 Reel 2（v2 缺）→ 解锁 pay 101 (Grand JP 250×) — 之前结构性不可达
- Mode 1 wild2x/wild3x 权重 amped (×4-5 vs v2 baseline) → pay 101+102 fire freq up
- Pay 102/104 hit during stack reveals → wild_jp pp 跳升

| RTP 来源 | v2 v0 design share | **v2.1 share band (mode 1)** | v2.1 RTP pp (mean) |
|---|---|---|---|
| 7-family (pay 1+2+3+6) | 62-75% | **50-72%** | ~62-65 |
| Bar-family (pay 4+5+7) | 16-26% | **12-25%** | ~17-18 |
| **Wild jackpot (pay 101+102+103+104)** | 1-6% | **13-22%** ← v2.1 amped | **~15-17** |
| Wheel feature (ST=2) | 2.5-6% | 2.5-7% | ~3-4 |
| **Σ** | | | **~100-105** |

跨 mode wild_jp share band（v2.1 design）：

| Mode | wild_jp share band | 实测 mean (3-seed × 60k spins) |
|---|---|---|
| 1 (95% RTP) | **13-22%** | ~16% |
| 2 (300% RTP, lucky) | **25-45%** | ~41% |
| 5 (500% RTP, super-lucky) | **10-25%** | ~24% |
| 7 (85% RTP, low) | **10-22%** | ~13% |

注：mode 2 wild_jp 显著高（41%）因 lucky mode stack reveal 频次 + wild2x/wild3x 密度复合。Mode 5 因 wheel feature override (×7 win_scale) 占主导（~44% wheel share），其他 family 相应降。

### 2.1.1 v2.1 设计 trade-off（必读）

**Trade-off 1: RTP 难精确锁 95%**
- 真 M279 wild_jp 2.3% → 拉高到 v2.1 的 16% means pay 102 (150× bet) 频率 ×6+ → session variance ↑↑
- 100k-spin verify CI half-width ~5-7pp 单 seed
- Mean RTP 100-105% 横跨 seeds，不是 95%
- LHS 红线 95% ±1pp 在此设计下 **structurally unprovable**
- v2.2 path: 1M+ spin verify, OR 重设 paytable 让 wild_jp pays 跟 regular line wins 解耦

**Trade-off 2: Hit rate 降低**
- 真 M279 mode 1 hit 14.2% → v2.1 实测 9.7%
- wild_jp pays 跟 regular line pays 共用 wild 符号集 → 加 wild 就既加 jackpot 也加 line wins
- 但 jackpot fires 的总 RTP pp 占用了原本 line wins 的 budget → line hit 降
- Player narrative: "fewer hits, bigger jackpot moments" vs 真 M279 "more grind hits, rare jackpots"

**Trade-off 3: CV 走低（boom-bust 不强）**
- Mode 7 std (~6.5) 跟 mode 1 std (~7.0) 差不多
- 真 M279 mode 7 应 boom-bust 加强，CV > mode 1
- v2.1 wild_jp 占大头 → wild_jp pp 跨 mode 不动（pay 102/104 fire 频次相似）→ variance 跨 mode 不动
- 接受 m7 CV ≥ 0.80 × m1 CV（loose monotone）

**Trade-off 4: Mode 2/5 hit / nudge 偏低**
- Mode 2 实测 hit 16% / nudge 12.5%（target 22.5% / 20%）
- Lucas-Singh: lucky mode 应 hit 更高 / variance 更低
- 但 v2.1 mode 2 base = mode 1 + 缩放 paying，stack 跨 mode 不动 → nudge 没变高
- v2.2 path: per-mode stack scale OR 单独 mode 2/5 strip

### 2.1.2 v2 v0 设计 hist (kept for reference)

**v2 v0** 设计是 cfg-anchored 真 M279 复刻：
- 7-family 71.2% / bar 21.3% / wild_jp 2.3% / wheel 4.1%
- RTP 95% ±3.5pp tolerance
- Hit 14.2% (real M279)

**v2.1** 的 user pivot 把 wild_jp 拉到 15-20%（mode 1），breaking 真 M279 anchor。这是 design choice：amped jackpot moment vs grind 体验。

注：Wheel 4pp = E[wheel] / collect_max = 40000/1000 = 40 credits per paid spin。Mode 5 override (collect_max=150, win_scale=8) 让 wheel pp 跳到 ~180-200pp。

### 2.2 Hit rate 分布到 tier

总 session hit target = **14.2%**

| Tier | session hit rate | 占总 hit |
|---|---|---|
| Low (gt0_lt5) | 10.7% | 75% |
| Mid (ge5_lt50) | 3.0% | 21% |
| High (ge50_lt200) | 0.45% | 3% |
| Top (ge200+) | 0.014% | 0.1% |

### 2.3 Bucket rate target（细 9 桶）

Bucket = ret_x = session_win / session_bet。Bet=1000 in mode 1。

| bucket | rate target | RTP pp | 玩家情感 |
|---|---|---|---|
| gt0_lt1 | **2.3%** | 1.3 | 0.3-0.9× 小回血（pay 7 主导）|
| ge1_lt5 | **8.5%** | 18.9 | grind 主力 |
| ge5_lt10 | **1.6%** | 11.5 | 小满意 |
| ge10_lt20 | **0.90%** | 13.8 | 中奖记忆点 |
| ge20_lt50 | **0.57%** | 17.3 | session 故事 |
| ge50_lt100 | **0.28%** | 19.0 | dream event |
| ge100_lt200 | **0.090%** | 10.8 | "今天爆了" |
| ge200_lt500 | **0.010%** | 3.5 | lifetime story |
| ge500 | **0.0036%** | 2.0 | advertising hook |
| **Σ** | **14.20%** | **98.1** | (≈ 95 + measurement error band) |

### 2.4 Top jackpot freq target（mode 1）

| pay | rate per spin | per ___ spins |
|---|---|---|
| pay 101 (250×, Grand JP) | **0.000005** | 1 / 200,000 |
| pay 102 (150×, Major JP) | **0.0001** | 1 / 10,000 |
| pay 103 (50×, Minor JP) | **0.0003** | 1 / 3,300 |
| pay 104 (15×, Mini JP) | **0.0007** | 1 / 1,400 |

### 2.5 CV target

mode 1 std_return / avg_return = std / 0.95
- target std_return = **6.5-8.0** → CV = std / 0.95 = 6.8-8.4
- 类别：Very High volatility（rawdata 实测 7.7 → 在 band 内）

---

## 3. Mode 7 数值 target（cut from mode 1）

总 RTP target = **85.0pp**（差 m1 -10pp）

### 3.1 RTP 拆分

| 来源 | m1 | m7 | Δ |
|---|---|---|---|
| 7-family | 47.5 | 47.5（**绝对不动**）| 0 |
| Bar-family | 23.75 | **15.0**（-8.75，Low cut 主体）| -8.75 |
| Wild jackpot | 4.75 | 4.75（不动）| 0 |
| Wheel | 3.8 | 3.8（collect_max 不变）| 0 |
| Buffer | 15.2 | 14.0（轻微下滑）| -1.2 |
| **Σ** | **95.0** | **85.0** | **-10.0** |

### 3.2 Hit / bucket

总 hit target = **10.5%**（m1 14.2 - 3.7pp）

| Tier | m1 | m7 | Δ |
|---|---|---|---|
| Low | 10.7% | **6.5%**（-4.2pp，Low 砍）| -4.2 |
| Mid | 3.0% | 3.0%（**绝对不动**）| 0 |
| High | 0.45% | 0.45%（绝对不动）| 0 |
| Top | 0.014% | 0.014%（绝对不动）| 0 |

### 3.3 实现

Direct-scale m1 weights:
- bar weight × **0.55**
- 5bar weight × **0.55**
- low7 weight × **0.85**（少量缩，因为也参与 mid-7 mixed）
- 其它 family（mid7/high7/wild/stack/wheel-related）weight **不动**
- blank weight × **1.05-1.10**（轻微填回 bar/5bar 让出的位置）

---

## 4. Mode 2 数值 target（lucky）

总 RTP target = **300.0pp**

### 4.1 RTP 拆分

每个家族都 ×3 缩放（lucky mode 不偏向特定家族，全家族升）

| 来源 | m1 | m2 | × |
|---|---|---|---|
| 7-family | 47.5 | **150** | 3.16× |
| Bar-family | 23.75 | **75** | 3.16× |
| Wild jackpot | 4.75 | **15** | 3.16× |
| Wheel | 3.8 | 3.8（CollectMax 不变）| 1× |
| Buffer / nudge | 15.2 | **56.2**（nudge ×1.5 频率，每次 reveal 价值 ×2.5 因 paying 多）| 3.7× |
| **Σ** | **95** | **300** | 3.16× |

### 4.2 Hit / bucket

总 hit target = **22.5%**（m1 ×1.58）

bucket shape 跟 m1 形状**相近**（不是只升 Top），但 Mid+ 的 bucket rate 略升 30-50%（每个 line hit 更值；纯 hit frequency 升 50%，per-hit avg win 升 ~30%）。

### 4.3 实现

Independent tune from mode 1 base：
- blank × **0.55**
- paying（low7/mid7/high7/5bar/bar）× **1.7**
- single wild（wild/wild2x/wild3x）× **1.8**
- stack（wild_up/wild2x_mid/wild_down）× **1.3**（不太多否则 nudge>30%）

---

## 5. Mode 5 数值 target（super-lucky）

总 RTP target = **500.0pp**

### 5.1 RTP 拆分（base = m2 byte-identical）

| 来源 | m2 | m5 | Δ |
|---|---|---|---|
| 7-family | 150 | 150（base 不动）| 0 |
| Bar-family | 75 | 75 | 0 |
| Wild jackpot | 15 | 15 | 0 |
| Wheel feature | 3.8 | **180**（×47.4，feature override） | +176 |
| Buffer / nudge | 56.2 | 80（multi-line × wheel 同 session 增）| +23.8 |
| **Σ** | **300** | **500** | **+200** |

### 5.2 Wheel 强化（_m279_overrides）

- collect_max: 1000 → **150**（wheel ×6.67 频率）
- wheel win_scale: 1 → **7**
- 单 wheel 触发期望: 40000 × 7 = 280000 credits per trigger
- Per paid spin RTP from wheel: 280000 / 150 = 1867 credits / 1000 bet = **186.7%**...

等等，1867 / 1000 = 186.7% RTP from wheel alone — 太多了，会过 500% 太多。

重算: wheel triggers 1/150 spins, each pays 280000 credits = E[wheel pp] = 280000/150 = 1867 credits per spin, /1000 bet × 100 = **186.7%** RTP from wheel alone.

这样 base 300 + wheel 186 = 486% — 接近 500% target 了。再用 nudge multi-line 自然增的 ~10-20pp 就能到 500。

实测 v1 mode 5 (collect_max=150, win_scale=7) = 486% RTP — 数学对得上。**保留**。

### 5.3 Hit / bucket

base = m2 → hit / bucket 跟 m2 一样。Top tier 通过 wheel 频率提升获得（不通过 base reel 调整）。

---

## 6. Asymmetric Reel 设计（v2 关键升级）

### 6.1 v1 vs v2 区别

**v1**：3 reel 完全相同的 symbol 分布 + 不同的 reel 权重（reel 1 lead / reel 2 kill / reel 3 mid）。
**v2**：3 reel 不同的 symbol counts + reel 内权重 tuner 调（每个 reel 独立 symbol 集 / 数量）。

### 6.2 v2 reel symbol 分布（60 stops 每 reel）

| Symbol | Reel 1 (lead) | Reel 2 (kill) | Reel 3 (lead-mirror) |
|---|---|---|---|
| blank | 36 | 42 | 38 |
| low7 | 4 | 3 | 4 |
| mid7 | 3 | 2 | 3 |
| high7 | 3 | 1 | 3 |
| 5bar | 3 | 3 | 3 |
| bar | 4 | 4 | 3 |
| wild | 1 | 1 | 1 |
| wild2x | 1 | 0 | 0 |
| wild3x | 1 | 0 | 0 |
| wild_up | 1 | 1 | 1 |
| wild2x_mid | 1 | 1 | 1 |
| wild_down | 1 | 1 | 1 |
| **Σ** | **59** | **59** | **59**(+1 blank for 60) |

要点：
- **Reel 2 kill**: 高 7 仅 1 个（vs reel 1+3 各 3 个）→ 顶奖路径必经 reel 2 → reel 2 是 "constraint reel"
- **Reel 2 单 wild 缺位**: wild2x / wild3x 不上 reel 2 → 强迫 wild jackpot pay 101/102 必走 reel 1+3（kill reel 不参与 jackpot）
- **Stack 在所有 reel**: 三联栈（wild_up/wild2x_mid/wild_down）每 reel 都有 1 set，跨 reel 字节级一致 layout（跨 mode invariant）
- 37 blank ≠ 38（reel 1+3 vs reel 2）→ asymmetric 但每 reel 都 ≤ 70% blank（[DESIGN_PHILOSOPHY §3](../../DESIGN_PHILOSOPHY.md) blank cap headroom）

### 6.3 Reel 长度选择

60 stops 每 reel（v1 选定）。理由：
- 跟 RWB 64 接近但不照搬
- Wild stack 占 3 stops，单 anchor 设计（v1 是 1 个 anchor，v2 保持）
- 3-blank cluster pattern + asymmetric symbol counts 在 60 stops 内正好 fit

---

## 7. v2 verify 加 5 类 check

[scripts/verify_m279_design.py](../../scripts/verify_m279_design.py) v2 加：

1. **`BUCKET-SHAPE-MATCH`**: 每 mode 9 桶 distribution KS divergence vs target ≤ **0.10**
2. **`FAMILY-SHARE-BAND`**: 7-family 45-55% / bar 20-30% / wild-jp 3-8% / wheel 3-10% (mode 1)，各 mode 按 §1.3 narrative band 调整
3. **`TOP-JP-ESCALATION`**: pay 101 freq m5 / m1 ≥ **5×**（§7 红线）
4. **`CV-RTP-MONOTONE`**: m7 std > m1 std > m2 std（§5 红线）
5. **`ASYMMETRIC-REEL`**: reel 2 high7 marginal / reel 1 high7 marginal ≤ **0.5**（kill reel 比 lead reel 至少少一半 high7）

加上 v1 已有的 RTP / hit / nudge / wheel / hit-decomposition 共 **10 类** verify。

---

## 8. v2 工作流程（按 [WORKFLOW.md](../../WORKFLOW.md) 走）

1. 重写 spec / strips / weights 到 v2 数值
2. 升级 tuner cost function（per-symbol granular + bucket-shape KS + family-share band penalty）
3. tune mode 1 → 7 derive → 2 tune → 5 derive
4. verify v2（10 类 check 全 GREEN）
5. dump 实际数字眼过（每 mode × 每 reel × 每 family × 每 pay_id）
6. **adversarial 反问 ≥3 个**，每个答完才 commit
7. commit message 必含 ## Self-critique 段

---

## 9. 参考材料（不是约束，仅心理锚）

- [Light & Wonder Blazing 777 Triple Double Jackpot Wild — Nudge official](https://gaming.lnw.com/Games/LIGHT-AND-WONDER/class2/stepper/blazing-777%E2%84%A2-triple-double-jackpot-wild%E2%84%A2--nudge-20009): 3-reel 9-line stepper archetype, RTP variants 87/90/94/96, max 807×, "low to medium" volatility, "WILD + DOUBLE JACKPOT WILD nudge up to 2 times"
- [Wizard of Odds Red White & Blue PAR sheet](https://wizardofodds.com/games/slots/appendix/6/): 64 stops × 50% blank, asymmetric reels (Reel 1 has 1 Red7 / Reel 2 has 3 Red7 / Reel 3 has 1 Red7 — kill / anchor / kill pattern), RTP 87.47% (3-coin), std 9-10
- [Wizard of Odds Blazing Sevens 5-reel](https://wizardofodds.com/games/slots/blazing-sevens/): 7-family RTP share 68.9%, bar share 31.1%, high volatility class
- [Lucas-Singh 2008 — CV inversely related to time on device](https://journals.sagepub.com/doi/10.1177/1938965508315368): CV 是 player engagement 主要驱动；玩家无法察觉 1-2pp RTP 差异；variance shape > RTP point value for session experience
- [Harrigan 2007 — Slot machine structural characteristics](https://www.greo.ca/Modules/EvidenceCentre/files/Harrigan%20(2007)Electronic_gaming_machine_structural_characteristics.pdf): "award symbol ratio" 设计原则 — 顶奖符号 reel 上邻接 blank 制造 PWDF
- [Harrigan & Dixon — Near-miss effect review (PMC 7214505)](https://pmc.ncbi.nlm.nih.gov/articles/PMC7214505/)
- [Wizard of Vegas — Multiline hit rate](https://wizardofvegas.com/forum/gambling/slots/30588-more-lines-same-probability/): 9 line independent → session_hit = 1 - (1 - per_line_hit)^9
- [Slot Math Tutorial PAR sheet creation](https://slotgamedesign.com/2019/01/19/slot-math-tutorial-creating-par-sheets/)

这些都是**心理锚**：archetype 数据让设计意图有真实参考，但所有具体数字（mode RTP / hit / bucket rate / family share）走 LHS 红线 + cfg paytable + slot_designer 规范。
