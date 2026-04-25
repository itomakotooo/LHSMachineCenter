// Report compare mode — orchestrator + DOM rendering.
//
// Entry: window.COMPARE.enterCompareMode({machine, mode, version}, {...})
//   - fetches both summaries
//   - switches to the debug-machine tab
//   - paints a compare header + per-section diff blocks into the
//     debug-tab body
//
// Exit: window.COMPARE.exit() OR auto-exit on tab switch / focus
//   change.
//
// File-level IIFE; exposes only window.COMPARE (no global pollution).
//
// Pure helpers live in compare_diff.js (window.COMPARE_DIFF) so the
// math is node-testable without DOM stubs.

(function () {
"use strict";

const D = (typeof window !== "undefined" && window.COMPARE_DIFF) || {};

// ── State ─────────────────────────────────────────────────────────

let _state = null;  // { a, b, viewMode } when active; null otherwise

const VIEW_MODES = ["side", "delta", "overlay"];

// ── Formatting helpers ────────────────────────────────────────────

function _fmtNum(v, digits = 2) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

function _fmtPct(v, digits = 2) {
  const n = Number(v);
  return Number.isFinite(n) ? (n * 100).toFixed(digits) + "%" : "—";
}

function _fmtInt(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString() : "—";
}

function _fmtPp(v, digits = 2) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  const s = n.toFixed(digits);
  return n > 0 ? "+" + s + "pp" : s + "pp";
}

function _shortVer(v) {
  // "rv_20260423T112406Z_e4cc77a9" → "04-23 11:24"
  const m = String(v || "").match(/rv_(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})/);
  if (!m) return String(v || "").slice(0, 16);
  return `${m[2]}-${m[3]} ${m[4]}:${m[5]}`;
}

function _deltaCell(deltaValue, sigState) {
  // sigState: "significant" | "noise" | "unknown" — drives color/badge.
  const cls = sigState === "significant"
    ? "cmp-delta cmp-delta-strong"
    : sigState === "noise"
      ? "cmp-delta cmp-delta-noise"
      : "cmp-delta";
  return `<span class="${cls}">${deltaValue}</span>`;
}

function _sigBadge(sig) {
  if (sig === "significant") return `<span class="cmp-sig cmp-sig-strong">实质差异</span>`;
  if (sig === "noise") return `<span class="cmp-sig cmp-sig-noise">CI 内</span>`;
  return `<span class="cmp-sig cmp-sig-unknown">CI 未知</span>`;
}

// ── Compatibility banner ──────────────────────────────────────────

function _renderCompatBanner(checks) {
  const items = checks.map((c) => {
    const icon = c.level === "ok" ? "✓" : c.level === "warn" ? "⚠" : "ℹ";
    return `<div class="cmp-compat cmp-compat-${c.level}">${icon} ${c.text}</div>`;
  });
  return `<div class="cmp-compat-banner">${items.join("")}</div>`;
}

// ── Headline tiles ────────────────────────────────────────────────

function _renderHeadlineTiles(a, b) {
  const ha = D.extractHeadline(a);
  const hb = D.extractHeadline(b);
  // 5 tiles: RTP / Hit / Big-x10 / Avg win when hit / Archetype.
  const tile = (label, valA, valB, deltaText, sigState) => `
    <div class="cmp-tile">
      <div class="cmp-tile-label">${label}</div>
      <div class="cmp-tile-row"><span class="cmp-tile-tag">A</span> ${valA}</div>
      <div class="cmp-tile-row"><span class="cmp-tile-tag">B</span> ${valB}</div>
      <div class="cmp-tile-delta">${deltaText} ${_sigBadge(sigState)}</div>
    </div>`;

  // RTP — significance via CI half-widths (pp).
  const rtpDelta = hb.rtp_pct - ha.rtp_pct;
  const rtpSig = D.isSignificant(rtpDelta, ha.ci_pp, hb.ci_pp);

  // Hit rate / big-win — use a 0.5pp / 50bp default threshold since
  // these don't carry an explicit CI in the summary. We treat any
  // |Δ| > 0.5pp as significant via isSignificant's fallback path.
  const hitDelta = (hb.hit_rate - ha.hit_rate) * 100;  // pp
  const hitSig = D.isSignificant(hitDelta);

  const bigDelta = (hb.big_win_x10_rate - ha.big_win_x10_rate) * 100;
  const bigSig = D.isSignificant(bigDelta);

  const avgDelta = hb.avg_win_when_hit_x - ha.avg_win_when_hit_x;
  // avg_win_when_hit is multiplier (not pp); use the unknown-CI fallback.
  const avgSig = D.isSignificant(avgDelta);

  return `
    <div class="cmp-headline">
      ${tile("RTP",
        `${_fmtNum(ha.rtp_pct, 4)}% ±${_fmtNum(ha.ci_pp, 2)}pp`,
        `${_fmtNum(hb.rtp_pct, 4)}% ±${_fmtNum(hb.ci_pp, 2)}pp`,
        _fmtPp(rtpDelta), rtpSig)}
      ${tile("命中率",
        _fmtPct(ha.hit_rate),
        _fmtPct(hb.hit_rate),
        _fmtPp(hitDelta), hitSig)}
      ${tile("大奖 10× 比例",
        _fmtPct(ha.big_win_x10_rate),
        _fmtPct(hb.big_win_x10_rate),
        _fmtPp(bigDelta), bigSig)}
      ${tile("命中均赢 (倍率)",
        _fmtNum(ha.avg_win_when_hit_x, 2),
        _fmtNum(hb.avg_win_when_hit_x, 2),
        _deltaCell(_fmtNum(avgDelta, 2), avgSig), avgSig)}
      ${tile("体验类型 / 波动",
        `${ha.archetype || "—"} / ${ha.volatility || "—"}`,
        `${hb.archetype || "—"} / ${hb.volatility || "—"}`,
        ha.archetype === hb.archetype ? "类型一致" : "类型不同",
        ha.archetype === hb.archetype ? "noise" : "significant")}
    </div>`;
}

// ── KPI table (next-tier metrics) ─────────────────────────────────

function _renderKpiTable(a, b) {
  const ha = D.extractHeadline(a);
  const hb = D.extractHeadline(b);
  const sa = (a && a.sampling) || {};
  const sb = (b && b.sampling) || {};
  const hapA = ((a && a.player_impact) || {}).hit_and_payout || {};
  const hapB = ((b && b.player_impact) || {}).hit_and_payout || {};
  const stA = ((a && a.player_impact) || {}).streaks || {};
  const stB = ((b && b.player_impact) || {}).streaks || {};

  const rows = [
    ["总 spins", _fmtInt(ha.total_spins), _fmtInt(hb.total_spins),
     _fmtInt(hb.total_spins - ha.total_spins)],
    ["付费 / Bonus", `${_fmtInt(sa.paid_spins)} / ${_fmtInt(sa.bonus_spins)}`,
     `${_fmtInt(sb.paid_spins)} / ${_fmtInt(sb.bonus_spins)}`, ""],
    ["零赢回合率", _fmtPct(ha.zero_win_rate), _fmtPct(hb.zero_win_rate),
     _fmtPp((hb.zero_win_rate - ha.zero_win_rate) * 100)],
    ["保本以上回合率", _fmtPct(hapA.breakeven_or_more_rate), _fmtPct(hapB.breakeven_or_more_rate),
     _fmtPp(((hapB.breakeven_or_more_rate || 0) - (hapA.breakeven_or_more_rate || 0)) * 100)],
    ["大奖 100× 比例", _fmtPct(ha.big_win_x100_rate), _fmtPct(hb.big_win_x100_rate),
     _fmtPp((hb.big_win_x100_rate - ha.big_win_x100_rate) * 100)],
    ["P95 败局连", _fmtNum(stA.loss_streak_p95, 1), _fmtNum(stB.loss_streak_p95, 1),
     _fmtNum((stB.loss_streak_p95 || 0) - (stA.loss_streak_p95 || 0), 1)],
    ["最大单回合倍率", _fmtNum(stA.max_return_x, 1), _fmtNum(stB.max_return_x, 1),
     _fmtNum((stB.max_return_x || 0) - (stA.max_return_x || 0), 1)],
  ];
  return `
    <h3 class="cmp-section-title">次级指标</h3>
    <table class="drilldown-table cmp-kpi-table">
      <thead><tr><th>指标</th><th>A</th><th>B</th><th>Δ</th></tr></thead>
      <tbody>${rows.map((r) =>
        `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td></tr>`
      ).join("")}</tbody>
    </table>`;
}

// ── Bucket distribution overlay ───────────────────────────────────

function _renderBucketsCompare(a, b) {
  const rows = D.bucketsDiff(a, b);
  if (rows.length === 0) {
    return `<div class="cmp-section"><h3 class="cmp-section-title">倍率分布</h3><div class="muted">无数据</div></div>`;
  }
  // Inline overlay: for each bucket, render two stacked thin bars
  // so the operator sees A vs B side-by-side at a glance.
  const maxPct = Math.max(...rows.flatMap((r) => [r.a_pct, r.b_pct]));
  const scale = (p) => Math.max(2, (p / Math.max(0.01, maxPct)) * 280);
  const bucketHtml = rows.map((r) => `
    <div class="cmp-bucket-row">
      <div class="cmp-bucket-label">${r.bucket}</div>
      <div class="cmp-bucket-bars">
        <div class="cmp-bar cmp-bar-a" style="width:${scale(r.a_pct)}px" title="A: ${_fmtNum(r.a_pct, 2)}%">${_fmtNum(r.a_pct, 2)}%</div>
        <div class="cmp-bar cmp-bar-b" style="width:${scale(r.b_pct)}px" title="B: ${_fmtNum(r.b_pct, 2)}%">${_fmtNum(r.b_pct, 2)}%</div>
      </div>
      <div class="cmp-bucket-delta">${_fmtPp(r.delta_pp, 2)}</div>
    </div>`).join("");
  return `
    <div class="cmp-section">
      <h3 class="cmp-section-title">倍率分布 overlay</h3>
      <div class="cmp-bucket-grid">${bucketHtml}</div>
    </div>`;
}

// ── Pay ID Top 20 aligned table ───────────────────────────────────

function _renderPayoutIdsCompare(a, b) {
  const aArr = ((a && a.player_impact) || {}).payout_ids_top20 || [];
  const bArr = ((b && b.player_impact) || {}).payout_ids_top20 || [];
  const aligned = D.alignByKey(aArr, bArr, "payout_id", "total_win");
  if (aligned.length === 0) {
    return `<div class="cmp-section"><h3 class="cmp-section-title">Pay ID Top 20</h3><div class="muted">无数据</div></div>`;
  }
  // Cap at 30 so an A-only / B-only blowout doesn't make the page
  // thousands of rows.
  const capped = aligned.slice(0, 30);
  const row = (r) => {
    const ra = r.a || {};
    const rb = r.b || {};
    const pres = r.presence === "only_a" ? `<span class="cmp-only-a">仅 A</span>` :
                 r.presence === "only_b" ? `<span class="cmp-only-b">仅 B</span>` : "";
    const winA = Number(ra.total_win || 0);
    const winB = Number(rb.total_win || 0);
    const rtpA = Number(ra.rtp_contribution_pp || 0);
    const rtpB = Number(rb.rtp_contribution_pp || 0);
    const winDeltaPct = winA > 0 ? ((winB - winA) / winA) * 100 : (winB > 0 ? 100 : 0);
    return `<tr>
      <td>${r.key} ${pres}</td>
      <td>${_fmtInt(ra.hit_count)}</td><td>${_fmtInt(rb.hit_count)}</td>
      <td>${_fmtInt(winA)}</td><td>${_fmtInt(winB)}</td>
      <td>${_fmtNum(winDeltaPct, 1)}%</td>
      <td>${_fmtNum(rtpA, 2)}</td><td>${_fmtNum(rtpB, 2)}</td>
      <td>${_fmtPp(rtpB - rtpA, 2)}</td>
    </tr>`;
  };
  return `
    <div class="cmp-section">
      <h3 class="cmp-section-title">Pay ID Top 20（对齐）</h3>
      <table class="drilldown-table cmp-aligned-table">
        <thead><tr>
          <th rowspan="2">Pay ID</th>
          <th colspan="2">命中次数</th>
          <th colspan="3">Total Win</th>
          <th colspan="3">RTP 贡献(pp)</th>
        </tr><tr>
          <th>A</th><th>B</th>
          <th>A</th><th>B</th><th>Δ%</th>
          <th>A</th><th>B</th><th>Δpp</th>
        </tr></thead>
        <tbody>${capped.map(row).join("")}</tbody>
      </table>
      ${aligned.length > 30 ? `<div class="muted small">显示前 30 / ${aligned.length}</div>` : ""}
    </div>`;
}

// ── Symbol Top 20 aligned ─────────────────────────────────────────

function _renderSymbolsCompare(a, b) {
  // symbols_top20 schema in summaries we've seen is a list of {symbol,
  // count, rate, ...}. Some legacy reports may use a dict. Defensive:
  // normalise into a list before alignment.
  const _norm = (raw) => {
    if (Array.isArray(raw)) return raw;
    if (raw && typeof raw === "object") {
      return Object.entries(raw).map(([symbol, v]) => ({ symbol, ...v }));
    }
    return [];
  };
  const aArr = _norm(((a && a.player_impact) || {}).symbols_top20);
  const bArr = _norm(((b && b.player_impact) || {}).symbols_top20);
  const aligned = D.alignByKey(aArr, bArr, "symbol", "count");
  if (aligned.length === 0) return "";
  const capped = aligned.slice(0, 25);
  const row = (r) => {
    const ra = r.a || {};
    const rb = r.b || {};
    const pres = r.presence === "only_a" ? `<span class="cmp-only-a">仅 A</span>` :
                 r.presence === "only_b" ? `<span class="cmp-only-b">仅 B</span>` : "";
    return `<tr>
      <td>${r.key} ${pres}</td>
      <td>${_fmtInt(ra.count)}</td><td>${_fmtInt(rb.count)}</td>
      <td>${_fmtPct(ra.rate)}</td><td>${_fmtPct(rb.rate)}</td>
    </tr>`;
  };
  return `
    <div class="cmp-section">
      <h3 class="cmp-section-title">符号 Top 20（对齐）</h3>
      <table class="drilldown-table cmp-aligned-table">
        <thead><tr><th>符号</th><th>A 次数</th><th>B 次数</th><th>A 出现率</th><th>B 出现率</th></tr></thead>
        <tbody>${capped.map(row).join("")}</tbody>
      </table>
    </div>`;
}

// ── Feature breakdown aligned ─────────────────────────────────────

function _renderFeaturesCompare(a, b) {
  const diff = D.featuresDiff(a, b);
  if (diff.length === 0) return "";
  const row = (r) => {
    const ra = r.a || {};
    const rb = r.b || {};
    const pres = r.presence === "only_a" ? `<span class="cmp-only-a">仅 A</span>` :
                 r.presence === "only_b" ? `<span class="cmp-only-b">仅 B</span>` : "";
    return `<tr>
      <td>${r.name} ${pres}</td>
      <td>${_fmtInt(ra.total_win)}</td><td>${_fmtInt(rb.total_win)}</td>
      <td>${_fmtNum(ra.rtp_pp, 2)}</td><td>${_fmtNum(rb.rtp_pp, 2)}</td>
      <td>${_fmtPp((rb.rtp_pp || 0) - (ra.rtp_pp || 0), 2)}</td>
    </tr>`;
  };
  return `
    <div class="cmp-section">
      <h3 class="cmp-section-title">Feature breakdown（对齐）</h3>
      <table class="drilldown-table cmp-aligned-table">
        <thead><tr>
          <th>Feature</th>
          <th>A Total Win</th><th>B Total Win</th>
          <th>A RTP(pp)</th><th>B RTP(pp)</th><th>Δpp</th>
        </tr></thead>
        <tbody>${diff.map(row).join("")}</tbody>
      </table>
    </div>`;
}

// ── Bonus chain compare ───────────────────────────────────────────

function _renderBonusChainsCompare(a, b) {
  const ba = ((a && a.player_impact) || {}).bonus_chain_dynamics || {};
  const bb = ((b && b.player_impact) || {}).bonus_chain_dynamics || {};
  if (!ba.applicable && !bb.applicable) return "";
  const rows = [
    ["chain 数", ba.chain_count, bb.chain_count],
    ["bonus rounds", ba.bonus_round_count, bb.bonus_round_count],
    ["平均 chain 长度", ba.avg_chain_length, bb.avg_chain_length],
    ["自重触发率", ba.retrigger_rate, bb.retrigger_rate],
    ["max ExtraRatio", ba.max_extra_ratio, bb.max_extra_ratio],
  ];
  return `
    <div class="cmp-section">
      <h3 class="cmp-section-title">Bonus chain 动态</h3>
      <table class="drilldown-table cmp-aligned-table">
        <thead><tr><th>指标</th><th>A</th><th>B</th><th>Δ</th></tr></thead>
        <tbody>${rows.map((r) => {
          const va = Number(r[1]);
          const vb = Number(r[2]);
          const delta = (Number.isFinite(vb) && Number.isFinite(va)) ? vb - va : null;
          return `<tr>
            <td>${r[0]}</td>
            <td>${_fmtNum(r[1], 3)}</td>
            <td>${_fmtNum(r[2], 3)}</td>
            <td>${delta === null ? "—" : _fmtNum(delta, 3)}</td>
          </tr>`;
        }).join("")}</tbody>
      </table>
    </div>`;
}

// ── Bankruptcy ladder compare ─────────────────────────────────────

function _renderBankruptcyCompare(a, b) {
  const ba = ((a && a.player_impact) || {}).bankruptcy_simulation || {};
  const bb = ((b && b.player_impact) || {}).bankruptcy_simulation || {};
  const tiersA = ba.tiers || ba.results || [];
  const tiersB = bb.tiers || bb.results || [];
  if (tiersA.length === 0 && tiersB.length === 0) return "";
  const aligned = D.alignByKey(tiersA, tiersB, "multiplier", "bankruptcy_rate");
  if (aligned.length === 0) return "";
  const row = (r) => {
    const ra = r.a || {};
    const rb = r.b || {};
    return `<tr>
      <td>×${r.key}</td>
      <td>${_fmtPct(ra.bankruptcy_rate)}</td><td>${_fmtPct(rb.bankruptcy_rate)}</td>
      <td>${_fmtInt(ra.median_survival_spins)}</td><td>${_fmtInt(rb.median_survival_spins)}</td>
    </tr>`;
  };
  return `
    <div class="cmp-section">
      <h3 class="cmp-section-title">破产阶梯</h3>
      <table class="drilldown-table cmp-aligned-table">
        <thead><tr>
          <th>资金倍数</th>
          <th>A 破产率</th><th>B 破产率</th>
          <th>A 中位存活</th><th>B 中位存活</th>
        </tr></thead>
        <tbody>${aligned.map(row).join("")}</tbody>
      </table>
    </div>`;
}

// ── View-mode filter (delta-only / overlay) ───────────────────────

function _filterByViewMode(html, mode) {
  // For now the "delta" + "overlay" buttons just toggle CSS classes;
  // the underlying HTML always carries A + B + Δ. Future: hide
  // rows where Δ is zero / noise when in delta mode.
  return `<div class="cmp-body cmp-mode-${mode}">${html}</div>`;
}

// ── Compare header ────────────────────────────────────────────────

function _renderHeader(a, b, viewMode) {
  const labelA = `${a.machine || "?"} m${a.mode || "?"} · ${_shortVer((a.report_id || "").split("_").pop() || a.run_id || "")}`;
  const labelB = `${b.machine || "?"} m${b.mode || "?"} · ${_shortVer((b.report_id || "").split("_").pop() || b.run_id || "")}`;
  const modeBtn = (m, label) => {
    const active = m === viewMode ? "cmp-mode-btn-active" : "";
    return `<button class="cmp-mode-btn ${active}" data-cmp-mode="${m}">${label}</button>`;
  };
  return `
    <div class="cmp-header">
      <div class="cmp-header-title">
        <span class="cmp-header-tag">对比</span>
        <strong>${labelA}</strong>
        <span class="cmp-vs">vs</span>
        <strong>${labelB}</strong>
      </div>
      <div class="cmp-header-controls">
        ${modeBtn("side", "📊 并排")}
        ${modeBtn("delta", "Δ 差分")}
        ${modeBtn("overlay", "📈 Overlay")}
        <button class="cmp-exit-btn" id="cmpExitBtn" title="退出对比模式">✕</button>
      </div>
    </div>`;
}

// ── Public API ────────────────────────────────────────────────────

/**
 * Mount compare mode into the debug-tab body. Caller is responsible
 * for hiding any non-compare panels first (the compare body REPLACES
 * the standard debug-tab content while active).
 *
 * Idempotent: calling enter twice with the same a/b just re-paints.
 *
 * @param {Object} a - report summary A
 * @param {Object} b - report summary B
 * @param {string} viewMode - "side" | "delta" | "overlay" (default "side")
 */
function enterCompareMode(a, b, viewMode = "side") {
  if (!a || !b) return;
  if (!VIEW_MODES.includes(viewMode)) viewMode = "side";
  _state = { a, b, viewMode };

  const host = document.getElementById("cmpMount") || _ensureMount();
  const checks = D.compatibilityChecks(a, b);
  const sections = [
    _renderCompatBanner(checks),
    _renderHeadlineTiles(a, b),
    _renderKpiTable(a, b),
    _renderBucketsCompare(a, b),
    _renderPayoutIdsCompare(a, b),
    _renderSymbolsCompare(a, b),
    _renderFeaturesCompare(a, b),
    _renderBonusChainsCompare(a, b),
    _renderBankruptcyCompare(a, b),
  ].filter(Boolean).join("");

  host.innerHTML = _renderHeader(a, b, viewMode) + _filterByViewMode(sections, viewMode);
  host.classList.remove("hidden");

  // Wire mode buttons + exit.
  host.querySelectorAll(".cmp-mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      enterCompareMode(_state.a, _state.b, btn.dataset.cmpMode);
    });
  });
  const exitBtn = host.querySelector("#cmpExitBtn");
  if (exitBtn) exitBtn.addEventListener("click", exit);
}

function _ensureMount() {
  // Mount point: a div directly under the debug-tab page so the
  // compare body sits where the normal analysis blocks would.
  // The host page (index.html) provides #cmpMount; if it's missing
  // (older builds, tests), create one inside #tab-debug as fallback.
  let host = document.getElementById("cmpMount");
  if (host) return host;
  const debugTab = document.getElementById("tab-debug") || document.body;
  host = document.createElement("section");
  host.id = "cmpMount";
  host.className = "cmp-mount hidden";
  debugTab.insertBefore(host, debugTab.firstChild);
  return host;
}

/**
 * Tear down compare mode. Hides the mount, clears state. Caller
 * is responsible for restoring any panels they hid in enterCompareMode.
 */
function exit() {
  _state = null;
  const host = document.getElementById("cmpMount");
  if (host) {
    host.classList.add("hidden");
    host.innerHTML = "";
  }
  // Clear ?compare= URL param so a reload doesn't re-enter.
  try {
    const u = new URL(window.location.href);
    if (u.searchParams.has("compare")) {
      u.searchParams.delete("compare");
      window.history.replaceState({}, "", u.toString());
    }
  } catch (_) { /* IE / non-URL env, ignore */ }
  // Notify orchestrator (app.js) to re-render single-report view.
  try {
    document.dispatchEvent(new CustomEvent("compare:exit"));
  } catch (_) { /* CustomEvent unavailable, fine */ }
}

function isActive() {
  return _state !== null;
}

// ── Expose ────────────────────────────────────────────────────────

if (typeof window !== "undefined") {
  window.COMPARE = { enterCompareMode, exit, isActive };
}

})();
