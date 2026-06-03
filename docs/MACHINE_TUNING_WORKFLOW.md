# 机台真机调优工作流程 (Real-Machine Tuning Workflow)

> 给 agent(我自己)冷启动用的**纯流程**文档:改本地配置 → 打表 → 真机采样 → 出报表 → 分析 → 迭代,全程我端到端驱动。
> 与机台无关。具体机台的目标/约束由 user 在 session 里给。

---

## 0. 前提 / 环境

- **必须连内网 VPN**(采样接口在内网)。开工前先做连通性 smoke(§5),别假设通。
- 工具:`node`(打表)、`python ≥3.10`(采样/分析)。
- 打表工具链在仓库内:`Buffalo/`(同级目录可能也有一份)。
- **全程用 PowerShell 工具**:worktree 里 Bash 被一个坏掉的 `PreToolUse:Bash` hook(`verify-commit-msg.py` 路径不存在)挡住。
- 关键目录(相对仓库根):
  - 配置源(Excel):`Buffalo/Assets/Config/Excel/Machine/<M>/`
  - 打表产物:`Buffalo/Assets/Config/output/<M>Cfg.txt`
  - 订阅区(采样读这):`machineconfig/<M>Cfg.txt`
  - analyzer:`fresh_slotlab/player_impact_analyzer.py`
  - server 列表:`configs/servers.json`
  - rawdata 缓存:`rawdata/<M>/mode_<n>/`,报表:`reports/<M>/mode_<n>/versions/`

---

## 1. 先理解机台(动手前必做)

先打一次表(§3)、订阅(§4),然后解析 `machineconfig/<M>Cfg.txt`(整机 JSON)。用 python 逐块 dump,看清:

- `_excel` 各表:`<M>{Reel, Symbol, Payline, Basic}.xlsx` + 机台特有表
- **paytable**:`<M>Cfg.payout`(组合)× `<M>Cfg.rewards`(倍率,注意单位——常见 `Ratio÷100=bet 倍数`,用实测 avg_win 反推确认)
- **reel 权重**:`_excel.<M>Reel`,通常按 **skin** 分组,每 skin 各 reel 一组 `(symbol, weight)`
- **feature/小游戏**:如 respin 的 `<M>Cfg.WinSpin`(触发概率表、链长、用哪套 skin)
- **RTP 控制**:`RTPCfg`(`RTPDecision` 决策树 / `RTPNodes` 目标带 / lucky·jackpot 节点)
- **模式 ↔ skin/RTP-tier 的映射**:**每台机不一样,必须当场确认,不要假设**(可能 mode=skin 1:1,也可能控制器在多 skin 间混合)。

> ⚠ **不要从配置纸面推算结果**。见 §7「权重≠实测」——这类机有 strip 排布 + 引擎处理,纸面模型不可信,一切以采样为准。

---

## 2. 可改 / 不可改(tunable surface)

默认边界(**每台机开工时跟 user 确认一次**):

- ✅ **可改**:reel 权重(各 skin 的 weight 值)、feature 触发(如 respin 概率/链长)、小游戏(feature)内的倍率与权重(可**新建**专用 skin 让某 skin 指过去)。
- ❌ **不可改**:reel **排布本身**(每条 reel 上有哪些 symbol、按什么顺序排——只能改 weight 值,不动 symbol 构成/顺序;weight 别设 0)、`RTPDecision` 决策树。
- RTP 目标节点是否属于 user 域:**先用探针确认 RTP 是不是权重驱动**(§7),据此决定是自己调权重还是请 user 改目标节点。

---

## 3. 打表(build)

源在 Excel;**真正的改动改 Excel + 打表(canonical)**,只改 weight 值不动排布。
(快速探针可直接改 `machineconfig/<M>Cfg.txt` 的 `_excel.<M>Reel` JSON,跳过打表——见 §7,仅限一次性诊断。)

```powershell
# 1) 防撞:把任何文件名中含 ".xlsx." 的备份隔离(build 会把它们也编进去 → 灌错数据)
powershell -ExecutionPolicy Bypass -File Buffalo\BuildKit\quarantine_xlsx_backups.ps1
# 2) 打表(纯本地、不联网、不碰 Unity)。node 用绝对路径即可,cwd 无所谓
node "<repo>\Buffalo\BuildKit\js\menu.js" -once make.point.machine.cfg <M>
#    → 产出 Buffalo\Assets\Config\output\<M>Cfg.txt
```

校验:`Get-Content output\<M>Cfg.txt -Raw | ConvertFrom-Json | Out-Null`(JSON 合法)。
打表是**确定性**的:用未改的 Excel 重打,sha256 应与原产物一致(可作为 build 链自检)。

---

## 4. 订阅 / "上传"

"上传"**不是往服务器 push** —— cfg 作为每条 spin 请求的 `MachineConfig` 覆盖字段发出去。把产物落到订阅区即可:

```powershell
Copy-Item Buffalo\Assets\Config\output\<M>Cfg.txt machineconfig\<M>Cfg.txt   # 首次订阅
# 之后重打后刷新已订阅的:
powershell -ExecutionPolicy Bypass -File Buffalo\BuildKit\sync_built_configs.ps1
```

---

## 5. 采样(真机)

先算 localcfg md5(让 chunks 按本地 cfg 单独分桶,不污染服务端 baseline):

```powershell
python -c "import hashlib,pathlib; c=pathlib.Path('machineconfig/<M>Cfg.txt').read_text(encoding='utf-8'); print('localcfg_'+hashlib.sha1(c.encode('utf-8')).hexdigest()[:8])"
```

**连通性 smoke**(开大跑前必做,几秒~几十秒;0 spin/超时 = VPN/endpoint 没通):

```powershell
$env:PYTHONPATH = "<repo>"
python fresh_slotlab\player_impact_analyzer.py --machine <M> --rtp-mode <n> `
  --machine-config-file machineconfig\<M>Cfg.txt --upstream-config-md5 localcfg_<hash> `
  --endpoint-url http://192.168.10.21:15060/MachineTest/MultiRobotTestSpinVariant `
  --chunk-spin-times 1000 --chunk-robot-count 10 --batch-concurrency 1 `
  --max-chunks 1 --timeout 90 --disable-non-convergence-abort `
  --chunk-cache-dir <temp_dir> --output-dir <temp_report>
```

**正式采样**(后台跑,完成会通知):

```powershell
python fresh_slotlab\player_impact_analyzer.py --machine <M> --rtp-mode <n> `
  --machine-config-file machineconfig\<M>Cfg.txt --upstream-config-md5 localcfg_<hash> `
  --endpoint-url http://192.168.10.21:15060/MachineTest/MultiRobotTestSpinVariant `
  --chunk-spin-times 5000 --chunk-robot-count 20 --batch-concurrency 2 `
  --max-chunks <N> --target-halfwidth-pp 0.5 --timeout 300 --disable-non-convergence-abort `
  --chunk-cache-dir <chunk_dir> --output-dir <report_dir>
```

- **粗采**(定方向):`--max-chunks 4`(~40 万 spin,几分钟,RTP CI ±~2pp,够看趋势/分布形状)。
- **细采**(终验):`--max-chunks 40+`(收到 ~0.5pp / 2M+ spin)。
- endpoint 从 `configs/servers.json` 选(intranet `127.0.0.1` / dev `192.168.10.21` 默认 / prod);非默认就显式传 `--endpoint-url`。
- `--upstream-machine-name <key>` 仅 variant 机台需要(非 variant 不传)。
- 节流:per-source 有限流,默认 robot=20/conc=2 别乱探并发,免得自我 DoS。

> ⚠ **chunk-cache-dir 陷阱**:指向**已有 chunk 的目录**会从 `chunk_0001` 起**覆盖**!→ 每个 config 用**独立/临时** chunk 目录(探针/迭代尤其);要在已有缓存上追加用 `--resume-from-cache <mode_dir>`。

---

## 6. 出报表 + 分析

analyzer 自动写 `<report_dir>/player_impact_summary.json` + `player_impact_report.md`。用小 python 脚本提取关键维度:

- `rtp.point_pct` + `ci95_interval_pct`;`sampling.{total_spins, session_level_halfwidth_pp}`
- `player_impact.hit_and_payout.{win_hit_rate, zero_win_rate, avg_win_when_hit_x}`
- `player_impact.volatility.{return_bucket_rate, std_return_x, max_observed_return_x}`
- `player_impact.multiplier_profile.buckets`(每档 `spin_rate / rtp_contribution_pp / win_share`)
- `player_impact.payout_ids_top20` / `spin_type_breakdown`(base vs feature 的 RTP 拆分)
- `player_impact.symbols_by_column_top10`(每列窗口符号率 → blank/near-miss)
- `player_impact.bankruptcy_simulation` / `rtp_integrity_check`

**自检(必做)**:`rtp_integrity_check.passed==true` 且 `our_total_win==server_total_win`;`sum(spin_type win)`、`sum(pay_id win)` 要对得上总 win。对不上先查归属/分母,别下结论。

---

## 7. 迭代方法论(核心)⭐

这类机有 RTP 控制器 + strip 排布,**纸面推算不可信**,必须靠实测闭环:

1. **权重 ≠ 实测分布**:reel weight 经 strip/引擎转换后,实测分布跟 weight 可能差几十个百分点。**永远以采样为准**,别信手算/枚举。
2. **诊断探针(binary/灵敏度问题先问真机)**:不确定"杠杆 X 动不动指标 Y"或结构性问题(RTP 是权重驱动还是被控制器钉死?)时,做一个**极端 / 单变量**改动 → 粗采 → 一眼看答案,**再开始精调**。比黑盒反推快 10×(参见 memory `feedback_diagnostic_reel_pattern`)。
3. **保留 baseline 数据点**:每次改动都跟 baseline 比,用 delta 校准这个杠杆的灵敏度。
4. **粗采→细采**:粗采定方向(快、便宜),只在终验时细采到 0.5pp。
5. **尽量单变量**:一次主要动一个东西,改动可归因;多变量同改只适合回答"动不动"的 binary 问题。
6. **改前后对照**:改 reel 时常用非对称(各 reel weight 不同)做 near-miss 等效果——这是改 weight,不算改排布。
7. **对抗式自评 + 交叉一致性**:宣布"达标"前 dump 真实数字、跑一致性自检、自问"user 第一个会质疑什么",过了再交付(memory `feedback_adversarial_self_review`)。

---

## 8. 常见坑速查

- worktree Bash 被坏 hook 挡 → 用 PowerShell。
- 打表前没跑 quarantine → `.xlsx.` 中缀备份被编进去灌错数据。
- `--chunk-cache-dir` 撞已有 chunk → 从 0001 覆盖;用独立/临时目录或 `--resume-from-cache`。
- 没传 `--upstream-config-md5 localcfg_<hash>` → chunks 落错桶 / 报表 md5 stamp 错。
- 拿纸面权重当实测信 → 必踩;一切采样为准。
- 这条 loop **合法地**对新 config 重采(新 md5 无缓存)——是 memory `feedback_no_proactive_fetch`「dev 走缓存」的明确例外。

---

## 9. 一次完整迭代的节奏

```
(理解机台 §1) → 改 weight/feature §2-3 → 打表 §3 → 订阅 §4
   → [首轮] 连通 smoke §5 → 诊断探针(粗采)§5,§7.2 → 读结果校准 §6
   → 精调 → 粗采 → 对照目标 → 再精调 …(收敛)
   → 终验:改 Excel 走 canonical 打表 → 细采到 0.5pp §5 → 逐条对验收指标 + 自检 §6-7
```
