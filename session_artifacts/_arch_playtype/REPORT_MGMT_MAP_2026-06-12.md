# Report Version Store — Management Layer Map (2026-06-12)

> Recorded by the coordinator from the arch-mapper run (the agent returned the map inline).
> Evidence basis for REPORT_MGMT_FIX_2026-06-12.md. Line numbers are pre-fix.

## 1. Physical store layout

```
reports/<M>/mode_<n>/
  index.json          — append-log of report entries
  latest.json         — copy of most-recent successful entry
  versions/<rv_*>/
    player_impact_summary.json  — canonical output (always present)
    player_impact_report.md     — LEGACY path only; new engine never writes it
    _post_hook.json             — batch-gen diagnostic (new path only)
    machine_config.json         — present if per-run localcfg was used

state/console/console.db — SQLite: runs, interpretations, batches
rawdata/<M>/mode_<n>/   — chunks; coupled only for md5-cell routing
```

## 2. Writers (pre-fix)

| # | Writer | Site | Entry shape | Dir creation | On failure |
|---|--------|------|-------------|--------------|------------|
| 2A | LEGACY sampling `RunManager._update_report_index` | app.py:6647 | FULL: + rawdata_config_md5/code_md5/analyzer_version/effective_analyzer_version; .md exists | start_run :6383 mkdir before subprocess | dir persists; no index entry |
| 2B | NEW generate `_run_generate_report` | app.py:9310/:9556 | IMPOVERISHED: md5/analyzer/effective ABSENT; report_file DANGLING (.md never written by report_engine — writer.py:203 writes only the summary; report_engine.py:353 docstring falsely claims ".md") | :9408 mkdir BEFORE engine/validation | dir persists (live case rv_20260612T064850Z, run gen_a09fa4a08ce6 failed in 24ms on manifest validation) |
| 2C | BATCH `_prepare_batch_gen_item`/`_finalize_batch_gen_item` | app.py:9639/:9824 | same as 2B | :9675 mkdir before worker | dir persists |
| 2D | IMPORT `import_reports` | app.py:10512 | writes NO index/latest at all; DB row lacks md5/version fields | copytree | partial copies possible |
| 2E | RETENTION pruner `_refresh_mode_manifests` | reports_retention.py:149 | FOURTH shape: only version/run_id/created_at/paths/rtp/quality; report_file UNCONDITIONAL .md claim (:184); skips summary-less dirs (:169) | n/a | n/a |
| 2F | `_tag_reports_stale` | app.py:1494 | adds underlying_removed to entries | n/a | n/a |
| 2G/2H | delete paths | app.py:6777/:10358 | remove entry + roll latest back | n/a | zombie handling exists |

`update_run`: legacy patches effective_analyzer_version (:6732); NEW paths omit it entirely (:9544-9554, :9878-9888).

**Concurrency: NO LOCK anywhere** — every writer does read-list → append → atomic-write; concurrent
batch finalizes lose entries (M14/mode_1: 16 dirs vs 4 index entries).

## 3. Readers

| Consumer | Site | Relies on |
|---|---|---|
| `GET /api/reports/{m}/{n}` report_versions | app.py:10222 | index; backfills md5/analyzer (NOT effective) from entry.summary_file at read time, in-memory only |
| `GET /api/reports/{m}/{n}/{v}` detail | app.py:10350 | DERIVES path from machine/mode/version (immune to stored-path rot) |
| `GET /api/reports/stale-count` | app.py:7645 | SQLite rows: rawdata_config_md5 / effective_analyzer_version → new-path rows (NULL effective) count "untagged", never stale/fixable |
| catalog report_count | app.py:2808 | counts raw version DIRS (incl. empty/failed) |
| `_build_machines_summary` / report-validate / cycle-detect / static-attrs | app.py:3800/:10922/:1687/:3465 | walk versions/*/player_impact_summary.json directly |
| `GET /api/runs/{rid}/report` | app.py:10203 | SQLite summary_file/report_file ("" markdown when .md absent) |
| Frontend rwtree report routing | app.js:1766 | report-validate (summary-direct) md5 map, not index |
| startup backfill | app.py:2563 | predicate excludes effective_analyzer_version as trigger → never fills it for new rows |

## 4. Legacy vs new shape diff (the user-hypothesis confirmation)

Legacy entries carry rawdata_config_md5 / rawdata_code_md5 / analyzer_version /
effective_analyzer_version + a real .md; BOTH new paths omit all four and claim a
nonexistent .md; import writes nothing; retention rebuilds a fourth shape. Fleet:
2,054 completed run rows, only 2 with effective_analyzer_version (both legacy).
The management layer logic did NOT change — the new producers feed it less.

## 5. Defect anchors (live evidence)

- A: dir-before-validation → empty dir rv_20260612T064850Z (M275/mode_1).
- B: report_count inflated — fleet 387 dirs vs 343 index entries.
- C: new-path entries lack md5/analyzer/effective; read-time backfill in-memory only.
- D: 261/343 entries' summary_file point into `.claude/worktrees/stoic-napier-f0ea00/`
  (dir exists but no longer a registered worktree — deletion bomb); canonical copies in main repo.
- E: update_run omits effective_analyzer_version → honesty-3 staleness blind.
- F: failed runs leave versions/<rv>/ + stale latest.json with index [] (M254/mode_7, M275/mode_7).

## 6. Disk sweep (2026-06-12, pre-repair)

387 version dirs vs 343 index entries; 15 empty dirs; 9 dirs without summary
(machine_config/progress litter); 0 entries whose summary_file missing (worktree still
on disk); 21 entries missing rawdata_config_md5; 10 dangling report_file claims.
Worst cells: M1/mode_1 (23 dirs / 12 entries), M14/mode_1 (16 / 4 — the lock race),
M275/mode_1 (3 / 2, one empty), M254+M275 mode_7 (latest.json with empty index).

## 7. Open questions (carried)

- Which writer produced latest.json-without-index on M254/M275 mode_7 (crash-interrupted
  sequence suspected; both paths write index+latest adjacently).
- M14's 12 unindexed dirs == the no-lock race (most named rv_*_rawdata_* = batch runs).
- 9 machine_config-only dirs are never pruned by prune_versions (skipped by :169) — now
  handled by the reconcile's no-summary class.
