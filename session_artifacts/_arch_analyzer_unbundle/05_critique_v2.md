# 05 — Architecture Critique v2: Analyzer Unbundle (M275-driven)

> **Produced by**: arch-critic (W3) — v2 re-review pass
> **Date**: 2026-05-25
> **Topic dir**: `session_artifacts/_arch_analyzer_unbundle/`
> **Proposal reviewed**: `04_architecture_proposal_v2.md`
> **v1 critique checked against**: `05_critique.md` (15 questions, 11 MRs, 7 ECs, 5 TCs)
> **Validation cross-reference**: `06_validation.md`

---

## §1 Top Concerns (v2)

**TC1 — `PipelineContext` field completeness is explicitly left to implementation-time discovery (04_v2 §16 SQ2)**

The designer acknowledges in Open Question SQ2 that the 6 `PipelineContext` fields were derived from `01_pipeline_map.md §7 Dependency E` and the v1 critic's EC6/EC7 — but admits that Block F5 (440 lines) and Block F9 (124 lines) may require additional fields not yet identified. The dataclass is shipped as `@dataclass` with 6 declared fields, all required (`ALL fields are required` per §4.1), with no mechanism for extension. If Phase C5 implementation reveals a 7th required field, every prior phase's `PipelineContext` construction must be updated retroactively and all affected tests must be re-run. The "required + no extension" contract means a missed field is a Phase C5 blocker that forces a C1 patch. This is not a "design is wrong" finding — it is a design with a known hole where the designer correctly names the risk but does not bound it. An acceptable design can leave implementation-time discovery open, but only if the discovery path does not cause cross-phase retroactive breakage.

**TC2 — DECLARED_DEPS key-presence check still allows silent semantic failures during Phase C5 migration (v1 TC3, status: partially resolved)**

The v2 spec (§4.2) adds the dep validation loop before `emit()` is called for each plugin. The check is `if dep_key not in summary: raise RuntimeError`. This closes the "completely missing key" failure mode. However, as the designer acknowledges in Open Question Q3 (§15): the check does not catch `summary["_bcm_bonus_feature"] = None`. During Phase C5, `upstream_feature.emit()` runs first and writes `_bcm_bonus_feature`. If `upstream_feature.emit()` raises a caught exception mid-write (per §4.3 error handling: "log + set `summary["_feature_errors"][fid]`"), the key may be partially written or absent entirely. In that case, the DECLARED_DEPS check fires a RuntimeError when `collect_mechanic.emit()` tries to run — killing the entire emit loop even though the error was in `upstream_feature`, not `collect_mechanic`. This is a "cascading error from a logged-and-continued upstream failure" scenario. The v2 spec's error handling for `emit()` says "log + set `_feature_errors`; do NOT crash" — but the DECLARED_DEPS pre-check is a separate, unconditional `raise RuntimeError`. These two behaviors are inconsistent: upstream failure logs and continues, but its missing dep output causes a hard crash in the downstream. Whether RuntimeError on a DECLARED_DEPS miss should kill the run or be treated like an emit() failure is not specified.

**TC3 — Chicken-and-egg: F1-must-precede-registry sentinel vs. F1-as-future-plugin (v1 TC2, status: resolved but a new forward risk)**

V2 resolves the immediate TC2 concern: the sentinel assertion `assert "spin_type_breakdown" in summary["player_impact"]` is now specified at §4.2, and C1 deliverable §7.2 explicitly states F1 must complete before `_build_mechanism_registry()`. This is closed for the current design. However, §7.3 post-carve PIA state at the end of Phase C6 still lists "Block F1 inline: stays inline" as a permanent decision. If a future phase (C7+) attempts to carve F1 into a plugin, the sentinel assertion would need to be replaced by a `REQUIRES` entry from the registry builder — which is not a plugin. This creates a forward maintenance trap: the sentinel works because F1 is inline; the moment F1 becomes a plugin, the ordering enforcement breaks. This is not a v2 blocker, but it is an undisclosed forward risk that the implementation team must not discover mid-C7.

**TC4 — `emit()` signature adds mandatory 3rd parameter `ctx: PipelineContext` but existing 4 plugins accept 2 parameters — transition spec is present but the call-site fix is also load-bearing (v1 TC5, status: addressed but residual)**

V2 §4.1 specifies: "C1 deliverable explicitly requires updating all 4 existing plugins' signatures to `emit(self, final_acc, summary, ctx)` where `ctx` is accepted but not used." This is correct and specified. However, there is a subtlety at the call site: the current PIA call is `_feature.emit(None, summary)` — the first argument is `None` as the `parse_state` position (per v1 Risk C1-2 analysis). V2's new call is `_feature.emit(final_acc, summary, ctx)`. This means the `None` was not `final_acc` but `parse_state`. The v2 ABC shows `emit(self, final_acc: dict, summary: dict, ctx: PipelineContext)` — so the corrected call signature also changes the semantics of the first argument from `parse_state=None` to `final_acc={}`. For Pattern A plugins with assertions like `assert key in summary["player_impact"]`, this is safe because they don't use `final_acc`. For `BankruptcySimulation` (Pattern B), which uses `final_acc` (the per-plugin accumulated extract() output), changing the first argument from `None` to the actual accumulated dict IS a behavior change — not just a signature update. C1 deliverable 4 says "BankruptcySimulation: add DECLARED_DEPS; update emit() signature; no behavior change." This is incorrect: `BankruptcySimulation` previously received `None` as its first arg and must have been accessing its accumulated data from somewhere else. If it now receives a real `_feature_accs.get(FEATURE_ID, {})` dict, the behavior may change.

**TC5 — `mechanism_registry.py` hash gap is now explicitly acknowledged, but the mitigation is operator-reliant with no detection mechanism (v1 Q1, status: partial)**

V2 §8.2 now explicitly states: "changes to `mechanism_registry.py` are NOT reflected in `effective_analyzer_version`; operators must manually invalidate when registry detection logic changes." This closes the documentation gap from v1. The acknowledged mitigation is: "Operators must manually trigger report regeneration when the detection logic in `mechanism_registry.py` changes." Per `memory/feedback_fallback_hides_drift.md`, monitoring gaps that rely on human discipline rather than automated detection are known to decay. The proposal has no mechanism to detect when `mechanism_registry.py` has changed without a matching operator action. This is the same pre-existing gap for `round_classification.py` and `round_win.py`, so it is not worse than the status quo — but it means the architecture introduces a third file with this gap rather than resolving the pattern.

---

## §2 Part A: Did Designer Close v1 Gaps?

### The 5 Mandatory Revisions

#### REV-1 (v1 Blocker) — F1 ordering enforcement
**v2 section**: `04_v2 §4.2`, `§7.2 C1`
**Resolution**: RESOLVED. V2 specifies Phase B → Phase C → Phase D execution ordering with explicit sentinel: `assert "spin_type_breakdown" in summary["player_impact"]` before `_build_mechanism_registry()` is called. C1 deliverable 7 and 8 include ordering enforcement and `_EMIT_PHASE_PRECONDITIONS` sentinel. The constraint is now an enforced runtime invariant, not an implicit convention.
**Verdict**: Resolved.

#### REV-2 (v1 Blocker) — All-3-import-sites enumeration
**v2 section**: `04_v2 §7.2 Phase C2 deliverable 5`, `§15.5 acceptance table`
**Resolution**: RESOLVED. §15.5 is a per-phase acceptance criteria table that explicitly lists, for each new plugin, the 3 import sites: `pia:4816-4827` (both try blocks), `versioning.py:165-176`, `validate_manifests.py:43-47`. The table also specifies `len(ALL_FEATURES) == N` as an acceptance criterion for each phase. This closes the silent wrong-version risk documented in `03_coupling_audit.md §2.2 Symbol 5`.
**Verdict**: Resolved.

#### REV-3 (v1 Blocker) — Raw accumulator scalars for plugin emit()
**v2 section**: `04_v2 §4.1 PipelineContext`, `§4.2 Phase D pseudocode`
**Resolution**: RESOLVED with one bounded open item. V2 specifies `PipelineContext` dataclass with 6 fields (`effective_bet_for_rtp`, `total_spins`, `total_paid_sessions`, `total_paid_spins`, `clamp_pending_robots_total`, `robots_with_pending_cycle`, plus `mechanism_registry`). The Phase D pseudocode shows `ctx = PipelineContext(...)` constructed from local accumulator variables before the emit loop. The open item (SQ2) — that Block F5's 440 lines may require additional fields — is explicitly flagged as an implementation-time discovery. This is acceptable: the designer cannot fully enumerate without reading all 440 lines. However, the "ALL fields are required" contract on the dataclass means discovering a new field is a retroactive C1 patch. This bounded open risk is acceptable for APPROVE but must be noted for the impl team.
**Verdict**: Resolved (with bounded open risk noted in TC1).

#### REV-4 (v1 Significant) — mechanism_registry.py hash gap explicit documentation
**v2 section**: `04_v2 §8.2`
**Resolution**: RESOLVED. §8.2 now explicitly states the gap and its mitigation, alongside the pre-existing acknowledgment for `round_classification.py` and `round_win.py`. The change log entry R-16 confirms this was driven by `05 Q1`.
**Verdict**: Resolved.

#### REV-5 (v1 Significant) — Phase C2 behavior change for 50 scatter-marker machines
**v2 section**: `04_v2 §7.2 Phase C2 deliverables`, `§11.2 backward compatibility table`
**Resolution**: RESOLVED. §11.2 now has a dedicated row: `payout_ids_top20 scatter marker category — C2 BEHAVIOR CHANGE: 50 machines' scatter marker pid moves from cat=paid to cat=scatter_trigger`. This is explicit in the migration table. The qualification that `rtp_integrity_contract.required_attribution_anchors` is unaffected (anchors are by PID, not by category) is present.
**Verdict**: Resolved.

---

### v1 Top Concerns (TC1–TC5) Resolution Tracking

| Finding | v2 Section | Status |
|---|---|---|
| TC1 — Registry build timing uses Tier 2 evidence not yet computed | §3 objection response, §4.2, §5.2 | Resolved: v2 replaces Tier 2 dependency on `bonus_chain_dynamics` output with raw merge-loop `bonus_chain_lengths` accumulator (available pre-emit). |
| TC2 — F1 must emit before registry build, not enforced | §4.2 Phase B sentinel, §7.2 C1 | Resolved: sentinel assertion + C1 deliverable 7 enforces this. |
| TC3 — DECLARED_DEPS is key-presence check, silent semantic failures remain | §4.2 dep validation, §15 Q3 | Partially resolved: key-presence check added; semantic-null case (dep present but None) flagged as open Q3. |
| TC4 — "Universal" phase additions = 5×253 rebuild burden, no pilot window | §11.7 batch-rebuild workflow | Partially resolved: §11.7 specifies operator workflow and burden estimation. Pilot-window concern is acknowledged but accepted (inline code already ran for all machines; universalizing is correct). |
| TC5 — `_mechanism_registry` cleanup timing vs non-JSON object | §4.2 cleanup block | Resolved: cleanup runs after ALL plugins have emitted; no plugin runs after cleanup. The `PipelineContext.mechanism_registry` field also gives plugins a second reference path. The confusing-failure risk during development remains but is not a production correctness risk. |

---

### v1 Stress Questions (Q1–Q15) Resolution Tracking

**Q1 — mechanism_registry.py hash gap**
**v2**: §8.2 explicitly acknowledges the gap and its accepted limitation.
**Verdict**: Resolved (acknowledged-and-accepted).

**Q2 — Jackpot PID threshold edge cases (scatter exclusion ordering)**
**v2**: §5.2 Tier 3 raw specifies scatter detection runs FIRST, then jackpot candidates are filtered: `jackpot_candidates - scatter_marker_pids`. §12.3 M275 end-to-end walk shows `{27502, 27503, 27504, 666} - {666} = {27502, 27503, 27504}`. R-08 and R-09 in the change log confirm.
**Verdict**: Resolved.

**Q3 — DECLARED_DEPS topo-sort edge cases (cycles, missing deps, typos, determinism)**
**v2**: §4.2 specifies Kahn's algorithm, `PluginCyclicDependencyError` on cycle, `PluginMissingDependencyError` on missing dep, lexicographic tie-breaking. R-04 confirms.
**Verdict**: Resolved for algorithm and edge cases. One gap remains: the DECLARED_DEPS pre-check vs emit() error handling inconsistency (TC2 above).

**Q4 — `_st_label` reconstruction requires F1 to have already emitted**
**v2**: §4.2 Phase B sentinel guarantees F1 completes before emit loop. §7.2 C3 deliverable 1 confirms `payouts_by_spin_type` reads `summary["player_impact"]["spin_type_breakdown"]` which is guaranteed by Phase B.
**Verdict**: Resolved.

**Q5 — Backward compat for existing reports missing new `machine_mechanics` fields**
**v2**: §11.2 migration table addresses this: old reports remain readable with wrong values; frontend handles absent fields as null. §14.8 defers `REGISTERED_FALLBACK_RULES` production consumption. The concern that old inline-produced `machine_mechanics` has no `schema_version` field is accepted — the fallback mechanism is not needed because additive fields render safely, and semantic corrections (jackpot.applicable flip) are detected by `effective_analyzer_version` staleness. This was v1's "NOT ADDRESSED" verdict; v2 still defers REGISTERED_FALLBACK_RULES but provides the migration table explanation.
**Verdict**: Partially resolved. The `REGISTERED_FALLBACK_RULES` non-consumption is explicitly deferred at §14.8 with rationale. The additive-only nature of Phase C3 changes and the version-based staleness detection make this acceptable for current phases. A breaking schema change would need this resolved first.

**Q6 — Per-chunk extract() memory characterization**
**v2**: Not addressed in v2. §4.1 ParseState schema lists what chunk_dict fields are guaranteed but does not address memory cost of per-plugin accumulators. The designer's C1 deliverables do not include a memory bound analysis.
**Verdict**: Unresolved (same as v1 verdict: PARTIAL). Acceptable risk — plugins accumulate from already-aggregated chunk records, not from raw round-level data. No new information added in v2.

**Q7 — Phased carve invalidation cadence: operator workflow for 1265+ rebuilds**
**v2**: §11.7 adds a batch-rebuild operator workflow section. Specifies `FleetRefreshManager`, "Regenerate all historical (from cache)" workflow, ~633 stale entries per phase × 5 phases, wall-clock estimates, and edge case for machines with no valid cached chunks (M281 etc. remain historical).
**Verdict**: Resolved.

**Q8 — Sidecar persistence race conditions**
**v2**: §5.4 addresses per-run sidecar (unique `rv_` directory, no collision) and defers the optional `latest_portrait.json` pointer to Phase 3 with atomic-rename pattern noted.
**Verdict**: Resolved (same as v1 verdict: ADEQUATELY ADDRESSED for core sidecar).

**Q9 — Cross-reference detector confidence with upstream API changes**
**v2**: Not addressed beyond what v1 had. The three-tier precedence (Tier 1 manifest override as escape valve) remains the answer. The gap that 96% of BCM machines have unreviewed manifests (so Tier 1 won't be populated) is acknowledged in the B_BCM archetype scope but not addressed.
**Verdict**: Unresolved (same as v1 PARTIAL verdict). Acceptable for the current proposal scope.

**Q10 — "Zero-code new machine" claim for M275 with multiplier wilds excluded**
**v2**: §13.1 and §13.2 table now explicitly states "Multiplier wilds: NOT YET (gap #4)" as a dedicated row. The claim is now scoped correctly.
**Verdict**: Resolved.

**Q11 — Hidden F5→F6 dependency via `spin_type_to_feature`**
**v2**: §7.1 ordering constraint explicitly adds: "F5 (upstream_feature.emit()) may need to run before F6 (bonus_chain_dynamics.emit()) for the spin_type_to_feature dependency at pia:3501." §7.2 C5 deliverable specifies `BonusChainDynamicsFeature.REQUIRES = ("upstream_feature",)` and `DECLARED_DEPS = ("_spin_type_to_feature",)`. §7.2 C6 deliverable 1 confirms `upstream_feature.emit()` writes `_spin_type_to_feature` as a DECLARED_DEP output. R-03 and §7.1 pseudocode confirm.
**Verdict**: Resolved.

**Q12 — Frontend renderer SCHEMA_VERSION bump in Phase C3**
**v2**: §14.8 and §14.2 now explicitly defer `REGISTERED_FALLBACK_RULES` production consumption. The additive-fields-are-safe claim is maintained. The concern about hard-coded field references in `app.js` is not verified in v2 (designer does not grep app.js). The §15 Q7 flags this as an open question for W3 v2.
**Verdict**: Partially resolved (deferred with rationale; app.js grep not done but flagged as implementation acceptance criterion).

**Q13 — Gap #6 `estimated_correction_pp = 0.0` scope**
**v2**: §15 Q1 and §12.5 resolve this: Gap #6 is a labeling issue, not a formula bug. The portrait will add a human-readable distinction between `pending_paid_spins_pct` and `pending_cycle_count`. No formula change required. Validator (06 §2 Case 1) confirms from live data.
**Verdict**: Resolved (confirmed by validator evidence).

**Q14 — M273 family benefit claim: clarified mechanism**
**v2**: §11.4 revised with precise framing. M275-specific corrections benefit M275 only. Universal plugin addition benefits all 253 non-variant manifests including M273.json. M273's 85 variants inherit via `inherits_from` cascade. §13.2 confirms the "107 entities" figure is for universal plugin addition, not M275-specific fixes.
**Verdict**: Resolved.

**Q15 — Three-import-site enumeration for new plugins**
**v2**: §15.5 acceptance criteria table explicitly lists all 3 import sites per phase, with `len(ALL_FEATURES) == N` verification criterion. Change log R-12 confirms.
**Verdict**: Resolved.

---

### v1 Migration Risks (MR1–MR11) Resolution Tracking

| Risk | v2 treatment | Status |
|---|---|---|
| C1-1 (dual-path extract() wiring) | §7.2 C1 deliverable 6 explicitly requires BOTH paths; §15.5 C1 acceptance criteria include both-paths test | Resolved |
| C1-2 (emit signature load-bearing change) | §4.1 backward-compat note + C1 deliverable 5; but the `parse_state=None` → `final_acc={}` semantic drift for BankruptcySimulation is a new concern (TC4) | Partially resolved (new gap opened) |
| C1-3 (BankruptcySimulation DECLARED_DEPS + RuntimeError new behavior) | §7.2 C1 deliverable 4; DECLARED_DEPS validation now a pre-check | Unresolved: test coverage for BankruptcySimulation under new validation not specified |
| C2-1 (double-write if F2 inline removal incomplete) | §7.2 C2 deliverable 2: "Block F2 and F2b inline code removed atomically" | Resolved |
| C2-2 (50 non-666 scatter machines behavior change) | §11.2 migration table explicitly calls this out | Resolved |
| C2-3 (payout_groups suppression edge case) | §5.2 corrects the detection to "two-field check (non-zero group_id AND non-zero win)" | Resolved |
| C3-1 (Pattern A assertion removal) | §7.2 C3 explicitly: SCHEMA_VERSION bump + F3 inline removal + assertion superseded by plugin output | Resolved |
| C4-1 (jackpot.applicable flip for 26 machines) | §7.2 C4 explicitly: "implementer must verify rtp_integrity_contract for each of the 26 machines" as acceptance criterion | Resolved |
| C5-1 (resolve_bonus_feature 3x → 1x consolidation) | §7.2 C5 deliverable 4: "_load_bcm_pairings() consolidated to one call." The 3-call→1-call consolidation is not verified as idempotent | Partially resolved (consolidation specified, idempotency not proven) |
| C5-2 (bcm_pairings.json not hashed) | §8.2 acknowledges as a deferred gap | Acknowledged-deferred (same as pre-v2) |
| XP-1 (rolling back C3 while C2 live) | §11.3 rollback paths unchanged from v1; PIA line number context after F2 removal is a risk that remains | Unresolved (acknowledged risk) |
| XP-2 (M275 manifest correction exposes Layer 4 failures) | §11.2 table notes Layer 4 SKIP for M275; §15 Q2 (M275 trigger-session applicability) is an open question | Partially resolved (open Q2 pending) |

---

### v1 Edge Cases (EC1–EC7) Resolution Tracking

**EC1 — First-time-load with mechanism_overrides but no rawdata**
**v2**: Not addressed. The edge case where `jackpot_pid_set` is Tier-1 populated but `payout_ids_top20` is empty (no rawdata) produces an inconsistency between portrait and panel. Still not covered.
**Verdict**: Unresolved.

**EC2 — Variant manifest with broken base**
**v2**: §11.6 addresses M273 variant auto-coverage but does not address the case of a malformed base manifest (M278, M280 mentioned in v1 EC2). §14.7 out-of-scope section covers only M250/M272/M279.
**Verdict**: Unresolved.

**EC3 — Machines with wrong spin_type_convention (116 of 253 manifests)**
**v2**: §13.2 table adds "B — BCM with non-standard ST (M108/M117/M125 ST=101): PARTIAL — Manifest spin_type_convention override." The freespin Tier 2 detection (`len(bonus_chain_lengths) > 0`) is ST-agnostic. The §15 Q6 flags this as an open question. Partially addressed but not resolved.
**Verdict**: Partially resolved.

**EC4 — Concurrent batch runs during phase transition (partial deployment)**
**v2**: Not addressed. The scenario where plugin file is added but not all 253 manifests updated is still not covered. §15.5 acceptance table ensures correct final state but does not address intermediate deployment window.
**Verdict**: Unresolved.

**EC5 — mechanism_portrait.py write failure behavior**
**v2**: §5.4 now fully specifies error handling: `_portrait_write_error.json` sidecar, logger.error call, main run continues. Change log R-10 confirms. Matches `memory/feedback_no_silent_swallow.md`.
**Verdict**: Resolved.

**EC6 — effective_bet_for_rtp availability during plugin emit**
**v2**: §4.1 PipelineContext dataclass includes `effective_bet_for_rtp` as a required field. Phase D pseudocode shows `ctx = PipelineContext(effective_bet_for_rtp=effective_bet_for_rtp, ...)`. The field is always available to every plugin's emit() via `ctx`.
**Verdict**: Resolved.

**EC7 — total_spins and total_paid_sessions denominators**
**v2**: §4.1 PipelineContext includes `total_spins`, `total_paid_sessions`, `total_paid_spins`, `clamp_pending_robots_total`, `robots_with_pending_cycle`. Change log R-14 confirms.
**Verdict**: Resolved.

---

## §3 Part B: New Problems Introduced by v2

### NP1 — `PluginCyclicDependencyError` / `PluginMissingDependencyError` surfacing path is unspecified

The v2 spec (§4.2) says these exceptions raise at "sort time" before any emit runs. But the spec does not say where they surface. Per `memory/feedback_no_silent_swallow.md`, exceptions must be persisted diagnostically to disk. The `emit()` error handling uses `summary["_feature_errors"][fid]`; the topo-sort errors happen before the emit loop, before `_feature_errors` is set up. If these errors are caught by PIA's outer try/except (which writes the run as failed), they surface in the run's error state but not in any structured diagnostic that an operator can inspect. If they propagate uncaught, the run crashes with a Python traceback in a subprocess log that may not surface in the console UI. Neither outcome matches the "persist diagnostic to disk" pattern required by project memory.

**Attempted designer response**: "These are programming errors (cycle or typo in REQUIRES), not runtime data errors. They should propagate as runtime exceptions and cause the run to fail, which the backend reports as a run error to the UI."
**Why insufficient**: Per `memory/feedback_no_silent_swallow.md`, the pattern is explicit: "any best-effort post-hook must put outcome to disk (rc + stderr tail + parsing path)." A cycle in DECLARED_DEPS discovered after Phase C5 ships would make all BCM machines fail to produce reports silently from the batch runner perspective unless the diagnostic is surfaced. The spec should state: "these exceptions are caught by PIA's outer error handler and written to `_run_error.json` alongside the run directory (or equivalent), not only to the subprocess stderr."
**Verdict**: Not addressed in v2. New gap.

### NP2 — Topological sort runs on every analyzer invocation; performance not characterized for 4+ plugins

Every PIA invocation calls `_topological_sort(_machine_features)`. For a machine with 8+ plugins (post-C6), this runs a Kahn's BFS every run. With 393 machines × multiple modes × potentially thousands of batch runs, this is called millions of times. Kahn's BFS is O(V+E) where V=plugin count and E=dependency edge count. For 9 plugins and ~4 edges, this is negligible. However, the v2 spec doesn't state whether `_topological_sort` is cached per `(manifest_hash, feature_set)` or recomputed per invocation. If recomputed per invocation, the cost is trivial but it means the `PluginCyclicDependencyError` / `PluginMissingDependencyError` check runs per invocation rather than at startup. An error introduced by a manifest edit is discovered at analysis time, not at import/startup time.
**Verdict**: Not a correctness concern; the cost is negligible. But the "error discovered at invocation time, not startup" behavior is worth noting for the impl team as an operational characteristic, not a flaw.

### NP3 — `PipelineContext.mechanism_registry` field creates a second reference path alongside `summary["_mechanism_registry"]`

V2 §4.1 adds `mechanism_registry: Any` as a field on `PipelineContext`. This means plugins can access the registry via either `ctx.mechanism_registry` or `summary["_mechanism_registry"]`. The §4.2 cleanup block deletes all `_`-prefixed summary keys after all plugins emit. A plugin that reads `summary["_mechanism_registry"]` during emit() is safe (cleanup runs after all emits). But the existence of two paths (ctx and summary) creates an inconsistency: if implementers use both paths in different plugins (some via ctx, some via summary), the behavior is equivalent but the code is inconsistent. More importantly: after cleanup, `summary["_mechanism_registry"]` is gone, but `ctx.mechanism_registry` still holds the reference. Any code that runs AFTER the emit loop (e.g., the RTP integrity gate, the write phase) that reads `ctx.mechanism_registry` still gets the live registry object. This is not a bug — the write phase does not have access to `ctx` unless explicitly passed. But it is a subtle design inconsistency worth flagging for the impl team.
**Verdict**: Minor inconsistency. Not a correctness risk for current phases.

### NP4 — `mechanism_overrides` hash dimension: machine adding then removing an override changes `effective_analyzer_version` twice, but both states may be "correct"

V2 §8.2 and §5 Q5 note that when `mechanism_overrides` is non-empty in the manifest, its contents are hashed into `effective_analyzer_version`. The SQ5 open question asks whether this should apply to all non-`analyzer_features` manifest fields or just `mechanism_overrides`. But a more specific concern is the asymmetric case: a machine adds `mechanism_overrides.freespin_applicable: true` (version flips), then inference improves and the override is removed (version flips again). The historical reports from the "with override" period are now stale. But the "without override" period may produce the same `freespin_applicable: true` via Tier 2 inference. An operator looking at historical reports cannot tell whether the old report had the correct value via override or the same correct value via inference. The `_detection_source` field in the portrait partially answers this, but historical reports don't have the portrait (it's written per-run and becomes stale with the run). This is a precision audit concern, not a correctness concern.
**Verdict**: Acceptable design tradeoff. Not a blocker.

### NP5 — F5→F6 `spin_type_to_feature` dep path: v2 adds it as DECLARED_DEPS but F5 writes it as a SIDE EFFECT of emit(), not as a primary output

V2 §7.1 states: "F5's `upstream_feature.emit()` will write `summary["_spin_type_to_feature"]` in addition to `summary["_bcm_bonus_feature"]` and `summary["_bcm_bonus_source"]`." The §7.2 C5 deliverable lists `_spin_type_to_feature` as a DECLARED_DEPS output for `upstream_feature`. But the `DECLARED_DEPS` ClassVar on `UpstreamFeatureFeature` is not shown in the spec — only `BonusChainDynamicsFeature.DECLARED_DEPS = ("_spin_type_to_feature",)` is listed. If `upstream_feature` does not declare `_spin_type_to_feature` in its own `DECLARED_DEPS`, the emit-loop runner's pre-check for `bonus_chain_dynamics` will verify `_spin_type_to_feature` is in summary — but there's no mechanism to verify `upstream_feature` is supposed to write it. The dep validation is one-directional (consumer declares what it reads; writer just writes). If `upstream_feature.emit()` has a bug and does not write `_spin_type_to_feature`, the DECLARED_DEPS check for `bonus_chain_dynamics` fires a RuntimeError — pointing at the consumer, not the writer. This is the same fragility pattern that existed before v2 for the temp-key stash; DECLARED_DEPS formalizes the consumer side but not the writer side.
**Verdict**: Partially new concern (v1 TC3 noted the general pattern; v2 resolves the `_bcm_bonus_feature` case but the `_spin_type_to_feature` case is new and not covered).

---

## §4 Migration Risk Inventory (v2)

### Phase C1 (revised assessment)

**C1-1 (dual-path extract() wiring)**: Resolved per §7.2 C1 deliverable 6. Both paths explicitly required.

**C1-2 (BankruptcySimulation first-arg semantic drift)**: Still present. V2 §4.1 says the current call is `_feature.emit(None, summary)` and v2 changes it to `_feature.emit({}, summary, ctx)`. For BankruptcySimulation (Pattern B), if the plugin currently accesses its accumulated data from `final_acc` (the first argument), receiving `{}` instead of a real accumulated dict would break it. If it accesses data from `summary["_bankruptcy_rows"]` only (which is set by PIA before the emit loop, not by extract()), then `final_acc={}` is safe. The proposal does not inspect whether BankruptcySimulation uses `final_acc`. This is a C1 acceptance criterion gap.

**C1-3 (BankruptcySimulation DECLARED_DEPS validation fires on missing dep)**: The dep validation now raises RuntimeError if `_bankruptcy_rows` is absent from summary. This is new behavior for any test or diagnostic path that calls `BankruptcySimulation.emit()` standalone. Tests for BankruptcySimulation must be verified against the new pre-check.

**NEW C1-4 (F5 block size makes PipelineContext field enumeration an implementation-time risk)**: Block F5 is 440 lines. The designer explicitly flags SQ2 — additional `PipelineContext` fields may be required at Phase C5 time. If a new field is discovered at Phase C5, C1's `PipelineContext` dataclass must be patched retroactively. Since the dataclass is `@dataclass` with all-required fields, the patch is a C1 re-touch and a re-run of all C2/C3/C4 tests.

### Phase C2 (no new risks beyond v1 assessment)

The §11.2 migration table now calls out the 50-machine scatter category change explicitly. The payout_groups two-field check correction is specified. Risk C2-3 is closed.

### Phase C5 (new risk identified)

**C5-3 (upstream_feature emit() writes 3 DECLARED_DEP outputs; partial write on error)**: If `upstream_feature.emit()` partially completes (writes `_bcm_bonus_feature` but fails before writing `_spin_type_to_feature`), the DECLARED_DEPS pre-check for `bonus_chain_dynamics` fires RuntimeError pointing at `bonus_chain_dynamics`, not at `upstream_feature`. The `_feature_errors["upstream_feature"]` entry would exist from the caught emit() exception, but the error routing is confusing. The implementation team should handle this by verifying all 3 DECLARED_DEP outputs are written atomically (all or nothing) in `upstream_feature.emit()`, or by checking for partial write.

### Cross-phase rollback risks (unchanged from v1 assessment)

XP-1 (rolling back C3 while C2 live) and XP-2 (M275 manifest correction exposing Layer 4 failures) remain as before. V2 does not add new cross-phase rollback risks.

---

## §5 Edge Cases Not Covered in v2

**EC1 (from v1) — First-time-load with mechanism_overrides and no rawdata**: Still not covered. The inconsistency between `jackpot_pid_set` in portrait (Tier 1 populated) and `payout_ids_top20` empty (no rawdata) is not addressed.

**EC2 (from v1) — Variant manifest with broken base manifest**: Still not covered.

**EC4 (from v1) — Concurrent batch during partial deployment**: Still not covered.

**EC-NEW-1 — What happens when `bonus_chain_lengths` accumulator is absent (not an empty list but missing)**

V2 §5.2 Tier 2 blocking rule states: "Only when Tier 2 has NO signal (the accumulator key is absent, which should not occur in a well-formed run) does Tier 3 activate." The spec says this "should not occur" but does not specify what an "ill-formed run" looks like. If a machine has no bonus chain events AND a chunk parser bug causes `bonus_chain_lengths` key to be entirely absent from the merged accumulator (not `[]` but missing), Tier 3 activates. Tier 3 checks `total_freespin_chain_spins > 0`. For a B_BCM_WHEEL machine (no freespin), this is 0 → `freespin_applicable = False` (correct). For a corrupted B_BCM_FREESPIN machine where freespin events occurred but `freespin_chain_spins` accumulator also has a parser bug, Tier 3 would also miss them. The "should not occur" claim is not validated.

**EC-NEW-2 — What does the sentinel assertion do for a run where PIA crashes before Phase B completes?**

The sentinel `assert "spin_type_breakdown" in summary["player_impact"]` fires before `_build_mechanism_registry()`. If F1 inline code crashes (e.g., missing key in payout accumulator for a machine with unusual ST distribution), the sentinel fires an AssertionError, not a clean error message. PIA's outer error handler catches this AssertionError, writes a failed run. The operator sees a run error. But the error message "INVARIANT: F1 must write spin_type_breakdown before registry build" gives the operator no information about WHY F1 failed. A better pattern would be to catch and re-raise with context. This is a UX concern, not a correctness concern.

**EC-NEW-3 — `mechanism_overrides` manifest field interaction with `effective_analyzer_version` when the field is an empty dict vs absent**

V2 §8.2 says: "when `mechanism_overrides` is non-empty in the manifest, its contents are hashed." If `mechanism_overrides: {}` (empty dict) is added to a manifest, is it hashed (empty hash) or ignored (treated as absent)? If the hashing checks `if mechanism_overrides` (Python falsy for empty dict) vs `if "mechanism_overrides" in manifest`, the behavior differs. A manifest with `mechanism_overrides: {}` vs no `mechanism_overrides` key would produce different effective versions under one interpretation and the same version under another. This edge case is not specified.

---

## §6 Hidden Assumptions (v2)

**HA1 (from v1) — F1 output structure stable**: Now partially enforced via sentinel. The sentinel guards against F1 not running; it does not guard against F1 writing a malformed `spin_type_breakdown`. Still an assumption but now with partial enforcement.

**HA2 (from v1) — 26 jackpot-PID machines have PIDs observed in cached data**: Not addressed in v2. The rare jackpot event problem (hit rate < 1 in 10k spins means it may not appear in cached chunks) remains a Tier 3 detection gap for low-frequency jackpot machines.

**HA3 (from v1) — REQUIRES DAG is cycle-free**: Now enforced with `PluginCyclicDependencyError`. Resolved.

**HA4 (from v1) — validate_manifest handles new DECLARED_DEPS and REQUIRES ClassVars**: Now addressed via §15.5 acceptance criteria which require adding to `validate_manifests.py` as an import site. The import ensures `ALL_FEATURES` is correct at validation time. Resolved for the feature-ID validation. Not addressed: whether validate_manifests.py validates that `DECLARED_DEPS` entries are valid keys (not arbitrary strings). This is a lower-risk assumption.

**HA5 (from v1) — MechanismRegistry JSON serializability**: The cleanup block deletes `_mechanism_registry` from summary before write. The `mechanism_portrait.py` separately serializes the registry via `to_summary_dict()`. The risk is that a plugin's emit() embeds a registry reference inside a non-`_`-prefixed summary key (e.g., `summary["machine_mechanics"]["_registry_ref"] = registry`). The cleanup block only deletes top-level `_`-prefixed keys. Nested references survive cleanup and cause JSON serialization failure. This remains an assumption — the spec does not prohibit plugins from storing registry references in their output.

**HA-NEW-1 — `_feature_accs` dict is correctly keyed by FEATURE_ID and persists across both merge loop paths**

The v2 pseudocode at §4.2 shows `_feature_accs.get(_feature.FEATURE_ID, {})` in the emit loop. This assumes that the same `_feature_accs` dict is populated during both the from-cache path (pia:1614) and the online path (pia:2620), and that the keys are `FEATURE_ID` strings. This is correct if the extract() wiring uses `FEATURE_ID` as the accumulator key in both paths. The spec at §7.2 C1 says "both paths receive the same `_feature_accs` dict" — this is stated but not elaborated. The online path and from-cache path are in separate loop branches; sharing a dict across them requires that the dict is initialized before the branch decision and passed into both branches. Whether `_feature_accs` is initialized at PIA main() scope (above both branch conditions) or inside each branch is an implementation detail that the spec does not address explicitly. If `_feature_accs` is initialized inside one branch only, the other branch cannot populate it.

---

## §7 Comparison to Alternatives (v2 pass)

### Alternative 1 — Deferred mechanism registry, per-block fixes only

**v1 rejection rationale**: "does not address root cause; recreates coupling; does not close extract() lifecycle gap; does not deliver zero-code new machine property."

**v2 re-check**: The rejection remains valid. V2 does not change any of the four rejection reasons. The zero-code property for Case-B machines is the primary user goal per `00_brief.md §1`. Alternative 1 cannot deliver this. The critic noted in v1 that the coupling argument was slightly overstated (reading `payout_id_win` from F8's scope is a local accumulator access, not a cross-panel write/read). V2 does not address this nuance — it is not load-bearing for the rejection. Rejection is correct.

### Alternative 3 — Per-chunk extract() wiring only

**v1 rejection rationale**: "does not close any of the 8 gaps; no standalone value."

**v2 re-check**: The rejection stands. The v1 critic noted that Alternative 3 has "more than zero standalone value" as it unblocks Pattern B carves. V2 does not respond to this nuance. However, since v2's Phase C1 IS Alternative 3 (plus the emit loop fix and mechanism registry), Alternative 3 is subsumed rather than rejected. The designer chose correctly: implement Alternative 3's infrastructure as Phase C1 and then build on it with Phases C2-C6. The formal rejection of Alternative 3 as a standalone option remains correct.

---

## §8 Grading Each Mandatory Revision

| Revision | Grade | Notes |
|---|---|---|
| REV-1 (F1 ordering enforced sentinel) | Resolved | §4.2 Phase B sentinel + C1 deliverable 7; runtime assertion enforced |
| REV-2 (3-import-site enumeration) | Resolved | §15.5 table enumerates all sites per phase with ALL_FEATURES count criterion |
| REV-3 (PipelineContext for accumulator scalars) | Resolved with bounded open risk | 6 fields specified; F5 block discovery gap explicitly flagged as SQ2; retroactive patch risk for impl team |
| REV-4 (mechanism_registry.py hash gap documented) | Resolved | §8.2 explicit statement alongside round_classification.py |
| REV-5 (50 scatter-machine behavior change in migration table) | Resolved | §11.2 dedicated row for scatter category change |

4 of 5 mandatory revisions fully resolved; REV-3 resolved with bounded open risk that is acceptable. All 5 meet APPROVE threshold.

---

## §9 Verdict

**APPROVE-WITH-MINOR-REVISIONS**

All 5 mandatory revisions from v1 are addressed in v2. The architecture is sound, the ordering contract is enforced, the accumulator availability is specified, the import-site enumeration is complete, and the migration table correctly describes behavioral changes. The proposal is ready for the implementation phase pending two minor revisions and one bounded open item.

### Minor revisions required before implementation

**MR-v2-1 (Moderate): Specify surfacing path for `PluginCyclicDependencyError` / `PluginMissingDependencyError`**

Per `memory/feedback_no_silent_swallow.md`, these exceptions must be captured in a persistent diagnostic. The current spec says they raise RuntimeError at sort time before any emit runs. The proposal must specify: (a) these exceptions are caught by PIA's outer error handler; (b) they are written to the run's error record (or `_run_error.json`) alongside the run directory; (c) they surface in the console UI's run-error state. "They propagate as uncaught Python exceptions" is insufficient for a batch runner that may silently mark the run as failed without surfacing the cause to the operator.

**MR-v2-2 (Minor): Verify BankruptcySimulation first-arg semantics before C1 ships**

C1 changes `_feature.emit(None, summary)` to `_feature.emit(final_acc, summary, ctx)`. For Pattern A plugins, `final_acc = {}` is a no-op. For `BankruptcySimulation` (Pattern B), the implementation team must confirm that `BankruptcySimulation.emit()` does not use `final_acc` as its source of accumulated data (which would currently be `None` → now `{}`). If it does, behavior changes. If it reads only from `summary["_bankruptcy_rows"]`, the change is safe. This must be an explicit C1 acceptance criterion: "Verify BankruptcySimulation.emit() behavior is identical for final_acc=None vs final_acc={} by inspecting the implementation."

### Bounded open items (for implementation team, not blockers)

- **SQ2 (PipelineContext completeness)**: The 6 declared fields cover the identified dependencies. If Phase C5 implementation discovers additional required fields, the `PipelineContext` dataclass must be extended and C1/C2/C3/C4 pseudocode must be updated. Implement with an explicit "PipelineContext extension protocol" note in C5 acceptance criteria.
- **Q3 (DECLARED_DEPS semantic-null check)**: The current key-presence check is specified. Whether `summary["_bcm_bonus_feature"] = None` should also raise is deferred as Q3. The implementation team should document the convention: dep-writing plugins guarantee non-None values for all declared outputs, or explicitly document which deps are nullable.
- **EC-NEW-1 (bonus_chain_lengths absent vs empty)**: The "should not occur" claim for missing accumulator key should be a defensive check in `_build_mechanism_registry()` — treat absent key same as empty list for Tier 2 detection.

### Readiness for implementation phase

APPROVED for implementation via impl-* 4-agent team per `memory/feedback_impl_team_required.md`.

The implementation team (impl-implementer, impl-tester, impl-verifier, impl-critic) should begin with Phase C1 and treat the two minor revisions (MR-v2-1, MR-v2-2) as C1 acceptance criteria to be verified before proceeding to Phase C2. The §15.5 acceptance table provides sufficient specificity for the impl-tester to write tests for each phase.

The following Wave 1 + Wave 2 evidence is available and sufficient for implementation:
- `01_pipeline_map.md`: exact PIA line numbers for all blocks being carved
- `02_taxonomy.md`: machine classification for acceptance testing
- `03_coupling_audit.md`: blast-radius analysis for each phase
- `04_architecture_proposal_v2.md`: full spec with pseudocode for all new components
- `06_validation.md`: 7 concrete cases including live report data for M275

---

## Appendix: Summary Resolution Table

| Item | v1 Status | v2 Status |
|---|---|---|
| TC1 Registry ordering contradiction | Unresolved | Resolved |
| TC2 F1-before-emit unenforced | Unresolved | Resolved |
| TC3 DECLARED_DEPS silent mis-attribution | Unresolved | Partially resolved (key-presence check; null case open) |
| TC4 Universal 5×253 rebuild burden | Partially addressed | Partially resolved (§11.7 workflow added) |
| TC5 _mechanism_registry cleanup timing | Partial | Resolved (cleanup post all-emit; PipelineContext provides second ref) |
| Q1 hash gap undocumented | Not addressed | Resolved (§8.2 explicit) |
| Q2 jackpot-scatter ordering | Partial | Resolved (§5.2 scatter-first sequence) |
| Q3 topo-sort edge cases | Not addressed | Resolved (Kahn's + error types) |
| Q4 _st_label before emit | Partial | Resolved (Phase B sentinel) |
| Q5 backward compat old inline reports | Not addressed | Partially resolved (REGISTERED_FALLBACK_RULES deferred with rationale) |
| Q6 extract() memory characterization | Partial | Unresolved (not addressed in v2) |
| Q7 operator batch-rebuild workflow | Partial | Resolved (§11.7) |
| Q8 sidecar race conditions | Adequately addressed | Resolved (confirmed) |
| Q9 upstream API change resilience | Partial | Unresolved (same as v1) |
| Q10 zero-code vs multiplier-wilds | Partial | Resolved (§13.2 table) |
| Q11 F5→F6 spin_type_to_feature | Not addressed | Resolved (§7.1, §7.2 C5/C6 DECLARED_DEPS) |
| Q12 frontend Schema bump | Partial | Partially resolved (deferred §14.8, app.js grep TBD) |
| Q13 Gap #6 formula | Adequately addressed | Resolved (confirmed by validator) |
| Q14 M273 benefit claim | Adequately addressed | Resolved (§11.4 precise framing) |
| Q15 import-site enumeration | Not addressed | Resolved (§15.5 table) |
| MR C1-1 dual-path extract() | Unresolved | Resolved |
| MR C1-2 BankruptcySimulation arg semantics | Unresolved | Partially resolved (new MR-v2-2) |
| MR C2-2 50 machines behavior change | Unresolved | Resolved |
| MR C2-3 payout_groups two-field check | Unresolved | Resolved |
| EC5 portrait write error handling | Not addressed | Resolved (§5.4) |
| EC6 effective_bet_for_rtp availability | Not addressed | Resolved (PipelineContext) |
| EC7 total_spins availability | Not addressed | Resolved (PipelineContext) |
| NP1 error exception surfacing path | — | Not addressed (new gap) |
| NP5 upstream_feature writer-side dep contract | — | Partially addressed |
