# M15 v14c Modes 2 / 5 — INDEPENDENT VERIFICATION (2026-05-12)

> **Status**: M2_LC and M5_LC_plus PASS all 25 cross-mode invariants in BOTH analytic
> and engine-realized (post integer rounding + mechanism B) forms. D's claimed numerics
> reproduce within +/-0.012pp absolute. m5 LUCKY-MONO hit/trigger tight margins
> survive integer rounding — engine-realized margins are LARGER than analytic.
> No mitigation needed.
>
> **verify.py result**: 4 net new RED lines introduced by v14c modes 2/5
> (vs 9 baseline shipped RED lines that are pre-existing stale verify.py band
> issues inherited from already-shipped modes 1/7). All 4 v14c-introduced REDs
> are stale verify.py bands or USER_HARDLINES.md v8 deletions — NONE are
> user-explicit hardline violations.
>
> **Files**:
> - This report: `session_artifacts/M15/verify_v14c_modes_25.md`
> - Verifier script: `session_artifacts/M15/scripts/m15_v14c_verify.py`
> - Temp weights (DO NOT SHIP): `session_artifacts/M15/_tmp_v14c_verify/mode_{1,2,5,7}/weights.json`
> - Full verify.py log: `session_artifacts/M15/_tmp_v14c_verify/verify_output.txt`
>
> **No production files modified.**

---

## 1. Mode 2 (M2_LC) — numeric reproduction + cross-mode invariant check

### 1.1 Reproduction vs D's claims (analytic, tol 0.5pp)

| metric | mine | D | delta | OK |
|---|---:|---:|---:|:-:|
| total_rtp (pp) | 296.1288 | 296.13 | 0.0012 | ✓ |
| base_rtp (pp) | 97.9110 | 97.91 | 0.0010 | ✓ |
| feature_rtp (pp) | 198.2177 | 198.21 | 0.0077 | ✓ |
| base_hit (%) | 33.8518 | 33.85 | 0.0018 | ✓ |
| trigger (%) | 3.3040 | 3.304 | 0.0000 | ✓ |
| R1 blank (%) | 27.5280 | 27.53 | 0.0020 | ✓ |
| R3 blank (%) | 23.1900 | 23.19 | 0.0000 | ✓ |
| wild_pure cadence | 1/70,607 | 1/70,607 | 0.01 | ✓ |
| pay9 (cherry1) % | 15.6841 | 15.6841 | 0.0000 | ✓ |
| pay71 (cherry2) % | 0.9777 | 0.9777 | 0.0000 | ✓ |
| pay4 (cherry3) % | 0.0202 | 0.0202 | 0.0000 | ✓ |
| pay1 (wild_pure) % | 0.0014 | 0.0014 | 0.0000 | ✓ |
| pay2 (high7_wild) % | 0.1307 | 0.1307 | 0.0000 | ✓ |
| pay21 (high7_pure) % | 0.1821 | 0.1821 | 0.0000 | ✓ |
| pay3 (bar3) % | 0.2143 | 0.2143 | 0.0000 | ✓ |
| pay5 (bar2) % | 0.9854 | 0.9855 | 0.0001 | ✓ |
| pay7 (bar1) % | 1.6984 | 1.6984 | 0.0000 | ✓ |
| pay8 (bar_mixed) % | 13.9574 | 13.9575 | 0.0001 | ✓ |
| family_share cherry1 % | 16.02 | 16.02 | 0.001 | ✓ |
| family_share bar_mixed % | 31.17 | 31.17 | 0.001 | ✓ |
| family_share high7 % | 14.92 | 14.92 | 0.004 | ✓ |
| family_share wild_pure % | 0.289 | 0.289 | 0.000 | ✓ |
| P(R≥1000)/spin | 1.539e-6 | 1.539e-6 | 0 | ✓ |
| P(R≥200)/spin | 2.824e-4 | 2.82e-4 | 0 | ✓ |

**Verdict**: D's claimed numerics reproduce EXACTLY (max delta 0.012pp on RTP, 0.0023pp on hit, 0.0046pp on family shares). No discrepancies.

### 1.2 Cross-mode invariants (analytic) — 16/16 PASS

| invariant | result | detail |
|---|:-:|---|
| CROSS-RTP m2 band [290, 310] | ✓ | 296.129pp |
| CROSS-RTP m2 > m1 | ✓ | 296.13 > 94.29 |
| HIT m2 band [30, 35] | ✓ | 33.852% |
| LUCKY-MONO m2 > m1 hit | ✓ | 33.85 > 16.22 |
| LUCKY-MONO m2 >= m1 trig | ✓ | 3.3040% >= 1.1200% |
| BAR-HIER-§1 P(b1)>P(b2)>P(b3) | ✓ | 1.6984% > 0.9854% > 0.2143% |
| TOP-JACKPOT-CADENCE m2/m1 ≤ 1.5 | ✓ | ratio = 0.7268 |
| 1000+ P(R≥1000)/spin ≤ 1e-5 | ✓ | 1.539e-6 |
| REEL-ASYM-LUCKY R1 ≥ R3 blank | ✓ | 27.53 ≥ 23.19 |
| FAM-SHARE c1 [15, 25] | ✓ | 16.02% |
| FAM-SHARE b3 [5, 22] | ✓ | 7.15% |
| FAM-SHARE h7 [14, 30] | ✓ | 14.92% |
| FAM-SHARE wld [0.08, 0.30] | ✓ | 0.289% (0.011pp under cap) |
| JACKPOT-VIS R1 ≤ 0.6% | ✓ | 0.4000% |
| JACKPOT-VIS R2 ≤ 0.6% | ✓ | 0.4000% |
| JACKPOT-VIS R3 ≤ 0.6% | ✓ | 0.3000% |

### 1.3 Cross-mode invariants (ENGINE-REALIZED, post integer rounding + mech B) — 16/16 PASS

After `marginals_to_weights(scale=10000)` + `apply_mechanism_b_blanks`, all 16 invariants still PASS:

| invariant | engine value | analytic value | drift |
|---|---:|---:|---:|
| total_rtp | 295.784pp | 296.129pp | -0.344pp |
| base_rtp | 97.846pp | 97.911pp | -0.065pp |
| base_hit | 33.832% | 33.852% | -0.020pp |
| trigger | 3.2993% | 3.3040% | -0.0047pp |
| R1 blank | 27.53% | 27.53% | 0.000 |
| R3 blank | 23.22% | 23.19% | +0.025 |
| wild_pure cadence | 1/70,528 | 1/70,607 | -79 (denser by 0.0001%) |
| bar3 share | 7.14% | 7.15% | -0.005pp |
| wld share | 0.290% | 0.289% | +0.001pp (still under 0.30 cap) |

All bands respected post integer rounding. RTP margin to floor (290) remains +5.78pp (~4σ on 1M sim).

---

## 2. Mode 5 (M5_LC_plus) — numeric reproduction + cross-mode invariant check

### 2.1 Reproduction vs D's claims (analytic, tol 0.5pp)

| metric | mine | D | delta | OK |
|---|---:|---:|---:|:-:|
| total_rtp (pp) | 504.5595 | 504.56 | 0.0005 | ✓ |
| base_rtp (pp) | 97.0680 | 97.08 | 0.0120 | ✓ |
| feature_rtp (pp) | 407.4914 | 407.48 | 0.0114 | ✓ |
| base_hit (%) | 33.8922 | 33.89 | 0.0022 | ✓ |
| trigger (%) | 3.3040 | 3.304 | 0.0000 | ✓ |
| R1 blank (%) | 28.6390 | 28.64 | 0.0010 | ✓ |
| R3 blank (%) | 23.9640 | 23.96 | 0.0040 | ✓ |
| wild_pure cadence | 1/61,430 | 1/61,377 | 53 | ✓ (tol 0.09%) |
| pay9 (cherry1) % | 15.6841 | 15.6841 | 0.0000 | ✓ |
| pay71 (cherry2) % | 0.9777 | 0.9777 | 0.0000 | ✓ |
| pay4 (cherry3) % | 0.0202 | 0.0202 | 0.0000 | ✓ |
| pay1 (wild_pure) % | 0.0016 | 0.0016 | 0.0000 | ✓ |
| pay2 (high7_wild) % | 0.1181 | 0.1181 | 0.0000 | ✓ |
| pay21 (high7_pure) % | 0.1418 | 0.1418 | 0.0000 | ✓ |
| pay3 (bar3) % | 0.2198 | 0.2198 | 0.0000 | ✓ |
| pay5 (bar2) % | 0.9991 | 0.9991 | 0.0000 | ✓ |
| pay7 (bar1) % | 1.7181 | 1.7181 | 0.0000 | ✓ |
| pay8 (bar_mixed) % | 14.0118 | 14.0118 | 0.0000 | ✓ |
| family_share cherry1 % | 16.16 | 16.16 | 0.002 | ✓ |
| family_share bar_mixed % | 31.66 | 31.66 | 0.003 | ✓ |
| family_share high7 % | 13.03 | 13.03 | 0.005 | ✓ |
| family_share wild_pure % | 0.335 | 0.34 | 0.005 | ✓ |
| P(R≥1000)/spin | 1.100e-7 | 1.100e-7 | 0 | ✓ |
| P(R≥200)/spin | 3.887e-3 | 3.89e-3 | 0 | ✓ |

**Verdict**: D's claimed numerics reproduce. Max delta 0.012pp on base_rtp, 0.005pp on family shares. wild_pure cadence diff 53 (1/61,430 vs 1/61,377) is rounding-class noise, well within 1% tolerance.

### 2.2 Cross-mode invariants (analytic) — 13/13 PASS

| invariant | result | detail |
|---|:-:|---|
| CROSS-RTP m5 band [480, 520] | ✓ | 504.559pp |
| CROSS-RTP m5 > m2 | ✓ | 504.56 > 296.13 |
| HIT m5 band [30, 35] | ✓ | 33.892% |
| LUCKY-MONO m5 ≥ m2 hit | ✓ | 33.89224% ≥ 33.85184% (diff +0.04040pp) |
| LUCKY-MONO m5 ≥ m2 trig | ✓ | 3.3040% ≥ 3.3040% (diff +0.000000pp, equal) |
| BAR-HIER-§1 P(b1)>P(b2)>P(b3) | ✓ | 1.7181% > 0.9991% > 0.2198% |
| TOP-JACKPOT-CADENCE m5/m2 ≥ 1.1 | ✓ | ratio = 1.1494 |
| 1000+ P(R≥1000)/spin ≤ 1e-5 | ✓ | 1.100e-7 |
| REEL-ASYM-LUCKY R1 ≥ R3 blank | ✓ | 28.64 ≥ 23.96 |
| FAM-SHARE b3 [5, 22] | ✓ | 7.51% |
| JACKPOT-VIS R1 ≤ 0.6% | ✓ | 0.4000% |
| JACKPOT-VIS R2 ≤ 0.6% | ✓ | 0.4000% |
| JACKPOT-VIS R3 ≤ 0.6% | ✓ | 0.3000% |

### 2.3 Cross-mode invariants (ENGINE-REALIZED) — 13/13 PASS

After integer rounding + mech B:

| invariant | engine value | analytic value | drift |
|---|---:|---:|---:|
| total_rtp | 504.250pp | 504.559pp | -0.309pp |
| base_rtp | 97.089pp | 97.068pp | +0.021pp |
| base_hit | 33.891% | 33.892% | -0.002pp |
| trigger | 3.3013% | 3.3040% | -0.0027pp |
| R1 blank | 28.62% | 28.64% | -0.022pp |
| R3 blank | 23.95% | 23.96% | -0.014pp |
| wild_pure cadence | 1/61,286 | 1/61,430 | -144 |
| bar3 share | 7.51% | 7.51% | 0.000 |

RTP margin to floor (490) post-integer = +14.25pp (~10σ on 1M sim).

### 2.4 Cross-mode ladder (engine-realized) — 10/10 PASS

| ladder | engine value | result |
|---|---|:-:|
| RTP-LADDER m7 < m1 | 85.37 < 94.26 | ✓ |
| RTP-LADDER m1 < m2 | 94.26 < 295.78 | ✓ |
| RTP-LADDER m2 < m5 | 295.78 < 504.25 | ✓ |
| HIT-LADDER m7 < m1 | 13.08% < 16.22% | ✓ |
| HIT-LADDER m1 < m2 | 16.22% < 33.83% | ✓ |
| HIT-LADDER m5 ≥ m2 | 33.891% ≥ 33.832% (diff +0.059pp) | ✓ |
| TRIG-LADDER m7 ~ m1 | diff 0.000017 ≤ 5e-4 | ✓ |
| TRIG-LADDER m1 < m2 | 1.1194% < 3.2993% | ✓ |
| TRIG-LADDER m5 ≥ m2 | 3.3013% ≥ 3.2993% (diff +0.00198pp) | ✓ |
| TOP-JACKPOT-ESC m1 < m2 < m5 | 3.16e-5 < 2.82e-4 < 3.88e-3 | ✓ |

---

## 3. m5 vs m2 tight-margin analysis (LUCKY-MONO hit + trigger after integer rounding)

D self-flagged two risks:
1. m5 LUCKY-MONO hit margin only 0.04pp (33.89% vs 33.85% analytic) — integer rounding may flip.
2. m5 trigger = m2 trigger exactly (3.304% == 3.304% analytic) — integer rounding may make m5 < m2.

### 3.1 Engine-realized HIT diff (LUCKY-MONO m5 ≥ m2)

| view | m5 hit % | m2 hit % | m5 − m2 | verdict |
|---|---:|---:|---:|:-:|
| Analytic | 33.892240 | 33.851845 | +0.040395pp | PASS |
| Engine (integer + mech B) | 33.890566 | 33.831789 | **+0.058777pp** | **PASS (margin widens)** |

The integer rounding direction **widens** the LUCKY-MONO HIT margin from +0.040pp to +0.059pp. m2 integer-rounded loses 0.020pp of hit; m5 only loses 0.002pp. Net m5−m2 gap GROWS by +0.018pp. No mitigation needed.

### 3.2 Engine-realized TRIG diff (LUCKY-MONO m5 ≥ m2)

| view | m5 trig % | m2 trig % | m5 − m2 | verdict |
|---|---:|---:|---:|:-:|
| Analytic | 3.304000 | 3.304000 | +0.000000pp (equal) | PASS at zero margin |
| Engine (integer + mech B) | 3.301321 | 3.299340 | **+0.001980pp** | **PASS (margin opens)** |

The integer rounding direction differentiates m5 trigger from m2 trigger: m5 gives 3.3013%; m2 gives 3.2993%. m5 ends up MORE FREQUENT than m2 by 0.00198pp = 2e-5 absolute fraction. The shared R3 topdollar marginal target was the same (3.304%), but tiny integer-rounding asymmetry on other R3 symbols (different doublediamond + high7 marginals) shifts the remaining R3 weight available for topdollar, producing slightly different actual td marginals. Direction happens to favor m5 by chance.

Both LUCKY-MONO floors are met with margin after integer realization. D's flagged tight-margin risks do NOT materialize. No mitigation needed (no +1 weight bump, no cherry/bar lift).

### 3.3 Sanity: per-mode RTP / hit drift (analytic → engine)

| mode | RTP drift | hit drift | trig drift |
|---|---:|---:|---:|
| 1 | -0.026pp | -0.0003pp | -0.0006pp |
| 7 | +0.000pp | +0.0113pp | -0.0009pp |
| 2 | -0.344pp | -0.0201pp | -0.0047pp |
| 5 | -0.309pp | -0.0017pp | -0.0027pp |

Mode 2 has the largest RTP drift (-0.344pp), within D's predicted ±0.5pp band. Margin to RTP floor 290 post-engine = +5.78pp (still ~4σ on 1M sim).

---

## 4. verify.py mode 2 / 5 REDs classified

verify.py reports 13 RED lines total against the temp v14c weights tree. The 9 baseline shipped REDs (mode 1 + mode 7) are inherited from already-shipped state — they are PRE-EXISTING and not introduced by v14c modes 2/5 redesign. The 4 NEW REDs introduced by v14c are listed below.

### 4.1 NEW REDs introduced by v14c modes 2 / 5

| # | category | mode | RED detail | classification | rationale |
|---|---|:---:|---|---|---|
| 1 | PER-PAY-FLOOR | 2 | pay_id 71 (cherry2) P=0.9773% floor=1.0000% (miss 0.0227pp) | **(d) stale verify.py band** | verify.py floor 1.0% for m2 cherry2 was set at v2 baseline when cherry2 lift was higher; current design has cherry2 P just under floor. USER_HARDLINES.md v8 deleted all bucket bands; per-pay floors not user-explicit |
| 2 | PER-PAY-FLOOR | 5 | pay_id 71 (cherry2) P=0.9778% floor=1.0000% (miss 0.0222pp) | **(d) stale verify.py band** | Same as above — m5 cherry2 inherits m2 marginal; m5 floor 1.0 inherited from m2. Also stale per USER_HARDLINES.md v8 |
| 3 | PWDF-FLOOR | 2 | doublediamond R1 any-reel max p_window 16.48% floor 17.0% (miss 0.52pp) | **(d) stale verify.py band, possibly fixable** | v14c dd cut (R1×0.95, R2×0.90, R3×0.85 vs m1) reduced dd density. PWDF floor 17% was set at v8.1 mech B achieved baseline. v14c slightly under floor (0.52pp). NOT user-hardline; verify.py-internal |
| 4 | PWDF-FLOOR | 5 | doublediamond R1 any-reel max p_window 16.88% floor 17.0% (miss 0.12pp) | **(d) stale verify.py band, possibly fixable** | Same as #3 — m5 dd cut (R1×0.95 vs m2) drops dd density. Miss is small (0.12pp) |

### 4.2 BASELINE REDs (NOT introduced by v14c — pre-existing on shipped state)

These 9 REDs fire against the SHIPPED mode 1 / mode 7 baseline (per `python -m slot_designer.machines.M15.verify` on the production weights tree); they are inherited NOT caused by v14c modes 2/5 redesign. They are stale verify.py bands from v2 targets — per USER_HARDLINES.md v8 the user explicitly deleted all bucket / family-share bands except those listed as universal/mode-1 hardlines.

| # | category | mode | RED detail | classification |
|---|---|:---:|---|---|
| 1 | FAMILY-SHARE | 1 | cherry1 share 21.88% floor 26.0% (miss 4.12pp) | (a)/(d) inherited shipped baseline; USER_HARDLINES.md v8 deleted bucket bands |
| 2 | FAMILY-SHARE | 1 | bar_mixed share 27.93% cap 25.0% (over 2.93pp) | (a)/(d) inherited shipped baseline; deleted bucket bands |
| 3 | FAMILY-SHARE | 1 | bar1 share 12.11% cap 12.0% (over 0.11pp) | (a)/(d) inherited shipped baseline; deleted bucket bands |
| 4 | FAMILY-SHARE | 1 | high7 share 8.71% cap 8.0% (over 0.71pp) | (a)/(d) inherited shipped baseline; deleted bucket bands |
| 5 | PER-PAY-FLOOR | 1 | cherry2 P=0.317% floor=0.4% | (a)/(d) inherited shipped baseline |
| 6 | PER-PAY-FLOOR | 1 | cherry3 P=0.0035% floor=0.005% | (a)/(d) inherited shipped baseline |
| 7 | PWDF-FLOOR | 1 | dd PWDF 27.90% floor 28.0% (miss 0.1pp) | (b) structural to v14 design; floor 28% not user-hardline |
| 8 | PWDF-FLOOR | 7 | dd PWDF 30.42% floor 34.0% (miss 3.58pp) | (b) structural to v14b m7 design; cut mode reduces dd density per philosophy §4 |
| 9 | PWDF-FLOOR | 7 | high7 PWDF 33.28% floor 34.0% (miss 0.72pp) | (b) structural to v14b m7 design; cut mode |

### 4.3 RED classification summary per V's brief

Per V brief task 5 buckets:
- (a) user v8 hardline violation: **0** in m2/m5 new REDs. All 4 new REDs are NOT user-explicit hardlines (USER_HARDLINES.md v8 explicitly deletes bucket bands and family-share bands; PWDF floor is verify.py-derived not user-explicit; PER-PAY-FLOOR cherry2 1.0% is verify.py-derived).
- (b) structural to v14c design intent: **2** (m2/m5 dd PWDF). The v14c dd cut to control wild_pure share cap is intentional/structural per philosophy §10; reducing dd density to keep wild_pure share ≤ 0.30 inevitably pushes PWDF below 17%.
- (c) fixable: **2** possibly (m2/m5 cherry2 0.023pp miss could be closed with a +0.01 cherry lift on R3 — see §6 below). dd PWDF could be lifted by +1 to a specific R1 dd stop on top-adj blank — but this would tweak engine integers post-mech-B.
- (d) stale verify.py band: **4** (all of them). Per USER_HARDLINES.md v8 these are not user-explicit hardlines.

**No user-hardline violations.** All v14c-introduced REDs are stale verify.py bands or structural side-effects of intentional design decisions.

---

## 5. Cross-mode comparison table (engine-realized)

| metric | m1 (shipped) | m7 (shipped) | m2 (M2_LC) | m5 (M5_LC_plus) |
|---|---:|---:|---:|---:|
| Total RTP (engine pp) | 94.26 | 85.37 | **295.78** | **504.25** |
| Total RTP (analytic pp) | 94.29 | 85.37 | 296.13 | 504.56 |
| RTP user-target band | [94, 96] | [83, 87] | [292, 308] | [491.5, 508.5] |
| RTP verify band | [94, 96] | [83, 87] | [290, 310] | [480, 520] |
| RTP margin to verify floor (engine) | +0.26pp | +2.37pp | **+5.78pp** | **+14.25pp** |
| RTP margin to verify ceiling (engine) | +1.74pp | +1.63pp | +14.22pp | +15.75pp |
| Base RTP (engine) | 42.77 | 33.80 | 97.85 | 97.09 |
| Feature RTP (engine) | 51.49 | 51.57 | 197.94 | 407.16 |
| Base hit (%) engine | 16.22 | 13.08 | 33.83 | 33.89 |
| Hit session (%) | 17.33 | 14.20 | 37.13 | 37.19 |
| Trigger (%) engine | 1.1194 | 1.1211 | 3.2993 | 3.3013 |
| R1 blank (%) | 38.52 | 42.32 | 27.53 | 28.62 |
| R3 blank (%) | 59.01 | 64.86 | 23.22 | 23.95 |
| R1 ≥ R3 blank | F (lucky reversal m2/m5 only) | F | **T** (lucky carve) | **T** (lucky carve) |
| wild_pure cadence | 1/51,314 | 1/51,206 | 1/70,528 | 1/61,286 |
| wild_pure m2/m1 (cadence) | — | — | 0.728 | — |
| wild_pure m5/m2 (cadence) | — | — | — | **1.151** ≥ 1.1 floor |
| P(R≥200)/spin | 3.158e-5 | 3.158e-5 | 2.820e-4 | 3.884e-3 |
| P(R≥1000)/spin | 7.4e-8 | 7.4e-8 | 1.54e-6 | 1.10e-7 |
| BAR-HIER-§1 P(b1)>P(b2)>P(b3) | ✓ | ✓ | **✓** | **✓** |
| LUCKY-MONO m5 ≥ m2 hit/trig | — | — | base | **✓** both engine-realized |

---

## 6. RTP margin analysis (engine-realized)

| mode | analytic RTP | engine RTP | analytic margin (to floor) | engine margin (to floor) |
|---|---:|---:|---:|---:|
| 2 | 296.13 | 295.78 | +6.13pp | **+5.78pp** |
| 5 | 504.56 | 504.25 | +14.56pp | **+14.25pp** |

For 1M-spin sim: SE on m2 total RTP ≈ √(208/1e6) ≈ 1.44pp (per D's §Q2 analysis). Engine margin 5.78pp / 1.44 = **4.01σ buffer** → P(< 290) ~ 3e-5. m5 margin 14.25 / SE ~ 1.6 (higher feature variance) = **8.9σ buffer** → effectively zero.

**Conclusion**: Even after integer rounding drift, both modes have substantial RTP margin. Engine-realized m5 sits at 504.25pp which is +5.75pp inside the [491.5, 508.5] user-target band, +14.25pp inside the [490, 510] hard verify band (D's framing was [480, 520] = 504.25 vs floor 490 = +14.25pp).

For user-target band [491.5, 508.5] m5 engine = +12.75pp from floor, +4.25pp from ceiling.

---

## 7. Bar hierarchy explicit per mode (P values)

### 7.1 Mode 2 (M2_LC)

| pay_id | family | mult | P (engine, %) | P (analytic, %) |
|---|---|---:|---:|---:|
| 7 | bar1 (3-of-1bar) | 5× | 1.6962 | 1.6984 |
| 5 | bar2 (3-of-2bar) | 10× | 0.9858 | 0.9854 |
| 3 | bar3 (3-of-3bar) | 20× | 0.2140 | 0.2143 |

**P(bar1) 1.6962% > P(bar2) 0.9858% > P(bar3) 0.2140%** ✓ §1 hierarchy preserved cross-rounding.

### 7.2 Mode 5 (M5_LC_plus)

| pay_id | family | mult | P (engine, %) | P (analytic, %) |
|---|---|---:|---:|---:|
| 7 | bar1 (3-of-1bar) | 5× | 1.7174 | 1.7181 |
| 5 | bar2 (3-of-2bar) | 10× | 1.0003 | 0.9991 |
| 3 | bar3 (3-of-3bar) | 20× | 0.2197 | 0.2198 |

**P(bar1) 1.7174% > P(bar2) 1.0003% > P(bar3) 0.2197%** ✓ §1 hierarchy preserved.

### 7.3 Cross-mode bar §1 hierarchy ladder

| mode | P(bar1) | P(bar2) | P(bar3) | b1/b2/b3 ordering |
|---|---:|---:|---:|---|
| m1 (shipped) | 0.7065% | 0.4218% | 0.1033% | b1 > b2 > b3 ✓ |
| m2 (M2_LC) | 1.6984% | 0.9854% | 0.2143% | b1 > b2 > b3 ✓ |
| m5 (M5_LC_plus) | 1.7181% | 0.9991% | 0.2198% | b1 > b2 > b3 ✓ |

All three lucky-modes-plus-baseline preserve §1. v14c explicitly drops the "LUCKY-MONO bar2-peak" rule from v14b — bars lift uniformly, philosophy §1 preserved as user requested.

---

## 8. Final verdict per mode

### Mode 2 (M2_LC): **PASS**

- Total RTP 296.13 analytic / 295.78 engine — both inside [290, 310] verify band, both inside [292, 308] user-target band.
- All 16 user/cross-mode invariants PASS in both analytic + engine views.
- D's claims reproduce within +/-0.012pp on RTP, +/-0.005pp on family shares.
- Bar §1 hierarchy P(b1) > P(b2) > P(b3) preserved cross-rounding.
- LUCKY-MONO m2 > m1 (hit by +17.6pp; trig by +2.18pp) — substantial margin.
- Reel asymmetry R1 ≥ R3 blank preserved per shipped v9 lucky carve-out.
- Wild_pure share 0.29% under 0.30% cap (0.01pp margin).
- New verify.py REDs: 2 (cherry2 PER-PAY-FLOOR 0.023pp miss + dd PWDF-FLOOR 0.52pp miss) — both stale verify.py bands per USER_HARDLINES.md v8.

### Mode 5 (M5_LC_plus): **PASS**

- Total RTP 504.56 analytic / 504.25 engine — both inside [480, 520] verify band, both inside [491.5, 508.5] user-target band.
- All 13 user/cross-mode invariants PASS in both analytic + engine views.
- D's claims reproduce within +/-0.012pp on RTP, +/-0.005pp on family shares.
- Bar §1 hierarchy preserved.
- LUCKY-MONO m5 ≥ m2 hit/trig: engine-realized margin LARGER than analytic (+0.059pp hit, +0.00198pp trig vs analytic +0.040pp / +0.000pp). D's flagged tight-margin risks did NOT materialize.
- wild_pure cadence m5/m2 = 1.151 (engine) ≥ 1.1 floor.
- New verify.py REDs: 2 (cherry2 PER-PAY-FLOOR 0.022pp miss + dd PWDF-FLOOR 0.12pp miss) — both stale verify.py bands per USER_HARDLINES.md v8.

### Specific cells flagged

| issue | cell | severity | recommendation |
|---|---|---|---|
| m2/m5 cherry2 P just under verify.py 1.0% floor | PER-PAY-FLOOR | very low (0.02pp miss; user deleted bucket bands v8) | NONE required (not user hardline); OR optionally bump cherry R3 marginal +0.0003 to cross 1.0% |
| m2 dd R1 PWDF 16.48% under 17% floor | PWDF-FLOOR | low (0.52pp miss); structural (dd cut for wild_pure share cap) | NONE required (not user hardline); mech B floor of 17% is verify.py-internal not user |
| m5 dd R1 PWDF 16.88% under 17% floor | PWDF-FLOOR | very low (0.12pp miss) | NONE required |

---

## 9. Self-critique (V adversarial review)

### Q1. Did I trust D's numerics blindly?

No. I took D's marginals as INPUT (from design doc §2.2 / §3.2), then independently ran `analytic_profile_from_marginals` + computed feature RTP via locked feature_params + checked every invariant. My numbers reproduce D's within +/-0.012pp on every metric. The reproduction is independent — same inputs (marginals + locked feature_params) flowing through same primitives (`analytic_rtp.py`) but in MY script not D's.

### Q2. Did I rely on D's verify.py-pass claim, or did I exercise verify.py myself?

I ran verify.py against temp weights I wrote myself (post `marginals_to_weights` + `apply_mechanism_b_blanks`) via `subprocess.run`. The output is in `_tmp_v14c_verify/verify_output.txt`. I parsed 13 RED lines, classified each, and confirmed which came from v14c vs which inherited from shipped baseline. The 4 net-new RED lines I attribute to v14c are real and reproducible.

### Q3. Did the m5 tight-margin actually flip under engine integer rounding?

I tested this DIRECTLY by computing both analytic and engine-realized values. Engine-realized:
- m5 hit 33.890566% vs m2 hit 33.831789% → m5−m2 = +0.058777pp (WIDER than analytic +0.040pp)
- m5 trig 3.301321% vs m2 trig 3.299340% → m5−m2 = +0.001980pp (WIDER than analytic 0.000pp)

Both LUCKY-MONO floors hold with LARGER margin post-rounding, not smaller. D's self-flagged risk did not materialize. **No mitigation needed.**

The lucky direction is fortuitous: m2 integer-rounded loses more hit (-0.020pp) than m5 (-0.002pp), and the topdollar marginal rounds slightly differently between modes (different R3 dd weights → different residual for td given fixed total stops).

### Q4. Did I check whether the 4 NEW verify.py REDs are user hardlines?

I read `slot_designer/machines/M15/USER_HARDLINES.md` v8 (2026-05-12 latest revision). Per §"Bucket distribution (v8 directive 2026-05-12: 全部放开 bucket 数字 band)":

> "放开所有rtp分桶的限制。只满足reel体验和rtp构成的合理性。"

User explicitly deleted ALL `ge*_lt*` bucket bands AND released family-share bands AND released per-pay-floor bands EXCEPT for paytable lock + feature shape lock + total RTP + hit + R1 blank + jackpot ≤ 0.6% + 避免1000×+.

The 4 new v14c REDs (cherry2 floor 1.0%, dd PWDF 17%) are NOT in any of the user-retained hardlines list. They are stale verify.py-internal bands inherited from v2/v8 design intent. Both are structural artifacts of intentional v14c design (dd cut for wild_pure share cap; cherry2 P naturally falls under 1.0 with the current cherry lift pattern). The fix would be a mechanism inside verify.py itself, not v14c design.

### Q5. Was I lenient classifying the 4 new REDs as "stale band" when in fact they could be fixable design defects?

I dug into each:
- **cherry2 P 0.977% vs 1.0% floor**: Would require +0.02pp cherry lift somewhere. Doable via R3 cherry from 5.0% → 5.04%, but the floor itself is from v2 design (cherry2 [1.0, 3.5] was set for lucky modes when v2 base RTP was ~110pp). USER_HARDLINES.md v8 deleted these bands. Not a v14c design defect.
- **m2 dd PWDF 16.48% vs 17% floor**: dd lift in M2_LC is (R1×0.95, R2×0.90, R3×0.85) vs m1. Without the cut, wild_pure share exceeds 0.30% cap. The PWDF floor 17% was set v8.1 against m2 baseline where dd cube was higher. Lifting dd would break wild_pure share cap (structural tradeoff per philosophy §10 pareto defense). **(b) Structural** classification is correct.
- **m5 dd PWDF 16.88%** — same structural argument.

I'm comfortable with classification: 1 fixable (cherry2 if user requests) + 3 structural-to-design / stale.

### Q6. RTP margin engine drift — is the 5.78pp m2 margin actually 4σ buffer as D claimed?

D's analytic SE 1.44pp on 1M-spin sim is reasonable (recomputed: base_var 20.5, feature_var ~187, per-spin var ~208, SE=√(208/1e6)=1.44pp). Engine margin 5.78pp / 1.44 = 4.01σ. For 100k spins SE = √(208/1e5) = 4.56pp; margin 5.78/4.56 = 1.27σ → P(<290) ~ 10%.

So D's "1M production sim safe" claim holds (P(<290) ~ 3e-5 effectively zero). For dev 10k cache sim, margin would be only ~0.4σ → P(<290) ~ 35% noise. This is fine because dev 10k is for QA, not production calibration.

### Q7. Did I miss any invariants the v14c design should be checked against?

I checked:
- 12 user-brief cross-mode invariants (RTP ladder, hit ladder, trigger ladder, top-jackpot cadence, top-jackpot esc, bar §1, reel asymmetry, paytable lock, feature shape lock, jackpot per-reel, 1000+, family-share bands per verify.py).
- 25 specific verify.py categories ran via subprocess (PAYTABLE-LOCK / SCHEMA-FP / BLANK-FLANK / VISUAL-RHYTHM / REEL-ASYMMETRY / etc.).

I did NOT add ad-hoc invariants of my own — V brief explicitly says "DO NOT add new hardlines". My checks reproduce D's claimed invariants from his §2.6 / §3.6 tables + V's brief-listed 12 cross-mode invariants. PWDF + per-pay-floor came from verify.py firing them; I report and classify but don't promote as v14c-pass-required.

### Q8. Did I verify D's RTP margin claim ("4.4σ buffer on 1M sim") was correct?

D §Q2: σ_base² = (4.62 × 0.979)² = 20.5; σ_feat² ≈ 187; total per-spin var 208; SE = √(208/1e6) = 1.44pp; margin 6.13 / 1.44 = 4.26σ.

Engine RTP m2 = 295.78pp (drift -0.34pp from analytic). Engine margin to floor 290 = 5.78pp / 1.44 = 4.01σ. My more conservative engine-based estimate gives 4σ rather than 4.4σ but same order-of-magnitude conclusion ("substantial margin, P(<290) << 1% on 1M").

D's analytic-based σ count is slightly inflated by not accounting for engine drift. Engine margin 5.78pp / 1.44 SE = 4.0σ. P(realized < 290 on 1M) ≈ Φ(-4) ≈ 3e-5. **Practically safe.**

---

## 10. Recommendation

**SHIP M2_LC and M5_LC_plus.**

- All 12 user-brief cross-mode invariants PASS in both analytic and engine-realized views.
- D's claimed numerics reproduce exactly (max delta 0.012pp).
- D's flagged tight margins (m5 hit + m5 trig) RESOLVE in m5's favor after integer rounding — no mitigation needed.
- RTP margin to floor: m2 +5.78pp (4σ) / m5 +14.25pp (~9σ) engine-realized — both substantially exceed user-required 2pp / 1.5pp brief minimums.
- No user-hardline violations.
- 4 new verify.py REDs introduced are stale band issues per USER_HARDLINES.md v8 (user explicitly released all bucket/family-share/per-pay-floor bands except listed ones); 2 are structural to v14c's intentional dd cut for wild_pure share cap respect.
- 9 baseline REDs in verify.py are pre-existing on shipped state, not caused by v14c modes 2/5 — they exist on shipped mode 1 + mode 7 weights as already-acknowledged stale verify.py bands.

Main session should:
1. Run a 1M-spin engine simulation for final RTP confidence (engine analytic predicts 295.78 / 504.25 ± 1.4 / 1.6pp SE).
2. Commit the v14c temp weights to `slot_designer/machines/M15/weights/mode_{2,5}/weights.json` (and update the temp dir cleanup).
3. Update `slot_designer/machines/M15/MODE_DESIGN.md` to reflect v14c m2/m5 designs.
4. Optional follow-up: file a separate task to clean up verify.py stale bands per USER_HARDLINES.md v8 (out of scope for current ship).
