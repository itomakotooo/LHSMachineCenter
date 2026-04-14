# Slot Lab Repository

This repository stores slot test tooling and report assets with a split between
temporary data and long-term, versioned outputs.

## Directory Layout

- `src/`: analysis and sampling code
- `configs/`: machine and sampling configs
- `state/`: local runtime metadata (SQLite index, locks)
- `cache/chunks/`: temporary chunk cache (size-bounded, evictable)
- `reports/`: long-term report assets (version-managed, non-ephemeral)
- `scripts/`: utility scripts (maintenance, import/export, cleanup)
- `tests/`: automated tests
- `fresh_slotlab/`: current scripts under migration
- `configs/classic_slots_guideline.md`: classic-slot quant guideline

## Data Lifecycle Rules

1. Chunk source data may be cached locally with an upper bound.
2. Chunks that are not yet consumed by a generated report must not be deleted.
3. Report and aggregated metrics are core assets and should be retained/versioned.
4. `runs` is temporary output only.

## Report Versioning Convention

For each machine/mode pair, keep:

- `reports/<machine>/mode_<id>/index.json` (append-only history index)
- `reports/<machine>/mode_<id>/latest.json` (pointer to current recommended version)
- `reports/<machine>/mode_<id>/versions/<report_version>/...`

## Git Tracking Boundary

Tracked:

- code, configs, report manifests and final report outputs

Ignored:

- local chunk cache, runtime DB/locks, temporary run artifacts
