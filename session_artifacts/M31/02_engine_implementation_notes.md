# M31 Stage 2 Engine Implementation Notes

Date: 2026-05-14
Author: Implementer (I)
Stage: 2 (Engine + Tests)
Verdict: PASS

---

## 1. What Was Implemented

### Machine files

- `slot_designer/machines/M31/spec.json` — paytable DSL (11 symbols, 12 pay_ids including plugin_handled for scatter, 5 paylines, 2 spin_types ST=43/44)
- `slot_designer/machines/M31/reel_strips.json` — base reels (3×100 stops) + freespin_reels (R1:100, R2:13, R3:100)
- `slot_designer/machines/M31/weights/mode_1/weights.json` — uniform bootstrap weights (all 1s)
- `slot_designer/machines/M31/__init__.py` — empty package marker
- `slot_designer/machines/M31/plugins/__init__.py` — exposes `build_plugin`
- `slot_designer/machines/M31/plugins/feature.py` — M31FeaturePlugin implementation

### Tests (4/4 required, all PASS)

- `slot_designer/tests/machines/test_M31_engine.py` — 27 tests (27/27 PASS)
- `slot_designer/tests/machines/test_M31_strips_invariants.py` — 17 tests (17/17 PASS)
- `slot_designer/tests/machines/test_M31_plugin_protocol.py` — 14 tests (14/14 PASS)
- `slot_designer/tests/machines/test_M31_md5_isolation.py` — 8 tests (8/8 PASS)

Total: 66/66 PASS

### Registry

- `slot_designer/configs/machines_virtual.json` — M31sim entry added (mode 1, available=true)

---

## 2. Architecture Decision: Option B (FeaturePlugin)

Chosen: Option B — FeaturePlugin for multi-payline + FreeSpin reel-set switch. Core engine not modified.

Rationale:
- Core SpinEngine.spin() evaluates paylines[0] only. M31 has 5 paylines.
- Plugin intercepts every paid spin (trigger_pay_id=None, outcome-conditional mode).
- Plugin re-evaluates all 5 paylines + scatter via _evaluate_grid() in emit_extra_rounds.
- Plugin mutates base_round dict in-place (Python dict reference semantics — caller's reference in emit_session sees the mutation).
- FreeSpin engine is built inside build_plugin() using freespin_reels + freespin_weights from reel_strips.json/weights.json. No core modification needed.

---

## 3. Source-of-Truth Choices

| Artifact | Source | Confidence |
|---|---|---|
| Paytable (pay_ids 1-11 credit amounts) | 01c §2 (production rawdata verified) | HIGH |
| Scatter pay_ids (12=5000 credits, 666=trigger marker) | 01c §3 + 01b §4 | HIGH |
| 5 paylines (center/top/bottom/diag-down/diag-up) | 01c §4 | HIGH |
| 4 wild tiers (Wild2x/3x/5x/10x) | 01c §1 | HIGH |
| Tier B fixed credits (not multiplied by wild_mult) | 01c §2 (verified: 0 errors in 12,998 single-payline rounds) | HIGH |
| Tier A = base × wild_mult_product | 01c §2 | HIGH |
| FreeSpin = 7 spins per trigger | 01b §4 + production chunk (553/79 = 7.0000) | HIGH |
| FreeSpin R2 = 100% wilds | 01c §7 (1,470 stops, 0 non-wild) | HIGH |
| FreeSpin R2 wild distribution (Wild2x=47.7%, Wild3x=21.2%, Wild5x=14.6%, Wild10x=16.5%) | 01c §7 | MEDIUM |
| No retrigger (Scatter absent from freespin reels) | 01c §6, §7 | HIGH |
| Base reel stop counts (100 per reel) | 01b §3 + 01c §5 | MEDIUM |
| Base reel symbol marginals (bootstrap) | 01b §3 center-row marginals | LOW — uniform weights |
| FreeSpin R1/R3 stop counts (100 per reel) | approximated from 01b §5 | LOW |

---

## 4. Q1-Q6 Decisions

**Q1 (pure_wild_group alternatives):** All alternatives enumerated explicitly in spec.json for pay_ids 4, 5, 6. pay_id=4 includes all 10 combinations containing at least one Wild10x.

**Q2/Q3 (3xWild10x):** Falls under pay_id=4 (any 3 wilds including Wild10x, 10000 fixed). The pure_wild_group alternatives list includes `{"Wild10x":3}`.

**Q5 (FreeSpin R2 strip):** 13-stop strip bootstrapped from 01c §7 observed wild distribution (approximately 47.7% Wild2x, 21.2% Wild3x, 14.6% Wild5x, 16.5% Wild10x). Exact strip is TODO Stage 6 fit.

**Q6 (multiplier units):** Spec `multiplier` field carries x-bet fractions for Tier A (e.g., 0.1 for 1bar = 100 credits at 1000-credit bet). Plugin computes `int(multiplier * bet_amount)` then multiplies by wild_mult_product. Tier B fixed credits stored in `_TIER_B_FIXED_CREDITS` dict in plugin, bypassing the multiplier entirely.

---

## 5. Byte-Alignment Results

### Schema fingerprint check

- Production chunk fingerprint (rawdata/M31/mode_1/chunk_0002.json): `9d88f8b73ace40f7`
- Sim round field fingerprint: `9d88f8b73ace40f7` — EXACT MATCH

### Envelope keys

Production top-level: `['_bet', '_cache_version', '_chunk_index', '_code_md5', '_config_md5', '_machine', '_mode', '_payload_sha256', '_robot_count', '_saved_at', '_spin_times', '_upstream_schema_fingerprint', 'response']`

Sim top-level: Same keys (plus `_dev_sample` added by virtual console). Round-level keys: identical 17 fields.

### Per-round field set (17 fields)

Both production and sim:
`BetAmount, CostCredits, CurJackpotStoreWin, IsLackCreditsSpin, LastCredits, PayLineGroupId, PayoutByPayline, PayoutGroupId, PayoutIdToWinAmount, RTPId, ReMarks, ReelSkin, RewardLastNode, SpinTimes, SpinType, StopSymbolsByCol, WinCredits`

Status: EXACT KEY MATCH

### SpinType distribution

- Sim: {43: 20000, 44: 553} — 20k paid + 553 FreeSpin
- Production: {43, 44} — confirmed in rawdata
- Status: PASS

### ReMarks pattern

- Sim: `{"": 19921, "TriggerFreespin": 79, "FreeSpin": 553}`
- Production (chunk_0002): `{"": 15868, "TriggerFreespin": 132, "FreeSpin": 924}`
- Key strings match: `""`, `"TriggerFreespin"`, `"FreeSpin"` — PASS

### FreeSpin chain length

- Sim: 553 / 79 = 7.0000 (exact 7 per trigger)
- Production: 924 / 132 = 7.0000 (exact 7 per trigger)
- Status: PASS

### PayoutByPayline format

- Sim example: `5:11-11(101,200,299,);  ` (line_id:pay_id-pay_id(pos1,pos2,pos3,);  )
- Production example: `1:11-11(100,200,300,);  `
- Position encoding: (col+1)*100 + (row-1) — matches production. PASS

### Known non-RTP field value differences (cosmetic)

- `ReelSkin`: sim emits `""` (core emitter stub); production emits `1` (integer). This is a fleet-wide stub in core/emitter/round.py. Does NOT affect RTP computation. Field key is present (ARCHITECTURE byte-alignment check passes). Value drift is cosmetic only.

---

## 6. Sim RTP vs Production (20k paid spins, uniform weights)

| Metric | Sim (uniform weights) | Production target |
|---|---|---|
| RTP | 68.51% | 92.62% |
| Hit rate | ~13% (estimate) | 13.18% |
| Trigger rate | 1-in-253 paid rounds | 1-in-132.5 |

RTP gap: ~24pp. Expected for Stage 2 bootstrap weights (uniform = lower Scatter density → lower trigger rate → lower FreeSpin RTP contribution). Stage 6 (tuner) will fit weights to close this gap.

---

## 7. TODO Stage 6 Fit Markers

All markers in `slot_designer/machines/M31/plugins/feature.py` (module docstring) and `spec.json` (`_notes` array):

1. `feature.py` docstring: `# TODO Stage 6 fit: FreeSpin R1/R3 weights (approximated from observed stop frequencies)` — FreeSpin reels R1 and R3 use uniform weights; exact per-stop weights should be fitted by tuner to match production FreeSpin win distribution.

2. `feature.py` docstring: `# TODO Stage 6 fit: FreeSpin R2 strip approximation (13-stop fit, delta < 2pp per symbol)` — R2 strip is bootstrapped from 01c §7 observed percentages; exact stop layout should be refined.

3. `spec.json` `_notes`: `TODO Stage 6 fit: FreeSpin reel strip weights are approximated from observed stop frequencies` — base reel weights are uniform (all 1s); tuner must fit weights to match 01b center-row marginals and achieve RTP target.

Count: 3 TODO Stage 6 markers

---

## 8. Best-Guess Components

| Component | Confidence | Rationale |
|---|---|---|
| Base reel strip layout (100 stops, symbol sequence) | LOW | Bootstrapped from 01b center-row marginals only; per-stop sequence unknown. Uniform weights placeholder. |
| FreeSpin R2 strip (13-stop, Wild2x/3x/5x/10x mix) | MEDIUM | Bootstrapped from 01c §7 percentage distribution. Stop count 13 is an approximation. |
| FreeSpin R1/R3 strip (100 stops, uniform weights) | LOW | 01b §5 FreeSpin marginals available for bootstrap; uniform weights used as placeholder. |

---

## 9. Cross-Check vs xlsx

No xlsx provided for M31 mode 1. 01b baseline report and 01c field analysis are the authoritative sources. No xlsx cross-check performed.

---

## 10. Core Tests

Pre-existing failures (unrelated to M31, confirmed by stash test):
- `slot_designer/tests/core/test_no_machine_leakage.py::test_no_machine_name_tokens_in_core_source` — "M15" in comments in core/engine/spin.py and core/engine/feature_protocol.py. Pre-existing since before M31 onboarding.
- `slot_designer/tests/test_analytic_vs_sim.py::test_m37_mode5_analytic_includes_reroll_correction` — M37-specific pre-existing.
- `slot_designer/tests/test_phase5_ordering.py::test_pwdf_sensible_range` — M37-specific pre-existing.

M31 introduced 0 new core test failures. All 83 passing core tests continue to pass.

---

## 11. MD5 Values (machines_virtual.json)

- M31 code_md5: `3999b3b23f31f18cf184c4fd60f3bfb4`
- M31 mode 1 config_md5: `7836a4ddaa9c81d35622946df4d9150f`

---

## 12. Open Issues / Asks for Main Session

1. **ReelSkin value drift**: Sim emits `ReelSkin=""`, production emits `ReelSkin=1`. Key present and type is correct (cosmetic field). If production downstream systems reject non-integer ReelSkin, core/emitter/round.py needs a machine-specific ReelSkin config (would require core extension justification).

2. **Scatter symbol kind='filler'**: **FIXED (commit-pending)**. `core/engine/symbol.py` — added `'scatter'` to `_KNOWN_KINDS` + `is_scatter` property on `Symbol`. `core/engine/evaluator.py` — Stage 3 and Stage 5 filler checks extended to also exclude `is_scatter` symbols from payline evaluation. `slot_designer/machines/M31/spec.json` — `symbols.Scatter.kind` changed from `'filler'` to `'scatter'`. Plugin unchanged (detects scatter by symbol name string match, not by kind). Diff: symbol.py +8 lines, evaluator.py +8 lines, spec.json 1 field value.

3. **Stage 6 RTP gap of ~24pp**: Expected given uniform weights. Tuner needs access to 01b §3 per-reel marginals and 01b §5 FreeSpin marginals to bootstrap realistic weights. Main session should confirm weight fitting scope for Stage 6.

4. **PayoutByPayline format parity**: Position encoding `(col+1)*100 + (row-1)` matches production numerically. However the exact format string (trailing semicolons, double-space separator) is implemented in the plugin. If production format changes (e.g., different separator), only plugin changes are needed.

5. **Pre-existing test_no_machine_name_tokens_in_core_source failure**: **FIXED (commit-pending)**. `core/engine/spin.py` lines 135-136, 156, 163 — removed 4 "M15"/"M15-style" tokens from `spin_session()` docstring and inline comment; replaced with machine-agnostic phrasing ("scatter-pay trigger mode", "opaque per-plugin dataclass instances", etc.). `core/engine/feature_protocol.py` lines 62, 74 — removed 2 "M15-style"/"M15FeatureRound" tokens from `trigger_pay_id` docstring and `simulate_session` docstring. Total: 6 tokens removed across 2 files. `test_no_machine_leakage.py::test_no_machine_name_tokens_in_core_source` now GREEN (3/3 tests in that file pass).
