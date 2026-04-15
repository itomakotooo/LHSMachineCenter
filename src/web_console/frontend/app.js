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

const state = {
  lang: localStorage.getItem("slot_console_lang") || "zh",
  currentRunId: "",
  currentRunStatus: "",
  machines: [],
  runs: [],
  modelMeta: {},
  latestSummary: null,
  cacheStatus: null,
  systemState: null,
  timer: null,
  autoTuneRunning: false,
  busyActions: new Set(),
  ciChart: null,
  rtpChart: null,
  bucketChart: null,
  bankChart: null,
};

const byId = (id) => document.getElementById(id);
const fmt = (k, vars = {}) =>
  Object.keys(vars).reduce((s, n) => s.replaceAll(`{${n}}`, String(vars[n])), (I18N[state.lang] || I18N.en)[k] || k);

function applyI18n() {
  if (!I18N[state.lang]) state.lang = "zh";
  localStorage.setItem("slot_console_lang", state.lang);
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  document.title = fmt("appTitle");
  byId("langSelect").value = state.lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = fmt(el.dataset.i18n)));
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => (el.placeholder = fmt(el.dataset.i18nPlaceholder)));
  applyFieldHelpHints();
  byId("autotuneBtn").textContent = state.autoTuneRunning ? fmt("btnAutoTuneBusy") : fmt("btnAutoTune");
  setSystemStatePanel();
  renderCacheRiskMeta();
  updateChartLabels();
  if (byId("startBtn")) updateActionStates();
}

function applyFieldHelpHints() {
  document.querySelectorAll("[data-help-key]").forEach((el) => {
    const key = el.dataset.helpKey || "";
    const txt = fmt(key);
    el.title = txt;
    el.setAttribute("aria-label", `${fmt("helpIconLabel")}: ${txt}`);
  });
}

function switchTab(tab) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab-page").forEach((p) => p.classList.toggle("active", p.id === `tab-${tab}`));
}

function setHealth(ok, suffix = "") {
  const el = byId("health");
  el.textContent = `${ok ? fmt("healthOk") : fmt("healthFail")} ${suffix}`.trim();
  el.style.color = ok ? "#0f766e" : "#b91c1c";
}

async function apiGet(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

async function apiPost(url, payload) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}) });
  if (!res.ok) throw new Error(`${url}: ${res.status} ${await res.text()}`);
  return res.json();
}

const fNum = (v, d = 3) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "N/A" : Number(v).toFixed(d));
const fInt = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "N/A" : new Intl.NumberFormat("en-US").format(Number(v)));
const fRate = (v, d = 2) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "N/A" : `${(Number(v) * 100).toFixed(d)}%`);

function statusText(s) {
  const k = `status${String(s || "unknown").charAt(0).toUpperCase()}${String(s || "unknown").slice(1)}`;
  return fmt(k in I18N[state.lang] ? k : "statusUnknown");
}

function setSystemStatePanel() {
  const elMeta = byId("systemStateMeta");
  const elTips = byId("safetyTips");
  if (!elMeta || !elTips) return;
  const s = state.systemState || {};
  const startup = s.startup_recovery || {};
  const opName = s.operation_busy ? s.operation_name || "unknown" : "idle";
  const opSince = s.operation_busy ? s.operation_since || "-" : "-";
  const terminatedPids = Number(Array.isArray(startup.terminated_pids) ? startup.terminated_pids.length : 0);
  const failedPids = Number(Array.isArray(startup.failed_to_terminate_pids) ? startup.failed_to_terminate_pids.length : 0);
  elMeta.textContent = fmt("systemMeta", {
    startedAt: s.app_started_at || "-",
    operation: opName,
    opSince,
    runningCount: s.running_runs_count ?? 0,
    recovered: startup.recovered_count ?? 0,
    terminatedPids,
    failedPids,
  });
  const tips = [fmt("safetyTipBase")];
  if (s.operation_busy) tips.push(fmt("safetyTipBusy", { op: opName }));
  if (failedPids > 0) tips.push(fmt("warnRecoveredPidRisk", { count: failedPids }));
  elTips.textContent = tips.join("\n");
}

function collectSystemWarnings() {
  const out = [];
  const startup = state.systemState?.startup_recovery || {};
  const recovered = Number(startup.recovered_count || 0);
  const failedPids = Number(Array.isArray(startup.failed_to_terminate_pids) ? startup.failed_to_terminate_pids.length : 0);
  if (recovered > 0) out.push(fmt("warnRecovered", { count: recovered }));
  if (failedPids > 0) out.push(fmt("warnRecoveredPidRisk", { count: failedPids }));
  if (state.systemState?.operation_busy) out.push(fmt("warnSystemBusy", { op: state.systemState.operation_name || "unknown" }));
  return out;
}

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

function cacheRiskTier(reclaimableBytes) {
  const b = Number(reclaimableBytes || 0);
  if (b <= 0) return "none";
  if (b >= 2 * 1024 * 1024 * 1024) return "high";
  if (b >= 512 * 1024 * 1024) return "medium";
  return "low";
}

function cacheRiskView(cachedStatus) {
  const c = cachedStatus || {};
  const bytes = Number(c.reclaimable_bytes_estimate || 0);
  const tier = cacheRiskTier(bytes);
  const tierKey = tier === "high" ? "riskHigh" : tier === "medium" ? "riskMedium" : tier === "low" ? "riskLow" : "riskNone";
  const tierLabel = fmt(tierKey);
  const hintKey = tier === "high" ? "cacheRiskHighHint" : tier === "medium" ? "cacheRiskMediumHint" : tier === "low" ? "cacheRiskLowHint" : "cacheRiskNoneHint";
  return {
    bytes,
    tier,
    tierLabel,
    hint: fmt(hintKey),
  };
}

function renderCacheRiskMeta() {
  const el = byId("cacheRiskMeta");
  if (!el) return;
  const runningCount = Number(state.cacheStatus?.running_runs || 0);
  const risk = cacheRiskView(state.cacheStatus);
  const lines = [fmt("cacheRiskLine", { tier: risk.tierLabel, reclaimable: fBytes(risk.bytes) }), risk.hint];
  if (runningCount > 0) lines.push(fmt("cacheWarnRunning"));
  el.textContent = lines.join("\n");
}

async function confirmCacheCleanup() {
  if (!state.cacheStatus) await refreshCache();
  const runningCount = Number(state.cacheStatus?.running_runs || 0);
  if (runningCount > 0) {
    alert(fmt("cacheWarnRunning"));
    return false;
  }
  const risk = cacheRiskView(state.cacheStatus);
  if (risk.tier === "none") {
    alert(fmt("cacheNoReclaim"));
    return false;
  }
  const confirmKey = risk.tier === "high" ? "confirmCleanupHigh" : risk.tier === "medium" ? "confirmCleanupMedium" : "confirmCleanupLow";
  if (!window.confirm(fmt(confirmKey, { reclaimable: fBytes(risk.bytes) }))) return false;
  if (risk.tier === "medium" || risk.tier === "high") {
    const token = fmt("confirmCleanupToken");
    const typed = window.prompt(fmt("confirmCleanupTokenPrompt", { token, tier: risk.tierLabel }), "");
    if ((typed || "").trim() !== token) {
      alert(fmt("confirmCleanupTokenMismatch"));
      return false;
    }
  }
  return true;
}

async function refreshSystemState() {
  state.systemState = await apiGet("/api/system-state");
  setSystemStatePanel();
  if (!state.currentRunId) {
    const warnings = [...modelWarnings(), ...collectSystemWarnings()];
    setGlobalWarning(warnings);
  }
}

function updateActionStates() {
  const localBusy = state.busyActions.size > 0 || state.autoTuneRunning;
  const serverBusy = Boolean(state.systemState?.operation_busy);
  const anyRunRunning = state.runs.some((r) => String(r.status).toLowerCase() === "running");
  const hasCurrent = Boolean(state.currentRunId);
  const currentStatus = String(state.currentRunStatus || "").toLowerCase();
  const reclaimable = Number(state.cacheStatus?.reclaimable_bytes_estimate ?? 0);
  const tier = cacheRiskTier(reclaimable);

  byId("saveModelCfgBtn").disabled = localBusy || serverBusy;
  byId("startBtn").disabled = localBusy || serverBusy || anyRunRunning;
  byId("autotuneBtn").disabled = localBusy || serverBusy || anyRunRunning;
  byId("stopBtn").disabled = localBusy || serverBusy || !hasCurrent || currentStatus !== "running";
  byId("refreshBtn").disabled = localBusy || !hasCurrent;
  byId("interpretBtn").disabled = localBusy || serverBusy || !hasCurrent || currentStatus !== "completed";
  byId("cacheRefreshBtn").disabled = localBusy;
  const runningCount = Number(state.cacheStatus?.running_runs ?? state.systemState?.running_runs_count ?? 0);
  byId("cacheCleanupBtn").disabled = localBusy || serverBusy || runningCount > 0 || reclaimable <= 0;
  byId("cacheCleanupBtn").classList.toggle("danger-high", tier === "high");
  byId("autotuneBtn").textContent = state.autoTuneRunning ? fmt("btnAutoTuneBusy") : fmt("btnAutoTune");
}

async function withAction(name, fn) {
  if (state.busyActions.size > 0) return;
  state.busyActions.add(name);
  updateActionStates();
  try {
    return await fn();
  } finally {
    state.busyActions.delete(name);
    updateActionStates();
  }
}

function setGlobalWarning(lines) {
  const el = byId("globalWarning");
  const arr = (lines || []).filter(Boolean);
  if (!arr.length) return el.classList.add("hidden"), (el.textContent = "");
  el.textContent = arr.join(" | ");
  el.classList.remove("hidden");
}

function setKpi(id, text, tone = "neutral") {
  const el = byId(id);
  el.textContent = text;
  el.dataset.tone = tone;
}

function clearSummaryPanels() {
  byId("assessment").textContent = fmt("noReport");
  byId("interpretationText").textContent = fmt("noInterpret");
  byId("eventsText").textContent = fmt("noEvents");
  if (!state.autoTuneRunning) byId("autotuneMeta").textContent = fmt("noAutoTune");
  setKpi("kpiRtp", "N/A");
  setKpi("kpiCi", "N/A");
  setKpi("kpiSpins", "N/A");
  setKpi("kpiZero", "N/A");
  setKpi("kpiTail", "N/A");
  setKpi("kpiGuide", "N/A");
  if (state.bucketChart) {
    state.bucketChart.data.labels = [];
    state.bucketChart.data.datasets[0].data = [];
    state.bucketChart.update();
  }
  if (state.bankChart) {
    state.bankChart.data.labels = [];
    state.bankChart.data.datasets[0].data = [];
    state.bankChart.update();
  }
}

function buildCharts() {
  const mk = (ctx, type, label, color, bg) =>
    new Chart(ctx, {
      type,
      data: { labels: [], datasets: [{ label, data: [], borderColor: color, backgroundColor: bg, tension: 0.2, pointRadius: 2, borderWidth: 1 }] },
      options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: type !== "bar" } }, scales: { y: { beginAtZero: type !== "line" } } },
    });
  state.ciChart = mk(byId("ciChart").getContext("2d"), "line", fmt("chartCiLabel"), "#0f766e", "rgba(13,148,136,0.15)");
  state.rtpChart = mk(byId("rtpChart").getContext("2d"), "line", fmt("chartRtpLabel"), "#2563eb", "rgba(37,99,235,0.15)");
  state.bucketChart = mk(byId("bucketChart").getContext("2d"), "bar", fmt("chartBucketLabel"), "#0f766e", "rgba(13,148,136,0.35)");
  state.bankChart = mk(byId("bankChart").getContext("2d"), "line", fmt("chartBankLabel"), "#f97316", "rgba(249,115,22,0.2)");
}

function updateChartLabels() {
  if (state.ciChart) state.ciChart.data.datasets[0].label = fmt("chartCiLabel");
  if (state.rtpChart) state.rtpChart.data.datasets[0].label = fmt("chartRtpLabel");
  if (state.bucketChart) state.bucketChart.data.datasets[0].label = fmt("chartBucketLabel");
  if (state.bankChart) state.bankChart.data.datasets[0].label = fmt("chartBankLabel");
  state.ciChart?.update();
  state.rtpChart?.update();
  state.bucketChart?.update();
  state.bankChart?.update();
}

function renderMachineCatalog() {
  const wrap = byId("machineCatalog");
  wrap.innerHTML = "";
  if (!state.machines.length) return (wrap.textContent = fmt("noMachines"));
  state.machines.forEach((m) => {
    const d = document.createElement("div");
    d.className = "catalog-item";
    d.innerHTML = `<div class="catalog-title">${m.machine}</div><div class="catalog-modes">modes: ${(m.modes || []).join(", ")}</div>`;
    wrap.appendChild(d);
  });
}

function renderRunHistory() {
  const body = byId("runListTable").querySelector("tbody");
  body.innerHTML = "";
  if (!state.runs.length) return (body.innerHTML = `<tr><td colspan="6">${fmt("noRuns")}</td></tr>`);
  state.runs.forEach((r) => {
    const tr = document.createElement("tr");
    if (r.run_id === state.currentRunId) tr.classList.add("active-row");
    tr.innerHTML = `<td>${r.run_id}</td><td>${statusText(r.status)}</td><td>${r.machine}</td><td>${r.mode}</td><td>${r.created_at || ""}</td><td><button class="load-run-btn" data-id="${r.run_id}">${fmt("btnLoadRun")}</button></td>`;
    body.appendChild(tr);
  });
  body.querySelectorAll(".load-run-btn").forEach((b) =>
    b.addEventListener("click", async () => {
      if (state.busyActions.size > 0) return;
      state.currentRunId = b.dataset.id;
      renderRunHistory();
      switchTab("debug");
      await refreshCurrentRun();
    })
  );
  body.querySelectorAll(".load-run-btn").forEach((b) => {
    b.disabled = state.busyActions.size > 0;
  });
}

function renderAssessment(summary) {
  if (!summary || !summary.guideline_assessment) {
    byId("assessment").textContent = fmt("noReport");
    return;
  }
  const ga = summary.guideline_assessment || {};
  const gc = summary.guideline_comparison || {};
  const d = ga.derived_metrics || {};
  const lines = [];
  lines.push(`${fmt("assessmentQuality")}: ${ga.data_quality?.quality_label || "N/A"}`);
  lines.push(`${fmt("assessmentVolatility")}: ${ga.classification?.volatility_class || "N/A"}`);
  lines.push(`${fmt("assessmentArchetype")}: ${ga.classification?.experience_archetype || "N/A"}`);
  lines.push(`${fmt("assessmentRecoveryGap")}: ${fNum(d.recovery_gap)}`);
  lines.push(`${fmt("assessmentTail")}: ${fNum(d.tail_dependency)}`);
  lines.push(
    `${fmt("assessmentRule")}: ${gc.overall_status || "N/A"} (pass=${gc.pass_count ?? 0}, fail=${gc.fail_count ?? 0}, missing=${gc.missing_count ?? 0})`
  );
  const alerts = Array.isArray(ga.alerts) ? ga.alerts : [];
  if (alerts.length) {
    lines.push(`${fmt("assessmentAlerts")}:`);
    alerts.slice(0, 6).forEach((a) => lines.push(`- [${a.severity}] ${a.code}: ${a.message}`));
  }
  const actions = Array.isArray(ga.action_recommendations) ? ga.action_recommendations : [];
  if (actions.length) {
    lines.push(`${fmt("assessmentActions")}:`);
    actions.slice(0, 6).forEach((a, i) => lines.push(`${i + 1}. ${a}`));
  }
  byId("assessment").textContent = lines.join("\n");
}

function fillMachineModeSelectors() {
  const mSel = byId("machineSelect");
  mSel.innerHTML = "";
  state.machines.forEach((m) => mSel.appendChild(new Option(m.machine, m.machine)));
  refreshModes();
}

function refreshModes() {
  const machine = state.machines.find((m) => m.machine === byId("machineSelect").value) || state.machines[0] || { modes: [1] };
  const modeSel = byId("modeSelect");
  modeSel.innerHTML = "";
  (machine.modes || [1]).forEach((m) => modeSel.appendChild(new Option(String(m), String(m))));
}

function fillProviders() {
  const sel = byId("providerSelect");
  sel.innerHTML = "";
  (state.modelMeta.provider_options || ["gemini", "gpt", "claude"]).forEach((p) => sel.appendChild(new Option(p, p)));
  sel.value = state.modelMeta.active_provider || "gemini";
}

function fillModelsForProvider(provider, preferred = "") {
  const sel = byId("modelSelect");
  sel.innerHTML = "";
  const models = (state.modelMeta.provider_catalog || {})[provider] || [];
  models.forEach((m) => sel.appendChild(new Option(m, m)));
  if (preferred && models.includes(preferred)) sel.value = preferred;
}

function modelWarnings() {
  const provider = byId("providerSelect").value || state.modelMeta.active_provider || "gemini";
  const selected = byId("modelSelect").value || "";
  const models = ((state.modelMeta.provider_catalog || {})[provider] || []).map(String);
  const out = [];
  if (selected && models.length && !models.includes(selected)) out.push(fmt("warnModelMismatch"));
  if (!state.modelMeta.has_api_key) out.push(fmt("warnApiKeyEmpty", { provider: provider.toUpperCase() }));
  return out;
}

function readRunPayload() {
  return {
    machine: byId("machineSelect").value,
    mode: Number(byId("modeSelect").value),
    target_halfwidth_pp: Number(byId("ciInput").value),
    chunk_spin_times: Number(byId("spinInput").value),
    chunk_robot_count: Number(byId("robotInput").value),
    batch_concurrency: Number(byId("concInput").value),
    max_chunks: Number(byId("maxChunksInput").value),
    timeout: Number(byId("timeoutInput").value),
    bankruptcy_session_spins: Number(byId("bankSessionInput").value),
    bankruptcy_bankroll_multipliers: byId("bankMultInput").value,
    model_id: byId("modelSelect").value,
  };
}

async function refreshRunList(autoSelect = true) {
  const data = await apiGet("/api/runs");
  state.runs = data.runs || [];
  if (autoSelect && !state.currentRunId && state.runs.length) state.currentRunId = state.runs[0].run_id;
  if (state.currentRunId) {
    const cur = state.runs.find((r) => r.run_id === state.currentRunId);
    if (cur) state.currentRunStatus = cur.status || "";
  }
  renderRunHistory();
  updateActionStates();
}

async function refreshCurrentRun() {
  if (!state.currentRunId) {
    byId("runMeta").textContent = fmt("noRun");
    updateActionStates();
    return;
  }
  let run;
  try {
    run = await apiGet(`/api/runs/${state.currentRunId}`);
  } catch (err) {
    if (String(err?.message || "").includes("404")) {
      state.currentRunId = "";
      state.currentRunStatus = "";
      byId("runMeta").textContent = fmt("noRun");
      updateActionStates();
      return;
    }
    throw err;
  }
  state.currentRunStatus = run.status || "";
  const p = run.progress || {};
  const latest = p.latest_event || {};
  const hw = latest.current_halfwidth_pp;
  const target = run.target_halfwidth_pp;
  const pct = hw == null || !target ? 0 : hw <= target ? 100 : Math.min(100, (target / hw) * 100);
  byId("progressBar").style.width = `${pct}%`;
  byId("runMeta").textContent = `run=${run.run_id} status=${statusText(run.status)} machine=${run.machine} mode=${run.mode} spins=${latest.total_spins || 0} chunks=${p.chunk_count || 0} ci=${fNum(hw)} target=${target}`;
  setKpi("kpiRtp", latest.current_rtp_pct != null ? `${fNum(latest.current_rtp_pct)}%` : "N/A");
  setKpi("kpiCi", hw != null ? fNum(hw) : "N/A");
  setKpi("kpiSpins", latest.total_spins != null ? fInt(latest.total_spins) : "N/A");

  const events = (await apiGet(`/api/runs/${state.currentRunId}/progress`)).events || [];
  byId("eventsText").textContent = events.length ? events.slice(-80).map((e) => JSON.stringify(e)).join("\n") : fmt("noEvents");
  const chunks = events.filter((e) => e.event === "chunk_progress");
  state.ciChart.data.labels = chunks.map((e) => String(e.chunk_index));
  state.ciChart.data.datasets[0].data = chunks.map((e) => e.current_halfwidth_pp ?? null);
  state.rtpChart.data.labels = chunks.map((e) => String(e.chunk_index));
  state.rtpChart.data.datasets[0].data = chunks.map((e) => e.current_rtp_pct ?? null);
  state.ciChart.update();
  state.rtpChart.update();

  const warnings = modelWarnings();
  if (run.status === "failed") warnings.push(fmt("warnRunFailed", { msg: run.error_message || "unknown error" }));
  if (run.status === "cancelled") warnings.push(fmt("warnRunCancelled"));

  if (run.status === "completed") {
    const report = await apiGet(`/api/runs/${state.currentRunId}/report`);
    const s = report.summary || {};
    state.latestSummary = s;
    renderAssessment(s);
    setKpi("kpiRtp", s.rtp?.point_pct != null ? `${fNum(s.rtp.point_pct)}%` : "N/A");
    setKpi("kpiCi", s.sampling?.achieved_halfwidth_pp != null ? fNum(s.sampling.achieved_halfwidth_pp) : "N/A");
    setKpi("kpiSpins", s.sampling?.total_spins != null ? fInt(s.sampling.total_spins) : "N/A");
    setKpi("kpiZero", fRate(s.player_impact?.hit_and_payout?.zero_win_rate));
    setKpi("kpiTail", fNum(s.guideline_assessment?.derived_metrics?.tail_dependency));
    const gs = s.guideline_comparison?.overall_status || "UNKNOWN";
    setKpi("kpiGuide", gs, gs === "PASS" ? "good" : gs === "FAIL" ? "bad" : "warn");
    const buckets = s.player_impact?.multiplier_profile?.buckets || [];
    state.bucketChart.data.labels = buckets.map((b) => b.bucket);
    state.bucketChart.data.datasets[0].data = buckets.map((b) => (Number(b.spin_rate) <= 1 ? Number(b.spin_rate) * 100 : Number(b.spin_rate)));
    state.bucketChart.update();
    const bank = s.player_impact?.bankruptcy_probe || [];
    state.bankChart.data.labels = bank.map((b) => `x${b.bankroll_multiplier}`);
    state.bankChart.data.datasets[0].data = bank.map((b) => (Number(b.bankruptcy_rate) <= 1 ? Number(b.bankruptcy_rate) * 100 : Number(b.bankruptcy_rate)));
    state.bankChart.update();
    await refreshVersions();
    await refreshInterpretation();
  }
  warnings.push(...collectSystemWarnings());
  setGlobalWarning([...new Set(warnings)]);
  updateActionStates();
}

async function refreshVersions() {
  const d = await apiGet(`/api/reports/${byId("machineSelect").value || "M14"}/${Number(byId("modeSelect").value || 1)}`);
  const body = byId("versionsTable").querySelector("tbody");
  body.innerHTML = "";
  const arr = (d.versions || []).slice().reverse();
  if (!arr.length) return (body.innerHTML = `<tr><td colspan="5">${fmt("noVersions")}</td></tr>`);
  arr.forEach((v) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${v.report_version || ""}</td><td>${v.run_id || ""}</td><td>${v.created_at || ""}</td><td>${v.rtp_point_pct ?? ""}</td><td>${v.quality_label || ""}</td>`;
    body.appendChild(tr);
  });
}

async function refreshCache() {
  state.cacheStatus = await apiGet("/api/cache/status");
  const c = state.cacheStatus;
  byId("cacheMeta").textContent = `root=${c.cache_root}\nfiles=${c.file_count}\ntotal_bytes=${fBytes(c.total_bytes)} (${c.total_bytes})\nrunning_runs=${c.running_runs}\nreclaimable_est=${fBytes(c.reclaimable_bytes_estimate)} (${c.reclaimable_bytes_estimate})`;
  byId("cacheWarning").textContent = Number(c.running_runs || 0) > 0 ? fmt("cacheWarnRunning") : Number(c.reclaimable_bytes_estimate || 0) > 0 ? fmt("cacheWarnIdle") : fmt("cacheNoReclaim");
  renderCacheRiskMeta();
  updateActionStates();
}

async function runAutoTune() {
  if (state.autoTuneRunning) return;
  state.autoTuneRunning = true;
  updateActionStates();
  const rc = Number(byId("robotInput").value || 20);
  const cc = Number(byId("concInput").value || 2);
  const payload = {
    machine: byId("machineSelect").value || "M14",
    mode: Number(byId("modeSelect").value || 1),
    spin_times: Math.max(60, Math.min(240, Number(byId("spinInput").value || 120))),
    robot_candidates: [...new Set([rc - 8, rc - 4, rc, rc + 4, rc + 8].map((x) => Math.max(4, x)).filter((x) => x <= 200))],
    concurrency_candidates: [...new Set([1, cc - 1, cc, cc + 1, cc + 2].map((x) => Math.max(1, x)).filter((x) => x <= 16))],
    rounds: 2,
    timeout: 45,
    bet: 1000,
  };
  byId("autotuneMeta").textContent = `machine=${payload.machine} mode=${payload.mode}\nrobots=[${payload.robot_candidates.join(",")}]\nconc=[${payload.concurrency_candidates.join(",")}]`;
  try {
    const r = await apiPost("/api/autotune", payload);
    if (r.recommendation?.chunk_robot_count != null) byId("robotInput").value = r.recommendation.chunk_robot_count;
    if (r.recommendation?.batch_concurrency != null) byId("concInput").value = r.recommendation.batch_concurrency;
    const rows = (r.results || []).slice(0, 8).map((x, i) => `${i + 1}. robot=${x.robot_count} conc=${x.batch_concurrency} success=${fRate(x.success_rate, 1)} throughput=${fNum(x.throughput_spins_per_sec, 2)} p95=${fNum(x.p95_latency_s, 3)}s`);
    byId("autotuneMeta").textContent = `tested=${r.tested}\nrecommend robot=${r.recommendation?.chunk_robot_count} conc=${r.recommendation?.batch_concurrency}\n${rows.join("\n")}`;
    if (Number(r.best?.success_rate || 0) < 0.95) {
      setGlobalWarning([...modelWarnings(), fmt("warnAutoTuneLowSuccess", { rate: fRate(r.best?.success_rate, 1) })]);
    }
  } finally {
    state.autoTuneRunning = false;
    updateActionStates();
  }
}

async function generateInterpretation() {
  if (!state.currentRunId) return;
  const r = await apiPost("/api/interpretations", { run_id: state.currentRunId, model_id: byId("modelSelect").value });
  byId("interpretationText").textContent = r.content || fmt("noInterpret");
}

async function refreshInterpretation() {
  if (!state.currentRunId) return;
  const r = await apiGet(`/api/interpretations/${state.currentRunId}`);
  byId("interpretationText").textContent = r.content || fmt("noInterpret");
}

async function loadBootstrap() {
  const [h, m, models] = await Promise.all([apiGet("/api/health"), apiGet("/api/machines"), apiGet("/api/models")]);
  setHealth(Boolean(h.ok), h.ts || "");
  state.machines = m.machines || [];
  state.modelMeta = models || {};
  fillMachineModeSelectors();
  fillProviders();
  fillModelsForProvider(byId("providerSelect").value, state.modelMeta.default_model || "");
  renderMachineCatalog();
  byId("runMeta").textContent = fmt("noRun");
  byId("assessment").textContent = fmt("noReport");
  byId("interpretationText").textContent = fmt("noInterpret");
  byId("eventsText").textContent = fmt("noEvents");
  byId("autotuneMeta").textContent = fmt("noAutoTune");
  await refreshSystemState();
  await refreshCache();
  await refreshVersions();
  await refreshRunList(true);
  if (state.currentRunId) await refreshCurrentRun();
  setSystemStatePanel();
  updateActionStates();
  const warnings = [...modelWarnings(), ...collectSystemWarnings()];
  setGlobalWarning(warnings);
}

function bindEvents() {
  byId("langSelect").addEventListener("change", async (e) => {
    state.lang = e.target.value;
    applyI18n();
    renderMachineCatalog();
    renderRunHistory();
    setSystemStatePanel();
    await refreshVersions().catch(() => {});
    await refreshCache().catch(() => {});
    await refreshSystemState().catch(() => {});
    if (state.currentRunId) {
      await refreshCurrentRun().catch(() => {});
    } else {
      byId("runMeta").textContent = fmt("noRun");
      byId("assessment").textContent = fmt("noReport");
      byId("interpretationText").textContent = fmt("noInterpret");
      byId("eventsText").textContent = fmt("noEvents");
      byId("autotuneMeta").textContent = fmt("noAutoTune");
    }
    updateActionStates();
  });
  byId("tabBtnDebug").addEventListener("click", () => switchTab("debug"));
  byId("tabBtnManage").addEventListener("click", () => switchTab("manage"));
  byId("machineSelect").addEventListener("change", async () => {
    refreshModes();
    clearSummaryPanels();
    await refreshVersions();
  });
  byId("modeSelect").addEventListener("change", async () => {
    clearSummaryPanels();
    await refreshVersions();
  });
  byId("providerSelect").addEventListener("change", () => (fillModelsForProvider(byId("providerSelect").value), setGlobalWarning(modelWarnings())));
  byId("modelSelect").addEventListener("change", () => setGlobalWarning(modelWarnings()));
  byId("saveModelCfgBtn").addEventListener("click", () =>
    withAction("save_model", async () => {
      state.modelMeta = await apiPost("/api/model-config", { provider: byId("providerSelect").value, api_key: byId("apiKeyInput").value || "" });
      byId("apiKeyInput").value = "";
      fillProviders();
      fillModelsForProvider(byId("providerSelect").value, state.modelMeta.default_model || "");
      setGlobalWarning(modelWarnings());
    }).catch((e) => alert(String(e.message || e)))
  );
  byId("startBtn").addEventListener("click", () =>
    withAction("start_run", async () => {
      const r = await apiPost("/api/runs", readRunPayload());
      state.currentRunId = r.run_id;
      await refreshRunList(false);
      await refreshCurrentRun();
    }).catch((e) => alert(String(e.message || e)))
  );
  byId("stopBtn").addEventListener("click", () =>
    withAction("stop_run", async () => {
      if (!state.currentRunId) return;
      await apiPost(`/api/runs/${state.currentRunId}/cancel`, {});
      await refreshRunList(false);
      await refreshCurrentRun();
    }).catch((e) => alert(String(e.message || e)))
  );
  byId("refreshBtn").addEventListener("click", () =>
    withAction("refresh_run", async () => {
      await refreshSystemState();
      await refreshRunList(false);
      await refreshCache();
      await refreshCurrentRun();
    }).catch((e) => alert(String(e.message || e)))
  );
  byId("autotuneBtn").addEventListener("click", () =>
    withAction("autotune", runAutoTune).catch((e) => alert(String(e.message || e)))
  );
  byId("interpretBtn").addEventListener("click", () =>
    withAction("interpret", generateInterpretation).catch((e) => alert(String(e.message || e)))
  );
  byId("cacheRefreshBtn").addEventListener("click", () =>
    withAction("cache_refresh", refreshCache).catch((e) => alert(String(e.message || e)))
  );
  byId("cacheCleanupBtn").addEventListener("click", () =>
    withAction("cache_cleanup", async () => {
      if (!(await confirmCacheCleanup())) return;
      await apiPost("/api/cache/cleanup", { max_delete_bytes: 0 });
      await refreshCache();
    }).catch((e) => alert(String(e.message || e)))
  );
}

function startPolling() {
  if (state.timer) clearInterval(state.timer);
  state.timer = setInterval(() => {
    refreshSystemState().catch(() => {});
    refreshRunList(false).catch(() => {});
    refreshCache().catch(() => {});
    if (state.currentRunId) {
      refreshCurrentRun().catch(() => {});
    } else {
      updateActionStates();
    }
  }, 4500);
}

async function boot() {
  applyI18n();
  buildCharts();
  bindEvents();
  try {
    await loadBootstrap();
    startPolling();
  } catch (e) {
    setHealth(false, String(e.message || e));
  }
}

boot();
