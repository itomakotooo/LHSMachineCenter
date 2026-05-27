# Phase C3 — impl-* team brief

> **Date**: 2026-05-27
> **Coordinator**: main session
> **Authoritative spec**: `session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md`
> **Phase**: C3 (third of 7 — C1 ✓ ae6b79a / C2 ✓ c57c53a / **C3** / C3.5 / C4 / C5 / C6)
> **Branch**: `claude/analyzer-unbundle-c2` (continuing — will rename later or keep as-is for whole carve)
> **Commit scope**: one logical commit

---

## §1 Phase C3 purpose (one sentence)

Enrich `payouts_by_spin_type` plugin output with 4 new fields per `(pid, spin_type)`: **shape** (n-of-a-kind distribution), **covered_columns** (which reel columns), **paylines** (which payline_ids), **notes** (symbol_id + wild substitution hint + trigger marker flag). This closes user-stated gaps #7 + #8 from `session_artifacts/_arch_analyzer_unbundle/00_brief.md §3`.

## §2 What this phase ships

### 2.1 New plugin output fields

Per `(pid, ST_label)` row in `payouts_by_spin_type[ST_label]`, in addition to the existing 6 fields (payout_id / hit_count / hit_rate / total_win / avg_win_when_hit / rtp_contribution_pp), add:

```json
{
  "shape": {
    "3_of_a_kind": 145,
    "4_of_a_kind": 0,
    "5_of_a_kind": 0
  },
  "covered_columns": [0, 1, 2],
  "paylines": [
    {"payline_id": "1", "hit_count": 30, "total_win": 150000},
    {"payline_id": "2", "hit_count": 42, "total_win": 210000},
    ...
  ],
  "notes": {
    "symbol_id": "1",
    "is_trigger_marker": false,
    "scatter_like": false,
    "max_match_count_observed": 3
  }
}
```

**Per-machine semantics**:
- For M275 (3×3 grid, 5 paylines, 12 pids): each row populated with real data
- For pid 666 on M275: `is_trigger_marker: true` (line_id=-1, all wins=0)
- For pid 27502/27503/27504 (jackpot pids): no special treatment YET (jackpot semantic detection is C4 scope; C3 just exposes the data)
- For a vanilla 1-payline classic Seven (M37 mode 1): `paylines` has 1 entry, `covered_columns: [0]`

### 2.2 SCHEMA_VERSION bump 1 → 2

Per `04_v3 §5.4`: bumping SCHEMA_VERSION invalidates downstream renderers that have not been updated.

Add `REGISTERED_FALLBACK_RULES` on the plugin:
```python
REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {
    1: {
        # v1 → v2 fallback: the 4 new fields are absent in v1 summaries.
        # Frontend renderer should render them as None / hide gracefully.
        "shape": None,
        "covered_columns": None,
        "paylines": None,
        "notes": None,
    }
}
```

This allows the frontend renderer to gracefully render v1 summaries (existing on-disk reports) without crashing on missing keys.

### 2.3 Plugin implementation choice

The plugin needs **per-round PayoutByPayline + StopSymbolsByCol** access to compute shape / cols / paylines / notes. Two architectural options:

**Option A (preferred): plugin processes raw rounds from chunk_dict**
- Verify if `chunk_dict` already exposes raw rounds (or rec-level extracted records that include PayoutByPayline per round)
- If yes: extract() iterates rounds, computes per-(pid, ST) enrichment, returns
- If no but plugin can iterate raw chunk envelope: extract() opens envelope (it has the path? no — pass via parse_state)
- Pros: plugin self-contained; no core/*.py hash flip → only 253 declaring machines invalidate
- Cons: plugin does per-round iteration; may be slower

**Option B: parser aggregates new per-(pid, ST) maps**
- Parser computes `payout_id_payline_records_by_spin_type[pid][st_int] = [{payline_id, symbol_id, match_count, positions}, ...]` and exposes in chunk_dict
- Plugin extract() reads pre-aggregated maps from chunk_dict
- Pros: faster (parser does it once)
- Cons: parser change → core/*.py hash → base_hash flip → **419 machines all invalidate** (violates per-machine isolation property)

**Implementer must choose A unless A is genuinely unworkable.** If A requires extending chunk_dict to carry raw rounds, that's still NOT a core/*.py logic change — it's a data exposure addition that other plugins might also benefit from (C4+). Document the choice in the implementer's summary.

### 2.4 Per-round attribution mechanism

The crucial mapping is: given a chunk's rounds, for each round's `PayoutByPayline` string (e.g. `"4:7-7(99,200,301,);"`), parse out `(payline_id, symbol_id, positions)`. Use existing helpers in `fresh_slotlab/round_classification.py`:
- `parse_payline_records(pbp: str)` — already returns `[{line_id, symbol_id, match_count, positions}, ...]`
- `attribute_lines_to_pay_ids(round)` — returns the same list with `pay_id` resolved

Plugin extract() should call these helpers, NOT re-implement parsing.

For positions → covered_columns: positions are slot indices in the grid (e.g. 99 = col 0 row 0, 200 = col 1 row 0, 301 = col 2 row 0 for M275's 3×3 layout). Need to infer column from position. M275 uses `pos // 100` as column (99 → 0, 200 → 2 wait that's not right). Look at the actual grid layout from `StopSymbolsByCol` — col count = len(StopSymbolsByCol). Position format may vary per machine.

**Implementer should investigate position-to-column mapping** by inspecting 2-3 real PayoutByPayline + StopSymbolsByCol pairs from M275 + M14. Document the rule.

### 2.5 Trigger-marker detection (notes.is_trigger_marker)

A pay_id is a "trigger marker" if all its hit records have `line_id = -1` AND `win = 0`. M275's pid 666 is the canonical example.

C3 detects this in the plugin's emit() (or earlier). It does NOT modify the pay_id's spin_type_breakdown classification (that's per-row); just adds the boolean note.

(Full scatter trigger handling — connecting trigger marker to freespin chain causation — is C6 scope.)

## §3 What this phase MUST NOT do

- ❌ Change ANY other plugin file (only payouts_by_spin_type.py modified)
- ❌ Modify `fresh_slotlab/analyzer/core/*.py` files unless ABSOLUTELY required (would flip 419-machine base_hash). If absolutely required, justify in implementer summary; coordinator will decide
- ❌ Modify `pipeline_context.py` / `parse_state.py` / `topo_sort.py` / `_base.py` (C1 infrastructure stable)
- ❌ Change F1 (spin_type_breakdown), F2 (payout_ids_top20), F4 (reel_marginal_by_spin_type), F5+ (other inline blocks) — those are separate phases
- ❌ Touch frontend (renderer registry deferred to Phase 4 per arch §6.6)
- ❌ Touch web_console / auto_inspect / recovery / configs files (respect concurrent session per user)
- ❌ Commit anything (only coordinator commits after impl-critic APPROVE)

## §4 Acceptance criteria (gates before commit)

1. **payouts_by_spin_type SCHEMA_VERSION == 2**: bumped from 1 per `_base.py` ABC contract
2. **REGISTERED_FALLBACK_RULES added** mapping `{1: {shape: None, covered_columns: None, paylines: None, notes: None}}`
3. **M275 mode 1 cached rebuild**: each row in payouts_by_spin_type contains all 4 new fields populated with real data (not None/empty for the 12 pids); pid 666 specifically shows `notes.is_trigger_marker: true`
4. **M275 existing 6 fields IDENTICAL pre/post C3** (the C2-shipped fields don't change; only 4 new fields added)
5. **M14 cached rebuild**: enrichment populated correctly (8 pids on M14 mode 1)
6. **M37 cached rebuild**: enrichment populated; reflects single-payline classic Seven structure (`paylines` has 1 entry)
7. ~~**No fleet-wide invalidation**~~ → **REVISED per coordinator post-implementer review (2026-05-27)**:

   The C3 enrichment requires per-round `PayoutByPayline` aggregation (3 of 4 new fields need round-level data). The implementer chose Option B (parser adds `payout_id_payline_hits` / `payout_id_match_count_dist` / `payout_id_col_set` / `payout_id_has_regular_line` aggregations in the per-round loop) — Option A1 (plugin self-iterates) would require parser to ALSO expose raw rounds (still a parser change), and Option A2 doesn't avoid it either.

   **Architectural reality**: any phase that needs round-level data for plugin enrichment MUST touch parser → `base_hash` flips → all 419 machine effective_version invalidates. This is unavoidable without major architecture redesign (moving parser out of `core/`).

   **Coordinator decision (locked 2026-05-27)**: ACCEPT base_hash flip for C3 (and likely C4 mechanism_registry + C5/C6 round-level work too). Document in commit message under `## Not verified` / known carry-forward. Update v3 spec retroactively if needed.

   Verifier should check: (a) base_hash flips (expected, not regression); (b) effective_version flips for all 419 machines (expected); (c) cached reports invalidate cleanly; (d) per-feature plugin hash also changes (proves additional plugin source change layered on top).
8. **All previous tests still green**: 75+ C2 tests, 39 lookup_machine_md5, 66 wave_2c, etc.
9. **Inject-bug → red → revert → green**: tester picks 2-3 sensitive C3 code paths and proves regression catch
10. **Plugin extract() error capture path still works** (verify: inject error in C3 enrichment logic → `summary["feature_errors"]` populated)

## §5 Memory feedback files this phase MUST honor

- `feedback_subprocess_import_suicide_and_module_globals.md` — plugin import-safe
- `feedback_md5_is_a_tag_not_a_destruction_signal.md` — schema bump invalidates, doesn't delete
- `feedback_no_silent_swallow.md` — extract errors continue surfacing
- `feedback_enumerate_safety_paths.md` — inject-bug protocol
- `feedback_perf_claim_needs_e2e_event_stream.md` — verifier subprocess-against-cached-fixture
- `feedback_md5_granularity_and_stamping.md` — per-mode hash preserved
- `feedback_invariant_with_fallback_hides_drift.md` — `notes.is_trigger_marker` is an explicit flag, not a fallback bucket
- `feedback_no_parallel_panel_impl.md` — N/A (no frontend in C3)
- `feedback_adversarial_self_review.md` — critic's job
- `feedback_prefer_complex_better.md` — choose Option A (plugin self-contained) unless A genuinely unworkable

## §6 Claims the verifier + critic must check

| Claim | Verification |
|---|---|
| 4 new fields present in M275 + M14 + M37 output | grep summary.json for keys `shape`, `covered_columns`, `paylines`, `notes` |
| SCHEMA_VERSION = 2 | grep plugin file |
| REGISTERED_FALLBACK_RULES populated for v1 | grep plugin file |
| base_hash unchanged | `compute_base_analyzer_version()` pre + post |
| Plugin file hash changed | feature.compute_hash() pre + post |
| effective_version flipped for declaring machines only | compute_effective_version_for_machine for M14 + a non-declaring machine (one of the 166 empty manifests) |
| M275 pid 666 has `notes.is_trigger_marker: true` | inspect M275 summary output |
| M275 pid 27502 (jackpot) is NOT marked trigger | inspect (it's a payout, not a trigger marker, even though pids 666 and 27502 are both "special") |
| M14 vanilla pid has reasonable paylines | inspect |
| Existing 6 fields per row unchanged pre/post C3 | diff just those fields |
| Pre-registration block still works | grep + extract_actually_called regression test |
| Outer except still handles errors | grep + extract_error_capture test |
| Markdown report still renders | run analyzer, check player_impact_report.md exists |

## §7 Files implementer expected to touch

Modified:
- `fresh_slotlab/analyzer/features/payouts_by_spin_type.py` (enrichment logic + SCHEMA_VERSION + REGISTERED_FALLBACK_RULES)
- (POSSIBLY) `fresh_slotlab/analyzer/core/parser.py` if Option B chosen — coordinator must approve before this touch

NEW:
- `tests/analyzer/test_c3_enrichment.py` — unit tests for shape / cols / paylines / notes derivation
- `tests/analyzer/test_c3_byte_identical_legacy_fields_m14.py` — assert C2 fields unchanged for M14
- `tests/analyzer/test_c3_byte_identical_legacy_fields_m275.py` — same for M275
- `tests/analyzer/test_c3_schema_version_2.py` — assert SCHEMA_VERSION == 2 + REGISTERED_FALLBACK_RULES correct
- `tests/analyzer/test_c3_trigger_marker_m275.py` — assert pid 666 marked is_trigger_marker
- `tests/analyzer/test_c3_isolation_no_base_hash_flip.py` — compute_base_analyzer_version pre + post unchanged

NOT touched:
- `pipeline_context.py` / `parse_state.py` / `topo_sort.py` / `_base.py` / 3 other plugins
- `core/aggregator.py` / `writer.py` (probably; verify)

## §8 Process (per docs/ARCH_TEAM_PROCESS.md §9.7)

1. Coordinator → impl-implementer with this brief → wait
2. Coordinator → impl-tester with implementer summary → wait
3. Coordinator → impl-verifier with both → wait
4. Coordinator → impl-critic with all + commit msg → wait
5. Verdict → loop / approve / commit
6. impl-committer pre-commit gate → coordinator commits

## §9 Commit message draft template

```
feat(analyzer): C3 — F3 payouts_by_spin_type enrichment (shape/cols/paylines/notes)

Phase C3 of analyzer unbundle (M275-driven) per
session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md.
Closes user-stated gaps #7 + #8: each (pid, spin_type) row now carries
shape distribution / covered columns / payline attribution / notes.

Changes:
- payouts_by_spin_type.py: SCHEMA_VERSION 1 → 2
- REGISTERED_FALLBACK_RULES[1] for v1 summary backward-compat
- extract()/emit() compute 4 new per-(pid, st) fields:
  shape, covered_columns, paylines, notes
- pid 666 on M275 + similar trigger markers now flagged
  notes.is_trigger_marker: true
- All existing C2 fields preserved byte-identical for M14/M275/M37/M272

## Verified happy path
- [byte-identical legacy fields, new fields populated]

## Verified failure paths
- [inject-bug cycles]

## Not verified
- [list]

## Tests added
- [list]
```

## §10 Sequencing note

C3 is a schema bump. After this, C3.5 (multiplier_wild plugin or extension), C4 (machine_mechanics + Mechanism Registry), C5 (upstream + collect), C6 (bonus_chain + scatter_marker) follow. C6 will properly connect scatter trigger marker → freespin chain causation; C3's `is_trigger_marker` flag is a precursor.