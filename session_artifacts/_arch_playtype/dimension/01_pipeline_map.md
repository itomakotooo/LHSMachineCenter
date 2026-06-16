# Dimension Framework — Pipeline Map

**Purpose:** End-to-end inventory of every per-ST metric the console currently
shows, tracing the data journey from rawdata round to rendered HTML. This map
defines the surface that must become dimension-aware.

Generated 2026-06-15 from code inspection (branch `claude/playtype-rearch`).

---

## 1. Scope and Entry Points

**Pipeline:** rawdata chunks → parser → per-chunk record → aggregator (report_engine) →
plugin feature emit → `player_impact_summary.json` → HTTP GET → frontend renderer

**Entry point:** `report_engine.generate_report_from_chunks()`
(`fresh_slotlab/analyzer/report_engine.py:400–~1900`)

**Machines in scope:** M15 (st1/st14/st15), M43 (st1/st50/st51), M279 (st140/st36/st2),
M275 (st140/st126). All confirmed (`validation.status: confirmed`).

**Manifest root:** `configs/machine_manifests/<M>.json`
— SpinType-native schema, loaded by `machine_spec.load_manifest()` (`machine_spec.py:243`).

**Analysis derivation:** `machine_spec.derive_analyses(manifest)` (`machine_spec.py:112`)
= `CROSS_CUTTING` + `PER_SPINTYPE` + `ROLE_ANALYSES[role]` + `PLAY_ANALYSES[play]`
for all roles/plays present in `spin_types`.

---

## 2. Layer-by-Layer Flow

### Layer 0 — Manifest Load and Analysis Selection

| Step | Location | Input | Output |
|------|----------|-------|--------|
| `load_manifest(machine_id)` | `machine_spec.py:243` | `configs/machine_manifests/<M>.json` | `manifest: dict` |
| `derive_analyses(manifest)` | `machine_spec.py:112` | manifest | `analysis_set: list[str]` — which plugin IDs run |
| `get_features_for_machine()` | `report_engine.py:496-497` | analysis_set | `_machine_features: list[AnalyzerFeature]` |
| `get_extractors_for_manifest(manifest)` | `report_engine.py:504`, `st_extract/__init__.py:136` | manifest spin_types blocks containing `"trigger_paths"` key | `_st_extractors: list[STExtractor]` (empty if no ST declares trigger_paths) |

**Key:** a machine's `spin_types[st]["trigger_paths"]` key activates `TriggerPathExtractor`;
all other ST fields are opaque to the extractor framework. Only M275 currently has
`trigger_paths` declared (`configs/machine_manifests/M275.json:22-30`).

---

### Layer 1 — Per-Chunk Parsing (`parse_chunk_response`)

**Location:** `fresh_slotlab/analyzer/core/parser.py:487`

Called once per chunk file from `report_engine.py:722-728`:
```python
rec = parse_chunk_response(resp, idx, chunk_bet_val,
    round_win_rules=_round_win_rules,
    st_extractors=_st_extractors)
```

#### ST-keyed accumulators (the complete set — ALL keyed by `sp_type: int`, NOT by dimension)

| Accumulator | Type | Lines | What it counts |
|-------------|------|-------|----------------|
| `spin_type_spins` | `dict[int, int]` | parser.py:840,1797 | rounds per ST |
| `spin_type_bet` | `dict[int, float]` | parser.py:841,1800 | total BetAmount per ST |
| `spin_type_paid_bet` | `dict[int, float]` | parser.py:842,1800 | CostCredits>0 sum per ST |
| `spin_type_paid_rounds` | `dict[int, int]` | parser.py:845,1801 | is_paid==True count per ST |
| `spin_type_win` | `dict[int, float]` | parser.py:843,1802 | total win per ST |
| `spin_type_wins` | `dict[int, int]` | parser.py:844,1803 | winning-round count per ST |
| `spin_type_next_counts` | `dict[int, Counter]` | parser.py:852,1897 | ST→ST transition tally |
| `spin_type_remarks_sample` | `dict[int, list[str]]` | parser.py:859,1903-1910 | sample ReMarks strings per ST (up to 3) |
| `spin_type_bucket_spins` | `dict[int, dict[str, int]]` | parser.py:886,1814 | all-round return-bucket counts per ST |
| `spin_type_bucket_bet` | `dict[int, dict[str, float]]` | parser.py:889,1815 | return-bucket bet per ST |
| `spin_type_bucket_win` | `dict[int, dict[str, float]]` | parser.py:892,1816 | return-bucket win per ST |
| `spin_type_paid_bucket_spins` | `dict[int, dict[str, int]]` | parser.py:900,1824 | paid-only return-bucket counts per ST |
| `spin_type_paid_bucket_bet` | `dict[int, dict[str, float]]` | parser.py:903,1825 | paid-only bucket bet per ST |
| `spin_type_paid_bucket_win` | `dict[int, dict[str, float]]` | parser.py:906,1826 | paid-only bucket win per ST |
| `spin_type_nudge_round_count` | `dict[int, int]` | parser.py:869,1810 | wild-nudge rounds per ST |
| `payout_id_by_spin_type` | `dict[str, dict[int, int]]` | parser.py:806,1xxx | (pid, ST) hit counts |
| `payout_id_win_by_spin_type` | `dict[str, dict[int, float]]` | parser.py:813,1434 | (pid, ST) win amounts |
| `session_bucket_spins_by_settlement_st` | `dict[int, dict[str, int]]` | parser.py:921,1365 | session-level bucket by settlement ST |
| `session_bucket_bet_by_settlement_st` | `dict[int, dict[str, float]]` | parser.py:924,1366 | session-level bucket bet by settlement ST |
| `session_bucket_win_by_settlement_st` | `dict[int, dict[str, float]]` | parser.py:927,1367 | session-level bucket win by settlement ST |
| `symbol_counts_by_col_by_spin_type` | `dict[int, dict[int, dict[str, int]]]` | parser.py:819,~1830 | symbol×column counts per ST |
| `payout_id_payline_hits` | `dict[str, dict[str, int]]` | parser.py:1011 | per-pid per-payline hit counts |
| `payout_id_match_count_dist` | `dict[str, dict[int, int]]` | parser.py:1012 | per-pid n-of-a-kind distribution |
| `payout_id_col_set` | `dict[str, set[int]]` | parser.py:1013 | per-pid column set |
| `payout_id_symbol_combos` | `dict[str, dict[str, int]]` | parser.py:1025 | per-pid symbol combo histogram |
| `chain_chunk_summaries` | `dict[tuple, dict]` | parser.py:874,1883 | chain trigger-path stats keyed by `(first_st, entry_cc_reset, sp_type)` |
| `chain_bucket_spins/bet/win` | `dict[tuple, dict[str, int/float]]` | parser.py:936-944,1891-1893 | return-bucket per chain path |

**Key observation:** every accumulator above is keyed by `sp_type` (SpinType integer)
only — NOT by `(sp_type, trigger_path_label)`. The only exception is `chain_chunk_summaries`
and `chain_bucket_*` which are keyed by `(first_st, entry_cc_reset, sp_type_within_chain)` —
a coarse proxy for trigger path, not the declarative `trigger_paths` dimension.

#### STExtractor hook (the one partial per-path path)

The `_active_st_extractors` loop (`parser.py:1182-1292`) runs alongside the main round loop:
- `begin_robot(robot_ctx)` called per robot (`parser.py:1285-1292`)
- `observe_round(round_dict, spin_type, round_ctx)` called per round (`parser.py:~2100-2130` — in the main round loop after per-SpinType accumulators are updated)
- `finalize_chunk()` called after the robot loop (`parser.py:~2300`)

The round_ctx passed to `observe_round` includes:
```
{
  "robot_idx": int,
  "round_idx": int,
  "session": dict | None,        # trigger session record for this round
  "bet": int,
  "win": float,                  # rule-view win (extract_round_win result)
  "last_paid_round": dict | None,
  "block_id": int | None,
}
```
(`_base.py:112-150`)

The extractor result lands in `rec["st_extract"]["trigger_path"]` keyed by `{st_str: {path_label: {round_count, win_sum, session_count, win_band_hist}}}`.
(`trigger_path.py:289-299`)

This is the ONLY per-round accumulation keyed by `(ST, path_label)`. It currently
accumulates: `round_count`, `win_sum`, `session_count`, `win_band_hist`.
It does NOT accumulate: hit_rate, cadence, uplift, FS arc, ER ladder, multiplier
distribution, payid mix, mean/median/max — all of those are ST-only.

---

### Layer 2 — Report Engine Aggregation

**Location:** `report_engine.py:732–~1400`

After each `parse_chunk_response` call, the report engine merges the chunk record
into cross-chunk totals. All ST-keyed accumulators use the same ST-only key:

```python
# report_engine.py:637-657 (representative sample)
for sp_type in rec["spin_type_spins"]:
    spin_type_spins[sp_type] += rec["spin_type_spins"][sp_type]
    spin_type_bet[sp_type] += rec["spin_type_bet"][sp_type]
    spin_type_win[sp_type] += rec["spin_type_win"][sp_type]
    spin_type_bucket_spins[sp_type].update(rec["spin_type_bucket_spins"][sp_type])
    # ... etc.
```

The `rec["st_extract"]` dict is passed through to the feature plugins via the
chunk_dict argument in `extract()` — it is NOT separately aggregated by the report
engine. Each plugin's `extract()` reads `chunk_dict["st_extract"]["trigger_path"]`
and `reduce()` accumulates across chunks.

---

### Layer 3 — Finalization and Inline Summary Construction

**Location:** `report_engine.py:~1400–~1800`

Before the plugin emit loop, the report engine builds several inline summary keys
including `player_impact.spin_type_breakdown` (the per-ST row table that all plugins
read). These rows are keyed by ST integer only and carry:
```
{spin_type, spins, win_rounds, hit_rate, rtp_contribution_pp, behavior_name,
 total_win, total_bet, feature_name, feature_trigger_only, feature_rtp_pp, ...}
```

**The `spin_type_breakdown` row IS the axis for all per-ST plugin output.** Its label
`f"ST{st_int}_{behavior_name}"` (e.g. `"ST126_free"`) is the shared key used by
`payouts_by_spin_type`, `spin_type_outcomes`, `spin_type_rtp_buckets`, and
`reel_marginal_by_spin_type` to emit their per-ST dicts. The label does NOT include
a path/dimension component.

---

### Layer 4 — Plugin Feature Emit Loop

**Location:** `report_engine.py:~1800–~1900` (topo-sorted emit)

**Emit order** (determined by `REQUIRES` dependencies via topo-sort):
1. `payouts_by_spin_type` (has no REQUIRES)
2. `spin_type_outcomes` (REQUIRES payouts_by_spin_type)
3. `spin_type_rtp_buckets` (REQUIRES spin_type_outcomes)
4. `reel_marginal_by_spin_type` (REQUIRES none; reads `_reel_marginal_by_spin_type_data` stash)
5. `freespin_dynamics` (REQUIRES payouts_by_spin_type, bonus_chain_dynamics)
6. All other CROSS_CUTTING and ROLE/PLAY plugins

---

## 3. Per-Plugin Metric Inventory

### 3A. Generic Per-ST Plugins (PER_SPINTYPE group)

These four plugins run for every machine via `PER_SPINTYPE` in `machine_spec.py:69-75`.

---

#### `payouts_by_spin_type`
**File:** `fresh_slotlab/analyzer/features/payouts_by_spin_type.py`
**Hook:** `PER_SPINTYPE` (machine_spec.py:70)

**extract() reads from chunk_dict:**
- `chunk_dict["payout_id_by_spin_type"]` — `{pid_str: {st_int: hit_count}}` (parser.py:806)
- `chunk_dict["payout_id_win_by_spin_type"]` — `{pid_str: {st_int: win_float}}` (parser.py:813)
- `chunk_dict["payout_id_payline_hits"]` — per-pid payline hit counts (parser.py:1011)
- `chunk_dict["payout_id_match_count_dist"]` — n-of-a-kind distribution (parser.py:1012)
- `chunk_dict["payout_id_col_set"]` — columns covered per pid (parser.py:1013)
- `chunk_dict["payout_id_has_regular_line"]` — scatter vs line flag (parser.py:1018)
- `chunk_dict["payout_id_symbol_combos"]` — symbol combo histogram (parser.py:1025)

**Accumulator keyed by:** `(pid_str, st_int)` — NOT `(pid_str, st_int, path_label)`

**emit() reads:**
- `summary["player_impact"]["spin_type_breakdown"]` — for ST labels and spins counts

**emit() writes:**
- `summary["player_impact"]["payouts_by_spin_type"]`
  keyed by ST label (e.g. `"ST126_free"`):
  ```
  {
    "ST126_free": [
      {payout_id, hit_count, avg_win_when_hit, rtp_contribution_pp,
       covered_columns, shape, paylines, notes, symbol_combo: {dominant, combos}},
      ...
    ]
  }
  ```

**Key:** Output is `{ST_label: [payid_rows]}`. A single ST's payid rows are NOT split
by trigger path. The `rtp_contribution_pp` per payid for a freespin ST aggregates ALL
trigger paths together.

---

#### `spin_type_outcomes`
**File:** `fresh_slotlab/analyzer/features/spin_type_outcomes.py`
**Hook:** `PER_SPINTYPE` (machine_spec.py:71)
**REQUIRES:** `payouts_by_spin_type`

**extract():** no-op (returns `{}`)
**reduce():** no-op

**emit() reads:**
- `summary["player_impact"]["payouts_by_spin_type"]` (declared REQUIRES dependency)
- `summary["player_impact"]["spin_type_breakdown"]`
- `summary["sampling"]["bet"]`

**emit() writes:**
- `summary["player_impact"]["spin_type_outcomes"]`
  keyed by ST label:
  ```
  {
    "ST126_free": {
      spin_type, label,
      dead_spin_rate, hit_rate, avg_win_when_hit, rtp_contribution_pp,  # round-level from stb
      win_bands: [{band, lo, hi, hit_count, rtp_pp}],   # payline-level, 6 bands
      top_combos: [{payout_id, combo, mult, hit_count, rtp_pp, covered_columns}],  # top 5
      max_mult, pct_small_hits, pct_big_hits, has_payouts, round_stats_available
    }
  }
  ```

**Key:** All fields aggregate ALL rounds of that ST regardless of trigger path.
`hit_rate`, `avg_win_when_hit`, `win_bands`, `top_combos`, `max_mult` — all
ST-only, zero path awareness.

---

#### `spin_type_rtp_buckets`
**File:** `fresh_slotlab/analyzer/features/spin_type_rtp_buckets.py`
**Hook:** `PER_SPINTYPE` (machine_spec.py:72)
**REQUIRES:** `spin_type_outcomes`

**extract() reads from chunk_dict:**
- `chunk_dict["spin_type_rtp_buckets"]` (= `spin_type_paid_bucket_{spins,bet,win}` from parser)
  keyed by `str(st_int)` → `{bucket_label: {spins, bet, win}}`

**Accumulator keyed by:** `(str(st_int), bucket_label)` — NOT `(st, path_label, bucket_label)`

**emit() reads:**
- `final_acc["by_st"]` — accumulated per-ST paid-round bucket data
- `summary["player_impact"]["spin_type_breakdown"]` — for labels and paid round counts

**emit() writes:**
- `summary["player_impact"]["spin_type_rtp_buckets"]`
  keyed by ST label:
  ```
  {
    "ST1_paid": [
      {bucket, spin_count, spin_rate, avg_return_x_in_bucket,
       rtp_contribution_pp, win_share},
      ...  # 11 rows in RETURN_BUCKET_ORDER
    ]
  }
  ```
  NOTE: Free-spin STs (paid_rounds==0) are silently omitted from the output —
  `spin_type_rtp_buckets` only covers paid STs. M275 ST126 (freespin) does NOT
  appear here by design.

**Key:** Each ST's bucket row aggregates ALL paid rounds of that ST regardless of
trigger path. On a pure-paid ST this is unambiguous. On M275 ST126 it is moot
(no paid rounds). But IF a future machine has a paid ST with two trigger paths,
the bucket distribution would aggregate both paths into one histogram.

---

#### `reel_marginal_by_spin_type`
**File:** `fresh_slotlab/analyzer/features/reel_marginal_by_spin_type.py`
**Hook:** `PER_SPINTYPE` (machine_spec.py:73)
**DECLARED_DEPS:** `_reel_marginal_by_spin_type_data` stash (written by report_engine inline block)

**extract():** no-op (reads from stash, not chunk_dict)

**emit() reads:**
- `summary["_reel_marginal_by_spin_type_data"]` stash:
  `symbol_counts_by_col_by_spin_type_total` — `{st_int: {col_int: {symbol: count}}}`
  (aggregated from parser's `symbol_counts_by_col_by_spin_type`, parser.py:819)
- `summary["player_impact"]["spin_type_breakdown"]` — for ST labels

**emit() writes:**
- `summary["player_impact"]["reel_marginal_by_spin_type"]`
  keyed by ST label:
  ```
  {
    "ST126_free": {
      "col_0": [{"symbol": "Bar", "count": int, "prob_pct": float}, ...],
      "col_1": [...],
      ...
    }
  }
  ```

**Key:** Symbol distributions per column per ST. NOT split by trigger path. M275 ST126
freespin rounds from both scatter and collect_peak paths are merged into a single symbol
distribution per column. If the two paths have different board configurations or skin
distributions, this masks the difference.

---

### 3B. Role/Play Plugin: `topdollar_choice`
**File:** `fresh_slotlab/analyzer/features/topdollar_choice.py`
**Hook:** `ROLE_ANALYSES["player_choice"]` (machine_spec.py:88) — fires for M15

**extract() reads from chunk_dict:**
- `chunk_dict["topdollar_sessions"]` — list of per-session dicts assembled in parser.py:1436-1499
  Shape: `{n_picks, offers, dollar_counts, chosen, settled_win}`

**Accumulator:** aggregated across sessions — picks_per_session histogram, dollar_tier_counts,
chosen_combo_counts, total_mult_buckets, total_mult_median/max

**emit() writes:**
- `summary["topdollar_choice"]` (top-level, not under `player_impact`):
  ```
  {applicable, total_sessions, trigger_rate, stopped_early_rate, forced_4th_rate,
   bad_gamble_rate, picks_per_session, dollar_tier_counts, chosen_combo_counts,
   total_mult_buckets, total_mult_median, total_mult_max, feature_name}
  ```

**Key:** Aggregates ALL TopDollar sessions regardless of trigger path. M15 has only
one trigger path (scatter pid 666), so this is currently unambiguous.

---

### 3C. Role Plugin: `respin_dynamics`
**File:** `fresh_slotlab/analyzer/features/respin_dynamics.py`
**Hook:** `ROLE_ANALYSES["respin"]` (machine_spec.py:89) — fires for M43 (ST50), M279 (ST36)

**extract() reads from chunk_dict:**
- `chunk_dict["spin_type_next_counts"]` — ST→ST transition tally (parser.py:852)
- `chunk_dict["spin_type_bucket_spins"]` — per-ST return-bucket spins (parser.py:886)
- `chunk_dict["spin_type_bucket_win"]` — per-ST return-bucket win (parser.py:892)

All three are keyed by ST integer only.

**emit() reads:**
- `summary["player_impact"]["spin_type_breakdown"]` — for hit_rate, rtp_contribution_pp
- `summary["player_impact"]["payouts_by_spin_type"]` — for payid mix

**emit() writes:**
- `summary["player_impact"]["respin_dynamics"]`:
  ```
  {applicable, respin_spin_type, base_spin_type,
   grant_rate: {openers, per_winning_paid_spin, per_paid_spin, one_per_n_paid_spins},
   hit_rate_uplift: {respin_hit_rate, base_hit_rate, uplift_ratio},
   respin_multiplier_distribution: {total_spins, win_rounds, bands, tail_ge20x_*},
   base_multiplier_distribution: {...},
   payid_mix: {respin_payid_share, base_payid_share},
   continuity: {continuation_prob, respin_to_respin_transitions, ...},
   rtp_concentration: {...}}
  ```

**Key:** All metrics aggregate all respin rounds together. M279 ST36 (MoveSpin) has one
trigger path today (win-gated paid-spin extension); M43 ST50 (WinRespin) also has one.
No trigger_paths dimension in their manifests. If a future machine had two trigger paths
into the same respin ST, all of these metrics (grant_rate, uplift, distribution, payid_mix)
would blend both paths into one view.

---

### 3D. Play Plugin: `minigame_dynamics`
**File:** `fresh_slotlab/analyzer/features/minigame_dynamics.py`
**Hook:** `PLAY_ANALYSES["WinMiniGame"]` (machine_spec.py:107) — fires for M43 (ST51)

**extract() reads from chunk_dict:**
- `chunk_dict["spin_type_next_counts"]` — ST→ST transition tally
- `chunk_dict["spin_type_bucket_spins"]`, `chunk_dict["spin_type_bucket_win"]`

All keyed by ST integer only.

**emit() reads:**
- `summary["player_impact"]["spin_type_breakdown"]`
- `summary["player_impact"]["payouts_by_spin_type"]`

**emit() writes:**
- `summary["player_impact"]["minigame_dynamics"]`:
  ```
  {applicable, minigame_spin_type, base_spin_type,
   multiplier_distribution: {total_events, modal_band, dominant_band_share, bands},
   trigger_frequency: {minigame_events, per_paid_spin, one_per_n_paid_spins},
   trigger_context: {opener_from_base_spin, share_from_base_spin, opener_from_respin_burst, ...},
   node_path_analysis: {parser_blind: [...]},
   rtp_concentration: {...}}
  ```

**Key:** Single trigger path (win from WinRespin burst or base spin). Not path-split.

---

### 3E. Play Plugin: `wheel_dynamics`
**File:** `fresh_slotlab/analyzer/features/wheel_dynamics.py`
**Hook:** `PLAY_ANALYSES["Wheel"]` (machine_spec.py:108) — fires for M279 (ST2)

**extract() reads from chunk_dict:**
- `chunk_dict["spin_type_next_counts"]`
- `chunk_dict["spin_type_bucket_spins"]`, `chunk_dict["spin_type_bucket_win"]`

All keyed by ST integer only.

**emit() reads:**
- `summary["player_impact"]["spin_type_breakdown"]`
- `summary["player_impact"]["payouts_by_spin_type"]`

**emit() writes:**
- `summary["player_impact"]["wheel_dynamics"]`:
  ```
  {applicable, wheel_spin_type, base_spin_type,
   guaranteed_payout: {events, hit_rate, one_per_n_paid_spins},
   prize_distribution: {total_events, modal_band, dominant_band_share, bands, parser_blind},
   cell_map: {wheel_cell_count, jackpot_cells, parser_blind},
   rtp_concentration: {...}}
  ```

**Key:** ST2 (Wheel) fires deterministically every 1000 paid spins (CollectCount==1000).
Single trigger path. Not path-split.

---

### 3F. Role Plugin: `freespin_dynamics` — the ONE PARTIAL per-path plugin
**File:** `fresh_slotlab/analyzer/features/freespin_dynamics.py`
**Hook:** `ROLE_ANALYSES["freespin"]` (machine_spec.py:90) — fires for M275 (ST126)
**REQUIRES:** `payouts_by_spin_type`, `bonus_chain_dynamics`

**extract() reads from chunk_dict:**
- `chunk_dict["spin_type_next_counts"]` — ST→ST tally (keyed by ST only)
- `chunk_dict["spin_type_bucket_spins"]` — per-ST bucket spins (keyed by ST only)
- `chunk_dict["spin_type_bucket_win"]` — per-ST bucket win (keyed by ST only)
- `chunk_dict["st_extract"]["trigger_path"]` — the per-path extractor output:
  `{str(st): {path_label: {round_count, win_sum, session_count, win_band_hist}}}`
  (freespin_dynamics.py:270-296)
- `chunk_dict["st_extract"]["_extract_error_trigger_path"]` — surfaced errors

**emit() reads:**
- `summary["player_impact"]["spin_type_breakdown"]` — for hit_rate, rtp_contribution_pp, total_win
- `summary["player_impact"]["payouts_by_spin_type"]` — for payid mix
- `summary["player_impact"]["bonus_chain_dynamics"]` — chain structure corroboration only

**emit() writes:**
- `summary["player_impact"]["freespin_dynamics"]`:
  ```
  {
    applicable, freespin_spin_type, base_spin_type,
    session_cadence: {openers, per_paid_spin, one_per_n_paid_spins, avg_block_length_rounds,
                      continuation: {...}, chain_structure_corroboration: {...}},
    hot_board_uplift: {freespin_hit_rate, base_hit_rate, uplift_ratio},
    freespin_multiplier_distribution: {total_spins, win_rounds, bands, tail_ge20x_*},
    base_multiplier_distribution: {...},
    payid_mix: {freespin_payid_share: {pid: {hit_count, hit_share, win_share}},
                base_payid_share: {...}},
    rtp_concentration: {freespin_rtp_contribution_pp, share_of_all_win,
                        fat_tail_ge20x_win_share, zero_win_round_rate},
    trigger_paths: {   # <-- THE ONE PATH-SPLIT SECTION
      available: bool,
      total_sessions: int,
      freespin_total_win_share_covered: float,
      paths: [
        {path, label, session_count, session_share, trigger_rate_per_paid_spin,
         one_per_n_paid_spins, round_count, win_share, rtp_contribution_pp_split,
         win_band_hist: [{band, round_count, prob}]},
        ...
      ],
      unknown_paths: [...],  # alarm semantics
      multi_buckets: [...],  # alarm semantics
    },
    parser_blind: [...]
  }
  ```

**Path-split coverage in trigger_paths section:** ONLY the following 4 stats per path:
`session_count`, `round_count`, `win_sum` (→ `win_share`, `rtp_contribution_pp_split`),
`win_band_hist`.

**NOT path-split** (all ST126-aggregate in freespin_dynamics):
- `session_cadence` (openers, per_paid_spin, avg_block_length, continuation_prob, exit_breakdown)
- `hot_board_uplift` (hit_rate, uplift_ratio)
- `freespin_multiplier_distribution` (bands, tail share)
- `payid_mix` (per-pid hit/win shares)
- `rtp_concentration` (rtp_pp, share_of_all_win, zero_win_round_rate)

---

### 3G. Cross-Cutting Plugins that Read Per-ST Data

#### `upstream_feature_breakdown`
**File:** `fresh_slotlab/analyzer/features/upstream_feature_breakdown.py`
**Hook:** `CROSS_CUTTING` (machine_spec.py:63)

**Reads from stash** `summary["_upstream_feature_breakdown_data"]` containing raw inputs:
- `spin_type_bucket_{spins,bet,win}` — per-ST multiplier histograms (keyed by ST)
- `chain_chunk_summaries` — keyed by `(first_st, entry_cc_reset, sp_type_within_chain)`
- `chain_bucket_{spins,bet,win}` — per-chain-path bucket histograms
- `session_bucket_{spins,bet,win}_by_settlement_st` — settlement-ST bucket fallback
- `spin_type_next_counts`, `spin_type_nudge_round_count`, `spin_type_spins`
- `upstream_feature_tally`, `feature_to_spin_type`, `spin_type_to_feature`

**emit() writes:**
- `summary["player_impact"]["upstream_feature_breakdown"]`:
  the per-feature rows with sub_streams (trigger-path split via the coarse
  `chain_chunk_summaries` key, NOT the declarative `trigger_paths` extractor):
  ```
  {applicable, source, features: [
    {feature_name, spin_type, rtp_contribution_pp, hit_rate, ...
     sub_streams: [{label, count, win, bet, ...}, ...],
     multiplier_bucket_rows: [{bucket, spin_count, ...}, ...]}
  ]}
  ```

**Key:** The `sub_streams` split uses the `chain_chunk_summaries` coarse mechanism
(`(first_st, entry_cc_reset, sp_type)` key). For M275, this produces `[via NormalCollectionSpin]`
vs `[via NewFreespin]` split labels — a heuristic based on prev-round pids, NOT the
GTT-discriminated trigger_paths data. The M275 manifest caveats note this explicitly:
"bonus_chain_dynamics.by_feature trigger-path labels use the prev-round-pids heuristic
(841/67 vs GTT truth 829/80)". The accurate split is the `trigger_paths` section
inside `freespin_dynamics`, not `upstream_feature_breakdown.sub_streams`.

---

#### `bonus_chain_dynamics`
**File:** `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py`
**Hook:** `CROSS_CUTTING` (machine_spec.py:64)

**Reads from stash** `summary["_bonus_chain_dynamics_data"]` which includes:
- `chunk_bonus_chain_lengths`, `chunk_bonus_chain_max_ratios` — global chain stats
- `chunk_chains_by_feature` — per-feature keyed by trigger_feature string
  (heuristic: "NormalCollectionSpin" vs "NewFreespin" from prev-round-pids detection at parser.py:1927-1931)

**emit() writes:**
- `summary["player_impact"]["bonus_chain_dynamics"]`:
  aggregated chain metrics — NOT the per-path split from `trigger_paths`

---

#### `collect_mechanic`
**File:** `fresh_slotlab/analyzer/features/collect_mechanic.py`
**Hook:** `CROSS_CUTTING` (machine_spec.py:64)

Reads `CollectCount`, `AccCredits`, cycle peaks. Keyed by ST-agnostic collect mechanics.
Not per-ST keyed; not per-path keyed.

---

#### `structure_drift`
**File:** `fresh_slotlab/analyzer/features/structure_drift.py`
**Hook:** `CROSS_CUTTING` (machine_spec.py:66)

**extract() reads from chunk_dict:**
- `chunk_dict["st_extract"]["signature_audit"]` — per-ST field presence counts
  (produced by a `signature_audit` STExtractor; check if that extractor is registered)

**emit() reads:**
- `ctx.machine_spec_manifest["spin_types"]` — to compare declared signature/observed_fields

**emit() writes:**
- `summary["structure_drift"]` (top-level, not under `player_impact`):
  `{status: ok|warn|fail|unaudited, reason, undeclared_sts, declared_sts_absent, per_st_audits}`

**Key:** Operates at the ST-field level, not at the per-path level.

---

## 4. player_impact_summary.json Schema — Per-ST Keys

The following keys in `player_impact_summary.json` contain per-ST data. All are
currently ST-keyed (not path-keyed):

| JSON key | Keyed by | Produced by | Consumed by frontend |
|----------|----------|-------------|----------------------|
| `player_impact.spin_type_breakdown` | ST label `"ST{n}_{behavior}"` | report_engine inline | `renderSpinTypeOutcomes`, `_stDimOverview` |
| `player_impact.payouts_by_spin_type` | ST label | `payouts_by_spin_type.emit()` | `_stDimPayid`, `_stDimSelectorChoice`, `_stDimSettlement`, `freespin_dynamics._payid_share` |
| `player_impact.spin_type_outcomes` | ST label | `spin_type_outcomes.emit()` | `renderSpinTypeOutcomes` (stCtx.outcome) |
| `player_impact.spin_type_rtp_buckets` | ST label | `spin_type_rtp_buckets.emit()` | `_stDimWinDistribution` (preferred path) |
| `player_impact.reel_marginal_by_spin_type` | ST label | `reel_marginal_by_spin_type.emit()` | `renderReelMarginalBySpinType` |
| `player_impact.respin_dynamics` | flat (respin_spin_type scalar) | `respin_dynamics.emit()` | `_stDimRespin` (checks `rd.respin_spin_type == stCtx.row.spin_type`) |
| `player_impact.minigame_dynamics` | flat (minigame_spin_type scalar) | `minigame_dynamics.emit()` | `_stDimMinigame` |
| `player_impact.wheel_dynamics` | flat (wheel_spin_type scalar) | `wheel_dynamics.emit()` | `_stDimWheel` |
| `player_impact.freespin_dynamics` | flat (freespin_spin_type scalar) + `trigger_paths.paths[]` (per path row) | `freespin_dynamics.emit()` | `_stDimFreespin` |
| `player_impact.upstream_feature_breakdown` | `features[]` list with sub_streams | `upstream_feature_breakdown.emit()` | `renderUpstreamFeatureBreakdown` |
| `topdollar_choice` | flat | `topdollar_choice.emit()` | `_stDimSelectorChoice`, `_stDimSettlement` |
| `structure_drift` | `per_st_audits[st_str]` | `structure_drift.emit()` | `renderStructureDriftPanel` |

---

## 5. Frontend Rendering — Per-ST Dimension Architecture

**File:** `src/web_console/frontend/app.js`

### ST Section Rendering Entry Point

`renderSpinTypeOutcomes(summary)` (app.js:5326) iterates `spin_type_breakdown` rows;
for each ST creates an `stCtx` and calls two render paths:

1. `_stDimOverview(stCtx)` — always present (app.js:5352)
2. For each dim in `SPINTYPE_DIMENSIONS`: `dim(stCtx)` (app.js:5356) — self-applies if data present

**`SPINTYPE_DIMENSIONS` (app.js:5315-5324):**
```javascript
const SPINTYPE_DIMENSIONS = [
  _stDimWinDistribution,    // app.js:4646 — reads spin_type_rtp_buckets[label]
  _stDimPayid,              // app.js:4719 — reads payouts_by_spin_type[label]
  _stDimSelectorChoice,     // app.js:4740 — reads topdollar_choice (trigger_only ST)
  _stDimSettlement,         // app.js:4751 — reads topdollar_choice (settlement ST)
  _stDimRespin,             // app.js:4766 — reads respin_dynamics (by respin_spin_type match)
  _stDimMinigame,           // app.js:4908 — reads minigame_dynamics (by minigame_spin_type match)
  _stDimWheel,              // app.js:5009 — reads wheel_dynamics (by wheel_spin_type match)
  _stDimFreespin,           // app.js:5100 — reads freespin_dynamics (by freespin_spin_type match)
];
```

### Key Frontend Rendering Details per Dimension

| Renderer | Data source key | Path-aware? | i18n prefix |
|----------|-----------------|-------------|-------------|
| `_stDimOverview` | `stCtx.row` (spin_type_breakdown) | No | `sto*` |
| `_stDimWinDistribution` | `spin_type_rtp_buckets[label]` (preferred) or `payouts_by_spin_type[label]` (fallback) | No | `sto*` |
| `_stDimPayid` | `payouts_by_spin_type[label]` | No | `sto*` |
| `_stDimSelectorChoice` | `summary.topdollar_choice` | No (whole feature) | `td*` |
| `_stDimSettlement` | `summary.topdollar_choice` | No | `td*` |
| `_stDimRespin` | `summary.player_impact.respin_dynamics` | No | `rd*` |
| `_stDimMinigame` | `summary.player_impact.minigame_dynamics` | No | `mg*` |
| `_stDimWheel` | `summary.player_impact.wheel_dynamics` | No | `wd*` |
| `_stDimFreespin` | `summary.player_impact.freespin_dynamics` | PARTIAL — only `trigger_paths` subsection | `fs*` |

### `_stDimFreespin` Path Table (the only rendered path split)

At app.js:5216-5291, when `fd.trigger_paths.available == true`:
- Renders a side-by-side table with one column per path
- Per-path metrics shown: `session_count`, `session_share`, `trigger_rate_per_paid_spin`,
  `one_per_n_paid_spins`, `round_count`, `win_share`, `rtp_contribution_pp_split`
- Per-path win_band_hist: rendered as a separate band table per path (app.js:5234-5255)
- Alarm rows for `unknown_paths` and `multi_buckets` (app.js:5257-5273)

Everything ELSE in `_stDimFreespin` (cadence, uplift, multiplier distribution, payid mix,
RTP concentration) is rendered from the ST-aggregate fields — no path split.

---

## 6. Shared vs Per-X Boundary Table

| File / Key | Scope | Consumers |
|------------|-------|-----------|
| `machine_spec.py` — `CROSS_CUTTING`, `PER_SPINTYPE`, `ROLE_ANALYSES`, `PLAY_ANALYSES` | fleet-shared framework | `report_engine`, `versioning` |
| `machine_spec.py` — `derive_analyses()` | fleet-shared | `report_engine.py:488` |
| `parser.py` — `spin_type_*` accumulators | fleet-shared closure | all feature plugins via chunk_dict |
| `parser.py` — `st_extractors` hook | fleet-shared framework + per-machine declared | `TriggerPathExtractor` when manifest has `trigger_paths` |
| `st_extract/__init__.py` — `TriggerPathExtractor` registration | fleet-shared (closure) | `report_engine`, `freespin_dynamics`, `structure_drift` |
| `st_extract/trigger_path.py` — `TriggerPathExtractor` | base-EXCLUDED; per-machine declared | machines with `trigger_paths` in manifest |
| `features/payouts_by_spin_type.py` | base-EXCLUDED; all PER_SPINTYPE machines | report_engine emit loop, `spin_type_outcomes`, `freespin_dynamics`, `respin_dynamics` |
| `features/spin_type_outcomes.py` | base-EXCLUDED; all PER_SPINTYPE machines | report_engine emit loop → `player_impact.spin_type_outcomes` |
| `features/spin_type_rtp_buckets.py` | base-EXCLUDED; all PER_SPINTYPE machines | report_engine emit loop → `player_impact.spin_type_rtp_buckets` |
| `features/reel_marginal_by_spin_type.py` | base-EXCLUDED; all PER_SPINTYPE machines | report_engine emit loop → `player_impact.reel_marginal_by_spin_type` |
| `features/topdollar_choice.py` | base-EXCLUDED; player_choice-role machines (M15) | `_stDimSelectorChoice`, `_stDimSettlement` |
| `features/respin_dynamics.py` | base-EXCLUDED; respin-role machines (M43, M279) | `_stDimRespin` |
| `features/minigame_dynamics.py` | base-EXCLUDED; WinMiniGame-play machines (M43) | `_stDimMinigame` |
| `features/wheel_dynamics.py` | base-EXCLUDED; Wheel-play machines (M279) | `_stDimWheel` |
| `features/freespin_dynamics.py` | base-EXCLUDED; freespin-role machines (M275) | `_stDimFreespin` |
| `features/upstream_feature_breakdown.py` | base-EXCLUDED; all CROSS_CUTTING machines | `renderUpstreamFeatureBreakdown` |
| `features/bonus_chain_dynamics.py` | base-EXCLUDED; all CROSS_CUTTING machines | `freespin_dynamics` (REQUIRES), `renderBonusChainDynamics` |
| `features/structure_drift.py` | base-EXCLUDED; all CROSS_CUTTING machines | `renderStructureDriftPanel` |
| `configs/machine_manifests/M275.json` — `trigger_paths` block | per-machine declared | `TriggerPathExtractor`, `freespin_dynamics._trigger_path_section` |
| `app.js` — `SPINTYPE_DIMENSIONS` | fleet-shared frontend framework | `renderSpinTypeOutcomes` |
| `app.js` — `_stDimFreespin` | fleet-shared but M275-driven (only machine with freespin role) | `renderSpinTypeOutcomes` for freespin ST |

---

## 7. Existing Trigger-Path Data Flow (The One Partial Path)

The complete data journey for M275 ST126 trigger_path data:

```
configs/machine_manifests/M275.json          [spin_types.126.trigger_paths block]
         |
         v (report_engine.py:504)
get_extractors_for_manifest(manifest)        [st_extract/__init__.py:136]
  → TriggerPathExtractor.clone_for_manifest(manifest)
  → _st_declarations[126] = trigger_paths block
         |
         v (report_engine.py:727)
parse_chunk_response(..., st_extractors=[tp_ext])
  [per robot: parser.py:1285]
  → tp_ext.begin_robot(robot_ctx)            [trigger_path.py:185]
    robot_ctx = {robot_idx, trig_sessions, cycle_peak}
  [per round: parser.py:~2120]
  → tp_ext.observe_round(round_dict, spin_type=126, round_ctx)
    [trigger_path.py:199]
    → spin_type in _st_declarations? YES (126 declared)
    → _resolve_labels() → discriminator kind="round_field", field="GameplayTriggerType"
      [trigger_path.py:379]
      → round_dict["GameplayTriggerType"] in {"0": "scatter", "2": "collect_peak"}
      → returns "scatter" | "collect_peak" | "unknown:<value>"
    → accumulates: _chunk_round_count[(126, label)] += 1
                   _chunk_win_sum[(126, label)] += win_amt
                   _chunk_win_band[(126, label)][bucket] += 1
                   _chunk_session_keys[(126, label)].add((robot_idx, block_id))
  [after all robots: parser.py:~2300]
  → tp_ext.finalize_chunk() → dict
    [trigger_path.py:267]
    output: {"126": {"scatter": {round_count, win_sum, session_count, win_band_hist},
                     "collect_peak": {...}}}
    stored in: rec["st_extract"]["trigger_path"]
         |
         v (report_engine.py: plugin extract loop)
freespin_dynamics.extract(parse_state, chunk_dict)
  [freespin_dynamics.py:236-312]
  → chunk_dict["st_extract"]["trigger_path"]["126"] → per-path stats
  → accumulated in: acc["trigger_paths"]["126"]["scatter"] += ...
                    acc["trigger_paths"]["126"]["collect_peak"] += ...
  → merged across chunks via reduce() [freespin_dynamics.py:314-350]
         |
         v (report_engine.py: plugin emit loop)
freespin_dynamics.emit(final_acc, summary, ctx)
  [freespin_dynamics.py:608-805]
  → _trigger_path_section(final_acc, fs_st=126, ...)
    [freespin_dynamics.py:451-606]
    → per-path row: {path, label, session_count, session_share,
                     trigger_rate_per_paid_spin, one_per_n_paid_spins,
                     round_count, win_share, rtp_contribution_pp_split,
                     win_band_hist: [{band, round_count, prob}]}
    → written to: summary["player_impact"]["freespin_dynamics"]["trigger_paths"]
         |
         v (HTTP GET /api/reports/...)
player_impact_summary.json deserialized in frontend
         |
         v (app.js:5100)
_stDimFreespin(stCtx)
  → checks fd.freespin_spin_type == stCtx.row.spin_type (126 match)
  → trigger_paths block rendered at app.js:5216-5291
  → side-by-side table: scatter | collect_peak columns
  → per-path metrics + band histograms rendered
```

**What this path produces per path today:**
- `session_count` (distinct opened blocks)
- `round_count` (total freespin rounds in that path)
- `win_sum` → `win_share`, `rtp_contribution_pp_split`
- `win_band_hist` (round-level multiplier distribution)

**What is NOT path-split today (all aggregated at ST126 level):**
- Hit rate (freespin rounds that win vs don't)
- Avg win when hit
- Session cadence (avg block length, continuation probability)
- Payid mix (symbol combo distribution)
- RTP concentration (fat tail share, zero-win round rate)
- Multiplier distribution bands (the full `freespin_multiplier_distribution`)
- Hot-board uplift ratio
- ER ladder, FS arc (parser_blind)
- Mean/median/max session win
- FS-index arc

---

## 8. freespin_dynamics Consumes trigger_path — Evidence

`freespin_dynamics.py:270-296` (extract):
```python
st_extract = chunk_dict.get("st_extract")
if isinstance(st_extract, dict):
    tp_raw = st_extract.get(_TRIGGER_PATH_EXTRACTOR_ID)  # "trigger_path"
    if isinstance(tp_raw, dict):
        chunks_with_extract = 1
        for st_key, paths in tp_raw.items():
            dest = trigger_paths.setdefault(str(st_key), {})
            for label, stats in paths.items():
                dest[str(label)] = {
                    "round_count": int(stats.get("round_count") or 0),
                    "win_sum": float(stats.get("win_sum") or 0.0),
                    "session_count": int(stats.get("session_count") or 0),
                    "win_band_hist": {...},
                }
```

`freespin_dynamics.py:451` (`_trigger_path_section`):
```python
acc_paths = (final_acc.get("trigger_paths") or {}).get(str(fs_st)) or {}
```

The `freespin_dynamics` plugin is the ONLY feature that reads
`chunk_dict["st_extract"]["trigger_path"]`. No other plugin in
`fresh_slotlab/analyzer/features/` reads `st_extract` from the chunk dict.

---

## 9. Open Questions

1. **`spin_type_bucket_spins/win` in `freespin_dynamics.extract()`** (freespin_dynamics.py:299-311):
   These are the ST-keyed multiplier histograms used to build `freespin_multiplier_distribution`
   and `base_multiplier_distribution`. Currently keyed by ST integer only. If a future machine
   had a freespin ST opened by two paths with different config slots (e.g. different paytables),
   the multiplier distributions for the two paths would be merged here. The `trigger_path` extractor
   collects `win_band_hist` per path, but that is a different histogram (win-per-round/bet) from
   the per-ST bucket histogram (which uses ALL of a ST's rounds without filtering by path).
   It is unclear whether `win_band_hist` in the trigger_path extractor and `spin_type_bucket_win`
   in the parser accumulator are measuring the same thing or something different (the extractor
   uses `win_amt / effective_bet` per round; the parser accumulates `return_bucket(win_amt / bet_amt)`
   per round — same bucket function, but the extractor only accumulates rounds matching the ST AND
   path label while the parser accumulates all rounds of the ST regardless). If they ARE the same
   metric, `win_band_hist` from trigger_path is already the path-split version of
   `spin_type_bucket_win` for the freespin ST. If they differ in subtle ways (e.g. bet used,
   rounds included), that gap needs documentation.

2. **`structure_drift` reads `chunk_dict["st_extract"]["signature_audit"]`** (structure_drift.py:46):
   The source says `extract() lifts rec["st_extract"]["signature_audit"]`. However, the
   `st_extract/__init__.py` only shows `TriggerPathExtractor` registered (DECLARED_IN_KEY =
   "trigger_paths"). There is no `SignatureAuditExtractor` visible in `st_extract/`. It is
   unclear whether `signature_audit` is: (a) a second STExtractor module not yet read, (b)
   produced by a different mechanism inside the parser, or (c) the structure_drift plugin has
   a stale docstring and actually reads from a different stash key. The actual data path for
   `structure_drift` cannot be fully confirmed from the files inspected.

3. **`payout_id_win_by_spin_type` attribution for trigger sessions** (parser.py:1424-1434):
   When a trigger session fires (e.g. M275 ST126 opened by scatter), the session win is
   attributed to the trigger round's ST (`_trig_st = trigger_round.SpinType`). For M275,
   the trigger round is ST140 (paid_spin), so `payout_id_win_by_spin_type["666"][140] +=
   session_win`. This means the freespin session win in `payouts_by_spin_type` appears under
   `"ST140_paid"`, not under `"ST126_free"`. But `freespin_dynamics` looks for the freespin ST's
   payid rows in `payouts_by_spin_type` via `_label_for_st(pbst, fs_st)` (freespin_dynamics.py:730).
   It is unclear whether `"ST126_free"` has meaningful payid rows or if ST126's real wins are
   attributed under ST140 via the trigger-session fold — the exact split between what lands in
   ST140 vs ST126 in `payouts_by_spin_type` is not fully traced here.

4. **`session_bucket_spins_by_settlement_st`** (parser.py:921-927): This accumulator keys the
   per-session return-bucket histogram by `settlement_st` (last bonus SpinType in the trigger
   session). It is used by `upstream_feature_breakdown` as a fallback bucket source for settlement
   STs whose `spin_type_bucket_win` is all-zero. For M275 ST126 (a freespin, not a settlement),
   it is unclear whether any trigger sessions are detected for M275 (Type-2 self-crediting shape)
   and whether this accumulator carries meaningful M275 data or is an effective no-op.

5. **`bonus_chain_dynamics` per-feature split vs `trigger_paths` split** accuracy:
   The `upstream_feature_breakdown` `sub_streams` uses `chain_chunk_summaries` keyed by
   `(first_st, entry_cc_reset, sp_type_within_chain)`. For M275, this produces a
   `[via NormalCollectionSpin]` vs `[via NewFreespin]` label based on prev-round-pids heuristic.
   The M275 manifest caveats state "841/67 vs GTT truth 829/80" — a discrepancy. It is unclear
   which path the `session_count` in `upstream_feature_breakdown.sub_streams` reports for M275
   (from the coarse chain mechanism), and whether that number is presented in any frontend panel
   the user currently sees as authoritative.
