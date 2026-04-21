# M1 rawdata field analysis

扫过 `rawdata/M1/mode_1/chunk_000*.json` 共 110k round。这份笔记是 M1 spec 的来源依据，也是未来新机台 onboarding 的模板。

## Chunk envelope

```jsonc
{
  "_cache_version": "v3",
  "_machine": "M1",
  "_mode": 1,
  "_bet": 1000,
  "_spin_times": ...,
  "_robot_count": ...,
  "_chunk_index": N,
  "_saved_at": "...",
  "_config_md5": "...",
  "_code_md5": "...",
  "_upstream_schema_fingerprint": "sha256:...",
  "_dev_sample": true/false,
  "response": [
    { "roundResult": "<JSON string>", "analysisResult": {...} },
    ...
  ]
}
```

**关键坑**：`response[i].roundResult` 是 **JSON 字符串**（serialized），不是嵌套对象。反解 `json.loads(robot["roundResult"])` 才是 round list。Emitter 要遵循这个约定。

## Round schema (M1)

每 round 17 个字段（all `SpinType: 1` for M1 mode 1）：

| 字段                     | 类型      | M1 值域 / 含义                                   |
|--------------------------|-----------|---------------------------------------------------|
| `ReMarks`                | string    | 空字符串（M1 无 bonus 链注释）                     |
| `LastCredits`            | int       | 上一 round 结束后 credits（robot state）           |
| `CostCredits`            | int       | 本 round 扣钱，M1 恒 1000                         |
| `WinCredits`             | int       | 本 round 中奖                                     |
| `BetAmount`              | int       | 下注额，M1 恒 1000                                |
| `ReelSkin`               | string    | "default" 或空                                    |
| `StopSymbolsByCol`       | list[str] | 3 cols；每 col 形如 `"top-mid-bot-"`（dash 分隔 + trailing dash） |
| `RewardLastNode`         | list[str] | 中奖时 `["<pay_id>-"]`（cherry 凯旋中 pay_id 14），不中时 `[]` |
| `PayoutByPayline`        | string    | 中奖时 `"line_id:pay_id-pay_id(pos,pos,pos,);"`（pay_id 重复两次；pos 编码见下），不中时空字符串或 `" "` |
| `PayoutGroupId`          | int       | M1 恒 0                                            |
| `PayLineGroupId`         | int       | M1 恒 0                                            |
| `PayoutIdToWinAmount`    | dict      | 中奖时 `{"pay_id_str": win_credits}`，空时 `{}`    |
| `CurJackpotStoreWin`     | int       | M1 恒 0                                            |
| `SpinType`               | int       | M1 恒 1                                            |
| `SpinTimes`              | int       | robot 分配的总 spin 数                             |
| `RTPId`                  | int       | M1 mode 1 恒 1                                    |
| `IsLackCreditsSpin`      | bool      | 恒 false（ContinueAfterBankrupt=true）             |

## Grid / payline 定位

- `StopSymbolsByCol[i]` = `"{top}-{mid}-{bot}-"`，split('-') 得 4 段（最后空）
- 位置编码（来自 `PayoutByPayline`）：`pos = (col+1)*100 + row` where `col, row` 都是 0-indexed
  - pos 100 = (col=0, row=1) = col 0 的中间行 ✓ 实测
  - pos 200 = (col=1, row=1) ✓
  - pos 300 = (col=2, row=1) ✓
- payline line_id=1 覆盖 3 cols 的 middle row

## Pay_id → 规则映射（从 rawdata 完整反推）

| pay_id | fires/110k | 规则                                        | base × | wild 行为                  |
|--------|-----------|---------------------------------------------|--------|----------------------------|
| 14     | 16030     | payline 上 1 个 Cherry                      | 1      | wild 不替代 cherry          |
| 13     | 876       | payline 上 2 个 Cherry                      | 2      | wild 不替代                 |
| 12     | 15        | payline 上 3 个 Cherry                      | 10     | wild 不替代                 |
| 2      | 2         | payline 全 Diamond1 (纯 wild2x)             | 500    | N/A                        |
| 3      | 6         | payline 2D1+1D2 或 1D1+2D2 (group pay)      | 240/360 | N/A                       |
| 4      | 0 观测    | payline 全 Diamond2 (grand jackpot)         | 1000   | `rtp_excluded`，不期望出现  |
| 5      | 27        | 3× Seven2（wild 替代+乘数叠加）             | 50     | 允许                        |
| 6      | 120       | 3× Seven1                                   | 40     | 允许                        |
| 7      | 181       | 3× Bar3                                     | 20     | 允许                        |
| 8      | 317       | 3× Bar2                                     | 15     | 允许                        |
| 9      | 609       | 3× Bar1                                     | 10     | 允许                        |
| 10     | 99        | 3 个 Seven 混搭（≥1 个 Seven1 + ≥1 个 Seven2）| 25     | 允许                       |
| 11     | 4255      | 3 个 Bar 混搭（任意 Bar 组合，不全同）       | 5      | 允许                        |

## Wild 替代 + 乘数叠加（精确机制验证）

取 pay_id 9 (3 Bar1) 为例：

| payline                          | 乘数计算       | 预期 | 观测 |
|----------------------------------|----------------|------|------|
| Bar1, Bar1, Bar1                 | 10             | 10x  | ✓    |
| Bar1, Bar1, Diamond1 (wild2x)    | 10 × 2         | 20x  | ✓    |
| Bar1, Bar1, Diamond2 (wild3x)    | 10 × 3         | 30x  | ✓    |
| Bar1, Diamond1, Diamond1         | 10 × 2 × 2     | 40x  | ✓    |
| Bar1, Diamond2, Diamond2         | 10 × 3 × 3     | 90x  | ✓    |
| Bar1, Diamond1, Diamond2         | 10 × 2 × 3     | 60x  | ✓    |

**结论**：wild 替代成任意普通/7/bar 符号，并且每个参与的 wild 把最终乘数**乘法叠加**。

Diamond1 = wild2x，Diamond2 = wild3x。

## Cherry 独占优先级

观察样本：`(Cherry, Diamond1, Diamond1)` 触发 pay_id 14 (1 Cherry = 1×)，**不是** pay_id 2 (全 wild = 500×)。

→ 只要 payline 存在任意数量 Cherry，wild 的替代/乘数**全部失效**，严格触发 cherry_count pay。

Evaluation order: cherry_count → pure_wild → pure_wild_group → line_3_same → line_3_group。

## Wild 替代的"最优选择"

观察 `(Bar1, Bar1, Bar2)` 无 wild → 触发 pay_id 11 (mixed bars = 5×)。不会有 wild 替代成 3 Bar1 的路径。

但 `(Bar1, Bar1, Diamond1)` → 触发 pay_id 9 (3 Bar1 × wild2x = 20×)，而不是 pay_id 11 (mixed × wild2x = 10×)。

→ 当 wild 在场且有多种替代方案，engine 选**最终 win 最大**的路径（标准 slot 引擎行为）。

## 未观测但预留的 case

- pay_id 4 (3 Diamond2 grand jackpot): 0/110k 观测。策划文档明确"不通过普通 spin 产生"，spec 里标 `rtp_excluded: true`。按权重算 P ≈ 9.7e-7 / spin → 100 万 spin 预期 1 次；如真跑出来，分析 report 不应计入 RTP。
- pay_id 0 / 1 / 15+: 数据里完全不出现。保留 gap。

## 对未来新机台的启示

1. **不信任 md，只信任 rawdata**。md 可能有 typo 或混合不同 mode 的数值。
2. **先扫 pay_id → 典型中奖 payline → 倍率**，建 "pay_id 清单"。M1 只用了 1-3 个 chunk 就够。
3. **wild 行为**靠"clean 3-of-a-kind 的 WinCredits" vs "带 wild 的 WinCredits" 比例反推 wild 乘数。
4. **Cherry-like 独占机制**靠找 (special_sym, wild, wild) 这种 test case，看触发哪个 pay。
5. 把反推结论都写进 `tests/fixtures/M{N}_field_analysis.md`，便于 review。
