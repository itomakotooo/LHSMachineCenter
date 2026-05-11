# M15 v8.1 — §15 PWDF Active Optimization Audit (before / after Mechanism B)

> **Phase C audit** per [`DESIGN_PHILOSOPHY.md`](../../slot_designer/DESIGN_PHILOSOPHY.md) §15.9 mandate. Per philosophy: "**Physical-reel 机台 (无 virtual mapping)**: 必须跑 mechanism B (RTP-neutral blank redistribute) — 不是'可选 nice-to-have'."
>
> **M15 architecture**: 3-reel physical (no virtual reel mapping). Mechanism C unavailable; Mechanism A breaks RTP (per philosophy §15.5 M1 empirical). Mechanism B is the only viable path.
>
> **User confirmation (v8.1 brief)**: mid-pay window visibility drop is "不算副作用,甚至是需求" (welcomed).

---

## 1. Machine-specific §15 floors (M15-locked)

Per philosophy §15.3 + §15.8: floors are machine-specific, NOT cross-machine. Set BELOW post-mechanism-B achieved with 2-5pp safety margin for tuner perturbations.

**Top symbol any-reel `p_window` floor** (per `_PWDF_TOP_ANY_REEL_FLOOR_PCT` in `verify.py`):

| mode | doublediamond | high7 | topdollar | rationale |
|---|---:|---:|---:|---|
| 1 (paid 95%) | 28.0% | 28.0% | 22.0% | standard mode; mechanism B fully applied |
| 2 (lucky 300%) | 17.0% | 25.0% | 10.0% | lucky mode has spread base marginals, mechanism B less dramatic |
| 5 (super-lucky 500%) | 17.0% | 25.0% | 10.0% | tracks mode 2 baseline (lucky derivation) |
| 7 (cut 85%) | 34.0% | 34.0% | 24.0% | cut mode high blank → mechanism B lift is largest |

**Mid-pay any-reel `p_window` floor** (per `_PWDF_MID_PAY_FLOOR_PCT`):
- modes 1/2/5: ≥ 3.0% (cherry / 1bar / 2bar / 3bar each on at least one reel)
- mode 7: ≥ 2.0% (cut shrinks total — relaxed)

These are "didn't disappear entirely" floors. The intentional drop from mechanism B (e.g. cherry R3 mode 1: 18.28% → 4.81%) still well above 3% mid-pay floor.

---

## 2. Per-top-symbol per-reel — BEFORE Mechanism B

**Pre-Mechanism-B state**: v8.1 post-rearrange but pre-redistribute. All blank weights uniform per reel (e.g. mode 1 R1 all blanks weight=36).

### mode 1

| symbol | reel | p_mid | p_window | PWDF |
|---|---|---:|---:|---:|
| doublediamond | R1 | 3.022% | 15.822% | 5.24 |
| doublediamond | R2 | 4.238% | 16.424% | 3.87 |
| doublediamond | R3 | 1.043% | 7.939% | 7.62 |
| **doublediamond any-reel max** | — | — | **16.42%** | — |
| high7 | R1 | 2.844% | 15.644% | 5.50 |
| high7 | R2 | 4.238% | 16.424% | 3.87 |
| high7 | R3 | 2.085% | 15.878% | 7.62 |
| **high7 any-reel max** | — | — | **16.42%** | — |
| topdollar | R3 | 1.283% | 15.076% | 11.75 |
| **topdollar any-reel max** | — | — | **15.08%** | — |

### mode 7

| symbol | reel | p_mid | p_window | PWDF |
|---|---|---:|---:|---:|
| doublediamond | R1 | 3.254% | 17.416% | 5.35 |
| doublediamond | R2 | 3.441% | 19.355% | 5.62 |
| doublediamond | R3 | 1.237% | 8.468% | 6.85 |
| **doublediamond any-reel max** | — | — | **19.36%** | — |
| high7 R1 | — | 2.908% | 17.225% | 5.62 |
| high7 R2 | — | 3.441% | 19.355% | 5.62 |
| **high7 any-reel max** | — | — | **19.36%** | — |
| topdollar | R3 | 1.332% | 15.794% | 11.86 |
| **topdollar any-reel max** | — | — | **15.79%** | — |

(modes 2 / 5 similar pattern — see [`pwdf_pre_mechanism_b.txt`](pwdf_pre_mechanism_b.txt))

---

## 3. Per-top-symbol per-reel — AFTER Mechanism B

### mode 1

| symbol | reel | p_mid | p_window | PWDF |
|---|---|---:|---:|---:|
| doublediamond | R1 | 3.022% | **31.467%** | 10.41 |
| doublediamond | R2 | 4.238% | **31.258%** | 7.37 |
| doublediamond | R3 | 1.043% | **13.312%** | 12.77 |
| **doublediamond any-reel max** | — | — | **31.47%** | — |
| high7 | R1 | 2.844% | **31.111%** | 10.94 |
| high7 | R2 | 4.238% | **30.728%** | 7.25 |
| high7 | R3 | 2.085% | **26.704%** | 12.81 |
| **high7 any-reel max** | — | — | **31.11%** | — |
| topdollar | R3 | 1.283% | **25.822%** | 20.13 |
| **topdollar any-reel max** | — | — | **25.82%** | — |

### mode 7

| symbol | reel | p_mid | p_window | PWDF |
|---|---|---:|---:|---:|
| doublediamond | R1 | 3.254% | **34.641%** | 10.65 |
| doublediamond | R2 | 3.441% | **38.710%** | 11.25 |
| doublediamond | R3 | 1.237% | **14.082%** | 11.38 |
| **doublediamond any-reel max** | — | — | **38.71%** | — |
| high7 R1 | — | 3.062% | **34.450%** | 11.25 |
| high7 R2 | — | 3.441% | **38.710%** | 11.25 |
| **high7 any-reel max** | — | — | **38.71%** | — |
| topdollar | R3 | 1.332% | **27.022%** | 20.29 |
| **topdollar any-reel max** | — | — | **27.02%** | — |

(modes 2 / 5 — see [`pwdf_post_mechanism_b.txt`](pwdf_post_mechanism_b.txt))

---

## 4. Lift summary (post − pre)

| mode | top symbol | pre-B max p_window | post-B max p_window | lift |
|---|---|---:|---:|---:|
| 1 | doublediamond | 16.42% | **31.47%** | **+15.0pp** |
| 1 | high7 | 16.42% | **31.11%** | **+14.7pp** |
| 1 | topdollar | 15.08% | **25.82%** | **+10.7pp** |
| 2 | doublediamond | 11.86% | **20.14%** | **+8.3pp** |
| 2 | high7 | 20.97% | **29.24%** | **+8.3pp** |
| 2 | topdollar | 8.49% | **12.55%** | **+4.1pp** |
| 5 | doublediamond | 12.75% | **20.90%** | **+8.1pp** |
| 5 | high7 | 21.17% | **29.31%** | **+8.1pp** |
| 5 | topdollar | 8.60% | **12.61%** | **+4.0pp** |
| 7 | doublediamond | 19.36% | **38.71%** | **+19.4pp** |
| 7 | high7 | 19.36% | **38.71%** | **+19.4pp** |
| 7 | topdollar | 15.79% | **27.02%** | **+11.2pp** |

**Average lift across all top symbols across all modes: ~11pp**. Mode 1 / mode 7 (where blanks are heavier) see the biggest lifts (15-19pp); lucky modes (2/5) lift less (4-8pp) because base blank weight is lower → less weight to redistribute.

---

## 5. Side effect: mid-pay window visibility drop (intentional)

Per user v8.1 brief: "不算副作用,甚至是需求" (welcomed; user wants visual attention pulled toward branded top symbols).

### mode 1

| symbol | reel | pre-B p_window | post-B p_window | drop |
|---|---|---:|---:|---:|
| 3bar | R2 | 28.61% | 11.79% | -16.8pp |
| 2bar | R1 | 39.82% | 21.96% | -17.9pp |
| 1bar | R2 | 32.19% | 21.32% | -10.9pp |
| cherry | R3 | 18.28% | 4.81% | -13.5pp |
| jackpot | R3 | 7.06% | 6.34% | -0.7pp |

All mid-pay symbols still above the M15-specific 3% mid-pay floor (mode 1). Lowest is cherry R3 at 4.81%.

### mode 7

| symbol | reel | pre-B p_window | post-B p_window | drop |
|---|---|---:|---:|---:|
| 3bar | R3 | 27.97% | 25.98% | -2.0pp |
| 2bar | R1 | 39.81% | 20.00% | -19.8pp |
| 1bar | R3 | 30.83% | 22.45% | -8.4pp |
| cherry | R3 | 18.08% | 4.00% | -14.1pp |
| jackpot | R2 | 8.39% | 9.35% | +0.96pp |

Lowest mid-pay (cherry R3) at 4.00% — still above the M15 mode-7 2% mid-pay floor.

---

## 6. RTP / hit invariance proof

Per philosophy §15.5 mechanism B definition: total Blank weight per reel preserved → all marginals invariant → RTP/hit/share UNCHANGED.

Direct verification (analytic_profile pre/post Mechanism B):

| mode | metric | pre-Mechanism-B | post-Mechanism-B | delta |
|---|---|---:|---:|---:|
| 1 | base RTP | 35.0774% | 35.0774% | 0.0000% |
| 1 | hit rate | 17.4041% | 17.4041% | 0.0000% |
| 2 | base RTP | 99.0333% | 99.0333% | 0.0000% |
| 2 | hit rate | 33.5417% | 33.5417% | 0.0000% |
| 5 | base RTP | 108.3814% | 108.3814% | 0.0000% |
| 5 | hit rate | 33.6078% | 33.6078% | 0.0000% |
| 7 | base RTP | 21.9902% | 21.9902% | 0.0000% |
| 7 | hit rate | 11.4800% | 11.4800% | 0.0000% |

Per-reel total weight preserved (e.g. mode 1 R1: 648 → 648), per-symbol weight preserved (only blank-weight positions redistributed).

---

## 7. Verify red lines locked

`slot_designer/machines/M15/verify.py` [PWDF-FLOOR] category:

```python
_PWDF_TOP_ANY_REEL_FLOOR_PCT = {
    1: {"doublediamond": 28.0, "high7": 28.0, "topdollar": 22.0},
    2: {"doublediamond": 17.0, "high7": 25.0, "topdollar": 10.0},
    5: {"doublediamond": 17.0, "high7": 25.0, "topdollar": 10.0},
    7: {"doublediamond": 34.0, "high7": 34.0, "topdollar": 24.0},
}
_PWDF_MID_PAY_SYMBOLS = ("3bar", "2bar", "1bar", "cherry")
_PWDF_MID_PAY_FLOOR_PCT = {1: 3.0, 2: 3.0, 5: 3.0, 7: 2.0}
```

Inject-bug regression: [`test_inject_pwdf_floor_breach`](../../tests/machines/test_M15_verify_inject_bug.py) zeros mode 1 top-adj Blank weights (undoes Mechanism B) → asserts [PWDF-FLOOR] RED → reverts → asserts clean. Confirms verify.py truly catches §15 violations.

Total [PWDF-FLOOR] check count: **28** (4 modes × {3 top symbols + 4 mid-pay symbols}) — all GREEN on v8.1.

---

## 8. Reproducibility

- Pre-Mechanism-B PWDF dump: [`pwdf_pre_mechanism_b.txt`](pwdf_pre_mechanism_b.txt)
- Post-Mechanism-B PWDF dump: [`pwdf_post_mechanism_b.txt`](pwdf_post_mechanism_b.txt)
- Script: `python session_artifacts/M15/scripts/m15_v81_pwdf_dump.py`
- Mechanism B script: `python session_artifacts/M15/scripts/m15_v81_mechanism_b.py --write --verify`
