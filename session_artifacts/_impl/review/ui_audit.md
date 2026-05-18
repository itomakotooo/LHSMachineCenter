# UI Completeness Audit — internal-deploy migration

Branch `claude/keen-wu-b8b520`, HEAD `c095180`. Real Playwright (headless chromium) + uvicorn on 127.0.0.1:8879 + a separate 8880 instance against a clean state dir.

## 1. Panel inventory

27 `<section class="panel ...">` total. All match i18n keys in `pure.js` and have renderer/handler in `app.js`.

| Panel (id / class)            | HTML L | i18n key                       | Renderer / handler                                            | Status |
|-------------------------------|--------|--------------------------------|---------------------------------------------------------------|--------|
| loaded-machine                | 57     | panelLoadedMachine             | `setLoadedMachineInfo`                                        | OK     |
| interpretation                | 65     | panelInterpretation            | `refreshInterpretation`, `saveModelCfgBtn` handler            | OK     |
| kpis                          | 95     | panelKpi                       | `_paintAnalysisFromSummary` -> kpi grid                       | OK     |
| bucket-distribution           | 120    | panelBuckets                   | `renderBucketTable`                                           | OK     |
| bankruptcy-analysis (hidden)  | 145    | panelBankruptcy                | `renderBankruptcy`                                            | OK     |
| spin-types                    | 151    | panelSpinType                  | `renderSpinTypeTable`                                         | OK     |
| payid-overview x2 (hidden)    | 177,186| panelPayIdOverview / -BySpinType| `renderPayIdOverview`, `renderPayoutsBySpinType`              | OK     |
| payline-classification        | 194    | panelPaylineClassification     | `renderPaylineClassification`                                 | OK     |
| field-discovery               | 200    | panelFieldDiscovery            | `renderFieldDiscovery`                                        | OK     |
| machine-mechanics             | 215    | panelMachineMechanics          | `renderMechanics`                                             | OK     |
| bonus-chain-dynamics          | 221    | panelBonusChainDynamics        | `renderBonusChain`                                            | OK     |
| collect-cycle                 | 231    | panelCollectCycle              | `renderCollectCycle`                                          | OK     |
| paylines / symbols            | 240,257| panelPaylines / panelSymbols   | `renderPaylineDrilldown`, `renderSymbolDrilldown`             | OK     |
| reel-marginal-by-spin-type    | 278    | panelReelMarginalBySpinType    | `renderReelMarginalBySpinType`                                | OK     |
| logs                          | 287    | panelEvents                    | textContent direct write                                      | OK     |
| activity-strip                | 298    | panelActivityStrip             | `_renderActivityStrip`                                        | OK     |
| machine-catalog               | 375    | panelMachineCatalog            | `renderMachineCatalog`                                        | OK     |
| fleet-overview                | 404    | panelFleetOverview             | `renderFleetOverview`                                         | OK     |
| machine-detail                | 415    | (id only)                      | `showMachineDetail`, danger zone wiring                       | OK     |
| detail-multi                  | 459    | panelMultiSelect               | `renderMultiDetail`                                           | OK     |
| detail-rawdata                | 466    | panelRawdataGlobal             | `renderGlobalRawdata`                                         | OK     |
| system-status                 | 478    | panelSystemState               | `refreshSystemState` / `setSystemStatePanel`                  | OK     |
| server-management             | 484    | panelServerManagement          | `renderServerTable`, `addServer`, `compareServers`            | OK     |
| **config-upload (P3 NEW)**    | 518    | panelConfigUpload              | `_initConfigUploadPanel`, `renderConfigList`, `_handleConfigUpload` | OK (but see §3) |
| **fleet-refresh (P3 NEW)**    | 536    | panelFleetRefresh              | `_initFleetRefreshPanel`, `refreshFleetRefreshPanel`, `_startFleetRefresh`, `_cancelFleetRefresh` | OK (but see §3) |

All P3-new i18n keys present in both zh and en variants (`pure.js` L483-499 zh / L968-984 en). All handler-bound element IDs exist in DOM (verified via Playwright `element_presence` probe — see `audit_result.json`).

## 2. Visual audit

Screenshots written to `session_artifacts/_impl/review/`:

- `ui_audit_top.png` — top viewport, machine catalog (existing state with stale DB)
- `ui_audit_mid.png` — middle viewport, system-state + server-mgmt header
- `ui_audit_bot.png` — bottom viewport, server-mgmt + config-upload + fleet-refresh fully rendered
- `ui_audit_full.png` — full-page screenshot
- `ui_audit_fresh_bot.png` — bottom viewport on a CLEAN state DB (no stale runs)

**Per-panel rendering verdict (from DOM dimensions)**:

| Panel                | width | height | Notes |
|----------------------|-------|--------|-------|
| activity-strip       | 1412  | 62     | rendered |
| machine-catalog      | 490   | 687    | rendered |
| fleet-overview       | 910   | 220    | rendered |
| system-status        | 1412  | 118    | rendered |
| server-management    | 1412  | 345    | rendered |
| config-upload        | 1412  | 100    | rendered |
| fleet-refresh        | 1412  | 97     | rendered |

**Browser console errors** (2 total):
- `404` on `/api/runs/gen_34d9539dbc28/report` — root cause of bug #1 below.
- `404` on `/api/servers/compare?a=dev&b=test` — `test` server has no snapshot (expected, soft failure).

**Network failures**: 0 (no `requestfailed` events).

## 3. Frontend bug surface

### BUG #1 (P1 — blocking local use): Stale `currentRunId` aborts `loadBootstrap` → P3 panels stay unwired

**Reproduced**: Open console with any completed run in `console.db` whose report file is missing (e.g. operator deleted reports via UI without deleting runs). `loadBootstrap()`:
1. Calls `refreshRunList(true)` (L7297) → auto-selects first run via L6396: `state.currentRunId = state.runs[0].run_id`.
2. Then `await refreshCurrentRun()` (L7298) → run exists in DB, so the L6920 404-catch for `/api/runs/<id>` doesn't fire.
3. Reaches L7029: `const report = await apiGet('/api/runs/<id>/report')`. **No try/catch.** 404 throws.
4. Throw propagates out of `loadBootstrap()` → caught by `boot()` (L7932) → sets `setHealth(false, ...)`.
5. **L7304-7305 NEVER RUNS** — `_initConfigUploadPanel()` + `_initFleetRefreshPanel()` are skipped. The upload + fleet-refresh + start/cancel buttons have NO click listeners.

Health bar shows red "API 异常 /api/runs/gen_xxx/report: 404" but the cascading consequence (P3 panels silently dead) is invisible until the user clicks a button.

Stack trace via Playwright reproduction:
```
Error: /api/runs/gen_34d9539dbc28/report: 404
    at apiGet (app.js:358)
    at async refreshCurrentRun (app.js:7029)
    at async loadBootstrap (app.js:7298)
```

**Fix** (one line): wrap L7029 in try/catch, set `state.currentRunId=""` on 404, mirroring the L6916-6946 pattern.

Verified fix works: `probe_fresh_db.py` against a clean state-dir shows health green + all P3 buttons functional + config-upload-no-file status reads "请先选择文件" correctly.

### Silent swallows in app.js (28 `catch(_) {}` total)

Most are defensive `try { renderX() } catch(_) {}` around render calls (OK — failure of one render shouldn't stop the next). Two concerning ones:

- L7963: `refreshConfigList` catches and ignores ANY error. Comment claims "404 means virtual console" — but it also swallows 500 / network errors. Operator never sees backend failures fetching config list.
- L8014: `refreshFleetRefreshPanel`'s 404 catch is similar; comment is accurate for 404 path but blanket-catches every other error too.

Verdict: low impact for normal use. If the backend `fleet_refresh` daemon panics, the UI silently shows "Idle" instead of warning.

### `console.error` / `console.warn` (4 usages)

- L2468 `rwtree load-btn refresh failed` — warns to console only, no UI feedback.
- L3547 `compare paint failed` — error logged, but compare flow's banner shows nothing.
- L6941, L6981 — transient polling failures (OK).

### Race / setInterval audit

8 setInterval call sites. The one most prone to overlap (`state.fastTimer` at L7911, polls every 1s) has the one-shot guard via `state._autoRefreshedForRunId` at L6975 — matches `feedback_fasttimer_overlap_needs_oneshot.md` directive. Similarly `state._autoRefreshedForFleetRefreshId` (L8056) for the new P3 fleet-refresh poll.

### Missing i18n keys

None. Every `data-i18n` key in `index.html` has a corresponding entry in `pure.js`'s `I18N` table (both zh + en). The 4-state freshness banner i18n cross-check via Playwright also passes (`panelServerManagement` → "服务器管理" etc).

## 4. Panel functional check (Playwright clicks)

| Action                                                       | Network request fired              | UI feedback                                              | JS errors |
|--------------------------------------------------------------|------------------------------------|----------------------------------------------------------|-----------|
| `#refreshMd5Btn` click                                        | POST `/api/machines/refresh-md5`   | alert("刷新完成…"); MD5 catalog re-renders                | none      |
| `#configUploadBtn` click (no file, fresh DB)                  | none                               | status text "请先选择文件" appears                        | none      |
| `#configUploadBtn` click (no file, stale-runId DB)            | **none**                           | **status text stays empty** (BUG #1)                     | none      |
| `#configUploadBtn` click (invalid JSON file, stale-runId DB)  | **none**                           | **status stays empty** (BUG #1)                          | none      |
| `#configUploadBtn` click (well-formed JSON, stale-runId DB)   | **none**                           | **status stays empty** (BUG #1)                          | none      |
| `#fleetRefreshStartBtn` click (stale-runId DB)                | **none**                           | **start btn stays enabled**, no progress (BUG #1)        | none      |
| `#fleetRefreshStartBtn` click (fresh DB)                      | (would fire POST /api/fleet/refresh) — not clicked to avoid running 393-machine fleet refresh; verified status text reads "空闲" pre-click | OK | none |
| `#compareServersBtn` (a=dev,b=test)                           | GET `/api/servers/compare?a=dev&b=test` | result shows raw "/api/servers/compare?a=dev&b=test: 404" — visible but unfriendly | none |

The unhandled report-404 from boot also affects `addServer`, `compareServersBtn`, server table buttons — these handlers ARE bound earlier in `bindEvents()` (called from `boot()` BEFORE `loadBootstrap()`), so they survive. But the P3 panels were intentionally moved to AFTER bootstrap data is ready (L7303 comment), which created the dependency.

## 5. Memory feedback violations

- `feedback_fasttimer_overlap_needs_oneshot.md` — satisfied (L8056 `_autoRefreshedForFleetRefreshId`).
- `feedback_no_silent_swallow.md` — partial: L7963 / L8014 swallow non-404 errors. Low impact.
- `feedback_inference_ui_verify_panel.md` — N/A (no inference panels added in P3).
- `feedback_no_parallel_panel_impl.md` — partial: `renderConfigList` (L7939) reuses `_escHtml`, `fmt`, and the `.muted` / `.config-list-row` styling pattern. `refreshFleetRefreshPanel` (L7999) does NOT reuse the existing `sampleProgressPanel` progress-bar markup (L361-364) — it builds its own `progress-bar-wrap` / `progress-bar-inner` pair. Minor; the visual styles are consistent via `styles.css`.
- `feedback_dont_swallow_errors_in_fix.md` — BUG #1 *is* an instance: the report-fetch at L7029 has no try/catch and the swallow happens upstream in `boot()`.

## 6. Error path UI

- `stop_reason` for failed batch runs (e.g. `request_failed_http_502`) is rendered raw via `pure.js:1565 formatRunFailureNote` → no localization map. Operator sees the literal token. Visible but unfriendly.
- Failed runs DO remain in the run list (status badge + last-failure tail).
- After a failed batch-run, the next batch-run attempt works (sampleStartBtn handler not bound to state of previous batch).
- Server compare upstream-404 ("test" server has no snapshot) surfaces as `<div class="muted">/api/servers/compare?a=dev&b=test: 404</div>` — visible but not localized.
- Default-server toggle: clicking 设为默认 in server-mgmt fires PUT `/api/servers/<id>/set-default`, re-renders table with badge — verified visually in `ui_audit_bot.png` (prod is `默认`).
- `globalWarning` banner correctly shows the model API-key warning (`GEMINI API Key 为空`). No UI fragility on the `setGlobalWarning(warnings)` path.

## Overall verdict

**BUGS-FOUND** — one P1 blocker (stale `currentRunId` aborts `loadBootstrap` → P3 panels dead). Reproducible whenever the operator has a completed run in `console.db` whose report file has been deleted. This is a realistic scenario: any "清空机台所有数据" or report-cleanup operation leaves run rows in DB that point at vanished report files.

Other P3 / server-mgmt panel surface is sound:
- i18n complete (zh + en).
- All renderer / handler functions exist and are reachable.
- One-shot polling guards present.
- Visual rendering verified at 1440×900.

### Minimum-fix to ship:

1. **L7029** wrap report-fetch in try/catch matching L6916-6946 (clear `state.currentRunId` on 404, return gracefully).
2. Suggested: also `try {} finally { _initConfigUploadPanel(); _initFleetRefreshPanel(); }` block around the bulk of `loadBootstrap` body so panel-wiring survives ANY future throw. Defensive in depth.

### Nice-to-haves (not blocking):

3. `formatRunFailureNote` map `request_failed_http_*` → "上游服务返回 HTTP {code}" / "Upstream returned HTTP {code}".
4. `refreshConfigList` / `refreshFleetRefreshPanel` non-404 errors should surface to UI (status pill) rather than be swallowed.
5. Server-compare 404 ("test" has no snapshot) should show "请先扫描 <服务器名>" instead of raw URL+404.

Artifacts:
- `session_artifacts/_impl/review/audit_result.json` — full Playwright probe data.
- `session_artifacts/_impl/review/probe_*.json` — six follow-up probes that confirmed root cause.
- `session_artifacts/_impl/review/ui_audit_{top,mid,bot,full,fresh_bot}.png` — five screenshots.
