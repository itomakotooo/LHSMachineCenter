# MachineTest / TestSpin 使用说明

本文档说明 GM 工程中 **单机台表测试** 接口 `POST /MachineTest/TestSpin` 的用途、请求与响应字段，以及与服务端逻辑的对应关系。实现入口见 `MachineTestController`、`MachineTestService`、`MachineTestModel`。

---

## 接口概览

| 项目 | 说明 |
|------|------|
| **路径** | `POST /MachineTest/TestSpin` |
| **控制器** | `MachineTestController`（路由 `[Route("[controller]")]`，故前缀为 `MachineTest`） |
| **请求体** | JSON，反序列化为 `MachineTestRequest` |
| **响应体** | JSON，`MachineTestResponse` |
| **CORS** | 使用策略 `GMPolicy` |
| **Base URL** | 随部署变化；**本地断点调试** 常用 `http://127.0.0.1:1111`（以你本机 GM 监听端口为准）。 |

服务端会为每次调用创建一个 **机器人玩家**（`PlayerModel`，`IsRobot = true`，`Level = 100`），在虚拟机台上执行最多 `SpinTimes` 次 Spin 循环，并汇总每轮结果与统计分析。

### 权限（GM 中间件）

除登录、版本等白名单路径外，`AuthMiddleware` 会校验 **Query** 参数 `token`，并在 Mongo `GMPermission` 中为该用户配置的路由列表里包含 **完整路径**（例如 `/MachineTest/TestSpin`）才会进入后续管道。未通过校验时可能出现 **200 且响应体为空** 等现象。详见 `GM/Middlewares/AuthMiddleware.cs`。

---

## 请求体：`MachineTestRequest`

### 资金与下注

| 字段 | 类型 | 说明 |
|------|------|------|
| `InitCredits` | `decimal` | 初始筹码（总可用额度经 `ConvertMore` / `MoreCredits` 处理）。 |
| `InitCreditsStr` | `string` | 可选。若非空，会 **覆盖** `InitCredits`：按 `InvariantCulture` 解析，支持千分位与科学计数法（`AllowThousands` \| `AllowExponent`）。 |
| `BetOrigin` | `long` | 下注策略中的「基准下注额」，具体含义见 `BetStrategy`。 |
| `BetOriginStr` | `string` | 可选，非空时解析为 `long` 后覆盖 `BetOrigin`，规则同上的数字格式。 |
| `BetStrategy` | `int` | 下注策略枚举值（与 `BetStrategy` 枚举一致）：`0` = `FixBet`，`1` = `Alternating`，`2` = `HalfHalf`。 |
| `StrategyParam` | `long` | 与 `Alternating`、`HalfHalf` 策略配合的第二档下注额。 |
| `StrategyParamStr` | `string` | 可选，非空时解析为 `long` 后覆盖 `StrategyParam`。 |

**下注策略行为**（每次 Spin 结束后会重新计算下一轮的 `bet`）：

- **FixBet (0)**：每轮下注恒为 `BetOrigin`。
- **Alternating (1)**：`CalculateBet` 的第三个参数为「当前已完成的 Spin 计数」`spinTimes`。循环开始前先用 `spinTimes == 0` 算首轮下注 → `BetOrigin`。每轮结束后用新的 `spinTimes` 算下一轮：`spinTimes % 2 == 0` 时为 `BetOrigin`，否则为 `StrategyParam`。因此实际顺序为：第 1 轮 `BetOrigin`，第 2 轮 `StrategyParam`，第 3 轮 `BetOrigin`，依此类推。
- **HalfHalf (2)**：前半段 `spinTimes < SpinTimes / 2` 用 `BetOrigin`，后半段用 `StrategyParam`。
- **其他整数值**：回退为每轮使用 `BetOrigin`。

### 机台与 RTP

| 字段 | 类型 | 说明 |
|------|------|------|
| `MachineName` | `string` | 机台名称，用于创建 `SpinMachine` 与持久化数据加载等。 |
| `MachineConfig` | `string` | 可选。非空时为 JSON 字符串，解析为 `JObject` 作为该机台的配置覆盖；为空则使用全局配置 `GetCfgJObject()`。 |
| `RtpId` | `int` | 传入 `SpinRequest.RTPId`，参与 RTP 树/策略选择。 |

### Spin 次数与行为开关

| 字段 | 类型 | 说明 |
|------|------|------|
| `SpinTimes` | `int` | 目标 Spin 循环次数上限（while 条件为 `spinTimes < SpinTimes`）。 |
| `ShouldTestLuckyGame` | `bool` | 传入 `SpinRequest.ShouldTestLuckyGame`，用于 Lucky Game 相关逻辑。 |
| `ContinueAfterBankrupt` | `bool` | 为 `false` 时，若当前筹码不足以支付本轮 `bet`，**直接结束**循环；为 `true` 时仍会继续计数并 Spin（实际扣费为 0，详见下方「余额不足」）。 |
| `ResetPlayerStateAfterEachSpin` | `bool` | 是否在**每次 Spin 循环开始前**将玩家状态重置为首轮前快照（`Credits` / `MoreCredits` / `Level` / `Exp` / `MoreExp`）。默认 `false`（不重置）。 |

### 其他字段（与本接口关系）

| 字段 | 说明 |
|------|------|
| `TestTime` | 主要在 **批量 RTP 测试**（`GenerateMachineTestRequests`）里用于标记第几次重复试验；单独调用 `TestSpin` 时通常不必设置。 |
| `RobotCount` / `OutputAllRobotResult` | 用于 `POST /MachineTest/MultiRobotTestSpin`，不是单接口 `TestSpin` 的必需字段。 |

---

## 执行流程要点

1. **虚拟机台**：`SpinFactory.CreateSpinMachine(MachineName, config, ...)`，`MachineEntranceType.Normal`。
2. **持久化数据**：`MachineService.TestCheckAndGetPersistData`；若 `MachineName` 为勋章机（`MachineService.MedalsMachineName`），会强制使用 `MedalsDataModel` 列表。
3. **循环**：每轮构造 `SpinRequest`、根据当前 `SpinType` 插入 `NormalSpinInput` / `LockReSpinInput` 等，调用 `virtualMachine.Spin`。
   - 若 `ResetPlayerStateAfterEachSpin == true`，在每轮开始前会先把机器人玩家恢复到首轮前状态，再执行余额校验与 Spin；适合做“每轮独立样本”测试。
4. **异常**：若 `Spin` 抛错，会 **回滚本轮**（`spinTimes` 与 `allCostBet` 回退，机器人状态恢复为本轮前快照），并 **重试同一轮**。
5. **余额不足**：当 `ContinueAfterBankrupt == true` 且筹码不足时，本轮 `trueCostBet` 为 0，`NormalSpinTestRoundResponse.CostCredits` 会被置为 0；`IsLackCreditsSpin` 标记为 true。
6. **Feature 统计**：若单次 `Spin` 产生多于一个 `OutputsList` 元素，`TriggerFeatureCount` 递增；`FeatureTotalWinRatio` 等统计基于多段输出汇总。
7. **结果解析**：每段输出通过 `MachineTestResultParserFactory.GetMachineTestResultParser` 生成具体的 `MachineTestRoundResponseBase` 子类（各机台玩法不同，字段不同）。

---

## 响应体：`MachineTestResponse`

| 字段 | 说明 |
|------|------|
| `RoundResponses` | 每轮（含 Feature 内多段）的解析结果列表，类型为各机台对应的 `MachineTestRoundResponseBase` 派生类。 |
| `RoundResult` | 只读属性：将 `RoundResponses` 序列化为 JSON 字符串。 |
| `AnalysisResponse` | `MachineTestAnalysisResult`，内含按赔付倍率分桶的统计。 |
| `AnalysisResponse.TotalWin` / `FeatureWin` / `SummaryWin` | 三个 **字符串** 属性，内容为 JSON 序列化后的字典结构（便于前端或脚本二次解析）。 |
| `AnalysisResult` | 整个 `AnalysisResponse` 对象的 JSON 字符串。 |
| `PayoutIdToWinRatio` | 针对主游戏第一段 Normal 输出的 `PayoutId -> win/bet 比值` 累加（用于分布分析）。 |
| `Robot` | 测试结束后的机器人 `PlayerModel`（含最终筹码等）。 |
| `AllCostBet` | 累计实际消耗下注（余额不足时为 0 的那几轮不计入消耗）。 |
| `StandardDev` | 以「赢额/下注」为样本，在 `SpinTimes` 上的标准差（用于波动评估）。 |
| `FeatureTotalWinRatio` | 与 Feature 相关的赢额比统计累加。 |
| `TriggerFeatureCount` | 触发「多段输出」Spin 的次数。 |

---

## 本地断点调试（`127.0.0.1:1111`）

启动本机 GM 并确认监听 **1111** 后，可用下列请求命中 `TestSpin`（与线上一致，仅 Host 改为本地）。

**完整 URL**：`http://127.0.0.1:1111/MachineTest/TestSpin`

**HTTP 示例**（权限需在 Query 带 `token`，与 `AuthMiddleware` 一致）：

```http
POST /MachineTest/TestSpin?token=你的token HTTP/1.1
Host: 127.0.0.1:1111
Content-Type: application/json
Accept: */*

{"MachineName":"M15","InitCreditsStr":"100000000","BetStrategy":0,"BetOriginStr":"1000","SpinTimes":10,"RtpId":0,"ShouldTestLuckyGame":false,"ContinueAfterBankrupt":true,"ResetPlayerStateAfterEachSpin":false}
```

**curl**（建议 body 放文件，避免 PowerShell 转义问题）：

```bash
curl.exe -X POST "http://127.0.0.1:1111/MachineTest/TestSpin?token=你的token" -H "Content-Type: application/json" --data-binary "@body.json"
```

---

## 调用示例（JSON）

```json
{
  "InitCreditsStr": "1000000",
  "BetStrategy": 0,
  "BetOriginStr": "1000",
  "SpinTimes": 1000,
  "RtpId": 0,
  "MachineName": "M123YourMachine",
  "ShouldTestLuckyGame": false,
  "ContinueAfterBankrupt": false,
  "ResetPlayerStateAfterEachSpin": false
}
```

交替下注示例（前半 `BetOrigin`，后半 `StrategyParam` 请改用 `BetStrategy`: 2；奇偶交替请用 `BetStrategy`: 1 并设置 `StrategyParam`）。

---

## 相关接口（同一控制器）

| 路径 | 说明 |
|------|------|
| `POST /MachineTest/MultiRobotTestSpin` | 同一 `MachineTestRequest`，按 `RobotCount` 多次独立 `TestSpin`；可按 `OutputAllRobotResult` 精简中间机器人的 `RoundResponses`。 |
| `POST /MachineTest/RTPTest` | 批量机台 RTP 测试；过程中会缓存每台最后一次 `TestSpin` 结果。 |
| `POST /MachineTest/HistoryTestResult?machineName=...` | 读取 **最近一次 RTP 批量测试** 中为该机台缓存的结果；与单独调用 `TestSpin` 无自动关联。 |
| `POST /MachineTest/MachineConfigMd5` | 返回 `cfg.json` 中 `_machineConfigMd5` 的完整值（`JToken` 原样输出）。 |

### `MachineConfigMd5` 请求示例

- 路径：`POST /MachineTest/MachineConfigMd5`
- 请求体：无
- 返回：`cfg.json` 的 `_machineConfigMd5` 节点（按服务当前加载配置返回）

```http
POST /MachineTest/MachineConfigMd5?token=你的token HTTP/1.1
Host: 127.0.0.1:1111
Accept: application/json
Content-Length: 0
```

---

## 代码索引

- 路由与入参预处理：`Server/GM/MachineTest/MachineTestController.cs`
- 核心逻辑：`Server/GM/MachineTest/MachineTestService.cs`（`TestSpin`）
- 请求/响应模型：`Server/GM/MachineTest/MachineTestModel.cs`
- 下注策略枚举：`Server/GM/MachineTest/MachineTestDefine.cs`
- 下注计算：`Server/GM/MachineTest/MachineTestBetStrategy/*`
- GM 鉴权中间件：`GM/Middlewares/AuthMiddleware.cs`
