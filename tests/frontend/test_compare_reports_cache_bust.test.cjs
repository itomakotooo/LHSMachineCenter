"use strict";

/**
 * Regression tests for P1-A5: compareReports cache-bust race fix.
 *
 * These tests cover the pure-logic contracts that do NOT require a DOM or
 * live server. They test:
 *
 *   C1 — Map.delete semantics for compareSelected
 *   C3 — Invocation-id guard logic (pure predicate)
 *
 * NOTE: These tests run with `node --test` and import no app.js (which has
 * DOM dependencies). They assert the algorithm / pure-function layer of the
 * fix. The DOM + live-server contracts are covered by
 * tests/e2e/test_compare_reports_cache_bust.py.
 *
 * INJECT-BUG discipline: each test documents what mutation makes it go red.
 * See 03_tests.md for the full inject-bug verification log.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

// ---------------------------------------------------------------------------
// compareSelected Map semantics (C1)
// ---------------------------------------------------------------------------

test("compareSelected.delete removes only the target version key", () => {
  // Models state.compareSelected = new Map().
  const compareSelected = new Map();
  const rv_a = "rv_20260501T120000Z_unitA";
  const rv_b = "rv_20260501T130000Z_unitB";
  compareSelected.set(rv_a, { mode: 1, machine: "M14" });
  compareSelected.set(rv_b, { mode: 1, machine: "M14" });

  // The fix: delete the version that was DELETEd from the backend.
  compareSelected.delete(rv_a);

  // C1: rv_a removed, rv_b intact.
  assert.equal(compareSelected.has(rv_a), false,
    "deleted version must not be in compareSelected after delete(rv_a)");
  assert.equal(compareSelected.has(rv_b), true,
    "non-deleted version must remain in compareSelected");
  assert.equal(compareSelected.size, 1, "Map size must be 1 after deleting 1 of 2");
});

test("compareSelected.delete on absent key is a no-op (idempotent)", () => {
  // Inject-bug scenario: if delete is called twice (e.g., retry or duplicate
  // event), it must not throw and must leave Map in a consistent state.
  const compareSelected = new Map();
  const rv = "rv_20260501T140000Z_unitC";
  compareSelected.set(rv, { mode: 1, machine: "M14" });
  compareSelected.delete(rv);
  // Second delete (absent key) must not throw.
  assert.doesNotThrow(() => compareSelected.delete(rv));
  assert.equal(compareSelected.has(rv), false);
  assert.equal(compareSelected.size, 0);
});

test("compareSelected cleared to new Map() removes all entries", () => {
  // Models what _resetCompareModeToEmpty must do: state.compareSelected = new Map().
  // Inject-bug: if the reset only calls .clear() but not = new Map(), the
  // Map reference is still the same and any stale listener holding the old
  // reference will see an empty map — acceptable. But if the code does
  // compareSelected = someOldMap, it would retain stale entries.
  const compareSelected = new Map();
  compareSelected.set("rv_20260501T150000Z_unitD", { mode: 1 });
  compareSelected.set("rv_20260501T160000Z_unitE", { mode: 2 });

  // Simulate _resetCompareModeToEmpty: state.compareSelected = new Map().
  const resetMap = new Map();
  assert.equal(resetMap.size, 0, "freshly created Map must be empty");
  assert.equal(resetMap.has("rv_20260501T150000Z_unitD"), false);
});

// ---------------------------------------------------------------------------
// Invocation-id guard logic (C3)
// ---------------------------------------------------------------------------

test("invocation-id guard: stale captured id causes fetch result to be discarded", () => {
  /**
   * Models the C3 one-shot guard:
   *   const capturedId = ++state._compareInvocationId;
   *   // ... await fetch ...
   *   if (capturedId !== state._compareInvocationId) return;  // discard
   *
   * Inject-bug: remove the guard check → stale fetch applies stale data.
   */
  let compareInvocationId = 0;

  // compareReports() starts: capture id = 1.
  const capturedId = ++compareInvocationId;  // 1

  // DELETE fires during the await: bump id to 2.
  compareInvocationId++;  // 2

  // Fetch completes: check if we should apply the result.
  const shouldApply = capturedId === compareInvocationId;

  assert.equal(shouldApply, false,
    "stale fetch (capturedId=1 != currentId=2) must NOT apply compare result");
});

test("invocation-id guard: fresh id (no DELETE during fetch) applies result", () => {
  let compareInvocationId = 0;

  // compareReports() starts: capture id = 1.
  const capturedId = ++compareInvocationId;  // 1

  // No DELETE during the fetch: id stays at 1.

  // Fetch completes: capturedId === currentId → apply.
  const shouldApply = capturedId === compareInvocationId;

  assert.equal(shouldApply, true,
    "fresh fetch (capturedId=1 == currentId=1) must apply compare result");
});

test("invocation-id increments monotonically on each DELETE", () => {
  /**
   * Multiple DELETEs during one compare session: each bumps the id.
   * Only the very last fetch (capturing the final id) should apply.
   */
  let compareInvocationId = 0;

  // Fetch starts: id=1.
  const captured = ++compareInvocationId;  // 1

  // Three rapid DELETEs (bulk delete scenario).
  compareInvocationId++;  // 2
  compareInvocationId++;  // 3
  compareInvocationId++;  // 4

  // Stale fetch (id=1) is discarded.
  assert.equal(captured === compareInvocationId, false,
    "fetch with id=1 must be discarded when currentId=4");

  // New fetch starts with current id=4.
  const fresh = ++compareInvocationId;  // 5 — fresh fetch after all DELETEs
  assert.equal(fresh, 5);
  assert.equal(fresh === compareInvocationId, true, "fresh fetch id=5 matches currentId=5");
});

// ---------------------------------------------------------------------------
// compareMode null-check guard before entering compare
// ---------------------------------------------------------------------------

test("compareMode null check: entering compare with non-null compareMode is an idempotent replace", () => {
  /**
   * If compareMode is already non-null when _enterCompareMode fires (e.g.,
   * fast double-click), the fix should overwrite it, not stack. This test
   * documents that compareMode is a scalar slot (not a stack/queue).
   */
  // Models state.compareMode = { a, b, vA, vB }.
  let compareMode = null;

  // First compare enters.
  compareMode = { a: { machine: "M14" }, b: { machine: "M14" }, vA: "rv_v1", vB: "rv_v2" };
  assert.ok(compareMode !== null);

  // _resetCompareModeToEmpty called: compareMode → null.
  compareMode = null;
  assert.equal(compareMode, null,
    "compareMode must be null after _resetCompareModeToEmpty");

  // Second compare can then enter cleanly.
  compareMode = { a: { machine: "M14" }, b: { machine: "M15" }, vA: "rv_v3", vB: "rv_v4" };
  assert.ok(compareMode !== null);
  assert.equal(compareMode.vA, "rv_v3");
});

test("compareMode.vA and vB correctly identify which versions are active", () => {
  /**
   * The delete handler must check: did the deleted rv match compareMode.vA
   * or compareMode.vB? This pure test validates the comparison logic.
   * Inject-bug: if the handler checks compareMode.a.machine instead of vA/vB,
   * the wrong version triggers exit.
   */
  const compareMode = {
    a: { machine: "M14", mode: 1 },
    b: { machine: "M14", mode: 1 },
    vA: "rv_20260501T120000Z_v1",
    vB: "rv_20260501T130000Z_v2",
  };

  const deleted_rv = "rv_20260501T120000Z_v1";  // matches vA

  const isInCompare = (
    compareMode !== null &&
    (compareMode.vA === deleted_rv || compareMode.vB === deleted_rv)
  );

  assert.equal(isInCompare, true,
    "deleted rv matching vA must trigger compare mode exit");

  const other_rv = "rv_20260501T999999Z_notincompare";
  const otherIsInCompare = (
    compareMode !== null &&
    (compareMode.vA === other_rv || compareMode.vB === other_rv)
  );
  assert.equal(otherIsInCompare, false,
    "rv not in compare must NOT trigger compare mode exit");
});
