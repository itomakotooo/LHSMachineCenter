# MEMORY

## A. USER HARD RULES (DO NOT CHANGE WITHOUT USER CONFIRMATION)

These are the project-level hard constraints from the user. They have highest priority:

1. Do not use sub-agents. Execute in the main thread only.
2. Use the provided test API. Current primary target is `M14` with `rtp mode=1`.
3. Request must include `ResetPlayerStateAfterEachSpin=true`.
4. Request must include `OutputAllRobotResult=true`.
5. RTP sampling must stop dynamically when 95% CI half-width is `<= 0.5pp`.
6. Reports must focus on player-impact metrics:
   volatility, paylines, symbol frequency, bankruptcy rate, losing/winning streaks.
7. Do not include low-value metrics like hot/cold window.
8. Raw per-spin data may be cached locally for offline re-analysis and
   report rebuild (the cache follows Rules #12-13 lifecycle). Reports
   and long-term assets persist aggregated metrics only; raw cache is
   operational, not archival.
9. `runs` is a temporary directory, not a long-term archive.
10. Memory must be split into two layers:
    `USER HARD RULES` and `ASSISTANT WORKING MEMORY`.
11. Data is managed in three logical layers:
    chunk source data, report data, aggregated metrics.
12. Chunk source data may use local cache with size limits.
13. Any chunk not yet consumed by a generated report must never be deleted.
14. Report data and aggregated metrics are core assets and must be version-managed.
15. Project should be managed in a Git repository for long-term management.
16. Report generation stays script-driven and deterministic; LLM is only for interpretation/comparison.
17. Web console model selector must be 3-way provider choice:
    `gemini`, `gpt`, `claude`, with a single API key input.
18. Cache cleanup is manual-trigger only, and UI must show clear warnings before cleanup.

Update policy:
- This section can only be changed when user explicitly says to add/remove/modify a hard rule.

## B. ASSISTANT WORKING MEMORY (ADJUSTABLE)

This section is for execution efficiency and can be updated as long as section A is respected:

1. Recommended directory split:
   - temp artifacts: `fresh_slotlab/runs/`
   - long-term reports: `reports/<machine>/mode_<id>/index.json`,
     `latest.json`, and `versions/<report_version>/...`
2. Practical sampling starting point:
   `chunk_spin_times=5000`, `robot_count=20`, `batch_concurrency=2`,
   then tune by measured throughput and stability.
3. Preferred report narration order:
   player experience conclusion -> statistical evidence -> risk and action notes.
4. On any failure (API/script/path pollution):
   stop first, preserve reproducibility, then provide exact recovery steps.
5. Suggested cache eviction policy:
   delete only `RELEASED` chunks, never `LOCKED` or `PENDING_REPORT`.
6. Suggested cache capacity control:
   use high/low watermarks (for example 80%/65%) for cleanup.
7. Suggested Git tracking boundary:
   track code/config/reports manifests; ignore cache and transient runtime state.
8. Repository status:
   Git repository initialized at project root on 2026-04-14.
9. Report default:
   include multiplier buckets with tail contribution metrics by default,
   even if user does not explicitly ask in each run.
10. Report default:
   include `guideline_assessment` with quality gate, classification,
   alert rules, and filled conclusion template.
11. Console status:
   local web console MVP is available at `/console` via FastAPI backend,
   started by `scripts/start_console.ps1`.
12. Model-routing status:
   backend runtime model config supports provider switch
   (`gemini`/`gpt`/`claude`) and single-key update API.
13. Safety default:
   never persist user API keys into repository files or reports.
14. Console UX default:
   all critical run/model parameters should expose field-level tooltip hints
   (CN/EN synchronized with language switch).
14a. Machine catalog (configs/machines.json) currently lists:
   - M14 (modes 1, 2, 5, 7): classic 3-col slot, SpinType=1 only,
     no collect mechanic.
   - M272 (modes 1, 2, 5, 7): collect/bonus mechanic, SpinType=140
     (main) + 126 (bonus/re-spin); 3 cols of stopped symbols (dash
     separated, trailing dash); round count exceeds SpinTimes due
     to bonus triggers (~10-30% on mode 1, ~36% on mode 2);
     PayoutByPayline uses a richer "id:mult-count(positions);"
     format that parse_paylines still reduces to id correctly.
     CollectCount + AccCredits + CreditsSymbols carry the collect
     mechanic state that summary.collect_mechanic exposes.
   When adding a new machine, probe it via curl to MultiRobotTestSpin
   first; any envelope that's not [{roundResult, ...}, ...] will
   be caught by Layer 1 of the schema check (see #24a) -- update
   that path or wrap as needed before adding to machines.json.
   Both M14 and M272 winning rounds populate PayoutIdToWinAmount
   (the Pay ID drilldown source) and analysisResult.TotalWin (the
   sanity-check source); test before assuming a new machine does.
15. Cache safety default:
   cache cleanup follows risk-tier confirmation:
   low risk = one confirm; medium/high risk = confirm + `DELETE` token.
16. Restart robustness default:
   startup recovery must auto-fail stale `running` tasks and attempt stale
   worker termination via persisted `process_pid`, then expose recovery snapshot in API.
17. Run config workflow:
   - mode 2 and 5 must use fuzzy target (target_halfwidth_pp=0 -> backend
     recomputes max_chunks so sampling targets ~1M spins; analyzer receives
     halfwidth=999 so the CI-stop branch never fires);
   - mode 1 and 7 support 0.5 / 1 / 2 / 5 pp or fuzzy;
   - chunk_robot_count / batch_concurrency are editable inputs with
     preset defaults (robot=24, conc=2; validated against M272 mode 1
     via run_auto_tune probe -- that combo achieved 100% success rate
     at throughput=922 spins/s p95=8.1s, the best stable point below
     the higher-p95 conc=4 tail);
   - Auto Tune button remains available to refine per machine; on
     machine / mode change the two inputs reset back to preset so the
     screen always carries sensible defaults;
   - advanced params default to chunk_spin_times=5000 /
     max_chunks=60 / timeout=120 (previously 120 / 300; tightened
     after the autotune probe showed M272 mode 1 achieves CI target
     in well under 60 chunks at the preset concurrency, and per-chunk
     latency p95=10s leaves ample margin within timeout=120).
18. Bankroll multiplier presets:
   UI exposes three fixed presets (Standard 100/200/500, Short 50/100/200,
   Long 200/500/1000). Non-Standard presets bypass the x100/x200/x500
   guideline-rule thresholds until rules.json becomes dynamic; tooltip
   must surface that caveat.
19. Progress feedback channels (always HTTP polling, 1 Hz, snapshot dicts):
   - Per-run events: GET /api/runs/{run_id}/progress (jsonl replay).
     Frontend fast timer activates only while currentRunStatus === "running".
     Live status line via pure.summarizeRunEvent; progress bar via
     pure.computeRunProgressPct.
   - Autotune: GET /api/autotune/progress reads app.state.autotune_progress
     under app.state.autotune_progress_lock. Mutated by the progress
     callback that create_app() injects into run_auto_tune; phases are
     start / candidate / finish (with finish always running in finally).
   - Global warning bar reserved for system + model notices. Per-run
     failure detail lives inside the runMeta panel; backend always
     persists a structured error_message that includes exit_code +
     missing artefacts.
19b. Paid-session refactor (M272 collect-mechanic insight + RTP fix):
   - "Paid session" = paid spin (CostCredits > 0) + any bonus /
     free-spins it triggers, until the next paid spin or end of
     robot's rounds. Legacy machines without CostCredits default
     to is_paid=True (every round = its own session).
   - hit_and_payout, multiplier_profile.buckets, streaks, and
     volatility all derive from session-level counters now. Bonus
     wins attribute to the session that triggered them; bonus rounds
     don't dilute hit_rate / zero_win_rate.
   - rtp.point_pct uses session_bet_sum (paid bet only) -- the old
     total_bet also added BetAmount for bonus spins, which the player
     doesn't pay; on bonus-heavy machines (M272 mode 2: 46% bonus
     rounds) this had been under-reporting RTP by ~2x (286% vs 563%
     true).
   - sampling.paid_spins + sampling.bonus_spins added so the
     paid/bonus split is visible. total_spins still records the
     round-count for sample-size gates.
   - collect_mechanic.clamp_warning flags chunks where SpinTimes
     ran out mid-collect-cycle (paid spins accumulated past the
     last collect trigger but the next one didn't fire). Reports
     raw signals (pending_robots, total_pending_paid_spins,
     pending_share_of_paid_spins, avg_paid_spins_per_collect) +
     a note string; deliberately does NOT fabricate an
     "estimated lost RTP pp" because per-collect bonus payout
     varies too much per machine for a heuristic to be honest.
     Frontend renders the warning via #rtpClampWarning when
     clamp_warning.applicable=true.
   - main() force-exits via os._exit(rc) after stdout/stderr flush
     so any worker thread stuck in a slow socket read can't keep
     the process alive past main return (defensive after observing
     orphaned analyzer processes from upstream-trickle scenarios).
19a. Round-level surfaces in summary.player_impact (added after the
   M14+M272 field investigation):
   - payout_ids_top20: PayoutIdToWinAmount aggregated as
     {payout_id, hit_count, hit_rate, total_win, avg_win_when_hit,
     rtp_contribution_pp}. Replaces payout_groups_top20 in the UI
     (which was always group 0); old field still emitted for
     back-compat.
   - spin_type_breakdown: per-SpinType {spins, share_pct,
     win_rounds, hit_rate, total_bet, total_win, rtp_pct,
     rtp_contribution_pp}. Sorted by spins desc. Surfaces M272
     mode 2's ~36% bonus contribution that aggregate RTP hides.
   - paylines_top20[].top_symbols: per-payline winning-symbol
     inference via leftmost-3-col intersection + blank filter.
   Plus two cross-cutting blocks at summary top-level:
   - upstream_analysis: server-side analysisResult.TotalWin
     cross-check ({server_total_win, our_total_win, delta,
     delta_pct, matches, server_robots_seen}). matches=true with
     delta=0 confirms we agree with the upstream; future drift
     surfaces here before bad data leaks into the report.
   - collect_mechanic: M272+ collect tally ({applicable,
     robots_with_data, total_collects, max_acc_credits_observed,
     avg_spins_between_collects}). M14 reports applicable=false.
   The interpretation prompt subset
   (backend/app.py build_interpretation_prompt) now carries all
   four so the LLM sees Pay-ID hotspots, bonus contribution,
   server sanity, and collect mechanic together with the
   reference thresholds (#24).
20. Player-impact drilldown surface:
   - summary.player_impact.paylines_top20 (existing): payline_id /
     hit_count / hit_rate / approx_rtp_contribution_pp / win_share /
     top_symbols / top_symbols_source ("rln" when RewardLastNode was
     present on the winning spins, "heuristic" when it fell back to
     the left-3-col intersection).
   - summary.player_impact.symbols_top20 + symbols_by_column_top10
     (existing): overall + per-column symbol frequency.
   - summary.player_impact.payout_ids_top20 (primary PayoutId
     drilldown, from PayoutIdToWinAmount): {payout_id, hit_count,
     hit_rate, total_win, avg_win_when_hit, rtp_contribution_pp}.
     Replaces payout_groups_top20 in the UI (still emitted for back-
     compat; M14 + M272 mode 1/2 always reported group 0).
   - Rendered as stacked panels (NOT tabs -- the drilldown-tabs
     component was unrolled in the dashboard follow-up round because
     tabs added friction for text/table content): #paylineTable,
     #payoutGroupTable (reads payout_ids_top20 despite the legacy id),
     #symbolOverallTable + #symbolByColMatrix.
21. UI layout convention (Grafana-style dashboard, debug tab):
   - Three-region shell: sticky .dash-topbar (title / liveStatusStrip /
     lang+health), .dash-sidebar (run-actions + run-config + model-
     config in that DOM order so Start/Auto are above the fold, 260px
     column on desktop, drawer toggled by #sidebarToggle below 1120px),
     .dash-main (KPI 3x4 strip with whole-card pastel tone bg + single
     bucket chart + 3 stacked mid panels (interpretation, assessment,
     events) + 3 stacked drilldown panels (paylines, payout-groups,
     symbols)).
   - Why: tabs were unrolled per user feedback after first dashboard
     pass -- friction without payoff for narrative + table content.
     CI / RTP / bankruptcy charts dropped because their values already
     live in KPI cards.
   - All e2e selectors (#startBtn / #autotuneBtn / #ciSelect /
     #robotInput / #paylineTable / #payoutGroupTable /
     #symbolOverallTable / #symbolByColMatrix / 12 KPI strong IDs /
     #liveStatusStrip / #sidebarToggle / #bucketChart) preserved across
     the refactor; IDs never queried by structural class.
   - Manage tab (#tab-manage) deliberately retains its single-column
     panel stack so the cache-cleanup risk-tier e2e fixtures targeting
     #cacheRefreshBtn / #cacheCleanupBtn keep working unchanged.
   - Pure helpers untouched -- only added i18n keys (sidebarToggleLabel
     / thTopSymbols) and small formatting helpers (prettyBucketLabel,
     formatPaylineTopSymbols). No business signature changes.
   - Dark-mode palette prepared as :root[data-theme="dark"] vars; not
     activated. Setting <html data-theme="dark"> would flip the theme
     without further CSS edits.
22. Multiplier bucket schema (analyzer + frontend chart):
   - 11 win-bearing bins: gt0_lt1 / ge1_lt5 / ge5_lt10 / ge10_lt20 /
     ge20_lt50 / ge50_lt100 / ge100_lt200 / ge200_lt500 / ge500_lt1000
     / ge1000_lt5000 / ge5000. No `eq0` row -- zero-win sessions are
     tracked via hit_and_payout.zero_win_rate; a bucket where
     avg_return_x / rtp_contribution_pp / win_share are structurally
     0 is noise on the multiplier chart. return_bucket() returns ""
     for zero-win and the accumulators skip empty keys, so the
     summary never emits an eq0 entry (dropped in commit 1c17b34).
   - Path from 10 -> 12 -> 11: the 10-bin schema was first refined to
     12 (dashboard follow-up: low buckets collapsed, deep tail split)
     then `eq0` was dropped.
   - TAIL_GEX10_BUCKETS / TAIL_GEX20_BUCKETS / TAIL_GEX50_BUCKETS /
     TAIL_GEX100_BUCKETS each include all bins at/above their
     threshold so tail_dependency_ge{10x,20x,50x,100x} can emit a
     4-point curve (see #25).
   - Old reports keep their old labels in summary JSON;
     PURE.prettyBucketLabel falls back gracefully for legacy keys
     (including `eq0`) so pre-drop charts still render.
23. Payline winning-symbol inference (analyzer):
   - API exposes PayoutByPayline (winning line ids) and
     StopSymbolsByCol (5 columns of stopped symbols) per spin, but no
     payline -> position map (machines.json doesn't carry payline
     definitions either).
   - Heuristic: when a line pays, intersect the leftmost-3 column
     symbol sets and credit the result(s) as the winning symbol(s)
     for that line. Matches the classic 3+ left-to-right slot pattern.
     Falls back to the leftmost column's first symbol when no
     intersection (rare bonus payouts).
   - Output: each row in summary.player_impact.paylines_top20 carries
     top_symbols [{symbol, count}, ...] (top 5 by frequency). Frontend
     paylines table renders top 3 via PURE.formatPaylineTopSymbols.
24a. Upstream API shape + schema drift defense:
   - Two layers in run_sampling_chunk; both surface as structured
     error strings in the chunk record's "error" field which the
     main loop converts to a "failed" event reason and _watch_run
     puts into error_message.
   - Layer 1: top-level shape ("response_shape_unexpected:..."):
     catches dict-envelope-instead-of-list, non-list/non-dict types,
     and lists where no item is a robot dict. Echoes the offending
     keys / types so the operator can ask for the new shape to be
     supported.
   - Layer 2: round-level schema ("schema_drift_missing_fields:..."):
     _REQUIRED_ROUND_FIELDS = (WinCredits, StopSymbolsByCol). These
     are the only fields that should appear on EVERY spin regardless
     of win/lose state. PayoutByPayline / PayoutGroupId are NOT
     strict-checked because lose / no-payout spins legitimately omit
     them (the very first spin of most chunks is statistically a lose
     spin, so strict-checking them aborted every run -- learned the
     hard way during the dashboard follow-up round).
   - BetAmount uses a union check ("BetAmount|CostCredits" -- at
     least one must exist) since CostCredits is the documented fallback.
   - On drift, run_sampling_chunk returns
     "schema_drift_missing_fields:..." and the main loop aborts the
     run; _watch_run surfaces the missing fields in error_message.
   - tests/backend/test_analyzer_parsing.py (70 cases) monkey-patches
     post_json to feed crafted round shapes through run_sampling_chunk,
     locking: schema check (positive + negative cases including the
     lose-spin-first regression), 11-bin bucket classification (eq0
     dropped, see #22), payline winning-symbol heuristic (left-3 col
     intersection + blank filter + fallback), payout group
     aggregation (numeric + string + garbage ids), CostCredits
     fallback when BetAmount is absent.
24b. Zero-spin run guard (backend _watch_run):
   - The analyzer's main loop breaks on the first failed chunk and
     writes an empty summary with sampling.total_spins=0 plus
     sampling.stop_reason recording the cause (e.g. request_failed_
     http_504 from an upstream gateway timeout). exit_code is 0 and
     both summary+report files exist, so the watcher would call that
     "completed" -- presenting the operator with a green run that has
     zero data and no error message.
   - The watcher now reads sampling.total_spins on success and, if 0,
     promotes the run to "failed" with error_message of the form
     "sampling produced 0 spins after N chunk(s); stop_reason=...".
     The empty report is also kept out of the report index / latest.json
     so manage-tab navigation isn't polluted.
   - Locked by tests/backend/test_run_lifecycle.py (11 cases cover
     happy-path + zero-spin guard + delete cascade + cancel graceful
     + backfill; see #24d / #26 / #27 for the newer cases added since
     the zero-spin guard first landed).
24d. Manage-tab run-history surface:
   - runs table columns: Run ID / Status / Machine / Mode / Created At
     / RTP / CI\u00b1 / Action(Load+Delete). RTP and CI come from two
     new DB columns `achieved_rtp_pct` and `achieved_halfwidth_pp`
     populated by _update_report_index() when a run completes; legacy
     rows migrated via ALTER TABLE stay NULL and render as "\u2014".
   - DELETE /api/runs/{id} removes the DB row + interpretations cascade
     + per-run progress/summary/report files + the report version
     directory under reports/<machine>/mode_<n>/versions/<rv>/, and
     filters the entry from index.json; latest.json rolls back to the
     newest remaining version (or is removed if the last was dropped).
     Protected server-side: 409 if the row's status is "running" (both
     via DB status check and the in-memory _running dict). Protected
     by tests/backend/test_run_lifecycle.py::
     test_delete_run_removes_row_and_report_artefacts / _rolls_back_
     latest_to_previous_version / _refuses_running / _not_found.
   - Frontend state.runFilterMachine drives a clickable machine catalog
     panel: each .catalog-item carries role=button + keyboard focus;
     click toggles filter and re-renders the history table. When a
     filter is active, #runFilterBanner shows the active machine + a
     clear button. Clear also triggers by clicking the active catalog
     row a second time.
24c. Autotune wall-time optimization:
   - Default candidate grid compacted from 5x4=20 to 3x3=9 ({8,16,24}
     x {1,2,4}). Frontend defaults match.
   - Per-robot early exit in run_auto_tune: once a (robot, conc)
     candidate's success_rate < 0.7, every subsequent (robot, conc)
     pair with the same robot is skipped (more parallel load on an
     already-stressed worker pool will only fail harder). Skip events
     are still emitted via progress_callback with skipped=True so the
     operator sees why the sweep finished early.
   - Default rounds dropped from 2 to 1 in the frontend payload (less
     averaging, but shaves ~50% of remote requests).
   - Combined effect: autotune typically completes in well under half
     the previous wall time without losing the low/mid/high coverage.
   - Locked by tests/backend/test_autotune_progress.py: default grid
     is 3x3, healthy run produces all 9, saturation at lowest conc
     skips higher conc for that robot, partial saturation only affects
     the offending robot.
24. Interpretation prompt contract (backend build_interpretation_prompt):
   - Subset includes paylines_top20 / payout_groups_top20 /
     symbols_top20 / symbols_by_column_top10 alongside the existing
     aggregate fields so the LLM can comment on hotspots.
   - Reference block precedes the JSON payload listing the exact
     thresholds analyzer uses (volatility tiers, archetype rules,
     sampling quality bar, loss-streak / bankruptcy / tail-dependency
     alerts). Output prompt requires citation of these numbers.
   - Output structure: 6 sections, including "4) 支付线与符号热点"
     (must reference drilldown data) and "5) 关键风险与告警" (must
     reference threshold numbers). Locked by
     tests/backend/test_interpret_prompt.py.

25. Round-level surfaces mined from the upstream field audit
    (commits c3e7096 analyzer + 94dae2f frontend):
   - Multi-threshold tail_dependency: guideline_assessment.
     derived_metrics now emits tail_dependency_ge{10x,20x,50x,100x}
     and matching tail_rtp_contribution_pp_ge{10x,20x,50x,100x}.
     ge10x is the canonical input to classify_volatility /
     classify_experience_archetype (back-compat alias
     `tail_dependency` preserved). The 4-point curve exposes how
     fast the tail mass decays -- slow decay = Boom-Bust with deep
     bursts, sharp decay = grindy. KPI `kpiTail` primary shows
     ge10x; `#kpiTailSub` renders the ≥20x/50x/100x breakdown.
   - player_impact.upstream_feature_breakdown (from
     analysisResult.FeatureWin): server-authoritative grouping by
     feature NAME string ("Normal" / "NormalCollectionSpin" /
     "NewFreespin" on M272 mode 1). Each feature lists
     total_win, total_times, rtp_contribution_pp,
     share_of_total_win, per-payout_id payouts[] with
     share_of_feature_win. Single-feature machines (M14: "Normal"
     only) emit applicable=false; frontend panel hides.
   - player_impact.bonus_chain_dynamics (from round ReMarks
     "Freespin N; CollectCount:X; ExtraRatio:R; [AddFreespins; M]"):
     per-chain length + peak ExtraRatio quantiles (p50/p90/p95/max),
     self_retrigger_round_rate, avg_retriggers_per_chain,
     extra_ratio_histogram, extra_ratio_by_chain_depth (depth
     buckets 1 / 2-5 / 6-10 / 11-20 / 21+ → avg ratio — the
     MapCollection energy-ramp curve). M272 mode 1 smoke: avg chain
     length 16.1, peak ratio 800x, 32.5% self-retrigger, ratio
     ramps 122 -> 175 -> 263 -> 366 -> 528 across depth buckets.
     M14 (no Freespin annotations) emits applicable=false.
   - paylines_top20[].top_symbols now prefers RewardLastNode (RLN)
     numeric symbol codes (upstream-authoritative) and falls back to
     the left-3-col heuristic. top_symbols_source flag tells the UI
     which path fired.
   - SpinType breakdown fix: per-type RTP now uses spin_type_paid_bet
     (CostCredits>0 rounds) as denominator; rtp_pct is null for
     all-free types (avoided 243% nonsense on M272 SpinType=126 that
     earlier path emitted). behavior_name ("paid"/"free"/"mixed") is
     derived from per-type paid_rounds count so UI can badge the row
     without hardcoding machine-specific int semantics.
   - Reference: reports/M14/mode_1/versions/rv_20260415T100548Z_*
     (pre-migration) vs reports/M272/mode_1/versions/rv_20260415T113518Z_*
     (post-migration) as shape diff examples.
   - Docs: reference_upstream_unmined_fields memory lists 7 fields
     still unmined (CreditsSymbols / CurJackpotStoreWin /
     PayLineGroupId / ReelSkin / SymbolIndexToRewards / LastCredits
     / SummaryWin) to revisit when a new machine lands.

26. Manage-tab (current state):
   - Run History table: 9 columns — checkbox / Run ID / Status /
     Machine / Mode / RTP / CI± / Quality / Action (Load + Rebuild
     + Delete). Report Versions panel removed; merged into run row.
   - Batch operations: select-all checkbox in header; batch action
     bar appears when ≥1 row checked with "删除选中 (N)" button.
   - Rebuild per-row: async-checks GET /api/runs/{id}/chunks; shows
     "N chunks ✓" when compatible, "N chunks ✗ 失效" when schema
     drifted (button disabled + line-through style). POST rebuild
     pre-checks compatibility → 409 if stale.
   - Machine catalog: multi-select (Set<string>). Each catalog item
     toggles independently. Empty set = show all. Filter banner
     shows "M14 + M272" when both selected.
   - DB columns achieved_rtp_pct / achieved_halfwidth_pp /
     quality_label added via ALTER TABLE migrations; populated on
     run completion in _update_report_index. StateStore.backfill_rtp_
     ci_from_summaries() runs on every create_app() startup to fill
     legacy rows (status IN completed/cancelled, any of the three
     fields NULL) by re-reading summary.json. Test coverage:
     test_backfill_rtp_ci_from_summaries.
   - Machine-catalog click-to-filter: .catalog-item is role=button
     keyboard-activatable; click toggles state.runFilterMachine;
     #runFilterBanner appears above the table with a clear button.
     Active row gets .active class. Click active again or clear
     button to reset.

27. Graceful Stop + cancelled status (commit 1714b93):
   - Analyzer accepts --stop-flag-file PATH. Between-chunks loop
     polls the file's existence (cross-platform; Windows
     subprocess.terminate()==TerminateProcess doesn't deliver a
     catchable signal). Also registers SIGTERM/SIGINT handlers
     where catchable. On stop: breaks out of loop with
     stop_reason="user_stop", builds summary with whatever chunks
     completed, exits 0.
   - cancel_run writes the flag file to progress_dir/{run_id}.stop
     instead of calling process.terminate(); response status is
     "cancelling". Falls back to hard terminate() only if the flag
     write fails.
   - _watch_run promotes exit-0 + user_stop + total_spins>0 runs
     to status "cancelled" (NOT failed) and writes the report
     index/latest like completed. zero-spin + user_stop -> still
     cancelled (user intent) with error_message noting "cancelled
     by user". Non-user zero-spin -> existing failed path
     (504 / network etc).
   - Frontend: refreshCurrentRun renders full panel stack for
     status==completed OR cancelled. interpretBtn enables for
     cancelled too (LLM can comment on partial data).
     statusText auto-routes "cancelled" via status<Camel> i18n.
     Tests: test_cancel_run_writes_stop_flag_and_completes_as_cancelled,
     test_cancel_run_with_zero_spins_marks_cancelled_not_failed.

28. Cross-library ranking (commit ed90aa9):
   - GET /api/library/distributions walks reports/*/mode_*/latest.json
     + their summary JSON, emits per-metric {values, count} +
     archetype_counts + volatility_class_counts. Metrics tracked:
     volatility_score (max(zero_win/0.82, loss_p95/18, tail_ge10/0.50)
     -- a composite where 1.0 = Very High threshold, so rank
     against this gives a continuous "intensity" reading discrete
     labels can't). zero_win_rate / tail_dependency_ge10x /
     big_win_x10_rate / profit_spin_rate also emitted.
   - Frontend kpiVolatilitySub renders "全库 {P-rank} ({n}/{total})"
     for library size >=3, "全库 {n}/{total}" for 2-machine libraries
     (small sample; percentile is noise). kpiArchetypeSub shows
     "{count}/{total} 机台同类型" (categorical; counts distribution
     rather than rank). Applied via applyLibraryRanking() in
     app.js; silently no-ops for single-machine library.

29. Preset run-config defaults (commit 390e1c0):
   - chunk_robot_count / batch_concurrency are editable inputs
     (no longer readonly/autotune-only). Defaults robot=24 conc=2,
     validated against M272 mode 1 autotune (100% success rate,
     922 spins/s p95=8.1s; conc=4 was top-ranked but p95=10s
     tail pushed it to preset conc=2 for safety margin).
   - Advanced params: chunk_spin_times=5000 (unchanged),
     max_chunks=60 (was 120), timeout=120 (was 300). Tightened
     after autotune showed typical CI target hit in well under
     60 chunks at preset concurrency.
   - On machine/mode change: resetConcurrencyInputsToPreset()
     fills inputs from input.defaultValue so the screen always
     has sensible values ready. Auto Tune still refines per
     machine if user wants.

30. Three-layer data architecture (fully implemented):
   - Layer 1 (raw cache): cache/chunks/{run_id}/chunk_*.json saves
     the full upstream API response (~250KB/chunk) with an envelope
     carrying _cache_version, _upstream_schema_fingerprint (SHA256
     of first round's sorted key set), and metadata. Cleaned by
     existing /api/cache/cleanup; Rule #13 compliance: don't delete
     chunks whose run still has a live report version.
   - Layer 2 (aggregated intermediate): the 45-key dict returned by
     run_sampling_chunk(). Lives in memory only; never persisted.
     Rebuild re-computes it from Layer 1 every time.
   - Layer 3 (report assets): reports/<machine>/mode_<n>/versions/
     player_impact_summary.json + _report.md. Permanent. Version-
     managed via index.json + latest.json.
   - Rebuild: POST /api/runs/{id}/rebuild reads Layer 1, re-runs
     full analyzer main() with monkey-patched post_json, overwrites
     Layer 3. Pre-checks chunk compatibility (required round fields
     present in cached data); returns 409 if schema drifted.
31. NewFreespin RTP truncation correction
    (summary.collect_mechanic.newfreespin_correction):
   - Dynamic cycle detection: tracks CollectCount resets per robot.
     Peak CC before each reset = cycle length (median of observed
     peaks). Not hardcoded — works for any machine/mode.
   - Correction = sum across robots of (final_cc / cycle_length) ×
     avg_NewFreespin_payout / total_paid_bet × 100 = correction_pp.
   - M272 mode 1: cycle_length=1000. chunk_spin_times=5000 (aligned)
     → correction=0pp. chunk_spin_times=4500 → +5.92pp.
   - BuffCollectionMap fires at each cycle completion (times=5 per
     5000 spins) but produces 0 WinCredits — it's a progress marker.
     NewFreespin is the forced bonus chain at cycle boundary (no
     PayId 666 involved; trigger spin has PID={}).
32. Raw-data analyses (need per-spin sequential context from Layer 1):
   - payline_symbol_top20: joint (payline_id, symbol_code) → hits +
     total_win + rtp_contribution_pp. Uses RLN when available.
   - session_rtp_curves: per-robot cumulative RTP at ~50 sampled
     points. Frontend can plot spaghetti / envelope.
   - chain_ratio_sequences: per-chain ordered ExtraRatio list (the
     complete escalation path, ≤50 chains).
   - reel_position_top20: position codes from PayoutByPayline
     ranked by hit count.
   - Near-miss: BLOCKED — needs payline definition table the
     upstream API doesn't expose. Noted in TODO.
33. Test infrastructure:
   - tests/fixtures/{machine}_mode{N}_r{robots}_s{spins}.json —
     raw API responses for offline regression. Currently: M14 + M272.
   - test_fixture_{machine}.py: chunk-level invariant tests (5 per
     machine) — upstream delta=0, session_bet_sum correctness,
     RTP plausible range, eq0 internal/external split, SpinType
     behavior.
   - test_full_pipeline_{machine}.py: end-to-end main() → summary
     → baseline comparison (9 per M272, 7 per M14) — exact RTP,
     bucket_sum=rtp, paid/bonus exact, classification match,
     tail_dep tolerance, output shape.
   - Convention: new machine → fetch fixture → compute baseline →
     write test module. No network needed at test time.

34. Upstream API 完整文档 (MachineTest-TestSpin (3).md):
   - POST /MachineTest/MachineConfigMd5 — 返回机台配置 MD5。
     可用于 chunk cache 的双重兼容性检测：schema fingerprint
     （字段结构）+ config md5（机台逻辑）。采样前存 → rebuild 时
     比对 → 两者任一变 = 旧 cache 语义过期。尚未集成到 analyzer。
   - Auth: 正式环境需 ?token= query 参数。buffalo-debug 目前免认证。
   - MachineConfig 字段: 可传自定义 JSON 覆盖全局配置（A/B 测试）。
   - BetStrategy: 0=FixBet（当前使用）/ 1=Alternating / 2=HalfHalf。
   - POST /MachineTest/RTPTest: 上游原生批量 RTP 测试接口。
   - POST /MachineTest/HistoryTestResult: 读取上次批量测试缓存。
35. Debug tab 面板顺序（最新）：
   interpretation → kpis → assessment → bucket-distribution (TABLE,
   无 Chart.js) → spin-types+feature → bonus-chain (per-feature only,
   含 depth curve + histogram) → paylines → pay-ids → symbols →
   events。
36. Bonus chain per-feature 分类规则：
   trigger spin 有 PayoutIdToWinAmount → NormalCollectionSpin（随机）；
   空 PID → NewFreespin（强制保底）。aggregate 汇总已删除，只保留
   per-feature cards + 共享 depth/histogram 表。

Update policy:
- Assistant may update this section after execution, and must explicitly state:
  `updated assistant working memory`.
