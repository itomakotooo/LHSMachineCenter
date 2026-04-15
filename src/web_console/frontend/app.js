// I18N + pure helpers come from window.PURE (loaded by /console/pure.js).
// Lang-dependent helpers (fmt, statusText, cacheRiskTier, cacheRiskView,
// collectSystemWarnings, modelWarnings) are wrapped below to read from `state`.
const I18N = PURE.I18N;
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
  autoTuneRunning: false,
  busyActions: new Set(),
  ciChart: null,
  rtpChart: null,
  bucketChart: null,
  bankChart: null,
};

const byId = (id) => document.getElementById(id);
const fmt = (k, vars) => PURE.fmt(state.lang, k, vars);

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
  return PURE.modelWarnings({
    provider: byId("providerSelect").value || state.modelMeta.active_provider || "gemini",
    selected: byId("modelSelect").value || "",
    catalog: state.modelMeta.provider_catalog || {},
    hasApiKey: Boolean(state.modelMeta.has_api_key),
    lang: state.lang,
  });
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
