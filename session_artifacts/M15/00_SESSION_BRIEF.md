# M15 数值重新设计 — Session Brief

> **本 session 任务**：M15 (Top Dollar Feature Play) 4-mode 数值**优化迭代**，按 [`slot_designer/ONBOARDING_PROCESS.md`](../../slot_designer/ONBOARDING_PROCESS.md) 6-agent 11-stage 流程跑通 ship-ready。
>
> **方向**：顺着 [`v7_baseline_quickref.md`](v7_baseline_quickref.md) 数据做 optimization，**不是 greenfield 重建**。v7 结构 + paytable + plugin 实现是健康基础（archetype-faithful），优化点是 user brief 的 6 项（hit / CV / split / count_x=1 / 千倍避免 / jackpot 偏低）。
>
> **本 session 同时是 ONBOARDING_PROCESS.md 的首个 use case**——任何 process 不顺手 / 文档不清楚的地方都是 ONBOARDING_PROCESS 改进的 input。新 session 的失败模式都要回写进 ONBOARDING_PROCESS（不是只改 M15）。
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

## §3 user_brief — 已确认 6 条核心诉求

落到 `session_artifacts/M15/user_brief.md`：

```
# M15 user brief (v1, 2026-XX-XX 确认)

## mode 1 核心诉求（其他 mode 衍生）

1. 命中率 (hit_rate) ∈ [15%, 18%]
   当前 v7：19.31% (超 1.31pp，需向下优化)

2. 波动性
   - normal spin 部分：低波动 (CV ∈ [3, 5])
     当前 v7 base CV：5.77 (中-高，需向下优化)
   - feature 部分：中波动 (conditional CV ∈ [1, 2])
     当前 v7 feature CV：0.74 (低，需向上优化)

3. base : feature RTP 比例 = 50 : 50
   当前 v7：45.4 : 54.6 (feature 超 4.6pp)

4. feature 体验：count_x = 1 (单牌 reveal) 概率 ≤ 2%
   当前 v7：5%

5. 避免 1000× bet 以上奖（跨所有 mode）
   当前 v7：mode 1 P(R≥1000/spin) = 1/8.3M ≈ 0 ✓ 已达成
   (mode 5 也维持避免：1/3.6M ✓)

6. jackpot symbol 击中率正常偏低（universal across mode 1/2/5/7）
   当前 v7：mode 1 jackpot R1 0.08% / R2 0.53% / R3 0.14% ✓ 已偏低
   保持任一 reel marginal ≤ 0.6%

## 衍生关系（universal §C/D 强制）

- mode 7 = mode 1 砍小奖 freq (per philosophy §4)，feature_params 字节
  级 = mode 1
- mode 2 = mode 1 lucky 派生，hit ×1.5-2 (不是 ×3)
- mode 5 base = mode 2 base 字节级一致；feature 加强 (EV 升、count_y
  / x_value_weights 调；不可破"避免 1000+"红线)

## 默认决策（Designer 不需问 user）

- archetype: Top Dollar 1-line ($1 denom ~92% RTP) + Double Top Dollar
  ×2 multiplier 元素混合 (跟 v7 保持)
- cherry-1 1× anywhere 是 archetype 必然，**接受**（不动 paytable）
- accept threshold: 当前 v7 flat 40 保持（不恢复 graduated）
- §7 顶奖阶梯例外：M15 走"密集 mid-high 替代稀有 top"路线，DESIGN.md
  写明 deviation；不动 universal philosophy
- 3-wild 200× cadence: 保持 v7 (~1/60k)，不主动拉到 1/15-30k

## 留空给 Designer 派生 (cite archetype URL or §条款)

- bucket distribution per mode (low/mid/high/top RTP %)
- per-pay_id frequency band
- family RTP share band
- trigger rate (受 brief #3 RTP 50:50 + Designer 选 feature EV 影响)
- per-hit avg win
```

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

把下面这段**完整** copy-paste 进新 session 第一句：

```
本 session 任务：M15 (Top Dollar Feature Play) 4-mode 数值优化迭代。
方向：顺 v7 baseline 数据按 user brief 6 项做 optimization，不是
greenfield 重建。本 session 同时是 ONBOARDING_PROCESS.md 的首个 use
case — process 不顺手 / 文档不清楚都要回写改 process。

------------------------------------------------------------
# 必读（按顺序）

1. slot_designer/ONBOARDING_PROCESS.md    (6-agent + 11-stage 总规范)
2. slot_designer/ARCHITECTURE.md          (代码工程规范)
3. slot_designer/DESIGN_PHILOSOPHY.md     (设计 first principles 15 条)
4. slot_designer/WORKFLOW.md              (commit 前 review 流程)
5. session_artifacts/M15/00_SESSION_BRIEF.md   (本机台 stage 裁剪)
6. session_artifacts/M15/user_brief.md    (user 6 项核心诉求 + 衍生关系)
7. session_artifacts/M15/v7_baseline_quickref.md   (起点参考, 6-item 简表)

------------------------------------------------------------
# Stage 裁剪 (per 00_SESSION_BRIEF.md §2)

Stage 0  Setup           满做 (读 1-7)
Stage 1a Data Acq.       满做 (A 确认 cache/chunks/M15$TopDollarSelector$0$/)
Stage 1b Prod Baseline   **满做 12 sections** (per ONBOARDING §5.1b
                          表) — 不是 v7 quickref 那种 6-item，必跑
                          完整 RTP+bucket+pay_id+family+per-reel+
                          asymmetry+PWDF+blank-flank+feature-session+
                          top-prize+cross-mode+schema-fingerprint
Stage 1c Mech. Inf.      跳 (M15 paytable 已知)
Stage 1d Archetype       满做 (R 跑 fresh WebSearch Top Dollar 业界数据)
Stage 2  Engine Impl     跳 (FeaturePlugin 已实现，schema 已对齐)
Stage 3  Bootstrap       简化 (v7 weights 当 optimization 起点)
Stage 4  Design Narr.    满做 (D 写 DESIGN.md / MODE_DESIGN.md / target;
                          每数字 cite archetype URL or § 条款;
                          target 朝 user brief 6 项 optimize)
Stage 5  TDD Verify      满做 (V 写 machines/M15/verify.py + 注入 bug 测)
Stage 6  Per-Mode Tune   满做 (mode 1 → 7 → 2 → 5 顺序; 每 mode
                          5-iter cap; 4-lock; pareto-trap 警惕)
Stage 7  Cross-Mode      满做
Stage 8  Empirical Val.  满做 (虚拟 console 4 mode × 50k spin;
                          analytic vs sim ±2σ)
Stage 9  Adv. Gate       满做
Stage 10 Commit & Merge  满做 (新分支 feat/m15-redesign-v8 fork from
                          collab/dev; merge 回 collab/dev; 更新
                          ONBOARDING_PROCESS.md §11 进度表)

------------------------------------------------------------
# 第一动作（主 session）

1. 完整读完上面 7 份文档（不要跳读、不要总结性扫一眼）
2. 主 session 跑当前 v7 analytic dump 验证 quickref 数字仍准确
3. 起 Agent A 在 Stage 1b 先写 baseline_dump 脚本（仿照 ONBOARDING
   §5.1b 12 sections），跑出 session_artifacts/M15/01b_baseline_report.md
4. 同时起 Agent R 跑 Stage 1d 拿 Top Dollar archetype WebSearch
   → 01d_research.md
5. A 跟 R 各自 done 后，起 Agent D 进 Stage 4 起草 design 文档 +
   target file
6. Agent X 进 pre-tune adversarial review（Stage 4 末）
7. Agent V 进 Stage 5 写 verify.py 红线 + 注入 bug 测
8. Stage 6 内循环（per mode 5-iter cap）
9. ...

每个 agent 通过 Agent tool 起 general-purpose subagent。每次起 agent 时
prompt 里贴 ONBOARDING_PROCESS.md §4 该 agent 那一行作 role contract +
说明本次 deliverable 文件路径。**主 session 不在对话贴大段内容**，给
agent 文件路径让它自己 Read。

------------------------------------------------------------
# 红线（防 Claude-self-loop）

- 不读已删的旧 MODE_DESIGN.md / NOTES.md（从 git history 翻出也算
  contamination；它们漂过 archetype + philosophy）
- 不抄 sister machine target 数字（M1 / M37 / M279 paytable 结构不同）
- D 的每个数字必 cite (R archetype URL / A 数据 / brief 项 / § 条款)
  否则不进 design 文档
- V 红线必逐条 cite PHILOSOPHY §; 不能 Claude 自定 cap
- 每 mode 4-lock 齐开 (V analytic + A empirical per mode + A
  analytic-vs-empirical 一致 + X adversarial sub-review)
- inner loop 5-iter cap; 超出 escalate user
- pareto trap: 连续 3 iter 同 RED → 回 Stage 4 改 design intent，
  不死 tune

------------------------------------------------------------
# 兼任 process 改进

本 session 任何环节遇到 ONBOARDING_PROCESS.md 写不清 / 漏 / 流程
不顺手 → 当场修 ONBOARDING_PROCESS.md（同 commit 落地），不是只
解决 M15 那一个 case。预期发现 5-15 处可改进点（首个 use case 必
然有）。

------------------------------------------------------------
# 完成标志

✓ 4 mode 全 verify GREEN (含 cross-mode invariants)
✓ 4 mode analytic vs Monte Carlo 在 ±2σ
✓ user brief 6 项全部兑现（hit ∈ [15,18] / base CV ∈ [3,5] /
  feature CV ∈ [1,2] / 50:50 split ±5pp / count_x=1 ≤ 2% /
  P(R≥1000) 全 mode ≤ 1e-5 / jackpot ≤ 0.6%/reel）
✓ ONBOARDING_PROCESS.md §11 进度表 M15 标完成 + commit SHA
✓ commit 通过 .claude/hooks/verify-commit-msg.py 4 段格式
✓ push origin/collab/dev 成功
```

**注**：以上 prompt 设计为 fresh context 自完整，不需要旧 session 的对话
历史。新 session 从 0 启动直接走流程。

---

## §6 当前 git baseline

session 启动时主仓库应在：

```
collab/dev @ 86b8310  Merge branch 'claude/happy-bell-6f0192' (refactor)
                     ↑ 含 ONBOARDING_PROCESS.md
```

新 session 工作 fork 到新分支 (e.g. `feat/m15-redesign-2026-XX-XX`)，
最后 merge 回 collab/dev。
