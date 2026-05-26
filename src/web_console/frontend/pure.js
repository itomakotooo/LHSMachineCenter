// Pure-logic module: no DOM, no fetch, no localStorage.
// Browser-friendly via window.PURE; Node-friendly via module.exports.
// Tested by tests/frontend/pure.test.cjs.
//
// Everything is wrapped in an IIFE so the top-level const declarations
// (I18N, fmt, fNum, fInt, fRate, fBytes, cacheRiskTier, cacheRiskView,
// statusText, modelWarnings, collectSystemWarnings) do NOT pollute the
// global binding scope shared by classic <script> tags -- otherwise
// app.js would get a SyntaxError for any binding it wants to re-declare
// (e.g. `const { fNum } = PURE`).

(function () {
"use strict";

const I18N = {
  zh: {
    appTitle: "老虎机控制台",
    subtitle: "机台调试、指标分析与版本管理",
    languageLabel: "语言",
    healthChecking: "检查中...",
    healthOk: "API 正常",
    healthFail: "API 异常",
    tabDebug: "调试机台",
    tabManage: "机台管理",
    panelRunConfig: "运行参数",
    panelModelConfig: "模型配置",
    panelRunControl: "运行控制",
    panelProgress: "当前运行进度",
    panelLoadedMachine: "当前载入机台",
    freshnessAnalyzer: "Analyzer",
    freshnessRawdata: "Rawdata",
    freshnessFresh: "✓ 当前",
    freshnessStale: "⚠ 过期",
    freshnessUntagged: "· 未标记",
    panelKpi: "关键指标",
    panelBuckets: "倍率分布",
    thBucket: "倍率区间",
    thSpinCount: "次数",
    thSpinRate: "出现率",
    panelCharts: "图形分析",
    panelBankruptcy: "破产分析",
    panelInterpretation: "模型解读",
    panelEvents: "运行事件",
    panelMachineCatalog: "机台目录",
    panelRunHistory: "运行历史",
    panelReportVersions: "报告版本",
    panelCache: "Chunk 缓存",
    panelSystemState: "系统状态与恢复",
    labelMachine: "机台",
    labelMode: "RTP Mode",
    labelCiTarget: "目标 CI 半宽",
    ciOption05: "0.5 pp (高精度)",
    ciOption1: "1.0 pp (标准)",
    ciOption2: "2.0 pp (快速)",
    ciOption5: "5.0 pp (探索)",
    ciOptionFuzzy: "模糊 (高波动 mode)",
    helpCiTargetFuzzy: "模糊档：跳过 CI 停止条件，直接按约 100 万 spin 采样，用于 mode 2/5 这类 RTP 爆炸的特殊机制。",
    placeholderAutotuneFill: "由压测自动填充",
    validateConcurrencyRequired: "请填写每 Chunk 机器人数和批并发数（或点「一键压测并调参」获得机台实测推荐值）。",
    validateMode25RequireFuzzy: "mode 2 和 5 必须使用模糊档位（CI 半宽 = 模糊）。",
    labelAdvancedParams: "高级参数",
    bankMultStandard: "标准 (10x / 100x / 200x / 500x) — 推荐",
    bankMultShort: "短会话 (10x / 50x / 100x / 200x)",
    bankMultLong: "长会话 (10x / 200x / 500x / 1000x)",
    helpBankMultiplierWarn: "仅「标准」档位与 guideline rules 里的 x100/x200/x500 阈值对齐；切换到其他档位时破产相关的 A5 规则不会触发。",
    runStatusLabel: "状态",
    runFailedLabel: "上次失败原因",
    runCancelledLabel: "上次结果",
    runCancelledText: "已取消",
    runFailureNoneCaptured: "未捕获到诊断信息（analyzer 未输出 stderr/stdout）",
    runEventNone: "无最新事件",
    runEventStarted: "已提交 · machine={machine} mode={mode} 目标={target}",
    runEventStartedFuzzy: "已提交 · machine={machine} mode={mode} 目标=模糊（约 100 万 spin）",
    runEventChunk: "chunk {idx}/{max} · 总 spins={spins} · RTP={rtp}% · CI={ci}pp",
    runEventChunkFuzzy: "chunk {idx} · 总 spins={spins} · RTP={rtp}% · 模糊采样进度 {pct}%",
    runEventCompleted: "已完成 · 总 spins={spins} · RTP={rtp}% · CI={ci}pp · {sec}s",
    runEventCompletedFuzzy: "已完成 · 总 spins={spins} · RTP={rtp}% · {sec}s（模糊档）",
    runEventFailed: "失败: {reason}",
    runSubmittedPlaceholder: "已提交，等待 analyzer 启动...",
    autotuneProgressIdle: "未发起压测",
    autotuneProgressStarting: "压测启动中...",
    autotuneNeedsMachine: "请先在机台目录里选至少一台机台，再点「⚙ 调参」。",
    autotuneProgressLine1: "进度 {done}/{total} 候选完成 · {pctText}",
    autotuneProgressLast: "最近: robot={rc} conc={cc} 成功率={sr} 吞吐={tp} sps p95={p95}s",
    autotuneProgressDone: "已完成 · 共测 {total} 候选",
    autotuneProgressError: "出错 · 已测 {done}/{total} 候选",
    kpiVolatility: "波动性全库分位",
    kpiArchetype: "体验类型",
    kpiLossStreak: "P95 败局连",
    kpiMaxReturn: "最大单回合倍率",
    kpiBigWin: "大奖回合率",
    archetypeBoomBust: "爆击驱动",
    archetypeBalanced: "稳定平衡",
    archetypeGrindy: "磨损消耗",
    archetypeBoomBustHint: "空转率高，靠偶发 10×+ 大奖回本",
    archetypeBalancedHint: "空转中等，利润率温和",
    archetypeGrindyHint: "空转率高，少大奖，缓慢消耗",
    libRankNoData: "—",
    libRankTooFew: "全库样本不足",
    bankruptcyIntro: "每档初始 bankroll = 倍数 × bet，从 rawdata 池化重放到破产或跑完 {session} 回合。下表各行 P10 / P20 / ... / P90 分别表示「第 N% 位玩家破产时已完成的 spin 数」（分母 = 全部模拟 session，含生存）；最快破产一行单独列出最早被打空的那位。",
    bankruptcyTierLabel: "x{mult} 资金",
    bankruptcyRateLabel: "破产率",
    bankruptcyAvgLabel: "平均存活",
    bankruptcyMedianLabel: "中位存活",
    bankruptcySessionsLabel: "Session 数",
    bankruptcySurvivedLabel: "生存",
    bankruptcyBinLabel: "{start}-{end}",
    bankruptcyBinSurvived: "生存（满 {cap}）",
    bankruptcyFastestLabel: "最快破产",
    bankruptcyPercentileCol: "百分位",
    bankruptcySpinCountCol: "Spin 数",
    panelPaylines: "支付线深度（Top 20）",
    thPaylineId: "Payline ID",
    thHitCount: "命中次数",
    thHitRate: "命中率",
    thRtpContribution: "RTP 贡献(pp)",
    thSpinTypeBehavior: "类型",
    spinTypeBehavior_paid: "付费",
    spinTypeBehavior_free: "免费",
    spinTypeBehavior_mixed: "混合",
    panelFeatureBreakdown: "上游 Feature 分布",
    panelBonusChainDynamics: "Bonus Chain 动态",
    featureBreakdownMeta: "{count} 个 feature · 上游权威分组（analysisResult.FeatureWin）",
    featureBreakdownEmpty: "本机台仅含单一 feature（Normal），已由 Pay ID 分布覆盖。",
    featureRowSummary: "总 Win {totalWin} · RTP 贡献 {rtpPp}pp · 占总 win 比 {shareTotal}",
    thFeaturePayId: "Pay ID",
    thFeatureWinCredits: "Win Credits",
    thFeatureTimes: "Times",
    thFeatureShare: "Feature 内占比",
    bonusChainMeta: "{chainCount} 条 chain · {bonusRounds} 个 bonus round",
    bonusChainEmpty: "本机台未发现 Freespin 类型的 bonus chain。",
    bonusChainLenLabel: "Chain 长度",
    bonusChainRatioLabel: "Chain 最高 ExtraRatio",
    bonusChainRetriggerLabel: "自重触发率",
    bonusChainRetriggerDetail: "每条 chain 平均触发 {avg} 次自重",
    bonusChainDepthLabel: "能量敦线（按 chain 深度）",
    bonusChainHistogramLabel: "ExtraRatio 直方图（按 bonus round 计数）",
    bonusChainQuantileFmt: "p50 {p50} · p90 {p90} · p95 {p95} · max {max}",
    libRank: "全库 {p}（{rank}/{total}）",
    libRankSmall: "全库 {rank}/{total}",
    archetypeShare: "{count}/{total} 机台同类型",
    thWinShare: "Win 占比",
    thTopSymbols: "中奖符号 Top",
    paylineEmpty: "暂无支付线数据。",
    panelSymbols: "符号深度（整体 + 按列）",
    symbolsOverallHeader: "整体 Top 20",
    symbolsByColHeader: "按列分布 Top 10（每列）",
    thSymbol: "符号",
    thCount: "次数",
    thRate: "窗口占比",
    thRatePayline: "支付线占比",
    symbolsEmpty: "暂无符号数据。",
    symbolColLabel: "列 {idx}",
    symbolColLabelWithPaylineRows: "列 {idx}（支付线行={rows}）",
    paylineRateUnavailable: "—",
    rtpClampWarning: "RTP 可能被低估：本次采样有 {robots} 个机器人的最后 {pending} 个付费 spin 累积到下次 collect 触发前就被 chunk_spin_times 截断。\n本机型平均每 {avg} 个付费 spin 触发一次 collect bonus；建议增大 chunk_spin_times 重测以拿到更紧的 RTP。",
    panelSpinType: "SpinType 分布",
    thSpinType: "SpinType",
    thSpinShare: "占比",
    thSpinRtpPct: "本类 RTP",
    spinTypeEmpty: "暂无 SpinType 数据。",
    panelPayoutGroups: "Pay ID 深度（PayoutId Top 20）",
    thGroupId: "Pay ID",
    thAvgWinX: "命中均赢",
    thTotalWin: "总 Win",
    payoutGroupEmpty: "暂无 Pay ID 数据。",
    payoutGroupZeroHint: "按 PayoutIdToWinAmount 聚合，按总 Win 倒序展示。",
    sidebarToggleLabel: "切换侧边栏",
    labelChunkSpins: "每 Chunk Spin 次数",
    labelRobotCount: "每 Chunk 机器人数",
    labelConcurrency: "批并发数",
    labelMaxChunks: "最大 Chunk 数",
    labelTimeout: "单请求超时 (秒)",
    labelBankSession: "破产探测回合数",
    labelBankMultipliers: "资金倍数梯度",
    labelProvider: "模型供应商",
    labelModel: "模型",
    labelApiKey: "API Key",
    placeholderApiKey: "粘贴一个 API Key",
    btnSaveModel: "保存模型配置",
    btnStart: "▶ 开始",
    btnStop: "■ 停止",
    btnRefresh: "↻ 刷新",
    btnAutoTune: "⚙ 调参",
    btnAutoTuneBusy: "调参中...",
    btnBatchGenerate: "⟳ 批量生成 Report",
    batchGenerateBusy: "生成中 {done}/{total}",
    batchGenerateDone: "✓ 完成 {done}/{total}（失败 {failed}）",
    batchGenerateFailed: "✗ 失败: {error}",
    batchGenerateNoSelection: "请先在机台目录选中至少 1 台机台",
    viewHall: "按大厅",
    btnSelectAllVisible: "全选",
    hallsEmpty: "大厅分组数据未拉取",
    hallsRefreshBtn: "⟳ 从服务器拉取大厅分组",
    hallsRefreshBusy: "拉取中…",
    hallsRefreshSuccess: "✓ 已拉取 {halls} 个大厅，{machines} 台机台（{ts}）",
    hallsRefreshFailed: "拉取失败: {error}",
    staleBannerAnalyzer: "⚠ {n} 个 report 的 analyzer 版本已过期（rawdata 仍当前）",
    staleBannerRawdata: "⚠ 另有 {n} 个 report 的 rawdata 已过期（服务器升级，需重新采样）",
    staleBannerAllFresh: "",
    btnRegenerateStale: "⟳ 一键重生成（{n}）",
    btnInterpret: "生成解读",
    chunkCacheLabel: "{count} chunks",
    chunkCacheNone: "无缓存",
    btnCacheRefresh: "刷新缓存状态",
    btnCacheCleanup: "清理缓存",
    btnLoadRun: "载入",
    btnDeleteRun: "删除",
    thRawdataVersion: "Rawdata",
    thAnalyzerVersion: "Analyzer",
    badgeFresh: "当前",
    badgeStale: "失配",
    badgeUntagged: "未标记",
    btnBatchDelete: "删除选中",
    btnClearSelection: "清除选择",
    batchSelectedCount: "已选 {n} 项",
    confirmBatchDelete: "确定删除选中的 {n} 条运行记录？关联的报告版本和缓存也会清除。",
    btnClearFilter: "清除筛选",
    thCiHalfwidth: "CI 半宽",
    runFilterActive: "筛选机台：{machine}",
    noRunsForMachine: "该机台暂无运行记录。",
    confirmDeleteRun: "确定删除 run {runId}？关联的报告版本目录 / latest.json 也会清除。",
    runDeleteFailed: "删除失败：{error}",
    paramGuideTitle: "参数说明（新手）",
    helpMachine: "机台：选择目标机台（建议先固定单机台做基线）。",
    helpMode: "RTP Mode：同机台不同数值模式，报告必须按 mode 分开对比。",
    helpCiTarget: "目标 CI 半宽：统计置信精度目标，越小越准，耗时越长。",
    helpChunkSpins: "每 Chunk Spin 次数：单次采样请求中每个机器人执行的转动次数。",
    helpRobotCount: "每 Chunk 机器人数：单次请求同时模拟的机器人数量。",
    helpConcurrency: "批并发数：同一轮并发发送多少个采样请求。",
    helpMaxChunks: "最大 Chunk 数：达到后强制停止，防止无限采样。",
    helpTimeout: "单请求超时：网络或服务慢时的超时保护。",
    helpBankSession: "破产探测回合数：用于估算会话期内破产率。",
    helpBankMultipliers: "资金倍数梯度：例如 10,100,200,500，对应不同起始资金强度；10x 为最前一档 tourist / panic 基线。",
    helpProvider: "供应商：选择解读调用的模型厂商。",
    helpModel: "模型：选择具体解读模型，必须属于当前供应商。",
    helpApiKey: "API Key：仅用于模型解读调用；留空则回退规则解读。",
    helpIconLabel: "参数说明",
    kpiRtp: "RTP %",
    kpiCi: "CI 半宽",
    kpiSpins: "总付费回合",
    kpiZero: "空转率",
    kpiTail: "尾部依赖度",
    chartBucketTitle: "倍率分桶占比",
    chartBucketLabel: "Spin 占比 %",
    thRunId: "Run ID",
    thStatus: "状态",
    thMachine: "机台",
    thMode: "Mode",
    thCreated: "创建时间",
    thAction: "操作",
    thVersion: "版本",
    thRun: "Run",
    thRtp: "RTP",
    thQuality: "质量",
    noRun: "未载入任何机台 run。到「机台管理」点击运行历史里的「载入」再查看分析。",
    noReport: "暂无报告。",
    noInterpret: "暂无解读。",
    noEvents: "暂无事件。",
    noAutoTune: "尚未执行自动调优。",
    noMachines: "暂无机台配置。",
    catalogNoMatch: "无匹配机台。",
    detailLogicClasses: "逻辑类",
    detailConfigMd5: "Config MD5",
    detailCodeMd5: "Code MD5",
    detailReports: "Report 数量",
    thVolatility: "波动性",
    panelFleetOverview: "机台概览",
    fleetTotal: "机台总数",
    fleetWithReports: "有 Report",
    fleetAllHealthy: "全部机台数据正常",
    fleetAvgRtp: "平均 RTP",
    fleetRtpRange: "RTP 范围",
    fleetMechanics: "特殊机制",
    filterClear: "清除筛选",
    btnReportCleanup: "清理旧版本 Report",
    btnImportReports: "导入 Reports",
    btnRefreshMd5: "刷新机台 MD5",
    labelUseLocalMachineConfig: "使用本地 cfg",
    serverDefault: "默认",
    btnSetDefault: "设为默认",
    reportCleanupConfirm: "将删除每台机器每个 mode 下除最新版本外的所有旧 report。确定？",
    reportCleanupDone: "已删除 {deleted} 个旧版本，保留 {kept} 个。",
    btnExportCsv: "导出 CSV",
    thMechanics: "机制",
    catalogSearchPlaceholder: "搜索机台...",
    viewCategory: "按玩法",
    viewName: "按名称",
    viewVolatility: "按波动性",
    viewRtp: "按 RTP",
    viewMechanic: "按机制",
    tabBatch: "批量采样",
    btnBatchStart: "开始批量采样",
    btnSelectAll: "全选",
    btnSelectNone: "取消全选",
    labelConcurrency: "并发数",
    panelFieldDiscovery: "字段发现",
    thFieldName: "字段名",
    thFieldOccurrences: "出现次数",
    thFieldRate: "出现率",
    labelServer: "服务器",
    panelServerManagement: "服务器管理",
    thServerId: "ID",
    thServerName: "名称",
    thServerEndpoint: "地址",
    thServerStatus: "状态",
    serverActive: "已启用",
    serverInactive: "未启用",
    serverNoEndpoint: "未配置地址",
    noServers: "暂无服务器配置。",
    btnAddServer: "添加服务器",
    btnEdit: "编辑",
    btnDelete: "删除",
    serverPromptName: "输入服务器名称：",
    serverPromptEndpoint: "输入服务器地址 (如 http://...)：",
    serverPromptActive: "是否启用此服务器？",
    serverConfirmDelete: "确定删除服务器 {id} ？",
    serverRequiredFields: "ID 和名称为必填项。",
    btnScan: "扫描",
    btnCheckChanges: "检测变更",
    checkFirstScan: "首次扫描完成，已记录 {n} 台机器的基线。下次检测将与此对比。",
    checkNoChanges: "无变更 — 所有机器版本与上次一致。",
    checkChangesFound: "检测到 {n} 项变更！",
    serverCompareTitle: "版本对比",
    btnCompareServers: "对比 MD5",
    compareSelectDifferent: "请选择两个不同的服务器。",
    compareIdentical: "两台服务器 MD5 完全一致（{total} 台机器）。",
    compareDiffs: "项差异",
    panelMachineMechanics: "机台特殊机制",
    mechLockRate: "触发率",
    mechLockSpins: "触发次数",
    mechAvgLines: "平均锁定线数",
    mechUniqueSymbols: "唯一符号数",
    mechTriggerRate: "触发率",
    mechTriggerSpins: "触发次数",
    mechJackpotIds: "Jackpot ID 数",
    mechRtpContrib: "RTP 贡献",
    mechChainRate: "链触发率",
    mechChainSpins: "链内 Spins",
    mechMaxChain: "最长链",
    mechRetriggers: "重触发次数",
    mechPickRate: "触发率",
    mechPickSpins: "触发次数",
    mechAvgDollars: "平均拾取数",
    panelSystemSettings: "系统设置",
    settingMinRetentionLabel: "每 (机台, mode) 最低保留 spins",
    settingMinRetentionHint: "超出部分 chunk 才会被 UI「删除可回收」+ 自动清理回收，保底块永不被自动删除",
    btnSaveSettings: "保存",
    settingsSaved: "已保存 (min_retention_spins={value})",
    settingsSaveError: "保存失败: {error}",
    panelPaylineClassification: "支付线结构分类",
    panelPaytableShape: "Pay ID 形状推断",
    panelPayIdOverview: "Pay ID 总览",
    payIdCol: "Pay ID",
    payIdCatCol: "类型",
    payIdPaidHitsCol: "Paid 命中",
    payIdHitRateCol: "命中率",
    payIdMultCol: "倍率 (× bet)",
    payIdWinShareCol: "占比",
    payIdExpandAll: "展开全部",
    payIdCollapseAll: "收起全部",
    payIdRtpCol: "RTP (pp)",
    payIdShapeCol: "形状",
    payIdColsCol: "覆盖列",
    payIdLineCol: "支付线属性",
    payIdNotesCol: "备注",
    payIdCatPaid: "付费",
    payIdCatBonus: "Bonus",
    payIdCatMixed: "混合",
    payIdGridLabel: "网格",
    payIdWildInferLabel: "Wild 推断",
    payIdWildEvidenceLabel: "▸ Wild 证据明细（按符号）",
    payIdWildReviewNeeded: "Wild 推断需人工核对：下方形状信度已自动降一档显示。",
    payIdShapeNotRun: "形状推断暂未运行；Pay ID 行仅显示频率/RTP 数据，形状列留空。生成 Report 时会自动刷新。",
    lineSignPositive: "支付线",
    lineSignNegative: "负 line_id (scatter)",
    lineSignMixed: "混合",
    lineIdBoardScatter: "板面 Scatter (-1)",
    lineIdAltScatter: "特殊 Scatter (-2)",
    topSymSourceRln: "R",
    topSymSourceHeur: "H",
    topSymSourceRlnTooltip: "权威：来自上游 RewardLastNode 编码",
    topSymSourceHeurTooltip: "启发式：左 3 列符号交集推断",
    panelActivityStrip: "活动日志流",
    panelCollectCycle: "收集周期 & RTP 校正",
    panelMultiSelect: "多选批量操作",
    panelRawdataGlobal: "全局 rawdata 明细",
    hintMultiSelectBar: "↑ 请使用上方批量操作条",
    systemFooterSummary: "⚙ 系统 / 维护 / 历史",
    btnBatchDeleteRawdata: "🗑 删 rawdata",
    btnWipeMachineData: "🗑 清空机台所有数据",
    dangerZoneTitle: "高危操作",
    dangerZoneWipeDesc: "清空该机台的所有 rawdata（所有 mode）、所有 reports，以及对应的运行历史记录。此操作不可撤销。",
    labelSpinCount: "Spins",
    labelSampleStrategy: "策略",
    classifyHeadCrossMode: "跨 mode 分类",
    classifyHeadChannel: "通道归集（当前 mode）",
    classifyHeadDelta: "特征模式规则差异",
    classifyColMode: "Mode",
    classifyColLabel: "分类",
    classifyColPaidSt: "Paid ST",
    classifyColTally: "Feature Tally",
    classifyColSpinType: "SpinType",
    classifyColBehavior: "类型",
    classifyColClass: "分类桶",
    classifyColChannel: "归集通道",
    classifyColExpl: "说明",
    classifyColAdded: "新增 line_id",
    classifyColRemoved: "移除 line_id",
    classifyKindPaid: "付费",
    classifyKindFree: "免费/Bonus",
    classifyCurrent: "当前",
    classifyDeltaHint: "以下 bonus SpinType 的 line_id 集合与付费 ST {paid} 不同 — bonus 模式使用独立支付规则。",
    panelVersionHistory: "版本历史",
    panelComparison: "Report 对比",
    btnCompare: "对比选中",
    thMetric: "指标",
    thVersion: "版本",
    thSpins: "Spins",
    panelSampling: "采样选中机台",
    btnSampleStart: "开始采样",
    btnBatchRun: "批量采样选中",
    batchHintNone: "选择机台后可批量采样",
    batchHintSelected: "已选 {n} 台",
    panelBatchProgress: "批量采样进度",
    batchProgressLabel: "已完成",
    btnBatchCancel: "取消批量",
    noRuns: "暂无运行记录。",
    noVersions: "暂无版本记录。",
    assessmentQuality: "数据质量",
    assessmentVolatility: "波动性分类",
    assessmentArchetype: "体验类型",
    assessmentRecoveryGap: "恢复缺口",
    assessmentTail: "尾部依赖度",
    assessmentRule: "规则对比",
    assessmentAlerts: "告警",
    assessmentActions: "建议动作",
    cacheWarnRunning: "有运行任务进行中，缓存清理已被阻止。",
    cacheWarnIdle: "清理为手动触发。确认无活动运行后再执行缓存清理。",
    cacheNoReclaim: "当前没有可回收的缓存文件。",
    cacheRiskLine: "清理风险等级={tier}，预计可回收={reclaimable}",
    cacheRiskNoneHint: "风险说明：当前不建议执行清理（无可回收空间）。",
    cacheRiskLowHint: "风险说明：低风险，建议在确认无运行任务后执行。",
    cacheRiskMediumHint: "风险说明：中风险，删除量较大，执行前应确认当前分析任务全部完成。",
    cacheRiskHighHint: "风险说明：高风险，删除量非常大，建议先导出必要资料并由负责人确认。",
    riskNone: "无",
    riskLow: "低",
    riskMedium: "中",
    riskHigh: "高",
    confirmCleanupLow: "将执行缓存清理（低风险）。预计删除：{reclaimable}。是否继续？",
    confirmCleanupMedium: "将执行缓存清理（中风险）。预计删除：{reclaimable}。是否继续？",
    confirmCleanupHigh: "将执行缓存清理（高风险）。预计删除：{reclaimable}。是否继续？",
    confirmCleanupToken: "DELETE",
    confirmCleanupTokenPrompt: "当前为{tier}风险。请输入确认口令：{token}",
    confirmCleanupTokenMismatch: "确认口令不匹配，已取消清理。",
    confirmCleanup: "警告：将删除当前可回收的本地 Chunk 缓存文件，是否继续？",
    statusRunning: "运行中",
    statusCompleted: "已完成",
    statusFailed: "失败",
    statusCancelled: "已取消",
    statusUnknown: "未知",
    warnModelMismatch: "所选模型不属于当前供应商。",
    warnApiKeyEmpty: "{provider} API Key 为空，解读会回退到规则模式。",
    warnRecovered: "检测到服务重启后恢复了 {count} 个遗留 running 任务（已标记为 failed）。",
    warnRecoveredPidRisk: "检测到 {count} 个遗留子进程未能自动终止，请在服务器上确认是否仍有分析进程残留。",
    warnSystemBusy: "系统正在执行 {op}，写操作已互斥保护。",
    warnRunFailed: "运行失败：{msg}",
    warnRunCancelled: "运行已取消。",
    warnAutoTuneLowSuccess: "自动调优最佳成功率仅 {rate}，建议降低并发。",
    systemMeta:
      "服务启动时间={startedAt}\\n当前系统操作={operation}\\n操作开始时间={opSince}\\n运行中任务数={runningCount}\\n启动恢复数={recovered}\\n启动已终止遗留进程数={terminatedPids}\\n遗留进程终止失败数={failedPids}",
    safetyTipBase:
      "安全策略：按钮互斥 + 后端操作互斥；服务重启后会自动修正遗留 running 状态，避免出现假运行。",
    safetyTipBusy: "当前有进行中的系统操作：{op}。",
    panelPayoutsBySpinType: "按 SpinType 拆分的 Pay ID",
    panelReelMarginalBySpinType: "按 SpinType 拆分的转轮边际分布",
    spinTypeBehaviorPaid: "付费",
    spinTypeBehaviorFree: "免费",
    spinTypeBehaviorMixed: "混合",
    thProbPct: "出现率",
    reelColPrefix: "列",
    // Phase 3 (D11): config upload + fleet refresh panel keys
    panelConfigUpload: "配置上传",
    labelConfigFile: "配置文件 (JSON)",
    labelConfigDisplayName: "显示名称",
    btnConfigUpload: "上传",
    configUploadOk: "上传成功 (id={id})",
    configUploadErr: "上传失败: {error}",
    configUploadNoFile: "请先选择文件",
    configListEmpty: "暂无上传的配置",
    configListHeader: "已上传配置 ({count})",
    panelFleetRefresh: "全机台刷新队列",
    btnFleetRefreshStart: "开始全刷新",
    btnFleetRefreshCancel: "取消",
    fleetRefreshRunning: "刷新中 {done}/{total}",
    fleetRefreshDone: "已完成 {done}/{total}（跳过 {skipped}）",
    fleetRefreshCancelled: "已取消",
    fleetRefreshIdle: "空闲",
    fleetRefreshConflict: "已有队列在运行，请先取消",
    underlyingRemovedBadge: "rawdata 已删",
    // ── P4 auto-inspect tab ──
    tabAutoInspect: "自动巡检",
    panelAutoInspectSettings: "自动巡检设置",
    panelAutoInspectPreview: "巡检预览",
    panelAutoInspectProgress: "巡检进度",
    panelAutoInspectHistory: "最近巡检记录",
    labelAiEnabled: "启用自动巡检",
    labelAiSchedule: "执行计划",
    labelAiScheduleDaily: "每天",
    labelAiScheduleInterval: "每",
    labelAiScheduleHours: "小时",
    labelAiSweepConcurrency: "巡检并发",
    labelAiSkipFresh: "跳过新鲜格",
    labelAiBinaryGroupCap: "二元组并发上限",
    labelAiMaxConsecutiveFailures: "连续失败上限",
    labelAiConsecutiveFailureWindow: "失败计数窗口",
    labelAiCellBusyTimeout: "格锁超时(s)",
    labelAiWallTimePerCell: "单格时限(s)",
    labelAiStructuralSkipMachines: "结构跳过机台 (逗号分隔)",
    labelAiPerModeSettings: "各 Mode 参数",
    thAiMode: "Mode",
    thAiChunkSpinTimes: "每批 Spins",
    thAiChunkRobotCount: "每批机器人",
    thAiBatchConcurrency: "并发",
    thAiTargetHalfwidth: "目标半宽(pp)",
    thAiMaxChunks: "最大批次",
    btnAiSaveSettings: "保存设置",
    aiSettingsSaved: "已保存",
    aiSettingsError: "保存失败: {error}",
    btnAiPreview: "预览将巡检的机台",
    aiPreviewIdle: "点击「预览」查看本次巡检范围",
    aiPreviewLoading: "扫描中...",
    aiPreviewResult: "共 {total} 个格 · 预计 {hours}h{mins}min · 跳过 {skip} 结构机台 · {override} 个 override 机台",
    aiPreviewEmpty: "无需巡检的格（所有格均新鲜）",
    aiPreviewByMode: "Mode {mode}: {count} 个",
    aiPreviewError: "预览失败: {error}",
    btnAiStart: "开始巡检",
    btnAiCancel: "取消巡检",
    aiSweepRunning: "运行中",
    aiSweepCompleted: "已完成",
    aiSweepCancelled: "已取消",
    aiSweepFailed: "失败",
    aiSweepIdle: "空闲",
    aiSweepConflict: "巡检或机台刷新已在运行中",
    aiCounterBanner: "{done} / {total} 完成（{failed} 失败，{skipped} 跳过，{pending} 待处理）",
    labelAiFilter: "过滤",
    aiFilterAll: "全部",
    aiFilterCompleted: "已完成",
    aiFilterFailed: "失败",
    aiFilterSkipped: "跳过",
    aiFilterPending: "待处理",
    thAiItemMachine: "机台",
    thAiItemMode: "Mode",
    thAiItemStatus: "状态",
    thAiItemCellClass: "类别",
    thAiItemReason: "原因",
    aiHistoryEmpty: "暂无记录",
    aiHistoryRow: "{time} · {status} · {done}/{total} · {trigger}",
    aiHistoryClickHint: "点击行载入该次巡检详情",
    aiStatusPending: "待处理",
    aiStatusClaimed: "已认领",
    aiStatusRunning: "采样中",
    aiStatusGenerating: "生成中",
    aiStatusCompleted: "已完成",
    aiStatusFailed: "失败",
    aiStatusStructuralSkip: "结构跳过",
    aiStatusConvergenceTimeout: "收敛超时",
    aiStatusManifestPartial: "manifest 部分",
    aiStatusDeferredLock: "锁冲突延迟",
    aiStatusWallTime: "时限超出",
    aiStatusMd5Drift: "MD5 漂移",
    aiStatusCancelled: "已取消",
    aiStatusScanning: "扫描中",
    aiStatusSampling: "采样中",
    aiStatusFinalizing: "收尾中",
    aiSweepTriggerManual: "手动",
    aiSweepTriggerCron: "定时",
  },
  en: {
    appTitle: "Slot Console",
    subtitle: "Machine debugging, metrics analysis, and version management",
    languageLabel: "Language",
    healthChecking: "Checking...",
    healthOk: "API OK",
    healthFail: "API ERROR",
    tabDebug: "Machine Debug",
    tabManage: "Machine Management",
    panelLoadedMachine: "Currently Loaded Machine",
    freshnessAnalyzer: "Analyzer",
    freshnessRawdata: "Rawdata",
    freshnessFresh: "✓ current",
    freshnessStale: "⚠ stale",
    freshnessUntagged: "· untagged",
    panelRunConfig: "Run Parameters",
    panelModelConfig: "Model Config",
    panelRunControl: "Run Control",
    panelProgress: "Current Run Progress",
    panelKpi: "Key Indicators",
    panelBuckets: "Multiplier Distribution",
    thBucket: "Bucket",
    thSpinCount: "Count",
    thSpinRate: "Rate",
    panelCharts: "Visual Analytics",
    panelBankruptcy: "Bankruptcy Analysis",
    panelInterpretation: "Model Interpretation",
    panelEvents: "Run Events",
    panelMachineCatalog: "Machine Catalog",
    panelRunHistory: "Run History",
    panelReportVersions: "Report Versions",
    panelCache: "Chunk Cache",
    panelSystemState: "System State & Recovery",
    labelMachine: "Machine",
    labelMode: "RTP Mode",
    labelCiTarget: "Target CI Half-width",
    ciOption05: "0.5 pp (high precision)",
    ciOption1: "1.0 pp (standard)",
    ciOption2: "2.0 pp (fast)",
    ciOption5: "5.0 pp (exploratory)",
    ciOptionFuzzy: "Fuzzy (high-volatility mode)",
    helpCiTargetFuzzy: "Fuzzy tier: CI stop is bypassed; sampling targets ~1M spins via max_chunks. Required for mode 2/5 (RTP-exploding special mechanics).",
    placeholderAutotuneFill: "filled by Auto Tune",
    validateConcurrencyRequired: "Fill in robot count and concurrency (or click 'Auto Tune Parallelism' to probe machine-specific recommendations).",
    validateMode25RequireFuzzy: "Mode 2 and 5 must use the fuzzy CI tier.",
    labelAdvancedParams: "Advanced parameters",
    bankMultStandard: "Standard (10x / 100x / 200x / 500x) — recommended",
    bankMultShort: "Short session (10x / 50x / 100x / 200x)",
    bankMultLong: "Long session (10x / 200x / 500x / 1000x)",
    helpBankMultiplierWarn: "Only the Standard preset aligns with the guideline rules' x100/x200/x500 thresholds; other presets skip the bankruptcy A5 rule.",
    runStatusLabel: "Status",
    runFailedLabel: "Last failure reason",
    runCancelledLabel: "Last result",
    runCancelledText: "Cancelled",
    runFailureNoneCaptured: "No diagnostic captured (analyzer produced no stderr/stdout)",
    runEventNone: "no events yet",
    runEventStarted: "submitted · machine={machine} mode={mode} target={target}",
    runEventStartedFuzzy: "submitted · machine={machine} mode={mode} target=fuzzy (~1M spins)",
    runEventChunk: "chunk {idx}/{max} · spins={spins} · RTP={rtp}% · CI={ci}pp",
    runEventChunkFuzzy: "chunk {idx} · spins={spins} · RTP={rtp}% · fuzzy progress {pct}%",
    runEventCompleted: "completed · spins={spins} · RTP={rtp}% · CI={ci}pp · {sec}s",
    runEventCompletedFuzzy: "completed · spins={spins} · RTP={rtp}% · {sec}s (fuzzy)",
    runEventFailed: "failed: {reason}",
    runSubmittedPlaceholder: "submitted, waiting for analyzer to spawn...",
    autotuneProgressIdle: "no autotune yet",
    autotuneProgressStarting: "autotune starting...",
    autotuneNeedsMachine: "Select at least one machine in the catalog first, then click ⚙ AutoTune.",
    autotuneProgressLine1: "{done}/{total} candidates done · {pctText}",
    autotuneProgressLast: "last: robot={rc} conc={cc} success={sr} throughput={tp} sps p95={p95}s",
    autotuneProgressDone: "completed · {total} candidates tested",
    autotuneProgressError: "error · {done}/{total} candidates tested",
    kpiVolatility: "Volatility (Lib Rank)",
    kpiArchetype: "Experience",
    kpiLossStreak: "P95 Loss Streak",
    kpiMaxReturn: "Max Return x (paid round)",
    kpiBigWin: "Big-Win Round Rate",
    archetypeBoomBust: "Boom-Bust",
    archetypeBalanced: "Balanced",
    archetypeGrindy: "Grindy",
    archetypeBoomBustHint: "High zero-win, big wins drive RTP",
    archetypeBalancedHint: "Moderate zero-win, steady profit",
    archetypeGrindyHint: "High zero-win, rare big wins",
    libRankNoData: "—",
    libRankTooFew: "library too small",
    bankruptcyIntro: "Initial bankroll = multiplier × bet per tier. Pooled rawdata replay stops at bankruptcy or session cap ({session}). Rows P10 / P20 / ... / P90 show the spin count reached at each percentile of ALL simulated sessions (bankrupt + survived). Fastest row = the earliest bankruptcy observed.",
    bankruptcyTierLabel: "x{mult} bankroll",
    bankruptcyRateLabel: "Bankruptcy rate",
    bankruptcyAvgLabel: "Avg survival",
    bankruptcyMedianLabel: "Median survival",
    bankruptcySessionsLabel: "Sessions",
    bankruptcySurvivedLabel: "Survived",
    bankruptcyBinLabel: "{start}-{end}",
    bankruptcyBinSurvived: "Survived ({cap})",
    bankruptcyFastestLabel: "Fastest bankruptcy",
    bankruptcyPercentileCol: "Percentile",
    bankruptcySpinCountCol: "Spins",
    panelPaylines: "Payline Drilldown (Top 20)",
    thPaylineId: "Payline ID",
    thHitCount: "Hit Count",
    thHitRate: "Hit Rate",
    thRtpContribution: "RTP Contribution (pp)",
    thSpinTypeBehavior: "Behavior",
    spinTypeBehavior_paid: "paid",
    spinTypeBehavior_free: "free",
    spinTypeBehavior_mixed: "mixed",
    panelFeatureBreakdown: "Upstream feature breakdown",
    panelBonusChainDynamics: "Bonus chain dynamics",
    featureBreakdownMeta: "{count} feature(s) · upstream-authoritative grouping (analysisResult.FeatureWin)",
    featureBreakdownEmpty: "Single-feature machine (Normal); already covered by Pay ID breakdown.",
    featureRowSummary: "total win {totalWin} · RTP contrib {rtpPp}pp · {shareTotal} of total win",
    thFeaturePayId: "Pay ID",
    thFeatureWinCredits: "Win credits",
    thFeatureTimes: "Times",
    thFeatureShare: "Share of feature",
    bonusChainMeta: "{chainCount} chains · {bonusRounds} bonus rounds",
    bonusChainEmpty: "No Freespin-annotated bonus chains found on this machine.",
    bonusChainLenLabel: "Chain length",
    bonusChainRatioLabel: "Peak ExtraRatio per chain",
    bonusChainRetriggerLabel: "Self-retrigger rate",
    bonusChainRetriggerDetail: "avg {avg} retriggers per chain",
    bonusChainDepthLabel: "Energy ramp (by chain depth)",
    bonusChainHistogramLabel: "ExtraRatio histogram (bonus rounds)",
    bonusChainQuantileFmt: "p50 {p50} · p90 {p90} · p95 {p95} · max {max}",
    libRank: "lib {p} ({rank}/{total})",
    libRankSmall: "lib {rank}/{total}",
    archetypeShare: "{count}/{total} share this archetype",
    thWinShare: "Win Share",
    thTopSymbols: "Top Win Symbols",
    paylineEmpty: "No payline data yet.",
    panelSymbols: "Symbol Drilldown (Overall + by Column)",
    symbolsOverallHeader: "Overall Top 20",
    symbolsByColHeader: "By Column Top 10 (each column)",
    thSymbol: "Symbol",
    thCount: "Count",
    thRate: "Window %",
    thRatePayline: "Payline %",
    symbolsEmpty: "No symbol data yet.",
    symbolColLabel: "Col {idx}",
    symbolColLabelWithPaylineRows: "Col {idx} (payline rows={rows})",
    paylineRateUnavailable: "—",
    rtpClampWarning: "RTP may be under-reported: this sample left {robots} robot(s) with {pending} paid spin(s) accumulating toward the next collect trigger when chunk_spin_times ran out.\nThis machine averages 1 collect bonus per {avg} paid spins; widen chunk_spin_times and rerun for a tighter RTP estimate.",
    panelSpinType: "SpinType Breakdown",
    thSpinType: "SpinType",
    thSpinShare: "Share",
    thSpinRtpPct: "Type RTP",
    spinTypeEmpty: "No SpinType data yet.",
    panelPayoutGroups: "Pay ID Drilldown (PayoutId Top 20)",
    thGroupId: "Pay ID",
    thAvgWinX: "Avg Win when Hit",
    thTotalWin: "Total Win",
    payoutGroupEmpty: "No Pay ID data yet.",
    payoutGroupZeroHint: "Aggregated from PayoutIdToWinAmount, sorted by total win desc.",
    sidebarToggleLabel: "Toggle sidebar",
    labelChunkSpins: "Chunk Spin Times",
    labelRobotCount: "Chunk Robot Count",
    labelConcurrency: "Batch Concurrency",
    labelMaxChunks: "Max Chunks",
    labelTimeout: "Request Timeout (sec)",
    labelBankSession: "Bankruptcy Session Spins",
    labelBankMultipliers: "Bankroll Multipliers",
    labelProvider: "Provider",
    labelModel: "Model",
    labelApiKey: "API Key",
    placeholderApiKey: "Paste one API key",
    btnSaveModel: "Save Model Config",
    btnStart: "▶ Start",
    btnStop: "■ Stop",
    btnRefresh: "↻ Refresh",
    btnAutoTune: "⚙ Auto Tune",
    btnAutoTuneBusy: "Tuning...",
    btnBatchGenerate: "⟳ Batch Generate Report",
    batchGenerateBusy: "Generating {done}/{total}",
    batchGenerateDone: "✓ Done {done}/{total} (failed {failed})",
    batchGenerateFailed: "✗ Failed: {error}",
    batchGenerateNoSelection: "Select at least 1 machine in the catalog first",
    viewHall: "By Hall",
    btnSelectAllVisible: "Select All",
    hallsEmpty: "Hall mapping not yet fetched",
    hallsRefreshBtn: "⟳ Fetch hall mapping from server",
    hallsRefreshBusy: "Fetching…",
    hallsRefreshSuccess: "✓ Fetched {halls} hall(s), {machines} machines ({ts})",
    hallsRefreshFailed: "Fetch failed: {error}",
    staleBannerAnalyzer: "⚠ {n} report(s) have stale analyzer version (rawdata still fresh)",
    staleBannerRawdata: "⚠ Plus {n} report(s) with stale rawdata (server upgraded — resample required)",
    staleBannerAllFresh: "",
    btnRegenerateStale: "⟳ Regenerate ({n})",
    btnInterpret: "Generate Interpretation",
    chunkCacheLabel: "{count} chunks",
    chunkCacheNone: "no cache",
    btnCacheRefresh: "Refresh Cache",
    btnCacheCleanup: "Cleanup Cache",
    btnLoadRun: "Load",
    btnDeleteRun: "Delete",
    thRawdataVersion: "Rawdata",
    thAnalyzerVersion: "Analyzer",
    badgeFresh: "fresh",
    badgeStale: "stale",
    badgeUntagged: "untagged",
    btnBatchDelete: "Delete selected",
    btnClearSelection: "Clear selection",
    batchSelectedCount: "{n} selected",
    confirmBatchDelete: "Delete {n} selected run(s)? Associated report versions and cache will also be cleared.",
    btnClearFilter: "Clear filter",
    thCiHalfwidth: "CI \u00b1",
    runFilterActive: "Filtering machine: {machine}",
    noRunsForMachine: "No runs for this machine yet.",
    confirmDeleteRun: "Delete run {runId}? Associated report version directory + latest.json will also be cleared.",
    runDeleteFailed: "Delete failed: {error}",
    paramGuideTitle: "Parameter Guide (for newcomers)",
    helpMachine: "Machine: select target machine (use one machine first for baseline).",
    helpMode: "RTP Mode: treat each mode as a separate numeric profile when comparing reports.",
    helpCiTarget: "Target CI half-width: smaller gives higher confidence but takes longer.",
    helpChunkSpins: "Chunk Spin Times: spins per robot in one sample request.",
    helpRobotCount: "Chunk Robot Count: robots simulated per sample request.",
    helpConcurrency: "Batch Concurrency: number of sample requests sent in parallel per round.",
    helpMaxChunks: "Max Chunks: hard stop to prevent unbounded sampling.",
    helpTimeout: "Request Timeout: per-request network timeout protection.",
    helpBankSession: "Bankruptcy Session Spins: session horizon for bankruptcy-rate probing.",
    helpBankMultipliers: "Bankroll Multipliers: e.g. 10,100,200,500 — 10x is the leading tourist / panic baseline, the rest cover progressively longer sessions.",
    helpProvider: "Provider: selects the vendor for interpretation calls.",
    helpModel: "Model: concrete interpretation model; must belong to current provider.",
    helpApiKey: "API key: used only for interpretation calls; empty key falls back to rule-based text.",
    helpIconLabel: "Parameter help",
    kpiRtp: "RTP %",
    kpiCi: "CI Half-width",
    kpiSpins: "Total Paid Rounds",
    kpiZero: "Zero Win Rate",
    kpiTail: "Tail Dependency",
    chartBucketTitle: "Multiplier Bucket Rate",
    chartBucketLabel: "Spin Rate %",
    thRunId: "Run ID",
    thStatus: "Status",
    thMachine: "Machine",
    thMode: "Mode",
    thCreated: "Created At",
    thAction: "Action",
    thVersion: "Version",
    thSpins: "Spins",
    thRun: "Run",
    thRtp: "RTP",
    thQuality: "Quality",
    noRun: "No run loaded. Open 「Machine Management」and click 「Load」on a row in Run History to view analysis.",
    noReport: "No report yet.",
    noInterpret: "No interpretation yet.",
    noEvents: "No events yet.",
    noAutoTune: "No auto tune run yet.",
    noMachines: "No machine config found.",
    catalogNoMatch: "No matching machines.",
    detailLogicClasses: "Logic Classes",
    detailConfigMd5: "Config MD5",
    detailCodeMd5: "Code MD5",
    detailReports: "Reports",
    thVolatility: "Volatility",
    panelFleetOverview: "Fleet Overview",
    fleetTotal: "Total Machines",
    fleetWithReports: "With Reports",
    fleetAllHealthy: "All machines healthy",
    fleetAvgRtp: "Avg RTP",
    fleetRtpRange: "RTP Range",
    fleetMechanics: "Mechanics",
    filterClear: "Clear Filter",
    btnReportCleanup: "Cleanup Old Reports",
    btnImportReports: "Import Reports",
    btnRefreshMd5: "Refresh Machine MD5",
    labelUseLocalMachineConfig: "Use local cfg",
    serverDefault: "Default",
    btnSetDefault: "Set default",
    reportCleanupConfirm: "Delete all but the newest report version per machine-mode?",
    reportCleanupDone: "Deleted {deleted} old versions, kept {kept}.",
    btnExportCsv: "Export CSV",
    thMechanics: "Mechanics",
    catalogSearchPlaceholder: "Search machines...",
    viewCategory: "By Category",
    viewName: "By Name",
    viewVolatility: "By Volatility",
    viewRtp: "By RTP",
    viewMechanic: "By Mechanic",
    tabBatch: "Batch Sampling",
    btnBatchStart: "Start Batch",
    btnSelectAll: "Select All",
    btnSelectNone: "Clear All",
    labelConcurrency: "Concurrency",
    panelFieldDiscovery: "Field Discovery",
    thFieldName: "Field",
    thFieldOccurrences: "Occurrences",
    thFieldRate: "Rate",
    labelServer: "Server",
    panelServerManagement: "Server Management",
    thServerId: "ID",
    thServerName: "Name",
    thServerEndpoint: "Endpoint",
    thServerStatus: "Status",
    serverActive: "Active",
    serverInactive: "Inactive",
    serverNoEndpoint: "Not configured",
    noServers: "No servers configured.",
    btnAddServer: "Add Server",
    btnEdit: "Edit",
    btnDelete: "Delete",
    serverPromptName: "Enter server name:",
    serverPromptEndpoint: "Enter endpoint URL (e.g. http://...):",
    serverPromptActive: "Enable this server?",
    serverConfirmDelete: "Delete server {id}?",
    serverRequiredFields: "ID and name are required.",
    btnScan: "Scan",
    btnCheckChanges: "Check Changes",
    checkFirstScan: "First scan done — {n} machines baselined. Next check will compare against this.",
    checkNoChanges: "No changes — all machine versions match previous scan.",
    checkChangesFound: "{n} changes detected!",
    serverCompareTitle: "Version Comparison",
    btnCompareServers: "Compare MD5",
    compareSelectDifferent: "Select two different servers.",
    compareIdentical: "Servers are identical ({total} machines).",
    compareDiffs: "differences",
    panelMachineMechanics: "Machine Mechanics",
    mechLockRate: "Lock Rate",
    mechLockSpins: "Lock Spins",
    mechAvgLines: "Avg Lines/Lock",
    mechUniqueSymbols: "Unique Symbols",
    mechTriggerRate: "Trigger Rate",
    mechTriggerSpins: "Trigger Spins",
    mechJackpotIds: "Jackpot IDs",
    mechRtpContrib: "RTP Contribution",
    mechChainRate: "Chain Rate",
    mechChainSpins: "Chain Spins",
    mechMaxChain: "Max Chain",
    mechRetriggers: "Retriggers",
    mechPickRate: "Pick Rate",
    mechPickSpins: "Pick Spins",
    mechAvgDollars: "Avg Dollars/Pick",
    panelSystemSettings: "System Settings",
    settingMinRetentionLabel: "Min retention spins per (machine, mode)",
    settingMinRetentionHint: "Chunks beyond this cumulative spin count are eligible for UI \"Delete reclaimable\" + auto-cleanup; baseline below the quota is protected.",
    btnSaveSettings: "Save",
    settingsSaved: "Saved (min_retention_spins={value})",
    settingsSaveError: "Save failed: {error}",
    panelPaylineClassification: "Payline Structure Classification",
    panelPaytableShape: "Pay ID Shape Inference",
    panelPayIdOverview: "Pay ID Overview",
    payIdCol: "Pay ID",
    payIdCatCol: "Type",
    payIdPaidHitsCol: "Paid hits",
    payIdHitRateCol: "Hit rate",
    payIdMultCol: "Multiplier (× bet)",
    payIdWinShareCol: "Share",
    payIdExpandAll: "Expand all",
    payIdCollapseAll: "Collapse all",
    payIdRtpCol: "RTP (pp)",
    payIdShapeCol: "Shape",
    payIdColsCol: "Cols",
    payIdLineCol: "Line",
    payIdNotesCol: "Notes",
    payIdCatPaid: "Paid",
    payIdCatBonus: "Bonus",
    payIdCatMixed: "Mixed",
    payIdGridLabel: "Grid",
    payIdWildInferLabel: "Wild inference",
    payIdWildEvidenceLabel: "▸ Wild evidence (per symbol)",
    payIdWildReviewNeeded: "Wild inference flagged for manual review — shape confidence is auto-downgraded below.",
    payIdShapeNotRun: "Shape inference not yet run; pay_id rows show frequency / RTP only. Auto-refreshes on next generate-report.",
    lineSignPositive: "line-pay",
    lineSignNegative: "scatter (negative)",
    lineSignMixed: "mixed",
    lineIdBoardScatter: "Board Scatter (-1)",
    lineIdAltScatter: "Alt Scatter (-2)",
    topSymSourceRln: "R",
    topSymSourceHeur: "H",
    topSymSourceRlnTooltip: "Authoritative: from upstream RewardLastNode codes",
    topSymSourceHeurTooltip: "Heuristic: inferred from left-3-column symbol intersection",
    panelActivityStrip: "Activity Log Stream",
    panelCollectCycle: "Collect Cycle & RTP Correction",
    panelMultiSelect: "Batch Operations",
    panelRawdataGlobal: "Global Rawdata Detail",
    hintMultiSelectBar: "↑ Use the batch action bar above",
    systemFooterSummary: "⚙ System / Maintenance / History",
    btnBatchDeleteRawdata: "🗑 Delete rawdata",
    btnWipeMachineData: "🗑 Wipe all machine data",
    dangerZoneTitle: "Danger zone",
    dangerZoneWipeDesc: "Erases all rawdata (every mode), every report version, and the run history for this machine. This action is irreversible.",
    labelSpinCount: "Spins",
    labelSampleStrategy: "Strategy",
    classifyHeadCrossMode: "Cross-mode Labels",
    classifyHeadChannel: "Win Channel (current mode)",
    classifyHeadDelta: "Feature-Mode Rule Delta",
    classifyColMode: "Mode",
    classifyColLabel: "Label",
    classifyColPaidSt: "Paid ST",
    classifyColTally: "Feature Tally",
    classifyColSpinType: "SpinType",
    classifyColBehavior: "Kind",
    classifyColClass: "Bucket",
    classifyColChannel: "Channel",
    classifyColExpl: "Explanation",
    classifyColAdded: "Added line_id",
    classifyColRemoved: "Removed line_id",
    classifyKindPaid: "Paid",
    classifyKindFree: "Free/Bonus",
    classifyCurrent: "current",
    classifyDeltaHint: "The following bonus SpinTypes have line_id sets that differ from paid ST {paid} — bonus mode uses distinct payline rules.",
    panelVersionHistory: "Version History",
    panelComparison: "Report Comparison",
    btnCompare: "Compare Selected",
    thMetric: "Metric",
    panelSampling: "Sample Selected Machines",
    btnSampleStart: "Start Sampling",
    btnBatchRun: "Batch Run Selected",
    batchHintNone: "Select machines to batch run",
    batchHintSelected: "{n} selected",
    panelBatchProgress: "Batch Progress",
    batchProgressLabel: "completed",
    btnBatchCancel: "Cancel Batch",
    noRuns: "No runs yet.",
    noVersions: "No versions yet.",
    assessmentQuality: "quality_label",
    assessmentVolatility: "volatility_class",
    assessmentArchetype: "experience_archetype",
    assessmentRecoveryGap: "recovery_gap",
    assessmentTail: "tail_dependency",
    assessmentRule: "guideline_compare",
    assessmentAlerts: "alerts",
    assessmentActions: "actions",
    cacheWarnRunning: "Cleanup is blocked while runs are active.",
    cacheWarnIdle: "Cleanup is manual only. Confirm no active run before cleanup.",
    cacheNoReclaim: "No reclaimable cache files at the moment.",
    cacheRiskLine: "Cleanup risk={tier}, reclaimable={reclaimable}",
    cacheRiskNoneHint: "Risk note: cleanup is not needed now (nothing reclaimable).",
    cacheRiskLowHint: "Risk note: low risk. Run cleanup after confirming no active runs.",
    cacheRiskMediumHint: "Risk note: medium risk. Large deletion volume; ensure all analyses are finished first.",
    cacheRiskHighHint: "Risk note: high risk. Very large deletion volume; require owner confirmation first.",
    riskNone: "none",
    riskLow: "low",
    riskMedium: "medium",
    riskHigh: "high",
    confirmCleanupLow: "Run cache cleanup (low risk). Estimated deletion: {reclaimable}. Continue?",
    confirmCleanupMedium: "Run cache cleanup (medium risk). Estimated deletion: {reclaimable}. Continue?",
    confirmCleanupHigh: "Run cache cleanup (high risk). Estimated deletion: {reclaimable}. Continue?",
    confirmCleanupToken: "DELETE",
    confirmCleanupTokenPrompt: "Current risk is {tier}. Type confirmation token: {token}",
    confirmCleanupTokenMismatch: "Confirmation token mismatch. Cleanup canceled.",
    confirmCleanup: "WARNING: this will delete local reclaimable chunk files. Continue?",
    statusRunning: "running",
    statusCompleted: "completed",
    statusFailed: "failed",
    statusCancelled: "cancelled",
    statusUnknown: "unknown",
    warnModelMismatch: "Selected model does not belong to current provider.",
    warnApiKeyEmpty: "{provider} API key is empty. Interpretation will fallback to rule-based.",
    warnRecovered: "Recovered {count} stale running tasks after service restart (marked as failed).",
    warnRecoveredPidRisk: "{count} stale worker process(es) could not be terminated automatically; please verify server-side leftovers.",
    warnSystemBusy: "System is executing {op}; write operations are mutex-protected.",
    warnRunFailed: "Run failed: {msg}",
    warnRunCancelled: "Run cancelled.",
    warnAutoTuneLowSuccess: "Best auto-tune success rate is only {rate}; consider lower concurrency.",
    systemMeta:
      "app_started_at={startedAt}\\noperation={operation}\\noperation_since={opSince}\\nrunning_runs={runningCount}\\nstartup_recovered={recovered}\\nstartup_terminated_pids={terminatedPids}\\nstartup_failed_to_terminate_pids={failedPids}",
    safetyTipBase:
      "Safety policy: UI mutex + backend operation mutex. On service restart, stale running states are auto-corrected.",
    safetyTipBusy: "Current system operation in progress: {op}.",
    panelPayoutsBySpinType: "Pay IDs by SpinType",
    panelReelMarginalBySpinType: "Reel Marginal by SpinType",
    spinTypeBehaviorPaid: "paid",
    spinTypeBehaviorFree: "free",
    spinTypeBehaviorMixed: "mixed",
    thProbPct: "Prob %",
    reelColPrefix: "Col",
    // Phase 3 (D11): config upload + fleet refresh panel keys
    panelConfigUpload: "Config Upload",
    labelConfigFile: "Config file (JSON)",
    labelConfigDisplayName: "Display name",
    btnConfigUpload: "Upload",
    configUploadOk: "Uploaded (id={id})",
    configUploadErr: "Upload failed: {error}",
    configUploadNoFile: "Please select a file first",
    configListEmpty: "No configs uploaded yet",
    configListHeader: "Uploaded configs ({count})",
    panelFleetRefresh: "Fleet Refresh Queue",
    btnFleetRefreshStart: "Start full refresh",
    btnFleetRefreshCancel: "Cancel",
    fleetRefreshRunning: "Refreshing {done}/{total}",
    fleetRefreshDone: "Done {done}/{total} (skipped {skipped})",
    fleetRefreshCancelled: "Cancelled",
    fleetRefreshIdle: "Idle",
    fleetRefreshConflict: "Queue already running — cancel first",
    underlyingRemovedBadge: "rawdata removed",
    // ── P4 auto-inspect tab ──
    tabAutoInspect: "Auto-Inspect",
    panelAutoInspectSettings: "Auto-Inspect Settings",
    panelAutoInspectPreview: "Sweep Preview",
    panelAutoInspectProgress: "Sweep Progress",
    panelAutoInspectHistory: "Recent Sweeps",
    labelAiEnabled: "Enable auto-inspect",
    labelAiSchedule: "Schedule",
    labelAiScheduleDaily: "Daily at",
    labelAiScheduleInterval: "Every",
    labelAiScheduleHours: "hours",
    labelAiSweepConcurrency: "Sweep concurrency",
    labelAiSkipFresh: "Skip fresh cells",
    labelAiBinaryGroupCap: "Binary group large cap",
    labelAiMaxConsecutiveFailures: "Max consecutive failures",
    labelAiConsecutiveFailureWindow: "Failure window",
    labelAiCellBusyTimeout: "Cell lock timeout (s)",
    labelAiWallTimePerCell: "Wall time per cell (s)",
    labelAiStructuralSkipMachines: "Structural skip machines (comma-separated)",
    labelAiPerModeSettings: "Per-mode settings",
    thAiMode: "Mode",
    thAiChunkSpinTimes: "Spins/chunk",
    thAiChunkRobotCount: "Robots/chunk",
    thAiBatchConcurrency: "Concurrency",
    thAiTargetHalfwidth: "Target HW (pp)",
    thAiMaxChunks: "Max chunks",
    btnAiSaveSettings: "Save settings",
    aiSettingsSaved: "Saved",
    aiSettingsError: "Save failed: {error}",
    btnAiPreview: "Preview cells in scope",
    aiPreviewIdle: "Click Preview to see sweep scope",
    aiPreviewLoading: "Scanning...",
    aiPreviewResult: "{total} cells · est. {hours}h{mins}min · {skip} structural-skip · {override} override",
    aiPreviewEmpty: "No cells need sweep (all fresh)",
    aiPreviewByMode: "Mode {mode}: {count}",
    aiPreviewError: "Preview failed: {error}",
    btnAiStart: "Start sweep",
    btnAiCancel: "Cancel sweep",
    aiSweepRunning: "Running",
    aiSweepCompleted: "Completed",
    aiSweepCancelled: "Cancelled",
    aiSweepFailed: "Failed",
    aiSweepIdle: "Idle",
    aiSweepConflict: "Sweep or fleet refresh already running",
    aiCounterBanner: "{done} / {total} done ({failed} failed, {skipped} skipped, {pending} pending)",
    labelAiFilter: "Filter",
    aiFilterAll: "All",
    aiFilterCompleted: "Completed",
    aiFilterFailed: "Failed",
    aiFilterSkipped: "Skipped",
    aiFilterPending: "Pending",
    thAiItemMachine: "Machine",
    thAiItemMode: "Mode",
    thAiItemStatus: "Status",
    thAiItemCellClass: "Class",
    thAiItemReason: "Reason",
    aiHistoryEmpty: "No sweep history",
    aiHistoryRow: "{time} · {status} · {done}/{total} · {trigger}",
    aiHistoryClickHint: "Click row to load sweep detail",
    aiStatusPending: "pending",
    aiStatusClaimed: "claimed",
    aiStatusRunning: "running",
    aiStatusGenerating: "generating",
    aiStatusCompleted: "completed",
    aiStatusFailed: "failed",
    aiStatusStructuralSkip: "structural skip",
    aiStatusConvergenceTimeout: "convergence timeout",
    aiStatusManifestPartial: "manifest partial",
    aiStatusDeferredLock: "deferred lock",
    aiStatusWallTime: "wall time exceeded",
    aiStatusMd5Drift: "md5 drift",
    aiStatusCancelled: "cancelled",
    aiStatusScanning: "scanning",
    aiStatusSampling: "sampling",
    aiStatusFinalizing: "finalizing",
    aiSweepTriggerManual: "manual",
    aiSweepTriggerCron: "cron",
  },
};

function fmt(lang, key, vars) {
  const dict = I18N[lang] || I18N.en;
  let base = dict[key] || (I18N.en[key] || key);
  const v = vars || {};
  for (const n of Object.keys(v)) {
    base = base.split(`{${n}}`).join(String(v[n]));
  }
  return base;
}

const fNum = (v, d = 3) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "N/A" : Number(v).toFixed(d);
const fInt = (v) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "N/A" : new Intl.NumberFormat("en-US").format(Number(v));
const fRate = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "N/A" : `${(Number(v) * 100).toFixed(d)}%`;

function fBytes(value) {
  const n = Number(value || 0);
  if (n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let idx = 0;
  let num = n;
  while (num >= 1024 && idx < units.length - 1) {
    num /= 1024;
    idx += 1;
  }
  return `${num.toFixed(idx === 0 ? 0 : 2)} ${units[idx]}`;
}

function cacheRiskTier(bytes, thresholds) {
  const b = Number(bytes || 0);
  const t = thresholds || {};
  const mid = Number(t.medium_bytes != null ? t.medium_bytes : 512 * 1024 * 1024);
  const high = Number(t.high_bytes != null ? t.high_bytes : 2 * 1024 * 1024 * 1024);
  if (b <= 0) return "none";
  if (b >= high) return "high";
  if (b >= mid) return "medium";
  return "low";
}

function cacheRiskView(lang, cachedStatus) {
  const c = cachedStatus || {};
  const bytes = Number(c.reclaimable_bytes_estimate || 0);
  const tier = cacheRiskTier(bytes, c.risk_thresholds);
  const tierKey =
    tier === "high" ? "riskHigh" : tier === "medium" ? "riskMedium" : tier === "low" ? "riskLow" : "riskNone";
  const tierLabel = fmt(lang, tierKey);
  const hintKey =
    tier === "high"
      ? "cacheRiskHighHint"
      : tier === "medium"
      ? "cacheRiskMediumHint"
      : tier === "low"
      ? "cacheRiskLowHint"
      : "cacheRiskNoneHint";
  return { bytes, tier, tierLabel, hint: fmt(lang, hintKey) };
}

function statusText(lang, s) {
  const raw = String(s || "unknown");
  const k = `status${raw.charAt(0).toUpperCase()}${raw.slice(1)}`;
  const dict = I18N[lang] || I18N.en;
  return k in dict ? dict[k] : fmt(lang, "statusUnknown");
}

// CI half-width tier picker. "0" is the fuzzy tier: CI stop disabled,
// sampling relies on max_chunks to cover ~1M spins (handled backend-side).
function ciTierOptions(lang) {
  return [
    { value: "0.5", label: fmt(lang, "ciOption05") },
    { value: "1", label: fmt(lang, "ciOption1") },
    { value: "2", label: fmt(lang, "ciOption2") },
    { value: "5", label: fmt(lang, "ciOption5") },
    { value: "0", label: fmt(lang, "ciOptionFuzzy") },
  ];
}

// Bankroll multiplier presets for bankruptcy probe. Only the "standard"
// preset aligns with the hard-coded x100/x200/x500 thresholds in
// guideline_assessment + configs/classic_slots_guideline_rules.json;
// other presets sample different points and skip the A5 rule.
function bankrollMultiplierPresets(lang) {
  // 10x is prepended to every preset as a fixed short-play / panic
  // baseline column (user ask 2026-04-22: "最前面加一列 10x 的分析").
  // The remaining 3 tiers still differentiate session strategies,
  // and guideline rules' A5 bankruptcy thresholds still look at
  // x100/x200/x500 — only Standard hits all three.
  return [
    { value: "10,100,200,500", label: fmt(lang, "bankMultStandard") },
    { value: "10,50,100,200", label: fmt(lang, "bankMultShort") },
    { value: "10,200,500,1000", label: fmt(lang, "bankMultLong") },
  ];
}

// Default fuzzy target spins; mirrors backend.RunManager.FUZZY_TARGET_TOTAL_SPINS.
const FUZZY_TARGET_SPINS_DEFAULT = 1_000_000;

function _formatThousands(n) {
  if (n == null || Number.isNaN(Number(n))) return "?";
  return new Intl.NumberFormat("en-US").format(Number(n));
}

// One-line readable summary of the latest jsonl event from a run. Used in
// the runMeta panel between status and the legacy events textarea.
function summarizeRunEvent(lang, ev, opts) {
  const o = opts || {};
  const target = o.target;
  const isFuzzy = o.isFuzzy === true;
  const maxChunks = Number(o.maxChunks || 0);
  const fuzzyTarget = Number(o.fuzzyTarget || FUZZY_TARGET_SPINS_DEFAULT);
  if (ev == null) return fmt(lang, "runEventNone");
  const phase = ev.event;

  if (phase === "started") {
    return fmt(lang, isFuzzy ? "runEventStartedFuzzy" : "runEventStarted", {
      machine: ev.machine != null ? ev.machine : "?",
      mode: ev.mode != null ? ev.mode : "?",
      target: target != null ? `${target}pp` : "?",
    });
  }

  if (phase === "chunk_progress") {
    const idx = ev.chunk_index != null ? ev.chunk_index : "?";
    const spins = _formatThousands(ev.total_spins);
    const rtp = ev.current_rtp_pct != null ? Number(ev.current_rtp_pct).toFixed(2) : "?";
    const ci = ev.current_halfwidth_pp != null
      ? Number(ev.current_halfwidth_pp).toFixed(3)
      : "?";
    if (isFuzzy) {
      const pct = fuzzyTarget > 0 && ev.total_spins != null
        ? Math.min(100, (Number(ev.total_spins) / fuzzyTarget) * 100).toFixed(1)
        : "?";
      return fmt(lang, "runEventChunkFuzzy", { idx, spins, rtp, pct });
    }
    return fmt(lang, "runEventChunk", {
      idx, max: maxChunks || "?", spins, rtp, ci,
    });
  }

  if (phase === "completed") {
    const spins = _formatThousands(ev.total_spins);
    const rtp = ev.rtp_point_pct != null ? Number(ev.rtp_point_pct).toFixed(2) : "?";
    const sec = ev.duration_seconds != null ? Number(ev.duration_seconds).toFixed(0) : "?";
    if (isFuzzy) {
      return fmt(lang, "runEventCompletedFuzzy", { spins, rtp, sec });
    }
    const ciInt = Array.isArray(ev.ci95_interval_pct) && ev.ci95_interval_pct.length === 2
      ? ((ev.ci95_interval_pct[1] - ev.ci95_interval_pct[0]) / 2).toFixed(3)
      : "?";
    return fmt(lang, "runEventCompleted", { spins, rtp, ci: ciInt, sec });
  }

  if (phase === "failed") {
    return fmt(lang, "runEventFailed", { reason: ev.reason || "?" });
  }

  return fmt(lang, "runEventNone");
}

// 0..100 number suitable for the progress bar width.
// Non-fuzzy: chunks completed / max_chunks.
// Fuzzy: total_spins / fuzzy_target.
function computeRunProgressPct(latestEvent, opts) {
  const o = opts || {};
  const isFuzzy = o.isFuzzy === true;
  const maxChunks = Number(o.maxChunks || 0);
  const fuzzyTarget = Number(o.fuzzyTarget || FUZZY_TARGET_SPINS_DEFAULT);
  if (latestEvent == null) return 0;
  if (isFuzzy) {
    const spins = Number(latestEvent.total_spins || 0);
    if (fuzzyTarget <= 0) return 0;
    return Math.max(0, Math.min(100, (spins / fuzzyTarget) * 100));
  }
  const idx = Number(latestEvent.chunk_index || 0);
  if (maxChunks <= 0) return 0;
  return Math.max(0, Math.min(100, (idx / maxChunks) * 100));
}

// Compute the percentile rank of `value` within `values`. Returns the
// count of values <= value as a percentage of total (0-100), or null
// when the sample is empty, too small, or value is invalid. The
// caller decides how to format: "P87" for a population of 17+,
// "rank/total" for smaller libraries where a single-digit percentile
// is noisy.
function computeLibPercentile(value, values) {
  if (value == null || Number.isNaN(Number(value))) return null;
  if (!Array.isArray(values)) return null;
  const v = Number(value);
  const sorted = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  if (sorted.length === 0) return null;
  let le = 0;
  for (const x of sorted) if (x <= v) le++;
  return {
    percentile: (le / sorted.length) * 100,
    rank: le,
    total: sorted.length,
  };
}

// Format a library-rank suffix for a KPI card. Small library (<3
// machines) shows "lib-N/M"; bigger shows "lib-P{percentile} (N/M)"
// so the operator always sees the raw fraction too.
function formatLibRank(rank, lang) {
  if (!rank || rank.total <= 0) return "";
  if (rank.total < 3) {
    return fmt(lang, "libRankSmall", {
      rank: rank.rank,
      total: rank.total,
    });
  }
  const p = rank.percentile;
  const pText = p >= 99 ? "P99+" : `P${Math.round(p)}`;
  return fmt(lang, "libRank", {
    p: pText,
    rank: rank.rank,
    total: rank.total,
  });
}

// Pretty-print analyzer's multiplier-bucket key into a chart-friendly
// label ("100-200" instead of "ge100_lt200"). Falls back to the raw
// key for unknown buckets so an old report's labels still render.
function prettyBucketLabel(key) {
  switch (key) {
    case "eq0":            return "0";
    case "gt0_lt1":        return "0\u20131";
    case "ge1_lt5":        return "1\u20135";
    case "ge5_lt10":       return "5\u201310";
    case "ge10_lt20":      return "10\u201320";
    case "ge20_lt50":      return "20\u201350";
    case "ge50_lt100":     return "50\u2013100";
    case "ge100_lt200":    return "100\u2013200";
    case "ge200_lt500":    return "200\u2013500";
    case "ge500_lt1000":   return "500\u20131000";
    case "ge1000_lt5000":  return "1000\u20135000";
    case "ge5000":         return "\u22655000";
    // Legacy bucket labels (old reports) -- best-effort pretty form.
    case "gt0_lt0.5":      return "0\u20130.5";
    case "ge0.5_lt1":      return "0.5\u20131";
    case "ge1_lt2":        return "1\u20132";
    case "ge2_lt5":        return "2\u20135";
    case "ge100":          return "\u2265100";
    default:               return String(key);
  }
}

// Format payout_groups_top20 (added by analyzer commit 9). Sorts by
// rtp_contribution_pp descending so the most impactful pay groups
// appear first; group_id 0 is kept in the list (it always carries the
// non-winning spins and is useful as a reference baseline).
function formatPayoutGroupRows(summary) {
  const rows = ((summary || {}).player_impact || {}).payout_groups_top20 || [];
  const ranked = [...rows].sort(
    (a, b) =>
      Number(b.rtp_contribution_pp || 0) - Number(a.rtp_contribution_pp || 0)
  );
  return ranked.map((r) => ({
    group_id: Number(r.group_id != null ? r.group_id : 0),
    hit_count: Number(r.hit_count || 0),
    hit_rate_pct: Number(r.hit_rate || 0) * 100,
    avg_win_when_hit_x: Number(r.avg_win_when_hit_x || 0),
    rtp_contribution_pp: Number(r.rtp_contribution_pp || 0),
  }));
}

// Format spin_type_breakdown (added in the SpinType-breakdown commit).
// Returns rows ready for <td> rendering. spin_type semantics are
// machine-specific (M14: 1 only; M272: 140 main + 126 bonus); the
// helper just formats whatever the analyzer aggregated. Sorted by
// spins desc to match the analyzer's output.
function formatSpinTypeRows(summary) {
  const rows = ((summary || {}).player_impact || {}).spin_type_breakdown || [];
  return rows.map((r) => ({
    spin_type: Number(r.spin_type != null ? r.spin_type : 0),
    // behavior_name is "paid" / "free" / "mixed" (derived by the
    // analyzer from per-type CostCredits>0 round count). Old reports
    // may lack it -- leave empty so the UI renders "—".
    behavior_name: String(r.behavior_name || ""),
    spins: Number(r.spins || 0),
    share_pct: Number(r.share_pct || 0),
    win_rounds: Number(r.win_rounds || 0),
    hit_rate_pct: Number(r.hit_rate || 0) * 100,
    total_win: Number(r.total_win || 0),
    // rtp_pct is null (JSON) for all-free types (paid_bet denominator
    // is 0) -- pass null through so the UI can render "N/A". Legacy
    // rows always had a numeric rtp_pct; we still show those.
    rtp_pct: r.rtp_pct === null || r.rtp_pct === undefined ? null : Number(r.rtp_pct),
    rtp_contribution_pp: Number(r.rtp_contribution_pp || 0),
    rare: Boolean(r.rare),
  }));
}

// Format payout_ids_top20 (added in the PayoutIdToWinAmount commit).
// This is the actual payout-source breakdown (M14 + M272 both populate
// it); the older payout_groups_top20 is kept as a fallback for legacy
// reports. Sorts by rtp_contribution_pp desc so the dominant payout
// source lands at the top of the table.
function formatPayoutIdRows(summary) {
  const rows = ((summary || {}).player_impact || {}).payout_ids_top20 || [];
  const ranked = [...rows].sort(
    (a, b) =>
      Number(b.rtp_contribution_pp || 0) - Number(a.rtp_contribution_pp || 0)
  );
  return ranked.map((r) => ({
    payout_id: String(r.payout_id != null ? r.payout_id : "?"),
    hit_count: Number(r.hit_count || 0),
    hit_rate_pct: Number(r.hit_rate || 0) * 100,
    total_win: Number(r.total_win || 0),
    avg_win_when_hit: Number(r.avg_win_when_hit || 0),
    rtp_contribution_pp: Number(r.rtp_contribution_pp || 0),
  }));
}

// Format the overall symbols_top20 table. Returns rows ready for <td>.
function formatSymbolRows(summary) {
  const rows = ((summary || {}).player_impact || {}).symbols_top20 || [];
  return rows.map((r) => ({
    symbol: String(r.symbol != null ? r.symbol : "?"),
    count: Number(r.count || 0),
    rate_pct: Number(r.rate || 0) * 100,
  }));
}

// Build a column-major matrix from symbols_by_column_top10. Returns:
//   { columnIds: ["0", "1", ...], rowsByCol: { "0": [...], "1": [...] } }
// Each row is {symbol, count, rate_pct}. Useful for rendering as a side-by
// -side per-column table in the UI.
function symbolByColMatrix(summary) {
  const pi = (summary || {}).player_impact || {};
  const byCol = pi.symbols_by_column_top10 || {};
  // 2026-04-24: payline-density sibling of by-col distribution.
  // Analyzer derives per-column payline row mask from observed
  // PayoutByPayline positions (multi-payline aware, no spec dependency).
  // Classic single-payline slots (M1 / M37): row=[1] (mid) per column.
  // Multi-payline machines: row=[0, 1, 2] or V-shape subsets per column.
  // "symbols_by_column_top10_payline" is the same shape as
  // "symbols_by_column_top10" but counted only on payline rows.
  const byColPayline = pi.symbols_by_column_top10_payline || {};
  const paylineRowsPerCol = pi.payline_rows_per_col || {};
  const columnIds = Object.keys(byCol).sort((a, b) => Number(a) - Number(b));
  const rowsByCol = {};
  const paylineByCol = {};   // col -> {symbol: {count, rate_pct}} (quick lookup)
  const paylineRowsByCol = {}; // col -> [row_indices] (for header label)
  for (const col of columnIds) {
    const list = Array.isArray(byCol[col]) ? byCol[col] : [];
    rowsByCol[col] = list.map((r) => ({
      symbol: String(r.symbol != null ? r.symbol : "?"),
      count: Number(r.count || 0),
      rate_pct: Number(r.rate || 0) * 100,
    }));
    const plList = Array.isArray(byColPayline[col]) ? byColPayline[col] : [];
    const plMap = {};
    for (const r of plList) {
      plMap[String(r.symbol != null ? r.symbol : "?")] = {
        count: Number(r.count || 0),
        rate_pct: Number(r.rate || 0) * 100,
      };
    }
    paylineByCol[col] = plMap;
    paylineRowsByCol[col] = Array.isArray(paylineRowsPerCol[col])
      ? paylineRowsPerCol[col].map((n) => Number(n))
      : [];
  }
  return { columnIds, rowsByCol, paylineByCol, paylineRowsByCol };
}

// Build display rows for the paylines drilldown table. Sorted by the
// requested column descending (default: approx_rtp_contribution_pp).
// Returns objects ready to drop into <td>.
function formatPaylineRows(summary, sortBy) {
  const rows = ((summary || {}).player_impact || {}).paylines_top20 || [];
  const sortKey = sortBy || "approx_rtp_contribution_pp";
  const ranked = [...rows].sort(
    (a, b) => Number(b[sortKey] || 0) - Number(a[sortKey] || 0)
  );
  const totalRtp = ranked.reduce(
    (acc, r) => acc + Number(r.approx_rtp_contribution_pp || 0),
    0
  );
  return ranked.map((r) => {
    const rtp = Number(r.approx_rtp_contribution_pp || 0);
    // top_symbols was added by the payline-winning-symbol commit.
    // Old reports omit it; keep an empty array so the table renders
    // cleanly across both schemas.
    const topSymbols = Array.isArray(r.top_symbols) ? r.top_symbols : [];
    return {
      payline_id: String(r.payline_id != null ? r.payline_id : "?"),
      payline_id_num: Number(r.payline_id),
      hit_count: Number(r.hit_count || 0),
      hit_rate_pct: Number(r.hit_rate || 0) * 100,
      rtp_contribution_pp: rtp,
      win_share_pct: Number(r.approx_rtp_contribution_pp != null && totalRtp > 0
        ? rtp / totalRtp
        : 0) * 100,
      top_symbols: topSymbols.map((t) => ({
        symbol: String((t && t.symbol) != null ? t.symbol : ""),
        count: Number((t && t.count) || 0),
      })),
      // ``top_symbols_source``: "rln" (authoritative, from
      // RewardLastNode codes) vs "heuristic" (left-3-column
      // intersection fallback). UI surfaces this so 策划 knows
      // whether to trust the symbol list at face value.
      top_symbols_source: r.top_symbols_source
        ? String(r.top_symbols_source)
        : null,
    };
  });
}

// Pretty-print top winning symbols for a payline as "sym1, sym2, sym3"
// truncated to the top N (default 3). Returns "—" when the payline has
// no inferred symbols (old report or no winning spins).
function formatPaylineTopSymbols(topSymbols, n) {
  const limit = Number.isFinite(n) && n > 0 ? Math.floor(n) : 3;
  const arr = Array.isArray(topSymbols) ? topSymbols : [];
  if (!arr.length) return "\u2014";
  return arr
    .slice(0, limit)
    .map((t) => (t && t.symbol ? String(t.symbol) : ""))
    .filter((s) => s.length)
    .join(", ");
}

// Pull all KPI card values out of a player_impact_summary.json shape and
// classify each into a tone (good / warn / bad / neutral). Returns
// {[id]: {value, tone}}. Tone thresholds mirror guideline rules so the
// frontend doesn't need to re-derive them from the alerts list.
function extractMetricCards(summary, lang) {
  const s = summary || {};
  const rtp = s.rtp || {};
  const sampling = s.sampling || {};
  const player = s.player_impact || {};
  const hit = player.hit_and_payout || {};
  const vol = player.volatility || {};
  const streaks = player.streaks || {};
  const ga = s.guideline_assessment || {};
  const cls = ga.classification || {};
  const derived = ga.derived_metrics || {};

  const num = (v, fn) => (v == null ? "N/A" : fn(Number(v)));
  const pct = (v, d = 2) => (v == null ? "N/A" : `${(Number(v) * 100).toFixed(d)}%`);

  // tone helpers (paid-round oriented)
  const toneZeroWin = (v) =>
    v == null ? "neutral" : v > 0.82 ? "bad" : v > 0.75 ? "warn" : "good";
  const toneTailDep = (v) =>
    v == null ? "neutral" : v >= 0.5 ? "bad" : v >= 0.45 ? "warn" : v >= 0.2 ? "neutral" : "good";
  const toneLossStreak = (v) =>
    v == null ? "neutral" : v >= 18 ? "bad" : v >= 15 ? "warn" : "good";

  // Archetype → plain-Chinese label via i18n. Keeps the raw key on
  // `raw` for tooltip / debug use. Falls back to raw when the lang
  // bundle doesn't carry a mapping (e.g. a new archetype is added
  // upstream before we ship the translation).
  const archetypeKey = cls.experience_archetype || "";
  const archetypeI18nKey = {
    "Boom-Bust": "archetypeBoomBust",
    "Balanced": "archetypeBalanced",
    "Grindy": "archetypeGrindy",
  }[archetypeKey];
  const archetypeHintKey = {
    "Boom-Bust": "archetypeBoomBustHint",
    "Balanced": "archetypeBalancedHint",
    "Grindy": "archetypeGrindyHint",
  }[archetypeKey];
  const archetypeValue = archetypeI18nKey
    ? fmt(lang || "zh", archetypeI18nKey)
    : (archetypeKey || "N/A");
  const archetypeHint = archetypeHintKey
    ? fmt(lang || "zh", archetypeHintKey)
    : "";

  return {
    rtp: { value: num(rtp.point_pct, (x) => `${x.toFixed(2)}%`), tone: "neutral" },
    ci: { value: num(sampling.achieved_halfwidth_pp, (x) => x.toFixed(3)), tone: "neutral" },
    spins: {
      // Prefer paid_spins over total_spins when present (paid-round is
      // the default metric unit per user spec). Falls back to total
      // spins if the summary is pre-migration.
      value: (() => {
        const v = sampling.paid_spins ?? sampling.total_spins;
        if (v == null) return "N/A";
        return new Intl.NumberFormat("en-US").format(Number(v));
      })(),
      tone: "neutral",
    },
    zeroWin: { value: pct(hit.zero_win_rate), tone: toneZeroWin(hit.zero_win_rate) },
    tailDep: (() => {
      // 2×2 grid rendered by app.js. Value is the primary (ge10x)
      // rate; sub is now unused (decay is visible across the 4 tiles).
      const d10 = derived.tail_dependency_ge10x ?? derived.tail_dependency;
      return {
        value: num(d10, (x) => x.toFixed(3)),
        tone: toneTailDep(d10),
      };
    })(),
    // Volatility card keeps no primary number — only lib-rank sub line
    // (populated by applyLibraryRanking). Tone neutral.
    volatility: { value: "", tone: "neutral" },
    // Archetype card shows human-readable phrase; tooltip hint via
    // `sub` if you want to display it (app.js can render it in the
    // secondary line when no lib-rank is present).
    archetype: {
      value: archetypeValue,
      tone: "neutral",
      raw: archetypeKey,
      hint: archetypeHint,
    },
    lossStreak: {
      value: streaks.loss_streak_p95 == null ? "N/A" : String(streaks.loss_streak_p95),
      tone: toneLossStreak(streaks.loss_streak_p95),
    },
    maxReturn: {
      value: num(vol.max_observed_return_x, (x) => `${x.toFixed(1)}x`),
      tone: "neutral",
    },
    // Big-win rate: now a 4-tile grid (≥10/≥20/≥50/≥100 of bet inside
    // a paid round). Shape mirrors tailDep so app.js can render both
    // with the same 2×2 helper.
    bigWin: (() => {
      const r10 = hit.big_win_x10_rate;
      const r20 = hit.big_win_x20_rate;
      const r50 = hit.big_win_x50_rate;
      const r100 = hit.big_win_x100_rate;
      return {
        value: pct(r10, 3),
        tone: "neutral",
        tiles: { ge10: r10, ge20: r20, ge50: r50, ge100: r100 },
      };
    })(),
  };
}

// Multi-line readable autotune progress for the autotuneMeta panel.
// Input is the dict returned by GET /api/autotune/progress.
function formatAutotuneProgress(lang, progress) {
  const p = progress || {};
  const status = String(p.status || "idle");
  const done = Number(p.completed_candidates || 0);
  const total = Number(p.total_candidates || 0);
  if (status === "idle") return fmt(lang, "autotuneProgressIdle");
  if (status === "running" && total === 0) return fmt(lang, "autotuneProgressStarting");
  const pctText = total > 0 ? `${((done / total) * 100).toFixed(0)}%` : "?";
  const lines = [];
  if (status === "completed") {
    lines.push(fmt(lang, "autotuneProgressDone", { total }));
  } else if (status === "error") {
    lines.push(fmt(lang, "autotuneProgressError", { done, total }));
  } else {
    lines.push(fmt(lang, "autotuneProgressLine1", { done, total, pctText }));
  }
  const last = p.last_result;
  if (last) {
    const sr = last.success_rate != null ? `${(Number(last.success_rate) * 100).toFixed(1)}%` : "?";
    const tp = last.throughput_spins_per_sec != null
      ? Number(last.throughput_spins_per_sec).toFixed(0)
      : "?";
    const p95 = last.p95_latency_s != null ? Number(last.p95_latency_s).toFixed(3) : "?";
    lines.push(
      fmt(lang, "autotuneProgressLast", {
        rc: last.robot_count != null ? last.robot_count : "?",
        cc: last.batch_concurrency != null ? last.batch_concurrency : "?",
        sr,
        tp,
        p95,
      })
    );
  }
  return lines.join("\n");
}

// Build a readable failure note for runMeta. The backend now always puts
// at least `analyzer exit_code=N | summary missing: ... | report missing: ...`
// into error_message; the fallback covers older rows or the corner case
// where the message is empty for some reason.
function formatRunFailureNote(lang, errorMsg) {
  const trimmed = (errorMsg == null ? "" : String(errorMsg)).trim();
  if (!trimmed) return fmt(lang, "runFailureNoneCaptured");
  return trimmed;
}

// Pure validator used by the frontend to gate the Start button. Returns
// {blocking: string[], warnings: string[], canStart: bool}. Blocking
// strings are localized and meant to be shown to the operator.
function validateRunConfig(opts) {
  const o = opts || {};
  const mode = Number(o.mode);
  const halfwidthPp = o.halfwidthPp;
  const rc = o.robotCount;
  const cc = o.concurrency;
  const lang = o.lang || "en";
  const blocking = [];
  const warnings = [];

  if ((mode === 2 || mode === 5) && Number(halfwidthPp) !== 0) {
    blocking.push(fmt(lang, "validateMode25RequireFuzzy"));
  }
  const missingConc =
    rc === null ||
    rc === undefined ||
    rc === "" ||
    Number(rc) <= 0 ||
    cc === null ||
    cc === undefined ||
    cc === "" ||
    Number(cc) <= 0;
  if (missingConc) {
    blocking.push(fmt(lang, "validateConcurrencyRequired"));
  }

  return { blocking, warnings, canStart: blocking.length === 0 };
}

function modelWarnings(opts) {
  const o = opts || {};
  const provider = o.provider || "";
  const selected = o.selected || "";
  const catalog = o.catalog || {};
  const hasApiKey = Boolean(o.hasApiKey);
  const lang = o.lang || "en";
  const models = (catalog[provider] || []).map(String);
  const out = [];
  if (selected && models.length && !models.includes(selected)) {
    out.push(fmt(lang, "warnModelMismatch"));
  }
  if (!hasApiKey) {
    out.push(fmt(lang, "warnApiKeyEmpty", { provider: provider.toUpperCase() }));
  }
  return out;
}

function collectSystemWarnings(opts) {
  const o = opts || {};
  const lang = o.lang || "en";
  const systemState = o.systemState || null;
  const out = [];
  const startup = (systemState && systemState.startup_recovery) || {};
  const recovered = Number(startup.recovered_count || 0);
  const failedPids = Number(
    Array.isArray(startup.failed_to_terminate_pids) ? startup.failed_to_terminate_pids.length : 0
  );
  if (recovered > 0) out.push(fmt(lang, "warnRecovered", { count: recovered }));
  if (failedPids > 0) out.push(fmt(lang, "warnRecoveredPidRisk", { count: failedPids }));
  if (systemState && systemState.operation_busy) {
    out.push(fmt(lang, "warnSystemBusy", { op: systemState.operation_name || "unknown" }));
  }
  return out;
}

// ---------- sampling log timeline ----------

/**
 * Build a synthetic UI-origin lifecycle event for the sampling log.
 * These are the "missing" observable moments between a user click and
 * the first analyzer chunk_progress event: submit-in-flight, batch
 * created, submit failed. Without them the log stays empty for the
 * 30-60s it takes an analyzer to produce its first chunk, which reads
 * as "the app is stuck".
 *
 * @param {string} kind - "click" | "submit" | "batch_created" | "submit_failed" | "polling_started"
 * @param {object} data - kind-specific payload
 * @param {string} [nowIso] - ISO timestamp (tests inject; production omits → uses new Date().toISOString())
 */
function buildClientEvent(kind, data, nowIso) {
  const ts = nowIso || new Date().toISOString();
  const modeStr = data && data.mode != null ? `mode=${data.mode}` : "";
  const ciStr = data && data.ci != null
    ? (data.ci === 0 ? "fuzzy" : data.ci + "pp")
    : "";
  const detail = [modeStr, ciStr ? `ci=${ciStr}` : ""].filter(Boolean).join(" · ");
  switch (kind) {
    case "click":
      return {
        ts, level: "info", source: "ui",
        text: `▷ 开始采样 · 已选 ${(data && data.count) || 0} 台${detail ? " · " + detail : ""}`,
      };
    case "submit":
      return { ts, level: "info", source: "ui", text: "⋯ 提交批次请求…" };
    case "batch_created":
      return {
        ts, level: "info", source: "ui",
        text: `⋓ 批次 ${(data && data.batchId ? data.batchId.slice(0, 8) : "?")} 已创建`,
      };
    case "submit_failed":
      return {
        ts, level: "error", source: "ui",
        text: `✗ 提交失败: ${(data && data.error) || "unknown"}`,
      };
    case "polling_started":
      return { ts, level: "info", source: "ui", text: "◷ 开始轮询进度…" };
    case "md5_refresh_start":
      return { ts, level: "info", source: "ui", text: "⟳ md5 刷新中…" };
    case "md5_refresh_done": {
      const fetched = (data && data.fetched != null) ? data.fetched : 0;
      const updated = (data && data.updated != null) ? data.updated : 0;
      if (updated > 0) {
        // Fleet shifted — warn so the operator notices. Include
        // machine names so they can immediately tell if THEIR
        // working machine is one of them. Before names were shown
        // (2026-04-21), operators would see "3/253 台有变更" after
        // restart and reasonably assume their just-sampled M1 had
        // drifted when actually some unrelated machine shifted.
        // Truncate at 5 names to keep the line scannable; full
        // list is still in the response body for debugging.
        const names = (data && Array.isArray(data.updated_machines))
          ? data.updated_machines
          : [];
        let namePart = "";
        if (names.length > 0) {
          const shown = names.slice(0, 5).join(", ");
          const extra = names.length > 5 ? ` (+${names.length - 5})` : "";
          namePart = ` · ${shown}${extra}`;
        }
        return {
          ts, level: "warn", source: "ui",
          text: "✓ md5 刷新: " + updated + "/" + fetched + " 台有变更" + namePart,
        };
      }
      return {
        ts, level: "info", source: "ui",
        text: "✓ md5 刷新: " + fetched + " 台无变更",
      };
    }
    case "md5_refresh_failed":
      return {
        ts, level: "warn", source: "ui",
        text: "⚠ md5 刷新失败（沿用本地缓存）: " + ((data && data.error) || "unknown"),
      };
    case "generate_report_start": {
      // 2026-04-22: click on rwtree ⟳ 生成 Report must produce an
      // immediate activity-log entry. Before the fix the click
      // silently kicked off a 30-90s analyzer replay with no log
      // trail — user "没法确认状态".
      const m = (data && data.machine) || "?";
      const mo = (data && data.mode != null) ? data.mode : "?";
      return {
        ts, level: "info", source: "ui",
        text: `⋯ 生成 Report · ${m} mode ${mo} …`,
      };
    }
    case "generate_report_done": {
      const m = (data && data.machine) || "?";
      const mo = (data && data.mode != null) ? data.mode : "?";
      const rtp = (data && data.rtp_pct != null)
        ? Number(data.rtp_pct).toFixed(2) + "%"
        : "—";
      const ci = (data && data.halfwidth_pp != null)
        ? "±" + Number(data.halfwidth_pp).toFixed(2) + "pp"
        : "—";
      return {
        ts, level: "info", source: "ui",
        text: `✓ 生成完成 · ${m} mode ${mo} · RTP ${rtp} · CI ${ci}`,
      };
    }
    case "generate_report_failed": {
      const m = (data && data.machine) || "?";
      const mo = (data && data.mode != null) ? data.mode : "?";
      const err = (data && data.error) || "unknown";
      return {
        ts, level: "error", source: "ui",
        text: `✗ 生成失败 · ${m} mode ${mo} · ${err}`,
      };
    }
    case "generate_report_timeout": {
      const m = (data && data.machine) || "?";
      const mo = (data && data.mode != null) ? data.mode : "?";
      const last = (data && data.last_status) || "unknown";
      return {
        ts, level: "warn", source: "ui",
        text: `⏱ 生成轮询超时 · ${m} mode ${mo} · last=${last}（后台可能仍在跑）`,
      };
    }
    default:
      return { ts, level: "info", source: "ui", text: `? ${kind}` };
  }
}

/**
 * Format a chunk-level event (from analyzer progress.jsonl) as a
 * one-line timeline row text. Keeps rendering logic off the impure
 * side so we can snapshot-test the text shape.
 */
function formatChunkEventText(ev) {
  if (!ev || !ev.event) return "";
  const fInt_ = (x) => (x == null ? "—" : Number(x).toLocaleString());
  if (ev.event === "chunk_progress") {
    // Prefer session_rtp_pct (paid-session denominator, matches final
    // summary's rtp.point_pct). Fall back to current_rtp_pct (spin-
    // level, under-reports on collect-mechanic machines) for events
    // from pre-2026-04-17 analyzer builds that didn't emit the new
    // field. On M14 the two are identical; on M272/M273 they diverge.
    const rtpVal = ev.session_rtp_pct != null
      ? ev.session_rtp_pct : ev.current_rtp_pct;
    const rtp = rtpVal != null ? Number(rtpVal).toFixed(2) + "%" : "—";
    const hwRaw = ev.current_halfwidth_pp != null
      ? ev.current_halfwidth_pp : ev.halfwidth_pp;
    const hw = hwRaw != null ? "±" + Number(hwRaw).toFixed(3) + "pp" : "";
    return `chunk ${ev.chunk_index} · ${fInt_(ev.total_spins)} spins · RTP=${rtp} ${hw}`;
  }
  if (ev.event === "chunk_failed") {
    const err = (ev.error || "").slice(0, 80);
    return `✗ chunk ${ev.chunk_index} 失败 · ${err} · 累计失败 ${ev.cumulative_failed}`;
  }
  if (ev.event === "resume_from_cache") {
    return `♻ 续采: 已有 ${ev.existing_chunks || 0} chunks / ${fInt_(ev.existing_spins)} spins · 下一个 chunk_${ev.next_chunk_index}`;
  }
  if (ev.event === "cache_read_start") {
    // 2026-04-26: surface "K 旧 md5 跳过" when md5 pre-filter cut down
    // the iteration list. Pre-fix UX showed only the matching count
    // with no hint that there were historical chunks on disk being
    // ignored — operator wondered why total_chunks was lower than
    // they expected, especially right after a fresh-md5 pull.
    const skipSuffix1 = (ev.md5_skipped && ev.md5_skipped > 0)
      ? ` · 跳过 ${ev.md5_skipped} 个旧 md5`
      : "";
    return `📖 读取已有 ${ev.total_chunks} chunks${skipSuffix1}（静默 replay，约需 ${Math.round((ev.total_chunks || 0) * 0.5)}s）…`;
  }
  if (ev.event === "cache_read_progress") {
    const pct = ev.total_chunks > 0
      ? Math.round((ev.chunks_read / ev.total_chunks) * 100)
      : 0;
    return `📖 已读 ${ev.chunks_read}/${ev.total_chunks} chunks (${pct}%) · ${fInt_(ev.total_spins)} spins`;
  }
  if (ev.event === "cache_read_done") {
    const skipSuffix2 = (ev.md5_skipped && ev.md5_skipped > 0)
      ? ` · 跳过 ${ev.md5_skipped} 个旧 md5`
      : "";
    return `📖 已读完 ${ev.chunks_read} chunks · ${fInt_(ev.total_spins)} spins${skipSuffix2}，进入采样阶段`;
  }
  if (ev.event === "cache_read_target_met") {
    const ci = ev.current_halfwidth_pp != null ? Number(ev.current_halfwidth_pp).toFixed(2) : "?";
    const tgt = ev.target_halfwidth_pp != null ? Number(ev.target_halfwidth_pp).toFixed(2) : "?";
    return `✓ 已有 ${ev.chunks_read} chunks 的 CI=±${ci}pp 已满足目标 ±${tgt}pp，提前结束读取 + 跳过新采样`;
  }
  if (ev.event === "non_convergence_abort") {
    // Tier-2 early bail for bug / in-dev machines. Render the
    // reason + the key numbers so operator can triage without
    // opening the progress file.
    if (ev.reason === "rtp_out_of_band") {
      const rtp = ev.rtp_pct != null ? Number(ev.rtp_pct).toFixed(2) : "?";
      const lo = ev.band_lo_pct ?? "?";
      const hi = ev.band_hi_pct ?? "?";
      return `⛔ 非收敛早退 · RTP=${rtp}% 连续 ${ev.consecutive} chunks 超出合理区间 [${lo}-${hi}]% · 已采 ${ev.chunks} chunks (mode ${ev.mode})`;
    }
    if (ev.reason === "projected_budget_exceeded") {
      const ci = ev.current_ci_pp != null ? Number(ev.current_ci_pp).toFixed(2) : "?";
      const tgt = ev.target_ci_pp != null ? Number(ev.target_ci_pp).toFixed(2) : "?";
      return `⛔ 非收敛早退 · 预计需 ${ev.projected_chunks}+ chunks 才能从 ±${ci}pp 收敛到 ±${tgt}pp（远超预算 ${ev.budget_ceiling}）· 已采 ${ev.chunks}`;
    }
    return `⛔ 非收敛早退 · ${ev.reason || "unknown"}`;
  }
  if (ev.event === "disk_guard_stop") {
    return `⛔ 磁盘低 ${ev.free_gb}GB < ${ev.threshold_gb}GB · 自动停止`;
  }
  if (ev.event === "failed") {
    return `⛔ 终止: ${(ev.reason || "").slice(0, 120)}`;
  }
  if (ev.event === "analyzer_started") {
    return `⚙ analyzer 就绪 · pid=${ev.pid || "?"}`;
  }
  if (ev.event === "fetching_chunk") {
    return `⇅ 请求 chunk ${ev.chunk_index}…`;
  }
  if (ev.event === "chunk_started") {
    // Not rendered in the unified timeline (filtered by mergeTimeline);
    // the in-flight section shows these with live elapsed tickers.
    // Fallback text only used if a caller renders one directly.
    return `⇅ chunk ${ev.chunk_index} 发出`;
  }
  if (ev.event === "adaptive_tune") {
    const arrow = ev.direction === "down" ? "↓" : "↑";
    const reasonMap = {
      fully_failed_batch: "整批失败",
      success_streak: "连续成功",
    };
    const reason = reasonMap[ev.reason] || ev.reason || "";
    return `${arrow} 自适应调参 (${reason}): 并发 ${ev.from_concurrency}→${ev.to_concurrency} · chunk_spins ${ev.from_chunk_spins}→${ev.to_chunk_spins}`;
  }
  if (ev.event === "circuit_pause") {
    return `⏸ 熔断暂停 ${Number(ev.pause_seconds || 0).toFixed(0)}s (${ev.reason || "?"})`;
  }
  return ev.event;
}

/**
 * Elapsed seconds since a client-captured monotonic reference. Used
 * for "t+Ns" ticker on running items so the operator sees that time
 * is passing even when the analyzer is still in its slow initial
 * fetch (30-60s before first chunk_progress emits).
 */
function computeElapsedSeconds(startedAtMs, nowMs) {
  if (!startedAtMs) return null;
  const n = typeof nowMs === "number" ? nowMs : Date.now();
  return Math.max(0, Math.round((n - startedAtMs) / 100) / 10);  // tenths
}

/**
 * Derive the set of in-flight chunks for one batch item: those that
 * have emitted a `chunk_started` event but no matching
 * `chunk_progress` / `chunk_failed` yet (matched by `chunk_index`).
 * Pairs with the analyzer's per-submit emission so the UI can show
 * "⇅ chunk 38 · 等待中 · t+24.3s" rows that tick every poll while the
 * HTTP request is outstanding.
 *
 * Returns: array of { chunk_index, startedTs (ISO string),
 * startedMs (epoch ms) }, sorted by chunk_index.
 *
 * @param {object} item - one entry from data.items
 * @param {number} [nowMs] - Date.now() override for testing
 */
function computeInflightChunks(item /* nowMs — reserved for future use */) {
  if (!item || !Array.isArray(item.chunk_events)) return [];
  const started = {};  // chunk_index → startedTs
  const completed = new Set();  // chunk_index
  for (const ev of item.chunk_events) {
    if (!ev) continue;
    if (ev.event === "chunk_started" && ev.chunk_index != null) {
      started[ev.chunk_index] = ev.ts;
    } else if (
      (ev.event === "chunk_progress" || ev.event === "chunk_failed")
      && ev.chunk_index != null
    ) {
      completed.add(ev.chunk_index);
    }
  }
  const out = [];
  for (const [idx, ts] of Object.entries(started)) {
    const idxN = Number(idx);
    if (completed.has(idxN) || completed.has(idx)) continue;
    const startedMs = Date.parse(ts);
    out.push({
      chunk_index: idxN,
      startedTs: ts,
      startedMs: Number.isFinite(startedMs) ? startedMs : null,
    });
  }
  out.sort((a, b) => a.chunk_index - b.chunk_index);
  return out;
}

/**
 * Merge the three event streams (batch-level, per-item chunk events,
 * client-side lifecycle events) into one chronological timeline
 * suitable for rendering as a single list. Every row carries a
 * `source` tag so the UI can show [M273] / [batch] / [ui].
 *
 * Pruning mirrors the "criticals never, progress last N" rule from
 * the backend:
 *   - critical chunk events (chunk_failed / resume_from_cache /
 *     disk_guard_stop / failed) and all batch-level / ui events
 *     pass through untouched
 *   - chunk_progress is capped to the last `progressCap` per-machine
 *     so a machine that ran 200 chunks doesn't drown out a warning
 *     from a sibling machine
 */
function mergeTimeline(data, clientEvents, progressCap) {
  const cap = progressCap != null ? progressCap : 8;
  const CRITICAL = new Set([
    "chunk_failed", "resume_from_cache", "disk_guard_stop", "failed",
    "analyzer_started", "fetching_chunk",
    // AIMD adaptive-tuning events: rare (once per value change), high
    // signal — the operator needs to see when the analyzer shrank or
    // grew load in response to upstream stress.
    "adaptive_tune", "circuit_pause",
    // 2026-04-21: "reading N existing chunks" progress so the batch
    // log keeps ticking during the silent resume-read phase (a 165-
    // chunk cache takes ~80s to replay; user thought it was stuck).
    "cache_read_start", "cache_read_progress", "cache_read_done",
    // Early-stop signal when cumulative cache CI already meets target
    // — no need to sample any further.
    "cache_read_target_met",
    // Tier-2 non-convergence abort (bug/in-dev machine that can't
    // converge to target CI in a reasonable budget).
    "non_convergence_abort",
  ]);
  const out = [];
  const batchEvents = (data && data.events) || [];
  const items = (data && data.items) || [];

  for (const ev of batchEvents) {
    out.push({
      ts: ev.ts || "",
      level: ev.level || "info",
      source: ev.machine ? `${ev.machine}` : "batch",
      text: ev.text || "",
      kind: "batch",
    });
  }
  for (const it of items) {
    const chunkEvents = it.chunk_events || [];
    // chunk_started events are filtered out — they drive the
    // separate in-flight section (computeInflightChunks), not the
    // timeline. Once a chunk completes its chunk_progress/chunk_failed
    // counterpart carries the same chunk_index so there's no info
    // loss in the timeline from skipping chunk_started here.
    const criticals = chunkEvents.filter(
      (e) => CRITICAL.has(e.event) && e.event !== "chunk_started"
    );
    const progresses = chunkEvents
      .filter((e) => e.event === "chunk_progress")
      .slice(-cap);
    for (const ev of [...criticals, ...progresses]) {
      let level = "info";
      if (ev.event === "chunk_failed") level = "warn";
      else if (ev.event === "disk_guard_stop" || ev.event === "failed") level = "danger";
      else if (ev.event === "adaptive_tune" || ev.event === "circuit_pause") level = "warn";
      else if (ev.event === "non_convergence_abort") level = "danger";
      out.push({
        ts: ev.ts || "",
        level,
        source: it.machine || "?",
        text: formatChunkEventText(ev),
        kind: "chunk",
      });
    }
  }
  for (const ev of clientEvents || []) {
    out.push({
      ts: ev.ts || "",
      level: ev.level || "info",
      source: ev.source || "ui",
      text: ev.text || "",
      kind: "client",
    });
  }
  // Chronological sort; stable on equal ts.
  out.sort((a, b) => (a.ts || "").localeCompare(b.ts || ""));
  return out;
}


// Compare a run row's stored version fingerprints against the
// current server/analyzer values, producing a badge descriptor for
// the Run History table.
//
// Inputs:
//   row     — runs row fields as returned by /api/runs (may have
//             rawdata_config_md5 / rawdata_code_md5 / analyzer_version
//             null on pre-migration legacy rows).
//   current — { analyzer_version, machines: {machine: {config_md5, code_md5}} }
//             from /api/versions/current.
//
// Returns { rawdata: { tier, tip }, analyzer: { tier, tip } } where
// tier ∈ "fresh" | "stale" | "untagged". The caller is responsible
// for picking badge colors / text via i18n using the returned tier.
function versionBadges(row, current) {
  const out = {
    rawdata: { tier: "untagged", tip: "" },
    analyzer: { tier: "untagged", tip: "" },
  };
  if (!row) return out;
  const machines = (current && current.machines) || {};
  const curMachine = machines[row.machine] || {};
  const curCfg = curMachine.config_md5 || "";
  const curCode = curMachine.code_md5 || "";
  const rowCfg = row.rawdata_config_md5 || "";
  const rowCode = row.rawdata_code_md5 || "";
  if (!rowCfg && !rowCode) {
    out.rawdata.tier = "untagged";
    out.rawdata.tip = "untagged";
  } else if (!curCfg && !curCode) {
    // Server not in machines.json (unregistered machine) — can't verify.
    out.rawdata.tier = "untagged";
    out.rawdata.tip = "no upstream md5 reference";
  } else if (rowCfg === curCfg && rowCode === curCode) {
    out.rawdata.tier = "fresh";
    out.rawdata.tip = "server version matches sampling";
  } else {
    out.rawdata.tier = "stale";
    out.rawdata.tip = `cur=${(curCfg || "?").slice(0, 8)}/${(curCode || "?").slice(0, 8)}; row=${(rowCfg || "?").slice(0, 8)}/${(rowCode || "?").slice(0, 8)}`;
  }
  const curAnalyzer = (current && current.analyzer_version) || "";
  const rowAnalyzer = row.analyzer_version || "";
  if (!rowAnalyzer) {
    out.analyzer.tier = "untagged";
    out.analyzer.tip = "untagged";
  } else if (!curAnalyzer) {
    out.analyzer.tier = "untagged";
    out.analyzer.tip = "no current analyzer reference";
  } else if (rowAnalyzer === curAnalyzer) {
    out.analyzer.tier = "fresh";
    out.analyzer.tip = "analyzer code unchanged";
  } else {
    out.analyzer.tier = "stale";
    out.analyzer.tip = `cur=${curAnalyzer.slice(0, 8)}; row=${rowAnalyzer.slice(0, 8)}`;
  }
  return out;
}


// ── rwtree cell predicates ────────────────────────────────────────
//
// Extracted from the inline rwtree cell renderer so the routing /
// "fresh" / "best-CI" rules are headlessly testable. Pure: no DOM
// access, no global state.

/** Reports that are "fresh" for this rwtree cell.
 *
 * "Fresh" means the operator can confidently read RTP/CI from this
 * report as a header-level "样本 RTP" hint for the cell's rawdata.
 *
 * Routing already places each report in the cell whose
 * (config_md5, code_md5) matches the report's stored rawdata md5
 * (see ``_renderRwtreeGrid``). So at the cell level the question
 * "is this report fresh?" reduces to "does this cell describe the
 * rawdata the user is currently sampling against?" — i.e.
 * ``cell.is_current``. The backend marks BOTH server-global current
 * md5 AND localcfg-override current md5 as ``is_current=true``, so
 * localcfg-sampled reports correctly count as fresh in their cell.
 *
 * History (5+ regressions of "无 fresh report" before this one):
 *   - 2026-04-26 (fbf7ff8): the predicate also required
 *     ``analyzer_status === "match"``. Any commit to
 *     ``player_impact_analyzer.py`` (even a docstring) bumped the
 *     analyzer sha256 → every just-generated report turned "stale"
 *     overnight. Dropped the analyzer requirement; per-report ⚠
 *     "Analyzer 过期" badge still surfaces drift.
 *   - 2026-04-25 (8bb531c, f88fe2c): in-process and virtual-analyzer
 *     paths wrote summary.json without stamping config_md5/code_md5
 *     → ``md5_status=untagged`` → not-fresh. Patched both writers.
 *   - 2026-04-27 (THIS FIX): ``/api/report-validate`` compares
 *     report.config_md5 against UPSTREAM md5 only. Localcfg sampling
 *     stamps reports with ``localcfg_<hash>``; upstream is the
 *     server-global md5; the comparison always says "outdated"
 *     even though the report IS the rawdata's report. Fix is
 *     architectural: stop using ``info.md5_status`` at the cell
 *     level (it asks the wrong question for localcfg cells) and
 *     trust ``cell.is_current``, which the backend already computes
 *     correctly for both server-global and localcfg cases.
 *
 * The per-report ⚠ "Analyzer 过期" badge in the row still surfaces
 * analyzer drift as an actionable warning; this helper is just about
 * cell-level "is there a report I can read RTP/CI off?".
 *
 * @param {object} cell — rwtree cell: { is_current, reports }.
 * @returns {Array} subset of cell.reports that are fresh; empty when
 *   cell isn't current (historical cells aren't expected to host a
 *   header-level RTP/CI hint — point-in-time comparisons live in the
 *   reports list itself).
 */
function freshReportsForCell(cell) {
  if (!cell || typeof cell !== "object") return [];
  if (!cell.is_current) return [];
  return Array.isArray(cell.reports) ? cell.reports.slice() : [];
}

/** Should the ⭐ "best CI" marker render in this cell?
 *
 * Only current cells (rawdata md5 == upstream md5) are eligible.
 * Historical cells host reports that are inherently outdated —
 * their best-CI is a within-history comparison, not a comparable
 * "best report". Untagged cells likewise can't be compared.
 *
 * @param {object} cell — { is_current, untagged }
 * @returns {boolean}
 */
function cellShowsBestCiStar(cell) {
  if (!cell || typeof cell !== "object") return false;
  if (cell.untagged) return false;
  return Boolean(cell.is_current);
}


const PURE = {
  I18N,
  fmt,
  fNum,
  fInt,
  fRate,
  fBytes,
  cacheRiskTier,
  cacheRiskView,
  statusText,
  modelWarnings,
  collectSystemWarnings,
  ciTierOptions,
  validateRunConfig,
  bankrollMultiplierPresets,
  formatRunFailureNote,
  summarizeRunEvent,
  computeRunProgressPct,
  formatAutotuneProgress,
  extractMetricCards,
  formatPaylineRows,
  formatPaylineTopSymbols,
  formatSymbolRows,
  symbolByColMatrix,
  formatPayoutGroupRows,
  formatPayoutIdRows,
  formatSpinTypeRows,
  prettyBucketLabel,
  computeLibPercentile,
  formatLibRank,
  buildClientEvent,
  formatChunkEventText,
  computeElapsedSeconds,
  computeInflightChunks,
  mergeTimeline,
  versionBadges,
  freshReportsForCell,
  cellShowsBestCiStar,
};

if (typeof window !== "undefined") window.PURE = PURE;
if (typeof module !== "undefined") module.exports = PURE;

})();
