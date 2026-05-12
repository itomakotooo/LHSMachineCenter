# M37 mode 1 small tune — session brief

> Scope: **mode 1 only**. Mode 2/5/7 是 v3 finalized 2026-05-08 真机 5M+ rounds 验证过的状态，**不动**。Paytable 也不动（§1.1 universal）。

## 0. 当前已 ship 状态 (2026-05-08 v3 finalized)

Mode 1 实测 (真机 2.62M rounds, bit-perfect 引擎对齐):
- RTP 95.04%
- hit 20.05%
- ge1_5 bucket RTP ≈ 19.6pp
- ge20-100 bucket RTP ≈ 16.5pp (ge20_50 9.7pp + ge50_100 6.85pp)
- 76/76 verify categories GREEN

## 1. User 本次要求 (2026-05-11)

> "小改。先改 mode 1。1，把中奖率砍到 14-16 之间。2，把 1-5 倍的 rtp 占比砍掉 10pp，投放到 20-100 之间。方式：基本上就是砍掉 reel2 上 mini wild 的概率，放到 minor 和 major？"

### §1.2 约束类型 (per ONBOARDING_PROCESS §1.2)

| User 输入 | 约束类型 | 备注 |
|---|---|---|
| hit ∈ [14%, 16%] | **precise red-line**（明确单位 + 数字范围）| Designer verify [HIT] band 改 |
| ge1_lt5 RTP 砍 10pp (19.6 → ~9.6pp) | **precise red-line** (明确 magnitude)| Designer 加 [BUCKET-GE1_5] band |
| ge20_lt100 RTP +10pp (16.5 → ~26.5pp) | **？** — User 用了"投放到 20-100 之间" 但跟 lever 提示连读，可能 directional | **Designer Stage 4 时需澄清** |
| Lever: R2 mini → minor + major | directional hint (user 用"基本上" + "?" 不肯定) | Designer 评估 → 提替代方案 OK |

### §2.1 contamination firewall 提醒

Designer 不应读 layer 4 派生层（已删的旧 NOTES.md / `_design` blocks）。
**可读**：
- `slot_designer/DESIGN_PHILOSOPHY.md`（universal layer）
- `slot_designer/machines/M37/spec.json` 的 mechanism blocks（pays / symbols / evaluation_order）
- `slot_designer/machines/M37/DESIGN.md` 的 §1 archetype + §2 hard constraints — **设计契约真理源**
- `slot_designer/machines/M37/reel_strips.json` `_archetype` block
- `01b_baseline_analytic.txt`（本 session 主 session 已 dump）
- 本 brief
- `feasibility_v0_notes.md`（本 session 主 session 探索结果，作 evidence 不作结论）
- 公服 baseline `machineconfig/M37Cfg.txt _excel.M37Reel skin 1`（archetype 真理源）

**禁读**：
- M37 DESIGN.md 里 §3 "玩家体验目标" 的具体数字（这是 v3 派生层，Designer 应 derive 自己的新数字）
- 任何旧 `TUNE_REPORT.md` 的"调到 X 的理由"

## 2. 已发现的结构性 finding（pre-spawn main-session evidence）

主 session 跑了一组变种 evidence (落 `feasibility_v0_notes.md`)，**preliminary 发现 ge20_lt100 +10pp 在当前 paytable + 不动 mode 2/5/7 base 的约束下，可能 structurally 难达**：

- ge20-100 桶现有 16.5pp **由 8 个 specific combo 喂**：
  - (high7×3) × minor = 50× → 3.24pp（单 combo 最大）
  - (high7×3) × mini = 20× → 1.80pp
  - (7bar×3) × minor = 30× → ?pp (待 Designer 重 enumerate)
  - (3bar×3) × major = 50× → 2.13pp
  - (3bar×3) × minor = 25× → 1.39pp
  - (2bar×3) × major = 40× → 1.70pp
  - (2bar×3) × minor = 20× → 1.12pp
  - 等等
- 这些 combo 的概率 = (R1 sym × R2 sym × R3 sym 边际) 都是 ~0.05-0.09% 量级
- 砍 R1+R3 bar 砍 ge1_5（pay_id 7 any-bar mixed）✓ **同时砍** (bar×3 × booster) 这条 20-100 主路径 ✗

主 session preliminary 测试 6 个 variant 都没法在 RTP=95 / hit 14-16 同时让 ge20-100 ≥ 26.5。**最接近的变种** (α 系列) 落在：
- RTP 91-99% / hit 14-16% / ge1_5 11-14pp / ge20-100 13-15pp（**没涨甚至轻微跌**）
- 多出来的 10pp 主要落 **ge10_20 (+5-7pp) 和 ge100+ (+5-7pp)**

→ **Designer 任务**：独立 verify 这个 finding，或找出更好的 lever（可能我没试到）。如果 finding 成立 → 起 §2 真理顺位 escalation：让 user 在以下选项里选/amend：
1. 放宽 ge20-100 目标为 directional（接受落 ge10_20 + ge100+）
2. 接受 BOOSTER-HIER 倒序违反（user 已 hint "mini → minor/major"，本就要倒序）作为 trade
3. 改 paytable —— **forbidden** per §1.1
4. 推迟 ge20-100 目标到 mode 2/5 lucky 改动（这里只做 hit + ge1_5）

## 3. 输出契约

Designer (D) → `design_v0.md` + `targets_v0/M37_mode1.target.json` + 给 V 的 verify band updates
Critic (X) → `mode_1_pretune_critique_v0.md`
Verifier (V) → 修订 `slot_designer/scripts/verify_m37_design.py` mode 1 部分 (HIT band, 加 BUCKET-GE1_5 band)
主 session → tune mode 1 only (其他 mode weights 不动 / target.json 锁)
Analyst (A) → empirical sub-gate 后 `empirical_v0_mode1_iter1.md`
Critic (X) → `final_critique_v0.md`
主 session → commit + machines_virtual.json md5 refresh

## 4. 跨 mode 不变量保留

- MODE7-LOCK: m7 R2 booster marginal ≈ m1 (现在是)。改 mode 1 R2 booster → m7 也需同步改才保持 lock。Designer 决策：
  - 选项 a: m7 R2 跟着 m1 改（保 MODE7-LOCK）→ m7 重 tune 也要跑
  - 选项 b: 改 MODE7-LOCK 定义放宽容差 → user escalation
- MODE5-BASE-LOCK: m2/m5 base byte-eq，不动 m2/m5 → 不冲突
- 所有 cross-mode invariants（RTP-MONOTONIC / HIT-MONOTONIC / TOP-JACKPOT-ESCALATION）需保留

**User 提示**："小改，先改 mode 1" — 暗示 mode 7 可能也需同步改但 user 没明说。Designer Stage 4 应在 design_v0.md 明确写出 m7 跟改 vs 接受 MODE7-LOCK 漂移的 trade-off，给 user 拍板。

## 5. 路径

```
session_artifacts/M37/
├── 00_SESSION_BRIEF.md             ← 本文件
├── user_brief.md                   ← user 原话 + §1.2 vocabulary annotation
├── 01b_baseline_analytic.txt       ← 主 session dump (engine analytic_profile 全部表)
├── feasibility_v0_notes.md         ← 主 session 跑过的 variant evidence
├── design_v0.md                    ← Designer 输出
├── targets_v0/M37_mode1.target.json
├── mode_1_pretune_critique_v0.md   ← Critic 输出 (Stage 4 X)
├── verify_run_v0_iter*.txt         ← Verifier 输出
├── empirical_v0_mode1_iter*.md     ← Analyst 输出
└── final_critique_v0.md            ← Critic 最终
```
