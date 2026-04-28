# M279 Design — Triple Blazing Sevens (Nudging Stacks + Collect-to-Wheel)

## 1. 机台原型（archetype）

**主原型**：Light & Wonder（前 Bally / SG）**"Blazing 777 — Triple Double Jackpot Wild — Nudging Stacks"** 3-reel 9-line stepper。
- Reference: <https://gaming.lnw.com/Games/LIGHT-AND-WONDER/class2/stepper/blazing-777%E2%84%A2-triple-double-jackpot-wild%E2%84%A2--nudge-20009>
- Confidence: **high**（精确对应：3 reel、9 line、5 jackpot tier、wild/2x/3x 家族、nudge "up to two times"、~750× 顶奖）

**次原型 / 修改**：Asian-market **collect-to-wheel feature**（每付费轮收 1 颗，满 1000 触发 12-cell wheel）。该机制借鉴 Aristocrat 的 collect 类 feature（如 *Buffalo Stampede* 的 mini-meter trigger），但实际数学接近 Konami 的"周期奖池"设计 —— 1000 spin 一次 wheel 是固定周期，wheel 派彩 5/10/20/50/100x bet。

**LHS 修改 vs 真原型**：
- 加入 Wheel feature（原型没有）—— 把基础 ~85% 推到 ~95% 总 RTP，wheel 贡献 ~10pp
- BuffCollectionMap = wheel 触发的 UI overlay（trigger-only，无 win）
- Triple Wild 顶奖 750× → 设计为 pay_id 101 = 250× JP（受 wheel 顶奖 100× + Triple Wild line 250× 的复合）
- 去掉 progressive jackpot；5 jackpot tier 改为固定派彩

## 2. 机制总览

### 2.1 网格 + paylines
- 3 reel × 3 row = 9 cell grid
- 9 paylines（标准 3-reel 9-line layout，line 1-9 各自经过 3 个 cell，每列贡献 1 cell）
- bet=1000，全 9 line 同 cost（line bet = bet / 9 ≈ 111 credits/line，但派彩按 reward Ratio 直接算）

### 2.2 4 种 SpinType

| SpinType | rawdata 标记 | 名字 | 触发 | 占比（mode 1 实测） | RTP 贡献 |
|---|---|---|---|---|---|
| 1 (= 140 in rawdata) | `NormalCollectionSpin` | 付费基础轮 | 用户每次付 1000 | 87.7% | 39.95pp |
| 36 | `MoveSpin` | 三联栈推动 | 上一轮可见部分 wild stack | 12.2% | **53.99pp**（最大头） |
| 2 | `Wheel` | 12-cell 转盘 | collect meter 满 1000 | 0.09% | 4.05pp |
| 102 | `BuffCollectionMap` | wheel UI overlay | 跟 wheel 同时触发 | 0.09% | 0pp（trigger only） |

### 2.3 Wild 全集（12 symbol）

| 符号 | kind | 角色 | grid 出现率（实测） |
|---|---|---|---|
| `blank` | filler | 不付彩 | 45.5% |
| `bar` | regular | 低 tier 1 | 12.3% |
| `5bar` | regular | 低 tier 2 | 8.5% |
| `low7` | regular | 中 tier 1 | 12.2% |
| `mid7` | regular | 中 tier 2 | 5.3% |
| `high7` | regular | 高 tier | 7.3% |
| `wild` | wild (×1) | 普通替代 | 2.16% |
| `wild2x` | wild (×2) | 单格 2× | 0.37% |
| `wild3x` | wild (×3) | 单格 3× | 0.37% |
| `wild_up` | wild (×1) + nudge anchor (up) | 三联栈底端 | 1.89% |
| `wild2x_mid` | wild (×2) | 三联栈中位 | 2.12% |
| `wild_down` | wild (×1) + nudge anchor (down) | 三联栈顶端 | 1.90% |

`wild_up` / `wild2x_mid` / `wild_down` 三个符号在 reel strip 上**字节级相邻**作为一组，永远整体出现 / 滑动。

### 2.4 Wild Nudge 双向机制

**触发条件**：上一付费轮的 grid 上，三联栈某 reel 只显示 1-2 个 wild（不是全 3 个）：
- `wild_up` 单独可见在底行（row 2）→ 下一帧栈往**上**推 1 格
- `wild_down` 单独可见在顶行（row 0）→ 下一帧栈往**下**沉 1 格
- 中间状态（2 wild 可见）→ 继续向 anchor 方向推 1 格

**MoveSpin 链**：每次推动是 1 个 cost=0 的 ST=36 free spin，重新评估 9 paylines（栈到位置后产生新 line wins）。链式触发直到三联全显（3 wild 全部在该 reel 可见），最多 2 次 MoveSpin（原型 "nudge up to two times"）。

**RTP 影响**：单 paid spin 的栈 partial-visible 概率 ≈ 12.2%（fire rate of MoveSpin），MoveSpin 命中率 53.9%（更高，因为 2-3 wild 在 reel 几乎保证 ≥1 line win），avg multiplier × 2x（wild2x_mid 在中行）。

### 2.5 Collect-to-Wheel 机制

**Collect meter**:
- 每付费轮（ST=140）`AccCredits += 100`、`CollectCount += 1`
- 满 `CollectMax=1000` 时（= 1000 paid spin 后）触发 wheel
- Reset 到 100/1
- 实测周期：1000 / 0.877 paid_rate ≈ 1140 total spin / wheel

**Wheel feature**（12 cell 固定，每 cell 30°）:

| cellIndex | 派彩 (credits @ bet=1000) | 倍率 vs bet | weight |
|---|---|---|---|
| 1 | 50,000 | 50× | 50 |
| 2 | 10,000 | 10× | 30 |
| 3 | 20,000 | 20× | 30 |
| 4 | 50,000 | 50× | 20 |
| 5 | 30,000 | 30× | 30 |
| 6 | 5,000 | 5× | 10 |
| 7 | 20,000 | 20× | 30 |
| 8 | 100,000 | 100× | 20 |
| 9 | 5,000 | 5× | 10 |
| 10 | 100,000 | 100× | 50 |
| 11 | 20,000 | 20× | 15 |
| 12 | 10,000 | 10× | 50 |
| **Σ weight** | | | **345** |

**Wheel EV 解析**：
- Σ(weight × win) = 50·50000 + 30·10000 + 30·20000 + 20·50000 + 30·30000 + 10·5000 + 30·20000 + 20·100000 + 10·5000 + 50·100000 + 15·20000 + 50·10000
- = 2,500,000 + 300,000 + 600,000 + 1,000,000 + 900,000 + 50,000 + 600,000 + 2,000,000 + 50,000 + 5,000,000 + 300,000 + 500,000
- = 13,800,000
- E[wheel] = 13,800,000 / 345 = **40,000 credits = 40× bet**
- Wheel 触发率 ≈ 1 / 1140 spin
- Wheel RTP 贡献 = 40 / 1140 = **3.51%** ≈ 实测 4.05pp（有 ±15% 误差，和 wheel 周期波动 + bonus spin 计入分母方式相关）

### 2.6 Paytable

**基础线**（3-OAK，wild 可代）：

| pay_id | 符号 | reward Ratio | 基础派彩（line bet 不算 multiplier） | 实测 fires | 实测 avg_win |
|---|---|---|---|---|---|
| 1 | 3× high7 | 6000 | ~6000 base × wild boost | 59,447 | 29,247 |
| 2 | 3× mid7 | 4000 | ~4000 base × wild boost | 39,790 | 12,483 |
| 3 | 3× low7 | 2000 | 2000 base × wild boost | 93,350 | 8,520 |
| 4 | 3× 5bar | 1500 | 1500 base × wild boost | 76,460 | 4,542 |
| 5 | 3× bar | 1000 | 1000 × wild boost | 139,531 | 3,090 |
| 6 | 3× any 7 mixed (low7/mid7/high7) | 1000 | 1000 × wild boost | 273,608 | 2,370 |
| 7 | 3× any bar mixed (bar/5bar) | 300 | 300 × wild boost | 138,944 | 557 |

**Wild 跳奖**（all-wild combos）：

| pay_id | 触发 | 派彩 | 实测 fires |
|---|---|---|---|
| 101 | 3× wild3x | 250,000 (250× bet) | 1（极稀有） |
| 102 | 3× wild2x / wild2x_mid 混 | 150,000 (150× bet) | 356 |
| 103 | 3× wild | 50,000 (50× bet) | 42 |
| 104 | 3 个任意 wild 混合 | 15,000 (15× bet) | 1,918 |

## 3. 玩家感性体验

### 3.1 主题
"Blazing Triple Sevens" classic Vegas style — 红/橙火焰背景 + 经典 3-7-bar 符号。**LHS Asian-market 改版**加 fortune wheel 元素（金色转盘 / 灯笼装饰 / "幸运转盘" 中文 UI），把美式 7-bar classic 嫁接到中式 lottery wheel 文化。

### 3.2 每档 win 的情感定位（mode 1 baseline）

| 档 | 范围 | 情感 | hit_rate | RTP 占比 |
|---|---|---|---|---|
| Low | gt0 - 5× | "刚回点本" grind 感 | ~10% | ~20pp |
| Mid | 5× - 50× | "今天命中了" reveal drama | ~3% | ~43pp |
| High | 50× - 200× | session 记忆点 | ~0.4% | ~30pp |
| Top | 200× - 1000× | 朋友圈截图 / lifetime story | ~0.014% | ~5pp |
| **Σ** | | | **~14.2%** | **~98pp** |

注：mode 1 实测 98%，但 LHS 红线规定 mode 1 = 95%。下面 §4 mode 1 target 走 95%。

### 3.3 Near-miss 设计（PWDF）

**Wild 三联栈**是核心 near-miss 引擎：
- 三联栈在 reel 上每 ~30 stop 出现 1 次 anchor → 单 reel marginal 见 1+ wild ≈ 8%
- 上栈"差一点全显"（部分可见）的视觉冲击 → MoveSpin 立即兑现（不像 traditional near-miss 是空欢喜，M279 的 near-miss 一定 cash 出来）
- 设计意图：把 traditional near-miss 的"惋惜情绪"转化为"惊喜情绪" —— 玩家看到 wild_up 在底行时知道下一帧会 nudge 出更多 wild

**Wheel 周期叙事**：
- 1000 paid spin 大约 = 1 hour 玩（普通频率），collect 进度条做成"水位上涨" UI → 玩家有清晰预期
- Wheel 派彩 5-100× 之间 randomize → 中位 20× 带"小幸运"反馈，顶 100× 带"今天爆了"感
- 100× wheel 命中率 = 70/345 = **20.3%**，每 ~5,700 paid spin 见一次 → 长 session（5-6 hour）能见 1 次

### 3.4 跨 mode 差异化叙事

| Mode | RTP 红线 | 玩家故事 | 跟 mode 1 关系 |
|---|---|---|---|
| 1 | 95% | "原生体验"，标准玩 | baseline |
| 2 | 300% | "幸运 mode"，wild stack 出现率 ×1.5 → MoveSpin 频率 ↑、line hit ↑ | hit ×1.5-2，bucket shape 跟 mode 1 形状相近 |
| 5 | 500% | "super-lucky"，Wheel 出现率 ↑（CollectMax 减半 = 500） + wild3x 占比 ↑ | base 字节级 = mode 2，feature 加强 |
| 7 | 85% | "冷 mode"，bar 家族砍权 → Low bucket 砍，Mid/High/Top 不动 | direct-scale from mode 1（5bar/bar ×0.7）|

**Mode 2 vs mode 1 不变量**：所有 tier hit 略升（不是只升 Top），bucket 形状不漂。
**Mode 7 vs mode 1 不变量**：Mid/High/Top **绝对 hit 不动**，只 Low 降。
**Mode 5 vs mode 2 不变量**：base 字节级一致（hit shape 不动），feature 加强（CollectMax 1000→500、wheel cell 重权 100× 加权）。

### 3.5 Family RTP share（mode 1 设计 target）

| Family | RTP share target | 设计意图 |
|---|---|---|
| 7-family (low7/mid7/high7) | ~50% | classic 7-dominant 灵魂（参考 Blazing Sevens 89% 中 7 家族 68.8%；M279 因 wheel 占 4-10pp 拉低 7 share） |
| Bar-family (bar/5bar) | ~25% | 低 tier "grind" 收益 |
| Wild jackpot (pay_id 101-104) | ~5% | rare moment |
| MoveSpin contribution | ~25% | nudge mechanic 是核心 RTP 引擎 |
| Wheel | ~5-10% | 周期奖池 |

注意：MoveSpin contribution 不是独立 family，是上面 7/bar/wild family 在 ST=36 free spin 的额外贡献（line wins 在 nudge 后栈到位置仍按 7/bar pay 派彩）。

## 4. 4 mode RTP / hit / bucket target

### Mode 1（baseline，95% RTP）

```
total_rtp_pct = 95   ±1pp 严格
hit_rate      = 0.142 ±1pp
cv            = 7.7  (volatility = "Very High" classic 7-dominant)
bucket_rate (paid round 口径，ret_x = win/bet):
  gt0_lt1     = 0.023  (low chase)
  ge1_lt5     = 0.085  (low grind 主力)
  ge5_lt10    = 0.016
  ge10_lt20   = 0.009
  ge20_lt50   = 0.0057
  ge50_lt100  = 0.0028
  ge100_lt200 = 0.0009
  ge200_lt500 = 0.0001
  ge500       = 0.00004 (top 极稀)
trigger_target (collect → wheel) = 1/1140 = 0.000877
trigger_target (move spin / nudge) = 0.122 (12.2% of total spins)
```

### Mode 2（lucky, 300% RTP）

```
total_rtp_pct = 300   ±20pp 可漂
hit_rate      = 0.225 (≈ ×1.6 mode 1, NOT ×3)
bucket shape ≈ mode 1 (low bucket 略压、mid/high 略升)
nudge frequency ≈ ×1.5 mode 1 (wild stack reel 上权重 ×1.5)
wheel trigger 同 mode 1（CollectMax 不变）
```

### Mode 5（super-lucky, 500% RTP, base = mode 2）

```
total_rtp_pct = 500   ±30pp 可漂
base weights 字节级 = mode 2
feature 加强：CollectMax 1000 → 500（wheel 频率 ×2）
wheel cell 重权：100× cellIndex 8/10 weight ×1.5
wild3x 出现率 ×2（mode 2 的 0.005 → mode 5 的 0.010）
```

### Mode 7（standard low, 85% RTP）

```
total_rtp_pct = 85    ±1pp 严格
hit_rate      = 0.105 (mode 1 - 3.7pp; bar/5bar 砍单)
Mid/High/Top bucket_rate 绝对 = mode 1
Low bucket_rate × 0.7
Direct-scale path: 5bar weight ×0.7, bar weight ×0.7（其他 family 不动）
nudge frequency 跟 mode 1
wheel trigger 跟 mode 1
```

## 5. 跨机台硬约束 ↔ M279 实现

| 约束（DESIGN_PHILOSOPHY） | M279 实现 |
|---|---|
| §1 倒金字塔 | 7 家族倒金字塔：high7 > mid7 > low7（按 reward Ratio 6000 > 4000 > 2000 GAP ratio = 1.5x、2.0x） |
| §2 Brand visibility | wild 三联栈 reel 出现率 ~6% → 每 17 spin 一次（visible），但全显需 nudge 链（rare） |
| §3 Blank cap headroom | blank weight ≤ cap × 0.95 |
| §4 Per-tier hit preservation | mode 7 砍 bar/5bar Low、保 Mid/High/Top；mode 2 全 tier 略升 |
| §5 CV-RTP consistency | mode 1 CV ≈ 7-8（Very High vol 7-dominant）, mode 2 CV ≈ 4（lucky 平稳）|
| §6 Family share archetype | 7 家族 ~50% RTP（archetype Blazing Sevens 68.8% 因 wheel 拉到 50%） |
| §7 Top jackpot escalation | mode 1: pay_id 101 ~1/2.9M，mode 5: ~1/100k（×30 升） |
| §8 Hit decomposition | pay_id 6 (mixed-7) 273k fires 占 hit ~28%（不超 70%） |
| §9 Mode-pair monotonicity | RTP m5 > m2 > m1 > m7；hit m5 ≥ m2 > m1 > m7；wheel freq m5 > m1 ≈ m7 |
| §10 Pareto trap | family-share lower bound + nudge_anchor 锁权（三联栈不能砍权到 0） |
| §11 假但不怪 | verify 11 类硬约束（含 wheel EV / nudge mechanic / family share） |

## 6. 实现路径（v1 plan）

1. spec：12 symbol、9 payline、11 pay（7 line + 4 wild jp）+ 4 spin_type + nudge_anchors block + collect_meter block + wheel block
2. engine extensions：loader 多 payline、evaluator.evaluate_all_paylines()
3. M279 modules：engine/m279/{engine, nudge, collect, wheel}.py
4. emitter/m279_round.py（多 line PayoutByPayline + AccCredits/CollectCount/CreditsSymbols）
5. backend/virtual_analyzer.py 加 M279sim routing
6. weights/M279/reel_strips.json：~50 stop strip / reel，2 个 wild stack anchor
7. mode 1/2/5/7 weights + tune（sim-based，9-line analytic 太复杂走仿真）
8. verify_m279_design.py：11 类硬约束 + experience invariant
9. 注册 + console 端到端验

详细每 phase 见 todo list。
