# Analyst pid 9 sub-row reconciliation — 2026-05-11

## TL;DR (verdict first)

**The 7× discrepancy is NOT a spec / engine / analyzer bug. It is stale-cache pollution.**

The "real machine" column in the user's screenshot is the file
`configs/paytables/M37_mode1.json` (mtime **2026-05-08 12:22**), which was
produced by `scripts/infer_paytable.py` against an older 131-chunk sample
representing a **prior M37 cfg version** (likely v3 — the 580%-RTP run from
memory). The current rawdata under `rawdata/M37/mode_1/` has 328 chunks all
saved **2026-05-11 02:47–03:01** (single coherent md5
`localcfg_bbc2d863|536fc5a2a8f2ecf1fd8c6dfcf2c025cc`) — a different,
post-fix cfg.

When the analyzer is re-run against the *current* rawdata, **all four
sub-row counts agree with the analytic engine prediction within 1–3 %
(pure sampling noise)**. Spec.json and the local engine are correct.

## 1. Rawdata location + chunks scanned

| Source | Path | Chunks | md5 | Saved |
|---|---|---|---|---|
| Real machine (current) | `rawdata/M37/mode_1/` | 328 | `localcfg_bbc2d863\|536fc5a2a8f2ecf1fd8c6dfcf2c025cc` | 2026-05-11 |
| Local sim (M37sim) | `slot_designer/rawdata/M37sim/mode_1/` | 641 (3 md5 groups) | newest = `68fbdafc...` 339 chunks | 2026-05-11 |
| **STALE paytable inference cache** | `configs/paytables/M37_mode1.json` | reported `chunks_scanned: 131` | unknown (no md5 stamped) | mtime **2026-05-08 12:22** |

Total spins in current real-machine rawdata: 2,624,000.
Total pid 9 fires: **221,359** (matches user's "~220k" quote).

## 2. pid 9 match_count distribution (current rawdata, full 328-chunk scan)

| match_count | fires |
|---|---|
| 1 | 218,164 (98.56 %) |
| 2 | 3,195 (1.44 %) |
| 3 | 0 |
| **total** | **221,359** |

(re-confirmed by running `scripts/infer_paytable._infer_one_machine('M37', 1)` in-process.)

## 3. Per-(R1, R2, R3) configuration table — current rawdata, all match_count = 2 pid 9 events

Every row reconstructed from `StopSymbolsByCol` at row index 1 (the sole
payline). Match-count-2 positions decoded from `PayoutByPayline` via
`_decode_position`. Win = `PayoutIdToWinAmount["9"] / BetAmount`.

| (R1, R2, R3) | count | observed mult | spec.json prediction | matches? |
|---|---|---|---|---|
| (blank, mini, wild) | 640 | 2.0 always | mini × 1 wild = 2 (center_booster_alone + 1 side wild) | ✓ |
| (wild, mini, blank) | 598 | 2.0 always | wild × 1 + mini × 1 = 2 | ✓ |
| (wild, minor, blank) | 457 | 5.0 always | wild × 1 + minor × 1 = 5 | ✓ |
| (wild, blank, wild) | 435 | 1.0 always | wild × 1 × wild × 1 (side_wild_alone with second wild) = 1 | ✓ |
| (blank, minor, wild) | 414 | 5.0 always | minor × 1 + wild × 1 = 5 | ✓ |
| (blank, major, wild) | 335 | 10.0 always | major × 1 + wild × 1 = 10 | ✓ |
| (wild, major, blank) | 316 | 10.0 always | wild × 1 + major × 1 = 10 | ✓ |
| **TOTAL** | **3,195** | | | |

**Configurations where R1 or R3 is non-blank AND non-wild: 0.** The
hypothesis ("production engine routes `(wild, mid-wild, 1bar)` → pid 9")
is **rejected**. No such events exist in current real-machine rawdata.

## 4. Analyzer sub-row view (sorted-tuple of contributing symbols)

Aggregated by `tuple(sorted(symbols_at_positions))`, the analyzer-equivalent
output (what user's screenshot would show *if* run against current rawdata):

| sub-row | mc=1 fires | mc=2 fires |
|---|---|---|
| `1× wild` | 67,954 | — |
| `1× mini` | 66,379 | — |
| `1× minor` | 47,500 | — |
| `1× major` | 36,331 | — |
| `1× mini + 1× wild` | — | **1,238** |
| `1× minor + 1× wild` | — | **871** |
| `1× major + 1× wild` | — | **651** |
| `2× wild` | — | **435** |
| **mc=1 total** | **218,164** | |
| **mc=2 total** | | **3,195** |

## 5. Comparison: stale cache (May 8) vs. current analytic vs. current rawdata

### Match-count = 2 pid 9 sub-rows

| sub-row | STALE cache (user screenshot) | CURRENT analytic (engine prediction) | CURRENT rawdata (this report) | deviation analytic↔real |
|---|---|---|---|---|
| 1× mini + 1× wild | 546 | 1,221 | 1,238 | +1.4 % |
| 1× minor + 1× wild | **6,112** | 877 | 871 | −0.7 % |
| 1× major + 1× wild | 2,782 | 669 | 651 | −2.7 % |
| 2× wild | 1,769 | 425 | 435 | +2.4 % |
| **total mc=2** | **11,209** | 3,192 | **3,195** | +0.1 % |

The stale cache (11,209 mc=2 fires) reflects a fundamentally different R2
weighting (minor >> mini) and ~3.5× larger pid 9 mc=2 hit-rate — consistent
with M37 v3 having ~580 % RTP per memory note.

The current analytic prediction agrees with current rawdata within
sampling noise (< 3 % per sub-row, 0.1 % aggregate).

### Why the ordering flipped

Observed R2 row-1 marginals (current rawdata, 400k spin sub-sample):

| symbol | observed | analytic (from weights.json mode 1) |
|---|---|---|
| blank | 50.46 % | 50.46 % |
| mini | 3.70 % | 3.73 % |
| minor | 2.71 % | 2.68 % |
| major | 2.05 % | 2.04 % |
| grand | 0.11 % | 0.11 % |

mini > minor > major (with grand isolated) — matches `weights/mode_1/weights.json`
v6.1 (saved 2026-05-07). Stale cache showed minor:mini ≈ 11:1 → was sampled
when an older mode 1 weights file lived in the repo.

## 6. Verdict

| question | answer |
|---|---|
| Does production engine route `(wild, mid-wild, X non-blank)` → pid 9 instead of pid 1–5? | **No.** Such configs do not occur in current rawdata. |
| Is `spec.json` evaluation_order wrong? | **No.** All 3,195 mc=2 pid 9 events conform to `center_booster_alone` + `side_wild_alone` semantics with correct multipliers. |
| Is the local engine analytic wrong? | **No.** Predicts current rawdata within sampling noise. |
| Is the stale 11,209 number a real machine signal? | It was once. It described an older M37 cfg (probably v3 / 580 %-RTP run). The cache simply was never refreshed after the new sample was pulled. |

## 7. Recommended fix

**No source-code change in `spec.json`, `evaluator.py`, or `infer_paytable.py`.**

The only action needed is **operational**: refresh the cached paytable
inference file so the user's UI / report tooling shows current numbers.

```bash
# rebuild paytable inference for M37 mode 1 against current rawdata
python -m scripts.infer_paytable --machine M37 --mode 1
# this overwrites configs/paytables/M37_mode1.json with the 328-chunk view
# (1238/871/651/435 for the four mc=2 sub-rows)
```

Optional follow-ups (out of scope here; flagging for triage):

- **F1.** `configs/paytables/M37_mode1.json` has **no `cfg_md5` / `rawdata_chunks_signature` stamp**. Any cached inference whose underlying rawdata has rotated is invisibly stale. Consider stamping `cfg_md5 + code_md5 + chunks_scanned + chunks_signature` into the output and surfacing a UI badge when current md5 ≠ cached md5. This matches the universal `md5 is a tag, not a destruction signal` pattern from memory.
- **F2.** The pid 9 sub-row table conflates *all* `center_booster_alone` variants (mini / minor / major) into a single `pay_id=9` row — fine for analyzer purposes but means a sudden weight shift on R2 (like v3 → current) looks like a "7× discrepancy" to a human comparing screenshots taken hours apart. Could split or annotate the sub-rows with the wild-tier composition more prominently.

## 8. Quick reproducibility notes

- Helper used: `attribute_lines_to_pay_ids` from `fresh_slotlab/round_classification.py`.
- Position decode: `(col, row) = ((p+1)//100 - 1, (p+1) % 100)`.
- Grid parse: `StopSymbolsByCol[col].split('-')[row]`.
- `composition_breakdown` (analyzer field driving the user's screenshot) builds the sorted-symbol-tuple aggregation at `scripts/infer_paytable.py` lines 809–858 — purely a rawdata read with no engine logic.
