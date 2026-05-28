# 07 — Coordinator Decision Summary (R1)

> **Date**: 2026-05-28
> **Coordinator**: main session
> **Status**: arch-* R1 complete; proceed to impl-* Phase 1 (Cluster E)
> **Recommendation**: APPROVED with coordinator-resolved interpretation gaps

---

## §1 Process recap

| Wave | Agent | Verdict | Output |
|---|---|---|---|
| W1 | arch-mapper | facts (4 error paths + 4 D sites + 8 test files; base_hash hex pin intentional) | 01_pipeline_map.md |
| W1 | arch-taxonomist | facts (d1: 32 machines / d2: ~37 / d3: 0 / d4: 1 frontend consumer); **d2 real correctness bug (M275 NCS 841 vs NewFreespin 67)** | 02_taxonomy.md |
| W1 | arch-coupling-auditor | E must precede D (RED tests); A try/finally zero blast on success | 03_coupling_audit.md |
| W2 v1 | arch-designer | Phase E→D→A; A-3 two-region try/finally; d2 chain-count majority; E-3 differential | 04_architecture_proposal.md |
| W3 v1 | arch-critic | APPROVE-WITH-REVISIONS — TC-1 test count undercount, TC-2 silent fallback, TC-3 Region 2 test | 05_critique.md |
| W3 v1 | arch-validator | APPROVE-WITH-REVISIONS — B1 + B2 same findings as critic | 06_validation.md |
| W2 v2 | arch-designer | 3 surgical fixes; high confidence | 04_architecture_proposal_v2.md |
| W3 v2 | arch-critic | APPROVE-WITH-MINOR-REVISIONS — CR-1 `_make_stash()` interpretation, CR-2 fallback warning | 05_critique_v2.md |
| W3 v2 | arch-validator | **APPROVE 10/0/0** — Phase 2/3 NOT ordering risk; CR-1 contradicts critic (1-feature → "unique" branch) | 06_validation_v2.md |

## §2 Coordinator-resolved interpretation gaps

### CR-1: `_make_stash()` impact disagreement

Critic v2 + Validator v2 read d2 dispatch ordering oppositely:
- Critic: check stash → dispatch by len → 1-feature crashes on missing stash
- Validator: dispatch by len FIRST → len==1 hits "unique" branch (no stash check)

**Coordinator decision**: validator reading (len-first dispatch). Justification:
- 1-feature case is deterministic ("unique") — no need for chain_counts data
- len-first ordering doesn't change CR-2 concern (fallback for len≥2 with empty chain_counts still surfaces)
- Existing test infrastructure (`_make_stash()` 1-feature) remains unbroken
- Implementer brief for Phase 2 will spec this explicitly

### CR-2: fallback_no_chain_data companion warning

Real spec gap. v2 missing `feature_errors` companion entry when fallback fires.

**Coordinator decision**: ADD companion warning per `feedback_invariant_with_fallback_hides_drift.md`. Implementer brief Phase 2 will spec:
```
When trigger_target_confidence == "fallback_no_chain_data":
  summary["feature_errors"]["bonus_chain_dynamics_fallback_<pid>"] = {
    "type": "alphabetical_fallback",
    "reason": "scatter_feature_chain_counts all-zero for pid X",
    "pid": "...",
    "chosen_target": "...",
    "candidates": [...]
  }
```
Operator sees explicit alert, not silent emission.

## §3 Phase plan (3 commits, with coordinator-resolved details)

| Phase | Cluster | Files modified | Hash impact | Status |
|---|---|---|---|---|
| **1** | E (test refactor) | 8 test files: dynamic compute_effective_version_for_machine + structural differential | **0 production code** → 0 machines invalidated | **READY — start now** |
| **2** | D (4 fixes) | payouts_by_spin_type.py (d1), bonus_chain_dynamics.py (d2 + d3), PIA inline (d4 if needed) | d1 → 253 declaring; d2+d3 same file → 253 (one flip); d4 PIA analyzer_version only | **READY after Phase 1 lands** (uses Phase 1's dynamic test pattern) |
| **3** | A (error surfacing) | PIA main() two-region try/finally + topo_sort.py new exception class | 0 machines invalidated (error path only) | **READY** — can ship parallel to Phase 1/2 |

Phase 2/3 ordering NOT a risk per validator: d2 RuntimeError caught by existing C2 `except Exception` → `feature_errors` graceful path. Phase 2 ships standalone if Phase 3 not yet shipped.

## §4 Open questions surviving R1 (deferred to implementer)

- SQ-1: fallback warning enabled? → **YES per CR-2 decision above**
- SQ-2: Region 2 inject in-process vs subprocess? → in-process via `monkeypatch.setattr(feature_registry, "ALL_FEATURES", new_list)` per validator v2
- SQ-3 (new): which test_c6 file actually has `_make_stash()` — confirm in implementer brief

## §5 Coordinator recommendation

**APPROVED with above CR resolutions. Start impl-* Phase 1 (Cluster E) immediately.**

Phase 2 brief will be written with CR-1 (len-first dispatch) + CR-2 (companion warning) already resolved.

Phase 3 brief will reference v2 §4.3 + §4.4 Region 2 spec.
