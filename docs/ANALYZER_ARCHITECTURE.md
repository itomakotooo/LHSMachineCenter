# Analyzer Architecture & Rebuild Spec

Authoritative spec for the analyzer's **settled foundation** + the in-progress
**rebuild** (orchestrator deleted 2026-06-05, being rebuilt SpinType-native).

**Implementation agents MUST follow this doc.** Any deviation needs human sign-off.
Every factual path/claim here was verified against the tree on 2026-06-05; re-verify
before editing. Do NOT invent structure not described here.

---

## 1. The model — LOCKED, do not re-litigate

- The unit is the **SpinType** — a protocol event token with a **role**:
  `paid_spin` / `player_choice` / `settlement` / `state`. NOT "a spin".
- A machine = the set of SpinTypes it emits. A 玩法/feature = a group of related
  SpinTypes. Analyses are **DERIVED from `spin_types`**, never hand-listed.
- Source of truth: `fresh_slotlab/analyzer/machine_spec.py` (schema + `derive_analyses`)
  and `docs/MACHINE_ONBOARDING.md`. M15 ground truth: `session_artifacts/_arch_playtype/02_traces.md`.
- **Agents must not invent domain layers** (the old "play-type/PT" layer was wrong and
  is gone). If the rawdata doesn't have it, it doesn't exist.

---

## 2. Current reality — the analyzer is 5 layers (exact files)

| Layer | Modules | Disposition |
|---|---|---|
| **L1 core math** | `fresh_slotlab/analyzer/core/{parser,aggregator,writer,base_pipeline}.py`; `fresh_slotlab/{round_win,round_classification,trigger_sessions,sampler,machine_md5,rawdata_index,chunk_index}.py`; `fresh_slotlab/analyzer/rtp_integrity.py` | **KEEP** (framework-agnostic: sample→parse→aggregate→write) |
| **L2 plugin framework + plugins** | `fresh_slotlab/analyzer/{feature_registry,topo_sort,pipeline_context,parse_state}.py`, `features/_base.py`; the plugins `features/*.py` | **KEEP**. The "general / non-ST analyses" the console shows (bankruptcy, multiplier_profile, hit_and_payout, volatility, streaks, …) ARE these plugins — reused, not rewritten. |
| **L3 resolution / manifest** | OLD: `manifest_loader.py` + 420 flat manifests in `slot_designer/configs/machine_manifests/` (`analyzer_features` list + `console_diagnostic_complete` + `spin_type_convention`) + `feature_registry.get_features_for_machine` (reads flat) + `mechanism_registry.py` (Tier-2 mechanism DETECTION) | **REPLACE** → `machine_spec` (SpinType-native manifest) + `derive_analyses()` + `validation:{auto,confirmed}`. Mechanism is **declared** in the manifest (role/play), not detected. |
| **L4 orchestrator** | OLD `fresh_slotlab/player_impact_analyzer.py` (DELETED) | **REBUILD** (slim): load manifest → derive_analyses → sample(L1) → parse(L1) → run plugins(L2) → write `player_impact_summary.json`(L1). |
| **L5 versioning / freshness** | `fresh_slotlab/analyzer/versioning.py` + `src/web_console/backend/effective_version_cache.py` (read flat `analyzer_features`); the 2 carves `analyzer/play_types/{bcm_cycle,wild_nudge}.py` (base-excluded, no per-machine hash) | **REWIRE** to read `derive_analyses`; converting the 2 carves to `AnalyzerFeature` plugins (per-machine hashing — closes the stale-report gap) is DEFERRED to BCM/wild-nudge machine onboarding (validate emit against real data). |

**Live coupling to the OLD system after the orchestrator deletion (narrow):**
- `versioning.py` (`compute_effective_version_for_machine`, line ~359 reads
  `manifest.get("analyzer_features")`) + `effective_version_cache.py` → drives console
  report-freshness.
- `src/web_console/backend/app.py` (~7923) reads `console_diagnostic_complete` → the
  "verified" UI badge. Also reads `rtp_integrity.py` + `manifest_loader.py`.
- `mechanism_registry` is entangled in `features/{bonus_chain_dynamics,machine_mechanics}.py`
  + `_base.py` + `pipeline_context.py` + `parse_state.py` — removing it requires those
  two plugins to take mechanism from the manifest (role/play) instead.
- **Report VIEWING (`/api/reports/...`) is independent** — reads `player_impact_summary.json`
  off disk, touches none of the above.

---

## 3. Target foundation (the settled structure)

**One path, no coexistence:**
```
configs/machine_manifests/<M>.json   (machine_spec, SpinType-native)
        │  load_manifest + derive_analyses(spin_types → analysis set)
        ▼
   L1 sample → parse → aggregate          L2 run derived plugins (per-ST + cross-cutting)
        └──────────────┬───────────────────────────┘
                       ▼
        player_impact_summary.json  (UNCHANGED schema — frontend contract)
```

- **Registry = registered machines only.** A machine is "registered" iff it has a
  `configs/machine_manifests/<M>.json` with `validation.status == confirmed`. Only such
  machines generate reports. **Only M15 is registered now.**
- **Non-registered machines → graceful "not registered, no report"** (HTTP-level clear
  message, not a crash). This is ACCEPTED — do not migrate the other 420 machines, do not
  keep the old path alive for them.
- The general/cross-cutting analyses are L2 plugins selected by `derive_analyses`
  (the `CROSS_CUTTING` set) — reused as-is.

---

## 4. Cleanup — files to DELETE (no coexistence left behind)

- `fresh_slotlab/analyzer/manifest_loader.py`
- `fresh_slotlab/analyzer/mechanism_registry.py` (after folding its 2 plugin consumers onto manifest role/play)
- `slot_designer/configs/machine_manifests/` (all 420 flat manifests) → `slot_designer/` then empty, remove it
- `console_diagnostic_complete` — every reader (`manifest_loader`, `rtp_integrity.py`, `app.py`) → `validation`
- `_unattributed_*` as a silent garbage bucket → make it an **alarm** (rtp_integrity already has fallback-share checks; surface, don't swallow)
- `fresh_slotlab/analyzer/_stub_features.py` (test-only, no longer needed)

---

## 5. Invariants / gates — EVERY phase must hold (gate before commit)

1. **Output schema preserved.** `player_impact_summary.json` keys the frontend depends on
   (top-level `rtp/sampling/player_impact/guideline_assessment/rtp_integrity_check/collect_mechanic/topdollar_choice`
   + the `player_impact.*` panels) are byte-stable. Verify by diffing a regenerated M15
   report against a kept-good one (schema/keys, not the numbers). See `docs/REPORT_SPEC.md`.
2. **base_hash honest + new-plugin registration must NOT edit a closure file.** Root fix:
   feature plugins auto-discovered (glob/registry), so adding a plugin no longer flips the
   fleet `base_hash`. (Today registration is a hardcoded import list — that's the bug.)
3. **Tests green**: `pytest tests/analyzer tests/backend` → 0 failed / 0 errors.
4. **M15 e2e**: M15 regenerates a report with the correct schema; `rtp_integrity` passes
   (`sum(payid)==summary`, `our==server`, fallback < threshold).
5. **No silent drift**: any `_unattributed_*` / `_other` share over threshold is an ALARM.
6. **Tests/regressions are VALUE-AGNOSTIC.** Assert `rtp_integrity` (L1 sum==our_total,
   L2 no fallback buckets, L3 anchors; `our==server` when server aggregate is available —
   note: NOT available on the from-cache path, `server_total_win` is null there) + schema
   keys + structural rule-effects (e.g. a preview ST contributes 0). **NEVER pin an RTP
   value OR a range** — the source machine's numbers change (re-sample / re-tune / upstream
   config), so any value-based assertion is a brittle false-alarm. The ST14-double-count
   regression is caught by L2 (the phantom win has no pay_id → fallback bucket), not by an
   RTP threshold.

---

## 6. Phased execution (each phase gated + committed; coordinator reviews every agent diff)

1. **L5 rewire (additive, reversible).** `versioning` / `effective_version_cache` resolve a
   machine's analyses via `machine_spec.derive_analyses` when a new-schema manifest exists,
   else fall back to flat (so nothing breaks yet). `app.py` "verified" reads `validation`
   with `console_diagnostic_complete` fallback. Gate: M15 effective_version stable; suite green.
2. **L4 rebuild — slim orchestrator.** New entry (e.g. `fresh_slotlab/analyzer/report_engine.py`):
   for a registered machine, load manifest → derive → sample(L1) → parse(L1) → plugins(L2) →
   write summary. Wire `app.py` `_run_generate_report` + the batch worker to it for registered
   machines; non-registered → clean "not registered". Gate: invariants 1+3+4 on M15.
3. **Mechanism de-couple.** `features/{bonus_chain_dynamics,machine_mechanics}` take mechanism
   from the manifest role/play (`machine_spec.derive_mechanism_flags`), with a `mechanism_registry`
   fallback when no SpinType-native manifest is present. **DEFERRED** (to BCM/wild-nudge machine
   onboarding): the carve→`AnalyzerFeature` conversion that gives `play_types/{bcm_cycle,wild_nudge}`
   per-machine hashing — its emit logic can only be validated against a real BCM/nudge machine, and
   M15 has neither (it would be empty-validated only). Gate: M15 schema + integrity stable
   (value-agnostic); suite green.
4. **Auto-discover plugins.** Replace the hardcoded feature import list with discovery so a new
   plugin doesn't touch a closure file. Gate: invariant 2 (adding a dummy plugin doesn't flip
   base_hash for un-declaring machines).
5. **Delete the old (§4) — coupling-aware (audited 2026-06-06; phases 1-4 are committed/verified).**
   This is NOT just file deletion: three live consumers still read the legacy flat manifest /
   mechanism_registry on M15's WORKING path and must be re-sourced from the SpinType-native
   manifest FIRST, then the old files deleted. **Key de-risking finding: no plugin reads
   `ctx.manifest` (the flat one)** — every feature reads `ctx.machine_spec_manifest` — so the flat
   manifest is load-bearing for only the 3 spots below. Pre-delete rewiring:
   - `report_engine.py:~467` loads M15's flat manifest into `_legacy_manifest`, which feeds:
     (a) `MechanismRegistry.build(manifest=_legacy_manifest)` (~L1808) — for new-manifest machines
     the 2 mechanism plugins already use `derive_mechanism_flags(machine_spec_manifest)`, so the
     built registry is UNUSED by M15; build from `{}` or skip for registered machines.
     (b) `PipelineContext(manifest=_legacy_manifest)` (~L1843) — VESTIGIAL (no plugin reads it);
     set `manifest={}`. (c) `check_rtp_integrity(manifest=_legacy_manifest)` (~L1914) — reads
     `console_diagnostic_complete` for Layer-2 gating; re-source from the new manifest's
     `rtp_integrity`/`validation` block (M15's new manifest already has an `rtp_integrity` key).
   - `app.py:~7912` builds the verified-badge map by ITERATING the flat-manifest dir; deleting the
     420 flat manifests empties that loop → M15 vanishes from the badge map. Rewire it to iterate
     `configs/machine_manifests/` (new dir). NOTE: the catalog "broken-machine ⚠" flag is a
     SEPARATE pre-existing roster check (`_machineBrokenIssues` → "缺 mode 2,5,7"), not this.
   - `rtp_integrity.py:~631` reads `manifest.console_diagnostic_complete` — same re-source.
   - `versioning.py:~308` flat fallback (legacy branch) + the `_CLOSURE_FILES` entries (~L125/126)
     for manifest_loader.py / mechanism_registry.py. Removing those 2 closure entries flips
     base_hash ONCE — this is an INTENTIONAL final-baseline re-flag (not the phase-4 churn it
     fixed); re-baseline + pin once, all reports re-flag stale a single time (acceptable).
   - Also fold report_engine's extract loop (~L987, currently iterates `ALL_FEATURES`) onto the
     per-machine `get_features_for_machine` set, computed BEFORE the chunk loop (it's currently
     resolved at ~L1850, after). Harmless today (emit already filters) but completes the model.
   Then delete: manifest_loader.py, mechanism_registry.py, 420 flat manifests, _stub_features.py,
   console_diagnostic_complete readers. Gate: M15 schema + integrity byte-stable (value-agnostic)
   BEFORE vs AFTER; full suite green; grep shows no live refs to deleted symbols; base_hash
   re-baselined exactly once + pinned. Given the M15-working-path surgery, run the impl-* team
   (cross-cutting deletion) with byte-identical M15 report diffs as the gate.

---

## 7. Post-rebuild API — the ONLY work future sessions do

1. **Add a machine** = write `configs/machine_manifests/<M>.json` (`spin_types{role,play}`,
   economy, trigger, `validation`) per `docs/MACHINE_ONBOARDING.md`, then it's registered.
2. **Add an ST parser/analysis** = add a per-ST handler / `AnalyzerFeature` plugin; wire it via
   role/play in `derive_analyses`.
Everything else — general analyses, versioning/freshness, report generation — is automatic.

---

## 8. Non-goals (do NOT do these)

- Do NOT migrate the 420 legacy machines or keep the old flat-manifest path alive for them.
- Do NOT make non-M15 machines generate reports (graceful "not registered" is the correct
  behavior).
- Do NOT change the `player_impact_summary.json` schema or the frontend (`panel_registry.js`).
- Do NOT invent domain layers; the SpinType model is locked (§1).
- Do NOT re-baseline scattered base_hash pins (they were removed on purpose; §5.2 is the fix).
