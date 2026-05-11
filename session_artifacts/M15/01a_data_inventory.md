# M15 — Stage 1a Data Acquisition Inventory

> **Agent**: Analyst (A) — per [`slot_designer/ONBOARDING_PROCESS.md`](../../slot_designer/ONBOARDING_PROCESS.md) §4 row "A Analyst" / §5 stage 1a.
>
> **Date**: 2026-05-11
>
> **Scope**: Confirm M15 production rawdata presence + chunk-count + schema-fingerprint baseline per mode (1 / 2 / 5 / 7). **No analyzer / no heavy I/O** — just enumeration.

---

## Result summary

All 4 modes have production rawdata. **Stage 1b can proceed for every mode** (mode 1 is the canonical empirical anchor; modes 2 / 5 / 7 have less coverage but are non-virtual).

| mode | chunks | total spins | first / last file | distinct (cfg_md5, code_md5) | schema fingerprint |
|---|---|---|---|---|---|
| **1** | 21 | 228,000 | chunk_0001 / chunk_0021 | 2 (2d89963173… + localcfg_42979d13) | `5d02773c069fc396` |
| **2** | 13 | 104,000 | chunk_0001 / chunk_0013 | 1 (2d89963173…) | `5d02773c069fc396` |
| **5** | 13 | 104,000 | chunk_0001 / chunk_0013 | 1 (2d89963173…) | `5d02773c069fc396` |
| **7** | 4 | 88,000 | chunk_0001 / chunk_0004 | 1 (2d89963173…) | `5d02773c069fc396` |

Single shared `code_md5 = 44297a616be42cc26ed2bae3e6301d1a` across **all** modes / cfgs. Single shared `upstream_schema_fingerprint = 5d02773c069fc396` across **all** modes. The mode 1 second cfg (`localcfg_42979d13`) is a localcfg variant sampled 2026-04-28 — same code_md5, same schema, presumably a re-run with localized weights. Stage 1b prod baseline should use the production-anchored cfg `2d89963173c4ce21690baa84f9bfec59` for cleanliness.

---

## Location

Production rawdata lives at:

```
rawdata/M15$TopDollarSelector$0$/
├── mode_1/  (_chunks.json + chunk_0001..0021.json)
├── mode_2/  (_chunks.json + chunk_0001..0013.json)
├── mode_5/  (_chunks.json + chunk_0001..0013.json)
└── mode_7/  (_chunks.json + chunk_0001..0004.json)
```

Each `_chunks.json` is the per-mode index sidecar (per memory `reference_chunk_index_inverted_md5.md`) containing per-chunk envelope metadata + `by_md5` inverted index.

> **Note (process gap, logged to `process_improvements.md` #7)**: SESSION_BRIEF §2 names `cache/chunks/M15$TopDollarSelector$0$/` as the expected production cache path. The repo's actual cache dir (`cache/chunks/`) is empty except for `.gitkeep`. Real prod rawdata is under `rawdata/M15$TopDollarSelector$0$/`. Both paths conventions co-exist in this repo (`cache/chunks/` is fresh_slotlab analyzer's working cache, `rawdata/` is the persistent upstream archive). Stage 1a should look in both. This task uses `rawdata/`.

---

## Per-mode detail

### mode 1 (paid baseline)

- **228,000 total spins** across **21 chunks**
- 5 chunks under prod cfg `2d89963173…` → 100,000 spins (5 × 20 robots × 1000 spins)
- 16 chunks under `localcfg_42979d13` → 128,000 spins (16 × 8 robots × 1000 spins). Saved 2026-04-28 (~6 days ago at session start).
- Same `code_md5 = 44297a616b…`, same `schema_fp = 5d02773c069fc396`.
- bet (`_bet`) and other envelope fields match across cfgs.

### mode 2 (lucky mode)

- **104,000 total spins** across **13 chunks**
- Single cfg / code / schema cluster.
- robots per chunk = 8; spins per robot = 1000.

### mode 5 (super-lucky mode)

- **104,000 total spins** across **13 chunks**
- Identical envelope shape to mode 2 (cfg / code / robots / spin_times / schema).

### mode 7 (cut mode)

- **88,000 total spins** across **4 chunks**
- robots per chunk = 22; spins per robot = 1000.

---

## Schema fingerprint sanity (Stage 1b §12 input)

One production chunk (`mode_1/chunk_0001.json`) has envelope (top-level) keys:

```
['_cache_version', '_machine', '_mode', '_bet', '_spin_times', '_robot_count',
 '_chunk_index', '_saved_at', '_config_md5', '_code_md5',
 '_upstream_schema_fingerprint', '_payload_sha256', 'response']
```

Each entry of `response[]` is a robot, with two stringified-JSON fields: `roundResult` (round list) and `analysisResult` (`{TotalWin, FeatureWin, SummaryWin}`). The first round inside `roundResult` has these 17 keys (sorted):

```
['BetAmount', 'CostCredits', 'CurJackpotStoreWin', 'IsLackCreditsSpin',
 'LastCredits', 'PayLineGroupId', 'PayoutByPayline', 'PayoutGroupId',
 'PayoutIdToWinAmount', 'RTPId', 'ReMarks', 'ReelSkin', 'RewardLastNode',
 'SpinTimes', 'SpinType', 'StopSymbolsByCol', 'WinCredits']
```

Distinct `SpinType` values in `roundResult`: `{1, 14, 15}`.

- ST=1: base paid spin
- ST=14: Feature Play offer/reveal sub-round
- ST=15: Feature Play end marker

This matches the M15 plugin's `emit_extra_rounds` contract (per `machines/M15/plugins/feature.py` + `__init__.py`) — Stage 2 schema alignment already verified at refactor merge `2ae5a7d` (per SESSION_BRIEF §1).

The 16-byte `_upstream_schema_fingerprint = 5d02773c069fc396` is what Stage 1b §12 cross-checks against the virtual engine's emitted chunk.

---

## Decision

Stage 1a passes. **All 4 modes have production rawdata** — Stage 1b can compute a "prod baseline" comparison column for every mode (not just mode 1).

No upstream fetch required, no escalation to user.

Proceed to Stage 1b: `scripts/baseline_dump.py` produces the 12-section comprehensive baseline → `01b_baseline_report.md`.
