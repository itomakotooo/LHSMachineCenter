# M15 数值重新设计 — Session Brief

> **本 session 任务**：从零重新设计 M15 (Top Dollar Feature Play) 4-mode 数值，按 [`slot_designer/ONBOARDING_PROCESS.md`](../../slot_designer/ONBOARDING_PROCESS.md) 6-agent 11-stage 流程跑通 ship-ready。
>
> **已删的旧设计文档不可作为 input**（DESIGN.md / MODE_DESIGN.md / NOTES.md / target.json / 数值断言 test 已在 Phase 0a 删除；从 git history 翻出来也算 contamination）。
>
> **真理顺位** (per ONBOARDING_PROCESS.md §2)：
> archetype + 真 rawdata > universal philosophy > user brief > machine-private docs

---

## §1 已完成（不要重做）

| Stage | 已完成内容 | 状态 |
|---|---|---|
| **Stage 2 Engine Impl** | `slot_designer/machines/M15/spec.json` paytable 结构（10 pay_id 含 666 scatter_trigger） | ✓ verified at refactor merge `2ae5a7d` |
| Stage 2 续 | `slot_designer/machines/M15/reel_strips.json` (36 stops × 3 reels, blank-alternation, topdollar 仅 R3) | ✓ |
| Stage 2 续 | `slot_designer/machines/M15/plugins/{__init__.py, plugin.py, feature.py}` 实现 `FeaturePlugin` Protocol（trigger_pay_id=666 + simulate_session + emit_extra_rounds + classify_round → "TopDollar" / "TopDollarSelector" / "Normal"） | ✓ Phase C |
| Stage 2 schema check | virtual chunk 跟生产 `M15$TopDollarSelector$0$` rawdata schema 字节级对齐（roundResult / analysisResult 双层 JSON encode / TotalWin/FeatureWin/SummaryWin / 含 ST=14 reveals + ST=15 end markers） | ✓ Phase C+E 2af08b9/764ef89 |
| Stage 3 Bootstrap | v7 历史 weights 还在 `weights/mode_{1,2,5,7}/weights.json`（base RTP 43.15pp / hit 19.31% / trigger 1.127% / feature EV 46×）—— **作 analytic baseline 参考，不当设计真理** | ✓ retained as fixture |

→ Stage 0 / 1a / 1d / 2 / 3 主要是 confirm-existing；Stage 1b / 1c / 4 / 5 / 6 / 7 / 8 / 9 / 10 走完整流程。

---

## §2 流程裁剪 — 哪些 stage 满做 / 跳

| Stage | 处理 |
|---|---|
| 0 Setup | **满做**：读 ARCHITECTURE / PHILOSOPHY / WORKFLOW / ONBOARDING_PROCESS；建 `session_artifacts/M15/`（已建）；读 `user_brief.md`（user 写） |
| 1a Data Acquisition | **满做**：A 确认 `cache/chunks/M15$TopDollarSelector$0$/` 已有上游 rawdata；不在则上游拉 |
| 1b Production Baseline | **满做**：A 跑 fresh_slotlab analyzer 拿真生产 M15 的 baseline (RTP / hit / bucket / per-pay_id / family share) |
| 1c Mechanism Inference | **跳**：M15 paytable + rules 已知（spec.json 已写，跟生产 schema 字节对齐过）|
| 1d Archetype Research | **满做**：R 重跑 WebSearch — Top Dollar / Double Top Dollar 当前公开 PAR sheet / KnowYourSlots / SlotsMate / Wizard / 论坛。**不靠 memory 笔记替代** |
| 2 Engine Impl | **跳**（已完成；若 1d 发现新机制差异再回头补）|
| 3 Bootstrap Weights | **简化**：v7 weights 当 analytic baseline；user 可选择保留 / 全弃。Designer 在 Stage 4 决定 |
| 4 Design Narrative | **满做**：D 综合 (R archetype) × (A 上游 baseline) × (user_brief) × (philosophy) → 全新 DESIGN.md / MODE_DESIGN.md / target files |
| 5 TDD Verify Setup | **满做**：V 写 `machines/M15/verify.py`，从 D 的 design intent 派生红线，不抄已删的旧 verify_m15_design.py |
| 6 Per-Mode Tune Loop | **满做**：mode 1 → 7 → 2 → 5 顺序，每 mode 5-iter cap + empirical sub-gate + X adversarial sub-review |
| 7 Cross-Mode | **满做** |
| 8 Empirical Validation | **满做** |
| 9 Adversarial Gate | **满做** |
| 10 Commit & Merge | **满做**：commit + push + 更新 ONBOARDING_PROCESS.md §11 进度表（M15 状态从 pending → 完成 + commit SHA） |

---

## §3 user_brief.md 占位（user 写，Designer 必读）

落到 `session_artifacts/M15/user_brief.md`，建议覆盖：

```
# M15 user brief

## 玩家叙事 / 机台 character
- M15 是 ____ 路线（boom-bust / cherry-grindy / dream-jackpot / mid-heavy / etc.）
- 期望玩家坐 30 分钟感受到 ____

## RTP / mode 数值约束
- mode 1 total RTP = 95% ±1pp 严格（universal §C）
- mode 1 base hit rate 期望 ≈ ____ % (留空给 Designer 派生 from archetype)
- mode 1 base : feature 比例期望 ____
- 跨 mode hit/avg/trigger 关系倾向 ____

## bucket / 玩家手感
- low (1-10×) bucket 占 ____ % RTP
- mid (10-50×) bucket 占 ____
- high (50-500×) bucket 占 ____
- top (500+) bucket 占 ____
- 任一 mode 顶奖 cadence 期望 ____

## 不变量严格度
- mode 7 vs mode 1：____ (universal §4 cut-mode 砍小奖 freq 不动大奖；这条严格 / 让步)
- mode 5 vs mode 2：____ (universal §9 / §7 顶奖阶梯；这条严格 / 让步)

## 用户主动选边
- 1000+ peak 是不是趋近 0？(prev v7 选 "趋近 0"，user 是否还坚持)
- cherry-1 1× pay 主导 base 是 archetype 必然，接受 / 改 paytable 去掉

## archetype 选择
- 倾向 Top Dollar 1-line ($1 denom 87-92% RTP) / Double Top Dollar 9-line
  (96.24% RTP, 4000× max) / 还是混合
- 哪些 archetype 元素优先保留：bonus reveal drama / cherry-grindy base /
  ×2 multiplier feature / etc.
```

**user 没填的字段** Designer 必从 (R archetype + philosophy + 数学下限) 派生，并在 DESIGN.md 注明"derived from archetype because user_brief 未指定"。

---

## §4 上轮 M15 设计失败的反例（避免重蹈）

per Phase 0a commit message + memory：

1. **MODE_DESIGN.md 跟 shipped weights drift** — 旧 doc 写 mode 1 hit 13.17%、per-hit avg 3.26×，shipped 实际 19.31% / 2.23×。**因为 Claude 写 doc 时没拿真数字 cross-check**。新 session：D 的每个数字必跑 analytic / sample 印证。

2. **mode 7 设计走错路** — 旧 MODE_DESIGN.md 写 "per-hit avg ↓"，跟 PHILOSOPHY §4 cut-mode "砍小奖 freq" 直接矛盾。**因为 Claude 拿 sister machine 的 cut 路径硬套**。新 session：D 必须 cite §4 条款决定 mode 7 走 freq-cut（小奖 hit ↓，中/大/顶奖 hit 不动），不是 per-hit-avg-shrink。

3. **MODE_DESIGN.md 被当 "设计真理"读** — D 写完 doc 后下一轮 Claude 把它当 input；2 轮分析全跑歪。新 session：machine-private docs 是 layer 4 派生层，永远不能反推回 layer 1-3。

4. **verify 96 类全 GREEN 但漏 hit_rate / bucket-shape / reel-asymmetry** — 旧 verify_m15_design.py 红线类别太窄。**因为 Claude 写 verify 时只 cover 自己想到的**。新 session：V 在 Stage 5 必注入 bug 测每条红线真能抓；红线条款必逐条 cite PHILOSOPHY §。

5. **cherry-grindy 被误判为 bug** — base RTP 32% 来自 cherry-1 是 archetype 必然（任意 reel cherry → 1× pay）；旧分析当成"设计偏差要修"，差点强行调 paytable。新 session：archetype 优先；任何想偏离 archetype 的决策必走 user 拍板。

6. **mode 5 v7 砍 1000+ 是 user-pinned**（"1000+ 趋近 0"）—— archetype default 会给 1000+ peak（Double Top Dollar 4000× max）。这条 deviation 必须落 user_brief.md，由 user 显式确认是否还坚持。

---

## §5 第一步指令（主 session 启动 prompt）

把下面这段塞进新 session 第一句：

```
本 session 任务：M15 数值重新设计验证迭代。

必读：
  slot_designer/ONBOARDING_PROCESS.md   (团队 + 流程总规范)
  slot_designer/ARCHITECTURE.md         (代码工程规范)
  slot_designer/DESIGN_PHILOSOPHY.md    (设计 first principles)
  slot_designer/WORKFLOW.md             (commit 前 review 流程)
  session_artifacts/M15/00_SESSION_BRIEF.md  (本机台 session-specific 裁剪)
  session_artifacts/M15/user_brief.md   (user 倾向性输入)

按 ONBOARDING_PROCESS.md §5 11-stage 流程走，6 个 agent 编制
(R/A/I/D/V/X)，但本 session 按 00_SESSION_BRIEF §2 裁剪
(Stage 1c / 2 跳；Stage 0 / 1a / 1b / 1d / 3 简化；其余满做)。

第一动作：
1. 读上面 5 份必读文档
2. 主 session 跑 analytic dump 看当前 v7 weights baseline 数字
   (作参考，不当设计真理)
3. 检查 cache/chunks/M15$TopDollarSelector$0$/ 是否有上游 rawdata
4. 起 Agent A 跑 Stage 1a (data acquisition) + Stage 1b (production
   baseline)；同时起 Agent R 跑 Stage 1d (archetype WebSearch)
5. 跟 user 确认 user_brief.md 内容（00_SESSION_BRIEF §3 占位填）
6. 起 Agent D 进 Stage 4 写 DESIGN.md / MODE_DESIGN.md / target files
7. 后续按 ONBOARDING_PROCESS.md 流程跑

每个 agent 起的时候 prompt 里贴 ONBOARDING_PROCESS.md §4 对应行作为
role contract；artifact 路径用文件传不在对话里贴大段内容。

红线（再次强调）：
- 不读已删的旧 MODE_DESIGN.md / NOTES.md (从 git history 翻出来也算
  contamination)
- 不抄 sister machine target 数字
- D 的每个数字必 cite (R archetype URL / A 数据 / brief 项 / § 条款)
- V 红线必逐条 cite PHILOSOPHY §
- 每 mode 4-lock (V analytic + A empirical + A consistency + X review)
  齐开才算锁定
- 5-iter cap on inner loop；超出 escalate user
```

---

## §6 当前 git baseline

session 启动时主仓库应在：

```
collab/dev @ 86b8310  Merge branch 'claude/happy-bell-6f0192' (refactor)
                     ↑ 含 ONBOARDING_PROCESS.md
```

新 session 工作 fork 到新分支 (e.g. `feat/m15-redesign-2026-XX-XX`)，
最后 merge 回 collab/dev。
