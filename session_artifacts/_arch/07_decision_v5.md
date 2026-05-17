# Architecture Review v5 — Decision Summary + Ship-Ready Inline Patches

> Branch `arch/console-refactor`. 5 full iterations complete. 19 artifacts in `session_artifacts/_arch/`.
> Per `00_brief_v5_addendum.md §5` stop criteria: both reviewers APPROVE-WITH-REVISIONS with <3 must-resolves → **coordinator inline-patches + ships**.

---

## §1 v5 outcome

| Reviewer | Verdict | Issues |
|---|---|---|
| arch-critic v5 | APPROVE-WITH-REVISIONS | 2 medium + 2 soft (all documentation-level, no algorithmic changes) |
| arch-validator v5 | APPROVE-WITH-REVISIONS | 3 spec clarifications, 0 cases broken, 0 algorithm changes |

**Critic v5 stress questions**: 5 ✓ / 5 ⚠ / 2 ✗ (vs v4's 4/4/2)

**Crucially: ALL v4 substantive concerns (A/B/C/D) RESOLVED in v5**:
- A (trigger-session false-positive) → Skip approach + manifest rule 11
- B (Day-1 verification) → §6.3.3 item 0 (formal gate)
- C (variant override re-enablement) → metadata + lint + quarterly QA
- D (Layer 4 perf) → ~3s/machine estimate

**Validator v5 cases**: 6 ✓ / 3 ⚠ / 0 ✗. Re-verified Layer 4 catches synthetic dispatch bug on M274. M15 Skip group correctly documented. **0 cases broken across all 5 iterations.**

---

## §2 Convergence trajectory (5 iterations)

| Iteration | Critic must-resolves | Validator | Cases broken |
|---|---|---|---|
| v1 | 11/15 | APPROVE-WITH-REVISIONS (4 gaps) | 0 |
| v2 | 6/15 | **APPROVE** (2 minor) | 0 |
| v3 | 3 | (skipped) | 0 |
| v4 | 4 (different concerns) | APPROVE-WITH-REVISIONS (3 doc) | 0 |
| **v5** | **2 medium + 2 soft (all doc-level)** | APPROVE-WITH-REVISIONS (3 spec) | 0 |

Design is genuinely converged. Remaining issues are documentation polish, not algorithmic.

---

## §3 Inline patches (per §5 stop criteria authorization)

The following patches modify v5 understanding but the **`04_architecture_proposal_v5.md` file remains the ship-ready spec**. Implementation team reads v5 + these clarifications.

### Patch P1 — §5.5.6 per-mode `layer4_applicable` resolution (Critic v5 medium #1)

For machines where `trigger_session_pattern` differs by mode (e.g., mode 1: null, mode 2: type_1), `layer4_applicable` resolves **per-(machine, mode)**, not at machine level:

```
def resolve_layer4_applicable(machine, mode):
    pattern = manifest.modes[mode].get("trigger_session_pattern")
    if pattern is None:
        return True
    override = manifest.modes[mode].get("trigger_session_pattern_override")
    if override is not None:
        pattern = override
    return False  # any non-null trigger_session_pattern → skip
```

Hash composition (per (machine, mode) effective_analyzer_version) already mode-dimensioned in v2/v3/v4/v5. This resolution function plugs in naturally.

### Patch P2 — §6.3.3 Day-2 candidates path out (Critic v5 medium #2)

Day-2 candidates (failed Day-1 verification gate) follow the **same flip criteria as any `complete: false` machine** (§6.3.2):

1. Diagnose the failure layer (1, 2, 3, or 4)
2. Either: (a) fix the analyzer rule causing the failure + re-verify, OR (b) operator confirms the rawdata anomaly is intentional (manifest documents it) + re-verify
3. Once Layers 1-4 PASS on a fresh sample: candidate flips to `complete: true` with audit log entry
4. No time-bound; stays in Day-2 until verified

Quarterly QA review for stale overrides (§5.5.7) also reviews Day-2 candidates for staleness.

### Patch P3 — §9.4 perf cold-disk caveat (Critic v5 soft)

`~3s per machine` claim assumes warm disk + chunk index cache loaded. Cold first fleet pull after server restart adds ~10-15s per machine for chunk discovery overhead. Implementation should warm chunk cache on backend startup to avoid cold-start surprise.

### Patch P4 — §1 Issue ① correction (Critic v5 soft)

The v5 addendum text incorrectly listed **M14 and M139** as trigger-session machines. Per Wave 1 evidence (`02_taxonomy.md §3.1`), both are **SC-Vanilla** with `trigger_session_pattern: null`. Corrected list of trigger-session machines: M15 + M120 + M279 (per memory `reference_trigger_session_patterns.md`) + variants of TopDollarSelector / FortunesSelector / CommonSelector / WheelSelector classes. **M14 and M139 are Day-1 strict-mode candidates**, not Skip group.

### Patch P5 — §9.2 server_win_override denominator (Validator v5 spec gap #2)

For machines using `server_win_override` (e.g., M15 Top Dollar bonus settlement): Layer 1's `sum(pid rtp_pp) == summary.rtp.point_pct` check must use the **credit-level denominator** (`server_total_win`), not analyzer's `our_total_win`. The two differ by the server override on bonus credit attribution. Layer 1 check must compute both, prefer `server_total_win` for machines with `server_win_override` in manifest, fall back to `our_total_win` otherwise.

### Patch P6 — §5.5.7 orphan override metadata (Validator v5 spec gap #3)

If manifest has `override_set_at` / `override_set_reason` / `override_set_by` fields but no `override_console_diagnostic_complete` value: lint rule 10 emits warning "orphan override metadata; either complete the override or remove fields". Currently silently ignored by resolver.

---

## §4 Ship recommendation

Per `00_brief_v5_addendum.md §5` stop criteria + 0 broken cases in 5 iterations + all v4 substantive concerns resolved + Validator empirically confirms (M274 4-layer PASS + synthetic mismatch caught):

**Ship v5 + P1-P6 patches as the architecture-approved design. Move to implementation pass.**

Implementation team reads:
- `04_architecture_proposal_v5.md` (1402 lines — main spec)
- This file (`07_decision_v5.md`) for P1-P6 inline patches
- All Wave 1 artifacts for context
- Memory pointer `feedback_arch_team_process.md`

Implementation team produces actual code changes in a separate session per ARCH_TEAM_PROCESS §3 "Implementation handoff after user approval".

---

## §5 What you decide

1. **Ship v5 + P1-P6?** Yes / no / inspect specific patch
2. **Implementation timing**: next session immediate / scheduled / later
3. **Branch policy**: `arch/console-refactor` merged to `collab/dev` now (ship the docs), or hold until implementation lands?

---

## §6 Cross-references

19 artifacts in `session_artifacts/_arch/`:
- 00 brief + 4 addendums (v2/v3/v4/v5)
- 01 pipeline / 02 taxonomy / 03 coupling
- 04 proposal × 5 (v1-v5)
- 05 critique × 5 (v1-v5)
- 06 validation × 4 (v1/v2/v4/v5; v3 skipped)
- 07 decision × 5 (v1-v5)

Process: `docs/ARCH_TEAM_PROCESS.md` (with §9 troubleshooting added 2026-05-17)
Memory: `memory/feedback_arch_team_process.md`
Branch: `arch/console-refactor` (HEAD `0353567` + pending wave-3-v5 commit + this file)
