# Design v1 — 给 user 的拍板（直白短版）

> v0 你 reject 了 lever 太大。v1 我严格按你说的"只动 mini/minor/major"。结果：**3 个目标一个都做不到**。

---

## 核心结论

**只动 R2 mini / minor / major 三个 weight + 保 HIER + 保 RTP 94-96**，做了 6.7 万次组合枚举：

| 你要的 | 实际可达 | Gap |
|---|---|---|
| Hit 14-16% | 最低 **19.81%** | 高 3.81pp |
| ge1_5 砍 10pp (→ 9.6pp) | 最低 **19.18pp** | 只能砍 0.41pp，远不到 10pp |
| ge20-100 +10pp (→ 26.5pp) | 最高 **17.06pp** | 只能升 0.5pp，远不到 +10pp |

**为什么这么惨**: R2 总权重 9789，mini+minor+major 三个加起来才 827（**占 R2 的 8.4%**）。HIER 锁住后他们只能在内部互换，几乎不影响 hit / ge1_5 这两个 user 关心的数字。Hit 主要由 **R1+R3 paying density + R2 blank** 决定——这俩你都禁动了。

---

## 你的选项 — 选一个

### (A) 接受微调（"小改"的最 literal 版本）
最大可达改动：mini 365 → 340，minor/major 不动。
- RTP 94.79（≈ baseline 95.45 微降）
- hit 19.85（≈ baseline 20.07 微降）
- ge1_5 19.18（≈ baseline 19.59 微降）
- ge20-100 16.41（≈ baseline 16.54 微降）

→ 数字上 essentially baseline + noise，**没达到你要的"砍 hit / 砍 1-5 倍"任何效果**。但符合"只动 mini" 的字面要求。

### (B) 放开 lever scope（推荐）
让 Designer 多动 1-2 个 weight。按对 user 目标的影响力排序：

1. **R1+R3 上的 bar weights**（最有用）：直接砍 hit（任意-bar 占 ge1_5 大头）。砍 R1+R3 bar 20% → hit -3-4pp / ge1_5 -3-5pp，**是你目标方向**
2. **R1+R3 上的 wild weights**：砍 wild → 砍 pid 9 (side-wild-alone) → 砍 ge1_5 第二大供给
3. **R2 blank**：抬 blank 整体降 marginal （但跟"只动 mini/minor/major"语义冲突，慎选）

→ 你说一句"开 X"，Designer 就重新设计。

### (C) 改 paytable
不允许（universal §1.1 锁）。列出仅为说明已穷尽。

### (D) 改 strip layout
不允许（mode 2/5/7 rawdata 全失效）。也列出仅为说明已穷尽。

---

## 推荐你选 (B) — 放开 R1+R3 bar

这是 v0 我用过的核心 lever，是你"砍 hit"目标的直接物理对应（少 bar = 少中奖 = hit ↓ + ge1_5 ↓）。**不破 archetype（bar marginal 改 ≈ 公服 baseline ±15%）、不破 R2 booster 频率叙事、不动 grand**。

如果你同意 (B) + 限定 "R1+R3 bar weights only"，Designer 立刻重做 design_v2，目标点会贴近：
- RTP 95 ✓
- hit 14-16 ✓ (cut R1+R3 bar 20-30%)
- ge1_5 -5 to -8pp (砍 anybar pid 7)
- ge20-100 微动（这部分 v0 已证明物理不可达 +10pp，accept directional）

---

## 你需要做的

回复主 session 一句话即可，例如：
- **"选 A，接 baseline 微抖"** → ship 微抖版
- **"选 B，开 R1+R3 bar"** → Designer 做 v2
- **"选 B，开 R1+R3 bar + wild"** → Designer 做 v2 with wider lever
- **"目标改成 hit 17 / ge1_5 14"** → 接受 strict lever 下可达点，部分目标
