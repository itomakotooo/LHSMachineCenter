# Phase C6 — impl-* team brief

> **Date**: 2026-05-27
> **Coordinator**: main session
> **Authoritative spec**: `session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md` §7.2 + `07_decision.md §7` row "C6"
> **Phase**: C6 (final of 7 — C1✓ / C2✓ / C3✓ / C3.5✓ / C4✓ / C5✓ / **C6**)
> **Branch**: `claude/analyzer-unbundle-c2`
> **Commit scope**: one logical commit

---

## §1 Phase C6 purpose (one sentence)

Carve PIA inline `bonus_chain_dynamics` block into plugin + close gap #3 (M275 pid 666 scatter trigger marker — currently classified as `cat=paid dom_st=140` with普通 pay, should be classified as `scatter_trigger_marker`) — final phase of analyzer unbundle.

## §2 What this phase ships

### 2.1 New plugin: `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py`

Pattern B stash pattern (same as C5 collect_mechanic). Replaces PIA inline F6 block that builds `summary["player_impact"]["bonus_chain_dynamics"]`.

- SCHEMA_VERSION=1 (no shape change; pure carve)
- REQUIRES=() (stash pattern; reads pre-loop summary or stash)
- DECLARED_DEPS=() (no `_`-temp-key reads)
- RTP_CONTRIBUTION=False (display only)

### 2.2 Gap #3 fix: scatter_trigger_marker on payout_ids_top20

Per `00_brief.md §3`: M275 pid 666 hit=829, win=0, line_id=-1 (scatter trigger of freespin) but classified as `cat=paid dom_st=140` mixed with regular pay-id rows.

C3 already added `notes.is_trigger_marker` to `payouts_by_spin_type` row level. C6 extends this to `payout_ids_top20`:

Per pid row in payout_ids_top20, add a `notes` block similar to C3 enrichment:
```json
{
  "payout_id": "666",
  "hit_count": 829,
  "total_win": 0,
  "...existing fields...",
  "notes": {
    "is_trigger_marker": true,    // C6 NEW
    "trigger_target": "NewFreespin"  // C6 NEW: which feature this scatter triggers (cross-ref from mechanism_registry)
  }
}
```

For pids that ARE NOT trigger markers: `notes.is_trigger_marker: false`, `notes.trigger_target: null`.

Implementation: C3 already aggregates `payout_id_has_regular_line` in parser. Reuse this signal:
- `payout_id_has_regular_line[pid] == False` AND `payout_id_win[pid] == 0` → trigger_marker = true
- trigger_target: look up in mechanism_registry (Tier 2 inference) or via cross-reference to bonus_chain_dynamics feature names

### 2.3 PIA inline F6 carve

Delete PIA inline F6 block (search for `bonus_chain_dynamics` construction — there's a large block that builds chain_count / bonus_round_count / avg_chain_length / chain_length_quantiles / chain_max_ratio_quantiles / extra_ratio_histogram / by_feature etc).

Stash pattern: PIA writes `summary["_bonus_chain_dynamics_data"]` (raw inputs) before emit loop, plugin's emit() reads + composes the public summary key.

### 2.4 Gap #8 completion check

Gap #8 was "payout_ids_top20 缺 shape / cols / paylines / 备注". C3 added these to `payouts_by_spin_type` rows but NOT to `payout_ids_top20`. C6 should consider:
- Option A: extend payout_ids_top20 with same 4 enrichment fields (shape / covered_columns / paylines / notes including trigger_marker)
- Option B: only add `notes` to payout_ids_top20 (just trigger_marker info, since shape/cols/paylines are per-(pid,ST) and payout_ids_top20 is per-pid aggregate)

Option B is cleaner since payout_ids_top20 is already aggregate. Implementer choice.

### 2.5 Manifest

Add `bonus_chain_dynamics` plugin to 253 declaring manifests (universal rollout).

Already-declared `bonus_chain_dynamics` is currently inline in PIA — adding it to manifest doesn't create false expectation since plugin emit() will replace the inline output. If implementer goes M275-only first, that's also fine.

### 2.6 5-site registration

1 new plugin × 5 sites = 5 import additions.

## §3 What this phase MUST NOT do

- ❌ Touch core/*.py (parser etc) — base_hash must stay fa440e3eb5f6 unless ABSOLUTELY needed for gap #3 detection. Likely not needed since C3 + C4 already aggregate the needed signals
- ❌ Touch C1 infrastructure
- ❌ Touch other 7 plugin files
- ❌ Touch web_console / auto_inspect / recovery / configs files
- ❌ Carve F2 payout_ids_top20 inline (just augment in place with new fields)
- ❌ Commit anything

## §4 Acceptance criteria

1. `bonus_chain_dynamics` plugin registers; M275 cached rebuild byte-identical for `bonus_chain_dynamics` subkey (pure carve, no schema change)
2. M275 `payout_ids_top20` row for pid 666: `notes.is_trigger_marker == True`, `notes.trigger_target == "NewFreespin"` (or similar — gap #3 closed)
3. M275 other rows (1, 2, 4, 7, 8...): `notes.is_trigger_marker == False`
4. M14 / M37 / M272: no false trigger_marker positives
5. base_hash UNCHANGED `fa440e3eb5f6` (parser not touched if possible)
6. 543+ tests/analyzer/ still pass + new C6 tests
7. 5-site registration verified
8. Inject-bug × 3+ cycles for new code paths

## §5 Memory feedback

Same as previous phases. Emphasis:
- `feedback_invariant_with_fallback_hides_drift.md` — `notes.is_trigger_marker` on payout_ids_top20 is explicit alert
- `feedback_no_parallel_panel_impl.md` — payout_ids_top20 notes shape should mirror payouts_by_spin_type notes shape

## §6 Files implementer expected

NEW:
- `fresh_slotlab/analyzer/features/bonus_chain_dynamics.py`
- 5+ test files

MODIFIED:
- PIA: F6 inline carve + F2 inline add notes to payout_ids_top20 rows
- versioning.py + validate_manifests.py
- 253 manifests

NOT touched: parser / 7 other plugins / C1 infrastructure / web_console / configs / frontend.

## §7 Process

Full impl-* loop. C6 is final — extra carefulness on commit msg / Self-critique + clear "C-phases complete" summary.

## §8 Commit message template

Use 4-section hook + Self-critique. Include: "this completes the C-phase analyzer unbundle: all 8 gaps closed (#1 jackpot / #2 freespin / #3 scatter / #4 multiplier_wild / #5 group noise / #6 chunk-size / #7 payouts_by_spin_type enrich / #8 payout_ids_top20 enrich)". Note that scatter_trigger_marker semantic + bonus_chain_dynamics carve are the last 2 deliverables.
