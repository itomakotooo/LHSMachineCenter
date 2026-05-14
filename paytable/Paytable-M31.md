机器编号：M31

Payline：5 条（3 条直线 + 2 条 V 形对角线）

一、基本规则

老虎机共有 3 个纵向转轮（Reel），每个转轮停止后显示 3 行（共 3 × 3 = 9 格网格）。系统沿 5 条 Payline 判定结果，每条 Payline 由 3 个标签构成。当 Payline 上的 3 个标签出现特定组合时，根据当前下注额（bet）获得对应倍率的奖励。同一次转动中多条 Payline 可同时中奖，奖励累加。

Payline 几何：

- 第 1 条：中间一行（col0 mid, col1 mid, col2 mid）
- 第 2 条：顶部一行（col0 top, col1 top, col2 top）
- 第 3 条：底部一行（col0 bot, col1 bot, col2 bot）
- 第 4 条：V 形向下对角线（col0 top, col1 mid, col2 bot）
- 第 5 条：V 形向上对角线（col0 bot, col1 mid, col2 top）

二、标签类型与功能

游戏包含以下 6 类标签：

1 类：Bar 标签
   包含 3 种：1bar、2bar、3bar。三者按等级递增。
   - 三个相同 Bar 标签按对应倍率赢钱（详见倍率表）。
   - 不支持"任意 Bar 混合"组合赢钱。

2 类：Bell 标签
   包含 1 种：bell（中等等级）。三个相同 Bell 按对应倍率赢钱。

3 类：High7 标签
   包含 1 种：high7（最高等级普通符号）。三个相同 High7 按对应倍率赢钱。

4 类：Wild 标签（共 4 种，含倍率）
   本机包含四种 Wild 标签：Wild2x、Wild3x、Wild5x、Wild10x。名称后的"x"以及数字代表该 Wild 的倍率乘数（如 Wild5x = ×5）。

   - 替代功能：Wild 可以替代除 Scatter 和 Blank 之外的任意标签（即 1bar / 2bar / 3bar / bell / high7）。
   - 倍率加成（Tier A 走加成）：当 Wild 作为替代标签参与形成普通符号赢钱组合时，最终倍率 = 基础倍率 × 该 Payline 上所有 Wild 倍率连乘。
     示例：1bar + Wild10x + Wild2x（在某条 Payline 上）
     先按"3 个 1bar"获得基础倍率 0.1 倍，再乘以 Wild10x（×10）和 Wild2x（×2），最终倍率 = 0.1 × 10 × 2 = 2 倍。
   - 纯 Wild 组合（Tier B）：当一条 Payline 上 3 个标签全部为 Wild 时，触发独立的固定倍率奖励（详见倍率表 Tier B），**Wild 倍率乘法不再生效**，固定金额。
     示例：Wild2x + Wild2x + Wild3x（任意 Payline，全部为 Wild）
     按 Tier B 规则匹配为"含 Wild2x + Wild3x 组合"，固定 0.6 倍，**不**乘以 (2 × 2 × 3) = 12。
   - 不能替代 Scatter 或 Blank。

5 类：Scatter 标签
   - 触发功能：在 3 × 3 网格的任意位置出现 3 个 Scatter（不限 Payline、不限 Reel），即触发 FreeSpin Feature。
   - Wild 不能替代 Scatter：必须真实出现 3 个 Scatter 才触发，wild 顶替无效。
   - 派奖：同时给 5 倍 bet 的固定 Scatter 奖励（与触发 Feature 并行，可与 Payline 普通赢钱叠加）。
   - 频率：在 base 转动中约 6.1% 每停每位置；约每 132 次付费转动触发一次 Feature。

6 类：Blank 标签
   仅作为填充标签，无赢钱倍率。本机默认存在。

三、双层 win 评估系统

M31 采用 Tier A + Tier B 双层评估，对每条 Payline 独立判断：

- Tier B 优先：若该 Payline 上 3 个标签全部为 Wild → 按 Tier B 固定倍率派奖，Wild 倍率乘法不参与。
- Tier A 次之：若该 Payline 上包含至少一个普通符号 → 按 Tier A 普通符号倍率（含 Wild 替代 + 倍率乘法）派奖。
- 同一条 Payline 不会同时触发 Tier A 和 Tier B；但不同 Payline 可以分别是不同 Tier（例如某次转动中 Payline 1 是 Tier B 纯 Wild、Payline 2 是 Tier A 三 bell）。

四、赢钱倍率表（按 Payline 计算，每条满足的 Payline 独立派奖）

Tier A — 普通符号组合（基础倍率，Wild 替代时再乘以 Wild 倍率连乘）

| 组合 | 基础倍率（×bet） |
|---|---|
| 3 个 high7 | 1.6 |
| 3 个 bell | 1.2 |
| 3 个 3bar | 0.6 |
| 3 个 2bar | 0.2 |
| 3 个 1bar | 0.1 |

注：未列出的混合组合（如 1bar + 2bar + 3bar、bell + high7 + 1bar 等）若无 Wild 完成替代则无奖励。

Tier B — 纯 Wild 组合（固定倍率，不乘以 Wild 倍率）

| 组合 | 固定倍率（×bet） |
|---|---|
| 3 个 Wild5x | 30 |
| 3 个 Wild3x | 15 |
| 3 个 Wild2x | 5 |
| 任意 3 Wild 中含 Wild10x（含 3 个 Wild10x） | 10 |
| 任意 3 Wild 中含 Wild5x、不含 Wild10x、非 3-同色 | 3 |
| 任意 3 Wild 仅由 Wild2x + Wild3x 组成、非 3-同色 | 0.6 |

注：Tier B 组合按上表自顶向下匹配（先看是否 3 同色，再看是否含 Wild10x，再看是否含 Wild5x，最后归 Wild2x+Wild3x）。

Scatter 组合（任意位置，不走 Payline）

| 组合 | 倍率（×bet） | 附加效果 |
|---|---|---|
| 网格中任意位置出现 3 个 Scatter | 5 | 触发 FreeSpin Feature（7 次免费转动）|

五、FreeSpin Feature

1. 触发方式：base 转动中网格内任意位置出现 3 个 Scatter（不限 Payline、不限位置、Wild 不能替代）。
2. 转数：固定 7 次免费转动，无 retrigger 机制（FreeSpin 中不会再出现 Scatter，因此无法在 Feature 中再次触发）。
3. 转轮替换（reel set switch）：FreeSpin 期间使用专用的 freespin 转轮组，跟 base 转轮不同：
   - **中央列（Reel 2）：100% Wild** —— 不会出现 blank 或任何普通符号。每次停止必定是 Wild2x / Wild3x / Wild5x / Wild10x 之一。Reel 2 上的 Wild 分布大致为 Wild2x ≈ 47.7%、Wild3x ≈ 21.2%、Wild5x ≈ 14.6%、Wild10x ≈ 16.5%。
   - **两侧列（Reel 1 / Reel 3）**：混合普通符号 + 高密度 Wild。Wild 出现频率比 base 高 3-8 倍。**不含 Scatter**（因此 FreeSpin 中无法 retrigger）。
4. 评估规则：FreeSpin 与 base 完全一致 —— 同 5 条 Payline、同 Tier A / Tier B 评估、同倍率表。Reel 组成不同导致 Wild 命中密集，hit rate 大幅提升（base 约 13%、FreeSpin 约 38%）。
5. 退出条件：7 次 FreeSpin 全部转完后自动返回 base 游戏。
6. 结算归属：FreeSpin 期间所有赢钱累加到触发它的 base 付费转动上（按"付费回合（paid round）"为单位计算 RTP，FreeSpin 不单独计 spin 数）。
7. Feature RTP 贡献：FreeSpin 占总 RTP 约 40%（即真机 92.6% 总 RTP 中约 37 pp 来自 FreeSpin）。

六、最终奖励计算

每次转动按以下顺序计算：

1. 检测 Scatter：若网格中出现 ≥3 个 Scatter，发放固定 5×bet Scatter 奖励 + 触发 FreeSpin（7 次免费转动入队）。
2. 对每条 Payline（1-5）独立评估：
   - 若 3 个标签全 Wild → 按 Tier B 表匹配，固定倍率派奖。
   - 否则若可形成普通符号组合（含 Wild 替代）→ 按 Tier A 表派奖，并乘以该 Payline 上 Wild 倍率连乘。
   - 若无可形成组合 → 该 Payline 不派奖。
3. 累加所有 Payline 奖励 + Scatter 奖励 = 本次转动总奖励。
4. 触发的 FreeSpin 在 base 转动结算完后依次执行，每一次 FreeSpin 重复上述评估，所有 FreeSpin 奖励归到触发的那一 base 付费转动。

注：真机最大观测单次付费回合总奖励约 160×bet（典型来源：Tier A high7 基础 1.6 × Wild10x × Wild10x = 160），符合"lifetime-tier"顶奖叙事（Tier B 顶奖 3-Wild5x 30 倍密度更高、但单次绝对值不及 Tier A + 双 Wild10x 乘倍）。
