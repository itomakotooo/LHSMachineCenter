# 00 — Brief: Analyzer Unbundle (M275 driven)

> **Date**: 2026-05-25
> **Coordinator**: main session (claude)
> **Topic dir**: `session_artifacts/_arch_analyzer_unbundle/`
> **Trigger**: per `docs/ARCH_TEAM_PROCESS.md` §1 — touches fleet-shared (`fresh_slotlab/analyzer/`), changes hash composition, restructures schema fields. All three triggers fire.

---

## §1 Task statement (verbatim user goal)

> "我希望你这里在分析完 rawdata 以后直接可以建立正确的解析器，也不需要增加或者修改任何代码"
>
> "以 M275 为例子做正确的事就行。最好直接把现在的 analyzer 拆了。"

Translated: when the planner team adds a new machine that's purely a recombination of existing mechanics (with parameter changes — multiplier / BCM cycle / jackpot count / etc.), the analyzer side must produce a correct report **without any code change** — only a manifest + raw data.

Use M275 as the driving case study. **Restructure the current monolithic analyzer into a true plugin system** as the means.

---

## §2 Scope

### In scope
- `fresh_slotlab/player_impact_analyzer.py` — the ~5500-line monolith. Specifically the `main()` body's inline aggregation that currently produces:
  - `payouts_by_spin_type`, `payout_ids_top20`, `payout_groups_top20`
  - `reel_marginal_by_spin_type`
  - `multiplier_profile`, `bankruptcy_simulation`
  - `machine_mechanics` (jackpot / free_spin / lock_* / dollar_pick auto-detect)
  - `collect_mechanic` (BCM cycle + correction + clamp warning)
  - `bonus_chain_dynamics`
  - `upstream_feature_breakdown`
- `fresh_slotlab/analyzer/features/*.py` — current 4 Pattern-A scaffolds (`payouts_by_spin_type` / `reel_marginal_by_spin_type` / `bankruptcy_simulation` / `multiplier_profile`)
- `fresh_slotlab/analyzer/core/*.py` — parser / aggregator / writer / base_pipeline / _utils
- `fresh_slotlab/analyzer/feature_registry.py` + `versioning.py`
- `fresh_slotlab/analyzer/manifest_loader.py`
- `slot_designer/configs/machine_manifests/*.json` (419 files)
- `configs/machines.json`
- `configs/machine_round_win_rules.json`
- Auto-inference modules: `round_classification.py` (BCM cycle, payid attribution, trigger session), `round_win.py` (RoundWinRule), `post_inference.py`, `trigger_sessions.py`
- Frontend renderers that read these summary keys (read-only audit; no edits in this team)

### Out of scope
- Sampling pipeline (`batch_dev_sampler.py`, backend `_batch_gen_worker.py`)
- Console backend / frontend code editing
- Slot designer onboarding pipeline (`slot_designer/scripts/*`, except as it consumes manifest output)
- Spec / engine generation
- Test code (impl-tester writes tests later, in implementation phase)

---

## §3 Driving case (M275)

M275 is a **Case-B machine** (recombination of known mechanics, no new ones):
- 3×3 grid, 5 paylines
- SpinType set: 140 (paid) + 126 (free)
- BCM cycle 1 → 1000 (Tier-1 hard family: M250/M260/M264/M268/M279/M11)
- Multiplier wilds: wild2x / wild5x / wild10x (raw shows; inference paused fleet-wide per memory)
- Jackpot pay_ids: 27502 / 27503 / 27504 (single hits 10k–100k credits)
- Scatter trigger pay_id: 666 (line_id=-1, win=0, fires freespin)
- Freespin: fixed 10 spins, no retrigger, ExtraRatio=100
- Collect features observed in raw: NormalCollectionSpin / NewFreespin / BuffCollectionMap

### What the analyzer gets right today (auto)
1. BCM cycle length 1000 (`collect_mechanic.bonus_cycle_correction.detected_cycle_length`)
2. avg_spins_between_collects 5.57; completed_cycles_total 64
3. clamp_warning correctly identifies 80% pending-share → explains 89% RTP vs ~95% target as sampling truncation
4. 3 upstream features identified + chain-parent inference (`NewFreespin [via BCM cycle]` etc.)
5. payout_id 27502-27504 / 666 all in payout_ids_top20 (correct attribution)
6. paylines_top20, payouts_by_spin_type (ST126_free / ST140_paid) all populated
7. Symbol set includes wild2x/wild5x/wild10x in symbols_top20
8. RTP integrity L1/L2/L3 PASS; server_total_win == our_total_win

### Where it fails today — the 8 gaps
| # | Symptom | Truth | Failure mode |
|---|---|---|---|
| 1 | `machine_mechanics.jackpot.applicable: false` | pid 27502/27503/27504 sum 4.39M ≈ 5.5% RTP | Independent detection module not cross-referenced with payout_ids panel |
| 2 | `machine_mechanics.free_spin.applicable: false` | 9090 freespin rounds; `bonus_chain_dynamics` already identifies them | Same — independent module no link |
| 3 | pid 666 classified `cat=paid dom_st=140` | Scatter trigger marker (hit 829, win=0, line_id=-1) | Trigger-marker concept missing from pay_id panel |
| 4 | wild2x/wild5x/wild10x not interpreted as multiplier values | Need ×2 / ×5 / ×10 semantics + RTP contribution | Multiplier inference paused fleet-wide (2026-04), needs restart |
| 5 | `payout_groups_top20` shows group 0 = 80% RTP | M275 PayoutGroupId all 0 (= no grouping), this row is noise | Doesn't distinguish "all zeros" from "real group 0" |
| 6 | `bonus_cycle_correction.estimated_correction_pp: 0.0` | clamp_warning says 80% pending → should estimate correction | Correction formula not implemented |
| 7 | `payouts_by_spin_type` missing shape / cols / paylines / notes | User-stated requirement | Universal field augmentation |
| 8 | `payout_ids_top20` same missing fields | Same | Universal field augmentation |

### Cross-cutting design defect (root cause)
Several panels (`collect_mechanic`, `upstream_feature_breakdown`, `bonus_chain_dynamics`) already correctly identify freespin + jackpot mechanics. But independent panels (`machine_mechanics.jackpot`, `machine_mechanics.free_spin`) report "not applicable". **No single source of truth for "what mechanics does this machine have"** — each panel reaches its own conclusion from raw, inconsistently.

Also: auto-inferred parameters (cycle length 1000, 3 features identified, freespin length 10) are **recomputed every run, never persisted** — no "machine mechanism portrait" surface that an operator can look at.

---

## §4 Constraints

### Hard invariants (must not break)
- **393 machines × N modes existing cached reports** must remain readable. Schema bumps must include fallback rendering rules (`REGISTERED_FALLBACK_RULES`) per `04_v5 §5.4`.
- **RTP integrity invariant**: `summary.rtp.our_total_win == server_total_win == sum(payout_id_win)` (Layer 1/2). Any plugin restructuring must preserve this fleet-wide.
- **Hash composition algorithm** per `versioning.py:202` (`compute_effective_analyzer_version`) is the contract. Any change to composition is itself a contract change; if changed, design must justify + provide migration.
- **Manifest = sole per-machine input** (the goal). No new per-machine config file types unless absolutely required.
- **PIA legacy `analyzer_version` field** stays for backward-compat of older summaries; new `effective_analyzer_version` is the forward field.

### Soft constraints
- Minimum delta to existing files where the change is mechanical (carve into plugin) vs. behavior change.
- Preserve dual-path imports (package mode + script-mode) per `feedback_subprocess_import_suicide_and_module_globals.md`.
- No module-top I/O / side effects in plugin files.

### Memory invariants this design must honor
- `feedback_arch_team_process.md` — this team is the right vehicle
- `feedback_impl_team_required.md` — implementation phase will use impl-* team
- `feedback_md5_is_a_tag_not_a_destruction_signal.md` — hash is for classification not deletion
- `feedback_invariant_with_fallback_hides_drift.md` — fallback buckets must surface as alerts
- `feedback_subprocess_import_suicide_and_module_globals.md` — no import-time I/O
- `feedback_md5_granularity_and_stamping.md` — per-mode hash, delegate paths must re-stamp
- `feedback_perf_claim_needs_e2e_event_stream.md` — claims need real subprocess e2e
- `feedback_no_parallel_panel_impl.md` — reuse sibling renderers
- `feedback_prefer_complex_better.md` — choose the structurally-better option

---

## §5 Goals (success criteria for the proposal)

The proposal must answer:

1. **Plugin contract**: what does Pattern-B look like exactly? extract / reduce / emit signatures + how parser_state surfaces all raw fields a plugin might need (PayoutByPayline records, StopSymbolsByCol grid, ReMarks, FeatureWin map, etc.).
2. **Mechanism registry**: how do we get one source of truth for "M275 has jackpot, has freespin, has BCM, has scatter trigger" — replacing the contradicting parallel detections (gaps #1, #2, #3).
3. **Auto-inference persistence**: where does the inferred mechanism portrait land so it's visible / auditable (gap-level: clamp correction formula, BCM cycle peak, jackpot pid set, scatter marker pid set, multiplier wild values).
4. **PIA inline carve plan**: which inline sections move into which plugin(s), in what order, with what backward-compat behavior during transition.
5. **Hash composition**: does `effective_analyzer_version` still work end-to-end after carve? Are there new dimensions (per-machine inference config hash) to include?
6. **Manifest schema evolution**: do manifests need new fields (e.g. for per-machine BCM cycle override when sample-too-short to auto-detect)? Or is everything inferred + persisted side-by-side?
7. **8 gaps closure**: for each of the 8 gaps, which plugin owns it post-carve, and what's the fix sketch?
8. **Migration path**: how do we ship this without invalidating 393×N reports at once? Phased? Big-bang? Feature flag?
9. **M275 validation**: walk M275 mode 1 through the proposed pipeline end-to-end; show all 8 gaps closed; show RTP integrity still PASSes; show no other machine's effective_version changes spuriously.
10. **"Zero-code new machine" property**: precise statement of when this property holds (Case-A always; Case-B after this work — list which mechanism types are auto-handled; Case-C still requires plugin work — list residual machines / types).

---

## §6 Out of scope for this proposal (deferred / explicit)

- **Multiplier wild auto-inference resume** — gap #4 needs investigation of the 2 paused bugs first; this proposal may flag it as "requires upstream investigation, not blocker for plugin carve."
- **Frontend renderer registry / SCHEMA_VERSION CI** — Phase 4 of original arch proposal (`04_v5 §6.6`); optional, may be deferred.
- **PIA legacy `analyzer_version` field deprecation** — keep for backward-compat.
- **Test code** — impl-tester writes during impl phase.

---

## §7 Process this team will run

Per `docs/ARCH_TEAM_PROCESS.md`:

- **Wave 1 (parallel, background)**:
  - `arch-mapper` → `01_pipeline_map.md` (data/control flow through PIA main → core → features → summary; identify exactly which inline aggregation blocks need to move)
  - `arch-taxonomist` → `02_taxonomy.md` (419 machines classified by mechanism — vanilla / BCM / multi-wild / jackpot / scatter / etc.; M275 placed; other Case-B machines enumerated)
  - `arch-coupling-auditor` → `03_coupling_audit.md` (every fleet-shared symbol's blast radius; specifically what breaks if `payouts_by_spin_type.py` Pattern A → B; hash composition impact map)
- **Wave 2**: `arch-designer` → `04_architecture_proposal.md`
- **Wave 3 (parallel)**: `arch-critic` → `05_critique.md` + `arch-validator` → `06_validation.md`
- **Coordinator**: writes `07_decision.md` summarizing for user (plain language, no jargon).

Loop if critic/validator says APPROVE-WITH-REVISIONS or REJECT.

---

## §8 Reference artifacts to read

Agents should read these (relative paths from repo root):

- `docs/ARCH_TEAM_PROCESS.md` — this team's protocol
- `docs/PROD_VS_VIRTUAL_CONTRACT.md` — analyzer/console boundary
- `session_artifacts/_arch/04_architecture_proposal_v5.md` — original plugin design spec (authoritative for hash algorithm and plugin Protocol shape)
- `session_artifacts/_arch/09_architecture_as_built.md` — what shipped vs designed; Tier-1/2/3 hard cases
- `session_artifacts/_impl/STATUS.md` — current branch state, fleet smoke results (59 fail L2)
- `slot_designer/DESIGN_PHILOSOPHY.md` + `slot_designer/ARCHITECTURE.md` — design constraints for slot machines
- `memory/feedback_arch_team_process.md`, `memory/feedback_impl_team_required.md`, `memory/feedback_invariant_with_fallback_hides_drift.md`, `memory/project_paytable_inference_paused.md`

Live state to probe (read-only):

- `fresh_slotlab/player_impact_analyzer.py` lines 1046 (main start) — 5500 (end). Pay special attention to lines 3180-3500 (spin_type + payout aggregation), 4260-4290 (version stamping), 4427-4436 (summary assembly).
- `fresh_slotlab/analyzer/features/*.py` (4 Pattern-A scaffolds)
- `fresh_slotlab/analyzer/core/{parser,aggregator,writer,base_pipeline,_utils}.py`
- `fresh_slotlab/analyzer/{versioning,feature_registry,manifest_loader,rtp_integrity}.py`
- `fresh_slotlab/{round_classification,round_win,trigger_sessions,post_inference}.py`
- `rawdata/M275/mode_1/chunk_000{1,2}.json` (real raw, 25MB each)
- `reports/M275/mode_1/versions/rv_20260520T145625Z_3f69de76/player_impact_summary.json` (current report; 8 gaps live here)
- `slot_designer/configs/machine_manifests/M275.json`
- 5-10 sibling machine manifests for taxonomy: M14 (simple), M272 (BCM), M279 (BCM+jackpot), M37 (classic Seven), M250 (BCM+correction), M11 (BCM+freespin)
