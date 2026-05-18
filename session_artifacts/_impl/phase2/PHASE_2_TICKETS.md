# Phase 2 — Ticket Index

> Source: `session_artifacts/_arch/08_handoff.md §4 Phase 2` + `04_architecture_proposal_v5.md §6.2` + `07_decision_v5.md P1`.
>
> **Phase 2 goal**: slice the 8176-line `player_impact_analyzer.py` into base + feature plugins; define `AnalyzerFeature` Protocol + `feature_registry`; onboard 12 known-complex machines as forcing function; build RTP integrity gate (Layers 1-4) in warn-only mode.
>
> Phase risk: **HIGH**. Estimated 12-16 days per handoff. Largest phase of the project.
>
> Dependencies: Phase 1 deliverables landed (canonical helpers in `fresh_slotlab/` ready for plugin code to call).

---

## Execution order — 6 waves

| Wave | Tickets | Rationale |
|---|---|---|
| **2a — Foundation** | P2-A1, P2-A2 | Framework files: AnalyzerFeature Protocol + versioning.py + feature_registry skeleton. Other Phase 2 work depends on this. |
| **2b — Core carve** | P2-B1, P2-B2, P2-B3, P2-B4 | Extract `analyzer/core/` (4 files: parser / aggregator / writer / cli). Replaces in-PIA monolith. |
| **2c — Universal features** | P2-C1×4 (RTP / Spin-type-split / Payout-id-top-N / Bankruptcy) | 4 features used by ALL machines; carve first. |
| **2d — Cluster-shared features** | P2-D1×9 (per `02_taxonomy.md` cluster catalog) | 9 features shared across multiple machines; carve in dependency order. |
| **2e — Bespoke + RTP gate** | P2-E1 RTP integrity gate + P2-E2..E13 (12 forcing-function machines: M21/M260/M268/M279/M274/M113/M11/M250/M108/M65/M67/M120) | Per-machine bespoke features + the gate. Each machine = potentially 1 bespoke + integration tests. |
| **2f — Example 6 + cleanup** | P2-F1 Example 6 workflow M250 end-to-end demo + per-cluster regression tests | Demonstrate the architecture; cleanup; ship. |

---

## Wave 2a (READY — start here)

### P2-A1 — Foundation files: AnalyzerFeature Protocol + versioning.py + feature_registry skeleton

**Brief**: `session_artifacts/_impl/phase2/01_foundation_files/00_ticket.md`

Smallest standalone Phase 2 ticket. Lays the contract surface that all subsequent feature/carve work imports from.

**Deliverables**:
- `fresh_slotlab/analyzer/__init__.py` (new package)
- `fresh_slotlab/analyzer/feature_protocol.py` — `AnalyzerFeature` `@runtime_checkable` Protocol per `04_v5 §5.2`
- `fresh_slotlab/analyzer/versioning.py` — `compute_effective_analyzer_version(machine, mode)` per `04_v5 §4.1`
- `fresh_slotlab/analyzer/feature_registry.py` — `ALL_FEATURES: list[AnalyzerFeature] = []` skeleton + `register(feature)` helper
- 4 stub features for smoke tests (no real logic; just verify the registry works)

**Risk**: LOW. Foundation files; no behavior change for production. Established by tests.

### P2-A2 — Manifest loader + schema

**Brief**: TBD (write when starting)

Implements `manifest_loader.py` reading `slot_designer/configs/machine_manifests/<M>.json` per `04_v5 §5.5`. Phase 3 will write the 421 manifests; Phase 2 just needs the loader interface.

---

## Wave 2b — Core carve (after 2a)

(Tickets TBD; each carves one of the 4 core files from PIA into `fresh_slotlab/analyzer/core/`.)

---

## Wave 2c — Universal features (after 2b)

(4 tickets, one per universal feature.)

---

## Wave 2d — Cluster-shared features (after 2c)

(9 tickets per `02_taxonomy.md`.)

---

## Wave 2e — Bespoke + RTP gate (after 2d)

(13 tickets: 1 for `rtp_integrity.py` (Layers 1-4) + 12 forcing-function machines.)

---

## Wave 2f — Example 6 + cleanup

(2-3 tickets.)

---

## Status tracker

| Ticket | Brief | Status | Commit |
|---|---|---|---|
| P2-A1 (FIRST) | [01_foundation_files/00_ticket.md](01_foundation_files/00_ticket.md) | **READY** | — |
| P2-A2 | TBD | PENDING | — |
| P2-B1..B4 | TBD | PENDING | — |
| P2-C1..C4 | TBD | PENDING | — |
| P2-D1..D9 | TBD | PENDING | — |
| P2-E1..E13 | TBD | PENDING | — |
| P2-F1+ | TBD | PENDING | — |

---

## Phase 1 follow-ups still open (tracked here for visibility)

None — all Phase 1 follow-ups CLOSED by P1-D1 commit `c4b3e26`. Pure-function extraction (P1-C2) remains an OPTIONAL future ticket not blocking Phase 2.
