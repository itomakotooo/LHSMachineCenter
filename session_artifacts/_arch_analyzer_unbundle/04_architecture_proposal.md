# 04 — Architecture Proposal: Analyzer Unbundle (M275-driven)

> **Produced by**: arch-designer (W2)
> **Date**: 2026-05-25
> **Topic dir**: `session_artifacts/_arch_analyzer_unbundle/`
> **Inputs consumed**: 00_brief.md, 01_pipeline_map.md, 02_taxonomy.md, 03_coupling_audit.md,
>   session_artifacts/_arch/04_architecture_proposal_v5.md (predecessor plugin design),
>   session_artifacts/_arch/09_architecture_as_built.md (as-built state)
> **Next consumer**: arch-critic (W3), arch-validator (W3)

---

## §1 Executive Summary

The PIA monolith (`player_impact_analyzer.py`, ~5500 lines) produces correct RTP accounting for the 393-machine fleet but fails to correctly characterize *what* mechanics each machine has. M275 exposes this cleanly: six of eight known gaps trace to a single structural defect — **each analysis panel (machine_mechanics, collect_mechanic, bonus_chain_dynamics, upstream_feature_breakdown, payout_ids_top20, payouts_by_spin_type) independently reaches its own conclusion about machine behavior from raw fields, with no shared source of truth for mechanism identity**. The remaining two gaps (shapes/cols/paylines/notes fields, gap #7 and #8) are universal display augmentations not yet implemented.

The predecessor architecture (`04_v5.md`) correctly designed a plugin system (Protocol `AnalyzerFeature`, manifests, hash composition) and shipped most of that foundation (`09_architecture_as_built.md`). What did NOT ship: the actual carve of inline blocks F2–F9 into plugins, and any mechanism for cross-panel synthesis. The four existing feature plugins (Pattern A: no-op scaffold × 3; Pattern B: `BankruptcySimulation`) demonstrate the container but hold no meaningful analytical content for the blocks that contain the 8 gaps.

This proposal extends the as-built architecture with three specific additions:

1. **Mechanism Registry** — a single in-memory object (built once per run, persisted to summary + `mechanism_portrait.json` sidecar) that synthesizes the canonical answer to "what mechanics does this machine have" from three source tiers: raw field detection, inferred analytics panels, and manifest-declared overrides. All panels consume it, no panel re-derives it.

2. **Plugin Protocol v2** — extends the existing `AnalyzerFeature` ABC with: (a) a wired `parse_state` object carrying per-round data to `extract()`; (b) a `DECLARED_DEPS` mechanism replacing the hidden temp-key stash; (c) formal `parser_state` schema. The `extract()` call is wired at the **per-chunk merge** level (not per-round in `parse_chunk_response`) because this is the least disruptive wiring point and Pattern B plugins currently have all the data they need from `chunk_dict`.

3. **PIA Inline Carve Plan** — phased promotion of blocks F2–F9 into genuine Pattern B plugins, with a strict ordering that respects the `_st_label` / `_st_behavior` / `_bcm_bonus_feature` cross-block dependencies identified in `01_pipeline_map.md §7`.

Five concrete pain points, each cited from Wave 1:

1. **`machine_mechanics` isolation** — `total_jackpot_spins` requires raw `JackpotIds` field, which M275 never sets; its jackpots are in `PayoutIdToWinAmount`. The panel reaches "not applicable" while three other panels correctly characterize the jackpots (`01_pipeline_map.md §5 Gap #1`). **26 machines** affected across all archetypes (`02_taxonomy.md §5 Ax5`).

2. **Scatter trigger mis-classification** — pid 666 classified `cat=paid` in 99 machines using standard scatter markers because the zero-win + line_id=-1 pattern is not checked in F2's category logic (`01_pipeline_map.md §5 Gap #3`; `02_taxonomy.md §5 Ax6`).

3. **`extract()` lifecycle never wired** — the only call site is `_feature.emit(None, summary)` with `parse_state=None`; `extract()` is never invoked (`01_pipeline_map.md §6`). This means Pattern B carves for blocks that need per-round data cannot proceed without wiring `extract()` first.

4. **Hidden temp-key stash is the only inter-plugin mechanism** — `BankruptcySimulation` reads `summary["_bankruptcy_rows"]` and `summary["_bankruptcy_sim_session_spins"]` (set by PIA at line 4811 before the emit loop) without any ABC enforcement or ordering guarantee (`03_coupling_audit.md §4.3`). Promoting F5 (upstream_feature_breakdown) and F9 (collect_mechanic) to Pattern B requires the same mechanism for `_bcm_bonus_feature`/`_bcm_bonus_source`, which are computed in F5 and consumed in F9.

5. **`feature_registry.get_features_for_machine()` unused in production** — the emit loop at `pia:4830` calls `for _feature in ALL_FEATURES: _feature.emit()` unconditionally, not filtered by manifest. Adding a new feature plugin to the registry would silently run `emit()` on every machine, even those that don't declare the feature (`03_coupling_audit.md §2.2 Symbol 6`).

---

## §2 Design Alternatives

### §2.1 Alternative 1 — Deferred mechanism registry, per-block fixes only (minimal)

**Core idea**: Fix each of the 8 gaps with targeted edits to the inline blocks that produce the broken output, without restructuring the plugin system or adding a mechanism registry. Each gap is an isolated fix.

**Sketch of changes**:
- Gap #1: add cross-reference in Block F8 — `if any(int(pid) >= 10000 for pid in payout_id_win)` → set jackpot applicable.
- Gap #2: add cross-reference in Block F8 — if `bonus_chain_dynamics.applicable` is True → set free_spin applicable.
- Gap #3: add zero-win + line_id=-1 check in Block F2 category logic.
- Gap #5: add "all-zero guard" before F2b row emission.
- Gap #6: re-examine formula (per-mapper, this may already be correct per math).
- Gaps #7/#8: add shape/cols/paylines/notes enrichment to F2 and F3 output rows.
- Gap #4: out of scope (multiplier inference paused).

**Pros**:
- Minimum code delta. No new abstractions.
- No risk to hash composition or existing reports.
- Can be done without resolving the `extract()` wiring question.
- Fastest path to M275 correctness.

**Cons**:
- Does not address the root cause (independent detectors, no shared source of truth). The same pattern will recur for the next new machine.
- Does not implement the user's stated goal: "zero-code new machine" for Case-B recombinations.
- The cross-references (F8 reading `payout_id_win`, F8 reading `bonus_chain_dynamics` output) recreate exactly the coupling pattern that the plugin architecture was designed to eliminate.
- Does not close the `extract()` lifecycle gap, which blocks any future genuine Pattern B carve.
- Blast radius per `03_coupling_audit.md §5 Case Study B`: touching Block F8 changes `player_impact_analyzer.py`, flipping the legacy `analyzer_version` for all 393 machines.

**Migration cost**: LOW. Hours per gap.

**This option was proposed by**: the brief's framing implies it as the "fix only" baseline. It is rejected by the user's stated intent ("最好直接把现在的 analyzer 拆了").

---

### §2.2 Alternative 2 — Mechanism Registry + Protocol v2 + Phased Plugin Carve (recommended)

**Core idea**: Build a `MechanismRegistry` object that is populated once per run and passed through the pipeline. Extend `AnalyzerFeature` ABC with wired `extract()` at the per-chunk merge level. Carve F2–F9 into Pattern B plugins in phases, using `MechanismRegistry` as the shared source of truth. Close all 8 gaps as part of the carve.

**Key file structure sketch**:

```
fresh_slotlab/
  analyzer/
    core/
      __init__.py
      _utils.py
      aggregator.py
      base_pipeline.py
      parser.py
      writer.py
      mechanism_registry.py      ← NEW: single source of truth
    features/
      _base.py                   ← EXTENDED: extract() wired, DECLARED_DEPS, parse_state
      feature_registry.py        ← FIXED: emit loop uses get_features_for_machine()
      payouts_by_spin_type.py    ← PROMOTED: Pattern A → B (gaps #7, #8 enrichment)
      reel_marginal_by_spin_type.py ← stays Pattern A (no behavior change)
      multiplier_profile.py      ← stays Pattern A (no behavior change)
      bankruptcy_simulation.py   ← Pattern B (no change, already works)
      payout_id_panel.py         ← NEW Pattern B: F2 + F2b (gaps #3, #5, #8)
      payouts_by_spin_type.py    ← PROMOTED: F3 (gap #7, #8 enrichment)
      machine_mechanics.py       ← NEW Pattern B: F8 (gaps #1, #2)
      collect_mechanic.py        ← NEW Pattern B: F9
      upstream_feature.py        ← NEW Pattern B: F5
      bonus_chain_dynamics.py    ← NEW Pattern B: F6
    manifest_loader.py
    versioning.py
    feature_registry.py
    rtp_integrity.py
  mechanism_portrait.py          ← NEW: persistence + operator surface
  player_impact_analyzer.py      ← SLIMMED: inline F2–F9 removed
```

**Key interface sketches**:

```python
# fresh_slotlab/analyzer/core/mechanism_registry.py

class MechanismRegistry:
    """Single source of truth for 'what mechanics does this machine have'.
    Built once per run from three tiers. Consumed by all plugins."""

    # Populated during run
    jackpot_pid_set: frozenset[str]   # pids with win ≥ 10000
    scatter_marker_pids: frozenset[str]  # pids where win==0 AND line_id==-1
    freespin_applicable: bool
    bcm_applicable: bool
    freespin_st_set: frozenset[int]
    paid_st_set: frozenset[int]
    bcm_cycle_length: int | None
    bcm_bonus_feature: str | None
    bcm_bonus_source: str | None

    # Detection tier that set each field (for auditability)
    _detection_source: dict[str, str]  # field_name → "raw"|"inferred"|"manifest"

    def build(
        self,
        *,
        payout_id_win: dict,        # from accumulator
        payout_id_hits: dict,       # from accumulator
        payline_records: dict,      # from accumulator (for scatter detection)
        bonus_chain_result: dict,   # from intermediate
        upstream_feature_tally: dict,  # from accumulator
        all_cycle_peaks: list,      # from accumulator
        spin_type_spins: dict,      # from accumulator
        manifest: dict,             # from manifest_loader
    ) -> "MechanismRegistry": ...

    def to_summary_dict(self) -> dict:
        """Produces the machine_mechanics summary key."""
        ...

    def to_portrait_dict(self) -> dict:
        """Full persistence surface including detection_source audit."""
        ...
```

```python
# fresh_slotlab/analyzer/features/_base.py  (extended)

class AnalyzerFeature(ABC):
    FEATURE_ID: ClassVar[str] = ""
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ()
    SCHEMA_VERSION: ClassVar[int] = 1
    REQUIRES: ClassVar[tuple[str, ...]] = ()      # feature IDs this plugin depends on
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()  # summary temp-keys this plugin reads
    RTP_CONTRIBUTION: ClassVar[bool] = False
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    @abstractmethod
    def extract(self, parse_state: "ParseState | None", chunk_dict: dict) -> dict:
        """Called once per chunk in the merge loop.
        parse_state carries the chunk-level MechanismRegistry (once built)
        and any other chunk-level context a plugin needs."""
        ...

    @abstractmethod
    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Merge two extract() outputs across chunks."""
        ...

    @abstractmethod
    def emit(self, final_acc: dict, summary: dict) -> None:
        """Called once after all chunks. Writes to summary.
        Must not read summary keys not declared in DECLARED_DEPS."""
        ...
```

```python
# fresh_slotlab/analyzer/features/_base.py  (ParseState schema)

class ParseState:
    """Per-chunk context passed to extract().
    Built once per chunk from the merged rec dict and MechanismRegistry.
    Plugins MUST only read fields documented here; other fields may vanish."""
    chunk_dict: dict               # the full rec dict from parse_chunk_response
    mechanism_registry: "MechanismRegistry | None"  # None until registry is built
    machine_id: str
    mode: int
    manifest: dict
```

**Pros (grounded in Wave 1)**:
- Closes all 8 gaps as part of the carve — each gap is owned by a specific plugin.
- The mechanism registry is the single source of truth that eliminates the root cause of gaps #1, #2, #3: `01_pipeline_map.md §5` documents all three as "independent detector reads different raw field than the other panels that already have the correct answer."
- Surgical hash invalidation: new feature file → only machines declaring that feature flip `effective_analyzer_version` (`03_coupling_audit.md §3.3`).
- The `DECLARED_DEPS` mechanism replaces the hidden temp-key stash identified as a fragility in `03_coupling_audit.md §4.3` — it makes ordering contracts explicit and machine-checkable.
- Fixing the emit loop to use `get_features_for_machine()` closes the `03_coupling_audit.md §2.2 Symbol 6` silent-wrong-result risk immediately.
- `mechanism_portrait.json` sidecar answers the user's stated need for "auto-inference persistence" without changing the main summary schema.

**Cons**:
- Adding `mechanism_registry.py` to `core/` triggers `compute_base_analyzer_version` flip → all 393 machines' `effective_analyzer_version` changes, all 275 existing reports become "historical" (03_coupling_audit.md §5 Case Study A). This is a one-time fleet-wide invalidation that cannot be avoided if the registry lives in `core/`. The alternative (putting it in `analyzer/` not `core/`) avoids this; see §8 for the resolution.
- Protocol v2 `extract()` wiring requires coordinating the call site in PIA's merge loop and the `ParseState` object construction — two changes to PIA, but neither is a schema change.
- Phased carve of F2–F9 creates a transition period where inline blocks coexist with Pattern B plugins. The ordering constraint is: inline blocks must be removed atomically with the plugin's Pattern B promotion, not left alongside (double-write risk per `03_coupling_audit.md §5 Case Study B`).

**Migration cost**: MEDIUM. Approximately 3 phased releases.

---

### §2.3 Alternative 3 — Per-chunk `extract()` wiring only, mechanism registry deferred (intermediate)

**Core idea**: Wire `extract()` at the per-chunk merge level as Protocol v2 requires. Do not build the mechanism registry or carve the inline blocks yet. This unblocks future Pattern B carves without doing the full carve now.

**Pros**:
- Low risk. The wiring change touches PIA's merge loop but does not change any output key.
- Unlocks phased carve in follow-on passes.

**Cons**:
- Does not close any of the 8 gaps. M275's problems persist.
- Does not deliver "zero-code new machine" property.
- Creates an intermediate state that must be followed by Alternative 2's carve. No standalone value.

**This option is rejected**: the brief explicitly states M275 as the driving case and requires gap closure. Alternative 3 delivers none of that.

---

## §3 Recommended Option

**Alternative 2 — Mechanism Registry + Protocol v2 + Phased Plugin Carve.**

**Reasoning against predictable critic objections**:

**Objection: "Adding mechanism_registry.py to core/ invalidates 393 machines at once."**
Response: Place `mechanism_registry.py` in `fresh_slotlab/analyzer/` (not `core/`). Per `03_coupling_audit.md §2.1`, only files inside `fresh_slotlab/analyzer/core/*.py` feed `compute_base_analyzer_version`. A file in `fresh_slotlab/analyzer/` does not change the base hash. The registry is then imported by the plugin files that need it; changes to the registry file flip the hash of those plugins, not of base. This means the invalidation is scoped to machines declaring the plugins that import the registry.

**Objection: "The cross-block dependency (_st_label, _bcm_bonus_feature) breaks the plugin ordering."**
Response: `_st_label` and `_st_behavior` can be reconstructed from `spin_type_breakdown` (which Block F1 writes to summary). No plugin needs to re-derive them from raw accumulators — they can read the already-computed `spin_type_breakdown` from summary at emit time. The `_bcm_bonus_feature` and `_bcm_bonus_source` computed in F5 and needed by F9 are handled via `DECLARED_DEPS` (see §4). The `collect_mechanic` plugin declares `DECLARED_DEPS = ("_bcm_bonus_feature", "_bcm_bonus_source")` and PIA's emit-loop runner validates those keys are present before calling emit.

**Objection: "The mechanism registry can't be built before chunks are merged, but plugins need it during extract()."**
Response: Correct. The mechanism registry is built once during finalization (after all chunks are merged), not during chunk parsing. `extract()` at the per-chunk merge level receives `parse_state.mechanism_registry = None` during chunk processing. The registry is only available during `emit()`. This is the correct and safe design — plugins that need the registry to write their output access it in `emit()` via `final_acc` or `summary["_mechanism_registry"]`. The `ParseState` contract makes this explicit (no false promise that the registry is available during extract).

**Objection: "The emit loop must use get_features_for_machine() but manifests today all declare the same 4 features."**
Response: True for today. The fix is still necessary because the brief's goal is to add new feature plugins (machine_mechanics, collect_mechanic, etc.) that not every machine should run. If the emit loop stays unfiltered, every new plugin runs on every machine, which is incorrect once feature sets diverge. The fix is surgical (one line change at `pia:4830`) and backward-compatible: `get_features_for_machine(manifest)` returns the same 4 features for today's machines and does not change `effective_analyzer_version`.

**Objection: "Manifests for 96% of BCM machines are unreviewed — adding new analyzer_features fields to M275.json without reviewing others creates asymmetry."**
Response: The asymmetry already exists: M275 is the driving case and must be corrected. The proposal does not require reviewing all 57 BCM machines before fixing M275. The manifest for M275 is updated to declare the new plugins; the existing 253 machines keep declaring the existing 4 features; their `effective_analyzer_version` is unaffected. Per `03_coupling_audit.md §3.3`, adding a feature to M275's manifest changes only M275's version hash.

---

## §4 Plugin Protocol v2

### §4.1 `AnalyzerFeature` ABC extensions

The following extends the existing `_base.py` without breaking the 4 current plugins. All existing plugins continue to work: `extract()` still defaults to returning `{}`, `reduce()` defaults to returning `this_acc`, `emit(None, summary)` is still the fallback call signature.

```python
# fresh_slotlab/analyzer/features/_base.py  (EXTENDED SECTION — additions only)

from dataclasses import dataclass, field
from typing import ClassVar, Any

@dataclass
class ParseState:
    """Per-chunk context object passed to extract().
    
    SCHEMA CONTRACT (Wave 2 stable):
    - chunk_dict: full rec dict from parse_chunk_response(). All ~80 keys accessible.
      Guaranteed keys: ok, index, spins, bet, win, payout_id_hits, payout_id_win,
      payout_id_by_spin_type, payout_id_win_by_spin_type, spin_type_spins,
      spin_type_win, spin_type_paid_bet, symbol_counts, symbol_counts_by_col_by_spin_type,
      payline_hits, payline_win_approx, payline_winning_symbols, collect_count_total,
      cycle_peaks, final_cc_values, completed_cycles, upstream_feature_tally,
      bonus_chain_lengths, bonus_chain_max_ratios, jackpot_spins, jackpot_ids_seen,
      freespin_chain_spins, freespin_retriggers, bankruptcy_reps.
    - machine_id: str, mode: int, manifest: dict (resolved, with per_mode applied)
    - mechanism_registry: MechanismRegistry | None
      None during per-chunk extract() calls.
      Populated only after finalization (for emit()-time access via final_acc).
    
    Plugins MUST NOT rely on chunk_dict keys not listed above without checking
    for their presence — field_discovery keys may be absent for some machines.
    """
    chunk_dict: dict
    machine_id: str
    mode: int
    manifest: dict
    mechanism_registry: Any = None  # MechanismRegistry | None


class AnalyzerFeature(ABC):
    FEATURE_ID: ClassVar[str] = ""
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ()
    SCHEMA_VERSION: ClassVar[int] = 1
    REQUIRES: ClassVar[tuple[str, ...]] = ()
    # NEW in Protocol v2:
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    # DECLARED_DEPS: tuple of summary temp-key names this plugin reads in emit().
    # The emit-loop runner validates all declared deps are present before calling emit().
    # Example: BankruptcySimulation.DECLARED_DEPS = ("_bankruptcy_rows",
    #                                                  "_bankruptcy_sim_session_spins")
    # Example: CollectMechanicFeature.DECLARED_DEPS = ("_bcm_bonus_feature",
    #                                                    "_bcm_bonus_source")
    RTP_CONTRIBUTION: ClassVar[bool] = False
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    @abstractmethod
    def extract(self, parse_state: ParseState, chunk_dict: dict) -> dict:
        """Called once per chunk during merge loop.
        Accumulates plugin-private state from the chunk record.
        Return dict is passed as prev_acc to reduce() on next chunk.
        Default implementation: return {} (backward compat for Pattern A)."""
        return {}

    @abstractmethod
    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Merge two extract() outputs across chunks.
        Default: return {**prev_acc, **this_acc} (accumulate)."""
        return {**prev_acc, **this_acc}

    @abstractmethod
    def emit(self, final_acc: dict, summary: dict) -> None:
        """Called once after all chunks. Writes plugin output to summary.
        final_acc is the result of reduce() across all chunks.
        Reads summary keys only if declared in DECLARED_DEPS.
        Must not read undeclared summary keys (ordering is not guaranteed)."""
        ...
```

### §4.2 Wiring `extract()` in PIA's merge loop

The call site for `extract()` is in PIA's chunk merge loop. The from-cache path and online path share the same merge logic (per `01_pipeline_map.md §3`). The wiring is:

```python
# player_impact_analyzer.py — merge loop (both from-cache and online paths)
# CURRENT (pia:4831 equivalent for emit; no extract call exists):
#   for _feature in ALL_FEATURES:
#       _feature.emit(None, summary)
#
# NEW — in the merge block body (once per chunk), BEFORE existing accumulator merge:

parse_state = ParseState(
    chunk_dict=rec,
    machine_id=args.machine,
    mode=args.rtp_mode,
    manifest=manifest,
    mechanism_registry=None,  # not yet built
)
_machine_features = get_features_for_machine(manifest)  # filtered by manifest
_feature_accs = {}  # {fid: acc_dict}
for _feature in _machine_features:
    _prev = _feature_accs.get(_feature.FEATURE_ID, {})
    _this = _feature.extract(parse_state, rec)
    _feature_accs[_feature.FEATURE_ID] = _feature.reduce(_prev, _this)

# ... existing accumulator merge continues unchanged ...
```

And in the finalization block, after building the mechanism registry and before writing summary:

```python
# NEW — emit loop with dep validation and mechanism_registry injection
mechanism_registry = _build_mechanism_registry(...)  # see §5
summary["_mechanism_registry"] = mechanism_registry  # available to plugins via DECLARED_DEPS

_machine_features = get_features_for_machine(manifest)  # same filtered list
for _feature in _machine_features:
    # Validate DECLARED_DEPS are present
    for dep_key in _feature.DECLARED_DEPS:
        if dep_key not in summary:
            raise RuntimeError(
                f"Feature {_feature.FEATURE_ID} declared dep '{dep_key}' "
                f"but it is not in summary. Check ordering or plugin declaration."
            )
    _feature.emit(_feature_accs.get(_feature.FEATURE_ID, {}), summary)

# Clean up temp keys after all plugins have emitted
for _key in list(summary):
    if _key.startswith("_"):
        del summary[_key]
```

**Important**: the emit loop now uses `get_features_for_machine(manifest)` (filtered) not `ALL_FEATURES` (unfiltered). This closes `03_coupling_audit.md §2.2 Symbol 6` risk.

**Backward compat for BankruptcySimulation**: The existing temp-key stash (`summary["_bankruptcy_rows"]`) continues to work unchanged — it is now a formally declared dep (`DECLARED_DEPS = ("_bankruptcy_rows", "_bankruptcy_sim_session_spins")`). The dep validation ensures ordering. No behavior change for existing machinery.

### §4.3 Error handling

- `extract()` errors: log + return `{}`. Per-chunk extract errors must not crash the run.
- `reduce()` errors: log + return `prev_acc` (keep prior state, skip broken chunk contribution).
- `emit()` errors: log + set `summary["_feature_errors"][fid] = str(e)`. Do not crash. Pattern A `assert` statements in existing plugins are replaced with log-and-continue.
- Dep validation failure: raise RuntimeError at startup (plugin declared dep that is not set by anything). This is a programming error, not a runtime data error.

### §4.4 `SCHEMA_VERSION` semantics (unchanged from v5 §5.4)

Each plugin increments its own `SCHEMA_VERSION` when the shape of its summary key changes. Old reports (lower schema version) have `REGISTERED_FALLBACK_RULES` applied when read by the frontend renderer. Backend does not apply fallback rules — it serves the summary as-is.

---

## §5 Mechanism Registry Design

### §5.1 Single source of truth rationale

Per `01_pipeline_map.md §5 Gap #1 and #2`: both gaps trace to Block F8 using `total_jackpot_spins` and `total_freespin_chain_spins` as its sole detection signal. These counters are zero for M275 because M275 uses `PayoutIdToWinAmount` (not `JackpotIds`) for jackpot delivery and uses SpinType+ReMarks (not `CurFreeSpin`) for freespin signaling. Three other panels independently arrive at the correct answer, but Block F8 cannot see their conclusions.

The mechanism registry is the canonical authority. It is built once, after all chunk accumulators are merged, and then:
- `machine_mechanics` plugin reads it to write the `machine_mechanics` summary key (no more independent detection in F8).
- `payout_id_panel` plugin reads it to classify pid 666 as `scatter_trigger` (Gap #3).
- `collect_mechanic` plugin reads it for `bcm_bonus_feature`.
- `upstream_feature` plugin reads it instead of calling `_resolve_bonus_feature()` independently.

### §5.2 Detection sources and precedence

Three source tiers, applied in priority order (highest to lowest):

**Tier 1 — Manifest-declared overrides** (highest precedence):
Fields in `manifest["mechanism_overrides"]` (new optional manifest field). Example: if a machine's jackpot PIDs are known but not yet appearing in rawdata (early sampling), the operator can declare them. Precedence ensures manifest intent wins over inference.

```json
{
  "mechanism_overrides": {
    "jackpot_pid_set": ["27502", "27503", "27504"],
    "scatter_marker_pids": ["666"],
    "bcm_cycle_length": 1000,
    "freespin_applicable": true
  }
}
```

**Tier 2 — Inferred analytics** (second precedence):
Results from `upstream_feature_breakdown` construction (F5), `bonus_chain_dynamics` (F6), and the `collect_mechanic` cycle-peak inference (F9). These panels already have the correct answer per `01_pipeline_map.md §5 Gap #2` (bonus_chain_dynamics.applicable: True correctly identifies 9090 freespin rounds).

**Tier 3 — Raw field detection** (lowest precedence):
The existing accumulators: `payout_id_win` (jackpot via ≥10000 PID threshold), `payline_records` scatter pattern (line_id=-1 + win=0), `spin_type_spins` freespin-named-ST detection, `total_jackpot_spins` (raw `JackpotIds` field). These are the current Block F8 inputs — they remain as fallbacks but no longer have sole authority.

**Precedence rule**: if Tier 1 declares a field, use it. Else if Tier 2 has evidence, use it. Else fall through to Tier 3. The `_detection_source` dict records which tier produced each field for operator auditability.

**Threshold definitions** (measurable, per `02_taxonomy.md §3`):
- Jackpot PID: any observed PID in `payout_id_win` where `int(pid) >= 10000`. This is directly measurable from rawdata and covers all 26 fleet machines with jackpot PIDs identified in `02_taxonomy.md §5 Ax5`.
- Scatter marker: any PID in `PayoutByPayline` where the payline entry has `line_id == -1` AND the PID's total win is 0 across all observed rounds. Covers 99 machines with pid=666 and 50 with other scatter PIDs per `02_taxonomy.md §3 Ax6`.
- Freespin applicable: `bonus_chain_dynamics.chain_count > 0` (Tier 2) OR any SpinType in rawdata whose ReMarks contain "Freespin" (Tier 2 raw, parsed by parser.py) OR `total_freespin_chain_spins > 0` (Tier 3).
- Group 0 meaningless (Gap #5): if `max(payout_group_win.keys()) == 0` AND count of distinct non-zero `PayoutGroupId` values in raw == 0, then `payout_groups_applicable = False`. This covers ~247 of 256 machines per `02_taxonomy.md §11 Seam 6`.

### §5.3 Consumer API

```python
# Usage in any plugin's emit():
registry = summary.get("_mechanism_registry")  # declared via DECLARED_DEPS

# Check jackpot
if registry.jackpot_pid_set:
    # jackpot applicable; use registry.jackpot_pid_set as authoritative PID list

# Check freespin
if registry.freespin_applicable:
    # free_spin applicable

# Check scatter trigger for a pid
if pid in registry.scatter_marker_pids:
    category = "scatter_trigger"
    trigger_only = True

# Check payout groups
if not registry.payout_groups_applicable:
    # suppress or label the payout_groups panel
```

### §5.4 Persistence

The registry persists in two places:

1. **In the summary dict** (embedded): the existing `machine_mechanics` key is replaced by the registry's `to_summary_dict()` output. This is a schema-compatible change — the same top-level fields (`jackpot`, `free_spin`, `lock_lines`, etc.) are written, but now also with correct values.

2. **`mechanism_portrait.json` sidecar** (new, operator-visible): written alongside `player_impact_summary.json` in `reports/<M>/mode_<N>/versions/<rv>/`. Contains the full `to_portrait_dict()` output including `_detection_source`, inferred parameters (cycle length, freespin ST set, jackpot PID set, scatter marker PIDs, etc.). This is the "auto-inference persistence" surface the brief requires.

```json
{
  "_schema_version": 1,
  "_built_at": "2026-05-25T12:00:00Z",
  "machine_id": "M275",
  "mode": 1,
  "jackpot": {
    "applicable": true,
    "pid_set": ["27502", "27503", "27504"],
    "total_rtp_pp": 5.52,
    "_detection_source": "tier2_inferred"
  },
  "free_spin": {
    "applicable": true,
    "freespin_st_set": [126],
    "chain_count": 908,
    "avg_chain_length": 10.01,
    "_detection_source": "tier2_inferred"
  },
  "bcm": {
    "applicable": true,
    "cycle_length": 1000,
    "bonus_feature": "NewFreespin",
    "_detection_source": "tier2_inferred"
  },
  "scatter_triggers": {
    "applicable": true,
    "marker_pids": ["666"],
    "_detection_source": "tier3_raw"
  },
  "payout_groups": {
    "applicable": false,
    "reason": "all_zero_sentinel",
    "_detection_source": "tier3_raw"
  },
  "multiplier_wilds": {
    "applicable": "paused",
    "reason": "multiplier_inference_paused_per_memory_project_paytable_inference_paused"
  }
}
```

The sidecar is written by `mechanism_portrait.py` (new module), called from PIA's write phase after `write_summary_json()`. It does not feed into `effective_analyzer_version` — it is a derived artifact, not an input to analysis.

---

## §6 Auto-Inference Persistence

The `mechanism_portrait.json` sidecar (§5.4) is the primary operator-visible surface. Beyond it:

**Manifest cross-validation**: after a run produces a portrait sidecar, `manifest_loader.py` can optionally cross-validate the inferred values against manifest-declared values and emit warnings where they diverge. Example: manifest declares `spin_type_convention.paid = [1]` but portrait says `paid_st_set = {140}` → emit warning "manifest declares paid ST=[1] but rawdata shows ST=140 is the dominant paid round; update manifest." This warning surface is part of the manifest review workflow for the 182 unreviewed machines.

**Per-run persistence location**:
```
reports/M275/mode_1/versions/rv_20260525T.../
  player_impact_summary.json    # existing
  mechanism_portrait.json       # NEW sidecar
```

**Per-machine latest-portrait pointer**: `reports/M275/mode_1/latest_portrait.json` (symlink or pointer file) — optional Phase 3 addition, deferred. Operators can view the latest portrait by navigating to the run directory.

**Inferred parameters visible in portrait**:
- BCM cycle length (inferred from `detect_cycle_peak`, or manifest override)
- Jackpot PID set (inferred from PID ≥ 10000 in payout_id_win)
- Freespin chain length distribution (inferred from bonus_chain_dynamics)
- Scatter marker PID set (inferred from payline_records line_id=-1 + win=0)
- Multiplier wild values (paused — portrait shows `"applicable": "paused"`)
- BCM bonus feature name (inferred from `_resolve_bonus_feature` / BCM pairings)
- Dominant paid ST (inferred from spin_type_spins most-common ST)

The portrait is NOT an input to the analyzer hash. If the portrait file is deleted, the next run regenerates it from scratch — it is purely a derived output.

---

## §7 PIA Inline Carve Plan

### §7.1 Ordering constraint

The cross-block dependencies from `01_pipeline_map.md §7` impose a strict ordering:

```
F1 (spin_type_rows, _st_behavior, _st_label) must run before F2, F3, F4
F5 (_bcm_bonus_feature) must run before F9 (collect_mechanic)
MechanismRegistry must be built before machine_mechanics plugin emit()
```

This ordering is enforced by the PIA emit-loop runner via `REQUIRES` and `DECLARED_DEPS`. Since F1 writes `spin_type_breakdown` to `summary["player_impact"]["spin_type_breakdown"]`, F2/F3/F4 plugins can reconstruct `_st_label` from that key at emit time. The DECLARED_DEPS pattern handles F5→F9.

### §7.2 Phase breakdown

#### Phase C1 — Mechanism Registry + emit loop fix (prerequisite, no gap closure yet)

**Deliverables**:
1. `fresh_slotlab/analyzer/mechanism_registry.py` — `MechanismRegistry` class, `_build_mechanism_registry()` builder function. Located in `fresh_slotlab/analyzer/` (not `core/`) to avoid base-hash invalidation (see §8).
2. `feature_registry.py` fix: emit loop uses `get_features_for_machine(manifest)` instead of `ALL_FEATURES`.
3. `_base.py` extension: add `ParseState` dataclass, `DECLARED_DEPS` ClassVar, update call site in PIA merge loop to call `extract()` with `ParseState`.
4. `BankruptcySimulation` updated: add `DECLARED_DEPS = ("_bankruptcy_rows", "_bankruptcy_sim_session_spins")`. No behavior change.
5. All 4 existing plugins: replace `emit(None, summary)` call signature handling with `emit(final_acc, summary)` where `final_acc` is the accumulated dict from extract/reduce. For Pattern A plugins, `final_acc = {}` by default.
6. `mechanism_portrait.py` writer — writes sidecar after summary write.

**Backward-compat during C1**: 
- The 4 existing Pattern A plugins assert their key is in summary — these assertions remain. No output changes.
- `BankruptcySimulation` behavior unchanged — DECLARED_DEPS enforces what was previously implicit.
- `effective_analyzer_version` changes: changing `_base.py` changes the hash of all 4 plugin files (since `compute_hash()` hashes the plugin's own file — but NOT `_base.py`, which is imported not hashed directly). Wait — per `03_coupling_audit.md §2.1 Symbol 4`, `compute_hash()` hashes `cls.__module__.__file__`, which is the plugin's own `.py` file. Changes to `_base.py` do NOT change any plugin's hash (the plugin file itself is unchanged). **No version invalidation from C1's `_base.py` changes.** The emit loop fix in `feature_registry.py` does not affect any plugin hash. The PIA merge loop wiring changes PIA's own file → legacy `analyzer_version` flips → all 393 reports appear stale in the legacy field (expected and acceptable; this is the broad legacy hash). The `effective_analyzer_version` is unaffected.

**Rollback**: Revert the 5 PIA merge loop lines that call `extract()`. The emit loop reverts to `for _feature in ALL_FEATURES: _feature.emit(None, summary)`. The `DECLARED_DEPS` validation is then dead code but harmless.

**Expected `effective_version` delta count**: 0 (no plugin source files change, no manifest changes).

---

#### Phase C2 — Gap #3 + Gap #5 fix: `payout_id_panel` Pattern B plugin

**Inline blocks targeted**: Block F2 (`payout_id_rows`, `pia:3224-3290`) + Block F2b (`payout_group_rows`, `pia:3430-3445`).

**Deliverables**:
1. `features/payout_id_panel.py` — new Pattern B plugin with `FEATURE_ID = "payout_id_panel"`.
   - `emit()`: rebuilds `payout_ids_top20` and `payout_groups_top20` from accumulators available in `summary` (via DECLARED_DEPS for the accumulator snapshot).
   - **Gap #3 fix**: in the pid category logic, adds: `if str(pid) in registry.scatter_marker_pids: category = "scatter_trigger"; trigger_only = True`.
   - **Gap #5 fix**: if `not registry.payout_groups_applicable`, writes `payout_groups_top20 = []` with a `"suppressed": "all_zero_sentinel"` note.
   - **Gap #8 partial**: adds `notes` field to rows (e.g., "scatter trigger" for marker PIDs; "jackpot" for PIDs in registry.jackpot_pid_set).
2. Block F2 and F2b inline code in PIA is removed (replaced by the plugin).
3. M275 manifest updated: `analyzer_features` adds `"payout_id_panel"`.
4. All other manifests: `"payout_id_panel"` is added to the default feature set (all 253 non-variant manifests). Since all machines currently have all 4 features, and `payout_id_panel` replaces inline code that was running for all machines anyway, this is correct — it must run for all machines.

**Backward-compat during C2**:
- Old reports have `payout_ids_top20` produced by inline code. New reports have `payout_ids_top20` produced by the plugin. The output schema is identical (same field names). Existing field names are not renamed.
- The plugin adds new fields (`notes`, `trigger_only`) — these are additive. Old reports do not have them; frontend renders them if present, ignores if absent.
- `payout_groups_top20` for machines with actual non-zero groups (9 machines per `02_taxonomy.md §11 Seam 6`) continues to work — only the all-zero case is suppressed.

**Rollback**: Restore Block F2 and F2b inline code, remove plugin file, revert M275 manifest feature list.

**Expected `effective_version` delta count**: 254 (M275 + 253 others; the new plugin is declared by all non-variant machines; their feature hashes change with the new plugin file).

---

#### Phase C3 — Gaps #7 + #8 shape enrichment: `payouts_by_spin_type` Pattern A → B

**Inline blocks targeted**: Block F3 (`payouts_by_spin_type`, `pia:3306-3349`).

**Deliverables**:
1. Promote `features/payouts_by_spin_type.py` from Pattern A to Pattern B.
   - `emit()`: rebuilds `payouts_by_spin_type` from accumulators. Adds `shape`, `cols`, `paylines`, `notes` fields.
   - **Gap #7 fix**: `paylines` is derived from `payline_winning_symbols_rln` (keyed by pid in the accumulator at `parser.py:2104`). `shape` is the payline pattern string. `cols` is the list of reel columns active for this pid. `notes` includes "scatter trigger" for marker PIDs and "jackpot" for jackpot PIDs.
   - Reads `_st_label` by reconstructing it from `summary["player_impact"]["spin_type_breakdown"]` (avoids DECLARED_DEPS on a temp key that no longer exists post-C1).
2. Block F3 inline code in PIA is removed.
3. **Gap #8**: the same `notes`, `paylines`, `cols`, `shape` fields are added to `payout_ids_top20` rows by the Phase C2 `payout_id_panel` plugin (which also has access to payline records).

**Backward-compat during C3**:
- Old `payouts_by_spin_type` rows have 6 fields. New rows have 6 + 4 = 10 fields. Additive.
- The Pattern A `emit()` assertion (`assert "payouts_by_spin_type" in player_impact`) is removed.
- SCHEMA_VERSION bumps from 1 to 2 for this plugin.
- `REGISTERED_FALLBACK_RULES = {1: {"missing_fields": ["shape", "cols", "paylines", "notes"]}}` — old reports with schema version 1 are flagged as missing enrichment fields.

**Expected `effective_version` delta count**: 253 (all machines declaring this feature).

---

#### Phase C4 — Gaps #1 + #2: `machine_mechanics` Pattern B plugin

**Inline blocks targeted**: Block F8 (`machine_mechanics`, `pia:4457-4510`).

**Deliverables**:
1. `features/machine_mechanics.py` — new Pattern B plugin with `FEATURE_ID = "machine_mechanics"`.
   - `DECLARED_DEPS = ("_mechanism_registry",)`
   - `emit()`: reads `summary["_mechanism_registry"]` → writes `machine_mechanics` summary key.
   - **Gap #1 fix**: `machine_mechanics.jackpot.applicable = bool(registry.jackpot_pid_set)` instead of `total_jackpot_spins > 0`.
   - **Gap #2 fix**: `machine_mechanics.free_spin.applicable = registry.freespin_applicable` instead of `total_freespin_chain_spins > 0`.
   - All other sub-fields (lock_lines, lock_symbols, lock_reels, dollar_pick) continue from their existing accumulators unchanged.
2. Block F8 inline code in PIA is removed.
3. M275 manifest adds `"machine_mechanics"` to `analyzer_features`.
4. All 253 non-variant manifests add `"machine_mechanics"`.

**Note on Gap #6 (BCM correction formula)**: Per `01_pipeline_map.md §5 Gap #6`, the mapper's analysis suggests this may not be a formula bug but a correct 0.0 output given `robots_with_pending_cycle: 0`. The architecture does not fix this in Phase C4; it flags it as an open question (§15 Q1). The MechanismRegistry will surface `robots_with_pending_cycle` in the portrait, making it operator-visible. If the formula is incorrect, it is fixed in the `collect_mechanic` plugin (see Phase C5).

**Expected `effective_version` delta count**: 254 (M275 + 253 others).

---

#### Phase C5 — `collect_mechanic` and `upstream_feature` Pattern B plugins (BCM family fixes)

**Inline blocks targeted**: Block F5 (`upstream_feature_breakdown`, `pia:3431-3872`) + Block F9 (`collect_mechanic`, `pia:4608-4732`).

**Deliverables**:
1. `features/upstream_feature.py` — Pattern B plugin. Absorbs Block F5's 440-line block. Writes `upstream_feature_breakdown` to `summary["player_impact"]`. Sets `summary["_bcm_bonus_feature"]` and `summary["_bcm_bonus_source"]` as DECLARED_DEPS outputs for Phase C5b.
2. `features/collect_mechanic.py` — Pattern B plugin. Absorbs Block F9. `DECLARED_DEPS = ("_bcm_bonus_feature", "_bcm_bonus_source", "_mechanism_registry")`. Writes `summary["collect_mechanic"]` (top-level key, not under `player_impact`).
3. The three calls to `_resolve_bonus_feature()` and `_load_bcm_pairings()` (noted as called three times in `01_pipeline_map.md §8 Duplication finding 2`) are consolidated: computed once in `upstream_feature.py`'s `emit()`, stashed as DECLARED_DEPS for `collect_mechanic.py`.
4. Block F5 and F9 inline code in PIA is removed.

**Ordering enforcement**: The emit-loop runner must call `upstream_feature` before `collect_mechanic`. The `REQUIRES = ("upstream_feature",)` ClassVar in `CollectMechanicFeature` declares this; the runner enforces topological order.

**Expected `effective_version` delta count**: 254 (all manifests; these are universal features).

---

#### Phase C6 — `bonus_chain_dynamics` Pattern B plugin

**Inline blocks targeted**: Block F6 (`bonus_chain_dynamics`, `pia:3874-3962`).

**Deliverables**:
1. `features/bonus_chain_dynamics.py` — Pattern B plugin. Absorbs Block F6. Writes `bonus_chain_dynamics` to `summary["player_impact"]`.
2. Block F6 inline code in PIA is removed.

**Expected `effective_version` delta count**: 254.

---

### §7.3 Post-carve PIA state

After C1 through C6, `player_impact_analyzer.py`'s finalization block (currently lines 3155-4924) reduces to:
- Block F1: `spin_type_rows` + `_st_behavior` (stays inline; produces `spin_type_breakdown` which plugins read)
- Block F4: `reel_marginal_by_spin_type` (stays inline or moves to existing Pattern A plugin; no behavior change needed)
- Block F7: streaks / bankruptcy finalization (stays inline; sets `_bankruptcy_rows` DECLARED_DEP for BankruptcySimulation)
- `_build_mechanism_registry()` call (new, in finalization)
- Plugin emit loop (new, replaces current ad-hoc loop)
- RTP integrity gate (unchanged)
- Write phase (unchanged)

The merge loop itself is unchanged in structure; it gains the per-chunk `extract()` calls.

---

## §8 Hash Composition

### §8.1 Does the algorithm change?

**No.** The existing `compute_effective_analyzer_version` algorithm (`versioning.py:202`) is unchanged:
```
h = sha256(base_hash)
for fid in sorted(set(machine_features)):
    h.update(b"\x00" + fid.encode() + b"=" + feature_hashes[fid].encode())
h.update(b"\x00mode=" + str(mode).encode())
return h.hexdigest()[:12]
```

Per `03_coupling_audit.md §3.3`, this algorithm is `behavior-stable` and works correctly for the proposed additions.

### §8.2 New dimensions introduced

One new optional dimension: `mechanism_portrait_hash`.

When a manifest declares `mechanism_overrides` (new optional field, §5.2 Tier 1), those override values are operator-supplied inputs that affect analysis output. They must be included in `effective_analyzer_version` so that changing an override (e.g., correcting an incorrectly declared jackpot PID) triggers re-analysis.

**Proposed extension** (only activated when `mechanism_overrides` is non-empty in the manifest):

```
if manifest.get("mechanism_overrides"):
    overrides_hash = sha256(json_canonical(manifest["mechanism_overrides"]))[:12]
    h.update(b"\x00mechanism_overrides=" + overrides_hash.encode())
```

Where `json_canonical` is deterministic JSON serialization (sorted keys). This extension is off by default (no overrides declared → no hash change). Activating it for M275 (or any machine) only affects that machine's hash.

**What is NOT hashed** (unchanged from as-built `09_architecture_as_built.md §6`):
- `round_classification.py`, `round_win.py`, `trigger_sessions.py` — not in `core/` and not in `features/`. Changes to these files change `analyzer_version` (legacy) but not `effective_analyzer_version`. This pre-existing gap is acknowledged in `01_pipeline_map.md §10 Q7`. Resolving it would require adding these files to the base hash computation (which would invalidate all 393 machines on any change). **Deferred** to Phase C6 or later; these files are mature and rarely change.
- `mechanism_portrait.py` — derived output writer, not analysis code. Hashed into no version.
- `configs/bcm_pairings.json` — remains unhashed. When this file changes, the operator must manually invalidate affected reports. Note: Phase C5's consolidation of BCM pairing reads makes this easier to track.

### §8.3 Worked example: adding `machine_mechanics` feature to M275

Before Phase C4:
- M275 manifest: `analyzer_features = ["bankruptcy_simulation", "multiplier_profile", "payouts_by_spin_type", "reel_marginal_by_spin_type"]`
- M14 manifest: same 4 features
- `effective_analyzer_version(M275, 1) == effective_analyzer_version(M14, 1)` (same features)

After Phase C4 (M275 manifest updated, machine_mechanics plugin added):
- M275 manifest: `analyzer_features = ["bankruptcy_simulation", "machine_mechanics", "multiplier_profile", "payout_id_panel", "payouts_by_spin_type", "reel_marginal_by_spin_type"]`
- M14 manifest: still 4 features (plus `payout_id_panel` and `machine_mechanics` added universally)

Wait — per Phase C4 design, all 253 non-variant manifests add `machine_mechanics`. So the hash change is: all 253 machines' `effective_analyzer_version` flips once (when the feature is universally added). After that, changes to `machine_mechanics.py` flip only the hash of machines that declare it (= all 253 until differentation occurs).

The surgical property is this: if machine_mechanics logic is later split into a BCM-specific variant plugin (`machine_mechanics_bcm`) declared only by BCM machines, then editing that plugin flips only the BCM machines' hashes, not the 53 A_VANILLA machines.

**Hash formula worked example** (Phase C4, M275 mode 1):
```
base_hash = sha256(core/*.py files)[:12] = "abc123def456"
feature_hashes = {
    "bankruptcy_simulation":      "bb1",
    "machine_mechanics":          "mm1",  # new plugin
    "multiplier_profile":         "mp1",
    "payout_id_panel":            "pi1",  # from Phase C2
    "payouts_by_spin_type":       "ps2",  # bumped in Phase C3
    "reel_marginal_by_spin_type": "rm1",
}
machine_features_M275 = sorted([
    "bankruptcy_simulation", "machine_mechanics", "multiplier_profile",
    "payout_id_panel", "payouts_by_spin_type", "reel_marginal_by_spin_type"
])

h = sha256(b"abc123def456")
h.update(b"\x00bankruptcy_simulation=bb1")
h.update(b"\x00machine_mechanics=mm1")
h.update(b"\x00multiplier_profile=mp1")
h.update(b"\x00payout_id_panel=pi1")
h.update(b"\x00payouts_by_spin_type=ps2")
h.update(b"\x00reel_marginal_by_spin_type=rm1")
h.update(b"\x00mode=1")
effective_analyzer_version(M275, 1) = h.hexdigest()[:12]
```

If only `machine_mechanics.py` is later edited (e.g., to fix a lock_symbols bug):
- `mm1` becomes `mm2`
- M275's version changes
- M14's version also changes (since M14 also declares `machine_mechanics`)
- M37's version also changes (A_VANILLA, also declares it)
- **Zero machines that do NOT declare `machine_mechanics`** are affected

### §8.4 Migration of existing reports

Existing 336 on-disk reports were built with the 4-feature version. After Phase C2 (which adds `payout_id_panel` universally), all 253 machines' `effective_analyzer_version` changes. The existing 275 reports with non-empty `effective_analyzer_version` become "historical" from that point. They remain readable; the UI freshness badge shows them as not matching the current version.

**This is correct behavior** per `feedback_md5_is_a_tag_not_a_destruction_signal.md`: old reports are reclassified as `historical`, not deleted. Operators regenerate reports on demand. The phased release plan (C1 through C6) means there are at most 6 fleet-wide invalidation events, not one big-bang. Each phase is a deliberate boundary.

---

## §9 Manifest Schema Evolution

### §9.1 New optional fields

Two new optional manifest fields:

**`mechanism_overrides`** (optional, default: `{}`):
```json
{
  "mechanism_overrides": {
    "jackpot_pid_set": ["27502", "27503", "27504"],
    "scatter_marker_pids": ["666"],
    "bcm_cycle_length": 1000,
    "freespin_applicable": true,
    "payout_groups_applicable": false
  }
}
```
- Used when raw data is insufficient for reliable inference (e.g., early in sampling, or for machines with sparse jackpot events in the sample window).
- Affects `effective_analyzer_version` when non-empty (per §8.2 extension).
- Validated by `manifest_loader.py` rule: each key must match a known registry field.
- Most machines: not needed; inference is correct from data.

**`mechanism_declared_sources`** (optional, default: `{}`):
Records which tier the operator expects to be the authoritative source for each field. Used by `manifest_lint.py` to warn if the registry's `_detection_source` disagrees with expectation. Example:
```json
{
  "mechanism_declared_sources": {
    "jackpot_pid_set": "manifest",
    "freespin_applicable": "tier2_inferred"
  }
}
```
This is pure metadata; it does not affect analysis or hashing.

### §9.2 Required manifest updates for M275

M275's current manifest (`slot_designer/configs/machine_manifests/M275.json`) has two known errors per `01_pipeline_map.md §9`:
1. `spin_type_convention.paid = [1]` — wrong; M275's paid ST is 140.
2. `rtp_integrity_contract.expected_paid_st = [1]` — same error.
3. `rtp_integrity_contract.expected_bonus_st = []` — missing ST 126 (freespin).
4. `console_diagnostic_complete: false` — appropriate given unreviewed state.

These must be corrected as part of Phase C4 or earlier (they affect the Layer 4 integrity check, not the plugin architecture). No hash impact from correcting `spin_type_convention` — this field is not part of `effective_analyzer_version` composition.

### §9.3 Per-mode overrides for hard-to-infer parameters

For BCM machines where the sample is too short to observe a complete cycle (cycle_length = 1000 requires >1000 paid spins), the `mechanism_overrides.bcm_cycle_length` field provides a manual declaration. This matches the user's stated concern about "不需要增加或者修改任何代码" — the operator declares the cycle length in the manifest, and the registry uses the declared value (Tier 1 precedence) rather than requiring a code change.

---

## §10 8 Gaps Closure Table

| # | Gap | Owning Plugin | Fix Sketch | Tested via |
|---|-----|---------------|------------|------------|
| **1** | `machine_mechanics.jackpot.applicable: false` | `machine_mechanics.py` (Phase C4) | Plugin reads `registry.jackpot_pid_set`; applicable = bool(non-empty). Registry built from `payout_id_win` PIDs ≥ 10000 (Tier 3 raw, 26 machines) | Verify M275 report: `machine_mechanics.jackpot.applicable: true`, `pid_set: ["27502","27503","27504"]`. Fleet smoke: 26 jackpot machines show applicable:true; 230 non-jackpot show applicable:false. |
| **2** | `machine_mechanics.free_spin.applicable: false` | `machine_mechanics.py` (Phase C4) | Plugin reads `registry.freespin_applicable`; applicable = True if bonus_chain has chains (Tier 2). Fallback: any SpinType in rawdata with ReMarks containing "Freespin". | Verify M275 report: `machine_mechanics.free_spin.applicable: true`. Fleet smoke: all 107 machines in C_FREESPIN_* and B_BCM_FREESPIN_* archetypes show applicable:true. |
| **3** | pid=666 classified `cat=paid` | `payout_id_panel.py` (Phase C2) | pid in `registry.scatter_marker_pids` → `category = "scatter_trigger"`, `trigger_only = True`. Registry scatter detection: PID with line_id=-1 + win==0 in payline records. | Verify M275 report: pid 666 shows `category: "scatter_trigger"`. Fleet smoke: 99 machines with standard scatter pid=666 all show correct classification. |
| **4** | Multiplier wild not interpreted | deferred (paused) | Per `00_brief.md §6`, paused fleet-wide. Architecture provides hooks (`mechanism_portrait.multiplier_wilds.applicable = "paused"`). No code change. | N/A until multiplier inference bugs are fixed. |
| **5** | `payout_groups_top20` all-zero noise | `payout_id_panel.py` (Phase C2) | `registry.payout_groups_applicable = False` when all observed PayoutGroupId == 0. Plugin writes `payout_groups_top20 = []` with `"suppressed"` note. | Verify M275 report: `payout_groups_top20` is empty or annotated. Fleet smoke: 247 all-zero machines suppress panel; 9 machines with real groups continue to show panel. |
| **6** | `estimated_correction_pp: 0.0` | `collect_mechanic.py` (Phase C5) + formula investigation | Per mapper analysis (`01_pipeline_map.md §5 Gap #6`), 0.0 may be mathematically correct for M275's specific sample (all robots completed cycles). Architecture surfaces `robots_with_pending_cycle` prominently in portrait. Formula investigation required before claiming this is a bug. See §15 Q1. | Verify M275 portrait shows `robots_with_pending_cycle: 0` with explanation. Separately: construct test case with known pending cycle to verify correction formula non-zero output. |
| **7** | `payouts_by_spin_type` missing shape/cols/paylines/notes | `payouts_by_spin_type.py` promoted (Phase C3) | Plugin computes `paylines` from `payline_winning_symbols_rln` joined to pid. `shape` from payline topology. `notes` from scatter_marker and jackpot registry checks. | Verify M275 report: each pid row in payouts_by_spin_type has `paylines`, `notes` fields. Fleet smoke: all machines produce non-null `paylines` for winning pids. |
| **8** | `payout_ids_top20` missing same fields | `payout_id_panel.py` (Phase C2) | Same enrichment applied to payout_ids_top20 rows. `notes` field: "scatter trigger" for marker pids, "jackpot" for jackpot pids. | Verify M275 report: pids 27502/27503/27504 have `notes: "jackpot"`. pid 666 has `notes: "scatter trigger"`. Fleet smoke: additive fields present fleet-wide. |

---

## §11 Migration and Rollout

### §11.1 Phased rollout strategy

The 6 phases in §7.2 (C1–C6) define the rollout. Key properties:
- **Each phase is independently deployable**: the system is correct at the end of each phase.
- **No big-bang**: no "stop the world, rewrite everything" moment.
- **Feature flags via manifests**: a machine opts into new plugins by having them in `analyzer_features`. Machines not yet updated continue with the old behavior.
- **M275 is the pilot**: M275's manifest is updated in each phase as the driving case. After validating M275's reports correct, the feature is added universally (to all 253 non-variant manifests in the same PR).

### §11.2 Backward compatibility table

| Artifact | During migration | After full carve |
|----------|-----------------|-----------------|
| 336 on-disk summaries | Readable unchanged. Freshness badge may flip per phase. | Readable. Historical. Re-runnable from cache. |
| `payout_ids_top20` field name | Unchanged throughout | Unchanged |
| `payout_ids_top20` row schema | Additive fields added (notes, trigger_only) in C2 | Same as C2 |
| `payouts_by_spin_type` row schema | Additive fields added in C3 | Same as C3 |
| `machine_mechanics` sub-fields | field values corrected in C4 (jackpot.applicable may flip true) | Values now correct |
| `machine_mechanics` key structure | Unchanged | Unchanged |
| `collect_mechanic` key structure | Unchanged | Unchanged |
| `upstream_feature_breakdown` key structure | Unchanged | Unchanged |
| `bonus_chain_dynamics` key structure | Unchanged | Unchanged |
| `analyzer_version` legacy field | Unchanged (stays in summary) | Unchanged |
| `effective_analyzer_version` | Changes per phase for machines affected | Stable post-C6 |
| RTP integrity L1/L2/L3 | Must PASS throughout (no accumulator changes) | Same |
| `rtp_integrity_check` field | Unchanged | Unchanged |

### §11.3 Rollback path per phase

Each phase has an isolated rollback:
- **C1**: revert merge loop `extract()` wiring, revert `feature_registry.py` emit loop change. All existing output unchanged. Zero observable side effect.
- **C2**: revert `payout_id_panel.py` creation, restore Block F2/F2b inline code, revert M275 and other manifests. Previous output restored exactly.
- **C3**: revert `payouts_by_spin_type.py` Pattern B promotion, restore Block F3 inline code. Previous output restored.
- **C4**: revert `machine_mechanics.py`, restore Block F8 inline code, revert manifest changes. Previous (incorrect) `machine_mechanics.jackpot.applicable: false` restored.
- **C5**: revert `upstream_feature.py` and `collect_mechanic.py`, restore Block F5/F9 inline code.
- **C6**: revert `bonus_chain_dynamics.py`, restore Block F6 inline code.

### §11.4 B_BCM_FREESPIN_WHEEL archetype first

Per `02_taxonomy.md §10`, B_BCM_FREESPIN_WHEEL has 87 M273 variants — fixing M275 (the archetype's driving case) benefits 107 fleet entities if variants inherit the corrected manifest. The manifest update pattern:
1. Fix M275.json — pilot.
2. Validate M275 reports correct.
3. Add new features universally to all 253 non-variant manifests (one PR per phase).
4. Variants inherit via `inherits_from` cascade (per `09_architecture_as_built.md §2`).

### §11.5 No report deletion

Per `feedback_md5_is_a_tag_not_a_destruction_signal.md`: `effective_analyzer_version` changes reclassify old reports as `historical`, not `deleted`. All 336 existing reports remain on disk. Operators regenerate from cache on demand. The phased release means at most one fleet-wide freshness-badge flip per phase (6 flips total, spread over implementation sessions).

---

## §12 M275 End-to-End Walk

Tracing M275 mode 1 through the proposed pipeline after all phases (C1–C6) complete:

### §12.1 Chunk parse (parser.py)

Unchanged. `parse_chunk_response()` produces `rec` with:
- `payout_id_win = {"27502": 1.2e6, "27503": 8.1e5, "27504": 2.2e6, "666": 0.0, ...}`
- `payline_winning_symbols_rln` containing per-pid payline records
- `payline_hits` with line_id=-1 entries for pid 666
- `cycle_peaks = [1000, 1000, ...]`, `final_cc_values = [...]`
- `bonus_chain_lengths = [10, 10, ...]`, `bonus_chain_max_ratios = [...]`
- `freespin_chain_spins = 0` (raw CurFreeSpin field not set — unchanged; the M275 raw field gap remains in the accumulator but is no longer the sole input to `machine_mechanics`)
- `jackpot_spins = 0` (raw JackpotIds field not set — unchanged for the same reason)

### §12.2 Merge loop (extract calls)

Each chunk's rec is passed to `extract()` for each declared feature plugin. Pattern A plugins return `{}`. Pattern B plugins accumulate plugin-private state (e.g., `payout_id_panel.extract()` accumulates per-chunk pid-to-payline mappings from `payline_winning_symbols_rln`).

### §12.3 Finalization — MechanismRegistry build

After all chunks merged, `_build_mechanism_registry()` is called:
- Tier 3 raw: `payout_id_win` contains PIDs 27502, 27503, 27504 all ≥ 10000 → `jackpot_pid_set = {"27502", "27503", "27504"}`, `_detection_source["jackpot_pid_set"] = "tier3_raw"`.
- Tier 3 raw: `payline_records` for pid 666 has `line_id=-1` and `total_win=0` → `scatter_marker_pids = {"666"}`, `_detection_source["scatter_marker_pids"] = "tier3_raw"`.
- Tier 2 inferred: `bonus_chain_dynamics.chain_count > 0` (will be computed in F6 — but F6 runs after registry build). **Ordering problem**: the registry needs freespin evidence from bonus_chain_dynamics, but bonus_chain_dynamics isn't finalized yet.

**Resolution**: The registry build uses only Tier 3 raw accumulators for its initial build. After F6 (bonus_chain_dynamics) runs and writes to summary, the registry can be updated with Tier 2 evidence. OR: build `freespin_applicable` from Tier 3 raw (SpinType 126 in `spin_type_spins` with "free" behavior label from F1) without requiring F6 to run first.

For M275: `spin_type_spins` contains SpinType 126 — F1's `spin_type_rows` classifies it as `behavior_name = "free"`. This Tier 3 raw signal is sufficient: `freespin_applicable = True`, `freespin_st_set = {126}`, `_detection_source["freespin_applicable"] = "tier3_raw_st_behavior"`.

Manifest has no `mechanism_overrides` for M275 → Tier 1 is empty → Tier 3 raw values are authoritative.

Registry is built. `summary["_mechanism_registry"] = registry`.

### §12.4 Plugin emit sequence

**F1 inline**: produces `spin_type_breakdown` with ST140 (paid) and ST126 (free). `_st_label = {140: "ST140_paid", 126: "ST126_free"}`.

**`payout_id_panel.emit()`** (Phase C2):
- pid 666: `registry.scatter_marker_pids` contains "666" → `category = "scatter_trigger"`, `trigger_only = True`, `notes = "scatter trigger"`. Gap #3 CLOSED.
- pid 27502/27503/27504: `registry.jackpot_pid_set` contains these → `notes = "jackpot"`. Gap #8 enrichment applied.
- `registry.payout_groups_applicable = False` (all PayoutGroupId == 0) → `payout_groups_top20 = []`. Gap #5 CLOSED.

```json
"payout_ids_top20": [
  {"payout_id": "27502", "hit_count": 432, "total_win": 1200000,
   "rtp_contribution_pp": 1.83, "notes": "jackpot", ...},
  {"payout_id": "27503", "hit_count": 310, "total_win": 810000,
   "rtp_contribution_pp": 1.23, "notes": "jackpot", ...},
  {"payout_id": "27504", "hit_count": 84, "total_win": 2200000,
   "rtp_contribution_pp": 3.35, "notes": "jackpot", ...},
  {"payout_id": "666", "hit_count": 829, "total_win": 0,
   "rtp_contribution_pp": 0.0, "category": "scatter_trigger",
   "trigger_only": true, "notes": "scatter trigger", ...}
]
"payout_groups_top20": []
```

**`payouts_by_spin_type.emit()`** (Phase C3):
- Adds `paylines`, `shape`, `notes` to each pid row per ST. Gap #7 CLOSED.

**`upstream_feature.emit()`** (Phase C5): unchanged behavior, but now also sets `_bcm_bonus_feature` and `_bcm_bonus_source` as DECLARED_DEPS.

**`bonus_chain_dynamics.emit()`** (Phase C6): unchanged behavior. chain_count=908 correctly reflects 9090 freespin rounds.

**`machine_mechanics.emit()`** (Phase C4):
- reads `registry.jackpot_pid_set = {"27502", "27503", "27504"}` → `jackpot.applicable = True`. Gap #1 CLOSED.
- reads `registry.freespin_applicable = True` → `free_spin.applicable = True`. Gap #2 CLOSED.

```json
"machine_mechanics": {
  "jackpot": {
    "applicable": true,
    "observed_jackpot_pids": ["27502", "27503", "27504"],
    "jackpot_rtp_pp": 6.41,
    "jackpot_hit_rate_per_paid_spin": 0.00826
  },
  "free_spin": {
    "applicable": true,
    "freespin_st_set": [126],
    "freespin_chain_count": 908,
    "freespin_rounds_per_chain": 10.01,
    "freespin_rtp_pp": 24.8
  },
  ...
}
```

**`collect_mechanic.emit()`** (Phase C5): reads `_bcm_bonus_feature`, writes corrected `collect_mechanic` key. Gap #6 (correction formula) behavior unchanged pending investigation.

### §12.5 Portrait write

`mechanism_portrait.py` writes `mechanism_portrait.json` alongside the summary. All gaps #1, #2, #3, #5, #7, #8 closed. Gap #6 open pending investigation. Gap #4 deferred.

### §12.6 RTP integrity check

L1: `our_total_win == server_total_win` — unchanged (accumulator values not touched by any plugin).
L2: no `_unattributed_*` pids — unchanged.
L3: required anchors — once M275 manifest is corrected, required anchors include the scatter trigger pid.
L4: `layer4_applicable` — depends on whether M275 uses trigger-session pattern (per v5 §9.4, trigger-session machines skip L4). M275 uses freespin triggered by scatter, not `compute_trigger_sessions` session re-attribution. L4 applicable: TBD (open question §15 Q3).

All 8 gaps shown in predicted summary above. RTP integrity L1/L2 PASS. No other machine's `effective_analyzer_version` changes spuriously — only machines that declare any of the newly promoted plugins change.

---

## §13 "Zero-Code New Machine" Property

### §13.1 Precise statement post-this-work

**Case A — Pure vanilla** (A_VANILLA archetype, 53 base machines):
Zero-code onboarding property: HOLDS. A new machine with `NormalSpin*` + `NormalRTP*` classes, using any ST convention, with any payline count, requires only a manifest JSON. The existing 4 Pattern A + 4 Pattern B plugins (post-carve) handle it correctly.

**Case B — Recombination of known mechanics** (B_BCM_* archetypes, 57 base machines + 89 variants):
Zero-code onboarding property: HOLDS after this work, for the following mechanism combinations:
- BCM cycle collection ✓ (collect_mechanic plugin handles it)
- Freespin triggered by scatter marker ✓ (scatter detection is universal)
- Jackpot PIDs (machine-ID-prefixed) ✓ (jackpot detection is universal: any PID ≥ 10000)
- BCM + Freespin + Wheel combination ✓ (M275's exact combination is the test case)
- Multiplier wilds: NOT YET (gap #4, inference paused)

A new machine with BCM + Freespin + Jackpot PIDs (e.g., a hypothetical M276-like machine) requires: manifest JSON with correct `spin_type_convention` and optionally `mechanism_overrides.bcm_cycle_length`. No code change.

**Residual Case B requiring code**: A new machine with a DIFFERENT detection signal for jackpots (e.g., jackpots stored in a new upstream field, not `PayoutIdToWinAmount`) would require a code change to the detection tier. The detection threshold (≥10000) is heuristic; a machine with jackpots at PID 9999 would be missed.

**Case C — Novel mechanic** (C_RESPIN_ONLY, C_WHEEL_ONLY, C_LOCK_*, D_* archetypes, ~132 base machines):
Zero-code onboarding property: DOES NOT HOLD. Machines with new mechanics (novel respin types, lock patterns, minigames) require:
1. A new Pattern B plugin implementing the mechanic's analysis.
2. The plugin declared in the machine's manifest `analyzer_features`.

The architecture makes this cheap (isolated blast radius: one new plugin file + one manifest line), but it does require code.

**Residual machines requiring code work**:
- M11 (Grand* engine family, bespoke ST numbering) — Tier 1 hard case, requires bespoke plugin.
- M94 (BCM with ST=1 convention, not ST=140) — BCM detection based on ST=140 will miss this machine.
- M113 (ExpandingSymbolSpinGenerator, unique mechanic) — requires bespoke plugin.
- M250/M239 (single-row strip grids in BCM family) — BCM plugins should handle these; the grid topology may affect payline analysis plugins.
- M99/M104 (ST=96 GoldenPrize family with lock/minigame sub-rounds) — known double-count bug for ST=97+98.
- M260/M268 (BCM with non-standard ST conventions) — BCM detection should handle with correct manifest `spin_type_convention`.

### §13.2 Summary table

| Case | Archetype count | Zero-code after this work? | Residual requirement |
|------|-----------------|---------------------------|---------------------|
| A — Vanilla | 53 base | YES | None |
| B — BCM recombination (standard) | ~50 of 57 BCM base | YES | Manifest with correct `spin_type_convention` |
| B — BCM with non-standard ST | ~7 BCM outliers (M108/M117/M125/M138/M249/M251/M254) | PARTIAL | Manifest `spin_type_convention` override |
| B — Multiplier wilds | Any machine with wild multipliers | NOT YET (gap #4) | Multiplier inference restart |
| C — Single mechanic (freespin/respin/wheel) | 132 base | NO | Cluster-shared plugin per mechanic type |
| D — Complex/outlier | 14 base | NO | Bespoke plugin per machine |

---

## §14 Out of Scope Deferrals

### §14.1 Multiplier wild auto-inference resume (Gap #4)

**Why deferred**: Per `00_brief.md §6` and `memory/project_paytable_inference_paused.md`, multiplier inference is paused due to two open bugs. This proposal does not restart it. The architecture provides: (a) portrait shows `multiplier_wilds.applicable = "paused"` with reason; (b) the `mechanism_registry.py` has a placeholder field `multiplier_wild_values: dict | None` that the inference module can populate when resumed.

**Not deferred because**: fixing gaps #1-#3 and #5-#8 is valuable without gap #4. Multiplier inference is a separate feature with its own bugs, not a prerequisite for the mechanism registry.

### §14.2 Frontend renderer registry / SCHEMA_VERSION CI

**Why deferred**: This is Phase 4 of the original `04_v5.md` proposal (`09_architecture_as_built.md §2 Phase 4`). The field additions proposed here (notes, trigger_only, paylines, shape) are additive — old frontend renders them if present, ignores if absent. No immediate renderer breakage. The SCHEMA_VERSION bump for `payouts_by_spin_type` signals the schema change for future enforcement.

### §14.3 PIA legacy `analyzer_version` field deprecation

**Why deferred**: `00_brief.md §4` explicitly states this field stays for backward-compat. It is a load-bearing field in `latest.json`, `index.json`, SQLite `runs` table, `app.js`, `pure.js`, `compare_diff.js` (`03_coupling_audit.md §2.1 Symbol 3`).

### §14.4 `round_classification.py` / `round_win.py` / `trigger_sessions.py` hashing into `effective_analyzer_version`

**Why deferred**: adding these files to the base hash computation would invalidate all 393 machines on any edit to these mature modules. They are rarely changed. The risk does not justify the blast. Tracked in `01_pipeline_map.md §10 Q7` as an open question.

### §14.5 Merge loop duplication (from-cache vs. online path)

**Why deferred**: `01_pipeline_map.md §8 Duplication finding 1` documents this acknowledged duplication. The `extract()` wiring (Phase C1) must be applied to BOTH paths — this is captured in the C1 deliverables. The deduplication of the merge loop itself (consolidating into a helper function) is a separate refactor not needed for gap closure.

### §14.6 Cluster-specific plugins for C_* archetypes

**Why deferred**: C_FREESPIN_ONLY, C_WHEEL_ONLY, C_RESPIN_ONLY, C_LOCK_* archetypes (132 base machines) each have their own mechanic logic. Designing cluster-specific plugins is valuable but is a follow-on task once the mechanism registry and Protocol v2 are established. This proposal establishes the container; the content is per subsequent arch-team sessions.

---

## §15 Open Questions for Wave 3

**Q1: Gap #6 — Is `estimated_correction_pp = 0.0` a formula bug or correct output?**

Per `01_pipeline_map.md §5 Gap #6`, the mapper's analysis suggests the 0.0 value is mathematically correct when `robots_with_pending_cycle = 0`. The `clamp_warning` "80% pending" refers to paid spins toward the next cycle trigger, not to incomplete cycles. But the brief classifies this as a gap. Wave 3 critic and validator must weigh in: is this a real bug requiring formula correction, or a display confusion requiring only better labeling in the portrait?

Binary choice:
- (a) Formula is correct; fix is to label `clamp_warning` more clearly in the portrait and add a note explaining the distinction between "pending paid spins" and "pending cycle completion."
- (b) Formula is wrong; the correction should account for all pending paid spins, not just robots with incomplete cycles. Fix requires understanding the economic impact of early-sample truncation.

**Q2: `mechanism_registry.py` placement — `fresh_slotlab/analyzer/` vs `fresh_slotlab/analyzer/core/`?**

If placed in `core/`, it triggers a fleet-wide `effective_analyzer_version` invalidation (293 reports) on the first deploy (`03_coupling_audit.md §5 Case Study A`). If placed in `fresh_slotlab/analyzer/` (not `core/`), no invalidation occurs from the file's creation.

The recommended placement is `fresh_slotlab/analyzer/` (outside `core/`). The critic should validate: is there any current or planned consumer that expects to find `mechanism_registry` in `core/` via the `compute_base_analyzer_version` glob? The glob is currently `core/*.py` — any file outside that directory is excluded. The registry would need to be explicitly added to the base hash if its changes should invalidate all machines (which we do NOT want — the registry changes only when a plugin that imports it changes its file hash).

**Q3: Is M275 a trigger-session machine? Is `layer4_applicable` true or false for M275?**

M275 has freespin triggered by scatter (pid=666). The `trigger_session_pattern` in v5 refers to `compute_trigger_sessions()` re-attribution where a bonus win is credited back to the triggering paid spin's session. The scatter-triggered freespin in M275 may or may not use this re-attribution pattern. If M275 uses `trigger_session_pattern != null`, then Layer 4 should be `layer4_applicable: false` per v5 architecture. This must be determined from rawdata analysis before correcting the M275 manifest.

Binary choices:
- (a) M275 uses trigger-session re-attribution → `layer4_applicable: false`, `trigger_session_pattern: "type_1"` or `"type_2"`.
- (b) M275 does not use trigger-session re-attribution → `layer4_applicable: true`, `trigger_session_pattern: null`. Layer 4 runs and may reveal dispatch-routing bugs.

**Q4: `DECLARED_DEPS` ordering — should the emit-loop runner enforce topological sort, or is a fixed ordering in the plugin declaration sufficient?**

The proposal uses `REQUIRES = ("upstream_feature",)` in `CollectMechanicFeature` to declare ordering. The emit-loop runner must topologically sort plugins before calling emit. Two options:
- (a) Static ordering: the runner sorts ALL_FEATURES by declaration order in manifest. Plugins must be declared in dependency order in `analyzer_features`. Simple but fragile — a manifest with wrong declaration order silently fails.
- (b) Topological sort: the runner uses `REQUIRES` ClassVar to build a DAG and topologically sorts. Safe but adds runtime complexity.

**Q5: Should `payout_id_panel` plugin replace both F2 and F2b, or should `payout_groups_top20` remain inline?**

`payout_groups_top20` is a separate summary key from `payout_ids_top20`. Both are built in adjacent inline blocks (F2 and F2b). The proposal combines them into one plugin for simplicity. The critic should validate: is there any machine where `payout_groups_top20` requires different accumulator access than `payout_ids_top20`? If yes, split into two plugins. If no, combining is cleaner.

**Q6: Should `mechanism_overrides` in the manifest trigger a different `effective_analyzer_version` hash, or is it acceptable for report freshness to not reflect manifest override changes?**

The §8.2 proposal adds `mechanism_overrides` to the hash only when non-empty. This means adding an override to M275.json would change M275's `effective_analyzer_version`, correctly signaling that old reports should be regenerated. The critic should validate: is this the right scope? Should ALL non-`analyzer_features` manifest fields be included in the hash? (That would make manifest changes version-visible, but also means any text edit to a manifest's `_generator_notes` comment would flip the version.)

**Q7: BCM machines with non-standard SpinType conventions (M108/M117/M125 with ST=101) — does the mechanism registry's freespin detection handle them?**

Per `02_taxonomy.md §6`, these BCM machines have paid ST=101 instead of the standard ST=140. The mechanism registry's freespin detection (Tier 3 raw: "any SpinType with ReMarks containing 'Freespin'") is ST-agnostic — it does not rely on ST=126 specifically. But the `spin_type_behavior` labeling from F1 must correctly classify these machines' bonus STs as "free". Validator should verify: does F1's current `_st_behavior` classification work for machines with ST=101 paid convention?

---

## Summary reference table

| Design dimension | Decision |
|---|---|
| Mechanism Registry placement | `fresh_slotlab/analyzer/mechanism_registry.py` (NOT `core/`) |
| Registry build timing | Post-merge, pre-emit finalization |
| `extract()` wiring | Per-chunk in merge loop; `ParseState` passed |
| `emit()` loop | Uses `get_features_for_machine(manifest)` (filtered, not `ALL_FEATURES`) |
| Cross-plugin ordering | `REQUIRES` + topological sort by runner |
| Inter-plugin data | `DECLARED_DEPS` temp-key stash (formalized) |
| Portrait sidecar | `mechanism_portrait.json` alongside summary, written by `mechanism_portrait.py` |
| Hash composition change | No algorithm change; new optional `mechanism_overrides` dimension |
| Carve phases | C1 (wiring) → C2 (payout panel) → C3 (payouts enrichment) → C4 (machine_mechanics) → C5 (upstream_feature + collect_mechanic) → C6 (bonus_chain) |
| M275 manifest errors corrected | `spin_type_convention.paid = [140]`, `expected_paid_st = [140]`, `expected_bonus_st = [126]` |
| Zero-code property scope | Case-A VANILLA + Case-B standard BCM; excludes Case-C and D archetypes |
| Gap #4 multiplier wilds | Deferred (paused inference) |
| Gap #6 BCM correction | Open question §15 Q1 |
