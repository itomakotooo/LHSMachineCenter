# slot_designer — 新机台 onboarding 流程规范

> **范围**：把一台新机台从 rawdata 起步、走通 6-agent team 协作、经 11-stage 工作流，最后 ship-ready 落 `collab/dev` 的完整流程。
>
> **跟其他文档边界**：
> - [`ARCHITECTURE.md`](ARCHITECTURE.md) 写**代码长成什么样**（文件布局 / Plugin 协议 / per-machine md5 / 命名禁区 / 不变量）
> - [`DESIGN_PHILOSOPHY.md`](DESIGN_PHILOSOPHY.md) 写**设计的 first principles**（倒金字塔 / brand visibility / pareto trap / reel asymmetry / PWDF / 等 15 条）
> - [`WORKFLOW.md`](WORKFLOW.md) 写**每次 commit 前的 self-review 5 步**
> - **本文件**写**谁做、怎么做、怎么收敛**（团队分工 + stage 工作流 + 收敛 / stop 条件）

---

## §1 输入契约

每台新机台 onboarding 前，user 提供：

| 输入 | 必需性 | 说明 |
|---|---|---|
| **A. rawdata** | **必有** | 上游生产 chunk JSON，或 user 直接 ship 一包 chunk。所有 rules / paytable / 玩家行为统计**唯一权威来源** |
| **B. 规则文档 + paytable** | 可选 | 没给就 Analyst 从 rawdata 反推 (Stage 1c)；给了也只是辅助，跟 rawdata 冲突时 rawdata 赢 |
| **C. 用户倾向性 brief** | 可选但很关键 | mode 1 hit 期望、bucket shape 倾向、机台 character、不变量严格度、不想要的体验。落到 `session_artifacts/<M>/user_brief.md`，Designer 必读。**首次 use case 强制要求 SESSION_BRIEF 模板里 user_brief.md 这个文件实际存在**（M15 process_improvement #1）|
| **D. archetype hint** | 可选 | user 指定原型机（"这台是 Buffalo / Top Dollar / Wheel of Fortune 路线"）；没给就 Researcher WebSearch 推断 |

### §1.1 Universal invariants (cross-machine, never violate)

- **paytable 永远不改** (slot_designer/machines/<M>/spec.json `pays` block byte-identical from Stage 1c onward; cross-machine universal rule per M15 process_improvement #36, established 2026-05-11). Reel strips / weights / plugins **可改**；只锁 paytable structure.
- **rawdata 是唯一权威源**：本台机器的真实玩家行为 > 业界平均（Stage 1c paytable inference 也走 rawdata 不走 manufacturer specs）。
- **跨机台不互相 import**：machines/<M>/ 不 import 其他 machines.<other>.* （ARCHITECTURE.md §8 不变量 #2）。

### §1.2 User brief vocabulary

user brief 区分两种约束类型 — Agent 必须主动澄清：

- **数值约束 (precise red line, with units)** — 例 "命中率 ∈ [15, 18]%" → verify.py [TAG] RED line
- **感性描述 (qualitative direction)** — 例 "base 低波动 / feature 中波动" → verify.py 走 INFORMATIONAL metric，不当 RED

当 user 写数字段（如 "[3, 5]"）但意图模糊，**Stage 4 design review 时显式问 user**："这是 red line 还是 directional descriptor?" 默认按 precise；user 回 "不需要控制精确" 即转 informational + 更新 user_brief.md amendment 段。(M15 process_improvement #37)

---

## §2 真理顺位

```
┌─────────────────────────────────────────────────────────┐
│  layer 1  真原型 PAR sheet  +  本机台 真 rawdata       │ ← 最高
├─────────────────────────────────────────────────────────┤
│  layer 2  universal philosophy  (DESIGN_PHILOSOPHY.md)  │
├─────────────────────────────────────────────────────────┤
│  layer 3  user brief 倾向性                              │
├─────────────────────────────────────────────────────────┤
│  layer 4  machine-private docs (machines/<M>/DESIGN.md  │
│            + MODE_DESIGN.md + verify.py + target.json)  │ ← 派生层
└─────────────────────────────────────────────────────────┘
```

冲突解决：
- **layer 1 内部**：archetype baseline ≠ 本机台 rawdata 时，本机台 rawdata 赢（"this machine 真行为 > industry 平均"）
- **layer 1 vs layer 2**：哲学赢；layer 1 数据用于校准 layer 2 容差
- **layer 2 vs layer 3**：哲学赢；user brief 妥协部分明文记 DESIGN.md
- **layer 1+2 vs layer 4**：machine-private 不能 override 上层；冲突时上层赢、layer 4 重写
- **paytable 数学下限 vs 任何 layer**：paytable 结构赢（不能违反 math）。**paytable 永久不可改**（§1.1 universal rule） → 冲突时调 weights/strips/plugin 兼容，或 escalate user 接受 deviation；**不再走"改 paytable"路径**。

### §2.1 Designer 禁读 list (contamination firewall)

Designer (Stage 4) 不能反向读 layer 4 派生层当输入 — 容易拿历史 narrative 当 ground truth 自我循环：

| 禁读 | 原因 | M15 record |
|---|---|---|
| 已删 / git-history 中 `machines/<M>/DESIGN.md` / `MODE_DESIGN.md` / `NOTES.md` | layer 4 派生层 | M15 Phase 0a 已删 |
| `machines/<M>/spec.json` 里的 `_design` / `_notes` / `_weights_rationale` / `_default_weights_note` 等 `_*` 段 | stale narrative blocks | M15 process_improvement #2 |
| `machines/<M>/weights/mode_*/weights.json` 里的 `_tuned_summary` / `feature_params._analytic` | 历史 measurement snapshot | M15 process_improvement #3 |
| sister machine targets / DESIGN.md（不同 paytable 结构） | cross-machine contamination | — |

spec.json **mechanism 段** (`pays` / `symbols` / `evaluation_order` / `spin_types`) 是 authoritative — 这些可读。`_*` 前缀的 narrative blocks 必跳过。

---

## §3 输出契约

ship-ready 必须产出：

1. **虚拟机实现**
   - `machines/<M>/spec.json` (paytable + rules DSL)
   - `machines/<M>/reel_strips.json` (reel symbol 布局)
   - `machines/<M>/weights/mode_<N>/weights.json` × 4 modes
   - `machines/<M>/plugins/` (feature 机台才需要：FeaturePlugin Protocol 或 custom engine adapter)
   - `machines/<M>/__init__.py` (空)
   - 框架扩展 (若有完全新机制需要 `core/` 加 Protocol)

2. **数值设计**
   - `machines/<M>/DESIGN.md` (archetype 出处 + 4-mode 玩家叙事 + user_brief 兑现)
   - `machines/<M>/MODE_DESIGN.md` (per-mode 数值意图 + cross-mode 关系)
   - `core/tuner/targets/<M>_mode<N>_*.target.json` (mode 1 + 2 必填; 5/7 派生可省)

3. **验证基础设施**
   - `machines/<M>/verify.py` (machine-specific 红线 — 引用 `DESIGN_PHILOSOPHY.md` 各 §)

4. **必备测试** (per ARCHITECTURE.md §5.4)
   - `tests/machines/test_<M>_engine.py`
   - `tests/machines/test_<M>_strips_invariants.py`
   - `tests/machines/test_<M>_plugin_protocol.py` (feature 机台才有)
   - `tests/machines/test_<M>_md5_isolation.py`

5. **registry**
   - `slot_designer/configs/machines_virtual.json` 加 entry
   - md5 refresh 完成

6. **end-to-end 通过**
   - 本机台 verify.py 全 GREEN (含 cross-mode invariants)
   - 4 mode analytic vs Monte Carlo 在 ±2σ
   - 跟生产 rawdata schema 字节级对齐 (chunk envelope + analysisResult format)
   - 跨 fleet `tests/core/` 全 GREEN (新机台不破坏 fleet 不变量)

---

## §4 Agent Team

6 个独立 fresh-context 子 agent，每个 single-responsibility：

| Agent | 角色 | 唯一职责 | 工具面 | 不做 |
|---|---|---|---|---|
| **R** Researcher | 业界研究员 | WebSearch archetype（PAR sheet / KnowYourSlots / SlotsMate / Wizard / 论坛 / 学术）+ 文献查阅 | WebSearch / WebFetch | 不碰 rawdata；不写 spec；不出设计意图 |
| **A** Analyst | 数据 + 报告分析师 | (1) 拉上游 rawdata 进 cache (或确认已有);  (2) 跑 `fresh_slotlab/player_impact_analyzer.py --from-cache` 出 baseline report;  (3) 从 rawdata field-analyze 反推 rules + paytable + SpinType + feature 字段 (若 user 没给);  (4) 每次需要 empirical gate 时跑虚拟机产 chunks 过同一 analyzer，diff 虚拟 sim_report vs Stage 1b baseline_report | 子进程 + Python 数据分析 + JSON | 不调 weights；不出设计意图；不写 verify 红线 |
| **I** Implementer | 引擎实现 | 写 `spec.json`、`reel_strips.json`(initial)、Plugin (若需要)、机制正确性测试 (sim output vs 生产 rawdata 字节比对) | Edit / pytest | 不出设计意图；不调 weights；不写 verify 红线 |
| **D** Designer | 数值设计师 | 综合 (R archetype) × (A baseline) × (user brief) × (philosophy) → DESIGN.md / MODE_DESIGN.md / target.json。每个数字 cite 来源 | Read / Write | 不写 spec 或 plugin；不调 tune；不写 verify (但 verify 的红线由它的 design intent 派生) |
| **V** Verifier | 数值校验员 | 写 + 跑 `machines/<M>/verify.py` (analytic 路径) → categorized RED/GREEN/WARN; 每次 tune 完跑 | Edit / Bash | 不调 weights；不改 design；不做 commit 决策；不跑 sampling (那是 A 的活) |
| **X** Critic | 魔鬼律师 | 每个里程碑扮 user stress-test 5 反问；写 commit message 的 `## Self-critique` 段 | 读所有 artifact | 不实现任何代码 |

主 session 是**协调员** — 决定该起哪个 agent / 跑 `tune.py` / 跑 `git` / 文件操作。**不做 design / verify / review 决策本身**——决策都在 agent 里。

### §4.1 R / A 边界

```
R 答："业界 / 学术圈对这种机台说什么"  → outside knowledge
A 答："本台机自己的真 rawdata 说什么"   → inside data

R fail mode: 找不到原型 / 业界没数据
A fail mode: rawdata 反推错 / analyzer 跑挂

合并 = 两种 fail mode 串联，单 agent 顾不过来
```

### §4.2 V / A 边界 — 双轨验证

```
                ┌── analytic 路径（V）：
                │   core/devtools/analytic_rtp.analytic_profile()
                │   1 秒出 RTP / hit / bucket / per-pay_id
                │   假设 evaluator + sampler 实现正确
                │   → 实现层 bug 抓不到
   "数值对了"
                │   empirical 路径（A）：
                └── 起虚拟 console 采 N 万 spin → analyzer report
                    几分钟出全套（含 SpinType / feature breakdown / streaks /
                    bankruptcy / session-level）
                    ground truth，能抓 implementation bug
```

每 mode 锁定必须**两路都过**：

```
analytic GREEN     →   weights 算出来对
empirical 在 ±2σ   →   实际采样跑出来对
analytic vs empirical 一致 → engine + emitter 实现没 bug
```

不能用单路替代另一路。

---

## §5 11-Stage 工作流

```
Stage  Owner     Action
───────────────────────────────────────────────────────────────────────────
0      主 session 读 ARCHITECTURE / PHILOSOPHY / WORKFLOW；建 machines/<M>/
                  + session_artifacts/<M>/ 目录；读 user_brief.md (若有)

1a     A         Data Acquisition：确保 cache/chunks/<M>/mode_<N>/ 有
                  rawdata（不在则上游拉）；schema fingerprint + chunk
                  count baseline → 01a_data_inventory.md

1b     A         Production Baseline：跑 fresh_slotlab analyzer
                  --from-cache + 自写 analytic profile dump，**完整
                  12 sections** (见 §5.1b detail) → 01b_baseline_report.md

1c     A         Mechanism Inference (若 user 没给 rules/paytable)：
                  rawdata 反推 (pay_id ↔ symbol 映射 / wild 行为 /
                  cherry priority / scatter / SpinType 含义)
                  → 01c_field_analysis.md

1d     R         Archetype Research：基于 1c 反推机制 + paytable 推断
                  archetype，跑 WebSearch → 01d_research.md
                  (含来源 URL 跟 baseline 数字对照)

2      I         Engine Implementation：写 spec.json + reel_strips.json
                  (initial) + plugin (若新机制) + 机制正确性 tests
                  → 跑 sim chunk vs 生产 rawdata 字节级对齐 check

3      I + A     Bootstrap Weights：从生产 rawdata 反推 initial weights
                  (求每 reel 每 symbol 的边际频率 → fit 权重)；
                  V 跑 analytic_profile 看 baseline RTP / hit (做 design
                  起点参考)

4      D         Design Narrative：综合 R / A / brief / philosophy
                  写 DESIGN.md + MODE_DESIGN.md + target files
                  → design_v0.md + targets_v0/
                  **必含**：§14 全 symbol 排布 audit（per PHILOSOPHY §14.5；
                  每条 reel 每 symbol 都 audit，不只 bars/top）+ §15 PWDF
                  mechanism 选择（per PHILOSOPHY §15.9；物理 reel 强制
                  mechanism B redistribute，virtual reel 走 mechanism C）。
                  违反任一直接修，不能"标 informational 跳过"。

       X         Pre-Tune Review (一次)：
                  - 玩家手感讲得通吗？
                  - 数字 cite 哪个 archetype 数据？
                  - 跨 mode 叙事自洽吗？
                  - §14 audit 全 symbol 覆盖 + 违反点 D 给修复方案?
                  - §15 PWDF active optimization 选了哪个 mechanism + 提
                    升量?
                  → 不通过回 4 改；通过进 5

5      V         TDD Verify Setup：从 design intent 写 verify.py 红线 (不
                  抄旧代码)；跑 baseline RED；注入 bug 测 verify 真能抓
                  → 5 通过条件：故意改坏 weights → 触发对应 RED；revert
                    → 回 baseline RED
                  **必含**：[VISUAL-RHYTHM] 类别（§14.5；具体阈值机台特定）
                  + [PWDF-FLOOR] 类别（§15.9；具体 floor 机台特定）。两者
                  写不全 = Stage 5 不通过。

6      多 agent  Per-Mode Tune Loop (mode 1 → 7 → 2 → 5 顺序)
                  详见 §5.6

7      V         Cross-Mode Integration：跑跨 mode invariants
                  (LUCKY-MONO / MODE7-LOCK / MODE5-BASE-LOCK / mode-pair
                  monotonicity §9 / top-jackpot escalation §7)
                  → RED 锁定哪 1-2 mode 不一致，回 6；GREEN 进 8

8      A + V + X Full Empirical Validation：
                  - 主 session 起虚拟 console + 4 mode 各 ≥ 50k paid spin
                  - A 跑 analyzer 出 sim_report
                  - A diff sim_report vs (Stage 1b baseline) AND
                    (target 数字)
                  - V 跑 analytic vs empirical 一致性 (双路验)
                  - X 看抽样 round 序列：玩家叙事跟实际 chunk 真自洽？
                  → 全条通过进 9；任一不通过定位回相应 stage

9      X         Adversarial Gate：commit 前最后 stress-test 5 反问 →
                  写 final_critique.md；
                  连续 3 次同问拒 → escalate user

10     主 session Commit & Merge：写 commit message (4 必有段过
                  .claude/hooks/verify-commit-msg.py); 推 collab/dev;
                  refresh machines_virtual.json md5; 更新 ARCHITECTURE.md
                  §10 进度表
```

### §5.1b Stage 1b — comprehensive baseline 12 必含 sections

跑 `fresh_slotlab/player_impact_analyzer.py --from-cache` 拿基本 RTP/bucket/hit
不够，A 必须写 / 复用 analytic profile dump 脚本一次产 12 sections（per
mode × 全 mode）：

| § | 必含 | 数据源 | 用途 |
|---|---|---|---|
| 1 | per-mode 总数 | analytic_profile() | RTP / hit_rate / std_return_x / CV / total_prob (sanity) |
| 2 | bucket distribution | analytic_profile()['bucket_rate'] + ['bucket_rtp'] | per bucket rate% + RTP%，11 桶（gt0_lt1 → ge5000）|
| 3 | per pay_id breakdown | analytic_profile()['pay_hits'] + ['pay_rtp'] | "1 in N spins" cadence + per-pay_id RTP 贡献 |
| 4 | family RTP share | pay_id → family 聚合 | wild_pure / high7 / bar / cherry / 等 RTP pp + share% |
| 5 | per-reel marginals | compute_reel_marginal() per reel | 每 symbol 在每 reel 中线 marginal 概率 |
| 6 | reel asymmetry §12 | (5) 派生 | R1 vs R3 (or R5) blank density + top-prize family density 方向 check |
| 7 | window visibility §15 PWDF | per-reel-window enumeration | top symbol any-row visibility + PWDF ratio (mid vs window)|
| 8 | blank-flank §13 | strip layout 字符串扫 | 任 strip 上是否有 X-Blank-X 模式 |
| 9 | feature session bucket | feature plugin's session_dist | per trigger R 落各桶概率 + cadence per paid spin |
| 10 | top-prize escalation §7 | per mode (9) 跨 mode 对比 | mode 1 → 5 顶奖 cadence 阶梯 |
| 11 | cross-mode invariants | 跨 mode 对比 (1)(3)(4) | mode-pair monotonicity / mode 7 cut direction / mode 5 base = mode 2 base bytes |
| 12 | schema fingerprint vs production | compute_schema_fingerprint() vs production chunk | virtual chunk 字段集跟生产 rawdata 字节级对齐 ✓/✗ |

输出格式：单一 markdown 文件 `session_artifacts/<M>/01b_baseline_report.md`，每
section 独立块 + 关键数字 + 哪条 §条款 / archetype baseline 触发。

**为什么必须 12 sections**：缺哪一节都让 Designer 在 Stage 4 决策时盲。比如：
- 缺 §6 reel asymmetry → Designer 不知道 R1/R3 是否需要 enforce
- 缺 §7 PWDF → 不知道 top symbol 视窗 visibility 是 4× (Harrigan-class) 还
  是 73× (extreme clustering)
- 缺 §11 cross-mode invariants → 后续 mode 派生时把 universal §C/D 不变量
  踩了不知道
- 缺 §12 schema fingerprint → 看不出引擎是否真跟生产一致，可能等到
  Stage 8 才暴露 bug

参考 / 模板：早期 commit 含的 `dump_m15_player_experience.py`（已删，git
log 可查）—— 12 section 结构成熟，新 session 第一件事是仿照它写
`session_artifacts/<M>/scripts/baseline_dump.py`，落 `01b_baseline_report.md`。

### §5.6 Per-Mode Inner Loop (Stage 6 细节)

```
对每个 mode 跑下面 loop，最多 5 次 iteration，超出 → escalate user：

iter k = 1..5:

  6.k.a  主 session: tune.py (target 来自 D 的 target file，cost weights
         覆盖 RTP / hit / shape / trigger / family share)

  6.k.b  V: verify.py → categorized RED/GREEN/WARN 报告
         → verify_run_v<n>_iter<k>.txt

  6.k.c  分类处理：

    (i) strict GREEN + warn 都可解释 → 进 6.k.d empirical sub-gate

    (ii) RED 是 STRUCTURAL（paytable 物理上做不到）：
         → V 标 STRUCTURAL；D 写 self-critique 解释；user 拍板
           accept-as-design vs 改 paytable

    (iii) RED 是 TUNABLE：
         → D 决策三选一：
           (a) 调 target file 数字 (cite 新 archetype 数据)
           (b) 调 tune cost weights (哪条红线 priority 上调)
           (c) 改 weights 结构 (PWDF redistribute / family-scale 锁)
         → 回 6.k+1.a

  6.k.d  Empirical sub-gate (analytic GREEN 后):
         - A: 起虚拟 console 单 mode 采 ≥ 20k spin
         - A: analyzer report → empirical_v<n>_mode<N>_iter<k>.md
         - A: 三层 diff:
              ① analytic (V) vs empirical (A) → 一致？(±2σ)
              ② empirical vs target.json → 设计目标达到？
              ③ empirical vs baseline_report (Stage 1b) → 跟原型偏离合理？
         - 全过 → 进 6.k.e
         - 偏离 → 定位:
              · ① fail → engine 实现 bug，回 Stage 2 找 I
              · ② fail → tune 没收敛，回 6.k+1.a
              · ③ fail (跟 baseline 偏离过大) → D review 是否预期，
                   不预期 → 回 4 改 design intent

  6.k.e  X: per-mode adversarial sub-review (5 反问)
         → 通过该 mode 锁定，进下一 mode；不通过回 6.k+1.a
```

### §5.6.1 Per-Mode 4-Lock Convergence

一个 mode 算"通过"必须四锁齐开：

```
✓ V (analytic)                strict GREEN, soft warn 都有书面理由
✓ A (empirical per mode)      sim_RTP / hit / bucket 跟 target 在 ±2σ
✓ A (analytic vs empirical)   两路数字一致 → 证明 engine 没 bug
✓ X (adversarial)             5 反问全有非空答案
```

四锁分给四个 agent（V / A / A / X），**没人单枪匹马能过整 mode**。这是防 self-loop 的核心。

---

## §6 Pareto Trap 警惕

如果 Per-Mode Inner Loop 出现以下情况：

```
连续 3 次 iter 都是同样 RED 类别（比如 high7 share 总顶不到下限，
或 mode 1 hit 总比 target 高 2pp 拉不下来）
```

**不能死 tune**。说明设计本身跟 paytable 数学不自洽：

```
回 Stage 4 让 D 改 design intent，理由：
- 真原型 PAR sheet 数字可能跟当前 paytable 结构不兼容（cherry-anywhere
  机制下 hit 物理下限就是某值）
- user_brief 倾向性可能跟 paytable 结构冲突 → escalate user
```

参考 [`memory/feedback_tuner_pareto_trap.md`](../memory/feedback_tuner_pareto_trap.md) 跟 [`memory/feedback_dont_lower_floor_when_blocked.md`](../memory/feedback_dont_lower_floor_when_blocked.md)。

---

## §7 信息流 — `session_artifacts/<M>/` 目录

agent 间不通过对话传 — 通过文件传，省 context：

```
session_artifacts/<M>/
├── user_brief.md                 # user 输入（手写）
├── 01a_data_inventory.md         # A: cache 状态 + chunk count
├── 01b_baseline_report.md        # A: production analyzer 输出摘要
├── 01c_field_analysis.md         # A: rawdata 反推 rules / paytable
├── 01d_research.md               # R: archetype + 业界数据
├── design_v<n>.md                # D: 综合 4 路输入（迭代版本号）
├── targets_v<n>/                 # D: target file snapshots
├── verify_run_v<n>_iter<k>.txt   # V: 每次 verify 输出
├── empirical_v<n>_mode<N>_iter<k>.md  # A: 每次 empirical sub-gate
├── mode_<N>_critique_v<n>.md     # X: per-mode adversarial answers
├── cross_mode_check_v<n>.txt     # Stage 7 V 输出
├── empirical_v<n>.md             # Stage 8 A 输出（全 mode）
└── final_critique.md             # Stage 9 X 输出（commit 前最后）
```

每个 agent prompt 里指定它的输入 artifact 路径（绝对或 session-relative），输出落到指定路径。主 session 协调时**永远不在对话里贴大段内容** — 给 path，让 agent 自己 Read。

---

## §8 收敛 / 终止条件

**通过条件（同时满足）**：

1. Stage 6 每个 mode 4-lock 都开
2. Stage 7 cross-mode invariants 全 GREEN
3. Stage 8 full empirical 通过：
   - 4 mode 全 ±2σ
   - schema 跟生产 rawdata 字节级对齐
   - X 抽样 round 看叙事自洽
4. Stage 9 final_critique 5 反问全 closed loop

**Stop 触发（任一即停手报 user）**：

- ✗ Stage 6 任一 mode 5 次 iter 仍同类 RED
- ✗ Stage 7 同对 mode 来回踢皮球 ≥ 2 轮
- ✗ Stage 8 realized 持续偏离 5σ+（不是 noise）
- ✗ Stage 9 同条 stress-test 连拒 3 次（设计本身结构问题）
- ✗ Stage 6.k.d 出现 ① fail (engine bug) 类型，回 Stage 2 修后**全流程从 Stage 5 重跑**

---

## §9 跨切原则（每个 stage 都生效）

1. **archetype-first**：所有数字必须 cite 真原型 PAR sheet / 业界数据，不抄 sister machine 的 target
2. **TDD**：verify 先写、注入 bug 先测，再开始 tune；新 stage 进入前先建该 stage 的 stop condition
3. **"假但不怪"** ([`PHILOSOPHY §11`](DESIGN_PHILOSOPHY.md))：数值是基础，玩家手感是灵魂；每 stage 通过前 X 必走玩家叙事自检
4. **archetype > philosophy > user brief > machine-private** 的真理顺位严格执行（§2）
5. **per-machine isolation** (`tests/core/test_per_machine_code_md5.py`)：本机改动只 invalidate 本机 cache；新机台 onboarding 必跑 isolation test
6. **生产 schema 字节对齐**：Stage 2 完就跑 `compute_schema_fingerprint` vs 生产 chunk，差 1 字节都 fail
7. **Empirical-grounded**：所有 analytic 结论必须在 Stage 6.k.d / Stage 8 被 Monte Carlo 印证，否则不算通过
8. **No Claude-self-loop**：永远不读上一轮 Claude 写的 narrative 当 input；每次 design 走 archetype + philosophy + brief 重新推
9. **escalation over guessing**：遇到结构性矛盾（philosophy vs user brief vs paytable math）→ escalate user，不自决
10. **commit hook 强制 4 段** (`.claude/hooks/verify-commit-msg.py`)：Verified happy path / Verified failure paths / Not verified / Tests added 全有非空内容

---

## §10 跟其他文档的关系

```
ARCHITECTURE.md         代码长成什么样   工程层
DESIGN_PHILOSOPHY.md    设计 first principles  设计层
WORKFLOW.md             commit 前 review 流程  review 层
ONBOARDING_PROCESS.md   团队 + workflow 流程   process 层 ← 本文件
SPEC_SCHEMA.md          spec DSL 字段说明  schema 层
machines/<M>/DESIGN.md  这台机的设计      机台私有
machines/<M>/MODE_DESIGN.md  这台机的 per-mode 设计  机台私有
```

新机台开 session 第一步：主 session 读 1-3 + 本文件，再决定调哪个 agent。

---

## §11 进度跟踪

每次 onboarding 完成后在此追加一行：

| 机台 | 完成日期 | merge commit | 备注 |
|---|---|---|---|
| M1 | pre-Phase-A | — | base only，refactor 时迁入新布局 |
| M37 | pre-Phase-A | — | base only |
| M279 | pre-Phase-A | — | custom engine adapter |
| M15 | 2026-05-11 | `275675c` (feature commit) + merge SHA below | **首次跑完整流程** — 6-agent × 11-stage × 3 D waves × 2 X reviews → v8 weights GREEN on 25 verify categories；session_artifacts/M15/process_improvements.md 累 45 条改进，§1.1 / §1.2 / §2.1 已 backport；详细 audit trail 见 session_artifacts/M15/ |

### §11.1 First-run lessons (M15 2026-05-11) backported

以下 process gaps 已在 M15 完成时 backport 到 ONBOARDING_PROCESS.md / 相关代码：

- **§1.1 paytable 永久不变 invariant** ← process_improvement #36
- **§1.2 数值约束 vs 感性描述区分** ← process_improvement #37
- **§2.1 Designer contamination firewall** ← process_improvements #2 / #3
- Stage 4 Designer 必跑 `analytic_profile` / `analyze_feature` feasibility-first（不再纸面推） ← process_improvements #20 / #25
- Stage 5 V 必跑 inject-bug TDD + 独立 feasibility numerator check ← process_improvement #22
- Escalate user 时必用玩家语言不是技术黑话 ← process_improvement #23

剩余 ~30 条 process gaps（M15-specific 细节、工具 docstring drift、edge cases 等）在 [`session_artifacts/M15/process_improvements.md`](../session_artifacts/M15/process_improvements.md) — 下一个机台 onboarding 时按需 backport。
