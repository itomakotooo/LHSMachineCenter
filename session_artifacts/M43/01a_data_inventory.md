# Stage 1a — M43 data inventory

## Verdict (one-liner)

**pass** — Mode 1 cache is complete (650,000 paid spins across 41 chunks, single config_md5/code_md5 anchor, schema fingerprint matches envelope). No drift detected. Ready for Stage 1b baseline + Stage 1c mechanism inference. Mode 2/5/7 caches exist but are out-of-scope this session (mode-1-first universal workflow per SESSION_BRIEF).

---

## Cache scope checked

- `rawdata/M43/mode_1/` (in-scope this session)
- `rawdata/M43/mode_2/`, `rawdata/M43/mode_5/`, `rawdata/M43/mode_7/` (briefly noted; out-of-scope)
- `cache/chunks/` — N/A (project standardized on `rawdata/<M>/mode_<N>/` per current ARCHITECTURE; no separate per-machine chunks cache layer for M43)

## Chunks per mode

| mode | chunks | total paid spins (envelope-claimed) | first saved | scope |
|---|---|---|---|---|
| **1** | **41** | **650,000** | 2026-04-17T02:23:09Z | in-scope |
| 2 | 1 | 10,000 | 2026-04-17T02:36:50Z | out-of-scope (deferred) |
| 5 | 1 | 10,000 | 2026-04-17T02:26:56Z | out-of-scope (deferred) |
| 7 | 3 | 90,000 | 2026-04-17T02:59:52Z | out-of-scope (deferred) |

### Mode 1 chunk size mix
- chunk_0001: 1,000 spins × 10 robots = 10,000 spins (legacy 2026-04-17 sample)
- chunks 0002-0041: 2,000 spins × 8 robots = 16,000 spins each (re-sampled 2026-05-13 at session kickoff)
- Total: 10,000 + 40 × 16,000 = 650,000 paid spins

The mix of robot_count (10 vs 8) and spin_times (1000 vs 2000) per chunk is non-uniform; the analyzer aggregates these uniformly via `_chunks.json` envelope and the `response` list semantics.

## Envelope structure (chunk_0001.json — common across all chunks)

| key | value | notes |
|---|---|---|
| `_cache_version` | `2` | v2 envelope (no payload sha256) — per `slot_designer/core/emitter/chunk.py` |
| `_machine` | `M43` | matches `configs/machines.json` `M43` entry |
| `_mode` | `1` | |
| `_bet` | `1000` | base bet 1000 credits/spin |
| `_spin_times` | varies (1000 or 2000) | per-robot spin count |
| `_robot_count` | varies (10 or 8) | concurrent robots |
| `_chunk_index` | sequential | |
| `_saved_at` | ISO-8601 UTC | |
| `_config_md5` | `b99e0b0523794944f807154a0da22e5e` | matches `configs/machines.json` `M43.configSummaryMd5` |
| `_code_md5` | `6e02924b710ae1ba0845223730cf728e` | matches `configs/machines.json` `M43.codeSummaryMd5` |
| `_upstream_schema_fingerprint` | `5d02773c069fc396` | round-keyset hash |
| `_dev_sample` | `true` | dev sample, not prod runtime data — acceptable per `feedback_no_proactive_fetch.md` (cached) |
| `response` | list of robots | each robot has stringified `roundResult` and `analysisResult` JSON |

## Schema fingerprint vs latest production

| check | result |
|---|---|
| envelope `_upstream_schema_fingerprint` (claimed) | `5d02773c069fc396` |
| recomputed from first SpinType=1 round (`sha256[:16]` of sorted keys) | `5d02773c069fc396` |
| **match** | **YES** |
| md5 anchors uniform across all 41 mode-1 chunks (cfg/code) | YES (single anchor each) |
| md5 anchors consistent across mode 1/2/5/7 caches | YES (same cfg/code md5 in every mode dir) |
| schema fingerprint consistent across modes | YES (`5d02773c069fc396` in all 4 modes) |

**Drift status**: NO DRIFT. Cache is freshly resampled (2026-05-13) at exactly the same `configSummaryMd5 / codeSummaryMd5` as the production registry. Stage 1b can proceed against this cache via direct rawdata read; no fresh upstream fetch needed (per `memory/feedback_no_proactive_fetch.md`).

## Round structure (chunk_0001.json — first SpinType=1 round)

17 fields per paid base-spin round (`SpinType=1`):
```
['BetAmount', 'CostCredits', 'CurJackpotStoreWin', 'IsLackCreditsSpin',
 'LastCredits', 'PayLineGroupId', 'PayoutByPayline', 'PayoutGroupId',
 'PayoutIdToWinAmount', 'RTPId', 'ReMarks', 'ReelSkin', 'RewardLastNode',
 'SpinTimes', 'SpinType', 'StopSymbolsByCol', 'WinCredits']
```

Mini-game rounds (`SpinType=51`) have a **reduced 7-field keyset** (drop `BetAmount, CostCredits, PayoutByPayline, PayoutGroupId, PayLineGroupId, PayoutIdToWinAmount, ReelSkin, RewardLastNode, StopSymbolsByCol, CurJackpotStoreWin`). This is structural — mini-game rounds attach to the preceding paid round and don't have their own reels. Respin rounds (`SpinType=50`) retain the full keyset (free re-spin with new stops).

## Out-of-scope inventories (mode 2/5/7) — captured for next session

- Mode 2 (lucky, ~300% RTP target): 1 chunk × 10,000 spins — minimal cache, OK for stage-0 verification but Stage 1b for mode 2 will need re-sampling once mode 2 is in-scope.
- Mode 5 (super-lucky, ~500% RTP target): 1 chunk × 10,000 spins — same status as mode 2.
- Mode 7 (cut, ~85% RTP target): 3 chunks × 90,000 spins — usable for orientation but small.

Out-of-scope per `00_SESSION_BRIEF.md`: "This session ships mode 1 only. Mode 7 / 2 / 5 are not in scope until mode 1 is shipped on `collab/dev`."

## Cross-references

- Chunks inventory file: `rawdata/M43/mode_1/_chunks.json` (`_version=1`, `chunks` dict + `by_md5` inverted index)
- Per `memory/reference_chunk_index_inverted_md5.md`: read inverted `by_md5` map for batch processing.
- Per `memory/feedback_no_proactive_fetch.md`: do not refetch upstream; 650k cache is sufficient for Stage 1b.

## Sources/anchors

- `configs/machines.json` lines 9966-9989 (M43 entry): mechanism `logicClassNames` confirms 9 logic classes for normal+respin+wild+minigame.
- `rawdata/M43/mode_1/_chunks.json`: 41 chunks all anchored at the same md5 pair.
- `rawdata/M43/mode_1/chunk_0001.json` envelope + first round: structural verification.
