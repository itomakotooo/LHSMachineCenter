# 第一个机台的完整制作流程（以 M1 为例）

此文档 walk-through M1 机台从零到 rawdata-deliverable 的完整路径，既是
M1 的 how-we-did-it 记录，也是未来新机台的 onboarding 模板。

## 核心契约

**输入**（策划 / 上游给）：
1. **机台规则**（`机台规则 + 赔率表`）：paytable md 文档 + 任何特殊机制描述
   （wild 替代规则、cherry 优先级、grand jackpot 排除等）
2. **reel 表**（`reel表`）：初始权重表（每 reel 的 stop 列表 + 权重）
3. **真实 rawdata**：从上游 API 采集的 `rawdata/<machine>/mode_<N>/chunk_*.json`

**输出**（我产出给你）：
- **rawdata chunks**（primary deliverable）：格式和上游 API 完全一致，
  项目现有 `player_impact_analyzer --from-cache` 直接吃
- intermediate：spec + tuned weights + tune report（可检查，非交付物）

**两种 workflow 共享 rawdata 输出契约**：
- **模式 A: "程序员"** — 按给定 reel 表实现机台，验证 rawdata 正确
- **模式 B: "数值策划"** — 加一个 target profile，输出调参后 rawdata，
  和真机产出交叉对比择优

---

## 工作流程（4 阶段，约 30 分钟 wall time）

### 阶段 1 — 理解机台（手工，~10 分钟）

1. **读策划 md**：理解 symbol 集合、pay 规则、特殊机制
2. **扫 rawdata**：用 `python -c "..."` 抽 pay_id → (middle payline symbols, win)，
   验证策划 md（注意：md 可能有笔误，数据为准）
3. **手写 spec**（我来做）：`slot_designer/specs/<M>.spec.json`
   - 声明式规则：symbols / pays / evaluation_order / spin_types
   - 参考 `specs/schema.md` 的 DSL 规范
4. **记录反推笔记**：`tests/fixtures/<M>_field_analysis.md` 保存观察到的
   每个 pay_id 的规则和你发现的笔误，便于将来 review

M1 实例：见 [tests/fixtures/M1_field_analysis.md](tests/fixtures/M1_field_analysis.md)。
md 说 3 Bar1=20× 实际 10×、3 Bar3=10× 实际 20×（笔误）。

### 阶段 2 — 结构化 reel 表（自动）

**工具**：把策划给的 reel 配置（常见格式：表格 reel1/weight1/reel2/weight2/reel3/weight3）
转成 `weights/<MACHINE>/mode_<N>/reel_weights.json`。

M1 实例：36 stops × 3 reels，sum=1010 per reel。见
[weights/M1/mode_1/reel_weights.json](weights/M1/mode_1/reel_weights.json)。

### 阶段 3 — 验证机台实现正确（模式 A 终点）

```bash
python -m slot_designer.scripts.verify \
  --spec slot_designer/specs/M1.spec.json \
  --weights slot_designer/weights/M1/mode_1/reel_weights.json \
  --ref-summary dev_reports/M1/mode_1/versions/<latest>/player_impact_summary.json
```

流程：my simulator 跑 N spin → 格式化为 rawdata → 丢给现有 analyzer →
对比真 report。如果 RTP / bucket / per-pay_id hit 都在 CI 内吻合，
**机台实现正确**。至此模式 A 交付。

### 阶段 4 — 按目标调参（模式 B）

输入：target profile（从参考机台抽取），例：M14 mode 1
```bash
python -m slot_designer.tuner.target_profile \
  --summary dev_reports/M14/mode_1/versions/<latest>/player_impact_summary.json \
  --out slot_designer/tuner/targets/M14_mode1.target.json \
  --label "M14_mode1"
```

然后跑两阶段调参（**推荐一条命令**）：
```bash
python -m slot_designer.scripts.tune \
  --spec slot_designer/specs/M1.spec.json \
  --base-weights slot_designer/weights/M1/mode_1/reel_weights.json \
  --target slot_designer/tuner/targets/M14_mode1.target.json \
  --out-weights slot_designer/weights/M1/mode_1/reel_weights.json \
  --out-report slot_designer/weights/M1/mode_1/TUNE_REPORT.md \
  --evaluations 1500 --restarts 3 --sa-steps 3000 --emit-chunks 110
```

内部分两阶段：

- **Phase 4 — count tuning (hard 约束)**：(1+1)-ES 在 27 维 (symbol ×
  reel) count space 搜索。cost = `(ΔRTP/0.5pp)² + JS(bucket_shape) ×
  100 + (ΔCV/0.1)² × 0.3`。RTP + shape 命中。
- **Phase 5 — order tuning (体验约束)**：simulated annealing 在 permutation
  space 调 stop 顺序。保留 Phase 4 marginals（RTP/bucket 不变）。cost
  综合 near-miss 带宽 + PWDF 底线 + blank-adjacency 奖励。

输出**automatically**：
- `weights/<M>_mode<N>.tuned.json` (**primary release artifact** — 这个
  才是交给 console 的；虚拟 console 下次 refresh 会自动更新 md5)
- `out/<M>_tune_report.md` (Phase 4 + Phase 5 diff 表)
- `_dev_scratch/rawdata/<M>sim/mode_<N>/chunk_*.json` (dev scratch，
  供开发自己用 `analyzer --from-cache` 交叉验证 RTP/CV 数值；**不是**
  console 的数据入口)

### 阶段 5 — 打开虚拟机 console 管理（Phase 6 添加）

Release 流程（dev → console）：
1. `tune.py` 产出 tuned weights 到 `weights/<M>_mode<N>.tuned.json`
   和 dev-scratch rawdata 到 `slot_designer/_dev_scratch/rawdata/...`
2. 虚拟 console 下次 refresh-md5（启动/手动）时自动算出新的
   `configSummaryMd5`，写入 `machines_virtual.json`
3. Operator 在虚拟 console 里点 **开始采样** → `virtual_analyzer.py`
   按新 md5 产出 chunk 到 `slot_designer/rawdata/<M>sim/mode_<N>/`
   （这是 console 的 rawdata 入口，dev 脚本不碰）

启动虚拟 console（port 8878，和真 console 8877 **完全独立的实例**）：
```powershell
powershell -ExecutionPolicy Bypass -File slot_designer/scripts/start_virtual_console.ps1 -OpenBrowser
```

浏览器会打开 http://127.0.0.1:8878/console/  —— **和真机 console 完全
一样的 UI**，因为用的是同一份 `create_app()`，只是注入了虚拟 console
的独立路径（slot_designer/{rawdata,reports,state,configs/machines_virtual.json}）。

在虚拟 console 里**和操作真机台完全一致**：
- 机台目录 / 机台过滤器 → 能看到 `M1sim`
- "开始采样" → 自动调 **virtual_analyzer** 跑我的 simulator（而不是
  HTTP 上游），产新 chunks 按 md5 `append` 到 `slot_designer/rawdata/
  M1sim/mode_<N>/`（新装机或 refresh 后 rawdata 池是空的，operator
  首次采样就把它填上；之后 md5 变了再采，新旧版 chunk 自动按 md5
  分 kept/historical，不互相覆盖）
- rawdata 管理 → 看到对应的 spin / chunks / kept/deletable/historical 分组
- "⟳ 生成 Report" → 用现有 analyzer 分析虚拟 rawdata，产出标准报告
- mode 选择 / 目标 CI 精度 / spin 次数等采样参数 → 全部支持
- 批量采样 / 批量生成报告 → 全部支持
- 报告对比 / 加载 / 删除 / LLM 解读 → 全部支持

**数据隔离**：
- 真 console 的 `rawdata/` 和虚拟 console 的 `slot_designer/rawdata/`
  互不干扰 —— 两个 console 可以同时开，两个 tab。
- Dev 侧 `simulate.py` / `tune.py` 的产出在 `slot_designer/_dev_scratch/
  rawdata/` 下，**不进** console 的数据池。想清理直接 rm 整个
  `_dev_scratch/` 即可；console 那边的 rawdata 由 console 自己的
  一键清理 / per-version DELETE 管。

### 阶段 6 — 和真机交叉对比（择优录取）

真机 console（8877）里加载真 M1 的 report；虚拟 console（8878）里加载
M1sim 的 report。两个 console 的指标画像并排比较，按你的设计目标择优。

这一步**不改任何代码** —— 就是用两个 console 各自的标准"对比"功能。

### 阶段 7 — 离线 CLI 验证（可选）

如果不想开 console，也可以直接命令行跑 analyzer：
```bash
python fresh_slotlab/player_impact_analyzer.py \
  --machine M1sim --rtp-mode 1 \
  --from-cache slot_designer/_dev_scratch/rawdata/M1sim/mode_1 \
  --output-dir slot_designer/out/M1sim_offline_report \
  --target-halfwidth-pp 0.001 --max-chunks 9999
```

---

## M1 实测结果

**模式 B 完整 pipeline**（110k rounds sim / 1.1M chunk 产出）：

| 指标 | baseline（原 reel 表） | Phase 4 tuned | Phase 5 tuned | M14 target |
|---|---|---|---|---|
| RTP | 76.93% | 93.50% | 93.50% | 93.49% |
| CV (σ/RTP) | 9.16 | 4.94 | 4.94 | 4.94 |
| JS shape | 0.033 | 0.016 | 0.016 | — |
| blank_adj (HV) | 1.00 | 1.00 | 0.80 (capped) | — |
| PWDF (avg) | ~20 | 24 | 23 | — |

**rawdata 端到端（分析器真跑）**：RTP 93.60% (CI ±0.89pp)，和 target
在 1pp 内。

---

## 哪些地方要每次 onboard 新机台时重做

1. ✍️ 手写 spec (机台特有规则)
2. ✍️ 手写 field analysis 笔记（反推你从 rawdata 看到什么）
3. 📥 导入策划给的 reel 表
4. 📋 抽 target profile（如果要模式 B）
5. 🏃 跑 tune
6. 🔍 和真机对比

无需改动的部分：
- engine（泛用，按 spec 驱动）
- emitter（rawdata schema 泛用）
- analytic / shape_distance / experience metrics（纯 math）
- tuner loop（无机台特化）

**特殊机制扩展点**：机台有 bonus chain / collect mechanic / wheel 这些新
feature 时，需要扩 `engine/features/`（每类 feature 一个插件）+ spec DSL
`features` 字段。M1 不触及，M272+ 会触及。

---

## 研究参考（按 memory feedback，每次重搜）

Phase 5 体验指标的设计依据（2026-04-20 搜索）：
- Harrigan K. (2009) "Slot Machines: Pursuing Responsible Gaming Practices
  for Virtual Reels and Near Misses" — clustering 技术 / 1989 Nevada 裁决
- Lucas & Singh (2008) — CV 反相关 time-on-device
- Muir R. (2013) "Elements of Slot Design" — σ 闭式 / PAR sheet 实例
- 2020 near-miss review — 效应有争议，不过度优化

**重要**：不要只看这些笔记，每次开发都用 WebSearch 重新查一遍最新资料。
