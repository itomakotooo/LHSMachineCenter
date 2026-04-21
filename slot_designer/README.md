# slot_designer

独立的 slot-machine 数值调参模块。**不与现有代码耦合**：
- 不 import 任何 `fresh_slotlab/` 或 `src/web_console/` 下的符号
- 不修改现有模块行为
- 唯一交互面是**输出 rawdata 格式的 JSON chunk** —— 现有 `player_impact_analyzer.py --from-cache` 直接吃

## 为什么这样设计

目标：策划给权重表和 paytable 规则 → 我正向模拟 → 生成 rawdata → 现有 analyzer 分析 → 和参考机台画像对比 → 自动/半自动调参。

把 simulator output 对齐到现有 rawdata schema 有两大好处：
1. **白嫖所有分析能力**：现有 analyzer 已经实现 pay_id tally / bucket / tail curve / streak / bankruptcy replay / session-level RTP 等全部指标，不重写
2. **自然的正确性验证**：用已知权重（你给的真实 reel 表）跑 simulator → 跑 analyzer → 对比真实 `reports/M1/mode_1/latest.json` 的 RTP / bucket / per-pay_id fires，差距 < 0.5pp 说明引擎对了

## 模块结构

```
slot_designer/
├── specs/                          spec = 机台规则的声明式 JSON + schema 文档
│   ├── schema.md                   ← spec DSL 规范
│   └── M{NN}.spec.json             ← 逐机台规则
├── weights/                        reel strip 权重表（策划给或调参产出）
│   └── M{NN}_mode{N}.json
├── engine/                         (Phase 1) 正向游戏引擎
│   ├── reel_strip.py               ReelStrip: 带权 stop 采样 + window(3 行)
│   ├── symbol.py                   Symbol / SymbolKind
│   ├── rules.py                    PayRule 抽象 + 内置 kinds (line_3_same / cherry_count / pure_wild_group / …)
│   ├── evaluator.py                payline 评估（wild 替换 + multiplier 叠加 + cherry 优先级 + grand jackpot 守门）
│   ├── features/                   pluggable 机制（M1 只需 cherry + wild_mult，未来 collect / bonus_chain / lock_respin）
│   ├── state.py                    MachineState: per-robot 状态（CollectCount, free spins remaining, …）
│   ├── spin.py                     SpinEngine: 编排一次 spin（按 SpinType 路由）
│   └── loader.py                   读 spec + weights → 实例化引擎
├── emitter/                        (Phase 1) 输出 rawdata 格式
│   ├── round.py                    emit 单 round dict（对齐 rawdata schema 所有字段）
│   ├── robot.py                    N round → robot.roundResult JSON string
│   └── chunk.py                    N robot → chunk JSON with envelope（_cache_version / _bet / _config_md5 / …）
├── devtools/                       (Phase 3) 开发者快速反馈
│   ├── analytic_rtp.py             闭式 RTP 计算（给权重 + 规则，亚秒级返回）
│   ├── analytic_bucket.py          闭式 bucket 边际分布
│   └── weight_diff.py              两套权重 predicted-metrics diff
├── tuner/                          (Phase 4) 调参 loop
│   ├── target_profile.py           从参考机台 report 抽画像（bucket_dist / tail / hit / σ / …）
│   ├── cost.py                     硬/软/体验三层 cost function
│   └── loop.py                     hybrid: math 快筛候选 → sim+analyzer 验证 → 迭代
├── scripts/                        CLI entry points
│   ├── simulate.py                 spec + weights + N spins → rawdata chunks 落盘
│   ├── verify.py                   sim → analyzer → diff 真实 report
│   └── tune.py                     调参入口
├── tests/
│   ├── fixtures/                   rawdata 反推笔记（新机台 onboarding 参考）
│   │   └── M1_field_analysis.md
│   ├── test_m1_rules.py            单测每个 pay 规则（合成 3-symbol 输入 → 预期 pay_id + win）
│   └── test_m1_engine_regression.py sim(known M1 weights) vs 真实 M1 summary 对账
├── out/                            sim 产出（gitignored）
└── README.md                       本文件
```

## 架构原则（为"千变万化"的未来机台做准备）

### 1. 规则声明 vs 执行分离
- `specs/M{NN}.spec.json` 声明**机台是什么** —— grid 尺寸 / symbol 集合 / pay 规则 / SpinType / feature / 转换
- `engine/` 是**通用执行器** —— 不 hardcode 任何机台
- 添加新机台 = 写新 spec + (可选) 写新 feature plugin。引擎主干代码不动

### 2. 三层扩展点
- **Symbol kind**：`regular / wild / cherry_special / scatter / locked`  
  新 kind → 加一个 symbol.py 中的 strategy 类
- **Pay kind**：`cherry_count / line_3_same / line_3_group / pure_wild / pure_wild_group / scatter_count / ways_pay / cluster_pay / …`  
  新 kind → 加一个 rules.py 中的 PayRule 子类
- **Feature**：`cherry_precedence / wild_multiplier / collect_mechanic / bonus_chain / wheel / pick_em / lock_symbol_freespin / …`  
  新 feature → `engine/features/<name>.py` 实现接口 + 在 spec 声明

### 3. SpinType 路由
每个 spin 按 SpinType 查 `spec.spin_types[type]`：
- 选用哪套 reel_set（paid / bonus / wheel 各有各的 strip）
- cost / bet 规则
- 评估哪些 pay 规则（某些 pay 只在 bonus spin 触发）
- 后置效果（bonus spin 消耗 free_spin_counter / 触发新链）

M1 简化：只有 `"1"` 一种 SpinType。

### 4. 状态机显式化
`MachineState` 载：`free_spins_remaining / collect_count / acc_credits / chain_depth / locked_symbols`。  
每个 feature 声明它要读/写哪些 state 字段。避免隐式耦合。

### 5. Emitter schema-aware per machine
现有 rawdata 的 round schema 各机台差异（M272 有 `CollectCount` / `AccCredits`；M1 没有）。  
emitter 按 `spec.emit_fields` 决定哪些字段写入 —— spec 为王，不在 emitter 里 if-else 机台名。

### 6. 两条调参路径
- **math 路径**（`devtools/analytic_*.py`）：闭式算 RTP + bucket 边际。对 M1 3×3 classic 可行；复杂机台退化为小规模 Monte Carlo（不落盘，内存中）
- **sim 路径**（`scripts/simulate.py` → analyzer）：真跑 100k+ spin，产 rawdata，analyzer 出完整 summary。给出 streak / tail / near-miss 等 math 路径拿不到的指标

tuner 用 math 做内循环快筛，用 sim 做外循环 ground-truth 确认。

## Phase 状态

- **Phase 0** — ✅ scaffold + M1 spec + 结构化权重 + 反推笔记
- **Phase 1** — ✅ engine + rawdata-format emitter + verify
- **Phase 2** — ✅ M14 target profile 抽取
- **Phase 3** — ✅ devtools (analytic RTP + shape distance + weight diff)
- **Phase 4** — ✅ count tuner ((1+1)-ES on 27-dim counts space)
- **Phase 5** — ✅ order tuner (SA on permutation space, 保持 Phase 4 marginals)

第一个机台（M1）pipeline 完整见 [`FIRST_MACHINE.md`](FIRST_MACHINE.md)。

## 硬约束（不变）

1. 不 import 现有代码
2. 不修改现有代码
3. 输出必须严格对齐现有 rawdata chunk schema —— 任何字段名或格式变化 = 破坏约定
