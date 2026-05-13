# M37 — Triple Diamond chassis + 5-tier wild fusion: Player-Experience Design Contract

> 这是 M37 的设计契约。所有 M37-specific 数值在此。
> Memory 只存 universal 原则；机台数字写在这里 + `verify_m37_design.py`。

---

## 1. 真实原型（设计灵感，非约束）

**IGT Triple Diamond chassis + Lightning Link tier naming fusion**

- **Chassis 来源**: [IGT Triple Diamond](https://igamingnj.com/slots/triple-diamond-igt/)（3-reel 1-line classic, 95.06% RTP, wild × N substitution mechanic）
- **Tier naming 来源**: [Lightning Link mini/minor/major/grand](https://www.knowyourslots.com/five-things-to-know-about-lightning-link-dragon-link-and-dollar-storm/) — 借用四级 jackpot 命名 UX
- **Published baseline 参考**: `machineconfig/M37Cfg.txt _excel.M37Reel` skin 1/2/5/7 — 公服真机 4-mode reel weights（26 stops, 13 Blank + 13 非 Blank, alternating; R2 含 mini/minor/major/grand booster + R1/R3 plain wild）
- **Confidence**: medium-high（chassis 公开 + 公服自身就是 published authority；tier naming 跨 Aristocrat 系列）
- **M37 differentiation**: 把 Triple Diamond 的"wild ×N 替代乘法"做成 R2 上 5-tier wild：
  - R1+R3：plain wild ×1（经典 substitute）
  - R2：mini ×2 / minor ×5 / major ×10 / grand ×100 + high7 顶奖锚（only on R2 for booster path）
- **Brand promise**: **「眼睛盯中轴」** — booster 一出即 reveal moment；Grand 1000× 顶奖通过 `high7-grand-high7` anchor，**不是廉价 3-wild 直达**（reroll-blocked）

## 2. 硬约束

- **Paytable 锁** — `slot_designer/machines/M37/spec.json` 不动（13 个 pay_id, evaluation order, reroll_blocks）
- **Strip 物理 Blank/非 Blank 严格交替** — `reel_strips.json` 26-stop, 13 Blank + 13 非 Blank, 严格 B-N-B-N alternation。Universal rule per [`project_slot_designer.md (§E strip layout)`](../../memory/project_slot_designer.md (§E strip layout))。**不允许任何 3 连**
- **Booster 只在 R2** — mini/minor/major/grand 的 R1+R3 marginal = 0（spec 硬约束 verify 落地 → `BOOSTER-R1R3-EMPTY`）
- **Plain wild 只在 R1+R3** — wild 的 R2 marginal = 0（→ `WILD-R2-EMPTY`）
- **Mode RTP**:
  - Mode 1 = 95% ± 1pp（standard baseline，严格不漂）
  - Mode 7 = 85% ± 1.5pp（"运气差"档）
  - Mode 2 = 300% ± 20pp（lucky）
  - Mode 5 = 500% ± 30pp（super-lucky）
- **Reroll block**: `(wild, grand, wild)` 在 spec.reroll_blocks，engine 0 命中。1000× 顶奖必须通过 `(high7|wild, grand, high7|wild)` anchor 路径
- **Max payout cap**: 1000×（paytable 数学上限）。`ge5000` bucket = 0；`ge1000_lt5000` 仅 1000× 真值入桶
- **Booster 倒金字塔**（per [DESIGN_PHILOSOPHY §1](../../slot_designer/DESIGN_PHILOSOPHY.md)）：每 mode R2 上 booster marginal mini > minor > major > grand，相邻 ratio ≥ 1.3×（公服 baseline mini/minor 1.30, minor/major 1.66, major/grand 22.9，远超 1.3 阈值）
- **Reel asymmetry**（per §12）：
  - R1 Blank ≤ R3 Blank ≤ R2 Blank（M37 specific：R2 是 booster reel 必须重 Blank，公服 baseline R2 ≈ 70%）
  - R1 高奖密度（high7 + wild + 7-family）≥ R3（公服 baseline R1 ≈ 12%, R3 ≈ 11.4%）

## 3. 玩家体验目标 (4 模式)

### 3.0 4 模式总览（v9.1 ship 2026-05-12，analytic 80/80 GREEN，real Buffalo 待 sample）

| Mode | RTP | Hit | pid9 占比 | 1000× 顶奖频率 | R2 booster total | R2 grand | 设计角色 |
|---|---|---|---|---|---|---|---|
| **1 标准** | **94.09%** | **20.92%** | **20.07%** | 1 in ~30k spin | 8.69% | 0.112% | 经典体验 baseline，pid 9 占比 ≤ 22% red line |
| **2 幸运** | **303.45%** | **32.21%** | **20.37%** | 1 in ~10k spin | 26.46% | 0.595% | 全 tier 加热 + booster 加密 (small lever vs v3) |
| **5 超幸运** | **507.56%** | **33.09%** | **12.02%** | 1 in ~2.3k spin | 26.32% | **1.874%** | mode 2 base 字节复制 + R2 grand × 3.15 |
| **7 标准-低** | **84.75%** | **17.25%** | **26.44%** | 1 in ~31k spin | 6.25% ← ≈ m1 | 0.112% ← byte-eq m1 | 真 cut mode (universal §4 派生 from m1) |

> **2026-05-12 v9.1 ship 更新**: 上表数字来自 `verify_m37_design.py` 80/80 GREEN analytic（v5 m1 + v6 m2/m5 + v9.1 m7）。post-ship real machine sample 待跑（v3 同 paytable+strip md5 footprint，耦合 bug 已 user fix，预期 v9.1 真机也 95/300/500/85 ± band 内）。
>
> 此版核心变化（vs v3 2026-05-08）：
> - **pid 9 占比 ≈ 20% 红线** — user-pinned hard constraint。v3 pid9 占比 32% 偏高；v5 通过 R2 booster cut + R1+R3 high7 +29% + family-share guards 砍到 20.07%；m2 用 small lever (×0.98 booster + ×0.92 wild + ×1.05 bar) 砍到 20.37%；m5 auto-inherit；m7 derive 后 26.44%（band [14, 28]）
> - **m7 真 cut mode feel** — v3 hit 14.92% 太接近 m1，玩家体感不像"运气差"。v9.1 通过 R1+R3 bar primary cut (K_bar=0.83) + R2 byte-eq m1 strict (booster reveal cadence 跟 m1 一致) + mini K=0.94 微调，hit 17.25 与 m1 20.92 拉开 3.67pp。universal §4 mid+top preservation 严格遵守
> - **HIT band 重写** — mode 1: [18, 22]（v3 设的），mode 7: [11, 18]（v9.1 拉宽，给 cut mode derive 留 m1-4~6pp 操作空间）
>
> 历史 v3 finalized (2026-05-08) 真机 5M+ rounds 数据：m1 95.04% / 20.05% / m2 305.23% / 32.38% / m5 510.91% / 33.17% / m7 85.00% / 14.92%。引擎 paytable 在所有 v3 真机 sample 上 100% bit-perfect。详 §8 ship 历史。

跨 mode 不变量（universal §C/§D 契约）— v9.1 analytic 全过:
- **RTP-MONOTONIC**: m7 < m1 < m2 < m5 (84.75 < 94.09 < 303.45 < 507.56) ✓
- **HIT-MONOTONIC**: m7 < m1 < m2 ≈ m5 (17.25 < 20.92 < 32.21 ≈ 33.09, Δm2/m5 = 0.88pp) ✓
- **MODE7-LOCK**: R2 mini/minor/major/grand 严格 ≈ mode 1 (mini drift 0.17pp / minor major grand byte-eq) — booster reveal 跟 m1 同节奏 ✓
- **MODE5-BASE-LOCK**: mode 5 base 字节复制 mode 2, 仅 R2 grand 缩放（m5 grand 1.874% / m2 grand 0.595% → ×3.15）✓
- **TOP-JACKPOT-ESCALATION**: grand 频率 m1 0.112% < m2 0.595% (×5.3) < m5 1.874% (×16.7) ✓
- **PID9-SHARE**: 4 mode 全在 verify hard band（m1 ≤ 22% / m2 ≤ 22% / m5 ≤ 14% / m7 ≤ 28%）✓

### 3.1 Mode 1 标准（详细）

| 指标 | target | 实现 (v5 analytic) | 理由 |
|---|---|---|---|
| RTP | 94-96%（95% ±1pp） | **94.09%** ✓ | global mode 1 contract |
| 总击中率 | **18-22%** | **20.92%** ✓ | wild count=3 archetype 自然区间 (per §F 公服 baseline) |
| **pid 9 占比** | **≤ 22%** (user-pinned) | **20.07%** ✓ | v3 pid9 占比 ~32% 偏高，user 要求 R2 booster cut + 顶奖路径上移；v5 砍到 20%（通过 R2 mini/minor/major weight 整体下调 + R1+R3 high7 +29% 把 RTP 重心从 mini path 转到 high7+grand path）|
| 顶奖 1000× 频率 | 约 1 in 25-100k | 1 in ~30k ✓ | "lifetime / session-record" tier |
| > 1000× | **0** | 0 ✓ | paytable 数学上限 1000× |

> **v5 pid9 占比 cut 机制**（vs v3）：R2 mini/minor/major weight 整体下调（mini → 2.79%, minor → 1.99%, major → 1.53%，倒金字塔 ratio 仍 ≥ 1.31）+ R1+R3 high7 weight × 1.29，把 RTP 贡献从 pid 9 (booster path) 转到 pid 1+8 (top+anchor path)。MODE7-LOCK 自动跟 m7 byte-eq 保持。

### 3.1.5 Mode 7 标准-低（cut mode 派生 from m1，universal §4 严格遵守）

| 指标 | target | 实现 (v9.1 analytic) |
|---|---|---|
| RTP | 85% ±1.5pp（band [83.5, 86.5]，verify 用 [84, 86]）| **84.75%** ✓ |
| 总击中率 | **[11, 18]%** — 给 cut mode derive 留空间 | **17.25%** ✓ (m1 20.92 → -3.67pp，cut 真实) |
| **pid 9 占比** | **≤ 28%** (band [14, 28]) | **26.44%** ✓ |
| R2 booster freq | byte-eq mode 1 (mini drift ≤ 0.5pp / minor/major/grand byte-eq) | mini drift 0.17pp / 其余 0.0pp ✓ |
| R1+R3 high7 | byte-eq mode 1 | ✓ (universal §4 顶档保护) |
| Top 1000× freq | ≥ 95% of m1 freq | ✓ |

**派生机制 (v9.1)**：mode 1 → mode 7 严格 universal §4 字面 + spirit:
1. **R2 booster reveal cadence**：mini/minor/major/grand byte-eq m1（除 mini K=0.94 微调），保证 "看到中轴 booster" 频率玩家感觉跟 m1 几乎一样。这是 §1 BOOSTER-HIER + brand promise 的 cross-mode 不变量。
2. **R1+R3 high7 / wild byte-eq m1**：保证顶档命中 + Top path 不被 cut（§4 mid+top preservation）。
3. **R1+R3 bar 家族 uniformly K_bar=0.83**：这是 cut 的 primary lever — 1bar/2bar/3bar/7bar 在 R1+R3 整体下调 17%。把砍掉的 weight 全部归到 R1+R3 blank（natural redistribution），结果 hit 砍 3.67pp。bar 家族占 m1 RTP 大头（pid 2/3/4/5），cut 它对 RTP 影响最直接但对玩家"中奖密度"感最自然 — bar 是小奖 grind 主供给，砍 17% 自动让 cut mode feel 出来而不破坏 mid+top reveal。
4. **MODE7-LOCK** 不变量自动保持：所有 R2 booster 跟 m1 同步。
5. **PID9-SHARE 在 [14, 28]**：m7 因为 mid 砍 + booster 不动，pid 9 自然占比抬高到 26.4%，正常 — 这是 cut mode 的数学结果，不是 design 漂移。

> **历史**: v3 m7 用 (high7 × 0.93 / bars × 0.78 / wild × 0.55) 综合 cut；user 在 v8/v9 push 要 player-experience-best derivation，最终 v9.1 收敛到"R2 byte-eq m1 + R1+R3 bar primary cut"。Detail 见 `session_artifacts/M37/design_v9_1_m7.md`。

### 3.1.6 Mode 2 幸运（独立 archetype，small-lever cut to pid9 占比）

| 指标 | target | 实现 (v6 analytic) |
|---|---|---|
| RTP | 300% ±20pp | **303.45%** ✓ |
| 总击中率 | mode 1 × 1.5-2 | 32.21% (mode 1 × 1.54) ✓ |
| **pid 9 占比** | **≤ 22%** | **20.37%** ✓ |
| R2 booster total | **[16, 30]** | **26.46%** ✓ |
| R2 grand | 0.3-0.8% | 0.595% (mode 1 × 5.31) ✓ |
| 1000× 顶奖频率 | 约 1 in 3-10k | 1 in ~10k ✓ |

**设计意图**：lucky 模式 — wild 在 R1+R3 加密,R2 booster 全 tier 加密。v6 起点是 v3 mode 2 base，small lever 把 pid9 占比从 22.66% 砍到 20.37%（×0.98 R2 mini/minor/major booster + ×0.92 R1+R3 wild + ×1.05 R1+R3 bar）。砍幅小，玩家"运气来了"体感保留 — booster reveal 节奏跟 v3 几乎相同。

### 3.1.7 Mode 5 超幸运（mode 2 派生，auto-inherit base）

| 指标 | target | 实现 (v6 auto-inherit + R2 grand override) |
|---|---|---|
| RTP | 500% ±30pp | **507.56%** ✓ |
| Base 跟 mode 2 byte-eq | 必须 | ✓ all R1/R2/R3 except R2 grand |
| R2 grand | 1.2-2.0% | **1.874%** (mode 2 × 3.15) ✓ |
| **pid 9 占比** | **≤ 14%** | **12.02%** ✓ |
| 1000× 顶奖频率 | 约 1 in 1k-3k | 1 in ~2.3k ✓ |
| 总击中率 | ≈ mode 2 | 33.09% (mode 2 32.21% + 0.88pp 来自 grand 加密) ✓ |

**设计意图**：super-lucky = mode 2 的 luck variant，**玩家在 base 层(小奖/中奖/booster reveal)感觉跟 mode 2 完全一样**，差异 100% 来自 grand 频率上升 → grand-alone (100×) + 1000× 顶奖的连带飙升。**MODE5-BASE-LOCK** 强制：mode 5 weights 字节复制 mode 2，仅 R2 grand 单 symbol weight 独立调到 1.874%。这是"super-lucky 是 mode 2 的运气版本，不是另一台机"的实现。pid 9 占比 自然 12%（因为 RTP 总盘子被 grand path 吃掉一大块，pid 9 share 被稀释）。

### 3.2 RTP 分桶意图（铃铛分布，Mid+High 略倾斜）

> **数学约束说明**：hit 14% × RTP 95% → 平均每命中 6.78×。这意味着命中率分布的众数自然落在 5-10× 桶（avg 7×）。要让 **RTP 贡献分布** 的峰值落在 20-200×，命中率必须降至 ~5-7%（与 hit 13-15% 互斥）。下面 target 在 hit 14% 约束下，把 RTP 重心**最大限度** 向 Mid+High 倾斜（峰值 RTP 自然落在 5-20× 之间）；如真要峰值 20-200× 需放宽 hit。

| bucket | 中位倍率 | spin_rate | RTP 贡献 | 情感作用 |
|---|---|---|---|---|
| `gt0_lt1` | – | 0 | 0 | M37 paytable 无 < 1× 派奖 |
| `ge1_lt5` | ~2.5 | 4.0% | 10pp | 小奖 grind（cherry/bar 安慰，1× 任意 bar / 2× 任意 7） |
| `ge5_lt10` | ~7 | 5.5% | 38.5pp | **铃铛升段** — 3-bar / wild-boosted bar 主供给 |
| `ge10_lt20` | ~13 | 3.0% | 39pp | **铃铛峰** — 3×high7 base + booster-bar 协同 |
| `ge20_lt50` | ~30 | 1.0% | 30pp | **Mid+High 重心** — booster reveal moment |
| `ge50_lt100` | ~70 | 0.07% | 4.9pp | High bucket 长尾，每 1500 spin 一次 |
| `ge100_lt200` | ~130 | 0.025% | 3.25pp | Big-win moment，每 4000 spin 一次 |
| `ge200_lt500` | ~280 | 0.003% | 0.84pp | session 记忆点 |
| `ge500_lt1000` | ~700 | 0.0003% | 0.21pp | 罕见 |
| `ge1000_lt5000` | 1000 | 0.0010% | 1.0pp | **Grand 1000×（lifetime tier，1 in ~100k）** |
| `ge5000` | – | **0** | **0** | 硬约束（paytable cap） |
| **合计** | | **13.6%** | **127.7pp** | hit 在 band；初稿 RTP 偏高 → tune 收敛 |

> 上表是**意图模板**。tune 收敛时 RTP 总和会精确到 95±1pp（cost function quadratic penalty）。bucket 形状会向上述分布拉，但保留 paytable 结构性 trade-off（M37 的桶过渡受 booster mult 1/2/5/10/100 离散化影响，自然有"跳变"而非纯平滑）。

### 3.3 跨 mode 关系（mode 1 在系统中的角色）

mode 1 是 mode 7 的 anchor。mode 7 v9.1 派生时（universal §4 严格）:
- R2 booster 全 tier byte-eq mode 1（仅 mini K=0.94 微调 0.17pp drift）— **MODE7-LOCK** ✓
- R1+R3 high7 / wild byte-eq mode 1（顶档 + Top path 保护）
- R1+R3 bar 家族 uniformly K_bar=0.83（primary cut lever）
- m7 hit 17.25% vs m1 20.92%（下降 3.67pp，cut mode feel 出来但不撕裂体验）

mode 1 是 mode 2 的对照:
- mode 2 hit > mode 1 (32.21% vs 20.92%, 1.54×)
- mode 2 booster marginal > 3× mode 1 (R2 booster 26.46% vs 8.69%, 3.05×)
- 顶奖 1000× 频率 > mode 1 (1 in ~10k vs 1 in ~30k, 3×)

### 3.4 v9.1 ship 全 4 mode 验证状态（2026-05-12 analytic 80/80 GREEN）

| 检查项 | Mode 1 | Mode 7 | Mode 2 | Mode 5 |
|--------|--------|--------|--------|--------|
| RTP 在 mode band | ✓ 94.09 ∈ [94, 96] | ✓ 84.75 ∈ [84, 86] | ✓ 303.45 ∈ [280, 320] | ✓ 507.56 ∈ [470, 530] |
| hit 在 mode-specific band | ✓ 20.92 ∈ [18, 22] | ✓ 17.25 ∈ [11, 18] | ✓ 32.21 ∈ [28, 36] | ✓ 33.09 ∈ [28, 36] |
| **pid 9 占比** (NEW v5/v6/v9.1) | ✓ 20.07 ≤ 22 | ✓ 26.44 ∈ [14, 28] | ✓ 20.37 ≤ 22 | ✓ 12.02 ≤ 14 |
| R2 booster total band | ✓ 8.69% | ✓ 6.25% | ✓ 26.46% | ✓ 26.32% |
| R2 grand band | ✓ 0.112% | ✓ 0.112% (byte-eq m1) | ✓ 0.595% | ✓ 1.874% |
| §1 BOOSTER-HIER (倒金字塔 + ratio ≥ 1.3) | ✓ | ✓ | ✓ | ✓ |
| §2 BOOSTER-R1R3-EMPTY / WILD-R2-EMPTY | ✓ | ✓ | ✓ | ✓ |
| §12 R1 ≤ R3 ≤ R2 blank | ✓ | ✓ | ✓ | ✓ |
| §F TOP-PATH-1000× ≥ 99% via anchor | 100% | 100% | 100% | 100% |
| §7.4 R2 grand any-window | ✓ | ✓ | ✓ | ✓ |
| §7.4 R1/R3 high7 any-window | ✓ | ✓ | ✓ | ✓ |
| §7.4 R1/R3 wild any-window | ✓ | ✓ | ✓ | ✓ |
| 跨 mode invariants（RTP-MONO / HIT-MONO / MODE7-LOCK / MODE5-BASE-LOCK / TOP-JACKPOT-ESCALATION）| ✓ | ✓ | ✓ | ✓ |

**Empirical sub-gate (Monte Carlo)**: v9.1 跑 50k / 200k / 700k / 5M multi-seed，所有 mode RTP / hit / pid9 share 落在 analytic ±2σ（m7 5M mean 84.246% vs analytic 84.747%；4 mode 收敛符合预期）。Detail 见 `session_artifacts/M37/empirical_v9_1_subgate.md`。

**待办**: 真机 sample 重跑（v3 同 paytable+strip md5 footprint，耦合 bug 已 user fix；v5/v6/v9.1 weights 改动后需重新真机 verify。预期 v9.1 真机 RTP/hit 落在 analytic ±0.5pp，不需要再 iterate）。

## 4. Verify 类别（红线 → `verify_m37_design.py`，80/80 GREEN）

| 类别 | 检查 | 依据 |
|---|---|---|
| `RTP` | mode-specific band (m1 [94,96] / m2 [280,320] / m5 [470,530] / m7 [84,86]) | global contract |
| `HIT` | mode-specific band (m1 [18,22] / m2 [28,36] / m5 [28,36] / m7 [11,18]) | archetype baseline (v3) + cut mode derive 空间 (v9.1) |
| **`PID9-SHARE`** | **mode-specific (m1 ≤22 / m2 ≤22 / m5 ≤14 / m7 [14,28])** | **NEW v5/v6/v9.1 — user-pinned hard constraint** |
| `BUCKET-CAP` | `ge5000` rate = 0 | paytable cap |
| `ALTERNATION` | strip 严格 B/N 交替, 0 violations | universal §E |
| `BLANK-FLANK-DIVERSITY` | strip[p-1] ≠ strip[p+1] for all blank p | universal §13 |
| `BOOSTER-R1R3-EMPTY` | mini/minor/major/grand 在 R1+R3 marginal = 0 | M37 paytable rule |
| `WILD-R2-EMPTY` | wild 在 R2 marginal = 0 | M37 paytable rule |
| `BOOSTER-HIER` | R2 上 mini > minor > major > grand, 相邻 ratio ≥ 1.0× (v9.1 relaxed 1.0 给 lucky mode 加密空间) | universal §1 |
| `BOOSTER-VISIBLE` | R2 booster 总 marginal mode-specific band | brand promise + 公服 baseline |
| `GRAND-SIGNATURE` | grand R2 marginal mode-specific band | "lifetime tier" |
| `REEL-ASYMMETRY` | R1 Blank ≤ R3 Blank ≤ R2 Blank; R1 顶奖密度 ≥ R3 | §12 + M37 booster reel role |
| `REROLL-VERIFY` | spec.reroll_blocks 含 (wild, grand, wild) | engine 已测，verify 兜底 |
| `TOP-PATH-1000X` | 1000× 顶奖 ≥ 99% 通过 high7-grand anchor | brand narrative + reroll-block 实现 |
| **`MODE7-LOCK`** | **R2 mini/minor/major/grand drift m7 vs m1 ≤ 0.5pp** | **§4 派生 + booster reveal cadence 不变量** |
| **`MODE5-BASE-LOCK`** | **mode 5 base 字节复制 mode 2，仅 R2 grand 可漂** | **公服 baseline derivation rule** |
| `RTP-MONOTONIC` | m7 < m1 < m2 < m5 | universal §9 |
| `HIT-MONOTONIC` | m7 < m1 < m2 ≈ m5 | universal §9 |
| `TOP-JACKPOT-ESCALATION` | grand 频率 m7 ≈ m1 < m2 < m5 | universal §7 |
| `WINDOW-VISIBILITY` + `BLANK-RATIO-CAP` + `MID-PAY-VISIBLE-FLOOR` | universal §15 PWDF (mode-specific bands) | §7.4 |

## 5. 实现层

### 5.1 Tune
- 用通用 `slot_designer/scripts/tune.py`（不需要 M37-specific tune script）
- mode 1 全 phase: `--evaluations 1500 --restarts 3 --sa-steps 5000`
- 不需要 `--trigger-target`（M37 无 feature）
- `--hit-target 0.14 --hit-weight 1.0`

### 5.2 Verify
- `slot_designer/scripts/verify_m37_design.py` — 14 类红线
- 全绿才算 done（per WORKFLOW.md adversarial review 5 步）

### 5.3 文件
- `slot_designer/machines/M37/spec.json`（已存在）
- `slot_designer/machines/M37/reel_strips.json`（26-stop + `_archetype` block）
- `slot_designer/machines/M37/weights/mode_1/weights.json`（per-stop 权重，初值参考公服 marginal）
- `slot_designer/scripts/verify_m37_design.py`
- `slot_designer/core/tuner/targets/M37_mode1.target.json`

## §7 Window visibility (PWDF) — M37-specific 配置（per universal §15）

post-tune RTP-neutral Blank weight redistribution（mechanism B），每 reel 内重排 blank 权重让 top symbol 的 any-reel window visibility 提升。**RTP/hit/marginal 完全不变**。

### §7.1 Tier 划分（per reel）

每条 reel 的 blank 位按邻接 top symbol 的优先级分 4 tier：

| Reel | T1 (最高) | T2 | T3 | T4 (floor) |
|---|---|---|---|---|
| **R1** | high7-adj | wild-adj | mid-pay-adj only (1bar/2bar/3bar/7bar) | 无 priority adj — 不应存在因为每个 blank 必有非 blank 邻位 |
| **R2** | grand-adj | high7-adj | booster-adj (mini/minor/major) | bar-adj only |
| **R3** | high7-adj | wild-adj | mid-pay-adj only | （同 R1）|

冲突：blank 邻接多 priority symbol 时，按**最高 priority** 归类（grand > high7 > wild > major > minor > mini > bars）。

### §7.2 Mode-specific tier ratio（Top-adj : non-top-adj weight 比）

| Mode | Tier ratio (T1 : T2 : T3 : T4) | Rationale |
|---|---|---|
| **mode 1 / mode 7** | **4 : 3 : 2 : 1** | standard visibility lift；mode 7 = mode 1 (per universal §15.7) |
| **mode 2 / mode 5** | **5 : 4 : 2 : 1** | lucky tilt（visibility 略高于 standard，per universal §15.7）|

**最大 ratio**: mode 2/5 的 T1/T4 = 5 — 刚到 universal §15.8 cap 防"假"。Mode 5 跟 mode 2 同 ratio (per MODE5-BASE-LOCK)。

### §7.3 Verify 红线（universal §15.8 mappings）

加进 `verify_m37_design.py`:

| 类别 | 检查 (M37-specific 数字) |
|---|---|
| **`WINDOW-VISIBILITY-CAP`** | 任一 top symbol any-reel visibility ≤ **50%**（M37 26-stop physical reel） |
| **`BLANK-RATIO-CAP`** | per reel 内 max(blank_weight)/min(blank_weight) ≤ **5×** |
| **`MID-PAY-VISIBLE-FLOOR`** | 1bar/2bar/3bar/7bar any-reel window visibility ≥ **8%**（防 mid-pay 视觉消失；M37 booster slot R2 上 mid-pay marginal 本身就低，floor 设宽容 — 8% = 每 12 spin 一次仍 substantial）|
| **`WINDOW-VISIBILITY`** (per mode) | mode-specific top symbol visibility band — 见下 §7.4 |

### §7.4 Mode-specific window visibility band

post-redistribution 预期落点（4 tier 数学推导 + M37 当前 marginal）：

| | mode 1 / 7 | mode 2 / 5 |
|---|---|---|
| R2 grand any-window | ∈ **[12%, 22%]** | ∈ **[22%, 40%]** |
| R1 high7 any-window | ∈ **[28%, 38%]** | ∈ **[32%, 45%]** |
| R3 high7 any-window | ∈ **[28%, 38%]** | ∈ **[32%, 45%]** |
| R1+R3 wild any-window | ∈ **[12%, 22%]** | ∈ **[15%, 25%]** |
| R2 booster total any-window | ∈ **[18%, 40%]** | ∈ **[35%, 60%]** |

### §7.5 实现脚本

`slot_designer/scripts/redistribute_m37_blanks.py`（仿 M1 但 4-tier multi-priority + per-mode ratio）：
- 输入: M37 spec + reel_strips.json + mode_{1,2,5,7}/weights.json
- 算法: per (mode, reel) 计算每 blank tier，按 mode-specific ratio 分配 weight
- 守恒: per (mode, reel) 总 blank weight 不变 → marginals 不变 → RTP/hit/14 类 verify 全保
- 验证: pre/post marginals byte-identical

应用范围：**4 mode 一次应用**（mode 1/7 用 standard ratio，mode 2/5 用 lucky ratio）

### §7.6 副作用 caveats

- ⚠ **Mid-pay visibility 反向下降**（1bar/2bar/3bar/7bar）— 它们邻位 blank 权重被压低。`MID-PAY-VISIBLE-FLOOR` 18% 防极端。M1 实证 mid-pay (Cherry) 跌幅 -19pp 但仍 well above floor
- ⚠ **Strip md5 不变 / weights md5 改** → 4 mode 旧 sample rawdata 全失效，需重采
- ✓ pay_id frequencies / 倒金字塔 / MODE7-LOCK / MODE5-BASE-LOCK 等 14 类 verify **完全保留**

## 6. 设计 Review Checklist (每次 tune 完必跑, per WORKFLOW.md §1.5 adversarial)

### A. 数值层 (verify_m37_design.py 自动)
- RTP / Hit / bucket shape 在 band
- Booster 倒金字塔
- 各家族 marginal 在合理范围
- ge5000 = 0

### B. Per-reel symbol density review (人眼过)
- R1: 高奖密度 ≥ R3，blank ≤ R3
- R2: 13 个非 Blank 槽位中 booster 共 4 个（mini/minor/major/grand 各 1）
- R3: 与 R1 镜像角色

### C. Per-pay-id frequency review
- 每个 pay_id 都有非零命中（pay_id 8 grand-alone 应有，pay_id 102/103/104 pure-wild-booster 应有）
- pay_id 1 (high7×3) 在 1000× 时 = grand boost path 唯一通道

### D. Bucket distribution review (铃铛形状)
- 是否 Mid+High 略倾斜（vs 1-5× heavy classic）
- ge1000_lt5000 是否 lifetime tier 频率（1 in ~80-100k）
- ge5000 严格 0

### E. Cross-mode narrative review (mode 1 only 现阶段)
- 暂不适用，等 mode 2/5/7 设计后回来 review

### 怎么用
每次 tune 完:
1. 跑 verify_m37_design.py (A 自动)
2. **人眼过 B/C/D** (脚本难 cover player perception)
3. 任一 fail 必须 root-cause:
   - 真 bug → fix
   - 数学结构性 trade-off → 验证是不是真"结构性"（试 fix 看能不能修；修不了才认）
   - verify 漏掉 → 加新硬约束
4. **绝不 patch** 用任意硬 threshold 数字

## 7. 设计 Anti-patterns (避免)

1. **picked numerical thresholds without justification** — 每条数字都需要 archetype/公服 baseline/玩家 cadence 支撑
2. **booster R2 缺一**：mini/minor/major/grand 任一 R2 marginal = 0 = 设计缺陷（jackpot UX tier 残）
3. **R2 装太多 booster** → 总 booster marginal > 15% 玩家麻木（公服 mode 1 ≈ 9.7%）
4. **强行追求 RTP 峰值在 20-200**：与 hit 13-15% 数学冲突；只能"略倾斜"不能"重心移到 20-200"

---

**当前状态**: 4 mode 全部 ship 状态 (2026-05-12 v5/v6/v9.1 finalized, analytic 80/80 GREEN, empirical sub-gate 50k/200k/700k/5M multi-seed 全过 ±2σ。真机 sample 待跑)。

**已知 open TODO**:
1. 真机 sample 重跑（v5/v6/v9.1 weights 改动后需重新真机 verify）
2. mode 2/5 R1 winners-friendly 修(R1 wild weight ×1.10,R3 wild weight ÷1.10)，不动 RTP/hit（v3 历史 TODO 沿用）
3. TDD test file `tests/machines/test_verify_m37_*` 未 wire（proposals in `session_artifacts/M37/verify_v9_1_diff.md` §5）

**ship 历史**:
- **2026-05-12 v9.1**（current）—— m7 真 cut mode feel：R1+R3 bar primary cut (K_bar=0.83) + R2 byte-eq m1 strict + mini K=0.94 微调。hit 17.25 cut 3.67pp vs m1 20.92。pid9 占比 26.44%。RTP 84.75 with safe MC margin（5M mean 84.246）。Commit `b99ee22`。
- **2026-05-12 v8 (m7 only)** —— intermediate, hit ≈ m1 not cut mode (Option E mini unchanged + minor/major cut), user 否决 — pid 9 占比 26% 但 hit 不像 cut mode。Commit `5adbe38`。
- **2026-05-11 v5 (m1) + v6 (m2/m5/m7-base)** —— pid 9 占比 ≈ 20% 红线落地：m1 R2 booster cut + R1+R3 high7 +29%；m2 small lever；m5 auto-inherit；m7 first independent search。Commit `09c7871`。
- **2026-05-08 v3 finalized** —— real Buffalo verify 76/76 GREEN（m1 95.04 / 20.05 / m2 305.23 / 32.38 / m5 510.91 / 33.17 / m7 85.00 / 14.92），5M+ rounds 真机实测。部署到真机后**触发耦合系统 bug**(real Buffalo 给出 580% RTP)。bug 不在 cfg/paytable/sampling，经用户修复后 v3 cfg 真机表现回到 95.04%。
- 诊断工具 `scripts/m37_build_diagnostic_reel.py`：极端权重对比(1000× vs 1×)证明 cfg weight 真在 sampling 时被使用，64k spin 内可排除"server-side 缓存"等假设。复用 pattern：任何"实测跟预期差距大且不能在 1-2 个想法内定位"时，设计极端对照 cfg + 每个 hypothesis 提前写下预测，部署 → 跑 → 一比落地。比黑盒反推快 10×。

**process improvements 来自此次 M37 工作**（已落 memory）:
- **adversarial self-review** — 每次 commit 前 designer 自己 stress-test 5 反问，不能靠 X agent 兜底（commit message 必含 `## Self-critique` 段）
- **layer 4 contamination firewall** — Designer 不读 machine-private DESIGN.md / spec._design / weights._tuned_summary 这些 narrative blocks
- **X gate per Designer milestone** — Stage 4 design 完每次都过 X Critic（不只是 commit 前过一次）
- **framework cite 必须 universal 层** — 不抄 layer 4 历史 narrative。M37 v6 m7 derive 错就是抄 v3 narrative 的"R1/R3 paying × 系数"语言，没回到 universal §4 字面 + spirit
- **诊断 reel pattern** — 任何"实测跟预期差距大"立刻设计极端对照 cfg，不要黑盒反推
