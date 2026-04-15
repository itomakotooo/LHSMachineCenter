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
    labelCiTarget: "目标 CI 半宽 (pp)",
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
    btnStart: "开始运行",
    btnStop: "停止运行",
    btnRefresh: "刷新状态",
    btnAutoTune: "一键压测并调参",
    btnAutoTuneBusy: "压测中...",
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
    chartCiTitle: "CI 半宽趋势",
    chartRtpTitle: "RTP 趋势",
    chartBucketTitle: "倍率分桶占比",
    chartBankTitle: "破产曲线",
    chartCiLabel: "CI 半宽",
    chartRtpLabel: "RTP %",
    chartBucketLabel: "Spin 占比 %",
    chartBankLabel: "破产率 %",
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
    labelCiTarget: "Target CI Half-width (pp)",
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
    btnStart: "Start Run",
    btnStop: "Stop Run",
    btnRefresh: "Refresh",
    btnAutoTune: "Auto Tune Parallelism",
    btnAutoTuneBusy: "Auto Tuning...",
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
    chartCiTitle: "CI Half-width Trend",
    chartRtpTitle: "RTP Trend",
    chartBucketTitle: "Multiplier Bucket Rate",
    chartBankTitle: "Bankruptcy Curve",
    chartCiLabel: "CI Half-width",
    chartRtpLabel: "RTP %",
    chartBucketLabel: "Spin Rate %",
    chartBankLabel: "Bankruptcy Rate %",
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
};

if (typeof window !== "undefined") window.PURE = PURE;
if (typeof module !== "undefined") module.exports = PURE;

})();
