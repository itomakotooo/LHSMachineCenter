# 给策划的 Slot Console 使用指南

> 这份文档讲**策划怎么用 Slot Console 验证 MachineConfig 改动**。重点是迭代闭环:**改 cfg → 拉数据 → 看报告 → 再改 cfg**。
>
> 工程细节(API / 内部架构 / 高级故障排查)在 [CONSOLE_OPERATIONS.md](CONSOLE_OPERATIONS.md)、[API_REFERENCE.md](API_REFERENCE.md)、[REPORT_SPEC.md](REPORT_SPEC.md)。

---

## 1. 它能干嘛

把你在 MachineBuilder 那侧导出的 `<M>Cfg.txt`(整机 JSON config)塞进 console,自动跑大量 spin 采样,然后给你出一份**玩家体验报告**:RTP / 命中率 / 倍数分布 / 破产曲线 / 各 pay_id 命中频率 / feature 表现 / etc.

典型用法:
- 改完 reel weights,想看玩家感受怎么变
- 这版 cfg 跟上一版比 RTP 漂了多少、漂到哪个 pay_id 头上
- top jackpot 是不是出得太多/太少
- 玩家进 feature 的频率合理吗
- 这版 cfg 玩家破产速度是不是变了

---

## 2. 准备工作(每台机器一次)

### 2.1 装环境

1. Python ≥ 3.10(命令行 `python --version` 看一下)
2. clone 这个 repo 到本地
3. **首次启动** 双击 `start.bat /install`(自动 pip install 依赖 + 启动 console)
4. 之后启动直接双击 `start.bat`

注:必须在 **LHS 内网**(console 后端拉 `192.168.10.21:15060` 的采样接口)。

### 2.2 跑通第一次

console 起来后浏览器自动打开 `http://127.0.0.1:8877/console/`。

第一次先验证能拉到数据:随便选一台已有的机台(比如 `M14`)、mode `1`、直接点 **开始采样**。等几分钟出第一份 report。看到 KPI / chart 填上数字就说明环境 OK。

---

## 3. 迭代主流程 ⭐

这是策划日常工作流。一次完整闭环:

```
┌──────────────────────────────────────────────────────────────┐
│  ① MachineBuilder 里改 weights / paytable / reel strips      │
└─────────────────────┬────────────────────────────────────────┘
                      ↓ 导出整机 Cfg.txt
┌──────────────────────────────────────────────────────────────┐
│  ② 把 <M>Cfg.txt 放到 repo 根的 machineconfig/ 目录           │
│     文件名严格 = <underlying>Cfg.txt                          │
│       M15 → M15Cfg.txt                                       │
│       M273 (含 variant)→ M273Cfg.txt(不带 variant 后缀)    │
└─────────────────────┬────────────────────────────────────────┘
                      ↓ console 自动检测
┌──────────────────────────────────────────────────────────────┐
│  ③ UI 选这台机台 → 参数 panel 自动出现 ☑ 使用本地 cfg          │
│     (没出现 = 文件名拼错 / 还没切到这台机台,试着刷新页面)    │
└─────────────────────┬────────────────────────────────────────┘
                      ↓ 勾上 → 点开始采样
┌──────────────────────────────────────────────────────────────┐
│  ④ console 走你这份本地 cfg 拉上游采样                        │
│     chunks 自动标记成单独的 md5 bucket                       │
│     ⇒ 不污染服务端默认 cfg 的 baseline                       │
└─────────────────────┬────────────────────────────────────────┘
                      ↓ 采完(几分钟到十几分钟)
┌──────────────────────────────────────────────────────────────┐
│  ⑤ Report 面板同时显示两套数据:                              │
│     ├ "服务端默认"        — 原 cfg baseline                  │
│     └ "本地 cfg (M15Cfg.txt)"  — 你这版                      │
│     同图对比 RTP / hit / bucket / 破产曲线 / pay_id 频率     │
└──────────────────────────────────────────────────────────────┘
```

**迭代完想拆掉:** 把 `machineconfig/<M>Cfg.txt` 删了或改名 → checkbox 自动隐藏 → 下次采样回服务端默认 cfg。

**改 cfg 又想试一版:** 直接覆盖 `machineconfig/<M>Cfg.txt`(文件名不变)→ md5 变 → 旧 chunks 自动归为 historical bucket(不参与新统计但留 disk,md5 只是分类 tag、不触发删除),新 chunks 重新采。**不需要清缓存**。

---

## 4. 看报告时该重点看什么

每次跑完按这个优先级扫:

### 4.1 KPI cards(顶部)
- **RTP %** — 目标 hit 了吗?(95% / 300% / 500% / 85% 因 mode 而异)
- **Hit Rate %** — 命中率合理吗?
- **Volatility / CV** — 波动性符合机台 character 吗?
- **Tail Dep** — 大奖比例阶梯(≥10/20/50/100x)合理吗?
- **rtpClampWarning** — 如果出现红字,说明 collect 机制把 RTP 截断了,通常意味着 paytable 设计 RTP 超过了 mode 上限。

### 4.2 Multiplier Bucket Chart
11 个赢分桶(`gt0_lt1`, `ge1_lt5`, ..., `ge5000`)。看分布形状是不是预期 — 大头在哪个桶、长尾合不合理。

### 4.3 Pay ID drilldown
每个 pay_id 的命中频率 + RTP 贡献占比。**核心检查项**:你改的那条 weight / paytable line 对应的 pay_id,变化方向跟预期一致吗?

### 4.4 Symbols by column / Paylines
看具体 symbol 在每条 reel 出现的频率、各 payline 中奖分布,排查权重失衡。

### 4.5 Feature 面板(只对有 bonus 的机台)
- **Upstream feature breakdown** — feature 触发率 + 每次触发的平均收益
- **Bonus chain dynamics** — chain 长度分布、retrigger 率、能量曲线

### 4.6 Bankruptcy curve
玩家破产概率 vs 投注轮数。你改动后玩家破产速度变了吗?

### 4.7 模型解读(可选)
Report 出来后可以点 **生成解读** 按钮触发 LLM 解释(支持 gemini / gpt / claude,需要在 UI 输 API key)。当数字一堆但不知道怎么用人话总结时有用。

---

## 5. 采样参数(基本不用动)

默认配置已经过验证,日常用直接默认就行:

| 参数 | 默认 | 啥时候改 |
|---|---|---|
| `target_halfwidth_pp` | 0.5pp | 想跑快一点出粗略结果调到 1.0 / 2.0;想跑细到 0.2(但会慢很多) |
| `chunk_spin_times` | 5000 | 一般不动 |
| `chunk_robot_count` | 24 | 一般不动;吞吐压力大时调小 |
| `batch_concurrency` | 2 | 一般不动 |
| `max_chunks` | 120 | 跑得久但不收敛时手动调大 |

如果不确定调多少 → 点 **Auto Tune Parallelism** 让系统自动测一组好参数。

Mode 2 / 5(super-lucky / mega-lucky)CI 锁定 fuzzy 模式,不需要调收敛精度。

---

## 6. 常见情况

**Q: "使用本地 cfg" checkbox 不出现**
- 检查 `machineconfig/<M>Cfg.txt` 文件名拼写大小写。M15 必须叫 `M15Cfg.txt`,不是 `m15cfg.txt` / `M15.txt` / `M15_cfg.txt`。
- 切换机台时如果还没刷新,试着刷新页面或点 **刷新机台 MD5** 按钮。
- 确认文件**直接在** `machineconfig/` 下,不能嵌套子目录。

**Q: 跑完 KPI 全空 / NaN / 异常**
- 上面有 `rtpClampWarning` 红字 → paytable 设计 RTP 超 mode 上限,collect 截断。
- 看 `chunk N ✗ stale` 大量 → 上游 schema 变了,cached 数据解析不了。删 cache 重采。

**Q: 想丢掉这次实验,从头来**
- Fleet Management → 找到这个 run → 删除 report;或在 **Chunk Cache** panel 清掉对应 cache。
- cleanup 会要求确认 risk tier(low / medium / high)防止误删。

**Q: 想跟上一版本对比**
- Report 面板的版本下拉切换。每次采样自动版本化保留 history。
- 在 "**Fleet Management**" tab 可以看完整 run 历史。

**Q: 跑到一半要停**
- 点 **停止**(■)。会 graceful cancel — 已采完的 chunks 保留(status 变 `cancelled`),summary 仍可看,interpretation 也能跑(LLM 能基于不完整数据给出评论)。

**Q: code 改了想重新算 report 但不想重采**
- analyzer 改动后,受影响机台的旧 report 会按 per-(机台, mode) 的版本被标成"过期"(report 行上的 **⚠ 过期** 角标 + 顶部 "{n} 个 report 的 analyzer 版本已过期" 提示条),只标不删——旧 report 一直在,直到你主动重生成。
- 在机台目录选中机台 → 点 **批量生成 Report**(⟳)从已 cache 的 raw chunks 重新过 analyzer 出新 report;或对一批过期 report 点 **一键重生成**。不需要重采上游。

---

## 7. 进一步阅读

| 文档 | 看啥 |
|---|---|
| [CONSOLE_OPERATIONS.md](CONSOLE_OPERATIONS.md) | 完整操作流程、auto tune、cache 管理、安全互锁、recovery |
| [REPORT_SPEC.md](REPORT_SPEC.md) | Report 字段 schema 详解 — 每个指标怎么算 |
| [API_REFERENCE.md](API_REFERENCE.md) | REST API ref(给开发) |

如果遇到工具坑 / 数据问题 / 上游接口异常 → 找仓库 owner。
