# Verify v8 m7 diff (extends v6 diff, replaces v6 m7 only)

> **Stage 5 Verifier output (v8 m7 extension)** per `ONBOARDING_PROCESS.md §4`. Fresh-context derivation of v8 verify red lines from `design_v8_m7.md` (Designer v8 m7) + `critic_review_v8.md` (X SHIP-WITH-CAVEAT). Builds on `verify_v6_diff.md`. m1 / m2 / m5 verify lines NOT touched — v8 only replaces v6 m7.
>
> Output: diff proposal layered on top of v6 diff (which is now committed in live `verify_m37_design.py`).

---

## 0. Scope reminder

- **m1 v5 SHIPPED & LOCKED** — verify untouched
- **m2 v6 SHIPPED & LOCKED** — verify untouched
- **m5 v6 SHIPPED & LOCKED** — verify untouched
- **m7 v6 SHIPPED 09c7871 — TO BE REPLACED by v8** per `critic_review_v8.md §5`
- **v8 m7 lever** (from `design_v8_m7.md §5`): R2 mini ×1.00, R2 minor ×0.80, R2 major ×0.80, R1+R3 wild ×0.95, **all other untouched** (vs v6 which boosted R1+R3 bar ×1.15 + high7 ×1.05)
- **v8 m7 numbers** (from `critic_review_v8.md §1` + `design_v8_m7.md §5`):
  - RTP 85.16% ∈ [84, 86] ✓
  - hit **20.11%** < 20.62 universal §9 safety (margin **0.51pp tight**)
  - pid 9 share **18.82%** ∈ [14, 21] v6 band ✓
- 2 X audit YELLOWs (`critic_review_v8.md §2`):
  - YELLOW §4 — pid 102/103 freq 0.722 (wild²·booster physics floor, designer-justified)
  - YELLOW-borderline §9 — hit safety margin 0.51pp tight; A empirical sub-gate multi-seed must confirm

---

## 1. Diff from v6 m7 → v8 m7 (lever level, for context)

| Lever | v6 m7 (committed) | v8 m7 (proposed replace) | Δ |
|---|---|---|---|
| R2 mini weight | 240 (×0.85 from m7 baseline 284) | **274** (m1 v5 byte-eq, ×1.00 from m1) | mini **UN-cut** — Lightning Link mini UX preserved (`design_v8_m7.md §5`) |
| R2 minor weight | 190 (×0.93) | **156.8** (×0.80 from m1 196) | deeper cut (`design_v8_m7.md §5`) |
| R2 major weight | 126 (×0.81) | **120.0** (×0.80 from m1 150) | similar magnitude but anchored on m1 not m7 baseline |
| R2 high7 (total) | 950 (factor 1.00 vs m7 baseline) | **1280** (m1 v5 byte-eq) | high7 returns to m1 v5 weight (v6 was at m7-baseline weight) |
| R2 grand | 11 LOCKED | 11 LOCKED | unchanged |
| R1+R3 bar per-symbol | ×1.15 from m7 baseline | **m1 v5 byte-eq** (×1.00 vs m1) | bar boost UNDONE — back to m1 levels |
| R1+R3 high7 | ×1.05 from m7 baseline | **m1 v5 byte-eq** (×1.00 vs m1) | high7 boost UNDONE |
| R1+R3 wild | ×1.00 (m7 baseline) | **×0.95** from m1 v5 wild | small cut |

**Critical implication for verify**: v8 m7 is a **slight perturbation off m1 v5** (only R2 mini cut to m1-level, R2 minor/major cut 20%, R1+R3 wild cut 5%). v6 m7 was anchored on m7 baseline with bar/high7 boost.

→ **v8 m7 per-symbol marginals are ≈ m1 v5 marginals** (except booster + wild) → window visibility, archetype, mid-pay floor all **revert to m1-aligned bands**.

---

## 2. verify_m37_design.py MODE_TARGETS[7] adjustments (v6 → v8)

| Field | v6 value (live in code) | v8 new value | Reason (cite) |
|---|---|---|---|
| `rtp` / `rtp_tol_pp` | 85.0 / 1.0 (band [84, 86]) | **same** | v8 RTP 85.16 ∈ [84, 86]. `design_v8_m7.md §5` + `critic_review_v8.md §1`. No change. |
| **`hit_lo` / `hit_hi`** | 0.11 / **0.17** | **0.11 / 0.21** | **Critical change**. v8 m7 hit 20.11% — v6 band upper 0.17 = 17% **does not cover 20.11**. Upper widened to **0.21** to bracket v8 hit 20.11 with 0.89pp safety. Rationale: v8 m7 hit jumps from v6's 15.00% to 20.11% because Designer v8 picked R2 mini = m1 level (not m7-baseline cut) which keeps small-pay frequency higher; combined with R1+R3 bar reverting to m1 level (no v6 +15% boost) — `design_v8_m7.md §5` Option E: hit 20.11 with 0.51pp safety to 20.62 ceiling. `critic_review_v8.md §1 row Hit` confirms "margin 0.51pp tight". Band must NOT exceed 0.21 (would shadow the §9 HIT-MONOTONIC-SAFETY 0.30pp floor — would let hit 21.5+ pass without firing). 0.21 keeps the verify gate functioning: any value > 20.62 still RED via `[HIT-MONOTONIC-SAFETY]`; values 17-21 are now permitted by `[HIT]` band but still subject to the 0.3pp safety constraint. |
| `booster_visible_lo` / `hi` | 0.04 / 0.12 | **same** | v8 m7 booster total = 2.79 + 1.59 + 1.22 + 0.112 = **5.71%** ∈ [4%, 12%] passes. `design_v8_m7.md §5` recommended levers. No change needed. (Note: v6 m7 was 6.08%; v8 5.71% drops slightly due to deeper minor/major cut but mini preserved.) |
| `grand_lo` / `hi` | 0.0007 / 0.0016 | **same** | v8 m7 grand 0.118% (unchanged from v6, weight 11). No change. |
| `hier_ratio_min` | 1.0 | **same** | v8 m7 HIER ratios mini/minor **1.755**, minor/major **1.303**, major/grand 10.9 — all well above 1.0 floor (`critic_review_v8.md §2 row §1` confirms "ratios 1.755/1.303/10.9 well above 1.0"). No change. |
| `shape_js_max` | 0.10 | **same** | No change. |
| `pid9_share_lo` / `hi` | 14.0 / 21.0 | **same** | v8 m7 pid 9 share **18.82%** ∈ [14, 21] passes with 2.18pp safety to ceiling. `design_v8_m7.md §5` + `critic_review_v8.md §1`. v8 lands 0.31pp below v6 19.13. No change. |

### Why hit_hi = 0.21 (not wider)

Brief task §2 asks "改 hit_hi to 0.21 (or wider, since v8 hit 涨到 m1 hit 附近)". Considered three options:

- **0.21** (recommended): brackets v8 actual 20.11 with 0.89pp headroom; just below m1 hit 20.92 to preserve cross-mode "m7 hit < m1 hit" narrative readability when scanning verify output.
- **0.22** (same as m1 hit_hi): consistent ceiling across modes 1+7. But would silently allow m7 hit to equal m1 hit, masking `[HIT-MONOTONIC]` direction — relying entirely on the cross-mode check.
- **0.25** or wider: opens way too much for accidental drift; no design intent for m7 hit to climb 4pp above v8 actual.

**Pick 0.21**. The actual hard red on cross-mode safety is `[HIT-MONOTONIC-SAFETY]` (m1.hit - m7.hit ≥ 0.30pp = m7 < 20.62) which still fires correctly regardless of `[HIT]` band — `[HIT]` is the within-mode "design intent" band; `[HIT-MONOTONIC-SAFETY]` is the cross-mode hard rule. Keeping `[HIT]` at 0.21 gives 0.89pp headroom above v8 actual without masking the cross-mode constraint.

---

## 3. WINDOW-VISIBILITY mode 7 bands (v6 → v8 revert)

Brief task §3 explicitly asks: "v6 m7 R1+R3 bar ×1.15 → bar window vis 高 → v6 widened bands. v8 m7 R1+R3 bar UNTOUCHED → window vis 跟 baseline 相同 → 可能需要 revert 到 v3 baseline 数字".

**Current live code** (verify_m37_design.py line 410):
```python
7: {"r2_grand": (0.10, 0.22), "r1r3_high7": (0.24, 0.38), "r1r3_wild": (0.08, 0.26),
    "r2_booster_total": (0.18, 0.40)},
```

**v6 lowered**:
- `r1r3_high7` lower: 0.26 → **0.24** (because v6 bar ×1.15 diluted high7 window visibility)
- `r1r3_wild` lower: 0.10 → **0.08** (same reason — bar boost diluted wild visibility)

**v8 implication**: v8 reverts R1+R3 bar/high7 to m1 v5 levels (no boost). Strip is locked. → window visibility for R1+R3 high7 and wild on m7 returns to m1-equivalent baseline.

**Predicted v8 m7 window visibility** (back-of-envelope, from R1+R3 high7 marginal ~14% on baseline strip with 3-row window): ~30-35% for R1/R3 high7, ~15-18% for wild (slightly cut by ×0.95).

**Recommendation**:

| Band | v6 (live) | v8 proposed | Reason |
|---|---|---|---|
| m7 `r1r3_high7` | (0.24, 0.38) | **(0.26, 0.40)** | revert to m1-aligned. v8 R1+R3 high7 marginals = m1 v5 byte-eq, so window vis should mirror m1's `(0.26, 0.40)` band. Lower 0.24 was v6-specific accommodation that's no longer needed. |
| m7 `r1r3_wild` | (0.08, 0.26) | **(0.08, 0.26)** keep | v8 R1+R3 wild marginals = m1 v5 × 0.95 (slight cut). Window vis ~15-18% range still well above 0.08 lower; upper 0.26 unchanged. The v6 lower 0.08 was already accommodating; keep it because v8 cut 5% further means even lower vis floor needs to remain. |
| m7 `r2_grand` | (0.10, 0.22) | **same** | unchanged (grand weight unchanged) |
| m7 `r2_booster_total` | (0.18, 0.40) | **same** | unchanged structurally (mini preserved, minor/major slightly cut — booster mass moves from 6.08% to 5.71%, window vis ~25-30% still in band) |

**Net m7 window-visibility changes**: 1 band (`r1r3_high7` lower 0.24→0.26 revert). Other 3 unchanged.

---

## 4. Per-tier preservation §4 verify support — informational only (NOT new red line)

Brief task §4 asks whether to add a `[PER-TIER-PRESERVATION]` red line backing Designer-defined floors (顶 ≥ 0.85 / 中 ≥ 0.80 / 大 ≥ 0.50).

### Analysis

**Arguments for adding red line**:
- `design_v8_m7.md §1` cites universal §4 as hard rule
- `critic_review_v8.md §6.1` explicitly recommends backporting "per-pay_id ratio table" gate to ONBOARDING §5 Stage 4
- Designer floors are explicit numerics that can be checked

**Arguments against** (or against adding it strict-RED right now):
1. **Requires m1 baseline pinned in verify code**. v8's tier floors are *ratios* (m7 freq / m1 freq), so verify needs to know m1 baseline freqs. m1 v5 weights are ship'd so freqs are well-defined, but they aren't currently exposed in verify — would require analytic profile of m1 cached as a baseline constant, or re-computed every run.
2. **m1 changes would invalidate the m7 baseline**. Next time m1 is touched (unlikely but possible), the m7 ratio check would silently shift its reference. This is the "MODE7-LOCK fragility" pattern — currently `check_mode7_lock` does this for boosters only.
3. **Designer floors are deliberate trade-offs**, not invariants. The 0.50 floor for jackpot trio is explicitly *acceptable trade-off* per `critic_review_v8.md §3` ("Designer 这里是 deliberate trade-off justified by structural physics"). Encoding 0.50 as a red line makes the floor immutable, which contradicts the design-time judgment that this floor is contextual.
4. **Universal §4 says "中/大/顶 hit 不动" directionally, not numerically**. Universal layer per `DESIGN_PHILOSOPHY.md §4` says: "用 frozen weights / floor / ceiling 在 tune 里实现" — the floor is a tuner constraint, not a verify constant. Per `WORKFLOW.md §2.6 boundary discipline`: agent NOT allowed to introduce numerical boundaries user hasn't stated. Designer's 0.85/0.80/0.50 are *Designer's interpretation of universal §4*, not user red lines.

**Recommendation**: Add as **informational YELLOW** check `[MODE7-PER-PID-RATIO]`, NOT a hard RED. Implementation:

```python
def check_mode7_per_pid_ratio(profiles: dict) -> list[tuple[bool | None, str]]:
    """Informational YELLOW — m7 per-pay_id frequency / m1 per-pay_id frequency.
    
    Surface ratios; no hard red. Universal §4 says "中/大/顶 hit 不动" directionally;
    specific numerical floors are Designer-interpretation, not universal numerics.
    
    Use as audit aid: future tunes of m7 (or m1) should see ratios shift; tooling
    that flags ratios < 0.50 on mid-tier paths warns of structural drift.
    """
    out = []
    if 1 not in profiles or 7 not in profiles:
        return out
    m1_pay_hits = profiles[1]["pay_hits"]
    m7_pay_hits = profiles[7]["pay_hits"]
    # Tier classification per design_v8_m7.md §2:
    TIERS = {
        "1": ("top", "pid 1 (line 3-same high7, 1000× path)"),
        "8": ("top", "pid 8 (center grand alone 100×)"),
        "2": ("mid", "pid 2 (3-7bar)"),
        "3": ("mid", "pid 3 (3-3bar)"),
        "4": ("mid", "pid 4 (3-2bar)"),
        "5": ("mid", "pid 5 (3-1bar)"),
        "6": ("mid", "pid 6 (7-bar mix)"),
        "7": ("small", "pid 7 (any-bar)"),
        "9": ("mixed", "pid 9 (booster/wild alone)"),
        "102": ("big", "pid 102 (Major Jackpot wild×major×wild)"),
        "103": ("big", "pid 103 (Minor Jackpot wild×minor×wild)"),
        "104": ("big", "pid 104 (Mini Jackpot wild×mini×wild)"),
    }
    # Floors (Designer-interpretation, informational only):
    TIER_FLOOR = {"top": 0.85, "mid": 0.80, "big": 0.50, "small": None, "mixed": None}
    for pid, (tier, name) in TIERS.items():
        p_m1 = m1_pay_hits.get(pid, 0.0)
        p_m7 = m7_pay_hits.get(pid, 0.0)
        if p_m1 <= 0:
            continue
        ratio = p_m7 / p_m1
        floor = TIER_FLOOR.get(tier)
        if floor is not None and ratio < floor:
            out.append((None, _warn(
                f"[MODE7-PER-PID-RATIO] {name} ratio {ratio:.3f} < {floor:.2f} {tier}-tier floor (informational; Designer §4 interpretation)"
            )))
        else:
            out.append((None, _warn(
                f"[MODE7-PER-PID-RATIO] {name} ratio {ratio:.3f} (informational, tier={tier})"
            )))
    return out
```

`None` as the first tuple element means "skip count" — caller doesn't add to `results`, only prints. This matches the pattern used by `check_bucket_ge1_5_yellow` from the v5 diff.

**Verdict on adding the function**: **YES, add as informational only**. Provides audit transparency without locking in Designer-interpretation numerics. Future tunes will see ratios in verify output and judge against `critic_review_v8.md §3` reasoning.

---

## 5. Expected verify output on v8 (m1 ship'd + m2/m5 v6 + m7 v8)

```
=== M37 design verification ===

Strip-level: 3 GREEN

Mode 1 (v5 SHIP'd unchanged): ALL GREEN (1 informational YELLOW [BUCKET-GE1_5])

Mode 2 (v6 SHIP'd unchanged): ALL GREEN

Mode 5 (v6 SHIP'd unchanged): ALL GREEN

Mode 7 (v8 — REPLACE v6):
  RTP 85.16%  hit 20.115%  CV ~11
  GREEN  [RTP]                 mode 7 RTP 85.163% ∈ [84.0, 86.0]
  GREEN  [HIT]                 mode 7 hit 20.115% ∈ [11%, 21%]   ← v8 hit_hi 0.17→0.21
  GREEN  [PID9-SHARE]          mode 7 pid9 18.82% ∈ [14%, 21%]   ← v8 same band, v8 actual 18.82
  GREEN  [BUCKET-CAP]
  GREEN  [BOOSTER-R1R3-EMPTY]
  GREEN  [WILD-R2-EMPTY]
  GREEN  [BOOSTER-HIER]        mini/minor=1.755x, minor/major=1.303x (≥ 1.0)
  GREEN  [BOOSTER-VISIBLE]     R2 booster total 5.71% ∈ [4%, 12%]
  GREEN  [GRAND-SIGNATURE]     R2 grand 0.118% ∈ [0.07%, 0.16%]
  GREEN  [REEL-ASYMMETRY]      blanks ok; top R1 ≥ R3 (m7 inherits m1 structure)
  GREEN  [TOP-PATH-1000X]
  GREEN  [TOP-PATH-1000X-FREQ] mode 7 1 in ~25k ∈ [15k, 50k]
  GREEN  [ARCHETYPE-HIGH7]     R1+R3 m1 v5 byte-eq → ±30% trivially holds
  GREEN  [ARCHETYPE-BAR]       all bar tiers same as m1 v5 → ±25% holds
  GREEN  [ARCHETYPE-WILD]      R1+R3 wild × 0.95 from m1 v5 → ±30% holds (well within ×0.95)
  GREEN  [WINDOW-VISIBILITY]   m7 R2 grand window ~18-19% ∈ [10%, 22%]
  GREEN  [WINDOW-VISIBILITY]   m7 R1+R3 high7 window ~30-32% ∈ [26%, 40%]   ← v8 band reverted to m1-aligned
  GREEN  [WINDOW-VISIBILITY]   m7 R1+R3 wild window ~15-17% ∈ [8%, 26%]
  GREEN  [WINDOW-VISIBILITY-CAP] mode 7 no top symbol exceeds 50%
  GREEN  [BLANK-RATIO-CAP]     mode 7 ≤ 5x
  GREEN  [MID-PAY-VISIBLE-FLOOR] mode 7 all mid-pay ≥ 8%

Cross-mode invariants:
  GREEN  [MODE7-LOCK]          R2 mini m1 2.786 / m7 2.786 (drift 0.000pp)
  GREEN  [MODE7-LOCK]          R2 minor m1 1.993 / m7 1.594 (drift 0.399pp ≤ 0.5pp tier 1)
  GREEN  [MODE7-LOCK]          R2 major m1 1.525 / m7 1.220 (drift 0.305pp ≤ 0.5pp tier 1)
  GREEN  [MODE7-LOCK]          R2 grand m1 0.1119 / m7 0.118 (drift 0.006pp ≤ 0.5pp)
  GREEN  [MODE5-BASE-LOCK]     mode 5 base byte-eq mode 2
  GREEN  [RTP-MONOTONIC]       m7 85.2 < m1 94.1 < m2 303.5 < m5 507.6
  GREEN  [HIT-MONOTONIC]       m7 20.11% < m1 20.92% < m2 32.21% ≈ m5 33.09%
  GREEN  [HIT-MONOTONIC-SAFETY] m1 - m7 = 0.81pp ≥ 0.30pp safety floor   ← TIGHT (was 5.92pp on v6)
  GREEN  [TOP-JACKPOT-ESCALATION]

  YELLOW [MODE7-PER-PID-RATIO] pid 1 (1000× top) ratio 0.958 (tier=top)              ← NEW informational
  YELLOW [MODE7-PER-PID-RATIO] pid 8 (grand alone) ratio 1.002 (tier=top)
  YELLOW [MODE7-PER-PID-RATIO] pid 2 (3-7bar) ratio 0.931 (tier=mid)
  YELLOW [MODE7-PER-PID-RATIO] pid 3 (3-3bar) ratio 0.942 (tier=mid)
  YELLOW [MODE7-PER-PID-RATIO] pid 4 (3-2bar) ratio 0.942 (tier=mid)
  YELLOW [MODE7-PER-PID-RATIO] pid 5 (3-1bar) ratio 0.952 (tier=mid)
  YELLOW [MODE7-PER-PID-RATIO] pid 6 (7-bar mix) ratio 0.977 (tier=mid)
  YELLOW [MODE7-PER-PID-RATIO] pid 7 (any-bar) ratio 0.983 (tier=small)
  YELLOW [MODE7-PER-PID-RATIO] pid 9 (booster/wild alone) ratio 0.913 (tier=mixed)
  YELLOW [MODE7-PER-PID-RATIO] pid 102 (Major Jackpot) ratio 0.722 (tier=big)        ← Designer-justified, > 0.50 floor
  YELLOW [MODE7-PER-PID-RATIO] pid 103 (Minor Jackpot) ratio 0.722 (tier=big)
  YELLOW [MODE7-PER-PID-RATIO] pid 104 (Mini Jackpot) ratio 0.902 (tier=big)

=== Result: N/N GREEN; YELLOW informational: 13 (1 BUCKET-GE1_5 m1 + 12 MODE7-PER-PID-RATIO) ===
```

**Predicted total**: 0 RED. `[HIT-MONOTONIC-SAFETY]` margin **0.81pp** (m1 20.92 - m7 20.11) — passes 0.3pp floor with **0.51pp headroom**. This is the X-audit-flagged tight margin (`critic_review_v8.md §5 Caveat 1`). Verify gate PASSES on the 4-mode v8 set, but commit message must flag the tight margin per X recommendation.

---

## 6. TDD inject tests added (extends v6 diff §4)

For new/changed v8 bands. Append to `test_verify_m37_v8_red_lines.py` (or merge into the v5+v6 test file).

| Test ID | Category | Inject (v8 m7 weight mutation) | Expected RED | Revert | Expected GREEN |
|---|---|---|---|---|---|
| v8-T1 | `[HIT]` m7 upper 0.21 | mode 7: R1+R3 bar all positions ×1.5 (push hit above 21) | `[HIT] mode 7 hit ~22% NOT in [11%, 21%]` | restore | `[HIT] mode 7 hit 20.115% ∈ [11%, 21%]` |
| v8-T2 | `[HIT-MONOTONIC-SAFETY]` margin 0.3pp | mode 7: cut R2 mini ×0.7 + R1+R3 bar ×1.05 (push m7 hit to 20.7, breaks 0.3pp floor) | `[HIT-MONOTONIC-SAFETY] gap 0.22pp < 0.30pp safety floor` | restore | `[HIT-MONOTONIC-SAFETY] gap 0.81pp ≥ 0.30pp` |
| v8-T3 | `[WINDOW-VISIBILITY]` m7 R1+R3 high7 lower revert 0.26 | mode 7: blank weights × 5 near every R1/R3 high7 position (dilute high7 window visibility below 0.26) | `[WINDOW-VISIBILITY] mode 7 R1 high7 ~22% NOT in [26%, 40%]` | restore | `[WINDOW-VISIBILITY] mode 7 R1+R3 high7 ~30% ∈ [26%, 40%]` |
| v8-T4 | `[MODE7-LOCK]` minor drift tier 1 | mode 7: R2 minor ×0.5 (push m7 minor to ~0.80%, drift from m1 1.99 by 1.20pp > 0.5pp) | `[MODE7-LOCK] R2 minor drift 1.20pp > 0.5pp tolerance` | restore | `[MODE7-LOCK] R2 minor drift 0.399pp ≤ 0.5pp` |
| v8-T5 | `[BOOSTER-HIER]` ratio 1.0 (regression) | mode 7: R2 mini × 0.4 (push mini below minor — breaks monotone) | `[BOOSTER-HIER] violations: mini/minor 0.70x (need ≥ 1.0x with hi > lo)` | restore | `[BOOSTER-HIER] mini/minor=1.755x, minor/major=1.303x` |
| v8-T6 | `[MODE7-PER-PID-RATIO]` informational floor breach detection | mode 7: R1+R3 wild × 0.5 (push pid 102/103 ratio = 0.5²×0.8 = 0.20 < 0.50 big-tier floor) | YELLOW emitted: `[MODE7-PER-PID-RATIO] pid 102 ratio 0.200 < 0.50 big-tier floor (informational)` | restore | YELLOW emitted: `pid 102 ratio 0.722 (informational, tier=big)` (within floor — different YELLOW msg) |

Test v8-T6 is informational — it doesn't fail verify hard, but the test asserts the YELLOW message contains "< 0.50 big-tier floor" wording so future regressions break visibility (Designer/X can detect it in CI logs).

---

## 7. Python diff (extends v6, layered on live verify_m37_design.py)

```diff
--- a/slot_designer/scripts/verify_m37_design.py  (after v5+v6 diff committed)
+++ b/slot_designer/scripts/verify_m37_design.py  (with v8 m7 diff layered)
@@ -100,17 +100,21 @@ MODE_TARGETS = {
     7: {
-        # v6 amendment: RTP 85.02 / hit 15.00 / pid9 share 19.13%
-        # MODE7-LOCK tier 1 ±0.5pp drift preserved
-        # - hit_hi 0.155→0.17 (V verify_v6_diff: bar ×1.15 lift, hit 15.00 close to v3 15.5 upper)
-        # - hier_ratio_min 1.3→1.0
-        # - pid9_share band [14, 21]% (NEW per V verify_v6_diff, m7 v3 baseline 26.29%)
+        # v8 amendment 2026-05-12 (replaces v6 09c7871): RTP 85.16 / hit 20.11 / pid9 share 18.82%
+        # Designer v8 lever: R2 mini ×1.00 (Lightning Link mini UX preserved) / R2 minor ×0.80
+        # / R2 major ×0.80 / R1+R3 wild ×0.95. All other R1+R3 (bar, high7) reverted to m1 v5 byte-eq.
+        # See design_v8_m7.md §5 + critic_review_v8.md SHIP-WITH-CAVEAT.
+        # - hit_hi 0.17→0.21 (V verify_v8_diff §2: v8 hit 20.11 — was 15.00 on v6)
+        # - HIT-MONOTONIC-SAFETY enforced separately (gap = m1 hit - m7 hit ≥ 0.3pp)
+        #   v8 actual gap: 20.92 - 20.11 = 0.81pp (X-audit YELLOW-borderline; A multi-seed must confirm)
+        # - pid9_share band [14, 21] unchanged (v8 actual 18.82%, was 19.13% on v6)
+        # - hier_ratio_min 1.0 unchanged (v8 actual ratios 1.755/1.303/10.9 well above)
         "rtp": 85.0, "rtp_tol_pp": 1.0,
-        "hit_lo": 0.11, "hit_hi": 0.17,
+        "hit_lo": 0.11, "hit_hi": 0.21,
         "booster_visible_lo": 0.04, "booster_visible_hi": 0.12,
         "grand_lo": 0.0007, "grand_hi": 0.0016,
         "hier_ratio_min": 1.0,
         "shape_js_max": 0.10,
         "pid9_share_lo": 14.0, "pid9_share_hi": 21.0,
     },
 }
@@ -407,11 +411,12 @@ def check_window_visibility(strips: list[list[str]], weights: list[list[int]], m
         1: {"r2_grand": (0.10, 0.22), "r1r3_high7": (0.26, 0.40), "r1r3_wild": (0.10, 0.26),
             "r2_booster_total": (0.18, 0.40)},
-        # m7 v6 2026-05-12: R1+R3 bar ×1.15 + high7 ×1.05 → high7/wild window vis slightly
-        # diluted by bar weight increase. Bands widened lower: high7 26→24 / wild 10→8.
-        # Universal §15 PWDF still satisfied (mid-pay floor 8% any-reel hold).
-        7: {"r2_grand": (0.10, 0.22), "r1r3_high7": (0.24, 0.38), "r1r3_wild": (0.08, 0.26),
+        # m7 v8 2026-05-12 (replaces v6): R1+R3 bar/high7 reverted to m1 v5 byte-eq (no v6 boost).
+        # → R1+R3 high7 window vis returns to m1-aligned range. r1r3_high7 lower 0.24 → 0.26 (revert).
+        # r1r3_wild lower kept at 0.08 (v8 wild × 0.95 cut, slight extra dilution vs m1).
+        7: {"r2_grand": (0.10, 0.22), "r1r3_high7": (0.26, 0.40), "r1r3_wild": (0.08, 0.26),
             "r2_booster_total": (0.18, 0.40)},
+        # NOTE: m7 was v6-anchored (bar/high7 boosted); v8 reverts to m1-anchored except booster + wild.
         2: {"r2_grand": (0.10, 0.45), "r1r3_high7": (0.15, 0.40), "r1r3_wild": (0.05, 0.35),
             "r2_booster_total": (0.35, 0.60)},
         5: {"r2_grand": (0.15, 0.55), "r1r3_high7": (0.15, 0.40), "r1r3_wild": (0.05, 0.35),
             "r2_booster_total": (0.35, 0.60)},
     },
@@ -540,6 +545,71 @@ def check_mode7_lock(profiles: dict, marginals: dict) -> list[tuple[bool, str]]:
     return out
 
 
+def check_mode7_per_pid_ratio(profiles: dict) -> list[tuple[bool | None, str]]:
+    """[MODE7-PER-PID-RATIO] informational YELLOW — m7 per-pay_id freq / m1 per-pay_id freq.
+
+    Universal §4 says "中/大/顶 hit 不动" directionally; numerical floors are
+    Designer-interpretation (see design_v8_m7.md §1+§2+§4). Designer v8 floors:
+      top (pid 1 + pid 8): ≥ 0.85
+      mid (pid 2-6): ≥ 0.80
+      big (pid 102/103/104 = wild²·booster Jackpot UX): ≥ 0.50 (wild² physics floor)
+
+    NOT a hard red — verify never fails on this. Always YELLOW output for audit
+    transparency. Future tunes that drift below tier floors get caught in CI
+    logs even though verify gate passes.
+
+    Per WORKFLOW.md §2.6 boundary discipline: agent does not introduce numerical
+    boundaries user hasn't stated. Designer's tier floors are Designer-judgment
+    of how to apply universal §4 — surfaced here for transparency, not enforced.
+    """
+    out: list[tuple[bool | None, str]] = []
+    if 1 not in profiles or 7 not in profiles:
+        return out
+    m1_pay_hits = profiles[1].get("pay_hits", {})
+    m7_pay_hits = profiles[7].get("pay_hits", {})
+    # Tier classification per design_v8_m7.md §2 (Designer's reading of universal §4):
+    TIERS = [
+        ("1",   "top",   "pid 1 (line 3-same high7, 1000× path)"),
+        ("8",   "top",   "pid 8 (center grand alone 100×)"),
+        ("2",   "mid",   "pid 2 (3-7bar)"),
+        ("3",   "mid",   "pid 3 (3-3bar)"),
+        ("4",   "mid",   "pid 4 (3-2bar)"),
+        ("5",   "mid",   "pid 5 (3-1bar)"),
+        ("6",   "mid",   "pid 6 (7-bar mix)"),
+        ("7",   "small", "pid 7 (any-bar)"),
+        ("9",   "mixed", "pid 9 (booster/wild alone, mixed sub-tiers)"),
+        ("102", "big",   "pid 102 (Major Jackpot wild×major×wild)"),
+        ("103", "big",   "pid 103 (Minor Jackpot wild×minor×wild)"),
+        ("104", "big",   "pid 104 (Mini Jackpot wild×mini×wild)"),
+    ]
+    TIER_FLOOR = {"top": 0.85, "mid": 0.80, "big": 0.50, "small": None, "mixed": None}
+    for pid, tier, name in TIERS:
+        p_m1 = m1_pay_hits.get(pid, 0.0)
+        p_m7 = m7_pay_hits.get(pid, 0.0)
+        if p_m1 <= 0:
+            continue
+        ratio = p_m7 / p_m1
+        floor = TIER_FLOOR.get(tier)
+        if floor is not None and ratio < floor:
+            msg = f"[MODE7-PER-PID-RATIO] {name} ratio {ratio:.3f} < {floor:.2f} {tier}-tier floor (informational; Designer §4 interpretation)"
+        else:
+            msg = f"[MODE7-PER-PID-RATIO] {name} ratio {ratio:.3f} (informational, tier={tier})"
+        out.append((None, _warn(msg)))
+    return out
+
+
 def check_mode5_base_lock(weights: dict, strips: list) -> tuple[bool, str]:
     ...
@@ -660,6 +730,10 @@ def main() -> int:
     for ok, msg in check_mode7_lock(profiles, marginals):
         results.append(ok); print(msg)
+    # v8 NEW: informational YELLOW per-pay_id ratio m7 vs m1 (universal §4 audit transparency)
+    for ok, msg in check_mode7_per_pid_ratio(profiles):
+        if ok is not None:
+            results.append(ok)
+        print(msg)
     if 2 in raw_weights and 5 in raw_weights:
         ok, msg = check_mode5_base_lock(raw_weights, strips); results.append(ok); print(msg)
```

**Net code changes**:
1. `MODE_TARGETS[7]`: `hit_hi` 0.17 → **0.21** + comment block updated to reflect v8
2. `check_window_visibility` band table for mode 7: `r1r3_high7` lower 0.24 → **0.26** (revert) + comment updated
3. **NEW** `check_mode7_per_pid_ratio` function (informational YELLOW, no hard red)
4. `main()`: 1 new loop call after `check_mode7_lock`

No new bands replaced as RED; no MODE_TARGETS structural shape change.

---

## 8. Commit message must-includes (per critic_review_v8.md §5)

Per `critic_review_v8.md §5 Caveat 1 + Caveat 2`, the main session commit that ships v8 m7 must explicitly note:

1. **Hit margin tight**: `[HIT-MONOTONIC-SAFETY]` gap 20.92 - 20.11 = **0.81pp** (analytic). 50k MC sampling 1σ ≈ 0.36pp → tight; **A empirical sub-gate must multi-seed (200k + 600k)** confirm gap ≥ 0.3pp holds across seeds. If multi-seed worst-case m7 hit ≥ 20.62 → reject v8 + explore Option G (R1+R3 bar ×0.95 per `critic_review_v8.md §4.3 Hidden candidate`).
2. **pid 102/103 freq 0.722**: wild²·booster math floor (0.95² × 0.80 = 0.722). NOT a designer cut for cost-saving — structural physics. Baseline jackpot freq 1/3.7k-4.4k is lifetime-tier player-invisible; 0.72× freq = single-player session indistinguishable. Per X audit "Designer Option E SHIP-acceptable... 大-tier floor 0.50 acceptable trade-off cite reasoning is structural physics not laziness".
3. **v8 m7 replaces v6 m7 09c7871** — not a brand new commit; specifically supersedes.

Verify itself doesn't enforce these (they're commit-message hygiene per X's process backport recommendations in `critic_review_v8.md §6`). The new `[MODE7-PER-PID-RATIO]` informational YELLOW makes them visible in verify output every run.

---

## 9. 80-word summary

v8 m7 verify diff layered on v6: **2 changes + 1 new informational function**. (1) `MODE_TARGETS[7].hit_hi` 0.17→**0.21** — v8 m7 hit 20.11 (was 15.00 v6); §9 HIT-MONOTONIC-SAFETY 0.81pp margin still passes 0.3pp floor but tight (X YELLOW). (2) `check_window_visibility[7].r1r3_high7` lower **0.24→0.26 revert** — v8 m7 R1+R3 bar/high7 reverted to m1 v5 byte-eq (no v6 boost). (3) **NEW** `check_mode7_per_pid_ratio` informational YELLOW surfaces top/mid/big tier ratios per `design_v8_m7.md §4`; no hard red (Designer-interpretation, not user red). pid 102/103 0.72 wild² physics floor visible. 6 TDD inject tests. m1/m2/m5 untouched.
