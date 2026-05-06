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

### 3.0 4 模式总览（已实现 2026-05-05，verify 52/52 GREEN）

| Mode | RTP | Hit | CV | 1000× 顶奖频率 | R2 booster total | R2 grand | 设计角色 |
|---|---|---|---|---|---|---|---|
| **1 标准** | 94.60% | **15.70%** | 9.63 | 1 in 26k spin | 8.37% | 0.113% | 经典体验 baseline |
| **2 幸运** | 304.83% | **32.31%** | 7.62 | 1 in 3k spin | 19.64% | 0.558% | 全 tier 都热 + booster 加密 |
| **5 超幸运** | 500.57% | **33.03%** | 7.60 | 1 in 1k spin | 20.49% | **1.616%** | mode 2 base 字节复制，仅 grand × 2.93 |
| **7 标准低** | 85.38% | **13.30%** | 9.96 | 1 in 28k spin | **8.37%** ← byte-eq m1 | 0.113% ← byte-eq m1 | 砍小奖、保大奖 + booster freq 锁 mode 1 |

跨 mode 不变量（universal §C/§D 契约）：
- **RTP-MONOTONIC**: m7 < m1 < m2 < m5 ✓
- **HIT-MONOTONIC**: m7 < m1 < m2 ≈ m5 ✓
- **CV trend**: m7 ≈ m1 (boom-bust) > m2 ≈ m5 (lucky 低 vol) ✓ 契合 §5
- **MODE7-LOCK**: R2 mini/minor/major/grand byte-eq mode 1 ✓ 公服 skin 7 实证
- **MODE5-BASE-LOCK**: mode 5 base 字节复制 mode 2，仅 R2 grand 缩放 ×2.93 ✓ 公服 skin 5 实证
- **TOP-JACKPOT-ESCALATION**: grand 频率 m1 < m2 (×4.9) < m5 (×14.3) ✓

### 3.1 Mode 1 标准（详细）

| 指标 | target | 实现 | 理由 |
|---|---|---|---|
| RTP | 95% | **94.60%** | global mode 1 contract |
| 总击中率 | 13-18% | **15.70%** | 1-line classic + R2 重 booster + brand wild 的自然区间 |
| 顶奖 1000× 频率 | 约 1 in 30-100k | 1 in 26k | "lifetime / session-record" tier (lifetime 边缘) |
| > 1000× | **0** | 0 ✓ | paytable 数学上限 1000× |

### 3.1.5 Mode 7 标准-低（cut mode 派生）

| 指标 | target | 实现 |
|---|---|---|
| RTP | 85% ±1.5pp | **85.38%** ✓ |
| 总击中率 | mode 1 - 2-3pp | 13.30% (mode 1 15.70 → -2.40pp) |
| R2 booster freq | byte-eq mode 1 | **byte-eq ✓** |
| Mid+High+Top bucket hit | ≈ mode 1 | 0.93×/0.87×/0.79× (slight cut acceptable) |

**派生机制**：mode 1 → mode 7 通过 R1+R3 paying-symbol weight × 系数（high7 × 0.93 / bars × 0.78 / wild × 0.55），R2 byte-identical 锁 booster reveal cadence 跟 mode 1 一致。

### 3.1.6 Mode 2 幸运（独立 archetype）

| 指标 | target | 实现 |
|---|---|---|
| RTP | 300% ±20pp | **304.83%** ✓ |
| 总击中率 | mode 1 × 1.5-2 | 32.31% (mode 1 × 2.06) |
| R2 booster total | 16-24% | **19.64%** ✓ |
| R2 grand | 0.3-0.8% | 0.558% (mode 1 × 4.9) |
| 1000× 顶奖频率 | 约 1 in 3-10k | 1 in 3k ✓ |

**设计意图**：lucky 模式 — wild 在 R1+R3 显著加密 (1.78% → 6.7%)，R2 booster 全 tier 加密（mini 3.64→8.32 / minor 2.62→6.19 / major 2.00→4.57 / grand 0.11→0.56）。R1+R3 blank 显著降低（30→35% but with much more high7/wild）。玩家"运气来了"体感来自 booster reveal 频率 ×2.4，小奖密度 ×2，顶奖密度 ×5。

### 3.1.7 Mode 5 超幸运（mode 2 派生）

| 指标 | target | 实现 |
|---|---|---|
| RTP | 500% ±30pp | **500.57%** ✓ |
| Base 跟 mode 2 byte-eq | 必须 | ✓ except R2 grand |
| R2 grand | 1.2-2.0% | **1.616%** (mode 2 × 2.93) |
| 1000× 顶奖频率 | 约 1 in 1k-3k | 1 in 1k ✓ |
| 总击中率 | ≈ mode 2 | 33.03% (mode 2 32.31% + 0.72pp 来自 grand 加密) |

**设计意图**：super-lucky = mode 2 的 luck variant，**玩家在 base 层（小奖/中奖/booster reveal）感觉跟 mode 2 完全一样**，差异 100% 来自 grand 频率上升 → grand-alone (100×) + 1000× 顶奖的连带飙升。这是"super-lucky 是 mode 2 的运气版本，不是另一台机"的实现 — 公服 M37Cfg skin 5 vs skin 2 实证支持此 derivation rule。

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

mode 1 是 mode 7 的 anchor。mode 7 派生时：
- 中/大/顶奖 hit 严格不动（→ `MODE7-LOCK` verify）
- Low 砍 ≤ 3pp（→ `MODE7-CUT`）
- Booster 频率字节级 = mode 1（公服 baseline 已实证）

mode 1 是 mode 2 的对照：
- mode 2 hit ≥ 1.5× mode 1（hit 21-28%）
- mode 2 booster marginal ≥ 2× mode 1
- 顶奖 1000× 频率 ≥ 3× mode 1

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

**当前状态**: mode 1 设计中（仅 mode 1 ; mode 2/5/7 后续设计）
