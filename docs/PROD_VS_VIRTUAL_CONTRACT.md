# Production vs Virtual Console Asymmetry Contract

> Source of truth for every intentional (and accidental) behavioral
> difference between the **real console** (port 8877, `src/web_console/`)
> and the **virtual console** (port 8878, `slot_designer/core/backend/`).
>
> Generated from: `session_artifacts/_arch/01_pipeline_map.md §4` (reuse/duplication audit)
> and `session_artifacts/_arch/03_coupling_audit.md §4.5`.
> Ticket: phase1/05_virtual_paytable_probe_docs (P1-A3).
>
> Last updated: 2026-05-17

---

## How to use this document

- **Adding a new virtual-only route** — add an entry to §A below; add a
  cross-reference comment at the registration site.
- **Collapsing an asymmetry** — remove the entry and update both callsites.
- **Discovering an unknown asymmetry** — add it here; decide intentional vs
  accidental; link the ticket that will fix it if accidental.

---

## §A — Asymmetries (divergences)

Each entry covers: **What / Why / Code location / Risk**.

---

### A1 — `/api/virtual/paytable/{m}` virtual-only route

**What**: `GET /api/virtual/paytable/{m}` is registered only on the virtual
console. The real console returns 404 for this path.

**Why**: Intentional architectural contract (2026-04-22). Virtual-specific
HTTP endpoints are kept out of `src/web_console/backend/app.py` so the real
console surface stays unchanged. See docstring at
`slot_designer/core/backend/virtual_app.py:152-159`.

**Code location**:
- Virtual (registers route): `slot_designer/core/backend/virtual_app.py:149-173`
  (`_register_virtual_only_routes` → `GET /api/virtual/paytable/{machine}`)
- Real (no route, returns 404): `src/web_console/backend/app.py` — not present
- Frontend probe + catch: `src/web_console/frontend/app.js:4558-4569`
  (try/catch around `apiGet('/api/virtual/paytable/${machine}')`;
  `declaredPays` stays `[]` on error — observed-only rendering)

**Risk**: If a future refactor removes the try/catch in `app.js:4484-4494`
(e.g. someone replaces it with an `await` without a catch), the real console
UI will break because 404 becomes an uncaught rejection. The catch block must
be kept unconditionally or gated on a virtual-console feature flag.

---

### A2 — `_local_md5_refresh`: virtual computes md5 locally; real fetches from upstream

**What**: `POST /api/machines/refresh-md5` calls different md5 sources on
each console. Real console fetches `configSummaryMd5` / `codeSummaryMd5`
from the upstream server (`192.168.10.21:15060`). Virtual console recomputes
md5 locally from spec + weights + engine source files.

**Why**: Intentional. Virtual machines have no upstream server entry; their
md5 is authoritatively derived from local files at
`slot_designer/configs/machines_virtual.json`. Without this override, the
real-console md5-refresh handler would try to pull from upstream and merge
real-fleet machine rows into `machines_virtual.json`, breaking data isolation
(incident recorded at `virtual_app.py:62-67`).

**Code location**:
- Virtual (local refresh): `slot_designer/core/backend/virtual_app.py:56-94`
  (`_local_md5_refresh` → calls `refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)`)
- Real (upstream fetch): `src/web_console/backend/app.py` — default handler
  (no override; `create_app(md5_refresh_override=None)` uses upstream path)
- Injection point: `virtual_app.py:195` (`create_app(md5_refresh_override=_local_md5_refresh)`)

**Risk**: If `md5_refresh_override` is removed from the `create_app` call in
`virtual_app.py:195`, the frontend bootstrap's auto-refresh-md5 POST will
silently merge upstream real-fleet rows into `machines_virtual.json`. The
data-isolation boundary breaks without any error; symptoms appear only at
the rwtree freshness layer.

---

### A3 — `_load_declared_pays_from_spec`: virtual reads spec; real has no equivalent

**What**: The virtual paytable endpoint (`A1`) uses `_load_declared_pays_from_spec`
to read the full declared `pays` list from the machine's spec file (including
`rtp_excluded` grand jackpots that never fire at 10k-spin sample sizes). The
real console has no concept of a "declared paytable" — it renders only what
was observed in the data.

**Why**: Intentional. Virtual machines are designed with explicit `pays` entries
in `machines_virtual.json` → spec file. Making declared-but-unobserved pay_ids
visible in the Pay ID overview panel is a virtual-console UX feature (operators
see "pay_id 4 = 1000× — 0 hits" instead of the row simply being absent).

**Code location**:
- Virtual: `slot_designer/core/backend/virtual_app.py:97-146`
  (`_load_declared_pays_from_spec(machine)` → reads `_spec_path` field from
  `VIRTUAL_MACHINES_CONFIG`, loads JSON spec, returns lean `pays` list)
- Real: no equivalent; `src/web_console/backend/app.py` does not have a
  `_load_declared_pays_from_spec` function

**Risk**: If `machines_virtual.json` entries don't carry a valid `_spec_path`
field (e.g. after a machine rename or spec-file move), the function returns `[]`
silently (by design — callers treat it as best-effort). The frontend falls back
to observed-only rendering without error. Low risk, but debugging "missing
declared rows" requires checking the `_spec_path` field in the registry.

---

### A4 — Summary md5 patch: two separate patch sites (consolidation target P1-B2)

**What**: After an analyzer run, the summary JSON's `config_md5` / `code_md5`
fields may be empty because `_lookup_machine_md5` in the real analyzer reads
only `configs/machines.json` (real-fleet registry) and returns `("", "")` for
virtual machines. Two separate code paths patch these fields post-run:

1. **Real console in-process generate-report path** patches the written summary
   after calling `pia.main()` in-process.
2. **Virtual analyzer subprocess path** patches the summary after the delegate
   subprocess returns.

**Why**: Accidental duplication. Both sites were added independently to fix the
same symptom (`md5_status=untagged` → rwtree cell shows "无 fresh report").
P1-B2 is the consolidation ticket that will unify these into a single helper.

**Code location**:
- Real console patch: `src/web_console/backend/app.py:6945-6969`
  (inline block in `_run_generate_report`; patches if `_cur_cfg` or `_cur_code`
  is non-empty and summary field is currently empty)
- Virtual analyzer patch: `slot_designer/core/backend/virtual_analyzer.py:500-558`
  (`_patch_summary_md5_tags(output_dir, cfg, code)` called at `virtual_analyzer.py:665`)
- Cross-reference comment at real site: `app.py:6953` ("Mirrors the fix
  virtual_analyzer.py applies …")

**Risk**: If P1-B2 is only partially applied (one site consolidated, other
left), the unconsolidated side will continue patching with stale md5 values.
Both sites must be migrated together.

---

### A5 — Inference trigger: two separate trigger sites (consolidation target P1-B5)

**What**: After analysis completes, inference scripts (`infer_paytable.py` +
`infer_bcm_pairing.py`) are triggered from two different locations with
different argument signatures:

1. **Real console** triggers from the backend after `_run_generate_report`
   completes (called via `_run_post_analyzer_inference`).
2. **Virtual analyzer** triggers from inside the virtual_analyzer subprocess
   after the delegate returns (via `_run_inference_scripts`).

**Why**: Accidental duplication. Virtual sampling does not route through
`_run_generate_report` (it goes through `virtual_analyzer.main()` → delegate
subprocess → `_run_inference_scripts`), so the real backend's post-hook never
fires for virtual runs. The virtual path had to duplicate the trigger logic.
P1-B5 is the consolidation ticket.

**Code location**:
- Real console trigger: `src/web_console/backend/app.py:85-194`
  (`_run_post_analyzer_inference(machine, mode, paytables_dir, classify_dir)`;
  called at `app.py:7055` as a background thread after generate-report)
- Virtual analyzer trigger: `slot_designer/core/backend/virtual_analyzer.py:555-649`
  (`_run_inference_scripts(machine, mode)`; hardcodes virtual paths; called
  at `virtual_analyzer.py:674` after delegate returns)

**Risk**: The two implementations have diverging argument signatures (real takes
`paytables_dir` / `classify_dir` params; virtual hardcodes). If the scripts'
CLI changes, both sites must be updated independently until P1-B5 consolidates
them. Forgetting one side silently breaks inference for one console type.

---

## §B — Non-asymmetries (shared verbatim — record for audit completeness)

These items were audited and confirmed to be single-sourced. Recorded here so
future auditors don't re-investigate them.

---

### B1 — Frontend bundle is single-sourced

**What**: `index.html`, `app.js`, `pure.js`, `compare_diff.js`, `styles.css`
are served identically by both consoles. The virtual console calls the same
`create_app()` factory which mounts the same `FRONTEND_DIR` at `/console`.

**Evidence**: `src/web_console/backend/app.py:72` defines `FRONTEND_DIR =
src/web_console/frontend`; `app.py:5392` mounts it; `virtual_app.py:186-197`
calls `create_app(...)` without overriding `FRONTEND_DIR`.

**Implication**: Any frontend change (including comment additions) applies to
both consoles automatically. No virtual-specific frontend fork exists.

---

### B2 — `chunk_index` + `rawdata_index` are shared verbatim

**What**: `fresh_slotlab/chunk_index.py` and `fresh_slotlab/rawdata_index.py`
are imported directly by both console stacks. No forked copies exist.

**Evidence**: `chunk_index.py:46-51` docstring states "shared verbatim between
real console and virtual console". Virtual chunk writes go through
`slot_designer/core/emitter/chunk.py:write_chunk` → `chunk_index.update_chunk_entry`
(same function). Virtual reads go through `virtual_analyzer.py:353-376`
`_select_session_stat_chunks` → `chunk_index.chunks_by_md5` (same function).

**Implication**: Bug fixes and index-format changes in `chunk_index.py` apply
to both consoles. Do not fork. Per `memory/reference_chunk_index_inverted_md5.md`.

---

## §C — How to add a new virtual-only route

1. Implement the route handler function in `virtual_app.py` (before
   `_register_virtual_only_routes`).
2. Add the `@app.get(...)` or `@app.post(...)` registration inside
   `_register_virtual_only_routes(app)` at `virtual_app.py:149-173`.
3. Add an entry to §A of this document with What / Why / Code location / Risk.
4. If the frontend probes the new route: add a try/catch at the callsite so
   real-console 404 degrades gracefully (see A1 pattern at `app.js:4484-4494`).

---

## §D — Ticket cross-references

| Asymmetry | Status | Ticket |
|-----------|--------|--------|
| A1 (virtual paytable route) | Intentional; stable | — |
| A2 (_local_md5_refresh) | Intentional; stable | — |
| A3 (_load_declared_pays_from_spec) | Intentional; stable | — |
| A4 (summary md5 patch: two sites) | Accidental; pending consolidation | P1-B2 |
| A5 (inference trigger: two sites) | Accidental; pending consolidation | P1-B5 |
| B1 (frontend single-sourced) | Non-asymmetry; confirmed | — |
| B2 (chunk_index + rawdata_index shared) | Non-asymmetry; confirmed | — |

---

## §E — Known duplications not yet ticketed (one-liners)

Per P1-A3 round-2 critic R2: keep an exhaustive record so future auditors
do not miss them. Each entry is one line by design; promote to a full §A
entry when a ticket is opened.

| Duplication | Location | Status |
|---|---|---|
| `t_critical_95` table | `fresh_slotlab/sampler.py:139-190` canonical (3 → 1 dedup landed) | **CLOSED** by P1-B4 (commit f8d8360) |
| Session-CI half-width formula | `fresh_slotlab/player_impact_analyzer.py:1012-1034` + `slot_designer/core/backend/virtual_analyzer.py:278-291` | **PENDING** P1-B3 |
| Schema fingerprint compute | `fresh_slotlab/player_impact_analyzer.py:_compute_upstream_schema_fingerprint:2108-2138` + `slot_designer/core/emitter/{chunk,driver}.py` | **OPEN** — no ticket; investigate later |
| `peek_chunk_envelope` | `fresh_slotlab/player_impact_analyzer.py:2083` + `fresh_slotlab/chunk_index.py:145` (canonical per `03_coupling_audit.md §4.5`) | **OPEN** — analyzer's local copy is latent divergence risk |
