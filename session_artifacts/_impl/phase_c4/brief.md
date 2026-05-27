# Phase C4 — impl-* team brief

> **Date**: 2026-05-27
> **Coordinator**: main session
> **Authoritative spec**: `session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md` §5.2 (Mechanism Registry) + §7.2 Phase C4 deliverables + `07_decision.md §7` row "C4"
> **Phase**: C4 (fifth of 7 — C1 ✓ ae6b79a / C2 ✓ c57c53a / C3 ✓ 8cda1ab / C3.5 ✓ 6c2eda0 / **C4** / C5 / C6)
> **Branch**: `claude/analyzer-unbundle-c2` (continuing)
> **Commit scope**: one logical commit (largest phase yet — may take 2 days)

---

## §1 Phase C4 purpose (one sentence)

Replace the independent `machine_mechanics` block in PIA `main()` with a real **Mechanism Registry** that is the single source of truth for "what mechanics does this machine have" — closing gaps #1 (jackpot.applicable=false despite jackpot pids present) + #2 (free_spin.applicable=false despite freespin rounds present) from `session_artifacts/_arch_analyzer_unbundle/00_brief.md §3`.

## §2 What this phase ships

### 2.1 Real `MechanismRegistry` implementation

The C1-shipped `MechanismRegistry` placeholder (in `fresh_slotlab/analyzer/pipeline_context.py`) becomes a real class with Tier 1/2/3 detection per 04_v3 §5.2:

- **Tier 1: Manifest declared** — `manifest.get("mechanism_overrides", {})` highest precedence
- **Tier 2: Aggregated derived signals** — read from already-emitted summary keys:
  - `summary["player_impact"]["bonus_chain_dynamics"]["chain_count"] > 0` → freespin_applicable
  - `summary["player_impact"]["payouts_by_spin_type"]` for trigger marker presence
  - `summary["player_impact"]["payout_ids_top20"]` for jackpot candidate detection
- **Tier 3: Raw evidence** — read from chunk_dict accumulators (parser-provided):
  - `payout_id_win` PIDs with `avg_win_when_hit >= 10 * bet_face` OR PID >= 10000 → jackpot candidate
  - `jackpot_ids_seen` raw `JackpotIds` field (per NB1 fix in arch v3) UNION with PID source

**Output**: `summary["player_impact"]["machine_mechanics"]` keeps the existing 6-section schema (lock_lines / lock_symbols / lock_reels / jackpot / free_spin / dollar_pick) but **driven by Mechanism Registry**, not independent detectors. Existing fields preserved for backward compatibility:

```json
{
  "jackpot": {
    "applicable": true,
    "trigger_spins": 199,
    "trigger_rate": 0.00223,
    "jackpot_ids": ["27502", "27503", "27504"],
    "jackpot_id_count": 3,
    "total_win": 4390000,
    "rtp_contribution_pp": 5.49,
    "_detection_source": "tier3_pid_ge_10000"   // NEW C4 transparency field
  },
  "free_spin": {
    "applicable": true,
    "chain_spins": 9090,
    "chain_rate": 0.102,
    "retriggers": 0,
    "max_chain_length": 10,
    "total_win": 35531500,
    "rtp_contribution_pp": 39.88,
    "_detection_source": "tier2_bonus_chain_count_gt_0"   // NEW
  },
  ...
}
```

### 2.2 New plugin file: `fresh_slotlab/analyzer/features/machine_mechanics.py`

Pattern B from start. Replaces the PIA inline `machine_mechanics` aggregation block.

```python
FEATURE_ID: ClassVar[str] = "machine_mechanics"
SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("machine_mechanics",)
SCHEMA_VERSION: ClassVar[int] = 2  # bump from C1-era inline shape v1 (adds _detection_source field)
REQUIRES: ClassVar[tuple[str, ...]] = ("payouts_by_spin_type", "bonus_chain_dynamics")  # needs these for Tier 2
DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
RTP_CONTRIBUTION: ClassVar[bool] = False  # display only; doesn't add to RTP
REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {
    1: {"_detection_source": None}  # v1 -> v2: new field renders as null
}
```

Plugin uses topo sort (`REQUIRES`) to ensure it runs AFTER payouts_by_spin_type + bonus_chain_dynamics have emitted their summary keys, so Tier 2 detection has data to read.

### 2.3 Mechanism Registry file location

Per 04_v3 design + critic Q1 + coordinator decision: registry placed OUTSIDE `core/` to avoid base_hash invalidation. **BUT** the existing placeholder is currently in `pipeline_context.py` (also outside core/, so fine). Two options:

- **Option A**: Move MechanismRegistry to its own file `fresh_slotlab/analyzer/mechanism_registry.py`, leave only a re-export in pipeline_context.py
- **Option B**: Keep MechanismRegistry inside pipeline_context.py (current location)

**Implementer choice** based on cleanliness — both work for isolation. Option A is more spec-aligned per 04_v3 §5.2.

### 2.4 PIA `main()` inline carve

The current PIA inline `machine_mechanics` block (search for the section that builds `lock_lines` / `lock_symbols` / etc dicts) is deleted. The plugin takes over.

**Backward-compat for in-place rebuild**: if the PIA inline produced specific edge cases the plugin misses, those would surface as byte-identical diffs. Tester must verify byte-identical for at least M14 (no mechanisms) + M275 (has jackpot+freespin) + M11 (JackpotIds raw field) + M37 (vanilla classic Seven).

### 2.5 Parser changes (likely required)

To populate `mechanism_registry.jackpot_ids_seen` from raw `JackpotIds` field (per NB1 fix in arch v3 §5.2), parser must accumulate it across rounds. If raw JackpotIds field is not already aggregated by parser → ADD aggregator → core/parser.py change → base_hash flips (just like C3).

**Per coordinator decision (carried from C3)**: ACCEPT base_hash flip for round-level data dependencies. Document in commit msg.

### 2.6 Manifest

**Decision**: add `machine_mechanics` to ALL 253 declaring-manifests (currently `payouts_by_spin_type / reel_marginal_by_spin_type / bankruptcy_simulation / multiplier_profile`). The machine_mechanics panel is universal — every machine that gets the other 4 should get this too.

Alternative (M275-only): test on M275 first, promote later. Coordinator chooses M275-only first OR full 253.

**Implementer decision based on scope risk**: M275-only first; if M275 + M11 (JackpotIds) + M14 (vanilla) verify clean, promote in same commit OR follow-up. Document choice.

### 2.7 PIA registration: 5-site trap

Per C2 / C3.5 lesson: new plugin must be imported at all 5 sites (PIA pre-reg ×2, PIA emit, versioning, validate_manifests). Implementer must enumerate.

## §3 What this phase MUST NOT do

- ❌ Change machine_mechanics schema SHAPE (only add `_detection_source` field per fallback rule)
- ❌ Touch other 5 plugin files (bankruptcy / multiplier_profile / payouts_by_spin_type / reel_marginal / multiplier_wild)
- ❌ Modify C1 infrastructure (pipeline_context.py is OK to touch for MechanismRegistry class body; parse_state.py / topo_sort.py / _base.py off-limits)
- ❌ Touch web_console / auto_inspect / recovery / configs files
- ❌ Commit anything (coordinator commits after impl-critic APPROVE + impl-committer gate)
- ❌ Skip impl-verifier ceremony (this is the largest phase — full ceremony per coordinator commit msg in C3.5)

## §4 Acceptance criteria (gates before commit)

1. `machine_mechanics` plugin registers in `ALL_FEATURES` post-import
2. Plugin SCHEMA_VERSION = 2; REGISTERED_FALLBACK_RULES[1] = {"_detection_source": None}
3. Plugin REQUIRES = ("payouts_by_spin_type", "bonus_chain_dynamics") — topo sort proves this runs AFTER both
4. M275 mode 1: `machine_mechanics.jackpot.applicable: true` + `jackpot_ids: ["27502", "27503", "27504"]` + `rtp_contribution_pp ≈ 5.49` (close gap #1 ✓)
5. M275 mode 1: `machine_mechanics.free_spin.applicable: true` + `chain_spins: 9090` + `max_chain_length: 10` (close gap #2 ✓)
6. M11 mode 1: `machine_mechanics.jackpot.applicable: true` + `jackpot_ids` populated from raw `JackpotIds` field (NB1 fix verified)
7. M14 mode 1: `machine_mechanics.jackpot.applicable: false` + `free_spin.applicable: false` (no jackpot or freespin on vanilla machine — no false positives)
8. M37 mode 1: similar to M14 (no false positives)
9. Plugin extract() actually called (extends C2's regression test)
10. PIA inline machine_mechanics block deleted (grep verifies absence)
11. base_hash flip ACCEPTED (per coordinator decision); document in commit msg
12. effective_version flips for all 253 machines declaring machine_mechanics (or just M275 if implementer chose M275-only)
13. All previous tests pass (306 tests/analyzer/ + 66 wave_2c + 39 lookup_md5)
14. Inject-bug → red → revert → green for 3+ sensitive paths
15. 5-site registration verified

## §5 Memory feedback files this phase MUST honor

(Same set as previous phases plus emphasis on `feedback_invariant_with_fallback_hides_drift.md` — `_detection_source` explicit field is the alert, not a silent bucket).

## §6 Files implementer expected to touch

NEW:
- `fresh_slotlab/analyzer/features/machine_mechanics.py` (the plugin)
- `fresh_slotlab/analyzer/mechanism_registry.py` (Option A) OR extend pipeline_context.py (Option B)
- 5+ test files in tests/analyzer/test_c4_*.py

MODIFIED:
- `slot_designer/configs/machine_manifests/M275.json` (+1 feature; possibly +1 for M11 + M14 + M37 if implementer goes M11-too)
- `fresh_slotlab/analyzer/pipeline_context.py` (MechanismRegistry placeholder → real, or moved to mechanism_registry.py)
- `fresh_slotlab/player_impact_analyzer.py` (delete inline machine_mechanics block; add 5-site registration)
- `fresh_slotlab/analyzer/versioning.py` (1 import site)
- `scripts/validate_manifests.py` (1 import site)
- `fresh_slotlab/analyzer/core/parser.py` (likely: add JackpotIds raw field accumulator → base_hash flips)

NOT touched:
- 5 other plugin files
- parse_state.py / topo_sort.py / _base.py
- Other manifests (only the ones implementer chose to update)
- web_console / auto_inspect / recovery / configs

## §7 Process (per docs/ARCH_TEAM_PROCESS.md §9.7)

Full 4-agent loop: implementer → tester → verifier → critic → impl-committer → commit. **No skipping** (largest phase).

## §8 Commit message template

```
feat(analyzer): C4 — machine_mechanics plugin + Mechanism Registry (gap #1+#2)

[detail]

## Verified happy path
- [M14/M37/M275/M11/M272 byte-identical or expected new behavior]

## Verified failure paths
- [inject-bug cycles]

## Not verified
- [list]

## Tests added
- [list]

## Self-critique
- [adversarial self-review]
```
