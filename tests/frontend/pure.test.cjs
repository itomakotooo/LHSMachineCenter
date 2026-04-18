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
    "validateConcurrencyRequired",
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
  // Sidebar refactor (Commit 2 of dashboard layout) shortened the run-control
  // button labels from "开始运行" / "Start Run" to icon + short phrase so the
  // 4 buttons fit a 2x2 grid in the 260px sidebar column.
  assert.equal(PURE.fmt("zh", "btnStart"), "▶ 开始");
  assert.equal(PURE.fmt("en", "btnStart"), "▶ Start");
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

// ---------- summarizeRunEvent + computeRunProgressPct ----------

test("summarizeRunEvent: null event -> localized 'no events' text", () => {
  assert.equal(PURE.summarizeRunEvent("en", null, {}), PURE.I18N.en.runEventNone);
  assert.equal(PURE.summarizeRunEvent("zh", null, {}), PURE.I18N.zh.runEventNone);
});

test("summarizeRunEvent: started event includes machine/mode/target", () => {
  const out = PURE.summarizeRunEvent(
    "en",
    { event: "started", machine: "M14", mode: 1 },
    { target: 0.5, maxChunks: 120 }
  );
  assert.ok(out.includes("M14"));
  assert.ok(out.includes("0.5pp"));
});

test("summarizeRunEvent: started in fuzzy mode says ~1M spins", () => {
  const out = PURE.summarizeRunEvent(
    "zh",
    { event: "started", machine: "M14", mode: 2 },
    { target: 0, isFuzzy: true }
  );
  assert.ok(out.includes("模糊"));
});

test("summarizeRunEvent: chunk_progress non-fuzzy uses idx/maxChunks + CI", () => {
  const out = PURE.summarizeRunEvent(
    "en",
    {
      event: "chunk_progress",
      chunk_index: 15,
      total_spins: 300000,
      current_rtp_pct: 85.234,
      current_halfwidth_pp: 1.2,
    },
    { maxChunks: 120, target: 0.5 }
  );
  assert.ok(out.includes("15/120"));
  assert.ok(out.includes("300,000"));
  assert.ok(out.includes("85.23"));
  assert.ok(out.includes("1.200"));
});

test("summarizeRunEvent: chunk_progress fuzzy reports % vs 1M target", () => {
  const out = PURE.summarizeRunEvent(
    "en",
    {
      event: "chunk_progress",
      chunk_index: 5,
      total_spins: 250000,
      current_rtp_pct: 200.5,
      current_halfwidth_pp: 999.0,
    },
    { isFuzzy: true }
  );
  // 250_000 / 1_000_000 = 25.0%
  assert.ok(out.includes("25.0%"), out);
  assert.ok(out.includes("200.50"));
  // No CI in fuzzy summary
  assert.ok(!out.includes("CI="));
});

test("summarizeRunEvent: completed includes spins + duration", () => {
  const out = PURE.summarizeRunEvent(
    "en",
    {
      event: "completed",
      total_spins: 2400000,
      rtp_point_pct: 95.12,
      ci95_interval_pct: [94.638, 95.602],
      duration_seconds: 127,
    },
    {}
  );
  assert.ok(out.includes("2,400,000"));
  assert.ok(out.includes("95.12"));
  assert.ok(out.includes("127s"));
});

test("summarizeRunEvent: failed shows reason", () => {
  const out = PURE.summarizeRunEvent(
    "en",
    { event: "failed", reason: "request_failed_HTTPError" },
    {}
  );
  assert.ok(out.includes("request_failed_HTTPError"));
});

test("computeRunProgressPct: non-fuzzy uses chunks/max", () => {
  assert.equal(
    PURE.computeRunProgressPct({ chunk_index: 30 }, { maxChunks: 120 }),
    25
  );
  assert.equal(PURE.computeRunProgressPct({ chunk_index: 0 }, { maxChunks: 120 }), 0);
  // Saturates at 100
  assert.equal(
    PURE.computeRunProgressPct({ chunk_index: 999 }, { maxChunks: 120 }),
    100
  );
});

test("computeRunProgressPct: fuzzy uses spins/fuzzyTarget", () => {
  assert.equal(
    PURE.computeRunProgressPct({ total_spins: 500000 }, { isFuzzy: true }),
    50
  );
  assert.equal(
    PURE.computeRunProgressPct({ total_spins: 100000 }, { isFuzzy: true, fuzzyTarget: 200000 }),
    50
  );
});

test("computeRunProgressPct: null event -> 0", () => {
  assert.equal(PURE.computeRunProgressPct(null, { maxChunks: 120 }), 0);
});

// ---------- prettyBucketLabel ----------

test("prettyBucketLabel: new 12-bucket schema renders compact ranges", () => {
  // Anchor labels for the new bin set so a future analyzer change can't
  // silently shift the chart x-axis.
  assert.equal(PURE.prettyBucketLabel("eq0"), "0");
  assert.equal(PURE.prettyBucketLabel("gt0_lt1"), "0\u20131");
  assert.equal(PURE.prettyBucketLabel("ge1_lt5"), "1\u20135");
  assert.equal(PURE.prettyBucketLabel("ge100_lt200"), "100\u2013200");
  assert.equal(PURE.prettyBucketLabel("ge5000"), "\u22655000");
});

test("prettyBucketLabel: legacy bucket keys still render", () => {
  // Old reports (pre-bucket-redefinition commit) keep their original
  // chart labels so the chart never shows a raw "ge100" key.
  assert.equal(PURE.prettyBucketLabel("gt0_lt0.5"), "0\u20130.5");
  assert.equal(PURE.prettyBucketLabel("ge100"), "\u2265100");
});

test("prettyBucketLabel: unknown key falls back to the raw key", () => {
  assert.equal(PURE.prettyBucketLabel("future_label_x"), "future_label_x");
});

// ---------- formatPayoutGroupRows ----------

test("formatPayoutGroupRows: empty -> []", () => {
  assert.deepStrictEqual(PURE.formatPayoutGroupRows({}), []);
});

test("formatPayoutGroupRows: sorts by rtp contribution desc, group 0 kept", () => {
  const s = {
    player_impact: {
      payout_groups_top20: [
        { group_id: 0, hit_count: 1500, hit_rate: 0.75, total_win: 0, avg_win_when_hit_x: 0, rtp_contribution_pp: 0 },
        { group_id: 7, hit_count: 200, hit_rate: 0.10, total_win: 50000, avg_win_when_hit_x: 2.5, rtp_contribution_pp: 25.0 },
        { group_id: 3, hit_count: 100, hit_rate: 0.05, total_win: 80000, avg_win_when_hit_x: 8.0, rtp_contribution_pp: 40.0 },
      ],
    },
  };
  const rows = PURE.formatPayoutGroupRows(s);
  assert.equal(rows.length, 3);
  // Sorted by rtp_contribution_pp desc -> 3, 7, 0
  assert.deepStrictEqual(
    rows.map((r) => r.group_id),
    [3, 7, 0]
  );
  assert.equal(rows[0].rtp_contribution_pp, 40.0);
  assert.equal(rows[0].hit_rate_pct, 5);
  assert.equal(rows[2].avg_win_when_hit_x, 0);
});

// ---------- formatPayoutIdRows ----------

test("formatPayoutIdRows: empty / missing surface -> []", () => {
  assert.deepStrictEqual(PURE.formatPayoutIdRows({}), []);
  assert.deepStrictEqual(PURE.formatPayoutIdRows({ player_impact: {} }), []);
});

test("formatPayoutIdRows: sorts by rtp_contribution_pp desc", () => {
  // Realistic M272 mode 2 shape (3 dominant ids).
  const s = {
    player_impact: {
      payout_ids_top20: [
        { payout_id: "1", hit_count: 30, hit_rate: 0.05, total_win: 333300, avg_win_when_hit: 11110, rtp_contribution_pp: 73.0 },
        { payout_id: "2", hit_count: 5, hit_rate: 0.008, total_win: 49950, avg_win_when_hit: 9990, rtp_contribution_pp: 11.0 },
        { payout_id: "8", hit_count: 4, hit_rate: 0.006, total_win: 16500, avg_win_when_hit: 4125, rtp_contribution_pp: 4.0 },
      ],
    },
  };
  const rows = PURE.formatPayoutIdRows(s);
  assert.equal(rows.length, 3);
  assert.deepStrictEqual(
    rows.map((r) => r.payout_id),
    ["1", "2", "8"]
  );
  assert.equal(rows[0].rtp_contribution_pp, 73.0);
  assert.equal(rows[0].hit_rate_pct, 5);
  assert.equal(rows[0].avg_win_when_hit, 11110);
  assert.equal(rows[0].total_win, 333300);
});

test("formatPayoutIdRows: tolerates missing fields with zero defaults", () => {
  const s = {
    player_impact: {
      payout_ids_top20: [
        { payout_id: "666", hit_count: 1 }, // hit but no win info
      ],
    },
  };
  const rows = PURE.formatPayoutIdRows(s);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].payout_id, "666");
  assert.equal(rows[0].hit_count, 1);
  assert.equal(rows[0].hit_rate_pct, 0);
  assert.equal(rows[0].total_win, 0);
  assert.equal(rows[0].avg_win_when_hit, 0);
  assert.equal(rows[0].rtp_contribution_pp, 0);
});

test("formatPayoutIdRows: payout_id is always coerced to string", () => {
  // Analyzer emits string already, but defensive coercion matters when
  // tests / older fixtures pass a number.
  const s = {
    player_impact: {
      payout_ids_top20: [{ payout_id: 6, hit_count: 1, total_win: 100 }],
    },
  };
  const rows = PURE.formatPayoutIdRows(s);
  assert.strictEqual(rows[0].payout_id, "6");
});

// ---------- formatSpinTypeRows ----------

test("formatSpinTypeRows: empty / missing -> []", () => {
  assert.deepStrictEqual(PURE.formatSpinTypeRows({}), []);
  assert.deepStrictEqual(PURE.formatSpinTypeRows({ player_impact: {} }), []);
});

test("formatSpinTypeRows: M272-shaped breakdown (main + bonus)", () => {
  const s = {
    player_impact: {
      spin_type_breakdown: [
        { spin_type: 140, spins: 200, share_pct: 64.5, win_rounds: 30, hit_rate: 0.15, total_win: 80000, rtp_pct: 80.0, rtp_contribution_pp: 50.0 },
        { spin_type: 126, spins: 110, share_pct: 35.5, win_rounds: 25, hit_rate: 0.227, total_win: 50000, rtp_pct: 0.0, rtp_contribution_pp: 30.0 },
      ],
    },
  };
  const rows = PURE.formatSpinTypeRows(s);
  assert.equal(rows.length, 2);
  // hit_rate is converted to percent (0.15 -> 15).
  assert.equal(rows[0].hit_rate_pct, 15);
  assert.equal(rows[1].hit_rate_pct, 22.7);
  // share_pct passes through unchanged (analyzer already in percent).
  assert.equal(rows[0].share_pct, 64.5);
  // spin_type stays numeric.
  assert.strictEqual(rows[0].spin_type, 140);
});

test("formatSpinTypeRows: zero defaults for missing fields", () => {
  const s = {
    player_impact: {
      spin_type_breakdown: [{ spin_type: 1, spins: 100 }],
    },
  };
  const rows = PURE.formatSpinTypeRows(s);
  assert.equal(rows[0].total_win, 0);
  // rtp_pct defaults to null now (was 0): the analyzer emits null for
  // free-spin types where the paid-bet denominator is 0 so the UI can
  // render "N/A" instead of a meaningless 0% or a nonsense percentage.
  // Legacy reports (field missing) also resolve to null so the UI
  // picks the same "N/A" path rather than inventing a number.
  assert.equal(rows[0].rtp_pct, null);
  assert.equal(rows[0].rtp_contribution_pp, 0);
  assert.equal(rows[0].win_rounds, 0);
  assert.equal(rows[0].hit_rate_pct, 0);
  // behavior_name defaults to empty string for legacy rows without
  // the analyzer's derived label.
  assert.equal(rows[0].behavior_name, "");
});

// ---------- computeLibPercentile + formatLibRank ----------

test("computeLibPercentile: empty / invalid values -> null", () => {
  assert.equal(PURE.computeLibPercentile(0.5, []), null);
  assert.equal(PURE.computeLibPercentile(0.5, null), null);
  assert.equal(PURE.computeLibPercentile(null, [1, 2, 3]), null);
  assert.equal(PURE.computeLibPercentile(NaN, [1, 2, 3]), null);
});

test("computeLibPercentile: percentile rank is count(<=v)/total * 100", () => {
  const r = PURE.computeLibPercentile(3, [1, 2, 3, 4, 5]);
  assert.equal(r.rank, 3);
  assert.equal(r.total, 5);
  assert.equal(r.percentile, 60);
});

test("computeLibPercentile: value above all -> 100th percentile", () => {
  const r = PURE.computeLibPercentile(100, [1, 2, 3]);
  assert.equal(r.percentile, 100);
  assert.equal(r.rank, 3);
});

test("computeLibPercentile: value below all -> 0th percentile", () => {
  const r = PURE.computeLibPercentile(0, [1, 2, 3]);
  assert.equal(r.percentile, 0);
  assert.equal(r.rank, 0);
});

test("formatLibRank: small library (<3) uses rank/total shorthand", () => {
  const rank = { rank: 2, total: 2, percentile: 100 };
  const zh = PURE.formatLibRank(rank, "zh");
  assert.ok(zh.includes("2/2"), `zh small form: ${zh}`);
  const en = PURE.formatLibRank(rank, "en");
  assert.ok(en.includes("2/2"), `en small form: ${en}`);
});

test("formatLibRank: big library shows percentile + fraction", () => {
  const rank = { rank: 14, total: 17, percentile: 82.35 };
  const out = PURE.formatLibRank(rank, "en");
  assert.ok(out.includes("P82"), `percentile token: ${out}`);
  assert.ok(out.includes("14/17"), `fraction token: ${out}`);
});

test("formatLibRank: >=99th percentile renders as P99+", () => {
  const rank = { rank: 50, total: 50, percentile: 100 };
  const out = PURE.formatLibRank(rank, "en");
  assert.ok(out.includes("P99+"), `cap token: ${out}`);
});

test("formatLibRank: empty/invalid rank -> ''", () => {
  assert.equal(PURE.formatLibRank(null, "en"), "");
  assert.equal(PURE.formatLibRank({ total: 0 }, "en"), "");
});

test("formatSpinTypeRows: free-spin rtp_pct=null passes through untouched", () => {
  const s = {
    player_impact: {
      spin_type_breakdown: [
        {
          spin_type: 126,
          spins: 1520,
          total_win: 3821000,
          rtp_pct: null,
          rtp_contribution_pp: 40.14,
          behavior_name: "free",
        },
      ],
    },
  };
  const rows = PURE.formatSpinTypeRows(s);
  assert.equal(rows[0].rtp_pct, null);
  assert.equal(rows[0].behavior_name, "free");
  assert.ok(rows[0].rtp_contribution_pp > 0);
});

// ---------- formatSymbolRows + symbolByColMatrix ----------

test("formatSymbolRows: empty -> []", () => {
  assert.deepStrictEqual(PURE.formatSymbolRows({}), []);
});

test("formatSymbolRows: maps symbol/count/rate_pct correctly", () => {
  const s = {
    player_impact: {
      symbols_top20: [
        { symbol: "blank", count: 5000, rate: 0.5 },
        { symbol: "cherry", count: 1234, rate: 0.1234 },
      ],
    },
  };
  const rows = PURE.formatSymbolRows(s);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].symbol, "blank");
  assert.equal(rows[0].count, 5000);
  assert.equal(rows[0].rate_pct, 50);
  assert.equal(rows[1].symbol, "cherry");
  assert.equal(rows[1].rate_pct, 12.34);
});

test("symbolByColMatrix: empty -> {columnIds:[], rowsByCol:{}}", () => {
  const m = PURE.symbolByColMatrix({});
  assert.deepStrictEqual(m.columnIds, []);
  assert.deepStrictEqual(m.rowsByCol, {});
});

test("symbolByColMatrix: numeric column ids sorted", () => {
  const s = {
    player_impact: {
      symbols_by_column_top10: {
        "2": [{ symbol: "high7", count: 100, rate: 0.05 }],
        "0": [{ symbol: "blank", count: 5000, rate: 0.5 }],
        "1": [{ symbol: "wild", count: 800, rate: 0.08 }],
      },
    },
  };
  const m = PURE.symbolByColMatrix(s);
  assert.deepStrictEqual(m.columnIds, ["0", "1", "2"]);
  assert.equal(m.rowsByCol["0"][0].symbol, "blank");
  assert.equal(m.rowsByCol["0"][0].rate_pct, 50);
  assert.equal(m.rowsByCol["2"][0].symbol, "high7");
});

// ---------- formatPaylineRows ----------

test("formatPaylineRows: empty summary -> []", () => {
  assert.deepStrictEqual(PURE.formatPaylineRows({}), []);
  assert.deepStrictEqual(PURE.formatPaylineRows({ player_impact: {} }), []);
});

test("formatPaylineRows: sorts by rtp contribution desc by default", () => {
  const summary = {
    player_impact: {
      paylines_top20: [
        { payline_id: "1", hit_count: 100, hit_rate: 0.05, approx_rtp_contribution_pp: 12.0 },
        { payline_id: "2", hit_count: 200, hit_rate: 0.1, approx_rtp_contribution_pp: 30.0 },
        { payline_id: "3", hit_count: 50, hit_rate: 0.025, approx_rtp_contribution_pp: 8.0 },
      ],
    },
  };
  const rows = PURE.formatPaylineRows(summary);
  assert.equal(rows.length, 3);
  assert.deepStrictEqual(
    rows.map((r) => r.payline_id),
    ["2", "1", "3"]
  );
  // win_share is computed against the sum of contributions (50pp total).
  assert.equal(rows[0].win_share_pct, 60); // 30/50 = 60%
  assert.equal(rows[1].win_share_pct, 24); // 12/50 = 24%
  assert.equal(rows[2].win_share_pct, 16); // 8/50 = 16%
});

test("formatPaylineRows: hit_rate gets converted to percent", () => {
  const summary = {
    player_impact: {
      paylines_top20: [
        { payline_id: "1", hit_count: 100, hit_rate: 0.0123, approx_rtp_contribution_pp: 1.0 },
      ],
    },
  };
  const rows = PURE.formatPaylineRows(summary);
  assert.equal(rows[0].hit_rate_pct, 1.23);
});

test("formatPaylineRows: top_symbols passthrough (analyzer winning-symbol commit)", () => {
  // Newer reports include analyzer-inferred top winning symbols per
  // payline. The pure formatter just pipes them through to the row.
  const summary = {
    player_impact: {
      paylines_top20: [
        {
          payline_id: "1",
          hit_count: 10,
          hit_rate: 0.005,
          approx_rtp_contribution_pp: 5.0,
          top_symbols: [
            { symbol: "cherry", count: 7 },
            { symbol: "1bar", count: 2 },
            { symbol: "blank", count: 1 },
          ],
        },
      ],
    },
  };
  const rows = PURE.formatPaylineRows(summary);
  assert.equal(rows.length, 1);
  assert.deepStrictEqual(rows[0].top_symbols, [
    { symbol: "cherry", count: 7 },
    { symbol: "1bar", count: 2 },
    { symbol: "blank", count: 1 },
  ]);
});

test("formatPaylineRows: top_symbols defaults to [] for old reports", () => {
  const summary = {
    player_impact: {
      paylines_top20: [
        { payline_id: "1", hit_count: 10, hit_rate: 0.005, approx_rtp_contribution_pp: 5.0 },
      ],
    },
  };
  const rows = PURE.formatPaylineRows(summary);
  assert.deepStrictEqual(rows[0].top_symbols, []);
});

// ---------- formatPaylineTopSymbols ----------

test("formatPaylineTopSymbols: empty -> em-dash", () => {
  assert.equal(PURE.formatPaylineTopSymbols([]), "\u2014");
  assert.equal(PURE.formatPaylineTopSymbols(null), "\u2014");
  assert.equal(PURE.formatPaylineTopSymbols(undefined), "\u2014");
});

test("formatPaylineTopSymbols: top 3 by default, comma joined", () => {
  const out = PURE.formatPaylineTopSymbols([
    { symbol: "cherry", count: 7 },
    { symbol: "1bar", count: 2 },
    { symbol: "blank", count: 1 },
    { symbol: "2bar", count: 1 },
  ]);
  assert.equal(out, "cherry, 1bar, blank");
});

test("formatPaylineTopSymbols: respects N override", () => {
  const out = PURE.formatPaylineTopSymbols(
    [
      { symbol: "cherry", count: 7 },
      { symbol: "1bar", count: 2 },
    ],
    1
  );
  assert.equal(out, "cherry");
});

// ---------- extractMetricCards ----------

const _summaryFixture = () => ({
  rtp: { point_pct: 95.123 },
  sampling: { achieved_halfwidth_pp: 0.482, total_spins: 2400000 },
  player_impact: {
    hit_and_payout: { zero_win_rate: 0.78, big_win_x10_rate: 0.0123 },
    volatility: { max_observed_return_x: 421.5 },
    streaks: { loss_streak_p95: 14 },
  },
  guideline_assessment: {
    classification: { volatility_class: "High", experience_archetype: "Boom-Bust" },
    derived_metrics: { tail_dependency: 0.41 },
    bankruptcy_checks: { x500_bankruptcy_rate: 0.012 },
  },
  guideline_comparison: { overall_status: "FAIL" },
});

test("extractMetricCards: pulls all 12 cards from a summary", () => {
  const c = PURE.extractMetricCards(_summaryFixture());
  for (const k of [
    "rtp", "ci", "spins", "zeroWin", "tailDep", "guideline",
    "volatility", "archetype", "lossStreak", "maxReturn", "bigWin", "bankruptX500",
  ]) {
    assert.ok(c[k] != null, `${k} missing`);
    assert.ok("value" in c[k], `${k}.value missing`);
    assert.ok("tone" in c[k], `${k}.tone missing`);
  }
  assert.equal(c.rtp.value, "95.12%");
  assert.equal(c.ci.value, "0.482");
  assert.equal(c.spins.value, "2,400,000");
  assert.equal(c.zeroWin.value, "78.00%");
  // tailDep.value is now "≥10x N.N%" format (2×2 grid display).
  assert.ok(c.tailDep.value.includes("41.0%"), `tailDep.value=${c.tailDep.value}`);
  assert.equal(c.volatility.value, "High");
  assert.equal(c.archetype.value, "Boom-Bust");
  assert.equal(c.lossStreak.value, "14");
  assert.equal(c.maxReturn.value, "421.5x");
  assert.equal(c.bigWin.value, "1.230%");
  assert.equal(c.bankruptX500.value, "1.200%");
  assert.equal(c.guideline.value, "FAIL");
});

test("extractMetricCards: tone classification respects guideline thresholds", () => {
  const c = PURE.extractMetricCards(_summaryFixture());
  assert.equal(c.zeroWin.tone, "warn");          // 0.78 in (0.75, 0.82]
  assert.equal(c.tailDep.tone, "neutral");       // 0.41 in [0.20, 0.45)
  assert.equal(c.lossStreak.tone, "good");       // 14 < 15
  assert.equal(c.bankruptX500.tone, "warn");     // 0.012 in [0.01, 0.05)
  assert.equal(c.guideline.tone, "bad");         // FAIL
  assert.equal(c.rtp.tone, "neutral");
  assert.equal(c.volatility.tone, "neutral");
});

test("extractMetricCards: missing summary fields -> N/A and neutral tone", () => {
  const c = PURE.extractMetricCards({});
  for (const k of ["rtp", "ci", "spins", "zeroWin", "tailDep", "guideline",
                    "volatility", "archetype", "lossStreak", "maxReturn",
                    "bigWin", "bankruptX500"]) {
    assert.equal(c[k].value, "N/A", `${k}.value should be N/A`);
  }
  assert.equal(c.zeroWin.tone, "neutral");
  assert.equal(c.guideline.tone, "warn"); // empty status falls into warn bucket
});

// ---------- formatAutotuneProgress ----------

test("formatAutotuneProgress: idle status -> localized 'no autotune yet'", () => {
  assert.equal(PURE.formatAutotuneProgress("en", { status: "idle" }), "no autotune yet");
  assert.equal(PURE.formatAutotuneProgress("zh", { status: "idle" }), "未发起压测");
});

test("formatAutotuneProgress: running with no candidates yet -> 'starting'", () => {
  assert.equal(
    PURE.formatAutotuneProgress("en", { status: "running", total_candidates: 0 }),
    "autotune starting..."
  );
});

test("formatAutotuneProgress: running mid-flight shows X/Y + percent + last result", () => {
  const out = PURE.formatAutotuneProgress("en", {
    status: "running",
    total_candidates: 20,
    completed_candidates: 7,
    last_result: {
      robot_count: 16,
      batch_concurrency: 2,
      success_rate: 0.96,
      throughput_spins_per_sec: 4200.5,
      p95_latency_s: 0.553,
    },
  });
  assert.ok(out.includes("7/20"), out);
  assert.ok(out.includes("35%"), out);  // 7/20 = 35%
  assert.ok(out.includes("robot=16"));
  assert.ok(out.includes("96.0%"));
  assert.ok(out.includes("4201"));  // 4200.5 -> toFixed(0) = "4201"
  assert.ok(out.includes("0.553"));
});

test("formatAutotuneProgress: completed status uses 'completed' template", () => {
  const out = PURE.formatAutotuneProgress("en", {
    status: "completed",
    total_candidates: 20,
    completed_candidates: 20,
  });
  assert.ok(out.includes("completed"));
  assert.ok(out.includes("20"));
});

test("formatAutotuneProgress: error status surfaces partial count", () => {
  const out = PURE.formatAutotuneProgress("en", {
    status: "error",
    total_candidates: 20,
    completed_candidates: 5,
  });
  assert.ok(out.includes("error"));
  assert.ok(out.includes("5/20"));
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

// ---------- sampling log timeline (layer 1) ----------

test("buildClientEvent: click includes count + mode + ci", () => {
  const ev = PURE.buildClientEvent(
    "click", { count: 3, mode: 1, ci: 0.5 }, "2026-04-17T12:00:00Z"
  );
  assert.equal(ev.ts, "2026-04-17T12:00:00Z");
  assert.equal(ev.level, "info");
  assert.equal(ev.source, "ui");
  assert.ok(ev.text.includes("开始采样"));
  assert.ok(ev.text.includes("3 台"));
  assert.ok(ev.text.includes("mode=1"));
  assert.ok(ev.text.includes("0.5pp"));
});

test("buildClientEvent: fuzzy (ci=0) renders as 'fuzzy' not '0pp'", () => {
  const ev = PURE.buildClientEvent(
    "click", { count: 1, mode: 2, ci: 0 }, "2026-04-17T12:00:00Z"
  );
  assert.ok(ev.text.includes("fuzzy"));
  assert.ok(!ev.text.includes("0pp"));
});

test("buildClientEvent: batch_created truncates id to 8 chars", () => {
  const ev = PURE.buildClientEvent(
    "batch_created",
    { batchId: "abcdef0123456789-very-long" },
    "2026-04-17T12:00:01Z"
  );
  assert.ok(ev.text.includes("abcdef01"));
  assert.ok(!ev.text.includes("abcdef0123"));
});

test("buildClientEvent: submit_failed is level=error", () => {
  const ev = PURE.buildClientEvent(
    "submit_failed", { error: "network down" }, "2026-04-17T12:00:01Z"
  );
  assert.equal(ev.level, "error");
  assert.ok(ev.text.includes("network down"));
});

test("buildClientEvent: unknown kind returns placeholder, no crash", () => {
  const ev = PURE.buildClientEvent("zzznope", {}, "2026-04-17T12:00:00Z");
  assert.equal(ev.level, "info");
  assert.ok(ev.text.includes("zzznope"));
});

test("formatChunkEventText: chunk_progress includes spins + RTP + CI", () => {
  const t = PURE.formatChunkEventText({
    event: "chunk_progress", chunk_index: 5,
    total_spins: 500000, current_rtp_pct: 92.07, current_halfwidth_pp: 0.63,
  });
  assert.ok(t.includes("chunk 5"));
  assert.ok(t.includes("500,000"));
  assert.ok(t.includes("92.07%"));
  assert.ok(t.includes("±0.630pp"));
});

test("formatChunkEventText: chunk_progress prefers session_rtp_pct when present", () => {
  // Paid-session RTP (session_rtp_pct=95.43) and spin-level RTP
  // (current_rtp_pct=83.11) diverge on collect-mechanic machines.
  // UI must show the session-level number to match the final summary.
  const t = PURE.formatChunkEventText({
    event: "chunk_progress", chunk_index: 3,
    total_spins: 300000,
    current_rtp_pct: 83.11, session_rtp_pct: 95.43,
    current_halfwidth_pp: 0.5,
  });
  assert.ok(t.includes("95.43%"), `session_rtp_pct should win; got: ${t}`);
  assert.ok(!t.includes("83.11%"), `current_rtp_pct must not leak; got: ${t}`);
});

test("formatChunkEventText: chunk_progress falls back to current_rtp_pct on legacy events", () => {
  // Pre-2026-04-17 analyzer builds don't emit session_rtp_pct; the
  // UI must still render those events (the same progress.jsonl files
  // are re-consumed by rebuild_rawdata_index + offline analysis).
  const t = PURE.formatChunkEventText({
    event: "chunk_progress", chunk_index: 1,
    total_spins: 100000, current_rtp_pct: 92.0,
  });
  assert.ok(t.includes("92.00%"), `should fall back to current_rtp_pct; got: ${t}`);
});

test("formatChunkEventText: chunk_progress with session_rtp_pct=null falls back", () => {
  // session_rtp_pct is null when session_bet_sum==0 (no paid sessions
  // have completed yet in the run — should be rare but can happen in
  // the first chunk of a bonus-heavy machine before the first paid
  // session closes). Fall back to current_rtp_pct rather than showing
  // a literal "null".
  const t = PURE.formatChunkEventText({
    event: "chunk_progress", chunk_index: 1,
    total_spins: 50000,
    session_rtp_pct: null, current_rtp_pct: 80.0,
  });
  assert.ok(t.includes("80.00%"), `null session_rtp_pct should fall back; got: ${t}`);
});

test("formatChunkEventText: chunk_failed uses ✗ + cumulative counter", () => {
  const t = PURE.formatChunkEventText({
    event: "chunk_failed", chunk_index: 12,
    error: "request_failed_http_502", cumulative_failed: 4,
  });
  assert.ok(t.startsWith("✗"));
  assert.ok(t.includes("chunk 12"));
  assert.ok(t.includes("502"));
  assert.ok(t.includes("累计失败 4"));
});

test("formatChunkEventText: analyzer_started + fetching_chunk render (layer 3)", () => {
  const t1 = PURE.formatChunkEventText({ event: "analyzer_started", pid: 8877 });
  assert.ok(t1.includes("analyzer 就绪"));
  assert.ok(t1.includes("8877"));
  const t2 = PURE.formatChunkEventText({ event: "fetching_chunk", chunk_index: 1 });
  assert.ok(t2.includes("请求 chunk 1"));
});

test("computeElapsedSeconds: rounds to tenths of a second", () => {
  assert.equal(PURE.computeElapsedSeconds(1000, 1500), 0.5);
  assert.equal(PURE.computeElapsedSeconds(1000, 2345), 1.3);
  assert.equal(PURE.computeElapsedSeconds(1000, 1050), 0.1);
  assert.equal(PURE.computeElapsedSeconds(null, 2000), null);
  assert.equal(PURE.computeElapsedSeconds(2000, 1000), 0);
});

test("mergeTimeline: merges and sorts by ts across sources", () => {
  const data = {
    events: [
      { ts: "2026-04-17T12:00:05Z", level: "info", machine: "M14", text: "开始 API 采样" },
    ],
    items: [
      {
        machine: "M14",
        chunk_events: [
          { event: "chunk_progress", chunk_index: 1, ts: "2026-04-17T12:00:30Z",
            total_spins: 100000, current_rtp_pct: 92.0 },
          { event: "chunk_failed", chunk_index: 2, ts: "2026-04-17T12:00:45Z",
            error: "504", cumulative_failed: 1 },
        ],
      },
    ],
  };
  const clientEvents = [
    { ts: "2026-04-17T12:00:00Z", level: "info", source: "ui", text: "▷ 开始采样" },
    { ts: "2026-04-17T12:00:02Z", level: "info", source: "ui", text: "⋯ 提交…" },
  ];
  const out = PURE.mergeTimeline(data, clientEvents);
  assert.deepEqual(out.map((r) => r.ts), [
    "2026-04-17T12:00:00Z",
    "2026-04-17T12:00:02Z",
    "2026-04-17T12:00:05Z",
    "2026-04-17T12:00:30Z",
    "2026-04-17T12:00:45Z",
  ]);
  assert.equal(out[0].source, "ui");
  assert.equal(out[3].source, "M14");
  assert.equal(out[4].level, "warn");  // chunk_failed → warn
});

test("mergeTimeline: critical events never pruned; chunk_progress capped", () => {
  const items = [{
    machine: "M14",
    chunk_events: [
      ...Array.from({ length: 12 }, (_, i) => ({
        event: "chunk_progress", chunk_index: i + 1,
        total_spins: (i + 1) * 1000, current_rtp_pct: 92.0,
        ts: `2026-04-17T12:${String(i).padStart(2, "0")}:00Z`,
      })),
      { event: "chunk_failed", chunk_index: 50, error: "504",
        cumulative_failed: 1, ts: "2026-04-17T12:15:00Z" },
      { event: "chunk_failed", chunk_index: 51, error: "504",
        cumulative_failed: 2, ts: "2026-04-17T12:15:05Z" },
      { event: "chunk_failed", chunk_index: 52, error: "504",
        cumulative_failed: 3, ts: "2026-04-17T12:15:10Z" },
      { event: "failed", reason: "upstream_unstable:...",
        ts: "2026-04-17T12:15:15Z" },
    ],
  }];
  const out = PURE.mergeTimeline({ events: [], items }, []);
  const failedRows = out.filter((r) => r.text.includes("失败") || r.text.includes("终止"));
  assert.equal(failedRows.length, 4, "all 4 critical events must survive");
  const progressRows = out.filter(
    (r) => r.kind === "chunk" && !r.text.includes("失败") && !r.text.includes("终止")
  );
  assert.equal(progressRows.length, 8, "chunk_progress must be capped at 8");
});

test("mergeTimeline: progressCap override is honored", () => {
  const items = [{
    machine: "M14",
    chunk_events: Array.from({ length: 20 }, (_, i) => ({
      event: "chunk_progress", chunk_index: i + 1,
      total_spins: 1000, current_rtp_pct: 92,
      ts: `2026-04-17T12:${String(i).padStart(2, "0")}:00Z`,
    })),
  }];
  const out = PURE.mergeTimeline({ events: [], items }, [], 3);
  assert.equal(out.length, 3);
});

test("mergeTimeline: empty inputs yield empty list", () => {
  assert.deepEqual(PURE.mergeTimeline({}, []), []);
  assert.deepEqual(PURE.mergeTimeline({ events: [], items: [] }, null), []);
});

test("mergeTimeline: batch event without machine tag falls back to 'batch'", () => {
  const data = {
    events: [{ ts: "2026-04-17T12:00:00Z", level: "info", text: "disk ok" }],
    items: [],
  };
  const out = PURE.mergeTimeline(data, []);
  assert.equal(out[0].source, "batch");
});

test("mergeTimeline: chunk_started events are filtered out of timeline", () => {
  // chunk_started drives the separate in-flight section. Including it
  // in the timeline would double-count: once as "⇅ chunk 38 发出" and
  // again when the chunk_progress lands.
  const items = [{
    machine: "M14",
    chunk_events: [
      { event: "chunk_started", chunk_index: 38, ts: "2026-04-17T12:00:00Z" },
      { event: "chunk_started", chunk_index: 39, ts: "2026-04-17T12:00:00Z" },
      { event: "chunk_progress", chunk_index: 38, total_spins: 100000,
        current_rtp_pct: 92, ts: "2026-04-17T12:00:30Z" },
    ],
  }];
  const out = PURE.mergeTimeline({ events: [], items }, []);
  assert.equal(out.length, 1, "only chunk_progress should render");
  assert.equal(out[0].kind, "chunk");
  assert.ok(out[0].text.includes("chunk 38"));
});

// ---------- computeInflightChunks ----------

test("computeInflightChunks: returns started chunks without matching completion", () => {
  const item = {
    machine: "M273",
    chunk_events: [
      { event: "chunk_started", chunk_index: 38, ts: "2026-04-17T12:00:00Z" },
      { event: "chunk_started", chunk_index: 39, ts: "2026-04-17T12:00:00Z" },
      { event: "chunk_started", chunk_index: 40, ts: "2026-04-17T12:00:00Z" },
      { event: "chunk_started", chunk_index: 41, ts: "2026-04-17T12:00:00Z" },
      // 38 completed successfully, 41 failed — both leave the in-flight set.
      { event: "chunk_progress", chunk_index: 38, total_spins: 100000,
        current_rtp_pct: 92, ts: "2026-04-17T12:00:30Z" },
      { event: "chunk_failed", chunk_index: 41, error: "504",
        cumulative_failed: 1, ts: "2026-04-17T12:00:35Z" },
    ],
  };
  const out = PURE.computeInflightChunks(item);
  const indices = out.map((c) => c.chunk_index);
  assert.deepEqual(indices, [39, 40], "only chunks 39+40 still in flight");
  assert.equal(out[0].startedTs, "2026-04-17T12:00:00Z");
  assert.ok(Number.isFinite(out[0].startedMs), "startedMs should be parseable epoch");
});

test("computeInflightChunks: empty / missing events → []", () => {
  assert.deepEqual(PURE.computeInflightChunks({}), []);
  assert.deepEqual(PURE.computeInflightChunks({ chunk_events: [] }), []);
  assert.deepEqual(PURE.computeInflightChunks(null), []);
  assert.deepEqual(PURE.computeInflightChunks(undefined), []);
});

test("computeInflightChunks: sorted by chunk_index ascending", () => {
  const item = {
    chunk_events: [
      { event: "chunk_started", chunk_index: 10, ts: "2026-04-17T12:00:00Z" },
      { event: "chunk_started", chunk_index: 7, ts: "2026-04-17T12:00:00Z" },
      { event: "chunk_started", chunk_index: 25, ts: "2026-04-17T12:00:00Z" },
    ],
  };
  const out = PURE.computeInflightChunks(item);
  assert.deepEqual(out.map((c) => c.chunk_index), [7, 10, 25]);
});

test("computeInflightChunks: started+completed in same tick still empty", () => {
  // Can happen if chunk returns from a cached response instantly.
  const item = {
    chunk_events: [
      { event: "chunk_started", chunk_index: 1, ts: "2026-04-17T12:00:00Z" },
      { event: "chunk_progress", chunk_index: 1, total_spins: 1000,
        current_rtp_pct: 92, ts: "2026-04-17T12:00:00Z" },
    ],
  };
  assert.deepEqual(PURE.computeInflightChunks(item), []);
});

test("formatChunkEventText: chunk_started fallback text (rare path)", () => {
  // Normally filtered from timeline; this is the defensive path if a
  // caller renders one directly (e.g. debug panel).
  const t = PURE.formatChunkEventText({ event: "chunk_started", chunk_index: 38 });
  assert.ok(t.includes("chunk 38"));
  assert.ok(t.includes("发出"));
});

// ---------- adaptive_tune + circuit_pause (phase 3) ----------

test("formatChunkEventText: adaptive_tune down direction uses ↓", () => {
  const t = PURE.formatChunkEventText({
    event: "adaptive_tune", direction: "down",
    from_concurrency: 4, to_concurrency: 2,
    from_chunk_spins: 5000, to_chunk_spins: 2500,
    reason: "fully_failed_batch",
  });
  assert.ok(t.includes("↓"));
  assert.ok(t.includes("整批失败"));
  assert.ok(t.includes("并发 4→2"));
  assert.ok(t.includes("chunk_spins 5000→2500"));
});

test("formatChunkEventText: adaptive_tune up direction uses ↑", () => {
  const t = PURE.formatChunkEventText({
    event: "adaptive_tune", direction: "up",
    from_concurrency: 2, to_concurrency: 3,
    from_chunk_spins: 2500, to_chunk_spins: 3125,
    reason: "success_streak",
  });
  assert.ok(t.includes("↑"));
  assert.ok(t.includes("连续成功"));
  assert.ok(t.includes("2→3"));
});

test("formatChunkEventText: circuit_pause shows seconds + reason", () => {
  const t = PURE.formatChunkEventText({
    event: "circuit_pause", pause_seconds: 20,
    reason: "fully_failed_batch",
  });
  assert.ok(t.includes("⏸"));
  assert.ok(t.includes("20s"));
  assert.ok(t.includes("fully_failed_batch"));
});

test("mergeTimeline: adaptive_tune + circuit_pause are CRITICAL (never pruned)", () => {
  const items = [{
    machine: "M273",
    chunk_events: [
      // 20 progress events would normally prune, but adaptive_tune
      // and circuit_pause pass through anyway.
      ...Array.from({ length: 20 }, (_, i) => ({
        event: "chunk_progress", chunk_index: i + 1,
        total_spins: 1000, current_rtp_pct: 92,
        ts: `2026-04-17T12:${String(i).padStart(2, "0")}:00Z`,
      })),
      { event: "adaptive_tune", direction: "down",
        from_concurrency: 4, to_concurrency: 2,
        from_chunk_spins: 5000, to_chunk_spins: 2500,
        reason: "fully_failed_batch",
        ts: "2026-04-17T12:30:00Z" },
      { event: "circuit_pause", pause_seconds: 20,
        reason: "fully_failed_batch",
        ts: "2026-04-17T12:30:00Z" },
    ],
  }];
  const out = PURE.mergeTimeline({ events: [], items }, []);
  const kinds = out.map((r) => r.text);
  assert.ok(kinds.some((t) => t.includes("↓")), "adaptive_tune must survive prune");
  assert.ok(kinds.some((t) => t.includes("⏸")), "circuit_pause must survive prune");
  // warn level on both so UI colors them distinctly from normal chunk events.
  const tune = out.find((r) => r.text.includes("↓"));
  const pause = out.find((r) => r.text.includes("⏸"));
  assert.equal(tune.level, "warn");
  assert.equal(pause.level, "warn");
});


// ---------- versionBadges (Commit 4: Run History staleness) ----------

test("versionBadges: both match current → both fresh", () => {
  const row = {
    machine: "M14", rawdata_config_md5: "CFG", rawdata_code_md5: "CODE",
    analyzer_version: "AAAA",
  };
  const current = {
    analyzer_version: "AAAA",
    machines: { M14: { config_md5: "CFG", code_md5: "CODE" } },
  };
  const badges = PURE.versionBadges(row, current);
  assert.equal(badges.rawdata.tier, "fresh");
  assert.equal(badges.analyzer.tier, "fresh");
});

test("versionBadges: rawdata mismatch → rawdata stale, analyzer fresh", () => {
  const row = {
    machine: "M14", rawdata_config_md5: "OLD_CFG", rawdata_code_md5: "OLD_CODE",
    analyzer_version: "AAAA",
  };
  const current = {
    analyzer_version: "AAAA",
    machines: { M14: { config_md5: "NEW_CFG", code_md5: "NEW_CODE" } },
  };
  const badges = PURE.versionBadges(row, current);
  assert.equal(badges.rawdata.tier, "stale");
  assert.ok(badges.rawdata.tip.includes("cur="));
  assert.equal(badges.analyzer.tier, "fresh");
});

test("versionBadges: analyzer mismatch → analyzer stale, rawdata fresh", () => {
  const row = {
    machine: "M14", rawdata_config_md5: "CFG", rawdata_code_md5: "CODE",
    analyzer_version: "OLDAAAA",
  };
  const current = {
    analyzer_version: "NEWBBBB",
    machines: { M14: { config_md5: "CFG", code_md5: "CODE" } },
  };
  const badges = PURE.versionBadges(row, current);
  assert.equal(badges.rawdata.tier, "fresh");
  assert.equal(badges.analyzer.tier, "stale");
});

test("versionBadges: legacy row (null fingerprints) → both untagged", () => {
  const row = {
    machine: "M14", rawdata_config_md5: null, rawdata_code_md5: null,
    analyzer_version: null,
  };
  const current = {
    analyzer_version: "AAAA",
    machines: { M14: { config_md5: "CFG", code_md5: "CODE" } },
  };
  const badges = PURE.versionBadges(row, current);
  assert.equal(badges.rawdata.tier, "untagged");
  assert.equal(badges.analyzer.tier, "untagged");
});

test("versionBadges: machine missing from current → rawdata untagged", () => {
  /* Unregistered machine (not in machines.json). Without an upstream
     reference, we can't verify — show untagged, not stale. */
  const row = {
    machine: "M999", rawdata_config_md5: "CFG", rawdata_code_md5: "CODE",
    analyzer_version: "AAAA",
  };
  const current = {
    analyzer_version: "AAAA",
    machines: { M14: { config_md5: "CFG", code_md5: "CODE" } },
  };
  const badges = PURE.versionBadges(row, current);
  assert.equal(badges.rawdata.tier, "untagged");
  assert.equal(badges.analyzer.tier, "fresh");
});

test("versionBadges: null row / empty current → safe defaults", () => {
  const b1 = PURE.versionBadges(null, null);
  assert.equal(b1.rawdata.tier, "untagged");
  assert.equal(b1.analyzer.tier, "untagged");
  const b2 = PURE.versionBadges({}, {});
  assert.equal(b2.rawdata.tier, "untagged");
  assert.equal(b2.analyzer.tier, "untagged");
});
