# Phase C3.5 — impl-* team brief

> **Date**: 2026-05-27
> **Coordinator**: main session
> **Authoritative spec**: `session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md` + `07_decision.md §7`
> **Phase**: C3.5 (fourth of 7 — C1 ✓ ae6b79a / C2 ✓ c57c53a / C3 ✓ 8cda1ab / **C3.5** / C4 / C5 / C6)
> **Branch**: `claude/analyzer-unbundle-c2` (continuing)
> **Commit scope**: one logical commit

---

## §1 Phase C3.5 purpose (one sentence)

Add a new `multiplier_wild` plugin that surfaces multiplier-wild symbol presence (`wild2x` / `wild5x` / `wild10x` / `wild_Nx`) + RTP contribution per (column, ST) — closing user-stated gap #4 from `session_artifacts/_arch_analyzer_unbundle/00_brief.md §3`. Mechanism: symbol-level embedded multiplier (NOT free-game cumulative — verified via raw data probe in earlier session).

## §2 What this phase ships

### 2.1 New plugin file: `fresh_slotlab/analyzer/features/multiplier_wild.py`

Pattern B from start (no Pattern A scaffold needed):

```python
FEATURE_ID: ClassVar[str] = "multiplier_wild"
SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ("multiplier_wild",)
SCHEMA_VERSION: ClassVar[int] = 1
DECLARED_DEPS: ClassVar[tuple[str, ...]] = ()
REQUIRES: ClassVar[tuple[str, ...]] = ()
RTP_CONTRIBUTION: ClassVar[bool] = True
REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}
```

### 2.2 Output schema: `summary["player_impact"]["multiplier_wild"]`

```json
{
  "applicable": true,
  "variants": [
    {
      "symbol": "wild2x",
      "multiplier_value": 2,
      "total_hits": 1666,
      "by_column": [
        {"col": 1, "hits": 1666, "hit_rate": 0.0186}
      ],
      "by_spin_type": [
        {"spin_type": 140, "behavior": "paid", "hits": 1260},
        {"spin_type": 126, "behavior": "free", "hits": 406}
      ]
    },
    {"symbol": "wild5x", "multiplier_value": 5, ...},
    {"symbol": "wild10x", "multiplier_value": 10, ...}
  ],
  "total_multiplier_wild_hits": 3953,
  "estimated_rtp_contribution_pp": null,
  "estimated_rtp_method": "deferred_v2"
}
```

**Field semantics**:
- `applicable: true` iff any symbol matching regex `^wild\d+x$` was observed in the chunk
- `applicable: false` + empty variants when no multiplier wild observed (vanilla machines)
- `multiplier_value` parsed from regex `wild(\d+)x` → int
- `by_column` shows which reel columns the variant landed in (M275: always col 1)
- `by_spin_type` cross-references SpinType (paid vs free) for behavioral analysis
- `estimated_rtp_contribution_pp` = null in v1 — actual RTP uplift requires combining with line-win data; calculation deferred to v2 to keep this phase scoped

### 2.3 Inference logic

Plugin's `extract(parse_state, chunk_dict)`:
- Read `chunk_dict["symbol_by_col_counts"]` (existing parser output — per-column symbol counts)
- Read `chunk_dict["symbol_counts_by_st"]` if exists (per-ST counts) — if not exists, fall back to overall counts
- For each symbol matching `^wild\d+x$`: extract multiplier value, hit counts per column / per ST
- Returns per-chunk accumulator dict

Plugin's `reduce(prev, cur)`:
- Additive merge across chunks (per variant per column per ST hit counts)

Plugin's `emit(final_acc, summary, ctx)`:
- Compose the schema dict
- Write to `summary["player_impact"]["multiplier_wild"]`
- Use `ctx.total_spins` for `hit_rate` denominator

### 2.4 Manifest registration

**Only M275 manifest gets `"multiplier_wild"` in analyzer_features** for now (per-machine isolation — base_hash should NOT flip; only M275's effective_version changes).

Edit `slot_designer/configs/machine_manifests/M275.json` analyzer_features list:
```json
"analyzer_features": [
  "payouts_by_spin_type",
  "reel_marginal_by_spin_type",
  "bankruptcy_simulation",
  "multiplier_profile",
  "multiplier_wild"
]
```

Other machines (252 declaring + 166 empty) keep their current manifests unchanged. Future phases can opt them in if they have multiplier wilds.

**Per-machine isolation property check**:
- base_hash unchanged (no `core/*.py` change)
- 4 existing plugin hashes unchanged (their source not modified)
- New plugin file `multiplier_wild.py` source bytes only matter for machines declaring it
- → Only M275's effective_version changes; other 418 machines unchanged

**This is the cleanest per-machine isolation demonstration in the whole carve.** Verify this property is preserved.

### 2.5 PIA registration (per coupling auditor's 3-import-site trap)

Per `03_coupling_audit.md §2.2 Symbol 5` and C2's pre-registration block lesson: every NEW plugin must be imported at 3 sites. C3.5 adds 1 new plugin → must register at:
1. `fresh_slotlab/player_impact_analyzer.py` from-cache pre-registration block (~line 1521)
2. `fresh_slotlab/player_impact_analyzer.py` online sampling pre-registration block (~line 2192)
3. `fresh_slotlab/player_impact_analyzer.py` emit-time lazy import (~line 4816-4827)
4. `fresh_slotlab/analyzer/versioning.py` (~line 165-176)
5. `scripts/validate_manifests.py` (~line 43-47)

5 sites! (the 3-site trap was for `_base.py` ABC + 2 import paths, but in practice each new plugin needs registration at 5 places per the existing pattern. Implementer should grep + add at all of them.)

## §3 What this phase MUST NOT do

- ❌ Change `core/*.py` files (would flip base_hash and violate per-machine isolation)
- ❌ Change existing 4 plugin files
- ❌ Change PIA `main()` inline logic (only add the import line to pre-registration blocks)
- ❌ Compute the actual RTP contribution in v1 (deferred to v2)
- ❌ Touch frontend
- ❌ Touch web_console / auto_inspect / recovery / configs files
- ❌ Touch ANY other manifest file (only M275.json gets the +1 feature)
- ❌ Commit anything (coordinator commits after impl-critic APPROVE)

## §4 Acceptance criteria (gates before commit)

1. **Plugin `multiplier_wild` registers** in `ALL_FEATURES` post-import (verify via `python -c "from fresh_slotlab.analyzer.feature_registry import ALL_FEATURES; print([f.FEATURE_ID for f in ALL_FEATURES])"`)
2. **base_hash UNCHANGED** vs C3 — `compute_base_analyzer_version()` returns `64409ab1b68c` (same as C3 ship)
3. **M275 effective_version flips** (manifest has new feature; plugin hash now contributes)
4. **M14 / M37 / M272 effective_version UNCHANGED** — their manifests don't declare multiplier_wild, so the new plugin doesn't contribute to their hash
5. **M275 mode 1 cached rebuild**: `summary["player_impact"]["multiplier_wild"]` populated with 3 variants (wild2x / wild5x / wild10x), each with by_column showing col 1 dominance + by_spin_type with paid+free split. Numbers should approximate raw probe values:
   - wild2x: ~1666 total hits (1260 paid + 406 free)
   - wild5x: ~2557 total hits (2471 paid + 86 free)
   - wild10x: ~1337 total hits (1262 paid + 75 free)
6. **M14 / M37 cached rebuild**: `summary["player_impact"]["multiplier_wild"]` NOT present (no manifest declaration) OR `{"applicable": false}` (if manifest declares but no data). Either is acceptable behavior; implementer chooses.
7. **All existing tests pass**: 215 tests/analyzer/ + 66 wave_2c + 39 lookup_md5 unchanged
8. **Plugin extract() actually called** for M275 — extends existing extract_actually_called regression guard
9. **Inject-bug → red → revert → green**: 2-3 sensitive paths
10. **3-site (or 5-site) import registration verified** — grep all sites; new plugin imported in each

## §5 Memory feedback files this phase MUST honor

- `feedback_subprocess_import_suicide_and_module_globals.md` — plugin import-safe
- `feedback_md5_is_a_tag_not_a_destruction_signal.md` — effective_version flip = classification, not destruction
- `feedback_no_silent_swallow.md` — extract errors continue surfacing via existing C2 mechanism
- `feedback_enumerate_safety_paths.md` — inject-bug protocol
- `feedback_perf_claim_needs_e2e_event_stream.md` — verifier subprocess test
- `feedback_md5_granularity_and_stamping.md` — per-mode hash preserved
- `feedback_invariant_with_fallback_hides_drift.md` — applicable=false is explicit signal, not silent bucket
- `feedback_no_parallel_panel_impl.md` — N/A (no frontend)
- `feedback_prefer_complex_better.md` — pick generic plugin design (not M275-specific hardcoded logic)
- `feedback_arch_team_process.md` — this phase is small, doesn't need fresh arch-* round (proposed in 07_decision)
- `feedback_impl_team_required.md` — full impl-* loop

## §6 Claims verifier + critic must check

| Claim | Verification |
|---|---|
| Plugin imports clean | `python -c "import fresh_slotlab.analyzer.features.multiplier_wild"` |
| Plugin registered post-import | `ALL_FEATURES` contains "multiplier_wild" |
| SCHEMA_VERSION = 1 | grep plugin |
| RTP_CONTRIBUTION = True | grep |
| M275 manifest has `"multiplier_wild"` in analyzer_features | grep M275.json |
| base_hash unchanged | `compute_base_analyzer_version()` == 64409ab1b68c |
| M275 effective_version changed | pre + post compute_effective_version_for_machine("M275", 1) |
| M14 effective_version UNCHANGED | pre + post compute_effective_version_for_machine("M14", 1) |
| M37 effective_version UNCHANGED | same |
| 5 import sites have new plugin | grep all 5 paths for "multiplier_wild" |
| M275 mode 1 output has multiplier_wild key | inspect cached rebuild summary |
| 3 variants present (wild2x/wild5x/wild10x) | inspect |
| wild5x has highest paid hits, wild2x highest free hits | inspect cross-ref against raw probe values |
| Inject-bug cycles documented | inject_bug_evidence.md |
| Pre-existing C1+C2+C3 regression tests still pass | rerun test_c2_extract_actually_called etc. |

## §7 Files implementer expected to touch

NEW:
- `fresh_slotlab/analyzer/features/multiplier_wild.py` (the plugin)
- `tests/analyzer/test_c3_5_multiplier_wild_plugin.py` (unit tests)
- `tests/analyzer/test_c3_5_isolation_m275_only.py` (key isolation test — base_hash unchanged + only M275 effective_version changes)
- `tests/analyzer/test_c3_5_m275_e2e.py` (subprocess + verify 3 variants present)
- `tests/analyzer/test_c3_5_inject_bug.py` (inject-bug coverage)

MODIFIED:
- `slot_designer/configs/machine_manifests/M275.json` (+1 line in analyzer_features array)
- `fresh_slotlab/player_impact_analyzer.py` (3 import sites: from-cache pre-reg + online pre-reg + emit lazy import)
- `fresh_slotlab/analyzer/versioning.py` (1 import site)
- `scripts/validate_manifests.py` (1 import site)

NOT touched:
- core/*.py
- pipeline_context.py / parse_state.py / topo_sort.py / _base.py
- 4 other plugin files (bankruptcy / multiplier_profile / payouts_by_spin_type / reel_marginal)
- Other manifest files (only M275.json)
- frontend / web_console / auto_inspect / recovery / configs

## §8 Process (per docs/ARCH_TEAM_PROCESS.md §9.7)

Standard 4-agent loop: implementer → tester → verifier → critic → impl-committer → coordinator commits.

## §9 Commit message template

```
feat(analyzer): C3.5 — multiplier_wild plugin (gap #4)

Phase C3.5 of analyzer unbundle (M275-driven). New plugin surfaces
wild_Nx symbol presence + per-column / per-spin-type hit distribution.
Closes gap #4 (multiplier wild interpretation) from 00_brief.md §3.

Per-machine isolation demonstration: only M275.json manifest gets
"multiplier_wild" feature; base_hash + other 418 machines unchanged.

Changes:
- NEW fresh_slotlab/analyzer/features/multiplier_wild.py (Pattern B from start)
- M275.json adds "multiplier_wild" to analyzer_features
- 5-site plugin registration (PIA pre-reg ×2 + PIA emit + versioning + validate_manifests)
- SCHEMA_VERSION = 1; RTP_CONTRIBUTION = True
- Mechanism: regex wild(\d+)x parses multiplier value (2/5/10/...)
- Per-(symbol, col, ST) hit aggregation; no full RTP uplift estimation
  in v1 (deferred — requires line-win correlation)

## Verified happy path
- [byte-identical for non-declaring machines; new plugin only for M275]

## Verified failure paths
- [inject-bug cycles]

## Not verified
- [list]

## Tests added
- [list]
```

## §10 Sequencing note

C3.5 is a **plugin-only** addition. No core/parser change → base_hash stable → ONLY M275 effective_version flips. This is the C-phases' textbook demonstration of per-machine isolation property.

Future phases (C4-C6) may need parser changes for round-level mechanism detection; those will flip base_hash. C3.5 is the "clean isolation" reference point.