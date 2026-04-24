# 新机台 Onboarding — 完整流程

**目标**：把一台新机台（例如 M3 / M27 / M42）从零带到 **4 mode (1/2/5/7) shipped + 虚拟 console 可采样 + rawdata 管道对上**。

**适用范围**：M1（base-only classic 3-reel）和 M15（带 Feature Play）两类机台都覆盖。有其它 feature 类型（bonus chain / collect / wheel / free spin）的机台参考 §9 扩展点。

## 0. 契约 + 上下文

**目标交付**（per machine）：
1. `slot_designer/specs/<M>.spec.json` — paytable + rules DSL
2. `slot_designer/weights/<M>/reel_strips.json` — 共享 symbol 布局（跨所有 mode 字节级一致）
3. `slot_designer/weights/<M>/mode_<N>/weights.json` × 4 — mode 1/2/5/7 per-stop 权重（feature 机台含 feature_params 块）
4. `slot_designer/tuner/targets/<M>_mode<N>_*.target.json` × 至少 2 — mode 1 + mode 2 的 tune target（mode 5/7 派生，不需要自己的 target）
5. `slot_designer/configs/machines_virtual.json` 注册条目
6. （可选）`slot_designer/weights/<M>/M<N>_weights_reference.csv` — 策划速查 CSV
7. 虚拟 console 跑 batch-run 产 rawdata OK + report 能画 feature panel（feature 机台）

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

## 1. 阶段 1 — 机台理解 + spec 写死（~20 分钟）

**输入**：
- 策划的 paytable md 文档
- 上游采来的 rawdata（`rawdata/<M>/mode_<N>/chunk_*.json`）— 用来反推
- 机台特殊机制说明（wild 规则、feature 玩法、scatter、re-roll 等）

**做什么**：

1. **读 paytable md**：列 symbol 集 / pay_id / 倍率 / 特殊规则
2. **扫 rawdata 反推**：
   ```bash
   python -c "
   import json
   d = json.load(open('rawdata/<M>/mode_1/chunk_0001.json'))
   # 看 pay_id → payline symbols → multiplier 对不对得上 md
   "
   ```
   md 经常有笔误 — rawdata 是 ground truth。
3. **写 `slot_designer/specs/<M>.spec.json`**（手写；参考 `specs/M15.spec.json` 或 `specs/M1.spec.json`）：
   - `symbols`：所有 symbol + kind（`filler / cherry_special / regular / wild`）
   - `pays`：所有 pay_id + kind（`line_3_same / cherry_count / pure_wild / line_3_group / scatter_trigger`）+ 倍率
   - `evaluation_order`：pay kind 的优先级
   - `spin_types`：至少 spin_type 1（paid），bet_amount, cost_per_spin
   - `features`（feature 机台）：feature_params 默认值 + trigger_pay_id
4. **写反推笔记 `tests/fixtures/<M>_field_analysis.md`**：记 md 跟 rawdata 不一致的地方 + 你的判断
5. **Symbol 命名一律小写**（生产 schema 对齐；PascalCase 是 M1 遗留）

> **production-schema 对齐是硬约束**：分析器跟生产 rawdata 强耦合。`_machine / _mode / response / roundResult JSON string / analysisResult JSON string` 这些字段不能动。M15 验收时跟 `M15$TopDollarSelector$0$` 字节级对齐。

**feature 机台特有**：
- Spec features[0] 需声明 `trigger_pay_id`（feature 触发标记 pay_id）
- 写 `engine/feature_<M>.py` 或复用现有（M15 是 `feature_m15.py`），实现 `analyze_feature()` + `simulate_feature_session()`
- Spec `spin_types` 里 feature 轮走 ST=14，end marker ST=15，见 §4.5

---

## 2. 阶段 2 — 初始 reel 表 + 目录骨架

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

## 3. 阶段 3 — Mode 1 first tune (Phase 4 + Phase 5 full)

Mode 1 是所有 mode 的起点：
- 独立 archetype（不是从别人派生）
- **必须跑 Phase 5** — 这会设定整个机台的 strip 排列（之后 mode 2/5/7 都跟这个走）

**写 target file** `slot_designer/tuner/targets/<M>_mode1_classic.target.json`（参考 `M15_mode1_classic.target.json`）：
- `rtp_pct`: 42.75（或按 base:feature split 调，feature 机台 ~45pp，base-only 机台 95pp）
- `bucket_rate`: 参考 M1/M15 类似机台 + 业界 classic 1-line 基准（`reference_classic_slot_rtp_distribution.md`）
- `hit_rate`: 13-15% 带宽（mode 1 reference）
- `_design_constraints`: 记总 RTP target / split / trigger 等

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

## 4. 阶段 4 — Mode 2 独立 tune (`--sa-steps 0`, strips 已锁)

Mode 2 是独立 archetype（不从 mode 1 派生），但 strips 跟 mode 1 一致。

**写 target file** `<M>_mode2_lucky.target.json`（参考 `M15_mode2_lucky.target.json`）：
- `rtp_pct`: 135（feature 机台基本都是）
- `hit_rate`: 0.20-0.25（**×1.5-2 mode 1，不是 ×3**！见 `project_slot_designer_hit_rate_deviation.md`）
- `bucket_rate`: 跟 mode 1 形状相近，总和对应 hit_rate

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

## 5. 阶段 5 — Mode 7 派生 from mode 1

**两条路径**（按 hit rate 带宽决定）：

### 5A. Direct-scale 路径（M1 方式；hit rate 允许下降 ~5pp）

```
mode_7_weights = mode_1_weights × (Cherry × 0.5, Bar × 0.9)
```

- 简单，不走 tuner
- M1 实测：hit 从 15.5% 降到 10.4%，合 target
- **陷阱**（见 `feedback_tuner_pareto_trap.md`）：tuner 会 pareto 把 Seven 家族砍到 0，破坏 bucket 结构。direct scale 保 Seven marginal

### 5B. Phase 4 tune 路径（M15 方式；hit rate 严格贴 mode 1）

- M15 试过 direct-scale (Cherry × 0.3, Bar × 0.77) 落 RTP 32.67 OK 但 hit 7.5% ✗（要 12-13%）
- **原因**：direct scale 砍 paying symbol 权重，同时砍 hit；两个 target 冲突
- **改走 tune.py**：新 target file `<M>_mode7_standard_low.target.json`，rtp=32.5 + hit=0.125 + trigger 跟 mode 1

```bash
python -m slot_designer.scripts.tune \
    ... --mode 7 --sa-steps 0 \
    --target slot_designer/tuner/targets/<M>_mode7_standard_low.target.json \
    --hit-target 0.125 --hit-weight 1.5 \
    --trigger-target 0.01136 --trigger-symbol topdollar \
    --trigger-reel 3 --trigger-weight 2.0
```

**Feature 机台 mode 7**：feature_params **字节级复制 mode 1**（"feature 完全同 mode 1" 设计契约）。Post-tune 手动 cp：
```python
m7['feature_params'] = copy.deepcopy(m1['feature_params'])
```

**路径选择规则**：
- Hit rate 可漂 3-5pp → direct-scale（M1 方式）
- Hit rate 严格 ±1pp → Phase 4 tune（M15 方式）
- 不确定？跑 direct-scale 先看 hit 掉多少；如果超 band 再转 tune

---

## 6. 阶段 6 — Mode 5 派生 from mode 2

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

## 7. 阶段 7 — 注册虚拟机台 + 生成 reference CSV

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

## 8. 阶段 8 — 虚拟 console 采样 + 验证

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

## 9. 特殊 feature 机台扩展点

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

## 10. 检查清单（每个新机台过一遍）

**Phase 0 准备**：
- [ ] Paytable md 读完 + symbol/pay_id 理解
- [ ] Rawdata 反推跟 md 对上 + 笔记写好
- [ ] Spec 文件写完（symbols / pays / evaluation_order / spin_types / features）
- [ ] Field analysis 笔记

**Phase 1 mode 1 tune**：
- [ ] reel_strips.json 写完（Blank/非Blank 交替、trigger 符号只在 reel 3）
- [ ] mode_1/weights.json 初稿（策划原始数字）
- [ ] `<M>_mode1_classic.target.json` 写完
- [ ] Phase 4 + 5 tune 跑通，RTP + hit 贴 target ±1pp
- [ ] Feature 机台：feature_params 手附

**Phase 2 mode 2 tune**：
- [ ] `<M>_mode2_lucky.target.json` 写完（hit 20-25%，不是 ×3！）
- [ ] Tune `--sa-steps 0 --hit-target 0.225 --trigger-target ...`
- [ ] RTP 135 / hit 22.5% / trigger 2.75% 都贴
- [ ] Feature 机台：feature_params 手附

**Phase 3 mode 7 派生**：
- [ ] 选 direct-scale OR Phase 4 tune（看 hit rate 带宽要求）
- [ ] Total 85% ±1pp
- [ ] Feature 机台：feature_params 字节级 = mode 1

**Phase 4 mode 5 派生**：
- [ ] Base weights 字节级 = mode 2
- [ ] Feature params 加强（feature 机台）或 top-bucket 加权（非 feature）
- [ ] Total 500% ±20pp

**Phase 5 注册 + 验证**：
- [ ] `machines_virtual.json` 加 `<M>sim` 条目
- [ ] Refresh md5 成功，per-mode modesMd5 都有值
- [ ] 虚拟 console 能看到 `<M>sim` 4 个 mode
- [ ] 4 个 mode 各自采样成功，report 有数据
- [ ] RTP / hit / trigger 全部贴 analytic target
- [ ] Feature 机台：report 的 feature panel 非空

**Phase 6 文档 + 交付**：
- [ ] `weights/<M>/MODE_DESIGN.md` 写完（参考 M15 structure）
- [ ] `weights/<M>/README.md` 写完
- [ ] `weights/<M>/<M>_weights_reference.csv` 生成（策划速查）
- [ ] Regression test 加到 `tests/test_<M>_*.py`（mode 1/2/5/7 numeric 回归，参考 `test_m15_feature.py`）
- [ ] Pytest 全绿
- [ ] Commit

---

## 11. See also

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
