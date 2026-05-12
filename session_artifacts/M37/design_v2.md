# M37 mode 1 design_v2 — 2026-05-11

> **Designer fresh-context v2**, per user_brief.md § v2 AMENDMENT.
> User 拍板放开 R1+R3 bar weights，禁动 wild/high7。Designer 在新 scope 下重做。

## 1. v2 lever scope (confirm)

可改：`weights[1][5]` (R2 mini)、`weights[1][11]` (R2 minor)、`weights[1][17]` (R2 major)、R1 bar 4 symbols (`1bar/2bar/3bar/7bar` × 8 positions)、R3 bar 4 symbols (× 8 positions)。R1/R3 blank 被动吸收 saved weight。

**禁动**：R2 grand、R2 high7、R2 bar/blank、R1 wild/high7、R3 wild/high7、strip、paytable、mode 2/5/7。

## 2. Lever physics (first principles)

baseline pid 分解（from 01b）:
- pid 7 (any-bar mixed) P=8.91%, RTP-pp=16.92 → ge1_5 contribution **7.35pp** (mult 1×) + ge5-10/10-20 (wild substitute)
- pid 9 mult 2× (mini-alone, no R1+R3 match) → ge1_5 **5.13pp**
- pid 9 mult 1× (side-wild-alone) → ge1_5 **2.58pp** **UNCUTTABLE** (wild 不动)
- pid 6 mult 2× (high7+7bar mixed) → ge1_5 **1.31pp** **UNCUTTABLE** (high7 不动)
- pid 5-4 (single-bar 3-of-kind small mult) → ge1_5 ~1.5pp (cuttable via bar)
- Other small uncuttable ~0.4pp

**Cuttable ge1_5 mass = ~14pp** (pid 7 + pid 9 mult 2× + small bar 3-of-kind)
**Uncuttable ge1_5 mass = ~4.3pp** (pid 9 mult 1× + pid 6 mult 2× + 高7 mult 4× via wild)

→ **ge1_5 absolute physical floor in v2 = ~4.3pp**. User target 9.6pp **is above floor**, so theoretically reachable from ge1_5 side alone.

但 ge1_5 cut 受 RTP 锁约束: 把 pid 7 + mini-alone 砍掉同时 RTP 必须留在 [94, 96]。pid 7+pid 9 mult 2× 合占 RTP ~12.5pp，全砍掉后 RTP 总 -12.5pp。需要 boost 别处来回填，**唯一可用 lever** = R2 minor/major（mini 又被禁砍）。但 R2 minor/major 上涨也会 boost ge1_5 间接（via minor-3-of-kind landing ge5-10 不影响 ge1_5，但其它路径 + minor itself 增加 hit）。

## 3. Feasibility verification (4D grid + spot check)

Grid: k1 (R1 bar scale) × k3 (R3 bar scale) × R2 (mini_w, minor_w, major_w)。每点 analytic_profile 评估。

**约束矩阵（min hit / min ge1_5 at RTP ∈ [94, 96]）**:

| HIER | §12 R3≤R2 | §12 R1≤R3 | min hit | min ge1_5 | user 红线？|
|---|---|---|---|---|---|
| ratio ≥ 1.3 (universal §1) | strict (M37 verify.py) | strict | **18.48** | **17.74** | ❌ |
| ratio ≥ 1.0 (monotone only) | strict | strict | **17.41** | **15.76** | ❌ |
| ratio ≥ 1.0 (monotone only) | **relaxed** | strict | **16.63** | **14.36** | ❌ (hit gap 0.63, ge1_5 gap 4.76) |
| inverted (minor > mini) | strict | strict | 12.69 | 6.56 | ✓ **315 in box** — 但 user 已 reject v0 |

**结论**: v2 lever 在 user 接受的 HIER 范围内 (mini > minor)**仍达不到 (hit 14-16) ∩ (ge1_5 ≈ 9.6)**。

**ge1_5 是绑死项**: 即使放开 §12-M37 R3≤R2，ge1_5 min 仍 14.36，**比 user 目标 9.6pp 高 4.76pp**。差距来源：

1. RTP-comp constraint: 砍 R1+R3 bar 砍 RTP，需要 R2 boost 回填，boost 出来的 mass 会落到 ge5-10/ge10-20 但**对 ge1_5 几乎无补**（因为 minor/major-alone 不在 ge1_5）。但 mini cut 受 HIER 锁——HIER monotone 要 mini > minor > major，最低可设 mini=400 (ratio 1.05 to minor=380)。**mini 仍 4.0%**(vs baseline 3.73%)，反而比 baseline 高！
2. **想砍 mini-alone (ge1_5 5.13pp) 必须 mini ↓，但 mini ↓ 又破 HIER (除非 minor 同步 ↓)**。然而 minor ↓ 则 RTP ↓ 又破 [94, 96]。

→ 物理 zero-sum dance。

## 4. 候选点 (5 个) + 推荐

| 候选 | k1 | k3 | mi/mn/mj | RTP | hit | ge1_5 | ge20_100 | R3-R2 | HIER | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|
| BASELINE | 1.0 | 1.0 | 365/262/200 | 95.45 | 20.07 | 19.59 | 16.54 | -15.3 | 1.39/1.31 | v3 finalized |
| **REC-1 (推荐)** | 0.75 | 0.45 | 400/380/250 | 94.04 | 16.63 | 14.36 | 12.71 | **+13.0** | **1.05**/1.52 | 离 user 最近，§12-M37 R3≤R2 violate +13pp |
| REC-2 | 0.65 | 0.55 | 400/380/250 | 94.48 | 16.78 | 14.52 | 12.92 | +8.0 | 1.05/1.52 | RTP 中位，R3-R2 违反小 |
| REC-3 | 0.60 | 0.55 | 400/380/250 | 93.73 | 16.57 | 14.29 | 12.54 | +8.0 | 1.05/1.52 | RTP 93.7 略 < 94 |
| HIER-strict (1.3) | 0.725 | 0.725 | 500/380/200 | 94.30 | 18.48 | 17.74 | 14.47 | +0.6 | 1.32/1.90 | HIER 强保但 hit 大幅 fail |

**Designer 推荐 REC-2** (k1=0.65, k3=0.55, R2=400/380/250)：
- **最佳 hit/ge1_5 trade-off** 在 user-acceptable HIER 内
- §12-M37 R3≤R2 违反 8pp（不是 +13pp 大裂口）
- RTP 94.48 居中安全
- 但 **hit 16.78 (gap 0.78pp) 和 ge1_5 14.52 (gap 4.92pp) 仍不达 user 红线**

## 5. REC-2 详细

### 5.1 Weight 改动

- R1 8 bar pos: ×0.65 each (saved weight → R1 blank pos)
- R3 8 bar pos: ×0.55 each (saved weight → R3 blank pos)
- R2[5] mini 365→400, R2[11] minor 262→380, R2[17] major 200→250
- L1 total weight change ≈ 4700 units (vs v1 max 27; symbol of "放开 bar")

### 5.2 Marginal change

| Reel/Symbol | Baseline | Target | Δpp |
|---|---|---|---|
| R1 bar | 49.49% | 32.15% | **-17.3** |
| R1 blank | 34.48% | 51.82% | +17.3 |
| R3 bar | 49.52% | 27.24% | **-22.3** |
| R3 blank | 35.20% | 57.47% | +22.3 |
| R2 mini | 3.73% | 4.00% | +0.27 |
| R2 minor | 2.68% | 3.80% | +1.12 |
| R2 major | 2.04% | 2.50% | +0.46 |
| R2 blank | 50.46% | 49.44% | -1.0 (passive, mini+minor+major up) |
| (R1/R3 wild/high7, R2 grand/high7/bar) | unchanged | locked | — |

### 5.3 Bucket distribution

| Bucket | Baseline | REC-2 | Δpp |
|---|---|---|---|
| ge1_lt5 | 19.59 | **14.52** | **-5.07** (user 目标 -10pp; 50% 达成) |
| ge5_lt10 | 14.02 | 18.65 | +4.63 |
| ge10_lt20 | 23.41 | 27.51 | +4.10 |
| ge20-100 sum | 16.54 | **12.92** | **-3.62** (user 目标 +10pp; 反向 ⚠) |
| ge100_lt200 | 14.78 | 16.34 | +1.56 |
| ge200+ | 7.11 | 4.54 | -2.57 |
| **Total RTP** | **95.45** | **94.48** | -0.97 |
| **Hit** | **20.07%** | **16.78%** | -3.29 |

## 6. Honest assessment vs user precise 红线

| User 红线 | REC-2 实际 | 达成？ | Gap |
|---|---|---|---|
| hit ∈ [14, 16] | **16.78%** | ❌ | +0.78pp 高于上界 |
| ge1_5 砍 10pp (→ ~9.6pp) | **14.52pp** (cut 5.07pp from 19.59) | ❌ | gap 4.92pp 还远 |
| ge20-100 +10pp (→ ~26.5pp) | **12.92pp** (反向 -3.62pp) | ❌ | gap ~13.5pp（且方向反） |

**No red line reached.** v2 lever 比 v0 (无 lever 限制) 弱很多，比 v1 (仅 R2 mini/minor/major) 强一些，但仍不够。

### 6.1 ge20-100 反向解释

砍 R1+R3 bar 后，(bar×bar) 类 base 概率剧降，连带 (bar×3 × booster) 也降 → ge20-100 mass 流失到 ge100-200（high7 没动 → high7×high7×high7 + booster 组合稳定但 mass 降）和 ge1_5 (uncuttable side-wild-alone 仍贡献)。

## 7. Cross-mode invariants check

| Invariant | REC-2 | 状态 |
|---|---|---|
| RTP-MONOTONIC m7<m1<m2<m5 | m1=94.48, m7=85, m2=305, m5=510 | ✓ |
| HIT-MONOTONIC | m1=16.78 > m7=14.92 | ✓ |
| CV trend | m1=8.12 > m2/m5 ≈ 6 | ✓ |
| MODE5-BASE-LOCK | m2/m5 unchanged | ✓ |
| MODE7-LOCK (m7 R2 ≈ m1 R2) | m1 R2 mini 3.73→4.00 (+7%), minor 2.68→3.80 (+42%) | ⚠ 需用户拍板 m7 跟改 or LOCK 放宽 |
| TOP-JACKPOT-ESCALATION | m1 1/37k < m2 1/13k < m5 1/2.4k | ✓ (grand 不动) |
| §1 BOOSTER-HIER ratio≥1.3 | **1.05/1.52** | ⚠ mini/minor ratio 跌至 1.05 (universal §1 要 1.3) |
| §2 GRAND-SIGNATURE | grand 0.110% in [0.05, 0.15] | ✓ |
| **§12 REEL-ASYMMETRY R1≤R3≤R2 blank** | R1=51.82, R3=57.47, R2=49.44 — **R3 > R2** | ❌ **break +8pp** |
| §12 R1 (high7+wild) ≥ R3 | R1=16.03 vs R3=15.29 | ✓ (lock 保) |
| TOP-PATH-1000X via high7-grand-high7 | 1/37k ≈ baseline | ✓ |
| §13 BLANK-FLANK-DIVERSITY / §14 VISUAL-RHYTHM | strip 不动 | ✓ |
| §15 PWDF | strip 不动 → 自动 | ✓ |

**违规**: BOOSTER-HIER ratio (1.05 vs 1.3 floor) + §12 R3≤R2 (+8pp)。

## 8. Verify red-line 建议 (V agent)

**不建议改 verify** — 因为 REC-2 还在 verify FAIL 状态（hit/ge1_5/HIER ratio/§12 都 break）。先让 user 拍板 §9，再决定 verify 改动。

**如果 user 选 (A) ship REC-2 接受 partial**:
- [HIT] band 改 [14, 18] (扩到能容纳 16.78)
- [BUCKET-GE1_5] 新加：RTP-pp ∈ [12, 17] (扩到能容纳 14.52)
- [BOOSTER-HIER] ratio floor 改 1.05 (mode 1 only override)
- [REEL-ASYMMETRY] 加 mode 1 only slack：R3 blank ≤ R2 blank + 10pp
- 其它类别保留

**如果 user 选 (B) 扩 lever**: 等 v3 design。

## 9. Open question for user

V0 / V1 / V2 各 lever scope 都达不到 user 红线 (hit 14-16 + ge1_5 -10pp)。v2 最接近但仍 fail。User 必须在三件事里至少选一件 amend：

### 选项 (A) ship REC-2，接受 partial 完成

接受:
- hit **16.78%** (希望 14-16，gap 0.78pp)
- ge1_5 **14.52pp** (希望 9.6pp，gap 4.92pp)
- BOOSTER-HIER ratio 1.05 (universal §1 锁 1.3，mode 1 override)
- §12-M37 R3≤R2 **break +8pp** (R3 blank 57.5% > R2 blank 49.4%)

代价: verify 加 mode 1 override。Narrative: "小奖砍了 26% (19.6 → 14.5)，hit 略降 (20.1 → 16.8)，符合 user 大方向但未达精确数字"。

### 选项 (B) 进一步放开 lever scope — 再加 1 个 symbol

如再加 **R2 high7** weight 进可改 list（约 v0 path）:
- R2 high7 cut 释放 ~10pp RTP budget
- 该 budget 让 R1+R3 bar 可更激进砍 + R2 mini→minor 更激进 shift
- v0 已证：可达 RTP 95.98, hit 15.97, ge1_5 9.54, ge20_100 19.28 ✓ ✓

代价: R2 上 high7 marginal 从 10.5% → ~5%，玩家视觉上"R2 中轴 high7 出现频率减半"。但 1000× jackpot 频率不变（由 grand × R1/R3 high7 决定）。

### 选项 (C) 接受 R2 minor > mini 倒序 (v0 path 的另一面)

User v0 时反对了"minor > mini"。但在 v2 lever 下，**唯一能达 (hit, ge1_5) 红线的 R2 配置就是 minor > mini**:
- HIER inverted 时 315 in box
- 例: k1=0.625, k3=0.45, R2 mini=50, minor=380, major=250 → RTP 94, hit 12.7, ge1_5 7.2

代价: BOOSTER-HIER 倒序，玩家"minor 比 mini 还频繁"，违反 universal §1 + jackpot tier 直觉。

### 选项 (D) amend 目标

User 把 hit 目标改成 [17, 19] / ge1_5 改成 [14, 16] (= REC-2 实测点)。Baseline 微改方向但**不达原"砍 hit / 砍 1-5 倍"** 直觉。

**Designer 推荐 (B)** 放开 R2 high7：v0 已证可达全部红线 + 1000× jackpot freq 不变 + R2 high7 砍跟"砍小奖"体感方向一致。

详见 `design_v2_questions_for_user.md`。

## 10. 附

- `_designer_scratch/v2_probe.py` — v2 lever apply + spot evaluation
- `_designer_scratch/v1_grid_fine.py` — v1 strict lever 67k grid (for comparison)
- session_artifacts/M37/design_v0.md — wide lever feasible point (供选 B 后参考)
- session_artifacts/M37/design_v1.md — strict lever infeasible result
