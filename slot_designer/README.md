# slot_designer

虚拟老虎机框架 — **设计 / 调音 / 模拟新机台 + 跑虚拟 console** 的代码库，跟生产 analyzer (`fresh_slotlab/`) + web console (`src/web_console/`) 隔离。

虚拟 console 跑在 8878 端口（生产 console 8877），数据自带 `slot_designer/{rawdata,reports,state,configs}/`，可以跟生产 console 同时启动做并排对比。

---

## 必读文档

| 文件 | 写啥 | 什么时候读 |
|---|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 代码层布局、Plugin 协议、per-machine md5、新机台 onboarding 工程步骤、命名禁区、不变量 | 第一次接触本目录 / 新机台 / 改 core/ / 改 md5 |
| [`ONBOARDING_PROCESS.md`](ONBOARDING_PROCESS.md) | 新机台 onboarding 全流程：slot-* 6-agent team 分工 + 11-stage 工作流 + Stage 3.5 Boundary Contract + 收敛/stop 条件 | 新机台 onboarding（开 session 第一步）|
| [`DESIGN_PHILOSOPHY.md`](DESIGN_PHILOSOPHY.md) | slot 设计 first principles（家族倒金字塔 / brand visibility / CV-RTP / pareto trap / reel asymmetry / PWDF / blank flank / visual rhythm）| 设计任何机台前 |
| [`WORKFLOW.md`](WORKFLOW.md) | 每次 commit 前 adversarial self-review 5 步流程 | 每次提交前 |
| [`SPEC_SCHEMA.md`](SPEC_SCHEMA.md) | spec DSL 字段定义 | 写 / 改 spec.json 时 |

新机台 onboarding 工程步骤见 [ARCHITECTURE.md §5](ARCHITECTURE.md#5-新机台-onboarding-步骤)；完整团队 + stage 流程见 [`ONBOARDING_PROCESS.md`](ONBOARDING_PROCESS.md)。

---

## 目录布局

```
slot_designer/
├── core/                    ← 通用框架，不认识具体机台
│   ├── engine/              SpinEngine + FeaturePlugin Protocol + evaluator + rules + symbol + reel_strip + loader
│   ├── emitter/             chunk + round + robot + driver (机台无关)
│   ├── tuner/               通用调音框架 + targets/
│   ├── devtools/            analytic_rtp + player_experience + shape_distance + weight_diff
│   └── backend/             虚拟 console FastAPI app + per-machine md5 计算 + registry refresh
│
├── machines/                ← 每台机一个独立目录，互不 import
│   ├── M1/                  spec.json + reel_strips.json + weights/mode_<N>/ + DESIGN.md  (base only)
│   ├── M15/                 + plugins/ — Top Dollar Feature Play (FeaturePlugin)
│   ├── M37/                 (base only)
│   ├── M31/                 + plugins/ — multiplier-wild free-spin (FeaturePlugin)
│   ├── M43/                 + plugins/ — lucky-ducky respin mini-game (FeaturePlugin)
│   └── M279/                + plugins/ — 自定义引擎（多 payline + 收集 + nudge stack + wheel）
│
├── configs/
│   ├── machines_virtual.json   ← 虚拟机台 registry，含 _spec_path / _strips_path / _weights_path_template / 可选 _engine
│   └── paytables_virtual/
│
├── tests/
│   ├── core/                ← 跨机台框架测试 (TDD baseline)
│   │   ├── test_layout.py
│   │   ├── test_per_machine_code_md5.py
│   │   ├── test_no_machine_leakage.py
│   │   ├── test_feature_plugin_protocol.py
│   │   ├── test_custom_engine_adapter.py
│   │   └── test_end_to_end_refactor.py
│   └── test_*.py            ← 其他通用 + 机台 fixture 测试
│
├── scripts/                 通用工具 (tune.py / verify.py / simulate.py 等) + machine-private wrapper 脚本
└── ARCHITECTURE.md / DESIGN_PHILOSOPHY.md / WORKFLOW.md / SPEC_SCHEMA.md
```

---

## 启动虚拟 console

项目根目录：

```bat
start_virtual.bat              REM 8878 端口，自动开浏览器
start_virtual.bat /install     REM 先 pip install 依赖
start_virtual.bat /port 8879   REM 自定义端口
```

直接命令：

```powershell
powershell -File slot_designer/scripts/start_virtual_console.ps1 -OpenBrowser
```

实际跑的是 `python -m uvicorn slot_designer.core.backend.virtual_app:app`。

---

## 最小可工作流（已注册机台）

1. 启动虚拟 console (`start_virtual.bat`) → 浏览器打开 `http://127.0.0.1:8878/console/`
2. 选机台 (M1sim / M15sim / M37sim / M31sim / M43sim / M279sim) + 选 mode (1/2/5/7；M31sim / M43sim 当前仅 mode 1)
3. **开始采样** → 调 `core/backend/virtual_analyzer.py` (subprocess) → 走 `core/emitter/driver.sample_one_chunk` 或自定义引擎 adapter → 写 chunk 到 `slot_designer/rawdata/<M>sim/mode_<N>/`
4. **生成 Report** → 委托给 `fresh_slotlab/player_impact_analyzer.py --from-cache` → 输出 `slot_designer/reports/<M>sim/mode_<N>/`
5. 浏览器看分析结果（RTP / bucket / hit / 跨 mode 对比 / etc.）

---

## RTP / 数值约束 (跨机台契约)

| Mode | Total RTP | 严格度 |
|---|---|---|
| 1 | 95% | ±1pp |
| 2 | 300% | ±10-20pp |
| 5 | 500% | ±10-20pp |
| 7 | 85% | ±1pp |

详见 [DESIGN_PHILOSOPHY.md §4-§9](DESIGN_PHILOSOPHY.md) (per-tier hit / CV / archetype / mode-pair monotonicity).

---

## 跟生产 analyzer 的对接

虚拟机台 chunk 输出严格对齐生产 rawdata schema:
- `roundResult` = JSON-encoded 字符串列表 (per round 17-key dict)
- `analysisResult` = JSON-encoded 字符串，inner = `{TotalWin, FeatureWin, SummaryWin}` 各自也是 JSON 字符串 (双层 encode)
- chunk envelope = `{_machine, _mode, _config_md5, _code_md5, _schema_fingerprint, response}`

→ `player_impact_analyzer.py --from-cache <chunks>` 直接吃，不用改 analyzer 一行。

---

## 不变量（架构红线，由 [`tests/core/`](tests/core/) 自动守住）

1. `core/` 不 import 任何 `slot_designer.machines.*` (静态)
2. `core/` 源码不含机台名 token (`M\d+` / `TopDollar` / hardcoded `ST=14/15`)
3. `compute_code_md5(machine_name)` 是 per-machine —— 改 `machines/M15/plugins/` 只 M15 hash 翻
4. `machines/<M>/` 不 import 其他 `machines.<other>/`
5. 每台 feature 机台的 plugin 满足 [`FeaturePlugin` Protocol](core/engine/feature_protocol.py)
6. 每台机台 `DESIGN.md` 不 override 全局 `DESIGN_PHILOSOPHY.md`，只 specialize

违反任何一条 → `pytest slot_designer/tests/core/` 红，commit 卡住。
