# 04 — Architecture Proposal v2: Analyzer Unbundle (M275-driven)

> **Produced by**: arch-designer (W2) — revision pass
> **Date**: 2026-05-25
> **Prior version**: `04_architecture_proposal.md` (v1)
> **Topic dir**: `session_artifacts/_arch_analyzer_unbundle/`
> **Inputs consumed**: v1 proposal, `05_critique.md` (critic), `06_validation.md` (validator),
>   `00_brief.md`, `01_pipeline_map.md`, `02_taxonomy.md`, `03_coupling_audit.md`
> **Next consumer**: arch-critic (W3 v2), arch-validator (W3 v2)

---

## §0 Revision Log v1 → v2

Every change below is surgical; v1 sections not listed are carried forward unchanged.

| # | Changed section | What changed | Driven by |
|---|---|---|---|
| R-01 | §0 (new) | This revision log | Process |
| R-02 | §4.2 | Added `PipelineContext` dataclass as 3rd parameter to `emit()` carrying `effective_bet_for_rtp`, `total_spins`, `total_paid_sessions` and all other raw accumulator scalars needed by panel plugins | `05 EC6/EC7`, `05 REV-3` |
| R-03 | §4.2 | Specified exact emit loop execution order constraint: "F1 inline MUST complete before `_build_mechanism_registry()` call which MUST complete before plugin emit loop begins"; added `_EMIT_PHASE_PRECONDITIONS` sentinel dict as enforced runtime check | `05 TC1`, `05 Q4`, `05 REV-1` |
| R-04 | §4.2 | Added topological sort algorithm spec: Kahn's algorithm over `REQUIRES` DAG; cycle detection raises `PluginCyclicDependencyError`; missing-dependency (node present in `REQUIRES` but absent from `get_features_for_machine()`) raises `PluginMissingDependencyError` at sort time, not silently at emit time | `05 Q3`, `05 REV-6` |
| R-05 | §4.1 | Added `PipelineContext` dataclass sketch with all fields; updated `emit()` signature to `emit(self, final_acc: dict, summary: dict, ctx: PipelineContext) -> None` | `05 REV-3`, `05 EC6`, `05 EC7` |
| R-06 | §5.2 | Corrected Tier 3 freespin signal: replaced `spin_type_spins behavior_name=free` with `total_freespin_chain_spins > 0` (the CurFreeSpin-based accumulator). Added explicit note that `behavior_name=free` MUST NOT be used as freespin proxy because B_BCM_WHEEL machines (M279, 18 total) also have bonus/wheel SpinTypes with behavior_name=free but zero actual freespin chains | `06 R1`, `06 Case 4` |
| R-07 | §5.2 | Added Tier 2 explicit-False blocking rule: if `bonus_chain_dynamics` accumulator gives `all_bonus_chains_by_feature` with no entries (chain_count=0 and total_freespin_chain_spins=0), Tier 2 explicitly sets `freespin_applicable=False` and blocks Tier 3 fallback. Only when Tier 2 has no signal (data not yet computed) does Tier 3 activate | `06 R1`, `06 Case 4` |
| R-08 | §5.2 | Added jackpot-scatter exclusion ordering: scatter marker detection runs first; PIDs in `scatter_marker_pids` are excluded from jackpot PID candidate set before the ≥10000 threshold is applied | `05 Q2` |
| R-09 | §5.2 | Added Tier 2 jackpot alternative signal: if no PID ≥10000 found in Tier 3 raw but `bonus_chain_dynamics` or `upstream_feature` contains explicit jackpot-feature markers, promote to jackpot_applicable=True with `_detection_source="tier2_inferred"` | `05 Q2` |
| R-10 | §5.4 | Added `mechanism_portrait.py` error handling specification: write failure captures rc+stderr tail+path to `_portrait_write_error.json` alongside the run directory; main run continues (portrait is non-blocking); the portrait absence is surfaced in the run metadata | `05 EC5`, `memory/feedback_no_silent_swallow.md` |
| R-11 | §5.4 | Added sidecar concurrency spec: sidecar path is unique per `rv_<timestamp>` directory (same as summary); no file-level locking needed for the per-run sidecar. The optional `latest_portrait.json` pointer (Phase 3, deferred) uses atomic-rename pattern per `ConfigFileWriter` | `05 Q8` |
| R-12 | §7.2 | Added "§15.5 Per-phase acceptance criteria" table enumerating all 3 import sites for every new plugin added in phases C2/C4/C5/C6 | `05 TC3`, `05 Q15`, `05 REV-2` |
| R-13 | §7.2 C1 | Strengthened C1 deliverables: explicit requirement that F1 inline runs before `_build_mechanism_registry()` call, enforced by `_EMIT_PHASE_PRECONDITIONS` sentinel; explicit requirement that `extract()` is wired in BOTH merge loop paths (from-cache at `pia:1614` and online at `pia:2620`) | `05 C1-1`, `05 REV-1` |
| R-14 | §7.2 C1 | Added `PipelineContext` construction to C1 deliverables: the context object is built in the finalization block after all accumulators are merged and passed to every `emit()` call | `05 REV-3` |
| R-15 | §7.2 (all phases) | Corrected "Expected delta count: 254" → "253" throughout all phase sections | `06 Break 4` |
| R-16 | §8.2 | Added explicit statement: "changes to `mechanism_registry.py` are NOT reflected in `effective_analyzer_version`; operators must manually invalidate when registry detection logic changes." Placed alongside existing acknowledgment for `round_classification.py` | `05 Q1`, `05 REV-4` |
| R-17 | §11.2 | Added Phase C2 behavior-change row for 50 non-666 scatter marker machines: their `payout_ids_top20` scatter-marker pid moves from `category: "paid"` to `category: "scatter_trigger"` | `05 REV-5`, `05 C2-2` |
| R-18 | §11.7 (new) | Added batch-rebuild operator workflow specification for the 5-phase × 253-machine rebuild burden; references `FleetRefreshManager` and machines-with-no-cache edge case | `05 Q7` |
| R-19 | §12.3 | Corrected Tier 3 freespin detection source label from `"tier3_raw_st_behavior"` to `"tier3_raw_freespin_chain_spins"` throughout the M275 end-to-end walk | `06 R1` |
| R-20 | §13.1 | Added explicit out-of-scope scoping for M250, M272, M279 L2 failures: named machines listed with explicit statement that their attribution failures are RoundWinRule-scope (separate task), not fixed by this proposal | `06 R2`, `06 Break 2`, `06 Break 3` |
| R-21 | §13.2 | Qualified "107 entities benefit" claim: the benefit comes from universal plugin addition to all 253 non-variant manifests including M273.json, not from M275-specific manifest corrections flowing to M273 variants | `05 Q14`, `05 REV-7` |
| R-22 | §14 (new §14.7) | Added explicit out-of-scope section for M273 variants auto-coverage via variant resolution | `05 Q14` |
| R-23 | §15 | Removed Q2 (registry placement — resolved: `fresh_slotlab/analyzer/`, confirmed correct by validator `06 §4`); renumbered remaining questions; added new Q8 on M273 variant auto-coverage confirmation | — |
| R-24 | §16 (new) | Added "Open questions surviving v2" section for items requiring user or W3-v2 input | — |

Total revisions in §0 log: **24**.

---

## §1 Executive Summary

*(Carried forward from v1 with one sentence addition at the end of the last paragraph.)*

The PIA monolith (`player_impact_analyzer.py`, ~5500 lines) produces correct RTP accounting for the 393-machine fleet but fails to correctly characterize *what* mechanics each machine has. M275 exposes this cleanly: six of eight known gaps trace to a single structural defect — **each analysis panel independently reaches its own conclusion about machine behavior from raw fields, with no shared source of truth for mechanism identity**. The remaining two gaps are universal display augmentations not yet implemented.

The predecessor architecture (`04_v5.md`) correctly designed a plugin system and shipped most of that foundation (`09_architecture_as_built.md`). What did NOT ship: the actual carve of inline blocks F2–F9 into plugins, and any mechanism for cross-panel synthesis. The four existing feature plugins (Pattern A: no-op scaffold × 3; Pattern B: `BankruptcySimulation`) demonstrate the container but hold no meaningful analytical content for the blocks that contain the 8 gaps.

This proposal extends the as-built architecture with three specific additions:

1. **Mechanism Registry** — a single in-memory object (built once per run, persisted to summary + `mechanism_portrait.json` sidecar) that synthesizes the canonical answer to "what mechanics does this machine have" from three source tiers. All panels consume it, no panel re-derives it.

2. **Plugin Protocol v2** — extends the existing `AnalyzerFeature` ABC with: (a) a `ParseState` object for per-chunk data at `extract()`; (b) a `DECLARED_DEPS` mechanism for inter-plugin data passing; (c) a `PipelineContext` dataclass passed to `emit()` carrying all raw accumulator scalars that panel plugins need for RTP computation; (d) formal topological sort enforcement for plugin ordering.

3. **PIA Inline Carve Plan** — phased promotion of blocks F2–F9 into genuine Pattern B plugins, with strict ordering that respects the `_st_label` / `_st_behavior` / `_bcm_bonus_feature` cross-block dependencies identified in `01_pipeline_map.md §7`.

Five concrete pain points, each cited from Wave 1:

1. **`machine_mechanics` isolation** — `total_jackpot_spins` requires raw `JackpotIds` field, which M275 never sets; its jackpots are in `PayoutIdToWinAmount`. The panel reaches "not applicable" while three other panels correctly characterize the jackpots (`01_pipeline_map.md §5 Gap #1`). **26 machines** affected (`02_taxonomy.md §5 Ax5`).

2. **Scatter trigger mis-classification** — pid 666 classified `cat=paid` in 99 machines using standard scatter markers because the zero-win + line_id=-1 pattern is not checked in F2's category logic (`01_pipeline_map.md §5 Gap #3`; `02_taxonomy.md §5 Ax6`).

3. **`extract()` lifecycle never wired** — the only call site is `_feature.emit(None, summary)` with `parse_state=None`; `extract()` is never invoked (`01_pipeline_map.md §6`). Pattern B carves for blocks that need per-round data cannot proceed.

4. **Hidden temp-key stash is the only inter-plugin mechanism** — `BankruptcySimulation` reads `summary["_bankruptcy_rows"]` without any ABC enforcement or ordering guarantee (`03_coupling_audit.md §4.3`). Promoting F5 and F9 requires the same mechanism for `_bcm_bonus_feature`/`_bcm_bonus_source`.

5. **`feature_registry.get_features_for_machine()` unused in production** — the emit loop calls `for _feature in ALL_FEATURES: _feature.emit()` unconditionally. Adding a new feature plugin would silently run `emit()` on every machine, even those that don't declare the feature (`03_coupling_audit.md §2.2 Symbol 6`).

---

## §2 Design Alternatives

*(Carried forward from v1 unchanged. Alt 2 recommended; Alts 1 and 3 rejected.)*

### §2.1 Alternative 1 — Deferred mechanism registry, per-block fixes only (minimal)

**Rejected.** Does not address root cause; recreates coupling; does not close `extract()` lifecycle gap; does not deliver "zero-code new machine" property. Migration cost LOW but value LOW. Full rationale in v1 §2.1.

### §2.2 Alternative 2 — Mechanism Registry + Protocol v2 + Phased Plugin Carve (recommended)

See §3–§15 for full specification.

### §2.3 Alternative 3 — Per-chunk extract() wiring only (intermediate)

**Rejected.** Does not close any of the 8 gaps. No standalone value for M275. Full rationale in v1 §2.3.

---

## §3 Recommended Option

**Alternative 2 — Mechanism Registry + Protocol v2 + Phased Plugin Carve.**

*(Rationale carried forward from v1 §3. Objection responses unchanged.)*

The four objection responses from v1 §3 stand, with one addition:

**Objection (from `05 TC1`): "The registry needs Tier 2 freespin evidence from bonus_chain_dynamics, but bonus_chain_dynamics hasn't run yet when the registry is built."**

Response: The registry does NOT rely on bonus_chain_dynamics output for the freespin signal. After v2's §5.2 revision, Tier 3 freespin uses `total_freespin_chain_spins > 0` (the raw CurFreeSpin-based counter from the merge loop accumulator, available post-merge before any emit runs). For M275 specifically, this counter is 0 (CurFreeSpin not set); the Tier 2 signal from `bonus_chain_dynamics.chain_count` cannot be used because bonus_chain_dynamics hasn't emitted yet. Instead, the registry uses Tier 3 raw `freespin_chain_spins` accumulator (`bonus_chain_lengths` in the merge loop, which is non-empty when freespin events occurred). This accumulator IS available post-merge. See §5.2 for the corrected tier definitions.

---

## §4 Plugin Protocol v2 **[v2 revised]**

### §4.1 `AnalyzerFeature` ABC extensions **[v2 revised]**

The following extends the existing `_base.py` without breaking the 4 current plugins.

```python
# fresh_slotlab/analyzer/features/_base.py  (EXTENDED SECTION)

from dataclasses import dataclass, field
from typing import ClassVar, Any

@dataclass
class ParseState:
    """Per-chunk context passed to extract().

    SCHEMA CONTRACT (Wave 2 stable):
    Guaranteed chunk_dict keys: ok, index, spins, bet, win,
      payout_id_hits, payout_id_win, payout_id_by_spin_type,
      payout_id_win_by_spin_type, spin_type_spins, spin_type_win,
      spin_type_paid_bet, symbol_counts, symbol_counts_by_col_by_spin_type,
      payline_hits, payline_win_approx, payline_winning_symbols,
      collect_count_total, cycle_peaks, final_cc_values,
      completed_cycles, upstream_feature_tally, bonus_chain_lengths,
      bonus_chain_max_ratios, jackpot_spins, jackpot_ids_seen,
      freespin_chain_spins, freespin_retriggers, bankruptcy_reps.

    mechanism_registry is ALWAYS None during extract() calls.
    It is only available at emit() time via summary["_mechanism_registry"].
    Plugins MUST NOT assume mechanism_registry is populated during extract().
    """
    chunk_dict: dict
    machine_id: str
    mode: int
    manifest: dict
    mechanism_registry: Any = None  # Always None in extract(); do not use here.


@dataclass
class PipelineContext:
    """Raw accumulator scalars passed as 3rd argument to every emit() call.

    These are values that live as local variables in PIA main() after the
    merge loop completes. They are NOT written to the summary dict by the
    existing pipeline; panel plugins need them to compute rtp_contribution_pp
    and other RTP-denominated metrics.

    ALL fields are required. The builder (PIA finalization block) populates
    all fields from local accumulator variables before calling the emit loop.

    NOTE: plugins must declare '_pipeline_context' in DECLARED_DEPS to signal
    they need this; the emit-loop runner passes the shared PipelineContext
    instance to every plugin's emit() regardless of DECLARED_DEPS (it is
    always available). DECLARED_DEPS declaration is informational only for ctx.
    """
    # RTP denominator: total credited bet across all paid spins.
    # Used by every plugin computing rtp_contribution_pp.
    # Source: local var 'effective_bet_for_rtp' in PIA main() post-merge.
    effective_bet_for_rtp: float

    # Total spins (paid + bonus) across all chunks.
    # Source: local var 'total_spins' in PIA main() post-merge.
    total_spins: int

    # Total paid-round sessions (deduplicated per session-centric semantics).
    # Source: local var 'total_paid_sessions' in PIA main() post-merge.
    total_paid_sessions: int

    # Total paid spins (subset of total_spins, paid rounds only).
    # Source: local var 'total_paid_spins' in PIA main() post-merge.
    total_paid_spins: int

    # BCM-specific: pending robots at time of analysis cutoff.
    # Source: local var 'clamp_pending_robots_total' in PIA main() post-merge.
    # Used by collect_mechanic plugin for correction formula.
    clamp_pending_robots_total: int

    # BCM-specific: robots that completed at least one full cycle.
    # Source: local var 'robots_with_pending_cycle' in PIA main() post-merge.
    robots_with_pending_cycle: int

    # MechanismRegistry instance. Available here in addition to
    # summary["_mechanism_registry"] (both reference the same object).
    mechanism_registry: Any  # MechanismRegistry


class AnalyzerFeature(ABC):
    FEATURE_ID: ClassVar[str] = ""
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ()
    SCHEMA_VERSION: ClassVar[int] = 1
    REQUIRES: ClassVar[tuple[str, ...]] = ()
    DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
    RTP_CONTRIBUTION: ClassVar[bool] = False
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    @abstractmethod
    def extract(self, parse_state: ParseState, chunk_dict: dict) -> dict:
        """Called once per chunk. Returns accumulator dict merged via reduce().
        mechanism_registry is always None here; do not read it."""
        return {}

    @abstractmethod
    def reduce(self, prev_acc: dict, this_acc: dict) -> dict:
        """Merge two extract() outputs across chunks."""
        return {**prev_acc, **this_acc}

    @abstractmethod
    def emit(self, final_acc: dict, summary: dict, ctx: PipelineContext) -> None:
        """Called once after all chunks. Writes plugin output to summary.
        ctx carries effective_bet_for_rtp and other raw accumulator scalars.
        Reads summary keys only if declared in DECLARED_DEPS."""
        ...
```

**Backward compatibility for 4 existing plugins**: The `emit()` signature adds a 3rd parameter `ctx`. Existing plugins that ignore it will fail unless their signatures accept `**kwargs` or are explicitly updated. C1 deliverable explicitly requires updating all 4 existing plugins' signatures to `emit(self, final_acc, summary, ctx)` where `ctx` is accepted but not used (Pattern A). This is a one-time update with no behavior change.

### §4.2 Wiring `extract()` and the emit loop in PIA **[v2 revised]**

#### Execution phase ordering contract (ENFORCED)

The following ordering is a hard invariant. Violating it causes silent wrong results:

```
Phase A: Merge loop (all chunks)
  → per-chunk: parse_chunk_response() → extract() for each plugin
  → accumulate: payout_id_win, spin_type_spins, freespin_chain_spins,
                bonus_chain_lengths, all_chains_by_feature, cycle_peaks, ...

Phase B: F1 inline code
  → produces: summary["player_impact"]["spin_type_breakdown"]
  → MUST complete before Phase C

Phase C: _build_mechanism_registry()
  → reads: payout_id_win, payline_records, freespin_chain_spins,
            bonus_chain_lengths (all from Phase A accumulators)
  → reads: summary["player_impact"]["spin_type_breakdown"] (from Phase B)
  → writes: summary["_mechanism_registry"]
  → MUST complete before Phase D

Phase D: Plugin emit loop (topologically sorted)
  → each emit() receives: final_acc, summary, PipelineContext
  → PipelineContext is constructed from Phase A accumulator locals before
    the emit loop starts
  → MUST run after Phase C
```

**Enforcement at runtime**: PIA's finalization block sets a sentinel after each phase:

```python
# PIA finalization block (pseudocode):

# Phase B: F1 inline
_compute_spin_type_breakdown(summary, ...)  # Block F1 inline code
assert "spin_type_breakdown" in summary["player_impact"], (
    "INVARIANT: F1 must write spin_type_breakdown before registry build"
)
_emit_preconditions_satisfied = True  # sentinel

# Phase C: Registry build
mechanism_registry = _build_mechanism_registry(
    payout_id_win=payout_id_win,
    payout_id_hits=payout_id_hits,
    payline_records=payline_records,
    freespin_chain_spins=freespin_chain_spins,  # Tier 3 raw
    bonus_chain_lengths=bonus_chain_lengths,     # Tier 3 raw
    spin_type_breakdown=summary["player_impact"]["spin_type_breakdown"],
    manifest=manifest,
)
summary["_mechanism_registry"] = mechanism_registry

# Phase D: Plugin emit loop
ctx = PipelineContext(
    effective_bet_for_rtp=effective_bet_for_rtp,
    total_spins=total_spins,
    total_paid_sessions=total_paid_sessions,
    total_paid_spins=total_paid_spins,
    clamp_pending_robots_total=clamp_pending_robots_total,
    robots_with_pending_cycle=robots_with_pending_cycle,
    mechanism_registry=mechanism_registry,
)
_machine_features = get_features_for_machine(manifest)  # filtered
_sorted_features = _topological_sort(_machine_features)  # Kahn's algorithm
for _feature in _sorted_features:
    for dep_key in _feature.DECLARED_DEPS:
        if dep_key not in summary:
            raise RuntimeError(
                f"Feature {_feature.FEATURE_ID} declared dep '{dep_key}' "
                f"absent from summary. Ordering error or typo."
            )
    _feature.emit(
        _feature_accs.get(_feature.FEATURE_ID, {}),
        summary,
        ctx,
    )

# Cleanup: remove all temp keys
for _key in list(summary):
    if _key.startswith("_"):
        del summary[_key]
```

#### Topological sort specification **[v2 new]**

The runner uses **Kahn's algorithm** (BFS-based) over the `REQUIRES` DAG:

- Build adjacency list: for each plugin P in `_machine_features`, for each fid in `P.REQUIRES`, add edge `fid → P.FEATURE_ID`.
- If a REQUIRES entry names a FEATURE_ID NOT present in `_machine_features`, raise `PluginMissingDependencyError(plugin=P.FEATURE_ID, missing_dep=fid)` at sort time (before any emit runs).
- If the DAG has a cycle, raise `PluginCyclicDependencyError(cycle=detected_cycle_list)` at sort time.
- Tie-breaking within same topological layer: lexicographic by FEATURE_ID. This ensures deterministic ordering across Python versions.
- Registration order in `ALL_FEATURES` does NOT determine emit order; only `REQUIRES` DAG and lexicographic tie-breaking matter.

#### Merge loop wiring (both paths) **[v2 new]**

Per `05 C1-1` and `01_pipeline_map.md §8 Duplication 1`, `extract()` must be wired in BOTH merge loop paths:

- From-cache path: `player_impact_analyzer.py:1614-1963`
- Online path: `player_impact_analyzer.py:2620-2960`

Both paths receive the same `_feature_accs` dict (carried across the two paths' loops). The `extract()` call is identical in both paths. C1 acceptance criteria explicitly verify both paths are patched.

#### Error handling (unchanged from v1 §4.3)

- `extract()` errors: log + return `{}`.
- `reduce()` errors: log + return `prev_acc`.
- `emit()` errors: log + set `summary["_feature_errors"][fid] = str(e)`. Do not crash.
- DECLARED_DEPS missing key: RuntimeError at emit-loop start (programming error).
- Topo-sort errors: RuntimeError at sort time (programming error).

### §4.3 `SCHEMA_VERSION` semantics

*(Unchanged from v1 §4.4.)*

---

## §5 Mechanism Registry Design **[v2 revised]**

### §5.1 Single source of truth rationale

*(Unchanged from v1 §5.1.)*

### §5.2 Detection sources and precedence **[v2 revised]**

Three source tiers, applied in priority order (highest to lowest):

**Tier 1 — Manifest-declared overrides** (highest precedence):

Fields in `manifest["mechanism_overrides"]` (new optional manifest field). Example:

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

**Tier 2 — Inferred analytics from pre-computed accumulators** (second precedence):

Inferred from accumulators that are computed during the merge loop (Phase A) and available before the emit loop (Phase D). These accumulators are NOT the same as the emit outputs of F5/F6 plugins (which haven't run yet). Specifically:

- **freespin (Tier 2)**: `len(bonus_chain_lengths) > 0` — the `bonus_chain_lengths` accumulator is populated in the merge loop when freespin chain events are observed (`pia:1866` and `pia:2592`). This accumulator has entries when there are actual freespin chains, and is zero-length when there are only wheel/bonus rounds with no freespin chains. For M279 (BCM+Wheel, no freespin): `bonus_chain_lengths = []` → `freespin_applicable = False` (CORRECT). For M275 (BCM+Freespin): `bonus_chain_lengths = [10, 10, ...]` → `freespin_applicable = True` (CORRECT).

- **jackpot (Tier 2)**: if `upstream_feature_tally` accumulator (built in merge loop from `FeatureWin` field) contains an entry with feature type matching a known jackpot-feature pattern, set `jackpot_applicable = True`. This is a secondary signal when Tier 3 raw PID threshold doesn't catch an edge case.

**CRITICAL NOTE — what Tier 2 is NOT**: Tier 2 does NOT use the `bonus_chain_dynamics.chain_count` output key from F6's `emit()`. That key does not exist at registry build time. Tier 2 uses the raw merge-loop accumulator `bonus_chain_lengths` list, which carries the same information (non-empty ↔ chain_count > 0) but is available pre-emit.

**Tier 3 — Raw field detection** (lowest precedence):

- **Jackpot PID detection (Tier 3 raw)**:
  1. Scatter marker detection runs FIRST. Build `scatter_marker_pids` = any PID where `payout_id_win[pid] == 0.0` AND there exists a payline record with `line_id == -1` for that PID. This set is established before jackpot detection.
  2. Jackpot PID candidates = `{pid for pid in payout_id_win if int(pid) >= 10000}`.
  3. Exclude any PID in `scatter_marker_pids` from jackpot candidates (scatter markers can have high numeric IDs but win=0).
  4. `jackpot_pid_set = jackpot_candidates - scatter_marker_pids`.
  5. `jackpot_applicable = bool(jackpot_pid_set)`.
  6. `_detection_source["jackpot_pid_set"] = "tier3_raw"`.

- **Freespin detection (Tier 3 raw — CORRECTED FROM v1)**:
  - Signal: `total_freespin_chain_spins > 0` where `total_freespin_chain_spins` is the sum of the `freespin_chain_spins` accumulator across all chunks.
  - **`behavior_name=free` MUST NOT be used as Tier 3 freespin proxy.** B_BCM_WHEEL machines (M279, M274, and 16 others — 18 total per `02_taxonomy.md §3`) have wheel/bonus SpinTypes classified as `behavior_name=free` but have zero actual freespin chains. Using `behavior_name=free` would false-positive `freespin_applicable=True` for all 18 B_BCM_WHEEL machines. This was the inconsistency between v1 §5.2 and v1 §12.3; v2 resolves it in favor of §5.2's correct definition.
  - `_detection_source["freespin_applicable"] = "tier3_raw_freespin_chain_spins"` when Tier 3 is used.

- **Tier 2 blocking rule**: if Tier 2 produces an explicit `False` result (e.g., `bonus_chain_lengths` is empty list), Tier 3 fallback does NOT activate. The Tier 2 explicit-False result is authoritative. Only when Tier 2 has NO signal (the accumulator key is absent, which should not occur in a well-formed run) does Tier 3 activate. In practice: if `bonus_chain_lengths = []` (Tier 2 explicit-False), `freespin_applicable = False` regardless of `total_freespin_chain_spins`.

- **Scatter detection (Tier 3 raw)**: any PID where `payout_id_win[pid] == 0.0` AND payline records show `line_id == -1` for that PID. The win==0 criterion correctly distinguishes M120's pid=666 (win=2.38M — real award PID, not scatter) from M275's pid=666 (win=0 — scatter trigger marker), as confirmed by `06 §2 Case 6`.

- **Payout groups (Tier 3 raw)**: `payout_groups_applicable = any(gid != 0 and win > 0 for gid, win in payout_group_win.items())`. This is a two-field check (non-zero group_id AND non-zero win), not just `max(keys)`, which prevents the `02 §3 C2-3` edge case where a machine has both group_id=0 and group_id=5 but the max-key check would still be wrong.

**Tier precedence summary**:

```
For each registry field:
  if field in manifest["mechanism_overrides"]:
      use Tier 1 value; _detection_source = "manifest"
  elif Tier 2 has explicit signal (positive or blocking-negative):
      use Tier 2 value; _detection_source = "tier2_inferred"
  else:
      use Tier 3 raw value; _detection_source = "tier3_raw_*"
```

### §5.3 Consumer API

*(Unchanged from v1 §5.3.)*

### §5.4 Persistence **[v2 revised]**

The registry persists in two places:

1. **In the summary dict** (embedded): same as v1. The existing `machine_mechanics` key is replaced by the registry's `to_summary_dict()` output.

2. **`mechanism_portrait.json` sidecar** (new, operator-visible): written alongside `player_impact_summary.json` in `reports/<M>/mode_<N>/versions/<rv>/` by `mechanism_portrait.py` after `write_summary_json()` completes.

**Sidecar path concurrency**: Each run has a unique `rv_<timestamp>_<hash>` directory created by the backend before PIA is invoked. Two concurrent runs for the same machine/mode produce different `rv_` directories. There is no file-level collision on the per-run sidecar. The optional `latest_portrait.json` pointer (Phase 3, deferred) uses atomic-rename (`Path.replace()`) per the `ConfigFileWriter` pattern in the codebase.

**Sidecar error handling** (per `memory/feedback_no_silent_swallow.md`):

```python
# mechanism_portrait.py — write() method (pseudocode)

def write(portrait_dict: dict, run_dir: Path) -> None:
    portrait_path = run_dir / "mechanism_portrait.json"
    error_path = run_dir / "_portrait_write_error.json"
    try:
        portrait_path.write_text(json.dumps(portrait_dict, indent=2))
    except Exception as e:
        # Do NOT crash the main run. Persist diagnostic instead.
        error_record = {
            "error": str(e),
            "error_type": type(e).__name__,
            "portrait_path": str(portrait_path),
            "stderr_tail": traceback.format_exc()[-2000:],
            "timestamp": datetime.utcnow().isoformat(),
        }
        try:
            error_path.write_text(json.dumps(error_record, indent=2))
        except Exception:
            pass  # If we can't write the error file either, accept silently
        # Log to PIA's logger (never swallow silently at log level)
        logger.error(
            "mechanism_portrait write failed: %s. "
            "Diagnostic written to %s.",
            e, error_path,
        )
        # Do NOT re-raise; portrait is non-blocking for the main run.
```

The presence of `_portrait_write_error.json` alongside a run directory signals that the portrait is missing. The `app.py` report-serving endpoint can surface this in report metadata (flagging the portrait as unavailable). This is a Phase 3 addition; for Phases C1–C6 the error file is written but not surfaced in the UI.

The sidecar JSON structure is as shown in v1 §5.4.

---

## §6 Auto-Inference Persistence

*(Unchanged from v1 §6. The `mechanism_portrait.json` sidecar is the primary operator surface.)*

---

## §7 PIA Inline Carve Plan

### §7.1 Ordering constraint

*(Carried forward from v1 §7.1 with one addition.)*

The cross-block dependencies from `01_pipeline_map.md §7` impose a strict ordering:

```
F1 (spin_type_rows, spin_type_breakdown) must run inline before MechanismRegistry build
MechanismRegistry must be built before machine_mechanics plugin emit()
F5 (upstream_feature.emit()) must run before F9 (collect_mechanic.emit())
F5 (upstream_feature.emit()) may need to run before F6 (bonus_chain_dynamics.emit())
  for the spin_type_to_feature dependency at pia:3501 (see §7.2 C5/C6 note)
```

**F5→F6 dependency (per `05 Q11`)**: `01_pipeline_map.md §7 Dependency D` states Block F6 uses `spin_type_to_feature` at `pia:3501` to categorize chain entries. This is in the finalization block, not the merge loop. When F5 and F6 are both carved to Pattern B plugins, `upstream_feature.emit()` must run before `bonus_chain_dynamics.emit()`. This is enforced via `REQUIRES`:

```python
class BonusChainDynamicsFeature(AnalyzerFeature):
    REQUIRES = ("upstream_feature",)  # enforces F5 before F6 in topological sort
    DECLARED_DEPS = ("_spin_type_to_feature",)  # F5 stashes this as a dep
```

F5's `upstream_feature.emit()` will write `summary["_spin_type_to_feature"]` in addition to `summary["_bcm_bonus_feature"]` and `summary["_bcm_bonus_source"]`.

### §7.2 Phase breakdown

#### Phase C1 — Mechanism Registry + emit loop fix (prerequisite) **[v2 revised]**

**Deliverables**:
1. `fresh_slotlab/analyzer/mechanism_registry.py` — `MechanismRegistry` class, `_build_mechanism_registry()` builder. Located in `fresh_slotlab/analyzer/` (not `core/`), per §8 rationale.
2. `feature_registry.py` fix: emit loop uses `get_features_for_machine(manifest)` instead of `ALL_FEATURES`.
3. `_base.py` extension: add `ParseState` dataclass, `PipelineContext` dataclass, `DECLARED_DEPS` ClassVar. Update `emit()` signature to accept `ctx: PipelineContext` as 3rd parameter.
4. `BankruptcySimulation` updated: add `DECLARED_DEPS = ("_bankruptcy_rows", "_bankruptcy_sim_session_spins")`. Update `emit()` signature to accept `ctx`. No behavior change.
5. All 4 existing Pattern A plugins: update `emit()` signature to `emit(self, final_acc, summary, ctx)` where `ctx` is accepted but not used. No behavior change.
6. PIA merge loop: wire `extract()` in **BOTH** the from-cache path (`pia:1614`) AND the online path (`pia:2620`). Both use the shared `_feature_accs` dict.
7. PIA finalization: add Phase B→C→D ordering with sentinel assertion (see §4.2 pseudocode).
8. PIA finalization: construct `PipelineContext` from local accumulator variables before emit loop.
9. `mechanism_portrait.py` writer — writes sidecar with error handling per §5.4.
10. Topological sort: implement `_topological_sort()` using Kahn's algorithm with cycle detection and missing-dependency detection (see §4.2).

**F1 ordering enforcement** (per `05 REV-1`): Phase C1 must explicitly document in the PIA finalization block code comment: `# INVARIANT: F1 inline must have written spin_type_breakdown before this call`. An assertion verifies the key is present before `_build_mechanism_registry()` is called.

**Dual-path extract() verification** (per `05 C1-1`): C1 acceptance criteria include a test that verifies both paths invoke `extract()` by checking that `_feature_accs` is non-empty after processing a from-cache chunk and after processing an online-path chunk. The test uses the `PayoutsBySpinTypeFeature` (which has a no-op `extract()` returning `{}`) as a probe — if `extract()` is called, the dict key is set (even to `{}`).

**Backward-compat during C1**:
- The 4 existing Pattern A plugins' signatures update is the only visible change. Assertions remain. No output changes.
- `BankruptcySimulation` behavior unchanged.
- `effective_analyzer_version` delta: 0 (no plugin source files change, no manifest changes).

**Rollback**: revert `_base.py` signature changes, revert PIA merge loop extract wiring (both paths), revert emit loop to `for _feature in ALL_FEATURES: _feature.emit(None, summary)`.

**Expected `effective_version` delta count**: 0.

---

#### Phase C2 — Gap #3 + Gap #5 + Gap #8: `payout_id_panel` Pattern B plugin **[v2 revised]**

**Inline blocks targeted**: Block F2 (`payout_id_rows`, `pia:3224-3290`) + Block F2b (`payout_group_rows`, `pia:3430-3445`).

**Deliverables**:
1. `features/payout_id_panel.py` — new Pattern B plugin.
   - `FEATURE_ID = "payout_id_panel"`, `DECLARED_DEPS = ("_mechanism_registry",)`.
   - **Gap #3 fix**: `if str(pid) in registry.scatter_marker_pids: category = "scatter_trigger"; trigger_only = True`.
   - **Gap #5 fix**: `payout_groups_applicable = registry.payout_groups_applicable`. Two-field check (non-zero group_id AND non-zero win) per corrected §5.2 definition.
   - **Gap #8**: adds `notes` field to rows ("jackpot" for PIDs in `registry.jackpot_pid_set`, "scatter trigger" for PIDs in `registry.scatter_marker_pids`).
2. Block F2 and F2b inline code removed atomically with plugin promotion.
3. M275 manifest: adds `"payout_id_panel"` to `analyzer_features`.
4. All 253 non-variant manifests: `"payout_id_panel"` added.
5. **3 import sites updated** (acceptance criterion per §15.5):
   - `pia:4816-4827` (both try blocks for package + script mode): add `from analyzer.features.payout_id_panel import PayoutIdPanelFeature`
   - `versioning.py:165-176`: add import
   - `validate_manifests.py:43-47`: add import

**Phase C2 behavior changes for 50 non-666 scatter marker machines** (per `05 REV-5`): Machines with non-666 scatter marker PIDs (50 machines per `02_taxonomy.md §5 Ax6`) will have their scatter marker pid reclassified from `category: "paid"` to `category: "scatter_trigger"`. This IS a behavior change, not an additive-only change. The operator benefit is correct classification. Any machine whose `rtp_integrity_contract.required_attribution_anchors` includes the scatter marker PID expecting `cat=paid` must have its manifest updated — but since anchor classification has never been by category (anchors are by PID, not by category), this does not affect L3 integrity checks.

**Backward-compat during C2**:
- Old reports: `payout_ids_top20` rows missing `notes`, `trigger_only`. Frontend renders them as absent (safe per additive contract).
- 50 scatter-marker machines: old reports show `cat=paid` (wrong); new reports show `cat=scatter_trigger` (correct). Old reports become historical.
- `payout_groups_top20` shape change: old reports may have 1-row list; new reports have empty list for all-zero machines. Frontend must handle empty list gracefully (not assume non-empty).

**Rollback**: restore F2 and F2b inline code, revert manifests, remove plugin file.

**Expected `effective_version` delta count**: 253.

---

#### Phase C3 — Gaps #7 + #8: `payouts_by_spin_type` Pattern A → B **[v2 revised]**

*(Core unchanged from v1 §7.2 C3. Deliverable count corrected.)*

**Inline blocks targeted**: Block F3 (`payouts_by_spin_type`, `pia:3306-3349`).

**Deliverables**:
1. Promote `features/payouts_by_spin_type.py` from Pattern A to Pattern B.
   - `DECLARED_DEPS = ("_mechanism_registry",)` added (to read scatter/jackpot labels for `notes`).
   - Adds `paylines`, `shape`, `cols`, `notes` fields. Gap #7 closed.
   - `_st_label` reconstruction: reads `summary["player_impact"]["spin_type_breakdown"]` (written by F1 inline in Phase B, guaranteed present before emit loop per §4.2 ordering contract).
2. Block F3 inline code removed.
3. `SCHEMA_VERSION` bumps 1 → 2. `REGISTERED_FALLBACK_RULES = {1: {"missing_fields": ["shape", "cols", "paylines", "notes"]}}`.
4. **3 import sites updated** (no new import file — this is a modification of existing import; verify the existing import at all 3 sites is for the updated class, not a stale Pattern A reference).

**Expected `effective_version` delta count**: 253.

---

#### Phase C4 — Gaps #1 + #2: `machine_mechanics` Pattern B plugin **[v2 revised]**

**Inline blocks targeted**: Block F8 (`machine_mechanics`, `pia:4457-4510`).

**Deliverables**:
1. `features/machine_mechanics.py` — new Pattern B plugin.
   - `FEATURE_ID = "machine_mechanics"`, `DECLARED_DEPS = ("_mechanism_registry",)`.
   - **Gap #1 fix**: `machine_mechanics.jackpot.applicable = bool(registry.jackpot_pid_set)`.
   - **Gap #2 fix**: `machine_mechanics.free_spin.applicable = registry.freespin_applicable`.
   - RTP computation uses `ctx.effective_bet_for_rtp` as denominator.
2. Block F8 inline code removed.
3. M275 manifest and all 253 non-variant manifests: add `"machine_mechanics"`.
4. M275 manifest corrections (also in C4 or earlier): `spin_type_convention.paid = [140]`, `expected_paid_st = [140]`, `expected_bonus_st = [126]`.
5. **3 import sites updated**: add `from analyzer.features.machine_mechanics import MachineMechanicsFeature` to all 3 sites.

**C4 risks**: Per `05 C4-1`, the 26 jackpot-PID machines' `machine_mechanics.jackpot.applicable` will flip from `false` to `true`. For each of these 26 machines, the implementer must verify their `rtp_integrity_contract.required_attribution_anchors` does not create a Layer 3 conflict. This is an acceptance criterion for Phase C4.

**Expected `effective_version` delta count**: 253.

---

#### Phase C5 — `collect_mechanic` and `upstream_feature` Pattern B plugins (BCM family) **[v2 revised]**

**Inline blocks targeted**: Block F5 (`upstream_feature_breakdown`, `pia:3431-3872`) + Block F9 (`collect_mechanic`, `pia:4608-4732`).

**Deliverables**:
1. `features/upstream_feature.py` — Pattern B plugin.
   - `FEATURE_ID = "upstream_feature"`.
   - Absorbs Block F5 (440 lines).
   - Writes `summary["player_impact"]["upstream_feature_breakdown"]`.
   - Also writes `DECLARED_DEPS` outputs: `summary["_bcm_bonus_feature"]`, `summary["_bcm_bonus_source"]`, `summary["_spin_type_to_feature"]`.
   - The three calls to `_resolve_bonus_feature()` consolidated to one call in `upstream_feature.emit()`. The `feature_match` and `bonus_feature` outputs both derive from this single call (they are different return values of the same function, not two separate calls).
   - `ctx.effective_bet_for_rtp` used for RTP computations.
2. `features/collect_mechanic.py` — Pattern B plugin.
   - `FEATURE_ID = "collect_mechanic"`.
   - `REQUIRES = ("upstream_feature",)` — topological sort guarantees upstream_feature emits first.
   - `DECLARED_DEPS = ("_bcm_bonus_feature", "_bcm_bonus_source", "_mechanism_registry")`.
   - Uses `ctx.clamp_pending_robots_total` and `ctx.robots_with_pending_cycle` for correction formula (no more local variable access needed — these are in `PipelineContext`).
   - Uses `ctx.effective_bet_for_rtp` for RTP denominator.
3. Block F5 and F9 inline code removed atomically.
4. `_load_bcm_pairings()` consolidated to one call in `upstream_feature.emit()`.
5. **3 import sites updated** for both `upstream_feature` and `collect_mechanic` (6 total insertion points across 3 files).

**F5→F6 ordering note**: `BonusChainDynamicsFeature.REQUIRES = ("upstream_feature",)` ensures F5 emits before F6. This handles the `spin_type_to_feature` dependency at `pia:3501` (finalization block) now that both are plugins. F6 reads `summary["_spin_type_to_feature"]` via `DECLARED_DEPS`.

**Expected `effective_version` delta count**: 253.

---

#### Phase C6 — `bonus_chain_dynamics` Pattern B plugin **[v2 revised]**

**Inline blocks targeted**: Block F6 (`bonus_chain_dynamics`, `pia:3874-3962`).

**Deliverables**:
1. `features/bonus_chain_dynamics.py` — Pattern B plugin.
   - `FEATURE_ID = "bonus_chain_dynamics"`.
   - `REQUIRES = ("upstream_feature",)`.
   - `DECLARED_DEPS = ("_spin_type_to_feature",)`.
   - Absorbs Block F6.
   - `ctx.effective_bet_for_rtp` for RTP denominators.
2. Block F6 inline code removed.
3. **3 import sites updated** for `bonus_chain_dynamics`.

**Expected `effective_version` delta count**: 253.

---

### §7.3 Post-carve PIA state

*(Unchanged from v1 §7.3.)*

After C1 through C6, PIA's finalization block reduces to:
- Block F1 inline: `spin_type_rows` + `spin_type_breakdown` (stays inline; Phase B in ordering)
- Block F4: `reel_marginal_by_spin_type` (stays inline or existing Pattern A plugin)
- Block F7: streaks/bankruptcy finalization (stays inline; sets `_bankruptcy_rows` DECLARED_DEP)
- `_build_mechanism_registry()` call (Phase C)
- `PipelineContext` construction
- Plugin emit loop with topological sort (Phase D)
- RTP integrity gate (unchanged)
- Write phase (unchanged)

---

### §15.5 Per-phase acceptance criteria table **[v2 new]**

| Phase | New plugins | 3 import sites | Other acceptance criteria |
|---|---|---|---|
| C1 | None (no new plugin) | Verify existing 4 plugins still imported at all 3 sites | `extract()` wired in BOTH merge paths; `PipelineContext` constructed; topo-sort implemented; F1 sentinel assertion present |
| C2 | `payout_id_panel` | Add `PayoutIdPanelFeature` import at `pia:4816-4827` (both try blocks), `versioning.py:165-176`, `validate_manifests.py:43-47`; verify `len(ALL_FEATURES) == 5` after | Block F2/F2b removed; 253 manifests updated; scatter-marker classification verified for M275 (pid=666 → scatter_trigger) and M37 (no scatter marker, no change) |
| C3 | `payouts_by_spin_type` (modified, not new) | Verify existing import at 3 sites references the promoted Pattern B class (not a stale Pattern A stub) | Block F3 removed; SCHEMA_VERSION bumped to 2; `shape/cols/paylines/notes` fields present in M275 report |
| C4 | `machine_mechanics` | Add `MachineMechanicsFeature` import at all 3 sites; verify `len(ALL_FEATURES) == 6` | Block F8 removed; M275 `machine_mechanics.jackpot.applicable: true`; M14 `machine_mechanics.jackpot.applicable: false`; 26 jackpot machines verified no L3 conflict |
| C5 | `upstream_feature`, `collect_mechanic` | Add both at all 3 sites; verify `len(ALL_FEATURES) == 8` | Block F5/F9 removed; `_resolve_bonus_feature()` called once; topo-sort places upstream_feature before collect_mechanic (verify via log) |
| C6 | `bonus_chain_dynamics` | Add at all 3 sites; verify `len(ALL_FEATURES) == 9` | Block F6 removed; topo-sort places upstream_feature before bonus_chain_dynamics; `chain_count` value matches pre-carve value for M275 |

---

## §8 Hash Composition **[v2 revised]**

### §8.1 Does the algorithm change?

**No.** Unchanged from v1 §8.1.

### §8.2 New dimensions introduced **[v2 revised]**

**`mechanism_overrides` hash dimension** (unchanged from v1): when `mechanism_overrides` is non-empty in the manifest, its contents are hashed into `effective_analyzer_version`.

**`mechanism_registry.py` hashing gap (explicitly stated per `05 REV-4`)**: `mechanism_registry.py` is placed in `fresh_slotlab/analyzer/` (not `core/`). Per `03_coupling_audit.md §2.1 Symbol 1`, only `core/*.py` files feed `compute_base_analyzer_version`. Therefore, **changes to `mechanism_registry.py` are NOT reflected in `effective_analyzer_version`**. If the jackpot threshold changes from ≥10000 to ≥9000, or if a new detection rule is added to the registry builder, old reports are NOT automatically marked stale.

This is the same pre-existing gap acknowledged for `round_classification.py` and `round_win.py` in v1 §8.2. The mitigation is:
- Operators must manually trigger report regeneration when the detection logic in `mechanism_registry.py` changes.
- Change log entries for `mechanism_registry.py` should explicitly note "affects all machines that use the changed detection field; operator must regenerate."
- A future enhancement could add `mechanism_registry.py` to the base hash explicitly (not via the `core/` glob), but this is deferred — the blast radius of adding it to the base hash is fleet-wide invalidation, identical to Case Study A in `03_coupling_audit.md §5`.

The plugin files that import `mechanism_registry.py` ARE hashed (per plugin file content). But changing `mechanism_registry.py` without changing any plugin file leaves the plugin file hashes unchanged. This is the gap.

**What is NOT hashed** (unchanged from v1):
- `round_classification.py`, `round_win.py`, `trigger_sessions.py`
- `mechanism_portrait.py`
- `configs/bcm_pairings.json`
- `mechanism_registry.py` (acknowledged above)

### §8.3 Worked example

*(Unchanged from v1 §8.3. Count corrected from 254 to 253.)*

After Phase C4 (universal addition of `machine_mechanics` to all 253 manifests), all 253 machines' `effective_analyzer_version` changes. The surgical property activates only when feature sets diverge (e.g., a future `machine_mechanics_bcm` plugin declared only by BCM machines).

### §8.4 Migration of existing reports

*(Unchanged from v1 §8.4. Count corrected: "253 machines" not "254".)*

---

## §9 Manifest Schema Evolution

*(Unchanged from v1 §9.)*

---

## §10 8 Gaps Closure Table

*(Unchanged from v1 §10. All 8 gaps, same ownership, same fix sketches.)*

---

## §11 Migration and Rollout **[v2 revised]**

### §11.1 Phased rollout strategy

*(Unchanged from v1 §11.1.)*

### §11.2 Backward compatibility table **[v2 revised]**

| Artifact | During migration | After full carve |
|----------|-----------------|-----------------|
| 336 on-disk summaries | Readable unchanged. Freshness badge flips per phase. | Readable. Historical. Re-runnable from cache. |
| `payout_ids_top20` field name | Unchanged throughout | Unchanged |
| `payout_ids_top20` row schema | Additive fields (`notes`, `trigger_only`) in C2 | Same as C2 |
| **`payout_ids_top20` scatter marker category** | **C2 BEHAVIOR CHANGE**: 50 machines' scatter marker pid moves from `cat=paid` to `cat=scatter_trigger` | Correct per design |
| `payout_groups_top20` shape | C2: may change from 1-row to empty list for ~247 machines | Empty for all-zero machines; populated for 9 real-group machines |
| `payouts_by_spin_type` row schema | Additive fields (`shape`, `cols`, `paylines`, `notes`) in C3 | Same as C3 |
| `machine_mechanics` field values | C4: `jackpot.applicable` and `free_spin.applicable` corrected (26 machines flip jackpot; many flip freespin) | Values now correct |
| `machine_mechanics` key structure | Unchanged | Unchanged |
| `collect_mechanic` key structure | Unchanged | Unchanged |
| `upstream_feature_breakdown` key structure | Unchanged | Unchanged |
| `bonus_chain_dynamics` key structure | Unchanged | Unchanged |
| `analyzer_version` legacy field | Unchanged | Unchanged |
| `effective_analyzer_version` | Flips per phase for machines affected | Stable post-C6 |
| RTP integrity L1/L2/L3 | PASS throughout | Same |
| `mechanism_portrait.json` sidecar | Newly written alongside summary per run | Present for all post-C1 runs |

### §11.3 Rollback path per phase

*(Unchanged from v1 §11.3.)*

### §11.4 B_BCM_FREESPIN_WHEEL archetype first **[v2 revised]**

The "107 fleet entities benefit" claim requires precise framing (per `05 REV-7`):

- **What benefits from M275-specific manifest corrections**: M275 only. The corrections (`spin_type_convention.paid = [140]`, etc.) are M275-specific. They do not flow to M273 variants (which inherit from M273.json, not M275.json).

- **What benefits from universal plugin addition**: all 253 non-variant manifests, including M273.json. When M273.json receives `machine_mechanics` and `payout_id_panel` (universal Phase C2/C4), M273's 85 variants inherit those features via `inherits_from: "M273"`. This is what produces the "107 entities" figure (20 B_BCM_FREESPIN_WHEEL base machines + 87 M273 variants). The benefit is from the universal addition, not from M275-specific fixes.

- **Phrasing in operator communications**: "Fixing M275 as the pilot validates the universal plugin addition that benefits the full B_BCM_FREESPIN_WHEEL archetype (20 bases + 87 variants = 107 entities)."

### §11.5 No report deletion

*(Unchanged from v1 §11.5.)*

### §11.6 M273 variants auto-coverage via variant resolution **[v2 new]**

Per `memory/project_variants_fleet.md`, variant manifests use `inherits_from` pointing to a base machine ID. The variant resolution in `manifest_loader.py` applies the base machine's `analyzer_features` list to the variant (with per-variant overrides applied on top).

When Phase C2 adds `payout_id_panel` to M273.json, the 85 M273 variants that `inherits_from: "M273"` inherit the new feature automatically. No per-variant manifest update is needed. This is confirmed by the variant fleet design: "唯一跨机台 coupling 是 md5 fanout；所有 resolution 走 variants_map" (`memory/project_variants_fleet.md`).

**What variant resolution does NOT do**: it does not cascade M275.json's `mechanism_overrides` or `spin_type_convention` corrections to M273 variants. Those corrections are M275-specific. M273 and its variants are separate machines with their own spin_type conventions.

**Acceptance criterion**: after Phase C2, verify that one M273 variant (e.g., M273$selector_1) reports `effective_analyzer_version` that matches the base M273 version plus the new `payout_id_panel` hash dimension. Verify that M275$-variants (if any) similarly inherit M275's features.

### §11.7 Batch-rebuild operator workflow **[v2 new]**

Per `05 Q7`, each of the 5 phases that universally add plugins to 253 manifests (C2 through C6) triggers a fleet-wide `effective_analyzer_version` flip. The operator burden:

- Each phase: 253 non-variant machines × (modes 1, 2, 5, 7 where applicable) ≈ 253 × 2.5 avg modes ≈ 633 stale report entries per phase.
- 5 phases: ~3165 stale entries total (not 5060 — the 4-modes-per-machine figure overstates; most machines are analyzed in fewer modes).
- "Stale" means "freshness badge shows historical" — old reports remain readable; operators regenerate on demand.

**Operator workflow**:
1. Phase N ships (manifests updated, new plugin file added).
2. Operator opens console batch-run UI.
3. Selects "Regenerate all historical (from cache)" — this uses `FleetRefreshManager` (existing batch machinery) to re-run PIA with `--from-cache` for all machines/modes that have valid cached chunks.
4. For machines with no valid cached chunks (M281 per `02_taxonomy.md §13`, and any others with missing rawdata): these cannot be regenerated from cache. They remain historical until new sampling is done. This is acceptable per the no-proactive-fetch constraint (`memory/feedback_no_proactive_fetch.md`).
5. Estimated wall-clock for full fleet regen from cache: 253 machines × ~30s per machine (existing benchmark) ≈ ~2 hours if run serially; parallel batch with existing concurrency settings would take ~30 min.

**Phase-by-phase rollout reduces rebuild cadence**: operators can choose to run the batch-rebuild after C1+C2 together, then after C3+C4 together, etc. The phases are designed to be independent deployments, but the freshness flip is driven by manifest update commits, not by deployment timing. The operator decides when to trigger batch regeneration.

**Machines with stale or broken cache**: these are a pre-existing operational concern (59 machines failing L2 smoke per `session_artifacts/_impl/STATUS.md`). The proposal does not make this worse — it does not delete any cache. It does not require fresh sampling of these machines.

---

## §12 M275 End-to-End Walk **[v2 revised]**

### §12.1 Chunk parse

*(Unchanged from v1 §12.1.)*

### §12.2 Merge loop

*(Unchanged from v1 §12.2.)*

### §12.3 Finalization — MechanismRegistry build **[v2 revised]**

After all chunks merged, Phase B runs F1 inline → `spin_type_breakdown` written to summary. Then `_build_mechanism_registry()` is called (Phase C):

- **Tier 1**: M275 manifest has no `mechanism_overrides` → Tier 1 empty.

- **Tier 3 raw (scatter detection first)**:
  `payout_id_win["666"] = 0.0` + payline record for pid 666 with `line_id=-1` → `scatter_marker_pids = {"666"}`. `_detection_source["scatter_marker_pids"] = "tier3_raw"`.

- **Tier 3 raw (jackpot detection, after scatter exclusion)**:
  Jackpot PID candidates from `payout_id_win`: `{pid for pid in payout_id_win if int(pid) >= 10000}` = `{"27502", "27503", "27504", "666"}`. Exclude scatter_marker_pids: `{"27502", "27503", "27504", "666"} - {"666"} = {"27502", "27503", "27504"}`. `jackpot_pid_set = {"27502", "27503", "27504"}`. `_detection_source["jackpot_pid_set"] = "tier3_raw"`.

- **Tier 2 (freespin, from merge-loop accumulator)**:
  `bonus_chain_lengths` accumulator = `[10, 10, 10, ...]` (908 entries × 10 spins each). `len(bonus_chain_lengths) > 0` → Tier 2 explicit-True. `freespin_applicable = True`. `_detection_source["freespin_applicable"] = "tier2_inferred"`. (NOTE: `behavior_name=free` signal is NOT used per v2 §5.2 correction — this signal would false-positive on B_BCM_WHEEL machines.)

- **Tier 3 raw (freespin backup — would also work for M275)**:
  `total_freespin_chain_spins = sum(freespin_chain_spins accumulator) = 9090`. But Tier 2 is authoritative, so Tier 3 is not used here. Detection source remains `"tier2_inferred"`.

Registry is built. `summary["_mechanism_registry"] = registry`.

### §12.4 Plugin emit sequence

*(Unchanged from v1 §12.4, with one correction: `PipelineContext` is now passed to every emit call.)*

**F1 inline** (Phase B, already complete): `spin_type_breakdown` with ST140 (paid) and ST126 (free) already in summary.

**Plugin emit loop** (Phase D, topologically sorted):

`upstream_feature.emit(acc, summary, ctx)` → writes `_bcm_bonus_feature`, `_bcm_bonus_source`, `_spin_type_to_feature`.

`payout_id_panel.emit(acc, summary, ctx)`:
- Uses `ctx.effective_bet_for_rtp` for `rtp_contribution_pp` computation.
- pid 666: in `registry.scatter_marker_pids` → `category = "scatter_trigger"`, `trigger_only = True`, `notes = "scatter trigger"`. Gap #3 CLOSED.
- pids 27502/27503/27504: in `registry.jackpot_pid_set` → `notes = "jackpot"`. Gap #8 enrichment applied.
- `registry.payout_groups_applicable = False` → `payout_groups_top20 = []`. Gap #5 CLOSED.

`payouts_by_spin_type.emit(acc, summary, ctx)`: adds `paylines`, `shape`, `cols`, `notes`. Gap #7 CLOSED.

`bonus_chain_dynamics.emit(acc, summary, ctx)`: reads `_spin_type_to_feature`. Unchanged behavior. chain_count=908.

`machine_mechanics.emit(acc, summary, ctx)`:
- `registry.jackpot_pid_set = {"27502","27503","27504"}` → `jackpot.applicable = True`. Gap #1 CLOSED.
- `registry.freespin_applicable = True` → `free_spin.applicable = True`. Gap #2 CLOSED.
- Uses `ctx.effective_bet_for_rtp` for RTP denominators.

`collect_mechanic.emit(acc, summary, ctx)`:
- Reads `_bcm_bonus_feature`, `_bcm_bonus_source` (from upstream_feature via DECLARED_DEPS).
- Uses `ctx.clamp_pending_robots_total` and `ctx.robots_with_pending_cycle` for correction formula.
- `estimated_correction_pp = 0.0` (correct — `ctx.robots_with_pending_cycle = 0`; see Gap #6 resolution).

`bankruptcy_simulation.emit(acc, summary, ctx)`: unchanged behavior.

### §12.5 Portrait write

`mechanism_portrait.py` writes sidecar with error handling per §5.4. All gaps #1-#3, #5, #7-#8 closed. Gap #6 labeled correctly. Gap #4 deferred.

### §12.6 RTP integrity check

*(Unchanged from v1 §12.6.)*

---

## §13 "Zero-Code New Machine" Property **[v2 revised]**

### §13.1 Precise statement post-this-work **[v2 revised]**

**Case A — Pure vanilla**: HOLDS. (Unchanged from v1.)

**Case B — Recombination of known mechanics**: HOLDS for standard BCM combinations after this work. (Unchanged from v1.)

**Explicit out-of-scope for L2 failures** (per `06 R2`):

The following machines have pre-existing L2 attribution failures that are NOT fixed by this proposal:

| Machine | Archetype | L2 failure | Root cause | Proposed path |
|---|---|---|---|---|
| M250 | B_BCM_FREESPIN_WHEEL | `_unattributed_st140` (40.66%) + `_unattributed_st2` (5.94%) — 100% fallback | 20×1 strip grid payline topology not handled by existing `RoundWinRule` | Separate RoundWinRule investigation task |
| M239 | B_BCM_FREESPIN_WHEEL | Same 20×1 strip grid issue | Same | Same |
| M272 | B_BCM_FREESPIN | `_unattributed_st126` (freespin rounds not attributed) | RoundWinRule attribution gap for freespin ST | Separate per-machine onboarding / `BCMCycleAnchorRule` investigation |
| M279 | B_BCM_WHEEL | `_unattributed_st2` (4.35%) | Wheel spin RoundWinRule attribution gap | Same as M272 |

This proposal does NOT fix these L2 failures. These machines will still fail L2 after full C1–C6 carve. The mechanism registry will correctly identify their freespin/BCM mechanics (improving machine_mechanics panel), but the RTP attribution gap in `payout_ids_top20` persists.

The `00_brief.md §3` mention of M250 as a "fleet-smoke L2 failure" was contextual (showing the breadth of unaddressed gaps) and does not commit this proposal to fixing M250's L2 failure. The brief's stated goal is "M275 as the driving case" with mechanism detection improvement, not fleet-wide L2 attribution healing.

**Residual Case B requiring code**: unchanged from v1 §13.1 (machines with jackpots at PID < 10000, machines with novel detection signal types).

**Case C — Novel mechanic**: DOES NOT HOLD. Unchanged from v1 §13.1.

### §13.2 Summary table **[v2 revised]**

| Case | Archetype count | Zero-code after this work? | Residual requirement |
|------|-----------------|---------------------------|---------------------|
| A — Vanilla | 53 base | YES | None |
| B — BCM recombination (standard) | ~50 of 57 BCM base | YES (mechanism detection) | Manifest with correct `spin_type_convention`; L2 attribution requires RoundWinRule for machine's ST set |
| B — BCM with 20×1 strip grid (M250/M239) | 2 | YES for mechanism detection; NO for L2 | Separate RoundWinRule task |
| B — BCM freespin with non-standard attribution (M272, M279) | 2+ | YES for mechanism detection; NO for L2 | Separate RoundWinRule task |
| B — BCM with non-standard ST (M108/M117/M125 ST=101) | 3 | PARTIAL | Manifest `spin_type_convention` override |
| B — Multiplier wilds | Any machine with wild multipliers | NOT YET (gap #4) | Multiplier inference restart |
| C — Single mechanic (freespin/respin/wheel) | 132 base | NO | Cluster-shared plugin per mechanic type |
| D — Complex/outlier | 14 base | NO | Bespoke plugin per machine |

**The "107 entities benefit" claim**: the universal plugin addition (not M275-specific manifest corrections) benefits all 253 non-variant bases plus their inherited variants. The B_BCM_FREESPIN_WHEEL archetype (20 bases + 87 M273 variants = 107 entities) is the largest single-archetype beneficiary because M273 has the most variants in the fleet. The mechanism by which M273 variants benefit is `inherits_from` cascade from M273.json → M273's 85 variants, confirmed by variant fleet design (`memory/project_variants_fleet.md`).

---

## §14 Out of Scope Deferrals **[v2 revised]**

### §14.1 Multiplier wild auto-inference resume (Gap #4)

*(Unchanged from v1 §14.1.)*

### §14.2 Frontend renderer registry / SCHEMA_VERSION CI

*(Unchanged from v1 §14.2.)*

### §14.3 PIA legacy `analyzer_version` field deprecation

*(Unchanged from v1 §14.3.)*

### §14.4 `round_classification.py` / `round_win.py` / `trigger_sessions.py` hashing

*(Unchanged from v1 §14.4.)*

### §14.5 Merge loop duplication (from-cache vs. online path)

*(Unchanged from v1 §14.5. Note: v2 requires extract() wired in BOTH paths in C1, but does not require deduplicating the merge loop itself.)*

### §14.6 Cluster-specific plugins for C_* archetypes

*(Unchanged from v1 §14.6.)*

### §14.7 M250, M272, M279 L2 attribution failures **[v2 new]**

The L2 attribution failures for M250, M239, M272, and M279 are explicitly out of scope for this proposal. They require separate RoundWinRule investigation, as noted in §13.1. This proposal improves their mechanism detection (machine_mechanics panel) but does not fix the underlying attribution gaps. Follow-up work: a separate arch-team session or impl-team task for each affected machine family.

### §14.8 `REGISTERED_FALLBACK_RULES` production consumption

*(Carries forward from v1 §14.2.)*
The `REGISTERED_FALLBACK_RULES` mechanism is declared in `_base.py` but not yet consumed by production code (`03_coupling_audit.md §4.4`). For Phase C3's additive field additions, old reports render correctly without the rules (absent fields → frontend ignores). For future breaking schema changes, the frontend renderer registry consumption must be implemented first. This is deferred to Phase 4 of the original arch proposal.

---

## §15 Open Questions for W3 v2

*(v1 Q2 removed — registry placement resolved: `fresh_slotlab/analyzer/`. v1 Q1, Q3-Q7 renumbered. New Q8 added.)*

**Q1: Gap #6 — Is `estimated_correction_pp = 0.0` a formula bug or correct output?**

Per `06 §2 Case 1` validator analysis: M275 report shows `robots_with_pending_cycle = 0` and `completed_cycles_total = 64`. The correction formula correctly returns 0.0 when no robots have incomplete cycles. Gap #6 verdict from validator: **formula is correct; the issue is a labeling confusion** — `clamp_warning` fires because pending paid spins are high (toward next cycle trigger), not because cycles are incomplete. The portrait should add a human-readable distinction: "pending_paid_spins_pct: 80%" vs "pending_cycle_count: 0". No formula change required. **This question is tentatively resolved by validator evidence; W3 v2 should confirm.**

**Q2: Is M275 a trigger-session machine (`layer4_applicable` true or false)?**

*(v1 Q3, renumbered.)*

M275 has freespin triggered by scatter (pid=666). Does it use `compute_trigger_sessions()` re-attribution? Binary: (a) trigger-session machine → `layer4_applicable: false`; (b) not → `layer4_applicable: true`. Must be determined from rawdata analysis before M275 manifest is corrected in Phase C4.

**Q3: DECLARED_DEPS validation — emit() error handling when dep is present but semantically empty (None / wrong type)?**

*(v1 Q4 partially resolved: topological sort specified as Kahn's algorithm in §4.2. Remaining issue:)*

The dep validation checks `if dep_key not in summary`. It does not catch `summary["_bcm_bonus_feature"] = None` (key present but null). Should the validator also check `if summary[dep_key] is None: raise ...`? This is a per-dep semantic question. The current design (key-presence check only) is correct if all dep-writing plugins guarantee non-None values. Should the Protocol require non-None dep values, or is None acceptable for optional deps?

**Q4: Should `payout_id_panel` plugin combine F2 and F2b, or should `payout_groups_top20` remain inline?**

*(v1 Q5.)* Is there any machine where `payout_groups_top20` requires different accumulator access than `payout_ids_top20`? If yes, split into two plugins. The current design combines them for simplicity. W3 v2 should validate this combination is safe.

**Q5: Should `mechanism_overrides` manifest changes trigger `effective_analyzer_version` hash change?**

*(v1 Q6.)* The v2 design (same as v1) adds `mechanism_overrides` to the hash when non-empty. Should ALL non-`analyzer_features` manifest fields be hashed? Would that be too broad (any comment edit triggers version flip)?

**Q6: BCM machines with non-standard SpinType conventions (M108/M117/M125 with ST=101) — does the mechanism registry's freespin detection handle them?**

*(v1 Q7.)* The Tier 2 signal (`len(bonus_chain_lengths) > 0`) is ST-agnostic. But does F1's `spin_type_behavior` classification correctly label ST=101-family machines' bonus STs? Validator should check a live report for one of these machines.

**Q7: Does `effective_analyzer_version` stay stable across Phase C3's `payouts_by_spin_type` SCHEMA_VERSION bump?**

The `SCHEMA_VERSION` ClassVar lives inside the plugin's `.py` file. Bumping SCHEMA_VERSION from 1 to 2 changes the plugin file's content → changes `compute_hash()` output → changes `effective_analyzer_version` for all 253 machines declaring `payouts_by_spin_type`. This is the intended behavior (all machines' version flips for C3, signaling that old reports need regeneration). But the question is: does `SCHEMA_VERSION` also appear in the emitted summary somewhere, and can the frontend distinguish old-schema from new-schema reports? W3 v2 should verify that the frontend's `payouts_by_spin_type` renderer handles absent `shape`/`cols`/`paylines` fields gracefully (the "ignores if absent" contract).

---

## §16 Open Questions Surviving v2 (for User or W3 v2 Decision) **[v2 new]**

Items that the designer cannot resolve without external input:

**SQ1 — Gap #6 formula verdict**: the validator evidence strongly suggests the formula is correct and Gap #6 is a labeling issue. If the user or W3 v2 critic confirms this, Gap #6 can be closed by adding a portrait label improvement and no formula change. The proposal currently marks it as "formula investigation required." If confirmed correct, the Phase C5 deliverable for Gap #6 simplifies from "formula fix" to "portrait label improvement."

**SQ2 — `PipelineContext` field completeness**: the `PipelineContext` dataclass in §4.1 lists 6 fields. Are there other raw accumulator scalars that panel plugins need? The designer identified these from `01_pipeline_map.md §7 Dependency E` and EC6/EC7 from the critique. If the implementer discovers additional required scalars during Phase C5 (carving F5/F9), the dataclass must be extended before Phase C5 ships. This is an implementation-time discovery that cannot be fully pre-specified without reading all 440 lines of Block F5 and 124 lines of Block F9.

**SQ3 — Topological sort tie-breaking when feature ordering matters for performance**: the current tie-breaking rule is lexicographic by FEATURE_ID. If a future Phase adds two plugins where one is computationally cheap and the other expensive, and there's no REQUIRES dependency between them, lexicographic order may run the expensive one first. This is a non-functional concern. The designer's choice (lexicographic) is deterministic and predictable. W3 v2 can flag if this should be changed.

---

## Summary Reference Table

| Design dimension | Decision (v2) |
|---|---|
| Mechanism Registry placement | `fresh_slotlab/analyzer/mechanism_registry.py` (NOT `core/`) |
| Registry build timing | Post-merge, after F1 inline (Phase C in ordering) |
| Freespin Tier 3 signal | `total_freespin_chain_spins > 0` (CurFreeSpin-based accumulator). behavior_name=free MUST NOT be used. |
| Freespin Tier 2 signal | `len(bonus_chain_lengths) > 0` (merge-loop accumulator, available pre-emit) |
| Tier 2 blocking rule | Tier 2 explicit-False blocks Tier 3 fallback |
| Scatter-jackpot ordering | Scatter detection first; PIDs in scatter_marker_pids excluded from jackpot candidates |
| `emit()` signature | `emit(self, final_acc: dict, summary: dict, ctx: PipelineContext) -> None` |
| `PipelineContext` fields | `effective_bet_for_rtp`, `total_spins`, `total_paid_sessions`, `total_paid_spins`, `clamp_pending_robots_total`, `robots_with_pending_cycle`, `mechanism_registry` |
| Topological sort algorithm | Kahn's BFS; cycle → `PluginCyclicDependencyError`; missing dep → `PluginMissingDependencyError` |
| F1 ordering enforcement | Sentinel assertion: F1 must write `spin_type_breakdown` before `_build_mechanism_registry()` |
| extract() wiring | Both merge loop paths (from-cache at `pia:1614` AND online at `pia:2620`) |
| `mechanism_registry.py` hash gap | Explicitly acknowledged; operator must manually invalidate when detection logic changes |
| Portrait write error | `_portrait_write_error.json` sidecar; main run continues; never swallowed silently |
| Hash composition change | No algorithm change; optional `mechanism_overrides` dimension added |
| Phase count | C1 (wiring) → C2 (payout panel) → C3 (payouts enrichment) → C4 (machine_mechanics) → C5 (upstream + collect) → C6 (bonus_chain) |
| ALL_FEATURES import sites | 3 sites per new plugin: `pia:4816-4827` (both try blocks), `versioning.py:165-176`, `validate_manifests.py:43-47` |
| M250/M272/M279 L2 | Out of scope; separate RoundWinRule task; mechanism detection improves but attribution gap persists |
| "107 entities" benefit source | Universal plugin addition to 253 manifests (incl. M273.json) → M273's 85 variants inherit via `inherits_from` cascade |
| Batch-rebuild burden | ~633 stale entries per phase × 5 phases ≈ 3165 total; operator runs `FleetRefreshManager` batch from cache |
| Gap #6 (correction formula) | Tentatively: formula is correct; portrait label improvement needed; pending W3 v2 confirmation |
| Zero-code property | Case-A VANILLA + Case-B standard BCM; L2 attribution requires RoundWinRule (separate concern) |
| Gap #4 multiplier wilds | Deferred (paused inference) |
