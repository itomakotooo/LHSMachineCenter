# Commit A — adversarial review (coordinator self-review)

> The `impl-critic` agent hit **3 consecutive transient socket failures** (0 tokens, ~3s each), so the coordinator performed this review directly. Commit A is the lowest-risk commit in the phase (pure-additive, 0 existing files touched), so self-review is acceptable here. Behavior-changing commits (B+) route the adversarial pass through an independent agent (impl-critic retry, or general-purpose fallback) so independent review is preserved where it matters.

## Verdict: SAFE TO COMMIT (pending impl-tester green)
Commit A is **byte-identical by construction** (verified inert). One SERIOUS design-gap finding applies to **Commit C**, not Commit A.

## Critical check — INERTNESS: PASS
`grep play_type` across the repo matches only: the 8 new framework files, the new `tests/backend/test_play_type_framework.py`, and 4 `session_artifacts` md files. **No existing pipeline file** (`parser.py`, `player_impact_analyzer.py`, `feature_registry.py`, `versioning.py`, `manifest_loader.py`, …) imports or references the new package. The live analyzer path cannot reach the new code → Commit A cannot change runtime behavior → byte-identical guaranteed structurally (no golden-diff needed for A).

## Implementer's 3 self-flagged concerns — adjudicated
1. **PlayTypePlugin no-op `extract/reduce/emit` defaults** — ACCEPTABLE (minor). Mechanic-only plugins are real, but most play-type plugins will have display panels, so a forgotten override = silent empty panel. Mitigation: each concrete plugin's display role must be tested at B+. Not a blocker.
2. **`_topo_sort_plugins` silently skips MECHANIC_DEPS not in active set** — ACCEPTABLE (minor), documented. A subordinate (e.g. MultiSymbolCollection deps scatter_freespin) may legitimately run standalone if its dep didn't match this machine.
3. **frozen dataclass + `field(default_factory=frozenset)`** — NON-ISSUE. Correct Python (3.7+).

## NEW finding (SERIOUS) — resolve before Commit C; NOT a Commit-A blocker
**The detector has no per-SpinType ownership mechanism.** `detect_play_types` Step 3 sets `claimants = list(matching_plugins)` for EVERY observed ST — every plugin whose *machine-level* `ClaimSignature` matched becomes a claimant for *every* ST, then resolves to one global precedence-winner per ST. `_resolve_claimants` never inspects the ST. On a multi-play-type machine (M275: ST=140 paid / ST=126 freespin) both STs resolve to the SAME winner instead of ST=140→BCMBase, ST=126→BCMFreespin.
- **Root cause**: `ClaimSignature` is a machine-level predicate (paid/bonus field presence, §4.2-rev); it does not encode which ST a plugin owns. 04_v2 §4.6 presupposes "plugins claim a specific ST" but the per-ST claim mechanism was never specified.
- **Severity nuance**: per 04_v2 deliverable 14, every active accumulator sees every round via `on_round` and self-filters, so this does NOT corrupt core round processing. It DOES produce a wrong `st_map` → wrong config record + wrong display-panel routing (`REQUIRES_PLAY_TYPES`).
- **Inert in Commit A** (empty registry → empty `st_map`; the multi-plugin path is unreachable until concrete plugins exist).
- **Action (Commit C prerequisite)**: design the per-ST ownership mechanism (options: plugins declare an ST-population predicate; or `matches()` evaluated per-ST-bucket; or `st_map` derived from each accumulator's self-claimed STs after a detection pass). Validate against M275/M279 (multi-play-type) real rawdata.

## Minor
- `ClaimSignature.matches()._is_paid` uses `(r.get("CostCredits") or 0) > 0` — less defensive than the existing `round_classification.is_paid_round` (which `float()`s under try/except). Non-numeric CostCredits would `TypeError`. Low risk on pilots (numeric); align with `is_paid_round` robustness when wiring real data at Commit B.
- `per_machine_config_hash()` stability / config round-trip: delegated to impl-tester's tests.

## Process note
`impl-critic` unavailable (3× socket failure this session). Behavior-changing commits (B/C) re-attempt impl-critic (infra may recover) or use a general-purpose agent so independent adversarial review is preserved.
