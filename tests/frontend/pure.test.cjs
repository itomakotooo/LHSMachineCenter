"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PURE = require(path.resolve(__dirname, "../../src/web_console/frontend/pure.js"));

// ---------- i18n parity ----------

test("i18n: zh and en have identical key sets", () => {
  const zhKeys = Object.keys(PURE.I18N.zh).sort();
  const enKeys = Object.keys(PURE.I18N.en).sort();
  assert.deepStrictEqual(zhKeys, enKeys, "zh/en key sets must match");
});

test("i18n: critical risk-tier keys are non-empty in both locales", () => {
  const required = [
    "riskNone",
    "riskLow",
    "riskMedium",
    "riskHigh",
    "confirmCleanupLow",
    "confirmCleanupMedium",
    "confirmCleanupHigh",
    "confirmCleanupToken",
    "confirmCleanupTokenPrompt",
    "confirmCleanupTokenMismatch",
  ];
  for (const k of required) {
    assert.ok(PURE.I18N.zh[k], `zh.${k} missing`);
    assert.ok(PURE.I18N.en[k], `en.${k} missing`);
  }
});

// ---------- fmt ----------

test("fmt: substitutes vars", () => {
  assert.equal(
    PURE.fmt("en", "cacheRiskLine", { tier: "low", reclaimable: "1 MB" }),
    "Cleanup risk=low, reclaimable=1 MB"
  );
});

test("fmt: missing key returns key as-is", () => {
  assert.equal(PURE.fmt("en", "nonexistent_key_xyz"), "nonexistent_key_xyz");
});

test("fmt: unknown lang falls back to en", () => {
  assert.equal(PURE.fmt("ja", "btnStart"), PURE.fmt("en", "btnStart"));
});

test("fmt: zh value is used when lang=zh", () => {
  assert.equal(PURE.fmt("zh", "btnStart"), "开始运行");
  assert.equal(PURE.fmt("en", "btnStart"), "Start Run");
});

// ---------- fNum / fInt / fRate ----------

test("fNum: null/undefined/NaN -> N/A", () => {
  assert.equal(PURE.fNum(null), "N/A");
  assert.equal(PURE.fNum(undefined), "N/A");
  assert.equal(PURE.fNum(NaN), "N/A");
});

test("fNum: default 3 decimals", () => {
  assert.equal(PURE.fNum(1.23456), "1.235");
  assert.equal(PURE.fNum(0), "0.000");
});

test("fInt: null/undefined/NaN -> N/A", () => {
  assert.equal(PURE.fInt(null), "N/A");
  assert.equal(PURE.fInt(undefined), "N/A");
  assert.equal(PURE.fInt(NaN), "N/A");
});

test("fInt: thousands separator", () => {
  assert.equal(PURE.fInt(1234567), "1,234,567");
  assert.equal(PURE.fInt(0), "0");
});

test("fRate: null/undefined/NaN -> N/A", () => {
  assert.equal(PURE.fRate(null), "N/A");
  assert.equal(PURE.fRate(undefined), "N/A");
  assert.equal(PURE.fRate(NaN), "N/A");
});

test("fRate: converts to percentage", () => {
  assert.equal(PURE.fRate(0.12345), "12.35%");
  assert.equal(PURE.fRate(1), "100.00%");
  assert.equal(PURE.fRate(0), "0.00%");
});

// ---------- fBytes ----------

test("fBytes: zero / negative / sub-KB", () => {
  assert.equal(PURE.fBytes(0), "0 B");
  assert.equal(PURE.fBytes(-5), "0 B");
  assert.equal(PURE.fBytes(1023), "1023 B");
});

test("fBytes: unit scaling", () => {
  assert.equal(PURE.fBytes(1024), "1.00 KB");
  assert.equal(PURE.fBytes(1024 * 1024), "1.00 MB");
  assert.equal(PURE.fBytes(1024 * 1024 * 1024), "1.00 GB");
  assert.equal(PURE.fBytes(1024 * 1024 * 1024 * 1024), "1.00 TB");
});

// ---------- cacheRiskTier with default thresholds ----------

test("cacheRiskTier: default thresholds — none/low/medium/high boundaries", () => {
  assert.equal(PURE.cacheRiskTier(0), "none");
  assert.equal(PURE.cacheRiskTier(-1), "none");
  assert.equal(PURE.cacheRiskTier(1), "low");
  assert.equal(PURE.cacheRiskTier(100 * 1024 * 1024), "low");
  assert.equal(PURE.cacheRiskTier(512 * 1024 * 1024), "medium");
  assert.equal(PURE.cacheRiskTier(2 * 1024 * 1024 * 1024 - 1), "medium");
  assert.equal(PURE.cacheRiskTier(2 * 1024 * 1024 * 1024), "high");
  assert.equal(PURE.cacheRiskTier(10 * 1024 * 1024 * 1024), "high");
});

test("cacheRiskTier: injected thresholds (KB-scale for e2e)", () => {
  const t = { medium_bytes: 1024, high_bytes: 4096 };
  assert.equal(PURE.cacheRiskTier(0, t), "none");
  assert.equal(PURE.cacheRiskTier(500, t), "low");
  assert.equal(PURE.cacheRiskTier(1024, t), "medium");
  assert.equal(PURE.cacheRiskTier(2000, t), "medium");
  assert.equal(PURE.cacheRiskTier(4096, t), "high");
  assert.equal(PURE.cacheRiskTier(99999, t), "high");
});

// ---------- cacheRiskView ----------

test("cacheRiskView: none tier in zh", () => {
  const v = PURE.cacheRiskView("zh", { reclaimable_bytes_estimate: 0 });
  assert.equal(v.tier, "none");
  assert.equal(v.tierLabel, "无");
  assert.ok(v.hint.includes("不建议执行清理"));
});

test("cacheRiskView: high tier in en (with default thresholds)", () => {
  const v = PURE.cacheRiskView("en", {
    reclaimable_bytes_estimate: 3 * 1024 * 1024 * 1024,
  });
  assert.equal(v.tier, "high");
  assert.equal(v.tierLabel, "high");
  assert.ok(v.hint.includes("high risk"));
});

test("cacheRiskView: respects injected risk_thresholds", () => {
  const v = PURE.cacheRiskView("en", {
    reclaimable_bytes_estimate: 5000,
    risk_thresholds: { medium_bytes: 1024, high_bytes: 4096 },
  });
  assert.equal(v.tier, "high");
});

// ---------- statusText ----------

test("statusText: known status, both languages", () => {
  assert.equal(PURE.statusText("en", "running"), "running");
  assert.equal(PURE.statusText("zh", "running"), "运行中");
  assert.equal(PURE.statusText("en", "completed"), "completed");
  assert.equal(PURE.statusText("zh", "completed"), "已完成");
});

test("statusText: unknown status falls back", () => {
  assert.equal(PURE.statusText("en", "bogus"), "unknown");
  assert.equal(PURE.statusText("zh", "bogus"), "未知");
});

test("statusText: empty/null -> unknown", () => {
  assert.equal(PURE.statusText("en", ""), "unknown");
  assert.equal(PURE.statusText("en", null), "unknown");
});

// ---------- modelWarnings ----------

test("modelWarnings: model belongs to provider, key present -> []", () => {
  const out = PURE.modelWarnings({
    provider: "gpt",
    selected: "gpt-5.4",
    catalog: { gpt: ["gpt-5.4"] },
    hasApiKey: true,
    lang: "en",
  });
  assert.deepStrictEqual(out, []);
});

test("modelWarnings: model mismatch produces warnModelMismatch", () => {
  const out = PURE.modelWarnings({
    provider: "gpt",
    selected: "claude-3",
    catalog: { gpt: ["gpt-5.4"] },
    hasApiKey: true,
    lang: "en",
  });
  assert.ok(out.some((w) => w.includes("Selected model does not belong")));
});

test("modelWarnings: missing api key produces warnApiKeyEmpty (with provider name uppercased)", () => {
  const out = PURE.modelWarnings({
    provider: "gemini",
    selected: "gemini-2.5-flash",
    catalog: { gemini: ["gemini-2.5-flash"] },
    hasApiKey: false,
    lang: "en",
  });
  assert.equal(out.length, 1);
  assert.ok(out[0].startsWith("GEMINI"));
});

// ---------- collectSystemWarnings ----------

test("collectSystemWarnings: nothing wrong -> []", () => {
  const out = PURE.collectSystemWarnings({
    lang: "en",
    systemState: { operation_busy: false, startup_recovery: {} },
  });
  assert.deepStrictEqual(out, []);
});

test("collectSystemWarnings: stale running tasks recovered", () => {
  const out = PURE.collectSystemWarnings({
    lang: "en",
    systemState: { startup_recovery: { recovered_count: 3 } },
  });
  assert.equal(out.length, 1);
  assert.ok(out[0].includes("3 stale running tasks"));
});

test("collectSystemWarnings: stale pids + busy yields two warnings", () => {
  const out = PURE.collectSystemWarnings({
    lang: "en",
    systemState: {
      operation_busy: true,
      operation_name: "start_run",
      startup_recovery: { failed_to_terminate_pids: [1, 2] },
    },
  });
  assert.equal(out.length, 2);
  assert.ok(out.some((w) => w.includes("2 stale worker process")));
  assert.ok(out.some((w) => w.includes("start_run")));
});
