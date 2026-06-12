# Report-store management fix (2026-06-12)

User-approved investigation → fix. Map (read first): REPORT_MGMT_MAP_2026-06-12.md.
User hypothesis CONFIRMED: the management layer didn't change; the NEW-architecture
producers feed it incompatible/poorer data, and the old layer has pre-existing
structural defects the new load exposed. Console backend only — fresh_slotlab is NOT
touched (no base_hash implications; the analyzer is frozen).

## Defects being fixed (from the map)

1. **Four producers, four entry shapes.** Legacy `_update_report_index` (app.py:6685)
   writes the full shape (incl. rawdata_config_md5/code_md5/analyzer_version/
   effective_analyzer_version); the generate path (:9559) and batch finalize (:9892)
   omit all four; `/api/reports/import` (:10512) writes NO index/latest at all;
   `reports_retention._refresh_mode_manifests` (:175) rebuilds a fourth, poorest shape
   and unconditionally claims `player_impact_report.md` which the new engine never
   writes (report_engine docstring is wrong about ".md" too — fix the docstring only,
   not the engine).
2. **index.json lost-update race.** All writers do read-list → append → atomic write
   with NO lock; concurrent batch finalizes drop entries (M14/mode_1: 16 dirs, 4
   entries). chunk_index's sidecar locking is the in-repo precedent.
3. **update_run omits effective_analyzer_version** on both new paths (+ import) even
   though the summary carries it → honesty-3 staleness counts these rows "untagged"
   forever (2,054 completed rows; only 2 have it).
4. **Version dir created before validation; failure path never cleans.** Empty dirs
   accumulate (15 fleet-wide; live case rv_20260612T064850Z) + 9 dirs holding only
   machine_config.json/progress.jsonl; `report_count` (app.py:2808) counts raw dirs →
   catalog says N, panel says M.
5. **Stale latest.json** where a failed run wrote latest or entries were lost
   (M254/mode_7, M275/mode_7: latest.json + index []).
6. **Absolute paths rot**: 261/343 entries point into `.claude/worktrees/stoic-napier-…`
   (the dir still exists but is no longer a registered worktree — a deletion bomb).
   Canonical copies exist in the main repo for at least some (M275 May-20 verified);
   repair must verify per entry.

## Fix design

### F1 — single entry builder + locked writer (new module `src/web_console/backend/report_index.py`)
- `build_index_entry(reports_root, machine, mode, report_version, run_id, *, summary: dict, summary_path: Path) -> dict`
  → the FULL legacy-compatible shape: report_version, run_id, created_at,
  summary_file (canonical absolute under reports_root), report_file (ONLY when the
  .md actually exists — key present-with-path or absent entirely), rtp_point_pct,
  achieved_rtp_pct, achieved_halfwidth_pp, total_spins, quality_label,
  rawdata_config_md5, rawdata_code_md5, analyzer_version, effective_analyzer_version.
  All md5/version fields read from the SUMMARY (single source).
- `append_index_entry(mode_dir, entry)` and `rewrite_latest(mode_dir)` guarded by a
  `index.json.lock` file lock (mirror chunk_index's locking; timeout + stale-lock
  handling). latest.json = the newest entry by created_at (recomputed, not blind copy).
- Wire ALL producers onto it: generate finalize (~:9556), batch finalize (~:9890),
  `/api/reports/import` (must now ALSO index + latest each imported version),
  `reports_retention._refresh_mode_manifests` (rebuild via the same builder).
- `update_run` on both new paths + import gains `effective_analyzer_version` (from
  summary).
- `report_versions` read-time backfill also fills `effective_analyzer_version`.

### F2 — failure hygiene
- generate + batch: on failure/exception, remove the created version dir IF it does
  not contain `player_impact_summary.json` (guard: only the dir this run created).
  Keep the failed run row (history is wanted) — it just no longer leaves litter.
- Move the mkdir AFTER the manifest-existence/validation pre-checks where trivially
  possible; the cleanup covers the rest (engine-internal failures).

### F3 — honest report_count
- `load_machines` counts version dirs that CONTAIN `player_impact_summary.json`
  (the "reports on disk" truth, immune to index lag/races). Same definition everywhere
  a dir scan counts "reports" (`_machines_summary_fingerprint` stays stat-based —
  it's only a cache key).

### F4 — reconcile (repair the existing litter; one-shot now + reusable)
New maintenance endpoint `POST /api/maintenance/reconcile-reports` (+ `dry_run` flag,
default true) + same logic callable as a script. Per (machine, mode):
- empty version dir → delete.
- dir without summary (only machine_config/progress) → delete ONLY IF no run row in
  status running/pending references it AND mtime > 1h old.
- dir WITH summary but no index entry → append a rebuilt entry (builder above). This
  recovers M14's 12 race-lost reports and indexes imported dirs.
- index entry whose summary_file ≠ canonical path: if canonical exists → rewrite to
  canonical; elif old path exists → copy the version dir's files to canonical, then
  rewrite; else → drop the entry (zombie) with a logged action.
- entries missing md5/analyzer/effective/perf fields → persist-backfill from summary.
- `report_file` claims with no file → drop the key.
- latest.json recomputed from the final index (deleted when index empty).
- SQLite: backfill `effective_analyzer_version` (and missing rawdata md5s) on
  completed rows from their summaries.
- Returns a full action report (counts + per-action list); NEVER silent
  (feedback_no_silent_swallow). Deletion safety per feedback_md5_is_a_tag: only
  the explicitly-enumerated litter classes above, never md5-driven.

### Tests (value-agnostic, inject-bug→red→revert→green)
- Entry shape: all four producers route through the builder → full field set
  (parametrized); report_file key only when .md exists.
- Race: two concurrent append_index_entry → both entries present (threaded test).
- Failure hygiene: generate path failing on manifest validation leaves NO version dir.
- report_count == summary-bearing dirs (empty dir ignored).
- Reconcile: build a synthetic litter tree (each defect class) → reconcile dry-run
  reports the right actions, wet-run repairs them, second run = no-op (idempotent).
- update_run effective_analyzer_version present on the new paths (argv/integration
  level where a subprocess is involved — feedback_integration_test_argv).

### Out of scope
- fresh_slotlab/** (frozen; no closure files touched — base_hash must stay c5d2199142c3).
- Switching stored paths to relative (bigger reader refactor; canonical-absolute +
  reconcile covers the rot; revisit if repo relocation becomes real).
- The legacy sampling RunManager path keeps writing its rich entries — it is wired
  onto the builder too for shape unification, but its behavior must not otherwise change.
