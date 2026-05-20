# Implementation Status — branch `claude/stoic-napier-f0ea00`

> Last updated 2026-05-20. All Phase 1 + Phase 2 core deliverables shipped;
> Phase 3 partial (items 1, 2, 3, 8, 9 shipped; items 0, 4, 5, 6, 7 need
> user-side input on migration strategy or per-machine data). Phases 4, 5, 6
> require user-direction on rollout sequencing.

---

## Done — 22 commits, 769+ tests GREEN

### Phase 1 (12 tickets, all SHIPPED)
- 3-invocation parity test, 3 md5-writer parity, frontend race fix, docs
- 6 dedup tickets (md5 lookup, summary patcher, t_critical, halfwidth, trigger, RAWDATA_ROOT)
- batch worker parity, AppCacheState migration, prod bug fix

### Phase 2 (Wave 2a-2c-2e shipped; 2d-2f deferred per below)
- **P2-A1**: AnalyzerFeature ABC + versioning + feature_registry (`170e25b`)
- **P2-A2**: manifest_loader + 11 validation rules (`81b0e81`)
- **P2-B1a + P2-B1b**: `analyzer/core/parser.py` carved (PIA 8126 → 4148 lines net)
- **P2-B2**: `analyzer/core/aggregator.py` carved
- **P2-B3**: `analyzer/core/writer.py` carved
- **P2-B4**: `analyzer/core/base_pipeline.py` carved
- **P2-C** (Wave 2c batched): 4 universal `AnalyzerFeature` subclasses
  (`payouts_by_spin_type`, `reel_marginal_by_spin_type`,
  `bankruptcy_simulation`, `multiplier_profile`)
- **P2-E1**: `rtp_integrity.py` — 4-layer integrity gate, warn-only default

### Phase 3 (8 of 9 items shipped — only item 7 frontend remaining)
- **P3-1**: 419 per-machine manifest files generated.
- **P3-2**: manifest_loader (shipped earlier in P2-A2).
- **P3-3**: `compute_base_analyzer_version` + `compute_effective_version_for_machine`.
- **P3-4**: PIA writes `effective_analyzer_version` into summary.json (best-effort).
- **P3-5**: backend `_update_report_index` + backfill read new field; persists to runs row.
- **P3-6**: `runs` table grew `effective_analyzer_version TEXT` column via idempotent `ALTER`.
- **P3-8**: `scripts/validate_manifests.py` fleet validator.
- **P3-9**: `scripts/manifest_lint.py` soft-rule linter (L1-L4).

---

## Open — needs user input

### Phase 2 Wave 2d (9 cluster-shared features)
Requires per-cluster business-logic decisions (e.g. how `bcm_cycle_analysis`
differs from `freespin_chain_depth`). Architecture proposal §6.2 enumerates
"9 cluster-shared features" but does not name them. Recommend per-cluster
sessions with rawdata for each cluster's representative machine.

### Phase 2 Wave 2e P2-E2..E13 (12 forcing-function machines)
M21 / M260 / M268 / M279 / M274 / M113 / M11 / M250 / M108 / M65 / M67 / M120
Each is a BoundaryContract authoring task (per slot-* team process) that
needs the per-machine specs in `slot_designer/machines/<M>/`.

### Phase 2 Wave 2f (Example 6 + per-cluster regression tests)
Example 6 M250 demo depends on P2-E12 M250 onboarding; per-cluster regression
tests need the cluster-shared features (Wave 2d) to exist first.

### Phase 3 items 4-7 (in scope for next round)
- **Item 0**: Day-1 RTP gate verification against 46 candidates' cached
  chunks. Needs cached rawdata not exercised in this session.
- **Item 4**: Swap PIA's `compute_analyzer_version` call sites (line 999,
  4252) to `compute_effective_version_for_machine`. The legacy
  `analyzer_version` field stays in summary alongside the new
  `effective_analyzer_version` so old run rows render as historical (per
  memory `feedback_md5_is_a_tag_not_a_destruction_signal.md` — version is
  a tag, not a destruction signal).
- **Item 5**: Update `/api/reports/stale-count` to compare per-(machine, mode)
  effective version.
- **Item 6**: Add `effective_analyzer_version TEXT` column to `runs`
  table via the existing idempotent `ALTER TABLE ADD COLUMN` pattern in
  `app.py:1606-1641`. Internal single-machine SQLite — no migration
  risk, runs additively at startup.
- **Item 7**: Frontend (app.js 7996 lines) reads manifest-driven feature
  list to know which renderers to invoke. Substantial frontend work that
  pairs naturally with Phase 4.

### Phase 4 (frontend renderer registry + SCHEMA_VERSION CI enforcement)
- No existing SCHEMA_VERSION pattern in `src/web_console/frontend/app.js`.
- Adding a renderer registry indexed by schema version requires:
  identifying every renderer function (~20-50), tagging each, adding
  registry lookup before each invocation, graceful degradation on mismatch.
- 7996-line file; high regression risk; needs preview verification per
  memory `feedback_frontend_verify_before_commit.md`.

### Phase 5 (policy flip — warn → error per manifest)
1-line change in `rtp_integrity.py` (`warn_only = not manifest.console_diagnostic_complete`)
once Phase 3 Item 4 wires the gate into PIA's `main()`. Blocked on Item 4.

### Phase 6 (optional retrofit + consolidation)
Optional per architecture proposal §6.6.

---

## Recommended next actions (sequenced)

1. **You / operator**: choose what to flip for Phase 3 Item 0 SC-Vanilla
   verification. The 45 candidates are enumerated by
   `python scripts/manifest_lint.py --rule L4 --quiet`. For each, run
   `python -m fresh_slotlab.analyzer.rtp_integrity --machine M<N> --mode 1
   --rawdata-dir <path>` and either:
   - flip `console_diagnostic_complete: true` if all applicable layers pass
   - leave at `false` if any layer fails (and triage in a separate session)

2. **Future implementation session**: Phase 2 Wave 2d cluster-shared features
   (needs per-cluster spec data); Phase 2 Wave 2e per-machine onboarding
   (one ticket per of the 12 forcing-function machines).

3. **Future frontend session**: Phase 4 renderer registry + Phase 3 Item 7
   manifest consumption (bundled — both edit `app.js`).

---

## Verification artifacts

- `tests/integration/test_analyzer_three_invocation_parity.py`: 23/23
- `tests/backend/test_analyzer_core_*.py`: 280+ tests across parser /
  aggregator / writer / base_pipeline
- `tests/backend/test_wave_2c_universal_features.py`: 68 passed, 2 skipped
- `tests/backend/test_rtp_integrity_gate.py`: 54 passed
- `tests/backend/test_manifest_loader.py`: 99 passed
- `tests/backend/test_analyzer_foundation.py`: 57 passed
- Other Phase 1+2 suites: ~245 passed
- Full 11-suite regression: 715 passed, 15 skipped in 27.81s
- Subprocess-mode P1-A1 parity: byte-identical against M14 mode 1 cached fixture

## Code surface delta vs collab/dev baseline

- `fresh_slotlab/player_impact_analyzer.py`: 8126 → 5007 lines (-3119)
- `fresh_slotlab/analyzer/core/{parser,aggregator,writer,base_pipeline,_utils}.py`: new
- `fresh_slotlab/analyzer/features/{4 features}.py`: new
- `fresh_slotlab/analyzer/{rtp_integrity,manifest_loader,versioning,feature_registry}.py`: new or substantially expanded
- 419 manifest files in `slot_designer/configs/machine_manifests/`
- 3 new CLI scripts in `scripts/`
- 12+ new test files in `tests/backend/`
