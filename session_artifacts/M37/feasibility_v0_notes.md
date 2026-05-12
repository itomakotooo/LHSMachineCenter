# Feasibility evidence — main-session exploratory variants (PRE-Designer)

> **Status**: evidence not conclusion. Designer should verify independently or find better lever.
>
> **Date**: 2026-05-11 main session pre-Designer-spawn
>
> **Method**: mutate `mode_1/weights.json` in-memory, call `analytic_profile()`, compare to baseline.

## Baseline (mode 1 current)

- RTP 95.45% (engine analytic — note real-machine 95.04% from 2.62M sample, drift ~0.4pp is expected analytic vs empirical)
- hit 20.07%
- ge1_5 RTP 19.59pp
- ge5_10 RTP 14.02pp
- ge10_20 RTP 23.41pp
- ge20_lt50 RTP 9.69pp / ge50_lt100 RTP 6.85pp / ge20-100 total 16.54pp
- ge100+ total 21.88pp
- R2 mini 3.73% / minor 2.68% / major 2.04% / grand 0.112%  (HIER ratios 1.39/1.31/18.2 ✓)
- R1: high7 14.25% wild 1.78% bar 49.49%
- R3: high7 13.49% wild 1.80% bar 49.52%

## Target (user brief)

- RTP ≈ 95% (hold)
- hit 14-16%
- ge1_5 ↓ ~10pp (→ ~9.6pp)
- ge20-100 ↑ ~10pp (→ ~26.5pp) ⚠ structural-feasibility doubt

## Top ge1_lt5 source decomposition

| Combo | P | RTP-pp |
|---|---|---|
| pid 7 mult 1× (any-bar mixed) | 7.35% | **7.35** |
| pid 9 mult 2× (mini alone + R1R3 non-match) | 2.56% | **5.13** |
| pid 9 mult 1× (side wild alone + R1R3 non-match) | 2.58% | 2.58 |
| pid 7 mult 2× (any-bar + 1 wild) | 0.68% | 1.36 |
| pid 6 mult 2× (high7+7bar mixed) | 0.65% | 1.31 |
| pid 5 mult 3× (1bar×3 base) | 0.29% | 0.87 |
| pid 4 mult 4× (2bar×3 base) | 0.16% | 0.62 |
| pid 6 mult 4× (high7-wild-7bar etc) | 0.10% | 0.38 |

Sum top 8 ≈ 19.6pp ≈ ge1_5 total ✓

**Levers that cut ge1_5**:
- Cut R2 mini → cuts pay_id 9 mult 2× (~5pp)
- Cut R1+R3 bar marginal → cuts pay_id 7 mult 1× (~7pp)
- Cut R1+R3 wild → cuts pay_id 9 mult 1× (~2.5pp) + pay_id 7 mult 2×

## Top ge20-100 source decomposition (16.5pp total)

| Combo | P | RTP-pp |
|---|---|---|
| (high7×3) × minor = 50× | 0.0647% | 3.24 |
| (3bar×3) × major = 50× | 0.0426% | 2.13 |
| (high7×3) × mini = 20× | 0.0902% | 1.80 |
| (2bar×3) × major = 40× | 0.0426% | 1.70 |
| (1bar×3) × major = 30× | 0.0556% | 1.67 |
| (3bar×3) × minor = 25× | 0.0558% | 1.39 |
| (2bar×3) × minor = 20× | 0.0558% | 1.12 |
| pid 6 mult 20× (high7+7bar × major) | 0.0522% | 1.04 |
| (7bar×3) × major = 60× | 0.0287% | 1.72 (in ge50_100) |
| (7bar×3) × minor = 30× | 0.0376% | 1.13 |

ge20-100 桶**结构性 reliance**: 80%+ 来自 (R1+R3 paying-base) × (R2 booster)。砍 R1+R3 bar 同时砍这条主路径。

## Variant test matrix

Format: variant — main lever → outcome (RTP / hit / ge1_5 / ge20-100 / HIER status)

| | Lever | RTP | hit | ge1_5 | ge5_10 | ge10_20 | ge20-100 | ge100+ | HIER |
|---|---|---|---|---|---|---|---|---|---|
| baseline | — | 95.45 | 20.07 | 19.59 | 14.02 | 23.41 | 16.54 | 21.88 | OK |
| A | mini→minor+major 全 push (user 原话) | 121.71 | 20.09 | 14.60 | 17.03 | 39.04 | 24.65 | 26.38 | FAIL |
| D | R1/R2/R3 bar -25/-15/-25% → blank | 84.56 | 16.00 | 15.14 | 13.49 | 23.08 | 12.19 | 20.67 | OK |
| H | A booster + R1+R3 bar ×0.7 + wild ×0.75 | 105.18 | 15.33 | 9.32 | 17.17 | 39.63 | 14.87 | 24.19 | FAIL |
| O | M (bar ×0.55 + high7 boost) + booster shift | 99.77 | 14.48 | 10.77 | 14.68 | 31.07 | 14.33 | 28.92 | FAIL |
| α | R1+R3 bar ×0.55 + high7 +220 + minor 290/major 220/mini 240 | 91.15 | 14.26 | 11.54 | 14.34 | 26.26 | 13.09 | 25.92 | FAIL |
| β | bar ×0.45 + high7 +380 + wild +40 + minor 320/major 230 | 108.31 | 16.41 | 13.25 | 15.38 | 28.79 | 18.09 | 32.82 | FAIL |
| γ | user exact + bar ×0.62 + wild ×0.7 | 101.78 | 14.34 | 8.21 | 17.20 | 39.75 | 12.85 | 23.75 | FAIL |
| δ | HIER-preserving (mini 320/minor 245/major 188) + bar ×0.60 + high7 +100 | 81.20 | 14.57 | 13.49 | 12.52 | 22.43 | 10.79 | 21.98 | OK |

## Observations (Designer should re-verify)

1. **ge20-100 stubborn**: even aggressive bar cut + high7 boost + booster shift (β) only pushes ge20-100 from 16.5 → 18.1 (+1.6pp). Far from +10pp target. Spill goes mostly to **ge100+ (+10pp)** and **ge10_20 (+5pp)**.

2. **HIER violation is necessary for "shift mass up booster ladder"**: User's lever direction inherently violates BOOSTER-HIER (mini > minor > major)。否则 mass 没法搬上去。

3. **Mode 7 R2 lock**: 任何 mode 1 R2 booster 改 → m7 R2 booster 跟改才保 MODE7-LOCK，否则 verify FAIL。

4. **Variant α is the "best compromise" main session found**:
   - RTP 91.15 (need to nudge +4pp to 95)
   - hit 14.26 ✓
   - ge1_5 11.54 (close to 9.6 target)
   - ge20-100 13.09（**没达目标，反而 -3.5pp**）
   - HIER 倒序违反

5. **Variant O 同时数字也接近**: RTP 99.77 / hit 14.48 / ge1_5 10.77 / 20-100 14.33 / 100+ 28.92 — RTP 多 5pp 需要 cut，bucket pattern 类似 α。

## Open levers Designer might explore further (NOT exhausted)

- 改 strip layout（同 family symbol 位置 swap），保 marginal 但移 (high7, X, high7) 邻接概率。**慎用** — strip md5 改让 m2/m5/m7 rawdata 失效，违反 "小改"。
- 重新 enumerate evaluation_order 路径 ── eval_order 决定 (wild, mini, 7bar) 是按 pure_wild_with_booster + line_3_group + center_booster_alone 还是别的。**不动 spec** 但要确认 lever 假设。
- 同 booster shift 方向 + 不同 R2 总量（如 booster_total 6% 而非 8.5%），把 R2 blank 加上来，更激进。
- 主动放弃 ge20-100 +10pp，改 escalate user 接受 redistribution 落 ge10-20 + ge100+（α/O 数字达成 hit + ge1_5 双 precise 红线）。
- 跟 user 商量 **paytable 临时澄清**（重申 paytable 锁 universal §1.1，不能改 pays。但可以 ask user 接受 reroll_blocks 调整 — 例如解除 (wild, grand, wild) reroll-block 让 1000× 也能走纯 wild path？× 不行，破 brand promise）。

## Scripts run for evidence

- 1次 baseline `analytic_profile` dump
- 12 个 variant 的 `analytic_profile` 对比（A/B/C/D/E/F/G/H/I/J/K/L/M/N/O/P/Q/R/S/T/U/α/β/γ/δ — 实际 24 个）

完整命令在 main session transcript（可重跑），不再 copy 进 file 避免污染 Designer。

## Files in this dir produced for Designer

- `00_SESSION_BRIEF.md` — task framing
- `user_brief.md` — user 原话 + §1.2 vocab
- `01b_baseline_analytic.txt` — 4 mode analytic dump + combo enumeration
- `feasibility_v0_notes.md` — 本文件（main session evidence）

Designer 输出去：
- `design_v0.md`
- `targets_v0/M37_mode1.target.json`
