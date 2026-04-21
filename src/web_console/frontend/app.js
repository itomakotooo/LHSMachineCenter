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
  // Manage-tab focus (master/detail model introduced 2026-04-19):
  // plain-click on a catalog card sets focusedMachine (single-machine
  // detail view in right pane); ctrl/shift/checkbox/全选 paths set
  // runFilterMachines (batch mode). The two are mutually exclusive —
  // entering one clears the other. Null means "nothing focused" →
  // right pane shows fleet overview (when runFilterMachines is also
  // empty) or multi-select summary (when runFilterMachines has >0).
  focusedMachine: null,
  // Global rawdata detail view (step 6): when true the right pane
  // shows the fleet-wide per-machine rawdata table instead of fleet
  // overview. Toggled by the rawdata banner's 明细 button. Takes
  // precedence over fleet overview but NOT over focus/multi.
  showGlobalRawdata: false,
  rawdataOverview: null,  // cached GET /api/rawdata/overview response
  // Static machine attributes (category / features / mechanics / md5)
  // — decoupled from report lifecycle. Loaded from /api/machines/static
  // on bootstrap so the catalog filter chips + mechanic view don't
  // break when reports are deleted / regenerated.
  staticAttrs: null,
  // Operator-tunable retention quota (spins). Loaded on boot from
  // /api/settings, persisted there. Rendered inline inside the
  // rawdata banner's always-visible settings row.
  minRetentionSpins: 100000,
  // Set of selected run_ids for batch operations.
  // selectedRuns retired 2026-04-19 with the run-history table.
  // Kept as empty Set for back-compat with any stale reads.
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
  // 按大厅 ordering mode: "default" (upstream localMapMachineCellsJson
  // order) or "current" (default + currently-active activity order
  // overrides applied). Toggled by the hallsRefreshBar UI; the tab
  // isn't a grouping anymore (server confirmed no real halls; what
  // the old code called "halls" came from Unity asset-bundle paths).
  hallOrderMode: "default",
  // 按 RTP 视图的 mode 选择器 (2026-04-20 round 7). "auto" = 保留历史
  // 行为（优先 mode 2，否则最小 mode），用于兼容旧书签；具体数字 =
  // 只按该 mode 的 rtp_pct 排序，没有该 mode 数据的机台沉底。视图本身
  // 已去掉 < 90% / 90–95% 这种数值分段分组，改成 rtp 降序 flat 列表。
  catalogRtpMode: "auto",
  catalogFeatureFilter: new Set(),
  catalogSortReverse: false,  // reverse ordering toggle
  versionHistoryMachine: null,
  versionHistoryMode: null,
  // Map<report_version, {mode}> — rwtree checkboxes register mode so
  // compareReports can call /api/reports/{m}/{mode}/{version} correctly.
  // Pre-2026-04-19 this was a plain Set<version> driven by the
  // per-mode versionHistoryPanel (which always knew its own mode).
  compareSelected: new Map(),
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
  // Freshness row: compare this run's analyzer_version + config/code md5
  // against the CURRENT upstream/local snapshots (state.currentVersions,
  // populated by loadBootstrap). "✓ 当前" when match, "⚠ 过期" when
  // drifted. Keeps the operator from staring at a months-old run
  // thinking it reflects reality. Classifier / paytable-shape panels
  // are auto-regenerated post generate-report, so they track analyzer
  // freshness; no separate per-artifact badge needed here.
  const cv = state.currentVersions || {};
  const cvAnalyzer = cv.analyzer_version || "";
  const cvMachines = cv.machines || {};
  const cvCfg = ((cvMachines[run.machine] || {}).config_md5) || "";
  const cvCode = ((cvMachines[run.machine] || {}).code_md5) || "";
  const analyzerMatch = run.analyzer_version && cvAnalyzer
    ? String(run.analyzer_version) === String(cvAnalyzer)
    : null;
  const cfgMatch = run.rawdata_config_md5 && cvCfg
    ? String(run.rawdata_config_md5) === String(cvCfg)
    : null;
  const codeMatch = run.rawdata_code_md5 && cvCode
    ? String(run.rawdata_code_md5) === String(cvCode)
    : null;
  const rawdataMatch = (cfgMatch != null && codeMatch != null)
    ? (cfgMatch && codeMatch)
    : (cfgMatch != null ? cfgMatch : codeMatch);
  const analyzerBadge = analyzerMatch == null
    ? `<span class="lm-badge lm-badge-unknown">${fmt("freshnessUntagged")}</span>`
    : analyzerMatch
      ? `<span class="lm-badge lm-badge-fresh">${fmt("freshnessFresh")}</span>`
      : `<span class="lm-badge lm-badge-stale">${fmt("freshnessStale")}</span>`;
  const rawdataBadge = rawdataMatch == null
    ? `<span class="lm-badge lm-badge-unknown">${fmt("freshnessUntagged")}</span>`
    : rawdataMatch
      ? `<span class="lm-badge lm-badge-fresh">${fmt("freshnessFresh")}</span>`
      : `<span class="lm-badge lm-badge-stale">${fmt("freshnessStale")}</span>`;
  rows.push(
    `<div class="lm-freshness">` +
    `<span class="lm-label">${fmt("freshnessAnalyzer")}:</span> ${analyzerBadge}` +
    ` · <span class="lm-label">${fmt("freshnessRawdata")}:</span> ${rawdataBadge}` +
    `</div>`,
  );
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

  // Batch-bar buttons act on the effective selection (focus OR multi).
  const autotuneBtn = byId("autotuneBtn");
  const hasSelection = _effectiveSelectionSize() > 0;
  if (autotuneBtn) {
    autotuneBtn.disabled = localBusy || serverBusy || anyRunRunning || !hasSelection;
    autotuneBtn.textContent = state.autoTuneRunning ? fmt("btnAutoTuneBusy") : fmt("btnAutoTune");
  }

  // Batch Generate Report: rebuild reports from cached rawdata across
  // every effective-selected machine for the current sampleMode.
  // Disabled when no selection / a run is already active / another
  // batch is tracked in state.batchGenerateId.
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

  // Delete rawdata (new step-3 button). Destructive — always requires
  // selection + no concurrent ops. Does NOT depend on batchActive
  // because the ops mutex serializes it anyway on the server side.
  const deleteRawBtn = byId("batchDeleteRawdataBtn");
  if (deleteRawBtn) {
    deleteRawBtn.disabled = localBusy || serverBusy || anyRunRunning || !hasSelection;
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

  // Fix 2 (2026-04-19 round 3): dynamic destructive / cleanup buttons
  // live outside the static HTML (rendered inside banners / tree /
  // global table). When busy state changes, re-render the cheap
  // containers so the new disabled= evaluations pick up _isAnyBusy().
  // Tree re-render is EXPENSIVE (fetches) — we set disabled inline on
  // the DOM instead. Transient over/under-disable is fine: the user
  // never fires a button during a busy period anyway (server would
  // 409), this just visually hints the busy state.
  const anyBusy = localBusy || serverBusy || anyRunRunning;
  state._anyBusy = anyBusy;  // cache for render-time checks
  // Banner + global table: cheap, can re-render in place.
  if (state.rawdataOverview) renderRawdataBanner();
  if (state.showGlobalRawdata) renderRawdataGlobalTable();
  // Tree: don't re-render (expensive fetches); toggle disabled inline.
  // Buttons with data-intrinsic-disabled="1" stay disabled regardless;
  // others track busy state.
  document.querySelectorAll(".rwtree-gen-btn").forEach((btn) => {
    if (btn.dataset.intrinsicDisabled === "1") {
      btn.disabled = true;
      return;
    }
    btn.disabled = anyBusy;
  });
}

function _isAnyBusy() { return !!state._anyBusy; }

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
  // kpiTail / kpiBigWin render via grid helpers instead of setKpi.
  setKpi("kpiVolatility", fmt("libRankNoData"));
  setKpi("kpiArchetype", "N/A");
  setKpi("kpiLossStreak", "N/A");
  setKpi("kpiMaxReturn", "N/A");
  const tg = byId("kpiTailGrid"); if (tg) tg.innerHTML = "";
  const bg = byId("kpiBigWinGrid"); if (bg) bg.innerHTML = "";
  const bt = byId("bucketTable");
  if (bt) bt.querySelector("tbody").innerHTML = "";
  const fdp = byId("fieldDiscoveryPanel");
  if (fdp) fdp.classList.add("hidden");
  const mmp = byId("machineMechanicsPanel");
  if (mmp) mmp.classList.add("hidden");
  const bkp = byId("bankruptcyPanel");
  if (bkp) bkp.classList.add("hidden");
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

// Get all features a machine has. Prefer the static-attrs cache
// (union across report history, survives deletions); fall back to
// machinesSummary per-mode features for back-compat.
function _machineFeatures(machineName) {
  const staticEntry = ((state.staticAttrs || {}).machines || {})[machineName];
  if (staticEntry && Array.isArray(staticEntry.features) && staticEntry.features.length) {
    return [...staticEntry.features];
  }
  const modes = ((state.machinesSummary || {}).machines || {})[machineName] || {};
  const features = new Set();
  Object.values(modes).forEach((d) => (d.features || []).forEach((f) => features.add(f)));
  return [...features];
}

// Features used by ≥2 machines are "primary"; singletons → "其他".
function _featureIsSingleton(featureName) {
  const dist = (state.staticAttrs || {}).feature_distribution
            || (state.machinesSummary || {}).feature_distribution
            || {};
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
      // 2026-04-20 round 7: removed numeric banding (< 90%, 90–95%,
      // ...). Now a single flat "all" group sorted by the selected
      // mode's rtp_pct in renderMachineCatalog.
      key = "all";
    } else if (viewMode === "hall") {
      // Hall view splits into TWO sections (2026-04-20 round 4):
      //   - "club"   — the multi-cabinet bank (Royal lobby),
      //                identified upstream by selectType===2 on the
      //                cell. 17 machines on dev fleet.
      //   - "normal" — everything else. Ordering toggle (默认/当前)
      //                only applies to this section; club stays in
      //                upstream cell sequence regardless.
      // Neither section auto-collapses.
      const clubList = (state.machineHalls || {}).club_machines || [];
      key = clubList.includes(m.machine) ? "club" : "normal";
    } else if (viewMode === "mechanic") {
      // Prefer staticAttrs (union across history); fall back to
      // per-mode machinesSummary for back-compat.
      const staticEntry = ((state.staticAttrs || {}).machines || {})[m.machine];
      let allMechs = new Set();
      if (staticEntry && Array.isArray(staticEntry.mechanics)) {
        staticEntry.mechanics.forEach((mk) => allMechs.add(mk));
      } else {
        const mdata = sm[m.machine] || {};
        Object.values(mdata).forEach((d) => (d.mechanics || []).forEach((mk) => allMechs.add(mk)));
      }
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
  if (viewMode === "mechanic") return ["lock_lines", "lock_symbols", "lock_reels", "jackpot", "free_spin", "dollar_pick", "Normal"];
  if (viewMode === "hall") {
    // Club section pinned on top; normal section below. Ordering
    // within each section is applied in renderMachineCatalog.
    return ["club", "normal"];
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

  const dist = (state.staticAttrs || {}).feature_distribution
            || (state.machinesSummary || {}).feature_distribution
            || {};
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
    const dist = (state.staticAttrs || {}).feature_distribution
            || (state.machinesSummary || {}).feature_distribution
            || {};
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

  // Sort within groups. Hall view uses upstream-provided ordering
  // (default_order or current_hall_order) — honor that by sorting
  // machines by their position in the chosen list; RTP view sorts
  // the single flat group by the selected mode's rtp_pct (with
  // null-rtp machines sunk to the bottom); all other views sort by
  // machine number with the reverse toggle.
  const dir = state.catalogSortReverse ? -1 : 1;
  if (viewMode === "hall") {
    const hallData = state.machineHalls || {};
    const clubOrder = hallData.club_machines || [];
    // Normal section honors the default/current toggle; club section
    // always uses its upstream cell sequence (clubs don't reorder
    // based on activity overrides).
    const normalOrder = state.hallOrderMode === "current"
      ? (hallData.current_hall_order || hallData.default_order || [])
      : (hallData.default_order || []);
    const clubRank = new Map(clubOrder.map((m, i) => [m, i]));
    const normalRank = new Map(normalOrder.map((m, i) => [m, i]));
    const makeHallSort = (rank) => (a, b) => {
      const ra = rank.has(a.machine) ? rank.get(a.machine) : Infinity;
      const rb = rank.has(b.machine) ? rank.get(b.machine) : Infinity;
      if (ra !== rb) return dir * (ra - rb);
      return dir * ((parseInt(a.machine.slice(1)) || 0) - (parseInt(b.machine.slice(1)) || 0));
    };
    if (groups.club) groups.club.sort(makeHallSort(clubRank));
    if (groups.normal) groups.normal.sort(makeHallSort(normalRank));
  } else if (viewMode === "rtp") {
    // Pick RTP from the selected mode (or auto-picker fallback). Null
    // RTP → sink to bottom (stays at bottom regardless of reverse so
    // the "no data" tail doesn't swap to the top when user toggles).
    const rtpMode = state.catalogRtpMode || "auto";
    const rtpOf = (machineName) => {
      const sm = ((state.machinesSummary || {}).machines || {})[machineName] || {};
      if (rtpMode === "auto") {
        return (_machineData(machineName) || {}).rtp_pct;
      }
      const entry = sm[String(rtpMode)];
      return entry ? entry.rtp_pct : null;
    };
    // Base direction is DESC (highest RTP first) since that's the
    // usual operator question ("which machines pay highest?"). The
    // existing ↑↓ toggle flips it.
    const baseDir = state.catalogSortReverse ? 1 : -1;
    const rtpSort = (a, b) => {
      const ra = rtpOf(a.machine);
      const rb = rtpOf(b.machine);
      const aNull = ra == null;
      const bNull = rb == null;
      if (aNull && bNull) return (parseInt(a.machine.slice(1)) || 0) - (parseInt(b.machine.slice(1)) || 0);
      if (aNull) return 1;   // null always last
      if (bNull) return -1;
      if (ra === rb) return (parseInt(a.machine.slice(1)) || 0) - (parseInt(b.machine.slice(1)) || 0);
      return baseDir * (ra - rb);
    };
    Object.values(groups).forEach((arr) => arr.sort(rtpSort));
  } else {
    const numSort = (a, b) => dir * ((parseInt(a.machine.slice(1)) || 0) - (parseInt(b.machine.slice(1)) || 0));
    Object.values(groups).forEach((arr) => arr.sort(numSort));
  }
  // For non-RTP views, reverse the group order too when operator
  // hits ↑↓. RTP view stays with a single "all" group so there's
  // nothing to flip at this level (the sort above already handled
  // direction).
  if (state.catalogSortReverse && viewMode !== "rtp") orderedKeys.reverse();

  const isFlatView = viewMode === "name" || viewMode === "category" || viewMode === "rtp";

  orderedKeys.forEach((groupKey) => {
    const machines = groups[groupKey];
    const section = document.createElement("div");
    section.className = "catalog-group";

    if (!isFlatView) {
      const isMechView = viewMode === "mechanic";
      const isHallView = viewMode === "hall";
      const hallLabels = { club: "Club 大厅", normal: "普通大厅" };
      const hallColors = { club: "#b45309", normal: "#475569" };
      const catColor = isHallView
        ? (hallColors[groupKey] || "#475569")
        : (CATEGORY_COLORS[groupKey] || VOL_COLORS[groupKey] || (isMechView ? MECH_GROUP_COLORS[groupKey] : null) || "#9ca3af");
      const displayName = isHallView
        ? (hallLabels[groupKey] || groupKey)
        : (isMechView ? (MECH_GROUP_LABELS[groupKey] || groupKey) : groupKey);
      const header = document.createElement("div");
      header.className = "catalog-group-header";
      header.innerHTML = `<span class="catalog-group-arrow">&#9660;</span> <span class="catalog-group-dot" style="background:${catColor}"></span> <span class="catalog-group-name">${displayName}</span> <span class="catalog-group-count">(${machines.length})</span>`;
      header.addEventListener("click", () => {
        section.classList.toggle("collapsed");
        header.querySelector(".catalog-group-arrow").innerHTML = section.classList.contains("collapsed") ? "&#9654;" : "&#9660;";
      });
      section.appendChild(header);
      // Auto-collapse groups when the operator isn't filtering —
      // except in hall view where we always show both sections
      // (user feedback 2026-04-20: "两个板块都不要再收起").
      if (!query && !isHallView) {
        section.classList.add("collapsed");
        header.querySelector(".catalog-group-arrow").innerHTML = "&#9654;";
      }
    }

    const grid = document.createElement("div");
    grid.className = "catalog-list";
    machines.forEach((m) => {
      const d = document.createElement("div");
      d.className = "catalog-item";
      const isMulti = state.runFilterMachines.has(m.machine);
      const isFocused = state.focusedMachine === m.machine;
      const isActive = isMulti || isFocused;
      // Don't apply heatmap bg on active cards (selection bg wins).
      if (!isActive) {
        const bg = _cardBgColor(m.machine);
        if (bg) d.style.background = bg;
      }
      const catColor = CATEGORY_COLORS[m.category] || "#9ca3af";
      d.style.borderLeftColor = catColor;
      if (isActive) d.classList.add("active");
      if (isFocused) d.classList.add("focused");
      if (m.available === false) d.classList.add("unavailable");
      d.dataset.machine = m.machine;
      d.setAttribute("role", "button");
      d.setAttribute("tabindex", "0");
      const metrics = _catalogModeMetrics(m.machine);
      const reportBadge = m.report_count ? `<span class="catalog-badge" style="background:${catColor}">${m.report_count}</span>` : "";
      const issues = _machineBrokenIssues(m.machine);
      const brokenBadge = issues.length
        ? `<span class="catalog-broken" title="${issues.join(' · ').replace(/"/g, '&quot;')}">⚠</span>`
        : "";
      // Multi-select checkbox: stopPropagation in click handler so
      // card body click still focuses. Click body = focus, click
      // checkbox = batch multi-select (two independent affordances).
      d.innerHTML =
        `<input type="checkbox" class="catalog-check" title="加入批量操作" ${isMulti ? "checked" : ""}>` +
        `<div class="catalog-title">${m.machine}${brokenBadge}${reportBadge}</div>` +
        `${metrics || `<div class="catalog-modes">modes: ${(m.modes || []).join(", ")}</div>`}`;
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

// ── Click model (refactor 2026-04-19) ──────────────────────────────
// Plain click / Enter on a catalog card = FOCUS (single-machine detail
// in the right pane). Ctrl/Meta/Shift-click = MULTI-SELECT (batch
// mode, drives runFilterMachines). Focus and multi-select are mutually
// exclusive — entering one clears the other. renderDetailPane() below
// owns the right pane's state-driven switching.
function _cardActiveDomSync(machine, active) {
  const el = document.querySelector(`.catalog-item[data-machine="${CSS.escape(machine)}"]`);
  if (!el) return;
  el.classList.toggle("active", active);
  if (!active) {
    const bg = _cardBgColor(machine);
    el.style.background = bg || "";
  } else {
    el.style.background = "";
  }
}

function _syncAllCardsActiveDom() {
  // After bulk state changes (focus flip, multi clear, etc.), reconcile
  // every card's .active / .focused class + checkbox state in one pass.
  const cards = document.querySelectorAll(".catalog-item");
  cards.forEach((el) => {
    const m = el.dataset.machine;
    if (!m) return;
    const focused = state.focusedMachine === m;
    const multi = state.runFilterMachines.has(m);
    const active = focused || multi;
    if (el.classList.contains("active") !== active) {
      _cardActiveDomSync(m, active);
    }
    el.classList.toggle("focused", focused);
    const cb = el.querySelector(".catalog-check");
    if (cb) cb.checked = multi;
  });
}

function _setFocusedMachine(machine) {
  if (!machine) return;
  // Entering focus mode clears any existing multi-select set.
  if (state.runFilterMachines.size > 0) {
    state.runFilterMachines.clear();
  }
  state.focusedMachine = machine;
  _syncAllCardsActiveDom();
  renderRunHistory();
  updateSampleHint();
  updateActionStates();
  renderDetailPane();
}

function _clearFocus() {
  state.focusedMachine = null;
  _syncAllCardsActiveDom();
  // Fix 1 (2026-04-19 round 3): unfocus must also refresh batch bar
  // + action states so the sticky bar hides when nothing is selected.
  // Without this, the bar stays stuck on "聚焦 Mx" with stale buttons.
  updateSampleHint();
  updateActionStates();
  renderDetailPane();
}

function _toggleMultiSelect(machine) {
  if (!machine) return;
  // Entering multi-select mode clears any focus.
  if (state.focusedMachine !== null) {
    state.focusedMachine = null;
  }
  const had = state.runFilterMachines.has(machine);
  if (had) state.runFilterMachines.delete(machine);
  else state.runFilterMachines.add(machine);
  _syncAllCardsActiveDom();
  renderRunHistory();
  updateSampleHint();
  updateActionStates();
  renderDetailPane();
}

// Legacy name kept so existing call sites (全选 button, clear selection,
// _recoverActiveSampling restore path) still work. Defaults to multi mode.
function _toggleCatalogMachineSelection(machine) {
  _toggleMultiSelect(machine);
}

function _initCatalogDelegation() {
  const wrap = byId("machineCatalog");
  if (!wrap || wrap.dataset.delegationInit === "1") return;
  wrap.dataset.delegationInit = "1";
  wrap.addEventListener("click", (e) => {
    const el = e.target.closest(".catalog-item");
    if (!el || !wrap.contains(el)) return;
    const machine = el.dataset.machine;
    // Checkbox click: multi-select toggle only, no focus change.
    if (e.target.classList.contains("catalog-check")) {
      e.stopPropagation();
      _toggleMultiSelect(machine);
      return;
    }
    const withModifier = e.ctrlKey || e.metaKey || e.shiftKey;
    if (withModifier) {
      _toggleMultiSelect(machine);
    } else {
      // Plain card body click: toggle focus. Clicking focused card again unfocuses.
      if (state.focusedMachine === machine) {
        _clearFocus();
      } else {
        _setFocusedMachine(machine);
      }
    }
  });
  wrap.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const el = e.target.closest(".catalog-item");
    if (!el || !wrap.contains(el)) return;
    e.preventDefault();
    const machine = el.dataset.machine;
    const isMulti = e.ctrlKey || e.metaKey || e.shiftKey;
    if (isMulti) {
      _toggleMultiSelect(machine);
    } else if (state.focusedMachine === machine) {
      _clearFocus();
    } else {
      _setFocusedMachine(machine);
    }
  });
}

// Effective selection for batch-bar actions (sampling / autotune /
// batch-generate / delete-rawdata): focused machine takes priority (1
// item), otherwise all multi-selected machines. Returns [] when nothing
// is selected — batch bar stays hidden, all its buttons disabled.
function _effectiveSelectedMachines() {
  if (state.focusedMachine) return [state.focusedMachine];
  return [...state.runFilterMachines];
}
function _effectiveSelectionSize() {
  if (state.focusedMachine) return 1;
  return state.runFilterMachines.size;
}

// Detail pane switch: picks which of the right-column sections to show
// based on state.focusedMachine + state.runFilterMachines. Step 1 only
// wires container visibility + delegates to existing render functions
// for the focused case; step 4 replaces machineDetailPanel with the
// new rawdata × report tree.
function renderDetailPane() {
  const fleet = byId("detailFleetOverview");
  const detail = byId("machineDetailPanel");
  const compare = byId("reportComparisonPanel");
  const multi = byId("detailMultiSelect");
  const globalRaw = byId("detailRawdataGlobal");
  if (!fleet || !detail) return;  // DOM not yet built (tests / early boot)

  const focused = state.focusedMachine;
  const multiSize = state.runFilterMachines.size;

  // Default: hide everything, then reveal the appropriate combination.
  const hide = (el) => el && el.classList.add("hidden");
  const show = (el) => el && el.classList.remove("hidden");
  hide(fleet); hide(detail); hide(compare); hide(multi); hide(globalRaw);

  if (focused) {
    show(detail);
    try { showMachineDetail(focused); } catch (_) {}
    // Reports list is inside the rwtree inside machineDetailPanel now
    // (step 4) — legacy versionHistoryPanel stays hidden. Compare
    // panel only fires when user picks 2 versions via the tree.
    return;
  }
  if (multiSize > 0) {
    show(multi);
    const countEl = byId("multiSelectCount");
    const listEl = byId("multiSelectList");
    if (countEl) countEl.textContent = String(multiSize);
    if (listEl) {
      listEl.innerHTML = "";
      [...state.runFilterMachines].sort().forEach((m) => {
        const li = document.createElement("li");
        li.textContent = m;
        listEl.appendChild(li);
      });
    }
    return;
  }
  // Nothing selected: either global rawdata detail (from banner) or fleet overview.
  if (state.showGlobalRawdata) {
    show(globalRaw);
    renderRawdataGlobalTable();
    return;
  }
  show(fleet);
}

// Refresh the static-attrs cache from the backend. Called after any
// operation that may have updated the file (generate-report, batch
// regen, import). Cheap — the backend endpoint reads an mtime cache
// in sub-millisecond time.
async function refreshStaticAttrs() {
  try {
    state.staticAttrs = await apiGet("/api/machines/static");
    renderCatalogFeatureChips();
    renderCatalogFilters();
    renderMachineCatalog();
  } catch (_) { /* non-fatal */ }
}

// ── Global rawdata banner + detail table (step 6) ───────────────────
async function refreshRawdataOverview() {
  try {
    state.rawdataOverview = await apiGet("/api/rawdata/overview");
  } catch (_) {
    state.rawdataOverview = null;
  }
  renderRawdataBanner();
  // If the global detail view is already showing, re-render the table
  // so size/row changes after a cleanup reflect immediately.
  if (state.showGlobalRawdata) renderRawdataGlobalTable();
}

function renderRawdataBanner() {
  const banner = byId("rawdataOverviewBanner");
  if (!banner) return;
  const d = state.rawdataOverview;
  if (!d || !d.total_bytes) {
    banner.classList.add("hidden");
    return;
  }
  banner.classList.remove("hidden");
  const totalGb = (d.total_bytes / 1024 / 1024 / 1024).toFixed(2);
  const baselineGb = (d.baseline_bytes / 1024 / 1024 / 1024).toFixed(2);
  const reclaimMb = d.reclaimable_bytes / 1024 / 1024;
  const reclaimText = reclaimMb >= 1024
    ? (reclaimMb / 1024).toFixed(2) + " GB"
    : reclaimMb.toFixed(1) + " MB";
  const cleanupDisabled = d.reclaimable_bytes <= 0 || _isAnyBusy();
  const minRet = Number(state.minRetentionSpins || 100000);
  banner.innerHTML = `
    <div class="rawdata-banner-row">
      <span class="rawdata-banner-main">💾 rawdata <b>${totalGb} GB</b> · baseline ${baselineGb} GB 保底 · 可回收 <b>${reclaimText}</b></span>
      <span class="rawdata-banner-actions">
        <button id="rawdataBannerCleanupBtn" class="small-btn danger-btn" ${cleanupDisabled ? "disabled" : ""}>一键清理 ${reclaimText}</button>
        <button id="rawdataBannerDetailBtn" class="small-btn ${state.showGlobalRawdata ? "active" : ""}">${state.showGlobalRawdata ? "↩ 返回概览" : "明细 ▶"}</button>
      </span>
    </div>
    <div class="rawdata-banner-settings">
      <label>保底 spins 阈值
        <input id="bannerMinRetention" type="number" min="0" step="10000" value="${minRet}" />
      </label>
      <button id="bannerSaveSettingsBtn" class="small-btn primary-btn">保存</button>
      <span id="bannerSettingsMeta" class="muted"></span>
      <span class="muted">超过这个保底量的 chunks 才会被自动清理 / UI「删除可回收」回收；保底永不删。</span>
    </div>`;
  byId("rawdataBannerCleanupBtn")?.addEventListener("click", async () => {
    if (!confirm(`一键清理 ${reclaimText}？baseline 保底不会被删除。`)) return;
    try {
      await apiPost("/api/cache/cleanup", { max_delete_bytes: 0 });
    } catch (err) {
      alert("清理失败：" + (err.message || err));
      return;
    }
    await refreshRawdataOverview();
  });
  byId("rawdataBannerDetailBtn")?.addEventListener("click", () => {
    state.showGlobalRawdata = !state.showGlobalRawdata;
    renderRawdataBanner();
    renderDetailPane();
  });
  byId("bannerSaveSettingsBtn")?.addEventListener("click", async () => {
    const input = byId("bannerMinRetention");
    const meta = byId("bannerSettingsMeta");
    if (!input) return;
    const value = Number(input.value);
    if (!Number.isFinite(value) || value < 0) {
      if (meta) meta.textContent = "✗ 无效值";
      return;
    }
    try {
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
      state.minRetentionSpins = saved.min_retention_spins;
      if (meta) meta.textContent = `✓ 已保存 (${saved.min_retention_spins.toLocaleString()})`;
      // Retention change affects what counts as baseline vs deletable —
      // refresh overview so the banner numbers update.
      refreshRawdataOverview();
    } catch (err) {
      if (meta) meta.textContent = "✗ 保存失败: " + (err.message || err);
    }
  });
}

function renderRawdataGlobalTable() {
  const wrap = byId("rawdataGlobalTableWrap");
  if (!wrap) return;
  const d = state.rawdataOverview;
  if (!d) {
    wrap.innerHTML = `<div class="muted">加载中…</div>`;
    refreshRawdataOverview();
    return;
  }
  const fMbShort = (b) => {
    const mb = b / 1024 / 1024;
    if (mb >= 1024) return (mb / 1024).toFixed(2) + " GB";
    return mb >= 1 ? mb.toFixed(1) + " MB" : (b / 1024).toFixed(0) + " KB";
  };
  const rows = [...d.per_machine].sort((a, b) =>
    (b.deletable_bytes + b.stale_bytes) - (a.deletable_bytes + a.stale_bytes)
  );
  if (!rows.length) {
    wrap.innerHTML = `<div class="muted">无 rawdata</div>`;
    return;
  }
  wrap.innerHTML = `
    <table class="drilldown-table rawdata-global-table">
      <thead>
        <tr>
          <th>机台</th>
          <th>保底</th>
          <th>可回收</th>
          <th>过期</th>
          <th>最近采样</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((r) => {
          const last = r.last_sample_mtime
            ? new Date(r.last_sample_mtime * 1000).toISOString().slice(0, 10)
            : "—";
          const reclaim = r.deletable_bytes + r.stale_bytes;
          const delDisabled = reclaim <= 0 || _isAnyBusy();
          return `<tr class="rawdata-global-row" data-machine="${r.machine}">
            <td><strong>${r.machine}</strong></td>
            <td>${fMbShort(r.kept_bytes)} <span class="muted">(${r.kept_chunks})</span></td>
            <td class="${r.deletable_bytes > 0 ? "rawdata-reclaim" : "muted"}">
              ${fMbShort(r.deletable_bytes)} <span class="muted">(${r.deletable_chunks})</span>
            </td>
            <td class="${r.stale_bytes > 0 ? "rawdata-stale" : "muted"}">
              ${fMbShort(r.stale_bytes)} <span class="muted">(${r.stale_chunks})</span>
            </td>
            <td class="muted">${last}</td>
            <td>
              <button class="small-btn danger-btn rwglobal-del-btn" data-machine="${r.machine}" ${delDisabled ? "disabled" : ""} title="删除此机台的可回收 + 过期 chunks（保留 baseline）">🗑 ${fMbShort(reclaim)}</button>
            </td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>
  `;
  // Row click → focus machine (global detail acts as a diagnostic
  // drilldown → user's next natural action is "go to this machine").
  // 🗑 button stops propagation so it doesn't trigger the row-click.
  wrap.querySelectorAll(".rawdata-global-row").forEach((tr) => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest(".rwglobal-del-btn")) return;
      const m = tr.dataset.machine;
      state.showGlobalRawdata = false;
      _setFocusedMachine(m);
      renderRawdataBanner();
    });
  });
  wrap.querySelectorAll(".rwglobal-del-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const m = btn.dataset.machine;
      if (state.systemState?.operation_busy) {
        alert(`有操作进行中，请等待完成再删除。`);
        return;
      }
      if (!confirm(`删除 ${m} 的可回收 + 过期 chunks？baseline 保留。`)) return;
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = "删除中…";
      try {
        await apiDelete(`/api/rawdata/${encodeURIComponent(m)}`);
      } catch (err) {
        alert(`删除失败: ${err.message || err}`);
        btn.textContent = orig;
        btn.disabled = false;
        return;
      }
      await refreshRawdataOverview();
    });
  });
}

// ── Catalog Mechanic Filters ──────────────────────────────────────

function renderCatalogFilters() {
  const el = byId("catalogFilters");
  if (!el) return;
  // Prefer staticAttrs (survives report deletes); fall back to summary.
  const mechDist = (state.staticAttrs || {}).mechanics_distribution
                || (state.machinesSummary || {}).mechanics_distribution
                || {};
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

  const logicList = m.logicClassNames || [];
  const logicShort = logicList.length <= 3
    ? (logicList.join(", ") || "—")
    : logicList.slice(0, 3).join(", ") + ` · +${logicList.length - 3}`;
  const configMd5 = m.configSummaryMd5 ? m.configSummaryMd5.slice(0, 10) + "…" : "—";
  const codeMd5 = m.codeSummaryMd5 ? m.codeSummaryMd5.slice(0, 10) + "…" : "—";
  const logicTitle = logicList.join(", ");

  byId("machineDetailBody").innerHTML = `
    <div class="detail-meta">
      <div title="${logicTitle}"><span class="detail-label">${fmt("detailLogicClasses")}</span> <code>${logicShort}</code></div>
      <div><span class="detail-label">${fmt("detailConfigMd5")}</span> <code>${configMd5}</code></div>
      <div><span class="detail-label">${fmt("detailCodeMd5")}</span> <code>${codeMd5}</code></div>
      <div><span class="detail-label">${fmt("detailReports")}</span> <span id="detailReportCount">—</span></div>
    </div>
    <div id="rwtree" class="rwtree"><div class="muted">加载 rawdata × report 树…</div></div>`;

  // Load + render the rawdata × report tree async.
  renderRawdataReportTree(machineName);
}

// ── Rawdata × Report tree (step 4–5) ────────────────────────────────
// 4-column grid (mode 1/2/5/7); each column = rawdata stats + reports
// derived from that rawdata. Best-CI report auto-expands. Step 5 adds
// multi-md5 support: when a machine's rawdata carries ≥2 distinct
// (config_md5, code_md5) pairs (server upgraded since last sample),
// a switcher dropdown appears in the header and filters the tree by
// selected md5. "+ 跨版本对比" button enters side-by-side mode for
// cross-version report comparison.
async function renderRawdataReportTree(machineName) {
  const container = byId("rwtree");
  if (!container) return;

  const mConfig = state.machines.find((x) => x.machine === machineName) || {};
  const modes = (mConfig.modes && mConfig.modes.length) ? mConfig.modes : [1, 2, 5, 7];

  // Parallel fetch rawdata + reports + validate (for per-report md5).
  let rawdataModes = {};
  try {
    const data = await apiGet(`/api/rawdata/${encodeURIComponent(machineName)}`);
    rawdataModes = data.modes || {};
  } catch (_) { /* fall-through with empty rawdata */ }

  const [reportsByMode, validateData] = await Promise.all([
    Promise.all(modes.map((mode) =>
      apiGet(`/api/reports/${encodeURIComponent(machineName)}/${mode}`).catch(() => ({ versions: [] }))
    )),
    apiGet(`/api/report-validate/${encodeURIComponent(machineName)}`).catch(() => ({ reports: [] })),
  ]);

  // Fix 2: header "Report 数量" now reads the actual versions fetched,
  // not m.report_count (which counted every versions/* dir including
  // devcache + legacy paths → often wildly off from what the tree shows).
  const totalReports = reportsByMode.reduce((s, r) => s + ((r.versions || []).length), 0);
  const headerCountEl = byId("detailReportCount");
  if (headerCountEl) headerCountEl.textContent = String(totalReports);

  // Map (report_version) → md5 + analyzer status so the tree can
  // filter reports by md5 AND show analyzer-stale badges inline.
  const reportMd5Map = new Map();
  for (const r of (validateData.reports || [])) {
    reportMd5Map.set(r.version, {
      config_md5: r.report_config_md5 || "",
      code_md5: r.report_code_md5 || "",
      md5_status: r.md5_status,
      analyzer_status: r.analyzer_status || "untagged",
      analyzer_version: r.report_analyzer_version || "",
    });
  }

  // Distinct md5s across rawdata versions + reports. If only 1, the
  // switcher stays hidden and the tree renders normally.
  const md5Map = new Map();  // key="cfg|code" → {config_md5, code_md5, is_current, label}
  for (const [, st] of Object.entries(rawdataModes)) {
    for (const v of (st.versions || [])) {
      const key = `${v.config_md5}|${v.code_md5}`;
      if (!md5Map.has(key)) {
        md5Map.set(key, {
          config_md5: v.config_md5, code_md5: v.code_md5,
          is_current: !!v.is_current, source: "rawdata",
        });
      }
    }
  }
  for (const r of (validateData.reports || [])) {
    if (!r.report_config_md5) continue;
    const key = `${r.report_config_md5}|${r.report_code_md5}`;
    if (!md5Map.has(key)) {
      md5Map.set(key, {
        config_md5: r.report_config_md5, code_md5: r.report_code_md5,
        is_current: r.md5_status === "match", source: "report-only",
      });
    }
  }
  const md5Keys = [...md5Map.keys()];
  const multiMd5 = md5Keys.length > 1;

  // Reset md5 selection when switching machines; default to current-md5
  // if available, else first available.
  if (state._rwtreeMachine !== machineName) {
    state._rwtreeMachine = machineName;
    state._rwtreeMd5Key = null;
    state._rwtreeCrossMode = false;
  }
  if (!state._rwtreeMd5Key || !md5Map.has(state._rwtreeMd5Key)) {
    const current = md5Keys.find((k) => md5Map.get(k).is_current);
    state._rwtreeMd5Key = current || md5Keys[0] || null;
  }

  const fInt2 = (n) => Number(n || 0).toLocaleString();
  const fMb = (n) => {
    const mb = Number(n || 0);
    return mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(1)} MB`;
  };

  // Clear compare state when switching machines (tree rebuild).
  if (state.versionHistoryMachine !== machineName) {
    state.compareSelected = new Map();
    state.versionHistoryMachine = machineName;
  }

  // md5 switcher header — only rendered when multiple md5s exist.
  const switcherHtml = multiMd5 ? `
    <div class="rwtree-md5-switcher">
      <span class="muted">rawdata 版本:</span>
      <select id="rwtreeMd5Select">
        ${[...md5Map.entries()].map(([k, v]) => {
          const short = (v.config_md5 || "").slice(0, 8) || "—";
          const tag = v.is_current ? "当前" : "过期";
          return `<option value="${k}" ${k === state._rwtreeMd5Key ? "selected" : ""}>${short}… (${tag})</option>`;
        }).join("")}
      </select>
      <button id="rwtreeCrossBtn" class="small-btn ${state._rwtreeCrossMode ? "active" : ""}" ${md5Keys.length < 2 ? "disabled" : ""}>
        ${state._rwtreeCrossMode ? "↩ 退出跨版本对比" : "+ 跨版本对比"}
      </button>
    </div>
  ` : "";

  // Cross-version mode: render two side-by-side trees. Left=current
  // md5 (or first md5 if none flagged current), right=other md5.
  if (state._rwtreeCrossMode && md5Keys.length >= 2) {
    const currentKey = md5Keys.find((k) => md5Map.get(k).is_current) || md5Keys[0];
    const otherKey = md5Keys.find((k) => k !== currentKey) || md5Keys[1];
    container.classList.add("rwtree-cross");
    container.innerHTML = switcherHtml + `
      <div class="rwtree-cross-pair">
        <div class="rwtree-side" data-side="left">
          <div class="rwtree-side-head">当前 md5 · ${md5Map.get(currentKey).config_md5.slice(0, 10)}…</div>
          <div class="rwtree rwtree-grid" data-md5="${currentKey}"></div>
        </div>
        <div class="rwtree-side" data-side="right">
          <div class="rwtree-side-head">历史 md5 · ${md5Map.get(otherKey).config_md5.slice(0, 10)}…</div>
          <div class="rwtree rwtree-grid" data-md5="${otherKey}"></div>
        </div>
      </div>`;
    container.querySelectorAll(".rwtree-grid").forEach((gridEl) => {
      _renderRwtreeGrid(gridEl, machineName, modes, rawdataModes, reportsByMode,
                        reportMd5Map, md5Map, gridEl.dataset.md5, fInt2, fMb);
    });
    _wireRwtreeSwitcher(machineName);
    _ensureCompareBar(container.parentElement);
    _updateRwtreeCompareBar();
    return;
  }

  // Single-md5 view (default). If no md5s at all, render empty-state.
  container.classList.remove("rwtree-cross");
  container.innerHTML = switcherHtml + `<div class="rwtree rwtree-grid" id="rwtreeSingleGrid"></div>`;
  const grid = byId("rwtreeSingleGrid");
  _renderRwtreeGrid(grid, machineName, modes, rawdataModes, reportsByMode,
                    reportMd5Map, md5Map, state._rwtreeMd5Key, fInt2, fMb);
  _wireRwtreeSwitcher(machineName);
  _ensureCompareBar(container.parentElement);
  _updateRwtreeCompareBar();
}

function _wireRwtreeSwitcher(machineName) {
  byId("rwtreeMd5Select")?.addEventListener("change", (e) => {
    state._rwtreeMd5Key = e.target.value;
    renderRawdataReportTree(machineName);
  });
  byId("rwtreeCrossBtn")?.addEventListener("click", () => {
    state._rwtreeCrossMode = !state._rwtreeCrossMode;
    renderRawdataReportTree(machineName);
  });
}

function _ensureCompareBar(parentEl) {
  if (!parentEl) return;
  let compareBar = byId("rwtreeCompareBar");
  if (!compareBar) {
    compareBar = document.createElement("div");
    compareBar.id = "rwtreeCompareBar";
    compareBar.className = "rwtree-compare-bar hidden";
    parentEl.appendChild(compareBar);
  }
}

// Core per-grid renderer. Filters rawdata + reports by selectedMd5Key.
// Used for both the single-md5 tree and each side of the cross-version
// parallel pair.
function _renderRwtreeGrid(gridEl, machineName, modes, rawdataModes, reportsByMode,
                           reportMd5Map, md5Map, selectedMd5Key, fInt2, fMb) {
  const selected = selectedMd5Key ? md5Map.get(selectedMd5Key) : null;
  const matchMd5 = (cfg, code) => !selected
    || (cfg === selected.config_md5 && code === selected.code_md5);

  gridEl.innerHTML = modes.map((mode, i) => {
    const st = rawdataModes[String(mode)] || {};
    const versionsAll = Array.isArray(st.versions) ? st.versions : [];
    // Filter chunk versions to the selected md5; recompute classified
    // counts from filtered entries so per-column totals only show
    // chunks that belong to this md5.
    const versions = versionsAll.filter((v) => matchMd5(v.config_md5, v.code_md5));
    // Fix 3: chunk COUNTS are meaningless (each chunk has different
    // spin_times); operator tracks the retention quota in SPINS. Use
    // kept_spins / deletable_spins / stale_spins instead.
    const keptSpins = versions.reduce((s, v) => s + (v.kept_spins || 0), 0);
    const delSpins = versions.reduce((s, v) => s + (v.deletable_spins || 0), 0);
    const staleSpins = versions.reduce((s, v) => s + (v.stale_spins || 0), 0);
    const totalSpins = keptSpins + delSpins + staleSpins;
    const keptChunks = versions.reduce((s, v) => s + (v.kept_chunks || 0), 0);
    const delChunks = versions.reduce((s, v) => s + (v.deletable_chunks || 0), 0);
    const staleChunks = versions.reduce((s, v) => s + (v.stale_chunks || 0), 0);
    const totalChunks = keptChunks + delChunks + staleChunks;
    const hasCurrent = versions.some((v) => v.is_current);
    const hasStale = versions.some((v) => !v.is_current);

    let statusTag;
    if (totalChunks === 0) {
      statusTag = `<span class="rwtree-status none">无</span>`;
    } else if (hasCurrent && !hasStale) {
      statusTag = `<span class="rwtree-status ok">✅当前</span>`;
    } else if (hasStale && !hasCurrent) {
      statusTag = `<span class="rwtree-status warn">⚠失配</span>`;
    } else {
      statusTag = `<span class="rwtree-status mixed">⚠混合</span>`;
    }

    // Filter reports to those matching the selected md5. Reports with
    // no md5 info (md5_status "untagged", pre-MD5-tagging migration)
    // are ALWAYS shown — otherwise they'd silently disappear just
    // because the tree happens to have a selected md5 key.
    const allReports = reportsByMode[i].versions || [];
    const filteredReports = allReports.filter((v) => {
      const info = reportMd5Map.get(v.report_version);
      if (!info) return true;
      if (info.md5_status === "untagged") return true;
      return matchMd5(info.config_md5, info.code_md5);
    });

    // Fix 3: surface RTP / CI inferred from the best-CI FRESH report
    // (analyzer+md5 both match current) as the de-facto "current
    // sample RTP/CI". If no fresh report exists, tell the operator to
    // ⟳ 生成 Report. Re-running analyzer would compute exactly this —
    // for reasonable dev / prod fleets, the O(N chunks) re-parse is a
    // user-initiated action, not something to do on every page load.
    const freshReports = filteredReports.filter((v) => {
      const info = reportMd5Map.get(v.report_version);
      return info && info.md5_status === "match" && info.analyzer_status === "match";
    });
    const bestFresh = freshReports.slice().sort((a, b) => {
      const ca = a.achieved_halfwidth_pp ?? Infinity;
      const cb = b.achieved_halfwidth_pp ?? Infinity;
      return ca - cb;
    })[0];
    let rawdataApprox = "";
    if (totalChunks > 0) {
      if (bestFresh) {
        const rtp = bestFresh.achieved_rtp_pct != null
          ? bestFresh.achieved_rtp_pct.toFixed(2) + "%" : "—";
        const ci = bestFresh.achieved_halfwidth_pp != null
          ? "±" + bestFresh.achieved_halfwidth_pp.toFixed(2) + "pp" : "—";
        rawdataApprox = `<div class="rwtree-rawdata-approx" title="基于最新 fresh report（analyzer+md5 都匹配当前）">
          样本 RTP <b>${rtp}</b> · CI <b>${ci}</b>
        </div>`;
      } else {
        rawdataApprox = `<div class="rwtree-rawdata-approx muted" title="需要 analyzer+md5 都匹配当前的 report 才能显示 RTP/CI">
          <i>无 fresh report — 生成后会显示 RTP/CI</i>
        </div>`;
      }
    }

    const isLocked = !!st.locked;
    const lockIcon = isLocked ? "🔒" : "🔓";
    const lockTitle = isLocked
      ? "已上锁：auto-cleanup 不会删这些 chunks（即使超过 retention）"
      : "未上锁：超过 retention 的 chunks 可能被 auto-cleanup 自动删除";
    const rawdataBlock = totalChunks === 0
      ? `<div class="rwtree-rawdata empty"><div class="muted">无本地 rawdata</div></div>`
      : `<div class="rwtree-rawdata ${isLocked ? "rwtree-locked" : ""}">
          <div class="rwtree-rawdata-line">
            <b>${fInt2(totalSpins)}</b> spins
            <span class="muted">(${totalChunks} chunks)</span>
          </div>
          <div class="rwtree-rawdata-line muted">
            保底 ${fInt2(keptSpins)} / 可回收 ${fInt2(delSpins)}${staleSpins ? ` / 过期 ${fInt2(staleSpins)}` : ""}
          </div>
          ${rawdataApprox}
          <div class="rwtree-rawdata-actions">
            <button class="small-btn primary-btn rwtree-gen-btn" data-machine="${machineName}" data-mode="${mode}" data-intrinsic-disabled="${(keptChunks + delChunks) === 0 ? "1" : ""}" ${((keptChunks + delChunks) === 0 || _isAnyBusy()) ? "disabled" : ""} title="用当前 analyzer 从这些 chunks 生成新 report">⟳ 生成 Report</button>
            <button class="small-btn rwtree-lock-btn ${isLocked ? "active" : ""}" data-machine="${machineName}" data-mode="${mode}" data-locked="${isLocked ? "1" : "0"}" title="${lockTitle}">${lockIcon} ${isLocked ? "已锁" : "锁定"}</button>
          </div>
        </div>`;

    // Sort versions by CI ascending (smallest first); fallback by
    // report_version reverse-alphabetical (newer first).
    const sortedReports = [...filteredReports].sort((a, b) => {
      const ca = a.achieved_halfwidth_pp;
      const cb = b.achieved_halfwidth_pp;
      if (ca != null && cb != null) return ca - cb;
      if (ca != null) return -1;
      if (cb != null) return 1;
      return (b.report_version || "").localeCompare(a.report_version || "");
    });
    const bestCiVersion = sortedReports[0]?.report_version;

    // Sort for display: newest first (so operator sees recent at top).
    const displayReports = [...sortedReports].sort(
      (a, b) => (b.report_version || "").localeCompare(a.report_version || "")
    );
    const reportsBlock = displayReports.length === 0
      ? `<div class="rwtree-reports empty"><div class="muted">无 report</div></div>`
      : `<div class="rwtree-reports">
          <div class="rwtree-reports-head">reports (${displayReports.length})</div>
          ${displayReports.map((v) => {
            const rv = v.report_version || "?";
            const rid = v.run_id || "";
            const rtp = v.achieved_rtp_pct != null ? v.achieved_rtp_pct.toFixed(2) + "%" : "—";
            const ci = v.achieved_halfwidth_pp != null ? "±" + v.achieved_halfwidth_pp.toFixed(2) + "pp" : "—";
            const spins = v.total_spins != null ? fInt2(v.total_spins) : "—";
            const quality = v.quality_label || "";
            const ts = rv.match(/rv_(\d{8})/)?.[1] || "";
            const tsShort = ts ? `${ts.slice(4, 6)}-${ts.slice(6, 8)}` : rv.slice(3, 11);
            const isBest = rv === bestCiVersion;
            const expanded = isBest ? " expanded" : "";
            const checked = (state.compareSelected || new Map()).has(rv) ? "checked" : "";
            // Fix 4: restore analyzer-status badge so operators can see
            // at a glance which reports are stale vs current analyzer.
            const info = reportMd5Map.get(rv) || {};
            const analyzerStatus = info.analyzer_status || "untagged";
            let analyzerBadge = "";
            if (analyzerStatus === "outdated") {
              analyzerBadge = `<span class="rwtree-analyzer-badge stale" title="analyzer 版本已过期（report=${info.analyzer_version?.slice(0,10) || "?"}），建议重新生成">⚠</span>`;
            } else if (analyzerStatus === "untagged") {
              analyzerBadge = `<span class="rwtree-analyzer-badge untagged" title="report 未标记 analyzer 版本">·</span>`;
            }
            return `<div class="rwtree-report${expanded}" data-rv="${rv}">
              <div class="rwtree-report-summary">
                <input type="checkbox" class="rwtree-compare-check" data-rv="${rv}" data-mode="${mode}" ${checked} title="勾选以对比版本" />
                <span class="rwtree-report-date">${tsShort}</span>
                <span class="rwtree-report-rtp">${rtp}</span>
                <span class="rwtree-report-ci">${ci}</span>
                ${analyzerBadge}
                ${isBest ? '<span class="rwtree-best-tag" title="当前最佳 CI">⭐</span>' : ''}
              </div>
              <div class="rwtree-report-details">
                <div class="rwtree-kv"><span>Spins</span><span>${spins}</span></div>
                <div class="rwtree-kv"><span>Quality</span><span>${quality || "—"}</span></div>
                <div class="rwtree-kv"><span>Analyzer</span><span title="report 生成时的 analyzer 代码版本">${info.analyzer_version?.slice(0,10) || "—"} <span class="muted">(${analyzerStatus === "match" ? "当前" : analyzerStatus === "outdated" ? "⚠ 过期" : "未标记"})</span></span></div>
                <div class="rwtree-report-actions">
                  <button class="small-btn rwtree-load-btn" data-run-id="${rid}" ${rid ? "" : "disabled"} title="${rid ? "" : "该 report 无 run_id 记录，无法加载（可以直接删除）"}">载入调试</button>
                  <button class="small-btn danger-btn rwtree-delete-btn" data-run-id="${rid}" data-rv="${rv}" data-mode="${mode}" title="删除此 report 版本">🗑 删除</button>
                </div>
              </div>
            </div>`;
          }).join("")}
        </div>`;

    return `<div class="rwtree-col" data-mode="${mode}">
      <div class="rwtree-col-head">
        <span class="rwtree-mode-label">Mode ${mode}</span>
        ${statusTag}
      </div>
      ${rawdataBlock}
      ${reportsBlock}
    </div>`;
  }).join("");

  // Wire buttons + checkboxes on the freshly-rendered grid. Uses
  // gridEl (not parent container) so cross-version mode's two sides
  // attach their listeners independently.
  gridEl.querySelectorAll(".rwtree-report-summary").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.matches("input[type=checkbox]")) return;
      row.parentElement.classList.toggle("expanded");
    });
  });
  gridEl.querySelectorAll(".rwtree-compare-check").forEach((cb) => {
    cb.addEventListener("change", () => {
      const rv = cb.dataset.rv;
      if (cb.checked) state.compareSelected.set(rv, { mode: Number(cb.dataset.mode) });
      else state.compareSelected.delete(rv);
      _updateRwtreeCompareBar();
    });
  });
  gridEl.querySelectorAll(".rwtree-lock-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const m = btn.dataset.machine;
      const mo = btn.dataset.mode;
      const locked = btn.dataset.locked === "1";
      const orig = btn.textContent;
      btn.disabled = true;
      btn.textContent = locked ? "解锁中…" : "上锁中…";
      try {
        const path = `/api/rawdata/${encodeURIComponent(m)}/mode/${encodeURIComponent(mo)}/lock`;
        if (locked) {
          await apiDelete(path);
        } else {
          await apiPost(path, {});
        }
        // Re-render the tree to pick up the new lock state.
        await renderRawdataReportTree(m);
      } catch (err) {
        alert(`${locked ? "解锁" : "上锁"}失败: ${err.message || err}`);
        btn.textContent = orig;
        btn.disabled = false;
      }
    });
  });
  gridEl.querySelectorAll(".rwtree-gen-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const m = btn.dataset.machine, mo = btn.dataset.mode;
      const orig = btn.textContent;
      btn.disabled = true;
      btn.textContent = "生成中… (后台)";
      try {
        await apiPost(
          `/api/rawdata/${encodeURIComponent(m)}/generate-report`,
          { mode: Number(mo), async: true },
        );
        btn.textContent = "⏳ 已入队";
        await refreshRunList(false);
        setTimeout(() => renderRawdataReportTree(m), 3000);
      } catch (err) {
        alert(`生成 Report 失败: ${String(err && err.message ? err.message : err)}`);
        btn.textContent = orig;
        btn.disabled = false;
      }
    });
  });
  gridEl.querySelectorAll(".rwtree-load-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const rid = btn.dataset.runId;
      if (!rid) return;
      state.currentRunId = rid;
      switchTab("debug");
      await refreshCurrentRun();
    });
  });
  gridEl.querySelectorAll(".rwtree-delete-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const rv = btn.dataset.rv;
      const mode = btn.dataset.mode;
      if (!rv || !mode) return;
      if (state.systemState?.operation_busy) {
        alert("有操作进行中，请等待完成再删除。");
        return;
      }
      if (!confirm(`删除 report ${rv}？此操作不可撤销。`)) return;
      const orig = btn.textContent;
      btn.disabled = true;
      btn.textContent = "删除中…";
      try {
        // Route through the report-version endpoint so orphan disk
        // versions (no DB row — common after the aggressive cleanup)
        // still delete cleanly. Endpoint also cascades the DB row
        // when one exists.
        await apiDelete(
          `/api/reports/${encodeURIComponent(machineName)}/${encodeURIComponent(mode)}/${encodeURIComponent(rv)}`,
        );
        state.compareSelected?.delete?.(rv);
        await renderRawdataReportTree(machineName);
        refreshReportMgmtBanner();  // stale count likely changed
      } catch (err) {
        alert("删除失败: " + (err.message || err));
        btn.disabled = false;
        btn.textContent = orig;
      }
    });
  });
}

function _updateRwtreeCompareBar() {
  const bar = byId("rwtreeCompareBar");
  if (!bar) return;
  const n = (state.compareSelected || new Map()).size;
  // Show bar on ≥1 to enable 批量删除; 对比 itself needs ≥2.
  if (n < 1) {
    bar.classList.add("hidden");
    bar.innerHTML = "";
    return;
  }
  bar.classList.remove("hidden");
  bar.innerHTML = `
    <span>已选 ${n} 个 report</span>
    <button class="primary-btn small-btn" id="rwtreeCompareRunBtn" ${n === 2 ? "" : "disabled"} title="恰好选中 2 个 report 才能对比">对比${n === 2 ? " (2/2)" : ""}</button>
    <button class="small-btn danger-btn" id="rwtreeBatchDeleteBtn">🗑 批量删除 (${n})</button>
    <button class="small-btn" id="rwtreeCompareClearBtn">清除</button>`;
  byId("rwtreeCompareRunBtn")?.addEventListener("click", () => {
    compareReports();
  });
  byId("rwtreeBatchDeleteBtn")?.addEventListener("click", async () => {
    if (state.systemState?.operation_busy) {
      alert("有操作进行中，请等待完成再删除。");
      return;
    }
    const entries = [...(state.compareSelected || new Map()).entries()];
    if (!entries.length) return;
    if (!confirm(`批量删除 ${entries.length} 个 report？此操作不可撤销。`)) return;
    // Each entry: [rv, {mode}]. Use the report-version endpoint so
    // orphan disk versions (no DB row) delete cleanly too.
    const machine = state.focusedMachine;
    if (!machine) return;
    let done = 0;
    let failed = 0;
    for (const [rv, meta] of entries) {
      const mode = meta?.mode;
      if (!mode) { failed += 1; continue; }
      try {
        await apiDelete(
          `/api/reports/${encodeURIComponent(machine)}/${encodeURIComponent(mode)}/${encodeURIComponent(rv)}`,
        );
        done += 1;
      } catch (_) {
        failed += 1;
      }
    }
    state.compareSelected = new Map();
    await renderRawdataReportTree(machine);
    refreshReportMgmtBanner();
    const msg = failed > 0
      ? `批量删除: ${done} 成功 / ${failed} 失败`
      : `批量删除完成: ${done} 个 report`;
    alert(msg);
  });
  byId("rwtreeCompareClearBtn")?.addEventListener("click", () => {
    state.compareSelected = new Map();
    document.querySelectorAll(".rwtree-compare-check").forEach((cb) => { cb.checked = false; });
    _updateRwtreeCompareBar();
  });
}

// _loadRawdataSection removed 2026-04-19 — the master/detail refactor
// (step 4+6) replaced the stacked per-machine rawdata cards with the
// rwtree 4-column grid + the global rawdata banner/detail table.
// Delete lives on the batch action bar (focus/multi) and the global
// detail rows; single-focus detail is READ-ONLY per design.

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

  // Step 3 (2026-04-19 round 6): surface MD5 drift from static attrs
  // cache. Machine's cached config_md5/code_md5 differs from current
  // machines.json → the cached features/mechanics may be stale for
  // that machine. Banner line + [刷新 MD5] reminder.
  const drift = ((state.staticAttrs || {}).drift) || [];
  const driftHtml = drift.length
    ? `<div class="fleet-headline fleet-headline-warn">
        <strong>⚠ ${drift.length} 台机台版本变更</strong>
        <span class="muted">— 属性缓存可能过期: ${drift.slice(0, 8).join(", ")}${drift.length > 8 ? ` +${drift.length - 8}` : ""}</span>
        <button id="fleetDriftRefreshBtn" class="small-btn" style="margin-left:8px">刷新 MD5 + 属性</button>
      </div>`
    : "";

  el.innerHTML = `
    <div class="fleet-summary-row">
      <strong>${total}</strong> ${fmt("fleetTotal")} · <strong>${withReports}</strong> ${fmt("fleetWithReports")}
      <a href="/api/fleet/export-csv" class="small-btn" download="fleet_summary.csv" style="margin-left:8px">${fmt("btnExportCsv")}</a>
    </div>
    <div class="fleet-categories">${catBadges}</div>
    <div class="fleet-headlines">${driftHtml}${headlineHtml}</div>`;

  byId("fleetDriftRefreshBtn")?.addEventListener("click", async () => {
    const btn = byId("fleetDriftRefreshBtn");
    if (btn) { btn.disabled = true; btn.textContent = "刷新中…"; }
    try {
      // Refresh server-side machines.json MD5s from upstream + reload
      // static attrs. Feature/mechanic lists auto-refresh on the next
      // generate-report; no need to force-regen here.
      await apiPost("/api/servers/refresh-md5", {});
    } catch (_) { /* non-fatal */ }
    try {
      const [m, attrs] = await Promise.all([
        apiGet("/api/machines"),
        apiGet("/api/machines/static"),
      ]);
      state.machines = m.machines || [];
      state.staticAttrs = attrs;
    } catch (_) {}
    renderMachineCatalog();
    renderFleetOverview();
    renderCatalogFeatureChips();
  });
}

// ── Batch Run UI ──────────────────────────────────────────────────

// ── Inline Sampling Panel ─────────────────────────────────────────

function updateSampleHint() {
  const countEl = byId("sampleSelectedCount");
  const btn = byId("sampleStartBtn");
  const hint = byId("sampleHint");
  const bar = byId("batchActionBar");
  const mode = parseInt(byId("sampleMode")?.value || "2");
  const ciSel = byId("sampleCi");
  const effective = _effectiveSelectedMachines();
  const n = effective.length;

  // Batch bar visibility: show whenever there IS a selection (focus
  // OR multi) OR a sampling batch is in flight. The in-flight rule
  // fixes a bug where operator would start batch, unfocus the
  // machine, and the whole bar (including 停止 btn) disappeared —
  // forcing a page refresh / kill to stop the batch (2026-04-20 r5).
  const hasSelection = n > 0;
  const samplingActive = !!state.activeBatchId;
  if (bar) bar.classList.toggle("hidden", !hasSelection && !samplingActive);

  if (countEl) {
    if (state.focusedMachine) {
      countEl.textContent = `聚焦 ${state.focusedMachine}`;
    } else if (n > 0) {
      countEl.textContent = `批量: 已选 ${n} 台`;
    } else if (samplingActive) {
      countEl.textContent = "⏳ 采样中";
    } else {
      countEl.textContent = "";
    }
  }

  // Fix 3 (2026-04-19 round 4): batch-only buttons hide in focus mode.
  // 批量生成 Report is redundant when focused because the rwtree has
  // per-mode 生成 Report buttons. Sampling + autotune + delete-rawdata
  // still meaningful for single-machine (scoped to focused machine).
  const batchGenBtn = byId("batchGenerateBtn");
  if (batchGenBtn) {
    if (state.focusedMachine) batchGenBtn.classList.add("hidden");
    else batchGenBtn.classList.remove("hidden");
  }
  // Sampling label reflects scope: single machine vs batch.
  const startBtn = byId("sampleStartBtn");
  if (startBtn) {
    startBtn.textContent = state.focusedMachine ? "▶ 开始采样 (本机)" : (n > 1 ? `▶ 批量采样 (${n})` : "▶ 开始采样");
  }

  // Mode 2/5 can't use CI-based stopping (RTP high-volatility makes
  // the halfwidth unreliable). Auto-select "指定采样次数" and lock
  // the dropdown; operator can still tune the spin count.
  if (ciSel) {
    const isLucky = mode === 2 || mode === 5;
    if (isLucky) {
      ciSel.value = "count";
      ciSel.disabled = true;
    } else {
      ciSel.disabled = false;
    }
  }

  // Toggle visibility of spin-count input + strategy toggle based
  // on whether the "指定采样次数" mode is active.
  const ciValue = byId("sampleCi")?.value || "0.5";
  const isCount = ciValue === "count";
  byId("sampleCountLabel")?.classList.toggle("hidden", !isCount);
  byId("sampleStrategyLabel")?.classList.toggle("hidden", !isCount);

  // Hint text based on mode + whether there's a tuned param set for
  // the first selected machine + current mode.
  if (hint) {
    let lines = [];
    if (mode === 2 || mode === 5) {
      lines.push(`Mode ${mode} 为幸运模式（RTP 高波动），仅支持「指定采样次数」模式`);
    }
    if (isCount) {
      const spinCount = parseInt(byId("sampleSpinCount")?.value || "10000");
      const strategy = byId("sampleStrategy")?.value || "total";
      const strategyLabel = strategy === "total"
        ? "总量（已有缓存够就跳过）"
        : "增量（在现有缓存基础上再加）";
      lines.push(`目标 ${spinCount.toLocaleString()} spins · ${strategyLabel}`);
    } else {
      const ci = parseFloat(ciValue || "0.5");
      lines.push(`目标 ±${ci}pp 精度，上限 10M spins`);
    }
    // Show whether the upcoming 开始采样 will use tuned params (from
    // a previous 调参 click on the first effective machine + this mode)
    // or the hardcoded preset (robot_count=20, batch_concurrency=2).
    if (n > 0) {
      const firstMachine = effective[0];
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
  // Effective set: focused machine (single) OR multi-selected (all).
  // Focus and multi are mutually exclusive (see click model).
  const selected = _effectiveSelectedMachines();
  if (!selected.length) { if (btn) btn.disabled = false; return; }
  const mode = parseInt(byId("sampleMode")?.value || "2");
  const ciRaw = byId("sampleCi")?.value || "0.5";
  // "count" → operator-specified spin-count mode (replaces old Fuzzy).
  // Mode 2/5 forces count-mode (CI unreliable for lucky modes).
  let ciMode;
  let ci = 0;
  if (ciRaw === "count" || mode === 2 || mode === 5) {
    ciMode = "count";
  } else {
    ciMode = "ci";
    ci = parseFloat(ciRaw);
  }
  const spinCount = parseInt(byId("sampleSpinCount")?.value || "10000");
  const samplingStrategy = byId("sampleStrategy")?.value || "total";

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

  // max_chunks derivation depends on mode:
  //   - CI mode: budget-cap at ~10M spins using chunk averages
  //   - count mode: ceil(spinCount / (chunk_spin_times × robot_count))
  //     using the average chunk size across selected machines
  const avgChunk = items.reduce((s, i) => s + i.chunk_spin_times, 0) / items.length;
  let max_chunks;
  let target_halfwidth_pp;
  if (ciMode === "count") {
    max_chunks = Math.max(1, Math.ceil(spinCount / (chunk_robot_count * avgChunk)));
    // 0.001 is the never-reachable sentinel — makes max_chunks the
    // sole stop gate. Avoids the target=999 early-stop pitfall.
    target_halfwidth_pp = 0.001;
  } else {
    max_chunks = Math.floor(10_000_000 / (chunk_robot_count * avgChunk));
    target_halfwidth_pp = ci;
  }

  const payload = {
    items,
    concurrency: batch_concurrency,
    chunk_spin_times: 1000,  // overridden per-item below (not yet supported, needs backend update)
    chunk_robot_count,
    max_chunks,
    target_halfwidth_pp,
    batch_concurrency,
    timeout: 300,
    auto_cleanup_cache: ciMode !== "count",
    sampling_strategy: ciMode === "count" ? samplingStrategy : "total",
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
        renderRtpModeBar();  // fleet mode set may have grown post-sampling
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

// showVersionHistory / loadVersionsForMode / updateCompareBtn removed
// 2026-04-19 — the rwtree (step 4+5) inlines per-mode report listing
// + CI-sorted expansion + md5 filtering + compare checkboxes. The
// old versionHistoryPanel DOM is dropped from the HTML in step 8.

async function compareReports() {
  // state.compareSelected is Map<version, {mode}> — each entry knows
  // its own mode (can span different modes or md5 versions).
  const entries = [...(state.compareSelected || new Map()).entries()];
  if (entries.length !== 2) return;
  const machine = state.versionHistoryMachine || state.focusedMachine;
  if (!machine) return;
  const panel = byId("reportComparisonPanel");
  const body = byId("comparisonBody");
  panel.classList.remove("hidden");
  body.innerHTML = `<div class="muted">Loading...</div>`;

  try {
    const [[vA, metaA], [vB, metaB]] = entries;
    const [a, b] = await Promise.all([
      apiGet(`/api/reports/${machine}/${metaA.mode}/${vA}`),
      apiGet(`/api/reports/${machine}/${metaB.mode}/${vB}`),
    ]);
    renderComparison(a, b, vA, vB);
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

// updateBatchBar / renderRunHistory removed 2026-04-19 — run-history
// big table retired from the manage tab. The per-machine rwtree +
// global rawdata detail now own the "what ran / load this version"
// surface; delete-run is invoked indirectly via delete-rawdata in
// the batch action bar. Calls sites that still invoke
// renderRunHistory() are no-oped below.
function renderRunHistory() { /* retired — see above */ }
function updateBatchBar() { /* retired */ }

// renderPayoutGroupDrilldown was retired on 2026-04-20 round 2 —
// the Pay ID depth table was merged into the unified Pay ID 总览
// panel (see renderPayIdOverview). Helper retained as a no-op so
// older call sites wouldn't break, but there are none left.
function renderPayoutGroupDrilldown(_summary) { /* retired */ }

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
      // Prefix a source badge on the top-symbols cell so 策划 can tell
      // at a glance whether the symbol list is authoritative (from
      // RewardLastNode codes) or heuristic (left-3-col intersection).
      const src = r.top_symbols_source;
      const srcBadge = src === "rln"
        ? `<span class="tsym-src tsym-src-rln" title="${_escHtml(fmt("topSymSourceRlnTooltip"))}">${_escHtml(fmt("topSymSourceRln"))}</span>`
        : src === "heuristic"
          ? `<span class="tsym-src tsym-src-h" title="${_escHtml(fmt("topSymSourceHeurTooltip"))}">${_escHtml(fmt("topSymSourceHeur"))}</span>`
          : "";
      // Decorate the payline_id with the -1 / -2 scatter legend.
      const plineBadge = _lineIdSignBadge(
        r.payline_id_num < 0 ? "negative" : "positive",
        Number.isFinite(r.payline_id_num) ? r.payline_id_num : null,
      );
      return (
        `<tr>` +
        `<td><code>${_escHtml(r.payline_id)}</code> ${plineBadge}</td>` +
        `<td>${fInt(r.hit_count)}</td>` +
        `<td>${r.hit_rate_pct.toFixed(3)}%</td>` +
        `<td class="bar-cell" style="--bar:${barPct.toFixed(1)}%">${r.rtp_contribution_pp.toFixed(4)}</td>` +
        `<td>${r.win_share_pct.toFixed(2)}%</td>` +
        `<td>${srcBadge}${topSyms}</td>` +
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

  // Block order reshuffled (2026-04-20 round 2) per 策划 feedback:
  // feature-mode rule delta (when present) is the highest-value
  // signal — "bonus modes use different payline rules from paid" is
  // the question the operator is usually answering when they open
  // this panel. Channel split comes next for the current mode, then
  // the cross-mode label table as reference context at the bottom.
  body.innerHTML = `
    ${deltaHtml}
    ${channelHtml}
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
// Unified "Pay ID 总览" — merges the live analyzer's payout_ids
// rows (frequency + RTP contribution) with the offline shape
// inference script's per-pay_id shape signature (symbol set, wild
// substitution rate, line sign, col coverage, confidence) so 策划
// can eyeball one row per pay_id without JOINing across panels.
//
// Shape data source: /api/paytables/{m}/mode/{n}/shape (produced by
// scripts/infer_paytable.py, auto-triggered post generate-report).
// Frequency data source: summary.player_impact.payout_ids_top20.
//
// Separately: the wild-evidence sub-table (symbol-level, not
// pay_id-level) keeps its own sub-section at the top so 策划 can
// see wild auto-detection signals before reading the shape rows.
async function renderPayIdOverview(summary) {
  const panel = byId("payIdOverviewPanel");
  if (!panel) return;
  const body = byId("payIdOverviewBody");
  const s = summary || {};
  const machine = s.machine;
  const mode = Number(s.mode);
  const payoutRows = (s.player_impact || {}).payout_ids_top20 || [];
  if (!machine || !mode || !Array.isArray(payoutRows) || !payoutRows.length) {
    panel.classList.add("hidden");
    body.innerHTML = "";
    return;
  }

  let shapeData = null;
  try {
    shapeData = await apiGet(
      `/api/paytables/${encodeURIComponent(machine)}/mode/${mode}/shape`,
    );
  } catch (_err) {
    shapeData = null;
  }
  const shapeRows = (shapeData && Array.isArray(shapeData.rows))
    ? shapeData.rows
    : [];
  const shapeByPayId = new Map();
  for (const r of shapeRows) {
    shapeByPayId.set(String(r.pay_id), r);
  }
  const wildReviewNeeded = Boolean(
    shapeData && shapeData.wild_inference && shapeData.wild_inference.review_needed,
  );

  panel.classList.remove("hidden");

  // Wild inference sub-section (symbol-level; unrelated to pay_id
  // rows). Kept visible at the top so 策划 sees "inferred wilds: X,
  // Y" before reading the per-pay_id shape column.
  const wi = (shapeData && shapeData.wild_inference) || null;
  const wildsStr = wi && Array.isArray(wi.wilds) && wi.wilds.length
    ? wi.wilds.map(_escHtml).join(", ")
    : "—";
  const wildStatus = (wi && wi.status) || "undetermined";
  let wildStatusColor = "#6b7f90";
  let wildStatusEmoji = "·";
  if (wildStatus === "inferred") { wildStatusColor = "#2e7d32"; wildStatusEmoji = "✓"; }
  else if (wildStatus === "partial") { wildStatusColor = "#c88a00"; wildStatusEmoji = "≈"; }
  else if (wildStatus === "undetermined") { wildStatusColor = "#888"; wildStatusEmoji = "?"; }
  const grid = (shapeData && shapeData.grid) || {};
  const gridStr = grid.n_cols && grid.n_rows ? `${grid.n_cols}×${grid.n_rows}` : "—";
  const chunksStr = (shapeData && shapeData.chunks_scanned != null)
    ? ` · ${shapeData.chunks_scanned} chunks scanned`
    : "";
  const headerHtml =
    `<div class="shape-header">` +
    `<span>${_escHtml(fmt("payIdGridLabel"))}: ${_escHtml(gridStr)}${_escHtml(chunksStr)}</span>` +
    `<span class="shape-wild-status" style="color:${wildStatusColor}">` +
    `${wildStatusEmoji} ${_escHtml(fmt("payIdWildInferLabel"))}: ${_escHtml(wildStatus)} — ${wildsStr}` +
    `</span></div>`;
  const reviewBanner = wildReviewNeeded
    ? `<div class="shape-warn">⚠ ${_escHtml(fmt("payIdWildReviewNeeded"))}</div>`
    : "";
  const flags = (shapeData && Array.isArray(shapeData.machine_flags)) ? shapeData.machine_flags : [];
  const flagsBanner = flags.length
    ? `<div class="shape-flag">🚩 ${flags.map(_escHtml).join(" · ")}</div>`
    : "";
  const noShapeBanner = !shapeData || shapeData.status === "not_run"
    ? `<div class="shape-warn">⚠ ${_escHtml(fmt("payIdShapeNotRun"))}</div>`
    : "";

  // Wild evidence: symbol-level table (unchanged from prior panel).
  const ev = (wi && wi.evidence) || {};
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
    ? `<details class="payid-wild-evidence"><summary>${_escHtml(fmt("payIdWildEvidenceLabel"))}</summary>
       <table class="drilldown-table">
         <thead><tr>
           <th>symbol</th><th>conf</th><th>mono</th><th>sub</th><th>paying</th><th>score</th><th>reason</th>
         </tr></thead>
         <tbody>${evRows}</tbody>
       </table></details>`
    : "";

  // Unified pay_id overview rows. Sort by RTP contribution (primary
  // 策划 sort — "what contributes most to the machine's RTP?"); pay_ids
  // present only in shape (zero hits in this sample) land at the bottom.
  const maxRtp = Math.max(
    ...payoutRows.map((r) => Number(r.rtp_contribution_pp || 0)),
    0.001,
  );
  const categoryBadge = (cat) => {
    if (cat === "paid") return `<span class="pid-cat pid-cat-paid">${_escHtml(fmt("payIdCatPaid"))}</span>`;
    if (cat === "bonus") return `<span class="pid-cat pid-cat-bonus">${_escHtml(fmt("payIdCatBonus"))}</span>`;
    if (cat === "mixed") return `<span class="pid-cat pid-cat-mixed">${_escHtml(fmt("payIdCatMixed"))}</span>`;
    return `<span class="pid-cat pid-cat-unknown">—</span>`;
  };

  // Bet denominator for multiplier column. Analyzer writes it under
  // summary.sampling.bet; fall back to 1000 (the default CLI bet) if
  // the field is missing from older reports.
  const bet = Number(((summary || {}).sampling || {}).bet) || 1000;
  const fmtMult = (avgWin) => {
    const m = Number(avgWin || 0) / bet;
    if (!Number.isFinite(m) || m === 0) return "—";
    // ≥10× → 1 decimal; smaller → 2 decimals for readability.
    return m >= 10 ? `${m.toFixed(1)}×` : `${m.toFixed(2)}×`;
  };

  const rows = payoutRows.map((pr) => {
    const pid = String(pr.payout_id);
    const shape = shapeByPayId.get(pid) || null;
    const sh = shape && shape.shape ? shape.shape : {};
    const symSet = Array.isArray(sh.symbol_set) ? sh.symbol_set : [];
    const mc = shape ? (shape.match_count ?? "—") : "—";
    const symDisplay = symSet.length
      ? `${mc}× ${symSet.map(_escHtml).join(" / ")}`
      : "—";
    const cols = Array.isArray(sh.position_cols_covered) ? sh.position_cols_covered : [];
    const colStr = cols.length ? cols.join(",") : "—";
    const lineSign = sh.line_id_sign || "—";
    const lineBadge = _lineIdSignBadge(lineSign, Number(pid));
    const notes = Array.isArray(sh.notes) && sh.notes.length
      ? sh.notes.map(_escHtml).join("; ")
      : "";
    const rtpPp = Number(pr.rtp_contribution_pp || 0);
    const bar = Math.min(100, (rtpPp / maxRtp) * 100);
    const cat = pr.spin_type_category;
    const firesRaw = shape ? Number(shape.fires || 0) : null;
    const firesAttr = firesRaw != null
      ? ` title="rawdata fires: ${firesRaw.toLocaleString()} (script scan; includes bonus-round appearances)"`
      : "";
    const mainMult = fmtMult(pr.avg_win_when_hit);
    // Composition sub-rows — every pay_id with ≥2 distinct symbol
    // tuples emits one sub-row per composition. For Bar/7 pays with
    // wild substitutions this shows each (base + wild) variant's
    // own multiplier; for all-wild pays it splits e.g. 3 DD vs
    // 2DD+1TD vs 1DD+2TD. Trailing "其他 N 种组合" row collapses the
    // long-tail (script caps display at 10 + 1 aggregate).
    const breakdown = Array.isArray(sh.composition_breakdown)
      ? sh.composition_breakdown
      : (Array.isArray(sh.wild_composition_breakdown)
        ? sh.wild_composition_breakdown
        : null);
    const hasBreakdown = breakdown && breakdown.length >= 2;
    // 策划 wants per-sub-row share of the pay_id's TOTAL win amount:
    // "the slice of RTP contribution each composition explains". Sum
    // is the sample-observed win total across every composition under
    // this (pay_id, match_count). The tail "其他 N 种组合" row is
    // included in the sum since its rows are displayed as one bucket.
    let parentWinTotal = 0;
    if (hasBreakdown) {
      for (const b of breakdown) {
        parentWinTotal += Number(b.win_total || 0);
      }
    }
    const toggleIcon = hasBreakdown
      ? `<span class="payid-toggle" data-toggle-pid="${_escHtml(pid)}" role="button" title="展开 / 收起子组合">▸</span> `
      : `<span class="payid-toggle-spacer"></span>`;
    const mainRowCls = hasBreakdown ? "payid-main payid-main-expandable" : "payid-main";
    const mainRow =
      `<tr class="${mainRowCls}" data-pid="${_escHtml(pid)}">` +
      `<td>${toggleIcon}${_escHtml(pid)}</td>` +
      `<td>${categoryBadge(cat)}</td>` +
      `<td${firesAttr}>${fInt(pr.hit_count)}</td>` +
      `<td class="payid-mult">${mainMult}</td>` +
      `<td class="payid-winshare">—</td>` +
      `<td class="bar-cell" style="--bar:${bar.toFixed(1)}%">${rtpPp.toFixed(2)}pp</td>` +
      `<td>${symDisplay}</td>` +
      `<td>${_escHtml(colStr)}</td>` +
      `<td>${lineBadge}</td>` +
      `<td class="shape-notes">${notes}</td>` +
      `</tr>`;
    let subRows = "";
    if (hasBreakdown) {
      subRows = breakdown.map((b) => {
        const subMult = fmtMult(b.avg_win);
        const isAggregate = Boolean(b.is_aggregate_tail);
        const clsExtra = isAggregate ? " payid-subrow-aggregate" : "";
        const subWin = Number(b.win_total || 0);
        const winShareText = parentWinTotal > 0
          ? `${((subWin / parentWinTotal) * 100).toFixed(1)}%`
          : "—";
        return (
          `<tr class="payid-subrow payid-subrow-collapsed${clsExtra}" data-parent-pid="${_escHtml(pid)}">` +
          `<td><span class="payid-subrow-indent">↳</span> <span class="payid-subrow-label">${_escHtml(b.label || "")}</span></td>` +
          `<td>${categoryBadge(cat)}</td>` +
          `<td>${fInt(b.fires)}</td>` +
          `<td class="payid-mult">${subMult}</td>` +
          `<td class="payid-winshare">${winShareText}</td>` +
          `<td class="payid-subrow-muted">—</td>` +
          `<td class="payid-subrow-muted">—</td>` +
          `<td class="payid-subrow-muted">—</td>` +
          `<td class="payid-subrow-muted">—</td>` +
          `<td class="payid-subrow-muted">—</td>` +
          `</tr>`
        );
      }).join("");
    }
    return mainRow + subRows;
  }).join("");

  const controlsHtml =
    `<div class="payid-overview-controls">` +
    `<button type="button" class="payid-ctrl-btn" data-payid-action="expand-all">▾ ${_escHtml(fmt("payIdExpandAll"))}</button>` +
    `<button type="button" class="payid-ctrl-btn" data-payid-action="collapse-all">▸ ${_escHtml(fmt("payIdCollapseAll"))}</button>` +
    `</div>`;

  body.innerHTML =
    headerHtml + reviewBanner + flagsBanner + noShapeBanner +
    controlsHtml +
    `<table class="drilldown-table payid-overview-table">` +
    `<thead><tr>` +
    `<th>${_escHtml(fmt("payIdCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdCatCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdPaidHitsCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdMultCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdWinShareCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdRtpCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdShapeCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdColsCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdLineCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdNotesCol"))}</th>` +
    `</tr></thead>` +
    `<tbody>${rows}</tbody>` +
    `</table>` +
    evidenceHtml;

  // Wire up per-row and global expand/collapse toggles. Delegates to
  // the body container so re-rendering the table doesn't require
  // re-binding.
  _wirePayIdOverviewToggles(body);
}

// Wire expand/collapse interactions on the Pay ID 总览 table. Idempotent —
// safe to call after every renderPayIdOverview rebuild.
function _wirePayIdOverviewToggles(body) {
  if (!body || body._payidTogglesWired) return;
  body._payidTogglesWired = true;
  body.addEventListener("click", (evt) => {
    const tgt = evt.target;
    if (!tgt || !tgt.closest) return;
    // Per-row toggle: click on the ▸/▾ icon OR anywhere on the main
    // expandable row (excluding links/buttons, none present today).
    const toggle = tgt.closest(".payid-toggle");
    const mainRow = tgt.closest("tr.payid-main-expandable");
    if (toggle || mainRow) {
      const pid = (toggle && toggle.getAttribute("data-toggle-pid"))
        || (mainRow && mainRow.getAttribute("data-pid"));
      if (pid) _togglePayIdSubrows(body, pid);
      return;
    }
    // Global controls.
    const ctrl = tgt.closest(".payid-ctrl-btn[data-payid-action]");
    if (ctrl) {
      const action = ctrl.getAttribute("data-payid-action");
      if (action === "expand-all") _setAllPayIdSubrows(body, true);
      else if (action === "collapse-all") _setAllPayIdSubrows(body, false);
    }
  });
}

function _togglePayIdSubrows(body, pid) {
  const subs = body.querySelectorAll(
    `tr.payid-subrow[data-parent-pid="${CSS.escape(pid)}"]`,
  );
  if (!subs.length) return;
  // Determine target state by inspecting the first sub-row.
  const wasCollapsed = subs[0].classList.contains("payid-subrow-collapsed");
  subs.forEach((sr) => {
    sr.classList.toggle("payid-subrow-collapsed", !wasCollapsed);
  });
  const toggle = body.querySelector(
    `.payid-toggle[data-toggle-pid="${CSS.escape(pid)}"]`,
  );
  if (toggle) toggle.textContent = wasCollapsed ? "▾" : "▸";
}

function _setAllPayIdSubrows(body, expand) {
  body.querySelectorAll("tr.payid-subrow").forEach((sr) => {
    sr.classList.toggle("payid-subrow-collapsed", !expand);
  });
  body.querySelectorAll(".payid-toggle[data-toggle-pid]").forEach((t) => {
    t.textContent = expand ? "▾" : "▸";
  });
}

// Render a friendly badge for a line_id or line_id_sign token. Slot
// conventions: positive integers = line-pays, -1 = board-wide scatter,
// -2 = alternative scatter mechanic (per 策划). Anything else we
// render raw so unexpected values stay visible.
function _lineIdSignBadge(signOrId, numericId) {
  const raw = String(signOrId || "");
  if (raw === "positive") {
    return `<span class="line-badge line-positive">${_escHtml(fmt("lineSignPositive"))}</span>`;
  }
  if (raw === "mixed") {
    return `<span class="line-badge line-mixed">${_escHtml(fmt("lineSignMixed"))}</span>`;
  }
  if (raw === "negative" || (typeof numericId === "number" && numericId < 0)) {
    const id = Number.isFinite(numericId) ? numericId : null;
    if (id === -1) return `<span class="line-badge line-scatter">${_escHtml(fmt("lineIdBoardScatter"))}</span>`;
    if (id === -2) return `<span class="line-badge line-scatter-alt">${_escHtml(fmt("lineIdAltScatter"))}</span>`;
    return `<span class="line-badge line-scatter">${_escHtml(fmt("lineSignNegative"))}</span>`;
  }
  return `<span class="line-badge">${_escHtml(raw || "—")}</span>`;
}

// NOTE: ``renderPaytableShape`` (dedicated shape-inference panel) and
// ``renderPayoutGroupDrilldown`` (Pay ID depth drilldown) were merged
// into the single ``renderPayIdOverview`` panel on 2026-04-20 round 2.
// Both independent panels are removed from the HTML; 策划 now reads
// one unified row per pay_id that carries frequency / RTP / shape /
// wild substitution / line-id semantics in one place.

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

// Render the bankruptcy analysis panel. Sourced from
// ``summary.player_impact.bankruptcy_simulation.tiers`` (rawdata-replay
// histograms). Each tier gets a full-width block showing the
// bankruptcy rate / avg survival / total sessions headline + a
// drilldown-style bin histogram. Bin percentages sum to 100% per tier
// (bankrupt bins + `survived` row). Hidden when the sim produced no
// sessions (degenerate case — e.g. an all-empty rawdata).
function renderBankruptcyAnalysis(summary) {
  const panel = byId("bankruptcyPanel");
  if (!panel) return;
  const body = byId("bankruptcyBody");
  const sim = ((summary || {}).player_impact || {}).bankruptcy_simulation;
  const tiers = sim && Array.isArray(sim.tiers) ? sim.tiers : [];
  const anyData = tiers.some(
    (t) => Number(t?.robots || 0) > 0,
  );
  if (!anyData) {
    panel.classList.add("hidden");
    body.innerHTML = "";
    return;
  }
  panel.classList.remove("hidden");

  const sessionSpins = Number(sim.session_spins || 10000);
  // Decile percentiles (P10, P20, ..., P90) come pre-computed from the
  // analyzer with denominator = ALL simulated sessions in the tier.
  const percentileKeys = Array.isArray(sim.percentile_keys) && sim.percentile_keys.length
    ? sim.percentile_keys.map((v) => Number(v))
    : [10, 20, 30, 40, 50, 60, 70, 80, 90];

  const intro = `<p class="bankruptcy-intro">${_escHtml(
    fmt("bankruptcyIntro", { session: sessionSpins })
  )}</p>`;

  const cards = tiers.map((t) => {
    const mult = Number(t.bankroll_multiplier || 0);
    const sessions = Number(t.robots || 0);
    const survived = Number(t.completed_robots || 0);
    const rate = Number(t.bankruptcy_rate || 0);
    const medianSpins = Number(t.median_spins_completed || 0);
    const fastestRaw = t.fastest_bankruptcy_spins;
    const fastest = fastestRaw == null ? null : Number(fastestRaw);
    const pctMap = (t.percentiles && typeof t.percentiles === "object")
      ? t.percentiles
      : {};

    // Bar scale: use the tier's own max percentile value so the
    // in-tier progression reads clearly (x500 stretches to 10k; x100
    // tops out a few hundred). Including `fastest` in the max is safe
    // since fastest ≤ P10 always.
    const pctValues = percentileKeys.map((k) =>
      Number(pctMap[String(k)] != null ? pctMap[String(k)] : pctMap[k] || 0),
    );
    const maxSpin = Math.max(sessionSpins, ...pctValues, 0.001);

    // Fastest row: highlighted separately at the top. Rendered even
    // when null (shows "—") so the row layout stays aligned across
    // tiers.
    const fastestRow = (() => {
      const bar = fastest == null ? 0 : Math.min(100, (fastest / maxSpin) * 100);
      const spinText = fastest == null ? "—" : Math.round(fastest).toLocaleString();
      return (
        `<tr class="bk-row-fastest">` +
        `<td>${_escHtml(fmt("bankruptcyFastestLabel"))}</td>` +
        `<td>${spinText}</td>` +
        `<td class="bar-cell" style="--bar:${bar.toFixed(1)}%"></td>` +
        `</tr>`
      );
    })();

    // Decile rows: each shows "at this percentile of ALL users, how
    // many spins did they get?". Once cumulative mass passes bankrupt
    // share, percentile pins to session_spins — the transition row
    // visually coincides with the survival rate.
    const pctRows = percentileKeys.map((p) => {
      const spin = Number(pctMap[String(p)] != null ? pctMap[String(p)] : pctMap[p] || 0);
      const bar = Math.min(100, (spin / maxSpin) * 100);
      const isSurvived = spin >= sessionSpins;
      const cls = isSurvived ? "bk-row-survived" : "bk-row-bankrupt";
      return (
        `<tr class="${cls}">` +
        `<td>P${p}</td>` +
        `<td>${spin.toLocaleString()}</td>` +
        `<td class="bar-cell" style="--bar:${bar.toFixed(1)}%"></td>` +
        `</tr>`
      );
    }).join("");

    return (
      `<div class="bankruptcy-tier">` +
      `<h3 class="bankruptcy-tier-head">${_escHtml(
        fmt("bankruptcyTierLabel", { mult })
      )}</h3>` +
      `<div class="bankruptcy-tier-stats">` +
      `<span class="bk-stat bk-stat-rate"><em>${_escHtml(fmt("bankruptcyRateLabel"))}</em><b>${(rate * 100).toFixed(1)}%</b></span>` +
      `<span class="bk-stat"><em>${_escHtml(fmt("bankruptcyMedianLabel"))}</em><b>${medianSpins.toLocaleString()}</b></span>` +
      `<span class="bk-stat"><em>${_escHtml(fmt("bankruptcySurvivedLabel"))}</em><b>${sessions > 0 ? ((survived / sessions) * 100).toFixed(1) : "0.0"}%</b></span>` +
      `</div>` +
      `<table class="drilldown-table bankruptcy-histogram">` +
      `<thead><tr>` +
      `<th>${_escHtml(fmt("bankruptcyPercentileCol"))}</th>` +
      `<th>${_escHtml(fmt("bankruptcySpinCountCol"))}</th>` +
      `<th></th>` +
      `</tr></thead>` +
      `<tbody>${fastestRow}${pctRows}</tbody>` +
      `</table>` +
      `</div>`
    );
  }).join("");

  body.innerHTML = intro + `<div class="bankruptcy-tiers-grid">${cards}</div>`;
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

// Populate the Volatility + Archetype KPI cards with a library-
// relative rank. Volatility card shows the rank as its PRIMARY value
// (no separate "Very High" label anymore — the lib percentile is the
// whole signal). Archetype keeps the plain-Chinese label as primary
// with the share count as secondary.
//
// `dist` is expected to be filtered to the summary's own mode (backend
// honors ?mode=N; see refreshCurrentRun for the wired call). Same-mode
// ranking is a hard requirement — comparing a mode 1 baseline machine
// against mode 5 bonus-mode reports mixes incomparable ranges.
//
// Silently no-ops when the library has fewer than 2 entries (ranking
// against oneself isn't informative).
function applyLibraryRanking(summary, dist) {
  const volEl = byId("kpiVolatilitySub");
  if (volEl) volEl.textContent = fmt("libRankNoData");
  const archSubEl = byId("kpiArchetypeSub");
  if (archSubEl) archSubEl.textContent = "";

  if (!dist || !dist.metrics) return;
  const total = Number(dist.machines_count || 0);
  if (total < 2) {
    if (volEl) volEl.textContent = fmt("libRankTooFew");
    return;
  }
  const ga = (summary || {}).guideline_assessment || {};
  const derived = ga.derived_metrics || {};
  const cls = ga.classification || {};
  const hit = ((summary || {}).player_impact || {}).hit_and_payout || {};
  const streaks = ((summary || {}).player_impact || {}).streaks || {};

  // Volatility: rank composite against the (same-mode) library.
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
    const text = PURE.formatLibRank(rank, state.lang);
    if (volEl) volEl.textContent = text || fmt("libRankNoData");
  }

  // Archetype: categorical — "{count}/{total} same archetype".
  const currentArchetype = cls.experience_archetype;
  if (currentArchetype && dist.archetype_counts) {
    const count = Number(dist.archetype_counts[currentArchetype] || 0);
    if (archSubEl) archSubEl.textContent = fmt("archetypeShare", { count, total });
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
// Fix 5: unified Report 管理 banner — always visible (not just when
// stale). Merges the old staleness banner + maintenance-actions panel
// into one row at the top so report lifecycle ops (regen stale /
// cleanup old versions / import) share a consistent home.
async function refreshStaleBanner() { return refreshReportMgmtBanner(); }

async function refreshReportMgmtBanner() {
  const banner = byId("reportMgmtBanner");
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
  const analyzerShort = (body.current_analyzer_version || "").slice(0, 10) || "—";

  banner.classList.remove("hidden");
  let staleText;
  if (staleAnalyzer === 0 && staleRawdata === 0) {
    staleText = `<span class="report-mgmt-ok">✓ 全 fleet analyzer 均最新</span>`;
  } else {
    const parts = [];
    if (staleAnalyzer > 0) parts.push(`⚠ ${staleAnalyzer} 个 analyzer 过期`);
    if (staleRawdata > 0) parts.push(`⚠ ${staleRawdata} 个 rawdata 过期`);
    staleText = `<span class="report-mgmt-warn">${parts.join(" · ")}</span>`;
  }

  const regenBtn = fixable > 0
    ? `<button id="regenerateStaleBtn" class="small-btn primary-btn" title="只重生 analyzer 过期 + rawdata 未过期的 report (轻量修复)">⟳ 重生 ${fixable}</button>`
    : "";

  banner.innerHTML = `
    <div class="report-mgmt-row">
      <span class="report-mgmt-main">💼 Report 管理 · analyzer <code>${analyzerShort}</code> · ${staleText}</span>
      <span class="report-mgmt-actions">
        ${regenBtn}
        <button id="rebuildAllReportsBtn" class="small-btn" title="扫所有含 rawdata 的 (机台, mode)，用当前 analyzer 全部重跑 generate-report (大批量，耗时长)">⟳ 全 fleet 重建</button>
        <button id="reportCleanupBtn" class="small-btn danger-btn" title="清理 analyzer 过期的 report 版本 (按 machine+mode 只保留最新 match)">🗑 清理过期</button>
        <button id="importReportsBtn" class="small-btn" title="从 dev_reports/ 导入离线生成的 report">📥 导入</button>
        <span id="reportCleanupResult" class="muted"></span>
      </span>
    </div>`;

  async function _kickBatchGenerate(payload, msgOnErr) {
    const panel = byId("batchGenerateProgressPanel");
    const meta = byId("batchGenerateProgressMeta");
    const log = byId("batchGenerateProgressLog");
    if (panel) panel.classList.remove("hidden");
    if (log) log.innerHTML = "";
    try {
      const resp = await fetch("/api/rawdata/batch-generate-report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
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
      if (meta) meta.textContent = (msgOnErr || "重建失败") + ": " + String(err.message || err);
    }
  }

  byId("regenerateStaleBtn")?.addEventListener("click", async () => {
    const items = body.fixable_items || [];
    if (!items.length) return;
    await _kickBatchGenerate({ items }, "重生失败");
  });

  byId("rebuildAllReportsBtn")?.addEventListener("click", async () => {
    if (state.systemState?.operation_busy) {
      alert("有操作进行中，请等待完成再点。");
      return;
    }
    if (!confirm("全 fleet 重建 report：将遍历所有含 rawdata 的 (机台, mode)，用当前 analyzer 全部重跑。耗时较长（每台约 20-60s × mode 数）。确认？")) return;
    await _kickBatchGenerate({ scope: "all_with_rawdata" }, "全 fleet 重建失败");
  });

  byId("importReportsBtn")?.addEventListener("click", async () => {
    const source = prompt("输入 Reports 源目录绝对路径（如 D:\\\\dev_reports 或 /path/to/dev_reports）:");
    if (!source) return;
    const mode = confirm("合并模式？\n[确定] 合并（跳过已存在）\n[取消] 替换（删除目标后导入）") ? "merge" : "replace";
    try {
      const r = await apiPost("/api/reports/import", { source_path: source, mode });
      alert(`导入完成：新增 ${r.imported} 个版本，跳过 ${r.skipped} 个。\n影响机台：${r.machines_affected.join(", ") || "无"}`);
      const [m, mSummary] = await Promise.all([apiGet("/api/machines"), apiGet("/api/machines/summary").catch(() => null)]);
      state.machines = m.machines || [];
      state.machinesSummary = mSummary;
      renderCatalogFeatureChips();
      renderMachineCatalog();
      renderRtpModeBar();  // imported reports may add new modes to fleet
      renderFleetOverview();
      refreshReportMgmtBanner();  // refresh stale counts after import
      refreshStaticAttrs();  // Round 6: imports touched static attrs
    } catch (e) {
      alert("导入失败：" + (e.message || e));
    }
  });

  byId("reportCleanupBtn")?.addEventListener("click", async () => {
    if (!confirm(fmt("reportCleanupConfirm"))) return;
    const btn = byId("reportCleanupBtn");
    const result = byId("reportCleanupResult");
    btn.disabled = true;
    if (result) result.textContent = "...";
    try {
      const data = await apiPost("/api/reports/cleanup");
      if (result) result.textContent = fmt("reportCleanupDone", { deleted: data.deleted, kept: data.kept });
      const [m, mSummary] = await Promise.all([apiGet("/api/machines"), apiGet("/api/machines/summary").catch(() => null)]);
      state.machines = m.machines || [];
      state.machinesSummary = mSummary;
      renderCatalogFilters();
      renderMachineCatalog();
      renderRtpModeBar();  // cleanup may have removed all reports for a mode
      renderFleetOverview();
      refreshReportMgmtBanner();
      refreshStaticAttrs();
    } catch (e) {
      if (result) result.textContent = String(e.message || e);
    } finally {
      btn.disabled = false;
    }
  });
}

// Poll the active batch-generate-report every 1s until it reaches a
// terminal state, updating inline progress + refreshing runs/reports
// once done so the new gen_* rows + report versions land in the UI
// without a manual refresh.
// Cancel handler — bound once per boot (button lives in static HTML).
// Listener re-registration is idempotent because the element is
// fixed. POSTs the cancel endpoint; backend flips batch status to
// cancelled after current item finishes.
function _initBatchGenerateCancelBtn() {
  const btn = byId("batchGenerateCancelBtn");
  if (!btn || btn.dataset.wired === "1") return;
  btn.dataset.wired = "1";
  btn.addEventListener("click", async () => {
    const bid = state.batchGenerateId;
    if (!bid) return;
    if (!confirm("请求停止批量生成？当前正在处理的那一项会先完成，剩余 pending 项会跳过。")) return;
    btn.disabled = true;
    btn.textContent = "停止中…";
    try {
      await fetch(`/api/rawdata/batch-generate-report/${encodeURIComponent(bid)}/cancel`, {
        method: "POST",
      });
    } catch (_) { /* non-fatal */ }
  });
}

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
      // Expose the stop button while the batch is running.
      const cancelBtn = byId("batchGenerateCancelBtn");
      if (cancelBtn) cancelBtn.classList.toggle("hidden", body.status !== "running" && body.status !== "pending");

      if (body.status === "completed" || body.status === "partial" || body.status === "failed" || body.status === "cancelled") {
        clearInterval(state.batchGeneratePollTimer);
        state.batchGeneratePollTimer = null;
        state.batchGenerateId = null;
        await refreshRunList(false);
        refreshStaleBanner();
        refreshStaticAttrs();  // Round 6: regen populated attrs cache
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
    // Drive the KPI cards from a single pure helper so tone classification
    // stays in one place (testable without DOM).
    const cards = PURE.extractMetricCards(s, state.lang);
    const kpiBindings = [
      ["kpiRtp", "rtp"], ["kpiCi", "ci"], ["kpiSpins", "spins"],
      ["kpiZero", "zeroWin"],
      // Volatility main slot intentionally empty (lib-rank is the only
      // signal; applyLibraryRanking fills #kpiVolatilitySub).
      ["kpiArchetype", "archetype", "kpiArchetypeSub"],
      ["kpiLossStreak", "lossStreak"], ["kpiMaxReturn", "maxReturn"],
    ];
    for (const binding of kpiBindings) {
      const [domId, key, subId] = binding;
      const c = cards[key] || { value: "N/A", tone: "neutral" };
      setKpi(domId, c.value, c.tone);
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
    // Big-win rate 4-tile grid (paid-round "≥Nx of bet" rates).
    // Structurally identical to tail-dep so the two cards read as a
    // set — monotonically decreasing across the 4 thresholds. Each
    // rate is sessions-with-a-≥Nx-round / total paid rounds.
    const bigWinGrid = byId("kpiBigWinGrid");
    if (bigWinGrid) {
      const tiles = (cards.bigWin && cards.bigWin.tiles) || {};
      const pct1 = (v) => v == null ? "\u2014" : (Number(v) * 100).toFixed(2) + "%";
      bigWinGrid.innerHTML =
        `<div class="tail-cell"><em>\u226510x</em><b>${pct1(tiles.ge10)}</b></div>` +
        `<div class="tail-cell"><em>\u226520x</em><b>${pct1(tiles.ge20)}</b></div>` +
        `<div class="tail-cell"><em>\u226550x</em><b>${pct1(tiles.ge50)}</b></div>` +
        `<div class="tail-cell"><em>\u2265100x</em><b>${pct1(tiles.ge100)}</b></div>`;
    }
    // Across-library ranking, filtered to the same mode so a mode 1
    // baseline machine isn't ranked against mode 5 bonus-mode reports
    // (their ranges are inherently different). Falls back to cross-mode
    // ranking if the backend doesn't support ?mode yet.
    try {
      const m = Number(s.mode || 0);
      const distUrl = m > 0
        ? `/api/library/distributions?mode=${m}`
        : "/api/library/distributions";
      const dist = await apiGet(distUrl);
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
    renderPayIdOverview(s);
    renderFieldDiscovery(s);
    renderMachineMechanics(s);
    renderBonusChainDynamicsPanel(s);
    renderCollectCyclePanel(s);
    renderPaylineDrilldown(s);
    renderSymbolDrilldown(s);
    renderBankruptcyAnalysis(s);
    await refreshInterpretation();
  }
  warnings.push(...collectSystemWarnings());
  setGlobalWarning([...new Set(warnings)]);
  updateActionStates();
}

async function refreshCache() {
  // Cache panel DOM was retired 2026-04-19 (rawdata banner + global
  // detail table own these signals now). Keep the function + state
  // as a thin fetch so callers that still need state.cacheStatus
  // (updateActionStates) get fresh data without the DOM writes.
  try {
    state.cacheStatus = await apiGet("/api/cache/status");
  } catch (_) { /* non-fatal — banner refreshes independently */ }
  updateActionStates();
}

async function runAutoTune() {
  if (state.autoTuneRunning) return;
  // Pick the first effective-selected machine for tuning. Different
  // machines have different optimal (robot_count, concurrency); we
  // apply the tuned values to the WHOLE batch as a pragmatic
  // simplification — tuning per-machine is N × autotune wall time.
  const selected = _effectiveSelectedMachines();
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
  const [h, m, models, versions] = await Promise.all([
    apiGet("/api/health"),
    apiGet("/api/machines"),
    apiGet("/api/models"),
    // Current analyzer + per-machine md5 fingerprints drive the
    // Run History staleness badges; fetched once per bootstrap and
    // cached in state — these change only when code is reloaded or
    // machines.json is refreshed, both of which already reload.
    apiGet("/api/versions/current").catch(() => null),
  ]);
  // /api/machines/summary scans every summary.json across the fleet to
  // pick best-CI per (machine, mode) — on a fleet with many report
  // versions this takes 10-15s on a cold cache. Don't block the
  // initial render on it; the catalog renders fine with summary=null
  // (all per-card lookups fall back to empty via `|| {}`). When the
  // summary arrives we re-render.
  const summaryPromise = apiGet("/api/machines/summary").catch(() => null);
  setHealth(Boolean(h.ok), h.ts || "");
  state.machines = m.machines || [];
  state.modelMeta = models || {};
  state.machinesSummary = null;
  state.currentVersions = versions || { analyzer_version: "", machines: {} };
  summaryPromise.then((mSummary) => {
    if (!mSummary) return;
    state.machinesSummary = mSummary;
    try { renderCatalogFeatureChips(); } catch (_) {}
    try { renderMachineCatalog(); } catch (_) {}
    try { renderFleetOverview(); } catch (_) {}
    // RTP 模式按钮条的 mode 集合来自 machinesSummary.machines[*] 的 keys。
    // 初次渲染发生在页面加载早期（summary 还没到），此时 modeSet 为空，
    // 只出 auto 按钮。summary 到货后必须重渲，否则 "按 RTP" tab 只有 auto。
    try { renderRtpModeBar(); } catch (_) {}
  });
  // Round 6: load static machine attrs (category / features / mechanics
  // / md5) in parallel with summary. Static cache is the primary source
  // for catalog filter chips + mechanic view — survives report deletes.
  apiGet("/api/machines/static").then((attrs) => {
    state.staticAttrs = attrs || null;
    try { renderCatalogFeatureChips(); } catch (_) {}
    try { renderCatalogFilters(); } catch (_) {}
    try { renderMachineCatalog(); } catch (_) {}
  }).catch(() => { /* falls back to machinesSummary */ });
  fillMachineModeSelectors();
  fillCiTierOptions();
  fillBankMultOptions();
  fillProviders();
  fillModelsForProvider(byId("providerSelect").value, state.modelMeta.default_model || "");
  renderCatalogFeatureChips();
  renderMachineCatalog();
  renderFleetOverview();
  renderDetailPane();  // initialize right-pane container visibility
  refreshStaleBanner();  // don't await — non-blocking for bootstrap
  refreshRawdataOverview();  // populate the rawdata banner in topbar (async)
  _initBatchGenerateCancelBtn();  // wire the stop button one-shot
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

// Inline RTP mode bar: only when 按 RTP tab active. Shows a row of
// "auto | 1 | 2 | 5 | ..." buttons (union of modes present across
// the fleet in machinesSummary). Clicking a mode re-sorts the flat
// catalog by that mode's rtp_pct. "auto" = the legacy fallback
// (prefer mode 2, else smallest numeric mode) kept for bookmarks.
//
// Top-level (not nested inside bindEvents) so loadBootstrap /
// pollSampling / any non-event-handler call path can reach it.
// The 2026-04-21 regression (f398d57 silent-noop + pollSampling
// handler breakage) was caused by nesting this inside bindEvents;
// ReferenceError from outside the closure was swallowed by the
// outer try/catch, looking like "fix didn't apply".
function renderRtpModeBar() {
  const bar = byId("rtpModeBar");
  if (!bar) return;
  if (state.catalogViewMode !== "rtp") {
    bar.classList.add("hidden");
    return;
  }
  bar.classList.remove("hidden");
  // Enumerate unique mode keys present anywhere in machinesSummary.
  // Sort numerically so 1 < 2 < 5 < 7, keeping the UI deterministic
  // across page reloads.
  const sm = ((state.machinesSummary || {}).machines || {});
  const modeSet = new Set();
  Object.values(sm).forEach((machineModes) => {
    Object.keys(machineModes || {}).forEach((k) => modeSet.add(String(k)));
  });
  const modes = [...modeSet].sort((a, b) => Number(a) - Number(b));
  const active = String(state.catalogRtpMode || "auto");
  const autoBtn = `<button class="small-btn ${active === "auto" ? "active" : ""}" data-mode="auto" title="优先 mode 2，否则最小 mode">auto</button>`;
  const modeBtns = modes.map((m) => (
    `<button class="small-btn ${active === m ? "active" : ""}" data-mode="${m}">mode ${m}</button>`
  )).join("");
  bar.innerHTML = `
    <div class="rtp-mode-row">
      <span class="muted">RTP 排序 mode：</span>
      <div class="rtp-mode-toggle">${autoBtn}${modeBtns}</div>
      <span class="muted">· 没有该 mode 数据的机台沉底</span>
    </div>
  `;
  bar.querySelectorAll(".rtp-mode-toggle button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const m = btn.dataset.mode;
      if (!m || m === state.catalogRtpMode) return;
      state.catalogRtpMode = m;
      renderRtpModeBar();
      renderMachineCatalog();
    });
  });
}

// Inline hall bar: only when 按大厅 tab active. Shows the ordering
// mode toggle (默认 / 当前大厅) + active-activity summary + a
// refresh button that re-pulls from upstream MapMachineOrder.
// Top-level alongside renderRtpModeBar for the same reason.
function renderHallsRefreshBar() {
  const bar = byId("hallsRefreshBar");
  if (!bar) return;
  if (state.catalogViewMode !== "hall") {
    bar.classList.add("hidden");
    return;
  }
  bar.classList.remove("hidden");
  const data = state.machineHalls || {};
  const defaultOrder = data.default_order || [];
  const currentOrder = data.current_hall_order || [];
  const activeActs = data.active_activities || [];
  const updated = data.updated_at;
  if (!defaultOrder.length) {
    bar.innerHTML = `<span class="muted">未拉取地图顺序。</span>
      <button id="hallsRefreshBtn" class="small-btn primary-btn">拉取地图顺序</button>`;
  } else {
    const defaultActive = state.hallOrderMode !== "current";
    const hasCurrent = activeActs.length > 0 && currentOrder.length > 0;
    // Build the activity summary: "活动 Id=10 置顶 10 台 · Id=13 置顶 M272"
    const actSummary = activeActs.map((a) => {
      const ims = a.influence_machines || [];
      const count = ims.length;
      const sample = ims.slice(0, 3).join(", ");
      const more = count > 3 ? ` +${count - 3}` : "";
      const orders = (a.orders || [])[0];
      const target = orders != null ? `→ 位置 ${orders}` : "";
      return `Id=${a.id} ${target} ${count}台(${sample}${more})`;
    }).join(" · ");
    bar.innerHTML = `
      <div class="halls-row">
        <div class="halls-mode-toggle">
          <button class="small-btn ${defaultActive ? "active" : ""}" data-mode="default">默认顺序</button>
          <button class="small-btn ${defaultActive ? "" : "active"}" data-mode="current" ${hasCurrent ? "" : "disabled"} title="${hasCurrent ? "应用当前运营活动的位置覆盖" : "无活动中的运营活动"}">当前大厅顺序</button>
        </div>
        <span class="muted">${defaultOrder.length} 台 · ${activeActs.length ? `${activeActs.length} 个活动: ${actSummary}` : "无活动中的运营活动"}${updated ? ` · ${updated.slice(0, 19).replace("T", " ")}` : ""}</span>
        <button id="hallsRefreshBtn" class="small-btn">刷新上游</button>
      </div>
    `;
    bar.querySelectorAll(".halls-mode-toggle button").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        if (e.target.disabled) return;
        const mode = btn.dataset.mode;
        if (mode && mode !== state.hallOrderMode) {
          state.hallOrderMode = mode;
          renderHallsRefreshBar();
          renderMachineCatalog();
        }
      });
    });
  }
  byId("hallsRefreshBtn")?.addEventListener("click", async () => {
    const btn = byId("hallsRefreshBtn");
    if (!btn) return;
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = "刷新中…";
    try {
      const resp = await fetch("/api/machines/halls/refresh", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${resp.status}`);
      }
      state.machineHalls = await apiGet("/api/machines/halls");
      renderHallsRefreshBar();
      renderMachineCatalog();
    } catch (err) {
      btn.textContent = `失败: ${String(err.message || err).slice(0, 60)}`;
      setTimeout(() => { btn.disabled = false; btn.textContent = orig; }, 4000);
    }
  });
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
    // Clear BOTH focus and multi-select (master/detail refactor 2026-04-19).
    state.runFilterMachines.clear();
    state.focusedMachine = null;
    renderMachineCatalog();
    renderRunHistory();
    updateSampleHint();
    updateActionStates();
    renderDetailPane();
  });
  // Select-all: add every machine currently visible in the catalog
  // (honors current view-mode + feature-chip filter + search) to the
  // multi-select set. Intentionally scoped to the filtered view so
  // users don't accidentally select 253 machines when they meant the
  // 10 visible after a filter. Always enters multi-select mode, clears
  // any focused machine.
  byId("catalogSelectAllVisible")?.addEventListener("click", () => {
    state.focusedMachine = null;
    const visible = document.querySelectorAll("#machineCatalog .catalog-item");
    visible.forEach((el) => {
      const m = el.dataset.machine;
      if (m) state.runFilterMachines.add(m);
    });
    renderMachineCatalog();
    renderRunHistory();
    updateSampleHint();
    updateActionStates();
    renderDetailPane();
  });
  // View tabs for catalog grouping mode.
  byId("catalogViewTabs").addEventListener("click", async (e) => {
    const btn = e.target.closest(".view-tab");
    if (!btn) return;
    state.catalogViewMode = btn.dataset.view;
    byId("catalogViewTabs").querySelectorAll(".view-tab").forEach((b) => b.classList.toggle("active", b === btn));
    renderCatalogFeatureChips();
    // First click on "按大厅" lazily fetches the upstream ordering
    // cache (default_order + current_hall_order + active_activities).
    if (btn.dataset.view === "hall" && state.machineHalls === null) {
      try {
        state.machineHalls = await apiGet("/api/machines/halls");
      } catch (_err) {
        state.machineHalls = {
          default_order: [], current_hall_order: [],
          active_activities: [], halls: {},
          updated_at: null, source: null,
        };
      }
    }
    renderHallsRefreshBar();
    renderRtpModeBar();
    renderMachineCatalog();
  });

  // Inline sampling panel controls.
  byId("sampleStartBtn").addEventListener("click", () => startSampling());
  byId("sampleCancelBtn").addEventListener("click", () => cancelSampling());
  byId("sampleMode").addEventListener("change", () => { updateSampleHint(); _saveSamplingPrefs(); });
  byId("sampleCi").addEventListener("change", () => { updateSampleHint(); _saveSamplingPrefs(); });
  byId("sampleSpinCount")?.addEventListener("input", () => updateSampleHint());
  byId("sampleStrategy")?.addEventListener("change", () => updateSampleHint());
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
      renderRtpModeBar();  // md5 refresh may flip modes to/from match state
      renderFleetOverview();
    } catch (e) {
      alert("刷新失败：" + (e.message || e));
    } finally {
      btn.disabled = false;
      btn.textContent = "刷新机台 MD5";
    }
  });
  // importReportsBtn + reportCleanupBtn handlers moved into
  // refreshReportMgmtBanner() below — the buttons are rendered
  // dynamically inside the Report 管理 banner, so listeners attach
  // each time the banner repaints.
  byId("compareServersBtn").addEventListener("click", () => compareServers());
  // compareBtn removed from the HTML in step 8; rwtree's built-in
  // compare bar (#rwtreeCompareBar) now owns the click → compareReports
  // wiring directly inside _updateRwtreeCompareBar.
  byId("compareBtn")?.addEventListener("click", () => compareReports());
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
  // Cache refresh/cleanup buttons removed 2026-04-19 — the rawdata
  // banner's 一键清理 owns cleanup; refresh is no longer needed (the
  // banner reads /api/rawdata/overview which is mtime-invalidated).

  // System settings: load current value on page init; the save path
  // moved into renderRawdataBanner's inline settings row (2026-04-19).
  (async () => {
    try {
      const current = await apiGet("/api/settings");
      if (current && typeof current.min_retention_spins === "number") {
        state.minRetentionSpins = current.min_retention_spins;
        // Re-render banner if already populated so the settings input
        // reflects the real server-side value on first paint.
        if (state.rawdataOverview) renderRawdataBanner();
      }
    } catch (_err) { /* non-fatal — banner falls back to 100000 default */ }
  })();

  // Batch Generate Report: kick off a sequential rebuild for every
  // effective-selected machine at the current sampleMode. Progress
  // polls the batch endpoint every 1s while in flight.
  byId("batchGenerateBtn")?.addEventListener("click", async () => {
    const selected = _effectiveSelectedMachines();
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

  // Delete rawdata: destructive batch action (new step 3). For the
  // effective-selected machines at the current sampleMode, hit
  // DELETE /api/rawdata/{m}?mode=N per machine. Surfaces per-item
  // success/fail in batchGenerateProgressPanel (reused — it's the
  // natural spot for batch op logs in the left column).
  byId("batchDeleteRawdataBtn")?.addEventListener("click", async () => {
    const selected = _effectiveSelectedMachines();
    if (!selected.length) return;
    const mode = Number(byId("sampleMode")?.value || 1);
    const confirmMsg = selected.length === 1
      ? `删除 ${selected[0]} mode ${mode} 的 rawdata chunks？此操作不可撤销。`
      : `删除 ${selected.length} 台机台 mode ${mode} 的 rawdata chunks？此操作不可撤销。`;
    if (!confirm(confirmMsg)) return;

    const panel = byId("batchGenerateProgressPanel");
    const meta = byId("batchGenerateProgressMeta");
    const log = byId("batchGenerateProgressLog");
    if (panel) panel.classList.remove("hidden");
    if (meta) meta.textContent = `删除 rawdata 中... (0 / ${selected.length})`;
    if (log) log.innerHTML = "";

    let done = 0;
    let failed = 0;
    let deletedChunks = 0;
    for (const machine of selected) {
      try {
        const resp = await fetch(
          `/api/rawdata/${encodeURIComponent(machine)}?mode=${mode}`,
          { method: "DELETE" },
        );
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${resp.status}`);
        }
        const body = await resp.json();
        deletedChunks += Number(body.deleted_chunks || 0);
        done += 1;
        if (log) {
          const row = document.createElement("div");
          row.className = "sample-log-row";
          row.textContent = `✓ ${machine} mode ${mode}: 删除 ${body.deleted_chunks || 0} chunks`;
          log.appendChild(row);
        }
      } catch (err) {
        failed += 1;
        if (log) {
          const row = document.createElement("div");
          row.className = "sample-log-row danger";
          row.textContent = `✗ ${machine} mode ${mode}: ${String(err.message || err)}`;
          log.appendChild(row);
        }
      }
      if (meta) meta.textContent = `删除 rawdata 中... (${done + failed} / ${selected.length})`;
    }
    if (meta) {
      meta.textContent = `删除完成：${done} 成功 / ${failed} 失败 · 共删 ${deletedChunks} chunks`;
    }
    // Refresh caches/machines-summary so the catalog cards reflect
    // the now-empty rawdata.
    try {
      const mSummary = await apiGet("/api/machines/summary");
      state.machinesSummary = mSummary;
      renderMachineCatalog();
      renderRtpModeBar();  // rawdata delete may have dropped a mode's reports
      renderFleetOverview();
    } catch (_) {}
    try { await refreshCache(); } catch (_) {}
  });

  // Run-history batch selection handlers removed 2026-04-19 — the
  // run-history table itself is gone from the manage tab. Batch
  // operations on rawdata live on the sticky batch action bar, and
  // the global rawdata detail table provides its own per-row delete.
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
