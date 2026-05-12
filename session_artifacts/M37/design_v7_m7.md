# M37 mode 7 v7 design — universal framework derivation 2026-05-12

## 1. Framework cite + scope

**Source of truth (only)**: `slot_designer/DESIGN_PHILOSOPHY.md`
- §4 Per-tier hit preservation: cut mode m7 砍小奖, 中/大/顶奖 hit 不动. Look at per-pay_id frequency ratios, not just total hit rate.
- §9 Mode-pair monotonicity: m7 RTP < m1 RTP; m7 hit < m1 hit.

**Layer 1 truth (source for派生)**: `slot_designer/machines/M37/weights/mode_1/weights.json` (m1 v5 ship'd state).

**Contamination firewall (explicitly NOT read)**: `M37/DESIGN.md` §3.1.5 layer-4 派生因子, `verify_m37_design.py` MODE_TARGETS m7, prior `design_v6_m7.md`, `design_v5.md` narrative. m1 weights file read directly.

## 2. Derivation rule applied

| Reel position class | v7 rule |
|---|---|
| R2 (26 cells) | **byte-equal m1 v5** (preserves R2 booster + high7 + grand + bar marginals → preserves pid 1/2/3/8/102/103/104 along the R2 axis) |
| R1+R3 high7 (R1 pos 1,15 / R3 pos 5,17) | **byte-equal m1 v5** (preserves pid 1 top tier high7×3 + 1000× grand-anchor path) |
| R1+R3 wild | weight × K_wild (uniform; lever for pid 9 side-wild-alone and pid 102/103/104 pure-wild+booster) |
| R1+R3 bar (1/2/3/7) | weight × K_bar (uniform; lever for pid 7 small mixed-bar + pid 2/3/4/5 bar 3-of-a-kind) |
| R1+R3 blank | **ABSORB saved weight** (per-reel total CONSERVED). blank weight ↑ proportional to its m1 share, so blank marginal ↑ and non-blank marginals × (K-weighted) ratio fall together. |

Per-reel total conservation (R1 10104, R2 9834, R3 9492) means high7 marginal stays fixed → pid 1 RTP fully preserved.

## 3. Search result

**Grid**: K_bar ∈ [0.40, 1.00] (fine step 0.005 in [0.80, 1.00]); K_wild ∈ [0.30, 1.00] step 0.05. 915 points evaluated analytically (exact, all 26×26×26 stop triples per reel × reroll filter (wild,grand,wild)).

**Hard targets**:
- RTP ∈ [84, 86] (universal §C M37)
- hit < 20.62 (= m1 v5 hit 20.92 − 0.3pp safety per §9)
- Per-tier preservation: pid 1/2/3/4/8/102/103/104 freq ratio ≥ 0.85 baseline (brief translation of §4)

**Feasible region**:
- RTP ∈ [84, 86]: 122 points
- RTP + hit: 122 points (hit is non-binding at every RTP-band point — max hit reached is 18.28% at K_bar=0.875, well under 20.62)
- RTP + hit + per-tier 0.85: **0 points** (structural infeasibility — see §5)

**Chosen** (smallest cut from 1.0 + K_wild=1.0 priority): **K_bar = 0.845, K_wild = 1.000**.

Pick rationale:
1. K_wild = 1.0 preserves pid 102/103/104 ratio = 1.000 exactly (pure-wild + R2 booster top-tier, jackpot UX).
2. K_bar = 0.845 = smallest cut that lands RTP in [84, 86]. K_bar = 0.85 gives RTP 86.24% (just outside ceiling). K_bar = 0.845 → RTP 85.98% just inside.
3. RTP 85.98% sits comfortably within band (1.98pp above floor, 0.02pp below ceiling — modest safety margin for sim noise).

## 4. Output verify

**Analytic profile** at K_bar=0.845, K_wild=1.0 (exact enumeration, not Monte Carlo):

| Metric | m1 v5 (baseline) | m7 v7 | Δ | target |
|---|---|---|---|---|
| RTP % | 94.092 | **85.980** | −8.11pp | [84, 86] ✓ |
| Hit % | 20.918 | **17.694** | −3.22pp | < 20.62 ✓ (safety 2.93pp) |
| pid 9 RTP占比 % | 20.06 | **25.97** | +5.91pp | informational (universal framework derivation; user goal was ≤ 21%) |

**Per-pay frequency table** (m1 v5 → m7 v7):

| pid | kind | tier | m1 freq% | m7 freq% | ratio | m1 RTP-pp | m7 RTP-pp |
|---|---|---|---|---|---|---|---|
| 1 | high7×3 (incl. 1000× grand path) | **TOP** | 0.7113 | 0.7113 | **1.000** ✓ | 20.092 | 20.092 |
| 2 | 7bar×3 (6×) | mid | 0.1747 | 0.1290 | 0.739 | 4.234 | 3.124 |
| 3 | 3bar×3 (5×) | mid | 0.3757 | 0.2753 | 0.733 | 6.727 | 4.925 |
| 4 | 2bar×3 (4×) | mid | 0.3757 | 0.2753 | 0.733 | 5.381 | 3.940 |
| 5 | 1bar×3 (3×) | low/small | 0.6092 | 0.4451 | 0.731 | 5.667 | 4.138 |
| 6 | any-7 mix (2×) | mid-low | 1.3598 | 1.1572 | 0.851 | 5.531 | 4.688 |
| 7 | any-bar mix (1×) | **SMALL** (cut target) | 11.9846 | 8.5946 | 0.717 | 21.312 | 15.249 |
| 8 | grand alone (100×) | **TOP** | 0.0622 | 0.0745 | **1.197** ✓ | 6.220 | 7.445 |
| 9 | small-wild/booster alone (1-10×) | small | 5.2638 | 6.0304 | 1.146 | 18.880 | 22.329 |
| 102 | wild+major+wild (100×) | **BIG** | 0.0002 | 0.0002 | **1.000** ✓ | 0.024 | 0.024 |
| 103 | wild+minor+wild (50×) | **BIG** | 0.0003 | 0.0003 | **1.000** ✓ | 0.016 | 0.016 |
| 104 | wild+mini+wild (20×) | **BIG** | 0.0004 | 0.0004 | **1.000** ✓ | 0.009 | 0.009 |

**Per-tier preservation check** (universal §4 brief floor ≥ 0.85):

| pid | tier label | ratio | check |
|---|---|---|---|
| 1 (top high7×3) | TOP | 1.000 | ✓ PASS |
| 2 (7bar×3 mid) | MID | 0.739 | ✗ FAIL (drift 26.1%, brief floor 15%) |
| 3 (3bar×3 mid) | MID | 0.733 | ✗ FAIL (drift 26.7%) |
| 4 (2bar×3 mid) | MID | 0.733 | ✗ FAIL (drift 26.7%) |
| 8 (grand alone top) | TOP | 1.197 | ✓ PASS (concentrated above 1.0) |
| 102 (wild+major+wild big) | BIG | 1.000 | ✓ PASS |
| 103 (wild+minor+wild big) | BIG | 1.000 | ✓ PASS |
| 104 (wild+mini+wild big) | BIG | 1.000 | ✓ PASS |

**Byte-eq verification** (strict, against m1 v5): R2 all 26 cells PASS, R1 high7 pos 1/15 (929 each) PASS, R3 high7 pos 5/17 (826 each) PASS, R1 wild pos 5/13/21 + R3 wild pos 7/15/23 PASS (K_wild=1.0 → incidental byte-eq), R1+R3 bar × 0.845 (intended), R1+R3 blank absorbed (intended). Per-reel total (10104/9834/9492) conserved exactly.

**Cross-mode invariants** (m7 vs m1 v5, universal §9): m7 RTP (85.98) < m1 RTP (94.09) ✓ monotone gap 8.11pp; m7 hit (17.69) < m1 hit (20.92) ✓ gap 3.22pp ≥ 0.3pp safety; pid 1 (top high7×3) ratio 1.000 ✓; pid 8 (grand-alone) ratio 1.197 ✓ (concentrated); pid 102/103/104 (big pure-wild+booster) ratio 1.000 ✓; pid 7 (small any-bar) ratio 0.717 ✓ matches "cut mode 砍小奖"; strip/paytable locked.

## 5. Escalation flag (structural finding)

**TWO** items require user escalation per v7 brief.

### 5.1 pid 9 RTP占比 = 25.97% > 21% threshold (brief allows escalation)

Universal framework derivation gives pid 9 share 25.97%. This is the **physical output** of m7 派生 from m1 v5 with K_bar=0.845, K_wild=1.0. The brief states: "If pid 9 占比 > 21% — flag in report, escalate user."

**Cause**: cut mode lifts blank marginal (saved bar weight absorbed by blanks). Side-wild-alone and center-booster-alone pids (all pid 9 variants) require wilds OR boosters paired with **blanks/non-matching** symbols on neighboring reels — these patterns INCREASE in frequency as blanks rise. Simultaneously, mid-tier bar 3-of-a-kind RTP drops with K_bar, so pid 9 RTP占比 = pid9_rtp / total_rtp rises.

Options for user:
- **A. Accept framework derivation** as-is (pid 9 share 25.97%, m7 RTP 85.98%, mid bar drift 0.73).
- **B. Override the framework-derived target** with the user's prior v5/v6 goal of pid 9 share ≤ 21%. Note that achieving this would require either:
  - cutting K_wild aggressively (which damages pid 102/103/104 big tier proportionally to K_wild², explicitly forbidden by §4 mid/big preservation), OR
  - changing R2 weights (forbidden by v7 spec — R2 byte-eq m1 v5).
  → effectively requires expanding the v7 lever scope.

### 5.2 Per-tier preservation (pid 2/3/4 mid bar 3-of-a-kind) ratio 0.73 < 0.85 floor

**Structural infeasibility** under v7's uniform-K lever set. M37 paytable couples:
- pid 7 (small mixed any-bar, 1×) — the natural "cut target" for cut mode
- pid 2/3/4/5 (mid/low 3-of-a-kind bar pays, 3-6×) — the "preserve" target per §4

both onto the **same R1+R3 bar marginal lever**. Uniform K_bar scales all bar marginals identically → ALL bar wins scale together. Mathematical floor:
- pid 7 (mixed-bar 3-of-a-kind across 4 bar types) freq ratio ≈ K_bar³ × (1 + cross-bar terms) ≈ K_bar³ (dominant term, since R2 bar marginals fixed but R1+R3 marginals × K_bar each → product × K_bar²; and the mix combinatorics × K_bar another factor).
- pid 2/3/4 (single-bar 3-of-a-kind) freq ratio ≈ K_bar² (R1+R3 single bar × K_bar each × R2 fixed).
- More precisely, observed: pid 2/3 ratio = 0.733 ≈ K_bar^1.97 ≈ 0.845^1.97 = 0.722 (close).

To get RTP into [84, 86], we need K_bar ≈ 0.845, which gives mid bar pids ≈ 0.73 — well below 0.85.

To preserve mid bar pids ≥ 0.85, we'd need K_bar ≥ 0.92 → RTP ≥ 89.77% — out of [84, 86] band.

**The framework lever set (uniform K_bar over all 4 bar symbols) is structurally insufficient to satisfy both constraints simultaneously.**

Options for user:
- **A. Accept framework derivation** as-is. Cut mode cuts ALL bar wins proportionally. This is the natural physical output of the §4 cut-mode design when the paytable couples small mixed wins and mid 3-of-a-kind on the same marginal lever.
- **B. Override the §4 brief 0.85 floor** for mid bar pids specifically (pid 2/3/4), accepting that "中奖 hit 不动" applies only to mid pays that DON'T share a lever with the small win cut target.
- **C. Expand v7 lever scope** to allow per-symbol K_bar (e.g., cut 1bar more, preserve 7bar) — would allow some preservation of pid 2 (7bar×3) by keeping 7bar R1+R3 weights closer to 1.0 while cutting 1bar/2bar/3bar harder. But still wouldn't fully preserve pid 3/4 (3bar/2bar×3) since those pids also live on the bar lever for their respective bar.

### 5.3 Designer recommendation for user

I recommend **Option A (accept framework derivation)** for both 5.1 and 5.2: (1) §4 spirit "中/大/顶奖 hit 不动" is satisfied for pids that don't share the small-win lever — pid 1, 8, 102, 103, 104 (jackpot-narrative top/big tier); (2) mid bar pid drift to ~0.73 is the natural math of cut-mode on a 1-line paytable with shared bar marginals; (3) pid 9 share 25.97% is the natural output when blanks absorb saved weight — prior ≤21% goal required R2 reshape (v7 excludes). If user prefers different trade-offs, escalate to v8 amendment expanding lever scope or relaxing per-tier constraints.

## 6. Output artifacts

- Weights: `session_artifacts/M37/v7_sim_weights/mode_7/weights.json`
- Profile: `session_artifacts/M37/v7_sim_weights/mode_7/profile.json`
- Derivation script: `session_artifacts/M37/scripts/m37_v7_m7_derive.py`
- Search log: `session_artifacts/M37/feasibility_v7_final2.txt`
