# 00_brief — Console refactor: flexible ST/feature panel assembly

> Coordinator brief. Cross-cutting refactor of `src/web_console/` (fleet-shared) → arch design before impl.
> Branch `claude/playtype-rearch`. User directive (2026-06-03, verbatim intent):
> "review the console code structure; per our NEW framework, refactor it directly. The console's ST and
> feature analysis modules should be **flexibly assembled per the new framework, NOT hardwired**."

## The task
The analyzer was re-architected to an **event model** (per-SpinType) + a **per-machine feature system**
(`fresh_slotlab/analyzer/features/*` AnalyzerFeature plugins; each machine declares `analyzer_features` in its
manifest; `effective_version = hash(base_hash + that machine's feature hashes)`). The CONSOLE did not follow:
its rendering is **fully hardcoded** — a central dispatch (`frontend/app.js` ~line 7230) calls ~33 bespoke
`renderXxx(summary)` functions, each reading a FIXED summary path (e.g. `summary.player_impact.payouts_by_spin_type`,
`summary.collect_mechanic.*`, `summary.player_impact.bonus_chain_dynamics`). Adding a feature (e.g. the new
`topdollar_choice`) currently requires hand-writing a `renderTopDollarChoice` + editing the central dispatch.

**Goal:** make panel assembly DRIVEN by what a machine actually has (its declared features / observed STs +
the summary schema), so a new feature appears in the console WITHOUT hand-wiring a panel + editing the dispatch.

**Design intent already exists in the backend:** `fresh_slotlab/analyzer/features/_base.py` (`AnalyzerFeature`)
declares `SCHEMA_KEYS` ("used by the frontend renderer registry to declare fallback rules") + `SCHEMA_VERSION` +
`REGISTERED_FALLBACK_RULES` ("Per-SCHEMA_VERSION fallback renderer rules ... allows the frontend renderer registry
to render historical summaries"). The renderer registry these hooks were designed for was NEVER built. This
refactor builds it.

## Scope
- IN: `src/web_console/frontend/app.js` (render layer + central dispatch), `compare_diff.js` (A/B compare path),
  `index.html` (panel containers), the summary→panel contract, and any backend support
  (`src/web_console/backend/app.py`) for serving a per-machine "report panels" descriptor. The AnalyzerFeature
  panel-metadata hooks (`_base.py`) if descriptors co-locate with features.
- OUT (this phase): the analyzer logic (done), new machine onboarding, the slot_designer working-tree deletion
  (pre-existing, separate).

## Constraints (the gates)
- **Byte-identical rendered output for migrated panels** — the DOM/HTML a real machine's report produces must be
  identical before/after migrating a panel. This is the objective gate (the console's equivalent of the analyzer's
  byte-identical summary gate). Verify with `preview_*` against real cached reports (M15 w/ topdollar_choice,
  M275 multi-feature, a variant machine, a multi-current cell, A/B compare mode).
- **Incremental, minimum-delta** (`feedback_respect_existing_codebase`): build the flexible framework, route the
  NEW panels (topdollar_choice) through it first, migrate the 33 existing panels in byte-identical waves; do NOT
  big-bang rewrite app.js.
- **No parallel panel impl** (`feedback_no_parallel_panel_impl`): the generic renderers must reuse the existing
  formatters (fInt/fRate/fmtMult etc.) + i18n keys + helpers; a migrated panel must be column-for-column,
  formatter-for-formatter identical to its hardcoded original.
- **Machine = the increment unit** (`project_playtype_rearch`): the console assembles a machine's panels from ITS
  features; never hardcode a per-ST/per-feature panel that all machines get unconditionally.

## What this brief asks the MAPPER to produce (01_pipeline_map.md)
1. **Full panel inventory**: every `renderXxx` panel — its function name, the EXACT summary path it reads, its
   container element id, where it's called from (the central dispatch sequence + any conditional gating), and a
   type classification (kv-table / rows-table / chart / drilldown / banner / bespoke). ~33 panels.
2. **The render dispatch flow**: the central report-render entry (≈app.js:7220-7250) → ordered render calls; how
   the summary reaches it; how A/B compare (`cmpB` / compare_diff.js) threads a second summary; how
   variant/multi-current/historical cells select which summary.
3. **The summary→panel contract**: which top-level summary keys exist (e.g. `player_impact.*`, `collect_mechanic`,
   `topdollar_choice`, `upstream_analysis`), and which panel reads which — the implicit schema the registry must
   formalize. Cross-reference the backend AnalyzerFeature `SCHEMA_KEYS` for the feature-owned sections.
4. **Backend serving**: how the summary is served to the frontend (endpoint, shape); whether the backend already
   exposes the machine's `analyzer_features` / manifest to the frontend (needed to know which panels a machine has).
5. **Insertion points + risks**: where a registry-driven assembler would slot in; the hardest cases that could
   break a generic assembler (compare-diff, split/aggregate views like payouts_by_spin_type, retired panels,
   panels reading multiple summary sections, panels with bespoke charts).

Evidence: cite `file:line`. NO design proposals (that is the designer's job) — just the map.
