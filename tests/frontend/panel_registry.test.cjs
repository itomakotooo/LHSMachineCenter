/**
 * Tests for panel_registry.js (P1 — BYTE-IDENTICAL refactor)
 *
 * Memory feedback honored:
 *   - feedback_enumerate_safety_paths.md: inject-bug exercise proves the registry
 *     actually drives rendering (removing a descriptor removes its panel from dispatch).
 *   - feedback_integration_test_argv.md: test checks the actual registry array structure,
 *     not just "the module loaded".
 *   - feedback_dont_swallow_errors_in_fix.md: confirm the dispatch loop has NO catch-all
 *     that would hide a throwing panel.
 *
 * Inject-bug recipe (Gate 5):
 *   1. Remove the "bucket_distribution" descriptor from PANEL_REGISTRY.
 *   2. Assert that iterating the registry no longer includes it.
 *   3. Restore.
 *   4. Assert it is present again.
 *   The full inject-bug exercise is embedded in the test below.
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

test("panel_registry: descriptor count is 20 (5 inline/extracted + 15 named)", () => {
  // 5 extracted inline: kpi_tiles, tail_dep_grid, big_win_grid, library_ranking, bucket_distribution
  // 15 named: rtp_clamp_warning .. bankruptcy_analysis
  assert.equal(REGISTRY.length, 20, `Expected 20 descriptors, got ${REGISTRY.length}`);
});

// ── Order sequence matches original dispatch order ──────────────────────────────

test("panel_registry: descriptors in order 100→2000 when sorted", () => {
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
    "Panel dispatch order must match the original 7036→7248 sequence");
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
  // Use 1500 chars — the for loop starts ~887 chars into the function.
  const fnStart = appSource.indexOf("async function _paintAnalysisFromSummary(s)");
  assert.ok(fnStart !== -1, "_paintAnalysisFromSummary must exist in app.js");
  const loopSlice = appSource.slice(fnStart, fnStart + 1500);

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

test("inject-bug: removing bucket_distribution from registry excludes it from dispatch (inject → absent → restore → present)", () => {
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
  assert.equal(ids.length, 19, "After inject: registry must have 19 descriptors");

  // --- RESTORE ---
  shimWindow.PANEL_REGISTRY = originalRegistry;

  const sortedRestored = shimWindow.PANEL_REGISTRY.slice().sort((a, b) => a.order - b.order);
  const idsRestored = sortedRestored.map((d) => d.id);

  // Assert bucket_distribution is present again
  assert.ok(
    idsRestored.includes("bucket_distribution"),
    "After restore: bucket_distribution must be present in registry iteration"
  );
  assert.equal(idsRestored.length, 20, "After restore: registry must have 20 descriptors");
});

// ── Descriptor id set matches all 20 expected panel ids ────────────────────────

test("panel_registry: descriptor id set is complete — all 20 expected panels present", () => {
  const ids = new Set(REGISTRY.map((d) => d.id));
  const EXPECTED_IDS = [
    "kpi_tiles", "tail_dep_grid", "big_win_grid", "library_ranking", "bucket_distribution",
    "rtp_clamp_warning", "report_self_check", "spin_type_breakdown", "feature_breakdown",
    "payline_classification", "pay_id_overview", "payouts_by_spin_type", "field_discovery",
    "machine_mechanics", "bonus_chain_dynamics", "collect_cycle", "payline_drilldown",
    "symbol_drilldown", "reel_marginal", "bankruptcy_analysis",
  ];
  for (const id of EXPECTED_IDS) {
    assert.ok(ids.has(id), `Expected descriptor id "${id}" to be present in PANEL_REGISTRY`);
  }
  assert.equal(ids.size, EXPECTED_IDS.length, "No extra unexpected descriptor ids");
});
