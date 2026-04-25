// Pure-logic module for report comparison: diff math, significance,
// union helpers, compatibility checks. NO DOM, NO fetch — testable
// in node via tests/frontend/.
//
// Browser: window.COMPARE_DIFF = {...}
// Node:    module.exports = {...}

(function () {
"use strict";

// ── Significance ──────────────────────────────────────────────────

/** Direction of B vs A: "up" (B>A), "down" (B<A), "eq" (equal). */
function signDelta(a, b) {
  const av = Number(a);
  const bv = Number(b);
  if (!Number.isFinite(av) || !Number.isFinite(bv)) return "eq";
  if (bv > av) return "up";
  if (bv < av) return "down";
  return "eq";
}

/** Is |Δ| larger than the combined CI half-widths?
 *  Used to flag a percentage-point delta as "real signal" vs "noise
 *  inside CI". Both half-widths in pp; missing or non-finite → fall
 *  back to a hard 0.1pp threshold so the function never throws.
 *
 *  Returns "significant" | "noise" | "unknown" so callers can
 *  render a third state when CIs aren't available. */
function isSignificant(deltaPp, halfwidthA, halfwidthB) {
  const d = Math.abs(Number(deltaPp));
  if (!Number.isFinite(d)) return "unknown";
  const ha = Number(halfwidthA);
  const hb = Number(halfwidthB);
  if (!Number.isFinite(ha) || !Number.isFinite(hb)) {
    // Conservative default — only flag really obvious diffs.
    return d > 0.5 ? "significant" : "unknown";
  }
  return d > (ha + hb) ? "significant" : "noise";
}

// ── Set / map union helpers ───────────────────────────────────────

/** Union of dict keys from two objects, preserving order:
 *  A's keys first (in their order), then B's keys not in A (in B's
 *  order). Lets the rendered table read naturally for the operator
 *  while still surfacing B-only entries.
 */
function unionKeys(objA, objB) {
  const out = [];
  const seen = new Set();
  const sa = (objA && typeof objA === "object") ? objA : {};
  const sb = (objB && typeof objB === "object") ? objB : {};
  for (const k of Object.keys(sa)) {
    if (!seen.has(k)) { seen.add(k); out.push(k); }
  }
  for (const k of Object.keys(sb)) {
    if (!seen.has(k)) { seen.add(k); out.push(k); }
  }
  return out;
}

/** Align two arrays of records by a key field (e.g. "payout_id" or
 *  "symbol"). Returns rows of {key, a, b, presence}:
 *  - presence: "both" / "only_a" / "only_b"
 *  Sorted by max(a.metric, b.metric) where metric = sortField, desc;
 *  ties broken by key string compare for determinism.
 *
 *  Used for Pay ID Top 20 / Symbols Top 20 / Feature breakdown.
 */
function alignByKey(arrA, arrB, keyField, sortField) {
  const a = Array.isArray(arrA) ? arrA : [];
  const b = Array.isArray(arrB) ? arrB : [];
  const mapA = new Map();
  const mapB = new Map();
  for (const row of a) {
    if (row && row[keyField] !== undefined) mapA.set(String(row[keyField]), row);
  }
  for (const row of b) {
    if (row && row[keyField] !== undefined) mapB.set(String(row[keyField]), row);
  }
  const allKeys = new Set([...mapA.keys(), ...mapB.keys()]);
  const out = [];
  for (const k of allKeys) {
    const ra = mapA.get(k);
    const rb = mapB.get(k);
    let presence;
    if (ra && rb) presence = "both";
    else if (ra) presence = "only_a";
    else presence = "only_b";
    out.push({ key: k, a: ra || null, b: rb || null, presence });
  }
  out.sort((x, y) => {
    const xa = Number((x.a || {})[sortField] || 0);
    const xb = Number((x.b || {})[sortField] || 0);
    const ya = Number((y.a || {})[sortField] || 0);
    const yb = Number((y.b || {})[sortField] || 0);
    const xMax = Math.max(xa, xb);
    const yMax = Math.max(ya, yb);
    if (yMax !== xMax) return yMax - xMax;
    return String(x.key).localeCompare(String(y.key));
  });
  return out;
}

// ── Compatibility checks ──────────────────────────────────────────

/** Inspect both summaries and return a list of compatibility notes:
 *    {level: "ok" | "warn" | "info", text: "..."}
 *  Caller renders these as a banner on top of the compare view.
 *
 *  Per user direction: cross-machine + cross-mode are ALLOWED without
 *  warning; only flag genuine numerical-comparability concerns
 *  (different bet, different chunk_spin_times affecting CI math,
 *  different analyzer version potentially changing bucket schemas).
 */
function compatibilityChecks(a, b) {
  const out = [];
  const sa = (a && a.sampling) || {};
  const sb = (b && b.sampling) || {};
  // Machine + mode — informational only, not warning.
  const ma = (a && a.machine) || "?";
  const mb = (b && b.machine) || "?";
  const mod_a = (a && a.mode) || "?";
  const mod_b = (b && b.mode) || "?";
  if (ma !== mb || mod_a !== mod_b) {
    out.push({
      level: "info",
      text: `跨机台/模式对比: ${ma} mode ${mod_a}  ↔  ${mb} mode ${mod_b}（指标解读自行考虑差异）`,
    });
  }
  // Bet — denominator. Different bets mean RTP comparable (ratio)
  // but absolute win amounts aren't.
  const ba = Number(sa.bet || 0);
  const bb = Number(sb.bet || 0);
  if (ba && bb && ba !== bb) {
    out.push({
      level: "warn",
      text: `不同 bet (${ba} vs ${bb}): RTP 比例可比，绝对 win 数值不可比`,
    });
  }
  // chunk_spin_times — affects CI math; not a blocker but worth noting.
  const cstA = Number(sa.chunk_spin_times || 0);
  const cstB = Number(sb.chunk_spin_times || 0);
  if (cstA && cstB && cstA !== cstB) {
    out.push({
      level: "warn",
      text: `不同 chunk_spin_times (${cstA} vs ${cstB}): CI 估计可能略偏`,
    });
  }
  // Analyzer version — schema drift indicator.
  const va = (a && a.analyzer_version) || "";
  const vb = (b && b.analyzer_version) || "";
  if (va && vb && va !== vb) {
    out.push({
      level: "warn",
      text: `不同 analyzer 版本 (${va.slice(0, 12)}… ↔ ${vb.slice(0, 12)}…): 部分字段可能仅在一边存在`,
    });
  }
  // md5 — a/b test detection, informational.
  const cfgA = (a && a.config_md5) || "";
  const cfgB = (b && b.config_md5) || "";
  if (cfgA && cfgB && cfgA !== cfgB) {
    out.push({
      level: "info",
      text: `不同 cfg md5: ${cfgA.slice(0, 16)}…  ↔  ${cfgB.slice(0, 16)}…`,
    });
  }
  // bet sample size.
  const ta = Number(sa.total_spins || 0);
  const tb = Number(sb.total_spins || 0);
  if (ta && tb) {
    const ratio = Math.max(ta, tb) / Math.max(1, Math.min(ta, tb));
    if (ratio > 5) {
      out.push({
        level: "warn",
        text: `样本量差异较大 (${ta.toLocaleString()} vs ${tb.toLocaleString()}, ${ratio.toFixed(1)}×): 小样本侧 CI 大、可比性弱`,
      });
    }
  }
  if (out.length === 0) {
    out.push({ level: "ok", text: "兼容性检查全绿" });
  }
  return out;
}

// ── Headline metric extraction ────────────────────────────────────

/** Pull the "5 headline tile" values from a summary dict. Returns
 *  { rtp_pct, ci_pp, hit_rate, big_win_x10_rate, archetype, volatility }
 *  with NaN/'' fallback when fields are missing — so a malformed /
 *  cross-version report doesn't crash the renderer.
 */
function extractHeadline(s) {
  const sampling = (s && s.sampling) || {};
  const rtp = (s && s.rtp) || {};
  const pi = (s && s.player_impact) || {};
  const hap = pi.hit_and_payout || {};
  const ga = (s && s.guideline_assessment) || {};
  const gc = ga.classification || {};
  return {
    rtp_pct: Number(rtp.point_pct),
    ci_pp: Number(sampling.achieved_halfwidth_pp),
    total_spins: Number(sampling.total_spins),
    hit_rate: Number(hap.win_hit_rate ?? hap.hit_rate),
    zero_win_rate: Number(hap.zero_win_rate),
    big_win_x10_rate: Number(hap.big_win_x10_rate),
    big_win_x100_rate: Number(hap.big_win_x100_rate),
    avg_win_when_hit_x: Number(hap.avg_win_when_hit_x),
    archetype: String(gc.experience_archetype || ""),
    volatility: String(gc.volatility_class || ""),
  };
}

// ── Bucket distribution diff ──────────────────────────────────────

/** Produce per-bucket diff rows from two reports' multiplier
 *  bucket distributions. Bucket schemas may differ across analyzer
 *  versions / machines — use union of bucket keys with 0 fill.
 *
 *  Returns [{ bucket, a_pct, b_pct, delta_pp }] in canonical bucket
 *  order if discoverable, else union-order.
 */
function bucketsDiff(a, b) {
  const _bd = (s) => {
    const pi = (s && s.player_impact) || {};
    // Schema variants seen across analyzer versions:
    //   1. ``player_impact.multiplier_profile.buckets``: list of
    //      {bucket, spin_rate, ...} — current fresh_slotlab.
    //   2. ``player_impact.multiplier_bucket_distribution``: dict
    //      keyed by bucket name → {rate, ...} — older virtual.
    //   3. ``player_impact.bucket_distribution``: same as 2 (alt name).
    //   4. ``player_impact.multiplier_profile.bucket_distribution``: dict.
    // Normalise all into a {bucket: {rate}} dict so downstream code
    // is shape-agnostic.
    const profileBuckets = pi.multiplier_profile && pi.multiplier_profile.buckets;
    if (Array.isArray(profileBuckets)) {
      const out = {};
      for (const row of profileBuckets) {
        if (row && row.bucket) out[row.bucket] = { rate: row.spin_rate };
      }
      return out;
    }
    return (
      pi.multiplier_bucket_distribution
      || pi.bucket_distribution
      || (pi.multiplier_profile && pi.multiplier_profile.bucket_distribution)
      || {}
    );
  };
  const ba = _bd(a);
  const bb = _bd(b);
  // Canonical order (matches BUCKET_ORDER in pi analyzer); fall back
  // to union order when an analyzer version reports a non-canonical key.
  const CANON = [
    "eq0", "gt0_lt1", "ge1_lt5", "ge5_lt10",
    "ge10_lt20", "ge20_lt50", "ge50_lt100",
    "ge100_lt200", "ge200_lt500", "ge500_lt1000",
    "ge1000",
  ];
  const seen = new Set();
  const ordered = [];
  for (const k of CANON) {
    if (k in ba || k in bb) { ordered.push(k); seen.add(k); }
  }
  for (const k of Object.keys(ba)) if (!seen.has(k)) { ordered.push(k); seen.add(k); }
  for (const k of Object.keys(bb)) if (!seen.has(k)) { ordered.push(k); seen.add(k); }
  return ordered.map((k) => {
    const a_pct = Number(((ba[k] || {}).rate ?? ba[k] ?? 0)) * 100;
    const b_pct = Number(((bb[k] || {}).rate ?? bb[k] ?? 0)) * 100;
    return {
      bucket: k,
      a_pct: Number.isFinite(a_pct) ? a_pct : 0,
      b_pct: Number.isFinite(b_pct) ? b_pct : 0,
      delta_pp: (Number.isFinite(b_pct) ? b_pct : 0) - (Number.isFinite(a_pct) ? a_pct : 0),
    };
  });
}

// ── Feature breakdown diff ────────────────────────────────────────

/** Both reports' upstream_feature_breakdown.features are dicts keyed
 *  by feature name. Some machines have only "Normal"; some have
 *  "TopDollarSelector" / "NewFreespin" / etc. Union the names + zero-
 *  fill for the missing side. */
function featuresDiff(a, b) {
  const _f = (s) => {
    const fb = ((s && s.player_impact) || {}).upstream_feature_breakdown || {};
    return fb.features || {};
  };
  const fa = _f(a);
  const fb = _f(b);
  const keys = unionKeys(fa, fb);
  return keys.map((name) => {
    const ra = fa[name] || null;
    const rb = fb[name] || null;
    return {
      name,
      a: ra,
      b: rb,
      presence: ra && rb ? "both" : ra ? "only_a" : "only_b",
    };
  });
}

// ── Module export ─────────────────────────────────────────────────

const API = {
  signDelta,
  isSignificant,
  unionKeys,
  alignByKey,
  compatibilityChecks,
  extractHeadline,
  bucketsDiff,
  featuresDiff,
};

if (typeof window !== "undefined") {
  window.COMPARE_DIFF = API;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = API;
}

})();
