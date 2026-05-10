# Spec DSL — schema & semantics

Spec 是声明式的机台规则描述。Engine 根据 spec 执行 spin 逻辑，不 hardcode 机台。

## Top-level shape

```jsonc
{
  "machine": "M1",            // 机台代号（必须和 configs/machines.json 对齐，给 emitter 填 _machine 用）
  "mode": 1,                  // RTP mode
  "schema_version": 1,        // spec DSL 版本，未来 breaking change 时 bump

  "grid":      { ... },       // 网格尺寸 + payline 定义
  "symbols":   { ... },       // 符号集合 + 行为 kind
  "pays":      [ ... ],       // pay 规则列表（含 pay_id → rule 映射）
  "evaluation_order": [ ... ],// pay 评估优先级（第一个命中为准）
  "spin_types":{ ... },       // SpinType → reel set / cost / 后置行为

  "features":  [ ... ],       // 可选：collect_mechanic / bonus_chain / wheel / …
  "emit_fields":{ ... }       // 可选：覆盖默认 round schema（某些机台有额外字段）
}
```

## `grid`

```jsonc
{
  "cols": 3,
  "rows": 3,
  "paylines": [
    {
      "line_id": 1,
      "positions": [[0,1],[1,1],[2,1]]   // (col, row) 0-indexed，row=1 = middle
    }
  ]
}
```

复杂机台：多 payline 直接列出。ways-pay 机台用 `"paylines": "ways_pay_left_to_right"` 这种字符串 strategy 占位，evaluator 里匹配 strategy 名。

## `symbols`

```jsonc
{
  "Blank":    { "kind": "filler" },
  "Cherry":   { "kind": "cherry_special" },
  "Bar1":     { "kind": "regular" },
  "Diamond1": { "kind": "wild", "multiplier": 2 }
}
```

### 支持的 `kind`

| kind            | 语义                                              | 扩展字段           |
|-----------------|---------------------------------------------------|--------------------|
| `filler`        | 填充符号，无 pay，wild 不能替代                   | —                  |
| `regular`       | 普通符号，可被 wild 替代                          | —                  |
| `wild`          | 通配符，替代非 filler/非 cherry_special           | `multiplier` (默认 1) |
| `cherry_special`| 独占优先级：任何出现则触发 cherry_count pay，wild 不替代它 | — |
| `scatter`       | （未来）任意位置计数 pay                           | —                  |
| `locked`        | （未来）hold-and-win / lock-symbol-freespin 用    | —                  |

新 kind → 在 `engine/symbol.py` 加 strategy 类，spec schema_version bump。

## `pays`

每个 pay_id **必须**唯一。Engine 评估时按 `evaluation_order` 遍历 pay kind，第一个匹配触发。pay_id 保留给 rawdata emitter 写 `PayoutIdToWinAmount`。

```jsonc
[
  {"pay_id": 14, "kind": "cherry_count", "count": 1, "multiplier": 1},
  {"pay_id": 13, "kind": "cherry_count", "count": 2, "multiplier": 2},
  {"pay_id": 12, "kind": "cherry_count", "count": 3, "multiplier": 10},

  {"pay_id": 2, "kind": "pure_wild", "multiset": {"Diamond1": 3}, "multiplier": 500},
  {"pay_id": 3, "kind": "pure_wild_group",
   "alternatives": [
     {"multiset": {"Diamond1": 2, "Diamond2": 1}, "multiplier": 240},
     {"multiset": {"Diamond1": 1, "Diamond2": 2}, "multiplier": 360}
   ]},
  {"pay_id": 4, "kind": "pure_wild", "multiset": {"Diamond2": 3}, "multiplier": 1000,
   "grand_jackpot": true, "rtp_excluded": true},

  {"pay_id": 5, "kind": "line_3_same", "symbol": "Seven2", "multiplier": 50},
  {"pay_id": 6, "kind": "line_3_same", "symbol": "Seven1", "multiplier": 40},
  {"pay_id": 7, "kind": "line_3_same", "symbol": "Bar3",   "multiplier": 20},
  {"pay_id": 8, "kind": "line_3_same", "symbol": "Bar2",   "multiplier": 15},
  {"pay_id": 9, "kind": "line_3_same", "symbol": "Bar1",   "multiplier": 10},

  {"pay_id": 10, "kind": "line_3_group", "group": ["Seven1","Seven2"], "multiplier": 25},
  {"pay_id": 11, "kind": "line_3_group", "group": ["Bar1","Bar2","Bar3"], "multiplier": 5}
]
```

### 支持的 pay `kind`

| kind                | 触发条件                                                   | 是否允许 wild 替代     |
|---------------------|------------------------------------------------------------|------------------------|
| `cherry_count`      | payline 上 cherry 计数 == `count`                          | 不允许（cherry 独占）  |
| `line_3_same`       | payline 上（wild 替代后）3 个 == `symbol`                  | 允许，wild 乘数叠加    |
| `line_3_group`      | payline 上（wild 替代后）3 个都属于 `group`，且非 3-same   | 允许，wild 乘数叠加    |
| `pure_wild`         | payline 上 3 个 wild 且 multiset 精确匹配                  | N/A (本身全 wild)      |
| `pure_wild_group`   | `pure_wild` 的多候选（任一 alternative 的 multiset 匹配即可）| N/A                    |
| `scatter_count`     | （未来）整 grid 的 scatter 计数                            | 可选                   |
| `line_N_same`       | （未来）N-reel 通用版 line_3_same                          | 允许                   |
| `ways_pay`          | （未来）从左到右连续列匹配                                 | 允许                   |

### 关键语义

- `rtp_excluded: true` → 该 pay 的 win 在 summary RTP 计算中不计入。**但 engine 仍会在极少数情况下产生它**（按权重算的真实概率），只是它不统计。策划可以用这个实现 "grand jackpot 通过机制给而非 spin 中" —— 把它的 pay 标上 rtp_excluded + weights 设到 P<1e-8 基本不出现。
- `multiset` = symbol → count 字典。3-col 机台下 sum(count) == 3。
- `alternatives` = 多候选，任一匹配即触发（且用该候选的 multiplier）。

## `evaluation_order`

```jsonc
["cherry_count", "pure_wild", "pure_wild_group", "line_3_same", "line_3_group"]
```

Engine 按此顺序遍历所有 pay kind，逐条尝试匹配。**第一个命中即停**（不是 "取 max pay" —— cherry 优先级依赖这个顺序）。

**Tie-breaking 内 kind**：同 kind 内按 `pay_id` 升序？不——按 `multiplier desc`。例如 `line_3_same` 内 3-Seven2(50×) 和 3-Seven1(40×) 都能匹配（wild 替代后）时，payline 符号决定具体哪个 —— 具体符号唯一时无歧义；符号组合有歧义时选 max multiplier。

**Wild 替代选择策略**：当 payline 含 wild 且有多种替代方案产生不同 pay 时，evaluator 计算所有可能的 (pay_id, final_multiplier) 并**选 final_multiplier 最大**的。例如 (Bar1, Bar1, Wild2x) 可触发 3-Bar1 (10×2=20) 或 mixed-bar (5×2=10)；选 3-Bar1。这是标准 slot 引擎行为。

## `spin_types`

```jsonc
{
  "1": {
    "kind": "paid",
    "cost_per_spin": 1000,
    "bet_amount": 1000,
    "reel_set": "default"
  }
}
```

M1 只有一种。未来机台：

```jsonc
{
  "140": { "kind": "paid", "cost_per_spin": 1000, "bet_amount": 1000, "reel_set": "main" },
  "126": { "kind": "bonus_respin", "cost_per_spin": 0, "bet_amount": 1000, "reel_set": "bonus",
           "consumes_state": "free_spins_remaining",
           "pays_included_in_rtp": true }
}
```

`kind` 决定 engine 怎么编排：
- `paid`：扣 `cost_per_spin` credits，emit 正常 round
- `bonus_respin`：不扣 credits，emit bonus round（`CostCredits=0`, `BetAmount=bet_amount`）
- `wheel` / `pick_em`：（未来）非 reel-based 的特殊 spin 类型

## `features`

可选。每个 feature 声明它的触发条件 + 后置效果。

```jsonc
[
  {
    "name": "collect_mechanic",
    "trigger": { "kind": "symbol_count_in_grid", "symbol": "CollectCoin", "min_count": 1 },
    "effect":  { "kind": "increment_state", "field": "collect_count", "by": 1 },
    "threshold": { "field": "collect_count", "value": 1000, "cycle_reset": true },
    "on_threshold": { "kind": "enqueue_bonus_chain", "feature_name": "NewFreespin" }
  },
  {
    "name": "NewFreespin",
    "kind": "bonus_chain",
    "entry_spin_type": "126",
    "initial_spins": 5,
    "retrigger": { "kind": "symbol_count_in_grid", "symbol": "RetrigScatter", "min_count": 3,
                   "add_spins": 3 }
  }
]
```

M1 没有 features，这个字段留空数组。

## `emit_fields`

可选。覆盖默认 round schema。默认 emitter 输出现有 rawdata 观察到的通用字段集（`WinCredits / CostCredits / BetAmount / StopSymbolsByCol / PayoutByPayline / PayoutIdToWinAmount / SpinType / ReMarks / RewardLastNode / PayoutGroupId / PayLineGroupId / CurJackpotStoreWin / IsLackCreditsSpin / SpinTimes / RTPId / LastCredits / ReelSkin`）。

M1 spec 不需要 override。复杂机台（带 collect）可能需要：

```jsonc
{
  "extra_round_fields": {
    "CollectCount": "state.collect_count",
    "AccCredits":   "state.acc_credits"
  }
}
```

engine 按路径从 `MachineState` 读值填入 round dict。

## 新机台 onboarding 流程

1. `rawdata/<M>/mode_<N>/` 已经存在的 → 写 `tests/fixtures/M{N}_field_analysis.md`：扫几千 round，挖出 pay_id → 规则映射、wild 行为、特殊 feature
2. 手写 `specs/M{N}.spec.json`
3. 手写 `weights/M{N}_mode{N}.json`（策划给或反推）
4. `scripts/verify.py --machine M{N} --mode N` 跑 simulator → analyzer → 对比真实 report，diff 接受则 spec 正确
5. 如果 diff 大，说明 spec 漏了什么或 engine 缺 feature → 修 + 重跑

目标：大部分机台 **只改 spec 不改 engine**。只有真出现新机制（如没人见过的 feature）才加 plugin。
