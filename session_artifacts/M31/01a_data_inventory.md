# M31 Mode 1 — Stage 1a Data Inventory

**Date**: 2026-05-14
**Analyst**: A (Analyst agent, slot-analyst)
**Scope**: Mode 1 only (Phase alpha, mode-1-first universal scope per ONBOARDING_PROCESS.md §1.1)

---

## §1 Chunk Inventory

**Total chunks**: 25 (chunk_0001.json through chunk_0025.json)

| File | idx | spin_times | robot_count | saved_at | cfg_md5 | code_md5 | size_bytes |
|---|---|---|---|---|---|---|---|
| chunk_0001.json | 1 | 1000 | 10 | 2026-04-17T02:22:46Z | e7f4aa3f | 8067f1ba | 4,637,971 |
| chunk_0002.json | 2 | 2000 | 8 | 2026-05-14T03:45:20Z | e7f4aa3f | 8067f1ba | 7,468,432 |
| chunk_0003.json | 3 | 2000 | 8 | 2026-05-14T03:45:22Z | e7f4aa3f | 8067f1ba | 7,469,980 |
| chunk_0004.json | 4 | 2000 | 8 | 2026-05-14T03:45:23Z | e7f4aa3f | 8067f1ba | 7,406,081 |
| chunk_0005.json | 5 | 2000 | 8 | 2026-05-14T03:45:26Z | e7f4aa3f | 8067f1ba | 7,473,591 |
| chunk_0006.json | 6 | 2000 | 8 | 2026-05-14T03:45:26Z | e7f4aa3f | 8067f1ba | 7,428,297 |
| chunk_0007.json | 7 | 2000 | 8 | 2026-05-14T03:45:24Z | e7f4aa3f | 8067f1ba | 7,363,327 |
| chunk_0008.json | 8 | 2000 | 8 | 2026-05-14T03:45:24Z | e7f4aa3f | 8067f1ba | 7,471,116 |
| chunk_0009.json | 9 | 2000 | 8 | 2026-05-14T03:45:26Z | e7f4aa3f | 8067f1ba | 7,422,478 |
| chunk_0010.json | 10 | 2000 | 8 | 2026-05-14T03:45:40Z | e7f4aa3f | 8067f1ba | 7,450,012 |
| chunk_0011.json | 11 | 2000 | 8 | 2026-05-14T03:45:40Z | e7f4aa3f | 8067f1ba | 7,434,617 |
| chunk_0012.json | 12 | 2000 | 8 | 2026-05-14T03:45:36Z | e7f4aa3f | 8067f1ba | 7,476,403 |
| chunk_0013.json | 13 | 2000 | 8 | 2026-05-14T03:45:38Z | e7f4aa3f | 8067f1ba | 7,404,128 |
| chunk_0014.json | 14 | 2000 | 8 | 2026-05-14T03:45:40Z | e7f4aa3f | 8067f1ba | 7,407,681 |
| chunk_0015.json | 15 | 2000 | 8 | 2026-05-14T03:45:42Z | e7f4aa3f | 8067f1ba | 7,418,885 |
| chunk_0016.json | 16 | 2000 | 8 | 2026-05-14T03:45:42Z | e7f4aa3f | 8067f1ba | 7,442,427 |
| chunk_0017.json | 17 | 2000 | 8 | 2026-05-14T03:45:42Z | e7f4aa3f | 8067f1ba | 7,357,670 |
| chunk_0018.json | 18 | 2000 | 8 | 2026-05-14T03:46:01Z | e7f4aa3f | 8067f1ba | 7,404,119 |
| chunk_0019.json | 19 | 2000 | 8 | 2026-05-14T03:46:02Z | e7f4aa3f | 8067f1ba | 7,408,874 |
| chunk_0020.json | 20 | 2000 | 8 | 2026-05-14T03:45:58Z | e7f4aa3f | 8067f1ba | 7,453,660 |
| chunk_0021.json | 21 | 2000 | 8 | 2026-05-14T03:45:57Z | e7f4aa3f | 8067f1ba | 7,412,384 |
| chunk_0022.json | 22 | 2000 | 8 | 2026-05-14T03:46:00Z | e7f4aa3f | 8067f1ba | 7,469,141 |
| chunk_0023.json | 23 | 2000 | 8 | 2026-05-14T03:45:59Z | e7f4aa3f | 8067f1ba | 7,435,901 |
| chunk_0024.json | 24 | 2000 | 8 | 2026-05-14T03:45:58Z | e7f4aa3f | 8067f1ba | 7,412,534 |
| chunk_0025.json | 25 | 2000 | 8 | 2026-05-14T03:46:01Z | e7f4aa3f | 8067f1ba | 7,481,573 |
| **TOTALS** | | **49,000** | | | | | **184,516,263** |

**Paid spin accounting**:
- chunk_0001: 1000 spin_times x 10 robots = 10,000 paid spins
- chunks 0002-0025: 2000 spin_times x 8 robots x 24 chunks = 384,000 paid spins
- Total paid spins: **394,000** (matches `sampling.paid_spins` in summary exactly)
- Bonus spins (free spins, attributed to triggering paid rounds): 20,818
- Grand total rounds in analyzer: 414,818 (per session-centric semantics)

**Index gaps**: None. Indices 1 through 25 are all present with no gaps.

---

## §2 Production MD5 Uniqueness

**Source**: `_chunks.json` `by_md5` inverted index (authoritative grouping per `reference_chunk_index_inverted_md5.md`).

The `by_md5` index contains exactly one partition key:

```
e7f4aa3f7e8792473290d33cf3fe27f3|8067f1baa85812bb05d91515f61bf2d6
```

All 25 chunks are listed under this single key:

```
chunk_0001.json, chunk_0002.json, ..., chunk_0025.json  (25 total)
```

**VERDICT: UNIFORM — all 25 chunks share the single (cfg_md5, code_md5) pair:**

| Field | Value |
|---|---|
| cfg_md5 | `e7f4aa3f7e8792473290d33cf3fe27f3` |
| code_md5 | `8067f1baa85812bb05d91515f61bf2d6` |

Cross-check: `configs/machines.json` M31 entry shows `configSummaryMd5 = e7f4aa3f7e8792473290d33cf3fe27f3` and `codeSummaryMd5 = 8067f1baa85812bb05d91515f61bf2d6` — chunk md5s match production config exactly. No drift.

---

## §3 Schema Fingerprint

**Method**: `_compute_upstream_schema_fingerprint` in `fresh_slotlab/player_impact_analyzer.py` (lines 2108-2138) — takes sorted key set of `roundResult[0]` from first robot, computes `sha256[:16]`.  
The virtual emitter in `slot_designer/core/emitter/chunk.py` implements the identical algorithm as `compute_schema_fingerprint`.

### Chunk envelope (top-level keys)

Observed in chunk_0001.json:

```
_bet, _cache_version, _chunk_index, _code_md5, _config_md5,
_dev_sample, _machine, _mode, _robot_count, _saved_at,
_spin_times, _upstream_schema_fingerprint, response
```

`response` is a list of robot dicts. Each robot has two keys: `roundResult` (JSON-encoded string) and `analysisResult` (JSON-encoded string).

### roundResult inner schema (per-spin record keys, sorted)

```
BetAmount, CostCredits, CurJackpotStoreWin, IsLackCreditsSpin, LastCredits,
PayLineGroupId, PayoutByPayline, PayoutGroupId, PayoutIdToWinAmount, RTPId,
ReMarks, ReelSkin, RewardLastNode, SpinTimes, SpinType, StopSymbolsByCol,
WinCredits
```

**Key count**: 17 fields.

### analysisResult shape (double-encoded JSON per README.md)

Outer keys: `TotalWin`, `FeatureWin`, `SummaryWin` — each value is a JSON-encoded string (double-encoded).

Inner key sets:
- `TotalWin` inner: `-1, 0, 1, 10, 20, 5, 50` (7 RTP multiplier buckets)
- `FeatureWin` inner: `FreeSpin, NormalFreeSpin`
- `SummaryWin` inner: `FreeSpin, NormalFreeSpin`

This confirms the double-encode format documented in slot_designer/README.md is present and consistent.

### Fingerprint computation

```
roundResult[0] sorted key string:
  BetAmount|CostCredits|CurJackpotStoreWin|IsLackCreditsSpin|LastCredits|
  PayLineGroupId|PayoutByPayline|PayoutGroupId|PayoutIdToWinAmount|RTPId|
  ReMarks|ReelSkin|RewardLastNode|SpinTimes|SpinType|StopSymbolsByCol|WinCredits

sha256[:16]: 5d02773c069fc396
```

**Envelope stored fingerprint** (`_upstream_schema_fingerprint` in chunk_0001.json): `5d02773c069fc396`

**VERDICT: MATCH** — computed fingerprint equals stored envelope value.

### Drift check vs production schema definition

The fingerprint algorithm in `fresh_slotlab/player_impact_analyzer.py` and in `slot_designer/core/emitter/chunk.py` are byte-identical (both: `sha256("|".join(sorted(keys)).encode()).hexdigest()[:16]`). No drift between production analyzer definition and M31 chunk data.

**Schema status: CLEAN — fingerprint `5d02773c069fc396`, 17-field roundResult, no unexpected or missing fields.**

---

## §4 Existing Dev Report Metadata Snapshot

**Source**: `reports/M31/mode_1/latest.json` + `reports/M31/mode_1/versions/rv_20260514T034512Z_48e77c07/player_impact_summary.json`

| Field | Value |
|---|---|
| report_version | `rv_20260514T034512Z_48e77c07` |
| run_id | `48e77c0721f8` |
| created_at | `2026-05-14T03:46:08.196032Z` |
| analyzer_version | `ac7ff302873b` |
| rawdata_config_md5 | `e7f4aa3f7e8792473290d33cf3fe27f3` |
| rawdata_code_md5 | `8067f1baa85812bb05d91515f61bf2d6` |
| RTP (point_pct) | **92.62%** |
| CI 95% interval | [91.63%, 93.61%] |
| achieved_halfwidth_pp | 0.991 pp (target was 1.0 pp — JUST met) |
| total_spins (sessions) | 414,818 (394,000 paid + 20,818 free/bonus) |
| quality_label | `EXPLORATORY` |
| stop_reason | `target_ci_reached` |
| sampling duration | 55.83 seconds |
| our_total_win = server_total_win | 364,919,000 credits (cross-signal match) |

**RTP gap vs universal target**:  
Mode 1 target = 95.0%. Observed = 92.62%. Gap = **-2.38 pp** (informational, no analysis at Stage 1a; Stage 1b will establish baseline).

**Spin type breakdown** (record only):
- SpinType 43 ("paid"): 394,000 spins, RTP contribution 50.84 pp
- SpinType 44 ("free"): 20,818 spins (5.02% of all rounds), RTP contribution 37.13 pp

**Feature streams** (record only):
- `NormalFreeSpin`: fires on SpinType 43 (paid), 394,000 fires, RTP contribution 53.52 pp
- `FreeSpin`: fires on SpinType 44 (free), 20,818 fires, RTP contribution 39.10 pp

---

## §5 Anomalies / Risk Flags

### 5.1 Chunk size outlier: chunk_0001 (significant — structural, not random)

chunk_0001 has 1000 spin_times x 10 robots vs all other chunks at 2000 spin_times x 8 robots. This accounts for its smaller file size (4,637,971 bytes vs median 7,431,457 for 2k-spin chunks). The configuration difference is expected from the sampling pipeline's initial chunk design; it is not a data corruption indicator. The paid spin accounting (10,000 + 384,000 = 394,000) reconciles cleanly with the analyzer.

Additionally, chunk_0001 was saved on **2026-04-17** (27 days before the rest, which were all saved **2026-05-14**). This is a genuine partial-refresh signal: chunk_0001 predates the bulk collection by ~4 weeks.

**FLAG (LOW severity)**: chunk_0001 is an older seed chunk with a different spin_times/robot_count configuration than the bulk. It shares the same (cfg_md5, code_md5) as all other chunks, so it is production-consistent data. No action required; note in Stage 1b that this chunk contributes 2.5% of paid spins at a different per-round B/spin ratio (~4,638 B/spin vs ~3,716 B/spin for 2k chunks — likely due to different robot count structure).

### 5.2 Chunk size variance within 2k-spin group (low severity)

Among the 24 homogeneous 2k-spin chunks, stdev is 34,512 bytes (0.46% of median). Several chunks fall slightly beyond 1 sigma (chunk_0007 and chunk_0017 at ~2 sigma below median), consistent with normal variation in free spin win volume per chunk. No structural anomaly.

### 5.3 quality_label = EXPLORATORY

The report is labeled `EXPLORATORY`. The CI halfwidth is 0.991 pp (target 1.0 pp, just met). At 394,000 paid spins, this is adequate for Stage 1b baseline purposes but is below the volume expected from a full production cache (10,000 spins/chunk x 25 = expected ~250,000 paid spins baseline; actual is higher due to multi-robot design). The label is a pipeline quality tier indicator, not a data quality failure. Stage 1b analysis proceeds on this basis.

### 5.4 No _unattributed_* / fallback / _other buckets found

A full grep of `player_impact_summary.json` for `_unattributed`, `fallback`, and `_other` patterns returned zero matches. The `payout_ids_top20` list contains pay_ids `1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 666` with no unattributed residual entry. The `payout_group` section shows a single group_id=0 covering all 414,818 rounds with total_win=364,919,000 — matching `our_total_win`/`server_total_win` exactly.

Per `feedback_invariant_with_fallback_hides_drift.md`: no fallback bucket alert needed for this report.

### 5.5 RTP cross-signal sanity (preliminary)

`our_total_win` = `server_total_win` = 364,919,000 credits. This is the primary invariant (our calc vs server). Sum of payout_id RTP contributions from the top-20 payout_ids listing:

28.73 (pid 8) + 24.30 (pid 7) + 12.22 (pid 9) + 7.48 (pid 10) + 6.75 (pid 4) + 4.59 (pid 11) + 3.77 (pid 12) + 2.41 (pid 5) + 1.10 (pid 3) + 0.47 (pid 2) + 0.46 (pid 1) + 0.33 (pid 6) + 0.00 (pid 666) = **92.62 pp**

Sum of pay_id RTP contributions = 92.62 pp = summary RTP 92.62%. Cross-signal passes. Full parity verification deferred to Stage 1b.

### 5.6 machines.json logicClassNames note

The M31 entry in `configs/machines.json` lists logic classes: `FreeSpinGenerator`, `FreeSpinPostProcessor`, `FreeSpinPreProcessor`, `FreeSpinValidator`, `NormalFreeSpinGenerator`, `NormalFreeSpinPostProcessor`, `NormalFreeSpinValidator`, `NormalRTPPreProcessor`. This is consistent with the two observed SpinTypes (43=paid/NormalFreeSpin, 44=free/FreeSpin) and the dual feature streams in the report. No unexpected classes; no drift from observed data.

---

## Readiness Verdict

Stage 1a complete; Stage 1b can begin once user_brief.md is in.
