机器编号：M37

Payline：1 条

一、基本规则

老虎机共有3个纵向转轮（Reel），沿唯一一条 Payline 判定结果。每个转轮停止后显示一个标签（Symbol）。当 Payline 上的3个标签出现特定组合时，根据当前下注额（bet）获得对应倍率的奖励。

二、标签类型与功能

游戏包含以下标签：

1. Bar标签
   包含3种不同标签：bar1、bar2、bar3。
   - 三个相同Bar标签（bar1+bar1+bar1、bar2+bar2+bar2、bar3+bar3+bar3）按对应倍率赢钱。
   - 任意三个Bar标签混合（包括 bar1/bar2/bar3 之间的任意组合，以及包含 bar7 的混合）按“任意Bar”倍率赢钱。

2. 7标签
   包含两种：high7、bar7。
   - 三个 high7 按“3个 high7”倍率赢钱。
   - 三个 bar7 按“3个 bar7”倍率赢钱。
   - 任意三个7标签混合（high7 与 bar7 任意组合）按“任意7”倍率赢钱。

3. Wild标签
   本机包含五种 Wild 标签：wild1x、wild2x、wild5x、wild10x、wild100x。名称后的“x”以及数字代表该 Wild 的倍率乘数（例如 wild1x 表示 ×1）。
   - 位置限制：
        - wild1x 只会在 Reel 1 和 Reel 3 上出现。
        - wild2x、wild5x、wild10x、wild100x 只会在 Reel 2 上出现。
   - 替代功能（通用）：Wild 可以替代除 Blank 之外的任意标签（即 bar1/bar2/bar3/high7/bar7）。当 Wild 参与替代并形成赢钱组合时，最终倍率 = 基础倍率 × 所有参与替代的 Wild 倍率连乘。
   - 单Wild规则：当 Payline 上恰好只有一个 Wild 标签时，系统计算所有可能的赢钱方式：
        * 方式A（单Wild直接奖励）：bet × 该 Wild 倍率。
        * 方式B（替代后形成常规组合）：按上述替代功能计算（Wild 替代后与另两个标签形成最高基础倍率的组合，并乘以该 Wild 倍率）。
        * 取较高值作为最终奖励。
   - 两个Wild规则：当 Payline 上恰好有两个 Wild 标签（第三个位置不是 Wild）时：
        * 若第三个位置是 Blank：奖励 = bet × (Wild1倍率 × Wild2倍率)（此即两Wild直接相乘，无需替代）。
        * 若第三个位置是有效标签（非 Blank 且非 Wild）：系统计算以下两种方式并取较高值：
            - 方式A（替代组合）：将两个 Wild 替代成与第三个标签能形成的最高基础倍率的常规组合，并按替代功能计算最终倍率 = 基础倍率 × Wild1倍率 × Wild2倍率。
            - 方式B（两Wild直接相乘）：奖励 = bet × (Wild1倍率 × Wild2倍率)。
   - 三个Wild组合（Jackpot）：当三个转轮均为 Wild 时（Reel1和Reel3必定是 wild1x，Reel2 为 wild2x/wild5x/wild10x 之一），触发对应等级的 Jackpot，奖励固定如下（不适用替代规则）：
        - 若 Reel2 为 wild2x → Mini Jackpot，奖励 = bet × 20
        - 若 Reel2 为 wild5x → Minor Jackpot，奖励 = bet × 50
        - 若 Reel2 为 wild10x → Major Jackpot，奖励 = bet × 100
        - **Grand Jackpot 不通过 3-wild 路径触发** —— `(wild1x, wild100x, wild1x)` 中间行被服务端 reroll-blocked（实测 2.14M 轮 0 命中）。Grand 1000× 顶奖通过 `(high7|wild1x, wild100x, high7|wild1x)` 替代路径触发：3个 high7 基础 10× × wild100x 的 100× = 1000×。设计意图：让顶奖路径走 high7 anchor "有 narrative"（差一个 high7 的 near-miss 心理），而不是廉价的 3-wild 直达。
   - 限制：Wild 不能替代 Blank。

4. Blank标签
   仅作为填充标签，无赢钱倍率。本机默认存在。

三、Jackpot 成长机制

- 每次常规转动（Spin）后，系统会为 Mini、Minor、Major 三个 Jackpot 的奖励倍数增加一定数值（具体增加规则不在此文档列出）。Grand Jackpot 不参与此增长。
- 当某个 Jackpot 被触发时（即三个 Wild 对应中间值），玩家获得该 Jackpot 当前的奖励倍数（初始值分别为：Mini 20倍、Minor 50倍、Major 100倍）。Mini/Minor/Major 会随时间增长。
- 触发后，该 Jackpot 的倍数重置为初始值，然后继续随 Spin 增长。
- **数值设计层面**：Jackpot 增长机制忽略不计（实际量级远低于 base 派奖，对 RTP 影响 < 0.1pp）。Slot designer 各 mode RTP target 的计算、tune 收敛 + verify 都用基础 Jackpot 倍数（Mini=20 / Minor=50 / Major=100），不考虑增长 delta。

四、赢钱倍率表（基础倍率，不含 Jackpot）

组合：3个 high7，倍率：10
组合：3个 bar7，倍率：6
组合：3个 bar1，倍率：5
组合：3个 bar2，倍率：4
组合：3个 bar3，倍率：3
组合：任意7（high7 和 bar7 混合），倍率：2
组合：任意Bar（bar1/bar2/bar3/bar7 混合），倍率：1

注：其他未列出的组合（如两个相同加一个不同等）若无 Wild 参与则无奖励。

五、最终奖励计算

- 最高奖励优先原则：对于任何一次转动，系统计算所有可能的赢钱方式（包括单Wild直接奖励、两Wild相乘、替代组合（含Wild倍率乘法）、三个Wild Jackpot奖励），并选择奖励最高的一种进行派奖。