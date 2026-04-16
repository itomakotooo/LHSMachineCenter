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
  servers: [],
  defaultServer: "",
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
}

// Chart.js removed — bucket distribution is now a table.
function buildCharts() {}
function updateChartLabels() {}

// Category → color mapping for badges and card tints.
const CATEGORY_COLORS = {
  Normal: "#6b7280", Collect: "#7c3aed", Lock: "#ea580c",
  FreeSpin: "#059669", ReSpin: "#0891b2", Wheel: "#d97706",
  Fortunes: "#c026d3", Other: "#9ca3af", Unknown: "#9ca3af",
};
const VOL_COLORS = { Low: "#059669", Medium: "#2563eb", High: "#ea580c", "Very High": "#dc2626" };

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
    return `<div class="cat-mode-row"><span class="cat-mode-label">m${mode}</span> <span class="cat-rtp">${rtp}</span> <span class="cat-ci">${ci}</span> ${volHtml}</div>`;
  }).join("");
}

function renderMachineCatalog() {
  const wrap = byId("machineCatalog");
  wrap.innerHTML = "";
  if (!state.machines.length) return (wrap.textContent = fmt("noMachines"));

  const searchEl = byId("catalogSearch");
  const query = (searchEl ? searchEl.value : "").trim().toLowerCase();

  // Group machines by category.
  const groups = {};
  const CATEGORY_ORDER = ["Normal", "Collect", "Lock", "FreeSpin", "ReSpin", "Wheel", "Fortunes", "Other", "Unknown"];
  state.machines.forEach((m) => {
    if (query && !m.machine.toLowerCase().includes(query) && !(m.category || "").toLowerCase().includes(query)) return;
    const cat = m.category || "Other";
    if (!groups[cat]) groups[cat] = [];
    groups[cat].push(m);
  });

  const orderedKeys = CATEGORY_ORDER.filter((k) => groups[k]);
  Object.keys(groups).forEach((k) => { if (!orderedKeys.includes(k)) orderedKeys.push(k); });

  if (!orderedKeys.length) {
    wrap.textContent = query ? fmt("catalogNoMatch") : fmt("noMachines");
    return;
  }

  orderedKeys.forEach((cat) => {
    const machines = groups[cat];
    const catColor = CATEGORY_COLORS[cat] || "#9ca3af";
    const section = document.createElement("div");
    section.className = "catalog-group";

    const header = document.createElement("div");
    header.className = "catalog-group-header";
    header.innerHTML = `<span class="catalog-group-arrow">&#9660;</span> <span class="catalog-group-dot" style="background:${catColor}"></span> <span class="catalog-group-name">${cat}</span> <span class="catalog-group-count">(${machines.length})</span>`;
    header.addEventListener("click", () => {
      section.classList.toggle("collapsed");
      header.querySelector(".catalog-group-arrow").innerHTML = section.classList.contains("collapsed") ? "&#9654;" : "&#9660;";
    });
    section.appendChild(header);

    const grid = document.createElement("div");
    grid.className = "catalog-list";
    machines.forEach((m) => {
      const d = document.createElement("div");
      d.className = "catalog-item";
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
    };
    el.addEventListener("click", toggle);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    });
  });
  updateBatchRunHint();
}

// ── Batch Run UI ──────────────────────────────────────────────────

function updateBatchRunHint() {
  const hint = byId("batchRunHint");
  const btn = byId("batchRunBtn");
  if (!hint || !btn) return;
  const n = state.runFilterMachines.size;
  if (n === 0) {
    hint.textContent = fmt("batchHintNone");
    btn.disabled = true;
  } else {
    hint.textContent = fmt("batchHintSelected", { n });
    btn.disabled = !!state.activeBatchId;
  }
}

async function startBatchRun() {
  const selected = [...state.runFilterMachines];
  if (!selected.length) return;
  // Build items: each selected machine × mode 2 (default).
  // Use all available modes for each machine.
  const items = [];
  selected.forEach((machineName) => {
    const m = state.machines.find((x) => x.machine === machineName);
    const modes = m && m.modes && m.modes.length ? m.modes : [2];
    // For batch, run only mode 2 to keep it fast. Users can adjust.
    items.push({ machine: machineName, mode: modes.includes(2) ? 2 : modes[0] });
  });
  try {
    const result = await apiPost("/api/batch-run", { items, concurrency: 3 });
    state.activeBatchId = result.batch_id;
    updateBatchRunHint();
    pollBatchProgress();
  } catch (e) {
    alert(String(e.message || e));
  }
}

function pollBatchProgress() {
  if (!state.activeBatchId) return;
  const panel = byId("batchProgressPanel");
  if (panel) panel.classList.remove("hidden");

  const poll = async () => {
    if (!state.activeBatchId) return;
    try {
      const data = await apiGet(`/api/batch-run/${state.activeBatchId}`);
      renderBatchProgress(data);
      if (data.status === "completed") {
        state.activeBatchId = null;
        updateBatchRunHint();
        // Refresh catalog to show new reports.
        const mSummary = await apiGet("/api/machines/summary").catch(() => null);
        state.machinesSummary = mSummary;
        renderMachineCatalog();
        await refreshRunList(false);
        return;
      }
    } catch (_) { /* ignore transient errors */ }
    setTimeout(poll, 2000);
  };
  poll();
}

function renderBatchProgress(data) {
  const meta = byId("batchProgressMeta");
  const list = byId("batchProgressList");
  const cancelBtn = byId("batchCancelBtn");
  if (!meta || !list) return;

  meta.textContent = `${data.completed} / ${data.total} ${fmt("batchProgressLabel")}`;
  if (cancelBtn) cancelBtn.disabled = data.status !== "running";

  const statusIcon = { pending: "\u23f3", running: "\u25b6", completed: "\u2705", failed: "\u274c", cancelled: "\u23f8" };
  list.innerHTML = data.items
    .map((it) => {
      const icon = statusIcon[it.status] || "\u2753";
      const err = it.error ? ` — ${it.error.slice(0, 60)}` : "";
      return `<div class="batch-item batch-${it.status}">${icon} ${it.machine} m${it.mode}${err}</div>`;
    })
    .join("");
}

async function cancelBatchRun() {
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
      `<td><button class="srv-edit-btn small-btn">${fmt("btnEdit")}</button> <button class="srv-delete-btn small-btn danger-btn">${fmt("btnDelete")}</button></td>` +
      `</tr>`
    );
  }).join("");

  // Wire up edit/delete buttons.
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
  const ORDER = ["Normal", "Collect", "Lock", "FreeSpin", "ReSpin", "Wheel", "Fortunes", "Other", "Unknown"];
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
  renderMachineCatalog();
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
  byId("batchRunBtn").addEventListener("click", () => startBatchRun());
  byId("batchCancelBtn").addEventListener("click", () => cancelBatchRun());
  byId("addServerBtn").addEventListener("click", () => addServer());
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
