# Architecture Proposal v2 — rawdata → analyzer → console pipeline (Wave 2 iteration)

> Wave 2 v2 deliverable from `arch-designer`. **Single rewrite** integrating:
> - 5 user updates from `00_brief_v2_addendum.md`
> - 11 must-resolves from `05_critique.md`
> - 4 spec gaps from `06_validation.md`
> - 5 pre-Phase-1 blockers from `01_pipeline_map.md §5` (mapper open questions #1, #3, #5, #7, #8)
>
> Reuses what v1 got right (hash composition algorithm, manifest schema mechanics, `AnalyzerFeature` Protocol). **Rewrites** v1's §3/§5/§6 framing where the user explicitly rejected the "84% clean cluster + 12 outliers" tier model. Adds a new §9 covering RTP integrity enforcement per addendum §1.4.
>
> Citations: every load-bearing claim points to a Wave 1 file:section. No design without observation.
>
> **Date**: 2026-05-15
> **Brief**: `session_artifacts/_arch/00_brief.md` + `session_artifacts/_arch/00_brief_v2_addendum.md` (the addendum supersedes specific points)
> **v1**: `session_artifacts/_arch/04_architecture_proposal.md`
> **Repo root**: `User_Managerment_GPT/`

---

## §1 Problem statement (restated for v2 post-philosophy-shift)

The production console pipeline is structurally sound at the heavy edges — `create_app` factory shared by both consoles (`01 §4` verdict "thin shell"); `parse_chunk_response`, `chunk_index`, `rawdata_index` single-sourced; frontend bundle served to both real (8877) and virtual (8878). The architectural rot is concentrated at three layers: **version stamping**, **schema contract enforcement**, and **per-machine-correctness verification**.

v1 framed this as "84% clean cluster (~213 machines fit 6 super-clusters) + 12 outliers". The user rejected that framing (addendum §1.5):

> "12 个机台不是我提供的,估计是之前你自己归纳的,那估计就有很大的问题,比如其实所有的机台都有可能有这种程度的复杂性。所以你要做的不是剩下的机台都是 ok 的,而是保持警惕。"

The reasoning is empirical: the surface signals taxonomy used (logicClassNames, schema fingerprint, declared rule reliance) only show what's been **encoded or surfaced today**. Real-world examples of "looked normal until investigated":

- **M274**: 4.87% RTP attribution leaked to `_unattributed_st139` fallback before BCMCycleAnchorRule was enabled (memory `feedback_invariant_with_fallback_hides_drift.md`).
- **M250**: 100% RTP leak only discovered after deeper analysis.
- **M268 / M260 / M264**: 70-90% leak; **fleet-wide** 55 of 117 cached BCM (m,mode) pairs had >0.5% fallback.
- Even SC-Vanilla membership (`02 §4.2`'s largest super-cluster) is "machine declared `{NormalRTPPreProcessor, NormalSpinGenerator, NormalSpinValidator}` and emitted only the 17-key base envelope" — NOT proof the analyzer's default path produces correct attribution for it.

v2's premise: **every machine is potentially unique. Sharing is opt-in via manifest declaration. Each machine's manifest must be backed by an explicit RTP integrity check that proves its declared composition actually produces correct RTP for that machine.**

### §1.1 Five concrete pain points (each cited from Wave 1)

These are the pain points v1 identified; v2 keeps them but reframes how they're resolved.

1. **Universal `analyzer_version` stamp invalidates 1007 (machine, mode) pairs on any byte change** —
   `compute_analyzer_version()` at `fresh_slotlab/player_impact_analyzer.py:2141` SHA256s the entire 8,176-line file. Per `03 §3.3` live DB measurement, 2030 completed runs across 1007 distinct (machine, mode) pairs get flagged `stale_analyzer` by `/api/reports/stale-count` (`app.py:5694`) on any comment-only edit. **v2 fix**: per-machine `effective_analyzer_version` composed from base hash + feature hashes the machine declares (§4).

2. **Schema renames silently break 17 frontend renderers** — `03 §4.3` tabulates ~30 schema fields × 17 renderers (`app.js` 14 + `pure.js` 3). Only `payouts_by_spin_type` family has frontend fallback. **v2 fix**: explicit `SCHEMA_VERSION` per feature + frontend renderer registry with declared fallback rules (§5.3 + §5.4 SCHEMA_VERSION policy).

3. **Real-fleet hash is upstream, virtual hash is local** — `03 §3.4` measured 421 entries in `configs/machines.json` get `codeSummaryMd5` from upstream `/MachineConfigMd5` (`machine_variants.py:336`); `compute_code_md5(machine_name)` at `slot_designer/core/backend/machine_version.py:109` only feeds 6 virtual entries. Editing `core/engine/symbol.py` flips 6 virtual hashes and 0 real ones (`03 §5.1`). **v2 stance**: this asymmetry is preserved (out of scope per addendum §3); per-virtual-machine isolation from core-engine changes deferred to spec-format work.

4. **Duplication concentrated in md5 + summary-patch + session-CI + inference triggers** — `01 §4` itemizes **six** duplications: (1) md5 lookup, (2) md5 patch into summary, (3) session-CI half-width, (4) t-critical table, (5) inference-script trigger, (6) schema fingerprint. **v2 fix**: Phase 1 extracts ALL SIX (v1 only specced 1-4; see §6 below).

5. **Module globals + import-time side effects are latent suicide bombs** — `03 §4.1` enumerates 11 references to `RAWDATA_ROOT` in `app.py`, 33 module globals in the analyzer, plus `virtual_app.py:201`'s import-time `app = build_virtual_app()` side effect. Memory `feedback_subprocess_import_suicide_and_module_globals.md`. **v2 fix**: Phase 1 (a) FastAPI dependency injection for `RAWDATA_ROOT` and similar singletons, (b) move `app = build_virtual_app()` to lazy/explicit construct, (c) extend regression test coverage from `virtual_registry` to `virtual_app` itself (§6).

### §1.2 NEW pain point #6 — silent fallback-bucket RTP leak fleet-wide

Memory `feedback_invariant_with_fallback_hides_drift.md`: "55 of 117 cached BCM (m,mode) pairs have >0.5% RTP falling into the `_unattributed_st<N>` fallback bucket; M250 100%, M268/M260/M264 70-90%, M163/M147 ~35%". `02 §3.5.1` confirms only 13 of 421 machines have explicit `RoundWinRule` registration even though `02 §3.5.2` infers ~35-40 machines need `detect_cycle_peak` and ~25 need `is_wild_nudge_round`.

This is the same failure mode as #1-#5 but along a different axis: **the analyzer produces a "GREEN" number for every machine today, even when the per-pay-id attribution is structurally wrong, because the invariant `sum(pid_win) == chunk_win` is force-closed by an `_unattributed_*` synthesizer**. v1 did not list this as a pain point. v2 promotes it to a top-level constraint (constraint S per addendum §1.4) and an enforcement mechanism for manifest correctness (§9 below).

### §1.3 Headline blast-radius framing (per addendum §1.1, replaces v1's "10×" claim)

v1 led with "10× available reduction". Critic Concern 1 + Q6 showed this is misleading: 5 of 7 brief §3 commits land in `features/payouts_by_spin_type.py`, which is universal — no reduction realized. User accepted Critic's framing (addendum §1.1).

v2 replaces the single-headline reduction claim with the **per-change-class blast table** below. Each row names a class of change; the universal-feature-edit class is explicitly listed as **1× (no reduction by design)** so the design is honest about what it does and doesn't fix.

| Change class | Blast under current architecture | Blast under proposal | Reduction |
|---|---|---|---|
| **Per-cluster feature edit** (e.g., adding BCM `_unattributed_st` cleanup rule) | 421 machines | 12-30 machines (one cluster) | 12-30× |
| **Per-machine bespoke fix** (e.g., M21 Buffalo-counter tweak; M279 combo logic) | 421 machines | 1 machine | 421× |
| **Novel machine onboarding** (M400 with new feature plugin) | 421 machines (analyzer touched) | 1 machine (only declarant) | 421× |
| **Universal feature edit** (e.g., adding a new field to a feature used by every machine; renaming a `bankruptcy_simulation` field) | 421 machines | 421 machines | **1× (no reduction by design)** |
| **Frontend renderer plugin update** | varies (silent break risk per `03 §4.3`) | machines using that renderer; schema-version gated | varies |
| **Bespoke-plugin lift for a "vanilla" machine that turned out non-vanilla** (e.g., a previously-SC-Vanilla machine that RTP integrity check flags as broken) | Required per-machine code added to monolith → 1007 (m,mode) flagged stale | Add per-machine bespoke feature; only that machine flagged | 421× |
| **Schema rename inside a universal feature** (e.g., `hit_rate_pct → hit_rate` in `payouts_by_spin_type`) | 421 machines + silent renderer break | 421 machines + explicit fallback rule applied | 1× invalidation but 0× silent break |

**Universal-feature-edit class is named honestly**: 5 of 7 brief §3 commits fall here, so the dominant historical change pattern still produces fleet-wide invalidation. That's by design — universal features touch every machine. The proposal does not fake reduction for changes that affect every machine.

The reduction the proposal delivers is for the **other** classes — and per Critic Q6, those classes are not the historical ones. v2's defensibility relies on the future change pattern looking different from history, because v2's mechanism makes "carve a per-cluster or per-machine feature instead of editing the universal one" the path of least resistance. Today there's no incentive to carve.

---

## §2 Design alternatives

Three alternatives remain. v2 keeps the same set as v1 (A / B / C) but rewrites the framing so the choice axis is **"how strictly does the architecture treat every machine as potentially unique?"** rather than "how aggressively to slice analyzer_version".

### §2.1 Alternative A — Per-machine manifests + sliced analyzer + RTP integrity gate (recommended)

**Core idea**: Every one of the 421 machines has an explicit manifest declaring (a) which feature plugins it uses, (b) which round-win rules it uses, (c) which RTP integrity contract it must satisfy. The analyzer is sliced into `core/` (universal orchestration) + `features/` (opt-in). The per-machine effective analyzer version composes from base + the features the manifest declares. Plus an RTP integrity check (§9) that runs on every fleet-wide pull and emits an explicit per-machine error if any machine cannot be correctly attributed under its manifest.

**Key change vs v1**: NO default-cluster tier. Vanilla machines have **short** manifests (they declare the small set of features they use); complex machines have **long** manifests. Quantitative difference only — no machine is "the default". Sharing is opt-in via plugin composition (e.g., `analyzer_features: [payouts_by_spin_type, bankruptcy_simulation, multiplier_profile]` is a "shared path" with whichever other machines happen to declare the same set).

**File tree sketch** (additions marked `(new)`):

```
fresh_slotlab/
  player_impact_analyzer.py        # main() + parse_chunk_response orchestration (slim, <500 LoC post-Phase-2)
  identity_stamp.py                # (new, Phase 1) extracted md5/summary-stamp duplication
  session_ci.py                    # (new, Phase 1) extracted session-CI helpers
  inference_trigger.py             # (new, Phase 1) extracted inference-script trigger (was duplicated)
  upstream_schema_fingerprint.py   # (new, Phase 1) extracted schema-fingerprint helper
  analyzer/
    __init__.py
    versioning.py                  # (new) hash composition primitives
    feature_registry.py            # (new) explicit registration of analyzer features (Critic Q4, Validator §3.4)
    core/                          # always-invoked (universal) — orchestrator + summary writer + chunk merge
      base_pipeline.py
      chunk_aggregation.py
      summary_writer.py
      schema_gate.py               # _REQUIRED_ROUND_FIELDS lives here (Critic Q17)
    features/                      # opt-in features; each module hashes itself
      _base.py                     # AnalyzerFeature ABC + REQUIRES + manifest hooks
      payouts_by_spin_type.py
      reel_marginal_by_spin_type.py
      bankruptcy_simulation.py
      bonus_chain_dynamics.py
      collect_mechanic.py
      multiplier_profile.py
      wild_nudge_classification.py
      cycle_peak_detection.py
      topdollar_settlement.py
      wheel_selector_type2.py
      lock_symbol_handling.py
      lock_lines_handling.py
      pay_id_suffix_attribution.py
      ...
      bespoke_m21_buffalo.py
      bespoke_m260_buffs.py
      bespoke_m279_combo.py
      ... (extensible; no fixed count)
  round_classification.py          # unchanged (still the primitive library)
  round_win.py                     # unchanged (existing RoundWinRule ABC + RULE_REGISTRY)
  chunk_index.py                   # unchanged
  rawdata_index.py                 # unchanged
  rtp_integrity.py                 # (new, Phase 4) constraint S enforcement

slot_designer/configs/
  machine_manifests/               # (new) per-machine manifests, one file each
    M1.json
    M14.json
    M15.json
    ...
    M400.json                      # added by Phase-6+ for novel machines
  manifest_schema.json             # (new) JSON Schema validation for manifests

slot_designer/machines/<M>/
  (existing per-machine spec/weights/plugins; UNCHANGED per addendum §3)
```

**Key Protocol interfaces** — Python ABC sketch (additions vs v1 marked `[v2]`):

```python
# fresh_slotlab/analyzer/features/_base.py (NEW)
from abc import ABC, abstractmethod
from typing import Any, ClassVar
import hashlib
from pathlib import Path

class AnalyzerFeature(ABC):
    """Versioned, opt-in slice of analyzer functionality.

    Each subclass module corresponds to one feature module file under
    fresh_slotlab/analyzer/features/. The file's own bytes are hashed
    for compute_hash().
    """
    FEATURE_ID: ClassVar[str] = ""              # stable string; never renamed
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = () # summary keys this feature WRITES
    SCHEMA_VERSION: ClassVar[int] = 1           # bumped on breaking field rename
    REQUIRES: ClassVar[tuple[str, ...]] = ()    # [v2] feature_ids this feature reads (Critic Q2)
    RTP_CONTRIBUTION: ClassVar[bool] = False    # [v2] does this feature affect win attribution? (§9)

    @abstractmethod
    def extract(self, parse_state, chunk_dict) -> dict: ...

    @abstractmethod
    def reduce(self, prev_acc, this_acc) -> Any: ...

    @abstractmethod
    def emit(self, final_acc, summary: dict) -> None: ...

    @classmethod
    def compute_hash(cls) -> str:
        src = Path(__file__).resolve()
        return hashlib.sha256(src.read_bytes()).hexdigest()[:12]


# fresh_slotlab/analyzer/feature_registry.py (NEW; addresses Critic Q4 + Validator §3.4)
"""Explicit registry of analyzer features.

Avoids implicit file-system scan. New features must be imported here
and registered. The registry is the single source of truth for:
- which features exist
- their FEATURE_ID → class mapping
- order-resolution for REQUIRES (topological sort)
"""

ALL_FEATURES: dict[str, type[AnalyzerFeature]] = {}

def register(feature_cls: type[AnalyzerFeature]) -> type[AnalyzerFeature]:
    ALL_FEATURES[feature_cls.FEATURE_ID] = feature_cls
    return feature_cls

def feature_dependency_order(feature_ids: list[str]) -> list[str]:
    """Topological sort by REQUIRES. Raises if cycle or missing dep."""
    ...


# fresh_slotlab/analyzer/versioning.py (NEW)
def compute_base_analyzer_version() -> str:
    """SHA256 of fresh_slotlab/analyzer/core/*.py only (orchestration + summary writer)."""

def compute_feature_hashes() -> dict[str, str]:
    """For each registered feature, hash its module file. Cached at startup."""

def compute_effective_analyzer_version(
    *, base_hash: str, feature_hashes: dict[str, str],
    machine_features: list[str], mode: int | None = None,  # [v2] mode dimension (Critic Q11)
) -> str:
    """Per-machine, optionally per-mode hash composition.

    Algorithm (kept from v1, validated clean by Wave 3):
        h = sha256(base_hash)
        for fid in sorted(set(machine_features)):
            h.update(b"\\x00" + fid + b"=" + feature_hashes[fid])
        if mode is not None:
            h.update(b"\\x00mode=" + str(mode))
        return h.hexdigest()[:12]
    """
```

**Manifest schema** — full schema with explicit RTP contract (§5):

```json
{
  "machine_id": "M274",
  "manifest_version": 1,
  "spin_type_convention": {"paid": [140], "bonus": [139]},
  "feature_tags": ["BCM", "Wheel"],
  "round_win_rules": ["bcm_cycle_anchor_m274"],
  "analyzer_features": [
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "bankruptcy_simulation",
    "bonus_chain_dynamics",
    "collect_mechanic",
    "multiplier_profile",
    "cycle_peak_detection"
  ],
  "bcm_target_feature": "ListRewardWheel",
  "trigger_session_pattern": null,
  "modes_supported": [1, 5, 7],
  "rtp_integrity_contract": {
    "fallback_share_threshold_pct": 0.5,
    "expected_paid_st": [140],
    "expected_bonus_st": [139],
    "required_attribution_anchors": ["_bcm_cycle", "5801"]
  }
}
```

**Pros** (grounded in Wave 1):

- **Implements addendum §1.5 philosophy** — every machine has an explicit manifest. Sharing is opt-in. No default cluster tier.
- **Implements addendum §1.4 constraint S** — manifest declares RTP integrity contract; §9 enforces it on every fleet-wide pull.
- **Realizes the blast-radius profile from §1.3** — the change classes that have natural per-machine or per-cluster scope get the reductions; the universal class stays at 1×.
- **Backward-compatible by addendum §1.2** — clean break; no historical preservation required; 2030 existing runs can be invalidated.
- **Formalizes the existing `RoundWinRule` pattern** (`round_win.py:102` RULE_REGISTRY, `02 §3.5.1` 13 machines registered) rather than introducing a parallel one. Memory `reference_round_win_rule_architecture.md` validates the pattern.
- **Solves md5/summary-patch duplication** (`01 §4`) via Phase-1 shared primitives. v2 covers all 6 dups (v1 covered 4).
- **Plugin discovery is explicit** (Critic Q4 + Validator §3.4) via `feature_registry.ALL_FEATURES` registration.
- **Plugin dependencies are declared** (Critic Q2) via `AnalyzerFeature.REQUIRES`; topological sort prevents silent cross-feature accumulator collisions.

**Cons**:

- **Manifest accuracy is load-bearing**. RTP integrity check is the safety net (§9) — if every machine's manifest must back its claim with a passing RTP check, the surface area is larger than v1's "warn if inconsistent". v2 makes drift detection a **strict error**, not a warning (resolves Critic Concern 3 + §7.4 open question; see §9.3).
- **Onboarding regression for the simplest cases**: a brand-new "vanilla" machine still needs a manifest file. v2 accepts this — the manifest entry is short (~10 lines JSON) and it forces the operator to think about which features apply. Addendum §1.5 makes this explicit: "Vanilla machines have short manifests; complex machines have long manifests."
- **Per-machine manifests = 421 files** (instead of v1's central+per-machine hybrid). Bigger filesystem surface; mitigated by JSON Schema validation + bulk tooling. v2 picks per-machine files (Option 5.5b from v1) because per-machine PR isolation is the most important property under addendum §1.5's "every machine potentially unique".

**Migration cost estimate**: **MEDIUM-HIGH**. Slicing the analyzer monolith is still the biggest lift; adding 421 per-machine manifests + RTP integrity contract is new. Backward-compat **dropped** per addendum §1.2 (clean break — large simplification of phase 3).

### §2.2 Alternative B — Lightweight per-feature SCHEMA_VERSION sidecar (smallest change)

**Core idea (unchanged from v1)**: Leave `compute_analyzer_version()` exactly as it is. Add a `schema_versions: {feature_id: int}` field into the summary JSON. Frontend renderers consult this map for fallback decisions.

**Why this remains a viable alternative**: it's the smallest change that addresses pain point #2 (schema rename silence). However, addendum §1.4 + §1.5 mean B is **insufficient** because:
- It does not provide per-machine RTP integrity (the addendum's hard constraint S).
- It does not allow per-machine isolation of bespoke logic.
- It does not address the dominant pain point (universal `analyzer_version` blast) — same critique as v1.

**v2 verdict**: B is REJECTED because addendum §1.4 makes it non-viable. The RTP integrity check (constraint S) requires manifests to declare per-machine contracts, which B explicitly doesn't introduce.

### §2.3 Alternative C — Full per-machine analyzer plugin tree (most aggressive)

**Core idea (unchanged from v1)**: Every machine has `slot_designer/machines/<M>/analyzer_plugin.py` inheriting a thin `BaseChunkAnalyzer` class.

**Why C is REJECTED in v2** — v1's rejection still stands and the v2 user updates do NOT push toward C:
- Addendum §1.5 says "sharing is opt-in via manifest", NOT "no sharing". C eliminates sharing wholesale. That's not what the user asked for.
- 408 of 421 machines today have no explicit per-machine code (`02 §3.5.1` shows 13 with rules, 408 default). C forces shim files for all 408 — that's the parallel-impl anti-pattern flagged by memory `feedback_no_parallel_panel_impl.md` (cited in v1, still valid).
- Per-machine plugins lose the natural sharing C couldn't recover (e.g., M152/M153/M186/... all need the same BCM cycle peak detection; under C they each re-declare it).

Addendum §1.5 explicitly: "Plugin composition is the contract, not the cluster membership." C eliminates composition by forcing per-machine plugins. A's composition model is exactly what addendum §1.5 wants.

### §2.4 Comparison table

| Criterion | A (per-machine manifests + sliced analyzer + RTP gate) | B (sidecar) | C (per-machine plugins) |
|---|---|---|---|
| Implements addendum §1.5 philosophy (every machine potentially unique; opt-in sharing) | YES (manifest + opt-in composition) | NO (no per-machine declaration) | OVERSHOOTS (no sharing) |
| Implements addendum §1.4 constraint S (RTP integrity gate) | YES (§9 below) | NO | PARTIAL (can be bolted on per machine) |
| Solves `analyzer_version` blast for per-cluster + per-machine changes (`03 §3.3`) | YES (composes per-machine) | NO | YES |
| Solves universal feature-edit blast (the dominant historical pattern) | NO by design (honest about 1×) | NO | NO |
| Solves schema-rename silence (`03 §4.3`) | YES (versioned + registry) | YES (explicit version map) | YES |
| Solves md5/summary-patch + inference-trigger + schema-fingerprint dup (all 6 of `01 §4`) | YES (Phase 1 all 6) | NO | PARTIAL |
| Solves module-global suicide bombs (`03 §4.1`) | YES (Phase 1 + virtual_app lazy-init) | NO | NO |
| Backward-compat for 2030 existing runs (`03 §3.3`) | N/A — clean break per addendum §1.2 | YES | HARD |
| Onboarding cost for new vanilla machine | 1 file (machines.json) + 1 manifest (~10 lines) | 1 file (machines.json) | 1 plugin file + 1 manifest |
| Onboarding cost for new complex machine (M400-class novel) | 1 features/module + 1 manifest + 1 machines.json row | requires editing monolith | 1 plugin file + 1 features/ shared + 1 manifest |
| LOC delta estimate | +3,500 (analyzer slice + manifests + RTP gate + Phase 1 dedup) | +250 | +12,000 |
| Migration risk | MEDIUM-HIGH | LOW | HIGH |
| Heavy outlier handling (M260, M279, M250, M21) | Bespoke feature modules; manifest declares them; RTP gate verifies | No mechanism | Plugin file per machine |
| Resolves `_unattributed_st*` fallback-bucket silent leak (memory) | YES — RTP gate makes it an error (§9) | NO | PARTIAL |
| Resolves Critic 11 must-resolves | YES (each addressed in v2 §3-§9) | partial 3 of 11 | partial 5 of 11 |

---

## §3 Recommended design — Alternative A v2

**Pick: Alternative A v2** (per-machine manifests + sliced analyzer + RTP integrity gate + 6-dup Phase-1 + addendum-driven philosophy shift).

**Reasoning** (cited from Wave 1 + addendum):

1. **A v2 implements addendum §1.5 philosophy** — the user explicitly rejected v1's "84% clean cluster + 12 outliers" tier framing. A v2 makes every machine carry an explicit manifest; sharing is opt-in via the feature_ids the manifest lists. There is no "default cluster" anymore. Two machines that both declare `{base, freespin_v2}` are on a shared path *because they both declared it*, not because they were classified into the same tier.

2. **A v2 implements addendum §1.4 constraint S** — RTP integrity becomes the **enforcement mechanism** for manifest correctness. Per §9 below, the integrity check runs on every fleet-wide pull, and any machine whose manifest does not produce correct RTP gets an explicit per-machine error. The proposal is honest that not every machine will have full plugin coverage on day one — but the gate refuses to silently emit wrong numbers for those machines (vs today's `_unattributed_st<N>` silent leak per `feedback_invariant_with_fallback_hides_drift.md`).

3. **A v2 reuses what Wave 3 validated** — Wave 3 (critic + validator) approved v1's hash-composition algorithm (Critic §6, Validator §4.6 "no regression cases"), manifest schema mechanics (Validator §2 walks 7 cases through cleanly), and the `AnalyzerFeature` Protocol. v2 keeps these unchanged and addresses the 11 must-resolves + 4 spec gaps + 5 pre-Phase-1 blockers via targeted additions (§4 mode dimension, §5 SCHEMA_VERSION policy + REQUIRES + registry, §6 retro-fit ordering with 12 machines as Phase 2 forcing function, §9 RTP gate, §7 open questions reduced).

4. **A v2 addresses Critic Concern 1 honestly** — the universal-feature-edit class stays at 1× reduction by design (§1.3 table). v2 names this class explicitly so the proposal is defensible against "the historical change pattern is mostly universal features and you don't reduce that". The honest answer: yes, that class doesn't reduce; the proposal's value is in *the change classes that natural per-machine or per-cluster scoping affords*, which become the path of least resistance once mechanisms exist.

5. **A v2 addresses Critic Concern 5 + Validator §3.1 by making 12 known-complex machines the Phase 2 forcing function** (addendum §1.3). Phase 2 onboards M21, M260, M268, M279, M274, M113, M11, M250, M108, M65, M67, M120 under per-machine plugin path **before the framework is committed**. If a machine doesn't fit, the framework iterates *before* downstream phases lock it in.

6. **A v2 addresses Critic Concern 3 + §7.4** by making manifest drift a **strict error** (§9.3). This is enabled by addendum §1.2's clean-break authorization: we don't need to support the existing 22+ silently-broken BCM machines through a transition window — they get errored out and re-onboarded under the new architecture.

7. **C is rejected** as in v1 — overshoots. The addendum updates push toward opt-in composition, not no-composition. **B is rejected** as in v1 + does not satisfy constraint S.

The remaining sections specify A v2 in detail.

---

## §4 Hash composition rules

(v1's algorithm validated cleanly by Wave 3 — kept. v2 adds the mode dimension per Critic Q11 and clarifies the per-change-class table per addendum §1.1.)

### §4.1 The composition algorithm (unchanged structure; mode dimension added)

```python
# fresh_slotlab/analyzer/versioning.py (NEW)

def compute_base_analyzer_version() -> str:
    """SHA256 of fresh_slotlab/analyzer/core/*.py — universally-invoked code only.
    Replaces compute_analyzer_version() at player_impact_analyzer.py:2141.
    Length: 12 hex chars (matches legacy)."""

def compute_feature_hashes() -> dict[str, str]:
    """For each module registered in feature_registry.ALL_FEATURES,
    return {feature_id: short_hex_hash}. Computed at startup."""

def compute_effective_analyzer_version(
    *, base_hash: str,
    feature_hashes: dict[str, str],
    machine_features: list[str],
    mode: int | None = None,                     # [v2] per-mode dimension
) -> str:
    """Per-machine (optionally per-mode) effective hash.

    Composition (matches v1 algorithm, validated by Wave 3):
      h = sha256(base_hash)
      for fid in sorted(set(machine_features)):
        h.update(b"\\x00" + fid + b"=" + feature_hashes[fid])
      if mode is not None:
        h.update(b"\\x00mode=" + str(mode))
      return h.hexdigest()[:12]

    The mode dimension addresses Critic Q11: a machine may declare
    different analyzer_features for different modes via manifest.modes_supported
    + per-mode override. Without mode, the legacy 1007 (m,mode) dedupe at
    /api/reports/stale-count collapses to 421 (m,) dedupe.
    """
```

The **per-(machine, mode) effective version** is:
```
effective_analyzer_version(M, mode) =
    sha256( base_hash ||
            "\\x00".join(f"{fid}={feature_hashes[fid]}" for fid in sorted(manifest[M, mode].analyzer_features)) ||
            f"\\x00mode={mode}"
          )[:12]
```

Manifests can declare per-mode feature lists for machines with mode-specific behavior (per memory `user_testing_machine.md`: "mode 2/5 RTP 不可精准监控" — different modes might want different feature sets). When per-mode features aren't specified, all modes inherit the machine-level list.

### §4.2 Per-change-class blast table (replaces v1's "10× reduction" framing per addendum §1.1)

The honest blast profile of the proposal:

| Change class | Wave 1 evidence | Today blast | Post-mig blast | Reduction |
|---|---|---|---|---|
| Per-cluster feature edit (e.g., BCM cleanup rule lands in `features/cycle_peak_detection.py`) | `02 §6.5` shows 28 BCM-21k machines; `04 §4.2 ex 3` (v1) | 421 (m,mode) | 28 machines × N modes ≈ 70 (m,mode) | 12-15× |
| Per-machine bespoke fix (e.g., `features/bespoke_m21_buffalo.py` edit) | `02 §5.1` 12 heavy outliers individually scopable | 421 | 1 machine × N modes ≈ 3-4 (m,mode) | 100-421× |
| Novel machine onboarding (M400-class) | Validator §2.7 case | 1007 (m,mode) (analyzer source change) | 1 machine | 1007× |
| **Universal feature edit** (e.g., `features/payouts_by_spin_type.py` rename) | 5 of 7 brief §3 commits | 1007 (m,mode) | 1007 (m,mode) — feature declared by every manifest | **1× by design** |
| Frontend renderer plugin update | `03 §4.3` schema renames; `7e5fe32` precedent | 17 renderers × silent break risk | machines using that renderer × 0 silent breaks (registry-gated) | varies + safety improvement |
| Bespoke-plugin lift for a previously-vanilla machine (e.g., M65 was thought vanilla but RTP gate flags it) | Addendum §1.5 + memory `feedback_invariant_with_fallback_hides_drift.md` | Required adding per-machine code → 1007 stale | New `features/bespoke_m65.py` + manifest change → 1 machine affected | 421× |

This table goes into the proposal's elevator pitch instead of "10× reduction". Each row is independently defensible against Wave 1 evidence.

### §4.3 Worked examples — invalidation radius (carried from v1 §4.2, kept as illustrative)

#### Example 1: comment-only edit to `features/bankruptcy_simulation.py`
- `feature_hashes["bankruptcy_simulation"]` flips.
- Every machine's manifest declares `bankruptcy_simulation` (universal feature).
- Therefore: **all 421 machines** × all modes invalidate. Same as today's 1007 (m,mode).
- **Per §1.3 table this is the "Universal feature edit" class. 1× by design.**

#### Example 2: rename a field in `features/payouts_by_spin_type.py` (the `8411c9d`-class change)
- `feature_hashes["payouts_by_spin_type"]` flips.
- This feature is declared in every manifest's analyzer_features list.
- Invalidation: **1007 (m,mode) — same as today.**
- **Per §1.3 table this is also "Universal feature edit". 1× by design.**
- **But**: SCHEMA_VERSION bumps from 1 to 2 (§5.4 policy). Frontend registry adds fallback rule for v1→v2. Old reports continue rendering correctly via registry-driven fallback application; no silent .toFixed(3) crash.

#### Example 3: add new BCM cleanup rule in `features/cycle_peak_detection.py`
- `feature_hashes["cycle_peak_detection"]` flips.
- Per manifest, only the ~28-35 machines that declared `cycle_peak_detection` (BCM-21k + adjacent) are affected.
- Invalidation: **28-35 machines × ~3 modes ≈ 100 (m,mode).**
- **Per §1.3 table: per-cluster class. 12-15× reduction. Matches `02 §6.5` projection.**

#### Example 4: bespoke fix for M21 Buffalo in `features/bespoke_m21_buffalo.py`
- `feature_hashes["bespoke_m21_buffalo"]` flips.
- Only M21's manifest declares this feature.
- Invalidation: **1 machine × N modes ≈ 3-4 (m,mode).**
- **Per §1.3 table: per-machine bespoke class. 421× reduction.**

#### Example 5: change to `core/base_pipeline.py`
- `base_hash` flips.
- All 421 machines × all modes invalidate. **1× by design.**

#### Example 6 (NEW per Critic Concern 5): a "vanilla" machine X graduates to bespoke
This is the scenario addendum §1.5 highlights:

> "Add a representative example of 'machine X declared vanilla manifest, RTP integrity check fails, we add a per-machine plugin Y, X re-onboards — works without changing the framework'."

Walkthrough:
1. Machine X starts with a short manifest declaring 4 universal features.
2. RTP integrity gate (§9) runs on fleet pull. X fails — `fallback_share_pct = 6%` exceeds X's manifest contract threshold (0.5%).
3. Operator reads error: "M_X: RTP fallback share 6% > 0.5%. Manifest declares features [F1, F2, F3, F4] but RTP attribution leaks into `_unattributed_st<N>` bucket."
4. Operator (or slot-* team) investigates → confirms X needs a new bespoke feature `bespoke_mX.py`.
5. Operator adds `bespoke_mX.py`, registers it in `feature_registry.ALL_FEATURES`, updates X's manifest to add it.
6. RTP gate runs again, passes.
7. **Framework unchanged** — no analyzer monolith edit, no Phase-2-level refactor. Just added a new feature file + manifest line.

This is the workflow the proposal claims to enable. It is testable as a Phase-2 deliverable: pick a known-broken machine (M250 100% fallback) and run this workflow end-to-end (addendum §1.5 paragraph 4 forcing-function requirement).

### §4.4 Per-machine config_md5 and code_md5 — virtual side unchanged

Per `03 §3.1` and `04 §4.3` (v1) — `compute_code_md5(machine_name)` at `machine_version.py:109` feeds only the 6 virtual entries. Real fleet's `codeSummaryMd5` comes from upstream `/MachineConfigMd5`. **v2 does not change either path's hash composition.** Per-virtual-machine isolation from `core/engine/*.py` changes is **out of scope** per addendum §3.

Validator §3.2 surfaced this as an "awkward but acknowledged" limitation. v2 explicitly notes: when `core/engine/symbol.py` is touched, all 6 virtual machines' `code_md5` flips. That's the existing behavior; the proposal preserves it. Decoupling per-virtual-machine from shared engine code is a separate spec-format refactor.

### §4.5 Honesty about universal-feature changes (per addendum §1.1)

The proposal **does not** claim to reduce blast for universal feature changes. Per §1.3 table the "Universal feature edit" row is **1× by design**. Reasoning:

- A feature is "universal" if every machine declares it.
- If every machine declares feature F, then changing F's hash flips every machine's effective version.
- The proposal does not magically separate "comment-only edit" from "behavior-changing edit" — the analyzer-source-hash framework is deliberately broad per `compute_analyzer_version`'s original docstring at `player_impact_analyzer.py:2147`.

What the proposal **does** allow is making more features non-universal. Today's `compute_analyzer_version` is intrinsically universal (whole-file hash). v2's per-feature hashes allow:
- A feature can be declared by a subset of machines (e.g., `cycle_peak_detection` declared only by ~28 BCM machines).
- New features can be added without retroactively making every machine declare them.

Over time the proposal expects:
- Universal features stay universal (e.g., `bankruptcy_simulation` likely always universal because every machine wants RTP/streak stats).
- New mechanisms are introduced as opt-in features, not universal ones.
- The blast profile shifts from "everything is 1007 (m,mode)" toward "most changes are per-cluster or per-machine, occasional universals".

This shift is what the proposal *enables*, not what it *forces*. The path of least resistance becomes "carve a per-cluster or per-machine feature instead of editing the universal one". v1's failure mode (developers edit the monolith because there's nowhere else to put logic) goes away.

### §4.6 Hash composition map (text diagram, post-migration)

```
Source-file edit
   |
   v
 [a] fresh_slotlab/analyzer/core/*.py             ──> base_hash flips → all 421 machines × all modes
 [b] fresh_slotlab/analyzer/features/<fid>.py    ──> feature_hashes[fid] flips → only machines declaring fid
 [c] slot_designer/core/engine/*.py +             ──> compute_code_md5(M) flips → 6 virtual machines only
     slot_designer/core/emitter/*.py                   (out of scope per addendum §3)
 [d] slot_designer/machines/<M>/plugins/**/*.py  ──> compute_code_md5(M) flips → only that virtual machine
 [e] slot_designer/machines/<M>/{spec,strips,    ──> compute_config_md5 flips → only that virtual machine + mode
       weights}
 [f] slot_designer/configs/machine_manifests/<M>.json
                                                  ──> effective_analyzer_version(M, mode) flips
                                                       only when manifest field affecting feature list changes
 [g] upstream /MachineConfigMd5 emission          ──> machines.json upstream md5 flips (real machines only)
   |
   v
 effective_analyzer_version(M, mode) =
     sha256(base_hash || sorted(features_M_uses) || mode)[:12]
   |
   v
 Stamped into:
   * summary.effective_analyzer_version  ← stamped at write time
   * summary.analyzer_features          ← list of features used; for debugability
   * summary.schema_versions[fid]       ← per-feature version map
   * runs.effective_analyzer_version    ← state/console/console.db (new col)
   * reports/<M>/mode_<N>/index.json[*].effective_analyzer_version
```

**Per addendum §1.2 clean break**: no compatibility layer is needed for pre-v2 reports. Phase 1 deploys clean — all 2030 existing runs are invalidated; operators regen reports under new manifests. Critic Tier 1 #3 (NULL semantics) becomes moot.

---

## §5 Plugin / extension Protocol + manifest

(v1's Protocol + manifest mechanics validated by Wave 3 — kept. v2 adds: REQUIRES dependency declaration per Critic Q2; explicit registry per Critic Q4 + Validator §3.4; SCHEMA_VERSION bump policy per Critic Q7 + §7.8; per-mode dimension per Critic Q11; per-machine manifest files instead of central hybrid; manifest validation rules with strict-error drift per Critic Concern 3.)

### §5.1 Three plugin axes (each independent)

| Axis | Existing artifact | New v2 contract |
|---|---|---|
| Round-level extraction | `RoundWinRule` ABC at `round_win.py:102` + RULE_REGISTRY at `:423` | **Formalized as-is** (v1 kept); manifest declares rule_ids |
| Summary-level aggregation | (today: inline in `parse_chunk_response` + `main()`) | **NEW `AnalyzerFeature` Protocol** with REQUIRES + RTP_CONTRIBUTION flag |
| Frontend rendering | (today: 17 inline renderers; no contract) | **NEW renderer registry** with explicit fallback rules |
| **[v2 NEW]** RTP integrity contract | (today: silent `_unattributed_st<N>` synthesizer) | **NEW per-machine `rtp_integrity_contract` block in manifest** (§9) |

### §5.2 `AnalyzerFeature` Protocol with v2 additions

```python
# fresh_slotlab/analyzer/features/_base.py (NEW; v2 expansion of v1 sketch)
from abc import ABC, abstractmethod
from typing import ClassVar, Any
import hashlib
from pathlib import Path

class AnalyzerFeature(ABC):
    """Versioned, opt-in slice of analyzer functionality."""

    FEATURE_ID: ClassVar[str] = ""               # stable; manifest key; never renamed
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ()  # summary keys this feature WRITES
    SCHEMA_VERSION: ClassVar[int] = 1            # bumped on breaking field rename (§5.4)
    REQUIRES: ClassVar[tuple[str, ...]] = ()     # [v2] feature_ids this feature reads
    RTP_CONTRIBUTION: ClassVar[bool] = False     # [v2] does this feature affect win attribution (§9)
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}  # [v2] schema version → fallback map

    @abstractmethod
    def extract(self, parse_state, chunk_dict) -> dict:
        """Per-chunk extraction. Reads chunk_dict + REQUIRES-fields from parse_state.
        Returns {summary_key: value} for SCHEMA_KEYS."""

    @abstractmethod
    def reduce(self, prev_acc, this_acc) -> Any:
        """Merge across chunks. Idempotent."""

    @abstractmethod
    def emit(self, final_acc, summary: dict) -> None:
        """Write into summary at SCHEMA_KEYS paths."""

    @classmethod
    def compute_hash(cls) -> str:
        src = Path(cls.__module__.replace(".", "/") + ".py")
        return hashlib.sha256(src.read_bytes()).hexdigest()[:12]
```

**Example skeleton — `payouts_by_spin_type`** (the `729a6ca` / `8411c9d` / `4cbcab2` cluster):

```python
# fresh_slotlab/analyzer/features/payouts_by_spin_type.py (NEW)
from ._base import AnalyzerFeature
from ..feature_registry import register

@register
class PayoutsBySpinTypeFeature(AnalyzerFeature):
    FEATURE_ID = "payouts_by_spin_type"
    SCHEMA_KEYS = ("player_impact.payouts_by_spin_type",)
    SCHEMA_VERSION = 2  # bumped on the 8411c9d rename (hit_rate_pct → hit_rate)
    REQUIRES = ()  # standalone
    RTP_CONTRIBUTION = True  # affects attribution; triggered by RTP gate
    REGISTERED_FALLBACK_RULES = {
        1: {  # v1 → v2 fallback: divide percent by 100, rename rtp_pp → rtp_contribution_pp
            "hit_rate": {"source": "hit_rate_pct", "transform": "divide_100"},
            "rtp_contribution_pp": {"source": "rtp_pp", "transform": "identity"},
        }
    }

    def extract(self, parse_state, chunk_dict): ...
    def reduce(self, prev_acc, this_acc): ...
    def emit(self, final_acc, summary): ...
```

### §5.3 Frontend renderer registry — TypeScript sketch

```typescript
// src/web_console/frontend/renderers/registry.js (NEW)
interface RendererPlugin {
  readonly id: string;                    // matches FEATURE_ID
  readonly schemaKey: string;             // e.g. "player_impact.payouts_by_spin_type"
  readonly minSchemaVersion: number;
  readonly maxSchemaVersion: number;
  readonly fallbackRules?: Record<number, FallbackMap>;
  render(summary: object, host: HTMLElement, ctx: RendererCtx): void;
}

const RENDERER_REGISTRY: Record<string, RendererPlugin> = {
  "payouts_by_spin_type": {
    id: "payouts_by_spin_type",
    schemaKey: "player_impact.payouts_by_spin_type",
    minSchemaVersion: 1,
    maxSchemaVersion: 2,
    fallbackRules: {
      1: {
        hit_rate: { source: "hit_rate_pct", transform: "divide_100" },
        rtp_contribution_pp: { source: "rtp_pp", transform: "identity" }
      }
    },
    render: renderPayoutsBySpinType
  },
  // 16 other renderers from 03 §2.10 enumeration
};
```

`_paintAnalysisFromSummary` at `app.js:6676` iterates the registry. Reading `summary.schema_versions[feature_id]` selects the right fallback. This addresses Critic Concern 7 + memory `feedback_no_parallel_panel_impl.md`.

### §5.4 SCHEMA_VERSION bump policy (resolves Critic Q7 + §7.8 open question)

v1 deferred this to Validator. v2 makes it explicit (matches user expectation of "every change should have a clear contract").

**The SCHEMA_VERSION of a feature MUST be bumped when ANY of the following occur in the feature's emit output**:

| Change | SCHEMA_VERSION bump required? | Rationale |
|---|---|---|
| Rename a field name | **YES** | Renderer breaks without fallback |
| Change a field's units (e.g., percent → fraction; the `8411c9d` case) | **YES** | Numeric meaning changes |
| Change a field's data type (e.g., int → float) | **YES** | Renderer formatter assumptions break |
| Remove a field | **YES** | Renderer reading the field gets undefined |
| Reorder array elements within a single field | **YES** | If order is semantic; e.g., percentile arrays |
| Change a default fill value (e.g., 0 → null for missing) | **YES** | Renderer null-handling differs |
| Add a new field | **NO** | Additive; renderers ignore unknown fields |
| Add a new element to an existing dict (e.g., new pid in payouts_by_spin_type[ST1_paid]) | **NO** | Additive content |
| Bug fix that changes numeric output without changing field names/types | **NO** by default; **YES** if the fix alters how operators interpret historical reports | Judgment call; default toward NO to avoid noise |

**Enforcement**: a pre-commit hook (or CI check) inspects diffs in `fresh_slotlab/analyzer/features/*.py`. For each module changed, check if SCHEMA_KEYS used inside `emit()` were renamed/removed/typechanged via AST analysis. If yes AND SCHEMA_VERSION unchanged → block commit with a clear error message.

A fallback test is required for any non-trivial bump: provide a v_{old}-schema fixture summary and a v_{new}-schema fixture; assert renderer produces equivalent visual output for both via the registry's `fallbackRules` entry.

**This policy resolves Critic Q7 + §7.8.** It's not policy-only — there's an enforcement mechanism.

### §5.5 Per-machine manifest format (Option 5.5b chosen, replaces v1's hybrid)

v1 offered three options (central, per-machine, hybrid). v2 picks **per-machine files** (Option 5.5b) because addendum §1.5's "every machine potentially unique" principle requires per-machine PR isolation. A central file with 421 entries undermines that principle: changes to M_X's manifest can collide with changes to M_Y's manifest in source control.

Trade-off: 421 manifest files. Mitigated by JSON Schema validation, bulk tooling (`scripts/manifest_lint.py`, `scripts/manifest_diff.py`), and the validation rules in §5.6.

**Layout**:
```
slot_designer/configs/machine_manifests/
  M1.json
  M14.json
  M15.json
  M15$TopDollarSelector$0$.json    # variants get their own file or inherit via reference
  M21.json
  M260.json
  M274.json
  M279.json
  ...
  manifest_schema.json             # JSON Schema for validation
```

**Variant handling**: Two options surfaced by Critic Q12 + v1 §7.5:
- (a) Each variant has its own manifest file (verbose but isolated).
- (b) Variants reference an underlying file via `"inherits_from": "M273.json"` and only declare overrides.

v2 picks **(b) inheritance via `inherits_from`** because `02 §4.1` observation 6 explicitly notes "166 variants share Axes 1-4 with their underlying" — they're definitionally identical except for selector parameterization. The 85 M273 variants share a single underlying manifest file and reference it; their per-variant files contain only the variant-specific delta (typically just the selector instance ID).

**Manifest schema (per-machine file)**:

```json
{
  "machine_id": "M274",
  "manifest_version": 1,
  "inherits_from": null,
  "spin_type_convention": {"paid": [140], "bonus": [139]},
  "feature_tags": ["BCM", "Wheel"],
  "round_win_rules": ["bcm_cycle_anchor_m274"],
  "analyzer_features": [
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "bankruptcy_simulation",
    "bonus_chain_dynamics",
    "collect_mechanic",
    "multiplier_profile",
    "cycle_peak_detection"
  ],
  "bcm_target_feature": "ListRewardWheel",
  "trigger_session_pattern": null,
  "modes_supported": [1, 5, 7],
  "per_mode_overrides": {
    "5": {
      "analyzer_features_remove": ["bonus_chain_dynamics"],
      "analyzer_features_add": []
    }
  },
  "rtp_integrity_contract": {
    "fallback_share_threshold_pct": 0.5,
    "expected_paid_st": [140],
    "expected_bonus_st": [139],
    "required_attribution_anchors": ["_bcm_cycle", "5801"],
    "exception_policy": "error"
  }
}
```

**Variant-inheriting manifest** (e.g., M273$WheelSelector$0$):

```json
{
  "machine_id": "M273$WheelSelector$0$",
  "manifest_version": 1,
  "inherits_from": "M273.json",
  "spin_type_convention_override": null,
  "feature_tags_override": null,
  "analyzer_features_override": null
}
```

### §5.6 Manifest validation rules — strict (resolves Critic Concern 3)

Per addendum §1.2 (clean break) and §1.4 (constraint S strict), manifest validation is **strict error** on drift. The pre-deploy gate enforces:

1. **Every machine in `configs/machines.json` MUST have a manifest file in `machine_manifests/`**. Missing file = error.
2. **Every `analyzer_feature` ID MUST correspond to a class registered in `feature_registry.ALL_FEATURES`**. Manifest references typo'd or deleted feature = error.
3. **Every `round_win_rule` ID MUST be defined in `configs/machine_round_win_rules.json` with this machine in `applies_to`**.
4. **REQUIRES dependency satisfaction**: for every feature F in `analyzer_features`, every R in F.REQUIRES must also be in `analyzer_features`. (Topological sort done by orchestrator; manifest validation just checks existence.)
5. **Mode coverage**: for every mode in `modes_supported`, the resolved per-mode feature set must include all RTP_CONTRIBUTION=True features that the integrity contract requires.
6. **RTP integrity contract validity**: `expected_paid_st` and `expected_bonus_st` must be non-empty; `fallback_share_threshold_pct` must be in [0, 100]; `required_attribution_anchors` must reference real pay_id strings (validated at first run, not commit time).
7. **Rawdata sanity check** (if rawdata available; per `02 §1` 215 machines without rawdata are exempt from this rule but still subject to rules 1-6):
   - Declared `spin_type_convention.paid` must match observed paid-ST set in chunks.
   - If `wild_nudge_classification` is NOT declared but rawdata has ST=36+ReMarks=move, error.
   - If `cycle_peak_detection` is NOT declared but rawdata has `CollectCount` extras, error.
   - If `pay_id_suffix_attribution` is NOT declared but rawdata has line_id values not matching pay_id keys (the suffix attribution case per `02 §3.5.2`), error.

**On any error**: the deploy gate refuses to ship. The 22+ machines today that have undeclared implicit dependencies (per `02 §3.5.2`) are blocked at validation time. They get explicit manifests during Phase 2 (forcing function) and the gate clears.

Addendum §1.2's clean-break authorization is what enables this strictness: we don't preserve the 22+ silently-broken machines through a transition window. They get errored out, manifests fixed, re-onboarded.

### §5.7 Feature discovery + missing-feature runtime error (resolves Critic Q4 + Validator §3.4)

v1 deferred feature discovery to "the orchestrator at main() reads SCHEMA_KEYS during summary assembly". v2 specifies:

**Discovery**:
- Feature modules MUST be imported in `fresh_slotlab/analyzer/features/__init__.py` (single import list, easy to grep).
- Each feature module uses `@register` decorator at class definition; importing the module registers it.
- `feature_registry.ALL_FEATURES` is the runtime source of truth.

**Manifest references non-existent feature**:
- Manifest validation (§5.6 rule 2) catches this at commit / deploy time.
- Runtime: if somehow a manifest references a feature not in `ALL_FEATURES` (post-deploy deletion of feature without manifest update), the orchestrator emits an **explicit error** before chunk processing starts: `RuntimeError: machine M_X manifest references feature 'F_id' not in registry`. Run aborts with non-zero exit code.

**Runtime topological dependency resolution**:
- For machine M with `analyzer_features = [F1, F2, F3]`, the orchestrator computes `feature_registry.feature_dependency_order([F1, F2, F3])` → topological sort by REQUIRES.
- Cycle in REQUIRES → error at registry initialization.
- Each chunk: orchestrator iterates features in topological order; each feature's `extract` sees a `parse_state` with prior features' outputs already merged.

This addresses Critic Q2 (manifest collision / silent shared accumulators) directly.

### §5.8 In-process monkey-patch path under sliced architecture (resolves Critic Q13)

v1 did not address how `_run_generate_report` at `app.py:6700` continues to monkey-patch `pia.post_json`, `sys.argv`, `os._exit` post-slicing.

v2 specifies:

- `fresh_slotlab/player_impact_analyzer.py` remains the **entry-point module**. Its `main()` is preserved as the public CLI entry. Post-slicing it becomes a thin orchestrator that imports from `analyzer/core/base_pipeline.py` and `analyzer/feature_registry.py`.
- `pia.post_json` (the upstream HTTP function) is still defined in `player_impact_analyzer.py` (Layer 0 of `01 §2`). Monkey-patch attaches here. Unchanged.
- `pia.main` is still the CLI entry. Monkey-patch of `sys.argv` and `os._exit` still works at the same attach point.
- The actual chunk parsing logic lives in `analyzer/core/base_pipeline.py:parse_chunk_response` (moved from `pia:2354`). `pia.main` calls into it. The in-process caller doesn't need to know — it still imports `pia` and calls `pia.main()`.

**Tests** (Phase 1 deliverable, addresses Critic Concern 4 / mapper §5 #1):
- `tests/backend/test_invocation_styles_parity.py`: spawn analyzer via (a) subprocess (`RunManager.start_run`), (b) in-process import + monkey-patch (`_run_generate_report`), (c) batch-pool subprocess (`_batch_gen_worker.run_analyzer_job`). All three feed identical chunks. Assert byte-identical summaries. This codifies the implicit contract that all three behave identically.

If the test fails today (before Phase 1), the divergence is documented and fixed before Phase 1 ships the shared primitives. Phase 1 doesn't proceed until parity is established.

### §5.9 Per-machine `round_win_rule` plugin — formalize existing pattern (unchanged from v1)

`round_win.py:102` ABC + RULE_REGISTRY at `:423` stays unchanged. Manifest references rule_ids; `load_rules_for_machine` reads either `configs/machine_round_win_rules.json` (existing source) or, optionally per Phase 6, per-machine manifest's `round_win_rules` array.

### §5.10 Plugin lifecycle (resolves Critic Q10)

v2 specifies:

- **Adding a feature**: register in `feature_registry`. Add reference in any machine manifest that needs it. RTP gate validates.
- **Deleting a feature**: only allowed if no manifest references it. CI lint job: search all manifests for the feature_id; if found, deletion blocked.
- **Renaming a feature**: requires migration of all manifests referencing it. CI lint validates.
- **Historical reports**: per addendum §1.2 clean break, historical reports do NOT need to deserialize the same way. They're recomputable. If an old report references a feature that no longer exists, the report is simply marked "incompatible with current analyzer"; operator regenerates from rawdata. No "phantom feature hash" problem.

### §5.11 Manifest examples (representative machines)

**M1** (one of the simplest possible):
```json
{
  "machine_id": "M1",
  "manifest_version": 1,
  "inherits_from": null,
  "spin_type_convention": {"paid": [1], "bonus": []},
  "feature_tags": ["Plain"],
  "round_win_rules": [],
  "analyzer_features": [
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "bankruptcy_simulation",
    "multiplier_profile"
  ],
  "modes_supported": [1, 2, 5, 7],
  "rtp_integrity_contract": {
    "fallback_share_threshold_pct": 0.5,
    "expected_paid_st": [1],
    "expected_bonus_st": [],
    "required_attribution_anchors": [],
    "exception_policy": "error"
  }
}
```

**M15** (TopDollar, rule-bearing):
```json
{
  "machine_id": "M15",
  "manifest_version": 1,
  "inherits_from": null,
  "spin_type_convention": {"paid": [1], "bonus": [14, 15]},
  "feature_tags": ["Selector"],
  "round_win_rules": ["topdollar_selector_settlement"],
  "analyzer_features": [
    "payouts_by_spin_type",
    "bankruptcy_simulation",
    "topdollar_settlement",
    "multiplier_profile"
  ],
  "selector_type": "TopDollarSelector",
  "trigger_session_pattern": "type_1",
  "modes_supported": [1, 2, 5, 7],
  "rtp_integrity_contract": {
    "fallback_share_threshold_pct": 0.5,
    "expected_paid_st": [1],
    "expected_bonus_st": [14, 15],
    "required_attribution_anchors": ["666"],
    "exception_policy": "error"
  }
}
```

**M279** (heavy outlier, BCM+MoveNudge+Wheel combo):
```json
{
  "machine_id": "M279",
  "manifest_version": 1,
  "inherits_from": null,
  "spin_type_convention": {"paid": [140], "bonus": [2, 36]},
  "feature_tags": ["BCM", "MoveNudge", "Wheel"],
  "round_win_rules": [],
  "analyzer_features": [
    "payouts_by_spin_type",
    "reel_marginal_by_spin_type",
    "bankruptcy_simulation",
    "bonus_chain_dynamics",
    "collect_mechanic",
    "multiplier_profile",
    "cycle_peak_detection",
    "wild_nudge_classification",
    "pay_id_suffix_attribution",
    "bespoke_m279_combo"
  ],
  "bcm_target_feature": "Wheel",
  "trigger_session_pattern": null,
  "modes_supported": [1, 2, 5, 7],
  "per_mode_overrides": {
    "2": {"bcm_target_feature_override": "MoveSpin"},
    "5": {"bcm_target_feature_override": "MoveSpin"},
    "7": {"bcm_target_feature_override": "MoveSpin"}
  },
  "rtp_integrity_contract": {
    "fallback_share_threshold_pct": 1.0,
    "expected_paid_st": [140],
    "expected_bonus_st": [2, 36],
    "required_attribution_anchors": ["_bcm_cycle", "27905"],
    "exception_policy": "error"
  }
}
```

**M21** (Buffalo bespoke):
```json
{
  "machine_id": "M21",
  "manifest_version": 1,
  "inherits_from": null,
  "spin_type_convention": {"paid": [27], "bonus": [25]},
  "feature_tags": ["FreeSpin", "Wheel"],
  "round_win_rules": [],
  "analyzer_features": [
    "payouts_by_spin_type",
    "bankruptcy_simulation",
    "multiplier_profile",
    "bespoke_m21_buffalo"
  ],
  "modes_supported": [1, 2, 5, 7],
  "rtp_integrity_contract": {
    "fallback_share_threshold_pct": 0.5,
    "expected_paid_st": [27],
    "expected_bonus_st": [25],
    "required_attribution_anchors": [],
    "exception_policy": "error"
  }
}
```

---

## §6 Migration plan (simplified per addendum §1.2 clean break)

Five phases — v1 had 5 phases; v2 keeps 5 but **reorders** them per Critic Concern 5 (12 known-complex machines as Phase 2 forcing function) and **simplifies** Phase 3 dramatically per addendum §1.2 (clean break — no historical preservation).

**Cross-cutting simplification from addendum §1.2**: No NULL `effective_analyzer_version` window. No dual-comparison logic. No "preserve old reports while new field rolls out". Migration day = clean cut: all 2030 existing runs are invalidated, regen from rawdata (which is preserved). Validator §3.3 resolves: "n/a per user clean-break authorization in 00_brief_v2 §1.2".

### Phase 1 — Foundation: extract all 6 duplications + module-global fix + invocation parity

**Goals**:
- Eliminate the 6 duplications between real and virtual identified by `01 §4` (v1 covered 4; v2 covers all 6).
- Resolve the `RAWDATA_ROOT` module-global hazard at `app.py:518` AND the `virtual_app.py:201` import-time side effect.
- Codify the 3-invocation-styles parity contract (mapper §5 #1; Critic Concern 4).
- Resolve the 3-summary-md5-writers question (mapper §5 #3).
- Resolve `_classify_chunks` historical-feeding question (mapper §5 #7).
- Resolve frontend probe-and-fallback location (mapper §5 #5).
- Resolve compareReports cache-bust race (mapper §5 #8).

**Deliverables**:

1. **Extract `_lookup_machine_md5`** to `fresh_slotlab/identity_stamp.py`. Today at `pia:2163` AND `app.py:548-591`. Both call sites import. Per `01 §4` ("Two ENTIRELY SEPARATE md5 implementations").

2. **Extract `_patch_summary_md5_tags`** to `fresh_slotlab/identity_stamp.py:stamp_summary_identity(summary, machines_config, machine, mode)`. Today at `virtual_analyzer.py:506-558` AND `_run_generate_report:6955-6973`.

3. **Reconcile the 3-writers question (mapper §5 #3)**: BEFORE extraction, run a parity test that loads identical (machine, mode) data through all 3 paths (live sampling, in-process replay, virtual delegate) and asserts identical md5 stamps emitted. If they diverge: pick the authoritative one (likely `_lookup_machine_md5` from `configs/machines.json` since that's the canonical registry source); patch the others. **Block extraction until parity is established.** Then extract.

4. **Unify session-CI helpers** in `fresh_slotlab/session_ci.py`. Both `_ci_halfwidth_pp` at `virtual_analyzer.py:278-291` and `session_halfwidth_pp` at `pia:1012-1034`.

5. **Extract inference-script trigger** to `fresh_slotlab/inference_trigger.py`. Today at `_run_post_analyzer_inference` `app.py:85-194` AND `_run_inference_scripts` `virtual_analyzer.py:561-649`. (Covered by v2; v1 missed this.)

6. **Extract schema-fingerprint helper** to `fresh_slotlab/upstream_schema_fingerprint.py`. Today at `_compute_upstream_schema_fingerprint` `pia:2108-2138` AND `compute_schema_fingerprint` in `slot_designer/core/emitter/`. (Covered by v2; v1 missed this.)

7. **`RAWDATA_ROOT` injection fix**. Strategy:
   - 4 sites currently using `rawdata_root if rawdata_root is not None else RAWDATA_ROOT` fallback (lines 695, 1064, 3187, 5318) — convert to required parameter; remove fallback. Force callers to inject explicit path.
   - 7 remaining sites — convert to `self._rawdata_root` for class-method ones; convert to required parameter for module-level functions. Use FastAPI's `Depends(get_rawdata_root)` pattern for routes.
   - Regression test: `tests/backend/test_rawdata_root_injection.py` — instantiate `create_app(rawdata_root="/test/path/")` and assert no code path in `app.py` reads the module-level `RAWDATA_ROOT` (via patch + assertion).

8. **Lazy-init `virtual_app.py:201`**. Today `app = build_virtual_app()` runs at module import time. Move to lazy: `def get_app(): ... if not _APP: _APP = build_virtual_app(); return _APP`. Anyone importing the module no longer triggers `build_virtual_app`. Extends regression test from `virtual_registry` to `virtual_app` (resolves Critic Q15).

9. **Codify 3-invocation-styles parity test** per §5.8. `tests/backend/test_invocation_styles_parity.py`. (Resolves mapper §5 #1 / Critic Concern 4.)

10. **Verify `_classify_chunks` doesn't feed historical chunks to analyzer accidentally** (mapper §5 #7). Today `_classify_chunks` returns kept/deletable/historical lists; `_run_generate_report:6733` consumes the kept list. Audit `_run_generate_report` end-to-end; confirm historical chunks are filtered out before reaching `pia.main`. Add an explicit assertion in `_run_generate_report` that historical chunks are excluded. Regression test: feed a (machine, mode) with mixed-md5 chunks; assert the run only processes kept ones.

11. **Frontend probe-and-fallback documentation** (mapper §5 #5). Audit `app.js apiGet` callers for `/api/virtual/paytable/{m}` and similar virtual-only endpoints. Document the catch behavior. Add explicit comment block in `app.js` listing all virtual-only endpoints and their fallback paths.

12. **compareReports cache-bust race fix** (mapper §5 #8). Today `compareReports:3477` fetches by `(machine, mode, version)` tuple; a concurrent DELETE on that version yields 404 mid-fetch. Add explicit error handling: on 404 during compare, show "report was deleted; select another" instead of crashing.

**Rollback**: revert the phase-1 commit(s). The new shared modules are additive; the old paths in `app.py`, `pia`, and `virtual_analyzer.py` can be restored from git. Per addendum §1.2 clean-break authorization, no data loss concern.

**Why Phase 1 first**: zero schema change, zero hash change, no manifest infrastructure. It pays down the duplication debt + the parity-uncertainty debt that would otherwise compound. Critically, **resolves ALL 5 pre-Phase-1 blockers from `01 §5` (#1, #3, #5, #7, #8)** — the proposal does not commit to Phase 2 until these resolve cleanly.

### Phase 2 — Slice analyzer + 12 known-complex machines as forcing function

**Goals**:
- Migrate analyzer monolith from `pia:1-8176` into `fresh_slotlab/analyzer/{core, features}/` tree.
- Introduce `compute_base_analyzer_version` + `compute_feature_hashes`.
- **Forcing function (addendum §1.3): 12 known-complex machines onboard cleanly under per-machine plugin path BEFORE the framework is committed**. Specifically: M21, M260, M268, M279, M274, M113, M11, M250, M108, M65, M67, M120.
- Demonstrate end-to-end the workflow from §4.3 Example 6: "machine X declared vanilla manifest, RTP integrity check fails, we add a per-machine plugin Y, X re-onboards — works without changing the framework". Pick one (e.g., M250 100% fallback) and walk it through.

**Deliverables**:

1. **Carve core/**:
   - `analyzer/core/base_pipeline.py` — `parse_chunk_response` orchestration (universal shape).
   - `analyzer/core/chunk_aggregation.py` — chunk merge loop from `pia:4774-5400+`.
   - `analyzer/core/summary_writer.py` — summary dict assembly from `pia:7800-7920`.
   - `analyzer/core/schema_gate.py` — `_REQUIRED_ROUND_FIELDS` lives here (resolves Critic Q17).

2. **Carve universal features** (declared by every machine's manifest):
   - `features/payouts_by_spin_type.py` (was `729a6ca` cluster, `8411c9d` rename, `4cbcab2` filter).
   - `features/reel_marginal_by_spin_type.py` (paired with above).
   - `features/bankruptcy_simulation.py` (universal KPI; `pia:1141, 1266, 1373`).
   - `features/multiplier_profile.py` (universal KPI; `pia:1978`).

3. **Carve sometimes-applicable features**:
   - `features/bonus_chain_dynamics.py` (machines with bonus rounds; ~152 per `02 §3.1`).
   - `features/collect_mechanic.py` (BCM machines; ~30 per `02 §3.5.3`).
   - `features/cycle_peak_detection.py` (machines with `CollectCount`; ~35 per `02 §3.5.2`).
   - `features/wild_nudge_classification.py` (ST=36+ReMarks=move; ~7 per `02 §3.5.2`).
   - `features/topdollar_settlement.py` (M12/M15/M90/M132 + variants; 17 per `02 §3.5.1`).
   - `features/wheel_selector_type2.py` (M273 + 84 variants + others; ~96 per `02 §4.2`).
   - `features/pay_id_suffix_attribution.py` (M120/M123/M139/M279; ~4+ per `02 §3.5.2`).
   - `features/lock_symbol_handling.py` (S-LockSym: M99/M103/M104/M240/M239; ~5 per `02 §3.4`).
   - `features/lock_lines_handling.py` (S-LockLines: M10/M131/M133/M23/M241; ~5 per `02 §3.4`).

4. **Carve the 12 forcing-function bespoke features** — Phase 2's signature deliverable. Each must onboard cleanly under the new framework BEFORE the framework is locked in:
   - `features/bespoke_m21_buffalo.py`
   - `features/bespoke_m260_buffs.py`
   - `features/bespoke_m268_credits_symbol.py`
   - `features/bespoke_m279_combo.py`
   - `features/bespoke_m274_listrewardwheel.py` (wraps existing `BCMCycleAnchorRule` + extras)
   - `features/bespoke_m113_expanded.py`
   - `features/bespoke_m11_diamond.py`
   - `features/bespoke_m250_grid.py`
   - `features/bespoke_m108_fillup.py`
   - `features/bespoke_m65_collection.py`
   - `features/bespoke_m67_open_close.py`
   - `features/bespoke_m120_reward_id.py`

   For each: write the bespoke feature → write its manifest entry → run RTP integrity gate (§9) → confirm it passes → commit. If any of these 12 cannot be expressed cleanly, the framework iterates (e.g., add a new lifecycle hook, expand `AnalyzerFeature` Protocol, etc.) BEFORE Phase 2 is locked.

   **This addresses Critic Concern 5 directly**: the forcing-function test is done at Phase 2, not Phase 5.

5. **Demonstrate Example 6 workflow end-to-end** (addendum §1.5 paragraph 4):
   - Pick M250 (memory says 100% RTP leak into fallback bucket).
   - Write minimal manifest for M250 declaring "I should be BCM" features.
   - Run RTP gate → fails with explicit error.
   - Add `features/bespoke_m250_grid.py` to fix.
   - Update manifest.
   - Re-run RTP gate → passes.
   - Framework not touched. Document the workflow in `docs/feature_onboarding_workflow.md`.

6. **`fresh_slotlab/analyzer/versioning.py`** with `compute_base_analyzer_version` + `compute_feature_hashes` + `compute_effective_analyzer_version` (per-mode capable per §4.1).

7. **`fresh_slotlab/analyzer/feature_registry.py`** with explicit `ALL_FEATURES` + topological sort.

8. **Per-cluster regression tests** — at least one machine per super-cluster shape (M14/SC-Vanilla, M272/SC-BCM-Modern, M15/SC-TopDollar, M273/SC-WheelSelector, M150/SC-LockRespin-50, M140/SC-MoveNudge), plus all 12 forcing-function machines. Byte-identical summary against golden file (run pre-Phase-2 analyzer → save golden → run post-Phase-2 analyzer → assert identical).

**Rollback**: revert the phase-2 commits. The pre-phase-2 monolith is preserved in git. Per addendum §1.2, no data preservation needed. The framework + the 12 forcing-function plugins are vetted before commit, so Phase 2 rollback is only triggered by truly unexpected failures.

**Why Phase 2 forcing function** (addressing Critic Concern 5 + Validator §3.1): The 12 known-complex machines are the canaries. If the framework fits them, it fits the long tail of medium outliers (§02 §5.2) and future "graduated" machines. If it doesn't fit them, we discover it now, not at Phase 5.

### Phase 3 — Per-machine manifests + per-feature registry wiring (clean break)

**Goals**:
- Land 421 per-machine manifest files (one per machines.json entry).
- Wire `compute_effective_analyzer_version` to consult manifest per machine, per mode.
- Frontend reads manifest-driven feature list to know which renderers to invoke.
- **Clean break from old reports**: drop `summary.analyzer_version`'s use as the freshness key; use `summary.effective_analyzer_version` only. Pre-migration reports become "stale, regen required" and are regenerated from rawdata in a separate fleet pull.

**Deliverables**:

1. **Write 421 per-machine manifests** in `slot_designer/configs/machine_manifests/<M>.json`. Most machines are short manifests (~10 lines JSON declaring 4-5 universal features). The 12 forcing-function machines + the variant-bearing underlyings get longer manifests with explicit overrides.

2. **`manifest_loader.py`** — reads `machine_manifests/<M>.json`, resolves `inherits_from` recursively, resolves `per_mode_overrides`, returns `EffectiveManifest(machine_id, mode)`. Single source of truth.

3. **Wire `compute_effective_analyzer_version` to read manifest** per (machine, mode). Each call passes `machine_features = manifest.analyzer_features` and `mode=mode`.

4. **Update analyzer + backend write sites** to use effective version:
   - `pia.main()` stamps `summary.effective_analyzer_version` (per machine/mode).
   - `_run_generate_report` (post-Phase-1 already extracted) stamps the same.
   - `RunManager.start_run` stamps in the `runs` DB column.
   - `BatchRunManager.finalize_run` stamps in `reports/<M>/mode_<N>/index.json`.

5. **Update `/api/reports/stale-count` at `app.py:5694`** to compare per-(machine, mode) `effective_analyzer_version`. **No NULL handling needed (clean break per addendum §1.2)**. Pre-migration runs simply fall into "stale, regen required".

6. **DB column**: ALTER TABLE runs ADD COLUMN effective_analyzer_version TEXT. Per addendum §1.2 clean break, no UPDATE migration needed; column starts NULL and stays NULL for pre-migration rows. The stale-count logic treats NULL as stale (which is correct: those rows are pre-migration and need regen anyway). Operator sees an explicit "X reports require regen post-architecture-migration" banner.

7. **Frontend updates** (`app.js`, `pure.js`):
   - `_renderRwtreeCell` at `app.js:1895`: read `effective_analyzer_version` for freshness; legacy `analyzer_version` shown for debug but not used in comparison.
   - `_paintAnalysisFromSummary` at `app.js:6676`: skip renderers whose `feature_id` isn't in the report's manifest. Avoid empty panels.

8. **Manifest validation CLI**: `scripts/validate_manifests.py` — runs all rules from §5.6. Adds to CI pre-commit hook.

9. **Manifest tooling**:
   - `scripts/manifest_lint.py` — single-file lint.
   - `scripts/manifest_diff.py` — show what changed between two versions.
   - `scripts/manifest_audit.py` — fleet-wide drift report (precursor to RTP integrity gate).

**Rollback**: revert phase-3 commits. Manifest files stay on disk but are ignored (no consumer reads them). `compute_effective_analyzer_version` falls back to `compute_base_analyzer_version()` alone (universal). Per addendum §1.2 the same "clean break" applies — Phase 3 rollback also doesn't preserve historical reports; ops would regen.

**Why Phase 3 third**: needs Phase 2's features registered. Independent of Phase 4 (frontend renderer registry) and Phase 5 (RTP integrity gate). Clean-break authorization (addendum §1.2) makes this phase **much simpler** than v1's transition-window-with-dual-comparison logic.

### Phase 4 — Frontend renderer registry + schema-version contract enforcement

**Goals**:
- Land §5.3 frontend renderer registry.
- Wire schema-version fallback rules.
- Add SCHEMA_VERSION bump enforcement (CI lint per §5.4).
- Cover all 17 renderers from `03 §2.10` + `compare_diff.js`.

**Deliverables**:

1. **`src/web_console/frontend/renderers/registry.js`** with 17 renderer entries each declaring `feature_id`, `minSchemaVersion`, `maxSchemaVersion`, `fallbackRules`.

2. **Refactor `_paintAnalysisFromSummary`** to iterate `RENDERER_REGISTRY`. Each renderer call checks `summary.schema_versions[feature_id]` vs supported range; selects fallback if needed.

3. **`compare_diff.js` integration** (Critic flagged this; v1 missed). Add a parallel registry mechanism so compare-mode rendering also goes through registry-driven fallback.

4. **Replace silent `??` fallbacks** scattered through `app.js` (enumerated in `03 §4.3`) with explicit registry-driven fallback application.

5. **SCHEMA_VERSION enforcement (CI hook)** per §5.4. AST-based diff check on `features/*.py`. Block commits that rename SCHEMA_KEYS without bumping SCHEMA_VERSION.

6. **Fallback unit tests** — for each renderer with fallbackRules: load a v_{old}-schema fixture + a v_{new}-schema fixture; assert renderer produces equivalent rendered output.

7. **Frontend cache-bust** for `RENDERER_REGISTRY` updates: include the registry version in the `{{ASSET_HASH}}` cache-bust token from `console_root:5383`. Avoids per-worker stale registry per Critic Edge Case 1.

**Rollback**: revert phase-4 commits. The new registry stays but is unused. Inline dispatch is restored. Reports keep rendering.

**Why Phase 4 fourth**: independent of analyzer slicing. Pairs naturally with Phase 3 (manifest's feature_id list informs which renderers to invoke).

### Phase 5 — RTP integrity gate (constraint S enforcement)

**Goals**:
- Implement RTP integrity check per addendum §1.4 (constraint S; see §9 below for full spec).
- Wire into every fleet-wide pull: per-machine RTP correctness check; explicit per-machine error on failure.
- Backend surface: failed integrity check emits an explicit error response; UI shows the error banner.
- Document the audit deliverable for known-broken machines (memory `feedback_invariant_with_fallback_hides_drift.md`: M250, M268, M260, M264, M163, M147 — explicit triage list).

**Deliverables**:

1. **`fresh_slotlab/rtp_integrity.py`** — implements `check_rtp_integrity(summary, manifest) -> RTPIntegrityResult`. See §9 for full spec.

2. **Wire into analyzer end-of-run**: after `summary_writer.py` produces the summary, `pia.main` invokes `check_rtp_integrity(summary, load_manifest(machine, mode))`. Result attached to summary as `summary.rtp_integrity_check`.

3. **Backend surface**:
   - `GET /api/runs/{rid}/report` (`app.py:7580`) returns the integrity check result in its response.
   - `POST /api/runs/integrity-check-all` — fleet-wide on-demand check, returns per-machine status.
   - Background job: every cron / scheduled fleet pull also runs the check; failures captured in `state/console/console.db.integrity_failures` table.

4. **Frontend UI**:
   - Per-machine cell in the rwtree shows a red badge if `rtp_integrity_check.passed == false`.
   - Click-through shows the explicit error message (`feedback_invariant_with_fallback_hides_drift.md` style: "M250: fallback_share_pct=100% > 0.5%; manifest declares features [X,Y,Z]; suggested fix: ...").

5. **Known-broken machines triage** — addendum §1.4 explicitly references the memory list. Phase 5 deliverable: explicit table of known-broken machines + their current fallback share + planned fix:
   | Machine | Current fallback share | Suggested fix |
   |---|---|---|
   | M250 | ~100% | Add `features/bespoke_m250_grid.py` (already in Phase 2 forcing function set) |
   | M268 | ~70-90% | Add `features/bespoke_m268_credits_symbol.py` |
   | M260 | ~70-90% | Add `features/bespoke_m260_buffs.py` |
   | M264 | ~70-90% | Apply `cycle_peak_detection` in manifest; verify |
   | M163 | ~35% | Apply `cycle_peak_detection`; verify |
   | M147 | ~35% | Apply `cycle_peak_detection`; verify |

   By Phase 5 completion, every one of these machines passes RTP integrity OR has an explicit "out of scope; documented" stance with operator sign-off.

6. **Per-machine error format spec** (§9.4 below for full detail) — clear, machine-readable JSON + human-readable summary string. Documented as a public contract.

**Rollback**: revert phase-5 commits. The gate is opt-in initially (warning-only flag during rollout); strict-error mode toggled per-machine via manifest's `exception_policy` field (default "error"; can downgrade to "warn" for a transition machine if needed — but addendum §1.4 says default is strict).

**Why Phase 5 last** (deviation from v1's "retro-fit last"): the integrity gate depends on manifests being in place (Phase 3) and renderer registry being wired (Phase 4 — for displaying integrity badges). It's the keystone, not retro-fit work. The 12 forcing-function machines are already done by Phase 2; Phase 5 validates them end-to-end and adds the fleet-wide gate.

### Phase 6 — (formerly Phase 5 in v1) Retro-fit + consolidation (optional / out-of-scope)

This phase was Phase 5 in v1 ("retro-fit + outlier conversion + machine_round_win_rules consolidation"). Per addendum §1.2 clean break, much of v1's Phase 5 simplifies:

- The "retro-fit 7 fleet-shared commits" maps to existing v1 §6 Phase 5 deliverable 1, but **with clean-break authorization** no special transition logic is needed.
- The "12 heavy outliers" are already done in Phase 2 (forcing function).
- `configs/machine_round_win_rules.json` consolidation is **optional** — addendum §1.5 says rules can stay in the central file or move to per-machine manifest's `round_win_rules` array; `load_rules_for_machine` reads either source.

Phase 6 deliverables (optional, post-Phase-5):

1. **Consolidate `machine_round_win_rules.json` into per-machine manifests** (optional; deferred unless operator value clear).
2. **Document architectural workflow** in `slot_designer/ARCHITECTURE.md` and `docs/ARCH_TEAM_PROCESS.md`.
3. **Audit medium outliers** (`02 §5.2` ~30 machines) — write manifests for them; run RTP integrity; address any failures.

### §6.5 Phase summary table

| Phase | Risk | Days est. | Schema change | Rollback simplicity |
|---|---|---|---|---|
| 1 (dedup + globals + 5 mapper blockers) | LOW-MEDIUM | 4-6 | None | Trivial revert |
| 2 (slice analyzer + 12 forcing-function machines + workflow demo) | HIGH | 10-14 | Per-feature SCHEMA_VERSION; effective_analyzer_version field | Per-feature revert |
| 3 (manifests + clean-break wiring) | MEDIUM | 4-6 | Manifest files; new DB col | Manifest ignored on rollback |
| 4 (frontend registry + SCHEMA_VERSION enforcement) | LOW | 2-3 | None | Trivial revert |
| 5 (RTP integrity gate + known-broken triage) | MEDIUM-HIGH | 5-7 | New `rtp_integrity_check` field in summary; new DB table | Gate becomes opt-in on rollback |
| 6 (optional retro-fit + consolidation + medium outlier audit) | LOW | 3-5 | None | Optional throughout |

Total: ~28-41 dev days (sequential).

### §6.6 Migration constraint compliance (updated per addendum §1.2)

| Constraint | How honored by v2 plan |
|---|---|
| **00 §5.1** Backward-compat for 393 machines' reports | **Per addendum §1.2 clean-break authorization, this constraint is relaxed.** Pre-migration reports are NOT preserved across Phase 3 deploy; operators regen from rawdata. Saves ~15 days of migration complexity. |
| **00 §5.2** Prod console (8877) never breaks | Each phase has rollback; phase 2's feature carve-outs verified against 12 forcing-function machines BEFORE commit; phase 1's parity tests codify invariant. |
| **00 §5.3** Virtual reuses prod code | Phase 1 removes 6 dups; Phase 2's feature modules are shared. |
| **00 §5.4** New machine = O(1) hash | Phase 3 manifests + Phase 2's bespoke plugin pattern achieves this for per-machine and per-cluster cases. Universal-feature changes still flip 421 (§1.3 honest framing). |
| **00 §5.5** Rollback per phase | Documented per phase. Per addendum §1.2 simplified (no historical preservation). |
| **00 §5.6** No silent data loss | Phase 5 RTP integrity gate makes silent loss an explicit error. Per addendum §1.4 constraint S. |
| **Addendum §1.4** RTP integrity hard constraint S | Phase 5 + §9 below. |
| **Addendum §1.5** Every machine potentially unique | Phase 3 per-machine manifests; no default cluster tier. |

---

## §7 Open questions for Wave 3 v2

v1 had 9 open questions; Wave 3 v2 reduces this to 4 — each truly requires Wave 3 input vs. inline resolution in this proposal.

### §7.1 Cluster-inheritance vs per-machine-manifest tradeoff (Critic Q12 + §7.5)

v1 §7.5 asked: 85 M273 variants — explicit per-variant manifest or template inheritance? v2 §5.5 picks **inheritance via `inherits_from`**. Wave 3 v2 should validate: is `inherits_from` the right semantic? Should we support multi-level inheritance (M273$WheelSelector$0$ → M273 → SC-WheelSelector defaults)? Per addendum §1.5 the framing changed: no super-cluster defaults anymore, so multi-level is just `M273$WheelSelector$0$ → M273`.

### §7.2 SCHEMA_VERSION bump policy edge cases (Critic Q7 + §7.8)

§5.4 specifies SCHEMA_VERSION bump rules. Edge case: bug fix that changes numeric output without renaming fields. Rule says "by default NO; YES if interpreting historical reports differs". This is a judgment call. **Wave 3 v2 should propose**: what's the operator-facing notification mechanism when a numeric-change bug fix lands? Memory `feedback_md5_is_a_tag_not_a_destruction_signal.md` cited in v1 — same principle: don't destroy historical-tagged data, but DO clearly mark which interpretation applies.

### §7.3 RTP integrity gate strictness during rollout window (addendum §1.4 + §9)

§9 spec says default exception_policy is "error". During Phase 5 rollout, machines that have never been audited might unexpectedly fail. **Wave 3 v2 should weigh in**: should there be a per-machine "audited" flag in the manifest, where un-audited machines default to "warn" until first audit? Or is the cleaner play to require operator audit before manifest commit (forcing function for actual coverage)?

### §7.4 Manifest mode dimension semantics (Critic Q11)

§4.1 + §5.5 support `per_mode_overrides`. Some machines have very different mode 1 vs mode 5 semantics. **Wave 3 v2 should walk a specific case** — e.g., M14 mode 1 (RTP-monitorable) vs M14 mode 2 (per memory `user_testing_machine.md` "mode 2/5 RTP 不可精准监控") — to verify the override mechanism handles the case where one mode is in-scope and another mode is out-of-scope per the RTP integrity gate.

---

## §8 Out of scope (refined for v2 per addendum §3)

### §8.1 Upstream API schema changes
Per `00 §7`. The chunk envelope (`01 §2 layer 0`, `_BASELINE_ROUND_FIELDS` at `:1444-1452`) is immutable. v2 works within the existing schema.

### §8.2 The 80% spin_type_category threshold (`5c4a111` revert)
Per `00 §7` + addendum §3. Reverted; stays out.

### §8.3 Performance optimization unrelated to architecture
Per `00 §7`. v2 does not touch AIMD sampling, `chunks_by_md5` inverted index, or bankruptcy streaming accumulator.

### §8.4 UX / visual redesign
Per `00 §7` + addendum §3. v2's renderer registry refactor is structural-only; no layout/color changes.

### §8.5 Implementing this proposal
Per `00 §7`. v2 produces design only.

### §8.6 Per-virtual-machine isolation from core engine changes
`compute_code_md5(machine_name)` at `machine_version.py:109` bundles all `core/engine/*.py` + `core/emitter/*.py` files; touching `core/engine/symbol.py` flips all 6 virtual machines (per `03 §5.1`, Validator §3.2). v2 explicitly does NOT change this. Addendum §3: "Re-onboarding existing per-machine specs ... byte-locked per universal rule" — virtual machines stay as-is.

### §8.7 reporter.py legacy module + sampler.py M14-hardcoded path
v2 leaves them in place. Cleanup is separate task.

### §8.8 Database schema migration (large-scale)
v2 adds two columns (`effective_analyzer_version`, integrity-related). Per addendum §1.2 no UPDATE migration of existing rows.

### §8.9 Variant fanout syntax (`$` separator)
v2 keeps existing parsing. New fanout modes (e.g., 200+-variant machines) work with same infrastructure.

### §8.10 i18n updates
Per `00 §7` + memory `feedback_no_parallel_panel_impl.md`. Renderer registry preserves existing i18n keys.

### §8.11 Universal feature edit blast reduction
Per §1.3 + §4.5: the universal-feature-edit change class stays at 1× by design. The proposal does NOT promise this changes. (Reframed honestly per addendum §1.1.)

### §8.12 The 80% rawdata coverage gap
Per `02 §1`: 215 of 421 machines have NO rawdata. Manifest validation rule 7 (rawdata sanity check) is gated on rawdata availability. The 215 machines without rawdata bypass that rule. Future task: backfill rawdata for these or accept manifest authoring without rawdata-driven validation.

---

## §9 RTP integrity enforcement (NEW per addendum §1.4 constraint S)

This section satisfies the addendum §1.4 hard constraint:

> **For any fleet-wide pull / analysis run, the system MUST EITHER (a) emit correct RTP for each machine in the run, OR (b) emit an explicit per-machine error identifying that machine cannot be correctly analyzed and why. Silent fallback to `_unattributed_st*` / `_other` / wildcard buckets without an explicit per-machine error is forbidden.**

### §9.1 How RTP correctness is checked per machine

The integrity check has **three layers**, each running per-machine per-run:

**Layer 1 — Hard invariant** (existing, kept):
```
sum(payout_id_win) == chunk_win  (across all chunks)
```
If this fails, the analyzer already raises today. Layer 1 catches arithmetic bugs.

**Layer 2 — Fallback-bucket share invariant** (NEW per memory `feedback_invariant_with_fallback_hides_drift.md`):
```python
fallback_share_pct = sum(payout_id_win[pid] for pid in payout_ids if pid.startswith("_unattributed_"))
                   / total_paid_win * 100
```
If `fallback_share_pct > manifest.rtp_integrity_contract.fallback_share_threshold_pct`, the machine **fails** integrity. Default threshold per manifest = 0.5% (or per-machine override per §5.5).

**Layer 3 — Attribution-anchor coverage** (NEW):
Per manifest, every machine declares `required_attribution_anchors` — a list of pay_ids that MUST appear in the summary (with > 0 hits) if the machine's mechanic is functioning correctly. E.g.:
- M274's manifest requires `["_bcm_cycle", "5801"]` — both must have hits in the report.
- M15's manifest requires `["666"]` (TopDollar trigger).
- A vanilla machine like M1 may have `[]` (no required anchors; just standard pay_id attribution).

If any required anchor has 0 hits, the machine **fails** integrity (with explicit "expected anchor X not found").

### §9.2 Combined integrity result

```python
@dataclass
class RTPIntegrityResult:
    machine: str
    mode: int
    passed: bool
    layer1_invariant_ok: bool          # sum(pid_win) == chunk_win
    layer1_error: str | None
    layer2_fallback_ok: bool           # fallback_share <= threshold
    layer2_fallback_share_pct: float
    layer2_threshold_pct: float
    layer3_anchors_ok: bool            # all required anchors present
    layer3_missing_anchors: list[str]
    summary_message: str               # human-readable error message
    suggested_actions: list[str]       # operator guidance
```

A machine `passes` only if all three layers pass.

### §9.3 Explicit error format when correctness fails

For a failing machine, the error is structured per layer and surfaces actionably:

**JSON error format**:
```json
{
  "machine": "M250",
  "mode": 1,
  "passed": false,
  "layer1_invariant_ok": true,
  "layer2_fallback_ok": false,
  "layer2_fallback_share_pct": 100.0,
  "layer2_threshold_pct": 0.5,
  "layer3_anchors_ok": false,
  "layer3_missing_anchors": ["_bcm_cycle"],
  "summary_message": "M250 mode 1 failed RTP integrity: fallback bucket holds 100% of paid RTP (threshold 0.5%). Required anchor '_bcm_cycle' has 0 hits.",
  "suggested_actions": [
    "Manifest declares cycle_peak_detection but BCM cycle anchor is not being synthesized.",
    "Likely fix: enable bcm_cycle_anchor rule (round_win_rules: [\"bcm_cycle_anchor_m250\"]) and define the per-machine rule.",
    "Alternatively: add features/bespoke_m250_grid.py to handle the 20-reel grid mechanic; declare in manifest.",
    "See memory/feedback_invariant_with_fallback_hides_drift.md for similar machines."
  ]
}
```

**Human-readable string** (for CLI / log output):
```
[ERROR] M250 mode 1: RTP integrity FAILED
  Layer 1 (sum invariant):     OK
  Layer 2 (fallback share):    FAIL — 100.0% in _unattributed_* (threshold 0.5%)
  Layer 3 (anchor coverage):   FAIL — missing required anchors: _bcm_cycle
  Summary: This machine's manifest declares it should have BCM cycle attribution,
           but the analyzer's current rule set is not producing the _bcm_cycle anchor.
  Suggested fix: see suggested_actions[]
```

### §9.4 How the error is surfaced to the operator

**Backend**:
- Every `pia.main` invocation runs `check_rtp_integrity` and attaches result to `summary.rtp_integrity_check`.
- If `passed == false`: the analyzer returns non-zero exit code (after writing summary; the summary itself is preserved for debug). Per `01 §2 layer 4` `RunManager.start_run` catches the exit code; the `runs` row is marked `status='failed'` with `failure_reason='rtp_integrity'`.
- Backend exposes `GET /api/runs/{rid}/integrity` — returns the structured result.
- Fleet-wide endpoint `GET /api/integrity/status` returns a roll-up: all machines with failing integrity.

**UI** (Phase 4 + Phase 5 wiring):
- Per-machine rwtree cell shows a red border + an "⚠ RTP integrity failed" badge.
- Click-through opens a modal with the full structured error message + suggested actions.
- Fleet dashboard tile: "X machines have RTP integrity failures" — links to filtered list.

**CLI / log**:
- `pia.main` prints the human-readable string to stderr on failure.
- Batch-run worker (`_batch_gen_worker.py`) propagates the error per job item; the batch result includes per-item integrity status.
- Background pull scripts log failures with the same format.

### §9.5 When the check runs

Per addendum §1.4: "the integrity check must run **on every fleet-wide pull**, not just on machine-specific tests."

Concretely:

| Trigger | When integrity check runs |
|---|---|
| Live sampling via `POST /api/runs` | At end-of-run, before summary write |
| In-process replay via `POST /api/rawdata/{m}/generate-report` | Same — after `pia.main()` returns |
| Batch generate-report `POST /api/rawdata/batch-generate-report` | Per item, after each subprocess run |
| Fleet-wide cron pull (e.g., nightly refresh) | Per machine after analyzer completes |
| On-demand fleet check `POST /api/runs/integrity-check-all` | Iterates all (machine, mode) with recent reports |
| Manifest validation `scripts/validate_manifests.py` | Static-only checks (no rawdata); flags machines that might fail Layer 2/3 |

The integrity check is **mandatory** — there is no flag to disable it globally. The only per-machine knob is `manifest.rtp_integrity_contract.exception_policy`:
- `"error"` (default) → integrity failure makes the run fail; operator must address.
- `"warn"` → integrity failure logs a warning but the run completes; UI shows warn badge. Reserved for explicit triage cases.

### §9.6 Interaction with manifest validation

When the manifest declares `analyzer_features = [F1, F2, F3]` and the RTP integrity check fails:

- **If Layer 2 fails (fallback share too high)**: the manifest claims F1/F2/F3 cover this machine's mechanics, but the analyzer's output shows otherwise. **Operator's job**: either (a) update the manifest to declare additional features (e.g., the bespoke one), (b) fix the existing features to handle this machine, or (c) explicitly downgrade `exception_policy` to "warn" with a documented reason.
- **If Layer 3 fails (missing anchors)**: the manifest claims anchor X should appear, but the analyzer didn't produce it. Usually means the round_win_rule that synthesizes X isn't applied (e.g., M274's `_bcm_cycle` anchor requires `bcm_cycle_anchor_m274` rule).

The check IS the enforcement mechanism for manifest correctness. A manifest is "correct" iff the integrity check passes for that machine on representative rawdata. There's no way to claim a manifest is correct in the abstract — the rawdata-driven check is the proof.

### §9.7 Known-broken machines triage (addendum §1.4 explicit reference)

Per memory `feedback_invariant_with_fallback_hides_drift.md`, the following machines are known-broken today and must be addressed during Phase 5:

| Machine | Mode | Current fallback share | Phase 5 action |
|---|---|---|---|
| M250 | 1 | ~100% | Bespoke feature `bespoke_m250_grid.py` (already in Phase 2 forcing function); manifest declares it; integrity passes. |
| M268 | 1 | ~70-90% | Bespoke feature `bespoke_m268_credits_symbol.py` (already in Phase 2); same. |
| M260 | 1 | ~70-90% | Bespoke feature `bespoke_m260_buffs.py` (already in Phase 2); same. |
| M264 | 1 | ~70-90% | Enable `cycle_peak_detection` in manifest; verify integrity. |
| M163 | 1 | ~35% | Enable `cycle_peak_detection`; verify. |
| M147 | 1 | ~35% | Enable `cycle_peak_detection`; verify. |
| M274 | 1 | (resolved via existing rule) | Confirmation only: M274's bcm_cycle_anchor rule already in place. |

By Phase 5 completion, every machine in the table has either passed integrity OR has explicit operator sign-off on `"warn"` policy. The default state for the fleet is "all machines have manifest + all manifests have passed integrity check on most recent fleet pull".

### §9.8 Memory cross-reference

The integrity gate directly implements the lesson from memory `feedback_invariant_with_fallback_hides_drift.md`:

> "兜底合成器（`_unattributed_st<N>` / `_unattributed_residual` 这类垃圾桶 label）应当被设计成 **告警信号** 而非 **静默关账机制**."

v2 makes this concrete: any `_unattributed_*` bucket > threshold → explicit per-machine error. Not a silent close-out.

Also implements memory `feedback_no_silent_swallow.md`:

> "任何 best-effort post-hook 都必须把 outcome 落盘"

The integrity check result is persisted (per-run in DB + per-summary in the report); never swallowed.

---

## §10 Resolution map — must-resolves / spec gaps / blockers

This section maps every Critic must-resolve + Validator gap + mapper blocker to where v2 addresses it. For each, name the section in v1 that was wrong (or absent) and the section in v2 that fixes it.

### §10.1 Critic 11 must-resolves (from `05 §7` change requests 1-15; 1-15 listed but 11 marked as Critic asks)

| # | Critic ask | v1 section that was wrong | v2 fix location |
|---|---|---|---|
| 1 | Reconcile "10× reduction" claim with historical change pattern (Concern 1, Q6) | v1 §1 + §3 + §4.2 | v2 §1.3 (honest blast table), §4.2 (worked examples), §4.5 (universal-feature honesty) |
| 2 | Spec Phase-2-pre-Phase-3 window (Concern 2, Q3) | v1 §6 phase 2 deliverable 13 | v2 §6 — addendum §1.2 clean break eliminates the window entirely; §6.6 honored constraint table reflects this |
| 3 | Decide MANIFEST_DRIFT severity (Concern 3, §7.4) | v1 §5.5 rule 4 (warning) | v2 §5.6 (strict error; addendum §1.2 enables it) |
| 4 | Resolve 5 mapper-§5 blockers (Concern 4, Q16) | v1 §7.9 (3 named, 2 missed) | v2 §6 Phase 1 deliverables 3, 10, 11, 12 + §5.8 (3-invocation parity) |
| 5 | Move heavy outlier conversion EARLIER (Concern 5, Q5) | v1 §6 phase 5 deliverable 2 | v2 §6 Phase 2 forcing function — 12 machines + workflow demo |
| 7 | Handle existing 2030 runs' NULL `effective_analyzer_version` (Q1) | v1 §6.6 (claimed no regen but didn't spec) | v2 §6 Phase 3 + addendum §1.2 — clean break, no NULL handling needed |
| 11 | Decide per-mode manifest dimension (Q11) | v1 §4.1 (no mode) | v2 §4.1 (mode added), §5.5 (`per_mode_overrides`) |
| 12 | Decide variant-fanout integration (Q12, §7.5) | v1 §7.5 (deferred) | v2 §5.5 (inherits_from semantic) |
| 13 | Plugin lifecycle / historical-report deserialization (Q10) | v1 (not addressed) | v2 §5.10 — addendum §1.2 simplifies (no historical preservation needed) |
| 14 | Define SCHEMA_VERSION bump policy (Q7, §7.8) | v1 §7.8 (deferred) | v2 §5.4 (explicit policy + CI enforcement) |
| 15 | Decide `_REQUIRED_ROUND_FIELDS` schema-gate placement (Q17, §7.1) | v1 §7.1 (deferred) | v2 §2.1 file tree (`core/schema_gate.py`), §6 Phase 2 deliverable 1.4 |

Critic also asked 4 implementation details (#6, #8, #9, #10) — these are addressed but as implementation detail:
- #6 (AnalyzerFeature.REQUIRES): v2 §5.2 (REQUIRES added)
- #8 (Plugin discovery + missing-plugin runtime error): v2 §5.7
- #9 (In-process monkey-patch path under sliced architecture): v2 §5.8
- #10 (Cover remaining 2 duplications — inference + schema-fingerprint): v2 §6 Phase 1 deliverables 5 + 6

### §10.2 Validator 4 spec gaps (from `06 §6.2`)

| Gap | v1 section | v2 fix |
|---|---|---|
| §3.1 / M99 / cluster gap (~42 non-cluster machines) | v1 §5.5 (assumed 6 super-clusters cover most) | v2 §5.5 — per-machine manifests with `inherits_from` (no super-cluster defaults; addendum §1.5 ends the super-cluster tier) |
| §3.2 / M37sim / virtual-side core engine blast | v1 §4.3 (out of scope but not explicit) | v2 §4.4 + §8.6 (explicit out-of-scope clause; addendum §3) |
| §3.3 / M15 / pre-migration freshness signal | v1 §6 phase 3 deliverable 5 | v2 §6 Phase 3 — addendum §1.2 clean break, pre-migration runs are stale; operator regens |
| §3.4 / M400 / feature discovery mechanism | v1 §5.2 (didn't fully spec) | v2 §5.7 (`feature_registry.ALL_FEATURES` + explicit @register) |

Validator also mentioned a bonus suggestion (M279 `bcm_cycle_anchor` enablement candidate):
- v2 §9.7 (known-broken machines triage table)

### §10.3 Mapper 5 pre-Phase-1 blockers (from `01 §5` #1, #3, #5, #7, #8)

| # | Mapper question | v1 section | v2 fix |
|---|---|---|---|
| #1 | 3 invocation styles — no spec saying they behave identically | v1 §7.9 (named, deferred to Critic) | v2 §5.8 + §6 Phase 1 deliverable 9 (parity test) |
| #3 | 3 summary md5 writers — cannot tell if they agree | v1 §6 phase 1 deliverable 2 (extract but no parity test) | v2 §6 Phase 1 deliverable 3 (parity test before extraction) |
| #5 | Frontend probe-and-fallback location | v1 §7.9 (named, deferred to Critic) | v2 §6 Phase 1 deliverable 11 (documented + audited) |
| #7 | `_classify_chunks` historical bucket feeding | v1 (not addressed) | v2 §6 Phase 1 deliverable 10 (explicit filter audit + regression test) |
| #8 | compareReports cache-bust race | v1 §7.9 (named, deferred to Critic) | v2 §6 Phase 1 deliverable 12 (explicit error handling) |

All 5 blockers resolved within Phase 1 BEFORE Phase 2 commits.

---

```
arch-designer complete.
- Version: v2
- Alternatives explored: 3 (A v2 recommended; B rejected per addendum §1.4 non-viability; C rejected per addendum §1.5 overshoot)
- Recommended: Alternative A v2 — per-machine manifests + sliced analyzer + RTP integrity gate (no default-cluster tier)
- Hash composition: per-(machine, mode) effective_analyzer_version = sha256(base_hash || sorted(feature_hashes_M_uses) || mode)[:12]
- Migration phases: 6 (1 foundation+globals+5-blockers, 2 slice-analyzer+12-forcing-function, 3 per-machine-manifests-clean-break, 4 frontend-registry+SCHEMA_VERSION-enforcement, 5 RTP-integrity-gate, 6 optional-consolidation)
- Critic must-resolves addressed: 11/11
- Validator spec gaps addressed: 4/4
- Mapper pre-Phase-1 blockers addressed: 5/5
- New section: §9 RTP integrity enforcement (constraint S; addendum §1.4)
- Out-of-scope items: 12
- Open questions for Wave 3 v2: 4 (down from v1's 9)
- Output: session_artifacts/_arch/04_architecture_proposal_v2.md
```
