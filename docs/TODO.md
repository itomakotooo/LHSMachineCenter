# TODO

Executable next steps for the current phase. Audited & rewritten 2026-06-06.

Context: the report-production orchestrator `fresh_slotlab/player_impact_analyzer.py`
was **deleted** and is being rebuilt SpinType-native. Core primitives survive under
`fresh_slotlab/analyzer/core/*` + `round_win.py` / `round_classification.py` /
`trigger_sessions.py` / `sampler.py` / `machine_md5.py` / `versioning.py` /
`rtp_integrity.py` / `st_inventory.py` / `machine_spec.py` / `features/*`.
Report **generation** is OFFLINE (HTTP 503 in `_run_generate_report`); report
**viewing** still works. The virtual (`slot_designer/`) framework, the
byte-identical/golden corpus, and the team-process mandate were all removed.
Read `MACHINE_ONBOARDING.md` + memory `project_playtype_rearch.md` first.

## P0 — rebuild the SpinType-native report engine (blocks everything else)

- [ ] **Build the new SpinType-native orchestrator.** Replace the deleted
      `player_impact_analyzer.py` with an integrated per-SpinType event parser
      (start with M15 TopDollar) that reuses the surviving core (`core/parser`,
      `core/aggregator`, `core/writer`, `core/base_pipeline`, `round_win`,
      `round_classification`, `trigger_sessions`, the `features/*` plugins, the
      topo-sort emit loop). Must produce the **preserved** output schema
      (`player_impact_summary.json` + `player_impact_report.md`) so the existing
      read path / console panels keep working unchanged. Gate it: real-trace
      verification + `rtp_integrity` invariant + the per-machine digest harness
      (below). SpinType is the unit; no invented play-type layer.

- [ ] **Wire `derive_analyses()` into the live path.** `machine_spec.derive_analyses()`
      derives the analysis set from `spin_types` and is unit-tested against M15, but
      it is NOT consumed yet (its own docstring: "Wiring versioning/PIA to consume it
      is the next step"). The live `versioning.compute_effective_version_for_machine`
      still reads the hand-listed `manifest["analyzer_features"]` and points
      `manifests_root` at the OLD `slot_designer/configs/machine_manifests`. Switch
      the orchestrator + versioning to the SpinType-native manifest +
      `derive_analyses()`, retiring the hand-listed `analyzer_features` path.

- [ ] **Auto-discover feature plugins** so adding one does not flip the fleet
      `base_hash` or require editing a hardcoded import list.
      `versioning.compute_effective_version_for_machine` currently hardcodes ~10
      `import fresh_slotlab.analyzer.features.<name>` lines (versioning.py ~318-342)
      to force registration before reading `ALL_FEATURES`; `feature_registry.register()`
      already dedups by `FEATURE_ID`. Replace the manual import block with package
      auto-discovery (walk `analyzer/features/`), keeping the R-4 base-exclusion
      (registered plugins stay OUT of `_CLOSURE_FILES`) so a new plugin invalidates
      only the machines that use it.

- [ ] **Re-enable report generation.** Two coupled call sites are intentionally
      offline pending the rebuild:
      1. `_run_generate_report` in `src/web_console/backend/app.py` (~line 9317)
         raises HTTP 503; the original generation body is retained but unreachable.
      2. `RunManager.start_run` (~line 6375) aborts with 500 "analyzer script not
         found" because `ANALYZER = .../player_impact_analyzer.py` no longer exists,
         so the live-sampling path is dead too. The `_batch_gen_worker.py` subprocess
         path also still targets the removed module.
      Repoint all three at the new orchestrator once it lands.

- [ ] **Per-machine digest regression harness.** Replaces the deleted fleet golden
      corpus. Each confirmed machine gets a digest baseline (step 8 of
      MACHINE_ONBOARDING.md); the harness re-derives and diffs per-machine instead
      of byte-comparing a fleet corpus. Does not exist yet (`scripts/` has no
      `*digest*`). Build alongside the orchestrator so the M15 rebuild is gated.

## P1 — SpinType-native onboarding plumbing

- [ ] **Validated-ST registry.** `st_inventory.py` extracts each ST's real field
      signature (Phase 0a); MACHINE_ONBOARDING notes "same number ≠ same semantics".
      A registry of validated-ST parsers (keyed by field signature, not ST number)
      so a confirmed parser can be safely reused across machines does not exist yet —
      build it as machines get confirmed.

- [ ] **Convert + relocate the 420 legacy manifests.**
      `slot_designer/configs/machine_manifests/*.json` (420 files, OLD
      `analyzer_features` / `round_win_rules` / `console_diagnostic_complete` schema)
      → `configs/machine_manifests/` in the LOCKED SpinType-native schema
      (`spin_types{role,play}` + `derive_analyses()` + `validation` +
      `out_of_engine_mechanics`). Only `M15.json` exists in the new location/schema
      today. Per onboarding, freshly-converted manifests are `auto` until the 5-gate
      confirmation (incl. user sign-off); do not stamp `confirmed` without it. Once
      done, drop the legacy dir and the old `manifest_loader.py` schema.

## P0/P1 — sampling (pre-existing, still open)

- [ ] **Fuzzy live-sampling CI-stop latent bug** (live `start_run` path NOT
      hardened). The from-cache / generate-report paths pass `target_halfwidth_pp =
      0.001` so `max_chunks` is the sole stop gate (app.py ~9376 / ~9657), but
      `start_run` still feeds the analyzer `effective_halfwidth_pp = 999.0` for the
      fuzzy tier (app.py ~6400), which the CI-stop branch satisfies after ~2 chunks
      and can terminate a live run early. Make `start_run` use `0.001` too + add a
      regression test. (Lower priority now that the sampling UI defaults to count
      mode, but the backend fuzzy path still exists. Re-validate once the engine /
      live path is back online.)

- [ ] **`sampling_source` field on run summaries.** Not implemented. Stamp which
      endpoint fed each report so throughput/RTP can be attributed retrospectively.
      The default endpoint is now the INTERNAL server
      (`192.168.10.21:15060/MachineTest/MultiRobotTestSpinVariant`), so the older
      "switch off the external test endpoint" action is effectively done; what
      remains is recording the source + re-benchmarking concurrency against the
      internal server (the external-direct 8×8 throughput regimes in
      `reference_sampling_api.md` may no longer apply).

- [ ] **Multi-server live test.** `configs/servers.json` CRUD + scan + MD5-diff +
      per-run `server_id` resolution infra is in place; waiting on user-provided
      test/prod addresses to exercise it end-to-end.

## P1 — product (still genuinely open)

- [ ] Auth layer for the web console (local admin token; internal single-box
      deploy per `project_internal_deploy_intent.md`, so keep it minimal).
- [ ] Operation audit log: who started/stopped runs / triggered cache cleanup,
      timestamps, payload summary.
- [ ] Report comparison view: version-vs-version and machine-vs-machine for key
      player-impact metrics.
- [ ] Runtime health dashboard: queue depth, API failure/timeout rate, endpoint
      latency percentiles.

## P2 — paused / deferred

- [ ] **Paytable multiplier inference — PAUSED.** Shape inference shipped
      (2026-04-19); multipliers have 2 unfixed bugs (multi-fire double-count, wild
      stacking). Do NOT propose resuming unless the user raises it
      (`project_paytable_inference_paused.md`).
- [ ] Multi-machine batch test-campaign scheduling/tracking.
- [ ] Automatic report-baseline alerting on threshold deviation.
- [ ] Deployment packaging beyond the existing single-box Windows flow
      (`scripts/deploy/` Task Scheduler XML + run_smoke + rollback + README,
      `scripts/start_console.ps1`).
- [ ] CI integration (deferred; baseline is local `scripts/lint.ps1` +
      `scripts/test.ps1 -E2E`).

## Work Mode

- Report generation stays deterministic and script-driven; LLM usage confined to
  the interpretation/comparison layer.
- Never persist raw per-spin full data as long-term report assets.
- Gates-first: `base_hash` / per-machine digest / real rawdata trace are the
  objective gates. arch-*/impl-* teams are opt-in (the standalone process docs were
  removed); use a team only for changes that truly touch core/schema/hash.
- Adding a feature plugin or a machine manifest must NOT flip the fleet `base_hash`.
