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
    panelKpi: "关键指标",
    panelBuckets: "倍率分布",
    thBucket: "倍率区间",
    thSpinCount: "次数",
    thSpinRate: "出现率",
    panelCharts: "图形分析",
    panelAssessment: "规则评估",
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
    bankMultStandard: "标准 (100x / 200x / 500x) — 推荐",
    bankMultShort: "短会话 (50x / 100x / 200x)",
    bankMultLong: "长会话 (200x / 500x / 1000x)",
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
    kpiVolatility: "波动性",
    kpiArchetype: "体验类型",
    kpiLossStreak: "P95 败局连",
    kpiMaxReturn: "最大单转倍率",
    kpiBigWin: "10x+ 大奖率",
    kpiBankruptX500: "x500 破产率",
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
    thRate: "占比",
    symbolsEmpty: "暂无符号数据。",
    symbolColLabel: "列 {idx}",
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
    btnInterpret: "生成解读",
    btnRebuild: "基于缓存重建",
    rebuildSuccess: "重建完成 · RTP {rtp}% · {chunks} 个 chunk 重解析",
    rebuildFailed: "重建失败：{error}",
    rebuildNoChunks: "无可用缓存 chunk，需重新采样",
    rebuildIncompatible: "缓存 chunk 与当前 analyzer 不兼容（{reason}），需重新采样",
    chunkCompatible: "{count} chunks ✓",
    chunkIncompatible: "{count} chunks ✗ 失效",
    rebuildBusy: "系统忙，请稍后重试",
    chunkCacheLabel: "{count} chunks",
    chunkCacheNone: "无缓存",
    btnCacheRefresh: "刷新缓存状态",
    btnCacheCleanup: "清理缓存",
    btnLoadRun: "载入",
    btnDeleteRun: "删除",
    btnRebuildRun: "重建",
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
    helpBankMultipliers: "资金倍数梯度：例如 100,200,500，对应不同起始资金强度。",
    helpProvider: "供应商：选择解读调用的模型厂商。",
    helpModel: "模型：选择具体解读模型，必须属于当前供应商。",
    helpApiKey: "API Key：仅用于模型解读调用；留空则回退规则解读。",
    helpIconLabel: "参数说明",
    kpiRtp: "RTP %",
    kpiCi: "CI 半宽",
    kpiSpins: "总 Spins",
    kpiZero: "空转率",
    kpiTail: "尾部依赖度",
    kpiGuide: "规则状态",
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
    panelAssessment: "Guideline Assessment",
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
    bankMultStandard: "Standard (100x / 200x / 500x) — recommended",
    bankMultShort: "Short session (50x / 100x / 200x)",
    bankMultLong: "Long session (200x / 500x / 1000x)",
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
    kpiVolatility: "Volatility",
    kpiArchetype: "Archetype",
    kpiLossStreak: "P95 Loss Streak",
    kpiMaxReturn: "Max Return x",
    kpiBigWin: "10x+ Big Win Rate",
    kpiBankruptX500: "x500 Bankruptcy",
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
    thRate: "Rate",
    symbolsEmpty: "No symbol data yet.",
    symbolColLabel: "Col {idx}",
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
    btnInterpret: "Generate Interpretation",
    btnRebuild: "Rebuild from cache",
    rebuildSuccess: "Rebuilt · RTP {rtp}% · {chunks} chunk(s) reprocessed",
    rebuildFailed: "Rebuild failed: {error}",
    rebuildNoChunks: "No cached chunks; resample required",
    rebuildIncompatible: "Cached chunks incompatible with current analyzer ({reason}); resample required",
    chunkCompatible: "{count} chunks ✓",
    chunkIncompatible: "{count} chunks ✗ stale",
    rebuildBusy: "System busy, try again later",
    chunkCacheLabel: "{count} chunks",
    chunkCacheNone: "no cache",
    btnCacheRefresh: "Refresh Cache",
    btnCacheCleanup: "Cleanup Cache",
    btnLoadRun: "Load",
    btnDeleteRun: "Delete",
    btnRebuildRun: "Rebuild",
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
    helpBankMultipliers: "Bankroll Multipliers: e.g. 100,200,500 for different starting bankroll levels.",
    helpProvider: "Provider: selects the vendor for interpretation calls.",
    helpModel: "Model: concrete interpretation model; must belong to current provider.",
    helpApiKey: "API key: used only for interpretation calls; empty key falls back to rule-based text.",
    helpIconLabel: "Parameter help",
    kpiRtp: "RTP %",
    kpiCi: "CI Half-width",
    kpiSpins: "Total Spins",
    kpiZero: "Zero Win Rate",
    kpiTail: "Tail Dependency",
    kpiGuide: "Guideline Status",
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
  return [
    { value: "100,200,500", label: fmt(lang, "bankMultStandard") },
    { value: "50,100,200", label: fmt(lang, "bankMultShort") },
    { value: "200,500,1000", label: fmt(lang, "bankMultLong") },
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
  const byCol = ((summary || {}).player_impact || {}).symbols_by_column_top10 || {};
  const columnIds = Object.keys(byCol).sort((a, b) => Number(a) - Number(b));
  const rowsByCol = {};
  for (const col of columnIds) {
    const list = Array.isArray(byCol[col]) ? byCol[col] : [];
    rowsByCol[col] = list.map((r) => ({
      symbol: String(r.symbol != null ? r.symbol : "?"),
      count: Number(r.count || 0),
      rate_pct: Number(r.rate || 0) * 100,
    }));
  }
  return { columnIds, rowsByCol };
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
function extractMetricCards(summary) {
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
  const bank = ga.bankruptcy_checks || {};
  const cmp = s.guideline_comparison || {};

  const num = (v, fn) => (v == null ? "N/A" : fn(Number(v)));
  const pct = (v, d = 2) => (v == null ? "N/A" : `${(Number(v) * 100).toFixed(d)}%`);

  // tone helpers
  const toneZeroWin = (v) =>
    v == null ? "neutral" : v > 0.82 ? "bad" : v > 0.75 ? "warn" : "good";
  const toneTailDep = (v) =>
    v == null ? "neutral" : v >= 0.5 ? "bad" : v >= 0.45 ? "warn" : v >= 0.2 ? "neutral" : "good";
  const toneLossStreak = (v) =>
    v == null ? "neutral" : v >= 18 ? "bad" : v >= 15 ? "warn" : "good";
  const toneBankruptX500 = (v) =>
    v == null ? "neutral" : v >= 0.05 ? "bad" : v >= 0.01 ? "warn" : "good";
  const toneGuideline = (status) => {
    const u = String(status || "").toUpperCase();
    return u === "PASS" ? "good" : u === "FAIL" ? "bad" : "warn";
  };

  return {
    rtp: { value: num(rtp.point_pct, (x) => `${x.toFixed(2)}%`), tone: "neutral" },
    ci: { value: num(sampling.achieved_halfwidth_pp, (x) => x.toFixed(3)), tone: "neutral" },
    spins: {
      value:
        sampling.total_spins == null
          ? "N/A"
          : new Intl.NumberFormat("en-US").format(Number(sampling.total_spins)),
      tone: "neutral",
    },
    zeroWin: { value: pct(hit.zero_win_rate), tone: toneZeroWin(hit.zero_win_rate) },
    tailDep: (() => {
      // Primary value shows ge10x (the canonical dependency that
      // classify_volatility / classify_experience_archetype read).
      // sub carries the compact ge20x / ge50x / ge100x breakdown so
      // the operator sees how fast the tail decays.
      const d10 = derived.tail_dependency_ge10x ?? derived.tail_dependency;
      const d20 = derived.tail_dependency_ge20x;
      const d50 = derived.tail_dependency_ge50x;
      const d100 = derived.tail_dependency_ge100x;
      const fmt1 = (v) => (v == null ? "\u2014" : (Number(v) * 100).toFixed(1) + "%");
      // Compact bar-like format: ≥10 68.6 → ≥20 48.2 → ≥50 21.6 → ≥100 5.0
      // Uses → arrows to show the decay direction.
      const parts = [];
      if (d10 != null) parts.push(`\u226510x ${fmt1(d10)}`);
      if (d20 != null) parts.push(`\u226520x ${fmt1(d20)}`);
      if (d50 != null) parts.push(`\u226550x ${fmt1(d50)}`);
      if (d100 != null) parts.push(`\u2265100x ${fmt1(d100)}`);
      return {
        value: parts.length ? parts[0] : num(d10, (x) => x.toFixed(3)),
        tone: toneTailDep(d10),
        sub: parts.slice(1).join(" \u2192 "),
      };
    })(),
    guideline: { value: cmp.overall_status || "N/A", tone: toneGuideline(cmp.overall_status) },
    volatility: { value: cls.volatility_class || "N/A", tone: "neutral" },
    archetype: { value: cls.experience_archetype || "N/A", tone: "neutral" },
    lossStreak: {
      value: streaks.loss_streak_p95 == null ? "N/A" : String(streaks.loss_streak_p95),
      tone: toneLossStreak(streaks.loss_streak_p95),
    },
    maxReturn: {
      value: num(vol.max_observed_return_x, (x) => `${x.toFixed(1)}x`),
      tone: "neutral",
    },
    bigWin: { value: pct(hit.big_win_x10_rate, 3), tone: "neutral" },
    bankruptX500: {
      value: pct(bank.x500_bankruptcy_rate, 3),
      tone: toneBankruptX500(bank.x500_bankruptcy_rate),
    },
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
    const criticals = chunkEvents.filter((e) => CRITICAL.has(e.event));
    const progresses = chunkEvents
      .filter((e) => e.event === "chunk_progress")
      .slice(-cap);
    for (const ev of [...criticals, ...progresses]) {
      let level = "info";
      if (ev.event === "chunk_failed") level = "warn";
      else if (ev.event === "disk_guard_stop" || ev.event === "failed") level = "danger";
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
  mergeTimeline,
};

if (typeof window !== "undefined") window.PURE = PURE;
if (typeof module !== "undefined") module.exports = PURE;

})();
