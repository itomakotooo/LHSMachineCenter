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
  // Whether the currently-loaded run has cached chunks available for
  // rebuild. Updated by refreshChunkStatus() after each run load.
  currentChunksAvailable: false,
  // Latest library-wide metric distributions (from
  // GET /api/library/distributions). Drives the "lib-P{N}" suffix on
  // Volatility + Archetype KPI cards so the operator sees where the
  // current machine stands across the library.
  libraryDistributions: null,
  // Per-machine-mode best-report summary (from GET /api/machines/summary).
  // { machines: { M14: { "1": {rtp_pct, ci_halfwidth_pp, ...}, ... }, ... } }
  machinesSummary: null,
  // Active batch run state.
  activeBatchId: null,
  batchSelectedMachines: new Set(),
  servers: [],
  defaultServer: "",
  catalogViewMode: "category",  // "category" | "name" | "volatility" | "rtp" | "mechanic"
  catalogFeatureFilter: new Set(),  // selected feature chips for "按玩法" view
  versionHistoryMachine: null,
  versionHistoryMode: null,
  compareSelected: new Set(),
};

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
  byId("autotuneBtn").textContent = state.autoTuneRunning ? fmt("btnAutoTuneBusy") : fmt("btnAutoTune");
  setSystemStatePanel();
  renderCacheRiskMeta();
  updateChartLabels();
  renderLiveStatusStrip();
  if (byId("startBtn")) updateActionStates();
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
  const validation = PURE.validateRunConfig({
    mode: Number(byId("modeSelect").value),
    halfwidthPp: byId("ciSelect") ? byId("ciSelect").value : "0.5",
    robotCount: byId("robotInput").value,
    concurrency: byId("concInput").value,
    lang: state.lang,
  });

  byId("saveModelCfgBtn").disabled = localBusy || serverBusy;
  byId("startBtn").disabled = localBusy || serverBusy || anyRunRunning || !validation.canStart;
  byId("startBtn").title = validation.blocking.join(" ");
  byId("autotuneBtn").disabled = localBusy || serverBusy || anyRunRunning;
  byId("stopBtn").disabled = localBusy || serverBusy || !hasCurrent || currentStatus !== "running";
  byId("refreshBtn").disabled = localBusy || !hasCurrent;
  // Interpretation can run on any run that produced a valid summary
  // -- "completed" (hit CI target / max_chunks) OR "cancelled"
  // (graceful user stop with partial data). Not "failed" (no summary)
  // or "running".
  byId("interpretBtn").disabled = localBusy || serverBusy || !hasCurrent || (
    currentStatus !== "completed" && currentStatus !== "cancelled"
  );
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
  if (!state.autoTuneRunning) byId("autotuneMeta").textContent = fmt("noAutoTune");
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
    return `<div class="cat-mode-row"><span class="cat-mode-label">m${mode}</span> <span class="cat-rtp">${rtp}</span> <span class="cat-ci">${ci}</span> ${volHtml}${mechIcons ? ` <span class="cat-mech" title="${d.mechanics.join(', ')}">${mechIcons}</span>` : ""}</div>`;
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

  // Sort within groups: by machine number for most views.
  const numSort = (a, b) => (parseInt(a.machine.slice(1)) || 0) - (parseInt(b.machine.slice(1)) || 0);
  Object.values(groups).forEach((arr) => arr.sort(numSort));

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
      const bg = _cardBgColor(m.machine);
      if (bg) d.style.background = bg;
      const catColor = CATEGORY_COLORS[m.category] || "#9ca3af";
      d.style.borderLeftColor = catColor;
      if (state.runFilterMachines.has(m.machine)) d.classList.add("active");
      if (m.available === false) d.classList.add("unavailable");
      d.dataset.machine = m.machine;
      d.setAttribute("role", "button");
      d.setAttribute("tabindex", "0");
      const metrics = _catalogModeMetrics(m.machine);
      const reportBadge = m.report_count ? `<span class="catalog-badge" style="background:${catColor}">${m.report_count}</span>` : "";
      d.innerHTML = `<div class="catalog-title">${m.machine}${reportBadge}</div>${metrics || `<div class="catalog-modes">modes: ${(m.modes || []).join(", ")}</div>`}`;
      grid.appendChild(d);
    });
    section.appendChild(grid);
    wrap.appendChild(section);
  });

  // Click handlers — multi-select toggle.
  wrap.querySelectorAll(".catalog-item").forEach((el) => {
    const toggle = () => {
      const machine = el.dataset.machine;
      if (state.runFilterMachines.has(machine)) {
        state.runFilterMachines.delete(machine);
      } else {
        state.runFilterMachines.add(machine);
      }
      renderMachineCatalog();
      renderRunHistory();
      updateSampleHint();
      // Show detail for the last toggled machine (if selected).
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
    };
    el.addEventListener("click", toggle);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    });
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
    ${metricsHtml}`;
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

  // Hint text based on mode.
  if (hint) {
    if (mode === 2 || mode === 5) {
      hint.textContent = `Mode ${mode} 为幸运模式（RTP 高波动），仅支持 Fuzzy 采样，固定 20 chunks`;
    } else {
      const ci = parseFloat(byId("sampleCi")?.value || "0.5");
      if (ci === 0) hint.textContent = `Fuzzy 模式，固定 chunks，约 1M spins`;
      else hint.textContent = `目标 ±${ci}pp 精度，上限 10M spins`;
    }
  }

  if (btn) btn.disabled = n === 0 || !!state.activeBatchId;
}

async function startSampling() {
  const selected = [...state.runFilterMachines];
  if (!selected.length) return;
  const mode = parseInt(byId("sampleMode")?.value || "2");
  let ci = parseFloat(byId("sampleCi")?.value || "0.5");
  if (mode === 2 || mode === 5) ci = 0;

  // Build items with smart chunk size per machine (category-based initial heuristic).
  const items = selected.map((machine) => {
    const m = state.machines.find((x) => x.machine === machine);
    const cat = m?.category || "";
    let chunk_spin_times = 1000;
    if (cat === "Collect") chunk_spin_times = 5000;
    else if (cat === "Lock" || cat === "ReSpin" || cat === "FreeSpin") chunk_spin_times = 2000;
    return { machine, mode, chunk_spin_times };
  });

  // Max chunks based on mode + CI.
  let max_chunks;
  if (ci === 0) max_chunks = 20;  // fuzzy
  else {
    // Cap at 10M spins total: max_chunks * 20 robots * chunk_spin_times_avg
    const avgChunk = items.reduce((s, i) => s + i.chunk_spin_times, 0) / items.length;
    max_chunks = Math.floor(10_000_000 / (20 * avgChunk));
  }

  const payload = {
    items,
    concurrency: 2,
    chunk_spin_times: 1000,  // overridden per-item below (not yet supported, needs backend update)
    chunk_robot_count: 20,
    max_chunks,
    target_halfwidth_pp: ci,
    batch_concurrency: 2,
    timeout: 300,
    auto_cleanup_cache: true,
  };

  try {
    const result = await apiPost("/api/batch-run", payload);
    state.activeBatchId = result.batch_id;
    updateSampleHint();
    byId("sampleCancelBtn").classList.remove("hidden");
    byId("sampleStartBtn").classList.add("hidden");
    pollSampling();
  } catch (e) {
    alert(String(e.message || e));
  }
}

function pollSampling() {
  if (!state.activeBatchId) return;
  const panel = byId("sampleProgressPanel");
  if (panel) panel.classList.remove("hidden");

  const poll = async () => {
    if (!state.activeBatchId) return;
    try {
      const data = await apiGet(`/api/batch-run/${state.activeBatchId}`);
      renderSamplingProgress(data);
      refreshDiskSpace();
      if (data.status === "completed") {
        state.activeBatchId = null;
        byId("sampleCancelBtn").classList.add("hidden");
        byId("sampleStartBtn").classList.remove("hidden");
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
    setTimeout(poll, 2000);
  };
  poll();
}

function renderSamplingProgress(data) {
  const meta = byId("sampleProgressMeta");
  const log = byId("sampleProgressLog");
  if (!meta || !log) return;

  meta.textContent = `${data.completed} / ${data.total} 完成 · ${data.items.filter(i=>i.status==='running').length} 运行中`;

  // Build combined timeline: machine status summary + events log.
  const levelIcon = { info: "ℹ", warn: "⚠", ok: "✓", error: "✗", danger: "⛔" };
  const levelClass = { info: "sample-info", warn: "sample-warn", ok: "sample-completed", error: "sample-failed", danger: "sample-danger" };
  // Per-machine status rows at top.
  const statusIcon = { pending: "⏳", running: "▶", completed: "✓", failed: "✗", cancelled: "⏸" };
  const statusRows = data.items.map((it) => {
    const icon = statusIcon[it.status] || "?";
    const chunk = it.chunk_spin_times ? ` (chunk=${it.chunk_spin_times})` : "";
    const err = it.error ? ` — ${it.error.slice(0, 60)}` : "";
    return `<div class="sample-log-item sample-${it.status}">${icon} ${it.machine} m${it.mode}${chunk}${err}</div>`;
  }).join("");

  // Event log below.
  const eventRows = (data.events || []).map((ev) => {
    const icon = levelIcon[ev.level] || "·";
    const cls = levelClass[ev.level] || "";
    const machine = ev.machine ? `[${ev.machine}] ` : "";
    const ts = (ev.ts || "").slice(11, 19);
    return `<div class="sample-log-item ${cls}">${ts} ${icon} ${machine}${ev.text}</div>`;
  }).join("");

  log.innerHTML = `<div class="sample-log-section-title">机台状态</div>${statusRows}
    <div class="sample-log-section-title">事件日志 (最近 ${(data.events || []).length})</div>${eventRows}`;
  log.scrollTop = log.scrollHeight;
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
  try {
    await apiPost(`/api/batch-run/${state.activeBatchId}/cancel`);
  } catch (_) { /* ignore */ }
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
    const data = await apiGet(`/api/reports/${machine}/${mode}`);
    const versions = data.versions || [];
    if (!versions.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="muted">${fmt("noVersions")}</td></tr>`;
      return;
    }
    // Sort newest first.
    versions.sort((a, b) => (b.report_version || "").localeCompare(a.report_version || ""));
    tbody.innerHTML = versions.map((v) => {
      const rv = v.report_version || "?";
      const rtp = v.achieved_rtp_pct != null ? v.achieved_rtp_pct.toFixed(2) + "%" : "—";
      const ci = v.achieved_halfwidth_pp != null ? "\u00b1" + v.achieved_halfwidth_pp.toFixed(2) : "—";
      const spins = v.total_spins != null ? Number(v.total_spins).toLocaleString() : "—";
      const quality = v.quality_label || "—";
      return (
        `<tr data-version="${rv}">` +
        `<td><input type="checkbox" class="compare-check" value="${rv}"></td>` +
        `<td class="version-id">${rv}</td>` +
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
    body.innerHTML = `<tr><td colspan="9">${msg}</td></tr>`;
    updateBatchBar();
    return;
  }
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    if (r.run_id === state.currentRunId) tr.classList.add("active-row");
    const rtpCell = fMetricCell(r.achieved_rtp_pct, 2, "%");
    const ciCell = fMetricCell(r.achieved_halfwidth_pp, 3, "pp");
    const qualityCell = r.quality_label || "\u2014";
    const checked = state.selectedRuns.has(r.run_id) ? "checked" : "";
    tr.innerHTML =
      `<td class="td-check"><input type="checkbox" class="run-check" data-id="${r.run_id}" ${checked}></td>` +
      `<td>${r.run_id}</td>` +
      `<td>${statusText(r.status)}</td>` +
      `<td>${r.machine}</td>` +
      `<td>${r.mode}</td>` +
      `<td>${rtpCell}</td>` +
      `<td>${ciCell}</td>` +
      `<td>${qualityCell}</td>` +
      `<td class="action-cell">` +
      `<button class="load-run-btn" data-id="${r.run_id}">${fmt("btnLoadRun")}</button> ` +
      `<button class="rebuild-run-btn" data-id="${r.run_id}">${fmt("btnRebuildRun")}</button> ` +
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

  // Rebuild (per-row): checks chunk compatibility, shows inline status.
  body.querySelectorAll(".rebuild-run-btn").forEach((b) => {
    b.disabled = true;
    b.title = fmt("rebuildNoChunks");
    apiGet(`/api/runs/${encodeURIComponent(b.dataset.id)}/chunks`).then((d) => {
      if (d.available && d.compatible) {
        b.disabled = state.busyActions.size > 0;
        b.title = fmt("chunkCompatible", { count: d.chunk_count });
      } else if (d.chunk_count > 0 && !d.compatible) {
        b.disabled = true;
        b.title = fmt("rebuildIncompatible", { reason: d.incompatible_reason || "unknown" });
        b.classList.add("stale");
      }
    }).catch(() => {});
    b.addEventListener("click", async () => {
      if (state.busyActions.size > 0) return;
      const runId = b.dataset.id;
      const origText = b.textContent;
      // Disable ALL action buttons in this row during rebuild.
      const row = b.closest("tr");
      const rowButtons = row ? row.querySelectorAll("button") : [];
      rowButtons.forEach((btn) => (btn.disabled = true));
      b.textContent = fmt("rebuildBusy");
      state.busyActions.add("rebuild");
      updateActionStates();
      // Show progress in runMeta panel.
      const metaEl = byId("runMeta");
      const oldMeta = metaEl?.textContent;
      if (metaEl) metaEl.textContent = fmt("rebuildBusy") + ` (${runId})...`;
      try {
        const resp = await apiPost(`/api/runs/${encodeURIComponent(runId)}/rebuild`, {});
        b.textContent = `✓ ${resp.rtp_point_pct != null ? Number(resp.rtp_point_pct).toFixed(1) + "%" : "done"}`;
        b.classList.add("rebuild-done");
        if (metaEl) metaEl.textContent = fmt("rebuildSuccess", {
          rtp: resp.rtp_point_pct != null ? Number(resp.rtp_point_pct).toFixed(2) : "?",
          chunks: resp.chunks_reprocessed || 0,
        });
        await refreshRunList(false);
        if (state.currentRunId === runId) {
          switchTab("debug");
          await refreshCurrentRun();
        }
        setTimeout(() => { b.textContent = origText; b.classList.remove("rebuild-done"); }, 3000);
      } catch (err) {
        const errMsg = String(err && err.message ? err.message : err);
        b.textContent = "✗";
        if (metaEl) metaEl.textContent = fmt("rebuildFailed", { error: errMsg });
        setTimeout(() => { b.textContent = origText; if (metaEl && oldMeta) metaEl.textContent = oldMeta; }, 3000);
      } finally {
        state.busyActions.delete("rebuild");
        rowButtons.forEach((btn) => (btn.disabled = false));
        updateActionStates();
      }
    });
  });

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
// summary.player_impact.upstream_feature_breakdown. Hidden when the
// upstream only reports a single "Normal" feature (redundant with
// payout_ids_top20). Each feature renders as a small header + per-
// payout-id table.
function renderFeatureBreakdownPanel(summary) {
  // Renders inside #featureBreakdownInline (merged into the SpinType
  // panel) instead of a standalone section. Clears the div when not
  // applicable so the SpinType table stands alone for single-feature
  // machines.
  const body = byId("featureBreakdownInline");
  if (!body) return;
  const data = ((summary || {}).player_impact || {}).upstream_feature_breakdown;
  if (!data || !data.applicable || !Array.isArray(data.features) || !data.features.length) {
    body.innerHTML = "";
    return;
  }
  body.innerHTML =
    `<hr style="margin:14px 0;border:none;border-top:1px solid #d2dde9">` +
    `<h3 style="margin:0 0 8px;font-size:13px;color:var(--muted)">${fmt("panelFeatureBreakdown")}</h3>` +
    `<div class="feature-blocks-grid">` +
    data.features.map((feat) => {
      const rows = Array.isArray(feat.payouts) ? feat.payouts : [];
      const maxShare = Math.max(
        ...rows.map((p) => Number(p.share_of_feature_win || 0)),
        0
      );
      // Only show paying payids (skip the "-1" / zero-win catch-all).
      const payingRows = rows.filter((p) => Number(p.win_credits || 0) > 0);
      const tblRows = payingRows
        .map((p) => {
          const share = Number(p.share_of_feature_win || 0);
          const bar = maxShare > 0 ? Math.min(100, (share / maxShare) * 100) : 0;
          return (
            `<span class="feature-bar-row">` +
            `<span class="feature-bar-label">ID ${String(p.payout_id)}</span>` +
            `<span class="feature-bar-track"><span class="feature-bar" style="width:${bar.toFixed(1)}%"></span></span>` +
            `<span class="feature-bar-val">${(share * 100).toFixed(1)}%</span>` +
            `</span>`
          );
        })
        .join("");
      const rtpPp = Number(feat.rtp_contribution_pp || 0).toFixed(2);
      const sharePct = (Number(feat.share_of_total_win || 0) * 100).toFixed(1);
      // Compact layout: feature name + headline metrics + minimal
      // per-PayId rows (just payid + share bar — no "Win Credits"
      // or "Times" columns, which the user flagged as noisy).
      return (
        `<div class="feature-block">` +
        `<h3>${String(feat.feature_name)} <span class="feature-metric">${rtpPp}pp · ${sharePct}%</span></h3>` +
        `<div class="feature-payids">${tblRows}</div>` +
        `</div>`
      );
    })
    .join("") + `</div>`;
}

// Render the bonus_chain_dynamics panel (ReMarks-derived
// MapCollection stats). Hidden when the sample contains no
// Freespin-annotated chains.
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
  const mSel = byId("machineSelect");
  mSel.innerHTML = "";
  // Group by category for optgroups.
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
  const machine = state.machines.find((m) => m.machine === byId("machineSelect").value) || state.machines[0] || { modes: [1] };
  const modeSel = byId("modeSelect");
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

async function refreshChunkStatus() {
  if (!state.currentRunId) {
    state.currentChunksAvailable = false;
    return;
  }
  try {
    const d = await apiGet(`/api/runs/${encodeURIComponent(state.currentRunId)}/chunks`);
    state.currentChunksAvailable = Boolean(d.available);
  } catch {
    state.currentChunksAvailable = false;
  }
  updateActionStates();
}

async function refreshCurrentRun() {
  if (!state.currentRunId) {
    byId("runMeta").textContent = fmt("noRun");
    renderLiveStatusStrip();
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
      renderLiveStatusStrip();
      updateActionStates();
      return;
    }
    throw err;
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
  byId("progressBar").style.width = `${pct}%`;

  const summaryLine = PURE.summarizeRunEvent(state.lang, latest && latest.event ? latest : null, {
    isFuzzy,
    maxChunks,
    target,
  });
  const runMetaLines = [
    `run=${run.run_id} ${fmt("runStatusLabel")}=${statusText(run.status)} machine=${run.machine} mode=${run.mode}`,
    summaryLine,
  ];
  if (String(run.status).toLowerCase() === "failed") {
    runMetaLines.push(`${fmt("runFailedLabel")}: ${PURE.formatRunFailureNote(state.lang, run.error_message)}`);
  } else if (String(run.status).toLowerCase() === "cancelled") {
    runMetaLines.push(`${fmt("runCancelledLabel")}: ${fmt("runCancelledText")}`);
  }
  byId("runMeta").textContent = runMetaLines.join("\n");
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
    renderFieldDiscovery(s);
    renderMachineMechanics(s);
    renderBonusChainDynamicsPanel(s);
    renderPaylineDrilldown(s);
    renderPayoutGroupDrilldown(s);
    renderSymbolDrilldown(s);
    await refreshInterpretation();
    await refreshChunkStatus();
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
  state.autoTuneRunning = true;
  updateActionStates();
  // robotInput / concInput are filled by Auto Tune itself, so on the first
  // click they are empty. Fall back to a compact candidate grid (3 robots
  // x 3 concs = 9 candidates) in that case; subsequent clicks refine
  // around the previously recommended values with the same compact grid.
  // Combined with the backend's per-robot early-exit on low success_rate,
  // this typically cuts autotune wall time more than half compared to
  // the previous 5x4 = 20 candidate sweep.
  const rcRaw = byId("robotInput").value;
  const ccRaw = byId("concInput").value;
  const hasPrev = rcRaw !== "" && ccRaw !== "";
  const rc = Number(rcRaw || 16);
  const cc = Number(ccRaw || 2);
  const robotCandidates = hasPrev
    ? [...new Set([rc - 6, rc, rc + 6].map((x) => Math.max(4, x)).filter((x) => x <= 200))]
    : [8, 16, 24];
  const concurrencyCandidates = hasPrev
    ? [...new Set([Math.max(1, cc - 1), cc, cc + 1].filter((x) => x >= 1 && x <= 16))]
    : [1, 2, 4];
  const payload = {
    machine: byId("machineSelect").value || "M14",
    mode: Number(byId("modeSelect").value || 1),
    spin_times: Math.max(60, Math.min(240, Number(byId("spinInput").value || 120))),
    robot_candidates: robotCandidates,
    concurrency_candidates: concurrencyCandidates,
    rounds: 1,
    timeout: 45,
    bet: 1000,
  };
  byId("autotuneMeta").textContent = `machine=${payload.machine} mode=${payload.mode}\nrobots=[${payload.robot_candidates.join(",")}]\nconc=[${payload.concurrency_candidates.join(",")}]\n${fmt("autotuneProgressStarting")}`;
  // Start a 1s poller against /api/autotune/progress so the user can see
  // candidate-by-candidate progress while the POST is still in flight.
  startAutotunePolling();
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
  const [h, m, models, mSummary] = await Promise.all([
    apiGet("/api/health"),
    apiGet("/api/machines"),
    apiGet("/api/models"),
    apiGet("/api/machines/summary").catch(() => null),
  ]);
  setHealth(Boolean(h.ok), h.ts || "");
  state.machines = m.machines || [];
  state.modelMeta = models || {};
  state.machinesSummary = mSummary;
  fillMachineModeSelectors();
  fillCiTierOptions();
  fillBankMultOptions();
  fillProviders();
  fillModelsForProvider(byId("providerSelect").value, state.modelMeta.default_model || "");
  renderCatalogFeatureChips();
  renderMachineCatalog();
  renderFleetOverview();
  updateSampleHint();
  refreshDiskSpace();
  await refreshServers();
  // Now that machineSelect is populated, seed the topbar idle brief.
  // (applyI18n() ran before bootstrap when machineSelect was empty, so
  // its renderLiveStatusStrip() call was a no-op.)
  renderLiveStatusStrip();
  byId("runMeta").textContent = fmt("noRun");
  byId("assessment").textContent = fmt("noReport");
  byId("interpretationText").textContent = fmt("noInterpret");
  byId("eventsText").textContent = fmt("noEvents");
  byId("autotuneMeta").textContent = fmt("noAutoTune");
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
  byId("catalogSearch").addEventListener("input", () => renderMachineCatalog());
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
  // View tabs for catalog grouping mode.
  byId("catalogViewTabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".view-tab");
    if (!btn) return;
    state.catalogViewMode = btn.dataset.view;
    byId("catalogViewTabs").querySelectorAll(".view-tab").forEach((b) => b.classList.toggle("active", b === btn));
    renderCatalogFeatureChips();
    renderMachineCatalog();
  });
  // Inline sampling panel controls.
  byId("sampleStartBtn").addEventListener("click", () => startSampling());
  byId("sampleCancelBtn").addEventListener("click", () => cancelSampling());
  byId("sampleMode").addEventListener("change", () => updateSampleHint());
  byId("sampleCi").addEventListener("change", () => updateSampleHint());
  byId("addServerBtn").addEventListener("click", () => addServer());
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
  byId("machineSelect").addEventListener("change", async () => {
    refreshModes();
    applyModeCiConstraint();
    resetConcurrencyInputsToPreset();
    clearSummaryPanels();
    renderLiveStatusStrip();
  });
  byId("modeSelect").addEventListener("change", async () => {
    applyModeCiConstraint();
    resetConcurrencyInputsToPreset();
    clearSummaryPanels();
    renderLiveStatusStrip();
  });
  byId("ciSelect").addEventListener("change", () => updateActionStates());
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
      const payload = readRunPayload();
      // Capture fuzzy + max_chunks so the polling tick can compute
      // progress correctly even before /api/runs/{id}/progress has any
      // chunks logged.
      state.lastSubmittedFuzzy = Number(payload.target_halfwidth_pp) === 0;
      state.lastSubmittedMaxChunks = Number(payload.max_chunks) || 120;
      // Immediate placeholder while uvicorn spawns the analyzer.
      byId("runMeta").textContent = fmt("runSubmittedPlaceholder");
      byId("progressBar").style.width = "0%";
      const r = await apiPost("/api/runs", payload);
      state.currentRunId = r.run_id;
      state.currentRunStatus = "running";
      ensureFastPolling();
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
  // rebuildBtn moved to manage-tab per-row (renderRunHistory).
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
  // Fast tick (1s): only the active run's progress. Created/torn down by
  // ensureFastPolling() based on currentRunStatus.
  ensureFastPolling();
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
