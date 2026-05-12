# M37 mode 1 design_v1 — 2026-05-11

> **Designer fresh-context v1**, post-user-reject of v0. Per user_brief.md § v1 AMENDMENT.

## 1. v1 lever scope

只可改 3 个 weight：`weights[1][5]`(R2 mini, baseline 365)、`weights[1][11]`(R2 minor, 262)、`weights[1][17]`(R2 major, 200)。

**不动**: R2 grand / R2 high7 / R2 bar / R2 blank（其它 22 个 R2 positions）/ R1 全部 / R3 全部 / strip / paytable / spec / mode 2/5/7。

**哲学硬约束**: BOOSTER-HIER mini > minor > major > grand 必须 hold，ratio ≥ 1.3。GRAND-SIGNATURE 自动保留（grand 不动）。R2 high7 archetype 自动保留。

## 2. Feasibility within strict lever (enumeration)

### 2.1 Grid scan

dense step=5 enumerate (mini_w, minor_w, major_w) in [5, 500]³ with weight-level HIER pruning：

| Filter | Count |
|---|---|
| Total points evaluated | 67,920 |
| HIER 1.3 OK (marginal-level) | 67,800 |
| **+ RTP ∈ [94, 96]** | **1,325** |
| **+ hit ∈ [14, 16] + ge1_5 ≤ 11** | **0** ❌ |

### 2.2 Reachable extremes within (HIER OK, RTP 94-96)

| 维度 | Baseline | Min reachable | Max reachable | User target |
|---|---|---|---|---|
| **hit %** | 20.07 | **19.81** | 21.50 | **14-16** ⊥ |
| **ge1_5 RTP-pp** | 19.59 | **19.18** | ~21.7 | **~9.6** ⊥ |
| ge20_100 RTP-pp | 16.54 | ~16.0 | **17.06** | (+10pp → 26.5) ⊥ |
| ge5_10 RTP-pp | 14.02 | ~13.6 | ~15.1 | — |
| ge10_20 RTP-pp | 23.41 | ~21.8 | ~23.5 | — |

→ **(hit 14-16) ∩ (ge1_5 ≈ 9.6) 在 strict lever 下 UNREACHABLE**。差距巨大：

- Hit floor at strict-lever 是 **19.81%**，比 user 上界 16% 还高 **3.81pp**
- ge1_5 floor at strict-lever 是 **19.18pp**，比 user 目标 9.6pp 高 **9.58pp**（几乎没动）

### 2.3 物理为何动不了

R2 reel total weight = 9789。3 个可调 stop 的 baseline 总权重 = 365+262+200 = 827 = **R2 总权重的 8.4%**。

把它们全归零（mini=minor=major=1）→ R2 marginal 改 ~5pp（这 3 个 booster 不可见），但 RTP 直接坍塌到 **36.7%**（mini/minor/major 是 RTP 主供给之一）。把它们全设到 500（HIER 上限）→ RTP 升到 117%。

→ 在 (RTP 94-96, HIER 1.3) 双锁定下，3 个权重只能在 baseline ±50 范围微调。**Hit 主要来自 R1+R3 paying density × R2-blank 概率**，两者都在禁动列表里。

### 2.4 Pareto frontier (hit, ge1_5) within HIER+RTP-OK

唯一 Pareto 点：mini_w=400, minor_w=300, major_w=175 → RTP 95.14, hit 20.46, ge1_5 20.15。

L1 改动 < 30 的所有 "user-direction-friendly"（mini ↓, minor or major ↑）feasible 点：

| mini_w | minor_w | major_w | L1 | RTP | hit | ge1_5 | ge20_100 |
|---|---|---|---|---|---|---|---|
| **360** | **260** | **200** | **7** | 95.21 | 20.01 | 19.51 | 16.48 |
| 360 | 270 | 200 | 13 | 95.88 | 20.09 | 19.49 | 16.72 |
| 350 | 260 | 200 | 17 | 95.00 | 19.93 | 19.34 | 16.44 |
| 360 | 270 | 190 | 23 | 94.44 | 20.01 | 19.51 | 16.33 |
| 340 | 260 | 200 | 27 | 94.79 | 19.85 | 19.18 | 16.41 |

**最大 L1 改 27 时**: hit 砍 0.22pp（20.07 → 19.85），ge1_5 砍 0.41pp（19.59 → 19.18），ge20_100 微降 0.13pp。**全部 ≈ baseline ± noise**。

## 3. 推荐点 — 无 (在 feasible region 内)

诚实结论：**strict lever 下没有"推荐点"**。在 (hit 14-16) ∩ (ge1_5 -10pp) 的 user precise red line 下，3 个 weight 的可达空间最多让 hit 砍 0.22pp、ge1_5 砍 0.41pp。这跟 user 期望的 "hit -4 到 -6pp、ge1_5 -10pp" 量级差 10×-20×。

如果硬选一个 "minimal change" 点 cite **L1=27**（mini=340 / minor=260 / major=200）：
- 改 R2 mini weight 365 → 340（cut 7%）
- 不改 minor / major（baseline）
- 结果：RTP 94.79, hit 19.85, ge1_5 19.18, ge20_100 16.41 — **不达 user 任何精确红线**

## 4. Honest assessment vs user precise red lines

| User 红线 | 达成 | Gap |
|---|---|---|
| hit ∈ [14, 16] | **❌** | min reachable 19.81%, gap ≥ 3.81pp 到上界 |
| ge1_5 砍 10pp (→ ~9.6pp) | **❌** | min reachable 19.18pp, gap 9.58pp |
| ge20_100 +10pp (→ ~26.5pp) | **❌** | max reachable 17.06pp, gap 9.44pp |

**没达成的原因**: lever-too-narrow。3 个 weight 仅控 R2 reel 8.4% 的权重份额；hit 主要由 R1+R3 paying density 决定，ge1_5 主要由 R1+R3 bar + R1/R3 wild + R2 mini 4 个 driver 决定。strict lever 只能动其中 1 个 (R2 mini)，且 mini ↓ 必须配 minor + major ↑ 才 hold HIER → mass 在 booster 内重洗，**总 booster RTP 几乎不变 → hit / ge1_5 不变**。

**不是 "structurally impossible per paytable + strip"，是 "structurally impossible per v1 lever scope"。**v0 中我证明 ge20_100 +10pp 跨 paytable+strip 也不可达；但 hit / ge1_5 红线在 v0 wider lever 下是可达的（v0 给的点 RTP 95.98 hit 15.97 ge1_5 9.54 ✓ ✓）。**问题 = lever 太窄，不是物理不允许**。

## 5. Verify red-line 建议

**不建议改 verify**。strict lever 下 baseline 仍 GREEN（v3 finalized 76/76），任何 ±27 L1 变动也仍 GREEN。改 [HIT] band 到 [14, 16] / 加 [BUCKET-GE1_5] 没意义——所有可达点都 fail 那两类。

→ V agent 在 user 做 §6 拍板后再确定改不改 verify。

## 6. Open question for user — **escalation required**

Strict lever 下 user 的 3 个精确红线**没有一个可达**。User 必须在以下里选一个：

- **(A) 接受可达点**: 比如 mini=340/minor=260/major=200 (L1=27)。RTP 94.79, hit 19.85, ge1_5 19.18, ge20_100 16.41。**这是 essentially baseline 微抖动**——可能跟 user "小改" 直觉一致但跟 user "砍 hit 砍 ge1_5" 数字目标完全不匹配
- **(B) 放开 lever scope**: User 主动允许加 1-2 个额外 weight 进 scope。最有用候选（按"hit / ge1_5 影响力"排序）：
  1. **R1+R3 bar weights**: 它们是 ge1_5 (pid 7 anybar) + hit 主供给。**最有用**
  2. **R1+R3 wild weights**: 喂 pid 9 side-wild-alone (ge1_5 第二大供给)
  3. **R2 blank** 或 **R2 high7**: 整体 booster cadence 调节
- **(C) 改 paytable**: forbidden per universal §1.1，列出仅说明已穷尽
- **(D) 改 strip layout**: forbidden per "小改"（mode 2/5/7 rawdata 失效）

详见 `design_v1_questions_for_user.md`。

## 7. 附

Evidence:
- `_designer_scratch/v1_grid.py` — coarse step=25 grid (580 candidate, 9 RTP-OK, 0 box)
- `_designer_scratch/v1_grid_fine.py` — dense step=5 grid (67,920 candidate, 1,325 RTP-OK, 0 box)
- Corner-probe (mini=200/minor=100/major=50 → RTP 57.7 hit 15.97 ✓ hit-band) 证明 hit 14-16 只在 RTP ≤ 61% 才可达
