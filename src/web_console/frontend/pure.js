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
    tabManage: "全面管理",
    panelRunConfig: "运行参数",
    panelModelConfig: "模型配置",
    panelRunControl: "运行控制",
    panelProgress: "当前运行进度",
    panelKpi: "关键指标",
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
    validateAutotuneFirst: "请先点「一键压测并调参」获得并发推荐值。",
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
    thWinShare: "Win 占比",
    paylineEmpty: "暂无支付线数据。",
    panelSymbols: "符号深度（整体 + 按列）",
    symbolsOverallHeader: "整体 Top 20",
    symbolsByColHeader: "按列分布 Top 10（每列）",
    thSymbol: "符号",
    thCount: "次数",
    thRate: "占比",
    symbolsEmpty: "暂无符号数据。",
    symbolColLabel: "列 {idx}",
    panelPayoutGroups: "Pay ID 深度（PayoutGroupId Top 20）",
    thGroupId: "Group ID",
    thAvgWinX: "命中均赢(x)",
    payoutGroupEmpty: "暂无 PayoutGroupId 数据。",
    payoutGroupZeroHint: "Group 0 = 未中奖，仅展示作对照。",
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
    btnCacheRefresh: "刷新缓存状态",
    btnCacheCleanup: "清理缓存",
    btnLoadRun: "载入",
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
    noRun: "未选择运行。",
    noReport: "暂无报告。",
    noInterpret: "暂无解读。",
    noEvents: "暂无事件。",
    noAutoTune: "尚未执行自动调优。",
    noMachines: "暂无机台配置。",
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
    tabManage: "Fleet Management",
    panelRunConfig: "Run Parameters",
    panelModelConfig: "Model Config",
    panelRunControl: "Run Control",
    panelProgress: "Current Run Progress",
    panelKpi: "Key Indicators",
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
    validateAutotuneFirst: "Click 'Auto Tune Parallelism' first to get recommended concurrency values.",
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
    thWinShare: "Win Share",
    paylineEmpty: "No payline data yet.",
    panelSymbols: "Symbol Drilldown (Overall + by Column)",
    symbolsOverallHeader: "Overall Top 20",
    symbolsByColHeader: "By Column Top 10 (each column)",
    thSymbol: "Symbol",
    thCount: "Count",
    thRate: "Rate",
    symbolsEmpty: "No symbol data yet.",
    symbolColLabel: "Col {idx}",
    panelPayoutGroups: "Pay ID Drilldown (PayoutGroupId Top 20)",
    thGroupId: "Group ID",
    thAvgWinX: "Avg Win when Hit (x)",
    payoutGroupEmpty: "No PayoutGroupId data yet.",
    payoutGroupZeroHint: "Group 0 = no payout; shown for reference only.",
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
    btnCacheRefresh: "Refresh Cache",
    btnCacheCleanup: "Cleanup Cache",
    btnLoadRun: "Load",
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
    thRun: "Run",
    thRtp: "RTP",
    thQuality: "Quality",
    noRun: "No run selected.",
    noReport: "No report yet.",
    noInterpret: "No interpretation yet.",
    noEvents: "No events yet.",
    noAutoTune: "No auto tune run yet.",
    noMachines: "No machine config found.",
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
    return {
      payline_id: String(r.payline_id != null ? r.payline_id : "?"),
      hit_count: Number(r.hit_count || 0),
      hit_rate_pct: Number(r.hit_rate || 0) * 100,
      rtp_contribution_pp: rtp,
      win_share_pct: Number(r.approx_rtp_contribution_pp != null && totalRtp > 0
        ? rtp / totalRtp
        : 0) * 100,
    };
  });
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
    tailDep: {
      value: num(derived.tail_dependency, (x) => x.toFixed(3)),
      tone: toneTailDep(derived.tail_dependency),
    },
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
    blocking.push(fmt(lang, "validateAutotuneFirst"));
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
  formatSymbolRows,
  symbolByColMatrix,
  formatPayoutGroupRows,
  prettyBucketLabel,
};

if (typeof window !== "undefined") window.PURE = PURE;
if (typeof module !== "undefined") module.exports = PURE;

})();
