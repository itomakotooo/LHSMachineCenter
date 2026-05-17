# Ticket P1-A3 — Frontend probe location documented for `/api/virtual/paytable/{m}` (Batch 1b)

> Phase 1 / Batch 1b. Pure documentation; no code change to runtime. Establishes a record of the real ↔ virtual asymmetries so future contributors don't break them.

---

## §1 Ticket scope

The probe location was found during ticket research: [app.js:4484-4495](src/web_console/frontend/app.js:4484). The existing comment block at lines 4475-4482 already explains the asymmetry well ("Real console: endpoint 404s → declaredPays stays [] → observed-only rendering"). This ticket extracts the contract into a dedicated doc + adds cross-references so future audits land on it.

Files expected to change:
- `docs/PROD_VS_VIRTUAL_CONTRACT.md` (new) — enumerates every real ↔ virtual asymmetry
- `src/web_console/frontend/app.js:4475-4495` — add a 1-line `// See docs/PROD_VS_VIRTUAL_CONTRACT.md` cross-reference comment
- `slot_designer/core/backend/virtual_app.py:152-159` — add the same cross-reference comment

---

## §2 Brief sections cited

- `session_artifacts/_arch/01_pipeline_map.md §5 Q5` — probe location was unverified
- `session_artifacts/_arch/03_coupling_audit.md §4.5` last bullet — asymmetry list
- `session_artifacts/_arch/01_pipeline_map.md §4` (entire) — real vs virtual reuse vs duplication audit (good source material for the doc)

---

## §3 Contract (testable invariants)

### C1 — Doc enumerates known asymmetries
`docs/PROD_VS_VIRTUAL_CONTRACT.md` lists at minimum:
- `/api/virtual/paytable/{m}` (virtual-only route, real returns 404, frontend probes + catches)
- `_local_md5_refresh` (virtual computes md5 locally; real fetches from upstream)
- Spec-load helper `_load_declared_pays_from_spec` (virtual reads `machines_virtual.json`; real has no equivalent)
- Two summary md5 patch sites (real `_run_generate_report:6955`; virtual `_patch_summary_md5_tags:506`) — note these are being consolidated in P1-B2
- Two inference triggers (real `_run_post_analyzer_inference:85`; virtual `_run_inference_scripts:561`) — note P1-B5 consolidation
- Frontend bundle is single-sourced (no asymmetry — call this out as a positive)
- chunk_index + rawdata_index are shared verbatim (no asymmetry — positive)

### C2 — Each asymmetry entry has fields
For each asymmetry:
- **What** — one line
- **Why** — one line (intentional or accidental; if accidental, link to relevant ticket)
- **Code location** — file:line for both sides
- **Risk** — what breaks if the asymmetry is collapsed naively

### C3 — Cross-reference comments
Frontend probe site (`app.js:4475-4482`) and virtual route registration site (`virtual_app.py:152-159`) both contain a single-line comment pointing to the doc.

---

## §4 Out of scope

- Making real console return `/api/virtual/paytable/{m}` as a stub (asymmetry is intentional per `virtual_app.py:152-159` architectural contract)
- Auditing every line of `app.js` for unmentioned asymmetries (initial pass: 6 known asymmetries from `01 §4`; future asymmetries get added per discovery)
- Renaming any code paths

---

## §5 Rollback path

Single commit. `git revert <sha>` removes the doc + comments.

---

## §6 Risk + rollback notes

**Risk class**: LOW (docs only; no runtime change).

**Test added**: per `IMPL_TEAM_PROCESS §5 invariant 5`: docs-only tickets can use `N/A: docs only` for tests-added section in commit message, since there's no behavior to test. The doc itself is the deliverable. Critic verifies completeness against `01 §4` source material.

---

## §7 Suggested impl-* team workflow

### Wave 1 (parallel)
- `impl-implementer` — writes the doc + cross-reference comments + `02_implementation.md`
- `impl-tester` — N/A (docs only). Writes `03_tests.md` with "N/A: docs only" verdict + cites the asymmetries from `01 §4` as the validation criterion for critic to check

### Wave 2 (parallel)
- `impl-verifier` — N/A runtime; reads the doc against `01 §4` source material, asserts all 6 known asymmetries documented; runs full pytest suite (sanity check no accidental code change)
- `impl-critic` — checks: doc complete? Any asymmetry missed from `01 §4`? Are cross-references at the right locations?

Expected wall time: ~20-30 min.
