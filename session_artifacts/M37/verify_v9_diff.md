# Verify v9 m7 diff (extends v8 diff, replaces v8 m7 only)

> **Stage 5 Verifier output (v9 m7 extension)** per `ONBOARDING_PROCESS.md §4`. Fresh-context derivation of v9 verify red lines from `design_v9_m7.md` + `critic_review_v9.md` (X SHIP-WITH-CAVEAT pending A empirical RTP confirm). Builds on `verify_v8_diff.md`. m1 / m2 / m5 verify lines NOT touched.
>
> Output: diff proposal layered on top of v8 diff (which assumed live in `verify_m37_design.py` after v6 commit + v8 m7 commit).

---

## 0. Scope reminder

- **m1 v5 SHIPPED & LOCKED** — verify untouched
- **m2 v6 SHIPPED & LOCKED** — verify untouched
- **m5 v6 SHIPPED & LOCKED** — verify untouched
- **m7 v8 SHIPPED (committed) — TO BE REPLACED by v9** per `critic_review_v9.md §5`
- **v9 m7 framing** (per `design_v9_m7.md §1`): v8 cut middle (R2 minor/major ×0.80) + preserved small (R1+R3 bar unchanged → pid 7 unchanged) — this is the **opposite** of universal §4 spirit. User caught it: "中奖率错了" (hit not cut).
- **v9 corrected lever** (per `design_v9_m7.md §5`): R1+R3 bar **×0.82** (primary cut → drives pid 7 main small target), R1+R3 wild **×1.00** (fully preserved), R2 mini **×0.91**, R2 minor/major/grand/high7/bar **byte-eq m1** (mid + top + jackpot all preserved).
- **v9 m7 numbers** (analytic verified by V — run against `v9_sim_weights/mode_7/weights.json`):
  - RTP **84.011%** (lower edge of [84, 86]; X audit flags as tight — A multi-seed required)
  - hit **16.99%** ∈ [14, 17] (cut mode feel restored, m1-m7 gap 3.93pp)
  - pid 9 share **26.77%** (OUT of v6/v8 band [14, 21] — needs widening per X §2)
  - booster total 6.17%, HIER 1.272/1.307/13.6, R1 wild 1.247% R3 wild 1.264%
- 1 X audit YELLOW (`critic_review_v9.md §3`): §4 pid 2/3/4 ratios 0.682/0.682/0.686 (~0.014-0.018 below brief 0.70 floor — physically verified shared-lever coupling, designer-justified).

---

## 1. Diff from v8 m7 → v9 m7 (lever level, for context)

| Lever | v8 m7 (current commit) | v9 m7 (proposed replace) | Δ |
|---|---|---|---|
| R2 mini weight (vs m1 274) | ×1.00 (274, m1 byte-eq) | **×0.91** (~250) | mild mini cut — restores some §1 conventional 1.2 floor (mini/minor 2.79/1.99 → 2.54/1.99 = 1.27) |
| R2 minor weight | ×0.80 (156.8, from m1 196) | **m1 byte-eq** (196) | minor RESTORED (v8 cut undone — §4 mid preserve) |
| R2 major weight | ×0.80 (120.0, from m1 150) | **m1 byte-eq** (150) | major RESTORED (§4 mid preserve) |
| R2 high7, R2 bar, R2 grand | m1 byte-eq | m1 byte-eq | unchanged |
| R1+R3 bar (1/2/3/7) | m1 byte-eq | **×0.82** PRIMARY CUT | drives pid 7 (anybar 1× = largest small) cut to 0.673 ratio — delivers real "cut mode feel" |
| R1+R3 wild | ×0.95 (slight cut) | **×1.00** FULLY PRESERVED | wild side-win cadence intact (pid 102/103 jackpot UX ratio rises 0.72→1.00) |
| R1+R3 high7 | m1 byte-eq | m1 byte-eq | unchanged (top tier preserved) |
| R2 blank / R1+R3 blank | passive | passive (absorb saved bar weight) | R1+R3 blank ↑ ~3pp (per-reel total conserved) |

**Why v9 is the correct framing** (per `design_v9_m7.md §1` + `critic_review_v9.md §1`):
- §4 says "砍小奖, 保中/大/顶". pid 7 (anybar 1×) is the **largest small pay** — main cut target.
- v8 preserved R1+R3 bar (pid 7 unchanged → hit 20.11 ≈ m1) AND cut R2 minor/major (pid 9 mid sub-tiers cut). **Both backwards**.
- v9 cuts R1+R3 bar (pid 7 → 0.673 delivered, hit drops to 16.99) AND preserves R2 minor/major (pid 9 mult 5×/10× rise to ≥ 1.0 via R1+R3 dilution coupling).

**Trade-off** (`critic_review_v9.md §3`): pid 2/3/4 (bar×3 mid) couples to same R1+R3 bar lever as pid 7. K_bar = 0.82 → pid 7 = 0.673 ✓ but pid 2/3/4 = 0.682-0.686 (~0.014-0.018 below 0.70 floor). Physically verified shared-lever; mechanism space exhausted (1089-candidate grid). Designer + X both accept as M37-specific structural floor 0.68.

---

## 2. MODE_TARGETS[7] adjustments (v8 → v9)

| Field | v8 value (live in code) | v9 new value | Reason (cite) |
|---|---|---|---|
| `rtp` / `rtp_tol_pp` | 85.0 / 1.0 (band [84, 86]) | **same — band [84, 86] keep** | v9 RTP 84.011 ∈ [84, 86] passes analytically (0.011pp from lower). `critic_review_v9.md §4` flags as tight; **A empirical sub-gate multi-seed (3+ seeds × 200k MC + 700k mean) must confirm empirical mean ≥ 84.0**. Verify uses analytic profile (deterministic GREEN); per brief task §3, V keeps band unchanged and defers margin decision to A. If A fails → v9.1 re-tune (Designer raises K_bar to 0.825 + accepts deeper pid 2/3/4 floor relax to ~0.65). Documented in commit. |
| **`hit_lo` / `hit_hi`** | 0.11 / **0.21** (v8 widened from 0.17 because v8 hit was 20.11 ≈ m1) | **0.11 / 0.17** REVERT | v8 widened to 0.21 was *framing error accommodation* — v8 hit ≈ m1 hit meant "no cut mode feel" per user. v9 framing corrects: hit 16.99 belongs in v6-era band [11, 17] (cut mode hit naturally < m1 by 3-6pp). Revert to **0.17** with v9 16.99 at upper edge (1pp safety to ceiling). `design_v9_m7.md §6` lists "Hit ∈ [14, 17] non-negotiable" per v9 brief; band lower 0.11 keeps prior v3-era headroom. Brief task §1 explicitly says "revert to 0.17 (or slightly higher e.g. 0.175 for buffer)" — chose **0.17** (matches v6 ship state precedent + v9 brief precise red ceiling). |
| **`pid9_share_lo` / `pid9_share_hi`** | 14.0 / **21.0** | **14.0 / 28.0** WIDEN | **Critical change**. v9 pid 9 share **26.77%** OUT of [14, 21]. Reason: v9 cuts R1+R3 bar (pid 7 down) → P(no 3-match on payline) rises → P(R2 booster-alone fires) rises ⇒ pid 9 frequency rises. This is **structural side effect of cut mode under §4 framing**, NOT a regression. `critic_review_v9.md §2 row §8` "pid 9 占比 26.77% — 是 R1+R3 bar cut 导致 booster-alone fallback 更频繁 — 是 structural side effect not regression". Widen upper to **28%** (1.23pp safety above v9 actual 26.77). Brief task §2 explicitly cites X audit: "cut mode 派生从 m1 在 §4 strict 下 pid 9 占比 自然 25-27 — Band 应该 informational level reflect 这点". The 28 upper still keeps the check meaningful (pid 9 > 28% would indicate excessive booster-alone fallback dominance). Lower kept at 14 (still catches the case of pid 9 collapsing too low). |
| `booster_visible_lo` / `hi` | 0.04 / 0.12 | **same** | v9 booster total **6.166%** ∈ [4%, 12%] passes (mini ×0.91 → 2.54%, minor/major byte-eq m1 → 1.99%/1.53%). `design_v9_m7.md §5` confirms HIER monotone. No change. |
| `grand_lo` / `hi` | 0.0007 / 0.0016 | **same** | v9 grand 0.112% unchanged (weight 11, byte-eq m1). No change. |
| `hier_ratio_min` | 1.0 | **same** | v9 ratios 1.272/1.307/13.6 — all ≥ 1.0 (mini/minor 1.272 > 1.2 conventional). `critic_review_v9.md §2 row §1`. No change. |
| `shape_js_max` | 0.10 | **same** | No change. |

**Net MODE_TARGETS[7] code changes**: 2 numeric edits (hit_hi revert, pid9_share_hi widen) + comment block updated.

---

## 3. WINDOW-VISIBILITY mode 7 bands (v9 actual computation)

**Computed v9 m7 window visibility** (V independent run against `v9_sim_weights/mode_7/weights.json`):

| Target | R1 | R3 | Notes |
|---|---|---|---|
| R2 grand | — | — | R2 grand window 12.72% (R2 alone) |
| R1+R3 high7 | 31.36% | 31.14% | both in v8 band [26%, 40%] ✓ |
| R1+R3 wild | 16.66% | 18.38% | both in v8 band [8%, 26%] ✓ — wild marginal preserved at ×1.00 so vis pattern ~ m1 |

**Bar window visibility (mid-pay floor §14)**: R1 1bar 21.94%, R3 1bar 22.26%, R1 7bar 16.89%, R3 7bar 17.04% — all well above 8% floor (smallest is 14.7% on R2 7bar). `[MID-PAY-VISIBLE-FLOOR]` passes.

**Decision**: **No window-visibility band change needed for v9**. The v8 band table for mode 7 (after v8 revert: `r1r3_high7 (0.26, 0.40)`, `r1r3_wild (0.08, 0.26)`, `r2_grand (0.10, 0.22)`, `r2_booster_total (0.18, 0.40)`) passes for v9 cleanly:

- R2 grand 12.72% ∈ [10%, 22%] ✓
- R1+R3 high7 31.14-31.36% ∈ [26%, 40%] ✓
- R1+R3 wild 16.66-18.38% ∈ [8%, 26%] ✓

Brief task §4 anticipated "v9 R1+R3 bar ×0.82 cut → R1/R3 上 blank ↑ → wild/high7 window vis 比 v8 状态 有变化". Empirically confirmed:
- v8 (R1+R3 ≈ m1 byte-eq): R1+R3 high7 marginals 14.25%/13.49%
- v9 (R1+R3 bar ×0.82, blank passive ↑): R1 high7 marginal **18.389%**, R3 high7 marginal **17.404%** (rises ~4pp on R1, ~4pp on R3)
- v9 high7 marginal rise raises window vis to 31.x% (vs ~28% baseline for m1)
- Both v8 and v9 vis values land **inside** the m1-aligned band [26%, 40%]; **no band edit needed**

`r1r3_high7` upper 0.40 already accommodates v9 31% comfortably (no upper concern). Lower 0.26 still meaningful (would catch a scenario where high7 marginal drops below normal — won't trigger for v9 or m1).

**Net WINDOW-VISIBILITY changes**: 0.

---

## 4. Per-pay informational YELLOW threshold (v8 v9 m7-specific amend)

Brief task §5: v8 added `check_mode7_per_pid_ratio` informational YELLOW with Designer §4 floors (顶 ≥ 0.85, 中 ≥ 0.80, 大 ≥ 0.50). v9 pid 2/3/4 ratios 0.682/0.682/0.686 are below 0.80 v8 mid-tier floor. Per X verdict (`critic_review_v9.md §3.4`): "Brief amend M37 m7-specific ratio floor to ≥ **0.68** per §14 universal 'specific tolerance per-machine'".

### Decision

Amend `check_mode7_per_pid_ratio` to support **per-pid floor override for M37-specific mid (bar×3) tier**.

**Reasoning**:
- §14 universal philosophy explicitly allows per-machine numerics: "**Universal layer 不写绝对数字** — 每机台 specific".
- M37 paytable couples pid 7 (cut target) and pid 2/3/4 (preserve target) on same R1+R3 bar lever (`design_v9_m7.md §6` + `critic_review_v9.md §3.1` independent physics check).
- 1089-candidate grid exhausted under hit ≤ 17 ∩ pid 2/3/4 ≥ 0.70 dual hard → infeasible (`critic_review_v9.md §3.2`).
- Designer + X both accept 0.68 as M37 m7 mid-bar-×3 specific floor (`critic_review_v9.md §3.4`).

**Implementation pattern**: per-pid floor override dict, not a global mid-tier lowering. Other mid pids (pid 5/6 for small, pid 9 mult 5×/10× via R2 minor/major-alone) keep universal mid floor 0.80. Only the **bar×3 mid** (pid 2/3/4) gets M37-specific 0.68.

**Code structure**:
```python
# Designer tier floors per design_v8_m7 §1+§2+§4 + v9 M37-specific amend
TIER_FLOOR = {"top": 0.85, "mid": 0.80, "big": 0.50, "small": None, "mixed": None}

# Per-machine pid-specific override — captures structural shared-lever floors.
# M37: pid 2/3/4 (bar×3 mid) couples to R1+R3 bar lever which also drives
# pid 7 (anybar 1× — cut target). Cutting pid 7 ~33% forces pid 2/3/4 ratio
# to ~0.68 (verified 1089-candidate grid). Per §14 "specific tolerance per-machine"
# floor relaxed to 0.68 for these three pids only.
PID_FLOOR_OVERRIDE = {
    "2": 0.68,  # M37 pid 2 (7bar×3 mid) — shared R1+R3 bar lever w/ pid 7
    "3": 0.68,  # M37 pid 3 (3bar×3 mid) — same
    "4": 0.68,  # M37 pid 4 (2bar×3 mid) — same
}
```

### Predicted output for v9 m7

```
YELLOW [MODE7-PER-PID-RATIO] pid 1 (line 3-same high7, 1000× path) ratio 0.987 (informational, tier=top)
YELLOW [MODE7-PER-PID-RATIO] pid 8 (center grand alone 100×) ratio 1.225 (informational, tier=top)
YELLOW [MODE7-PER-PID-RATIO] pid 2 (3-7bar) ratio 0.686 ≥ 0.68 M37-specific floor (informational, tier=mid)
YELLOW [MODE7-PER-PID-RATIO] pid 3 (3-3bar) ratio 0.682 ≥ 0.68 M37-specific floor (informational, tier=mid)
YELLOW [MODE7-PER-PID-RATIO] pid 4 (3-2bar) ratio 0.682 ≥ 0.68 M37-specific floor (informational, tier=mid)
YELLOW [MODE7-PER-PID-RATIO] pid 5 (3-1bar) ratio 0.681 (informational, tier=small)
YELLOW [MODE7-PER-PID-RATIO] pid 6 (7-bar mix) ratio 0.822 (informational, tier=mid)   ← uses universal 0.80 mid floor (small misclassification — see note)
YELLOW [MODE7-PER-PID-RATIO] pid 7 (any-bar) ratio 0.673 (informational, tier=small)   ← MAIN CUT TARGET
YELLOW [MODE7-PER-PID-RATIO] pid 9 (booster/wild alone, mixed sub-tiers) ratio 1.136 (informational, tier=mixed)
YELLOW [MODE7-PER-PID-RATIO] pid 102 (Major Jackpot wild×major×wild) ratio 1.000 (informational, tier=big)
YELLOW [MODE7-PER-PID-RATIO] pid 103 (Minor Jackpot wild×minor×wild) ratio 1.000 (informational, tier=big)
YELLOW [MODE7-PER-PID-RATIO] pid 104 (Mini Jackpot wild×mini×wild) ratio 0.910 (informational, tier=big)
```

**Note on pid 6 tier**: v8 diff tier table classified pid 6 as `"mid"`. `design_v9_m7.md §2` row pid 6 shows tier as "small". This is a v8 → v9 reclassification (pid 6 = any-7-mix 2× was treated as mid by Designer v8 but small per Designer v9). Recommend updating v9 informational check tier mapping to align with `design_v9_m7.md §2` Designer canonical:

```python
TIERS = [
    ("1",   "top",   "pid 1 (line 3-same high7, 1000× path)"),
    ("8",   "top",   "pid 8 (center grand alone 100×)"),
    ("2",   "mid",   "pid 2 (3-7bar)"),
    ("3",   "mid",   "pid 3 (3-3bar)"),
    ("4",   "mid",   "pid 4 (3-2bar)"),
    ("5",   "small", "pid 5 (3-1bar)"),     # v9: was "mid" in v8 → "small" per design_v9_m7 §2
    ("6",   "small", "pid 6 (7-bar mix)"),  # v9: was "mid" in v8 → "small" per design_v9_m7 §2
    ("7",   "small", "pid 7 (any-bar, MAIN CUT TARGET)"),
    ("9",   "mixed", "pid 9 (booster/wild alone, mixed sub-tiers)"),
    ("102", "big",   "pid 102 (Major Jackpot wild×major×wild)"),
    ("103", "big",   "pid 103 (Minor Jackpot wild×minor×wild)"),
    ("104", "big",   "pid 104 (Mini Jackpot wild×mini×wild)"),
]
```

This is *also a v9 amend* — reflects Designer v9's corrected §4 字面 reading.

---

## 5. Expected verify output on v9 (m1 ship'd + m2/m5 v6 + m7 v9)

```
=== M37 design verification ===

Strip-level: 3 GREEN

Mode 1 (v5 SHIP'd unchanged): ALL GREEN (1 informational YELLOW [BUCKET-GE1_5])

Mode 2 (v6 SHIP'd unchanged): ALL GREEN

Mode 5 (v6 SHIP'd unchanged): ALL GREEN

Mode 7 (v9 — REPLACE v8):
  RTP 84.011%  hit 16.986%  CV ~11.5
  GREEN  [RTP]                 mode 7 RTP 84.011% ∈ [84.0, 86.0]   ← TIGHT 0.011pp from lower (A multi-seed required)
  GREEN  [HIT]                 mode 7 hit 16.986% ∈ [11%, 17%]     ← v9 hit_hi 0.21→0.17 revert
  GREEN  [PID9-SHARE]          mode 7 pid9 26.77% ∈ [14%, 28%]     ← v9 hi 21→28 widen (R1+R3 bar cut side effect)
  GREEN  [BUCKET-CAP]
  GREEN  [BOOSTER-R1R3-EMPTY]
  GREEN  [WILD-R2-EMPTY]
  GREEN  [BOOSTER-HIER]        mini/minor=1.272x, minor/major=1.307x (≥ 1.0)
  GREEN  [BOOSTER-VISIBLE]     R2 booster total 6.17% ∈ [4%, 12%]
  GREEN  [GRAND-SIGNATURE]     R2 grand 0.112% ∈ [0.07%, 0.16%]
  GREEN  [REEL-ASYMMETRY]      blanks R1=31.67% R3=32.61% R2=50.49%; top-prize R1=19.64% R3=18.67%
  GREEN  [TOP-PATH-1000X]
  GREEN  [TOP-PATH-1000X-FREQ] mode 7 1 in ~25k ∈ [15k, 50k]
  GREEN  [ARCHETYPE-HIGH7]     R1=18.39 / R2=13.02 / R3=17.40 (m1 byte-eq → in ±30%)
  GREEN  [ARCHETYPE-BAR]       all bar tiers cut ~18% from m1 v5 (R1+R3 × 0.82 → bar marginals ≈ 0.82 × m1) ∈ ±25%
  GREEN  [ARCHETYPE-WILD]      R1 wild 1.247% / R3 wild 1.264% (= m1 v5 wild × ~1.0, in ±30% baseline 1.781% × [0.70, 1.30])
  GREEN  [WINDOW-VISIBILITY]   mode 7 R2 grand window 12.72% ∈ [10%, 22%]
  GREEN  [WINDOW-VISIBILITY]   mode 7 R1 high7 31.36%, R3 high7 31.14% ∈ [26%, 40%]
  GREEN  [WINDOW-VISIBILITY]   mode 7 R1 wild 16.66%, R3 wild 18.38% ∈ [8%, 26%]
  GREEN  [WINDOW-VISIBILITY-CAP] no top symbol exceeds 50%
  GREEN  [BLANK-RATIO-CAP]     mode 7 ≤ 5x
  GREEN  [MID-PAY-VISIBLE-FLOOR] mode 7 all mid-pay ≥ 8% (R1+R3 bar window vis 17-23% range)

Cross-mode invariants:
  GREEN  [MODE7-LOCK]          R2 mini m1 2.786 / m7 2.535 (drift 0.251pp ≤ 0.5pp tier 1)
  GREEN  [MODE7-LOCK]          R2 minor m1 1.993 / m7 1.993 (drift 0.000pp byte-eq)
  GREEN  [MODE7-LOCK]          R2 major m1 1.525 / m7 1.525 (drift 0.000pp byte-eq)
  GREEN  [MODE7-LOCK]          R2 grand m1 0.112 / m7 0.112 (drift 0.000pp byte-eq)
  GREEN  [MODE5-BASE-LOCK]
  GREEN  [RTP-MONOTONIC]       m7 84.0 < m1 94.1 < m2 303.5 < m5 507.6
  GREEN  [HIT-MONOTONIC]       m7 17.0% < m1 20.9% < m2 32.2% ≈ m5 33.1%
  GREEN  [HIT-MONOTONIC-SAFETY] m1 - m7 = 3.93pp ≥ 0.30pp safety floor   ← HUGE margin (v8 was 0.81)
  GREEN  [TOP-JACKPOT-ESCALATION]

  YELLOW [MODE7-PER-PID-RATIO] pid 1 ratio 0.987 (tier=top)
  YELLOW [MODE7-PER-PID-RATIO] pid 8 ratio 1.225 (tier=top)
  YELLOW [MODE7-PER-PID-RATIO] pid 2 ratio 0.686 ≥ 0.68 M37-specific floor (tier=mid)   ← Brief amend 0.70→0.68
  YELLOW [MODE7-PER-PID-RATIO] pid 3 ratio 0.682 ≥ 0.68 M37-specific floor (tier=mid)
  YELLOW [MODE7-PER-PID-RATIO] pid 4 ratio 0.682 ≥ 0.68 M37-specific floor (tier=mid)
  YELLOW [MODE7-PER-PID-RATIO] pid 5 ratio 0.681 (tier=small)
  YELLOW [MODE7-PER-PID-RATIO] pid 6 ratio 0.822 (tier=small)
  YELLOW [MODE7-PER-PID-RATIO] pid 7 ratio 0.673 (tier=small, MAIN CUT TARGET — delivered)
  YELLOW [MODE7-PER-PID-RATIO] pid 9 ratio 1.136 (tier=mixed)
  YELLOW [MODE7-PER-PID-RATIO] pid 102 ratio 1.000 (tier=big)
  YELLOW [MODE7-PER-PID-RATIO] pid 103 ratio 1.000 (tier=big)
  YELLOW [MODE7-PER-PID-RATIO] pid 104 ratio 0.910 (tier=big)

=== Result: N/N GREEN; YELLOW informational: 13 ===
```

**Predicted total**: 0 RED. All RED categories pass. `[HIT-MONOTONIC-SAFETY]` margin **3.93pp** comfortable (vs v8's 0.51pp tight). `[RTP]` analytic passes deterministically at 84.011 (X audit Caveat: A multi-seed empirical must confirm mean ≥ 84.0 — verify itself is GREEN at analytic).

**Pre-existing inherited YELLOWs (m1/m2/m5)** unchanged — still 1 informational `[BUCKET-GE1_5]` on m1 + the 2 v6 pre-existing structural YELLOWs on m2/m5 absorbed silently by existing slack.

---

## 6. TDD inject tests added (extends v8 diff)

For new/changed v9 bands. Append to test file.

| Test ID | Category | Inject (v9 m7 weight mutation) | Expected RED / specific YELLOW | Revert | Expected GREEN |
|---|---|---|---|---|---|
| v9-T1 | `[HIT]` m7 upper 0.17 | mode 7: R1+R3 bar all positions × 1.10 (push hit above 17 toward 19) | `[HIT] mode 7 hit ~19% NOT in [11%, 17%]` | restore | `[HIT] mode 7 hit 16.986% ∈ [11%, 17%]` |
| v9-T2 | `[PID9-SHARE]` m7 upper 0.28 | mode 7: R1+R3 bar × 0.55 (very deep cut → P(no match) much higher → pid9 share climbs above 28%) | `[PID9-SHARE] mode 7 pid9 ~32% NOT in [14%, 28%]` | restore | `[PID9-SHARE] mode 7 pid9 26.77% ∈ [14%, 28%]` |
| v9-T3 | `[PID9-SHARE]` m7 lower 0.14 | mode 7: R2 mini × 0.05 + R2 minor × 0.05 + R2 major × 0.05 (annihilate booster-alone) | `[PID9-SHARE] mode 7 pid9 ~6% NOT in [14%, 28%]` | restore | `[PID9-SHARE] mode 7 pid9 26.77% ∈ [14%, 28%]` |
| v9-T4 | `[HIT-MONOTONIC-SAFETY]` 0.3pp floor | mode 7: R1+R3 bar × 1.05 (push m7 hit toward m1; gap shrinks below 0.3pp) | `[HIT-MONOTONIC-SAFETY] gap 0.18pp < 0.30pp safety floor` | restore | `[HIT-MONOTONIC-SAFETY] gap 3.93pp ≥ 0.30pp` |
| v9-T5 | `[MODE7-PER-PID-RATIO]` pid 2/3/4 0.68 M37 floor | mode 7: R1+R3 bar × 0.70 (cut deeper → pid 2/3/4 ratios drop below 0.68) | YELLOW emitted: `[MODE7-PER-PID-RATIO] pid 2 ratio ~0.51 < 0.68 M37-specific floor (informational; mid)` | restore | YELLOW: `pid 2 ratio 0.686 ≥ 0.68 M37-specific floor` |
| v9-T6 | `[MODE7-LOCK]` minor drift (regression sentinel) | mode 7: R2 minor × 0.6 (push m7 minor below m1 by > 0.5pp drift) | `[MODE7-LOCK] R2 minor drift 0.80pp > 0.5pp tolerance` | restore | `[MODE7-LOCK] R2 minor drift 0.000pp (byte-eq)` |
| v9-T7 | `[ARCHETYPE-WILD]` lower edge | mode 7: R1 wild positions × 0.5 (push R1 wild below 0.70× baseline) | `[ARCHETYPE-WILD] mode 7 violations: R1 wild ~0.62% NOT in [1.247%, 2.315%]` | restore | `[ARCHETYPE-WILD] mode 7 R1+R3 wild in ±30%` |

**Test v9-T5 specifically validates the M37-specific PID_FLOOR_OVERRIDE**: when ratio is below 0.68 (the M37 amend), informational YELLOW includes `< 0.68 M37-specific floor` text. Above 0.68 but below 0.80 universal mid: YELLOW says `≥ 0.68 M37-specific floor` (passing). This makes the M37 amend visible in audit logs without making it a hard red.

---

## 7. Python diff (extends v8, layered on live verify_m37_design.py)

```diff
--- a/slot_designer/scripts/verify_m37_design.py  (after v5+v6+v8 m7 diff committed)
+++ b/slot_designer/scripts/verify_m37_design.py  (with v9 m7 diff layered)
@@ -100,17 +100,21 @@ MODE_TARGETS = {
     7: {
-        # v8 amendment 2026-05-12 (replaces v6 09c7871): RTP 85.16 / hit 20.11 / pid9 share 18.82%
-        # Designer v8 lever: R2 mini ×1.00 / R2 minor ×0.80 / R2 major ×0.80 / R1+R3 wild ×0.95.
-        # All other R1+R3 (bar, high7) reverted to m1 v5 byte-eq.
-        # - hit_hi 0.17→0.21 (V verify_v8_diff §2: v8 hit 20.11 — was 15.00 on v6)
-        # - HIT-MONOTONIC-SAFETY enforced separately (gap = m1 hit - m7 hit ≥ 0.3pp)
-        #   v8 actual gap: 20.92 - 20.11 = 0.81pp (X-audit YELLOW-borderline)
-        # - pid9_share band [14, 21] unchanged (v8 actual 18.82%, was 19.13% on v6)
+        # v9 amendment 2026-05-13 (REPLACES v8): RTP 84.011 / hit 16.99 / pid9 share 26.77%
+        # Designer v9 lever (corrected §4 framing): R1+R3 bar ×0.82 PRIMARY CUT (drives pid 7 anybar = main small target)
+        # / R1+R3 wild ×1.00 (fully preserved) / R2 mini ×0.91 (mild) /
+        # R2 minor/major/grand/high7/bar/R1+R3 high7 all byte-eq m1 v5.
+        # See design_v9_m7.md + critic_review_v9.md SHIP-WITH-CAVEAT (A multi-seed RTP confirm pending).
+        # - hit_hi 0.21→0.17 REVERT (v9 hit 16.99, cut mode feel restored, gap m1-m7 = 3.93pp)
+        # - pid9_share_hi 21→28 WIDEN (v9 26.77 — structural side effect of R1+R3 bar cut raising booster-alone fallback; cut mode physical character per X audit §2)
+        # - rtp_tol_pp 1.0 unchanged (analytic 84.011 passes, A multi-seed must verify ≥ 84.0 mean)
+        # - HIT-MONOTONIC-SAFETY gap 20.92 - 16.99 = 3.93pp ≥ 0.30pp ✓
+        # - hier_ratio_min 1.0 unchanged (v9 ratios 1.272/1.307/13.6)
         "rtp": 85.0, "rtp_tol_pp": 1.0,
-        "hit_lo": 0.11, "hit_hi": 0.21,
+        "hit_lo": 0.11, "hit_hi": 0.17,
         "booster_visible_lo": 0.04, "booster_visible_hi": 0.12,
         "grand_lo": 0.0007, "grand_hi": 0.0016,
         "hier_ratio_min": 1.0,
         "shape_js_max": 0.10,
-        "pid9_share_lo": 14.0, "pid9_share_hi": 21.0,
+        "pid9_share_lo": 14.0, "pid9_share_hi": 28.0,
     },
 }
@@ -545,30 +549,52 @@ def check_mode7_per_pid_ratio(profiles: dict) -> list[tuple[bool | None, str]]:
-    """[MODE7-PER-PID-RATIO] informational YELLOW — m7 per-pay_id freq / m1 per-pay_id freq.
-
-    Universal §4 says "中/大/顶 hit 不动" directionally; numerical floors are
-    Designer-interpretation (see design_v8_m7.md §1+§2+§4). Designer v8 floors:
-      top (pid 1 + pid 8): ≥ 0.85
-      mid (pid 2-6): ≥ 0.80
-      big (pid 102/103/104 = wild²·booster Jackpot UX): ≥ 0.50 (wild² physics floor)
-
-    NOT a hard red — verify never fails on this. ...
-    """
+    """[MODE7-PER-PID-RATIO] informational YELLOW — m7 per-pay_id freq / m1 per-pay_id freq.
+
+    Universal §4 says "中/大/顶 hit 不动" directionally; numerical floors are
+    Designer-interpretation. Tier classification per design_v9_m7.md §2
+    (v9 corrected framing — pid 5/6 are small per Designer canonical, was mid in v8 misreading):
+      top (pid 1 + pid 8): ≥ 0.85
+      mid (pid 2/3/4 + minor/major-alone within pid 9): ≥ 0.80 universal; M37-specific override 0.68 for pid 2/3/4
+      big (pid 102/103/104 = wild²·booster Jackpot UX): ≥ 0.50 (wild² physics floor)
+      small (pid 5/6/7): floor None (cut targets allowed)
+      mixed (pid 9 aggregate): floor None (sum of sub-tiers)
+
+    M37-specific pid 2/3/4 override per §14 universal "specific tolerance per-machine":
+      pid 2 (7bar×3), pid 3 (3bar×3), pid 4 (2bar×3) share R1+R3 bar lever with pid 7
+      (anybar 1× = cut target). Cutting pid 7 ~33% structurally forces pid 2/3/4 to ~0.68
+      (1089-candidate grid exhausted, critic_review_v9.md §3.2). Per `feedback_dont_lower_floor_when_blocked`
+      this is deliberate trade-off justified by structural physics, not "lower floor when blocked".
+
+    NOT a hard red — verify never fails on this. Always YELLOW for audit transparency.
+    """
     out: list[tuple[bool | None, str]] = []
     if 1 not in profiles or 7 not in profiles:
         return out
     m1_pay_hits = profiles[1].get("pay_hits", {})
     m7_pay_hits = profiles[7].get("pay_hits", {})
-    # Tier classification per design_v8_m7.md §2:
-    TIERS = [
-        ("1",   "top",   "pid 1 (line 3-same high7, 1000× path)"),
-        ("8",   "top",   "pid 8 (center grand alone 100×)"),
-        ("2",   "mid",   "pid 2 (3-7bar)"),
-        ("3",   "mid",   "pid 3 (3-3bar)"),
-        ("4",   "mid",   "pid 4 (3-2bar)"),
-        ("5",   "mid",   "pid 5 (3-1bar)"),
-        ("6",   "mid",   "pid 6 (7-bar mix)"),
-        ("7",   "small", "pid 7 (any-bar)"),
-        ("9",   "mixed", "pid 9 (booster/wild alone, mixed sub-tiers)"),
+    # Tier classification per design_v9_m7.md §2 (corrected from v8: pid 5/6 are small).
+    TIERS = [
+        ("1",   "top",   "pid 1 (line 3-same high7, 1000× path)"),
+        ("8",   "top",   "pid 8 (center grand alone 100×)"),
+        ("2",   "mid",   "pid 2 (3-7bar)"),
+        ("3",   "mid",   "pid 3 (3-3bar)"),
+        ("4",   "mid",   "pid 4 (3-2bar)"),
+        ("5",   "small", "pid 5 (3-1bar)"),
+        ("6",   "small", "pid 6 (7-bar mix)"),
+        ("7",   "small", "pid 7 (any-bar, MAIN CUT TARGET)"),
+        ("9",   "mixed", "pid 9 (booster/wild alone, mixed sub-tiers)"),
         ("102", "big",   "pid 102 (Major Jackpot wild×major×wild)"),
         ("103", "big",   "pid 103 (Minor Jackpot wild×minor×wild)"),
         ("104", "big",   "pid 104 (Mini Jackpot wild×mini×wild)"),
     ]
     TIER_FLOOR = {"top": 0.85, "mid": 0.80, "big": 0.50, "small": None, "mixed": None}
+    # M37-specific per-pid floor override per §14 universal "specific tolerance per-machine".
+    # See critic_review_v9 §3.4 + brief task §5: M37 m7 pid 2/3/4 shared-lever physics floor.
+    PID_FLOOR_OVERRIDE = {
+        "2": 0.68,
+        "3": 0.68,
+        "4": 0.68,
+    }
     for pid, tier, name in TIERS:
         p_m1 = m1_pay_hits.get(pid, 0.0)
         p_m7 = m7_pay_hits.get(pid, 0.0)
         if p_m1 <= 0:
             continue
         ratio = p_m7 / p_m1
-        floor = TIER_FLOOR.get(tier)
-        if floor is not None and ratio < floor:
-            msg = f"[MODE7-PER-PID-RATIO] {name} ratio {ratio:.3f} < {floor:.2f} {tier}-tier floor (informational; Designer §4 interpretation)"
-        else:
-            msg = f"[MODE7-PER-PID-RATIO] {name} ratio {ratio:.3f} (informational, tier={tier})"
+        # M37 pid-specific override takes precedence over universal tier floor.
+        override = PID_FLOOR_OVERRIDE.get(pid)
+        if override is not None:
+            if ratio < override:
+                msg = f"[MODE7-PER-PID-RATIO] {name} ratio {ratio:.3f} < {override:.2f} M37-specific floor (informational; tier={tier})"
+            else:
+                msg = f"[MODE7-PER-PID-RATIO] {name} ratio {ratio:.3f} ≥ {override:.2f} M37-specific floor (informational; tier={tier})"
+        else:
+            floor = TIER_FLOOR.get(tier)
+            if floor is not None and ratio < floor:
+                msg = f"[MODE7-PER-PID-RATIO] {name} ratio {ratio:.3f} < {floor:.2f} {tier}-tier floor (informational; Designer §4 interpretation)"
+            else:
+                msg = f"[MODE7-PER-PID-RATIO] {name} ratio {ratio:.3f} (informational, tier={tier})"
         out.append((None, _warn(msg)))
     return out
```

**Net code changes**:
1. `MODE_TARGETS[7]`: `hit_hi` 0.21 → **0.17** (revert) + `pid9_share_hi` 21 → **28** (widen) + comment updated
2. `check_mode7_per_pid_ratio`: tier reclassification (pid 5/6 small not mid) + `PID_FLOOR_OVERRIDE` dict for M37 pid 2/3/4 = 0.68 floor + branched message format

**Files unchanged**: `MODE_TARGETS[1/2/5]`, `check_window_visibility` (v8 m7 bands stay), all other check functions.

---

## 8. Commit message must-includes (per critic_review_v9 §5)

1. **RTP 84.011 tight margin** — analytic 0.011pp from lower band 84.0. A empirical sub-gate **multi-seed 200k MC × 3 seeds + 700k seed mean** must confirm empirical RTP mean ≥ 84.0. If A fails → v9.1 contingency: Designer raises K_bar to ~0.825 (or escalate user for hit ≤ 17.10).
2. **§4 pid 2/3/4 ratio 0.682-0.686 below brief-stated 0.70 floor** — M37 paytable shared-lever physics floor (pid 7 cut target + pid 2/3/4 preserve target both depend on R1+R3 bar weights). 1089-candidate grid exhausted. Per §14 universal "specific tolerance per-machine", M37 m7-specific floor amended to **0.68**. Verify informational YELLOW surfaces ratio per run.
3. **v9 m7 replaces v8 m7** — explicit supersedes (v8 reverted "中奖率错了" user feedback).
4. **Process backport** (`critic_review_v9.md §6.2`): ONBOARDING_PROCESS.md §5 Stage 4 X gate "if §9 character is cut mode (m7), evaluate hit gap vs m1 not m7 baseline; gap < 2pp = 'no cut feel' even if §9 字面 0.3pp safety passes".

Verify itself does not enforce these (commit-message hygiene per X process recommendations).

---

## 9. 80-word summary

v9 m7 verify diff layered on v8: **2 MODE_TARGETS edits + 1 informational function update**. (1) `MODE_TARGETS[7].hit_hi` 0.21→**0.17** revert — v8 widening was framing-error accommodation, v9 hit 16.99 restores cut mode feel (HIT-MONOTONIC-SAFETY gap 3.93pp vs v8's 0.51pp). (2) `MODE_TARGETS[7].pid9_share_hi` 21→**28** widen — v9 pid9 share 26.77% is structural side effect of R1+R3 bar cut raising booster-alone fallback; X audit §2 confirms cut mode physical character. (3) `check_mode7_per_pid_ratio`: pid 5/6 reclassified small (Designer v9 canonical) + M37-specific `PID_FLOOR_OVERRIDE` pid 2/3/4 = 0.68 (per §14 specific-tolerance, 1089-candidate grid exhausted). RTP 84.011 analytic GREEN; A multi-seed empirical must confirm ≥ 84.0. m1/m2/m5 untouched. 7 TDD inject tests.
