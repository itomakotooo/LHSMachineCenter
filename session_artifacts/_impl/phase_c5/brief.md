# Phase C5 — impl-* team brief

> **Date**: 2026-05-27
> **Coordinator**: main session
> **Authoritative spec**: `session_artifacts/_arch_analyzer_unbundle/04_architecture_proposal_v3.md` §7.2 + `07_decision.md §7` row "C5"
> **Phase**: C5 (sixth of 7 — C1✓ / C2✓ / C3✓ / C3.5✓ / C4✓ / **C5** / C6)
> **Branch**: `claude/analyzer-unbundle-c2`
> **Commit scope**: one logical commit

---

## §1 Phase C5 purpose (one sentence)

Carve PIA inline `upstream_feature_breakdown` + `collect_mechanic` blocks into plugins; add chunk_spin_times sizing recommendation to `clamp_warning` per user gap #6 clarification — closes gap #5 (payout_groups_top20 noise) + gap #6 (estimated_correction_pp = 0.0 + chunk sizing).

## §2 What this phase ships

### 2.1 Two new plugins (Pattern B from start)

**`fresh_slotlab/analyzer/features/upstream_feature_breakdown.py`**:
- Replaces PIA inline `upstream_feature_breakdown` block
- Reads `chunk_dict["analysisResult"]["FeatureWin"]` cross-references (per existing PIA logic)
- Writes `summary["player_impact"]["upstream_feature_breakdown"]`
- SCHEMA_VERSION=1 (no shape change vs current inline)
- REQUIRES = () (reads chunk_dict directly; no plugin deps)

**`fresh_slotlab/analyzer/features/collect_mechanic.py`**:
- Replaces PIA inline `collect_mechanic` top-level block
- Reads BCM cycle accumulators + clamp_warning + bonus_cycle_correction inline computations
- Writes `summary["collect_mechanic"]` (top-level, not under player_impact — preserve existing schema location)
- SCHEMA_VERSION=2 (bump to add `chunk_spin_times_recommendation` field per gap #6)
- REGISTERED_FALLBACK_RULES[1] = {"chunk_spin_times_recommendation": None}
- REQUIRES = () (reads chunk_dict + ctx)

### 2.2 Gap #5 fix: payout_groups_top20 noise filter

`payout_groups_top20` is built in PIA F2 inline. If `PayoutGroupId` is all zeros across all rounds (e.g. M275), the panel currently shows `[{group_id: 0, hit_count: 89090, rtp_pp: 80.13}]` which is **noise** (not real grouping; just default value).

Fix scope:
- Detect "all zero PayoutGroupId" condition in PIA F2 inline
- If detected: return empty list `[]` for payout_groups_top20 (frontend should render as "N/A" or hide panel)
- Document in `summary["player_impact"]["_payout_groups_status"]` (NEW): one of `"populated"` / `"all_zeros_filtered"` / `"absent_field"`

Backward-compat: returning `[]` vs `[{group 0 noise}]` is a behavior change. Frontend renderers reading `payout_groups_top20[0]` would null-deref; check frontend code or document as a known impact.

**Implementer decision**: keep gap #5 fix in PIA F2 inline (don't carve F2 as a plugin — that's deferred to a later phase or never). Add the all-zero filter + status flag.

### 2.3 Gap #6 fix: chunk_spin_times sizing recommendation

User clarification (2026-05-27): `estimated_correction_pp = 0.0` is mathematically correct (depends on whether chunk_spin_times is large enough for the BCM cycle to complete). The fix:

Add to `clamp_warning` block in `collect_mechanic`:
```json
"clamp_warning": {
  ...existing fields...,
  "chunk_spin_times_recommendation": {
    "current": 5000,
    "recommended_min": 5570,     // detected_cycle_length * avg_spins_per_collect
    "recommended_safety": 8350,  // recommended_min * 1.5 safety factor
    "rationale": "BCM cycle length 1000 * avg 5.57 spins/collect = 5570 spins/cycle; current chunk_spin_times 5000 too short for complete cycles"
  }
}
```

Plugin computes from `ctx` + collect_mechanic's existing detected_cycle_length + avg_spins_per_collect.

### 2.4 PIA inline carve

Delete:
- PIA inline `upstream_feature_breakdown` block (find lines)
- PIA inline `collect_mechanic` block (find lines — large block with cycle_observation / clamp_warning / bonus_cycle_correction / newfreespin_correction)

Plugin emit replaces both. Other accumulators that fed these blocks stay in PIA (some may be needed by other inline blocks not yet carved).

### 2.5 Manifest

**Decision (coordinator)**: full 253 rollout for upstream_feature_breakdown + collect_mechanic — both are universal panels that all reporting machines benefit from.

Per C4 pattern, update all 253 declaring-manifests to include 2 new features.

### 2.6 5-site plugin registration

2 new plugins × 5 sites = 10 import additions. Per C2/C3.5/C4 pattern.

## §3 What this phase MUST NOT do

- ❌ Touch C1 infrastructure (pipeline_context.py / parse_state.py / topo_sort.py / _base.py)
- ❌ Modify other 6 plugin files (bankruptcy / multiplier_profile / payouts_by_spin_type / reel_marginal / multiplier_wild / machine_mechanics)
- ❌ Touch web_console / auto_inspect / recovery / configs files
- ❌ Carve F2 payout_ids_top20 (deferred to C6 or later)
- ❌ Touch parser unless necessary (prefer Option A1 — read chunk_dict existing keys)
- ❌ Change machine_mechanics behavior (C4 just shipped, leave it stable)
- ❌ Commit anything

## §4 Acceptance criteria

1. `upstream_feature_breakdown` plugin registers; M275 cached rebuild produces same output as pre-C5 (byte-identical for this subkey)
2. `collect_mechanic` plugin registers; M275 cached rebuild produces same output as pre-C5 for existing fields + NEW `chunk_spin_times_recommendation` field
3. `payout_groups_top20` on M275: now empty `[]` (all PayoutGroupId zeros filtered); `_payout_groups_status: "all_zeros_filtered"` (NEW field documents)
4. `payout_groups_top20` on any machine with real grouping: unchanged behavior
5. base_hash flip status: if parser untouched → unchanged; if parser touched → document per C3/C4 pattern
6. M14/M275/M37/M272 byte-identical for non-modified fields
7. 416 tests/analyzer/ still pass; new C5 tests pass; no regressions
8. Inject-bug ×3+ cycles for new code paths
9. 10-site plugin registration (2 plugins × 5 sites) verified
10. Commit msg disclosures + Self-critique section

## §5 Memory feedback files

Same as previous phases. Emphasis:
- `feedback_invariant_with_fallback_hides_drift.md` — `_payout_groups_status` is explicit signal not silent bucket
- `feedback_no_silent_swallow.md` — chunk_spin_times_recommendation is operator-facing alert

## §6 Files implementer expected to touch

NEW:
- `fresh_slotlab/analyzer/features/upstream_feature_breakdown.py`
- `fresh_slotlab/analyzer/features/collect_mechanic.py`
- 6+ test files

MODIFIED:
- PIA: delete 2 inline blocks; add 10-site registration; add gap #5 filter
- versioning.py: 2 import sites
- validate_manifests.py: 2 import sites
- 253 manifest files: add 2 features each

NOT touched:
- 6 existing plugin files
- C1 infrastructure
- frontend / web_console / auto_inspect / recovery / configs

## §7 Process

Full impl-* 4-agent loop. No skipping.

## §8 Commit message template (per brief §9 of C4)

Use 4-section hook (Verified happy / failure / Not verified / Tests added) + Self-critique. Disclose carry-forwards.
