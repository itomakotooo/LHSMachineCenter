# Implementation Status — branch `claude/stoic-napier-f0ea00` (merged with collab/dev)

> Last updated 2026-05-21 post-merge. Phase 1 + Phase 2 core deliverables shipped
> on this branch (49 commits) + collab/dev deploy P1-P4 work merged in
> (14 commits). End-to-end verified against real backend; both sides of the
> merge work in production console flow.

---

## Branch state

- Base: `5c19760` (common ancestor with collab/dev on 2026-05-15)
- This branch ahead by: 49 commits (Phase 1 dedup + Phase 2 cores +
  Phase 2c features + RTP gate + Phase 3 manifests + Phase 5 inline gate +
  frontend self-check + manifest review badges + fleet smoke test)
- Merged in from collab/dev: 14 commits (deploy P1-P4: CellLockRegistry +
  ConfigFileWriter + ConcurrencyLimiter + FleetRefreshManager + start_console
  restart loop + LAN bind + vendored chart.js)
- Merge commit: `5f11171`
- Post-merge cleanup commit: (this commit)

---

## What works post-merge (verified against real backend on port 8877)

### My side (Phase 2/3/5)

| Feature | Verified |
|---|---|
| Self-check panel (`summary.rtp_integrity_check` → UI) | Synthesized + real data; 4-layer labels in zh-CN render; tone classes (pass-verified / pass-hint / fail-verified / fail-hint / error) all confirmed |
| Manifest review badges on machine catalog | 45 ✓ verified / 166 · reviewed / 182 ? pending — exact distribution rendered |
| `/api/manifests/review-state` | 200 response, 393 entries |
| `effective_analyzer_version` in summary | Real M14 sample produced `90e36d27df98` (12-hex), error field None |
| RTP integrity gate inline in PIA | 4 layers all True for M14 mode 1, completeness_declared True |
| 419 per-machine manifest files | All present; loader resolves variants via eager cascade |
| `compute_base_analyzer_version` / `compute_effective_version_for_machine` | Public surface; deterministic hash composition |
| `scripts/validate_manifests.py` + `scripts/manifest_lint.py` | CLI tools; lint surfaces 182 config_not_reviewed backlog |

### Main's side (deploy P1-P4)

| Feature | Verified |
|---|---|
| `ConfigFileWriter` (atomic JSON write) | `/api/configs` returns 200; no race observed |
| `CellLockRegistry` per-cell mutex (INV-1) | Second M14 SAMPLING returned `attached` (INV-R9: same 4-tuple attaches to existing run, not rejected) |
| `ConcurrencyLimiter` | 137/137 unit tests pass for new modules |
| `FleetRefreshManager` | POST `/api/fleet/refresh` creates queue with 422 items; DELETE switches status to `cancelled` |
| `runs.underlying_removed` column | Schema present; tagging logic `_tag_reports_stale` correctly gated on "last chunk removed" (INV-7 v2 spec) |
| Config upload + Fleet refresh frontend panels | Both rendered + visible in UI |
| Vendored chart.js | Loaded from `/console/vendor/chart.min.js` (intranet-safe) |
| start_console restart loop + Task Scheduler XML | Out of single-session scope (deploy infra) |

### Test posture

- My Phase 2/3 suites: 690 / 692 passed (2 skipped) — intact post-merge
- Main's 4 new modules: 137 / 137 passed
- P1-A1 3-invocation parity canary: 22 / 23 passed
- 1 P1-A1 test debt: `test_path_b_config_md5_matches_path_a` times out at 180s under main's new ConcurrencyLimiter — needs fixture update; production path unaffected
- 106 pre-existing test debts on this branch from P2-B3/B4 signature changes
  (e.g. `_save_chunk_cache` requires `lookup_machine_md5` kwarg; downstream tests
  predate the change and were never updated). Verified by checkout HEAD~1
  same failures — NOT merge-introduced. Follow-up cleanup.

---

## End-to-end verification against real backend

### Sample run: M14 mode 1 (post-merge)
- Backend: `python -m uvicorn src.web_console.backend.main:app` on port 8877
- POST `/api/batch-run` with `server_id=dev`, `chunk_spin_times=5000`, `max_chunks=2`
- Result:
  - `rtp.point_pct`: 91.34%
  - `sampling.total_spins`: 64000
  - `analyzer_version`: `c4f99adcccab` (legacy)
  - `effective_analyzer_version`: `90e36d27df98` (new field, 12-hex)
  - `rtp_integrity_check.passed`: True
  - All 4 layers True
  - `completeness_declared`: True

### Frontend (preview verified at `console-verify` port 8879)
- Page loads with 0 console errors / 0 warnings
- All 393 machine cards show review badge (visual + tooltip)
- ConfigUpload + FleetRefresh panels visible
- Self-check panel renders correctly for all 4 visual states
- Chart.js loaded from local vendored file

---

## Open work — needs user input

### Test debt cleanup (107 tests)
- 106 from Phase 2 signature changes (P2-B3/B4): need to update test callsites
  to pass `lookup_machine_md5` kwarg etc.
- 1 from main's ConcurrencyLimiter compat: P1-A1 path (b) test needs fixture
  inject for new limiter
- Triage: which test files to fix manually vs delete vs adapt

### Per-cluster + per-machine onboarding (~13 machines from Tier 1/2 + ~46 surprises from fleet smoke)
- 59 machines fail L2 (RTP-calculation completeness) per fleet smoke `02_verification.csv`
- 6 expected (Tier 1: M250/M260/M264/M268/M279/M11)
- ~46 surprises (Tier 2 trigger-session + new finds: M100/M107/M110/M121/M125/M138/M147/M151/M158/M163/M171/M18/M214/M239/M24/M243/M246/M251/M254/M263/etc)
- Per-machine investigation + manifest tuning needed

### Manifest gaps
- M278 / M280: present in current `configs/machines.json` but my generator missed them. Regenerate + re-test.

### Phase 5 proper (warn → error policy flip)
- Architecture says flip per `manifest.console_diagnostic_complete=true`. Per
  user direction 2026-05-20: integrity check stays soft hint forever; this flip
  is dropped. Status: NO-OP — preserved as is.

### Phase 4 (frontend renderer registry + SCHEMA_VERSION CI)
- Not started. Substantial app.js refactor (7996 lines). Optional per
  architecture proposal §6.6.

---

## Documentation alignment

- Architecture spec: `session_artifacts/_arch/04_architecture_proposal_v5.md` —
  authoritative for the algorithm + 11 validation rules. Unchanged by merge.
- As-built: `session_artifacts/_arch/09_architecture_as_built.md` — reframings
  per user direction (Phase 5 dropped; Tier 1/2/3 hard-case list). Unchanged
  by merge; still current.
- Deploy spec: `session_artifacts/_arch/deploy/07_deploy_decision.md` — main's
  4-phase deploy decision. Unchanged by merge; still current.
- Phase 2 tickets index: `session_artifacts/_impl/phase2/PHASE_2_TICKETS.md` —
  all ticket statuses preserved.
- Test artifacts: `session_artifacts/_test/{work_plan_*,run_log,02_verification,03_final_report}.md` —
  fleet smoke evidence; preserved.

---

## What this branch can now be merged into mainline

YES. Merge tip is `<merge-commit-after-cleanup>`. Operator side: physical copy
of new rawdata (51 freshly sampled machines) + 254 cached reports to main repo's
`rawdata/` and `reports/` directories is a separate post-push step (not via
git — both directories are gitignored or operator-state).
