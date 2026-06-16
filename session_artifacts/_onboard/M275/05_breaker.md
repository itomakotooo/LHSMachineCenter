# M275 mode_1 — W5 adversarial verify (onboard-breaker)

> Everything below was RECOMPUTED from `rawdata/M275/mode_1` (2 chunks, 16 robots,
> 89,090 rounds; deep-parse: `json.loads(response)` → per-robot `roundResult` /
> double-loads `analysisResult`). The CLAIM = a fresh report generated once via
> `report_engine.generate_report_from_chunks("M275", 1, bet=1000)` →
> `cache/_m275_breaker/player_impact_summary.json`. No exit-code trust anywhere;
> every number below was read from the user-visible summary/render and compared
> against my own raw-round recomputation.

## VERDICT

**One BREAKING counterexample (display-level, small fix) + everything else HELD
with exact traces.**

---

## COUNTEREXAMPLE — machine_mechanics.free_spin renders "0.00pp" for a mechanic that carries ~half of all payback

**Machine + trace:** M275 mode 1, fresh report above.

```
player_impact.machine_mechanics.free_spin = {
  applicable: true, chain_spins: 9090, chain_rate: 0.10203, retriggers: 0,
  max_chain_length: 10, total_win: 0.0, rtp_contribution_pp: 0.0,
  _detection_source: "manifest_spin_types" }
```

Raw truth: st126 carries **35,531,500** win = 44.414 pp (paid-bet) / 39.883 pp
(global-bet) — recomputed from 9,090 raw rounds. The console mechanics panel
(`app.js` `renderMachineMechanics`, line ~5277) renders the block whenever
`fs.applicable` and prints `fs.rtp_contribution_pp.toFixed(2)+"pp"` → the user
sees **"Free Spin … RTP 贡献 0.00pp"** on the same page where `freespin_dynamics`
shows 39.88 pp and the per-path table shows 40.86+3.56 pp.

**Why:** `machine_mechanics.py` (~line 415–450): `fs_win` comes from the
CurFreeSpin-style accumulator which is 0 on ReMarks-tracked machines; the code
falls back to `bonus_chain_dynamics` for `chain_spins`/`max_chain_length` but
**not for `total_win`** → `rtp_contribution_pp = 0.0`. This section is **newly
ACTIVATED by this very diff** (the role-aware `freespin_applicable` derivation in
`machine_spec.py`): before the change `applicable` was false and the section was
hidden. The change fixes the W2-note-3 FLAG self-contradiction but introduces a
VALUE self-contradiction — `test_machine_mechanics_free_spin_applicable`
(test docstring: "the report no longer self-contradicts") only asserts
`applicable is True`, so the suite cannot catch it.

**Boundary of the break:** chain_rate (10.20%), chain_spins (9,090), max_chain
(10), retriggers (0) in the same block are all CORRECT vs raw. Parsing, economy,
parity, the new plugin, the extractor, and the session fold are all unaffected.
Fix options (framework queue — `machine_mechanics.py` is shared; do NOT fork):
fall back `fs_win` to the freespin-role ST's `spin_type_breakdown.total_win` the
way `chain_spins` already falls back, or suppress the pp stat when it is
0-with-nonzero-chain-spins.

---

## HELD — per-case traces (all recomputed independently)

### 1. Hard sessions

| case | raw trace | report placement |
|---|---|---|
| **max session 338×** | robot 3, trigger SpinTimes 1658 (pid 666 win 0, cc=658), GTT=0 ×10, skins 11/11/11/21/21/21/21/31/31/31, ER 100→1700 monotone; FS3 = 325,000 (pids 1:250,000 = 5×bet×ER5×wild10x, 6:75,000) + FS4 6,000 + FS5 7,000 = **338,000** | `volatility.max_observed_return_x=338.0` ✓; server TotalWin tier-300 = 1/338,000 ✓; SummaryWin NewFreespin tier-300 ✓; scatter path band `ge200_lt500` holds the 325× round (count 2) ✓ |
| **top-5 scatter** | 338 / 277 / 235 / 224.5 / 213.5 × (robots 3,8,13,13,10) — all GTT=0 | all in the scatter rows of the per-path/band hists; session-level tiers parser_blind by declaration, server SummaryWin confirms ✓ |
| **top-5 collect_peak** | 172.5 / 128 / 115.5 / 107 / 95.5 × (trigger SpinTimes all ∈ {3000,4000} = deterministic peaks) | max 172.5× == W1 §7.2 ✓; ccpeak band hist exact ✓ |
| **longest ER ladder** | ER@FS10 = 2800 (robot 11, scatter, trigger SpinTimes 4747) — FS10 itself **won 0** (the rise-then-cliff in one trace) | ER correctly NOT in the report (parser_blind F4, flagged); the round sits in scatter `eq0` ✓ |
| **double-trigger block** | robot 3, SpinTimes 4000: trigger round has BOTH cc=1000 AND pid 666 (win 0); **GTT=2 block first** (2,000+30,000=32,000), then GTT=0 block (5,500+7,500+16,000+19,500=48,500) | extractor counts the one contiguous block once per path → total_sessions **909** = 829+80 ✓ with the additive_sessions note in `source` ✓; `session_cadence.openers=908` (contiguous blocks) with the merge note ✓ |

### 2. Per-path split vs raw — EXACT to full float precision

My GTT recomputation == report `freespin_dynamics.trigger_paths`:

| | scatter | collect_peak |
|---|---|---|
| sessions | 829 ✓ | 80 ✓ |
| rounds | 8,290 ✓ | 800 ✓ |
| win | 32,685,500 (share 0.919902058736614 ✓) | 2,846,000 (0.08009794126338601 ✓) |
| pp (paid-bet) | 40.856874999999995 ✓ | 3.5575 ✓ |
| band hist | 21/526/546/502/353/105/24/2 + eq0 6211 ✓ all 9 bands exact | 1/50/46/47/47/6 + eq0 603 ✓ all 7 exact |

Cross-foots: rates×N=sessions, one_per_n=inverse, shares sum to 1, hist sums =
round_count, per-band path-sum == `freespin_multiplier_distribution` band
counts, pp-sum 44.414375 == `share_of_all_win × summary.rtp` (0.4977167×89.23625)
== Σ exactly; `freespin_total_win_share_covered = 1.0` ✓ (32,685,500+2,846,000 =
35,531,500 = st126 total).

Server's OWN taxonomy reconciliation (recomputed by aggregating all 16 robots'
`analysisResult`):
- **TotalWin** (session-centric paid-spin view): 80,000 / 71,389,000, tiers
  −1:68,107 0:2,346 1:6,577 5:1,453 10:676 20:533 50:226 100:81 300:1 — equals
  my paid-round session fold and the report's `volatility.return_bucket_rate`
  EXACTLY (tier edges differ from bands only at [200,300): 81 = 75 + 6) ✓.
- **FeatureWin** NewFreespin per-round tiers == st126 band hist (tier 100 = 24+1,
  tier 300 = the 325× round) ✓; NormalCollectionSpin == st140 bands ✓;
  BuffCollectionMap 80/0 ✓.
- **SummaryWin** NewFreespin = **908** sessions: my merged-block tier recompute
  {−1:43, 0:1, 1:47, 5:89, 10:160, 20:326, 50:177, 100:64, 300:1} is
  **byte-identical to the server**; my 909 GTT view differs exactly by the
  documented merge (two tier-20 sessions 32×/48.5× → one tier-50 80.5×:
  20: 328→326, 50: 176→177). Reconciled, not silently different ✓.
- UFB `[via]` rows (8,280/32,637,000 vs 810/2,894,500) = the documented
  near-exact anchor-walk split: delta vs GTT truth is exactly the 10-round/48,500
  double-trigger scatter half binned to the BCM bucket — same merge direction the
  server applies; manifest caveat names it ✓.

### 3. Session-dim KPIs (the b8826c5 fix under adversarial load) — EXACT

Raw per-paid-round fold (paid win + triggered block win):
avg_return_x **0.8923625** ✓; win sessions **11,893** (0.1486625) ✓; ≥10×
**1,517** (0.0189625) ✓; ≥20× 841 / ≥50× 308 / ≥100× 82 ✓; max **338.0** ✓;
profit_spin_rate 0.077025 ✓; breakeven 0.1193375 ✓; avg_win_when_hit_x
6.002606575296393 ✓; every `return_bucket_rate` band exact ✓ (std: report =
sample-stdev ddof=1; my pstdev² ×n/(n−1) reproduces 6.433919906… — convention,
not a mismatch). **Conservation: Σ session wins = 71,389,000 == total win EXACT**;
`session_conservation_level: "ok"`, notes show ratio 1.000000 ✓.

### 4. Economy / parity gates

- `sum(payout rtp_pp) = 89.23625 == summary.rtp.point_pct` EXACT ✓ (12 rows).
- `_unattributed_*` rows: **none** ✓; `layer2_no_fallback_buckets_ok: true` ✓.
- pid 666: 829 hits, total_win 0.0, `notes.is_trigger_marker: true`,
  combo bonus|bonus|bonus ✓ (raw: 829 occurrences, Σ win 0).
- `sum(payids)==WinCredits`: **89,090/89,090**, 0 mismatches ✓ (raw recount).
- per-ST payid totals: ST140_paid 12 rows / 13,816 hits / 35,857,500;
  ST126_free 11 rows / 2,951 hits / 35,531,500 — == W1 §8.1 sums ✓.
- No preview/offer pid exists → nothing to zero ✓.

### 5. Parsing correctness / schema honesty

- `parser_blind` list present (F3a/F4/F5 + per-path session-tier/ER/un-merge) and
  **no fabricated ER/FS-arc number exists in `freespin_dynamics`** ✓.
- Known pre-existing flat-100 ER surfaces remain elsewhere in the summary
  (`bonus_chain_dynamics.extra_ratio_histogram` = [{100: 9090}],
  `chain_max_ratio_quantiles` all 100, `by_feature` 841/67 heuristic labels,
  and `chain_ratio_sequences` = flat-100 sequences). All but
  `chain_ratio_sequences` are explicitly named in the manifest caveats; the
  bonus-chain console panel renders them ("100x · 100.0%") — factually wrong on
  this field-borne-ER machine but **pre-existing fleet display, not introduced
  by this diff**, and the new freespin panel carries the explicit MUST-NOT-cite
  warning. → recommend adding `chain_ratio_sequences` to the caveat list.
- Provenance nuance: a DIRECT `generate_report_from_chunks` call stamps
  `config_md5` from the roster (2c98ce05…) while the chunks are the historical
  bucket (8c89bc95…). Known engine/caller contract — the served console path
  re-stamps (fd6b507/597e8bf); this dir is single-bucket so no number shifts.

### 6. Reuse integrity

- `compute_base_analyzer_version()` **== c5d2199142c3** with the full working
  tree applied ✓ (the new plugin + manifest + machine_spec wiring do not flip it).
- Working-tree diff inside `fresh_slotlab/`: ONLY `machine_spec.py`
  (base-EXCLUDED) modified + NEW `features/freespin_dynamics.py`. Zero edits to
  core/, other features/*, round_win, trigger_sessions, st_extract ✓.
- 4/4 `_fwpass_gate` checks: **sha256 byte-identical** (M15|1 02dba26a…,
  M43|1 1f8980f7…, M43|7 adf66e7f…, M279|1 d25d4449…), and the goldens were
  written 2026-06-11 14:59–15:01 — BEFORE b8826c5 (15:46), 95ba119 (06-12
  12:27) and all working-tree edits → the gates genuinely prove the committed
  framework + M275 onboarding leave the three onboarded machines' reports
  untouched ✓.
- Effective versions: M275 mode-1 = c3b00f4af0c3 (matches the report stamp;
  my first recompute differed only because I omitted `mode=1`), base ≠ effective
  per machine (M15 3ea81112…, M43 368012f7…, M279 a373cfc3…) ✓.
- impl_B FIX-FIRST bugs verified FIXED in committed code: parser snapshots
  `_obs_errors`/`_begin_robot_error` BEFORE finalize (parser.py ~2488–2490),
  extractor resets both in finalize (trigger_path.py 314–315), float
  discriminator normalized via `raw_val == int(raw_val)` (trigger_path.py
  408–409).

### 7. Over-claim hunt (renderer semantics)

- All 40 i18n keys referenced by `_stDimFreespin` exist in BOTH locales ✓.
- Real render (the actual function source evaluated against the actual summary,
  PURE.fmt zh): 11,026 chars; asserts pass for 908 / 88.1 / 10.01 / 25.0% /
  13.9% / 1.81× / 829 / 80 / 1000.0 / 40.86pp / 3.56pp / 909 / 91.2% / 39.88pp /
  49.8%; **no `undefined` / `NaN` / `[object`**; ST140 renders "" ✓.
- unknown/multi alarm absence is DATA (GTT vocabulary {0,2} fully mapped; raw
  recount has zero other values), not code dropping them:
  `test_unmapped_value_surfaces_as_unknown_not_merged` (D2) proves unknown:*
  WOULD surface, suite **96 passed, 1 skipped** (the documented value-agnostic
  F5b fallback skip).
- **Minor finding (non-breaking):** the panel shows two "RTP contribution"
  figures with different denominators — `rtp_concentration
  .freespin_rtp_contribution_pp` = 39.88 (global-bet, mirrors
  spin_type_breakdown fleet semantics) vs per-path sum 44.41 (paid-bet, the
  parity denominator). Each is individually correct; the explanation lives only
  in the plugin docstring. Recommend surfacing the denominator note in the
  emitted JSON/panel. (With the counterexample above the console currently
  shows THREE freespin pp figures: 0.00 / 39.88 / 44.41.)

### 8. Edge cases

- Robot boundaries: 16/16 robots start ST140/SpinTimes=1/cc=1; ALL 16 end with a
  COMPLETE trailing freespin block ("Freespin 10" last) — the deterministic 5th
  cc-peak at SpinTimes 5000 ✓ (hence exit_transitions 9,074 = 9,090−16, and
  continuation_prob 8,182/9,074 = 0.9017 with the honest "arithmetic of the
  block, not a win-gated chain" note ✓).
- cc wrap: 64 in-sequence (1000→1) transitions, 0 anomalies; 80 peaks total ✓.
- Zero-win freespin sessions: 39 scatter + 4 ccpeak = **43** == server SummaryWin
  tier −1 = 43 ✓ (session-level placement is parser_blind by declaration; the
  round-level eq0 6,814 = 6,211+603 is in the report ✓).
- W1-artifact nit (not a report claim): W1 §7.2 ccpeak session median "30.0×"
  recomputes as 30.25× over all 80 (mean of 40th/41st), and zero-win 4/80=5.0%
  vs the quoted 4/79=5.1% — both depend on both-pair inclusion; nothing in the
  report emits these.

---

## Gate summary

| gate | result |
|---|---|
| schema (superset, honest parser_blind) | PASS |
| sum(payid)==summary | PASS (89.23625 exact) |
| our==server | PASS (71,389,000 == server aggregate; all 3 views reconciled) |
| fallback/_unattributed == 0 | PASS |
| previews → 0 | PASS (pid 666 = 0-win marker; nothing else) |
| base_hash == c5d2199142c3 | PASS |
| shared plugins untouched | PASS (diff-verified) |
| fwpass ×4 byte-identical (pre-change goldens) | PASS |
| render (real data, both-locale i18n, alarms data-driven) | PASS for `_stDimFreespin`; **FAIL for the newly-activated mechanics Free Spin card (0.00pp)** — the counterexample above |
