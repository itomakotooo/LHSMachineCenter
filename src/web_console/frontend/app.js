// Pure helpers come from window.PURE (loaded by /console/pure.js).
// Lang-dependent helpers (fmt, statusText, cacheRiskTier, cacheRiskView,
// collectSystemWarnings, modelWarnings) are wrapped below to read from
// `state`. We read I18N through PURE.I18N directly rather than aliasing
// it, because pure.js already declares `const I18N` at the top-level
// binding scope; re-declaring it here breaks app.js with a SyntaxError.
const { fNum, fInt, fRate, fBytes } = PURE;

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
  fastTimer: null,
  autotuneTimer: null,
  // Captured at the moment Start is clicked so the polling code can
  // compute fuzzy-aware progress without re-deriving from API state.
  lastSubmittedFuzzy: false,
  lastSubmittedMaxChunks: 120,
  autoTuneRunning: false,
  busyActions: new Set(),
  // Only the multiplier-bucket chart survives the dashboard revision;
  // CI / RTP / bankruptcy already render as KPI cards.
  // bucketChart removed — bucket distribution is now a table.
  // Manage-tab run-history filter. Empty Set = show all; non-empty =
  // union of selected machines. Multi-select from machine catalog.
  runFilterMachines: new Set(),
  // Set of selected run_ids for batch operations.
  selectedRuns: new Set(),
  // Latest library-wide metric distributions (from
  // GET /api/library/distributions). Drives the "lib-P{N}" suffix on
  // Volatility + Archetype KPI cards so the operator sees where the
  // current machine stands across the library.
  libraryDistributions: null,
  // Per-machine-mode best-report summary (from GET /api/machines/summary).
  // { machines: { M14: { "1": {rtp_pct, ci_halfwidth_pp, ...}, ... }, ... } }
  machinesSummary: null,
  // Snapshot of current analyzer version + per-machine server md5s
  // (from GET /api/versions/current). Used by renderRunHistory to
  // render fresh/stale/untagged badges without per-row fetches.
  currentVersions: { analyzer_version: "", machines: {} },
  // Active batch-generate-report tracking. null when idle; holds
  // {batch_id, poll_timer} while a batch is in flight.
  batchGenerateId: null,
  batchGeneratePollTimer: null,
  // Last-known batch state from /api/rawdata/batch-generate-report/{id}
  // — drives the inline progress bar.
  batchGenerateProgress: null,
  // Active batch run state.
  activeBatchId: null,
  batchSelectedMachines: new Set(),
  servers: [],
  defaultServer: "",
  catalogViewMode: "category",  // "category" | "name" | "volatility" | "rtp" | "mechanic" | "hall"
  // 按大厅 view data: {halls: {hall_name: [machine_list]}, updated_at, source}.
  // Populated lazily on first "按大厅" tab click via GET /api/machines/halls.
  machineHalls: null,
  catalogFeatureFilter: new Set(),
  catalogSortReverse: false,  // reverse ordering toggle
  versionHistoryMachine: null,
  versionHistoryMode: null,
  compareSelected: new Set(),
  // True for a short window right after a batch completes: blocks
  // renderSamplingProgress so the final error log stays readable.
  // Cleared when the user clicks 开始采样 for a fresh batch.
  batchJustCompleted: false,
  // Client-side synthetic lifecycle events (click / submit / batch_created
  // / submit_failed / polling_started). These fill the observability
  // gap between a user click and the first analyzer chunk_progress
  // event (typically 30-60s of silence). Reset on each fresh batch.
  clientEvents: [],
  // Client-captured monotonic references so the UI can show "t+5.2s"
  // elapsed counters on running items — gives the operator visible
  // progress during the slow startup window.
  batchStartedAt: null,  // Date.now() when 开始采样 was clicked
  itemStartTimes: {},     // { run_id: Date.now() when first seen running }
  // Autotune result cache. Keyed by `${machine}|${mode}` → {robot_count,
  // batch_concurrency, success_rate, throughput, tuned_at}. When the
  // user clicks 开始采样 and an entry matches the first selected machine
  // + current sampleMode, those tuned values override the hardcoded
  // preset (robot=20 / concurrency=2). Persisted in localStorage so
  // tuning effort isn't wasted on page reload.
  tunedSamplingParams: (() => {
    try { return JSON.parse(localStorage.getItem("slot_console_tunedParams") || "{}"); }
    catch { return {}; }
  })(),
};

// Persist the sampling-panel selections + autotune cache across page
// reloads. Language handling already follows this pattern (line 71).
function _saveSamplingPrefs() {
  try {
    const mode = byId("sampleMode")?.value;
    const ci = byId("sampleCi")?.value;
    if (mode != null) localStorage.setItem("slot_console_sampleMode", mode);
    if (ci != null) localStorage.setItem("slot_console_sampleCi", ci);
    localStorage.setItem(
      "slot_console_tunedParams",
      JSON.stringify(state.tunedSamplingParams || {})
    );
  } catch {
    // localStorage can throw (quota, private-browsing) — best-effort
    // persistence, silent failure.
  }
}

function _restoreSamplingPrefs() {
  try {
    const mode = localStorage.getItem("slot_console_sampleMode");
    const ci = localStorage.getItem("slot_console_sampleCi");
    const modeSel = byId("sampleMode");
    const ciSel = byId("sampleCi");
    if (modeSel && mode && [...modeSel.options].some((o) => o.value === mode)) {
      modeSel.value = mode;
    }
    if (ciSel && ci && [...ciSel.options].some((o) => o.value === ci)) {
      ciSel.value = ci;
    }
  } catch {
    // no-op
  }
}

const byId = (id) => document.getElementById(id);
const fmt = (k, vars) => PURE.fmt(state.lang, k, vars);

function applyI18n() {
  if (!PURE.I18N[state.lang]) state.lang = "zh";
  localStorage.setItem("slot_console_lang", state.lang);
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  document.title = fmt("appTitle");
  byId("langSelect").value = state.lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = fmt(el.dataset.i18n)));
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => (el.placeholder = fmt(el.dataset.i18nPlaceholder)));
  document.querySelectorAll("[data-i18n-aria]").forEach((el) =>
    el.setAttribute("aria-label", fmt(el.dataset.i18nAria)),
  );
  applyFieldHelpHints();
  const autotuneBtnRefresh = byId("autotuneBtn");
  if (autotuneBtnRefresh) autotuneBtnRefresh.textContent = state.autoTuneRunning ? fmt("btnAutoTuneBusy") : fmt("btnAutoTune");
  setSystemStatePanel();
  renderCacheRiskMeta();
  updateChartLabels();
  renderLiveStatusStrip();
  updateActionStates();
}

// Topbar live-status strip. When a run is active the running poll passes
// the same summarizeRunEvent line + computed percent into here so the
// strip mirrors what runMeta shows in the panel; when idle/completed/no
// run we degrade to a "machine . mode . status" brief so the strip
// still communicates context. Kept entirely in DOM-land -- pure formatting
// of the running summary line still happens via PURE.summarizeRunEvent.
function renderLiveStatusStrip(opts) {
  const el = byId("liveStatusStrip");
  if (!el) return;
  el.innerHTML = "";
  if (opts && typeof opts.summary === "string" && opts.summary.length) {
    const text = document.createElement("span");
    text.className = "live-status-text";
    text.textContent = opts.summary;
    el.appendChild(text);
    if (typeof opts.pct === "number" && isFinite(opts.pct) && opts.pct >= 0) {
      const bar = document.createElement("div");
      bar.className = "live-status-bar";
      const fill = document.createElement("div");
      fill.className = "live-status-bar-fill";
      fill.style.width = `${Math.min(100, Math.max(0, opts.pct))}%`;
      bar.appendChild(fill);
      el.appendChild(bar);
    }
    return;
  }
  // Idle path -- "machine . mode . status" brief, suppressed entirely
  // until the bootstrap fills the machine selector.
  const machineEl = byId("machineSelect");
  const modeEl = byId("modeSelect");
  const machine = (machineEl && machineEl.value) || "";
  const mode = (modeEl && modeEl.value) || "";
  if (!machine) return;
  const parts = [machine];
  if (mode) parts.push(`mode ${mode}`);
  if (state.currentRunStatus) parts.push(statusText(state.currentRunStatus));
  const text = document.createElement("span");
  text.className = "live-status-text live-status-text--idle";
  text.textContent = parts.join(" \u00b7 ");
  el.appendChild(text);
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

// Writes the identifying info for the currently-loaded run into the
// 调试机台 tab's header panel (replaces the old "当前运行进度" status
// block). Shows WHAT is being viewed — machine / mode / run_id / status
// / report version / MD5 — without duplicating the metric values that
// the 关键指标 panel already surfaces.
function setLoadedMachineInfo(run, summaryLine) {
  const el = byId("loadedMachineInfo");
  if (!el) return;
  if (!run) {
    el.textContent = fmt("noRun");
    return;
  }
  const status = statusText(run.status);
  const statusCls = String(run.status || "").toLowerCase();
  const cfgMd5 = run.config_md5 ? String(run.config_md5).slice(0, 12) + "…" : "—";
  const rv = run.report_version || "—";
  const savedAt = (run.finished_at || run.started_at || "").replace("T", " ").replace(/\..*$/, "");
  const rows = [
    `<div><span class="lm-label">${fmt("thMachine")}:</span> <strong>${run.machine}</strong> · <span class="lm-label">${fmt("thMode")}:</span> <strong>mode ${run.mode}</strong></div>`,
    `<div><span class="lm-label">run_id:</span> <code>${run.run_id}</code> · <span class="lm-label lm-status lm-status-${statusCls}">${fmt("runStatusLabel")}: ${status}</span></div>`,
    `<div><span class="lm-label">report_version:</span> <code>${rv}</code> · <span class="lm-label">config_md5:</span> <code>${cfgMd5}</code></div>`,
    savedAt ? `<div><span class="lm-label">saved_at:</span> ${savedAt}</div>` : "",
  ];
  if (String(run.status).toLowerCase() === "failed") {
    rows.push(`<div class="lm-error">${fmt("runFailedLabel")}: ${PURE.formatRunFailureNote(state.lang, run.error_message)}</div>`);
  } else if (String(run.status).toLowerCase() === "cancelled") {
    rows.push(`<div class="lm-error">${fmt("runCancelledLabel")}: ${fmt("runCancelledText")}</div>`);
  }
  if (summaryLine) {
    rows.push(`<div class="lm-summary">${summaryLine}</div>`);
  }
  el.innerHTML = rows.filter(Boolean).join("");
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

async function apiPut(url, payload) {
  const res = await fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}) });
  if (!res.ok) throw new Error(`${url}: ${res.status} ${await res.text()}`);
  return res.json();
}

async function apiDelete(url) {
  const res = await fetch(url, { method: "DELETE" });
  if (!res.ok) throw new Error(`${url}: ${res.status} ${await res.text()}`);
  return res.json();
}

const statusText = (s) => PURE.statusText(state.lang, s);

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

const collectSystemWarnings = () =>
  PURE.collectSystemWarnings({ lang: state.lang, systemState: state.systemState });

// Risk-tier helpers wrap PURE so they can read state.lang and the latest
// risk_thresholds returned by /api/cache/status.
const cacheRiskTier = (reclaimableBytes) =>
  PURE.cacheRiskTier(reclaimableBytes, state.cacheStatus && state.cacheStatus.risk_thresholds);
const cacheRiskView = (cachedStatus) => PURE.cacheRiskView(state.lang, cachedStatus);

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

  // Model-config save button (now nested inside 模型解读 panel).
  const saveModelBtn = byId("saveModelCfgBtn");
  if (saveModelBtn) saveModelBtn.disabled = localBusy || serverBusy;

  // Autotune moved to 采样选中机台 panel on the manage tab. It operates
  // on the catalog-selected machines (state.runFilterMachines), not on
  // the old sidebar machineSelect. Disabled if no machine selected.
  const autotuneBtn = byId("autotuneBtn");
  const hasSelection = state.runFilterMachines && state.runFilterMachines.size > 0;
  if (autotuneBtn) {
    autotuneBtn.disabled = localBusy || serverBusy || anyRunRunning || !hasSelection;
    autotuneBtn.textContent = state.autoTuneRunning ? fmt("btnAutoTuneBusy") : fmt("btnAutoTune");
  }

  // Batch Generate Report: rebuild reports from cached rawdata across
  // every catalog-selected machine for the current sampleMode. Disabled
  // when no selection / a run is already active / another batch is
  // tracked in state.batchGenerateId.
  const batchGenBtn = byId("batchGenerateBtn");
  if (batchGenBtn) {
    const batchActive = Boolean(state.batchGenerateId);
    batchGenBtn.disabled = (
      localBusy || serverBusy || anyRunRunning || !hasSelection || batchActive
    );
    batchGenBtn.textContent = batchActive
      ? fmt("batchGenerateBusy", {
          done: state.batchGenerateProgress?.completed ?? 0,
          total: state.batchGenerateProgress?.total ?? 0,
        })
      : fmt("btnBatchGenerate");
  }

  // Interpretation can run on any run that produced a valid summary
  // -- "completed" (hit CI target / max_chunks) OR "cancelled"
  // (graceful user stop with partial data). Not "failed" (no summary)
  // or "running".
  const interpretBtn = byId("interpretBtn");
  if (interpretBtn) {
    interpretBtn.disabled = localBusy || serverBusy || !hasCurrent || (
      currentStatus !== "completed" && currentStatus !== "cancelled"
    );
  }

  const cacheRefreshBtn = byId("cacheRefreshBtn");
  if (cacheRefreshBtn) cacheRefreshBtn.disabled = localBusy;
  const runningCount = Number(state.cacheStatus?.running_runs ?? state.systemState?.running_runs_count ?? 0);
  const cacheCleanupBtn = byId("cacheCleanupBtn");
  if (cacheCleanupBtn) {
    cacheCleanupBtn.disabled = localBusy || serverBusy || runningCount > 0 || reclaimable <= 0;
    cacheCleanupBtn.classList.toggle("danger-high", tier === "high");
  }
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
  if (!el) return; // element may have been replaced (e.g. kpiTail → kpiTailGrid)
  el.textContent = text;
  el.dataset.tone = tone;
  // Mirror the tone onto the parent .kpi card via a BEM modifier so the
  // whole-card background can react to status. We keep the old strong[
  // data-tone] text-color rule alongside it (deliberate: bg + text-color
  // both reinforce the tone, no class removal required for back-compat).
  const card = el.closest(".kpi");
  if (card) {
    card.classList.remove("kpi--good", "kpi--warn", "kpi--bad");
    if (tone === "good" || tone === "warn" || tone === "bad") {
      card.classList.add(`kpi--${tone}`);
    }
  }
}

function clearSummaryPanels() {
  byId("assessment").textContent = fmt("noReport");
  byId("interpretationText").textContent = fmt("noInterpret");
  byId("eventsText").textContent = fmt("noEvents");
  if (!state.autoTuneRunning) {
    const autoEl = byId("autotuneMeta");
    if (autoEl) autoEl.textContent = fmt("noAutoTune");
  }
  setKpi("kpiRtp", "N/A");
  setKpi("kpiCi", "N/A");
  setKpi("kpiSpins", "N/A");
  setKpi("kpiZero", "N/A");
  // kpiTail replaced by kpiTailGrid (2×2 grid, not a single <strong>).
  setKpi("kpiGuide", "N/A");
  setKpi("kpiVolatility", "N/A");
  setKpi("kpiArchetype", "N/A");
  setKpi("kpiLossStreak", "N/A");
  setKpi("kpiMaxReturn", "N/A");
  setKpi("kpiBigWin", "N/A");
  setKpi("kpiBankruptX500", "N/A");
  byId("kpiTailGrid").innerHTML = "";
  const bt = byId("bucketTable");
  if (bt) bt.querySelector("tbody").innerHTML = "";
  const fdp = byId("fieldDiscoveryPanel");
  if (fdp) fdp.classList.add("hidden");
  const mmp = byId("machineMechanicsPanel");
  if (mmp) mmp.classList.add("hidden");
}

// Chart.js removed — bucket distribution is now a table.
function buildCharts() {}
function updateChartLabels() {}

// Category → color mapping for badges and card tints.
const CATEGORY_COLORS = {
  Normal: "#6b7280", Collect: "#7c3aed", Lock: "#ea580c",
  FreeSpin: "#059669", ReSpin: "#0891b2", Wheel: "#d97706",
  Fortunes: "#c026d3", Selector: "#6366f1", Other: "#9ca3af", Unknown: "#9ca3af",
};
const VOL_COLORS = { Low: "#059669", Medium: "#2563eb", High: "#ea580c", "Very High": "#dc2626" };

const MECH_ICONS = { lock_lines: "\ud83d\udd12", lock_symbols: "\ud83d\udcce", lock_reels: "\ud83c\udfaa", jackpot: "\ud83c\udfc6", free_spin: "\ud83c\udfb0", dollar_pick: "\ud83d\udcb5" };

function _catalogModeMetrics(machine) {
  const sm = ((state.machinesSummary || {}).machines || {})[machine] || {};
  const modes = Object.keys(sm).sort((a, b) => Number(a) - Number(b));
  if (!modes.length) return "";
  return modes.map((mode) => {
    const d = sm[mode];
    const rtp = d.rtp_pct != null ? d.rtp_pct.toFixed(1) + "%" : "—";
    const ci = d.ci_halfwidth_pp != null ? "\u00b1" + d.ci_halfwidth_pp.toFixed(1) : "";
    const vol = d.volatility_class || "";
    const pct = d.volatility_percentile != null ? `P${d.volatility_percentile}` : "";
    const vc = VOL_COLORS[vol] || "#888";
    const volHtml = vol ? `<span class="cat-vol" style="color:${vc}">${vol} ${pct}</span>` : "";
    const mechIcons = (d.mechanics || []).map((mk) => MECH_ICONS[mk] || "").join("");
    const md5 = d.md5_status;
    const ciVal = d.ci_halfwidth_pp;
    const ciAccurate = ciVal != null && ciVal <= 0.5;
    let md5Icon = '';
    if (md5 === "match") {
      md5Icon = ciAccurate
        ? '<span class="md5-match" title="report MD5 匹配上游，CI ≤ 0.5pp">✓</span>'
        : `<span class="md5-partial" title="report MD5 匹配但 CI 不精确 (${ciVal == null ? 'null' : '>' + '0.5pp'})">🟡</span>`;
    } else if (md5 === "outdated") {
      md5Icon = '<span class="md5-mismatch" title="机台版本已变更，report 过期">⚠</span>';
    } else if (md5 === "untagged") {
      md5Icon = '<span class="muted" title="旧格式 report 无 MD5 标签">?</span>';
    }
    return `<div class="cat-mode-row">${md5Icon} <span class="cat-mode-label">m${mode}</span> <span class="cat-rtp">${rtp}</span> <span class="cat-ci">${ci}</span> ${volHtml}${mechIcons ? ` <span class="cat-mech" title="${d.mechanics.join(', ')}">${mechIcons}</span>` : ""}</div>`;
  }).join("");
}

// Get the primary summary data for a machine (prefer mode 2, fallback lowest).
function _machineData(machineName) {
  const sm = ((state.machinesSummary || {}).machines || {})[machineName] || {};
  const modes = Object.keys(sm);
  if (!modes.length) return null;
  const best = modes.includes("2") ? "2" : modes.sort((a, b) => Number(a) - Number(b))[0];
  return sm[best] || null;
}

// Card background color based on volatility percentile (heat map).
function _cardBgColor(machineName) {
  const d = _machineData(machineName);
  if (!d || d.volatility_percentile == null) return "";
  const p = d.volatility_percentile;
  // Green (low vol) → Yellow → Orange → Red (high vol)
  if (p < 25) return "#f0fdf4";
  if (p < 50) return "#fefce8";
  if (p < 75) return "#fff7ed";
  return "#fef2f2";
}

// Get all features a machine has across all its modes.
function _machineFeatures(machineName) {
  const modes = ((state.machinesSummary || {}).machines || {})[machineName] || {};
  const features = new Set();
  Object.values(modes).forEach((d) => (d.features || []).forEach((f) => features.add(f)));
  return [...features];
}

// Features used by ≥2 machines are "primary"; singletons → "其他".
function _featureIsSingleton(featureName) {
  const dist = (state.machinesSummary || {}).feature_distribution || {};
  return (dist[featureName] || 0) < 2;
}

// Group machines by the current view mode.
function _groupMachines(machines, viewMode) {
  const groups = {};
  const sm = (state.machinesSummary || {}).machines || {};

  machines.forEach((m) => {
    let key;
    if (viewMode === "name" || viewMode === "category") {
      // "按玩法" view: filter chips drive the selection. Output is a single flat list.
      // The filter itself is applied earlier (in renderMachineCatalog).
      key = "all";
    } else if (viewMode === "volatility") {
      const d = _machineData(m.machine);
      key = d?.volatility_class || "N/A";
    } else if (viewMode === "rtp") {
      const d = _machineData(m.machine);
      const rtp = d?.rtp_pct;
      if (rtp == null) key = "N/A";
      else if (rtp < 90) key = "< 90%";
      else if (rtp < 95) key = "90–95%";
      else if (rtp < 100) key = "95–100%";
      else if (rtp < 200) key = "100–200%";
      else if (rtp < 400) key = "200–400%";
      else key = "> 400%";
    } else if (viewMode === "hall") {
      // Map machine → hall_name using cached data. Machines not
      // present in any hall go into "未分组".
      const halls = (state.machineHalls && state.machineHalls.halls) || {};
      let hallOfMachine = null;
      for (const [hallName, machineList] of Object.entries(halls)) {
        if ((machineList || []).includes(m.machine)) {
          hallOfMachine = hallName;
          break;
        }
      }
      key = hallOfMachine || "未分组";
    } else if (viewMode === "mechanic") {
      const mdata = sm[m.machine] || {};
      const allMechs = new Set();
      Object.values(mdata).forEach((d) => (d.mechanics || []).forEach((mk) => allMechs.add(mk)));
      if (allMechs.size === 0) key = "Normal";
      else allMechs.forEach((mk) => {
        if (!groups[mk]) groups[mk] = [];
        groups[mk].push(m);
      });
      if (allMechs.size > 0) return; // already added
      // fall through for Normal
    } else {
      key = "all";
    }
    if (!groups[key]) groups[key] = [];
    groups[key].push(m);
  });
  return groups;
}

const MECH_GROUP_LABELS = {
  lock_lines: "Lock Lines", lock_symbols: "Lock Symbols", lock_reels: "Lock Reels",
  jackpot: "Jackpot", free_spin: "Free Spin", dollar_pick: "Dollar Pick",
  Normal: "Normal (无特殊机制)",
};
const MECH_GROUP_COLORS = {
  lock_lines: "#ea580c", lock_symbols: "#d97706", lock_reels: "#b45309",
  jackpot: "#7c3aed", free_spin: "#059669", dollar_pick: "#6366f1",
  Normal: "#6b7280",
};

function _groupOrder(viewMode) {
  if (viewMode === "volatility") return ["Low", "Medium", "High", "Very High", "N/A"];
  if (viewMode === "rtp") return ["< 90%", "90–95%", "95–100%", "100–200%", "200–400%", "> 400%", "N/A"];
  if (viewMode === "mechanic") return ["lock_lines", "lock_symbols", "lock_reels", "jackpot", "free_spin", "dollar_pick", "Normal"];
  if (viewMode === "hall") {
    // Sorted by hall name; "未分组" bucket always last.
    const halls = (state.machineHalls && state.machineHalls.halls) || {};
    const names = Object.keys(halls).sort();
    names.push("未分组");
    return names;
  }
  return ["all"]; // name, category → flat
}

// Generate a distinct pastel color per feature name (deterministic hash).
function _featureColor(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) | 0;
  const hue = Math.abs(h) % 360;
  return `hsl(${hue}, 65%, 88%)`;
}

// Render feature filter chips for "按玩法" view.
function renderCatalogFeatureChips() {
  const wrap = byId("catalogFeatureChips");
  if (!wrap) return;
  if (state.catalogViewMode !== "category") {
    wrap.innerHTML = "";
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.remove("hidden");

  const dist = (state.machinesSummary || {}).feature_distribution || {};
  const multi = Object.entries(dist)
    .filter(([, n]) => n >= 2)
    .sort((a, b) => b[1] - a[1]);
  const singletons = Object.entries(dist).filter(([, n]) => n < 2);
  const selected = state.catalogFeatureFilter;

  const chips = multi.map(([fn, n]) => {
    const active = selected.has(fn) ? "active" : "";
    const bg = _featureColor(fn);
    return `<button class="feature-chip ${active}" data-feature="${fn}" style="background:${bg}">${fn} <span class="chip-count">${n}</span></button>`;
  }).join("");

  const otherActive = selected.has("__other__") ? "active" : "";
  const otherChip = singletons.length
    ? `<button class="feature-chip ${otherActive}" data-feature="__other__" style="background:#e5e7eb">其他 <span class="chip-count">${singletons.length}</span></button>`
    : "";

  const clearBtn = selected.size
    ? `<button class="feature-chip-clear">${fmt("filterClear")} (${selected.size})</button>`
    : "";

  wrap.innerHTML = chips + otherChip + clearBtn;

  wrap.querySelectorAll(".feature-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const fn = btn.dataset.feature;
      if (selected.has(fn)) selected.delete(fn);
      else selected.add(fn);
      renderCatalogFeatureChips();
      renderMachineCatalog();
    });
  });
  wrap.querySelector(".feature-chip-clear")?.addEventListener("click", () => {
    state.catalogFeatureFilter = new Set();
    renderCatalogFeatureChips();
    renderMachineCatalog();
  });
}

function renderMachineCatalog() {
  const wrap = byId("machineCatalog");
  wrap.innerHTML = "";
  if (!state.machines.length) return (wrap.textContent = fmt("noMachines"));

  const query = (byId("catalogSearch")?.value || "").trim().toLowerCase();
  const viewMode = state.catalogViewMode || "category";

  // Filter by search.
  let filtered = state.machines;
  if (query) {
    filtered = filtered.filter((m) =>
      m.machine.toLowerCase().includes(query) ||
      (m.category || "").toLowerCase().includes(query)
    );
  }
  // Filter by feature chips (只在"按玩法" view 生效).
  if (viewMode === "category" && state.catalogFeatureFilter.size > 0) {
    const dist = (state.machinesSummary || {}).feature_distribution || {};
    filtered = filtered.filter((m) => {
      const features = _machineFeatures(m.machine);
      if (state.catalogFeatureFilter.has("__other__")) {
        // "其他" selected: match machines with any singleton feature.
        if (features.some((f) => (dist[f] || 0) < 2)) return true;
      }
      // OR-semantics: machine matches if it has any selected feature.
      return features.some((f) => state.catalogFeatureFilter.has(f));
    });
  }
  if (!filtered.length) {
    wrap.textContent = query ? fmt("catalogNoMatch") : fmt("noMachines");
    return;
  }

  const groups = _groupMachines(filtered, viewMode);
  const order = _groupOrder(viewMode);
  const orderedKeys = order.filter((k) => groups[k]);
  Object.keys(groups).forEach((k) => { if (!orderedKeys.includes(k)) orderedKeys.push(k); });

  // Sort within groups: by machine number for most views. Reverse if toggled.
  const dir = state.catalogSortReverse ? -1 : 1;
  const numSort = (a, b) => dir * ((parseInt(a.machine.slice(1)) || 0) - (parseInt(b.machine.slice(1)) || 0));
  Object.values(groups).forEach((arr) => arr.sort(numSort));
  if (state.catalogSortReverse) orderedKeys.reverse();

  const isFlatView = viewMode === "name" || viewMode === "category";

  orderedKeys.forEach((groupKey) => {
    const machines = groups[groupKey];
    const section = document.createElement("div");
    section.className = "catalog-group";

    if (!isFlatView) {
      const isMechView = viewMode === "mechanic";
      const catColor = CATEGORY_COLORS[groupKey] || VOL_COLORS[groupKey] || (isMechView ? MECH_GROUP_COLORS[groupKey] : null) || "#9ca3af";
      const displayName = isMechView ? (MECH_GROUP_LABELS[groupKey] || groupKey) : groupKey;
      const header = document.createElement("div");
      header.className = "catalog-group-header";
      header.innerHTML = `<span class="catalog-group-arrow">&#9660;</span> <span class="catalog-group-dot" style="background:${catColor}"></span> <span class="catalog-group-name">${displayName}</span> <span class="catalog-group-count">(${machines.length})</span>`;
      header.addEventListener("click", () => {
        section.classList.toggle("collapsed");
        header.querySelector(".catalog-group-arrow").innerHTML = section.classList.contains("collapsed") ? "&#9654;" : "&#9660;";
      });
      section.appendChild(header);
      // Auto-collapse when no search.
      if (!query) {
        section.classList.add("collapsed");
        header.querySelector(".catalog-group-arrow").innerHTML = "&#9654;";
      }
    }

    const grid = document.createElement("div");
    grid.className = "catalog-list";
    machines.forEach((m) => {
      const d = document.createElement("div");
      d.className = "catalog-item";
      const isActive = state.runFilterMachines.has(m.machine);
      // Don't apply heatmap bg on active cards (selection bg wins).
      if (!isActive) {
        const bg = _cardBgColor(m.machine);
        if (bg) d.style.background = bg;
      }
      const catColor = CATEGORY_COLORS[m.category] || "#9ca3af";
      d.style.borderLeftColor = catColor;
      if (isActive) d.classList.add("active");
      if (m.available === false) d.classList.add("unavailable");
      d.dataset.machine = m.machine;
      d.setAttribute("role", "button");
      d.setAttribute("tabindex", "0");
      const metrics = _catalogModeMetrics(m.machine);
      const reportBadge = m.report_count ? `<span class="catalog-badge" style="background:${catColor}">${m.report_count}</span>` : "";
      // Broken-machine badge: ⚠ with tooltip listing each anomaly.
      // Clicking the flag does nothing itself (the card click handler
      // still toggles selection) — it's a read-only indicator.
      const issues = _machineBrokenIssues(m.machine);
      const brokenBadge = issues.length
        ? `<span class="catalog-broken" title="${issues.join(' · ').replace(/"/g, '&quot;')}">⚠</span>`
        : "";
      d.innerHTML = `<div class="catalog-title">${m.machine}${brokenBadge}${reportBadge}</div>${metrics || `<div class="catalog-modes">modes: ${(m.modes || []).join(", ")}</div>`}`;
      if (issues.length) d.classList.add("broken-machine");
      grid.appendChild(d);
    });
    section.appendChild(grid);
    wrap.appendChild(section);
  });
  // Click / keydown listeners live on #machineCatalog itself (event
  // delegation, set up once in _initCatalogDelegation), so we don't
  // attach per-card listeners on every re-render — 253 cards × 2 events
  // was ~506 addEventListener calls per render.
}

// Single delegated click + keydown handler for the whole catalog grid.
// Attached once at init. Toggles .active on the clicked card inline
// rather than triggering a full renderMachineCatalog() — the full
// render (~10ms for 253 cards) was only there to re-apply the class;
// targeted DOM mutation keeps the clicks under 1ms.
function _toggleCatalogMachineSelection(machine) {
  if (!machine) return;
  const wasActive = state.runFilterMachines.has(machine);
  if (wasActive) state.runFilterMachines.delete(machine);
  else state.runFilterMachines.add(machine);

  const el = document.querySelector(`.catalog-item[data-machine="${CSS.escape(machine)}"]`);
  if (el) {
    el.classList.toggle("active", !wasActive);
    // .active CSS uses !important background, which overrides the
    // heatmap inline bg while selected. On deselect restore; on
    // select clear the inline style so the !important rule wins
    // without fighting specificity.
    if (wasActive) {
      const bg = _cardBgColor(machine);
      el.style.background = bg || "";
    } else {
      el.style.background = "";
    }
  }

  renderRunHistory();
  updateSampleHint();
  // Selection change affects the ⚙ 调参 button's enabled state (needs
  // at least one machine). Refresh action states so the button goes
  // from disabled → enabled (and vice-versa) as the user toggles.
  updateActionStates();
  if (state.runFilterMachines.has(machine)) {
    showVersionHistory(machine);
    showMachineDetail(machine);
  } else if (state.runFilterMachines.size === 1) {
    const last = [...state.runFilterMachines][0];
    showVersionHistory(last);
    showMachineDetail(last);
  } else if (state.runFilterMachines.size === 0) {
    byId("versionHistoryPanel")?.classList.add("hidden");
    byId("reportComparisonPanel")?.classList.add("hidden");
    byId("machineDetailPanel")?.classList.add("hidden");
  }
}

function _initCatalogDelegation() {
  const wrap = byId("machineCatalog");
  if (!wrap || wrap.dataset.delegationInit === "1") return;
  wrap.dataset.delegationInit = "1";
  wrap.addEventListener("click", (e) => {
    const el = e.target.closest(".catalog-item");
    if (!el || !wrap.contains(el)) return;
    _toggleCatalogMachineSelection(el.dataset.machine);
  });
  wrap.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const el = e.target.closest(".catalog-item");
    if (!el || !wrap.contains(el)) return;
    e.preventDefault();
    _toggleCatalogMachineSelection(el.dataset.machine);
  });
}

// ── Catalog Mechanic Filters ──────────────────────────────────────

function renderCatalogFilters() {
  const el = byId("catalogFilters");
  if (!el) return;
  const mechDist = (state.machinesSummary || {}).mechanics_distribution || {};
  if (!Object.keys(mechDist).length) { el.innerHTML = ""; return; }

  const LABELS = { lock_lines: "Lock Lines", lock_symbols: "Lock Sym", jackpot: "Jackpot", free_spin: "FreeSpin", dollar_pick: "Dollar Pick" };
  const active = state.catalogMechFilter;

  el.innerHTML = Object.entries(mechDist)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([k, n]) => {
      const cls = active === k ? "filter-chip active" : "filter-chip";
      return `<button class="${cls}" data-mech="${k}">${MECH_ICONS[k] || ""} ${LABELS[k] || k} (${n})</button>`;
    }).join("") + (active ? `<button class="filter-chip filter-clear">${fmt("filterClear")}</button>` : "");

  el.querySelectorAll(".filter-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mech = btn.dataset.mech;
      if (btn.classList.contains("filter-clear") || state.catalogMechFilter === mech) {
        state.catalogMechFilter = null;
      } else {
        state.catalogMechFilter = mech;
      }
      renderCatalogFilters();
      renderMachineCatalog();
    });
  });
}

// ── Machine Detail Panel ──────────────────────────────────────────

function showMachineDetail(machineName) {
  const panel = byId("machineDetailPanel");
  if (!panel) return;
  const m = state.machines.find((x) => x.machine === machineName);
  if (!m) { panel.classList.add("hidden"); return; }

  panel.classList.remove("hidden");
  byId("machineDetailTitle").textContent = `${machineName} — ${m.category || "?"}`;

  const logic = (m.logicClassNames || []).join(", ") || "—";
  const configMd5 = m.configSummaryMd5 ? m.configSummaryMd5.slice(0, 12) + "…" : "—";
  const codeMd5 = m.codeSummaryMd5 ? m.codeSummaryMd5.slice(0, 12) + "…" : "—";

  // Per-mode metrics from summary
  const sm = ((state.machinesSummary || {}).machines || {})[machineName] || {};
  const modes = Object.keys(sm).sort((a, b) => Number(a) - Number(b));
  let metricsHtml = "";
  if (modes.length) {
    metricsHtml = `<table class="drilldown-table detail-metrics-table">
      <thead><tr><th>Mode</th><th>RTP</th><th>CI\u00b1</th><th>Spins</th><th>${fmt("thVolatility")}</th><th>${fmt("thMechanics")}</th></tr></thead>
      <tbody>${modes.map((mode) => {
        const d = sm[mode];
        const vc = VOL_COLORS[d.volatility_class] || "#888";
        return `<tr>
          <td>m${mode}</td>
          <td>${d.rtp_pct != null ? d.rtp_pct.toFixed(2) + "%" : "—"}</td>
          <td>${d.ci_halfwidth_pp != null ? "\u00b1" + d.ci_halfwidth_pp.toFixed(2) : "—"}</td>
          <td>${d.total_spins ? Number(d.total_spins).toLocaleString() : "—"}</td>
          <td style="color:${vc}">${d.volatility_class || "—"} ${d.volatility_percentile != null ? "P" + d.volatility_percentile : ""}</td>
          <td>${(d.mechanics || []).map((mk) => MECH_ICONS[mk] || mk).join(" ") || "—"}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
  } else {
    metricsHtml = `<div class="muted">${fmt("noVersions")}</div>`;
  }

  byId("machineDetailBody").innerHTML = `
    <div class="detail-meta">
      <div><span class="detail-label">${fmt("detailLogicClasses")}</span> <code>${logic}</code></div>
      <div><span class="detail-label">${fmt("detailConfigMd5")}</span> <code>${configMd5}</code></div>
      <div><span class="detail-label">${fmt("detailCodeMd5")}</span> <code>${codeMd5}</code></div>
      <div><span class="detail-label">${fmt("detailReports")}</span> ${m.report_count || 0}</div>
    </div>
    ${metricsHtml}
    <div id="rawdataSection" class="rawdata-section"><div class="muted">加载本地 rawdata 状态…</div></div>`;

  // Load rawdata status async.
  _loadRawdataSection(machineName);
}

async function _loadRawdataSection(machineName) {
  const section = byId("rawdataSection");
  if (!section) return;
  try {
    const data = await apiGet(`/api/rawdata/${machineName}`);
    const modes = Object.entries(data.modes || {});
    if (!modes.length) {
      section.innerHTML = `<div class="rawdata-header">📦 本地 Rawdata</div><div class="muted">无本地 rawdata</div>`;
      return;
    }
    // Each mode gets a card showing:
    //   - classified summary (kept / deletable / stale counts + spins)
    //   - per-version breakdown (current server version vs outdated)
    //   - Safe delete button (respects retention) + Force delete (nuclear)
    const fInt = (n) => Number(n || 0).toLocaleString();
    const fMb = (n) => {
      const mb = Number(n || 0);
      return mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(1)} MB`;
    };
    const rows = modes.sort((a, b) => Number(a[0]) - Number(b[0])).map(([mode, st]) => {
      const cls = st.classified || {};
      const versions = Array.isArray(st.versions) ? st.versions : [];
      const unverifiable = st.unverifiable ? " (无上游 MD5 参考)" : "";
      const retention = cls.min_retention_spins ?? 100000;
      const keptSpins = fInt(cls.kept_spins);
      const keptChunks = cls.kept_chunks ?? 0;
      const delChunks = cls.deletable_chunks ?? 0;
      const delSpins = fInt(cls.deletable_spins);
      const staleChunks = cls.stale_chunks ?? 0;
      const staleSpins = fInt(cls.stale_spins);
      const versionRows = versions.map((v) => {
        const tag = v.is_current
          ? `<span class="rawdata-version-tag current">当前版本</span>`
          : `<span class="rawdata-version-tag old">服务器旧版 (stale)</span>`;
        const cfgShort = (v.config_md5 || "").slice(0, 8) || "—";
        const codeShort = (v.code_md5 || "").slice(0, 8) || "—";
        const total = (v.kept_chunks || 0) + (v.deletable_chunks || 0) + (v.stale_chunks || 0);
        return `<div class="rawdata-version-row">
          ${tag}
          <code>cfg=${cfgShort}</code> <code>code=${codeShort}</code>
          · ${total} chunks
          · kept ${v.kept_chunks || 0} / deletable ${v.deletable_chunks || 0}${v.stale_chunks ? ` / stale ${v.stale_chunks}` : ""}
        </div>`;
      }).join("");
      const delDisabled = (delChunks + staleChunks) === 0 ? "disabled" : "";
      // 生成 Report 按钮：至少有一个非 stale chunk 可用才启用
      const genDisabled = (keptChunks + delChunks) === 0 ? "disabled" : "";
      return `<div class="rawdata-row">
        <div class="rawdata-row-head">
          <strong>mode ${mode}</strong>
          · 保底 ${keptChunks} chunks / ${keptSpins} spins (≥${fInt(retention)})
          ${delChunks > 0 ? `· 可回收 ${delChunks} chunks / ${delSpins} spins` : ""}
          ${staleChunks > 0 ? `· <span class="rawdata-stale">过期 ${staleChunks} / ${staleSpins}</span>` : ""}
          · ${fMb(st.total_size_mb)}${unverifiable}
        </div>
        <div class="rawdata-versions">${versionRows || '<span class="muted">无 chunk</span>'}</div>
        <div class="rawdata-row-actions">
          <button class="small-btn primary-btn rawdata-generate-btn" data-machine="${machineName}" data-mode="${mode}" ${genDisabled} title="用当前 analyzer 代码重新跑这 (${keptChunks + delChunks}) 个 chunks 生成新 report">⟳ 生成 Report</button>
          <button class="small-btn rawdata-delete-btn" data-machine="${machineName}" data-mode="${mode}" ${delDisabled} title="删除可回收 + 过期 chunks，保留 baseline">删除可回收</button>
          <button class="small-btn danger-btn rawdata-force-delete-btn" data-machine="${machineName}" data-mode="${mode}" title="完全删除 (含 baseline)">完全删除</button>
        </div>
      </div>`;
    }).join("");
    section.innerHTML = `<div class="rawdata-header">📦 本地 Rawdata (采样时会自动复用)</div>${rows}
      <div class="rawdata-all-actions">
        <button class="small-btn rawdata-delete-all-btn" data-machine="${machineName}" title="删除所有 mode 的可回收 + 过期 chunks">删除全部 mode (保留 baseline)</button>
        <button class="small-btn danger-btn rawdata-force-delete-all-btn" data-machine="${machineName}" title="完全删除所有 mode">完全删除所有 mode</button>
      </div>`;

    section.querySelectorAll(".rawdata-generate-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const m = btn.dataset.machine, mo = btn.dataset.mode;
        const origText = btn.textContent;
        btn.disabled = true;
        btn.textContent = "生成中…（后台运行，见活动日志）";
        try {
          // Async path: backend returns immediately with run_id;
          // activity strip + run list show progress.
          await apiPost(
            `/api/rawdata/${encodeURIComponent(m)}/generate-report`,
            { mode: Number(mo), async: true },
          );
          btn.textContent = "⏳ 已入队";
          await refreshRunList(false);
          // Keep button disabled until serverBusy clears (will be
          // re-enabled by the next updateActionStates cycle).
          setTimeout(() => {
            btn.textContent = origText;
            btn.disabled = false;
          }, 4000);
        } catch (err) {
          btn.textContent = "✗";
          alert(`生成 Report 失败: ${String(err && err.message ? err.message : err)}`);
          setTimeout(() => {
            btn.textContent = origText;
            btn.disabled = false;
          }, 3000);
        }
      });
    });
    section.querySelectorAll(".rawdata-delete-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const m = btn.dataset.machine, mo = btn.dataset.mode;
        // Guard against concurrent ops — backend also rejects with
        // 409 but fail-fast in UI is friendlier.
        if (state.systemState?.operation_busy) {
          alert(`有操作进行中 (${state.systemState.operation || "busy"})，请等待完成再删除。`);
          return;
        }
        if (!confirm(`删除 ${m} mode ${mo} 的可回收 + 过期 chunks？baseline 保留。`)) return;
        try {
          await apiDelete(`/api/rawdata/${m}?mode=${mo}`);
        } catch (err) {
          alert(`删除失败: ${String(err?.message || err)}`);
          return;
        }
        _loadRawdataSection(machineName);
      });
    });
    section.querySelectorAll(".rawdata-force-delete-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const m = btn.dataset.machine, mo = btn.dataset.mode;
        if (state.systemState?.operation_busy) {
          alert(`有操作进行中 (${state.systemState.operation || "busy"})，请等待完成再删除。`);
          return;
        }
        const tok = prompt(`完全删除 ${m} mode ${mo} 的所有 rawdata (含 baseline)？输入 DELETE 确认：`);
        if (tok !== "DELETE") return;
        try {
          await apiDelete(`/api/rawdata/${m}?mode=${mo}&force=true`);
        } catch (err) {
          alert(`删除失败: ${String(err?.message || err)}`);
          return;
        }
        _loadRawdataSection(machineName);
      });
    });
    section.querySelector(".rawdata-delete-all-btn")?.addEventListener("click", async () => {
      if (state.systemState?.operation_busy) {
        alert(`有操作进行中 (${state.systemState.operation || "busy"})，请等待完成再删除。`);
        return;
      }
      if (!confirm(`删除 ${machineName} 所有 mode 的可回收 chunks？baseline 保留。`)) return;
      await apiDelete(`/api/rawdata/${machineName}`);
      _loadRawdataSection(machineName);
    });
    section.querySelector(".rawdata-force-delete-all-btn")?.addEventListener("click", async () => {
      const tok = prompt(`完全删除 ${machineName} 所有 rawdata (含 baseline)？输入 DELETE 确认：`);
      if (tok !== "DELETE") return;
      await apiDelete(`/api/rawdata/${machineName}?force=true`);
      _loadRawdataSection(machineName);
    });
  } catch (e) {
    section.innerHTML = `<div class="muted">加载失败: ${e.message || e}</div>`;
  }
}

// ── Fleet Overview ────────────────────────────────────────────────

// Expected RTP ranges per mode (mode_id → [min, max] percent).
// mode 1: ~90% (classic base), mode 7: ~80% (strict base)
// mode 2: "幸运" mode >200%, mode 5: most extreme, should be > mode 2
const _MODE_RTP_EXPECT = {
  1: { min: 80, max: 100, label: "mode 1 ~90%" },
  7: { min: 70, max: 90, label: "mode 7 ~80%" },
  2: { min: 150, max: Infinity, label: "mode 2 应 > 150%" },
  5: { min: 200, max: Infinity, label: "mode 5 应 > mode 2" },
};

// Per-machine broken flags (B3). Same anomaly rules as fleet headlines
// (_computeFleetHeadlines) but returns per-machine lists so catalog
// cards can surface a ⚠ badge with tooltip. Returns list of short
// strings ("mode 1 RTP 51%") or empty array when healthy.
function _machineBrokenIssues(machine) {
  const sm = (state.machinesSummary || {}).machines || {};
  const mConfig = (state.machines || []).find((x) => x.machine === machine);
  if (!mConfig) return [];
  const modes = sm[machine] || {};
  const expected = mConfig.modes || [1, 2, 5, 7];
  const actual = Object.keys(modes).map(Number);
  const issues = [];
  // Missing modes
  const missing = expected.filter((x) => !actual.includes(x));
  if (missing.length && mConfig.available !== false) {
    issues.push(`缺 mode ${missing.join(",")}`);
  }
  // Per-mode RTP expectation
  for (const modeStr of Object.keys(modes)) {
    const mode = Number(modeStr);
    const d = modes[modeStr];
    const rtp = d.rtp_pct;
    if (rtp == null) continue;
    const exp = _MODE_RTP_EXPECT[mode];
    if (exp && (rtp < exp.min || rtp > exp.max)) {
      issues.push(`mode ${mode} RTP=${rtp.toFixed(0)}% (期望 ${exp.label})`);
    }
  }
  // Mode 5 should be > mode 2
  const m2 = modes["2"]?.rtp_pct;
  const m5 = modes["5"]?.rtp_pct;
  if (m2 != null && m5 != null && m5 <= m2) {
    issues.push(`mode 5 ≤ mode 2 (m2=${m2.toFixed(0)}%, m5=${m5.toFixed(0)}%)`);
  }
  return issues;
}


function _computeFleetHeadlines() {
  const sm = (state.machinesSummary || {}).machines || {};
  const machines = state.machines || [];
  const missingModes = [];  // machines with missing modes
  const badRtpByMode = { 1: [], 2: [], 5: [], 7: [] };
  const mode5NotExtreme = []; // mode 5 <= mode 2

  for (const m of machines) {
    const machine = m.machine;
    const modes = sm[machine] || {};
    const expected = m.modes || [1, 2, 5, 7];
    const actual = Object.keys(modes).map(Number);
    const missing = expected.filter((x) => !actual.includes(x));
    if (missing.length && m.available !== false) {
      missingModes.push({ machine, missing });
    }
    // Per-mode RTP expectation checks.
    for (const modeStr of Object.keys(modes)) {
      const mode = Number(modeStr);
      const d = modes[modeStr];
      const rtp = d.rtp_pct;
      if (rtp == null) continue;
      const exp = _MODE_RTP_EXPECT[mode];
      if (exp && (rtp < exp.min || rtp > exp.max)) {
        badRtpByMode[mode].push({ machine, rtp });
      }
    }
    // Mode 5 should be higher than mode 2.
    const m2 = modes["2"]?.rtp_pct;
    const m5 = modes["5"]?.rtp_pct;
    if (m2 != null && m5 != null && m5 <= m2) {
      mode5NotExtreme.push({ machine, m2, m5 });
    }
  }

  const headlines = [];

  if (missingModes.length) {
    const top = missingModes.slice(0, 5);
    headlines.push({
      level: "warn",
      text: `${missingModes.length} 台机台 mode 数据不全`,
      detail: top.map((x) => `${x.machine}: 缺 mode ${x.missing.join(",")}`).join(", "),
    });
  }
  for (const mode of [1, 7, 2, 5]) {
    const bad = badRtpByMode[mode];
    if (!bad.length) continue;
    const top = bad.slice(0, 5);
    const exp = _MODE_RTP_EXPECT[mode];
    headlines.push({
      level: "warn",
      text: `${bad.length} 台机台 mode ${mode} RTP 异常（期望 ${exp.label}）`,
      detail: top.map((x) => `${x.machine}: ${x.rtp.toFixed(0)}%`).join(", "),
    });
  }
  if (mode5NotExtreme.length) {
    const top = mode5NotExtreme.slice(0, 5);
    headlines.push({
      level: "warn",
      text: `${mode5NotExtreme.length} 台机台 mode 5 ≤ mode 2（应更极端）`,
      detail: top.map((x) => `${x.machine}: m2=${x.m2.toFixed(0)}% m5=${x.m5.toFixed(0)}%`).join(", "),
    });
  }

  return headlines;
}

function renderFleetOverview() {
  const el = byId("fleetStats");
  if (!el) return;
  const machines = state.machines || [];
  const total = machines.length;
  const withReports = machines.filter((m) => m.report_count > 0).length;
  const categories = {};
  machines.forEach((m) => { const c = m.category || "Other"; categories[c] = (categories[c] || 0) + 1; });

  const catBadges = Object.entries(categories)
    .sort((a, b) => b[1] - a[1])
    .map(([c, n]) => `<span class="fleet-cat-badge" style="background:${CATEGORY_COLORS[c] || '#9ca3af'}">${c} ${n}</span>`)
    .join(" ");

  const headlines = _computeFleetHeadlines();
  const headlineHtml = headlines.length
    ? headlines.map((h) => `<div class="fleet-headline fleet-headline-${h.level}"><strong>⚠ ${h.text}</strong> <span class="muted">— ${h.detail}</span></div>`).join("")
    : `<div class="fleet-headline fleet-headline-ok">✓ ${fmt("fleetAllHealthy")}</div>`;

  el.innerHTML = `
    <div class="fleet-summary-row">
      <strong>${total}</strong> ${fmt("fleetTotal")} · <strong>${withReports}</strong> ${fmt("fleetWithReports")}
      <a href="/api/fleet/export-csv" class="small-btn" download="fleet_summary.csv" style="margin-left:8px">${fmt("btnExportCsv")}</a>
    </div>
    <div class="fleet-categories">${catBadges}</div>
    <div class="fleet-headlines">${headlineHtml}</div>`;
}

// ── Batch Run UI ──────────────────────────────────────────────────

// ── Inline Sampling Panel ─────────────────────────────────────────

function updateSampleHint() {
  const countEl = byId("sampleSelectedCount");
  const btn = byId("sampleStartBtn");
  const hint = byId("sampleHint");
  const mode = parseInt(byId("sampleMode")?.value || "2");
  const ciSel = byId("sampleCi");
  const n = state.runFilterMachines.size;

  if (countEl) countEl.textContent = n ? `已选 ${n} 台` : "未选机台";

  // Mode 2/5 force fuzzy.
  if (ciSel) {
    const isLucky = mode === 2 || mode === 5;
    if (isLucky) {
      ciSel.value = "0";
      ciSel.disabled = true;
    } else {
      ciSel.disabled = false;
    }
  }

  // Hint text based on mode + whether there's a tuned param set for
  // the first selected machine + current mode.
  if (hint) {
    let lines = [];
    if (mode === 2 || mode === 5) {
      lines.push(`Mode ${mode} 为幸运模式（RTP 高波动），仅支持 Fuzzy 采样，固定 20 chunks`);
    } else {
      const ci = parseFloat(byId("sampleCi")?.value || "0.5");
      if (ci === 0) lines.push(`Fuzzy 模式，固定 chunks，约 1M spins`);
      else lines.push(`目标 ±${ci}pp 精度，上限 10M spins`);
    }
    // Show whether the upcoming 开始采样 will use tuned params (from
    // a previous 调参 click on the first selected machine + this mode)
    // or the hardcoded preset (robot_count=20, batch_concurrency=2).
    if (n > 0) {
      const firstMachine = [...state.runFilterMachines][0];
      const tuned = state.tunedSamplingParams[`${firstMachine}|${mode}`];
      if (tuned) {
        lines.push(
          `⚙ 已调参 (${firstMachine} m${mode}): robot_count=${tuned.robot_count}, ` +
          `batch_concurrency=${tuned.batch_concurrency} · success=${fRate(tuned.success_rate, 1)}`
        );
      } else {
        lines.push(`未调参，将用预设 robot_count=20, batch_concurrency=2 (可先点 ⚙ 调参)`);
      }
    }
    hint.textContent = lines.join(" · ");
  }

  if (btn) btn.disabled = n === 0 || !!state.activeBatchId;
}

async function startSampling() {
  // Double-click guard: `await apiPost` below has non-trivial latency
  // (backend runs start_batch synchronously: per-item rawdata checks
  // can take 100s of ms each for 253 machines). Without this the user
  // impatient-clicks again during the await, the second POST creates
  // a second batch that hits the per-key lock and immediately fails.
  // Disable IMMEDIATELY + hide to make it unclickable; re-enable in
  // the finally / on POST success the Cancel button replaces it.
  const btn = byId("sampleStartBtn");
  if (btn && btn.disabled) return;  // already clicked, ignore
  if (btn) btn.disabled = true;
  // Clear frozen-log flag so renderSamplingProgress can render again
  // once the new batch starts emitting events. The previous batch's
  // log is about to be replaced wholesale, which is expected now that
  // the user has opted in by clicking 开始采样.
  state.batchJustCompleted = false;
  // Reset client-side observability state for this new batch.
  state.clientEvents = [];
  state.itemStartTimes = {};
  state.batchStartedAt = Date.now();
  const selected = [...state.runFilterMachines];
  if (!selected.length) { if (btn) btn.disabled = false; return; }
  const mode = parseInt(byId("sampleMode")?.value || "2");
  let ci = parseFloat(byId("sampleCi")?.value || "0.5");
  if (mode === 2 || mode === 5) ci = 0;

  // Surface the panel + inject "click" event IMMEDIATELY — before the
  // POST latency. Without this, the first 1-3 seconds after clicking
  // show an unchanged UI and feel like the button did nothing.
  const panel = byId("sampleProgressPanel");
  if (panel) panel.classList.remove("hidden");
  pushClientEvent("click", { count: selected.length, mode, ci });
  // Placeholder render so the panel isn't empty during the POST wait.
  renderSamplingProgress({
    status: "submitting", completed: 0, total: selected.length,
    items: [], events: [],
  });

  // Build items with smart chunk size per machine (category-based initial heuristic).
  const items = selected.map((machine) => {
    const m = state.machines.find((x) => x.machine === machine);
    const cat = m?.category || "";
    let chunk_spin_times = 1000;
    if (cat === "Collect") chunk_spin_times = 5000;
    else if (cat === "Lock" || cat === "ReSpin" || cat === "FreeSpin") chunk_spin_times = 2000;
    return { machine, mode, chunk_spin_times };
  });

  // Pick up autotune result for the first selected machine+mode if the
  // operator ran 调参 beforehand. Otherwise fall back to the hardcoded
  // preset (robot=20 / conc=2). Tuned values apply to the whole batch.
  const tunedKey = `${selected[0]}|${mode}`;
  const tuned = state.tunedSamplingParams[tunedKey];
  const chunk_robot_count = tuned ? tuned.robot_count : 20;
  const batch_concurrency = tuned ? tuned.batch_concurrency : 2;

  // Max chunks based on mode + CI. Uses the actual robot count so
  // tuning up to e.g. robot=24 doesn't overshoot the 10M-spins cap.
  let max_chunks;
  if (ci === 0) max_chunks = 20;  // fuzzy
  else {
    const avgChunk = items.reduce((s, i) => s + i.chunk_spin_times, 0) / items.length;
    max_chunks = Math.floor(10_000_000 / (chunk_robot_count * avgChunk));
  }

  const payload = {
    items,
    concurrency: batch_concurrency,
    chunk_spin_times: 1000,  // overridden per-item below (not yet supported, needs backend update)
    chunk_robot_count,
    max_chunks,
    target_halfwidth_pp: ci,
    batch_concurrency,
    timeout: 300,
    auto_cleanup_cache: true,
  };

  pushClientEvent("submit", {});
  try {
    const result = await apiPost("/api/batch-run", payload);
    state.activeBatchId = result.batch_id;
    localStorage.setItem("slot_console_activeBatchId", result.batch_id);
    pushClientEvent("batch_created", { batchId: result.batch_id });
    updateSampleHint();
    byId("sampleCancelBtn").classList.remove("hidden");
    byId("sampleStartBtn").classList.add("hidden");
    pollSampling();
  } catch (e) {
    pushClientEvent("submit_failed", { error: String(e.message || e) });
    // Keep the panel open so the client-side error event is readable.
    alert(String(e.message || e));
    if (btn) btn.disabled = false;  // POST failed, let user retry
  }
}

/**
 * Append a synthetic lifecycle event to state.clientEvents and
 * trigger a re-render. These cover the observability gap between the
 * user's click and the first backend chunk_progress event.
 */
function pushClientEvent(kind, data) {
  const ev = PURE.buildClientEvent(kind, data);
  state.clientEvents.push(ev);
  // Hard cap so a pathological re-click loop can't grow this unbounded.
  if (state.clientEvents.length > 100) {
    state.clientEvents = state.clientEvents.slice(-100);
  }
  // Eagerly re-render so the new event is visible without waiting for
  // the next poll tick. Uses a minimal synthetic `data` shape when no
  // batch data is available yet.
  if (!state.batchJustCompleted) {
    const stub = {
      status: "submitting", completed: 0,
      total: state.runFilterMachines ? state.runFilterMachines.size : 0,
      items: [], events: [],
    };
    renderSamplingProgress(stub);
  }
}

function pollSampling() {
  if (!state.activeBatchId) return;
  const panel = byId("sampleProgressPanel");
  if (panel) panel.classList.remove("hidden");
  pushClientEvent("polling_started", {});

  // Fast polling for the first 3 seconds (10 ticks × 300ms) so the
  // log feels responsive during batch creation + analyzer spawn. After
  // that, back off to 1s for the steady-state chunk loop (chunks take
  // 30-60s each; polling faster than 1s is wasted bandwidth).
  let tickCount = 0;
  const poll = async () => {
    if (!state.activeBatchId) return;
    try {
      const data = await apiGet(`/api/batch-run/${state.activeBatchId}`);
      renderSamplingProgress(data);
      refreshDiskSpace();
      if (data.status === "completed") {
        // Mark the log frozen so the user can read final state without
        // the panel re-rendering under them. Also stamp a completion
        // banner at the top so it's obvious why nothing's moving.
        const meta = byId("sampleProgressMeta");
        if (meta) {
          const failedChunks = (data.items || []).reduce((sum, it) =>
            sum + (it.chunk_events || []).filter(e => e.event === "chunk_failed").length, 0);
          const failedMachines = (data.items || []).filter(i => i.status === "failed").length;
          // Partial = completed but didn't hit the CI target
          // (upstream_unstable / max_chunks_reached / disk_low). Runs
          // with valid data but the goal not met. Banner stays ✓ only
          // when every completed item actually reached its target.
          const partialMachines = (data.items || []).filter(
            i => i.status === "completed" && i.ci_target_met === false
          ).length;
          const note = failedMachines > 0 ? ` · 机台失败 ${failedMachines}` : "";
          const partialNote = partialMachines > 0 ? ` · 未达 CI ${partialMachines}` : "";
          const fn = failedChunks > 0 ? ` · 总失败 chunk=${failedChunks}` : "";
          const bannerIcon = (failedMachines > 0 || partialMachines > 0) ? "⚠" : "✓";
          const totalElapsed = state.batchStartedAt
            ? ` · 总耗时 ${PURE.computeElapsedSeconds(state.batchStartedAt).toFixed(1)}s`
            : "";
          meta.textContent = `${bannerIcon} 批次已结束 · ${data.completed}/${data.total}${note}${partialNote}${fn}${totalElapsed} · 日志保留，点击开始采样可覆盖`;
        }
        state.batchJustCompleted = true;  // prevent further re-render
        state.activeBatchId = null;
        localStorage.removeItem("slot_console_activeBatchId");
        byId("sampleCancelBtn").classList.add("hidden");
        const startBtnEl = byId("sampleStartBtn");
        if (startBtnEl) {
          startBtnEl.classList.remove("hidden");
          startBtnEl.disabled = false;
        }
        updateSampleHint();
        // Refresh catalog with new reports.
        const [m, mSummary] = await Promise.all([
          apiGet("/api/machines"), apiGet("/api/machines/summary").catch(() => null),
        ]);
        state.machines = m.machines || [];
        state.machinesSummary = mSummary;
        renderCatalogFeatureChips();
        renderMachineCatalog();
        renderFleetOverview();
        await refreshRunList(false);
        return;
      }
    } catch (_) { /* ignore transient errors */ }
    tickCount += 1;
    const interval = tickCount < 10 ? 300 : 1000;
    setTimeout(poll, interval);
  };
  poll();
}

function renderSamplingProgress(data) {
  const meta = byId("sampleProgressMeta");
  const log = byId("sampleProgressLog");
  if (!meta || !log) return;
  // Freeze the log once a batch completes so the user can read the
  // final state (especially error chunks) without it being rewritten
  // by a late poll tick or a stale event fetch. Cleared when the user
  // clicks 开始采样 to start a fresh batch.
  if (state.batchJustCompleted) return;

  // Capture per-item start times for the "t+Ns" elapsed ticker. Once
  // an item first appears as running with a run_id, anchor the clock
  // so subsequent polls can show elapsed seconds. This matters during
  // the analyzer's slow initial fetch (30-60s before first
  // chunk_progress emits) — without the ticker the UI looks frozen.
  for (const it of data.items || []) {
    if (it.status === "running" && it.run_id && !state.itemStartTimes[it.run_id]) {
      state.itemStartTimes[it.run_id] = Date.now();
    }
  }

  const running = (data.items || []).filter((i) => i.status === "running").length;
  const batchElapsed = state.batchStartedAt
    ? ` · t+${PURE.computeElapsedSeconds(state.batchStartedAt).toFixed(1)}s`
    : "";
  meta.textContent = `${data.completed || 0} / ${data.total || 0} 完成 · ${running} 运行中${batchElapsed}`;

  // Per-machine compact status rows at top. Chunk events are NOT
  // inlined here anymore — they flow into the unified timeline below
  // (via PURE.mergeTimeline) alongside batch-level + client-synthetic
  // events. The two-section split (機台状態 vs 批次時間線) gives the
  // operator at-a-glance state + a narrative stream.
  const statusIcon = { pending: "⏳", running: "▶", completed: "✓", failed: "✗", cancelled: "⏸" };
  const statusRows = (data.items || []).map((it) => {
    const isPartial = it.status === "completed" && it.ci_target_met === false;
    const icon = isPartial ? "⚠" : (statusIcon[it.status] || "?");
    const rowCls = isPartial ? "sample-warn" : `sample-${it.status}`;
    const chunk = it.chunk_spin_times ? ` (chunk=${it.chunk_spin_times})` : "";
    const err = it.error ? ` — ${it.error.slice(0, 60)}` : "";
    const stopTail = isPartial && it.stop_reason ? ` · ${it.stop_reason.slice(0, 120)}` : "";
    let progress = "";
    if (it.status === "running" && it.progress) {
      const p = it.progress;
      const rtp = p.current_rtp_pct != null ? p.current_rtp_pct.toFixed(2) + "%" : "—";
      const hw = p.halfwidth_pp != null ? "±" + Number(p.halfwidth_pp).toFixed(3) + "pp" : "";
      progress = ` · chunk ${p.chunks_done} · ${(p.total_spins || 0).toLocaleString()} spins · RTP=${rtp} ${hw}`;
    } else if (it.status === "running") {
      progress = " · 启动中…";
    }
    // Elapsed ticker (pure helper). Shows tenths of a second so the
    // user sees the clock moving during slow startup. Only on items
    // that already acquired a run_id and are currently running.
    let elapsed = "";
    if (it.status === "running" && it.run_id && state.itemStartTimes[it.run_id]) {
      const s = PURE.computeElapsedSeconds(state.itemStartTimes[it.run_id]);
      if (s != null) elapsed = ` · t+${s.toFixed(1)}s`;
    }
    // In-flight per-chunk block: rows for each chunk that's been
    // submitted but hasn't returned yet, with a live elapsed ticker.
    // A batch of 4 concurrent chunks where one is mid-retry at 45s
    // used to show nothing until the slowest returned; now the
    // operator sees "chunk 38/39/40/41 · 等待中 · t+24.3s" rolling.
    let inflightBlock = "";
    if (it.status === "running") {
      const inflight = PURE.computeInflightChunks(it);
      if (inflight.length) {
        const rows = inflight.map((c) => {
          const e = PURE.computeElapsedSeconds(c.startedMs);
          const et = e != null ? ` · t+${e.toFixed(1)}s` : "";
          return `<div class="sample-chunk-row sample-info">  ⇅ chunk ${c.chunk_index} · 等待中${et}</div>`;
        }).join("");
        inflightBlock = rows;
      }
    }
    return `<div class="sample-log-item ${rowCls}">${icon} ${it.machine} m${it.mode}${chunk}${progress}${elapsed}${err}${stopTail}</div>${inflightBlock}`;
  }).join("");

  // Unified timeline: batch events + per-item chunk events + client
  // lifecycle events, sorted chronologically via PURE.mergeTimeline.
  // The pure helper also enforces the "criticals never pruned, progress
  // capped at 8 per machine" retention rule, so a 31-chunk run doesn't
  // drown out a warning from a sibling machine.
  const timeline = PURE.mergeTimeline(data, state.clientEvents);
  const levelIcon = { info: "ℹ", warn: "⚠", ok: "✓", error: "✗", danger: "⛔" };
  const levelClass = {
    info: "sample-info", warn: "sample-warn", ok: "sample-completed",
    error: "sample-failed", danger: "sample-danger",
  };
  const timelineRows = timeline.map((row) => {
    const icon = levelIcon[row.level] || "·";
    const cls = levelClass[row.level] || "";
    const ts = (row.ts || "").slice(11, 19);
    // Source tag distinguishes [M273] / [batch] / [ui] so the eye
    // can scan for a specific stream.
    const srcTag = row.source ? `[${row.source}] ` : "";
    return `<div class="sample-log-item ${cls}">${ts} ${icon} ${srcTag}${row.text}</div>`;
  }).join("");

  const sectionTitle = `批次时间线 (${timeline.length} 条)`;

  // Preserve scroll position if the user has scrolled up to read
  // earlier events. The previous unconditional scrollTop = scrollHeight
  // yanked them back to the bottom on every poll tick, which felt
  // like the log "isn't updating" (actually it updated, just scrolled
  // past whatever they were reading).
  const wasNearBottom =
    (log.scrollHeight - log.scrollTop - log.clientHeight) < 40;
  log.innerHTML = `<div class="sample-log-section-title">机台状态</div>${statusRows}
    <div class="sample-log-section-title">${sectionTitle}</div>${timelineRows}`;
  if (wasNearBottom) log.scrollTop = log.scrollHeight;
}

async function refreshDiskSpace() {
  const bar = byId("diskSpaceBar");
  if (!bar) return;
  try {
    const d = await apiGet("/api/disk-space");
    const free = d.free_gb || 0;
    const total = d.total_gb || 0;
    let cls = "";
    if (free < 2) cls = "danger";
    else if (free < 10) cls = "warn";
    bar.className = `disk-space-bar ${cls}`;
    bar.textContent = `磁盘可用 ${free}GB / ${total}GB`;
  } catch (_) { /* ignore */ }
}

async function cancelSampling() {
  if (!state.activeBatchId) return;
  const btn = byId("sampleCancelBtn");
  if (btn) { btn.disabled = true; btn.textContent = "停止中…"; }
  try {
    await apiPost(`/api/batch-run/${state.activeBatchId}/cancel`);
  } catch (e) {
    alert(String(e.message || e));
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "停止"; }
  }
}

// Called on page load. If the server reports an active batch OR
// localStorage remembers one that the server still knows, adopt it
// so the UI reflects server state after a refresh. Prevents the
// scenario where user clicks 开始采样, refreshes, then clicks again
// and gets "another batch is sampling" because the old one is still
// running in the background.
async function _recoverActiveSampling() {
  try {
    const status = await apiGet("/api/sampling-status");
    const active = (status.active_batches || []);
    // Prefer localStorage's batch_id if the server confirms it's still
    // active; otherwise adopt whichever active batch the server reports.
    const persisted = localStorage.getItem("slot_console_activeBatchId");
    let adopt = null;
    if (persisted && active.some((b) => b.batch_id === persisted)) {
      adopt = persisted;
    } else if (active.length > 0) {
      adopt = active[0].batch_id;
      localStorage.setItem("slot_console_activeBatchId", adopt);
    } else {
      // Server says no active batch; clear stale persisted id.
      localStorage.removeItem("slot_console_activeBatchId");
    }
    if (adopt) {
      state.activeBatchId = adopt;
      const startBtnEl = byId("sampleStartBtn");
      const cancelBtnEl = byId("sampleCancelBtn");
      if (startBtnEl) startBtnEl.classList.add("hidden");
      if (cancelBtnEl) cancelBtnEl.classList.remove("hidden");
      pollSampling();
    }
  } catch {
    // Endpoint may be offline during tests or boot race; silent.
  }
}

// ── Server Management ─────────────────────────────────────────────

async function refreshServers() {
  try {
    const data = await apiGet("/api/servers");
    state.servers = data.servers || [];
    state.defaultServer = data.default_server || "";
    fillServerSelector();
    renderServerTable();
    fillCompareSelectors();
  } catch (_) { /* ignore */ }
}

function fillServerSelector() {
  const sel = byId("serverSelect");
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = "";
  (state.servers || []).forEach((s) => {
    if (!s.active && !s.endpoint) return;
    const opt = new Option(`${s.name} (${s.id})`, s.id);
    sel.appendChild(opt);
  });
  if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
  else if (state.defaultServer) sel.value = state.defaultServer;
}

function renderServerTable() {
  const tbody = byId("serverTableBody");
  if (!tbody) return;
  const servers = state.servers || [];
  if (!servers.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted">${fmt("noServers")}</td></tr>`;
    return;
  }
  tbody.innerHTML = servers.map((s) => {
    const statusBadge = s.active
      ? `<span class="srv-active">${fmt("serverActive")}</span>`
      : `<span class="srv-inactive">${fmt("serverInactive")}</span>`;
    const epDisplay = s.endpoint
      ? `<code class="srv-endpoint">${s.endpoint}</code>`
      : `<span class="muted">${fmt("serverNoEndpoint")}</span>`;
    return (
      `<tr data-server-id="${s.id}">` +
      `<td><strong>${s.id}</strong></td>` +
      `<td>${s.name}</td>` +
      `<td>${epDisplay}</td>` +
      `<td>${statusBadge}</td>` +
      `<td><button class="srv-scan-btn small-btn">${fmt("btnScan")}</button> <button class="srv-check-btn small-btn">${fmt("btnCheckChanges")}</button> <button class="srv-edit-btn small-btn">${fmt("btnEdit")}</button> <button class="srv-delete-btn small-btn danger-btn">${fmt("btnDelete")}</button></td>` +
      `</tr>`
    );
  }).join("");

  // Wire up scan/check/edit/delete buttons.
  tbody.querySelectorAll(".srv-check-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest("tr");
      const sid = row.dataset.serverId;
      btn.disabled = true;
      btn.textContent = "...";
      try {
        const result = await apiPost(`/api/servers/${sid}/check-changes`);
        if (result.first_scan) {
          btn.textContent = fmt("btnCheckChanges");
          alert(fmt("checkFirstScan", { n: result.machine_count }));
        } else if (result.diff_count === 0) {
          btn.textContent = fmt("btnCheckChanges");
          alert(fmt("checkNoChanges"));
        } else {
          btn.textContent = `${result.diff_count} changes`;
          const configChanged = (result.config_changed || []).join(", ");
          const codeChanged = (result.code_changed || []).join(", ");
          let msg = fmt("checkChangesFound", { n: result.diff_count });
          if (configChanged) msg += "\n\nConfig: " + configChanged;
          if (codeChanged) msg += "\nCode: " + codeChanged;
          alert(msg);
        }
      } catch (e) {
        btn.textContent = fmt("btnCheckChanges");
        alert(String(e.message || e));
      } finally {
        btn.disabled = false;
      }
    });
  });
  tbody.querySelectorAll(".srv-scan-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest("tr");
      const sid = row.dataset.serverId;
      btn.disabled = true;
      btn.textContent = "...";
      try {
        const result = await apiPost(`/api/servers/${sid}/scan`);
        btn.textContent = `${result.machine_count} machines`;
        fillCompareSelectors();
      } catch (e) {
        btn.textContent = fmt("btnScan");
        alert(String(e.message || e));
      } finally {
        btn.disabled = false;
      }
    });
  });
  tbody.querySelectorAll(".srv-edit-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = btn.closest("tr");
      const sid = row.dataset.serverId;
      const s = servers.find((x) => x.id === sid);
      if (!s) return;
      const newName = prompt(fmt("serverPromptName"), s.name);
      if (newName === null) return;
      const newEndpoint = prompt(fmt("serverPromptEndpoint"), s.endpoint);
      if (newEndpoint === null) return;
      const newActive = confirm(fmt("serverPromptActive"));
      apiPut(`/api/servers/${sid}`, { name: newName, endpoint: newEndpoint, active: newActive })
        .then(() => refreshServers())
        .catch((e) => alert(String(e.message || e)));
    });
  });
  tbody.querySelectorAll(".srv-delete-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = btn.closest("tr");
      const sid = row.dataset.serverId;
      if (!confirm(fmt("serverConfirmDelete", { id: sid }))) return;
      apiDelete(`/api/servers/${sid}`)
        .then(() => refreshServers())
        .catch((e) => alert(String(e.message || e)));
    });
  });
}

async function addServer() {
  const id = byId("newServerId").value.trim();
  const name = byId("newServerName").value.trim();
  const endpoint = byId("newServerEndpoint").value.trim();
  if (!id || !name) return alert(fmt("serverRequiredFields"));
  try {
    await apiPost("/api/servers", { id, name, endpoint, active: !!endpoint });
    byId("newServerId").value = "";
    byId("newServerName").value = "";
    byId("newServerEndpoint").value = "";
    await refreshServers();
  } catch (e) {
    alert(String(e.message || e));
  }
}

// ── Version History + Report Comparison ───────────────────────────

async function showVersionHistory(machine) {
  const panel = byId("versionHistoryPanel");
  if (!panel) return;
  state.versionHistoryMachine = machine;
  state.versionHistoryMode = null;
  state.compareSelected = new Set();
  byId("versionHistoryTitle").textContent = `${fmt("panelVersionHistory")} — ${machine}`;
  panel.classList.remove("hidden");

  // Build mode tabs from machine config.
  const mConfig = state.machines.find((m) => m.machine === machine);
  const modes = (mConfig && mConfig.modes) || [1, 2, 5, 7];
  const tabsEl = byId("versionModeTabs");
  tabsEl.innerHTML = modes.map((m) => `<button class="mode-tab" data-mode="${m}">Mode ${m}</button>`).join("");
  tabsEl.querySelectorAll(".mode-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      tabsEl.querySelectorAll(".mode-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      loadVersionsForMode(machine, Number(btn.dataset.mode));
    });
  });
  // Auto-select first mode with reports, fallback to mode 2 or first.
  const sm = ((state.machinesSummary || {}).machines || {})[machine] || {};
  const bestMode = modes.find((m) => sm[String(m)]) || (modes.includes(2) ? 2 : modes[0]);
  const bestBtn = tabsEl.querySelector(`[data-mode="${bestMode}"]`);
  if (bestBtn) { bestBtn.classList.add("active"); loadVersionsForMode(machine, bestMode); }
}

async function loadVersionsForMode(machine, mode) {
  state.versionHistoryMode = mode;
  state.compareSelected = new Set();
  updateCompareBtn();
  const tbody = byId("versionTableBody");
  tbody.innerHTML = `<tr><td colspan="6" class="muted">Loading...</td></tr>`;

  try {
    const [data, validation] = await Promise.all([
      apiGet(`/api/reports/${machine}/${mode}`),
      apiGet(`/api/report-validate/${machine}`).catch(() => null),
    ]);
    const versions = data.versions || [];
    if (!versions.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="muted">${fmt("noVersions")}</td></tr>`;
      return;
    }
    // Map version → md5_status.
    const md5Map = {};
    if (validation && validation.reports) {
      validation.reports.filter((r) => r.mode === mode).forEach((r) => {
        md5Map[r.version] = r.md5_status;
      });
    }
    // Sort newest first.
    versions.sort((a, b) => (b.report_version || "").localeCompare(a.report_version || ""));
    tbody.innerHTML = versions.map((v) => {
      const rv = v.report_version || "?";
      const rtp = v.achieved_rtp_pct != null ? v.achieved_rtp_pct.toFixed(2) + "%" : "—";
      const ci = v.achieved_halfwidth_pp != null ? "\u00b1" + v.achieved_halfwidth_pp.toFixed(2) : "—";
      const spins = v.total_spins != null ? Number(v.total_spins).toLocaleString() : "—";
      const quality = v.quality_label || "—";
      const md5 = md5Map[rv] || "unknown";
      const badge = md5 === "match" ? '<span class="md5-match" title="MD5 匹配">✓</span>'
        : md5 === "outdated" ? '<span class="md5-mismatch" title="机台版本已变更">⚠ 过期</span>'
        : md5 === "untagged" ? '<span class="muted" title="无 MD5 标签">—</span>'
        : '';
      return (
        `<tr data-version="${rv}">` +
        `<td><input type="checkbox" class="compare-check" value="${rv}"></td>` +
        `<td class="version-id">${rv} ${badge}</td>` +
        `<td>${rtp}</td><td>${ci}</td><td>${spins}</td><td>${quality}</td>` +
        `</tr>`
      );
    }).join("");

    // Wire checkboxes.
    tbody.querySelectorAll(".compare-check").forEach((cb) => {
      cb.addEventListener("change", () => {
        if (cb.checked) state.compareSelected.add(cb.value);
        else state.compareSelected.delete(cb.value);
        updateCompareBtn();
      });
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="muted">${e.message || e}</td></tr>`;
  }
}

function updateCompareBtn() {
  const btn = byId("compareBtn");
  if (!btn) return;
  const n = (state.compareSelected || new Set()).size;
  btn.disabled = n !== 2;
  btn.textContent = fmt("btnCompare") + ` (${n}/2)`;
}

async function compareReports() {
  const selected = [...(state.compareSelected || [])];
  if (selected.length !== 2) return;
  const machine = state.versionHistoryMachine;
  const mode = state.versionHistoryMode;
  const panel = byId("reportComparisonPanel");
  const body = byId("comparisonBody");
  panel.classList.remove("hidden");
  body.innerHTML = `<div class="muted">Loading...</div>`;

  try {
    const [a, b] = await Promise.all([
      apiGet(`/api/reports/${machine}/${mode}/${selected[0]}`),
      apiGet(`/api/reports/${machine}/${mode}/${selected[1]}`),
    ]);
    renderComparison(a, b, selected[0], selected[1]);
  } catch (e) {
    body.innerHTML = `<div class="muted">${e.message || e}</div>`;
  }
}

function renderComparison(a, b, vA, vB) {
  const body = byId("comparisonBody");
  const sa = a.sampling || {};
  const sb = b.sampling || {};
  const ra = a.rtp || {};
  const rb = b.rtp || {};
  const pia = a.player_impact || {};
  const pib = b.player_impact || {};
  const hapa = pia.hit_and_payout || {};
  const hapb = pib.hit_and_payout || {};
  const ga_a = (a.guideline_assessment || {}).classification || {};
  const ga_b = (b.guideline_assessment || {}).classification || {};

  const rows = [
    ["RTP %", fmtNum(ra.point_pct, 4), fmtNum(rb.point_pct, 4), diffPp(ra.point_pct, rb.point_pct)],
    ["CI \u00b1pp", fmtNum(sa.achieved_halfwidth_pp, 2), fmtNum(sb.achieved_halfwidth_pp, 2), ""],
    ["Total Spins", fmtInt(sa.total_spins), fmtInt(sb.total_spins), ""],
    ["Paid / Bonus", `${fmtInt(sa.paid_spins)} / ${fmtInt(sa.bonus_spins)}`, `${fmtInt(sb.paid_spins)} / ${fmtInt(sb.bonus_spins)}`, ""],
    ["Hit Rate", fmtPct(hapa.hit_rate), fmtPct(hapb.hit_rate), ""],
    ["Zero Win Rate", fmtPct(hapa.zero_win_rate), fmtPct(hapb.zero_win_rate), ""],
    ["Big Win x10 Rate", fmtPct(hapa.big_win_x10_rate), fmtPct(hapb.big_win_x10_rate), ""],
    ["Volatility", ga_a.volatility_class || "—", ga_b.volatility_class || "—", ""],
    ["Archetype", ga_a.experience_archetype || "—", ga_b.experience_archetype || "—", ""],
  ];

  body.innerHTML = `
    <table class="drilldown-table comparison-table">
      <thead><tr><th>${fmt("thMetric")}</th><th>${vA.slice(3, 18)}</th><th>${vB.slice(3, 18)}</th><th>\u0394</th></tr></thead>
      <tbody>${rows.map((r) => {
        const delta = r[3];
        const cls = delta && delta.startsWith("+") ? "delta-pos" : delta && delta.startsWith("-") ? "delta-neg" : "";
        return `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td class="${cls}">${delta}</td></tr>`;
      }).join("")}</tbody>
    </table>`;
}

function fmtNum(v, d) { return v != null ? Number(v).toFixed(d) : "—"; }
function fmtInt(v) { return v != null ? Number(v).toLocaleString() : "—"; }
function fmtPct(v) { return v != null ? (Number(v) * 100).toFixed(2) + "%" : "—"; }
function diffPp(a, b) {
  if (a == null || b == null) return "";
  const d = Number(a) - Number(b);
  const sign = d >= 0 ? "+" : "";
  return `${sign}${d.toFixed(2)}pp`;
}

function fillCompareSelectors() {
  const selA = byId("compareServerA");
  const selB = byId("compareServerB");
  if (!selA || !selB) return;
  const servers = state.servers || [];
  [selA, selB].forEach((sel) => {
    const prev = sel.value;
    sel.innerHTML = "";
    servers.forEach((s) => sel.appendChild(new Option(`${s.name} (${s.id})`, s.id)));
    if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
  });
  // Default: A = first, B = second (if available).
  if (selA.options.length >= 2 && selA.value === selB.value) {
    selB.selectedIndex = 1;
  }
}

async function compareServers() {
  const a = byId("compareServerA")?.value;
  const b = byId("compareServerB")?.value;
  const resultDiv = byId("serverCompareResult");
  if (!a || !b || !resultDiv) return;
  if (a === b) { resultDiv.innerHTML = `<div class="muted">${fmt("compareSelectDifferent")}</div>`; return; }

  resultDiv.innerHTML = `<div class="muted">Loading...</div>`;
  try {
    const data = await apiGet(`/api/servers/compare?a=${a}&b=${b}`);
    if (!data.diffs || data.diffs.length === 0) {
      resultDiv.innerHTML = `<div class="compare-ok">${fmt("compareIdentical", {total: data.total_a})}</div>`;
      return;
    }
    const rows = data.diffs.map((d) => {
      let badge = "";
      if (d.status === "only_in_a") badge = `<span class="diff-badge diff-only-a">only in ${a}</span>`;
      else if (d.status === "only_in_b") badge = `<span class="diff-badge diff-only-b">only in ${b}</span>`;
      else {
        const parts = [];
        if (d.config_changed) parts.push("config");
        if (d.code_changed) parts.push("code");
        badge = `<span class="diff-badge diff-changed">${parts.join("+")} changed</span>`;
      }
      return `<div class="diff-item">${d.machine} ${badge}</div>`;
    }).join("");
    resultDiv.innerHTML = `<div class="compare-summary">${data.diff_count} ${fmt("compareDiffs")} (${a}: ${data.total_a} | ${b}: ${data.total_b})</div>${rows}`;
  } catch (e) {
    resultDiv.innerHTML = `<div class="muted">${e.message || e}</div>`;
  }
}

function renderRunFilterBanner() {
  const banner = byId("runFilterBanner");
  if (!banner) return;
  if (!state.runFilterMachines.size) {
    banner.innerHTML = "";
    banner.style.display = "none";
    return;
  }
  banner.style.display = "";
  const label = Array.from(state.runFilterMachines).join(" + ");
  banner.innerHTML =
    `<span class="filter-label">${fmt("runFilterActive", { machine: label })}</span>` +
    `<button type="button" class="clear-filter-btn">${fmt("btnClearFilter")}</button>`;
  banner.querySelector(".clear-filter-btn").addEventListener("click", () => {
    state.runFilterMachines.clear();
    renderMachineCatalog();
    renderRunHistory();
  });
}

function updateBatchBar() {
  const bar = byId("batchActionsBar");
  const n = state.selectedRuns.size;
  if (!bar) return;
  bar.style.display = n > 0 ? "" : "none";
  byId("batchCount").textContent = fmt("batchSelectedCount", { n });
}

// Format a number field that may be null/undefined (legacy rows persisted
// before the achieved_rtp_pct / achieved_halfwidth_pp migration) as an em
// dash. `precision` digits, trailing "%" or " pp" suffix optional.
function fMetricCell(value, precision, suffix) {
  if (value === null || value === undefined || value === "") return "\u2014";
  const n = Number(value);
  if (!Number.isFinite(n)) return "\u2014";
  return n.toFixed(precision) + (suffix || "");
}

function renderRunHistory() {
  renderRunFilterBanner();
  const body = byId("runListTable").querySelector("tbody");
  body.innerHTML = "";
  const filterSet = state.runFilterMachines;
  const rows = filterSet.size
    ? state.runs.filter((r) => filterSet.has(r.machine))
    : state.runs;
  if (!rows.length) {
    const msg = filterSet.size ? fmt("noRunsForMachine") : fmt("noRuns");
    body.innerHTML = `<tr><td colspan="12">${msg}</td></tr>`;
    updateBatchBar();
    return;
  }
  const current = state.currentVersions || { analyzer_version: "", machines: {} };
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    if (r.run_id === state.currentRunId) tr.classList.add("active-row");
    const rtpCell = fMetricCell(r.achieved_rtp_pct, 2, "%");
    const ciCell = fMetricCell(r.achieved_halfwidth_pp, 3, "pp");
    const spinsCell = r.total_spins != null
      ? Number(r.total_spins).toLocaleString()
      : "\u2014";
    const qualityCell = r.quality_label || "\u2014";
    const checked = state.selectedRuns.has(r.run_id) ? "checked" : "";
    const badges = PURE.versionBadges(r, current);
    const rawdataBadge = `<span class="ver-badge ver-${badges.rawdata.tier}" title="${badges.rawdata.tip.replace(/"/g, '&quot;')}">${fmt("badge" + badges.rawdata.tier.charAt(0).toUpperCase() + badges.rawdata.tier.slice(1))}</span>`;
    const analyzerBadge = `<span class="ver-badge ver-${badges.analyzer.tier}" title="${badges.analyzer.tip.replace(/"/g, '&quot;')}">${fmt("badge" + badges.analyzer.tier.charAt(0).toUpperCase() + badges.analyzer.tier.slice(1))}</span>`;
    tr.innerHTML =
      `<td class="td-check"><input type="checkbox" class="run-check" data-id="${r.run_id}" ${checked}></td>` +
      `<td>${r.run_id}</td>` +
      `<td>${statusText(r.status)}</td>` +
      `<td>${r.machine}</td>` +
      `<td>${r.mode}</td>` +
      `<td>${spinsCell}</td>` +
      `<td>${rtpCell}</td>` +
      `<td>${ciCell}</td>` +
      `<td>${qualityCell}</td>` +
      `<td>${rawdataBadge}</td>` +
      `<td>${analyzerBadge}</td>` +
      `<td class="action-cell">` +
      `<button class="load-run-btn" data-id="${r.run_id}">${fmt("btnLoadRun")}</button> ` +
      `<button class="delete-run-btn danger-btn" data-id="${r.run_id}">${fmt("btnDeleteRun")}</button>` +
      `</td>`;
    body.appendChild(tr);
  });

  // Checkbox handlers
  body.querySelectorAll(".run-check").forEach((cb) =>
    cb.addEventListener("change", () => {
      if (cb.checked) state.selectedRuns.add(cb.dataset.id);
      else state.selectedRuns.delete(cb.dataset.id);
      updateBatchBar();
      // Sync select-all checkbox
      const all = body.querySelectorAll(".run-check");
      const allChecked = Array.from(all).every((c) => c.checked);
      byId("selectAllRuns").checked = allChecked;
    })
  );

  // Load
  body.querySelectorAll(".load-run-btn").forEach((b) => {
    b.disabled = state.busyActions.size > 0;
    b.addEventListener("click", async () => {
      if (state.busyActions.size > 0) return;
      state.currentRunId = b.dataset.id;
      renderRunHistory();
      switchTab("debug");
      await refreshCurrentRun();
    });
  });

  // Delete (single)
  body.querySelectorAll(".delete-run-btn").forEach((b) => {
    b.disabled = state.busyActions.size > 0;
    b.addEventListener("click", async () => {
      if (state.busyActions.size > 0) return;
      const runId = b.dataset.id;
      if (!window.confirm(fmt("confirmDeleteRun", { runId }))) return;
      state.busyActions.add("delete_run");
      updateActionStates();
      try {
        await apiDelete(`/api/runs/${encodeURIComponent(runId)}`);
        if (state.currentRunId === runId) {
          state.currentRunId = "";
          state.currentRunStatus = "";
          clearSummaryPanels();
        }
        state.selectedRuns.delete(runId);
        await refreshRunList(false);
      } catch (err) {
        window.alert(fmt("runDeleteFailed", { error: String(err && err.message ? err.message : err) }));
      } finally {
        state.busyActions.delete("delete_run");
        updateActionStates();
      }
    });
  });

  // Rebuild button removed — report generation is now rawdata-driven
  // (machine detail panel → rawdata section → ⟳ 生成 Report). Produces
  // a new run row + report version rather than overwriting history.

  updateBatchBar();
}

function renderPayoutGroupDrilldown(summary) {
  // Reads payout_ids_top20 (from PayoutIdToWinAmount) -- the actual
  // payout-source breakdown. The legacy payout_groups_top20 surface
  // (always group 0 for M14/M272 mode 1/2) is no longer rendered;
  // PURE.formatPayoutGroupRows is kept exported for back-compat but
  // unused here. Falls back to the empty-row hint when the report
  // pre-dates the payout_ids_top20 commit.
  const tbody = byId("payoutGroupTable") && byId("payoutGroupTable").querySelector("tbody");
  if (!tbody) return;
  const rows = PURE.formatPayoutIdRows(summary);
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5">${fmt("payoutGroupEmpty")}</td></tr>`;
    return;
  }
  const maxRtp = Math.max(...rows.map((r) => r.rtp_contribution_pp), 0);
  tbody.innerHTML = rows
    .map((r) => {
      const bar = maxRtp > 0 ? Math.min(100, (r.rtp_contribution_pp / maxRtp) * 100) : 0;
      return (
        `<tr>` +
        `<td>${r.payout_id}</td>` +
        `<td>${fInt(r.hit_count)}</td>` +
        `<td>${r.hit_rate_pct.toFixed(3)}%</td>` +
        `<td>${r.avg_win_when_hit.toFixed(1)}</td>` +
        `<td class="bar-cell" style="--bar:${bar.toFixed(1)}%">${r.rtp_contribution_pp.toFixed(2)}</td>` +
        `</tr>`
      );
    })
    .join("");
}

function renderSymbolDrilldown(summary) {
  // Overall top-20
  const overallTbody = byId("symbolOverallTable") && byId("symbolOverallTable").querySelector("tbody");
  if (overallTbody) {
    const rows = PURE.formatSymbolRows(summary);
    if (!rows.length) {
      overallTbody.innerHTML = `<tr><td colspan="3">${fmt("symbolsEmpty")}</td></tr>`;
    } else {
      const maxCount = Math.max(...rows.map((r) => r.count), 0);
      overallTbody.innerHTML = rows
        .map((r) => {
          const bar = maxCount > 0 ? Math.min(100, (r.count / maxCount) * 100) : 0;
          return (
            `<tr>` +
            `<td>${r.symbol}</td>` +
            `<td class="bar-cell" style="--bar:${bar.toFixed(1)}%">${fInt(r.count)}</td>` +
            `<td>${r.rate_pct.toFixed(3)}%</td>` +
            `</tr>`
          );
        })
        .join("");
    }
  }
  // By-column matrix
  const matrixHost = byId("symbolByColMatrix");
  if (!matrixHost) return;
  const matrix = PURE.symbolByColMatrix(summary);
  if (!matrix.columnIds.length) {
    matrixHost.textContent = fmt("symbolsEmpty");
    return;
  }
  matrixHost.innerHTML = matrix.columnIds
    .map((col) => {
      const rows = matrix.rowsByCol[col] || [];
      const headerLabel = fmt("symbolColLabel", { idx: col });
      const max = rows.length ? Math.max(...rows.map((r) => r.count)) : 0;
      const body = rows
        .map((r) => {
          const bar = max > 0 ? Math.min(100, (r.count / max) * 100) : 0;
          return (
            `<tr>` +
            `<td>${r.symbol}</td>` +
            `<td class="bar-cell" style="--bar:${bar.toFixed(1)}%">${fInt(r.count)}</td>` +
            `<td>${r.rate_pct.toFixed(2)}%</td>` +
            `</tr>`
          );
        })
        .join("");
      return (
        `<div class="col-table">` +
        `<h4>${headerLabel}</h4>` +
        `<table class="drilldown-table"><tbody>${body}</tbody></table>` +
        `</div>`
      );
    })
    .join("");
}

function renderPaylineDrilldown(summary) {
  const tbody = byId("paylineTable") && byId("paylineTable").querySelector("tbody");
  if (!tbody) return;
  const rows = PURE.formatPaylineRows(summary);
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="6">${fmt("paylineEmpty")}</td></tr>`;
    return;
  }
  const maxRtp = Math.max(...rows.map((r) => r.rtp_contribution_pp), 0);
  tbody.innerHTML = rows
    .map((r) => {
      const barPct = maxRtp > 0 ? Math.min(100, (r.rtp_contribution_pp / maxRtp) * 100) : 0;
      const topSyms = PURE.formatPaylineTopSymbols(r.top_symbols, 3);
      return (
        `<tr>` +
        `<td>${r.payline_id}</td>` +
        `<td>${fInt(r.hit_count)}</td>` +
        `<td>${r.hit_rate_pct.toFixed(3)}%</td>` +
        `<td class="bar-cell" style="--bar:${barPct.toFixed(1)}%">${r.rtp_contribution_pp.toFixed(4)}</td>` +
        `<td>${r.win_share_pct.toFixed(2)}%</td>` +
        `<td>${topSyms}</td>` +
        `</tr>`
      );
    })
    .join("");
}

function renderRtpClampWarning(summary) {
  // Show the operator a heads-up when the analyzer detected truncated
  // collect cycles in the sample (chunk_spin_times ran out before the
  // next collect bonus could trigger). Hidden when the machine has no
  // collect mechanic or when no robots ended mid-cycle.
  const el = byId("rtpClampWarning");
  if (!el) return;
  const cw = ((summary || {}).collect_mechanic || {}).clamp_warning || {};
  if (!cw.applicable) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  const avg = cw.avg_paid_spins_per_collect;
  el.textContent = fmt("rtpClampWarning", {
    robots: cw.pending_robots || 0,
    pending: cw.total_pending_paid_spins || 0,
    avg: typeof avg === "number" ? avg.toFixed(1) : "?",
  });
  el.classList.remove("hidden");
}

function renderSpinTypeBreakdown(summary) {
  const tbody = byId("spinTypeTable") && byId("spinTypeTable").querySelector("tbody");
  if (!tbody) return;
  const rows = PURE.formatSpinTypeRows(summary);
  const coverage = ((summary || {}).player_impact || {}).spin_type_coverage || 0;
  // Update panel heading with coverage count.
  const heading = document.querySelector(".spin-types h2");
  if (heading) heading.textContent = fmt("panelSpinType") + (coverage > 0 ? ` (${coverage})` : "");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="6">${fmt("spinTypeEmpty")}</td></tr>`;
    return;
  }
  const maxRtp = Math.max(...rows.map((r) => r.rtp_contribution_pp), 0);
  tbody.innerHTML = rows
    .map((r) => {
      const bar = maxRtp > 0 ? Math.min(100, (r.rtp_contribution_pp / maxRtp) * 100) : 0;
      const behavior = r.behavior_name
        ? fmt("spinTypeBehavior_" + r.behavior_name)
        : "\u2014";
      const rtpCell = r.rtp_pct == null
        ? `<td class="muted">N/A</td>`
        : `<td>${r.rtp_pct.toFixed(2)}%</td>`;
      const rareClass = r.rare ? ' class="rare-row"' : "";
      return (
        `<tr${rareClass}>` +
        `<td>${r.spin_type}${r.rare ? " \u26a0" : ""}</td>` +
        `<td>${behavior}</td>` +
        `<td>${r.share_pct.toFixed(1)}%</td>` +
        `<td>${r.hit_rate_pct.toFixed(2)}%</td>` +
        rtpCell +
        `<td class="bar-cell" style="--bar:${bar.toFixed(1)}%">${r.rtp_contribution_pp.toFixed(2)}</td>` +
        `</tr>`
      );
    })
    .join("");
}

function renderMachineMechanics(summary) {
  const panel = byId("machineMechanicsPanel");
  if (!panel) return;
  const mm = ((summary || {}).player_impact || {}).machine_mechanics;
  if (!mm) { panel.classList.add("hidden"); return; }

  const ll = mm.lock_lines || {};
  const ls = mm.lock_symbols || {};
  const lr = mm.lock_reels || {};
  const jp = mm.jackpot || {};
  const anyApplicable = ll.applicable || ls.applicable || lr.applicable || jp.applicable;
  if (!anyApplicable) { panel.classList.add("hidden"); return; }

  panel.classList.remove("hidden");
  const body = byId("mechanicsBody");
  let html = "";

  if (ll.applicable) {
    html += `<div class="mech-section">
      <h3>Lock Lines</h3>
      <div class="mech-grid">
        <div class="mech-stat"><span class="mech-label">${fmt("mechLockRate")}</span><span class="mech-value">${(ll.lock_rate * 100).toFixed(2)}%</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechLockSpins")}</span><span class="mech-value">${ll.lock_spins.toLocaleString()}</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechAvgLines")}</span><span class="mech-value">${ll.avg_lines_per_lock.toFixed(1)}</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechRtpContrib")}</span><span class="mech-value">${ll.lock_rtp_contribution_pp.toFixed(2)}pp</span></div>
      </div>
    </div>`;
  }
  if (ls.applicable) {
    html += `<div class="mech-section">
      <h3>Lock Symbols</h3>
      <div class="mech-grid">
        <div class="mech-stat"><span class="mech-label">${fmt("mechLockRate")}</span><span class="mech-value">${(ls.lock_rate * 100).toFixed(2)}%</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechLockSpins")}</span><span class="mech-value">${ls.lock_spins.toLocaleString()}</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechUniqueSymbols")}</span><span class="mech-value">${ls.unique_symbol_count}</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechRtpContrib")}</span><span class="mech-value">${ls.lock_rtp_contribution_pp.toFixed(2)}pp</span></div>
      </div>
    </div>`;
  }
  if (lr.applicable) {
    html += `<div class="mech-section">
      <h3>Lock Reels</h3>
      <div class="mech-grid">
        <div class="mech-stat"><span class="mech-label">${fmt("mechLockRate")}</span><span class="mech-value">${(lr.lock_rate * 100).toFixed(2)}%</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechLockSpins")}</span><span class="mech-value">${lr.lock_spins.toLocaleString()}</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechRtpContrib")}</span><span class="mech-value">${lr.lock_rtp_contribution_pp.toFixed(2)}pp</span></div>
      </div>
    </div>`;
  }
  if (jp.applicable) {
    html += `<div class="mech-section">
      <h3>Jackpot</h3>
      <div class="mech-grid">
        <div class="mech-stat"><span class="mech-label">${fmt("mechTriggerRate")}</span><span class="mech-value">${(jp.trigger_rate * 100).toFixed(3)}%</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechTriggerSpins")}</span><span class="mech-value">${jp.trigger_spins.toLocaleString()}</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechJackpotIds")}</span><span class="mech-value">${jp.jackpot_id_count}</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechRtpContrib")}</span><span class="mech-value">${jp.rtp_contribution_pp.toFixed(2)}pp</span></div>
      </div>
    </div>`;
  }
  const fs = mm.free_spin || {};
  if (fs.applicable) {
    html += `<div class="mech-section">
      <h3>Free Spin</h3>
      <div class="mech-grid">
        <div class="mech-stat"><span class="mech-label">${fmt("mechChainRate")}</span><span class="mech-value">${(fs.chain_rate * 100).toFixed(2)}%</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechChainSpins")}</span><span class="mech-value">${fs.chain_spins.toLocaleString()}</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechMaxChain")}</span><span class="mech-value">${fs.max_chain_length}</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechRetriggers")}</span><span class="mech-value">${fs.retriggers}</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechRtpContrib")}</span><span class="mech-value">${fs.rtp_contribution_pp.toFixed(2)}pp</span></div>
      </div>
    </div>`;
  }
  const dp = mm.dollar_pick || {};
  if (dp.applicable) {
    html += `<div class="mech-section">
      <h3>Dollar Pick</h3>
      <div class="mech-grid">
        <div class="mech-stat"><span class="mech-label">${fmt("mechPickRate")}</span><span class="mech-value">${(dp.pick_rate * 100).toFixed(3)}%</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechPickSpins")}</span><span class="mech-value">${dp.pick_spins.toLocaleString()}</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechAvgDollars")}</span><span class="mech-value">${dp.avg_dollars_per_pick.toFixed(1)}</span></div>
        <div class="mech-stat"><span class="mech-label">${fmt("mechRtpContrib")}</span><span class="mech-value">${dp.rtp_contribution_pp.toFixed(2)}pp</span></div>
      </div>
    </div>`;
  }
  body.innerHTML = html;
}

// Minimal HTML escape for strings that come from classifier output —
// feature names / labels / explanations are machine-internal text and
// generally safe, but we escape defensively to avoid surprises if the
// classifier JSON ever carries unexpected content.
function _escHtml(s) {
  if (s == null) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

// Render the payline-structure classification panel. Data comes from
// /api/classifier/{machine}; three sub-blocks:
//   1. cross-mode labels (this machine classified per mode)
//   2. per-SpinType channel split for the CURRENT mode (which win
//      channel — pay_id / FeatureWin aggregate / pick-em selector —
//      accounts for wins in each SpinType)
//   3. feature-mode rule delta flag: bonus SpinTypes whose line_id
//      set differs from paid ST (e.g. line_id=-2 appearing only in
//      bonus rounds, indicating distinct bonus-mode payline rules)
// Missing classifier output / fetch failure → hide panel silently.
async function renderPaylineClassification(summary) {
  const panel = byId("paylineClassificationPanel");
  if (!panel) return;
  const machine = (summary || {}).machine;
  const currentMode = Number((summary || {}).mode);
  if (!machine) { panel.classList.add("hidden"); return; }

  let data;
  try {
    data = await apiGet(`/api/classifier/${encodeURIComponent(machine)}`);
  } catch (_err) {
    panel.classList.add("hidden");
    return;
  }
  const modes = (data && data.modes) || {};
  if (!Object.keys(modes).length) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  const body = byId("paylineClassificationBody");

  // (1) cross-mode label table
  const modeRows = Object.entries(modes)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([m, v]) => {
      const isCurrent = Number(m) === currentMode;
      const label = _escHtml(v.machine_label || "—");
      const paidSt = v.paid_spin_type != null ? v.paid_spin_type : "—";
      const tally = _escHtml((v.feature_tally_keys || []).join(", ") || "—");
      const curTag = isCurrent
        ? ` <span class="classify-current-tag">(${_escHtml(fmt("classifyCurrent"))})</span>`
        : "";
      return `<tr${isCurrent ? ' class="classify-current-row"' : ""}>`
        + `<td>${m}${curTag}</td>`
        + `<td>${label}</td>`
        + `<td>${paidSt}</td>`
        + `<td>${tally}</td>`
        + `</tr>`;
    })
    .join("");

  // (2) per-SpinType channel split for CURRENT mode
  const cur = modes[String(currentMode)];
  let channelHtml = "";
  if (cur && cur.per_st_verdicts) {
    const stRows = Object.entries(cur.per_st_verdicts)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([st, v]) => {
        const kind = v.is_paid
          ? _escHtml(fmt("classifyKindPaid"))
          : _escHtml(fmt("classifyKindFree"));
        const bucket = _escHtml((v.classification || {}).bucket || "—");
        const channel = _escHtml(v.channel || "—");
        const expl = _escHtml(v.explanation || "");
        return `<tr>`
          + `<td>${_escHtml(st)}</td>`
          + `<td>${kind}</td>`
          + `<td>${bucket}</td>`
          + `<td>${channel}</td>`
          + `<td class="classify-expl">${expl}</td>`
          + `</tr>`;
      })
      .join("");
    channelHtml = `
      <h3>${_escHtml(fmt("classifyHeadChannel"))}</h3>
      <table class="drilldown-table">
        <thead><tr>
          <th>${_escHtml(fmt("classifyColSpinType"))}</th>
          <th>${_escHtml(fmt("classifyColBehavior"))}</th>
          <th>${_escHtml(fmt("classifyColClass"))}</th>
          <th>${_escHtml(fmt("classifyColChannel"))}</th>
          <th>${_escHtml(fmt("classifyColExpl"))}</th>
        </tr></thead>
        <tbody>${stRows}</tbody>
      </table>`;
  }

  // (3) feature-mode rule delta flag
  let deltaHtml = "";
  if (cur && cur.feature_delta_from_paid
      && Object.keys(cur.feature_delta_from_paid).length) {
    const paidSt = cur.paid_spin_type != null ? cur.paid_spin_type : "?";
    const hint = fmt("classifyDeltaHint").replace("{paid}", String(paidSt));
    const rows = Object.entries(cur.feature_delta_from_paid)
      .map(([st, delta]) => {
        const added = (delta.added || []).join(", ") || "—";
        const removed = (delta.removed || []).join(", ") || "—";
        return `<tr><td>${_escHtml(st)}</td>`
          + `<td>${_escHtml(added)}</td>`
          + `<td>${_escHtml(removed)}</td></tr>`;
      })
      .join("");
    deltaHtml = `
      <h3 class="classify-warn">⚠ ${_escHtml(fmt("classifyHeadDelta"))}</h3>
      <p class="hint">${_escHtml(hint)}</p>
      <table class="drilldown-table">
        <thead><tr>
          <th>${_escHtml(fmt("classifyColSpinType"))}</th>
          <th>${_escHtml(fmt("classifyColAdded"))}</th>
          <th>${_escHtml(fmt("classifyColRemoved"))}</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  body.innerHTML = `
    <h3>${_escHtml(fmt("classifyHeadCrossMode"))}</h3>
    <table class="drilldown-table">
      <thead><tr>
        <th>${_escHtml(fmt("classifyColMode"))}</th>
        <th>${_escHtml(fmt("classifyColLabel"))}</th>
        <th>${_escHtml(fmt("classifyColPaidSt"))}</th>
        <th>${_escHtml(fmt("classifyColTally"))}</th>
      </tr></thead>
      <tbody>${modeRows}</tbody>
    </table>
    ${channelHtml}
    ${deltaHtml}
  `;
}

// Render the per-pay_id SHAPE inference panel. Data comes from
// /api/paytables/{machine}/mode/{mode}/shape produced by
// scripts/infer_paytable.py. Shows:
//   1. wild inference status banner (inferred / partial / undetermined +
//      review-needed flag for machines with polluted substitution signal)
//   2. wild evidence table (confidence + mono/substitute/paying counts
//      per candidate symbol)
//   3. per (pay_id, match_count) shape rows: symbol_set / match_count /
//      wild substitution rate / line sign / position cols covered /
//      confidence tag / notes
// Missing inference output → hide panel silently (non-critical).
async function renderPaytableShape(summary) {
  const panel = byId("paytableShapePanel");
  if (!panel) return;
  const machine = (summary || {}).machine;
  const mode = Number((summary || {}).mode);
  if (!machine || !mode) { panel.classList.add("hidden"); return; }

  let data;
  try {
    data = await apiGet(
      `/api/paytables/${encodeURIComponent(machine)}/mode/${mode}/shape`,
    );
  } catch (_err) {
    panel.classList.add("hidden");
    return;
  }
  if (!data || data.status === "not_run" || !Array.isArray(data.rows) || !data.rows.length) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  const body = byId("paytableShapeBody");

  const wi = data.wild_inference || {};
  const wildStatus = wi.status || "undetermined";
  const wilds = Array.isArray(wi.wilds) ? wi.wilds : [];
  const reviewNeeded = Boolean(wi.review_needed);
  const stemCount = Number(wi.stem_count || 0);
  const flags = Array.isArray(data.machine_flags) ? data.machine_flags : [];

  // Banner styling by status.
  let statusColor = "#6b7f90";
  let statusEmoji = "·";
  if (wildStatus === "inferred") { statusColor = "#2e7d32"; statusEmoji = "✓"; }
  else if (wildStatus === "partial") { statusColor = "#c88a00"; statusEmoji = "≈"; }
  else if (wildStatus === "undetermined") { statusColor = "#888"; statusEmoji = "?"; }

  const wildsStr = wilds.length ? wilds.map(_escHtml).join(", ") : "—";
  const reviewBanner = reviewNeeded
    ? `<div class="shape-warn">⚠ ${_escHtml(
        `推断出 ${wilds.length} 个 wild 候选，跨 ${stemCount} 个符号族。` +
        `复杂 group-pay 机台可能产生假阳，请人工核对。`,
      )}</div>`
    : "";
  const flagsBanner = flags.length
    ? `<div class="shape-flag">🚩 ${flags.map(_escHtml).join(" · ")}</div>`
    : "";

  // Wild evidence table.
  const ev = wi.evidence || {};
  const evRows = Object.entries(ev)
    .sort(([, a], [, b]) => {
      const order = { high: 0, medium: 1, low: 2 };
      return (order[a.confidence] ?? 3) - (order[b.confidence] ?? 3);
    })
    .slice(0, 12)
    .map(([sym, e]) => {
      const conf = e.confidence || "-";
      const confBadge = conf === "high" ? "🟢" : conf === "medium" ? "🟡" : "⚪";
      const score = e.wild_score != null ? Number(e.wild_score).toFixed(1) : "—";
      const reason = _escHtml(e.reason || "");
      return `<tr>
        <td><code>${_escHtml(sym)}</code></td>
        <td>${confBadge} ${_escHtml(conf)}</td>
        <td>${Number(e.mono_count || 0)}</td>
        <td>${Number(e.substitutes_count || 0)}</td>
        <td>${Number(e.paying_count || 0)}</td>
        <td>${score}</td>
        <td class="shape-reason">${reason}</td>
      </tr>`;
    })
    .join("");

  const evidenceHtml = evRows
    ? `<h3 style="margin:14px 0 6px;font-size:13px;color:var(--muted)">Wild evidence</h3>
       <table class="drilldown-table">
         <thead><tr>
           <th>symbol</th><th>conf</th><th>mono</th><th>sub</th><th>paying</th><th>score</th><th>reason</th>
         </tr></thead>
         <tbody>${evRows}</tbody>
       </table>`
    : "";

  // Shape rows table. Sort positive pay_ids then negative, each by -fires.
  const sorted = [...data.rows].sort((a, b) => {
    const aPos = (a.pay_id ?? 0) >= 0 ? 0 : 1;
    const bPos = (b.pay_id ?? 0) >= 0 ? 0 : 1;
    if (aPos !== bPos) return aPos - bPos;
    return (b.fires || 0) - (a.fires || 0);
  });

  const rowsHtml = sorted
    .map((r) => {
      const sh = r.shape || {};
      const symSet = Array.isArray(sh.symbol_set) ? sh.symbol_set : [];
      const mc = r.match_count;
      const symDisplay = symSet.length
        ? `${mc}× ${symSet.map(_escHtml).join(" / ")}`
        : "—";
      const purity = Number(sh.symbol_purity || 0);
      const wildSubRate = Number(sh.wild_substitution_rate || 0);
      const wildSubBadge = wildSubRate > 0
        ? `<span class="shape-wild-rate" title="wild 替换率">${(wildSubRate * 100).toFixed(0)}% W</span>`
        : "";
      const lineSign = sh.line_id_sign || "—";
      const cols = Array.isArray(sh.position_cols_covered) ? sh.position_cols_covered : [];
      const colStr = cols.length ? cols.join(",") : "—";
      const conf = sh.confidence || "low";
      const confBadge = conf === "high" ? "🟢" : conf === "medium" ? "🟡" : "⚪";
      const notes = Array.isArray(sh.notes) && sh.notes.length
        ? sh.notes.map(_escHtml).join("; ")
        : "";
      return `<tr>
        <td>${r.pay_id}</td>
        <td>${r.fires}</td>
        <td>${_escHtml(symDisplay)} ${wildSubBadge}</td>
        <td>${(purity * 100).toFixed(0)}%</td>
        <td>${_escHtml(lineSign)}</td>
        <td>${_escHtml(colStr)}</td>
        <td>${confBadge}</td>
        <td class="shape-notes">${notes}</td>
      </tr>`;
    })
    .join("");

  const grid = data.grid || {};
  const gridStr = grid.n_cols && grid.n_rows ? `${grid.n_cols}×${grid.n_rows}` : "—";
  const chunksStr = data.chunks_scanned != null
    ? ` · ${data.chunks_scanned} chunks scanned`
    : "";

  body.innerHTML =
    `<div class="shape-header">
       <span>网格 ${_escHtml(gridStr)}${_escHtml(chunksStr)}</span>
       <span class="shape-wild-status" style="color:${statusColor}">
         ${statusEmoji} Wild 推断: ${_escHtml(wildStatus)} — ${wildsStr}
       </span>
     </div>` +
    reviewBanner +
    flagsBanner +
    evidenceHtml +
    `<h3 style="margin:14px 0 6px;font-size:13px;color:var(--muted)">每个 Pay ID 的形状</h3>
     <table class="drilldown-table">
       <thead><tr>
         <th>pay_id</th><th>fires</th><th>shape (N× symbols)</th>
         <th>purity</th><th>line</th><th>cols</th><th>conf</th><th>notes</th>
       </tr></thead>
       <tbody>${rowsHtml}</tbody>
     </table>`;
}

// Build the per-feature bucket histogram as a standard drilldown-
// table so typography + bar line match the global 倍率分布 panel
// byte-for-byte. Columns: 倍率区间 / 次数 / 占比 / 本类 pp / bar.
// The pp values slice the GLOBAL RTP denominator (see analyzer
// note) so summing a feature's bucket pp = that feature's header
// pp (e.g. LockSymbolFreespin buckets sum to its 41.18pp header).
// Skips buckets with zero spins. Returns "" when nothing to show.
function _renderFeatureBucketTable(buckets) {
  if (!Array.isArray(buckets) || !buckets.length) return "";
  const nonzero = buckets.filter((b) => Number(b.spin_count || 0) > 0);
  if (!nonzero.length) return "";
  const maxRtp = Math.max(
    ...nonzero.map((b) => Math.abs(Number(b.rtp_contribution_pp || 0))),
    0.001,
  );
  const body = nonzero.map((b) => {
    const label = PURE.prettyBucketLabel(b.bucket);
    const count = Number(b.spin_count || 0);
    const rate = (Number(b.spin_rate || 0) * 100).toFixed(2);
    const rtpPp = Number(b.rtp_contribution_pp || 0);
    const bar = Math.min(100, (Math.abs(rtpPp) / maxRtp) * 100);
    return (
      `<tr>` +
      `<td>${_escHtml(label)}</td>` +
      `<td>${count.toLocaleString()}</td>` +
      `<td>${rate}%</td>` +
      `<td>${rtpPp.toFixed(2)}pp</td>` +
      `<td class="bar-cell" style="--bar:${bar.toFixed(1)}%"></td>` +
      `</tr>`
    );
  }).join("");
  return (
    `<table class="drilldown-table feature-bucket-table">` +
    `<thead><tr>` +
    `<th>${_escHtml(fmt("thBucket"))}</th>` +
    `<th>${_escHtml(fmt("thCount"))}</th>` +
    `<th>${_escHtml(fmt("thRate"))}</th>` +
    `<th>${_escHtml(fmt("thRtpContribution"))}</th>` +
    `<th></th>` +
    `</tr></thead>` +
    `<tbody>${body}</tbody>` +
    `</table>`
  );
}

function renderFieldDiscovery(summary) {
  const panel = byId("fieldDiscoveryPanel");
  if (!panel) return;
  const fd = ((summary || {}).player_impact || {}).field_discovery;
  if (!fd || !fd.extra_field_count) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  const totalSpins = ((summary || {}).sampling || {}).total_spins || 1;
  const tbody = byId("fieldDiscoveryTable").querySelector("tbody");
  tbody.innerHTML = fd.extra_fields
    .map((f) => {
      const rate = ((f.occurrences / totalSpins) * 100).toFixed(1);
      return `<tr><td><code>${f.field}</code></td><td>${f.occurrences.toLocaleString()}</td><td>${rate}%</td></tr>`;
    })
    .join("");
}

// Render the upstream_feature_breakdown panel from
// summary.player_impact.upstream_feature_breakdown. Paying features
// render as cards with per-feature bucket histograms (same visual
// language as the global 倍率分布 table). Trigger-only features
// don't get their own cards — they're absorbed into their paying
// parent as a precursor chain breadcrumb, so the operator reads a
// single story: "this bonus is gated by X→Y→Z, it fires N×, its
// RTP shape is this histogram." Orphan triggers (no resolved paying
// parent — e.g. M273's BuffCollectionMap session meta) get one
// compact footer row instead of a full-width empty card.
function renderFeatureBreakdownPanel(summary) {
  const body = byId("featureBreakdownInline");
  if (!body) return;
  const data = ((summary || {}).player_impact || {}).upstream_feature_breakdown;
  if (!data || !data.applicable || !Array.isArray(data.features) || !data.features.length) {
    body.innerHTML = "";
    return;
  }
  const features = data.features;
  const triggerOnly = features.filter((f) => Boolean(f.trigger_only));
  const paying = features.filter((f) => !f.trigger_only);

  // For each paying feature, collect EVERY inbound trigger chain.
  // A paying feature may have multiple independent predecessors:
  // M273 LockSymbolFreespin is fed by both the wheel-ceremony chain
  // (ListRewardWheel → WheelSelector → PreWheel) AND the BCM cycle
  // (BuffCollectionMap as cycle trigger from config pairing). Each
  // inbound chain renders as its own breadcrumb line.
  const absorbed = new Set();
  function chainsInto(payingName) {
    const chains = [];
    // Walk each direct predecessor back to its terminus.
    const directPreds = triggerOnly.filter(
      (t) => t.chain_parent_feature === payingName && !absorbed.has(t.feature_name),
    );
    for (const pred of directPreds) {
      const rev = [pred];
      absorbed.add(pred.feature_name);
      let target = pred.feature_name;
      while (true) {
        const upstream = triggerOnly.find(
          (t) => t.chain_parent_feature === target && !absorbed.has(t.feature_name),
        );
        if (!upstream) break;
        rev.push(upstream);
        absorbed.add(upstream.feature_name);
        target = upstream.feature_name;
      }
      // rev[0] = direct predecessor (closest), rev[last] = furthest.
      // Reverse for display "earliest → latest → bonus".
      chains.push(rev.reverse());
    }
    return chains;
  }

  const payingCards = paying.map((feat) => {
    const chains = chainsInto(feat.feature_name);
    return _renderPayingFeatureCard(feat, chains);
  }).join("");

  const orphans = triggerOnly.filter((t) => !absorbed.has(t.feature_name));
  const orphansRow = orphans.length
    ? `<div class="feature-orphans">` +
      `<span class="feature-orphans-label">其他（未归属链条）:</span> ` +
      orphans.map((t) => {
        const fires = Number(t.fires_spins || t.total_times || 0).toLocaleString();
        const rate = (Number(t.fire_rate || 0) * 100).toFixed(2);
        return `<span class="orphan-chip" title="${rate}% of spins · ${fires}×">`
          + `${_escHtml(t.feature_name)}<span class="orphan-fires"> ${fires}×</span>`
          + `</span>`;
      }).join("") +
      `</div>`
    : "";

  body.innerHTML =
    `<hr style="margin:14px 0;border:none;border-top:1px solid #d2dde9">` +
    `<h3 style="margin:0 0 8px;font-size:13px;color:var(--muted)">${fmt("panelFeatureBreakdown")}</h3>` +
    `<div class="feature-blocks-grid">${payingCards}</div>` +
    orphansRow;
}

// Render one paying feature card: header + meta + one breadcrumb
// per inbound trigger chain + per-feature multiplier bucket
// histogram. Same teal aesthetic as the global 倍率分布 table.
// ``chains`` is a list-of-lists — each inner list is a single
// linear trigger chain feeding into this paying feature.
function _renderPayingFeatureCard(feat, chains) {
  const rtpPp = Number(feat.rtp_contribution_pp || 0).toFixed(2);
  const sharePct = (Number(feat.share_of_total_win || 0) * 100).toFixed(1);
  const firesSpins = Number(feat.fires_spins || feat.total_times || 0);
  const fireRatePct = (Number(feat.fire_rate || 0) * 100).toFixed(2);
  const buckets = Array.isArray(feat.bucket_distribution) ? feat.bucket_distribution : [];
  const bucketTableHtml = _renderFeatureBucketTable(buckets);
  const subStreams = Array.isArray(feat.sub_streams) ? feat.sub_streams : [];
  const subStreamsHtml = _renderFeatureSubStreams(subStreams);

  // Multi-chain breadcrumb: one line per inbound chain. Cycle-type
  // triggers (resolved_spin_type == null — e.g. BuffCollectionMap)
  // get a "(cycle)" suffix on the trigger name since they're not a
  // sequential round chain but a per-spin counter reset.
  const chainLines = (chains || [])
    .filter((c) => Array.isArray(c) && c.length)
    .map((chain) => {
      const steps = chain.map((t) => {
        const tFires = Number(t.fires_spins || t.total_times || 0).toLocaleString();
        const conf = t.chain_parent_confidence || "";
        const confDot = conf === "high" ? "" : conf === "medium"
          ? `<span class="chain-conf-warn" title="medium confidence on chain edge">·</span>`
          : `<span class="chain-conf-low" title="low-confidence chain edge">·</span>`;
        const isCycle = t.resolved_spin_type == null;
        const cycleTag = isCycle
          ? `<span class="chain-cycle-tag" title="cycle/session-level trigger (no round-level SpinType) — typically a CollectCount-style accumulator">(cycle)</span>`
          : "";
        return `<span class="chain-step" title="${tFires}× fires">`
          + `${_escHtml(t.feature_name)}${cycleTag}${confDot}`
          + `</span>`;
      }).join(`<span class="chain-arrow">→</span>`);
      const tail = chain[chain.length - 1];
      const endFires = Number(tail?.fires_spins || 0).toLocaleString();
      return `<div class="feature-chain">` +
        `<span class="feature-chain-label">前置:</span> ${steps}` +
        `<span class="chain-fires"> · ${endFires}× 触发</span>` +
        `</div>`;
    })
    .join("");

  return (
    `<div class="feature-block">` +
    `<h3>${_escHtml(String(feat.feature_name))} <span class="feature-metric">${rtpPp}pp · ${sharePct}%</span></h3>` +
    `<div class="feature-meta">fires ${firesSpins.toLocaleString()}× · ${fireRatePct}% of spins</div>` +
    chainLines +
    (bucketTableHtml
      ? bucketTableHtml
      : `<div class="muted" style="font-size:12px">无倍率分桶数据</div>`) +
    subStreamsHtml +
    `</div>`
  );
}

// Render per-feature sub-stream summary (one row per trigger path).
// Same paying feature entered via different trigger chains often
// has different stats (initial ReelSkin / multiplier / etc.). This
// compact table lets the operator see each path's fires + rtp split
// without drilling into raw data. Suppressed if only one stream
// (nothing to compare) or no streams (feature not in any chain —
// typically paid-normal features like NormalCollectionSpin).
function _renderFeatureSubStreams(subs) {
  if (!Array.isArray(subs) || subs.length < 2) return "";
  const body = subs.map((sub) => {
    const fires = Number(sub.fires || 0).toLocaleString();
    const win = Number(sub.win_credits || 0);
    const rtpPp = Number(sub.rtp_contribution_pp || 0).toFixed(2);
    const avgWin = sub.fires > 0
      ? Math.round(win / sub.fires).toLocaleString()
      : "—";
    return (
      `<tr>` +
      `<td>${_escHtml(String(sub.label || "—"))}</td>` +
      `<td>${fires}</td>` +
      `<td>${avgWin}</td>` +
      `<td>${rtpPp}pp</td>` +
      `</tr>`
    );
  }).join("");
  return (
    `<div class="feature-substreams-head">按触发路径拆分</div>` +
    `<table class="drilldown-table feature-substream-table">` +
    `<thead><tr>` +
    `<th>触发路径</th>` +
    `<th>${_escHtml(fmt("thCount"))}</th>` +
    `<th>均赢</th>` +
    `<th>${_escHtml(fmt("thRtpContribution"))}</th>` +
    `</tr></thead>` +
    `<tbody>${body}</tbody>` +
    `</table>`
  );
}

// Render the bonus_chain_dynamics panel (ReMarks-derived
// MapCollection stats). Hidden when the sample contains no
// Freespin-annotated chains.
// Render the collect-cycle + RTP correction panel. Sourced from
// ``summary.collect_mechanic.{cycle_observation,bonus_cycle_correction,
// feature_match}``. Only visible when a collect mechanic was
// observed in the sample (mechanic_detected). Surfaces:
//   - detected cycle length (floor / lower bound)
//   - completed cycles total + pending
//   - resolved bonus pair (config / heuristic / none)
//   - estimated correction pp + pre/post RTP
//   - any warnings from feature_match or cycle_observation
// Hidden for machines with no collect mechanic (most non-M272-style
// machines) — the data is non-applicable there.
function renderCollectCyclePanel(summary) {
  const panel = byId("collectCyclePanel");
  if (!panel) return;
  const cm = (summary || {}).collect_mechanic || {};
  const co = cm.cycle_observation || {};
  const bcc = cm.bonus_cycle_correction || {};
  const fm = cm.feature_match || {};
  // Only applicable when a cycle mechanic was detected at all.
  if (!co.mechanic_detected && !bcc.applicable) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  const body = byId("collectCycleBody");

  const rtpPp = Number(((summary || {}).rtp || {}).point_pct || 0);
  // ``bcc.applicable=false`` means the analyzer couldn't compute a
  // correction (typically: sample too short to observe a full cycle
  // reset). Distinguish from "applicable=true, correction=0" (sample
  // covers a complete cycle, nothing to correct).
  const correctionApplicable = Boolean(bcc.applicable);
  const correctionPp = correctionApplicable
    ? Number(bcc.estimated_correction_pp || 0)
    : null;
  const postRtp = correctionPp != null ? rtpPp + correctionPp : null;

  const cycleLen = co.cycle_len_lower_bound != null
    ? `≥${Number(co.cycle_len_lower_bound).toLocaleString()} spins`
    : (bcc.detected_cycle_length != null
      ? `${Number(bcc.detected_cycle_length).toLocaleString()} spins`
      : "—");
  const completed = Number(bcc.completed_cycles_total || 0).toLocaleString();
  const pending = Number(bcc.robots_with_pending_cycle || 0).toLocaleString();
  const avgPayout = bcc.avg_bonus_payout != null
    ? Number(bcc.avg_bonus_payout).toLocaleString(undefined, { maximumFractionDigits: 0 })
    : "—";
  const bonusFeat = bcc.bonus_feature || fm.bonus_feature;
  const bonusSrc = bcc.bonus_feature_source || fm.bonus_feature_source || "—";
  const srcBadge = bonusSrc === "config" ? "🟢 config"
    : bonusSrc === "heuristic" ? "🟡 heuristic"
    : bonusSrc === "none" ? "⚪ none"
    : `⚪ ${_escHtml(bonusSrc)}`;
  const resetBadge = co.reset_observed ? "✓ reset 已观测" : "⚠ reset 未观测（样本不足一周期）";
  const warnings = [];
  if (co.warning) warnings.push(`cycle: ${co.warning}`);
  if (fm.warning) warnings.push(`feature_match: ${fm.warning}`);

  // Correction block: three states. applicable + >0.5pp = warn;
  // applicable + small = ok (sample covered the cycle); inapplicable
  // = "n/a" with an explanation (sample too short).
  let correctionBlock;
  if (!correctionApplicable) {
    correctionBlock =
      `<div class="cc-correction cc-correction-na">` +
        `<div class="cc-correction-headline">` +
          `<span class="cc-label">RTP 校正</span>` +
          `<span class="cc-correction-delta">N/A</span>` +
        `</div>` +
        `<div class="cc-correction-split">` +
          `<span class="cc-pre">raw ${rtpPp.toFixed(2)}%</span>` +
          `<span class="cc-arrow">·</span>` +
          `<span class="cc-post">无法校正</span>` +
        `</div>` +
        `<div class="cc-correction-hint">` +
          "样本未覆盖完整 cycle（无 reset 观测），无法估算校正量。增加 SpinTimes / 续采直到 CollectCount 至少完成一次 reset 才能生成校正。" +
        `</div>` +
      `</div>`;
  } else {
    const tone = correctionPp > 0.5 ? "warn" : correctionPp > 0.05 ? "note" : "ok";
    const sign = correctionPp >= 0 ? "+" : "";
    correctionBlock =
      `<div class="cc-correction cc-correction-${tone}">` +
        `<div class="cc-correction-headline">` +
          `<span class="cc-label">RTP 校正</span>` +
          `<span class="cc-correction-delta">${sign}${correctionPp.toFixed(2)}pp</span>` +
        `</div>` +
        `<div class="cc-correction-split">` +
          `<span class="cc-pre">raw ${rtpPp.toFixed(2)}%</span>` +
          `<span class="cc-arrow">→</span>` +
          `<span class="cc-post">校正后 ${postRtp.toFixed(2)}%</span>` +
        `</div>` +
        `<div class="cc-correction-hint">` +
          (correctionPp > 0.5
            ? "部分 robot 在样本末尾尚未完成一个完整 cycle，校正补上这部分未触发 bonus 的贡献。"
            : correctionPp > 0.05
            ? "样本基本覆盖完整 cycle，校正很小，可忽略。"
            : "样本已充分覆盖完整 cycle，无须校正。") +
        `</div>` +
      `</div>`;
  }

  body.innerHTML =
    `<div class="collect-cycle-grid">` +
      `<div class="cc-item"><div class="cc-label">机制状态</div><div class="cc-value">${_escHtml(resetBadge)}</div></div>` +
      `<div class="cc-item"><div class="cc-label">周期长度</div><div class="cc-value">${_escHtml(cycleLen)}</div></div>` +
      `<div class="cc-item"><div class="cc-label">已完成周期</div><div class="cc-value">${_escHtml(completed)}</div></div>` +
      `<div class="cc-item"><div class="cc-label">待触发周期</div><div class="cc-value">${_escHtml(pending)}</div></div>` +
      `<div class="cc-item"><div class="cc-label">配对 bonus</div><div class="cc-value">${_escHtml(bonusFeat || "—")} <span class="cc-src">${srcBadge}</span></div></div>` +
      `<div class="cc-item"><div class="cc-label">平均 bonus 奖励</div><div class="cc-value">${_escHtml(avgPayout)} credits</div></div>` +
    `</div>` +
    correctionBlock +
    (warnings.length
      ? `<div class="cc-warnings">⚠ ${warnings.map(_escHtml).join(" · ")}</div>`
      : "");
}

function renderBonusChainDynamicsPanel(summary) {
  const panel = byId("bonusChainDynamicsPanel");
  if (!panel) return;
  const d = ((summary || {}).player_impact || {}).bonus_chain_dynamics;
  if (!d || !d.applicable || !d.chain_count) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");

  // Per-feature cards with KPIs + depth curve + histogram.
  const byFeat = d.by_feature || {};
  const featNames = Object.keys(byFeat);
  const features = featNames.length >= 1
    ? featNames.map((fn) => ({ name: fn, data: byFeat[fn] }))
    : [{ name: "All", data: {
        chain_count: d.chain_count,
        bonus_round_count: d.bonus_round_count,
        avg_chain_length: d.avg_chain_length,
        chain_length_quantiles: d.chain_length_quantiles,
        chain_max_ratio_quantiles: d.chain_max_ratio_quantiles,
        self_retrigger_round_rate: d.self_retrigger_round_rate,
      }}];

  // Aggregate depth curve + histogram (shared across features since
  // per-feature breakdown doesn't carry these yet — they come from
  // the global accumulators).
  const totalBonusRounds = Number(d.bonus_round_count || 0);
  const hist = Array.isArray(d.extra_ratio_histogram) ? d.extra_ratio_histogram : [];
  const maxHistShare = Math.max(...hist.map((h) => Number(h.rounds || 0)), 0) / (totalBonusRounds || 1);
  const histHtml = hist.map((h) => {
    const r = Number(h.rounds || 0);
    const share = totalBonusRounds > 0 ? (r / totalBonusRounds) : 0;
    const bar = maxHistShare > 0 ? Math.min(100, (share / maxHistShare) * 100) : 0;
    return `<tr><td>${fInt(h.ratio)}x</td><td class="bar-cell" style="--bar:${bar.toFixed(1)}%">${(share * 100).toFixed(1)}%</td></tr>`;
  }).join("");

  const depth = Array.isArray(d.extra_ratio_by_chain_depth) ? d.extra_ratio_by_chain_depth : [];
  const maxDepthRatio = Math.max(...depth.map((b) => Number(b.avg_extra_ratio || 0)), 0);
  const depthHtml = depth.map((b) => {
    const avg = Number(b.avg_extra_ratio || 0);
    const rounds = Number(b.rounds || 0);
    const sharePct = totalBonusRounds > 0 ? ((rounds / totalBonusRounds) * 100).toFixed(1) : "0.0";
    const bar = maxDepthRatio > 0 ? Math.min(100, (avg / maxDepthRatio) * 100) : 0;
    return `<tr><td>${b.depth_bucket}</td><td>${sharePct}%</td><td class="bar-cell" style="--bar:${bar.toFixed(1)}%">${avg.toFixed(0)}x</td></tr>`;
  }).join("");

  const featHtml = features.map((f) => {
    const fd = f.data;
    const fq = fd.chain_length_quantiles || {};
    const frq = fd.chain_max_ratio_quantiles || {};
    const retrigger = (Number(fd.self_retrigger_round_rate || 0) * 100).toFixed(1);
    const chains = fd.chain_count || 0;
    const rnds = fd.bonus_round_count || 0;
    return (
      `<div class="bcFeatCard">` +
      `<h4>${f.name} <span class="bcFeatCount">${chains} chains · ${rnds} rounds</span></h4>` +
      `<div class="bcFeatKpis">` +
      `<div class="bcFeatMetric"><em>${fmt("bonusChainLenLabel")}</em><b>avg ${Number(fd.avg_chain_length || 0).toFixed(1)}</b><span>p50 ${fq.p50 || 0} · p90 ${fq.p90 || 0} · max ${fq.max || 0}</span></div>` +
      `<div class="bcFeatMetric"><em>${fmt("bonusChainRatioLabel")}</em><b>p50 ${frq.p50 || 0}x</b><span>p90 ${frq.p90 || 0}x · max ${frq.max || 0}x</span></div>` +
      `<div class="bcFeatMetric"><em>${fmt("bonusChainRetriggerLabel")}</em><b>${retrigger}%</b></div>` +
      `</div></div>`
    );
  }).join("");

  byId("bonusChainBody").innerHTML =
    `<div class="bcFeatGrid">${featHtml}</div>` +
    `<div class="bonus-chain-tables">` +
    `<div><h3>${fmt("bonusChainDepthLabel")}</h3>` +
    `<table class="drilldown-table"><thead><tr><th>Depth</th><th>Share</th><th>avg ExtraRatio</th></tr></thead>` +
    `<tbody>${depthHtml}</tbody></table></div>` +
    `<div><h3>${fmt("bonusChainHistogramLabel")}</h3>` +
    `<table class="drilldown-table"><thead><tr><th>Ratio</th><th>Share</th></tr></thead>` +
    `<tbody>${histHtml}</tbody></table></div>` +
    `</div>`;
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
  // machineSelect / modeSelect lived on the old debug-tab sidebar and are
  // gone after the UI simplification. Sampling now runs from the manage
  // tab's 采样选中机台 panel which uses sampleMode + the catalog-selected
  // machines from state.runFilterMachines. This function is kept as a
  // no-op so existing call sites (loadBootstrap + lang change + rebuild
  // refresh) don't need to be re-plumbed.
  const mSel = byId("machineSelect");
  if (!mSel) return;
  mSel.innerHTML = "";
  const groups = {};
  const ORDER = ["Normal", "Collect", "Lock", "FreeSpin", "ReSpin", "Wheel", "Fortunes", "Selector", "Other", "Unknown"];
  state.machines.forEach((m) => {
    const cat = m.category || "Other";
    if (!groups[cat]) groups[cat] = [];
    groups[cat].push(m);
  });
  const orderedKeys = ORDER.filter((k) => groups[k]);
  Object.keys(groups).forEach((k) => { if (!orderedKeys.includes(k)) orderedKeys.push(k); });
  orderedKeys.forEach((cat) => {
    const og = document.createElement("optgroup");
    og.label = `${cat} (${groups[cat].length})`;
    groups[cat].forEach((m) => og.appendChild(new Option(m.machine, m.machine)));
    mSel.appendChild(og);
  });
  refreshModes();
}

function refreshModes() {
  const mSel = byId("machineSelect");
  const modeSel = byId("modeSelect");
  if (!mSel || !modeSel) return;
  const machine = state.machines.find((m) => m.machine === mSel.value) || state.machines[0] || { modes: [1] };
  modeSel.innerHTML = "";
  (machine.modes || [1]).forEach((m) => modeSel.appendChild(new Option(String(m), String(m))));
}

function fillCiTierOptions() {
  const sel = byId("ciSelect");
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = "";
  for (const { value, label } of PURE.ciTierOptions(state.lang)) {
    sel.appendChild(new Option(label, value));
  }
  // Preserve user selection across language re-render; default to 0.5.
  sel.value = prev || "0.5";
  applyModeCiConstraint();
}

function fillBankMultOptions() {
  const sel = byId("bankMultSelect");
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = "";
  for (const { value, label } of PURE.bankrollMultiplierPresets(state.lang)) {
    sel.appendChild(new Option(label, value));
  }
  // Default: Standard preset; preserve user's previous choice across re-renders.
  sel.value = prev || "100,200,500";
}

// Reset the robot/concurrency inputs to their preset defaults from the
// HTML `value` attribute (validated against M272 mode 1 via autotune).
// Called on machine / mode change so the operator always starts with
// sensible values; Auto Tune remains available for machine-specific
// refinement.
function resetConcurrencyInputsToPreset() {
  const r = byId("robotInput");
  const c = byId("concInput");
  if (r) r.value = r.defaultValue || "";
  if (c) c.value = c.defaultValue || "";
  updateActionStates();
}

// Mode 2 / 5 are high-volatility bonus/freegame paths that must use the
// fuzzy tier (value "0"); force the select there and gray out the other
// options. Mode 1 / 7 (regular-player modes) re-enable the full set.
function applyModeCiConstraint() {
  const modeSel = byId("modeSelect");
  const ciSel = byId("ciSelect");
  if (!modeSel || !ciSel) return;
  const mode = Number(modeSel.value);
  const forceFuzzy = mode === 2 || mode === 5;
  for (const opt of ciSel.options) {
    opt.disabled = forceFuzzy && opt.value !== "0";
  }
  if (forceFuzzy) {
    ciSel.value = "0";
  } else if (ciSel.value === "0") {
    // User coming back from mode 2/5 -- reset to the standard default.
    ciSel.value = "0.5";
  }
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
  return PURE.modelWarnings({
    provider: byId("providerSelect").value || state.modelMeta.active_provider || "gemini",
    selected: byId("modelSelect").value || "",
    catalog: state.modelMeta.provider_catalog || {},
    hasApiKey: Boolean(state.modelMeta.has_api_key),
    lang: state.lang,
  });
}

// Populate the Volatility + Archetype KPI cards' sub-lines with a
// library-relative rank. Silently no-ops when the library has fewer
// than 2 entries (ranking against oneself isn't informative).
function applyLibraryRanking(summary, dist) {
  if (!dist || !dist.metrics) return;
  const total = Number(dist.machines_count || 0);
  if (total < 2) return;
  const ga = (summary || {}).guideline_assessment || {};
  const derived = ga.derived_metrics || {};
  const cls = ga.classification || {};
  const hit = ((summary || {}).player_impact || {}).hit_and_payout || {};
  const streaks = ((summary || {}).player_impact || {}).streaks || {};

  // Volatility: rank the composite score against the library.
  const zeroWin = hit.zero_win_rate;
  const tailDep = derived.tail_dependency_ge10x ?? derived.tail_dependency;
  const lossP95 = streaks.loss_streak_p95;
  if (zeroWin != null && tailDep != null && lossP95 != null) {
    const score = Math.max(
      Number(zeroWin) / 0.82,
      Number(lossP95) / 18.0,
      Number(tailDep) / 0.50
    );
    const values = ((dist.metrics || {}).volatility_score || {}).values || [];
    const rank = PURE.computeLibPercentile(score, values);
    const sub = PURE.formatLibRank(rank, state.lang);
    const el = byId("kpiVolatilitySub");
    if (el) el.textContent = sub || "";
  }

  // Archetype: categorical -- show how common the label is.
  const currentArchetype = cls.experience_archetype;
  if (currentArchetype && dist.archetype_counts) {
    const count = Number(dist.archetype_counts[currentArchetype] || 0);
    const el = byId("kpiArchetypeSub");
    if (el) el.textContent = fmt("archetypeShare", { count, total });
  }
}

function readRunPayload() {
  return {
    machine: byId("machineSelect").value,
    mode: Number(byId("modeSelect").value),
    target_halfwidth_pp: Number(byId("ciSelect").value),
    chunk_spin_times: Number(byId("spinInput").value),
    chunk_robot_count: Number(byId("robotInput").value),
    batch_concurrency: Number(byId("concInput").value),
    max_chunks: Number(byId("maxChunksInput").value),
    timeout: Number(byId("timeoutInput").value),
    bankruptcy_session_spins: Number(byId("bankSessionInput").value),
    bankruptcy_bankroll_multipliers: byId("bankMultSelect").value,
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

// Refresh the stale-report banner above 机台概览. Hidden when zero
// stale; otherwise shows analyzer-stale count (with "一键重生成"
// button that batch-submits the fixable items) + rawdata-stale count
// as a separate line (no auto-fix — operator must resample).
async function refreshStaleBanner() {
  const banner = byId("staleReportBanner");
  if (!banner) return;
  let body;
  try {
    body = await apiGet("/api/reports/stale-count");
  } catch (_err) {
    banner.classList.add("hidden");
    return;
  }
  state.staleCount = body;
  const staleAnalyzer = body.stale_analyzer || 0;
  const staleRawdata = body.stale_rawdata || 0;
  const fixable = body.fixable_count || 0;
  if (staleAnalyzer === 0 && staleRawdata === 0) {
    banner.classList.add("hidden");
    banner.innerHTML = "";
    return;
  }
  banner.classList.remove("hidden");
  const lines = [];
  if (staleAnalyzer > 0) {
    lines.push(
      `<div class="stale-banner-row">` +
      `<span>${fmt("staleBannerAnalyzer", { n: staleAnalyzer })}</span>` +
      (fixable > 0
        ? `<button id="regenerateStaleBtn" class="primary-btn small-btn">${fmt("btnRegenerateStale", { n: fixable })}</button>`
        : "") +
      `</div>`
    );
  }
  if (staleRawdata > 0) {
    lines.push(
      `<div class="stale-banner-row">${fmt("staleBannerRawdata", { n: staleRawdata })}</div>`
    );
  }
  banner.innerHTML = lines.join("");
  byId("regenerateStaleBtn")?.addEventListener("click", async () => {
    const items = body.fixable_items || [];
    if (!items.length) return;
    const panel = byId("batchGenerateProgressPanel");
    const meta = byId("batchGenerateProgressMeta");
    const log = byId("batchGenerateProgressLog");
    if (panel) panel.classList.remove("hidden");
    if (log) log.innerHTML = "";
    try {
      const resp = await fetch("/api/rawdata/batch-generate-report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items }),
      });
      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP ${resp.status}`);
      }
      const out = await resp.json();
      state.batchGenerateId = out.batch_id;
      state.batchGenerateProgress = { total: out.total, completed: 0, failed: 0, pending: out.total };
      if (meta) meta.textContent = fmt("batchGenerateBusy", { done: 0, total: out.total });
      updateActionStates();
      _startBatchGeneratePoll();
    } catch (err) {
      if (meta) meta.textContent = fmt("batchGenerateFailed", { error: String(err.message || err) });
    }
  });
}

// Poll the active batch-generate-report every 1s until it reaches a
// terminal state, updating inline progress + refreshing runs/reports
// once done so the new gen_* rows + report versions land in the UI
// without a manual refresh.
function _startBatchGeneratePoll() {
  if (state.batchGeneratePollTimer) clearInterval(state.batchGeneratePollTimer);
  state.batchGeneratePollTimer = setInterval(async () => {
    if (!state.batchGenerateId) {
      clearInterval(state.batchGeneratePollTimer);
      state.batchGeneratePollTimer = null;
      return;
    }
    try {
      const body = await apiGet(`/api/rawdata/batch-generate-report/${encodeURIComponent(state.batchGenerateId)}`);
      state.batchGenerateProgress = body;
      const meta = byId("batchGenerateProgressMeta");
      const log = byId("batchGenerateProgressLog");
      if (meta) {
        const statusText = (body.status === "running" || body.status === "pending")
          ? fmt("batchGenerateBusy", { done: body.completed, total: body.total })
          : fmt("batchGenerateDone", { done: body.completed, total: body.total, failed: body.failed });
        meta.textContent = statusText;
      }
      if (log) {
        log.innerHTML = (body.items || []).map((it) => {
          const icon = it.status === "completed" ? "✓"
            : it.status === "failed" ? "✗"
            : it.status === "running" ? "…"
            : "·";
          const detail = it.status === "completed"
            ? ` RTP=${it.rtp_point_pct != null ? Number(it.rtp_point_pct).toFixed(2) + "%" : "?"} · CI=±${it.achieved_halfwidth_pp != null ? Number(it.achieved_halfwidth_pp).toFixed(3) + "pp" : "?"} · ${it.chunks_processed || 0} chunks`
            : it.status === "failed"
            ? ` — ${(it.error || "?").substring(0, 120)}`
            : "";
          return `<div class="batch-gen-item batch-gen-${it.status}">${icon} ${it.machine} mode ${it.mode}${detail}</div>`;
        }).join("");
      }
      if (body.status === "completed" || body.status === "partial" || body.status === "failed") {
        clearInterval(state.batchGeneratePollTimer);
        state.batchGeneratePollTimer = null;
        state.batchGenerateId = null;
        await refreshRunList(false);
        // Re-scan fleet staleness — the generated runs should flip
        // analyzer-stale → fresh, shrinking the banner.
        refreshStaleBanner();
        updateActionStates();
      }
    } catch (_err) {
      // transient; next tick retries
    }
  }, 1000);
}

async function refreshCurrentRun() {
  if (!state.currentRunId) {
    setLoadedMachineInfo(null);
    renderLiveStatusStrip();
    updateActionStates();
    return;
  }
  let run;
  try {
    run = await apiGet(`/api/runs/${state.currentRunId}`);
  } catch (err) {
    const msg = String(err?.message || "");
    if (msg.includes("404")) {
      // Stale currentRunId (run was deleted) — clear and keep going.
      state.currentRunId = "";
      state.currentRunStatus = "";
      setLoadedMachineInfo(null);
      renderLiveStatusStrip();
      updateActionStates();
      return;
    }
    // Transient network error (e.g. "Failed to fetch" during a page
    // reload race, or a brief backend hiccup). Don't let it bubble up
    // through loadBootstrap → setHealth(false): the next poll tick
    // (4.5s) will retry, and the rest of the UI is already populated.
    console.warn("refreshCurrentRun: transient, skipping —", msg);
    setLoadedMachineInfo(null);
    renderLiveStatusStrip();
    updateActionStates();
    return;
  }
  const prevStatus = state.currentRunStatus;
  state.currentRunStatus = run.status || "";
  // If status flipped relative to last poll, re-evaluate fast polling.
  if (prevStatus !== state.currentRunStatus) ensureFastPolling();

  const p = run.progress || {};
  const latest = p.latest_event || {};
  const hw = latest.current_halfwidth_pp;
  const target = run.target_halfwidth_pp;
  // target_halfwidth_pp == 0 in DB means the user picked the fuzzy tier
  // (backend rewrites to 999 for the analyzer; the DB still has 0).
  const isFuzzy = Number(target) === 0;
  const maxChunks = Number(run.max_chunks || state.lastSubmittedMaxChunks || 0);
  const pct = PURE.computeRunProgressPct(latest, {
    isFuzzy,
    maxChunks,
  });
  const summaryLine = PURE.summarizeRunEvent(state.lang, latest && latest.event ? latest : null, {
    isFuzzy,
    maxChunks,
    target,
  });
  setLoadedMachineInfo(run, summaryLine);
  // Mirror the run summary into the topbar live-status strip. While the
  // run is active we show summarizeRunEvent + a mini progress bar; once
  // the run leaves "running" the strip falls back to the idle brief on
  // the next refresh tick (handled by renderLiveStatusStrip's idle path).
  if (String(state.currentRunStatus || "").toLowerCase() === "running") {
    renderLiveStatusStrip({ summary: summaryLine, pct });
  } else {
    renderLiveStatusStrip();
  }
  setKpi("kpiRtp", latest.current_rtp_pct != null ? `${fNum(latest.current_rtp_pct)}%` : "N/A");
  setKpi("kpiCi", hw != null ? fNum(hw) : "N/A");
  setKpi("kpiSpins", latest.total_spins != null ? fInt(latest.total_spins) : "N/A");

  const events = (await apiGet(`/api/runs/${state.currentRunId}/progress`)).events || [];
  byId("eventsText").textContent = events.length ? events.slice(-80).map((e) => JSON.stringify(e)).join("\n") : fmt("noEvents");

  // Per-run failures / cancellations are shown inside runMeta (above).
  // Global warning area stays reserved for system + model notices.
  const warnings = modelWarnings();

  // "completed" (ran to CI / max_chunks) and "cancelled" (graceful
  // Stop with partial data) both have a readable summary. Show the
  // full panel stack in either case; the status badge / topbar
  // already distinguishes the two so the operator sees which path
  // produced the data.
  if (run.status === "completed" || run.status === "cancelled") {
    const report = await apiGet(`/api/runs/${state.currentRunId}/report`);
    const s = report.summary || {};
    state.latestSummary = s;
    renderAssessment(s);
    // Drive all 12 KPI cards from a single pure helper so tone classification
    // stays in one place (testable without DOM).
    const cards = PURE.extractMetricCards(s);
    const kpiBindings = [
      ["kpiRtp", "rtp"], ["kpiCi", "ci"], ["kpiSpins", "spins"],
      ["kpiZero", "zeroWin"], ["kpiGuide", "guideline"],
      ["kpiVolatility", "volatility", "kpiVolatilitySub"],
      ["kpiArchetype", "archetype", "kpiArchetypeSub"],
      ["kpiLossStreak", "lossStreak"], ["kpiMaxReturn", "maxReturn"],
      ["kpiBigWin", "bigWin"], ["kpiBankruptX500", "bankruptX500"],
    ];
    for (const binding of kpiBindings) {
      const [domId, key, subId] = binding;
      const c = cards[key] || { value: "N/A", tone: "neutral" };
      setKpi(domId, c.value, c.tone);
      // Optional sub-line (e.g. tail-dep breakdown ≥20/50/100). Cleared
      // when no sub data is available so the card doesn't show stale
      // text from a prior summary.
      if (subId) {
        const subEl = byId(subId);
        if (subEl) subEl.textContent = c.sub || "";
      }
    }
    // Tail dependency 2×2 grid (uniform, no emphasis on ≥10x).
    const tailGrid = byId("kpiTailGrid");
    if (tailGrid) {
      const td = cards.tailDep || {};
      const dm = s.guideline_assessment?.derived_metrics || {};
      const fmt1 = (v) => v == null ? "\u2014" : (Number(v) * 100).toFixed(1) + "%";
      const tone = td.tone || "neutral";
      tailGrid.innerHTML =
        `<div class="tail-cell"><em>\u226510x</em><b>${fmt1(dm.tail_dependency_ge10x)}</b></div>` +
        `<div class="tail-cell"><em>\u226520x</em><b>${fmt1(dm.tail_dependency_ge20x)}</b></div>` +
        `<div class="tail-cell"><em>\u226550x</em><b>${fmt1(dm.tail_dependency_ge50x)}</b></div>` +
        `<div class="tail-cell"><em>\u2265100x</em><b>${fmt1(dm.tail_dependency_ge100x)}</b></div>`;
      const card = tailGrid.closest(".kpi");
      if (card) {
        card.classList.remove("kpi--good", "kpi--warn", "kpi--bad");
        if (tone === "good" || tone === "warn" || tone === "bad") card.classList.add(`kpi--${tone}`);
      }
    }
    // Across-library ranking: Volatility + Archetype cards get a
    // lib-rank sub-line ("全库 P87 (15/17)" or "{count}/{total} share
    // this archetype"). Pulled lazily per summary load -- hundreds of
    // machines is still a sub-second fetch and skipping it silently
    // on error keeps the panel working when the library is empty.
    try {
      const dist = await apiGet("/api/library/distributions");
      state.libraryDistributions = dist;
      applyLibraryRanking(s, dist);
    } catch (_err) {
      // Non-fatal: leave sub-lines cleared.
    }
    // Bucket distribution: table-based (replaces Chart.js canvas).
    const buckets = s.player_impact?.multiplier_profile?.buckets || [];
    const bucketBody = byId("bucketTable")?.querySelector("tbody");
    if (bucketBody) {
      const maxRtp = Math.max(...buckets.map((b) => Number(b.rtp_contribution_pp || 0)), 0.001);
      bucketBody.innerHTML = buckets
        .map((b) => {
          const count = fInt(b.spin_count);
          const spinPct = (Number(b.spin_rate || 0) * 100).toFixed(2);
          const rtpPp = Number(b.rtp_contribution_pp || 0).toFixed(2);
          const bar = Math.min(100, (Number(b.rtp_contribution_pp || 0) / maxRtp) * 100);
          return (
            `<tr>` +
            `<td>${PURE.prettyBucketLabel(b.bucket)}</td>` +
            `<td>${count}</td>` +
            `<td>${spinPct}%</td>` +
            `<td>${rtpPp}pp</td>` +
            `<td class="bar-cell" style="--bar:${bar.toFixed(1)}%"></td>` +
            `</tr>`
          );
        })
        .join("");
    }
    renderRtpClampWarning(s);
    renderSpinTypeBreakdown(s);
    renderFeatureBreakdownPanel(s);
    // Classifier panel needs its own API call; fire-and-forget so the
    // rest of the debug tab isn't blocked on a second network round-
    // trip. Hidden automatically when the classifier output doesn't
    // cover this machine.
    renderPaylineClassification(s);
    renderPaytableShape(s);
    renderFieldDiscovery(s);
    renderMachineMechanics(s);
    renderBonusChainDynamicsPanel(s);
    renderCollectCyclePanel(s);
    renderPaylineDrilldown(s);
    renderPayoutGroupDrilldown(s);
    renderSymbolDrilldown(s);
    await refreshInterpretation();
  }
  warnings.push(...collectSystemWarnings());
  setGlobalWarning([...new Set(warnings)]);
  updateActionStates();
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
  // Pick the first catalog-selected machine for tuning. Different
  // machines have different optimal (robot_count, concurrency); we
  // apply the tuned values to the WHOLE batch as a pragmatic
  // simplification — tuning per-machine is N × autotune wall time.
  const selected = [...state.runFilterMachines];
  if (!selected.length) {
    alert(fmt("autotuneNeedsMachine"));
    return;
  }
  const machine = selected[0];
  const mode = Number(byId("sampleMode")?.value || 1);
  const cacheKey = `${machine}|${mode}`;
  const prev = state.tunedSamplingParams[cacheKey];

  state.autoTuneRunning = true;
  updateActionStates();
  // First click: 3 robots × 3 concs = 9 candidates (compact grid).
  // Subsequent clicks: refine ±6 robots / ±1 concurrency around the
  // previously tuned values. Backend does per-robot early-exit on
  // success_rate < threshold so wall time stays bounded.
  const robotCandidates = prev
    ? [...new Set([prev.robot_count - 6, prev.robot_count, prev.robot_count + 6]
        .map((x) => Math.max(4, x)).filter((x) => x <= 200))]
    : [8, 16, 24];
  const concurrencyCandidates = prev
    ? [...new Set([Math.max(1, prev.batch_concurrency - 1), prev.batch_concurrency, prev.batch_concurrency + 1]
        .filter((x) => x >= 1 && x <= 16))]
    : [1, 2, 4];
  const payload = {
    machine,
    mode,
    spin_times: 120,
    robot_candidates: robotCandidates,
    concurrency_candidates: concurrencyCandidates,
    rounds: 1,
    timeout: 45,
    bet: 1000,
  };
  const autoEl = byId("autotuneMeta");
  if (autoEl) {
    autoEl.classList.remove("hidden");
    autoEl.textContent = `machine=${machine} mode=${mode}\nrobots=[${robotCandidates.join(",")}]\nconc=[${concurrencyCandidates.join(",")}]\n${fmt("autotuneProgressStarting")}`;
  }
  startAutotunePolling();
  try {
    const r = await apiPost("/api/autotune", payload);
    const rec = r.recommendation || {};
    if (rec.chunk_robot_count != null && rec.batch_concurrency != null) {
      state.tunedSamplingParams[cacheKey] = {
        robot_count: Number(rec.chunk_robot_count),
        batch_concurrency: Number(rec.batch_concurrency),
        success_rate: Number(r.best?.success_rate || 0),
        throughput: Number(r.best?.throughput_spins_per_sec || 0),
        tuned_at: new Date().toISOString(),
      };
      _saveSamplingPrefs();  // persist the cache across page reloads
    }
    const rows = (r.results || []).slice(0, 8).map((x, i) =>
      `${i + 1}. robot=${x.robot_count} conc=${x.batch_concurrency} success=${fRate(x.success_rate, 1)} throughput=${fNum(x.throughput_spins_per_sec, 2)} p95=${fNum(x.p95_latency_s, 3)}s`
    );
    if (autoEl) {
      autoEl.textContent = (
        `machine=${machine} mode=${mode} · tested=${r.tested}\n` +
        `→ 推荐 robot_count=${rec.chunk_robot_count} batch_concurrency=${rec.batch_concurrency}` +
        `  (success=${fRate(r.best?.success_rate, 1)}, throughput=${fNum(r.best?.throughput_spins_per_sec, 2)} spins/s)\n` +
        `下次点「开始采样」将自动使用这组值\n\n` +
        rows.join("\n")
      );
    }
    updateSampleHint();
    if (Number(r.best?.success_rate || 0) < 0.95) {
      setGlobalWarning([...modelWarnings(), fmt("warnAutoTuneLowSuccess", { rate: fRate(r.best?.success_rate, 1) })]);
    }
  } finally {
    state.autoTuneRunning = false;
    stopAutotunePolling();
    updateActionStates();
  }
}

function startAutotunePolling() {
  if (state.autotuneTimer != null) return;
  const tick = async () => {
    try {
      const progress = await apiGet("/api/autotune/progress");
      // Don't overwrite the final formatted result the POST handler wrote;
      // only overwrite while the autotune is still in flight on the server.
      if (progress && (progress.status === "running" || progress.status === "starting")) {
        const head = byId("autotuneMeta").textContent.split("\n").slice(0, 3).join("\n");
        byId("autotuneMeta").textContent = `${head}\n${PURE.formatAutotuneProgress(state.lang, progress)}`;
      }
    } catch (_e) { /* keep polling silently on transient errors */ }
  };
  tick();  // first tick immediately so user sees state quickly
  state.autotuneTimer = setInterval(tick, 1000);
}

function stopAutotunePolling() {
  if (state.autotuneTimer != null) {
    clearInterval(state.autotuneTimer);
    state.autotuneTimer = null;
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
  const [h, m, models, mSummary, versions] = await Promise.all([
    apiGet("/api/health"),
    apiGet("/api/machines"),
    apiGet("/api/models"),
    apiGet("/api/machines/summary").catch(() => null),
    // Current analyzer + per-machine md5 fingerprints drive the
    // Run History staleness badges; fetched once per bootstrap and
    // cached in state — these change only when code is reloaded or
    // machines.json is refreshed, both of which already reload.
    apiGet("/api/versions/current").catch(() => null),
  ]);
  setHealth(Boolean(h.ok), h.ts || "");
  state.machines = m.machines || [];
  state.modelMeta = models || {};
  state.machinesSummary = mSummary;
  state.currentVersions = versions || { analyzer_version: "", machines: {} };
  fillMachineModeSelectors();
  fillCiTierOptions();
  fillBankMultOptions();
  fillProviders();
  fillModelsForProvider(byId("providerSelect").value, state.modelMeta.default_model || "");
  renderCatalogFeatureChips();
  renderMachineCatalog();
  renderFleetOverview();
  refreshStaleBanner();  // don't await — non-blocking for bootstrap
  _restoreSamplingPrefs();  // hydrate sampleMode/sampleCi from localStorage
  updateSampleHint();
  refreshDiskSpace();
  // Recover activeBatchId from server if a batch is still running;
  // resumes polling + hides 开始采样 so user doesn't click again.
  _recoverActiveSampling();
  await refreshServers();
  // Now that machineSelect is populated, seed the topbar idle brief.
  // (applyI18n() ran before bootstrap when machineSelect was empty, so
  // its renderLiveStatusStrip() call was a no-op.)
  renderLiveStatusStrip();
  setLoadedMachineInfo(null);
  byId("assessment").textContent = fmt("noReport");
  byId("interpretationText").textContent = fmt("noInterpret");
  byId("eventsText").textContent = fmt("noEvents");
  const autotuneMetaEl = byId("autotuneMeta");
  if (autotuneMetaEl) autotuneMetaEl.textContent = fmt("noAutoTune");
  await refreshSystemState();
  await refreshCache();
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
    fillCiTierOptions();
    fillBankMultOptions();
    renderMachineCatalog();
    renderRunHistory();
    setSystemStatePanel();
    await refreshCache().catch(() => {});
    await refreshSystemState().catch(() => {});
    if (state.currentRunId) {
      await refreshCurrentRun().catch(() => {});
    } else {
      setLoadedMachineInfo(null);
      byId("assessment").textContent = fmt("noReport");
      byId("interpretationText").textContent = fmt("noInterpret");
      byId("eventsText").textContent = fmt("noEvents");
      byId("autotuneMeta").textContent = fmt("noAutoTune");
    }
    updateActionStates();
  });
  byId("tabBtnDebug").addEventListener("click", () => switchTab("debug"));
  byId("tabBtnManage").addEventListener("click", () => switchTab("manage"));
  // Mobile drawer: hamburger toggles the sidebar on/off; tapping the
  // dimmed backdrop (anywhere inside .dashboard that isn't the sidebar
  // or the toggle itself) closes it. CSS hides .sidebar-toggle above
  // 1120px so this never fires on the desktop e2e path.
  const sidebarToggle = byId("sidebarToggle");
  if (sidebarToggle) {
    sidebarToggle.addEventListener("click", (e) => {
      e.stopPropagation();
      document.querySelector(".dashboard")?.classList.toggle("sidebar-open");
    });
  }
  document.querySelector(".dashboard")?.addEventListener("click", (e) => {
    const dashboard = document.querySelector(".dashboard");
    if (!dashboard?.classList.contains("sidebar-open")) return;
    const sidebar = document.querySelector(".dash-sidebar");
    if (sidebar?.contains(e.target) || (sidebarToggle && sidebarToggle.contains(e.target))) return;
    dashboard.classList.remove("sidebar-open");
  });
  _initCatalogDelegation();
  byId("catalogSearch").addEventListener("input", () => renderMachineCatalog());
  byId("catalogSortReverse").addEventListener("click", (e) => {
    state.catalogSortReverse = !state.catalogSortReverse;
    e.currentTarget.classList.toggle("active", state.catalogSortReverse);
    renderMachineCatalog();
  });
  byId("catalogCollapseAll").addEventListener("click", () => {
    const groups = document.querySelectorAll(".catalog-group");
    const allCollapsed = [...groups].every((g) => g.classList.contains("collapsed"));
    groups.forEach((g) => {
      g.classList.toggle("collapsed", !allCollapsed);
      const arrow = g.querySelector(".catalog-group-arrow");
      if (arrow) arrow.innerHTML = allCollapsed ? "&#9660;" : "&#9654;";
    });
  });
  byId("catalogClearSelection").addEventListener("click", () => {
    state.runFilterMachines.clear();
    renderMachineCatalog();
    renderRunHistory();
    byId("versionHistoryPanel")?.classList.add("hidden");
    byId("reportComparisonPanel")?.classList.add("hidden");
    byId("machineDetailPanel")?.classList.add("hidden");
  });
  // Select-all: add every machine currently visible in the catalog
  // (honors current view-mode + feature-chip filter + search) to the
  // multi-select set. Intentionally scoped to the filtered view so
  // users don't accidentally select 253 machines when they meant the
  // 10 visible after a filter.
  byId("catalogSelectAllVisible")?.addEventListener("click", () => {
    const visible = document.querySelectorAll("#machineCatalog .catalog-item");
    visible.forEach((el) => {
      const m = el.dataset.machine;
      if (m) state.runFilterMachines.add(m);
    });
    renderMachineCatalog();
    renderRunHistory();
    updateSampleHint();
    updateActionStates();
  });
  // View tabs for catalog grouping mode.
  byId("catalogViewTabs").addEventListener("click", async (e) => {
    const btn = e.target.closest(".view-tab");
    if (!btn) return;
    state.catalogViewMode = btn.dataset.view;
    byId("catalogViewTabs").querySelectorAll(".view-tab").forEach((b) => b.classList.toggle("active", b === btn));
    renderCatalogFeatureChips();
    // First click on "按大厅" lazily fetches the cached hall map.
    if (btn.dataset.view === "hall" && state.machineHalls === null) {
      try {
        state.machineHalls = await apiGet("/api/machines/halls");
      } catch (_err) {
        state.machineHalls = { halls: {}, updated_at: null, source: null };
      }
    }
    renderHallsRefreshBar();
    renderMachineCatalog();
  });

  // Inline hall-refresh banner: visible only when 按大厅 tab active.
  function renderHallsRefreshBar() {
    const bar = byId("hallsRefreshBar");
    if (!bar) return;
    if (state.catalogViewMode !== "hall") {
      bar.classList.add("hidden");
      return;
    }
    bar.classList.remove("hidden");
    const halls = state.machineHalls?.halls || {};
    const hallCount = Object.keys(halls).length;
    const updated = state.machineHalls?.updated_at;
    if (!hallCount) {
      bar.innerHTML = `<span class="muted">${fmt("hallsEmpty")}</span>
        <button id="hallsRefreshBtn" class="small-btn primary-btn">${fmt("hallsRefreshBtn")}</button>`;
    } else {
      const machineCount = Object.values(halls).reduce((s, v) => s + (v?.length || 0), 0);
      bar.innerHTML = `<span class="muted">${fmt("hallsRefreshSuccess", { halls: hallCount, machines: machineCount, ts: updated || "?" })}</span>
        <button id="hallsRefreshBtn" class="small-btn">${fmt("hallsRefreshBtn")}</button>`;
    }
    byId("hallsRefreshBtn")?.addEventListener("click", async () => {
      const btn = byId("hallsRefreshBtn");
      if (!btn) return;
      const orig = btn.textContent;
      btn.disabled = true;
      btn.textContent = fmt("hallsRefreshBusy");
      try {
        const resp = await fetch("/api/machines/halls/refresh", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${resp.status}`);
        }
        const data = await resp.json();
        state.machineHalls = {
          halls: data.halls || {},
          updated_at: data.updated_at,
          source: data.source,
        };
        renderHallsRefreshBar();
        renderMachineCatalog();
      } catch (err) {
        btn.textContent = fmt("hallsRefreshFailed", { error: String(err.message || err) });
        setTimeout(() => { btn.disabled = false; btn.textContent = orig; }, 4000);
      }
    });
  }
  // Inline sampling panel controls.
  byId("sampleStartBtn").addEventListener("click", () => startSampling());
  byId("sampleCancelBtn").addEventListener("click", () => cancelSampling());
  byId("sampleMode").addEventListener("change", () => { updateSampleHint(); _saveSamplingPrefs(); });
  byId("sampleCi").addEventListener("change", () => { updateSampleHint(); _saveSamplingPrefs(); });
  byId("addServerBtn").addEventListener("click", () => addServer());
  byId("refreshMd5Btn").addEventListener("click", async () => {
    const btn = byId("refreshMd5Btn");
    btn.disabled = true;
    btn.textContent = "拉取中…";
    try {
      const r = await apiPost("/api/machines/refresh-md5", { server_id: "dev" });
      alert(`刷新完成：拉取 ${r.machines_fetched} 台，${r.machines_updated} 台 MD5 变更`);
      // Re-fetch machines + summary to refresh UI with new MD5 comparison.
      const [m, mSummary] = await Promise.all([apiGet("/api/machines"), apiGet("/api/machines/summary").catch(() => null)]);
      state.machines = m.machines || [];
      state.machinesSummary = mSummary;
      renderCatalogFeatureChips();
      renderMachineCatalog();
      renderFleetOverview();
    } catch (e) {
      alert("刷新失败：" + (e.message || e));
    } finally {
      btn.disabled = false;
      btn.textContent = "刷新机台 MD5";
    }
  });
  byId("importReportsBtn").addEventListener("click", async () => {
    const source = prompt("输入 Reports 源目录绝对路径（如 D:\\\\dev_reports 或 /path/to/dev_reports）:");
    if (!source) return;
    const mode = confirm("合并模式？\n[确定] 合并（跳过已存在）\n[取消] 替换（删除目标后导入）") ? "merge" : "replace";
    try {
      const r = await apiPost("/api/reports/import", { source_path: source, mode });
      alert(`导入完成：新增 ${r.imported} 个版本，跳过 ${r.skipped} 个。\n影响机台：${r.machines_affected.join(", ") || "无"}`);
      // Refresh UI
      const [m, mSummary] = await Promise.all([apiGet("/api/machines"), apiGet("/api/machines/summary").catch(() => null)]);
      state.machines = m.machines || [];
      state.machinesSummary = mSummary;
      renderCatalogFeatureChips();
      renderMachineCatalog();
      renderFleetOverview();
    } catch (e) {
      alert("导入失败：" + (e.message || e));
    }
  });
  byId("reportCleanupBtn").addEventListener("click", async () => {
    if (!confirm(fmt("reportCleanupConfirm"))) return;
    const btn = byId("reportCleanupBtn");
    const result = byId("reportCleanupResult");
    btn.disabled = true;
    result.textContent = "...";
    try {
      const data = await apiPost("/api/reports/cleanup");
      result.textContent = fmt("reportCleanupDone", { deleted: data.deleted, kept: data.kept });
      // Refresh catalog to update report counts.
      const [m, mSummary] = await Promise.all([apiGet("/api/machines"), apiGet("/api/machines/summary").catch(() => null)]);
      state.machines = m.machines || [];
      state.machinesSummary = mSummary;
      renderCatalogFilters();
      renderMachineCatalog();
      renderFleetOverview();
    } catch (e) {
      result.textContent = String(e.message || e);
    } finally {
      btn.disabled = false;
    }
  });
  byId("compareServersBtn").addEventListener("click", () => compareServers());
  byId("compareBtn").addEventListener("click", () => compareReports());
  // machineSelect / modeSelect / ciSelect were on the old sidebar and
  // are gone after the UI simplification. Sampling now runs from the
  // manage tab's 采样选中机台 panel which uses sampleMode / sampleCi.
  byId("providerSelect")?.addEventListener("change", () => (fillModelsForProvider(byId("providerSelect").value), setGlobalWarning(modelWarnings())));
  byId("modelSelect")?.addEventListener("change", () => setGlobalWarning(modelWarnings()));
  byId("saveModelCfgBtn")?.addEventListener("click", () =>
    withAction("save_model", async () => {
      state.modelMeta = await apiPost("/api/model-config", { provider: byId("providerSelect").value, api_key: byId("apiKeyInput").value || "" });
      byId("apiKeyInput").value = "";
      fillProviders();
      fillModelsForProvider(byId("providerSelect").value, state.modelMeta.default_model || "");
      setGlobalWarning(modelWarnings());
    }).catch((e) => alert(String(e.message || e)))
  );
  // startBtn / stopBtn / refreshBtn were on the old sidebar and are
  // removed. Sampling is initiated exclusively from the manage tab's
  // 采样选中机台 panel via sampleStartBtn (below).
  byId("autotuneBtn")?.addEventListener("click", () =>
    withAction("autotune", runAutoTune).catch((e) => alert(String(e.message || e)))
  );
  byId("interpretBtn")?.addEventListener("click", () =>
    withAction("interpret", generateInterpretation).catch((e) => alert(String(e.message || e)))
  );
  // rebuildBtn moved to manage-tab per-row (renderRunHistory).
  byId("cacheRefreshBtn")?.addEventListener("click", () =>
    withAction("cache_refresh", refreshCache).catch((e) => alert(String(e.message || e)))
  );
  byId("cacheCleanupBtn")?.addEventListener("click", () =>
    withAction("cache_cleanup", async () => {
      if (!(await confirmCacheCleanup())) return;
      await apiPost("/api/cache/cleanup", { max_delete_bytes: 0 });
      await refreshCache();
    }).catch((e) => alert(String(e.message || e)))
  );

  // System settings: load current value on page init, save via PUT
  // on button click. Kept inline rather than a separate fetch/render
  // function because it's one scalar — a function would be overkill.
  (async () => {
    try {
      const current = await apiGet("/api/settings");
      const input = byId("settingMinRetention");
      if (input && current && typeof current.min_retention_spins === "number") {
        input.value = String(current.min_retention_spins);
      }
    } catch (_err) {
      // Non-fatal: defaults to placeholder value 100000 in the HTML.
    }
  })();
  byId("saveSettingsBtn")?.addEventListener("click", async () => {
    const meta = byId("settingsSaveMeta");
    try {
      const value = Number(byId("settingMinRetention").value);
      if (!Number.isFinite(value) || value < 0) {
        if (meta) meta.textContent = fmt("settingsSaveError", {
          error: "value must be a non-negative integer",
        });
        return;
      }
      const resp = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ min_retention_spins: Math.trunc(value) }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${resp.status}`);
      }
      const saved = await resp.json();
      if (meta) meta.textContent = fmt("settingsSaved", { value: saved.min_retention_spins });
    } catch (err) {
      if (meta) meta.textContent = fmt("settingsSaveError", { error: String(err.message || err) });
    }
  });

  // Batch Generate Report: kick off a sequential rebuild for every
  // selected machine at the current sampleMode. Progress polls the
  // batch endpoint every 1s while in flight.
  byId("batchGenerateBtn")?.addEventListener("click", async () => {
    const selected = [...(state.runFilterMachines || [])];
    if (!selected.length) {
      alert(fmt("batchGenerateNoSelection"));
      return;
    }
    const mode = Number(byId("sampleMode")?.value || 1);
    const items = selected.map((m) => ({ machine: m, mode }));
    const panel = byId("batchGenerateProgressPanel");
    const meta = byId("batchGenerateProgressMeta");
    const log = byId("batchGenerateProgressLog");
    if (panel) panel.classList.remove("hidden");
    if (log) log.innerHTML = "";
    try {
      const resp = await fetch("/api/rawdata/batch-generate-report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${resp.status}`);
      }
      const body = await resp.json();
      state.batchGenerateId = body.batch_id;
      state.batchGenerateProgress = { total: body.total, completed: 0, failed: 0, pending: body.total };
      if (meta) meta.textContent = fmt("batchGenerateBusy", { done: 0, total: body.total });
      updateActionStates();
      _startBatchGeneratePoll();
    } catch (err) {
      if (meta) meta.textContent = fmt("batchGenerateFailed", { error: String(err.message || err) });
      if (panel) setTimeout(() => panel.classList.add("hidden"), 5000);
    }
  });

  // --- batch selection ---
  byId("selectAllRuns").addEventListener("change", (e) => {
    const checks = document.querySelectorAll("#runListTable .run-check");
    checks.forEach((cb) => {
      cb.checked = e.target.checked;
      if (cb.checked) state.selectedRuns.add(cb.dataset.id);
      else state.selectedRuns.delete(cb.dataset.id);
    });
    updateBatchBar();
  });
  byId("clearSelectionBtn").addEventListener("click", () => {
    state.selectedRuns.clear();
    document.querySelectorAll("#runListTable .run-check").forEach((cb) => (cb.checked = false));
    byId("selectAllRuns").checked = false;
    updateBatchBar();
  });
  byId("batchDeleteBtn").addEventListener("click", async () => {
    const ids = Array.from(state.selectedRuns);
    if (!ids.length) return;
    if (!window.confirm(fmt("confirmBatchDelete", { n: ids.length }))) return;
    state.busyActions.add("batch_delete");
    updateActionStates();
    let deleted = 0;
    try {
      for (const rid of ids) {
        try {
          await apiDelete(`/api/runs/${encodeURIComponent(rid)}`);
          deleted++;
          if (state.currentRunId === rid) {
            state.currentRunId = "";
            state.currentRunStatus = "";
          }
        } catch { /* skip failures silently for batch */ }
      }
      state.selectedRuns.clear();
      await refreshRunList(false);
    } finally {
      state.busyActions.delete("batch_delete");
      updateActionStates();
    }
  });
}

function startPolling() {
  // Slow tick (4.5s): system / runs list / cache. Always on.
  if (state.timer) clearInterval(state.timer);
  state.timer = setInterval(() => {
    refreshSystemState().catch(() => {});
    refreshRunList(false).catch(() => {});
    refreshCache().catch(() => {});
    if (!state.currentRunId) updateActionStates();
  }, 4500);
  // Activity strip (1.2s): unified log across all active + recent
  // runs, feeds the top panel in 机台管理 tab.
  if (state.activityTimer) clearInterval(state.activityTimer);
  state.activityTimer = setInterval(() => {
    refreshActivityStrip().catch(() => {});
  }, 1200);
  refreshActivityStrip().catch(() => {});
  // Fast tick (1s): only the active run's progress. Created/torn down by
  // ensureFastPolling() based on currentRunStatus.
  ensureFastPolling();
}

// Pull the unified event stream + render the top "活动日志流" panel.
// ``state.activitySince`` is the cursor for incremental fetch; on the
// first tick we omit it so the panel shows the last 5 min of context.
async function refreshActivityStrip() {
  const panel = byId("activityStripPanel");
  const body = byId("activityStripBody");
  const statusEl = byId("activityStripStatus");
  if (!panel || !body) return;
  let url = "/api/events?lookback_minutes=5&limit=200";
  if (state.activitySince) {
    url += `&since=${encodeURIComponent(state.activitySince)}`;
  }
  let data;
  try {
    data = await apiGet(url);
  } catch (_err) {
    return;
  }
  state.activityEvents = state.activityEvents || [];
  for (const ev of (data.events || [])) {
    state.activityEvents.push(ev);
  }
  // Cap to latest 200 events (ring buffer).
  if (state.activityEvents.length > 200) {
    state.activityEvents = state.activityEvents.slice(-200);
  }
  if (data.max_ts) state.activitySince = data.max_ts;
  const active = Array.isArray(data.active_runs) ? data.active_runs : [];
  if (active.length) {
    panel.classList.add("activity-strip-live");
    const opsLine = active
      .map((r) => `<span class="op-chip">${_escHtml(r.model_id)} · ${_escHtml(r.machine)} mode${r.mode}</span>`)
      .join("");
    statusEl.innerHTML = `🟡 ${active.length} 运行中 ${opsLine}`;
  } else {
    panel.classList.remove("activity-strip-live");
    statusEl.textContent = "idle";
  }
  // Render last 12 events newest-first.
  const recent = state.activityEvents.slice(-12).reverse();
  body.innerHTML = recent.length
    ? recent.map((ev) => {
        const tsShort = (ev.ts || "").substring(11, 19);
        const mach = ev.machine ? `${ev.machine} mode${ev.mode}` : "";
        const op = ev.model_id || "";
        const kind = ev.event || "";
        let tail = "";
        if (ev.chunks_completed != null) {
          tail += `chunks ${ev.chunks_completed}`;
          if (ev.total_spins != null) tail += ` · ${ev.total_spins.toLocaleString()} spins`;
          if (ev.current_halfwidth_pp != null)
            tail += ` · CI±${Number(ev.current_halfwidth_pp).toFixed(2)}pp`;
        } else if (ev.stop_reason) {
          tail = `stop: ${_escHtml(ev.stop_reason)}`;
        } else if (ev.error_message) {
          tail = `⚠ ${_escHtml(String(ev.error_message).substring(0, 80))}`;
        }
        const statusClass = ev.run_status === "failed" ? "ev-fail"
          : ev.event === "completed" ? "ev-ok" : "";
        return `<div class="activity-line ${statusClass}">`
          + `<span class="activity-ts">${_escHtml(tsShort)}</span>`
          + `<span class="activity-op">${_escHtml(op)}</span>`
          + `<span class="activity-mach">${_escHtml(mach)}</span>`
          + `<span class="activity-kind">${_escHtml(kind)}</span>`
          + `<span class="activity-tail">${tail}</span>`
          + `</div>`;
      }).join("")
    : `<div class="muted" style="padding:8px 4px;font-size:12px">无近期事件</div>`;
}

function ensureFastPolling() {
  const wantFast =
    state.currentRunId && String(state.currentRunStatus || "").toLowerCase() === "running";
  if (wantFast && state.fastTimer == null) {
    state.fastTimer = setInterval(() => {
      refreshCurrentRun().catch(() => {});
    }, 1000);
  } else if (!wantFast && state.fastTimer != null) {
    clearInterval(state.fastTimer);
    state.fastTimer = null;
  }
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
