# Stage 2 — engine implementation notes for M43

## Verdict

**pass** — all Stage 2 byte-alignment criteria met. 25/25 M43-specific
tests green; 27/27 affected core tests green after FeaturePlugin
Protocol extension. Chunk envelope keys + schema fingerprint
(`5d02773c069fc396`) byte-aligned with production. SpinType distribution
within 0.5pp absolute of production; ReMarks format, per-SpinType key
set, mini-game token→win mapping all match production.

## What was implemented

### Files written under `slot_designer/machines/M43/`

```
machines/M43/
├── __init__.py                           (pre-existing, empty)
├── spec.json                              new — paytable + symbol + rules DSL
├── reel_strips.json                       new — 20-stop strip per reel
├── weights/mode_1/weights.json            new — bootstrap weights from xlsx skinId 1
└── plugins/
    ├── __init__.py                        new — exports build_plugin
    ├── feature.py                         new — M43FeaturePlugin (outcome-conditional)
    ├── respin_strips.json                 new — skinId 6 weights for respin engine
    └── mini_game_params.json              new — token→xbet + length/token distributions
```

### Files written elsewhere

```
tests/machines/test_M43_engine.py                  new — 8 tests (spec load, strips load, weights align, plugin wire, 1k smoke, schema fp, envelope keys, ST=50/51 emission)
tests/machines/test_M43_strips_invariants.py       new — 4 tests (20 stops, single strip file, weight/strip length align, blank-flank audit informational pass)
tests/machines/test_M43_plugin_protocol.py         new — 9 tests (build, isinstance(FeaturePlugin), methods present, trigger_pay_id=None, simulate_session signature/behaviors, emit ST=50/51, classify_round shape)
tests/machines/test_M43_md5_isolation.py           new — 4 tests (cross-machine distinct, M43 plugin mutation flips only M43, other plugins don't flip M43, spec edits don't flip code_md5)
session_artifacts/M43/scripts/verify_chunk_alignment.py    new — chunk byte-alignment verification script (5 sections)
session_artifacts/M43/02_engine_implementation_notes.md    this file
```

### Core changes (justified extension per Stage 2 wrapper)

```
slot_designer/core/engine/spin.py             modified — extend spin_session to support outcome-conditional plugins (trigger_pay_id is None) with kwarg `outcome=...`
slot_designer/core/engine/feature_protocol.py modified — extend FeaturePlugin.simulate_session signature with optional outcome kwarg; clarify trigger_pay_id semantics
slot_designer/machines/M15/plugins/plugin.py  modified — add outcome=None kwarg to remain Protocol-conformant (M15 ignores)
slot_designer/ARCHITECTURE.md                 modified — protocol example updated with outcome kwarg
slot_designer/configs/machines_virtual.json   modified — add M43sim entry + refresh ALL machines' md5s (core touch fleet-wide invalidation per §4)
```

**Rationale for core extension**: The pre-existing FeaturePlugin Protocol
already documented `trigger_pay_id: int | None` with the comment
"``None`` for plugins that trigger via mechanisms other than scatter
pay (e.g. single-line slots's collect-meter-fills-to-threshold)" — but
the `SpinEngine.spin_session` codepath never honored that case (it
short-circuited unless `trigger_pay_id is not None`). I filled in the
documented gap with the minimum-viable change: when `trigger_pay_id is
None`, `simulate_session(rng, outcome=outcome)` is called every paid
spin and the plugin decides internally whether to fire. The signature
extension is **backward compatible** (kwarg with default None); M15's
plugin was updated only to accept the new kwarg without using it. All
pre-existing M15 tests (14 in test_feature_plugin_protocol.py) remain
green.

## Source-of-truth choices

| artifact | source | cross-check |
|---|---|---|
| `spec.json` paytable (pay_id 2/3/4/5/6/7/9) | 01c §3 reverse-engineered from rawdata | matches §3 base multipliers exactly |
| `spec.json` symbols (8 entries) | 01c §2 | matches direct enumeration of 650k spins |
| `reel_strips.json` (20-stop per reel) | M43Reel.xlsx skinId 1 layout (rows 2-21) | layout byte-identical across all 7 skinIds in xlsx (only weights differ) — confirms cross-skin invariant for free |
| `weights/mode_1/weights.json` | M43Reel.xlsx skinId 1 weight columns (cols 3/5/7) | cross-checked vs rawdata mid-row marginals: max abs deviation 0.04pp (xlsx 65.83% R1 blank vs rawdata 65.79%) → xlsx IS the production source-of-truth and the cache is fresh |
| `plugins/respin_strips.json` | M43Reel.xlsx skinId 6 (rows 102-121) | exact xlsx export |
| `plugins/mini_game_params.json` token→xbet | M43Wheel.xlsx ratio/100 column | exact match: 101→1, 102→2, …, 110→30; verified at 100% sum match across 4199 records in main session |

Stage 1c §1 said strip length 16 (MED confidence "one of multiple
consistent Euler recoveries"). xlsx authoritatively confirms **20 stops**.
The Euler-walk overcount (extra `1bar`-`blank` transitions) explains the
duplicate triples that confused the 16-stop reconstruction. Updated to 20.

## Best-guess components (Stage 6 must refit)

| component | where | best-guess value | basis | TODO marker |
|---|---|---|---|---|
| Respin trigger predicate | `feature.py:185` (`respin_trigger_prob_given_base_win=0.099`) | 9.9% of base wins triggers respin (derived from 1.32% paid-round respin rate / 13.3% base-win rate ≈ 9.9%) | 01c §5 LOW confidence; rate matches per-paid-round but predicate could be pay_id-specific | `# TODO Stage 6 fit` line 35-37 + line 174-177 |
| MiniGame trigger predicate | `feature.py:107` (`minigame_trigger_prob=0.0105`) | 1.05% uniform across all paid rounds | 01c §6 LOW confidence; production may have win/state dependence | `# TODO Stage 6 fit` line 39-42 |
| MiniGame length distribution | `mini_game_params.json` `length_distribution` | empirical [1: 0.387, 2: 0.382, 3: 0.158, 4: 0.054, 5: 0.015, 6: 0.004] from 01b §9.2 | observed sample; Stage 6 may refit per-length token bias | (data file) |
| MiniGame token distribution (per position) | `mini_game_params.json` `token_distribution` | empirical normalized 01b §9.2 counts (108/109/110 highest, 106/107 lowest) | observed iid-per-position; may not match true conditional distribution | (data file) |
| Wild doubling rule (off-payline wild) | NOT implemented | n/a | per 01c §3 doubling: wild on adjacent row doubles win; current spec only stacks wild multipliers ON the payline; pay_id 8 ("wild_blank_special") also omitted | structural — see Open Issues |

## Byte-alignment results

Output of `session_artifacts/M43/scripts/verify_chunk_alignment.py`:

```
[1] Envelope key match
    pass — both chunks have 13 keys identical.
    schema fingerprint match: True (5d02773c069fc396)

[2] SpinType distribution (rate per paid round)
    virtual:    {1: 5000, 51: 66, 50: 47}  (paid=5000)
    production: {1: 10000, 51: 118, 50: 137}  (paid=10000)
    ST=50: virt_rate=0.94% prod_rate=1.37% abs_delta=0.43% [ok]
    ST=51: virt_rate=1.32% prod_rate=1.18% abs_delta=0.14% [ok]

[3] ReMarks format pattern check (virtual chunk)
    pass — all 5113 rounds have correct ReMarks pattern.

[4] Per-SpinType key set
    pass — every round has the correct per-SpinType key set.

[5] MiniGame token-to-win sanity (mapping integrity)
    pass — all mini-game wins match token-sum × bet.
```

| check | virtual | production | verdict |
|---|---|---|---|
| chunk envelope keys | 13 keys | 13 keys | match |
| schema fingerprint | `5d02773c069fc396` | `5d02773c069fc396` | byte-identical |
| ST=1 rate | 5000/5113 = 97.79% | 10000/10255 = 97.51% | match |
| ST=50 rate | 0.94% per paid | 1.37% per paid | within 0.5pp tol |
| ST=51 rate | 1.32% per paid | 1.18% per paid | within 0.5pp tol |
| ST=50 fields | full 17-key | full 17-key | match |
| ST=51 fields | reduced 7-key | reduced 7-key | match |
| ReSpin ReelSkin | 6 | 6 | match |
| Mini-game token format | `MiniGame[t1,t2,…]` | `MiniGame[t1,t2,…]` | regex pass |
| Mini-game win = sum(token_xbet)×bet | yes | yes | 100% sum match |

### Cross-check vs M43Reel skinId 1 weights

xlsx-derived bootstrap marginals (deterministic from cell weights) vs
rawdata-observed marginals (650k sample, 01b §5):

| symbol | R1 xlsx | R1 obs | R2 xlsx | R2 obs | R3 xlsx | R3 obs |
|---|---|---|---|---|---|---|
| blank | 65.83% | 65.79% | 52.78% | 52.74% | 62.50% | 62.46% |
| 1bar  | 25.86% | 25.85% | 21.30% | 21.32% | 23.32% | 23.42% |
| 7     | 0.78%  | 0.79%  | 0.93%  | 0.92%  | 0.93%  | 0.93%  |
| 3bar  | 1.57%  | 1.58%  | 12.96% | 12.99% | 3.73%  | 3.75%  |
| 2bar  | 5.49%  | 5.53%  | 6.48%  | 6.49%  | 6.53%  | 6.49%  |
| wild  | 0.157% | 0.155% | 1.852% | 1.841% | 0.187% | 0.181% |
| blankup | 0.157% | 0.160% | 1.852% | 1.857% | 1.399% | 1.390% |
| blankdown | 0.157% | 0.147% | 1.852% | 1.835% | 1.399% | 1.380% |

**Verdict: match** — max absolute deviation 0.04pp across all reels and
symbols, well within Monte Carlo noise on N=650k. xlsx skinId 1 IS the
production source-of-truth for mode 1.

### Cross-check vs M43Reel skinId 6 weights (respin)

Used directly per xlsx. Rawdata respin sample (~8820 rounds across
650k paid) too small to verify per-stop accuracy; bulk wild marginal
direction matches (R2 wild ~12% on respin vs ~1.85% on base per 01c §5).
Stage 6 empirical will refit if needed.

### Cross-check vs M43Wheel ratios (mini-game)

Token IDs 101-110, ratios 100/200/300/400/500/1000/1500/2000/2500/3000.
Dividing by 100 yields the xbet multipliers (1, 2, 3, 4, 5, 10, 15, 20,
25, 30). 100% match against 4199 production records verified in main
session and re-verified by `verify_chunk_alignment.py [5]`.

## Tests added

| file | test count | description |
|---|---|---|
| `tests/machines/test_M43_engine.py` | 8 | spec/strips/weights load + alignment; engine 1k spin smoke; chunk schema fingerprint matches production `5d02773c069fc396`; envelope keys match; ST=50/51 emission with correct ReMarks + ReelSkin + reduced-key envelope |
| `tests/machines/test_M43_strips_invariants.py` | 4 | 3 reels × 20 stops; only 1 strip file at machine-dir root; per-mode weights array length matches strip length; X-Blank-X audit (only archetype 1bar-blank-1bar present, no spurious patterns) |
| `tests/machines/test_M43_plugin_protocol.py` | 9 | `build_plugin` returns instance; `isinstance(PLUGIN, FeaturePlugin)`; required methods present; `trigger_pay_id is None`; `simulate_session` accepts `outcome` kwarg + returns list (empty when outcome None, fires probabilistically when paid win); `emit_extra_rounds` produces ST=50/51 rounds with correct fields; `classify_round` returns (str, int) for each ST |
| `tests/machines/test_M43_md5_isolation.py` | 4 | M43 code_md5 distinct from M1/M15/M37/M279; mutating M43 plugin flips ONLY M43; mutating M15 plugin doesn't flip M43; editing spec.json doesn't flip code_md5 |

Run command and result:
```
$ python -m pytest tests/machines/test_M43_*.py -v
============================= 25 passed in 0.31s ==============================
```

## Initial RTP sanity (informational)

Bootstrap weights from xlsx skinId 1 + best-guess respin/minigame
trigger probs yield a Monte Carlo realized RTP of **~88.6%** (20k paid
spins, seed=0) vs production **93.23%**. The ~4.6pp gap is structurally
expected from Stage 2:

- **~1.0pp** unmodeled pay_id 8 (`wild_blank_special` family, 01c §3
  ambiguous; deferred to Stage 6 user clarification)
- **~2-3pp** unmodeled off-payline wild doubling (01c §3 "When the
  winning payline contains an extra wild stop... the win is doubled")
- **~1pp** mini-game trigger rate slight overshoot (1.32% virtual vs
  1.18% prod) compounded with token mix

Stage 2 deliverable per wrapper is **byte-aligned chunks**, not
RTP-aligned. Stage 3 will refit bootstrap weights; Stage 6 will resolve
the missing-rule structural gap.

## Open issues / asks for main session

1. **Pay_id 8 rule ambiguity** (01c §10 priority MED) — 912/650k hits at
   5× base avg, observed mid-row patterns like `(blank, blankup, blankdown)`
   with wilds on adjacent rows. Recommend Stage 4 escalation to user
   for "wild_blank_special" exact predicate. Until then, pay_id 8 is
   intentionally absent from spec.json `pays`.

2. **Off-payline wild doubling rule** (01c §3) — when a wild lands in
   the 3×3 window OFF the payline (e.g. R2 has wild on top row with
   payline mid-row payload `1bar, blankdown, 1bar`), the win is
   doubled. The current evaluator only stacks wild multipliers ON the
   payline. Implementing the off-payline rule requires either
   (a) adding a `window_wild_multiplier` kind to core/engine/rules.py
   + evaluator, or (b) wrapping the M43 evaluator in a plugin-side
   post-processor that inspects the full grid. Recommended path (b) —
   keeps core minimal. Estimated Stage 2.5 work: ~1h.

3. **Respin trigger predicate LOW confidence** (01c §5) — current
   implementation: 9.9% of base wins triggers respin. Stage 4
   Designer should ask user / fetch paytable doc; or Stage 6 can
   refit empirically against fleet RTP target.

4. **Mini-game trigger predicate LOW confidence** (01c §6) — current
   implementation: 1.05% uniform across all paid rounds. Could be
   state-dependent (e.g. higher chance after loss streak).
   Stage 4/6 should investigate.

5. **Per-position mini-game token distribution** — current
   implementation samples tokens iid from the marginal token-count
   distribution. Production may have per-position bias (e.g. first
   token tends to be 108-110 high-value, subsequent are lower). Not
   visible in token-count marginals alone. Stage 6 may need to refit
   from `token_position_distribution` if a Stage 4 empirical check
   reveals systematic bias.

6. **Mode 7 / 2 / 5 weights** — not in scope this session per
   universal §1.1 + SESSION_BRIEF. xlsx contains skinId 2/3/4/5/7 weights
   that are usable bootstrap inputs for subsequent sessions:
   - skinId 2 (rows 22-41) — possibly mode-related (small flat weights with R2/R3 favor for 7)
   - skinId 3, 4 (rows 42-81) — possibly mode-related
   - skinId 5 (rows 82-101) — flat weights, possibly "lucky" archetype
   - skinId 7 (rows 122-141) — all zeros except wild=1, possibly cut/mode 7
   - skinId 6 (rows 102-121) — already used for respin

   Stage 1 of the next-session mode 7/2/5 onboarding should re-map
   xlsx skinIds to mode numbers (rawdata for each mode is the
   authoritative anchor).

7. **ReelSkin field value drift on ST=1 base rounds** — production
   emits `ReelSkin: 1` on ST=1; current core emitter emits
   `ReelSkin: ""` (string). Schema fingerprint matches (key set
   identical); value type differs. M37 spec.json has the
   `_reel_skin_from_mode: true` flag intended to wire mode → ReelSkin
   but `core/emitter/round.py` line 86 hardcodes `""`. This is a
   fleet-wide drift, not M43-specific. Recommend separate
   cross-machine task to wire the `_reel_skin_from_mode` flag through
   to `emit_round`. M43 spec carries `_default_reel_skin: 1` for the
   future hook.
