# TODO

This file tracks executable next steps for the current phase.

## P0 (user-blocked)

- [ ] **Paytable multiplier inference** — PAUSED (shape shipped
      2026-04-19). Multipliers still have 2 unfixed bugs
      (multi-fire double-count, wild stacking rule). Do NOT propose
      resuming; user said "除非我主动提起，不做". See memory
      `project_paytable_inference_paused.md`.

- [ ] **Fuzzy live-sampling CI-stop latent bug** (still pending —
      now less critical since fuzzy is replaced by count-mode in
      the sampling UI, but the backend fuzzy path still exists).
      The live-sampling path (`app.py` `RunManager.start_run`, fuzzy
      tier `target_halfwidth_pp == 0`) still feeds the analyzer
      `effective_halfwidth_pp = 999.0` as the sentinel and bounds the
      run only via the `FUZZY_TARGET_TOTAL_SPINS` max_chunks override.
      The analyzer's stop branch fires when
      ``session_halfwidth_pp ≤ target`` — 999 is usually satisfied
      after chunks=2, so the CI-stop branch can still terminate the
      live run early before max_chunks is reached. The from-cache /
      generate-report paths were already hardened to pass `0.001`
      (so max_chunks is the sole gate, same pattern as ecc5bd4); the
      live `start_run` path was NOT. Fix: make `start_run` also pass
      `0.001` for the fuzzy tier and rely on max_chunks solely. Add a
      regression test. (PARTIALLY ADDRESSED — verify live path before
      closing.)

- [ ] Multi-server 实测: 基础设施就绪，等用户提供 test/prod 地址。

- [ ] **Upstream sampling throughput crisis — switch to internal server**
      (2026-04-24 investigation). Direct-connect to
      the external test endpoint showed two distinct regimes:
      fresh-probe peak 3,765-4,411 outer spin/s at 8×8, dropping to
      ~710-1,085 outer/s after a few hundred requests (per-source
      rate limit). Historical proxy-era single-stream was 4,113
      outer/s with no concurrency benefit needed. Implications:
      - Production 3M-spin sample = 46-75 min per machine/mode
        (well above the 10 min user target)
      - 393 machines × 4-8 modes × 50 min = weeks of wall time
      - No amount of client-side parameter tuning closes the gap
      Action plan:
      1. User is switching to internal game-engine server (pending).
         Retest all concurrency scaling once new endpoint available
         — likely invalidates the 8×8 preset.
      2. If internal server behaves like historical proxy (~4k/s
         single-stream), drop to conc=1-2 for stability and longer
         poll windows.
      3. Add `sampling_source` field to run summaries so we can
         tell retrospectively which endpoint fed which report.
      See memory: reference_sampling_api.md (throughput regimes section)
      + feedback_upstream_throttle_ceiling.md.

- [ ] Consider CI integration when remote build is needed. For now
      the baseline is local-only (`scripts\lint.ps1` +
      `scripts\test.ps1 -E2E`).

## P1 (high-value product improvements)

- [ ] Add auth layer for web console (at least local admin token / company SSO-ready design).
- [ ] Add operation audit log:
  who started/stopped runs, who triggered cache cleanup, timestamps, payload summary.
- [ ] Add report comparison view:
  version-vs-version and machine-vs-machine for key player-impact metrics.
- [ ] Add richer planning metrics cards:
  volatility profile, symbol frequency concentration, streak risk distribution, bankruptcy sensitivity deltas.
- [ ] Add runtime health dashboard:
  queue depth, API failure rate, timeout rate, and endpoint latency percentile.

## P2 (scale and platformization)

- [ ] Multi-machine batch orchestration:
  schedule and track large test campaigns across many machines/modes.
- [ ] Automatic report baseline alerting:
  trigger alerts when new report deviates from baseline thresholds.
- [ ] Config-as-data workflow:
  controlled machine/mode/test profile templates with versioning and approval flow.
- [ ] Deployment packaging:
  produce repeatable deploy assets for company server environment.
  (Partial: a single-box Windows deploy flow now exists —
  `scripts/deploy/` (Task Scheduler XML + run_smoke.ps1 + rollback.ps1 +
  README_DEPLOY.md) plus `scripts/start_console.ps1`. "Repeatable
  deploy assets" packaging beyond that is open.)

## Done Recently

- [x] **Analyzer plugin unbundle + honest per-(machine,mode) staleness +
      auto-inspect + restart recovery + team process** (2026-05-17 →
      2026-05-30; commits include `82bad7a`/`f675556` recovery
      persistence, `1bcf43c`→`fad7f2c` auto-inspect P1–P5,
      `fc1598b`/`3c7e0ba`/`7246a91` honesty-1/2/3,
      `b8ad3fa`→`0045cae` unbundle Phases 2a–6):
      - **Analyzer "unbundle"**: the PIA monolith no longer
        builds report sections inline. All 9 display features are
        plugins under `fresh_slotlab/analyzer/features/`
        (`payouts_by_spin_type`, `reel_marginal_by_spin_type`,
        `bankruptcy_simulation`, `multiplier_profile`, `multiplier_wild`,
        `machine_mechanics`, `upstream_feature_breakdown`,
        `collect_mechanic`, `bonus_chain_dynamics`). The monolith runs a
        topo-sorted feature emit loop; plugins register in
        `fresh_slotlab/analyzer/feature_registry.py` (`ALL_FEATURES`),
        and each machine's manifest
        (`slot_designer/configs/machine_manifests/<machine>.json` →
        `analyzer_features`) declares which it uses. Report content kept
        **byte-identical** (code moved, numbers unchanged).
      - **Hash / versioning model** (`fresh_slotlab/analyzer/versioning.py`):
        `compute_base_analyzer_version()` hashes the report-production
        import closure (`_CLOSURE_FILES`, CRLF-normalized) MINUS the
        registered feature-plugin files; editing a plugin does not flip
        base, editing a closure/core file does.
        `compute_effective_version_for_machine(machine, mode)` =
        sha256(base ⊕ declared-feature hashes ⊕ mode) — the
        per-(machine,mode) version the console uses for report freshness.
        Legacy `compute_analyzer_version()` (sha of PIA's own bytes) is
        still stamped into the summary but is RETIRED from the freshness
        decision.
      - **Honest report-staleness signal**: the console compares the
        per-(machine,mode) effective version (memoized via
        `src/web_console/backend/effective_version_cache.py`). Adding a
        machine invalidates zero existing machines; changing a machine's
        declared features invalidates only that machine. Editing shared
        analyzer logic (closure/core/rule-engines) still invalidates every
        machine that declares an affected feature — by design, a shared-logic
        change really does affect them all. The verdict is **non-destructive**: a
        mismatch marks a cell `needs_rebaseline` and NEVER deletes report
        artifacts (re-baseline is lazy/on-demand + a rate-limited
        background sweep).
      - **Auto-inspect ("自动巡检") fleet sweep**: scan + atomic claim +
        worker dispatch, per-item generate with 9 failure modes + restart
        recovery, frontend tab, cron scheduler, and an M274 RTP-drift
        baseline/alert. See `scripts/deploy/AUTO_INSPECT_SMOKE.md`.
      - **Restart recovery / batch persistence**: the `batches` SQLite
        table (RunManager `_store`, added 2026-05-22) persists
        BatchRunManager + BatchGenerateManager state across console
        restarts; non-terminal batches are restored on startup
        (`_restore_persisted_batches`). This SUPERSEDES the old
        "batch object is in-memory, machine list lost on restart"
        limitation. Orphan runs also auto-resume on startup.
      - **Team process**: `docs/ARCH_TEAM_PROCESS.md` (`arch-*` 6-agent
        design team, markdown only) + `docs/IMPL_TEAM_PROCESS.md`
        (`impl-*` 4-agent implementation team) were used end-to-end for
        the unbundle and honesty work.


- [x] **Variants rollout (stages 1-8) + Analyzer RTP parity (iter 1-6)**
      (2026-04-22→23 round 6, branch `feat/machine-variants` 17 commits
      HEAD `bea239b`):
      - **Variants fleet**: 253 → 393 machines.json rows. 26 underlying
        with variants (TopDollar 5 台×3 / Wheel 11 台 / Common 3 台 /
        Fortunes/DancingDrum/Hoppy/Christmas/Valentine/QuickDollar 各
        1 台) replaced by 166 variant entries. Each is an independent
        first-class machine — own md5, modes, rawdata dir, reports.
        Display name embeds selector type
        (`M273$WheelSelector$1$1-2-3`) while `upstream_key` field
        carries the raw variant key (`M273$1$1-2-3`) for API routing.
        No parent/child relation; only coupling is md5 fanout
        (upstream reports per underlying, siblings share md5).
      - **Analyzer `fresh_slotlab/trigger_sessions.py`**: pure-function
        helper that detects trigger sessions (paid round + non-paid
        sequence + win=0 pay_id anchor). Type 1 (ReMarks starts with
        "Trigger" — M15 TopDollar / M6 Fortunes / etc) uses
        `last_non_none` session_win rule. Type 2 (empty ReMarks —
        M273 Wheel / M201 Common) uses `sum_all` with
        `_round_has_credited_win` filter to skip bonus rounds whose
        Payout already credited pay_ids at round level.
      - **RTP parity invariant** locked: `sum(payout_ids_top20.rtp_pp)
        == summary.rtp.point_pct` (< 0.01pp) fleet-wide. 3 common
        裂缝 fixed: (1) denominator unification (payout row and
        summary.rtp now both use `effective_bet_for_rtp` = paid-only),
        (2) double-count filter for Type 2 sessions, (3) M209 Payout-
        Win scaling (Payout sum > WinCredits → proportional allocate).
      - **Pass 5 settlement-ST binding**: `_infer_feature_spin_type_mapping`
        now binds paying features (total_win > 0) to zero-win
        settlement SpinTypes when count matches within 15%. Runs after
        sanity gate to re-bind what the gate drops. Fixes M15 TopDollar
        → ST 15 (previous rounds 1-4 had TopDollar.resolved_ST = None).
      - **chain_predecessor_feature**: added on every feature row
        (reverse of `spin_type_next_counts`). The legacy
        `chain_parent_feature` actually stores the chain successor
        (misnomer); kept for front-end back-compat. Feature cards now
        know both "who fires me" and "who I fire into".
      - **Settlement bucket reconstruction**: per-session win
        histogram keyed by session's settlement SpinType. Features
        bound to zero-win ST (Pass 5) read buckets from this map
        instead of empty spin_type_bucket_win. M15 TopDollar now
        renders 6-row bucket card (sum 52.83pp = feature header).
      - **Fleet verification**: 5 representative machines live-probed
        post-iter-6; sum(pay_id.rtp_pp) matches summary.rtp within
        sample noise (M15/M273/M257/M209 exact; M273/M201 <1pp on
        30k spin).
      - Tests: 621 pytest (50 variants + 47 trigger_sessions + 9
        payout_win_scaling + 8 post-hook-logging + assorted new
        fixtures / parity locks). Inject-bug-revert patterns applied
        to every load-bearing hunk.
      - **UI structure unchanged** per user directive — catalog grew
        293 → 393 cards but layout identical. Round-4 leftover
        TypeError (`byId("assessment").textContent` on 2 unguarded
        sites) fixed along the way.

- [x] **M112 RTP 修正 + batch-worker 稳定化 + RTP tab flat 排序**
      (2026-04-20 round 4, 3 commits 403adfc → fe6f9d2):
      - **M112 RTP inflation fix**（403adfc）：双路径污染
        1) `CostCredits` 为 null 时 analyzer 把 bet 当 cost 近似，低估
        分母 → RTP 虚高。2) `FinalMinigame` round 和 trigger spin 的
        win 在 session-centric 归因里被双重计入。修完 M112 RTP 从
        139.69% 降到 96.99%，和 server `upstream_feature_breakdown`
        的 96.99pp 精确对齐。summary.rtp 字段加了注释指向
        `upstream_feature_breakdown` 作为 per-feature 权威来源（前者
        在 double-count 机台上 sum 可能 >100%）。
      - **Batch-worker post_hook 可观测**（7e00486）：
        mode 7 全量 batch (252 items) 跑完后发现
        `configs/paytables/*_mode7.json` 一个都没生成 —— analyzer
        summary 都在，但 PayID 总览面板的 shape/covered/composition
        子行全空。根因: `_batch_gen_worker.py` 的 post-analyzer hook
        （跑 `infer_paytable.py` + `verify_machine_labels.py`）有两
        个 silent-failure 缺陷。(1) `script_root` 从 `sys.path[0]`
        读 —— analyzer.main() 导入链会 reorder sys.path，job 执行时
        `sys.path[0]` 可能指向某个 site-packages dir，`scripts/infer_paytable.py`
        路径 check 失败被当成 "script_missing" 跳过。(2) 旧代码
        `except Exception: pass` 吞掉所有错，失败无 trace。修：
        `_pool_worker_init` 把 root path 存成模块全局 `_project_root`，
        hook 用这个稳定锚点解析 script 路径；每个 hook 结果（skip
        原因 / subprocess rc + stderr_tail / timeout / exception）
        append 到 `post_hook` list，并由 `_finalize_batch_gen_item`
        落盘到 `{output_dir}/_post_hook.json`（列表首项是 context
        block: script_root / project_root / sys.executable /
        sys_path_0 / rawdata_root）。5 regression tests 在
        `tests/backend/test_batch_worker_post_hook.py` 锁定契约
        （env 短路、script_missing 记录、context 固定、chunk_dir
        race、initializer 捕获 root）。现有 252 个 mode 7 item 要
        跑 `python scripts/infer_paytable.py --all --mode 7` +
        `python scripts/verify_machine_labels.py --all --mode 7`
        补 paytable JSON，不需要重跑 analyzer。
      - **按 RTP tab flat 化 + 可选 mode**（fe6f9d2）：
        去掉 `< 90% / 90–95% / 95–100% / 100–200% / 200–400% / > 400%`
        七档数字分组，改成单列 flat RTP 降序排。tab 下面多条 mode
        选择器 `auto | mode 1 | mode 2 | mode 5 | mode 7`（全舰队
        summary 的 mode 并集，数字升序），点击立即按该 mode 的
        `rtp_pct` 重排。`auto` 保留旧 picker（优先 mode 2 否则最小
        mode），老书签不破。没有该 mode 数据的机台永远沉底（↑↓
        反转也不上浮）。`state.catalogRtpMode` 新字段；
        `renderRtpModeBar` 仿 `renderHallsRefreshBar` 模式。

- [x] **PayID 总览合并 + 破产分析稳定化 + 采样基建 session** (2026-04-20
      round 3, 10 commits 6defb68 → ecc7c92):
      - **Pay ID 总览**：形状推断 + Pay ID 深度 合并成一张表，策划
        一行读懂每个 pay_id 的 frequency + 倍率 + shape + category
        + composition 细分。把「wild 替换 / 纯度 / 信度」三列都
        删了（composition sub-rows 信息更具体）。
      - **倍率列**（× bet）替代「均赢」列；分母来自新加的
        `summary.sampling.bet` 字段。
      - **Composition breakdown 通用化**：每 pay_id 按 symbol
        multiset 细分，每子行带 fires + avg_win + win_total。
        all-wild pay（pay_id 2、3）拆成具体 wild 组合（e.g.
        `2× Diamond1 + 1× Diamond2` = 240×，`1× Diamond1 + 2×
        Diamond2` = 360×），Bar/7 pay 拆成 base + wild-scaled
        变体（e.g. `3× Bar1` 10× base、`+1 DD` 20× 等）。
        scripts/infer_paytable.py 加 `symbol_tuple_wins` per-tuple
        win aggregator + `composition_breakdown` 输出（top 10 +
        其他 N 种组合 aggregate row）。
      - **折叠/展开**：子行默认全收起；click main 行的 `▸` 或
        整行 toggle 单 pay_id；「展开全部 / 收起全部」两键在
        表格顶部。Client-side state（refresh 归零）。
      - **占比列**：每子行显示该 composition 的
        `win_total / parent win_total %` — 策划直接看到
        「这 pay 的 RTP 贡献里 base vs wild 各占多少」。
      - **Paytable 交叉验证**：新增 `paytable/` 文件夹
        （gitignored? 不，tracked — 策划导出的设计文档），
        `Paytable-M1.md` 当 ground truth，M1 paytable 13 条
        设计 pay 全部对上 analyzer 观察值（误差 < 5%）。
        注意 `3 wild3x = 1000×` 是 grand jackpot，不走普通 spin，
        分析器若观察到要视为异常。
      - **Auto-trigger hook 稳定化**：M1 infer_paytable 实测
        70s，旧 60s timeout 杀 subprocess。修：
        `_run_generate_report` 把 hook 扔后台 daemon 线程（不
        占 ops mutex）+ subprocess timeout 60→300s。测试侧
        `SLOT_SKIP_AUTO_INFER=1` autouse fixture 保持快。
      - **verify_machine_labels.py**：per-machine 文件
        （`dev_reports/_classify/{m}_mode{n}.json`）取代单一
        clobber 的 `all_verdicts_mode{n}.json`（后者仍在
        multi-machine 扫描时写）。backend classifier 端点
        优先读 per-machine，fallback combined。避免并发写 race。
      - **Freshness 行**：当前载入机台面板底部显示
        `Analyzer: ✓ 当前 · Rawdata: ✓ 当前`（或 ⚠ 过期 /
        · 未标记），基于 `state.currentVersions` 和 run 的
        md5 / analyzer_version 对比。
      - **PayID 类型标签**：`payout_ids_top20[*]` 行带
        `spin_type_category` (paid/bonus/mixed) +
        `dominant_spin_type` + `spin_type_breakdown` 三个
        字段（analyzer 新增 per-pay_id × spin_type tally）。
      - **支付线深度双强化**：line_id `-1` 板面 scatter /
        `-2` 特殊 scatter legend badge + top_symbols 源徽章
        (R=RewardLastNode 权威 / H=启发式).
      - **支付线结构分类重排**：feature-mode delta 首位 →
        channel split → cross-mode label table。
      - **`/console/` + `/console` 显式路由**替换 StaticFiles
        mount，修 `{{ASSET_HASH}}` 占位符未替换导致旧 JS 被
        抱死的顽疾。
      - 436 pytest + 133 node:test 绿。

- [x] **机台管理采样基建 + rawdata 锁 session** (2026-04-20 round 3
      tail, 3 commits 82a17c7 → ecc7c92):
      - **Per-(machine, mode) operator lock 注册表**：
        `configs/rawdata_locks.json`（atomic write），
        `POST/DELETE /api/rawdata/{m}/mode/{mode}/lock` 端点
        + `GET /api/rawdata/{m}` 返回 `locked` 字段。
      - **In-memory `_IN_USE_MODES`** 集合追踪正在采样/分析的
        (machine, mode) pair；acquire 在 generate-report /
        batch / sampling 各入口，release 在 finally 早于
        semaphore 以便 waiter 立即见到空闲。
      - **`_auto_cleanup_for_space`** 跨全 fleet 按 oldest-mtime
        删 stale + deletable chunks 到 free ≥ target；**跳过
        locked + in-use** pair；报告 `skipped_locked /
        skipped_in_use`。
      - **Disk-pressure 阻塞等待**替代旧的「`< 2 GB → cancel
        whole batch`」死胡同。env 变量：
        `SLOT_DISK_LOW_WATER_GB=5` / `TARGET_FREE_GB=10` /
        `HARD_STOP_GB=2` / `WAIT_RETRIES=30`。低于 low-water
        时跑 auto-cleanup → 重试 → wait 10s → 重试；只失败
        当前 item 不杀整 batch。
      - **Fix：lock 跨 auto-delete 路径一致**（M1|1 regression
        ecc7c92）：`check_rawdata_status(auto_delete_mismatched
        =True)` 之前没查 lock 注册表，结果 M1 上旧 md5 era 的
        ~百万 spin 样本在 batch 触发时被清空。补上 lock 检查。
      - **采样 UI 批量栏修复**（82a17c7）：`#sampleCancelBtn`
        在 `#batchActionBar` 里，之前可见性只看 selection，
        sampling active 时若清空选择会连带隐藏 cancel 键。
        改成 `hasSelection || samplingActive`。
      - **Orphan report 删除修复**（239b166）：`DELETE
        /api/reports/{m}/{n}/{v}` 新端点替代 `DELETE
        /api/runs/{rid}` 路径处理 `run_id` 在 index.json 但
        DB row 已被 aggressive cleanup 删掉的 orphan 场景。
      - **按大厅 view 重做**（c7363ca + 9a3d4b0）：
        `localMapMachineCellsJson` 默认顺序（~252 cells）+
        `gmMapMachineOrderJson` activity overrides；
        `selectType === 2` 的 17 台 club machine 单独分组。
        去除了假大厅（G6/G10 regex bucket 是 Unity asset
        bundle 名，不是真大厅）。

- [x] **调试机台 KPI 重构 + rawdata-replay 破产分析 session** (2026-04-20,
      5 commits 54836d4 → 5368979):
      - **KPI grid 重写**：删「规则状态」卡、「x500 破产率」卡；波动性
        卡删 Very High/High/... 分类词，只保留全库分位（同 mode 过滤，
        `/api/library/distributions?mode=N` 后端支持）；体验类型卡主
        值改成中文人话（Boom-Bust→爆击驱动、Balanced→稳定平衡、
        Grindy→磨损消耗），子行显示 `{count}/{total} 机台同类型`
        （同 mode 子集）；新增「大奖回合率」4-tile（≥10x / ≥20x /
        ≥50x / ≥100x），结构对齐尾部依赖度；analyzer 扩
        `session_big_win_x{20,50,100}_count/rate`（paid-round 口径）。
      - **规则评估 panel 整块删除**（#assessment / renderAssessment /
        panelAssessment i18n 全部清理）。
      - **破产分析（rawdata-replay）**：替换老的 live HTTP probe
        (`run_bankruptcy_probe` + `skip_bankruptcy` + `--bankruptcy-
        robot-count` 全删)。算法：chunk 内 pool 全部 robot 的 rounds
        成单序列 → 切 non-overlapping session_spins 窗口 → 每窗口
        从新 bankroll 重放（CostCredits 扣钱、WinCredits 加钱，bonus
        round 不扣 bet 但加 win，自然建模「bonus 链短暂救命」）。
        `from-cache` 也能算，不再依赖 live HTTP。
      - **精度进化史**（同一 session 内迭代）：
        * 初版：固定 10 bin 等宽直方图 → x100 首 bin 吃掉 78.5% 难读
        * 改 1：cross-tier shared 自适应等质量 edges（8 bins 从
          pooled bankrupt 分布推出）→ 改善但仍聚合显示
        * 改 2：decile 百分位表（P10..P90）+ 单独「最快破产」行 +
          中位存活（P50），分母 = 全 session，survivor-heavy tier 过了
          bankruptcy 份额后 percentile 自动 pin 到 session_spins
        * **终版**：抛弃 fine_bins 100-bin histogram，per-tier 存精确
          `spins_done` list，sort 后直接取 rank → **spin 级精度**，
          修好 M1 x100 早 decile 都挤在 150/150/150/250... 的假崩塌
      - **session_spins 默认 500 → 10000**（analyzer CLI + backend
        BatchRunRequest + 3 处硬编 + `_batch_gen_worker.py`）。
      - **Pooling 正当性**：upstream RNG stateless per spin
        (ContinueAfterBankrupt=True + reset_each_spin=True)，所以跨
        robot 池化 round 序列 → 合成 10k 窗口与单 robot 跑 10k 统计
        等价。自然突破单 robot chunk_spin_times=5000 的限制。
      - **新 panel 位置**：破产分析放在倍率分布下方（都是风险侧画像，
        连起来读）。
      - **Fix：Pay ID 形状面板双 HTML 转义 bug**（`<all-wild>` →
        `&lt;` → `&amp;lt;` 浏览器渲染出 `&lt;all-wild&gt;` 文本）。
      - **Fix：`/console/` + `/console` 显式 FastAPI 路由**替换 bare
        StaticFiles mount，使 `{{ASSET_HASH}}` 占位符真正替换，浏览器
        不再抱死旧 app.js/pure.js。
      - **新/改 API**：
        * `/api/library/distributions?mode=N` 接 mode 查询参数
        * summary `player_impact.bankruptcy_simulation` 全新 shape：
          `{source, session_spins, percentile_keys: [10..90],
            tiers: [{bankroll_multiplier, robots, bankrupt_robots,
            completed_robots, bankruptcy_rate, median_spins_completed,
            fastest_bankruptcy_spins, percentiles: {10..90 → int}}]}`
        * 保留 `bankruptcy_probe` / `bankruptcy_checks` 旧字段别名
      - **Memory**: `feedback_paid_round_default.md` 新增（所有指标
        默认 paid-round 口径）。
      - **Tests**: +15 `test_analyzer_bankruptcy.py`（break-even
        survival / 破产分桶精度 / bonus 不扣 bet / median=P50 / 过渡
        到 survivor / 分位单调 / 多 chunk merge 保持精度）。
      - **最终数值**（M1 mode 1, 7.67M paid spins, RTP 89.96%）：
        x100: rate 98.7%, fastest 117, P50 365, P90 2,308
        x200: rate 97.3%, fastest 265, P50 920, P90 4,751
        x500: rate 89.0%, fastest 835, P50 3,246, P90 10,000 (pin)
      - 434 pytest + 133 node:test 全绿；全部 preview-verified。

- [x] **机台管理 master/detail 重构 session** (2026-04-19 round 2, 16
      commits 028246d → 0377bd3):
      - **Master/detail shell + focus click model**: `#tab-manage`
        rewritten as topbar + two-column body (catalog master +
        state-driven detail) + flat system footer. Plain click →
        focus, Ctrl/Shift/checkbox → multi, mutually exclusive.
        Run-history table + versionHistoryPanel DOM removed.
        Sticky `#batchActionBar` shows context-aware label + buttons.
      - **Rawdata × Report 4-col tree**: per-mode rawdata stats
        (`N spins (K chunks) · 保底/可回收/过期 in spins`) + 生成
        Report btn + reports list (CI-sorted, best-⭐ expanded).
        Report row has analyzer version badge + 载入/🗑 actions.
        Compare bar sticky bottom with `对比 (2/2)` / `🗑 批量删除
        (N)` / 清除. md5 switcher when rawdata carries ≥2 md5;
        `[+ 跨版本对比模式]` renders side-by-side trees.
      - **Per-path feature bucket split**: analyzer gains
        `chain_bucket_{spins,bet,win}` trackers; paying features
        with ≥2 trigger paths emit separate rows named `{base}
        [via {label}]` with path-specific bucket distribution.
        Trigger-only features kept as single aggregate rows.
        M273 `LockSymbolFreespin` splits via-ListRewardWheel
        (38.11pp) vs via-BCM (3.07pp).
      - **Global rawdata banner + detail table**: topbar shows
        `💾 rawdata X GB · baseline Y GB · 可回收 Z GB` + `一键清理`
        + `明细 ▶` + always-visible settings row (保底 spins 阈值).
        `GET /api/rawdata/overview` backs it with per-machine
        breakdown cached by mtime_ns.
      - **Unified Report 管理 banner**: merges old staleness banner
        + bottom maintenance panel into `💼 Report 管理 · analyzer
        <hash> · ⚠/✓ state [⟳ 重生 K] [⟳ 全 fleet 重建] [🗑 清理过期]
        [📥 导入]`. `⟳ 全 fleet 重建` always visible, scope=all_with
        _rawdata backend variant. Cleanup is aggressive: drops
        tagged-stale disk versions + DB rows; stale count actually
        zeroes after click.
      - **Static-attrs cache** (architectural fix): new
        `configs/machines_static.json` caches category / features /
        mechanics / md5 per machine, UNION across report history.
        Survives report deletes. `GET /api/machines/static` returns
        cache + `drift` list of machines whose cached md5 ≠ current
        machines.json. Fleet overview banner surfaces drift with
        `[刷新 MD5 + 属性]` button. Catalog filter chips + 按机制
        view read from staticAttrs, fall back to machinesSummary.
      - **ProcessPoolExecutor batch parallelism**: `BatchGenerate
        Manager` rewritten to 3-phase (prepare in parent, analyzer
        in worker pool, finalize in parent). New worker module
        `src/web_console/backend/_batch_gen_worker.py`. Default 4
        workers (env var `SLOT_BATCH_GEN_WORKERS`), cross-platform
        via `mp_context=spawn`. In-flight cancel via `[停止]`
        button → `POST /api/rawdata/batch-generate-report/{bid}
        /cancel` → queued futures cancelled, in-flight drains.
      - **Misc fixes**: `_classify_chunks` spins = `_spin_times ×
        _robot_count` (was undercount 27× on M273); report row
        analyzer badge from extended `/api/report-validate`;
        per-report delete + checkbox batch delete via compare bar;
        dynamic destructive btn disabled on ops-busy; catalog
        cards get checkbox for explicit multi-select affordance.
      - 419 pytest (−1 from 420; removed 2 obsolete cache-cleanup
        e2e, added 1 banner cleanup test) + 132 node:test green.
      - `configs/machines_static.json` gitignored (per-fleet cache).
      - **Collateral**: most report versions wiped during aggressive-
        cleanup testing. Rawdata intact; operator clicks `⟳ 全 fleet
        重建` to restore (1006 items × ~15-20s ÷ 4 workers ≈ 30-50
        min wall).

- [x] **Paytable shape + feature chain + bucket pp + dev-decouple
      session** (2026-04-19, 22 commits 3214653 → 00f73b8):
      - **Paytable shape auto-inference fleet-wide** (4 commits):
        `scripts/infer_paytable.py` rewritten for pure shape;
        wild auto-detection multi-signal (mono-tuple +
        substitution + grid density + tier-stem); per-pay_id
        rich shape (symbol_set / symbol_purity /
        wild_substitution_rate / line_id_sign /
        position_cols_covered / confidence / notes);
        `GET /api/paytables/{m}/mode/{n}/shape` endpoint reads
        `configs/paytables/{m}_mode{n}.json`; UI panel on debug
        tab. 27 tests (shape endpoint + wild inference).
      - **Feature↔SpinType mapping robustness** (4 commits):
        `_infer_feature_spin_type_mapping()` 4-pass (unique-count /
        ReMarks count-compat / tied ordinal / tolerance) + sanity
        gate (drops mapping when feature.direct_win>0 and
        ST.total_win<=0). Fixes M102 Wheel over-eager bind + M12/
        M15 TopDollar zero-bucket. Trigger-only feature detection
        with chain_parent inference from SpinType co-occurrence +
        ReMarks + BCM config fallback. Chain-detect uses stricter
        is_paid (None → non-paid) to fix M273 sub-stream
        mis-labeling on ceremony rounds. 13 unit tests +
        inject-bug-revert-verify coverage.
      - **Per-feature multiplier bucket histogram** (3 commits):
        `feature_row.bucket_distribution` + bucket_total_spins;
        `effective_bet_for_rtp = global_paid_bet` so per-bucket pp
        slices global RTP and sums to feature header. Drilldown-
        table styling consistency (purple dev cards removed,
        trigger features absorbed into paying feature breadcrumb).
      - **Per-feature sub-stream split by trigger chain**
        (afcad01): single feature reached via multiple paths
        (e.g. LockSymbolFreespin via ListRewardWheel + via
        BuffCollectionMap) gets per-path bucket histogram + RTP
        pp. UI renders side-by-side sub_stream table.
      - **Collect-cycle + RTP correction panel** (cdf93f8):
        dedicated `#collectCyclePanel` on debug tab; bonus_feature
        (config or heuristic) + cycle_len_lower_bound + correction
        pp; applicable/N/A tone variants. Verified across 129 BCM
        machines × 4 modes (1 legit null for M238 mode 2 — only
        cached mode with no BCM data).
      - **Async generate-report + unified events + delete lock**
        (2 commits): `POST /api/rawdata/{m}/generate-report` with
        `async: true` spawns daemon thread; `DELETE /api/rawdata/
        {m}` acquires ops lock (409 if busy); `GET /api/events`
        aggregated feed; `refreshActivityStrip` polls every 1.2s;
        auto cache-bust via `{{ASSET_HASH}}` templated from
        app.js/pure.js mtime.
      - **Dev/prod sampling decoupling — count mode** (3 commits,
        last 2 = revert+rework): replaced fuzzy dropdown option
        with "指定采样次数" + spin-count input + 总量/增量 strategy
        toggle; `BatchRunRequest` gained `sampling_strategy:
        "total" | "incremental"`. Unifies dev/prod — no separate
        dev-sampling path.
      - **Batch regen performance cap** (2 commits):
        `_peek_chunk_spins()` 20x faster chunk metadata scan;
        `--target-spins-per-mode 10000` picks just enough chunks;
        analyzer `--from-cache` now respects `--max-chunks`
        (was unbounded bug causing M273 to process all 51 chunks).
        M273 batch regen 200s → 3s. `no_chunk` → [SKIP] not [FAIL].
        Low-sample warning path <1000 spins.
      - **Fleet state**: 1006 reports regenerated; 0 failures;
        `scripts/verify_fleet_recent_work.py` returns
        "FLEET VERIFICATION: PASS"; 138 reports with multi-path
        sub_streams; 128/129 BCM machines resolved via config;
        252 paytable shapes clean.
      - 420 pytest (+21) + 132 node:test green.

- [x] **A+B roadmap shipped** (2026-04-18 late, 4 commits):
      - `feat(A1): batch generate-report endpoint + UI` (bc7804d) —
        BatchGenerateManager (sequential worker + per-item status),
        `POST /api/rawdata/batch-generate-report` with polling
        endpoint, sampling-panel "⟳ 批量生成 Report" button that
        runs against the current runFilterMachines × sampleMode.
        Inline per-item log colored by status; 6 regression tests.
      - `feat(A2): fleet staleness banner + one-click batch regen`
        (ca3cb07) — `GET /api/reports/stale-count` buckets runs by
        staleness kind + de-dups fixable items by (machine, mode).
        机台概览 yellow banner shows analyzer-stale count with a
        one-click "⟳ 一键重生成 (K)" button that feeds A1's batch
        endpoint. 5 regression tests.
      - `feat(B3): broken-machine badge on catalog cards` (c5d08c8)
        — per-card ⚠ glyph + tooltip + subtle orange border for
        any machine the fleet-overview anomaly rules flag. 105 of
        253 machines flagged on current data.
      - `feat(B4): 按大厅 catalog view + 全选 button` (00a1031) —
        new view mode grouped by hall ID parsed from upstream
        MapMachineOrder; lazy-fetched cache in
        `configs/machine_halls.json` (gitignored per-server); 全选
        button adds every visible machine to runFilterMachines.
        Live dev server: 32 halls / 247 machines classified.

- [x] **Two UI fixes before A+B** (2026-04-18 late, 2 commits):
      - `fix(generate-report): process all cached chunks`
        (ecc5bd4) — operator noticed M273 rebuild gave 3.4pp CI
        from 2 chunks instead of ~0.5pp from all 51. Root cause:
        target=999 satisfied the analyzer's session-CI stop branch
        immediately. Fix: target=0.001 so max_chunks is the sole
        gate. Reproduced on real M273: 51 chunks / 0.4901pp CI /
        stop_reason=max_chunks_reached. Regression test asserts
        chunks_processed == cached count.
      - `fix(ui): run-history Spins col + version-history white-on-
        white` (d6939bd) — added total_spins column to runs table
        (DB + backfill + UI render); fixed `.mode-tab` inactive
        state that inherited global `button { color: #fff }` →
        `color: var(--ink)`; fixed version-history RTP/CI/Spins
        showing "—" (index.json lacked achieved_* fields; now
        written both sides + endpoint reads summary.json fallback
        for legacy entries).

- [x] **Rawdata lifecycle + version tracking overhaul** (2026-04-18
      evening, 6 commits on top of BCM v2):
      - `feat(versions): plumbing for report staleness detection`
        (27beacd) — analyzer `compute_analyzer_version()` (SHA256[:12]
        of module source) stamped into summary.json; three DB columns
        (`rawdata_config_md5`, `rawdata_code_md5`, `analyzer_version`)
        on `runs`; backfill from summary.json on startup;
        `GET /api/versions/current` returns current analyzer + per-
        machine md5 map.
      - `feat(rawdata): chunk lifecycle rewrite — retention-quota
        tiered delete` (0d68d29) — `_classify_chunks()` partitions
        chunks into kept / deletable / stale per (machine, mode);
        default UI delete respects a 100k-spin retention quota (tunable
        via `PUT /api/settings`); force=true for nuclear cleanup;
        `/api/cache/cleanup` rewritten to operate on RAWDATA_ROOT with
        oldest-mtime priority; rawdata section UI groups chunks by
        md5 version (当前版本 / 服务器旧版); 系统设置 panel exposes the
        retention knob; 26s → 135ms perf via 4 KB envelope peek instead
        of full JSON parse.
      - `feat(rawdata): generate-report endpoint replaces run-id
        rebuild` (21a432f) — old `POST /api/runs/{id}/rebuild` +
        `GET /api/runs/{id}/chunks` removed (they read from the
        never-populated `cache/chunks/`); new
        `POST /api/rawdata/{machine}/generate-report` body `{mode}`
        reads from RAWDATA_ROOT, creates a NEW run row + NEW report
        version (history never overwritten); Frontend rebuild button
        removed from run-history, ⟳ 生成 Report button added to rawdata
        section rows.
      - `feat(run-history): rawdata + analyzer version badges`
        (220044f) — two new columns (Rawdata / Analyzer) with
        当前/失配/未标记 badges per row; `PURE.versionBadges()` isolates
        the comparison logic for unit testing; loadBootstrap caches
        `/api/versions/current` result in state.currentVersions.
      - `refactor: rename dev_rawdata/ → rawdata/` (17fe9f4) — inode
        rename (instant, 9 GB intact); 20+ file references updated;
        `RAWDATA_ROOT` now defaults to `ROOT/rawdata` with
        `SLOT_RAWDATA_ROOT` env var override for prod deploys;
        `scripts/validate_dev_rawdata.py` → `validate_rawdata.py`;
        `DEV_RAWDATA` constants renamed to `RAWDATA`.
      - Post-ship cleanup — removed orphan `refreshChunkStatus` +
        `state.currentChunksAvailable` (belonged to the retired
        rebuild button); removed 9 rebuild-related i18n keys
        (btnRebuild, rebuildSuccess, rebuildFailed, rebuildNoChunks,
        rebuildIncompatible, chunkCompatible, chunkIncompatible,
        rebuildBusy, btnRebuildRun); removed
        `_check_chunk_compatibility` helper.
      - Tests: 377 pytest (+34 new vs 343 baseline) + 132 node:test
        (+6 via versionBadges). All 4 commits preview-verified on real
        M273 data. E2E `test_cache_cleanup_*` updated to write envelope
        chunks to rawdata instead of bytes to cache root. conftest
        gains `tmp_rawdata` fixture; `e2e_launch.py` takes new
        `SLOT_E2E_RAWDATA` env var.

- [x] **Payline-structure classification surfaced to UI** (post
      2026-04-18):
      - New backend endpoint `GET /api/classifier/{machine}` reads
        `dev_reports/_classify/all_verdicts_mode*.json` and returns
        compact per-mode verdict (machine_label, paid_spin_type,
        per_st_verdicts with channel, feature_delta_from_paid,
        feature_tally_keys). 7 tests: happy path / per-mode shape /
        feature-mode delta pass-through / machine-not-in-verdict /
        missing classify dir / corrupted JSON skip / helper directly.
      - New frontend panel "支付线结构分类" (paylineClassification
        Panel) in 调试机台 tab renders 3 blocks:
        (1) cross-mode label table (highlights current mode),
        (2) per-SpinType channel split for current mode (pay_id /
        FeatureWin aggregated / pick-em / etc),
        (3) ⚠ feature-mode rule delta flag — red heading + added/
        removed line_id table when bonus ST line_ids differ from
        paid ST. M273 real-world verification: ST 117 (bonus) adds
        line_id=-2 not in ST 140 (paid); the panel surfaces this.
      - i18n keys added for ZH + EN (panelPaylineClassification,
        classifyHead*, classifyCol*, classifyKind*, classifyDeltaHint).
      - create_app gained optional classify_dir parameter so tests
        can point at a tmp dir with fixture JSON.
      - 343 pytest (+7) + 126 node:test green. Preview-verified on
        M273 mode 1 run before commit.

- [x] **BCM pairing schema v2 — per-mode** (post 2026-04-18):
      - Schema evolved `configs/bcm_pairings.json` from flat
        `{machine: {bonus_feature}}` → per-mode
        `{machine: {modes: {mode_str: {bonus_feature, confidence,
        heuristic_pair, spintype_pair}}}}`. v1 flat schema still
        loads (legacy _mode field honored; unlisted modes fall
        through to heuristic).
      - Cross-mode variance confirmed: **M247** truly pairs with
        PreWheel on modes 1/2/5 but LockReSpin on mode 7. Writing
        mode-1 data as "all modes" would silently under-correct RTP
        on mode 7. 32 other BCM machines consistent across modes.
      - Cache-gap coverage flagged: **M227** (missing mode 5),
        **M238** (only mode 2 in cache), **M254** (missing mode 2 & 5),
        **M274** (missing mode 2). Heuristic fallback handles these.
      - Analyzer `_load_bcm_pairings()` returns
        `dict[str, dict[int, str]]`; `_resolve_bonus_feature(machine,
        mode, tally, config)` takes explicit mode arg.
        `config[machine][mode]` hit → source="config"; miss → falls
        through to heuristic rather than silently using another
        mode's pair.
      - `scripts/infer_bcm_pairing.py` now takes `--modes 1 2 5 7`
        (default), runs all modes in one pass, merges into existing
        v2 config (preserves modes not listed), emits cross-mode
        variance + incomplete-coverage report as self-verification.
      - 4 new test cases in `test_bcm_resolver.py`: per-mode config
        hit, mode-miss falls through to heuristic, v2 loader, v1
        loader backward-compat with explicit _mode. 336 pytest
        (+4 over 332 baseline) + 126 node:test green.

- [x] **Session 2026-04-18 — data-layer deep dive** (8 commits
      463d8d3 → defac90 + cleanup):
      - Sampling-log observability 3-layer refactor (panel即现 +
        lifecycle events + unified timeline with source tags)
      - Adaptive retry hardening (IncompleteRead / RemoteDisconnected
        / ConnectionReset into retry set; max_attempts 3→5 with
        30s backoff cap; bail thresholds 3/20 → 5/40)
      - In-flight per-chunk visibility with live elapsed ticker
        (chunk_started events + as_completed-loop emission)
      - Session-level RTP in live progress (matches final report
        on collect-mechanic machines where spin-level denominator
        under-reports)
      - ✓/⚠ completion semantics (ci_target_met distinguishes real
        success from upstream_unstable / max_chunks-without-CI)
      - AIMD adaptive tuning (halve concurrency + chunk_spins on
        fully-failed batch; grow back on streak) + circuit pause
      - Per-machine BCM bonus-feature pairing
        (`configs/bcm_pairings.json` + heuristic fallback). 33
        BCM machines all paired with high confidence; M273 pairs
        with LockSymbolFreespin, M254 with MultiBuffFreespin, etc.
        Replaces the hardcoded `"NewFreespin"` in the RTP correction
        that silently under-reported 20 of 33 BCM machines.
      - `bonus_cycle_correction` renamed from `newfreespin_correction`
        (legacy key kept as alias); added `bonus_feature` +
        `bonus_feature_source` fields
      - New `cycle_observation` block: distinguishes "no collect
        mechanic" from "collect mechanic but sample too short to
        see a cycle reset" — surfaces cycle_len_lower_bound
      - Per-(machine, SpinType) payline-structure classification
        across 1006 machine-modes — 100% auto-verified via 5-channel
        win-coverage check (pay_id / pay_id+FeatureWin /
        FeatureWin-aggregated / loose-overlap / pick-em-selector).
        Classes: classic-payline, ways-pay (M21/M33 etc.), hybrid,
        no-wins.
      - Schema-probe toolkit: `scripts/probe_schema_full.py`,
        `scripts/probe_round_field.py`,
        `scripts/classify_payline_structure.py`,
        `scripts/verify_machine_labels.py`,
        `scripts/infer_bcm_pairing.py`,
        `scripts/scan_collect_feature_match.py`
      - Data findings documented:
        * `PayoutByPayline` format: `line_id:pay_id-pay_id(positions);`
          where pay_id appears twice (redundant encoding); line_id=-1
          is board-wide scatter; line_id=-2 is another scatter type
          (8 M273 records, 策划 to clarify)
        * Position encoding: `pos = (col+1)*100 + (row-1)`,
          col & row 0-indexed
        * `StopSymbolsByCol` = list[str] per column, dash-joined rows
        * Wild symbols contain "wild" substring (case-insensitive)
          with tier regex `(\d+)x[_-]?wild`
        * M14 true paytable manually verified: 3× high7/3bar/2bar/
          1bar/any-bar/cherry = 8/6/5/4/3/2 × line_bet (line_bet=110
          not 1000/9; remaining 10 is feature/ante)
        * `RewardType` field (策划 mentioned) does NOT exist in any
          cached chunk across 252 machines × 4 modes. Likely
          策划 meant a different field name (possibly `RewardLastNode`
          prefix numerics) or it's a new upstream field not yet
          cached. Awaiting 策划 follow-up.
        * Negative PayId (策划 mentioned) — actually negative line_id
          in PayoutByPayline records, marking board-wide scatter wins.
          PayId values themselves in cached data are all positive.
      - Memory: 3 new feedback files
        (`feedback_no_proactive_fetch`, `feedback_prefer_complex_better`,
        `feedback_self_verify_output`) + 1 project note
        (`project_paytable_inference_paused`)
      - 332 pytest + 126 node:test passing (+ 54 new cases over
        the session)


- [x] **Sampling quality + UX pass** (2026-04-17, second half, 13 commits):
      - `--resume-from-cache` analyzer mode: seed aggregators from cached
        chunks, continue live sampling from `max_existing_idx + 1` until
        CI target or max_chunks. Replaced read-only `--from-cache` on
        the user's batch-run path.
      - Stop condition uses **session-level** CI (not chunk-level).
        Chunk-level CI can collapse with 2-3 similarly-valued chunks
        and would false-trigger `target_ci_reached` at N=240k spins
        with actual CI of 12pp. Shared `session_halfwidth_pp` helper.
      - Loop continues through single-chunk failures. `run_sampling_chunk`
        retries 5xx/URLError/Timeout; if retry exhausts, failure is
        logged as `chunk_failed` event. Run bails only at
        `_MAX_CONSECUTIVE_FAILED_BATCHES=3` or
        `_MAX_CUMULATIVE_FAILED_CHUNKS=20`.
      - Progress event key alignment: analyzer writes
        `current_halfwidth_pp`; backend now reads both that and the
        legacy `halfwidth_pp`. UI CI gauge live during sampling (was
        stuck at N/A).
      - Completion event carries stop_reason + chunks + total_spins +
        duration so operator sees WHY sampling ended.
      - Per-chunk event log in UI: backend exposes `chunk_events` per
        item; critical events (`chunk_failed` / `resume_from_cache` /
        `disk_guard_stop` / `failed`) never pruned, `chunk_progress`
        rotates (last 8). Frontend partitions + sorts chronologically,
        renders all criticals + last 8 progress.
      - Log freezes on batch completion (`state.batchJustCompleted`
        blocks `renderSamplingProgress`). Prev behavior re-rendered on
        every poll tick, could wipe error rows.
      - Double-click guard: `sampleStartBtn.disabled = true`
        synchronously at handler entry. Page-refresh recovery via
        `GET /api/sampling-status` + localStorage `activeBatchId`.
      - Bet-mismatch warning: `_peek_cache_bets(dir)` scans envelope
        `_bet` values; warns when cache differs from analyzer default
        (1000). CI math stays valid; RTP=value-weighted may drift <1%.
      - `resume_cache` is now the only non-fresh path from batch-run
        (reuse/read-only was removed). `--from-cache` CLI still used
        by `batch_generate_reports.py` for offline re-analysis.
      - Analyzer mid-loop disk guard (2GB threshold) + per-(machine,
        mode) lock in `BatchRunManager` to prevent concurrent batches
        from racing the same chunk dir.
      - Autotune rewired to catalog selection + `sampleMode`
        (no sidebar). Tuned values cached in
        `state.tunedSamplingParams`, persisted to localStorage, picked
        up by the next `startSampling()` as robot_count / batch_concurrency.
      - UI restructure: 调试机台 is display-only (sampling moved to 机台
        管理 / 采样选中机台 panel); left sidebar removed; model config
        folded into 模型解读 panel; "当前运行进度" replaced with compact
        loaded-machine identity header.
      - `/api/runs` default limit 50 → 2000; 运行历史 table width auto;
        `max-height: 620px` so 2000 rows scroll internally.
      - Tests: 244 → 278 passed (+34 new cases) including end-to-end
        `test_batch_analyzer_cli.py` which inspects the actual
        subprocess argv (POST /api/batch-run → analyzer CLI args).

- [x] **Structural hardening pass** (2026-04-17, 10+ commits):
      - Chunk cache v3: `.tmp` + `os.replace` atomic write + `_payload_sha256`
        with `load_chunk_envelope()` validation. `ChunkIntegrityError` surfaces
        corruption as a readable error instead of JSONDecodeError. v2 envelopes
        still load for backwards compat.
      - Rawdata index: `rawdata/_index.json` fast path for
        `check_rawdata_status` — 18× speedup (65ms→3.5ms/call).
        Self-healing on drift; `scripts/rebuild_rawdata_index.py` big-hammer.
      - Import transactionality: 4-step commit
        (read_summary → insert_run status=importing → copytree →
        update_run status=completed). Any step fails → full rollback.
        Response shape `{imported, skipped, failed, failures[]}`.
      - Versions retention: `POST /api/maintenance/prune-versions` +
        `scripts/prune_report_versions.py` (default keep=5). Syncs DB +
        index.json + latest.json. Skips active (running/importing) runs.
      - Sampler retry: exp-backoff (1s→2s→4s ×3) on 5xx / URLError /
        TimeoutError. Non-retryable errors fail-fast.
      - Batch regen: 17min → 54s for 1006 reports (bankruptcy probe
        skipped on `--from-cache` since it hits live HTTP; + mp.Pool
        with pre-imported analyzer worker).
      - Session-level CI: `t × sqrt(Var(ret_x)/N) × 100`. Works on
        single-chunk dev reports; stored as
        `sampling.session_level_halfwidth_pp`. Zero-variance clamp.
      - Badge 4-state: ✓ green (MD5 match + CI≤0.5pp) / 🟡 yellow
        (MD5 match, CI > 0.5pp or null) / ⚠ red (MD5 outdated) /
        ? gray (untagged).
      - Error handling tiered: system-level raises, data-level logs +
        continues, action-level logs visibly. Bare `except Exception:
        pass` narrowed to specific types at 4 sites.
      - E2E test: sample → chunk → analyzer → import → UI one-shot
        covering the full happy path + chunk corruption detection.
      - Tests: 166 → 244 passed (+78 over the session).
- [x] **253-machine platform** (2026-04 build):
      auto-synced `configs/machines.json` from MachineConfigMd5,
      9-category auto-classification, raw-feature filter chips (multi-select OR),
      5-view catalog (category/name/volatility/RTP/mechanic),
      per-machine detail panel with logicClassNames + MD5 + per-mode metrics,
      version history + report comparison, machine mechanics analysis
      (LockLines / LockSymbols / LockReels / Jackpot / FreeSpin / DollarPick).
- [x] **Rawdata MD5 tagging + auto-reuse**:
      chunk envelope v2 stores `_config_md5` + `_code_md5` from machines.json;
      per-chunk MD5 verification on batch-run with auto-delete of stale chunks;
      analyzer `--from-cache` mode when usable chunks exist (skip API sampling).
- [x] **Inline sampling panel**: mode+CI selectors (0.5/1/5pp/fuzzy),
      auto-lock fuzzy for mode 2/5, smart chunk_spin_times per machine
      (detects cycle from historical reports), real-time chunk-level progress,
      detailed event log (info/warn/error/danger), disk-space monitor with
      auto-stop < 2GB, subprocess-kill on cancel.
- [x] **Multi-server architecture**:
      `configs/servers.json` CRUD + scan + MD5 diff; analyzer `--endpoint-url`
      CLI arg; version change detection endpoint.
- [x] **Fleet overview headlines**: mode-completeness + per-mode expected-RTP
      range checks (mode 1 ~90%, mode 7 ~80%, mode 2 >150%, mode 5 > mode 2).
- [x] **CostCredits unreliable fix**: pre-scan chunk; if all CostCredits=0
      but BetAmount>0 (LockReSpin machines M10/M23/M131/M133), treat all
      spins as paid so session metrics don't collapse to zero.
- [x] CN/EN console switch and tabbed layout.
- [x] Field-level parameter help tooltips for newcomer usability.
- [x] UI + backend operation mutex for safer writes.
- [x] Startup stale-run recovery with stale process termination attempt.
- [x] Cache cleanup risk-tier UX (low/medium/high) with manual confirmation flow.
- [x] Backend safety-interlock test suite (6 cases: runs / autotune /
      cache-cleanup active-run + mutex blocking).
- [x] Backend startup-recovery test suite (4 cases: stale row marked
      failed, pid termination success/failure, health/system-state
      exposure).
- [x] Backend cache-cleanup test suite (3 cases: idle cleanup,
      max_delete_bytes budget, mutex 409).
- [x] Frontend pure-function test suite
      (25+ assertions via Node built-in `node:test` against `pure.js`).
- [x] Playwright e2e smoke suite (4 cases: language switch, cache
      low-risk flow, cache high-risk token flow, start-button disable).
- [x] Local lint + test scripts (`scripts/lint.ps1`, `scripts/test.ps1`)
      with strict defaults and `-AllowMissingNode` / `-Install` escape
      hatches. Replaces the earlier "Define CI gates" item (CI is
      deferred per operator decision).
- [x] Backend refactor: `create_app()` factory + `main.py` entrypoint;
      `app.py` is now side-effect free at module level, enforced by
      `scripts/check_no_global_state.py` in the lint pipeline.
- [x] `/api/cache/status` exposes `risk_thresholds` so the frontend
      risk tier can be tuned via `SLOT_RISK_MEDIUM_BYTES` /
      `SLOT_RISK_HIGH_BYTES` env vars (used by e2e fixtures).
- [x] M14 now advertises modes 1 / 2 / 5 / 7 via
      `configs/machines.json`; test API verified for all four.
- [x] CI half-width input replaced with a 5-tier picker (0.5 / 1 / 2
      / 5 / fuzzy). Fuzzy tier (value "0") makes the backend target
      ~1M spins via recomputed `max_chunks` and pass halfwidth=999
      to the analyzer so the CI-stop branch never fires. Mode 2 and
      5 are constrained to fuzzy (frontend forces, backend 400-rejects).
- [x] ~~chunk_robot_count + batch_concurrency are now readonly inputs
      populated only by Auto Tune~~ -- superseded. Those inputs are
      now editable with preset defaults (robot=8, conc=8, retuned
      2026-04-24 against direct-connect upstream). Auto Tune remains
      optional for machine-specific refinement. See "Preset run-config
      defaults" entry below.
- [x] chunk_spin_times / max_chunks / timeout moved into a collapsed
      "Advanced parameters" section so the primary panel is shorter.
- [x] Bankruptcy multipliers freeform input replaced with a 3-preset
      select (Standard / Short / Long). Tooltip warns that only
      Standard aligns with the x100/x200/x500 thresholds in
      `classic_slots_guideline_rules.json`.
- [x] Backend `_watch_run` failure message now structured: includes
      analyzer exit_code and lists missing summary/report files even
      when stderr/stdout are empty. Frontend "unknown error" gone.
- [x] New `/api/autotune/progress` endpoint exposes a 1 Hz snapshot
      of the autotune candidate grid so the UI can render
      "X/Y candidates done · last result" while the POST is in flight.
- [x] Global warning bar scoped to system + model only. Per-run
      failure / cancellation detail moved into the runMeta panel.
- [x] Frontend split-cadence polling: 4.5 s for system / runs / cache,
      1 s for the active run. Run progress bar driven by chunks/max
      (or total_spins/1M for fuzzy). New live event summary line.
- [x] Auto Tune live progress panel: 1 s polling against
      `/api/autotune/progress`, formatted via `pure.formatAutotuneProgress`.
- [x] KPI grid expanded from 6 to 12 cards (added volatility class /
      experience archetype / loss streak p95 / max return x / 10x+
      big win rate / x500 bankruptcy rate). Tone classification in
      `pure.extractMetricCards`.
- [x] Three new player-impact drilldown panels: paylines (top 20),
      symbols (overall + by column), payout groups (top 20). Analyzer
      now aggregates `PayoutGroupId` per spin and emits
      `summary.player_impact.payout_groups_top20`.
- [x] Dashboard layout refactor (Grafana-style debug tab): three-region
      shell -- sticky topbar with health/lang/liveStatusStrip; sidebar
      (260px column on desktop, drawer below 1120px with hamburger
      toggle) holding params/model/control buttons; main area with
      compact 3x4 KPI strip (whole-card tone bg), 2x2 chart grid,
      tabbed assessment/interpretation/events panel, tabbed drilldown
      (paylines/payouts/symbols) panel. Manage tab kept as single-
      column panel stack so cache-cleanup e2e keeps working unchanged.
- [x] Dashboard follow-up (per user feedback after first pass):
      sidebar reordered so run-actions sits at the top of the column
      (Start/Auto above the fold). Mid-area and drilldown tab groups
      unrolled into stacked panels because tabs added friction without
      payoff for narrative + table content; mid order is now
      interpretation -> assessment -> events.
- [x] Multiplier bucket schema refined from 10 bins to 12: collapses
      sub-1x buckets (gt0_lt1 unifies the old gt0_lt0.5 + ge0.5_lt1;
      ge1_lt5 unifies ge1_lt2 + ge2_lt5) and splits the deep tail
      (ge100 became ge100_lt200 / ge200_lt500 / ge500_lt1000 /
      ge1000_lt5000 / ge5000). pure.prettyBucketLabel renders friendly
      ranges and keeps fallbacks for legacy keys.
- [x] Charts trimmed to bucket-only: CI / RTP / bankruptcy line charts
      removed since their values are already KPI cards. Multiplier
      bucket bar chart spans full panel width.
- [x] Payline winning-symbol inference: analyzer heuristically tags
      each winning payline with the symbol(s) shared by the leftmost
      three stopped columns (classic 3+ left-to-right pattern). Each
      paylines_top20 row carries top_symbols; the drilldown table
      shows the top 3.
- [x] Interpretation prompt overhauled: includes paylines / payouts /
      symbols subsets, prepends a "参照阈值" reference block mirroring
      classify_volatility / classify_experience_archetype / alert
      thresholds, expands output structure to 6 sections with a
      mandatory "支付线与符号热点" narrative.
- [x] Analyzer parsing test suite + upstream schema drift defense:
      `_check_round_schema` validates first parsed round; required set
      narrowed to {WinCredits, StopSymbolsByCol} after lose-spin
      regression (PayoutByPayline / PayoutGroupId legitimately absent
      on lose / no-payout spins). BetAmount checked via union with
      CostCredits. `tests/backend/test_analyzer_parsing.py` (44 cases)
      locks the parsing contract: schema check (incl. lose-spin-first
      regression + CostCredits fallback), 12-bin bucket classification,
      payline winning-symbol heuristic (left-3 intersection + blank
      filter), payout-group aggregation.
- [x] Zero-spin run guard: `_watch_run` promotes "exit 0 + summary +
      report files but sampling.total_spins=0" runs (e.g. upstream API
      504s for the first chunk) from "completed" to "failed" with
      error_message recording the analyzer's stop_reason. Empty
      reports are kept out of the report index / latest.json.
      Locked by `tests/backend/test_run_lifecycle.py` (4 cases) which
      also covers the happy path end-to-end (POST -> mock analyzer
      writes artefacts -> GET /api/runs/{id}/report serves summary +
      index/latest updated).
- [x] Autotune wall-time speedup (per user feedback): default
      candidate grid compacted from 5x4=20 to 3x3=9
      ({8,16,24} x {1,2,4}); per-robot early exit in `run_auto_tune`
      skips higher concurrency for any robot whose lower-concurrency
      candidate falls below success_rate=0.7; frontend default rounds
      dropped from 2 to 1. Combined effect: autotune typically
      completes in well under half the previous wall time. Locked by
      4 new cases in `tests/backend/test_autotune_progress.py`.
- [x] Events panel moved to bottom of debug tab (per user feedback:
      raw jsonl events are low-readability and only consulted when
      something looks off; assessment + drilldowns get screen
      priority).
- [x] M272 added to machines.json (modes 1, 2, 5, 7). Probed all
      four modes, response shape is the same list-of-robots envelope
      M14 uses; round-level schema satisfied (WinCredits +
      StopSymbolsByCol present). Notes: M272 mode 1 is a collect
      mechanic (SpinType 140 + 126 bonus re-spins), so round count
      exceeds SpinTimes by ~10-30%; PayoutByPayline uses a richer
      `id:mult-count(positions);` format that parse_paylines still
      reduces to ids correctly. End-to-end smoke run: 1812 spin /
      RTP=72.4% in 4 seconds.
- [x] Analyzer top-level shape catch: when upstream returns a non-
      list (e.g. single-dict envelope, raw error string) or a list
      with no robot dicts, the chunk now fails with
      `response_shape_unexpected:...` echoing the offending keys/
      types, instead of iterating non-dict items and silently
      producing parse_failed_zero_chunk. Operator can immediately
      see the shape and ask for the new envelope to be supported.
      5 new test cases lock dict / string / list-of-strings /
      partial-corruption paths.
- [x] Round-level field investigation (M14 + M272) surfaces 4 new
      summary blocks that previous versions either missed or showed
      as informationally empty:
      * `player_impact.payout_ids_top20` (PayoutIdToWinAmount-based
        Pay ID drilldown -- M14 also shows 7 distinct ids contributing
        ~RTP; the older payout_groups_top20 was always group 0 so
        the UI now reads from this).
      * `player_impact.spin_type_breakdown` (per-SpinType spins/
        win/RTP -- exposes M272 mode 2's 36% bonus rounds).
      * `paylines_top20[].top_symbols` (left-3-col intersection +
        blank filter).
      * `upstream_analysis` at summary top-level: server-side
        analysisResult.TotalWin cross-checked against our parsed
        total_win. M14 + M272 mode 1 both verified delta=0.
      * `collect_mechanic` at summary top-level: M272 collect
        bonus tally; M14 reports applicable=false.
      Frontend renders payout_ids_top20 (replacing the empty
      PayoutGroupId table) and spin_type_breakdown (new panel).
      Interpretation prompt subset includes all four blocks plus
      the reference thresholds.

- [x] Paid-session refactor (per user feedback): hit_rate / RTP /
      multiplier bucket / streaks / volatility all switched from
      per-spin to per-paid-session math. Bonus / free-spin wins
      attribute back to the paid spin that triggered them, so hit
      rate isn't diluted by bonus chains. rtp.point_pct denominator
      switched to session_bet_sum (paid bet only) -- the old
      total_bet was also adding BetAmount for bonus spins, which the
      player doesn't actually pay. On bonus-heavy machines (M272
      mode 2: 46% bonus rounds) true RTP recovered from ~286% (under-
      reported) to ~563%. sampling.paid_spins + sampling.bonus_spins
      added so the split is visible. 5 new analyzer test cases lock
      session-tracking semantics.
- [x] Trunk-clamp warning: collect_mechanic.clamp_warning surfaces
      raw signals when chunks ran out of SpinTimes mid-collect-cycle
      (pending_robots, total_pending_paid_spins,
      pending_share_of_paid_spins, avg_paid_spins_per_collect). Does
      NOT fabricate an "estimated lost RTP pp" -- per-machine
      collect bonus varies too much for a single heuristic. Frontend
      interpretation panel renders a warning via #rtpClampWarning
      when applicable=true. 4 new analyzer test cases.
- [x] Defensive os._exit(rc) at analyzer main exit so any worker
      thread stuck in a slow socket read can't keep the process
      alive (defense against the orphan-process leak the user
      reported with 3 stuck CLI probes from upstream-trickle).
- [x] Drop `eq0` multiplier bucket (commit 1c17b34). 11 win-bearing
      bins remain; zero-win rate still lives in
      `hit_and_payout.zero_win_rate`. `prettyBucketLabel` keeps the
      legacy-key fallback so old reports still render.
- [x] Preset run-config defaults + unlock robot/conc inputs
      (commit 390e1c0, retuned 4a76e9e on 2026-04-24). Current preset
      robot=8 / conc=8 / max_chunks=60 / timeout=120. Direct-connect
      benchmark on M14 mode 1 showed 8×8 = 4,411 outer spin/s at
      first probe (fresh upstream), well below robot×conc >= 128
      upstream ceiling. Reset-to-preset on machine/mode change via
      `resetConcurrencyInputsToPreset()` reading input.defaultValue.
      CAVEAT: steady-state throughput drops to ~1,100 outer/s under
      per-source rate limiting (confirmed 2026-04-24); production
      sampling plans must budget 50-60 min per 3M-spin run in the
      limited state, not the 12 min that the peak 4,411/s predicts.
- [x] Manage-tab run history: RTP + CI cols, delete button, machine
      filter via catalog click (commit 56903bc). `DELETE
      /api/runs/{id}` cascades row + interpretations + per-run
      artefacts + report version dir + index.json/latest.json
      rollback. Locked by 4 delete tests.
- [x] 4 new analyzer surfaces from upstream field audit
      (commit c3e7096): multi-threshold tail_dependency_ge{10,20,50,
      100}x; upstream_feature_breakdown from analysisResult.
      FeatureWin (machine-named features like "NormalCollectionSpin"
      / "NewFreespin"); bonus_chain_dynamics from ReMarks Freespin
      annotations (chain length + peak ratio quantiles + self-
      retrigger rate + depth-bucketed energy ramp curve);
      RewardLastNode-based authoritative winning-symbol codes with
      heuristic fallback. M272 mode 1 smoke validates all 4.
- [x] SpinType breakdown RTP denominator fix (commit c3e7096): per-
      type bet now uses CostCredits>0 amounts only (was BetAmount
      blindly); free-spin types (M272 126) emit rtp_pct=null so UI
      shows "N/A" instead of 243% nonsense. Analyzer-derived
      behavior_name ("paid"/"free"/"mixed") added as new table col.
- [x] Frontend panels for the 4 new surfaces (commit 94dae2f):
      kpi-sub multi-threshold on tail card; feature breakdown
      panel (#featureBreakdownPanel); bonus-chain dynamics panel
      with 3 KPI pills + depth curve table + ratio histogram.
- [x] Backfill achieved_rtp_pct / _halfwidth_pp / quality_label
      from on-disk summaries on every startup (commit fd30707).
      Legacy rows render "—" until first startup after migration;
      after backfill they show real values.
- [x] Merge Report Versions panel into Run History (commit 718e955).
      Run-history table grew from 8 to 10 columns (added Version +
      Quality). `section.versions` panel removed;
      `refreshVersions()` fn deleted; `/api/reports/{m}/{n}` still
      exists but unused by frontend. quality_label column added via
      ALTER TABLE + populated in `_update_report_index`.
- [x] Graceful Stop + cancelled status (commit 1714b93).
      `--stop-flag-file` path the backend touches on cancel; the
      analyzer polls it between chunks and exits 0 with
      stop_reason="user_stop". `_watch_run` promotes to
      "cancelled" (NOT failed) when there's any completed chunk;
      status viewable, interpretation enabled. Cross-platform
      alternative to SIGTERM (Windows TerminateProcess doesn't
      deliver a catchable signal).
- [x] Cross-library relative ranking (commit ed90aa9).
      `GET /api/library/distributions` walks all latest.json +
      summaries to emit per-metric {values, count} +
      archetype_counts + volatility_class_counts. Frontend KPI
      cards `kpiVolatilitySub` / `kpiArchetypeSub` render "全库 P87
      (15/17)" for big libraries, "全库 N/M" for small ones.
      Composite volatility_score = max(zero_win/0.82, loss_p95/18,
      tail_ge10/0.50).

- [x] RTP denominator bug fix (commit 5ef2562): eq0 drop had
      excluded zero-win session bets from the denominator, inflating
      M272 RTP from 95% to 470%. return_bucket() restored to "eq0"
      internally; RETURN_BUCKET_ORDER still excludes it from output.
- [x] M272 + M14 full-pipeline regression fixtures + tests (commits
      8586afc + a9ecd4e + 6757cf1). Raw API responses as offline
      fixtures; 9 M272 + 7 M14 baseline assertions lock RTP, bucket
      sum, upstream delta, classification, tail dep, output shape.
- [x] Raw chunk cache: analyzer --chunk-cache-dir saves full API
      response per chunk (~250KB each, ~15MB/run). Backend wires
      cache dir; rebuild endpoint re-parses cached data through
      current analyzer code (commit 1c98edd + f23f302).
- [x] Upstream schema fingerprint + rebuild compatibility pre-check
      (commit 199d14e). SHA256 of first round's sorted key set;
      rebuild returns 409 when cached data is incompatible.
- [x] Debug tab reorder: interpretation moved to top (right after
      KPIs/chart); SpinType + Feature merged into one panel
      (commit ccfb2ca). Feature detail only shown for multi-feature
      machines.
- [x] Manage tab overhaul (commit 67771e3 + f347242 + 3ad8f4d):
      checkbox column + batch delete action bar; machine catalog
      multi-select filter (Set); rebuild button per-row with
      async chunk compatibility check (compatible ✓ / stale ✗).
- [x] NewFreespin RTP truncation correction (commit 098fc98):
      dynamic BuffCollectionMap cycle detection from CC resets;
      estimates lost payout from incomplete cycles. M272 mode 1:
      cycle=1000, correction=0pp when chunk_spin_times aligned.
- [x] 4 raw-data analyses (commit ba33480): payline×symbol joint
      top 20, session RTP curves (per-robot ~50 points), chain
      ExtraRatio complete sequences (≤50 chains), reel position
      hit frequency. Near-miss blocked (needs payline definitions).
- [x] Feature bar track container fix (commit f347242): bar width
      is now relative to a grey track div, not the full row.
      Bonus chain depth curve shows share% of total bonus rounds.

- [x] Major UI redesign (commit 979be08): interpretation at very top,
      Chart.js removed → table-based bucket distribution (count +
      rate% + RTP pp + bar), tail dep 2×2 uniform grid, bonus chain
      per-feature only with restored depth/histogram tables, rebuild
      mutex + runMeta progress.
- [x] Bonus chain per-feature split (commit 1ed1e83): NCS random
      (PayId 666) vs NFS forced (empty PID at cycle boundary). prev_
      round_pids indentation bug fixed.
- [x] Bucket count column + restored bonus chain tables (commit
      40dd34b).

## Work Mode

- Keep report generation deterministic and script-driven.
- Keep LLM usage in interpretation/comparison layer only.
- Never persist raw per-spin full data as long-term report assets.
