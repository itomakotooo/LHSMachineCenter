# slot_designer — 架构规范

> **范围**：虚拟机台框架的代码层布局、插件协议、版本 hash 算法、新机台 onboarding 步骤、测试规范、命名禁区。每次新增机台、改动核心代码、写新测试前必读。
>
> **跟 [DESIGN_PHILOSOPHY.md](DESIGN_PHILOSOPHY.md) 区别**：DESIGN_PHILOSOPHY 写"设计 slot 时数学/玩家心理上要满足什么"，是**设计哲学**。本文件写"代码层怎么组织、模块边界在哪、新机台怎么挂进来"，是**工程规范**。
>
> **跟 [WORKFLOW.md](WORKFLOW.md) 区别**：WORKFLOW 写"commit 前 self-review 怎么做"，本文件写"代码长成什么样"。

---

## §1 重构出发点（历史 — 两个根本问题，均已解决）

> **状态**：本节描述重构**之前**的问题状态，作为 §2-§9 设计的 rationale 保留。两个问题都已在 Phase A-E 解决（见 §10 进度表 + §10 兑现的承诺）。当前 `code_md5` 已是 per-machine（`machines_virtual.json` 每台 `codeSummaryMd5` 已各不相同），`core/` 已无机台名漏出（`tests/core/test_no_machine_leakage.py` 守住）。

### 1.1 （历史）fleet-wide `code_md5` ── 改一个机台 ⇒ 全 fleet cache 失效

重构前 `compute_code_md5()` 不带 machine 参数，把 `engine/*.py` + `emitter/*.py` 一锅炖成单一 fleet-wide digest，所有机台 `codeSummaryMd5` 相同：

```python
# machines_virtual.json 重构前
M1sim   codeSummaryMd5: 6d7a7d03dc...   ← 全相同
M15sim  codeSummaryMd5: 6d7a7d03dc...
M37sim  codeSummaryMd5: 6d7a7d03dc...
M279sim codeSummaryMd5: 6d7a7d03dc...
```

→ 改 M15 的 feature 实现 1 个字符 → fleet-wide hash 翻 → M1 / M37 / M279 所有 cached chunks 全部 stale。
→ 几百个机台扩展后，单点改动会触发全 fleet 重采样。**修法见 §4**（per-machine `compute_code_md5(machine_name)`）。

### 1.2 （历史）机台名漏到通用层 ── code 边界混乱

重构前漏出点（现已全部清理，列出仅作 rationale）：

| 位置 | 漏出的机台名 |
|---|---|
| `engine/spin.py` | `from .feature_m15 import ...` |
| `engine/loader.py` | `from .feature_m15 import FeatureSpec, _X_POOL, _Y_POOL` |
| `emitter/round.py` | `from ..engine.feature_m15 import FeatureRound` |
| `emitter/robot.py` | hardcode `"TopDollar"` / `"TopDollarSelector"` 字符串 + `st == 14 / 15` 数字 |
| `emitter/driver.py` | 调 `engine.spin_session()`（M15 feature 子轮 API）|

通用代码认识具体机台名 = 边界破坏。后果：**新增一台 feature 机台必须改通用代码** → 又会让所有机台 md5 翻。

---

## §2 当前布局（重构 Phase A-E 已落地）

> 下树是 schematic（重在边界 + 归属规则，不逐字枚举每个文件）；权威以磁盘为准。

```
slot_designer/
├── ARCHITECTURE.md              ← 本文件
├── DESIGN_PHILOSOPHY.md         ← 设计哲学（不变）
├── WORKFLOW.md                  ← review 流程（不变）
│
├── core/                        ← 真正机台无关的框架
│   ├── engine/
│   │   ├── spin.py              SpinEngine（无 machine-specific import）
│   │   ├── loader.py            load_engine（无 feature_m15 import；通过 plugin 协议加载）
│   │   ├── evaluator.py
│   │   ├── reel_strip.py
│   │   ├── rules.py
│   │   ├── symbol.py
│   │   └── feature_protocol.py  FeaturePlugin Protocol/ABC
│   ├── emitter/
│   │   ├── chunk.py
│   │   ├── round.py             只 emit_round（base round）
│   │   ├── robot.py             generic _classify_rounds（走 plugin，无字符串 hardcode）
│   │   └── driver.py            base sample_one_chunk
│   ├── tuner/                   通用 tuner 框架
│   ├── devtools/                analytic_rtp / shape_distance / 等
│   └── backend/                 virtual console FastAPI app (virtual_app / virtual_analyzer /
│                                virtual_registry) + machine_version.py
│                                (compute_code_md5(machine_name) per-machine)
│
├── machines/                    ← 每台机台一个独立目录，互不 import
│   ├── M1/
│   │   ├── spec.json
│   │   ├── reel_strips.json
│   │   ├── weights/
│   │   │   ├── mode_1/weights.json
│   │   │   └── mode_<N>/weights.json
│   │   ├── DESIGN.md            该机台设计文档（机台私有，不能 override DESIGN_PHILOSOPHY）
│   │   ├── verify.py            该机台 verify 脚本
│   │   └── (base only — 无 plugins/)
│   │
│   ├── M15/
│   │   ├── spec.json
│   │   ├── reel_strips.json
│   │   ├── weights/...
│   │   ├── DESIGN.md
│   │   ├── verify.py
│   │   └── plugins/
│   │       ├── __init__.py      暴露 build_plugin(spec, weights_doc) 工厂
│   │       ├── plugin.py        M15FeaturePlugin + build_plugin（emit_extra_rounds / classify_round）
│   │       └── feature.py       M15 accept/reject + ST=14/15 feature 子轮实现
│   │
│   ├── M37/                     同 M1（base only）
│   ├── M31/                     FeaturePlugin 机台（multiplier-wild free-spin）
│   ├── M43/                     FeaturePlugin 机台（lucky-ducky respin mini-game）
│   └── M279/                    custom-engine 机台（registry 标 _engine="m279"）
│       ├── spec.json  reel_strips.json  weights/
│       ├── DESIGN.md  verify.py
│       └── plugins/
│           ├── __init__.py      暴露 load_engine / build_plugin(→None) / sample_one_chunk /
│           │                    compute_schema_fingerprint
│           ├── m279_round.py / m279_driver.py
│           └── m279/            嵌套子包：loader / engine（M279SpinEngine 多 payline）/
│                                nudge / collect / wheel
│
├── configs/
│   └── machines_virtual.json    每台 entry 指向 machines/<M>/
│
├── scripts/                     通用工具脚本（tune.py / 等）
└── tests/                       通用测试 + plugin protocol 合约测试
```

### 2.1 文件归属判定

| 它属于哪？ | 标准 |
|---|---|
| `core/` | 跨多台机台共用，**不**能 import 任何 `machines.*`，**不**含任何机台名字面量 |
| `machines/<M>/` | 该机台私有；可以 import `core.*`，**不**能 import 其他 `machines.<other>.*` |
| `machines/<M>/plugins/` | 实现 plugin Protocol；通过 importlib + machines_virtual.json 配置加载 |

**判定例**："这段代码用 `if machine_name == 'M15'` 区分行为吗？" 是 → 属于 `machines/M15/`。"这段代码改了对其他机台有影响吗？" 是 → 属于 `core/`。

---

## §3 FeaturePlugin Protocol 契约

`core/engine/feature_protocol.py`：

```python
from typing import Protocol, runtime_checkable
from random import Random

@runtime_checkable
class FeaturePlugin(Protocol):
    """Plugin contract — feature 机台用，base 机台不需要 plugin。

    Generic engine/emitter 通过本协议调用 plugin，不认识具体机台。
    """

    # 触发 pay_id（生效前 evaluator 算出 scatter_pays，含此 id 即触发）
    trigger_pay_id: int | None

    def simulate_session(self, rng: Random, *, outcome=None) -> list:
        """运行一次 feature session，返回 round list（每个 round 是 plugin 自定义 dataclass）。

        ``outcome``: optional ``SpinOutcome`` for outcome-conditional plugins
        (``trigger_pay_id is None``); ``None`` for M15-style scatter-pay triggers.
        """
        ...

    def emit_extra_rounds(
        self, base_round: dict, feature_rounds: list, *,
        last_credits: int, spin_times: int, rtp_id: int, bet_amount: int,
    ) -> list[dict]:
        """把 feature rounds 转换成 rawdata round dict 列表（含 ST=14 / ST=15 等机台特定 SpinType）。"""
        ...

    def classify_round(
        self, round_dict: dict, next_round_dict: dict | None,
    ) -> tuple[str, int]:
        """analyzer 侧 — 输入 round dict + 下一行 dict（可能为 None）；
        输出 (feature_name, effective_win) 用于 robot 的 FeatureWin 分桶。"""
        ...
```

**核心约定**：
- Generic emitter 拿到 `feature_rounds` 列表后调 `plugin.emit_extra_rounds()`，**不**做 ST=14 / ST=15 / "TopDollar" 的 hardcode
- Generic robot `_classify_rounds` 调 `plugin.classify_round()`，**不**判断 spin_type 数字
- 没 plugin 的机台（M1 / M37）：base round 全部 classify 为 `"Normal"`，跟当前 base-only 行为一致

### 3.1 plugin 加载

约定：`machines/<machine>/plugins/__init__.py` 暴露 **`build_plugin(spec_dict, weights_doc) -> FeaturePlugin | None`** 工厂函数（不是 `PLUGIN` 顶层变量）。返回配置好的 plugin 实例；spec 不声明 feature 时返回 `None`。

`core/engine/loader.py` 的 `_load_plugin_for_machine()` 在 `load_engine` 时按 `spec["machine"]` 拼出模块路径 `slot_designer.machines.<machine>.plugins`，`importlib.import_module` 加载后调 `build_plugin`。下列任一情况 plugin 为 `None`（engine 跑 base-only，`spin_session()` 永远返回空 feature_rounds）：

- `machines/<M>/plugins/` 不存在（base-only 机台）
- 模块没有 `build_plugin` 属性
- `build_plugin` 对该 spec 返回 `None`

**不**静态 import 任何 `machines.<M>.*`。注：模块路径由 `spec["machine"]` 派生，不读 registry 字段（`machines_virtual.json` 里历史遗留的 `_plugin_module` 字段当前不被加载逻辑使用）。自定义引擎机台（如 M279）走另一条路：registry 标 `_engine` marker，plugin 模块暴露 `load_engine` / `sample_one_chunk` / `compute_schema_fingerprint`（见 §10 兑现 #4）。

---

## §4 per-machine `code_md5` 算法

`core/backend/machine_version.py` 的 `compute_code_md5(machine_name)`。Hash 输入按顺序：

1. `core/engine/**/*.py`   （核心引擎；排除 `__init__.py` / `__pycache__`）
2. `core/emitter/**/*.py`  （核心 emitter；同上排除）
3. `machines/<machine_name>/plugins/**/*.py`  （该机台私有 plugin，base 机台为空）

**注意 hash 边界只含 `engine/` + `emitter/`**，不含 `core/tuner/` / `core/devtools/` / `core/backend/` ——
所以改 tuner / devtools / backend / tests / docs / scripts / configs **不翻**任何机台 md5。翻 md5 的条件：

- 改 `core/engine/*` 或 `core/emitter/*` → 全机台 md5 翻（合理：框架引擎变更是 fleet-wide 事件）
- 改 `machines/M15/plugins/*` → 只 M15 md5 翻
- 改 `machines/M279/plugins/*` → 只 M279 md5 翻

权威实现 + 完整 docstring 见 `core/backend/machine_version.py`（`_core_source_files` / `_plugin_source_files` / `compute_code_md5`）。
**所有 callsite**（chunk stamping via `virtual_analyzer._compute_md5s` / registry refresh via `virtual_app.refresh_machines_virtual` / `scripts/tune.py`）必须通过本函数获取 code_md5，不重新实现。

---

## §5 新机台 onboarding 步骤

接前置：[DESIGN_PHILOSOPHY.md](DESIGN_PHILOSOPHY.md) 必读 + WebSearch 真原型。本节只覆盖**工程层**；数学/玩家心理层在 DESIGN_PHILOSOPHY 写。

### 5.1 起目录

```bash
mkdir -p slot_designer/machines/<M>/{weights,plugins}
mkdir slot_designer/machines/<M>/weights/mode_{1,2,5,7}
```

### 5.2 必备文件

| 文件 | 必填 | 说明 |
|---|---|---|
| `machines/<M>/spec.json` | ✓ | paytable + rules（小写 symbol 名，对齐生产 schema）|
| `machines/<M>/reel_strips.json` | ✓ | reel symbol 布局（跨 mode 字节级一致）|
| `machines/<M>/weights/mode_<N>/weights.json` | ✓ | per-stop weights，每 mode 一份 |
| `machines/<M>/BOUNDARY_CONTRACT.md` | ✓ | Stage 3.5 全 team 协商 + user sign-off 4-layer contract。drives DESIGN.md / verify.py / target.json 全部数字。template 在 `slot_designer/templates/BOUNDARY_CONTRACT_TEMPLATE.md`。详 ONBOARDING_PROCESS §5.3.5 |
| `machines/<M>/DESIGN.md` | ✓ | 该机台**设计文档**（archetype 来源 + 玩家叙事 + per-mode 数值意图，必须 trace BOUNDARY_CONTRACT.md §2）。**机台私有，不能 override DESIGN_PHILOSOPHY**|
| `machines/<M>/verify.py` | ✓ | 该机台 verify 脚本，每条红线 trace BOUNDARY_CONTRACT.md §2 某条具体 bound，引用 DESIGN_PHILOSOPHY 各 §条款 |
| `machines/<M>/plugins/__init__.py` | feature 机台才需要 | 暴露 `build_plugin(spec_dict, weights_doc) -> FeaturePlugin \| None` 工厂 |
| `machines/<M>/plugins/<*>.py` | feature 机台才需要 | plugin 实现拆模块 |

### 5.3 注册到 `machines_virtual.json`

```json
{
  "machine": "<M>sim",
  "modes": [1, 2, 5, 7],
  "available": true,
  "_source_machine": "<M>",
  "_spec_path": "slot_designer/machines/<M>/spec.json",
  "_strips_path": "slot_designer/machines/<M>/reel_strips.json",
  "_weights_path_template": "slot_designer/machines/<M>/weights/mode_{mode}/weights.json",
  "_engine": "<engine_marker>"   // 仅自定义引擎机台才填（如 M279 = "m279"）；FeaturePlugin 机台不填
}
```

`_spec_path` / `_strips_path` / `_weights_path_template` 是路径来源，`_source_machine` 标 `machines/<M>/` 目录名（md5 + plugin 解析用）。`configSummaryMd5` / `codeSummaryMd5` / `modesMd5` 由 `core/backend/virtual_registry.refresh_machines_virtual()` + `machine_version.py` 在 console boot 和每次采样前自动 refresh（不手填）。`refresh_machines_virtual` 还会扫描 weights 目录自动 union 新落盘的 mode。

### 5.4 **强制**测试（每台新机台必加）

| 文件 | 测什么 |
|---|---|
| `tests/machines/test_<M>_engine.py` | spec/strips/weights 加载成功；engine 跑 1k spin 不抛异常；产出 chunk schema 跟生产对齐 |
| `tests/machines/test_<M>_strips_invariants.py` | strip 跨 mode 字节级一致；§13 X-Blank-X 0 violations |
| `tests/machines/test_<M>_plugin_protocol.py` | plugin（如有）满足 `isinstance(PLUGIN, FeaturePlugin)`；`simulate_session` / `emit_extra_rounds` / `classify_round` 三方法存在 + 类型签名对 |
| `tests/machines/test_<M>_md5_isolation.py` | 改 `machines/<M>/plugins/*.py` 文件内容 → `compute_code_md5("<M>")` 翻、其他机台不翻 |

### 5.5 提交规范

每台机台 onboarding 至少分两 commit：

1. `feat(slot_designer/<M>): scaffold structural files` — spec/strips/weights 起步、verify 起步、plugin 骨架
2. `feat(slot_designer/<M>): tune mode 1 weights to 95% RTP` — Phase 4/5 tune 完后

---

## §6 测试规范（TDD-driven 强制）

### 6.1 改 core 必须配套测试

任何 `core/*.py` 改动 commit 必带至少一个 `tests/core/test_*.py` 的新增/修改。理由：core 改动 fleet-wide 影响，没测试 = 静默回归风险。

### 6.2 改 plugin 必须配套该机台测试

`machines/<M>/plugins/*.py` 改动必带 `tests/machines/test_<M>_*.py` 的新增/修改。

### 6.3 测试组织

```
tests/
├── core/                             ← 测 core 框架（机台无关）
│   ├── test_layout.py                目录布局 + 每台机台必备文件
│   ├── test_per_machine_code_md5.py  per-machine md5 隔离
│   ├── test_no_machine_leakage.py    ← 静态检查 core/ 不 import machines.* + 无机台名 token
│   ├── test_feature_plugin_protocol.py  FeaturePlugin Protocol 合约
│   ├── test_custom_engine_adapter.py    _engine marker 自定义引擎路径
│   └── test_end_to_end_refactor.py      4 台 fleet load + 1 chunk e2e
├── machines/                         ← 每台机台一组（test_<M>_engine / _strips_invariants /
│   │                                   _plugin_protocol / _md5_isolation，见 §5.4）
│   └── test_M31_*.py                 （新机台模板；legacy M1/M15/M37/M279 fixture 测试在 tests/ 顶层）
└── （其它通用 + 机台 fixture 测试散在 tests/ 顶层，如 test_machine_version / test_per_mode_md5 /
    test_analytic_vs_sim / test_m279 / test_virtual_* 等）
```

### 6.4 commit 工作流

每个 commit：

1. **写测试先**（新增 / 修改），跑应该失败（红）
2. **实现**，跑应该通过（绿）
3. **commit message** 必含 `## Tests added` 段写明哪些 test fn

测试不必每条全都"红 → 绿"——**修 bug 类**才需要"注入 bug → 红 → fix → 绿"证明能 catch；**新功能类**只要"先有失败假设 → 实现后通过"。

---

## §7 命名禁区

`core/` 全树（包括 source、注释、docstring、log、字符串字面量）**不允许**出现以下：

| 类别 | 禁词举例 |
|---|---|
| 机台名 | `M1`, `M15`, `M37`, `M279`, `m15sim`, `M15sim`, etc.（**注释里出现也算违反**）|
| 机台 brand 名 | `TopDollar`, `TopDollarSelector`, `TripleDouble`, etc. |
| 机台 spin_type 数字 | `ST=14`, `ST=15`, etc.（必须经 plugin / spec 配置） |
| 机台特有 symbol 名 | `topdollar`, `doublediamond`, `Diamond1` 等（symbol 名通过 spec 字符串传入） |
| 机台特有 pay_id | `pay_id=666`, `pay_id=21` 等（pay_id 通过 plugin trigger_pay_id 字段或 spec 取） |

例外：
- 在 `machines/<M>/` 树内随便用
- `core/` 里**架构层概念**（如 `FeaturePlugin`, `feature_protocol.py`）OK——这些是抽象，不是机台名
- `tests/machines/test_<M>_*.py` 自然要含机台名，没问题

**自动化 enforcement**：`tests/core/test_no_machine_leakage.py` 跑 grep 检查 `core/` 子树没 `M\d+` / `from .*machines\.` import 字符串。

---

## §8 不变量（违反 = bug）

| # | 不变量 | 失败后果 |
|---|---|---|
| 1 | `core/` 不 import 任何 `machines.*` | 改一台机台代码影响其他机台 md5 |
| 2 | `machines/<M>/` 不 import 任何 `machines.<other>.*` | 跨机台耦合 |
| 3 | `machines/<M>/plugins/` 通过 importlib 加载，不写在通用 import 链 | 静态 import 触发 `__init__` 副作用 |
| 4 | `code_md5(machine)` 是 per-machine | fleet-wide 缓存失效 |
| 5 | `machines_virtual.json` 的 `_spec_path` / `_strips_path` / `_weights_path_template` 指向 `machines/<M>/` 树（md5 / plugin 解析全走它们 + `_source_machine`）| 路径分散维护，drift |
| 6 | `core/` 任何机台名字面量出现 | 通用代码认识具体机台 |
| 7 | plugin 实现满足 `FeaturePlugin` Protocol 且通过 `tests/machines/test_<M>_plugin_protocol.py` | 静默 contract 违反 |
| 8 | 每台机台 `DESIGN.md` 不 override 全局 `DESIGN_PHILOSOPHY.md`，只 specialize | 机台私有文档篡改 universal 哲学 |

---

## §9 跨文档授权层次

```
真原型 (IGT / Aristocrat / 公开 PAR sheet)            ← 最高真理
┌── 全局层 ──────────────────────────────────────────┐
│  memory/project_slot_designer.md                   │  universal rules + cross-machine contracts
│  slot_designer/DESIGN_PHILOSOPHY.md                │  设计 first principles
│  slot_designer/ARCHITECTURE.md (本文件)             │  代码工程规范
│  slot_designer/WORKFLOW.md                         │  review 流程
└────────────────────────────────────────────────────┘
┌── 机台私有层 ──────────────────────────────────────┐
│  slot_designer/machines/<M>/DESIGN.md              │  该机台 specific 数值/叙事
│  slot_designer/machines/<M>/verify.py              │  该机台硬约束代码
└────────────────────────────────────────────────────┘
```

**机台私有层不能 override 全局层**。当两者冲突，全局层赢。

机台 DESIGN.md 写"hit_rate 12%" 但 DESIGN_PHILOSOPHY.md §4 派生规则要求"小奖 hit ↓ 中/大/顶奖 hit 不动"——以哲学为准，重写 DESIGN.md 数字。

---

## §10 重构进度

| Phase | 状态 | commit | tests added |
|---|---|---|---|
| 0a — M15 design records 删除 | ✓ | `c4d7d82` | N/A (deletion) |
| 0b — ARCHITECTURE.md 写入 | ✓ | `615591a` | N/A (docs) |
| A — `core/` + `machines/<M>/` 目录拆分 | ✓ | `aacde85` | 33 layout |
| B — per-machine `compute_code_md5` | ✓ | `ac414a7` | 13 md5 isolation |
| C — FeaturePlugin Protocol + 解 M15 耦合 | ✓ | `…` | 3 leakage + 14 protocol |
| D — Custom-engine adapter (M279) | ✓ | `39c86a0` | 9 adapter |
| E — end-to-end fleet verification | ✓ | `…` | 12 e2e |

**总计**：84 new tests across 5 implementation phases. 全部 TDD 顺序 (write test → red → implement → green → commit). Final pytest baseline:
**239 passed, 1 pre-existing M37 reroll fail** (unchanged from pre-refactor baseline).

### 重构兑现的承诺

1. **`core/` 不认识机台名**：`tests/core/test_no_machine_leakage.py` 自动验证 grep `from slot_designer\.machines\.` / `\bM\d+\b` / `\bTopDollar.*\b` / hardcoded ST=14/15 全部 0 命中。

2. **per-machine `code_md5` 隔离**：`tests/core/test_per_machine_code_md5.py` mutate machines/M15/plugins/* → 只 M15 hash 翻；mutate machines/M279/plugins/* → 只 M279 翻；mutate core/engine/* → 全机台翻；mutate tests/docs/__pycache__/configs → 全机台不翻。

3. **`FeaturePlugin` Protocol 把 feature 机台 hook 起来**：`load_engine` 通过 importlib 找 `machines/<M>/plugins/__init__.py` 的 `build_plugin`，不静态 import 任何 `slot_designer.machines.*`。

4. **Custom-engine 路径**：M279 走 `_load_custom_engine_module`，registry 用 `_engine` marker 标记，plugin module 暴露 `load_engine` / `sample_one_chunk` / `compute_schema_fingerprint`。

5. **End-to-end 验证**：4 台 fleet (M1 / M15 / M37 / M279) 每台都跑 `load_engine` + 1 chunk sampling + chunk envelope 校验，不抛异常，不串扰。
