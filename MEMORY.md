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
8. Do not persist raw per-spin data. Persist aggregated metrics only.
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
   - frontend chunk_robot_count and batch_concurrency inputs are readonly
     and only Auto Tune populates them;
   - mode / machine change clears those two inputs to force a fresh tune.
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
20. Player-impact drilldown surface:
   - summary.player_impact.paylines_top20 (existing): payline_id /
     hit_count / hit_rate / approx_rtp_contribution_pp / win_share.
   - summary.player_impact.symbols_top20 + symbols_by_column_top10
     (existing): overall + per-column symbol frequency.
   - summary.player_impact.payout_groups_top20 (added by analyzer in
     P1.a/d round): {group_id, hit_count, hit_rate, total_win,
     avg_win_when_hit_x, rtp_contribution_pp}. Group 0 = no payout.
   - All three rendered as their own panel below assessment; the next
     UI restructure round consolidates positioning + visual language.

Update policy:
- Assistant may update this section after execution, and must explicitly state:
  `updated assistant working memory`.
