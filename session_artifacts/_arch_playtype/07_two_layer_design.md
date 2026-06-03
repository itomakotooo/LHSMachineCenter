# Two-Layer Play-Type Architecture — design proposal (CORRECTED model)

> arch-designer (W2). Designs the two-layer model from **`DIRECTION.md §12`** (trigger-session is the play-type unit),
> not the superseded ST-primary model in §3/§10/02/04_v2. Markdown only — NO code, NO edits. Adversarial review +
> arch-critic/arch-validator follow; everything I am unsure about is flagged in §10.
>
> **Ground truth used** (cached only, no upstream fetch): `cache/_playtype_tax/tally_results.json` (parsed per-pilot
> signal census), `cache/_playtype_tax/{deep_tally,verify_claims,cross_check}.py` (the taxonomist's JSON-string-decoded
> walks), and `cache/_playtype_golden_pristine/<M>/player_impact_summary.json` (current analyzer output). Code read:
> `trigger_sessions.py`, `round_win.py`, `round_classification.py`, `analyzer/core/parser.py`, `analyzer/versioning.py`,
> and the whole `analyzer/play_types/` framework + 2 carves.

> **⚠ COORDINATOR CORRECTION (2026-06-02, user-taught — read `DIRECTION.md §13`):** "Layer 1 = round parser"
> below must be read as an **EVENT parser**. A SpinType is a protocol token for a kind of EVENT (reel spin /
> player CHOICE / settlement / state), NOT "a spin". Layer 1 must understand each event and extract what's
> meaningful — **economy AND player behavior (e.g. M15 ST=14 = the player's TopDollar picks) AND state** —
> never bucket by has-win / no-win. The round-type table in §2/§4a is INCOMPLETE: it omits player-choice +
> state event types and their behavioral statistics. **M15 (a full event parser — base spin ST=1 + the
> choice ST=14 with its pick statistics + settlement ST=15) is the milestone node** for this architecture.

---

## 0. TL;DR (the decision)

- The current code **already implements both layers**, but tangled inside `base_hash` closure files. Layer 1 (round
  parsing) lives in `parser.py`'s loop body; Layer 2 (trigger-session 统计口径) lives in `trigger_sessions.py` +
  `round_win.py` rule classes + the `_resolve_bonus_feature` / chain-labeling logic in `player_impact_analyzer.py`.
- The refactor is therefore **not "invent two layers"** — it is **"physically relocate the already-separable Layer-2
  trigger/attribution logic out of the closure, keep Layer-1 parsing shared in a base-excluded library, and make the
  carve unit a TRIGGER (not an ST)."**
- **Recommended variant: B — "Trigger-rooted play-type plugins over a shared round-parser library, attribution stays a
  universal engine that DELEGATES per-trigger policy to plugins."** (Variants and why-B in §3–4.)
- The 2 done carves slot in cleanly: **PT-3 BCM-cycle = a TRIGGER detector** (a play-type's trigger primitive);
  **PT-7 wild-nudge = a shared round-CLASSIFIER** (Layer-1 helper, NOT a trigger-rooted play-type). Confirmed in §8.

---

## 1. Problem statement (restated from Wave 1, corrected by §12)

A machine's analysis = read each round (parse) + decide which play-type's economy each round counts toward
(attribution / 统计口径). Today both jobs are welded into `base_hash` closure files
(`03_coupling_audit.md §2.1`: `parser.py` 122 KB, `round_classification.py` 18 KB, `round_win.py` 23 KB,
`trigger_sessions.py` 17 KB, plus mechanic chunks of `player_impact_analyzer.py` 272 KB). Editing any of them to
support or fix ONE machine flips `base_hash` → **all 420 machines re-flag** (`03 §3.1`). The play-type refactor exists
to relocate mechanic logic so editing it scopes to only the machines that use it.

**The model correction (`DIRECTION §12`) that this design answers:** the play-type unit is the **trigger-session**,
NOT the SpinType. The decisive counter-example is **M275**: the SAME freespin round-type (ST=126) is opened either by
a scatter (`pay_id=666`) or by the BCM cycle peak (`CollectCount==1000`). The rounds **parse identically** but their
economy counts toward **different play-types** (scatter-freespin vs BCM-reward freespin). An ST→play-type map cannot
express this; a TRIGGER→play-type map can.

Concrete pain points, each cited:

1. **Mechanic fix = fleet re-flag.** Fixing M274's BCM attribution edits `round_win.py` (in closure) → 420 re-flag
   even though 1 machine is affected (`03 §3.1` row "Fix M274 BCM attribution"; `03 §8 Case A`).
2. **Same-ST-different-trigger is unrepresentable in the ST-primary model.** Verified live: M275 freespin attributes
   to `NewFreespin [via BCM cycle]` (parent `NormalCollectionSpin`) **and** `NewFreespin [via NewFreespin]` in the SAME
   report (`cache/_playtype_golden_pristine/M275/player_impact_summary.json` lines 7252, 7424–7425). The C1 per-ST
   `detect_play_types` ownership (`_detector.py` Step 3b) routes ST=126 to ONE plugin — structurally wrong (`§12`).
3. **Silent config dependencies have no version signal.** `configs/bcm_pairings.json` (30 machines) and
   `configs/machine_round_win_rules.json` (13 machines) drive attribution but are hashed by nothing
   (`03 §6.2/§6.3`, `03 §8 Case E`). A per-machine attribution change is invisible to staleness.
4. **Attribution-engine vs per-mechanic-policy are conflated.** `round_win.py` holds BOTH a universal dispatcher
   (`extract_round_win`/`extract_round_payouts`/`extract_round_trigger_anchor`, every machine) AND mechanic-specific
   rule classes (`SettlementWinAmountRule`, `BCMCycleAnchorRule`) used by 13/30 machines. A fix to a rule class flips
   `base_hash` for all 420 (`03 §7.2 Risk`, hotspots #6/#8).
5. **The C2 hollow-carve trap is structural, not a one-off.** `CARVE_METHODOLOGY §2` shows that leaving logic in a
   closure file + calling it from a plugin delivers ZERO isolation while passing byte-identical "by construction." Any
   design that does not move the *code* out of the closure repeats this.

---

## 2. The two layers, made precise (the contract the variants share)

**Layer 1 — Shared round-PARSER library (keyed by round TYPE).** "Given one round dict + a frozen `RoundCtx`, read its
economy": `win`, `cost`, `is_paid`, `spin_count`, authoritative `pay_ids`, and any per-round mechanic fields
(CollectCount, LockReels, WinAmount, RewardIdToCollectAmount, …). A round of a given TYPE parses the same regardless of
what triggered it. **A freespin parses as a freespin whether a scatter or a BCM cycle opened it** — that is the whole
reason Layer 1 is trigger-blind.

Round TYPES derived from rawdata (`02 §A3` census, confirmed in `tally_results.json`):

| Round type | Detection (Layer-1 signal, trigger-blind) | Pilots exhibiting | Parse specifics beyond win/cost |
|---|---|---|---|
| `paid` | `CostCredits>0` (universal `is_paid_round`) OR `cost_credits_unreliable` probe | ALL | payline pay_ids; BCM fields ride along on paid rounds |
| `freespin` | `CostCredits∈{0,None}` + `ReMarks ~ "Freespin N"` | M275/M272/M260/M120/M31(ST44 "FreeSpin") | run length via remark index; `ExtraRatio` multiplier |
| `wheel` | cost 0 + `ReMarks ~ "WheelSpin CellIndex N; WheelId N"` | M279(ST2)/M260(ST2)/M99(ST97) | cell→win; `WheelId` |
| `respin` | cost 0 + `ReMarks ~ "ReSpin"/"Respin"` | M43(ST50)/M268(ST125) | `LockReels`/`LockLines`/`LockSymbols` if present |
| `nudge` | cost 0 + `ReMarks ~ \b(move\|nudge)\b` (**PT-7 carve**) | M279(ST36) | extends preceding paid spin; pay_ids from reeled position |
| `minigame_pick` | cost 0 + `ReMarks ~ "MiniGame[...]"`; win in `WinCredits`, `PayoutIdToWinAmount` empty | M43(ST51)/M99(ST98) | win is WinCredits-only (no pay_id breakdown) |
| `selector_offer` (phantom) | cost 0 + `DollarCount`/`ChosenDollar` present; `WinAmount`=null | M15(ST14) | preview; contributes 0 win (phantom) |
| `selector_settlement` | cost 0 + `WinAmount` populated, `WinCredits`=null | M15(ST15) | win in `WinAmount` |
| `transition` | cost 0 + win 0 + `ReMarks`=None (provisional) | M260(ST105) | LOW confidence (`02 §A8`); no economy |

> Note Layer-1 detection is by **round shape (cost/remark/field)**, never by hardcoded ST number — matching the
> generation-independence insight in `02 §A4` (freespin uses ST 44/126/138/157 across engines). The ST number is
> retained as a per-machine label in `st_map` for display/diagnostics, not as the routing key.

**Layer 2 — Trigger-session ATTRIBUTION (统计口径, keyed by TRIGGER).** "Group rounds into sessions by which trigger
opened them; route each session's economy to the play-type that triggered it." This is what `trigger_sessions.py`
already does (`compute_trigger_sessions`: paid trigger → following non-paid block = one session, with a per-session
`win_rule` and `session_win`) — but today it is one monolithic function in the closure with all per-trigger policy
inlined.

**A play-type = (TRIGGER detector) + (session attribution policy) + (stat rollup), DELEGATING round parsing to Layer 1.**
Examples: scatter-freespin = trigger `pay_id=666 + TriggerFreespin` → session = following freespin block → rollup =
freespin economy attributed to the scatter-freespin play-type. BCM-reward = trigger `CollectCount==cycle_peak` → session
= following reward block (freespin / wheel / minigame) → rollup = BCM-reward economy.

---

## 3. Design alternatives

All three keep Layer 1 as a shared base-excluded parser library and put the version model on
`base ⊕ {round-parser-lib hashes} ⊕ {play-type plugin hashes} ⊕ per-machine-config-hash ⊕ mode`. They differ in
**where the attribution loop lives and how much policy a plugin owns.**

### Variant A — "Fat play-type plugin owns its whole session loop"

Each play-type plugin owns trigger detection AND its own session-scan loop AND rollup. There is no shared attribution
engine; `compute_trigger_sessions` is deleted and re-expressed as N independent per-plugin scans.

```
fresh_slotlab/analyzer/
  round_parsers/                # Layer 1 (base-EXCLUDED)
    _base.py        # RoundParser Protocol, RoundEconomy dataclass
    freespin.py  wheel.py  respin.py  nudge.py  minigame_pick.py  selector.py  paid.py
  play_types/                   # Layer 2 (base-EXCLUDED)
    _plugin.py      # PlayTypePlugin: detect_triggers() + scan_sessions() + rollup()
    scatter_freespin.py   bcm_reward.py   topdollar_selector.py   wheel_selector.py ...
```

- **Pros:** maximum isolation per play-type; no shared loop to re-flag. A plugin is fully self-contained.
- **Cons (Wave-1-grounded):**
  - **Re-derives the hard-won double-count guards N times.** `trigger_sessions.py` lines 281–349 encode the
    `round_has_credited_win` double-count filter, the `seed=0` regular-payline guard, the `last_non_none` vs `sum_all`
    selection — each a fleet-wide invariant fix (`feedback_aggregator_parity_invariant.md`,
    `reference_trigger_session_patterns.md`). Forcing every plugin to re-own the scan loop invites N divergent copies of
    these guards → exactly the parallel-impl anti-pattern memory warns against
    (`feedback_no_parallel_panel_impl.md`).
  - **Multi-trigger interleaving on ONE robot is ambiguous** when N plugins each scan independently (who owns a bonus
    round two plugins both think they triggered?). M279 (BCM + nudge + wheel) and M260 (BCM + freespin + wheel) make this
    concrete.
- **Migration cost:** HIGH. Deletes `compute_trigger_sessions`; re-validates the parity invariant per-plugin.

### Variant B — "Shared attribution ENGINE; plugins supply per-trigger POLICY" (RECOMMENDED)

Keep ONE shared session-scan engine (the relocated, generalized `compute_trigger_sessions`) in the base-excluded
attribution library. It does the universal, fragile work ONCE: walk the robot, cut paid→non-paid→paid sessions, apply
the double-count filter, select session win. Each play-type plugin contributes only **policy**: a `TriggerSpec` (does my
trigger fire on this paid round?) + an `AttributionPolicy` (how is my session's win computed + which pay-id/label it
credits) + a `rollup` (my stat block). The engine asks each active plugin's `TriggerSpec` at each paid round and routes
the session to the winning trigger.

```
fresh_slotlab/analyzer/
  round_parsers/                       # Layer 1 (base-EXCLUDED, keyed by round TYPE)
    _base.py            # RoundParser Protocol + RoundEconomy
    freespin.py wheel.py respin.py nudge.py minigame_pick.py selector.py paid.py
  attribution/                         # Layer 2 ENGINE (base-EXCLUDED, shared)
    _engine.py          # session_scan(): the generalized compute_trigger_sessions
    _policy.py          # TriggerSpec + AttributionPolicy Protocols
  play_types/                          # Layer 2 POLICY plugins (base-EXCLUDED, keyed by TRIGGER)
    _plugin.py          # PlayTypePlugin: trigger_spec() + attribution_policy() + rollup()
    scatter_freespin.py bcm_reward.py topdollar_selector.py wheel_selector.py
                        common_selector.py lock_respin.py ...
    bcm_cycle.py        # PT-3 carve — the BCM TRIGGER primitive (already done)
  play_types_shared/                   # cross-cutting Layer-1 classifiers (base-EXCLUDED)
    wild_nudge.py       # PT-7 carve — a shared round-classifier (already done)
```

- **Pros (Wave-1-grounded):**
  - The fragile parity/double-count logic lives in ONE engine (relocated `compute_trigger_sessions`), so it is fixed in
    one place — matching how `extract_round_win` is "a universal dispatcher that stays in base" per
    `03 §7.1`/`§10.6`. Editing the ENGINE re-flags everyone (correct — it IS universal). Editing a play-type's
    `TriggerSpec`/`AttributionPolicy` re-flags only its machines.
  - **Multi-trigger on one robot is resolved by the engine deterministically** (one trigger-arbitration point, §3c),
    not by N racing scans.
  - It is the **smallest faithful relocation** of today's code: `compute_trigger_sessions` already takes
    `round_win_rules` + `ctx` and dispatches to rule objects (`trigger_sessions.py` lines 131–360). Variant B simply
    moves those rule objects into play-type plugins and the engine out of the closure.
  - Honors `feedback_prefer_complex_better.md`: the engine+policy split is the more robust structure; we are not
    deferring it.
- **Cons:** the engine stays universal → a genuine engine bug still re-flags 420 (`03 §10.6` calls this unavoidable for
  a universal primitive). The `TriggerSpec`/`AttributionPolicy` boundary must be drawn carefully so per-machine policy
  does not leak back into the engine.
- **Migration cost:** MEDIUM. Generalize + relocate `compute_trigger_sessions`; move 2 rule classes into plugins; keep
  the per-round consumption in `parser.py` byte-identical.

### Variant C — "Two-pass: parse-all-then-attribute"

Pass 1: Layer-1 parses every round into a `RoundEconomy` stream (no attribution). Pass 2: a separate attribution module
consumes the full stream and assigns sessions. Clean separation; plugins are pure functions over the parsed stream.

- **Pros:** cleanest conceptual split; Layer 2 never touches raw round dicts; trivially testable (golden `RoundEconomy`
  streams).
- **Cons (Wave-1-grounded):**
  - **Breaks the byte-identical accumulation-order guarantee.** `play_types/_base.py` lines 58–68 document that
    byte-identity depends on float-accumulation order and dict-key insertion order being **identical to the current
    single-pass inline loop**. A two-pass rewrite changes accumulation order → fails the correctness gate
    (`DIRECTION §4`) for reasons unrelated to logic.
  - Materializing a full `RoundEconomy` stream per chunk is a memory/throughput regression on 120k-round chunks (M274/
    M279) with no isolation benefit over B.
- **Migration cost:** HIGH and RISKY (byte-identity). Rejected primarily on the byte-identical gate.

**Chosen: Variant B.** It is the only variant that (a) preserves the single-pass byte-identical accumulation contract
already proven by the 2 carves, (b) keeps the fragile parity invariant in one engine instead of N copies, and (c)
resolves multi-trigger arbitration at one deterministic point. A and C trade those away for a conceptual purity that
the correctness gate and Wave-1 coupling evidence do not reward.

---

## 4. Recommended design (Variant B) in detail

### 4a. Layer 1 — shared round-parser library

**Where:** `fresh_slotlab/analyzer/round_parsers/` — **base-EXCLUDED** (its files are NOT added to `_CLOSURE_FILES`;
each parser's source is hashed into the version of any machine whose round-type set includes it — §5).

**Interface (Protocol sketch, no impl):**

```python
# round_parsers/_base.py  (DESIGN SKETCH — not code to write)
from dataclasses import dataclass

@dataclass(frozen=True)
class RoundEconomy:
    is_paid: bool
    cost: float
    win: float                      # rule-processed (matches RoundCtx.win_credits today)
    pay_ids: dict[str, float]       # rule-processed authoritative attribution
    spin_count: int                 # 1 for paid/most bonus; freespin run index if applicable
    round_type: str                 # "freespin" | "wheel" | "respin" | "nudge" | ...
    # mechanic extras are read by the plugin from round_dict directly; not all hoisted here

class RoundParser(Protocol):
    ROUND_TYPE: str                                  # e.g. "freespin"
    def matches(self, round_dict: dict, ctx) -> bool: ...   # trigger-BLIND shape test
    def parse(self, round_dict: dict, ctx) -> RoundEconomy: ...
```

**Isolation consequence (and why it is CORRECT):** editing `round_parsers/freespin.py` re-flags **every machine that
has a freespin round type** (M275, M272, M260, M120, M31, … — `02 §A5` PT-4 ~34 + PT-2 ~13 machines, deduped on
freespin-present). This is the right blast radius: a freespin parser is genuinely shared; if how we read a freespin
changes, every freespin machine's numbers can change, so all must re-flag. This is the same principle `03 §6.4` accepts
for variant fan-out and `CARVE_METHODOLOGY §8` states explicitly ("editing one re-flags every machine with that round
type — correct; it IS shared"). It is strictly better than today (edit freespin parsing → all 420 re-flag).

> **Important scoping decision:** Layer 1 does NOT get one parser per ST. It gets one parser per **round TYPE**. M14's
> ST=1 and M31's ST=43 both use the `paid` parser; M275/M272/M260 freespin all use the `freespin` parser. This is what
> makes a brand-new machine that only re-mixes existing round types cost ZERO new code (`DIRECTION §2`).

### 4b. Layer 2 — attribution engine + play-type policy plugins

**The engine** (`attribution/_engine.py`, base-EXCLUDED, shared) is the relocated + generalized
`compute_trigger_sessions`. Its universal responsibilities (lifted verbatim in spirit from `trigger_sessions.py`):

- Walk the robot's rounds; cut sessions at paid→non-paid→paid boundaries (lines 229–255).
- Apply the `round_has_credited_win` double-count filter so a bonus round already credited at pay-id level is not
  re-summed into the trigger (lines 281–329) — the Iter-3 fleet-wide parity fix.
- Seed session win at 0 so a co-occurring regular-payline win on the trigger round is not double-attributed
  (lines 263–272) — the M53/M27/M174 fix.
- Select the session win (the `last_non_none`/`sum_all` logic, lines 330–349).

**What changes:** instead of `is_new_trigger_remark(remarks)` deciding the rule inline (line 258) and `round_win_rules`
being a flat per-machine list, the engine asks the **active play-type plugins** two questions:

```python
# attribution/_policy.py  (DESIGN SKETCH)
class TriggerSpec(Protocol):
    # Does THIS play-type's trigger fire on this paid round? Return an opaque
    # trigger token (anchor pay-id or synthetic like "_bcm_cycle") or None.
    def fires(self, round_dict: dict, ctx) -> str | None: ...

class AttributionPolicy(Protocol):
    win_rule: str                         # "last_non_none" | "sum_all"
    def credit_target(self, trigger_token, session) -> str: ...   # which pay-id/label gets session_win
    def includes_round(self, round_dict, ctx) -> bool: ...        # session-membership override (rare)
```

**The play-type plugin** binds a trigger + a policy + a rollup + a Layer-1 dependency set:

```python
# play_types/_plugin.py  (DESIGN SKETCH — extends nothing fragile; pure declaration)
class PlayTypePlugin(Protocol):
    FEATURE_ID: str                        # "scatter_freespin", "bcm_reward", ...
    CLAIM_SIGNATURE: ClaimSignature        # auto-detect: is this play-type present on this machine?
    USES_ROUND_TYPES: tuple[str, ...]      # Layer-1 deps, e.g. ("freespin",) — drives hash composition
    MECHANIC_DEPS: tuple[str, ...]         # play-type deps (e.g. bcm_reward depends on bcm_cycle trigger)
    def trigger_spec(self, machine_config) -> TriggerSpec | None: ...     # None = not trigger-rooted
    def attribution_policy(self, machine_config) -> AttributionPolicy: ...
    def make_rollup(self, machine_config) -> MechanicAccumulator: ...     # the existing per-robot accumulator
```

**Concrete mapping of existing logic → plugins** (grounded in `round_win.py` + `trigger_sessions.py`):

| Today (in closure) | Moves to | Trigger token | Win rule |
|---|---|---|---|
| `SettlementWinAmountRule` + Type-1 `is_new_trigger_remark` | `play_types/topdollar_selector.py` | `pay_id=666` on `ReMarks="Trigger"` paid round | `last_non_none` (selector accepts last offer; `trigger_sessions.py` docstring) |
| Type-2 `sum_all` selector logic | `play_types/wheel_selector.py` + `common_selector.py` | win==0 pay-id anchor, no Type-1 remark | `sum_all` |
| `BCMCycleAnchorRule` + the `via BCM cycle` chain label | `play_types/bcm_reward.py` (DELEGATES trigger to `bcm_cycle.py` carve) | `_bcm_cycle` at `CollectCount==cycle_peak` | `sum_all` (delegates to round-level credit) |
| scatter `pay_id=666 + TriggerFreespin` (M31/M275 scatter path) | `play_types/scatter_freespin.py` | `pay_id=666` + `TriggerFreespin` remark | `sum_all` |
| `SynthesizePayIdRule` (st-label/multiplier synth) | stays a SHARED attribution helper in `attribution/` (used by several play-types; not trigger-rooted) | n/a | n/a |
| universal dispatch (`extract_round_win/payouts/trigger_anchor`, `is_paid_round`, `round_has_credited_win`) | **STAYS in base** — these are universal (`03 §7.1`, §10.6) | n/a | n/a |

**Composition with Layer 1:** a plugin never parses rounds itself. Its `USES_ROUND_TYPES` declares which Layer-1
parsers it consumes; the engine parses every round once via Layer 1 and the plugin's rollup reads the resulting
`RoundEconomy`. M275's `scatter_freespin` and `bcm_reward` plugins both declare `USES_ROUND_TYPES=("freespin",)` and
share the single `freespin.py` parser — this is the §12 requirement made mechanical.

### 4c. Detector — trigger-session ownership replaces per-ST ownership

The C1 `_detector.py` assigns each ST to one owning plugin (`st_map[st] = winner.FEATURE_ID`, Step 3b). Under §12 this
is wrong: one ST (M275 ST=126) belongs to TWO play-types depending on trigger. **Replace per-ST ownership with
trigger-session ownership:**

- Detection still runs `CLAIM_SIGNATURE.matches()` per plugin to decide **which play-types a machine HAS** (this part
  is sound — it answers "is the scatter-freespin trigger present? is the BCM-reward trigger present?", both true on
  M275). Keep it.
- **Drop the `st_map` single-owner assignment as the attribution key.** Keep `st_map` only as a *display label*
  (ST→dominant-play-type, best-effort, may be many-to-one). It MUST NOT route attribution.
- **Attribution ownership is decided per-SESSION at runtime by the engine**, not per-ST at detect time: when the engine
  cuts a session at a paid trigger round, it asks each active plugin's `TriggerSpec.fires(round)`; the plugin whose
  trigger fires owns that session. For M275: a paid round with `pay_id=666` → `scatter_freespin` owns the following
  freespin session; a paid round with `CollectCount==cycle_peak` (and no 666) → `bcm_reward` owns it. Same ST=126
  rounds, different owners, decided by the trigger on the paid round that opened the session.

**The crux: SAME ST under MULTIPLE triggers on one machine.** The engine handles it because ownership is keyed on the
**trigger round**, not the bonus round's ST. The arbitration rule when >1 trigger fires on the same paid round
(rare but real — `round_win.py` BCMCycleAnchorRule docstring notes M274 has 5/3902 rounds with both `5801` and
`CC==peak`): reuse the existing **max-numeric-anchor** heuristic already in `extract_round_trigger_anchor`
(`round_win.py` lines 496–521: "numeric pids win over synthetic underscore-prefixed ones") — a real `pay_id=666`/`5801`
beats a synthetic `_bcm_cycle`. Promote this from an inline heuristic to a documented engine arbitration step with an
**onboarding alert** when two *numeric* triggers tie (genuine ambiguity → human review, matching `_detector.py`
`_resolve_claimants` tie behavior).

---

## 5. base_hash isolation map + hash composition rules

### 5a. The composition algorithm (extends today's `versioning.py`)

Today (`versioning.py` lines 345–403):
```
effective(machine,mode) = sha256(base_hash) ⊕ {sorted feature_id=feature_hash} ⊕ mode
```
where `base_hash = sha256(sorted _CLOSURE_FILES, CRLF-normalized)`.

**New composition (additive — same shape, more contributors):**
```
effective(machine, mode) =
    h = sha256(base_hash)                                           # base_hash UNCHANGED in definition: still the closure
    for ptid in sorted(active_play_type_ids):                      # Layer-2 plugins this machine has
        h.update( b"\x00pt=" + ptid + b"=" + play_type_hash[ptid] )
    for rtid in sorted(used_round_type_ids):                       # Layer-1 parsers this machine uses
        h.update( b"\x00rt=" + rtid + b"=" + round_parser_hash[rtid] )
    h.update( b"\x00cfg=" + per_machine_config_hash )              # play_type_configs/<M>/mode_<n>.json (§5c)
    h.update( b"\x00mode=" + mode )
    return h.hexdigest()[:12]
```

Where:
- `play_type_hash[ptid]` = sha256 of `play_types/<ptid>.py` source (CRLF-normalized), same hashing style as
  `AnalyzerFeature.compute_hash()`. **PLUS the transitive hash of its `MECHANIC_DEPS` plugins** so editing a dep
  (e.g. `bcm_cycle.py`) re-flags dependents (`bcm_reward`). Compose deps the same way features compose: fold dep hashes
  into the plugin's own hash in sorted order. This is the **"hash composition is mandatory"** requirement made concrete.
- `round_parser_hash[rtid]` = sha256 of `round_parsers/<rtid>.py` source.
- `used_round_type_ids` = union of `USES_ROUND_TYPES` across the machine's active play-types **plus** the always-present
  `paid` parser. Derived, not hand-declared.
- `per_machine_config_hash` = `MachinePlayTypeConfig.per_machine_config_hash()` (already implemented,
  `_machine_config.py` lines 253–279) — closes the `03 §6.2/§6.3` silent-config gap.

**`base_hash` still covers the closure** (universal engine skeleton: `is_paid_round`, the universal `extract_round_*`
dispatch, the attribution-engine *invocation* glue in parser.py, RTP math, report shell). The relocation moves the
mechanic *policy* out; the universal dispatch stays in. This matches `03 §7.1` exactly.

### 5b. Per-piece blast-radius table (the isolation map)

Pilot machines used to size each row; counts from `02 §A5` (deduped on the relevant signal), `tally_results.json`,
`03 §3.1`.

| Edit this piece | In `_CLOSURE_FILES`? | base_hash flips? | Machines re-flagged | Correct? |
|---|---|---|---|---|
| `attribution/_engine.py` (session-scan engine) | NO (base-excluded) | no | every machine with ANY trigger-session play-type (~all bonus machines) | YES — it is the shared 统计口径 engine; a parity-logic fix legitimately affects all attributed machines, but NOT the pure-paid machines (M14 + ~63 PT-1 machines untouched) |
| `round_parsers/freespin.py` | NO | no | freespin machines (M275, M272, M260, M120, M31, ~40 deduped) | YES — shared parser; `CARVE_METHODOLOGY §8` |
| `round_parsers/wheel.py` | NO | no | wheel machines (M279, M260, M99, ~32) | YES |
| `round_parsers/nudge.py` (PT-7 home) | NO | no | nudge machines (~10, `02 §A5`) | YES |
| `play_types/scatter_freespin.py` (TriggerSpec+policy) | NO | no | scatter-freespin machines (M31, M275, ~13) | YES — fixing the scatter trigger must not touch BCM-only machines |
| `play_types/bcm_reward.py` | NO | no | BCM-reward machines (M272/M275/M274/M279/M260/M268 + ~28) | YES |
| `play_types/bcm_cycle.py` (PT-3 trigger primitive) | NO (already carved) | no | BCM-family (`bcm_reward` + any dependent) | YES — pinned by `test_bcm_cycle_carve.py` |
| `play_types/topdollar_selector.py` (was `SettlementWinAmountRule`) | NO | no | TopDollar family (M15 + 12, `03 §8 Case C`) | YES — was 420 today |
| `configs/play_type_configs/M274/mode_1.json` (per-machine policy) | NO | no | **M274 only** | YES — closes silent-config gap (`03 §8 Case E`: 1 vs 0-silent today) |
| `is_paid_round` / universal `extract_round_*` dispatch | YES (stays base) | YES | 420 (all) | YES — genuinely universal (`03 §10.6`) |
| RTP math / report shell / sampling | YES (stays base) | YES | 420 (all) | YES — universal data-quality (`03 §8 Case D`) |

**Goal check (`DIRECTION §2`):**
- *Add a new machine reusing existing play-types* → no new files; its `effective` = base ⊕ existing plugin/parser hashes
  ⊕ its config ⊕ mode → **0 fleet re-flag.** ✅
- *Change one machine's mechanic config* (e.g. M274 trigger pay-id) → only `per_machine_config_hash` changes → **only
  M274.** ✅
- *Fix a play-type* → only machines with that play-type. ✅
- *Edit a shared parser* → all machines with that round type re-flag — **this is correct and intended**, not a failure
  (§4a, `CARVE_METHODOLOGY §8`). ✅

### 5c. `mechanism_registry.py` and `_CLOSURE_FILES` cleanups (flagged by `03 §10.4`/hotspot-10)

`mechanism_registry.py`'s own docstring claims it is excluded from base "so detection changes don't flip base_hash" but
it IS in `_CLOSURE_FILES` (`03 §10.4`). Under this design, mechanism/play-type detection logic
(`_detector.py`, `_claim.py`) should be **base-excluded** too (it is per-machine detection, not universal math). The
`_CLOSURE_FILES` edit to remove these is the **one-time cost** (`CARVE_METHODOLOGY §5`): it flips `base_hash` once;
re-pin the base_hash-value tests with a documented reason. **Flagged for the critic:** removing files from
`_CLOSURE_FILES` is exactly the over-isolation risk `CARVE_METHODOLOGY §3.2` warns about — each removal needs the
paired-guard test (editing a still-universal function flips; editing the relocated detector does not).

---

## 6. Plugin / extension contract (skeletons)

### 6a. A trigger-rooted play-type — `scatter_freespin.py` (skeleton)

```python
# play_types/scatter_freespin.py  (DESIGN SKETCH — base-EXCLUDED)
class ScatterFreespinTrigger:                      # TriggerSpec
    def fires(self, round_dict, ctx):
        if not is_paid_round(round_dict):
            return None
        pids = round_dict.get("PayoutIdToWinAmount") or {}
        if "666" in pids and _trigger_freespin_remark(round_dict.get("ReMarks")):
            return "666"
        return None

class ScatterFreespinPolicy:                       # AttributionPolicy
    win_rule = "sum_all"
    def credit_target(self, token, session): return token            # credit pay_id 666
    def includes_round(self, round_dict, ctx): return True

class ScatterFreespinPlugin(PlayTypePlugin):
    FEATURE_ID = "scatter_freespin"
    USES_ROUND_TYPES = ("freespin",)               # delegates parsing to Layer 1
    MECHANIC_DEPS = ()
    CLAIM_SIGNATURE = ClaimSignature(              # auto-detect presence on a machine
        required_trigger_pay_id="666",
        required_bonus_remark_pattern=r"Freespin",
        # Rule-1 structural exclusion is NOT used to separate it from bcm_reward anymore —
        # both can be present; the ENGINE separates them per-session by trigger. (See §10 OP-2.)
    )
    def trigger_spec(self, mc): return ScatterFreespinTrigger()
    def attribution_policy(self, mc): return ScatterFreespinPolicy()
    def make_rollup(self, mc): return ScatterFreespinRollup(mc)   # per-robot MechanicAccumulator
```

### 6b. A play-type that depends on another play-type's trigger — `bcm_reward.py` (skeleton)

```python
# play_types/bcm_reward.py  (DESIGN SKETCH)
from analyzer.play_types.bcm_cycle import detect_cycle_peak, get_collect_count   # PT-3 carve, shared trigger primitive

class BCMRewardTrigger:                            # TriggerSpec — DELEGATES to the carved cycle primitive
    def fires(self, round_dict, ctx):
        if not is_paid_round(round_dict):
            return None
        peak = ctx.get("cycle_peak")               # engine pre-computes via detect_cycle_peak (already wired)
        if peak and get_collect_count(round_dict) == peak:
            return "_bcm_cycle"
        return None

class BCMRewardPlugin(PlayTypePlugin):
    FEATURE_ID = "bcm_reward"
    USES_ROUND_TYPES = ("freespin", "wheel", "minigame_pick")   # BCM reward can be any of these (M275 fs / M279 wheel / M274 minigame)
    MECHANIC_DEPS = ("bcm_cycle",)                 # editing bcm_cycle.py re-flags bcm_reward (hash composition §5a)
    CLAIM_SIGNATURE = ClaimSignature(
        required_fields=frozenset({"CollectCount","AccCredits","CreditsSymbols","SymbolIndexToRewards"})
    )
    def trigger_spec(self, mc): return BCMRewardTrigger()
    def attribution_policy(self, mc): return BCMRewardPolicy()   # win_rule="sum_all"
    def make_rollup(self, mc): return BCMRewardRollup(mc)
```

### 6c. A shared Layer-1 parser — `freespin.py` (skeleton)

```python
# round_parsers/freespin.py  (DESIGN SKETCH — base-EXCLUDED, trigger-BLIND)
class FreespinParser:
    ROUND_TYPE = "freespin"
    def matches(self, round_dict, ctx):
        return (not ctx.is_paid) and _freespin_remark(round_dict.get("ReMarks"))
    def parse(self, round_dict, ctx):
        return RoundEconomy(
            is_paid=False, cost=0.0,
            win=extract_round_win(round_dict, rules=ctx.rules, ctx=ctx.rule_ctx),     # universal dispatch stays in base
            pay_ids=extract_round_payouts(round_dict, rules=ctx.rules, ctx=ctx.rule_ctx),
            spin_count=_freespin_index(round_dict.get("ReMarks")),
            round_type="freespin",
        )
```

> Note the parser calls the **universal** `extract_round_win`/`extract_round_payouts` (which stay in base). The parser
> file itself holds only the freespin-specific *shape* logic (remark match, run-index). This keeps the universal
> dispatcher's blast radius universal while the freespin-shape blast radius is freespin-only.

### 6d. The wild-nudge classifier — `play_types_shared/wild_nudge.py` (already done, re-labeled)

PT-7 stays exactly as carved (`is_wild_nudge_round`). Under §12 it is **a shared Layer-1 round-classifier, not a
trigger-rooted play-type**: it answers "is this round a nudge?" so the `nudge` parser and the paid-spin extension logic
can treat it correctly. It has no `TriggerSpec`. It lives in `play_types_shared/` (or `round_parsers/`), base-excluded,
pinned by `test_wild_nudge_carve.py`. No change to its hash property.

---

## 7. Migration plan (phases + rollback)

Greenfield is permitted for the plugin set (`DIRECTION §4/§8`: discard the 9 feature plugins + 420 manifests), but the
**closure code is migrated, not rewritten**, to preserve the byte-identical gate. All work stays behind the existing
`use_play_type_plugins` flag (default OFF) until phase 3 flips it (`11 AS-BUILT`).

**Phase 1 — Layer-1 parser library + attribution engine relocation (no behavior change).**
Deliverables:
1. `round_parsers/` with `paid`, `freespin`, `wheel`, `respin`, `nudge`, `minigame_pick`, `selector` parsers — each a
   pure relocation of the corresponding inline branch in `parse_chunk_response`, base-excluded.
2. `attribution/_engine.py` = `compute_trigger_sessions` relocated out of `trigger_sessions.py` (the closure file) into
   a base-excluded module; the closure keeps only a thin re-export shim if any external script imports it
   (`feedback_perf_claim_needs_e2e_event_stream.md`: external script-mode importers exist).
3. `attribution/_policy.py` Protocols.
4. Gate tests per `CARVE_METHODOLOGY §3` for EACH relocated module (isolation + paired-guard), byte-identical on the 9
   golden pilots (flag OFF and ON), engagement (monkeypatch → output changes).
Rollback: the relocation is import-repointing; revert the commit + re-pin base_hash tests to the prior value.

**Phase 2 — play-type policy plugins (the 统计口径 carve — THE core per §12).**
Deliverables:
1. `play_types/{scatter_freespin, bcm_reward, topdollar_selector, wheel_selector, common_selector, lock_respin,
   minigame_pick_bonus}.py` — each moving its `TriggerSpec`/`AttributionPolicy`/rollup out of `round_win.py`'s rule
   classes + `trigger_sessions.py`'s inline Type-1/Type-2 branch into a base-excluded plugin.
2. Engine arbitration step (§4c) + onboarding-alert on numeric-trigger tie.
3. Migrate `configs/bcm_pairings.json` (30 machines) + `configs/machine_round_win_rules.json` (13 machines) into
   `play_type_configs/<M>/mode_<n>.json` (the per-machine config layer already supports the BCM bonus_feature merge —
   `_detector.py` lines 327–368, `_machine_config.get_bcm_bonus_feature`). This closes the silent-config gap.
4. Version model: add the `pt=`/`rt=`/`cfg=` folds to `versioning.py` (§5a).
5. Per-plugin gate + byte-identical + inject-bug TDD (`DIRECTION §6`).
**Correctness sub-task (per `DIRECTION §9`/§11):** the 4 golden pilots with pre-existing layer-2 `_unattributed`
fallback (M15/M268 large, M272/M279 small) get re-validated against rawdata. A deliberate attribution fix that diverges
from current output is surfaced as a flagged diff, NOT laundered into byte-identity.
Rollback: each plugin is independently revertible; the engine falls back to the relocated monolithic path when a
play-type's policy is absent (the `round_win_rules=None` byte-identical path in `compute_trigger_sessions` is the
fallback, preserved).

**Phase 3 — flip the active staleness signal + onboard remaining machines as "new".**
Deliverables:
1. Switch the backend staleness check from legacy `analyzer_version` to `effective_analyzer_version`
   (`03 §5`/§7.3 gap); treat blank `effective_analyzer_version` as historical.
2. Flip `use_play_type_plugins` default ON after the 12 pilots are byte-identical.
3. Onboard the remaining ~310 machines iteratively as "new machines" (compose existing play-types; add a plugin only
   for a genuinely-new mechanic) — `DIRECTION §5/§8`.
Rollback: flip the flag + the staleness-signal source back; both are single-switch reversions.

---

## 8. How the 2 done carves fit (verified)

- **PT-3 BCM-cycle (`bcm_cycle.py`, `c21eb4e`)** = the **BCM TRIGGER primitive**. `detect_cycle_peak` /
  `get_collect_count` / `compute_robot_cycle_peaks` / `at_cycle_peak_indices` / `infer_bcm_target_spin_type` answer
  "when does the BCM cycle complete (= fire its trigger)?" In Variant B, `play_types/bcm_reward.py`'s `BCMRewardTrigger`
  imports and delegates to it (§6b). It is correctly base-excluded and pinned by `test_bcm_cycle_carve.py`. **No
  re-work needed** — it is already the Layer-2 trigger primitive this design wants. ✅
- **PT-7 wild-nudge (`wild_nudge.py`, `8445312`)** = a **shared Layer-1 round-CLASSIFIER** (§6d). It is NOT
  trigger-rooted; it answers "is this round a nudge?" so the `nudge` parser + paid-spin-extension logic handle it. Under
  §12 it stays a Layer-1 helper. Pinned by `test_wild_nudge_carve.py`. **No re-work needed.** ✅
- The **C2 BCMBasePlugin** (`bcm_base.py`) is, in this model, the BCM **rollup + ClaimSignature** half of the
  `bcm_reward` (and `bcm_base` presence) play-type. Its accumulator already delegates cycle logic to `bcm_cycle.py`
  (the genuine redo). In Phase 2 it absorbs a `TriggerSpec`/`AttributionPolicy` to become trigger-rooted, OR is split
  into `bcm_base` (presence/rollup of the collection mechanic on paid rounds) + `bcm_reward` (the trigger-rooted reward
  session). **Flagged for the critic — see OP-5.**

---

## 9. Trade-offs / alternatives summary

| Concern | Variant A (fat plugin) | **Variant B (engine+policy)** | Variant C (two-pass) |
|---|---|---|---|
| Parity/double-count invariant | re-derived N times (risk) | **one engine (safe)** | one module (safe) |
| Byte-identical accumulation order | preserved | **preserved (single-pass)** | BROKEN (gate fail) |
| Multi-trigger one-robot arbitration | ambiguous (N scans) | **one deterministic point** | clean but irrelevant |
| Per-play-type isolation | maximal | **high (policy-level)** | high |
| Migration risk | high | **medium** | high |
| Faithfulness to existing code | low (rewrite) | **high (relocate)** | low (rewrite) |

Variant B chosen. The decisive factors are the **byte-identical accumulation-order contract** (kills C) and the
**single-copy parity invariant** (kills A) — both Wave-1-grounded, not aesthetic.

---

## 10. Open problems / what's hard / unresolved (be adversarial here)

**OP-1 — The engine stays universal, so a genuine engine bug still re-flags every attributed machine.** `03 §10.6`
calls this unavoidable for a universal primitive. I claim the engine's *policy-free* surface is small enough that it
changes rarely, but `trigger_sessions.py` has 8 commits (`03 §3.2`) — it is NOT change-free. **If the engine churns as
much post-refactor as `trigger_sessions.py` did pre-refactor, the isolation win is smaller than advertised.** Needs the
critic to judge whether the policy/engine line I drew actually moves the churn into the plugins.

**OP-2 — `scatter_freespin` and `bcm_reward` coexisting on M275 is the entire point, but the C1 detector's Rule-1
structural exclusion was DESIGNED to separate them** (`_detector.py` lines 16–22 explicitly cite the
"M275 ST=126 BCMFreespin-vs-ScatterFreespin conflict" and resolve it by `exclude_if_fields_present={CollectCount,...}`
on ScatterFreespin). Under §12 that exclusion is WRONG — both plugins must be active on M275, separated per-session by
the engine, not vetoed at detect time. **I am removing a deliberate C1 mechanism.** Risk: if the per-session trigger
arbitration is not airtight, M275 freespin wins could be double-counted (scatter session AND bcm session both claim the
same freespin block) or dropped. This is the single highest-risk change and the exact thing the old ST-primary model
got wrong in the opposite direction. **Must be validated with a session-level trace on M275 rawdata before Phase 2
ships**, not just byte-identical aggregate (a double-count + a drop can net to the same chunk total — the
`feedback_invariant_with_fallback_hides_drift.md` lesson).

**OP-3 — Is a freespin block EVER co-triggered (both scatter 666 AND cc==peak on the same paid round)?** The taxonomy
says M275 triggers are 91.8% scatter / 8.2% BCM-peak and implies they are disjoint, but I have NOT verified that NO
paid round carries both signals simultaneously. If they can co-occur, the max-numeric arbitration (§4c) silently routes
it to scatter (666 > synthetic `_bcm_cycle`) — which may or may not be the right 口径. **Unverified; flagged.** (I could
not run a sequential co-occurrence scan — no Bash; the existing `cross_check.py` did not test this exact predicate.)

**OP-4 — Session membership when a bonus block mixes round types.** M260 has freespin (ST157) + wheel (ST2) + transition
(ST105) and M279 has nudge (ST36) interleaved with paid spins. The engine cuts sessions at paid→non-paid→paid, but a
nudge (ST36, cost 0) is an EXTENSION of a paid spin, not a triggered bonus session (`reference_round_classification_primitives.md`
Bug 3). So the nudge must NOT open/close a session the way a freespin does. Today this is handled inline; the design
must let a Layer-1 round-type declare "I am a paid-spin extension, not a session member." **Under-specified in this
proposal** — I assert the `nudge` parser + PT-7 classifier carry this, but the engine's session-cut rule needs an
explicit "extension rounds are transparent to session boundaries" clause. Flagged.

**OP-5 — `bcm_base` vs `bcm_reward` split is unresolved.** Is "the BCM collection mechanic on paid rounds" a play-type
(it has no trigger of its own — it IS the base economy, like PT-1 per `02` top-note), or just a rollup feature? The
collection counter accrues on every paid spin (not a session). I lean: `bcm_base` = a paid-round rollup/ClaimSignature
(NOT trigger-rooted, like PT-1 base game), and `bcm_reward` = the trigger-rooted reward play-type. But the current
`BCMBasePlugin` conflates them. **Needs a decision before Phase 2** — it affects whether `02`'s PT-3 is "a play-type" or
"the base game with a collection counter."

**OP-6 — M274 has BOTH a real anchor (`pay_id=5801`) AND `CC==peak` never fires (cc always 0).** `cross_check.py` /
`tally_results.json` confirm M274 cc≡0. So `BCMRewardTrigger` (cc==peak) NEVER fires on M274; its trigger is purely
`pay_id=5801`. This means `bcm_reward`'s TriggerSpec must support BOTH a cycle-peak path AND a config-supplied anchor
pay-id path (per-machine config). The `02 §A6 disagreement #1` already flags that the old `bcm_cycle_anchor` rule
conflates detection with attribution. **The design's per-machine config (`play_type_configs`) carries the M274 anchor
pay-id**, but I have NOT specified how a single `bcm_reward` plugin cleanly supports two trigger mechanisms without
becoming a junk-drawer. Flagged.

**OP-7 — M260 ST=105 transition round.** LOW confidence (`02 §A8.1`, `cross_check.py` CHECK 3). If it is a no-economy
transition it is harmless to Layer 1 (`transition` parser returns zero economy), but if it ever carries win the design
mis-attributes. I propose treating it as zero-economy with an onboarding alert; unresolved pending a sequential
ST105→ST157 adjacency check I could not run.

**OP-8 — Variant fan-out interaction with play-types.** M273 has 85 variants (`03 §6.4`). If variants inherit the
parent's play-type set (as they inherit features today via `resolve_inheritance`), editing a shared play-type re-flags
all 86 — accepted (`03 §10.5`). But the per-machine `play_type_configs` path for variants is unspecified: does each
variant get its own config file, or inherit the parent's? Flagged; leans inherit-with-override but not designed here.

**OP-9 — I could not execute a fresh sequential rawdata trace** (Read tool errors on the 16M-token single-line chunk
files; no Bash). My multi-trigger evidence is the taxonomist's parsed `tally_results.json` + the existing golden
summaries (which DO show `[via BCM cycle]` vs `[via NewFreespin]` labels, lines 7252/7424 — strong corroboration that
the current analyzer already distinguishes the two paths). But OP-2/OP-3/OP-4/OP-7 each want a per-round sequential scan
I have not personally re-run this session. **The coordinator should run those four targeted scans before Phase 2** (the
`CARVE_METHODOLOGY §4` deep-parse, `json.loads` the `response`/`roundResult` strings) rather than trust this proposal's
adjacency/co-occurrence assumptions.

---

## 11. Out of scope (explicit, with rationale)

- **Output-level isolation.** Hash-level over-invalidation is accepted (`DIRECTION §4/§8`); a play-type edit re-flags
  every machine with that play-type even if its numbers are unchanged. Output-level is a later optimization.
- **The remaining ~310 machines.** Round-1 supports the 12 pilots; the rest onboard as "new machines" (`DIRECTION §8`).
- **Re-validating ALL pre-existing attribution correctness.** Only the 4 flagged `_unattributed`-bearing pilots get
  correctness re-validation in Phase 2 (`DIRECTION §9/§11`); a fleet-wide attribution audit is separate.
- **The legacy `analyzer_version` field.** Kept for backward-compat reads during migration; Phase 3 flips the *active*
  staleness signal to `effective_analyzer_version` but does not delete the legacy field (`03 §7.3`).
- **Universal infrastructure blast radius.** Sampling/RTP-math/report-shell changes still re-flag 420 — correct and
  unchanged (`03 §8 Case D`). Not a problem this refactor solves.
- **`mechanism_registry.py` full removal from closure.** Flagged (§5c) as a cleanup the design enables, but executing
  the `_CLOSURE_FILES` surgery + over-isolation guards is left to the implementer with the critic's sign-off.

---

*End of proposal. This is a W2 design for adversarial review — every assumption I could not personally verify against a
fresh sequential rawdata trace is flagged in §10 (OP-2/3/4/7/9 are the ones that gate Phase 2).*

---

## 12. Coordinator review (2026-06-02)

**Verdict: design ENDORSED as the direction.** Variant B is the right call — rejecting C (breaks the byte-identical
accumulation-order contract) and A (re-derives the parity/double-count invariant N times) is correctly grounded in the
byte-identical gate + Wave-1 coupling evidence, not aesthetics. The two-layer split (shared round-parsers by TYPE +
trigger-session attribution by TRIGGER) faithfully implements §12; the detector change (per-session trigger ownership
replacing per-ST ownership) directly resolves the crux. The 2 done carves are correctly placed (PT-3 = trigger
primitive; PT-7 = shared Layer-1 classifier).

**Empirical gaps the designer flagged (OP-9), now CLOSED by the coordinator (had Bash; the agent didn't):**
- **Linchpin CONFIRMED** (M275 chunk_0001, deep-parsed `response`): freespin is a SINGLE ST (`126`; 4780 rounds); BOTH
  triggers are real on the same machine — scatter `pay_id=666` (438 paid rounds) + BCM cycle (CollectCount on all 40000
  paid spins, peak=1000). "Same freespin ST, two triggers, different 口径" is real data, not a hypothesis — the
  ST-primary model genuinely cannot express it.
- **OP-3 RESOLVED — the two triggers are disjoint:** exactly **1 of 40000** paid rounds carries BOTH `pay_id=666` AND
  `CollectCount==peak` (the 666 rounds' CollectCount is spread across 46–802, not at peak). Per-session attribution is
  well-defined; the lone co-trigger is handled deterministically by the design's max-numeric-anchor arbitration
  (666 > synthetic `_bcm_cycle`). The 38 near-peak 666 rounds are pure-scatter (cc≠peak → the cycle trigger doesn't
  fire) — no ambiguity.

**Real Phase-2 gates (coordinator agrees with the designer):**
- **OP-2 is still the #1 risk, now de-risked but NOT closed:** removing the C1 Rule-1 detect-time exclusion is sound IF
  the engine's per-session arbitration is airtight. OP-3 shows the triggers are disjoint (arbitration rarely invoked),
  but Phase-2 MUST still ship a **session-level rawdata trace on M275** (every freespin session → exactly one trigger;
  chunk total unchanged; no double-count+drop netting) BEFORE flipping anything. Aggregate byte-identical is NOT
  sufficient (the fallback-hides-drift lesson).
- **OP-5 (bcm_base vs bcm_reward split) + OP-6 (M274's trigger is `pay_id=5801`, not cc==peak — cc≡0)** are genuine
  unresolved design decisions that gate Phase-2: the `bcm_reward` TriggerSpec must support a config-supplied anchor
  pay-id path, not only cycle-peak.

**Not over-claiming:** OP-1 (the engine stays universal → an engine bug still re-flags all attributed machines) is
accepted, not solved — correct for a universal primitive; worth watching that policy churn actually moves into the
plugins post-refactor.

---

## 13. M15 TopDollar — worked event-model + ST=14 stats (validated on real rawdata, 2026-06-02)

The **milestone node**. M15 is a TopDollar machine; its events (per `DIRECTION.md §13` — SpinType = event token):
- **ST=1** — base paid spin (cost 1000). A `ReMarks="Trigger"` ST=1 opens a TopDollar session.
- **ST=14** — a player PICK. 玩法: up to **4 picks**; the player may **stop early** or is **forced to take the 4th**.
  Fields: `DollarCount` (dollars in the offer), `ChosenDollar` (the dollars, e.g. "5-10-5"), `OfferValue` (their sum).
  **`WinCredits` on ST=14 is a PREVIEW of the offer, NOT real win** → contributes 0 economy (else RTP double-counts).
- **ST=15** — settlement; `WinAmount` = the accepted/forced offer = the real win.
- TopDollar play-type session = ST=1 trigger + the ST=14 pick sequence + the ST=15 settlement.

**ST=14 behavioral stats — validated over 5 chunks / 440 sessions / 40,000 base spins:**

| Stat | Real value (M15) |
|---|---|
| picks-per-session (1 / 2 / 3 / 4) | 104 / 66 / 69 / **201** |
| stopped-early vs forced-4th | 54.3% / 45.7% |
| bad-gamble (forced 4th < a passed offer) | 91 of 201 forced = **45.3%** |
| final settled value | min 10k / median 40k / mean 45.8k / max 440k |
| dollar-tier composition | 5:2188, 10:1030, 20:230, 50:22, 100:2 |
| trigger rate | 440/40000 = **1.10%** of base spins |
| **TopDollar RTP contribution** | **50.4%** of total bet |

These are exactly the behavioral signals the old "phantom 0-win selector" model discarded (it kept only the ST=15
win). Headline: TopDollar is a **1.1%-frequency feature carrying ~50% of RTP**, where players gamble to the 4th pick
46% of the time and ~45% of those over-gambles land below an offer they'd passed.

**Parser build (the milestone):** event parsers for ST=1 / ST=14 / ST=15 + trigger-session attribution + the ST=14
stat rollup, with ST=14 win = preview (0 economy). Gated: byte-identical vs current M15 output (the existing
settlement/phantom handling must still hold) + base_hash isolation + this session trace. The stats above are the
validated spec the parser encodes.
