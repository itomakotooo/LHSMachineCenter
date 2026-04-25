"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const D = require(path.resolve(__dirname, "../../src/web_console/frontend/compare_diff.js"));

// ---------- signDelta ----------

test("signDelta: up / down / eq", () => {
  assert.equal(D.signDelta(1, 2), "up");
  assert.equal(D.signDelta(2, 1), "down");
  assert.equal(D.signDelta(2, 2), "eq");
});

test("signDelta: NaN inputs collapse to eq", () => {
  assert.equal(D.signDelta("oops", 1), "eq");
  assert.equal(D.signDelta(1, undefined), "eq");
});

// ---------- isSignificant ----------

test("isSignificant: |Δ| > halfwidth_a + halfwidth_b → significant", () => {
  assert.equal(D.isSignificant(2.0, 0.5, 0.5), "significant");
  assert.equal(D.isSignificant(0.5, 0.5, 0.5), "noise");
});

test("isSignificant: missing CI half-widths fall back to 0.5pp threshold", () => {
  // 0.6pp > 0.5pp → significant when CI unknown.
  assert.equal(D.isSignificant(0.6, undefined, undefined), "significant");
  // 0.3pp < 0.5pp → unknown (we can't say without CI).
  assert.equal(D.isSignificant(0.3, undefined, undefined), "unknown");
});

// ---------- unionKeys ----------

test("unionKeys preserves A's order, then appends B-only keys in B's order", () => {
  const a = { x: 1, y: 2, z: 3 };
  const b = { y: 9, w: 7, x: 8 };
  // x, y, z (from A) then w (B-only)
  assert.deepEqual(D.unionKeys(a, b), ["x", "y", "z", "w"]);
});

test("unionKeys handles null / non-object inputs", () => {
  assert.deepEqual(D.unionKeys(null, { a: 1 }), ["a"]);
  assert.deepEqual(D.unionKeys({ a: 1 }, undefined), ["a"]);
  assert.deepEqual(D.unionKeys(null, null), []);
});

// ---------- alignByKey ----------

test("alignByKey: matches records, sorts by max(sortField), ties by key", () => {
  const a = [
    { payout_id: 1, total_win: 100 },
    { payout_id: 2, total_win: 50 },
  ];
  const b = [
    { payout_id: 1, total_win: 80 },   // both, max=100
    { payout_id: 3, total_win: 200 },  // only_b, max=200
  ];
  const out = D.alignByKey(a, b, "payout_id", "total_win");
  // Sorted by max desc: 200 (id=3), 100 (id=1), 50 (id=2).
  assert.deepEqual(out.map((r) => r.key), ["3", "1", "2"]);
  assert.equal(out[0].presence, "only_b");
  assert.equal(out[1].presence, "both");
  assert.equal(out[2].presence, "only_a");
});

// ---------- compatibilityChecks ----------

test("compatibilityChecks: same-machine same-mode → just 'ok'", () => {
  const a = { machine: "M14", mode: 1, sampling: { bet: 1000, total_spins: 1000 }, analyzer_version: "x" };
  const b = { machine: "M14", mode: 1, sampling: { bet: 1000, total_spins: 1000 }, analyzer_version: "x" };
  const out = D.compatibilityChecks(a, b);
  assert.ok(out.find((x) => x.level === "ok"), "should report ok when nothing differs");
  assert.equal(out.length, 1);
});

test("compatibilityChecks: cross-machine reports 'info' not 'warn'", () => {
  const a = { machine: "M14", mode: 1, sampling: { bet: 1000 } };
  const b = { machine: "M15", mode: 1, sampling: { bet: 1000 } };
  const out = D.compatibilityChecks(a, b);
  const cross = out.find((x) => x.text.includes("跨机台"));
  assert.ok(cross);
  assert.equal(cross.level, "info");
});

test("compatibilityChecks: different bet flagged as 'warn'", () => {
  const a = { machine: "M14", mode: 1, sampling: { bet: 1000 } };
  const b = { machine: "M14", mode: 1, sampling: { bet: 500 } };
  const out = D.compatibilityChecks(a, b);
  const w = out.find((x) => x.text.includes("bet"));
  assert.equal(w.level, "warn");
});

test("compatibilityChecks: 5x sample-size diff flags 'warn'", () => {
  const a = { machine: "M14", mode: 1, sampling: { bet: 1000, total_spins: 1000 } };
  const b = { machine: "M14", mode: 1, sampling: { bet: 1000, total_spins: 6000 } };
  const out = D.compatibilityChecks(a, b);
  const w = out.find((x) => x.text.includes("样本量"));
  assert.equal(w.level, "warn");
});

// ---------- extractHeadline ----------

test("extractHeadline: tolerates missing fields", () => {
  const h = D.extractHeadline({});
  // All numeric fields → NaN-safe; archetype/volatility → empty string.
  assert.ok(Number.isNaN(h.rtp_pct));
  assert.equal(h.archetype, "");
});

test("extractHeadline: pulls from rtp.point_pct + hit_and_payout + classification", () => {
  const s = {
    sampling: { achieved_halfwidth_pp: 0.5, total_spins: 100000 },
    rtp: { point_pct: 92.5 },
    player_impact: {
      hit_and_payout: { win_hit_rate: 0.38, big_win_x10_rate: 0.02 },
    },
    guideline_assessment: {
      classification: { experience_archetype: "Balanced", volatility_class: "Mid" },
    },
  };
  const h = D.extractHeadline(s);
  assert.equal(h.rtp_pct, 92.5);
  assert.equal(h.hit_rate, 0.38);
  assert.equal(h.archetype, "Balanced");
  assert.equal(h.volatility, "Mid");
});

test("extractHeadline: falls back to legacy hit_rate field", () => {
  // Some old reports use "hit_rate" instead of "win_hit_rate".
  const s = { player_impact: { hit_and_payout: { hit_rate: 0.4 } } };
  assert.equal(D.extractHeadline(s).hit_rate, 0.4);
});

// ---------- bucketsDiff ----------

test("bucketsDiff: handles multiplier_profile.buckets list shape (fresh_slotlab)", () => {
  // Current analyzer emits a list of {bucket, spin_rate, ...}.
  // bucketsDiff must normalise this into the same diff rows the
  // dict shape produces — otherwise compare mode silently shows
  // "no buckets" for the most common report type.
  const a = {
    player_impact: {
      multiplier_profile: {
        buckets: [
          { bucket: "eq0", spin_rate: 0.6 },
          { bucket: "ge1_lt5", spin_rate: 0.2 },
        ],
      },
    },
  };
  const b = {
    player_impact: {
      multiplier_profile: {
        buckets: [
          { bucket: "eq0", spin_rate: 0.5 },
          { bucket: "ge1000", spin_rate: 0.001 },
        ],
      },
    },
  };
  const out = D.bucketsDiff(a, b);
  assert.deepEqual(out.map((r) => r.bucket), ["eq0", "ge1_lt5", "ge1000"]);
  // Δ check on eq0: a 60% → b 50% → -10pp.
  assert.ok(Math.abs(out[0].delta_pp - (-10)) < 0.01);
});

test("bucketsDiff: union of bucket keys, canonical order first", () => {
  const a = {
    player_impact: {
      multiplier_bucket_distribution: {
        eq0: { rate: 0.6 },
        ge1_lt5: { rate: 0.2 },
      },
    },
  };
  const b = {
    player_impact: {
      multiplier_bucket_distribution: {
        eq0: { rate: 0.5 },
        ge1000: { rate: 0.001 },  // canonical-but-rare
      },
    },
  };
  const out = D.bucketsDiff(a, b);
  // Order: canonical present in either side. eq0 first, then ge1_lt5
  // (A only), then ge1000 (B only).
  assert.deepEqual(out.map((r) => r.bucket), ["eq0", "ge1_lt5", "ge1000"]);
  assert.ok(Math.abs(out[0].delta_pp - (-10)) < 0.01,
    `expected eq0 delta -10pp, got ${out[0].delta_pp}`);
});

// ---------- featuresDiff ----------

test("featuresDiff: aligns by feature name, marks only_a / only_b", () => {
  const a = {
    player_impact: {
      upstream_feature_breakdown: {
        features: { Normal: { rtp_pp: 90 }, TopDollar: { rtp_pp: 5 } },
      },
    },
  };
  const b = {
    player_impact: {
      upstream_feature_breakdown: {
        features: { Normal: { rtp_pp: 88 }, FreeSpin: { rtp_pp: 3 } },
      },
    },
  };
  const out = D.featuresDiff(a, b);
  const m = Object.fromEntries(out.map((r) => [r.name, r.presence]));
  assert.equal(m.Normal, "both");
  assert.equal(m.TopDollar, "only_a");
  assert.equal(m.FreeSpin, "only_b");
});
