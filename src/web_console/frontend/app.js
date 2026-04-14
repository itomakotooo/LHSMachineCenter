const state = {
  currentRunId: "",
  machines: [],
  modes: [],
  models: [],
  modelMeta: {},
  timer: null,
  ciChart: null,
  rtpChart: null,
  bucketChart: null,
  bankChart: null,
  latestSummary: null,
  autoTuneRunning: false,
};

function byId(id) {
  return document.getElementById(id);
}

async function apiGet(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

async function apiPost(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${url}: ${res.status} ${text}`);
  }
  return res.json();
}

function setHealth(text, ok = true) {
  const el = byId("health");
  el.textContent = text;
  el.style.color = ok ? "#0f766e" : "#b91c1c";
}

function setMeta(text) {
  byId("runMeta").textContent = text;
}

function setGlobalWarning(lines) {
  const el = byId("globalWarning");
  const cleaned = (lines || []).filter((x) => String(x || "").trim().length > 0);
  if (!cleaned.length) {
    el.textContent = "";
    el.classList.add("hidden");
    return;
  }
  el.textContent = cleaned.join(" | ");
  el.classList.remove("hidden");
}

function setProgress(rate) {
  const pct = Math.max(0, Math.min(100, rate));
  byId("progressBar").style.width = `${pct}%`;
}

function formatNum(v, d = 4) {
  if (v === null || v === undefined || Number.isNaN(v)) return "N/A";
  return Number(v).toFixed(d);
}

function formatInt(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "N/A";
  return new Intl.NumberFormat("en-US").format(Number(v));
}

function formatRatePct(rate, d = 2) {
  if (rate === null || rate === undefined || Number.isNaN(rate)) return "N/A";
  return `${(Number(rate) * 100).toFixed(d)}%`;
}

function setKpi(id, text, tone = "neutral") {
  const el = byId(id);
  el.textContent = text;
  el.dataset.tone = tone;
}

function resetKpis() {
  setKpi("kpiRtp", "N/A");
  setKpi("kpiCi", "N/A");
  setKpi("kpiSpins", "N/A");
  setKpi("kpiZero", "N/A");
  setKpi("kpiTail", "N/A");
  setKpi("kpiGuide", "N/A");
}

function clearDistributionCharts() {
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

function clearSummaryPanels() {
  state.latestSummary = null;
  byId("assessment").textContent = "No report yet.";
  resetKpis();
  clearDistributionCharts();
}

function buildCharts() {
  const ciCtx = byId("ciChart").getContext("2d");
  const rtpCtx = byId("rtpChart").getContext("2d");
  const bucketCtx = byId("bucketChart").getContext("2d");
  const bankCtx = byId("bankChart").getContext("2d");

  state.ciChart = new Chart(ciCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "CI Half-width",
          data: [],
          borderColor: "#0f766e",
          backgroundColor: "rgba(13,148,136,0.15)",
          tension: 0.2,
          pointRadius: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        y: { beginAtZero: true, title: { display: true, text: "pp" } },
      },
    },
  });

  state.rtpChart = new Chart(rtpCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "RTP %",
          data: [],
          borderColor: "#2563eb",
          backgroundColor: "rgba(37,99,235,0.15)",
          tension: 0.2,
          pointRadius: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        y: { beginAtZero: false, title: { display: true, text: "%" } },
      },
    },
  });

  state.bucketChart = new Chart(bucketCtx, {
    type: "bar",
    data: {
      labels: [],
      datasets: [
        {
          label: "Spin Rate %",
          data: [],
          backgroundColor: "#0d9488",
          borderColor: "#0f766e",
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, title: { display: true, text: "%" } },
      },
    },
  });

  state.bankChart = new Chart(bankCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Bankruptcy Rate %",
          data: [],
          borderColor: "#f97316",
          backgroundColor: "rgba(249,115,22,0.18)",
          tension: 0.25,
          pointRadius: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        y: { beginAtZero: true, title: { display: true, text: "%" } },
      },
    },
  });
}

function updateCharts(events) {
  const chunk = events.filter((e) => e.event === "chunk_progress");
  const labels = chunk.map((e) => String(e.chunk_index));
  const ci = chunk.map((e) => e.current_halfwidth_pp ?? null);
  const rtp = chunk.map((e) => e.current_rtp_pct ?? null);
  state.ciChart.data.labels = labels;
  state.ciChart.data.datasets[0].data = ci;
  state.ciChart.update();
  state.rtpChart.data.labels = labels;
  state.rtpChart.data.datasets[0].data = rtp;
  state.rtpChart.update();
}

function updateEvents(events) {
  const lines = events.slice(-50).map((e) => JSON.stringify(e));
  byId("eventsText").textContent = lines.join("\n");
}

function updateDistributionCharts(summary) {
  const buckets = summary?.player_impact?.multiplier_profile?.buckets || [];
  const bucketLabels = buckets.map((b) => String(b.bucket || ""));
  const bucketRates = buckets.map((b) => {
    const value = Number(b.spin_rate);
    if (!Number.isFinite(value)) return null;
    return value <= 1 ? value * 100 : value;
  });
  state.bucketChart.data.labels = bucketLabels;
  state.bucketChart.data.datasets[0].data = bucketRates;
  state.bucketChart.update();

  const bank = summary?.player_impact?.bankruptcy_probe || [];
  const bankLabels = bank.map((b) => `x${b.bankroll_multiplier}`);
  const bankRates = bank.map((b) => {
    const value = Number(b.bankruptcy_rate);
    if (!Number.isFinite(value)) return null;
    return value <= 1 ? value * 100 : value;
  });
  state.bankChart.data.labels = bankLabels;
  state.bankChart.data.datasets[0].data = bankRates;
  state.bankChart.update();
}

function updateLiveKpis(latest) {
  setKpi("kpiRtp", latest?.current_rtp_pct != null ? `${formatNum(latest.current_rtp_pct, 3)}%` : "N/A");
  setKpi("kpiCi", latest?.current_halfwidth_pp != null ? formatNum(latest.current_halfwidth_pp, 3) : "N/A");
  setKpi("kpiSpins", latest?.total_spins != null ? formatInt(latest.total_spins) : "N/A");
  if (!state.latestSummary) {
    setKpi("kpiZero", "N/A");
    setKpi("kpiTail", "N/A");
    setKpi("kpiGuide", "N/A");
  }
}

function updateSummaryKpis(summary) {
  const rtpPoint = summary?.rtp?.point_pct;
  const sampling = summary?.sampling || {};
  const ciInterval = summary?.rtp?.ci95_interval_pct;
  let achievedHalfwidth = sampling?.achieved_halfwidth_pp;
  if (
    achievedHalfwidth == null &&
    Array.isArray(ciInterval) &&
    ciInterval.length === 2 &&
    Number.isFinite(Number(ciInterval[0])) &&
    Number.isFinite(Number(ciInterval[1]))
  ) {
    achievedHalfwidth = Math.abs(Number(ciInterval[1]) - Number(ciInterval[0])) / 2;
  }
  const spins = sampling?.total_spins;
  const zeroRate = summary?.player_impact?.hit_and_payout?.zero_win_rate;
  const tailDep = summary?.guideline_assessment?.derived_metrics?.tail_dependency;
  const guidelineStatus =
    summary?.guideline_comparison?.overall_status || summary?.guideline_assessment?.data_quality?.quality_label || "N/A";

  setKpi("kpiRtp", rtpPoint != null ? `${formatNum(rtpPoint, 3)}%` : "N/A");
  setKpi("kpiCi", achievedHalfwidth != null ? formatNum(achievedHalfwidth, 3) : "N/A");
  setKpi("kpiSpins", spins != null ? formatInt(spins) : "N/A");
  setKpi("kpiZero", formatRatePct(zeroRate, 2));
  setKpi("kpiTail", tailDep != null ? formatNum(tailDep, 3) : "N/A");
  const tone = guidelineStatus === "PASS" ? "good" : guidelineStatus === "FAIL" ? "bad" : "warn";
  setKpi("kpiGuide", guidelineStatus, tone);
}

function updateAssessment(summary) {
  if (!summary || Object.keys(summary).length === 0) {
    byId("assessment").textContent = "No report yet.";
    return;
  }
  const ga = summary.guideline_assessment || {};
  const gc = summary.guideline_comparison || {};
  const cls = ga.classification || {};
  const q = ga.data_quality || {};
  const d = ga.derived_metrics || {};
  const alerts = ga.alerts || [];
  const actions = ga.action_recommendations || [];
  const block = [];
  block.push(`quality_label: ${q.quality_label || "N/A"}`);
  block.push(`volatility_class: ${cls.volatility_class || "N/A"}`);
  block.push(`experience_archetype: ${cls.experience_archetype || "N/A"}`);
  block.push(`recovery_gap: ${formatNum(d.recovery_gap)}`);
  block.push(`tail_dependency: ${formatNum(d.tail_dependency)}`);
  if (gc.overall_status) {
    block.push(
      `guideline_compare: ${gc.overall_status} (pass=${gc.pass_count ?? 0}, fail=${gc.fail_count ?? 0}, missing=${gc.missing_count ?? 0}, na=${gc.not_applicable_count ?? 0})`
    );
  }
  const failedChecks = Array.isArray(gc.checks)
    ? gc.checks.filter((x) => x.status === "fail" || x.status === "missing")
    : [];
  if (failedChecks.length) {
    block.push("guideline_failures:");
    failedChecks.slice(0, 8).forEach((x) => {
      block.push(
        `- [${x.severity || "medium"}][${x.status}] ${x.id || "UNKNOWN"}: observed=${x.observed ?? "N/A"} target=${JSON.stringify(
          x.target ?? "N/A"
        )}`
      );
    });
  }
  if (alerts.length) {
    block.push("alerts:");
    alerts.forEach((a) => block.push(`- [${a.severity}] ${a.code}: ${a.message}`));
  } else {
    block.push("alerts: none");
  }
  if (actions.length) {
    block.push("actions:");
    actions.forEach((a, i) => block.push(`${i + 1}. ${a}`));
  }
  byId("assessment").textContent = block.join("\n");
}

function summaryWarnings(summary) {
  const warnings = [];
  const ga = summary.guideline_assessment || {};
  const gc = summary.guideline_comparison || {};
  const quality = ga.data_quality?.quality_label || "";
  if (quality === "EXPLORATORY") {
    warnings.push("REPORT QUALITY = EXPLORATORY. Do not use this result for balancing decisions.");
  }
  if (gc.overall_status === "FAIL") {
    warnings.push(
      `GUIDELINE CHECK FAIL: fail=${gc.fail_count ?? 0}, missing=${gc.missing_count ?? 0}, hard_fail=${gc.hard_fail_count ?? 0}`
    );
  }
  const alerts = Array.isArray(ga.alerts) ? ga.alerts : [];
  alerts
    .filter((a) => ["high", "critical"].includes(String(a?.severity || "").toLowerCase()))
    .slice(0, 3)
    .forEach((a) => warnings.push(`ALERT ${a.code || "UNKNOWN"}: ${a.message || ""}`));
  return warnings;
}

function setModelStatus(info) {
  byId("modelStatus").textContent = info || "";
}

function modeValue() {
  return Number(byId("modeSelect").value || "1");
}

function machineValue() {
  return byId("machineSelect").value || "M14";
}

function providerValue() {
  return byId("providerSelect").value || state.modelMeta.active_provider || "gemini";
}

function modelValue() {
  return byId("modelSelect").value || "gemini-3-flash-preview";
}

function modelSelectionWarning() {
  const provider = providerValue();
  const selected = modelValue();
  const models = providerModels(provider);
  if (!models.includes(selected)) {
    return `Selected model does not belong to provider=${provider}.`;
  }
  if (!state.modelMeta.has_api_key) {
    return `${provider.toUpperCase()} API key is empty. Interpretation will fallback to rule-based.`;
  }
  return "";
}

function fillMachineModeSelectors() {
  const machineSel = byId("machineSelect");
  machineSel.innerHTML = "";
  state.machines.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m.machine;
    opt.textContent = m.machine;
    machineSel.appendChild(opt);
  });
  refreshModes();
}

function refreshModes() {
  const selected = machineValue();
  const machine = state.machines.find((m) => m.machine === selected) || state.machines[0];
  const modeSel = byId("modeSelect");
  modeSel.innerHTML = "";
  (machine?.modes || [1]).forEach((mode) => {
    const opt = document.createElement("option");
    opt.value = mode;
    opt.textContent = String(mode);
    modeSel.appendChild(opt);
  });
}

function providerModels(provider) {
  const catalog = state.modelMeta.provider_catalog || {};
  const models = catalog[provider];
  return Array.isArray(models) ? models : [];
}

function fillProviders() {
  const providerSel = byId("providerSelect");
  providerSel.innerHTML = "";
  const options = state.modelMeta.provider_options || ["gemini", "gpt", "claude"];
  options.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p;
    opt.textContent = p;
    providerSel.appendChild(opt);
  });
}

function fillModelsForProvider(provider, preferred = "") {
  const modelSel = byId("modelSelect");
  modelSel.innerHTML = "";
  const models = providerModels(provider);
  models.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    modelSel.appendChild(opt);
  });
  if (preferred && models.includes(preferred)) {
    modelSel.value = preferred;
  } else if (models.length) {
    modelSel.value = models[0];
  }
}

async function loadBootstrap() {
  const [health, machines, models] = await Promise.all([apiGet("/api/health"), apiGet("/api/machines"), apiGet("/api/models")]);
  setHealth(`API OK ${health.ts}`, true);
  state.machines = machines.machines || [];
  state.models = models.models || [];
  state.modelMeta = models || {};
  fillMachineModeSelectors();
  fillProviders();
  byId("providerSelect").value = state.modelMeta.active_provider || "gemini";
  fillModelsForProvider(providerValue(), state.modelMeta.default_model || "");
  setModelStatus(
    `provider=${state.modelMeta.active_provider || "unknown"} has_api_key=${String(
      !!state.modelMeta.has_api_key
    )} persisted=${String(!!state.modelMeta.config_persisted)} cleanup_policy=${state.modelMeta.cleanup_policy || "manual_only"}`
  );
  const bootWarnings = [...(state.modelMeta.warnings || [])];
  const selectedWarning = modelSelectionWarning();
  if (selectedWarning) bootWarnings.push(selectedWarning);
  setGlobalWarning(bootWarnings);
  byId("autotuneMeta").textContent = "No auto tune run yet.";
  clearSummaryPanels();
  await refreshCache();
  await refreshVersions();
  await refreshRunListAndAutoSelect();
}

async function saveModelConfig() {
  const payload = {
    provider: providerValue(),
    api_key: byId("apiKeyInput").value || "",
  };
  const models = await apiPost("/api/model-config", payload);
  state.modelMeta = models || {};
  state.models = models.models || [];
  fillProviders();
  byId("providerSelect").value = state.modelMeta.active_provider || providerValue();
  fillModelsForProvider(providerValue(), state.modelMeta.default_model || "");
  byId("apiKeyInput").value = "";
  setModelStatus(
    `provider=${state.modelMeta.active_provider || "unknown"} has_api_key=${String(
      !!state.modelMeta.has_api_key
    )} persisted=${String(!!state.modelMeta.config_persisted)} cleanup_policy=${state.modelMeta.cleanup_policy || "manual_only"}`
  );
  const warnings = [...(state.modelMeta.warnings || [])];
  const selectedWarning = modelSelectionWarning();
  if (selectedWarning) warnings.push(selectedWarning);
  setGlobalWarning(warnings);
}

function readRunPayload() {
  return {
    machine: machineValue(),
    mode: modeValue(),
    target_halfwidth_pp: Number(byId("ciInput").value),
    chunk_spin_times: Number(byId("spinInput").value),
    chunk_robot_count: Number(byId("robotInput").value),
    batch_concurrency: Number(byId("concInput").value),
    max_chunks: Number(byId("maxChunksInput").value),
    timeout: Number(byId("timeoutInput").value),
    bankruptcy_session_spins: Number(byId("bankSessionInput").value),
    bankruptcy_bankroll_multipliers: byId("bankMultInput").value,
    model_id: modelValue(),
  };
}

function sanitizeIntCandidates(values, lower, upper) {
  return [...new Set(values.map((v) => Math.round(Number(v))).filter((v) => Number.isFinite(v) && v >= lower && v <= upper))].sort(
    (a, b) => a - b
  );
}

function buildAutoTunePayload() {
  const baseRobot = Number(byId("robotInput").value || "20");
  const baseConc = Number(byId("concInput").value || "2");
  const spinRaw = Number(byId("spinInput").value || "120");
  const spinTimes = Math.max(60, Math.min(240, Number.isFinite(spinRaw) ? Math.round(spinRaw) : 120));
  const robotCandidates = sanitizeIntCandidates(
    [baseRobot - 8, baseRobot - 4, baseRobot, baseRobot + 4, baseRobot + 8],
    4,
    200
  );
  const concurrencyCandidates = sanitizeIntCandidates([1, baseConc - 1, baseConc, baseConc + 1, baseConc + 2], 1, 16);
  return {
    machine: machineValue(),
    mode: modeValue(),
    spin_times: spinTimes,
    robot_candidates: robotCandidates.length ? robotCandidates : [8, 12, 16, 20, 24],
    concurrency_candidates: concurrencyCandidates.length ? concurrencyCandidates : [1, 2, 3, 4],
    rounds: 2,
    timeout: 45,
    bet: 1000,
  };
}

function setAutoTuneBusy(isBusy) {
  state.autoTuneRunning = isBusy;
  const btn = byId("autotuneBtn");
  btn.disabled = isBusy;
  btn.textContent = isBusy ? "Auto Tuning..." : "Run Auto Tune";
}

function renderAutoTuneResult(result, payload) {
  const reco = result?.recommendation || {};
  if (reco.chunk_robot_count != null) byId("robotInput").value = String(reco.chunk_robot_count);
  if (reco.batch_concurrency != null) byId("concInput").value = String(reco.batch_concurrency);

  const lines = [];
  lines.push(`machine=${result.machine} mode=${result.mode} spin_times=${result.spin_times} rounds=${result.rounds}`);
  lines.push(`tested=${result.tested} candidates`);
  lines.push(`recommended chunk_robot_count=${reco.chunk_robot_count} batch_concurrency=${reco.batch_concurrency}`);
  const best = result.best || {};
  lines.push(
    `best throughput=${formatNum(best.throughput_spins_per_sec, 2)} spins/s success=${formatRatePct(
      best.success_rate,
      1
    )} p95=${formatNum(best.p95_latency_s, 3)}s wall=${formatNum(best.wall_elapsed_s, 2)}s`
  );
  lines.push("top results:");
  (result.results || []).slice(0, 8).forEach((item, idx) => {
    lines.push(
      `${idx + 1}. robot=${item.robot_count} conc=${item.batch_concurrency} success=${formatRatePct(
        item.success_rate,
        1
      )} throughput=${formatNum(item.throughput_spins_per_sec, 2)} p95=${formatNum(item.p95_latency_s, 3)}s`
    );
  });
  lines.push(
    `payload robots=[${(payload.robot_candidates || []).join(",")}] conc=[${(payload.concurrency_candidates || []).join(",")}]`
  );
  byId("autotuneMeta").textContent = lines.join("\n");
}

async function runAutoTune() {
  if (state.autoTuneRunning) return;
  const payload = buildAutoTunePayload();
  setAutoTuneBusy(true);
  byId("autotuneMeta").textContent =
    `Running quick stress test...\nmachine=${payload.machine} mode=${payload.mode} spin_times=${payload.spin_times}\n` +
    `robots=[${payload.robot_candidates.join(",")}] conc=[${payload.concurrency_candidates.join(",")}]`;
  try {
    const result = await apiPost("/api/autotune", payload);
    renderAutoTuneResult(result, payload);
    const best = result?.best || {};
    if (best.success_rate != null && Number(best.success_rate) < 0.95) {
      setGlobalWarning([
        ...(state.modelMeta.warnings || []),
        `Auto tune best success rate is ${formatRatePct(best.success_rate, 1)} (<95%). Consider reducing concurrency.`,
      ]);
    }
  } finally {
    setAutoTuneBusy(false);
  }
}

async function startRun() {
  clearSummaryPanels();
  byId("interpretationText").textContent = "";
  const payload = readRunPayload();
  const res = await apiPost("/api/runs", payload);
  state.currentRunId = res.run_id;
  await refreshCurrentRun();
}

async function stopRun() {
  if (!state.currentRunId) return;
  await apiPost(`/api/runs/${state.currentRunId}/cancel`, {});
  await refreshCurrentRun();
}

async function refreshRunListAndAutoSelect() {
  const data = await apiGet("/api/runs");
  const runs = data.runs || [];
  if (!state.currentRunId && runs.length) {
    state.currentRunId = runs[0].run_id;
  }
  if (state.currentRunId) {
    await refreshCurrentRun();
  }
}

async function refreshCurrentRun() {
  if (!state.currentRunId) return;
  const run = await apiGet(`/api/runs/${state.currentRunId}`);
  const p = run.progress || {};
  const latest = p.latest_event || {};
  const chunkCount = p.chunk_count || 0;
  const target = run.target_halfwidth_pp;
  const hw = latest.current_halfwidth_pp ?? null;
  const progressPct =
    hw === null || hw === undefined || !target ? 0 : hw <= target ? 100 : Math.min(100, (target / hw) * 100);
  setProgress(progressPct);
  setMeta(
    `run=${run.run_id} status=${run.status} machine=${run.machine} mode=${run.mode} spins=${latest.total_spins ?? 0} chunks=${chunkCount} ci=${formatNum(hw)} target=${target}`
  );
  updateLiveKpis(latest);

  const eventsData = await apiGet(`/api/runs/${state.currentRunId}/progress`);
  const events = eventsData.events || [];
  updateCharts(events);
  updateEvents(events);

  const warnings = [];
  if (Array.isArray(state.modelMeta.warnings)) warnings.push(...state.modelMeta.warnings);
  const selectedWarning = modelSelectionWarning();
  if (selectedWarning) warnings.push(selectedWarning);
  if (run.status === "failed") warnings.push(`RUN FAILED: ${run.error_message || "unknown error"}`);
  if (run.status === "cancelled") warnings.push("RUN CANCELLED by user.");

  if (run.status === "completed") {
    const report = await apiGet(`/api/runs/${state.currentRunId}/report`);
    state.latestSummary = report.summary || null;
    updateAssessment(report.summary);
    updateSummaryKpis(report.summary);
    updateDistributionCharts(report.summary);
    warnings.push(...summaryWarnings(report.summary));
    await refreshVersions();
    await refreshInterpretation();
  }
  setGlobalWarning([...new Set(warnings)]);
}

async function refreshVersions() {
  const data = await apiGet(`/api/reports/${machineValue()}/${modeValue()}`);
  const body = byId("versionsTable").querySelector("tbody");
  body.innerHTML = "";
  (data.versions || [])
    .slice()
    .reverse()
    .forEach((v) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
      <td>${v.report_version || ""}</td>
      <td>${v.run_id || ""}</td>
      <td>${v.created_at || ""}</td>
      <td>${v.rtp_point_pct ?? ""}</td>
      <td>${v.quality_label || ""}</td>
    `;
      body.appendChild(tr);
    });
}

async function refreshCache() {
  const data = await apiGet("/api/cache/status");
  byId("cacheMeta").textContent =
    `root=${data.cache_root}\nfiles=${data.file_count} total_bytes=${data.total_bytes}\nrunning_runs=${data.running_runs} reclaimable_est=${data.reclaimable_bytes_estimate}`;
  const cleanupBtn = byId("cacheCleanupBtn");
  cleanupBtn.disabled = Number(data.running_runs || 0) > 0;
  byId("cacheWarning").textContent =
    Number(data.running_runs || 0) > 0
      ? "Cleanup is blocked while runs are active. Stop all runs before cleanup."
      : "Cleanup is manual only. Click Cleanup Cache only when you confirm no active run needs cached chunks.";
}

async function cleanupCache() {
  const ok = window.confirm(
    "WARNING: this will delete local chunk cache files that are not currently protected by active runs. Continue?"
  );
  if (!ok) return;
  await apiPost("/api/cache/cleanup", { max_delete_bytes: 0 });
  await refreshCache();
}

async function generateInterpretation() {
  if (!state.currentRunId) return;
  const res = await apiPost("/api/interpretations", {
    run_id: state.currentRunId,
    model_id: modelValue(),
  });
  byId("interpretationText").textContent = res.content || "";
  const modelInfo = `provider=${res.provider || providerValue()} model=${res.model_id || ""} source=${res.source || "unknown"}`;
  setModelStatus(res.warning ? `${modelInfo} | ${res.warning}` : modelInfo);
  if (res.warning) {
    setGlobalWarning([...(state.modelMeta.warnings || []), res.warning]);
  }
}

async function refreshInterpretation() {
  if (!state.currentRunId) return;
  const res = await apiGet(`/api/interpretations/${state.currentRunId}`);
  byId("interpretationText").textContent = res.content || "";
  if (res.model_id) {
    const modelInfo = `model=${res.model_id || ""} source=${res.source || "unknown"}`;
    setModelStatus(res.warning ? `${modelInfo} | ${res.warning}` : modelInfo);
  }
}

function bindEvents() {
  byId("machineSelect").addEventListener("change", async () => {
    refreshModes();
    clearSummaryPanels();
    byId("interpretationText").textContent = "";
    await refreshVersions();
  });
  byId("modeSelect").addEventListener("change", async () => {
    clearSummaryPanels();
    byId("interpretationText").textContent = "";
    await refreshVersions();
  });
  byId("providerSelect").addEventListener("change", () => {
    fillModelsForProvider(providerValue());
    const selectedWarning = modelSelectionWarning();
    setGlobalWarning([...(state.modelMeta.warnings || []), ...(selectedWarning ? [selectedWarning] : [])]);
  });
  byId("modelSelect").addEventListener("change", () => {
    const selectedWarning = modelSelectionWarning();
    setGlobalWarning([...(state.modelMeta.warnings || []), ...(selectedWarning ? [selectedWarning] : [])]);
  });
  byId("saveModelCfgBtn").addEventListener("click", () => saveModelConfig().catch((e) => alert(e.message)));
  byId("startBtn").addEventListener("click", () => startRun().catch((e) => alert(e.message)));
  byId("stopBtn").addEventListener("click", () => stopRun().catch((e) => alert(e.message)));
  byId("refreshBtn").addEventListener("click", () => refreshCurrentRun().catch((e) => alert(e.message)));
  byId("cacheRefreshBtn").addEventListener("click", () => refreshCache().catch((e) => alert(e.message)));
  byId("cacheCleanupBtn").addEventListener("click", () => cleanupCache().catch((e) => alert(e.message)));
  byId("interpretBtn").addEventListener("click", () => generateInterpretation().catch((e) => alert(e.message)));
  byId("autotuneBtn").addEventListener("click", () => runAutoTune().catch((e) => alert(e.message)));
}

function startPolling() {
  if (state.timer) clearInterval(state.timer);
  state.timer = setInterval(() => {
    if (!state.currentRunId) return;
    refreshCurrentRun().catch(() => {});
  }, 2500);
}

async function boot() {
  buildCharts();
  bindEvents();
  try {
    await loadBootstrap();
    startPolling();
  } catch (err) {
    setHealth(`API ERROR: ${err.message}`, false);
  }
}

boot();
