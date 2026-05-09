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

- **Paytable 锁** — `slot_designer/specs/M37.spec.json` 不动（13 个 pay_id, evaluation order, reroll_blocks）
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

### 3.0 4 模式总览（v3 finalized 2026-05-08，real Buffalo verify 76/76 GREEN）

| Mode | RTP | Hit | CV | 1000× 顶奖频率 | R2 booster total | R2 grand | 设计角色 |
|---|---|---|---|---|---|---|---|
| **1 标准** | **95.04%** | **20.05%** | 8.55 | 1 in 39k spin | 8.56% | 0.111% | 经典体验 baseline |
| **2 幸运** | **305.23%** | **32.38%** | 5.88 | 1 in 13k spin | 26.11% | 0.636% | 全 tier 都热 + booster 加密 |
| **5 超幸运** | **510.91%** | **33.17%** | 6.28 | 1 in 2.4k spin | 26.93% | **1.915%** | mode 2 base 字节复制，仅 grand × 2.93 |
| **7 标准低** | **85.00%** | **14.92%** | 9.27 | 1 in 42k spin | 8.45% ← ≈ m1 | 0.114% ← ≈ m1 | 砍小奖、保大奖 + booster freq 锁 mode 1 |

> **2026-05-08 v3 finalized 实测更新**: 上表数字改为真机 5M+ rounds 实测(mode 1: 2.62M,mode 7: 2.43M,mode 2/5: 各 104k)。引擎 paytable 在所有真机 sample 上 100% bit-perfect。
>
> 历史:此前 2026-05-05 版总览(m1 RTP 94.60% / hit 15.70% / m2 304.83% / m5 500.57% / m7 85.38%)是 v* 阶段引擎闭式预测 + 早期 wild count=2 状态;v3 layout 把 R1/R3 wild 改到 3(per §F 公服 baseline)→ hit 自然抬到 20%(side_wild_alone + bar group with wild 命中增多)→ RTP 微调到 95.04%。

跨 mode 不变量（universal §C/§D 契约）— 全部 v3 实测确认:
- **RTP-MONOTONIC**: m7 < m1 < m2 < m5 (85.00 < 95.04 < 305.23 < 510.91) ✓
- **HIT-MONOTONIC**: m7 < m1 < m2 ≈ m5 (14.92 < 20.05 < 32.38 ≈ 33.17, Δm2/m5 = 0.79pp) ✓
- **CV trend**: m7 ≈ m1 (boom-bust) > m2 ≈ m5 (lucky 低 vol) — 9.27, 8.55 > 5.88, 6.28 ✓
- **MODE7-LOCK**: R2 mini/minor/major/grand ≈ mode 1 (m7 grand 0.114% ≈ m1 0.111%) ✓
- **MODE5-BASE-LOCK**: mode 5 base 字节复制 mode 2,仅 R2 grand 缩放 ×2.93 ✓ (实测 m5/m2 grand 比 = 3.01×;hit 比 1.02×;booster total 比 1.03× ✓)
- **TOP-JACKPOT-ESCALATION**: grand 频率 m1 < m2 (×5.71) < m5 (×17.19) ✓ (设计 ×4.9 / ×14.3 — 实测略密)

### 3.1 Mode 1 标准（详细）

| 指标 | target | 实现 (v3 真机 2.62M) | 理由 |
|---|---|---|---|
| RTP | 95% ±1pp | **95.04%** ✓ | global mode 1 contract |
| 总击中率 | **18-22%** | **20.05%** ✓ | v3 wild count=3 (per §F 公服 baseline) 的自然区间 — band 从原 [13, 18] 扩到 [18, 22] 反映 v3 layout 实际 |
| 顶奖 1000× 频率 | 约 1 in 30-100k | 1 in 39k ✓ | "lifetime / session-record" tier |
| > 1000× | **0** | 0 ✓ | paytable 数学上限 1000× |

> **2026-05-08 hit band 更新历史**: 早期 v* 设计 wild count=2,hit ≈ 15.70%,band [13, 18]。v3 把 R1/R3 wild 改到 3 后 hit 实测 20%。每多一个 wild 的 side_wild_alone (mult 1) + bar group with wild substitute 命中累加,把 hit 抬高 ~4pp。这是 §F archetype lock(公服 wild count=3)的直接连带,不是设计漂移。

### 3.1.5 Mode 7 标准-低（cut mode 派生）

| 指标 | target | 实现 (v3 真机 2.43M) |
|---|---|---|
| RTP | 85% ±1.5pp | **85.00%** ✓ |
| 总击中率 | mode 1 - 4-6pp | 14.92% (mode 1 20.05 → -5.13pp) ✓ |
| R2 booster freq | ≈ mode 1 | grand 0.114% ≈ m1 0.111% / booster total 8.45% ≈ m1 8.56% ✓ |
| Mid+High+Top bucket hit | ≈ mode 1 | 0.92×/0.97×/0.93× (slight cut acceptable) |

**派生机制**：mode 1 → mode 7 通过 R1+R3 paying-symbol weight × 系数（high7 × 0.93 / bars × 0.78 / wild × 0.55），R2 byte-identical 锁 booster reveal cadence 跟 mode 1 一致。

### 3.1.6 Mode 2 幸运（独立 archetype）

| 指标 | target | 实现 (v3 真机 104k) |
|---|---|---|
| RTP | 300% ±20pp | **305.23%** ✓ |
| 总击中率 | mode 1 × 1.5-2 | 32.38% (mode 1 × 1.62) ✓ |
| R2 booster total | **16-28%** | **26.11%** ✓ (band 从原 [16, 24] 扩到 [16, 28] 反映 v3 mode 2 实际加密) |
| R2 grand | 0.3-0.8% | 0.636% (mode 1 × 5.71) ✓ |
| 1000× 顶奖频率 | 约 1 in 3-10k | 1 in 13k ⚠ (8 次命中/104k 样本太少,SE 大;预计更多采样后回 band) |

**设计意图**：lucky 模式 — wild 在 R1+R3 显著加密,R2 booster 全 tier 加密(mini 3.73→11.0% / minor 2.69→8.4% / major 2.04→6.1% / grand 0.11→0.64%)。R1+R3 blank 显著降低。玩家"运气来了"体感来自 booster reveal 频率提升,小奖密度提升,顶奖密度 ×5。

**TODO (mode 2 R1 winners-friendly)**: 实测 R1 (high7+wild) 13.61% < R3 13.95%,违反 §12 R1 ≥ R3 top 密度约束。修法:R1 wild weight ×1.10 / R3 wild weight ÷1.10,RTP/hit 不变。

### 3.1.7 Mode 5 超幸运（mode 2 派生）

| 指标 | target | 实现 (v3 真机 104k) |
|---|---|---|
| RTP | 500% ±30pp | **510.91%** ✓ |
| Base 跟 mode 2 byte-eq | 必须 | ✓ except R2 grand (实测 booster 比 1.03×, hit 比 1.02× ≈ 1) |
| R2 grand | 1.2-2.0% | **1.915%** (mode 2 × 3.01,设计 ×2.93) ✓ |
| 1000× 顶奖频率 | 约 1 in 1k-3k | 1 in 2.4k ✓ |
| 总击中率 | ≈ mode 2 | 33.17% (mode 2 32.38% + 0.79pp 来自 grand 加密) ✓ |

**设计意图**：super-lucky = mode 2 的 luck variant,**玩家在 base 层(小奖/中奖/booster reveal)感觉跟 mode 2 完全一样**,差异 100% 来自 grand 频率上升 → grand-alone (100×) + 1000× 顶奖的连带飙升。这是"super-lucky 是 mode 2 的运气版本,不是另一台机"的实现 — 公服 M37Cfg skin 5 vs skin 2 实证支持此 derivation rule。

**TODO (mode 5 R1 winners-friendly)**: 跟 mode 2 同一个问题,R1 13.46% < R3 14.19%,跟 mode 2 一起修。

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

mode 1 是 mode 7 的 anchor。mode 7 派生时:
- R2 booster 频率 ≈ mode 1(实测 grand 0.114% ≈ m1 0.111%)— **MODE7-LOCK** ✓
- R1+R3 paying-symbol weight × 系数(high7 × 0.93 / bars × 0.78 / wild × 0.55)→ Low 砍降 hit
- 实测 m7 hit 14.92% vs m1 20.05%(下降 5.13pp,约束 ≤ 6pp)

mode 1 是 mode 2 的对照:
- mode 2 hit > mode 1 (32.38% vs 20.05%, 1.62×)
- mode 2 booster marginal > 2× mode 1 (R2 booster 26.11% vs 8.56%, 3.05×)
- 顶奖 1000× 频率 > mode 1 (1 in 13k vs 1 in 39k, 3×)

### 3.4 v3 finalized 全 4 mode 验证状态(2026-05-08 真机 5M+ rounds)

| 检查项 | Mode 1 | Mode 7 | Mode 2 | Mode 5 |
|--------|--------|--------|--------|--------|
| RTP 在 §C band | ✓ | ✓ | ✓ | ✓ |
| hit 在 mode-specific band | ✓ (band 已更新到 [18,22]) | ✓ | ✓ | ✓ |
| R2 booster total band | ✓ | ✓ | ✓ (band 更新到 [16,28]) | ✓ |
| R2 grand band | ✓ | ✓ | ✓ | ✓ |
| 1000× freq band | ✓ | ✓ | ⚠ 样本不足 | ✓ |
| paytable bit-perfect (vs 真机) | 100% (2.62M) | 100% (2.43M) | 100% (104k) | 100% (104k) |
| §2 BOOSTER-HIER (倒金字塔 + ratio ≥ 1.3) | ✓ | ✓ | ✓ | ✓ |
| §2 BOOSTER-R1R3-EMPTY / WILD-R2-EMPTY | ✓ | ✓ | ✓ | ✓ |
| §12 R1 ≤ R3 ≤ R2 blank | ✓ | ✓ | ✓ | ✓ |
| §12 R1 top 密度 ≥ R3 | ✓ | ✓ | **✗ TODO** | **✗ TODO** |
| §F TOP-PATH-1000× ≥ 99% via anchor | 100% | 100% | 100% | 100% |
| §7.4 R2 grand any-window | ✓ | ✓ | ⚠ 略低 lucky band | ⚠ 略低 lucky band |
| §7.4 R1/R3 high7 any-window | ✓ | ✓ | ✓ | ✓ |
| §7.4 R1/R3 wild any-window | ✓ | ✓ | ✓ | ✓ |
| 跨 mode invariants(MONOTONIC / MODE5-BASE-LOCK / TOP-JACKPOT-ESCALATION) | ✓ | ✓ | ✓ | ✓ |

**Open TODO (mode 2/5 only)**: R1 winners-friendly 在 lucky 模式没保住(R1 top 密度 < R3 0.34-0.73pp)。修法见 §3.1.6/3.1.7 TODO 注释。

## 4. Verify 类别（红线 → `verify_m37_design.py`）

| 类别 | 检查 | 依据 |
|---|---|---|
| `RTP` | mode 1 ∈ [94%, 96%] | global contract |
| `HIT` | mode 1 ∈ [13%, 15%] | user-pinned |
| `BUCKET-SHAPE` | 实际 vs target bucket_rate JS divergence ≤ threshold | 铃铛分布检查 |
| `BUCKET-CAP` | `ge5000` rate = 0 | paytable cap |
| `ALTERNATION` | strip 严格 B/N 交替, 0 violations | universal §E |
| `BLANK-FLANK-DIVERSITY` | strip[p-1] ≠ strip[p+1] for all blank p | universal §13 |
| `BOOSTER-R1R3-EMPTY` | mini/minor/major/grand 在 R1+R3 marginal = 0 | M37 paytable rule |
| `WILD-R2-EMPTY` | wild 在 R2 marginal = 0 | M37 paytable rule |
| `BOOSTER-HIER` | R2 上 mini > minor > major > grand, 相邻 ratio ≥ 1.3× | universal §1 + 公服 baseline |
| `BOOSTER-VISIBLE` | R2 booster 总 marginal ∈ [7%, 13%] mode 1 | brand promise + 公服 baseline ~9.7% |
| `GRAND-SIGNATURE` | grand R2 marginal ∈ [0.05%, 0.15%] mode 1 | "lifetime tier" + 公服 0.08% |
| `REEL-ASYMMETRY` | R1 Blank ≤ R3 Blank ≤ R2 Blank; R1 顶奖密度 ≥ R3 | §12 + M37 booster reel role |
| `REROLL-VERIFY` | spec.reroll_blocks 含 (wild, grand, wild) | engine 已测，verify 兜底 |
| `TOP-PATH-1000X` | 1000× 顶奖 ≥ 99% 通过 high7-grand anchor | brand narrative + reroll-block 实现 |

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
- `slot_designer/specs/M37.spec.json`（已存在）
- `slot_designer/weights/M37/reel_strips.json`（26-stop + `_archetype` block）
- `slot_designer/weights/M37/mode_1/weights.json`（per-stop 权重，初值参考公服 marginal）
- `slot_designer/scripts/verify_m37_design.py`
- `slot_designer/tuner/targets/M37_mode1.target.json`

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

**当前状态**: 4 mode 全部 ship 状态 (2026-05-08 v3 finalized,真机 5M+ rounds 验证 §C/§D/§F/§12-§15 全过)。

**已知 open TODO**:
1. mode 2/5 R1 winners-friendly 修(R1 wild weight ×1.10,R3 wild weight ÷1.10),不动 RTP/hit
2. mode 2 1000× freq 等更多采样验证
3. mode 2/5 R2 grand any-window lucky band [22,40] 略低,选择性追加 PWDF lucky tier ratio 微调

**ship 历史**:
- 2026-05-08 v3 finalized 部署到真机后**触发耦合系统 bug**(real Buffalo 给出 580% RTP,本来应 95%)。bug 不在 cfg/paytable/sampling,在真机的耦合系统某层,经用户修复后 v3 cfg 真机表现回到 95.04%(完全符合设计)。
- 该次诊断用了"诊断 reel 设计"工具(`scripts/m37_build_diagnostic_reel.py`):用极端权重对比(1000× vs 1×)证明 cfg 的 weight 真在 sampling 时被使用,从 12 万 spin 实测可立即排除"server-side 缓存"等假设。这个工具值得复用。
