# 01 Pipeline Map — Analyzer Unbundle (M275-driven)

> **Produced by**: arch-mapper (W1)
> **Date**: 2026-05-25
> **Scope**: `fresh_slotlab/player_impact_analyzer.py` → `fresh_slotlab/analyzer/core/` → `fresh_slotlab/analyzer/features/` → `player_impact_summary.json`
> **Tuned for**: "PIA inline → plugin carve" surgery decisions

---

## §1 Scope and Entry Points

### Pipeline entry: where data starts

```
upstream API (buffalo-debug.citrusjoy.com)
  → rawdata cache: rawdata/<M>/mode_<N>/chunk_NNN.json
  → parse_chunk_response()  [fresh_slotlab/analyzer/core/parser.py:477]
  → per-chunk rec dict (80+ keys)
  → main() merge loop  [player_impact_analyzer.py:1614-1963]
  → finalization  [player_impact_analyzer.py:3155-4924]
  → write_summary_json()  [fresh_slotlab/analyzer/core/writer.py, re-exported at pia:232]
  → reports/<M>/mode_<N>/versions/<rv>/player_impact_summary.json
```

### Data entry variants

| Mode | Where chunks come from | main() gate |
|------|----------------------|-------------|
| `--from-cache` | `cache_read_dir/*.json` | `player_impact_analyzer.py:1512` |
| `--resume-from-cache` | cache first, then live HTTP | `player_impact_analyzer.py:1512` + online loop |
| Live sampling | `run_sampling_chunk()` → `post_json_with_retry()` → upstream HTTP | `player_impact_analyzer.py:~2100` |

All three paths feed into the **same merge block** at `player_impact_analyzer.py:1614`. The `--from-cache` path repackages the single `rec` as `batch_results_fc = [rec]` and falls through to the same for-loop body (`player_impact_analyzer.py:1613-1613`).

---

## §2 Layer-by-Layer Flow

### Layer 0: Chunk load + envelope

| Function | File:Line | Input | Output |
|----------|-----------|-------|--------|
| `load_chunk_envelope(path)` | `analyzer/core/parser.py:381` | `Path` to `chunk_NNN.json` | `dict` with `response`, `_bet`, `_chunk_index`, `_config_md5`, `_code_md5` |
| `peek_chunk_envelope(path)` | `analyzer/core/parser.py:403` | `Path` (reads only first 512 bytes) | `(idx, cfg_md5, code_md5)` — used for md5 pre-filter without full load |
| `select_replay_chunks_by_md5()` | `analyzer/core/base_pipeline.py`, re-exported at `pia:279` | `cache_dir`, `chunks_index`, md5 filters | filtered `chunk_files` list |

**Chunk envelope fields** (written by `_save_chunk_cache`, re-exported from `analyzer/core/writer.py`):
- `_bet`, `_chunk_index`, `_config_md5`, `_code_md5`, `_payload_sha256`, `response` (list of robot dicts)

---

### Layer 1: Per-round parsing (`parse_chunk_response`)

**Function**: `parse_chunk_response(resp, chunk_index, bet, ...)` — `analyzer/core/parser.py:477`
**Size**: ~1800 lines. The monolithic per-round parsing orchestrator.
**Input**: `resp` (list of robot dicts from upstream API), `chunk_index`, `bet`, `bankruptcy_session_spins`, `bankruptcy_bankroll_mults`, `round_win_rules`

**Internal loop structure** (per robot, per round):

```
for robot in resp:                    # parser.py ~640
    for r in parse_rounds(robot):     # parser.py:187
        # r is a single round dict with fields:
        #   SpinType, BetAmount, CostCredits, WinCredits,
        #   PayoutIdToWinAmount, PayoutGroupId, PayoutByPayline,
        #   StopSymbolsByColumn, ReMarks, JackpotIds, CurFreeSpin,
        #   AddFreeSpin, LockLines, LockSymbols, LockReels,
        #   CollectCount, BuffCollectionMap, ChosenDollarPickPositions
        # + extra fields surfaced via field_discovery
```

**Fields carried per round** (accessible in `extract()` if carve moves work here):

The round dict `r` has these raw upstream fields (subset, `_BASELINE_ROUND_FIELDS` at `parser.py:100`):
```
SpinType           int     — round type (140=paid, 126=free for M275; varies per machine)
BetAmount          int     — face bet in credits
CostCredits        int     — 0 for free spins; >0 for paid
WinCredits         int     — per-round win (may be overridden by RoundWinRule)
PayoutIdToWinAmount str    — "id:win;id:win;..." breakdown
PayoutGroupId      int     — grouping (0 = no grouping for M275)
PayoutByPayline    str     — "line:sym..;..." for symbol placement
StopSymbolsByColumn str    — reel grid snapshot
ReMarks            str     — free-text annotations incl. "Freespin N/M ExtraRatio=100"
JackpotIds         str     — "-"-separated jackpot tier IDs when triggered
CurFreeSpin        int     — current free spin index (0 = paid spin)
AddFreeSpin        int     — retrigger count added this round
LockLines          str     — locked paylines
LockSymbols        str     — locked symbol positions
LockReels          str     — locked reel indices
CollectCount       int     — BCM cycle counter (0..1000 for M275 family)
BuffCollectionMap  str     — BCM buffer state (trigger: reset CC back to 0)
ChosenDollarPickPositions str — dollar-pick game selections
```

**Per-round derived state** (computed inside parser loop, NOT returned to main):

- `win_amt` from `extract_round_win(r, rules=round_win_rules)` — `round_win.py`, imported at `parser.py:72`
- `payouts` from `extract_round_payouts(r, rules=round_win_rules)` — `round_win.py`
- `is_wild_nudge = is_wild_nudge_round(r)` — `round_classification.py:71`, imported at `parser.py:71`
- `is_cycle_peak = detect_cycle_peak(r, prev_cc)` — `round_classification.py`, imported at `parser.py:71`
- `fs_meta = parse_freespin_remarks(r.get("ReMarks"))` — `parser.py:238`
- Per-robot trigger sessions computed by `compute_trigger_sessions(rounds, rules)` — `trigger_sessions.py`, imported at `parser.py:70`

**Key observation**: none of these derived values flow back to `main()`. They are computed, consumed inside `parse_chunk_response`, and aggregated into the returned `rec` dict. A `plugin.extract(parse_state, chunk_dict)` call in the current architecture receives the chunk-level `rec` dict (`chunk_dict`), not the round-level `r` dict. The `parse_state` parameter in `AnalyzerFeature.extract()` is documented as "current parser state object" (`features/_base.py:129`) but is currently passed as `None` in the only call site (`player_impact_analyzer.py:4831`).

---

### Layer 2: Chunk-record shape (`rec` dict)

`parse_chunk_response` returns an `ok=True` dict with these top-level keys (full list at `parser.py:2084-2331`):

**RTP / basic counters**:
```
ok, index, elapsed_seconds, spins, bet, win
ret_count, ret_sum, ret_sq_sum, max_return_x
win_spins, loss_spins, profit_spins, breakeven_or_more_spins, big_win_x10_spins
win_sum, lack_credit_spins
```

**Payout attribution** (feeds payout_ids_top20, payout_groups_top20, payouts_by_spin_type):
```
payout_id_hits              dict[str, int]         — pid → count
payout_id_win               dict[str, float]        — pid → credits won
payout_id_by_spin_type      dict[pid, dict[ST,int]] — per-ST hit counts
payout_id_win_by_spin_type  dict[pid, dict[ST,float]]— per-ST win amounts  (added 2026-05-14)
payout_group_hits           dict[int, int]
payout_group_win            dict[int, float]
```

**SpinType breakdown** (feeds spin_type_breakdown, payouts_by_spin_type, reel_marginal_by_spin_type):
```
spin_type_spins             dict[str, int]
spin_type_bet               dict[str, float]
spin_type_paid_bet          dict[str, float]
spin_type_win               dict[str, float]
spin_type_wins              dict[str, int]
spin_type_paid_rounds       dict[str, int]
spin_type_next_counts       dict[str, dict[str, int]]   — transition matrix
spin_type_remarks_sample    dict[str, list[str]]
spin_type_nudge_round_count dict[str, int]              (Bug 3 fix 2026-04-27)
spin_type_bucket_spins      dict[str, dict[bname, int]]
spin_type_bucket_bet        dict[str, dict[bname, float]]
spin_type_bucket_win        dict[str, dict[bname, float]]
```

**Symbol / reel** (feeds symbols_top20, symbols_by_column, reel_marginal_by_spin_type):
```
symbol_counts               dict[str, int]
symbol_counts_by_col        dict[str, dict[str, int]]
symbol_counts_by_col_by_row dict[str, dict[str, dict[str, int]]]
symbol_counts_by_col_by_spin_type  dict[str, dict[str, dict[str, int]]]  (added 2026-05-14)
payline_rows_per_col        dict[str, list[int]]
total_symbol_slots          int
payline_hits, payline_win_approx, payline_winning_symbols, payline_winning_symbols_rln
payline_symbol_joint, reel_position_hits
```

**BCM / collect mechanic** (feeds collect_mechanic):
```
collect_count_total         int
acc_credits_max             int
collect_robots_seen         int
clamp_pending_paid_spins    int
clamp_pending_robots        int
cycle_peaks                 list[int]
final_cc_values             list[int]
completed_cycles            int
```

**Upstream feature attribution** (feeds upstream_feature_breakdown):
```
upstream_feature_tally      dict[feat_name, dict[pid, {win, times}]]
upstream_chunk_total_win    float
upstream_chunk_robots_seen  int
```

**Bonus-chain dynamics** (feeds bonus_chain_dynamics):
```
bonus_chain_lengths, bonus_chain_max_ratios, bonus_chain_retrigger_events
bonus_total_rounds, bonus_retrigger_rounds
bonus_extra_ratio_counts    dict[str, int]
bonus_depth_ratio_sum, bonus_depth_ratio_count
chains_by_feature           dict[feat, {lengths, max_ratios, ...}]
chain_chunk_summaries       list[{first_st, entry_cc_reset, sp_type, count, win, bet}]
chain_bucket_spins/bet/win  list[{first_st, entry_cc_reset, sp_type, buckets}]
chain_ratio_sequences       list[list[int]]
```

**Machine mechanics** (feeds machine_mechanics.jackpot / free_spin / lock_* / dollar_pick):
```
jackpot_spins, jackpot_ids_seen, jackpot_win
freespin_chain_spins, freespin_retriggers, freespin_max_chain, freespin_win
lock_lines_spins, lock_lines_total_lines, lock_lines_win
lock_symbols_spins, lock_symbols_unique, lock_symbols_win
lock_reels_spins, lock_reels_win
dollar_pick_spins, dollar_pick_total_dollars, dollar_pick_win
```

**Session-level** (feeds player_impact.volatility, hit_and_payout, streaks):
```
paid_session_count, bonus_spin_count
session_win_count, session_lose_count, session_profit_count, session_breakeven_count
session_big_win_x10/x20/x50/x100_count
session_ret_count, session_ret_sum, session_ret_sq_sum, session_max_return_x, session_win_sum
session_bucket_spins/bet/win
session_loss/win_streak_hist, session_max_loss/win_streak
session_bucket_spins/bet/win_by_settlement_st  (Iter 6, 2026-04-23)
session_rtp_curves
```

**Bankruptcy**:
```
bankruptcy_sim              dict[int, {bankrupt, survived, spins_done}]   — per-tier, per-chunk
bankruptcy_reps             list[(cost_bet, cost_win)]                    — raw reps for cross-chunk pooling
```

---

### Layer 3: Cross-chunk accumulation (merge loop)

**Location**: `player_impact_analyzer.py:1614–1963` (from-cache path) + online path (same logic, identical merge statements, duplicate code — noted in source comment at `pia:1606-1612`).

**Accumulator count**: ~50 module-level variables initialized at `pia:1183-1388`.

The merge loop reads each `rec[key]` and adds/extends into the corresponding accumulator. There is no abstraction over accumulator types — each field is merged with hand-written add/max/extend logic.

**Observation**: The from-cache merge block and the online sampling merge block are noted as duplicates in the source. The source comment at `pia:1606-1612` says "We must replicate the merge here because the online loop is inside a while-block we skip." This is an open duplication risk noted in the code itself.

---

### Layer 4: Finalization — inline aggregation blocks

This is the surgical target. After all chunks are merged, `main()` runs a sequence of aggregation blocks (all in `player_impact_analyzer.py:3155-4796`) to produce the summary keys. The blocks and their line ranges:

#### Block F1: `spin_type_rows` + `_st_behavior`
- **Lines**: `pia:3155–3222`
- **Reads**: `spin_type_spins`, `spin_type_bet`, `spin_type_paid_bet`, `spin_type_win`, `spin_type_wins`, `spin_type_paid_rounds`, `total_spins`, `total_bet`
- **Intermediate**: `spin_type_rows: list[dict]`
- **Writes**: `summary["player_impact"]["spin_type_breakdown"]` (at `pia:4441`)
- **Side products**: `spin_type_coverage` (`pia:4442`), `_st_behavior` dict used by F2

#### Block F2: `payout_id_rows`
- **Lines**: `pia:3210–3290`
- **Reads**: `payout_id_win`, `payout_id_hits`, `payout_id_by_spin_type_total`, `_st_behavior`, `total_spins`, `effective_bet_for_rtp`
- **Intermediate**: `payout_id_rows: list[dict]`
- **Writes**: `summary["player_impact"]["payout_ids_top20"]` (at `pia:4428`)
- **Depends on**: Block F1 (`_st_behavior`)

#### Block F2b: `payout_group_rows`
- **Lines**: immediately before F2, ~`pia:3430-3445` (payout_groups assembly)
- **Reads**: `payout_group_hits`, `payout_group_win`, `total_spins`, `effective_bet_for_rtp`
- **Writes**: `summary["player_impact"]["payout_groups_top20"]` (at `pia:4427`)

**Gap #5 source**: `payout_group_rows` is always built; if all PayoutGroupId values are 0 (M275), there is a single row covering 100% of spins. The block has no "is this grouping meaningful?" guard — it writes the row regardless (`pia:4427`).

#### Block F3: `_st_label` + `payouts_by_spin_type`
- **Lines**: `pia:3292–3349`
- **Reads**: `_st_label` (derived from F1's `spin_type_rows`), `payout_id_win`, `payout_id_win_by_spin_type_total`, `payout_id_by_spin_type_total`, `spin_type_spins`, `spin_type_paid_bet`, `effective_bet_for_rtp`
- **Intermediate**: `payouts_by_spin_type: dict[str, list[dict]]`
- **Writes**: `summary["player_impact"]["payouts_by_spin_type"]` (at `pia:4436`)
- **Depends on**: Block F1 (`_st_label`)

**Gap #7 source**: `payouts_by_spin_type` rows lack `shape`, `cols`, `paylines`, `notes` fields. The current row schema only contains `payout_id, hit_count, hit_rate, total_win, avg_win_when_hit, rtp_contribution_pp` (`pia:3331-3346`).

**`_st_label` is a cross-cutting intermediate**: defined at `pia:3302-3305` from F1's output; consumed by F3 (payouts_by_spin_type) AND F4 (reel_marginal). Any carve that moves either F3 or F4 must carry `_st_label` with it or it must be a separately computed shared intermediate.

#### Block F4: `reel_marginal_by_spin_type`
- **Lines**: `pia:3408–3429`
- **Reads**: `_st_label`, `symbol_counts_by_col_by_spin_type_total`
- **Intermediate**: `reel_marginal_by_spin_type: dict[str, dict[str, list[dict]]]`
- **Writes**: `summary["player_impact"]["reel_marginal_by_spin_type"]` (at `pia:4440`)
- **Depends on**: Block F1 (`_st_label`)

#### Block F5: `upstream_feature_breakdown`
- **Lines**: `pia:3431–3872` (includes `_infer_feature_spin_type_mapping`, `_resolve_bonus_feature`, `sub_streams_by_feature` post-processing, per-feature row assembly)
- **Reads**: `upstream_feature_tally`, `spin_type_spins`, `spin_type_remarks_sample`, `spin_type_win`, `spin_type_nudge_round_count`, `spin_type_next_counts`, `spin_type_bucket_spins/bet/win`, `session_bucket_spins/bet/win_by_settlement_st`, `chain_chunk_summaries`, `chain_bucket_spins/bet/win`, `effective_bet_for_rtp`, `upstream_total_win`, `total_spins`, `args.machine`, `args.rtp_mode`
- **Intermediates**: `feature_times_total`, `feature_win_total`, `feature_to_spin_type`, `spin_type_to_feature`, `ambiguous_mapped`, `_wild_nudge_st_set`, `_bcm_bonus_feature/_bcm_bonus_source`, `_sub_stream_acc`, `sub_streams_by_feature`, `spin_type_prev_counts`, `upstream_feature_rows`
- **Writes**: `summary["player_impact"]["upstream_feature_breakdown"]` (at `pia:4511`)
- **Helper calls**:
  - `_infer_feature_spin_type_mapping()` — `pia:3447`, defined `pia:498`
  - `_resolve_bonus_feature()` — `pia:3478`, defined `pia:681`
  - `build_multiplier_bucket_rows()` — re-exported from `aggregator.py`, called at `pia:3718`, `pia:3790`
  - `_load_bcm_pairings()` — `pia:441`, reads `configs/bcm_pairings.json`

**This is the largest finalization block.** It alone spans ~440 lines. BCM pairing config is read twice via `_load_bcm_pairings()` — once for `_resolve_bonus_feature` at `pia:3478` and once again for `collect_mechanic.bonus_cycle_correction` at `pia:4706`/`4718`.

#### Block F6: `bonus_chain_dynamics`
- **Lines**: `pia:3874–3962`
- **Reads**: `bonus_chain_lengths`, `bonus_chain_max_ratios`, `bonus_chain_retrigger_events`, `bonus_total_rounds_global`, `bonus_retrigger_rounds_global`, `bonus_extra_ratio_counts`, `bonus_depth_ratio_count`, `bonus_depth_ratio_sum`, `all_chains_by_feature`
- **Intermediate**: `bonus_chain_dynamics: dict`
- **Writes**: `summary["player_impact"]["bonus_chain_dynamics"]` (at `pia:4516`)

#### Block F7: streak / bankruptcy / volatility / tail metrics
- **Lines**: `pia:3964–4105` (streaks, quantiles, bankruptcy finalize, quality gate, tail metrics, classify_*)
- **Reads**: `session_loss/win_streak_hist`, `total_session_max_loss/win_streak`, `loss/win_streak_hist`, `max_loss/win_streak`, `bankruptcy_sim_totals`, `bankruptcy_stream_acc`, `_bankruptcy_mults_tuple`, `bankruptcy_sim_session_spins`, `multiplier_bucket_spins/bet/win`, `total_win`, `effective_bet_for_rtp`, `total_spins`, `ret_count/sum/sq_sum`, `total_paid_sessions`, `total_bonus_spins`
- **Intermediates**: `bankruptcy_rows`, `loss/win_streak_p50/90/95`, `volatility_class`, `experience_archetype`, `tail_*`, `quality_label`, etc.
- **Writes**: Multiple keys in `summary["player_impact"]`: `multiplier_profile`, `hit_and_payout`, `streaks`, `bankruptcy_simulation`, `bankruptcy_probe` (the last two via `BankruptcySimulation.emit()`, Pattern B plugin)

**`multiplier_bucket_rows`** is computed before this block at `pia:~2980-3100` (inside a larger block computing `effective_bet_for_rtp`, `rtp_point_pct`, `multiplier_bucket_rows`). These intermediate values are then read by F7 and also by F3, F4, F5.

#### Block F8: `machine_mechanics`
- **Lines**: `pia:4457–4510`
- **Reads**: `total_jackpot_spins`, `total_jackpot_ids_seen`, `total_jackpot_win`, `total_freespin_chain_spins`, `total_freespin_retriggers`, `total_freespin_max_chain`, `total_freespin_win`, `total_lock_lines_*`, `total_lock_symbols_*`, `total_lock_reels_*`, `total_dollar_pick_*`, `effective_bet_for_rtp`, `total_spins`
- **Writes**: `summary["player_impact"]["machine_mechanics"]` (at `pia:4457`)

**Gap #1 and #2 source — root cause**:
- `machine_mechanics.jackpot.applicable` is `total_jackpot_spins > 0` (`pia:4484`)
- `total_jackpot_spins` is populated from `rec["jackpot_spins"]` in the merge loop (`pia:1950`)
- `rec["jackpot_spins"]` comes from `parser.py` counter `jackpot_spins` which increments when `r.get("JackpotIds")` is non-empty (`parser.py:1378-1383`)
- M275's jackpot pids (27502/27503/27504) are payout IDs in `PayoutIdToWinAmount`, NOT entries in the `JackpotIds` field
- Therefore `jackpot_spins` = 0 despite jackpot-class wins being visible in `payout_id_win`
- Same issue for `freespin_chain_spins`: increments only when `r.get("CurFreeSpin")` has a positive value (`parser.py:1389-1399`). M275 freespins may use SpinType=126 + `ReMarks="Freespin..."` but without `CurFreeSpin` being set → `freespin_chain_spins` = 0
- **There is no cross-reference between `payout_ids_top20` / `upstream_feature_breakdown` and `machine_mechanics`**: each panel builds from independent accumulators populated by different raw field detectors

#### Block F9: `collect_mechanic`
- **Lines**: `pia:4608–4732`
- **Reads**: `collect_robots_seen_total`, `collect_count_total`, `acc_credits_max_global`, `total_spins`, `total_paid_sessions`, `clamp_pending_robots_total`, `clamp_pending_paid_spins_total`, `all_cycle_peaks`, `all_final_cc_values`, `total_completed_cycles`, `upstream_feature_tally`, `effective_bet_for_rtp`, `args.machine`, `args.rtp_mode`
- **Helper calls**:
  - `_compute_bonus_correction()` — `parser.py:274`, imported and called at `pia:4700`
  - `_resolve_bonus_feature()` — called twice at `pia:4706` and `pia:4717` (second call just for `feature_match`)
  - `collect_feature_match_warning()` — `pia:744`, called at `pia:4714`
  - `build_cycle_observation()` — `pia:786`, called at `pia:4727`
- **Writes**: `summary["collect_mechanic"]` (at `pia:4608`, top-level, NOT under `player_impact`)

**Gap #6 source**: `estimated_correction_pp` is computed by `_compute_bonus_correction()` (`parser.py:274`). The formula requires `all_final_cc_values` to contain robots with pending cycles (`fcc < cycle_length`). In the M275 report, `robots_with_pending_cycle: 0` means no robot had a partial cycle at chunk-end. With `robots_with_pending_cycle = 0`, the correction formula correctly returns 0.0 — this is mathematically correct given the truncation, not a formula bug. The brief's claim that the correction should be nonzero given clamp_warning's 80% pending share requires investigation: clamp_warning fires for a different reason (pending_paid_spins represent paid spins toward next cycle trigger, which is different from "robots with partial cycle at end").

**Note on `collect_mechanic` scope**: it is at the TOP LEVEL of `summary`, not under `summary["player_impact"]`. This is distinct from all other panel blocks which live under `player_impact`.

---

### Layer 5: Version stamping

**Location**: `player_impact_analyzer.py:4245–4302`

| Function | File:Line | Output |
|----------|-----------|--------|
| `compute_analyzer_version()` | `pia:1007` — reads `__file__` (PIA itself) | `sha256(pia_source)[:12]` → `summary["analyzer_version"]` |
| `compute_effective_version_for_machine(machine, mode)` | `analyzer/versioning.py:92` — called at `pia:4284` | composed hash → `summary["effective_analyzer_version"]` |

**Hash composition flow** (per `versioning.py:202-260`):
```
compute_base_analyzer_version()        # versioning.py:48
  → sha256(sorted(core/*.py files))[:12]
  → base_hash

compute_effective_analyzer_version(    # versioning.py:202
  base_hash,
  feature_hashes = {fid: sha256(feature_file)[:12]},
  machine_features = manifest["analyzer_features"],
  mode = args.rtp_mode
)
  → h = sha256(base_hash)
  → for fid in sorted(set(machine_features)):
      h.update(b"\x00" + fid + b"=" + feature_hashes[fid])
  → h.update(b"\x00mode=" + str(mode))
  → return h.hexdigest()[:12]
```

**What is hashed**:
- `base_hash`: all `*.py` files in `fresh_slotlab/analyzer/core/` — aggregator, base_pipeline, parser, writer, _utils (`versioning.py:86`)
- `feature_hashes[fid]`: `sha256(Path(cls.__file__).read_bytes())[:12]` for each feature plugin (`_base.py:191`)
- `machine_features`: from `manifest["analyzer_features"]` list (`versioning.py:191`)
- `mode`: appended as `b"\x00mode=1"` (`versioning.py:255`)

**What is NOT hashed**:
- `player_impact_analyzer.py` itself — this is hashed separately into the legacy `analyzer_version`
- `round_classification.py`, `round_win.py`, `trigger_sessions.py` — not in core/ or features/
- `configs/bcm_pairings.json` — external config, not hashed
- `configs/machine_round_win_rules.json` — not hashed
- `slot_designer/configs/machine_manifests/*.json` — manifest schema not hashed (only the `analyzer_features` list content drives the hash via feature file hashes)

**Where hashes land**:
- `summary["analyzer_version"]` = legacy PIA-file hash (`pia:4316`)
- `summary["effective_analyzer_version"]` = composed hash (`pia:4319`)
- `summary["effective_analyzer_version_error"]` = diagnostic if computation failed (`pia:4323`)

---

### Layer 6: Feature plugin execution (Wave 2c)

**Location**: `player_impact_analyzer.py:4806-4832`

```
summary["_bankruptcy_rows"] = bankruptcy_rows          # pia:4811
summary["_bankruptcy_sim_session_spins"] = ...         # pia:4812

# Import all 4 feature modules (idempotent register() calls)
import fresh_slotlab.analyzer.features.payouts_by_spin_type
import fresh_slotlab.analyzer.features.reel_marginal_by_spin_type
import fresh_slotlab.analyzer.features.bankruptcy_simulation
import fresh_slotlab.analyzer.features.multiplier_profile

for _feature in ALL_FEATURES:
    _feature.emit(None, summary)        # pia:4831 — None is parse_state
```

**What each plugin actually does**:

| Plugin | Pattern | emit() behavior | FEATURE_ID |
|--------|---------|-----------------|------------|
| `PayoutsBySpinType` | A (scaffold) | assert key present in summary — no-op verification | `payouts_by_spin_type` |
| `ReelMarginalBySpinType` | A (scaffold) | assert key present — no-op verification | `reel_marginal_by_spin_type` |
| `MultiplierProfile` | A (scaffold) | assert key present — no-op verification | `multiplier_profile` |
| `BankruptcySimulation` | B (logic extracted) | reads temp keys, writes `bankruptcy_simulation` + `bankruptcy_probe`, deletes temp keys | `bankruptcy_simulation` |

**Critical finding**: `parse_state` is always `None` at the call site (`pia:4831`). The `AnalyzerFeature.extract()` contract specifies `parse_state` as "current parser state object" (`_base.py:129`) but it has never been wired. All 4 plugins have no-op `extract()` implementations.

---

### Layer 7: RTP integrity gate

**Location**: `player_impact_analyzer.py:4849-4922`

Calls `check_rtp_integrity(summary, manifest, rawdata_dir=None, warn_only=True)` from `analyzer/rtp_integrity.py`.

Writes `summary["rtp_integrity_check"]` with:
- `layer1_invariant_ok` — `our_total_win == server_total_win` (±epsilon)
- `layer2_no_fallback_buckets_ok` — no `_unattributed_*` pids in top-N
- `layer3_anchors_ok` — manifest-declared `required_attribution_anchors` present in payout_ids
- `layer4_per_st_consistency_ok` — per-SpinType win sums consistent

---

### Layer 8: Write

**Location**: `player_impact_analyzer.py:4924`

`write_summary_json(summary, args.output_dir)` — `analyzer/core/writer.py`, re-exported at `pia:231`

Writes to `args.output_dir/player_impact_summary.json`. The `args.output_dir` is set by the backend to `reports/<M>/mode_<N>/versions/<rv>/`.

---

## §3 Shared vs Per-X Boundary Table

| File / Function | Scope | Consumers |
|----------------|-------|-----------|
| `fresh_slotlab/player_impact_analyzer.py` | Fleet-shared (runs for every machine/mode) | backend `_batch_gen_worker.py`, `virtual_analyzer.py`, CLI |
| `fresh_slotlab/analyzer/core/parser.py` | Fleet-shared | PIA (re-export), `batch_dev_sampler.py`, tests |
| `fresh_slotlab/analyzer/core/aggregator.py` | Fleet-shared | PIA (re-export), tests |
| `fresh_slotlab/analyzer/core/writer.py` | Fleet-shared | PIA (re-export) |
| `fresh_slotlab/analyzer/core/base_pipeline.py` | Fleet-shared (HTTP + AIMD + arg parsing) | PIA (re-export), tests |
| `fresh_slotlab/analyzer/core/_utils.py` | Fleet-shared (helper functions) | PIA (re-export), parser.py |
| `fresh_slotlab/analyzer/features/_base.py` | Fleet-shared (ABC) | all 4 plugin files |
| `fresh_slotlab/analyzer/feature_registry.py` | Fleet-shared | PIA, versioning.py, tests |
| `fresh_slotlab/analyzer/versioning.py` | Fleet-shared | PIA main() (effective_version), backend staleness check |
| `fresh_slotlab/analyzer/manifest_loader.py` | Fleet-shared | PIA main() (integrity gate), versioning.py |
| `fresh_slotlab/analyzer/rtp_integrity.py` | Fleet-shared | PIA main() (Layer 1-4 gate) |
| `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` | Fleet-shared (Pattern A scaffold) | PIA main() emit loop |
| `fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py` | Fleet-shared (Pattern A scaffold) | PIA main() emit loop |
| `fresh_slotlab/analyzer/features/multiplier_profile.py` | Fleet-shared (Pattern A scaffold) | PIA main() emit loop |
| `fresh_slotlab/analyzer/features/bankruptcy_simulation.py` | Fleet-shared (Pattern B, logic extracted) | PIA main() emit loop |
| `fresh_slotlab/round_classification.py` | Fleet-shared (BCM cycle / wild-nudge detection) | parser.py, PIA (direct import for `_wild_nudge_st_set` pass) |
| `fresh_slotlab/round_win.py` | Fleet-shared (per-machine win extraction rules) | parser.py, trigger_sessions.py |
| `fresh_slotlab/trigger_sessions.py` | Fleet-shared (session attribution) | parser.py |
| `fresh_slotlab/machine_md5.py` | Fleet-shared | PIA main() (stamp md5 on report) |
| `configs/bcm_pairings.json` | Per-machine config (consumed fleet-wide) | `_load_bcm_pairings()` at `pia:441`, called twice in main |
| `configs/machine_round_win_rules.json` | Per-machine config (consumed fleet-wide) | PIA main() `load_rules_for_machine()` at `pia:1121` |
| `slot_designer/configs/machine_manifests/*.json` (419 files) | Per-machine | manifest_loader.py → versioning.py + integrity gate |
| Block F1: `spin_type_rows`, `_st_behavior` | Per-run intermediate | F2 (`_st_behavior`), F3 (`_st_label`), F4 (`_st_label`) |
| Block F3+F4: `_st_label` | Per-run intermediate | F3, F4 — shared cross-block dependency |
| Block F5: `feature_to_spin_type`, `spin_type_to_feature` | Per-run intermediate | F5 (upstream_feature rows), F9 (`collect_mechanic` uses `_bcm_bonus_feature` which derives from same mapping) |

---

## §4 Pattern-A/B Plugin Presence vs Inline Blocks

### Current plugin coverage

| Summary key | In-scope per brief §2 | Plugin present? | Pattern | What plugin does |
|------------|----------------------|-----------------|---------|-----------------|
| `payouts_by_spin_type` | Yes | `payouts_by_spin_type.py` | A | no-op assert only |
| `payout_ids_top20` | Yes (via F2) | No plugin | — | 100% inline F2 |
| `payout_groups_top20` | Yes | No plugin | — | 100% inline F2b |
| `reel_marginal_by_spin_type` | Yes | `reel_marginal_by_spin_type.py` | A | no-op assert only |
| `multiplier_profile` | Yes | `multiplier_profile.py` | A | no-op assert only |
| `bankruptcy_simulation` | Yes | `bankruptcy_simulation.py` | B | full emit logic |
| `machine_mechanics` | Yes | No plugin | — | 100% inline F8 |
| `collect_mechanic` | Yes | No plugin | — | 100% inline F9 |
| `bonus_chain_dynamics` | Yes | No plugin | — | 100% inline F6 |
| `upstream_feature_breakdown` | Yes | No plugin | — | 100% inline F5 (~440 lines) |

**Summary**: 4 plugins registered, 3 are Pattern A no-ops, 1 is Pattern B with real logic. The 6 most complex blocks (`machine_mechanics`, `collect_mechanic`, `bonus_chain_dynamics`, `upstream_feature_breakdown`, `payout_ids_top20`, `payout_groups_top20`) have zero plugin presence.

---

## §5 The 8 Gaps — Root Cause Traces

### Gap #1: `machine_mechanics.jackpot.applicable: false`

**Failing code**: `pia:4484` — `"applicable": total_jackpot_spins > 0`

**Population path**:
- `total_jackpot_spins` ← merge loop `pia:1950` ← `rec["jackpot_spins"]`
- `rec["jackpot_spins"]` ← `parser.py:656-1383` — increments only when `r.get("JackpotIds") or r.get("JackpotID")` is non-empty string

**M275 reality**: jackpot pids 27502/27503/27504 appear in `PayoutIdToWinAmount` (and therefore in `payout_id_win`), NOT in the `JackpotIds` raw field. The detector checks the wrong field.

**What has the correct answer**: `payout_ids_top20` contains pids 27502/27503/27504 with correct `rtp_contribution_pp`. `upstream_feature_breakdown` correctly attributes them. Neither panel is queried by Block F8.

**Root cause**: Block F8 is an independent detection module with no cross-reference to the payout attribution panels that already identified the jackpot pids correctly.

### Gap #2: `machine_mechanics.free_spin.applicable: false`

**Failing code**: `pia:4493` — `"applicable": total_freespin_chain_spins > 0`

**Population path**:
- `total_freespin_chain_spins` ← merge loop `pia:1954` ← `rec["freespin_chain_spins"]`
- `rec["freespin_chain_spins"]` ← `parser.py:663-1396` — increments only when `r.get("CurFreeSpin")` is a positive integer

**M275 reality**: 9090 freespin rounds exist (SpinType 126, `behavior_name="free"`). The freespin detection requires the `CurFreeSpin` raw field to be present and positive. If M275 uses `ReMarks="Freespin N/M..."` without setting `CurFreeSpin`, the counter stays 0.

**What has the correct answer**: `bonus_chain_dynamics.applicable: True`, `chain_count: 908`, `bonus_round_count: 9090`. `spin_type_breakdown` has ST126 as `behavior_name="free"` with 9090 spins. Neither is queried by Block F8.

**Root cause**: Same isolation pattern as Gap #1. F8's `free_spin` detector reads a different raw field path than the freespin evidence that other panels already have.

### Gap #3: pid 666 classified as `cat=paid dom_st=140`

**Failing code**: F2 block, `pia:3249-3257`

**Current behavior**: `_st_behavior.get(140, "mixed")` = `"paid"`, `dominant_share` ≈ 1.0 (829/829 hits are from ST140), so `category = "paid"`.

**Truth**: pid 666 is a scatter trigger marker with `win=0`, `hit_count=829`. Its inclusion in ST140's `payout_id_by_spin_type` is correct (it fires during paid spins), but the semantic interpretation "paid" is wrong — it should be "scatter_trigger" or `trigger_only=True`.

**Root cause**: The category logic in F2 (`pia:3249-3257`) maps `st_behavior="paid" AND dominant_share>=0.8` → `category="paid"` with no special handling for zero-win pids. The `upstream_feature_breakdown` correctly identifies trigger-only features via `trigger_only = feat_total_times > 0 and feat_total_win == 0.0` (`pia:3582`), but this predicate is not reused in F2's `payout_id_rows` assembly.

### Gap #4: wild2x/wild5x/wild10x not interpreted as multiplier values

**Status per brief §6**: paused fleet-wide since 2026-04. Two bugs unfixed. Out of scope for this carve analysis.

**What is currently computed**: `multiplier_profile.buckets` at `pia:4386` uses session-level return_x (win/bet) — it is NOT a per-symbol multiplier analysis. The wild multiplier interpretation is a separate inference that was paused.

### Gap #5: `payout_groups_top20` shows group 0 = 80% RTP

**Failing code**: F2b block (payout_group_rows assembly, around `pia:3430-3445`)

**Root cause**: There is no guard for "all PayoutGroupId values are 0 = no meaningful grouping". The block always builds a row for each observed group ID. For M275, every round has `PayoutGroupId=0`, so a single row covers all spins with `group_id=0, hit_count=89090, rtp_contribution_pp=80.13%`. The operator sees noise, not signal.

**What's needed**: A detector that distinguishes "group 0 is a real group used for classification" from "group 0 = sentinel for 'not grouped'". The distinction is not currently encoded anywhere in the pipeline.

### Gap #6: `bonus_cycle_correction.estimated_correction_pp: 0.0`

**Failing code**: `_compute_bonus_correction()` at `parser.py:274`, called at `pia:4700`

**Analysis**: In the M275 report, `robots_with_pending_cycle: 0` (all robots completed cycles cleanly within the sample). With 0 pending robots, `_compute_bonus_correction` returns 0.0 correctly by formula. The `clamp_warning` fires because `clamp_pending_robots_total > 0` (`pia:4638`), which counts robots with pending paid spins. These are different signals: a robot can have pending paid spins (toward the next cycle trigger) without having a partial cycle (cycle itself completed, but the sequence restarted). The correction formula needs robots with cycles that did NOT complete — if all robots did complete their cycles within the sample window, correction = 0 is correct.

**Open question**: does `all_final_cc_values` for M275 truly contain 0 robots with `fcc < cycle_length_median`? The report says `robots_with_pending_cycle: 0`. If so, the 0.0 correction may be mathematically correct for this specific sample, not a formula bug. The `clamp_warning` "80% pending" refers to paid spins, not cycle completion.

### Gap #7: `payouts_by_spin_type` missing shape/cols/paylines/notes

**Failing code**: F3 block, `pia:3331-3346`

**Current schema per row**: `payout_id, hit_count, hit_rate, total_win, avg_win_when_hit, rtp_contribution_pp`

**Missing fields**: `shape` (payline pattern), `cols` (which reel columns trigger), `paylines` (which paylines carry this pid), `notes` (e.g. "scatter trigger")

**Root cause**: These fields are display augmentations not yet implemented. The raw data to derive `paylines` is available (`payline_winning_symbols` at `parser.py:2104`), but the join between pid and paylines is not built in F3. The `shape` and `cols` fields would require additional per-round tracking (which payline positions triggered which pid).

### Gap #8: `payout_ids_top20` missing same fields

Same as Gap #7, applied to F2's row schema. F2 and F3 share the same base row schema (`pia:3258-3289` for F2, `pia:3331-3346` for F3). Neither has the augmentation fields.

---

## §6 `parse_state` Contract: Current vs Needed

### Current contract

`AnalyzerFeature.extract(parse_state, chunk_dict)` is the ABC interface (`_base.py:119`).

**Current wiring** (`pia:4831`):
```python
for _feature in ALL_FEATURES:
    _feature.emit(None, summary)    # parse_state=None, no extract() call at all
```

`extract()` is never called by main(). The entire feature lifecycle is:
1. Feature imports fire `register()` calls (module import side effect)
2. main() calls `_feature.emit(None, summary)` once after all chunks

**What `parse_state` was intended to carry** (per `_base.py:127-134`): the current parser state — i.e., a per-round snapshot. This was designed for Wave 2d where extract() would be called once per round to accumulate feature-specific data.

**Current state**: the `parse_state` parameter does nothing. All 4 plugins use no-op `extract()` → `return {}`. The chunk-level accumulation is entirely in main()'s merge loop and the finalization blocks.

### What `parse_state` would need for a true carve

For a Plugin B carve of blocks F5/F8/F9, `extract()` would need to be called in `parse_chunk_response` or in main()'s merge loop. The "parse_state" that would be needed per round:
- `r` (the raw round dict) — or at minimum the derived fields: `spin_type`, `win_amt`, `payouts`, `is_cycle_peak`, `fs_meta`
- The chunk-level accumulators (to fold into)

This is currently not architected. There is no `parse_state` object flowing anywhere in the codebase.

---

## §7 Cross-File Dependencies That Block a Clean Carve

### Dependency A: `_st_label` bridges F3 and F4

`_st_label` is defined at `pia:3302-3305` from `spin_type_rows` (Block F1). Both F3 (payouts_by_spin_type) and F4 (reel_marginal_by_spin_type) iterate over `_st_label`. Moving F3 into a plugin without moving F4 (or vice versa) requires `_st_label` to be accessible to the remaining inline block. If both move into separate plugins, `_st_label` must be computed in a shared pre-processing step or serialized between plugins via the `REQUIRES` classvar mechanism.

### Dependency B: `_st_behavior` bridges F1 and F2

`_st_behavior` (`pia:3219-3222`) is derived from F1's `spin_type_rows`. F2 (payout_id_rows) reads it. Moving F2 into a plugin requires F1 to run first and its output accessible.

### Dependency C: `_bcm_bonus_feature` bridges F5 and F9

`_bcm_bonus_feature` and `_bcm_bonus_source` are computed at `pia:3478-3483` (in Block F5's setup). They feed into `collect_mechanic.bonus_cycle_correction` at `pia:4706-4708`. Moving either block into a plugin requires this shared computation to run first. Currently `_resolve_bonus_feature()` is called twice — once at `pia:3478` (F5 setup) and again at `pia:4706` and `pia:4718` (F9). Refactoring to compute once would require coordination.

### Dependency D: `feature_to_spin_type` / `spin_type_to_feature` bridges F5 and F6

Block F5 (upstream_feature_breakdown) computes `feature_to_spin_type` at `pia:3447`. Block F6 (bonus_chain_dynamics) uses `spin_type_to_feature` at `pia:3501` to categorize `chain_chunk_summaries` entries. Moving F5 into a plugin without F6 leaves `_sub_stream_acc` without its feature-lookup context.

### Dependency E: `effective_bet_for_rtp` is a pre-computed shared denominator

`effective_bet_for_rtp` is computed at approximately `pia:2880-2950` (trigger_sessions section, before the finalization blocks). It is read by F2, F3, F4, F5, F6, F8, F9 — every panel that computes `rtp_contribution_pp`. Moving any block into a plugin requires `effective_bet_for_rtp` to be in the summary dict or passed in another way.

### Dependency F: `bankruptcy_rows` is used both pre- and post-summary

`bankruptcy_rows` is built at `pia:4006-4051` (Block F7), used for `x100_br / x200_br / x500_br` local variables at `pia:4151-4153`, then passed to `summary["_bankruptcy_rows"]` at `pia:4811` for `BankruptcySimulation.emit()` to consume. The temp-key pattern (`_bankruptcy_rows`) is the workaround for this pre/post ordering. This same pattern would be needed for other blocks with pre-summary data dependencies.

### Dependency G: `payout_id_win` (chunk accumulator) is read by both F2 and F3

F2 and F3 both iterate `payout_id_win.items()` as the primary source of pid-level win data. Carving either into a separate plugin would require access to this cross-chunk accumulator — it cannot live inside either plugin's own `reduce()` state without replicating the same dict structure.

---

## §8 Reuse vs Duplication Audit

### Duplication finding 1: Merge block duplicated between `--from-cache` and online path

The source comment at `pia:1606-1612` explicitly acknowledges this:
> "We must replicate the merge here because the online loop is inside a while-block we skip. A helper would be cleaner but duplicating keeps the diff small."

The merge block appears at `pia:1614-1963` (from-cache) and again inside the online sampling while loop starting at approximately `pia:2620-2960` (online path). Both blocks are byte-for-byte identical merge logic. The `core/aggregator.py` module was created to hold aggregation helpers but the merge loop was not moved there.

### Duplication finding 2: `_resolve_bonus_feature()` called three times

`_resolve_bonus_feature(args.machine, args.rtp_mode, upstream_feature_tally, _load_bcm_pairings())` is called:
1. `pia:3478-3483` — to set `_bcm_bonus_feature/_bcm_bonus_source` for F5
2. `pia:4706-4708` — for `bonus_cycle_correction` computation in F9
3. `pia:4717-4719` — for `feature_match` in F9

The last two are in a lambda immediately following one another. The first is in a separate block 1200+ lines earlier. All three call `_load_bcm_pairings()` which reads `configs/bcm_pairings.json` from disk each time.

### Duplication finding 3: `parse_state=None` passed to `extract()` that is never called

`_feature.emit(None, summary)` is called but `extract()` and `reduce()` are never invoked. The plugin lifecycle is partial — only `emit()` runs. The `parse_state` parameter in `extract(parse_state, chunk_dict)` is dead in all 4 current plugins.

### Duplication finding 4: Feature module imports at module top AND in main()

Feature modules are imported in `versioning.py:163-175` (to ensure `register()` fires before `ALL_FEATURES` is read) and again inside `main()` at `pia:4816-4827`. The dual import is idempotent (Python module cache) but redundant.

### Reuse confirmed: `build_multiplier_bucket_rows()` shared between aggregate and per-feature

`build_multiplier_bucket_rows()` (re-exported from `aggregator.py`) is called:
- `pia:~3080` — for the global `multiplier_bucket_rows` aggregate
- `pia:3718` — for per-feature bucket rows in F5
- `pia:3790` — for per-path bucket rows in F5's sub-stream split

This is correct reuse.

### Reuse confirmed: `effective_bet_for_rtp` used as single denominator across 6+ blocks

All `rtp_contribution_pp` computations across F2, F3, F4, F5, F6, F8, F9 use the same `effective_bet_for_rtp` value. This is correct shared denominator discipline.

---

## §9 M275 Manifest State

`slot_designer/configs/machine_manifests/M275.json`:

```json
{
  "machine_id": "M275",
  "console_diagnostic_complete": false,
  "spin_type_convention": {"paid": [1], "bonus": []},
  "analyzer_features": [
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "bankruptcy_simulation",
    "multiplier_profile"
  ],
  "rtp_integrity_contract": {
    "required_attribution_anchors": [],
    "expected_paid_st": [1],
    "expected_bonus_st": []
  },
  "_generator_notes": {"config_not_reviewed": true, ...}
}
```

**Critical observation**: `spin_type_convention.paid: [1]` but M275's actual paid SpinType is 140, free is 126. The bootstrap generator set `paid: [1]` by default. The manifest is unreviewed (`config_not_reviewed: true`). This means:
- The RTP integrity gate's Layer 4 check uses `expected_paid_st: [1]`, which will mismatch M275's actual ST=140 behavior
- The manifest does not declare `BCM` or any mechanism-specific features — all mechanism plugins that might exist post-carve would need this manifest updated

---

## §10 Open Questions

1. **parse_state contract**: The `AnalyzerFeature.extract(parse_state, chunk_dict)` signature was designed for per-round extraction, but `parse_state` has never been wired — it is `None` at the only call site (`pia:4831`) and `extract()` is never called. For Pattern B carves that need per-round data, what is the wiring plan: call `extract()` inside `parse_chunk_response`? Inside the merge loop in `main()`? The current plugin lifecycle only exercises `emit()`. The designer must decide where in the pipeline `extract()` fires.

2. **`collect_mechanic.estimated_correction_pp = 0.0` — formula vs data**: The report shows `robots_with_pending_cycle: 0`, making 0.0 correction mathematically correct given the sample. But `clamp_warning` shows 80% pending paid spins. Are these two measures compatible or contradictory? If all cycle peaks were observed (64 complete cycles, all robots finished their cycles), why does clamp_warning fire? The mechanism connecting "paid spins toward next cycle" and "pending cycle" is unclear from reading the code alone. This may not be a gap but a correct output from an ambiguous sample.

3. **`_st_label` shared intermediate**: F3 and F4 both need `_st_label` derived from F1's `spin_type_rows`. If F3, F4, or both move to plugins, how does `_st_label` get from F1 into the plugin? Options: (a) F1 also becomes a plugin and writes `_st_label` to summary as a temp key; (b) F3/F4 plugins re-derive it from `spin_type_breakdown` which F1 writes to summary; (c) `_st_label` is a shared pre-computed dict passed via the summary temp-key pattern. The current `BankruptcySimulation` temp-key pattern is the only working precedent.

4. **Jackpot/freespin detection for M275**: The `JackpotIds` raw field is not set for M275's jackpot pids. What raw field signals the jackpot trigger for M275? If it's purely inferred from `PayoutIdToWinAmount` containing pids in a "known jackpot range", what defines that range? Is the mapping between pay_id → mechanic type a manifest-declared contract or must it be inferred from the win distribution? The brief lists this as gap #1/#2 but does not specify the correct detection mechanism for M275.

5. **payout_groups_top20 "group 0 = no grouping" distinction**: Is there a reliable signal in the raw data for "this machine uses PayoutGroupId=0 as a sentinel" vs "this machine actually has a group 0 with semantic meaning"? If the only signal is that all rounds have group_id=0, the detector needs a threshold (e.g. "if >99% of rounds are group 0, flag as no-grouping"). The designer must define this threshold.

6. **`_load_bcm_pairings()` read-thrice pattern**: If F5 and F9 both move to plugins, the BCM pairings config would be read in F5's plugin and again in F9's plugin (since they each call `_resolve_bonus_feature()` independently). Is the manifest the right place to declare BCM pairing (eliminating the external `configs/bcm_pairings.json` dependency for manifested machines)?

7. **Hash composition gap for non-core files**: `round_classification.py`, `round_win.py`, `trigger_sessions.py` are not hashed into `effective_analyzer_version`. Changes to these files invalidate reports but the hash does not reflect it — only the legacy `analyzer_version` (which hashes `player_impact_analyzer.py`) would change if PIA imports them (and any edit to their code would require PIA re-import to trigger hash change). Should these files be part of the hash composition?

8. **Manifest `spin_type_convention` vs actual behavior for M275**: The manifest declares `paid: [1]` but the machine uses ST=140 as paid and ST=126 as free. This is a pre-existing bootstrap error. For the "mechanism portrait" goal, the manifest needs to declare the correct SpinType set. Post-carve, which component writes the corrected values back to the manifest, and what is the carve/verification workflow for this?
