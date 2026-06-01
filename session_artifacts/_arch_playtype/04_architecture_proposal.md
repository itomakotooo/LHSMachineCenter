# Architecture Proposal — Analyzer Play-Type Refactor
> Wave-2 designer output. 2026-06-01.
> Grounded in: `01_pipeline_map.md`, `02_taxonomy.md`, `03_coupling_audit.md`, `DIRECTION.md`.
> Foundation signed off per `DIRECTION.md §10`.

---

## 1. Problem Statement

The current analyzer is a shared monolith where approximately 1,070 lines of mechanic-specific logic
(`round_classification.py` 64% B, `round_win.py` 37% B, `trigger_sessions.py` 70% B, plus BCM functions in
`player_impact_analyzer.py`) are locked inside `_CLOSURE_FILES`. Any byte change to any of these files
flips `base_hash` and re-flags all 420 machines and 1,088 `(machine,mode)` pairs — even when the change
affects only one mechanic family. The six-phase display-feature unbundle proved the hash isolation
mechanism works (`multiplier_wild.py` edit re-flags only M275: `03_coupling_audit.md §4.1`), but that
isolation exists only on the display axis. The mechanic axis — where all real per-machine behavior lives
— is still fully shared.

**Five concrete pain points (all cited from Wave 1):**

1. **Full-fleet re-flag on every BCM fix.** `detect_cycle_peak`, `BCMCycleAnchorRule`,
   `_resolve_bonus_feature` are in base. A bug fix targeting M274 re-flags all 420 machines
   (`03_coupling_audit.md §3.1`, Case A). Target: re-flag only the ~30-55 BCM machines.

2. **Config changes are completely silent.** `configs/bcm_pairings.json` (30 machines) and
   `configs/machine_round_win_rules.json` (13 + M274) are NOT in any hash. Editing them changes
   attribution behavior for those machines with zero staleness signal
   (`03_coupling_audit.md §6.2`, `§6.3`).

3. **The staleness UI is wired to the wrong hash.** `/api/reports/stale-count` compares
   `analyzer_version` (SHA256 of `player_impact_analyzer.py` only), NOT `effective_analyzer_version`.
   Display-plugin isolation built in Phase 3 is invisible to the UI's stale badge
   (`03_coupling_audit.md §5`).

4. **B-class mechanic code trapped in universal parse loop.** `compute_trigger_sessions` (230 lines,
   Type 1 + Type 2 session families) and BCM cycle detection (`detect_cycle_peak`,
   `BCMCycleAnchorRule`) are called per-robot inside `parse_chunk_response`. The parse loop is in
   `_CLOSURE_FILES` (`01_pipeline_map.md §2 Stage 1`). There is no hook for mechanic-specific logic to
   plug into the per-round stream without re-parsing it.

5. **Auto-detection is absent; 420 manifests encode mechanic assignments as static config.** The
   current system requires a human-authored `M*.json` to declare which features apply. A new machine
   always requires a manifest edit, and the 420 manifests list all 9 universal display plugins for
   nearly every machine — meaning the feature declaration is effectively fleet-wide, not per-play-type
   (`01_pipeline_map.md §4`, `DIRECTION.md §4`).

---

## 2. Primary Structural Decision: Parse-Loop Hook vs Restructure

### The Problem (from `01_pipeline_map.md §8 Q3/Q4`)

`compute_trigger_sessions` and the BCM functions (`detect_cycle_peak`, `BCMCycleAnchorRule`) run
**inside** `parse_chunk_response` — the per-robot, per-chunk inner loop. The current 9 display plugins
hook at the **post-parse finalize/emit stage** (Stage 4). Moving mechanic logic to that post-parse hook
is insufficient: `compute_trigger_sessions` needs to observe the ordered round stream, and
`detect_cycle_peak` needs per-robot sequential state (CollectCount resets require observing the reset
event, not a batch). Neither can be computed after the fact from the already-flattened chunk dict that
Stage 4 receives.

### Alternative A: Per-Robot Hook Inside the Parse Loop

**Sketch**: `parse_chunk_response` calls `plugin_registry.per_robot_hook(robot_rounds, robot_state)`
for each robot, immediately after iterating that robot's rounds. Each play-type plugin registers a
`per_robot_hook` method. BCM plugin registers `detect_cycle_peak` logic here. TriggerSession plugin
registers `compute_trigger_sessions` logic here. The parse loop remains the "host" and delegates
mechanic accumulation into the plugin hooks.

**Pros:**
- Preserves the existing robot-iteration structure. Minimal structural change to `parse_chunk_response`.
- Plugin hooks receive the live ordered round stream — same sequential context BCM and trigger-session
  detection require.
- No re-parsing: data flows once.

**Cons:**
- `parse_chunk_response` STAYS in `_CLOSURE_FILES` (it's the host). The parse loop file itself never
  leaves base. Any change to the hook dispatch machinery re-flags the fleet.
- Blast-radius improvement is partial: mechanic rule classes move out, but the dispatch host stays in.
- The hook interface is novel machinery in the base. It needs to be designed carefully to not become a
  second way to embed mechanic logic in base.
- State communication from `per_robot_hook` output back into the existing chunk dict accumulation
  requires explicit plumbing for each mechanic (cycle peaks list, trigger session dict, etc.).

### Alternative B: Restructure parse_chunk_response into Base + Per-Play-Type Passes

**Sketch**: Refactor `parse_chunk_response` into two layers:
- **Layer 1 (base, stays in closure)**: pure universal operations — decode round fields, compute
  `is_paid_round`, extract `PayoutIdToWinAmount`, count symbols, compute `WinCredits`, accumulate
  `chunk_win`. Emits a list of annotated round dicts (`ParsedRound`) per robot.
- **Layer 2 (per play-type plugin)**: the plugin receives the `ParsedRound` stream for its claimed
  rounds and runs its own mechanic logic (BCM cycle detection, trigger-session windowing,
  wild-nudge tagging) against that stream.

**Pros:**
- Cleaner separation: base layer contains no mechanic branches. After the carve, editing BCM or
  trigger-session logic only touches plugin files.
- The `ParsedRound` stream is a stable data contract — plugins don't need parser internals.
- True blast-radius isolation: BCM plugin edit re-flags BCM machines; trigger-session plugin edit
  re-flags trigger-session machines.

**Cons:**
- Larger structural change. `parse_chunk_response` is 1,857 lines (`01_pipeline_map.md §1`) and is
  deeply stateful — the per-robot loop carries ~40 accumulator variables that intermix universal and
  mechanic state.
- The `ParsedRound` struct needs to carry enough fields that mechanic plugins don't need to re-read
  raw fields (which would require re-parsing). Getting this contract right is non-trivial.
- Migration risk: any omission from `ParsedRound` that a mechanic plugin needs causes a runtime
  failure, not a hash mismatch.
- Requires new `parse_state.py` / `ParsedRound` schema design.

### Alternative C: Two-Stage Parse with Mechanic Accumulators as Plugin State (Recommended)

**Sketch**: The `parse_chunk_response` loop is refactored to separate its per-robot work into:
1. **Universal inner body** (A-class, stays in base): computes `is_paid_round`, `WinCredits`,
   `PayoutIdToWinAmount`, symbols, paylines, session boundaries. Universal accumulators unchanged.
2. **Mechanic accumulator objects** (B-class, belong to plugins): each active play-type plugin provides
   a `MechanicAccumulator` object that is handed to the parse loop. The parse loop calls
   `acc.on_round(round_dict, robot_rounds)` for each round in the per-robot iteration. The accumulator
   object owns its own sequential state (e.g., BCM's `prev_cc`, trigger-session's open-session state).
   The parse loop does NOT know what the accumulator does — it only calls `on_round` and, at robot
   boundary, `on_robot_end(robot_rounds)`.
3. **At chunk end**: the loop calls `acc.finalize()` → returns a dict that is merged into the chunk
   output alongside universal outputs.

This is structurally Alternative A but with a critical difference: the `parse_chunk_response` function
can eventually be removed from `_CLOSURE_FILES` once its mechanic branches are fully evacuated.
The key insight is that the universal inner body (steps 1) is small and stable; the accumulators
(step 2) are the entire source of mechanic variation.

**Why Alternative C over A**: Alternative A's "hook dispatch machinery stays in base" risk is addressed
by making the accumulator interface minimal — the base loop calls exactly ONE method per round
(`on_round`) and ONE per robot (`on_robot_end`). There is no dispatch complexity in base; only the
call sites exist. Once all mechanic code is in accumulators, `parse_chunk_response` becomes a
mechanical coordinator with zero mechanic knowledge.

**Why Alternative C over B**: Alternative B's `ParsedRound` struct contract is the harder design
problem — if a mechanic plugin needs a field that Layer 1 didn't emit, it fails at runtime. Alternative
C's accumulator receives the raw `round_dict` directly, so it has access to ALL upstream fields without
a contract boundary that might omit something. The trade-off is that accumulators are more tightly
coupled to the upstream round schema, but that is acceptable: each play-type plugin is already
claiming ownership of specific upstream fields (BCM owns `CollectCount`; TopDollar owns `DollarCount`).

**Migration cost**: Medium. `parse_chunk_response` needs surgery to extract its BCM accumulators,
trigger-session state, and wild-nudge classification into three `MechanicAccumulator` objects. The
universal remainder (symbols, paylines, session-level win bucketing) stays in base. The surgery is
invasive but scoped: the function's external contract (input: chunk response + bet + rules; output:
chunk dict) does not change.

---

## 3. Recommended Design

**Chosen: Alternative C (Two-Stage Parse with MechanicAccumulator Objects).**

Justification from Wave 1 evidence:
- The parse loop MUST remain the host for per-robot ordering (both BCM and trigger-session detection
  require ordered-round sequential state — `01_pipeline_map.md §8 Q3/Q4`). No design can avoid this.
- The `MechanicAccumulator` interface requires exactly two hooks (`on_round`, `on_robot_end`), keeping
  the base-loop surface area minimal and stable. The method signatures are fixed; adding a new
  accumulator does not change the dispatch host.
- Once all mechanic branches are evacuated from `parse_chunk_response`, the file can be removed from
  `_CLOSURE_FILES`. The base-hash closure shrinks by its largest mechanic contributor (122 KB per
  `03_coupling_audit.md §2.1`).
- The 9 existing display plugins use `AnalyzerFeature.extract/reduce/emit` against the
  already-flattened chunk dict. Play-type plugins own BOTH a `MechanicAccumulator` (runs during parse)
  AND an `AnalyzerFeature.emit` (runs post-finalize). They are the same plugin class; two roles.

### Play-Type Plugin Model (3-4 sentences)

A play-type plugin is a class that implements TWO roles in one unit. During per-chunk parsing, it
provides a `MechanicAccumulator` object that receives ordered round events (`on_round`, `on_robot_end`)
and computes mechanic-specific per-chunk state (BCM cycle peaks, trigger session windows, wild-nudge
tags). After all chunks are merged, the same plugin class acts as an `AnalyzerFeature` — its `emit()`
method reads the pre-accumulated mechanic state from the summary stash and writes its analysis payload
(collect-cycle stats, trigger-session RTP breakdown, nudge win attribution) to the summary dict.
Play-type is registered and versioned identically to the existing display plugins (via
`feature_registry`, base-excluded SHA256), except that the manifest-based declaration is replaced by
auto-detection from rawdata: the plugin exposes a `claim_signature` (minimal field/remark predicate)
that the auto-detector matches against the machine's observed rawdata fields before the first chunk
parse begins.

---

## 4. Design: Play-Type Plugin Model

### 4.1 Plugin Contract

```
# File location example:
#   fresh_slotlab/analyzer/play_types/bcm_freespin.py
#   fresh_slotlab/analyzer/play_types/scatter_freespin.py
#   fresh_slotlab/analyzer/play_types/topdollar_selector.py
#   ... (one file per play-type)

# Every play-type plugin module:
#   1. Defines a MechanicAccumulator subclass (per-parse-loop state)
#   2. Defines a PlayTypePlugin subclass (AnalyzerFeature subclass with claim_signature)
#   3. Calls register(PlayTypePlugin()) at module top → appends to play_type_registry.ALL_PLAY_TYPES

class MechanicAccumulator(ABC):
    """Per-robot, per-chunk stateful accumulator. Instantiated fresh per robot."""

    @abstractmethod
    def on_round(self, round_dict: dict, round_idx: int) -> None:
        """Called for every round in this robot's round list, in order."""

    @abstractmethod
    def on_robot_end(self, all_rounds: list[dict]) -> None:
        """Called once after the last round of each robot."""

    @abstractmethod
    def to_chunk_partial(self) -> dict:
        """Return this robot's mechanic contribution dict to be merged into the chunk output."""


class PlayTypePlugin(AnalyzerFeature):
    """Play-type plugin = MechanicAccumulator factory + AnalyzerFeature emit.

    CLAIM_SIGNATURE: ClassVar[ClaimSignature] — the portable rawdata predicate
        that identifies this play-type on any machine. Used by auto-detection.
    MECHANIC_DEPS: ClassVar[tuple[str, ...]] — other play-type FEATURE_IDs
        this plugin depends on (e.g., BCM-freespin depends on BCM-base).
    """

    CLAIM_SIGNATURE: ClassVar[ClaimSignature]
    MECHANIC_DEPS: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def make_accumulator(self, machine_config: "MachinePlayTypeConfig") -> MechanicAccumulator:
        """Return a fresh accumulator for one robot. Called per robot per chunk."""

    # extract/reduce/emit inherited from AnalyzerFeature for the display-payload role.
    # extract() is called with the accumulator's to_chunk_partial() output already
    # merged into the chunk dict — so existing extract/reduce/emit semantics are preserved.
```

### 4.2 ClaimSignature — the auto-detection predicate

```
# fresh_slotlab/analyzer/play_types/_claim.py

@dataclass(frozen=True)
class ClaimSignature:
    """Portable, generation-independent rawdata predicate.

    A signature CLAIMS that this plugin applies to a machine when ALL
    conditions are met on the machine's observed rawdata sample.

    Fields
    ------
    required_fields : frozenset[str]
        Extra (non-baseline) round fields that MUST be present on paid rounds.
        E.g., BCM: {"CollectCount", "AccCredits", "CreditsSymbols", "SymbolIndexToRewards"}
        E.g., TopDollar: {"DollarCount", "ChosenDollar", "OfferValue"}
    required_bonus_remark_pattern : str | None
        If set, at least one bonus round must have ReMarks matching this regex.
        E.g., ScatterFreespin: r"\bFreeSpin\b"
        E.g., WildNudge: r"\b(move|nudge)\b"
    required_trigger_pay_id : str | None
        If set, at least one paid round must carry this pay_id in PayoutIdToWinAmount.
        E.g., ScatterFreespin (via PT-2): "666" when combined with TriggerFreespin remark.
        E.g., PT-6 (M274 ListRewardWheel): "5801"
    required_paid_cost_zero_bonus : bool
        If True, at least one bonus round must have CostCredits=0 + non-empty ReMarks.
        Used to exclude PT-1 (pure paid) machines.
    exclude_if_fields_present : frozenset[str]
        If any of these fields appear, this signature does NOT apply.
        E.g., PT-15 (non-BCM Wheel): exclude if BCM core fields present.
    """
    required_fields: frozenset[str] = frozenset()
    required_bonus_remark_pattern: str | None = None
    required_trigger_pay_id: str | None = None
    required_paid_cost_zero_bonus: bool = False
    exclude_if_fields_present: frozenset[str] = frozenset()
```

### 4.3 Plugin claim key vs ST number

Per `DIRECTION.md §10`: "Plugin claim key = feature signature; ST = the resulting per-machine
partition (NOT ST-number-as-key)."

The auto-detector runs each registered plugin's `CLAIM_SIGNATURE` against the machine's rawdata sample.
When a plugin's signature matches, the auto-detector observes which SpinType numbers are present in
rounds that exhibit the signature's signals. This produces the `st_map: dict[int, str]` for that
machine — mapping observed ST numbers to the play-type's FEATURE_ID. The ST map is per-machine
config (not part of the plugin hash) and is stored in the per-machine config layer (§6).

**Example (M31, scatter freespin):**
- `ScatterFreespinPlugin.CLAIM_SIGNATURE` requires: `required_bonus_remark_pattern=r"\bFreeSpin\b"`,
  `required_trigger_pay_id="666"`.
- Auto-detector observes M31 rawdata: bonus ST=44 has ReMarks="FreeSpin", paid rounds have
  pay_id=666 on trigger rounds.
- `st_map = {44: "scatter_freespin"}` stored in M31's per-machine config.
- Plugin receives `st_map` at parse time and uses it to know which round numbers are "its" rounds.

**M15 fork case (ST=1 = base paid + TopDollar trigger):**
- `PurePaidPlugin` claims ST=1 via `required_paid_cost_zero_bonus=False` (no bonus rounds).
- `TopDollarPlugin` claims `DollarCount+ChosenDollar+OfferValue` extra fields.
- Both signatures match. Auto-detector sees paid ST=1 AND bonus ST=14,15 with `DollarCount`.
- Result: `st_map = {1: "pure_paid", 14: "topdollar_offer", 15: "topdollar_settlement"}`.
- ST=1 is shared between `pure_paid` (for rounds without TopDollar fields) and `topdollar` (for
  trigger rounds carrying pay_id=666 + `Trigger` remark). The fork is handled inside the
  `TopDollarAccumulator.on_round`: if round is ST=1 AND has `DollarCount` OR pay_id=666 with
  `ReMarks="Trigger"`, it is a TopDollar trigger round. Otherwise it is a pure paid round.
  The two accumulators co-exist on the same machine; the TopDollar accumulator claims the trigger
  rounds; pure paid claims the rest.
- **ONBOARDING ALERT**: any ST whose rounds satisfy two signatures' claims without a clear fork
  rule raises an alert. Resolution: inspect rawdata and encode a fork rule in the plugin(s)
  (not in a per-machine manifest).

**M274 case (BCM schema present but CollectCount always 0; pay_id=5801 trigger):**
- `BCMBasePlug.CLAIM_SIGNATURE` requires `{"CollectCount","AccCredits","CreditsSymbols","SymbolIndexToRewards"}`. These are present on M274 paid rounds — signature MATCHES.
- `PT6ListRewardPlugin.CLAIM_SIGNATURE` requires `required_trigger_pay_id="5801"` PLUS the
  Minigame cell/lock remark pattern on bonus rounds.
- Both match. `st_map = {140: "bcm_base", 139: "bcm_listreward_minigame"}`.
- The BCM accumulator handles paid ST=140 (CollectCount tracking — all zeros, which is valid: the
  BCM cycle detection logic returns None for no observed reset, and the plugin's `finalize()`
  gracefully handles that case without emitting cycle-peak stats).
- The PT-6 accumulator handles bonus ST=139 (Minigame cell/lock observations).
- **The `_unattributed_st139` bug** (`DIRECTION.md §9`): the current monolith's trigger-session
  logic cannot attribute ST=139 wins because `detect_cycle_peak` returns None for M274 (cc always 0),
  leaving `_unattributed_st139` to collect 4.87% RTP. The PT-6 plugin replaces this with explicit
  pay_id=5801 anchor attribution. This is a deliberate correctness fix; the output DIVERGES from
  current output. It is flagged as a diff, not byte-identity-required (per `DIRECTION.md §9`).

### 4.4 "New plugin vs new per-machine config" decision rule

When a new machine brings a mechanic variant, the question is: does this variant need a new plugin,
or is it a config option of an existing plugin?

**Decision rule:**
- **New per-machine config** when: the mechanic logic (round classification, win attribution,
  session detection) is identical to an existing plugin, but one or more numeric/string parameters
  differ across machines (cycle length, trigger pay_id, specific ST number, ExtraRatio interpretation).
  The existing plugin's `MechanicAccumulator` already handles the variant correctly when given
  the machine-specific parameters from the config layer.
- **New plugin** when: the control flow (how rounds are classified, how wins are attributed,
  what sequential state is tracked) is structurally different from all existing plugins.

**Applied to M274 (BCM with cc≡0, trigger=pay_id=5801):**
- `BCMBasePlugin` cycle detection logic handles cc≡0 gracefully (detect_cycle_peak returns None).
- The ListRewardMinigame bonus rounds (ST=139, multi-cell Minigame remarks) have STRUCTURALLY
  different attribution logic from BCM-freespin or BCM-WheelSpin.
- The `BCMListRewardPlugin` (PT-6) is a **new plugin** — but it REUSES BCM base infrastructure by
  having `MECHANIC_DEPS = ("bcm_base",)`, meaning the BCM accumulator runs first and PT-6 receives
  the BCM-accumulated state (cycle peaks, trigger anchors) as input.

**Applied to M272 vs M275 (both BCM + freespin, different ExtraRatio scales, different trigger mix):**
- Same plugin (`BCMFreespinPlugin`) applies to both.
- Trigger pay_id (666 for both), cycle length (1000 for both), ExtraRatio interpretation (independent
  per-trigger parameter for both) — all handled by the SAME accumulator logic.
- Machine-specific config: which pay_ids are jackpot tiers on M275 (27502/27503/27504) — these live
  in the per-machine config layer. Same plugin; different config.

---

## 5. Auto-Detection (No Manifest)

### 5.1 Detection flow

```
# At the START of an analysis run (before any chunk is parsed):

def detect_play_types(
    machine: str,
    mode: int,
    sample_rounds: list[dict],  # first 500-2000 rounds from chunk_0001
    registered_plugins: list[PlayTypePlugin],
) -> "MachinePlayTypeConfig":
    """
    1. For each registered plugin P:
       - Evaluate P.CLAIM_SIGNATURE against sample_rounds
       - If signature matches: record P as claimed, note which ST numbers
         appear in rounds matching the signature's signals
    2. For each ST number observed in sample_rounds:
       - Determine which plugin(s) claim it
       - If exactly 1: assign ST → plugin FEATURE_ID in st_map
       - If 0: ST is "unclaimed" → assign to pure_paid if CostCredits>0,
                                    else to "unknown_bonus" → ONBOARDING ALERT
       - If 2+: fork case → check if plugins define a fork rule together
                            → if yes, apply fork; if no → ONBOARDING ALERT
    3. Emit MachinePlayTypeConfig:
         active_plugins: list[FEATURE_ID]   (detected, ordered by MECHANIC_DEPS)
         st_map: dict[int, str]             (ST number → FEATURE_ID)
         onboarding_alerts: list[str]       (any ambiguous/unclaimed STs)
    """
```

### 5.2 M15 hard case (ST=1 forks into pure-paid + TopDollar-trigger)

1. Auto-detector evaluates `TopDollarPlugin.CLAIM_SIGNATURE`:
   `required_fields={"DollarCount","ChosenDollar","OfferValue"}` → present on bonus ST=14 rounds.
   `required_trigger_pay_id` is not set (pay_id=666 with `ReMarks="Trigger"` is validated by
   the remark pattern instead). Signature matches.
2. Paid rounds are ALL ST=1. Bonus rounds are ST=14 (offer) and ST=15 (settlement).
3. ST=14: only `TopDollarPlugin` claims it. Assignment: `{14: "topdollar"}`.
4. ST=15: only `TopDollarPlugin` claims it. Assignment: `{15: "topdollar"}`.
5. ST=1: `PurePaidPlugin` claims it (CostCredits>0 is the universal paid-round predicate).
   `TopDollarPlugin` does NOT claim ST=1 by field signature — the DollarCount field appears
   only on ST=14 bonus rounds. **No fork** needed for ST=1: it is assigned to pure_paid.
6. Within the `TopDollarAccumulator.on_round`: when it sees ST=1 rounds with pay_id=666 +
   `ReMarks="Trigger"`, it records those as the trigger anchors for the TopDollar session.
   The pure-paid accumulator ignores these rounds' trigger signal (they ARE paid spins; the
   win-attribution is handled by the trigger-session logic inside the TopDollar accumulator).
7. Result: `active_plugins=["pure_paid", "topdollar"]`, `st_map={1:"pure_paid", 14:"topdollar", 15:"topdollar"}`, `onboarding_alerts=[]`.

### 5.3 M274 hard case (BCM schema present but cc≡0, trigger=pay_id=5801)

1. `BCMBasePlugin.CLAIM_SIGNATURE` → `required_fields={"CollectCount","AccCredits","CreditsSymbols","SymbolIndexToRewards"}` → all present on M274 paid rounds → matches.
2. `BCMListRewardPlugin.CLAIM_SIGNATURE` → requires Minigame cell/lock remark on bonus rounds +
   `required_trigger_pay_id="5801"` → both present on M274 bonus ST=139 and paid trigger rounds →
   matches.
3. ST assignments: `{140: "bcm_base", 139: "bcm_listreward_minigame"}`.
4. `BCMBaseAccumulator.on_round` for ST=140: tracks CollectCount (always 0 on M274) → no cycle peak
   detected → no BCM cycle trigger fires → graceful no-op.
5. `BCMListRewardAccumulator.on_round` for paid ST=140 with pay_id=5801: records trigger anchor
   (2,044 events at ~1.022% trigger rate per `02_taxonomy.md §A3 M274`).
6. `BCMListRewardAccumulator.on_round` for bonus ST=139: records Minigame win via `WinCredits`
   (direct, no PayoutIdToWinAmount on Minigame rounds).
7. The 4.87% `_unattributed_st139` RTP is now explicitly attributed to the trigger pay_id=5801
   bucket by the BCMListRewardAccumulator, NOT to the fallback bucket.
8. Result: `active_plugins=["bcm_base","bcm_listreward_minigame"]`,
   `st_map={140:"bcm_base", 139:"bcm_listreward_minigame"}`,
   `onboarding_alerts=[]` (pay_id=5801 is a known anchor for this plugin).

### 5.4 Onboarding alert format

When the auto-detector encounters an ST that cannot be cleanly assigned:

```
ONBOARDING ALERT — machine=<M>, mode=<n>
  Ambiguous ST: SpinType=<X>
  Matching plugins: [<plugin_A>, <plugin_B>]
  No fork rule defined between <plugin_A> and <plugin_B> for ST=<X>.
  ACTION REQUIRED: inspect rawdata for ST=<X> rounds and define a fork rule
  in one or both plugin files. Do NOT create a per-machine manifest entry.
```

The analyzer run continues with a conservative assignment (first-match wins) but stamps the alert
in the summary JSON under `"onboarding_alerts": [...]`. The frontend surfaces this as a warning
badge on the machine's report card.

---

## 6. Per-Machine Config Layer

### 6.1 What lives here

Per `DIRECTION.md §10` and `03_coupling_audit.md §7.1`:

| Config item | Current location | New location |
|---|---|---|
| payid → semantic mapping | `machine_round_win_rules.json` (13 machines) | per-machine config (hashed) |
| BCM bonus feature pairing | `bcm_pairings.json` (30 machines) | auto-detected (no config needed) |
| Trigger anchor pay_ids | `machine_round_win_rules.json` (M274: pay_id=5801) | per-machine config (hashed) |
| BCM cycle length | inferred from rawdata | per-machine config (auto-populated from detection) |
| Jackpot tier pay_ids | not currently tracked per-machine | per-machine config (hashed) |
| ST map (ST# → plugin FEATURE_ID) | not currently tracked | per-machine config (auto-populated, hashed) |

**Why bcm_pairings.json can be retired**: the 30-machine BCM bonus-feature pairings exist because the
old analyzer needed a human-provided mapping to know which feature name (`NormalCollectionSpin` vs
`NewFreespin`) corresponds to BCM vs scatter. Under the new design, the BCM accumulator observes
which SpinType follows a cycle-peak trigger — that IS the BCM bonus feature, by definition. The
pairing is auto-detected, not config.

### 6.2 MachinePlayTypeConfig schema

```
# Written to: configs/play_type_configs/<machine>/mode_<n>.json
# Hash: sha256 of this file's bytes → per-machine-config-hash component

{
  "machine": "M274",
  "mode": 1,
  "active_plugins": ["bcm_base", "bcm_listreward_minigame"],
  "st_map": {"140": "bcm_base", "139": "bcm_listreward_minigame"},
  "trigger_anchors": {
    "bcm_listreward_minigame": {"pay_ids": ["5801"]}
  },
  "cycle_length": {
    "bcm_base": null
  },
  "jackpot_tier_pay_ids": [],
  "onboarding_alerts": [],
  "detected_at": "2026-06-01T00:00:00Z",
  "config_schema_version": 1
}
```

The file is auto-generated by the auto-detector on first analysis run and cached. It is NOT
hand-authored. If the auto-detector disagrees with a cached config (rawdata changed significantly),
it raises an onboarding alert rather than silently overwriting.

### 6.3 Addressing the silent-dependency finding (`03_coupling_audit.md §6.2-6.3`)

`configs/bcm_pairings.json` and `configs/machine_round_win_rules.json` are currently NOT hashed.
Under the new design:
- `machine_round_win_rules.json` entries for specific machines are MIGRATED into the per-machine
  config files (`trigger_anchors` field). The JSON file itself is deprecated.
- `bcm_pairings.json` is retired (auto-detection replaces it).
- The per-machine config file IS hashed (see §7). Editing it → per-machine-config-hash changes →
  `effective_analyzer_version` changes for that machine only.

---

## 7. Hash / Version Model

### 7.1 New _CLOSURE_FILES (post-refactor, reduced set)

Files that MOVE OUT of `_CLOSURE_FILES` (become plugin content or per-machine config):

| File | Current status | New status |
|---|---|---|
| `fresh_slotlab/round_classification.py` | In `_CLOSURE_FILES` (majority B) | Carved: A functions remain in base; B functions move to play-type plugins |
| `fresh_slotlab/round_win.py` | In `_CLOSURE_FILES` (3 rule classes are B) | Carved: `SettlementWinAmountRule`, `BCMCycleAnchorRule`, `SynthesizePayIdRule` move to plugins; dispatcher+ABC stay in base |
| `fresh_slotlab/trigger_sessions.py` | In `_CLOSURE_FILES` (70% B) | Entirely moved to play-type plugins; the dispatching call site in `parse_chunk_response` becomes a MechanicAccumulator call |
| `fresh_slotlab/analyzer/mechanism_registry.py` | In `_CLOSURE_FILES` (docstring claims otherwise — `03_coupling_audit.md §9 hotspot 10`) | Moved to base-excluded plugin (`machine_mechanics` display plugin absorbs or it becomes a play-type plugin post) |
| `fresh_slotlab/player_impact_analyzer.py` (B portions) | In `_CLOSURE_FILES` | `_infer_feature_spin_type_mapping`, `_resolve_bonus_feature`, `_load_bcm_pairings`, `PAID_NORMAL_FEATURES` → moved to BCM plugin and auto-detection |

Files that STAY in `_CLOSURE_FILES` (remain A-class):

| File | Justification |
|---|---|
| `fresh_slotlab/analyzer/core/parser.py` (residual) | The universal inner loop body + MechanicAccumulator call sites stay in base. Once fully carved, this file shrinks but stays in closure as the universal coordinator. |
| `fresh_slotlab/round_classification.py` (A functions) | `is_paid_round`, `extract_authoritative_pay_ids`, `parse_payline_records` — universal, stay in base |
| `fresh_slotlab/round_win.py` (A functions) | `RoundWinRule` ABC, `extract_round_win` dispatcher, `extract_round_payouts` dispatcher, `extract_trigger_pay_ids_default` — universal dispatchers, stay in base |
| `fresh_slotlab/analyzer/feature_registry.py` | Registry plumbing — stays in base |
| All other current A-class closure files | Unchanged |

**New play-type registry file added to base:**
`fresh_slotlab/analyzer/play_type_registry.py` — analogous to `feature_registry.py` but for play-type
plugins. This file IS in `_CLOSURE_FILES` (it is the registry machinery, not a plugin). Adding a new
play-type plugin does NOT change this file; plugins self-register at import time.

### 7.2 Effective version composition algorithm

```
# versioning.py — extended algorithm

def compute_effective_version_for_machine(machine, mode, play_type_config):
    # Step 1: base hash (reduced _CLOSURE_FILES — same algorithm as today)
    h = sha256()
    for f in sorted(_CLOSURE_FILES):
        h.update(read_crlf_normalized(f))
    base_hash = h.hexdigest()[:12]

    # Step 2: play-type plugin hashes (auto-detected for this machine+mode)
    h2 = sha256(base_hash.encode())
    for fid in sorted(play_type_config.active_plugins):
        plugin_hash = play_type_registry.get_plugin_hash(fid)  # sha256 of plugin source
        h2.update(b"\x00" + fid.encode() + b"=" + plugin_hash.encode())

    # Step 3: display feature plugin hashes (same as today, but no manifest needed —
    #   display features are auto-applied based on active play-types)
    for fid in sorted(display_features_for_play_types(play_type_config.active_plugins)):
        feature_hash = feature_registry.get_feature_hash(fid)
        h2.update(b"\x00" + fid.encode() + b"=" + feature_hash.encode())

    # Step 4: per-machine config hash
    config_hash = sha256(read_bytes(play_type_config_path(machine, mode))).hexdigest()[:12]
    h2.update(b"\x00config=" + config_hash.encode())

    # Step 5: mode
    h2.update(b"\x00mode=" + str(mode).encode())

    return h2.hexdigest()[:12]
```

**machine_hash = base_hash + sorted(play_type_plugin_hashes) + sorted(display_feature_hashes) + per_machine_config_hash + mode**

This composition means:
- Editing a play-type plugin → only machines with that play-type change their effective version.
- Editing a display plugin → only machines with that display feature change (same as today).
- Editing a machine's per-machine config → only that machine changes.
- Editing base infrastructure → all machines change (correct; base IS universal).

### 7.3 Staleness UI migration

`03_coupling_audit.md §5` identified that `/api/reports/stale-count` uses `analyzer_version`
(monolith SHA256 only), not `effective_analyzer_version`. This must be corrected:

- **Phase 1**: continue computing both `analyzer_version` and `effective_analyzer_version`.
  Switch the backend staleness check to compare `effective_analyzer_version` (the per-machine
  scoped signal). The `analyzer_version` legacy field remains in the JSON for backward compat
  but is no longer the active staleness signal.
- **Phase 2**: once all machines have been regenerated under the new model, `analyzer_version`
  can be deprecated from new reports (old reports on disk still carry it; the backend must handle
  its absence gracefully with a fallback to "historical").

### 7.4 Worked re-flag scenarios

**Scenario A: Edit BCM-freespin play-type plugin**
- `BCMFreespinPlugin` source changes → `play_type_registry.get_plugin_hash("bcm_freespin")` changes.
- Only machines with `"bcm_freespin"` in their `active_plugins` list get a new effective version.
- Per `02_taxonomy.md §A5`: ~34 machines have BCM+freespin (PT-4).
- Result: ~34 machines re-flag. Other 386 machines unchanged.

**Scenario B: Edit M274's trigger config (per-machine config file)**
- `configs/play_type_configs/M274/mode_1.json` is edited (e.g., trigger anchor pay_id changes).
- `config_hash` changes for M274 mode 1 only.
- M274's `effective_analyzer_version` changes; all other machines unchanged.
- Result: 1 machine re-flags. (Compare: today editing `machine_round_win_rules.json` is SILENT — zero re-flag per `03_coupling_audit.md §6.3`.)

**Scenario C: Edit wild-nudge play-type plugin (`is_wild_nudge_round` logic)**
- `WildNudgePlugin` source changes → its hash changes.
- Per `02_taxonomy.md §A5`: 10 machines have PT-7 (wild-nudge).
- Result: ~10 machines re-flag. Other 410 unchanged.

**Scenario D: Edit `compute_trigger_sessions` (now inside ScatterFreespinPlugin)**
- The function is part of `scatter_freespin.py`.
- `ScatterFreespinPlugin` hash changes.
- Re-flags: machines with PT-2 (13+ scatter-freespin machines) + any other plugin that uses
  `ScatterFreespinAccumulator` for trigger-session logic.
- Result: ~13-52 machines re-flag (depending on how many machines use Type 1 trigger sessions).
  Compare: today editing `trigger_sessions.py` re-flags all 420 machines.

**Scenario E: Add infrastructure feature (new sampling parameter)**
- Edit `base_pipeline.py` or `parser.py` universal body → `_CLOSURE_FILES` → `base_hash` changes.
- All 420 machines re-flag. This is CORRECT (infrastructure change affects everyone equally).

---

## 8. byte-identical Correctness Gate

Per `DIRECTION.md §9`: "byte-identical proves the CARVE didn't change behavior; it does NOT prove
the behavior was right."

### 8.1 Standard gate (refactor carve)

For play-type plugins that are a clean CARVE of existing logic (no intentional fix):
- Generate report for each pilot machine using the new play-type plugin architecture.
- Compare every key in `player_impact_summary.json` against the current (pre-refactor) report.
- Assert byte-identical on all keys EXCEPT:
  - `effective_analyzer_version` (changes by design — the new hash composition is different).
  - `onboarding_alerts` (new field).
  - `active_play_types` (new field).
- Test structure: one pytest per pilot machine, fixture = pre-refactor golden JSON.
- Inject-bug red→green: corrupt one function in the plugin → assert at least one key differs →
  revert → assert byte-identical again.

### 8.2 Correctness-fix carve-out (M274 and other known-suspect machines)

Machines where the current output is itself wrong (identified by `_unattributed_*` fallback share
> 0.5% per `03_coupling_audit.md §8 Case A`):
- The byte-identical gate is SKIPPED for the affected keys.
- Instead, assert that `_unattributed_*` buckets are SMALLER (or absent) in the new output.
- The diff is flagged in the test report: "Correctness fix detected: `_unattributed_st139` removed,
  4.87% RTP now attributed to `pay_id=5801` (BCMListRewardPlugin trigger anchor)."
- This diff is surfaced to the user as a flagged change, not silently accepted.

### 8.3 Known-suspect machine list (round-1, from `03_coupling_audit.md §8 Case A`)

Machines with BCM fallback_pct > 0.5% per the sweep (55 (machine,mode) pairs identified):
- M250: 100% fallback, M268/M260/M264: 70-90% fallback — these are correctness-fix candidates.
- For the 12 pilots: M274 (confirmed 4.87% unattributed) is the primary case.
- Other pilot machines: byte-identical gate applies (no known attribution errors).

---

## 9. Migration Plan

### Phase 1: Foundation + BCM carve (pilots M272, M275, M274, M279, M268)

**Deliverables:**
1. `fresh_slotlab/analyzer/play_types/` directory created.
2. `MechanicAccumulator` ABC defined in `play_types/_base.py`.
3. `PlayTypePlugin` subclass of `AnalyzerFeature` defined in `play_types/_plugin.py`.
4. `ClaimSignature` dataclass defined in `play_types/_claim.py`.
5. `fresh_slotlab/analyzer/play_type_registry.py` — analogous to `feature_registry.py`.
6. Auto-detection function `detect_play_types()` in `play_types/_detector.py`.
7. Per-machine config schema + reader/writer in `play_types/_machine_config.py`.
8. **First plugins**: `BCMBasePlugin`, `BCMFreespinPlugin` (covers M272, M275, M279).
   These carve `detect_cycle_peak`, `BCMCycleAnchorRule`, `_resolve_bonus_feature`,
   `_load_bcm_pairings`, `PAID_NORMAL_FEATURES` OUT of base.
9. `BCMListRewardPlugin` (covers M274, PT-6) — includes the correctness fix for
   `_unattributed_st139`.
10. `BCMLockReelsPlugin` (covers M268, PT-11).
11. `parse_chunk_response` extended with MechanicAccumulator call sites (universal shell
    preserved; BCM accumulator plugged in).
12. Staleness backend switched to `effective_analyzer_version`.
13. byte-identical golden tests for M272, M275, M279, M268 (carve gate).
14. Correctness-fix test for M274 (unattributed gone, diff flagged).
15. `configs/play_type_configs/M272/mode_1.json` through M274 auto-generated.
16. `machine_round_win_rules.json` M274 entry migrated to M274 per-machine config.
17. `bcm_pairings.json` entries for Phase 1 pilots retired.

**Rollback**: Phase 1 is behind a feature flag (`--use-play-type-plugins`). If byte-identical gate
fails for any pilot, the flag is disabled and the monolith path resumes. The flag is removed when
all 12 pilots pass.

### Phase 2: Remaining pilot play-types (M14, M31, M43, M15, M99, M120, M260)

**Deliverables:**
1. `PurePaidPlugin` (covers M14 — trivially, no mechanic accumulator needed; exists to make
   `active_plugins=["pure_paid"]` explicit and hashed).
2. `ScatterFreespinPlugin` — absorbs `compute_trigger_sessions` Type 1 + Type 2 families,
   `is_new_trigger_remark`, `SettlementWinAmountRule`. Covers M31 (scatter freespin) and M15
   (TopDollar, via fork). This is the largest carve: 230 lines of `compute_trigger_sessions`
   move to the plugin's `TriggerSessionAccumulator`.
3. `TopDollarPlugin` — the fork of M15's ST=1: trigger detection + settlement win extraction.
   Absorbs `SettlementWinAmountRule` from `round_win.py`.
4. `WinRespinPlugin` (covers M43 ST=50 ReSpin, PT-12).
5. `MiniGamePlugin` (covers M43 ST=51, M99 ST=98, PT-13) — WinCredits-only attribution.
6. `LockSymbolPlugin` (covers M99 ST=96/97, PT-9).
7. `WheelNonBCMPlugin` (covers M99 ST=97 WheelSpin, PT-15).
8. `MultiSymbolCollectionPlugin` (covers M120, PT-14) — `RewardIdToCollectAmount` handling.
9. `WildNudgePlugin` — absorbs `is_wild_nudge_round` from `round_classification.py`. Covers
   M279 ST=36 (also co-present with BCMBasePlugin on M279).
10. `CostCreditsReliabilityPlugin` — the pre-scan probe for M10-family (LockReSpin ST=13,
    CostCredits always 0) extracted from `parse_chunk_response` pre-scan block.
11. `trigger_sessions.py` removed from `_CLOSURE_FILES` (fully evacuated into plugins).
12. `mechanism_registry.py` removed from `_CLOSURE_FILES` (moved to base-excluded plugin,
    fixing the docstring-vs-reality inconsistency flagged at `03_coupling_audit.md §9 hotspot 10`).
13. `round_classification.py` B functions removed from `_CLOSURE_FILES` (A functions remain).
14. `round_win.py` B rule classes removed from `_CLOSURE_FILES`.
15. byte-identical golden tests for all 12 pilots.
16. Auto-detection configs generated for all 12 pilots.
17. `bcm_pairings.json` retired entirely. `machine_round_win_rules.json` deprecated (entries
    migrated to per-machine configs).

**Rollback**: same flag as Phase 1. If any pilot fails byte-identical, identify which plugin
caused the diff, fix or escalate.

### Phase 3: Fleet onboarding (remaining ~308 machines)

**Deliverables:**
1. Run auto-detection against all 327 machines with cached rawdata.
2. For each machine: generate `play_type_configs/<M>/mode_<n>.json`.
3. For any machine where auto-detection raises an ONBOARDING ALERT: human reviews the alert
   (typically resolves to "add a config entry for the trigger anchor" or "this is the same
   mechanic as an existing pilot, just different ST number").
4. Regenerate reports for all machines (fleet re-generation is expected once — the effective
   version changes because the composition algorithm changed).
5. New machines after Phase 3 onboard identically to "a brand-new machine" (no manifest
   creation, no plugin changes unless genuinely new mechanic).
6. The 420 `machine_manifests/*.json` are DELETED (they are greenfield-replaced by auto-detection
   + per-machine play-type configs). The 9 display plugin FEATURE_ID declarations in those
   manifests are replaced by `display_features_for_play_types()` logic that auto-applies the
   correct display plugins based on active play-types.
7. Old test files (`test_2a..6_*`, feature-plugin tests, manifest/closure-pin tests) are
   DELETED per `DIRECTION.md §6`.
8. New test suite: one pytest per play-type plugin (byte-identical golden + inject-bug).

**Rollback**: Phase 3 is purely additive (new configs, new reports). If the auto-detection
produces wrong configs for a subset of machines, those machines' configs are corrected
individually. No code changes needed for most rollbacks — only config file edits.

---

## 10. Alternatives for Plugin Claim Mechanism (Supplement to §2)

The primary decision (Alternative C parse-loop restructure) is above. Here is the secondary
decision on the claim mechanism itself:

**Claim Alt-1 (Chosen): Signature-based auto-detection against first-chunk sample.**
- `ClaimSignature` evaluated once before the first chunk parse.
- Result cached in `play_type_configs/<M>/mode_<n>.json`.
- Re-evaluated on first run after cache invalidation (when per-machine config is absent or stale).

**Claim Alt-2: Lazy detection — observe all chunks, build plugin set retroactively.**
- Run parse with all plugins active; collect which ST numbers fired for which accumulators.
- After the last chunk, finalize the plugin set based on observed activity.
- Pro: no pre-scan needed; handles machines where bonus ST appears rarely.
- Con: all accumulator objects run for all robots on all chunks, even for mechanics not present.
  BCM accumulator runs on M14 (pure paid) — wasted computation. More importantly, the effective
  hash cannot be computed BEFORE the run, which breaks the staleness-check model (we need to know
  if the existing report is stale before deciding whether to re-run).
- **Rejected**: incompatible with pre-run staleness check.

**Claim Alt-3: ST-number-as-key (registry of ST numbers → plugin).**
- Build a fleet-wide census mapping (ST number → mechanic) and hard-code it.
- Pro: simple; no detection needed.
- Con: directly contradicts `DIRECTION.md §10`: "Plugin claim key = feature signature; ST = the
  resulting per-machine partition (NOT ST-number-as-key)." Engine generations use different ST
  numbers for the same mechanic (freespin = 44/126/138/157 per `DIRECTION.md §10`).
- **Rejected**: violates the signed-off model.

---

## 11. Open Questions for Wave 3 (Critic + Validator) and User Decision Summary

**Q1 (Wave 3 Critic — design risk):** The `TriggerSessionAccumulator` inside `ScatterFreespinPlugin`
must implement both Type 1 (Trigger ReMarks, last_non_none win) and Type 2 (win==0 anchor, sum_all)
families from `trigger_sessions.py`. `compute_trigger_sessions` is 230 lines (`01_pipeline_map.md §3`)
covering both families and the double-count filter. Does moving it into a single plugin create an
over-large plugin that blurs the mechanic boundary? Alternative: split into two plugins
(`RemarkTriggerPlugin` for Type 1, `WheelSelectorPlugin` for Type 2). Risk: adds a plugin for M273's
85-variant WheelSelector family as a separate plugin from M31's scatter-freespin. Ask: is the split
worth it, or is "trigger session detection" a coherent atomic unit?

**Q2 (Wave 3 Validator — byte-identical risk):** `_infer_feature_spin_type_mapping` (5 passes,
498-678 in PIA) has a "second consumer on the bonus-chain path" per `01_pipeline_map.md §8 Q1` —
but the comment doesn't name it. Before Phase 2, the validator must identify the exact second consumer
to ensure the migration of this function into the auto-detection + BCM plugin doesn't break a silent
dependency. If the second consumer is a display plugin that reads from a stash key, the stash key
must be preserved.

**Q3 (User decision — play-type vs config boundary for PT-6):** M274's `BCMListRewardPlugin` is
currently scoped to pay_id=5801 as a per-machine config anchor. If other BCM machines exist with
different `ListRewardWheel` trigger anchors (different pay_id values), should they use the SAME
plugin (with different trigger anchor in their per-machine config), or should each trigger anchor be
a distinct plugin? The proposed decision rule (§4.4) says "same plugin if control flow is identical."
The user should confirm whether the Minigame cell/lock format is consistent across all ListRewardWheel
machines, or whether format differences would require distinct plugins.

**Q4 (Wave 3 Critic — migration atomicity):** Phase 1 uses a feature flag
(`--use-play-type-plugins`). This creates a period where two code paths coexist. The validator should
confirm that the byte-identical gate reliably catches regressions in this dual-path configuration,
particularly for the BCM accumulator state handoff (the accumulator writes to the chunk dict; the old
code reads from the same keys). If key naming conflicts, the golden comparison will fail silently
(both paths produce a key, values differ).

**Q5 (Wave 3 Critic — CostCredits reliability probe):** The pre-scan probe for M10-family
(LockReSpin, CostCredits always 0) is proposed as `CostCreditsReliabilityPlugin` with a
`ClaimSignature`. But the probe currently runs on the FIRST 200 rounds of the FIRST robot
(`01_pipeline_map.md §2 Stage 1 CostCredits reliability probe`). If this becomes a plugin, it needs
to run before ANY other accumulator touches `is_paid_round`, because its result changes how `is_paid_round`
is evaluated. This ordering constraint is not captured by `MECHANIC_DEPS` (which orders emit(); the
parse-loop accumulator order may differ). Wave 3 must validate that the accumulator dispatch order
can enforce "CostCreditsPlugin runs first" before other accumulators call `is_paid_round`.

---

## 12. Out of Scope

**Explicitly NOT addressed by this proposal:**

1. **The remaining ~308 machines** (those beyond the 12 pilots). Phase 3 onboards them using the
   architecture; no new design decisions needed. Rationale: `DIRECTION.md §8` and §10.

2. **Output-level isolation** (re-flagging only when a machine's actual output changes, not when
   its plugin changes). Hash-level isolation is accepted per `DIRECTION.md §4`. Output-level
   isolation is a "later optimization" per DIRECTION.

3. **Frontend rendering changes** for new play-type output fields. The `emit()` output of new
   plugins adds new summary keys; the frontend must add display panels for them. This is an
   impl-team task, not part of this architecture proposal.

4. **Virtual analyzer compatibility** (`slot_designer/core/backend/virtual_analyzer.py`). The
   `_delegate_to_real_analyzer` path (`01_pipeline_map.md §6.2`) calls the real analyzer subprocess.
   Play-type plugins run inside the real analyzer; the virtual analyzer's delegate path is
   unaffected by plugin internals. The `_patch_summary_md5_tags` function must be extended to
   handle new top-level keys — but this is a one-line addition, not an architectural concern.

5. **`sampler.py` closure coupling** (`03_coupling_audit.md §6.5`). `sampler.py` is in
   `_CLOSURE_FILES` because PIA imports two math functions from it. Extracting those two
   functions to a pure-math module would break this coupling, but it is a standalone improvement
   unrelated to the play-type refactor. Left for a follow-on.

6. **M260 ST=105 semantics** (`02_taxonomy.md §A8 item 1`). ST=105 rounds (CostCredits=0,
   WinCredits=0, ReMarks=None) are likely transition rounds between WheelSpin and FreeSpin.
   Taxonomy confidence is MEDIUM. The architecture handles them (they would be assigned to an
   "unknown_bonus" bucket initially, triggering an onboarding alert for M260). Resolution of
   their semantics requires sequential rawdata inspection outside this architecture proposal.

7. **M99/M112 ST=97+98 sub-round dedupe** (NOT_FIXED per memory reference). The `SynthesizePayIdRule`
   for M99 double-counting is a known open bug. The new architecture does not fix it; PT-13
   (MiniGame) and PT-15 (Wheel non-BCM) plugins must carry forward the current behavior (modulo
   byte-identical) and the bug is surfaced as a correctness-fix candidate for a follow-on.

8. **`RTP_CONTRIBUTION` ClassVar on play-type plugins**. The existing RTP integrity gate reads
   `RTP_CONTRIBUTION` from each `AnalyzerFeature`. Play-type plugins that contribute to RTP
   must declare `RTP_CONTRIBUTION = True`. The gate itself (`rtp_integrity.py`) is A-class and
   stays in base; its contract with `AnalyzerFeature.RTP_CONTRIBUTION` is preserved.
   The manifest-based `required_attribution_anchors` contract (`01_pipeline_map.md §6 item 5`)
   is replaced by the auto-detected play-type set, which determines which pay_ids are expected
   to have non-zero attribution. This replacement is a design decision but its implementation
   detail is deferred to the impl-team.
