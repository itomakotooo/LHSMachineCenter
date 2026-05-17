# Architecture Proposal v4 — rawdata → analyzer → console pipeline (Wave 2 v4 iteration)

> Wave 2 v4 deliverable from `arch-designer` (running on general-purpose harness; self-constrained to designer role). **Focused 3-issue revision of v3**, NOT a full rewrite. Reuses 80%+ of v3 verbatim.
>
> Changes vs v3 (the three issues from addendum v4 §1):
> - **§9.4 Layer 4 algorithm rewrite** (Change ①, HARD): replaces v3's Layer 4 with an independent rawdata-level cross-check. v3's Layer 4 compared two readouts of the same in-memory dict `payout_id_by_spin_type_total` — trivially equal, catches nothing about dispatch routing. v4's Layer 4 performs a fresh rawdata scan (Step A: capture analyzer dispatch result; Step B: independent re-scan of rawdata chunks; Step C: assert equality per (pid, ST) pair). This actually catches M31 pid-8 style dispatch-routing bugs that v3 missed.
> - **§6.3 Phase 3 Day-1 strict candidates** (Change ②, HARD): v3 shipped all 421 machines as `console_diagnostic_complete: false` with no plan. v4 §6.3 enumerates explicit Day-1 strict candidates (SC-Vanilla 45 + M274 + other empirically-clean machines) with flip criteria, converting "all-false at cutover" to "obvious-clean-flipped, rest-false-default".
> - **§5.5.7 variant cascade for completeness flag** (Change ③, SOFT): v3 declared variants have independent `console_diagnostic_complete` (per-variant), inconsistent with §5.5.4's "variants ARE the same machine" justification for eager analyzer_features cascade. v4 makes the flag cascade eagerly from underlying to variants, with an override-only-true-to-false safety valve.
>
> Unchanged from v3 (validated by Wave 3 v3 reviews):
> - §1 + §9.1 operator-diagnostic framing (addendum v3 §1 reframe)
> - Layers 1, 2, 3 of integrity check (§9.2)
> - `console_diagnostic_complete` mechanism core (§5.5.3)
> - §5.5.4 variant analyzer_features eager cascade
> - Phase 2 builds gate code, Phase 5 flips default policy (§6.2, §6.5)
> - Hash composition algorithm (§4)
> - 6-phase migration framework (§6)
> - Plugin Protocol (§5.2), manifest schema baseline (§5.5.1–§5.5.2)
> - All v3 §8.1–§8.12 out-of-scope items (§8)
>
> **Date**: 2026-05-17
> **Brief**: `00_brief.md` + `00_brief_v2_addendum.md` + `00_brief_v3_addendum.md` + `00_brief_v4_addendum.md` (v4 addendum supersedes §5.5.7, §6.3, §9.4)
> **v3**: `04_architecture_proposal_v3.md` (1261 lines)
> **v3 reviews**: `05_critique_v3.md` (APPROVE-WITH-REVISIONS; 2 hard + 1 soft must-resolves) + `06_validation_v2.md` (APPROVE; re-used as basis for Day-1 candidate list in §6.3)
> **Repo root**: `User_Managerment_GPT/`

---

## §1 Problem statement (unchanged from v3 — operator-diagnostic framing)

### §1.1 The operator-diagnostic premise

The production console exists to serve a single, specific person: the **operator (策划)** who configures slot machines for the production fleet. The operator picks paytable values, weights, feature parameters, and RTP targets, then ships the resulting configuration to production. The machine code itself is **not** the source of error — production machines faithfully execute whatever the operator configured. The **rawdata** captured from production reflects exactly what the configuration produced, which **may be off-target if the operator misconfigured something** (a typo in a weight, wrong RTP target, mismatched paytable rows, etc.).

User's exact framing (from addendum v3 §1, verbatim):

> "console 的诉求是帮我分析真机数据,找到问题并优化,所以 console 必须要是正确的,真机数据是有可能存在错误的。包括刚刚我说的 rtp 报错,也是 console 认为分析不出机器的 rtp 报错。"

> "rawdata 错的意思不是机台的逻辑和数据错误,就是比如策划 rtp 配错了,手滑了,之类的。"

The console's job, therefore, is **not** to certify the machine produced "correct" RTP in some absolute sense. The operator owns the configuration. The console's job is to **analyze the rawdata correctly so it can tell the operator whether the configuration produced the intended result**. When the operator looks at a console report and sees RTP, payout distribution, hit rates, or per-SpinType attribution, those numbers must be the actual analysis of rawdata — not a synthesized estimate, not a silent fallback, not a "we couldn't tell so we made one up".

This is the load-bearing inversion vs v2's framing:

| Aspect | v2 (incorrect) | v3/v4 (corrected per addendum) |
|---|---|---|
| What "RTP error" means | Internal analyzer bug | Console claims it cannot reliably analyze this machine right now |
| What console is | An internal correctness checker | A diagnostic tool for the operator |
| What "correctness" means | RTP statistically matches a target | Console's logic accurately reflects rawdata into the report |
| What happens when console can't analyze | Silent fallback to a synthesized number (today's `_unattributed_st<N>`) | Explicit per-machine error with actionable diagnosis hints |
| Who owns "machine RTP is wrong" | Console (which would auto-fix or warn) | **Operator** (who debugs their own configuration) |

The architecture's purpose, rewritten per this framing:

> **The architecture must deliver per-machine, accurate-or-explicitly-error diagnostic signals to the operator across 421+ machines, while supporting cheap addition of new machines / new features without invalidating unrelated reports.**

The data chain:

```
[Operator]                          [Production machine]                  [Console]
  configures                          executes configuration                analyzes rawdata
  paytable + weights        ───►      faithfully               ───►        produces report
  + RTP target                        emits rawdata
                                                                           Either:
                                                                           (a) correct numbers → operator validates / debugs
                                                                           (b) explicit per-machine error → operator investigates
                                                                              (cause: operator misconfig OR console rule gap OR data corruption)
```

`console correct ∧ machine configured correctly → RTP signal trustworthy.` The console must be correct so its signals are trustworthy.

### §1.2 Five concrete pain points (each cited from Wave 1)

1. **Universal `analyzer_version` stamp invalidates 1007 (machine, mode) pairs on any byte change** —
   `compute_analyzer_version()` at `fresh_slotlab/player_impact_analyzer.py:2141` SHA256s the entire 8,176-line file. Per `03 §3.3` live DB measurement, 2030 completed runs across 1007 distinct (machine, mode) pairs get flagged `stale_analyzer` by `/api/reports/stale-count` on any comment-only edit. **v4 fix**: per-machine `effective_analyzer_version` composed from base hash + feature hashes the machine declares (§4).

2. **Schema renames silently break 17 frontend renderers** — `03 §4.3` tabulates ~30 schema fields × 17 renderers. **v4 fix**: explicit `SCHEMA_VERSION` per feature + frontend renderer registry with declared fallback rules (§5.3 + §5.4).

3. **Real-fleet hash is upstream, virtual hash is local** — `03 §3.4` measured 421 entries in `configs/machines.json` get `codeSummaryMd5` from upstream `/MachineConfigMd5`; `compute_code_md5(machine_name)` only feeds 6 virtual entries. **v4 stance**: preserved (out of scope per addendum §3).

4. **Duplication concentrated in md5 + summary-patch + session-CI + inference triggers** — `01 §4` itemizes six duplications. **v4 fix**: Phase 1 extracts ALL SIX (covered by v2 Phase 1; v4 keeps the same).

5. **Module globals + import-time side effects are latent suicide bombs** — `03 §4.1` enumerates 11 references to `RAWDATA_ROOT`, 33 module globals in the analyzer. Memory `feedback_subprocess_import_suicide_and_module_globals.md`. **v4 fix**: Phase 1 dependency injection (covered by v2).

### §1.3 The §9 framing change — operator diagnostic, not internal assertion

Memory `feedback_invariant_with_fallback_hides_drift.md` measured fleet-wide: 55 of 117 cached BCM (m, mode) pairs have >0.5% RTP falling into `_unattributed_st<N>` fallback buckets (M250 100%, M268/M260/M264 70-90%, M163/M147 ~35%). v2 framed this as an "internal RTP correctness" problem and built a 3-layer gate with a numeric threshold. **v3/v4 reframes**: the fallback bucket is the symptom that the **console couldn't analyze this machine**. The architectural response is not "is RTP correct? fail if not", but **"can the console deliver a trustworthy signal to the operator? if not, say so explicitly with actionable diagnosis"**.

The reframe matters for two design decisions:

- The check is no longer a threshold gate (statistical noise can trip a threshold); it's a per-machine **completeness declaration** (operator-side concept; see §5.5 / §9).
- The check has 4 layers in v3/v4 (was 3 in v2), with **Layer 4** (v4 revised) catching dispatch-routing bugs at the rawdata level — the mis-attribution case v2's 3 layers missed and v3's same-accumulator Layer 4 also missed (Critic v3 Concern 2 / Issue ① in addendum v4).

### §1.4 Headline blast-radius framing (per addendum v2 §1.1, kept from v2/v3)

| Change class | Blast under current architecture | Blast under proposal | Reduction |
|---|---|---|---|
| **Per-cluster feature edit** (e.g., adding BCM cleanup rule) | 421 machines | 12-30 machines (one cluster) | 12-30× |
| **Per-machine bespoke fix** (e.g., M21 Buffalo-counter tweak) | 421 machines | 1 machine | 421× |
| **Novel machine onboarding** (M400 with new feature plugin) | 421 machines | 1 machine (only declarant) | 421× |
| **Universal feature edit** (e.g., renaming a field used by every machine) | 421 machines | 421 machines | **1× (no reduction by design)** |
| **Frontend renderer plugin update** | varies (silent break risk) | machines using that renderer; schema-version gated | varies + safety improvement |
| **Bespoke-plugin lift for a previously-vanilla machine** | 421 (added to monolith) | 1 (new bespoke feature + manifest line) | 421× |
| **Schema rename inside a universal feature** | 421 + silent renderer break | 421 + explicit fallback rule applied | 1× invalidation but 0× silent break |

Universal-feature-edit class is explicitly **1× by design** — the proposal does not fake reduction.

---

## §2 Design alternatives

v4 keeps v3's 3 alternatives unchanged. Alternative A v4 is the recommended variant, refining A v3 per the v4 addendum.

### §2.1 Alternative A v4 — Per-machine manifests + sliced analyzer + operator-diagnostic console signal (recommended)

**Core idea (unchanged from A v3)**: Every one of the 421 machines has an explicit manifest declaring (a) which feature plugins it uses, (b) which round-win rules it uses, (c) **whether the console claims it can diagnose this machine completely** (the `console_diagnostic_complete` flag). The analyzer is sliced into `core/` (universal orchestration) + `features/` (opt-in). The per-machine effective analyzer version composes from base + the features the manifest declares.

**Key changes from A v3** (v4-specific):

- §9.4 Layer 4: **independent rawdata-level cross-check** (Step A/B/C) replacing v3's same-accumulator self-consistency check that Critic v3 proved couldn't catch dispatch-routing bugs
- §6.3 Phase 3: **explicit Day-1 strict candidates** enumerated (SC-Vanilla 45 + M274 + empirically-clean machines from Validator v2 walkthroughs), plus flip criteria
- §5.5.7: **variant cascade for completeness flag** from underlying to variants (with override-only-true-to-false valve), consistent with §5.5.4's "variants ARE the same machine" thesis

**Pros (grounded in Wave 1)**:

- Implements addendum §1.5 philosophy — every machine has a manifest; sharing is opt-in via plugin composition.
- Implements addendum §1.4 constraint S **and** addendum v3 §1 operator-diagnostic framing — the console either delivers correct numbers OR an explicit per-machine error with actionable diagnosis hints.
- v4's Layer 4 (§9.4) performs an independent rawdata re-scan (Step B), not a same-dict readout, catching the dispatch-routing bug class Critic v3 identified as uncaught by v3.
- The Day-1 strict candidates list (§6.3) means Phase 5 is not dormant — at least 46+ machines carry actual strict-mode coverage on day one.
- Variant completeness cascade (§5.5.7) is now consistent with §5.5.4: variants ARE the same machine, so they share parser quality and share diagnostic completeness.

**Cons (acknowledged)**:

- Layer 4 Step B adds an extra rawdata pass (~5s per machine per fleet pull). This is the cost of catching dispatch-routing bugs. The check is enabled for all machines in warn-only for `complete: false`; strict for `complete: true`.
- Day-1 strict candidates require pre-Phase-5 verification runs. This adds ~0.5 days of pre-cutover work.
- Variant cascade means flipping the underlying to `true` also flips all its variants. Operators must verify underlying quality covers variant data shapes.

**Migration cost estimate**: MEDIUM-HIGH (same as A v3). v4 adds minimal overhead.

### §2.2 Alternative B — Lightweight per-feature SCHEMA_VERSION sidecar (rejected as in v2/v3)

**Why B remains rejected in v4**: B doesn't implement the operator-diagnostic framing from addendum v3 §1. Under B, the console has no per-machine completeness signal and cannot implement v4's Layer 4 rawdata cross-check. Addendum v3 §1's framing strengthens the rejection.

### §2.3 Alternative C — Full per-machine analyzer plugin tree (rejected as in v2/v3)

**Why C remains rejected in v4**: C eliminates sharing wholesale; addendum §1.5 says "sharing is opt-in via manifest". v4's §5.5.7 variant cascade fix is the opposite of C's "no sharing" stance. C would force 166 per-variant plugin files (parallel-impl anti-pattern per memory `feedback_no_parallel_panel_impl.md`).

### §2.4 Comparison table (v4 update)

| Criterion | A v4 (recommended) | B (sidecar) | C (per-machine plugins) |
|---|---|---|---|
| Implements addendum v3 §1 operator-diagnostic framing | YES | NO | PARTIAL |
| Implements addendum §1.5 philosophy (every machine potentially unique) | YES | NO | OVERSHOOTS |
| Implements addendum §1.4 constraint S | YES (§9 with 4 layers including v4 Layer 4) | NO | PARTIAL |
| **v4 Layer 4 catches dispatch-routing bugs (Critic v3 M1)** | **YES — Step B independent rawdata scan** | NO | PARTIAL |
| **Day-1 strict candidates enumerated (Critic v3 M2)** | **YES — §6.3 names 46+ machines** | NO | NO |
| **Variant completeness cascade consistent (Critic v3 S1)** | **YES — §5.5.7 eager cascade with true→false-only override** | NO | NO |
| `inherits_from` cascade semantics resolved | YES — eager per addendum v3 §3 #4 | n/a | n/a |
| Phase 2 RTP-gate dependency resolved | YES — gate code in Phase 2 | n/a | n/a |
| `console_diagnostic_complete` per-machine flag | YES | NO | NO |
| Solves universal feature-edit blast | NO by design (honest about 1×) | NO | NO |
| Solves schema-rename silence | YES | YES | YES |
| LOC delta estimate | +3,500-4,000 | +250 | +12,000 |
| Migration risk | MEDIUM-HIGH | LOW | HIGH |

---

## §3 Recommended design — Alternative A v4

**Pick: Alternative A v4** (per-machine manifests + sliced analyzer + operator-diagnostic signal with 4-layer integrity check including rawdata-level Layer 4 + per-machine completeness flag with Day-1 strict candidates + consistent variant cascade).

**Reasoning** (cited from Wave 1 + addendum + Wave 3 v3 reviews):

1. **A v4 closes the Layer 4 hole identified by Critic v3** — Critic v3 Concern 2 verified by reading `fresh_slotlab/player_impact_analyzer.py:6438-6509` that v3's Layer 4 compared two readouts of the same dict `payout_id_by_spin_type_total`. Both `payouts_by_spin_type[label].rows[pid].hit_count` (line 6493) and `payout_ids_top20.rows[pid].spin_type_breakdown[N].count` (line 6446 via `st_hits`) read from the same dict. If the dispatch into the dict is wrong, both sides are equally wrong. v4's Layer 4 Step B performs a fresh rawdata scan — iterating chunks independently without going through the analyzer's dispatch path — eliminating the trivially-true self-consistency check.

2. **A v4 delivers Day-1 strict-mode coverage** — Critic v3 Concern 1 identified that v3's all-false default at Phase 3 cutover leaves Phase 5's strict-error mechanism with zero members on day one, risking permanent dormancy. v4 §6.3 enumerates the obvious-eligible machines (SC-Vanilla 45 machines per `02 §4.2`, M274 per Validator v2 §2.6 empirical pass) and provides flip criteria so the mechanism engages on day one.

3. **A v4 makes variant completeness consistent with variant parser sharing** — Critic v3 Concern 3 identified an incoherence: §5.5.4 says variants ARE the same machine for parser purposes (analyzer_features cascades eagerly), but §5.5.7 said variants have independent `console_diagnostic_complete`. v4 §5.5.7 closes the gap: variants inherit `console_diagnostic_complete` from their underlying (eager cascade), with override allowed only true→false.

4. **A v4 preserves A v3's validated parts** — Validator v2 gave clean APPROVE on hash composition, manifest schema mechanics, Plugin Protocol, file tree, Phase 1 deliverables. Validator v2 §2.6 empirically confirmed M274's 4-layer pass on live data (all 9 pids, 0 `_unattributed_*` rows, sum(pid rtp_pp) == summary.rtp). v4 keeps all of these unchanged.

5. **B is rejected** per §2.2. **C is rejected** per §2.3.

The remaining sections specify A v4 in detail.

---

## §4 Hash composition rules (unchanged from v2/v3)

v2's algorithm validated cleanly by Wave 3 v2 (Validator §4 cross-product 0 regressions). v3 kept it unchanged. v4 keeps it unchanged.

### §4.1 The composition algorithm (unchanged)

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
    mode: int | None = None,
) -> str:
    """Per-machine (optionally per-mode) effective hash.

    Composition:
      h = sha256(base_hash)
      for fid in sorted(set(machine_features)):
        h.update(b"\\x00" + fid + b"=" + feature_hashes[fid])
      if mode is not None:
        h.update(b"\\x00mode=" + str(mode))
      return h.hexdigest()[:12]
    """
```

The per-(machine, mode) effective version is:

```
effective_analyzer_version(M, mode) =
    sha256( base_hash ||
            "\\x00".join(f"{fid}={feature_hashes[fid]}" for fid in sorted(manifest[M, mode].analyzer_features)) ||
            f"\\x00mode={mode}"
          )[:12]
```

### §4.2 Per-change-class blast table (unchanged from v2/v3)

See §1.4 above. Six change classes; only one (universal-feature edit) stays at 1×, the rest reduce by 12-421×.

### §4.3 Worked examples — invalidation radius

Six examples carried unchanged from v2 §4.3. Example 6 (M250 graduation: vanilla → bespoke) is executable in Phase 2 because the RTP gate code is built in Phase 2.

### §4.4 Per-machine config_md5 and code_md5 — virtual side unchanged

Unchanged from v2/v3 §4.4. Out of scope per addendum §3.

### §4.5 Honesty about universal-feature changes

Unchanged from v2/v3 §4.5. The proposal does not claim to reduce blast for universal feature changes; it makes more features non-universal so the path of least resistance changes over time.

### §4.6 Hash composition map (unchanged from v2/v3 §4.6)

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

Per addendum §1.2 clean break: no compatibility layer for pre-v3 reports.

---

## §5 Plugin / extension Protocol + manifest

v2's Protocol + manifest mechanics validated by Wave 3 v2. v3 updated §5.5 for `console_diagnostic_complete` flag, variant justification, eager cascade, and `per_mode_overrides` field enumeration. v4 updates **§5.5.7 only** (variant cascade for completeness flag, Change ③). All other sections unchanged from v3.

### §5.1 Three plugin axes (unchanged from v2/v3 §5.1)

| Axis | Existing artifact | v4 contract |
|---|---|---|
| Round-level extraction | `RoundWinRule` ABC at `round_win.py:102` + RULE_REGISTRY at `:423` | Formalized as-is; manifest declares rule_ids |
| Summary-level aggregation | (today: inline in `parse_chunk_response` + `main()`) | NEW `AnalyzerFeature` Protocol with REQUIRES + RTP_CONTRIBUTION flag |
| Frontend rendering | (today: 17 inline renderers; no contract) | NEW renderer registry with explicit fallback rules |
| **[v3 NEW]** Console diagnostic completeness | (today: silent `_unattributed_st<N>` synthesizer) | Per-machine `console_diagnostic_complete` boolean in manifest + 4-layer integrity check per §9 |

### §5.2 `AnalyzerFeature` Protocol (unchanged from v2/v3 §5.2)

```python
# fresh_slotlab/analyzer/features/_base.py (NEW)
from abc import ABC, abstractmethod
from typing import ClassVar, Any
import hashlib
from pathlib import Path

class AnalyzerFeature(ABC):
    """Versioned, opt-in slice of analyzer functionality."""

    FEATURE_ID: ClassVar[str] = ""
    SCHEMA_KEYS: ClassVar[tuple[str, ...]] = ()
    SCHEMA_VERSION: ClassVar[int] = 1
    REQUIRES: ClassVar[tuple[str, ...]] = ()
    RTP_CONTRIBUTION: ClassVar[bool] = False
    REGISTERED_FALLBACK_RULES: ClassVar[dict[int, dict]] = {}

    @abstractmethod
    def extract(self, parse_state, chunk_dict) -> dict: ...

    @abstractmethod
    def reduce(self, prev_acc, this_acc) -> Any: ...

    @abstractmethod
    def emit(self, final_acc, summary: dict) -> None: ...

    @classmethod
    def compute_hash(cls) -> str:
        src = Path(cls.__module__.replace(".", "/") + ".py")
        return hashlib.sha256(src.read_bytes()).hexdigest()[:12]
```

### §5.3 Frontend renderer registry (unchanged from v2/v3 §5.3)

```typescript
// src/web_console/frontend/renderers/registry.js (NEW)
interface RendererPlugin {
  readonly id: string;
  readonly schemaKey: string;
  readonly minSchemaVersion: number;
  readonly maxSchemaVersion: number;
  readonly fallbackRules?: Record<number, FallbackMap>;
  render(summary: object, host: HTMLElement, ctx: RendererCtx): void;
}
```

### §5.4 SCHEMA_VERSION bump policy (unchanged from v2/v3 §5.4)

The table is identical to v2's. Pre-commit hook enforcement; fallback test required for any non-trivial bump. Resolves Critic v1 Q7 + §7.8.

### §5.5 Per-machine manifest format — v4 change in §5.5.7

Sections §5.5.1 through §5.5.6 are identical to v3. The v4 change is in §5.5.7 (variant cascade for `console_diagnostic_complete`).

#### §5.5.1 Layout (unchanged from v2/v3)

```
slot_designer/configs/machine_manifests/
  M1.json
  M14.json
  M15.json
  M15$TopDollarSelector$0$.json    # variant — see §5.5.4
  M21.json
  M260.json
  M274.json
  M279.json
  ...
  manifest_schema.json             # JSON Schema for validation
```

#### §5.5.2 Manifest schema (per-machine file) — v3/v4 form (unchanged from v3)

Full schema with M274 as example:

```json
{
  "machine_id": "M274",
  "manifest_version": 1,
  "inherits_from": null,
  "console_diagnostic_complete": true,
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
      "analyzer_features_remove": ["bonus_chain_dynamics"]
    }
  },
  "rtp_integrity_contract": {
    "expected_paid_st": [140],
    "expected_bonus_st": [139],
    "required_attribution_anchors": ["_bcm_cycle", "5801"]
  }
}
```

No `fallback_share_threshold_pct`, no `exception_policy`. The `console_diagnostic_complete` boolean is the single per-machine completeness signal.

#### §5.5.3 `console_diagnostic_complete` semantics (unchanged from v3)

**`console_diagnostic_complete: true`** — the operator declares "console claims it can diagnose this machine correctly":

- All 4 layers from §9 enforced as **hard errors** if they fail
- Failure blocks the individual machine's report write
- Does NOT block the fleet pull — other machines' reports continue to be produced
- Error message guides the operator per §9.3 format with actionable diagnosis hints

**`console_diagnostic_complete: false`** — used during development of new machine support:

- All 4 layers from §9 are still computed but their failure produces a **warning**, not an error
- Report is still produced + flagged "[INCOMPLETE]" in the summary metadata + visible in the rwtree UI
- Migration path: flip to `true` when rules are verified clean per §6.3.2 criteria

**Initial values at Phase 3 cutover** (v4 update): most machines ship `false`; Day-1 strict candidates (§6.3.1) ship `true`. See §6.3 for the enumerated list and flip criteria.

**Why this is better than v2's numeric threshold**: Critic v2 Concern 2 false-positive cliff disappears; Q16 threshold authority question disappears; semantics align with operator-diagnostic framing.

#### §5.5.4 Variant justification (unchanged from v3)

`inherits_from` for variants is intentional. Variants represent the same underlying machine with different user-decision configurations. Analyzer rules and parsing must be identical between a variant and its underlying — they read the same rawdata schema from the same machine code. Storage and reports are isolated per variant because user-decision histories differ. `inherits_from` lets the variant manifest reuse the underlying's `analyzer_features` list by reference.

**This is NOT cluster-by-inheritance.** The parser sharing is **by definition** because variants ARE the same machine. There is no similarity assumption to be wrong about. (Full paragraph preserved in v3 §5.5.4 verbatim.)

#### §5.5.5 Variant cascade — eager (unchanged from v3)

When an underlying machine's manifest changes, all variants pick up the change immediately. Variants ARE the same machine; their parser cannot drift from the underlying's parser. Lazy resolution would create a silent correctness bug. Hash-composition consequence: when M273.json changes, all 86 hashes (1 underlying + 85 variants) flip — correct behavior. (Full section preserved in v3 §5.5.5 verbatim.)

#### §5.5.6 Fields that support `per_mode_overrides` (unchanged from v3)

| Field | Override syntax | Example use case |
|---|---|---|
| `analyzer_features` | `analyzer_features_add: [...]`, `analyzer_features_remove: [...]` | M274 mode 5 removes `bonus_chain_dynamics` |
| `round_win_rules` | `round_win_rules_add: [...]`, `round_win_rules_remove: [...]` | M-something where one mode uses a different rule set |
| `bcm_target_feature` | `bcm_target_feature_override: "<feature_name>"` | M279 mode 1 = Wheel, modes 2/5/7 = MoveSpin |
| `trigger_session_pattern` | `trigger_session_pattern_override: "type_1" \| "type_2" \| null` | machines where session pattern differs per mode |
| `spin_type_convention` | `spin_type_convention_override: {"paid": [...], "bonus": [...]}` | rare; for machines whose ST set differs per mode |
| `feature_tags` | `feature_tags_override: [...]` | rare; for tagging mode-specific behavior |
| `rtp_integrity_contract.required_attribution_anchors` | `required_attribution_anchors_override: [...]` | M279 mode 1 (Wheel) requires `27905`; modes 2/5/7 (MoveSpin) require different anchors |
| `rtp_integrity_contract.expected_paid_st` / `expected_bonus_st` | `expected_paid_st_override: [...]`, `expected_bonus_st_override: [...]` | machines where ST set differs per mode |

Fields that **do NOT** support `per_mode_overrides`: `machine_id`, `manifest_version`, `inherits_from`, `console_diagnostic_complete` (per-machine; cascade semantics in §5.5.7).

**Resolution order**: `per_mode_overrides.<mode>` first applies `_remove` operations to the base list, then applies `_add` operations.

#### §5.5.7 Variant cascade for `console_diagnostic_complete` (v4 CHANGE ③ — replaces v3 §5.5.7)

**v4 change**: Variants inherit `console_diagnostic_complete` from their underlying machine (eager cascade), matching the `analyzer_features` cascade in §5.5.4–§5.5.5. This replaces v3's per-variant independent flag.

**Rationale**: v3 §5.5.4 justifies eager cascade for `analyzer_features` on the basis that "variants ARE the same machine" — they share the same parser, the same SpinType convention, the same RoundWinRule logic. The same logic applies to `console_diagnostic_complete`: variants share the parser, so they share parser quality, so they share diagnostic capability. If the underlying machine's diagnostic coverage is incomplete (i.e., `false`), all its variants are equally incomplete for the same reason — they all use the same parser that has the gap. If the underlying is verified complete (i.e., `true`), all variants are equally complete — they share the same verified parser.

v3's per-variant independent flag was inconsistent with this thesis. Critic v3 Concern 3 identified the incoherence: §5.5.4 says "variants ARE the same machine" for parser purposes but v3 §5.5.7 implied "variants are NOT the same machine" for completeness purposes.

**Cascade mechanism**:

```
Underlying M273.json: console_diagnostic_complete = true
   |
   +──> M273$WheelSelector$0$.json: inherits_from = "M273.json"
   |      resolved console_diagnostic_complete = true (cascaded from underlying)
   |
   +──> M273$WheelSelector$42$.json: inherits_from = "M273.json"
          resolved console_diagnostic_complete = true (cascaded from underlying)
```

**Override — true → false only** (regression valve):

A variant may declare an explicit `console_diagnostic_complete_override: false` in its manifest. This is the **only** permitted override direction. It applies when:
- The underlying is `true` (verified complete), AND
- A specific variant's user-decision data has surfaced an edge case not present in the underlying's rawdata (e.g., a rare selector path that triggers a parser gap)

The override is **never** used to elevate `false → true`. A variant cannot claim to be more complete than its underlying; the underlying's flag controls the floor.

**Variant manifest with override (regression case)**:

```json
{
  "machine_id": "M273$WheelSelector$42$",
  "manifest_version": 1,
  "inherits_from": "M273.json",
  "console_diagnostic_complete_override": false,
  "_comment": "Override: this selector index triggers an uncommonly-deep Wheel nesting path not present in M273 underlying's rawdata sample. Layer 2 fires on a ~0.4% RTP fallback bucket for a specific wheel stop combination. Investigated 2026-05-17; bespoke rule pending. Flip when rule verified."
}
```

**Variant manifest without override (the common case)**:

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

No `console_diagnostic_complete` field present — the resolver reads from the underlying's manifest.

**Resolver logic**:

```python
_UNSET = object()

def resolve_completeness(variant_manifest, underlying_manifest) -> bool:
    """Resolve console_diagnostic_complete for a variant.

    Cascade rule: underlying's value is the default.
    Override rule: variant can only go true → false (regression valve).
    Override false → true is rejected at manifest validation time.
    """
    underlying_complete = underlying_manifest["console_diagnostic_complete"]
    override = variant_manifest.get("console_diagnostic_complete_override", _UNSET)
    if override is _UNSET:
        return underlying_complete
    if override is False:
        return False   # regression valve: variant found an edge case
    # override is True — validation should have caught this at commit time
    raise ManifestValidationError(
        f"{variant_manifest['machine_id']}: console_diagnostic_complete_override: true "
        f"is not permitted. Variants cannot elevate completeness above their underlying. "
        f"Underlying {underlying_manifest['machine_id']} is the authoritative source."
    )
```

**Operational consequence**: when M273 is flipped to `true` (underlying verified complete), all 85 variants automatically become strict. The operator must verify that the underlying's parser quality covers the variant data shapes — guaranteed by the §5.5.4 parser-sharing premise.

**Blast-radius implication for flip decisions**: flipping the underlying to `true` also flips all 85 variants. The flip criteria in §6.3.2 (below) apply to the underlying; passing the criteria implies all variants are also covered.

**Exception audit log**: any `console_diagnostic_complete_override: false` on a variant must be accompanied by a `_comment` field explaining which edge case triggered it. git history provides the audit trail.

**Manifest validation rule (added to §5.6 rule 6)**: `console_diagnostic_complete_override: true` on any variant manifest is rejected at commit time with error: "Variants may not elevate completeness above their underlying. Remove the override or set it to false."

### §5.6 Manifest validation rules — strict (updated for v4 §5.5.7)

1. Every machine in `configs/machines.json` MUST have a manifest file. Missing file = error.
2. Every `analyzer_feature` ID MUST correspond to a class in `feature_registry.ALL_FEATURES`. Typo = error.
3. Every `round_win_rule` ID MUST be defined in `configs/machine_round_win_rules.json` with this machine in `applies_to`.
4. REQUIRES dependency satisfaction.
5. Mode coverage: for every mode in `modes_supported`, the resolved per-mode feature set must include all RTP_CONTRIBUTION=True features that the integrity contract requires.
6. Non-variant manifests: `console_diagnostic_complete` MUST be a boolean. Variant manifests: the field is either absent (inherited from underlying) or `console_diagnostic_complete_override: false` only. **v4 NEW**: `console_diagnostic_complete_override: true` on any variant manifest is a validation error.
7. `expected_paid_st` + `expected_bonus_st` non-empty; `required_attribution_anchors` validated at first run (not commit time) against rawdata.
8. **v3 NEW**: if `console_diagnostic_complete: true`, every feature in `feature_registry.ALL_FEATURES` whose `RTP_CONTRIBUTION=True` flag is set MUST be present in the manifest's `analyzer_features`. (This ensures complete machines declare all RTP-contribution features registered in the system, not just any subset they chose.)
9. Rawdata sanity check (if rawdata available; 206 of 421 machines):
   - Declared `spin_type_convention.paid` must match observed paid-ST set.
   - If `wild_nudge_classification` is NOT declared but rawdata has ST=36+ReMarks=move, error.
   - If `cycle_peak_detection` is NOT declared but rawdata has `CollectCount` extras, error.
   - If `pay_id_suffix_attribution` is NOT declared but rawdata has line_id values not matching pay_id keys, error.

### §5.7 Feature discovery + missing-feature runtime error (unchanged from v2/v3 §5.7)

`@register` decorator + manual import in `fresh_slotlab/analyzer/features/__init__.py`. `feature_registry.ALL_FEATURES` runtime source of truth. Manifest typo caught at validation; runtime missing-feature raises `RuntimeError` clearly.

### §5.8 In-process monkey-patch path under sliced architecture (unchanged from v2/v3 §5.8)

`pia.main` remains entry point post-slice; thin orchestrator delegating to `analyzer/core/base_pipeline.py`. Monkey-patches attach at same attribute. Phase 1 deliverable 9 codifies 3-style parity test.

### §5.9 Per-machine `round_win_rule` plugin (unchanged from v2/v3 §5.9)

`round_win.py:102` ABC + RULE_REGISTRY unchanged. Manifest references rule_ids.

### §5.10 Plugin lifecycle (unchanged from v2/v3 §5.10)

Adding / deleting / renaming features; historical reports per addendum §1.2 clean-break.

### §5.11 Manifest examples — v4 form

**M1** (vanilla, SC-Vanilla — Day-1 strict candidate per §6.3.1):

```json
{
  "machine_id": "M1",
  "manifest_version": 1,
  "inherits_from": null,
  "console_diagnostic_complete": true,
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
    "expected_paid_st": [1],
    "expected_bonus_st": [],
    "required_attribution_anchors": []
  }
}
```

Note: v4 ships M1 as `true` at Phase 3 cutover (Day-1 candidate; SC-Vanilla cluster member per `02 §4.2`). v3 shipped it as `false`.

**M15** (TopDollar, rule-bearing — starts `false`; requires topdollar rule verification):

```json
{
  "machine_id": "M15",
  "manifest_version": 1,
  "inherits_from": null,
  "console_diagnostic_complete": false,
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
    "expected_paid_st": [1],
    "expected_bonus_st": [14, 15],
    "required_attribution_anchors": ["666"]
  }
}
```

**M274** (BCM + Wheel — Day-1 strict candidate per §6.3.1 Group B, pending Layer 4 v4 re-verification):

```json
{
  "machine_id": "M274",
  "manifest_version": 1,
  "inherits_from": null,
  "console_diagnostic_complete": true,
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
      "analyzer_features_remove": ["bonus_chain_dynamics"]
    }
  },
  "rtp_integrity_contract": {
    "expected_paid_st": [140],
    "expected_bonus_st": [139],
    "required_attribution_anchors": ["_bcm_cycle", "5801"]
  }
}
```

Basis for `true`: Validator v2 §2.6 empirical — 0 `_unattributed_*` rows, `_bcm_cycle` at 315 hits / 4.87% RTP, `5801` at 3592 hits / 54.11% RTP, sum(pid rtp_pp) = 106.34% == summary.rtp. Layer 4 v4 Step B re-verification required before Phase 3 cutover.

**M279** (heavy outlier — starts `false`):

```json
{
  "machine_id": "M279",
  "manifest_version": 1,
  "inherits_from": null,
  "console_diagnostic_complete": false,
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
    "2": {"bcm_target_feature_override": "MoveSpin", "required_attribution_anchors_override": ["_bcm_cycle"]},
    "5": {"bcm_target_feature_override": "MoveSpin", "required_attribution_anchors_override": ["_bcm_cycle"]},
    "7": {"bcm_target_feature_override": "MoveSpin", "required_attribution_anchors_override": ["_bcm_cycle"]}
  },
  "rtp_integrity_contract": {
    "expected_paid_st": [140],
    "expected_bonus_st": [2, 36],
    "required_attribution_anchors": ["_bcm_cycle", "27905"]
  }
}
```

**M273$WheelSelector$0$** (variant — inherits completeness from M273 underlying):

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

No `console_diagnostic_complete` field — resolver reads M273.json's value (cascaded eagerly). When M273 is flipped to `true`, all 85 variants automatically become strict per §5.5.7.

---

## §6 Migration plan — v4 changes

v4 keeps v3's 6 phases. The **change** in v4 is §6.3 (Phase 3 deliverables), which adds Day-1 strict candidates. Phase 2 (gate code construction) and Phase 5 (policy flip) are unchanged from v3.

### §6.1 Phase 1 — Foundation (unchanged from v2/v3)

All 12 Phase 1 deliverables from v2/v3 §6 unchanged. Resolves all 5 pre-Phase-1 blockers from `01 §5`. Risk LOW-MEDIUM; 4-6 days; trivial rollback.

### §6.2 Phase 2 — Slice analyzer + forcing function + RTP integrity gate code (unchanged from v3)

Goals and deliverables unchanged from v3 §6.2. The key v3 addition (building `fresh_slotlab/rtp_integrity.py` with all 4 layers in warn-only mode) remains. Layer 4 in Phase 2 is built per the v4 Step A/B/C algorithm (§9.4). Risk HIGH; 12-16 days.

Deliverables (abbreviated; full list in v3 §6.2):
1. Carve `core/` (4 files).
2. Carve 4 universal features.
3. Carve 9 cluster-shared features.
4. Carve 12 forcing-function bespoke features.
5. **Build `fresh_slotlab/rtp_integrity.py`** — all 4 layers (Layer 4 per v4 §9.4 Step A/B/C algorithm), runs in warn-only mode.
6. Demonstrate Example 6 workflow end-to-end on M250.
7. `fresh_slotlab/analyzer/versioning.py`.
8. `fresh_slotlab/analyzer/feature_registry.py`.
9. Per-cluster regression tests.

### §6.3 Phase 3 — Per-machine manifests + wiring + Day-1 strict candidates (v4 CHANGE ②)

**Goals (v4 update)**:
- Land 421 per-machine manifest files.
- **NEW v4**: ship Day-1 strict candidates with `console_diagnostic_complete: true`. All remaining machines ship as `false`.
- Wire `compute_effective_analyzer_version` to consult manifest per machine, per mode.
- Frontend reads manifest-driven feature list to know which renderers to invoke.
- Clean break from old reports.

#### §6.3.1 Day-1 strict candidates (v4 CHANGE ②)

The following machines ship as `console_diagnostic_complete: true` at Phase 3 cutover:

**Group A — SC-Vanilla cluster (~45 machines per `02 §4.2`)**:

Source: `02 §4.2` super-cluster table. SC-Vanilla definition: machines co-clustering across all 5 axes — ST-1A (paid=1, no bonus) / F-Plain (exact `{NormalRTPPreProcessor, NormalSpinGenerator, NormalSpinValidator}` logicClassNames) / 1-9 paylines / S-Base rawdata schema (Tier-0 keys only) / no round_win_rules entries.

Named members (rawdata-confirmed, per `02 §4.2` and `02 §3.5.3 Tier-1`): M1, M14, M37, M101, M105, M127, M13, M135, M137, M139, M142, M143, M145, plus the remaining machines with exact `{NormalRTPPreProcessor, NormalSpinGenerator, NormalSpinValidator}` logicClassNames as identified during Phase 3 manifest authoring (target: all 45 per `02 §4.2`).

**Eligibility basis**: these machines have been in production for years with no known correctness issues. No bespoke rules needed. No `_unattributed_*` rows in historical reports (per `02 §3.5.3 Tier-1`). Memory `user_testing_machine.md` confirms M14 mode 1 is the primary validation machine with precision RTP monitoring, consistent with clean Layer 1-3 behavior.

**Pre-Phase-3 verification step**: before setting `console_diagnostic_complete: true` in any SC-Vanilla manifest, the implementation team runs `rtp_integrity.py` (built in Phase 2) against each machine's most recent rawdata. All 4 layers must pass. Expected outcome: all ~45 machines pass trivially — no bonus ST, no required anchors, no bespoke rules. Layers 2/3 are vacuously clean; Layer 4 Step B scan will show single-ST dispatch with no routing complexity.

**Group B — M274 (empirically verified per Validator v2 §2.6)**:

Source: Validator v2 §2.6 live data walkthrough — "0 `_unattributed_*` entries; pid `_bcm_cycle` has 315 hits / 4.867% rtp_pp; pid `5801` has 3592 hits / 54.11% rtp_pp; Sum of all rtp_pp = 106.338125 == summary.rtp.point_pct." Both required anchors present. No fallback buckets.

**Layer 4 v4 re-verification required**: v4's Layer 4 algorithm (Step B independent rawdata scan) is a different check from v3's same-accumulator self-consistency. M274 must be re-verified under v4 Layer 4 before Phase 3 cutover. Expected outcome: pass, because the `bcm_cycle_anchor_m274` rule was added specifically to fix the dispatch routing gap. But empirical confirmation under v4 Layer 4 is required.

**Group C — Other Validator v2 walkthroughs that passed cleanly**:

Validator v2 §2 walked 8+1 cases. Additional named candidates:
- **M37** (Validator v2 §2.3): SC-Vanilla member, real-fleet layer pass confirmed. Covered by Group A.
- **M14** (Validator v2 §2.8b, cross-mode hash test): primary validation machine per memory. Covered by Group A.

Non-candidates from Validator v2 walkthroughs (explicitly excluded):
- M15 (§2.2): requires topdollar rule verification
- M99 (§2.4): known unfixed dedup bug
- M279 (§2.5): known BCM routing complexity
- M250 (§2.7): 100% RTP fallback leak
- M65 (§2.8a): collection mechanic complexity

**Estimated Day-1 count**: ~45 (Group A) + 1 (M274, pending Layer 4 re-verification) = **~46 machines** shipping `console_diagnostic_complete: true` at Phase 3 cutover. Approximately 11% of the 421-machine fleet.

#### §6.3.2 Flip criteria for future machines

A machine flips from `console_diagnostic_complete: false` → `true` when ALL of the following hold:

1. **All 4 layers PASS on representative rawdata**: run `python -m fresh_slotlab.rtp_integrity M<N> --mode <mode>` against the most recent representative rawdata sample (10k+ spins for the machine's primary mode). All 4 layers — including Layer 4 Step B rawdata scan — must return PASS.

2. **No known issue or pending rule update**: no open issue in the repo or QA backlog indicating a parser gap or pending rule addition for this machine.

3. **Audit log entry**: the flip commit message must include:
   ```
   flip console_diagnostic_complete: false → true for M<N>
   Basis: rtp_integrity all 4 layers PASS on [rawdata version tag]
   Run date: [date]
   Verified by: [role / initials]
   ```
   Git history provides the tamper-evident audit trail.

**Direction asymmetry**: a machine flips `true → false` when a regression is discovered. Any team member can flip `true → false` without ceremony — the conservative direction is always permitted. Flip `false → true` requires the 3-step criteria above.

**Variant flip**: when an underlying machine is flipped to `true`, all its variants automatically inherit `true` (per §5.5.7 cascade). The flip commit for the underlying covers all variants. A variant-specific `console_diagnostic_complete_override: false` is added if a specific variant's data reveals an edge case not present in the underlying's verification sample.

#### §6.3.3 Other Phase 3 deliverables (unchanged from v3)

1. Write 421 per-machine manifests. Day-1 candidates (§6.3.1) ship `true`; all others ship `false`.
2. `manifest_loader.py` — reads manifests, resolves `inherits_from` (eager), resolves `per_mode_overrides`, includes `resolve_completeness()` per §5.5.7.
3. Wire `compute_effective_analyzer_version` to read manifest per (machine, mode).
4. Update analyzer + backend write sites to use effective version.
5. Update `/api/reports/stale-count` to compare per-(machine, mode) `effective_analyzer_version`. No NULL handling (clean break).
6. ALTER TABLE runs ADD COLUMN effective_analyzer_version TEXT.
7. Frontend updates (`app.js`, `pure.js`): freshness and renderer-skip logic.
8. Manifest validation CLI: `scripts/validate_manifests.py`.
9. Manifest tooling: `scripts/manifest_lint.py`, `manifest_diff.py`, `manifest_audit.py`.

**Phase 3 risk**: MEDIUM; 4-7 days (v3 was 4-6; +0.5 days for Day-1 verification step).

### §6.4 Phase 4 — Frontend renderer registry + schema-version contract enforcement (unchanged from v2/v3)

All 7 Phase 4 deliverables from v2/v3 §6 unchanged. Risk LOW; 2-3 days.

### §6.5 Phase 5 — Flip RTP integrity gate default policy from warn to error (unchanged from v3)

Goals, deliverables, and risk (LOW-MEDIUM; 2-3 days) are unchanged from v3 §6.5. The key v3 deliverable is the policy flip in `rtp_integrity.py`: when `manifest.console_diagnostic_complete == true`, layer failures raise; when `== false`, warnings only.

**v4 difference at Phase 5 deployment**:
- v3: 0 machines have `console_diagnostic_complete: true` on Phase 5 day 1 → strict-error mechanism dormant.
- v4: ~46 machines have `console_diagnostic_complete: true` from Phase 3 → Phase 5 strict-error policy flip immediately engages for those ~46 machines.

Phase 5 deliverable 4 (known-broken machines triage): at Phase 5 deploy time, the operator continues flipping machines to `true` per §6.3.2 criteria. The SC-TopDollar cluster (12 variants + 5 underlying per `02 §4.2`) may be eligible early if their `topdollar_selector_settlement` rule produces clean Layer 1-4 results.

**Rollback**: revert Phase 5 commits. Gate stays in warn-only mode globally. Per-machine `true` flags in manifests remain but are not enforced as errors. No data loss.

### §6.6 Phase 6 — (Optional / out-of-scope) Retro-fit + consolidation (unchanged from v2/v3)

Optional. Phase 6 deliverables: consolidation of `machine_round_win_rules.json`, architecture docs, medium-outlier audit + flip for verified-clean machines. Risk LOW; 3-5 days.

### §6.7 Phase summary table (v4 updated)

| Phase | Risk | Days est. | Schema change | Rollback simplicity |
|---|---|---|---|---|
| 1 (dedup + globals + 5 mapper blockers) | LOW-MEDIUM | 4-6 | None | Trivial revert |
| 2 (slice analyzer + 12 forcing-function machines + RTP integrity gate code v4 Layer 4) | HIGH | 12-16 | Per-feature SCHEMA_VERSION; effective_analyzer_version; `summary.rtp_integrity_check` | Per-feature revert |
| 3 (manifests + clean-break; **v4: ~46 Day-1 candidates ship `true`**; remainder `false`) | MEDIUM | 4-7 (+0.5 for Day-1 verification) | Manifest files; new DB col | Manifest ignored on rollback |
| 4 (frontend registry + SCHEMA_VERSION enforcement) | LOW | 2-3 | None | Trivial revert |
| 5 (flip policy; **v4: policy engages for ~46 `true` machines on day 1**) | LOW-MEDIUM | 2-3 | New `integrity_failures` DB table; new badge UI | Policy flip reverts globally |
| 6 (optional retro-fit + consolidation + outlier audit) | LOW | 3-5 | None | Optional throughout |

Total: ~28-41 dev days (sequential). Comparable to v3's 27-39 days (+0.5 for Day-1 verification).

### §6.8 Migration constraint compliance (v4 updated)

| Constraint | How honored by v4 plan |
|---|---|
| **00 §5.1** Backward-compat for 393 machines' reports | Per addendum §1.2 clean-break authorization, relaxed. Operators regen from rawdata. |
| **00 §5.2** Prod console (8877) never breaks | Each phase has rollback; Phase 2 verified against 12 forcing-function machines BEFORE commit. |
| **00 §5.3** Virtual reuses prod code | Phase 1 removes 6 dups; Phase 2's features shared. |
| **00 §5.4** New machine = O(1) hash | Phase 3 manifests + Phase 2's bespoke pattern. Universal-feature changes still 1× per §1.4. |
| **00 §5.5** Rollback per phase | Documented per phase. |
| **00 §5.6** No silent data loss | Phase 2 RTP integrity gate (4 layers including v4 Layer 4) makes silent loss explicit error or warning. |
| **Addendum §1.4** RTP integrity hard constraint S | Phase 2 gate + Phase 5 policy flip + §9 reframed per addendum v3 §1. |
| **Addendum §1.5** Every machine potentially unique | Phase 3 per-machine manifests; eager variant cascade per §5.5.5. |
| **Addendum v3 §1** Operator-diagnostic framing | §9 entirely rewritten; `console_diagnostic_complete` per-machine flag; §1 problem statement rewritten. |
| **Addendum v3 §2 must-resolve #2** Layer 4 within-pid attribution | §9.4 v4 revised — independent rawdata-level Step A/B/C algorithm catches dispatch-routing bugs. |
| **Addendum v3 §2 must-resolve #3** Phase 2/5 ordering | §6.2 + §6.5 resolved (unchanged from v3). |
| **Addendum v3 §2 must-resolve #6** Per-machine completeness flag | §5.5.3 replaces v2 numeric threshold. |
| **Addendum v3 §3 #1** `inherits_from` variant justification | §5.5.4 dedicated paragraph. |
| **Addendum v3 §3 #4** Variant cascade eager | §5.5.5. |
| **Addendum v3 §4** Validator v2 doc gaps | §5.5.6 + §9.7 illustrative-not-exhaustive marker. |
| **Addendum v4 §1 Issue ①** Layer 4 must catch dispatch-routing bugs | §9.4 rewritten with Step A/B/C rawdata-level cross-check. |
| **Addendum v4 §1 Issue ②** Day-1 strict candidates enumerated | §6.3.1 names ~46 machines; §6.3.2 specifies flip criteria. |
| **Addendum v4 §1 Issue ③** Variant cascade for completeness flag | §5.5.7 rewritten — eager cascade from underlying with true→false-only override valve. |

---

## §7 Open questions for Critic v4 + Validator v4

v4 addresses all 3 issues from addendum v4 §1. Remaining open questions for Wave 3 v4:

### §7.1 Layer 4 Step B performance under fleet-pull conditions

§9.4 Step B (independent rawdata scan) is estimated at <5 seconds for 414k spins per addendum v4 §1 Issue ① perf note. For a fleet pull across 421 machines, the cumulative overhead is 421 × ~5s = ~35 minutes if all machines run sequentially. In practice, fleet pulls are parallelized per-machine subprocess; Step B runs inside the same subprocess as the main analysis pass. **Critic v4 / Validator v4 should verify**: is the ~5s estimate realistic for the chunk sizes in this fleet? Does the estimate hold for machines with larger rawdata (e.g., those with 1M+ cached spins)? The implementation team should add an `--skip-layer4-rawdata-scan` escape hatch for development workflows.

### §7.2 Layer 4 edge cases — SpinType missing or invalid

v4 §9.4 Step B specifies two edge cases: SpinType field missing (raises `Layer4Error` naming chunk + robot ID) and SpinType value invalid (raises with value and location). **Critic v4 should verify**: are these edge cases sufficient to cover the range of rawdata anomalies observed in the fleet? Are there additional edge cases (e.g., SpinType field present but integer-valued as float like `43.0`, or encoded as string `"43"`) that the pseudocode should handle explicitly?

### §7.3 Day-1 candidate verification workload

§6.3.1 targets ~46 machines for Day-1 `true` status. The verification step is estimated at 0.5 days (run the gate against ~45 SC-Vanilla + M274). **Validator v4 should verify**: is there any known SC-Vanilla machine (per `02 §4.2`) that currently has `_unattributed_*` rows in reports (Layer 2 failure), or any anchor misses (Layer 3 failure), or any dispatch routing complexity that might trip Layer 4 Step B? Given SC-Vanilla machines have no bonus ST and no required anchors, this is expected to be trivially clean, but empirical confirmation is valuable.

### §7.4 Layer 4 trigger policy — `complete: false` machines and performance

§9.5 states the integrity check (including Step B) runs on every fleet pull for all machines, with `complete: false` machines in warn-only mode. Step B adds ~5s per machine regardless of completeness flag. For 421 machines in warn-only mode, this is ~35 min of cumulative rawdata scan time across all subprocesses (parallelized). **Critic v4 should assess**: should Step B be gated to `complete: true` machines only (to avoid the extra rawdata cost for machines not yet in strict mode), or should it run for all machines (to surface dispatch issues as warnings even in `complete: false` mode, enabling earlier detection)? The proposal currently runs for all machines (consistent with "find bugs early"). If the perf cost is unacceptable, the policy can restrict Step B to `complete: true` machines with a Phase 5 policy flip option.

---

## §8 Out of scope (refined for v4)

§8.1-§8.12 unchanged from v2/v3 §8. §8.13 is updated to reflect partial specification.

### §8.13 `console_diagnostic_complete` flip mechanism — partially specified (v4 update from v3)

v3 §8.13 deferred the entire flip mechanism. v4 §6.3.2 now specifies the flip **criteria** (4-layer pass + no known issues + audit log entry) and the **direction asymmetry** (false→true requires criteria; true→false is always permitted). What remains explicitly out of scope:

- Which organizational role owns flip decisions for non-Day-1-candidate machines (QA / operator / slot-* team / arch team)
- Batch-flip tooling (e.g., a script that sweeps the fleet, identifies candidates passing all 4 layers, and generates bulk flip PRs)
- Scheduled re-verification cadence (e.g., weekly re-run of the gate for all `true` machines to catch regressions)

These are operational concerns for the implementation team. v4 specifies the criteria and audit format; organizational ownership and tooling build are out of scope.

---

## §9 Operator diagnostic signal — Console's RTP integrity output (v4 CHANGE ① in §9.4)

Sections §9.1 through §9.3 and §9.5 through §9.8 are unchanged from v3. The v4 change is entirely in **§9.4**, which replaces v3's same-accumulator Layer 4 algorithm with an independent rawdata-level cross-check.

### §9.1 Purpose (unchanged from v3)

The console exists to help the operator (策划) find issues in production machine configurations they themselves wrote. Production machines faithfully execute the operator's configuration. Rawdata reflects that configuration. The console's job is to analyze rawdata correctly and tell the operator whether the result matches intent.

**When the console cannot reliably analyze a machine, it must surface that to the operator with actionable diagnosis hints — not silently fall back to wrong numbers.**

Memory `feedback_invariant_with_fallback_hides_drift.md` documents the failure mode: "55 of 117 cached BCM (machine, mode) pairs have >0.5% RTP falling into the `_unattributed_st<N>` fallback bucket". The 4-layer check makes these explicit signals rather than silent leaks.

Memory `feedback_no_silent_swallow.md` documents the broader principle: any best-effort post-hook's outcome must persist to disk. The integrity check result is persisted per-run (DB + summary); never silently swallowed.

### §9.2 The 4-layer integrity check — Layers 1, 2, 3 (unchanged from v3)

For every (machine, mode) analyzer run, the gate computes 4 layers and produces a structured result.

#### Layer 1 — Hard invariant (unchanged from v2/v3)

```
sum(payout_id_win[pid] for all pid) == chunk_win  (across all chunks)
```

If this fails, the analyzer's arithmetic is wrong. Layer 1 catches pure arithmetic / accumulator bugs.

#### Layer 2 — Fallback-bucket non-existence (unchanged from v3)

```
No payout_id starts with "_unattributed_", "_other", "_default", or "_misc".
```

**Any fallback-bucket row** is the signal that the console couldn't attribute some win to a real pay_id. No statistical threshold. The reserved fallback prefix list: `_unattributed_`, `_other`, `_default`, `_misc`.

#### Layer 3 — Attribution-anchor coverage (unchanged from v2/v3)

Per manifest, every machine declares `required_attribution_anchors` — a list of pay_ids that MUST appear in the summary (with > 0 hits) if the machine's mechanic is functioning correctly.

- M274's manifest requires `["_bcm_cycle", "5801"]` — both must have hits.
- M15's manifest requires `["666"]`.
- A vanilla machine like M1 may have `[]` (no required anchors — vacuously passes).

If any required anchor has 0 hits, Layer 3 fires.

#### Combined check structure (unchanged from v3)

```python
@dataclass
class RTPIntegrityResult:
    machine: str
    mode: int
    passed: bool
    layer1_invariant_ok: bool
    layer1_error: str | None
    layer2_no_fallback_buckets_ok: bool
    layer2_fallback_buckets_found: list[str]
    layer3_anchors_ok: bool
    layer3_missing_anchors: list[str]
    layer4_per_st_consistency_ok: bool         # v4: rawdata-level cross-check
    layer4_inconsistencies: list[dict]         # v4: one entry per (pid, ST) mismatch
    summary_message: str
    suggested_actions: list[str]
    completeness_declared: bool                # mirrors manifest.console_diagnostic_complete
```

A machine **passes** only if all 4 layers pass.

### §9.3 Per-machine error format (unchanged from v3)

The JSON error format and human-readable CLI format are identical to v3 §9.3. The Layer 4 inconsistency entry format is updated to reflect the v4 rawdata-level discrepancy — each entry includes:

```json
{
  "pay_id": 8,
  "spin_type": 43,
  "analyzer_dispatch_count": 33167,
  "rawdata_observed_count": 22370,
  "difference": 10797,
  "note": "Analyzer dispatched 10797 more rounds to ST=43 than rawdata shows. Possible cause: dispatch rule for ST=44 (free spin) is attributing those rounds to paid-spin bucket."
}
```

`analyzer_dispatch_count` = from Step A (analyzer's `payout_id_by_spin_type_total`). `rawdata_observed_count` = from Step B (independent rawdata scan). A non-zero `difference` is the dispatch routing bug that v3's Layer 4 could not detect.

### §9.4 Layer 4 — Dispatch routing self-consistency via rawdata cross-check (v4 REWRITE, Change ①)

**Why v3's Layer 4 failed**: v3 §9.2 Layer 4 compared `payouts_by_spin_type[label].rows[pid].hit_count` against `payout_ids_top20.rows[pid].spin_type_breakdown[N].count`. Critic v3 Concern 2 verified (by reading `player_impact_analyzer.py:6438-6509`) that both fields read from the same in-memory dict `payout_id_by_spin_type_total`:

- Line 6493 (`payouts_by_spin_type` path) reads `payout_id_by_spin_type_total[str(pid)][st_int]`
- Line 6446 (`payout_ids_top20` spin_type_breakdown path) reads `st_hits = payout_id_by_spin_type_total[str(pid)]`

They are not two independent derivations — they are two readouts of the same dict. If the dict is populated with a dispatch bug, both sides are equally wrong. v3's Layer 4 is a self-consistency check, not a correctness check. It catches "emitter-level inconsistency" (two presentation slices of the same dict diverge) but NOT "dispatch-routing bug" (wrong values in the shared dict).

**The motivating case (M31 pid-8 style, per addendum v3 §2 must-resolve #2)**:

- Rawdata: pid 8 fires 33,167 times total — 22,370 rounds with SpinType=43 (paid), 10,797 rounds with SpinType=44 (free)
- Dispatch bug: the analyzer's `parse_chunk_response` routes the 10,797 ST=44 rounds into the ST=43 bucket: `payout_id_by_spin_type_total["8"][43] = 33167` (wrong), `payout_id_by_spin_type_total["8"][44] = 0` (wrong)
- v3 Layer 4: reads `payouts_by_spin_type[ST43].rows[8].hit_count = 33167` AND `payout_ids_top20.rows[8].spin_type_breakdown[43].count = 33167` → they agree → Layer 4 PASSES → bug invisible
- v4 Layer 4 Step B: counts rawdata rounds independently → `fresh_dispatch[8][43] = 22370`, `fresh_dispatch[8][44] = 10797`
- v4 Layer 4 Step C: `analyzer_dispatch[8][43] = 33167 ≠ fresh_dispatch[8][43] = 22370` → **Layer 4 FAILS**, mismatch reported

**The Step A / B / C algorithm**:

```
Layer 4 (v4 revised): Dispatch routing self-consistency via rawdata cross-check

For each (machine, mode) being analyzed — runs as part of rtp_integrity.py:

  Step A — Capture analyzer's dispatch result:
    # Source: payout_id_by_spin_type_total built during parse_chunk_response
    # This dict drives both payouts_by_spin_type AND spin_type_breakdown
    analyzer_dispatch = {}   # dict[pid, dict[st_int, count]]
    for pid_str, st_counts in payout_id_by_spin_type_total.items():
        pid = int(pid_str) if pid_str.isdigit() else pid_str
        analyzer_dispatch[pid] = dict(st_counts)   # copy; int ST keys

  Step B — Independent fresh scan of rawdata chunks:
    fresh_dispatch = {}   # dict[pid, dict[st_int, count]]
    # Iterate ALL chunk files independently — do NOT call any analyzer function.
    for chunk_path in sorted(rawdata_dir.glob("chunk_*.json")):
        chunk = json.loads(chunk_path.read_bytes())
        for robot_response in chunk["response"]:
            for round_result in robot_response.get("roundResult", []):

                # Edge case: SpinType field missing → data corruption
                raw_st = round_result.get("SpinType")
                if raw_st is None:
                    raise Layer4Error(
                        f"SpinType field missing in round at "
                        f"{chunk_path}:{robot_response['robotId']}. "
                        f"Possible cause: data corruption or rawdata envelope version drift."
                    )
                try:
                    st = int(raw_st)
                except (TypeError, ValueError):
                    raise Layer4Error(
                        f"SpinType field invalid (value={raw_st!r}) at "
                        f"{chunk_path}:{robot_response['robotId']}."
                    )

                # Extract pids fired this round (0-win-but-fired pids included
                # per 4cbcab2 fix — count existence in PayoutIdToWinAmount.keys())
                payout_id_to_win = round_result.get("PayoutIdToWinAmount", {})
                for pid_str in payout_id_to_win.keys():
                    try:
                        pid = int(pid_str)
                    except (TypeError, ValueError):
                        pid = pid_str   # keep as string for non-numeric pids

                    if pid not in fresh_dispatch:
                        fresh_dispatch[pid] = {}
                    fresh_dispatch[pid][st] = fresh_dispatch[pid].get(st, 0) + 1

  Step C — Compare:
    inconsistencies = []
    all_pids = set(analyzer_dispatch.keys()) | set(fresh_dispatch.keys())
    for pid in all_pids:
        a_sts = analyzer_dispatch.get(pid, {})
        f_sts = fresh_dispatch.get(pid, {})
        all_sts = set(a_sts.keys()) | set(f_sts.keys())
        for st in all_sts:
            a_count = a_sts.get(st, 0)
            f_count = f_sts.get(st, 0)
            if a_count != f_count:
                inconsistencies.append({
                    "pay_id": pid,
                    "spin_type": st,
                    "analyzer_dispatch_count": a_count,
                    "rawdata_observed_count": f_count,
                    "difference": a_count - f_count,
                    "note": (
                        f"Analyzer dispatched {a_count} round(s) with pid={pid} to ST={st}; "
                        f"rawdata shows {f_count}. "
                        f"Possible causes: (a) dispatch rule routes these rounds to wrong ST bucket / "
                        f"(b) session-bonus grouping re-attributes free-spin rounds to paid-spin bucket / "
                        f"(c) round_classification primitive mismatch for ST={st}. Investigate."
                    )
                })

    if inconsistencies:
        result.layer4_per_st_consistency_ok = False
        result.layer4_inconsistencies = inconsistencies
    else:
        result.layer4_per_st_consistency_ok = True
        result.layer4_inconsistencies = []
```

**Why this catches M31 pid-8 bug that v3 missed**: Step B re-derives (pid, ST) counts from the raw chunk data, bypassing the analyzer's dispatch path entirely. The M31 dispatch bug puts wrong values into `payout_id_by_spin_type_total` during `parse_chunk_response`. Both of v3's Layer 4 readers consumed the wrong dict and agreed. v4's Step B reads rawdata `SpinType` field directly — it sees 22,370 rounds with pid=8, ST=43 and 10,797 rounds with pid=8, ST=44. Step C exposes the mismatch immediately.

**Performance note**:

Step B adds one full pass through rawdata chunks. Per addendum v4 §1 Issue ① the estimate is <5 seconds for 414k spins on local disk. Key assumptions:

- Chunks are already on local disk (the main analysis pass downloaded them; Step B reads the same cached files).
- The loop is sequential JSON iteration with no heavy computation.
- Parallelism is inherited from the existing per-machine subprocess model: Step B runs inside the same `pia.main` subprocess.

For machines with very large rawdata (multi-million spins), Step B cost scales linearly. The implementation team should add a `--skip-layer4-rawdata-scan` escape hatch for development workflows, with a warning that Layer 4 will be degraded to a no-op in that mode. This flag should never be enabled for production fleet pulls.

**Trigger policy**:

Per §9.5, the integrity check runs on every fleet pull for all machines. Step B runs as part of Layer 4 for all machines — `complete: true` machines in strict mode, `complete: false` machines in warn-only mode. Running Step B for all machines (not just `complete: true`) provides early detection of dispatch-routing bugs before a machine is declared complete. Operators see warnings on `complete: false` machines with dispatch issues, enabling earlier investigation.

**Edge cases**:

| Edge case | Handling in Step B |
|---|---|
| `SpinType` field missing from a round | Raises `Layer4Error` with chunk path + robot ID + "data corruption" hypothesis. Layer 4 fails with specific error. |
| `SpinType` field present but value not in `expected_paid_st ∪ expected_bonus_st` | Counted into `fresh_dispatch` under the unexpected ST value. Step C comparison either finds a matching entry in `analyzer_dispatch` (dispatch handles unknown STs consistently) or reports a mismatch. The `note` field hints at "manifest's spin_type_convention may be incomplete". |
| `PayoutIdToWinAmount` field missing from a round | The round had no payouts (zero-win spin). Step B skips it (no pids to count). Consistent with analyzer's main pass behavior. |
| Round has pid with `win = 0` (fired but zero payout) | Step B counts the pid regardless of win amount — existence in `PayoutIdToWinAmount.keys()` is sufficient. Consistent with the `4cbcab2` fix ("retain 0-win-but-fired pids like M31 pid 666" per `00_brief.md §3` commit table). |
| Chunk file has malformed JSON | Step B raises `json.JSONDecodeError`; integrity check fails with data corruption note. |
| Machine has no rawdata cached (0 chunks on disk) | Step B detects "no rawdata chunks found" before iterating and emits specific error: "Layer 4 cannot run: no rawdata chunks found for this (machine, mode). Possible cause: rawdata not yet sampled or deleted." Layer 4 fails explicitly, not silently. |

### §9.5 When the check runs (unchanged from v3)

| Trigger | When integrity check runs |
|---|---|
| Live sampling via `POST /api/runs` | At end-of-run, before summary write |
| In-process replay via `POST /api/rawdata/{m}/generate-report` | After `pia.main()` returns |
| Batch generate-report `POST /api/rawdata/batch-generate-report` | Per item, after each subprocess run |
| Fleet-wide cron pull (e.g., nightly refresh) | Per machine after analyzer completes |
| On-demand fleet check `POST /api/runs/integrity-check-all` | Iterates all (machine, mode) with recent reports |
| Manifest validation `scripts/validate_manifests.py` | Static-only checks (no rawdata); flags machines whose `console_diagnostic_complete: true` is set without all RTP_CONTRIBUTION=True features |

The integrity check is **mandatory** — there is no flag to disable it globally.

### §9.6 Interaction with manifest validation (unchanged from v3)

- **Layer 2 fails**: manifest claims declared features cover this machine, but fallback buckets appeared. Operator: add/fix features or keep `complete: false`.
- **Layer 3 fails**: manifest claims anchor X should appear, but it didn't. Usually means the round_win_rule that synthesizes X isn't applied.
- **Layer 4 fails**: Step C found `analyzer_dispatch[pid][st] ≠ fresh_dispatch[pid][st]`. The analyzer's dispatch logic has a routing bug at rawdata level. Operator: investigate `round_classification` rules for the mismatched ST + trigger-session pattern declaration. The `note` field in the inconsistency entry provides the starting hypothesis.

The check IS the enforcement mechanism for manifest correctness. A manifest is "correct" iff the integrity check passes for that machine on representative rawdata.

### §9.7 Known-broken machines triage — Illustrative, not exhaustive — comprehensive list maintained by QA team (unchanged from v3 §9.7)

**This table is illustrative of the failure modes; it is NOT an exhaustive list. The comprehensive triage list is maintained by the QA team during the Phase 5 default-policy flip rollout.**

| Machine | Mode | Symptom | Failure layer (under v4 gate) | Phase 5 / QA action |
|---|---|---|---|---|
| M250 | 1 | ~100% RTP in `_unattributed_st139` | Layer 2 + Layer 3 (missing `_bcm_cycle`) | Bespoke feature `bespoke_m250_grid.py` in Phase 2. Flip after verified. |
| M268 | 1 | ~70-90% fallback | Layer 2 + likely Layer 3 | Bespoke feature `bespoke_m268_credits_symbol.py` in Phase 2. Flip after verified. |
| M260 | 1 | ~70-90% fallback | Layer 2 + likely Layer 3 | Bespoke feature `bespoke_m260_buffs.py` in Phase 2. Flip after verified. |
| M264 | 1 | ~70-90% fallback | Layer 2 + likely Layer 3 | Enable `cycle_peak_detection` in manifest; verify. |
| M163 | 1 | ~35% fallback | Layer 2 | Enable `cycle_peak_detection`; verify. |
| M147 | 1 | ~35% fallback | Layer 2 | Enable `cycle_peak_detection`; verify. |
| M274 | 1 | Resolved via `bcm_cycle_anchor_m274`; Layers 1-3 PASS per Validator v2 §2.6 | Layer 4 v4 re-verification pending before Phase 3 cutover | Day-1 strict candidate per §6.3.1 Group B — verify Layer 4 Step B before setting `true`. |
| M99 / M112 | (varied) | Sub-round dedup defect | Likely Layer 1 or Layer 4 | Add dedup rule per `lock_symbol_handling` feature; verify. |
| ~16-21 additional BCM machines | (varied) | 0.5-35% fallback share | Layer 2 | QA team's fleet sweep during Phase 5 rollout identifies them. |

### §9.8 Memory cross-reference (unchanged from v3)

- `feedback_invariant_with_fallback_hides_drift.md`: fallback buckets must be alerts, not silent accounting mechanisms. v4 Layer 4 Step B catches dispatch mis-routing that v3's same-accumulator check missed.
- `feedback_no_silent_swallow.md`: integrity check results persisted per-run (DB + summary); never silently swallowed.
- Addendum v3 §1: "Console must analyze rawdata correctly so its diagnostic signals are trustworthy." v4 §9 is the architectural implementation.

---

## §10 Resolution map — addendum v4 changes + residual items

### §10.1 Addendum v4's 3 issues — where v4 addresses each

| # | Issue | v4 resolution |
|---|---|---|
| ① | Layer 4 algorithm doesn't catch dispatch-routing bugs (Critic v3 Concern 2, HARD) | §9.4 entirely rewritten with Step A/B/C rawdata-level cross-check. Step B independently iterates rawdata chunks without going through `payout_id_by_spin_type_total`. Step C compares against Step A's dispatch result. Catches M31 pid-8 class bug that v3's same-accumulator check missed because both v3 readers consumed the same wrong dict. |
| ② | Day-1 strict mode ships with zero members (Critic v3 Concern 1, HARD) | §6.3 Phase 3 deliverable enumerates explicit Day-1 strict candidates: SC-Vanilla ~45 machines (per `02 §4.2`) + M274 (per Validator v2 §2.6 empirical pass, pending Layer 4 v4 re-verification). §6.3.2 specifies flip criteria. Phase 5 policy flip engages immediately for ~46 machines. |
| ③ | Variant cascade asymmetry (Critic v3 Concern 3, SOFT) | §5.5.7 rewritten. Completeness flag cascades eagerly from underlying to variants (matching §5.5.4/§5.5.5 eager cascade for parser features). Override allowed only `true → false` (regression valve); never `false → true`. Resolver logic specified. Validation rejects `console_diagnostic_complete_override: true` on variant manifests. |

### §10.2 Validator v2 2 minor doc gaps (unchanged from v3)

| Gap | v3/v4 fix |
|---|---|
| §5.5 enumerate which manifest fields support `per_mode_overrides` | v3 §5.5.6 explicit table (unchanged in v4). |
| §9.7 mark known-broken triage table as "illustrative, not exhaustive" | v3/v4 §9.7 prefix: "Illustrative, not exhaustive — comprehensive list maintained by QA team". |

### §10.3 Items NOT in v4's scope (per addendum v4 §2)

- Variants design (`inherits_from`) — kept; §5.5.4 justification unchanged.
- Eager cascade for `analyzer_features` — resolved in v3; unchanged in v4.
- Phase 5 ships before Phase 6 BCM audits — accepted by user; unchanged.
- Hash composition algorithm — validated by Wave 3 v2; unchanged.
- Operator-diagnostic framing in §1 + §9.1 — unchanged from v3.
- Layers 1-3 of integrity check — unchanged from v3.
- `console_diagnostic_complete` mechanism core — unchanged; v4 only changes cascade and Day-1 candidates.

---

## §11 Closing

v4 is a focused 3-issue revision of v3 that:

1. **Rewrites Layer 4** (§9.4) with an independent rawdata-level Step A/B/C cross-check that catches dispatch-routing bugs. Critic v3 proved v3's same-accumulator check was trivially-true for any dispatch-consistent but dispatch-wrong analyzer. v4's Step B bypasses the analyzer's dispatch dict entirely, reading rawdata `SpinType` and `PayoutIdToWinAmount` fields directly.

2. **Enumerates Day-1 strict candidates** (§6.3.1) — ~46 machines shipping `console_diagnostic_complete: true` at Phase 3 cutover (SC-Vanilla ~45 + M274), with explicit flip criteria (§6.3.2). Phase 5's strict-error mechanism engages on day one for these machines.

3. **Makes variant completeness cascade consistent** (§5.5.7) with the §5.5.4 "variants ARE the same machine" thesis. Variants inherit `console_diagnostic_complete` from their underlying. Override allowed only `true → false` (regression valve). Validation rejects `override: true` on variant manifests.

The proposal preserves v2's validated parts (hash composition, manifest schema baseline, Plugin Protocol, 6-phase migration framework), v3's operator-diagnostic framing (§1, §9.1), v3's Layers 1-3 (§9.2), and v3's Phase 2 gate-code construction (§6.2). The 3 v4 changes are surgical and targeted.

Expected next step: Critic v4 + Validator v4 in parallel (per addendum v4 §5). Critic v4 verifies the 3 issues are addressed cleanly and no new structural regressions are introduced. Validator v4 re-walks key cases, specifically verifying v4 Layer 4 catches a synthetic dispatch mismatch.

---

```
arch-designer complete.
- Version: v4
- Alternatives explored: 3 (A v4 recommended; B rejected — no per-machine completeness signal or rawdata cross-check; C rejected — no sharing, incompatible with variant cascade)
- Recommended: Alternative A v4 — per-machine manifests + sliced analyzer + operator-diagnostic 4-layer integrity check (Layer 4 rawdata cross-check Step A/B/C) + Day-1 strict candidates (~46 machines) + consistent variant completeness cascade
- Hash composition: per-(machine, mode) effective_analyzer_version = sha256(base_hash || sorted(feature_hashes_M_uses) || mode)[:12] (unchanged from v2/v3)
- Migration phases: 6 (1 foundation+globals, 2 slice-analyzer+forcing-function+gate-code-v4-Layer4, 3 manifests+clean-break+46-Day1-candidates, 4 frontend-registry, 5 policy-flip-engages-day1-for-46-machines, 6 optional-consolidation)
- v4 changes addressed: 3/3 (① Layer 4 rawdata cross-check / ② Day-1 strict candidates + flip criteria / ③ variant completeness cascade)
- Out-of-scope items: 13 + §8.13 partially-specified
- Open questions for Wave 3 v4: 4 (§7.1 Step B perf grounding / §7.2 Layer 4 edge cases / §7.3 Day-1 candidate verification workload / §7.4 Step B trigger policy for complete:false machines)
- Output: session_artifacts/_arch/04_architecture_proposal_v4.md
```
