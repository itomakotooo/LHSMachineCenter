# M43 Stage 2.5 Supplementary — pay_id 8 predicate lock-down

**Session**: 2026-05-14  
**Scope**: Resolve LOW-confidence pay_id 8 ("wild_blank_special") trigger rule from 01c §3  
**Rawdata**: 42 chunks, 650,000 paid spins (ST=1 only used here)  
**Script**: `session_artifacts/M43/scripts/analyze_pay_id_8.py`

---

## §1 Hit enumeration

| metric | value |
|---|---|
| Total ST=1 paid rounds scanned | 650,000 |
| Pay_id 8 hits | **829** |
| Hit rate | 1 in 784 paid rounds (0.1275%) |
| Chunk coverage | all 42 chunks contain hits (uniform distribution) |

**Payout multiplier histogram** (bet = 1000):

| win credits | multiplier | count | share |
|---|---|---|---|
| 5,000 | 5× | 507 | 61.2% |
| 10,000 | 10× | 303 | 36.6% |
| 20,000 | 20× | 19 | 2.3% |

Average: 7.17× bet (vs 5× base, consistent with off-payline wild boosting).  
RTP contribution: **0.915 pp** out of 93.23% total (as expected from 02 engine notes estimate of ~1pp).

Note: 01c §3 cited 912 hits; actual count is 829 (difference due to 01c sampling only 41 chunks; current scan covers all 42 final production chunks). The 01c estimate was ~10% high but the structural characterization holds.

---

## §2 Mid-row (payline) payload distribution

The payline is (R1-mid, R2-mid, R3-mid). **All 829 pay_id=8 rounds have the payline consisting of exactly 2 wild-family cells (wild / blankup / blankdown) and 1 plain blank.**

Top payline patterns (n=829 hits):

| R1-mid | R2-mid | R3-mid | count | share |
|---|---|---|---|---|
| blank | blankdown | blankdown | 125 | 15.1% |
| blank | blankup | blankdown | 112 | 13.5% |
| blank | blankup | blankup | 106 | 12.8% |
| blank | wild | blankup | 102 | 12.3% |
| blank | wild | blankdown | 100 | 12.1% |
| blank | blankdown | blankup | 90 | 10.9% |
| blank | blankup | wild | 22 | 2.7% |
| blankup | wild | blank | 14 | 1.7% |
| ... (20 more patterns, all 2wf+1blank combinations) | | | |

Observation: blank lands on R1-mid in 81.9% of hits (679/829). This reflects the much lower wild-family marginal on R1 (0.16% vs 1.85% on R2 and 1.39% on R3), making R1 the most likely "blank" position when R2 and R3 both show wild-family symbols.

Wild-family symbol pair observed on payline:

| symbol pair | count | share |
|---|---|---|
| blankdown + blankup | 238 | 28.7% |
| blankup + wild | 163 | 19.7% |
| blankdown + blankdown | 144 | 17.4% |
| blankdown + wild | 140 | 16.9% |
| blankup + blankup | 125 | 15.1% |
| wild + wild | 19 | 2.3% |

---

## §3 Adjacent row (top+bot) pattern distribution

When pay_id 8 fires, the top and bottom rows carry the wild's neighbors (blankup/blankdown or wild itself on adjacent stops, and 7s from the natural strip layout).

**Top row** (R1-top, R2-top, R3-top) — selected most common:
- `7 | wild | wild`: 31 hits (3.7%) — R1 top = 7 (from strip position), R2 and R3 show wild on top
- `7 | wild | 1bar`: 28 hits (3.4%)
- `7 | blankdown | wild`: 27 hits (3.3%)
- Top row generally reflects R2/R3 wild-family cluster (blankdown / wild)

**Bottom row** (R1-bot, R2-bot, R3-bot) — selected most common:
- `1bar | blankup | wild`: 48 hits (5.8%) — R1 bot = 1bar, R2/R3 bot = blankup/wild
- `1bar | wild | wild`: 45 hits (5.4%)
- `1bar | 7 | 7`: 43 hits (5.2%) — the "near-win" pattern: wild flanked by 7s in the window
- `1bar | 7 | wild`: 40 hits (4.8%)
- `1bar | blankup | 7`: 39 hits (4.7%)

The adjacent-row distribution confirms this is the "wild's physical strip context" showing up in the window. The key is the mid row, not the adjacent rows.

---

## §4 Wild + blankup + blankdown position cross-tab

Position frequency across all 829 pay_id=8 hits (% of rounds having that symbol at that cell):

| Cell | wild | blankup | blankdown | 7 | any-wf-family |
|---|---|---|---|---|---|
| R1-top | 6.6% | 0.0% | 5.8% | 20.7% | 12.4% |
| R1-mid | 5.8% | 6.6% | 5.7% | 0.0% | **18.1%** |
| R1-bot | 5.7% | 5.8% | 0.0% | 15.0% | 11.5% |
| R2-top | 32.4% | 0.0% | 29.6% | 2.2% | **62.0%** |
| R2-mid | 29.6% | 32.4% | 31.7% | 0.0% | **93.7%** |
| R2-bot | 31.7% | 29.6% | 0.0% | 33.1% | **61.3%** |
| R3-top | 39.4% | 0.0% | 5.8% | 3.4% | 45.2% |
| R3-mid | 5.8% | 39.4% | 42.9% | 0.0% | **88.2%** |
| R3-bot | 42.9% | 5.8% | 0.0% | 40.2% | 48.7% |

Key observations:
- R2-mid and R3-mid are heavily wild-family concentrated (93.7% and 88.2%). These are the two payline positions that carry the wild-family symbols.
- R1-mid is only 18.1% wild-family — this is the "blank" position in 81.9% of hits.
- blankup and blankdown do NOT appear on top/bot rows (by strip definition — blankup is only above wild, blankdown only below wild, so they never appear on top-of-top or bottom-of-bottom edges of the visible window).

**Window wild-family count distribution:**

| cells in window | count | share | payout |
|---|---|---|---|
| 4 wf cells | 507 | 61.2% | 5× |
| 5 wf cells | 303 | 36.6% | 10× |
| 6 wf cells | 19 | 2.3% | 20× |

---

## §5 Predicate decision

### Three candidates from 01c §3

| candidate | hit coverage | FP rate on 649,171 non-pay_id-8 rounds | conclusion |
|---|---|---|---|
| **A** — near 3× 7 (3 sevens in window, not all on payline) | 6.3% (52/829) | 1.780% | REJECT — misses 93.7% of hits |
| **B_v2** — exactly 2 wf-family cells on payline + exactly 1 blank cell | **100.0% (829/829)** | **0.000% (0/649,171)** | **ACCEPT** |
| **C** — payline all blank/wf + at least 1 seven off payline | 49.6% (411/829) | 19.430% | REJECT — 50% miss + unacceptably high FP |

### Predicate B_v2 — exact definition

**Trigger condition (pay_id 8 fires if and only if):**

```
payline = [R1-mid, R2-mid, R3-mid]
n_wf  = count(s in payline where s in {wild, blankup, blankdown})
n_blank = count(s in payline where s == 'blank')

pay_id_8_fires  iff  n_wf == 2  AND  n_blank == 1
```

Equivalently: the payline has **2 wild-family markers and 1 plain blank** (no bar or 7 symbol on payline).

**Why this is mechanically clean**: when wild (a single stop) lands adjacent to the payline, it places blankup above itself and blankdown below itself on the strip. If two reels show their wild-adjacent markers on the payline (n_wf=2) and the third reel shows a literal blank (not a paying symbol), the engine awards pay_id 8 as a "near-wild" consolation. This is distinct from pay_id 9 (n_wf=1 on payline, the other single-wild-marker consolation) and from regular bar pays where a bar symbol appears alongside wild markers.

**Disambiguation from bar wins with doubling**: rounds with 2 wf + 1 bar on payline (e.g. `[1bar, blankdown, blankup]`) are assigned to pay_id 6 with doubling (not pay_id 8). The discriminator is precisely the non-wf payline cell: blank → pay_id 8; bar/7 → bar/seven pay_id with wild multiplier.

### Multiplier rule (deterministic, 100% match on all 829 hits)

```
win = 5 * 2^(window_wf_count - 4) * bet

where window_wf_count = count of wild/blankup/blankdown in all 9 cells of the 3x3 grid
```

| window_wf_count | multiplier | formula | hits |
|---|---|---|---|
| 4 | 5× | 5 × 2^0 | 507 (61.2%) |
| 5 | 10× | 5 × 2^1 | 303 (36.6%) |
| 6 | 20× | 5 × 2^2 | 19 (2.3%) |

This is NOT the same as the off-payline wild doubling rule described in 01c §3 (which doubles bar pays by adding an off-payline wild). The pay_id 8 multiplier is a separate payline-tier rule where the base pay tier is 5× and each additional wild-family symbol in the window adds a 2× multiplier.

### RECOMMENDATION (HIGH confidence)

**Implement pay_id 8 with predicate B_v2 and the 5×2^(wf-4) multiplier rule.**

Confidence: **HIGH**
- 100.0% hit coverage (829/829), 0 false positives (0/649,171 non-pay_id-8 rounds)
- Multiplier formula: 100% exact match on all 829 hits (no exceptions)
- No co-occurring pay_ids (pay_id 8 never fires alongside another pay_id in the same round)
- Mechanically consistent with the strip layout: blankup/blankdown are physical adjacent-wild markers; 2 of them on the payline + 1 plain blank = "two wilds almost there"
- Base multiple 5× aligns with pay_id 7 (any-3-bars, also 5× base) — pay_id 8 is the "near-wild" equivalent at the same tier

No 2nd-choice fallback needed — the data is unambiguous.

---

## §6 False-positive check

Predicate B_v2 was tested against all 649,171 non-pay_id-8 ST=1 rounds.

**Result: 0 false positives (0/649,171, 0.0000%)**

This is a structural zero, not a statistical near-zero. Explanation: rounds where payline has exactly 2 wf-family cells and 1 blank are assigned pay_id 8 by the engine with no exceptions. Rounds where payline has 2 wf cells + 1 bar/7 cell are assigned the corresponding bar/seven pay_id instead (confirmed: pay_id=6 gets 333 such rounds; pay_id=5 gets 77; pay_id=4 gets 28; pay_id=3 gets 12).

**The predicate and the pay_id assignment are 1-to-1.** Implementer can encode this as an exact rule with no ambiguity.

---

## §7 Verification protocol for Implementer

After implementing pay_id 8 in spec.json, run the following checks against a virtual sim of >= 20k paid spins:

### Check 1 — Pay_id 8 rate
| metric | production value | tolerance |
|---|---|---|
| pay_id 8 hits per 100k paid rounds | ~127.5 (829/650k × 100k) | ± 20% (Poisson noise on small n) |
| hit rate formula | depends on P(2wf+1blank on payline) from reel weights | must match reel-weight-derived analytic |

### Check 2 — Payout per hit distribution
| metric | production value | tolerance |
|---|---|---|
| share of 5× hits | 61.2% | ± 5 pp |
| share of 10× hits | 36.6% | ± 5 pp |
| share of 20× hits | 2.3% | ± 2 pp |
| avg multiplier per hit | 7.17× | ± 0.5× |

### Check 3 — RTP contribution
| metric | production value | tolerance |
|---|---|---|
| pay_id 8 RTP contribution | 0.915 pp | ± 0.2 pp (Monte Carlo noise on N=20k) |
| RTP contribution at N=650k | 0.915 pp | ± 0.05 pp |

### Check 4 — Multiplier formula
Every simulated pay_id 8 hit must satisfy: `win == 5 × 2^(window_wf_count - 4) × bet` where window_wf_count is the count of wild/blankup/blankdown across all 9 cells of the 3×3 grid. Zero exceptions allowed.

### Check 5 — No co-occurrence
Pay_id 8 must never fire in the same round as another pay_id. Zero co-occurrences in production; virtual sim must also show zero.

### Check 6 — Predicate exclusivity
In virtual sim, scan all ST=1 rounds and verify: every round with exactly 2 wf-family payline cells + 1 blank payline cell has pay_id 8 assigned. Every round with pay_id 8 has exactly 2 wf-family + 1 blank on payline. 100% both directions.

---

## §8 Implementation spec for Implementer

This section provides the concrete encoding for spec.json `pays` block entry for pay_id 8.

### Trigger rule (to add to engine evaluator or pays block)

```
pay_id: 8
family: wild_blank_special
trigger:
  payline_wf_count == 2   (wild/blankup/blankdown cells on mid-row)
  payline_blank_count == 1  (plain blank on mid-row)
  payline_bar_count == 0    (no bar/7 symbol — distinguishes from doubled bar pays)
multiplier:
  base: 5
  window_multiplier: 2^(window_wf_count - 4)
  where window_wf_count = total wild/blankup/blankdown in all 9 cells
  valid range: window_wf_count in {4, 5, 6}
```

Alternatively, the multiplier can be expressed as a window_wf_count → payout table:

```
  window_wf_count=4 -> payout = 5 * bet
  window_wf_count=5 -> payout = 10 * bet
  window_wf_count=6 -> payout = 20 * bet
```

**Implementation path recommendation** (per 02 engine notes §Open Issues #2):
This is most cleanly implemented as a plugin-side post-processor that inspects the full 3×3 grid after the standard payline evaluator runs. The standard evaluator will return no match (since blank/blankup/blankdown are not bar/7 symbols), and the plugin catches the 2wf+1blank pattern and assigns pay_id 8 with the window-count-based multiplier.

---

## Cross-signal sanity

- Sum of pay_id RTPs must still equal summary RTP after adding pay_id 8 implementation.
- pay_id 8 RTP contribution: 0.915 pp.
- Previous total estimated: 88.6% (engine without pay_id 8 + off-payline doubling).
- Adding pay_id 8 alone accounts for ~1pp of the 4.6pp gap.
- Remaining gap (~3.6pp) is primarily off-payline wild doubling (02 notes estimate ~2-3pp) + mini-game trigger rate calibration (~1pp).

---

## Sources

- Rawdata: `rawdata/M43/mode_1/` chunks 0001-0041 (42 files, 650k ST=1 rounds)
- Analysis script: `session_artifacts/M43/scripts/analyze_pay_id_8.py`
- Prior context: `session_artifacts/M43/01c_field_analysis.md` §3 (3 candidates), `session_artifacts/M43/02_engine_implementation_notes.md` Open Issues #1
- Per `memory/feedback_no_hardcode.md`: all semantics inferred from M43 rawdata only
- Per `memory/feedback_self_verify_output.md`: predicate verified both directions (hit coverage 100% + FP 0%), multiplier formula verified 100% exact on all 829 hits
- Per `memory/feedback_paid_round_default.md`: all rates expressed per paid round (ST=1)
