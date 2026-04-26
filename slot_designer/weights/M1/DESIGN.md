# M1 — IGT Triple Double Diamond archetype: 数值 + 感性体验设计

> 这是 M1 的**设计契约文档**。数值 target + experience invariants 在此。
> Memory 里只存通用原则，具体 M1 benchmark 数字全在这里。

## 1. 真实原型

**IGT Triple Double Diamond**（3-reel 1-line classic slot，2000s 发行）

- 原型数据来源：[Wizard of Obds — Hot Roll analysis](https://wizardofodds.com/games/slots/hot-roll/)（Triple Double Diamond 衍生版的反向工程 reel mapping）
- 物理 reel: 22 stops × 3 reels（independent 序列）
- 虚拟转盘: 256 stops / reel
- Confidence: medium-high（WoO 专家反推，不是 IGT 官方 PAR sheet）
- Modifications from archetype: position 13 (原 Hot Roll bonus trigger) 替换为 Blank（M1 无 bonus）

## 2. 家族 RTP share benchmark

**TDD 原型在 M1 paytable 下的自然家族分布**（`verify_m1_design.py` 的红线锚）:

Pure TDD baseline (family scales 全 1.0): Seven 20.1%, Bar 64.8%, Cherry 15.0%, Wild 0.1%。

**Per-mode family share target range**（跟 luck 水平分层）:

| 家族 | Mode 1 / 7 (standard) | Mode 2 (lucky) | Mode 5 (super lucky) |
|---|---|---|---|
| **Seven** | **18% - 30%** | 25% - 55% | 35% - 70% |
| **Bar** | 55% - 75% | 35% - 65% | 25% - 55% |
| **Cherry** | 8% - 20% | 3% - 15% | 1% - 10% |
| **Wild (pure)** | ≤ 1% | ≤ 2% | ≤ 3% |

**⚠ "Wild (pure)" 只是 `pay_id 2/3/4`（纯 3-wild 路径）的 RTP 占比 —— 这数字本身几乎**没有**反映 wild 在 "Double Diamond" 这台机里的真实角色**。Wild 的 99% 价值来自 **substitution + multiplier boost**（例如 Diamond1 + Bar2 + Bar2 = 3-Bar2 × 2 倍率，被归到 Bar family），不是 pure-wild pays。

**Wild 的真实 experience 衡量指标**（Double Diamond 机台必验）:

| 指标 | Mode 1 / 7 | Mode 2 | Mode 5 | 含义 |
|---|---|---|---|---|
| **P(wild 出现在 payline)** | **≥ 5%** | ≥ 8% | ≥ 12% | Player 多久看到 wild 在 payline 帮忙 |
| **P(2+ wild on payline)** | ≥ 0.1% | ≥ 0.3% | ≥ 0.7% | 双 wild（pure_wild pay 触发的场景） |
| **P(3-Diamond2 top jackpot)** | > 0 | > 0 | > 0 | 顶奖路径 1000× 可达（极稀但必须 ≥ 1 in 10M spin） |

TDD 原型 baseline P(≥1 wild on payline) = 5.37% → 我们 Mode 1 要 ≥ 这个。

**Rationale**：
- Standard 模式（1, 7）Seven 20% 贴 TDD baseline —— "classic 节奏"
- Lucky（2）Seven 涨到 40-50% —— "今天 7 出得频"
- Super-lucky（5）Seven 60% —— 顶奖成主角，Bar 成配角
- Cherry 随 luck 级提升反降（lucky 模式 Bar/Seven 主导）
- **Wild 不要被 "pure pay share ≤ 1%" 误导** —— 这台机的灵魂是"Double Diamond + Triple Diamond 在 window/payline 频繁出现 substitute"，那是 experience 核心

**Rationale**：
- M1 paytable 是 TDD 原型的约 ~50% 倍率（Seven2 50× vs TDD Red 7 100×），因此 Seven share 为 20%（TDD 原型 50% 的 classic RWB share 不直接适用 M1，因为倍率被砍半了 —— 这个 20% 是 TDD 原型 structurally 在 M1 paytable 下的真实值，不是编的）
- Bar 在 TDD 每个 reel 的 stop 数多（reel 2/3 各 ~50 stops），自然占主导，但不能超过 75%（> 75% = Seven 灵魂被淹没）
- Cherry 作为小奖 staple 10-20% 合理
- Wild 跨家族 share 应该**极低**（wild 在 M1 主要作 substitute 而不是 pure-wild 顶奖 —— top 顶奖走 `pay_id 4` = 3-Diamond2 × 3x wild = 1000× 极稀）

## 3. 跨 mode RTP target

| Mode | RTP | Hit rate | Mode 叙事 |
|---|---|---|---|
| 1 | **95% ± 1pp** | ~15% | Classic TDD baseline，标准运气 |
| 2 | **300% ± 20pp** | 22-28% | Lucky — 同一台机今天手气好 |
| 5 | **500% ± 20pp** | 22-28% | Super-lucky — session 级大奖更频繁 |
| 7 | **85% ± 1pp** | ~10% | Grind — 小奖少，大奖 / Seven 不变 |

## 4. 跨 mode experience invariants

### Mode 7 vs Mode 1: "砍小奖保大奖"

- **Seven 家族 RTP share mode 7 ≥ mode 1**（mode 7 Seven share 必须 ≥ mode 1 Seven share 的 95%）
- **Seven 家族 per-reel absolute marginal mode 7 ≥ mode 1 × 0.9**（核心"大奖频率不降"保证）
- Diamond 家族同上（顶奖路径不被砍）
- Cherry / Bar 可以降（这是"小奖少"的来源）

### Mode 2 vs Mode 1: "全 family 都热"

- 各家族 RTP share ratio 保持（allow ± 3pp drift）
- Hit rate ≈ mode 1 × 1.5-1.9
- Bucket shape 朝 Mid/High 稍偏（per-hit 平均倍率略升）

### Mode 5 vs Mode 2: "top bucket 加厚"

- 各家族 share 基本保持
- High bucket (50-500×) RTP share ≥ mode 2 High × 1.3
- Hit rate ≈ mode 2

## 5. Per-family per-reel ratio 锁

TDD 原型的 per-reel stop 分布（22-stop physical）必须 preserve。每 mode tune 完 per-family 的 R1:R2:R3 ratio vs TDD baseline **drift < 0.15**（Diamond 家族因 stop 数少 1-4 int rounding 放宽到 < 0.25）。

TDD baseline per-family per-reel stop count：

| 家族 | R1 | R2 | R3 |
|---|---|---|---|
| Blank | 129 | 116 | 115 |
| Diamond1 | 2 | 3 | 1 |
| Diamond2 | 1 | 3 | 4 |
| Seven1 (Purple 7) | 5 | 19 | 13 |
| Seven2 (Red 7) | 24 | 3 | 17 |
| Cherry | 5 | 5 | 1 |
| Bar1 (1-Bar) | 6 | 54 | 56 |
| Bar2 (2-Bar) | 18 | 4 | 17 |
| Bar3 (3-Bar) | 41 | 21 | 12 |

## 6. Near-miss 结构

TDD 设计的 Seven 近 miss clustering：Seven (Red 7 尤其) 旁边 stop 是 Blank，window 可见但 payline 不中。衡量指标：

- Seven2 **窗口/支付线 ratio** ≥ 1.3（正常 classic clustering 强度）
- Diamond 家族窗口/支付线 ratio ≥ 1.3

这些是 rawdata 跑完后从 `symbols_by_column_top10` vs `symbols_by_column_top10_payline` 计算出来（analyzer 已经 emit 两个字段）。

## 7. Bucket shape narrative

M1 应该是 **boom-bust** 不是 mid-heavy：

- Low (1-10×) hit rate ≥ total hit × 50%（小奖基础流量）
- High (50-500×) RTP share ≥ 15%（big-win memory points）
- Mid (10-50×) 是自然 filler，无 hard rule
- Top (500+) 仅通过 pay_id 4 (3-Diamond2 = 1000×)，极稀有

## 8. Family-scale tune 策略

**锁死的 family（所有 mode strict scale = 1.0）**：
- Diamond1, Diamond2（wild / 顶奖路径）
- Seven1, Seven2（核心 win-carrying family）

**自由 scale 的 family（[0.25, 4.0] bounds）**：
- Blank, Cherry, Bar1, Bar2, Bar3

**Mode 2/5（lucky）的 relaxation**：
- RTP 300% / 500% 无法仅靠 Blank/Cherry/Bar 达到 → 允许 Seven/Diamond scale ∈ [1.0, 2.5]
- 约束：family RTP share 必须仍在 §2 的 target range 内（verify 红线）

**Mode 1/7（标准）strict lock**：
- Seven/Diamond 严格 1.0
- 只让 Blank/Cherry/Bar 吸收 RTP 调节

## 9. 回归测试

- `tests/test_tuner.py::test_m1_per_reel_ratios_match_tdd_archetype` — per-family per-reel ratio drift 锁 §5
- `scripts/verify_m1_design.py` — 跑所有 red/green check
  - §2 家族 RTP share 合规
  - §3 RTP 命中 target
  - §4 mode 间 invariant 满足
  - §5 per-reel ratio drift < threshold
  - §6 near-miss clustering ratio 达标
  - §7 bucket shape narrative 合规

## 相关文件

- `slot_designer/weights/M1/reel_strips.json` — 22-stop 布局（`_archetype` block 记录设计灵感来源，TDD WoO Hot Roll 反向工程）
- `slot_designer/weights/M1/mode_*/weights.json` — 各 mode 权重（`_family_uniform_weights` 字段记录每家族每 reel uniform weight）
- `slot_designer/scripts/tune_m1.py` — player-experience direct tune（27-dim 每家族每 reel uniform weight + experience cost penalty）
- `slot_designer/scripts/verify_m1_design.py` — experience gate
- `slot_designer/tuner/targets/M1_mode*.target.json` — 数值 target（RTP / hit / bucket）

## 设计 Review Checklist (每次 tune 完必跑)

**目的**: 自动化"假但不怪"判定。tune 出来的数字看起来对 ≠ 设计完成。
每次跑完 tune 必须人眼 + 脚本过下面这些维度，检测 player perception 层的 怪。

### 数值层 (verify_m1_design.py 自动检查)
- [ ] **RTP target** 命中容差内 (mode 1=95±1, 7=85±1.5, 2=294.5±20, 5=500±30)
- [ ] **Hit rate** 在 band (mode 1: 14-22%, 7: 10-16%, 2: 20-35%, 5: 20-40%)
- [ ] **Wild on payline** 在 band (mode 1: 10-16%, 7: 10-18%, 2: 12-25%, 5: 12-28%)
- [ ] **Family RTP share** 各 family 在 band

### 体验层 (人眼 + 脚本一起过)

**A. Per-symbol per-reel density review** — 直接看 per-reel 表
- [ ] 每个 family × 每 reel density 在 per-family cap 内
- [ ] 顶奖家族 (Seven, Diamond) 跨 reel max/min ratio ≤ 2.0 (standard) / 2.5 (lucky)
- [ ] **没有单 symbol 在某 reel > 22% (普通) / > 25% (lucky)**

**B. Per-reel Blank density review** — 关键的"reels 看起来一致"check
- [ ] 每 reel Blank weighted density ≥ floor (m1/7=40%, m2=25%, m5=20%)
- [ ] Blank max/min ratio 跨 reel ≤ 2-2.5x (一个 reel 不能特别 dense 或 empty)
- [ ] 玩家盲玩看 3 个 reel 应该感觉**密度差不多**，不是某个 reel "永远满"

**C. Per-pay-id frequency review (cross-mode)** — 每个 pay 频率有没有合理变化
- [ ] **Mode 7**: 每个 big-win pay (id 2/3/5/6/10) 频率 = mode 1 (frozen weights，差应 < 1%)
- [ ] **Mode 2/5**: 每个 pay 频率 ≥ mode 1 (lucky 不该让任何 pay 更稀)
- [ ] **Mode 7**: 小奖 pay (Cherry id 12/13/14, Bar1 id 9) 频率明显 < mode 1

**D. Bucket distribution review** — 玩家见到 win 的 cadence
- [ ] **Mode 1**: ge5_lt10 hit ≥ 0.8% (~12 min/次), ge10_lt20 hit ≥ 1% (~10 min/次)
- [ ] **桶分布**: 不能 200-500 bucket > 30% RTP (太 tail-heavy 玩家见不到中等赢)
- [ ] 每个 reachable bucket hit rate ≥ 0.01% (没"消失"的 bucket)

**E. 跨 mode 叙事 review** — mode 是 luck dial，mode 1 → mode 7 → mode 2 → mode 5 应该有一致演进
- [ ] CV 层级: mode 5 < mode 2 < mode 1 ≤ mode 7 (lucky 平滑, 一般 boom-bust)
- [ ] Hit rate 层级: mode 7 < mode 1 < mode 2 ≈ mode 5
- [ ] Wild on payline 层级: mode 7 ≈ mode 1 ≤ mode 2 ≤ mode 5
- [ ] 每个 big-win pay 频率层级: mode 7 ≈ mode 1 ≤ mode 2 ≤ mode 5

**F. Per-reel asymmetry semantic check** — 不对称是不是有设计理由
- [ ] Top-tier (Seven, Diamond) 不该单 reel 偏倚（除非有近似命中设计意图）
- [ ] Mid-tier (Bar3) R1 偏多 = 经典 near-miss，OK
- [ ] Filler (Bar1, Cherry) 不对称 OK，但极端 (e.g. R3=25% vs R1=2%) 要警惕

### 怎么用

每次 `python tune_m1.py` 跑完：
1. 跑 `python -m slot_designer.scripts.verify_m1_design` (数值层 + A 自动)
2. **人眼过** B / C / D / E / F (脚本难自动化的 player perception 部分)
3. 任一 fail 必须 root-cause + 重 tune (修 bound / 加 penalty / 改 anchor)

**绝对原则**: 数值全过 ≠ 设计完成。Player perception 体验合理才是 done。任何"怪"现象不能 ship。
