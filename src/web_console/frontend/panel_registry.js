// panel_registry.js — ordered panel descriptor registry for _paintAnalysisFromSummary.
// Loaded BEFORE app.js (see index.html). render() fns reference app.js globals by name;
// they are only CALLED at runtime (after app.js has executed), so the references resolve.
//
// Shape of each descriptor:
//   { id: string, order: number, render: (ctx) => void|Promise, fireAndForget?: boolean }
//
// ctx built by _paintAnalysisFromSummary:
//   { a: s,   // primary summary (always present)
//     b: ...,  // compare-mode B summary or null (P1: panels still read state.compareMode.b internally)
//     machine: s.machine,
//     mode: s.mode,
//     compare: !!state.compareMode }
//
// P1 INVARIANT: every render fn below is a THIN WRAPPER around the existing render function
// or the extracted named function defined in app.js. No render logic is duplicated here.
// Byte-identical DOM output is guaranteed by construction (same fn, same args).
//
// Order values correspond to the current dispatch order in _paintAnalysisFromSummary
// (7036→7248). Gaps are intentional — future panels can be inserted without renumbering.

window.PANEL_REGISTRY = [
  // ── Inline blocks (extracted to named fns in app.js) ──────────────────────────

  { id: "kpi_tiles",            order: 100, render: (ctx) => renderKpiTiles(ctx.a) },
  { id: "tail_dep_grid",        order: 200, render: (ctx) => renderTailDepGrid(ctx.a) },
  { id: "big_win_grid",         order: 300, render: (ctx) => renderBigWinGrid(ctx.a) },

  // Library-ranking fetch: async but fire-and-forget (non-blocking for the panel sequence).
  // renderLibraryRanking returns a Promise; fireAndForget:true means the loop does NOT await it.
  { id: "library_ranking",      order: 400, render: (ctx) => renderLibraryRanking(ctx.a), fireAndForget: true },

  { id: "bucket_distribution",  order: 500, render: (ctx) => renderBucketDistribution(ctx.a) },

  // ── Named render fns (already exist in app.js) ────────────────────────────────

  { id: "rtp_clamp_warning",    order: 600,  render: (ctx) => renderRtpClampWarning(ctx.a) },
  { id: "report_self_check",    order: 700,  render: (ctx) => renderReportSelfCheck(ctx.a) },
  { id: "spin_type_breakdown",  order: 800,  render: (ctx) => renderSpinTypeBreakdown(ctx.a) },

  // Unified per-SpinType analysis: organized strictly BY SpinType. Each ST section
  // carries its dimensions — feature + payid (symbol combos / covered cols) +
  // outcome (win bands) + a special behavior block (e.g. ST=14 TopDollar pick
  // behavior). This CONSOLIDATES what were separate parallel panels
  // (spin_type_outcomes / payouts_by_spin_type / topdollar_choice) so they no
  // longer float as redundant sibling modules. Self-hides (P1 pattern).
  { id: "spin_type_outcomes",   order: 810,  render: (ctx) => renderSpinTypeOutcomes(ctx.a) },

  { id: "feature_breakdown",    order: 900,  render: (ctx) => renderFeatureBreakdownPanel(ctx.a) },

  // Classifier panel: fire-and-forget (its own API call; must not block the rest of the tab).
  { id: "payline_classification", order: 1000, render: (ctx) => renderPaylineClassification(ctx.a), fireAndForget: true },

  // renderPayIdOverview is async; the ORIGINAL dispatch called it WITHOUT await
  // (`renderPayIdOverview(s);` at app.js:7239, like payline_classification). Its paytable
  // fetches must NOT serialize into the paint chain → fireAndForget:true preserves the
  // original latency/ordering byte-for-byte.
  { id: "pay_id_overview",      order: 1100, render: (ctx) => renderPayIdOverview(ctx.a), fireAndForget: true },

  // (payouts_by_spin_type + topdollar_choice CONSOLIDATED into spin_type_outcomes
  //  at order 810 — the per-SpinType payid breakdown + TopDollar behavior now
  //  render inside each ST's own section, not as separate floating panels.)
  { id: "field_discovery",      order: 1300, render: (ctx) => renderFieldDiscovery(ctx.a) },
  { id: "machine_mechanics",    order: 1400, render: (ctx) => renderMachineMechanics(ctx.a) },
  { id: "bonus_chain_dynamics", order: 1500, render: (ctx) => renderBonusChainDynamicsPanel(ctx.a) },
  { id: "collect_cycle",        order: 1600, render: (ctx) => renderCollectCyclePanel(ctx.a) },
  { id: "payline_drilldown",    order: 1700, render: (ctx) => renderPaylineDrilldown(ctx.a) },
  { id: "symbol_drilldown",     order: 1800, render: (ctx) => renderSymbolDrilldown(ctx.a) },
  { id: "reel_marginal",        order: 1900, render: (ctx) => renderReelMarginalBySpinType(ctx.a) },
  { id: "bankruptcy_analysis",  order: 2000, render: (ctx) => renderBankruptcyAnalysis(ctx.a) },
];
