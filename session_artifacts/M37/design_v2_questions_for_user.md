# Design v2 — 给 user 的拍板（直白短版）

> v2 lever 放开 R1+R3 bar 后，**仍达不到 user 红线**。Designer 数学穷尽后请你再选一次。

## 最关键的数字

| User 红线 | v2 最佳点 (REC-2) | Gap |
|---|---|---|
| hit ∈ [14, 16] | **16.78%** | +0.78pp 高于 16 |
| ge1_5 砍 10pp (→ 9.6pp) | **14.52pp** (砍 5.07pp) | gap 4.92pp（一半都没砍到）|
| ge20-100 +10pp (→ 26.5pp) | **12.92pp** (反而 -3.62pp) | gap 13.6pp，**方向反了** |

物理原因：v2 lever 禁动 R1+R3 wild/high7 + 禁动 R2 high7/blank。这些恰好是 v0 可达 user 红线的关键 lever。砍 R1+R3 bar 让 RTP 下降，但 R2 mini/minor/major 上涨 comp RTP 时也把 hit 顶回去——zero-sum dance。

## 4 个选项 — 选一个

### (A) Ship REC-2 (部分完成 + verify 加 mode 1 override)
- hit 16.78（接近 16 但不达），ge1_5 14.52（一半都没砍到），ge20-100 12.92（反方向）
- BOOSTER-HIER ratio 1.05（mini > minor，但 ratio 跌到 1.05；universal §1 锁 1.3）
- §12-M37 R3≤R2 break +8pp
- Narrative: "小奖砍了 26%，hit 略降，符合大方向但未达精确数字"

### (B) 放开 R2 high7 lever（Designer 推荐）
- v0 已证：可达 RTP 95.98, hit 15.97 ✓, ge1_5 9.54 ✓, ge20-100 19.28（仍 +10pp 不可达 — 物理硬上限）
- 代价：R2 上 high7 marginal 10.5% → ~5%（"中轴 high7 出现频率减半"）
- **1000× jackpot 频率不变**（由 grand × R1/R3 high7 决定）
- 优点：是唯一能达 hit + ge1_5 双 ✓ 的现实方案

### (C) 接受 minor > mini 倒序
- v0 path 的另一面：mini=50, minor=380, major=250 → RTP 94, hit 12.7, ge1_5 7.2（甚至超目标）
- 代价：BOOSTER-HIER 倒序，玩家"minor 比 mini 还频繁"，**user v0 时明确反对过**

### (D) 把 user 目标改成可达点
- 接受 hit 17-19、ge1_5 14-16（= REC-2 实测）
- 这是"baseline 微改" 方向，但**不达原"砍 hit / 砍 1-5 倍"** 直觉

---

## Designer 强烈推荐 (B)

理由：
1. v0 已证 (B) 可达 user 红线 hit + ge1_5 双 ✓
2. 1000× jackpot frequency 不变（grand 不动 + R1/R3 high7 不动 → jackpot path 完整）
3. R2 中轴 high7 砍半 跟 user "砍小奖" 体感方向一致（high7 是中段锚，砍它 = 中段 reveal 稀）
4. 不破 archetype（M37Cfg 公服 baseline 也有 high7 marginal 但本来就是设计选择，可调）
5. 不需要 inverted HIER（mini > minor 仍 hold）

代价就一个：R2 中轴的 high7 视觉频率从 10.5% → ~5%。但**没有更便宜的路了**。

---

## 你需要做的

回复主 session 一句话：
- **"选 A，ship REC-2"** → ship 部分达成版，verify 加 mode 1 override
- **"选 B，开 R2 high7"** → Designer 做 v3（其实就是回去拿 v0）
- **"选 C，接 minor > mini"** → Designer 做 v3 with inverted HIER
- **"选 D，改目标 hit 17 / ge1_5 14"** → ship REC-2 当目标

Designer 等指示。
