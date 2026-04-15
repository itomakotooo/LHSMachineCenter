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

test("i18n: CI tier option keys are non-empty in both locales", () => {
  const required = [
    "ciOption05",
    "ciOption1",
    "ciOption2",
    "ciOption5",
    "ciOptionFuzzy",
    "helpCiTargetFuzzy",
  ];
  for (const k of required) {
    assert.ok(PURE.I18N.zh[k], `zh.${k} missing`);
    assert.ok(PURE.I18N.en[k], `en.${k} missing`);
  }
});

test("i18n: run-config validation keys are non-empty in both locales", () => {
  const required = [
    "placeholderAutotuneFill",
    "validateAutotuneFirst",
    "validateMode25RequireFuzzy",
  ];
  for (const k of required) {
    assert.ok(PURE.I18N.zh[k], `zh.${k} missing`);
    assert.ok(PURE.I18N.en[k], `en.${k} missing`);
  }
});

test("i18n: run failure / cancellation keys are non-empty in both locales", () => {
  const required = [
    "runStatusLabel",
    "runFailedLabel",
    "runCancelledLabel",
    "runCancelledText",
    "runFailureNoneCaptured",
  ];
  for (const k of required) {
    assert.ok(PURE.I18N.zh[k], `zh.${k} missing`);
    assert.ok(PURE.I18N.en[k], `en.${k} missing`);
  }
});

test("i18n: advanced + bankroll keys are non-empty in both locales", () => {
  const required = [
    "labelAdvancedParams",
    "bankMultStandard",
    "bankMultShort",
    "bankMultLong",
    "helpBankMultiplierWarn",
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

// ---------- ciTierOptions ----------

test("ciTierOptions: returns 5 options with stable values", () => {
  const opts = PURE.ciTierOptions("zh");
  assert.equal(opts.length, 5);
  assert.deepStrictEqual(
    opts.map((o) => o.value),
    ["0.5", "1", "2", "5", "0"]
  );
});

test("ciTierOptions: labels localized for zh", () => {
  const opts = PURE.ciTierOptions("zh");
  const fuzzy = opts.find((o) => o.value === "0");
  assert.ok(fuzzy.label.includes("模糊"));
});

test("ciTierOptions: labels localized for en", () => {
  const opts = PURE.ciTierOptions("en");
  const fuzzy = opts.find((o) => o.value === "0");
  assert.ok(fuzzy.label.toLowerCase().includes("fuzzy"));
});

// ---------- formatRunFailureNote ----------

test("formatRunFailureNote: empty error falls back to localized note (zh)", () => {
  assert.equal(
    PURE.formatRunFailureNote("zh", ""),
    PURE.I18N.zh.runFailureNoneCaptured
  );
  assert.equal(
    PURE.formatRunFailureNote("zh", null),
    PURE.I18N.zh.runFailureNoneCaptured
  );
  assert.equal(
    PURE.formatRunFailureNote("zh", undefined),
    PURE.I18N.zh.runFailureNoneCaptured
  );
});

test("formatRunFailureNote: whitespace-only error also falls back", () => {
  assert.equal(
    PURE.formatRunFailureNote("en", "   \n\t "),
    PURE.I18N.en.runFailureNoneCaptured
  );
});

test("formatRunFailureNote: populated error passes through trimmed", () => {
  assert.equal(
    PURE.formatRunFailureNote(
      "en",
      "  analyzer exit_code=1 | summary missing: a.json  "
    ),
    "analyzer exit_code=1 | summary missing: a.json"
  );
});

// ---------- bankrollMultiplierPresets ----------

test("bankrollMultiplierPresets: returns 3 presets with stable values", () => {
  const presets = PURE.bankrollMultiplierPresets("zh");
  assert.equal(presets.length, 3);
  assert.deepStrictEqual(
    presets.map((p) => p.value),
    ["100,200,500", "50,100,200", "200,500,1000"]
  );
});

test("bankrollMultiplierPresets: labels localized (zh 标准/短/长)", () => {
  const presets = PURE.bankrollMultiplierPresets("zh");
  assert.ok(presets[0].label.includes("标准"));
  assert.ok(presets[1].label.includes("短会话"));
  assert.ok(presets[2].label.includes("长会话"));
});

test("bankrollMultiplierPresets: labels localized (en Standard/Short/Long)", () => {
  const presets = PURE.bankrollMultiplierPresets("en");
  assert.ok(presets[0].label.toLowerCase().includes("standard"));
  assert.ok(presets[1].label.toLowerCase().includes("short"));
  assert.ok(presets[2].label.toLowerCase().includes("long"));
});

// ---------- validateRunConfig ----------

test("validateRunConfig: mode 1 happy path -> canStart=true", () => {
  const r = PURE.validateRunConfig({
    mode: 1,
    halfwidthPp: "0.5",
    robotCount: "20",
    concurrency: "2",
    lang: "en",
  });
  assert.equal(r.canStart, true);
  assert.deepStrictEqual(r.blocking, []);
});

test("validateRunConfig: mode 7 + fuzzy + filled concurrency -> canStart=true", () => {
  const r = PURE.validateRunConfig({
    mode: 7,
    halfwidthPp: "0",
    robotCount: 16,
    concurrency: 1,
    lang: "en",
  });
  assert.equal(r.canStart, true);
});

test("validateRunConfig: mode 2 with non-fuzzy halfwidth -> blocking", () => {
  const r = PURE.validateRunConfig({
    mode: 2,
    halfwidthPp: "0.5",
    robotCount: "20",
    concurrency: "2",
    lang: "en",
  });
  assert.equal(r.canStart, false);
  assert.ok(r.blocking.some((m) => m.toLowerCase().includes("fuzzy")));
});

test("validateRunConfig: mode 5 with fuzzy is fine", () => {
  const r = PURE.validateRunConfig({
    mode: 5,
    halfwidthPp: "0",
    robotCount: "24",
    concurrency: "4",
    lang: "en",
  });
  assert.equal(r.canStart, true);
});

test("validateRunConfig: empty robotCount produces autotune-first blocker", () => {
  const r = PURE.validateRunConfig({
    mode: 1,
    halfwidthPp: "0.5",
    robotCount: "",
    concurrency: "2",
    lang: "en",
  });
  assert.equal(r.canStart, false);
  assert.ok(r.blocking.some((m) => m.toLowerCase().includes("auto tune")));
});

test("validateRunConfig: empty concurrency also triggers autotune-first", () => {
  const r = PURE.validateRunConfig({
    mode: 7,
    halfwidthPp: "0.5",
    robotCount: "20",
    concurrency: "",
    lang: "zh",
  });
  assert.equal(r.canStart, false);
  // zh locale should produce a zh-localized message, not a key fallback.
  assert.ok(r.blocking.some((m) => m.includes("压测")));
});

test("validateRunConfig: stacked failures (mode 2 non-fuzzy + empty conc)", () => {
  const r = PURE.validateRunConfig({
    mode: 2,
    halfwidthPp: "1",
    robotCount: "",
    concurrency: "",
    lang: "en",
  });
  assert.equal(r.canStart, false);
  assert.equal(r.blocking.length, 2);
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
