# Ticket P3-1 — Bootstrap 419 per-machine manifest files

Phase 3 item 1 deliverable (the architecture proposal's "421 manifests"
target — 419 actual: 393 fleet + 26 synthesized variant parents). All
manifests pass the 11 validation rules from P2-A2 manifest_loader.

## Deliverables

- `scripts/generate_machine_manifests.py` — generator script.
- `slot_designer/configs/machine_manifests/<machine_id>.json` × 419.
- Updated `fresh_slotlab/analyzer/manifest_loader.py`:
  - `_extract_machine_ids`: added `machine` field as primary lookup
    (was only `machine_id`/`id`; actual `configs/machines.json` schema
    uses `machine`).
  - Rule 1: skip synthetic template manifests (those marked
    `_generator_notes.synthetic_template = True`).

## Strategy

Bootstrap with conservative defaults — operators review per-machine.

- **SC-Vanilla cluster (45 machines)**: 4 universal features wired,
  `console_diagnostic_complete: false` initially. Phase 3 Item 0
  (RTP gate verification) flips to `true` after empirical confirmation.
- **Other underlying machines (182)**: same defaults +
  `cluster_review_pending: true` notes flag.
- **Variants (166)**: `inherits_from: <underlying>.json`. Eager
  cascade per §5.5.5.
- **Synthesized underlyings (26)**: standalone templates so variants
  resolve correctly. Marked `synthetic_template: true`; Rule 1 skip
  carve-out.

## Verification

- 419 manifests load via `manifest_loader.load_manifest`.
- 166 variants resolve via `resolve_inheritance` to inherit underlying's
  `analyzer_features` and `rtp_integrity_contract`.
- Fleet-wide validation (393 manifests + 26 templates): 0 errors.
- P1-A1 canary: 23/23 GREEN (manifest changes don't affect PIA path).
- P2-A2 manifest_loader suite: 99 passed (no regression).
- Wave 2c + RTP gate + foundation suites: all GREEN.

## Out of scope

- Item 0 Day-1 verification (needs cached chunks per machine).
- Item 3 (wire `compute_effective_analyzer_version` to consult manifest).
- Items 4-9 (DB column, frontend, lint tools).
- Per-machine review and trigger-session pattern back-fill.
