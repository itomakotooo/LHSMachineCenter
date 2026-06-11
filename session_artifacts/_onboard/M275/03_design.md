# M275 / mode 1 — Wave 3 QUANT DESIGN (player-experience metric design + manifest)

DATA-FIRST. Every metric below is grounded in a distribution W1 actually measured
(`01_understanding.md`, cited inline as W1 §n). Money-agnostic throughout — multipliers
(win/bet), hit-rates, probabilities, shares; NEVER a coin total. Honors the W2 verdicts
(`02_reuse.md`): st140 STRICT-REUSE; st126 NEW-EVENT mechanic (ONE new plugin) +
PER_SPINTYPE strict-reuse; economy fully self-settling (NO attribution rule); and the
W2 **ABORT** on the shared session-KPI fold (framework-team fix pending) — **nothing in
this design patches shared code**; every metric that depends on that fix is tagged.

**Deliverable = the report-generating STRUCTURE** (manifest + one new role-keyed plugin
+ wiring + the trigger-path declaration). A report is the acceptance test, not the
product.

Framework reads that ground the wiring (verified in code, not assumed):
- `machine_spec.py`: `KNOWN_ROLES = {paid_spin, player_choice, settlement, state, respin}`
  — an **open set**, base-EXCLUDED file. `ROLE_ANALYSES`/`PLAY_ANALYSES` are the two
  hooks; `derive_analyses()` = CROSS_CUTTING + PER_SPINTYPE + role-keyed + play-keyed.
  `derive_mechanism_flags()` keys `freespin_applicable` on play=="freespin" EXACT
  (case-insensitive) — misses "NewFreespin" (W2 note 3).
- `core/parser.py` (read, lines 548–617 + 2390–2519): the per-chunk record accumulates
  server `TotalWin` (totals) + `FeatureWin` (per-feature per-pid tally →
  `upstream_feature_tally`) but **NOT `SummaryWin`** (mentioned only in a comment) —
  the server's session-tier taxonomy is parser_blind today. The chain accumulators
  `chain_chunk_summaries` / `chain_bucket_{spins,bet,win}` are keyed by
  `(first_st, entry_cc_reset, sp_type)` — `entry_cc_reset` IS the trigger-path
  discriminator the `[via BCM cycle]` split uses, available per-chunk TODAY.
  `chains_by_feature.extra_ratio_counts` exists but is ReMarks-regex-sourced
  (`parse_freespin_remarks`) — DEFAULT-FILLED flat-100 on M275's field-borne ER
  (W2 cross-cutting note 2). **Never cite it as ER coverage.**
- `features/respin_dynamics.py`: resolves its ST via `role=="respin"` from the manifest;
  with no respin-role ST it writes `{applicable: False}` — so NOT attaching it to M275
  is structural, not a fork.
- `features/wheel_dynamics.py` / `minigame_dynamics.py`: the play-keyed precedent + the
  honest `parser_blind` contract the new plugin must mirror.

### Tag legend (every metric carries exactly one)
| tag | meaning |
|---|---|
| **NOW** | deliverable on the frozen framework today (accumulator-derivable; W2 ran it or the accumulator is proven present) |
| **parser_blind** | per-round fields the L1 parser does not accumulate (ExtraRatio field, ReelSkin per round, GameplayTriggerType, FS-index, SummaryWin tiers, joint grid counts) — designed here as the requirement spec for the per-ST extraction layer (DIRECTION.md §3); NEVER fabricated |
| **blocked_on_session_fix** | correct only after the framework team fixes the `_close_session` fold (the W2 ABORT: scatter-session freespin wins dropped from the 付费回合 dimension); acceptance values recorded below |

---

## 0. The two SpinTypes at a glance (W1 §1/§2)

| ST | feature (play) | role (decided §3) | share | the felt event | W2 verdict |
|----|----------------|------|-------|----------------|------------|
| **140** | `NormalCollectionSpin` | `paid_spin` | 89.80% | the paid grind: a 13.9%-hit base spin, a scatter to chase (and near-miss), and a pity counter ticking toward a guaranteed bonus | STRICT-REUSE: 4 PER_SPINTYPE + `collect_mechanic` |
| **126** | `NewFreespin` | **`freespin` (NEW role token)** | 10.20% | a granted 10-spin free session whose multiplier ONLY climbs (1×→ up to 28×) while the reels go progressively colder | NEW-EVENT mechanic (ONE new plugin) + PER_SPINTYPE strict-reuse |

Economy (W1 §4): `WinCredits` is the REAL win on BOTH STs; every round self-settles
(`sum(payids)==WinCredits` 89,090/89,090); pid **666 is a zero-win scatter marker** (829
rounds, total win 0); the collect pot (`AccCredits`) is **never paid as credits** —
display/anticipation only. Paid bet = ST140 `CostCredits` only (st126 cost 0).
RTP 89.24% = 44.82pp base + 44.41pp freespin (this md5 bucket).

**Headline single numbers (the M15 bar — each one a feeling):**
- **1.14% of paid spins** open a 10-spin freespin block that carries **49.8% of ALL
  payback** (W1 §4, W2 `share_of_all_win=0.4977`).
- You see a **2-scatter near-miss 11× more often than the trigger** (11.4% vs 1.04%,
  W1 §8.2).
- If luck never comes, **every 1000th paid spin opens the bonus anyway** — the pity
  path supplies **8.8% of all bonus sessions** but only **8.0% of the bonus payback**
  (80/909 sessions; 3.56pp of 44.41pp, W1 §7.2).
- Inside the bonus, the multiplier **never falls** (8,181/8,181 steps positive, W1 §7.3)
  — but the last 3 spins, holding the **highest multipliers (mean 12.8–16.4×)**, hit only
  **4.7% of the time**: spins 1–7 carry **91.7% of the session win** (W1 §8.5). The climb
  is the hope; the cash lives early.

---

## 1. ST140 — NormalCollectionSpin (REUSE; do NOT redesign)

### 1.1 Base-grind outcome curve — the per-spin gamble — **NOW / reuse**
Felt: an 86.1%-lose grind with a mid tail and a rare 125× pop.
Signal: `spin_type_breakdown[ST140]` (spins 80,000, hit_rate 0.13859, W2-run exact) +
`spin_type_rtp_buckets[ST140]` / `spin_type_outcomes["ST140_paid"]` win/bet bands.
The machine's OWN taxonomy agrees: server FeatureWin NormalCollectionSpin tiers
−1:68,913 / 0:2,350 / 1:6,580 / 5:1,369 / 10:517 / 20:206 / 50:48 / 100:17 (W1 §5.2).

### 1.2 Payid mix incl. the all-wild specials — **NOW / reuse**
Felt: which line events make up the base game, incl. the rare "screen of wilds" fixed
pops. Signal: `payouts_by_spin_type["ST140_paid"]` — all 12 pids W2-run exact to W1 §8.1
(e.g. pid 4 at 4.33%/round, pid 27502 = the 100× all-wild line at 0.021%, pid 27503 25×
at 0.017%, pid 27504 10× at 0.152%). Per-pid hit-rate + RTP-pp columns are the
money-agnostic form.

### 1.3 Scatter anticipation + near-miss — **NOW (rate) / parser_blind (ladder)**
- Trigger rate — **NOW / reuse**: pid 666 row in `payouts_by_spin_type` (829 hits, win 0,
  `is_trigger_marker:true`, symbol_combo `bonus|bonus|bonus`) → **1.036% per paid spin
  (1 in 96.5)**. W2-run exact.
- Near-miss ladder — **parser_blind / NEW metric spec**: bonus-symbol count per grid
  0/1/2/3 = 47.4/40.2/**11.4 (2-of-3 near-miss)**/1.04% (W1 §8.2); single number:
  **11.0 near-misses per trigger**. Needs a per-round cross-reel bonus-count tally
  (joint, not the per-reel marginals `reel_marginal_by_spin_type` keeps) → per-ST
  extraction layer. Designed, not fabricated.

### 1.4 Collect metronome — the pity timer — **NOW / reuse + manifest note**
Felt: a counter that ticks +1 on EVERY paid spin and at exactly 1000 opens the bonus —
deterministic anticipation, never a credit payout (`AccCredits` = 100×CC is a display
pot; the 80 peak rounds pay only ordinary line wins, W1 §6).
Signal: `collect_mechanic` (CROSS_CUTTING, no hook): `detected_cycle_length=1000`,
`bonus_feature="NewFreespin"` (source=config, `bcm_pairings.json` correct),
`estimated_correction_pp=0.0` — all W2-run verified. Felt numbers: cadence 1/1000
deterministic; pity share of sessions 8.8%; mean distance-to-guaranteed-bonus = 500
paid spins (CC uniform 1..1000, W1 §6).
Known fleet-wide cosmetics (W2): `completed_cycles_total` counts resets (64 vs 80
true cycles), always-on `clamp_warning`, and the M275-specific sharpening —
`avg_bonus_payout` divides the WHOLE NewFreespin win (92% scatter-path) by cycle count,
~15× the true per-BCM-cycle payout. Harmless while correction_pp=0.0; carried in the
manifest caveats for the framework team. **Not grounds to fork.**

### 1.5 Wild / wildNx dimension — **NOW (specials) / parser_blind (crosses)**
- The specials' rates + fixed multipliers (1.2 above) ARE the felt "all-wild jackpot"
  quantification — **NOW**.
- The per-round wild-count distribution (0/1/2/3 = 34,111/36,306/8,966/617, W1 §8.4) and
  the wildNx×line-win multiplication law (base ×2/×5/×10 verified, specials immune,
  W1 §8.3) — **parser_blind** (per-round joint grid reads); requirement spec for the
  extraction layer. wild10x all-wild line: 0 occurrences in 89,090 rounds — honestly
  unknowable from this sample (W1 §9.2).

→ **No new code for ST140.** Declare `role: paid_spin, play: NormalCollectionSpin`.

---

## 2. ST126 — NewFreespin (NEW-EVENT) — full player-experience design

### 2.1 What the player FEELS (each feeling → a number)
1. **The grant** — "I got 10 free spins" (rare, mostly by luck, sometimes earned by the
   meter). → session cadence + the two trigger paths (§4).
2. **The hot board** — free spins hit 25.0% vs the base 13.9% (×1.807 uplift, W1 §4/§7.2).
3. **The one-way multiplier ladder** — ER starts at 1–5× and ONLY climbs (+1..+5× each
   spin; 8,181/8,181 steps positive; max 28×; line win = base × ER/100 × wildNx, proven
   with 0 violations, W1 §7.3). Pure escalation/anticipation.
4. **The rise-then-cliff arc** — hit-rate 41% (spins 1–3) → 28% (4–7) → **4.7%** (8–10)
   exactly as the ladder peaks (W1 §8.5). Hope climbs while odds collapse.
5. **The session outcome** — what the 10 spins were worth: mean 39.1× bet, median ~28.5×,
   4.7% pay nothing, best observed 338× (W1 §5.3/§7.2).
6. **No retrigger, ever** — the free skins carry zero bonus symbols (9,090/9,090 rounds,
   W1 §2): the block is exactly 10, structurally.

### 2.2 The metric set

| # | metric (felt experience) | exact data signal | tag | reuse-or-new |
|---|---|---|---|---|
| F1 | **Session cadence**: openers 908 contiguous blocks (the 1 double-trigger pair merges — same merge the server's own SummaryWin does, W1 §5.3); 1 per 88.1 paid spins; fixed length 10 (every `Freespin N` 1..10 appears ×909, zero truncated, W1 §3) | `spin_type_next_counts` st140→st126 = 908 (W2 ran this value via respin_dynamics; same accumulator) + `bonus_chain_dynamics` chain_count=908 / avg_chain_length=10.0 / retrigger=0 (W2-run) | **NOW** | NEW plugin (`freespin_dynamics`) F1 section; structure corroborated by reused `bonus_chain_dynamics` (chain STRUCTURE only — its ER surfaces are default-filled and MUST NOT be cited) |
| F2 | **Hot-board uplift**: hit 25.04% vs 13.86% (×1.807); overlaid per-round multiplier band distributions (st126 reaches ge200_lt500 — the 325× round); payid mix vs base (same paytable, hotter mix) | `spin_type_breakdown` both STs + `spin_type_bucket_{spins,win}` + `payouts_by_spin_type` (all W2-run exact) | **NOW** | strict-reused dims re-presented by `freespin_dynamics` F2 (same pattern as respin_dynamics M2/M3); `spin_type_rtp_buckets` intentionally omits free STs — by design, not a gap (W2 note 7) |
| F3a | **Session-value distribution in the machine's OWN taxonomy** (charter inv. 4): server SummaryWin NewFreespin tiers over 908 sessions — −1:43 / 0:1 / 1:47 / 5:89 / 10:160 / 20:326 / 50:177 / 100:64 / 300:1 (W1 §5.3); zero-win-session rate 4.7% | server `analysisResult.SummaryWin` — **the parser accumulates TotalWin+FeatureWin only** (parser.py 584–617); no SummaryWin accumulator exists | **parser_blind** | requirement spec: a SummaryWin (tier×feature) accumulator is the single highest-value parser add for this family — it IS the standard session multiplier distribution |
| F3b | **Session KPIs in the 付费回合 dimension**: avg_return_x 0.8924; session win-rate 14.87% (11,893/80,000); ≥10× session rate 1.90% (1,517/80,000); max session 338× | the shared session fold (volatility / hit_and_payout / big_win rates) — currently drops the scatter sessions' 45.8% of win (W2 ABORT, held trace) | **blocked_on_session_fix** | reuse (shared KPI layer); the four values here are the POST-FIX acceptance numbers from W2's held trace — re-audit = re-run `_tmp/m275_reuse_audit/run_audit.py` |
| F4 | **The one-way ER ladder** ⭐: ER@FS1 dist {1×:72.7, 2×:15.7, 3×:8.5, 5×:3.1}%; per-spin step dist {+1×:57.4, +2×:26.6, +3×:12.1, +5×:3.9}%; monotone 8,181/8,181; ER@FS10 mean 16.4× (max 28×); win law base×ER×wildNx (0 violations); specials immune; step weights segment-dependent (W1 §7.3/§8.7) | the per-round `ExtraRatio` FIELD — not accumulated; `chains_by_feature.extra_ratio_counts` is ReMarks-regex-sourced → flat-100 default on M275 (W2 note 2; proven on the blessed golden) | **parser_blind** | NEW plugin F4 section declares the spec + `parser_blind` flags; NEVER backed by the flat-100 accumulator |
| F5 | **The rise-then-cliff arc** ⭐: per-FS-index hit/mean-multiplier table (41.1% → 28.3% → 4.7% across skins 11/21/31; FS1–7 carry 91.7% of session win; FS3 holds the 325× max) (W1 §8.5) | FS-index (ReMarks "Freespin N") × outcome × per-round ReelSkin — none accumulated | **parser_blind** | NEW plugin F5 section, spec + flags |
| F6 | **Trigger-path dimension** ⭐⭐ (the central design) | see §4 | **NOW (coarse) / parser_blind (exact)** | NEW plugin F6 section + manifest `trigger_paths` declaration |
| F7 | **No-retrigger structure**: retrigger_events 0; free skins carry no bonus symbol | `bonus_chain_dynamics` retrigger=0 (W2-run) + manifest note | **NOW** | reuse + note |

### 2.3 Why ONE new plugin is forced (data, not taste)
The strict-reused machinery delivers F2 and the raw counts behind F1 — but **no reused
plugin states the freespin-session mechanic**: `spin_type_rtp_buckets` omits free STs by
design; `bonus_chain_dynamics`'s ER surfaces are default-filled flat-100 on field-borne-ER
machines (the "emits rows ≠ mechanic handled" trap, W2); and `respin_dynamics`' metric
semantics mis-describe a scatter freespin (§3). The felt mechanic — granted fixed-10
session, hot board, one-way ladder, rise-then-cliff, two doors in — has no home. → **NEW
plugin `freespin_dynamics`** (the ONE new plugin W2 allowed), assembling F1/F2/F6-coarse
from proven accumulators (`spin_type_next_counts`, `spin_type_bucket_{spins,win}`,
`chain_chunk_summaries`/`chain_bucket_*` keyed by `entry_cc_reset`,
`spin_type_breakdown`, `payouts_by_spin_type`) and declaring F3a/F4/F5/F6-exact
`parser_blind` (M279 `wheel_dynamics` honesty contract). `RTP_CONTRIBUTION=False`
(re-presents wins already attributed to st126's own pids; parity invariant untouched).

---

## 3. ROLE / PLAY for st126 + the analysis HOOK — RESOLVED (not a user question)

**Decision: `role: "freespin"` — a NEW role token; extend `KNOWN_ROLES`.
`play: "NewFreespin"` — the literal FeatureWin key. Hook: `ROLE_ANALYSES["freespin"] =
("freespin_dynamics",)` (ROLE hook, generic).**

Derivation per charter rule 8 (role token from the rawdata's own naming): the machine
calls these rounds `"Freespin N; "` in ReMarks (9,090/9,090) and the feature
`NewFreespin` (FeatureWin key). The structural kind = a **granted multi-spin free
session opened by a trigger event** — token **`freespin`** (the "New" prefix is the
machine's branding and belongs to `play`; the role token is the structural kind, exactly
as `respin` was derived from M43's "ReSpin" ReMarks).

**Why NOT `role: respin`** (W2 ran `respin_dynamics` successfully via that role, so this
was a genuine call — decided on the DATA semantics):
1. **Different structural kind.** `respin` (M43 WinRespin / M279 MoveSpin) = a win-driven
   extension of the same paid spin with variable, win-gated burst length. st126 = a
   FIXED-10 session opened by a scatter pid / a pity counter — nothing is win-gated
   (the trigger round usually wins NOTHING: pid 666 carries win 0). The signature
   differs too: `ExtraRatio` (100% presence, load-bearing win law) + `GameplayTriggerType`
   ∈{0,2} exist on no respin-role ST (W2 signature table).
2. **respin_dynamics' metric semantics would LIE about the felt experience**:
   `grant_rate.per_winning_paid_spin` (openers/winning-base-spins = 908/11,087 ≈ 8.2%) is
   meaningless for a scatter trigger independent of wins; `continuation_prob=0.9017`
   reads as a 90% win-gated chain when it is just the arithmetic of a fixed 10-block.
   The numbers were run-correct; the STORY they tell is the wrong mechanic.
3. **Family generality.** The brief's family (M272/M271/M264/M250/M256) are freespin
   machines (M272's NewFreespin is cited in framework docstrings). A generic `freespin`
   role + role-keyed `freespin_dynamics` is the reusable hook for all of them — per
   charter 8a, attach by ROLE because the analysis applies to ANY freespin-role ST
   (session cadence / uplift / fixed-vs-variable length / trigger paths are
   feature-agnostic). No play-key needed: there is no role-collision to scope away
   (unlike WinMiniGame/Wheel, whose `settlement` role is shared with unrelated features).
4. **No cross-fire**: no existing machine declares role `freespin` → today the hook fires
   only on M275; future family machines opt in by declaring the role — intended.

Consequences (all structural, none a fork):
- `respin_dynamics` does NOT attach to M275 (no respin-role ST → it isn't even in the
  derived set). Its W2-verified M275 numbers (openers 908, uplift 1.807, share 0.4977)
  become **acceptance anchors** for `freespin_dynamics`' equivalent metrics — same
  accumulators, freespin-correct semantics.
- `machine_spec.py` edits (base-EXCLUDED, no fleet base_hash flip):
  `KNOWN_ROLES += {"freespin"}`; `ROLE_ANALYSES["freespin"] = ("freespin_dynamics",)`.
- Recommended same-file companion fix (resolves W2 cross-cutting note 3, the
  self-contradicting report): `derive_mechanism_flags.freespin_applicable` should ALSO
  derive from `role=="freespin"` (additive; only manifests declaring the new role change
  output — M15/M43/M279 unaffected; W4 tester locks that with the existing manifests).
  If the coordinator prefers zero shared-logic deltas this can ride the framework-team
  queue instead; the manifest is correct either way.
- Tester non-leak locks (M43 precedent): `test_m15_has_no_freespin_dynamics`,
  `test_m43_has_no_freespin_dynamics`, `test_m279_has_no_freespin_dynamics`, and the
  converse — M275's derived set contains `freespin_dynamics` and does NOT contain
  `respin_dynamics` / `minigame_dynamics` / `wheel_dynamics` / `topdollar_choice`.
- Ordering note for W4: the `KNOWN_ROLES` extension must land WITH the manifest
  (`validate_schema` rejects unknown roles).

---

## 4. THE TRIGGER-PATH DIMENSION (central design goal)

### 4.1 The felt experience: two doors into the same room
The bonus opens by **luck** (3 bonus symbols = pid 666; random, 1.036%/paid spin) or by
**right** (CollectCount hits 1000; deterministic, exactly 0.100%/paid spin). The player
feels these completely differently — surprise vs earned certainty — even though W1 §7.2
shows the room inside is IDENTICAL in this config (same 10 spins, same skin ladder
11/21/31, same ER mechanics; only frequency differs). **The dimension therefore REPORTS
the two paths side-by-side and lets identity/difference EMERGE from the data** — exactly
what makes it reusable across the M272/M271/M264/M250/M256 family, where per-path
configs may genuinely differ.

Ground truth (W1 §7.1): 909 sessions = 829 scatter + 80 cc-peak; disjoint + exhaustive;
0 orphans; the 1 double-trigger round grants BOTH (additive; peak session first); the
per-round `GameplayTriggerType` on st126 is a PERFECT discriminator — **GTT=0 ↔ scatter,
GTT=2 ↔ collect-peak** (no mixed session).

### 4.2 The per-path metric table (the spec — each row side-by-side per path)

| metric (felt) | scatter666 | ccpeak | W1 anchor | tag |
|---|---|---|---|---|
| session count / share | 829 / 91.2% | 80 / 8.8% | §7.1 | **NOW** (coarse, see 4.3) |
| trigger rate per paid spin | 1.036% (random) | 0.100% (deterministic 1/1000) | §7.2 | **NOW** |
| RTP split (pp of the 44.41 freespin pp) | 40.86 | 3.56 | §7.2 | **NOW** |
| per-path round-level multiplier band distribution | — | — | §7.2 | **NOW** (chain buckets) |
| per-path session-tier distribution (SummaryWin taxonomy −1..300) | 39/1/42/81/150/291/164/60/1 | 4/0/5/8/10/37/12/4/0 | §7.2 | **parser_blind** |
| per-path session multiplier mean/median/max | 39.4× / 28.5× / 338× | 35.6× / 30.0× / 172.5× | §7.2 | **parser_blind** (session-level) |
| per-path zero-win session rate | 4.7% | 5.1% | §7.2 | **parser_blind** |
| per-path ER arc (ER@FS1 dist / step dist / ER@FS10 mean) | 1645 mean @FS10 | 1596 | §7.2 | **parser_blind** (rides F4) |
| per-path FS-index hit arc | — | — | §7.2 + §8.5 | **parser_blind** (rides F5) |

The config-identity finding itself ("within n=80 noise the two paths run the SAME
session") is a REPORTED OBSERVATION the side-by-side table makes visible — never an
assumption baked into the structure.

### 4.3 Deliverable NOW vs parser_blind (the honest boundary)
- **NOW — the coarse split already assembles** via `upstream_feature_breakdown`'s
  `[via NewFreespin]` vs `[via BCM cycle]` rows (W2-run: 32,637,000 win / 8,280 rounds vs
  2,894,500 / 810 rounds), built from the `chain_*` accumulators keyed by
  `entry_cc_reset` (trigger-anchor walk: pid-666 anchor vs cc-reset entry). Near-exact:
  the single double-trigger GTT=0 half (10 rounds, 48,500) bins to the BCM bucket — a
  1-in-909 edge the server's own SummaryWin merges the same way. `freespin_dynamics` F6
  consumes the same accumulators to present per-path round counts, win shares, RTP-pp
  split, and per-path band histograms, labeling paths from the manifest declaration
  (4.4). Per-path SESSION counts: derivable from `chain_chunk_summaries` if its `count`
  is chain-count — **W4 must verify that semantics on real chunks** (else derive via the
  proven fixed-10 length, stated as such). The trigger RATES come from the pid-666 row +
  `collect_mechanic` cycle length — both NOW.
- **MUST NOT be cited**: `bonus_chain_dynamics.by_feature`'s prev-round-pids heuristic
  (841/67 vs truth 829/80 — mislabels the ~12-14 cc-peak openers that happened to carry
  line wins; W2 attribution section). The ufb `[via …]` rows are the correct NOW view.
- **parser_blind — the exact split**: the per-round GTT tag never reaches the
  accumulators, so GTT-discriminated session tiers / per-path ER & FS arcs / the
  double-trigger un-merge wait for the per-ST extraction layer. The rows above are that
  layer's requirement spec.

### 4.4 The GENERIC DECLARATIVE manifest block (declaration shape ONLY — framework
implementation is a coordinator/user architecture discussion, NOT designed here)

Proposed per-ST declaration, machine-insensitive:

```json
"trigger_paths": {
  "discriminator": {
    "kind": "round_field",
    "field": "GameplayTriggerType",
    "map": {"0": "scatter", "2": "collect_peak"},
    "unmapped_value_policy": "surface_as_unknown_path"
  },
  "fallback": {"kind": "trigger_anchor_walk",
               "note": "for machines without a per-round discriminator field: anchor on the opening signal of the preceding paid round (trigger pid / counter-peak), the walk ufb's [via ...] split already implements"},
  "paths": {
    "scatter":      {"opened_by": {"payout_id": "666"}, "label": "scatter (3 bonus symbols)"},
    "collect_peak": {"opened_by": {"counter": "CollectCount", "at_peak": 1000}, "label": "collect-peak (pity timer)"}
  },
  "multi_trigger_policy": "additive_sessions"
}
```

Design properties (why this shape): the **field-discriminator is data** (field+value→
label, mapped from observed values only — GTT vocabulary beyond {0,2} unknown, W1 §9.6,
hence the explicit unmapped-value policy per
feedback_invariant_with_fallback_hides_drift: an unknown value is a SIGNAL, never a
silent residual); the **fallback names the session-derived walk** that already exists
(so family machines lacking the field degrade to today's near-exact split, not to
nothing); `paths.opened_by` documents the opening signal per path (pid vs counter-peak —
both observable, §7.1); `multi_trigger_policy` records the proven additive double-grant.
The block is **declarative and inert today** (`validate_schema` ignores unknown keys —
verified; the loader passes it through), so the manifest can carry it NOW as the
requirement spec without any framework change. `freespin_dynamics` reads ONLY the
`paths` labels from it (display labels for the NOW-coarse split); the discriminator/
fallback wiring is the framework discussion.

---

## 5. ATTRIBUTION DIMENSION — RESOLVED (decision, not a question)

**Decision: NO attribution rule of any kind.** No `round_win` rule, no
`SynthesizePayIdRule`, no manifest `round_win_rule` entry.

Justification from the data (W1 §4, W2 trigger/attribution section): every round
self-settles (`sum(PayoutIdToWinAmount)==WinCredits` 89,090/89,090 — both STs); st126
wins flow through their own real pids (the M273-pattern attribution the framework
documents); pid 666 is a zero-win marker (`is_trigger_marker:true`). W2 layer-c PROVED
zero `_unattributed_*` buckets and **parity EXACT**: sum(pid rtp_pp) = 89.23625 ==
summary.rtp == W1. The fallback bucket is 0 by construction — `sum(payid)==summary`
holds with no rule, which best serves the money-agnostic goal: every pid row is a real
machine event with its own hit-rate/multiplier semantics, nothing synthetic.

`rtp_integrity`: `paid_st: [140]` (only ST140 costs; a global-bet denominator would
inflate by st126's cost-0 BetAmount rows), fleet-standard `fallback_warn 0.5 /
fallback_fail 5.0`.

---

## 6. PROPOSED MANIFEST — `configs/machine_manifests/M275.json`

Schema `spintype-native/1`; validates once `KNOWN_ROLES` gains `freespin` (W4 ordering).
`validation.status: auto` (user sign-off is the coordinator's gate). Signatures = W1 §1
(every field at presence 1.0).

```json
{
  "machine_id": "M275",
  "schema": "spintype-native/1",
  "modes": [1],
  "inherits_from": null,
  "spin_types": {
    "140": {
      "role": "paid_spin",
      "play": "NormalCollectionSpin",
      "economy": {"win_field": "WinCredits", "kind": "real"},
      "signature": ["BetAmount", "CostCredits", "StopSymbolsByCol", "PayoutByPayline", "PayoutIdToWinAmount", "RewardLastNode", "ReelSkin", "CollectCount", "AccCredits", "CreditsSymbols", "WinCredits"]
    },
    "126": {
      "role": "freespin",
      "play": "NewFreespin",
      "economy": {"win_field": "WinCredits", "kind": "real"},
      "signature": ["BetAmount", "CostCredits", "StopSymbolsByCol", "PayoutByPayline", "PayoutIdToWinAmount", "RewardLastNode", "ReelSkin", "ReMarks", "ExtraRatio", "GameplayTriggerType", "WinCredits"],
      "trigger_paths": {
        "discriminator": {"kind": "round_field", "field": "GameplayTriggerType", "map": {"0": "scatter", "2": "collect_peak"}, "unmapped_value_policy": "surface_as_unknown_path"},
        "fallback": {"kind": "trigger_anchor_walk", "note": "pid-666 anchor vs CollectCount-reset entry — the walk upstream_feature_breakdown's [via ...] split already implements; near-exact (1-in-909 double-trigger edge bins to the counter path, same merge the server's SummaryWin does)"},
        "paths": {
          "scatter": {"opened_by": {"payout_id": "666"}, "label": "scatter (3 bonus symbols)"},
          "collect_peak": {"opened_by": {"counter": "CollectCount", "at_peak": 1000}, "label": "collect-peak (pity timer)"}
        },
        "multi_trigger_policy": "additive_sessions"
      }
    }
  },
  "trigger": {"payout_id": "666", "remarks": "Freespin", "opens": "NewFreespin", "note": "TWO trigger paths open the SAME NewFreespin 10-spin session: (a) scatter pid 666 = bonus on all 3 reels (win 0 marker; 1.036%/paid spin, random); (b) CollectCount==1000 (deterministic pity timer, +1 every paid spin; 0.100%). Per-round GameplayTriggerType on st126 discriminates them perfectly (0=scatter, 2=collect-peak); both-on-one-round grants BOTH sessions (peak first). The collect pot (AccCredits=100xCC) is NEVER paid as credits - anticipation display only. No retrigger is structurally possible (free skins 11/21/31 carry zero bonus symbols)."},
  "validation": {
    "status": "auto",
    "user_signed_off": false,
    "confirmed_against": {"mode": 1, "rawdata": "M275/mode_1"},
    "evidence": "session_artifacts/_onboard/M275/01_understanding.md (W1: 89,090 rounds, 2 real chunks, single md5 bucket 8c89bc95/9b453ffc; ST roles from own fields; sum(payids)==WinCredits 89,090/89,090; 909 sessions = 829 scatter + 80 cc-peak, 0 orphans; GTT perfect discriminator; ER win law proven 0 violations; RTP 89.24 = 44.82 base + 44.41 freespin) + 02_reuse.md (W2: live engine on the 2 real chunks; st140 STRICT-REUSE 4 PER_SPINTYPE + collect_mechanic [cycle 1000, correction_pp 0.0 correct]; st126 PER_SPINTYPE strict-reuse exact, mechanic NEW-EVENT; NO attribution rule needed, parity EXACT 89.23625; ufb [via] split near-exact; W2 ABORT held on the shared session-KPI fold). W3 (this doc): role 'freespin' NEW KNOWN_ROLES token derived from the machine's own 'Freespin N' ReMarks / NewFreespin feature name; freespin_dynamics NEW role-keyed plugin (the one W2-allowed); trigger_paths declarative block = the per-path dimension spec (coarse split deliverable NOW via the entry_cc_reset chain accumulators; exact GTT split parser_blind).",
    "caveats": [
      "BLOCKED_ON_SESSION_FIX (W2 ABORT, framework-team): the shared _close_session fold drops scatter-session freespin wins from the paid-round (付费回合) KPI dimension on M275 (45.8% of all win). Post-fix acceptance: volatility.avg_return_x≈0.8924, win sessions 11,893/80,000, >=10x sessions 1,517/80,000, max session 338x (W2 held trace; re-audit via _tmp/m275_reuse_audit/run_audit.py). Pre-fix, the session-dim KPI panels understate; pid/per-ST/ufb dims are CORRECT and unaffected.",
      "parser_blind (per-ST extraction layer, DIRECTION.md §3 — designed in 03_design.md, never fabricated): (a) ER ladder (ExtraRatio FIELD; chains_by_feature.extra_ratio_counts is ReMarks-regex-sourced and default-fills flat 100 on M275 — MUST NOT be cited as ER coverage); (b) FS-index x skin x outcome arc (41%->4.7% hit cliff); (c) exact GTT-discriminated trigger-path split + per-path session tiers/ER arcs (coarse split IS delivered via entry_cc_reset chain accumulators); (d) server SummaryWin session-tier taxonomy (parser accumulates TotalWin+FeatureWin only); (e) st140 bonus-count near-miss ladder (2-of-3 = 11.4%); (f) per-round wild-count / wildNx-on-line crosses.",
      "bonus_chain_dynamics.by_feature trigger-path labels use the prev-round-pids heuristic (841/67 vs GTT truth 829/80) and its pid-666 trigger_target label reads 'NormalCollectionSpin' — display-level legacy; the ufb [via ...] rows are the correct path view. Framework-team display item (W2 notes 2/4).",
      "collect_mechanic cosmetics (fleet-wide, M279-manifest precedent): completed_cycles_total counts resets (64 vs 80 true cycles); always-on clamp_warning; M275 sharpening — avg_bonus_payout divides the WHOLE NewFreespin win (92% scatter-path) by cycle count, ~15x the true per-BCM-cycle payout. estimated_correction_pp (the RTP-bearing output) is 0.0 and correct. Framework-team precision item.",
      "machine_mechanics.free_spin.applicable currently False (derive_mechanism_flags keys on play=='freespin' exact; M275's play is the literal 'NewFreespin') — resolved if the role=='freespin' derivation lands with the KNOWN_ROLES extension (machine_spec.py, base-excluded); otherwise a framework-team display item (W2 note 3).",
      "PROVENANCE: this manifest's evidence derives ENTIRELY from the single HISTORICAL md5 bucket 8c89bc95…/9b453ffc… (roster current is 2c98ce05…/ebad1145…). Structure claims are value-agnostic; every NUMBER belongs to that bucket. Any SERVED report must go through the md5-scoped generate path (fd6b507/597e8bf) and be stamped with the chunk md5s, not the roster's current.",
      "GameplayTriggerType vocabulary: only {0,2} observed in this bucket; the trigger_paths discriminator maps observed values only and surfaces any new value as an unknown path (signal, not residual).",
      "wild10x all-wild line: 0 occurrences in 89,090 rounds — its special pid/prize is unknowable from this sample (re-sample-scale item, non-blocking).",
      "modes: [1] only — the only mode with cached rawdata. Extend on data, never by assumption (the M43/M279 cross-mode pattern)."
    ],
    "date": "2026-06-11"
  },
  "out_of_engine_mechanics": [
    {"name": "CurJackpotStoreWin progressive (test-interface-zeroed)", "desc": "Present on every round of both STs, =0 on 100% of 89,090 in-sample records (W1 §1/§9.4) — the M279 pattern (user-resolved there 2026-06-10: a real progressive whose accumulation the CURRENT testspin interface forces to 0). Parse-as-is at 0; the field is in both ST signatures so parsing is FORWARD-COMPATIBLE when the interface populates it. RTP 89.24% is the BASE RTP (excludes the progressive).", "rtp_impact": true, "rtp_impact_current": 0, "source": "domain", "status": "real_but_test_interface_zeroed_pending_user_confirm_for_M275"},
    {"name": "Production collect semantics", "desc": "In THIS interface CollectCount ticks +1 on EVERY paid spin (deterministic 1/1000 pity timer) and the AccCredits pot is NEVER paid as credits (W1 §6/§9.3); CreditsSymbols is a constant config echo and SymbolIndexToRewards is always '{}'. Whether the PRODUCTION game ties ticks to actual credit-symbol landings and/or pays the pot is a DOMAIN fact testspin cannot show.", "rtp_impact": true, "rtp_impact_current": 0, "source": "domain", "status": "domain_unknown"}
  ],
  "round_win_rule": null,
  "rtp_integrity": {"paid_st": [140], "fallback_warn": 0.5, "fallback_fail": 5.0}
}
```

### What `derive_analyses(M275)` produces (after the two `machine_spec.py` lines)
CROSS_CUTTING (incl. `collect_mechanic`, `upstream_feature_breakdown`,
`bonus_chain_dynamics`) + the 4 PER_SPINTYPE + **`freespin_dynamics`** (role `freespin`).
**NOT attached**: `respin_dynamics` (no respin role), `topdollar_choice` (no
player_choice), `minigame_dynamics` / `wheel_dynamics` (no such plays) — the set is
exactly M275's, no cross-machine leak (tester locks above).

---

## 7. Deliverables summary for W4/W5 (none is a fork; no shared-plugin edits)

| item | type | where |
|---|---|---|
| st140 dims + collect mechanic | STRICT-REUSE | 4 PER_SPINTYPE + `collect_mechanic` (CROSS_CUTTING) — zero code |
| st126 dims | STRICT-REUSE | 4 PER_SPINTYPE (free-ST omission from rtp_buckets is by-design) |
| st126 mechanic + trigger-path dimension | **NEW plugin** | `features/freespin_dynamics.py` (base-EXCLUDED; role-keyed; F1/F2/F6-coarse NOW from proven accumulators; F3a/F4/F5/F6-exact declared `parser_blind`; `RTP_CONTRIBUTION=False`) |
| wiring | NEW (base-excluded) | `machine_spec.py`: `KNOWN_ROLES += freespin`; `ROLE_ANALYSES["freespin"]`; (recommended) `derive_mechanism_flags` role-aware freespin flag |
| manifest | NEW | `configs/machine_manifests/M275.json` (above, incl. the declarative `trigger_paths` block — inert today, the extraction-layer requirement spec) |
| attribution | **NONE** | self-settling proven; parity exact; fallback 0 |
| frontend ST dimension (deliverable #5) | NEW | console per-ST section for `freespin_dynamics` (st126): cadence, uplift, band overlays, trigger-path side-by-side, honest parser_blind notices — reuse sibling renderers/formatters/i18n (feedback_no_parallel_panel_impl); bet passthrough via chunk `_bet=1000` |
| render gate 7 | acceptance | Playwright headless: st126 section renders, per-path split visible, numbers sane vs W1 anchors, zero pageerror |
| non-leak tests | NEW | `test_m15/m43/m279_has_no_freespin_dynamics` + M275 derived-set exact |
| acceptance numbers | — | report on the 2 real chunks: parity 89.23625 exact; pid tables == W1 §8.1; openers 908; uplift 1.807; freespin share_of_all_win 0.4977; ufb [via] split 8,280/810 rounds; post-session-fix: 0.8924 / 11,893 / 1,517 / 338× |

---

## ESCALATIONS (domain-unknown / re-sample ONLY — for the coordinator)

Per the charter, naming/attribution/metrics are resolved above. Remaining items:

1. **[dependency, already coordinator-verified — restated, not new]** The W2 ABORT:
   the shared session-KPI fold (framework team). All F3b metrics are tagged
   `blocked_on_session_fix`; this design does not patch shared code and completes
   everything else independently.
2. **[domain] `CurJackpotStoreWin` zeroed (M279 pattern).** =0 on 100% of 89,090 rounds.
   M279's user resolution (real progressive, test-interface-zeroed, parse-as-is
   forward-compatible) almost certainly applies — needs the user's one-line confirmation
   that M275 is the same case at the sign-off gate.
3. **[domain] Production collect semantics (W1 §9.3).** Whether production ties
   CollectCount ticks to credit-symbol landings and/or ever pays the AccCredits pot is
   out of testspin's reach (here: deterministic +1/paid spin; pot never settled).
   Domain fact for the user gate; in-data treatment (anticipation-only) is correct as-is.
4. **[re-sample-scale, non-blocking, NOT requested]** wild10x all-wild special: 0
   occurrences in 89,090 rounds — only a much larger sample (user-OK required) could
   price it. Recorded as an honest gap, not proposed as an action.

Non-escalations forwarded as manifest caveats (framework-team queue): the SummaryWin
accumulator (highest-value parser add for this family), the ExtraRatio field-vs-ReMarks
sourcing of `bonus_chain_dynamics`, the GTT/per-round accumulators for the exact path
split, the chain by_feature label heuristic, the collect_mechanic cosmetics, the
`free_spin.applicable` display flag, and the md5-scoped report provenance note.

— end W3 quant design.
