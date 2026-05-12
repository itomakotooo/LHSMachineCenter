# M37 mode 7 — Designer v9 design (fresh context, corrected framing)

## 1. v8 错诊断 + v9 corrected framing

### v8 failure mode
v8 m7 hit **20.115%** vs m1 v5 hit **20.918%** = 0.81pp gap. User feedback: "中奖率错了" — cut mode is supposed to feel "运气差", but v8 hit is essentially equal to m1 hit, so the player perceives no cut.

Root cause: v8 chose to **preserve R1+R3 bar** (uniform, no cut) and instead cut R2 minor + R2 major (both 0.80×). But under §4 字面解读:

- pid 7 (anybar 1×) = **biggest small pay** — should be MAIN CUT TARGET
- pid 9 mult 5× (minor-alone) and pid 9 mult 10× (major-alone) are **middle tier** — should be PRESERVED

v8 cut what should be preserved (minor/major-alone) and preserved what should be cut (anybar). Worse, R1+R3 bar untouched means pid 7 frequency in v8 = m1 baseline = 11.8% → 59% of v8 m7 hit. Hit cannot drop while its dominant component is preserved.

### v9 corrected framing (universal §4 字面 + §9)
- **小奖 cut targets** (§4): pid 7 anybar 1× (largest small), pid 9 mult 1× (side-wild-alone), pid 9 mult 2× (mini-alone), pid 5 (1bar×3 3×), pid 6 (any-7-mix 2×)
- **中段 preserve** (§4): pid 2 (7bar×3 6×), pid 3 (3bar×3 5×), pid 4 (2bar×3 4×); pid 9 mult 5× (minor-alone), pid 9 mult 10× (major-alone)
- **大奖 preserve** (§4): pid 102 / 103 / 104 (3-wild jackpots 20/50/100×)
- **顶奖 preserve** (§4): pid 1 (high7×3 → 1000× via grand), pid 8 (grand-alone 100×)

Primary cut lever **MUST be R1+R3 bar** (drives pid 7 the largest small). But — M37 paytable couples pid 7 (anybar mixed) and pid 2/3/4 (bar×3 mid) to the same R1+R3 bar weights. So cutting R1+R3 bar inevitably drifts pid 2/3/4. **Brief explicitly accepts this structural trade** (pid 2/3/4 floor relaxed to 0.70 vs 0.85 elsewhere).

## 2. Per-pay tier classification (§4 字面 + paytable)

| pid | name | mult | base | source semantics | tier | v9 lever-impact |
|-----|------|------|------|------------------|------|------------------|
| 1 | high7×3 | 10× | 100% R2 high7 byte-eq m1 + R1/R3 high7 byte-eq m1 | top (1000× via grand sub) | preserve byte-eq |
| 2 | 7bar×3 | 6× | R1×R2×R3 7bar (R1+R3 cut + wild sub) | mid (preserve) | drift (structural trade) |
| 3 | 3bar×3 | 5× | R1×R2×R3 3bar | mid (preserve) | drift (structural trade) |
| 4 | 2bar×3 | 4× | R1×R2×R3 2bar | mid (preserve) | drift (structural trade) |
| 5 | 1bar×3 | 3× | R1×R2×R3 1bar | small (cut OK) | drift (structural trade) |
| 6 | any-7-mix | 2× | (high7,7bar) ordered mix on payline | small | small drift |
| 7 | any-bar | 1× | (1/2/3/7 bar) mix on payline | **largest small** | **main cut target** |
| 8 | grand-alone | 100× | R2=grand, no R1/R3 match | top | preserve (R2 grand byte-eq m1; ratio naturally rises) |
| 9 mult 1× | side-wild-alone | 1× | R1 or R3 wild only, no match | small | (preserve wild marginal — chose K_wild=1.0) |
| 9 mult 2× | mini-alone | 2× | R2=mini, no R1/R3 match | small | cut OK (K_mini=0.91) |
| 9 mult 5× | minor-alone | 5× | R2=minor, no R1/R3 match | mid | preserve (R2 minor byte-eq m1; ratio rises with K_bar cut) |
| 9 mult 10× | major-alone | 10× | R2=major, no R1/R3 match | mid | preserve (R2 major byte-eq m1; ratio rises with K_bar cut) |
| 102 | (wild,major,wild) Major JP | 100× | R1/R3 wild × R2 major × R1/R3 wild | big | preserve (K_wild=1.0) |
| 103 | (wild,minor,wild) Minor JP | 50× | same | big | preserve (K_wild=1.0) |
| 104 | (wild,mini,wild) Mini JP | 20× | same w/ mini | big | drift to K_mini = 0.91 |

## 3. Lever-impact matrix (each lever → which pids affected, ranked by tier impact)

| Lever | Affects pids | Tier impact (§4) | Effect on hit | Effect on RTP |
|-------|--------------|-------------------|---------------|----------------|
| **R1+R3 bar (1/2/3/7) ×K_bar** | pid 2/3/4/5 (3-match drops), pid 6 (any-7-mix), pid 7 (any-bar — dominant) | small (pid 7) + mid drift (pid 2/3/4) | very large (pid 7 dominates) | very large |
| **R1+R3 wild ×K_wild** | pid 9 mult 1× side-wild-alone (small), pid 102/103/104 (big jackpots, K_wild²) | small + big jackpot loss | moderate | moderate |
| **R2 mini ×K_mini** | pid 9 mult 2× mini-alone (small), pid 104 (big jackpot, K_mini) | small + 1 big jackpot loss | small | small |
| **R2 minor ×K** | pid 9 mult 5× minor-alone (mid — preserve!), pid 103 (big) | mid drop + big loss | small | small |
| **R2 major ×K** | pid 9 mult 10× major-alone (mid — preserve!), pid 102 (big) | mid drop + big loss | small | small |
| R2 grand | pid 8 (top), pid 1 1000× path | locked (jackpot anchor) | — | — |
| R2 high7 / R2 bar | pid 1/2/3/4/5/6 (3-match) | byte-eq m1 (preserve mid/top R2 path) | — | — |
| R1+R3 high7 | pid 1 (3-match) | byte-eq m1 (preserve top tier) | — | — |

**Lever priority per v9 brief**:
1. R1+R3 bar (PRIMARY — drives pid 7 main cut target)
2. R1+R3 wild (secondary — side-wild-alone small + big-jackpot trade)
3. R2 mini (optional — mini-alone is small per §4)
4. R2 minor / major / grand / high7 / bar untouched (byte-eq m1 — middle/big/top per §4)
5. R1+R3 high7 untouched (byte-eq m1 — top tier pid 1)

## 4. Grid search result + candidates

3D grid: K_bar × K_wild × K_mini with multiple step sizes ran:
- Coarse pass (1089 candidates, K_bar [0.55, 0.95] step 0.05 × K_wild/K_mini [0.50, 1.0] step 0.05) → 0 feasible
- Fine pass around suspected RTP/hit feasible band → 0 strict feasible (under hard pid 2/3/4 ≥ 0.70 floor)

**Constraint tension (structural)**: Any candidate with RTP ≥ 84 AND hit ≤ 17 has pid 2/3/4 ≈ 0.68 (below 0.70 floor by ~0.015-0.02). This is **inherent to M37 paytable structure**: pid 7 (cut target) and pid 2/3/4 (preserve target) share the same R1+R3 bar weights. To cut pid 7 substantially (achieve hit ≤ 17), pid 2/3/4 must drop ~30%.

K_wild floor = 0.95 (because K_wild² ≥ 0.85 → K_wild ≥ √0.85 ≈ 0.92 for pid 102/103/104 ≥ 0.85; using K_wild ≥ 0.95 keeps comfortable margin).

K_mini floor = 0.85 (for pid 104 ratio ≥ 0.85).

**Closest candidates** (RTP & hit pass; pid 2/3/4 marginally below 0.70):

| K_bar | K_wild | K_mini | RTP | hit | pid 2 | pid 1 | pid 102 | pid 104 |
|-------|--------|--------|------|------|-------|-------|---------|---------|
| 0.820 | 1.00 | 0.91 | 84.011% | 16.986% | 0.686 | 0.987 | 1.000 | 0.910 |
| 0.823 | 0.98 | 0.91 | 84.017% | 16.995% | 0.687 | 0.985 | 0.960 | 0.892 |
| 0.821 | 0.95 | 0.95 | 84.074% | 16.997% | 0.683 | 0.986 | 0.902 | 0.950 |
| 0.822 | 0.99 | 0.91 | 84.037% | 16.999% | 0.683 | 0.986 | 0.980 | 0.910 |

## 5. Recommended lever values + per-pay frequency table

**RECOMMENDED**: K_bar=0.82, K_wild=1.00, K_mini=0.91

Rationale:
- K_wild=1.00 fully preserves wild side-win cadence (R1+R3 wild marginal unchanged). Per brief: "Prefer K_wild closer to 1.0 (preserve wild as side-win cadence)" — best possible.
- K_mini=0.91 = mild mini cut; R2 mini marginal 2.79% → 2.54% (Lightning Link 4-tier visibility intact: mini still 2.54% > minor 1.99% > major 1.53% > grand 0.11%, with mini/minor ratio = 1.27 — within v5 universal ≥ 1.0 monotone floor; close to philosophy §1's 1.2-1.3 conventional range). Per brief: "Prefer K_mini closer to 1.0 (preserve Lightning Link 4-tier visibility IF possible)".
- K_bar=0.82 = uniform R1+R3 bar cut (drops R1+R3 bar total marginal 59.4% → ~52%). Primary cut lever as required.

**Per-pay frequency outcomes (engine analytic)**:

| pid | freq | rtp_pp | ratio vs m1 | tier (§4) | verify | 
|-----|------|--------|-------------|-----------|--------|
| 1 | 0.00702 | 19.91 | 0.987 | 顶 | PASS ≥ 0.85 |
| 2 | 0.00120 | 2.93 | 0.686 | 中 | drift (off 0.014) |
| 3 | 0.00256 | 4.62 | 0.682 | 中 | drift (off 0.018) |
| 4 | 0.00256 | 3.69 | 0.682 | 中 | drift (off 0.018) |
| 5 | 0.00415 | 3.88 | 0.681 | 小 | cut OK |
| 6 | 0.01118 | 4.53 | 0.822 | 小 | cut OK |
| 7 | 0.08064 | 14.29 | 0.673 | 小 (MAIN TARGET) | cut delivered |
| 8 | 0.00076 | 7.62 | 1.225 | 顶 | PASS (booster-alone rises) |
| 9 | 0.05978 | 22.49 | 1.136 | mix | sum-of-sources |
| 102 | 0.000002 | 0.024 | 1.000 | 大 | PASS |
| 103 | 0.000003 | 0.016 | 1.000 | 大 | PASS |
| 104 | 0.000004 | 0.008 | 0.910 | 大 | PASS |

**Player-experience narrative**:
- m7 hit gap vs m1 = **3.93pp** (vs v8's 0.81pp). Player feels real "运气差".
- pid 7 (anybar 1×) frequency drops 32.7% (11.78% → 8.06% per spin). Anybar is the most visible "small win" — its rarefaction is the dominant subjective signal of cut mode.
- All wild side-win frequency preserved (K_wild=1.0). Player still feels "wilds appear regularly" — same wild visual rhythm.
- BOOSTER-HIER mini/minor/major/grand all visible with mini ~2.54% (still 1 in ~39 spins).
- Top jackpot path unchanged (pid 1 1000× retains 98.7% baseline freq — high7 + grand byte-eq m1).
- Big jackpots (pid 102/103/104) at ~91-100% baseline freq — visible jackpot path preserved.

## 6. Trade-offs explicit

### Accepted structural drift: pid 2/3/4 ratios 0.682-0.686 vs 0.70 floor
**Reason**: M37 paytable couples pid 7 (cut target, anybar 1×) and pid 2/3/4 (preserve target, bar×3 mid) on the same R1+R3 bar weights. There exists no lever that cuts pid 7 (hit ≤ 17 requires K_bar ≤ 0.82) without proportionally cutting pid 2/3/4. The brief explicitly sanctions this trade: "中段 tier preserve: pid 2/3/4 (bar×3) ratio ≥ 0.70 (**drift accepted for structural reason**)".

Actual drift: pid 2 ratio 0.686 (0.014 below floor), pid 3/4 ratio 0.682 (0.018 below floor). Absolute drift = 1.4-1.8% relative to floor. Per §1 universal "specific tolerance per-machine", we treat ≥ 0.68 as the practical floor for M37 m7 (rather than 0.70), explicit drift acceptance.

### Why not strict 0.70 floor?
Two options exist:
- (A) Accept pid 2/3/4 drift to 0.68 → hit 16.99% (v9 winner).
- (B) Strict pid 2/3/4 ≥ 0.70 → requires K_bar ≥ 0.825 → hit ≥ 17.10% (just over 17 ceiling, fails "real cut mode feel" non-negotiable).

v9 brief lists **m7 hit ∈ [14, 17] as "non-negotiable"** in 验收 section. Hit ceiling 17 takes priority over pid 2/3/4 ≥ 0.70 (which has drift-accept language in the same brief). Option A chosen.

### Trade: pid 5 (1bar×3 3×) ratio 0.681
pid 5 is "small" per §4 (lowest bar×3 multiplier). Cut along with K_bar is acceptable.

### Trade: pid 9 mult 5× / 10× (minor-alone, major-alone) preservation
R2 minor and R2 major are **byte-eq m1**. With K_bar cut, P(no R1/R3 winning match) RISES → minor-alone and major-alone frequencies RISE relative to baseline. So pid 9 mult 5×/10× ratios are **≥ 1.0** (well above 0.85 floor). The lever-coupling actually works in our favor for this tier.

## 7. Cross-mode invariants check

- §1 BOOSTER-HIER monotone: PASS (mini 2.54% > minor 1.99% > major 1.53% > grand 0.11%)
- §9 m7 hit < m1 hit (20.62 safety): PASS (16.99% << 20.62%)
- §9 m7 RTP < m1 RTP: PASS (84.0% < 94.1%)
- §10 MODE7-LOCK: m7 R2 booster ≈ m1 R2 booster ±0.5pp drift?
  - m1 mini 2.79% → m7 mini 2.54% (drift -0.25pp, within ±0.5pp tolerance ✓)
  - m1 minor 1.99% → m7 minor 1.99% (byte-eq ✓)
  - m1 major 1.53% → m7 major 1.53% (byte-eq ✓)
  - m1 grand 0.11% → m7 grand 0.11% (byte-eq ✓)
- §11 GRAND-SIGNATURE: grand 0.112% unchanged ✓
- §12 R1 ≤ R3 ≤ R2 blank: R1+R3 bar cut → R1+R3 blank rise. R2 unchanged. Need to verify R1/R3 blank ≤ R2 blank still holds (was passing in m1 baseline; m7 K_bar cut raises R1/R3 blank but R2 blank is highest at ~50%).
- §13 BLANK-FLANK-DIVERSITY: strip layout unchanged → trivially preserved ✓
- §14 VISUAL-RHYTHM: strip layout unchanged → trivially preserved ✓
- TOP-PATH-1000X: pid 1 ratio 0.987 (R2 high7 + R2 grand byte-eq m1; R1/R3 high7 byte-eq m1) → 1000× path 98.7% of baseline freq ✓
- Mode 1 / 2 / 5 weights: UNTOUCHED ✓
- Paytable / spec / strip: UNTOUCHED ✓

## Output

`session_artifacts/M37/v9_sim_weights/mode_7/weights.json`

Strategy summary: **K_bar=0.82 uniform R1+R3 1/2/3/7 bar; K_wild=1.00 (fully preserved); K_mini=0.91 (mild)**. R2 minor/major/grand/high7/bar byte-eq m1 v5. R1+R3 high7 byte-eq m1 v5. Saved weight proportionally to per-reel blanks.
