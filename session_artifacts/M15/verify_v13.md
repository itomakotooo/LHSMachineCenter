# M15 v13 mode 1 FINAL_E — V independent verification

> **Verdict: FAIL.** FINAL_E passes the 12 quantitative USER_HARDLINES.md v5 hardlines (H1–H12) AND bell-shape direction, BUT fails 4 distinct philosophy / verify.py mandates including 2 user-explicit ones (`§7 wild_pure cadence`, base hit < 15% floor in verify.py [HIT] mode 1). Plus D's design_v13.md has a documentation arithmetic bug (R2 row sums to 100.6%, not 100%).
>
> Recommendation: do NOT ship FINAL_E as-is. Two REAL blockers (one structural, one fixable). Discuss with main session + user before sign-off.

---

## Section 1: Numeric reproduction (V vs D)

V reproduced D's full closed-form analytic pipeline INDEPENDENTLY (no import from D's design script — only `slot_designer.core.devtools.analytic_rtp.analytic_profile_from_marginals` + `_round_payout_distribution` shared primitives).

**Key methodology fix**: D's `design_v13.md §1 table` lists R2 blank = **47.30%**, but D's actual `cand_final_e()` function uses non-blank fractions summing to 53.30% → blank = **46.70%** (residual). The 47.30 row sums to **100.6%** which is arithmetically impossible. V used D's script's actual values (46.70% R2 blank) for apples-to-apples comparison.

| Metric | V (recomputed) | D (claimed) | diff | flag |
|---|---:|---:|---:|:--:|
| total_rtp | **94.0533** | 94.0700 | -0.0167 | ok |
| hit_session | **15.3411** | 15.3400 | +0.0011 | ok |
| r1_blank | **39.0874** | 39.1000 | -0.0126 | ok |
| ge1_lt5 | **13.0252** | 13.0200 | +0.0052 | ok |
| ge5_lt10 | **14.1609** | 14.1600 | +0.0009 | ok |
| ge10_lt20 | **6.6468** | 6.6500 | -0.0032 | ok |
| ge20_lt50 | **23.5508** | 23.5600 | -0.0092 | ok |
| ge50_lt100 | **24.7014** | 24.7100 | -0.0086 | ok |
| ge100_lt200 | **9.7584** | 9.7600 | -0.0016 | ok |
| ge200_lt500 | **2.1475** | 2.1500 | -0.0025 | ok |
| sum_1_20 | **33.8329** | 33.8200 | +0.0129 | ok |
| base_rtp | **43.4887** | 43.4700 | +0.0187 | ok |
| feature_rtp | **50.5646** | 50.6000 | -0.0354 | ok |

All metrics agree within tolerance ≤ 0.04pp (well under the 0.1pp threshold). **D's reported metrics are reproducible.**

**Top-level deltas vs D**: (1) total_rtp 0.017pp lower, (2) feature_rtp 0.035pp lower, (3) sum_1_20 0.013pp higher. None material.

### Documentation arithmetic bug (D's design_v13.md §1 table)

D's `design_v13.md` Section 1 table claims R2 blank = 47.30%. The non-blank row entries are:
```
R2: 1bar 30.00 + high7 12.00 + 2bar 4.50 + cherry 3.00 + dd 2.20 + 3bar 1.20 + jp 0.40 = 53.30%
```
So R2 blank residual = 100 − 53.30 = **46.70%**, not 47.30%. The 47.30 + 53.30 = 100.60 is the bug. D's script `cand_final_e()` does not have this bug (it sets blank as 1 − sum_non_blank automatically). **Action**: D should fix the table for the user-facing doc, but it doesn't affect the actual recommendation since the script is the source of truth.

---

## Section 2: 14 hardline check (USER_HARDLINES.md v5)

V independent recomputation:

| # | Hardline | V value | Target | Status |
|---|---|---:|---|:--:|
| H1 | hit_session (session-centric) | **15.3411%** | [15, 18] | PASS |
| H2 | total_rtp | **94.0533pp** | [94, 96] | PASS (0.05pp margin) |
| H3 | R1 blank | **39.0874%** | [30, 40] | PASS (0.91pp margin) |
| H4 | ge1_lt5 | **13.0252pp** | [10, 15] | PASS (1.97pp margin) |
| H5 | sum_1_20 | **33.8329pp** | [28, 36] | PASS (2.17pp margin) |
| H6 | ge20_lt50 | **23.5508pp** | [22, 32] | PASS (1.55pp margin) |
| H7 | ge50_lt100 | **24.7014pp** | [17, 27] | PASS (2.30pp margin) |
| H8 | ge100_lt200 | **9.7584pp** | [4, 14] | PASS (4.24pp margin) |
| H9 | ge200_lt500 | **2.1475pp** | [0, 7.3] | PASS (5.15pp margin) |
| H10 | R1 jackpot marg | **0.4003%** | [0, 0.6] | PASS |
| H11 | R2 jackpot marg | **0.4004%** | [0, 0.6] | PASS |
| H12 | R3 jackpot marg | **0.2998%** | [0, 0.6] | PASS |
| H13 | paytable byte-equal | locked | byte-equal | PASS (verify.py [PAYTABLE-LOCK] GREEN) |
| H14 | feature_params v9 byte-equal | locked | byte-equal | PASS (V wrote fp from v9 doc) |

**All 14 user-explicit hardlines PASS.**

### Bell-shape direction

- g15 = **13.03pp**
- g510 = **14.16pp** ← peak
- g1020 = **6.65pp**
- peak_strength (max(g510,g1020) − g15) = **+1.14pp**
- direction g15 < (g510+g1020)? **TRUE** (13.03 < 20.81)

**Bell-shape direction PASS.**

---

## Section 3: M15 verify.py result (mode 1 RED categories)

`verify.py` writes/reads weights from a temp dir (mode 1 = FINAL_E, modes 2/5/7 = current production v9). Exit code 1, total **22 REDs**.

**Baseline comparison**: V also ran verify.py against current production v9 weights (mode 1 = v9 ship state, modes 2/5/7 = same). v9 shipped with **2 RED** ([PWDF-FLOOR] mode 1 topdollar 21.90% < 22%, [PWDF-FLOOR] mode 7 dd 31.58% < 34%). v9 mode 1 was effectively CLEAN. Swapping in FINAL_E introduces **~12 new mode 1 RED** (with cascading m7/cross-mode bringing total to 22). This is a substantial verify.py regression — design v5 intent and verify.py band definitions have drifted apart.

### Mode 1 only RED — 12 fails

| RED line | Cause | Structural / Fixable |
|---|---|---|
| `[HIT]` base hit 0.1424 < 0.1500 floor | Cherry+bar density chosen to keep g15 ≤15pp ceiling | **STRUCTURAL within v5 hardlines** — user H1 is session-centric (passes) but verify.py's [HIT] is base-only (fails). Mismatch between user H1 wording and verify.py band. Either widen verify.py [HIT] to [0.14, 0.18] or recategorize as informational once session-centric H1 added. |
| `[RTP]` total RTP 93.81pp band [94, 96] | **(in V run)** | NOT firing in re-run — V got 94.05pp; was a stale 0.26pp delta from the 47.30 vs 46.70 R2 table bug; FIXED |
| `[FAMILY-SHARE]` cherry1 19.92% (floor 26.0%) | Cherry pulled low to fit g15 ceiling | **STRUCTURAL within v5** — v9 had cherry1 share 50%+; current v5 design intent (1bar-dominant bell) inherently shifts share away from cherry. Need user direction to relax verify.py family floor or adjust design. |
| `[FAMILY-SHARE]` bar_mixed 10.03% (floor 12.0%) | 2bar/3bar pushed low to keep g15 down | structural with v5 ceiling — minor margin (~2pp short) |
| `[FAMILY-SHARE]` bar1 41.89% (cap 12.0%) | 1bar is the bell engine | **STRUCTURAL** — v5 bell intent IS "1bar carries g510 peak" → bar1 share dominates by design. Cap conflict with design intent. |
| `[FAMILY-SHARE]` bar2 1.16% (floor 10.0%) | 2bar 4.5% per reel × cubed ≈ 1.16% RTP share | structural under 1bar-bell design |
| `[FAMILY-SHARE]` bar3 0.31% (floor 5.0%) | 3bar 1.2% per reel × cubed ≈ 0.31% RTP share | structural under 1bar-bell design |
| `[FAMILY-SHARE]` high7 23.24% (cap 8.0%) | high7 15/12/8 to fill R1 density gap | structural — without high7 R1 blank would exceed 40 cap |
| `[FAMILY-SHARE]` wild_pure 0.29% (floor 0.4%) | dd 1.8/2.2/1.6 marginal gives pay_id 1 cadence beyond band | **same root as §7** — connects to wild_pure cadence below |
| `[PER-PAY-FLOOR]` pay_id 71 (cherry2) 0.27% < 0.4% floor | cherry low for g15 ceiling | structural |
| `[PER-PAY-FLOOR]` pay_id 4 (cherry3) 0.0026% < 0.005% floor | cherry low for g15 ceiling | structural |
| `[PWDF-FLOOR]` doublediamond R2 25.51% < 28% floor | dd marginal 2.2% × strip layout window | **fixable** — increase R2 dd marginal slightly (~0.3pp would lift), but trades off RTP |
| `[TOP-JACKPOT-CADENCE]` pay_id 1 wild_pure 1/157670 (band 1/50k-1/100k) | dd 1.8/2.2/1.6 → cubed = 6.34e-6 | **STRUCTURAL** — to get into [1/50k, 1/100k], need dd cube ≈ 1.5e-5 → dd ≈ 2.46% per reel. Current 1.8/2.2/1.6 is at design limit per archetype. D explicitly flagged this caveat in design_v13.md §9.6 Q6. |

### Mode 2/5/7 RED — 9 fails (untouched modes, expected; not a v13 redesign concern)

- `[MODE7-BIGPAY]` 3 fails — m7 weights unchanged but m1 changed, so m7/m1 ratios shift
- `[MODE7-CUT]` 5 fails — m7 small-pay no longer < m1 because m1 cherry+bar pushed down
- `[PWDF-FLOOR]` mode 7 dd 31.58% < 34% floor — m7 issue, not v13 mode 1

### Cross-mode RED — 1 fail (cascading from mode 1)

- `[TOP-JACKPOT-ESC]` m2/m1 wild_pure freq ratio 2.047 cap 1.5 — m2 unchanged; m1 wild_pure dropped → ratio jumps. Cascading from mode 1 change.

### Categorization summary

- **6 structural mode 1 RED** intrinsic to v5 v13 design intent (cherry low, 1bar dominant, dd at limit)
- **2 fixable mode 1 RED** (dd PWDF R2 marginal + bar_mixed share — both small magnitude)
- **2 user-explicit philosophy violations** (§7 cadence + base hit floor) — see §4
- **9 cascading mode 2/5/7 RED** (untouched modes; ignore for v13)

---

## Section 4: Philosophy §7 / §12 / §13 / §14 / §15 audit

### §7 wild_pure cadence (M15 carve [1/50k, 1/100k])

V computed: pay_id 1 hit = 0.0006344% → **1 in 157670**.

- Target band: **[1/50k, 1/100k]**
- Actual: **1 in 157670**, **57.7k outside upper bound**.
- Status: **FAIL** — confirmed exactly as D's caveat in design_v13.md §9.6 Q6.

**Structural?** D claimed "mechanism B only redistributes blanks, doesn't change wild_pure marginal". V confirms: dd marginal R1/R2/R3 = 1.8/2.2/1.6%. P(pay_id 1) = product of dd marginals = 0.018 × 0.022 × 0.016 = 6.34e-6 → 1/157670. To hit 1/100k ceiling, need product ≥ 1e-5 → e.g. dd = 2.15% uniform. To hit 1/50k floor, dd ≈ 2.71% uniform. **Fixable by increasing dd marginal** (would push other metrics up — wild_pure RTP from 0.13pp → ~0.85pp, dd PWDF would also lift).

### §12 reel asymmetry (Strickland/Reid)

| Constraint | R1 | R3 | Status |
|---|---:|---:|:--:|
| R1 blank ≤ R3 blank | 39.09% | 56.12% | **PASS** |
| R1 jackpot ≥ R3 jackpot | 0.40% | 0.30% | **PASS** |
| R1 doublediamond ≥ R3 doublediamond | 1.80% | 1.60% | **PASS** |

**§12 PASS.**

### §13 blank flank diversity (no X-Blank-X same-symbol bracketing)

| Reel | Violations |
|---|---:|
| R1 | 0 PASS |
| R2 | 0 PASS |
| R3 | 0 PASS |

**§13 PASS.** (Same strip as v9 — already passed v8.1 strip rearrange.)

### §14 visual rhythm (M15-specific thresholds)

| Reel | bar-family max run (cap 4) | top max run (cap 1) |
|---|---:|---:|
| R1 | 4 PASS | 1 PASS |
| R2 | 4 PASS | 1 PASS |
| R3 | 3 PASS | 1 PASS |

All top-pair min distance ≥ 8 stops (PASS), all same-symbol min cyclic gap ≥ 5 stops (PASS).

**§14 PASS** (strip rearrange from v8.1 still valid).

### §15 PWDF (mechanism B applied — same as v9)

Per §15.9 active-optimization mandate. M15 mode 1 floors: dd 28%, high7 28%, topdollar 22%, mid-pay 3%.

| symbol | max p_window | reel | floor | status |
|---|---:|:---:|---:|:--:|
| doublediamond | **25.51%** | R2 | 28.0% | **FAIL** (-2.49pp under) |
| high7 | 35.28% | R2 | 28.0% | PASS |
| topdollar | 23.51% | R3 | 22.0% | PASS |
| 3bar | 18.05% | R3 | 3.0% | PASS |
| 2bar | 27.81% | R2 | 3.0% | PASS |
| 1bar | 43.80% | R1 | 3.0% | PASS |
| cherry | 13.77% | R1 | 3.0% | PASS |

**§15 dd top-symbol floor FAIL.** Doublediamond max p_window across all reels is 25.51% (achieved on R2), 2.49pp under the 28% floor. Root cause: dd marginal R1/R2/R3 = 1.80/2.20/1.60% — same root as §7 wild_pure cadence (low dd marginal). Mechanism B is already maximizing top-symbol visibility per current marginals, so lifting requires raising dd marginal.

---

## Section 5: PWDF table (per top symbol per reel — with mechanism B)

| symbol | reel | p_window | p_mid | window/mid ratio |
|---|---:|---:|---:|---:|
| doublediamond | 1 | 21.29% | 1.80% | 11.82x |
| doublediamond | 2 | 25.51% | 2.20% | 11.58x |
| doublediamond | 3 | 12.81% | 1.60% | 8.01x |
| high7 | 1 | 34.50% | 15.01% | 2.30x |
| high7 | 2 | 35.28% | 12.01% | 2.94x |
| high7 | 3 | 30.41% | 7.99% | 3.80x |
| topdollar | 1 | 0.00% | 0.00% | n/a |
| topdollar | 2 | 0.00% | 0.00% | n/a |
| topdollar | 3 | 23.51% | 1.10% | 21.39x |

Mechanism B is delivering 8-21× window/mid lift for top symbols (the active-optimization mandate is working). The shortfall is purely from dd marginal being too low to start with.

---

## Section 6: Final verdict

**FAIL** — FINAL_E should NOT be shipped as-is.

### What passed (12/12 user-explicit hardlines + bell + §12/§13/§14)
- All 12 quantitative USER_HARDLINES.md v5 hardlines (H1–H12) PASS in V's recomputation
- All within-tolerance of D's claim (max diff 0.04pp, well under 0.1pp threshold)
- Bell-shape direction PASS (peak strength +1.14pp at g510)
- §12 reel asymmetry, §13 blank flank, §14 visual rhythm PASS

### What failed (4 categories — 2 user-relevant)

| Issue | Type | Severity |
|---|---|---|
| **§7 wild_pure cadence 1/157670** outside [1/50k, 1/100k] | Philosophy direction (D flagged in caveats) | **HIGH** — user-stated philosophy carve at user_brief level |
| **verify.py [HIT] base hit 0.1424 < 0.15 floor** | verify.py mandate (base-only, NOT user-session H1) | **MEDIUM** — design v5 H1 is session-centric (passes); verify.py band is base-only. Either widen verify.py or design must lift cherry/bar slightly. |
| **§15 PWDF dd max p_window 25.51% < 28% floor** | Philosophy mandate (verify.py [PWDF-FLOOR]) | **MEDIUM** — connected to §7 cadence (low dd root) |
| **verify.py [FAMILY-SHARE] 7 mode 1 fails** + **[PER-PAY-FLOOR] 2 mode 1 fails** | Structural to v5 1bar-bell design intent | **DESIGN INTENT** — these are pre-bell verify.py floors that don't reflect bell-design v5 reality. User direction needed to relax/restructure. |

### Recommended next step

1. **Confirm §7 wild_pure cadence**: this is a USER philosophy direction (user_brief carve-out: m1 base ∈ [1/50k, 1/120k]). D's FINAL_E violates by 57.7k. Either:
   - Increase dd marginal to ~2.5% per reel (would also fix §15 dd PWDF floor) — RTP changes
   - Or user must explicitly relax §7 cadence band (it's already a carve-out from philosophy)
2. **Decide on verify.py [HIT] band semantics**: user H1 is session-centric, verify.py [HIT] is base-only. Need user direction whether to widen verify.py or constrain design.
3. **Decide on family-share floors**: if v5 1bar-bell design intent is locked, verify.py family-share floors need restructuring (D's verify.py was authored under v4 hardlines / 50:50 bar share design). These RED are NOT real regressions; they're verify.py and design intent drifting apart.

### Comparison vs alternatives (D's table)

| Metric | FINAL_E | VVV | WWW | FINAL_F |
|---|---:|---:|---:|---:|
| total_rtp | 94.07 | 94.61 | 95.94 | 94.31 |
| g15 | 13.02 | 13.24 | 13.46 | 12.93 |
| Peak strength | 1.13pp | 0.26pp | 0.03pp | 0.44pp |

**All 4 candidates share the dd-low (and thus §7 cadence + §15 dd PWDF) problem** because dd marginal across all 4 is in the same 1.6-2.5% range. V's recommendation: a 5th candidate with dd ≈ 2.5% per reel uniform would likely fix both §7 and §15 dd, at small RTP cost. Or accept the §7 caveat and document it as a user-explicit relaxation.

---

## Section 7: Self-critique

If user says "PASS, ship FINAL_E", what would the first criticism be?

### Q1: "You said all 14 hardlines PASS but verify.py says 12 mode 1 REDs. Which one am I supposed to trust?"

**A**: The 14 USER_HARDLINES.md hardlines are USER-EXPLICIT (user-stated, not agent-derived); verify.py REDs include philosophy + archetype direction. The 12 USER hardlines PASS unambiguously. The verify.py REDs flag two categories:
- **2 user-relevant** (§7 + base hit floor) — user should see and decide
- **9 structural** (family-share / per-pay) — verify.py floors authored under v4 (50:50 bar share), do not reflect v5 1bar-bell design intent; not real regressions but doc-design drift
- **9 mode 2/5/7 cascading** — m1 changed, m7 ratios shifted; expected
- **1 cross-mode** (m2/m1 wild_pure ratio) — same dd cadence root

The clean PASS is "12 user hardlines + bell direction + §12/§13/§14". The dirty FAIL is "§7 cadence + §15 dd PWDF + verify.py [HIT] band semantics". User must make 3 decisions to ship.

### Q2: "If §7 cadence is structural, why didn't D try a 5th candidate with dd raised?"

**A**: V's audit suggests dd ≈ 2.5% uniform per reel would fix both §7 and §15 dd. RTP cost: pay_id 1 RTP would go from 0.13pp → ~0.85pp (+0.7pp), pay_id 2 (high7+wild) would also lift slightly. To stay in [94, 96] band, would need to redistribute. D's exploration of 94 candidates may not have included this specific knob in the search space — D's `cand_final_e` has dd 1.8/2.2/1.6 hand-picked; the sweep `m15_v13_reasonable_search.py` did include dd ∈ [1, 5]% range but the 4-pass candidates VVV/WWW/FINAL_E/FINAL_F all sit at the dd-low end. V did not run an independent dd sweep.

### Q3: "Why does V's R2 blank differ from D's table (46.7 vs 47.3)?"

**A**: D's design_v13.md §1 TABLE has an arithmetic bug (R2 row sums to 100.6%). D's actual cand_final_e() function uses blank = 1 − sum_non_blank = 46.70%. V used the script's source-of-truth values (which match D's reported metrics within 0.04pp). D should fix the table to display 46.70.

### Q4: "Could V's mechanism B implementation be subtly different from what the v9 weights on disk use?"

**A**: V copied `apply_mechanism_b_blanks` verbatim from `m15_v9_design.py` (which authored the production v9 weights). Tested: V's resulting weights apply the same non-top-adj-blank=1 / top-adj absorb-residual rule. p_window numbers match v9 expectations (high7 R2 35.28% close to v9's ~31%; dd R2 25.51% close to v9's drift). V is using D's same primitive, so any divergence would mirror D's design.

### Q5: "How confident is V in the philosophy §7 verdict?"

**A**: HIGH. The math is simple: P(pay_id 1) = m1_dd × m2_dd × m3_dd = 0.018 × 0.022 × 0.016 = 6.34e-6. 1/6.34e-6 = 157,720. V got 157,670 via the engine (difference is mechanism B integer rounding). Both are clearly outside [50k, 100k]. D admitted this in design_v13.md §9.6 Q6 — V confirms.

### Q6: "Is the bell-shape peak strength 1.14pp actually meaningful, or is it within tolerance noise?"

**A**: V got 1.14pp (D claimed 1.13pp). Bell-shape direction (g15 < g510+g1020) is structural at 13.03 < 20.81 (7.78pp margin) — not noise. The peak STRENGTH metric (max(g510,g1020) - g15) at 1.14pp is small but consistent with D's claim. The design is "barely bell-shaped" — g510 leads g15 by ~1pp, not a strong bell. User asked for bell direction; design delivers direction but with weak peak (per D's own §9.2). Whether this satisfies the spirit of user's v5 directive (bell-shape) is a user judgment call.

---

## Appendix: Files

- Verifier script: `session_artifacts/M15/scripts/m15_v13_verify.py`
- Temp weights (FINAL_E mode 1, post mechanism B): `session_artifacts/M15/_tmp_v13_verify/mode_1/weights.json`
- D's design doc: `session_artifacts/M15/design_v13.md`
- D's exploration script: `session_artifacts/M15/scripts/m15_v13_design.py`
- Production weights (untouched): `slot_designer/machines/M15/weights/mode_1/weights.json`
- Hardlines contract: `slot_designer/machines/M15/USER_HARDLINES.md` (v5)
