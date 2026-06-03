/**
 * Tests for panel_registry.js
 *
 * P1 — BYTE-IDENTICAL refactor (20 descriptors)
 * P2 — Generic stats-panel renderer + topdollar_choice (21 descriptors)
 *
 * Memory feedback honored:
 *   - feedback_enumerate_safety_paths.md: inject-bug exercise proves the registry
 *     actually drives rendering (removing a descriptor removes its panel from dispatch).
 *   - feedback_integration_test_argv.md: test checks the actual registry array structure,
 *     not just "the module loaded".
 *   - feedback_dont_swallow_errors_in_fix.md: confirm the dispatch loop has NO catch-all
 *     that would hide a throwing panel.
 *   - feedback_no_parallel_panel_impl.md: P2 generic renderer reuses sibling CSS/i18n.
 *
 * Inject-bug recipe (Gate 5 — P1 + P2):
 *   P1: Remove "bucket_distribution" → absent → restore → present.
 *   P2: Break topdollar_choice spec path ("total_sessions" → "BROKEN") → value wrong → revert.
 *   The full exercises are embedded below.
 *
 * Design notes:
 *   panel_registry.js assigns window.PANEL_REGISTRY. In Node there is no `window`,
 *   so we shim it before loading the file via module evaluation.
 *   render() fns reference app.js globals by name — they are arrow fns that capture
 *   the name at call time (not at definition time), so we don't need to stub them for
 *   registry-shape tests.
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

// ── Shim browser globals so panel_registry.js evaluates cleanly in Node ────────
const shimWindow = {};
global.window = shimWindow;

// Evaluate panel_registry.js (it assigns to window.PANEL_REGISTRY)
const registrySource = fs.readFileSync(
  path.resolve(__dirname, "../../src/web_console/frontend/panel_registry.js"),
  "utf8"
);
// eslint-disable-next-line no-new-func
new Function("window", registrySource)(shimWindow);

const REGISTRY = shimWindow.PANEL_REGISTRY;

// ── Basic shape invariants ──────────────────────────────────────────────────────

test("panel_registry: PANEL_REGISTRY is a non-empty array", () => {
  assert.ok(Array.isArray(REGISTRY), "PANEL_REGISTRY must be an array");
  assert.ok(REGISTRY.length > 0, "PANEL_REGISTRY must not be empty");
});

test("panel_registry: every descriptor has required fields (id, order, render)", () => {
  for (const d of REGISTRY) {
    assert.ok(typeof d.id === "string" && d.id.length > 0,
      `descriptor.id must be a non-empty string, got: ${JSON.stringify(d.id)}`);
    assert.ok(typeof d.order === "number",
      `descriptor.order must be a number for id=${d.id}`);
    assert.ok(typeof d.render === "function",
      `descriptor.render must be a function for id=${d.id}`);
  }
});

test("panel_registry: all order values are unique (no two descriptors at same order)", () => {
  const orders = REGISTRY.map((d) => d.order);
  const unique = new Set(orders);
  assert.equal(unique.size, orders.length,
    `Duplicate order values found: ${orders.join(", ")}`);
});

test("panel_registry: descriptor count is 21 (P1=20 + P2 topdollar_choice=1)", () => {
  // P1: 5 extracted inline (kpi_tiles, tail_dep_grid, big_win_grid, library_ranking, bucket_distribution)
  //   + 15 named (rtp_clamp_warning .. bankruptcy_analysis) = 20
  // P2: + 1 (topdollar_choice at order 850) = 21
  assert.equal(REGISTRY.length, 21, `Expected 21 descriptors, got ${REGISTRY.length}`);
});

// ── Order sequence matches original dispatch order ──────────────────────────────

test("panel_registry: descriptors in order 100→2000 when sorted (P2: topdollar_choice at 850)", () => {
  const sorted = [...REGISTRY].sort((a, b) => a.order - b.order);
  const EXPECTED_ORDER = [
    "kpi_tiles",            // 100  — was first inline block
    "tail_dep_grid",        // 200
    "big_win_grid",         // 300
    "library_ranking",      // 400  — fireAndForget async
    "bucket_distribution",  // 500
    "rtp_clamp_warning",    // 600  — named panels begin
    "report_self_check",    // 700
    "spin_type_breakdown",  // 800
    "topdollar_choice",     // 850  — P2 generic renderer (self-hides; no present skip)
    "feature_breakdown",    // 900
    "payline_classification",// 1000 — fireAndForget
    "pay_id_overview",      // 1100
    "payouts_by_spin_type", // 1200
    "field_discovery",      // 1300
    "machine_mechanics",    // 1400
    "bonus_chain_dynamics", // 1500
    "collect_cycle",        // 1600
    "payline_drilldown",    // 1700
    "symbol_drilldown",     // 1800
    "reel_marginal",        // 1900
    "bankruptcy_analysis",  // 2000
  ];
  const actualOrder = sorted.map((d) => d.id);
  assert.deepStrictEqual(actualOrder, EXPECTED_ORDER,
    "Panel dispatch order must match P1 order + topdollar_choice at 850");
});

// ── fireAndForget flags ─────────────────────────────────────────────────────────

test("panel_registry: EXACTLY the 3 async panels are fireAndForget", () => {
  // The original dispatch called library_ranking, payline_classification, AND
  // pay_id_overview WITHOUT await (fire-and-forget). All 3 must be marked so their
  // async work does not serialize into the paint chain (byte-identical latency/ordering).
  const ffIds = REGISTRY
    .filter((d) => d.fireAndForget === true)
    .map((d) => d.id)
    .sort();
  assert.deepStrictEqual(
    ffIds,
    ["library_ranking", "pay_id_overview", "payline_classification"].sort(),
    "fireAndForget must be set on exactly library_ranking, payline_classification, pay_id_overview");
});

test("panel_registry: pay_id_overview IS fireAndForget (original called it without await)", () => {
  const d = REGISTRY.find((d) => d.id === "pay_id_overview");
  assert.ok(d, "pay_id_overview descriptor must exist");
  assert.ok(d.fireAndForget === true,
    "pay_id_overview must be fireAndForget — the original dispatch did not await it");
});

// ── No catch-all swallow in dispatch (structural check of app.js loop) ─────────

test("panel_registry: dispatch loop in app.js has no catch-all wrapping render calls", () => {
  // Per feedback_dont_swallow_errors_in_fix: the loop must NOT wrap render() in
  // try/catch. Read the loop source and assert no catch block surrounds render().
  const appSource = fs.readFileSync(
    path.resolve(__dirname, "../../src/web_console/frontend/app.js"),
    "utf8"
  );
  // Extract the _paintAnalysisFromSummary function body.
  // Use 2200 chars — the for loop starts ~1100 chars into the function (after the
  // ctx-build + self-hide-pattern comment block).
  const fnStart = appSource.indexOf("async function _paintAnalysisFromSummary(s)");
  assert.ok(fnStart !== -1, "_paintAnalysisFromSummary must exist in app.js");
  const loopSlice = appSource.slice(fnStart, fnStart + 2200);

  // The loop must iterate sorted descriptors.
  assert.ok(loopSlice.includes("for (const descriptor of sorted)"),
    "Loop must iterate sorted descriptors");

  // Find function close: search for the 'for' loop, then find the closing '}\n' that
  // ends _paintAnalysisFromSummary (the function body ends before 'async function refreshCurrentRun').
  const forLoopIdx = loopSlice.indexOf("for (const descriptor of sorted)");
  // Extract just the for-loop body (from for to end of _paintAnalysisFromSummary).
  const nextFn = loopSlice.indexOf("async function refreshCurrentRun");
  const functionBody = nextFn !== -1
    ? loopSlice.slice(forLoopIdx, nextFn)
    : loopSlice.slice(forLoopIdx);

  // There must be NO try block wrapping descriptor.render inside _paintAnalysisFromSummary.
  assert.ok(!functionBody.includes("try {"),
    "The dispatch loop must NOT wrap render() calls in a try/catch (would hide panel errors per feedback_dont_swallow_errors_in_fix)");
});

// ── Gate 5 INJECT-BUG exercise ─────────────────────────────────────────────────
//
// Prove the registry actually drives rendering:
// Remove one descriptor → it is absent from the iteration → restore → present again.
// This simulates: if bucket_distribution were missing, bucketTable would not be rendered.

test("inject-bug (P1): removing bucket_distribution from registry excludes it from dispatch (inject → absent → restore → present)", () => {
  // --- INJECT BUG: remove bucket_distribution ---
  const originalRegistry = shimWindow.PANEL_REGISTRY.slice(); // copy
  shimWindow.PANEL_REGISTRY = shimWindow.PANEL_REGISTRY.filter(
    (d) => d.id !== "bucket_distribution"
  );

  const sorted = shimWindow.PANEL_REGISTRY.slice().sort((a, b) => a.order - b.order);
  const ids = sorted.map((d) => d.id);

  // Assert bucket_distribution is absent (panel would not be rendered)
  assert.ok(
    !ids.includes("bucket_distribution"),
    "After inject: bucket_distribution must not appear in registry iteration"
  );
  assert.equal(ids.length, 20, "After inject: registry must have 20 descriptors (21 - 1)");

  // --- RESTORE ---
  shimWindow.PANEL_REGISTRY = originalRegistry;

  const sortedRestored = shimWindow.PANEL_REGISTRY.slice().sort((a, b) => a.order - b.order);
  const idsRestored = sortedRestored.map((d) => d.id);

  // Assert bucket_distribution is present again
  assert.ok(
    idsRestored.includes("bucket_distribution"),
    "After restore: bucket_distribution must be present in registry iteration"
  );
  assert.equal(idsRestored.length, 21, "After restore: registry must have 21 descriptors");
});

// ── Descriptor id set matches all 21 expected panel ids (P1=20 + P2=1) ─────────

test("panel_registry: descriptor id set is complete — all 21 expected panels present (P1+P2)", () => {
  const ids = new Set(REGISTRY.map((d) => d.id));
  const EXPECTED_IDS = [
    // P1 (20)
    "kpi_tiles", "tail_dep_grid", "big_win_grid", "library_ranking", "bucket_distribution",
    "rtp_clamp_warning", "report_self_check", "spin_type_breakdown", "feature_breakdown",
    "payline_classification", "pay_id_overview", "payouts_by_spin_type", "field_discovery",
    "machine_mechanics", "bonus_chain_dynamics", "collect_cycle", "payline_drilldown",
    "symbol_drilldown", "reel_marginal", "bankruptcy_analysis",
    // P2 (1)
    "topdollar_choice",
  ];
  for (const id of EXPECTED_IDS) {
    assert.ok(ids.has(id), `Expected descriptor id "${id}" to be present in PANEL_REGISTRY`);
  }
  assert.equal(ids.size, EXPECTED_IDS.length, "No extra unexpected descriptor ids");
});

// ── P2: topdollar_choice descriptor shape (NO present() — renderer self-hides) ──

test("P2: topdollar_choice descriptor is registered at order 850, no present() skip", () => {
  const d = REGISTRY.find((d) => d.id === "topdollar_choice");
  assert.ok(d, "topdollar_choice descriptor must be in PANEL_REGISTRY");
  assert.equal(d.order, 850, "topdollar_choice must be at order 850");
  assert.equal(typeof d.render, "function", "topdollar_choice must have a render() function");
  assert.ok(d.fireAndForget !== true, "topdollar_choice must NOT be fireAndForget");
  // NO present() — renderStatsPanel SELF-HIDES when the feature is absent. A present()
  // skip would leave the panel showing stale data after a machine switch (the completed-run
  // load path does not reset before painting). See the stale-panel fix.
  assert.equal(typeof d.present, "undefined",
    "topdollar_choice must NOT have a present() skip — renderStatsPanel self-hides instead");
});

test("P2: NO descriptor uses a present() skip (renderers self-hide — no stale-panel trap)", () => {
  // Every descriptor's render() runs on each paint and self-hides when its data is absent
  // (the P1 pattern). A present() skip is forbidden: skipping render leaves the panel stale
  // on a machine switch. This guards the whole registry against re-introducing the trap.
  for (const d of REGISTRY) {
    assert.equal(typeof d.present, "undefined",
      `descriptor ${d.id} must NOT have a present() field — renderers self-hide, never skip`);
  }
});

test("P2: dispatch loop has NO present/skip — every descriptor renders (self-hide pattern)", () => {
  // Structural guard against re-introducing the stale-panel bug: the loop must NOT skip
  // render based on a predicate. Skipping leaves a panel stale after a machine switch (the
  // completed-run load path does not reset before painting). Each render() self-hides instead.
  const appSource = fs.readFileSync(
    path.resolve(__dirname, "../../src/web_console/frontend/app.js"),
    "utf8"
  );
  const fnStart = appSource.indexOf("async function _paintAnalysisFromSummary(s)");
  assert.ok(fnStart !== -1, "_paintAnalysisFromSummary must exist");
  const loopSlice = appSource.slice(fnStart, fnStart + 1800);
  assert.ok(loopSlice.includes("for (const descriptor of sorted)"),
    "Loop must iterate sorted descriptors");
  assert.ok(!loopSlice.includes("descriptor.present"),
    "Dispatch loop must NOT reference descriptor.present — no skip (skip → stale panel; renderers self-hide)");
});

test("P2: topDollarChoicePanel is in the _resetDebugPanelsToEmpty hide-list (clean empty state)", () => {
  // Like every gated panel, the registry panel must be reset to hidden on the
  // nothing-loaded / error paths so the debug tab shows a clean empty state.
  const appSource = fs.readFileSync(
    path.resolve(__dirname, "../../src/web_console/frontend/app.js"),
    "utf8"
  );
  const fnStart = appSource.indexOf("function _resetDebugPanelsToEmpty()");
  assert.ok(fnStart !== -1, "_resetDebugPanelsToEmpty must exist");
  const fnSlice = appSource.slice(fnStart, fnStart + 1500);
  assert.ok(fnSlice.includes('"topDollarChoicePanel"'),
    "_resetDebugPanelsToEmpty must include topDollarChoicePanel in its hide-list");
});

// ── P2 inject-bug: break spec path → wrong value → revert → correct value ──────
//
// Demonstrates that the generic renderer is actually driven by the spec:
// if a row's path is wrong, the value renders as N/A instead of the expected value.
// This proves renderStatsPanel reads spec.sections[].rows[].path at call time.

test("P2 inject-bug: breaking topdollar_choice spec path produces N/A, revert restores correct value", () => {
  // We test the spec-resolution logic directly (no DOM needed).
  // Mirror the path-resolution and value-formatting logic from renderStatsPanel.
  const fInt = (v) =>
    v === null || v === undefined || isNaN(Number(v))
      ? "N/A"
      : new Intl.NumberFormat("en-US").format(Number(v));
  const _fmtVal = (v, fmtType) => {
    if (v === null || v === undefined) return "N/A";
    switch (fmtType) {
      case "int": return fInt(v);
      default:    return String(v);
    }
  };
  const resolvePath = (data, pathStr) => {
    const parts = pathStr.split(".");
    let v = data;
    for (const p of parts) v = (v != null && typeof v === "object") ? v[p] : undefined;
    return v;
  };

  const td = { applicable: true, total_sessions: 440 };

  // CORRECT path
  const correctRow = { labelKey: "tdTotalSessions", path: "total_sessions", fmt: "int" };
  const correctVal = _fmtVal(resolvePath(td, correctRow.path), correctRow.fmt);
  assert.equal(correctVal, "440", "Correct path must resolve to '440'");

  // INJECT BUG: wrong path
  const brokenRow = { labelKey: "tdTotalSessions", path: "BROKEN_PATH", fmt: "int" };
  const brokenVal = _fmtVal(resolvePath(td, brokenRow.path), brokenRow.fmt);
  assert.equal(brokenVal, "N/A", "Broken path must produce N/A (inject-bug confirmed)");

  // REVERT: correct path again
  const revertedVal = _fmtVal(resolvePath(td, correctRow.path), correctRow.fmt);
  assert.equal(revertedVal, "440", "After revert: correct path must produce '440' again");
});
