# Production vs Virtual Console Asymmetry Contract

> Source of truth for every intentional (and accidental) behavioral
> difference between the **real console** (port 8877, `src/web_console/`)
> and the **virtual console** (port 8878, `slot_designer/core/backend/`).
>
> Generated from: `session_artifacts/_arch/01_pipeline_map.md §4` (reuse/duplication audit)
> and `session_artifacts/_arch/03_coupling_audit.md §4.5`.
> Ticket: phase1/05_virtual_paytable_probe_docs (P1-A3).
>
> Last updated: 2026-05-30 (honesty-3 effective-version asymmetry added as §A0;
> A4/A5 consolidation landed; §E P1-B3 closed; line refs converted to symbol anchors)

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

### A0 — `effective_analyzer_version`: real computes per-(machine,mode); virtual stamps base + `kind="virtual_base_only"`

**What**: The report-currency / staleness axis is the per-(machine,mode)
`effective_analyzer_version` summary field (honesty-3, 2026-05-29). The two
consoles populate it asymmetrically:

- **Real console**: the analyzer (`player_impact_analyzer.py` `main()`) calls
  `versioning.compute_effective_version_for_machine(machine, mode)`, which reads
  the machine's manifest, resolves declared features, and returns a 12-hex hash
  of `base ⊕ {declared feature hashes} ⊕ mode`. The summary gets that value plus
  a `effective_analyzer_version_error` diagnostic (None on success). No `kind`
  marker on the real path.
- **Virtual console**: virtual machines have **no manifest**, so PIA's
  `compute_effective_version_for_machine` raises `FileNotFoundError` and PIA
  leaves `effective_analyzer_version = ""`. The virtual delegate then post-stamps
  the **base hash** (`versioning.compute_base_analyzer_version()`) into the field
  and adds `effective_analyzer_version_kind = "virtual_base_only"` (and clears the
  PIA-swallowed error). This is an honest "virtual: no manifest, base-level
  resolution only" state — never an empty/swallowed value.

**Why**: Intentional (honesty-3 R-8). Virtual delegates to the REAL PIA code (same
import closure), so when the production closure changes, virtual reports must also
mark stale — base_hash gives them a real staleness axis. The `kind` marker
honestly discloses that per-feature isolation is unavailable (no manifest), so
the base hash is the best truthful resolution. Per-feature granularity (the
real-console behavior) requires a manifest the virtual fleet does not carry.

**Code location**:
- Real (per-machine effective written by PIA): `fresh_slotlab/player_impact_analyzer.py`
  `main()` (the `compute_effective_version_for_machine` call that fills the
  `effective_analyzer_version` summary key) → `fresh_slotlab/analyzer/versioning.py`
  `compute_effective_version_for_machine`
- Virtual (base+kind post-stamp): `slot_designer/core/backend/virtual_analyzer.py`
  `_patch_summary_effective_version` (called from `_delegate_to_real_analyzer`
  after the delegate subprocess returns, alongside `_patch_summary_md5_tags`)
- Console comparator (per-request, memoized): `src/web_console/backend/effective_version_cache.py`
  `EffectiveVersionCache.get` — returns the `UNVERIFIABLE` sentinel for any
  machine with no manifest (treated as "cannot verify", neither fresh nor stale).

**Risk**: If the virtual post-stamp is removed or `compute_base_analyzer_version`
starts raising (broken closure), virtual summaries land with empty
`effective_analyzer_version` and the virtual console loses its staleness axis
entirely (silently). The stamp is applied ONLY when the field is empty, so a
future PIA gaining virtual-registry awareness makes it a no-op automatically. Note
the comparison is **non-destructive**: a stale verdict is a read-only
classification (staleness badge); it NEVER deletes report artifacts.
Re-baselining is on-demand (operator regenerates).

---

### A1 — `/api/virtual/paytable/{m}` virtual-only route

**What**: `GET /api/virtual/paytable/{m}` is registered only on the virtual
console. The real console returns 404 for this path.

**Why**: Intentional architectural contract (2026-04-22). Virtual-specific
HTTP endpoints are kept out of `src/web_console/backend/app.py` so the real
console surface stays unchanged. See docstring on
`slot_designer/core/backend/virtual_app.py` `_register_virtual_only_routes`.

**Code location**:
- Virtual (registers route): `slot_designer/core/backend/virtual_app.py`
  `_register_virtual_only_routes` → `GET /api/virtual/paytable/{machine}`
- Real (no route, returns 404): `src/web_console/backend/app.py` — not present
- Frontend probe + catch: `src/web_console/frontend/app.js` — try/catch around
  `apiGet('/api/virtual/paytable/${machine}')` in the paytable-overview render
  path; `declaredPays` stays `[]` on error → observed-only rendering

**Risk**: If a future refactor removes that try/catch around the
`/api/virtual/paytable/${machine}` fetch (e.g. someone replaces it with an
`await` without a catch), the real console
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
(incident recorded in the `virtual_app.py` module docstring).

**Code location**:
- Virtual (local refresh): `slot_designer/core/backend/virtual_app.py`
  `_local_md5_refresh` → calls `refresh_machines_virtual(VIRTUAL_MACHINES_CONFIG)`
- Real (upstream fetch): `src/web_console/backend/app.py` — default handler
  (no override; `create_app(md5_refresh_override=None)` uses upstream path)
- Injection point: `virtual_app.py` `create_app(md5_refresh_override=_local_md5_refresh)`

**Risk**: If `md5_refresh_override` is removed from the `create_app` call in
`virtual_app.py`, the frontend bootstrap's auto-refresh-md5 POST will
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
- Virtual: `slot_designer/core/backend/virtual_app.py`
  `_load_declared_pays_from_spec(machine)` → reads `_spec_path` field from
  `VIRTUAL_MACHINES_CONFIG`, loads JSON spec, returns lean `pays` list
- Real: no equivalent; `src/web_console/backend/app.py` does not have a
  `_load_declared_pays_from_spec` function

**Risk**: If `machines_virtual.json` entries don't carry a valid `_spec_path`
field (e.g. after a machine rename or spec-file move), the function returns `[]`
silently (by design — callers treat it as best-effort). The frontend falls back
to observed-only rendering without error. Low risk, but debugging "missing
declared rows" requires checking the `_spec_path` field in the registry.

---

### A4 — Summary md5 patch: two call sites, ONE shared helper (P1-B2 CONSOLIDATED)

**What**: After an analyzer run, the summary JSON's `config_md5` / `code_md5`
fields may be empty because `_lookup_machine_md5` in the real analyzer reads
only `configs/machines.json` (real-fleet registry) and returns `("", "")` for
virtual machines. Two code paths post-stamp these fields, but as of P1-B2 both
delegate to the **same** shared helper `fresh_slotlab/summary_md5_patch.py`
`patch_summary_md5`:

1. **Real console in-process generate-report path** calls `patch_summary_md5`
   directly after `pia.main()` returns in-process.
2. **Virtual analyzer subprocess path** calls it via the thin wrapper
   `_patch_summary_md5_tags` after the delegate subprocess returns.

The remaining asymmetry is only *which call site fires for which console*; the
patch LOGIC is single-sourced.

**Why**: Was accidental duplication; now consolidated. Both sites were added
independently to fix the same symptom (`md5_status=untagged` → rwtree cell shows
"无 fresh report"). P1-B2 (commit d8747e9) unified the body into one helper.

**Code location**:
- Shared helper (canonical): `fresh_slotlab/summary_md5_patch.py` `patch_summary_md5`
- Real console call site: `src/web_console/backend/app.py` `_run_generate_report`
  (imports `patch_summary_md5` and calls it with a
  `lambda: _get_machine_md5(machine, mc, mode=mode)` md5 source)
- Virtual analyzer call site: `slot_designer/core/backend/virtual_analyzer.py`
  `_patch_summary_md5_tags` (thin wrapper, called from `_delegate_to_real_analyzer`)

**Risk**: Low (consolidated). If the shared helper's signature changes, both call
sites must pass compatible arguments, but the patch behavior can no longer drift
between consoles.

---

### A5 — Inference trigger: two call sites, ONE shared helper (P1-B5 CONSOLIDATED)

**What**: After analysis completes, inference scripts (`infer_paytable.py` +
`infer_bcm_pairing.py`) are triggered from two different locations, but as of
P1-B5 both delegate to the **same** canonical helper
`fresh_slotlab/post_inference.py` `run_post_analyzer_inference`:

1. **Real console** triggers from the backend after `_run_generate_report`
   completes (via the thin wrapper `_run_post_analyzer_inference`).
2. **Virtual analyzer** triggers from inside the virtual_analyzer subprocess
   after the delegate returns (via the thin wrapper `_run_inference_scripts`).

The remaining asymmetry is only *which call site fires for which console* (and
the per-console output-dir / path args each wrapper forwards); the trigger LOGIC
is single-sourced.

**Why**: Was accidental duplication; now consolidated. Virtual sampling does not
route through `_run_generate_report` (it goes through `virtual_analyzer.main()` →
delegate subprocess → `_run_inference_scripts`), so the real backend's post-hook
never fires for virtual runs — hence two call sites are still required. P1-B5
(commit f4fb94d) unified the trigger body into one helper.

**Code location**:
- Shared helper (canonical): `fresh_slotlab/post_inference.py` `run_post_analyzer_inference`
- Real console wrapper: `src/web_console/backend/app.py`
  `_run_post_analyzer_inference` (forwards `paytables_dir` / `classify_dir` /
  `rawdata_root` / `log_to_dir`; fired as a background thread after generate-report)
- Virtual analyzer wrapper: `slot_designer/core/backend/virtual_analyzer.py`
  `_run_inference_scripts` (hardcodes virtual paths; called from
  `_delegate_to_real_analyzer` after the delegate returns)

**Risk**: Low (consolidated). The two wrappers forward different per-console paths
into the same canonical helper; if the scripts' CLI changes the helper is updated
once and both consoles inherit the fix.

---

## §B — Non-asymmetries (shared verbatim — record for audit completeness)

These items were audited and confirmed to be single-sourced. Recorded here so
future auditors don't re-investigate them.

---

### B1 — Frontend bundle is single-sourced

**What**: `index.html`, `app.js`, `pure.js`, `compare_diff.js`, `styles.css`
are served identically by both consoles. The virtual console calls the same
`create_app()` factory which mounts the same `FRONTEND_DIR` at `/console`.

**Evidence**: `src/web_console/backend/app.py` defines `FRONTEND_DIR =
src/web_console/frontend` (module top) and mounts it at `/console` inside
`create_app`; `slot_designer/core/backend/virtual_app.py` calls `create_app(...)`
without overriding `FRONTEND_DIR`.

**Implication**: Any frontend change (including comment additions) applies to
both consoles automatically. No virtual-specific frontend fork exists.

---

### B2 — `chunk_index` + `rawdata_index` are shared verbatim

**What**: `fresh_slotlab/chunk_index.py` and `fresh_slotlab/rawdata_index.py`
are imported directly by both console stacks. No forked copies exist.

**Evidence**: the `fresh_slotlab/chunk_index.py` module docstring states "shared
verbatim between real console and virtual console". Virtual chunk writes go
through `slot_designer/core/emitter/chunk.py` `write_chunk` →
`chunk_index.update_chunk_entry` (same function). Virtual reads go through
`virtual_analyzer.py` `_select_session_stat_chunks` → `chunk_index.chunks_by_md5`
(same function).

**Implication**: Bug fixes and index-format changes in `chunk_index.py` apply
to both consoles. Do not fork. Per `memory/reference_chunk_index_inverted_md5.md`.

---

## §C — How to add a new virtual-only route

1. Implement the route handler function in `virtual_app.py` (before
   `_register_virtual_only_routes`).
2. Add the `@app.get(...)` or `@app.post(...)` registration inside
   `_register_virtual_only_routes(app)` in `virtual_app.py`.
3. Add an entry to §A of this document with What / Why / Code location / Risk.
4. If the frontend probes the new route: add a try/catch at the callsite so
   real-console 404 degrades gracefully (see the A1 pattern in `app.js`).

---

## §D — Ticket cross-references

| Asymmetry | Status | Ticket |
|-----------|--------|--------|
| A0 (effective_analyzer_version: real per-machine vs virtual base+kind) | Intentional (honesty-3 R-8); stable | — |
| A1 (virtual paytable route) | Intentional; stable | — |
| A2 (_local_md5_refresh) | Intentional; stable | — |
| A3 (_load_declared_pays_from_spec) | Intentional; stable | — |
| A4 (summary md5 patch: two call sites, one helper) | **CONSOLIDATED** (P1-B2, d8747e9) | P1-B2 |
| A5 (inference trigger: two call sites, one helper) | **CONSOLIDATED** (P1-B5, f4fb94d) | P1-B5 |
| B1 (frontend single-sourced) | Non-asymmetry; confirmed | — |
| B2 (chunk_index + rawdata_index shared) | Non-asymmetry; confirmed | — |

---

## §E — Known duplications not yet ticketed (one-liners)

Per P1-A3 round-2 critic R2: keep an exhaustive record so future auditors
do not miss them. Each entry is one line by design; promote to a full §A
entry when a ticket is opened.

| Duplication | Location | Status |
|---|---|---|
| `t_critical_95` table | `fresh_slotlab/sampler.py` `t_critical_95` canonical (3 → 1 dedup landed; PIA + virtual_analyzer import it) | **CLOSED** by P1-B4 (commit f8d8360) |
| Session-CI half-width formula | `fresh_slotlab/sampler.py` `session_halfwidth_pp` canonical; PIA imports it and keeps `_ci_halfwidth_pp` as a module alias, `virtual_analyzer.py` imports `session_halfwidth_pp` | **CLOSED** by P1-B3 (commit 17160c3) |
| Schema fingerprint compute | `fresh_slotlab/analyzer/core/parser.py` `_compute_upstream_schema_fingerprint` (moved out of PIA during the unbundle) + `slot_designer/core/emitter/{chunk,driver}.py` | **OPEN** — no ticket; investigate later. NOTE: PIA no longer carries its own copy (it lives in the analyzer core parser now). |
| `peek_chunk_envelope` | `fresh_slotlab/chunk_index.py` `peek_chunk_envelope` (canonical per `03_coupling_audit.md §4.5`) + `fresh_slotlab/analyzer/core/parser.py` `peek_chunk_envelope` (the analyzer's local copy, moved out of PIA during the unbundle) | **OPEN** — analyzer core's local copy is a latent divergence risk |
