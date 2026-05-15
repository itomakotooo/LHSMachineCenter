# Pipeline Map — rawdata → analyzer → backend → frontend

> Wave 1 / arch-mapper output. Pure observation of the **current state**
> of the production console pipeline (port 8877) and the virtual console
> audit (port 8878). Per `.claude/agents/arch-mapper.md`:
> concrete file:line refs throughout; no design opinions.
>
> Date: 2026-05-15
> Brief: `session_artifacts/_arch/00_brief.md`
> Repo root: `User_Managerment_GPT/`

---

## §1 Scope & entry points

### What pipeline

Upstream slot-machine simulation server → analyzer parses + classifies + aggregates
→ per-version `player_impact_summary.json` + `player_impact_report.md`
→ FastAPI backend serves report + run-mgmt + chunk-classification
→ vanilla-JS frontend renders KPI cards, drilldowns, version trees.

```
[Upstream server :15060]
  POST /MachineTest/MultiRobotTestSpinVariant
    → list[robot{analysisResult, roundResult}]
      → rawdata/<M>/mode_<N>/chunk_NNNN.json  (envelope schema v3+)
        + rawdata/<M>/mode_<N>/_chunks.json   (per-mode sidecar; chunk_index.py)
        + rawdata/_index.json                  (per-(machine,mode) summary; rawdata_index.py)
          → fresh_slotlab/player_impact_analyzer.py
              parse_chunk_response → per-chunk dict
              main() merge → summary dict
                → reports/<M>/mode_<N>/versions/rv_<ts>_<tag>/
                    player_impact_summary.json + player_impact_report.md
                  → src/web_console/backend/app.py FastAPI routes
                    GET /api/runs/{rid}/report
                    GET /api/reports/{m}/{mode}/{version}
                    GET /api/rawdata/{m}
                    POST /api/rawdata/{m}/generate-report
                      → src/web_console/frontend/{index.html, app.js, pure.js, compare_diff.js}
                        renderCatalogFeatureChips, renderRawdataReportTree,
                        _paintAnalysisFromSummary, _renderRwtreeCell
                          → browser DOM
```

### Entry points (where data first arrives in each layer)

| Entry | File | Anchor |
|---|---|---|
| Live sampling start | `src/web_console/backend/app.py` | `RunManager.start_run` `4739` (`@app.post("/api/runs")` registers it via `manager.start_run` at `6647`) |
| Live sampling subprocess | `fresh_slotlab/player_impact_analyzer.py` | `main()` `4211` → `run_sampling_chunk` `2286` → `parse_chunk_response` `2354` |
| Cache replay (resume / from-cache / generate-report) | same file | `main()` `4567-4774` (`--from-cache` / `--resume-from-cache` reader loop) |
| In-process generate-report | `src/web_console/backend/app.py` | `_run_generate_report` `6700` → in-process import of `pia.main` `6931-6932` |
| Batch generate-report | `src/web_console/backend/app.py` `7479` + worker `src/web_console/backend/_batch_gen_worker.py` `run_analyzer_job` `53` |
| Report retrieval | `src/web_console/backend/app.py` | `report_versions` `7600` (list) + `report_version_detail` `7728` (single) + `run_report` `7581` |
| Frontend boot | `src/web_console/frontend/index.html` | `<script>` tags for `pure.js`, `app.js` (loaded by `console_root` route `5383-5390`) |
| Frontend summary paint | `src/web_console/frontend/app.js` | `_paintAnalysisFromSummary` `6676` (consumes summary dict from `/api/runs/.../report`) |
| Virtual sampling (audit-only) | `slot_designer/core/backend/virtual_analyzer.py` | `main()` `690` → `_delegate_to_real_analyzer` `652` |

---

## §2 Layer-by-layer flow

### Layer 0 — Upstream contract (immutable per §7 of brief)

| File | Function | Lines | Input | Output |
|---|---|---|---|---|
| `fresh_slotlab/player_impact_analyzer.py` | `make_payload` | `1897` | machine, rtp_mode, bet, spin_times, robot_count | dict POSTed to `:15060/MachineTest/MultiRobotTestSpinVariant` |
| same | `post_json` / `post_json_with_retry` | `312`, `901` | payload + timeout | raw json response (list of robot dicts) |
| same | `_RETRYABLE_HTTP_CODES` | `330` | const `frozenset({500,502,503,504})` | retry policy gate |
| same | `_classify_failure` | `398-445` | `error_str` | `"network"` / `"machine"` |
| `fresh_slotlab/sampler.py` | `parse_robot_totals`, `extract_chunk_metrics` | `97`, `117` | analysisResult JSON | (spins, bet, win) for legacy single-machine M14 sampler (separate small CLI, not used by main analyzer) |

Endpoint constant: `DEFAULT_ENDPOINT_URL = "http://192.168.10.21:15060/MachineTest/MultiRobotTestSpinVariant"`
(`fresh_slotlab/player_impact_analyzer.py:78`).
Backend can override via `--endpoint-url` flag fed from
`src/web_console/backend/app.py:get_server_endpoint` `1331`.

Robot dict shape (consumed downstream): `{ analysisResult: str (JSON-encoded), roundResult: str (JSON-encoded list of round dicts) }`.
Round dict baseline fields enumerated in `_BASELINE_ROUND_FIELDS`
(`player_impact_analyzer.py:1444-1452`); strictly-required fields
in `_REQUIRED_ROUND_FIELDS` (`1465-1468`).

---

### Layer 1 — Chunk file persistence + index

After each successful upstream POST, the analyzer writes one envelope
per chunk to disk, then updates two index sidecars.

| File | Function | Lines | I/O |
|---|---|---|---|
| `fresh_slotlab/player_impact_analyzer.py` | `_save_chunk_cache` | `2187-2283` | writes `rawdata/<M>/mode_<N>/chunk_NNNN.json` via tmp + `os.replace`. Envelope contains `_cache_version`, `_machine`, `_mode`, `_chunk_index`, `_config_md5`, `_code_md5`, `_payload_sha256`, `_upstream_schema_fingerprint`, `response`. Hooks both index updaters at `2252-2273`. |
| same | `load_chunk_envelope` | `2037-2056` | reads file + verifies `_payload_sha256` via `_payload_sha256` `2032`; raises `ChunkIntegrityError` `2009`. |
| same | `peek_chunk_envelope` | `2083-2105` | regex-extracts `(chunk_index, config_md5, code_md5)` from first 4 KB without parsing whole file. Tightly mirrored in `fresh_slotlab/chunk_index.py:peek_chunk_envelope` `145-182`. |
| same | `_compute_upstream_schema_fingerprint` | `2108-2138` | hashes sorted key set of first round → schema fingerprint. |
| same | `compute_analyzer_version` | `2141-2160` | sha256 of analyzer module source → 12-hex-char "analyzer_version" tag stamped in summary. |
| same | `_lookup_machine_md5` | `2163-2184` | reads `configs/machines.json` for the real-console md5; returns `("","")` for virtual machines (which is why virtual analyzer patches summary post-hoc, see §4). |
| `fresh_slotlab/chunk_index.py` | `update_chunk_entry` | `422-532` | called from `_save_chunk_cache:2263`. Maintains per-mode `_chunks.json` sidecar with **two indexes**: `chunks` (filename→meta) + `by_md5` (cfg\|code → [filenames]). Thread-locked per mode_dir (`_sidecar_lock_for` `95-111`) since analyzer runs N parallel writers. |
| same | `bulk_remove_chunk_entries` | `548-617` | batched deletion path used by cleanup. |
| same | `get_chunks_index` | `407-416` | primary reader; auto-rebuilds on stale via `_is_index_stale` `360-404` + `build_chunks_index` `294-357`. |
| same | `chunks_by_md5` | `635-663` | O(1) inverted-index lookup → consumed by `select_replay_chunks_by_md5` and `_select_session_stat_chunks`. |
| same | `summarize_by_md5` | `693-716` | groups chunks → backend rwtree md5-bucket panel. |
| `fresh_slotlab/rawdata_index.py` | `update_entry` | `182-203` | called from `_save_chunk_cache:2256`. Maintains `rawdata/_index.json` (one row per (machine, mode)) so UI status refresh skips `N × envelope read`. Pre-aggregates `chunks`, `total_size_bytes`, `last_saved_at`, `config_md5`, `code_md5`, `mixed_md5`, `chunk_files`. |
| same | `_scan_mode_dir` | `104-179` | consults chunk_index sidecar first for size + md5; falls through to per-file json.loads only on sidecar miss. |
| same | `rebuild_full` | `216-241` | admin/CLI full rescan. |

Output shape — one chunk envelope (v3+):
```
{ "_cache_version": int, "_machine": str, "_mode": int, "_bet": int,
  "_spin_times": int (per-robot), "_robot_count": int,
  "_chunk_index": int, "_saved_at": iso8601,
  "_config_md5": str, "_code_md5": str,
  "_upstream_schema_fingerprint": str (16 hex),
  "_payload_sha256": str (64 hex),
  "response": [ robot, robot, ... ] }
```

Sidecar shape (`_chunks.json` v1) — see `chunk_index.py:21-46` docstring.

Memory cross-ref: `memory/feedback_md5_granularity_and_stamping.md`,
`memory/reference_chunk_index_inverted_md5.md`.

---

### Layer 2 — Per-chunk parse (pure function)

`parse_chunk_response` (`fresh_slotlab/player_impact_analyzer.py:2354-3961`)
is the canonical per-chunk worker. Pure: no network, no disk. Called both
by `run_sampling_chunk:2346-2351` (live path) and by `main()`'s
cache-read loop at `4758-4763`.

Input: raw upstream response list + chunk_index + bet + optional
`round_win_rules` list + bankruptcy params.
Output: large dict (return statement at `3961-4210`, ~245 keys)
serving as one chunk's contribution to all downstream metrics.

Inside `parse_chunk_response`, by stage:

| Stage | Function / inline block | Lines | Purpose |
|---|---|---|---|
| Shape sanity | inline | `2388-2408` | rejects non-list resp / empty / non-dict items → `response_shape_unexpected`. |
| `analysisResult` parse | inline | `2410-2479` | sums `TotalWin.WinCredits` → `upstream_chunk_total_win`. Parses `FeatureWin` → `feature_chunk_tally[name][pid] = {win, times}`. |
| Schema check | `_check_round_schema` | `1475-1494` | calls `_REQUIRED_ROUND_FIELDS` on first parsed round; returns `schema_drift_missing_fields:...` error. |
| CostCredits-reliability probe | inline | `2495-2517` | samples first 200 rounds; flips `cost_credits_unreliable` for LockReSpin-style machines (M10/M23/M131/M133). |
| Round-win extraction | calls `fresh_slotlab/round_win.py:extract_round_win` `430-448` per round | – | Default `r.get("WinCredits", 0)`; with rules: SettlementWinAmountRule `163`, SynthesizePayIdRule `230`, BCMCycleAnchorRule `345` may override. Rule list loaded by `load_rules_for_machine` `557-592` from `configs/machine_round_win_rules.json`. |
| Round-payouts extraction | `extract_round_payouts` `451-478` | – | Same rule plumbing; default is `r["PayoutIdToWinAmount"]`. |
| Trigger-anchor extraction | `extract_round_trigger_anchor` `481-521` + per-machine rules | – | Default is win==0 keys (`extract_trigger_pay_ids_default` `74`); rules may inject synthetic anchors (`_bcm_cycle` etc). |
| Trigger session detection | `fresh_slotlab/trigger_sessions.py:compute_trigger_sessions` | – called from analyzer's `parse_chunk_response` per-robot loop. Type 1 (`Trigger` ReMarks → last_non_none) + Type 2 (paid w/ win=0 anchor + empty ReMarks → sum_all w/ filter); both gated by `round_has_credited_win` `524-554`. |
| Wild-nudge detection | `fresh_slotlab/round_classification.py:is_wild_nudge_round` `138-164` | – | Tags ST=36 + ReMarks=move + cost=0 rounds; analyzer adds them to `wild_nudge_spin_types`. |
| Cycle-peak detection | `round_classification.py:detect_cycle_peak` `311-375` + `at_cycle_peak_indices` `378-391` + `infer_bcm_target_spin_type` `394-455` | – | BCM cycle peak per robot. Required observed reset; returns None when chunk too short. |
| Pay-id attribution | `round_classification.py:extract_authoritative_pay_ids` `172-189` + `parse_payline_records` `192-229` + `attribute_lines_to_pay_ids` `232-303` | – | Direct → suffix → single-remaining match resolution from `PayoutByPayline` to `PayoutIdToWinAmount`. |
| Session-level rollups | inline `_close_session` `2899-2979` + `_flush_bonus_chain` `2864-2887` | – | Builds session bucket histograms, chain summaries, big-win tiers. |
| Bankruptcy reps | `_extract_bankruptcy_reps` `1095-1138` (per-round (bet, win) tuples) — flows to chunk-level `simulate_bankruptcy_from_response` `1141-1206` OR to the streaming accumulator `_BankruptcyStreamAccumulator` `1266-1362`. | – | Streaming path is preferred (cross-chunk pooling); per-chunk is legacy/backcompat. |
| Result assembly | `return {...}` | `3961-4210` | flat dict with `ok=True`, `spins`, `bet`, `win`, `ret_*`, `*_spins`, `payline_*`, `bonus_chain_*`, `symbol_counts*`, `loss_streak_hist`, `multiplier_bucket_*`, `payout_id_*`, `spin_type_*`, `spin_type_bucket_*`, `chain_chunk_summaries`, `chain_bucket_*`, `upstream_feature_tally`, `upstream_chunk_total_win`, `cycle_peaks`, `final_cc_values`, `bankruptcy_reps`. |

Memory cross-refs: `memory/reference_round_classification_primitives.md`,
`memory/reference_round_win_rule_architecture.md`,
`memory/reference_trigger_session_patterns.md`,
`memory/feedback_invariant_with_fallback_hides_drift.md`.

---

### Layer 3 — Multi-chunk aggregation + finalize (in `main()`)

`main()` at `fresh_slotlab/player_impact_analyzer.py:4211-8159`
orchestrates both sampling and aggregation. Two execution branches:

**Branch A — Live sampling loop**
- Setup `4211-4566`: argparse, signal handlers, round_win rule load (`4275-4283`), bankruptcy multipliers (`4258-4262`).
- Live sampling loop starts after the cache reader at ~`5500+`; wraps `run_sampling_chunk` in `ThreadPoolExecutor`; AIMD tuning via `aimd_tune` `860-898`; non-convergence abort via `NON_CONVERGENCE_*` constants `373-377`.

**Branch B — Cache read (`--from-cache` / `--resume-from-cache`)**
- `4567-4774`: pre-loads chunk_index sidecar (`get_chunks_index` `4592`), pre-filters via `select_replay_chunks_by_md5` `1209-1263` (the inverted-index O(1) path), iterates, calls `parse_chunk_response` `4758-4763` per chunk.

**Both branches converge** at the merge block (`4774-5400+`) which sums every chunk's per-key tally into the `main()` scope totals (`total_spins`, `total_bet`, `total_win`, `payline_hits`, `payout_id_win`, `spin_type_bucket_*`, `bankruptcy_stream_acc.feed_reps`, `upstream_feature_tally`, etc).

**Finalize stage** runs after the loop exits (`stop_reason` set, ~`7000+`):

| Sub-step | Anchor | Notes |
|---|---|---|
| Bankruptcy histogram finalize | `bankruptcy_stream_acc.finalize` `7173` (calls `_BankruptcyStreamAccumulator.finalize` `1344-1358`) | per-tier percentiles via `compute_bankruptcy_percentiles` `1373-1412` |
| Feature → SpinType mapping | `_infer_feature_spin_type_mapping` `525-705` | 5-pass inference (unique fire-count, ReMarks substring, tied-count ordinal, ±2% tolerance, settlement-ST re-bind) |
| BCM bonus-feature resolution | `_resolve_bonus_feature` `708-768` + `collect_feature_match_warning` `771-810` + `build_cycle_observation` `813-857` | config (`configs/bcm_pairings.json` via `_load_bcm_pairings` `468-522`) → heuristic → none |
| NewFreespin / bonus-cycle RTP correction | `_compute_bonus_correction` `1811-1862` + `_compute_nf_correction` `1864-1875` | |
| Guideline check | `evaluate_guideline_comparison` `1591-1714` reads `configs/classic_slots_guideline_rules.json` (`DEFAULT_GUIDELINE_RULES_PATH` `149`) | |
| Volatility / archetype classification | `classify_volatility` `1717-1725`, `classify_experience_archetype` `1727-1742` | |
| Multiplier bucket rows | `build_multiplier_bucket_rows` `1978-2007` | uses `RETURN_BUCKET_ORDER` `94-106` + `return_bucket` `1946-1976`. Tail aggregation per `TAIL_GEX{10,20,50,100}_BUCKETS` `111-148`. |
| Summary dict assembly | inline `summary = { ... }` ending at ~`7919` | shape feeds frontend (see Layer 6) |

Output files (always pair-written):
- `<output_dir>/player_impact_summary.json` written at `7933-7934`
- `<output_dir>/player_impact_report.md` written at `8136-8137`

Where `<output_dir>` = `reports/<M>/mode_<N>/versions/rv_<ts>_<tag>/`
(constructed by backend, see Layer 4).

Lifecycle events written to JSONL progress file via `append_jsonl`
`1526-1532` — `event ∈ {started, analyzer_started, round_win_rules_active,
chunk_started, chunk_progress, target_ci_reached, cache_read_start,
cache_read_progress, cache_read_done, cache_read_target_met,
sampling_done, completed, ...}`. Same shape used by virtual_analyzer
(see §4).

Note on `fresh_slotlab/reporter.py`: this is **a legacy mini-reporter** (131 lines)
that builds a separate `report.json` + `report.md` from a single
`run_summary.json` produced by the legacy `fresh_slotlab/sampler.py`
(365 lines, single-machine M14 hardcoded). Not on the main pipeline
— backend never invokes it. Confirmed by grep: no production callers
reference `fresh_slotlab.reporter` outside the file itself.

---

### Layer 4 — Backend FastAPI service (port 8877)

App constructed by `create_app` at `src/web_console/backend/app.py:5286-5419`.
Builds `StateStore` (SQLite at `state/console/console.db`),
`RunManager` `4636`, `BatchRunManager` `3160`, `BatchGenerateManager`
`2862`, `OperationCoordinator` `4000`.
Entry point for uvicorn: `src/web_console/backend/main.py:13-15`
(`create_app()` at module level, then `uvicorn.run("...:app", port=8765)`).

#### Run lifecycle routes (sampling)

| Endpoint | File | Lines | Calls |
|---|---|---|---|
| `POST /api/runs` | `app.py` | `6633-6654` | `manager.start_run(req)` |
| `RunManager.start_run` | same | `4739-4798+` | builds analyzer argv; spawns subprocess via `self._popen_factory` (`_default_popen_factory` `4603-4617`); records pid in `process_pid` row col |
| `GET /api/runs/{rid}` | same | `6684-6686` | `store.get_run(rid)` |
| `GET /api/runs/{rid}/progress` | same | `6688-6694` | tails the run's `progress_file` JSONL |
| `GET /api/runs/{rid}/report` | same | `7580-7597` | reads `summary_file` + `report_file` from row |
| `POST /api/runs/{rid}/cancel` | same | `6696` | writes stop-flag file (analyzer's `--stop-flag-file` polling); falls back to `terminate_process_tree` `4057` |
| `DELETE /api/runs/{rid}` | same | `7564-7578` | mutex via `ops.acquire("delete_run")` → `manager.delete_run` |

`RunManager._recover_orphan_running_runs` `4686-4725` runs at create_app
time. **Critical isolation point** (see §4 audit): importing `virtual_app`
in a subprocess triggers this recovery → self-pid termination. Why
`virtual_registry.py` was carved out.

#### Generate-report (rawdata replay)

| Endpoint | File | Lines | Calls |
|---|---|---|---|
| `POST /api/rawdata/{m}/generate-report` | `app.py` | `7338-7477` | sync → `_run_generate_report` `7378`; async → spawns daemon thread `7470` |
| `_run_generate_report` | same | `6700-6999` | classify chunks via `_classify_chunks` `889-1039`; pre-load responses `6776-6789`; **in-process import + invoke** analyzer at `6867-6932` by monkey-patching `pia.post_json` `6873`, swapping `sys.argv` `6925-6926`, calling `pia.main()` `6931-6932`; restore `6933-6937`; patch empty md5 tags `6955-6973`. |
| `POST /api/rawdata/batch-generate-report` | same | `7479-7542` | `batch_gen_mgr.start(items)` (uses subprocess pool, NOT in-process monkey-patch — see worker `_batch_gen_worker.py:53-100+`) |
| `GET /api/rawdata/batch-generate-report/{bid}` | same | `7557-7562` | poll batch state |

The in-process path is single-threaded (mutex `ops.acquire`); batch
path runs `concurrent.futures.ProcessPoolExecutor` with
`_pool_worker_init` `_batch_gen_worker.py:37-50` pre-importing the
analyzer module per worker.

Both paths produce `player_impact_summary.json` + `player_impact_report.md`
in `reports/<M>/mode_<N>/versions/<report_version>/`.

#### Report retrieval routes

| Endpoint | File | Lines | Reads |
|---|---|---|---|
| `GET /api/reports/{m}/{mode}` | `app.py` | `7599-7726` | `versions/index.json` + `latest.json`; filters by `config_md5` / `code_md5` / `include_historical` query |
| `GET /api/reports/{m}/{mode}/{version}` | same | `7727-7733` | `versions/<v>/player_impact_summary.json` |
| `DELETE /api/reports/{m}/{mode}/{version}` | same | `7735-7884` | rmtree dir + drop index.json entry + rewrite latest.json |
| `POST /api/reports/import` | same | `7886+` | import external summary |
| `GET /api/report-validate/{m}` | same | `8246+` | computes md5_status (match / drift / untagged) — consumed by rwtree fresh-report logic |

#### Rawdata classification routes

| Endpoint | File | Lines | Reads |
|---|---|---|---|
| `GET /api/rawdata/{m}` | `app.py` | `5946-6024` | calls `check_rawdata_status` `655-818` per mode → consumes `rawdata/_index.json` + `_chunks.json` |
| `_classify_chunks` | same | `889-1039` | partitions chunks into kept/deletable/historical per md5 + retention quota. Critical: this is the function called by `_run_generate_report:6733` to scope what the in-process replay sees. |
| `DELETE /api/rawdata/{m}/mode/{n}/version` | same | `6042-6162` | per-version surgical delete; calls `bulk_remove_chunk_entries` `chunk_index.py:548` |
| `delete_rawdata` | same | `1040-1178` | per-mode wipe |

#### Other surfaces (peripheral but relevant)

- Static asset serve: `app.mount("/console", StaticFiles(...))` `5392`; index template substitution at `console_root` `5383-5390` (replaces `{{ASSET_HASH}}` cache-bust token).
- Disk-pressure auto-cleanup: `_auto_cleanup_for_space` `2455+`. Routes through `bulk_remove_chunk_entries` to keep sidecars consistent.
- Machines summary cache: `_build_machines_summary` `2718-2861`; pre-warmed on app start at `5332-5339`.
- Library distributions: `GET /api/library/distributions` `8543+` — frontend KPI cards consume this for cross-fleet rank.

---

### Layer 5 — Frontend asset shape

Three production files served from `src/web_console/frontend/`:

| File | Size | Role |
|---|---|---|
| `index.html` | 526 | DOM skeleton with `data-i18n` attrs + Chart.js CDN + script tags |
| `pure.js` | 2158 | Pure helpers (no DOM mutation, no fetch). Loaded first; exposed as `window.PURE`. |
| `app.js` | 7917 | All stateful UI: state, fetch wrappers, render functions, event wiring |
| `compare_diff.js` | 326 | Side panel: helpers for delta significance (Δ vs CI). Exposed as `window.COMPARE_DIFF`. |
| `styles.css` | – | (out of scope for data flow) |

Pure helpers in `pure.js`:

| Function | Lines | Consumer |
|---|---|---|
| `I18N` table | `15-948` | localization (zh/en) |
| `fmt` | `951` | format strings |
| `extractMetricCards` | `1379-1483` | maps summary→KPI tile objects (rtp/ci/spins/zeroWin/tailDep/volatility/archetype/lossStreak/maxReturn/bigWin). Read directly from `s.rtp.point_pct`, `s.sampling.achieved_halfwidth_pp`, `s.player_impact.hit_and_payout.*`, `s.guideline_assessment.derived_metrics.tail_dependency_ge*x`, `s.guideline_assessment.classification.experience_archetype`. **This is the single contract surface** between summary JSON schema and KPI rendering. |
| `formatPayoutGroupRows` / `formatSpinTypeRows` / `formatPayoutIdRows` / `formatSymbolRows` / `formatPaylineRows` | `1202-1364` | drilldown table builders |
| `extractMetricCards` consumes summary path | see above | reads ~25 dotted paths from summary |
| `freshReportsForCell` | `2092-2107` | cell-level freshness check (uses `cell.is_current`, not per-report md5_status — see `memory/feedback_fresh_report_predicate_anchor.md`) |
| `mergeTimeline` | `1907-1995` | merges progress events + clientEvents |
| `summarizeRunEvent` | `1056-1112` | progress-strip 1-line summary |

App state + render in `app.js`:

| Symbol | Lines | Role |
|---|---|---|
| `state` (global) | `9-147` | 100+ field UI state (currentRunId, machines, runs, focusedMachine, compareMode, batchGenerateId, ...) |
| `apiGet/apiPost/apiPut/apiDelete` | `345-368` | thin `fetch()` wrappers |
| `refreshCurrentRun` | `6890-7021` | the **central polling/render entrypoint**: fetches `/api/runs/{rid}`, `/api/runs/{rid}/progress`, and on completed/cancelled `/api/runs/{rid}/report`; calls `_paintAnalysisFromSummary` |
| `_paintAnalysisFromSummary` | `6676-6888` | top-level painter: KPI cards (`6679`), tail-dep grid (`6731-6762`), big-win grid (`6764-6789`), bucket table (`6805-...`), then dispatches to `renderSpinTypeBreakdown` `3940`, `renderFeatureBreakdownPanel`, `renderPaylineClassification` `4273`, `renderPayIdOverview` `4425`, `renderPayoutsBySpinType` `5026`, `renderFieldDiscovery`, `renderMachineMechanics` `4038`, `renderBonusChainDynamicsPanel`, `renderCollectCyclePanel`, `renderPaylineDrilldown` `3820`, `renderSymbolDrilldown` `3699`, `renderReelMarginalBySpinType`, `renderBankruptcyAnalysis` |
| `renderMachineCatalog` | `867-1059` | machine catalog grid (manage tab) |
| `renderRawdataReportTree` | `1701-1770` | rwtree grid for a single machine — fetches `/api/rawdata/{m}` + per-mode `/api/reports/{m}/{mode}` |
| `_renderRwtreeCell` | `1895-2140` | per-(mode, md5) cell rendering: shows kept/deletable/historical chunk counts, fresh/historical reports, action buttons |
| `_renderGenReportProgress` | `2141-2217` | in-cell live progress for active generate-report |
| `_pollGenerateReport` | `2218-2281` | per-run poll for generate-report-async path |
| `_renderPayoutRowsHtml` + `_renderReelColumnHtml` | `4747+` | shared payout / reel-column renderers used by both global and ST-split panels (extracted as shared helpers — see brief §3 commit `8411c9d`) |
| `_lineIdSignBadge` | `4968` | payline sign badge |
| `compareReports` | `3477-3504` | two-report compare entry |
| `_enterCompareMode` | `3505-3533` | compare mode painter |

Frontend → backend fetch endpoints (consumed):
- `/api/health`, `/api/machines`, `/api/versions/current`, `/api/machines/static`, `/api/machines/summary`, `/api/machines/halls`, `/api/library/distributions`, `/api/rawdata/overview`, `/api/rawdata/{m}`, `/api/disk-space`
- `/api/cache/status`, `/api/system-state`, `/api/settings`
- `/api/runs`, `/api/runs/{rid}`, `/api/runs/{rid}/progress`, `/api/runs/{rid}/report`, `/api/runs/{rid}/cancel`
- `/api/rawdata/{m}/generate-report`, `/api/rawdata/batch-generate-report`, `/api/rawdata/batch-generate-report/{bid}`
- `/api/reports/{m}/{mode}`, `/api/reports/{m}/{mode}/{version}`
- `/api/servers`, `/api/servers/{sid}/snapshot`, `/api/servers/compare`
- `/api/autotune`, `/api/autotune/progress`
- `/api/paytables/{m}/mode/{mode}/shape`, `/api/classifier/{m}`, `/api/report-validate/{m}`
- `/api/interpretations`, `/api/interpretations/{rid}`
- `/api/virtual/paytable/{m}` (probed; 404s on real console — graceful fallback)

---

### Layer 6 — Summary JSON contract (the load-bearing schema)

The shape of `player_impact_summary.json` is the **fleet-wide invariant**.
Every report on disk (~393 machines × N modes × M versions) is written
to this shape. Top-level keys produced by `main()`'s summary block
(observed in `player_impact_analyzer.py` summary-build region near
`7800-7920`):

```
{
  "report_id", "machine", "mode", "endpoint", "config_md5", "code_md5",
  "analyzer_version", "report_version",
  "sampling": { total_spins, paid_spins, chunks, target_halfwidth_pp,
                achieved_halfwidth_pp, chunk_level_halfwidth_pp,
                session_level_halfwidth_pp, stop_reason, started_at,
                finished_at, duration_seconds, chunk_rtps_pct },
  "rtp": { point_pct, ci95_interval_pct, point_frac, total_bet, total_win },
  "player_impact": {
    "volatility": { avg_return_x, std_return_x, max_observed_return_x },
    "hit_and_payout": { zero_win_rate, profit_spin_rate, big_win_x10_rate,
                        big_win_x20_rate, big_win_x50_rate, big_win_x100_rate,
                        avg_win_when_hit_x, win_hit_rate, breakeven_or_more_rate,
                        ... },
    "streaks": { loss_streak_p50, loss_streak_p90, loss_streak_p95,
                 max_loss_streak, win_streak_*, ... },
    "multiplier_profile": { buckets: [ {bucket, spin_count, spin_rate,
                                       rtp_contribution_pp, win_share,
                                       avg_return_x_in_bucket}, ... ],
                            tail_*: ..., }
  },
  "paylines": [ {payline_id, hit_count, hit_rate, approx_rtp_contribution_pp,
                 winning_symbols, winning_symbols_rln}, ... ],
  "symbols": [ {symbol, count, rate}, ... ],
  "symbol_distribution_by_col": { ... },
  "payout_groups": [ {payout_group_id, hit_count, win, ...}, ... ],
  "payout_ids": [ {payout_id, hit_count, total_win, hit_rate,
                   rtp_contribution_pp, spin_type_dominant,
                   spin_type_category, ...}, ... ],
  "payouts_by_spin_type": { "ST1_paid": [pid_row, ...], ... },         # brief §3 commit 729a6ca
  "spin_types": [ {spin_type, label, spins, bet, paid_bet, win,
                   wins, paid_rounds, ...}, ... ],
  "reel_marginal_by_spin_type": { "ST1_paid": { col_index: [...] } },  # brief §3 commit 729a6ca
  "upstream_feature_breakdown": [ {feature, payouts, resolved_spin_type, ...} ],
  "collect_mechanic": { applicable, ..., bonus_cycle_correction,
                        newfreespin_correction (alias) },
  "field_discovery": { extra_fields_seen, ... },
  "bonus_chain_dynamics": { applicable, ..., by_feature: {...} },
  "bankruptcy_simulation": { session_spins, tiers: { 100: {...}, 200: ... } },
  "machine_mechanics": { lock_lines, lock_symbols, lock_reels,
                         jackpot, free_spin, dollar_pick },
  "guideline_assessment": {
    "classification": { quality_label, volatility_class, experience_archetype },
    "derived_metrics": { tail_dependency, tail_dependency_ge20x,
                         tail_dependency_ge50x, tail_dependency_ge100x,
                         payline_top1_share, payline_top3_share,
                         blank_like_rate, ... },
    "bankruptcy_checks": { x100_bankruptcy_rate, ... },
    "alerts": [...], "action_recommendations": [...],
    "conclusion_template": { data_confidence, player_feel, rtp_structure,
                             session_risk, design_action },
  },
  "guideline_comparison": { ... external rules check },
}
```

The frontend's tight coupling to this contract surfaces most clearly in:
- `pure.js:1379-1483` `extractMetricCards` (reads ~25 paths)
- `app.js` `renderSpinTypeBreakdown` `3940-4037`
- `app.js` `renderPayIdOverview` `4425-4678`
- `app.js` `renderPayoutsBySpinType` `5026+`

Schema fallback rules for backward compat with old reports (see brief §3):
- `app.js:7e5fe32` rev — `hit_rate ?? hit_rate_pct/100` and `rtp_contribution_pp ?? rtp_pp` in `_renderPayoutRowsHtml`.
- `app.js:0f981b9` rev — derives `spin_type_category` from parent label if absent.

---

## §3 Shared vs per-X boundary table

| File / Function | Lines | Scope | Consumers |
|---|---|---|---|
| `fresh_slotlab/player_impact_analyzer.py:parse_chunk_response` | `2354-3961` | **fleet-shared** (393+ machines + virtual) | `main()` live + cache loops; called via `pia.main` in-process by backend `_run_generate_report` |
| `fresh_slotlab/player_impact_analyzer.py:main` | `4211-8159` | **fleet-shared** | spawned subprocess by `RunManager.start_run`; in-process by backend `_run_generate_report:6932`; subprocess by `_batch_gen_worker.run_analyzer_job` |
| `fresh_slotlab/round_classification.py` (all primitives) | `1-455` | **fleet-shared** | analyzer + `scripts/infer_paytable.py` + `scripts/infer_bcm_pairing.py` |
| `fresh_slotlab/round_win.py:RoundWinRule` + subclasses | `102-426` | **fleet-shared base class**; per-machine rule selection via `load_rules_for_machine` | analyzer parse loop |
| `fresh_slotlab/round_win.py:RULE_REGISTRY` | `423-427` | **fleet-shared** map of rule_type → class | `load_rules_for_machine` |
| `configs/machine_round_win_rules.json` | – | **per-machine selection** (applies_to: ["M12", "M15", ...]) | loaded by `main()` at `4275-4283` |
| `configs/bcm_pairings.json` | – | **per-machine config** | `_load_bcm_pairings` `468-522` |
| `configs/classic_slots_guideline_rules.json` | – | **fleet-shared** ruleset | `evaluate_guideline_comparison` `1591` |
| `configs/machines.json` | – | **fleet registry** (393 rows) | `_lookup_machine_md5`, `_resolve_upstream_machine_name`, machines summary, frontend catalog |
| `configs/servers.json` | – | **shared** server endpoint list | `load_servers` `362`, `get_server_endpoint` `1331` |
| `fresh_slotlab/chunk_index.py` (`update_chunk_entry`, `get_chunks_index`, `chunks_by_md5`) | `407-716` | **fleet-shared primitive**; shared verbatim between real console (`fresh_slotlab.rawdata`) and virtual console (`slot_designer.rawdata`) per module docstring `49-51` | analyzer write hooks + backend `_classify_chunks` + virtual_analyzer pre-check |
| `fresh_slotlab/rawdata_index.py` | `1-241` | **fleet-shared** | analyzer write hooks + `check_rawdata_status` |
| `fresh_slotlab/trigger_sessions.py` | `1-360` | **fleet-shared** (Type 1 + Type 2 families documented in docstring) | analyzer parse_chunk_response |
| `fresh_slotlab/sampler.py` | `1-365` | **single-machine M14 hardcoded** (`MACHINE_NAME = "M14"` `18`) — legacy CLI, not on prod path | dev-only |
| `fresh_slotlab/reporter.py` | `1-131` | **legacy single-machine** | not on prod path (no production callers; confirmed grep) |
| `fresh_slotlab/batch_dev_sampler.py` | `1-294` | dev-only | – |
| `src/web_console/backend/app.py:create_app` | `5286-5419` | **shared factory** for prod (port 8877) AND virtual (port 8878) | both `src/web_console/backend/main.py` and `slot_designer/core/backend/virtual_app.py` |
| `src/web_console/backend/app.py:_classify_chunks` | `889-1039` | **fleet-shared** | `_run_generate_report` + rawdata routes; calls `_get_machine_md5` `548` which routes through `MACHINES_CONFIG` param so virtual-console call uses `machines_virtual.json` |
| `src/web_console/backend/app.py:RunManager.start_run` | `4739` | **fleet-shared** | spawns `--analyzer` subprocess; `_analyzer` defaults to `ANALYZER` const `71` but virtual-console passes `VIRTUAL_ANALYZER` |
| `src/web_console/backend/app.py:_run_generate_report` | `6700-6999` | **fleet-shared** | in-process analyzer invocation; routes through `pia` import → real `fresh_slotlab.player_impact_analyzer` always (no virtual variant) |
| `src/web_console/backend/_batch_gen_worker.py:run_analyzer_job` | `53-100+` | **fleet-shared** | subprocess pool for batch generate-report |
| `src/web_console/backend/machine_variants.py` | `1-404` | **fleet-shared** variants resolver | machines registry processing |
| `src/web_console/backend/reports_retention.py` | `1-220` | **fleet-shared** | version retention policy |
| `src/web_console/frontend/pure.js:extractMetricCards` | `1379-1483` | **fleet-shared** schema mapping | every report regardless of machine |
| `src/web_console/frontend/app.js:_paintAnalysisFromSummary` | `6676-6888` | **fleet-shared** | every report; dispatches to per-feature renderers below |
| `app.js:renderSpinTypeBreakdown` | `3940-4037` | **fleet-shared**; iterates `s.spin_types` array generically | – |
| `app.js:renderMachineMechanics` | `4038-4129` | **fleet-shared**; uses `MECH_ICONS` const `638` map | – |
| `app.js:renderCollectCyclePanel` / `renderBonusChainDynamicsPanel` | – | **fleet-shared**; auto-hide via `applicable: false` field | – |
| `slot_designer/core/backend/virtual_app.py:_register_virtual_only_routes` | `149-173` | **virtual-only** (port 8878 only) | one route `GET /api/virtual/paytable/{m}` — explicitly scoped per docstring `152-159` |
| `slot_designer/core/backend/virtual_analyzer.py` | `1-1044` | **virtual-only analyzer** | invoked as `--analyzer` by virtual console `RunManager` (`VIRTUAL_ANALYZER` `virtual_app.py:53`) |
| `slot_designer/core/backend/virtual_registry.py` | `1-141` | **virtual-only** registry primitives | imported by virtual_app + virtual_analyzer (no-side-effects to avoid suicide bug, see `virtual_registry.py:1-23`) |
| `slot_designer/core/backend/machine_version.py` | `1-309` | **virtual-only** md5 computation (per-machine boundary per Phase B) | virtual_app + virtual_analyzer + `scripts/tune.py` |
| `slot_designer/configs/machines_virtual.json` | – | **virtual registry** (sibling to `configs/machines.json`) | virtual_app, virtual_analyzer, virtual create_app `machines_config` param |
| `slot_designer/core/version.py` | (not in this path) | brief mentions `compute_code_md5(machine_name)` — found in `machine_version.py:109-141` post-Phase-B | virtual chunk stamping |

Memory cross-ref for boundary discipline:
`memory/feedback_md5_granularity_and_stamping.md`,
`memory/project_variants_fleet.md`.

---

## §4 Reuse vs duplication audit (production vs virtual console)

**Audit target**: `slot_designer/core/backend/` per brief §2 audit-only.

### Finding: Virtual console is **a thin shell** that reuses production code via:
1. **Backend reuse** — `slot_designer/core/backend/virtual_app.py:39` imports `create_app` from `src.web_console.backend.app`; `build_virtual_app` `176-198` calls `create_app(...)` with isolated path injections. No fork of the FastAPI app, no fork of routes (with one explicit virtual-only addition).
2. **Analyzer reuse** — `slot_designer/core/backend/virtual_analyzer.py:109` defines `REAL_ANALYZER = _ROOT / "fresh_slotlab" / "player_impact_analyzer.py"`; all heavy parse/aggregate/report work is delegated via subprocess call in `_delegate_to_real_analyzer:652-687` and arg build in `_build_delegate_cmd:455-503`.

### Where they share (file:line proof)

| Shared piece | Real callsite | Virtual callsite |
|---|---|---|
| `create_app` (FastAPI factory) | `src/web_console/backend/main.py:13-15` | `slot_designer/core/backend/virtual_app.py:39, 186-197` |
| `player_impact_analyzer.main` | `RunManager.start_run` `app.py:4798` spawns subprocess; `_run_generate_report` `app.py:6931-6932` in-process | `_delegate_to_real_analyzer` `virtual_analyzer.py:667-668` → `subprocess.call(cmd, cwd=_ROOT)` with `cmd[0:2] = [python, REAL_ANALYZER]` `471-472` |
| `parse_chunk_response` | called by `main()` cache + live loops | delegated through subprocess (`--from-cache <virtual_rawdata>` `460, 479`) so the real analyzer parses virtual rawdata using the same code path |
| `chunk_index.update_chunk_entry` / `get_chunks_index` / `chunks_by_md5` | analyzer writers + backend `_classify_chunks` | virtual writers: `slot_designer/core/emitter/chunk.py:write_chunk` (chunk emitter); virtual readers: `virtual_analyzer.py:353-376` `_select_session_stat_chunks` |
| `_classify_chunks` | called by `_run_generate_report` `app.py:6733` with `mc = MACHINES_CONFIG` (real) | called by same function with `mc = VIRTUAL_MACHINES_CONFIG` (virtual) — same code path, parameterized via `create_app` `machines_config` arg `5290` |
| Frontend bundle (`index.html`, `app.js`, `pure.js`, `styles.css`) | served from `FRONTEND_DIR = src/web_console/frontend` `app.py:72` via `app.mount("/console", ...)` `app.py:5392` | identical mount (same `FRONTEND_DIR`) — virtual console serves the same JS files to its browser |
| Summary schema contract | every real report | every virtual report (real analyzer writes summary; virtual writers add md5 patch `virtual_analyzer.py:506-558` post-hoc) |

### Where they diverge (virtual-only code)

| Virtual-only piece | File | Lines | Reason |
|---|---|---|---|
| Path-injection for isolated state | `slot_designer/core/backend/virtual_app.py:46-53` | constants | `VIRTUAL_STATE_DIR / VIRTUAL_RAWDATA_ROOT / VIRTUAL_REPORTS_ROOT / VIRTUAL_CACHE_ROOT / VIRTUAL_CLASSIFY_DIR / VIRTUAL_PAYTABLES_DIR / VIRTUAL_ANALYZER` |
| Local md5 refresh handler | same `virtual_app.py` | `56-94` `_local_md5_refresh` | virtual machines have no upstream md5; recomputed locally via `refresh_machines_virtual` — passed to `create_app(md5_refresh_override=_local_md5_refresh)` `195` (real path leaves this None and uses upstream-fetched md5) |
| Virtual-only route | `virtual_app.py` | `149-173` `_register_virtual_only_routes` adds `GET /api/virtual/paytable/{m}` | architectural contract `152-159`: virtual-specific HTTP endpoints kept OUT of `src/web_console/backend/app.py` |
| Spec-load helper for virtual paytable | `virtual_app.py` | `97-146` `_load_declared_pays_from_spec` | reads virtual spec file from `machines_virtual.json` `_spec_path` field |
| Virtual analyzer entry point | `virtual_analyzer.py` | `690-1041` `main()` | sim loop produces chunks via `slot_designer.core.emitter.*` then delegates `--from-cache` to real analyzer |
| Custom-engine adapter loader | `virtual_analyzer.py` | `79-106` `_load_custom_engine_module` | per-machine plugin engines (`machines/<M>/plugins/__init__.py`) — used in sampling, not in analysis |
| Session-CI pre-check | `virtual_analyzer.py` | `262-432` `_t_critical_95`, `_ci_halfwidth_pp`, `_select_session_stat_chunks`, `_load_existing_session_stats` | early-bail if cached rawdata already meets CI target without sim. Duplicates the real analyzer's session CI formula (`player_impact_analyzer.py:1012-1034`) — both must agree byte-wise per `virtual_analyzer.py:282-283`. |
| md5 patch post-delegate | `virtual_analyzer.py` | `506-558` `_patch_summary_md5_tags` | fills virtual md5 into summary because real `_lookup_machine_md5` only reads `configs/machines.json` |
| Inference script trigger | `virtual_analyzer.py` | `561-649` `_run_inference_scripts` | mirrors `app.py:_run_post_analyzer_inference` `85-194` but fires in virtual subprocess (real path triggers from backend after generate-report; virtual sampling doesn't route through `_run_generate_report` so this had to be added — see docstring `561-583`) |
| Per-machine md5 helpers | `slot_designer/core/backend/machine_version.py` | `1-309` | virtual md5 schema differs from real (real reads upstream-stamped `configSummaryMd5`; virtual computes locally from spec + weights + plugins) |
| Virtual registry primitives (no side effects) | `slot_designer/core/backend/virtual_registry.py` | `1-141` | extracted from virtual_app because subprocess importing virtual_app triggered `app = build_virtual_app()` → `_recover_orphan_running_runs` → self-suicide. See module docstring `1-23` and `memory/feedback_subprocess_import_suicide_and_module_globals.md`. |

### Where they overlap in *function* but the code lives separately (potential duplication)

| Function | Real path | Virtual path | Comment |
|---|---|---|---|
| md5 computation for chunk stamping | `_lookup_machine_md5` `app.py:548-591` reads `configs/machines.json`; also `player_impact_analyzer.py:_lookup_machine_md5` `2163-2184` (same source) | `compute_machine_md5_for_mode` `machine_version.py:276-309`; `_compute_md5s` `virtual_analyzer.py:434-452` | Two ENTIRELY SEPARATE md5 implementations. Real reads JSON column; virtual computes via hashlib over file bytes. Same conceptual role; no shared abstraction. |
| md5 patch into summary | `_run_generate_report` `app.py:6955-6973` | `_patch_summary_md5_tags` `virtual_analyzer.py:506-558` | Same intent ("real analyzer left empty md5; patch in"). **Two implementations**; comments at both sites cross-reference each other (`app.py:6953` mentions virtual; `virtual_analyzer.py:514-522` describes the same problem). |
| Session CI half-width | `session_halfwidth_pp` `player_impact_analyzer.py:1012-1034` | `_ci_halfwidth_pp` `virtual_analyzer.py:278-291` | Same formula; virtual reimplements locally (with comment `282-283` noting the contract — "matches the formula used by the real analyzer") |
| t-critical table | `t_critical_95` `player_impact_analyzer.py:965-997` | `_T_CRITICAL_95_TABLE` + `_t_critical_95` `virtual_analyzer.py:262-275` | Two t-critical tables; smaller in virtual (sentinel 1.96 for df>30 vs analyzer's piecewise interp) |
| Inference scripts trigger | `_run_post_analyzer_inference` `app.py:85-194` | `_run_inference_scripts` `virtual_analyzer.py:561-649` | Same `paytable_shape` + `classifier` subprocess calls; different argument signatures (real takes `paytables_dir`/`classify_dir` param; virtual hardcodes the virtual paths). Diverging error reporting. |
| Chunk-write to disk | analyzer `_save_chunk_cache` `player_impact_analyzer.py:2187-2283` (writes upstream response) | `slot_designer/core/emitter/chunk.py:write_chunk` (writes simulator output) | Different writers but **share** `chunk_index.update_chunk_entry` (proven at `_save_chunk_cache:2264-2272` and confirmed by `chunk_index.py:46-51` docstring "shared verbatim between real console and virtual console") |
| Schema fingerprint | `_compute_upstream_schema_fingerprint` `player_impact_analyzer.py:2108-2138` | `compute_schema_fingerprint` / `compute_schema_fingerprint_for` in `slot_designer/core/emitter/chunk.py` + `slot_designer/core/emitter/driver.py` (imports at `virtual_analyzer.py:69-74`) | Two implementations; virtual emits its own fingerprint at sample-time, real fingerprints at cache-time |

### Summary verdict

Real + virtual share **the heavy code**: FastAPI factory (`create_app`),
the entire analyzer (`player_impact_analyzer.main` invoked via subprocess),
all of `fresh_slotlab/round_*.py` + `chunk_index.py` + `rawdata_index.py` +
`trigger_sessions.py`, the full frontend bundle. Virtual adds ~1,700
lines of glue (`virtual_app.py` 212, `virtual_analyzer.py` 1044,
`virtual_registry.py` 141, `machine_version.py` 309) covering:
sim-replaces-upstream, isolated paths, virtual md5 schema, summary
md5 patching, post-sample inference trigger, virtual-only paytable
endpoint.

There IS duplication, all concentrated in **md5 + summary-patching**:
two md5 computations, two "fill empty md5 in summary" implementations,
two session-CI formulas, two t-critical tables, two inference triggers.
These are the small-but-real forks identified by the brief §2
("verify it is a thin shell ... flag any independent parsing/display
logic as duplication-to-eliminate"). Display logic is NOT forked
(frontend bundle is single-sourced); parsing is NOT forked (real
analyzer parses both via `--from-cache`).

---

## §5 Open questions

Points where the current flow is unclear from observation alone. NOT
design proposals — only "this function does X and Y and I can't tell
which is the real path".

1. **Two routes for live sampling kick-off**: `RunManager.start_run`
   `app.py:4739` spawns `sys.executable <ANALYZER>` as a subprocess
   (used by `POST /api/runs` `6633`). Same analyzer also spawned
   inside `BatchRunManager` `3160+` via per-item subprocess. AND
   `_run_generate_report` `6700` imports the analyzer module
   in-process. Three invocation styles; all should behave identically
   per the analyzer contract — but the in-process style requires
   monkey-patching `pia.post_json` `6873`, `sys.argv` `6925-6926`,
   and `os._exit` `6874-6875` to keep the analyzer's process-suicide
   final line `8170` from killing the backend. The contract that says
   "these three behave the same" is implicit (no spec / tests
   asserting all three produce identical summaries for the same
   chunks).

2. **`_run_post_analyzer_inference` duplication across hooks**:
   triggered by `_run_generate_report` after summary write (callsite
   not shown in excerpts but consumed via `INFER_PAYTABLE_SCRIPT` +
   `VERIFY_LABELS_SCRIPT` `app.py:81-82`) AND by
   `virtual_analyzer._run_inference_scripts` `561-649` after delegate
   returns. The two paths use different signatures (real takes
   `paytables_dir` / `classify_dir` params; virtual hardcodes), so
   neither side can completely call the other. Unclear whether the
   live sampling path (`RunManager.start_run` → subprocess analyzer)
   also triggers inference — could not find an inference call in
   `_watch_run` (the post-subprocess hook in `RunManager` referenced
   by `app.py:5403` but content not in the excerpts I read).

3. **Summary md5 patch in two places**: `_run_generate_report:6955-6973`
   patches empty md5 in summary after `pia.main()`. `virtual_analyzer.
   _patch_summary_md5_tags:506-558` does the same after delegate.
   Both run on every report. Unclear what happens to the LIVE
   sampling path's summary md5 — the analyzer's own `_lookup_machine_md5`
   `2163-2184` populates it inline from `configs/machines.json` so
   no patch is needed THERE — but virtual sampling via virtual_analyzer's
   path 2 (sim then delegate) goes through `_patch_summary_md5_tags`
   at delegate return. Two separate patch sites + one in-line write
   means **three writers** all setting the same field; cannot tell
   from observation alone whether they always agree.

4. **`reporter.py` orphaned**: `fresh_slotlab/reporter.py` produces
   a different report shape (`report.json` + `report.md` with fields
   like `target_halfwidth_pp`, `achieved_halfwidth_pp`, no
   `player_impact` block) from `run_summary.json` (a separate output
   file generated only by `fresh_slotlab/sampler.py:330+` which is
   the single-machine M14 legacy CLI). I cannot locate any backend
   route or batch job that consumes `reporter.main()` or
   `run_summary.json`. Either this is dead code from before the
   `player_impact_analyzer.py` consolidation, or there's an external
   tooling path I didn't surface.

5. **`/api/virtual/paytable/{m}` 404 graceful fallback**: brief notes
   "frontend probes ... falls back gracefully when they 404". I see
   the registration at `virtual_app.py:160-173` but not the frontend's
   probe-and-fallback code. The fetch call is via `apiGet` `app.js:345`
   which throws on non-2xx — the call site must catch. Did not locate
   the specific catch.

6. **`compute_machine_md5` vs `compute_machine_md5_for_mode`**:
   `machine_version.py:251-308`. Brief §3 commit `54b7d01` mentions
   `scatter` symbol kind added to core; this would flip code_md5
   per Phase B (`machine_version.py:109-141`). The aggregate vs
   per-mode boundary is well-documented in docstring `276-301` but
   there are TWO write sites in `refresh_machines_virtual:107-135`:
   `configSummaryMd5` (aggregate) is written but also
   `modesMd5[mode].configSummaryMd5` (per-mode). The aggregate exists
   only for "did anything change?" UI signal per docstring; cannot
   tell from observation if any backend route reads it for
   correctness decisions (vs purely for display).

7. **`_classify_chunks` "kept vs deletable vs historical" semantics
   are deletion-policy-adjacent**: `_classify_chunks:889-1039` returns
   three lists; per docstring `896-922` this is "**not** a deletion
   decision — it's a tag for display + analyzer filtering". The actual
   deletion happens via `_auto_cleanup_for_space:2455+` (which I did
   not read) and per-version endpoints `6042-6162`. The kept/deletable/
   historical classification IS consumed by `_run_generate_report:6733`
   to decide which chunks the in-process replay sees. That's a
   classification-derived-from-md5 decision that drives what data
   the analyzer processes — could not verify from observation whether
   `historical` chunks ever feed an analyzer run unintentionally.

8. **Frontend version compare path**: `compareReports:3477` and
   `_enterCompareMode:3505` fetch two report summaries by version;
   the report URL pattern uses `metaA.mode` `3491` where `metaA`
   comes from the compareSelected Map `9-147`. Frontend assumes
   reports stay byte-identical for the same `(machine, mode, version)`
   tuple — but `DELETE /api/reports/.../{version}` `7735` can rmtree
   the directory underneath. Did not find a frontend cache-bust on
   selection clear; transient 404s during a delete+compare race could
   appear but the handling path is unclear.

---

End of arch-mapper output. The map above is current as of `git status`
on `collab/dev` branch (commits up to `e591bae`). Designer agents
should treat this as the structural ground truth to plan migration
against; the open questions are diagnostics for the team, not gaps
arch-mapper expects to resolve here.
