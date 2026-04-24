# 新机台 Onboarding — 完整流程

**目标**：把一台新机台（例如 M3 / M27 / M42）从零带到 **4 mode (1/2/5/7) shipped + 虚拟 console 可采样 + rawdata 管道对上**。

**适用范围**：M1（base-only classic 3-reel）和 M15（带 Feature Play）两类机台都覆盖。有其它 feature 类型（bonus chain / collect / wheel / free spin）的机台参考 §10 扩展点。

## 核心原则（4 条红线）

**0. 绝对原则：数值是基础，玩家感性体验是灵魂**（`project_slot_designer_axiom_experience_is_soul.md`）

数值 target hit（RTP / hit / bucket_js）是 **necessary precondition**，不是 "done" 标志。**done** = 数值全中 **+ experience 指标全绿**:
- 家族 RTP share vs classic benchmark（7-dominated 机 Seven ≥ 40-60%；Wild-jackpot 机 top path ≥ 60% of Top bucket；etc.）
- Mode 间 experience invariant（mode 7 vs mode 1 保 Seven 绝对击中率；mode 5 vs mode 2 High bucket × 1.5 +；etc.）
- Per-family per-reel ratio drift vs 真原型 < 0.15
- Near-miss 结构（顶奖 family 窗口/支付线 ratio > 1.5）
- Bucket shape narrative（boom-bust / mid-heavy / grind 对应设计叙事）

**反面案例**：M1 TDD-rebuild commit 00345a0 数值全中但 Seven share 10%（原 classic 20%）— classic "7-dominated" 灵魂丢失。原因：family-scale tuner cost_fn 没约束家族 share。**每次 tune 完跑 `slot_designer/scripts/verify_<M>_design.py` 全绿才算 done**。

**1. 每台机台都要跑 WebSearch 英文源**（`feedback_always_research_each_time.md`）
不能只靠 memory 笔记决定"M1 样、M15 样、...的新机台"。每台机台的玩家体验 / near-miss / bucket 目标都要独立查业界同类 + 研究论文。

**2. 数值 target 从设计原则推，不从上游 rawdata 继承**
上游 rawdata 反推**只用于理解机制**（pay_id / symbol / wild 规则 / re-roll protection）。**数值层面**（bucket 分布 / hit rate / per-mode RTP structure）**是我们独立设计**的，不抄原机台的现状分布。原机台的 RTP 是它的，新 4-mode 系统的 RTP 是我们的。

**3. Bucket 分布要合理**
每 mode 的 `bucket_rate` target 必须按 **Low/Mid/High/Top** 4 档给出**设计意图**（每档的 RTP 贡献 + hit rate band + 情感作用），不能是"随便塞个数字让 tuner 对上去"。合理 = 跟机台类型匹配（classic 1-line 是 Low/Mid 为主；video slot 可能 Mid-heavy），跟 mode 差异化叙事（mode 5 top-bucket 加厚等）一致。

## 0. 契约 + 上下文

**目标交付**（per machine）：
1. `slot_designer/specs/<M>.spec.json` — paytable + rules DSL
2. `slot_designer/weights/<M>/reel_strips.json` — 共享 symbol 布局（跨所有 mode 字节级一致）
3. `slot_designer/weights/<M>/mode_<N>/weights.json` × 4 — mode 1/2/5/7 per-stop 权重（feature 机台含 feature_params 块）
4. `slot_designer/tuner/targets/<M>_mode<N>_*.target.json` × 至少 2 — mode 1 + mode 2 的 tune target（mode 5/7 派生，不需要自己的 target）
5. `slot_designer/configs/machines_virtual.json` 注册条目
6. **`slot_designer/scripts/verify_<M>_design.py`** — **必备** experience-gate 脚本：跑完 4 mode 所有 red/green check，所有红线必绿才算 shipped。基于红线 0 的 experience invariant + 家族 RTP share benchmark
7. （可选）`slot_designer/weights/<M>/M<N>_weights_reference.csv` — 策划速查 CSV
8. 虚拟 console 跑 batch-run 产 rawdata OK + report 能画 feature panel（feature 机台）

**跨机台硬约束**（新机台必须套）：

| 约束 | 值 | 严格度 | 来源 memory |
|---|---|---|---|
| mode 1 Total RTP | **95%** | ±1pp 严格 | `project_slot_designer_mode_rtp_invariants.md` |
| mode 2 Total RTP | **300%** | ±10-20pp 可漂 | 同上 |
| mode 5 Total RTP | **500%** | ±10-20pp 可漂 | 同上 |
| mode 7 Total RTP | **85%** | ±1pp 严格 | 同上 |
| Strips 跨 mode | 字节级一致 | 硬 | `project_slot_designer_strips_identical_across_modes.md` |
| mode 7 hit vs mode 1 | ±1pp | 跟机台定 | `project_slot_designer_hit_rate_deviation.md` |
| mode 2 hit vs mode 1 | ×1.5-2（非 ×3） | 跟机台定 | 同上 |
| mode 5 base vs mode 2 base | 字节级一致 | 硬 | 同上 |
| Base:Feature split | 机台自选 | 软 | M15 用 45:55；M1 用 100:0（无 feature） |

---

## 1. 阶段 1 — 机台研究 + 玩家感性体验设计（~20 分钟，**每台机台都要做**）

> 这一阶段是**新机台 onboarding 的第一步，不能跳**（见 `feedback_always_research_each_time.md`）。每个新机台都跑一次 WebSearch，不靠 memory 笔记做决策。

**输入**：
- 策划的 paytable md + 机制说明
- 上游采来的 rawdata（用来反推机制 — **仅用于理解机制/机台身份，不用于决定数值 target**）

**做什么（产出 `weights/<M>/DESIGN.md`）**：

1. **识别机台原型（Prototype）**
   - M1 类（classic 7-dominant 1-line）？M15 类（Top Dollar + 4-round accept/reject）？M37 类（grand-tier booster 1-line）？
   - WebSearch 英文源：game name + paytable + RTP + "near miss" + "player psychology"
   - 对标业界同类机台（IGT / Aristocrat / Konami 产品线）

2. **玩家感性体验剖析** — 回答这些问题：
   - 机台叙事主题是什么（"vault/treasure"、"animal kingdom"、"mythology"）？
   - 每档 win 的**情感定位**是什么？
     - 小奖（1-10×）：chase excitement / grind 感
     - 中奖（10-50×）：accept 时的满足感 / 记忆点
     - 大奖（50-500×）：session 记忆点 / dream event
     - 顶奖（500+）：lifetime story / advertising hook
   - **Near-miss 机制**：2-of-3 high symbols 上 payline 的频率？高价值符号在 window 里的聚集度（PWDF）？
   - **Win 的感性构成**：win 是一次大爆（boom-bust 7-dominant）还是多次 mid 累（classic 46% RTP from Cherry）还是中高频中档（TD-style reveal drama）？
   - **Reject/reroll drama**（feature 机台）：玩家是否要做决策，决策难度分布？

3. **跨 mode 差异化叙事** — 每 mode 的"玩家故事"：
   - mode 1 baseline: 机台的"原生"感觉
   - mode 7 vs mode 1: 什么是"冷"（hit 频率同但 avg 小 / hit 少 / top bucket 少）
   - mode 2 vs mode 1: 什么是"运气来了"（hit 略多 + 每次更值 / feature 变常客 / ...）
   - mode 5 vs mode 2: 什么是"super 幸运"（feature EV × 2.2 / top jackpot moment / ...）

4. **参考文档**：
   - `reference_classic_slot_rtp_distribution.md` — IGT classic (RWB 87% 50%7-fam, Blazing 89% 69%7-fam) 基准
   - `reference_slot_design_research_keywords.md` — WebSearch keyword seed（别只靠这个）
   - Muir (2013) "Elements of Slot Design" / Harrigan (2009) near-miss / Lucas-Singh (2008) CV 研究

---

## 2. 阶段 2 — 机制反推 + spec 写死（~20 分钟）

**输入**：上面的机台研究结论 + paytable md + rawdata

**做什么**：

1. **读 paytable md**：列 symbol 集 / pay_id / 倍率 / 特殊规则
2. **扫 rawdata 反推**（**只用于机制**，不用于数值 target）：
   ```bash
   python -c "
   import json
   d = json.load(open('rawdata/<M>/mode_1/chunk_0001.json'))
   # 看 pay_id → payline symbols → multiplier 对不对得上 md
   # 看 SpinType 分布，ReMarks 有什么标记，有没有 feature ST
   # 看有没有特殊组合被屏蔽（re-roll protection）
   "
   ```
   md 经常有笔误 — rawdata 是 ground truth 反推**机制**。但**数值层面**（bucket 分布 / hit rate / RTP 分布）**不抄上游现状**，数值靠阶段 1 + 阶段 3 的设计决定。
3. **写 `slot_designer/specs/<M>.spec.json`**（手写；参考 `specs/M15.spec.json` 或 `specs/M1.spec.json`）：
   - `symbols`：所有 symbol + kind（`filler / cherry_special / regular / wild` + 新机台可能需要新 kind）
   - `pays`：所有 pay_id + kind（`line_3_same / cherry_count / pure_wild / line_3_group / scatter_trigger` + 可能新 kind）+ 倍率
   - `evaluation_order`：pay kind 的优先级
   - `spin_types`：至少 spin_type 1（paid），bet_amount, cost_per_spin
   - `features`（feature 机台）：feature_params 默认值 + trigger_pay_id
4. **写反推笔记 `tests/fixtures/<M>_field_analysis.md`**：记 md 跟 rawdata 不一致的地方 + 你的判断 + 机制发现（re-roll、booster 机制等）
5. **Symbol 命名一律小写**（生产 schema 对齐；PascalCase 是 M1 遗留）

> **production-schema 对齐是硬约束**：分析器跟生产 rawdata 强耦合。`_machine / _mode / response / roundResult JSON string / analysisResult JSON string` 这些字段不能动。M15 验收时跟 `M15$TopDollarSelector$0$` 字节级对齐。

**feature 机台特有**：
- Spec features[0] 需声明 `trigger_pay_id`（feature 触发标记 pay_id）
- 写 `engine/feature_<M>.py` 或复用现有（M15 是 `feature_m15.py`），实现 `analyze_feature()` + `simulate_feature_session()`
- Spec `spin_types` 里 feature 轮走 ST=14，end marker ST=15，见 §9

---

## 3. 阶段 3 — 初始 reel 表 + 目录骨架

```bash
mkdir -p slot_designer/weights/<M>/mode_{1,2,5,7}
```

**写 `slot_designer/weights/<M>/reel_strips.json`**（共享）：
```json
{
  "machine": "<M>",
  "reel_set": "default",
  "reels": [
    ["blank", "cherry", "blank", "3bar", ...],   // reel 1
    ["blank", "1bar", "blank", "cherry", ...],    // reel 2
    ["blank", "3bar", "blank", "topdollar", ...]  // reel 3
  ]
}
```

**结构不变量**：
- 每 reel 18 blank + 18 非 blank 严格交替（Harrigan near-miss band）
- 跨 mode 字节级一致（后面每次 tune mode 2/5/7 都要 `--sa-steps 0`）
- Trigger 符号（如 topdollar）只在特定 reel（通常 reel 3）

**写 `slot_designer/weights/<M>/mode_1/weights.json` 初稿**（策划给的 raw 权重；之后 tune.py 覆盖）：
```json
{
  "machine": "<M>",
  "mode": 1,
  "reel_set": "default",
  "weights": [
    [36, 8, 27, 49, ...],   // reel 1, len == strip[0] len
    [35, 46, 26, 5, ...],   // reel 2
    [26, 1, 35, 13, ...]    // reel 3
  ]
}
```

---

## 4. 阶段 4 — Mode 1 first tune (Phase 4 + Phase 5 full)

Mode 1 是所有 mode 的起点：
- 独立 archetype（不是从别人派生）
- **必须跑 Phase 5** — 这会设定整个机台的 strip 排列（之后 mode 2/5/7 都跟这个走）

**写 target file** `slot_designer/tuner/targets/<M>_mode1_classic.target.json`（参考 `M15_mode1_classic.target.json`）：

**⚠ bucket_rate 从设计原则推，不抄上游 rawdata**：
- 从阶段 1 研究结论推每档 RTP 贡献的 **意图**：
  - Low bucket (1-10×)：~30-50% RTP（小奖 grind 感 / chase excitement）
  - Mid bucket (10-50×)：~30-50% RTP（accept 时的记忆点 / 定期 reveal drama）
  - High bucket (50-500×)：~10-25% RTP（session 记忆点 / dream event）
  - Top bucket (500+)：0-5% RTP（legendary / advertising hook）
- 从 RTP target + bucket 贡献反推 per-bucket hit rate（RTP ÷ avg mult per bucket）
- 每档的"情感作用"必须写在 target 的 `_note` 里，tuner 只是把数字对上去，**设计意图在 target 文档里**

字段：
- `rtp_pct`: 42.75（或按 base:feature split 调，feature 机台 ~45pp，base-only 机台 95pp）
- `bucket_rate`: 按上面 4 档设计，Low/Mid 为主，High 少，Top 极少。数字参考 M1/M15 类似机台 + 业界 classic 1-line 基准（`reference_classic_slot_rtp_distribution.md`）— 但**不抄上游采的 rawdata 分布**
- `hit_rate`: 13-15% 带宽（mode 1 reference；阶段 1 研究支撑这个选择）
- `_design_constraints`: 记总 RTP target / split / trigger / 情感设计意图 等
- **`_archetype` + family-scale tune**（2026-04-24 修订 — 作废前一版"per-mode per-reel pattern"那套，见 `project_slot_designer_machine_archetype.md`）：
  - Reel_strips.json 必带 `_archetype` block 声明真实原型来源（如 `"source": "https://wizardofodds.com/games/slots/hot-roll/ — IGT Triple Double Diamond reverse-engineered"`, `"confidence": "medium-high"`, `"modifications_from_archetype": "..."`)
  - Mode 1 seed weights = 真原型 baseline 的 direct copy（real machine per-reel virtual mapping numbers）
  - **所有 mode tune 走 `tune_m1_family_scales.py` 那种 family-scale search**（9-dim scalar per mode，bounds [0.25, 4.0]），NOT per-position free tune
  - 每 mode weight[r][p] = mode1_weight[r][p] × scalar[symbol_at(r,p)]
  - Per-reel ratio 跨 mode 自然 preserve（by construction）
  - 来源 hierarchy（从硬到软）：①published real-machine reel mapping → ②industry prototype (IGT / Aristocrat / Dragon Link etc.) → ③literature。**禁用**历史 dev-sim rawdata（循环 reference）
  - 禁止 "每 mode 用不同 per-reel pattern" 叙事（mode 1 期待型 / mode 2 reveal 型 等）—— 那是编的，真机不是这样设计

**Tune 命令**：
```bash
python -m slot_designer.scripts.tune \
    --spec slot_designer/specs/<M>.spec.json \
    --strips slot_designer/weights/<M>/reel_strips.json \
    --base-weights slot_designer/weights/<M>/mode_1/weights.json \
    --target slot_designer/tuner/targets/<M>_mode1_classic.target.json \
    --out-weights slot_designer/weights/<M>/mode_1/weights.json \
    --out-report slot_designer/weights/<M>/mode_1/TUNE_REPORT.md \
    --mode 1 \
    --evaluations 1500 --restarts 3 \
    --sa-steps 5000 \
    --skip-rawdata
```

**对 feature 机台**，还要加 trigger 约束：
```bash
--trigger-target 0.01136 --trigger-symbol topdollar --trigger-reel 3 --trigger-weight 2.0
```

**验证**：
- RTP 贴 target ±0.5pp
- Hit 贴 target ±0.5pp
- `TUNE_REPORT.md` 无 warning
- Feature 机台：手写 feature_params 到 `mode_1/weights.json` 的 `feature_params` 块（tune.py 不碰）

---

## 5. 阶段 5 — Mode 2 独立 tune (`--sa-steps 0`, strips 已锁)

Mode 2 是独立 archetype（不从 mode 1 派生），但 strips 跟 mode 1 一致。

**写 target file** `<M>_mode2_lucky.target.json`（参考 `M15_mode2_lucky.target.json`）：
- `rtp_pct`: 135（feature 机台基本都是）
- `hit_rate`: 0.20-0.25（**×1.5-2 mode 1，不是 ×3**！见 `project_slot_designer_hit_rate_deviation.md`）
- `bucket_rate`: 跟 mode 1 形状**相近**（同一 Low/Mid/High/Top 比例结构），总和对应新 hit_rate。RTP delta 走 **per-hit avg win size**（bucket shape shift toward mid/high），不走 hit frequency inflation

**Seed mode 2 weights** — 先用 mode 1 做起点：
```bash
cp slot_designer/weights/<M>/mode_1/weights.json slot_designer/weights/<M>/mode_2/weights.json
# 改 "mode": 1 → "mode": 2；清掉 _tuned_summary / feature_params
```

**Tune**：
```bash
python -m slot_designer.scripts.tune \
    --spec ... --strips ... \
    --base-weights slot_designer/weights/<M>/mode_2/weights.json \
    --target slot_designer/tuner/targets/<M>_mode2_lucky.target.json \
    --out-weights slot_designer/weights/<M>/mode_2/weights.json \
    --mode 2 \
    --sa-steps 0 \
    --skip-rawdata \
    --evaluations 2500 --restarts 5 \
    --hit-target 0.225 --hit-weight 1.0 \
    --trigger-target 0.0275 --trigger-symbol topdollar \
    --trigger-reel 3 --trigger-weight 2.0
```

**关键 flag**：
- `--sa-steps 0` → 锁 strips（Phase 5 跳过），只调 weights；否则会污染 mode 1 的已采 rawdata
- `--hit-target` + `--hit-weight` → hit rate 硬约束，防止 tuner 自由乱搜（没这个会让 hit 飞到 36%+）
- `--trigger-target` → feature 机台必须，防止 tuner 把 topdollar 砍到 0
- `--sa-steps 0` 自动跳过 sibling weights 写入（mode 1/5/7 不被动）

**Feature 机台**：tune 完后**手动附 feature_params**（mode 2 有自己的 count_y + x_value_weights，跟 mode 1 不一样）。参考 `weights/<M>/MODE_DESIGN.md §2` 或 git log。

---

## 6. 阶段 6 — Mode 7 派生 from mode 1

**Mode 7 设计 guideline**（`project_slot_designer_hit_rate_deviation.md` 核心）：

> **基于 mode 1，降小奖击中率，中/大/顶奖击中率不变**。总 hit 因 Low 绝对数降而略降（mode 1 13% → mode 7 10-11%）；Mid/High/Top 的 **RTP 相对占比略升**（分子不动、Low 分母少了）。玩家感：小奖变稀少，但大奖跟 mode 1 一样 — "每次命中的小奖少，但大奖还是那么多"。

**M1 shipped 实证**（2026-04-23 数据）：

| 指标 | mode 1 | mode 7 |
|---|---|---|
| Total hit | 15.52% | 10.37% |
| Low RTP 占比 | 24.4% | 19.3%（绝对降）|
| Mid RTP 占比 | 63.9% | 66.4%（相对略升）|
| High RTP 占比 | 11.7% | 14.3%（相对略升）|
| 7-family 占比 | 5.2% | 6.6%（略升）|

### Target file 设计（重要）

`<M>_mode7_standard_low.target.json` 的 `bucket_rate` 字段是**绝对值 per-bucket**，不是 shape 模板：

- **Low bucket rate**: **mode 1 值 × 0.6-0.7**（绝对 hit 降 ~3-5pp）
- **Mid bucket rate**: **== mode 1 绝对值**（不动）
- **High bucket rate**: **== mode 1 绝对值**（不动）
- **Top bucket rate**: **== mode 1 绝对值**（不动）
- `hit_rate` target = sum = mode 1 total - 3-5pp（M1 是 -5pp，M15/M37 按 paytable 结构定）

> 跟 mode 2/5 的 bucket_rate 写法不一样：mode 2 bucket_rate 跟 mode 1 的相对分布类似（只是 scale up）；mode 7 bucket_rate **固定保 Mid/High/Top 绝对数**，只砍 Low。

### 两条实现路径（按 paytable 结构决定）

**A. Direct-scale 路径**（M1 方式）
- 适用：paytable 里有符号**几乎只进 Low bucket**（例如 M1 的 Cherry 1× 和混合 bar 2×）
- 方法：`mode_7_weights = mode_1_weights × (LowOnlySymbols × K, 其它 × 1)`
- M1 实测：`Cherry × 0.5, Bar × 0.9` → Low 降、Mid/High 基本保
- 不走 tuner，简单可靠

**B. Phase 4 tune 路径**（M15/M37 方式）
- 适用：paytable 里符号**跨多档**（例如 high7 进 Mid 但 high7+booster 进 High；bars 进 Low-Mid；这时 direct-scale 会误伤 Mid）
- 方法：按上面"Target file 设计"写 bucket_rate 绝对值，`--hit-target` 设总 hit 目标，tuner 自动找能保 Mid/High 的权重配置
- 代码：
  ```bash
  python -m slot_designer.scripts.tune \
      ... --mode 7 --sa-steps 0 \
      --target slot_designer/tuner/targets/<M>_mode7_standard_low.target.json \
      --hit-target 0.10 --hit-weight 1.5 \
      --trigger-target 0.01136 --trigger-symbol topdollar \
      --trigger-reel 3 --trigger-weight 2.0   # feature 机台才加 --trigger
  ```

**Feature 机台 mode 7**：feature_params **字节级复制 mode 1**（"feature 完全同 mode 1" 设计契约）。Post-tune 手动 cp：
```python
m7['feature_params'] = copy.deepcopy(m1['feature_params'])
```

**路径选择决策**：
- 小奖符号跟大奖符号**在 paytable 里分得开**（M1 的 Cherry vs Seven）→ **direct-scale 够**
- 小奖/大奖符号**耦合**（M15 的 cherry+bar 也进 Mid，高 pay_id 也能被 cherry 替代）→ **走 Phase 4 tune**
- 不确定？先看 paytable 结构，再决定；或直接用 Phase 4 tune（更稳）

---

## 7. 阶段 7 — Mode 5 派生 from mode 2

Mode 5 = **mode 2 base 字节级复刻** + **feature_params 加强**。这是硬约束（见 `project_slot_designer_hit_rate_deviation.md`）。

**feature 机台**：
```bash
python -m slot_designer.scripts.derive_m15_mode_5 --write --verify   # M15 做模板
```
或手写 `scripts/derive_<M>_mode_5.py` 仿这个脚本：
1. `cp mode_2/weights.json mode_5/weights.json`
2. 改 `mode: 2` → `mode: 5`
3. Swap `feature_params`（mode 5 的 `x_value_weights` 往高倍偏、`count_y` 往多 y 偏）
4. Analytic verify：total RTP 500 ±20pp

**非 feature 机台 mode 5**（M1 类型）：
- Base 完全 = mode 2
- RTP 从 300 → 500 的 +200pp 通过 **调 top-bucket 权重**（7 家族 / pure_wild）
- 具体做法按机台 paytable 结构定；M1 实测 7-家族占比 31.6% → 56%

---

## 8. 阶段 8 — 注册虚拟机台 + 生成 reference CSV

**注册到 `slot_designer/configs/machines_virtual.json`**（如果不存在的话）：
```json
{
  "machine": "<M>sim",
  "modes": [1, 2, 5, 7],
  "logicClassNames": ["SimulatedClassicPayline3ReelWithBonus"],
  "_source_machine": "<M>",
  "_spec_path": "slot_designer/specs/<M>.spec.json",
  "_strips_path": "slot_designer/weights/<M>/reel_strips.json",
  "_weights_path_template": "slot_designer/weights/<M>/mode_{mode}/weights.json"
}
```

**Refresh md5**：
```bash
python -c "from slot_designer.backend.virtual_registry import refresh_machines_virtual, VIRTUAL_MACHINES_CONFIG; refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)"
```

这会自动：
- Compute per-mode md5 + machine-level aggregate md5
- 填 `modesMd5` 块（每 mode 独立 md5，不互相影响）
- 2026-04-23 auto-discover：weights dir 下新加 `mode_<N>/weights.json` 自动进 `modes` 列表

**生成 reference CSV**（策划速查，不被代码读）：
- 参考 M15_weights_reference.csv 结构（Section A 总览 / B reel weights / C feature params / D 派生概率）
- 可以让 Claude 从 JSON 帮你导一版；手维护

---

## 9. 阶段 9 — 虚拟 console 采样 + 验证

**启动虚拟 console**：
```powershell
powershell -File slot_designer/scripts/start_virtual_console.ps1 -OpenBrowser
# → http://127.0.0.1:8878/console/
```

**UI 流程**：
1. 机台列表看到 `<M>sim`（4 个 mode 下拉）
2. 点 "开始采样"，选 mode 1 → 生成 rawdata 到 `slot_designer/rawdata/<M>sim/mode_1/`
3. "⟳ 生成 Report" → 出 player impact report
4. **验 RTP** 贴 analytic target（±1% 对 mode 1/7 严格，±5% 对 mode 2/5 宽）
5. Feature 机台额外验：report 的 **feature panel** 有 TopDollar / TopDollarSelector 等 feature breakdown，不是空

**遇到 "0 spins produced" 错误**：先排查
- Chunk envelope `_machine/_mode` 是否 = `<M>sim` / `mode_N`（不是 spec 的默认）— 见 `virtual_analyzer.py _run_simulator_chunk`
- Chunk 的 `_config_md5` 是否 = registry 的当前 md5（registry refresh 顺序问题）
- Session P(R≥X) tail 是否合预期（mode 5 特别）

---

## 10. 特殊 feature 机台扩展点

M15 定义了一个 `Feature Play`（4-round accept/reject）类型的 feature。其它类型需要新扩展：

| Feature 类型 | 产品例 | 要加什么 |
|---|---|---|
| Bonus chain | 很多 mainline 2020+ | 新 engine/features/bonus_chain.py + spec `features` DSL |
| Collect mechanic | Buffalo | 扩 spec symbols (collect_state) + engine/features/collect.py |
| Lock-respin | Dragon Link | 扩 spin_type（固定/自由轮）+ engine/features/lock_respin.py |
| Wheel | Wheel of Fortune | 新 spin_type + engine/features/wheel.py |
| Free spin | 几乎所有 video slot | 扩 spin_type + 可能 feature engine |

**Rawdata schema 对齐**（feature 机台硬约束）：
- Feature 触发的 paid spin：`SpinType: 1`, `ReMarks: "Trigger"`（分析器用这个锚）
- Feature 内每轮：新 `SpinType`（M15 用 14）
- Feature end marker：新 `SpinType`（M15 用 15）+ **`WinAmount` 字段（不是 `WinCredits`！）**— 分析器 Type-1 rule 用 `last_non_none WinCredits` 找 session payout，end marker 如果有 `WinCredits=0` 会 override 掉前面真正赢的 ST=14

**扩展完后**：
- 更新 `emitter/round.py` 加 `emit_<feature>_round()` / `emit_<feature>_end()`
- 更新 `emitter/round.py emit_session()` 组装新的 round sequence
- 更新 `engine/spin.py spin_session()` 实际跑 feature
- Engine loader 读 `feature_params` 块构建 FeatureSpec

---

## 11. 检查清单（每个新机台过一遍）

**Phase 1 研究**（**不跳**，每台机台都要）：
- [ ] WebSearch 英文源重跑（不靠 memory）
- [ ] 识别机台原型（M1/M15/新类别）+ 业界对标
- [ ] 玩家感性体验剖析（主题、每档 win 情感、near-miss、win 构成）
- [ ] 跨 mode 差异化叙事（每 mode 故事）
- [ ] 产出 `weights/<M>/DESIGN.md`

**Phase 2 机制 + spec**：
- [ ] Paytable md 读完 + rawdata 反推（**只做机制**）
- [ ] Spec 文件写完（symbols / pays / evaluation_order / spin_types / features）
- [ ] Field analysis 笔记

**Phase 3 reel 表初稿**：
- [ ] reel_strips.json 写完（Blank/非Blank 交替、trigger 符号只在 reel 3）
- [ ] mode_1/weights.json 初稿

**Phase 4 mode 1 tune**：
- [ ] **bucket_rate 从设计意图推**（不抄上游 rawdata），每档 RTP 贡献 + hit rate 在 `_note` 写清楚
- [ ] `<M>_mode1_classic.target.json` 写完
- [ ] Phase 4 + 5 tune 跑通，RTP + hit + bucket shape 贴 target ±1pp
- [ ] Feature 机台：feature_params 手附

**Phase 5 mode 2 tune**：
- [ ] `<M>_mode2_lucky.target.json` 写完（hit 20-25%，**不是 ×3**；bucket shape 跟 mode 1 结构相近）
- [ ] Tune `--sa-steps 0 --hit-target 0.225`（feature 机台加 `--trigger-target`）
- [ ] RTP 135 / hit 22.5% 都贴
- [ ] Feature 机台：feature_params 手附

**Phase 6 mode 7 派生**：
- [ ] 选 direct-scale OR Phase 4 tune（看 hit rate 带宽要求）
- [ ] Total 85% ±1pp
- [ ] Feature 机台：feature_params 字节级 = mode 1

**Phase 7 mode 5 派生**：
- [ ] Base weights 字节级 = mode 2
- [ ] Feature params 加强（feature 机台）或 top-bucket 加权（非 feature）
- [ ] Total 500% ±20pp

**Phase 8 注册 + CSV**：
- [ ] `machines_virtual.json` 加 `<M>sim` 条目
- [ ] Refresh md5 成功，per-mode modesMd5 都有值
- [ ] `weights/<M>/<M>_weights_reference.csv` 生成（策划速查）

**Phase 9 验证**：
- [ ] 虚拟 console 能看到 `<M>sim` 4 个 mode
- [ ] 4 个 mode 各自采样成功，report 有数据
- [ ] RTP / hit / trigger 全部贴 analytic target
- [ ] Feature 机台：report 的 feature panel 非空
- [ ] Bucket 分布图 visually 对上 DESIGN.md 里的意图

**Phase 10 文档 + 交付**：
- [ ] `weights/<M>/MODE_DESIGN.md` 写完（参考 M15 structure）
- [ ] `weights/<M>/README.md` 写完
- [ ] Regression test 加到 `tests/test_<M>_*.py`（mode 1/2/5/7 numeric 回归，参考 `test_m15_feature.py`）
- [ ] Pytest 全绿
- [ ] Commit

---

## 12. See also

**Memory notes（每条都读一遍）**：
- `project_slot_designer_mode_rtp_invariants.md` — 95/300/500/85 目标 + 派生关系
- `project_slot_designer_strips_identical_across_modes.md` — strips 锁死 + `--sa-steps 0` pitfall
- `project_slot_designer_hit_rate_deviation.md` — mode 2/5/7 hit rate 带宽
- `project_slot_designer_strips_weights_layout.md` — 文件布局
- `project_slot_designer_charter.md` — 双角色契约
- `feedback_tuner_pareto_trap.md` — 为什么 mode 7 不能乱 tuner
- `reference_classic_slot_rtp_distribution.md` — 业界基准数字
- `feedback_always_research_each_time.md` — 每次重搜英文源

**机台实例（参考模板）**：
- M1 = base-only 3-reel（无 feature），走 direct-scale mode 7 / top-bucket mode 5
- M15 = 带 Feature Play，走 Phase 4 tune mode 7 / feature-enhance mode 5

**代码入口**：
- `scripts/tune.py` — 4-mode 通用 tuner (Phase 4 + 5)
- `scripts/verify_m15_modes.py` — feature EV 验证（feature 机台套此模板）
- `engine/feature_m15.py` — feature 引擎参考实现
- `backend/virtual_analyzer.py` — 虚拟采样 + delegate 到 real analyzer
- `backend/virtual_registry.py` — machines_virtual.json refresh + mode auto-discover
