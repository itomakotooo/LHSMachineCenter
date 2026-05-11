# M15 v8.1 — §14 Visual Rhythm Audit (before / after)

> **Phase A audit** per [`DESIGN_PHILOSOPHY.md`](../../slot_designer/DESIGN_PHILOSOPHY.md) §14.5 mandate + [`ONBOARDING_PROCESS.md`](../../slot_designer/ONBOARDING_PROCESS.md) Stage 4 D gate.
>
> **Scope**: every reel, every symbol, every spacing dimension. Not only bars; not only top symbols. Per philosophy §14.5: "Audit scope: 每条 reel 上每个 symbol 都要审".
>
> **Generated**: 2026-05-11 via `scripts/m15_v81_audit_strip.py` (pre-rearrange) and `scripts/m15_v81_audit_strip.py` (post-rearrange).

---

## 1. Machine-specific §14 thresholds (M15-locked)

Per philosophy §14.2: universal layer is direction-only. M15-specific numbers below come from:
- M15 strip layout (36 stops / reel, 18 non-blank, 3 reels)
- Top Dollar archetype + Wizard of Odds RWB PAR proxy (which has tighter bar clustering than 5-reel video slots can tolerate)
- R3 already-clean baseline (3-run, 0 top-adj) — proves achievable

| dimension | M15 threshold | rationale |
|---|---|---|
| bar-family max consecutive run (non-blank cyclic seq) | **≤ 4 symbols** | 11 bars across 3 tiers in 18 non-blank positions; 5+ run reads as "all bar zone". R3 already at 3 |
| top-symbol max consecutive run (non-blank cyclic seq) | **≤ 1 symbols** | no top-top adjacency; 6 top instances across 3 reels; pairs allowed only with non-top in between |
| top-symbol pair min cyclic distance (full strip, counts blanks) | **≥ 8 stops** | prevents "two top in a flash" feel; ~22% of reel length |
| same-symbol min cyclic gap (full strip, counts blanks) | **≥ 5 stops** | conservative floor; observed natural min was 6-10 stops |
| brand symbol (cherry) cross-reel spread | informational | tracked; not a RED line for M15 (only 2 cherries per reel) |

Thresholds locked into `slot_designer/machines/M15/verify.py` constants `_VISUAL_RHYTHM_*`. **NOT cross-machine** — sister machines (M1, M37, M279) must derive their own from their own archetypes (per philosophy §14.2 + ONBOARDING §2.1 firewall).

---

## 2. Per-reel audit — BEFORE (v8 baseline)

### Reel 1 (v8 — pre-rearrange)

**Non-blank cyclic sequence** (18):
```
['cherry', '3bar', '2bar', '1bar', 'high7', 'doublediamond', '3bar', '2bar', '1bar',
 '3bar', '2bar', '1bar', 'cherry', '3bar', '2bar', 'jackpot', 'high7', 'doublediamond']
```

| dimension | observed | threshold | status |
|---|---|---|---|
| bar-family max consecutive run | **6 symbols** (idx 6-11: 3bar,2bar,1bar,3bar,2bar,1bar) | ≤ 4 | **VIOLATION** |
| top-symbol max consecutive run | **2 symbols** (idx 4-5: high7,doublediamond; idx 16-17: high7,doublediamond) | ≤ 1 | **VIOLATION** |
| top-pair min distance (doublediamond) | 12 stops | ≥ 8 | PASS |
| top-pair min distance (high7) | 12 stops | ≥ 8 | PASS |
| same-symbol min gap (1bar count=3) | 6 stops | ≥ 5 | PASS |
| same-symbol min gap (2bar count=4) | 6 stops | ≥ 5 | PASS |
| same-symbol min gap (3bar count=4) | 6 stops | ≥ 5 | PASS |
| X-Blank-X violations | 0 | (§13) 0 | PASS |

### Reel 2 (v8 — pre-rearrange)

**Non-blank cyclic sequence** (18):
```
['2bar', 'cherry', '3bar', '1bar', 'doublediamond', 'high7', '2bar', '3bar', '1bar',
 '2bar', '3bar', 'cherry', '1bar', '3bar', '2bar', 'jackpot', 'high7', 'doublediamond']
```

| dimension | observed | threshold | status |
|---|---|---|---|
| bar-family max consecutive run | **5 symbols** (idx 6-10: 2bar,3bar,1bar,2bar,3bar) | ≤ 4 | **VIOLATION** |
| top-symbol max consecutive run | **2 symbols** (idx 4-5; idx 16-17) | ≤ 1 | **VIOLATION** |
| top-pair min distance (doublediamond) | 10 stops | ≥ 8 | PASS |
| top-pair min distance (high7) | 14 stops | ≥ 8 | PASS |
| same-symbol min gap (1bar count=3) | 8 stops | ≥ 5 | PASS |
| same-symbol min gap (2bar count=4) | 6 stops | ≥ 5 | PASS |
| same-symbol min gap (3bar count=4) | 6 stops | ≥ 5 | PASS |
| X-Blank-X violations | 0 | (§13) 0 | PASS |

### Reel 3 (v8 — pre-rearrange, already clean)

**Non-blank cyclic sequence** (18):
```
['3bar', 'cherry', '2bar', 'topdollar', '1bar', 'high7', '3bar', 'doublediamond',
 '2bar', '1bar', '3bar', 'cherry', '2bar', 'topdollar', 'jackpot', '1bar', '2bar', 'high7']
```

| dimension | observed | threshold | status |
|---|---|---|---|
| bar-family max consecutive run | 3 symbols | ≤ 4 | PASS |
| top-symbol max consecutive run | 1 symbol | ≤ 1 | PASS |
| top-pair min distance (high7) | 12 stops | ≥ 8 | PASS |
| top-pair min distance (topdollar) | 16 stops | ≥ 8 | PASS |
| same-symbol min gap (1bar count=3) | 10 stops | ≥ 5 | PASS |
| same-symbol min gap (2bar count=4) | 8 stops | ≥ 5 | PASS |
| same-symbol min gap (3bar count=3) | 8 stops | ≥ 5 | PASS |
| X-Blank-X violations | 0 | (§13) 0 | PASS |

**R3 was ALREADY GREEN pre-v8.1** — proves the M15-specific thresholds are achievable, not invented.

---

## 3. Per-reel audit — AFTER (v8.1 post-rearrange)

### Reel 1 (v8.1 — post-rearrange, hamming 4/18 vs v8)

**Non-blank cyclic sequence** (18):
```
['doublediamond', '3bar', '2bar', '1bar', 'high7', '2bar', '3bar', 'doublediamond',
 '1bar', '3bar', '2bar', '1bar', 'cherry', '3bar', '2bar', 'jackpot', 'high7', 'cherry']
```

| dimension | observed | threshold | status |
|---|---|---|---|
| bar-family max consecutive run | **4 symbols** (idx 8-11) | ≤ 4 | **PASS** |
| top-symbol max consecutive run | **1 symbol** | ≤ 1 | **PASS** |
| top-pair min distance (doublediamond) | 14 stops | ≥ 8 | PASS |
| top-pair min distance (high7) | 12 stops | ≥ 8 | PASS |
| same-symbol min gap (1bar count=3) | 6 stops | ≥ 5 | PASS |
| same-symbol min gap (2bar count=4) | 6 stops | ≥ 5 | PASS |
| same-symbol min gap (3bar count=4) | 6 stops | ≥ 5 | PASS |
| same-symbol min gap (cherry count=2) | 10 stops | ≥ 5 | PASS |
| X-Blank-X violations | 0 | (§13) 0 | PASS |

### Reel 2 (v8.1 — post-rearrange, hamming 4/18 vs v8)

**Non-blank cyclic sequence** (18):
```
['doublediamond', 'cherry', '3bar', '1bar', 'doublediamond', '2bar', 'high7', '3bar',
 '1bar', '2bar', '3bar', 'cherry', '1bar', '3bar', '2bar', 'jackpot', 'high7', '2bar']
```

| dimension | observed | threshold | status |
|---|---|---|---|
| bar-family max consecutive run | **4 symbols** (idx 7-10) | ≤ 4 | **PASS** |
| top-symbol max consecutive run | **1 symbol** | ≤ 1 | **PASS** |
| top-pair min distance (doublediamond) | 8 stops | ≥ 8 | PASS (at floor) |
| top-pair min distance (high7) | 16 stops | ≥ 8 | PASS |
| same-symbol min gap (1bar count=3) | 8 stops | ≥ 5 | PASS |
| same-symbol min gap (2bar count=4) | 6 stops | ≥ 5 | PASS |
| same-symbol min gap (3bar count=4) | 6 stops | ≥ 5 | PASS |
| same-symbol min gap (cherry count=2) | 16 stops | ≥ 5 | PASS |
| X-Blank-X violations | 0 | (§13) 0 | PASS |

### Reel 3 (v8.1 — unchanged from v8, hamming 0/18)

R3 was already clean — algorithm correctly identified no repair needed.

---

## 4. Marginal preservation proof

Per-(reel, symbol) multiset preserved by construction (algorithm only permutes positions within the non-blank multiset of each reel; weights are permuted alongside their original symbols).

Direct numerical verification (analytic_profile across modes 1/2/5/7):

| mode | metric | v8 (pre-rearrange) | v8.1 (post-rearrange) | delta |
|---|---|---:|---:|---:|
| 1 | base RTP | 35.0774% | 35.0774% | 0.0000% |
| 1 | hit rate | 17.4041% | 17.4041% | 0.0000% |
| 2 | base RTP | 99.0333% | 99.0333% | 0.0000% |
| 2 | hit rate | 33.5417% | 33.5417% | 0.0000% |
| 5 | base RTP | 108.3814% | 108.3814% | 0.0000% |
| 5 | hit rate | 33.6078% | 33.6078% | 0.0000% |
| 7 | base RTP | 21.9902% | 21.9902% | 0.0000% |
| 7 | hit rate | 11.4800% | 11.4800% | 0.0000% |

**Zero drift confirmed.** RTP, hit rate, family share, and all derived band metrics are byte-identical pre/post.

---

## 5. Cross-reel brand (cherry) distribution

Cherry is the visual signature symbol. Pre/post comparison:

| reel | v8 cherry positions | v8.1 cherry positions | first-half / second-half split |
|---|---|---|---|
| R1 | [1, 25] | [25, 35] | v8: 1/1; v8.1: 0/2 (both in second half) |
| R2 | [3, 23] | [3, 23] | 1/1 (unchanged) |
| R3 | [3, 23] | [3, 23] | 1/1 (unchanged) |

R1 cherry both shifted to second half. **Not flagged as RED** — only 2 instances per reel makes "even cross-reel spread" statistically weak; the symbol is still visible at multiple stops. Tracked as informational.

---

## 6. Verify red lines locked

`slot_designer/machines/M15/verify.py` [VISUAL-RHYTHM] category checks all of the above per reel:

```python
# constants in verify.py
_VISUAL_RHYTHM_BAR_FAMILY = ("1bar", "2bar", "3bar")
_VISUAL_RHYTHM_TOP_SYMBOLS = ("doublediamond", "high7", "topdollar")
_VISUAL_RHYTHM_MAX_BAR_FAMILY_RUN = 4
_VISUAL_RHYTHM_MAX_TOP_RUN = 1
_VISUAL_RHYTHM_MIN_TOP_PAIR_DISTANCE_STOPS = 8
_VISUAL_RHYTHM_MIN_SAME_SYMBOL_GAP_STOPS = 5
```

Inject-bug regression: [`test_inject_visual_rhythm_violation`](../../tests/machines/test_M15_verify_inject_bug.py) mutates R1 nb-positions to create a longer bar run → asserts [VISUAL-RHYTHM] RED → reverts → asserts clean. Confirms verify.py truly catches a §14 violation, not just paper-passes.

Total [VISUAL-RHYTHM] check count: **30** (3 reels × {1 bar-run + 1 top-run + 3 top-pair-distance + ~6 same-symbol-gap}) — all GREEN on v8.1.
