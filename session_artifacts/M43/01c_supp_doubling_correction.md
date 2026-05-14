# M43 01c §3 Win-Doubling Rule — Stage 2.5 Empirical Correction

**Date**: 2026-05-14  
**Author**: slot-implementer (Stage 2.5)  
**Status**: Authoritative correction to `01c_field_analysis.md §3 "Win-doubling rule"` lines 99-106.  
**Replaces**: 01c §3 claim that `(1bar, blankdown, 1bar)` → 20,000 credits.

---

## §1 Background — What 01c §3 Said

`01c_field_analysis.md §3 "Win-doubling rule"` (lines 99-100) states:

> "With one extra wild in the window (e.g. `1bar, blankdown, 1bar` where R2 has a wild on top row), wins 20,000."

This claim was the Analyst's initial HIGH/MED-confidence observation that `blankdown` on the payline triggers a 2× doubling of the bar pay (from 10,000 to 20,000 credits for pay_id 6). The same paragraph also states:

> "pay_id=9 base 2,000; doubled to 4,000 when the wild is on R2 mid-row (vs. only blankup/blankdown adjacent)."

The pay_id=9 part of this claim is CORRECT. The bar-pay part is INCORRECT. See §2 below.

---

## §2 Empirical Correction — Actual Rule

Stage 2.5 engine implementation analyzed production rawdata (chunk_0001-0003, ~47k spins) against multiple implementation hypotheses. The correct rule is as follows.

### Bar/7 pays (pay_ids 2–7): NO post-eval doubling from off-payline or adjacent wilds

- When a **literal `wild`** is ON the payline mid-row as part of a bar/7 three-match combination, the standard evaluator's `wild_product` stage applies `wild.multiplier = 2`, giving the 2× factor.
- `blankup` and `blankdown` on the payline mid-row have `multiplier = 1` in `spec.json`. They substitute for the bar/7 family (via `kind: "wild"`) but do NOT contribute an additional doubling factor.
- There is **no** off-payline wild doubling for bar/7 pays. A literal `wild` appearing in the top or bottom row (off the payline) does NOT affect the payout of a bar/7 pay on the payline. The 01c §3 description of "extra wild in the window" was an over-interpretation.

### Pay_id 9 (side_wild_alone): post-eval doubling depends on which wild-family symbol is ON the payline

- When a **literal `wild`** is on the payline mid-row → pay_id 9 fires at 4× (doubled from the standard 2× base). This is because when `wild` occupies mid-row, `blankdown` appears at top-row and `blankup` appears at bot-row of the same reel — these off-payline markers function as the adjacent-wild bonus indicator. Standard evaluator fires `side_wild_alone` at 2×; plugin post-evaluator (Rule C in `feature.py`) doubles it to 4×.
- When `blankup` or `blankdown` is on the payline mid-row → pay_id 9 fires at 2× (no doubling). The literal `wild` they represent is already off-payline (top or bot row); no doubling is triggered.

The pay_id=9 part of 01c §3 is confirmed correct:  
> "doubled to 4,000 when the wild is on R2 mid-row (vs. only blankup/blankdown adjacent)"  
= pay_id 9 at 4× when literal wild on payline = YES, confirmed.

---

## §3 Concrete Examples Table

| payline (col0, col1, col2) | pay_id | multiplier | mechanism | 01c §3 claim | correct |
|---|---|---|---|---|---|
| `(1bar, blankdown, 1bar)` | 6 | **10×** | std eval: blankdown.mult=1 → 10×1=10× | "20×" (wrong) | **10×** |
| `(1bar, wild, 1bar)` | 6 | **20×** | std eval wild_product: wild.mult=2 → 10×2=20× | implied correct | **20×** |
| `(blank, blankup, blank)` | 9 | **2×** | side_wild_alone 2×; blankup on payline → no Rule C | 01c correct | **2×** |
| `(blank, blankdown, blank)` | 9 | **2×** | side_wild_alone 2×; blankdown on payline → no Rule C | (not explicitly covered in 01c) | **2×** |
| `(blank, wild, blank)` | 9 | **4×** | side_wild_alone 2× → Rule C doubles to 4× | "4,000" = correct | **4×** |
| `(3bar, blankdown, 3bar)` | 4 | **40×** | std eval: blankdown.mult=1 → 40×1=40× | 01c: "base 40,000; doubled 80,000" — 80× is WRONG for blankdown payline | **40×** |
| `(3bar, wild, 3bar)` | 4 | **80×** | std eval wild_product: wild.mult=2 → 40×2=80× | 80× for this pattern is correct | **80×** |

Key: The pattern `(3bar, blankdown, 3bar)` → 80,000 claimed in 01c §3 is wrong if blankdown is on the payline. 80× only occurs when literal `wild` is on the payline.

---

## §4 Implication for Stage 4 Designer and Stage 5 Verifier

**Read 01c §3 "Win-doubling rule" together with this supp file. This supp is authoritative.**

1. **01c §3 lines 99-101** ("with one extra wild in the window, wins 20,000") refers to the pattern `(1bar, blankdown, 1bar)`. This is INCORRECT. The correct win for this pattern is 10,000. The 20,000 win for pay_id 6 occurs only when literal `wild` is on the payline: `(1bar, wild, 1bar)`.

2. **Stage 4 Designer** should not design bonus features or target distributions assuming blankdown/blankup on a bar-pay payline gives a 2× bonus. They do not — they give the base pay only. The doubling bonus for bar pays requires the literal `wild` on the payline.

3. **Stage 5 Verifier** should verify the bar-pay multiplier distribution using the corrected rule: pay_id 6 at 10× corresponds to blankup/blankdown on payline; pay_id 6 at 20× corresponds to literal wild on payline. Do not verify against 01c §3 directly for the win-doubling claim.

4. **Engine implementation** (`feature.py _apply_payline_post_eval`) correctly implements:
   - Rule B: pay_id 8 override (HIGH confidence, 100% hit coverage).
   - Rule C: pay_id 9 doubling only when literal `wild` on payline (HIGH confidence, ~47k spins, 600+ pay_id 9 hits).
   - Rule A (no-op): bar/7 pays handled entirely by standard evaluator — no plugin action needed.

5. **Known defect**: Virtual engine over-estimates the pay_id 6 40× rate (~1% virtual vs 0.08% production, ~12.5× over-estimation, structural cause: virtual reel weight marginals produce more double-wild-on-payline events). Stage 6 weight refit will address. See `02b_stage_2_5_notes.md §4 item 4`.
