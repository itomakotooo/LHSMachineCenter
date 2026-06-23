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
  // Unified-log filter (log redesign P2): {errorsOnly, op, query}. Applied to the
  // 活动日志流 buffer by PURE.filterLogEntries before render.
  logFilter: { errorsOnly: false, op: "", query: "" },
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
  // Per-focused-machine MachineConfig override, resolved against
  // ``machineconfig/<underlying>Cfg.txt`` on the backend. Populated
  // by the availability-probe API on focus change:
  //   null              — no probe yet / no match → card hidden
  //   { available:false, underlying, filename } — probe done, no file
  //   { available:true, underlying, filename, bytes, mtime_iso,
  //     useLocal: bool } — probe done, file exists; useLocal tracks
  //     the checkbox state (sent to backend as use_local_machine_config)
  // Cleared on focus change / clear so a checkbox ticked for M14
  // never rides along with a sample on M15.
  machineConfigState: null,
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
  // Per-machine manifest review state (from GET /api/manifests/review-state).
  // { M14: {verified: true, reviewed: true, variant: false}, ... }
  // Drives the catalog's "verified / unreviewed" visual badge. Lazily
  // populated; treat missing entries as no-badge (same UX as pre-Phase-3).
  manifestReviewState: {},
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
  // null when not in compare mode; { a, b, vA, vB } when active.
  // Set by _enterCompareMode, cleared by _onCompareExit / _resetCompareModeToEmpty.
  compareMode: null,
  // Monotonically-increasing counter. Incremented by compareReports()
  // before each fetch pair. The fetch callback checks this value
  // matches state._compareInvocationId before applying the response —
  // if a DELETE raced and called _resetCompareModeToEmpty() in between,
  // the counter will have advanced and the stale response is discarded
  // (per memory feedback_fasttimer_overlap_needs_oneshot.md, C3).
  _compareInvocationId: 0,
  // True for a short window right after a batch completes: blocks
  // renderSamplingProgress so the final error log stays readable.
  // Cleared when the user clicks 开始采样 for a fresh batch.
  batchJustCompleted: false,
  // Client-side synthetic lifecycle events (click / submit / batch_created
  // / submit_failed / polling_started). These fill the observability
  // gap between a user click and the first analyzer chunk_progress
  // event (typically 30-60s of silence). Reset on each fresh batch.
  //
  // 2026-05-22 L1: persisted to localStorage so a browser refresh
  // does not erase the operator's UI-lifecycle trail (the backend
  // events on the same panel ARE already durable — they live in the
  // BatchRunManager state for the duration of the batch, and the
  // per-chunk events live in state/progress/{run_id}.jsonl. This
  // closes the last hole.). Capped at 100 entries to match the
  // in-memory cap on pushClientEvent so the localStorage value never
  // grows unbounded.
  clientEvents: (() => {
    try {
      const raw = JSON.parse(
        localStorage.getItem("slot_console_clientEvents") || "[]"
      );
      return Array.isArray(raw) ? raw.slice(-100) : [];
    } catch {
      return [];
    }
  })(),
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
  // Phase 3 (D11): fleet refresh state.
  // Per memory/feedback_fasttimer_overlap_needs_oneshot.md: use a
  // one-shot guard so each queue completion fires side-effects once.
  fleetRefreshQueueId: null,
  fleetRefreshPollTimer: null,
  // One-shot guard: set to queue_id after auto-refresh fires for that
  // completion, cleared on next queue start. JS is single-threaded so
  // the check + set block is atomic.
  _autoRefreshedForFleetRefreshId: null,
  // Phase 3 (D11): uploaded configs list.
  uploadedConfigs: [],
  // 2026-05-26 B2: setInterval handle for the batch history panel
  // auto-refresh. Cleared on _initBatchHistoryPanel so re-init
  // (HMR / test) doesn't leak timers.
  batchHistoryTimer: null,
  // ── P4 auto-inspect tab state ──────────────────────────────────────
  // Current sweep being displayed (null = none loaded / idle).
  aiCurrentSweepId: null,
  // setInterval handle for the live-progress poll (5s cadence).
  aiPollTimer: null,
  // One-shot guard so completed/cancelled/failed transition side-effects
  // (e.g. re-fetch history) only fire once per sweep terminal event.
  // Keyed by sweep_id.
  _aiAutoActedForSweepId: null,
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
  // Freshness row: compare this run's effective_analyzer_version +
  // config/code md5 against the CURRENT snapshots (state.currentVersions,
  // populated by loadBootstrap). "✓ 当前" when match, "⚠ 过期" when drifted.
  //
  // Honesty-3: routes through PURE.versionBadges (the single pure helper)
  // instead of duplicating comparison logic here. versionBadges uses
  // per-(machine, mode) effective_analyzer_version — not the global hash —
  // so editing one machine's analysis only flags that machine's runs.
  // Do NOT hand-roll the comparison here (feedback_no_parallel_panel_impl.md).
  const badges = PURE.versionBadges(run, state.currentVersions || {});
  const tierToClass = (tier) => tier === "fresh" ? "lm-badge-fresh" : tier === "stale" ? "lm-badge-stale" : "lm-badge-unknown";
  const analyzerBadge = badges.analyzer.tier === "fresh"
    ? `<span class="lm-badge lm-badge-fresh" title="${badges.analyzer.tip}">${fmt("freshnessFresh")}</span>`
    : badges.analyzer.tier === "stale"
      ? `<span class="lm-badge lm-badge-stale" title="${badges.analyzer.tip}">${fmt("freshnessStale")}</span>`
      : `<span class="lm-badge lm-badge-unknown" title="${badges.analyzer.tip}">${fmt("freshnessUntagged")}</span>`;
  const rawdataBadge = badges.rawdata.tier === "fresh"
    ? `<span class="lm-badge lm-badge-fresh" title="${badges.rawdata.tip}">${fmt("freshnessFresh")}</span>`
    : badges.rawdata.tier === "stale"
      ? `<span class="lm-badge lm-badge-stale" title="${badges.rawdata.tip}">${fmt("freshnessStale")}</span>`
      : `<span class="lm-badge lm-badge-unknown" title="${badges.rawdata.tip}">${fmt("freshnessUntagged")}</span>`;
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

function setKpi(id, text, tone = "neutral", compare = null) {
  const el = byId(id);
  if (!el) return; // element may have been replaced (e.g. kpiTail → kpiTailGrid)
  if (compare && (compare.textB !== undefined || compare.deltaText !== undefined)) {
    // Compare-aware tile: stack A on top, B underneath, optional Δ
    // chip below. Reuses the SAME card container as single-mode so
    // the tile's visual language stays put — only its inner content
    // gets denser. CSS rules in styles.css handle compact layout.
    const _esc = (s) => String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const sigCls = compare.deltaSig === "significant" ? "kpi-cmp-strong"
      : compare.deltaSig === "noise" ? "kpi-cmp-noise" : "kpi-cmp-unknown";
    el.innerHTML =
      `<div class="kpi-cmp-row"><span class="kpi-cmp-tag">A</span>${_esc(text)}</div>` +
      `<div class="kpi-cmp-row"><span class="kpi-cmp-tag kpi-cmp-tag-b">B</span>${_esc(compare.textB || "—")}</div>` +
      (compare.deltaText
        ? `<div class="kpi-cmp-delta ${sigCls}">${_esc(compare.deltaText)}</div>`
        : "");
  } else {
    el.textContent = text;
  }
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
  { const _ev = byId("eventsText"); if (_ev) _ev.textContent = fmt("noEvents"); }
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

// Maps a terminal-state client-event kind → the "start" kind it
// supersedes. pushClientEvent uses this to drop the start row from
// the activity strip once the outcome arrives, so the operator sees
// one line per completed action instead of "⟳ started" + "✓ done".
const ACTIVITY_TERMINAL_OF = {
  md5_refresh_done: "md5_refresh_start",
  md5_refresh_failed: "md5_refresh_start",
  batch_created: "submit",
  submit_failed: "submit",
  generate_report_done: "generate_report_start",
  generate_report_failed: "generate_report_start",
  generate_report_timeout: "generate_report_start",
};

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
    // Version icon = PURE server-version status (no longer mixed with CI). ✓ means
    // "report on the CURRENT server version", regardless of CI precision.
    let md5Icon = '';
    if (md5 === "match") {
      md5Icon = '<span class="md5-match" title="report 基于当前 server 版本">✓</span>';
    } else if (md5 === "outdated") {
      md5Icon = '<span class="md5-mismatch" title="report 基于旧 server 版本（需重采 / 重生）">⚠</span>';
    } else if (md5 === "untagged") {
      md5Icon = '<span class="muted" title="旧格式 report 无版本标签">?</span>';
    }
    // CI precision is a SEPARATE quality signal — colour the ± value amber when
    // loose (> 0.5pp). It is NOT a version problem (the old 🟡 conflated the two).
    const ciLoose = ciVal != null && ciVal > 0.5;
    const ciHtml = ci
      ? `<span class="cat-ci${ciLoose ? ' cat-ci-loose' : ''}"${ciLoose ? ' title="CI 不精确 (>0.5pp)，多采可收窄"' : ''}>${ci}</span>`
      : '';
    return `<div class="cat-mode-row">${md5Icon} <span class="cat-mode-label">m${mode}</span> <span class="cat-rtp">${rtp}</span> ${ciHtml} ${volHtml}${mechIcons ? ` <span class="cat-mech" title="${d.mechanics.join(', ')}">${mechIcons}</span>` : ""}</div>`;
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

// 4-state freshness chip for a catalog card — the clear "有没有当前 server 版本报表"
// answer. Combines the per-mode report md5_status (machinesSummary) with the
// machine's rawdata classification (rawdataOverview.per_machine) via
// PURE.machineFreshness: 当前 / 待生成 / 待重采 / 无. Rawdata lookup is built once
// per overview and cached on state (avoids an O(n) find per card).
function _machineFreshnessChip(machine) {
  const modeMap = ((state.machinesSummary || {}).machines || {})[machine];
  if (!state._rawByMachineCache || state._rawByMachineSrc !== state.rawdataOverview) {
    const map = {};
    (((state.rawdataOverview || {}).per_machine) || []).forEach((r) => {
      if (r && r.machine) map[r.machine] = r;
    });
    state._rawByMachineCache = map;
    state._rawByMachineSrc = state.rawdataOverview;
  }
  const raw = state._rawByMachineCache[machine];
  if (!modeMap && !raw) return "";  // nothing loaded yet → no misleading chip
  // Current effective analyzer version per mode (from the FRESH /api/versions/current).
  // Lets the chip downgrade 当前 → analyzer 过期待重生 when the report's analyzer moved.
  const effMap = ((state.currentVersions || {}).effective_versions) || {};
  const currentEffByMode = {};
  if (modeMap) {
    for (const mode of Object.keys(modeMap)) {
      const v = effMap[machine + "|" + mode];
      if (v) currentEffByMode[mode] = String(v);
    }
  }
  const f = PURE.machineFreshness(modeMap, raw, currentEffByMode);
  const short = { current: "当前", analyzer_stale: "待重生", ready_regen: "待生成", resample: "待重采", none: "无" };
  const tip = {
    current: "有基于当前 server 版本 + 当前 analyzer 的报表",
    analyzer_stale: "报表基于当前 server 版本，但 analyzer 已升级（过期）→ 点「重生 Report」（rawdata 已缓存，便宜）",
    ready_regen: "已有当前 server 版本 rawdata，但还没生成报表 → 点「重生 Report」",
    resample: "只有旧 server 版本的 rawdata → 需重新采样",
    none: "无 rawdata / 无报表",
  };
  return `<span class="cat-fresh cat-fresh-${f.state}" title="${f.label} — ${tip[f.state] || ""}">${short[f.state]}</span>`;
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
      // Legacy / old-framework machine: no SpinType-native manifest, so the new
      // engine can't (re)generate its reports (its on-disk reports stay
      // viewable). Grey it out + explain on hover; the regenerate button in the
      // detail pane is disabled separately.
      if (m.registered === false) {
        d.classList.add("legacy");
        d.title = "旧框架机台：新 SpinType 引擎不支持，旧报表仅可查看，无法重生成";
      }
      d.dataset.machine = m.machine;
      d.setAttribute("role", "button");
      d.setAttribute("tabindex", "0");
      const metrics = _catalogModeMetrics(m.machine);
      const reportBadge = m.report_count ? `<span class="catalog-badge" style="background:${catColor}">${m.report_count}</span>` : "";
      const issues = _machineBrokenIssues(m.machine);
      const brokenBadge = issues.length
        ? `<span class="catalog-broken" title="${issues.join(' · ').replace(/"/g, '&quot;')}">⚠</span>`
        : "";
      // Manifest review badge: ✓ if verified, · if reviewed but not
      // verified, ? if config_not_reviewed. Missing entry = no badge
      // (same UX as pre-Phase-3 catalog). Variants inherit from
      // underlying via the backend's eager cascade.
      const review = (state.manifestReviewState || {})[m.machine];
      let reviewBadge = "";
      if (review) {
        if (review.verified) {
          reviewBadge = `<span class="catalog-review verified" title="该机型 manifest 已核对，自检结果以完整置信度呈现">✓</span>`;
        } else if (review.reviewed) {
          reviewBadge = `<span class="catalog-review reviewed" title="该机型 manifest 已人工核对但尚未声明 console_diagnostic_complete">·</span>`;
        } else {
          reviewBadge = `<span class="catalog-review pending" title="该机型 manifest 使用 bootstrap 默认值，配置未核对；自检结果作软提示呈现">?</span>`;
        }
      }
      // Multi-select checkbox: stopPropagation in click handler so
      // card body click still focuses. Click body = focus, click
      // checkbox = batch multi-select (two independent affordances).
      const freshChip = _machineFreshnessChip(m.machine);
      d.innerHTML =
        `<input type="checkbox" class="catalog-check" title="加入批量操作" ${isMulti ? "checked" : ""}>` +
        `<div class="catalog-title">${m.machine}${freshChip}${reviewBadge}${brokenBadge}${reportBadge}</div>` +
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
  // Switching focus to a different machine invalidates any prior
  // MachineConfig probe (the checkbox and file metadata were for
  // the previous machine; sending them with a sample on a
  // different machine would silently apply wrong cfg).
  if (state.focusedMachine !== machine) {
    _clearStagedMachineConfig();
  }
  state.focusedMachine = machine;
  _syncAllCardsActiveDom();
  renderRunHistory();
  updateSampleHint();
  updateActionStates();
  renderDetailPane();
  renderMachineConfigOverride();
  // Async — no await; the card starts hidden, reveals itself on
  // response if a matching cfg file exists.
  _refreshMachineConfigAvailability(machine);
}

function _clearFocus() {
  state.focusedMachine = null;
  // Leaving focus mode drops the cfg-override probe (only applies
  // to focused single-machine sampling).
  _clearStagedMachineConfig();
  _syncAllCardsActiveDom();
  // Fix 1 (2026-04-19 round 3): unfocus must also refresh batch bar
  // + action states so the sticky bar hides when nothing is selected.
  // Without this, the bar stays stuck on "聚焦 Mx" with stale buttons.
  updateSampleHint();
  updateActionStates();
  renderDetailPane();
  renderMachineConfigOverride();
}

function _clearStagedMachineConfig() {
  state.machineConfigState = null;
}

async function _refreshMachineConfigAvailability(machine) {
  // Probe backend for machineconfig/<underlying>Cfg.txt existence.
  // Backend resolves variants → underlying via variants_map so a
  // M273 variant finds M273Cfg.txt. Best-effort: any fetch error
  // leaves state null → card stays hidden (no false advertising).
  if (!machine) { state.machineConfigState = null; renderMachineConfigOverride(); return; }
  try {
    const r = await fetch(`/api/machines/${encodeURIComponent(machine)}/cfg-availability`);
    if (!r.ok) throw new Error(`probe ${r.status}`);
    const body = await r.json();
    // Preserve current useLocal toggle IF we re-probe the same
    // machine (e.g. post-sampling refresh). On focus change the
    // whole state was nulled via _clearStagedMachineConfig, so
    // the fallback false is correct there.
    const prev = state.machineConfigState;
    const useLocal = (prev && prev.machine === machine) ? !!prev.useLocal : false;
    state.machineConfigState = {
      machine,
      available: !!body.available,
      underlying: body.underlying,
      filename: body.filename,
      bytes: body.bytes || 0,
      mtime_iso: body.mtime_iso || null,
      useLocal,
    };
  } catch (_e) {
    state.machineConfigState = null;
  }
  renderMachineConfigOverride();
}

function renderMachineConfigOverride() {
  const panel = byId("machineConfigOverride");
  if (!panel) return;
  const checkbox = byId("useLocalMachineConfig");
  const toggle = byId("useLocalConfigToggle");
  const clearBtn = byId("clearMachineConfigBtn");
  const info = byId("machineConfigFileInfo");
  const status = byId("machineConfigStatus");
  const s = state.machineConfigState;
  // Show whenever a machine is focused (probed). No focus → hide.
  if (!s || !s.machine) {
    panel.classList.add("hidden");
    if (checkbox) checkbox.checked = false;
    return;
  }
  panel.classList.remove("hidden");
  if (s.available) {
    // A config is cached server-side: status + clear + use-this toggle.
    const kb = (s.bytes / 1024).toFixed(1);
    const mtime = s.mtime_iso ? s.mtime_iso.substring(0, 16).replace("T", " ") : "?";
    if (info) info.textContent = `${s.filename} · ${kb} KB · ${mtime}`;
    if (toggle) toggle.classList.remove("hidden");
    if (clearBtn) clearBtn.classList.remove("hidden");
    if (checkbox) checkbox.checked = !!s.useLocal;
    if (status) {
      if (s.useLocal) {
        status.textContent = "✓ 下次采样将用这份 config 覆盖服务端全局";
        status.className = "config-override-status ok small";
      } else {
        status.textContent = "已缓存，本次未启用（勾选上方使用）";
        status.className = "config-override-status muted small";
      }
    }
  } else {
    // No config cached yet: just the upload button + a hint.
    if (info) info.textContent = "未上传（采样用服务器全局 config）";
    if (toggle) toggle.classList.add("hidden");
    if (clearBtn) clearBtn.classList.add("hidden");
    if (checkbox) checkbox.checked = false;
    if (status) { status.textContent = ""; status.className = "config-override-status muted small"; }
  }
}

// Upload (replace) the focused machine's local MachineConfig override. Reads
// the picked file as text, POSTs it; backend validates (machine match +
// structure) and writes machineconfig/<underlying>Cfg.txt. On success, re-probe
// and auto-enable "use this config". Validation errors surface inline.
function _uploadMachineConfig(machine) {
  const input = byId("machineConfigFileInput");
  if (!input || !machine) return;
  input.value = "";  // reset so re-picking the same file still fires change
  input.onchange = async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    const status = byId("machineConfigStatus");
    if (status) {
      status.textContent = "上传中…";
      status.className = "config-override-status muted small";
    }
    try {
      const text = await file.text();
      const r = await fetch(`/api/machines/${encodeURIComponent(machine)}/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        if (status) {
          status.textContent = `✗ ${body.detail || ("上传失败 " + r.status)}`;
          status.className = "config-override-status err small";
        }
        return;
      }
      await _refreshMachineConfigAvailability(machine);
      if (state.machineConfigState && state.machineConfigState.machine === machine) {
        state.machineConfigState.useLocal = true;  // default to using a fresh upload
        renderMachineConfigOverride();
      }
    } catch (e) {
      if (status) {
        status.textContent = `✗ 上传出错: ${(e && e.message) || e}`;
        status.className = "config-override-status err small";
      }
    }
  };
  input.click();
}

// Clear the focused machine's cached config → sampling reverts to global cfg.
async function _clearMachineConfig(machine) {
  if (!machine) return;
  try {
    await fetch(`/api/machines/${encodeURIComponent(machine)}/config`, { method: "DELETE" });
  } catch (_e) { /* best-effort; re-probe reflects truth */ }
  await _refreshMachineConfigAvailability(machine);
}

function _toggleMultiSelect(machine) {
  if (!machine) return;
  // Entering multi-select mode clears any focus.
  if (state.focusedMachine !== null) {
    state.focusedMachine = null;
    _clearStagedMachineConfig();
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
    // Keep the MachineConfig override card in sync with staged state
    // (filename, status line, clear button visibility) each time the
    // detail pane re-renders.
    try { renderMachineConfigOverride(); } catch (_) {}
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
    state.rawdataOverviewError = null;
  } catch (err) {
    state.rawdataOverview = null;
    state.rawdataOverviewError = String(err?.message || err || "unknown error");
  }
  renderRawdataBanner();
  // The catalog freshness chip (待生成 vs 待重采) depends on this overview's
  // per-machine current/historical rawdata. On initial load the catalog can
  // render before the overview resolves (both async), and rawdata ops change
  // the classification — so re-render the catalog here to keep chips truthful.
  if (state.machines && state.machines.length) renderMachineCatalog();
  // If the global detail view is already showing, re-render the table
  // so size/row changes after a cleanup reflect immediately.
  if (state.showGlobalRawdata) renderRawdataGlobalTable();
}

function renderRawdataBanner() {
  const banner = byId("rawdataOverviewBanner");
  if (!banner) return;
  const d = state.rawdataOverview;
  if (!d || !d.total_bytes) {
    // I4: surface fetch errors in the banner area so operators know the
    // rawdata overview isn't just "empty" but actually failed to load.
    if (state.rawdataOverviewError) {
      banner.classList.remove("hidden");
      banner.innerHTML = `<div class="rawdata-banner-row"><span class="muted" style="color:#b45309">⚠ rawdata 概览加载失败：${_escHtml(state.rawdataOverviewError)}</span></div>`;
      return;
    }
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
    (b.deletable_bytes + b.historical_bytes) - (a.deletable_bytes + a.historical_bytes)
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
          <th title="非当前 md5 的历史版本；不再自动删除，只通过缓存管理或手动删除">历史版本</th>
          <th>最近采样</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((r) => {
          const last = r.last_sample_mtime
            ? new Date(r.last_sample_mtime * 1000).toISOString().slice(0, 10)
            : "—";
          const reclaim = r.deletable_bytes + r.historical_bytes;
          const delDisabled = reclaim <= 0 || _isAnyBusy();
          return `<tr class="rawdata-global-row" data-machine="${r.machine}">
            <td><strong>${r.machine}</strong></td>
            <td>${fMbShort(r.kept_bytes)} <span class="muted">(${r.kept_chunks})</span></td>
            <td class="${r.deletable_bytes > 0 ? "rawdata-reclaim" : "muted"}">
              ${fMbShort(r.deletable_bytes)} <span class="muted">(${r.deletable_chunks})</span>
            </td>
            <td class="${r.historical_bytes > 0 ? "rawdata-historical" : "muted"}">
              ${fMbShort(r.historical_bytes)} <span class="muted">(${r.historical_chunks})</span>
            </td>
            <td class="muted">${last}</td>
            <td>
              <button class="small-btn danger-btn rwglobal-del-btn" data-machine="${r.machine}" ${delDisabled ? "disabled" : ""} title="删除此机台的可回收 + 历史版本 chunks（保留当前 md5 baseline）">🗑 ${fMbShort(reclaim)}</button>
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

  // Reveal the danger zone footer for this focused machine.
  _renderMachineDangerZone(machineName);

  // Load + render the rawdata × report tree async.
  renderRawdataReportTree(machineName);
}

// Render / re-arm the machine-detail "danger zone" wipe-all button.
// The HTML lives in index.html; we just toggle visibility, freshen
// the inline status copy (resets per-focus), and bind a single click
// handler. The handler is removed before re-binding so re-rendering
// the detail panel for a new machine doesn't stack listeners.
function _renderMachineDangerZone(machineName) {
  const zone = byId("machineDangerZone");
  const btn = byId("machineWipeAllBtn");
  const status = byId("machineDangerZoneStatus");
  if (!zone || !btn) return;
  zone.classList.remove("hidden");
  if (status) status.textContent = "";
  // Replace handler each time focus changes (cheapest way to drop the
  // previous closure over the previous machine name).
  const fresh = btn.cloneNode(true);
  btn.parentNode.replaceChild(fresh, btn);
  fresh.disabled = _isAnyBusy();
  fresh.addEventListener("click", () => _onClickWipeAllMachineData(machineName));
}

// Two-stage confirmation flow: confirm() the destructive intent, then
// prompt() for the machine name to make accidental mass-wipe nearly
// impossible. After success, refresh every surface that derives from
// rawdata / reports / runs so the UI doesn't lie about what's gone.
async function _onClickWipeAllMachineData(machineName) {
  const status = byId("machineDangerZoneStatus");
  const btn = byId("machineWipeAllBtn");
  // Stage 1 — quick confirm.
  const stage1 = confirm(
    `即将清空 ${machineName} 的所有数据：\n\n`
    + `  · 所有 mode 的 rawdata（所有 chunks）\n`
    + `  · 所有 reports（每个 mode 的所有版本）\n`
    + `  · 该机台所有运行历史记录\n\n`
    + `此操作不可撤销。继续？`
  );
  if (!stage1) return;
  // Stage 2 — type the machine name to confirm.
  const typed = prompt(
    `请输入机台名 "${machineName}" 以确认清空（区分大小写）：`,
  );
  if (typed == null) return;
  if (typed.trim() !== machineName) {
    if (status) status.textContent = `已取消：输入 "${typed}" 与 "${machineName}" 不匹配。`;
    return;
  }

  if (btn) btn.disabled = true;
  if (status) status.textContent = `正在清空 ${machineName}…`;
  try {
    const resp = await fetch(
      `/api/machines/${encodeURIComponent(machineName)}/all-data`,
      { method: "DELETE" },
    );
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${resp.status}`);
    }
    const body = await resp.json();
    const summary = `✓ ${machineName} 已清空：删除 ${body.deleted_chunks || 0} chunks · `
      + `${body.deleted_report_versions || 0} report 版本 · `
      + `${body.runs_deleted || 0} 运行记录。`;
    if (status) status.textContent = summary;
    try {
      pushClientEvent({ level: "ok", text: summary });
    } catch (_) {}

    // Drop focus + currentRun so the detail pane resets cleanly
    // (otherwise the now-empty rwtree shows a stale "无 fresh report"
    //  hint while panels keep rendering KPIs from an orphan summary).
    state.focusedMachine = null;
    state.currentRunId = null;

    // Refresh every surface that derives from rawdata / reports / runs.
    try {
      const mSummary = await apiGet("/api/machines/summary");
      state.machinesSummary = mSummary;
    } catch (_) {}
    try { await refreshCache(); } catch (_) {}
    try { await refreshRunList(false); } catch (_) {}
    try { renderMachineCatalog(); } catch (_) {}
    try { renderRtpModeBar(); } catch (_) {}
    try { renderFleetOverview(); } catch (_) {}
    try { renderDetailPane(); } catch (_) {}
  } catch (err) {
    if (status) status.textContent = `✗ 清空失败：${String(err.message || err)}`;
    if (btn) btn.disabled = false;
  }
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

  // 2026-04-21 layout rewrite: flatten (mode × md5) pairs into the
  // grid. Previously one cell per mode with an md5 dropdown filtering
  // all cells at once + a "跨版本对比" button pairing two md5s; both
  // gone now. Each (mode, md5) pair is its own cell with its own
  // stats, lock button, generate-report button, and delete-rawdata
  // button. Reports routed to the cell matching their declared md5;
  // untagged reports land on the mode's current-md5 cell (or the
  // first cell if no current-md5 exists).
  container.classList.remove("rwtree-cross");
  container.innerHTML = `<div class="rwtree rwtree-grid" id="rwtreeSingleGrid"></div>`;
  const grid = byId("rwtreeSingleGrid");
  _renderRwtreeGrid(grid, machineName, modes, rawdataModes, reportsByMode,
                    reportMd5Map, fInt2, fMb);
  _ensureCompareBar(container.parentElement);
  _updateRwtreeCompareBar();
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

// Core per-grid renderer (2026-04-21 rewrite). Produces one cell per
// (mode, md5) pair. Reports with declared md5 route to their matching
// cell; untagged reports go to the mode's current-md5 cell (or first
// cell if none current). Modes with no rawdata AND no reports are
// hidden entirely (user 2026-04-21).
function _renderRwtreeGrid(gridEl, machineName, modes, rawdataModes, reportsByMode,
                           reportMd5Map, fInt2, fMb) {
  // Build per-mode (md5 -> cellData) buckets.
  const modeCells = [];  // [{mode, st, cells: [{key, config_md5, code_md5, is_current, untagged, versions, reports}]}]
  modes.forEach((mode, i) => {
    const st = rawdataModes[String(mode)] || {};
    const versionsAll = Array.isArray(st.versions) ? st.versions : [];
    const allReports = reportsByMode[i].versions || [];

    const cellsByKey = new Map();
    const getCell = (cfgMd5, codeMd5, isCurrent, opts = {}) => {
      const key = `${cfgMd5}|${codeMd5}|${opts.untagged ? "untag" : "md5"}`;
      if (!cellsByKey.has(key)) {
        cellsByKey.set(key, {
          key,
          config_md5: cfgMd5,
          code_md5: codeMd5,
          is_current: !!isCurrent,
          // Optional label — backend tags current md5 buckets with
          // "服务端" (server global) or "本地 cfg (<file>)" so the
          // UI can distinguish multiple concurrently-"current" buckets.
          // Historical cells leave this empty.
          current_label: opts.current_label || "",
          current_source: opts.current_source || "",
          untagged: !!opts.untagged,
          versions: [],  // rawdata version stats (config/code md5 + counts)
          reports: [],
        });
      } else if (isCurrent && opts.current_label && !cellsByKey.get(key).current_label) {
        // First version of this cell was tagged without a label;
        // a later version carried the label — upgrade in place.
        cellsByKey.get(key).current_label = opts.current_label;
        cellsByKey.get(key).current_source = opts.current_source || "";
      }
      return cellsByKey.get(key);
    };

    // Bucket rawdata versions. Backend's ``versions`` entries now
    // carry ``is_current`` + ``current_label`` / ``current_source``
    // so multi-current (server + local-cfg) can be distinguished.
    for (const v of versionsAll) {
      const cell = getCell(
        v.config_md5 || "", v.code_md5 || "", !!v.is_current,
        { current_label: v.current_label || "", current_source: v.current_source || "" },
      );
      cell.versions.push(v);
    }

    // Route reports. Each report lands in the cell whose (config_md5,
    // code_md5) matches the report's stored rawdata md5. Untagged
    // reports (legacy, pre-md5-stamping) go to a SEPARATE synthetic
    // cell — NEVER commingled with the current cell, since we can't
    // prove they belong to the current rawdata. Bug 2026-04-26:
    // operator pulled fresh rawdata, but the "current" cell still
    // showed 4-5 historical reports because untagged were defaulted
    // into the current cell.
    const untaggedReports = [];
    for (const rep of allReports) {
      const info = reportMd5Map.get(rep.report_version);
      if (!info || info.md5_status === "untagged" || !info.config_md5) {
        untaggedReports.push(rep);
        continue;
      }
      const cell = getCell(
        info.config_md5, info.code_md5, info.md5_status === "match",
      );
      cell.reports.push(rep);
    }
    if (untaggedReports.length > 0) {
      // Always materialise a dedicated untagged cell (sorts to the
      // very end via the cells.sort() below). The cell's header
      // label reads "Mode N · 未标记" so the operator immediately
      // sees these reports aren't tied to any visible md5. Older
      // reports without rawdata md5 stamping live here regardless
      // of whether the current rawdata exists or not — this is the
      // honest answer "we can't tell which rawdata generated these".
      const untaggedCell = getCell("", "", false, { untagged: true });
      untaggedCell.reports.push(...untaggedReports);
    }

    // Mode-hide rule: no rawdata + no reports → skip this mode.
    if (cellsByKey.size === 0) return;

    // Sort: current md5 first, then by md5 alphabetically. Synthetic
    // untagged-only cells sort to the very end.
    const cells = [...cellsByKey.values()].sort((a, b) => {
      if (a.untagged !== b.untagged) return a.untagged ? 1 : -1;
      if (a.is_current !== b.is_current) return a.is_current ? -1 : 1;
      return (a.config_md5 || "").localeCompare(b.config_md5 || "");
    });
    modeCells.push({ mode, st, cells });
  });

  if (modeCells.length === 0) {
    gridEl.innerHTML = `<div class="muted" style="padding:20px;text-align:center">此机台暂无 rawdata 也无 reports</div>`;
    return;
  }

  // Flatten and render.
  const html = modeCells.flatMap(({ mode, st, cells }) =>
    cells.map((cell) => _renderRwtreeCell(machineName, mode, st, cell, reportMd5Map, fInt2, fMb))
  ).join("");
  gridEl.innerHTML = html;
  _wireRwtreeGridActions(gridEl, machineName);
}

// Render a single (mode × md5) cell. Extracted from _renderRwtreeGrid
// so the per-cell HTML is easier to reason about.
function _renderRwtreeCell(machineName, mode, st, cell, reportMd5Map, fInt2, fMb) {
  // Recompute stats from this cell's rawdata versions (already
  // filtered by md5 during bucketing).
  const versions = cell.versions;
  const keptSpins = versions.reduce((s, v) => s + (v.kept_spins || 0), 0);
  const delSpins = versions.reduce((s, v) => s + (v.deletable_spins || 0), 0);
  const historicalSpins = versions.reduce((s, v) => s + (v.historical_spins || 0), 0);
  const totalSpins = keptSpins + delSpins + historicalSpins;
  const keptChunks = versions.reduce((s, v) => s + (v.kept_chunks || 0), 0);
  const delChunks = versions.reduce((s, v) => s + (v.deletable_chunks || 0), 0);
  const historicalChunks = versions.reduce((s, v) => s + (v.historical_chunks || 0), 0);
  const totalChunks = keptChunks + delChunks + historicalChunks;

  // Cell header — "Mode N · 当前" / "Mode N · 历史 · cfg变更" /
  // "Mode N · 未标记". Upstream reports two md5s (configSummaryMd5 +
  // codeSummaryMd5) per machine — either flipping counts as a
  // rawdata version change (user 2026-04-21). The status tag calls
  // out WHICH half drifted so the operator doesn't have to diff
  // hashes by hand.
  const upCfg = String(st.upstream_config_md5 || "");
  const upCode = String(st.upstream_code_md5 || "");
  const cfgMatch = cell.config_md5 === upCfg;
  const codeMatch = cell.code_md5 === upCode;
  const cfgShort = (cell.config_md5 || "").slice(0, 8) || "—";
  const codeShort = (cell.code_md5 || "").slice(0, 8) || "—";

  let headerLabel;
  let statusTag;
  if (cell.untagged) {
    headerLabel = `Mode ${mode} · 未标记`;
    statusTag = `<span class="rwtree-status none" title="此 report 未标记 md5（v1 envelope 迁移遗留）">未标记</span>`;
  } else if (cell.is_current) {
    // Multi-current: server global + local-cfg can BOTH be "current"
    // simultaneously. Append the backend-supplied label so operators
    // see which of several current buckets they're looking at.
    // Falls back to just "当前" when label is empty (legacy responses).
    const currentSuffix = cell.current_label
      ? ` · ${cell.current_label}`
      : "";
    headerLabel = `Mode ${mode} · 当前${currentSuffix} ${cfgShort}…`;
    statusTag = `<span class="rwtree-status ok">✅当前</span>`;
  } else {
    // Historical: label which half drifted. If only code differs,
    // lead the header with the code md5 short (config is the same
    // as current, so showing config-short is confusing).
    const leadShort = !cfgMatch ? cfgShort : codeShort;
    headerLabel = `Mode ${mode} · 历史 ${leadShort}…`;
    let diffLabel;
    if (!cfgMatch && !codeMatch) diffLabel = "历史 · 两者变更";
    else if (!cfgMatch)          diffLabel = "历史 · config 变更";
    else                         diffLabel = "历史 · code 变更";
    const tip = `cfg: ${cfgShort}…${cfgMatch ? " ✓" : " ≠ " + upCfg.slice(0, 8) + "…"}\n`
      + `code: ${codeShort}…${codeMatch ? " ✓" : " ≠ " + upCode.slice(0, 8) + "…"}`;
    statusTag = `<span class="rwtree-status historical" title="${tip}">${diffLabel}</span>`;
  }

  // Compact md5 detail line — both halves, ✓ if matches current
  // upstream, ≠ otherwise. Rendered inside rawdataBlock below for
  // cells that have chunks; untagged cells skip it (no md5 to show).
  const md5DetailLine = cell.untagged
    ? ""
    : `<div class="rwtree-rawdata-line muted rwtree-md5-detail" title="两个 md5 任一变化 = rawdata 版本变更；悬停看对比">`
      + `cfg <span class="${cfgMatch ? "md5-match" : "md5-drift"}">${_escHtml(cfgShort)}${cfgMatch ? " ✓" : " ⚠"}</span>`
      + ` · code <span class="${codeMatch ? "md5-match" : "md5-drift"}">${_escHtml(codeShort)}${codeMatch ? " ✓" : " ⚠"}</span>`
      + `</div>`;

  const filteredReports = cell.reports;

  // Sample RTP/CI from best fresh report. See
  // ``PURE.freshReportsForCell`` for the full history and rationale —
  // 5+ regressions of "无 fresh report" before the cell-level
  // simplification. Short version: reports are routed to cells by
  // exact md5 match (see ``_renderRwtreeGrid``), so at the cell level
  // the freshness question reduces to ``cell.is_current``. The
  // backend marks both server-global AND localcfg-override current
  // md5 as ``is_current=true``, so localcfg-sampled reports correctly
  // count as fresh — fixing the 2026-04-27 regression where
  // /api/report-validate's upstream-only comparison falsely tagged
  // localcfg reports as "outdated".
  const freshReports = PURE.freshReportsForCell(cell);
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
    } else if (cell.is_current) {
      rawdataApprox = `<div class="rwtree-rawdata-approx muted" title="需要 analyzer+md5 都匹配当前的 report 才能显示 RTP/CI">
        <i>无 fresh report — 生成后会显示 RTP/CI</i>
      </div>`;
    } // else: historical cell — don't show the hint, point-in-time
      // comparisons live in the reports list below.
  }

  // Lock is (machine, mode) scoped — same lock button logic applies
  // to every cell of the same mode. Show lock state + controls only
  // on the FIRST cell of each mode (current md5 or the first
  // historical) so operator can't have two competing lock toggles
  // per mode. Cells beyond the first show a read-only lock indicator.
  const isLocked = !!st.locked;
  const lockIcon = isLocked ? "🔒" : "🔓";
  const lockTitle = isLocked
    ? "已上锁：缓存管理不会删这些 chunks"
    : "未上锁：超过 retention 的 chunks 可能被缓存管理删除";

  // Per-version delete — new 2026-04-21. Hidden when the cell is
  // untagged (no md5 tuple to target) or has no chunks.
  const canDeleteVersion = !cell.untagged && totalChunks > 0;
  const deleteTitle = isLocked
    ? "此 (机台, mode) 已上锁，先解锁才能删除该 md5 的 rawdata"
    : `删除该 md5 版本的 rawdata chunks（${totalChunks} 个文件，${fInt2(totalSpins)} spins）。reports 不会被删。`;
  const deleteBtn = canDeleteVersion
    ? `<button class="small-btn danger-btn rwtree-delver-btn" data-machine="${machineName}" data-mode="${mode}" data-cfg="${cell.config_md5}" data-code="${cell.code_md5}" ${(isLocked || _isAnyBusy()) ? "disabled" : ""} title="${deleteTitle}">🗑 删除该 rawdata</button>`
    : "";

  // Generate-report button: current md5 cell uses "current md5" path
  // (default analyzer behavior); historical cell passes config_md5 +
  // code_md5 so the analyzer scopes to that md5 bucket.
  const canGenerate = totalChunks > 0 && !cell.untagged;
  // Legacy machines (no SpinType-native manifest) can't be (re)generated by the
  // new engine — it 422s. Keep the button visible but DISABLED with a clear
  // reason; the machine's on-disk reports stay viewable.
  const _machineRegistered = ((state.machines || []).find((x) => x.machine === machineName) || {}).registered !== false;
  const genDisabled = _isAnyBusy() || !_machineRegistered;
  const genTitle = !_machineRegistered
    ? "旧框架机台：新 SpinType 引擎不支持重生成（旧报表仍可查看）"
    : (cell.is_current
      ? "用当前 analyzer 从这些 chunks 生成新 report"
      : `用当前 analyzer 从历史 md5 ${(cell.config_md5 || "").slice(0, 8)}… 的 chunks 生成 report`);
  const genBtn = canGenerate
    ? `<button class="small-btn primary-btn rwtree-gen-btn" data-machine="${machineName}" data-mode="${mode}" data-cfg="${cell.config_md5}" data-code="${cell.code_md5}" data-iscurrent="${cell.is_current ? "1" : "0"}" ${genDisabled ? "disabled" : ""} title="${genTitle}">⟳ 生成 Report</button>`
    : "";

  const rawdataBlock = totalChunks === 0
    ? `<div class="rwtree-rawdata empty"><div class="muted">无本地 rawdata${cell.untagged ? "（仅未标记 reports）" : ""}</div></div>`
    : `<div class="rwtree-rawdata ${isLocked ? "rwtree-locked" : ""}">
        <div class="rwtree-rawdata-line">
          <b>${fInt2(totalSpins)}</b> spins
          <span class="muted">(${totalChunks} chunks)</span>
        </div>
        <div class="rwtree-rawdata-line muted">
          ${cell.is_current
            ? `保底 ${fInt2(keptSpins)} / 可回收 ${fInt2(delSpins)}`
            : `历史 ${fInt2(historicalSpins)}（无保底）`}
        </div>
        ${md5DetailLine}
        ${rawdataApprox}
        <div class="rwtree-rawdata-actions">
          ${genBtn}
          <button class="small-btn rwtree-lock-btn ${isLocked ? "active" : ""}" data-machine="${machineName}" data-mode="${mode}" data-locked="${isLocked ? "1" : "0"}" title="${lockTitle}">${lockIcon} ${isLocked ? "已锁" : "锁定"}</button>
          ${deleteBtn}
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
  // Best-CI ⭐ is only meaningful in the CURRENT cell — historical
  // cells (whose reports are inherently outdated) shouldn't wear a
  // "best" star (2026-04-26 regression report). See
  // PURE.cellShowsBestCiStar for the predicate + tests.
  const bestCiVersion = PURE.cellShowsBestCiStar(cell)
    ? sortedReports[0]?.report_version
    : null;

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
          const info = reportMd5Map.get(rv) || {};
          const analyzerStatus = info.analyzer_status || "untagged";
          let analyzerBadge = "";
          if (analyzerStatus === "outdated") {
            analyzerBadge = `<span class="rwtree-analyzer-badge stale" title="analyzer 版本已过期（report=${info.analyzer_version?.slice(0,10) || "?"}），建议重新生成">⚠</span>`;
          } else if (analyzerStatus === "untagged") {
            analyzerBadge = `<span class="rwtree-analyzer-badge untagged" title="report 未标记 analyzer 版本">·</span>`;
          }
          // Phase 3 (D10): show badge when underlying rawdata has been deleted.
          // ``v.underlying_removed`` is set by _tag_reports_stale() on index.json entries.
          const removedBadge = v.underlying_removed
            ? `<span class="rwtree-analyzer-badge stale" title="${fmt("underlyingRemovedBadge")}">${fmt("underlyingRemovedBadge")}</span>`
            : "";
          return `<div class="rwtree-report${expanded}" data-rv="${rv}">
            <div class="rwtree-report-summary">
              <input type="checkbox" class="rwtree-compare-check" data-rv="${rv}" data-mode="${mode}" ${checked} title="勾选以对比版本" />
              <span class="rwtree-report-date">${tsShort}</span>
              <span class="rwtree-report-rtp">${rtp}</span>
              <span class="rwtree-report-ci">${ci}</span>
              ${analyzerBadge}
              ${removedBadge}
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

  return `<div class="rwtree-col rwtree-col-${cell.is_current ? "current" : cell.untagged ? "untagged" : "historical"}" data-mode="${mode}" data-cfg="${cell.config_md5}" data-code="${cell.code_md5}">
    <div class="rwtree-col-head">
      <span class="rwtree-mode-label">${headerLabel}</span>
      ${statusTag}
    </div>
    ${rawdataBlock}
    ${reportsBlock}
  </div>`;
}

// Render the generate-report progress into the same #sampleProgressLog
// panel that sampling-run batches use. 2026-04-22 user feedback: "生成
// 对了，但是还是看不到 log, 应该跟拉取的 log 框整合到一起才对" — the
// start/done pair in the top activity strip is not enough; operators
// want the same per-chunk timeline they get for live sampling.
//
// We synthesize a one-item batch-shape ``data`` object from the gen
// run's /api/runs + /api/runs/{rid}/progress payloads so PURE.merge-
// Timeline + the existing renderSamplingProgress reuse works as-is.
// When a real sampling batch is active (state.activeBatchId set), the
// batch poll owns the panel and we step aside — the generate-report
// progress still streams through the top activity strip as before.
function _renderGenReportProgress(runRow, progressEvents, machine, mode) {
  // Deferred: real batch takes precedence. User can still see the gen
  // lifecycle in the top activity strip via pushClientEvent pairs.
  if (state.activeBatchId) return;
  const panel = byId("sampleProgressPanel");
  const meta = byId("sampleProgressMeta");
  const log = byId("sampleProgressLog");
  if (!panel || !meta || !log) return;
  panel.classList.remove("hidden");
  // Freeze flag (set by sampling batches on completion) shouldn't
  // affect us — we're a different operation. Clear it so the log
  // re-renders on our poll ticks.
  state.batchJustCompleted = false;

  const status = String(runRow.status || "").toLowerCase();
  // Synthesize batch-shape item so PURE.mergeTimeline + the existing
  // status-row rendering below both work. progress.chunks_done /
  // total_spins / halfwidth_pp come from the last chunk_progress
  // event (the summary endpoint carries these too but progress
  // events are authoritative for mid-run values).
  const last = [...(progressEvents || [])].reverse().find(
    (e) => e.event === "chunk_progress"
  ) || {};
  const runningProgress = {
    chunks_done: last.chunks_completed || 0,
    total_spins: last.total_spins || 0,
    current_rtp_pct: last.current_rtp_pct,
    halfwidth_pp: last.current_halfwidth_pp,
  };
  const syntheticData = {
    total: 1,
    completed: (status === "completed" || status === "failed" || status === "cancelled") ? 1 : 0,
    items: [{
      run_id: runRow.run_id,
      machine,
      mode,
      status,
      chunk_spin_times: runRow.chunk_spin_times || 0,
      error: runRow.error_message || null,
      stop_reason: last.stop_reason || null,
      ci_target_met: true,
      progress: status === "running" ? runningProgress : null,
      chunk_events: progressEvents || [],
    }],
    events: [{
      ts: runRow.started_at,
      level: "info",
      machine,
      text: `⟳ 生成 Report · ${machine} mode ${mode} · chunks 将从 rawdata 缓存读取`,
    }],
  };
  // Anchor start time for the t+Ns elapsed ticker.
  state.itemStartTimes = state.itemStartTimes || {};
  if (status === "running" && runRow.run_id && !state.itemStartTimes[runRow.run_id]) {
    state.itemStartTimes[runRow.run_id] = Date.now();
  }
  // Reuse renderSamplingProgress — it knows the shape, the CSS, the
  // scroll-preservation, everything. The dispatch inside doesn't care
  // whether data came from /api/batch-run or from us synthesizing.
  try { renderSamplingProgress(syntheticData); } catch (_) { /* best-effort */ }
}

// Poll a generate-report async run until it transitions out of
// running/queued. Fires activity-log events for start → done / failed
// and triggers a single rwtree refresh on completion so the new
// report appears immediately (user feedback 2026-04-22: "生成完成
// 以后也没有及时刷新, 我刷新网页才看得到").
//
// Also streams progress into the sample-log panel each tick so the
// operator sees chunk-level progress, not just start/done in the
// activity strip (2026-04-22 follow-up: "跟拉取的 log 框整合到一起").
//
// Caller has already pushed `generate_report_start` before the POST.
// This function owns the terminal event + the post-completion
// refresh. ~3min ceiling on polling so a hung run doesn't leak a
// setInterval forever; if it outlasts that, one final refresh runs
// (the report may have landed even after we stopped watching).
async function _pollGenerateReport(runId, machine, mode) {
  const started = Date.now();
  const MAX_WAIT_MS = 180_000;  // 3 minutes — 10k-chunk replays run ~30-90s
  const INTERVAL_MS = 2_000;
  let lastStatus = "";
  // Flag the active gen run so pushClientEvent's stub-render (which
  // fires inside our terminal pushClientEvent calls below) doesn't
  // clobber the chunk-timeline we just painted.
  state.activeGenRun = { runId, machine, mode };
  while (Date.now() - started < MAX_WAIT_MS) {
    try {
      // Parallel fetch of row + events; if either 404s (edge case
      // during thread spawn) we catch below and retry on the next tick.
      const [row, progressResp] = await Promise.all([
        apiGet(`/api/runs/${encodeURIComponent(runId)}`),
        apiGet(`/api/runs/${encodeURIComponent(runId)}/progress`)
          .catch(() => ({ events: [] })),
      ]);
      const status = String(row && row.status || "").toLowerCase();
      lastStatus = status;
      // Render into the sample log panel every tick so the operator
      // sees chunks tick by (not just a start/done pair).
      _renderGenReportProgress(
        row, progressResp.events || [], machine, mode,
      );
      if (status === "completed") {
        pushClientEvent("generate_report_done", {
          machine, mode,
          rtp_pct: row && row.achieved_rtp_pct,
          halfwidth_pp: row && row.achieved_halfwidth_pp,
        });
        try { await renderRawdataReportTree(machine); } catch (_) { /* best-effort */ }
        state.activeGenRun = null;
        return;
      }
      if (status === "failed" || status === "cancelled") {
        pushClientEvent("generate_report_failed", {
          machine, mode,
          error: String(row && row.error_message || "unknown").slice(0, 120),
        });
        try { await renderRawdataReportTree(machine); } catch (_) { /* best-effort */ }
        state.activeGenRun = null;
        return;
      }
    } catch (_) {
      // Transient polling error (404 at the very start if the thread
      // is still spawning, or a momentary backend hiccup). Don't
      // abort the poll — the next tick will retry.
    }
    await new Promise((r) => setTimeout(r, INTERVAL_MS));
  }
  // Ceiling hit. Final refresh in case the run finished between our
  // last poll and now. No terminal event because we genuinely don't
  // know the outcome.
  pushClientEvent("generate_report_timeout", {
    machine, mode, last_status: lastStatus,
  });
  try { await renderRawdataReportTree(machine); } catch (_) { /* best-effort */ }
  state.activeGenRun = null;
}

// Wire grid-level interactions. Runs after _renderRwtreeGrid has
// populated the grid with all cells; event listeners live on the
// individual buttons so re-renders naturally rebind.
function _wireRwtreeGridActions(gridEl, machineName) {
  // Wire buttons + checkboxes on the freshly-rendered grid.
  gridEl.querySelectorAll(".rwtree-report-summary").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.matches("input[type=checkbox]")) return;
      row.parentElement.classList.toggle("expanded");
    });
  });
  gridEl.querySelectorAll(".rwtree-compare-check").forEach((cb) => {
    cb.addEventListener("change", () => {
      const rv = cb.dataset.rv;
      if (cb.checked) {
        // Stash the focused machine alongside mode so cross-machine
        // compare works when the operator pivots focus between picks.
        state.compareSelected.set(rv, {
          mode: Number(cb.dataset.mode),
          machine: state.focusedMachine || null,
        });
      } else {
        state.compareSelected.delete(rv);
      }
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
      const cfg = btn.dataset.cfg || "";
      const code = btn.dataset.code || "";
      const isCurrent = btn.dataset.iscurrent === "1";
      const orig = btn.textContent;
      btn.disabled = true;
      btn.textContent = "生成中… (后台)";
      // Activity-log start event fires BEFORE the POST so the operator
      // sees "⋯ 生成 Report 中…" in the strip immediately — before, the
      // click produced no log entry at all (user feedback 2026-04-22:
      // "点击生成以后没有 log, 没法确认状态").
      pushClientEvent("generate_report_start", {
        machine: m, mode: Number(mo),
      });
      try {
        const body = { mode: Number(mo), async: true };
        // Scope the generated report to THIS cell's md5 pair. Applies
        // to every cell — current or historical — because the multi-
        // current world (server-global AND local-cfg pairs can BOTH
        // be "current" simultaneously) means omitting md5 would pool
        // chunks across buckets. User 2026-04-24: "从本地 config 的
        // rawdata 生成 report 时会把网络拉取的 rawdata 一起算进去".
        //
        // Historical: old behavior omitted md5 on current cells on
        // the theory that "the analyzer default is more forgiving";
        // that theory predated multi-current + sidecar-based md5
        // filtering and now silently merges buckets. Always pass
        // the cell's md5 — analyzer's empty-filter fallback is for
        // callers who genuinely want "all chunks", which no rwtree
        // cell click means.
        if (cfg && code) {
          body.config_md5 = cfg;
          body.code_md5 = code;
        }
        const resp = await apiPost(
          `/api/rawdata/${encodeURIComponent(m)}/generate-report`, body,
        );
        btn.textContent = "⏳ 已入队";
        await refreshRunList(false);
        // 2026-04-22: replace the fragile setTimeout(3000) auto-refresh
        // with an actual poll on the returned run_id. Three outcomes:
        //   completed → push done event + refresh rwtree
        //   failed    → push failed event with error_message
        //   timeout   → give up after ~3min, one-time rwtree refresh
        //               (so a long-running replay still surfaces if it
        //               eventually finishes after our poll gives up)
        const rid = resp && resp.run_id;
        if (!rid) {
          // Back-compat: old backend without run_id — fall back to the
          // old behavior. Should never happen now that both sides are
          // updated.
          setTimeout(() => renderRawdataReportTree(m), 3000);
          return;
        }
        _pollGenerateReport(rid, m, Number(mo));
      } catch (err) {
        pushClientEvent("generate_report_failed", {
          machine: m, mode: Number(mo),
          error: String(err && err.message ? err.message : err).slice(0, 120),
        });
        alert(`生成 Report 失败: ${String(err && err.message ? err.message : err)}`);
        btn.textContent = orig;
        btn.disabled = false;
      }
    });
  });
  // Per-version delete (删除该 rawdata) — new 2026-04-21. Hits the
  // DELETE /api/rawdata/{m}/mode/{mode}/version endpoint with the
  // cell's (config_md5, code_md5). Reports are untouched.
  gridEl.querySelectorAll(".rwtree-delver-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const m = btn.dataset.machine;
      const mo = btn.dataset.mode;
      const cfg = btn.dataset.cfg || "";
      const code = btn.dataset.code || "";
      if (!cfg || !code) return;
      const shortCfg = cfg.slice(0, 8);
      if (!confirm(`删除 ${m} mode ${mo} 中 md5=${shortCfg}… 的 rawdata chunks？\nreports 不会被删，可随时重新生成。`)) return;
      const orig = btn.textContent;
      btn.disabled = true;
      btn.textContent = "删除中…";
      try {
        const resp = await fetch(
          `/api/rawdata/${encodeURIComponent(m)}/mode/${encodeURIComponent(mo)}/version`,
          {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ config_md5: cfg, code_md5: code }),
          },
        );
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${resp.status}`);
        }
        await renderRawdataReportTree(machineName);
      } catch (err) {
        alert(`删除失败: ${err.message || err}`);
        btn.textContent = orig;
        btn.disabled = false;
      }
    });
  });
  gridEl.querySelectorAll(".rwtree-load-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const rid = btn.dataset.runId;
      if (!rid) return;
      const prevRid = state.currentRunId;
      state.currentRunId = rid;
      switchTab("debug");
      try {
        await refreshCurrentRun();
      } catch (err) {
        // refreshCurrentRun normally catches 404 internally, but a
        // downstream await (/progress, /report) can still throw 500 or
        // network error. Without this catch, the promise rejection
        // bubbles out, leaving currentRunId pointing at the new run
        // with panels half-populated by the previous run — the user
        // clicked "load mode 1" and sees mode 2's data stubbornly on
        // screen (2026-04-22 bug report).
        console.warn(`rwtree load-btn: refresh failed for run ${rid}:`, err);
        // Revert to clean slate. Prefer resetting panels over restoring
        // prevRid because the user's intent was "stop showing the old
        // report"; keeping prevRid would just re-load what they were
        // trying to replace.
        state.currentRunId = "";
        state.currentRunStatus = "";
        setLoadedMachineInfo(null);
        _resetDebugPanelsToEmpty();
        renderLiveStatusStrip();
        updateActionStates();
        void prevRid;  // retained for debuggability via closure/stack
      }
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
        // C1 (brief §3): remove deleted version from compareSelected Map.
        // C2 (brief §3): if user was in compare mode with this version,
        // exit compare mode and reset ALL compare-related UI panels
        // (per memory feedback_error_branch_resets_all_state.md).
        // _resetCompareModeToEmpty() also bumps _compareInvocationId
        // to discard any in-flight compareReports() fetch (C3).
        // R1 fix (P1-A5 round-2 critic): gate is compareMode.vA/vB
        // match, NOT compareSelected membership. Without this fix, the
        // sequence (uncheck vA → delete vA via per-row) leaves
        // compareMode.vA pointing at the deleted version indefinitely.
        state.compareSelected?.delete?.(rv);
        const cm = state.compareMode;
        if (cm && (cm.vA === rv || cm.vB === rv)) {
          _resetCompareModeToEmpty();
        }
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
    // C2 (brief §3): snapshot compareMode before the loop so we can
    // detect whether any deleted version was part of an active comparison.
    const cmBefore = state.compareMode;
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
      } catch (err) {
        console.warn(`批量删除: ${rv} 失败:`, err);
        failed += 1;
      }
    }
    // C1 + C2 (brief §3): if any deleted version was in an active
    // comparison, exit compare mode and reset ALL compare-related panels
    // (per memory feedback_error_branch_resets_all_state.md).
    // _resetCompareModeToEmpty() also bumps _compareInvocationId (C3).
    const deletedVersions = entries.map(([rv]) => rv);
    if (cmBefore && (
      deletedVersions.includes(cmBefore.vA) ||
      deletedVersions.includes(cmBefore.vB)
    )) {
      _resetCompareModeToEmpty();
    } else {
      state.compareSelected = new Map();
    }
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
      // (Endpoint name was wrong — should be /api/machines/refresh-md5,
      // not /api/servers/. Old call silently 404'd. Fixed 2026-04-25.)
      await apiPost("/api/machines/refresh-md5", {});
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
    // or the internal-server benchmark preset (robot_count=8, batch_concurrency=8).
    if (n > 0) {
      const firstMachine = effective[0];
      const tuned = state.tunedSamplingParams[`${firstMachine}|${mode}`];
      if (tuned) {
        lines.push(
          `⚙ 已调参 (${firstMachine} m${mode}): robot_count=${tuned.robot_count}, ` +
          `batch_concurrency=${tuned.batch_concurrency} · success=${fRate(tuned.success_rate, 1)}`
        );
      } else {
        lines.push(`未调参，将用预设 robot_count=8, batch_concurrency=8 (可先点 ⚙ 调参)`);
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
  // 2026-05-22 L1: wipe the persisted copy too so a refresh after
  // starting fresh doesn't show prev-batch lifecycle events.
  try { localStorage.removeItem("slot_console_clientEvents"); } catch {}
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
  //
  // 2026-05-22 floor lift: per user requirement, chunk_spin_times must be
  // >= 10000 so per-chunk RTP variance is well-behaved (~10k samples give
  // a tight CI for the chunk-level signal). Previous values (Collect 5000
  // / Lock-ReSpin-FreeSpin 2000 / others 1000) were tuned for the public
  // prod (WAN) endpoint where bigger chunks made wall time too long
  // and timeout retries expensive. On the internal-deploy loopback path
  // each 10k-spin chunk wall-times ~10s (vs 300s timeout default before
  // this commit; now 60s), so the floor lift is cheap and gives cleaner
  // per-chunk statistics.
  //
  // The category-aware branch is kept (instead of collapsing to a single
  // literal) so a future per-machine differentiation can fan back out
  // without re-discovering the structure.
  const items = selected.map((machine) => {
    const m = state.machines.find((x) => x.machine === machine);
    const cat = m?.category || "";
    let chunk_spin_times = 10000;
    if (cat === "Collect") chunk_spin_times = 10000;
    else if (cat === "Lock" || cat === "ReSpin" || cat === "FreeSpin") chunk_spin_times = 10000;
    const item = { machine, mode, chunk_spin_times };
    // Attach use_local_machine_config flag only on the focused-machine
    // flow (selected.length === 1 AND matches the focused machine
    // AND availability probe confirmed the file exists AND user
    // checked the box). Backend reads machineconfig/<underlying>Cfg.txt
    // at submit time — frontend just ships the flag, not the content.
    // Multi-select batches deliberately never carry this; cross-
    // machine cfg reuse is almost always wrong.
    const mcfg = state.machineConfigState;
    if (selected.length === 1
        && mcfg
        && mcfg.available
        && mcfg.useLocal
        && state.focusedMachine === machine
        && mcfg.machine === machine) {
      item.use_local_machine_config = true;
    }
    return item;
  });

  // Pick up autotune result for the first selected machine+mode if the
  // operator ran 调参 beforehand. Otherwise fall back to the preset.
  // 2026-04-24 internal-server stress test (M14 chunk=2000, 8-wave
  // sustained): 8×8 = 8,593 outer/s (p50 14.5s max 16.7s, 100% ok),
  // 8×16 = 7,629/s with 2× bigger chunks (not worth it), 8×32 starts
  // timing out. 3M-spin single-machine = 5.7-6.5 min.
  const tunedKey = `${selected[0]}|${mode}`;
  const tuned = state.tunedSamplingParams[tunedKey];
  const chunk_robot_count = tuned ? tuned.robot_count : 8;
  const batch_concurrency = tuned ? tuned.batch_concurrency : 8;

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
    // Drop any stashed lastFinishedBatchId + hide the resume button —
    // operator explicitly started a fresh batch, so the previous
    // incomplete-set is no longer the natural thing to continue.
    state.lastFinishedBatchId = null;
    const _resumeBtnHide = byId("sampleResumeBtn");
    if (_resumeBtnHide) _resumeBtnHide.classList.add("hidden");
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
  // Tag kind so downstream dedupe can match start/terminal pairs
  // without parsing the rendered text.
  ev._kind = kind;
  state.clientEvents.push(ev);
  // Hard cap so a pathological re-click loop can't grow this unbounded.
  if (state.clientEvents.length > 100) {
    state.clientEvents = state.clientEvents.slice(-100);
  }
  // 2026-05-22 L1: persist to localStorage so refresh / new tab in the
  // same browser keeps the UI-lifecycle trail. The backend events
  // (timeline) already survive refresh via re-fetch; this closes the
  // gap for the client-side synthetic events (submit / batch_created /
  // polling_started / resume_submitted / etc.).
  try {
    localStorage.setItem(
      "slot_console_clientEvents",
      JSON.stringify(state.clientEvents),
    );
  } catch {
    // localStorage quota or disabled (private mode); the in-memory
    // copy still works for this session.
  }
  // Also land the client event on the top "活动日志流" panel. Same
  // event shape (ts/level/source/text) but rendered by the ui-branch
  // of _formatActivityRow so the operator sees it without waiting
  // for backend events to arrive.
  state.activityEvents = state.activityEvents || [];
  // Dedupe: when a terminal event arrives for a previously-started
  // action, drop the "…start" row so the strip shows only the
  // outcome. Keeps the log scannable without losing the "still
  // running" signal in the gap between start and terminal arrival.
  const supersedes = ACTIVITY_TERMINAL_OF[kind];
  if (supersedes) {
    state.activityEvents = state.activityEvents.filter((e) =>
      !(e && e.source === "ui" && e._kind === supersedes)
    );
  }
  state.activityEvents.push(ev);
  if (state.activityEvents.length > 200) {
    state.activityEvents = state.activityEvents.slice(-200);
  }
  try { _renderActivityStrip(); } catch (_) {}
  // Eagerly re-render so the new event is visible without waiting for
  // the next poll tick. Uses a minimal synthetic `data` shape when no
  // batch data is available yet.
  // 2026-04-22: skip the stub render when a generate-report poll is
  // active — its own per-tick _renderGenReportProgress owns the panel
  // and the empty stub would wipe out the chunk events. Also skip
  // when batchJustCompleted so the frozen end-of-run log isn't
  // blanked by a stray client event fired after completion.
  if (!state.batchJustCompleted && !state.activeGenRun) {
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
        // 2026-05-22 task A1: capture incomplete-item count BEFORE
        // nulling activeBatchId so the resume button (also below) can
        // call POST /api/batch-run/{old_id}/resume with the right id.
        const incompleteItems = (data.items || []).filter(
          (i) => i.status === "cancelled" || i.status === "failed" || i.status === "pending"
        );
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
          const resumeHint = incompleteItems.length > 0
            ? ` · 可点 ↻ 继续未完成项 (${incompleteItems.length}/${data.total})`
            : "";
          meta.textContent = `${bannerIcon} 批次已结束 · ${data.completed}/${data.total}${note}${partialNote}${fn}${totalElapsed} · 日志保留，点击开始采样可覆盖${resumeHint}`;
        }
        state.batchJustCompleted = true;  // prevent further re-render
        // Stash the finished batch_id for the resume button. Cleared
        // when operator clicks 开始采样 (new batch) or 继续未完成项
        // (resume) so the stale id can't be replayed across sessions.
        state.lastFinishedBatchId = incompleteItems.length > 0 ? state.activeBatchId : null;
        state.activeBatchId = null;
        localStorage.removeItem("slot_console_activeBatchId");
        byId("sampleCancelBtn").classList.add("hidden");
        const startBtnEl = byId("sampleStartBtn");
        if (startBtnEl) {
          startBtnEl.classList.remove("hidden");
          startBtnEl.disabled = false;
        }
        // Surface the resume button only when there is something to
        // resume; otherwise stays hidden (completed-clean batch).
        const resumeBtnEl = byId("sampleResumeBtn");
        if (resumeBtnEl) {
          if (incompleteItems.length > 0) {
            resumeBtnEl.classList.remove("hidden");
            resumeBtnEl.disabled = false;
            resumeBtnEl.textContent = `↻ 继续未完成项 (${incompleteItems.length}/${data.total})`;
          } else {
            resumeBtnEl.classList.add("hidden");
          }
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

// 2026-05-22 task A1: re-submit a finished-but-incomplete batch.
// Backend extracts items whose status is not completed/attached, copies
// the original batch's params, and starts a fresh batch_id. Frontend
// adopts the new id and re-enters the polling loop just like a normal
// 开始采样 click — the only difference is the resume button + hint
// text. Cached chunks under rawdata/ are reused per-item via
// resume_from_cache (existing behavior), so already-partial cells
// continue from their last chunk index.
async function resumeSampling() {
  const oldBatchId = state.lastFinishedBatchId;
  if (!oldBatchId) return;
  const btn = byId("sampleResumeBtn");
  if (btn) { btn.disabled = true; btn.textContent = "提交中…"; }
  try {
    const r = await apiPost(`/api/batch-run/${oldBatchId}/resume`, {});
    if (!r || !r.batch_id) {
      throw new Error("resume response missing batch_id");
    }
    // Adopt the new batch_id and re-enter the polling lifecycle. Clear
    // the stale finished-id so the resume button does not double-fire
    // if the operator hits it again while waiting for the new batch.
    state.lastFinishedBatchId = null;
    state.activeBatchId = r.batch_id;
    state.batchStartedAt = Date.now();
    state.itemStartTimes = {};
    state.batchJustCompleted = false;
    state.clientEvents = [];
    // 2026-05-22 L1: also wipe the persisted copy so refresh after
    // starting a new batch doesn't show stale prev-batch events.
    try { localStorage.removeItem("slot_console_clientEvents"); } catch {}
    localStorage.setItem("slot_console_activeBatchId", r.batch_id);
    // Show progress panel + cancel button; hide start + resume.
    const panel = byId("sampleProgressPanel");
    if (panel) panel.classList.remove("hidden");
    const startBtnEl = byId("sampleStartBtn");
    if (startBtnEl) startBtnEl.classList.add("hidden");
    const cancelBtnEl = byId("sampleCancelBtn");
    if (cancelBtnEl) cancelBtnEl.classList.remove("hidden");
    if (btn) btn.classList.add("hidden");
    pushClientEvent("resume_submitted", {
      resumed_from_batch_id: oldBatchId,
      resumed_items: r.resumed_items,
      skipped_completed_items: r.skipped_completed_items,
    });
    pollSampling();
  } catch (e) {
    alert(String(e.message || e));
    if (btn) {
      btn.disabled = false;
      // Keep the button label readable so the operator knows it failed
      // and can retry; counters are stale at this point so the bare
      // label is honest enough.
      btn.textContent = "↻ 继续未完成项";
    }
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
  const defaultSid = state.defaultServer || "";
  tbody.innerHTML = servers.map((s) => {
    const isDefault = s.id === defaultSid;
    const statusBadge = s.active
      ? `<span class="srv-active">${fmt("serverActive")}</span>`
      : `<span class="srv-inactive">${fmt("serverInactive")}</span>`;
    const defaultBadge = isDefault
      ? ` <span class="srv-default" title="batch-run 会用这台">${fmt("serverDefault")}</span>`
      : "";
    const epDisplay = s.endpoint
      ? `<code class="srv-endpoint">${s.endpoint}</code>`
      : `<span class="muted">${fmt("serverNoEndpoint")}</span>`;
    // Set-as-default button: only shown for entries that have an
    // endpoint AND aren't already the default. Setting a no-endpoint
    // entry as default would just silently fallthrough at resolve time.
    const setDefaultBtn = (!isDefault && s.endpoint)
      ? `<button class="srv-set-default-btn small-btn">${fmt("btnSetDefault")}</button> `
      : "";
    return (
      `<tr data-server-id="${s.id}">` +
      `<td><strong>${s.id}</strong></td>` +
      `<td>${s.name}</td>` +
      `<td>${epDisplay}</td>` +
      `<td>${statusBadge}${defaultBadge}</td>` +
      `<td>${setDefaultBtn}<button class="srv-scan-btn small-btn">${fmt("btnScan")}</button> <button class="srv-check-btn small-btn">${fmt("btnCheckChanges")}</button> <button class="srv-edit-btn small-btn">${fmt("btnEdit")}</button> <button class="srv-delete-btn small-btn danger-btn">${fmt("btnDelete")}</button></td>` +
      `</tr>`
    );
  }).join("");

  // Wire up set-default button.
  tbody.querySelectorAll(".srv-set-default-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest("tr");
      const sid = row.dataset.serverId;
      btn.disabled = true;
      try {
        await apiPut(`/api/servers/${encodeURIComponent(sid)}/set-default`);
        await refreshServers();  // re-render with new badge
      } catch (e) {
        alert(String(e.message || e));
        btn.disabled = false;
      }
    });
  });

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
  // state.compareSelected is Map<version, {mode, machine?}>. Each
  // entry can carry its own machine + mode (cross-machine /
  // cross-mode compare allowed per user direction 2026-04-25).
  const entries = [...(state.compareSelected || new Map()).entries()];
  if (entries.length !== 2) return;
  const focusedMachine = state.versionHistoryMachine || state.focusedMachine;

  // C3 (brief §3): per-invocation guard. Increment before the fetch so
  // that if DELETE fires _resetCompareModeToEmpty() while the fetch is
  // in flight, the counter advances and the stale response is discarded
  // rather than applied (per memory feedback_fasttimer_overlap_needs_oneshot.md).
  state._compareInvocationId = (state._compareInvocationId || 0) + 1;
  const myInvocationId = state._compareInvocationId;

  try {
    const [[vA, metaA], [vB, metaB]] = entries;
    const machineA = metaA?.machine || focusedMachine;
    const machineB = metaB?.machine || focusedMachine;
    if (!machineA || !machineB) return;
    const [a, b] = await Promise.all([
      apiGet(`/api/reports/${encodeURIComponent(machineA)}/${metaA.mode}/${vA}`),
      apiGet(`/api/reports/${encodeURIComponent(machineB)}/${metaB.mode}/${vB}`),
    ]);
    // C3: check invocation id is still current before applying response.
    // If a DELETE raced and bumped _compareInvocationId, discard this
    // response visibly (C4: console.warn, not silent swallow).
    if (myInvocationId !== state._compareInvocationId) {
      console.warn(
        `compareReports: invocation ${myInvocationId} superseded by ` +
        `${state._compareInvocationId} (DELETE raced) — discarding stale response`,
      );
      return;
    }
    _enterCompareMode(a, b, vA, vB);
  } catch (e) {
    alert("加载对比 report 失败: " + (e.message || e));
  }
}

/** Enter compare mode. Switch to debug tab, paint a sticky banner,
 *  set state.compareMode so the existing analysis renderers can
 *  branch into A/B/Δ inline rendering. We do NOT hide any panels —
 *  the existing visual structure stays; renderers grow new columns
 *  in compare mode. */
async function _enterCompareMode(a, b, vA, vB) {
  state.compareMode = { a, b, vA, vB };
  if (typeof switchTab === "function") {
    switchTab("debug");
  }
  _renderCompareBanner();
  // URL persistence: <machine>|<mode>|<version> per side.
  try {
    const u = new URL(window.location.href);
    const sa = `${a.machine}|${a.mode}|${vA}`;
    const sb = `${b.machine}|${b.mode}|${vB}`;
    u.searchParams.set("compare", `${sa},${sb}`);
    window.history.replaceState({}, "", u.toString());
  } catch (_) { /* IE / non-URL env */ }
  // Re-paint the analysis tab using A as the primary summary. Each
  // compare-aware renderer reads state.compareMode.b inside itself
  // to add B/Δ. Calls the extracted helper directly — critically,
  // this does NOT go through refreshCurrentRun (which fetches based
  // on state.currentRunId, not necessarily A's run — produced the
  // "both sides identical" bug 2026-04-25).
  state.latestSummary = a;
  document.body.classList.add("cmp-active");
  try {
    await _paintAnalysisFromSummary(a);
  } catch (e) {
    console.error("compare paint failed:", e);
  }
}

function _renderCompareBanner() {
  const banner = byId("cmpBanner");
  if (!banner) return;
  const cm = state.compareMode;
  if (!cm) {
    banner.classList.add("hidden");
    banner.innerHTML = "";
    return;
  }
  const labelA = `${cm.a.machine || "?"} m${cm.a.mode || "?"} · ${(cm.vA || "").slice(3, 18)}`;
  const labelB = `${cm.b.machine || "?"} m${cm.b.mode || "?"} · ${(cm.vB || "").slice(3, 18)}`;
  banner.classList.remove("hidden");
  banner.innerHTML = `
    <span class="cmp-banner-tag">对比</span>
    <span class="cmp-banner-label cmp-banner-a">A · ${labelA}</span>
    <span class="cmp-banner-vs">vs</span>
    <span class="cmp-banner-label cmp-banner-b">B · ${labelB}</span>
    <button class="cmp-banner-exit" id="cmpBannerExit" title="退出对比">✕ 退出对比</button>`;
  byId("cmpBannerExit")?.addEventListener("click", _onCompareExit);
}

/** Reset ALL compare-mode state to a clean empty slate.
 *  Called by both _onCompareExit (button) and the DELETE path
 *  (per memory feedback_error_branch_resets_all_state.md, brief C2).
 *  Also bumps _compareInvocationId to invalidate any in-flight
 *  compareReports() fetch pair (brief C3). Does NOT repaint with
 *  latestSummary — that is left to callers that know the primary
 *  summary is still valid (e.g. _onCompareExit button press).
 *  Per brief C4: no try/catch wrapper — let real errors surface. */
function _resetCompareModeToEmpty() {
  // Bump invocation id so any concurrent compareReports() fetch
  // discards its response instead of applying stale compare data.
  state._compareInvocationId = (state._compareInvocationId || 0) + 1;
  state.compareMode = null;
  state.compareSelected = new Map();
  document.body.classList.remove("cmp-active");
  _renderCompareBanner();
  try { _updateRwtreeCompareBar(); } catch (e) {
    console.warn("_resetCompareModeToEmpty: _updateRwtreeCompareBar failed:", e);
  }
  try { renderDetailPane(); } catch (e) {
    console.warn("_resetCompareModeToEmpty: renderDetailPane failed:", e);
  }
  try {
    const u = new URL(window.location.href);
    if (u.searchParams.has("compare")) {
      u.searchParams.delete("compare");
      window.history.replaceState({}, "", u.toString());
    }
  } catch (e) {
    console.warn("_resetCompareModeToEmpty: URL update failed:", e);
  }
}

function _onCompareExit() {
  _resetCompareModeToEmpty();
  // Repaint analysis tab as single-mode using the last loaded summary.
  // compareMode is now null so renderers' compare branches won't fire —
  // they'll go down their normal single-render paths. Only attempt
  // repaint on explicit user exit (not on DELETE-triggered reset) because
  // latestSummary may itself be stale after a delete.
  if (state.latestSummary) {
    try {
      _paintAnalysisFromSummary(state.latestSummary);
    } catch (e) {
      console.warn("_onCompareExit: repaint failed:", e);
    }
  }
}

/** Restore compare mode from URL on page load — operator's link
 *  shares are persistent. */
async function _restoreCompareFromUrl() {
  try {
    const u = new URL(window.location.href);
    const raw = u.searchParams.get("compare");
    if (!raw) return;
    const parts = raw.split(",");
    if (parts.length !== 2) return;
    const parsed = parts.map((p) => {
      const [machine, mode, version] = p.split("|");
      return { machine, mode: Number(mode), version };
    });
    if (!parsed[0].machine || !parsed[1].machine) return;
    const [a, b] = await Promise.all([
      apiGet(`/api/reports/${encodeURIComponent(parsed[0].machine)}/${parsed[0].mode}/${parsed[0].version}`),
      apiGet(`/api/reports/${encodeURIComponent(parsed[1].machine)}/${parsed[1].mode}/${parsed[1].version}`),
    ]);
    _enterCompareMode(a, b, parsed[0].version, parsed[1].version);
  } catch (_e) {
    // Bad / stale ?compare= — strip it and continue normal boot.
    try {
      const u = new URL(window.location.href);
      u.searchParams.delete("compare");
      window.history.replaceState({}, "", u.toString());
    } catch (_) {}
  }
}

// renderComparison + fmtNum / fmtInt / fmtPct / diffPp helpers
// DELETED 2026-04-25: replaced by the multi-section compare module
// in frontend/compare.js + compare_diff.js. The new flow takes
// over the entire 调试机台 tab body when 2 reports are selected.
// See COMPARE.enterCompareMode for the entry point.

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
  // Compare-mode B summary. Pulled once at the top so both the
  // overall-top-20 and per-column matrix use the same source.
  // ``cmpB`` falsy → single-mode rendering, byte-identical to
  // pre-compare behavior.
  const cmpB = state.compareMode && state.compareMode.b ? state.compareMode.b : null;

  // ─── Overall top-20 ────────────────────────────────────────────
  const overallTbody = byId("symbolOverallTable") && byId("symbolOverallTable").querySelector("tbody");
  if (overallTbody) {
    const rows = PURE.formatSymbolRows(summary);
    const rowsB = cmpB ? PURE.formatSymbolRows(cmpB) : [];
    // Build B map for alignment.
    const bMap = new Map();
    for (const r of rowsB) bMap.set(String(r.symbol), r);
    const aSet = new Set(rows.map((r) => String(r.symbol)));
    // Union: A's order first (already sorted by count desc), B-only
    // appended at the end.
    const merged = [...rows];
    if (cmpB) {
      for (const r of rowsB) {
        if (!aSet.has(String(r.symbol))) merged.push(r);
      }
    }
    if (!merged.length) {
      overallTbody.innerHTML = `<tr><td colspan="3">${fmt("symbolsEmpty")}</td></tr>`;
    } else {
      // Bar scale: union max across A and B counts.
      const maxCount = Math.max(
        ...merged.map((r) => r.count),
        ...(cmpB ? rowsB.map((r) => r.count) : []),
        0,
      );
      overallTbody.innerHTML = merged
        .map((r) => {
          const aIn = aSet.has(String(r.symbol));
          const bRow = cmpB ? bMap.get(String(r.symbol)) : null;
          const aCountRaw = aIn ? Number(r.count || 0) : NaN;
          const bCountRaw = bRow ? Number(bRow.count || 0) : NaN;
          const aRateRaw = aIn ? Number(r.rate_pct || 0) : NaN;
          const bRateRaw = bRow ? Number(bRow.rate_pct || 0) : NaN;
          const aCountFmt = aIn ? fInt(r.count) : "—";
          const bCountFmt = bRow ? fInt(bRow.count) : "—";
          const aRateFmt = aIn ? r.rate_pct.toFixed(3) + "%" : "—";
          const bRateFmt = bRow ? bRow.rate_pct.toFixed(3) + "%" : "—";
          const aBar = maxCount > 0 ? Math.min(100, ((aIn ? r.count : 0) / maxCount) * 100) : 0;
          const bBar = cmpB && maxCount > 0 ? Math.min(100, ((bRow ? bRow.count : 0) / maxCount) * 100) : 0;
          const barCell = cmpB
            ? `<td class="cmp-text-bar-cell">${_cmpCell(true, aCountFmt, bCountFmt, aCountRaw, bCountRaw, "rel", 0, { aBarPct: aBar, bBarPct: bBar })}</td>`
            : `<td class="bar-cell" style="--bar:${aBar.toFixed(1)}%">${aCountFmt}</td>`;
          // Symbol name column shows a presence tag in compare mode
          // when the symbol only fired on one side.
          let symCell = `<code>${_escHtml(r.symbol)}</code>`;
          if (cmpB) {
            if (aIn && !bRow) symCell += ` <span class="pid-presence-tag pid-presence-a">A only</span>`;
            else if (!aIn && bRow) symCell += ` <span class="pid-presence-tag pid-presence-b">B only</span>`;
          }
          return (
            `<tr>` +
            `<td>${symCell}</td>` +
            barCell +
            `<td>${_cmpCell(!!cmpB, aRateFmt, bRateFmt, aRateRaw, bRateRaw, "pp", 2)}</td>` +
            `</tr>`
          );
        })
        .join("");
    }
  }
  // ─── By-column matrix ──────────────────────────────────────────
  const matrixHost = byId("symbolByColMatrix");
  if (!matrixHost) return;
  const matrix = PURE.symbolByColMatrix(summary);
  const matrixB = cmpB ? PURE.symbolByColMatrix(cmpB) : null;
  if (!matrix.columnIds.length && !(matrixB && matrixB.columnIds.length)) {
    matrixHost.textContent = fmt("symbolsEmpty");
    return;
  }
  // Union of column IDs: A's order first, then B-only.
  const aCols = new Set(matrix.columnIds.map((c) => String(c)));
  const allCols = [...matrix.columnIds];
  if (matrixB) {
    for (const c of matrixB.columnIds) {
      if (!aCols.has(String(c))) allCols.push(c);
    }
  }
  // Shared _renderReelColumnHtml helper produces per-column blocks with
  // the same layout used by _renderReelMarginalMatrix (ST-split panels).
  matrixHost.innerHTML = allCols
    .map((col) => {
      const rows = matrix.rowsByCol[col] || [];
      const rowsB = matrixB ? (matrixB.rowsByCol[col] || []) : [];
      // 2026-04-24: dual-column view (窗口 + 支付线). For single-payline
      // classic slots (M1/M37), payline shows mid-row density — same
      // data as window on reels whose paylines cover all rows, but
      // dramatically different on sparse-payline machines (reveals
      // near-miss clustering: wild with 4× window/payline ratio is
      // a visual tease symbol, not a payout engine).
      const paylineMap = (matrix.paylineByCol && matrix.paylineByCol[col]) || {};
      const paylineMapB = (matrixB && matrixB.paylineByCol && matrixB.paylineByCol[col]) || {};
      const paylineRows = (matrix.paylineRowsByCol && matrix.paylineRowsByCol[col]) || [];
      const paylineRowsB = (matrixB && matrixB.paylineRowsByCol && matrixB.paylineRowsByCol[col]) || [];
      const useRows = paylineRows.length ? paylineRows : paylineRowsB;
      const headerLabel = useRows.length
        ? fmt("symbolColLabelWithPaylineRows", {
            idx: col,
            rows: useRows.join(","),
          })
        : fmt("symbolColLabel", { idx: col });
      return _renderReelColumnHtml(rows, {
        colId: col,
        headerLabel,
        rowsB: cmpB ? rowsB : null,
        paylineMap,
        paylineMapB: cmpB ? paylineMapB : null,
        cmpB: !!cmpB,
        includePayline: true,
      });
    })
    .join("");
}

function renderPaylineDrilldown(summary) {
  const tbody = byId("paylineTable") && byId("paylineTable").querySelector("tbody");
  if (!tbody) return;
  const rows = PURE.formatPaylineRows(summary);

  // Compare-aware: align by payline_id, A's order first, then
  // B-only appended. Top-symbols column stays A-side (it's
  // structural / per-machine; same machine same mode shouldn't
  // see drift). Source badge also A-side.
  const cmpB = state.compareMode && state.compareMode.b ? state.compareMode.b : null;
  const rowsB = cmpB ? PURE.formatPaylineRows(cmpB) : [];
  const bMap = new Map();
  for (const r of rowsB) bMap.set(String(r.payline_id), r);
  const aSet = new Set(rows.map((r) => String(r.payline_id)));
  const merged = [...rows];
  if (cmpB) {
    for (const r of rowsB) {
      if (!aSet.has(String(r.payline_id))) merged.push(r);
    }
  }
  if (!merged.length) {
    tbody.innerHTML = `<tr><td colspan="6">${fmt("paylineEmpty")}</td></tr>`;
    return;
  }
  // Bar scale: union max RTP across both sides.
  const maxRtp = Math.max(
    ...merged.map((r) => r.rtp_contribution_pp),
    ...(cmpB ? rowsB.map((r) => r.rtp_contribution_pp) : []),
    0,
  );
  tbody.innerHTML = merged
    .map((r) => {
      const aIn = aSet.has(String(r.payline_id));
      const bRow = cmpB ? bMap.get(String(r.payline_id)) : null;
      const aHitRaw = aIn ? Number(r.hit_count || 0) : NaN;
      const bHitRaw = bRow ? Number(bRow.hit_count || 0) : NaN;
      const aHitRateRaw = aIn ? Number(r.hit_rate_pct || 0) : NaN;
      const bHitRateRaw = bRow ? Number(bRow.hit_rate_pct || 0) : NaN;
      const aRtpRaw = aIn ? Number(r.rtp_contribution_pp || 0) : NaN;
      const bRtpRaw = bRow ? Number(bRow.rtp_contribution_pp || 0) : NaN;
      const aWinRaw = aIn ? Number(r.win_share_pct || 0) : NaN;
      const bWinRaw = bRow ? Number(bRow.win_share_pct || 0) : NaN;

      const aBar = maxRtp > 0 ? Math.min(100, ((aIn ? r.rtp_contribution_pp : 0) / maxRtp) * 100) : 0;
      const bBar = cmpB && maxRtp > 0 ? Math.min(100, ((bRow ? bRow.rtp_contribution_pp : 0) / maxRtp) * 100) : 0;
      const aHitFmt = aIn ? fInt(r.hit_count) : "—";
      const bHitFmt = bRow ? fInt(bRow.hit_count) : "—";
      const aHitRateFmt = aIn ? r.hit_rate_pct.toFixed(3) + "%" : "—";
      const bHitRateFmt = bRow ? bRow.hit_rate_pct.toFixed(3) + "%" : "—";
      const aRtpFmt = aIn ? r.rtp_contribution_pp.toFixed(4) : "—";
      const bRtpFmt = bRow ? bRow.rtp_contribution_pp.toFixed(4) : "—";
      const aWinFmt = aIn ? r.win_share_pct.toFixed(2) + "%" : "—";
      const bWinFmt = bRow ? bRow.win_share_pct.toFixed(2) + "%" : "—";

      const topSyms = aIn
        ? PURE.formatPaylineTopSymbols(r.top_symbols, 3)
        : (bRow ? PURE.formatPaylineTopSymbols(bRow.top_symbols, 3) : "");
      // Prefix a source badge on the top-symbols cell so 策划 can tell
      // at a glance whether the symbol list is authoritative (from
      // RewardLastNode codes) or heuristic (left-3-col intersection).
      const src = aIn ? r.top_symbols_source : (bRow ? bRow.top_symbols_source : null);
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
      // Presence tag in compare mode.
      let presence = "";
      if (cmpB) {
        if (aIn && !bRow) presence = ` <span class="pid-presence-tag pid-presence-a">A only</span>`;
        else if (!aIn && bRow) presence = ` <span class="pid-presence-tag pid-presence-b">B only</span>`;
      }
      // Compare mode: pass aBar/bBar to _cmpCell so each side's value
      // gets an inline magnitude bar paired on the same line as its
      // tag and number. Single mode: keep the legacy bar-behind-text
      // cell where the absolute-positioned ::after sits under "23.24pp".
      const barCell = cmpB
        ? `<td class="cmp-text-bar-cell">${_cmpCell(true, aRtpFmt, bRtpFmt, aRtpRaw, bRtpRaw, "pp", 4, { aBarPct: aBar, bBarPct: bBar })}</td>`
        : `<td class="bar-cell" style="--bar:${aBar.toFixed(1)}%">${aRtpFmt}</td>`;
      return (
        `<tr>` +
        `<td><code>${_escHtml(r.payline_id)}</code> ${plineBadge}${presence}</td>` +
        `<td>${_cmpCell(!!cmpB, aHitFmt, bHitFmt, aHitRaw, bHitRaw, "rel")}</td>` +
        `<td>${_cmpCell(!!cmpB, aHitRateFmt, bHitRateFmt, aHitRateRaw, bHitRateRaw, "pp", 3)}</td>` +
        barCell +
        `<td>${_cmpCell(!!cmpB, aWinFmt, bWinFmt, aWinRaw, bWinRaw, "pp", 2)}</td>` +
        `<td>${srcBadge}${topSyms}</td>` +
        `</tr>`
      );
    })
    .join("");
}

function renderReportSelfCheck(summary) {
  // Surface summary.rtp_integrity_check (Phase 5 partial — PIA wires the
  // 4-layer integrity gate into every report). Display contract:
  //   - "verified" machines (completeness_declared=true): full visual weight
  //   - "unreviewed" machines (completeness_declared=false): soft hint mode
  //   - never blocks: gate is informational only per user direction 2026-05-20
  // Hidden when the field is absent (old reports pre-Phase-5).
  const el = byId("reportSelfCheck");
  if (!el) return;
  const chk = (summary || {}).rtp_integrity_check;
  if (!chk || typeof chk !== "object") {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  // Error path (Layer4Error / unexpected exception during gate run).
  if (chk.error) {
    el.classList.remove("hidden");
    el.className = "self-check-box self-check-error";
    el.innerHTML = `
      <div class="self-check-head">
        <span class="self-check-icon">⚠</span>
        <span class="self-check-title">报告自检未能完成</span>
      </div>
      <div class="self-check-body">${escapeHtml(chk.error)}</div>
    `;
    return;
  }
  // Normal path: 4 layers + summary message + suggested actions.
  const reviewed = chk.completeness_declared === true;
  const pass = chk.passed === true;
  el.classList.remove("hidden");
  // Tone classes: pass-verified / pass-hint / fail-verified / fail-hint.
  const tone = (pass ? "pass" : "fail") + "-" + (reviewed ? "verified" : "hint");
  el.className = "self-check-box self-check-" + tone;
  // Layer line: ✓ passed | ✗ failed | ⏭ skipped
  const layerLine = (label, ok, info) => {
    const sym = ok === true ? "✓" : ok === false ? "✗" : "⏭";
    const cls = ok === true ? "ok" : ok === false ? "bad" : "skip";
    const tail = info ? ` <span class="muted">${escapeHtml(info)}</span>` : "";
    return `<li class="self-check-layer ${cls}">${sym} ${escapeHtml(label)}${tail}</li>`;
  };
  const fallbacks = (chk.layer2_fallback_buckets_found || []).join(", ");
  const missing = (chk.layer3_missing_anchors || []).join(", ");
  const l4inc = (chk.layer4_inconsistencies || []).length;
  const layers = [
    layerLine("算术一致性（各奖项加总=总赢钱）", chk.layer1_invariant_ok,
              chk.layer1_error ? "(" + chk.layer1_error + ")" : ""),
    layerLine("未归类奖项（应为 0）", chk.layer2_no_fallback_buckets_ok,
              fallbacks ? "发现: " + fallbacks : ""),
    layerLine("关键奖项命中（按机型清单）", chk.layer3_anchors_ok,
              missing ? "缺: " + missing : ""),
    layerLine("付费类型归类（与原始数据对比）",
              chk.layer4_applicable === false ? null : chk.layer4_per_st_consistency_ok,
              chk.layer4_applicable === false ? "本机型按设计跳过"
                                              : (l4inc ? l4inc + " 处不一致" : "")),
  ].join("");
  const msg = escapeHtml(chk.summary_message || "");
  const actions = Array.isArray(chk.suggested_actions) && chk.suggested_actions.length
    ? `<ul class="self-check-actions">${
        chk.suggested_actions.map(a => "<li>" + escapeHtml(a) + "</li>").join("")
      }</ul>`
    : "";
  const headTitle = reviewed
    ? (pass ? "报告自检通过" : "报告自检发现问题")
    : (pass ? "报告自检通过 · 该机型配置尚未核对，仅作参考"
            : "报告自检发现问题 · 该机型配置尚未核对，仅作参考");
  el.innerHTML = `
    <div class="self-check-head">
      <span class="self-check-icon">${pass ? "✓" : "⚠"}</span>
      <span class="self-check-title">${escapeHtml(headTitle)}</span>
    </div>
    <ul class="self-check-layers">${layers}</ul>
    ${msg ? `<div class="self-check-body">${msg}</div>` : ""}
    ${actions}
  `;
}

// Small helper. App.js already has fmt/byId/qs but no central escapeHtml;
// the older renderers either inline-escape or trust their input. Adding a
// scoped helper here keeps the new self-check renderer safe without
// disturbing existing code.
function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderStructureDriftPanel(summary) {
  // Surface summary.structure_drift (structure-drift gate, 2026-06-12).
  // Badge: green ok / yellow warn / red fail / grey unaudited.
  // Drill-down: undeclared STs + per-ST field drift.
  // Self-hides when the block is absent (old reports / unregistered machines).
  const el = byId("structureDriftPanel");
  if (!el) return;
  const drift = (summary || {}).structure_drift;
  if (!drift || typeof drift !== "object") {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  el.classList.remove("hidden");
  const lang = (typeof PURE !== "undefined" && PURE.currentLang) || state.lang || "zh";
  const t = (key) => PURE.fmt(lang, key);
  const fmtPct = (v) => (v == null ? "N/A" : `${(Number(v) * 100).toFixed(1)}%`);

  const status = drift.status || "unaudited";
  const toneMap = { ok: "sd-ok", warn: "sd-warn", fail: "sd-fail", unaudited: "sd-unaudited" };
  const tone = toneMap[status] || "sd-unaudited";
  el.className = `structure-drift-box structure-drift-${tone}`;

  const statusLabelKey = {
    ok: "sdStatusOk", warn: "sdStatusWarn", fail: "sdStatusFail", unaudited: "sdStatusUnaudited",
  }[status] || "sdStatusUnaudited";
  const icon = status === "ok" ? "✓" : status === "fail" ? "✗" : status === "warn" ? "⚠" : "·";

  // Undeclared STs section.
  const undecSts = Array.isArray(drift.undeclared_sts) ? drift.undeclared_sts : [];
  let undecStHtml = "";
  if (undecSts.length > 0) {
    const rows = undecSts.map(e =>
      `<tr><td>${escapeHtml(String(e.st))}</td><td>${escapeHtml(fInt(e.rounds))}</td>` +
      `<td>${escapeHtml(fmtPct(e.share))}</td></tr>`
    ).join("");
    undecStHtml = `
      <div class="sd-section">
        <div class="sd-section-title">${escapeHtml(t("sdUndeclaredSts"))}</div>
        <table class="sd-table">
          <thead><tr>
            <th>${escapeHtml(t("sdColSt"))}</th>
            <th>${escapeHtml(t("sdColRounds"))}</th>
            <th>${escapeHtml(t("sdColShare"))}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  // Declared-absent STs (informational).
  const declaredAbsent = Array.isArray(drift.declared_sts_absent) ? drift.declared_sts_absent : [];
  let absentHtml = "";
  if (declaredAbsent.length > 0) {
    absentHtml = `
      <div class="sd-section sd-info">
        <div class="sd-section-title">${escapeHtml(t("sdDeclaredAbsent"))}</div>
        <div class="sd-absent-list">${declaredAbsent.map(s => escapeHtml(String(s))).join(", ")}</div>
      </div>`;
  }

  // Per-ST field drift detail.
  const perSt = drift.per_st || {};
  const perStKeys = Object.keys(perSt).sort();
  let perStHtml = "";
  if (perStKeys.length > 0) {
    const stSections = perStKeys.map(st => {
      const stData = perSt[st] || {};
      // Keys MUST match the structure_drift plugin's emitted schema exactly:
      // signature_fields_missing (dict), new_fields (dict), observed_fields_absent (list).
      const missFields = stData.signature_fields_missing || {};
      const newFields = stData.new_fields || {};
      const absentFields = Array.isArray(stData.observed_fields_absent) ? stData.observed_fields_absent : [];
      const missKeys = Object.keys(missFields).sort();
      const newKeys = Object.keys(newFields).sort();
      let inner = "";
      if (missKeys.length > 0) {
        const rows = missKeys.map(f =>
          `<tr><td>${escapeHtml(f)}</td><td>${escapeHtml(fmtPct(missFields[f]))}</td></tr>`
        ).join("");
        inner += `<div class="sd-field-group">
          <div class="sd-field-group-title">${escapeHtml(t("sdMissingDeclaredFields"))}</div>
          <table class="sd-table"><thead><tr>
            <th>${escapeHtml(t("sdColField"))}</th>
            <th>${escapeHtml(t("sdColPresence"))}</th>
          </tr></thead><tbody>${rows}</tbody></table></div>`;
      }
      if (newKeys.length > 0) {
        const rows = newKeys.map(f =>
          `<tr><td>${escapeHtml(f)}</td><td>${escapeHtml(fmtPct(newFields[f]))}</td></tr>`
        ).join("");
        inner += `<div class="sd-field-group">
          <div class="sd-field-group-title">${escapeHtml(t("sdNewUndeclaredFields"))}</div>
          <table class="sd-table"><thead><tr>
            <th>${escapeHtml(t("sdColField"))}</th>
            <th>${escapeHtml(t("sdColPresence"))}</th>
          </tr></thead><tbody>${rows}</tbody></table></div>`;
      }
      if (absentFields.length > 0) {
        // Informational only (optional-field presence is config-dependent).
        inner += `<div class="sd-field-group sd-field-group-info">
          <div class="sd-field-group-title">${escapeHtml(t("sdObservedAbsent"))}</div>
          <div class="sd-absent-list">${absentFields.map(f => escapeHtml(f)).join(", ")}</div></div>`;
      }
      // unaudited_fields: ST has a signature but no observed_fields inventory →
      // the envelope (new-field) audit cannot run. Surface it honestly — never
      // silent (feedback_no_silent_swallow at the UI layer).
      if (stData.observed_fields_status === "unaudited_fields") {
        inner += `<div class="sd-field-group sd-field-group-info">
          <div class="sd-field-group-title">${escapeHtml(t("sdUnauditedFields"))}</div></div>`;
      }
      return inner ? `<div class="sd-st-block"><strong>ST ${escapeHtml(st)}</strong>${inner}</div>` : "";
    }).filter(Boolean).join("");
    if (stSections) {
      perStHtml = `
        <div class="sd-section">
          <div class="sd-section-title">${escapeHtml(t("sdPerStDrift"))}</div>
          ${stSections}
        </div>`;
    }
  } else if (status === "ok") {
    perStHtml = `<div class="sd-section sd-ok-note">${escapeHtml(t("sdNoDrift"))}</div>`;
  }

  // Reason (for unaudited).
  const reasonHtml = drift.reason
    ? `<div class="sd-reason">${escapeHtml(t("sdReason"))}: ${escapeHtml(drift.reason)}</div>`
    : "";

  // Footer: audited rounds + source.
  const footerHtml = `
    <div class="sd-footer">
      ${escapeHtml(t("sdAuditedRounds"))}: ${escapeHtml(fInt(drift.audited_rounds || 0))}
      &nbsp;·&nbsp; ${escapeHtml(drift.source || "")}
    </div>`;

  el.innerHTML = `
    <div class="sd-head">
      <span class="sd-icon">${icon}</span>
      <span class="sd-title">${escapeHtml(t(statusLabelKey))}</span>
    </div>
    ${reasonHtml}
    ${undecStHtml}
    ${absentHtml}
    ${perStHtml}
    ${footerHtml}
  `;
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
  // 2026-05-12: \u6539\u6210 compare-aware (\u8ddf paylineTable / bucketTable
  // \u4e00\u4e2a\u6a21\u5f0f)\u3002\u5bf9\u6bd4\u6a21\u5f0f\u4e0b\u5408\u5e76 A/B spin_type \u5217\u8868\u3001\u6309 spin_type \u914d\u5bf9\u3001
  // A-only / B-only \u52a0 presence tag,\u6bcf\u4e2a\u5355\u5143\u683c\u8d70 _cmpCell stack\u3002
  const cmpB = state.compareMode && state.compareMode.b ? state.compareMode.b : null;
  const rowsB = cmpB ? PURE.formatSpinTypeRows(cmpB) : [];
  const coverage = ((summary || {}).player_impact || {}).spin_type_coverage || 0;
  const coverageB = cmpB ? ((cmpB.player_impact || {}).spin_type_coverage || 0) : 0;
  const heading = document.querySelector(".spin-types h2");
  if (heading) {
    const covLabel = cmpB
      ? (coverage > 0 || coverageB > 0 ? ` (A:${coverage} / B:${coverageB})` : "")
      : (coverage > 0 ? ` (${coverage})` : "");
    heading.textContent = fmt("panelSpinType") + covLabel;
  }
  const bMap = new Map();
  for (const r of rowsB) bMap.set(String(r.spin_type), r);
  const aSet = new Set(rows.map((r) => String(r.spin_type)));
  const merged = [...rows];
  if (cmpB) {
    for (const r of rowsB) {
      if (!aSet.has(String(r.spin_type))) merged.push(r);
    }
  }
  if (!merged.length) {
    tbody.innerHTML = `<tr><td colspan="6">${fmt("spinTypeEmpty")}</td></tr>`;
    return;
  }
  const maxRtp = Math.max(
    ...merged.map((r) => r.rtp_contribution_pp),
    ...(cmpB ? rowsB.map((r) => r.rtp_contribution_pp) : []),
    0,
  );
  tbody.innerHTML = merged
    .map((r) => {
      const aIn = aSet.has(String(r.spin_type));
      const bRow = cmpB ? bMap.get(String(r.spin_type)) || null : null;

      const aShareRaw = aIn ? Number(r.share_pct || 0) : NaN;
      const bShareRaw = bRow ? Number(bRow.share_pct || 0) : NaN;
      const aHitRaw = aIn ? Number(r.hit_rate_pct || 0) : NaN;
      const bHitRaw = bRow ? Number(bRow.hit_rate_pct || 0) : NaN;
      const aRtpRaw = aIn && r.rtp_pct != null ? Number(r.rtp_pct) : NaN;
      const bRtpRaw = bRow && bRow.rtp_pct != null ? Number(bRow.rtp_pct) : NaN;
      const aContribRaw = aIn ? Number(r.rtp_contribution_pp || 0) : NaN;
      const bContribRaw = bRow ? Number(bRow.rtp_contribution_pp || 0) : NaN;

      const aShareFmt = aIn ? r.share_pct.toFixed(1) + "%" : "\u2014";
      const bShareFmt = bRow ? bRow.share_pct.toFixed(1) + "%" : "\u2014";
      const aHitFmt = aIn ? r.hit_rate_pct.toFixed(2) + "%" : "\u2014";
      const bHitFmt = bRow ? bRow.hit_rate_pct.toFixed(2) + "%" : "\u2014";
      const aRtpFmt = aIn ? (r.rtp_pct == null ? "N/A" : r.rtp_pct.toFixed(2) + "%") : "\u2014";
      const bRtpFmt = bRow ? (bRow.rtp_pct == null ? "N/A" : bRow.rtp_pct.toFixed(2) + "%") : "\u2014";
      const aContribFmt = aIn ? r.rtp_contribution_pp.toFixed(2) : "\u2014";
      const bContribFmt = bRow ? bRow.rtp_contribution_pp.toFixed(2) : "\u2014";

      const aBar = aIn && maxRtp > 0
        ? Math.min(100, (r.rtp_contribution_pp / maxRtp) * 100)
        : 0;
      const bBar = bRow && maxRtp > 0
        ? Math.min(100, (bRow.rtp_contribution_pp / maxRtp) * 100)
        : 0;

      const primary = aIn ? r : bRow;
      const behavior = primary && primary.behavior_name
        ? fmt("spinTypeBehavior_" + primary.behavior_name)
        : "\u2014";
      // ST x FeatureWin cross: tag the SpinType with the "\u73a9\u6cd5" (FeatureWin
      // feature) it maps to, e.g. "ST=15  TopDollar". trigger_only events
      // (fires>0/win==0, e.g. the ST=14 selector) get a "\u89e6\u53d1" marker so the
      // player sees they cost a pick but pay nothing on their own.
      let featureTag = "";
      if (primary && primary.feature_name) {
        const fname = escapeHtml(primary.feature_name);
        const trig = primary.feature_trigger_only
          ? ` \u00b7 ${escapeHtml(fmt("spinTypeFeatureTriggerOnly"))}`
          : "";
        featureTag =
          ` <span class="st-feature-tag" title="${escapeHtml(fmt("spinTypeFeatureTitle"))}">` +
          `${fname}${trig}</span>`;
      }
      const rareFlag = (aIn && r.rare) || (bRow && bRow.rare);
      const rareClass = rareFlag ? ' class="rare-row"' : "";

      let presence = "";
      if (cmpB) {
        if (aIn && !bRow) presence = ` <span class="pid-presence-tag pid-presence-a">A only</span>`;
        else if (!aIn && bRow) presence = ` <span class="pid-presence-tag pid-presence-b">B only</span>`;
      }
      const stName = aIn ? r.spin_type : (bRow ? bRow.spin_type : "?");

      const barCell = cmpB
        ? `<td class="cmp-text-bar-cell">${_cmpCell(true, aContribFmt, bContribFmt, aContribRaw, bContribRaw, "pp", 2, { aBarPct: aBar, bBarPct: bBar })}</td>`
        : `<td class="bar-cell" style="--bar:${aBar.toFixed(1)}%">${aContribFmt}</td>`;

      return (
        `<tr${rareClass}>` +
        `<td>${stName}${rareFlag ? " \u26a0" : ""}${featureTag}${presence}</td>` +
        `<td>${behavior}</td>` +
        `<td>${_cmpCell(!!cmpB, aShareFmt, bShareFmt, aShareRaw, bShareRaw, "pp")}</td>` +
        `<td>${_cmpCell(!!cmpB, aHitFmt, bHitFmt, aHitRaw, bHitRaw, "pp", 2)}</td>` +
        `<td>${_cmpCell(!!cmpB, aRtpFmt, bRtpFmt, aRtpRaw, bRtpRaw, "pp", 2)}</td>` +
        barCell +
        `</tr>`
      );
    })
    .join("");
}

// ── Per-SpinType analysis — data-driven DIMENSION framework ──────────────────
// The console organizes everything STRICTLY BY SpinType. Each ST section is
// assembled from a declarative list of DIMENSION renderers (SPINTYPE_DIMENSIONS).
// Each dimension is a pure fn (stCtx) -> html|"" that SELF-APPLIES iff its data
// exists for that ST — there is NO machine/ST hardcoding. Adding a new dimension
// (or supporting a new feature on a SpinType for another machine) = add/extend a
// dimension fn keyed on the DATA SHAPE, not on "if ST14" / "if M15".
//
// stCtx = { row, label, outcome, payRows, summary, bet }
//   row     — spin_type_breakdown row (overview + feature cross)
//   label   — "ST{n}_{behavior}" (the payouts_by_spin_type / spin_type_outcomes key)
//   outcome — spin_type_outcomes[label] (has_payouts, max_mult, ...)
//   payRows — payouts_by_spin_type[label] (per-payid rows)
//   summary — the full summary (for cross-feature blocks like topdollar_choice)
//   bet     — sampling.bet (multiplier denominator)

// Canonical multiplier buckets — same edges as the analyzer's global
// RETURN_BUCKET_ORDER (aggregator.py) so the per-SpinType win distribution uses
// the same fine granularity as the global multiplier-bucket table. [lo, hi).
const _CANON_BUCKETS = [
  ["gt0_lt1", 0, 1], ["ge1_lt5", 1, 5], ["ge5_lt10", 5, 10], ["ge10_lt20", 10, 20],
  ["ge20_lt50", 20, 50], ["ge50_lt100", 50, 100], ["ge100_lt200", 100, 200],
  ["ge200_lt500", 200, 500], ["ge500_lt1000", 500, 1000], ["ge1000_lt5000", 1000, 5000],
  ["ge5000", 5000, Infinity],
];

// TopDollar behavior split across its two SpinTypes (the user's event model:
// ST14 = the CHOICE/pick, ST15 = the SETTLEMENT). Built from topdollar_choice via
// the shared _buildStatsSectionsHtml. The ST→block mapping is DATA-DRIVEN below
// (trigger_only ST gets the pick block; the ST whose feature == the settlement
// feature_name gets the settlement block) — not hardcoded to ST14/ST15.
// ST14 (the CHOICE event) — all the per-draw distributions, as probability:
// trigger/stop/forced/bad-gamble RATES + pick-count dist + denomination-chosen
// dist + denomination-combination dist. No credit amounts (user: 倍率/概率/分布).
const _TD_PICK_SECTIONS = [
  { type: "kv", rows: [
    { labelKey: "tdTotalSessions",  path: "total_sessions",     fmt: "int" },
    { labelKey: "tdTriggerRate",    path: "trigger_rate",       fmt: "pct" },
    { labelKey: "tdStoppedEarly",   path: "stopped_early_rate", fmt: "pct" },
    { labelKey: "tdForced4th",      path: "forced_4th_rate",    fmt: "pct" },
    { labelKey: "tdBadGamble",      path: "bad_gamble_rate",    fmt: "pct" },
  ] },
  // 选中次数的分布 (how many picks per session).
  { type: "tally", titleKey: "tdPicksPerSession", path: "picks_per_session",
    keyColKey: "tdColPicks", countColKey: "tdColSessions" },
  // 面额被选的分布 (which denominations get chosen).
  { type: "tally", titleKey: "tdDollarTiers", path: "dollar_tier_counts",
    keyColKey: "tdColTier", countColKey: "tdColCount" },
  // 一次抽取的面额组合分布 (the multi-denomination combo per draw).
  { type: "tally", titleKey: "tdChosenCombos", path: "chosen_combo_counts",
    keyColKey: "tdColCombo", countColKey: "tdColCount" },
];
// ST15 (the SETTLEMENT event) — the WHOLE mini-game's TOTAL MULTIPLIER
// distribution (settled_win/bet, bucketed) + multiplier median/max. NO credit
// amounts (user: 我对结算的金钱额度没有分析需求，我只对倍率/概率/分布).
const _TD_SETTLE_SECTIONS = [
  { type: "kv", rows: [
    { labelKey: "tdTotalMultMedian", path: "total_mult_median", fmt: "mult" },
    { labelKey: "tdTotalMultMax",    path: "total_mult_max",    fmt: "mult" },
  ] },
  { type: "mult_buckets", titleKey: "tdTotalMultDist", path: "total_mult_buckets" },
];

// Dimension: overview KV (share / hit / self-RTP / RTP contribution / feature).
function _stDimOverview(stCtx) {
  const r = stCtx.row;
  const kv = [
    [fmt("stoShare"), (Number(r.share_pct) || 0).toFixed(1) + "%"],
    [fmt("stoHit"), PURE.fRate(r.hit_rate || 0)],
    [fmt("stoSelfRtp"), r.rtp_pct == null ? "N/A" : Number(r.rtp_pct).toFixed(2) + "%"],
    [fmt("stoRtpPp"), (Number(r.rtp_contribution_pp) || 0).toFixed(2) + "pp"],
  ];
  if (r.feature_name) {
    const feat = escapeHtml(r.feature_name)
      + (r.feature_trigger_only
        ? " (" + escapeHtml(fmt("spinTypeFeatureTriggerOnly")) + ")"
        : (r.feature_rtp_pp != null ? " " + Number(r.feature_rtp_pp).toFixed(2) + "pp" : ""));
    kv.push([fmt("stoFeature"), feat]);
  }
  const cells = kv
    .map(([k, v]) => `<div class="mech-stat"><span class="mech-label">${k}</span><span class="mech-value">${v}</span></div>`)
    .join("");
  return `<div class="mech-section"><div class="mech-grid">${cells}</div></div>`;
}

// Dimension: win distribution — per-SpinType RTP bucket distribution.
// PREFERRED (Phase C): ROUND-LEVEL — each spin's total win/bet binned into the
//   canonical buckets (spin_type_rtp_buckets, same as the global multiplier table).
//   占比 = fraction of this ST's PAID spins in the bucket (so named buckets sum to
//   the hit rate; the remainder are dead spins). This is "基于 spin 的 RTP 分桶".
// FALLBACK (Phase A): PAYLINE-level re-bin of payid avg_win/bet — used only for
//   old reports generated before spin_type_rtp_buckets existed.
function _stDimWinDistribution(stCtx) {
  const { summary, label, payRows, bet } = stCtx;

  // ── Round-level (preferred) ──
  const roundBuckets =
    (((summary.player_impact || {}).spin_type_rtp_buckets) || {})[label];
  if (Array.isArray(roundBuckets) && roundBuckets.length) {
    const shown = roundBuckets.filter((b) => (Number(b.spin_count) || 0) > 0);
    if (!shown.length) return "";
    const maxShare = Math.max(...shown.map((b) => Number(b.spin_rate) || 0), 0.0001);
    const rows = shown
      .map((b) => {
        const share = Number(b.spin_rate) || 0;
        const barPct = (share / maxShare) * 100;
        return (
          `<tr><td>${PURE.prettyBucketLabel(b.bucket)}×</td>` +
          `<td>${PURE.fInt(Number(b.spin_count) || 0)}</td>` +
          `<td class="bar-cell" style="--bar:${barPct.toFixed(1)}%">${(share * 100).toFixed(2)}%</td>` +
          `<td>${(Number(b.rtp_contribution_pp) || 0).toFixed(2)}</td></tr>`
        );
      })
      .join("");
    return (
      `<p class="drilldown-hint">${fmt("stoBandsTitle")} · ${fmt("stoBandsRoundNote")}</p>` +
      `<table class="drilldown-table"><thead><tr>` +
      `<th>${fmt("stoColBand")}</th><th>${fmt("stoColHits")}</th>` +
      `<th>${fmt("stoColShare")}</th><th>${fmt("stoColRtp")}</th>` +
      `</tr></thead><tbody>${rows}</tbody></table>`
    );
  }

  // ── Payline-level fallback (old reports) ──
  if (!(bet > 0)) return "";
  const real = payRows.filter((pr) => !String(pr.payout_id || "").startsWith("_"));
  if (!real.length) return "";
  const acc = _CANON_BUCKETS.map(([key, lo, hi]) => ({ key, lo, hi, hits: 0, rtp: 0 }));
  let totalHits = 0;
  for (const pr of real) {
    const hits = Number(pr.hit_count) || 0;
    const mult = (Number(pr.avg_win_when_hit) || 0) / bet;
    const rtp = Number(pr.rtp_contribution_pp ?? pr.rtp_pp ?? 0);
    let bi = acc.findIndex((b) => mult >= b.lo && mult < b.hi);
    if (bi < 0) bi = acc.length - 1;
    acc[bi].hits += hits;
    acc[bi].rtp += rtp;
    totalHits += hits;
  }
  const shown = acc.filter((b) => b.hits > 0);
  if (!shown.length || totalHits <= 0) return "";
  const maxShare = Math.max(...shown.map((b) => b.hits / totalHits), 0.0001);
  const rows = shown
    .map((b) => {
      const share = b.hits / totalHits;
      const barPct = (share / maxShare) * 100;
      return (
        `<tr><td>${PURE.prettyBucketLabel(b.key)}×</td>` +
        `<td>${PURE.fInt(b.hits)}</td>` +
        `<td class="bar-cell" style="--bar:${barPct.toFixed(1)}%">${(share * 100).toFixed(1)}%</td>` +
        `<td>${b.rtp.toFixed(2)}</td></tr>`
      );
    })
    .join("");
  return (
    `<p class="drilldown-hint">${fmt("stoBandsTitle")} · ${fmt("stoBandsPaylineNote")}</p>` +
    `<table class="drilldown-table"><thead><tr>` +
    `<th>${fmt("stoColBand")}</th><th>${fmt("stoColHits")}</th>` +
    `<th>${fmt("stoColShare")}</th><th>${fmt("stoColRtp")}</th>` +
    `</tr></thead><tbody>${rows}</tbody></table>`
  );
}

// Dimension: payid breakdown (symbol combo + covered cols) via the shared
// _renderPayoutRowsHtml — same renderer the Pay ID overview uses.
function _stDimPayid(stCtx) {
  const { payRows, bet, label } = stCtx;
  if (!payRows.length) return "";
  const m = /^ST\d+_(paid|free|mixed)$/.exec(label);
  const category = m ? (m[1] === "free" ? "bonus" : m[1]) : null;
  const ranked = [...payRows]
    .map((pr) => (category && pr.spin_type_category == null
      ? { ...pr, spin_type_category: category } : pr))
    .sort((a, b) => Number(b.rtp_contribution_pp ?? b.rtp_pp ?? 0) - Number(a.rtp_contribution_pp ?? a.rtp_pp ?? 0))
    .slice(0, 20);
  const tableInner = _renderPayoutRowsHtml(ranked, {
    shapeByPayId: null, cmpBMap: null, cmpB: false, bet, betB: bet,
    includeShape: false, includeNotes: false, includeSubRows: false,
  });
  return `<p class="drilldown-hint">${fmt("stoPayidTitle")}</p>` +
    `<table class="drilldown-table">${tableInner}</table>`;
}

// Dimension: selector/choice behavior — attaches to the CHOICE event (the
// trigger_only ST). Data-driven: present iff a topdollar_choice-style section
// exists. (Phase B4 generalizes the data side beyond topdollar_choice.)
function _stDimSelectorChoice(stCtx) {
  const td = stCtx.summary.topdollar_choice;
  if (!td || !td.applicable) return "";
  if (!stCtx.row.feature_trigger_only) return "";
  return `<p class="drilldown-hint">${fmt("stoBehaviorTitle")}</p>` +
    _buildStatsSectionsHtml(td, _TD_PICK_SECTIONS);
}

// Dimension: settlement outcome — attaches to the SETTLEMENT event (the ST whose
// feature matches the settlement feature_name and is NOT trigger-only). This is
// how ST=15 gets its OWN settlement analysis (not folded into ST=14).
function _stDimSettlement(stCtx) {
  const td = stCtx.summary.topdollar_choice;
  if (!td || !td.applicable) return "";
  const r = stCtx.row;
  if (r.feature_trigger_only) return "";
  if (!r.feature_name || r.feature_name !== td.feature_name) return "";
  return `<p class="drilldown-hint">${fmt("stoSettlementTitle")}</p>` +
    _buildStatsSectionsHtml(td, _TD_SETTLE_SECTIONS);
}

// Dimension: respin dynamics — attaches to the RESPIN event (the ST whose
// spin_type matches respin_dynamics.respin_spin_type). Data-driven: returns ""
// for every other ST so the analysis lives only inside the matching ST section.
// Reuses the same mech-section/mech-grid KPI blocks + drilldown-table/bar-cell
// markup that the former standalone renderRespinDynamics panel built.
function _stDimRespin(stCtx) {
  const rd = ((stCtx.summary || {}).player_impact || {}).respin_dynamics;
  if (!rd || !rd.applicable) return "";
  if (Number(rd.respin_spin_type) !== Number(stCtx.row.spin_type)) return "";

  // Helper: format a probability value as a percentage string or "—".
  const _pct = (v, d = 2) =>
    (v == null || !Number.isFinite(Number(v))) ? "—" : `${(Number(v) * 100).toFixed(d)}%`;
  // Helper: format a ratio/multiplier value or "—".
  const _ratio = (v, d = 2) =>
    (v == null || !Number.isFinite(Number(v))) ? "—" : `${Number(v).toFixed(d)}×`;
  // Helper: render a band distribution table (respin or base).
  const _bandTable = (dist, titleKey) => {
    if (!dist || !Array.isArray(dist.bands) || !dist.bands.length) return "";
    const bands = dist.bands.filter((b) => b.prob != null && Number(b.prob) > 0);
    if (!bands.length) return "";
    const maxProb = Math.max(...bands.map((b) => Number(b.prob) || 0), 0.0001);
    const rows = bands.map((b) => {
      const prob = Number(b.prob) || 0;
      const barPct = (prob / maxProb) * 100;
      const winShare = b.win_share != null ? `${(Number(b.win_share) * 100).toFixed(1)}%` : "—";
      return (
        `<tr>` +
        `<td>${PURE.prettyBucketLabel ? PURE.prettyBucketLabel(b.band) : b.band}×</td>` +
        `<td>${fInt(b.spin_count)}</td>` +
        `<td class="bar-cell" style="--bar:${barPct.toFixed(1)}%">${_pct(prob, 2)}</td>` +
        `<td>${winShare}</td>` +
        `</tr>`
      );
    }).join("");
    const tail = dist.tail_ge20x_win_share != null
      ? `<p class="drilldown-hint">${fmt("rdTailGe20")}: ${_pct(dist.tail_ge20x_win_share, 1)}</p>`
      : "";
    return (
      `<p class="drilldown-hint"><strong>${fmt(titleKey)}</strong> · ${fInt(dist.total_spins)} 次 · ${fInt(dist.win_rounds)} 次赢钱</p>` +
      `<table class="drilldown-table"><thead><tr>` +
      `<th>${fmt("rdColBand")}</th><th>${fmt("stoColHits")}</th>` +
      `<th>${fmt("rdColProb")}</th><th>${fmt("rdColWinShare")}</th>` +
      `</tr></thead><tbody>${rows}</tbody></table>` +
      tail
    );
  };

  // ── M1 Grant-rate KPI block ──
  const gr = rd.grant_rate || {};
  const grantHtml = `<div class="mech-section">
    <h3>${fmt("rdGrantRate")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("rdGrantOpeners")}</span><span class="mech-value">${fInt(gr.openers)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdGrantRatePerWin")}</span><span class="mech-value">${_pct(gr.per_winning_paid_spin, 2)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdGrantRatePerSpin")}</span><span class="mech-value">${_pct(gr.per_paid_spin, 3)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdGrantRateOnePerN")}</span><span class="mech-value">${gr.one_per_n_paid_spins != null ? Number(gr.one_per_n_paid_spins).toFixed(1) : "—"}</span></div>
    </div>
  </div>`;

  // ── M2 Hit-rate uplift KPI block ──
  const hru = rd.hit_rate_uplift || {};
  const upliftHtml = `<div class="mech-section">
    <h3>${fmt("rdHitRateUplift")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("rdRespinHitRate")}</span><span class="mech-value">${_pct(hru.respin_hit_rate, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdBaseHitRate")}</span><span class="mech-value">${_pct(hru.base_hit_rate, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdUpliftRatio")}</span><span class="mech-value">${_ratio(hru.uplift_ratio, 2)}</span></div>
    </div>
  </div>`;

  // ── M2 Multiplier distributions (respin + base side by side) ──
  const multHtml =
    _bandTable(rd.respin_multiplier_distribution, "rdRespinMultDist") +
    _bandTable(rd.base_multiplier_distribution, "rdBaseMultDist");

  // ── M3 PayID mix (respin vs base) ──
  const mix = rd.payid_mix || {};
  const _payidRows = (shareMap) => {
    const entries = Object.entries(shareMap || {});
    if (!entries.length) return "<tr><td colspan='3'>—</td></tr>";
    return entries
      .sort((a, b) => Number(b[1].hit_share || 0) - Number(a[1].hit_share || 0))
      .map(([pid, v]) =>
        `<tr><td>${pid}</td>` +
        `<td>${fInt(v.hit_count)}</td>` +
        `<td>${_pct(v.hit_share, 1)}</td>` +
        `<td>${_pct(v.win_share, 1)}</td></tr>`
      ).join("");
  };
  const payidHtml = (mix.respin_payid_share || mix.base_payid_share)
    ? (`<p class="drilldown-hint"><strong>${fmt("rdPayidMix")}</strong></p>` +
       `<div style="display:flex;gap:1rem;flex-wrap:wrap;">` +
       `<div><p class="drilldown-hint">Respin (ST${rd.respin_spin_type})</p>` +
       `<table class="drilldown-table"><thead><tr><th>${fmt("rdColPayid")}</th><th>${fmt("stoColHits")}</th><th>${fmt("rdColHitShare")}</th><th>${fmt("rdColWinShare")}</th></tr></thead><tbody>${_payidRows(mix.respin_payid_share)}</tbody></table></div>` +
       `<div><p class="drilldown-hint">Base (ST${rd.base_spin_type})</p>` +
       `<table class="drilldown-table"><thead><tr><th>${fmt("rdColPayid")}</th><th>${fmt("stoColHits")}</th><th>${fmt("rdColHitShare")}</th><th>${fmt("rdColWinShare")}</th></tr></thead><tbody>${_payidRows(mix.base_payid_share)}</tbody></table></div>` +
       `</div>` +
       (mix.note ? `<p class="drilldown-hint">${fmt("rdPayidNote")}: ${_escHtml(mix.note)}</p>` : ""))
    : "";

  // ── M4 Continuity ──
  const cont = rd.continuity || {};
  const exitRows = Object.entries(cont.exit_breakdown || {})
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .map(([st, cnt]) => `<tr><td>ST${st}</td><td>${fInt(cnt)}</td></tr>`)
    .join("");
  const parserBlindItems = Array.isArray(cont.parser_blind) ? cont.parser_blind : [];
  const parserBlindHtml = parserBlindItems.length
    ? (`<p class="drilldown-hint"><em>${fmt("rdParserBlind")} (待 per-ST 提取层):</em></p>` +
       `<ul class="drilldown-hint" style="margin:0 0 0 1em;padding:0;">` +
       parserBlindItems.map((s) => `<li>${_escHtml(s)}</li>`).join("") +
       `</ul>`)
    : "";
  const continuityHtml = `<div class="mech-section">
    <h3>${fmt("rdContinuity")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("rdContinuationProb")}</span><span class="mech-value">${_pct(cont.continuation_prob, 2)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdRespinToRespin")}</span><span class="mech-value">${fInt(cont.respin_to_respin_transitions)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdExitTotal")}</span><span class="mech-value">${fInt(cont.respin_exit_transitions)}</span></div>
    </div>
    ${exitRows ? (`<p class="drilldown-hint">${fmt("rdExitBreakdown")}</p><table class="drilldown-table"><thead><tr><th>ST</th><th>${fmt("tdColCount")}</th></tr></thead><tbody>${exitRows}</tbody></table>`) : ""}
    ${parserBlindHtml}
  </div>`;

  // ── M5 RTP concentration KPI block ──
  const rtpC = rd.rtp_concentration || {};
  const rtpHtml = `<div class="mech-section">
    <h3>${fmt("rdRtpConcentration")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("rdRtpContrib")}</span><span class="mech-value">${rtpC.respin_rtp_contribution_pp != null ? Number(rtpC.respin_rtp_contribution_pp).toFixed(2) + "pp" : "—"}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdShareOfWin")}</span><span class="mech-value">${_pct(rtpC.share_of_all_win, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdFatTailShare")}</span><span class="mech-value">${_pct(rtpC.fat_tail_ge20x_win_share, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdLossRate")}</span><span class="mech-value">${_pct(rtpC.loss_rate, 1)}</span></div>
    </div>
    ${rtpC.note ? `<p class="drilldown-hint">${_escHtml(rtpC.note)}</p>` : ""}
  </div>`;

  return `<p class="drilldown-hint"><strong>${fmt("panelRespinDynamics")}</strong></p>` +
    grantHtml + upliftHtml + multHtml + payidHtml + continuityHtml + rtpHtml;
}

// Dimension: minigame dynamics — attaches to the MINIGAME event (the ST whose
// spin_type matches minigame_dynamics.minigame_spin_type). Returns "" for all
// other STs so the analysis renders only inside the matching ST section.
// Reuses the same mech-section/mech-grid KPI blocks + drilldown-table/bar-cell
// markup that the former standalone renderMinigameDynamics panel built.
function _stDimMinigame(stCtx) {
  const mg = ((stCtx.summary || {}).player_impact || {}).minigame_dynamics;
  if (!mg || !mg.applicable) return "";
  if (Number(mg.minigame_spin_type) !== Number(stCtx.row.spin_type)) return "";

  // Helper: format a probability value as a percentage string or "—".
  const _pct = (v, d = 2) =>
    (v == null || !Number.isFinite(Number(v))) ? "—" : `${(Number(v) * 100).toFixed(d)}%`;

  // ── G1 Multiplier distribution ──
  const dist = mg.multiplier_distribution || {};
  const bands = Array.isArray(dist.bands) ? dist.bands.filter((b) => b.prob != null && Number(b.prob) > 0) : [];
  const maxProb = Math.max(...bands.map((b) => Number(b.prob) || 0), 0.0001);
  const bandRows = bands.map((b) => {
    const prob = Number(b.prob) || 0;
    const barPct = (prob / maxProb) * 100;
    const winShare = b.win_share != null ? `${(Number(b.win_share) * 100).toFixed(1)}%` : "—";
    return (
      `<tr>` +
      `<td>${PURE.prettyBucketLabel ? PURE.prettyBucketLabel(b.band) : b.band}×</td>` +
      `<td>${fInt(b.spin_count)}</td>` +
      `<td class="bar-cell" style="--bar:${barPct.toFixed(1)}%">${_pct(prob, 2)}</td>` +
      `<td>${winShare}</td>` +
      `</tr>`
    );
  }).join("");
  const multHtml = bands.length
    ? (`<p class="drilldown-hint"><strong>${fmt("mgMultDist")}</strong> · ${fInt(dist.total_events)} 次 · ${fmt("mgModalBand")}: ${dist.modal_band || "—"} · ${fmt("mgDominantShare")}: ${_pct(dist.dominant_band_share, 1)}</p>` +
       `<table class="drilldown-table"><thead><tr>` +
       `<th>${fmt("mgColBand")}</th><th>${fmt("mgColCount")}</th>` +
       `<th>${fmt("mgColProb")}</th><th>${fmt("mgColWinShare")}</th>` +
       `</tr></thead><tbody>${bandRows}</tbody></table>` +
       (dist.source ? `<p class="drilldown-hint">${_escHtml(dist.source)}</p>` : ""))
    : "";

  // ── G2 Trigger frequency KPI block ──
  const tf = mg.trigger_frequency || {};
  const freqHtml = `<div class="mech-section">
    <h3>${fmt("mgTriggerFreq")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("mgEvents")}</span><span class="mech-value">${fInt(tf.minigame_events)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("mgPerPaidSpin")}</span><span class="mech-value">${_pct(tf.per_paid_spin, 3)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("mgOnePerN")}</span><span class="mech-value">${tf.one_per_n_paid_spins != null ? Number(tf.one_per_n_paid_spins).toFixed(1) : "—"}</span></div>
    </div>
  </div>`;

  // ── G3 Trigger context ──
  const tc = mg.trigger_context || {};
  const tcParserBlindItems = Array.isArray(tc.parser_blind) ? tc.parser_blind : [];
  const tcParserBlindHtml = tcParserBlindItems.length
    ? (`<p class="drilldown-hint"><em>${fmt("mgParserBlind")} (待 per-ST 提取层):</em></p>` +
       `<ul class="drilldown-hint" style="margin:0 0 0 1em;padding:0;">` +
       tcParserBlindItems.map((s) => `<li>${_escHtml(s)}</li>`).join("") +
       `</ul>`)
    : "";
  const contextHtml = `<div class="mech-section">
    <h3>${fmt("mgTriggerContext")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("mgFromBase")}</span><span class="mech-value">${fInt(tc.opener_from_base_spin)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("mgShareFromBase")}</span><span class="mech-value">${_pct(tc.share_from_base_spin, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("mgFromRespin")}</span><span class="mech-value">${fInt(tc.opener_from_respin_burst)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("mgShareFromRespin")}</span><span class="mech-value">${_pct(tc.share_from_respin_burst, 1)}</span></div>
    </div>
    ${tcParserBlindHtml}
  </div>`;

  // ── G4/G5 Node path analysis (parser-blind) ──
  const npa = mg.node_path_analysis || {};
  const npaItems = Array.isArray(npa.parser_blind) ? npa.parser_blind : [];
  const nodeHtml = `<div class="mech-section">
    <h3>${fmt("mgNodePath")}</h3>
    <p class="drilldown-hint"><em>${fmt("mgNodePathNA")} (${fmt("mgParserBlind")}):</em></p>
    ${npaItems.length
      ? (`<ul class="drilldown-hint" style="margin:0 0 0 1em;padding:0;">` +
         npaItems.map((s) => `<li>${_escHtml(s)}</li>`).join("") +
         `</ul>`)
      : ""}
  </div>`;

  // ── G6 RTP concentration KPI block ──
  const rtpC = mg.rtp_concentration || {};
  const rtpHtml = `<div class="mech-section">
    <h3>${fmt("mgRtpConcentration")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("mgRtpContrib")}</span><span class="mech-value">${rtpC.minigame_rtp_contribution_pp != null ? Number(rtpC.minigame_rtp_contribution_pp).toFixed(2) + "pp" : "—"}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("mgShareOfWin")}</span><span class="mech-value">${_pct(rtpC.share_of_all_win, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("mgEventRate")}</span><span class="mech-value">${_pct(rtpC.event_rate, 3)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("mgHitRate")}</span><span class="mech-value">${_pct(rtpC.hit_rate, 1)}</span></div>
    </div>
    ${rtpC.note ? `<p class="drilldown-hint">${_escHtml(rtpC.note)}</p>` : ""}
  </div>`;

  return `<p class="drilldown-hint"><strong>${fmt("panelMinigameDynamics")}</strong></p>` +
    multHtml + freqHtml + contextHtml + nodeHtml + rtpHtml;
}

// Dimension: wheel dynamics — attaches to the WHEEL settlement event (the ST
// whose spin_type matches wheel_dynamics.wheel_spin_type, e.g. M279 ST2's
// collect wheel). Returns "" for all other STs. Reuses the same
// mech-section/mech-grid KPI blocks + drilldown-table/bar-cell markup as the
// sibling respin/minigame dimensions.
function _stDimWheel(stCtx) {
  const wd = ((stCtx.summary || {}).player_impact || {}).wheel_dynamics;
  if (!wd || !wd.applicable) return "";
  if (Number(wd.wheel_spin_type) !== Number(stCtx.row.spin_type)) return "";

  // Helper: format a probability value as a percentage string or "—".
  const _pct = (v, d = 2) =>
    (v == null || !Number.isFinite(Number(v))) ? "—" : `${(Number(v) * 100).toFixed(d)}%`;

  // ── W1 Guaranteed payout / cadence KPI block ──
  const gp = wd.guaranteed_payout || {};
  const gpHtml = `<div class="mech-section">
    <h3>${fmt("wdGuaranteed")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("wdEvents")}</span><span class="mech-value">${fInt(gp.events)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("wdHitRate")}</span><span class="mech-value">${_pct(gp.hit_rate, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("mgOnePerN")}</span><span class="mech-value">${gp.one_per_n_paid_spins != null ? Number(gp.one_per_n_paid_spins).toFixed(1) : "—"}</span></div>
    </div>
    ${gp.cadence_note ? `<p class="drilldown-hint">${_escHtml(gp.cadence_note)}</p>` : ""}
  </div>`;

  // ── W2 Discrete prize distribution — DISTINCT prizes (un-merged, data-derived
  // from the exact cell map; no RETURN_BUCKET band merge, no hardcoded ladder). ──
  const dist = wd.prize_distribution || {};
  const prizes = (dist.available && Array.isArray(dist.prizes))
    ? dist.prizes.filter((p) => p.prob != null && Number(p.prob) > 0)
    : [];
  const maxProb = Math.max(...prizes.map((p) => Number(p.prob) || 0), 0.0001);
  const prizeRows = prizes.map((p) => {
    const prob = Number(p.prob) || 0;
    const barPct = (prob / maxProb) * 100;
    const winShare = p.win_share != null ? `${(Number(p.win_share) * 100).toFixed(1)}%` : "—";
    return (
      `<tr>` +
      `<td>${p.prize_multiplier != null ? `${p.prize_multiplier}×` : "—"}</td>` +
      `<td>${fInt(p.hit_count)}</td>` +
      `<td class="bar-cell" style="--bar:${barPct.toFixed(1)}%">${_pct(prob, 2)}</td>` +
      `<td>${winShare}</td>` +
      `</tr>`
    );
  }).join("");
  const multHtml = prizes.length
    ? (`<p class="drilldown-hint"><strong>${fmt("wdPrizeDist")}</strong> · ${fInt(dist.total_events)} 次 · ${fmt("mgModalBand")}: ${dist.modal_prize_multiplier != null ? `${dist.modal_prize_multiplier}×` : "—"} · ${fmt("mgDominantShare")}: ${_pct(dist.dominant_prize_share, 1)}</p>` +
       `<table class="drilldown-table"><thead><tr>` +
       `<th>${fmt("wdColPrize")}</th><th>${fmt("wdColHitCount")}</th>` +
       `<th>${fmt("rdColProb")}</th><th>${fmt("rdColWinShare")}</th>` +
       `</tr></thead><tbody>${prizeRows}</tbody></table>`)
    : "";

  // ── W3 EXACT 12-cell wheel map (CellIndex → prize, data-derived). Jackpot
  // cell(s) highlighted; unobserved cells marked; nondeterministic cells alarmed. ──
  const cm = wd.cell_map || {};
  const jackpotCells = Array.isArray(cm.jackpot_cells) ? cm.jackpot_cells : [];
  const jackpotSet = new Set(jackpotCells.map(Number));
  const dJackpot = cm.jackpot_prize_multiplier;
  const cellList = (cm.available && Array.isArray(cm.cells)) ? cm.cells : [];
  const cellRows = cellList.map((c) => {
    const isJackpot = jackpotSet.has(Number(c.cell));
    const isNondet = c.nondeterministic === true;
    let prizeCell;
    if (!c.observed) {
      prizeCell = `<em>${fmt("wdUnobserved")}</em>`;
    } else if (c.prize_multiplier == null) {
      prizeCell = isNondet ? `<em>⚠ ${fmt("wdMergedTag")}</em>` : "—";
    } else if (isJackpot) {
      // Jackpot cell highlighted: star + bold (no new CSS dependency).
      prizeCell = `<strong>★ ${c.prize_multiplier}×</strong>`;
    } else {
      prizeCell = `${c.prize_multiplier}×`;
    }
    return (
      `<tr>` +
      `<td>#${c.cell}</td>` +
      `<td>${prizeCell}</td>` +
      `<td>${fInt(c.hit_count)}</td>` +
      `<td>${c.hit_prob != null ? _pct(c.hit_prob, 2) : "—"}</td>` +
      `</tr>`
    );
  }).join("");
  const cellGridHtml = cellList.length
    ? (`<p class="drilldown-hint"><strong>${fmt("wdCellGrid")}</strong></p>` +
       `<table class="drilldown-table"><thead><tr>` +
       `<th>${fmt("wdColCell")}</th><th>${fmt("wdColPrize")}</th>` +
       `<th>${fmt("wdColHitCount")}</th><th>${fmt("wdColHitRate")}</th>` +
       `</tr></thead><tbody>${cellRows}</tbody></table>` +
       (Array.isArray(cm.unobserved_cells) && cm.unobserved_cells.length
         ? `<p class="drilldown-hint"><em>${fmt("wdUnobservedNote")}</em></p>` : "") +
       ((cm.nondeterministic_cells && Object.keys(cm.nondeterministic_cells).length)
         ? `<p class="drilldown-hint"><em>${fmt("wdNondetAlarm")}</em></p>` : ""))
    : "";
  const cellHtml = `<div class="mech-section">
    <h3>${fmt("wdCellMap")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("wdCells")}</span><span class="mech-value">${fInt(cm.wheel_cell_count)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("wdObservedCells")}</span><span class="mech-value">${Array.isArray(cm.observed_cells) ? cm.observed_cells.length : "—"}/${fInt(cm.wheel_cell_count)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("wdJackpotPrize")}</span><span class="mech-value">${dJackpot != null ? `${dJackpot}×` : "—"}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("wdJackpotCells")}</span><span class="mech-value">${jackpotCells.length ? jackpotCells.map((c) => `#${c}`).join(" ") : "—"}</span></div>
    </div>
    ${cellGridHtml}
  </div>`;

  // ── W4 RTP concentration KPI block ──
  const rtpC = wd.rtp_concentration || {};
  const rtpHtml = `<div class="mech-section">
    <h3>${fmt("mgRtpConcentration")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("wdRtpContrib")}</span><span class="mech-value">${rtpC.wheel_rtp_contribution_pp != null ? Number(rtpC.wheel_rtp_contribution_pp).toFixed(2) + "pp" : "—"}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("mgShareOfWin")}</span><span class="mech-value">${_pct(rtpC.share_of_all_win, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("mgEventRate")}</span><span class="mech-value">${_pct(rtpC.event_rate, 3)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("mgHitRate")}</span><span class="mech-value">${_pct(rtpC.hit_rate, 1)}</span></div>
    </div>
    ${rtpC.note ? `<p class="drilldown-hint">${_escHtml(rtpC.note)}</p>` : ""}
  </div>`;

  return `<p class="drilldown-hint"><strong>${fmt("panelWheelDynamics")}</strong></p>` +
    gpHtml + multHtml + cellHtml + rtpHtml;
}

// Dimension: nudge dynamics — attaches to the crazy-reel NUDGE ST (the paid base
// spin whose spin_type matches nudge_dynamics.nudge_spin_type, e.g. M63 ST1 where
// the crazy_up/crazy/crazy_down 3-stack slides a single reel). Returns "" for all
// other STs and machines (same isolation as _stDimWheel — gates on applicable +
// nudge_spin_type === row.spin_type). Reuses the same mech-section/mech-grid KPI
// blocks + drilldown-table/bar-cell markup + helpers (fmt/fInt/_escHtml) as the
// sibling respin/minigame/wheel/freespin dimensions — no new CSS, no parallel impl
// (feedback_no_parallel_panel_impl.md).
function _stDimNudge(stCtx) {
  const nd = ((stCtx.summary || {}).player_impact || {}).nudge_dynamics;
  if (!nd || !nd.applicable) return "";
  if (Number(nd.nudge_spin_type) !== Number(stCtx.row.spin_type)) return "";

  // Helper: format a probability value as a percentage string or "—".
  const _pct = (v, d = 2) =>
    (v == null || !Number.isFinite(Number(v))) ? "—" : `${(Number(v) * 100).toFixed(d)}%`;
  // Helper: format a ratio/multiplier value or "—".
  const _ratio = (v, d = 2) =>
    (v == null || !Number.isFinite(Number(v))) ? "—" : `${Number(v).toFixed(d)}×`;

  // ── N1 Nudge cadence KPI block ──
  const cad = nd.cadence || {};
  const cadenceHtml = `<div class="mech-section">
    <h3>${fmt("ndCadence")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("ndHitRate")}</span><span class="mech-value">${_pct(nd.hit_rate, 2)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("ndNudgeRounds")}</span><span class="mech-value">${fInt(cad.nudge_rounds)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("ndSingleColShare")}</span><span class="mech-value">${_pct(nd.single_col_share, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("ndOnePerN")}</span><span class="mech-value">${cad.one_per_n_paid_spins != null ? Number(cad.one_per_n_paid_spins).toFixed(1) : "—"}</span></div>
    </div>
  </div>`;

  // ── N2 + N3 Win-rate uplift KPI block ──
  const u = nd.win_rate_uplift || {};
  const upliftHtml = `<div class="mech-section">
    <h3>${fmt("ndUplift")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("ndNudgeWinRate")}</span><span class="mech-value">${_pct(u.nudge, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("ndBaselineWinRate")}</span><span class="mech-value">${_pct(u.baseline, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("ndUpliftRatio")}</span><span class="mech-value">${_ratio(u.ratio, 2)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("ndWinThrough")}</span><span class="mech-value">${_pct(nd.win_through_nudge_share, 1)}</span></div>
    </div>
  </div>`;

  // ── N4 Slide-offset distribution (drilldown bar-table) ──
  const slides = Array.isArray(nd.slide_distribution)
    ? nd.slide_distribution.filter((s) => s.prob != null && Number(s.prob) > 0)
    : [];
  const maxSlideProb = Math.max(...slides.map((s) => Number(s.prob) || 0), 0.0001);
  const slideRows = slides.map((s) => {
    const prob = Number(s.prob) || 0;
    const barPct = (prob / maxSlideProb) * 100;
    return (
      `<tr>` +
      `<td>${_escHtml(String(s.offset_label))}</td>` +
      `<td>${fInt(s.count)}</td>` +
      `<td class="bar-cell" style="--bar:${barPct.toFixed(1)}%">${_pct(prob, 2)}</td>` +
      `</tr>`
    );
  }).join("");
  const slideHtml = slides.length
    ? (`<p class="drilldown-hint"><strong>${fmt("ndSlideDist")}</strong></p>` +
       `<table class="drilldown-table"><thead><tr>` +
       `<th>${fmt("ndColArrangement")}</th><th>${fmt("ndColCount")}</th>` +
       `<th>${fmt("rdColProb")}</th>` +
       `</tr></thead><tbody>${slideRows}</tbody></table>`)
    : "";

  // ── N5 Per-column distribution (drilldown table) ──
  const cols = Array.isArray(nd.by_column) ? nd.by_column : [];
  const colRows = cols.map((c) => (
    `<tr>` +
    `<td>${fmt("ndReelLabel")} ${_escHtml(String(c.col))}</td>` +
    `<td>${fInt(c.count)}</td>` +
    `<td>${_pct(c.share, 1)}</td>` +
    `</tr>`
  )).join("");
  const colHtml = cols.length
    ? (`<p class="drilldown-hint"><strong>${fmt("ndColDist")}</strong></p>` +
       `<table class="drilldown-table"><thead><tr>` +
       `<th>${fmt("ndColReel")}</th><th>${fmt("ndColCount")}</th>` +
       `<th>${fmt("ndColShare")}</th>` +
       `</tr></thead><tbody>${colRows}</tbody></table>`)
    : "";

  // ── N6 RTP concentration KPI block ──
  const rtpC = nd.rtp_concentration || {};
  const rtpHtml = `<div class="mech-section">
    <h3>${fmt("mgRtpConcentration")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("mgShareOfWin")}</span><span class="mech-value">${_pct(rtpC.share_of_all_win, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("ndRtpContrib")}</span><span class="mech-value">${rtpC.nudge_rtp_contribution_pp != null ? Number(rtpC.nudge_rtp_contribution_pp).toFixed(2) + "pp" : "—"}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("mgEventRate")}</span><span class="mech-value">${_pct(rtpC.event_rate, 2)}</span></div>
    </div>
    ${rtpC.note ? `<p class="drilldown-hint">${_escHtml(rtpC.note)}</p>` : ""}
  </div>`;

  return `<p class="drilldown-hint"><strong>${fmt("panelNudgeDynamics")}</strong></p>` +
    cadenceHtml + upliftHtml + slideHtml + colHtml + rtpHtml;
}

// Dimension: freespin dynamics — attaches to the FREESPIN event (the ST whose
// spin_type matches freespin_dynamics.freespin_spin_type, e.g. M275 ST126's
// NewFreespin granted 10-spin session). Returns "" for all other STs. Reuses
// the same mech-section/mech-grid KPI blocks + drilldown-table/bar-cell markup
// as the sibling respin/minigame/wheel dimensions.
function _stDimFreespin(stCtx) {
  const fd = ((stCtx.summary || {}).player_impact || {}).freespin_dynamics;
  if (!fd || !fd.applicable) return "";
  if (Number(fd.freespin_spin_type) !== Number(stCtx.row.spin_type)) return "";

  // Helper: format a probability value as a percentage string or "—".
  const _pct = (v, d = 2) =>
    (v == null || !Number.isFinite(Number(v))) ? "—" : `${(Number(v) * 100).toFixed(d)}%`;
  // Helper: format a ratio/multiplier value or "—".
  const _ratio = (v, d = 2) =>
    (v == null || !Number.isFinite(Number(v))) ? "—" : `${Number(v).toFixed(d)}×`;
  // Helper: render a band distribution table (same markup as _stDimRespin).
  const _bandTable = (dist, titleKey) => {
    if (!dist || !Array.isArray(dist.bands) || !dist.bands.length) return "";
    const bands = dist.bands.filter((b) => b.prob != null && Number(b.prob) > 0);
    if (!bands.length) return "";
    const maxProb = Math.max(...bands.map((b) => Number(b.prob) || 0), 0.0001);
    const rows = bands.map((b) => {
      const prob = Number(b.prob) || 0;
      const barPct = (prob / maxProb) * 100;
      const winShare = b.win_share != null ? `${(Number(b.win_share) * 100).toFixed(1)}%` : "—";
      return (
        `<tr>` +
        `<td>${PURE.prettyBucketLabel ? PURE.prettyBucketLabel(b.band) : b.band}×</td>` +
        `<td>${fInt(b.spin_count)}</td>` +
        `<td class="bar-cell" style="--bar:${barPct.toFixed(1)}%">${_pct(prob, 2)}</td>` +
        `<td>${winShare}</td>` +
        `</tr>`
      );
    }).join("");
    const tail = dist.tail_ge20x_win_share != null
      ? `<p class="drilldown-hint">${fmt("rdTailGe20")}: ${_pct(dist.tail_ge20x_win_share, 1)}</p>`
      : "";
    return (
      `<p class="drilldown-hint"><strong>${fmt(titleKey)}</strong> · ${fInt(dist.total_spins)} 次 · ${fInt(dist.win_rounds)} 次赢钱</p>` +
      `<table class="drilldown-table"><thead><tr>` +
      `<th>${fmt("rdColBand")}</th><th>${fmt("stoColHits")}</th>` +
      `<th>${fmt("rdColProb")}</th><th>${fmt("rdColWinShare")}</th>` +
      `</tr></thead><tbody>${rows}</tbody></table>` +
      tail
    );
  };
  // Helper: a parser-blind bullet list (same markup as the sibling dims).
  const _blindList = (items) => (Array.isArray(items) && items.length)
    ? (`<p class="drilldown-hint"><em>${fmt("mgParserBlind")}:</em></p>` +
       `<ul class="drilldown-hint" style="margin:0 0 0 1em;padding:0;">` +
       items.map((s) => `<li>${_escHtml(s)}</li>`).join("") +
       `</ul>`)
    : "";

  // ── F1 Session cadence KPI block ──
  const sc = fd.session_cadence || {};
  const cont = sc.continuation || {};
  const corr = sc.chain_structure_corroboration || {};
  const exitRows = Object.entries(cont.exit_breakdown || {})
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .map(([st, cnt]) => `<tr><td>ST${st}</td><td>${fInt(cnt)}</td></tr>`)
    .join("");
  const cadenceHtml = `<div class="mech-section">
    <h3>${fmt("fsCadence")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("fsOpeners")}</span><span class="mech-value">${fInt(sc.openers)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdGrantRatePerSpin")}</span><span class="mech-value">${_pct(sc.per_paid_spin, 3)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdGrantRateOnePerN")}</span><span class="mech-value">${sc.one_per_n_paid_spins != null ? Number(sc.one_per_n_paid_spins).toFixed(1) : "—"}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("fsAvgBlockLen")}</span><span class="mech-value">${sc.avg_block_length_rounds != null ? Number(sc.avg_block_length_rounds).toFixed(2) : "—"}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdContinuationProb")}</span><span class="mech-value">${_pct(cont.continuation_prob, 2)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("fsChainCount")}</span><span class="mech-value">${corr.chain_count != null ? fInt(corr.chain_count) : "—"}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("fsAvgChainLen")}</span><span class="mech-value">${corr.avg_chain_length != null ? Number(corr.avg_chain_length).toFixed(2) : "—"}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("fsRetriggersPerChain")}</span><span class="mech-value">${corr.avg_retriggers_per_chain != null ? Number(corr.avg_retriggers_per_chain).toFixed(3) : "—"}</span></div>
    </div>
    ${cont.note ? `<p class="drilldown-hint">${_escHtml(cont.note)}</p>` : ""}
    ${exitRows ? (`<p class="drilldown-hint">${fmt("rdExitBreakdown")}</p><table class="drilldown-table"><thead><tr><th>ST</th><th>${fmt("tdColCount")}</th></tr></thead><tbody>${exitRows}</tbody></table>`) : ""}
    ${corr.source ? `<p class="drilldown-hint">${_escHtml(corr.source)}</p>` : ""}
  </div>`;

  // ── F2 Hot-board uplift KPI block ──
  const hbu = fd.hot_board_uplift || {};
  const upliftHtml = `<div class="mech-section">
    <h3>${fmt("rdHitRateUplift")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("fsFreespinHitRate")}</span><span class="mech-value">${_pct(hbu.freespin_hit_rate, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdBaseHitRate")}</span><span class="mech-value">${_pct(hbu.base_hit_rate, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdUpliftRatio")}</span><span class="mech-value">${_ratio(hbu.uplift_ratio, 2)}</span></div>
    </div>
  </div>`;

  // ── F2 Multiplier distributions (freespin + base side by side) ──
  const multHtml =
    _bandTable(fd.freespin_multiplier_distribution, "fsFreespinMultDist") +
    _bandTable(fd.base_multiplier_distribution, "rdBaseMultDist");

  // ── F2 PayID mix (freespin vs base) ──
  const mix = fd.payid_mix || {};
  const _payidRows = (shareMap) => {
    const entries = Object.entries(shareMap || {});
    if (!entries.length) return "<tr><td colspan='3'>—</td></tr>";
    return entries
      .sort((a, b) => Number(b[1].hit_share || 0) - Number(a[1].hit_share || 0))
      .map(([pid, v]) =>
        `<tr><td>${pid}</td>` +
        `<td>${fInt(v.hit_count)}</td>` +
        `<td>${_pct(v.hit_share, 1)}</td>` +
        `<td>${_pct(v.win_share, 1)}</td></tr>`
      ).join("");
  };
  const payidHtml = (mix.freespin_payid_share || mix.base_payid_share)
    ? (`<p class="drilldown-hint"><strong>${fmt("fsPayidMix")}</strong></p>` +
       `<div style="display:flex;gap:1rem;flex-wrap:wrap;">` +
       `<div><p class="drilldown-hint">Freespin (ST${fd.freespin_spin_type})</p>` +
       `<table class="drilldown-table"><thead><tr><th>${fmt("rdColPayid")}</th><th>${fmt("stoColHits")}</th><th>${fmt("rdColHitShare")}</th><th>${fmt("rdColWinShare")}</th></tr></thead><tbody>${_payidRows(mix.freespin_payid_share)}</tbody></table></div>` +
       `<div><p class="drilldown-hint">Base (ST${fd.base_spin_type})</p>` +
       `<table class="drilldown-table"><thead><tr><th>${fmt("rdColPayid")}</th><th>${fmt("stoColHits")}</th><th>${fmt("rdColHitShare")}</th><th>${fmt("rdColWinShare")}</th></tr></thead><tbody>${_payidRows(mix.base_payid_share)}</tbody></table></div>` +
       `</div>` +
       (mix.note ? `<p class="drilldown-hint">${fmt("rdPayidNote")}: ${_escHtml(mix.note)}</p>` : ""))
    : "";

  // ── F6 Trigger-path dimension (side-by-side: one column per path) ──
  const tp = fd.trigger_paths || {};
  let pathsHtml = "";
  if (tp.available && Array.isArray(tp.paths) && tp.paths.length) {
    const paths = tp.paths;
    const headCols = paths.map((p) => `<th>${_escHtml(p.label || p.path)}</th>`).join("");
    const _metricRow = (labelKey, cellFn) =>
      `<tr><td>${fmt(labelKey)}</td>` +
      paths.map((p) => `<td>${cellFn(p)}</td>`).join("") + `</tr>`;
    const metricRows =
      _metricRow("fsRowSessions", (p) => fInt(p.session_count)) +
      _metricRow("fsRowSessionShare", (p) => _pct(p.session_share, 1)) +
      _metricRow("fsRowTriggerRate", (p) => _pct(p.trigger_rate_per_paid_spin, 3)) +
      _metricRow("fsRowOnePerN", (p) => p.one_per_n_paid_spins != null ? Number(p.one_per_n_paid_spins).toFixed(1) : "—") +
      _metricRow("fsRowRounds", (p) => fInt(p.round_count)) +
      _metricRow("fsRowWinShare", (p) => _pct(p.win_share, 1)) +
      _metricRow("fsRowRtpPp", (p) => p.rtp_contribution_pp_split != null ? Number(p.rtp_contribution_pp_split).toFixed(2) + "pp" : "—");
    // Per-path round-level multiplier band histograms, side by side.
    const _pathBandTable = (p) => {
      const rows = (Array.isArray(p.win_band_hist) ? p.win_band_hist : [])
        .filter((b) => (Number(b.round_count) || 0) > 0);
      if (!rows.length) return "";
      const maxProb = Math.max(...rows.map((b) => Number(b.prob) || 0), 0.0001);
      const body = rows.map((b) => {
        const prob = Number(b.prob) || 0;
        const barPct = (prob / maxProb) * 100;
        return (
          `<tr><td>${PURE.prettyBucketLabel ? PURE.prettyBucketLabel(b.band) : b.band}×</td>` +
          `<td>${fInt(b.round_count)}</td>` +
          `<td class="bar-cell" style="--bar:${barPct.toFixed(1)}%">${_pct(prob, 2)}</td></tr>`
        );
      }).join("");
      return (
        `<div><p class="drilldown-hint">${_escHtml(p.label || p.path)}</p>` +
        `<table class="drilldown-table"><thead><tr>` +
        `<th>${fmt("rdColBand")}</th><th>${fmt("fsRowRounds")}</th><th>${fmt("rdColProb")}</th>` +
        `</tr></thead><tbody>${body}</tbody></table></div>`
      );
    };
    const bandTables = paths.map(_pathBandTable).filter(Boolean).join("");
    // Surfaced alarm buckets (unknown discriminator values / multi-trigger).
    const _alarmRows = (list) => (Array.isArray(list) ? list : [])
      .map((p) =>
        `<tr><td>${_escHtml(p.path)}</td><td>${fInt(p.session_count)}</td>` +
        `<td>${fInt(p.round_count)}</td><td>${_pct(p.win_share, 1)}</td></tr>`)
      .join("");
    const unknownHtml = (tp.unknown_paths && tp.unknown_paths.length)
      ? (`<p class="drilldown-hint"><strong>⚠ ${fmt("fsUnknownPaths")}</strong></p>` +
         `<table class="drilldown-table"><thead><tr><th>${fmt("fsColPath")}</th><th>${fmt("fsRowSessions")}</th><th>${fmt("fsRowRounds")}</th><th>${fmt("rdColWinShare")}</th></tr></thead>` +
         `<tbody>${_alarmRows(tp.unknown_paths)}</tbody></table>` +
         (tp.unknown_paths_alarm ? `<p class="drilldown-hint">${_escHtml(tp.unknown_paths_alarm)}</p>` : ""))
      : "";
    const multiHtml = (tp.multi_buckets && tp.multi_buckets.length)
      ? (`<p class="drilldown-hint"><strong>${fmt("fsMultiBuckets")}</strong></p>` +
         `<table class="drilldown-table"><thead><tr><th>${fmt("fsColPath")}</th><th>${fmt("fsRowSessions")}</th><th>${fmt("fsRowRounds")}</th><th>${fmt("rdColWinShare")}</th></tr></thead>` +
         `<tbody>${_alarmRows(tp.multi_buckets)}</tbody></table>` +
         (tp.multi_buckets_note ? `<p class="drilldown-hint">${_escHtml(tp.multi_buckets_note)}</p>` : ""))
      : "";
    const errHtml = (tp.extraction_errors && tp.extraction_errors.length)
      ? `<p class="drilldown-hint"><strong>⚠ extract errors:</strong> ${tp.extraction_errors.map(_escHtml).join("; ")}</p>`
      : "";
    pathsHtml = `<div class="mech-section">
      <h3>${fmt("fsTriggerPaths")}</h3>
      <p class="drilldown-hint">${fmt("fsTotalSessions")}: ${fInt(tp.total_sessions)}</p>
      <table class="drilldown-table"><thead><tr><th>${fmt("fsColMetric")}</th>${headCols}</tr></thead><tbody>${metricRows}</tbody></table>
      ${bandTables ? `<p class="drilldown-hint"><strong>${fmt("fsPathBands")}</strong></p><div style="display:flex;gap:1rem;flex-wrap:wrap;">${bandTables}</div>` : ""}
      ${unknownHtml}${multiHtml}${errHtml}
      ${tp.source ? `<p class="drilldown-hint">${_escHtml(tp.source)}</p>` : ""}
    </div>`;
  } else if (tp && tp.available === false) {
    pathsHtml = `<div class="mech-section">
      <h3>${fmt("fsTriggerPaths")}</h3>
      <p class="drilldown-hint">${_escHtml(tp.reason || "—")}</p>
      ${(tp.extraction_errors && tp.extraction_errors.length) ? `<p class="drilldown-hint"><strong>⚠</strong> ${tp.extraction_errors.map(_escHtml).join("; ")}</p>` : ""}
    </div>`;
  }

  // ── RTP concentration KPI block ──
  const rtpC = fd.rtp_concentration || {};
  const rtpHtml = `<div class="mech-section">
    <h3>${fmt("rdRtpConcentration")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("fsRtpContrib")}</span><span class="mech-value">${rtpC.freespin_rtp_contribution_pp != null ? Number(rtpC.freespin_rtp_contribution_pp).toFixed(2) + "pp" : "—"}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdShareOfWin")}</span><span class="mech-value">${_pct(rtpC.share_of_all_win, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdFatTailShare")}</span><span class="mech-value">${_pct(rtpC.fat_tail_ge20x_win_share, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdLossRate")}</span><span class="mech-value">${_pct(rtpC.zero_win_round_rate, 1)}</span></div>
    </div>
    ${rtpC.note ? `<p class="drilldown-hint">${_escHtml(rtpC.note)}</p>` : ""}
  </div>`;

  // ── Phase 3: freespin-progression sub-panels (ER ladder / FS arc / session
  // tiers). These are freespin-SPECIFIC metrics no generic plugin can compute,
  // so freespin_dynamics owns them + their per-path by_dim breakdown. Each
  // section: aggregate (all paths) + one column per trigger-path value when
  // by_dim has >=2 real values. Reuses fmt/fInt/_pct/_escHtml. Absent/
  // unavailable -> the section is skipped (honest, no fabrication).
  const _fsIdxKeys = (m) => Object.keys(m || {})
    .filter(k => /^\d+$/.test(k)).sort((a, b) => Number(a) - Number(b));
  const _dimCols = (sec) => {
    // Returns [{key, label, data}] = aggregate + each real path value.
    const cols = [{ key: "_agg", label: fmt("fsProgAggregate"), data: sec.aggregate || {} }];
    const bd = (sec.by_dim || {});
    const dimName = Object.keys(bd)[0];
    if (dimName) {
      const vals = Object.keys(bd[dimName] || {})
        .filter(v => !String(v).startsWith("_unknown") && !String(v).startsWith("_multi")
                  && !String(v).startsWith("unknown:") && !String(v).startsWith("multi:"));
      if (vals.length >= 2) {
        for (const v of vals) cols.push({ key: v, label: _escHtml(v), data: bd[dimName][v] || {} });
      }
    }
    return cols;
  };

  // ER ladder — per-FS-index mean ExtraRatio (the climb), per path.
  let erHtml = "";
  const er = fd.er_ladder || {};
  if (er.available && (er.aggregate && Object.keys(er.aggregate).length)) {
    const cols = _dimCols(er);
    const idxs = _fsIdxKeys(er.aggregate);
    const head = cols.map(c => `<th>${c.label}</th>`).join("");
    const rows = idxs.map(i => {
      const cells = cols.map(c => {
        const e = (c.data || {})[i] || {};
        return `<td>${e.mean_er != null ? Number(e.mean_er).toFixed(0) : "—"}</td>`;
      }).join("");
      return `<tr><td>${_escHtml(i)}</td>${cells}</tr>`;
    }).join("");
    erHtml = `<div class="mech-section"><h3>${fmt("fsErLadder")}</h3>
      <table class="drilldown-table"><thead><tr><th>${fmt("fsErColFsIdx")}</th>${head}</tr></thead><tbody>${rows}</tbody></table>
      <p class="drilldown-hint">${fmt("fsErLadderNote")}</p>${er.source ? `<p class="drilldown-hint">${_escHtml(er.source)}</p>` : ""}</div>`;
  }

  // FS-index hit-rate arc — the cliff, per path.
  let arcHtml = "";
  const arc = fd.fs_index_arc || {};
  if (arc.available && (arc.aggregate && Object.keys(arc.aggregate).length)) {
    const cols = _dimCols(arc);
    const idxs = _fsIdxKeys(arc.aggregate);
    const head = cols.map(c => `<th>${c.label}</th>`).join("");
    const rows = idxs.map(i => {
      const cells = cols.map(c => {
        const e = (c.data || {})[i] || {};
        return `<td>${_pct(e.hit_rate, 1)}</td>`;
      }).join("");
      return `<tr><td>${_escHtml(i)}</td>${cells}</tr>`;
    }).join("");
    arcHtml = `<div class="mech-section"><h3>${fmt("fsFsArc")}</h3>
      <table class="drilldown-table"><thead><tr><th>${fmt("fsErColFsIdx")}</th>${head}</tr></thead><tbody>${rows}</tbody></table>
      <p class="drilldown-hint">${fmt("fsFsArcNote")}</p>${arc.note ? `<p class="drilldown-hint">${_escHtml(arc.note)}</p>` : ""}</div>`;
  }

  // Session-tier distribution — session win/bet band histogram.
  let tierHtml = "";
  const tier = fd.session_tier_distribution || {};
  if (tier.available !== false && Array.isArray(tier.aggregate) && tier.aggregate.length) {
    // Per-path columns when by_dim has >=2 real values: rows = bands (the
    // aggregate's band order), columns = session count per path. Single/absent
    // → aggregate session-count column only (today's view).
    const tbd = (tier.by_dim || {});
    const tdimName = Object.keys(tbd)[0];
    const tpaths = tdimName ? Object.keys(tbd[tdimName] || {})
      .filter(v => !String(v).startsWith("_unknown") && !String(v).startsWith("_multi")) : [];
    const _bandLabel = (band) => _escHtml(PURE.prettyBucketLabel ? PURE.prettyBucketLabel(band) : band);
    let head, rows;
    if (tpaths.length >= 2) {
      // Build per-path band→count maps.
      const pmap = {};
      for (const p of tpaths) {
        pmap[p] = {};
        for (const r of (tbd[tdimName][p].rows || [])) pmap[p][r.band] = r.session_count;
      }
      head = `<th>${fmt("fsProgAggregate")}</th>` + tpaths.map(p => `<th>${_escHtml(p)}</th>`).join("");
      rows = tier.aggregate.map(b => {
        const pcells = tpaths.map(p => `<td>${fInt(pmap[p][b.band] || 0)}</td>`).join("");
        return `<tr><td>${_bandLabel(b.band)}</td><td>${fInt(b.session_count)}</td>${pcells}</tr>`;
      }).join("");
    } else {
      head = `<th>${fmt("fsRowSessions")}</th><th>${fmt("stoColShare")}</th>`;
      rows = tier.aggregate.map(b =>
        `<tr><td>${_bandLabel(b.band)}</td><td>${fInt(b.session_count)}</td><td>${_pct(b.prob, 1)}</td></tr>`).join("");
    }
    tierHtml = `<div class="mech-section"><h3>${fmt("fsSessionTier")}</h3>
      <p class="drilldown-hint">${fmt("fsSessionTierTotal")}: ${fInt(tier.total_sessions)}</p>
      <table class="drilldown-table"><thead><tr><th>${fmt("rdColBand")}</th>${head}</tr></thead><tbody>${rows}</tbody></table>
      ${tier.total_sessions_note ? `<p class="drilldown-hint">${_escHtml(tier.total_sessions_note)}</p>` : ""}
      ${tier.source ? `<p class="drilldown-hint">${_escHtml(tier.source)}</p>` : ""}</div>`;
  }

  // ── F3a/F4/F5 honest parser-blind notice ──
  const blindHtml = _blindList(fd.parser_blind) +
    (fd.parser_blind_reason ? `<p class="drilldown-hint">${_escHtml(fd.parser_blind_reason)}</p>` : "");

  return `<p class="drilldown-hint"><strong>${fmt("panelFreespinDynamics")}</strong></p>` +
    cadenceHtml + upliftHtml + multHtml + payidHtml + pathsHtml + rtpHtml +
    erHtml + arcHtml + tierHtml + blindHtml;
}

// Dimension: generic trigger-path dimension — side-by-side per-dim columns.
// Phase 2 (dimension framework): reads spin_type_outcomes[label].by_dim and
// payouts_by_spin_type["<label>__by_dim__<dimName>"] when present.
//
// Guards:
// - by_dim absent (M15/M43/M279 — no dimensions declared) → returns ""
//   (byte-identical rendering for those machines per BREAK-1 contract)
// - by_dim present but only 1 real dim value → returns ""
// - N >= 2 real values → renders side-by-side metric table (one column per value)
//
// Reuses: fmt(), fInt(), PURE.fRate, _escHtml — same helpers as sibling dims
// (feedback_no_parallel_panel_impl.md). Reuses fsRowSessions/fsRowRounds/
// fsColMetric i18n keys (already present in pure.js).
function _stDimGenericDimension(stCtx) {
  const { label, outcome, summary } = stCtx;
  const pi = (summary || {}).player_impact || {};

  // Guard: outcome (spin_type_outcomes entry) must exist and have by_dim.
  if (!outcome || typeof outcome !== "object") return "";
  const byDim = outcome.by_dim;
  if (!byDim || typeof byDim !== "object") return "";

  const dimNames = Object.keys(byDim).filter((k) => !k.startsWith("_"));
  if (!dimNames.length) return "";

  let html = "";
  for (const dimName of dimNames) {
    const dimMeta = byDim[dimName];
    if (!dimMeta || typeof dimMeta !== "object") continue;

    // _dim_values is the ordered list of real (non-unknown/non-multi) values.
    const dimValues = Array.isArray(dimMeta._dim_values) ? dimMeta._dim_values : [];
    const realVals = dimValues.filter(
      (v) => !String(v).startsWith("unknown:") && !String(v).startsWith("multi:")
    );
    if (realVals.length < 2) continue;  // degenerate: no column split rendered

    // Per-dim payid rows from payouts_by_spin_type sibling key.
    const pbst = pi.payouts_by_spin_type || {};
    const siblingKey = `${label}__by_dim__${dimName}`;
    const payidByDv = pbst[siblingKey] || {};

    // Section header: dim label (from _dim_label or dim_name).
    const dimLabel = dimMeta._dim_label || dimName.replace(/_/g, " ");
    const headCols = realVals.map((v) => `<th>${_escHtml(String(v))}</th>`).join("");

    // Helper: format a value or "—".
    const _fv = (v, decimals, suffix) =>
      (v == null || !Number.isFinite(Number(v))) ? "—" : Number(v).toFixed(decimals) + (suffix || "");
    const _pct = (v, d) => _fv(Number(v) * 100, d != null ? d : 2, "%");

    // Metric rows: reuse existing i18n keys + new dim* keys.
    const _row = (labelKey, cellFn) =>
      `<tr><td>${fmt(labelKey)}</td>` +
      realVals.map((v) => `<td>${cellFn(dimMeta[v] || {})}</td>`).join("") +
      `</tr>`;

    const metricRows =
      _row("dimRowRounds", (d) => fInt(d.round_count)) +
      _row("dimRowHitRate", (d) => d.hit_rate != null ? _pct(d.hit_rate, 1) : "—") +
      _row("dimRowDeadSpinRate", (d) => d.dead_spin_rate != null ? _pct(d.dead_spin_rate, 1) : "—") +
      _row("dimRowRtpPp", (d) => _fv(d.rtp_contribution_pp, 2, "pp"));

    // Per-dim payid mini-table (top combos by rtp_contribution_pp).
    const _payidMini = (dvRows) => {
      const rows = (dvRows || [])
        .filter((r) => !String(r.payout_id || "").startsWith("_"))
        .sort((a, b) => Number(b.rtp_contribution_pp ?? b.rtp_pp ?? 0) - Number(a.rtp_contribution_pp ?? a.rtp_pp ?? 0))
        .slice(0, 8);
      if (!rows.length) return "—";
      return rows.map((r) =>
        `${_escHtml(String(r.payout_id || ""))} ${(Number(r.rtp_contribution_pp ?? r.rtp_pp ?? 0)).toFixed(2)}pp`
      ).join(", ");
    };
    const payidCells = realVals
      .map((v) => `<td><small>${_payidMini(payidByDv[v])}</small></td>`)
      .join("");
    const payidRow = payidByDv && Object.keys(payidByDv).length
      ? `<tr><td>${fmt("stoPayidTitle")}</td>${payidCells}</tr>`
      : "";

    // Alarm rows: _unknown / _multi (if non-empty in by_dim).
    const unknownVals = Object.keys(dimMeta).filter((k) => k.startsWith("unknown:") || k === "_unknown");
    const multiVals = Object.keys(dimMeta).filter((k) => k.startsWith("multi:") || k === "_multi");
    const alarmHtml = (unknownVals.length || multiVals.length)
      ? `<p class="drilldown-hint"><em>${_escHtml("unknown/multi buckets: " + [...unknownVals, ...multiVals].filter(k=>k!=="$meta").join(", ") || "none")}</em></p>`
      : "";

    html += `<div class="mech-section">
      <h3>${_escHtml(dimLabel)}</h3>
      <table class="drilldown-table"><thead><tr>
        <th>${fmt("dimColMetric")}</th>${headCols}
      </tr></thead><tbody>${metricRows}${payidRow}</tbody></table>
      ${alarmHtml}
    </div>`;
  }

  return html;
}

// Dimension: lock-respin dynamics — attaches to the LOCK event (the ST whose
// spin_type matches lock_respin_dynamics.lock_spin_type, e.g. M104 ST96's
// in-line LockSymbolSpin hold-and-respin). Returns "" for all other STs so the
// analysis renders only inside the matching ST section. Reuses the same
// mech-section/mech-grid KPI blocks + drilldown-table/bar-cell markup + the
// shared rd*/sto* i18n keys as the sibling respin/minigame/wheel/freespin
// dimensions (feedback_no_parallel_panel_impl.md — no parallel impl).
function _stDimLockRespin(stCtx) {
  const lr = ((stCtx.summary || {}).player_impact || {}).lock_respin_dynamics;
  if (!lr || !lr.applicable) return "";
  if (Number(lr.lock_spin_type) !== Number(stCtx.row.spin_type)) return "";

  // Helper: format a probability value as a percentage string or "—".
  const _pct = (v, d = 2) =>
    (v == null || !Number.isFinite(Number(v))) ? "—" : `${(Number(v) * 100).toFixed(d)}%`;
  // Helper: render a band distribution table (same markup as _stDimRespin).
  const _bandTable = (dist, titleKey) => {
    if (!dist || !Array.isArray(dist.bands) || !dist.bands.length) return "";
    const bands = dist.bands.filter((b) => b.prob != null && Number(b.prob) > 0);
    if (!bands.length) return "";
    const maxProb = Math.max(...bands.map((b) => Number(b.prob) || 0), 0.0001);
    const rows = bands.map((b) => {
      const prob = Number(b.prob) || 0;
      const barPct = (prob / maxProb) * 100;
      const winShare = b.win_share != null ? `${(Number(b.win_share) * 100).toFixed(1)}%` : "—";
      return (
        `<tr>` +
        `<td>${PURE.prettyBucketLabel ? PURE.prettyBucketLabel(b.band) : b.band}×</td>` +
        `<td>${fInt(b.spin_count)}</td>` +
        `<td class="bar-cell" style="--bar:${barPct.toFixed(1)}%">${_pct(prob, 2)}</td>` +
        `<td>${winShare}</td>` +
        `</tr>`
      );
    }).join("");
    const tail = dist.tail_ge20x_win_share != null
      ? `<p class="drilldown-hint">${fmt("rdTailGe20")}: ${_pct(dist.tail_ge20x_win_share, 1)}</p>`
      : "";
    return (
      `<p class="drilldown-hint"><strong>${fmt(titleKey)}</strong> · ${fInt(dist.total_spins)} 次 · ${fInt(dist.win_rounds)} 次赢钱</p>` +
      `<table class="drilldown-table"><thead><tr>` +
      `<th>${fmt("rdColBand")}</th><th>${fmt("stoColHits")}</th>` +
      `<th>${fmt("rdColProb")}</th><th>${fmt("rdColWinShare")}</th>` +
      `</tr></thead><tbody>${rows}</tbody></table>` +
      tail
    );
  };

  // ── FD1 Lock grant-rate KPI block (record-level, base-derivable) ──
  const gr = lr.grant_rate || {};
  const grantHtml = `<div class="mech-section">
    <h3>${fmt("lrGrantRate")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("lrLockRecords")}</span><span class="mech-value">${fInt(gr.lock_records)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("lrRecordRate")}</span><span class="mech-value">${_pct(gr.per_paid_spin_record_rate, 2)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("lrOnePerN")}</span><span class="mech-value">${gr.one_per_n_paid_spins_records != null ? Number(gr.one_per_n_paid_spins_records).toFixed(1) : "—"}</span></div>
    </div>
    ${gr.note ? `<p class="drilldown-hint">${_escHtml(gr.note)}</p>` : ""}
  </div>`;

  // ── FD3 35x ⟺ Lock determinism KPI block (declared structural fact) ──
  const det = lr.determinism || {};
  const detHtml = `<div class="mech-section">
    <h3>${fmt("lrDeterminism")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("lrTriggerSymbol")}</span><span class="mech-value">${det.trigger_symbol != null ? _escHtml(String(det.trigger_symbol)) : "—"}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("lrPLockGivenTrig")}</span><span class="mech-value">${_pct(det.p_lock_given_trigger, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("lrPLockGivenNoTrig")}</span><span class="mech-value">${_pct(det.p_lock_given_no_trigger, 1)}</span></div>
    </div>
    ${det.source ? `<p class="drilldown-hint">${_escHtml(det.source)}</p>` : ""}
  </div>`;

  // ── FD5 Lock RTP-concentration KPI block (base-derivable) ──
  const rtpC = lr.rtp_concentration || {};
  const rtpHtml = `<div class="mech-section">
    <h3>${fmt("rdRtpConcentration")}</h3>
    <div class="mech-grid">
      <div class="mech-stat"><span class="mech-label">${fmt("lrLockWinShareSt")}</span><span class="mech-value">${_pct(rtpC.lock_record_win_share_of_st, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdRtpContrib")}</span><span class="mech-value">${rtpC.st_rtp_contribution_pp != null ? Number(rtpC.st_rtp_contribution_pp).toFixed(2) + "pp" : "—"}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdFatTailShare")}</span><span class="mech-value">${_pct(rtpC.fat_tail_ge20x_win_share, 1)}</span></div>
      <div class="mech-stat"><span class="mech-label">${fmt("rdLossRate")}</span><span class="mech-value">${_pct(rtpC.loss_rate, 1)}</span></div>
    </div>
    ${rtpC.note ? `<p class="drilldown-hint">${_escHtml(rtpC.note)}</p>` : ""}
  </div>`;

  // ── FD2/FD4 multiplier band shape (the lock-RTP framing of the ST band dist) ──
  const multHtml = _bandTable(lr.multiplier_distribution, "lrMultDist");

  // ── parser_blind (FD2 chain-length ladder / FD4 wild ladder — honest, never
  //    fabricated; same boundary respin_dynamics flags for M43/M279). ──
  const pbItems = Array.isArray(lr.parser_blind) ? lr.parser_blind : [];
  const pbHtml = pbItems.length
    ? (`<div class="mech-section"><h3>${fmt("lrParserBlind")}</h3>` +
       `<p class="drilldown-hint"><em>${fmt("rdParserBlind")} (待 per-ST 提取层):</em></p>` +
       `<ul class="drilldown-hint" style="margin:0 0 0 1em;padding:0;">` +
       pbItems.map((s) => `<li>${_escHtml(s)}</li>`).join("") +
       `</ul>` +
       (lr.parser_blind_reason ? `<p class="drilldown-hint">${_escHtml(lr.parser_blind_reason)}</p>` : "") +
       `</div>`)
    : "";

  return `<p class="drilldown-hint"><strong>${fmt("panelLockRespinDynamics")}</strong></p>` +
    grantHtml + detHtml + multHtml + rtpHtml + pbHtml;
}

// The dimension list (order = render order within each ST section).
const SPINTYPE_DIMENSIONS = [
  _stDimWinDistribution,
  _stDimPayid,
  _stDimSelectorChoice,
  _stDimSettlement,
  _stDimRespin,
  _stDimMinigame,
  _stDimWheel,
  _stDimFreespin,
  _stDimLockRespin,
  _stDimNudge,
  _stDimGenericDimension,
];

function renderSpinTypeOutcomes(summary) {
  const panel = byId("spinTypeOutcomesPanel");
  if (!panel) return;
  const body = byId("spinTypeOutcomesBody");
  const pi = (summary || {}).player_impact || {};
  const stbRows = pi.spin_type_breakdown || [];
  if (!stbRows.length) {
    panel.classList.add("hidden");
    if (body) body.innerHTML = "";
    return;
  }
  const sto = pi.spin_type_outcomes || {};
  const pbst = pi.payouts_by_spin_type || {};
  const bet = Number((summary.sampling || {}).bet) || 1000;

  let html = "";
  for (const r of stbRows) {
    const label = "ST" + r.spin_type + "_" + (r.behavior_name || "");
    const stCtx = { row: r, label, outcome: sto[label] || {}, payRows: pbst[label] || [], summary, bet };

    // Header (feature chip) + always-present overview KV.
    const featChip = r.feature_name
      ? ` <span class="st-feature-tag" title="${escapeHtml(fmt("spinTypeFeatureTitle"))}">${escapeHtml(r.feature_name)}` +
        `${r.feature_trigger_only ? " · " + escapeHtml(fmt("spinTypeFeatureTriggerOnly")) : ""}</span>`
      : "";
    html += `<h3 class="drilldown-subhead">${_formatSpinTypeLabel(label)}${featChip}</h3>`;
    html += _stDimOverview(stCtx);

    // Detail dimensions — each self-applies by data present.
    let detail = "";
    for (const dim of SPINTYPE_DIMENSIONS) detail += dim(stCtx) || "";
    if (detail) html += detail;
    else html += `<p class="drilldown-hint">${fmt("stoNoPayouts")}</p>`;
  }

  body.innerHTML = html;
  panel.classList.remove("hidden");
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
  const fsMech = mm.free_spin || {};
  const dpMech = mm.dollar_pick || {};
  // Visibility gate must cover EVERY section the body below renders —
  // free_spin/dollar_pick were missing, so a machine whose ONLY applicable
  // mechanic is free_spin (M275) hid the whole panel (gate-7 finding).
  const anyApplicable = ll.applicable || ls.applicable || lr.applicable ||
    jp.applicable || fsMech.applicable || dpMech.applicable;
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

// ── Compare-mode Δ chip helpers ───────────────────────────────────
//
// Every numeric cell in a compare-aware panel now grows a small
// Δ chip next to B's value: ▲+12.5% (blue), ▼−56.9% (orange), or
// ≈ (gray for noise). The chip color encodes DIRECTION ONLY — we
// deliberately don't paint "B is better than A" green vs "B is
// worse" red, because the same metric can mean the opposite to
// different audiences (策划 wants more bankruptcy rate to mean
// 更刺激 = better volatility; player advocate wants it to mean
// 更危险 = worse). Operator interprets meaning; we just show the
// arrow.
//
// kind:
//   - 'pp' : both inputs are in the same "rate / pp / percent"
//            unit; Δ rendered as absolute (b - a)pp. Use this for
//            already-percent values (RTP pp, win share %, hit
//            rate as fraction, etc.).
//   - 'rel': inputs are counts / multipliers / unit-less numbers;
//            Δ rendered as (b - a)/a × 100% relative. Use for
//            spin counts, fires, durations.
//
// Noise threshold: |Δ| < 0.05pp (for 'pp') or |Δ| < 0.5%
// (for 'rel') → flat chip. Avoids visual noise on
// rounding-error-scale differences.
//
// digits: decimal places on the magnitude (default 1). Set to 2
// for finer-grained metrics like RTP pp where 0.10pp matters.
//
// Returns innerHTML; safe to concatenate into a TD.
function _cmpDelta(aRaw, bRaw, kind, digits) {
  if (!Number.isFinite(aRaw) || !Number.isFinite(bRaw)) {
    return `<span class="cmp-delta cmp-delta-flat" title="Δ unavailable">—</span>`;
  }
  digits = digits == null ? 1 : digits;
  if (kind === "pp") {
    const d = bRaw - aRaw;
    if (Math.abs(d) < 0.05) {
      return `<span class="cmp-delta cmp-delta-flat" title="Δ ≈ 0pp (within noise)">≈</span>`;
    }
    const arrow = d > 0 ? "▲" : "▼";
    const tone = d > 0 ? "up" : "down";
    return `<span class="cmp-delta cmp-delta-${tone}" title="B − A = ${d.toFixed(digits)}pp">${arrow}${Math.abs(d).toFixed(digits)}pp</span>`;
  }
  // 'rel' — relative percent change (B / A − 1) × 100.
  if (aRaw === 0 && bRaw === 0) {
    return `<span class="cmp-delta cmp-delta-flat" title="A = B = 0">≈</span>`;
  }
  if (aRaw === 0) {
    // Birth: B has data, A doesn't. Show as "new" so operator sees
    // it's not a Δ but a presence change.
    return `<span class="cmp-delta cmp-delta-up" title="A = 0; B = ${bRaw.toFixed(digits)} (new)">▲ new</span>`;
  }
  if (bRaw === 0) {
    return `<span class="cmp-delta cmp-delta-down" title="A = ${aRaw.toFixed(digits)}; B = 0 (gone)">▼ gone</span>`;
  }
  const dRel = ((bRaw - aRaw) / aRaw) * 100;
  if (Math.abs(dRel) < 0.5) {
    return `<span class="cmp-delta cmp-delta-flat" title="Δ ≈ 0% (within noise)">≈</span>`;
  }
  const arrow = dRel > 0 ? "▲" : "▼";
  const tone = dRel > 0 ? "up" : "down";
  return `<span class="cmp-delta cmp-delta-${tone}" title="B / A = ${(bRaw / aRaw).toFixed(2)} (${dRel >= 0 ? "+" : ""}${dRel.toFixed(digits)}%)">${arrow}${Math.abs(dRel).toFixed(digits)}%</span>`;
}

// Build an A/B stacked cell. When `cmpActive` is false, returns
// the plain A value (single-mode). When true, emits two flex
// rows where A/B tags lock to the left lane, the Δ chip locks
// to a fixed-width middle lane, and the formatted value locks
// to the right lane. This 4-lane layout makes numbers across
// rows form a tabular column even when chips have varying
// widths (▲new vs ▼56.9% vs ≈ would otherwise push values to
// different x positions across rows).
//
// Lanes: [tag] [bar slot opt] [chip] [value right-aligned]
//
// Args:
//   aFmt, bFmt: pre-formatted display strings ("4,300", "58.88pp", etc.)
//   aRaw, bRaw: raw numeric values for the Δ chip; pass undefined to
//               skip the chip (e.g. for non-numeric / multi-component cells)
//   kind:       'pp' | 'rel' for _cmpDelta; ignored if raws missing
//   digits:     Δ chip decimal places
//   opts:       optional { aBarPct, bBarPct } — when provided, an inline
//               magnitude bar renders next to each side's value, paired
//               with its tag's color. This replaces the cell-level
//               ::before / ::after stacked bars for cells that contain
//               text, so each value sits on the same horizontal line as
//               its bar (tight visual association). Omit opts for cells
//               that don't carry per-row bars (counts, hit rates, etc.)
function _cmpCell(cmpActive, aFmt, bFmt, aRaw, bRaw, kind, digits, opts) {
  if (!cmpActive) return aFmt;
  let chipHtml = "";
  if (aRaw !== undefined && bRaw !== undefined) {
    chipHtml = _cmpDelta(aRaw, bRaw, kind, digits);
  }
  // Inline bar slot: only emitted when opts.aBarPct / bBarPct provided.
  // Always renders BOTH slots together (or neither) so A and B rows
  // stay vertically aligned. A 0% bar shows the empty track but no fill.
  const _bar = (pct) =>
    `<span class="cmp-bar-track"><span class="cmp-bar-fill" style="width:${
      Math.max(0, Math.min(100, Number(pct) || 0)).toFixed(1)
    }%"></span></span>`;
  const wantBar = opts && (Number.isFinite(opts.aBarPct) || Number.isFinite(opts.bBarPct));
  const aBarHtml = wantBar ? _bar(opts.aBarPct) : "";
  const bBarHtml = wantBar ? _bar(opts.bBarPct) : "";
  // Note: the .cmp-chip-slot is always rendered (even if empty)
  // so A's and B's vertical alignment matches; without it B would
  // shift left when there's no chip and A/B values would not
  // line up across cells of the same column.
  return (
    `<div class="cmp-cell-a">` +
      `<span class="cmp-tag">A</span>` +
      aBarHtml +
      `<span class="cmp-chip-slot"></span>` +
      `<span class="cmp-val">${aFmt}</span>` +
    `</div>` +
    `<div class="cmp-cell-b">` +
      `<span class="cmp-tag">B</span>` +
      bBarHtml +
      `<span class="cmp-chip-slot">${chipHtml}</span>` +
      `<span class="cmp-val">${bFmt}</span>` +
    `</div>`
  );
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
  // 2026-05-12: clone — 之前直接拿 summary 里的数组引用,后面的
  // declaredPays / B-only 合成行 push 会真的写回 summary,重渲染
  // (轮询 / state 切换) 会累积幽灵行,退出对比模式回 single view 也
  // 残留 B-only 占位。clone 让本函数 push 只影响本地数组。
  const payoutRows = [...((s.player_impact || {}).payout_ids_top20 || [])];

  // Compare mode: pull B's payout rows so we can align by
  // payout_id and emit per-cell A/B stacks. Compare mode also
  // suppresses (a) declared-only paytable padding, (b) composition
  // sub-rows, (c) the wild-evidence sub-section — those are A-side
  // structural details that would clutter the diff. Single mode
  // path is byte-identical when state.compareMode is null.
  const cmpB = state.compareMode && state.compareMode.b ? state.compareMode.b : null;
  const cmpBPayoutRows = cmpB
    ? (cmpB.player_impact || {}).payout_ids_top20 || []
    : [];

  if ((!machine || !mode || !Array.isArray(payoutRows) || !payoutRows.length)
      && (!cmpB || !Array.isArray(cmpBPayoutRows) || !cmpBPayoutRows.length)) {
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

  // (Removed 2026-06-16) The virtual-console-only declared-paytable padding —
  // a GET /api/virtual/paytable/<machine> probe that appended zero-hit rows for
  // declared-but-unfired pay_ids — is gone. The slot_designer/virtual framework
  // (and that endpoint) was deleted (commit 62fb3b6), so the probe 404'd on
  // EVERY report paint fleet-wide. The real console renders observed pay_ids
  // only (the fallback the probe collapsed to anyway), so removing it changes
  // nothing visible and stops the per-paint 404.
  // In compare mode build B-side lookup + extend the row list with
  // B-only payout_ids appended at the end.
  const cmpBMap = new Map();
  if (cmpB) {
    for (const r of cmpBPayoutRows) cmpBMap.set(String(r.payout_id), r);
    const aPidSet = new Set(payoutRows.map((r) => String(r.payout_id)));
    for (const r of cmpBPayoutRows) {
      if (!aPidSet.has(String(r.payout_id))) {
        // Synthetic A-side placeholder so the row renders with "—"
        // for A's metrics; carries _b_only so the renderer can tag.
        payoutRows.push({
          payout_id: r.payout_id,
          hit_count: 0,
          hit_rate: 0,
          avg_win_when_hit: 0,
          rtp_contribution_pp: 0,
          spin_type_category: r.spin_type_category || "paid",
          dominant_spin_type: r.dominant_spin_type || 1,
          _b_only: true,
        });
      }
    }
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
  // Compare mode: hide wild-evidence sub-section. It's A-side
  // structural (per-machine wild inference output) — diffing the
  // evidence table across two reports doesn't tell the operator
  // anything they can't get from the main row diff above.
  const evidenceHtml = (!cmpB && evRows)
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
  // Compare mode: bar scale uses union max across A and B so a row's
  // bar reflects its rank against BOTH sides.
  const maxRtp = Math.max(
    ...payoutRows.map((r) => Number(r.rtp_contribution_pp || 0)),
    ...(cmpB ? cmpBPayoutRows.map((r) => Number(r.rtp_contribution_pp || 0)) : []),
    0.001,
  );
  // Bet denominator for multiplier column. Analyzer writes it under
  // summary.sampling.bet; fall back to 1000 (the default CLI bet) if
  // the field is missing from older reports. Compare mode: A and B
  // can have different bets (cross-machine compare).
  const bet = Number(((summary || {}).sampling || {}).bet) || 1000;
  const betB = cmpB ? Number((cmpB.sampling || {}).bet) || 1000 : bet;

  // Shared helper produces thead + tbody with the same columns, i18n
  // keys, and formatters as used by renderPayoutsBySpinType. Aggregate
  // path: all columns on, sub-rows on, shape data available.
  const tableInner = _renderPayoutRowsHtml(payoutRows, {
    shapeByPayId,
    cmpBMap: cmpB ? cmpBMap : null,
    cmpB: !!cmpB,
    bet,
    betB,
    includeShape: true,
    includeNotes: true,
    includeSubRows: !cmpB,
    maxRtp,
  });

  const controlsHtml =
    `<div class="payid-overview-controls">` +
    `<button type="button" class="payid-ctrl-btn" data-payid-action="expand-all">▾ ${_escHtml(fmt("payIdExpandAll"))}</button>` +
    `<button type="button" class="payid-ctrl-btn" data-payid-action="collapse-all">▸ ${_escHtml(fmt("payIdCollapseAll"))}</button>` +
    `</div>`;

  body.innerHTML =
    headerHtml + reviewBanner + flagsBanner + noShapeBanner +
    controlsHtml +
    `<table class="drilldown-table payid-overview-table">` +
    tableInner +
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

// ── Shared payout-row renderer ─────────────────────────────────────
//
// Shared by renderPayIdOverview (aggregate) and renderPayoutsBySpinType
// (per-ST view). Returns the <thead>...<tbody>... HTML for a payout-id
// table, using the same columns, i18n keys, and formatters as the
// aggregate panel. Callers wrap in <table class="...">.
//
// opts:
//   shapeByPayId  {Map|null}   — pay_id → shape row from /api/paytables shape
//   cmpBMap       {Map|null}   — pay_id → B-side payout row; null = single mode
//   cmpB          {bool}       — true when compare mode is active
//   bet           {number}     — A-side bet denominator for multiplier column
//   betB          {number}     — B-side bet denominator
//   includeShape      {bool}   — add Shape / Cols / Line columns (aggregate only)
//   includeNotes      {bool}   — add Notes column (aggregate only)
//   includeSubRows    {bool}   — render composition breakdown sub-rows
//   includeLiveSymbols {bool}  — add Symbol combo + Covered cols from live data (default true)
//   maxRtp            {number} — bar scale; 0 → computed from rows
function _renderPayoutRowsHtml(payoutRows, opts) {
  const {
    shapeByPayId = null,
    cmpBMap = null,
    cmpB = false,
    bet = 1000,
    betB = 1000,
    includeShape = true,
    includeNotes = true,
    includeSubRows = true,
    includeLiveSymbols = true,
  } = opts || {};
  let { maxRtp = 0 } = opts || {};

  // Schema fallback: pre-rename reports (rv_20260514T063337Z and earlier
  // testing artifacts) emit rtp_pp / hit_rate_pct. New reports emit
  // rtp_contribution_pp / hit_rate. Helper tolerates both so reports
  // generated across the refactor boundary still render.
  const _rtpOf = (r) => Number(r.rtp_contribution_pp ?? r.rtp_pp ?? 0);
  const _hitRateOf = (r) => Number(
    r.hit_rate ?? (r.hit_rate_pct != null ? r.hit_rate_pct / 100 : NaN),
  );

  if (maxRtp === 0) {
    maxRtp = Math.max(
      ...payoutRows.map(_rtpOf),
      ...(cmpBMap ? Array.from(cmpBMap.values()).map(_rtpOf) : []),
      0.001,
    );
  }

  // Local formatters — same semantics as the closures in renderPayIdOverview.
  const _fmtMult = (avgWin, betDenom) => {
    const m = Number(avgWin || 0) / (betDenom || bet);
    if (!Number.isFinite(m) || m === 0) return "—";
    return m >= 10 ? `${m.toFixed(1)}×` : `${m.toFixed(2)}×`;
  };
  const _fmtHitRate = (raw) => {
    if (!Number.isFinite(raw)) return "—";
    return raw < 0.001
      ? `${(raw * 100).toFixed(4)}%`
      : `${(raw * 100).toFixed(2)}%`;
  };
  const _catBadge = (cat) => {
    if (cat === "paid") return `<span class="pid-cat pid-cat-paid">${_escHtml(fmt("payIdCatPaid"))}</span>`;
    if (cat === "bonus") return `<span class="pid-cat pid-cat-bonus">${_escHtml(fmt("payIdCatBonus"))}</span>`;
    if (cat === "mixed") return `<span class="pid-cat pid-cat-mixed">${_escHtml(fmt("payIdCatMixed"))}</span>`;
    return `<span class="pid-cat pid-cat-unknown">—</span>`;
  };
  const _stack = (aVal, bVal, aRaw, bRaw, kind, digits) =>
    _cmpCell(!!cmpB, aVal, bVal, aRaw, bRaw, kind, digits);

  // thead — 7 base columns + optional live-symbol (2) + optional shape (3) + optional notes (1)
  const thead =
    `<thead><tr>` +
    `<th>${_escHtml(fmt("payIdCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdCatCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdPaidHitsCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdHitRateCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdMultCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdWinShareCol"))}</th>` +
    `<th>${_escHtml(fmt("payIdRtpCol"))}</th>` +
    (includeLiveSymbols
      ? `<th>${_escHtml(fmt("colSymbolCombo"))}</th>` +
        `<th>${_escHtml(fmt("colCoveredCols"))}</th>`
      : "") +
    (includeShape
      ? `<th>${_escHtml(fmt("payIdShapeCol"))}</th>` +
        `<th>${_escHtml(fmt("payIdColsCol"))}</th>` +
        `<th>${_escHtml(fmt("payIdLineCol"))}</th>`
      : "") +
    (includeNotes ? `<th>${_escHtml(fmt("payIdNotesCol"))}</th>` : "") +
    `</tr></thead>`;

  // tbody
  const tbody = payoutRows.map((pr) => {
    const pid = String(pr.payout_id);
    const prB = cmpB && cmpBMap ? (cmpBMap.get(pid) || null) : null;
    const shape = shapeByPayId ? (shapeByPayId.get(pid) || null) : null;
    const sh = shape && shape.shape ? shape.shape : {};

    // Shape columns (only populated when includeShape=true)
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

    const rtpPp = _rtpOf(pr);
    const rtpPpB = prB ? _rtpOf(prB) : 0;
    const aBar = Math.min(100, (rtpPp / maxRtp) * 100);
    const bBar = cmpB ? Math.min(100, (rtpPpB / maxRtp) * 100) : 0;
    const cat = pr.spin_type_category;
    const firesRaw = shape ? Number(shape.fires || 0) : null;
    const firesAttr = firesRaw != null
      ? ` title="rawdata fires: ${firesRaw.toLocaleString()} (script scan; includes bonus-round appearances)"`
      : "";

    const isBOnly = Boolean(pr._b_only);
    const mainMultA = isBOnly ? "—" : _fmtMult(pr.avg_win_when_hit, bet);
    const mainMultB = prB ? _fmtMult(prB.avg_win_when_hit, betB) : "—";

    // Composition sub-rows (only when includeSubRows=true and not compare mode)
    const breakdown = (includeSubRows && !cmpB && Array.isArray(sh.composition_breakdown))
      ? sh.composition_breakdown
      : (includeSubRows && !cmpB && Array.isArray(sh.wild_composition_breakdown)
        ? sh.wild_composition_breakdown
        : null);
    const hasBreakdown = breakdown && breakdown.length >= 2;
    let parentWinTotal = 0;
    if (hasBreakdown) {
      for (const b of breakdown) {
        parentWinTotal += Number(b.win_total || 0);
      }
    }
    const toggleIcon = hasBreakdown
      ? `<span class="payid-toggle" data-toggle-pid="${_escHtml(pid)}" role="button" title="展开 / 收起子组合">▸</span> `
      : `<span class="payid-toggle-spacer"></span>`;

    const isDeclaredOnly = Boolean(pr._declared_only);
    const declaredNote = isDeclaredOnly
      ? (pr._declared_grand_jackpot
          ? "未命中 · grand jackpot"
          : (pr._declared_rtp_excluded ? "未命中 · rtp_excluded" : "未命中"))
      : "";
    let cmpNote = "";
    if (cmpB) {
      if (isBOnly) cmpNote = `<span class="pid-presence-tag pid-presence-b">B only</span>`;
      else if (!prB) cmpNote = `<span class="pid-presence-tag pid-presence-a">A only</span>`;
    }
    const mainRowClassList = [
      hasBreakdown ? "payid-main payid-main-expandable" : "payid-main",
      isDeclaredOnly ? "payid-declared-only" : "",
      isBOnly ? "payid-b-only" : "",
    ].filter(Boolean).join(" ");

    const hitRateRaw = _hitRateOf(pr);
    const hitRateRawB = prB ? _hitRateOf(prB) : NaN;
    const hitRateA = (isDeclaredOnly || isBOnly || !Number.isFinite(hitRateRaw))
      ? "—"
      : _fmtHitRate(hitRateRaw);
    const hitRateB = prB ? _fmtHitRate(hitRateRawB) : "—";
    const hitCountRawA = isBOnly ? NaN : Number(pr.hit_count);
    const hitCountRawB = prB ? Number(prB.hit_count) : NaN;
    const hitCountA = isBOnly ? "—" : fInt(pr.hit_count);
    const hitCountB = prB ? fInt(prB.hit_count) : "—";
    const rtpCellA = isBOnly ? "—" : `${rtpPp.toFixed(2)}pp`;
    const rtpCellB = prB ? `${rtpPpB.toFixed(2)}pp` : "—";
    const rtpRawA = isBOnly ? NaN : rtpPp;
    const rtpRawB = prB ? rtpPpB : NaN;
    const multRawA = isBOnly ? NaN : Number(pr.avg_win_when_hit || 0) / bet;
    const multRawB = prB ? Number(prB.avg_win_when_hit || 0) / betB : NaN;
    const barCell = cmpB
      ? `<td class="cmp-text-bar-cell">${_cmpCell(true, rtpCellA, rtpCellB, rtpRawA, rtpRawB, "pp", 2, { aBarPct: aBar, bBarPct: bBar })}</td>`
      : `<td class="bar-cell" style="--bar:${aBar.toFixed(1)}%">${rtpPp.toFixed(2)}pp</td>`;

    // Live-symbol columns: symbol_combo.dominant + covered_columns from live data.
    // 1-indexed display for covered_columns so humans read "1,2,3" not "0,1,2".
    const liveCombo = pr.symbol_combo;
    const liveDominant = (liveCombo && liveCombo.dominant) ? _escHtml(liveCombo.dominant) : "—";
    const liveCovCols = Array.isArray(pr.covered_columns) && pr.covered_columns.length
      ? pr.covered_columns.map((c) => c + 1).join(",")
      : "—";
    // Phase B: symbol_combo.combos = full per-payid combo breakdown
    // [{combo,count,is_wild}]. Render as a native <details> (expand/collapse, no
    // JS wiring — same idiom as the wild-evidence panel) so wild-substituted
    // combos (flagged ⚡) split out from direct combos. Falls back to plain
    // dominant when combos absent (old reports).
    const liveCombos = (liveCombo && Array.isArray(liveCombo.combos)) ? liveCombo.combos : [];
    let comboCell = liveDominant;
    if (liveCombos.length) {
      const totalC = liveCombos.reduce((a, c) => a + (Number(c.count) || 0), 0) || 1;
      const items = liveCombos
        .map((c) => {
          const pct = (((Number(c.count) || 0) / totalC) * 100).toFixed(0);
          const wild = c.is_wild ? ` <span class="combo-wild" title="wild">⚡</span>` : "";
          return `<div class="combo-item">${_escHtml(String(c.combo || "?"))}` +
            ` <span class="combo-pct">${pct}%</span>${wild}</div>`;
        })
        .join("");
      comboCell = `<details class="combo-details"><summary>${liveDominant}</summary>${items}</details>`;
    }
    const liveSymbolCols = includeLiveSymbols
      ? `<td class="payid-symbol-combo">${comboCell}</td>` +
        `<td class="payid-covered-cols">${_escHtml(liveCovCols)}</td>`
      : "";

    // Extra columns that only appear in aggregate / shape-inclusive mode
    const shapeCols = includeShape
      ? `<td>${symDisplay}</td>` +
        `<td>${_escHtml(colStr)}</td>` +
        `<td>${lineBadge}</td>`
      : "";
    // Muted placeholders for sub-rows starting at the RTP bar column (col 7).
    // Total trailing muted = 1 (RTP) + 2×live-symbol + 3×shape + 1×notes when enabled.
    const subRowMutedCount = 1 + (includeLiveSymbols ? 2 : 0) + (includeShape ? 3 : 0) + (includeNotes ? 1 : 0);
    const noteCol = includeNotes
      ? `<td class="shape-notes">${cmpB ? cmpNote : (isDeclaredOnly ? _escHtml(declaredNote) : notes)}</td>`
      : "";

    const mainRow =
      `<tr class="${mainRowClassList}" data-pid="${_escHtml(pid)}">` +
      `<td>${toggleIcon}${_escHtml(pid)}</td>` +
      `<td>${_catBadge(cat)}</td>` +
      `<td${firesAttr}>${_stack(hitCountA, hitCountB, hitCountRawA, hitCountRawB, "rel")}</td>` +
      `<td class="payid-hitrate">${_stack(hitRateA, hitRateB, hitRateRaw * 100, hitRateRawB * 100, "pp", 2)}</td>` +
      `<td class="payid-mult">${_stack(mainMultA, mainMultB, multRawA, multRawB, "rel")}</td>` +
      `<td class="payid-winshare">—</td>` +
      barCell +
      liveSymbolCols +
      shapeCols +
      noteCol +
      `</tr>`;

    let subRows = "";
    if (hasBreakdown) {
      subRows = breakdown.map((b) => {
        const subMult = _fmtMult(b.avg_win, bet);
        const isAggregate = Boolean(b.is_aggregate_tail);
        const clsExtra = isAggregate ? " payid-subrow-aggregate" : "";
        const subWin = Number(b.win_total || 0);
        const winShareText = parentWinTotal > 0
          ? `${((subWin / parentWinTotal) * 100).toFixed(1)}%`
          : "—";
        // Trailing muted cells: 4 base (hitrate/mult/share/rtp) + shape cols + note col
        const trailingMuted = `<td class="payid-subrow-muted">—</td>`.repeat(subRowMutedCount);
        return (
          `<tr class="payid-subrow payid-subrow-collapsed${clsExtra}" data-parent-pid="${_escHtml(pid)}">` +
          `<td><span class="payid-subrow-indent">↳</span> <span class="payid-subrow-label">${_escHtml(b.label || "")}</span></td>` +
          `<td>${_catBadge(cat)}</td>` +
          `<td>${fInt(b.fires)}</td>` +
          // Hit-rate placeholder — sub-rows don't carry per-composition
          // hit rate; em-dash keeps column count aligned with main rows.
          `<td class="payid-subrow-muted">—</td>` +
          `<td class="payid-mult">${subMult}</td>` +
          `<td class="payid-winshare">${winShareText}</td>` +
          trailingMuted +
          `</tr>`
        );
      }).join("");
    }
    return mainRow + subRows;
  }).join("");

  return thead + `<tbody>${tbody}</tbody>`;
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

// ── Per-pay_id by SpinType ─────────────────────────────────────────
//
// Renders one sub-table per spin_type_label found in
// summary.player_impact.payouts_by_spin_type. Each row:
//   payout_id | hit_count | hit_rate | avg_win_when_hit | rtp_contribution_pp
// sorted by rtp_contribution_pp descending, capped at top 20 per label.
// Uses the same _renderPayoutRowsHtml helper as renderPayIdOverview so
// column set, i18n keys, and formatters are shared (no parallel impl).
//
// SpinType label keys are dynamic (ST43_paid / ST1_paid / etc.) —
// never hardcoded; derived from Object.keys() of the data object.
//
// Compare mode: if cmpB has the field, show A and B tables side-by-
// side per spin_type_label. If a label only exists on one side, it
// renders with an "(A only)" or "(B only)" note in the heading.
// If the whole field is absent from B, a single "B has no ST-split
// data" note is shown instead of a B panel.
//
// Graceful degradation: if the field is missing / empty on A (older
// reports pre-field-rename), the panel is hidden entirely.

// Format a spin_type_label string (e.g. "ST43_paid") into a human-readable
// heading. Parses "ST{N}_{behavior}" and substitutes the behavior token via
// i18n. Falls back to _escHtml(label) unchanged for unrecognised formats so
// unknown labels never crash the renderer.
function _formatSpinTypeLabel(label) {
  const m = /^ST(\d+)_(paid|free|mixed)$/.exec(label);
  if (!m) return _escHtml(label);
  const stNum = m[1];
  const behavior = m[2];
  const behaviorKey = "spinTypeBehavior" + behavior.charAt(0).toUpperCase() + behavior.slice(1);
  return `SpinType ST${_escHtml(stNum)} · ${_escHtml(fmt(behaviorKey))}`;
}

// (renderPayoutsBySpinType removed — the per-ST payid breakdown is now the
//  "payid dimension" inside renderSpinTypeOutcomes' per-SpinType sections,
//  built from the same shared _renderPayoutRowsHtml.)

// ── Per-reel Marginal by SpinType ──────────────────────────────────
//
// Renders one block per spin_type_label in
// summary.player_impact.reel_marginal_by_spin_type. Each block shows
// one table per reel column (side-by-side via the existing
// .symbol-matrix / .col-table layout). Columns: symbol | count | prob_pct.
// Rows sorted by prob_pct descending within each reel.
//
// Compare mode: if cmpB has the field, each spin_type_label block
// shows A reels then B reels with an A/B sub-heading. If only A
// has the field, renders A-only and notes "B has no ST-split data".
//
// Graceful degradation: hidden entirely when field missing/empty on A.
function renderReelMarginalBySpinType(summary) {
  const panel = byId("reelMarginalBySpinTypePanel");
  if (!panel) return;

  const cmpB = state.compareMode && state.compareMode.b ? state.compareMode.b : null;
  const aData = ((summary || {}).player_impact || {}).reel_marginal_by_spin_type || null;
  const bData = cmpB ? ((cmpB.player_impact || {}).reel_marginal_by_spin_type || null) : null;

  const aLabels = aData ? Object.keys(aData) : [];
  const bLabels = bData ? Object.keys(bData) : [];
  const hasA = aLabels.length > 0;
  const hasB = bLabels.length > 0;

  if (!hasA && !hasB) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");

  const body = byId("reelMarginalBySpinTypeBody");
  if (!body) return;

  const aLabelSet = new Set(aLabels);
  const allLabels = [...aLabels];
  for (const lb of bLabels) {
    if (!aLabelSet.has(lb)) allLabels.push(lb);
  }

  const bOnlyNote = (cmpB && !hasB)
    ? `<p class="drilldown-hint">B has no ST-split data (pre-729a6ca report).</p>`
    : "";

  let html = bOnlyNote;

  for (const label of allLabels) {
    const aColMap = aData ? (aData[label] || {}) : {};
    const bColMap = bData ? (bData[label] || {}) : {};
    const onlyA = Object.keys(aColMap).length > 0 && Object.keys(bColMap).length === 0;
    const onlyB = Object.keys(aColMap).length === 0 && Object.keys(bColMap).length > 0;

    let presenceTag = "";
    if (cmpB) {
      if (onlyA) presenceTag = ` <span class="pid-presence-tag pid-presence-a">A only</span>`;
      else if (onlyB) presenceTag = ` <span class="pid-presence-tag pid-presence-b">B only</span>`;
    }

    html += `<h3 class="drilldown-subhead">${_formatSpinTypeLabel(label)}${presenceTag}</h3>`;

    if (cmpB && bData !== null) {
      html += `<p class="drilldown-hint">A</p>`;
      html += _renderReelMarginalMatrix(aColMap);
      html += `<p class="drilldown-hint">B</p>`;
      html += _renderReelMarginalMatrix(bColMap);
    } else {
      html += _renderReelMarginalMatrix(aColMap);
    }
  }

  body.innerHTML = html;
}

// ── Shared reel-column renderer ────────────────────────────────────
//
// Shared by renderSymbolDrilldown (aggregate by-col matrix) and
// renderReelMarginalBySpinType (per-ST reel matrix). Produces one
// <div class="col-table"> block for a single reel column.
//
// rows: [{symbol, count, rate_pct|prob_pct}] — normalises either
//   field name to a window-rate percentage for display.
// opts:
//   colId        {string}       — column index label (e.g. "0")
//   headerLabel  {string}       — pre-formatted <h4> text (HTML-safe)
//   rowsB        {array|null}   — B-side rows for compare mode
//   paylineMap   {object|null}  — {symbol: {rate_pct}} for payline col
//   paylineMapB  {object|null}  — B-side payline map
//   cmpB         {bool}         — compare mode active
//   includePayline {bool}       — add payline-rate column (4th col)
function _renderReelColumnHtml(rows, opts) {
  const {
    colId = "0",
    headerLabel = null,
    rowsB = null,
    paylineMap = null,
    paylineMapB = null,
    cmpB = false,
    includePayline = false,
  } = opts || {};

  // Normalise rate field: aggregate uses rate_pct, ST-split uses prob_pct.
  const _ratePct = (r) => Number(r.rate_pct ?? r.prob_pct ?? 0);

  const aSymSet = new Set((rows || []).map((r) => String(r.symbol)));
  const bMapLocal = new Map();
  for (const r of (rowsB || [])) bMapLocal.set(String(r.symbol), r);
  const merged = [...(rows || [])];
  if (cmpB) {
    for (const r of (rowsB || [])) {
      if (!aSymSet.has(String(r.symbol))) merged.push(r);
    }
  }
  const max = Math.max(
    ...merged.map((r) => r.count || 0),
    ...(cmpB ? (rowsB || []).map((r) => r.count || 0) : []),
    0,
  );

  const paylineUnavailable = fmt("paylineRateUnavailable");
  const body = merged
    .map((r) => {
      const aIn = aSymSet.has(String(r.symbol));
      const bRow = cmpB ? bMapLocal.get(String(r.symbol)) : null;
      const aCountRaw = aIn ? Number(r.count || 0) : NaN;
      const bCountRaw = bRow ? Number(bRow.count || 0) : NaN;
      const aRateRaw = aIn ? _ratePct(r) : NaN;
      const bRateRaw = bRow ? _ratePct(bRow) : NaN;
      const aCountFmt = aIn ? fInt(r.count) : "—";
      const bCountFmt = bRow ? fInt(bRow.count) : "—";
      const aRateFmt = aIn ? _ratePct(r).toFixed(2) + "%" : "—";
      const bRateFmt = bRow ? _ratePct(bRow).toFixed(2) + "%" : "—";
      const aBar = max > 0 ? Math.min(100, ((aIn ? r.count : 0) / max) * 100) : 0;
      const bBar = cmpB && max > 0 ? Math.min(100, ((bRow ? bRow.count : 0) / max) * 100) : 0;
      const barCell = cmpB
        ? `<td class="cmp-text-bar-cell">${_cmpCell(true, aCountFmt, bCountFmt, aCountRaw, bCountRaw, "rel", 0, { aBarPct: aBar, bBarPct: bBar })}</td>`
        : `<td class="bar-cell" style="--bar:${aBar.toFixed(1)}%">${aCountFmt}</td>`;
      let symCell = `<code>${_escHtml(String(r.symbol))}</code>`;
      if (cmpB) {
        if (aIn && !bRow) symCell += ` <span class="pid-presence-tag pid-presence-a">A only</span>`;
        else if (!aIn && bRow) symCell += ` <span class="pid-presence-tag pid-presence-b">B only</span>`;
      }
      const plCols = includePayline
        ? (() => {
            const plEntryA = paylineMap ? paylineMap[r.symbol] : null;
            const plEntryB = cmpB && paylineMapB ? paylineMapB[r.symbol] : null;
            const aPlFmt = plEntryA ? plEntryA.rate_pct.toFixed(2) + "%" : paylineUnavailable;
            const bPlFmt = plEntryB ? plEntryB.rate_pct.toFixed(2) + "%" : paylineUnavailable;
            const aPlRaw = plEntryA ? Number(plEntryA.rate_pct) : NaN;
            const bPlRaw = plEntryB ? Number(plEntryB.rate_pct) : NaN;
            return `<td>${_cmpCell(!!cmpB, aPlFmt, bPlFmt, aPlRaw, bPlRaw, "pp", 2)}</td>`;
          })()
        : "";
      return (
        `<tr>` +
        `<td>${symCell}</td>` +
        barCell +
        `<td>${_cmpCell(!!cmpB, aRateFmt, bRateFmt, aRateRaw, bRateRaw, "pp", 2)}</td>` +
        plCols +
        `</tr>`
      );
    })
    .join("");

  const head =
    `<thead><tr>` +
    `<th>${fmt("thSymbol")}</th>` +
    `<th>${fmt("thCount")}</th>` +
    `<th>${fmt("thRate")}</th>` +
    (includePayline ? `<th>${fmt("thRatePayline")}</th>` : "") +
    `</tr></thead>`;
  const h4 = headerLabel != null
    ? headerLabel
    : `${_escHtml(fmt("reelColPrefix"))} ${_escHtml(String(colId))}`;
  return (
    `<div class="col-table">` +
    `<h4>${h4}</h4>` +
    `<table class="drilldown-table">${head}<tbody>${body}</tbody></table>` +
    `</div>`
  );
}

// Build the reel-matrix HTML for one spin_type_label's colMap.
// colMap: { "0": [{symbol, count, prob_pct}, ...], "1": [...], ... }
// Reel columns are sorted numerically. Within each column, rows are
// sorted by prob_pct descending. Uses _renderReelColumnHtml so layout
// matches the aggregate by-column matrix in renderSymbolDrilldown.
function _renderReelMarginalMatrix(colMap) {
  const colKeys = Object.keys(colMap).sort((a, b) => Number(a) - Number(b));
  if (!colKeys.length) {
    return `<p class="drilldown-hint">— no reel data —</p>`;
  }
  const colHtml = colKeys
    .map((colIdx) => {
      const rows = [...(colMap[colIdx] || [])]
        .sort((a, b) => Number(b.prob_pct || 0) - Number(a.prob_pct || 0));
      return _renderReelColumnHtml(rows, {
        colId: colIdx,
        headerLabel: null,  // default: "列 N"
        rowsB: null,
        paylineMap: null,
        paylineMapB: null,
        cmpB: false,
        includePayline: false,
      });
    })
    .join("");
  return `<div class="symbol-matrix">${colHtml}</div>`;
}

// Build the per-feature bucket histogram as a standard drilldown-
// table so typography + bar line match the global 倍率分布 panel
// byte-for-byte. Columns: 倍率区间 / 次数 / 占比 / 本类 pp / bar.
// The pp values slice the GLOBAL RTP denominator (see analyzer
// note) so summing a feature's bucket pp = that feature's header
// pp (e.g. LockSymbolFreespin buckets sum to its 41.18pp header).
// Skips buckets with zero spins on BOTH sides. Returns "" when
// nothing to show.
//
// Compare mode (``bucketsB`` non-null): align bucket rows by name,
// canonical order from A first then B-only appended. Each metric
// cell stacks A on top + B underneath; the bar cell uses
// ``bar-cell-cmp`` with --bar (A) and --bar-b (B) custom props
// scaled to the union max RTP across both sides.
function _renderFeatureBucketTable(buckets, bucketsB) {
  const aArr = Array.isArray(buckets) ? buckets : [];
  const bArr = Array.isArray(bucketsB) ? bucketsB : [];
  const compareMode = bucketsB != null;
  if (!aArr.length && !bArr.length) return "";

  // Map B by bucket name for alignment.
  const bMap = new Map();
  for (const r of bArr) bMap.set(String(r.bucket || ""), r);
  const aSet = new Set(aArr.map((r) => String(r.bucket || "")));
  // Filter zero rows: keep a row if EITHER side has non-zero spins.
  const aRows = aArr.filter((b) => {
    if (Number(b.spin_count || 0) > 0) return true;
    if (compareMode) {
      const bRow = bMap.get(String(b.bucket || ""));
      if (bRow && Number(bRow.spin_count || 0) > 0) return true;
    }
    return false;
  });
  // B-only rows (not present in A).
  const bOnlyRows = compareMode
    ? bArr.filter((r) => !aSet.has(String(r.bucket || "")) && Number(r.spin_count || 0) > 0)
    : [];
  const merged = [...aRows, ...bOnlyRows];
  if (!merged.length) return "";

  const maxRtp = Math.max(
    ...merged.map((b) => Math.abs(Number(b.rtp_contribution_pp || 0))),
    ...(compareMode
      ? merged.map((b) => Math.abs(Number((bMap.get(String(b.bucket || "")) || {}).rtp_contribution_pp || 0)))
      : []),
    0.001,
  );

  const _stack = (aVal, bVal, aRaw, bRaw, kind, digits) =>
    _cmpCell(compareMode, aVal, bVal, aRaw, bRaw, kind, digits);

  const body = merged.map((b) => {
    const label = PURE.prettyBucketLabel(b.bucket);
    // 2026-05-12: 同前页 bucketTable 的 fix —— merged 里 B-only 行
    // 的迭代变量 b 是 B 的桶,不能直接读做 A 字段。
    const aIn = aSet.has(String(b.bucket || ""));
    const aCount = aIn ? Number(b.spin_count || 0) : NaN;
    const aRateRaw = aIn ? Number(b.spin_rate || 0) * 100 : NaN;
    const aRate = aIn ? aRateRaw.toFixed(2) + "%" : "—";
    const aRtpPp = aIn ? Number(b.rtp_contribution_pp || 0) : NaN;
    const aRtpPpFmt = aIn ? aRtpPp.toFixed(2) + "pp" : "—";
    const aCountFmt = aIn ? aCount.toLocaleString() : "—";
    const aBar = aIn ? Math.min(100, (Math.abs(aRtpPp) / maxRtp) * 100) : 0;
    const bRow = compareMode ? (bMap.get(String(b.bucket || "")) || {}) : null;
    const bCount = bRow ? Number(bRow.spin_count || 0) : 0;
    const bRateRaw = bRow ? Number(bRow.spin_rate || 0) * 100 : 0;
    const bRate = bRateRaw.toFixed(2);
    const bRtpPp = bRow ? Number(bRow.rtp_contribution_pp || 0) : 0;
    const bBar = compareMode ? Math.min(100, (Math.abs(bRtpPp) / maxRtp) * 100) : 0;
    const barCell = compareMode
      ? `<td class="bar-cell bar-cell-cmp" style="--bar:${aBar.toFixed(1)}%;--bar-b:${bBar.toFixed(1)}%"></td>`
      : `<td class="bar-cell" style="--bar:${aBar.toFixed(1)}%"></td>`;
    return (
      `<tr>` +
      `<td>${_escHtml(label)}</td>` +
      `<td>${_stack(aCountFmt, bCount.toLocaleString(), aCount, bCount, "rel")}</td>` +
      `<td>${_stack(aRate, bRate + "%", aRateRaw, bRateRaw, "pp")}</td>` +
      `<td>${_stack(aRtpPpFmt, bRtpPp.toFixed(2) + "pp", aRtpPp, bRtpPp, "pp", 2)}</td>` +
      barCell +
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

  // Compare mode: pull B's feature breakdown so each paying card can
  // stack A/B headlines + dual-axis bucket histograms. The orphan
  // trigger chip row uses A's orphans only — those are upstream-
  // structural and shouldn't differ between mode 1/7 of the same
  // machine; if they DO differ that's a schema drift signal we
  // surface separately via the field-discovery panel.
  const cmpB = state.compareMode && state.compareMode.b ? state.compareMode.b : null;
  const dataB = cmpB ? (cmpB.player_impact || {}).upstream_feature_breakdown : null;

  const aHasFeatures = data && data.applicable && Array.isArray(data.features) && data.features.length;
  const bHasFeatures = dataB && dataB.applicable && Array.isArray(dataB.features) && dataB.features.length;
  if (!aHasFeatures && !bHasFeatures) {
    body.innerHTML = "";
    return;
  }

  // Helper: split a feature breakdown into paying + trigger-only and
  // build the multi-chain breadcrumb resolver. Same logic as before
  // but factored so we can call it independently for A and B and
  // pair the resulting paying-feature lists by feature_name. The
  // chain resolution is intentionally A-side only — chain structure
  // is upstream config, not RTP-side luck, so showing A's chain on
  // every paired card keeps the panel readable and avoids two-chain
  // diff fatigue (mode 1 vs mode 7 of same machine should have the
  // same upstream chain anyway).
  function _splitAndChain(featuresList) {
    const triggerOnly = featuresList.filter((f) => Boolean(f.trigger_only));
    const paying = featuresList.filter((f) => !f.trigger_only);
    const absorbed = new Set();
    function chainsInto(payingName) {
      const chains = [];
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
        chains.push(rev.reverse());
      }
      return chains;
    }
    return { paying, triggerOnly, chainsInto, absorbed };
  }

  const aSplit = aHasFeatures ? _splitAndChain(data.features) : { paying: [], triggerOnly: [], chainsInto: () => [], absorbed: new Set() };
  const bSplit = bHasFeatures ? _splitAndChain(dataB.features) : { paying: [], triggerOnly: [], chainsInto: () => [], absorbed: new Set() };

  // Pair paying features by name. Ordering: A's order first (so the
  // single-mode visual rank is preserved), then B-only at the end.
  const bPayingByName = new Map();
  for (const f of bSplit.paying) bPayingByName.set(f.feature_name, f);
  const aNames = new Set(aSplit.paying.map((f) => f.feature_name));
  const merged = aSplit.paying.map((aFeat) => ({
    name: aFeat.feature_name,
    a: aFeat,
    b: cmpB ? (bPayingByName.get(aFeat.feature_name) || null) : null,
    chains: aSplit.chainsInto(aFeat.feature_name),
  }));
  if (cmpB) {
    for (const bFeat of bSplit.paying) {
      if (aNames.has(bFeat.feature_name)) continue;
      merged.push({
        name: bFeat.feature_name,
        a: null,
        b: bFeat,
        // Use B's chain resolver since A doesn't even know about
        // this feature. Avoids "—" chain on a B-only card.
        chains: bSplit.chainsInto(bFeat.feature_name),
      });
    }
  }

  const payingCards = merged.map((row) => {
    return _renderPayingFeatureCard(row.a, row.chains, row.b);
  }).join("");

  // Orphan trigger row: keep A's view (chain structure is upstream
  // config, doesn't drift). In B-only mode (no A breakdown at all)
  // fall through to B's orphans.
  const orphanSrc = aHasFeatures ? aSplit : bSplit;
  const orphans = orphanSrc.triggerOnly.filter((t) => !orphanSrc.absorbed.has(t.feature_name));
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
//
// Compare mode (``bFeat`` non-null): the rtp/share metric in the
// header + fires/rate in the meta line stack A on top + B
// underneath. The bucket histogram becomes A/B-aware via
// _renderFeatureBucketTable. Sub-streams render only A's path —
// in compare we hide them since per-stream A/B at the trigger-
// path level is too noisy to read inside a card.
//
// When A is missing (B-only feature), feat is null — pull header
// + meta from bFeat and tag the card "[B only]".
function _renderPayingFeatureCard(feat, chains, bFeat) {
  const haveA = feat != null;
  const haveB = bFeat != null;
  // compareMode is keyed off state.compareMode so A-only cards (where
  // haveB === false but the panel itself is in compare mode) still
  // emit the "A only" presence tag and stacked-cell layout. Earlier
  // version inferred compareMode from haveB which silently dropped
  // the tag on A-only cards.
  const compareMode = !!(state && state.compareMode);
  // Resolve a "primary" record we read non-metric fields (name,
  // chain) from. When A is missing fall back to B so we still have
  // a name + chain to display.
  const primary = haveA ? feat : bFeat;

  const _toFixed = (rec, key, digits, suffix) => {
    if (!rec) return "—";
    const n = Number(rec[key] || 0);
    return n.toFixed(digits) + (suffix || "");
  };
  const _pctOf = (rec, key, digits) => {
    if (!rec) return "—";
    const n = Number(rec[key] || 0) * 100;
    return n.toFixed(digits) + "%";
  };
  const _intLocale = (rec, fallbackKey) => {
    if (!rec) return "—";
    const n = Number(rec.fires_spins || rec[fallbackKey] || 0);
    return n.toLocaleString();
  };

  const rtpA = _toFixed(feat, "rtp_contribution_pp", 2, "pp");
  const rtpB = _toFixed(bFeat, "rtp_contribution_pp", 2, "pp");
  const shareA = _pctOf(feat, "share_of_total_win", 1);
  const shareB = _pctOf(bFeat, "share_of_total_win", 1);
  const firesA = _intLocale(feat, "total_times");
  const firesB = _intLocale(bFeat, "total_times");
  const rateA = _pctOf(feat, "fire_rate", 2);
  const rateB = _pctOf(bFeat, "fire_rate", 2);
  // Raw values for Δ chips. The header carries one chip on
  // rtp_pp (the dominant metric — share_of_total_win is just a
  // ratio of the same number). The meta line carries one chip
  // on fires_spins (count → relative %).
  const rtpRawA = haveA ? Number(feat.rtp_contribution_pp || 0) : NaN;
  const rtpRawB = haveB ? Number(bFeat.rtp_contribution_pp || 0) : NaN;
  const firesRawA = haveA ? Number(feat.fires_spins || feat.total_times || 0) : NaN;
  const firesRawB = haveB ? Number(bFeat.fires_spins || bFeat.total_times || 0) : NaN;

  const bucketsA = haveA && Array.isArray(feat.bucket_distribution) ? feat.bucket_distribution : [];
  const bucketsB = haveB && Array.isArray(bFeat.bucket_distribution) ? bFeat.bucket_distribution : [];
  const bucketTableHtml = _renderFeatureBucketTable(bucketsA, compareMode ? bucketsB : null);
  const subStreams = haveA && Array.isArray(feat.sub_streams) ? feat.sub_streams : [];
  // In compare mode, hide sub-streams (per-trigger-path A/B becomes
  // unreadable inside an already-dense card). Single mode unchanged.
  const subStreamsHtml = compareMode ? "" : _renderFeatureSubStreams(subStreams);

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

  // Presence tag: only meaningful in compare mode. "Both sides
  // present" = no tag; "A only" = card came from A and B has no
  // matching feature; "B only" = card synthesized from B-only.
  let presenceTag = "";
  if (compareMode) {
    if (haveA && !haveB) presenceTag = ` <span class="feature-presence-tag feature-presence-a">A only</span>`;
    else if (!haveA && haveB) presenceTag = ` <span class="feature-presence-tag feature-presence-b">B only</span>`;
  }

  // Header + meta: A/B stacked in compare mode, plain in single
  // mode. Δ chip rides on rtp_pp (header) and fires_spins (meta)
  // — the two dominant metrics. Share % and fire rate are derived
  // from the same numerator so a second chip there would just
  // duplicate the same direction signal.
  const headerMetric = _cmpCell(
    compareMode,
    `${rtpA} · ${shareA}`,
    `${rtpB} · ${shareB}`,
    rtpRawA, rtpRawB, "pp", 2,
  );
  const metaLine = _cmpCell(
    compareMode,
    `fires ${firesA}× · ${rateA} of spins`,
    `fires ${firesB}× · ${rateB} of spins`,
    firesRawA, firesRawB, "rel",
  );

  return (
    `<div class="feature-block">` +
    `<h3>${_escHtml(String(primary.feature_name))}${presenceTag} <span class="feature-metric">${headerMetric}</span></h3>` +
    `<div class="feature-meta">${metaLine}</div>` +
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
  // Compare-aware: if a B summary is available, pull its tiers + sim
  // metadata so each tier card can stack A/B headlines + histogram
  // rows. When compareMode is null all the cmpB* values stay null and
  // every render branch falls through to the original single-render
  // path — the panel is byte-identical in single mode.
  const cmpB = state.compareMode && state.compareMode.b ? state.compareMode.b : null;
  const cmpBSim = cmpB ? (cmpB.player_impact || {}).bankruptcy_simulation : null;
  const cmpBTiers = cmpBSim && Array.isArray(cmpBSim.tiers) ? cmpBSim.tiers : [];
  const cmpBMap = new Map();
  for (const t of cmpBTiers) cmpBMap.set(Number(t.bankroll_multiplier), t);
  // Union of tiers: A's order first, then B-only (different bankroll
  // tiers configured between the two reports — shouldn't happen for
  // same-machine same-mode but we tolerate it for cross-mode compare).
  const aMults = new Set(tiers.map((t) => Number(t.bankroll_multiplier)));
  const mergedTiers = [...tiers];
  if (cmpB) {
    for (const t of cmpBTiers) {
      if (!aMults.has(Number(t.bankroll_multiplier))) mergedTiers.push(t);
    }
  }
  const anyData = mergedTiers.some(
    (t) => Number(t?.robots || 0) > 0,
  ) || (cmpBTiers.some((t) => Number(t?.robots || 0) > 0));
  if (!anyData) {
    panel.classList.add("hidden");
    body.innerHTML = "";
    return;
  }
  panel.classList.remove("hidden");

  const sessionSpins = Number((sim && sim.session_spins) || (cmpBSim && cmpBSim.session_spins) || 10000);
  // Decile percentiles (P10, P20, ..., P90) come pre-computed from the
  // analyzer with denominator = ALL simulated sessions in the tier.
  const percentileKeys = Array.isArray(sim && sim.percentile_keys) && sim.percentile_keys.length
    ? sim.percentile_keys.map((v) => Number(v))
    : (Array.isArray(cmpBSim && cmpBSim.percentile_keys) && cmpBSim.percentile_keys.length
      ? cmpBSim.percentile_keys.map((v) => Number(v))
      : [10, 20, 30, 40, 50, 60, 70, 80, 90]);

  const intro = `<p class="bankruptcy-intro">${_escHtml(
    fmt("bankruptcyIntro", { session: sessionSpins })
  )}</p>`;

  // Helper: A/B stacked cell + Δ chip in compare mode; plain text
  // in single mode. ``aRaw`` / ``bRaw`` drive the Δ chip when both
  // numeric. ``kind`` selects 'pp' (rate / percent values) or
  // 'rel' (counts / spins).
  const _stack = (aVal, bVal, aRaw, bRaw, kind, digits) =>
    _cmpCell(!!cmpB, aVal, bVal, aRaw, bRaw, kind, digits);

  const cards = mergedTiers.map((t) => {
    const mult = Number(t.bankroll_multiplier || 0);
    // Map A's tier to its B counterpart by bankroll multiplier. If
    // either side is missing for this tier, fall back to an empty
    // record so .robots / .bankruptcy_rate read 0 and the cell
    // renders "—".
    const tA = aMults.has(mult) ? t : null;
    const tB = cmpB ? cmpBMap.get(mult) || null : null;

    const _v = (rec, k) => rec ? Number(rec[k] || 0) : 0;
    const _has = (rec) => rec && Number(rec.robots || 0) > 0;

    const sessionsA = _v(tA, "robots");
    const sessionsB = _v(tB, "robots");
    const survivedA = _v(tA, "completed_robots");
    const survivedB = _v(tB, "completed_robots");
    const rateA = _v(tA, "bankruptcy_rate");
    const rateB = _v(tB, "bankruptcy_rate");
    const medianA = _v(tA, "median_spins_completed");
    const medianB = _v(tB, "median_spins_completed");
    const fastestA = tA && tA.fastest_bankruptcy_spins != null ? Number(tA.fastest_bankruptcy_spins) : null;
    const fastestB = tB && tB.fastest_bankruptcy_spins != null ? Number(tB.fastest_bankruptcy_spins) : null;
    const pctMapA = (tA && tA.percentiles && typeof tA.percentiles === "object") ? tA.percentiles : {};
    const pctMapB = (tB && tB.percentiles && typeof tB.percentiles === "object") ? tB.percentiles : {};

    // Bar scale: take the max across both sides + sessionSpins so A
    // and B bars share a common scale within the tier. Single mode:
    // same as before since pctValuesB === [].
    const pctValuesA = percentileKeys.map((k) =>
      Number(pctMapA[String(k)] != null ? pctMapA[String(k)] : pctMapA[k] || 0),
    );
    const pctValuesB = cmpB
      ? percentileKeys.map((k) =>
          Number(pctMapB[String(k)] != null ? pctMapB[String(k)] : pctMapB[k] || 0))
      : [];
    const maxSpin = Math.max(sessionSpins, ...pctValuesA, ...pctValuesB, 0.001);

    // Fastest row: highlighted separately at the top. Rendered even
    // when null (shows "—") so the row layout stays aligned across
    // tiers.
    const fastestRow = (() => {
      const barA = fastestA == null ? 0 : Math.min(100, (fastestA / maxSpin) * 100);
      const barB = fastestB == null ? 0 : Math.min(100, (fastestB / maxSpin) * 100);
      const spinTextA = fastestA == null ? "—" : Math.round(fastestA).toLocaleString();
      const spinTextB = fastestB == null ? "—" : Math.round(fastestB).toLocaleString();
      const barCell = cmpB
        ? `<td class="bar-cell bar-cell-cmp" style="--bar:${barA.toFixed(1)}%;--bar-b:${barB.toFixed(1)}%"></td>`
        : `<td class="bar-cell" style="--bar:${barA.toFixed(1)}%"></td>`;
      // Fastest row: spin counts → relative %.
      const fastA = fastestA == null ? NaN : fastestA;
      const fastB = fastestB == null ? NaN : fastestB;
      return (
        `<tr class="bk-row-fastest">` +
        `<td>${_escHtml(fmt("bankruptcyFastestLabel"))}</td>` +
        `<td>${_stack(spinTextA, spinTextB, fastA, fastB, "rel")}</td>` +
        barCell +
        `</tr>`
      );
    })();

    // Decile rows: each shows "at this percentile of ALL users, how
    // many spins did they get?". Once cumulative mass passes bankrupt
    // share, percentile pins to session_spins — the transition row
    // visually coincides with the survival rate.
    const pctRows = percentileKeys.map((p) => {
      const spinA = Number(pctMapA[String(p)] != null ? pctMapA[String(p)] : pctMapA[p] || 0);
      const spinB = cmpB
        ? Number(pctMapB[String(p)] != null ? pctMapB[String(p)] : pctMapB[p] || 0)
        : 0;
      const barA = Math.min(100, (spinA / maxSpin) * 100);
      const barB = cmpB ? Math.min(100, (spinB / maxSpin) * 100) : 0;
      // Row tone: in single mode use A's survival; in compare mode
      // class survives if EITHER side reached sessionSpins (the row
      // is "above the bankruptcy mass" for that side at least).
      const isSurvived = cmpB
        ? (spinA >= sessionSpins && spinB >= sessionSpins)
        : (spinA >= sessionSpins);
      const cls = isSurvived ? "bk-row-survived" : "bk-row-bankrupt";
      const barCell = cmpB
        ? `<td class="bar-cell bar-cell-cmp" style="--bar:${barA.toFixed(1)}%;--bar-b:${barB.toFixed(1)}%"></td>`
        : `<td class="bar-cell" style="--bar:${barA.toFixed(1)}%"></td>`;
      return (
        `<tr class="${cls}">` +
        `<td>P${p}</td>` +
        `<td>${_stack(spinA.toLocaleString(), spinB.toLocaleString(), spinA, spinB, "rel")}</td>` +
        barCell +
        `</tr>`
      );
    }).join("");

    // Headline KPIs: A on top + B underneath when comparing.
    const rateAStr = (rateA * 100).toFixed(1) + "%";
    const rateBStr = (rateB * 100).toFixed(1) + "%";
    const medianAStr = medianA.toLocaleString();
    const medianBStr = medianB.toLocaleString();
    const survAStr = sessionsA > 0 ? ((survivedA / sessionsA) * 100).toFixed(1) + "%" : "0.0%";
    const survBStr = sessionsB > 0 ? ((survivedB / sessionsB) * 100).toFixed(1) + "%" : "0.0%";

    // Tier header: in compare mode, mark "[A only]" / "[B only]" if
    // one side has no sessions at this multiplier — the histogram
    // and KPIs will show "—" but the operator immediately sees why.
    let presenceTag = "";
    if (cmpB) {
      if (_has(tA) && !_has(tB)) presenceTag = ` <span class="bk-presence-tag bk-presence-a">A only</span>`;
      else if (!_has(tA) && _has(tB)) presenceTag = ` <span class="bk-presence-tag bk-presence-b">B only</span>`;
    }

    return (
      `<div class="bankruptcy-tier">` +
      `<h3 class="bankruptcy-tier-head">${_escHtml(
        fmt("bankruptcyTierLabel", { mult })
      )}${presenceTag}</h3>` +
      `<div class="bankruptcy-tier-stats">` +
      // bankruptcy_rate / survived %: already in 0–1 → render in pp scale.
      // median spins: count → relative %.
      `<span class="bk-stat bk-stat-rate"><em>${_escHtml(fmt("bankruptcyRateLabel"))}</em><b>${_stack(rateAStr, rateBStr, rateA * 100, rateB * 100, "pp")}</b></span>` +
      `<span class="bk-stat"><em>${_escHtml(fmt("bankruptcyMedianLabel"))}</em><b>${_stack(medianAStr, medianBStr, medianA, medianB, "rel")}</b></span>` +
      `<span class="bk-stat"><em>${_escHtml(fmt("bankruptcySurvivedLabel"))}</em><b>${_stack(survAStr, survBStr, sessionsA > 0 ? (survivedA / sessionsA) * 100 : NaN, sessionsB > 0 ? (survivedB / sessionsB) * 100 : NaN, "pp")}</b></span>` +
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
  // If a previously-saved pref is an old 3-tier string (pre-10x era), map it
  // to the matching new 4-tier preset so the operator's setting survives the
  // 2026-04-22 10x-prepend change. Fall through to Standard otherwise.
  const _legacyPrevMap = {
    "100,200,500": "10,100,200,500",
    "50,100,200": "10,50,100,200",
    "200,500,1000": "10,200,500,1000",
  };
  const mapped = prev && _legacyPrevMap[prev] ? _legacyPrevMap[prev] : prev;
  sel.value = mapped || "10,100,200,500";
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
  const fixable = body.fixable_count || 0;
  const needsRawdata = body.needs_rawdata_count || 0;
  const analyzerShort = (body.current_analyzer_version || "").slice(0, 10) || "—";

  // Report 管理 banner is report-scope only (2026-04-21). "Rawdata
  // 过期" used to live here too but rawdata doesn't expire — md5 is
  // a tag, not a destruction signal (f5d8787); the per-mode "历史
  // md5" cell in rwtree is where operators manage different rawdata
  // versions. Keep this banner focused on analyzer staleness.
  banner.classList.remove("hidden");
  let staleText;
  if (staleAnalyzer === 0) {
    staleText = `<span class="report-mgmt-ok">✓ 全 fleet analyzer 均最新</span>`;
  } else {
    staleText = `<span class="report-mgmt-warn">⚠ ${staleAnalyzer} 个 analyzer 过期</span>`;
  }
  // R-6: surface the "needs rawdata" count so operators know those cells
  // can't be auto-fixed and must be re-sampled first.
  const needsRawdataHint = needsRawdata > 0
    ? `<span class="report-mgmt-warn muted" title="这些 (机台, mode) analyzer 过期但无可用 rawdata，需先重新采样">⚠ ${needsRawdata} 个需先采样</span>`
    : "";

  const regenBtn = fixable > 0
    ? `<button id="regenerateStaleBtn" class="small-btn primary-btn" title="只重生 analyzer 过期 + rawdata 未过期的 report (轻量修复)">⟳ 重生 ${fixable}</button>`
    : "";

  banner.innerHTML = `
    <div class="report-mgmt-row">
      <span class="report-mgmt-main">💼 Report 管理 · analyzer <code>${analyzerShort}</code> · ${staleText}${needsRawdataHint ? " · " + needsRawdataHint : ""}</span>
      <span class="report-mgmt-actions">
        ${regenBtn}
        <button id="rebuildAllReportsBtn" class="small-btn" title="扫所有含 rawdata 的 (机台, mode)，用当前 analyzer 全部重跑 generate-report (大批量，耗时长)">⟳ 全 fleet 重建</button>
        <button id="reportCleanupBtn" class="small-btn danger-btn" title="删除已被当前版报表取代的 analyzer 过期旧版本（仅当该 机台+mode 已有当前版报表时才删，否则只去重，绝不清空唯一报表）">🗑 清理过期版本</button>
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
      state.batchGenerateProgress = { total: out.total, completed: 0, failed: 0, pending: out.total, status: "running", items: [] };
      state._batchGenLogged = new Set();  // reset per-item dedup for the new batch
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
      if (result) result.textContent = `已清理：删除 ${data.deleted || 0} 个旧 report 版本（含 ${data.stale_pruned || 0} 个 analyzer 过期，仅当该机台已有当前版报表时才删）`;
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
      // Emit per-item ✓/✗ to the unified log as items reach a terminal state, so
      // the operator sees WHY the running count drops (success vs failure), not
      // just that it dropped. Dedup via state._batchGenLogged (reset on batch start).
      if (!state._batchGenLogged) {
        // No fresh kick (page reloaded mid-batch) — seed already-terminal items as
        // "logged" so we don't flood the log with the whole backlog on recovery;
        // only NEW completions after this point get a line.
        state._batchGenLogged = new Set();
        (body.items || []).forEach((it) => {
          if (it && (it.status === "completed" || it.status === "failed")) {
            state._batchGenLogged.add(`${it.machine}|${it.mode}`);
          }
        });
      }
      (body.items || []).forEach((it) => {
        if (!it || (it.status !== "completed" && it.status !== "failed")) return;
        const key = `${it.machine}|${it.mode}`;
        if (state._batchGenLogged.has(key)) return;
        state._batchGenLogged.add(key);
        if (it.status === "completed") {
          pushClientEvent("generate_item_done", {
            machine: it.machine, mode: it.mode,
            rtp_pct: it.rtp_point_pct, halfwidth_pp: it.achieved_halfwidth_pp, chunks: it.chunks_processed });
        } else {
          pushClientEvent("generate_item_failed", {
            machine: it.machine, mode: it.mode, error: String(it.error || "").substring(0, 200) });
        }
      });
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
        pushClientEvent("batch_generate_done", { completed: body.completed, total: body.total, failed: body.failed });
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

// Reset every debug-tab panel back to "no report loaded" state.
// Called when the current run's data can't be loaded (404 from the
// API, or no currentRunId to begin with). Without this, clearing
// setLoadedMachineInfo alone leaves all the KPI cards / bucket table /
// payIdOverview / classifier panels showing the PREVIOUSLY loaded run's
// data — so the user clicks "载入 mode 1" on a report whose run row got
// deleted, the /api/runs/{rid} 404s, currentRunId gets wiped, but the
// page still shows mode 2's panels from the last successful load
// (2026-04-22 bug: "载入 2 以后，点击载入 1 的那一份，显示的还是 2").
function _resetDebugPanelsToEmpty() {
  state.latestSummary = null;
  // KPI main tiles
  for (const id of [
    "kpiRtp", "kpiCi", "kpiSpins", "kpiZero",
    "kpiArchetype", "kpiLossStreak", "kpiMaxReturn",
  ]) {
    setKpi(id, "N/A", "neutral");
  }
  // KPI sub-lines that applyLibraryRanking / archetype populate
  for (const id of ["kpiArchetypeSub", "kpiVolatilitySub"]) {
    const el = byId(id);
    if (el) el.textContent = "";
  }
  // Multi-tile grids (tail-dep + big-win)
  const tailGrid = byId("kpiTailGrid");
  if (tailGrid) tailGrid.innerHTML = "";
  const bigWinGrid = byId("kpiBigWinGrid");
  if (bigWinGrid) bigWinGrid.innerHTML = "";
  // Bucket distribution table
  const bucketBody = byId("bucketTable")?.querySelector("tbody");
  if (bucketBody) bucketBody.innerHTML = "";
  // Panels that gate their own visibility on data presence — hide them
  // so the user sees a clean "nothing loaded" debug tab rather than a
  // partial mosaic of stale panels.
  for (const id of [
    "payIdOverviewPanel", "paylineClassificationPanel",
    "fieldDiscoveryPanel", "machineMechanicsPanel",
    "bonusChainDynamicsPanel", "collectCyclePanel",
    "bankruptcyPanel",
    "reelMarginalBySpinTypePanel",
    "spinTypeOutcomesPanel",  // unified per-SpinType panel (consolidates payouts-by-spintype + topdollar); self-hides on paint; reset here for the clean nothing-loaded state.
  ]) {
    const el = byId(id);
    if (el) el.classList.add("hidden");
  }
  // Text blocks
  const eventsEl = byId("eventsText");
  if (eventsEl) eventsEl.textContent = fmt("noEvents");
  const asEl = byId("assessment");
  if (asEl) asEl.textContent = fmt("noReport");
  const intEl = byId("interpretationText");
  if (intEl) intEl.textContent = fmt("noInterpret");
}


// ── Extracted named panel render functions ─────────────────────────────────────
// These were previously inline inside _paintAnalysisFromSummary. Extracted so
// they can be referenced by PANEL_REGISTRY descriptors in panel_registry.js.
// Each function produces BYTE-IDENTICAL DOM output to the original inline code.

/**
 * renderKpiTiles(s) — KPI card row (RTP, CI, Spins, Zero-win, Archetype,
 * Loss-streak, Max-return). Compare-aware via state.compareMode.b.
 * Extracted from _paintAnalysisFromSummary (was lines 7039-7086).
 */
function renderKpiTiles(s) {
  const cards = PURE.extractMetricCards(s, state.lang);
  const cardsB = state.compareMode && state.compareMode.b
    ? PURE.extractMetricCards(state.compareMode.b, state.lang)
    : null;
  const _ciA = Number((s.sampling || {}).achieved_halfwidth_pp);
  const _ciB = cardsB
    ? Number((state.compareMode.b.sampling || {}).achieved_halfwidth_pp)
    : null;
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
    let compareArg = null;
    if (cardsB) {
      const cB = cardsB[key] || { value: "N/A" };
      let deltaText = "";
      let deltaSig = "unknown";
      if (key === "rtp") {
        const aN = parseFloat((c.value || "").replace(/[^0-9.\-]/g, ""));
        const bN = parseFloat((cB.value || "").replace(/[^0-9.\-]/g, ""));
        if (Number.isFinite(aN) && Number.isFinite(bN)) {
          const d = bN - aN;
          deltaText = (d >= 0 ? "+" : "") + d.toFixed(2) + "pp";
          deltaSig = window.COMPARE_DIFF
            ? window.COMPARE_DIFF.isSignificant(d, _ciA, _ciB)
            : "unknown";
        }
      }
      compareArg = { textB: cB.value, deltaText, deltaSig };
    }
    setKpi(domId, c.value, c.tone, compareArg);
    if (subId) {
      const subEl = byId(subId);
      if (subEl) subEl.textContent = c.sub || "";
    }
  }
}

/**
 * renderTailDepGrid(s) — Tail-dependency 2x2 grid (#kpiTailGrid).
 * Compare-aware via state.compareMode.b.
 * Extracted from _paintAnalysisFromSummary (was lines 7091-7122).
 */
function renderTailDepGrid(s) {
  const cards = PURE.extractMetricCards(s, state.lang);
  const tailGrid = byId("kpiTailGrid");
  if (tailGrid) {
    const td = cards.tailDep || {};
    const dm = s.guideline_assessment?.derived_metrics || {};
    const dmB = state.compareMode && state.compareMode.b
      ? (state.compareMode.b.guideline_assessment?.derived_metrics || {})
      : null;
    const fmt1 = (v) => v == null ? "—" : (Number(v) * 100).toFixed(1) + "%";
    const tone = td.tone || "neutral";
    const _tcell = (label, key) => {
      const aRaw = dm[key];
      const aV = fmt1(aRaw);
      if (!dmB) return `<div class="tail-cell"><em>${label}</em><b>${aV}</b></div>`;
      const bRaw = dmB[key];
      const bV = fmt1(bRaw);
      // Tail-dep raws are 0–1 fractions → render Δ in pp scale.
      const aN = aRaw == null ? NaN : Number(aRaw) * 100;
      const bN = bRaw == null ? NaN : Number(bRaw) * 100;
      return `<div class="tail-cell"><em>${label}</em><b>` +
        _cmpCell(true, aV, bV, aN, bN, "pp", 2) + `</b></div>`;
    };
    tailGrid.innerHTML =
      _tcell("≥10x", "tail_dependency_ge10x") +
      _tcell("≥20x", "tail_dependency_ge20x") +
      _tcell("≥50x", "tail_dependency_ge50x") +
      _tcell("≥100x", "tail_dependency_ge100x");
    const card = tailGrid.closest(".kpi");
    if (card) {
      card.classList.remove("kpi--good", "kpi--warn", "kpi--bad");
      if (tone === "good" || tone === "warn" || tone === "bad") card.classList.add(`kpi--${tone}`);
    }
  }
}

/**
 * renderBigWinGrid(s) — Big-win rate 4-tile grid (#kpiBigWinGrid).
 * Compare-aware via state.compareMode.b.
 * Extracted from _paintAnalysisFromSummary (was lines 7123-7148).
 */
function renderBigWinGrid(s) {
  const cards = PURE.extractMetricCards(s, state.lang);
  const bigWinGrid = byId("kpiBigWinGrid");
  if (bigWinGrid) {
    const tiles = (cards.bigWin && cards.bigWin.tiles) || {};
    const cardsBLocal = state.compareMode && state.compareMode.b
      ? PURE.extractMetricCards(state.compareMode.b, state.lang)
      : null;
    const tilesB = cardsBLocal && cardsBLocal.bigWin ? cardsBLocal.bigWin.tiles : null;
    const pct1 = (v) => v == null ? "—" : (Number(v) * 100).toFixed(2) + "%";
    const _bcell = (label, key) => {
      const aRaw = tiles[key];
      const aV = pct1(aRaw);
      if (!tilesB) return `<div class="tail-cell"><em>${label}</em><b>${aV}</b></div>`;
      const bRaw = tilesB[key];
      const bV = pct1(bRaw);
      // Big-win tile raws are 0–1 fractions → render Δ in pp.
      const aN = aRaw == null ? NaN : Number(aRaw) * 100;
      const bN = bRaw == null ? NaN : Number(bRaw) * 100;
      return `<div class="tail-cell"><em>${label}</em><b>` +
        _cmpCell(true, aV, bV, aN, bN, "pp", 2) + `</b></div>`;
    };
    bigWinGrid.innerHTML =
      _bcell("≥10x", "ge10") +
      _bcell("≥20x", "ge20") +
      _bcell("≥50x", "ge50") +
      _bcell("≥100x", "ge100");
  }
}

/**
 * renderLibraryRanking(s) — Across-library ranking fetch + apply.
 * Async; registered as fireAndForget:true (non-blocking for the panel sequence).
 * Extracted from _paintAnalysisFromSummary (was lines 7154-7164).
 */
async function renderLibraryRanking(s) {
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
}

/**
 * renderBucketDistribution(s) — Multiplier-bucket distribution table (#bucketTable tbody).
 * Compare-aware via state.compareMode.b.
 * Extracted from _paintAnalysisFromSummary (was lines 7166-7228).
 */
function renderBucketDistribution(s) {
  // Bucket distribution: table-based (replaces Chart.js canvas).
  const buckets = s.player_impact?.multiplier_profile?.buckets || [];
  const bucketBody = byId("bucketTable")?.querySelector("tbody");
  if (bucketBody) {
    // Compare-aware: when compareMode active, each TD stacks A
    // value on top + B value (or Δ) underneath. The same
    // <thead> / column count is preserved — only cell content
    // gets denser. CSS .cmp-active styles handle compaction.
    const cmpB = state.compareMode && state.compareMode.b
      ? (state.compareMode.b.player_impact?.multiplier_profile?.buckets || [])
      : null;
    // Build a key→bucket map for B so we can align by bucket name.
    const bMap = new Map();
    if (cmpB) for (const r of cmpB) bMap.set(String(r.bucket || ""), r);
    // Merge bucket key set (canonical order from A, B-only appended).
    const aSet = new Set(buckets.map((r) => String(r.bucket)));
    const merged = [...buckets];
    if (cmpB) {
      for (const r of cmpB) {
        if (!aSet.has(String(r.bucket))) merged.push(r);
      }
    }
    const maxRtp = Math.max(...merged.map((b) => Math.max(
      Number(b.rtp_contribution_pp || 0),
      cmpB ? Number((bMap.get(String(b.bucket)) || {}).rtp_contribution_pp || 0) : 0,
    )), 0.001);
    bucketBody.innerHTML = merged
      .map((b) => {
        // 2026-05-12: B-only 行 (b 是 B 桶) 的 A 侧字段必须置 "—" / NaN,
        // 否则 aCountRaw 会从 b 自己读到 B 的数,Δ chip 显示 ≈ 假象。
        // 同形 bug 见 _renderFeatureBucketTable。
        const aIn = aSet.has(String(b.bucket));
        const aCountRaw = aIn ? Number(b.spin_count || 0) : NaN;
        const aSpinPctRaw = aIn ? Number(b.spin_rate || 0) * 100 : NaN;
        const aRtpPpRaw = aIn ? Number(b.rtp_contribution_pp || 0) : NaN;
        const aCount = aIn ? fInt(b.spin_count) : "—";
        const aSpinPct = aIn ? aSpinPctRaw.toFixed(2) : "—";
        const aRtpPp = aIn ? aRtpPpRaw.toFixed(2) : "—";
        const aBar = aIn ? Math.min(100, (aRtpPpRaw / maxRtp) * 100) : 0;
        let bCount = "—", bSpinPct = "—", bRtpPp = "—", bBar = 0;
        let bCountRaw = NaN, bSpinPctRaw = NaN, bRtpPpRaw = NaN;
        if (cmpB) {
          const bRow = bMap.get(String(b.bucket)) || {};
          bCountRaw = Number(bRow.spin_count || 0);
          bSpinPctRaw = Number(bRow.spin_rate || 0) * 100;
          bRtpPpRaw = Number(bRow.rtp_contribution_pp || 0);
          bCount = fInt(bRow.spin_count);
          bSpinPct = bSpinPctRaw.toFixed(2);
          bRtpPp = bRtpPpRaw.toFixed(2);
          bBar = Math.min(100, (bRtpPpRaw / maxRtp) * 100);
        }
        return (
          `<tr>` +
          `<td>${PURE.prettyBucketLabel(b.bucket)}</td>` +
          `<td>${_cmpCell(!!cmpB, aCount, bCount, aCountRaw, bCountRaw, "rel")}</td>` +
          `<td>${_cmpCell(!!cmpB, aSpinPct + "%", bSpinPct + "%", aSpinPctRaw, bSpinPctRaw, "pp")}</td>` +
          `<td>${_cmpCell(!!cmpB, aRtpPp + "pp", bRtpPp + "pp", aRtpPpRaw, bRtpPpRaw, "pp", 2)}</td>` +
          (cmpB
            ? `<td class="bar-cell bar-cell-cmp" style="--bar:${aBar.toFixed(1)}%;--bar-b:${bBar.toFixed(1)}%"></td>`
            : `<td class="bar-cell" style="--bar:${aBar.toFixed(1)}%"></td>`) +
          `</tr>`
        );
      })
      .join("");
  }
}

// ── Generic spec-driven stats panel renderer (P2) ──────────────────────────────
//
// renderStatsPanel(ctx, spec) — builds a KV table + optional tally sub-tables
// from a declarative spec. Zero bespoke render code per feature; add a spec,
// get a panel.
//
// spec shape:
//   {
//     panelId:        string  — DOM id of the <section> container
//     summaryKey:     string  — top-level key in ctx.a (e.g. "topdollar_choice")
//     titleKey:       string  — i18n key for the panel title (written to h2[data-i18n])
//     applicableField:string  — field inside the data obj that must be truthy
//     sections: [
//       { type:"kv", rows:[{labelKey, path, fmt}] }
//         — KV table: one row per spec entry.
//           fmt ∈ "int"  → PURE.fInt(v)
//                "pct"   → PURE.fRate(v)          (fraction 0-1 → "X.XX%")
//                "pp"    → v.toFixed(2) + "pp"     (already in pp units)
//                "raw"   → String(v)
//       { type:"tally", titleKey, path }
//         — small two-column table: key → count, sourced from an object dict.
//     ]
//   }
//
// Single-mode for P2 (reads ctx.a only). Compare-mode: renders A's values, no Δ
// column — P3 will add that. Does NOT break compare (panel is new; no prior DOM).
//
// Mirrors renderBonusChainDynamicsPanel conventions:
//   - panel.classList.add/remove("hidden") gating
//   - fmt() for i18n labels
//   - PURE.fInt / PURE.fRate for values
//   - .drilldown-table CSS (same as all sibling panels)
//   - .mech-section / .mech-stat / .mech-label / .mech-value CSS for KV grid
//
// Build the inner HTML for a spec-driven stats block (KV grid + tally tables).
// Extracted from renderStatsPanel so the SAME rendering can be (a) written to a
// standalone panel by renderStatsPanel, OR (b) embedded inline inside another
// panel (e.g. the TopDollar behavior under ST14 in the per-SpinType view).
// Reuses .mech-section/.mech-grid/.mech-stat + .drilldown-table — parity with siblings.
function _buildStatsSectionsHtml(data, sections) {
  const _fmtVal = (v, fmtType) => {
    if (v === null || v === undefined) return "N/A";
    switch (fmtType) {
      case "int": return fInt(v);
      case "pct": return fRate(v);           // fraction 0–1 → "X.XX%"
      case "pp":  return Number(v).toFixed(2) + "pp";
      case "mult": return Number(v).toFixed(1) + "×";  // multiplier
      case "raw": return String(v);
      default:    return String(v);
    }
  };
  const _resolve = (path) => {
    let v = data;
    for (const p of String(path).split(".")) { v = (v != null && typeof v === "object") ? v[p] : undefined; }
    return v;
  };
  let html = "";
  for (const section of (sections || [])) {
    if (section.type === "kv") {
      const rowsHtml = (section.rows || []).map((row) => (
        `<div class="mech-stat">` +
        `<span class="mech-label">${fmt(row.labelKey)}</span>` +
        `<span class="mech-value">${_fmtVal(_resolve(row.path), row.fmt)}</span>` +
        `</div>`
      )).join("");
      html += `<div class="mech-section"><div class="mech-grid">${rowsHtml}</div></div>`;
    } else if (section.type === "tally") {
      // Distribution table: key | count | 概率 (share). "_other" pinned last;
      // numeric-string keys come out ascending (JS), combo keys preserve the
      // analyzer's count-desc order.
      const dict = _resolve(section.path);
      let rowsHtml = "";
      if (dict && typeof dict === "object") {
        let keys = Object.keys(dict).filter((k) => k !== "_other");
        if (Object.prototype.hasOwnProperty.call(dict, "_other")) keys.push("_other");
        const total = keys.reduce((a, k) => a + (Number(dict[k]) || 0), 0) || 1;
        rowsHtml = keys
          .map((k) => {
            const cnt = Number(dict[k]) || 0;
            return `<tr><td>${escapeHtml(String(k))}</td><td>${fInt(cnt)}</td>` +
              `<td>${((cnt / total) * 100).toFixed(1)}%</td></tr>`;
          })
          .join("");
      }
      html += (
        `<div class="mech-section"><h3>${fmt(section.titleKey)}</h3>` +
        `<table class="drilldown-table"><thead><tr>` +
        `<th>${fmt(section.keyColKey || "tdColKey")}</th>` +
        `<th>${fmt(section.countColKey || "tdColCount")}</th>` +
        `<th>${fmt("stoColShare")}</th></tr></thead>` +
        `<tbody>${rowsHtml}</tbody></table></div>`
      );
    } else if (section.type === "mult_buckets") {
      // Multiplier bucket distribution: 倍率区间 | 次数 | 概率 (+bar). For the
      // TopDollar total-mini-game multiplier (settled_win/bet) — 倍率/概率/分布.
      const list = Array.isArray(_resolve(section.path)) ? _resolve(section.path) : [];
      let rowsHtml = "";
      if (list.length) {
        const maxProb = Math.max(...list.map((b) => Number(b.prob) || 0), 0.0001);
        rowsHtml = list
          .map((b) => {
            const prob = Number(b.prob) || 0;
            const barPct = (prob / maxProb) * 100;
            return `<tr><td>${PURE.prettyBucketLabel(b.bucket)}×</td>` +
              `<td>${fInt(Number(b.count) || 0)}</td>` +
              `<td class="bar-cell" style="--bar:${barPct.toFixed(1)}%">${(prob * 100).toFixed(1)}%</td></tr>`;
          })
          .join("");
      }
      html += (
        `<div class="mech-section"><h3>${fmt(section.titleKey)}</h3>` +
        `<table class="drilldown-table"><thead><tr>` +
        `<th>${fmt("stoColBand")}</th><th>${fmt("stoColHits")}</th><th>${fmt("stoColShare")}</th>` +
        `</tr></thead><tbody>${rowsHtml}</tbody></table></div>`
      );
    }
  }
  return html;
}

// (renderStatsPanel + TOPDOLLAR_CHOICE_SPEC removed — the per-SpinType view now
//  builds the TopDollar pick/settlement blocks inline via _buildStatsSectionsHtml
//  with _TD_PICK_SECTIONS / _TD_SETTLE_SECTIONS, split across ST=14 and ST=15.)

// ── End extracted named panel render functions ──────────────────────────────────

/** Render the analysis panels (KPI tiles, tail/big-win grids,
 *  bucket table, paylines, symbols, payouts, features, mechanics,
 *  bankruptcy, library ranking) from a given summary dict. Used by
 *  both refreshCurrentRun (after fetching from /api/runs/.../report)
 *  and _enterCompareMode (which has both summaries in memory and
 *  doesn't need an API round-trip). Compare-aware renderers branch
 *  on state.compareMode.b INSIDE this function — the caller just
 *  passes the primary summary as `s`.
 *
 *  Returns nothing. Async because applyLibraryRanking does its own
 *  /api/library/distributions fetch + several panel renderers are
 *  async on their own.
 */
async function _paintAnalysisFromSummary(s) {
  // Build the ctx object that PANEL_REGISTRY descriptors receive.
  // P1: wrapped fns still read state.compareMode.b internally — no change to
  // their bodies. ctx.b is wired for P2+ panels that accept it as a parameter.
  const ctx = {
    a: s,
    b: (state.compareMode && state.compareMode.b) || null,
    machine: s.machine,
    mode: s.mode,
    compare: !!state.compareMode,
  };

  // Iterate PANEL_REGISTRY in order-value order.
  // fireAndForget descriptors are called WITHOUT await — matches the original
  // dispatch, which called the 3 async panels (library-ranking,
  // renderPaylineClassification, renderPayIdOverview) without await. The
  // remaining panels are synchronous; awaiting a non-Promise is immediate, so
  // the original sequencing is preserved exactly.
  const _registry = window.PANEL_REGISTRY;
  if (!Array.isArray(_registry) || _registry.length === 0) {
    console.warn("PANEL_REGISTRY missing/empty — analysis panels will not render (panel_registry.js failed to load?)");
  }
  const sorted = (_registry || [])
    .slice()
    .sort((a, b) => a.order - b.order);
  // Every descriptor's render() runs on each paint and SELF-HIDES when its data is
  // absent (the P1 pattern). No present()/skip shortcut — skipping render would leave
  // a panel showing stale data after a machine switch (the load path does not reset
  // before painting). render() must be cheap + idempotent.
  for (const descriptor of sorted) {
    // Per-panel isolation: one panel throwing must NOT blank out the rest of the
    // report. Without this, a single bad render() aborts the loop → every later
    // panel (incl. the machine-general ones) vanishes and the report reads as
    // "completely unreadable". Log + continue; the failed panel just self-hides.
    try {
      if (descriptor.fireAndForget) {
        Promise.resolve(descriptor.render(ctx)).catch((e) =>
          console.error(`panel '${descriptor.id}' render() failed:`, e));
      } else {
        await descriptor.render(ctx);
      }
    } catch (e) {
      console.error(`panel '${descriptor.id}' render() failed:`, e);
    }
  }
}


async function refreshCurrentRun() {
  if (!state.currentRunId) {
    setLoadedMachineInfo(null);
    _resetDebugPanelsToEmpty();
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
      // Stale currentRunId (run was deleted) — clear, reset ALL panels
      // (previously only reset loadedMachineInfo, leaving KPI cards +
      // bucket table + sub-panels showing whichever report was loaded
      // before this click → user sees mismatched data with
      // loadedMachineInfo reading "no run loaded" but panels showing
      // the previous mode's values), and keep going.
      state.currentRunId = "";
      state.currentRunStatus = "";
      setLoadedMachineInfo(null);
      _resetDebugPanelsToEmpty();
      renderLiveStatusStrip();
      updateActionStates();
      return;
    }
    // Transient network error (e.g. "Failed to fetch" during a page
    // reload race, or a brief backend hiccup). Don't let it bubble up
    // through loadBootstrap → setHealth(false): the next poll tick
    // (4.5s) will retry, and the rest of the UI is already populated.
    // Panels intentionally NOT reset here — polling transients
    // shouldn't flash empty panels.
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

  // Auto-refresh the right-side mode-data panel (rwtree) when the
  // currently-focused machine's run just finished. Without this, a
  // sampling run produces new chunks + a new report, but the panel
  // still shows the pre-run counts — user has to click away and back
  // to see the update. Guard on (prev running/queued → terminal) so
  // we only refresh once per state transition, not on every poll tick
  // while the run stays "completed".
  //
  // Second guard on ``state._autoRefreshedForRunId`` — fastTimer fires
  // refreshCurrentRun every 1s while status == running, and those ticks
  // can overlap (each call is async, the second invocation can start
  // before the first finishes its chain of awaits). Both concurrent
  // invocations would see the same running→completed transition in
  // their local ``prevStatus`` snapshots and each fire the refresh
  // (observed 3× in preview testing). The per-run one-shot flag
  // dedupes them; it resets whenever currentRunId changes so
  // switching between runs still triggers a fresh auto-refresh.
  const _prevLower = String(prevStatus || "").toLowerCase();
  const _curLower = String(state.currentRunStatus || "").toLowerCase();
  const _justFinished = _prevLower !== _curLower
    && (_curLower === "completed" || _curLower === "cancelled" || _curLower === "failed")
    && _prevLower !== "";  // ignore the first load where prev was ""
  if (_justFinished && run.machine && state.focusedMachine === run.machine
      && state._autoRefreshedForRunId !== state.currentRunId) {
    state._autoRefreshedForRunId = state.currentRunId;
    // Fire-and-forget — don't block refreshCurrentRun on the tree
    // re-render (the rwtree has its own error handling + graceful
    // empty state if any of its fetches fail).
    renderRawdataReportTree(run.machine).catch((err) => {
      console.warn("rwtree auto-refresh on run finish failed:", err);
    });
  }

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
  // 运行事件 (raw-jsonl #eventsText) retired in the log redesign (P3): the unified
  // 活动日志流 shows these backend events in readable form, filterable by machine.
  // Guarded so this is a no-op once the panel markup is gone.
  { const _ev = byId("eventsText"); if (_ev) _ev.textContent = events.length ? events.slice(-80).map((e) => JSON.stringify(e)).join("\n") : fmt("noEvents"); }

  // Per-run failures / cancellations are shown inside runMeta (above).
  // Global warning area stays reserved for system + model notices.
  const warnings = modelWarnings();

  // "completed" (ran to CI / max_chunks) and "cancelled" (graceful
  // Stop with partial data) both have a readable summary. Show the
  // full panel stack in either case; the status badge / topbar
  // already distinguishes the two so the operator sees which path
  // produced the data.
  if (run.status === "completed" || run.status === "cancelled") {
    let report;
    try {
      report = await apiGet(`/api/runs/${state.currentRunId}/report`);
    } catch (err) {
      const msg = String(err?.message || "");
      if (msg.includes("404")) {
        // Report file deleted (e.g. operator cleaned up rawdata/reports
        // but the run row survives in console.db). Clear currentRunId so
        // subsequent polls don't keep hitting the missing report, and
        // reset panels to a clean state. Mirrors the run-404 catch above.
        state.currentRunId = "";
        state.currentRunStatus = "";
        setLoadedMachineInfo(null);
        _resetDebugPanelsToEmpty();
        renderLiveStatusStrip();
        updateActionStates();
        return;
      }
      // Non-404 (transient network / 500): leave panels as-is, next poll retries.
      console.warn("refreshCurrentRun: report fetch failed —", msg);
      return;
    }
    const s = report.summary || {};
    state.latestSummary = s;
    await _paintAnalysisFromSummary(s);
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
  // First click (no prev): set use_auto_grid=true + send empty candidate
  // arrays. Backend picks a probe grid sized for the current server
  // endpoint kind (loopback / LAN / WAN per
  // _classify_endpoint_kind in app.py). The 2026-04-25 external-server
  // benchmark numbers (r=8 c=8 ≈ 9k outer/s peak) live in the WAN preset.
  // Internal-deploy 2026-05-22 measurement: loopback can sustain 30k+
  // outer/s but only at robots=16-32 / conc=8-16, which the old [8,16]
  // × [4,8,12] grid never explored — the autotune capped at robot=8
  // conc=8 not because it was the true peak, just because nothing
  // higher was tested.
  //
  // Subsequent clicks (have prev): refine ±6 robots / ±2 concs around
  // the previous best — frontend-side narrowing is still useful for
  // iterating once the operator has a reasonable baseline.
  const useAutoGrid = !prev;
  const robotCandidates = prev
    ? [...new Set([prev.robot_count - 6, prev.robot_count, prev.robot_count + 6]
        .map((x) => Math.max(4, x)).filter((x) => x <= 200))]
    : [];
  const concurrencyCandidates = prev
    ? [...new Set([Math.max(2, prev.batch_concurrency - 2), prev.batch_concurrency, prev.batch_concurrency + 2]
        .filter((x) => x >= 1 && x <= 16))]
    : [];
  const payload = {
    machine,
    mode,
    spin_times: 200,
    robot_candidates: robotCandidates,
    concurrency_candidates: concurrencyCandidates,
    use_auto_grid: useAutoGrid,
    rounds: 2,
    timeout: 60,
    bet: 1000,
  };
  const autoEl = byId("autotuneMeta");
  if (autoEl) {
    autoEl.classList.remove("hidden");
    const gridLabel = useAutoGrid
      ? "robots=<auto>\nconc=<auto>"
      : `robots=[${robotCandidates.join(",")}]\nconc=[${concurrencyCandidates.join(",")}]`;
    autoEl.textContent = `machine=${machine} mode=${mode}\n${gridLabel}\n${fmt("autotuneProgressStarting")}`;
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

// ── One-click update/restart (topbar) ──────────────────────────────────────
// Fetch build identity + supervised flag; render the version chip + gate the
// button. Surfaces the launcher's last pull result into the unified log once.
async function refreshSystemVersion() {
  let info = null;
  try { info = await apiGet("/api/system/version"); } catch (_) { info = null; }
  state.systemVersion = info;
  if (info && info.app_started_at) state.appStartedAt = info.app_started_at;
  const wrap = byId("systemUpdate");
  const chip = byId("versionChip");
  const btn = byId("updateRestartBtn");
  if (!wrap || !chip || !btn) return;
  if (!info) { wrap.classList.add("hidden"); return; }
  wrap.classList.remove("hidden");
  const c = PURE.formatVersionChip(info);
  chip.textContent = c.text;
  chip.title = c.title;
  // Gate the button on supervised launch — a manually-started `uvicorn` would
  // self-exit and never come back, stranding the console down.
  btn.disabled = !info.supervised;
  btn.title = info.supervised
    ? "git pull 最新代码并重启 console"
    : "需经受管启动器启动才能自动更新重启（服务器=SlotConsole 计划任务，本地=start.bat）";
  // Surface the launcher's last pull result ONCE (cleared so it doesn't re-log
  // on every bootstrap / periodic refresh).
  if (info.last_update && !state._lastUpdateShown) {
    state._lastUpdateShown = true;
    // Only surface if recent — else an hours-old result would re-log after an
    // UNRELATED crash-restart + page reload, reading as a fresh update. Unknown
    // ts → show (don't suppress a legitimate one).
    const ts = Date.parse(info.last_update.ts || "");
    const recent = Number.isNaN(ts) || (Date.now() - ts) < 15 * 60 * 1000;
    if (recent) {
      const r = PURE.formatUpdateResult(info.last_update);
      if (r) pushClientEvent("update_result", { level: r.level, text: r.text });
    }
  }
}

async function doUpdateRestart() {
  if (state._updateInFlight) return;  // guard against double-click during the window
  const info = state.systemVersion || {};
  if (!info.supervised) {
    alert("console 未在受管启动器下运行，无法自动更新重启（服务器=SlotConsole 计划任务，本地=start.bat）。");
    return;
  }
  let force = false;
  if (info.busy) {
    if (!confirm(`有 ${info.running_runs_count || 0} 个运行中操作（采样/生成），更新重启会中断它们。仍要继续？`)) return;
    force = true;
  }
  if (!confirm(`更新并重启 console？\n当前 ${info.commit || "?"} → git pull 最新并重启（约 10–40 秒，期间页面自动重连刷新）。`)) return;
  state._updateInFlight = true;
  const btn = byId("updateRestartBtn");
  if (btn) btn.disabled = true;
  const before = state.appStartedAt || info.app_started_at || "";
  const overlay = byId("updateOverlay");
  const sub = byId("updateOverlaySub");
  if (overlay) overlay.classList.remove("hidden");
  if (sub) sub.textContent = `当前 ${info.commit || "?"} · 正在 git pull 并重启…`;
  pushClientEvent("update_start", { text: `更新并重启 · 当前 ${info.commit || "?"}` });
  try {
    await apiPost("/api/system/update-restart" + (force ? "?force=true" : ""), {});
  } catch (err) {
    state._updateInFlight = false;
    if (btn) btn.disabled = false;
    if (overlay) overlay.classList.add("hidden");
    const msg = (err && err.message) ? err.message : String(err);
    pushClientEvent("update_result", { level: "error", text: "更新请求失败：" + msg });
    alert("无法更新重启：" + msg);
    return;
  }
  _pollForRestart(before, 0);
}

// Poll /api/health until a NEW process is up (app_started_at changed), then
// reload. While the server is down the fetch just fails and we retry.
function _pollForRestart(beforeStartedAt, attempt) {
  const MAX = 80;  // ~80 × 1.5s ≈ 2 min
  const sub = byId("updateOverlaySub");
  if (attempt > MAX) {
    if (sub) sub.textContent = "重启超时（>2 分钟）。请检查服务器 console 窗口。";
    const rb = byId("updateReloadBtn");
    if (rb) rb.classList.remove("hidden");  // give the operator a manual-recover affordance
    const sp = document.querySelector(".update-spinner");
    if (sp) sp.style.display = "none";
    return;
  }
  setTimeout(async () => {
    let h = null;
    try { h = await apiGet("/api/health"); } catch (_) { h = null; }
    if (PURE.updateRestartDone(beforeStartedAt, h)) {
      if (sub) sub.textContent = "已重启，正在重新加载…";
      setTimeout(() => location.reload(), 600);
      return;
    }
    if (sub && attempt > 1) sub.textContent = `重启中…（${Math.round(attempt * 1.5)}s）`;
    _pollForRestart(beforeStartedAt, attempt + 1);
  }, 1500);
}

async function loadBootstrap() {
  const [h, m, models, versions, reviewState] = await Promise.all([
    apiGet("/api/health"),
    apiGet("/api/machines"),
    apiGet("/api/models"),
    // Current analyzer + per-machine md5 fingerprints drive the
    // Run History staleness badges; fetched once per bootstrap and
    // cached in state — these change only when code is reloaded or
    // machines.json is refreshed, both of which already reload.
    apiGet("/api/versions/current").catch(() => null),
    // Per-machine manifest review state (verified / reviewed flags).
    // Drives the catalog badges; missing entries = no-badge.
    apiGet("/api/manifests/review-state").catch(() => null),
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
  state.manifestReviewState = reviewState || {};
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
  refreshSystemVersion();    // version chip + 更新并重启 button (async)
  _initBatchGenerateCancelBtn();  // wire the stop button one-shot
  _restoreSamplingPrefs();  // hydrate sampleMode/sampleCi from localStorage
  updateSampleHint();
  refreshDiskSpace();
  // Recover activeBatchId from server if a batch is still running;
  // resumes polling + hides 开始采样 so user doesn't click again.
  _recoverActiveSampling();
  await refreshServers();
  // Auto-refresh upstream md5 on every page load (2026-04-21). Keeps
  // the UI's md5 comparisons honest — planner might have pushed a new
  // config between sessions, and we want cards / classifier / rwtree
  // to reflect that without the operator needing to hit the explicit
  // "刷新机台 MD5" button. Fire-and-forget: don't block the initial
  // render on upstream latency; events pushed to the activity strip
  // so the operator sees "⟳ 刷新上游 md5 … ✓ md5 已刷新 · N 台有变更".
  (async () => {
    pushClientEvent("md5_refresh_start", {});
    try {
      const r = await apiPost("/api/machines/refresh-md5", {});
      pushClientEvent("md5_refresh_done", {
        fetched: r.machines_fetched || 0,
        updated: r.machines_updated || 0,
        updated_machines: Array.isArray(r.updated_machines) ? r.updated_machines : [],
      });
      // Only re-render if something changed — saves a full summary
      // scan on the common "nothing changed" case.
      if ((r.machines_updated || 0) > 0) {
        try {
          const v = await apiGet("/api/versions/current");
          state.currentVersions = v || state.currentVersions;
        } catch (_) {}
        try {
          const s = await apiGet("/api/machines/summary");
          if (s) {
            state.machinesSummary = s;
            renderCatalogFeatureChips();
            renderMachineCatalog();
            renderFleetOverview();
            renderRtpModeBar();
          }
        } catch (_) {}
      }
    } catch (e) {
      pushClientEvent("md5_refresh_failed", {
        error: String((e && e.message) || e).slice(0, 80),
      });
    }
  })();
  // Now that machineSelect is populated, seed the topbar idle brief.
  // (applyI18n() ran before bootstrap when machineSelect was empty, so
  // its renderLiveStatusStrip() call was a no-op.)
  renderLiveStatusStrip();
  setLoadedMachineInfo(null);
  // #assessment was removed in round 4's KPI-grid rewrite but this
  // bootstrap-tail initializer kept referencing it; the unguarded
  // textContent write threw TypeError and aborted the remainder of
  // loadBootstrap, leaving state.machinesSummary / catalog render
  // hooks never invoked. Guard like the _resetDebugPanelsToEmpty
  // helper does (null-check, no-op if the element is gone).
  const asEl = byId("assessment");
  if (asEl) asEl.textContent = fmt("noReport");
  const intEl = byId("interpretationText");
  if (intEl) intEl.textContent = fmt("noInterpret");
  const evEl = byId("eventsText");
  if (evEl) evEl.textContent = fmt("noEvents");
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
  // Phase 3 (D11): wire P3 panels after DOM and bootstrap data are ready.
  _initConfigUploadPanel();
  _initFleetRefreshPanel();
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
  // Unified-log filters (log redesign P2): re-render the strip on change. Guarded
  // (byId may be null if the markup is absent) so binding never throws.
  const _lfQuery = byId("logFilterQuery");
  if (_lfQuery) _lfQuery.addEventListener("input", () => {
    state.logFilter.query = _lfQuery.value;
    _renderActivityStrip();
  });
  const _lfOp = byId("logFilterOp");
  if (_lfOp) _lfOp.addEventListener("change", () => {
    state.logFilter.op = _lfOp.value;
    _renderActivityStrip();
  });
  const _lfErr = byId("logFilterErrors");
  if (_lfErr) _lfErr.addEventListener("change", () => {
    state.logFilter.errorsOnly = _lfErr.checked;
    _renderActivityStrip();
  });
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
      // Same null-guard discipline as the bootstrap-tail initializer —
      // #assessment was removed in round 4 but the unguarded writes
      // here throw the same TypeError.
      const asEl = byId("assessment");
      if (asEl) asEl.textContent = fmt("noReport");
      const intEl = byId("interpretationText");
      if (intEl) intEl.textContent = fmt("noInterpret");
      const evEl = byId("eventsText");
      if (evEl) evEl.textContent = fmt("noEvents");
      const atEl = byId("autotuneMeta");
      if (atEl) atEl.textContent = fmt("noAutoTune");
    }
    updateActionStates();
  });
  byId("tabBtnDebug").addEventListener("click", () => switchTab("debug"));
  byId("tabBtnManage").addEventListener("click", () => switchTab("manage"));
  // P4: auto-inspect tab — fetch settings + active sweep on open.
  const tabBtnAI = byId("tabBtnAutoInspect");
  if (tabBtnAI) tabBtnAI.addEventListener("click", () => {
    switchTab("auto-inspect");
    _onAutoInspectTabOpen();
  });
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
  // 2026-05-26 B2: persistent batch history panel.
  _initBatchHistoryPanel();
  // 2026-05-22 task A1: 继续未完成项 button (hidden by default;
  // surfaced by pollSampling when a batch ends with cancelled/failed
  // items). Hidden again on fresh start so the operator cannot
  // accidentally retrigger a stale id.
  const _resumeBtnInit = byId("sampleResumeBtn");
  if (_resumeBtnInit) {
    _resumeBtnInit.addEventListener("click", () => resumeSampling());
  }
  byId("sampleMode").addEventListener("change", () => { updateSampleHint(); _saveSamplingPrefs(); });
  byId("sampleCi").addEventListener("change", () => { updateSampleHint(); _saveSamplingPrefs(); });
  byId("sampleSpinCount")?.addEventListener("input", () => updateSampleHint());
  byId("sampleStrategy")?.addEventListener("change", () => updateSampleHint());
  // Per-focused-machine MachineConfig override: checkbox tracks
  // state.machineConfigState.useLocal so startSampling can pick
  // it up. Card only renders when backend availability probe
  // returned `available: true`, so the checkbox can't be toggled
  // for a missing file.
  byId("useLocalMachineConfig")?.addEventListener("change", (e) => {
    if (state.machineConfigState) {
      state.machineConfigState.useLocal = !!e.target.checked;
      renderMachineConfigOverride();
    }
  });
  byId("uploadMachineConfigBtn")?.addEventListener("click", () => {
    const m = state.machineConfigState?.machine || state.focusedMachine;
    if (m) _uploadMachineConfig(m);
  });
  byId("clearMachineConfigBtn")?.addEventListener("click", () => {
    const m = state.machineConfigState?.machine || state.focusedMachine;
    if (m) _clearMachineConfig(m);
  });
  byId("addServerBtn").addEventListener("click", () => addServer());
  byId("refreshMd5Btn").addEventListener("click", async () => {
    const btn = byId("refreshMd5Btn");
    btn.disabled = true;
    btn.textContent = "拉取中…";
    try {
      // Empty body = let backend pick via resolver (default_server →
      // first active). Hardcoding "dev" used to override whatever
      // the operator had set as default in 服务器管理 — defeating
      // the whole UI. 2026-04-25 fix.
      const r = await apiPost("/api/machines/refresh-md5", {});
      // Show which machines changed so the operator can tell whether
      // their working machine is affected. Cap at 10 names in the
      // alert (full list is in the activity log / response body).
      const names = Array.isArray(r.updated_machines) ? r.updated_machines : [];
      let detail = "";
      if (names.length > 0) {
        const shown = names.slice(0, 10).join(", ");
        const extra = names.length > 10 ? ` (+${names.length - 10})` : "";
        detail = `\n变更机台: ${shown}${extra}`;
      }
      alert(`刷新完成：拉取 ${r.machines_fetched} 台，${r.machines_updated} 台 MD5 变更${detail}`);
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
  byId("updateRestartBtn")?.addEventListener("click", () =>
    doUpdateRestart().catch((e) => alert(String(e.message || e)))
  );
  byId("updateReloadBtn")?.addEventListener("click", () => location.reload());
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
  // Activity strip (1s): the unified log + live progress meters across all
  // active + recent runs. 1s (was 1.2s) so the in-flight meter feels real-time.
  if (state.activityTimer) clearInterval(state.activityTimer);
  state.activityTimer = setInterval(() => {
    refreshActivityStrip().catch(() => {});
  }, 1000);
  refreshActivityStrip().catch(() => {});
  // Fast tick (1s): only the active run's progress. Created/torn down by
  // ensureFastPolling() based on currentRunStatus.
  ensureFastPolling();
}

// Pull the unified event stream + render the top "活动日志流" panel.
// ``state.activitySince`` is the cursor for incremental fetch; on the
// first tick we omit it so the panel shows the last 5 min of context.
// Client-side events (pushed via ``pushClientEvent``) also land in
// ``state.activityEvents`` and render inline — see
// ``_renderActivityStrip`` below.
async function refreshActivityStrip() {
  const panel = byId("activityStripPanel");
  const body = byId("activityStripBody");
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
  state._activeRuns = Array.isArray(data.active_runs) ? data.active_runs : [];
  _renderActivityStrip();
}

// Render the activity strip panel using current ``state.activityEvents``
// + ``state._activeRuns``. Split out of ``refreshActivityStrip`` so
// ``pushClientEvent`` can trigger an immediate re-render without
// making another /api/events round trip. Handles both backend event
// shapes (fields: model_id / machine / event / chunks_completed …)
// and client event shapes (source=ui, level, text).
function _renderActivityStrip() {
  const panel = byId("activityStripPanel");
  const body = byId("activityStripBody");
  const statusEl = byId("activityStripStatus");
  if (!panel || !body) return;
  const active = state._activeRuns || [];
  // Batch-regenerate (重生) progress is item-based, not chunk-based — its own
  // authoritative meter (完成 X/Y), pinned first so 0%-chunk generate runs don't
  // masquerade as "stuck".
  const batchMeter = PURE.formatBatchGenerateMeter(state.batchGenerateProgress);
  const anyActive = active.length || Boolean(batchMeter);
  if (anyActive) {
    panel.classList.add("activity-strip-live");
    if (statusEl) {
      const n = active.length + (batchMeter ? 1 : 0);
      statusEl.innerHTML = `🟡 ${n} 运行中`;
    }
  } else {
    panel.classList.remove("activity-strip-live");
    if (statusEl) statusEl.textContent = "idle";
  }
  // Live progress meters (sticky at the top of the log): the batch-regenerate
  // item meter (if any) + one per active run, real-time bar updated every poll.
  // This IS the progress view — the separate 采样/批量生成 windows are retired.
  const meterRows = [];
  if (batchMeter) meterRows.push(_meterRowHtml(batchMeter));
  active.forEach((r) => meterRows.push(_formatRunMeter(r)));
  const meterHtml = meterRows.length
    ? `<div class="activity-meters">${meterRows.join("")}</div>`
    : "";
  // Apply the active filter (level/op/machine/search), then show the latest 50
  // (the body scrolls), newest on top. The buffer holds up to 200 (ring above);
  // the panel is the one place all log lines land, so 50 visible >> the old 12.
  const all = state.activityEvents || [];
  const filtered = PURE.filterLogEntries(all, state.logFilter || {});
  const sorted = [...filtered].sort((a, b) => String(a.ts || "").localeCompare(String(b.ts || "")));
  const recent = sorted.slice(-50).reverse();
  const f = state.logFilter || {};
  const filterActive = !!(f.query || f.op || f.errorsOnly);
  const rowsHtml = recent.length
    ? recent.map((ev) => _formatActivityRow(ev)).join("")
    : `<div class="muted" style="padding:8px 4px;font-size:12px">${filterActive ? "无匹配事件" : "无近期事件"}</div>`;
  body.innerHTML = meterHtml + rowsHtml;
}

// One live-progress meter row from a {op, machine, mode, pct, label} object —
// shared by active-run meters AND the batch-regenerate item meter.
function _meterRowHtml(m) {
  const opLabel = PURE.logOpLabel(m.op);
  const mach = m.machine ? (m.mode != null ? `${m.machine}·m${m.mode}` : String(m.machine)) : "";
  const bar = m.pct != null
    ? `<span class="meter-bar"><span class="meter-fill" style="width:${m.pct}%"></span></span>`
    : `<span class="meter-bar meter-indeterminate"><span class="meter-fill"></span></span>`;
  const pctTxt = m.pct != null ? `${m.pct}%` : "…";
  return `<div class="activity-meter">`
    + `<span class="activity-op">${_escHtml(opLabel)}</span>`
    + `<span class="activity-mach">${_escHtml(mach)}</span>`
    + bar
    + `<span class="meter-pct">${_escHtml(pctTxt)}</span>`
    + `<span class="meter-label">${_escHtml(m.label)}</span>`
    + `</div>`;
}
function _formatRunMeter(run) { return _meterRowHtml(PURE.formatRunMeter(run)); }

// Render ONE canonical log row for every entry — client OR backend. Client
// events (source:"ui") are already canonical (PURE.buildClientEvent); backend
// run events are normalized via PURE.normalizeBackendEvent. Both yield
// {ts, level, op, machine, mode, text, detail}, rendered as: time · op-lane ·
// machine · message, coloured by level. (Replaces the old ui-vs-backend split.)
function _formatActivityRow(ev) {
  const c = PURE.toCanonicalLogEntry(ev);
  const tsShort = (c.ts || "").substring(11, 19);
  const level = c.level || "info";
  const cls = level === "warn" ? "ev-warn"
    : level === "error" ? "ev-fail"
    : level === "ok" ? "ev-ok"
    : "";
  const opLabel = PURE.logOpLabel(c.op);
  const mach = c.machine
    ? (c.mode != null ? `${c.machine}·m${c.mode}` : String(c.machine))
    : "";
  // detail (long error / raw payload) surfaces on hover via title=, so the row
  // stays one line but the full text is reachable without a separate window.
  const tailAttr = c.detail ? ` title="${_escHtml(c.detail)}"` : "";
  const tailMark = c.detail ? " ⊕" : "";
  return `<div class="activity-line ${cls}">`
    + `<span class="activity-ts">${_escHtml(tsShort)}</span>`
    + `<span class="activity-op">${_escHtml(opLabel)}</span>`
    + `<span class="activity-mach">${_escHtml(mach)}</span>`
    + `<span class="activity-tail"${tailAttr}>${_escHtml(c.text || "")}${tailMark}</span>`
    + `</div>`;
}

function ensureFastPolling() {
  const wantFast =
    state.currentRunId && String(state.currentRunStatus || "").toLowerCase() === "running";
  if (wantFast && state.fastTimer == null) {
    // Refresh the unified-log meter immediately on run start (don't wait a tick).
    // The recurring meter refresh stays on the single activityTimer (1s) so two
    // timers never race on the activitySince cursor.
    refreshActivityStrip().catch(() => {});
    state.fastTimer = setInterval(() => {
      refreshCurrentRun().catch(() => {});
    }, 1000);
  } else if (!wantFast && state.fastTimer != null) {
    clearInterval(state.fastTimer);
    state.fastTimer = null;
    // Run ended — refresh once more so the meter clears / shows the final line.
    refreshActivityStrip().catch(() => {});
  }
}

async function boot() {
  applyI18n();
  buildCharts();
  bindEvents();
  try {
    await loadBootstrap();
    startPolling();
    // Restore compare mode from URL after bootstrap so the user
    // can share / bookmark a ?compare=A,B link. Failure is silent
    // (bad URL just clears the param + falls through to single-
    // report mode).
    try { await _restoreCompareFromUrl(); } catch (_) {}
  } catch (e) {
    setHealth(false, String(e.message || e));
  } finally {
    // Phase 3 (D11): wire P3 panels regardless of any boot error.
    // Defense-in-depth: even if loadBootstrap() throws (e.g. a
    // future API added inside it returns an unexpected status), the
    // config-upload and fleet-refresh click handlers must still bind.
    // In the normal (no-throw) path these are re-called after
    // loadBootstrap already called them, but _initConfigUploadPanel /
    // _initFleetRefreshPanel are idempotent (they replace listeners).
    _initConfigUploadPanel();
    _initFleetRefreshPanel();
    _initAutoInspectTab();
  }
}

// ── Phase 3 (D11): Config upload panel ──────────────────────────────

function renderConfigList() {
  const wrap = byId("configListWrap");
  if (!wrap) return;
  const configs = state.uploadedConfigs || [];
  if (configs.length === 0) {
    wrap.innerHTML = `<p class="muted">${fmt("configListEmpty")}</p>`;
    return;
  }
  const header = fmt("configListHeader", { count: configs.length });
  const rows = configs.map((c) =>
    `<div class="config-list-row">
      <span class="config-id-badge" title="${_escHtml(c.config_id || "")}">${_escHtml((c.config_id || "").slice(0, 8))}</span>
      <span class="config-display-name">${_escHtml(c.display_name || "")}</span>
      <span class="muted config-uploaded-at">${_escHtml((c.uploaded_at || "").slice(0, 16))}</span>
    </div>`
  ).join("");
  wrap.innerHTML = `<p class="muted">${_escHtml(header)}</p>${rows}`;
}

async function refreshConfigList() {
  try {
    const data = await apiGet("/api/configs");
    state.uploadedConfigs = Array.isArray(data.entries) ? data.entries : [];
    renderConfigList();
  } catch (_) {
    // 404 means fleet_refresh_enabled=False (virtual console) — hide silently.
  }
}

async function _handleConfigUpload() {
  const fileInput = byId("configFileInput");
  const nameInput = byId("configDisplayNameInput");
  const statusEl = byId("configUploadStatus");
  if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
    if (statusEl) statusEl.textContent = fmt("configUploadNoFile");
    return;
  }
  const file = fileInput.files[0];
  const displayName = (nameInput && nameInput.value.trim()) || file.name;
  if (statusEl) statusEl.textContent = "...";
  try {
    const text = await file.text();
    const content = JSON.parse(text);  // validate JSON client-side
    const result = await apiPost("/api/configs/upload", {
      content,
      display_name: displayName,
    });
    if (statusEl) statusEl.textContent = fmt("configUploadOk", { id: (result.config_id || "").slice(0, 8) });
    if (fileInput) fileInput.value = "";
    if (nameInput) nameInput.value = "";
    await refreshConfigList();
  } catch (e) {
    if (statusEl) statusEl.textContent = fmt("configUploadErr", { error: String(e.message || e).slice(0, 60) });
  }
}

// ── Phase 3 (D11): Fleet refresh panel with one-shot guard ──────────
// Per memory/feedback_fasttimer_overlap_needs_oneshot.md: use
// _autoRefreshedForFleetRefreshId so each completion fires once.

async function refreshFleetRefreshPanel() {
  const startBtn = byId("fleetRefreshStartBtn");
  const cancelBtn = byId("fleetRefreshCancelBtn");
  const statusEl = byId("fleetRefreshStatus");
  const progressDiv = byId("fleetRefreshProgress");
  const metaEl = byId("fleetRefreshProgressMeta");
  const barInner = byId("fleetRefreshProgressInner");

  let data = null;
  try {
    data = await apiGet("/api/fleet/refresh");
  } catch (e) {
    // Genuine error (network/5xx). "No queue" is no longer a 404 — the endpoint
    // now returns a 200 idle payload (handled below), so this path only fires on
    // a real failure.
    if (startBtn) startBtn.disabled = false;
    if (cancelBtn) cancelBtn.classList.add("hidden");
    if (statusEl) statusEl.textContent = fmt("fleetRefreshIdle");
    if (progressDiv) progressDiv.classList.add("hidden");
    if (state.fleetRefreshPollTimer) {
      clearInterval(state.fleetRefreshPollTimer);
      state.fleetRefreshPollTimer = null;
    }
    return;
  }

  // Idle 200 payload (no queue ever / unresolvable): render the idle state —
  // start enabled, no progress bar, polling stopped (same as the old 404 path).
  if (!data || !data.queue_id || data.status === "idle") {
    if (startBtn) startBtn.disabled = false;
    if (cancelBtn) cancelBtn.classList.add("hidden");
    if (statusEl) statusEl.textContent = fmt("fleetRefreshIdle");
    if (progressDiv) progressDiv.classList.add("hidden");
    if (state.fleetRefreshPollTimer) {
      clearInterval(state.fleetRefreshPollTimer);
      state.fleetRefreshPollTimer = null;
    }
    return;
  }

  const queueStatus = data.status || "unknown";
  const total = data.total_items || 0;
  const done = (data.completed_items || 0) + (data.skipped_items || 0);
  const failed = data.failed_items || 0;
  const skipped = data.skipped_items || 0;
  const queueId = data.queue_id || null;

  if (queueStatus === "running") {
    if (startBtn) startBtn.disabled = true;
    if (cancelBtn) cancelBtn.classList.remove("hidden");
    if (statusEl) statusEl.textContent = fmt("fleetRefreshRunning", { done, total });
    if (progressDiv) progressDiv.classList.remove("hidden");
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    if (barInner) barInner.style.width = pct + "%";
    if (metaEl) metaEl.textContent = `${done}/${total} (${pct}%) — failed=${failed} skipped=${skipped}`;
  } else {
    if (startBtn) startBtn.disabled = false;
    if (cancelBtn) cancelBtn.classList.add("hidden");
    if (queueStatus === "completed") {
      if (statusEl) statusEl.textContent = fmt("fleetRefreshDone", { done, total, skipped });
    } else if (queueStatus === "cancelled") {
      if (statusEl) statusEl.textContent = fmt("fleetRefreshCancelled");
    } else {
      if (statusEl) statusEl.textContent = fmt("fleetRefreshIdle");
    }
    if (progressDiv) progressDiv.classList.remove("hidden");
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    if (barInner) barInner.style.width = pct + "%";
    if (metaEl) metaEl.textContent = `${done}/${total} (${pct}%) — failed=${failed} skipped=${skipped}`;

    // One-shot guard: fire side-effects on completion/cancel exactly once
    // per queue_id transition. JS single-threaded guarantee makes check+set atomic.
    if (queueId && state._autoRefreshedForFleetRefreshId !== queueId) {
      state._autoRefreshedForFleetRefreshId = queueId;
      // Side-effects: refresh machines summary etc.
      refreshRunList(false).catch(() => {});
    }

    // Stop polling for a finished queue.
    if (state.fleetRefreshPollTimer) {
      clearInterval(state.fleetRefreshPollTimer);
      state.fleetRefreshPollTimer = null;
    }
  }

  state.fleetRefreshQueueId = queueId;
}

async function _startFleetRefresh() {
  const startBtn = byId("fleetRefreshStartBtn");
  const statusEl = byId("fleetRefreshStatus");
  if (startBtn) startBtn.disabled = true;
  try {
    const result = await apiPost("/api/fleet/refresh", {});
    state.fleetRefreshQueueId = result.queue_id || null;
    // Reset one-shot guard for the new queue.
    state._autoRefreshedForFleetRefreshId = null;
    // Start polling.
    if (state.fleetRefreshPollTimer) clearInterval(state.fleetRefreshPollTimer);
    state.fleetRefreshPollTimer = setInterval(() => {
      refreshFleetRefreshPanel().catch(() => {});
    }, 3000);
    await refreshFleetRefreshPanel();
  } catch (e) {
    if (statusEl) {
      const msg = String((e && e.detail) || (e && e.message) || e);
      statusEl.textContent = msg.includes("already running")
        ? fmt("fleetRefreshConflict")
        : fmt("configUploadErr", { error: msg.slice(0, 60) });
    }
    if (startBtn) startBtn.disabled = false;
  }
}

async function _cancelFleetRefresh() {
  try {
    await apiFetch("/api/fleet/refresh", { method: "DELETE" });
    await refreshFleetRefreshPanel();
  } catch (e) {
    const statusEl = byId("fleetRefreshStatus");
    if (statusEl) statusEl.textContent = String((e && e.detail) || (e && e.message) || e).slice(0, 60);
  }
}

function _initFleetRefreshPanel() {
  const startBtn = byId("fleetRefreshStartBtn");
  const cancelBtn = byId("fleetRefreshCancelBtn");
  if (startBtn) startBtn.addEventListener("click", _startFleetRefresh);
  if (cancelBtn) cancelBtn.addEventListener("click", _cancelFleetRefresh);
  // Initial poll to recover state from a previous session.
  refreshFleetRefreshPanel().catch(() => {});
}

// ── 2026-05-26 B2: persistent batch history panel ────────────
//
// Single source of truth: GET /api/batches. Lists recent sampling +
// generate batches across every console session by reading the
// batches SQLite table (L2 + L3 persist there). The previous problem
// the operator hit:
//   "I launched 全量 yesterday, console restarted overnight, today
//    I refresh and see nothing — no idea if it ran or not."
// This panel sits in the action area + auto-refreshes every 10s
// so the first-glance view always shows what's been done.

function _initBatchHistoryPanel() {
  const btn = byId("batchHistoryRefreshBtn");
  if (btn) btn.addEventListener("click", () => refreshBatchHistoryPanel());
  // Initial render + start the auto-refresh loop.
  refreshBatchHistoryPanel().catch(() => {});
  // 10s cadence: balances "feels responsive when a batch is running"
  // vs "doesn't hammer the API while operator is reading something
  // else." Active batches also update via their own poll, so this
  // is just the safety-net refresh.
  if (state.batchHistoryTimer) clearInterval(state.batchHistoryTimer);
  state.batchHistoryTimer = setInterval(() => {
    refreshBatchHistoryPanel().catch(() => {});
  }, 10000);
}

async function refreshBatchHistoryPanel() {
  const container = byId("batchHistoryRows");
  if (!container) return;
  let data;
  try {
    data = await apiGet("/api/batches?limit=15");
  } catch (e) {
    container.textContent = "(无法获取批次历史: " + (e.message || e) + ")";
    return;
  }
  const rows = data.batches || [];
  if (rows.length === 0) {
    container.innerHTML = '<div class="batch-history-empty">没有批次记录 — 启动一次采样后这里会显示历史。</div>';
    return;
  }
  // Render compact rows: icon, time, kind, status, counts. Click
  // opens the detail via the existing GET /api/batch-run/{id} path
  // (which now serves from DB for completed batches per B1).
  const statusIcon = {
    running: "▶", pending: "⏳", completed: "✓",
    cancelled: "⏸", partial: "⚠", failed: "✗",
  };
  const kindIcon = { sampling: "🎰", generate: "📊" };
  const html = rows.map((b) => {
    const sIcon = statusIcon[b.status] || "?";
    const kIcon = kindIcon[b.kind] || "·";
    const created = (b.created_at || "").slice(11, 19);  // HH:MM:SS
    const day = (b.created_at || "").slice(5, 10);  // MM-DD
    const counts = b.item_status_counts || {};
    const done = counts.completed || 0;
    const failed = counts.failed || 0;
    const cancelled = counts.cancelled || 0;
    const pending = (counts.pending || 0) + (counts.running || 0);
    const total = b.total_items || 0;
    const countSummary = total > 0
      ? `${done}/${total}` + (failed > 0 ? ` · ✗${failed}` : "") + (cancelled > 0 ? ` · ⏸${cancelled}` : "") + (pending > 0 ? ` · ▶${pending}` : "")
      : "(空)";
    const kindLabel = b.kind === "generate" ? "重生成" : "采样";
    return `<div class="batch-history-row batch-history-status-${b.status || 'unknown'}"
                 data-batch-id="${b.batch_id}"
                 data-kind="${b.kind}"
                 title="${b.batch_id}">
              <span class="batch-history-icon">${sIcon}${kIcon}</span>
              <span class="batch-history-time">${day} ${created}</span>
              <span class="batch-history-kind">${kindLabel}</span>
              <span class="batch-history-status">${b.status || "?"}</span>
              <span class="batch-history-counts">${countSummary}</span>
            </div>`;
  }).join("");
  container.innerHTML = html;
  // Click handler: log the detail to console for now. Future:
  // open a side-panel with full items + events.
  container.querySelectorAll(".batch-history-row").forEach((el) => {
    el.addEventListener("click", async () => {
      const bid = el.getAttribute("data-batch-id");
      const kind = el.getAttribute("data-kind");
      try {
        const url = kind === "generate"
          ? `/api/rawdata/batch-generate-report/${bid}`
          : `/api/batch-run/${bid}`;
        const detail = await apiGet(url);
        // Brief inline summary (no big modal needed for the MVP).
        const items = detail.items || [];
        const itemSummary = items.slice(0, 20)
          .map((it) => `  ${it.machine} m${it.mode} -> ${it.status}${it.run_id ? " ("+it.run_id.slice(0,8)+")" : ""}`)
          .join("\n");
        const more = items.length > 20 ? `\n  ... (+${items.length - 20} more)` : "";
        const fromHist = detail.from_history ? " [from DB history]" : "";
        alert(`Batch ${bid}${fromHist}\nStatus: ${detail.status}\nItems (${items.length}):\n${itemSummary}${more}`);
      } catch (e) {
        alert("无法读取批次详情: " + (e.message || e));
      }
    });
  });
}

function _initConfigUploadPanel() {
  const uploadBtn = byId("configUploadBtn");
  if (uploadBtn) uploadBtn.addEventListener("click", _handleConfigUpload);
  // I1 (Option B): config_id is not yet wired through the sampling path —
  // uploaded configs are stored in the registry but chunks are always tagged
  // "null" in the sidecar regardless of which config was selected.
  // Surface a prominent warning so operators know the feature is partial.
  const wrapEl = byId("configListWrap");
  if (wrapEl) {
    const warningId = "configWiringWarning";
    if (!document.getElementById(warningId)) {
      const warn = document.createElement("p");
      warn.id = warningId;
      warn.className = "muted config-wiring-warning";
      warn.style.cssText = "color:#b45309;font-style:italic;margin-top:6px";
      warn.textContent = "⚠ 当前 config 选择对采样无效 — 所有 chunks 仍标记为 \"null\" 桶。config_id 路由为后续 follow-up。";
      wrapEl.parentNode.insertBefore(warn, wrapEl);
    }
  }
  refreshConfigList().catch(() => {});
}

boot();

// ── P4: Auto-Inspect tab ─────────────────────────────────────────────────
//
// Per memory/feedback_no_parallel_panel_impl.md:
//   - Reuses .panel, .meta, .drilldown-table, apiGet/apiPost/apiPut helpers
//   - Reuses switchTab() from existing tab mechanism
//   - No new parallel fetch helpers
//
// Per memory/feedback_no_silent_swallow.md:
//   - Every catch block shows visible error to user (status span or banner)
//
// Per memory/feedback_fasttimer_overlap_needs_oneshot.md:
//   - _aiAutoActedForSweepId guards the "sweep completed" side-effect

// ── Status label helpers ──────────────────────────────────────────────────

function _aiSweepStatusLabel(status) {
  const map = {
    scanning:   fmt("aiStatusScanning"),
    sampling:   fmt("aiStatusSampling"),
    finalizing: fmt("aiStatusFinalizing"),
    completed:  fmt("aiSweepCompleted"),
    cancelled:  fmt("aiSweepCancelled"),
    failed:     fmt("aiSweepFailed"),
  };
  return map[status] || status || "—";
}

function _aiItemStatusLabel(status) {
  const map = {
    pending:                  fmt("aiStatusPending"),
    claimed:                  fmt("aiStatusClaimed"),
    running:                  fmt("aiStatusRunning"),
    generating:               fmt("aiStatusGenerating"),
    completed:                fmt("aiStatusCompleted"),
    failed:                   fmt("aiStatusFailed"),
    structural_skip:          fmt("aiStatusStructuralSkip"),
    convergence_timeout:      fmt("aiStatusConvergenceTimeout"),
    manifest_override_partial: fmt("aiStatusManifestPartial"),
    deferred_lock_conflict:   fmt("aiStatusDeferredLock"),
    wall_time_timeout:        fmt("aiStatusWallTime"),
    md5_drift_invalidated:    fmt("aiStatusMd5Drift"),
    cancelled:                fmt("aiStatusCancelled"),
  };
  return map[status] || status || "—";
}

function _aiItemStatusIcon(status) {
  const icons = {
    completed: "✓",
    failed:    "✗",
    running:   "⟳",
    generating: "⟳",
    structural_skip: "⏭",
    convergence_timeout: "⏱",
    manifest_override_partial: "⚠",
    deferred_lock_conflict: "⏳",
    wall_time_timeout: "⏱",
    md5_drift_invalidated: "⚡",
    cancelled: "✕",
    pending:   "·",
    claimed:   "·",
  };
  return icons[status] || "·";
}

function _aiSweepStatusIcon(status) {
  const icons = {
    scanning:   "⟳",
    sampling:   "⟳",
    finalizing: "⟳",
    completed:  "✓",
    cancelled:  "✕",
    failed:     "✗",
  };
  return icons[status] || "·";
}

// ── Settings load / save ─────────────────────────────────────────────────

function _aiLoadSettingsIntoForm(settings) {
  // settings is the auto_sweep block from GET /api/settings
  const as = settings || {};

  const enabledEl = byId("aiEnabled");
  if (enabledEl) enabledEl.checked = Boolean(as.enabled);

  const skipFreshEl = byId("aiSkipFreshCells");
  if (skipFreshEl) skipFreshEl.checked = (as.skip_fresh_cells !== false);

  // Schedule mode picker
  const sm = as.schedule_mode || "daily";
  const rdDaily = byId("aiScheduleDaily");
  const rdInterval = byId("aiScheduleInterval");
  if (rdDaily) rdDaily.checked = (sm === "daily");
  if (rdInterval) rdInterval.checked = (sm === "interval");

  const sv = String(as.schedule_value || "02:00");
  if (sm === "daily") {
    const timeEl = byId("aiScheduleTime");
    if (timeEl) timeEl.value = sv;
  } else {
    const nEl = byId("aiScheduleIntervalN");
    if (nEl) nEl.value = sv;
  }
  _aiUpdateScheduleVisibility();

  // Scalar ints
  const intFields = {
    aiSweepConcurrency:       "sweep_concurrency",
    aiBinaryGroupLargeCap:    "binary_group_large_cap",
    aiMaxConsecutiveFailures: "max_consecutive_failures",
    aiConsecutiveFailureWindow: "consecutive_failure_window",
    aiCellBusyTimeoutS:       "cell_busy_timeout_s",
    aiWallTimePerCellS:       "wall_time_per_cell_s",
  };
  for (const [elId, key] of Object.entries(intFields)) {
    const el = byId(elId);
    if (el && as[key] != null) el.value = as[key];
  }

  // Structural skip machines (list → comma-separated string)
  const ssmEl = byId("aiStructuralSkipMachines");
  if (ssmEl) {
    const ssm = as.structural_skip_machines;
    ssmEl.value = Array.isArray(ssm) ? ssm.join(",") : (ssm || "");
  }

  // Per-mode fields
  const modes_cfg = as.modes || {};
  document.querySelectorAll("#aiModeTableBody tr[data-mode]").forEach((row) => {
    const mode = row.dataset.mode;
    const modeCfg = modes_cfg[mode] || {};
    row.querySelectorAll("input.ai-mode-field").forEach((inp) => {
      const field = inp.dataset.field;
      if (modeCfg[field] != null) inp.value = modeCfg[field];
    });
  });
}

function _aiCollectSettingsFromForm() {
  const as = {};

  const enabledEl = byId("aiEnabled");
  as.enabled = enabledEl ? enabledEl.checked : false;

  const skipFreshEl = byId("aiSkipFreshCells");
  as.skip_fresh_cells = skipFreshEl ? skipFreshEl.checked : true;

  // Schedule picker
  const rdDaily = byId("aiScheduleDaily");
  as.schedule_mode = (rdDaily && rdDaily.checked) ? "daily" : "interval";
  if (as.schedule_mode === "daily") {
    const timeEl = byId("aiScheduleTime");
    as.schedule_value = (timeEl && timeEl.value) || "02:00";
    // Validate HH:MM format
    if (!/^\d{2}:\d{2}$/.test(as.schedule_value)) {
      throw new Error("时间格式必须为 HH:MM（如 02:00）");
    }
  } else {
    const nEl = byId("aiScheduleIntervalN");
    const n = parseInt((nEl && nEl.value) || "6", 10);
    if (n < 1 || n > 24) {
      throw new Error("间隔小时数必须在 1-24 之间");
    }
    as.schedule_value = String(n);
  }

  // Scalar int fields
  const intFields = {
    aiSweepConcurrency:       "sweep_concurrency",
    aiBinaryGroupLargeCap:    "binary_group_large_cap",
    aiMaxConsecutiveFailures: "max_consecutive_failures",
    aiConsecutiveFailureWindow: "consecutive_failure_window",
    aiCellBusyTimeoutS:       "cell_busy_timeout_s",
    aiWallTimePerCellS:       "wall_time_per_cell_s",
  };
  for (const [elId, key] of Object.entries(intFields)) {
    const el = byId(elId);
    if (el) as[key] = parseInt(el.value || "0", 10);
  }

  // Structural skip machines
  const ssmEl = byId("aiStructuralSkipMachines");
  if (ssmEl) {
    const raw = (ssmEl.value || "").trim();
    as.structural_skip_machines = raw
      ? raw.split(",").map((s) => s.trim()).filter(Boolean)
      : [];
  }

  // Per-mode
  as.modes = {};
  document.querySelectorAll("#aiModeTableBody tr[data-mode]").forEach((row) => {
    const mode = row.dataset.mode;
    const modeCfg = {};
    row.querySelectorAll("input.ai-mode-field").forEach((inp) => {
      const field = inp.dataset.field;
      if (field === "target_halfwidth_pp") {
        modeCfg[field] = parseFloat(inp.value || "0.5");
      } else {
        modeCfg[field] = parseInt(inp.value || "0", 10);
      }
    });
    as.modes[mode] = modeCfg;
  });

  return as;
}

function _aiUpdateScheduleVisibility() {
  const rdDaily = byId("aiScheduleDaily");
  const timeEl = byId("aiScheduleTime");
  const nEl = byId("aiScheduleIntervalN");
  if (!rdDaily) return;
  const isDaily = rdDaily.checked;
  if (timeEl) timeEl.style.display = isDaily ? "" : "none";
  if (nEl) nEl.style.display = isDaily ? "none" : "";
}

async function _aiSaveSettings() {
  const statusEl = byId("aiSettingsStatus");
  if (statusEl) statusEl.textContent = "...";
  try {
    const as = _aiCollectSettingsFromForm();
    await apiPut("/api/settings", { auto_sweep: as });
    if (statusEl) statusEl.textContent = fmt("aiSettingsSaved");
    setTimeout(() => {
      if (statusEl && statusEl.textContent === fmt("aiSettingsSaved")) {
        statusEl.textContent = "";
      }
    }, 3000);
  } catch (e) {
    if (statusEl) statusEl.textContent = fmt("aiSettingsError", {
      error: String(e.message || e).slice(0, 80),
    });
  }
}

// ── Preview ───────────────────────────────────────────────────────────────

async function _aiRunPreview() {
  const previewBody = byId("aiPreviewBody");
  if (!previewBody) return;
  previewBody.textContent = fmt("aiPreviewLoading");
  previewBody.className = "ai-preview-body";
  try {
    const data = await apiGet("/api/auto-inspect/preview");
    const total = data.total || 0;
    if (total === 0) {
      previewBody.innerHTML = `<span class="muted">${fmt("aiPreviewEmpty")}</span>`;
      return;
    }
    const estSecs = data.estimated_wall_time_s || (total * 300);
    const hours = Math.floor(estSecs / 3600);
    const mins = Math.floor((estSecs % 3600) / 60);
    const skip = data.structural_skip_count || 0;
    const override = data.manifest_override_count || 0;

    const summaryLine = fmt("aiPreviewResult", { total, hours, mins, skip, override });

    // Per-mode breakdown
    const byMode = data.by_mode || {};
    const modeLines = Object.entries(byMode)
      .sort((a, b) => Number(a[0]) - Number(b[0]))
      .map(([mode, count]) => fmt("aiPreviewByMode", { mode, count }))
      .join(" · ");

    // Cell-class breakdown
    const byCc = data.by_cell_class || {};
    const ccLines = Object.entries(byCc)
      .map(([cc, count]) => `${cc}: ${count}`)
      .join(", ");

    let html = `<div><strong>${summaryLine}</strong></div>`;
    if (modeLines) html += `<div class="ai-preview-by-mode">${modeLines}</div>`;
    if (ccLines) html += `<div class="ai-preview-by-mode">${ccLines}</div>`;
    if (skip > 0) {
      html += `<div class="ai-preview-warn">⚠ ${skip} 个机台在结构跳过名单 — 仅标记 structural_skip，不实际采样</div>`;
    }
    if (override > 0) {
      html += `<div class="ai-preview-warn">⚠ ${override} 个 manifest_override 机台 — 会正常采样，请确认 manifest 配置</div>`;
    }

    previewBody.innerHTML = html;
  } catch (e) {
    previewBody.innerHTML = `<span style="color:var(--danger)">${fmt("aiPreviewError", { error: String(e.message || e).slice(0, 100) })}</span>`;
  }
}

// ── Start / Cancel ────────────────────────────────────────────────────────

async function _aiStartSweep() {
  const statusEl = byId("aiSweepStatus");
  if (statusEl) statusEl.textContent = "...";
  try {
    const data = await apiPost("/api/auto-inspect/start", {});
    state.aiCurrentSweepId = data.sweep_id;
    state._aiAutoActedForSweepId = null;
    _aiStartPoll();
    _aiRenderSweepControls(true);
    if (statusEl) statusEl.textContent = "";
  } catch (e) {
    const msg = String(e.message || e);
    const isConflict = msg.includes("409") || msg.toLowerCase().includes("already running") || msg.toLowerCase().includes("active");
    if (statusEl) statusEl.textContent = isConflict
      ? fmt("aiSweepConflict")
      : String(e.message || e).slice(0, 120);
  }
}

async function _aiCancelSweep() {
  const sweepId = state.aiCurrentSweepId;
  if (!sweepId) return;
  try {
    await apiPost(`/api/auto-inspect/${sweepId}/cancel`, {});
    // Poll will detect terminal state + stop itself.
  } catch (e) {
    const statusEl = byId("aiSweepStatus");
    if (statusEl) statusEl.textContent = String(e.message || e).slice(0, 80);
  }
}

// ── Live progress polling ────────────────────────────────────────────────

function _aiStartPoll() {
  _aiStopPoll();
  state.aiPollTimer = setInterval(() => {
    _aiPollOnce().catch(() => {});
  }, 5000);
  // Immediate first paint
  _aiPollOnce().catch(() => {});
}

function _aiStopPoll() {
  if (state.aiPollTimer) {
    clearInterval(state.aiPollTimer);
    state.aiPollTimer = null;
  }
}

async function _aiPollOnce() {
  const sweepId = state.aiCurrentSweepId;
  if (!sweepId) return;
  let data;
  try {
    data = await apiGet(`/api/auto-inspect/${sweepId}`);
  } catch (_) {
    return; // transient error — don't reset UI
  }
  _aiRenderProgress(data);

  // Stop polling when sweep reaches terminal state.
  const terminalStatuses = new Set(["completed", "cancelled", "failed"]);
  if (terminalStatuses.has(data.status)) {
    _aiStopPoll();
    _aiRenderSweepControls(false);

    // One-shot: refresh history once after terminal.
    if (state._aiAutoActedForSweepId !== sweepId) {
      state._aiAutoActedForSweepId = sweepId;
      _aiLoadHistory().catch(() => {});
    }
  }
}

// ── Progress rendering ───────────────────────────────────────────────────

function _aiRenderProgress(data) {
  const progressBody = byId("aiProgressBody");
  const bannerEl = byId("aiProgressBanner");
  if (!data || !progressBody) return;

  progressBody.classList.remove("hidden");

  const total = data.total_items || 0;
  const done = data.completed_items || 0;
  const failed = data.failed_items || 0;
  const skipped = data.skipped_items || 0;
  const byStatus = data.items_by_status || {};
  const pending = (byStatus.pending || 0) + (byStatus.claimed || 0)
    + (byStatus.running || 0) + (byStatus.generating || 0);

  if (bannerEl) {
    bannerEl.className = `ai-progress-banner status-${data.status || ""}`;
    bannerEl.innerHTML = `
      <strong>${_aiSweepStatusIcon(data.status)} ${_aiSweepStatusLabel(data.status)}</strong>
      &nbsp;&nbsp;
      ${fmt("aiCounterBanner", { done, total, failed, skipped, pending })}
      <span class="muted" style="margin-left:8px;font-size:11px">#${data.sweep_id || ""}</span>
    `.trim();
  }

  // Items drilldown
  _aiRenderItemsTable(data.items || []);
}

function _aiRenderItemsTable(items) {
  const tbody = byId("aiItemsBody");
  const filterEl = byId("aiItemFilter");
  if (!tbody) return;

  const filterVal = (filterEl && filterEl.value) || "all";
  const filtered = filterVal === "all"
    ? items
    : items.filter((it) => {
        if (filterVal === "pending") {
          return ["pending", "claimed", "running", "generating"].includes(it.status);
        }
        if (filterVal === "structural_skip") {
          return ["structural_skip", "convergence_timeout", "manifest_override_partial",
                  "deferred_lock_conflict", "wall_time_timeout", "md5_drift_invalidated",
                  "cancelled"].includes(it.status);
        }
        return it.status === filterVal;
      });

  tbody.innerHTML = filtered.map((it) => {
    const rowClass = `ai-row-${it.status || "pending"}`;
    const icon = _aiItemStatusIcon(it.status);
    const label = _aiItemStatusLabel(it.status);
    const reason = it.terminal_reason || "";
    return `<tr class="${rowClass}">
      <td>${it.machine || ""}</td>
      <td>${it.mode || ""}</td>
      <td><span class="ai-status-icon">${icon}</span> ${label}</td>
      <td>${it.cell_class || "easy"}</td>
      <td class="ai-reason" title="${reason.replace(/"/g, "&quot;")}">${reason.slice(0, 120)}</td>
    </tr>`;
  }).join("");
}

function _aiRenderSweepControls(sweepRunning) {
  const startBtn = byId("aiStartBtn");
  const cancelBtn = byId("aiCancelBtn");
  if (startBtn) startBtn.classList.toggle("hidden", sweepRunning);
  if (cancelBtn) cancelBtn.classList.toggle("hidden", !sweepRunning);
}

// ── History ───────────────────────────────────────────────────────────────

async function _aiLoadHistory() {
  const histBody = byId("aiHistoryBody");
  if (!histBody) return;
  try {
    const data = await apiGet("/api/auto-inspect?limit=10");
    const sweeps = (data.sweeps || []).slice(0, 10);
    if (sweeps.length === 0) {
      histBody.innerHTML = `<span class="muted">${fmt("aiHistoryEmpty")}</span>`;
      return;
    }
    histBody.innerHTML = sweeps.map((sw) => {
      const rowClass = `ai-history-row ai-row-${sw.status || ""}`;
      const icon = _aiSweepStatusIcon(sw.status);
      const label = _aiSweepStatusLabel(sw.status);
      const time = String(sw.created_at || "").slice(0, 16).replace("T", " ");
      const done = sw.completed_items || 0;
      const total = sw.total_items || 0;
      const trigger = sw.trigger === "cron"
        ? fmt("aiSweepTriggerCron")
        : fmt("aiSweepTriggerManual");
      return `<div class="${rowClass}" data-sweep-id="${sw.sweep_id || ""}" title="${fmt("aiHistoryClickHint")}">
        <span class="ai-history-icon">${icon}</span>
        <span class="ai-history-time">${time}</span>
        <span class="ai-history-status">${label}</span>
        <span class="ai-history-counts">${done}/${total}</span>
        <span class="ai-history-trigger">${trigger}</span>
      </div>`;
    }).join("");

    // Click on history row → load that sweep into the progress panel.
    histBody.querySelectorAll(".ai-history-row[data-sweep-id]").forEach((row) => {
      row.addEventListener("click", () => {
        const sid = row.dataset.sweepId;
        if (!sid) return;
        state.aiCurrentSweepId = sid;
        state._aiAutoActedForSweepId = null;
        // Show progress panel
        const progressBody = byId("aiProgressBody");
        if (progressBody) progressBody.classList.remove("hidden");
        // Non-terminal sweeps resume polling; terminal sweeps do one fetch.
        const terminalStatuses = new Set(["completed", "cancelled", "failed"]);
        const sweepStatus = row.querySelector(".ai-history-status");
        const isTerminal = sweepStatus && terminalStatuses.has(
          sweeps.find((s) => s.sweep_id === sid)?.status || ""
        );
        if (!isTerminal) {
          _aiStartPoll();
          _aiRenderSweepControls(true);
        } else {
          _aiStopPoll();
          _aiRenderSweepControls(false);
          _aiPollOnce().catch(() => {});
        }
      });
    });
  } catch (_) {
    histBody.innerHTML = `<span class="muted">${fmt("aiHistoryEmpty")}</span>`;
  }
}

// ── Tab open handler ──────────────────────────────────────────────────────

async function _onAutoInspectTabOpen() {
  // 1. Load settings → populate form
  try {
    const settings = await apiGet("/api/settings");
    _aiLoadSettingsIntoForm(settings.auto_sweep || {});
  } catch (_) { /* best effort */ }

  // 2. Check for an active (non-terminal) sweep
  try {
    const listData = await apiGet("/api/auto-inspect?limit=5");
    const sweeps = listData.sweeps || [];
    const nonTerminalStatuses = new Set(["scanning", "sampling", "finalizing"]);
    const active = sweeps.find((s) => nonTerminalStatuses.has(s.status));
    if (active) {
      state.aiCurrentSweepId = active.sweep_id;
      state._aiAutoActedForSweepId = null;
      _aiStartPoll();
      _aiRenderSweepControls(true);
    } else {
      // Show last completed/cancelled sweep detail if any
      const last = sweeps[0];
      if (last) {
        state.aiCurrentSweepId = last.sweep_id;
        state._aiAutoActedForSweepId = last.sweep_id; // already terminal
        _aiStopPoll();
        _aiRenderSweepControls(false);
        // One-time render without starting poll
        const progressBody = byId("aiProgressBody");
        if (progressBody) progressBody.classList.remove("hidden");
        _aiPollOnce().catch(() => {});
      }
    }
  } catch (_) { /* best effort */ }

  // 3. Load history list
  _aiLoadHistory().catch(() => {});
}

// ── Init (wires click handlers, schedule toggle) ─────────────────────────

function _initAutoInspectTab() {
  // Schedule radio toggles visibility
  const rdDaily = byId("aiScheduleDaily");
  const rdInterval = byId("aiScheduleInterval");
  if (rdDaily) rdDaily.addEventListener("change", _aiUpdateScheduleVisibility);
  if (rdInterval) rdInterval.addEventListener("change", _aiUpdateScheduleVisibility);

  // Save settings
  const saveBtn = byId("aiSaveSettingsBtn");
  if (saveBtn) saveBtn.addEventListener("click", _aiSaveSettings);

  // Preview
  const previewBtn = byId("aiPreviewBtn");
  if (previewBtn) previewBtn.addEventListener("click", _aiRunPreview);

  // Start / Cancel
  const startBtn = byId("aiStartBtn");
  if (startBtn) startBtn.addEventListener("click", _aiStartSweep);
  const cancelBtn = byId("aiCancelBtn");
  if (cancelBtn) cancelBtn.addEventListener("click", _aiCancelSweep);

  // Filter dropdown: re-render items with new filter (if data in state)
  const filterEl = byId("aiItemFilter");
  if (filterEl) filterEl.addEventListener("change", () => {
    // Re-fetch current sweep items
    if (state.aiCurrentSweepId) _aiPollOnce().catch(() => {});
  });

  // Initial schedule visibility
  _aiUpdateScheduleVisibility();
}
